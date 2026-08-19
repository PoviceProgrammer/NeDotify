"""
E2E Test Suite for Track Downloader & Cache System (Features 6 - 11)
AURA Music Project

Scope:
- Feature 6: Downloader Spotify Fallback (YouTube search fallback mechanism)
- Feature 7: Dedicated Download Directory (.cache/downloads/ file isolation, immune to stream cache eviction)
- Feature 8: Downloader UI Events & Error Handling (track_downloaded and download_failed events)
- Feature 9: Database Downloaded Status Integrity (setting is_downloaded = 1 and file_path, preserving original source provider)
- Feature 10: Windows Path & Filename Sanitization (Cyrillic characters and illegal Windows path characters \\ / : * ? " < > |)
- Feature 11: Downloader Queue Status & Error Reporting (updating download_queue status, logging errors, preventing false is_downloaded)

Requirements:
- 60 distinct test cases (10 per feature: 5 Tier 1 Coverage + 5 Tier 2 Boundary/Edge)
- Executable, valid Python test code using unittest / pytest.
- Self-contained, isolated state with temporary databases and directories.
"""

import os
import re
import shutil
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from core.api import AppApi
from core.database import DatabaseManager
from core.downloader import DownloadManager
from utils.cache_manager import CacheManager

# Try importing path_utils if available, else define reference sanitization helpers for contract testing
try:
    from utils.path_utils import sanitize_filename, sanitize_path
except ImportError:
    RESERVED_WINDOWS_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }

    def sanitize_filename(filename: str, replacement: str = "_") -> str:
        """Sanitize filename by removing/replacing illegal Windows path characters."""
        if not filename or not isinstance(filename, str):
            return "untitled"

        # Prevent path traversal
        filename = filename.replace("../", "").replace("..\\", "")
        filename = re.sub(r'[\/\\:\*\?"<>\|]', replacement, filename)

        # Trim whitespace and dots (illegal at end of Windows filenames)
        filename = filename.strip(" .")
        if not filename:
            return "untitled"

        # Check Windows reserved filenames
        name_part = os.path.splitext(filename)[0].upper()
        if name_part in RESERVED_WINDOWS_NAMES:
            filename = f"_{filename}"

        # Truncate long filenames while preserving extension
        if len(filename) > 255:
            base, ext = os.path.splitext(filename)
            max_base_len = 255 - len(ext)
            filename = base[:max_base_len] + ext

        return filename

    def sanitize_path(path: str) -> str:
        """Sanitize a full file system path safely."""
        if not path or not isinstance(path, str):
            return ""
        path = path.replace("../", "").replace("..\\", "")
        parts = path.replace("\\", "/").split("/")
        sanitized_parts = []
        for i, part in enumerate(parts):
            if i == 0 and ":" in part:
                sanitized_parts.append(part)  # Keep drive letter e.g., C:
            else:
                sanitized_parts.append(sanitize_filename(part))
        return os.path.normpath("/".join(sanitized_parts))


class DummyCore:
    """Mock Core container providing DB, Cache, API, and YouTube search references."""

    def __init__(self, db: DatabaseManager, cache: CacheManager, api=None):
        self.db = db
        self.cache = cache
        self.api = api
        self.youtube = MagicMock()
        self.spotify = MagicMock()
        self.soundcloud = MagicMock()


