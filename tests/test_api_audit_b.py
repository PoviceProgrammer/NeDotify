"""Regression tests for the core/api.py + audio/ audit (zone B).

Every test here fails on the pre-fix code; the "why it fails" note lives in the
test name or its docstring. Only the fixtures from tests/conftest.py are used.
"""

import os
import socket
import types

import pytest

import core.api as api_mod
from audio.engine import AudioEngine
from audio.queue import PlaybackQueue
from core.api import (
    AppApi,
    _is_ssrf_safe_url,
    _normalize_cache_quota,
    _reset_ssrf_cache,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

class CacheStub:
    """Records the cache-manager calls the bridge makes."""

    def __init__(self):
        self.clear_all_calls = 0
        self.purges = []
        self.streams_dir = None

    def clear_all(self):
        self.clear_all_calls += 1

    def purge_stream_cache(self, quota_bytes=None, force_all_temporary=False):
        self.purges.append(quota_bytes)
        return 0

    def get_storage_details(self):
        return {"used_bytes": 0, "quota_bytes": 0, "quota_gb": 0, "protected_count": 0}


def _api_with_engine(core_ns):
    """AppApi bound to a fresh AudioEngine, headless (no UI callbacks)."""
    engine = AudioEngine()
    core_ns.engine = engine
    app = AppApi(core_ns)
    engine._on_track_changed = None
    return app, engine


def _tracks(n):
    return [
        {"id": i, "title": "t%d" % i, "artist": "a", "source": "youtube", "source_id": "v%d" % i}
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _isolated_ssrf_cache():
    """The SSRF DNS cache is module-global; never let it leak between tests."""
    _reset_ssrf_cache()
    yield
    _reset_ssrf_cache()


# --------------------------------------------------------------------------- #
# P0-5  toggle_mute must persist and report the real state
# --------------------------------------------------------------------------- #

def test_toggle_mute_persists_and_returns_new_state(api, settings_stub, emitted):
    """Old code hardcoded `return False`, so the second toggle could never be
    observed and settings never moved off DEFAULT_SETTINGS' audio.muted=False."""
    assert settings_stub.get("audio", "muted", "unset") == "unset"

    assert api.toggle_mute() is True
    assert settings_stub.get("audio", "muted") is True
    assert api.is_muted() is True

    assert api.toggle_mute() is False
    assert settings_stub.get("audio", "muted") is False
    assert api.is_muted() is False

    assert [name for name, _ in emitted].count("mute_changed") == 2


def test_toggle_mute_reads_preexisting_muted_flag(api, settings_stub):
    """A mute flag already stored in settings must be honoured, not reset."""
    settings_stub.set("audio", "muted", True)
    assert api.toggle_mute() is False
    assert settings_stub.get("audio", "muted") is False


# --------------------------------------------------------------------------- #
# P0-6  get_next_track must not wrap the queue
# --------------------------------------------------------------------------- #

def test_get_next_track_mid_queue_returns_next(core_ns):
    app, engine = _api_with_engine(core_ns)
    engine.queue.set_tracks(_tracks(3), 0)
    nxt = app.get_next_track()
    assert nxt is not None and nxt["id"] == 1


def test_get_next_track_none_at_queue_end_without_repeat(core_ns):
    """Old code did (idx + 1) % len, so preloading on the last track returned
    track 0 and the UI cached the wrong stream."""
    app, engine = _api_with_engine(core_ns)
    engine.queue.repeat = "off"
    engine.queue.set_tracks(_tracks(3), 2)
    assert engine.queue.next_track() is None  # queue semantics: end of queue
    assert app.get_next_track() is None


def test_get_next_track_wraps_when_repeat_all(core_ns):
    app, engine = _api_with_engine(core_ns)
    engine.queue.repeat = "all"
    engine.queue.set_tracks(_tracks(3), 2)
    nxt = app.get_next_track()
    assert nxt is not None and nxt["id"] == 0


def test_get_next_track_single_track_queue_is_not_the_same_track(core_ns):
    """len(tracks) == 1 used to make next_idx permanently 0 (self-preload)."""
    app, engine = _api_with_engine(core_ns)
    engine.queue.repeat = "off"
    engine.queue.set_tracks(_tracks(1), 0)
    assert app.get_next_track() is None


def test_get_next_track_empty_queue_returns_none(core_ns):
    app, engine = _api_with_engine(core_ns)
    engine.queue.set_tracks([], 0)
    assert engine.queue.current_index == -1
    assert app.get_next_track() is None


def test_get_next_track_ignores_negative_current_index(core_ns):
    """current_index == -1 with a non-empty queue must not raise or mis-index."""
    app, engine = _api_with_engine(core_ns)
    engine.queue.set_tracks(_tracks(2), -1)
    assert engine.queue.current_index == -1
    assert app.get_next_track() is None


# --------------------------------------------------------------------------- #
# P1-4  batch_download_started must precede any progress event
# --------------------------------------------------------------------------- #

def test_batch_download_started_precedes_progress(api, core_ns, emitted, monkeypatch, redirect_home):
    """Old order was: queue everything (progress events fly) THEN emit started,
    so a UI initializing its counter from `started` had it wiped again."""
    core_ns.downloader = types.SimpleNamespace(start_batch=lambda n: None)

    for i in range(3):
        tid = core_ns.db.add_track(title="T%d" % i, artist="A", source="youtube", source_id="vid%d" % i)
        core_ns.db.toggle_favorite(int(tid))

    def fake_download_track(track):
        api._emit("batch_download_progress", {"track_id": track.get("id")})
        return True

    monkeypatch.setattr(api, "download_track", fake_download_track)

    res = api.download_all_favorites()
    assert res["success"] is True
    assert res["count"] == 3

    names = [name for name, _ in emitted]
    assert "batch_download_started" in names
    assert names.index("batch_download_started") < names.index("batch_download_progress")
    assert names.index("batch_download_started") == 0

    started = dict(emitted)["batch_download_started"]
    assert started == {"total": 3, "current": 0}


# --------------------------------------------------------------------------- #
# P1-5  cached cover must keep its real extension
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("ext", [".png", ".webp", ".jpg"])
def test_update_track_tags_keeps_cover_extension(api, core_ns, tmp_path, redirect_home, emitted, ext):
    """Old code always wrote f"{track_id}.jpg"; the proxy serves /api/cover with
    mimetypes.guess_type(<path>) so PNG/WebP bytes were published as image/jpeg."""
    tid = int(core_ns.db.add_track(title="T", artist="A", source="local", source_id="s1"))
    src = tmp_path / ("cover" + ext)
    src.write_bytes(b"\x89PNG\r\n\x1a\n-binary-cover-payload")

    res = api.update_track_tags(tid, {"cover_path": str(src)})
    assert res["success"] is True, res

    cover_path = res["track"]["cover_path"]
    assert cover_path.endswith(ext), cover_path
    assert os.path.isfile(cover_path)
    with open(cover_path, "rb") as fh:
        assert fh.read() == src.read_bytes()

    # The DB row must carry the very same path that was written.
    assert core_ns.db.get_track(tid)["cover_path"] == cover_path
    assert os.path.basename(cover_path).startswith(str(tid))


def test_update_track_tags_cover_extension_is_proxy_servable(api, core_ns, tmp_path, redirect_home, emitted):
    """Whatever extension we write must be servable by /api/cover with the
    right Content-Type: core/proxy.py serve_local_file() publishes the file
    with mimetypes.guess_type(<path>), so the name has to carry the real format.
    """
    import mimetypes

    from core.proxy import COVER_EXTENSIONS

    tid = int(core_ns.db.add_track(title="T", artist="A", source="local", source_id="s2"))
    src = tmp_path / "cover.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    res = api.update_track_tags(tid, {"cover_path": str(src)})
    cover_path = res["track"]["cover_path"]

    ext = os.path.splitext(cover_path)[1].lower()
    assert ext in COVER_EXTENSIONS
    assert mimetypes.guess_type(cover_path)[0] == "image/png"
    # The old "<id>.jpg" name made the proxy announce image/jpeg for PNG bytes.
    assert mimetypes.guess_type(cover_path)[0] != "image/jpeg"


# --------------------------------------------------------------------------- #
# P1-6  SSRF DNS verdicts must be cached (thread-safe, bounded, per host)
# --------------------------------------------------------------------------- #

def _fake_resolver(mapping, calls):
    def _getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        ip = mapping[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    return _getaddrinfo


def test_ssrf_check_caches_dns_verdict(monkeypatch):
    """Old code called blocking socket.getaddrinfo() on EVERY call; under the
    main.py DoH fallback a dead host costs up to 3 x 2s per call."""
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_resolver({"example.com": "93.184.216.34"}, calls))

    assert _is_ssrf_safe_url("https://example.com/a") is True
    assert _is_ssrf_safe_url("https://example.com/b") is True
    assert _is_ssrf_safe_url("https://example.com/c?x=1") is True
    assert calls == ["example.com"]


def test_ssrf_cache_does_not_mix_different_hosts(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(
        {"good.test": "93.184.216.34", "evil.test": "127.0.0.1"}, calls))

    assert _is_ssrf_safe_url("https://good.test/x") is True
    assert _is_ssrf_safe_url("https://evil.test/x") is False
    # Cache hits must still return each host's OWN verdict, in any order.
    assert _is_ssrf_safe_url("https://good.test/y") is True
    assert _is_ssrf_safe_url("https://evil.test/y") is False
    assert sorted(calls) == ["evil.test", "good.test"]


def test_ssrf_cache_entry_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_resolver({"example.com": "93.184.216.34"}, calls))
    monkeypatch.setattr(api_mod, "_SSRF_CACHE_TTL", 0.0)  # already stale

    assert _is_ssrf_safe_url("https://example.com/a") is True
    assert _is_ssrf_safe_url("https://example.com/b") is True
    assert calls == ["example.com", "example.com"]


def test_ssrf_cache_is_bounded(monkeypatch):
    """A proxy sees arbitrary hosts; the cache must not grow without limit."""
    monkeypatch.setattr(api_mod, "_SSRF_CACHE_MAX", 4)
    calls = []
    hosts = {f"h{i}.test": "93.184.216.34" for i in range(40)}
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(hosts, calls))

    for i in range(40):
        assert _is_ssrf_safe_url(f"https://h{i}.test/") is True
    assert len(calls) == 40
    assert len(api_mod._ssrf_cache) == 4, "cache must stay capped at _SSRF_CACHE_MAX"


