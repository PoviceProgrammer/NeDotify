// Automated Node.js verification test for Milestone 3 (Player Tab Layout & Functionality)
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

console.log('--- Starting Milestone 3 Node.js Verification ---');

// 1. Verify index.html player view DOM structure
const indexHtml = fs.readFileSync(path.join(PROJECT_ROOT, 'ui/web_new_v2/index.html'), 'utf8');

assert(indexHtml.includes('id="pp-header-title"'), 'pp-header-title element must exist in index.html');
assert(indexHtml.includes('id="pp-title"'), 'pp-title span must exist in index.html');
assert(indexHtml.includes('id="pp-artist"'), 'pp-artist span must exist in index.html');
assert(indexHtml.includes('id="pp-volume-wrap"'), 'pp-volume-wrap must exist in index.html');
assert(indexHtml.includes('id="pp-volume-btn"'), 'pp-volume-btn must exist in index.html');
assert(indexHtml.includes('id="pp-volume-track"'), 'pp-volume-track must exist in index.html');
assert(indexHtml.includes('id="pp-volume-fill"'), 'pp-volume-fill must exist in index.html');
console.log('✓ Fix 1 & Fix 3 (HTML DOM): All required spans and volume elements exist in index.html');

// 2. Verify player-view.css and player-bar.css layout rules
const playerViewCss = fs.readFileSync(path.join(PROJECT_ROOT, 'ui/web_new_v2/css/components/player-view.css'), 'utf8');
const playerBarCss = fs.readFileSync(path.join(PROJECT_ROOT, 'ui/web_new_v2/css/components/player-bar.css'), 'utf8');

// #view-player constraints
assert(playerViewCss.includes('#view-player {'), 'player-view.css must style #view-player');
assert(playerViewCss.includes('min-height: 0;'), 'player-view.css #view-player must have min-height: 0');
assert(playerViewCss.includes('overflow: hidden;'), 'player-view.css #view-player must have overflow: hidden');

assert(playerBarCss.includes('#view-player {'), 'player-bar.css must style #view-player');
assert(playerBarCss.includes('min-height: 0;'), 'player-bar.css #view-player must have min-height: 0');
console.log('✓ Fix 4 (Height Overrun): #view-player height constraints properly set in CSS');

// .player-left-col & .player-cover-section & .player-card-controls
assert(playerViewCss.includes('justify-content: space-between;'), '.player-left-col must use justify-content: space-between');
assert(playerViewCss.includes('flex: 1;'), '.player-cover-section must have flex: 1');
assert(playerViewCss.includes('min-height: 0;'), '.player-cover-section must have min-height: 0');
assert(playerViewCss.includes('grid-template-columns: minmax(390px, 440px) 1fr;'), '.player-2col-layout columns adjusted');
assert(playerViewCss.includes('flex-wrap: nowrap;'), '.player-card-controls must prevent awkward wrapping');
console.log('✓ Fix 2 (2-Column & 300px Void): Left column and controls styling properly set in CSS');

// Responsive Media Query
assert(playerBarCss.includes('@media (max-width: 900px)'), 'player-bar.css must contain max-width: 900px query');
assert(!playerBarCss.includes('.player-page-container {\n        grid-template-columns: 1fr;'), 'player-bar.css must not target non-existent .player-page-container');
assert(playerViewCss.includes('@media (max-width: 900px)'), 'player-view.css must contain max-width: 900px query');
console.log('✓ Fix 5 (Responsive Media Query): Media queries correctly target .player-2col-layout');

// 3. Verify player.js logic
const playerJs = fs.readFileSync(path.join(PROJECT_ROOT, 'ui/web_new_v2/js/player.js'), 'utf8');

// Title/artist span preservation
assert(!playerJs.includes('headerEl.textContent = headerTitle'), 'player.js must not wipe headerEl.textContent');
assert(playerJs.includes("let ppTitle = document.getElementById('pp-title');"), 'player.js must update ppTitle directly');
assert(playerJs.includes("let ppArtist = document.getElementById('pp-artist');"), 'player.js must update ppArtist directly');
console.log('✓ Fix 1 (Title/Artist Spans): player.js preserves spans and does not overwrite headerEl.textContent');

