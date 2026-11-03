"""Audio-zone defect fixes: A1-006 cache collisions, A1-008 duration fork,
A1-009 stale resolutions, A1-017 queue snapshot, A1-003/012 spotify downloads,
A1-018 file validation, A1-019 auth retries, plus the player.js fixes
(A1-007/013/015, U3-013) via the Node harness. No network, no real downloads.
"""

import io
import os
import threading
from types import SimpleNamespace

import pytest

from tests.helpers import (
    PROXY_TOKEN, app_core, nedotify_home, proxy_factory, proxy  # noqa: F401
)

from core.downloader import DownloadManager, _downloaded_file_defect
from utils.cache_manager import (
    is_hashed_cache_stem,
    is_valid_cache_file,
    stream_cache_stem,
)


# --------------------------------------------------------------------------- #
# BUG-A1-006 — hashed cache names
# --------------------------------------------------------------------------- #

TRACK_A = "ytsearch1: Сплин - Выхода нет"
# Equal-length, equal-shape query: under the legacy sanitisation rule every
# Cyrillic char becomes '_', so both collapse onto the SAME cache-file name.
TRACK_B = "ytsearch1: Мумий - Полюса нет"


def test_legacy_names_collide_but_hashed_stems_do_not():
    """The two equal-length Russian queries shared one legacy file name; the
    digest scheme gives every (source, source_id) pair its own name."""
    import re as _re
    legacy = lambda sid: "spotify_" + _re.sub(r"[^a-zA-Z0-9_-]", "_", sid)
    assert legacy(TRACK_A) == legacy(TRACK_B), "the old bug is real"

    stem_a, stem_b = stream_cache_stem("spotify", TRACK_A), stream_cache_stem("spotify", TRACK_B)
    assert stem_a != stem_b
    assert is_hashed_cache_stem(stem_a) and is_hashed_cache_stem(stem_b)
    assert is_valid_cache_file(os.path.join("x", stem_a + ".m4a"))
    assert not is_valid_cache_file(legacy(TRACK_A) + ".m4a"), "legacy names are never valid"


def test_proxy_disk_probe_never_serves_a_colliding_track(proxy, app_core, nedotify_home):
    """Track A is cached; playing colliding track B must not receive A's audio,
    and a legacy-format file is never served to anyone."""
    streams_dir = app_core.cache._streams_dir
    legacy_name = "spotify_" + "ytsearch1" + "_" * 16  # shaped like the old name
    with open(os.path.join(streams_dir, legacy_name + ".m4a"), "wb") as f:
        f.write(b"LEGACY" * 300)
    with open(os.path.join(streams_dir, stream_cache_stem("spotify", TRACK_A) + ".m4a"), "wb") as f:
        f.write(b"AUDIO_A" * 300)

    served_a = proxy.get(proxy.url("/api/stream", source="spotify", source_id=TRACK_A))
    assert served_a.status == 200
    assert served_a.body == b"AUDIO_A" * 300

    served_b = proxy.get(proxy.url("/api/stream", source="spotify", source_id=TRACK_B))
    assert served_b.status != 200, "colliding track B must not receive A's cached audio"

    served_legacy = proxy.get(proxy.url("/api/stream", source="spotify", source_id="ytsearch1: Другое - Имя"))
    assert served_legacy.status != 200, "a legacy-format file is never served"


def test_cache_manager_writes_hashed_names(tmp_path, monkeypatch):
    """download_audio_stream persists under the hashed stem and registers it
    in stream_cache for the exact (source, source_id)."""
    from utils.cache_manager import CacheManager
    from tests.helpers import DeferredExecutor
    from services.base_service import BaseMusicService
    from tests.audio_helpers import wave_bytes
    import logging

    cache = CacheManager.__new__(CacheManager)
    cache._streams_dir = str(tmp_path)
    cache._temp_dir = str(tmp_path / "temp")
    tmp_path.joinpath("temp").mkdir()
    cache._active_downloads = set()
    cache._active_downloads_lock = threading.Lock()
    cache._executor = DeferredExecutor()
    cache.purge_stream_cache = lambda: None
    cache.mark_cache_dirty = lambda: None
    cache.logger = logging.getLogger("test-cache")
    saved = []
    cache.db = SimpleNamespace(set_cached_file=lambda *args: saved.append(args),
                               get_cached_stream=lambda *a, **k: None)

    class Response:
        headers = {"Content-Type": "audio/wav", "Content-Length": str(len(wave_bytes()))}
        def __init__(self):
            self.payload = wave_bytes()
        def read(self, count=-1):
            result, self.payload = self.payload[:count], self.payload[count:]
            return result
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("utils.url_safety.guarded_open_url", lambda *_a, **_k: Response())
    cache.download_audio_stream("spotify", TRACK_A, "https://media.example/audio")
    for task in cache._executor.tasks:
        task()

    final_path = saved[0][2]
    assert os.path.basename(final_path).startswith(stream_cache_stem("spotify", TRACK_A))
    assert os.path.isfile(final_path)


