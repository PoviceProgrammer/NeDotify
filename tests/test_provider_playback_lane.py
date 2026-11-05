"""Playback extraction has a reserved lane separate from provider search."""

import threading

from services.base_service import BaseMusicService
from services import soundcloud_service, youtube_service


class CaptureExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        return object()


class EmptyCache:
    def get(self, _key):
        return None


def test_youtube_stream_extraction_uses_playback_lane(monkeypatch):
    service = youtube_service.YouTubeService.__new__(youtube_service.YouTubeService)
    BaseMusicService.__init__(service)
    service.settings = None
    service._executor = CaptureExecutor()
    service._playback_executor = CaptureExecutor()
    service._ydl_lock = threading.RLock()
    service._pending_streams = {}

    monkeypatch.setattr(youtube_service, "HAS_YTDLP", True)
    monkeypatch.setattr(youtube_service, "_is_allowed_youtube_target", lambda _url: True)
    monkeypatch.setattr(service, "get_from_cache", lambda _key: None)

    service.get_stream_url("https://www.youtube.com/watch?v=abcdefghijk")

    assert len(service._playback_executor.submitted) == 1
    assert service._executor.submitted == []


def test_soundcloud_stream_extraction_uses_playback_lane(monkeypatch):
    service = soundcloud_service.SoundCloudService.__new__(soundcloud_service.SoundCloudService)
    BaseMusicService.__init__(service)
    service.settings = None
    service._executor = CaptureExecutor()
    service._playback_executor = CaptureExecutor()
    service._verified_cache = EmptyCache()
    service._unavailable_cache = EmptyCache()

    service.get_stream_url("12345")

    assert len(service._playback_executor.submitted) == 1
    assert service._executor.submitted == []
