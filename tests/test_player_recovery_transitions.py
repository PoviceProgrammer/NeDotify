from tests.helpers import HARNESS
from tests.jsdom import run_node, source


LIFECYCLE = r"""
const timers = new Map(), intervals = new Map(), mediaEvents = outputEvents;
let nextTimer = 0, clock = 10000;
context.performance.now = () => clock;
context.setTimeout = (callback, delay) => {const id = ++nextTimer; timers.set(id, {callback, delay}); return id};
context.clearTimeout = id => timers.delete(id);
context.setInterval = (callback, delay) => {const id = ++nextTimer; intervals.set(id, callback); return id};
context.clearInterval = id => intervals.delete(id);
context.window.settings = {audio: {}};
context.updatePlayingTrackInDOM = () => {};
context.getCoverUrl = () => '';
context.navigator.mediaDevices = {
    enumerateDevices: async () => [],
    addEventListener(name, callback) {mediaEvents.set(name, callback)},
};
vm.runInContext(`
audioA.pause = audioB.pause = function() {this.paused = true};
audioA.play = audioB.play = function() {this.paused = false; return Promise.resolve()};
audioA.load = audioB.load = function() {this.loads = (this.loads || 0) + 1};
isInitialLoad = false;
globalThis.lifecycle = {playTrack, onTrackChanged, handleStreamError, stopPlaybackForQueueEnd,
    setAudioOutput, listAudioOutputs, checkAutomaticTransition, checkPlaybackLookahead, togglePlayPause,
    get active() {return activeAudio}, get track() {return playbackState.track},
    get retries() {return currentTrackRetries}, get pending() {return pendingResume},
    get prepared() {return preparedNext}, get outgoing() {return outgoingAudio},
    get actualDevice() {return actualOutputDevice},
    get audios() {return [audioA, audioB]},
    prepare(track) {const audio = activeAudio === audioA ? audioB : audioA;
        loadAudioSource(audio, track.stream_url); audio.readyState = 4;
        preparedNext = {track, key: trackPlaybackKey(track), queueVersion: currentQueueVersion}},
};`, context);
const player = context.lifecycle;
const first = {title: 'First', artist: 'Artist', source: 'youtube', source_id: 'first', duration: 180, stream_url: 'https://cdn.example/first.mp3'};
const second = {...first, title: 'Second', source_id: 'second', stream_url: 'https://cdn.example/second.mp3'};
async function flush() {for (let index = 0; index < 10; index++) await Promise.resolve()}
async function retryTimer() {
    const entry = [...timers].find(([id, timer]) => timer.delay === 1500 || timer.delay === 3000);
    assert.ok(entry, 'expected a bounded recovery timer'); timers.delete(entry[0]);
    await entry[1].callback(); await flush();
}
"""


def player_test(script):
    harness = HARNESS.replace("const frames =", "const outputEvents = new Map(); const frames =").replace(
        "Audio: AudioStub, navigator: {},", "Audio: AudioStub, navigator: {mediaDevices: {addEventListener(name, callback) {outputEvents.set(name, callback)}}},"
    )
    run_node((harness + LIFECYCLE + script).replace("SOURCE", source("player.js")))


def test_prefetch_obeys_backend_preference_over_a_stale_browser_mirror():
    player_test(r"""
player.onTrackChanged(first);
context.window.settings.player={player_prefetch:false};
context.localStorage.getItem=key=>key==='nedotify_player_player_prefetch'?'true':null;
let requests=0;context.window.pywebview.api.get_next_track=async()=>{requests++;return null;};
player.checkPlaybackLookahead(19);await flush();assert.equal(requests,0);
context.window.settings.player.player_prefetch=true;
player.checkPlaybackLookahead(19);await flush();assert.equal(requests,1);
player.checkPlaybackLookahead(18);await flush();assert.equal(requests,1,'one in-flight prefetch');
""")


def test_clicking_paused_same_track_with_cached_stream_restarts_playback():
    player_test(r"""
const track={...first,autoplay:true,playback_epoch:1};
player.onTrackChanged(track);assert.equal(player.active.paused,false);
player.active.pause();
player.onTrackChanged({...track,playback_epoch:2});
assert.equal(player.active.paused,false,'Explicit Play must restart a cached paused track');
""")


