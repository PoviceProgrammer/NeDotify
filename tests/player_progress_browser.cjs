// Run with Node and Playwright available in NODE_PATH. Uses shipped HTML/CSS/JS,
// a disposable loopback server, and fake media facts; never opens a user profile.
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
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
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  try {
    const page = await browser.newPage();
    for (const style of ['current', 'macos']) for (const width of [600, 900, 1600]) for (const mode of ['panel', 'line', 'thin-line', 'smooth', 'solid']) {
      await page.setViewportSize({width,height:900});
      await page.goto(`http://127.0.0.1:${server.address().port}`);
      await page.addScriptTag({url:'/js/lucide.min.js'});
      await page.evaluate(async ({style,mode}) => {
        document.documentElement.dataset.uiStyle = style;
        document.documentElement.dataset.progressStyle = mode;
        document.querySelector('#app-splash')?.remove();
        document.querySelectorAll('.view-page').forEach(el=>el.classList.remove('active'));
        document.querySelector('#view-player').classList.add('active');
        window.player = await import('/js/player.js'); player.fixture(); player.seekTo(30000);
        window.lucide.createIcons();
      }, {style,mode});
      const track = page.locator('#pb-progress-track');
      const trackBox = await track.boundingBox();
      const barBox = await page.locator('#player-bar').boundingBox();
      const box = mode === 'panel' ? barBox : trackBox;
      // The slider row now lives inside the transport column, centred under
      // the buttons, for every slider style (panel keeps the whole-bar drag
      // surface and tint on top of it).
      const buttonsBox = await page.locator('.pb-buttons').boundingBox();
      const barCenter = barBox.x + barBox.width / 2;
      assert.ok(Math.abs(trackBox.x + trackBox.width / 2 - barCenter) < 12, `slider row is centred in the bar ${JSON.stringify({ barBox, trackBox })}`);
      assert.ok(trackBox.y > buttonsBox.y + buttonsBox.height - 1, `slider row sits under the transport buttons ${JSON.stringify({ buttonsBox, trackBox })}`);
      assert.ok(trackBox.width >= 260 && trackBox.width <= 642, `slider row keeps a usable width ${JSON.stringify(trackBox)}`);
      assert.equal(await track.evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)', `${style} ${mode}: progress track wrapper must stay transparent`);
      if (mode === 'panel') {
        assert.equal(await track.evaluate(el=>getComputedStyle(el,'::before').display),'none','panel mode has no separate thin line');
        assert.equal(await page.locator('#pb-progress-fill').evaluate(el=>getComputedStyle(el).display),'none');
      } else if (mode === 'solid') {
        const wave = page.locator('#pb-progress-track .progress-wave');
        assert.equal(await wave.count(),1,'wave canvas is mounted from real player state');
        const waveBox = await wave.boundingBox();
        for (const id of ['pb-time-current','pb-time-total']) {
          const time = await page.locator('#'+id).boundingBox();
          assert.ok(time.y+time.height <= waveBox.y+1 || time.x+time.width <= waveBox.x || time.x >= waveBox.x+waveBox.width,
            `${id} stays clear of the wave ${JSON.stringify({time,waveBox})}`);
        }
        const painted = await wave.evaluate(canvas=>{
          const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
          const rows=new Set();for(let i=3;i<data.length;i+=4)if(data[i]>100)rows.add(Math.floor(i/4/canvas.width));return rows.size;
        });
        assert.ok(painted>=5,'played seek indicator has a visible sine contour');
      }
      if (['line', 'thin-line', 'smooth'].includes(mode)) {
        const geometry = await track.evaluate(el => ({
          line: getComputedStyle(el, '::before').height,
          thickness: getComputedStyle(el.querySelector('.seek-thumb')).width,
          thumb: getComputedStyle(el.querySelector('.seek-thumb')).display,
          paint: getComputedStyle(el, '::before').backgroundImage
        }));
        assert.ok(geometry.paint.startsWith('linear-gradient('), `visible gradient: ${JSON.stringify(geometry)}`);
        assert.equal(geometry.line, {'line':'5px','thin-line':'2px','smooth':'4px'}[mode]);
        if (mode === 'line') assert.equal(geometry.thumb, 'none');
        else assert.equal(geometry.thickness, mode === 'thin-line' ? '14px' : '4px');
      }
      const seekY = mode === 'panel' ? box.y+box.height-3 : box.y+box.height/2;
      const controlsBefore = await page.locator('#pb-btn-play').boundingBox();
      const coverBox = await page.locator('#pb-cover').boundingBox();
      const timeBox = await page.locator('#pb-time-current').boundingBox();
      assert.ok(timeBox.y >= coverBox.y + coverBox.height - 1 || timeBox.x + timeBox.width <= coverBox.x || timeBox.x >= coverBox.x + coverBox.width,
        `the time label must not overlap the artwork: ${JSON.stringify({style,width,timeBox,coverBox})}`);
      await page.mouse.move(box.x+box.width*.25,seekY);
      const controlsAfter = await page.locator('#pb-btn-play').boundingBox();
      assert.deepEqual(controlsBefore,controlsAfter,'hover must not move controls');
      await page.mouse.move(box.x+box.width*.25,seekY);
      await page.mouse.down();
      await page.mouse.move(box.x+box.width*.5,seekY);
      assert.ok(Math.abs(Number(await track.getAttribute('aria-valuenow'))-50)<.2,'full surface previews the dragged position');
      await page.mouse.move(box.x+box.width*.75,seekY);
      await page.mouse.up();
      assert.ok(Math.abs(await page.evaluate(()=>player.fixtureState.positionMs)-90000)<500);
      const prior = await page.evaluate(()=>player.fixtureState.positionMs);
      await page.locator('#pb-btn-next').evaluate(el=>el.addEventListener('click',()=>window.transportClicks=(window.transportClicks||0)+1));
      await page.locator('#pb-btn-next').click();
      assert.equal(await page.evaluate(()=>window.transportClicks),1,'transport click stays reachable');
      assert.equal(await page.evaluate(()=>player.fixtureState.positionMs),prior,'transport pointerdown cannot seek');
      if (await page.locator('#pb-volume-track').isVisible()) {
        await page.locator('#pb-volume-track').click();
        assert.equal(await page.evaluate(()=>player.fixtureState.positionMs),prior,'volume pointerdown cannot seek');
      }
      await track.focus(); await page.keyboard.press('ArrowRight');
      assert.ok(Math.abs(await page.evaluate(()=>player.fixtureState.positionMs)-(prior+5000))<2,'keyboard seeking remains available');
      const regular = page.locator('#pp-progress-track');
      await regular.scrollIntoViewIfNeeded();
      const regularBox = await regular.boundingBox();
      assert.ok(regularBox.width>80 && regularBox.height>=16);
      await page.mouse.move(regularBox.x+regularBox.width*.2,regularBox.y+regularBox.height/2);
      await page.mouse.down();
      await page.mouse.move(regularBox.x+regularBox.width*.5,regularBox.y+regularBox.height/2);
      const values = await page.locator('[id$="-progress-track"]').evaluateAll(nodes=>nodes.map(el=>el.getAttribute('aria-valuenow')));
      assert.ok(values.every(v=>v==='50.0'), `all surfaces preview together: ${values}`);
      await page.mouse.up();
      assert.ok(Math.abs(await page.evaluate(()=>player.fixtureState.positionMs)-60000)<1000);
      const clipping = await regular.evaluate(el=>getComputedStyle(el).overflow);
      assert.equal(clipping,'visible','standard thumb must not be clipped');
      assert.equal(await page.locator('#pb-panel-fill').evaluate(el=>getComputedStyle(el).visibility),mode==='panel'?'visible':'hidden');
      const playBox = await page.locator('#pb-btn-play').boundingBox();
      assert.equal(await page.evaluate(({x,y})=>document.elementFromPoint(x,y)?.closest('button')?.id,{x:playBox.x+playBox.width/2,y:playBox.y+playBox.height/2}),'pb-btn-play');
      for (const zoom of [1.25,1.5]) {
        await page.evaluate(zoom=>document.documentElement.style.zoom=zoom,zoom);
        const zoomBox = await track.boundingBox();
        const zoomBar = await page.locator('#player-bar').boundingBox();
        assert.ok(Math.abs(zoomBox.x + zoomBox.width / 2 - (zoomBar.x + zoomBar.width / 2)) < 20, `zoom ${zoom}: slider row stays centred ${JSON.stringify({zoomBar,zoomBox})}`);
      }
      await page.evaluate(()=>document.documentElement.style.zoom='');
      await page.evaluate(async mode=>{
        const settings=await import('/js/settings.js');
        const position=player.fixtureState.positionMs;
        for (const next of ['line','thin-line','smooth','solid','panel',mode]) {
          settings.applySliderType(next);
          if(player.fixtureState.positionMs!==position)throw new Error('appearance switch changed playback position');
        }
      },mode);
      if(mode==='solid') assert.equal(await page.locator('#pb-progress-track .progress-wave').evaluate(el=>getComputedStyle(el).display),'block','paused wave repaints immediately after switching');
      assert.equal(await page.locator('#opt-slider-type button[aria-pressed="true"]').getAttribute('data-val'), mode);
      const dir = process.env.PROGRESS_SCREENSHOTS;
      if (dir) { mkdirSync(dir,{recursive:true}); await page.screenshot({path:resolve(dir,`${style}-${width}-${mode}.png`)}); }
      console.log(`PASS ${style} ${width} ${mode}`);
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());

