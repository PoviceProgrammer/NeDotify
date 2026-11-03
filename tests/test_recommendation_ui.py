"""Execute shipped recommendation JS with a small DOM/bridge stub in Node.

These checks exercise feed completion and out-of-order bridge messages without
starting the application. They do not stand in for a visual WebView smoke test.
"""

from tests.jsdom import run_node, source


def test_generated_mix_plays_its_actual_discoveries_without_playlist_substitution():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const button = {};
const card = {querySelector: () => button, addEventListener() {}};
let queued, collage;
const context = vm.createContext({
 document: {createElement: () => card}, escapeHtml: text => text,
 getCoverUrl: track => track.cover_url,
 renderPlaylistCoverCollage: rows => {collage = rows; return ''},
 window: {pywebview: {api: {play_track: (...args) => {queued = args; return Promise.resolve({success: true})}}}},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function createFeedCard('), code.indexOf('\nfunction setElText(')), context);
const tracks = [
 {source: 'deezer', source_id: '3135556', title: 'A real discovery', cover_url: 'https://cover.example/new.jpg'},
 {source: 'soundcloud', source_id: '123456', title: 'Another discovery', cover_url: 'https://cover.example/second.jpg'},
];
context.createFeedCard({type: 'custom_playlist', title: 'Открытия для вас', tracks});
button.onclick({stopPropagation() {}});
assert.equal(queued[0], tracks[0]);
assert.equal(queued[1], tracks);
assert.equal(queued[2], 0);
assert.deepEqual(collage.map(t => t.sourceId), ['3135556', '123456']);
""".replace('SOURCE', source('home.js')))


def test_feed_starts_while_artwork_pending_and_sync_completion_clears_timers():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const timers = new Map(); let timerId = 0;
const elements = new Map();
function element() {
    return {style: {}, innerHTML: '', appendChild() {}, addEventListener() {},
        querySelector() { return {addEventListener() {}}; }};
}
for (const id of ['home-popular', 'home-recommended', 'home-recommended-section',
    'home-artists', 'home-releases', 'home-mixes']) elements.set(id, element());
const calls = [], requestIds = new Map(); let subject;
const api = {
    get_home_data: async () => ({}), get_playlists: async () => [],
    fetch_missing_covers: () => { calls.push('covers'); return new Promise(() => {}); },
    get_popular_tracks: (region, requestId) => { requestIds.set('home-popular', requestId); calls.push('popular'); subject.renderPopular([]); },
    get_feed: (limit, requestId) => { requestIds.set('home-recommended', requestId); calls.push('feed'); subject.renderRecommendations([]); },
    get_home_releases: (limit, requestId) => { requestIds.set('home-releases', requestId); calls.push('releases'); subject.renderReleases([]); },
    get_home_mixes: (limit, requestId) => { requestIds.set('home-mixes', requestId); calls.push('mixes'); subject.renderMixes([]); },
    get_home_artists: (limit, requestId) => { requestIds.set('home-artists', requestId); calls.push('artists'); subject.renderArtists([]); },
    get_authentic_home_feed: () => { calls.push('duplicate-feed'); },
};
const context = vm.createContext({console, Promise, Date, URL,
    window: {awaitBridge: async () => {}, pywebview: {api}, addEventListener() {}},
    document: {getElementById: id => elements.get(id) || null,
        createElement: element, createDocumentFragment: element, addEventListener() {}},
    setTimeout: (fn, ms) => {
        const id = ++timerId;
        if (ms < 1000) Promise.resolve().then(fn); else timers.set(id, {fn, ms});
        return id;
    }, clearTimeout: id => timers.delete(id),
        updateHomeCoverCollage() {}, renderIcons() {}, registerCanvasDprListener() {}, updateHomeCollections() {}, refreshFavoritesCovers() {}, initHomeAtmosphere() {},
});
const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
vm.runInContext(code + '\nglobalThis.subject = {loadHome, renderPopular, renderRecommendations, renderReleases, renderMixes, renderArtists, isCurrentHomeEvent};', context);
subject = context.subject;
await subject.loadHome();
assert.deepEqual(calls, ['covers','mixes']);
assert.equal(requestIds.size,1,'only the personalized mixes shelf should request data');
assert.equal(timers.size, 0, 'completed feeds must not become false retry buttons');
await subject.loadHome(true);
assert.equal(calls.filter(x => x === 'covers').length, 1, 'track changes must reuse the pending scan');
assert.equal(calls.filter(x => x === 'feed').length, 0, 'track refresh must not re-request feeds');
""".replace("SOURCE", source("home.js")))


def test_empty_feed_event_clears_recommendations():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const calls = [];
const context = vm.createContext({console,
    window: {addEventListener() {}}, document: {getElementById() { return null; }},
    clearFeedTimeout: id => calls.push(['clear', id]),
    isCurrentHomeEvent: () => true,
    renderRecommendations: tracks => calls.push(['render', tracks]),
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '') + '\ninitEvents();', context);
context.window.onPythonEvent('feed_ready', []);
context.flushPythonEvents();
assert.equal(calls[1][0], 'render');
assert.equal(calls[1][1].length, 0, 'empty completion must reach the renderer');
""".replace("SOURCE", source("events.js")))


def test_tagged_home_feed_events_unwrap_rows_and_ignore_stale_request_ids():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const rendered = new Map(), cleared = [], retries = [];
const context = vm.createContext({console,
    window: {addEventListener() {}}, document: {getElementById() { return null; }},
    CustomEvent: class {constructor(type, options) {this.type=type;this.detail=options.detail}},
    isCurrentHomeEvent: (section, data) => data?.request_id === 'current:'+section,
    clearFeedTimeout: section => cleared.push(section),
    renderPopular: rows => rendered.set('home-popular', rows),
    renderRecommendations: rows => rendered.set('home-recommended', rows),
    renderArtists: rows => rendered.set('home-artists', rows),
    renderReleases: rows => rendered.set('home-releases', rows),
    renderMixes: rows => rendered.set('home-mixes', rows),
    renderHomeRetry: section => retries.push(section),
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '') + '\ninitEvents();flushPythonEvents();', context);
const cases=[
 ['popular_results','home-popular','tracks'],['feed_ready','home-recommended','tracks'],
 ['artists_ready','home-artists','artists'],['releases_ready','home-releases','tracks'],
 ['mixes_ready','home-mixes','tracks'],
];
for (const [event,section,key] of cases) {
    context.window.onPythonEvent(event,{request_id:'stale:'+section,[key]:[{id:'old'}]});
    assert.equal(rendered.has(section),false,section+' must ignore stale responses');
    context.window.onPythonEvent(event,{request_id:'current:'+section,[key]:[{id:'fresh'}]});
    assert.equal(rendered.get(section)[0].id,'fresh',section+' must unwrap tagged payload rows');
    assert.equal(cleared.at(-1),section,section+' must clear only its own timeout');
}
for (const [event,section] of cases) {
    context.window.onPythonEvent(event,{request_id:'current:'+section,error:'service unavailable'});
    assert.equal(retries.at(-1),section,section+' must offer retry on provider failure');
    assert.equal(rendered.get(section)[0].id,'fresh',section+' must preserve last successful rows on failure');
}
""".replace("SOURCE", source("events.js")))


def test_radio_ignores_old_wave_response_and_cleans_up_deadline():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners = new Set(); const timers = new Map(); let timerId = 0;
const requests = []; const queued = [];
const window = {awaitBridge: async () => {}, dispatchEvent() {},
    addEventListener: (name, handler) => listeners.add(handler),
    removeEventListener: (name, handler) => listeners.delete(handler),
    pywebview: {api: {play_track() {},
        get_track_wave: (...args) => { requests.push(args); return Promise.resolve([]); },
        add_tracks_to_queue: async tracks => queued.push(...tracks),
    }},
};
const code = SOURCE.match(/startTrackWave: async \(seedTrack\) => \{([\s\S]*?)\n    \},\r?\n    toggleMiniPlayerMode/)[1];
const context = vm.createContext({console, window,
    CustomEvent: class { constructor(name, options) { this.detail = options.detail; } },
    setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, {fn, ms}); return id; },
    clearTimeout: id => timers.delete(id),
});
vm.runInContext('let trackWaveRequestSequence = 0; globalThis.startWave = async seedTrack => {' + code + '};', context);
await context.startWave({source_id: 'old', title: 'Old'});
await context.startWave({source_id: 'new', title: 'New'});
assert.notEqual(requests[0][3], requests[1][3]);
for (const handler of Array.from(listeners)) await handler({detail: {request_id: requests[0][3], tracks: [{source_id: 'wrong'}]}});
assert.equal(queued.length, 0, 'old response must not populate the current wave');
assert.equal(listeners.size, 1);
for (const handler of Array.from(listeners)) await handler({detail: {request_id: requests[1][3], tracks: [{source_id: 'right'}]}});
assert.equal(queued[0].source_id, 'right');
assert.equal(listeners.size, 0);
assert.equal(timers.size, 0);
await context.startWave({source_id: 'timeout', title: 'Timeout'});
const deadline = Array.from(timers.values()).find(timer => timer.ms === 25000);
deadline.fn();
assert.equal(listeners.size, 0, 'a timed-out wave must release its listener');
assert.equal(timers.size, 0);
assert.equal(window._activeTrackWaveCleanup, null);
for (const handler of Array.from(listeners)) await handler({detail: {request_id: requests[2][3], tracks: [{source_id: 'late'}]}});
assert.equal(queued.length, 1, 'a response arriving after the deadline must not alter the queue');
window.pywebview.api.get_track_wave = () => Promise.reject(new Error('bridge failed'));
await context.startWave({source_id: 'failure', title: 'Failure'});
assert.equal(listeners.size, 0, 'bridge rejection must release the listener');
assert.equal(timers.size, 0);
""".replace("SOURCE", source("main.js")))
