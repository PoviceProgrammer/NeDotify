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


if __name__ == "__main__":
    unittest.main()
