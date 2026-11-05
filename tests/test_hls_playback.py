"""SoundCloud HLS must reach the player without re-extraction or unsafe fetches."""
import io
import os
from email.message import Message
from urllib.parse import parse_qs, urlsplit

import pytest

from core import proxy as module
from tests.helpers import app_core, nedotify_home, proxy, proxy_factory



def test_soundcloud_search_metadata_resolves_hls_without_track_lookup(providers):
    service = providers[1]
    payload = {
        'id': 123, 'title': 'Track', 'policy': 'ALLOW', 'duration': 180000,
        'media': {'transcodings': [
            {'url': 'https://api-v2.soundcloud.com/media/full',
             'preset': 'aac_160k', 'format': {'protocol': 'hls'}},
        ]},
    }
    calls, results = [], []
    from types import SimpleNamespace
    def api(url, **kwargs):
        calls.append(url)
        data = {'collection': [payload]} if '/search/' in url else {
            'url': 'https://cdn.sndcdn.com/full/playlist.m3u8'}
        return SimpleNamespace(status_code=200, json=lambda: data)
    service._api_get = api
    service._public_json = lambda url, **kwargs: {
        'url': 'https://cdn.sndcdn.com/full/playlist.m3u8'
    }
    service._media_url_is_servable = lambda url: True
    service._get_ydl = lambda: pytest.fail('HLS must not fall through to yt-dlp')
    service.search('track', callback=lambda tracks: None)
    service._executor.tasks.pop()()
    service.get_stream_url('https://api-v2.soundcloud.com/tracks/123',
                           callback=lambda url, meta: results.append(url))
    service._playback_executor.tasks.pop()()
    assert results == ['https://cdn.sndcdn.com/full/playlist.m3u8']
    assert len(calls) == 1  # one search request; metadata and transcode use the public JSON path


def test_hls_proxy_rewrites_resources_and_does_not_cache_manifest(proxy, app_core, monkeypatch):
    upstream = 'https://cdn.sndcdn.com/audio/playlist.m3u8'
    manifest = (b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n'
                b'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
                b'#EXTINF:6,\nsegment.m4s\n#EXT-X-ENDLIST\n')
    calls = []
    class Response(io.BytesIO):
        status = 200
        def __init__(self, url):
            super().__init__(manifest if url == upstream else b'audio-bytes')
            self.headers = Message()
            self.headers['Content-Type'] = 'application/vnd.apple.mpegurl' if url == upstream else 'audio/mp4'
            self.headers['Content-Length'] = str(len(self.getvalue()))
        def getheaders(self):
            return self.headers.items()
    def open_upstream(req, **kwargs):
        calls.append(req.full_url)
        assert proxy.token not in req.full_url
        return Response(req.full_url)
    monkeypatch.setattr(module, '_is_ssrf_safe_url', lambda url: '127.0.0.1' not in url)
    monkeypatch.setattr(module, '_safe_urlopen', open_upstream)
    response = proxy.get(proxy.url('/api/stream', url=upstream, source='soundcloud', source_id='123'))
    assert response.status == 200
    assert int(response.header('Content-Length')) == len(response.body)
    text = response.body.decode()
    assert text.count('k=' + proxy.token) == 3
    segment = next(line for line in text.splitlines() if line.startswith('/?'))
    assert parse_qs(urlsplit(segment).query)['url'] == ['https://cdn.sndcdn.com/audio/segment.m4s']
    assert proxy.get(segment).body == b'audio-bytes'
    assert not os.listdir(app_core.cache._streams_dir)
    # Nested resources retain the ordinary SSRF gate.
    blocked = module._rewrite_hls_playlist('#EXTM3U\nhttp://127.0.0.1/private\n',
                                          upstream, 'soundcloud', proxy.token)
    assert proxy.get(blocked.splitlines()[1]).status == 400
    assert len(calls) == 2


def test_hls_rejects_local_file_keys():
    with pytest.raises(ValueError):
        module._rewrite_hls_playlist('#EXT-X-KEY:URI="file:///secret"\n',
                                     'https://cdn.sndcdn.com/a', 'soundcloud', 'token')


