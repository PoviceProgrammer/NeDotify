"""
NeDotify / AURA Music - Rich System Tray Context Menu
Provides dynamic playback controls, track title display, and thread-safe pystray integration.
"""

import os
import sys
import time
import logging
import threading
from typing import Optional, Any, Dict

try:
    from PIL import Image
    import pystray
    from pystray import MenuItem as item, Menu, Separator
    HAS_PYSTRAY = True
except (ImportError, Exception):
    HAS_PYSTRAY = False

logger = logging.getLogger(__name__)


class TrayIcon:
    """Manages the Windows system tray icon and its interactive context menu."""

    def __init__(self, api, icon_path: Optional[str] = None):
        self.api = api
        self.icon_path = icon_path or self._resolve_default_icon_path()
        self.icon: Optional[Any] = None
        self._current_track: Optional[Dict[str, Any]] = None
        self._is_playing: bool = False
        self._last_update_time: float = 0.0
        self._lock = threading.Lock()
        self._is_running: bool = False

    def _resolve_default_icon_path(self) -> str:
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico_path = os.path.join(base, "icon.ico")
        if os.path.exists(ico_path):
            return ico_path
        png_path = os.path.join(base, "ui", "web_new", "assets", "logo.png")
        if os.path.exists(png_path):
            return png_path
        return ico_path

    def create_image(self):
        """Load icon image or generate fallback RGBA pixel grid."""
        if HAS_PYSTRAY and self.icon_path and os.path.exists(self.icon_path):
            try:
                return Image.open(self.icon_path)
            except Exception as e:
                logger.debug(f"Failed to open icon file: {e}")
        try:
            return Image.new("RGBA", (64, 64), color=(168, 85, 247, 255))
        except Exception:
            return None

    def _dispatch_js(self, action: str):
        """Dispatch playback control action via WebView bridge (Decision 2)."""
        try:
            if not self.api or not self.api._window:
                return
            js_code = f"""
                if (window.dispatchEvent) {{
                    window.dispatchEvent(new CustomEvent('nedotify:tray_action', {{ detail: {{ action: '{action}' }} }}));
                }}
            """
            self.api._window.evaluate_js(js_code)
        except Exception as e:
            logger.debug(f"Tray JS dispatch '{action}' error: {e}")

    def on_show(self, icon=None, item=None):
        """Restore and focus the application window."""
        try:
            if self.api and self.api._window:
                self.api._window.restore()
                self.api._window.show()
        except Exception as e:
            logger.debug(f"Failed to restore window: {e}")

    def on_play_pause(self, icon=None, item=None):
        """Toggle play/pause state in frontend."""
        self._dispatch_js("toggle_play")

    def on_next(self, icon=None, item=None):
        """Play next track in queue."""
        self._dispatch_js("next")

    def on_prev(self, icon=None, item=None):
        """Play previous track in queue."""
        self._dispatch_js("prev")

    def on_toggle_favorite(self, icon=None, item=None):
        """Toggle favorite for current track."""
        self._dispatch_js("toggle_like")

    def on_exit(self, icon=None, item=None):
        """Gracefully exit application."""
        try:
            self.stop()
            if self.api and self.api._window:
                self.api._window.destroy()
        except Exception as e:
            logger.debug(f"Error during tray exit: {e}")

    def _build_menu(self):
        """Build dynamic Menu items (Decision 1)."""
        if not HAS_PYSTRAY:
            return None

        # Track status title
        if self._current_track:
            title = self._current_track.get('title') or 'Неизвестный трек'
            artist = self._current_track.get('artist') or 'Неизвестный артист'
            play_indicator = "▶" if self._is_playing else "⏸"
            status_text = f"{play_indicator} {title} — {artist}"
            is_fav = bool(self._current_track.get('is_favorite', False))
            fav_text = "💔 Удалить из любимых" if is_fav else "❤️ В любимые"
        else:
            status_text = "AURA Music (Остановлено)"
            fav_text = "❤️ В любимые"

        play_pause_label = "⏸ Пауза" if self._is_playing else "▶ Воспроизведение"

        menu_items = [
            item(status_text, self.on_show, default=True),
            Separator(),
            item(play_pause_label, self.on_play_pause),
            item("⏭ Следующий трек", self.on_next),
            item("⏮ Предыдущий трек", self.on_prev),
            item(fav_text, self.on_toggle_favorite),
            Separator(),
            item("🗔 Открыть AURA Music", self.on_show),
            item("❌ Выход", self.on_exit)
        ]
        return Menu(*menu_items)

    def update_state(self, track: Optional[Dict[str, Any]] = None, is_playing: Optional[bool] = None, force: bool = False):
        """
        Update dynamic tray menu with throttling (Decision 4: <= 1 update per second).
        """
        if not HAS_PYSTRAY or not self._is_running or not self.icon:
            return

        now = time.time()
        if not force and (now - self._last_update_time < 1.0):
            return

        with self._lock:
            if track is not None:
                self._current_track = track
            if is_playing is not None:
                self._is_playing = bool(is_playing)
            self._last_update_time = now

            try:
                new_menu = self._build_menu()
                if new_menu and self.icon:
                    self.icon.menu = new_menu
            except Exception as e:
                logger.debug(f"Failed to update tray menu: {e}")

    def start(self):
        """Start the system tray in a background daemon thread."""
        if not HAS_PYSTRAY:
            logger.info("pystray not available; tray disabled.")
            return

        def _run_tray():
            try:
                img = self.create_image()
                if not img:
                    return
                menu = self._build_menu()
                self.icon = pystray.Icon("AURA Music", img, "AURA Music", menu)
                self._is_running = True
                self.icon.run()
            except Exception as e:
                logger.warning(f"System tray icon failed to run: {e}")
            finally:
                self._is_running = False

        threading.Thread(target=_run_tray, name="TrayThread", daemon=True).start()

    def stop(self):
        """Stop system tray icon."""
        if self.icon and self._is_running:
            try:
                self.icon.stop()
            except Exception:
                pass
            self._is_running = False
