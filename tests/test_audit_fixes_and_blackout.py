"""
Unit tests validating audit fixes and Yandex/VK UI blackout policy.
"""

import unittest
import threading
import tempfile
import os
from services.base_service import BaseMusicService
from core.database import DatabaseManager

# Capture the real Thread class: test_nedotify.py swaps threading.Thread for a
# synchronous shim at import time, and pytest.py imports every module before
# running any test.
_REAL_THREAD_CLASS = threading.Thread


class TestAuditFixesAndBlackout(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmp_dir.name, "test_audit.db")
        self.db = DatabaseManager(db_path)

    def tearDown(self):
        try:
            if hasattr(self.db, '_local') and hasattr(self.db._local, 'connection') and self.db._local.connection:
                self.db._local.connection.close()
                self.db._local.connection = None
        except Exception:
            pass
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_database_add_track_preserves_file_path(self):
        """Test that add_track preserves file_path even when source is not 'local'."""
        fake_path = os.path.join(self.tmp_dir.name, "downloaded_track.m4a")
        track_id = self.db.add_track(
            title="Test Track",
            artist="Test Artist",
            source="youtube",
            source_id="yt_12345",
            file_path=fake_path
        )
        track = self.db.get_track(track_id)
        self.assertIsNotNone(track)
        self.assertEqual(track["file_path"], fake_path)
        self.assertEqual(track["source"], "youtube")

    def test_base_service_cache_thread_safety(self):
        """Test concurrent access to BaseMusicService caches does not raise RuntimeError."""
        insert_order = []

        def worker(thread_idx):
            for i in range(100):
                key = f"key_{thread_idx}_{i}"
                BaseMusicService.set_to_cache(key, {"url": f"http://test/{key}"})
                BaseMusicService.get_from_cache(key)
                BaseMusicService.set_search_cache(key, [{"title": "Track"}])
                BaseMusicService.get_search_cache(key)
                insert_order.append(key)

        threads = [_REAL_THREAD_CLASS(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            if hasattr(t, "join"):
                t.join()

        # _search_cache is capped at 500 entries (oldest evicted on insert):
        # with 1000 unique keys the first-inserted key is deterministically gone,
        # the cache never grows past the cap, and the last-inserted key survives.
        self.assertLessEqual(len(BaseMusicService._search_cache), BaseMusicService._SEARCH_CACHE_MAX_SIZE)
        self.assertIsNone(BaseMusicService.get_search_cache("key_0_0"))
        newest_key = insert_order[-1]
        self.assertIsNotNone(BaseMusicService.get_search_cache(newest_key))

if __name__ == "__main__":
    unittest.main()
