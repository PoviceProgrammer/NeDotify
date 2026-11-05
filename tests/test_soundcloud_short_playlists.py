"""SoundCloud share links reach the normal playlist importer safely."""
from contextlib import contextmanager
from types import SimpleNamespace
import logging
import urllib.error

import pytest

from services.playlist_import_service import PlaylistImportService, PlaylistImportError
from tests.test_onboarding_ui import onboarding_js


SHORT = 'https://on.soundcloud.com/OPwcYGr0dlWx1Ss8Yx'
CANONICAL = 'https://soundcloud.com/artist/sets/playlist?ref=clipboard&p=i'


def resolver(monkeypatch, final=CANONICAL):
    opened, extracted = [], []
    monkeypatch.setattr('utils.url_safety.safe_public_url', lambda url: True)

    @contextmanager
    def open_share(url, **kwargs):
        opened.append(getattr(url, 'full_url', url))
        class Response:
            def geturl(self): return final
        yield Response()
    monkeypatch.setattr('utils.url_safety.guarded_open_url', open_share)
    service = PlaylistImportService()
    def extract(url):
        extracted.append(url)
        return {'source':'soundcloud', 'name':'Shared playlist', 'tracks':[{'source_id':'123'}]}
    monkeypatch.setattr(service, '_resolve_soundcloud', extract)
    return service, opened, extracted


def test_soundcloud_short_playlist_resolves_before_extraction(monkeypatch):
    service, opened, extracted = resolver(monkeypatch)
    result = service.resolve(SHORT)
    assert result['source'] == 'soundcloud'
    assert opened == [SHORT]
    assert extracted == [CANONICAL]


def test_short_playlist_is_accepted_during_first_run():
    onboarding_js("assert.equal(subject.validatePlaylistUrl('" + SHORT + "'), '');")


@pytest.mark.parametrize('target', [
    'https://example.com/artist/sets/list',
    'https://soundcloud.com.evil.test/artist/sets/list',
    'https://soundcloud.com/artist/track',
    'https://user:password@soundcloud.com/artist/sets/list',
    'file:///artist/sets/list',
])
def test_share_redirect_cannot_select_another_service_or_a_track(monkeypatch, target):
    service, opened, extracted = resolver(monkeypatch, target)
    with pytest.raises(PlaylistImportError):
        service.resolve(SHORT)
    assert opened == [SHORT]
    assert extracted == []


def test_playlist_details_use_the_resolved_url_and_keep_the_source(monkeypatch):
    resolver(monkeypatch)
    from services.soundcloud_service import SoundCloudService
    service = SoundCloudService.__new__(SoundCloudService)
    service.settings = None
    service.logger = logging.getLogger(__name__)
    service._executor = SimpleNamespace(submit=lambda callback: callback())
    service.get_search_cache = lambda key: None
    service.set_search_cache = lambda *args: None
    service._get_client_id = lambda: 'test-client'
    requested = []
    def get(url, **kwargs):
        requested.append(url)
        return SimpleNamespace(status_code=200, json=lambda:{'tracks':[
            {'id':123, 'title':'Song', 'duration':180000, 'user':{'username':'Artist'}}]})
    service._api_get = get
    received = []
    service.get_playlist_tracks(SHORT, callback=received.append)
    assert received[0][0]['source'] == 'soundcloud'
    assert received[0][0]['title'] == 'Song'
    assert len(requested) == 1
    assert 'on.soundcloud.com' not in requested[0]
    assert 'soundcloud.com/artist/sets/playlist' in urllib.parse.unquote(requested[0])


def test_failed_share_resolution_never_starts_extraction(monkeypatch):
    service, _, extracted = resolver(monkeypatch)
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError('connection timed out')
    monkeypatch.setattr('utils.url_safety.guarded_open_url', unavailable)
    with pytest.raises(urllib.error.URLError):
        service.resolve(SHORT)
    assert extracted == []


def test_first_run_rejects_share_host_lookalikes_and_invalid_tokens():
    onboarding_js(r"""
for (const url of ['https://on.soundcloud.com.evil.test/token', 'https://on.soundcloud.com/',
 'https://on.soundcloud.com/token/more', 'https://user:password@on.soundcloud.com/token'])
    assert.ok(subject.validatePlaylistUrl(url), url);
""")
