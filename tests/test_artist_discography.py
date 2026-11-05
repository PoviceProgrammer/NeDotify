"""Current catalogue/profile contracts, plus retained MusicBrainz regressions.

Pre-port expectations for Spotify.get_artist_catalog, LastFM.artist_get_info,
ArtistService injected providers/get_discography and AppApi.get_artist_discography
are superseded by verified CatalogService identities and ArtistService.get_profile.
Original tests remain in tests/legacy_pre_parity for traceability.
"""
import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from services.musicbrainz_service import MusicBrainzService
from services.artist_service import ArtistService, clean_artist_bio
from services.catalog_service import CatalogService
from services.itunes_gateway import ITunesGateway

class TestMusicBrainzService(unittest.TestCase):
    def setUp(self):
        self.svc = MusicBrainzService()

    def test_search_artist_empty_name(self):
        self.assertIsNone(self.svc.search_artist(""))
        self.assertIsNone(self.svc.search_artist("   "))

    def test_search_artist_matching(self):
        mock_payload = {
            "artists": [
                {"id": "mbid-1", "name": "Queen", "type": "Group", "country": "GB", "tags": [{"name": "rock"}]},
                {"id": "mbid-2", "name": "Queen Latifah", "type": "Person", "country": "US", "tags": []},
            ]
        }
        with patch.object(self.svc, "_http_get_json", return_value=mock_payload):
            # Exact match prioritization
            res = self.svc.search_artist("Queen")
            self.assertIsNotNone(res)
            self.assertEqual(res["id"], "mbid-1")
            self.assertEqual(res["name"], "Queen")
            self.assertEqual(res["type"], "Group")
            self.assertIn("rock", res["tags"])

    def test_get_artist_release_groups_categorization(self):
        mock_rg_payload = {
            "release-groups": [
                {
                    "id": "rg-1",
                    "title": "A Night at the Opera",
                    "primary-type": "Album",
                    "secondary-types": [],
                    "first-release-date": "1975-11-21",
                },
                {
                    "id": "rg-2",
                    "title": "Bohemian Rhapsody",
                    "primary-type": "Single",
                    "secondary-types": [],
                    "first-release-date": "1975-10-31",
                },
                {
                    "id": "rg-3",
                    "title": "Queen EP",
                    "primary-type": "EP",
                    "secondary-types": [],
                    "first-release-date": "1977-05-20",
                },
                {
                    "id": "rg-4",
                    "title": "Greatest Hits",
                    "primary-type": "Album",
                    "secondary-types": ["Compilation"],
                    "first-release-date": "1981-11-02",
                },
            ]
        }
        with patch.object(self.svc, "_http_get_json", return_value=mock_rg_payload):
            res = self.svc.get_artist_release_groups("mbid-1", artist_name="Queen")
            self.assertEqual(len(res["albums"]), 1)
            self.assertEqual(res["albums"][0]["title"], "A Night at the Opera")
            self.assertEqual(res["albums"][0]["year"], 1975)
            self.assertEqual(res["albums"][0]["type"], "album")
            self.assertIn("coverartarchive.org", res["albums"][0]["cover_url"])

            self.assertEqual(len(res["singles"]), 1)
            self.assertEqual(res["singles"][0]["title"], "Bohemian Rhapsody")
            self.assertEqual(res["singles"][0]["type"], "single")

            self.assertEqual(len(res["eps"]), 1)
            self.assertEqual(res["eps"][0]["title"], "Queen EP")
            self.assertEqual(res["eps"][0]["type"], "ep")

            self.assertEqual(len(res["compilations"]), 1)
            self.assertEqual(res["compilations"][0]["title"], "Greatest Hits")
            self.assertEqual(res["compilations"][0]["type"], "compilation")

    def test_get_artist_bio_wikipedia_relations(self):
        mock_rel_payload = {
            "relations": [
                {"url": {"resource": "https://ru.wikipedia.org/wiki/Queen"}},
                {"url": {"resource": "https://en.wikipedia.org/wiki/Queen_(band)"}},
            ]
        }
        ru_wiki_summary = {"extract": "Queen — британская рок-группа.", "thumbnail": {"source": "https://img.ru/queen.jpg"}}
        en_wiki_summary = {"extract": "Queen are a British rock band.", "thumbnail": {"source": "https://img.en/queen.jpg"}}

        def fake_http_get(url, *args, **kwargs):
            if "musicbrainz.org" in url:
                return mock_rel_payload
            elif "ru.wikipedia.org" in url:
                return ru_wiki_summary
            elif "en.wikipedia.org" in url:
                return en_wiki_summary
            return None

        with patch.object(self.svc, "_http_get_json", side_effect=fake_http_get):
            bio = self.svc.get_artist_bio("mbid-queen", "Queen")
            self.assertEqual(bio["bio_ru"], "Queen — британская рок-группа.")
            self.assertEqual(bio["bio_en"], "Queen are a British rock band.")
            self.assertEqual(bio["bio"], "Queen — британская рок-группа.")
            self.assertEqual(bio["avatar_url"], "https://img.ru/queen.jpg")

    def test_rate_limiter_tokens(self):
        # Verify rate limiter acquires token and refills
        start = time.time()
        self.svc._acquire_rate_token()
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.5)


