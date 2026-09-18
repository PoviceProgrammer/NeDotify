"""
Tests for Full Artist Discography & Biography Integration
Covers:
- MusicBrainzService (search, release groups, rate limiting, Wikipedia bios, CAA covers)
- LastFMService (artist_get_info, artist_get_top_albums, HTML stripping, listeners/tags)
- SpotifyService (get_artist_catalog, Web API + iTunes fallback, singles/EPs/albums)
- ArtistService (multi-source cascade, deduplication, bilingual bio, avatar resolution, caching)
"""

import unittest
from unittest.mock import MagicMock, patch
import threading
import time

from services.musicbrainz_service import MusicBrainzService
from services.lastfm_service import LastFMService
from services.spotify_service import SpotifyService
from services.artist_service import ArtistService


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


class TestLastFMArtistIntegration(unittest.TestCase):
    def setUp(self):
        self.svc = LastFMService()

    def test_artist_get_info_html_stripping_and_parsing(self):
        mock_payload = {
            "artist": {
                "name": "Pink Floyd",
                "bio": {
                    "summary": 'Pink Floyd were an English rock band. <a href="https://last.fm">Read more on Last.fm</a>',
                    "content": 'Pink Floyd were an English rock band formed in London in 1965. <a href="https://last.fm">User-contributed text</a>',
                },
                "stats": {"listeners": "4500000", "playcount": "150000000"},
                "tags": {"tag": [{"name": "progressive rock"}, {"name": "classic rock"}]},
                "image": [{"#text": "https://lastfm.freetls.fastly.net/image.png", "size": "extralarge"}],
            }
        }
        with patch.object(self.svc, "_api_request", return_value=mock_payload):
            res = self.svc.artist_get_info("Pink Floyd", lang="en")
            self.assertEqual(res["name"], "Pink Floyd")
            self.assertNotIn("<a", res["bio_summary"])
            self.assertNotIn("<a", res["bio_content"])
            self.assertIn("English rock band", res["bio_content"])
            self.assertEqual(res["listeners"], 4500000)
            self.assertEqual(res["playcount"], 150000000)
            self.assertIn("progressive rock", res["tags"])
            self.assertEqual(res["image"], "https://lastfm.freetls.fastly.net/image.png")

    def test_artist_get_top_albums(self):
        mock_payload = {
            "topalbums": {
                "album": [
                    {"name": "The Dark Side of the Moon", "playcount": "5000000", "image": [{"#text": "https://img/dsotm.jpg"}]},
                    {"name": "Wish You Were Here", "playcount": "4000000", "image": [{"#text": "https://img/wywh.jpg"}]},
                ]
            }
        }
        with patch.object(self.svc, "_api_request", return_value=mock_payload):
            albums = self.svc.artist_get_top_albums("Pink Floyd", limit=10)
            self.assertEqual(len(albums), 2)
            self.assertEqual(albums[0]["title"], "The Dark Side of the Moon")
            self.assertEqual(albums[0]["source"], "lastfm")
            self.assertEqual(albums[0]["type"], "album")
            self.assertEqual(albums[0]["cover"], "https://img/dsotm.jpg")

    def test_artist_handler_proxy_calls(self):
        with patch.object(self.svc, "artist_get_info", return_value={"name": "Test"}) as mock_info:
            res = self.svc.artist.getInfo("Test")
            self.assertEqual(res["name"], "Test")
            mock_info.assert_called_once_with("Test", lang="ru")

        with patch.object(self.svc, "artist_get_top_albums", return_value=[{"title": "Alb"}]) as mock_alb:
            res = self.svc.artist.getTopAlbums("Test", limit=20)
            self.assertEqual(len(res), 1)
            mock_alb.assert_called_once_with("Test", limit=20)


