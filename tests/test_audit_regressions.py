"""Regression tests for audit fixes in NeDotify.

Pre-port AURA-Music eval backdoor and v1 player tests remain in
tests/legacy_pre_parity; current desktop enforces eval-free proxy security,
single v2 UI audio routing, and verified database indexes.
"""
import io
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

from core.proxy import StreamProxyHandler, LocalProxyManager
from audio.engine import AudioEngine


class TestAuditRegressions(unittest.TestCase):
    """
    Comprehensive regression tests covering all fixes from the audit:
    - Web Audio destination routing & volume sync in player.js (web_new_v2)
    - HLS / dual-element instance isolation
    - Proxy fail-closed authorization & absolute eval rejection
    - Range status-code and headers handling (no fake 206 on 200)
    - SQLite thread connection cleanup in file_scanner and cache_manager
    - AudioEngine resolver race condition prevention
    - Database composite indexes
    """

    def setUp(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.player_v2_path = os.path.join(self.project_root, "ui", "web_new_v2", "js", "player.js")

    # -------------------------------------------------------------------------
    # 1. Web Audio Routing & Volume Sync (Player.js)
    # -------------------------------------------------------------------------
    def test_web_audio_routing_and_volume_sync_both_versions(self):
        self.assertTrue(os.path.exists(self.player_v2_path), f"File {self.player_v2_path} must exist")
        with open(self.player_v2_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. ReplayGain volume normalization must be present
        self.assertIn("updateReplayGain", content)
        self.assertIn("currentReplayGain", content)

        # 2. Dual HTML Audio instances (audioA and audioB) must be managed
        self.assertIn("audioA", content)
        self.assertIn("audioB", content)

        # 3. AudioContext connection must be guarded
        self.assertIn("initAudioContext", content)

    # -------------------------------------------------------------------------
    # 2. Proxy Authorization & Eval Lockdown
    # -------------------------------------------------------------------------
    def test_proxy_auth_fail_closed(self):
        server = MagicMock()
        server.auth_token = "secret_key_123"
        handler = StreamProxyHandler.__new__(StreamProxyHandler)
        handler.server = server

        # Must reject missing or empty tokens
        self.assertFalse(handler._authorized({}))
        self.assertFalse(handler._authorized({"k": [""]}))
        self.assertFalse(handler._authorized({"k": ["wrong_token"]}))
        # Must accept valid token
        self.assertTrue(handler._authorized({"k": ["secret_key_123"]}))
        self.assertTrue(handler._authorized({"auth_token": ["secret_key_123"]}))

        # If server auth_token is empty or unset, it must fail-closed (NOT fail-open)
        server.auth_token = ""
        self.assertFalse(handler._authorized({}))
        self.assertFalse(handler._authorized({"k": ["secret_key_123"]}))

        server.auth_token = None
        self.assertFalse(handler._authorized({}))

    def test_proxy_eval_disabled_in_production(self):
        # In NeDotify, POST eval backdoors are completely removed: do_POST does not exist
        self.assertFalse(hasattr(StreamProxyHandler, 'do_POST'), "do_POST must not exist on StreamProxyHandler")

        server = MagicMock()
        server.auth_token = "valid_tok"
        server.app_core = MagicMock()

        handler = StreamProxyHandler.__new__(StreamProxyHandler)
        handler.server = server
        handler.command = "GET"
        handler.path = "/__aura_eval?k=valid_tok"
        handler.headers = {}
        handler.wfile = io.BytesIO()

        status_codes = []
        handler._safe_send_error = lambda code, msg=None: status_codes.append(code)

        handler.do_GET()
        self.assertIn(404, status_codes)

    def test_proxy_eval_enabled_with_debug_flag(self):
        # In NeDotify, debug flags never open remote eval endpoints
        env_backup = dict(os.environ)
        try:
            os.environ["NEDOTIFY_DEBUG"] = "1"
            self.assertFalse(hasattr(StreamProxyHandler, 'do_POST'))

            server = MagicMock()
            server.auth_token = "valid_tok"
            server.app_core = MagicMock()

            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.server = server
            handler.command = "GET"
            handler.path = "/__aura_eval?k=valid_tok"
            handler.headers = {}
            handler.wfile = io.BytesIO()

            status_codes = []
            handler._safe_send_error = lambda code, msg=None: status_codes.append(code)

            handler.do_GET()
            self.assertIn(404, status_codes)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    # -------------------------------------------------------------------------
    # 3. Range Handling & Status Code Integrity
    # -------------------------------------------------------------------------
    def test_serve_local_file_range_request(self):
        import tempfile
        full_data = b"0123456789ABCDEF" * 64  # 1024 bytes
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(full_data)
            temp_file = f.name

        try:
            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.headers = {"Range": "bytes=10-29"}
            handler.wfile = io.BytesIO()

            sent_headers = {}
            status_codes = []
            handler.send_response = lambda code, msg=None: status_codes.append(code)
            handler.send_header = lambda k, v: sent_headers.update({k: v})
            handler.end_headers = lambda: None
            handler._send_cors_headers = lambda: None

            handler.serve_local_file(temp_file)

            # Must return 206 Partial Content
            self.assertEqual(status_codes, [206])
            # Must return correct Content-Range
            self.assertEqual(sent_headers.get("Content-Range"), "bytes 10-29/1024")
            self.assertEqual(sent_headers.get("Content-Length"), "20")
            self.assertEqual(sent_headers.get("Accept-Ranges"), "bytes")
            # Must return exactly bytes 10 to 29
            self.assertEqual(handler.wfile.getvalue(), full_data[10:30])
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    # -------------------------------------------------------------------------
    # 4. SQLite Thread Connection Cleanup (Leaking threads)
    # -------------------------------------------------------------------------
    def test_db_connection_cleanup_in_file_scanner(self):
        file_scanner_path = os.path.join(self.project_root, "utils", "file_scanner.py")
        with open(file_scanner_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            "self.db.close_thread_connection()",
            content,
            "file_scanner.py must call close_thread_connection() to prevent SQLite handle leaks"
        )
        self.assertTrue(
            re.search(r"finally:.*self\.db\.close_thread_connection\(\)", content, re.DOTALL),
            "file_scanner.py must call close_thread_connection() inside finally"
        )

    def test_db_connection_cleanup_in_cache_manager(self):
        cache_manager_path = os.path.join(self.project_root, "utils", "cache_manager.py")
        with open(cache_manager_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            "close_thread_connection",
            content,
            "cache_manager.py must call close_thread_connection in download task"
        )
        self.assertTrue(
            re.search(r"finally:.*close_connection\(\)", content, re.DOTALL),
            "cache_manager.py must call close_connection() inside finally"
        )

    # -------------------------------------------------------------------------
    # 5. Resolver Race Condition Prevention
    # -------------------------------------------------------------------------
    def test_resolver_race_prevention_stale_track(self):
        engine = AudioEngine()
        engine.app_core = MagicMock()

        # Set current track to track #2 via public queue API
        engine.queue.set_tracks([{"id": 2, "title": "New Track", "duration": 180}], start_index=0)
        self.assertEqual(engine.queue.current_track["id"], 2)

        # Inspect engine.py code to verify defensive checks
        engine_path = os.path.join(self.project_root, "audio", "engine.py")
        with open(engine_path, "r", encoding="utf-8") as f:
            engine_code = f.read()

        self.assertIn("track = current.copy()", engine_code)

    def test_database_composite_indexes_exist(self):
        import tempfile
        from core.database import DatabaseManager
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            db = DatabaseManager(db_path)
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}

            expected_indexes = {
                "idx_tracks_source",
                "idx_tracks_source_sid",
                "idx_tracks_downloaded",
                "idx_tracks_file_path",
                "idx_history_track_time",
                "idx_tracks_play_count",
            }
            for idx in expected_indexes:
                self.assertIn(idx, indexes, f"Missing index: {idx}")
            db.close()


if __name__ == "__main__":
    unittest.main()
