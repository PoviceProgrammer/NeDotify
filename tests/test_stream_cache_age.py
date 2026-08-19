"""
Playback-fix regression tests (stream-cache age / downloaded-file freshness).

Covers:
1. get_cached_stream default max age (14400s) rejects URLs older than 4h
   (googlevideo signatures expire in ~6h; the old 86400s default served
   stale URLs to the proxy -> 403 -> 15s self-heal hang).
2. set_cached_file bumps cached_at so downloaded files are always served
   from disk regardless of when the row was created.
3. StreamResolver._DB_MAX_AGE is aligned with the DB default.
"""

import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import AppCore
from core.database import DatabaseManager
from core.resolver import StreamResolver, _DB_MAX_AGE

# Capture the real Thread class: test_nedotify.py swaps threading.Thread for a
# synchronous shim at import time, and pytest.py imports every module before
# running any test. AppCore() spawns infinite background daemon loops, which
# must run on real threads or the constructor blocks forever.
_REAL_THREAD_CLASS = threading.Thread


class TestStreamCacheAge(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.mkdtemp(prefix="aura_stream_age_")
        self._expanduser = patch("os.path.expanduser", return_value=self._tmp)
        self._expanduser.start()
        threading.Thread = _REAL_THREAD_CLASS
        self.core = AppCore()

    def tearDown(self):
        try:
            self.core.cleanup()
        except Exception:
            pass
        self._expanduser.stop()

    def _backdate(self, source, source_id, delta_sql):
        cur = self.core.db.conn.cursor()
        cur.execute(
            "UPDATE stream_cache SET cached_at = datetime('now', ?) "
            "WHERE source = ? AND source_id = ?",
            (delta_sql, source, source_id),
        )
        self.core.db.conn.commit()

    def test_default_max_age_rejects_6h_old_url(self):
        self.core.db.cache_stream("youtube", "old6h", "http://stale.example/1.mp3")
        self._backdate("youtube", "old6h", "-6 hours")
        cached = self.core.db.get_cached_stream("youtube", "old6h")
        self.assertIsNone(cached)

    def test_default_max_age_accepts_2h_old_url(self):
        self.core.db.cache_stream("youtube", "fresh2h", "http://fresh.example/1.mp3")
        self._backdate("youtube", "fresh2h", "-2 hours")
        cached = self.core.db.get_cached_stream("youtube", "fresh2h")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["stream_url"], "http://fresh.example/1.mp3")

    def test_resolver_skips_6h_old_url_and_runs_network(self):
        self.core.db.cache_stream("youtube", "res_old", "http://stale.example/2.mp3")
        self._backdate("youtube", "res_old", "-6 hours")
        resolver = StreamResolver(self.core.db)
        calls = []
        url = resolver.resolve("youtube", "res_old", lambda: (calls.append(1), ("http://new.example/2.mp3", None))[1])
        self.assertEqual(url, "http://new.example/2.mp3")
        self.assertEqual(calls, [1])

    def test_set_cached_file_bumps_cached_at(self):
        self.core.db.cache_stream("youtube", "dl_file", "http://old.example/3.mp3")
        self._backdate("youtube", "dl_file", "-30 days")
        file_path = os.path.join(self._tmp, "streams", "dl.webm")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as fh:
            fh.write(b"fake webm")
        self.core.db.set_cached_file("youtube", "dl_file", file_path)
        cached = self.core.db.get_cached_stream("youtube", "dl_file")
        self.assertIsNotNone(cached, "downloaded-file row must stay fetchable regardless of age")
        self.assertEqual(cached["cached_file_path"], file_path)
        self.assertIsNone(cached["expires_at"])

    def test_invalidate_clears_url_keeps_file_row(self):
        self.core.db.cache_stream("youtube", "inv_file", "http://dead.example/4.mp3")
        file_path = os.path.join(self._tmp, "streams", "inv.webm")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as fh:
            fh.write(b"fake webm")
        self.core.db.set_cached_file("youtube", "inv_file", file_path)
        self.core.db.invalidate_cached_stream("youtube", "inv_file")
        row = self.core.db.get_cached_stream("youtube", "inv_file")
        self.assertIsNotNone(row)
        self.assertIsNone(row["stream_url"])
        self.assertEqual(row["cached_file_path"], file_path)

    def test_expired_url_with_expire_param_ignored_and_invalidated(self):
        import time
        past = int(time.time()) - 3600
        self.core.db.cache_stream("youtube", "exp_param", f"http://googlevideo.example/video?expire={past}&sig=abc")
        resolver = StreamResolver(self.core.db)
        self.assertIsNone(resolver.get_cached_url("youtube", "exp_param"))
        row = self.core.db.get_cached_stream("youtube", "exp_param")
        self.assertIsNone(row["stream_url"], "expired URL must be cleared from DB")

    def test_future_expire_param_still_cached(self):
        import time
        future = int(time.time()) + 7200
        self.core.db.cache_stream("youtube", "ok_param", f"http://googlevideo.example/video?expire={future}&sig=abc")
        resolver = StreamResolver(self.core.db)
        self.assertEqual(
            resolver.get_cached_url("youtube", "ok_param"),
            f"http://googlevideo.example/video?expire={future}&sig=abc",
        )

    def test_resolver_db_max_age_aligned_with_default(self):
        self.assertEqual(_DB_MAX_AGE, 14400)
        self.assertEqual(_DB_MAX_AGE, DatabaseManager.get_cached_stream.__defaults__[0])


if __name__ == "__main__":
    unittest.main()