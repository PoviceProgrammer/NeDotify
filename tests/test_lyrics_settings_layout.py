"""Lyrics display settings must not touch every rendered line on each input.

Dragging the font-size / line-height / weight sliders fires `input` at pointer
rate. `applyLyricsDisplaySettings` used to walk every `.lyric-line`,
`.lyric-orig-text`, `.lyric-word` and `.lyric-plain` node and write three inline
style properties on each — hundreds of style writes per frame, and none of them
could take effect because `lyrics.css` declares `font-size: var(--lyrics-font-size)
!important` on exactly those selectors. It then re-measured both kinetic sheets
synchronously: `measureViewport` writes px padding and immediately reads
`offsetHeight`/`offsetTop`, i.e. a forced layout flush per `input` event.

Typography now travels only through the `--lyrics-*` custom properties (a single
write on `:root`, inherited), and the re-measure is coalesced to one animation
frame.
"""

import json

from tests.jsdom import run_node, source


def test_lyrics_settings_write_only_custom_properties_and_one_remeasure_per_frame():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

const frames = new Map();
let frameId = 0;
let remeasures = 0;
const lineEl = {
    style: {fontSize: '', fontWeight: '', lineHeight: ''},
};

function makeStyle() {
    const store = {};
    return {
        store,
        setProperty(name, value) { store[name] = value; },
    };
}
const rootEl = {style: makeStyle()};
const bodyEl = {style: makeStyle()};
const viewport = {dataset: {}, style: makeStyle()};

const heading = {children: [], appendChild() {}, addEventListener() {}, classList: {toggle() {}}};
const context = vm.createContext({
    console, Math, Number, String, JSON, Object, Array,
    setTimeout: () => 0, clearTimeout() {},
    requestAnimationFrame: fn => { frames.set(++frameId, fn); return frameId; },
    cancelAnimationFrame: id => frames.delete(id),
    localStorage: {setItem() {}, getItem: () => null, removeItem() {}},
    document: {
        documentElement: rootEl,
        body: bodyEl,
        getElementById: () => null,
        querySelectorAll: selector => (selector.includes('.lyric-line') ? [lineEl] : [viewport]),
        addEventListener() {},
    },
    window: {innerWidth: 1200, innerHeight: 800, addEventListener() {},
        NeDotify: {invalidateLyricsKineticLayout() { remeasures++; }}},
});

// A frame is removed from the queue when it runs, like a real event loop.
function runFrame() {
    const [id, fn] = frames.entries().next().value;
    frames.delete(id);
    fn();
}

const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
vm.runInContext(code + '\nglobalThis.apply = applyLyricsDisplaySettings;', context);

const settings = {font_size: 30, font_weight: 600, line_height: 1.8, text_align: 'left'};
context.apply(settings, false);

// Typography reaches the sheet through custom properties only.
assert.equal(rootEl.style.store['--lyrics-font-size'], '30px');
assert.equal(rootEl.style.store['--lyrics-font-weight'], '600');
assert.equal(rootEl.style.store['--lyrics-line-height'], '1.8');
assert.equal(viewport.dataset.align, 'left', 'alignment stays a data attribute');
assert.equal(viewport.style.store['--lyrics-font-size'], '30px');

// The per-line inline write loop is gone: no direct property assignment.
assert.equal(lineEl.style.fontSize, '', 'no inline font-size on a rendered line');
assert.equal(lineEl.style.fontWeight, '');
assert.equal(lineEl.style.lineHeight, '');

// One pending frame, not one re-measure per call.
assert.equal(remeasures, 0, 'the re-measure is deferred to the next frame');
assert.equal(frames.size, 1);
context.apply({...settings, font_size: 32}, false);
context.apply({...settings, font_size: 34}, false);
assert.equal(frames.size, 1, 'a slider drag coalesces into a single frame');
assert.equal(rootEl.style.store['--lyrics-font-size'], '34px', 'the latest value still wins');

runFrame();
assert.equal(remeasures, 1, 'exactly one re-measure for the whole burst');

