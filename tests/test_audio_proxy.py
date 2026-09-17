import unittest
from unittest.mock import MagicMock, patch
import urllib.parse
import os
import sys

from core.proxy import _is_loopback_origin, _is_ssrf_safe_url, LocalProxyManager
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
            "source": "youtube",
            "source_id": "vid123",
            "file_path": "https://cdn.example.com/audio.m4a"
        }
        engine._on_track_changed = MagicMock()
        engine.play_queue([track], 0)

        engine._on_track_changed.assert_called_once()
        called_track = engine._on_track_changed.call_args[0][0]
        self.assertIn("stream_url", called_track)
        stream_url = called_track["stream_url"]
        self.assertTrue(stream_url.startswith("http://127.0.0.1:34151/api/stream?url="))
        self.assertNotIn("http://127.0.0.1:34151/?url=", stream_url)


    def test_ensure_sink_inputs_unmuted(self):
        from core.api import AppApi
        api = AppApi(core=MagicMock())

        fake_pactl_output = """
Sink Input #101
\tDriver: PipeWire
\tProperties:
\t\tapplication.name = "firefox"
\t\tmedia.role = "video"
Sink Input #202
\tDriver: PipeWire
\tProperties:
\t\tapplication.name = "main.py"
\t\tapplication.process.binary = "WebKitWebProcess"
\t\tmedia.role = "webaudio"
Sink Input #303
\tDriver: PipeWire
\tProperties:
\t\tapplication.name = "main.py"
\t\tapplication.process.binary = "WebKitWebProcess"
\t\tmedia.role = "music"
"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_pactl_output)
            api._migrate_streams_to_sink("bluez_output.test.1")

            commands = [c[0][0] for c in mock_run.call_args_list]
            # Should have moved target streams to device
            self.assertIn(["pactl", "move-sink-input", "202", "bluez_output.test.1"], commands)
            self.assertIn(["pactl", "move-sink-input", "303", "bluez_output.test.1"], commands)
            # Should NEVER move unrelated application stream (101)
            self.assertNotIn(["pactl", "move-sink-input", "101", "bluez_output.test.1"], commands)
            # Should NOT forcefully override volume or mute for streams (preserves user volume)
            self.assertNotIn(["pactl", "set-sink-input-mute", "202", "0"], commands)
            self.assertNotIn(["pactl", "set-sink-input-volume", "202", "100%"], commands)
            self.assertNotIn(["pactl", "set-sink-input-mute", "303", "0"], commands)
            self.assertNotIn(["pactl", "set-sink-input-volume", "303", "100%"], commands)

    def test_stream_proxy_downloaded_track_served_directly(self):
        import tempfile
        from core.proxy import StreamProxyHandler
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO BYTES")
            temp_file = f.name

        try:
            server = MagicMock()
            server.auth_token = "tok"
            server.app_core = MagicMock()
            server.app_core.cache._streams_dir = "/tmp/fake_streams"
            server.app_core.db.get_track.return_value = {
                "id": 99,
                "title": "Offline Song",
                "artist": "Artist",
                "source": "youtube",
                "source_id": "yt_99",
                "is_downloaded": 1,
                "file_path": temp_file
            }
            server.app_core.db.get_track_by_path.return_value = {"id": 99, "file_path": temp_file}
            server.app_core.engine.resolve_stream_url.side_effect = RuntimeError("Online resolver should not be called!")

            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.server = server
            handler.serve_local_file = MagicMock()
            handler.send_error = MagicMock()

            handler._handle_stream({"track_id": ["99"]})
            self.assertTrue(handler.serve_local_file.called)
            self.assertEqual(handler.serve_local_file.call_args[0][0], temp_file)
            self.assertFalse(server.app_core.engine.resolve_stream_url.called)
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_stream_proxy_forbidden_file_rejected_with_403(self):
        from core.proxy import StreamProxyHandler
        server = MagicMock()
        server.auth_token = "tok"
        server.app_core = MagicMock()
        server.app_core.cache._streams_dir = "/tmp/fake_streams"
        server.app_core.db.get_track_by_path.return_value = None

        handler = StreamProxyHandler.__new__(StreamProxyHandler)
        handler.server = server
        handler.serve_local_file = MagicMock()
        handler.send_error = MagicMock()

        handler._handle_stream({"url": ["/etc/passwd"]})
        self.assertFalse(handler.serve_local_file.called)
        handler.send_error.assert_called_with(403, "Forbidden local file access")

    def test_stream_proxy_scan_folder_audio_allowed(self):
        import tempfile
        from core.proxy import StreamProxyHandler
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = os.path.join(temp_dir, "song.flac")
            with open(audio_file, "wb") as f:
                f.write(b"FLAC DATA")

            server = MagicMock()
            server.auth_token = "tok"
            server.app_core = MagicMock()
            server.app_core.cache._streams_dir = "/tmp/fake_streams"
            server.app_core.db.get_track_by_path.return_value = None
            server.app_core.db.get_scan_folders.return_value = [{"folder_path": temp_dir}]

            handler = StreamProxyHandler.__new__(StreamProxyHandler)
            handler.server = server
            handler.serve_local_file = MagicMock()
            handler.send_error = MagicMock()

            handler._handle_stream({"url": [audio_file]})
            self.assertTrue(handler.serve_local_file.called)
            self.assertEqual(handler.serve_local_file.call_args[0][0], audio_file)


if __name__ == "__main__":
    unittest.main()
