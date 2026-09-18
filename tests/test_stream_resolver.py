"""
Unit test suite for core/resolver.py (StreamResolver).
Tests in-memory caching, single-flight concurrent deduplication, DB cache interactions,
expiration time parsing (YouTube & SoundCloud), and cache invalidation.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock

from core.resolver import StreamResolver, _MEM_MAX_SIZE


class TestStreamResolver(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.resolver = StreamResolver(db=self.mock_db, mem_ttl=60.0, resolve_timeout=2.0)

    def test_url_expired_youtube(self):
        """_url_expired detects expired YouTube stream URLs."""
        past_time = int(time.time()) - 100
        future_time = int(time.time()) + 10000

        expired_url = f"https://rr1---sn-4g5ednks.googlevideo.com/videoplayback?expire={past_time}&id=123"
        valid_url = f"https://rr1---sn-4g5ednks.googlevideo.com/videoplayback?expire={future_time}&id=123"

        self.assertTrue(self.resolver._url_expired(expired_url))
        self.assertFalse(self.resolver._url_expired(valid_url))
        self.assertFalse(self.resolver._url_expired(None))
        self.assertFalse(self.resolver._url_expired(""))

    def test_mem_lru_cap_eviction(self):
        """_mem_set evicts oldest entry when _MEM_MAX_SIZE is reached."""
        small_resolver = StreamResolver(db=None)
        # Populate up to max size
        for i in range(_MEM_MAX_SIZE):
            small_resolver._mem_set(f"key_{i}", (f"http://example.com/{i}", time.time()))

        self.assertEqual(len(small_resolver._mem), _MEM_MAX_SIZE)
        self.assertIn("key_0", small_resolver._mem)

        # Add one more
        small_resolver._mem_set("new_key", ("http://example.com/new", time.time()))
        self.assertEqual(len(small_resolver._mem), _MEM_MAX_SIZE)
        self.assertNotIn("key_0", small_resolver._mem)
        self.assertIn("new_key", small_resolver._mem)

    def test_resolve_in_memory_hit(self):
        """Resolving an in-memory cached URL does not call network cascade or DB."""
        future_ts = int(time.time()) + 5000
        stream_url = f"https://googlevideo.com/videoplayback?expire={future_ts}"
        self.resolver._mem_set(("youtube", "yt_123"), (stream_url, time.time()))

        mock_cascade = MagicMock()
        res = self.resolver.resolve("youtube", "yt_123", mock_cascade)

        self.assertEqual(res, stream_url)
        mock_cascade.assert_not_called()
        self.mock_db.get_cached_stream.assert_not_called()
        stats = self.resolver.stats()
        self.assertEqual(stats["mem_hits"], 1)

    def test_resolve_db_cache_hit(self):
        """Resolving a DB cached URL updates in-memory cache and returns URL."""
        future_ts = int(time.time()) + 5000
        stream_url = f"https://googlevideo.com/videoplayback?expire={future_ts}"
        self.mock_db.get_cached_stream.return_value = {"stream_url": stream_url}

        mock_cascade = MagicMock()
        res = self.resolver.resolve("youtube", "yt_456", mock_cascade)

        self.assertEqual(res, stream_url)
        mock_cascade.assert_not_called()
        self.mock_db.get_cached_stream.assert_called_once()
        stats = self.resolver.stats()
        self.assertEqual(stats["db_hits"], 1)

    def test_single_flight_concurrent_deduplication(self):
        """Concurrent calls for the same (source, source_id) must execute resolver_fn only once."""
        call_count = 0
        call_lock = threading.Lock()

        def slow_resolver():
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.1)
            future_ts = int(time.time()) + 5000
            return (f"https://googlevideo.com/videoplayback?expire={future_ts}&id=singleflight", None)

        self.mock_db.get_cached_stream.return_value = None

        results = []
        threads = []

        def worker():
            url = self.resolver.resolve("youtube", "single_flight_id", slow_resolver)
            results.append(url)

        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)
        # All 5 callers must receive the exact same URL
        self.assertEqual(len(set(results)), 1)
        # Network cascade must only have been invoked ONCE
        self.assertEqual(call_count, 1)

        stats = self.resolver.stats()
        self.assertEqual(stats["network_cascades"], 1)
        self.assertGreaterEqual(stats["single_flight_waits"], 1)

    def test_invalidate_and_refresh(self):
        """invalidate removes entry from memory and DB; refresh updates both."""
        self.resolver._mem_set(("soundcloud", "sc_99"), ("http://sc.com/1", time.time()))

        self.resolver.invalidate("soundcloud", "sc_99")
        self.assertNotIn(("soundcloud", "sc_99"), self.resolver._mem)
        self.mock_db.invalidate_cached_stream.assert_called_once_with("soundcloud", "sc_99")

        self.resolver.refresh("soundcloud", "sc_99", "http://sc.com/2")
        self.assertIn(("soundcloud", "sc_99"), self.resolver._mem)
        self.mock_db.cache_stream.assert_called_once_with("soundcloud", "sc_99", "http://sc.com/2")
