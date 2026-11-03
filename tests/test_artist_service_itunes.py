"""S4-002/S4-014: an iTunes-confirmed artist profile must not be an empty shell.

Pre-fix the profile shipped `tracks: []` (the page read "artist found, but no
tracks" and Play was a dead end), artwork stayed at 100x100 and every release
was labelled 'album' - singles included.
"""

from types import SimpleNamespace

import pytest

from services import artist_service as artist_service_module
from services.artist_service import ArtistService
from services.itunes_gateway import ITunesGateway


class FakeYT:
    def search(self, *a, **k):
        return []


@pytest.fixture
def svc():
    return ArtistService(FakeYT(), settings=None)


@pytest.fixture
def itunes(monkeypatch):
    calls = []
    def fake_get(url, session=None, timeout=4.0, deadline=None, is_current=None, settings=None):
        calls.append(url)
        if 'entity=song' in url:
            return {'results': [
                {'wrapperType': 'track', 'kind': 'song', 'trackId': 11, 'artistId': 77,
                 'artistName': 'Real Artist', 'trackName': 'Song One', 'collectionName': 'Album One',
                 'trackTimeMillis': 200000, 'artworkUrl100': 'https://x/100x100bb.jpg'},
                {'wrapperType': 'track', 'kind': 'song', 'trackId': 12, 'artistId': 77,
                 'artistName': 'Real Artist feat. Other', 'trackName': 'Song Two', 'trackTimeMillis': 1},
                {'wrapperType': 'track', 'kind': 'song', 'trackId': 13, 'artistId': 88,
                 'artistName': 'Someone Else', 'trackName': 'Not Theirs'},
                {'wrapperType': 'artist', 'artistId': 77, 'artistName': 'Real Artist'},
            ]}
        return {'results': []}
    monkeypatch.setattr(ITunesGateway, 'get', staticmethod(fake_get))
    return calls


def _itunes_profile(svc, monkeypatch):
    """Drive get_profile through the itunes branch without an executor hop."""
    raw = {'results': [
        {'wrapperType': 'artist', 'artistId': 77, 'artistName': 'Real Artist', 'primaryGenreName': 'Rock'},
        {'wrapperType': 'collection', 'collectionId': 500, 'artistId': 77, 'collectionName': 'Album One',
         'collectionType': 'Album', 'releaseDate': '2020-03-01', 'artworkUrl100': 'https://x/a100x100bb.jpg'},
        {'wrapperType': 'collection', 'collectionId': 501, 'artistId': 77, 'collectionName': 'Single One',
         'collectionType': 'Single', 'releaseDate': '2021-05-05', 'artworkUrl100': 'https://x/b100x100bb.jpg'},
        {'wrapperType': 'collection', 'collectionId': 502, 'artistId': 88, 'collectionName': 'Not Theirs',
         'collectionType': 'Album', 'artworkUrl100': 'https://x/c100x100bb.jpg'},
    ]}
    captured = {}
    svc.get_profile = lambda name, callback=None, error_callback=None, artist_ref=None, is_current=lambda: True: None
    # call the internals directly for a deterministic unit test
    albums = svc._collect_itunes_albums(raw, '77', 'Real Artist')
    tracks = svc._collect_itunes_tracks('77', is_current=lambda: True)
    captured['albums'], captured['tracks'] = albums, tracks
    return captured


def test_itunes_albums_are_upscaled_and_typed(svc, monkeypatch):
    data = _itunes_profile(svc, monkeypatch)
    albums = data['albums']
    assert [a['source_id'] for a in albums] == ['501', '500'], 'newest release first, other artists excluded'
    assert all(a['cover_url'].endswith('600x600bb.jpg') for a in albums), 'artwork must be upscaled from 100x100'
    types = {a['source_id']: a['type'] for a in albums}
    assert types == {'501': 'single', '500': 'album'}, 'singles must not be labelled album'
    assert {a['source_id']: a['album_type'] for a in albums} == {'501': 'Single', '500': 'Album'}


def test_itunes_tracks_are_collected_for_the_artist(svc, itunes):
    tracks = svc._collect_itunes_tracks('77', is_current=lambda: True)
    assert itunes and 'entity=song' in itunes[0], 'the song lookup must be issued'
    assert [t['title'] for t in tracks] == ['Song One', 'Song Two']
    assert all(t['source'] == 'spotify' for t in tracks)
    assert tracks[0]['source_id'] == 'ytsearch1: Real Artist - Song One'
    assert tracks[0]['duration'] == 200.0
    assert tracks[0]['cover_url'].endswith('600x600bb.jpg')


def test_itunes_tracks_exclude_other_artists(svc, itunes):
    tracks = svc._collect_itunes_tracks('77', is_current=lambda: True)
    assert all('Not Theirs' != t['title'] for t in tracks)


def test_itunes_tracks_lookup_failure_is_not_fatal(svc, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError('offline')
    monkeypatch.setattr(ITunesGateway, 'get', staticmethod(boom))
    assert svc._collect_itunes_tracks('77') == []


def test_itunes_tracks_require_numeric_id(svc, itunes):
    assert svc._collect_itunes_tracks('not-a-number') == []
    assert not itunes


def test_itunes_profile_payload_carries_tracks_and_genres(svc, itunes, monkeypatch):
    """The non-youtube branch assembles tracks and genres, not an empty shell."""
    resolved = {'status': 'found', 'source': 'itunes', 'source_id': '77',
                'name': 'Real Artist', 'profile_data': {'results': [
                    {'wrapperType': 'artist', 'artistId': 77, 'artistName': 'Real Artist',
                     'primaryGenreName': 'Rock'}]}}
    profile = svc._build_itunes_profile(resolved['profile_data'], '77', 'Real Artist')
    assert profile['status'] == 'found' and profile['source'] == 'itunes'
    assert profile['genres'] == 'Rock'
    assert [t['title'] for t in profile['tracks']] == ['Song One', 'Song Two']
    assert profile['albums'] == []
