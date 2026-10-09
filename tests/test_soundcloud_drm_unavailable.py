"""A track SoundCloud cannot serve must fail once, not on every click.

SoundCloud track 2301904229 ("baby my type (feat. GATASKI)") is
DRM-protected. Before the fix the api-v2 fast path handed out its
common-encryption media URL and cached it, the proxy answered 403, the
self-heal invalidated the cache and re-resolved to the same URL, and yt-dlp
separately reported "This video is DRM protected" — so every click walked the
same circle and the track never played.

Post-fix contracts pinned here, no network and no yt-dlp involved:
  * a DRM-protected stream URL is never offered to the player nor cached;
  * a permanent extraction failure is remembered, and the next attempt costs
    zero provider calls;
  * a transient failure is NOT remembered, so a network blip still retries;
  * a dead track does not stop the next one in the queue;
  * StreamResolver skips the cascade for a track marked unavailable, survives
    the proxy's invalidate() on 403, and clears the verdict once a real URL
    arrives.
"""

import pytest

from core.resolver import StreamResolver
from services.base_service import BaseMusicService
from services.soundcloud_service import (
    _UNAVAILABLE_MSG,
    SoundCloudService,
    _unavailable_key,
)


DRM_MEDIA_URL = "https://playback.media-streaming.soundcloud.cloud/cbcs/crWG1tb9kTxy/aac_160k/d21"

_TRACK_API_URL = "https://api-v2.soundcloud.com/tracks/2301904229"


def _track_payload(transcodings):
    return {
        "id": 2301904229,
        "title": "baby my type (feat. GATASKI)",
        "duration": 181000,
        "artwork_url": "https://i1.sndcdn.com/artworks-xyz-large.jpg",
        "user": {"username": "some-artist"},
        "media": {"transcodings": transcodings},
    }


#: The progressive entry resolves to a URL the CDN answers with 403, and the
#: second entry is the DRM one yt-dlp's SoundCloud extractor refuses
#: ("This video is DRM protected"). One progressive entry is enough to poison
#: the cache: it is sorted first and its media URL is accepted verbatim.
_DRM_TRANSCODE = _track_payload([
    {
        "preset": "mp3_0",
        "url": "https://api-v2.soundcloud.com/media/soundcloud:tracks:2301904229/aaa/stream/progressive",
        "format": {"protocol": "progressive", "mime_type": "audio/mpeg"},
    },
    {
        "preset": "abr_sq",
        "url": "https://api-v2.soundcloud.com/media/soundcloud:tracks:2301904229/bbb/stream/hls",
        "format": {"protocol": "cbc-aes", "mime_type": 'audio/mp4; codecs="mp4a.40.2"'},
    },
])

#: Same track, but every transcoding is DRM: nothing playable exists at all.
_DRM_ONLY_TRANSCODE = _track_payload([
    {
        "preset": "abr_sq",
        "url": "https://api-v2.soundcloud.com/media/soundcloud:tracks:2301904229/bbb/stream/hls",
        "format": {"protocol": "cbc-aes", "mime_type": 'audio/mp4; codecs="mp4a.40.2"'},
    },
])

_PLAYABLE_TRANSCODE = _track_payload([
    {
        "preset": "mp3_0",
        "url": "https://api-v2.soundcloud.com/media/soundcloud:tracks:111222333/aaa/stream/progressive",
        "format": {"protocol": "progressive", "mime_type": "audio/mpeg"},
    },
])


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def close(self):
        pass


class _StubSession:
    """Answers api-v2, and answers the CDN the way it really does.

    ``denied_media`` are the URLs the CDN refuses — the common-encryption ones
    behind a DRM-protected upload. That refusal IS the bug: api-v2 hands such a
    URL out happily, and it 403s on every single playback attempt.
    """

    def __init__(self, payload, media_url=DRM_MEDIA_URL, denied_media=(DRM_MEDIA_URL,)):
        self._payload = payload
        self._media_url = media_url
        self._denied = denied_media
        self.calls = []

    def get(self, url, timeout=None, headers=None, stream=False):
        self.calls.append(url)
        if "media-streaming" in url:
            return _Resp(403 if url in self._denied else 200)
        if "/media/" in url:
            return _Resp(200, {"url": self._media_url})
        return _Resp(200, self._payload)


class _StubYdl:
    def __init__(self, error=None, info=None):
        self.error = error
        self.info = info
        self.calls = []

    def extract_info(self, url, download=False):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.info


