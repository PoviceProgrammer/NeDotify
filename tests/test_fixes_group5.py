"""Tests for Group #5 bug fixes (Audio Engine, Queue & Playback).

Covers:
- BUG-WIN-016: Incorrect history and track 0 looping under Shuffle + Repeat All.
- BUG-WIN-017: Manual 'Next' stuck under Repeat One; force_advance=True on explicit next.
- BUG-WIN-018: Removing duplicate queue items in shuffle mode drops only the targeted instance.
- BUG-WIN-019: Fast skip resolution cancellation token prevents worker starvation.
- BUG-WIN-020: Web Audio API AudioContext recreation avoids DOMException on MediaElementSource.
- BUG-WIN-040: Browser autoplay NotAllowedError pauses without triggering network stream recovery.
- BUG-WIN-041: Local track resolution resolves file_path when url is absent.
- BUG-WIN-042: Volume normalization keeps transparent peak limiter without aggressive overcompression.
"""

import os
import time
import threading
import pytest

from audio.queue import PlaybackQueue
from audio.engine import AudioEngine
from core.api import AppApi
from tests.helpers import HARNESS
from tests.jsdom import run_node, source


def _make_tracks(n=5):
    return [
        {
            "id": i,
            "title": f"Track {i}",
            "artist": "Artist",
            "source": "youtube",
            "source_id": f"vid_{i}",
        }
        for i in range(n)
    ]


# ==============================================================================
# BUG-WIN-016: Shuffle + Repeat All
# ==============================================================================

def test_bug_win_016_shuffle_repeat_all_reshuffles_without_pinning_track_zero():
    """Under Shuffle + Repeat All, wrapping at the end of the queue must not pin

    the old track 0 to position 0 on every wrap.
    """
    q = PlaybackQueue()
    tracks = _make_tracks(10)
    q.repeat = "all"
    q.set_tracks(tracks, 0)
    q.shuffle = True

    # Play through the queue to trigger multiple wrap-arounds
    first_tracks_seen = []
    for _ in range(5):
        # Advance to the end of the queue
        while q.current_index < q.count - 1:
            q.next_track()
        # Next track wraps around with repeat all + shuffle
        wrapped = q.next_track()
        assert wrapped is not None
        assert q.current_index == 0
        first_tracks_seen.append(wrapped["id"])

    # Across multiple wraps, the reshuffled queue should not always start with
    # the exact same track ID (which was the old bug where track 0 was pinned).
    # With 10 tracks and 5 reshuffles, having at least 2 distinct starting tracks
    # confirms track 0 is not statically pinned.
    assert len(set(first_tracks_seen)) >= 2, f"Track 0 looped: {first_tracks_seen}"


def test_bug_win_016_shuffle_repeat_all_history_navigation_points_to_last_played():
    """Under Shuffle + Repeat All, previous_track() immediately after wrap

    must return the track that was playing right before the wrap.
    """
    q = PlaybackQueue()
    tracks = _make_tracks(4)
    q.repeat = "all"
    q.set_tracks(tracks, 0)
    q.shuffle = True

    # Advance to the last track
    for _ in range(q.count - 1):
        q.next_track()

    last_played_before_wrap = q.current_track
    assert last_played_before_wrap is not None

    # Wrap around
    wrapped = q.next_track()
    assert wrapped is not None
    assert q.current_index == 0

    # Back-navigation must return the track that was playing before wrap
    prev = q.previous_track()
    assert prev is not None
    assert prev.get("_queue_item_id") == last_played_before_wrap.get("_queue_item_id")
    assert prev["id"] == last_played_before_wrap["id"]


# ==============================================================================
# BUG-WIN-017: Repeat One & Manual Next
# ==============================================================================

