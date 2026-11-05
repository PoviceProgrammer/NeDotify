"""Exercise canvas scheduling and resource ownership with deterministic DOM stubs."""

from tests.jsdom import run_node, source


HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
function surface() {
    const listeners = new Map();
    return {
        addEventListener(name, callback) {
            if (!listeners.has(name)) listeners.set(name, new Set());
            listeners.get(name).add(callback);
        },
        removeEventListener(name, callback) { listeners.get(name)?.delete(callback); },
        dispatchEvent(event) {
            for (const callback of [...(listeners.get(event.type) || [])]) callback(event);
        },
        listenerCount(name) { return listeners.get(name)?.size || 0; },
    };
}
function classes(initial = []) {
    const values = new Set(initial);
    return {contains: value => values.has(value), toggle(value, enabled) {
        if (enabled) values.add(value); else values.delete(value);
    }};
}
const frames = new Map(), timers = new Map(), dprListeners = new Set();
const observers = [], mutations = [], operations = [];
let nextId = 0, clock = 1000, playing = true;
function canvasContext() {
    return new Proxy({}, {get(target, property) {
        if (!(property in target)) target[property] = (...args) => {
            operations.push({property, args});
            if (property === 'createLinearGradient' || property === 'createRadialGradient') {
                return {addColorStop() {}};
            }
        };
        return target[property];
    }});
}
function element() {
    const context = canvasContext();
    return {...surface(), nodeType: 1, isConnected: true, style: {}, dataset: {},
        classList: classes(), children: [], width: 0, height: 0, offsetParent: {},
        parentElement: {offsetWidth: 380, offsetHeight: 380},
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); child.parentNode = this; },
        remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); },
        querySelectorAll() { return []; }, matches() { return false; },
        closest() { return null; }, getContext() { return context; },
    };
}
const elements = new Map();
for (const id of ['particles-bg', 'visualizer-canvas', 'home-visualizer-canvas',
    'toggle-particles', 'toggle-visualizer', 'select-visualizer-style']) {
    elements.set(id, element());
}
elements.get('toggle-particles').classList = classes(['on']);
elements.get('home-visualizer-canvas').offsetParent = null;
class IntersectionObserver {
    constructor(callback) {this.callback = callback; this.observed = new Set(); observers.push(this);}
    observe(target) {this.observed.add(target);}
    unobserve(target) {this.observed.delete(target);}
    disconnect() {this.observed.clear();}
}
class MutationObserver {
    constructor(callback) {this.callback = callback; mutations.push(this);}
    observe() {}
}
const window = {...surface(), innerWidth: 1280, innerHeight: 720,
    settings: {ui: {particles_enabled: true}, atmosphere: {enabled: true}}, IntersectionObserver,
    matchMedia() { return {matches: false}; },
    getComputedStyle() { return {getPropertyValue() { return '255, 159, 28'; }}; },
};
const document = {...surface(), hidden: false, hasFocus() {return true;},
    body: element(), documentElement: element(),
    getElementById(id) {return elements.get(id) || null;},
    createElement: element, querySelector() {return null;},
};
elements.set('main-content', element());
const context = vm.createContext({console, window, document, navigator: {hardwareConcurrency: 12},
    IntersectionObserver, MutationObserver, Map, WeakMap, Float64Array, Uint8Array,
    localStorage: {getItem() {return null;}, setItem() {}},
    performance: {now() {return clock;}},
    requestAnimationFrame(callback) {const id = ++nextId; frames.set(id, callback); return id;},
    cancelAnimationFrame(id) {frames.delete(id);},
    setTimeout(callback) {const id = ++nextId; timers.set(id, callback); return id;},
    clearTimeout(id) {timers.delete(id);},
    getCanvasDpr() {return 1;},
    sizeCanvasForDpr(canvas, drawing, width, height) {
        canvas.width = width; canvas.height = height;
        return {cssW: width, cssH: height};
    },
    registerCanvasDprListener(callback) {
        dprListeners.add(callback); return () => dprListeners.delete(callback);
    },
    getIsPlaying() {return playing;}, getVolume() {return 70;},
    getCurrentTrack() {return {title: 'Track'};}, getAudioFrequencyData() {return false;},
    CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
});
function tick(timestamp) {
    clock = timestamp;
    const pending = [...frames.values()]; frames.clear();
    pending.forEach(callback => callback(timestamp));
}
function emit(target, type, detail = {}) {target.dispatchEvent({type, detail});}
function count(property) {return operations.filter(operation => operation.property === property).length;}
const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
vm.runInContext(code + '\nglobalThis.subject = SUBJECT;', context);
const subject = context.subject;
"""


def effects_test(filename, exports, script):
    # The retired particles module is a facade over the production atmosphere
    # components. Evaluate that actual dependency chain in the same DOM/RAF fake.
    code = source(filename)
    if filename == "particles.js":
        code = f"({source('atmosphere-effects.js')} + '\\n' + {source('atmosphere-engine.js')} + '\\n' + {code})"
    run_node(
        HARNESS.replace("SOURCE", code).replace("SUBJECT", exports)
        + script
    )


def test_particle_reconfiguration_releases_old_listeners_timers_and_canvases():
    effects_test("particles.js", "{initParticles, stopParticles}", r"""