def test_ssrf_cache_is_shared_across_threads(monkeypatch):
    """Proxy threads hit this concurrently; the verdict must stay consistent and
    the lock must collapse them onto a single resolution."""
    import threading

    calls = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_resolver({"race.test": "93.184.216.34"}, calls))
    results = []
    lock = threading.Lock()

    def _worker():
        ok = _is_ssrf_safe_url("https://race.test/x") is True
        with lock:
            results.append(ok)

    # Warm the cache first so the assertion below is deterministic: the cache is
    # a memo, not a single-flight resolver, so a genuinely cold concurrent start
    # may resolve more than once by design.
    assert _is_ssrf_safe_url("https://race.test/warmup") is True
    assert len(calls) == 1

    threads = [threading.Thread(target=_worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 16
    assert len(calls) == 1, "a warm cache entry must serve every concurrent caller"


def test_ssrf_literal_private_ip_still_blocked_without_dns():
    """Cheap pre-DNS rejections must keep short-circuiting (no cache needed)."""
    assert _is_ssrf_safe_url("http://127.0.0.1/x") is False
    assert _is_ssrf_safe_url("http://localhost/x") is False
    assert _is_ssrf_safe_url("http://2130706433/x") is False
    assert _is_ssrf_safe_url("ftp://example.com/x") is False
    assert api_mod._ssrf_cache == {}


def test_proxy_import_of_ssrf_helper_still_works():
    """core/proxy.py does `from core.api import _is_ssrf_safe_url`."""
    from core.proxy import _is_safe_url
    assert _is_safe_url is _is_ssrf_safe_url


# --------------------------------------------------------------------------- #
# P1-7  source == "local" must verify the file really exists
# --------------------------------------------------------------------------- #

def test_play_track_local_missing_file_reports_error(api, core_ns, emitted, tmp_path):
    """Old `source == "local" or _fp_usable(fp)` was always true for local, so a
    deleted file started silent playback instead of an error."""
    engine = AudioEngine()
    core_ns.engine = engine
    missing = tmp_path / "gone.mp3"
    track = {"id": 1, "title": "Vanished", "artist": "A", "source": "local",
             "source_id": "s1", "file_path": str(missing)}

    api.play_track(track, [track], 0)

    names = [name for name, _ in emitted]
    assert "audio_error" in names
    msg = emitted[names.index("audio_error")][1]["message"]
    assert "аудиофайл не найден" in msg
    assert "Vanished" in msg
    assert engine.queue.count == 0  # never entered the queue


def test_play_track_local_without_any_path_reports_error(api, core_ns, emitted):
    engine = AudioEngine()
    core_ns.engine = engine
    track = {"id": 2, "title": "NoPath", "source": "local", "source_id": "s2"}

    api.play_track(track, [track], 0)

    assert "audio_error" in [name for name, _ in emitted]
    assert engine.queue.count == 0


def test_play_track_local_existing_file_still_plays(api, core_ns, emitted, tmp_path):
    engine = AudioEngine()
    core_ns.engine = engine
    good = tmp_path / "here.mp3"
    good.write_bytes(b"\x00" * 4096)
    track = {"id": 3, "title": "Here", "source": "local", "source_id": "s3",
             "file_path": str(good)}

    api.play_track(track, [track], 0)

    assert "audio_error" not in [name for name, _ in emitted]
    assert engine.queue.count == 1
    assert engine.queue.current_track["id"] == 3


def test_play_track_online_source_still_resolves(api, core_ns, emitted, monkeypatch):
    """Online sources must be unaffected: they still enter the resolve cascade."""
    engine = AudioEngine()
    core_ns.engine = engine
    requested = []

    def fake_async(source, source_id, callback=None, on_error=None, track=None):
        requested.append((source, source_id))
        callback("https://cdn.test/stream.m4a")
        return None

    core_ns.re_resolve_stream_url_async = fake_async
    track = {"id": 4, "title": "Online", "source": "youtube", "source_id": "yt123"}

    api.play_track(track, [track], 0)

    assert requested == [("youtube", "yt123")]
    assert engine.queue.count == 1
    assert "audio_error" not in [name for name, _ in emitted]


def test_resolve_track_local_missing_file_reports_error(api, core_ns, emitted, tmp_path):
    """Same tautology lived in _resolve_track."""
    engine = AudioEngine()
    core_ns.engine = engine
    delivered = []
    track = {"id": 5, "title": "AlsoGone", "source": "local", "source_id": "s5",
             "file_path": str(tmp_path / "nope.mp3")}

    api._resolve_track(track, lambda t: delivered.append(t))

    assert delivered == []
    assert "audio_error" in [name for name, _ in emitted]


def test_resolve_track_local_recovered_from_streams_dir(api, core_ns, emitted, tmp_path):
    """The "file is missing" guard must come AFTER the cache-recovery chain:
    a local track still playable from the stream cache is not an error."""
    engine = AudioEngine()
    core_ns.engine = engine
    cache_dir = tmp_path / "streams"
    cache_dir.mkdir()
    cached = cache_dir / "local_s9.m4a"
    cached.write_bytes(b"\x00" * 4096)
    core_ns.cache = types.SimpleNamespace(_streams_dir=str(cache_dir))

    delivered = []
    track = {"id": 9, "title": "Cached", "source": "local", "source_id": "s9",
             "file_path": str(tmp_path / "gone.mp3")}

    api._resolve_track(track, lambda t: delivered.append(t))

    assert len(delivered) == 1
    assert delivered[0]["file_path"] == str(cached)
    assert "audio_error" not in [name for name, _ in emitted]


def test_resolve_track_local_existing_file_is_delivered(api, core_ns, emitted, tmp_path):
    engine = AudioEngine()
    core_ns.engine = engine
    delivered = []
    good = tmp_path / "ok.mp3"
    good.write_bytes(b"\x00" * 4096)
    track = {"id": 6, "title": "Ok", "source": "local", "source_id": "s6",
             "file_path": str(good)}

    api._resolve_track(track, lambda t: delivered.append(t))

    assert len(delivered) == 1
    assert "audio_error" not in [name for name, _ in emitted]


# --------------------------------------------------------------------------- #
# P2-7  clear_storage must honour storage_type
# --------------------------------------------------------------------------- #

def test_clear_storage_cache_only_keeps_downloads(api, core_ns, tmp_path):
    core_ns.cache = CacheStub()
    song = tmp_path / "keep.mp3"
    song.write_bytes(b"\x00" * 2048)
    tid = core_ns.db.add_track(title="Keep", artist="A", source="youtube", source_id="v1")
    core_ns.db.update_track(tid, file_path=str(song), is_downloaded=True)

    assert api.clear_storage("cache") is True
    assert core_ns.cache.clear_all_calls == 1
    assert song.exists(), "cache clear must not delete user-owned downloads"


def test_clear_storage_all_removes_downloaded_files(api, core_ns, tmp_path):
    core_ns.cache = CacheStub()
    song = tmp_path / "remove.mp3"
    song.write_bytes(b"\x00" * 2048)
    tid = core_ns.db.add_track(title="Gone", artist="A", source="youtube", source_id="v2")
    core_ns.db.update_track(tid, file_path=str(song), is_downloaded=True)

    assert api.clear_storage("all") is True
    assert core_ns.cache.clear_all_calls == 1
    assert not song.exists(), "'all' is documented to remove downloaded files"


def test_clear_storage_all_tolerates_missing_files(api, core_ns, tmp_path):
    core_ns.cache = CacheStub()
    tid = core_ns.db.add_track(title="Stale", artist="A", source="youtube", source_id="v3")
    core_ns.db.update_track(tid, file_path=str(tmp_path / "vanished.mp3"), is_downloaded=True)

    assert api.clear_storage("all") is True


@pytest.mark.parametrize("bad", ["covers", "downloads", "everything", 42])
def test_clear_storage_rejects_unsupported_type(api, core_ns, bad):
    """Old code returned True for anything that was not an exception, so a typo
    reported success while nothing was cleared."""
    core_ns.cache = CacheStub()
    assert api.clear_storage(bad) is False
    assert core_ns.cache.clear_all_calls == 0


@pytest.mark.parametrize("empty", ["", None])
def test_clear_storage_empty_value_falls_back_to_cache(api, core_ns, empty):
    """An absent value means "the default", which is the documented cache clear."""
    core_ns.cache = CacheStub()
    assert api.clear_storage(empty) is True
    assert core_ns.cache.clear_all_calls == 1


def test_clear_storage_is_case_insensitive(api, core_ns):
    core_ns.cache = CacheStub()
    assert api.clear_storage("CACHE") is True
    assert core_ns.cache.clear_all_calls == 1


def test_clear_storage_without_cache_manager_reports_failure(core_ns):
    core_ns.cache = None
    app = AppApi(core_ns)
    assert app.clear_storage("cache") is False


# --------------------------------------------------------------------------- #
# P2-8  quota 0 must not reach purge_stream_cache(quota_bytes=0)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kwargs", [
    {"quota_gb": 0},
    {"cache_quota_gb": 0},
    {"cache_size_mb": 0},
    {"quota_gb": -5},
])
def test_set_cache_quota_rejects_non_positive_quota(api, core_ns, settings_stub, kwargs):
    """Old code passed quota_bytes=0 to purge_stream_cache for these, which in
    a "0 means delete everything" implementation wipes the stream cache."""
    core_ns.cache = CacheStub()
    res = api.set_cache_quota(**kwargs)
    assert res["success"] is False
    assert res["error"]
    assert core_ns.cache.purges == [], "purge must never run with a 0 quota"
    assert settings_stub.get("storage", "cache_quota_gb") is None


