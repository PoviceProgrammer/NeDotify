const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..','ui');
const output = path.join(os.tmpdir(),'NeDotify','library-layout');fs.mkdirSync(output,{recursive:true});
const server = http.createServer((req,res)=>{
    const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file=path.resolve(root,name.startsWith('/MACos_ui/')?'.'+name:`web_new_v2/${name==='/'?'index.html':name.slice(1)}`);
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body=fs.readFileSync(file);
    if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace('</head>','<link rel="stylesheet" href="/css/components/library-refresh.css"><link rel="stylesheet" href="/css/components/search-refresh.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/library.css"></head>');
    res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true});
    try {
        const page=await browser.newPage();
        for(const style of ['current','macos'])for(const mode of ['dark','light'])for(const width of [1280,900,600]) {
            await page.setViewportSize({width,height:800});await page.goto(`http://127.0.0.1:${server.address().port}/`);
            await page.evaluate(({style,mode})=>{
                document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.theme=mode;document.documentElement.dataset.macosMode=mode;
                document.querySelectorAll('.view-page').forEach(node=>node.classList.remove('active'));document.getElementById('view-library').classList.add('active');
                document.getElementById('app-splash')?.remove();
                const grid=document.getElementById('lib-overview-collections');
                grid.innerHTML=Array.from({length:7},(_,i)=>`<article class="lib-collection-card"><button class="lib-collection-open"><span class="lib-collection-cover" style="background:linear-gradient(140deg,#6471bd,#c999ba)"></span><strong>Плейлист ${i+1}</strong><span>12 треков</span></button></article>`).join('');
            },{style,mode});
            const g=await page.evaluate(()=>{
                const view=document.getElementById('view-library'),side=view.querySelector('.lib-left-sidebar'),main=view.querySelector('.lib-main-layout'),cover=view.querySelector('.lib-collection-cover');
                return {sidebar:getComputedStyle(side).display,columns:getComputedStyle(main).gridTemplateColumns.split(' ').length,
                    tabHeight:view.querySelector('.lib-top-card').getBoundingClientRect().height,
                    cover:cover.getBoundingClientRect().toJSON(),overflow:view.scrollWidth>view.clientWidth};
            });
            assert.equal(g.sidebar,'none',`${style}/${width}: internal sidebar stays retired`);assert.equal(g.columns,1,`${style}/${width}: no empty column`);
            assert.ok(g.tabHeight<=44,`${style}/${width}: compact tabs (${g.tabHeight})`);
            assert.ok(Math.abs(g.cover.width-g.cover.height)<1,`${style}/${width}: square cover`);
            assert.ok(g.cover.width>=140,`${style}/${width}: large cover (${g.cover.width})`);
            assert.equal(g.overflow,false,`${style}/${width}: no horizontal overflow`);
            if(width===1280&&mode==='dark')await page.screenshot({path:path.join(output,`library-${style}.png`)});
        }
        for(const mode of ['dark','light']) {
            await page.setViewportSize({width:1280,height:800});
            await page.evaluate(mode=>{
                document.documentElement.dataset.uiStyle='macos';document.documentElement.dataset.macosMode=mode;
                document.documentElement.dataset.macosTransparency='true';document.documentElement.dataset.theme=mode;
                document.querySelectorAll('.view-page').forEach(node=>node.classList.remove('active'));document.getElementById('view-search').classList.add('active');
                document.getElementById('search-listened-grid').innerHTML='<button class="search-listened-card"><img alt="" src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'48\' height=\'48\'%3E%3Crect width=\'48\' height=\'48\' fill=\'purple\'/%3E%3C/svg%3E"><span class="search-listened-copy"><strong>Название трека</strong><span>Исполнитель</span></span></button>';
            },mode);
            const glass=await page.evaluate(()=>({parent:getComputedStyle(document.getElementById('search-discovery')).backdropFilter,
                card:getComputedStyle(document.querySelector('.search-listened-card')).backdropFilter,
                height:document.querySelector('.search-listened-card').getBoundingClientRect().height,
                foreground:getComputedStyle(document.querySelector('.search-listened-copy strong')).color,
                secondary:getComputedStyle(document.querySelector('.search-listened-copy > span')).color}));
            assert.equal(glass.parent,'none');assert.notEqual(glass.card,'none');assert.ok(Math.abs(glass.height-72)<1);assert.notEqual(glass.foreground,glass.secondary);
            await page.evaluate(()=>document.documentElement.classList.add('perf-low'));
            assert.equal(await page.locator('.search-listened-card').evaluate(node=>getComputedStyle(node).backdropFilter),'none');
            await page.evaluate(()=>document.documentElement.classList.remove('perf-low'));
        }
        console.log(`library/search layout: 12 library and 4 glass/performance scenarios passed; screenshots ${output}`);
    } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