// A later change schedules a new frame.
context.apply({...settings, font_size: 20}, false);
assert.equal(frames.size, 1);
frames.values().next().value();
assert.equal(remeasures, 2);
""".replace('SOURCE', source('lyrics-settings-popover.js')))


def test_lyrics_settings_accept_camel_case_and_save_a_dict():
    """The bridge speaks camelCase and takes a single dict.

    `get_lyrics_display_settings` returns `{fontSize, fontWeight, lineHeight,
    textAlign}` flat, but the popover only applied `res.success && res.settings`
    and read snake_case keys, so a saved size never came back. The save path
    passed four positional numbers into `save_lyrics_display_settings(settings)`,
    which rejected them with `isinstance(settings, dict) == False`.
    """
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

const store = {};
const rootEl = {style: {setProperty(name, value) { store[name] = value; }}};
const saves = [];
const timers = [];

const context = vm.createContext({
    console, Math, Number, String, JSON, Object, Array,
    setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout() {},
    requestAnimationFrame: () => 0,
    localStorage: {setItem() {}, getItem: () => null, removeItem() {}},
    document: {
        documentElement: rootEl,
        body: {style: {setProperty(name, value) { store[name] = value; }}},
        getElementById: () => null,
        querySelectorAll: () => [],
        addEventListener() {},
    },
    window: {
        innerWidth: 1200, innerHeight: 800, addEventListener() {},
        pywebview: {api: {save_lyrics_display_settings: payload => {
            saves.push(payload);
            return Promise.resolve(true);
        }}},
    },
});

const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
vm.runInContext(code + '\nglobalThis.apply = applyLyricsDisplaySettings;', context);

// The exact shape the Python side returns.
context.apply({fontSize: 31, fontWeight: 600, lineHeight: 1.9, textAlign: 'left'}, false);
assert.equal(store['--lyrics-font-size'], '31px');
assert.equal(store['--lyrics-font-weight'], '600');
assert.equal(store['--lyrics-line-height'], '1.9');
assert.equal(store['--lyrics-text-align'], 'left');

// Snake_case still works (localStorage and older payloads).
context.apply({font_size: 28, font_weight: 500, line_height: 1.7, text_align: 'left'}, false);
assert.equal(store['--lyrics-font-size'], '28px');

// A partial payload keeps the defaults for missing keys instead of reading
// `undefined` into the clamps.
context.apply({}, false);
assert.equal(store['--lyrics-font-size'], '24px');
assert.equal(store['--lyrics-font-weight'], '700');

// A user change is persisted as ONE dict argument, after the debounce.
context.apply({fontSize: 30, fontWeight: 700, lineHeight: 1.45, textAlign: 'center'}, true);
assert.equal(timers.length, 1, 'the save is debounced');
timers[0]();
assert.equal(saves.length, 1);
// The payload is created inside the vm realm, so compare by value, not identity.
assert.equal(JSON.stringify(saves[0]), JSON.stringify({fontSize: 30, fontWeight: 700, lineHeight: 1.45, textAlign: 'center'}));
""".replace('SOURCE', source('lyrics-settings-popover.js')))


def test_lyrics_settings_load_merges_backend_and_respects_user_changes():
    """A late/repeated backend response must not reset the current session.

    The backend now returns only stored keys, so an empty database must leave
    the localStorage copy alone, and a response that arrives after the user has
    already moved a slider must be ignored.
    """
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

const popover = {
    inert: true,
    style: {},
    parentElement: null,
    classList: {contains: () => true, add() {}, remove() {}},
    contains: () => false,
};

function makeHarness() {
    const store = {};
    const pending = [];
    const saves = [];
    const movedToBody = {value: false};
    let localValue = null;
    popover.parentElement = {id: 'app-container'};
    const context = vm.createContext({
        console, Math, Number, String, JSON, Object, Array,
        setTimeout: () => 0, clearTimeout() {},
        requestAnimationFrame: () => 0,
        localStorage: {
            setItem() {}, getItem: () => localValue,
            removeItem() { localValue = null; },
        },
        document: {
            documentElement: {style: {setProperty(name, value) { store[name] = value; }}},
            body: {
                style: {setProperty(name, value) { store[name] = value; }},
                appendChild(node) {
                    if (node === popover) {
                        movedToBody.value = true;
                        popover.parentElement = null;
                    }
                },
            },
            getElementById: id => id === 'lyrics-display-settings-popover' ? popover : null,
            querySelectorAll: () => [],
            addEventListener() {},
        },
        window: {
            innerWidth: 1200, innerHeight: 800, addEventListener() {},
            pywebview: {api: {
                get_lyrics_display_settings: () => {
                    let resolve;
                    const promise = new Promise(r => { resolve = r; });
                    pending.push(value => resolve(value));
                    return promise;
                },
                save_lyrics_display_settings: payload => {
                    saves.push(payload);
                    return Promise.resolve(true);
                },
            }},
        },
    });
    const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
    vm.runInContext(code + '\nglobalThis.init = initLyricsSettingsPopover;\nglobalThis.apply = applyLyricsDisplaySettings;', context);
    return {store, pending, saves, movedToBody, api: context, setLocal: value => { localValue = value; }};
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));

// Stored values come back camelCase and are merged over the defaults.
const merged = makeHarness();
merged.api.init();
assert.equal(merged.movedToBody.value, true, 'the popover leaves #app-container for <body>');
assert.equal(merged.pending.length, 1, 'the backend request is issued once');
merged.pending[0]({fontSize: 33, textAlign: 'left'});
await settle();
assert.equal(merged.store['--lyrics-font-size'], '33px', 'the stored size is applied');
assert.equal(merged.store['--lyrics-text-align'], 'left');

// An empty database returns {}, which must not wipe the localStorage copy.
const cached = makeHarness();
cached.setLocal(JSON.stringify({font_size: 30, font_weight: 700, line_height: 1.45, text_align: 'center'}));
cached.api.init();
cached.pending[0]({});
await settle();
assert.equal(cached.store['--lyrics-font-size'], '30px', 'a fresh database leaves the cache alone');

// A response that lands after the user moved a slider is ignored.
const guarded = makeHarness();
guarded.api.init();
guarded.api.apply({font_size: 20, font_weight: 700, line_height: 1.45, text_align: 'center'}, true);
guarded.pending[0]({fontSize: 33, textAlign: 'left'});
await settle();
assert.equal(guarded.store['--lyrics-font-size'], '20px', 'the user choice wins');
assert.equal(guarded.store['--lyrics-text-align'], 'center');
""".replace('SOURCE', source('lyrics-settings-popover.js')))
