"""Playback regressions seen with Zapret: rejected search and duplicate extraction."""
import threading
from types import SimpleNamespace

import pytest

from services.youtube_service import YouTubeService, _is_allowed_youtube_target
from services.soundcloud_service import SoundCloudService


class DeferredExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args):
        self.tasks.append(lambda: fn(*args))


@pytest.fixture
def youtube(monkeypatch):
    import services.youtube_service as module
    monkeypatch.setattr(module, "HAS_YTMUSIC", False)
    monkeypatch.setattr(module, "ThreadPoolExecutor", lambda **kw: DeferredExecutor())
    svc = YouTubeService()
    svc._executor.tasks.clear()  # constructor warm-up is irrelevant here
    svc._playback_executor.tasks.clear()
    monkeypatch.setattr(svc, "get_from_cache", lambda key: None)
    monkeypatch.setattr(svc, "set_to_cache", lambda *args: None)
    return svc


def test_spotify_search_target_reaches_extractor(youtube):
    target = "ytsearch1: PHARAOH - На луне"
    out, inputs = [], []
    def extract(url, *args, **kwargs):
        inputs.append(url)
        return {"url": "https://cdn.example/audio", "id": "dQw4w9WgXcQ"}
    youtube._extract_info_safe = extract
    youtube.get_stream_url(target, callback=lambda url, meta: out.append(url))
    youtube._playback_executor.tasks.pop()()
    assert inputs == [target]
    assert out == ["https://cdn.example/audio"]


@pytest.mark.parametrize("target", ["ytsearch1:", "ytsearch99:test", "http://127.0.0.1/a", "file:///a"])
def test_search_support_keeps_other_targets_rejected(target):
    assert not _is_allowed_youtube_target(target)


def test_simultaneous_play_and_queue_requests_share_extraction(youtube):
    streams = []
    youtube._extract_info_safe = lambda *a, **k: {"url": "https://cdn.example/audio"}
    for _ in range(3):
        youtube.get_stream_url("dQw4w9WgXcQ", callback=lambda url, meta: streams.append(url))
    assert len(youtube._playback_executor.tasks) == 1
    youtube._playback_executor.tasks.pop()()
    assert streams == ["https://cdn.example/audio"] * 3


def test_failed_shared_request_notifies_every_listener_and_can_retry(youtube):
    errors = []
    youtube._extract_info_safe = lambda *a, **k: None
    for _ in range(2):
        youtube.get_stream_url("dQw4w9WgXcQ", error_callback=errors.append)
    youtube._playback_executor.tasks.pop()()
    assert len(errors) == 2
    youtube.get_stream_url("dQw4w9WgXcQ", error_callback=errors.append)
    assert len(youtube._playback_executor.tasks) == 1


def test_soundcloud_refreshes_rejected_client_id_once():
    svc = SoundCloudService.__new__(SoundCloudService)
    svc._client_id = "old"
    svc._client_id_lock = threading.Lock()
    calls = []
    def get(url, timeout):
        calls.append(url)
        return SimpleNamespace(status_code=403 if "client_id=old" in url else 200)
    svc._session = SimpleNamespace(get=get)
    def refresh():
        assert svc._client_id is None
        svc._client_id = "new"
        return "new"
    svc._get_client_id = refresh
    response = svc._api_get("https://api-v2.soundcloud.com/search/tracks?q=test&client_id=old")
    assert response.status_code == 200
    assert len(calls) == 2
    assert "q=test" in calls[1] and "client_id=new" in calls[1]


def test_anonymous_success_does_not_disable_configured_cookies(youtube, monkeypatch):
    import services.youtube_service as module
    youtube.settings = SimpleNamespace(get=lambda category, key, default=None:
                                       "firefox" if key == "browser_cookies" else default)
    class CookieYdl:
        def extract_info(self, *a, **k):
            raise Exception("The page needs to be reloaded")
    class AnonymousYdl:
        def __init__(self, opts):
            assert "cookiesfrombrowser" not in opts
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def extract_info(self, *a, **k):
            return {"url": "https://cdn.example/audio", "acodec": "opus"}
    monkeypatch.setattr(youtube, "_get_ydl", lambda *a, **k: CookieYdl())
    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", AnonymousYdl)
    youtube._extract_info_safe("dQw4w9WgXcQ", "high")
    assert youtube._get_ydl_opts("bestaudio/best")["cookiesfrombrowser"] == ("firefox",)


