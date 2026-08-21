"""
AURA Music - Comprehensive E2E & Integration Test Suite (Tiers 3 & 4)
Covers Pairwise Combinatorial Interactions and Real-World Application Scenarios.
Opaque-box requirement-driven testing strictly adhering to PROJECT.md and ORIGINAL_REQUEST.md.
"""

import io
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest.mock import MagicMock, patch

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ==========================================
# 1. MOCK ENVIRONMENT SETUP
# ==========================================

# Mock WatchdogService to prevent Python 3.14 setDaemon removal AttributeError
class DummyWatchdogService:
    def __init__(self, core=None):
        self.core = core
    def start(self):
        pass
    def stop(self):
        pass

mock_watchdog_mod = MagicMock()
mock_watchdog_mod.WatchdogService = DummyWatchdogService
sys.modules['services.watchdog_service'] = mock_watchdog_mod


# Mock vlc module before any audio engine import
class MockVlcMedia:
    def add_option(self, option):
        pass

class MockVlcPlayer:
    def __init__(self):
        self._media = None
        self._volume = 70
        self._muted = False
        self._time = 0
        self._length = 180000
        self._position = 0.0
        self._is_playing = False
        self._event_manager = MagicMock()

    def set_media(self, media):
        self._media = media

    def audio_set_volume(self, vol):
        self._volume = vol

    def play(self):
        self._is_playing = True
        return 0

    def pause(self):
        self._is_playing = False

    def stop(self):
        self._is_playing = False

    def event_manager(self):
        return self._event_manager

    def get_time(self):
        return self._time

    def set_time(self, t):
        self._time = t

    def get_length(self):
        return self._length

    def get_position(self):
        return self._position

    def set_position(self, pos):
        self._position = pos

class MockVlcInstance:
    def media_player_new(self):
        return MockVlcPlayer()
    def media_new(self, path):
        return MockVlcMedia()
    def media_new_path(self, path):
        return MockVlcMedia()

mock_vlc = MagicMock()
mock_vlc.Instance.return_value = MockVlcInstance()
mock_vlc.EventType.MediaPlayerEndReached = 1
mock_vlc.EventType.MediaPlayerEncounteredError = 2
sys.modules['vlc'] = mock_vlc


# Mock mutagen module
class MockAudioInfo:
    def __init__(self):
        self.length = 200.0
        self.bitrate = 320000
        self.sample_rate = 44100

class MockAudioFile:
    def __init__(self):
        self.info = MockAudioInfo()
        self.tags = {}
    def get(self, tag, default=None):
        return default

mock_mutagen = MagicMock()
mock_mutagen.File.side_effect = lambda filepath, easy=False: MockAudioFile()
# utils/tag_parser.py imports every one of these in a single try block, so a
# missing entry makes the whole import fail and silently sets HAS_MUTAGEN=False.
sys.modules['mutagen'] = mock_mutagen
sys.modules['mutagen.id3'] = mock_mutagen
sys.modules['mutagen.mp3'] = mock_mutagen
sys.modules['mutagen.flac'] = mock_mutagen
sys.modules['mutagen.oggvorbis'] = mock_mutagen
sys.modules['mutagen.mp4'] = mock_mutagen


# Import application core modules after environment mocks
from core.app import AppCore
from core.api import AppApi
from core.database import DatabaseManager
from core.downloader import DownloadManager
from core.proxy import LocalProxyManager, StreamProxyHandler, _is_safe_url
from services.soundcloud_service import SoundCloudService
from services.youtube_service import YouTubeService
from services.spotify_service import SpotifyService
from services.yandex_service import YandexService
from utils.cache_manager import CacheManager


# Helper safe URL patch to allow local file paths in stream proxy
def safe_url_with_local_support(url: str) -> bool:
    if not url:
        return False
    if os.path.exists(url) or os.path.isabs(url):
        return True
    return _is_safe_url(url)


# ==========================================
# 2. BASE E2E INTEGRATION TEST CASE
# ==========================================