def test_recovery_preserves_position_and_inactive_metadata_does_not_erase_resume():
    player_test(r"""
context.window.pywebview.api.recover_stream = async () => ({ok: true, stream_url: 'https://cdn.example/fresh.mp3'});
player.playTrack(first, first.stream_url);
const old = player.active; old.currentTime = 42.5;
player.handleStreamError(old, 'network');
await retryTimer();
assert.equal(player.pending.ms, 42500);
old.events.get('loadedmetadata')();
assert.equal(player.pending.ms, 42500, 'metadata on inactive media must leave recovery state intact');
player.active.events.get('loadedmetadata')();
assert.equal(player.active.currentTime, 42.5);
assert.equal(player.pending, null);
assert.equal(player.retries, 1);
""")


def test_session_restore_stays_paused_until_explicit_play_and_seeks_after_resolution():
    player_test(r"""
vm.runInContext('isInitialLoad = true', context);
const restoring = {title: 'Restored', artist: 'Artist', source: 'youtube', source_id: 'restored',
    duration: 180, restore_position_sec: 37, autoplay: false};
player.onTrackChanged(restoring);
assert.equal(player.active.paused, true);
assert.equal(player.pending.ms, 37000);
player.onTrackChanged({...restoring, restore_position_sec: undefined,
    stream_url: 'https://cdn.example/restored.mp3'});
assert.equal(player.active.paused, true, 'resolved restore metadata must not autoplay');
player.active.duration = 180;
player.active.events.get('loadedmetadata')();
assert.equal(player.active.currentTime, 37);
assert.equal(player.pending, null);

const clicked = {...restoring, title: 'Clicked', source_id: 'clicked', restore_position_sec: 0, autoplay: true};
context.window.pywebview.api.play_track = async () => ({success: true});
player.onTrackChanged(clicked);
player.onTrackChanged({...clicked, stream_url: 'https://cdn.example/clicked.mp3'});
await flush();
assert.equal(player.track.source_id, 'clicked');
assert.equal(player.active.paused, false, 'first explicit play must start after stream resolution');
""")


def test_track_and_timeline_facts_share_one_playback_state_object():
    player_test(r"""
player.playTrack(first, first.stream_url);
await flush();
const state = vm.runInContext('playbackState', context);
assert.equal(state.track.source_id, 'first');
// BUG-A1-013: 'playing' is claimed only after the element reports audibility.
assert.equal(state.status, 'loading');
player.active.events.get('playing')();
assert.equal(vm.runInContext('playbackState', context).status, 'playing');
assert.equal(typeof state.durationMs, 'number');
assert.equal(typeof state.positionMs, 'number');
assert.equal('targetPosMs' in context, false, 'the unused seek mirror must stay removed');
""")


def test_recovery_stays_bounded_when_replacement_plays_then_fails():
    player_test(r"""
let requests = 0;
context.window.pywebview.api.recover_stream = async () => ({ok: true, stream_url: 'https://cdn.example/fresh' + ++requests + '.mp3'});
player.playTrack(first, first.stream_url);
for (let index = 0; index < 2; index++) {
    player.handleStreamError(player.active, 'network'); await retryTimer();
    player.active.events.get('playing')();
}
player.handleStreamError(player.active, 'network');
assert.equal(requests, 2, 'playing a few milliseconds must not reset the retry budget');
assert.ok(player.audios.every(audio => audio.src === ''));
""")


def test_skip_discards_a_recovery_result_and_queue_end_releases_both_elements():
    player_test(r"""
let finish;
context.window.pywebview.api.recover_stream = () => new Promise(resolve => finish = resolve);
player.playTrack(first, first.stream_url);
player.handleStreamError(player.active, 'network');
const pending = retryTimer(); await flush();
player.playTrack(second, second.stream_url);
finish({ok: true, stream_url: 'https://cdn.example/stale.mp3'});
await pending;
assert.equal(player.track.source_id, 'second');
assert.equal(player.active.src, second.stream_url);
player.prepare(first);
player.stopPlaybackForQueueEnd();
assert.ok(player.audios.every(audio => audio.src === '' && audio.paused));
assert.equal(timers.size, 0);
""")


