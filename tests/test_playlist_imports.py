import io
import os
import sys
import unittest
import urllib.request
import urllib.error
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
        self._url_patcher = patch('utils.url_safety.safe_public_url', side_effect=lambda u: not any(p in u for p in ('127.0.0.1', '192.168.', '169.254.', 'localhost', 'evil.m3u')))
        self._url_patcher.start()
        self.core = MagicMock()
        self.core.db = MagicMock()
        self.core.db.import_playlist_atomic.return_value = (1, 2)
        self.core.playlist_importer = self.service
        self.api = AppApi(self.core)

    def tearDown(self):
        self._url_patcher.stop()

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
        mock_entries = [
            {"id": "101", "title": "Full Track", "uploader": "Artist One", "duration": 180, "thumbnail": "https://img.sndcdn.com/art-large.jpg"},
            {"id": "102", "title": "Unknown Title", "uploader": "Unknown Artist", "duration": 210, "thumbnail": ""}
        ]
        mock_info = {"title": "Summer Vibes Set", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        def fake_enrich(tracks):
            for t in tracks:
                if t.get("source_id") == "102":
                    t["title"] = "Hydrated Track"
                    t["artist"] = "Artist Two"
                    t["cover_url"] = "https://img.sndcdn.com/art2-t500x500.jpg"

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            with patch.object(self.service, "_enrich_soundcloud_tracks", side_effect=fake_enrich):
                res = self.service.resolve("https://soundcloud.com/artist/sets/summer-vibes")
                self.assertEqual(res["name"], "Summer Vibes Set")
                self.assertEqual(res["source"], "soundcloud")
                self.assertEqual(len(res["tracks"]), 2)
                self.assertEqual(res["tracks"][0]["title"], "Full Track")
                self.assertEqual(res["tracks"][1]["title"], "Hydrated Track")
                self.assertEqual(res["tracks"][1]["artist"], "Artist Two")

    def test_soundcloud_ytdlp_slug_parsing_fallback(self):
        mock_entries = [
            {
                "id": "1514428012",
                "title": "Morning Coffee Beat",
                "uploader": "Chill Producer",
                "url": "https://soundcloud.com/chill-producer/morning-coffee-beat",
                "duration": 120
            }
        ]
        mock_info = {"title": "Lofi Chill Mix", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            with patch.object(self.service, "_enrich_soundcloud_tracks"):
                res = self.service.resolve("https://soundcloud.com/chill-producer/sets/lofi-chill")
                self.assertEqual(res["name"], "Lofi Chill Mix")
                self.assertEqual(len(res["tracks"]), 1)
                self.assertEqual(res["tracks"][0]["artist"], "Chill Producer")
                self.assertEqual(res["tracks"][0]["title"], "Morning Coffee Beat")

    def test_soundcloud_shortened_url_redirect(self):
        fake_resp = MagicMock()
        fake_resp.geturl.return_value = "https://soundcloud.com/artist/sets/canonical-set"
        fake_resp.__enter__.return_value = fake_resp

        mock_entries = [
            {"id": "1", "title": "Short Track", "uploader": "Short Artist", "duration": 100}
        ]
        mock_info = {"title": "Shortened Set", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch("utils.url_safety.guarded_open_url", return_value=fake_resp):
            with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
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

        def mock_api_get(url, *args, **kwargs):
            if "tracks?ids=" in url:
                return batch_resp
            return resolve_resp

        sc._api_get = mock_api_get

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

    def test_deezer_playlist_import_success(self):
        mock_collection = {
            "name": "Deezer Hits",
            "source": "deezer",
            "tracks": [
                {"title": "Deezer Song 1", "artist": "Deezer Artist 1", "duration": 180, "source": "deezer", "source_id": "111"}
            ]
        }
        with patch("services.deezer_service.DeezerService.collection", return_value=mock_collection):
            res = self.service.resolve("https://www.deezer.com/playlist/30595446")
            self.assertEqual(res["name"], "Deezer Hits")
            self.assertEqual(res["source"], "deezer")
            self.assertEqual(len(res["tracks"]), 1)

    def test_spotify_playlist_unsupported(self):
        with self.assertRaises(UnsupportedPlaylistService):
            self.service.resolve("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

    def test_unsupported_playlist_service_raises(self):
        with self.assertRaises(UnsupportedPlaylistService):
            self.service.resolve("https://tidal.com/browse/playlist/test")

    def test_api_import_external_playlist_ssrf_block(self):
        res = self.api.import_external_playlist("http://127.0.0.1:8080/evil.m3u")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_api_import_external_playlist_success(self):
        mock_entries = [
            {"title": "Track One", "uploader": "Musician", "id": "yt_10", "duration": 200, "thumbnail": ""}
        ]
        mock_info = {"title": "My Playlist", "entries": mock_entries}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl.__enter__.return_value = mock_ydl

        with patch.object(self.service, "_get_ydl", return_value=mock_ydl):
            res = self.api.import_external_playlist("https://www.youtube.com/playlist?list=PLvalid123")
            self.assertTrue(res["success"])
            self.assertEqual(res["imported_count"], 2)

    def test_resolve_rejects_ssrf_and_private_network(self):
        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://127.0.0.1:8080/evil.m3u")

        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://192.168.1.1/spotify.com/playlist/12345")

        with self.assertRaises(PlaylistImportError):
            self.service.resolve("http://169.254.169.254/latest/meta-data/playlist/12345")

    def test_safe_redirect_handler_blocks_ssrf(self):
        from utils.url_safety import PublicRedirectHandler
        handler = PublicRedirectHandler()
        req = urllib.request.Request("https://example.com/playlist")
        fp = MagicMock()
        headers = {}
        with self.assertRaises(urllib.error.URLError) as ctx:
            handler.redirect_request(req, fp, 302, "Found", headers, "http://127.0.0.1:8080/admin")
        self.assertIn("Unsafe redirect", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