class _InlineExecutor:
    """Runs the extraction worker on the calling thread, so tests are linear."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None

    def shutdown(self, wait=False, cancel_futures=False):
        pass


class _StubYouTube:
    """The fallback search finds nothing; nothing here may reach the network."""

    def __init__(self, settings=None):
        self.searches = []

    def search(self, query, max_results=1, callback=None, error_callback=None):
        self.searches.append(query)
        if error_callback:
            error_callback('nothing found')

    def get_stream_url(self, url, callback=None, error_callback=None):
        if error_callback:
            error_callback('no stream')


@pytest.fixture
def sc(monkeypatch):
    """Real SoundCloudService, hermetic: no client-id probe, no yt-dlp, no threads."""
    monkeypatch.setattr(SoundCloudService, '_get_client_id', lambda self: 'test-client-id')
    monkeypatch.setattr(SoundCloudService, '_get_ydl', lambda self, *a, **k: None)

    svc = SoundCloudService(settings=None)
    svc._executor.shutdown(wait=False, cancel_futures=True)
    svc._executor = _InlineExecutor()
    svc.ydl = _StubYdl()
    svc._get_ydl = lambda: svc.ydl
    svc._session = _StubSession(_DRM_TRANSCODE)

    # The service imports YouTubeService inside get_stream_url, so patching the
    # module attribute is enough to keep the fallback off the network.
    monkeypatch.setattr("services.youtube_service.YouTubeService", _StubYouTube)
    BaseMusicService._stream_cache.clear()
    yield svc
    BaseMusicService._stream_cache.clear()


def _resolve(svc, track_url="2301904229"):
    """One get_stream_url call; returns (stream_url, error) it reported."""
    out = {}

    def on_stream(url, meta=None):
        out['url'] = url

    def on_error(err):
        out.setdefault('error', err)

    svc.get_stream_url(track_url, callback=on_stream, error_callback=on_error)
    return out.get('url'), out.get('error')


def test_drm_stream_url_is_never_offered_or_cached(sc):
    """The pre-fix fast path handed the CDN URL out and cached it, so every
    later play started with a 403 the proxy could not heal."""
    url, error = _resolve(sc)

    assert url is None, "a DRM-protected media URL must not reach the player"
    assert BaseMusicService.get_from_cache("soundcloud:2301904229") is None
    assert sc._unavailable_cache.get(_unavailable_key("2301904229")), (
        "the refusal must be remembered, not rediscovered on every play"
    )


def test_permanent_failure_is_reported_once_and_never_re_resolved(sc, monkeypatch):
    """yt-dlp's DRM verdict ends the loop: the next attempt spends nothing."""
    sc._session = _StubSession(_DRM_ONLY_TRANSCODE)
    sc.ydl = _StubYdl(error=Exception(
        'ERROR: [soundcloud] 2301904229: This video is DRM protected'))

    url, error = _resolve(sc)
    assert url is None
    assert error, "the caller has to hear about it at least once"
    session_calls, ydl_calls = len(sc._session.calls), len(sc.ydl.calls)
    assert session_calls and ydl_calls

    url2, error2 = _resolve(sc)

    assert url2 is None
    assert error2 == _UNAVAILABLE_MSG
    assert len(sc._session.calls) == session_calls, "no second round trip to the CDN"
    assert len(sc.ydl.calls) == ydl_calls, "no second extraction of a DRM track"
    assert BaseMusicService.get_from_cache("soundcloud:2301904229") is None


def test_cached_dead_url_is_dropped_when_the_track_is_marked_unavailable(sc):
    """The stale URL the proxy already holds must not outrank the memo.

    ``play_track`` reads the cached stream URL before anything asks the
    provider, so a dead one has to disappear when the verdict is recorded.
    """
    BaseMusicService.set_to_cache("soundcloud:2301904229", {
        "title": "baby my type (feat. GATASKI)",
        "stream_url": DRM_MEDIA_URL,
    })
    sc._session = _StubSession(_DRM_ONLY_TRANSCODE)
    sc.ydl = _StubYdl(error=Exception('ERROR: [soundcloud] 2301904229: This video is DRM protected'))

    url, _error = _resolve(sc)

    assert url is None
    assert BaseMusicService.get_from_cache("soundcloud:2301904229") is None


def test_transient_failure_is_not_remembered(sc):
    """A socket error says nothing about the track, so it must stay retryable."""
    sc._session = _StubSession(_DRM_ONLY_TRANSCODE)
    sc.ydl = _StubYdl(error=ConnectionError('Read timed out'))

    _resolve(sc)
    assert not sc._unavailable_cache.get(_unavailable_key("2301904229"))
    first_calls = len(sc.ydl.calls)

    _resolve(sc)

    assert len(sc.ydl.calls) > first_calls, "a network blip must be retried"