def test_crossfade_waits_for_ready_media_then_advances_once_and_releases_outgoing():
    player_test(r"""
let advances = 0;
context.window.settings.audio = {crossfade_enabled: true, crossfade_duration_sec: 3};
context.window.pywebview.api.next_track = async () => {advances++; player.onTrackChanged(second); return second};
player.playTrack(first, first.stream_url);
player.active.events.get('playing')();
const old = player.active; old.currentTime = 177; old.duration = 180;
player.prepare(second);
player.checkAutomaticTransition(3); player.checkAutomaticTransition(3);
await flush();
assert.equal(advances, 1);
assert.equal(old.paused, false, 'outgoing audio remains audible during the fade');
assert.equal(player.active.volume, 0);
clock += 1500;
for (const callback of [...intervals.values()]) callback();
assert.ok(old.volume > 0 && old.volume < 0.7);
assert.ok(player.active.volume > 0 && player.active.volume < 0.7);
clock += 1500;
for (const callback of [...intervals.values()]) callback();
assert.equal(old.src, ''); assert.equal(old.paused, true);
assert.equal(player.active.volume, 0.7);
assert.equal(intervals.size, 0);
""")


def test_gapless_starts_preloaded_audio_before_bridge_and_adopts_fresh_session():
    player_test(r"""
context.window.settings.audio.gapless_playback = true;
context.window.pywebview.api.report_listening_state = () => new Promise(() => {});
let finishAdvance;
context.window.pywebview.api.next_track = () => new Promise(resolve => finishAdvance = resolve);
player.playTrack(first, first.stream_url); const old = player.active;
player.prepare(second); const incoming = player.audios.find(audio => audio !== old);
const loads = incoming.loads;
const ended = old.events.get('ended')(); await flush();
assert.equal(player.active, incoming);
assert.equal(incoming.loads, loads, 'gapless consumes the existing decoded preload');
assert.equal(incoming.paused, false, 'bridge accounting must not hold up the next audio');
player.onTrackChanged({...second, stream_url: 'http://127.0.0.1/resolved', listening_session: 'new-session'});
assert.equal(incoming.loads, loads, 'a changed proxy URL must not reload the already playing gapless track');
assert.equal(player.track.listening_session, 'new-session');
finishAdvance(second); await ended;
""")


def test_output_switch_updates_both_elements_and_rolls_back_partial_failure():
    player_test(r"""
const writes = [];
player.audios[0].setSinkId = async device => writes.push(['a', device]);
player.audios[1].setSinkId = async device => {writes.push(['b', device]); if (device === 'missing') throw {name: 'NotFoundError'}};
assert.equal((await player.setAudioOutput('headphones', {persist: false})).ok, true);
assert.equal(player.actualDevice, 'headphones');
const result = await player.setAudioOutput('missing', {persist: false});
assert.equal(result.ok, false);
assert.equal(player.actualDevice, 'headphones');
assert.deepEqual(writes.slice(-2), [['a', 'headphones'], ['b', 'headphones']]);
""")


def test_output_context_sink_and_permission_failure_leave_playback_intact():
    player_test(r"""
vm.runInContext('audioCtx = {setSinkId: async device => globalThis.contextSink = device}', context);
player.playTrack(first, first.stream_url); player.active.currentTime = 52;
assert.equal((await player.setAudioOutput('headphones', {persist: false})).ok, true);
assert.equal(context.contextSink, 'headphones');
context.navigator.mediaDevices.selectAudioOutput = async () => {throw {name: 'NotAllowedError'}};
const result = await player.listAudioOutputs(true);
assert.equal(result.code, 'NotAllowedError');
assert.equal(player.active.currentTime, 52);
assert.equal(player.active.paused, false);
""")


def test_output_persistence_failure_restores_the_previous_device_and_preference():
    player_test(r"""
for (const audio of player.audios) audio.setSinkId = async () => {};
assert.equal((await player.setAudioOutput('headphones', {persist:false})).ok,true);
context.window.settings.audio.output_device='headphones';
context.window.pywebview.api.save_setting=async()=>false;
const result=await player.setAudioOutput('speakers');
assert.equal(result.ok,false,'changing the sink must not hide a failed durable save');
assert.equal(player.actualDevice,'headphones');
assert.equal(context.window.settings.audio.output_device,'headphones');
""")


