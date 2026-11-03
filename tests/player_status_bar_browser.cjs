// Run with Node and Playwright available in NODE_PATH. Uses shipped HTML/CSS/JS,
// a disposable loopback server, and fake media facts; never opens a user profile.
const { chromium } = require('playwright');
const { readFileSync, existsSync, mkdirSync } = require('node:fs');
const { resolve, extname } = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = resolve(__dirname, '..', 'ui');
const player = readFileSync(resolve(root, 'web_new_v2/js/player.js'), 'utf8');
const bindings = player.slice(player.indexOf("    setupDragBar('mp-progress-track'"), player.indexOf('    // Volume bar drag'));
const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const path = resolve(root, pathname.startsWith('/MACos_ui/') ? '.' + pathname : 'web_new_v2/' + (pathname === '/' ? 'index.html' : pathname.slice(1)));
  if (!path.startsWith(root + require('node:path').sep) || !existsSync(path)) { res.writeHead(404); res.end(); return; }
  let body = readFileSync(path);
  if (path.endsWith('index.html')) body = body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
    .replace('</head>', '<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
  if (path.endsWith('/player.js') || path.endsWith('\\player.js')) body = body.toString() + `
export function fixture(duration = 120000, position = 30000) {
  playbackState.durationMs = duration; playbackState.positionMs = position;
  playbackState.track = { id: 'fixture' }; playbackState.status = 'paused';
  activeAudio = { currentTime: position / 1000, duration: duration / 1000, paused: true };
  lastSeekTime = 0; isSeeking = false;
  ${bindings}
}
export { playbackState as fixtureState };`;
  res.setHeader('Content-Type', ({'.html':'text/html','.css':'text/css','.js':'text/javascript','.png':'image/png','.woff2':'font/woff2'})[extname(path)] || 'application/octet-stream');
  res.end(body);
});

(async () => {
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();
  for (const style of ['current','macos']) for (const mode of ['light','dark']) {
   await page.setViewportSize({width:1000,height:800});
   await page.goto(`http://127.0.0.1:${server.address().port}`);
   await page.addScriptTag({url:'/js/lucide.min.js'});
   await page.evaluate(async ({style,mode})=>{
    document.documentElement.dataset.uiStyle=style;
    document.documentElement.dataset.theme=mode;
    document.documentElement.dataset.macosMode=mode;
    document.querySelector('#app-splash')?.remove();
    document.querySelectorAll('.view-page').forEach(el=>el.classList.remove('active'));
    document.querySelector('#view-player').classList.add('active');
    window.player=await import('/js/player.js'); player.initPlayer(); player.fixture();
    window.toggleMiniPlayerMode=()=>document.body.classList.remove('mini-player-active');
    player.onStateChanged('paused');
    document.querySelector('#lyrics-content').innerHTML='<p class="lyric-line active">Playing line <span class="lyric-word">word</span></p><p class="lyric-line">Upcoming lyric</p>';

   },{style,mode});
   if (style === 'macos') {
    assert.ok(await page.locator('#pp-btn-play').isVisible(),'main transport must remain visible in ordinary macOS mode');
    const colors=await page.evaluate(()=>({line:getComputedStyle(document.querySelector('#lyrics-content .lyric-line.active')).color,title:getComputedStyle(document.querySelector('#pp-header-title')).color,word:getComputedStyle(document.querySelector('.lyric-word')).getPropertyValue('--lyrics-word-active').trim()}));
    assert.equal(colors.line,colors.title,'active lyrics use the same readable ink as the title');
    assert.ok(colors.word,'word timing fill has a mode-aware ink token');
   }
   const before=await page.locator('#pb-btn-next').boundingBox();
   await page.evaluate(()=>player.onStateChanged('playing'));
   await page.waitForTimeout(260);
   assert.deepEqual(await page.locator('#pb-btn-next').boundingBox(),before,'bottom transport neighbours must remain fixed');
   assert.ok(Math.abs(await page.locator('#pb-btn-play').evaluate(el=>parseFloat(getComputedStyle(el).width))-64)<.2);
   await page.locator('#pp-btn-expand').click({timeout:3000});
   assert.equal(await page.locator('#pp-btn-expand').getAttribute('aria-pressed'),'true');
   await page.waitForTimeout(550);
   const expanded=await page.locator('#view-player').boundingBox();
   assert.ok(expanded.width>970 && expanded.height>740,JSON.stringify(expanded));
   assert.ok(await page.locator('#player-lyrics-scroll').isVisible());
   assert.ok(await page.locator('#pp-btn-play').isVisible());
   if (process.env.STATUS_SCREENSHOTS) {mkdirSync(process.env.STATUS_SCREENSHOTS,{recursive:true});await page.screenshot({path:resolve(process.env.STATUS_SCREENSHOTS,`${style}-${mode}-expanded.png`)})}
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('#pp-btn-expand').getAttribute('aria-pressed'),'false');
   await page.setViewportSize({width:340,height:64});
   await page.evaluate(()=>{document.body.classList.add('mini-player-active');player.onStateChanged('paused');player.seekTo(30000)});
   const buttons=await page.locator('#mini-player-overlay button:visible').evaluateAll(es=>es.map(e=>e.id));
   assert.deepEqual(buttons,['mp-btn-prev','mp-btn-play','mp-btn-next']);
   const mini=await page.locator('#mini-player-overlay').boundingBox();
   assert.ok(mini.width===340 && mini.height===64,JSON.stringify(mini));
   const next=await page.locator('#mp-btn-next').boundingBox();
   await page.evaluate(()=>player.onStateChanged('playing'));
   await page.waitForTimeout(260);
   assert.deepEqual(await page.locator('#mp-btn-next').boundingBox(),next,'mini neighbours must remain fixed');
   assert.ok(Math.abs(await page.locator('#mp-btn-play').evaluate(el=>parseFloat(getComputedStyle(el).width))-40)<.2);
   await page.emulateMedia({reducedMotion:'reduce'});
   assert.equal(await page.locator('#mp-btn-play').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
   if (process.env.STATUS_SCREENSHOTS) await page.screenshot({path:resolve(process.env.STATUS_SCREENSHOTS,`${style}-${mode}-mini.png`)});
   await page.emulateMedia({reducedMotion:'no-preference'});
   const seek=await page.locator('#mp-progress-track').boundingBox();
   assert.ok(seek.height>=16,'mini seek has a usable fixed hit target');
   await page.mouse.click(seek.x+seek.width*.75,seek.y+seek.height/2);
   assert.ok(Math.abs(await page.evaluate(()=>player.fixtureState.positionMs)-90000)<2000);
   await page.keyboard.press('Escape');
   assert.equal(await page.evaluate(()=>document.body.classList.contains('mini-player-active')),false);
   console.log(`PASS status bar + fullscreen ${style} ${mode}`);
  }
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>server.close());
