"""AppApi misc: quotas, queue clearing, settings visibility, play_track events."""

import os
import types

from audio.engine import AudioEngine
from audio.queue import PlaybackQueue


def test_set_cache_quota_accepts_gb_key(api, settings_stub):
    res = api.set_cache_quota(cache_quota_gb=5)
    assert res.get("success", True) is not False
    assert settings_stub.get("storage", "cache_quota_gb") == 5
    assert settings_stub.get("storage", "cache_size_mb") == 5 * 1024


def test_set_cache_quota_accepts_mb_key(api, settings_stub):
    api.set_cache_quota(cache_size_mb=2048)
    assert settings_stub.get("storage", "cache_quota_gb") == 2
    assert settings_stub.get("storage", "cache_size_mb") == 2048


def test_set_cache_quota_empty_rejected(api):
    res = api.set_cache_quota()
    assert res["success"] is False


def test_get_settings_includes_app_category(api, settings_stub, emitted):
    settings_stub.set("app", "discord_rpc_enabled", True)
    settings_stub.set("theme", "theme", "dark")
    res = api.get_settings()
    assert "app" in res
    assert res["app"]["discord_rpc_enabled"] is True


def test_get_setting_dotted_and_bare(api, settings_stub):
    settings_stub.set("audio", "volume", 70)
    assert api.get_setting("audio.volume") == 70
    assert api.get_setting("volume", "fallback") == "fallback"


def test_clear_queue_keeps_current(api, emitted, core_ns):
    core_ns.engine = types.SimpleNamespace(queue=PlaybackQueue())
    tracks = [{"id": i, "title": "t%d" % i} for i in range(3)]
    core_ns.engine.queue.set_tracks(tracks, 1)
    res = api.clear_queue()
    assert res["success"] is True
    assert core_ns.engine.queue.count == 1
    assert core_ns.engine.queue.current_track["id"] == 1
    assert any(e == "queue_updated" for e, _ in emitted)


def test_play_track_emits_queue_updated(core_ns, tmp_path, monkeypatch):
    engine = AudioEngine()
    core_ns.engine = engine
    from core.api import AppApi
    api = AppApi(core_ns)
    engine._on_track_changed = None  # keep the test headless: no UI callbacks
    events = []
    monkeypatch.setattr(api, "_emit", lambda n, d=None: events.append((n, d)))

    big = tmp_path / "big.mp3"
    big.write_bytes(b"\x00" * 2048)
    track = {"id": 1, "title": "T", "artist": "A", "source": "local",
             "source_id": "p1", "file_path": str(big)}
    engine.queue.set_tracks([], 0)
    api.play_track(track, [track], 0)
    assert any(e == "queue_updated" for e, _ in events)
    assert engine.queue.count == 1
