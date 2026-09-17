import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from core.downloader import DownloadManager
from core.api import AppApi


class TestDownloader(unittest.TestCase):
    def setUp(self):
        self.mock_core = MagicMock()
        self.mock_db = MagicMock()
        self.mock_core.db = self.mock_db
        self.mock_api = MagicMock()
        self.mock_core.api = self.mock_api

        # Create DownloadManager instance without starting processor thread
        with patch("threading.Thread"):
            self.dm = DownloadManager(self.mock_core)

    def test_queue_download_returns_true_on_success(self):
        self.dm._queue.clear()
        res = self.dm.queue_download(101, "youtube", "yt_vid_123")
        self.assertTrue(res)
        self.assertEqual(len(self.dm._queue), 1)
        self.assertEqual(self.dm._queue[0]["track_id"], 101)

    def test_queue_download_duplicate_in_memory_returns_true_and_does_not_duplicate(self):
        self.dm._queue = [{"track_id": 101, "source": "youtube", "source_id": "yt_123"}]
        res = self.dm.queue_download(101, "youtube", "yt_123")
        self.assertTrue(res)
        self.assertEqual(len(self.dm._queue), 1)

    def test_queue_download_db_failure_returns_false(self):
        self.mock_db.conn.execute.side_effect = Exception("Unique constraint failed")
        res = self.dm.queue_download(999, "youtube", "yt_999")
        self.assertFalse(res)

    def test_api_download_track_returns_bool(self):
        api = AppApi(self.mock_core)
        self.mock_core.downloader = self.dm

        # Success case
        self.mock_db.conn.execute.side_effect = None
        self.dm._queue.clear()
        res = api.download_track({"id": 202, "source": "youtube", "source_id": "vid202"})
        self.assertIs(res, True)

        # Empty data case
        res_empty = api.download_track({})
        self.assertIs(res_empty, False)

    def test_download_worker_spotify_resolves_via_youtube(self):
        item = {"track_id": 303, "source": "spotify", "source_id": "ytsearch1: Artist - Song"}
        self.mock_db.conn.cursor.return_value.fetchone.return_value = {"status": "pending"}
        self.mock_db.get_track.return_value = {"id": 303, "artist": "Artist", "title": "Song"}

        with patch("os.path.exists", return_value=True):
            self.mock_core.youtube.download_audio_sync.return_value = "/tmp/fake_spotify.mp3"
            self.dm._download_worker(item)

            self.mock_core.youtube.download_audio_sync.assert_called_once()
            called_target = self.mock_core.youtube.download_audio_sync.call_args[0][0]
            self.assertTrue(called_target.startswith("ytsearch1:"))

    def test_download_worker_closes_sqlite_thread_connection(self):
        item = {"track_id": 404, "source": "youtube", "source_id": "yt_404"}
        self.mock_db.conn.cursor.return_value.fetchone.return_value = {"status": "pending"}

        with patch("os.path.exists", return_value=True):
            self.mock_core.youtube.download_audio_sync.return_value = "/tmp/fake_yt.mp3"
            self.dm._download_worker(item)

            self.mock_db.close_thread_connection.assert_called_once()

    def test_cancel_batch(self):
        self.dm._queue = [{"track_id": 1}, {"track_id": 2}]
        self.dm.start_batch(2)
        self.assertTrue(self.dm._batch_active)

        cancelled = self.dm.cancel_batch()
        self.assertTrue(cancelled)
        self.assertFalse(self.dm._batch_active)
        self.assertEqual(len(self.dm._queue), 0)

    def test_download_worker_vk_download_support(self):
        item = {"track_id": 505, "source": "vk", "source_id": "https://vk.com/audio123"}
        self.mock_db.conn.cursor.return_value.fetchone.return_value = {"status": "pending"}

        with patch("os.path.exists", return_value=True):
            self.mock_core.vk.download_audio_sync.return_value = "/tmp/fake_vk.mp3"
            self.dm._download_worker(item)

            self.mock_core.vk.download_audio_sync.assert_called_once_with("https://vk.com/audio123", self.dm.download_dir)


if __name__ == "__main__":
    unittest.main()

