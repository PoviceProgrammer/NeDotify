"""
Unit and Integration Tests for Album Search, Metadata Resolution & Playback.
"""

import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import sqlite3

from core.database import DatabaseManager
from core.api import AppApi
from services.spotify_service import SpotifyService, _cached_spotify_album_search
from services.youtube_service import YouTubeService


class TestAlbumSearchAndPlayback(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_album.db")
        self.db = DatabaseManager(self.db_path)

        # Seed test tracks with albums
        self.db.add_track(
            title="Catapult",
            artist="Dinos Boys",
            album="Last Ones",
            duration=120.0,
            source="youtube",
            source_id="B3pxAqPD138"
        )
        self.db.add_track(
            title="Bloody Carpet",
            artist="Dinos Boys",
            album="Last Ones",
            duration=84.0,
            source="youtube",
            source_id="We-ypQcea1I"
        )

    def tearDown(self):
        try:
            if hasattr(self.db, '_local') and hasattr(self.db._local, 'connection') and self.db._local.connection:
                self.db._local.connection.close()
                self.db._local.connection = None
        except Exception:
            pass
        self.tmp_dir.cleanup()

    def test_database_search_albums(self):
        """Verify DatabaseManager.search_albums returns grouped album data."""
        albums = self.db.search_albums("Last Ones")
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["title"], "Last Ones")
        self.assertEqual(albums[0]["artist"], "Dinos Boys")
        self.assertEqual(albums[0]["track_count"], 2)
        self.assertEqual(albums[0]["type"], "album")

    def test_database_get_album_tracks(self):
        """Verify DatabaseManager.get_album_tracks returns all tracks in the album."""
        tracks = self.db.get_album_tracks("Last Ones", "Dinos Boys")
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["title"], "Bloody Carpet")
        self.assertEqual(tracks[1]["title"], "Catapult")

    @patch("services.spotify_service._session.get")
    def test_spotify_album_search(self, mock_get):
        """Verify SpotifyService.search with result_type='albums' parses iTunes album schema."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "collectionId": 123456,
                    "collectionName": "Last Ones Left",
                    "artistName": "42 Dugg & EST Gee",
                    "releaseDate": "2022-04-08T07:00:00Z",
                    "trackCount": 17,
                    "artworkUrl100": "https://example.com/100x100bb.jpg"
                }
            ]
        }
        mock_get.return_value = mock_resp

        service = SpotifyService()
        callback = MagicMock()
        service.search("Last Ones", callback=callback, result_type="albums")

        # Wait for background thread
        import time
        time.sleep(0.2)

        callback.assert_called_once()
        albums = callback.call_args[0][0]
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["title"], "Last Ones Left")
        self.assertEqual(albums[0]["artist"], "42 Dugg & EST Gee")
        self.assertEqual(albums[0]["year"], "2022")
        self.assertEqual(albums[0]["track_count"], 17)
        self.assertEqual(albums[0]["type"], "album")

    @patch("services.youtube_service.HAS_YTMUSIC", True)
    @patch("services.youtube_service.HAS_YTDLP", True)
    def test_youtube_album_search(self):
        """Verify YouTubeService.search with result_type='albums' parses YTMusic album schema."""
        service = YouTubeService()
        service._ytmusic = MagicMock()
        service._ytmusic.search.return_value = [
            {
                "browseId": "MPREb_5SzD7dJJzng",
                "title": "Last Ones",
                "artists": [{"name": "Dinos Boys"}],
                "year": "2014",
                "thumbnails": [{"url": "https://example.com/cover.jpg"}],
                "track_count": 11
            }
        ]

        callback = MagicMock()
        service.search("Last Ones", callback=callback, result_type="albums")

        import time
        time.sleep(0.2)

        callback.assert_called_once()
        albums = callback.call_args[0][0]
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["title"], "Last Ones")
        self.assertEqual(albums[0]["artist"], "Dinos Boys")
        self.assertEqual(albums[0]["type"], "album")

    def test_api_get_album_tracks_local(self):
        """Verify AppApi.get_album_tracks returns local tracks when source is local."""
        mock_core = MagicMock()
        mock_core.db = self.db
        api = AppApi(mock_core)

        album_data = {
            "title": "Last Ones",
            "artist": "Dinos Boys",
            "source": "local"
        }
        tracks = api.get_album_tracks(album_data)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["album"], "Last Ones")


if __name__ == "__main__":
    unittest.main()