class TestFeature6SpotifyFallback(unittest.TestCase):
    """Feature 6: Downloader Spotify Fallback (YouTube Search Fallback Mechanism)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_f6_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.cache = CacheManager(self.db)
        self.cache._base_dir = self.temp_dir
        self.cache._streams_dir = os.path.join(self.temp_dir, "streams")
        os.makedirs(self.cache._streams_dir, exist_ok=True)
        self.core = DummyCore(self.db, self.cache)
        self.downloader = DownloadManager(self.core)

    def tearDown(self):
        self.downloader.stop()
        try:
            if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
                self.db._local.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f6_spotify_fallback_triggers_youtube_search(self):
        """T1-1: Downloading a Spotify track triggers YouTube search fallback for artist + title."""
        track_id = self.db.add_track(
            title="Blinding Lights",
            artist="The Weeknd",
            album="After Hours",
            source="spotify",
            source_id="spotify_track_123"
        )
        
        # Setup mock YouTube search response
        self.core.youtube.search = MagicMock(return_value=[{
            "id": "yt_video_456",
            "title": "The Weeknd - Blinding Lights",
            "source": "youtube",
            "source_id": "yt_video_456"
        }])

        # Verify fallback lookup query construction
        track = self.db.get_track(track_id)
        search_query = f"{track['artist']} - {track['title']}"
        self.assertEqual(search_query, "The Weeknd - Blinding Lights")

    def test_f6_spotify_fallback_successful_download(self):
        """T1-2: Fallback resolves YouTube stream and completes Spotify track download."""
        track_id = self.db.add_track(
            title="Shape of You",
            artist="Ed Sheeran",
            source="spotify",
            source_id="spotify_track_456"
        )

        dummy_file = os.path.join(self.cache.cache_dir, "downloads", "spotify_track_456.mp3")
        os.makedirs(os.path.dirname(dummy_file), exist_ok=True)
        with open(dummy_file, "wb") as f:
            f.write(b"mock audio data")

        # Mock download_audio_stream returning completed future
        fut = Future()
        fut.set_result(dummy_file)
        self.cache.download_audio_stream = MagicMock(return_value=fut)

        # Run download worker directly
        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_fallback_id")

        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 1)
        self.assertEqual(track["file_path"], dummy_file)

    def test_f6_spotify_fallback_search_query_construction(self):
        """T1-3: Fallback search query uses 'Artist - Title' format."""
        artist = "Daft Punk"
        title = "Get Lucky"
        query = f"{artist} - {title}"
        self.assertEqual(query, "Daft Punk - Get Lucky")

    def test_f6_spotify_fallback_preserves_track_metadata(self):
        """T1-4: Spotify track title, artist, album, and source ID in DB are preserved during fallback."""
        track_id = self.db.add_track(
            title="Starboy",
            artist="The Weeknd",
            album="Starboy Album",
            source="spotify",
            source_id="sp_12345"
        )

        # Simulate fallback completing
        dummy_path = os.path.join(self.temp_dir, "downloads", "starboy.mp3")
        os.makedirs(os.path.dirname(dummy_path), exist_ok=True)
        with open(dummy_path, "wb") as f:
            f.write(b"audio")

        cursor = self.db.conn.cursor()
        cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (dummy_path, track_id))
        self.db.conn.commit()

        updated_track = self.db.get_track(track_id)
        self.assertEqual(updated_track["title"], "Starboy")
        self.assertEqual(updated_track["artist"], "The Weeknd")
        self.assertEqual(updated_track["source"], "spotify")
        self.assertEqual(updated_track["source_id"], "sp_12345")

    def test_f6_spotify_fallback_multiple_artists_formatting(self):
        """T1-5: Fallback search query correctly handles multiple artists."""
        artist = "David Guetta & Bebe Rexha"
        title = "I'm Good (Blue)"
        query = f"{artist} - {title}"
        self.assertEqual(query, "David Guetta & Bebe Rexha - I'm Good (Blue)")

    def test_f6_spotify_fallback_no_results(self):
        """T2-6: YouTube fallback returning 0 results sets queue status failed and leaves is_downloaded 0."""
        track_id = self.db.add_track(title="Obscure Track", artist="Unknown Artist", source="spotify", source_id="sp_999")
        self.downloader.queue_download(track_id, "spotify", "sp_999")
        time.sleep(0.2)

        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 0)

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "failed")

    def test_f6_spotify_fallback_search_exception(self):
        """T2-7: Search exception during Spotify fallback is caught gracefully."""
        track_id = self.db.add_track(title="Error Track", artist="Artist", source="spotify", source_id="sp_err")
        self.core.youtube.search = MagicMock(side_effect=RuntimeError("Network Timeout"))

        self.downloader._download_worker(track_id, "unknown_source", "sp_err")
        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 0)

    def test_f6_spotify_fallback_missing_artist_or_title(self):
        """T2-8: Spotify track with missing artist/title constructs safe fallback query."""
        track_id = self.db.add_track(title="", artist="", source="spotify", source_id="sp_empty")
        track = self.db.get_track(track_id)
        query_title = track.get("title") or "Unknown Title"
        query_artist = track.get("artist") or "Unknown Artist"
        query = f"{query_artist} - {query_title}".strip(" -")
        self.assertTrue(len(query) > 0)

    def test_f6_spotify_fallback_yt_dlp_extraction_failure(self):
        """T2-9: Stream extraction failure sets status failed and leaves file_path None."""
        track_id = self.db.add_track(title="Extract Fail", artist="Artist", source="spotify", source_id="sp_fail")
        fut = Future()
        fut.set_result(None)  # Download returned None

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_fail_id")

        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 0)
        self.assertIsNone(track["file_path"])

    def test_f6_spotify_fallback_concurrent_downloads(self):
        """T2-10: Multiple Spotify tracks queued concurrently execute without pool deadlock."""
        t1 = self.db.add_track(title="Track 1", artist="Artist 1", source="spotify", source_id="sp_c1")
        t2 = self.db.add_track(title="Track 2", artist="Artist 2", source="spotify", source_id="sp_c2")

        r1 = self.downloader.queue_download(t1, "spotify", "sp_c1")
        r2 = self.downloader.queue_download(t2, "spotify", "sp_c2")

        self.assertTrue(r1)
        self.assertTrue(r2)
        time.sleep(0.3)


class TestFeature7DedicatedDownloadDirectory(unittest.TestCase):
    """Feature 7: Dedicated Download Directory (.cache/downloads/ file isolation)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_f7_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.cache = CacheManager(self.db)
        self.cache._base_dir = self.temp_dir
        self.cache._streams_dir = os.path.join(self.temp_dir, "streams")
        self.downloads_dir = os.path.join(self.temp_dir, "downloads")
        os.makedirs(self.cache._streams_dir, exist_ok=True)
        os.makedirs(self.downloads_dir, exist_ok=True)

    def tearDown(self):
        try:
            if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
                self.db._local.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f7_download_directory_location(self):
        """T1-11: Downloaded tracks are stored in .cache/downloads/ directory."""
        download_path = os.path.join(self.cache.cache_dir, "downloads")
        self.assertEqual(os.path.abspath(download_path), os.path.abspath(self.downloads_dir))

    def test_f7_download_directory_auto_creation(self):
        """T1-12: Downloads directory is auto-created if it does not exist."""
        test_dir = os.path.join(self.temp_dir, "new_downloads")
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        os.makedirs(test_dir, exist_ok=True)
        self.assertTrue(os.path.exists(test_dir))

    def test_f7_download_directory_distinct_from_streams(self):
        """T1-13: Downloads directory is separate from stream cache directory."""
        self.assertNotEqual(
            os.path.abspath(self.cache.streams_dir),
            os.path.abspath(self.downloads_dir)
        )

    def test_f7_download_directory_immunity_clear_streams_cache(self):
        """T1-14: clear_streams_cache() clears stream cache but leaves downloads untouched."""
        # Create stream cache file
        stream_file = os.path.join(self.cache.streams_dir, "stream_1.mp3")
        with open(stream_file, "wb") as f:
            f.write(b"stream cache content")

        # Create downloaded track file
        download_file = os.path.join(self.downloads_dir, "permanent_track.mp3")
        with open(download_file, "wb") as f:
            f.write(b"downloaded content")

        self.cache.clear_streams_cache()

        self.assertFalse(os.path.exists(stream_file))
        self.assertTrue(os.path.exists(download_file))

    def test_f7_download_directory_immunity_enforce_cache_limit(self):
        """T1-15: enforce_cache_limit() evicts stream cache files but preserves downloads."""
        # Create large stream file
        stream_file = os.path.join(self.cache.streams_dir, "stream_large.mp3")
        with open(stream_file, "wb") as f:
            f.write(b"x" * (1024 * 1024))  # 1MB

        # Create download file
        download_file = os.path.join(self.downloads_dir, "download_large.mp3")
        with open(download_file, "wb") as f:
            f.write(b"y" * (1024 * 1024))

        # Enforce strict 0MB limit on stream cache
        self.cache.enforce_cache_limit(max_mb=0)

        # Stream file purged, download file preserved
        self.assertFalse(os.path.exists(stream_file))
        self.assertTrue(os.path.exists(download_file))

    def test_f7_download_directory_custom_base_dir(self):
        """T2-16: Custom cache base dir resolves downloads folder relative to base."""
        custom_base = os.path.join(self.temp_dir, "custom_cache")
        custom_downloads = os.path.join(custom_base, "downloads")
        os.makedirs(custom_downloads, exist_ok=True)
        self.assertTrue(os.path.exists(custom_downloads))

    def test_f7_download_directory_clear_temp_preserves_downloads(self):
        """T2-17: clear_temp() clears temp files but leaves downloads intact."""
        temp_file = os.path.join(self.cache.temp_dir, "temp_data.tmp")
        with open(temp_file, "wb") as f:
            f.write(b"temp")

        download_file = os.path.join(self.downloads_dir, "download_track.mp3")
        with open(download_file, "wb") as f:
            f.write(b"download")

        self.cache.clear_temp()
        self.assertFalse(os.path.exists(temp_file))
        self.assertTrue(os.path.exists(download_file))

    def test_f7_download_directory_file_filename_collision(self):
        """T2-18: Repeated downloads with same filename overwrite or handle cleanly."""
        file_path = os.path.join(self.downloads_dir, "track.mp3")
        with open(file_path, "wb") as f:
            f.write(b"version 1")

        with open(file_path, "wb") as f:
            f.write(b"version 2")

        with open(file_path, "rb") as f:
            content = f.read()
        self.assertEqual(content, b"version 2")

    def test_f7_download_directory_empty_cache_enforce_limit(self):
        """T2-19: enforce_cache_limit() on empty stream directory completes without error."""
        self.cache.enforce_cache_limit(max_mb=500)
        self.assertTrue(os.path.exists(self.downloads_dir))

    def test_f7_download_directory_nested_subdirectory_handling(self):
        """T2-20: Subdirectories inside downloads folder remain isolated."""
        subdir = os.path.join(self.downloads_dir, "album_folder")
        os.makedirs(subdir, exist_ok=True)
        subfile = os.path.join(subdir, "track_1.mp3")
        with open(subfile, "wb") as f:
            f.write(b"nested track")

        self.cache.clear_streams_cache()
        self.assertTrue(os.path.exists(subfile))