def test_bug_win_017_repeat_one_manual_next_advances_queue():
    """With Repeat One enabled, next_track(force_advance=True) must advance

    to the next track, while next_track(force_advance=False) stays on current.
    """
    q = PlaybackQueue()
    tracks = _make_tracks(3)
    q.repeat = "one"
    q.set_tracks(tracks, 0)

    # Natural / unforced next stays on current track
    stolen = q.next_track(force_advance=False)
    assert stolen["id"] == tracks[0]["id"]
    assert q.current_index == 0

    # Forced next (manual click) advances to next track
    advanced = q.next_track(force_advance=True)
    assert advanced["id"] == tracks[1]["id"]
    assert q.current_index == 1

    # Another forced advance
    advanced2 = q.next_track(force_advance=True)
    assert advanced2["id"] == tracks[2]["id"]
    assert q.current_index == 2


def test_bug_win_017_api_next_track_defaults_to_force_advance(api, core_ns):
    """Calling api.next_track() explicitly must advance even when Repeat One is active."""
    engine = core_ns.engine
    tracks = _make_tracks(3)
    engine.queue.set_tracks(tracks, 0)
    engine.queue.repeat = "one"

    # Direct call to api.next_track() should advance
    nxt = api.next_track()
    assert nxt is not None
    assert nxt["id"] == tracks[1]["id"]


# ==============================================================================
# BUG-WIN-018: Duplicate Track Removal in Shuffle Mode
# ==============================================================================

def test_bug_win_018_duplicate_removal_in_shuffle_mode_preserves_remaining_copy():
    """Removing one duplicate from a shuffled queue must remove ONLY that specific

    instance from _original_order, preserving the other duplicate(s).
    """
    q = PlaybackQueue()
    # Create a playlist with duplicate track id=1 at positions 0 and 2
    tracks = [
        {"id": 1, "title": "Song A", "artist": "A", "source": "youtube", "source_id": "vid_1"},
        {"id": 2, "title": "Song B", "artist": "B", "source": "youtube", "source_id": "vid_2"},
        {"id": 1, "title": "Song A", "artist": "A", "source": "youtube", "source_id": "vid_1"},
        {"id": 3, "title": "Song C", "artist": "C", "source": "youtube", "source_id": "vid_3"},
    ]
    q.set_tracks(tracks, 0)
    assert q.count == 4

    # Turn on shuffle
    q.shuffle = True
    assert q.count == 4

    # Locate the first instance of Song A in the shuffled tracks
    idx_to_remove = next(i for i, t in enumerate(q.tracks) if t["id"] == 1)
    q.remove_track(idx_to_remove)
    assert q.count == 3

    # Turn off shuffle to restore original order
    q.shuffle = False
    restored_ids = [t["id"] for t in q.tracks]

    # The other instance of id=1 must still be present!
    assert restored_ids.count(1) == 1, f"Expected 1 instance of Song A, found {restored_ids}"
    assert restored_ids == [2, 1, 3] or restored_ids == [1, 2, 3]


# ==============================================================================
# BUG-WIN-019: Fast Skipping & Resolution Cancellation Token
# ==============================================================================

def test_bug_win_019_fast_skipping_cancels_in_flight_resolution_immediately():
    """Passing a cancel_token that returns True must cause resolve_stream_url

    and _resolve_via_network to exit immediately rather than blocking.
    """
    engine = AudioEngine()
    track = {
        "id": 99,
        "title": "Slow Network Track",
        "artist": "Slow Artist",
        "source": "youtube",
        "source_id": "slow_vid",
    }

    # Cancel token already signaled
    cancelled = lambda: True

    start = time.monotonic()
    result = engine.resolve_stream_url(track, cancel_token=cancelled)
    elapsed = time.monotonic() - start

    assert result is None
    # Must abort in under 200ms rather than waiting 10-20 seconds
    assert elapsed < 0.2, f"Resolution took too long to cancel: {elapsed}s"


