// Real native dialogs and real shared handlers; no user's profile or bridge calls.
const {chromium} = require('playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..', 'ui');
const server = http.createServer((req,res) => {
    const name = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const file = path.resolve(root,name.startsWith('/MACos_ui/') ? '.'+name : 'web_new_v2/'+(name==='/'?'index.html':name.slice(1)));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
    let body=fs.readFileSync(file);
    if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace('</head>',['/css/components/library-refresh.css','/css/components/smart-playlists.css','/css/components/profile-refresh.css','/css/components/home-refresh.css','/MACos_ui/tokens.css','/MACos_ui/interface.css'].map(href=>`<link rel="stylesheet" href="${href}">`).join('')+'</head>');
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream');res.end(body);
});
(async()=>{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
    const failures=[];
    try {
        for(const style of ['current','macos','macos-light']) {
            const page=await browser.newPage({viewport:{width:1100,height:800}});
            page.setDefaultTimeout(3000);
            const errors=[];page.on('pageerror',error=>errors.push(error.message));
            await page.goto(`http://127.0.0.1:${server.address().port}`);
            await page.addScriptTag({url:'/js/lucide.min.js'});
            await page.evaluate(async style=>{
                document.getElementById('app-splash')?.remove();
                document.documentElement.dataset.uiStyle=style.startsWith('macos')?'macos':'current';
                document.documentElement.dataset.macosMode=style==='macos-light'?'light':'dark';
                window.utils=await import('/js/utils.js');
                window.libView=await import('/js/library-view.js');
                libView.initLibraryView({selected:()=>null,tracks:()=>[],overview(){},select(){}});
                const background=document.createElement('button');background.id='fixture-background';background.textContent='Background control';
                background.style.cssText='position:fixed;right:25px;bottom:25px;z-index:100';
                window.backgroundClicks=0;background.onclick=()=>window.backgroundClicks++;document.body.append(background);
                window.fixturePlaylist={id:1,name:'Synthwave & Night Drive',track_count:3};
                const smart=await import('/js/smart-playlists.js');smart.initSmartPlaylists({});window.smart=smart;
            },style);
            await page.evaluate(() => {
                const parent = document.createElement('div'); parent.id='fixture-parent-modal';
                parent.style.cssText='position:fixed;inset:20%;background:#333;z-index:10000';
                parent.innerHTML='<button id="fixture-parent-first">Parent first</button><button id="fixture-parent-last">Parent last</button>';
                const child = document.createElement('dialog'); child.id='fixture-child-modal';
                child.innerHTML='<button id="fixture-child-first">Child first</button><button id="fixture-child-last">Child last</button>';
                document.body.append(parent,child);window.parentClosed=0;
                utils.openModalFocusTrap(parent,{onClose(){parent.style.display='none';utils.closeModalFocusTrap(parent);window.parentClosed++;}});
                child.showModal();utils.openModalFocusTrap(child);
            });
            await page.locator('#fixture-child-last').focus();await page.keyboard.press('Tab');
            assert.equal(await page.locator('#fixture-child-first').evaluate(el=>el===document.activeElement),true,'Tab remains in the nested dialog');
            await page.keyboard.press('Escape');
            assert.equal(await page.evaluate(()=>window.parentClosed),0,'Escape closes the child before its floating settings parent');
            assert.equal(await page.locator('#fixture-child-modal').evaluate(el=>el.open),false);
            await page.keyboard.press('Escape');
            assert.equal(await page.evaluate(()=>window.parentClosed),1,'the next Escape closes the parent');
            await page.evaluate(()=>{document.getElementById('fixture-parent-modal').remove();document.getElementById('fixture-child-modal').remove();});
            await page.locator('#fixture-background').focus();
            await page.evaluate(()=>libView.openPlaylistActions(fixturePlaylist));
            const first=await page.locator('#lib-playlist-actions').boundingBox();
            if(!(first.x>100 && first.y>50))failures.push(`${style}: dialog stuck at viewport origin ${JSON.stringify(first)}`);
            const screenshots=path.resolve(__dirname,'..','docs','screenshots','dialog-fix-20261030');fs.mkdirSync(screenshots,{recursive:true});
            await page.waitForTimeout(250);
            await page.screenshot({path:path.join(screenshots,`${style}.png`)});
            await page.mouse.click(1060,700);
            await page.waitForFunction(()=>!document.getElementById('lib-playlist-actions').open);
            // Re-open after backdrop dismissal: this is where the invisible top-layer
            // dialog used to make every control in the application inert.
            await page.evaluate(()=>libView.openPlaylistActions(fixturePlaylist));
            const state=await page.locator('#lib-playlist-actions').evaluate(el=>({open:el.open,display:getComputedStyle(el).display,hidden:el.classList.contains('hidden')}));
            if(state.display==='none'||state.hidden)failures.push(`${style}: reopened modal is invisible and blocks the app ${JSON.stringify(state)}`);
            await page.keyboard.press('Escape');
            await page.locator('#fixture-background').click();
            assert.equal(await page.evaluate(()=>backgroundClicks),1,'background works after dismissal');
            // Content padding isn't the backdrop. Closing by button, native
            // cancel, Escape, and outside click must all release the trap.
            for(const width of [1100,360]) {
                await page.setViewportSize({width,height:800});
                for(const selector of ['#lib-playlist-actions','#home-detail-dialog','#profile-edit-dialog','.lib-smart-dialog']) {
                    for(const method of ['outside','escape','button','cancel']) {
                        await page.evaluate(selector=>{
                            const dialog=document.querySelector(selector);
                            dialog.style.removeProperty('display');dialog.classList.remove('hidden');
                            const close=dialog.querySelector('[data-modal-close],#home-detail-close,#profile-edit-cancel,[data-smart-cancel]');
                            close.onclick=()=>dialog.close();
                            dialog.showModal();utils.openModalFocusTrap(dialog,{returnFocusTo:document.getElementById('fixture-background')});
                        },selector);
                        await page.waitForTimeout(220);
                        const box=await page.locator(selector).boundingBox();
                        assert.ok(box.x>=0 && box.x+box.width<=width && box.y>=0 && box.y+box.height<=800,`${style}/${selector} stays in viewport`);
                        await page.mouse.click(box.x+3,box.y+3);
                        assert.equal(await page.locator(selector).evaluate(el=>el.open),true,'padding click keeps dialog open');
                        if(method==='outside')await page.mouse.click(width-5,790);
                        if(method==='escape')await page.keyboard.press('Escape');
                        if(method==='button')await page.locator(selector).locator('[data-modal-close],#home-detail-close,#profile-edit-cancel,[data-smart-cancel]').click();
                        if(method==='cancel')await page.locator(selector).evaluate(el=>el.requestClose());
                        await page.waitForFunction(selector=>!document.querySelector(selector).open && !utils.isModalFocusTrapped(document.querySelector(selector)),selector);
                        assert.equal(await page.locator(selector).evaluate(el=>utils.isModalFocusTrapped(el)),false,'closed native dialog releases focus trap');
                        await page.locator('#fixture-background').click();
                    }
                }
            }
            // A legacy duplicate closer cannot poison the next showModal().
            await page.evaluate(()=>{
                const dialog=document.getElementById('lib-playlist-actions');
                dialog.addEventListener('click',()=>dialog.close(),{once:true});
                dialog.showModal();utils.openModalFocusTrap(dialog);
            });
            await page.mouse.click(355,790);
            await page.evaluate(()=>{const d=document.getElementById('lib-playlist-actions');d.showModal();utils.openModalFocusTrap(d);});
            assert.equal(await page.locator('#lib-playlist-actions').isVisible(),true);
            await page.keyboard.press('Escape');
            // Div overlays retain their own close callback and never acquire
            // native browser inertness.
            await page.evaluate(()=>{
                const overlay=document.getElementById('modal-create-playlist');
                overlay.style.display='flex';utils.openModalFocusTrap(overlay,{onClose:()=>{overlay.style.display='none';utils.closeModalFocusTrap(overlay);}});
            });
            await page.mouse.click(355,790);
            assert.equal(await page.locator('#modal-create-playlist').isVisible(),false);
            await page.locator('#fixture-background').click();
            assert.deepEqual(errors,[]);
            await page.close();
        }
        assert.deepEqual(failures,[]);
        console.log('dialog lifecycle: 3 themes, 4 native dialogs, 2 widths, 4 dismissal methods, padding, duplicate closers and legacy overlays passed');
    }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
