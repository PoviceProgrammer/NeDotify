"""S4-001: a free-text query on the artists tab must never auto-open a profile.

The backend part (resolve_artist require_candidates) lives in
test_catalog_verification.py; here the UI contract is verified:
  * every query-as-artist entry point (artists tab, runSearchQuery, the
    suggestion banner) passes require_candidates to the backend;
  * the profile view shows the real search results under the candidate list
    (appendRealSearchResults) instead of leaving a confirmation wall.
"""

import json

from tests.jsdom import run_node, source


def test_search_js_query_as_artist_entry_points_require_candidates():
    raw = json.loads(source('search.js'))
    # The three query-as-artist entry points must mark the request; a fourth
    # occurrence of the literal lives in the explanatory comment.
    import re
    marked_calls = re.findall(r"searchArtistProfile\([^)]*require_candidates: true \}\)", raw)
    assert len(marked_calls) == 3, \
        "artists tab, runSearchQuery and the banner must all pass require_candidates"
    assert "searchArtistProfile(query, null, { require_candidates: true });return;" in raw
    assert "function searchArtistProfile(artistName, context = null, options = null)" in raw
    assert "const artistRef = { ...(context ? { context } : {}), ...((options && typeof options === 'object') ? options : {}) };" in raw


def test_append_real_search_results_renders_deduped_tracks_under_candidates():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

const listeners = new Map();
const appended = [];
function makeEl(tag) {
  return {
    tagName: tag, children: [], className: '', textContent: '', _rendered: false,
    appendChild(el) { this.children.push(el); return el; },
    addEventListener() {}, querySelector() { return null; },
  };
}
const container = {
  children: [],
  querySelector(sel) { return sel === '.artist-real-search' ? this.children[0] : null; },
  appendChild(el) { this.children.push(el); return el; },
  contains() { return true; },
};
const context = vm.createContext({
  window: {
    pywebview: { api: { search: (query, src) => { context.searchCalls.push([query, src]); } } },
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type) => listeners.delete(type),
  },
  document: { createElement: (tag) => makeEl(tag) },
  setTimeout: (fn, ms) => 0,
  clearTimeout: () => {},
  getCurrentTrack: () => null,
  createTrackElement: (track, index, tracks, current) => ({ track, index }),
  renderIcons: () => {},
  profileGenerationId: 7,
});
context.searchCalls = [];
vm.runInContext(SOURCE.slice(SOURCE.indexOf('const REAL_SEARCH_WINDOW_MS'), SOURCE.indexOf('async function renderArtistStatus')), context);
const fn = context.appendRealSearchResults;
assert.equal(typeof fn, 'function', 'appendRealSearchResults must be defined');

// Live results arrive through the window events and render once, deduped.
fn('Some Song', container, 7);
assert.deepEqual(context.searchCalls, [['Some Song', 'all']], 'the real search must run for the same text');
const first = container.children[0];
assert.equal(first.className, 'artist-real-search');
const listener = listeners.get('app:search_results');
assert.ok(listener, 'results listener must be registered');
listener({ detail: { query: 'Some Song', source: 'youtube', tracks: [
  { source: 'youtube', source_id: 'v1', title: 'A' },
  { source: 'youtube', source_id: 'v1', title: 'A duplicate' },
  { source: 'youtube', source_id: 'v2', title: 'B' },
] } });
assert.equal(first.children.length, 3, 'heading + two deduped results');
assert.deepEqual(first.children.slice(1).map(el => el.track.title), ['A', 'B']);

// Stale queries are ignored.
listener({ detail: { query: 'Another Query', source: 'youtube', tracks: [{ source: 'youtube', source_id: 'v3', title: 'C' }] } });
assert.equal(first.children.length, 3);

// A second call on the same container does not duplicate the section.
fn('Some Song', container, 7);
assert.equal(container.children.length, 1);

