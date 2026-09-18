import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from services.watchdog_service import WatchdogService
from services.audio_fingerprint_service import AudioFingerprintService
from audio.engine import AudioEngine
from services.taste_profile import UserTasteProfile
from core.session import SessionManager
from core.services.discord_rpc import DiscordRPCService
from services.lufs_scanner import LufsScannerService
import utils.tag_parser as tag_parser


class TestCycle7Audits(unittest.TestCase):

    def test_bug_038_watchdog_sync_folders_handles_dict_records(self):
        """BUG-038: _sync_folders raises TypeError on dict records from get_scan_folders()."""
        mock_core = MagicMock()
        mock_core.db.get_scan_folders.return_value = [
            {"id": 1, "folder_path": "/tmp/music1", "auto_scan": 1},
            {"id": 2, "folder_path": "/tmp/music2", "auto_scan": 0},
            {"id": 3, "folder_path": "/tmp/music3", "auto_scan": 1},
        ]
        
        service = WatchdogService(mock_core)
        # Should not raise TypeError: unhashable type: 'dict'
        with patch("os.path.isdir", return_value=False):
            service._sync_folders()

    def test_bug_038_watchdog_stop_when_watchdog_disabled(self):
        """BUG-038: stop() raises AttributeError when watchdog module is not installed."""
        mock_core = MagicMock()
        service = WatchdogService(mock_core)
        service.observer = None
        service.handler = None
        # Should not raise AttributeError
        service.stop()

    def test_bug_039_fingerprint_preserves_file_if_referenced_by_other_tracks(self):
        """BUG-039: delete_duplicate_track must NOT delete file on disk if other DB tracks reference it."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"dummy audio data")
            temp_path = f.name

        try:
            mock_db = MagicMock()
            mock_db.get_track.return_value = {"id": 1, "file_path": temp_path}
            # Simulate another track referencing the same file path
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1,)  # 1 other track found
            mock_db.conn.cursor.return_value = mock_cursor

            service = AudioFingerprintService()
            result = service.delete_duplicate_track(mock_db, track_id=1, delete_file=True)

            self.assertTrue(result)
            self.assertTrue(os.path.exists(temp_path), "File should NOT have been deleted from disk because other tracks reference it")
            mock_db.delete_track.assert_called_once_with(1)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_bug_040_engine_resolves_vk_tracks(self):
        """BUG-040: AudioEngine._resolve_via_network handles source == 'vk'."""
        engine = AudioEngine()
        mock_core = MagicMock()
        mock_vk = MagicMock()

        def fake_get_stream(target, cb, err_cb):
            cb("https://vk.com/stream/audio.mp3")

        mock_vk.get_stream_url.side_effect = fake_get_stream
        mock_core.vk = mock_vk
        engine.app_core = mock_core

        track = {"source": "vk", "source_id": "123_456", "title": "Test Song", "artist": "Artist"}
        url = engine._resolve_via_network(track)
        self.assertEqual(url, "https://vk.com/stream/audio.mp3")

    def test_bug_041_taste_profile_closes_sqlite_connection_for_filepath(self):
        """BUG-041: build_from_db leaks SQLite connection when db is passed as a string."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_db = f.name

        try:
            with sqlite3.connect(temp_db) as conn:
                conn.execute("CREATE TABLE tracks (id INTEGER, title TEXT, artist TEXT)")
                conn.commit()

            profile = UserTasteProfile()
            closed = False
            real_connect = sqlite3.connect

            class ConnWrapper:
                def __init__(self, target):
                    self._target = target

                def close(self):
                    nonlocal closed
                    closed = True
                    return self._target.close()

                def __getattr__(self, name):
                    return getattr(self._target, name)

            def mock_connect(*args, **kwargs):
                return ConnWrapper(real_connect(*args, **kwargs))

            with patch("sqlite3.connect", side_effect=mock_connect):
                profile.build_from_db(temp_db)
                self.assertTrue(closed, "SQLite connection opened from file path was not closed")
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_bug_042_tag_parser_backup_path_is_unique(self):
        """BUG-042: write_tags uses unique backup filename to prevent race condition overwrites."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ID3dummy")
            temp_file = f.name

        try:
            import shutil
            created_backups = []
            orig_copy2 = shutil.copy2

            def spy_copy(src, dst):
                created_backups.append(dst)
                return orig_copy2(src, dst)

            with patch("shutil.copy2", side_effect=spy_copy):
                try:
                    tag_parser.write_tags(temp_file, title="Test 1")
                except Exception:
                    pass
                try:
                    tag_parser.write_tags(temp_file, title="Test 2")
                except Exception:
                    pass

            self.assertEqual(len(created_backups), 2)
            # The two backup paths must not be identical
            self.assertNotEqual(created_backups[0], created_backups[1])
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_bug_043_session_restore_resets_spotify_and_yandex(self):
        """BUG-043: restore_session resets file_path and resolved_at for spotify and yandex."""
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda sec, key, default=None: {
            ("session", "last_track_id"): 1,
            ("session", "last_position"): 10.0,
            ("session", "last_volume"): 80,
            ("session", "last_queue"): [
                {"id": 1, "source": "spotify", "file_path": "http://stale.url", "resolved_at": 12345},
                {"id": 2, "source": "yandex", "file_path": "http://stale2.url", "resolved_at": 12345},
                {"id": 3, "source": "local", "file_path": "/home/user/song.mp3", "resolved_at": 12345},
            ],
            ("session", "last_queue_index"): 0,
            ("session", "shuffle"): False,
            ("session", "repeat"): "off",
        }.get((sec, key), default)

        manager = SessionManager(mock_settings)
        session = manager.restore_session()

        queue = session["queue"]
        self.assertIsNone(queue[0]["file_path"])
        self.assertEqual(queue[0]["resolved_at"], 0)
        self.assertIsNone(queue[1]["file_path"])
        self.assertEqual(queue[1]["resolved_at"], 0)
        # Local track must keep its file path
        self.assertEqual(queue[2]["file_path"], "/home/user/song.mp3")

    def test_bug_044_discord_rpc_stop_acquires_lock(self):
        """BUG-044: stop() acquires _lock to prevent race with running connection threads."""
        rpc_service = DiscordRPCService()
        mock_rpc = MagicMock()
        rpc_service.rpc = mock_rpc
        rpc_service.connected = True

        rpc_service.stop()
        self.assertFalse(rpc_service.connected)
        self.assertIsNone(rpc_service.rpc)
        mock_rpc.close.assert_called_once()

    def test_bug_045_lufs_scanner_uses_db_update_track(self):
        """BUG-045: LufsScannerService._update_db uses db.update_track with write lock."""
        mock_core = MagicMock()
        scanner = LufsScannerService(mock_core)
        scanner._update_db(42, -14.5, 0.95)

        mock_core.db.update_track.assert_called_once_with(
            42, lufs=-14.5, loudness_lufs=-14.5, peak_volume=0.95
        )


if __name__ == "__main__":
    unittest.main()
