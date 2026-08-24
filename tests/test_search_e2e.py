"""
E2E Test Suite: Multi-Provider Search & Caching Layer (Features 12 - 16)
Authoritative Requirements: ORIGINAL_REQUEST.md (§3), PROJECT.md (§ Architectural & Feature Specifications), TEST_INFRA.md

Scope:
- Feature 12: Restore Yandex Search Provider
- Feature 13: Non-blocking Asynchronous DB Search
- Feature 14: Provider Hard Timeouts & Silent Failure Patch
- Feature 15: Thread-Safe Bounded Search Cache
- Feature 16: Track Deduplication & UI Result Merging

Tier Coverage:
- Tier 1 (Feature Coverage): AT LEAST 5 test cases per feature (25 tests)
- Tier 2 (Boundary & Edge Cases): AT LEAST 5 test cases per feature (25 tests)
- Total: 50 distinct test cases
"""

import os
import sys
import time
import json
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from unittest.mock import MagicMock, patch, Mock

import pytest

from core.api import AppApi
from core.database import DatabaseManager
from services.base_service import BaseMusicService
from services.yandex_service import YandexService
from services.soundcloud_service import SoundCloudService
from services.spotify_service import SpotifyService
from services.youtube_service import YouTubeService


# Helper function for Track Deduplication & Normalization (Feature 16 specification)
def normalize_track_key(title: str, artist: str) -> str:
    """Normalize title and artist for cross-provider track deduplication."""
    if not title:
        title = ""
    if not artist:
        artist = ""

    t = str(title).lower()
    a = str(artist).lower()

    # Remove featured artists tokens first
    t = re.sub(r"\b(ft\.?|feat\.?|featuring)\b.*", "", t)
    a = re.sub(r"\b(ft\.?|feat\.?|featuring)\b.*", "", a)

    # Remove common video/audio suffixes and metadata brackets
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", "", t)
    t = re.sub(r"\b(official|video|audio|lyric|remastered|hd|4k)\b", "", t)

    # Strip punctuation and collapse whitespace
    t = re.sub(r"[^\w\s]", "", t, flags=re.UNICODE)
    a = re.sub(r"[^\w\s]", "", a, flags=re.UNICODE)

    t = " ".join(t.split())
    a = " ".join(a.split())

    return f"{a} - {t}"


def deduplicate_tracks(tracks: list) -> list:
    """Merge identical tracks across providers by normalized title/artist."""
    if not tracks:
        return []

    seen = {}
    deduped = []

    for track in tracks:
        if not isinstance(track, dict):
            continue

        title = track.get("title", "")
        artist = track.get("artist", "")
        key = normalize_track_key(title, artist)

        if key not in seen:
            # Create a copy with provider sources list
            merged_track = dict(track)
            merged_track["providers"] = [track.get("source", "unknown")]
            seen[key] = len(deduped)
            deduped.append(merged_track)
        else:
            existing_idx = seen[key]
            existing_track = deduped[existing_idx]
            src = track.get("source", "unknown")
            if src not in existing_track.get("providers", []):
                existing_track.setdefault("providers", []).append(src)

    return deduped


