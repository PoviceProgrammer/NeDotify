"""Current loopback audio proxy and stream routing contracts.

Pre-port WebKit pactl sink migration and legacy _handle_stream tests
remain in tests/legacy_pre_parity; current desktop uses Qt/HTML Audio
and _safe_stream_local_path validation.
"""
import unittest
from unittest.mock import MagicMock, patch
import urllib.parse
import os
import sys

from core.proxy import _is_loopback_origin, _is_ssrf_safe_url, LocalProxyManager, _safe_stream_local_path
from audio.engine import AudioEngine


class TestAudioProxy(unittest.TestCase):
    def test_loopback_origin(self):
        self.assertTrue(_is_loopback_origin("http://127.0.0.1:42001"))
        self.assertTrue(_is_loopback_origin("http://localhost:42001"))
        self.assertTrue(_is_loopback_origin("http://[::1]:8080"))
        self.assertFalse(_is_loopback_origin("https://example.com"))
        self.assertFalse(_is_loopback_origin("http://192.168.1.5"))

    def test_ssrf_safe_url(self):
        # Public URLs should be allowed
        self.assertTrue(_is_ssrf_safe_url("https://googlevideo.com/videoplayback"))
        self.assertTrue(_is_ssrf_safe_url("https://sndcdn.com/stream"))
        # Private/loopback IPs must be blocked
        self.assertFalse(_is_ssrf_safe_url("http://127.0.0.1:8080/stream"))
        self.assertFalse(_is_ssrf_safe_url("http://localhost:42001"))
        self.assertFalse(_is_ssrf_safe_url("http://10.0.0.1/admin"))
        self.assertFalse(_is_ssrf_safe_url("http://192.168.1.1/secret"))

    def test_proxy_get_proxy_url(self):
        proxy = LocalProxyManager(app_core=MagicMock())
        proxy.port = 43541
        proxy.token = "test_tok"
        url = proxy.get_proxy_url(source="youtube", source_id="abc123xyz", original_url="https://youtube.com/watch?v=abc123xyz")
        self.assertTrue(url.startswith("http://127.0.0.1:43541/api/stream?"))
        self.assertIn("k=test_tok", url)
        self.assertIn("source=youtube", url)
        self.assertIn("source_id=abc123xyz", url)

    def test_audio_engine_proxy_url_format(self):
        engine = AudioEngine()
        engine.proxy = MagicMock()
        engine.proxy.port = 34151
        engine.proxy.auth_query.return_value = "&k=dummy_token"

        track = {
            "title": "Test Title",
            "artist": "Test Artist",
            "source": "local",
            "source_id": "vid123",
            "file_path": "/home/user/Music/audio.mp3"
        }
        engine._on_track_changed = MagicMock()
        with patch("os.path.exists", return_value=True):
            engine.play_queue([track], 0)

        engine._on_track_changed.assert_called_once()
        called_track = engine._on_track_changed.call_args[0][0]
        self.assertIn("stream_url", called_track)
        stream_url = called_track["stream_url"]
        self.assertTrue(stream_url.startswith("http://127.0.0.1:34151/api/stream?url="))

    def test_linux_mpris_and_media_commands_route_to_player(self):
        """Linux MPRIS interface routes media keys directly to player engine."""
        from core.mpris import create_interfaces
        mock_desktop = MagicMock()
        root, player = create_interfaces(mock_desktop)
        player.PlayPause()
        mock_desktop.dispatch.assert_any_call('toggle_play')
        player.Next()
        mock_desktop.dispatch.assert_any_call('next')
        player.Previous()
        mock_desktop.dispatch.assert_any_call('prev')

    def test_stream_proxy_downloaded_track_served_directly(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO BYTES")
            temp_file = f.name

        try:
            mock_db = MagicMock()
            mock_db.conn.execute.return_value.fetchone.return_value = (99,)
            resolved = _safe_stream_local_path(temp_file, mock_db)
            self.assertEqual(resolved, os.path.realpath(temp_file))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_stream_proxy_forbidden_file_rejected_with_empty(self):
        mock_db = MagicMock()
        mock_db.conn.execute.return_value.fetchone.return_value = None
        self.assertEqual(_safe_stream_local_path("/etc/passwd", mock_db), "")
        self.assertEqual(_safe_stream_local_path("../../secret.mp3", mock_db), "")

    def test_stream_proxy_scan_folder_audio_allowed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = os.path.join(temp_dir, "song.flac")
            with open(audio_file, "wb") as f:
                f.write(b"FLAC DATA")

            mock_db = MagicMock()
            mock_db.conn.execute.return_value.fetchone.return_value = (1,)
            resolved = _safe_stream_local_path(audio_file, mock_db)
            self.assertEqual(resolved, os.path.realpath(audio_file))


if __name__ == "__main__":
    unittest.main()
