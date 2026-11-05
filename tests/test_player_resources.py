"""Execute player lifecycle and DOM update behavior without changing frame rate."""

from tests.helpers import player_test
from tests.jsdom import run_node, source





def test_progress_updates_only_changed_text_and_accessibility_values_at_full_fps():
    player_test(r"""
subject.setUiFps(60);
for (let index = 0; index < 60; index++) {
    subject.audio.currentTime = 1 + index / 60;
    subject.advanceFrame(10000 + index * 17);
}
assert.equal(transforms, 180, 'all three progress bars retain every requested frame');
assert.equal(textWrites, 3, 'unchanged labels must not recreate text nodes every frame');
assert.ok(attributeWrites < 30, 'rounded aria values change less often than progress transforms');
subject.audio.currentTime = 2;
subject.advanceFrame(12000);
assert.equal(textWrites, 6, 'all labels update immediately when the displayed second changes');
""")


def test_hidden_player_parks_frames_resumes_once_and_still_prefetches():
    player_test(r"""
subject.advanceFrame(10000);
assert.ok(subject.frame);
context.document.hidden = true;
visibilityChanged();
assert.equal(frames.size, 0);
assert.equal(subject.frame, null);
subject.advanceFrame(11000);
assert.equal(frames.size, 0, 'a hidden callback must not recreate its frame loop');
subject.onStateChanged('playing');
assert.equal(frames.size, 0, 'playback state changes must respect hidden rendering');
subject.audio.currentTime = 163;
subject.audio.events.get('timeupdate')();
assert.equal(prefetches, 1, 'audio events still prepare the next track while hidden');
assert.equal(textWrites, 3, 'background playback does not mutate progress labels');
context.document.hidden = false;
visibilityChanged();
visibilityChanged();
assert.equal(frames.size, 2, 'restoring resumes one progress loop and one glow loop');
const frame = subject.frame;
const callback = frames.get(frame);
frames.delete(frame);
callback(12000);
assert.equal(elements.get('pb-time-current').textContent, '2:43');
""")


def test_constant_orbit_glow_does_not_repeat_identical_style_writes():
    player_test(r"""
let glowWrites = 0;
const bar = {style: {setProperty() {glowWrites++}, removeProperty() {}}};
elements.set('player-bar', bar);
subject.onStateChanged('playing');
for (let index = 0; index < 30; index++) {
    const pending = [...frames]; frames.clear();
    for (const [frame, callback] of pending) callback(11000 + index * 34);
}
assert.equal(glowWrites, 2, 'unchanged formatted glow values are written once');
""")


def test_native_minimize_parks_player_when_webview_visibility_stays_visible():
    player_test(r"""
subject.advanceFrame(10000);
classes.add('window-hidden');
for (const callback of documentEvents.get('nedotify:window_visibility_changed')) callback();
assert.equal(context.document.hidden, false);
assert.equal(frames.size, 0, 'native minimize must park the player without document.hidden');
subject.audio.currentTime = 163;
subject.audio.events.get('timeupdate')();
assert.equal(prefetches, 1, 'native minimized playback still prepares the next track');
classes.delete('window-hidden');
for (const callback of documentEvents.get('nedotify:window_visibility_changed')) callback();
assert.ok(subject.frame);
""")


def test_bridge_window_visibility_updates_consumers_once_per_transition():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const classes = new Set(), notifications = [];
const context = vm.createContext({console,
    window: {addEventListener() {}},
    document: {documentElement: {classList: {
        contains: name => classes.has(name),
        toggle(name, value) {value ? classes.add(name) : classes.delete(name)},
    }}, dispatchEvent: event => notifications.push(event)},
    CustomEvent: class {constructor(name, options) {this.type = name; this.detail = options.detail}},
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '') + '\ninitEvents();', context);
context.window.onPythonEvent('window_visibility', {hidden: true});
assert.ok(classes.has('window-hidden'));
assert.equal(notifications[0].type, 'nedotify:window_visibility_changed');
context.window.onPythonEvent('window_visibility', {hidden: true});
assert.equal(notifications.length, 1, 'duplicate native events do not restart effect loops');
context.window.onPythonEvent('window_visibility', {hidden: false});
assert.ok(!classes.has('window-hidden'));
assert.equal(notifications.length, 2);
assert.equal(notifications[1].detail.hidden, false);
""".replace("SOURCE", source("events.js")))


def test_native_hidden_mini_equalizer_parks_and_resumes_without_playback_change():
    player_test(r"""
let spectrumReads = 0, barWrites = 0;
const bars = Array.from({length: 7}, () => ({style: {
    set transform(value) {if (value) barWrites++},
}}));
const equalizer = {classList: {add() {}, remove() {}}, querySelectorAll: () => bars};
context.document.querySelector = selector => selector === '#mini-player-overlay .mp-eq' ? equalizer : null;
context.spectrum = {getByteFrequencyData(data) {spectrumReads++; data.fill(128)}};
vm.runInContext("audioCtx = {state: 'running'}; analyserNode = spectrum;", context);
classes.add('mini-player-active');
subject.onStateChanged('playing');
function tickAll(timestamp) {
    const pending = [...frames.values()]; frames.clear();
    pending.forEach(callback => callback(timestamp));
}
function nativeVisibilityChanged() {
    for (const callback of documentEvents.get('nedotify:window_visibility_changed')) callback();
}
tickAll(10000);
assert.equal(spectrumReads, 1);
assert.equal(barWrites, 7, 'visible mini player paints all seven spectrum bars');
classes.add('window-hidden');
nativeVisibilityChanged();
assert.equal(context.document.hidden, false, 'WebView remains browser-visible after native hide/minimize');
assert.equal(frames.size, 0, 'native hiding parks every mini player animation');
tickAll(11000);
subject.onStateChanged('playing');
tickAll(12000);
assert.equal(spectrumReads, 1, 'hidden playback does not sample the spectrum');
assert.equal(barWrites, 7, 'hidden playback does not animate bars');
classes.delete('window-hidden');
nativeVisibilityChanged();
nativeVisibilityChanged();
tickAll(13000);
assert.equal(spectrumReads, 2, 'restoring resumes exactly one EQ loop without a playback event');
assert.equal(barWrites, 14, 'all seven bars animate on the first restored frame');
tickAll(13016);
assert.equal(spectrumReads, 3, 'visible EQ retains its display-frame cadence');
assert.equal(barWrites, 21);
""")