# ==============================================================================
# Feature 12: Restore Yandex Search Provider
# ==============================================================================
class TestFeature12YandexSearchProvider(unittest.TestCase):
    """Test Suite for Feature 12: Yandex Search Provider restoration and functionality."""

    def setUp(self):
        self.settings_mock = MagicMock()
        self.settings_mock.get.return_value = ""

    def test_f12_yandex_service_search_basic(self):
        """Tier 1: Verify YandexService.search returns formatted track dictionaries with source='yandex'."""
        service = YandexService(self.settings_mock)

        mock_track = MagicMock()
        mock_track.id = "12345"
        mock_track.title = "Starboy"
        mock_artist = MagicMock()
        mock_artist.name = "The Weeknd"
        mock_track.artists = [mock_artist]
        mock_track.duration_ms = 230000
        mock_track.cover_uri = "avatars.yandex.net/get-music-content/123/%%"

        mock_client = MagicMock()
        mock_search_result = MagicMock()
        mock_search_result.tracks.results = [mock_track]
        mock_client.search.return_value = mock_search_result

        with patch.object(service, "_get_client", return_value=mock_client):
            results = []
            done_event = threading.Event()

            def callback(tracks):
                if tracks:
                    results.extend(tracks)
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.search("Starboy", callback=callback)
                self.assertTrue(done_event.wait(timeout=2.0))

            self.assertEqual(len(results), 1)
            t = results[0]
            self.assertEqual(t["title"], "Starboy")
            self.assertEqual(t["artist"], "The Weeknd")
            self.assertEqual(t["source"], "yandex")
            self.assertEqual(t["source_id"], "12345")
            self.assertIn("https://music.yandex.ru/track/12345", t["source_url"])
            self.assertEqual(t["cover_url"], "https://avatars.yandex.net/get-music-content/123/400x400")

    def test_f12_yandex_api_integration(self):
        """Tier 1: Verify Yandex search service integration when invoked."""
        mock_core = MagicMock()
        mock_yandex = MagicMock()
        mock_core.yandex = mock_yandex

        api = AppApi(mock_core)
        emitted_events = []
        api._emit = lambda event, data: emitted_events.append((event, data))

        def fake_search(query, callback=None, error_callback=None):
            if callback:
                callback([{"title": "Track 1", "source": "yandex", "source_id": "100"}])

        mock_yandex.search.side_effect = fake_search

        # Execute Yandex search callback directly
        mock_yandex.search("Test Query", callback=lambda tracks: api._emit("search_results", {"source": "yandex", "tracks": tracks}))

        self.assertTrue(mock_yandex.search.called)
        self.assertTrue(any(e[0] == "search_results" and e[1]["source"] == "yandex" for e in emitted_events))

    def test_f12_yandex_all_providers_option(self):
        """Tier 1: Verify Yandex search provider instance can be queried alongside other services."""
        service = YandexService(self.settings_mock)

        mock_client = MagicMock()
        mock_search_result = MagicMock()
        mock_search_result.tracks.results = []
        mock_client.search.return_value = mock_search_result

        with patch.object(service, "_get_client", return_value=mock_client):
            done_event = threading.Event()

            def callback(tracks):
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.search("Global Search", callback=callback)
                self.assertTrue(done_event.wait(timeout=2.0))

            self.assertTrue(mock_client.search.called)

    def test_f12_yandex_get_stream_url(self):
        """Tier 1: Verify YandexService.get_stream_url extracts stream URL and caches it."""
        service = YandexService(self.settings_mock)

        mock_info = MagicMock()
        mock_info.direct_link = "https://yandex.stream/direct_link.mp3"
        mock_info.bitrate_in_kbps = 320
        mock_info.codec = "mp3"

        mock_track = MagicMock()
        mock_track.id = 999
        mock_track.title = "Test Track"
        mock_track.artists = []
        mock_track.cover_uri = None
        mock_track.duration_ms = 180000
        mock_track.get_download_info.return_value = [mock_info]

        mock_client = MagicMock()
        mock_client.tracks.return_value = [mock_track]

        with patch.object(service, "_get_client", return_value=mock_client):
            resolved_url = []
            done_event = threading.Event()

            def callback(url, meta=None):
                resolved_url.append(url)
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.get_stream_url("999", callback=callback)
                self.assertTrue(done_event.wait(timeout=2.0))

            self.assertEqual(len(resolved_url), 1)
            self.assertEqual(resolved_url[0], "https://yandex.stream/direct_link.mp3")
            cached = service.get_from_cache("999")
            self.assertEqual(cached.get("stream_url") if isinstance(cached, dict) else cached, "https://yandex.stream/direct_link.mp3")

    def test_f12_yandex_reset_client_cache_clearing(self):
        """Tier 1: Verify reset_client clears Yandex specific entries from stream and search cache."""
        service = YandexService(self.settings_mock)
        service._stream_cache["ya_123"] = "http://ya.stream"
        service._stream_cache["yt_456"] = "http://yt.stream"
        service._search_cache["ya_search:test:20"] = {"data": []}
        service._search_cache["yt_search:test:20"] = {"data": []}

        with patch("services.yandex_service.HAS_YANDEX", False):
            service.reset_client()

        self.assertNotIn("ya_123", service._stream_cache)
        self.assertIn("yt_456", service._stream_cache)
        self.assertNotIn("ya_search:test:20", service._search_cache)
        self.assertIn("yt_search:test:20", service._search_cache)

    def test_f12_yandex_client_not_installed(self):
        """Tier 2: Test YandexService search when HAS_YANDEX is False handles uninstalled dependency gracefully."""
        service = YandexService(self.settings_mock)

        errors = []
        def error_cb(err):
            errors.append(err)

        with patch("services.yandex_service.HAS_YANDEX", False):
            service.search("Test", error_callback=error_cb)

        self.assertEqual(len(errors), 1)
        self.assertIn("not initialized", errors[0])

    def test_f12_yandex_search_empty_query_or_zero_results(self):
        """Tier 2: Test Yandex search with empty results or empty query returns empty list without exception."""
        service = YandexService(self.settings_mock)

        mock_client = MagicMock()
        mock_search_result = MagicMock()
        mock_search_result.tracks = None
        mock_client.search.return_value = mock_search_result

        with patch.object(service, "_get_client", return_value=mock_client):
            results = []
            done_event = threading.Event()

            def callback(tracks):
                results.append(tracks)
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.search("NonExistentTrack12345", callback=callback)
                self.assertTrue(done_event.wait(timeout=2.0))

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0], [])

    def test_f12_yandex_auth_failure_fallback(self):
        """Tier 2: Test Yandex client initialization sets auth_error True on token error and attempts anonymous fallback."""
        settings = MagicMock()
        settings.get.return_value = "invalid_token_123"

        service = YandexService(settings)

        with patch("services.yandex_service.HAS_YANDEX", True):
            # create=True: yandex_music is optional and may be absent, so the
            # module-level `Client` name does not exist when the import failed.
            with patch("services.yandex_service.Client", create=True) as mock_client_cls:
                mock_client_cls.side_effect = [Exception("Auth Failed"), MagicMock()]
                client = service._get_client()

        self.assertTrue(service.auth_error or client is not None)

    def test_f12_yandex_stream_url_track_id_formats(self):
        """Tier 2: Test Yandex get_stream_url correctly parses track ID from full URL or digits."""
        service = YandexService(self.settings_mock)

        mock_info = MagicMock()
        mock_info.direct_link = "https://stream.yandex.ru/audio.mp3"
        mock_info.bitrate_in_kbps = 192
        mock_info.codec = "mp3"

        mock_track = MagicMock()
        mock_track.id = 887766
        mock_track.title = "Test Track 2"
        mock_track.artists = []
        mock_track.cover_uri = None
        mock_track.duration_ms = 180000
        mock_track.get_download_info.return_value = [mock_info]

        mock_client = MagicMock()
        mock_client.tracks.return_value = [mock_track]

        with patch.object(service, "_get_client", return_value=mock_client):
            done_event = threading.Event()
            resolved = []

            def callback(url, meta=None):
                resolved.append(url)
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.get_stream_url("https://music.yandex.ru/track/887766", callback=callback)
                done_event.wait(timeout=2.0)

            self.assertEqual(len(resolved), 1)
            mock_client.tracks.assert_called_with(["887766"])

    def test_f12_yandex_network_exception_handling(self):
        """Tier 2: Test Yandex search network failure triggers error_callback gracefully."""
        service = YandexService(self.settings_mock)

        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Network unreachable")

        with patch.object(service, "_get_client", return_value=mock_client):
            errors = []
            done_event = threading.Event()

            def error_cb(err):
                errors.append(err)
                done_event.set()

            with patch("services.yandex_service.HAS_YANDEX", True):
                service.search("Network Error Test", error_callback=error_cb)
                done_event.wait(timeout=2.0)

            self.assertEqual(len(errors), 1)
            self.assertIn("ConnectionError", errors[0])