def test_prefetch_callback_after_skip_cannot_load_stale_audio():
    player_test(r"""
let finishPreview;
context.window.pywebview.api.get_next_track = () => new Promise(resolve => finishPreview = resolve);
player.playTrack(first, first.stream_url);
player.checkPlaybackLookahead(19);
player.playTrack(second, second.stream_url);
finishPreview({...first, stream_url: 'https://cdn.example/stale.mp3'}); await flush();
assert.equal(player.prepared, null);
assert.equal(player.active.src, second.stream_url);
assert.ok(player.audios.every(audio => audio.src !== 'https://cdn.example/stale.mp3'));
""")


def test_disconnected_device_falls_back_then_reconnects_without_seeking_or_changing_volume():
    player_test(r"""
const writes = [];
for (const audio of player.audios) audio.setSinkId = async device => writes.push(device);
let outputs = [{kind: 'audiooutput', deviceId: 'headphones', label: 'Headphones'}];
context.navigator.mediaDevices.enumerateDevices = async () => outputs;
await player.setAudioOutput('headphones', {persist: false});
player.playTrack(first, first.stream_url); player.active.currentTime = 81;
const volume = player.active.volume;
outputs = [];
await mediaEvents.get('devicechange')();
assert.equal(player.actualDevice, 'default');
outputs = [{kind: 'audiooutput', deviceId: 'headphones', label: 'Headphones'}];
await mediaEvents.get('devicechange')();
assert.equal(player.actualDevice, 'headphones');
assert.equal(player.active.currentTime, 81);
assert.equal(player.active.volume, volume);
assert.equal(player.active.paused, false);
assert.deepEqual(writes, ['headphones', 'headphones', '', '', 'headphones', 'headphones']);
""")


def test_pausing_during_recovery_cancels_stale_result_even_when_media_already_paused():
    player_test(r"""
let finish;
context.window.pywebview.api.recover_stream = () => new Promise(resolve => finish = resolve);
player.playTrack(first, first.stream_url);
const old = player.active;
player.handleStreamError(old, 'error');
const pending = retryTimer(); await flush();
old.paused = true;
player.togglePlayPause();
finish({ok: true, stream_url: 'https://cdn.example/stale.mp3'});
await pending;
assert.equal(player.active, old);
assert.equal(old.paused, true);
assert.equal(old.src, first.stream_url);
""")


def test_seek_finishes_crossfade_and_cancels_outgoing_audio():
    player_test(r"""
context.window.settings.audio = {crossfade_enabled: true, crossfade_duration_sec: 3};
context.window.pywebview.api.next_track = async () => {player.onTrackChanged(second); return second};
player.playTrack(first, first.stream_url);
player.active.events.get('playing')();
const old = player.active; old.currentTime = 177;
player.prepare(second); player.checkAutomaticTransition(3); await flush();
vm.runInContext('seekTo(50000)', context);
assert.equal(player.outgoing, null);
assert.equal(intervals.size, 0);
assert.equal(old.paused, true);
assert.equal(old.src, '');
assert.equal(player.active.currentTime, 50);
""")


def test_sleep_at_track_end_blocks_crossfade_and_gapless_until_cancelled():
    player_test(r"""
let advances=0,pauses=0;
const events=[];
context.Event=class {constructor(type){this.type=type;}};
context.window.dispatchEvent=event=>events.push(event.type);
context.window.settings.audio={crossfade_enabled:true,crossfade_duration_sec:3,gapless_playback:true};
context.window.pywebview.api.next_track=async()=>{advances++;return second;};
context.window.pywebview.api.report_state=async state=>{if(state==='paused')pauses++;};
player.playTrack(first,first.stream_url);player.active.events.get('playing')();
player.prepare(second);
vm.runInContext('setSleepAtTrackEnd(true)',context);
player.checkAutomaticTransition(2);await flush();assert.equal(advances,0);
await player.active.events.get('ended')();await flush();
assert.equal(advances,0);assert.equal(pauses,1);
assert.ok(player.audios.every(audio=>audio.paused&&audio.src===''));
assert.deepEqual(events,['nedotify:sleep_timer_finished']);
// A cancelled timer must restore ordinary queue advancement.
player.playTrack(first,first.stream_url);player.active.events.get('playing')();player.prepare(second);
vm.runInContext('setSleepAtTrackEnd(true);setSleepAtTrackEnd(false)',context);
player.checkAutomaticTransition(2);await flush();assert.equal(advances,1);
""")