def test_set_cache_quota_positive_value_still_purges(api, core_ns, settings_stub):
    core_ns.cache = CacheStub()
    res = api.set_cache_quota(cache_quota_gb=5)
    assert res["success"] is True
    assert core_ns.cache.purges == [5 * 1024 * 1024 * 1024]
    assert settings_stub.get("storage", "cache_quota_gb") == 5
    assert settings_stub.get("storage", "cache_size_mb") == 5120


# --------------------------------------------------------------------------- #
# P2-9  the ">64 means MB" heuristic, now a pure documented function
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kwargs,expected", [
    ({}, (None, None)),
    ({"cache_quota_gb": 5}, (5.0, 5120.0)),                 # frontend key, GB
    ({"cache_size_mb": 2048}, (2.0, 2048.0)),               # legacy key, MB
    ({"cache_quota_gb": 5, "cache_size_mb": 2048}, (5.0, 5120.0)),  # GB wins
    ({"quota_gb": 500}, (500.0 / 1024.0, 500.0)),            # bare > 64 -> MB
    ({"quota_gb": 64}, (64.0, 65536.0)),                     # threshold is strict
    ({"quota_gb": 10}, (10.0, 10240.0)),                     # bare <= 64 -> GB
    ({"quota_gb": 0}, (0.0, 0.0)),
    ({"quota_gb": -3}, (0.0, 0.0)),
    ({"quota_gb": "junk"}, (None, None)),
    ({"quota_gb": None, "cache_quota_gb": None}, (None, None)),
    ({"quota_gb": "10"}, (10.0, 10240.0)),                   # numeric strings ok
    ({"quota_gb": True}, (None, None)),                      # bool is not a quota
    ({"size_mb": 4096}, (None, None)),                       # unknown key ignored
])
def test_normalize_cache_quota_table(kwargs, expected):
    assert _normalize_cache_quota(**kwargs) == expected


