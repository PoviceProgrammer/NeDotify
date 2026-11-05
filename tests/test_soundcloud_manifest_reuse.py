"""The CDN probe's static manifest must not be fetched twice before audio."""
import io
import logging

import pytest

from core import proxy as proxy_module
from services.soundcloud_service import SoundCloudService
from tests.helpers import app_core, proxy
from utils import url_safety

URL = 'https://playback.media-streaming.soundcloud.cloud/track/playlist.m3u8'
BODY = b'#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:10,\nsegment.aac\n#EXT-X-ENDLIST\n'


def probe_manifest(monkeypatch, body=BODY):
    calls = []
    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Type': 'application/vnd.apple.mpegurl', 'Content-Length': str(len(body))}
    def open_url(request, **kwargs):
        calls.append(request)
        return Response(body)
    monkeypatch.setattr(url_safety, 'guarded_open_url', open_url)
    service = SoundCloudService.__new__(SoundCloudService)
    service.logger = logging.getLogger(__name__)
    assert service._media_url_is_servable(URL)
    assert len(calls) == 1 and not calls[0].has_header('Range')
    return service


def test_probe_and_real_proxy_share_the_verified_vod_manifest(proxy, app_core, monkeypatch):
    service = probe_manifest(monkeypatch)
    app_core.soundcloud = service
    monkeypatch.setattr(proxy_module, '_is_ssrf_safe_url', lambda url: True)
    monkeypatch.setattr(proxy_module, '_safe_urlopen', lambda *a, **kw: pytest.fail('The manifest was already fetched'))
    response = proxy.get(proxy.url('/api/stream', url=URL, source='soundcloud', source_id='123'))
    assert response.status == 200
    assert b'#EXTM3U' in response.body and b'#EXT-X-ENDLIST' in response.body
    assert b'/?url=https%3A%2F%2F' in response.body and b'&k=test-proxy-token&resource=1' in response.body


@pytest.mark.parametrize('body', [BODY.replace(b'#EXT-X-ENDLIST\n', b''), b'audio bytes'])
def test_live_or_non_manifest_content_is_not_cached(monkeypatch, body):
    service = probe_manifest(monkeypatch, body)
    assert service.get_cached_manifest(URL) is None


def test_expired_signature_cannot_be_served_from_manifest_memo(monkeypatch):
    service = probe_manifest(monkeypatch)
    stale = URL + '?expires=1600000000'
    service._shared_manifests.set(stale, {'body': BODY, 'content_type': 'application/vnd.apple.mpegurl'})
    assert service.get_cached_manifest(stale) is None