def test_purge_keeps_legacy_files_of_protected_tracks(tmp_path, tmp_db):
    """LRU purge protects both naming generations for downloaded/favourite
    tracks (no user files are deleted), while legacy files of unprotected
    tracks stay purgeable."""
    from utils.cache_manager import CacheManager
    import re as _re

    tmp_db.add_track(title="Protected", artist="A", source="spotify",
                     source_id=TRACK_A, is_favorite=1)
    cache = CacheManager(tmp_db)
    # The legacy name of the protected track, exactly as the old scheme built it.
    legacy_protected = os.path.join(
        cache.streams_dir, "spotify_" + _re.sub(r"[^a-zA-Z0-9_-]", "_", TRACK_A) + ".m4a")
    legacy_unprotected = os.path.join(cache.streams_dir, "spotify_other_legacy.m4a")
    hashed_protected = os.path.join(
        cache.streams_dir, stream_cache_stem("spotify", TRACK_A) + ".m4a")
    for path in (legacy_protected, legacy_unprotected, hashed_protected):
        with open(path, "wb") as f:
            f.write(b"x" * 1024)
    # Give the unprotected file the older mtime so LRU picks it first.
    os.utime(legacy_unprotected, (1, 1))

    cache.purge_stream_cache(quota_bytes=1, force_all_temporary=False)
    # force_all_temporary=False with a tiny quota evicts down to 75% -> every
    # candidate would go unless protected; the protected ones must survive.
    assert os.path.isfile(legacy_protected), "a favourite track's legacy file is protected"
    assert os.path.isfile(hashed_protected), "a favourite track's hashed file is protected"
    assert not os.path.isfile(legacy_unprotected), "unprotected legacy files stay purgeable"


def test_download_task_ignores_a_legacy_stream_cache_row(tmp_path, tmp_db, monkeypatch):
    """A stream_cache row still pointing at a legacy-format file must not make
    the background cache reuse it: the real task downloads a fresh copy under
    the hashed stem and re-registers that path."""
    from utils.cache_manager import CacheManager
    from tests.helpers import DeferredExecutor
    from tests.audio_helpers import wave_bytes

    legacy_path = str(tmp_path / "legacy.mp3")
    with open(legacy_path, "wb") as f:
        f.write(b"stale" * 100)
    tmp_db.set_cached_file("spotify", TRACK_A, legacy_path)

    cache = CacheManager(tmp_db)
    cache._streams_dir = str(tmp_path / "streams")
    cache._temp_dir = str(tmp_path / "temp")
    for d in (cache._streams_dir, cache._temp_dir):
        os.makedirs(d, exist_ok=True)
    cache._active_downloads = set()
    cache._active_downloads_lock = threading.Lock()
    cache._executor = DeferredExecutor()
    cache.purge_stream_cache = lambda: None
    cache.mark_cache_dirty = lambda: None

    class Response:
        headers = {"Content-Type": "audio/wav", "Content-Length": str(len(wave_bytes()))}
        def __init__(self):
            self.payload = wave_bytes()
        def read(self, count=-1):
            result, self.payload = self.payload[:count], self.payload[count:]
            return result
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("utils.url_safety.guarded_open_url", lambda *_a, **_k: Response())
    cache.download_audio_stream("spotify", TRACK_A, "https://media.example/audio")
    for task in cache._executor.tasks:
        task()

    row = tmp_db.get_cached_stream("spotify", TRACK_A) or {}
    final_path = row.get("cached_file_path")
    assert final_path, "the stale legacy row did not abort the fresh download"
    assert os.path.basename(final_path).startswith(stream_cache_stem("spotify", TRACK_A)), \
        "the fresh copy is stored under the hashed stem"
    assert os.path.isfile(final_path)
    assert os.path.normpath(final_path) != os.path.normpath(legacy_path), \
        "the legacy-format row must never be served or reused"
    # Legacy files belong to the LRU purge, not to the download task.
    assert os.path.isfile(legacy_path)