def test_normalize_cache_quota_reads_alias_kwargs():
    assert _normalize_cache_quota(**{"cache_quota_gb": 3}) == (3.0, 3072.0)
    assert _normalize_cache_quota(**{"cache_size_mb": 1024}) == (1.0, 1024.0)


def test_set_cache_quota_matches_the_pure_function(api, settings_stub):
    api.set_cache_quota(quota_gb=500)
    gb, mb = _normalize_cache_quota(quota_gb=500)
    assert settings_stub.get("storage", "cache_quota_gb") == int(round(gb))
    assert settings_stub.get("storage", "cache_size_mb") == int(round(mb))


# --------------------------------------------------------------------------- #
# H-5  _on_queue_end must be wired (it was dead code)
# --------------------------------------------------------------------------- #

def test_app_api_wires_queue_end_hook(core_ns):
    engine = AudioEngine()
    core_ns.engine = engine
    AppApi(core_ns)
    assert engine._on_queue_end is not None, "H-5: hook was never assigned"


def test_queue_end_emits_event(core_ns, monkeypatch):
    app, engine = _api_with_engine(core_ns)
    engine._on_queue_end = app._on_queue_end  # restore what AppApi wired
    events = []
    monkeypatch.setattr(app, "_emit", lambda name, data=None: events.append((name, data)))

    engine.queue.repeat = "off"
    engine.queue.set_tracks(_tracks(2), 1)

    assert engine.next_track() is None
    assert [name for name, _ in events] == ["queue_ended"]
    # The queue itself must stay put at the end (repeat off).
    assert engine.queue.current_index == 1
    assert engine.queue.current_track["id"] == 1


