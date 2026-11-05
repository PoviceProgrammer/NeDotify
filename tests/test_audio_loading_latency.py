"""Time to first audio packet and provider work under background load."""
import http.client
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from core import proxy as proxy_module
from services.base_service import BaseMusicService
from services.yandex_service import YandexService
from tests.helpers import app_core, nedotify_home, proxy_factory, proxy, DeferredExecutor


class QueuedExecutor(DeferredExecutor):
    def submit(self, fn, *args, **kwargs):
        super().submit(fn, *args, **kwargs)
        return object()


@pytest.mark.parametrize('source', ['youtube', 'soundcloud', 'spotify', 'yandex', 'deezer', 'vk'])
def test_first_audio_packet_reaches_player_without_waiting_for_next_packet(proxy, monkeypatch, source):
    """Hold the CDN's second packet until the player receives the first one."""
    release, received = threading.Event(), threading.Event()
    payload = b'a' * 1024 + b'b' * 65536

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[:1024])
            self.wfile.flush()
            release.wait(3)
            self.wfile.write(payload[1024:])

    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True).start()
    # Real HTTPResponse reads, isolated from public DNS/CDN variability.
    monkeypatch.setattr(proxy_module, '_is_ssrf_safe_url', lambda url: True)
    monkeypatch.setattr(proxy_module, '_safe_urlopen', lambda *a, **kw: urllib.request.urlopen(
        f'http://127.0.0.1:{server.server_port}/audio', timeout=3))
    result = {}

    def play():
        conn = http.client.HTTPConnection('127.0.0.1', proxy.port, timeout=3)
        try:
            conn.request('GET', proxy.url('/api/stream', url='https://cdn.example/audio', source=source))
            response = conn.getresponse()
            result['first'] = response.read(1024)
            received.set()
            result['rest'] = response.read()
        finally:
            conn.close()

    player = threading.Thread(target=play)
    player.start()
    try:
        assert received.wait(.7), 'Proxy withheld the first audio packet while waiting for more CDN data'
    finally:
        release.set()
        player.join(4)
        server.shutdown()
        server.server_close()
    assert result == {'first': payload[:1024], 'rest': payload[1024:]}


def test_yandex_only_resolves_selected_bitrate_and_coalesces_simultaneous_plays(monkeypatch):
    import services.yandex_service as module
    monkeypatch.setattr(module, 'HAS_YANDEX', True)
    with BaseMusicService._cache_lock:
        monkeypatch.setattr(BaseMusicService, '_stream_cache', {})
    service = YandexService.__new__(YandexService)
    BaseMusicService.__init__(service)
    service.settings = None
    service._client_config = ('', '')
    service._executor = QueuedExecutor()
    service._playback_executor = QueuedExecutor()
    calls, results, errors = [], [], []

    class Format:
        def __init__(self, bitrate):
            self.codec, self.bitrate_in_kbps, self.direct_link = 'mp3', bitrate, None

        def get_direct_link(self):
            calls.append(self.bitrate_in_kbps)
            self.direct_link = f'https://cdn.example/{self.bitrate_in_kbps}.mp3'
            return self.direct_link

    formats = [Format(128), Format(192), Format(320)]

    def download_info(get_direct_links=False):
        if get_direct_links:
            for item in formats:
                item.get_direct_link()
        return formats

    track = SimpleNamespace(id='123', title='Song', artists=[], cover_uri='', duration_ms=180000,
                            get_download_info=download_info)
    service._get_client = lambda: SimpleNamespace(tracks=lambda ids: [track])
    for _ in range(3):
        service.get_stream_url('123', callback=lambda url, meta: results.append(url), error_callback=errors.append)
    # Exercise either implementation's scheduled work, then check actual API cost.
    for executor in (service._executor, service._playback_executor):
        while executor.tasks:
            executor.tasks.pop(0)()
    assert not errors
    assert results == ['https://cdn.example/320.mp3'] * 3
    assert calls == [320], 'One play must not resolve every bitrate or duplicate a concurrent extraction'


def test_yandex_play_does_not_wait_behind_search(monkeypatch):
    import services.yandex_service as module
    monkeypatch.setattr(module, 'HAS_YANDEX', True)
    service = YandexService.__new__(YandexService)
    BaseMusicService.__init__(service)
    service.settings = None
    service._client_config = None
    service._executor = QueuedExecutor()
    service._playback_executor = QueuedExecutor()
    service.get_stream_url('123')
    assert not service._executor.tasks, 'Playback is queued behind background searches'
    assert len(service._playback_executor.tasks) == 1


@pytest.mark.parametrize('source', ['yandex', 'deezer', 'vk'])
def test_playback_completes_while_background_provider_pool_is_saturated(monkeypatch, source):
    """Use real bounded executors: every background worker is held until Play finishes."""
    from concurrent.futures import ThreadPoolExecutor
    release, ready = threading.Event(), threading.Event()
    calls = []
    background = ThreadPoolExecutor(max_workers=2)
    playback = ThreadPoolExecutor(max_workers=1)
    try:
        blocked = [background.submit(lambda: release.wait(3)) for _ in range(2)]
        if source == 'yandex':
            import services.yandex_service as module
            monkeypatch.setattr(module, 'HAS_YANDEX', True)
            service = YandexService.__new__(YandexService)
            BaseMusicService.__init__(service)
            service.settings, service._client_config = None, None
            fmt = SimpleNamespace(codec='mp3', bitrate_in_kbps=320,
                                  direct_link='https://cdn.example/song.mp3')
            track = SimpleNamespace(id='99', title='Song', artists=[], cover_uri='', duration_ms=180000,
                                    get_download_info=lambda: [fmt])
            service._get_client = lambda: SimpleNamespace(tracks=lambda ids: [track])
            target = '99'
        elif source == 'deezer':
            from services.deezer_service import DeezerService
            service = DeezerService()
            provider = SimpleNamespace(get_stream_url=lambda sid, callback, **kw:
                                       callback('https://cdn.example/song.mp3', {}))
            service._audio_candidates = lambda sid: iter([(provider, {'source': 'youtube', 'source_id': 'video'})])
            target = '99'
        else:
            import services.vk_service as module
            service = module.VKService()
            class Ydl:
                def __init__(self, opts):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def extract_info(self, *args, **kw):
                    return {'url': 'https://cdn.example/song.mp3'}
            monkeypatch.setattr(module, '_has_ytdlp', lambda: True)
            monkeypatch.setattr(module, '_ytdlp', lambda: SimpleNamespace(YoutubeDL=Ydl))
            target = 'https://vk.com/audio123_456'
        service._executor, service._playback_executor = background, playback
        service.get_stream_url(target, callback=lambda url, meta: (calls.append(url), ready.set()))
        assert ready.wait(.7), 'Playback was blocked by background provider requests'
        assert calls == ['https://cdn.example/song.mp3']
        assert all(not task.done() for task in blocked)
    finally:
        release.set()
        background.shutdown(wait=True, cancel_futures=True)
        playback.shutdown(wait=True, cancel_futures=True)


def test_shared_playback_lane_stops_with_service_shutdown():
    service = BaseMusicService()
    assert service.submit_playback(lambda: 42).result(1) == 42
    BaseMusicService.shutdown_executor()
    assert service.submit_playback(lambda: pytest.fail('work after shutdown')) is None
