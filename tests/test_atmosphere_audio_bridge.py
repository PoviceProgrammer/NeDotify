"""The atmosphere shares playback's analyser without owning the audio graph."""

from tests.helpers import HARNESS
from tests.jsdom import run_node, source


def test_atmosphere_provider_never_initializes_or_resumes_audio():
    run_node((HARNESS + r"""
context.window.AudioContext = class {constructor() {throw Error('Backdrop initialized audio')}};
const first = vm.runInContext('getAtmosphereAudioSource()', context);
assert.equal(first.context, null);
assert.equal(first.analyser, null);
assert.equal(first.hasTrack, false);
assert.equal(vm.runInContext('getAtmosphereAudioSource()', context), first, 'reuse the snapshot rather than allocate every frame');
vm.runInContext(`
    audioCtx = {state: 'suspended', resume() {throw Error('Backdrop resumed audio')}};
    analyserNode = {id: 'existing-post-EQ-analyser'};
    playbackState.track = {id: 'track-a'};
`, context);
const active = vm.runInContext('getAtmosphereAudioSource()', context);
assert.equal(active, first);
assert.equal(active.analyser.id, 'existing-post-EQ-analyser');
assert.equal(active.context.state, 'suspended');
assert.equal(active.playing, true);
assert.equal(active.hasTrack, true);
""").replace('SOURCE', source('player.js')))


def test_atmosphere_provider_uses_selected_playback_state_across_pause_and_decks():
    run_node((HARNESS + r"""
vm.runInContext(`
    playbackState.track = {id: 'first'};
    audioCtx = {state: 'running'};
    analyserNode = {id: 'mixed-decks'};
`, context);
const shared = vm.runInContext('getAtmosphereAudioSource()', context);
assert.equal(shared.playing, true);
vm.runInContext('activeAudio.paused = true', context);
assert.equal(vm.runInContext('getAtmosphereAudioSource()', context).playing, false, 'audio pause wins even before a state notification');
vm.runInContext(`
    activeAudio = audioB; activeAudio.paused = false;
    playbackState.track = {id: 'second'};
    playbackState.status = 'loading';
`, context);
assert.equal(vm.runInContext('getAtmosphereAudioSource()', context).playing, false, 'buffering is not audible playback');
vm.runInContext("playbackState.status = 'playing'", context);
assert.equal(vm.runInContext('getAtmosphereAudioSource()', context).playing, true);
assert.equal(shared.analyser.id, 'mixed-decks', 'crossfade does not replace or reconnect the shared analyser');
vm.runInContext("playbackState.status = 'stopped'; analyserNode = null; audioCtx = null", context);
const stopped = vm.runInContext('getAtmosphereAudioSource()', context);
assert.equal(stopped.playing, false);
assert.equal(stopped.hasTrack, false);
assert.equal(stopped.analyser, null);
assert.equal(stopped.context, null);
""").replace('SOURCE', source('player.js')))