def test_youtube_search_result_is_reused_by_video_id(providers):
    service = providers[0]
    calls, results = [], []
    def extract(*args, **kwargs):
        calls.append(args[0])
        return {'id': 'dQw4w9WgXcQ', 'url': 'https://cdn.example/audio'}
    service._extract_info_safe = extract
    service.get_stream_url('ytsearch1:Artist - Track',
                           callback=lambda url, meta: results.append(url))
    service._playback_executor.tasks.pop()()
    service.get_stream_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                           callback=lambda url, meta: results.append(url))
    assert len(results) == 2 and len(calls) == 1
    assert not service._playback_executor.tasks


def test_player_recognizes_hls_inside_encoded_proxy_url():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const calls = [];
class Hls {
    static isSupported() { return true; }
    loadSource(url) { calls.push(url); }
    attachMedia() {}
}
const context = vm.createContext({
    URL, console, window: {Hls, location: {href: 'http://127.0.0.1:1234/'}},
    destroyHls() {}, handleStreamError() {}, playbackState: {track: null},
        normalizeAudioSourceUrl(url) { return url; },
});
const code = SOURCE;
vm.runInContext(code.slice(code.indexOf('function loadAudioSource('),
                          code.indexOf('// Prefetch state for the finite playback queue')), context);
// A genuine manifest behind an encoded proxy URL must reach hls.js.
const hlsUrl = 'http://127.0.0.1:1234/?url=' +
    encodeURIComponent('https://cdn.example/live/index.m3u8') + '&k=token';
context.loadAudioSource({removeAttribute() {}, load() {}, currentTime: 0}, hlsUrl);
assert.deepEqual(calls, [hlsUrl]);
// BUG-A1-015: an ordinary CDN path that merely contains "/playlist" is not a
// manifest; feeding it to hls.js turned a parse failure into fatal playback stop.
calls.length = 0;
const plainUrl = 'http://127.0.0.1:1234/?url=' +
    encodeURIComponent('https://cdn.sndcdn.com/playlist/track') + '&k=token';
context.loadAudioSource({removeAttribute() {}, load() {}, currentTime: 0}, plainUrl);
assert.deepEqual(calls, [], 'plain /playlist CDN path must not be treated as HLS');
const soundcloudUrl = 'http://127.0.0.1:1234/?url=' +
    encodeURIComponent('https://playback.media-streaming.soundcloud.cloud/stream/playlist/token') + '&k=token';
context.loadAudioSource({removeAttribute() {}, load() {}, currentTime: 0}, soundcloudUrl);
assert.deepEqual(calls, [soundcloudUrl], 'SoundCloud extensionless HLS must use the HLS player');
""".replace('SOURCE', source('player.js')))


def test_preview_only_soundcloud_skips_media_and_duplicate_extraction(providers, monkeypatch):
    from types import SimpleNamespace
    service = providers[1]
    service._track_metadata_cache.set('123', {
        'id': 123, 'title': 'Track', 'user': {'username': 'Artist'},
        'policy': 'SNIP', 'media': {'transcodings': [
            {'url': 'https://api-v2.soundcloud.com/media/preview',
             'format': {'protocol': 'progressive'}, 'snipped': True}]},
    })
    service._api_get = lambda *a, **k: pytest.fail('Preview does not need another HTTP request')
    service._get_ydl = lambda: pytest.fail('Preview must go directly to fallback')
    searches, errors = [], []
    def search(query, **kwargs):
        searches.append(query)
        kwargs['error_callback']('not found')
    monkeypatch.setattr('services.youtube_service.YouTubeService',
                        lambda *a, **k: SimpleNamespace(search=search))
    service.get_stream_url('123', error_callback=errors.append)
    service._playback_executor.tasks.pop()()
    assert searches == ['Artist - Track']
    assert errors


def test_anonymous_youtube_does_not_repeat_identical_anonymous_attempt(providers, monkeypatch):
    from types import SimpleNamespace
    service = providers[0]
    calls = []
    def extract(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('Requested format is not available')
    service._get_ydl = lambda *a, **k: SimpleNamespace(extract_info=extract)
    monkeypatch.setattr('services.youtube_service.yt_dlp.YoutubeDL',
                        lambda *a, **k: pytest.fail('Already anonymous'))
    with pytest.raises(RuntimeError, match='format'):
        service._extract_info_safe('dQw4w9WgXcQ', 'high')
    assert calls == [1]