def test_queue_end_not_emitted_when_advancing(core_ns, monkeypatch):
    app, engine = _api_with_engine(core_ns)
    engine._on_queue_end = app._on_queue_end
    events = []
    monkeypatch.setattr(app, "_emit", lambda name, data=None: events.append((name, data)))

    engine.queue.set_tracks(_tracks(3), 0)
    assert engine.next_track()["id"] == 1
    assert "queue_ended" not in [name for name, _ in events]


def test_queue_end_not_emitted_when_repeat_all_wraps(core_ns, monkeypatch):
    app, engine = _api_with_engine(core_ns)
    engine._on_queue_end = app._on_queue_end
    events = []
    monkeypatch.setattr(app, "_emit", lambda name, data=None: events.append((name, data)))

    engine.queue.repeat = "all"
    engine.queue.set_tracks(_tracks(2), 1)
    assert engine.next_track()["id"] == 0
    assert "queue_ended" not in [name for name, _ in events]


# --------------------------------------------------------------------------- #
# H-10  stub bridge methods
# --------------------------------------------------------------------------- #

def test_unused_stubs_removed_from_bridge():
    """stop_track / set_position were `pass` stubs exported to JS with zero
    callers anywhere in the repo (verified by full-tree grep)."""
    assert not hasattr(AppApi, "stop_track")
    assert not hasattr(AppApi, "set_position")


