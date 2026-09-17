import time
import threading
import unittest
from unittest.mock import MagicMock, patch

from services.soundcloud_service import SoundCloudService, _TTLCache
from services.spotify_service import SpotifyService, _cached_spotify_search, _cached_spotify_album_search


class TestTTLCache(unittest.TestCase):
    def test_ttl_cache_lru_and_expiry(self):
        cache = _TTLCache(max_entries=3, ttl_seconds=0.1)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        self.assertEqual(len(cache), 3)

        # Access "a" to make "b" least recently used
        self.assertEqual(cache.get("a"), 1)
        cache.set("d", 4)
        self.assertEqual(len(cache), 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("d"), 4)

        # Wait for TTL expiry
        time.sleep(0.12)
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.get("d"))

    def test_ttl_cache_thread_safety(self):
        cache = _TTLCache(max_entries=50, ttl_seconds=10)
        errors = []

        def worker(w_id):
            try:
                for i in range(100):
                    cache.set(f"k_{w_id}_{i}", i)
                    cache.get(f"k_{w_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestSoundCloudServiceUnit(unittest.TestCase):
    def setUp(self):
        self.sc = SoundCloudService()

    def test_search_empty_query_returns_empty_list(self):
        result = []
        event = threading.Event()

        def cb(tracks):
            result.extend(tracks)
            event.set()

        self.sc.search("", callback=cb)
        event.wait(timeout=2.0)
        self.assertEqual(result, [])

    def test_search_null_payload_resilience(self):
        # API returns tracks with null user, null artwork_url, null duration
        fake_api_response = {
            "collection": [
                {
                    "id": 12345,
                    "title": None,
                    "user": None,  # Bug BUG-017: causes AttributeError if user.get()
                    "duration": None,
                    "artwork_url": None,
                    "permalink_url": "https://soundcloud.com/artist/track",
                    "waveform_url": None
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_api_response

        with patch.object(self.sc, "_get_client_id", return_value="fake_cid"), \
             patch.object(self.sc._session, "get", return_value=mock_resp):
            event = threading.Event()
            res_tracks = []

            def cb(tracks):
                res_tracks.extend(tracks)
                event.set()

            self.sc.search("test query", callback=cb)
            event.wait(timeout=2.0)

            self.assertEqual(len(res_tracks), 1)
            t = res_tracks[0]
            self.assertEqual(t["source_id"], "12345")
            self.assertEqual(t["artist"], "SoundCloud Artist")
            self.assertEqual(t["duration"], 0)
            self.assertEqual(t["title"], "Unknown Title")

    def test_get_playlist_tracks_null_payload(self):
        fake_resp = {
            "tracks": [
                {
                    "id": 999,
                    "title": "Song In Playlist",
                    "user": None,
                    "duration": None,
                    "artwork_url": None
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_resp

        with patch.object(self.sc, "_get_client_id", return_value="fake_cid"), \
             patch.object(self.sc._session, "get", return_value=mock_resp):
            event = threading.Event()
            res_tracks = []

            def cb(tracks):
                res_tracks.extend(tracks)
                event.set()

            self.sc.get_playlist_tracks("12345", callback=cb)
            event.wait(timeout=2.0)

            self.assertEqual(len(res_tracks), 1)
            self.assertEqual(res_tracks[0]["artist"], "SoundCloud Artist")

    def test_get_stream_url_null_media_and_user(self):
        # Track data has null media, transcodings, and user
        track_resp = MagicMock()
        track_resp.status_code = 200
        track_resp.json.return_value = {
            "id": 555,
            "title": "Stream Track",
            "user": None,
            "duration": None,
            "media": {
                "transcodings": [
                    {"url": "https://api-v2.soundcloud.com/tc1", "format": {"protocol": "progressive"}}
                ]
            }
        }

        tc_resp = MagicMock()
        tc_resp.status_code = 200
        tc_resp.json.return_value = {"url": "https://cf-media.sndcdn.com/audio.mp3"}

        def mock_get(url, *args, **kwargs):
            if "tracks/555" in url:
                return track_resp
            elif "tc1" in url:
                return tc_resp
            return MagicMock(status_code=404)

        with patch.object(self.sc, "_get_client_id", return_value="fake_cid"), \
             patch.object(self.sc._session, "get", side_effect=mock_get):
            event = threading.Event()
            resolved = {}

            def cb(url, meta):
                resolved["url"] = url
                resolved["meta"] = meta
                event.set()

            self.sc.get_stream_url("555", callback=cb)
            event.wait(timeout=2.0)

            self.assertEqual(resolved.get("url"), "https://cf-media.sndcdn.com/audio.mp3")
            self.assertEqual(resolved.get("meta", {}).get("artist"), "Unknown")

    def test_get_related_tracks_sync_null_user(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "collection": [
                {"id": 777, "title": "Related Song", "user": None, "duration": None}
            ]
        }
        with patch.object(self.sc, "_get_client_id", return_value="fake_cid"), \
             patch.object(self.sc._session, "get", return_value=mock_resp):
            tracks = self.sc.get_related_tracks_sync("777", limit=5)
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0]["artist"], "SoundCloud Artist")

    def test_get_waveform_data_sync_normalization_and_sampling(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 200 raw samples with non-numeric / dirty values
        mock_resp.json.return_value = {
            "height": 100,
            "samples": [i for i in range(200)]
        }
        with patch.object(self.sc._session, "get", return_value=mock_resp):
            wave = self.sc.get_waveform_data_sync("https://wave.sndcdn.com/test.json")
            self.assertEqual(len(wave), 100)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in wave))

    def test_soundcloud_empty_and_none_guards(self):
        # Empty track_url must call error_callback immediately without throwing or calling yt-dlp
        event = threading.Event()
        errs = []
        self.sc.get_stream_url("", error_callback=lambda e: (errs.append(e), event.set()))
        event.wait(timeout=1.0)
        self.assertTrue(len(errs) > 0)

        # None playlist_id must call error_callback and return empty without hang
        event2 = threading.Event()
        errs2 = []
        self.sc.get_playlist_tracks(None, error_callback=lambda e: (errs2.append(e), event2.set()))
        event2.wait(timeout=1.0)
        self.assertTrue(len(errs2) > 0)


class TestSpotifyServiceUnit(unittest.TestCase):
    def setUp(self):
        self.spotify = SpotifyService()

    def test_spotify_available(self):
        self.assertTrue(self.spotify.available)

    def test_spotify_search_none_or_empty_query(self):
        # Empty query should return empty without exception
        event = threading.Event()
        res = []

        def cb(tracks):
            res.extend(tracks)
            event.set()

        self.spotify.search("", callback=cb)
        event.wait(timeout=2.0)
        self.assertEqual(res, [])

        # None query must not crash with quote() doesn't support None
        event2 = threading.Event()
        res2 = []
        self.spotify.search(None, callback=lambda t: (res2.extend(t), event2.set()))
        event2.wait(timeout=2.0)
        self.assertEqual(res2, [])

    def test_spotify_search_null_fields_resilience(self):
        # Bug BUG-018: trackTimeMillis is None or artworkUrl100 is None
        fake_itunes_resp = {
            "results": [
                {
                    "trackId": 9999,
                    "trackName": "Spotify Hit",
                    "artistName": "Hit Artist",
                    "collectionName": None,
                    "trackTimeMillis": None,  # Bug BUG-018: None / 1000 causes TypeError
                    "artworkUrl100": None,    # Bug BUG-018: None.replace causes AttributeError
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_itunes_resp

        with patch("services.spotify_service._session.get", return_value=mock_resp):
            tracks = _cached_spotify_search("test_unique_search_query_123", limit=10)
            self.assertEqual(len(tracks), 1)
            t = tracks[0]
            self.assertEqual(t[1], "Spotify Hit")
            self.assertEqual(t[2], "Hit Artist")
            self.assertEqual(t[4], 180)  # Default duration
            self.assertIsNone(t[5])      # artworkUrl100 is None

    def test_spotify_album_search_null_fields_resilience(self):
        fake_album_resp = {
            "results": [
                {
                    "collectionId": 8888,
                    "collectionName": "Hit Album",
                    "artistName": None,
                    "releaseDate": None,
                    "trackCount": None,
                    "artworkUrl100": None
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_album_resp

        with patch("services.spotify_service._session.get", return_value=mock_resp):
            albums = _cached_spotify_album_search("test_unique_album_query_456", limit=5)
            self.assertEqual(len(albums), 1)
            alb = albums[0]
            self.assertEqual(alb[1], "Hit Album")
            self.assertEqual(alb[2], "Unknown Artist")
            self.assertEqual(alb[4], 0)
            self.assertIsNone(alb[5])

    def test_get_album_tracks_null_fields(self):
        fake_tracks_resp = {
            "results": [
                {"wrapperType": "collection"},  # Header item
                {
                    "wrapperType": "track",
                    "kind": "song",
                    "trackId": 777,
                    "trackName": "Song In Album",
                    "artistName": None,
                    "trackTimeMillis": None,
                    "artworkUrl100": None
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_tracks_resp

        with patch("services.spotify_service._session.get", return_value=mock_resp):
            event = threading.Event()
            res_tracks = []

            def cb(tracks):
                res_tracks.extend(tracks)
                event.set()

            self.spotify.get_album_tracks("8888", callback=cb)
            event.wait(timeout=2.0)

            self.assertEqual(len(res_tracks), 1)
            self.assertEqual(res_tracks[0]["title"], "Song In Album")
            self.assertEqual(res_tracks[0]["duration"], 180)
            self.assertIsNone(res_tracks[0]["cover_url"])

    def test_get_stream_url_graceful_error(self):
        # SpotifyService must report error gracefully via error_callback without raising NotImplementedError
        event = threading.Event()
        err_msg = []

        def err_cb(msg):
            err_msg.append(msg)
            event.set()

        self.spotify.get_stream_url("spotify_123", error_callback=err_cb)
        event.wait(timeout=2.0)
        self.assertTrue(len(err_msg) > 0)

    def test_spotify_token_management(self):
        # Initial access token is None
        self.spotify._access_token = None
        self.spotify._token_expires_at = 0.0

        # Programmatically set token
        self.spotify.set_access_token("test_token_abc", expires_in=3600)
        self.assertEqual(self.spotify.get_access_token(), "test_token_abc")

        # Configured token from settings takes precedence
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda cat, key, default="": "cfg_secret_token" if key == "spotify_token" else default
        sp_with_settings = SpotifyService(settings=mock_settings)
        self.assertEqual(sp_with_settings.get_access_token(), "cfg_secret_token")

    def test_spotify_web_api_album_and_playlist_resolution(self):
        self.spotify.set_access_token("valid_token", expires_in=3600)

        fake_sp_album = {
            "items": [
                {
                    "id": "sp_t1",
                    "name": "Web Track 1",
                    "artists": [{"name": "Web Artist"}],
                    "duration_ms": 200000,
                    "external_urls": {"spotify": "https://open.spotify.com/track/sp_t1"}
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_sp_album

        with patch("services.spotify_service._session.get", return_value=mock_resp):
            event = threading.Event()
            res_tracks = []
            self.spotify.get_album_tracks("4aawyAB9vmqN3uQ7FjRGTy", callback=lambda t: (res_tracks.extend(t), event.set()))
            event.wait(timeout=2.0)

            self.assertEqual(len(res_tracks), 1)
            self.assertEqual(res_tracks[0]["id"], "spotify_sp_t1")
            self.assertEqual(res_tracks[0]["title"], "Web Track 1")
            self.assertEqual(res_tracks[0]["artist"], "Web Artist")
            self.assertEqual(res_tracks[0]["duration"], 200)

    def test_spotify_playlist_url_fallback(self):
        # When token is None and Spotify URL is passed, fallback should be triggered
        self.spotify._access_token = None
        self.spotify._token_expires_at = 0.0

        fake_resolved = {
            "name": "Imported Playlist",
            "source": "spotify",
            "tracks": [
                {"title": "Fallback Track", "artist": "Fallback Artist", "duration": 210.0, "source": "spotify", "source_id": "ytsearch1: Fallback"}
            ]
        }

        with patch("services.playlist_import_service.PlaylistImportService._resolve_spotify", return_value=fake_resolved):
            event = threading.Event()
            res_tracks = []
            self.spotify.get_playlist_tracks("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", callback=lambda t: (res_tracks.extend(t), event.set()))
            event.wait(timeout=2.0)

            self.assertEqual(len(res_tracks), 1)
            self.assertEqual(res_tracks[0]["title"], "Fallback Track")


if __name__ == "__main__":
    unittest.main()
