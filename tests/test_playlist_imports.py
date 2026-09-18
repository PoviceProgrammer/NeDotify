import io
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from services.playlist_import_service import (
    PlaylistImportService,
    PlaylistImportError,
    UnsupportedPlaylistService,
)
from core.app import AppCore
from core.api import AppApi


class TestPlaylistImports(unittest.TestCase):
    def setUp(self):
        self.service = PlaylistImportService()
        self.core = MagicMock()
        self.core.db = MagicMock()
        self.core.db.create_playlist.return_value = 1
        self.core.playlist_importer = self.service
        self.api = AppApi(self.core)

    def test_youtube_playlist_import_success(self):
        mock_entries = [
            {"title": "Track 1", "uploader": "Artist 1", "id": "yt_1", "duration": 180, "thumbnail": "http://cover1.jpg"},
            {"title": "Track 2", "uploader": "Artist 2", "id": "yt_2", "duration": 200, "thumbnail": "http://cover2.jpg"},
        ]
        mock_info = {
            "title": "My YouTube Mix",
            "entries": mock_entries
        }

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            res = self.service.resolve("https://www.youtube.com/playlist?list=PLtest123")
            self.assertEqual(res["name"], "My YouTube Mix")
            self.assertEqual(res["source"], "youtube")
            self.assertEqual(len(res["tracks"]), 2)
            self.assertEqual(res["tracks"][0]["title"], "Track 1")
            self.assertEqual(res["tracks"][0]["source_id"], "yt_1")

    def test_youtube_playlist_import_empty_raises(self):
        mock_info = {"title": "Empty Mix", "entries": []}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            with self.assertRaises(PlaylistImportError):
                self.service.resolve("https://www.youtube.com/playlist?list=PLempty")

    def test_soundcloud_playlist_import_success(self):
        mock_entries = [
            {"id": "sc_12345", "title": "SC Track 1", "uploader": "SC Artist 1", "url": "https://soundcloud.com/artist/track1", "duration": 150, "thumbnail": "http://sccover.jpg"}
        ]
        mock_info = {"title": "SC Playlist", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            res = self.service.resolve("https://soundcloud.com/user/sets/test-set")
            self.assertEqual(res["name"], "SC Playlist")
            self.assertEqual(res["source"], "soundcloud")
            self.assertEqual(len(res["tracks"]), 1)
            self.assertEqual(res["tracks"][0]["title"], "SC Track 1")

    def test_soundcloud_playlist_api_resolution_with_batch_hydration(self):
        mock_sc = MagicMock()
        mock_sc._get_client_id.return_value = "mock_client_id_123"

        # Mock resolve response: 1 full track, 1 stub track
        resolve_resp = MagicMock()
        resolve_resp.status_code = 200
        resolve_resp.json.return_value = {
            "title": "Summer Vibes Set",
            "tracks": [
                {
                    "id": 101,
                    "title": "Full Track",
                    "user": {"username": "Artist One"},
                    "duration": 180000,
                    "artwork_url": "https://img.sndcdn.com/art-large.jpg",
                    "permalink_url": "https://soundcloud.com/artist-one/full-track"
                },
                {
                    "id": 102,
                    "kind": "track"
                }
            ]
        }

        # Mock batch hydration response for stub track 102
        batch_resp = MagicMock()
        batch_resp.status_code = 200
        batch_resp.json.return_value = [
            {
                "id": 102,
                "title": "Hydrated Track",
                "user": {"username": "Artist Two"},
                "duration": 210000,
                "artwork_url": "https://img.sndcdn.com/art2-large.jpg",
                "permalink_url": "https://soundcloud.com/artist-two/hydrated-track"
            }
        ]

        def mock_get(url, *args, **kwargs):
            if "tracks?ids=" in url:
                return batch_resp
            return resolve_resp

        mock_sc._session.get.side_effect = mock_get
        self.service.soundcloud_service = mock_sc

        res = self.service.resolve("https://soundcloud.com/artist/sets/summer-vibes")
        self.assertEqual(res["name"], "Summer Vibes Set")
        self.assertEqual(res["source"], "soundcloud")
        self.assertEqual(len(res["tracks"]), 2)
        
        # Verify track 1
        self.assertEqual(res["tracks"][0]["title"], "Full Track")
        self.assertEqual(res["tracks"][0]["artist"], "Artist One")
        self.assertEqual(res["tracks"][0]["duration"], 180.0)
        self.assertIn("t500x500.jpg", res["tracks"][0]["cover_url"])

        # Verify hydrated track 2
        self.assertEqual(res["tracks"][1]["title"], "Hydrated Track")
        self.assertEqual(res["tracks"][1]["artist"], "Artist Two")
        self.assertEqual(res["tracks"][1]["duration"], 210.0)
        self.assertIn("t500x500.jpg", res["tracks"][1]["cover_url"])

    def test_soundcloud_ytdlp_slug_parsing_fallback(self):
        # When yt-dlp returns flat entries with missing title/uploader
        mock_entries = [
            {
                "id": "1514428012",
                "url": "https://soundcloud.com/chill-producer/morning-coffee-beat",
                "duration": 120
            }
        ]
        mock_info = {"title": "Lofi Chill Mix", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            res = self.service.resolve("https://soundcloud.com/chill-producer/sets/lofi-chill")
            self.assertEqual(res["name"], "Lofi Chill Mix")
            self.assertEqual(len(res["tracks"]), 1)
            self.assertEqual(res["tracks"][0]["artist"], "Chill Producer")
            self.assertEqual(res["tracks"][0]["title"], "Morning Coffee Beat")

    def test_soundcloud_shortened_url_redirect(self):
        fake_resp = MagicMock()
        fake_resp.geturl.return_value = "https://soundcloud.com/artist/sets/canonical-set"
        fake_resp.__enter__.return_value = fake_resp

        mock_sc = MagicMock()
        mock_sc._get_client_id.return_value = "cid_123"
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.return_value = {
            "title": "Shortened Set",
            "tracks": [{"id": 1, "title": "Short Track", "duration": 100000}]
        }
        mock_sc._session.get.return_value = mock_r
        self.service.soundcloud_service = mock_sc

        with patch("urllib.request.urlopen", return_value=fake_resp):
            res = self.service.resolve("https://on.soundcloud.com/abcde")
            self.assertEqual(res["name"], "Shortened Set")
            self.assertEqual(len(res["tracks"]), 1)
            self.assertEqual(res["tracks"][0]["title"], "Short Track")

    def test_soundcloud_service_get_playlist_tracks_hydrates_stubs(self):
        from services.soundcloud_service import SoundCloudService
        sc = SoundCloudService()
        sc._client_id = "test_cid"

        resolve_resp = MagicMock()
        resolve_resp.status_code = 200
        resolve_resp.json.return_value = {
            "tracks": [
                {"id": 1, "title": "Track 1", "user": {"username": "Artist 1"}},
                {"id": 2, "kind": "track"}
            ]
        }

        batch_resp = MagicMock()
        batch_resp.status_code = 200
        batch_resp.json.return_value = [
            {"id": 2, "title": "Track 2 Hydrated", "user": {"username": "Artist 2"}}
        ]

        def mock_get(url, *args, **kwargs):
            if "tracks?ids=" in url:
                return batch_resp
            return resolve_resp

        mock_session = MagicMock()
        mock_session.get.side_effect = mock_get
        sc._session = mock_session

        results = []
        import threading
        evt = threading.Event()
        def callback(tracks):
            results.extend(tracks)
            evt.set()

        sc.get_playlist_tracks("https://soundcloud.com/artist/sets/set", callback=callback)
        evt.wait(timeout=3.0)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Track 1")
        self.assertEqual(results[1]["title"], "Track 2 Hydrated")
        self.assertEqual(results[1]["artist"], "Artist 2")

    def test_spotify_playlist_import_success(self):
        fake_html = """
        <html>
            <head>
                <meta property="og:title" content="Awesome Spotify Mix">
                <meta name="description" content="Song A · Artist 1, Song B · Artist 2">
            </head>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = self.service.resolve("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
            self.assertEqual(res["name"], "Awesome Spotify Mix")
            self.assertEqual(res["source"], "spotify")
            self.assertEqual(len(res["tracks"]), 2)
            self.assertEqual(res["tracks"][0]["title"], "Song A")
            self.assertEqual(res["tracks"][0]["artist"], "Artist 1")
            self.assertEqual(res["tracks"][0]["source_id"], "ytsearch1: Artist 1 - Song A")

    def test_spotify_playlist_import_empty_raises_error(self):
        fake_html = "<html><head><title>No Tracks</title></head></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("No yt-dlp metadata")
        mock_ydl.__enter__.return_value = mock_ydl

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
                with self.assertRaises(PlaylistImportError):
                    self.service.resolve("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

    def test_spotify_playlist_invalid_url_format(self):
        with self.assertRaises(PlaylistImportError):
            self.service.resolve("https://open.spotify.com/album/37i9dQZF1DXcBWIGoYBM5M")

    def test_unsupported_playlist_service_raises(self):
        with self.assertRaises(UnsupportedPlaylistService):
            self.service.resolve("https://tidal.com/browse/playlist/test")

    def test_api_import_external_playlist_ssrf_block(self):
        res = self.api.import_external_playlist("http://127.0.0.1:8080/evil.m3u")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_api_import_external_playlist_success(self):
        fake_html = """
        <html>
            <head>
                <meta property="og:title" content="My Playlist">
                <meta name="description" content="Track One · Musician">
            </head>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = self.api.import_external_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
            self.assertTrue(res["success"])
            self.assertEqual(res["imported_count"], 1)

    def test_resolve_rejects_ssrf_and_private_network(self):
        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://127.0.0.1:8080/evil.m3u")

        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://192.168.1.1/spotify.com/playlist/12345")

        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://169.254.169.254/latest/meta-data/playlist/12345")

    def test_safe_redirect_handler_blocks_ssrf(self):
        from services.playlist_import_service import SafeRedirectHandler
        handler = SafeRedirectHandler()
        req = MagicMock()
        fp = MagicMock()
        headers = {}
        with self.assertRaises(PlaylistImportError) as ctx:
            handler.redirect_request(req, fp, 302, "Found", headers, "http://127.0.0.1:8080/admin")
        self.assertIn("SSRF Protection", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
