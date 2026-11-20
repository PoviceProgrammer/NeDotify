// Run with Node and Playwright available in NODE_PATH. Uses shipped HTML/CSS/JS,
// a disposable loopback server, and fake media facts; never opens a user profile.
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
const { readFileSync, existsSync, mkdirSync } = require('node:fs');
const { resolve, extname } = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = resolve(__dirname, '..', 'ui');
const player = readFileSync(resolve(root, 'web_new_v2/js/player.js'), 'utf8');
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
}
export { playbackState as fixtureState };`;
  res.setHeader('Content-Type', ({'.html':'text/html','.css':'text/css','.js':'text/javascript','.png':'image/png','.woff2':'font/woff2'})[extname(path)] || 'application/octet-stream');
  res.end(body);
});

(async () => {
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH});
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
   await page.waitForFunction(()=>Math.abs(parseFloat(getComputedStyle(document.querySelector('#pb-btn-play')).width)-48)<.2,'play button stays a fixed 48px circle');
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
   await page.mouse.move(20, 500);
   await page.evaluate(()=>{
    window.miniResizeCalls=[];
    window.pywebview={api:{set_mini_player_expanded:(...args)=>miniResizeCalls.push(args)}};
    document.body.classList.add('mini-player-active');player.onStateChanged('paused');player.seekTo(30000)
   });
   const card=page.locator('#mini-player-overlay');
   const details=page.locator('#mp-details');
   assert.equal(await details.getAttribute('inert'),'');
   await card.evaluate(el=>Promise.all(el.getAnimations().map(animation=>animation.finished)));
   assert.deepEqual(await card.boundingBox(),{x:330,y:0,width:340,height:64});
   await page.mouse.move(420, 28);
   await page.waitForFunction(()=>document.querySelector('#mini-player-overlay').dataset.expanded==='true');
   await page.waitForTimeout(300);
   assert.deepEqual(await card.boundingBox(),{x:270,y:0,width:460,height:244});
   const visibleButtons=await card.locator('button:visible').evaluateAll(es=>es.map(e=>e.id));
   assert.deepEqual(visibleButtons,['mp-btn-like','mp-btn-prev','mp-btn-play','mp-btn-next','mp-btn-dislike','mp-volume-btn','mp-btn-restore','mp-btn-close']);
   assert.deepEqual(await page.evaluate(()=>miniResizeCalls),[[true,true]]);
   await page.mouse.move(20,500);
   await page.waitForFunction(()=>document.querySelector('#mini-player-overlay').dataset.expanded==='false');
   await page.waitForTimeout(300);
   assert.deepEqual(await card.boundingBox(),{x:330,y:0,width:340,height:64});
   assert.equal(await details.getAttribute('inert'),'');
   await page.emulateMedia({reducedMotion:'reduce'});
   await card.locator('.mp-compact-row').focus();
   await page.keyboard.press('Enter');
   assert.equal(await card.evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
   assert.equal(await details.getAttribute('inert'), null);
   assert.deepEqual(await page.evaluate(()=>miniResizeCalls.at(-1)),[true,false]);
   if (process.env.STATUS_SCREENSHOTS) await page.screenshot({path:resolve(process.env.STATUS_SCREENSHOTS,`${style}-${mode}-mini.png`)});
   const seek=await page.locator('#mp-progress-track').boundingBox();
   assert.ok(seek.height>=16,'mini seek has a usable fixed hit target');
   await page.mouse.click(seek.x+seek.width*.75,seek.y+seek.height/2);
   assert.ok(Math.abs(await page.evaluate(()=>player.fixtureState.positionMs)-90000)<2000);
   const seekTrack = page.locator('#mp-progress-track');
   for (const sliderStyle of ['solid','line','thin-line','smooth','panel']) {
    await page.evaluate(async type => {
     const {applySliderType} = await import('/js/settings.js');
     applySliderType(type);
    }, sliderStyle);
    assert.equal(await seekTrack.evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)', 'the seek target must not paint a rectangular background');
    const rail = await seekTrack.evaluate(el=>getComputedStyle(el,'::before').display);
    if (sliderStyle === 'solid') {
     assert.equal(rail,'none');
     assert.ok(await seekTrack.locator('.progress-wave').isVisible(),'the wave must still paint the duration');
    } else {
     assert.notEqual(rail,'none','line-based styles retain their narrow rail');
    }
   }
   await page.keyboard.press('Escape');
   await page.emulateMedia({reducedMotion:'no-preference'});
   assert.equal(await page.evaluate(()=>document.body.classList.contains('mini-player-active')),false);
   // Native resize supplies the viewport for every frame, including mid-animation sizes.
   await page.mouse.move(20,500);
   await page.setViewportSize({width:340,height:64});
   await page.evaluate(()=>{
    document.body.classList.add('mini-player-active','mini-player-native');
    document.querySelector('#mini-player-overlay').dataset.expanded='false';
   });
   const backdrop=page.locator('#macos-backdrop');
   assert.equal(await backdrop.evaluate(el=>getComputedStyle(el).display),'none');
   for (const [width,height,expanded] of [[340,64,false],[410,180,true],[460,244,true],[410,180,false],[340,64,false]]) {
    await card.evaluate((el,value)=>el.dataset.expanded=String(value),expanded);
    await page.setViewportSize({width,height});
    assert.deepEqual(await card.boundingBox(),{x:0,y:0,width,height});
    const frame=await card.evaluate(el=>{
     const css=getComputedStyle(el);
     return [css.borderBottomLeftRadius,css.transitionDuration,css.animationName];
    });
    assert.deepEqual(frame,['0px','0s','none']);
   }
   console.log(`PASS status bar + fullscreen ${style} ${mode}`);
  }
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>server.close());
