"""Run the shipped audio/lyrics consumers with an isolated, deterministic bridge."""
from tests.jsdom import run_node, source


LYRICS_HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let track = {source: 'youtube', source_id: 'a', title: 'First', artist: 'Artist', duration: 180};
let clock = 1000;
class MockDate extends Date {static now() {return clock}}
const calls = [];
function element() { return {children: [], dataset: {}, style: {}, innerHTML: '',
 appendChild(el) {this.children.push(el)}, addEventListener() {}, querySelector() {return null}}; }
const container = element();
const context = vm.createContext({console, Date: MockDate, Map, JSON,
 getLyricsPlaybackClock: () => ({paused: true, buffering: true, positionMs: 0}),
 getCurrentTrack: () => track, getContainers: () => [container],
 localStorage: {getItem() {return null}},
 document: {getElementById() {return null}, createElement: element},
 window: {pywebview: {api: {get_lyrics(...args) {calls.push(args); return Promise.resolve({status: 'loading'})}}}},
 resetLyricsScroll() {}, updateOffsetBadges() {}, setOffsetControlsEnabled() {},
 updateLyricsPosition() {}, renderIcons() {}, parseLrc() {return []},
 refreshKineticState() {return {}}, ensureMeasured() {return false},
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('let parsedLyrics'), code.indexOf('export function toggleTranslation(')) +
 code.slice(code.indexOf('export function loadCurrentTrackLyrics('), code.indexOf('export function parseLrc(')).replaceAll('export ', '') +
 '\nglobalThis.subject = {loadCurrentTrackLyrics, renderLyrics, cache: lyricsMemoryCache};', context);
const subject = context.subject;
function publish(index, text, phase = 'final', revision = 1) {
 subject.renderLyrics({request_id: calls[index][5], revision, phase, plainLyrics: text, status: 'found'});
}
"""


def lyrics_test(script):
    run_node((LYRICS_HARNESS + script).replace('SOURCE', source('lyrics.js')))


def test_reopening_pending_lyrics_shares_request_and_streamed_upgrades():
    lyrics_test(r"""
subject.loadCurrentTrackLyrics();
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 1);
publish(0, 'Plain text', 'partial');
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 1, 'opening the overlay must preserve the in-flight upgrade');
publish(0, 'Better text', 'final', 2);
track = {...track, source_id: 'b', title: 'Second'};
subject.loadCurrentTrackLyrics();
publish(1, 'Second text');
track = {...track, source_id: 'a', title: 'First'};
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 2, 'a successful revisit must render without a bridge round trip');
assert.equal(subject.cache.size, 2);
assert.equal(container.children.at(-1).textContent, 'Better text');
""")


def test_lyrics_unknown_duration_upgrade_dedup_and_stale_result():
    lyrics_test(r"""
track.duration = 0;
subject.loadCurrentTrackLyrics();
subject.loadCurrentTrackLyrics(181000);
subject.loadCurrentTrackLyrics(181000);
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 2, 'new duration may upgrade a lookup once');
assert.equal(calls[1][2], 181000);
publish(0, 'Stale old-duration lyrics');
assert.equal(subject.cache.size, 0);
publish(1, 'Known-duration text');
subject.loadCurrentTrackLyrics(181000);
assert.equal(calls.length, 2);
""")


def test_lyrics_cloud_resolution_keeps_request_and_partial_result_can_retry():
    lyrics_test(r"""
subject.loadCurrentTrackLyrics();
track = {...track, file_path: 'https://cdn.example/track.mp3?signature=old'};
subject.loadCurrentTrackLyrics();
track = {...track, file_path: 'https://other-cdn.example/track.mp3?signature=new'};
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 1, 'resolving an online stream must keep the lyrics lookup');
publish(0, 'Partial text', 'partial');
assert.equal(subject.cache.size, 0, 'a partial response must not prevent later synced upgrades');
clock += 16000;
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 2, 'a lost final response must not strand the lookup permanently');
publish(0, 'Stale result after retry', 'final', 2);
assert.equal(subject.cache.size, 0);
publish(1, 'Final text');
assert.equal(subject.cache.size, 1);
""")


def test_lyrics_failures_retry_and_cache_is_bounded_without_cross_file_reuse():
    lyrics_test(r"""
subject.loadCurrentTrackLyrics();
subject.renderLyrics({request_id: calls[0][5], revision: 1, phase: 'final', status: 'unavailable'});
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, 2, 'a temporary provider failure must remain retryable');
for (let i = 0; i < 44; i++) {
 track = {source: 'local', id: i + 1, title: 'Track ' + i, artist: 'Artist', duration: 180, file_path: 'C:/music/' + i + '.mp3'};
 subject.loadCurrentTrackLyrics(); publish(calls.length - 1, 'Text ' + i);
}
assert.equal(subject.cache.size, 40);
const before = calls.length;
track = {...track, file_path: 'C:/other/43.mp3'};
subject.loadCurrentTrackLyrics();
assert.equal(calls.length, before + 1, 'embedded lyrics for different local files must not collide');
""")


def test_audio_prefetch_reuses_buffer_and_error_or_teardown_reloads():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let instances = 0, destroyed = 0;
class Hls {static isSupported() {return true} constructor() {instances++} loadSource() {} attachMedia() {} destroy() {destroyed++}}
const context = vm.createContext({console, playbackState:{track:null}, window: {Hls, PROXY_PORT: 1234, PROXY_TOKEN: 'secret token'}});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function destroyHls('), code.indexOf('// Prefetch state for the finite playback queue')), context);
function audio() {return {src: '', currentTime: 0, error: null, loads: 0,
 removeAttribute() {}, load() {this.loads++}};}
const direct = audio();
context.loadAudioSource(direct, 'https://cdn.example/track.mp3');
const loads = direct.loads;
context.loadAudioSource(direct, 'https://cdn.example/track.mp3');
assert.equal(direct.loads, loads, 'playing a prefetched URL must retain its request and buffer');
direct.error = {code: 2};
context.loadAudioSource(direct, 'https://cdn.example/track.mp3');
assert.ok(direct.loads > loads, 'failed media must be reloaded');
direct.error = null;
const afterError = direct.loads;
context.destroyHls(direct);
context.loadAudioSource(direct, 'https://cdn.example/track.mp3');
assert.ok(direct.loads > afterError, 'teardown must invalidate reuse even for non-HLS files');
const hls = audio();
context.loadAudioSource(hls, 'https://cdn.example/playlist.m3u8');
context.loadAudioSource(hls, 'https://cdn.example/playlist.m3u8');
assert.equal(instances, 1); assert.equal(destroyed, 0);
context.loadAudioSource(hls, 'https://cdn.example/other.m3u8');
assert.equal(instances, 2); assert.equal(destroyed, 1);
const local = audio();
context.loadAudioSource(local, 'C:\\Music\\Track.mp3');
assert.match(local.src, /^http:\/\/127\.0\.0\.1:1234\/api\/stream\?url=/);
assert.ok(local.src.includes('&k=secret%20token'));
const localLoads = local.loads;
context.loadAudioSource(local, 'C:\\Music\\Track.mp3');
assert.equal(local.loads, localLoads, 'local prefetch and play must use the same proxy URL');
""".replace('SOURCE', source('player.js')))
