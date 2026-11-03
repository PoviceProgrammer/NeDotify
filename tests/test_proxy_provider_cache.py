"""Proxy self-heal invalidates the provider stream cache before re-resolution."""

import io
import urllib.error
from email.message import Message
from types import SimpleNamespace

from core import proxy as proxy_module
from services.base_service import BaseMusicService
from services.soundcloud_service import SoundCloudService
from services.youtube_service import YouTubeService, _yt_cache_key
from tests.helpers import app_core, proxy, qs


def test_upstream_denial_invalidates_provider_cache_before_retry(proxy, app_core, monkeypatch):
    invalidated = []
    app_core.youtube = SimpleNamespace(
        invalidate_stream_url=invalidated.append,
        _get_ydl=lambda *_args, **_kwargs: SimpleNamespace(_cookiejar=None),
    )
    fresh_url = 'https://r1.googlevideo.com/fresh-audio'
    app_core.re_resolve_stream_url_async = lambda _source, _sid, callback, **_kwargs: callback(fresh_url, {})
    monkeypatch.setattr(proxy_module, '_is_ssrf_safe_url', lambda _url: True)
    requests = []

    class Response(io.BytesIO):
        status = 200

        def __init__(self):
            super().__init__(b'fresh-audio')
            self.headers = Message()
            self.headers['Content-Type'] = 'audio/mp4'
            self.headers['Content-Length'] = str(len(self.getvalue()))

        def getheaders(self):
            return list(self.headers.items())

    def open_upstream(req, **_kwargs):
        requests.append(req.full_url)
        if len(requests) == 1:
            raise urllib.error.HTTPError(req.full_url, 403, 'expired URL', {}, None)
        return Response()

    monkeypatch.setattr(proxy_module, '_safe_urlopen', open_upstream)
    response = proxy.get(proxy.url(
        '/api/stream', url='https://r1.googlevideo.com/old-audio',
        source='youtube', source_id='abcdefghijk'))

    assert response.status == 200
    assert response.body == b'fresh-audio'
    assert invalidated == ['abcdefghijk']
    assert requests == [
        'https://r1.googlevideo.com/old-audio',
        fresh_url,
    ]


def test_provider_invalidators_use_their_stream_cache_keys(monkeypatch):
    monkeypatch.setattr(BaseMusicService, '_stream_cache', {})
    youtube_id = 'abcdefghijk'
    youtube_key = _yt_cache_key(youtube_id)
    YouTubeService.set_to_cache(youtube_key, {'stream_url': 'https://cdn.invalid/old'})
    youtube = YouTubeService.__new__(YouTubeService)
    youtube.invalidate_stream_url(youtube_id)
    assert YouTubeService.get_from_cache(youtube_key) is None

    spotify_lookup = 'ytsearch1: Artist - Song'
    expression_key = _yt_cache_key(spotify_lookup)
    resolved_key = _yt_cache_key(youtube_id)
    YouTubeService.set_to_cache(expression_key, {
        'source_id': youtube_id, 'stream_url': 'https://cdn.invalid/old'})
    YouTubeService.set_to_cache(resolved_key, {
        'source_id': youtube_id, 'stream_url': 'https://cdn.invalid/old'})
    youtube.invalidate_stream_url(spotify_lookup)
    assert YouTubeService.get_from_cache(expression_key) is None
    assert YouTubeService.get_from_cache(resolved_key) is None

    soundcloud_id = '12345'
    soundcloud_key = 'soundcloud:https://api-v2.soundcloud.com/tracks/12345'
    SoundCloudService.set_to_cache(soundcloud_key, {'stream_url': 'https://cdn.invalid/old'})
    soundcloud = SoundCloudService.__new__(SoundCloudService)
    soundcloud.invalidate_stream_url(soundcloud_id)
    assert SoundCloudService.get_from_cache(soundcloud_key) is None