# --------------------------------------------------------------------------- #
# BUG-A1-008 — two-sided duration fork
# --------------------------------------------------------------------------- #

def _wave_file(tmp_path, frames):
    import wave
    path = str(tmp_path / "clip.wav")
    with wave.open(path, "wb") as audio:
        audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00" * (frames * 2))
    return path


def test_truncated_download_is_still_rejected(tmp_path):
    path = _wave_file(tmp_path, 22050)  # ~1s
    assert "обрезан" in _downloaded_file_defect(path, 240)


def test_much_longer_download_is_rejected_as_wrong_record(tmp_path):
    path = _wave_file(tmp_path, 22050 * 400)  # ~400s vs expected 240s
    defect = _downloaded_file_defect(path, 240)
    assert defect and "не та запись" in defect


def test_slightly_longer_download_is_accepted(tmp_path):
    path = _wave_file(tmp_path, 22050 * 248)  # ~248s vs expected 240s (+3%)
    assert _downloaded_file_defect(path, 240) == ""


# --------------------------------------------------------------------------- #
# BUG-A1-019 — auth failures are not transient
# --------------------------------------------------------------------------- #

def test_unauthorized_and_forbidden_are_not_retryable():
    dm = DownloadManager.__new__(DownloadManager)
    dm._RETRYABLE_MARKS = DownloadManager._RETRYABLE_MARKS
    assert not dm._is_retryable_error(Exception("HTTP Error 403: Forbidden"))
    assert not dm._is_retryable_error(Exception("unauthorized client"))
    assert dm._is_retryable_error(Exception("HTTP Error 503: overloaded")), \
        "genuinely transient marks stay retryable"


# --------------------------------------------------------------------------- #
# BUG-A1-003 / BUG-A1-012 — spotify download resolution
# --------------------------------------------------------------------------- #

class _StubYoutube:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search_sync(self, query, limit=20, result_type=None, timeout=6.0):
        self.calls.append((query, limit))
        return self._results[:limit]

    def download_audio_sync(self, source_id, output_dir, download_context=None):
        return os.path.join(output_dir, f"got_{source_id}.mp3")


def _downloader_with_track(tmp_db, tmp_path, monkeypatch, title, artist, duration):
    dm = DownloadManager.__new__(DownloadManager)
    dm._core = SimpleNamespace(db=tmp_db, settings=None,
                               youtube=_StubYoutube([]))
    track_id = tmp_db.add_track(title=title, artist=artist, source="spotify",
                                source_id="spotify_1", duration=duration)
    dm._worker_context = threading.local()
    return dm, track_id


def test_spotify_download_picks_the_verified_candidate(tmp_db, tmp_path, monkeypatch):
    """search_sync gets 5 slots and select_recording picks the matching entry,
    not the remix that happens to rank first (BUG-A1-003)."""
    results = [
        {"source_id": "remixvid1", "title": "Выхода нет (Club Mix)", "artist": "Сплин", "duration": 305},
        {"source_id": "original01", "title": "Выхода нет", "artist": "Сплин", "duration": 240},
    ]
    yt = _StubYoutube(results)
    dm = DownloadManager.__new__(DownloadManager)
    dm._core = SimpleNamespace(db=tmp_db, settings=None, youtube=yt)
    track_id = tmp_db.add_track(title="Выхода нет", artist="Сплин", source="spotify",
                                source_id="spotify_1", duration=240)
    dm._worker_context = threading.local()

    out_dir = str(tmp_path / "downloads")
    got = dm._download_spotify_track("spotify_1", track_id, out_dir)
    assert got == os.path.join(out_dir, "got_original01.mp3")
    assert yt.calls and yt.calls[0][1] == 5


def test_spotify_download_never_takes_a_soundcloud_substitute(tmp_db, tmp_path, monkeypatch):
    """BUG-A1-012: the TrackResolver stage is restricted to YouTube; a
    soundcloud-only provider must never be consulted or downloaded."""
    consulted = []
    class _ScService:
        def search(self, *a, **k):
            consulted.append("soundcloud")
            raise AssertionError("soundcloud must not be used for spotify downloads")

    class _YtResolverStub:
        def search(self, query, max_results=20, callback=None, error_callback=None):
            callback([])

    dm = DownloadManager.__new__(DownloadManager)
    dm._core = SimpleNamespace(db=tmp_db, settings=None, youtube=_StubYoutube([]),
                               soundcloud=_ScService())
    track_id = tmp_db.add_track(title="Выхода нет", artist="Сплин", source="spotify",
                                source_id="spotify_1", duration=240)
    dm._worker_context = threading.local()

    from services.track_resolver import TrackResolver
    real_init = TrackResolver.__init__
    def spy_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        consulted.append(("providers", self.providers))
    monkeypatch.setattr(TrackResolver, "__init__", spy_init)

    with pytest.raises(Exception):
        dm._download_spotify_track("spotify_1", track_id, str(tmp_path))
    assert ("providers", ("youtube",)) in consulted
    assert "soundcloud" not in consulted