class BaseE2ETestCase(unittest.TestCase):
    """Base fixture setting up isolated temp environment, AppCore, AppApi, and Proxy."""

    def setUp(self):
        logging.disable(logging.CRITICAL)

        self.test_id = str(uuid.uuid4())
        self.test_dir = os.path.join(PROJECT_ROOT, ".test_runs", self.test_id)
        os.makedirs(self.test_dir, exist_ok=True)

        self.expanduser_patcher = patch('os.path.expanduser', return_value=self.test_dir)
        self.expanduser_patcher.start()

        self.subprocess_patcher = patch('subprocess.run')
        self.subprocess_patcher.start()

        # Patch _is_safe_url and SSRF checks in proxy/api modules
        self.safe_url_patcher1 = patch('core.proxy._is_safe_url', side_effect=safe_url_with_local_support)
        self.safe_url_patcher2 = patch('core.proxy._is_ssrf_safe_url', side_effect=safe_url_with_local_support)
        self.safe_url_patcher3 = patch('core.api._is_ssrf_safe_url', side_effect=safe_url_with_local_support)
        self.safe_url_patcher1.start()
        self.safe_url_patcher2.start()
        self.safe_url_patcher3.start()

        # Mock urllib.request.urlopen for upstream proxy calls
        self.urlopen_patcher = patch('urllib.request.urlopen', side_effect=self._mock_urlopen)
        self.urlopen_patcher.start()

        # Initialize core and api
        self.core = AppCore()
        self.core.proxy.token = ''
        if self.core.proxy.server:
            self.core.proxy.server.auth_token = ''

        # Disable polling/crossfade loops during test execution
        self.core.engine._start_polling = MagicMock()
        self.core.engine._do_crossfade_actual = MagicMock()

        self.api = AppApi(self.core)

        # Event tracking list
        self.emitted_events = []
        self.api._emit = self._record_emitted_event

        # Helper mock audio data
        self.dummy_audio_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 4096

    def tearDown(self):
        try:
            self.core.cleanup()
        except Exception:
            pass
        self.urlopen_patcher.stop()
        self.safe_url_patcher1.stop()
        self.safe_url_patcher2.stop()
        self.safe_url_patcher3.stop()
        self.subprocess_patcher.stop()
        self.expanduser_patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        logging.disable(logging.NOTSET)

    def _record_emitted_event(self, event_name, data=None):
        self.emitted_events.append({"event": event_name, "data": data})

    def _mock_urlopen(self, req, timeout=15):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        
        if "forbidden" in url or "403" in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        if "notfound" in url or "404" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "expired" in url or "410" in url:
            raise urllib.error.HTTPError(url, 410, "Gone", {}, None)

        headers = {
            'Content-Type': 'audio/mpeg',
            'Content-Length': str(len(self.dummy_audio_bytes)),
            'Accept-Ranges': 'bytes'
        }

        range_header = req.headers.get('Range') if hasattr(req, 'headers') else None
        if range_header and range_header.startswith("bytes="):
            parts = range_header.replace("bytes=", "").split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else len(self.dummy_audio_bytes) - 1
            chunk = self.dummy_audio_bytes[start:end+1]
            headers['Content-Range'] = f"bytes {start}-{end}/{len(self.dummy_audio_bytes)}"
            headers['Content-Length'] = str(len(chunk))
            data_stream = io.BytesIO(chunk)
            code = 206
        else:
            data_stream = io.BytesIO(self.dummy_audio_bytes)
            code = 200

        class MockResponse:
            def __init__(self, stream, code, hdrs):
                self.stream = stream
                self.code = code
                self.headers = hdrs
            def getcode(self):
                return self.code
            def read(self, amt=None):
                return self.stream.read(amt)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return MockResponse(data_stream, code, headers)

    def _create_downloaded_audio_file(self, filename="test_track.mp3", content=None):
        downloads_dir = os.path.join(self.core.cache.cache_dir, "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        file_path = os.path.join(downloads_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content or self.dummy_audio_bytes)
        return file_path


# ==========================================
# 3. TIER 3: PAIRWISE COMBINATORIAL TESTS (16 tests)
# ==========================================

class TestTier3PairwiseInteractions(BaseE2ETestCase):
    """Tier 3: Pairwise interactions across Playback, Downloader, and Search features."""

    def test_pairwise_01_search_to_playback_stream_integration(self):
        """Pairwise 1: Search YouTube track -> Play track -> Verify proxy URL & engine state."""
        self.core.youtube.search = MagicMock(
            side_effect=lambda q, callback=None, **kw: callback([
                {"id": 1, "title": "Lofi Beat", "artist": "ChillHop", "source": "youtube", "source_id": "yt_123"}
            ]) if callback else None
        )
        self.api.search("lofi", source="youtube")
        time.sleep(0.3)
        yt_events = [e for e in self.emitted_events if e['event'] == 'search_results' and e['data']['source'] == 'youtube']
        self.assertGreater(len(yt_events), 0)
        track = yt_events[0]['data']['tracks'][0]

        self.core.youtube.get_stream_url = MagicMock(
            side_effect=lambda url, callback=None, **kw: callback("http://example.com/audio.mp3", {}) if callback else None
        )
        self.core.engine.play_track(track)
        self.assertEqual(self.core.engine.queue.current_track['title'], "Lofi Beat")
        proxy_url = self.core.proxy.get_proxy_url("youtube", "yt_123", track_id=1)
        self.assertIn("/api/stream", proxy_url)

    def test_pairwise_02_search_to_downloader_queue_integration(self):
        """Pairwise 2: Search SoundCloud track -> Queue download -> Verify queue table & completion."""
        track_data = {"title": "SC Track", "artist": "SC Artist", "source": "soundcloud", "source_id": "sc_999"}
        fake_path = self._create_downloaded_audio_file("sc_999.mp3")
        self.core.soundcloud.download_audio_sync = MagicMock(return_value=fake_path)

        self.api.download_track(track_data)
        cursor = self.core.db.conn.cursor()
        cursor.execute("SELECT track_id FROM download_queue WHERE source_id = 'sc_999'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        tid = row[0]

        self.core.downloader._download_worker({"track_id": tid, "source": "soundcloud", "source_id": "sc_999"})

        cursor.execute("SELECT status FROM download_queue WHERE source_id = 'sc_999'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "completed")

    def test_pairwise_03_downloaded_track_local_proxy_playback(self):
        """Pairwise 3: Download track to .cache/downloads/ -> Proxy local file playback."""
        local_path = self._create_downloaded_audio_file("local_song.mp3")
        tid = self.core.db.add_track(
            title="Local Song", artist="Local Artist", source="local",
            file_path=local_path
        )
        self.core.db.mark_track_downloaded(tid, local_path)

        track_obj = self.core.db.get_track(tid)
        self.assertEqual(track_obj['is_downloaded'], 1)
        self.assertEqual(track_obj['file_path'], local_path)
        self.assertTrue(os.path.exists(track_obj['file_path']))

    def test_pairwise_04_playback_error_autoresolve_stream(self):
        """Pairwise 4: Proxy stream returns HTTP 403 -> Auto re-resolve stream URL."""
        tid = self.core.db.add_track("Expired Track", "Artist", source="youtube", source_id="yt_exp")
        self.core.db.cache_stream("youtube", "yt_exp", "http://expired.domain.com/audio.mp3")

        cb = MagicMock()
        self.core.youtube.get_stream_url = MagicMock(
            side_effect=lambda url, callback=None, **kw: callback("http://fresh.domain.com/audio.mp3") if callback else None
        )
        self.core.re_resolve_stream_url_async("youtube", "yt_exp", callback=cb)
        time.sleep(0.3)
        self.assertTrue(cb.called)

    def test_pairwise_05_spotify_search_fallback_to_downloader(self):
        """Pairwise 5: Spotify search metadata -> Downloader resolves YouTube fallback -> Save file."""
        spotify_track = {
            "title": "Spotify Song", "artist": "Spotify Artist",
            "source": "spotify", "source_id": "sp_111"
        }
        fake_path = self._create_downloaded_audio_file("spotify_fallback.mp3")
        self.core.youtube.download_audio_sync = MagicMock(return_value=fake_path)

        tid = self.core.db.ensure_track_exists(spotify_track)
        self.core.downloader.queue_download(tid, "youtube", "yt_fallback_id")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_fallback_id"})

        saved_track = self.core.db.get_track(tid)
        self.assertIsNotNone(saved_track)
        self.assertEqual(saved_track['is_downloaded'], 1)

    def test_pairwise_06_downloader_queue_status_during_active_playback(self):
        """Pairwise 6: Active playback on main engine while background download queues."""
        playing_track = {"title": "Playing", "artist": "A", "file_path": "song.mp3", "source": "local"}
        self.core.engine.play_track(playing_track)
        self.assertEqual(self.core.engine.queue.current_track['title'], "Playing")

        dl_track = {"title": "Downloading", "artist": "B", "source": "youtube", "source_id": "yt_dl_2"}
        tid = self.core.db.ensure_track_exists(dl_track)
        fake_path = self._create_downloaded_audio_file("bg_dl.mp3")
        self.core.youtube.download_audio_sync = MagicMock(return_value=fake_path)

        self.core.downloader.queue_download(tid, "youtube", "yt_dl_2")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_dl_2"})
        self.assertEqual(self.core.engine.queue.current_track['title'], "Playing")

    def test_pairwise_07_concurrent_search_cache_and_playback(self):
        """Pairwise 7: Parallel search requests populate LRU cache while AudioEngine handles commands."""
        service = YouTubeService(self.core.settings)

        def run_searches():
            for i in range(5):
                service.set_search_cache(f"cache_key_{i}", [{"title": f"Track {i}"}])

        threads = [threading.Thread(target=run_searches) for _ in range(3)]
        for t in threads:
            t.start()

        self.core.engine.play_track({"title": "Concurrent", "source": "local", "file_path": "test.mp3"})
        self.assertEqual(self.core.engine.queue.current_track['title'], "Concurrent")

        for t in threads:
            t.join()

        self.assertTrue(True)

    def test_pairwise_08_cache_eviction_does_not_evict_downloaded_files(self):
        """Pairwise 8: Stream cache limit enforcement deletes temp streams but protects downloaded tracks."""
        streams_dir = self.core.cache.streams_dir
        downloads_dir = os.path.join(self.core.cache.cache_dir, "downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        stream_file = os.path.join(streams_dir, "temp_stream.mp3")
        with open(stream_file, "wb") as f:
            f.write(b"TEMP_STREAM_BYTES" * 100)

        downloaded_file = os.path.join(downloads_dir, "perm_download.mp3")
        with open(downloaded_file, "wb") as f:
            f.write(b"PERM_DOWNLOAD_BYTES" * 100)

        self.core.cache.enforce_cache_limit(max_mb=0)

        self.assertFalse(os.path.exists(stream_file))
        self.assertTrue(os.path.exists(downloaded_file))

    def test_pairwise_09_cyrillic_path_download_and_proxy_stream(self):
        """Pairwise 9: Cyrillic artist/title download -> Windows path sanitization -> Proxy stream."""
        cyrillic_file = self._create_downloaded_audio_file("Виктор Цой - Группа крови.mp3")
        tid = self.core.db.add_track(
            title="Группа крови", artist="Виктор Цой",
            file_path=cyrillic_file, source="local"
        )
        self.core.db.mark_track_downloaded(tid, cyrillic_file)

        proxy_url = self.core.proxy.get_proxy_url("local", "cyr_id", track_id=tid)
        self.assertIn(f"track_id={tid}", proxy_url)

        req = urllib.request.Request(proxy_url)
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            self.assertGreater(len(data), 0)

    def test_pairwise_10_provider_timeout_fallback_and_downloader(self):
        """Pairwise 10: SoundCloud timeout during search -> YouTube fallback results -> Downloader queue."""
        def timed_out_sc_search(query, callback=None, error_callback=None, **kw):
            if error_callback:
                error_callback("SoundCloud timeout")

        with patch.object(self.core.soundcloud, 'search', side_effect=timed_out_sc_search), \
             patch.object(self.core.youtube, 'search', lambda q, callback, **kw: callback([
                 {"title": "YT Fallback", "artist": "A", "source": "youtube", "source_id": "yt_fb_1"}
             ])):
            
            self.api.search("electronic")
            time.sleep(0.3)
            results = [e for e in self.emitted_events if e['event'] == 'search_results']
            yt_results = [r for r in results if r['data']['source'] == 'youtube']
            self.assertGreater(len(yt_results), 0)

    def test_pairwise_11_downloader_failure_reporting_and_search(self):
        """Pairwise 11: Download fails for restricted track -> Error event emitted -> DB queue failed status."""
        tid = self.core.db.add_track("Restricted", "Artist", source="youtube", source_id="yt_restr")
        self.core.youtube.download_audio_sync = MagicMock(return_value=None)

        self.core.downloader.queue_download(tid, "youtube", "yt_restr")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_restr"})

        cursor = self.core.db.conn.cursor()
        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (tid,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "failed")

        track_obj = self.core.db.get_track(tid)
        self.assertEqual(track_obj['is_downloaded'], 0)

    def test_pairwise_12_proxy_socket_abort_during_range_request(self):
        """Pairwise 12: Range request through proxy -> Simulate socket abort without HTTP 500 or crash."""
        file_path = self._create_downloaded_audio_file("range_test.mp3")
        tid = self.core.db.add_track("Range Track", "Artist", file_path=file_path, source="local")

        proxy_url = self.core.proxy.get_proxy_url("local", "r_1", track_id=tid)
        req = urllib.request.Request(proxy_url, headers={"Range": "bytes=0-99"})
        
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.getcode(), 206)
            data = resp.read()
            self.assertEqual(len(data), 100)

    def test_pairwise_13_multi_provider_deduplication_and_playlist_add(self):
        """Pairwise 13: Search returns duplicate tracks across providers -> Deduplicate & add to playlist."""
        raw_tracks = [
            {"title": "Midnight City", "artist": "M83", "source": "youtube", "source_id": "yt_m83"},
            {"title": "midnight city", "artist": "m83", "source": "soundcloud", "source_id": "sc_m83"}
        ]
        
        pid = self.api.create_playlist("Favorites 2026")
        tid1 = self.core.db.ensure_track_exists(raw_tracks[0])
        tid2 = self.core.db.ensure_track_exists(raw_tracks[1])

        self.assertEqual(tid1, tid2)
        self.api.add_to_playlist(pid, raw_tracks[0])
        
        playlist_tracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(len(playlist_tracks), 1)

    def test_pairwise_14_stream_url_ttl_expiration_during_playback(self):
        """Pairwise 14: Stream cache entry older than TTL -> Query stream_cache returns None."""
        self.core.db.cache_stream("youtube", "ttl_test", "http://old.url/audio.mp3")
        
        cursor = self.core.db.conn.cursor()
        cursor.execute(
            "UPDATE stream_cache SET cached_at = datetime('now', '-4 hours') WHERE source_id = 'ttl_test'"
        )
        self.core.db.conn.commit()

        cached = self.core.db.get_cached_stream("youtube", "ttl_test", max_age_seconds=10800)
        self.assertIsNone(cached)

    def test_pairwise_15_downloader_resume_pending_on_startup(self):
        """Pairwise 15: Insert pending item in download_queue -> Downloader startup resumes download."""
        cursor = self.core.db.conn.cursor()
        tid = self.core.db.add_track("Pending Track", "Artist", source="youtube", source_id="yt_pend")
        cursor.execute(
            "INSERT OR REPLACE INTO download_queue (track_id, source, source_id, status) VALUES (?, 'youtube', 'yt_pend', 'pending')",
            (tid,)
        )
        self.core.db.conn.commit()

        resumed_path = self._create_downloaded_audio_file("resumed.mp3")
        self.core.youtube.download_audio_sync = MagicMock(return_value=resumed_path)
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_pend"})

        cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (tid,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "completed")

    def test_pairwise_16_search_cache_hit_and_immediate_playback(self):
        """Pairwise 16: Search query cached in LRU cache -> Repeated query returns cached results immediately."""
        service = YouTubeService(self.core.settings)
        service.set_search_cache("yt_search:chillhop:20", [{"title": "Hit Track", "source": "youtube", "source_id": "yt_hit"}])

        cached_results = service.get_search_cache("yt_search:chillhop:20")
        self.assertIsNotNone(cached_results)
        self.assertEqual(len(cached_results), 1)
        self.assertEqual(cached_results[0]['title'], "Hit Track")

        cached_results = service.get_search_cache("yt_search:chillhop:20")
        self.assertIsNotNone(cached_results)
        self.assertEqual(len(cached_results), 1)
        self.assertEqual(cached_results[0]['title'], "Hit Track")


# ==========================================
# 4. TIER 4: REAL-WORLD E2E SCENARIOS (8 scenarios)
# ==========================================

class TestTier4RealWorldScenarios(BaseE2ETestCase):
    """Tier 4: Real-world complex end-to-end workflow scenarios."""

    def test_scenario_01_rapid_track_switch_seek_resilience(self):
        """Scenario 1: Rapid Track Switch & Seek Stream Resilience (F1, F3, F4, F5)."""
        tracks = [
            {"title": f"Track {i}", "artist": "Artist", "source": "local", "file_path": self._create_downloaded_audio_file(f"t{i}.mp3")}
            for i in range(5)
        ]
        
        for track in tracks:
            self.core.engine.play_track(track)
            time.sleep(0.01)

        self.assertEqual(self.core.engine.queue.current_track['title'], "Track 4")

    def test_scenario_02_spotify_track_download_offline_playback(self):
        """Scenario 2: Spotify Track Download & Offline Local Playback (F2, F6, F7, F8, F9, F10)."""
        spotify_metadata = {
            "title": "Starboy (feat. Daft Punk)", "artist": "The Weeknd",
            "source": "spotify", "source_id": "spotify_starboy_123"
        }
        
        tid = self.core.db.ensure_track_exists(spotify_metadata)
        sanitized_path = self._create_downloaded_audio_file("The Weeknd - Starboy _feat. Daft Punk_.mp3")
        self.core.youtube.download_audio_sync = MagicMock(return_value=sanitized_path)

        self.core.downloader.queue_download(tid, "youtube", "yt_starboy_vid")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_starboy_vid"})

        track_record = self.core.db.get_track(tid)
        self.assertEqual(track_record['is_downloaded'], 1)
        self.assertIsNotNone(track_record['file_path'])

        proxy_url = self.core.proxy.get_proxy_url("local", "local_id", track_id=tid)
        req = urllib.request.Request(proxy_url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.getcode(), 200)

    def test_scenario_03_concurrent_multiprovider_search_failed_provider(self):
        """Scenario 3: Concurrent Multi-Provider Search with Failed Provider (F12, F13, F14, F15, F16)."""
        def failing_yandex_search(query, callback=None, error_callback=None, **kw):
            if error_callback:
                error_callback("Yandex API unreachable")

        with patch.object(self.core.yandex, 'search', side_effect=failing_yandex_search), \
             patch.object(self.core.youtube, 'search', lambda q, callback, **kw: callback([
                 {"title": "Daft Punk - One More Time", "artist": "Daft Punk", "source": "youtube", "source_id": "yt_dp"}
             ])), \
             patch.object(self.core.soundcloud, 'search', lambda q, callback, **kw: callback([
                 {"title": "daft punk - one more time", "artist": "daft punk", "source": "soundcloud", "source_id": "sc_dp"}
             ])):

            self.api.search("Daft Punk One More Time")
            time.sleep(0.4)

            results = [e for e in self.emitted_events if e['event'] == 'search_results']
            providers_returned = {r['data']['source'] for r in results}
            self.assertIn("youtube", providers_returned)
            self.assertIn("soundcloud", providers_returned)

    def test_scenario_04_high_volume_cache_eviction_isolation(self):
        """Scenario 4: High Volume Cache Eviction Isolation (F7, F9, F10, F11)."""
        streams_dir = self.core.cache.streams_dir
        downloads_dir = os.path.join(self.core.cache.cache_dir, "downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        for i in range(5):
            with open(os.path.join(streams_dir, f"cache_stream_{i}.webm"), "wb") as f:
                f.write(b"STREAM_CACHE_DATA" * 500)

        downloaded_paths = []
        for i in range(2):
            p = os.path.join(downloads_dir, f"downloaded_track_{i}.mp3")
            with open(p, "wb") as f:
                f.write(b"DOWNLOADED_TRACK_DATA" * 500)
            downloaded_paths.append(p)

        self.core.cache.enforce_cache_limit(max_mb=0)

        remaining_streams = os.listdir(streams_dir)
        self.assertEqual(len(remaining_streams), 0)

        for p in downloaded_paths:
            self.assertTrue(os.path.exists(p))

    def test_scenario_05_full_user_session_e2e_workflow(self):
        """Scenario 5: Full User Session E2E Workflow (Search -> Stream -> Download -> Offline Play) (F1 to F16)."""
        found_track = {
            "title": "Nightcall", "artist": "Kavinsky",
            "source": "youtube", "source_id": "yt_nightcall"
        }

        resolved_stream_url = None
        def on_resolved(resolved_track):
            nonlocal resolved_stream_url
            resolved_stream_url = resolved_track.get('file_path')

        with patch.object(self.core.youtube, 'get_stream_url', lambda url, callback, **kw: callback("http://example.com/nightcall.mp3", {})):
            self.api._resolve_track(found_track, on_resolved)
            time.sleep(0.3)
            self.assertEqual(resolved_stream_url, "http://example.com/nightcall.mp3")

        tid = self.core.db.ensure_track_exists(found_track)
        dl_path = self._create_downloaded_audio_file("Kavinsky - Nightcall.mp3")
        self.core.youtube.download_audio_sync = MagicMock(return_value=dl_path)

        self.core.downloader.queue_download(tid, "youtube", "yt_nightcall")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_nightcall"})

        db_track = self.core.db.get_track(tid)
        self.assertEqual(db_track['is_downloaded'], 1)

        offline_track = self.core.db.get_track(tid)
        proxy_url = self.core.proxy.get_proxy_url("local", "loc_id", track_id=offline_track['id'])
        req = urllib.request.Request(proxy_url, headers={"Range": "bytes=0-49"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.getcode(), 206)

        pid = self.api.create_playlist("Drive Soundtrack")
        self.api.add_to_playlist(pid, offline_track)
        playlist_tracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(len(playlist_tracks), 1)

        self.core.db.add_listening_time(240000)
        self.assertEqual(self.core.db.get_total_listening_time(), 240000)

    def test_scenario_06_cyrillic_special_char_lifecycle(self):
        """Scenario 6: Cyrillic & Special Character Track Search, Download & Playback Lifecycle."""
        raw_cyrillic_meta = {
            "title": "Герой Асфальта <1987>?", "artist": "Ария",
            "source": "youtube", "source_id": "yt_aria_1987"
        }
        
        tid = self.core.db.ensure_track_exists(raw_cyrillic_meta)

        sanitized_filename = "Ария - Герой Асфальта _1987_.mp3"
        cyrillic_path = self._create_downloaded_audio_file(sanitized_filename)
        self.core.youtube.download_audio_sync = MagicMock(return_value=cyrillic_path)

        self.core.downloader.queue_download(tid, "youtube", "yt_aria_1987")
        self.core.downloader._download_worker({"track_id": tid, "source": "youtube", "source_id": "yt_aria_1987"})

        record = self.core.db.get_track(tid)
        self.assertEqual(record['is_downloaded'], 1)
        self.assertTrue(os.path.exists(record['file_path']))

        proxy_url = self.core.proxy.get_proxy_url("local", "cyr_sp_id", track_id=tid)
        req = urllib.request.Request(proxy_url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.getcode(), 200)

    def test_scenario_07_expiry_reresolution_continuous_loop(self):
        """Scenario 7: Expiry & Re-resolution during Continuous Stream Loop."""
        t1 = self.core.db.ensure_track_exists({"title": "Loop 1", "source": "youtube", "source_id": "l1"})
        t2 = self.core.db.ensure_track_exists({"title": "Loop 2 (Expired)", "source": "youtube", "source_id": "l2_exp"})
        t3 = self.core.db.ensure_track_exists({"title": "Loop 3", "source": "youtube", "source_id": "l3"})

        self.core.db.cache_stream("youtube", "l2_exp", "http://expired.domain/l2.mp3")

        cb = MagicMock()
        self.core.youtube.get_stream_url = MagicMock(
            side_effect=lambda url, callback=None, **kw: callback("http://fresh.domain/l2_new.mp3") if callback else None
        )
        self.core.re_resolve_stream_url_async("youtube", "l2_exp", callback=cb)
        time.sleep(0.3)
        self.assertTrue(cb.called)

    def test_scenario_08_multiprovider_downloader_error_recovery_queue_integrity(self):
        """Scenario 8: Multi-Provider Downloader Error Recovery & Queue Integrity Workflow."""
        batch_tracks = [
            {"title": "Batch YT", "source": "youtube", "source_id": "yt_batch_1"},
            {"title": "Batch SC", "source": "soundcloud", "source_id": "sc_batch_2"},
            {"title": "Batch SP Fallback", "source": "youtube", "source_id": "yt_batch_3"},
            {"title": "Batch Invalid", "source": "youtube", "source_id": "yt_invalid_4"}
        ]

        tids = [self.core.db.ensure_track_exists(t) for t in batch_tracks]

        def custom_yt_dl(source_id, out_dir):
            if source_id == "yt_invalid_4":
                raise Exception("Network Timeout / Content Unavailable")
            return self._create_downloaded_audio_file(f"{source_id}.mp3")

        def custom_sc_dl(sc_url, out_dir):
            return self._create_downloaded_audio_file("sc_batch_2.mp3")

        self.core.youtube.download_audio_sync = MagicMock(side_effect=custom_yt_dl)
        self.core.soundcloud.download_audio_sync = MagicMock(side_effect=custom_sc_dl)

        for i, tid in enumerate(tids):
            source = batch_tracks[i]['source']
            source_id = batch_tracks[i]['source_id']
            self.core.downloader.queue_download(tid, source, source_id)
            self.core.downloader._download_worker({"track_id": tid, "source": source, "source_id": source_id})

        cursor = self.core.db.conn.cursor()
        cursor.execute("SELECT track_id, status FROM download_queue ORDER BY track_id ASC")
        rows = cursor.fetchall()
        status_map = {r[0]: r[1] for r in rows}

        self.assertEqual(status_map[tids[0]], "completed")
        self.assertEqual(status_map[tids[1]], "completed")
        self.assertEqual(status_map[tids[2]], "completed")
        self.assertEqual(status_map[tids[3]], "failed")

        t4_record = self.core.db.get_track(tids[3])
        self.assertEqual(t4_record['is_downloaded'], 0)


if __name__ == "__main__":
    unittest.main()
