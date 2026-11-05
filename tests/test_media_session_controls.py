"""Media-session commands operate the actual audio owner, with idempotent intent."""
from tests.jsdom import run_node, source


def test_media_session_play_pause_controls_frontend_idempotently():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const handlers = {};
let toggles = 0;
const commands = [];
const audio = {paused: true};
const context = vm.createContext({
 navigator: {mediaSession: {setActionHandler(name, fn) {handlers[name] = fn}}},
 MediaMetadata: class {}, getCoverUrl: () => '',
 streamRetryTimer: null, recoveryRequest: null, activeAudio: audio, playbackState: {status: 'paused'},
 togglePlayPause() {toggles++; audio.paused = !audio.paused},
 api(name) {if (name === 'play_pause') throw Error('Backend cannot toggle audio'); commands.push(name)},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('export function updateMediaSession('), code.indexOf('export function playTrack(')).replaceAll('export ', ''), context);
context.updateMediaSession({title: 'Test'});
handlers.play(); handlers.play();
assert.equal(audio.paused, false);
assert.equal(toggles, 1);
handlers.pause(); handlers.pause();
assert.equal(audio.paused, true);
assert.equal(toggles, 2);
handlers.nexttrack(); handlers.previoustrack();
assert.deepEqual(commands, ['next_track', 'prev_track']);
""".replace('SOURCE', source('player.js')))


def test_recent_search_dropdown_has_no_genres_and_keyboard_buttons():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners = {};
const dropdown = {innerHTML: '', classList: {add(){}, remove(){}}, addEventListener(type, fn) {listeners[type] = fn}};
const inputListeners = {};
const input = {addEventListener(type, fn) {inputListeners[type] = fn}};
const code = SOURCE;
const context = vm.createContext({
 document: {querySelector: () => ({}), getElementById: id => id === 'search-input' ? input : dropdown, addEventListener() {}},
 getSearchHistory: () => ['Radiohead'], escapeHtml: s => s, window: {},
});
vm.runInContext(code.slice(code.indexOf('export function setupSmartSearchSuggestions(')).replace('export ', ''), context);
context.setupSmartSearchSuggestions();
inputListeners.focus();
assert.ok(!dropdown.innerHTML.includes('Быстрые жанры'));
assert.ok(!dropdown.innerHTML.includes('search-chip'));
assert.match(dropdown.innerHTML, /<button[^>]*class="search-history-query"/);
assert.match(dropdown.innerHTML, /data-delete-query="Radiohead"/);
assert.match(dropdown.innerHTML, /Недавние поиски/);
""".replace('SOURCE', source('search.js')))

