// Every shipped settings range: preview, units, commit, rejection and fresh-page restore.
const {chromium} = require('playwright-core');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../ui');
const server = http.createServer((req,res) => {
    const name = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file = path.resolve(root,name.startsWith('/MACos_ui/') ? '.'+name : 'web_new_v2/'+(name==='/'?'index.html':name.slice(1)));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body = fs.readFileSync(file);
    if(file.endsWith('index.html')) body = body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace('</head>','<link rel="stylesheet" href="/css/components/settings-refresh.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/settings.css"></head>');
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
    const aliases = await import('data:text/javascript,'+encodeURIComponent(fs.readFileSync(path.join(root,'web_new_v2/js/setting-aliases.js'),'utf8')));
    try {
        for(const style of ['current','macos']) {
            let state={theme:{font_size:16,glass_blur:14,transparency_enabled:true,transparency_level:80,bg_blur:0,bg_dim:30},interface:{ui_style:style,macos_font_size:17,macos_blur:32,border_radius:12},audio:{crossfade_duration_sec:3},optimization:{performance_preset:'high',fps_particles:24,fps_visualizer:30,fps_ui:60},efficiency:{unfocus_fps_limit:15},equalizer:{preamp:0,bands:Array(10).fill(0),mode:10},ui:{particles_enabled:false},player:{progress_transparency:18}};
            let reject=false,writes=0;const errors=[];
            const mount=async()=>{
                const context=await browser.newContext({viewport:{width:1200,height:900}}),page=await context.newPage();
                page.on('pageerror',e=>errors.push(e.message));
                await context.route(/^https?:\/\/(?!127\.0\.0\.1)/,r=>r.abort());
                await page.exposeFunction('readSettings',()=>structuredClone(state));
                await page.exposeFunction('writeSettings',(key,value,category)=>{
                    writes++;if(reject)return false;
                    for(const [cat,name] of aliases.settingAliases(category,key)){state[cat]||={};state[cat][name]=value;}return true;
                });
                await page.exposeFunction('writeEq',(preamp,bands,mode)=>{writes++;if(reject)return false;state.equalizer={...state.equalizer,preamp,bands,mode};return true;});
                await page.addInitScript(()=>{window.pywebview={api:{get_settings:()=>window.readSettings(),get_equalizer:async()=>(await window.readSettings()).equalizer,set_equalizer:(...args)=>window.writeEq(...args),save_setting:(...args)=>window.writeSettings(...args),get_zapret_status:async()=>({running:false}),get_discord_rpc_status:async()=>({enabled:false}),get_storage_info:async()=>({})}};window.awaitBridge=async()=>true;});
                await page.goto(`http://127.0.0.1:${server.address().port}`);await page.addScriptTag({url:'/js/appearance-assets.js'});await page.addScriptTag({url:'/js/ui-style.js'});await page.addScriptTag({url:'/js/lucide.min.js'});
                await page.evaluate(async style=>{
                    window.settings=await window.readSettings();document.getElementById('app-splash')?.remove();document.getElementById('view-settings').classList.add('active');
                    document.documentElement.dataset.uiStyle=style;
                    window.subject=await import('/js/settings.js');subject.initSettings();subject.applySettingsFromBackend(window.settings);await subject.ensureSettingsPanel();
                    await (await import('/js/equalizer.js')).initEqualizer();
                },style);
                return {page,context};
            };
            let {page,context}=await mount();
            const inventory=await page.locator('#view-settings input[type="range"]').evaluateAll(nodes=>nodes.map((el,index)=>({selector:el.id?'#'+el.id:el.dataset.atmosphereKey?`[data-atmosphere-key="${el.dataset.atmosphereKey}"]`:`.eq-band-slider[data-group="${el.dataset.group}"]`,id:el.id||el.dataset.atmosphereKey||'eq-band-'+el.dataset.group,min:Number(el.min),max:Number(el.max),step:Number(el.step)||1})));
            const expected=[];
            for(const item of inventory){
                const input=page.locator(item.selector);
                await input.evaluate(el=>{el.disabled=false;el.closest('details')?.setAttribute('open','');});
                const before=Number(await input.inputValue());
                let value=Number((item.min+Math.floor((item.max-item.min)/item.step*.65)*item.step).toFixed(2));
                if (value===before) value=Number((item.min+item.step).toFixed(2));
                await input.evaluate((el,value)=>{el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},value);
                await page.waitForTimeout(item.id.startsWith('eq-')?300:100);
                assert.equal(Number(await input.inputValue()),value,style+' '+item.id+' commit');
                const label=await input.evaluate(el=>{
                    const output=el.dataset.atmosphereKey?document.querySelector(`[data-atmosphere-output="${el.dataset.atmosphereKey}"]`):(el.id.startsWith('slider-')?document.getElementById(el.id.replace('slider-','label-')):null)||document.getElementById(el.id==='eq-preamp'?'eq-val-preamp':el.id==='player-progress-transparency'?'player-progress-transparency-value':'eq-val-group-'+el.dataset.group);
                    return output?.textContent||output?.value||'';
                });
                assert.ok(label.trim(),style+' '+item.id+' has a value label');
                if(item.id.includes('fps'))assert.ok(label.includes('FPS'),item.id+' FPS unit');
                if(/font-size|glass-blur|bg-blur|border-radius/.test(item.id))assert.ok(label.includes('px'),item.id+' px unit');
                if(/transparency|bg-dim/.test(item.id))assert.ok(label.includes('%'),item.id+' percent unit');
                if(item.id==='slider-crossfade-sec')assert.ok(label.includes('сек'));
                if(item.id.startsWith('eq-'))assert.ok(label.includes('dB'));
                const alternate=value===item.min?item.max:item.min;
                reject=true;
                await input.evaluate((el,value)=>{el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},alternate);
                await page.waitForTimeout(item.id.startsWith('eq-')?300:100);reject=false;
                assert.equal(Number(await page.locator(item.selector).inputValue()),value,style+' '+item.id+' rejected save restores value');
                expected.push([item.selector,value]);console.log('PASS',style,item.id,'value',value,'label',label,'rollback from',alternate,'initial',before);
            }
            await context.close();({page,context}=await mount());
            for(const [selector,value] of expected)assert.equal(Number(await page.locator(selector).inputValue()),value,style+' '+selector+' fresh context restore');
            assert.deepEqual(errors,[]);await context.close();console.log('PASS',style,inventory.length,'sliders reopen without localStorage;',writes,'bridge calls');
        }
    }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});

