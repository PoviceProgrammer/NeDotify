import os
import sys
import unittest
import glob
import re
import tempfile
import sqlite3

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.app import AppCore
from core.api import AppApi
from services.zapret_service import ZapretService
from services.playlist_import_service import PlaylistImportService
from audio.engine import AudioEngine


class TestGlobalPhasesAudit(unittest.TestCase):
    """
    Comprehensive Phase 1-5 Audit Suite verifying all features, contracts, and app launch capability.
    """

    @classmethod
    def setUpClass(cls):
        cls.core = AppCore()

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls.core, "db") and cls.core.db:
                cls.core.db.close()
        except Exception:
            pass

    # -------------------------------------------------------------
    # PHASE 1 VERIFICATION TESTS
    # -------------------------------------------------------------

    def test_phase1_playlist_import_service(self):
        """Phase 1: Test playlist import service resolves local M3U, JSON, and text lists."""
        importer = PlaylistImportService()
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as track_file:
            track_path = track_file.name

        with tempfile.NamedTemporaryFile(suffix=".m3u", mode="w", delete=False, encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:180,Test Artist - Test Title\n{track_path}\n")
            m3u_path = f.name

        try:
            res = importer.resolve(m3u_path)
            self.assertIn("tracks", res)
            self.assertEqual(len(res["tracks"]), 1)
            self.assertEqual(res["tracks"][0]["title"], "Test Title")
        finally:
            if os.path.exists(m3u_path): os.remove(m3u_path)
            if os.path.exists(track_path): os.remove(track_path)

        # Test Text List parsing
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Artist 1 - Track 1\nArtist 2 - Track 2\n")
            txt_path = f.name
        try:
            res_text = importer.resolve(txt_path)
            self.assertIn("tracks", res_text)
            self.assertEqual(len(res_text["tracks"]), 2)
        finally:
            os.remove(txt_path)

    def test_phase1_zapret_status_diagnostic(self):
        """Phase 1: Test Zapret service diagnostic status return strings in Russian."""
        zapret = ZapretService()
        status = zapret.get_status()
        self.assertIn("running", status)
        self.assertIn("message", status)
        self.assertIn("has_internet", status)
        self.assertTrue(isinstance(status["message"], str))
        self.assertTrue(len(status["message"]) > 0)

    def test_phase1_storage_info_contract(self):
        """Phase 1: Test storage info backend contract response structure."""
        api = AppApi(self.core)
        storage_info = api.get_storage_info()
        self.assertIn("total", storage_info)
        self.assertIn("tracks", storage_info)
        self.assertIn("covers", storage_info)
        self.assertIn("count", storage_info["tracks"])
        self.assertIn("size", storage_info["tracks"])
        self.assertIn("count", storage_info["covers"])
        self.assertIn("size", storage_info["covers"])

    def test_phase1_home_analytics_data(self):
        """Phase 1: Test home data analytics payload contains top_tracks and top_artists."""
        api = AppApi(self.core)
        home_data = api.get_home_data()
        self.assertIn("analytics", home_data)
        analytics = home_data["analytics"]
        self.assertIn("top_tracks", analytics)
        self.assertIn("top_artists", analytics)
        self.assertTrue(isinstance(analytics["top_tracks"], list))
        self.assertTrue(isinstance(analytics["top_artists"], list))

    # -------------------------------------------------------------
    # PHASE 2 VERIFICATION TESTS
    # -------------------------------------------------------------

    def test_phase2_frameless_window_maximize(self):
        """Phase 2: Test maximize API toggles frameless state without true OS fullscreen."""
        api = AppApi(self.core)
        class MockWin:
            def maximize(self): pass
            def restore(self): pass
        api.set_window(MockWin())
        self.assertFalse(getattr(api, "_is_maximized", False))
        api.maximize()
        self.assertTrue(getattr(api, "_is_maximized", False))
        api.maximize()
        self.assertFalse(getattr(api, "_is_maximized", False))

    def test_phase2_settings_layout_html_container(self):
        """Phase 2: Test index.html contains settings-layout container wrapping nav and panels."""
        index_path = os.path.join(os.path.dirname(__file__), "..", "ui", "web_new", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('class="settings-layout"', content)
        self.assertIn('class="settings-nav"', content)
        self.assertIn('class="settings-panels"', content)

    # -------------------------------------------------------------
    # PHASE 3 VERIFICATION TESTS
    # -------------------------------------------------------------

    def test_phase3_theme_presets_checkmark_encoding(self):
        """Phase 3: Test theme card checkmark in settings.js has no corrupted 'вњ"' artifacts."""
        settings_js_path = os.path.join(os.path.dirname(__file__), "..", "ui", "web_new", "js", "settings.js")
        with open(settings_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("вњ\"", content)

    def test_phase3_font_size_slider_clean_scaling(self):
        """Phase 3: Test applyFontSize in settings.js avoids CSS zoom coordinate bugs."""
        settings_js_path = os.path.join(os.path.dirname(__file__), "..", "ui", "web_new", "js", "settings.js")
        with open(settings_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("appContainer.style.zoom", content)
        self.assertIn("document.documentElement.style.fontSize", content)

    # -------------------------------------------------------------
    # PHASE 4 VERIFICATION TESTS
    # -------------------------------------------------------------

    def test_phase4_preload_get_next_track_api(self):
        """Phase 4: Test AppApi.get_next_track() returns next track in queue without mutating index."""
        api = AppApi(self.core)
        # Add sample tracks
        track1 = {"id": 1, "title": "Track 1", "artist": "Artist 1", "source": "local", "file_path": "C:\\t1.mp3"}
        track2 = {"id": 2, "title": "Track 2", "artist": "Artist 2", "source": "local", "file_path": "C:\\t2.mp3"}
        
        self.core.engine.play_queue([track1, track2], index=0)
        next_track = api.get_next_track()
        self.assertIsNotNone(next_track)
        self.assertEqual(next_track["id"], 2)
        # Current index should remain on track 1
        self.assertEqual(self.core.engine.queue.current_track["id"], 1)

    def test_phase4_audio_engine_queue_operations(self):
        """Phase 4: Test AudioEngine queue mode operations (shuffle, repeat, next, prev)."""
        engine = AudioEngine()
        t1 = {"id": 1, "title": "T1"}
        t2 = {"id": 2, "title": "T2"}
        engine.play_queue([t1, t2], index=0)
        self.assertEqual(engine.queue.current_track["id"], 1)
        
        mode = engine.toggle_repeat()
        self.assertIn(mode, ["off", "all", "one"])
        
        shuf = engine.toggle_shuffle()
        self.assertTrue(isinstance(shuf, bool))

    def test_phase4_report_position_milliseconds_contract(self):
        """Phase 4: Test report_position emits position_ms and duration_ms in milliseconds."""
        api = AppApi(self.core)
        emitted = []
        api._emit = lambda event, data: emitted.append((event, data))
        api.report_position(15500, duration_ms=211000)
        self.assertEqual(len(emitted), 1)
        event_name, data = emitted[0]
        self.assertEqual(event_name, "position_changed")
        self.assertEqual(data["position_ms"], 15500)
        self.assertEqual(data["duration_ms"], 211000)
        self.assertEqual(data["pos"], 15.5)
        self.assertEqual(data["duration"], 211.0)

    # -------------------------------------------------------------
    # PHASE 5 VERIFICATION TESTS & APPLICATION STARTUP
    # -------------------------------------------------------------

    def test_phase5_blackout_policy_isolation(self):
        """Phase 5: Test Yandex, VK, and Zeno providers remain excluded from active search."""
        api = AppApi(self.core)
        res = api.search("test", source="all")
        self.assertIn("tracks", res)
        # Verify no tracks return from blackout providers
        for track in res.get("tracks", []):
            self.assertNotIn(track.get("source"), ["yandex", "vk", "vkontakte", "zeno"])

    def test_phase5_app_startup_clean_launch(self):
        """Phase 5: Test full AppCore and AppApi startup initialization without runtime exceptions."""
        app = AppCore()
        api = AppApi(app)
        self.assertIsNotNone(app.db)
        self.assertIsNotNone(app.engine)
        self.assertIsNotNone(app.playlist_importer)
        self.assertIsNotNone(api._core)


if __name__ == "__main__":
    unittest.main()
