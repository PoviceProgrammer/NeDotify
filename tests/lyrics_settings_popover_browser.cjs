// The lyrics settings popover must stay clickable in every player layout.
//
// Regression: `#app-container` is a stacking context (position: relative;
// z-index: 10). Expanding the player moves `#view-player` to <body> with
// z-index: 80, while the popover used to remain inside `#app-container` at
// z-index: 10001 — but that number only competes *inside* the container, so
// the expanded player painted over it and the button looked dead. The popover
// is now re-parented to <body> at init.
//
// Run with Node and Playwright available in NODE_PATH (or PLAYWRIGHT_CORE_PATH).
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
const { readFileSync, existsSync, statSync } = require('node:fs');
const { resolve, extname } = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');

const root = resolve(__dirname, '../ui');
const types = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2'};
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const file = resolve(root, pathname.startsWith('/MACos_ui/') ? '.' + pathname : 'web_new_v2/' + (pathname === '/' ? 'index.html' : pathname.slice(1)));
  if (!file.startsWith(root + require('node:path').sep) || !existsSync(file) || !statSync(file).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  res.setHeader('Content-Type', types[extname(file)] || 'application/octet-stream');
  res.end(readFileSync(file));
});

async function boot(page, style) {
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(async style => {
    document.getElementById('app-splash')?.remove();
    document.documentElement.dataset.uiStyle = style;
    window.settings = {theme: {}, interface: {}, optimization: {}};
    window.awaitBridge = async () => true;
    window.__saves = [];
    window.pywebview = {api: {
      get_lyrics_display_settings: async () => ({fontSize: 24}),
      save_lyrics_display_settings: async payload => { window.__saves.push(payload); return true; },
    }};
    const module = await import('/js/lyrics-settings-popover.js');
    module.initLyricsSettingsPopover();
  }, style);
  await page.waitForTimeout(250);
}

async function checkChosenLyrics(page) {
  await page.evaluate(async () => {
    const player = await import('/js/player.js');
    const lyrics = await import('/js/lyrics.js');
    const first = {source: 'youtube', source_id: 'first', title: 'Original title', artist: 'Original artist', duration: 120};
    const second = {...first, source_id: 'second', title: 'Next track'};
    window.searchCalls = [];
    window.appliedTracks = [];
    window.automatic = [];
    Object.assign(window.pywebview.api, {
      get_lyrics: (...args) => new Promise(resolve => window.automatic.push({id: args[5], resolve})),
      search_lyrics: async (...args) => {
        window.searchCalls.push(args);
        return {success: true, candidates: [{source: 'LRCLIB', trackName: 'Edited title'}]};
      },
      apply_lyrics_candidate: (candidate, track) => {
        window.appliedTracks.push(track.source_id);
        return new Promise(resolve => { window.resolveSelection = resolve; });
      },
    });
    window.setLyricTrack = track => {
      const next = track === 'first' ? first : second;
      player.onTrackChanged(next);
      document.dispatchEvent(new CustomEvent('nedotify:track_changed', {detail: next}));
    };
    document.getElementById('view-player').classList.add('active');
    lyrics.initLyrics();
    window.setLyricTrack('first');
    document.getElementById('btn-lyrics-settings-page').click();
    document.getElementById('btn-lsp-action-pick-version').click();
  });
  const modal = page.locator('#modal-lyrics-search');
  const field = modal.locator('#input-lyrics-search-query');
  await field.waitFor();
  assert.equal(await field.inputValue(), 'Original artist - Original title');
  await field.fill('Edited title');
  await field.press('Enter');
  await page.waitForFunction(() => searchCalls.length === 2);
  assert.deepEqual(await page.evaluate(() => searchCalls[1]), ['Edited title', '', '', 0]);

  const result = modal.locator('.lyrics-search-item');
  await result.click();
  await page.evaluate(() => resolveSelection({success: false, error: 'Test provider failure'}));
  assert.equal(await modal.isVisible(), true);
  await page.waitForFunction(() => !document.getElementById('lyrics-search-results-list').hasAttribute('aria-busy'));

  await result.click();
  await page.evaluate(() => resolveSelection({success: true, lyrics: {status: 'found', plainLyrics: 'Chosen fixture lyrics'}}));
  await modal.waitFor({state: 'hidden'});
  const playerText = page.locator('#lyrics-content');
  const overlayText = page.locator('#lyrics-overlay .lyrics-track');
  assert.match(await playerText.textContent(), /Chosen fixture lyrics/);
  assert.match(await overlayText.textContent(), /Chosen fixture lyrics/);

  await page.evaluate(() => {
    const request = automatic[0];
    const late = {status: 'found', plainLyrics: 'Old automatic text', request_id: request.id, revision: 1};
    request.resolve(late);
    document.dispatchEvent(new CustomEvent('nedotify:lyrics_ready', {detail: late}));
    window.NeDotify.openLyricsSearchModal();
  });
  assert.match(await playerText.textContent(), /Chosen fixture lyrics/);

  await result.click();
  await page.evaluate(() => {
    window.setLyricTrack('second');
    automatic.at(-1).resolve({status: 'found', plainLyrics: 'Second track lyrics'});
    resolveSelection({success: true, lyrics: {status: 'found', plainLyrics: 'A second choice for the first track'}});
  });
  await page.waitForFunction(() => document.getElementById('lyrics-content').textContent.includes('Second track lyrics'));
  assert.deepEqual(await page.evaluate(() => appliedTracks), ['first', 'first', 'first']);
  assert.match(await playerText.textContent(), /Second track lyrics/);
  console.log('Lyrics selection: edited query, retry, instant rendering, stale results and track changes passed');
}

