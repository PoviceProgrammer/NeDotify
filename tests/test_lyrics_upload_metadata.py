"""YouTube upload title credits must reach identity-checked lyric providers."""
import json
import threading
import urllib.parse
from io import BytesIO

import pytest

from services.lyrics_service import LyricsService


@pytest.mark.parametrize('credit,offered_title,offered_artist,found', [
    ('PHARAON', 'BLACK SIEMENS', 'PHARAOH', True),
    ('PHARAON', 'BLACK SIEMENS', 'Other Artist', False),
    ('PHARAON', 'Different Song', 'PHARAOH', False),
    ('PHАRAON', 'BLACK SIEMENS', 'PHARAOH', False),  # Cyrillic homoglyph is not an alias.
])
def test_remix_upload_title_uses_verified_credit(monkeypatch, credit, offered_title, offered_artist, found):
    service = LyricsService()
    queries = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, *args):
            return json.dumps(self.payload).encode()

    def open_url(request, **kwargs):
        url = request.full_url
        if 'lrclib.net/' in url:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            queries.append(query)
            response = Response()
            # Independent provider fixtures, including an unrelated title twin.
            rows = [
                {'trackName': 'BLACK SIEMENS', 'artistName': 'Other Artist', 'duration': 120,
                 'plainLyrics': 'Wrong song'},
                {'trackName': offered_title, 'artistName': offered_artist, 'duration': 225,
                 'plainLyrics': 'Verified provider fixture', 'syncedLyrics': '[00:01] Verified provider fixture'},
            ]
            response.payload = rows if '/search?' in url else rows[0]
            return response
        raise ConnectionError('Provider intentionally offline')

    monkeypatch.setattr(service, '_open_url', open_url)
    result = service.get_lyrics(f'{credit} - BLACK SIEMENS (remix by NID)', 'BG Muz', 120000)
    if not found:
        assert result['status'] != 'found'
        assert not result['plainLyrics'] and not result['syncedLyrics']
        return
    assert result['status'] == 'found', {'result': result, 'queries': queries}
    assert result['matched_artist'] == 'PHARAOH'
    assert result['plainLyrics'] == 'Verified provider fixture'
    assert result['syncedLyrics'] is None
    assert result['match_type'] == 'base'
    assert queries[0]['artist_name'] == ['pharaoh']


@pytest.mark.parametrize('previous_status', ['not_found', 'unavailable'])
def test_upload_lookup_retries_previous_miss_after_service_restart(tmp_path, monkeypatch, previous_status):
    cache_path = tmp_path / 'lyrics.db'
    title, artist = 'PHARAON - BLACK SIEMENS (remix by NID)', 'BG Muz'
    previous = LyricsService(cache_path=cache_path)
    for name in ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(previous._lookup, name, lambda *args: None)
    if previous_status == 'unavailable':
        def offline(*args):
            raise ConnectionError('offline')
        monkeypatch.setattr(previous._lookup, 'lrclib', offline)
    assert previous.get_lyrics(title, artist, 120000)['status'] == previous_status

    restarted = LyricsService(cache_path=cache_path)
    requests = []
    def open_url(request, **kwargs):
        requests.append(request.full_url)
        if 'lrclib.net/' not in request.full_url:
            raise ConnectionError('Provider intentionally offline')
        row = {'trackName': 'BLACK SIEMENS', 'artistName': 'PHARAOH',
               'duration': 190, 'plainLyrics': 'Verified provider fixture'}
        payload = [row] if '/search?' in request.full_url else row
        return BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(restarted, '_open_url', open_url)
    actual = restarted.get_lyrics(title, artist, 120000)
    assert requests, 'A previous negative result must not suppress the corrected provider lookup'
    assert actual['status'] == 'found' and actual['matched_artist'] == 'PHARAOH'
    assert actual['plainLyrics'] == 'Verified provider fixture' and actual['syncedLyrics'] is None


def test_credited_remix_search_finishes_before_uploader_uses_provider_cap(monkeypatch):
    service = LyricsService()
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *args: None)
    requests = []
    uploader_started = threading.Event()

    def open_url(request, **kwargs):
        parsed = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(parsed.query)
        requests.append((parsed.path, query))
        if query.get('artist_name') == ['BG Muz'] and query.get('track_name') == ['PHARAON']:
            uploader_started.set()
        if parsed.path == '/api/get' and query.get('artist_name') == ['pharaoh']:
            # Let competing uploader jobs spend their requests while the
            # credited GET is pending. A correctly ordered batch has none.
            uploader_started.wait(1)
        row = {'trackName': 'BLACK SIEMENS', 'artistName': 'PHARAOH',
               'duration': 190, 'plainLyrics': 'Verified provider fixture'}
        if parsed.path == '/api/get':
            payload = {}  # Exact GETs miss; only the base-title search has text.
        else:
            payload = [row] if query.get('q') == ['pharaoh BLACK SIEMENS'] else []
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(service, '_open_url', open_url)
    actual = service.get_lyrics('PHARAON - BLACK SIEMENS (remix by NID)', 'BG Muz', 120000)
    assert actual['status'] == 'found', requests
    assert actual['matched_artist'] == 'PHARAOH' and actual['syncedLyrics'] is None
    assert requests == [
        ('/api/get', {'artist_name': ['pharaoh'], 'track_name': ['BLACK SIEMENS (remix by NID)'], 'duration': ['120']}),
        ('/api/search', {'q': ['pharaoh BLACK SIEMENS (remix by NID)']}),
        ('/api/get', {'artist_name': ['pharaoh'], 'track_name': ['BLACK SIEMENS']}),
        ('/api/search', {'q': ['pharaoh BLACK SIEMENS']}),
    ]
