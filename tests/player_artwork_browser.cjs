// Real player notifications, image decoding/CORS and shipped styles; no user profile.
const {chromium} = require('playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..', 'ui');
const serveArt = (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/late-error.svg') {
        setTimeout(() => { res.writeHead(404); res.end(); }, 500); return;
    }
    if (url.searchParams.get('cors') !== 'off') res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Content-Type', 'image/svg+xml');
    const color = url.pathname.includes('blue') ? '#1654e8' : '#e83818';
    const body = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="${color}"/></svg>`;
    if (url.pathname === '/late-red.svg') setTimeout(() => res.end(body), 400);
    else res.end(body);
};
const remote = http.createServer(serveArt);
const server = http.createServer((req, res) => {
    const name = new URL(req.url, 'http://localhost').pathname;
    if (name.endsWith('.svg')) { serveArt(req, res); return; }
    const file = path.resolve(root, name.startsWith('/MACos_ui/') ? '.' + name : 'web_new_v2/' + (name === '/' ? 'index.html' : name.slice(1)));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    let body = fs.readFileSync(file);
    if (file.endsWith('index.html')) body = body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', '<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
    res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.woff2':'font/woff2'})[path.extname(file)] || 'application/octet-stream');
    res.end(body);
});
(async () => {
    await Promise.all([new Promise(r => server.listen(0, '127.0.0.1', r)), new Promise(r => remote.listen(0, '127.0.0.1', r))]);
    const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
    const failures = [];
    try {
        for (const style of ['current', 'macos', 'macos-light']) {
            const page = await browser.newPage({viewport:{width:1200,height:850}});
            page.setDefaultTimeout(4000);
            await page.goto(`http://127.0.0.1:${server.address().port}`);
            await page.evaluate(async style => {
                document.getElementById('app-splash')?.remove();
                document.documentElement.dataset.uiStyle = style.startsWith('macos') ? 'macos' : 'current';
                document.documentElement.dataset.macosMode = style === 'macos-light' ? 'light' : 'dark';
                document.documentElement.style.setProperty('--player-glow-blur', '40px');
                document.documentElement.style.setProperty('--player-glow-opacity', '.55');
                document.querySelectorAll('.view-page').forEach(el => el.classList.remove('active'));
                document.getElementById('view-player').classList.add('active');
                window.player = await import('/js/player.js');
            }, style);
            const change = async url => {
                await page.evaluate(url => player.onTrackChanged({id:url,title:'Artwork fixture',artist:'Fixture',cover_url:url,autoplay:false}), url);
                await page.waitForFunction(() => { const image = document.getElementById('pb-cover'); return image.complete && image.naturalWidth > 0; });
            };
            const remoteBase = `http://127.0.0.1:${remote.address().port}`;
            await change(`${remoteBase}/red.svg`);
            await page.waitForTimeout(150);
            const ambient = await page.evaluate(() => document.documentElement.style.getPropertyValue('--ambient-glow'));
            if (!/rgb\(232,\s*56,\s*24\)/.test(ambient)) failures.push(`${style}: visible cross-origin red cover has no extracted red palette (${ambient})`);
            await change(`${remoteBase}/red.svg`);
            await page.waitForTimeout(150);
            assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue('--ambient-glow')), ambient, 'repeated cached artwork retains its palette');
            await page.evaluate(url => player.onTrackChanged({id:'slow',cover_url:url,autoplay:false}), `${remoteBase}/late-red.svg`);
            await change(`http://127.0.0.1:${server.address().port}/blue.svg`);
            await page.waitForTimeout(500);
            assert.match(await page.evaluate(() => document.documentElement.style.getPropertyValue('--ambient-glow')), /rgb\(22,\s*84,\s*232\)/, 'late successful sampling cannot restore the previous track palette');
            // A late failure from the previous track must not erase the new background.
            await page.evaluate(url => player.onTrackChanged({id:'old',cover_url:url,autoplay:false}), `${remoteBase}/late-error.svg`);
            await change(`http://127.0.0.1:${server.address().port}/blue.svg`);
            await page.waitForTimeout(700);
            const background = await page.locator('#player-bg-glow').evaluate(el => getComputedStyle(el).backgroundImage);
            if (!background.includes('blue.svg')) failures.push(`${style}: stale image failure erased current background (${background})`);
            // Palette failure must not prevent showing art from hosts without CORS.
            await change(`${remoteBase}/red.svg?cors=off`);
            await page.waitForTimeout(650);
            const box = await page.locator('.player-right-col').boundingBox();
            const png = await page.screenshot();
            const pixel = await page.evaluate(async ({png,x,y}) => {
                const image = new Image(); image.src = 'data:image/png;base64,' + png; await image.decode();
                const canvas = document.createElement('canvas'); canvas.width=image.width;canvas.height=image.height;
                const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);return [...ctx.getImageData(x,y,1,1).data];
            }, {png:png.toString('base64'), x:Math.round(box.x+box.width*.7), y:Math.round(box.y+box.height*.7)});
            if (pixel[0]-pixel[1]<15) failures.push(`${style}: cover is visible but player backdrop is still gray (${pixel})`);
            assert.ok((await page.locator('#player-bg-glow').evaluate(el => getComputedStyle(el).backgroundImage)).includes('red.svg'), 'a non-CORS cover keeps its artwork background');
            await page.evaluate(() => document.documentElement.style.setProperty('--player-glow-opacity', '0'));
            await page.waitForTimeout(600);
            assert.equal(await page.locator('#player-bg-glow').evaluate(el => getComputedStyle(el).opacity), '0', 'disabled glow is respected in both UI styles');
            await page.evaluate(() => player.onTrackChanged({id:'no-cover',autoplay:false}));
            assert.equal(await page.locator('.player-2col-layout').evaluate(el => el.classList.contains('has-player-artwork')), false);
            assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue('--player-art-color')), '', 'missing artwork clears the previous palette');
            await page.close();
        }
        assert.deepEqual(failures, []);
        console.log('PASS: artwork palettes, non-CORS fallback and stale requests in current/macOS dark/light');
    } finally { await browser.close(); server.close(); remote.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