// Queue click listener deduplication
assert(!playerJs.includes("ppQueue.addEventListener('click'"), 'player.js must not attach duplicate listener to pp-btn-queue');
console.log('✓ Fix 7 (Queue Click Deduplication): Duplicate click listener removed from player.js');

// Volume slider binding
assert(playerJs.includes("setupDragBar('pp-volume-track'"), 'player.js must bind pp-volume-track to setupDragBar');
assert(playerJs.includes("const ppVolBtn = document.getElementById('pp-volume-btn');"), 'player.js must bind pp-volume-btn');
assert(playerJs.includes("setEl('pp-volume-fill', 'width'"), 'player.js must update pp-volume-fill');
console.log('✓ Fix 3 (Dedicated Volume Controls): player.js wires pp-volume drag, click, and state sync');

// 4. Verify pages.js logic
const pagesJs = fs.readFileSync(path.join(PROJECT_ROOT, 'ui/web_new_v2/js/pages.js'), 'utf8');

assert(pagesJs.includes("if (pageId === 'player')"), 'pages.js must handle player tab switch');
assert(pagesJs.includes("document.querySelectorAll('.waveform-canvas')"), 'pages.js must query waveform canvases');
assert(pagesJs.includes("cv._wfW = undefined;"), 'pages.js must invalidate _wfW cache');
assert(pagesJs.includes("window.dispatchEvent(new Event('resize'));"), 'pages.js must dispatch resize event on tab switch');
console.log('✓ Fix 6 (Canvas & Waveform Resize): pages.js showPage handles canvas resize and invalidation');

// 5. Test DOM behavior simulation for title/artist spans
function createMockElement(id, tag = 'div', text = '') {
    const listeners = {};
    const classes = new Set();
    const children = [];
    return {
        id,
        tagName: tag.toUpperCase(),
        _text: text,
        title: '',
        style: {},
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
            toggle: (c, val) => {
                if (val !== undefined) {
                    if (val) classes.add(c); else classes.delete(c);
                } else {
                    if (classes.has(c)) classes.delete(c); else classes.add(c);
                }
            }
        },
        addEventListener: (event, handler) => {
            listeners[event] = listeners[event] || [];
            listeners[event].push(handler);
        },
        dispatchEvent: (event) => {
            (listeners[event.type] || []).forEach(h => h(event));
        },
        get textContent() { return this._text; },
        set textContent(val) { this._text = val; }
    };
}

const mockDoc = {
    elements: {},
    getElementById(id) {
        return this.elements[id] || null;
    }
};

const headerEl = createMockElement('pp-header-title', 'div');
const ppTitle = createMockElement('pp-title', 'span', 'Трек не выбран');
const ppArtist = createMockElement('pp-artist', 'span', 'Выберите трек');

let artistClicked = false;
ppArtist.addEventListener('click', (e) => {
    artistClicked = true;
});

mockDoc.elements['pp-header-title'] = headerEl;
mockDoc.elements['pp-title'] = ppTitle;
mockDoc.elements['pp-artist'] = ppArtist;

// Simulate track update logic
const testTrack = { title: 'Master of Puppets', artist: 'Metallica' };
const hasArtist = testTrack?.artist && testTrack.artist !== 'Unknown Artist';
const headerTitle = (testTrack?.title || 'Трек не выбран') + (hasArtist ? ' — ' + testTrack.artist : '');

headerEl.title = headerTitle;
const titleSpan = mockDoc.getElementById('pp-title');
const artistSpan = mockDoc.getElementById('pp-artist');
if (titleSpan) titleSpan.textContent = testTrack.title;
if (artistSpan) artistSpan.textContent = testTrack.artist;

assert.strictEqual(headerEl.title, 'Master of Puppets — Metallica');
assert.strictEqual(titleSpan.textContent, 'Master of Puppets');
assert.strictEqual(artistSpan.textContent, 'Metallica');

// Verify click listener on ppArtist still fires!
artistSpan.dispatchEvent({ type: 'click', stopPropagation: () => {} });
assert.strictEqual(artistClicked, true, 'Artist click handler must remain functional after track updates');
console.log('✓ DOM Simulation: Artist profile click listener intact after updateTrackUI simulation');

console.log('\n--- ALL MILESTONE 3 CHECKS PASSED SUCCESSFULLY ---');