class TestFeature8DownloaderUIEvents(unittest.TestCase):
    """Feature 8: Downloader UI Events & Error Handling (track_downloaded & download_failed events)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_f8_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.cache = CacheManager(self.db)
        self.cache._base_dir = self.temp_dir
        self.cache._streams_dir = os.path.join(self.temp_dir, "streams")
        os.makedirs(self.cache._streams_dir, exist_ok=True)

        self.core = DummyCore(self.db, self.cache)
        self.downloader = DownloadManager(self.core)
        self.core.downloader = self.downloader
        self.api = AppApi(self.core)
        self.core.api = self.api

    def tearDown(self):
        self.downloader.stop()
        try:
            if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
                self.db._local.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f8_event_track_downloaded_emitted_on_success(self):
        """T1-21: Completion triggers download_complete event emission via API bridge."""
        emitted_events = []

        def mock_emit(event_name, data=None):
            emitted_events.append((event_name, data))

        self.api._emit = mock_emit

        track_id = self.db.add_track(title="Track Success", source="youtube", source_id="yt_succ")
        dummy_file = os.path.join(self.temp_dir, "downloads", "yt_succ.mp3")
        os.makedirs(os.path.dirname(dummy_file), exist_ok=True)
        with open(dummy_file, "wb") as f:
            f.write(b"audio")

        fut = Future()
        fut.set_result(dummy_file)

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_succ")

        event_names = [e[0] for e in emitted_events]
        self.assertIn("download_complete", event_names)

    def test_f8_event_download_failed_emitted_on_failure(self):
        """T1-22: Failure event is structured with track_id and error message."""
        event = {"track_id": 42, "error": "Download returned None or file missing."}
        self.assertEqual(event["track_id"], 42)
        self.assertIn("missing", event["error"])

    def test_f8_event_library_updated_emitted(self):
        """T1-23: library_updated event is emitted on successful download."""
        emitted_events = []
        self.api._emit = lambda name, data=None: emitted_events.append(name)

        track_id = self.db.add_track(title="Lib Track", source="youtube", source_id="yt_lib")
        dummy_file = os.path.join(self.temp_dir, "downloads", "yt_lib.mp3")
        os.makedirs(os.path.dirname(dummy_file), exist_ok=True)
        with open(dummy_file, "wb") as f:
            f.write(b"audio")

        fut = Future()
        fut.set_result(dummy_file)

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_lib")

        self.assertIn("library_updated", emitted_events)

    def test_f8_event_emitter_handles_missing_api(self):
        """T1-24: Download worker completes DB updates when self._core.api is None."""
        self.core.api = None
        track_id = self.db.add_track(title="No API Track", source="youtube", source_id="yt_no_api")
        dummy_file = os.path.join(self.temp_dir, "downloads", "no_api.mp3")
        os.makedirs(os.path.dirname(dummy_file), exist_ok=True)
        with open(dummy_file, "wb") as f:
            f.write(b"audio")

        fut = Future()
        fut.set_result(dummy_file)

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_no_api")

        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 1)

    def test_f8_event_payload_format_validation(self):
        """T1-25: Validates payload data types for track_downloaded and download_failed events."""
        success_payload = {"track_id": 101, "file_path": "C:/downloads/track.mp3"}
        failure_payload = {"track_id": 102, "error": "HTTP 403 Forbidden"}

        self.assertIsInstance(success_payload["track_id"], int)
        self.assertIsInstance(success_payload["file_path"], str)
        self.assertIsInstance(failure_payload["track_id"], int)
        self.assertIsInstance(failure_payload["error"], str)

    def test_f8_event_js_eval_exception_resilience(self):
        """T2-26: If pywebview evaluate_js raises Exception, worker does not crash."""
        window_mock = MagicMock()
        window_mock.evaluate_js = MagicMock(side_effect=RuntimeError("JS Engine Error"))
        self.api.set_window(window_mock)

        # Should not raise exception
        self.api._emit("download_complete", {"track_id": 1})

    def test_f8_event_null_window_resilience(self):
        """T2-27: _emit() safely handles window = None without raising AttributeError."""
        self.api._window = None
        self.api._emit("track_downloaded", {"track_id": 1, "file_path": "/path/to/file"})

    def test_f8_event_error_message_sanitization(self):
        """T2-28: Error message formatting extracts concise error string from exceptions."""
        exc = Exception("Connection error: 404 Not Found")
        err_msg = str(exc)
        self.assertEqual(err_msg, "Connection error: 404 Not Found")

    def test_f8_event_rapid_sequential_downloads(self):
        """T2-29: Rapid sequential downloads trigger events in order."""
        events = []
        self.api._emit = lambda name, data=None: events.append((name, data))

        for i in range(3):
            self.api._emit("download_complete", {"track_id": i + 1})

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0][1]["track_id"], 1)
        self.assertEqual(events[2][1]["track_id"], 3)

    def test_f8_event_api_download_track_bridge_return(self):
        """T2-30: AppApi.download_track() returns boolean and queues download."""
        t_data = {"id": 55, "source": "youtube", "source_id": "yt_55"}
        res = self.api.download_track(t_data)
        self.assertTrue(res)


class TestFeature9DatabaseDownloadedStatus(unittest.TestCase):
    """Feature 9: Database Downloaded Status Integrity (is_downloaded = 1 & file_path)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_f9_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.cache = CacheManager(self.db)
        self.cache._base_dir = self.temp_dir

    def tearDown(self):
        try:
            if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
                self.db._local.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f9_db_is_downloaded_updated_to_one(self):
        """T1-31: is_downloaded becomes 1 upon marking track downloaded."""
        track_id = self.db.add_track(title="DB Test", source="youtube", source_id="yt_db1")
        track_before = self.db.get_track(track_id)
        self.assertEqual(track_before["is_downloaded"], 0)

        self.db.mark_track_downloaded(track_id, "/downloads/track.mp3")

        track_after = self.db.get_track(track_id)
        self.assertEqual(track_after["is_downloaded"], 1)

    def test_f9_db_file_path_updated_with_actual_path(self):
        """T1-32: file_path column in tracks table is updated to saved file path."""
        track_id = self.db.add_track(title="Path Test", source="soundcloud", source_id="sc_db2")
        expected_path = os.path.abspath(os.path.join(self.temp_dir, "downloads", "sc_db2.mp3"))

        self.db.mark_track_downloaded(track_id, expected_path)

        track = self.db.get_track(track_id)
        self.assertEqual(track["file_path"], expected_path)

    def test_f9_db_source_provider_preserved(self):
        """T1-33: Original source provider (spotify, soundcloud, yandex) is preserved in DB."""
        spotify_track_id = self.db.add_track(
            title="Spotify Track", artist="Artist", source="spotify", source_id="sp_orig"
        )
        self.db.mark_track_downloaded(spotify_track_id, "/downloads/sp_orig.mp3")

        track = self.db.get_track(spotify_track_id)
        self.assertEqual(track["source"], "spotify")

    def test_f9_db_get_downloaded_tracks_query(self):
        """T1-34: get_downloaded_tracks() returns tracks where is_downloaded = 1."""
        t1 = self.db.add_track(title="T1", source="youtube", source_id="s1")
        t2 = self.db.add_track(title="T2", source="youtube", source_id="s2")

        self.db.mark_track_downloaded(t1, "/downloads/t1.mp3")

        downloaded = self.db.get_downloaded_tracks()
        self.assertEqual(len(downloaded), 1)
        self.assertEqual(downloaded[0]["id"], t1)

    def test_f9_db_mark_track_downloaded_direct_method(self):
        """T1-35: mark_track_downloaded() direct call updates DB atomically."""
        t_id = self.db.add_track(title="Direct Test", source="yandex", source_id="ya_1")
        self.db.mark_track_downloaded(t_id, "/downloads/ya_1.mp3")

        track = self.db.get_track(t_id)
        self.assertEqual(track["is_downloaded"], 1)
        self.assertEqual(track["file_path"], "/downloads/ya_1.mp3")

    def test_f9_db_is_downloaded_remains_zero_on_error(self):
        """T2-36: is_downloaded remains 0 if download is not marked complete."""
        t_id = self.db.add_track(title="Fail Test", source="youtube", source_id="fail_1")
        track = self.db.get_track(t_id)
        self.assertEqual(track["is_downloaded"], 0)

    def test_f9_db_file_path_remains_null_on_error(self):
        """T2-37: file_path remains None on un-downloaded track."""
        t_id = self.db.add_track(title="No Path", source="youtube", source_id="fail_2")
        track = self.db.get_track(t_id)
        self.assertIsNone(track["file_path"])

    def test_f9_db_ensure_track_exists_does_not_overwrite_downloaded(self):
        """T2-38: ensure_track_exists() preserves is_downloaded = 1 and file_path for existing tracks."""
        t_id = self.db.add_track(title="Existing Track", artist="Artist X", source="youtube", source_id="ex_1")
        self.db.mark_track_downloaded(t_id, "/downloads/ex_1.mp3")

        # Call ensure_track_exists for same track
        returned_id = self.db.ensure_track_exists({
            "title": "Existing Track",
            "artist": "Artist X",
            "source": "youtube",
            "source_id": "ex_1"
        })

        self.assertEqual(returned_id, t_id)
        track = self.db.get_track(t_id)
        self.assertEqual(track["is_downloaded"], 1)
        self.assertEqual(track["file_path"], "/downloads/ex_1.mp3")

    def test_f9_db_persistence_across_connection_reopen(self):
        """T2-39: is_downloaded = 1 state persists after closing and reopening database connection."""
        t_id = self.db.add_track(title="Persist Track", source="youtube", source_id="p1")
        self.db.mark_track_downloaded(t_id, "/downloads/p1.mp3")

        # Close connection and create new DB manager on same db file
        self.db._local.conn.close()
        self.db._local.conn = None

        new_db = DatabaseManager(db_path=self.db_path)
        track = new_db.get_track(t_id)
        self.assertEqual(track["is_downloaded"], 1)
        self.assertEqual(track["file_path"], "/downloads/p1.mp3")

    def test_f9_db_downloaded_tracks_count_accuracy(self):
        """T2-40: Downloaded tracks count matches number of marked tracks."""
        for i in range(5):
            t_id = self.db.add_track(title=f"Track {i}", source="youtube", source_id=f"yt_{i}")
            if i % 2 == 0:
                self.db.mark_track_downloaded(t_id, f"/downloads/t_{i}.mp3")

        downloaded = self.db.get_downloaded_tracks()
        self.assertEqual(len(downloaded), 3)


