"""Warm streams must skip extraction and duplicate CDN validation, without stale tokens."""

import logging
import base64
import json
import threading
import time
from email.utils import formatdate
from types import SimpleNamespace

import pytest

from core.resolver import StreamResolver
from services.base_service import BaseMusicService
from services.soundcloud_service import SoundCloudService, _TTLCache
from services.youtube_service import YouTubeService
from tests.helpers import DeferredExecutor
from utils.stream_urls import stream_url_expired


@pytest.fixture(autouse=True)
def isolated_stream_cache(monkeypatch):
    with BaseMusicService._cache_lock:
        monkeypatch.setattr(BaseMusicService, '_stream_cache', {})


@pytest.mark.parametrize('query,expired', [
    ('expire=1700000000', True),
    ('Expires=1700000000&Signature=abc', True),
    ('expire=1700000060', True),
    ('expire=1700000061', False),
    ('expire=invalid', False),
    ('expire=12', False),
    ('expire=1700000061garbage', False),
    ('token=1700000000', False),
    ('Expires=1700000300', False),
])
def test_expiry_is_local_and_only_interprets_explicit_tokens(query, expired):
    assert stream_url_expired('https://cdn.example/audio?' + query, now=1700000000) is expired


def test_expires_accepts_http_date_form():
    http_date = formatdate(1699999900, usegmt=True)
    assert stream_url_expired(
        'https://cdn.example/audio?Expires=' + http_date.replace(' ', '%20').replace(',', '%2C'),
        now=1700000000,
    )


def _soundcloud_signed_url(expiry, *, outer_expiry=1700007200):
    # CloudFront uses a URL-safe alphabet different from RFC 4648.
    policy = {'Statement': [{'Resource': 'https://playback.media-streaming.soundcloud.cloud/audio/*',
                             'Condition': {'DateLessThan': {'AWS:EpochTime': expiry}}}]}
    encoded = base64.b64encode(json.dumps(policy).encode()).decode().translate(str.maketrans('+=/', '-_~'))
    return f'https://playback.media-streaming.soundcloud.cloud/audio/playlist.m3u8?expires={outer_expiry}&Policy={encoded}'


@pytest.mark.parametrize('expiry,expired', [(1699999999, True), (1700000060, True), (1700000061, False)])
def test_soundcloud_policy_deadline_overrides_longer_outer_expiry(expiry, expired):
    assert stream_url_expired(_soundcloud_signed_url(expiry), now=1700000000) is expired


def test_lowercase_cdn_expiry_is_checked():
    assert stream_url_expired('https://cdn.example/audio?expires=1699999999', now=1700000000)


def test_expired_soundcloud_policy_is_rejected_by_both_stream_cache_layers():
    url = _soundcloud_signed_url(int(time.time()) - 1, outer_expiry=int(time.time()) + 7200)
    BaseMusicService.set_to_cache('soundcloud:123', {'stream_url': url})
    assert BaseMusicService.get_from_cache('soundcloud:123') is None
    invalidated = []
    db = SimpleNamespace(get_cached_stream=lambda *a, **kw: {'stream_url': url},
                         invalidate_cached_stream=lambda *a: invalidated.append(a))
    resolver = StreamResolver(db=db)
    assert resolver.get_cached_url('soundcloud', '123') is None
    assert invalidated == [('soundcloud', '123')]


@pytest.mark.parametrize('policy', ['invalid', 'e30_', 'W10_', '!' * 20000])
def test_malformed_cdn_policy_cannot_break_playback(policy):
    assert not stream_url_expired('https://cdn.example/audio?Policy=' + policy, now=1700000000)


@pytest.mark.parametrize('wrapped', [False, True])
def test_provider_cache_skips_dead_tokens_even_before_six_hour_ttl(wrapped):
    key = 'youtube:video'
    data = {'stream_url': f'https://cdn.example/audio?expire={int(time.time()) - 1}'}
    if wrapped:
        BaseMusicService.set_to_cache(key, data)
    else:
        BaseMusicService._stream_cache[key] = data
    assert BaseMusicService.get_from_cache(key) is None
    assert key not in BaseMusicService._stream_cache


