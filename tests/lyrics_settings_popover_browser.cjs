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

(async () => {
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const browser = await chromium.launch({headless: true});
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
      await page.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