def test_a_dead_track_does_not_stop_the_next_one(sc):
    """The queue has to move: one unplayable track cannot poison its neighbours."""
    sc._session = _StubSession(_DRM_ONLY_TRANSCODE)
    sc.ydl = _StubYdl(error=Exception('ERROR: [soundcloud] 2301904229: This video is DRM protected'))
    _resolve(sc)

    sc._session = _StubSession(_PLAYABLE_TRANSCODE, media_url="https://playback.media-streaming.soundcloud.cloud/cbcs/ok/mp3_0/next/stream")
    sc.ydl = _StubYdl(info=None)

    url, _error = _resolve(sc, "111222333")

    assert url == "https://playback.media-streaming.soundcloud.cloud/cbcs/ok/mp3_0/next/stream"


def test_youtube_fallback_still_answers_for_a_drm_track(sc, monkeypatch):
    """Losing the DRM URL must not lose the track: the fallback is what plays it."""
    sc._session = _StubSession(_DRM_ONLY_TRANSCODE)
    sc.ydl = _StubYdl(error=Exception('ERROR: [soundcloud] 2301904229: This video is DRM protected'))

    class _HitYouTube(_StubYouTube):
        def search(self, query, max_results=1, callback=None, error_callback=None):
            self.searches.append(query)
            callback([{"source_id": "yt-id", "source_url": "https://www.youtube.com/watch?v=yt-id",
                       "duration": 181, "title": "baby my type", "artist": "some-artist"}])

        def get_stream_url(self, url, callback=None, error_callback=None):
            callback("http://yt/fallback", {"title": "baby my type"})

    monkeypatch.setattr("services.youtube_service.YouTubeService", _HitYouTube)

    url, _error = _resolve(sc)

    assert url == "http://yt/fallback", "the api-v2 payload carries the title the fallback needs"


# --------------------------------------------------------------------------- #
# StreamResolver: the cascade must not be walked again for a dead track
# --------------------------------------------------------------------------- #

def test_resolve_skips_the_cascade_for_a_marked_unavailable_track():
    r = StreamResolver(db=None)
    calls = []
    r.mark_unavailable("soundcloud", "2301904229", "DRM protected")

    for _ in range(3):
        assert r.resolve("soundcloud", "2301904229",
                         lambda: (calls.append(1), (None, "DRM"))[1]) is None

    assert calls == [], "the provider was asked again for a track that cannot play"
    assert r.is_unavailable("soundcloud", "2301904229")


def test_invalidate_from_the_proxy_403_keeps_the_verdict():
    """The proxy invalidates on every 403 and re-resolves; that pair must not
    re-open the loop this verdict closes."""
    r = StreamResolver(db=None)
    r.mark_unavailable("soundcloud", "2301904229", "DRM protected")
    calls = []

    r.invalidate("soundcloud", "2301904229")
    assert r.resolve("soundcloud", "2301904229",
                     lambda: (calls.append(1), (None, "DRM"))[1]) is None

    assert calls == []


def test_a_fresh_url_clears_the_verdict():
    r = StreamResolver(db=None)
    r.mark_unavailable("soundcloud", "2301904229", "DRM protected")

    r.refresh("soundcloud", "2301904229", "http://fresh/stream")

    assert not r.is_unavailable("soundcloud", "2301904229")
    assert r.resolve("soundcloud", "2301904229",
                     lambda: (_ for _ in ()).throw(AssertionError("cascade rerun"))) == "http://fresh/stream"


def test_only_the_dead_key_is_skipped():
    """Advancing the queue means resolving the next track, not every track."""
    r = StreamResolver(db=None)
    r.mark_unavailable("soundcloud", "2301904229", "DRM protected")

    assert r.resolve("soundcloud", "2301904229", lambda: (None, "DRM")) is None
    assert r.resolve("soundcloud", "111222333", lambda: ("http://ok/stream", None)) == "http://ok/stream"


def test_a_verdict_expires_so_a_re_enabled_track_is_tried_again(monkeypatch):
    import core.resolver as resolver_module

    monkeypatch.setattr(resolver_module, "_FAIL_TTL", 0.0)
    r = StreamResolver(db=None)
    r.mark_unavailable("soundcloud", "2301904229", "DRM protected")
    calls = []

    r.resolve("soundcloud", "2301904229", lambda: (calls.append(1), ("http://ok", None))[1])

    assert calls == [1], "an expired verdict must not keep a track unreachable"