class TestSpotifyArtistCatalog(unittest.TestCase):
    def setUp(self):
        self.svc = SpotifyService()

    def test_get_artist_catalog_empty(self):
        res = self.svc.get_artist_catalog("")
        self.assertEqual(res["albums"], [])
        self.assertEqual(res["singles"], [])
        self.assertEqual(res["eps"], [])

    def test_get_artist_catalog_itunes_fallback(self):
        itunes_album_payload = {
            "results": [
                {
                    "collectionId": 1001,
                    "collectionName": "Album One",
                    "artistName": "Artist A",
                    "collectionType": "Album",
                    "trackCount": 10,
                    "releaseDate": "2023-01-01T08:00:00Z",
                    "artworkUrl100": "https://img/100x100bb.jpg",
                },
                {
                    "collectionId": 1002,
                    "collectionName": "Single One - Single",
                    "artistName": "Artist A",
                    "collectionType": "Album",
                    "trackCount": 1,
                    "releaseDate": "2023-05-01T08:00:00Z",
                    "artworkUrl100": "https://img/100x100bb.jpg",
                },
                {
                    "collectionId": 1003,
                    "collectionName": "Mini Album - EP",
                    "artistName": "Artist A",
                    "collectionType": "Album",
                    "trackCount": 5,
                    "releaseDate": "2023-08-01T08:00:00Z",
                    "artworkUrl100": "https://img/100x100bb.jpg",
                },
                {
                    "collectionId": 1004,
                    "collectionName": "Best Hits",
                    "artistName": "Artist A",
                    "collectionType": "Compilation",
                    "trackCount": 20,
                    "releaseDate": "2024-01-01T08:00:00Z",
                    "artworkUrl100": "https://img/100x100bb.jpg",
                },
            ]
        }
        itunes_song_payload = {
            "results": [
                {
                    "trackId": 5001,
                    "trackName": "Hit Song",
                    "artistName": "Artist A",
                    "collectionName": "Album One",
                    "trackTimeMillis": 210000,
                    "artworkUrl100": "https://img/100x100bb.jpg",
                }
            ]
        }

        with patch.object(self.svc, "get_access_token", return_value=None):
            with patch("services.spotify_service._session.get") as mock_get:
                def fake_get(url, *args, **kwargs):
                    m = MagicMock()
                    m.status_code = 200
                    if "entity=album" in url:
                        m.json.return_value = itunes_album_payload
                    elif "entity=song" in url:
                        m.json.return_value = itunes_song_payload
                    else:
                        m.json.return_value = {"results": []}
                    return m

                mock_get.side_effect = fake_get
                catalog = self.svc.get_artist_catalog("Artist A")

                self.assertEqual(len(catalog["albums"]), 1)
                self.assertEqual(catalog["albums"][0]["title"], "Album One")
                self.assertEqual(catalog["albums"][0]["type"], "album")
                self.assertEqual(catalog["albums"][0]["cover"], "https://img/600x600bb.jpg")

                self.assertEqual(len(catalog["singles"]), 1)
                self.assertEqual(catalog["singles"][0]["title"], "Single One - Single")
                self.assertEqual(catalog["singles"][0]["type"], "single")

                self.assertEqual(len(catalog["eps"]), 1)
                self.assertEqual(catalog["eps"][0]["title"], "Mini Album - EP")
                self.assertEqual(catalog["eps"][0]["type"], "ep")

                self.assertEqual(len(catalog["compilations"]), 1)
                self.assertEqual(catalog["compilations"][0]["title"], "Best Hits")
                self.assertEqual(catalog["compilations"][0]["type"], "compilation")

                self.assertEqual(len(catalog["tracks"]), 1)
                self.assertEqual(catalog["tracks"][0]["title"], "Hit Song")
                self.assertEqual(catalog["tracks"][0]["duration"], 210)


