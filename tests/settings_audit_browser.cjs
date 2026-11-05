// Shipped settings modules, fresh browser contexts and an isolated bridge.
// Run with the bundled node_modules directory in NODE_PATH.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..', 'ui');
const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const name = decodeURIComponent(url.pathname);
    const file = path.resolve(root, name.startsWith('/MACos_ui/') ? '.' + name : `web_new_v2/${name === '/' ? 'index.html' : name.slice(1)}`);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404);res.end();return; }
    let body = fs.readFileSync(file);
    if (file.endsWith('index.html')) body = body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', '<link rel="stylesheet" href="/css/components/settings-refresh.css"><link rel="stylesheet" href="/css/components/ui-style-picker.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/settings.css"></head>');
    res.setHeader('Content-Type', {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)] || 'application/octet-stream');res.end(body);
});
const fixture = () => ({theme:{theme:'ocean',theme_mode:'dark',font_size:18,font_family:'Arial, sans-serif',glass_blur:23,transparency_enabled:true,transparency_level:65,bg_blur:4,bg_dim:0,custom_themes:[]},
    interface:{ui_style:'current',macos_mode:'dark',macos_font_size:17,macos_font_family:'Georgia, serif',macos_blur:32,border_radius:18},
    ui:{particles_enabled:false,particles_count:43,particles_size:4,particles_speed:3,particles_shape:'star',cover_visualizer:false},
    audio:{crossfade_enabled:true,crossfade_duration_sec:8,gapless_playback:false,volume_normalization:false,autoplay:true,visualizer_style:'wave'},
    app:{discord_rpc_enabled:false},storage:{cache_quota_gb:10,auto_download_favorites:false,auto_download_favorites_quota_gb:30},
    lyrics:{enabled:false,mode:'line',animations:'reduced'},services:{lastfm_enabled:false,youtube_enabled:false,soundcloud_enabled:true},auth:{browser_cookies:'firefox',cookies_file_path:'C:/test/cookies.txt',has_yandex_token:true},
    efficiency:{unfocus_enabled:true,unfocus_fps_limit:10},optimization:{performance_preset:'balanced',blur_quality:'hq',glow_quality:'subtle',resource_blur:true,resource_particles:false,resource_visualizers:false,fps_ui:50,fps_particles:17,fps_visualizer:35},player:{queue_autopilot:false,flow_enabled:false,aura_orbs_enabled:false}});