class TestMusicBrainzEdgeCases(unittest.TestCase):
    def test_sqlite_in_memory_cache_persistence(self):
        svc = MusicBrainzService()
        svc._db_path = ":memory:"
        svc._mem_conn = None
        svc._init_sqlite_cache_db()

        # Writing to in-memory DB must not crash
        svc._set_cached("test_key", {"val": 42}, ttl=60)
        # Clear local dict cache to force SQLite read
        with svc._cache_lock:
            svc._cache.clear()
        val = svc._get_cached("test_key")
        self.assertIsNotNone(val)
        self.assertEqual(val.get("val"), 42)

    def test_release_groups_without_caa_artwork(self):
        svc = MusicBrainzService()
        mock_rg_payload = {
            "release-groups": [
                {
                    "id": "rg-no-art",
                    "title": "No Art Album",
                    "primary-type": "Album",
                    "cover-art-archive": {"artwork": False, "front": False},
                }
            ]
        }
        with patch.object(svc, "_http_get_json", return_value=mock_rg_payload):
            res = svc.get_artist_release_groups("mbid-no-art", artist_name="Unknown")
            self.assertEqual(len(res["albums"]), 1)
            # Cover URL should be empty string when CAA explicitly reports no artwork
            self.assertEqual(res["albums"][0]["cover_url"], "")


def immediate_profile_service(monkeypatch):
    service = ArtistService()
    def submit(task):
        task()
        return object()
    monkeypatch.setattr(service, 'submit', submit)
    return service


def test_current_catalogue_keeps_unconfirmed_artist_names_as_choices():
    youtube = SimpleNamespace(_ytmusic=SimpleNamespace(search=lambda *args, **kwargs: [
        {'artist': 'Artist', 'browseId': 'UC-confirmed', 'thumbnails': [{'url': 'https://img/avatar.jpg'}]}]))
    catalogue = CatalogService(youtube)
    result = catalogue.resolve_artist('Artist', {'require_candidates': True})
    assert result['status'] == 'ambiguous'
    assert [(row['source'], row['source_id']) for row in result['candidates']] == [('youtube', 'UC-confirmed')]


