"""Exercise the shipped bridge consumers with out-of-order responses."""
from tests.jsdom import run_node, source


def test_lyrics_upgrade_preserves_offset_translation_and_rejects_old_revisions():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let resets = 0;
function element() { return {children: [], dataset: {}, appendChild(e) {this.children.push(e)}, addEventListener() {}, querySelector() {return null}, innerHTML: '', style: {}}; }
const container = element();
const context = vm.createContext({console,
 activeLyricsRequestId: 'current', lastLyricsRevision: 1,
 lastLyricsData: {plainLyrics: 'Hello', syncedLyrics: null, status: 'found', match_type: 'exact'},
 currentTranslationMap: {Hello: 'Привет'}, currentOffsetMs: 1500, currentRawLyricsText: 'Hello',
 lastLoadedTrackKey: 'track', requestedLyricsDurationMs: 180000,
 lyricsMemoryCache: new Map(), LYRICS_MEMORY_CACHE_LIMIT: 40,
 parsedLyrics: [], currentLineIndex: -1, isTranslationEnabled: true, lastPosMs: 2000,
 getContainers: () => [container], resetLyricsScroll: () => resets++, updateOffsetBadges() {},
 setOffsetControlsEnabled() {}, updateLyricsPosition() {}, renderIcons() {},
 document: {createElement: element}, parseLrc: () => [{text: 'Hello', timeMs: 1000}],
 refreshKineticState: () => ({}), ensureMeasured: () => false,
 cleanPlainLyrics: text => String(text || '').replace(/\[[^\]]*\]/g, '').trim().split('\n'),
 toggleTranslation() {throw Error('Identical text must reuse translation')},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function rememberLyrics('), code.indexOf('export function toggleTranslation(')), context);
vm.runInContext(code.slice(code.indexOf('export function renderLyrics('), code.indexOf('export function parseLrc(')).replace('export ', ''), context);
context.renderLyrics({request_id: 'old', revision: 10, plainLyrics: 'Wrong'});
assert.equal(resets, 0);
const update = {request_id: 'current', revision: 2, status: 'found', match_type: 'exact', plainLyrics: 'Hello', syncedLyrics: '[00:01.00] Hello'};
context.renderLyrics(update);
assert.equal(context.currentOffsetMs, 1500);
assert.equal(context.currentTranslationMap.Hello, 'Привет');
assert.equal(context.parsedLyrics.length, 1);
assert.equal(resets, 1);
context.renderLyrics({...update, revision: 1, plainLyrics: 'Wrong'});
context.renderLyrics({...update, revision: 3, phase: 'final'});
assert.equal(resets, 1);
assert.equal(context.lastLyricsRevision, 3);
""".replace('SOURCE', source('lyrics.js')))


def test_translation_envelope_builds_line_map_for_every_display_surface():
    """BUG-L2-001: the bridge answers {'success': True, 'text': ...}, not a map.

    The envelope used to be assigned as currentTranslationMap as-is, so lookups
    by line text missed on every surface (overlay sheet, player page panel and
    the PiP widget all key translations by the original line text). The
    envelope's text must be split line-by-line exactly like the string-shaped
    response, and stale responses must stay ignored.
    """
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
class CustomEvent { constructor(type, opts) { this.type = type; this.detail = opts?.detail; } }
const events = [];
function element() { return {classList: {toggle() {}, add() {}, remove() {}}, style: {}, disabled: false, addEventListener() {}}; }
let resolveApi, apiArgs;
const renderCalls = [];
const context = vm.createContext({
 console, CustomEvent, setTimeout, clearTimeout,
 parsedLyrics: [], currentTranslationMap: {}, isTranslationEnabled: false,
 currentRawLyricsText: 'Hello\nWorld', lastLyricsData: {plainLyrics: 'Hello\nWorld', syncedLyrics: null},
 lastLoadedTrackKey: 'track-1',
 cleanPlainLyrics: text => String(text || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean),
 renderLyrics(data, force) { renderCalls.push([data, force]); },
 renderCalls,
 document: {getElementById: () => element()},
 window: {dispatchEvent: e => events.push(e), pywebview: {api: {
   get_lyrics_translation: (text, lang) => { apiArgs = [text, lang]; return new Promise(r => { resolveApi = r; }); },
 }}},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function buildTranslationMap('), code.indexOf('export function updateOffsetBadges(')).replace('export ', ''), context);

// Envelope response: text must land as a per-line map keyed by original lines.
context.isTranslationEnabled = false;
context.toggleTranslation(true);
assert.equal(context.isTranslationEnabled, true);
assert.deepEqual(apiArgs, ['Hello\nWorld', 'ru']);
assert.equal(events.at(-1).detail.msg, 'Переводим текст песни...');
resolveApi({success: true, text: 'Привет\nМир', error: null});
await new Promise(r => setTimeout(r, 20));
assert.equal(JSON.stringify(context.currentTranslationMap), JSON.stringify({Hello: 'Привет', World: 'Мир'}));
assert.deepEqual(renderCalls.at(-1), [context.lastLyricsData, true]);

// String-shaped responses keep working through the same builder.
context.currentTranslationMap = {};
context.toggleTranslation(false);
context.toggleTranslation(true);
resolveApi('Привет\nМир');
await new Promise(r => setTimeout(r, 20));
assert.equal(JSON.stringify(context.currentTranslationMap), JSON.stringify({Hello: 'Привет', World: 'Мир'}));

// Untranslated passthrough is an error, not a silent empty map.
context.currentTranslationMap = {};
context.toggleTranslation(false);
context.toggleTranslation(true);
resolveApi({success: true, text: 'Hello\nWorld', error: null});
await new Promise(r => setTimeout(r, 20));
assert.equal(Object.keys(context.currentTranslationMap).length, 0);
assert.equal(context.isTranslationEnabled, false);
assert.equal(events.at(-1).detail.type, 'error');

// A response for a superseded track must be dropped without rendering.
context.toggleTranslation(true);
const staleResolve = resolveApi;
const rendersBeforeStale = renderCalls.length;
context.lastLoadedTrackKey = 'track-2';
staleResolve({success: true, text: 'Привет\nМир', error: null});
await new Promise(r => setTimeout(r, 20));
assert.equal(Object.keys(context.currentTranslationMap).length, 0);
assert.equal(renderCalls.length, rendersBeforeStale, 'stale response must not render');
""".replace('SOURCE', source('lyrics.js')))


def test_translation_map_keys_cover_synced_and_pip_lookups():
    """Synced sheets, the plain sheet and the PiP event all look translations
    up by the parsed line text; the built map must use exactly those keys."""
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
class CustomEvent { constructor(type, opts) { this.type = type; this.detail = opts?.detail; } }
const events = [];
function element() { return {classList: {toggle() {}, add() {}, remove() {}}, style: {}, disabled: false, addEventListener() {}}; }
let resolveApi;
const context = vm.createContext({
 console, CustomEvent, setTimeout, clearTimeout,
 parsedLyrics: [{text: 'Hello', timeMs: 1000}, {text: 'World', timeMs: 2000}],
 currentTranslationMap: {}, isTranslationEnabled: false,
 currentRawLyricsText: '[00:01.00] Hello\n[00:02.00] World',
 lastLyricsData: {syncedLyrics: '[00:01.00] Hello\n[00:02.00] World', plainLyrics: null},
 lastLoadedTrackKey: 'track-1',
 cleanPlainLyrics: text => String(text || '').replace(/\[[^\]]*\]/g, '').split(/\r?\n/).map(l => l.trim()).filter(Boolean),
 renderLyrics() {}, document: {getElementById: () => element()},
 window: {dispatchEvent: e => events.push(e), pywebview: {api: {
   get_lyrics_translation: () => new Promise(r => { resolveApi = r; }),
 }}},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function buildTranslationMap('), code.indexOf('export function updateOffsetBadges(')).replace('export ', ''), context);
context.toggleTranslation(true);
// Timestamps are stripped before the request: the backend must never see [00:01.00] tags.
resolveApi({success: true, text: 'Привет\nМир', error: null});
await new Promise(r => setTimeout(r, 20));
// Every consumer keys by parsedLyrics line text (synced sheet, player page
// panel, and the PiP widget's currentTranslationMap[parsedLyrics[index].text]).
for (const line of context.parsedLyrics) {
    assert.ok(context.currentTranslationMap[line.text], `no translation for ${line.text}`);
}
assert.equal(context.currentTranslationMap['[00:01.00] Hello'], undefined);
""".replace('SOURCE', source('lyrics.js')))


def test_album_fetch_cancels_previous_view_and_ignores_old_response():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners = new Set(), calls = [];
const context = vm.createContext({Date, Math, Promise, setTimeout, clearTimeout, activeBridgeCleanups: [],
 document: {addEventListener: (_, cb) => listeners.add(cb), removeEventListener: (_, cb) => listeners.delete(cb)},
 window: {pywebview: {api: {get_album_details: async (album, rid) => {calls.push(rid); return {status: 'loading'};}}}},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('let albumFetchCleanup'), code.indexOf('export async function playAlbum')).replaceAll('export ', ''), context);
const first = context.fetchAlbumDetails({title: 'First'});
const second = context.fetchAlbumDetails({title: 'Second'});
assert.equal((await first).cancelled, true);
for (const cb of listeners) cb({detail: {request_id: calls[0], status: 'found', tracks: [{title: 'Wrong'}]}});
for (const cb of [...listeners]) cb({detail: {request_id: calls[1], status: 'found', tracks: [{title: 'Right'}]}});
assert.equal((await second).tracks[0].title, 'Right');
assert.equal(listeners.size, 0);
""".replace('SOURCE', source('search.js')))


def test_artist_reference_and_request_id_are_forwarded_without_substring_matching():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners = new Map(); let call;
const context = vm.createContext({Date, Math, Promise, setTimeout, clearTimeout, activeBridgeCleanups: [],
 document: {addEventListener(name, cb) {listeners.set(name, cb)}, removeEventListener(name) {listeners.delete(name)}},
 window: {pywebview: {api: {get_artist_profile: async (...args) => {call = args; return {status: 'loading'};}}}},
});
const code = SOURCE;
const fnEnd = code.indexOf('function renderArtistCandidates(') !== -1 ? code.indexOf('function renderArtistCandidates(') : code.indexOf('let artistCandidateView');
vm.runInContext(code.slice(code.indexOf('export async function fetchArtistProfileFromBridge('), fnEnd).replace('export ', ''), context);
const promise = context.fetchArtistProfileFromBridge('Фараон', 1000, {source: 'youtube', source_id: 'UC-real'});
assert.equal(call[1].source_id, 'UC-real');
listeners.get('nedotify:artist_profile_ready')({detail: {request_id: 'wrong-id', name: 'Фараон Extra'}});
assert.equal(listeners.size, 2);
listeners.get('nedotify:artist_profile_ready')({detail: {request_id: call[2], status: 'found', name: 'PHARAOH'}});
assert.equal((await promise).name, 'PHARAOH');
assert.equal(listeners.size, 0);
""".replace('SOURCE', source('artist_profile.js')))