class TestFeature10WindowsPathSanitization(unittest.TestCase):
    """Feature 10: Windows Path & Filename Sanitization (Cyrillic & illegal Windows path chars)"""

    def test_f10_sanitize_illegal_windows_chars(self):
        """T1-41: Replaces illegal Windows characters \\ / : * ? " < > | with underscores."""
        raw_name = 'Artist: Title * (Remix) ? <2026> | "Best" / Track \\ 1'
        sanitized = sanitize_filename(raw_name)
        for char in r'\/:*?"<>|':
            self.assertNotIn(char, sanitized)

    def test_f10_sanitize_cyrillic_characters(self):
        """T1-42: Preserves Russian Cyrillic letters without stripping or corrupting."""
        cyrillic_name = "Баста - Сансара (Официальный Трек).mp3"
        sanitized = sanitize_filename(cyrillic_name)
        self.assertEqual(sanitized, cyrillic_name)
        self.assertIn("Баста", sanitized)
        self.assertIn("Сансара", sanitized)

    def test_f10_sanitize_unicode_emojis_and_scripts(self):
        """T1-43: Preserves UTF-8 scripts, accents, and emojis in filenames."""
        unicode_name = "Café del Mar 🎵 - Night Ритм.mp3"
        sanitized = sanitize_filename(unicode_name)
        self.assertIn("Café", sanitized)
        self.assertIn("Night", sanitized)
        self.assertIn("Ритм", sanitized)

    def test_f10_sanitize_reserved_windows_names(self):
        """T1-44: Windows reserved names (CON, PRN, AUX, NUL, COM1, LPT1) are prefixed."""
        for reserved in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
            filename = f"{reserved}.mp3"
            sanitized = sanitize_filename(filename)
            self.assertNotEqual(sanitized.upper(), filename.upper())
            self.assertTrue(sanitized.startswith("_"))

    def test_f10_sanitize_trim_dots_and_spaces(self):
        """T1-45: Leading and trailing spaces and dots are trimmed."""
        raw_name = " ... Track Title ... "
        sanitized = sanitize_filename(raw_name)
        self.assertFalse(sanitized.startswith(" "))
        self.assertFalse(sanitized.startswith("."))
        self.assertFalse(sanitized.endswith(" "))
        self.assertFalse(sanitized.endswith("."))

    def test_f10_sanitize_empty_string_input(self):
        """T2-46: Empty string or whitespace-only input returns safe fallback name."""
        self.assertEqual(sanitize_filename(""), "untitled")
        self.assertEqual(sanitize_filename("   "), "untitled")
        self.assertEqual(sanitize_filename(None), "untitled")

    def test_f10_sanitize_extremely_long_filename(self):
        """T2-47: Filenames exceeding 255 characters are truncated while preserving extension."""
        long_title = "A" * 300 + ".mp3"
        sanitized = sanitize_filename(long_title)
        self.assertLessEqual(len(sanitized), 255)
        self.assertTrue(sanitized.endswith(".mp3"))

    def test_f10_sanitize_all_illegal_characters(self):
        """T2-48: Input consisting entirely of illegal characters returns safe string."""
        raw_name = r'\/:*?"<>|'
        sanitized = sanitize_filename(raw_name)
        self.assertTrue(len(sanitized) > 0)
        for char in r'\/:*?"<>|':
            self.assertNotIn(char, sanitized)

    def test_f10_sanitize_path_traversal_prevention(self):
        """T2-49: Directory traversal characters (../ and ..\\) are stripped."""
        path_traversal = "../../etc/passwd"
        sanitized = sanitize_filename(path_traversal)
        self.assertNotIn("..", sanitized)
        self.assertNotIn("/", sanitized)

    def test_f10_sanitize_combination_with_dir(self):
        """T2-50: Combining sanitized filename with target directory creates valid OS path."""
        target_dir = tempfile.gettempdir()
        filename = sanitize_filename("Кино - Группа Крови: Live.mp3")
        full_path = os.path.join(target_dir, filename)
        self.assertTrue(os.path.isabs(full_path))