def test_late_cache_miss_does_not_start_another_network_cascade(monkeypatch):
    resolver = StreamResolver(db=None)

    def interrupted_cache_read(*args):
        # This caller observed a miss; another flight finishes before it can
        # register as an owner. A second extraction must not run in that gap.
        resolver.refresh('youtube', 'video', 'https://cdn.example/ready')
        return None

    monkeypatch.setattr(resolver, 'get_cached_url', interrupted_cache_read)
    calls = []
    assert resolver.resolve('youtube', 'video', lambda: (calls.append(1), None)) == 'https://cdn.example/ready'
    assert not calls
    assert resolver.stats()['network_cascades'] == 0


@pytest.fixture
def soundcloud():
    # No constructor: it warms client ID and yt-dlp on real worker threads.
    service = SoundCloudService.__new__(SoundCloudService)
    BaseMusicService.__init__(service)
    service.logger = logging.getLogger('test-stream-startup')
    service._executor = DeferredExecutor()
    service._playback_executor = DeferredExecutor()
    service.settings = SimpleNamespace(get=lambda category, key, default=None: default)
    service._ydl_tls = threading.local()
    service._verified_cache = _TTLCache()
    service._unavailable_cache = _TTLCache()
    service._track_metadata_cache = _TTLCache()
    service._get_client_id = lambda: 'cid'
    service._api_get = lambda *args, **kwargs: SimpleNamespace(status_code=404, json=lambda: {})
    service._get_ydl = lambda: SimpleNamespace(extract_info=lambda *args, **kwargs: None)
    return service


def test_fresh_soundcloud_validation_is_reused_by_replay(soundcloud):
    calls, probes, responses = [], [], []
    media_url = 'https://cdn.sndcdn.com/audio.mp3'

    def get(url, **kwargs):
        calls.append(url)
        payload = ({'url': media_url} if '/media/' in url else {
            'id': 123, 'duration': 180000, 'title': 'Track',
            'media': {'transcodings': [{'url': 'https://api-v2.soundcloud.com/media/stream',
                                      'format': {'protocol': 'progressive'}}]},
        })
        return SimpleNamespace(status_code=200, json=lambda: payload)

    soundcloud._api_get = get
    soundcloud._public_json = lambda url, **kwargs: {'url': media_url}
    soundcloud._media_url_is_servable = lambda url: probes.append(url) or True
    soundcloud.get_stream_url('123', callback=lambda url, meta: responses.append(url))
    soundcloud._playback_executor.tasks.pop()()
    assert len(calls) == 1 and probes == [media_url]

    for _ in range(3):
        soundcloud.get_stream_url('123', callback=lambda url, meta: responses.append(url))
    assert responses == [media_url] * 4
    assert len(calls) == 1 and probes == [media_url]
    assert not soundcloud._playback_executor.tasks


@pytest.mark.parametrize('servable', [False, True])
def test_uncertain_soundcloud_cache_is_probed_once_off_caller(soundcloud, servable):
    media_url = 'https://cdn.sndcdn.com/cached.mp3'
    BaseMusicService.set_to_cache('soundcloud:123', {'stream_url': media_url})
    probes, responses, errors = [], [], []
    soundcloud._media_url_is_servable = lambda url: probes.append(url) or servable
    for _ in range(4):
        soundcloud.get_stream_url('123', callback=lambda url, meta: responses.append(url),
                                  error_callback=errors.append)
    assert not probes and not responses and not errors
    assert len(soundcloud._playback_executor.tasks) == 1
    soundcloud._playback_executor.tasks.pop()()
    assert probes == [media_url]
    if servable:
        assert responses == [media_url] * 4 and not errors
    else:
        assert len(errors) == 4 and not responses
        assert all('SoundCloud' in error or 'резерв' in error.lower() for error in errors)
        assert BaseMusicService.get_from_cache('soundcloud:123') is None


def test_youtube_worker_reuses_a_prefetch_completed_before_it_runs(monkeypatch):
    import services.youtube_service as module
    monkeypatch.setattr(module, 'HAS_YTDLP', True)
    service = YouTubeService.__new__(YouTubeService)
    BaseMusicService.__init__(service)
    service._ydl_lock = threading.Lock()
    service._pending_streams = {}
    service._executor = DeferredExecutor()
    service._playback_executor = DeferredExecutor()
    calls, responses = [], []
    service._extract_info_safe = lambda *a, **k: calls.append(1)
    service.get_stream_url('dQw4w9WgXcQ', callback=lambda url, meta: responses.append(url))
    BaseMusicService.set_to_cache('youtube:dQw4w9WgXcQ', {'stream_url': 'https://cdn.example/ready'})
    service._playback_executor.tasks.pop()()
    assert responses == ['https://cdn.example/ready']
    assert not calls and not service._pending_streams


