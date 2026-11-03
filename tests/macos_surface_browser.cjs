// Regression: disabling blur must not make the sidebar/player opaque.
const {chromium}=require('playwright-core');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..','ui');
const server=http.createServer((req,res)=>{
    const name=new URL(req.url,'http://localhost').pathname;
    const file=path.resolve(root,name.startsWith('/MACos_ui/')?'.'+name:'web_new_v2/'+(name==='/'?'index.html':name.slice(1)));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body=fs.readFileSync(file);
    if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>','<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
    const failures=[];
    try{
        for(const mode of ['dark','light']){
            const page=await browser.newPage({viewport:{width:1100,height:800}});
            await page.goto(`http://127.0.0.1:${server.address().port}`);
            await page.evaluate(mode=>{window.settings={interface:{ui_style:'macos',macos_mode:mode,macos_glass:true,macos_blur:0},theme:{transparency_enabled:true,transparency_level:10},optimization:{resource_blur:false,blur_quality:'off',performance_preset:'balanced'}};document.getElementById('app-splash')?.remove();},mode);
            await page.addScriptTag({url:'/js/ui-style.js'});
            await page.evaluate(()=>window.NeDotifyAppearance.restore(window.settings));
            for(const selector of ['#sidebar','#player-bar']){
                const style=await page.locator(selector).evaluate(el=>{const computed=getComputedStyle(el),canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');ctx.fillStyle=computed.backgroundColor;ctx.fillRect(0,0,1,1);return {background:computed.backgroundColor,blur:computed.backdropFilter,alpha:ctx.getImageData(0,0,1,1).data[3]/255};});
                const alpha=style.alpha;
                if(!(alpha>0&&alpha<1))failures.push(`${mode} ${selector}: blur=0 produces opaque panel ${style.background}`);
                assert.equal(style.blur,'none','zero blur should avoid expensive backdrop work');
            }
            await page.evaluate(()=>{window.settings.interface.macos_glass=false;window.NeDotifyAppearance.restore(window.settings);});
            assert.equal(await page.evaluate(()=>document.documentElement.dataset.macosTransparency),'false','explicit glass off disables live blur');
            await page.close();
        }
        assert.deepEqual(failures,[]);console.log('PASS: macOS dark/light alpha remains independent of blur; explicit solid mode retained');
    }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
