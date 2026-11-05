"""AppApi misc: quotas, queue clearing, settings visibility, play_track events."""

import os
import types
import pytest

from audio.engine import AudioEngine
from audio.queue import PlaybackQueue


def test_paused_restore_is_explicit_and_does_not_start_resolution(api, core_ns, emitted, monkeypatch):
    track = {'source': 'youtube', 'source_id': 'restore', 'title': 'Saved track'}
    core_ns.engine.queue.set_tracks([track], 0)
    api._restore_autoplay = False
    api._restore_position_sec = 84.5
    monkeypatch.setattr(api, '_resolve_track', lambda *_: pytest.fail('Paused restore must not resolve remotely'))
    api.ui_ready()
    payload = next(data for event, data in emitted if event == 'track_changed')
    assert payload['autoplay'] is False
    assert payload['restore_position_sec'] == 84.5
    assert payload['resolution_status'] == 'resolving'


def test_restored_seek_duration_uses_known_library_metadata(api, core_ns, emitted, monkeypatch):
    track = {'id': 72, 'source': 'youtube', 'source_id': 'restore', 'title': 'Saved track', 'duration': 0}
    core_ns.engine.queue.set_tracks([track], 0)
    monkeypatch.setattr(core_ns.db, 'get_track', lambda _: dict(track, duration=175))
    monkeypatch.setattr(api, '_resolve_track', lambda *_: pytest.fail('Paused restore must stay offline'))
    api._restore_autoplay = False
    api.ui_ready()
    payload = next(data for event, data in emitted if event == 'track_changed')
    assert payload['duration'] == 175
    assert core_ns.engine.queue.current_track['duration'] == 175


def test_rejected_stale_queue_click_does_not_cancel_active_resolution(api, core_ns):
    core_ns.engine.queue.set_tracks([{'source':'youtube','source_id':'active','entry_id':'current'}], 0)
    api._playback_epoch = 7
    result = api.play_track({'source':'youtube','source_id':'removed','entry_id':'old'})
    assert result['code'] == 'stale_queue'
    assert api._playback_epoch == 7


def test_library_pagination_reports_true_total_and_does_not_drop_later_rows(api, core_ns):
    core_ns.db.import_playlist_atomic('Large library', '', [
        {'source':'youtube','source_id':str(i),'title':f'Track {i}','artist':'Artist'}
        for i in range(215)
    ])
    first = api.get_library(200, 0, True)
    assert first['total'] == 215 and first['has_more'] is True
    second = api.get_library(200, 200, True)
    assert second['total'] == 215 and second['has_more'] is False
    assert len(first['tracks']) == 200 and len(second['tracks']) == 15
    ids = [row['id'] for page in (first, second) for row in page['tracks']]
    assert len(set(ids)) == 215
    assert isinstance(api.get_library(2), list)


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


def test_settings_projection_tracks_schema_and_persisted_extensions(api, settings_stub, monkeypatch):
    from core.settings import DEFAULT_SETTINGS
    monkeypatch.setitem(DEFAULT_SETTINGS, 'future_category', {'enabled': False})
    settings_stub.set('future_category', 'enabled', True)
    settings_stub.set('subscription', 'active', False)
    settings_stub.set('appearance', 'legacy_custom_color', '#123456')
    tree = api.get_settings()
    assert tree['future_category'] == {'enabled': True}
    assert tree['subscription'] == {'active': False}
    assert tree['appearance'] == {'legacy_custom_color': '#123456'}


def test_failed_settings_flush_is_reported_and_cached_value_rolled_back(api, settings_stub, monkeypatch):
    settings_stub.set('theme', 'theme', 'dark')
    monkeypatch.setattr(settings_stub, 'sync_flush_now', lambda: False, raising=False)
    assert api.save_setting('theme', 'mint', 'theme') is False
    assert settings_stub.get('theme', 'theme') == 'dark'


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