for (let index = 0; index < 25; index++) subject.initParticles();
for (const event of ['resize', 'nedotify:appearance_changed', 'nedotify:efficiency_state', 'nedotify:mini_player_toggled']) {
    assert.equal(window.listenerCount(event), 1, event + ' must have one owner after reconfiguration');
}
assert.equal(elements.get('particles-bg').children.length, 1);
assert.equal(frames.size, 1);
emit(window, 'resize');
const lastCanvas = elements.get('particles-bg').children.at(-1);
assert.equal(timers.size, 0, 'atmosphere uses one scheduler, without private effect timers');
subject.stopParticles();
assert.equal(frames.size, 0);
assert.equal(timers.size, 0);
assert.equal(dprListeners.size, 0);
assert.equal(lastCanvas.width, 0);
assert.equal(lastCanvas.height, 0);
assert.equal(elements.get('particles-bg').children.length, 0);
for (const event of ['resize', 'nedotify:appearance_changed', 'nedotify:efficiency_state', 'nedotify:mini_player_toggled']) {
    assert.equal(window.listenerCount(event), 0);
}
""")


def test_particle_efficiency_pause_survives_visibility_mini_player_and_reinit():
    effects_test("particles.js", "{initParticles, stopParticles}", r"""
subject.initParticles();
assert.equal(frames.size, 1);
emit(window, 'nedotify:efficiency_state', {active: true, disable_visualizations: true});
assert.equal(frames.size, 0);
document.hidden = true; emit(document, 'visibilitychange');
document.hidden = false; emit(document, 'visibilitychange');
emit(window, 'nedotify:mini_player_toggled');
subject.initParticles();
assert.equal(frames.size, 0, 'paused effects must not restart through another lifecycle event');
emit(window, 'nedotify:efficiency_state', {active: false});
assert.equal(frames.size, 1);
tick(1100);
assert.ok(count('drawImage') > 0, 'restoring focus must restore visible particles');
subject.stopParticles();
emit(window, 'nedotify:efficiency_state', {active: false});
assert.equal(frames.size, 0, 'a disabled particle field must stay stopped');
""")


def test_particle_fps_setting_preserves_active_battery_limit():
    effects_test("particles.js", "{initParticles, setParticlesFps}", r"""
subject.initParticles();
const before = count('clearRect');
emit(window, 'nedotify:battery_saver_changed', {isBatteryMode: true});
subject.setParticlesFps(30);
tick(1034);
assert.equal(count('clearRect'), before, 'changing requested FPS must preserve the active battery limit');
tick(1084);
assert.equal(count('clearRect'), before + 1);
emit(window, 'nedotify:battery_saver_changed', {isBatteryMode: false});
tick(1118);
assert.equal(count('clearRect'), before + 2, 'normal cadence must resume immediately');
""")


def test_native_window_minimize_parks_particles_even_when_webview_reports_visible():
    effects_test("particles.js", "{initParticles}", r"""
subject.initParticles();
assert.equal(frames.size, 1);
assert.equal(document.hidden, false);
document.documentElement.classList.toggle('window-hidden', true);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(frames.size, 0);
emit(document, 'visibilitychange');
emit(window, 'nedotify:mini_player_toggled');
subject.initParticles();
assert.equal(frames.size, 0, 'native minimized state must survive unrelated restart paths');
document.documentElement.classList.toggle('window-hidden', false);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(frames.size, 1, 'restoring the native window must resume the particle field');
""")


def test_visualizer_reuses_gradients_keeps_all_bars_and_parks_offscreen():
    effects_test("visualizer.js", "{initVisualizer, notifyPlaybackState}", r"""
