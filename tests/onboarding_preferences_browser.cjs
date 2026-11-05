// Real onboarding DOM + handlers in Chromium, with an isolated bridge double.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright-core');
const root = path.resolve(__dirname, '..', 'ui');
const server = http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const file = path.resolve(root, name.startsWith('/MACos_ui/') ? '.' + name : `web_new_v2/${name === '/' ? 'index.html' : name.slice(1)}`);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
    let body = fs.readFileSync(file);
    if (file.endsWith('index.html')) body = body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', '<link rel="stylesheet" href="/css/components/onboarding.css"></head>');
    if (file.endsWith(path.join('js','onboarding.js'))) body = body.toString()
        .replace(/^import .*from '\.\/(?:player|settings|setup-panel)\.js';\r?$/gm, '')
        + '\nfunction applySettings() {} function applySettingsFromBackend() {} const listAudioOutputs=async()=>({supported:false,devices:[]});const openSetupPanel=async()=>true;';
    res.setHeader('Content-Type', {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)] || 'application/octet-stream');
    res.end(body);
});
(async () => {
    await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
    const browser = await chromium.launch({headless:true});
    try {
        const page = await browser.newPage({viewport:{width:900,height:700}});
        page.setDefaultTimeout(7000);
        const errors=[];page.on('pageerror',error=>errors.push(error.message));
        await page.addInitScript(() => {
            window.settings={general:{first_launch_done:false},services:{youtube_enabled:true,soundcloud_enabled:true}};
            window.submissions=[];window.folderImports=0;
            window.pywebview={api:{
                complete_onboarding:async payload=>{window.submissions.push(payload);return {success:true,settings:{...window.settings,general:{first_launch_done:true}}};},
                import_music_folder:async()=>{window.folderImports++;return {success:true,pending:true,path:'C:\\Music'};},
            }};
        });
        await page.goto(`http://127.0.0.1:${server.address().port}/`);
        await page.addScriptTag({url:'/js/lucide.min.js'});
        await page.evaluate(async () => {document.getElementById('app-splash')?.remove();window.onboarding=await import('/js/onboarding.js');await window.onboarding.initOnboarding();});
        assert.equal(await page.locator('.onboarding-step').count(),6);
        assert.equal(await page.locator('#ob-progress').getAttribute('max'),'6');
        assert.ok(await page.evaluate(()=>document.getAnimations().some(a=>a.effect?.target?.closest('#onboarding-wizard'))),'wizard has live motion');
        const screenshots=path.resolve(__dirname,'..','docs','screenshots','onboarding-motion-20261030');
        fs.mkdirSync(screenshots,{recursive:true});
        await page.waitForTimeout(800);
        await page.screenshot({path:path.join(screenshots,'appearance.png')});
        await page.locator('[data-ob-style="macos"]').click();
        await page.locator('#ob-btn-next').click();
        await page.locator('[data-ob-profile][data-value="high"]').click();
        await page.waitForTimeout(500);
        await page.screenshot({path:path.join(screenshots,'motion.png')});
        await page.locator('#ob-btn-next').click();
        await page.locator('#ob-crossfade').check();
        await page.locator('#ob-btn-next').click();
        await page.locator('#ob-import-folder').click();
        assert.match(await page.locator('#ob-folder-status').textContent(), /C:\\Music/);
        await page.locator('#ob-btn-next').click();
        await page.locator('[data-ob-source="youtube"]').uncheck();
        await page.locator('#ob-download-format').selectOption('mp3');
        await page.locator('#ob-download-quality').selectOption('192');
        await page.locator('#ob-btn-next').click();
        assert.equal(await page.locator('[data-ob-summary="style"]').textContent(),'macOS');
        await page.locator('#ob-btn-finish').click();
        await page.waitForFunction(()=>window.submissions.length === 1);
        const payload=await page.evaluate(()=>window.submissions[0]);
        assert.equal(payload.ui_style,'macos');assert.deepEqual(payload.sources,{youtube:false,soundcloud:true});
        assert.equal(payload.download_format,'mp3');assert.equal(payload.download_quality,'192');
        assert.equal(payload.crossfade_enabled,true);
        assert.equal(payload.performance_preset,'high');
        assert.equal(await page.evaluate(()=>window.folderImports),1);
        // Reopening must not leave the old completion/picker handlers active.
        await page.setViewportSize({width:600,height:650});
        await page.evaluate(()=>window.onboarding.reopenOnboarding());
        await page.locator('[data-ob-step="4"]').click();
        await page.locator('#ob-import-folder').click();
        assert.equal(await page.evaluate(()=>window.folderImports),2);
        await page.locator('#ob-btn-next').click();
        await page.locator('#ob-btn-next').click();
        const bounds=await page.locator('.ob-shell').boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x+bounds.width <= 600 && bounds.y+bounds.height <= 650,'wizard fits a small viewport');
        await page.locator('#ob-btn-finish').click();
        await page.waitForFunction(()=>window.submissions.length === 2);
        assert.equal(await page.evaluate(()=>window.submissions.length),2,'one completion per click after reentry');
        await page.locator('#onboarding-wizard').waitFor({state:'hidden'});
        // System motion preference also cancels an in-flight entrance.
        await page.evaluate(()=>window.onboarding.reopenOnboarding());
        await page.emulateMedia({reducedMotion:'reduce'});
        await page.waitForTimeout(50);
        const remaining=await page.evaluate(()=>document.getAnimations().filter(a=>a.playState==='running' && a.effect?.target?.closest('#onboarding-wizard')).map(a=>({target:a.effect.target.className,name:a.animationName,property:a.transitionProperty})));
        assert.deepEqual(remaining,[],'reduced motion cancels all wizard motion');
        // Rapid direction changes leave one live, focused page, with no ghost forms.
        await page.evaluate(()=>{
            for(const step of [2,3,1,4,2,5])document.querySelector(`[data-ob-step="${step}"]`).click();
        });
        assert.equal(await page.locator('.onboarding-step:not([hidden])').count(),1);
        assert.equal(await page.locator('.onboarding-step:not([hidden])').getAttribute('data-step'),'5');
        assert.equal(await page.evaluate(()=>document.activeElement.id),'ob-title-5');
        // Import validation remains on the library step after splitting the flow.
        await page.locator('[data-ob-step="4"]').click();
        await page.locator('[data-ob-library][data-value="import"]').click();
        await page.locator('#ob-playlist-url').fill('https://example.com/not-a-playlist');
        await page.locator('#ob-btn-next').click();
        assert.equal(await page.locator('.onboarding-step.active').getAttribute('data-step'),'4');
        assert.equal(await page.locator('#ob-playlist-url').getAttribute('aria-invalid'),'true');
        assert.equal(await page.evaluate(()=>window.submissions.length),2);
        await page.locator('[data-ob-library][data-value="empty"]').click();
        await page.locator('[data-ob-step="2"]').click();
        await page.locator('[data-ob-profile][data-value="low"]').click();
        await page.emulateMedia({reducedMotion:'no-preference'});
        assert.equal(await page.locator('.ob-record').evaluate(el=>getComputedStyle(el).animationName),'none','low profile stops ambient vinyl');
        for(const file of ['/MACos_ui/tokens.css','/MACos_ui/interface.css'])await page.addStyleTag({url:file});
        await page.evaluate(()=>{document.documentElement.dataset.uiStyle='macos';document.documentElement.dataset.macosMode='dark';});
        await page.setViewportSize({width:360,height:640});
        await page.locator('#toast-container').evaluate(el=>el.replaceChildren());
        await page.waitForTimeout(600);
        await page.screenshot({path:path.join(screenshots,'macos-small.png')});
        for(const step of [1,2,3,4,5,6]) {
            await page.locator(`[data-ob-step="${step}"]`).click();
            await page.waitForTimeout(700);
            const rect=await page.locator('.ob-shell').boundingBox();
            assert.ok(rect.x>=0 && rect.x+rect.width<=360 && rect.y>=0 && rect.y+rect.height<=640,'macOS wizard fits narrow window');
            assert.ok(await page.locator('.ob-content').evaluate(el=>el.scrollWidth<=el.clientWidth+1),`step ${step} content has no horizontal overflow`);
        }
        await page.locator('#ob-btn-finish').click();
        await page.locator('#onboarding-wizard').waitFor({state:'hidden'});
        assert.equal(await page.evaluate(()=>window.submissions.length),3);
        assert.deepEqual(errors,[]);
        console.log('onboarding browser: six steps, saved choices, reentry during exit, reduced motion, rapid navigation, validation, low profile, macOS at 360px passed');
    } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
