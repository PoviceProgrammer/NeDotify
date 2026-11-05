// Shipped UI/modules and real Canvas/Web Audio in headless Chromium, no native app/profile.
const {chromium}=require('playwright-core');
const fs=require('node:fs'), path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..','ui');
const server=http.createServer((req,res)=>{
    const name=new URL(req.url,'http://localhost').pathname;
    const file=path.resolve(root,name.startsWith('/MACos_ui/')?'.'+name:'web_new_v2/'+(name==='/'?'index.html':name.slice(1)));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body=fs.readFileSync(file);
    if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace('</head>',['/css/components/settings-refresh.css','/MACos_ui/tokens.css','/MACos_ui/interface.css','/MACos_ui/settings.css'].map(h=>`<link rel="stylesheet" href="${h}">`).join('')+'</head>');
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
    try{
        for(const style of ['current','macos','macos-light']){
            const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
            page.setDefaultTimeout(5000);page.on('pageerror',e=>errors.push(e.message));
            await page.goto(`http://127.0.0.1:${server.address().port}`);
            await page.addScriptTag({url:'/js/lucide.min.js'});
            await page.evaluate(async style=>{
                document.getElementById('app-splash')?.remove();
                document.documentElement.dataset.uiStyle=style.startsWith('macos')?'macos':'current';
                document.documentElement.dataset.macosMode=style==='macos-light'?'light':'dark';
                window.engine=await import('/js/atmosphere-engine.js');window.player=await import('/js/player.js');
                window.settingsModule=await import('/js/settings.js');window.pages=await import('/js/pages.js');window.utils=await import('/js/utils.js');
                window.atmosphereSettings=await import('/js/atmosphere-settings.js');window.discordSettings=await import('/js/discord-settings.js');
                window.settings={atmosphere:structuredClone(engine.ATMOSPHERE_DEFAULTS),app:{discord_rpc_enabled:false},optimization:{performance_preset:'balanced',resource_particles:false},ui:{particles_enabled:false}};
                window.saved=[];window.failNext=false;
                window.pywebview={api:{
                    save_setting(key,value,category){if(window.failNext){window.failNext=false;return Promise.resolve(false);}window.saved.push([category,key,structuredClone(value)]);return Promise.resolve(true);},
                    toggle_discord_rpc(enabled){return Promise.resolve({success:true,enabled});},
                    get_discord_rpc_status(){return Promise.resolve({enabled:window.settings.app.discord_rpc_enabled,connected:window.settings.app.discord_rpc_enabled,state:window.settings.app.discord_rpc_enabled?'CONNECTED':'DISABLED'});}
                }};
                engine.setAtmosphereAudioProvider(player.getAtmosphereAudioSource);
                const settingsPanel=await import('/js/settings-panel.js');settingsPanel.initSettings();
                pages.initPages();pages.showPage('library');
                const marker=document.createElement('input');marker.id='preserved-page-state';marker.value='keep this';document.getElementById('view-library').append(marker);marker.focus();
                pages.showPage('settings');
                document.querySelector('.settings-nav-btn[data-panel="atmosphere"]').click();
            },style);
            const card=page.locator('#view-settings .settings-modal-card');
            await card.waitFor({state:'visible'});
            const box=await card.boundingBox();assert.ok(box.x>20&&box.y>30&&box.width<1280&&box.height<850,'settings floats within the window');
            assert.equal(await page.locator('#view-library').evaluate(el=>el.inert),true);
            assert.equal(await page.evaluate(()=>player.getAtmosphereAudioSource().context),null,'opening settings/weather never initializes audio');
            await page.locator('#settings-search').fill('снежинок');await page.waitForTimeout(180);
            assert.equal(await page.locator('#settings-atmosphere').evaluate(el=>el.hidden),false,'new weather controls are indexed by settings search');
            assert.equal(await page.locator('#settings-search-empty').evaluate(el=>el.hidden),true);
            await page.locator('#settings-search').fill('');await page.waitForTimeout(180);
            await page.locator('#toggle-atmosphere').click();
            await page.waitForFunction(()=>window.settings.atmosphere.enabled&&engine.getAtmosphereStatus().rendering);
            assert.equal(await page.locator('#atmosphere-canvas').count(),1);
            assert.equal(await page.locator('#particles-bg').evaluate(el=>getComputedStyle(el).display),'block','macOS does not hide the atmosphere host');
            for(const effect of ['fog','thunderstorm','snow'])await page.locator(`[data-atmosphere-effect="${effect}"]`).click();
            const snapshots=path.resolve(__dirname,'..','docs','screenshots','atmosphere-20261030');fs.mkdirSync(snapshots,{recursive:true});
            await page.locator('.settings-panels').evaluate(el=>el.scrollTop=0);
            await page.screenshot({path:path.join(snapshots,`${style}.png`)});
            assert.equal(await page.locator('#atmosphere-canvas').count(),1,'four layers share one canvas');
            assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().audioArmed),false,'restored preferences never authorize sound');
            const thunder=page.locator('[data-atmosphere-key="storm.thunder"]');
            await thunder.evaluate(el=>el.closest('details').open=true);await thunder.check();
            assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().audioArmed),true,'explicit thunder gesture arms the already configured effect');
            await thunder.uncheck();assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().audioArmed),false);
            await page.evaluate(()=>window.failNext=true);
            await page.locator('[data-atmosphere-effect="fog"]').click();
            await page.waitForFunction(()=>window.settings.atmosphere.effects.fog===true);
            assert.equal(await page.locator('[data-atmosphere-effect="fog"]').getAttribute('aria-pressed'),'true','failed save rolls back the effect');
            const rain=page.locator('[data-atmosphere-key="rain.speed"]');
            await rain.evaluate(el=>el.closest('details').open=true);
            await rain.fill('1.75');await rain.dispatchEvent('change');
            await page.waitForFunction(()=>window.saved.some(row=>row[1]==='rain'&&row[2].speed===1.75));
            // A child native dialog must close first; the underlying page is still inert.
            await page.evaluate(()=>{const d=document.createElement('dialog');d.id='nested-atmosphere-dialog';d.innerHTML='<button>Nested</button>';document.body.append(d);d.showModal();utils.openModalFocusTrap(d);});
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('#nested-atmosphere-dialog').evaluate(el=>el.open),false);
            assert.equal(await page.locator('#view-settings').evaluate(el=>el.classList.contains('active')),true);
            await page.keyboard.press('Escape');
            await page.waitForFunction(()=>!document.getElementById('view-settings').classList.contains('active'));
            assert.equal(await page.locator('#view-library').evaluate(el=>el.inert),false);
            assert.equal(await page.locator('#preserved-page-state').inputValue(),'keep this');
            assert.equal(await page.locator('#preserved-page-state').evaluate(el=>el===document.activeElement),true);
            await page.evaluate(()=>{document.documentElement.classList.add('window-hidden');document.dispatchEvent(new CustomEvent('nedotify:window_visibility_changed'));});
            assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().rendering),false);
            await page.setViewportSize({width:640,height:760});
            const compact=await card.boundingBox();assert.ok(compact.x>=0&&compact.y>=20&&compact.x+compact.width<=641&&compact.height<740,'floating settings stays inside a compact window');
            await page.evaluate(()=>{document.documentElement.classList.remove('window-hidden');document.dispatchEvent(new CustomEvent('nedotify:window_visibility_changed'));pages.showPage('settings');document.querySelectorAll('.settings-panel').forEach(node=>{const active=node.id==='settings-appearance';node.classList.toggle('active',active);node.style.display=active?'block':'none';});});
            assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().rendering),true);
            await page.locator('#toggle-discord-rpc').click();
            await page.waitForFunction(()=>window.settings.app.discord_rpc_enabled===true);
            await page.waitForFunction(()=>document.getElementById('discord-connection-status').dataset.state==='CONNECTED');
            await page.locator('.discord-options').evaluate(el=>el.open=true);
            await page.locator('[data-discord-option="discord_show_cover"]').uncheck();
            await page.waitForFunction(()=>window.saved.some(row=>row[1]==='discord_show_cover'&&row[2]===false));
            // Reuse the real Web Audio graph for synthetic frequency integration.
            await page.evaluate(()=>{player.setEq(0,Array(10).fill(0));const source=player.getAtmosphereAudioSource();window.contextBefore=source.context;window.analyserBefore=source.analyser;});
            assert.equal(await page.evaluate(()=>{for(let i=0;i<50;i++)player.getAtmosphereAudioSource();return player.getAtmosphereAudioSource().context===contextBefore&&player.getAtmosphereAudioSource().analyser===analyserBefore;}),true);
            const bands=await page.evaluate(async()=>{
                const context=contextBefore,analyser=analyserBefore,previousSmoothing=analyserBefore.smoothingTimeConstant;
                analyser.smoothingTimeConstant=0;
                await context.resume();
                const oscillator=context.createOscillator(),gain=context.createGain();
                gain.gain.value=.15;oscillator.connect(gain);gain.connect(analyser);oscillator.start();
                const results=[];
                try{
                    for(const frequency of [190,1500,7500]){
                        oscillator.frequency.setValueAtTime(frequency,context.currentTime);
                        const bins=new Uint8Array(analyser.frequencyBinCount),targetBin=Math.round(frequency*analyser.fftSize/context.sampleRate);
                        for(let attempt=0;attempt<45;attempt++){
                            await new Promise(resolve=>requestAnimationFrame(resolve));
                            analyser.getByteFrequencyData(bins);
                            let peak=0;for(let i=1;i<bins.length;i++)if(bins[i]>bins[peak])peak=i;
                            if(Math.abs(peak-targetBin)<=1&&bins[peak]>150)break;
                        }
                        const signal=new engine.AtmosphereSignal(),config=engine.normalizeAtmosphere({smoothing:0,max_reaction:1});
                        for(let i=0;i<30;i++)signal.sample({context,analyser,playing:true,hasTrack:true},config,.1);
                        results.push({...signal.value});
                    }
                }finally{oscillator.stop();oscillator.disconnect();gain.disconnect();analyser.smoothingTimeConstant=previousSmoothing;}
                return results;
            });
            assert.ok(bands[0].low>bands[0].mid&&bands[1].mid>bands[1].low&&bands[2].high>bands[2].low,`real shared analyser distinguishes synthesized bass, mids and treble: ${JSON.stringify(bands)}`);
            await page.evaluate(()=>{engine.configureAtmosphere({...window.settings.atmosphere,enabled:false});});
            assert.equal(await page.locator('#atmosphere-canvas').count(),0);
            assert.equal(await page.evaluate(()=>engine.getAtmosphereStatus().rendering),false);
            assert.deepEqual(errors,[]);
            await page.close();
            console.log(`${style}: floating settings, effects, save/rollback, nesting, visibility, audio reuse and Discord controls passed`);
        }
    }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
