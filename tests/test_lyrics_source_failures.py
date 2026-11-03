"""Rich source failures must leave existing lyrics and bounded retry intact."""
import time
import urllib.error

import pytest

from services.lyrics_service import LyricsService

pytestmark = pytest.mark.rich_lyrics


@pytest.mark.parametrize('code', [401, 429, 'timeout'])
def test_rich_api_errors_do_not_block_existing_plain_source(monkeypatch, code):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *args: None)
    def original(form, *args):
        return service._lookup.accept(form, 'A Song', 'Artist', 120, None, 'Hello', 'Existing')
    monkeypatch.setattr(service._lookup, 'lrclib', original)
    calls = []
    def unavailable(req, **kwargs):
        calls.append(req.full_url)
        if code == 'timeout':
            raise TimeoutError('fixture timeout')
        raise urllib.error.HTTPError(req.full_url, code, 'fixture failure', {'Retry-After': '20'}, None)
    monkeypatch.setattr(service, '_open_url', unavailable)
    result = service.get_lyrics('A Song', 'Artist', 120000, album_name='Album',
                                source='youtube', source_id='abcdefghijk')
    assert result['plainLyrics'] == 'Hello' and result['source'] == 'Existing'
    assert len(calls) <= 3


def test_retry_after_cools_down_host_without_sleeping(monkeypatch):
    service = LyricsService()
    calls = []
    def limited(req, **kwargs):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, 'limited', {'Retry-After': '120'}, None)
    monkeypatch.setattr(service, '_open_url', limited)
    with pytest.raises(urllib.error.HTTPError):
        service._lookup._read('https://unison.boidu.dev/lyrics?song=First', time.monotonic() + 8)
    with pytest.raises(TimeoutError):
        service._lookup._read('https://unison.boidu.dev/lyrics?song=Second', time.monotonic() + 8)
    assert len(calls) == 1
