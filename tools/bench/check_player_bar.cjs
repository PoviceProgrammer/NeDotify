/* Browser geometry regression for the shipped bottom player and seek styles. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const os = require('node:os');
const {chromium} = require(process.env.NEDOTIFY_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '../..');
const ui = path.join(root, 'ui/web_new_v2');
const index = fs.readFileSync(path.join(ui, 'index.html'), 'utf8');
const styles = [...index.matchAll(/<link\s+rel="stylesheet"\s+href="([^"]+)"/g)]
    .map(match => `<link rel="stylesheet" href="/${match[1]}">`).join('\n');
const bar = index.slice(index.indexOf('<div id="player-bar">'), index.indexOf('<input id="lib-cover-file"'));
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'nedotify-player-layout-'));
const server = http.createServer((req,res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (name === '/') {
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        return res.end(`<!doctype html><html data-theme="dark" data-progress-style="solid"><head>${styles}
<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css">
<script defer src="/js/lucide.min.js"></script></head><body>${bar}</body></html>`);
    }
    const base = name.startsWith('/MACos_ui/') ? path.join(root, 'ui') : ui;
    const file = path.resolve(base, '.' + name);
    if (!file.startsWith(base + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);return res.end();}
    res.setHeader('Content-Type', {'.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(res);
});
(async () => {
    await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
    const browser = await chromium.launch({headless:true});
    try {
        const page = await browser.newPage();
        for (const style of ['current','macos']) for (const width of [1920,1280,900,760,600]) {
            await page.setViewportSize({width,height:700});
            await page.goto(`http://127.0.0.1:${server.address().port}/`);
            await page.evaluate(style => {
                document.documentElement.dataset.uiStyle = style;
                document.documentElement.dataset.macosMode = 'dark';
                document.getElementById('pb-title').textContent = 'BLACK SIEMENS';
                document.getElementById('pb-artist').textContent = 'PHARAOH';
                document.getElementById('pb-time-current').textContent = '1:29';
                document.getElementById('pb-time-total').textContent = '3:04';
                document.getElementById('pb-progress-fill').style.transform='translateX(-52%)';
                window.lucide?.createIcons();
            }, style);
            await page.evaluate(() => document.fonts.ready);
            for (const progress of ['solid','bars','wave','hidden']) {
                await page.evaluate(value => document.documentElement.dataset.progressStyle=value,progress);
                const g = await page.evaluate(() => {
                    const rect = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                    const title=document.getElementById('pb-title');const range=document.createRange();range.selectNodeContents(title);
                    return {bar:rect('#player-bar'),track:rect('#pb-progress-track'),current:rect('#pb-time-current'),total:rect('#pb-time-total'),
                        controls:rect('.pb-controls'),buttons:rect('.pb-buttons'),like:rect('#pb-btn-like'),title:rect('#pb-title'),
                        textRight:range.getBoundingClientRect().right,likeVisible:getComputedStyle(document.getElementById('pb-btn-like')).display!=='none'};
                });
                const label=`${style}/${width}/${progress}`;
                if (width === 1920 && progress==='solid') await page.screenshot({path:path.join(output,`${style}-desktop.png`),animations:'disabled'});
                if (g.likeVisible) assert.ok(g.like.left-g.textRight <= 22,`${label}: like drifts ${Math.round(g.like.left-g.textRight)}px from title`);
                assert.ok(g.track.left >= g.bar.left && g.track.right <= g.bar.right,`${label}: seek area escapes player`);
                if (progress==='solid') {
                    assert.ok(g.current.right <= g.track.left+1,`${label}: current time must sit beside the line`);
                    assert.ok(g.total.left >= g.track.right-1,`${label}: total time must sit beside the line`);
                    const lineY=(g.track.top+g.track.bottom)/2;
                    assert.ok(Math.abs((g.current.top+g.current.bottom)/2-lineY)<=3,`${label}: time detached from line`);
                    if (width>760) assert.ok(g.track.top>=g.buttons.bottom-1,`${label}: line overlaps transport`);
                }
            }
            console.log(`${style}/${width}: like + solid/bars/wave/hidden geometry PASS`);
        }
        console.log(`Screenshots: ${output}`);
    } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