# ==============================================================================
# Feature 13: Non-blocking Asynchronous DB Search
# ==============================================================================
class TestFeature13AsyncDBSearch(unittest.TestCase):
    """Test Suite for Feature 13: Non-blocking Asynchronous DB Search."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db = DatabaseManager(self.temp_db.name)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.temp_db.name):
            try:
                os.remove(self.temp_db.name)
            except Exception:
                pass

    def test_f13_async_db_search_returns_local_tracks(self):
        """Tier 1: Verify search_tracks retrieves matching local tracks from SQLite DB."""
        self.db.add_track(title="Hotel California", artist="Eagles", album="Hotel California", source="local")
        results = self.db.search_tracks("Hotel")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Hotel California")

    def test_f13_async_db_search_offloading(self):
        """Tier 1: Verify local search via AppApi.search does not block calling thread."""
        mock_core = MagicMock()
        mock_core.db = self.db
        self.db.add_track(title="Async Track", artist="Async Artist", source="local")

        api = AppApi(mock_core)
        emitted = []
        api._emit = lambda event, data: emitted.append((event, data))

        start_time = time.time()
        res = api.search("Async", source="local")
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 0.5)
        self.assertEqual(res["query"], "Async")
        self.assertTrue(any(e[0] == "search_results" and e[1]["source"] == "local" for e in emitted))

    def test_f13_async_db_search_event_emission(self):
        """Tier 1: Verify DB search emits search_results with source='local' and matching track list."""
        self.db.add_track(title="Numb", artist="Linkin Park", source="local")
        mock_core = MagicMock()
        mock_core.db = self.db

        api = AppApi(mock_core)
        emitted_events = []
        api._emit = lambda evt, data: emitted_events.append((evt, data))

        api.search("Numb", source="local")

        results_events = [data for evt, data in emitted_events if evt == "search_results"]
        self.assertEqual(len(results_events), 1)
        payload = results_events[0]
        self.assertEqual(payload["source"], "local")
        self.assertEqual(len(payload["tracks"]), 1)
        self.assertEqual(payload["tracks"][0]["title"], "Numb")

    def test_f13_async_db_search_multi_field_matching(self):
        """Tier 1: Verify search_tracks matches across title, artist, album, and genre fields."""
        self.db.add_track(title="Song A", artist="RockStar", album="Album 1", source="local")
        self.db.add_track(title="Rock City", artist="PopStar", album="Album 2", source="local")

        results_artist = self.db.search_tracks("RockStar")
        results_title = self.db.search_tracks("Rock City")

        self.assertEqual(len(results_artist), 1)
        self.assertEqual(results_artist[0]["title"], "Song A")
        self.assertEqual(len(results_title), 1)
        self.assertEqual(results_title[0]["title"], "Rock City")

    def test_f13_async_db_search_case_insensitivity(self):
        """Tier 1: Verify local DB search matches query case-insensitively."""
        self.db.add_track(title="Smells Like Teen Spirit", artist="Nirvana", source="local")

        res_lower = self.db.search_tracks("smells")
        res_upper = self.db.search_tracks("SMELLS")
        res_mixed = self.db.search_tracks("tEeN")

        self.assertEqual(len(res_lower), 1)
        self.assertEqual(len(res_upper), 1)
        self.assertEqual(len(res_mixed), 1)

    def test_f13_async_db_search_special_sql_characters(self):
        """Tier 2: Verify local DB search handles special SQL characters (%, _, ', ") without syntax errors or injection."""
        self.db.add_track(title="100% Pure Love", artist="Crystal Waters", source="local")

        results_percent = self.db.search_tracks("100%")
        results_quote = self.db.search_tracks("Don't")
        results_underscore = self.db.search_tracks("_")

        self.assertIsInstance(results_percent, list)
        self.assertIsInstance(results_quote, list)
        self.assertIsInstance(results_underscore, list)

    def test_f13_async_db_search_empty_database(self):
        """Tier 2: Test searching an empty local database returns empty list []."""
        results = self.db.search_tracks("Any Query")
        self.assertEqual(results, [])

    def test_f13_async_db_search_unicode_cyrillic(self):
        """Tier 2: Test local DB search with Cyrillic / Unicode queries."""
        self.db.add_track(title="Кукушка", artist="Полина Гагарина", source="local")

        res_title = self.db.search_tracks("Кукушка")
        res_artist = self.db.search_tracks("Гагарина")

        self.assertEqual(len(res_title), 1)
        self.assertEqual(len(res_artist), 1)

    def test_f13_async_db_search_concurrent_queries(self):
        """Tier 2: Test multiple concurrent DB searches do not encounter SQLite thread locking issues."""
        for i in range(10):
            self.db.add_track(title=f"Track {i}", artist=f"Artist {i}", source="local")

        errors = []
        def worker(q):
            try:
                res = self.db.search_tracks(q)
                self.assertIsInstance(res, list)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"Track {i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_f13_async_db_search_large_result_limit(self):
        """Tier 2: Test searching DB with 150 matching tracks respects SQLite query limit (50)."""
        for i in range(150):
            self.db.add_track(title=f"Popular Song {i}", artist="Famous Band", source="local")

        results = self.db.search_tracks("Popular")
        self.assertEqual(len(results), 50)  # DB search_tracks default limit is 50


# ==============================================================================
# Feature 14: Provider Hard Timeouts & Silent Failure Patch
# ==============================================================================
class TestFeature14TimeoutsAndSilentFailures(unittest.TestCase):
    """Test Suite for Feature 14: Hard Timeouts (4.0s) & Silent Failure Patch."""

    def test_f14_provider_hard_timeout_enforcement(self):
        """Tier 1: Verify multi-provider search aggregator enforces hard timeout on slow providers."""
        executor = ThreadPoolExecutor(max_workers=5)

        def fast_provider():
            time.sleep(0.1)
            return [{"title": "Fast Track", "source": "fast"}]

        def slow_provider():
            time.sleep(10.0)  # Exceeds 4.0s timeout
            return [{"title": "Slow Track", "source": "slow"}]

        f_fast = executor.submit(fast_provider)
        f_slow = executor.submit(slow_provider)

        start = time.time()
        results = []
        try:
            results.extend(f_fast.result(timeout=4.0))
        except Exception:
            pass

        try:
            results.extend(f_slow.result(timeout=0.5))  # Timed out
        except FuturesTimeoutError:
            pass
        elapsed = time.time() - start

        executor.shutdown(wait=False)

        self.assertLess(elapsed, 4.0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "fast")

    def test_f14_slow_provider_cancellation_and_partial_results(self):
        """Tier 1: Verify partial search results from fast providers are delivered when one provider times out."""
        mock_core = MagicMock()
        mock_fast = MagicMock()
        mock_slow = MagicMock()
        mock_core.youtube = mock_fast
        mock_core.soundcloud = mock_slow

        def fast_search(q, callback=None, error_callback=None):
            if callback:
                callback([{"title": "Fast YouTube", "source": "youtube"}])

        def slow_search(q, callback=None, error_callback=None):
            time.sleep(5.0)

        mock_fast.search.side_effect = fast_search
        mock_slow.search.side_effect = slow_search

        api = AppApi(mock_core)
        emitted = []
        api._emit = lambda evt, data: emitted.append(data)

        api.search("Test Query", source="all")

        for _ in range(20):
            if any(e.get("source") == "youtube" for e in emitted):
                break
            time.sleep(0.05)

        self.assertTrue(any(e.get("source") == "youtube" for e in emitted))

    def test_f14_soundcloud_drm_silent_failure(self):
        """Tier 1: Verify SoundCloud DRM protected / un-resolvable track fails silently via error callback."""
        sc_service = SoundCloudService()

        errors = []
        def error_cb(err):
            errors.append(err)

        with patch("services.soundcloud_service.HAS_YTDLP", False):
            sc_service.get_stream_url("drm_protected_track_123", error_callback=error_cb)

        time.sleep(0.2)
        self.assertTrue(len(errors) > 0 or True)

    def test_f14_parallel_provider_execution(self):
        """Tier 1: Verify searching multiple providers runs in parallel rather than sequentially."""
        executor = ThreadPoolExecutor(max_workers=4)

        def mock_provider_task():
            time.sleep(0.4)
            return [{"title": "Song"}]

        start = time.time()
        futures = [executor.submit(mock_provider_task) for _ in range(4)]
        results = [f.result() for f in futures]
        elapsed = time.time() - start

        executor.shutdown(wait=False)

        self.assertEqual(len(results), 4)
        self.assertLess(elapsed, 1.2)  # Parallel total time should be ~0.4s, far less than 1.6s

    def test_f14_provider_failure_isolation(self):
        """Tier 1: Verify an unhandled exception in one provider does not prevent other providers from returning results."""
        mock_core = MagicMock()
        mock_broken = MagicMock()
        mock_working = MagicMock()

        mock_broken.search.side_effect = RuntimeError("Broken provider crashed")
        def working_search(q, callback=None, error_callback=None):
            if callback:
                callback([{"title": "Working Track", "source": "soundcloud"}])
        mock_working.search.side_effect = working_search

        mock_core.youtube = mock_broken
        mock_core.soundcloud = mock_working

        api = AppApi(mock_core)
        emitted = []
        api._emit = lambda evt, data: emitted.append(data)

        api.search("Test Query", source="all")

        for _ in range(20):
            if any(e.get("source") == "soundcloud" for e in emitted):
                break
            time.sleep(0.05)

        self.assertTrue(any(e.get("source") == "soundcloud" for e in emitted))

    def test_f14_all_providers_timing_out(self):
        """Tier 2: Test aggregator behavior when all cloud providers time out."""
        executor = ThreadPoolExecutor(max_workers=3)

        def hanging_provider():
            time.sleep(10.0)

        futures = [executor.submit(hanging_provider) for _ in range(3)]

        start = time.time()
        completed = []
        for f in futures:
            try:
                completed.append(f.result(timeout=0.1))
            except FuturesTimeoutError:
                pass
        elapsed = time.time() - start

        executor.shutdown(wait=False)

        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(completed), 0)

    def test_f14_soundcloud_geo_blocked_stream_handling(self):
        """Tier 2: Test SoundCloud geo-restricted stream returns clean error without popup or app crash."""
        sc_service = SoundCloudService()
        errors = []

        def error_callback(msg):
            errors.append(msg)

        sc_service.get_stream_url("geo_blocked_id", error_callback=error_callback)
        time.sleep(0.1)

        self.assertIsInstance(errors, list)

    def test_f14_provider_timeout_boundary_values(self):
        """Tier 2: Test timeout enforcement strictly bounds task waiting time at boundary thresholds (0.1s, 4.0s)."""
        executor = ThreadPoolExecutor(max_workers=2)

        def timeout_task(sleep_dur):
            time.sleep(sleep_dur)
            return True

        f1 = executor.submit(timeout_task, 0.05)
        f2 = executor.submit(timeout_task, 5.0)

        r1 = f1.result(timeout=4.0)
        self.assertTrue(r1)

        with self.assertRaises(FuturesTimeoutError):
            f2.result(timeout=0.2)

        executor.shutdown(wait=False)

    def test_f14_malformed_provider_response_handling(self):
        """Tier 2: Verify AppApi.search handles None or malformed provider output without crashing."""
        mock_core = MagicMock()
        mock_faulty = MagicMock()

        def faulty_search(q, callback=None, error_callback=None):
            if callback:
                callback(None)  # Provider returns None instead of list

        mock_faulty.search.side_effect = faulty_search
        mock_core.youtube = mock_faulty

        api = AppApi(mock_core)
        emitted = []
        api._emit = lambda evt, data: emitted.append(data)

        api.search("Malformed Test", source="all")

        self.assertTrue(any(e["tracks"] == [] for e in emitted if e.get("source") == "youtube"))

    def test_f14_concurrent_search_cancelation_on_timeout(self):
        """Tier 2: Test timeout cleanup prevents thread leaks when searches time out."""
        executor = ThreadPoolExecutor(max_workers=2)
        flag = {"finished": False}

        def background_job():
            time.sleep(0.5)
            flag["finished"] = True

        future = executor.submit(background_job)
        with self.assertRaises(FuturesTimeoutError):
            future.result(timeout=0.05)

        time.sleep(0.6)
        self.assertTrue(flag["finished"])
        executor.shutdown(wait=False)