def test_bug_win_019_cancel_token_aborts_during_wait():
    """A cancel token that trips during network wait aborts promptly."""
    engine = AudioEngine()
    track = {
        "id": 100,
        "title": "Fallback Track",
        "artist": "Artist",
        "source": "youtube",
        "source_id": "unknown_id",
    }

    # Simulate cancellation tripping after 50ms
    cancel_event = threading.Event()
    threading.Timer(0.05, cancel_event.set).start()
    cancel_token = lambda: cancel_event.is_set()

    start = time.monotonic()
    result = engine.resolve_stream_url(track, cancel_token=cancel_token)
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 1.0, f"Wait abort took {elapsed}s"


# ==============================================================================
# BUG-WIN-041: Local Track Resolution with file_path
# ==============================================================================

def test_bug_win_041_local_track_with_file_path_resolves_without_url():
    """A local track dict specifying 'file_path' (and no 'url') must resolve

    to that file_path, even if source is not explicitly 'local'.
    """
    engine = AudioEngine()

    # Case A: explicit source="local", file_path provided, no url
    track_a = {
        "id": 1,
        "title": "Local Song A",
        "artist": "Artist",
        "source": "local",
        "file_path": r"C:\Music\song_a.mp3",
    }
    resolved_a = engine.resolve_stream_url(track_a)
    assert resolved_a == r"C:\Music\song_a.mp3"

    # Case B: source omitted, file_path provided, no url
    track_b = {
        "id": 2,
        "title": "Local Song B",
        "artist": "Artist",
        "file_path": r"C:\Music\song_b.flac",
    }
    resolved_b = engine.resolve_stream_url(track_b)
    assert resolved_b == r"C:\Music\song_b.flac"


# ==============================================================================
# BUG-WIN-020, BUG-WIN-040, BUG-WIN-042: Frontend Player Logic (JS Tests)
# ==============================================================================

LIFECYCLE_GROUP5 = r"""
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
globalThis.lifecycle = {
    playTrack, onTrackChanged, handleStreamError, stopPlaybackForQueueEnd,
    applyVolumeNormalization,
    get active() {return activeAudio}, get track() {return playbackState.track},
    get status() {return playbackState.status},
    get retries() {return currentTrackRetries},
    get audios() {return [audioA, audioB]},
};`, context);
const player = context.lifecycle;
"""


def _run_player_script(script):
    harness = HARNESS.replace(
        "const frames = new Map(), documentEvents = new Map(), elements = new Map();",
        "const frames = new Map(), documentEvents = new Map(), elements = new Map(), windowEvents = new Map(), outputEvents = new Map();"
    ).replace(
        "window: {location: {href: 'http://localhost/'}, addEventListener() {}, dispatchEvent() {},",
        "window: {location: {href: 'http://localhost/'}, addEventListener(name, cb) {if (!windowEvents.has(name)) windowEvents.set(name, []); windowEvents.get(name).push(cb);}, dispatchEvent() {},",
    ).replace(
        "Audio: AudioStub, navigator: {},",
        "Audio: AudioStub, navigator: {mediaDevices: {addEventListener(name, callback) {outputEvents.set(name, callback)}}},",
    )
    run_node((harness + LIFECYCLE_GROUP5 + script).replace("SOURCE", source("player.js")))


def test_bug_win_040_not_allowed_error_pauses_without_recovery():
    """When play() rejects with NotAllowedError (browser autoplay block),

    the player must transition to 'paused' and NOT invoke recover_stream.
    """
    _run_player_script(r"""
let recoveryCalled = false;
context.window.pywebview.api.recover_stream = async () => {
    recoveryCalled = true;
    return {ok: true, stream_url: 'https://cdn.example/fresh.mp3'};
};
const track = {title: 'Track', artist: 'Artist', source: 'youtube', source_id: 't1', stream_url: 'https://cdn.example/t1.mp3'};

// Reject play() on both audio elements with NotAllowedError (autoplay block)
for (const audio of context.lifecycle.audios) {
    audio.play = function() {
        const err = new Error('play() failed because the user didn\'t interact with the document first.');
        err.name = 'NotAllowedError';
        return Promise.reject(err);
    };
}

context.lifecycle.playTrack(track, track.stream_url);

// Allow microtasks to settle
for (let i = 0; i < 5; i++) await Promise.resolve();

assert.equal(recoveryCalled, false, 'recover_stream should NOT be called on NotAllowedError');
assert.equal(context.lifecycle.status, 'paused', 'player status should be paused');
""")


