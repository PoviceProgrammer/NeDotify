import os
import time
import unittest
from unittest.mock import MagicMock, patch
from core.tray import TrayIcon


class TestPhase5TrayMenu(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.mock_window = MagicMock()
        self.mock_api._window = self.mock_window
        self.tray = TrayIcon(self.mock_api)

    def test_headless_graceful_init(self):
        # Even without a real tray loop, TrayIcon should not crash
        self.assertIsNotNone(self.tray)
        self.tray.stop()

    def test_menu_generation_and_state_updates(self):
        # 1. Idle state
        menu = self.tray._build_menu()
        if menu:
            labels = [getattr(item, "text", str(item)) for item in menu.items if hasattr(item, "text")]
            self.assertTrue(any("AURA Music (Остановлено)" in str(l) for l in labels))

        # 2. Playing track state
        track = {"title": "Cyberpunk 2077", "artist": "Marcin Przybylowicz", "is_favorite": 1}
        self.tray.update_state(track=track, is_playing=True, force=True)
        menu_playing = self.tray._build_menu()
        if menu_playing:
            labels = [getattr(item, "text", str(item)) for item in menu_playing.items if hasattr(item, "text")]
            self.assertTrue(any("Cyberpunk 2077" in str(l) for l in labels))
            self.assertTrue(any("Удалить из любимых" in str(l) for l in labels))

        # 3. Paused track state
        self.tray.update_state(is_playing=False, force=True)
        menu_paused = self.tray._build_menu()
        if menu_paused:
            labels = [getattr(item, "text", str(item)) for item in menu_paused.items if hasattr(item, "text")]
            self.assertTrue(any("⏸" in str(l) for l in labels))

    def test_tray_dispatch_js(self):
        self.tray.on_play_pause()
        self.mock_window.evaluate_js.assert_called()
        call_args = self.mock_window.evaluate_js.call_args[0][0]
        self.assertIn("toggle_play", call_args)

        self.tray.on_next()
        call_args = self.mock_window.evaluate_js.call_args[0][0]
        self.assertIn("next", call_args)

        self.tray.on_prev()
        call_args = self.mock_window.evaluate_js.call_args[0][0]
        self.assertIn("prev", call_args)

        self.tray.on_toggle_favorite()
        call_args = self.mock_window.evaluate_js.call_args[0][0]
        self.assertIn("toggle_like", call_args)


if __name__ == "__main__":
    unittest.main()
