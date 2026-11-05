"""Exercise async playlist suggestions, navigation races and collection writes."""
from tests.jsdom import run_node, source


def run_recommendations(assertions):
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
class Element {
    constructor(tag = 'div') { this.tagName = tag; this.children = []; this.selectors = new Map(); this.dataset = {}; this.attrs = {}; this.hidden = false; this.isConnected = false; this.disabled = false; }
    set innerHTML(html) { this.html = html; this.children = []; this.selectors.clear(); }
    get innerHTML() { return this.html || ''; }
    appendChild(node) { this.children.push(node); node.parentElement = this; node.isConnected = true; return node; }
    setAttribute(key, value) { this.attrs[key] = value; }
    querySelector(selector) {
        if (!this.selectors.has(selector)) this.selectors.set(selector, new Element('button'));
        return this.selectors.get(selector);
    }
}
const parent = new Element();
const tracks = parent.appendChild(new Element());
const requests = [], writes = [], toasts = [], plays = [];
const listeners = new Map(), timers = new Map();
let pythonHandler, timerId = 0, favorites = [], rejectWrite = false, rejectRequest = false;
const context = vm.createContext({ console,
    document: {getElementById: id => id === 'lib-active-tracks' ? tracks : null, createElement: tag => new Element(tag)},
    window: {awaitBridge: async () => {}, addEventListener: (name, callback) => listeners.set(name, callback), pywebview: {api: {
        get_playlist_recommendations: async (...args) => { requests.push(args); if (rejectRequest) throw new Error('offline'); return []; },
        get_favorites: async () => favorites,
        toggle_favorite: async track => { writes.push(['favorite',track]); return {success: true, is_favorite: true}; },
        add_to_playlist: async (id, track) => { writes.push([id, track]); return !rejectWrite; },
        play_track: async (...args) => { plays.push(args); return {success: true}; },
    }}},
    addPythonEventHandler: handler => { pythonHandler = handler; },
    escapeHtml: text => String(text ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    getCoverUrl: () => '', coverImgHtml: () => '', renderIcons() {}, showTrackContextMenu() {},
    showToast: (...args) => toasts.push(args),
    setTimeout: callback => { const id = ++timerId; timers.set(id,callback); return id; }, clearTimeout: id => timers.delete(id),
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,''), context);
const seed = {id: 1, source: 'youtube', source_id: 'seed', title: 'Seed', artist: 'Artist'};
const suggestion = {source: 'youtube', source_id: 'new', title: 'New song', artist: 'New artist', recommendation_reason: 'Похоже на <любимое>'};
const tick = async () => { for (let i=0;i<8;i++) await Promise.resolve(); };
const section = () => parent.children.find(node => node.id === 'lib-playlist-recommendations');
const rows = () => section().querySelector('.playlist-recommendations-body').children;
const ready = (tracks, args = requests.at(-1)) => pythonHandler('playlist_recommendations_ready', {playlist_id: args[0], request_id: args[2], tracks});
ASSERTIONS
""".replace('SOURCE', source('playlist-recommendations.js')).replace('ASSERTIONS', assertions))


def test_playlist_suggestions_discard_stale_responses_and_duplicate_content():
    run_recommendations(r"""
context.showPlaylistRecommendations('playlist', {id: 2}, [seed]); await tick();
const old = requests.at(-1);
context.showPlaylistRecommendations('playlist', {id: 3}, [seed]); await tick();
ready([suggestion], old);
assert.equal(section().dataset.state, 'loading');
ready([{...seed, source_id: 'another-upload'}, suggestion, {...suggestion, source_id: 'duplicate'}]);
assert.equal(section().dataset.state, 'ready'); assert.equal(rows().length, 1);
assert.ok(rows()[0].innerHTML.includes('Похоже на &lt;любимое>'));
await rows()[0].querySelector('.playlist-recommendation-play').onclick();
assert.equal(plays[0][0].title, suggestion.title);
assert.equal(timers.size, 0);
context.hidePlaylistRecommendations(); ready([suggestion]); assert.equal(section().hidden, true);
""")


def test_addition_removes_suggestion_and_rejects_late_duplicate_response():
    run_recommendations(r"""
context.showPlaylistRecommendations('playlist', {id: 2}, [seed]); await tick(); ready([suggestion]);
const add = rows()[0].querySelector('.playlist-recommendation-add');
await add.onclick({currentTarget: add});
assert.equal(writes.length, 1); assert.equal(writes[0][0], 2);
assert.equal(section().dataset.state, 'empty');
ready([suggestion]); assert.equal(section().dataset.state, 'empty');
section().querySelector('.playlist-recommendations-refresh').onclick(); await tick();
ready([suggestion]); assert.equal(section().dataset.state, 'empty');
""")


def test_favorites_add_rechecks_existing_likes_before_toggle():
    run_recommendations(r"""
context.showPlaylistRecommendations('favorites', null, [seed]); await tick();
assert.equal(requests.at(-1)[0], 'favorites'); ready([suggestion]);
favorites = [{...suggestion, source_id: 'other-upload'}];
const button = rows()[0].querySelector('.playlist-recommendation-add');
await button.onclick({currentTarget: button});
assert.equal(writes.length, 0); assert.equal(section().dataset.state, 'empty');
context.showPlaylistRecommendations('favorites', null, [seed]); await tick(); ready([suggestion]);
favorites = [];
const add = rows()[0].querySelector('.playlist-recommendation-add'); await add.onclick({currentTarget: add});
assert.equal(writes.length, 1); assert.equal(writes[0][0], 'favorite');
""")


def test_failed_write_keeps_suggestion_and_feedback_replaces_inflight_request():
    run_recommendations(r"""
context.showPlaylistRecommendations('playlist', {id: 2}, [seed]); await tick(); ready([suggestion]);
rejectWrite = true; const button = rows()[0].querySelector('.playlist-recommendation-add');
await button.onclick({currentTarget: button});
assert.equal(button.disabled, false); assert.equal(rows().length, 1); assert.equal(toasts.at(-1)[1], 'error');
listeners.get('nedotify:recommendation_feedback_changed')(); await tick(); const old = requests.at(-1);
listeners.get('nedotify:recommendation_mode_changed')(); await tick();
assert.notEqual(old[2], requests.at(-1)[2]); ready([suggestion], old);
assert.equal(section().dataset.state, 'loading'); ready([]); assert.equal(section().dataset.state, 'empty');
""")


def test_empty_unsupported_and_unavailable_collections_have_recoverable_states():
    run_recommendations(r"""
context.showPlaylistRecommendations('all', null, [seed]); await tick(); assert.equal(requests.length, 0);
context.showPlaylistRecommendations('playlist', {id: 9, is_system: true}, [seed]); assert.equal(requests.length, 0);
context.showPlaylistRecommendations('favorites', null, []); assert.equal(section().dataset.state, 'empty'); assert.equal(requests.length, 0);
rejectRequest = true; context.showPlaylistRecommendations('favorites', null, [seed]); await tick();
assert.equal(section().dataset.state, 'error'); assert.equal(timers.size, 0);
rejectRequest = false; section().querySelector('.playlist-recommendations-refresh').onclick(); await tick();
const old = requests.at(-1); [...timers.values()][0](); assert.equal(section().dataset.state, 'error');
ready([suggestion], old); assert.equal(section().dataset.state, 'error');
section().querySelector('.playlist-recommendations-refresh').onclick(); await tick(); ready([suggestion]);
assert.equal(section().dataset.state, 'ready');
""")
