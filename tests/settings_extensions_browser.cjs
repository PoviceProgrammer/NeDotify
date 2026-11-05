const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..','ui');
const server=http.createServer((req,res)=>{
    const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file=path.resolve(root,name.startsWith('/MACos_ui/')?'.'+name:`web_new_v2/${name==='/'?'index.html':name.slice(1)}`);
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body=fs.readFileSync(file);
    if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace('</head>','<link rel="stylesheet" href="/css/components/settings-refresh.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/settings.css"></head>');
    res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true});
    try {
        const page=await browser.newPage({viewport:{width:1100,height:800}}), errors=[];
        const state={interface:{border_radius:12},services:{youtube_enabled:true,soundcloud_enabled:true}};
        const calls=[];
        await page.exposeFunction('settingsRead',()=>state);
        await page.exposeFunction('settingsWrite',(key,value,category)=>{state[category]||={};state[category][key]=value;calls.push([key,value,category]);return true;});
        await page.addInitScript(()=>{window.pywebview={api:{get_settings:()=>window.settingsRead(),save_setting:(...args)=>window.settingsWrite(...args)}};});
        page.on('pageerror',error=>errors.push(error.message));
        async function mount(style) {
            await page.evaluate(async style=>{
                window.settings=await window.pywebview.api.get_settings();
                document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.macosMode='dark';
                document.getElementById('app-splash')?.remove();document.getElementById('view-settings').classList.add('active');
                const {initAdditionalSettings}=await import('/js/settings-view.js');
                const {applyBorderRadius,saveSetting,savedSetting}=await import('/js/settings.js');
                const options={save:saveSetting,read:savedSetting,applyRadius:applyBorderRadius};
                initAdditionalSettings(options);initAdditionalSettings(options);
                const preview=document.createElement('article');preview.className='feed-card';preview.id='radius-preview';document.body.append(preview);
            },style);
        }
        await page.goto(`http://127.0.0.1:${server.address().port}/`);await mount('current');
        assert.equal(await page.locator('#settings-radius').count(),1);
        assert.equal(await page.locator('#settings-music-sources').count(),1);
        await page.locator('#slider-border-radius').evaluate(input=>{input.value='18';input.dispatchEvent(new Event('input',{bubbles:true}));});
        assert.equal(calls.length,0,'preview does not persist on every frame');
        assert.equal(await page.locator('#radius-preview').evaluate(node=>getComputedStyle(node).borderRadius),'18px');
        await page.locator('#slider-border-radius').dispatchEvent('change');
        await page.waitForFunction(()=>!document.getElementById('slider-border-radius').disabled);
        assert.deepEqual(calls,[['border_radius',18,'interface']]);
        await page.evaluate(()=>{document.getElementById('settings-appearance').style.display='none';const auth=document.getElementById('settings-auth');auth.classList.add('active');auth.style.display='block';});
        await page.locator('#toggle-source-youtube').click();
        await page.waitForFunction(()=>!document.getElementById('toggle-source-youtube').disabled);
        assert.equal(await page.locator('#toggle-source-youtube').getAttribute('aria-checked'),'false');
        assert.equal(state.services.youtube_enabled,false);
        await page.reload();await mount('macos');
        assert.equal(await page.locator('#slider-border-radius').inputValue(),'18');
        assert.equal(await page.locator('#radius-preview').evaluate(node=>getComputedStyle(node).borderRadius),'18px');
        assert.equal(await page.locator('#toggle-source-youtube').getAttribute('aria-checked'),'false');
        assert.equal(await page.locator('#toggle-source-soundcloud').getAttribute('aria-checked'),'true');
        assert.deepEqual(errors,[]);
        console.log('settings extensions: radius preview/save/restore in both skins, sources restore and idempotent mount passed');
    } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