(async () => {
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH});
  try {
    for (const style of ['current', 'macos']) for (const width of [1280, 1600]) {
      const page = await browser.newPage({viewport: {width, height: 900}});
      await boot(page, style);

      for (const layout of ['page', 'expanded']) {
        const report = await page.evaluate(async layout => {
          document.querySelectorAll('.view-page').forEach(v => v.classList.remove('active'));
          const view = document.getElementById('view-player');
          view.classList.add('active');
          if (layout === 'expanded') {
            // Same move `setPlayerExpanded(true)` performs in player.js.
            const marker = document.createComment('player view home');
            view.before(marker);
            document.body.appendChild(view);
            view.classList.add('player-expanded');
            document.documentElement.classList.add('player-view-expanded');
          }
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

          const trigger = document.getElementById('btn-lyrics-settings-page');
          trigger.click();
          await new Promise(r => requestAnimationFrame(r));

          const popover = document.getElementById('lyrics-display-settings-popover');
          const rect = popover.getBoundingClientRect();
          const hit = document.elementFromPoint(
            Math.round(rect.x + rect.width / 2),
            Math.round(rect.y + rect.height / 2),
          );
          const slider = document.getElementById('slider-lyrics-font-size');
          slider.value = '30';
          slider.dispatchEvent(new Event('input', {bubbles: true}));
          await new Promise(r => setTimeout(r, 400));

          const result = {
            parent: popover.parentElement?.id || popover.parentElement?.tagName,
            hidden: popover.classList.contains('hidden'),
            onTop: !!hit && popover.contains(hit),
            size: getComputedStyle(document.documentElement).getPropertyValue('--lyrics-font-size').trim(),
            saves: window.__saves.slice(),
          };
          document.getElementById('btn-close-lsp').click();
          return result;
        }, layout);

        assert.equal(report.parent, 'BODY', `${style}/${width}/${layout}: popover is at the top level`);
        assert.equal(report.hidden, false, `${style}/${width}/${layout}: popover opens`);
        assert.equal(report.onTop, true, `${style}/${width}/${layout}: popover is above the player`);
        assert.equal(report.size, '30px', `${style}/${width}/${layout}: slider applies`);
        assert.deepEqual(report.saves.at(-1), {fontSize: 30, fontWeight: 700, lineHeight: 1.45, textAlign: 'center'}, `${style}/${width}/${layout}: save payload is a dict`);
        console.log(`PASS ${style}/${width}/${layout}`);
      }
      if (style === 'current' && width === 1280) {
        await page.route('**/js/main.js*', route => route.fulfill({
          contentType: 'text/javascript',
          body: '',
        }));
        await boot(page, style);
        await checkChosenLyrics(page);
      }
      await page.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