def test_current_itunes_profile_deduplicates_verified_releases_and_tracks(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    artist = {'wrapperType': 'artist', 'artistId': 77, 'artistName': 'Artist', 'primaryGenreName': 'Rock'}
    album = {'wrapperType': 'collection', 'artistId': 77, 'collectionId': 101,
             'collectionName': 'Album', 'collectionType': 'Album', 'releaseDate': '2024-01-01',
             'artworkUrl100': 'https://img/100x100bb.jpg'}
    single = dict(album, collectionId=102, collectionName='Single', collectionType='Single')
    song = {'wrapperType': 'track', 'kind': 'song', 'artistId': 77, 'trackId': 201,
            'artistName': 'Artist', 'trackName': 'Song', 'trackTimeMillis': 210000}
    def get(url, **kwargs):
        query = parse_qs(urlsplit(url).query)
        if query.get('entity') == ['song']:
            return {'results': [song, song, dict(song, artistId=88, trackId=999)]}
        return {'results': [artist, album, album, single, dict(album, artistId=88, collectionId=999)]}
    monkeypatch.setattr(ITunesGateway, 'get', staticmethod(get))
    service = immediate_profile_service(monkeypatch)
    monkeypatch.setattr(service, '_resolve_metadata_fallback', lambda *args, **kwargs: ('https://img/artist.jpg', 'Биография исполнителя.'))
    result, errors = [], []
    service.get_profile('Artist', callback=result.append, error_callback=errors.append,
                        artist_ref={'source': 'itunes', 'source_id': '77'})
    assert not errors
    profile = result[0]
    assert profile['verified'] is True and profile['source_id'] == '77'
    assert [item['source_id'] for item in profile['albums']] == ['101', '102']
    assert {item['type'] for item in profile['albums']} == {'album', 'single'}
    assert profile['albums'][0]['cover_url'] == 'https://img/600x600bb.jpg'
    assert [(item['title'], item['duration']) for item in profile['tracks']] == [('Song', 210)]
    assert profile['bio_ru'] == profile['bio_original'] == 'Биография исполнителя.'


def test_profile_cache_uses_confirmed_source_identity_and_reports_missing_artist(monkeypatch):
    service = immediate_profile_service(monkeypatch)
    cached = {'status': 'found', 'verified': True, 'name': 'Confirmed', 'albums': [], 'tracks': []}
    service._cache_put('youtube:UC-confirmed', cached)
    monkeypatch.setattr(service.catalog, 'resolve_artist', lambda *args: {
        'status': 'found', 'name': 'Confirmed', 'source': 'youtube', 'source_id': 'UC-confirmed'})
    result = []
    service.get_profile('Alias Name', callback=result.append)
    assert result == [cached]
    monkeypatch.setattr(service.catalog, 'resolve_artist', lambda *args: {'status': 'not_found', 'error': 'Исполнитель не найден'})
    errors = []
    service.get_profile('Missing', error_callback=errors.append)
    assert errors == [{'status': 'not_found', 'artist': 'Missing', 'error': 'Исполнитель не найден'}]


def test_cancelled_profile_never_delivers_stale_callback(monkeypatch):
    service = immediate_profile_service(monkeypatch)
    monkeypatch.setattr(service.catalog, 'resolve_artist', lambda *args: {'status': 'not_found'})
    results = []
    service.get_profile('Artist', callback=results.append, error_callback=results.append, is_current=lambda: False)
    assert results == []


def test_lastfm_biography_fallback_uses_current_metadata_path_and_strips_boilerplate(monkeypatch):
    from services.deezer_service import DeezerService
    from services.lastfm_service import LastFMService
    service = ArtistService()
    monkeypatch.setattr(DeezerService, 'get_artist', lambda *args: {'avatar_url': 'https://img/artist.jpg'})
    monkeypatch.setattr('urllib.request.urlopen', MagicMock(side_effect=OSError('offline Wikipedia')))
    monkeypatch.setattr(LastFMService, 'is_enabled', lambda self: True)
    monkeypatch.setattr(LastFMService, '_resolve_api_keys', lambda self: ['test-key'])
    monkeypatch.setattr(LastFMService, '_api_request', lambda *args, **kwargs: {'artist': {'bio': {'content':
        'Artist &amp; band.<br>Second paragraph. <a href="https://last.fm">Read more on Last.fm</a> User-contributed text is available under the Creative Commons By-SA License.'}}})
    avatar, bio = service._resolve_metadata_fallback('Artist')
    assert avatar == 'https://img/artist.jpg'
    assert bio == 'Artist & band.\nSecond paragraph.'


def test_bilingual_bio_preserves_original_when_translation_fails(monkeypatch):
    from services.lyrics_service import LyricsService
    service = ArtistService()
    monkeypatch.setattr(LyricsService, 'translate_lyrics', lambda *args, **kwargs: 'Перевод биографии.')
    assert service._translate_bio('Original biography.') == ('Перевод биографии.', 'Original biography.')
    monkeypatch.setattr(LyricsService, 'translate_lyrics', MagicMock(side_effect=OSError('offline')))
    assert service._translate_bio('Original biography.') == ('Original biography.', 'Original biography.')