// Different profile generation is a no-op.
const freshContainer = { children: [], querySelector() { return null; }, appendChild(el) { this.children.push(el); return el; }, contains() { return true; } };
fn('Other', freshContainer, 8);
assert.equal(freshContainer.children.length, 0);
assert.equal(context.searchCalls.length, 1, 'stale generation must not search');
""".replace('SOURCE', source('artist_profile.js')))


def test_bio_cache_is_scoped_by_identity_with_ttl_and_backend_priority():
    """S4-005/S4-013: bio cache key, TTL and priority over stale values."""
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

const store = new Map();
const document = {
  createElement: (tag) => ({
    tagName: tag, children: [], className: '', style: {}, dataset: {},
    appendChild(el) { this.children.push(el); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() {}, classList: {toggle(){}, add(){}, remove(){}},
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
  }),
};
const context = vm.createContext({
  window: {}, document,
  localStorage: {
    getItem: (k) => store.has(k) ? store.get(k) : null,
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  Date, JSON, Math, Object, Array,
  escapeHtml: (s) => String(s),
});
const bioStart = SOURCE.indexOf('const BIO_CACHE_TTL_MS');
const bioEnd = SOURCE.indexOf('static renderSkeleton', SOURCE.indexOf('export class ArtistBioComponent'));
const bioSource = SOURCE.slice(bioStart, bioEnd).replace('export class ', 'class ');
vm.runInContext(bioSource + '\n}\n; globalThis.ArtistBioComponent = ArtistBioComponent;', context);
assert.equal(typeof context.ArtistBioComponent, 'function', 'component must be defined');

const { ArtistBioComponent } = context;
const data = (over) => Object.assign({
  name: 'Same Name', source: 'youtube', source_id: 'UC-1',
  bio: 'English text', bio_ru: 'Русский текст', bio_original: 'English text',
}, over);

// 1. Fresh backend translation wins and is cached under source:sid, not name.
const card = new ArtistBioComponent(data()).render();
assert.ok(store.has('artist_bio_youtube_UC-1_ru'), 'cache key must carry source and id');
assert.ok(!store.has('artist_bio_same name_ru'), 'the name-only key must be gone');
assert.equal(JSON.parse(store.get('artist_bio_youtube_UC-1_ru')).v, 'Русский текст');

// 2. A stale cached English "translation" never overrides the fresh answer.
store.set('artist_bio_youtube_UC-1_ru', JSON.stringify({ v: 'Старый английский кэш', o: 'English text', t: Date.now() }));
const card2 = new ArtistBioComponent(data()).render();
const entry = JSON.parse(store.get('artist_bio_youtube_UC-1_ru'));
assert.equal(entry.v, 'Русский текст', 'fresh backend value must overwrite the cache');

// 3. When the backend has no translation, the cached one for the SAME text applies.
store.set('artist_bio_youtube_UC-1_ru', JSON.stringify({ v: 'Ранее переведённый текст', o: 'English text', t: Date.now() }));
const card3 = new ArtistBioComponent(data({ bio_ru: null })).render();
assert.equal(JSON.parse(store.get('artist_bio_youtube_UC-1_ru')).v, 'Ранее переведённый текст');

// 4. A different bio_original invalidates the cached translation.
const card4 = new ArtistBioComponent(data({ bio_ru: null, bio: 'New English text', bio_original: 'New English text' })).render();
assert.ok(!store.has('artist_bio_youtube_UC-1_ru'), 'stale text must not be reused');

// 5. TTL: an old entry is dropped.
store.set('artist_bio_youtube_UC-1_ru', JSON.stringify({ v: 'Ранее переведённый текст', o: 'English text', t: Date.now() - 8 * 24 * 60 * 60 * 1000 }));
new ArtistBioComponent(data({ bio_ru: null })).render();
assert.ok(!store.has('artist_bio_youtube_UC-1_ru'), 'expired entries must be removed');

// 6. Homonyms do not share the biography.
new ArtistBioComponent(data({ bio_ru: 'Текст первого' })).render();
new ArtistBioComponent(data({ source_id: 'UC-2', bio_ru: 'Другой текст' })).render();
assert.ok(store.has('artist_bio_youtube_UC-2_ru'));
assert.equal(JSON.parse(store.get('artist_bio_youtube_UC-1_ru')).v, 'Текст первого');
assert.equal(JSON.parse(store.get('artist_bio_youtube_UC-2_ru')).v, 'Другой текст');
""".replace('SOURCE', source('artist_profile.js')))