class TestArtistServiceMultiSourceCascade(unittest.TestCase):
    def setUp(self):
        self.mock_spotify = MagicMock(spec=SpotifyService)
        self.mock_lastfm = MagicMock(spec=LastFMService)
        self.mock_musicbrainz = MagicMock(spec=MusicBrainzService)
        self.mock_youtube = MagicMock()

        self.svc = ArtistService(
            youtube_service=self.mock_youtube,
            settings={},
            spotify_service=self.mock_spotify,
            lastfm_service=self.mock_lastfm,
            musicbrainz_service=self.mock_musicbrainz,
        )

    def test_cascade_merges_albums_singles_eps_and_bio(self):
        # Mock Spotify Catalog
        self.mock_spotify.get_artist_catalog.return_value = {
            "albums": [
                {"id": "sp_1", "title": "Great Album", "year": 2022, "type": "album", "cover": "https://sp.img/alb.jpg"},
            ],
            "singles": [
                {"id": "sp_2", "title": "Fresh Single", "year": 2023, "type": "single", "cover": "https://sp.img/sng.jpg"},
            ],
            "eps": [
                {"id": "sp_3", "title": "Debut EP", "year": 2021, "type": "ep", "cover": "https://sp.img/ep.jpg"},
            ],
            "compilations": [],
            "tracks": [
                {"id": "sp_t1", "title": "Track One", "artist": "Mega Artist", "album": "Great Album", "duration": 180},
            ],
            "avatar_url": "https://sp.img/avatar_hd.jpg",
            "genres": "Rock, Indie",
        }

        # Mock Last.fm
        self.mock_lastfm.artist_get_info.return_value = {
            "bio_summary": "Известный рок-музыкант.",
            "bio_content": "Известный рок-музыкант, начавший карьеру в 2020 году.",
            "listeners": 1200000,
            "playcount": 50000000,
            "tags": ["rock", "indie"],
            "image": "https://lastfm.img/artist.jpg",
        }
        self.mock_lastfm.artist_get_top_albums.return_value = []

        # Mock MusicBrainz
        self.mock_musicbrainz.search_artist.return_value = {"id": "mbid-mega"}
        self.mock_musicbrainz.get_artist_release_groups.return_value = {
            "albums": [
                {"id": "mb_1", "title": "Great Album", "year": 2022, "type": "album"},
                {"id": "mb_2", "title": "Rare Album", "year": 2020, "type": "album"},
            ],
            "singles": [],
            "eps": [],
            "compilations": [],
        }
        self.mock_musicbrainz.get_artist_bio.return_value = {
            "bio_ru": "Известный рок-музыкант.",
            "bio_en": "Famous rock musician.",
            "bio": "Известный рок-музыкант.",
            "avatar_url": "",
            "source": "wikipedia",
        }

        # Mock YouTube Music (unavailable/failing to test resilience)
        self.mock_youtube._ytmusic.return_value = None

        result = None
        event = threading.Event()

        def on_ready(profile):
            nonlocal result
            result = profile
            event.set()

        self.svc.get_profile("Mega Artist", callback=on_ready)
        event.wait(timeout=2.0)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Mega Artist")
        self.assertEqual(result["avatar_url"], "https://sp.img/avatar_hd.jpg")
        self.assertIn("рок-музыкант", result["bio_ru"])
        self.assertEqual(result["listeners"], 1200000)

        # Check discography categorization
        self.assertGreaterEqual(len(result["albums"]), 2)  # Great Album and Rare Album
        self.assertGreaterEqual(len(result["singles"]), 1)  # Fresh Single
        self.assertGreaterEqual(len(result["eps"]), 1)      # Debut EP
        self.assertIn("albums", result["discography"])
        self.assertIn("singles", result["discography"])
        self.assertIn("eps", result["discography"])

        # Check tracks
        self.assertGreaterEqual(len(result["tracks"]), 1)
        self.assertEqual(result["tracks"][0]["title"], "Track One")

    def test_cache_hit(self):
        # Prime cache
        cached_data = {"name": "Cached Artist", "albums": [], "tracks": [], "bio": "Cached"}
        self.svc._cache_put("cached artist", cached_data)

        res = None
        event = threading.Event()
        self.svc.get_profile("Cached Artist", callback=lambda p: (event.set(), globals().update(res=p)))
        event.wait(timeout=1.0)

        # Provider calls should not have been made
        self.mock_spotify.get_artist_catalog.assert_not_called()
        self.mock_musicbrainz.search_artist.assert_not_called()

    def test_artist_not_found_invokes_error_callback(self):
        self.mock_spotify.get_artist_catalog.return_value = {}
        self.mock_lastfm.artist_get_info.return_value = {}
        self.mock_lastfm.artist_get_top_albums.return_value = []
        self.mock_musicbrainz.search_artist.return_value = None
        self.mock_musicbrainz.get_artist_release_groups.return_value = {}
        self.mock_musicbrainz.get_artist_bio.return_value = {}
        self.mock_youtube._ytmusic.return_value = None

        err = []
        event = threading.Event()

        self.svc.get_profile("NonExistentArtistXYZ", error_callback=lambda msg: (err.append(msg), event.set()))
        event.wait(timeout=2.0)

        self.assertTrue(len(err) > 0)
        self.assertIn("Исполнитель не найден", err[0])

    def test_avatar_priority_cascade(self):
        self.mock_spotify.get_artist_catalog.return_value = {
            "albums": [{"title": "Alb", "year": 2020}],
            "avatar_url": "https://sp.img/hq.jpg",
        }
        self.mock_lastfm.artist_get_info.return_value = {"image": "https://lastfm.img/med.jpg"}
        self.mock_lastfm.artist_get_top_albums.return_value = []
        self.mock_musicbrainz.search_artist.return_value = None
        self.mock_musicbrainz.get_artist_release_groups.return_value = {}
        self.mock_musicbrainz.get_artist_bio.return_value = {"avatar_url": "https://wiki.img/wiki.jpg"}
        self.mock_youtube._ytmusic.return_value = None

        res = None
        event = threading.Event()

        def on_ready(p):
            nonlocal res
            res = p
            event.set()

        self.svc.get_profile("Avatar Priority Artist", callback=on_ready)
        event.wait(timeout=2.0)

        # Spotify avatar should win over Wiki and Last.fm
        self.assertIsNotNone(res)
        self.assertEqual(res["avatar_url"], "https://sp.img/hq.jpg")

    def test_bio_resolution_bilingual(self):
        self.mock_spotify.get_artist_catalog.return_value = {"albums": [{"title": "A"}]}
        self.mock_lastfm.artist_get_info.return_value = {
            "bio_content": "Популярный российский хип-хоп исполнитель.",
        }
        self.mock_lastfm.artist_get_top_albums.return_value = []
        self.mock_musicbrainz.search_artist.return_value = None
        self.mock_musicbrainz.get_artist_release_groups.return_value = {}
        self.mock_musicbrainz.get_artist_bio.return_value = {
            "bio_en": "Popular Russian hip-hop artist.",
            "bio_ru": "",
        }
        self.mock_youtube._ytmusic.return_value = None

        res = None
        event = threading.Event()

        def on_ready(p):
            nonlocal res
            res = p
            event.set()

        self.svc.get_profile("Bilingual Artist", callback=on_ready)
        event.wait(timeout=2.0)

        self.assertIsNotNone(res)
        self.assertIn("российский", res["bio_ru"])
        self.assertIn("Popular", res["bio_en"])
        self.assertEqual(res["bio_source"], "lastfm")

    def test_merge_discography_deduplication_and_yt_lookup(self):
        sp_data = {
            "albums": [
                {"title": "Abbey Road", "year": 1969, "cover": "https://sp.img/abbey.jpg"},
            ],
            "singles": [
                {"title": "Let It Be - Single", "year": 1970, "cover": ""},
            ],
            "eps": [],
            "compilations": [],
        }
        mb_releases = {
            "albums": [
                {"title": "Abbey Road", "year": 1969, "cover": "https://mb.img/abbey_caa.jpg"},
            ],
            "singles": [
                {"title": "Let It Be", "year": 1970, "cover": "https://mb.img/letitbe.jpg"},
            ],
            "eps": [],
            "compilations": [],
        }
        yt_albums = [
            {"title": "Abbey Road", "source_id": "MPREb_abbey", "type": "album"},
            {"title": "Let It Be", "source_id": "MPREb_letitbe", "type": "single"},
        ]

        merged = self.svc._merge_discography(sp_data, mb_releases, [], yt_albums, "The Beatles")
        # Deduplicated: Abbey Road appears once
        self.assertEqual(len(merged["albums"]), 1)
        self.assertEqual(merged["albums"][0]["title"], "Abbey Road")
        # YouTube browse_id attached
        self.assertEqual(merged["albums"][0]["yt_source_id"], "MPREb_abbey")

        # Let It Be title cleaned and deduplicated
        self.assertEqual(len(merged["singles"]), 1)
        self.assertEqual(merged["singles"][0]["title"], "Let It Be")
        self.assertEqual(merged["singles"][0]["yt_source_id"], "MPREb_letitbe")
        # Cover updated from MB since SP cover was empty
        self.assertEqual(merged["singles"][0]["cover"], "https://mb.img/letitbe.jpg")


if __name__ == "__main__":
    unittest.main()