subject.initVisualizer();
tick(1000); tick(1050);
assert.equal(count('fillRect'), 96, 'both frames must draw every one of the 48 bars');
assert.equal(count('createLinearGradient'), 1, 'an unchanged visible gradient must be reused');
const primary = elements.get('visualizer-canvas');
const observer = observers[0];
observer.callback([{target: primary, isIntersecting: false}]);
tick(1100);
assert.equal(frames.size, 0, 'offscreen canvases must not retain a frame loop');
assert.equal(count('fillRect'), 96);
observer.callback([{target: primary, isIntersecting: true}]);
tick(1150);
assert.equal(count('fillRect'), 144, 'returning onscreen must immediately restore the full visualizer');
assert.equal(count('createLinearGradient'), 1);
playing = false;
tick(1200);
assert.equal(count('createLinearGradient'), 2, 'pause changes gradient opacity');
assert.equal(frames.size, 0, 'a paused visualizer draws an ambient frame once and then stops');
emit(window, 'resize'); tick(1250);
assert.equal(count('createLinearGradient'), 3, 'resize must invalidate gradients for the canvas transform');
""")


def test_visualizer_pause_cannot_restart_and_destroy_releases_resources():
    effects_test("visualizer.js", "{initVisualizer, notifyPlaybackState, destroyVisualizer}", r"""
subject.initVisualizer(); subject.initVisualizer();
assert.equal(window.listenerCount('resize'), 1);
assert.equal(dprListeners.size, 1);
assert.equal(frames.size, 1);
emit(window, 'nedotify:efficiency_state', {active: true, disable_visualizations: true});
document.hidden = true; emit(document, 'visibilitychange');
document.hidden = false; emit(document, 'visibilitychange');
emit(window, 'nedotify:page_changed'); subject.notifyPlaybackState(true);
assert.equal(frames.size, 0);
emit(window, 'nedotify:efficiency_state', {active: false});
assert.equal(frames.size, 1);
subject.destroyVisualizer();
assert.equal(window.listenerCount('resize'), 0);
assert.equal(dprListeners.size, 0);
assert.equal(observers[0].observed.size, 0);
assert.equal(timers.size, 0);
emit(window, 'nedotify:page_changed'); subject.notifyPlaybackState(true);
assert.equal(frames.size, 0);
""")


def test_native_window_minimize_parks_visualizer_even_when_webview_reports_visible():
    effects_test("visualizer.js", "{initVisualizer, notifyPlaybackState}", r"""
subject.initVisualizer();
assert.equal(frames.size, 1);
assert.equal(document.hidden, false);
document.documentElement.classList.toggle('window-hidden', true);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(frames.size, 0);
emit(document, 'visibilitychange');
emit(window, 'nedotify:page_changed');
subject.notifyPlaybackState(true);
assert.equal(frames.size, 0, 'playback and page changes must not revive a minimized visualizer');
document.documentElement.classList.toggle('window-hidden', false);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(frames.size, 1);
tick(1100);
assert.equal(count('fillRect'), 48, 'restoring the native window must restore every bar');
""")


def test_efficiency_uses_native_window_minimized_state_alongside_document_visibility():
    effects_test("efficiency.js", "{initEfficiency}", r"""
const states = [];
window.addEventListener('nedotify:efficiency_state', event => states.push(event.detail));
subject.initEfficiency();
assert.equal(states.at(-1).active, false);
assert.equal(document.hidden, false);
document.documentElement.classList.toggle('window-hidden', true);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(states.at(-1).active, true);
document.documentElement.classList.toggle('window-hidden', false);
emit(document, 'nedotify:window_visibility_changed');
assert.equal(states.at(-1).active, false);
document.hidden = true;
emit(document, 'visibilitychange');
assert.equal(states.at(-1).active, true, 'the standard browser visibility path must remain supported');
""")


def test_blur_observer_releases_removed_cards_and_preserves_dom_moves():
    effects_test("efficiency.js", "{initBlurObserver}", r"""
const card = element(), nested = element(), root = element();
card.matches = () => true;
card.querySelectorAll = () => [nested];
root.querySelectorAll = () => [card, nested];
    elements.set('main-content', root);
subject.initBlurObserver(); subject.initBlurObserver();
assert.equal(observers.length, 1);
assert.equal(mutations.length, 1);
const observer = observers[0];
assert.equal(observer.observed.size, 2);
mutations[0].callback([{removedNodes: [card], addedNodes: [card]}]);
assert.equal(observer.observed.size, 2, 'moving attached cards must preserve observation');
card.isConnected = false; nested.isConnected = false;
mutations[0].callback([{removedNodes: [card], addedNodes: []}]);
assert.equal(observer.observed.size, 0, 'discarded cards and descendants must be released');
card.isConnected = true; nested.isConnected = true;
mutations[0].callback([{removedNodes: [], addedNodes: [card]}]);
assert.equal(observer.observed.size, 2, 'reattached cards must be observed again');
""")