def test_soundcloud_absolute_url_is_not_prefixed_again():
    from core.app import AppCore
    core = AppCore.__new__(AppCore)
    import threading
    core._service_lock = threading.RLock()
    core._shutting_down = threading.Event()
    core._resolution_timers = set()
    core._resolve_threads = set()
    core.db = SimpleNamespace(close_thread_connection=lambda: None)
    targets = []
    done = threading.Event()
    def get_stream_url(url, callback, **kwargs):
        targets.append(url)
        callback(None)
    core.soundcloud = SimpleNamespace(get_stream_url=get_stream_url)
    core.settings = None
    target = "https://soundcloud.com/artist/song"
    core.re_resolve_stream_url_async("soundcloud", target, callback=lambda *a: done.set())
    assert done.wait(2)
    assert targets == [target]


@pytest.mark.parametrize('require_auth', [False, True])
def test_public_download_skips_cookies_but_gated_download_uses_them(youtube, monkeypatch, tmp_path, require_auth):
    import services.youtube_service as module
    youtube.settings = SimpleNamespace(get=lambda category, key, default=None:
                                       'firefox' if key == 'browser_cookies' else default)
    calls = []
    class Downloader:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, target, download):
            calls.append(target)
            assert download and self.opts['http_chunk_size'] <= 1048576
            if require_auth and 'cookiesfrombrowser' not in self.opts:
                raise Exception('Sign in to confirm your age')
            if not require_auth:
                assert 'cookiesfrombrowser' not in self.opts
            self.path = self.opts['outtmpl'].replace('%(ext)s', 'webm')
            with open(self.path, 'wb') as f:
                f.write(b'x' * 8192)
            return {'ext': 'webm', 'acodec': 'opus'}
        def prepare_filename(self, info):
            return self.opts['outtmpl'].replace('%(ext)s', info['ext'])
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Downloader)
    result = youtube.download_audio_sync('dQw4w9WgXcQ', str(tmp_path))
    assert tmp_path.joinpath(result).exists()
    assert len(calls) == (2 if require_auth else 1)
    if not require_auth:
        assert youtube._get_ydl_opts('bestaudio/best')['cookiesfrombrowser'] == ('firefox',)


def test_download_without_ffprobe_prefers_mutagen_supported_container(youtube, monkeypatch, tmp_path):
    import services.youtube_service as module
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: None)
    formats = []
    class Downloader:
        def __init__(self, opts):
            self.opts = opts
            formats.append(opts['format'])
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, target, download):
            self.path = self.opts['outtmpl'].replace('%(ext)s', 'm4a')
            with open(self.path, 'wb') as file:
                file.write(b'audio' * 1024)
            return {'ext': 'm4a', 'acodec': 'aac'}
        def prepare_filename(self, info):
            return self.path
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Downloader)
    output = youtube.download_audio_sync('dQw4w9WgXcQ', str(tmp_path))
    assert output.endswith('.m4a')
    assert formats[0].split('/')[0] == 'bestaudio[ext=m4a]'


def test_id_watch_url_and_short_url_share_stream_extraction(youtube):
    streams = []
    youtube._extract_info_safe = lambda *a, **k: {'url': 'https://cdn.example/audio'}
    for target in ('dQw4w9WgXcQ', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                   'https://youtu.be/dQw4w9WgXcQ?t=12'):
        youtube.get_stream_url(target, callback=lambda url, meta: streams.append(url))
    assert len(youtube._playback_executor.tasks) == 1
    youtube._playback_executor.tasks.pop()()
    assert len(streams) == 3


def test_background_cache_reuses_resolved_audio_without_provider_extraction(tmp_path, monkeypatch):
    import logging
    import yt_dlp
    from utils.cache_manager import CacheManager
    from tests.audio_helpers import wave_bytes
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
    cache.db = SimpleNamespace(set_cached_file=lambda *args: saved.append(args))
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', lambda *_a, **_k: pytest.fail('provider extraction must not run'))
    class Response:
        headers = {'Content-Type': 'audio/wav', 'Content-Length': str(len(wave_bytes()))}
        def __init__(self):
            self.payload = wave_bytes()
        def read(self, count=-1):
            result, self.payload = self.payload[:count], self.payload[count:]
            return result
        def __enter__(self): return self
        def __exit__(self, *_args): return False
    monkeypatch.setattr('utils.url_safety.guarded_open_url', lambda *_a, **_k: Response())
    source_id = 'ytsearch1: Artist - Title'
    cache.download_audio_stream('spotify', source_id,
                                'https://media.googlevideo.com/videoplayback?token=test')
    for task in cache._executor.tasks:
        task()
    assert saved and saved[0][:2] == ('spotify', source_id)
    from utils.cache_manager import stream_cache_stem
    # BUG-A1-006: cache files are named by a digest of (source, source_id), so
    # Cyrillic search expressions can no longer collide on one file name.
    assert tmp_path.joinpath(f"{stream_cache_stem('spotify', source_id)}.wav").exists()
