"""Status-bar mini player and live audio settings regression coverage."""
from tests.test_player_recovery_transitions import player_test
from tests.jsdom import source


def test_unknown_track_duration_never_becomes_an_infinite_timeline():
    player_test(r"""
for (const duration of [Infinity, NaN, -1, undefined]) {
 player.onTrackChanged({...first, source_id: String(duration), duration});
 assert.equal(vm.runInContext('playbackState.durationMs', context), 0);
 for (const prefix of ['pb','pp','mp']) {
  assert.equal(elements.get(prefix+'-progress-track').getAttribute('aria-disabled'), 'true');
 }
}
""")


def test_normalization_toggle_applies_to_the_current_track_without_restarting():
    player_test(r"""
player.onTrackChanged({...first, loudness_lufs: -8});
const active = player.active;
active.currentTime = 37;
context.window.settings.audio.volume_normalization = true;
vm.runInContext('applyAudioSettings({volume_normalization:true})', context);
assert.ok(Math.abs(active.volume - .7 * Math.pow(10, -6 / 20)) < .001);
assert.equal(active.currentTime, 37);
context.window.settings.audio.volume_normalization = false;
vm.runInContext('applyAudioSettings({volume_normalization:false})', context);
assert.equal(active.volume, .7);
assert.equal(player.active, active);
""")


def test_slow_seek_stays_pending_until_the_media_reports_completion():
    player_test(r"""
player.onTrackChanged(first);
player.active.seeking = true;
vm.runInContext('seekTo(90000)', context);
const fallback = [...timers].find(([id,timer])=>timer.delay === 1500);
fallback[1].callback();
assert.equal(vm.runInContext('isSeeking',context),true,'a slow HLS seek must not resume the old clock');
player.active.seeking = false;
player.active.events.get('seeked')();
assert.equal(vm.runInContext('isSeeking',context),false);
""")


def test_global_download_helper_propagates_failure_to_a_recycled_row():
    from tests.test_library_virtualization import run_library
    run_library("const PLAYER_SOURCE = " + source('player.js') + ";\n" + r"""
const helper = PLAYER_SOURCE.slice(PLAYER_SOURCE.indexOf('export async function downloadTrack('),
                                  PLAYER_SOURCE.indexOf('function updateRepeatIcon('));
load(helper);
window.NeDotify = {downloadTrack: context.downloadTrack};
let reject;
window.pywebview.api.download_track = () => new Promise((resolve, fail) => {reject = fail});
const list = mount();
rowAt(6).querySelector('.download-btn').emit('click');
scrollTo(500); scrollTo(0);
assert.ok(rowAt(6).querySelector('.download-btn').classList.contains('downloading'));
reject(Error('bridge rejected'));
for (let index=0;index<10;index++) await Promise.resolve();
assert.ok(!rowAt(6).querySelector('.download-btn').classList.contains('downloading'));
assert.equal(tracks[6].is_downloaded, undefined);
window.pywebview = null;
assert.equal((await context.downloadTrack(tracks[6])).success, false);
list.destroy();
""")