@pytest.mark.parametrize('failure', ['timeout', 'connection'])
def test_soundcloud_api_timeout_keeps_working_same_source_sdk_fallback(soundcloud, failure):
    import requests
    calls, errors = [], []
    def timeout(*args, **kwargs):
        calls.append('api')
        error = requests.exceptions.ReadTimeout if failure == 'timeout' else requests.exceptions.ConnectionError
        raise error('network unavailable')
    soundcloud._api_get = timeout
    def extract(*args, **kwargs):
        calls.append('sdk')
        return {'url': 'https://cdn.sndcdn.com/full.mp3', 'title': 'Song', 'uploader': 'Artist', 'duration': 180}
    soundcloud._get_ydl = lambda: SimpleNamespace(extract_info=extract)
    streams = []
    soundcloud.get_stream_url('2393146779', callback=lambda url, meta: streams.append(url), error_callback=errors.append)
    soundcloud._playback_executor.tasks.pop()()
    assert calls == ['api', 'sdk'] and not errors
    assert streams == ['https://cdn.sndcdn.com/full.mp3']
    assert not soundcloud._pending_requests
    assert not len(soundcloud._unavailable_cache), 'A network timeout is not a permanently unavailable track'


def test_soundcloud_timeout_reaches_engine_verified_fallback(soundcloud):
    import requests
    from tests.test_engine_resolve import _engine, _core, _Youtube
    class Immediate:
        def submit(self, fn):
            fn()
            return object()
    soundcloud._playback_executor = Immediate()
    def timeout(*args, **kwargs):
        raise requests.exceptions.ReadTimeout('read timed out')
    soundcloud._api_get = timeout
    soundcloud._get_ydl = lambda: SimpleNamespace(extract_info=lambda *args, **kw: (_ for _ in ()).throw(TimeoutError('SDK failed too')))
    youtube = _Youtube(results=[{'source_id': 'other', 'title': 'Other Song', 'artist': 'Artist'},
                               {'source_id': 'right', 'title': 'Song', 'artist': 'Artist'}],
                       stream='https://cdn.example/full.m4a')
    engine = _engine(_core(youtube=youtube, soundcloud=soundcloud))
    assert engine.resolve_stream_url({'source': 'soundcloud', 'source_id': '2393146779',
                                      'title': 'Song', 'artist': 'Artist'}) == 'https://cdn.example/full.m4a'
    assert len(youtube.stream_calls) == 1 and 'right' in youtube.stream_calls[0]


def test_soundcloud_reuses_ytdlp_public_client_id_without_scraping_again():
    service = SoundCloudService.__new__(SoundCloudService)
    BaseMusicService.__init__(service)
    service.settings = None
    service._client_id = None
    service._client_id_lock = threading.Lock()
    service._client_id_retry_at = 0
    cid = 'a' * 32
    service._client_id_cache = SimpleNamespace(load=lambda *args: cid)
    service._get_ydl = lambda: pytest.fail('Cache inspection must not allocate a yt-dlp instance')
    service._session = SimpleNamespace(get=lambda *args, **kwargs: pytest.fail('Client id was already extracted by yt-dlp'))
    assert service._get_client_id() == cid


def test_rejected_ytdlp_client_id_is_not_reused_during_api_refresh():
    service = SoundCloudService.__new__(SoundCloudService)
    BaseMusicService.__init__(service)
    service.settings = None
    old, fresh = 'a' * 32, 'b' * 32
    service._client_id = old
    service._client_id_lock = threading.Lock()
    service._client_id_retry_at = 0
    service._client_id_cache = SimpleNamespace(load=lambda *args: old)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url == 'https://soundcloud.com':
            return SimpleNamespace(status_code=200, text='<script src="https://a-v2.sndcdn.com/assets/app.js"></script>')
        if '/assets/' in url:
            return SimpleNamespace(text=f'client_id:"{fresh}"')
        return SimpleNamespace(status_code=403 if old in url else 200)
    service._session = SimpleNamespace(get=get)
    assert service._api_get(f'https://api-v2.soundcloud.com/tracks/123?client_id={old}').status_code == 200
    assert service._client_id == fresh
    assert len(calls) == 4
    assert not any('/search/' in url for url in calls), 'Validate through the requested track, not a throwaway search'
