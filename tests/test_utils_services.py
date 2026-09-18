import os
import math
import time
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from core.database import DatabaseManager
from utils.cache_manager import CacheManager
from utils.file_scanner import FileScanner
from services.lyrics_service import LyricsService
from services.artist_service import ArtistService
from services.lastfm_service import LastFMService


class TestCacheManagerUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_test_cm_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(self.db_path)
        self.cm = CacheManager(self.db)
        # Override paths to temporary directory
        self.cm._base_dir = self.temp_dir
        self.cm._covers_dir = os.path.join(self.temp_dir, "covers")
        self.cm._streams_dir = os.path.join(self.temp_dir, "streams")
        self.cm._temp_dir = os.path.join(self.temp_dir, "temp")
        for d in [self.cm._covers_dir, self.cm._streams_dir, self.cm._temp_dir]:
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        try:
            if hasattr(self.cm, "shutdown"):
                self.cm.shutdown()
            self.db.close()
        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_manager_path_traversal_sanitization(self):
        """BUG-032: source or source_id with directory traversal must not escape streams_dir."""
        malicious_source = "../../etc"
        malicious_id = "passwd"
        url = "https://example.com/audio.mp3"

        with patch.object(self.cm._executor, "submit") as mock_submit:
            self.cm.download_audio_stream(malicious_source, malicious_id, url)
            for call_args in mock_submit.call_args_list:
                fn = call_args[0][0]
                if fn.__name__ == "_download_task":
                    with self.cm._active_downloads_lock:
                        for act in self.cm._active_downloads:
                            self.assertNotIn("/", act)
                            self.assertNotIn("\\", act)
                            self.assertNotIn("..", act)

    def test_cache_manager_purge_thread_safety(self):
        """BUG-032: concurrent purge_stream_cache calls must not race or raise exceptions."""
        for i in range(10):
            fp = os.path.join(self.cm._streams_dir, f"cached_track_{i}.mp3")
            with open(fp, "wb") as f:
                f.write(b"0" * 1024)

        errors = []

        def run_purge():
            try:
                for _ in range(5):
                    self.cm.purge_stream_cache(quota_bytes=2048)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_purge) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_cache_manager_negative_quota_and_storage_details(self):
        """BUG-032: negative quota must be sanitized to 0 and not cause infinite loops or exceptions."""
        freed = self.cm.purge_stream_cache(quota_bytes=-500)
        self.assertIsInstance(freed, int)

        mock_settings = MagicMock()
        mock_settings.get.return_value = -10
        cm_neg = CacheManager(self.db, settings=mock_settings)
        details = cm_neg.get_storage_details()
        self.assertGreaterEqual(details["quota_bytes"], 0)
        self.assertGreaterEqual(details["quota_gb"], 0)
        if hasattr(cm_neg, "shutdown"):
            cm_neg.shutdown()

    def test_cache_manager_cover_disk_error_handling(self):
        """BUG-032: save_cover_from_url handles permission/disk errors without crashing."""
        self.assertIsNone(self.cm.save_cover_from_url("file:///etc/passwd", 1))
        self.assertIsNone(self.cm.save_cover_from_url("http://127.0.0.1/cover.jpg", 1))

        with patch("builtins.open", side_effect=OSError("No space left on device")), \
             patch("core.proxy._is_ssrf_safe_url", return_value=True):
            result = self.cm.save_cover_from_url("https://example.com/art.jpg", 123)
            self.assertIsNone(result)


class TestFileScannerUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_test_fs_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(self.db_path)
        self.scanner = FileScanner(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_file_scanner_broken_symlinks_and_non_files(self):
        """BUG-033: broken symlinks and directories disguised with audio extensions must be skipped."""
        fake_dir = os.path.join(self.temp_dir, "fake_album.mp3")
        os.makedirs(fake_dir, exist_ok=True)

        broken_link = os.path.join(self.temp_dir, "broken.mp3")
        try:
            os.symlink(os.path.join(self.temp_dir, "nonexistent.mp3"), broken_link)
        except OSError:
            pass

        txt_file = os.path.join(self.temp_dir, "readme.txt")
        with open(txt_file, "w") as f:
            f.write("text")

        res = self.scanner.scan_files([fake_dir, broken_link, txt_file])
        self.assertEqual(res, [])

        single = self.scanner.scan_single_file(fake_dir)
        self.assertIsNone(single)

    def test_file_scanner_path_normalization(self):
        """BUG-033: path normalization prevents duplicate records in DB for ./ and non-canonical paths."""
        real_file = os.path.join(self.temp_dir, "track1.mp3")
        with open(real_file, "wb") as f:
            f.write(b"ID3" + b"\x00" * 100)

        with patch("utils.file_scanner.parse_tags", return_value={
            "title": "Normalized Track",
            "artist": "Artist",
            "album": "Album",
            "duration": 180.0,
            "bitrate": 320,
            "format": "MP3",
            "genre": None,
            "year": 2024,
            "cover_data": None,
            "cover_mime": None,
        }):
            unnorm_path = os.path.join(self.temp_dir, ".", "track1.mp3")
            track1 = self.scanner.scan_single_file(unnorm_path)
            self.assertIsNotNone(track1)

            track2 = self.scanner.scan_single_file(real_file)
            self.assertIsNone(track2)

    def test_file_scanner_corrupted_metadata_resilience(self):
        """BUG-033: corrupted/NaN/negative duration or null tags must not crash or corrupt database."""
        real_file = os.path.join(self.temp_dir, "corrupt_tags.mp3")
        with open(real_file, "wb") as f:
            f.write(b"0" * 200)

        with patch("utils.file_scanner.parse_tags", return_value={
            "title": None,
            "artist": None,
            "album": None,
            "duration": -45.0,
            "bitrate": "unknown",
            "format": "MP3",
            "genre": None,
            "year": "invalid_year",
            "cover_data": b"corrupt_image_bytes",
            "cover_mime": "image/jpeg",
        }), patch("utils.file_scanner.save_cover_to_file", side_effect=Exception("Failed to save cover")):
            track = self.scanner.scan_single_file(real_file)
            self.assertIsNotNone(track)
            self.assertEqual(track["title"], "corrupt_tags")
            self.assertEqual(track["artist"], "Unknown Artist")
            self.assertGreaterEqual(track["duration"], 0.0)


class TestLyricsServiceUnit(unittest.TestCase):
    def setUp(self):
        self.svc = LyricsService()

    def test_lyrics_parse_lrc_standard_and_single_digit_minutes(self):
        """BUG-034: parse_lrc must parse 1-digit, 2-digit, 3-digit minutes, ms, and multi-timestamps."""
        lrc = (
            "[ti: Test Song]\n"
            "[ar: Test Artist]\n"
            "[1:05.20] First line\n"
            "[02:10.500] Second line\n"
            "[120:00.00] Long line\n"
            "[00:15:30] Colon separator line\n"
            "[00:30.00][00:45.00] Multi timestamp line\n"
        )
        parsed = self.svc.parse_lrc(lrc)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)

        t_first = next((p for p in parsed if "First line" in p["text"]), None)
        self.assertIsNotNone(t_first)
        self.assertEqual(t_first["timeMs"], (1 * 60 + 5) * 1000 + 200)

        t_second = next((p for p in parsed if "Second line" in p["text"]), None)
        self.assertIsNotNone(t_second)
        self.assertEqual(t_second["timeMs"], (2 * 60 + 10) * 1000 + 500)

        multi = [p for p in parsed if "Multi timestamp line" in p["text"]]
        self.assertEqual(len(multi), 2)
        self.assertEqual(multi[0]["timeMs"], 30000)
        self.assertEqual(multi[1]["timeMs"], 45000)

    def test_lyrics_parse_lrc_offset_tag(self):
        """BUG-034: [offset: +/-ms] in header must shift parsed timestamps."""
        lrc_pos = (
            "[offset: 500]\n"
            "[00:10.00] Line one\n"
        )
        parsed_pos = self.svc.parse_lrc(lrc_pos)
        self.assertEqual(parsed_pos[0]["timeMs"], 10500)

        lrc_neg = (
            "[offset: -500]\n"
            "[00:10.00] Line one\n"
        )
        parsed_neg = self.svc.parse_lrc(lrc_neg)
        self.assertEqual(parsed_neg[0]["timeMs"], 9500)

        lrc_clamp = (
            "[offset: -10000]\n"
            "[00:02.00] Early line\n"
        )
        parsed_clamp = self.svc.parse_lrc(lrc_clamp)
        self.assertEqual(parsed_clamp[0]["timeMs"], 0)

    def test_lyrics_parse_lrc_malformed_and_empty_payload(self):
        """BUG-034: malformed, empty, or header-only LRC payloads must return empty list."""
        self.assertEqual(self.svc.parse_lrc(""), [])
        self.assertEqual(self.svc.parse_lrc("   \n\t  "), [])
        self.assertEqual(self.svc.parse_lrc(None), [])
        self.assertEqual(self.svc.parse_lrc("[ti: Only Title]\n[ar: Only Artist]"), [])
        self.assertEqual(self.svc.parse_lrc("[invalid:timestamp] Not a timestamp"), [])

    def test_lyrics_make_result_empty_payloads(self):
        """BUG-034: _make_result must reject empty or whitespace-only lyrics."""
        self.assertIsNone(self.svc._make_result(None, None))
        self.assertIsNone(self.svc._make_result("", ""))
        self.assertIsNone(self.svc._make_result("   ", "   \n\t  "))
        res = self.svc._make_result("[ti: Song]\n[ar: Artist]", "[ti: Song]\n[ar: Artist]")
        if res is not None:
            self.assertNotEqual(res.get("weight"), 1)

    def test_lyrics_genius_empty_sections_safety(self):
        """BUG-034: _fetch_genius with empty sections list must not raise IndexError."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = '{"response": {"sections": []}}'.encode("utf-8")
        with patch.object(self.svc, "_open_url", return_value=mock_resp):
            res = self.svc._fetch_genius("Track", "Artist")
            self.assertIsNone(res)


class TestArtistServiceUnit(unittest.TestCase):
    def setUp(self):
        self.svc = ArtistService()

    def test_artist_service_null_artist_and_non_dict_payload(self):
        """BUG-035: null/non-dict artist payloads in _normalize_album and _artists_label."""
        self.assertIsNone(self.svc._normalize_album(None, "Fallback Artist"))
        self.assertIsNone(self.svc._normalize_album("string_not_dict", "Fallback Artist"))
        self.assertEqual(self.svc._artists_label(None, "Fallback"), "Fallback")
        self.assertEqual(self.svc._artists_label({}, "Fallback"), "Fallback")
        self.assertEqual(self.svc._artists_label({"artists": [None, "invalid"]}, "Fallback"), "Fallback")

    def test_artist_service_album_sort_none_title(self):
        """BUG-035: _collect_albums must not crash with TypeError when title is None."""
        fake_yt = MagicMock()
        fake_yt.search.return_value = []
        artist_dict = {
            "albums": {
                "results": [
                    {"browseId": "alb1", "title": None, "year": 2021},
                    {"browseId": "alb2", "title": "Album Two", "year": None},
                ]
            }
        }
        albums = self.svc._collect_albums(fake_yt, "channel1", artist_dict, "Artist Name")
        self.assertIsInstance(albums, list)

    def test_artist_service_network_timeout_resilience(self):
        """BUG-035: network timeouts in get_profile and get_avatars invoke error callbacks gracefully."""
        fake_yt = MagicMock()
        fake_yt.search.side_effect = TimeoutError("Connection timed out")
        self.svc.youtube = MagicMock()
        self.svc.youtube._ytmusic = fake_yt

        err_msg = []
        event = threading.Event()

        def on_err(msg):
            err_msg.append(msg)
            event.set()

        self.svc.get_profile("Test Artist", error_callback=on_err)
        event.wait(timeout=2.0)
        self.assertTrue(len(err_msg) > 0)


class TestLastFMServiceUnit(unittest.TestCase):
    def setUp(self):
        self.svc = LastFMService()

    def test_lastfm_null_collection_resilience(self):
        """BUG-036: Last.fm API returning None for collection keys must not raise AttributeError."""
        with patch.object(self.svc, "_api_request", return_value={"similarartists": None}):
            res = self.svc.artist_get_similar("Queen")
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"toptracks": None}):
            res = self.svc.artist_get_top_tracks("Queen")
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"toptags": None}):
            res = self.svc.artist_get_top_tags("Queen")
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"similartracks": None}):
            res = self.svc.track_get_similar("Queen", "Bohemian Rhapsody")
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"tracks": None}):
            res = self.svc.chart_get_top_tracks()
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"artists": None}):
            res = self.svc.chart_get_top_artists()
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"recenttracks": None}):
            res = self.svc.user_get_recent_tracks("user1")
            self.assertEqual(res, [])

        with patch.object(self.svc, "_api_request", return_value={"topartists": None}):
            res = self.svc.user_get_top_artists("user1")
            self.assertEqual(res, [])

    def test_lastfm_single_image_dict(self):
        """BUG-036: single image dict instead of list must be correctly extracted."""
        fake_data = {
            "similarartists": {
                "artist": [
                    {
                        "name": "David Bowie",
                        "match": "0.85",
                        "url": "http://last.fm/bowie",
                        "image": {"#text": "http://example.com/bowie.jpg", "size": "large"},
                        "mbid": "123",
                    }
                ]
            }
        }
        with patch.object(self.svc, "_api_request", return_value=fake_data):
            res = self.svc.artist_get_similar("Queen")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["image"], "http://example.com/bowie.jpg")
            self.assertAlmostEqual(res[0]["match"], 0.85)

    def test_lastfm_malformed_number_resilience(self):
        """BUG-036: malformed numbers in playcount, listeners, match must not raise ValueError."""
        fake_data = {
            "toptracks": {
                "track": [
                    {
                        "name": "Under Pressure",
                        "artist": "Queen",
                        "playcount": "not_an_int",
                        "listeners": None,
                        "url": "http://last.fm/track",
                    }
                ]
            }
        }
        with patch.object(self.svc, "_api_request", return_value=fake_data):
            res = self.svc.artist_get_top_tracks("Queen")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["playcount"], 0)
            self.assertEqual(res[0]["listeners"], 0)

    def test_lastfm_empty_arguments_fast_fail(self):
        """BUG-036: empty artist/track/user arguments should fast-fail without network request."""
        with patch.object(self.svc, "_api_request") as mock_req:
            self.assertEqual(self.svc.artist_get_similar(""), [])
            self.assertEqual(self.svc.artist_get_top_tracks("   "), [])
            self.assertEqual(self.svc.artist_get_top_tags(None), [])
            self.assertEqual(self.svc.track_get_similar("", "Track"), [])
            self.assertEqual(self.svc.track_get_similar("Artist", ""), [])
            self.assertEqual(self.svc.user_get_recent_tracks(""), [])
            self.assertEqual(self.svc.user_get_top_artists(""), [])
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