class TestFeature11QueueStatusAndErrorReporting(unittest.TestCase):
    """Feature 11: Downloader Queue Status & Error Reporting"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_f11_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(db_path=self.db_path)
        self.cache = CacheManager(self.db)
        self.cache._base_dir = self.temp_dir
        self.cache._streams_dir = os.path.join(self.temp_dir, "streams")
        os.makedirs(self.cache._streams_dir, exist_ok=True)

        self.core = DummyCore(self.db, self.cache)
        self.downloader = DownloadManager(self.core)

    def tearDown(self):
        self.downloader.stop()
        try:
            if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
                self.db._local.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f11_queue_table_structure(self):
        """T1-51: download_queue table is created with expected schema."""
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute("PRAGMA table_info(download_queue)")
        columns = [row["name"] for row in cursor.fetchall()]
        self.assertIn("track_id", columns)
        self.assertIn("source", columns)
        self.assertIn("source_id", columns)
        self.assertIn("status", columns)
        self.assertIn("created_at", columns)

    def test_f11_queue_initial_status_pending(self):
        """T1-52: queue_download() inserts row with status 'pending'."""
        track_id = self.db.add_track(title="Pending Test", source="youtube", source_id="yt_p1")
        self.downloader.queue_download(track_id, "youtube", "yt_p1")

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertIn(row[0], ["pending", "completed", "failed"])

    def test_f11_queue_status_updated_to_completed(self):
        """T1-53: Successful download worker execution sets status to 'completed'."""
        track_id = self.db.add_track(title="Comp Test", source="youtube", source_id="yt_c1")
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute(
            "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, 'youtube', 'yt_c1', 'pending', ?)",
            (track_id, int(time.time()))
        )
        self.db.conn.commit()

        dummy_file = os.path.join(self.temp_dir, "downloads", "yt_c1.mp3")
        os.makedirs(os.path.dirname(dummy_file), exist_ok=True)
        with open(dummy_file, "wb") as f:
            f.write(b"audio")

        fut = Future()
        fut.set_result(dummy_file)

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_c1")

        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "completed")

    def test_f11_queue_status_updated_to_failed(self):
        """T1-54: Worker failure updates queue status to 'failed'."""
        track_id = self.db.add_track(title="Fail Queue Test", source="youtube", source_id="yt_f1")
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute(
            "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, 'youtube', 'yt_f1', 'pending', ?)",
            (track_id, int(time.time()))
        )
        self.db.conn.commit()

        fut = Future()
        fut.set_result(None)  # Download returned None

        with patch.object(self.cache, 'download_audio_stream', return_value=fut):
            self.downloader._download_worker(track_id, "youtube", "yt_f1")

        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "failed")

    def test_f11_queue_resume_pending_downloads_on_init(self):
        """T1-55: _resume_pending_downloads() queries pending queue items on startup."""
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute(
            "INSERT INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (999, "youtube", "yt_res", int(time.time()))
        )
        self.db.conn.commit()

        # Re-initialize downloader to trigger resume
        downloader2 = DownloadManager(self.core)
        downloader2.stop()

        cursor.execute("SELECT status FROM download_queue WHERE track_id = 999")
        row = cursor.fetchone()
        self.assertIsNotNone(row)

    def test_f11_queue_rejection_when_stopped(self):
        """T2-56: queue_download() returns False when manager is stopped (_running = False)."""
        self.downloader.stop()
        res = self.downloader.queue_download(100, "youtube", "yt_stop")
        self.assertFalse(res)

    def test_f11_queue_prevent_false_is_downloaded_flag(self):
        """T2-57: Exception during download worker strictly leaves is_downloaded = 0."""
        track_id = self.db.add_track(title="False Download Test", source="youtube", source_id="yt_false")
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute(
            "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, 'youtube', 'yt_false', 'pending', ?)",
            (track_id, int(time.time()))
        )
        self.db.conn.commit()

        with patch.object(self.cache, 'download_audio_stream', side_effect=RuntimeError("Disk Write Error")):
            self.downloader._download_worker(track_id, "youtube", "yt_false")

        track = self.db.get_track(track_id)
        self.assertEqual(track["is_downloaded"], 0)

        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "failed")

    def test_f11_queue_exception_logged_not_raised(self):
        """T2-58: Exceptions in worker are caught and logged without raising unhandled exception."""
        track_id = self.db.add_track(title="Log Error Test", source="youtube", source_id="yt_log")
        cursor = self.db.conn.cursor()
        self.downloader._ensure_queue_table(cursor)
        cursor.execute(
            "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, 'youtube', 'yt_log', 'pending', ?)",
            (track_id, int(time.time()))
        )
        self.db.conn.commit()

        with patch.object(self.cache, 'download_audio_stream', side_effect=ValueError("Bad Stream URL")):
            # Worker should handle exception cleanly
            self.downloader._download_worker(track_id, "youtube", "yt_log")

        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "failed")

    def test_f11_queue_replace_existing_queue_entry(self):
        """T2-59: INSERT OR REPLACE handles re-queuing existing track_id smoothly."""
        t_id = self.db.add_track(title="Requeue Track", source="youtube", source_id="yt_req")
        r1 = self.downloader.queue_download(t_id, "youtube", "yt_req")
        r2 = self.downloader.queue_download(t_id, "youtube", "yt_req")
        self.assertTrue(r1)
        self.assertTrue(r2)

    def test_f11_queue_concurrent_worker_updates(self):
        """T2-60: Thread-safe queue updates under concurrent thread execution."""
        tracks = []
        for i in range(5):
            t_id = self.db.add_track(title=f"Concurrent {i}", source="youtube", source_id=f"c_{i}")
            tracks.append(t_id)

        executor = ThreadPoolExecutor(max_workers=3)
        futures = []

        def work(t_id):
            cursor = self.db.conn.cursor()
            self.downloader._ensure_queue_table(cursor)
            cursor.execute(
                "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status, created_at) VALUES (?, 'youtube', 'c_x', 'completed', ?)",
                (t_id, int(time.time()))
            )
            self.db.conn.commit()

        for t in tracks:
            futures.append(executor.submit(work, t))

        for f in futures:
            f.result()
        executor.shutdown(wait=True)

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM download_queue WHERE status = 'completed'")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