# --------------------------------------------------------------------------- #
# BUG-A1-009 — stale resolution tasks are dropped
# --------------------------------------------------------------------------- #

def test_resolve_track_drops_a_superseded_task(api, core_ns):
    engine = core_ns.engine
    track = {"id": 3, "title": "T", "source": "local", "source_id": "s",
             "file_path": "missing.mp3"}
    engine.queue.set_tracks([track], 0)
    future = api._resolve_track(track, lambda t: None)
    # Simulate the user moving on before the worker started.
    api._playback_epoch += 1
    future.result(timeout=2)
    assert track.get("resolution_status") != "failed"
    # A non-local superseded track must not even attempt the cascade.
    other = {"id": 4, "title": "T2", "source": "youtube", "source_id": "abc12345678"}
    engine.queue.set_tracks([other], 0)
    future2 = api._resolve_track(other, lambda t: None)
    api._playback_epoch += 1
    future2.result(timeout=2)
    assert "resolution_status" not in other or other["resolution_status"] != "ready"


def test_play_track_cancels_queued_resolution_futures(api, core_ns, monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    cancellation_checks = []

    def busy_resolve(track, cancel_token=None):
        # Engine.resolve_stream_url delegates here when no single-flight
        # resolver is installed (the shape core_ns uses).
        cancellation_checks.append(cancel_token)
        started.set()
        release.wait(2)
        return None

    monkeypatch.setattr(core_ns.engine, "_resolve_via_network", busy_resolve)
    track = {"id": 5, "title": "T", "source": "youtube", "source_id": "abcdefghijk"}
    core_ns.engine.queue.set_tracks([track], 0)
    future = api._resolve_track(track, lambda t: None)
    assert started.wait(2)
    assert callable(cancellation_checks[0])
    assert cancellation_checks[0]() is False
    # The next play bumps the epoch and cancels queued work; the RUNNING task
    # finishes on its own (cancel() only reaches not-yet-started futures).
    from tests.audio_helpers import wave_bytes
    local_audio = tmp_path / "next.wav"
    local_audio.write_bytes(wave_bytes())
    result = api.play_track({"id": 6, "title": "N", "source": "local", "file_path": str(local_audio)})
    assert result['success'] is True
    assert cancellation_checks[0]() is True
    release.set()
    future.result(timeout=2)
    assert not api._resolution_futures or all(f.done() for f in list(api._resolution_futures))


# --------------------------------------------------------------------------- #
# BUG-A1-017 — get_next_track reads a consistent snapshot
# --------------------------------------------------------------------------- #

def test_get_next_track_uses_the_queue_snapshot(api, core_ns):
    engine = core_ns.engine
    first = {"id": 1, "title": "One", "source": "youtube", "source_id": "aaaaaaaaaaa"}
    second = {"id": 2, "title": "Two", "source": "youtube", "source_id": "bbbbbbbbbbb"}
    engine.queue.set_tracks([first, second], 0)

    seen = {}
    original_snapshot = engine.queue.snapshot
    def racing_snapshot():
        state = original_snapshot()
        seen["read_index"] = state["current_index"]
        return state
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(engine.queue, "snapshot", racing_snapshot)
        nxt = api.get_next_track()
    finally:
        monkey.undo()
    assert nxt["title"] == "Two"
    assert seen["read_index"] == 0


# --------------------------------------------------------------------------- #
# BUG-A1-018 — every file-return path in download_audio_sync validates
# --------------------------------------------------------------------------- #

def test_youtube_download_steps_validate_the_file(tmp_path, monkeypatch):
    """A 0-byte file that matches the expected name must not be returned."""
    import services.youtube_service as ytsvc
    service = ytsvc.YouTubeService.__new__(ytsvc.YouTubeService)
    service.settings = None
    service.logger = ytsvc.logger

    class _Ydl:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def extract_info(self, url, download):
            return {"id": "dQw4w9WgXcQ", "ext": "m4a", "title": "T"}
        def prepare_filename(self, info):
            path = str(tmp_path / "yt_dQw4w9WgXcQ_1.m4a")
            open(path, "wb").close()  # 0 bytes
            return path

    monkeypatch.setattr(ytsvc, "_has_ytdlp", lambda: True)
    monkeypatch.setattr(ytsvc, "_ytdlp", lambda: SimpleNamespace(YoutubeDL=_Ydl))
    service._get_ydl_opts = lambda *a, **k: {}

    with pytest.raises(Exception):
        service.download_audio_sync("dQw4w9WgXcQ", str(tmp_path))


# --------------------------------------------------------------------------- #
# player.js fixes (A1-007, A1-013, A1-015, U3-013) — Node harness
# --------------------------------------------------------------------------- #

def test_player_toggle_play_rejects_a_stale_src():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
const src = SOURCE;
// BUG-A1-007: togglePlayPause must compare the loaded source with the
// current track's URL instead of trusting any non-empty src.
assert.ok(src.includes('_loadedSourceUrl === currentTrackSrc'),
    'togglePlayPause must verify the loaded source belongs to the current track');
// The resolving branch must release the previous track's audio element.
const resolving = src.slice(src.indexOf("Resolution belongs to the backend"),
                            src.indexOf("} else {", src.indexOf("Resolution belongs to the backend")));
assert.ok(resolving.includes('releaseAudio(activeAudio)'),
    'the resolving branch must release the active audio');
""".replace('SOURCE', source('player.js')))


def test_player_does_not_claim_playing_before_audio_starts():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
const src = SOURCE;
const playTrack = src.slice(src.indexOf('function playTrack('),
                            src.indexOf('export function seekTo('));
assert.ok(playTrack.includes("onStateChanged('loading')"),
    'playTrack must report loading while buffering');
assert.ok(!/onStateChanged\('playing'\)/.test(playTrack),
    "BUG-A1-013: playTrack must not claim 'playing' before the element's playing event");
""".replace('SOURCE', source('player.js')))


