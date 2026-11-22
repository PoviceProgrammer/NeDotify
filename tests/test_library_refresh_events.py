"""Library mutation events patch the open collection instead of rebuilding it.

Rebuilding the section (`refreshActiveLibraryView`) re-runs `selectSection`,
which empties `#lib-active-tracks`, shows a spinner and scrolls to the top. That
was visible after every finished download and after every track added from a
context menu, so the router must prefer the in-place patch.
"""
import json

from tests.jsdom import run_node, source

ROUTER_PRELUDE = r"""
const calls = [], timers = new Map();
let seq = 0, libraryRefreshTimer = null, isNextTrackChange = false;
let openPlaylistResult = false, collectionResult = false;
const window = {dispatchEvent: event => calls.push(['dispatch', event.type, event.detail])};
class CustomEvent {constructor(type, options = {}) {this.type = type; this.detail = options.detail}}
const isPageVisible = page => page === 'library';
const loadHome = () => calls.push(['loadHome']);
const loadLibrary = () => calls.push(['library']);
const loadPlaylists = () => calls.push(['playlists']);
const refreshActiveLibraryView = () => calls.push(['full']);
const refreshOpenPlaylist = id => {calls.push(['playlist', id]); return openPlaylistResult};
const refreshActiveCollection = () => {calls.push(['collection']); return collectionResult};
const setTimeout = (fn, ms) => {const id = ++seq; timers.set(id, {fn, ms}); return id};
const clearTimeout = id => timers.delete(id);
window.refreshOpenPlaylist = refreshOpenPlaylist;
window.refreshActiveCollection = refreshActiveCollection;
window.refreshActiveLibraryView = refreshActiveLibraryView;
function route(data) {switch ('library_updated') {
BODY
}}
globalThis.subject = {
    calls, timers, route,
    openPlaylist(v) {openPlaylistResult = v},
    collection(v) {collectionResult = v},
    run() {[...timers.values()][0].fn()},
    timerDelays() {return [...timers.values()].map(entry => entry.ms)},
    // Bridge broadcasts are noise for these assertions.
    refreshed() {return calls.filter(entry => entry[0] !== 'dispatch')},
};
"""


def router_program():
    code = json.loads(source("events.js"))
    start = code.index("case 'library_updated':")
    case_body = code[start:code.index("case 'mini_player_placement':", start)]
    prelude = ROUTER_PRELUDE.replace("BODY", case_body)
    return ("import assert from 'node:assert/strict';\n"
            "import vm from 'node:vm';\n"
            "const context = vm.createContext({console});\n"
            f"vm.runInContext({json.dumps(prelude)}, context);\n"
            "const subject = context.subject;\n")


def run_router(body):
    run_node(router_program() + body)


def test_playlist_mutation_patches_that_playlist_and_skips_full_rebuild():
    run_router(r"""
subject.openPlaylist(true);
subject.route({playlist_id: 42});
assert.equal(JSON.stringify(subject.timerDelays()), JSON.stringify([300]), 'bursts are still debounced');
subject.run();
assert.equal(JSON.stringify(subject.refreshed()), JSON.stringify([['library'], ['playlist', 42]]),
    'an open playlist must be patched in place, not rebuilt from the top');
""")


def test_library_download_without_a_playlist_patches_the_offline_view():
    run_router(r"""
subject.collection(true);
subject.route(true);
subject.run();
assert.equal(JSON.stringify(subject.refreshed()), JSON.stringify([['library'], ['playlist', null], ['collection']]),
    'a finished download patches the visible collection instead of rebuilding it');
""")


def test_other_sections_still_fall_back_to_the_full_refresh():
    run_router(r"""
subject.route({playlist_id: 7});
subject.run();
assert.equal(JSON.stringify(subject.refreshed()), JSON.stringify([['library'], ['playlist', 7], ['full']]),
    'overview, favorites and all still refresh normally');
""")


def test_mini_player_restoring_event_reaches_the_layout():
    code = json.loads(source("events.js"))
    start = code.index("case 'mini_player_restoring':")
    case_body = code[start:code.index("case 'scan_progress':", start)]
    program = ("import assert from 'node:assert/strict';\nimport vm from 'node:vm';\n"
               "const events = [];\n"
               "const context = vm.createContext({console,\n"
               "    window: {dispatchEvent: event => events.push([event.type, event.detail])},\n"
               "    CustomEvent: class {constructor(type, options = {}) {this.type = type; this.detail = options.detail}},\n"
               "});\n"
               "vm.runInContext(" + json.dumps("function route(data) {switch ('mini_player_restoring') {\n"
                                               + case_body + "}}") + ", context);\n"
               "context.route({success: true, is_mini: false});\n"
               "assert.deepEqual(events, [['nedotify:mini_player_restoring', {success: true, is_mini: false}]]);\n")
    run_node(program)
