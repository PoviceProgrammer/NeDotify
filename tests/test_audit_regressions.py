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
    - Web Audio destination routing & volume sync in both player.js files
    - HLS per-element instance isolation
    - Proxy fail-closed authorization & /__aura_eval lockdown
    - Range status-code and headers handling (no fake 206 on 200)
    - SQLite thread connection cleanup in file_scanner and cache_manager
    - AudioEngine resolver race condition prevention
    """

    def setUp(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.player_v1_path = os.path.join(self.project_root, "ui", "web_new", "js", "player.js")
        self.player_v2_path = os.path.join(self.project_root, "ui", "web_new_v2", "js", "player.js")

    # -------------------------------------------------------------------------
    # 1. Web Audio Routing & Volume Sync (Player.js)
    # -------------------------------------------------------------------------
    def test_web_audio_routing_and_volume_sync_both_versions(self):
        for path in (self.player_v1_path, self.player_v2_path):
            self.assertTrue(os.path.exists(path), f"File {path} must exist")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # 1. masterGainNode must NOT be connected to audioCtx.destination to avoid duplicates
            self.assertNotIn(
                "masterGainNode.connect(audioCtx.destination)",
                content,
                f"masterGainNode must not be connected to audioCtx.destination in {path}"
            )

            # 2. syncVolume must hardcode masterGainNode.gain.value = 0 to avoid duplicates
            sync_vol_match = re.search(r"export function syncVolume\(\)\s*\{(.*?)\n\}", content, re.DOTALL)
            self.assertIsNotNone(sync_vol_match, f"syncVolume() not found in {path}")
            sync_vol_body = sync_vol_match.group(1)

            self.assertIn(
                "masterGainNode.gain.value = 0",
                sync_vol_body,
                f"syncVolume() must hardcode masterGainNode.gain.value = 0 in {path}"
            )

            # 3. HLS race fix: must NOT have module-global `let hlsInstance = null;`
            self.assertNotIn(
                "let hlsInstance = null;",
                content,
                f"Global hlsInstance variable must be removed in {path} to avoid crossfade race conditions"
            )
            self.assertIn(
                "audioEl._hlsInstance",
                content,
                f"hlsInstance must be attached to audioEl._hlsInstance in {path}"
            )

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
        env_backup = dict(os.environ)
        try:
            os.environ.pop("AURA_DEBUG", None)
            os.environ.pop("NEDOTIFY_DEBUG", None)

            server = MagicMock()
            server.auth_token = "valid_tok"
            server.app_core = MagicMock()
            server.app_core.settings.get.return_value = False

            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.server = server
            handler.command = "POST"
            handler.path = "/__aura_eval?k=valid_tok"
            handler.headers = {"Content-Length": "14"}
            handler.rfile = io.BytesIO(b"console.log(1)")
            handler.wfile = io.BytesIO()

            errors = []
            handler.send_error = lambda code, msg=None: errors.append((code, msg))

            # Without debug mode, even with valid token, must respond with 403
            handler.do_POST()
            self.assertEqual(errors, [(403, "Endpoint disabled")])
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_proxy_eval_enabled_with_debug_flag(self):
        env_backup = dict(os.environ)
        try:
            os.environ["AURA_DEBUG"] = "1"

            server = MagicMock()
            server.auth_token = "valid_tok"
            server.app_core = MagicMock()
            window_mock = MagicMock()
            window_mock.evaluate_js.return_value = "evaluated_ok"
            server.app_core.window = window_mock

            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.server = server
            handler.command = "POST"
            handler.path = "/__aura_eval?k=valid_tok"
            handler.headers = {"Content-Length": "12"}
            handler.rfile = io.BytesIO(b"alert('test')")
            handler.wfile = io.BytesIO()

            status_codes = []
            handler.send_response = lambda code, msg=None: status_codes.append(code)
            handler.send_header = lambda k, v: None
            handler.end_headers = lambda: None
            handler._send_cors_headers = lambda: None

            handler.do_POST()
            self.assertIn(200, status_codes)
            self.assertIn(b"evaluated_ok", handler.wfile.getvalue())
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
            "self.db.close_thread_connection()",
            content,
            "cache_manager.py must call close_thread_connection() in download task"
        )
        self.assertTrue(
            re.search(r"finally:.*self\.db\.close_thread_connection\(\)", content, re.DOTALL),
            "cache_manager.py must call close_thread_connection() inside finally"
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

        self.assertIn("track = track.copy()", engine_code)
        self.assertIn('self.queue.current_track.get("id") == track.get("id")', engine_code)


if __name__ == "__main__":
    unittest.main()
