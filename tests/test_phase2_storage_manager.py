import os
import tempfile
import unittest
from unittest.mock import MagicMock
from core.database import DatabaseManager
from utils.cache_manager import CacheManager


class TestPhase2StorageManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_aura_storage.db")
        self.db = DatabaseManager(self.db_path)

        self.mock_settings = MagicMock()
        self.mock_settings.get.side_effect = lambda cat, key, default=5: 1  # 1 GB default for test

        self.cache_mgr = CacheManager(self.db, self.mock_settings)
        # Override directories to test sandbox
        self.cache_mgr._base_dir = self.temp_dir
        self.cache_mgr._streams_dir = os.path.join(self.temp_dir, "streams")
        self.cache_mgr._covers_dir = os.path.join(self.temp_dir, "covers")
        self.cache_mgr._temp_dir = os.path.join(self.temp_dir, "temp")
        for d in [self.cache_mgr._streams_dir, self.cache_mgr._covers_dir, self.cache_mgr._temp_dir]:
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lru_purge_and_protection(self):
        # 1. Create a downloaded track (PROTECTED)
        dl_file = os.path.join(self.cache_mgr.streams_dir, "downloaded_track.mp3")
        with open(dl_file, "wb") as f:
            f.write(b"X" * 1024 * 500)  # 500 KB
        dl_track_id = self.db.add_track(title="Downloaded Song", artist="Artist", file_path=dl_file, is_downloaded=1)

        # 2. Create a favorite track (PROTECTED)
        fav_file = os.path.join(self.cache_mgr.streams_dir, "favorite_track.mp3")
        with open(fav_file, "wb") as f:
            f.write(b"X" * 1024 * 500)  # 500 KB
        fav_track_id = self.db.add_track(title="Favorite Song", artist="Artist", file_path=fav_file, is_favorite=1)

        # 3. Create an actively downloading track (PROTECTED by lock)
        active_file = os.path.join(self.cache_mgr.streams_dir, "youtube_active123.m4a")
        with open(active_file, "wb") as f:
            f.write(b"X" * 1024 * 500)  # 500 KB
        with self.cache_mgr._active_downloads_lock:
            self.cache_mgr._active_downloads.add("youtube_active123")

        # 4. Create temporary cached tracks (DISPOSABLE)
        temp_files = []
        for i in range(5):
            tf = os.path.join(self.cache_mgr.streams_dir, f"temp_cache_{i}.m4a")
            with open(tf, "wb") as f:
                f.write(b"Y" * 1024 * 400)  # 400 KB each = 2000 KB
            # Set older mtime for temp_cache_0
            os.utime(tf, (1000000 + i * 100, 1000000 + i * 100))
            self.db.add_track(title=f"Temp Song {i}", artist="Artist", file_path=tf, is_cached=1)
            temp_files.append(tf)

        # Total cache is now ~3.5 MB. Let's set quota to 2 MB (2 * 1024 * 1024 bytes)
        quota = 2 * 1024 * 1024  # 2 MB -> Target 75% = 1.5 MB
        freed = self.cache_mgr.purge_stream_cache(quota_bytes=quota)

        # Verify:
        # 1. Downloaded file survived
        self.assertTrue(os.path.exists(dl_file))
        # 2. Favorite file survived
        self.assertTrue(os.path.exists(fav_file))
        # 3. Actively downloading file survived
        self.assertTrue(os.path.exists(active_file))
        # 4. Oldest temp files were purged
        self.assertFalse(os.path.exists(temp_files[0]))
        self.assertFalse(os.path.exists(temp_files[1]))
        # 5. Freed bytes > 0
        self.assertGreater(freed, 0)

        # 6. Check get_storage_details
        details = self.cache_mgr.get_storage_details()
        self.assertIn("used_bytes", details)
        self.assertIn("quota_bytes", details)
        self.assertGreaterEqual(details["protected_count"], 2)


if __name__ == "__main__":
    unittest.main()