def test_bug_win_042_volume_normalization_uses_safe_limiter_threshold():
    """applyVolumeNormalization(true) must configure a transparent peak limiter

    rather than an aggressive -14 dB threshold that distorts dynamic range.
    """
    _run_player_script(r"""
class CompressorMock {
    constructor() {
        this.threshold = {value: 0};
        this.knee = {value: 0};
        this.ratio = {value: 0};
        this.attack = {value: 0};
        this.release = {value: 0};
    }
}

class AudioContextMock {
    constructor() {
        this.state = 'running';
        this.destination = {};
    }
    createAnalyser() { return {fftSize: 256, smoothingTimeConstant: 0.8, connect() {}}; }
    createGain() { return {gain: {value: 1, setTargetAtTime() {}}, connect() {}}; }
    createBiquadFilter() { return {frequency: {value: 0}, gain: {value: 0}, Q: {value: 0}, connect() {}}; }
    createDynamicsCompressor() {
        const comp = new CompressorMock();
        comp.connect = () => {};
        return comp;
    }
    createMediaElementSource() { return {connect() {}, context: this}; }
    suspend() { return Promise.resolve(); }
    resume() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
}

context.window.AudioContext = AudioContextMock;

// Apply volume normalization
context.lifecycle.applyVolumeNormalization(true);

const comp = vm.runInContext('compressorNode', context);
assert.ok(comp, 'compressorNode must exist');
assert.ok(comp.threshold.value >= -3.0, 'Threshold must be a safe limiter value (>= -3dB), not -14dB: was ' + comp.threshold.value);
assert.ok(comp.ratio.value <= 4, 'Ratio must be gentle (<= 4), not aggressive 6: was ' + comp.ratio.value);
""")


def test_bug_win_020_pagehide_cleans_nodes_without_dangling_context():
    """pagehide event must clear node references and suspend context safely."""
    _run_player_script(r"""
class AudioContextMock {
    constructor() { this.state = 'running'; }
    createAnalyser() { return {connect() {}}; }
    createGain() { return {gain: {value: 1}, connect() {}}; }
    createBiquadFilter() { return {frequency: {value: 0}, gain: {value: 0}, Q: {value: 0}, connect() {}}; }
    createDynamicsCompressor() {
        return {threshold: {value: 0}, knee: {value: 0}, ratio: {value: 0}, attack: {value: 0}, release: {value: 0}, connect() {}};
    }
    createMediaElementSource() { return {connect() {}, disconnect() {}, context: this}; }
    suspend() { this.state = 'suspended'; return Promise.resolve(); }
    close() { this.state = 'closed'; return Promise.resolve(); }
}
context.window.AudioContext = AudioContextMock;

// Trigger initialization
context.lifecycle.applyVolumeNormalization(false);

// Dispatch pagehide
const pagehideHandlers = windowEvents.get('pagehide') || [];
for (const handler of pagehideHandlers) {
    handler();
}

// Ensure references are cleaned up so subsequent AudioContext creation does not reconnect dead nodes
assert.equal(vm.runInContext('srcA', context), null, 'srcA must be cleared on pagehide');
assert.equal(vm.runInContext('srcB', context), null, 'srcB must be cleared on pagehide');
assert.equal(vm.runInContext('mediaSourcesCreated', context), false, 'mediaSourcesCreated must be reset to false');
""")