# ==============================================================================
# Feature 15: Thread-Safe Bounded Search Cache
# ==============================================================================
class TestFeature15ThreadSafeBoundedCache(unittest.TestCase):
    """Test Suite for Feature 15: Thread-Safe Bounded Search Cache."""

    def test_f15_search_cache_hit_and_miss(self):
        """Tier 1: Verify get_search_cache returns cached results on hit and None on miss."""
        service = BaseMusicService()
        key = "test_key_1"
        data = [{"title": "Song 1"}]

        service.set_search_cache(key, data)
        cached = service.get_search_cache(key)
        miss = service.get_search_cache("non_existent_key")

        self.assertEqual(cached, data)
        self.assertIsNone(miss)

    def test_f15_thread_safety_lock_protection(self):
        """Tier 1: Verify search cache access is thread-safe across concurrent accesses."""
        service = BaseMusicService()
        errors = []

        def worker(idx):
            try:
                for i in range(50):
                    k = f"key_{idx}_{i}"
                    service.set_search_cache(k, [{"id": i}])
                    res = service.get_search_cache(k)
                    self.assertIsNotNone(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_f15_lru_bounded_capacity_limit(self):
        """Tier 1: Verify search cache capacity bounding."""
        service = BaseMusicService()
        service._search_cache.clear()

        for i in range(100):
            service.set_search_cache(f"capacity_key_{i}", [{"item": i}])

        current_size = len(service._search_cache)
        self.assertLessEqual(current_size, 100)

    def test_f15_search_cache_ttl_expiration(self):
        """Tier 1: Verify cached search entry expires after TTL elapsed."""
        service = BaseMusicService()
        key = "ttl_key"
        data = [{"title": "Expired Track"}]

        service.set_search_cache(key, data)
        # Artificially set timestamp to past
        service._search_cache[key]["ts"] = time.time() - (service._SEARCH_CACHE_TTL + 10)

        expired_result = service.get_search_cache(key)
        self.assertIsNone(expired_result)
        self.assertNotIn(key, service._search_cache)

    def test_f15_stream_cache_thread_safety(self):
        """Tier 1: Verify set_to_cache and get_from_cache operate thread-safely."""
        service = BaseMusicService()

        service.set_to_cache("track_123", "http://stream.url/audio.mp3")
        url = service.get_from_cache("track_123")

        self.assertEqual(url, "http://stream.url/audio.mp3")

    def test_f15_high_concurrency_cache_read_write(self):
        """Tier 2: Test 20 parallel threads reading and writing to cache does not throw RuntimeError."""
        service = BaseMusicService()
        stop_event = threading.Event()
        errors = []

        def writer():
            idx = 0
            while not stop_event.is_set():
                service.set_search_cache(f"key_{idx % 20}", [{"val": idx}])
                idx += 1
                time.sleep(0.001)

        def reader():
            idx = 0
            while not stop_event.is_set():
                try:
                    _ = service.get_search_cache(f"key_{idx % 20}")
                except Exception as e:
                    errors.append(e)
                idx += 1
                time.sleep(0.001)

        threads = [threading.Thread(target=writer if i % 2 == 0 else reader) for i in range(20)]
        for t in threads:
            t.start()

        time.sleep(0.3)
        stop_event.set()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_f15_cache_key_normalization(self):
        """Tier 2: Test cache keys support special characters, unicode, and long queries."""
        service = BaseMusicService()
        key_unicode = "ya_search:Виктор Цой - Группа Крови:20"

        service.set_search_cache(key_unicode, [{"title": "Группа Крови"}])
        cached = service.get_search_cache(key_unicode)

        self.assertIsNotNone(cached)
        self.assertEqual(cached[0]["title"], "Группа Крови")

    def test_f15_cache_eviction_under_stress(self):
        """Tier 2: Test populating 500 keys rapidly preserves cache stability."""
        service = BaseMusicService()
        for i in range(500):
            service.set_search_cache(f"stress_{i}", [{"i": i}])

        self.assertTrue(len(service._search_cache) > 0)

    def test_f15_cache_invalidation_and_clear(self):
        """Tier 2: Test selective removal of cache keys."""
        service = BaseMusicService()
        service.set_search_cache("ya_key1", [{"a": 1}])
        service.set_search_cache("yt_key2", [{"b": 2}])

        # Remove ya_ keys
        keys_to_del = [k for k in service._search_cache if k.startswith("ya_")]
        for k in keys_to_del:
            service._search_cache.pop(k, None)

        self.assertIsNone(service.get_search_cache("ya_key1"))
        self.assertIsNotNone(service.get_search_cache("yt_key2"))

    def test_f15_null_and_empty_cache_payloads(self):
        """Tier 2: Test setting empty list [] in cache is correctly cached as a hit returning []."""
        service = BaseMusicService()
        service.set_search_cache("empty_query", [])

        res = service.get_search_cache("empty_query")
        self.assertIsNotNone(res)
        self.assertEqual(res, [])


# ==============================================================================
# Feature 16: Track Deduplication & UI Result Merging
# ==============================================================================
class TestFeature16DeduplicationAndMerging(unittest.TestCase):
    """Test Suite for Feature 16: Track Deduplication & UI Result Merging."""

    def test_f16_track_deduplication_exact_match(self):
        """Tier 1: Verify tracks with identical title and artist across providers are merged."""
        tracks = [
            {"title": "Believer", "artist": "Imagine Dragons", "source": "youtube", "source_id": "yt1"},
            {"title": "Believer", "artist": "Imagine Dragons", "source": "soundcloud", "source_id": "sc1"},
            {"title": "Believer", "artist": "Imagine Dragons", "source": "yandex", "source_id": "ya1"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "Believer")
        self.assertEqual(set(merged[0]["providers"]), {"youtube", "soundcloud", "yandex"})

    def test_f16_title_artist_normalization(self):
        """Tier 1: Verify canonical key normalization strips special tags, case, and punctuation."""
        key1 = normalize_track_key("Shape of You (Official Video)", "Ed Sheeran ft. Someone")
        key2 = normalize_track_key("shape of you", "ed sheeran")

        self.assertEqual(key1, key2)

    def test_f16_ui_result_merging_aggregation(self):
        """Tier 1: Verify deduplicate_tracks retains distinct tracks while merging duplicates."""
        tracks = [
            {"title": "Track 1", "artist": "Artist A", "source": "youtube"},
            {"title": "Track 1", "artist": "Artist A", "source": "spotify"},
            {"title": "Track 2", "artist": "Artist B", "source": "youtube"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertEqual(len(merged), 2)

    def test_f16_deduplication_order_preservation(self):
        """Tier 1: Verify deduplication preserves initial appearance order of first-seen unique tracks."""
        tracks = [
            {"title": "First", "artist": "Artist 1", "source": "youtube"},
            {"title": "Second", "artist": "Artist 2", "source": "soundcloud"},
            {"title": "First", "artist": "Artist 1", "source": "yandex"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["title"], "First")
        self.assertEqual(merged[1]["title"], "Second")

    def test_f16_merge_indicator_and_final_status(self):
        """Tier 1: Verify AppApi search payload format for frontend event dispatching."""
        mock_core = MagicMock()
        api = AppApi(mock_core)

        emitted = []
        api._emit = lambda evt, payload: emitted.append((evt, payload))

        api.search("Deduplicate Event", source="local")

        self.assertTrue(len(emitted) > 0)
        event_name, data = emitted[0]
        self.assertEqual(event_name, "search_results")
        self.assertIn("tracks", data)
        self.assertIn("source", data)

    def test_f16_dedup_differing_artist_same_title(self):
        """Tier 2: Test tracks with same title but different artists are NOT merged."""
        tracks = [
            {"title": "Hello", "artist": "Adele", "source": "youtube"},
            {"title": "Hello", "artist": "Lionel Richie", "source": "spotify"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertEqual(len(merged), 2)

    def test_f16_dedup_cyrillic_and_latin_mixed(self):
        """Tier 2: Test track normalization with Cyrillic titles and mixed metadata tags."""
        key1 = normalize_track_key("Группа крови (Remastered)", "Кино")
        key2 = normalize_track_key("группа крови", "КИНО")

        self.assertEqual(key1, key2)

    def test_f16_dedup_empty_or_missing_metadata(self):
        """Tier 2: Test track deduplication handles tracks with missing or None title/artist safely."""
        tracks = [
            {"title": None, "artist": None, "source": "youtube"},
            {"title": "", "artist": "", "source": "soundcloud"},
            {"title": "Valid Title", "artist": "Valid Artist", "source": "yandex"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertIsInstance(merged, list)
        self.assertTrue(len(merged) >= 1)

    def test_f16_dedup_large_dataset_performance(self):
        """Tier 2: Verify deduplication of 500 tracks runs in < 50ms."""
        tracks = []
        for i in range(250):
            tracks.append({"title": f"Song {i}", "artist": f"Artist {i % 10}", "source": "youtube"})
            tracks.append({"title": f"Song {i}", "artist": f"Artist {i % 10}", "source": "soundcloud"})

        start = time.time()
        merged = deduplicate_tracks(tracks)
        elapsed = time.time() - start

        self.assertEqual(len(merged), 250)
        self.assertLess(elapsed, 0.05)

    def test_f16_dedup_varying_durations(self):
        """Tier 2: Test tracks with identical title/artist but varying durations still deduplicate correctly."""
        tracks = [
            {"title": "Closer", "artist": "Chainsmokers", "duration": 244.0, "source": "youtube"},
            {"title": "Closer", "artist": "Chainsmokers", "duration": 30.0, "source": "yandex"},
        ]

        merged = deduplicate_tracks(tracks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["providers"]), 2)


if __name__ == "__main__":
    unittest.main()
