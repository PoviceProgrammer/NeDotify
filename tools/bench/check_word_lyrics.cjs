/* Real Chromium rendering check. Transport/clock fixture; shipped renderer/CSS. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require(process.env.NEDOTIFY_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '../..');
const ui = path.join(root, 'ui/web_new_v2');
const styles = [...fs.readFileSync(path.join(ui, 'index.html'), 'utf8').matchAll(/<link\s+rel="stylesheet"\s+href="([^"]+)"/g)]
    .map(match => `<link rel="stylesheet" href="/${match[1]}">`).join('\n');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'nedotify-word-lyrics-'));
const player = `export function getCurrentTrack(){return window.track;}
export function getLyricsPlaybackClock(){return window.clock;}
export function seekTo(positionMs){window.clock.positionMs=positionMs;window.lastSeek=positionMs;document.dispatchEvent(new Event('nedotify:lyrics_clock_changed'));}`;
const server = http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (name === '/harness') {
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        return res.end(`<!doctype html><html data-theme="dark"><head>
${styles}
<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css">
<style>body{padding:30px;background:var(--bg-main,#19151f)}#view-player{display:block;position:relative;inset:auto;width:760px;height:560px}.player-2col-layout{grid-template-columns:minmax(0,1fr)!important;grid-template-rows:minmax(0,1fr)!important}.player-glass-card{height:500px}#player-lyrics-scroll{display:block;position:relative;height:440px;width:650px}#lyrics-content{display:block}.lyrics-track{width:100%}</style></head><body>
<div id="view-player"><div class="player-2col-layout"><div class="player-glass-card player-right-col"><div id="player-lyrics-scroll" class="lyrics-viewport"><div id="lyrics-content" class="lyrics-track"></div></div></div></div></div>
<div id="lyrics-container" style="display:none"><div id="overlay-lyrics-content" class="lyrics-track"></div></div>
</body></html>`);
    }
    if (name === '/js/player.js') {res.setHeader('Content-Type', 'text/javascript'); return res.end(player);}
    if (name === '/js/utils.js') {res.setHeader('Content-Type', 'text/javascript'); return res.end('export function renderIcons() {}');}
    const base = name.startsWith('/MACos_ui/') ? path.join(root, 'ui') : ui;
    const file = path.resolve(base, '.' + name);
    if (!file.startsWith(base + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404); return res.end();}
    const types = {'.js':'text/javascript', '.css':'text/css', '.woff2':'font/woff2'};
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(res);
});
(async () => {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const browser = await chromium.launch({headless:true});
    try {
        for (const [style, mode] of [['current','dark'], ['current','light'], ['macos','dark'], ['macos','light']]) {
            const page = await browser.newPage({viewport:{width:900,height:650}});
            page.setDefaultTimeout(8000);
            const errors = [];
            page.on('pageerror', error => errors.push(String(error)));
            await page.goto(`http://127.0.0.1:${server.address().port}/harness`);
            await page.evaluate(async ({style,mode}) => {
                document.documentElement.dataset.uiStyle = style;
                document.documentElement.dataset.theme = mode;
                document.documentElement.dataset.macosMode = mode;
                window.settings = {lyrics:{mode:'auto',animations:'standard'}};
                window.track = {title:'Апрель',artist:'Скриптонит',source:'youtube',source_id:'abcdefghijk'};
                const trackKey = JSON.stringify(['youtube','abcdefghijk','Апрель','Скриптонит','','']);
                window.clock = {positionMs:500,paused:false,buffering:false,seeking:false,playbackRate:1,trackKey};
                window.lyrics = await import('/js/lyrics.js');
                lyrics.initLyrics();
                lyrics.loadCurrentTrackLyrics();
                window.payload = {status:'found',match_type:'exact',syncType:'word',plainLyrics:'Апрель — рядом',syncedLyrics:'[00:00] Апрель — рядом',lines:[
                    {startMs:0,endMs:3000,words:[{text:'Апрель — ',startMs:0,endMs:1000},{text:'рядом',startMs:1000,endMs:3000}]}
                ]};
                lyrics.renderLyrics(payload);
            }, {style,mode});
            const fill = () => page.locator('#lyrics-content .lyric-word').first().evaluate(el => el.style.getPropertyValue('--lyric-word-fill'));
            await page.waitForFunction(() => document.querySelector('#lyrics-content .lyric-word')?.style.getPropertyValue('--lyric-word-fill') === '50.00%');
            assert.equal(await fill(), '50.00%');
            await page.evaluate(() => {clock.paused=true; document.dispatchEvent(new Event('nedotify:lyrics_clock_changed'));});
            await page.screenshot({path:path.join(output, `${style}-${mode}-word-lyrics.png`), animations:'disabled'});
            assert.equal(await page.locator('#lyrics-content .lyric-word').first().evaluate(el => getComputedStyle(el).backgroundClip), 'text');
            if (style === 'macos') {
                assert.match(await page.locator('#lyrics-content .lyric-word').first().evaluate(el => getComputedStyle(el).backgroundImage), /255, 255, 255/);
            }
            await page.locator('#lyrics-content .lyric-word').nth(1).click();
            assert.equal(await page.evaluate(() => window.lastSeek), 1000);
            await page.evaluate(() => {settings.lyrics.mode='line'; window.dispatchEvent(new Event('nedotify:lyrics_settings_changed'));});
            assert.equal(await page.locator('#lyrics-content .lyric-word').count(), 0);
            assert.match(await page.locator('#lyrics-content').innerText(), /Апрель/);
            await page.evaluate(() => {settings.lyrics.mode='word'; window.dispatchEvent(new Event('nedotify:lyrics_settings_changed'));});
            assert.equal(await page.locator('#lyrics-content .lyric-word').count(), 2);
            await page.setViewportSize({width:450,height:650});
            await page.evaluate(() => document.getElementById('player-lyrics-scroll').style.width='380px');
            assert.equal(await page.locator('#lyrics-content .lyric-word').first().evaluate(el => el.getBoundingClientRect().width <= 380), true);
            assert.deepEqual(errors, []);
            console.log(`${style}/${mode}: word fill, pause, word seek, settings fallback, wrapping: PASS`);
            await page.close();
        }
        console.log(`Screenshots: ${output}`);
    } finally {await browser.close(); server.close();}
})().catch(error => {console.error(error); server.close(); process.exitCode=1;});
