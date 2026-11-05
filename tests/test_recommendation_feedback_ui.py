"""Run the shipped feedback and audio listeners without launching WebView."""
from tests.jsdom import run_node, source


def test_feedback_can_be_blocked_restored_and_rejected_without_false_success():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let blocked = false; const writes = []; const events = []; const toasts = [];
const track = {artist: 'Artist', title: 'Song'};
const bridge = {
    get_recommendation_feedback: async () => ({track: blocked, artist: false}),
    set_recommendation_feedback: async (track, kind, value) => {
        writes.push([kind, value]); blocked = value; return {success: true};
    },
};
const context = vm.createContext({window: {pywebview: {api: bridge}, dispatchEvent: event => events.push(event.type)},
    CustomEvent: class {constructor(type) {this.type = type;}},
    showToast: (...args) => toasts.push(args)});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('export async function submitRecommendationFeedback'),
                          code.indexOf('export function showTrackContextMenu')).replace('export ', ''), context);
assert.equal(await context.submitRecommendationFeedback(track, 'track'), true);
assert.equal(await context.submitRecommendationFeedback(track, 'track'), true);
assert.deepEqual(writes, [['track', true], ['track', false]]);
assert.equal(events.length, 2);
assert.deepEqual(events, ['nedotify:recommendation_feedback_changed', 'nedotify:recommendation_feedback_changed']);
bridge.set_recommendation_feedback = async () => ({success: false, error: 'Write failed'});
assert.equal(await context.submitRecommendationFeedback(track, 'artist'), false);
assert.equal(events.length, 2);
assert.equal(toasts.at(-1)[1], 'error');
""".replace('SOURCE', source('utils.js')))


def test_play_request_is_not_counted_until_audible_and_end_is_flushed_before_next():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const calls = []; const listeners = new Map();
const audio = {duration: 180, playbackRate: 2, currentTime: 3, readyState: 4, paused: false, src: 'https://audio/',
    addEventListener(name, fn) {if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(fn);}};
const bridge = {
    report_listening_state: async (...args) => calls.push(['report_listening_state', ...args]),
    next_track: async () => {calls.push(['next_track']); return true;},
};
const context = vm.createContext({console, audio, activeAudio: audio, playbackState: {track: {listening_session: 'token'}, durationMs: 180000, positionMs: 0, status: 'playing'},
    currentTrackRetries: 0, isSeeking: false, seekTimeoutId: null, isDraggingProgress: false,
    isFlowEnabled: false,
        sleepAtTrackEnd: false, automaticTransition: null, playbackGeneration: 0, preparedNext: null, audioSetting: () => false,
    window: {pywebview: {api: bridge}, location: {href: 'http://localhost'}},
        document: {dispatchEvent() {}}, performance: {now: () => 6000}, isPlayerUiHidden: () => false,
    api: async (...args) => calls.push(args), armStallFallback() {}, disarmStallFallback() {},
        onStateChanged() {}, clearTimeout() {}, setEl() {}, setElText() {}, formatTime: () => '',
        checkAutomaticTransition() {}, finishFade() {}, cancelRecovery() {}, paintPlaybackProgress() {},
    CustomEvent: class {}, handleStreamError() {},
});
const code = SOURCE;
const start=code.indexOf('function setupAudioEvents(');
vm.runInContext(code.slice(start,code.indexOf('for (const audio of [audioA, audioB])',start)), context);
context.setupAudioEvents(audio);
async function fire(name) { for (const fn of listeners.get(name) || []) await fn(); }
await fire('play');
assert.equal(calls.length, 0);
await fire('playing');
assert.equal(calls[0][0], 'report_state'); assert.equal(calls[0][3], 'token');
assert.deepEqual(calls[1], ['report_listening_state', 'token', true, false, 180, 2]);
await fire('waiting');
assert.equal(calls.at(-1)[2], false);
await fire('seeking');
assert.equal(calls.at(-1)[2], false);
await fire('seeked');
assert.equal(calls.at(-1)[2], true);
await fire('timeupdate');
assert.deepEqual(calls.at(-1), ['report_position', 3000, 180000, 0, 'token']);
await fire('ended');
assert.deepEqual(calls.at(-2), ['report_listening_state', 'token', false, true, 180, 2]);
assert.deepEqual(calls.at(-1), ['next_track']);
""".replace('SOURCE', source('player.js')))