def test_play_pause_reports_last_known_state(api, emitted):
    """play_pause IS called (library "play all" buttons + mediaSession), so it
    must answer with the truth instead of a silent None."""
    assert api.play_pause() == ""
    api.report_state("playing")
    assert api.play_pause() == "playing"
    api.report_state("paused")
    assert api.play_pause() == "paused"
    api.report_state("stopped")
    assert api.play_pause() == "stopped"


# --------------------------------------------------------------------------- #
# dead code removals in audio/queue.py + audio/engine.py
# --------------------------------------------------------------------------- #

def test_queue_unused_helpers_removed():
    """to_serializable() / get_queue_track_ids() had no caller anywhere
    (main.py persists the session differently)."""
    assert not hasattr(PlaybackQueue, "to_serializable")
    assert not hasattr(PlaybackQueue, "get_queue_track_ids")


def test_queue_prev_track_alias_still_works():
    """The alias is dead inside the repo but harmless; keep it working."""
    q = PlaybackQueue()
    q.set_tracks(_tracks(3), 2)
    assert q.prev_track()["id"] == 1
    assert q.previous_track()["id"] == 0


def test_engine_cleanup_stub_removed():
    """AudioEngine.cleanup() was `pass` and AppCore.cleanup() never called it."""
    assert not hasattr(AudioEngine, "cleanup")


def test_shuffle_toggle_keeps_current_track(core_ns):
    """Removing the dead current_key assignment must not disturb shuffle."""
    q = PlaybackQueue()
    q.set_tracks(_tracks(6), 3)
    q.shuffle = True
    assert q.current_track["id"] == 3
    assert q.current_index == 0
    q.shuffle = False
    assert q.current_track["id"] == 3
    assert [t["id"] for t in q.tracks] == list(range(6))