(async () => {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const browser = await chromium.launch({headless:true});
    const screenshots = path.resolve(__dirname,'..','docs','screenshots','settings-controls-20261030');
    fs.mkdirSync(screenshots,{recursive:true});
    const failures = [], errors = [], calls = [];
    const {settingAliases} = await import('data:text/javascript,' + encodeURIComponent(fs.readFileSync(path.join(root,'web_new_v2','js','setting-aliases.js'),'utf8')));
    let state = fixture(), rejectKey = '';
    async function mount({style='current', stale=false, width=1100}={}) {
        const context = await browser.newContext({viewport:{width,height:800}});
        await context.route(/^https?:\/\/(?!127\.0\.0\.1)/, route => route.abort());
        const page = await context.newPage();
        page.setDefaultTimeout(5000);
        page.on('pageerror', error => errors.push(error.message));
        await page.exposeFunction('settingsRead', () => structuredClone(state));
        await page.exposeFunction('settingsWrite', (key,value,category) => {
            calls.push([key,value,category]);if (key === rejectKey) return false;
            for(const [cat,name] of settingAliases(category,key)){state[cat] ||= {};state[cat][name] = value;}return true;
        });
        await page.addInitScript(({style,stale}) => {
            window.pywebview={api:{get_settings:()=>window.settingsRead(),save_setting:(...args)=>window.settingsWrite(...args),get_zapret_status:async()=>({running:false}),get_storage_info:async()=>({}),toggle_discord_rpc:async value=>({success:await window.settingsWrite('discord_rpc_enabled',value,'app')}),set_cache_quota:async value=>({success:await window.settingsWrite('cache_quota_gb',value,'storage')})}};
            window.awaitBridge=async()=>true;
            localStorage.setItem('nedotify_interface_ui_style',JSON.stringify(style));
            if(stale){localStorage.setItem('nedotify_theme_font_size','12');localStorage.setItem('nedotify_theme_glass_blur','4');}
        },{style,stale});
        await page.goto(`http://127.0.0.1:${server.address().port}/`);
        await page.addScriptTag({url:'/js/appearance-assets.js'});await page.addScriptTag({url:'/js/ui-style.js'});await page.addScriptTag({url:'/js/lucide.min.js'});
        await page.evaluate(async style=>{
            window.settings=await window.pywebview.api.get_settings();window.settings.interface.ui_style=style;
            document.getElementById('app-splash').remove();document.getElementById('view-settings').classList.add('active');
            const settings=await import('/js/settings.js');window.settingsModule=settings;
            settings.initSettings();settings.applySettingsFromBackend(window.settings);await settings.ensureSettingsPanel();
            const visualizer=await import('/js/visualizer.js');visualizer.initVisualizer();
        },style);
        return {page,context};
    }
    async function check(name, body) {try {await body();console.log('PASS',name);} catch(error) {failures.push(`${name}: ${error.message}`);console.log('FAIL',name,error.message);}}
    try {
        let {page,context}=await mount({stale:true});
        await check('late panel mount keeps backend font and glass over stale mirrors',async()=>{
            assert.equal(await page.locator('#slider-font-size').inputValue(),'18');
            assert.equal(await page.locator('#slider-glass-blur').inputValue(),'23');
        });
        await check('privacy and credentials restore on late mount',async()=>{
            assert.equal(await page.locator('#lyrics-mode').inputValue(),'line');
            assert.equal(await page.locator('#lyrics-animations').inputValue(),'reduced');
            assert.equal(await page.locator('#select-browser-cookies').inputValue(),'firefox');
        });
        await check('visualizer initialisation respects backend disabled preference',async()=>{
            assert.equal(await page.locator('#toggle-visualizer').getAttribute('aria-checked'),'false');
        });
        await page.locator('[data-panel="appearance"]').click();
        await check('HEX field commits palette and survives a new context',async()=>{
            await page.locator('#picker-color-primary-hex').fill('#118855');await page.locator('#picker-color-primary-hex').press('Tab');
            await page.waitForTimeout(50);assert.equal(state.theme.color_primary,'#118855');assert.equal(state.theme.custom_palette_enabled,true);
        });
        await check('enable custom palette persists its checkbox',async()=>{
            await page.locator('#custom-palette-enabled').check();await page.waitForTimeout(50);assert.equal(state.theme.custom_palette_enabled,true);
        });
        await page.locator('[data-panel="audio"]').click();
        rejectKey='crossfade_duration_sec';
        await check('failed slider save restores thumb label and audio preference',async()=>{
            await page.locator('#slider-crossfade-sec').evaluate(input=>{input.value='11';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
            await page.waitForTimeout(100);assert.equal(await page.locator('#slider-crossfade-sec').inputValue(),'8');
            assert.equal(await page.locator('#label-crossfade-sec').textContent(),'8 сек');
            assert.equal(await page.evaluate(()=>window.settings.audio.crossfade_duration_sec),8);
        });rejectKey='';
        await check('failed visualizer switch and style restore their real rendering state',async()=>{
            rejectKey='cover_visualizer';await page.locator('#toggle-visualizer').click();await page.waitForTimeout(80);
            assert.equal(await page.locator('#toggle-visualizer').getAttribute('aria-checked'),'false');
            assert.equal(await page.evaluate(async()=>(await import('/js/visualizer.js')).isVisualizerEnabled()),false);
            rejectKey='visualizer_style';await page.locator('#select-visualizer-style').selectOption('bars');await page.waitForTimeout(80);
            assert.equal(await page.locator('#select-visualizer-style').inputValue(),'wave');rejectKey='';
        });rejectKey='';
        await check('Discord and quota use one action and restore their controls on failure',async()=>{
            await page.locator('[data-panel="appearance"]').click();
            let before=calls.length;rejectKey='discord_rpc_enabled';
            await page.locator('#toggle-discord-rpc').click();await page.waitForTimeout(50);
            assert.equal(calls.length-before,1);assert.equal(await page.locator('#toggle-discord-rpc').getAttribute('aria-checked'),'false');
            await page.locator('[data-panel="storage"]').click();before=calls.length;rejectKey='cache_quota_gb';
            await page.locator('#select-cache-quota').selectOption('2');await page.waitForTimeout(50);
            assert.equal(calls.length-before,1);assert.equal(await page.locator('#select-cache-quota').inputValue(),'10');rejectKey='';
        });rejectKey='';
        await check('explicit blur choice leaves Economy and actually enables glass',async()=>{
            await page.locator('[data-panel="optimization"]').click();
            await page.locator('#opt-perf-preset [data-val="low"]').click();
            await page.waitForTimeout(50);
            assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--glass-blur').trim()),'0px');
            await page.locator('#opt-blur-quality [data-val="hq"]').click();
            await page.waitForTimeout(100);
            assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--glass-blur').trim()),'14px');
            assert.equal(state.optimization.resource_blur,true);
        });
        await check('a rejected blur slider does not change the performance profile or resource switches',async()=>{
            await page.locator('#opt-perf-preset [data-val="low"]').click();await page.waitForTimeout(50);
            await page.locator('[data-panel="appearance"]').click();rejectKey='glass_blur';
            await page.locator('#slider-glass-blur').evaluate(input=>{input.value='20';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
            await page.waitForTimeout(100);
            assert.equal(state.optimization.performance_preset,'low');assert.equal(state.optimization.resource_blur,false);
            assert.equal(await page.locator('#slider-glass-blur').inputValue(),'0');rejectKey='';
        });rejectKey='';
        await check('background selection, dim zero, preview, disable and remove have real effects',async()=>{
            await page.locator('[data-panel="background"]').click();
            await page.locator('.settings-builtin-gallery button').first().click();
            await page.waitForTimeout(100);
            const url=state.theme.custom_bg_image;assert.ok(url);
            for(const [id,value] of [['slider-bg-dim',0],['slider-bg-blur',12]]) await page.locator('#'+id).evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));},value);
            await page.waitForTimeout(50);
            assert.equal(state.theme.bg_dim,0);assert.equal(state.theme.bg_blur,12);
            await page.waitForFunction(()=>getComputedStyle(document.getElementById('custom-bg-layer')).filter==='blur(12px)');
            assert.equal(await page.locator('#custom-bg-dim-layer').evaluate(node=>node.style.backgroundColor),'rgba(0, 0, 0, 0)');
            await page.locator('#btn-remove-bg-image').click();await page.waitForTimeout(50);
            assert.equal(state.theme.custom_bg_image,'');assert.equal(await page.locator('#custom-bg-layer').evaluate(node=>node.style.display),'none');
        });
        await check('all settings categories fit at narrow and wide widths in both skins',async()=>{
            for(const style of ['current','macos']) for(const width of [600,1100,1600]) {
                await page.setViewportSize({width,height:800});await page.evaluate(style=>window.NeDotifyAppearance.apply(style,'light'),style);
                for(const button of await page.locator('.settings-nav-btn[data-panel]').all()) {
                    await button.click();
                    const overflow=await page.locator('.settings-panels').evaluate(node=>node.scrollWidth-node.clientWidth);
                    assert.ok(overflow<=2,`${style} ${width} ${await button.getAttribute('data-panel')} overflow=${overflow}`);
                }
            }
        });
        await context.close();
        // Commit every ordinary slider, then restore from the bridge into a
        // completely new browser context with no mirrors or cached settings.
        ({page,context}=await mount());
        const sliders=[['appearance','slider-font-size','theme','font_size',20],['appearance','slider-glass-blur','theme','glass_blur',26],
            ['appearance','slider-border-radius','interface','border_radius',16],['background','slider-bg-blur','theme','bg_blur',9],['background','slider-bg-dim','theme','bg_dim',0],
            ['audio','slider-crossfade-sec','audio','crossfade_duration_sec',7],['particles','slider-particles-count','ui','particles_count',47],['particles','slider-particles-size','ui','particles_size',5],['particles','slider-particles-speed','ui','particles_speed',1],
            ['optimization','slider-fps-particles','optimization','fps_particles',19],['optimization','slider-fps-visualizer','optimization','fps_visualizer',40],['optimization','slider-fps-ui','optimization','fps_ui',55],['optimization','slider-unfocus-fps','efficiency','unfocus_fps_limit',20]];
        const switches=[['appearance','toggle-transparency','theme','transparency_enabled'],['audio','toggle-crossfade','audio','crossfade_enabled'],['audio','toggle-gapless','audio','gapless_playback'],['audio','toggle-normalization','audio','volume_normalization'],['audio','toggle-autoplay','audio','autoplay'],['audio','toggle-visualizer','ui','cover_visualizer'],['particles','toggle-particles','ui','particles_enabled'],
            ['optimization','toggle-unfocus-enabled','efficiency','unfocus_enabled'],['optimization','toggle-unfocus-blur','efficiency','unfocus_blur_reduction'],['optimization','toggle-unfocus-animations','efficiency','unfocus_disable_animations'],['optimization','toggle-unfocus-visualizations','efficiency','unfocus_disable_visualizations'],
            ['player','toggle-show-queue','player','show_queue'],['player','toggle-compact-queue-btn','player','compact_queue_btn'],['player','toggle-next-track-preview','player','next_track_preview'],['player','toggle-queue-autopilot','player','queue_autopilot'],['player','toggle-player-prefetch','player','player_prefetch'],['player','toggle-aura-orbs','player','aura_orbs_enabled'],['storage','toggle-auto-download-favorites','storage','auto_download_favorites'],
            ['audio','toggle-lyrics-enabled','lyrics','enabled'],['auth','toggle-lastfm-enabled','services','lastfm_enabled'],['auth','toggle-source-youtube','services','youtube_enabled'],['auth','toggle-source-soundcloud','services','soundcloud_enabled']];
        await check('all preference switches change real state with a single durable write',async()=>{
            for(const [panel,id,category,key] of switches){
                await page.locator(`[data-panel="${panel}"]`).click();
                const enabled=await page.locator('#'+id).getAttribute('aria-checked')==='true',before=calls.length;
                await page.locator('#'+id).click();await page.waitForTimeout(30);
                assert.equal(state[category][key],!enabled,id);assert.equal(calls.length-before,1,id+' single write');
            }
        });
        await check('every ordinary slider previews, commits and has a usable pointer target',async()=>{
            for(const [panel,id,category,key,value] of sliders){
                await page.locator(`[data-panel="${panel}"]`).click();
                assert.ok((await page.locator('#'+id).boundingBox()).height>=24,id);
                const before=calls.length;
                await page.locator('#'+id).evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));},value);
                assert.equal(calls.length,before,`${id} previews without bridge writes`);
                await page.locator('#'+id).dispatchEvent('change');await page.waitForTimeout(30);
                assert.equal(state[category][key],value,id);
            }
        });
        await context.close();({page,context}=await mount());
        await check('every committed slider restores in a new browser context without storage',async()=>{
            for(const [panel,id,,,value] of sliders){
                await page.locator(`[data-panel="${panel}"]`).click();assert.equal(await page.locator('#'+id).inputValue(),String(value),id);
            }
            assert.equal(await page.locator('#custom-palette-enabled').isChecked(),true);
            assert.equal(await page.locator('#picker-color-primary-hex').inputValue(),'#118855');
        });
        await check('all preference switches restore in a new browser context',async()=>{
            for(const [panel,id,category,key] of switches){
                await page.locator(`[data-panel="${panel}"]`).click();assert.equal(await page.locator('#'+id).getAttribute('aria-checked'),String(state[category][key]),id);
            }
        });
        await check('priority panels remain readable at maximum font size in both skins',async()=>{
            for(const style of ['current','macos']) for(const mode of ['light','dark']) for(const width of [600,1100]){
                await page.setViewportSize({width,height:800});await page.evaluate(({style,mode})=>window.NeDotifyAppearance.apply(style,mode),{style,mode});
                for(const panel of ['appearance','background','optimization']){
                    await page.locator(`[data-panel="${panel}"]`).click();
                    const overflow=await page.locator('.settings-panels').evaluate(node=>node.scrollWidth-node.clientWidth);
                    assert.ok(overflow<=2,`${style} ${mode} ${width} ${panel}`);
                    if(mode==='dark' && width===1100) await page.screenshot({path:path.join(screenshots,`${style}-${panel}.png`)});
                }
            }
        });
        await context.close();
        ({page,context}=await mount({style:'macos'}));
        await check('macOS font and blur controls match independent saved preferences',async()=>{
            assert.equal(await page.locator('#slider-font-size').inputValue(),'17');
            assert.equal(await page.locator('#slider-glass-blur').inputValue(),'32');
        });
        await check('macOS presets save independent blur strength without changing standard glass',async()=>{
            const standard=state.theme.glass_blur;
            await page.locator('[data-panel="optimization"]').click();await page.locator('#opt-perf-preset [data-val="balanced"]').click();await page.waitForTimeout(100);
            assert.equal(state.interface.macos_blur,6);assert.equal(state.theme.glass_blur,standard);
            assert.equal(await page.locator('#slider-glass-blur').inputValue(),'6');
        });
        await context.close();
        assert.deepEqual(errors,[],'no uncaught browser errors');
        assert.deepEqual(failures,[]);
        console.log('settings audit passed; bridge writes:',calls.length);
    } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
