from types import SimpleNamespace
from unittest.mock import Mock
import threading
import time

import pytest

from core.playback_recovery import _callback_result, _invalidate, recover_stream, same_recording
from core.resolver import StreamResolver
from services.base_service import BaseMusicService


@pytest.mark.parametrize("offered", [
    {"title": "Song (Live)", "artist": "Artist", "duration": 180},
    {"title": "Song (Instrumental)", "artist": "Artist", "duration": 180},
    {"title": "Song (Cover)", "artist": "Artist", "duration": 180},
    {"title": "Song", "artist": "Another Artist", "duration": 180},
    {"title": "Song", "artist": "Artist", "duration": 250},
])
def test_same_recording_rejects_wrong_artist_version_or_duration(offered):
    assert not same_recording({"title": "Song", "artist": "Artist", "duration": 180}, offered)


def test_same_recording_accepts_official_title_and_embedded_artist():
    assert same_recording({"title": "Song", "artist": "Artist", "duration": 180},
                          {"title": "Artist - Song (Official Audio)", "artist": "Uploader", "duration": 182})
    assert not same_recording({"title": "Song (First Remix)", "artist": "Artist"},
                              {"title": "Song (Other Remix)", "artist": "Artist"})


def test_same_recording_requires_offered_duration_when_expected():
    assert not same_recording(
        {"title": "Song", "artist": "Artist", "duration": 180},
        {"title": "Song", "artist": "Artist"},
    )
    assert same_recording(
        {"title": "Song", "artist": "Artist"},
        {"title": "Song", "artist": "Artist", "duration": 180},
    )


def test_callback_result_timeout_does_not_wait_for_blocking_provider():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked_provider(_success, _failure):
        entered.set()
        release.wait(2)
        finished.set()

    started = time.monotonic()
    result = _callback_result(blocked_provider, 0.03)
    elapsed = time.monotonic() - started
    assert entered.is_set()
    assert result == (None, {})
    assert elapsed < 0.5
    release.set()
    assert finished.wait(1)


def test_invalidate_snapshots_shared_provider_cache_once(monkeypatch):
    class CountingCache(dict):
        items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    cache = CountingCache({
        f"unrelated:{index}": {"stream_url": f"https://cdn.example/{index}"}
        for index in range(2000)
    })
    cache["youtube:abcdefghijk"] = {"stream_url": "https://cdn.example/dead"}
    monkeypatch.setattr(BaseMusicService, "_stream_cache", cache)
    core = SimpleNamespace(resolver=None)
    _invalidate(core, "youtube", {"source_id": "abcdefghijk"}, "https://www.youtube.com/watch?v=abcdefghijk")
    assert cache.items_calls == 1
    assert "youtube:abcdefghijk" not in cache


def provider(url=None, candidates=(), metadata=None):
    service = Mock()
    service.get_stream_url.side_effect = lambda target, callback, error_callback: callback(url, metadata or {})
    service.search.side_effect = lambda query, max_results, callback, error_callback: callback(list(candidates))
    return service


def core_for(youtube=None, soundcloud=None):
    return SimpleNamespace(
        youtube=youtube, soundcloud=soundcloud, resolver=StreamResolver(db=None),
        settings=SimpleNamespace(get=lambda category, key, default=None: default),
        proxy=SimpleNamespace(get_proxy_url=lambda source, identifier, url, track_id=None: f"http://127.0.0.1:1234/?url={url}"),
    )


def test_renewal_invalidates_both_stream_caches_and_preserves_position():
    wanted = {"title": "Song", "artist": "Artist", "source": "youtube", "source_id": "abcdefghijk", "duration": 180}
    youtube = provider("https://cdn.example/fresh.mp3", metadata={"title": "Song", "artist": "Artist", "duration": 180})
    core = core_for(youtube=youtube)
    core.resolver.refresh("youtube", "abcdefghijk", "https://cdn.example/dead.mp3")
    BaseMusicService.set_to_cache("youtube:abcdefghijk", {"stream_url": "https://cdn.example/dead.mp3"})
    try:
        result = recover_stream(core, wanted, 42123)
        assert result["ok"]
        assert result["position_ms"] == 42123
        assert result["stream_url"].startswith("http://127.0.0.1:")
        assert BaseMusicService.get_from_cache("youtube:abcdefghijk") is None
        assert core.resolver.get_cached_url("youtube", "abcdefghijk") == "https://cdn.example/fresh.mp3"
        assert "file_path" not in wanted
        youtube.get_stream_url.assert_called_once()
    finally:
        with BaseMusicService._cache_lock:
            BaseMusicService._stream_cache.pop("youtube:abcdefghijk", None)


def test_fallback_skips_incorrect_top_result_and_does_not_rewrite_track():
    wrong = {"title": "Song (Live)", "artist": "Artist", "source": "soundcloud", "source_id": "wrong", "duration": 180}
    wanted = {"title": "Song", "artist": "Artist", "source": "youtube", "source_id": "original", "duration": 180, "id": 99}
    correct = {**wanted, "source": "soundcloud", "source_id": "right"}
    soundcloud = provider("https://cdn.example/right.mp3", candidates=[wrong, correct])
    result = recover_stream(core_for(youtube=provider(), soundcloud=soundcloud), wanted, 5000)
    assert result["ok"]
    assert result["source"] == "soundcloud"
    assert result["source_id"] == "right"
    assert soundcloud.get_stream_url.call_args.args[0] == "right"
    assert wanted["source_id"] == "original"
    assert wanted["id"] == 99


def test_missing_file_never_contacts_providers(tmp_path):
    youtube = provider("https://cdn.example/track.mp3")
    core = core_for(youtube=youtube)
    local = tmp_path / "track.mp3"
    local.write_bytes(b"audio")
    result = recover_stream(core, {"source": "youtube", "file_path": str(local)}, 1234)
    assert result["ok"]
    assert result["position_ms"] == 1234
    youtube.get_stream_url.assert_not_called()
    local.unlink()
    core.settings = None
    assert recover_stream(core, {"source": "local", "file_path": str(local)})["code"] == "file_missing"


def test_disabled_sources_are_skipped_during_direct_and_fallback_recovery():
    youtube = provider('https://cdn.example/disabled.mp3')
    soundcloud = provider('https://cdn.example/disabled-sc.mp3')
    core = core_for(youtube=youtube, soundcloud=soundcloud)
    core.settings = SimpleNamespace(get=lambda category, key, default=None:
                                    False if key in ('youtube_enabled', 'soundcloud_enabled') else default)
    result = recover_stream(core, {'title': 'Song', 'artist': 'Artist', 'source': 'youtube', 'source_id': 'id'})
    assert not result['ok']
    youtube.get_stream_url.assert_not_called()
    youtube.search.assert_not_called()
    soundcloud.get_stream_url.assert_not_called()
    soundcloud.search.assert_not_called()


def test_provider_changing_metadata_does_not_play_unverified_fallback():
    wanted = {"title": "Song", "artist": "Artist", "source": "youtube", "source_id": "original", "duration": 180}
    youtube = provider("https://cdn.example/wrong.mp3", candidates=[wanted],
                       metadata={"title": "Song (Live)", "artist": "Artist", "duration": 180})
    result = recover_stream(core_for(youtube=youtube), wanted)
    assert not result["ok"]
    assert result["code"] == "source_unavailable"


def test_recovery_rejects_expired_url_and_normalizes_nonfinite_position():
    youtube = provider("https://cdn.example/track.mp3?expire=1000000000")
    result = recover_stream(core_for(youtube=youtube), {"source": "youtube", "source_id": "original"}, float("nan"))
    assert not result["ok"]