def test_player_hls_detection_without_playlist_substring():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
const src = SOURCE;
const loader = src.slice(src.indexOf('function loadAudioSource('),
                         src.indexOf('// Prefetch state for the finite playback queue'));
assert.ok(!loader.includes("includes('/playlist')"),
    "BUG-A1-015: the '/playlist' substring must not route plain CDN URLs into hls.js");
assert.ok(loader.includes('mediaType'), 'the explicit stream_type marker stays in control');
""".replace('SOURCE', source('player.js')))


def test_player_set_el_src_clears_the_previous_cover():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const context = vm.createContext({
    document: {
        getElementById(id) {
            return this[id] || null;
        },
    },
});
const src = SOURCE;
vm.runInContext(src.slice(src.indexOf('function setElSrc('),
                          src.indexOf('// --- Waveform Scrubber Engine ---')), context);
const ops = [];
const el = {
    style: {},
    attrs: {},
    getAttribute(name) { return this.attrs[name] || null; },
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; ops.push('clear:' + name); },
    get src() { return this.attrs.src || ''; },
    set src(v) { this.attrs.src = v; ops.push('src:' + v); },
};
context.document.cover = el;
// A caller-registered onload (colour extraction) must survive the swap.
let extracted = false;
el.onload = () => { extracted = true; };
vm.runInContext("setElSrc('cover', 'http://x/old.jpg')", context);
ops.length = 0;
vm.runInContext("setElSrc('cover', 'http://x/new.jpg')", context);
// BUG-U3-013: the old image is dropped BEFORE the new URL is assigned, and
// the element stays hidden until the new image actually loads.
const clearAt = ops.indexOf('clear:src');
const newAt = ops.indexOf('src:http://x/new.jpg');
assert.ok(clearAt !== -1, 'the previous cover is dropped during the swap');
assert.ok(newAt !== -1, 'the new URL is still assigned');
assert.ok(clearAt < newAt, 'the old image is cleared BEFORE the new one starts loading');
assert.equal(el.style.opacity, '0', 'the stale artwork is hidden while loading');
el.onload();
assert.ok(extracted, 'the caller onload hook still runs after the new image loads');
assert.equal(el.style.opacity, '', 'the new cover becomes visible');
assert.equal(el.getAttribute('src'), 'http://x/new.jpg');
""".replace('SOURCE', source('player.js')))
