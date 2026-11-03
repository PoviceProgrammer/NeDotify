// Run with NODE_PATH pointing at the installed Playwright runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright-core');
const root = path.resolve(__dirname, '..', 'ui');
const bridge = fs.readFileSync(path.join(root, 'web_new_v2/js/notifications.js'), 'utf8');
(async () => {
    const browser = await chromium.launch({headless: true});
    try {
        for (const width of [800, 360]) {
            const page = await browser.newPage({viewport: {width, height: 600}});
            await page.emulateMedia({reducedMotion:'reduce'});
            await page.setContent('<div id="notification-stack"><div id="network-banner" class="network-banner hidden"><svg></svg><span id="network-banner-text">Переподключение к потоку… (Попытка 2 из 3)</span></div><div id="toast-container" role="status" aria-live="polite"></div></div>');
            for (const file of ['web_new_v2/css/components/base.css', 'web_new_v2/css/components/visual-polish.css', 'MACos_ui/tokens.css', 'MACos_ui/interface.css', 'web_new_v2/css/components/notifications.css']) {
                await page.addStyleTag({content: fs.readFileSync(path.join(root, file), 'utf8')});
            }
            await page.addScriptTag({content: bridge});
            for (const style of ['current', 'light', 'dark']) {
                await page.evaluate(style => {
                    document.documentElement.dataset.uiStyle = style === 'current' ? 'current' : 'macos';
                    document.documentElement.dataset.macosMode = style;
                    document.getElementById('toast-container').replaceChildren();
                    window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {type: 'success', msg: 'Импортирован плейлист "Untitled playlist" (45 треков)'}}));
                }, style);
                const size = await page.locator('.toast').evaluate(el => {
                    const box = el.getBoundingClientRect();
                    const icon = el.querySelector('.toast-icon svg').getBoundingClientRect();
                    return {height: box.height, width: box.width, left: box.left, right: box.right, iconWidth: icon.width, iconHeight: icon.height};
                });
                assert.ok(size.iconWidth <= 20 && size.iconHeight <= 20, `${style}/${width}: oversized icon ${JSON.stringify(size)}`);
                assert.ok(size.height <= 100 && size.width <= 460 && size.left >= 0 && size.right <= width, `${style}/${width}: oversized toast ${JSON.stringify(size)}`);
                await page.locator('.toast-close').click();
                await page.locator('.toast').waitFor({state: 'detached'});
                console.log(`PASS ${style}/${width}: compact notification and close button`);
                for (const state of ['reconnecting', 'degraded', '']) {
                    await page.locator('#network-banner').evaluate((el,state) => el.className='network-banner '+state,state);
                    const geometry = await page.locator('#network-banner').evaluate(el => {
                        const rect=el.getBoundingClientRect(),css=getComputedStyle(el);
                        return {top:rect.top,left:rect.left,right:rect.right,height:rect.height,radius:css.borderBottomLeftRadius};
                    });
                    assert.equal(geometry.top,0,`${style}: status must attach to window top`);
                    assert.equal(geometry.radius,'22px');
                    assert.ok(geometry.left>=0 && geometry.right<=width && geometry.height<=100);
                }
                await page.evaluate(() => window.NeDotifyToast.show('Готово','success'));
                const statusBottom=await page.locator('#network-banner').evaluate(el=>el.getBoundingClientRect().bottom);
                const toastTop=await page.locator('.toast').evaluate(el=>el.getBoundingClientRect().top);
                assert.ok(toastTop>=statusBottom,`Simultaneous notifications must not overlap: ${toastTop} < ${statusBottom}`);
                await page.locator('.toast-close').click();
                await page.locator('.toast').waitFor({state:'detached'});
                await page.locator('#network-banner').evaluate(el=>el.classList.add('hidden'));
                console.log(`PASS ${style}/${width}: top status banner and notification stack`);
            }
            await page.close();
        }
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
