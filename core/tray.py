"""
NeDotify - Rich System Tray Context Menu
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
    from pystray import MenuItem as item, Menu
    HAS_PYSTRAY = True
except (ImportError, Exception):
    HAS_PYSTRAY = False

logger = logging.getLogger(__name__)


class TrayIcon:
    """Manages the Windows system tray icon and its interactive context menu."""

    def __new__(cls, api=None, icon_path=None):
        if sys.platform == "linux":
            from core.linux_tray import LinuxTrayIcon
            return LinuxTrayIcon(api, icon_path)
        return super().__new__(cls)

    def __init__(self, api, icon_path: Optional[str] = None):
        self.api = api
        self.icon_path = icon_path or self._resolve_default_icon_path()
        self.icon: Optional[Any] = None
        self._current_track: Optional[Dict[str, Any]] = None
        self._is_playing: bool = False
        self._last_update_time: float = 0.0
        self._lock = threading.Lock()
        self._is_running: bool = False
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    def _resolve_default_icon_path(self) -> str:
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico_path = os.path.join(base, "icon.ico")
        if os.path.exists(ico_path):
            return ico_path
        png_path = os.path.join(base, "ui", "web_new_v2", "assets", "logo.png")
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
                self.api._on_restored()
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

        with self._lock:
            current_track = dict(self._current_track) if self._current_track else None
            is_playing = self._is_playing

        # Track status title
        if current_track:
            title = current_track.get('title') or 'Неизвестный трек'
            artist = current_track.get('artist') or 'Неизвестный артист'
            play_indicator = "▶" if is_playing else "⏸"
            status_text = f"{play_indicator} {title} — {artist}"
            is_fav = bool(current_track.get('is_favorite', False))
            fav_text = "💔 Удалить из любимых" if is_fav else "❤️ В любимые"
        else:
            status_text = "NeDotify (Остановлено)"
            fav_text = "❤️ В любимые"

        play_pause_label = "⏸ Пауза" if is_playing else "▶ Воспроизведение"

        menu_items = [
            item(status_text, self.on_show, default=True),
            Menu.SEPARATOR,
            item(play_pause_label, self.on_play_pause),
            item("⏭ Следующий трек", self.on_next),
            item("⏮ Предыдущий трек", self.on_prev),
            item(fav_text, self.on_toggle_favorite),
            Menu.SEPARATOR,
            item("🗔 Открыть NeDotify", self.on_show),
            item("❌ Выход", self.on_exit)
        ]
        return Menu(*menu_items)

    def update_state(self, track=None, is_playing=None, force=False):
        """Keep the latest state; the tray thread rebuilds native menus when opened."""
        with self._lock:
            if track is not None:
                self._current_track = dict(track)
            if is_playing is not None:
                self._is_playing = bool(is_playing)

    def start(self):
        """Own one tray thread and defer stop requests until pystray is ready."""
        if not HAS_PYSTRAY:
            logger.info('pystray not available; tray disabled.')
            return
        with self._lock:
            if self._thread is not None or self._stop_requested.is_set():
                return
            owner = self
            class OwnedIcon(pystray.Icon):
                def _on_notify(self, wparam, lparam):
                    # Win32 context menus are allocated/destroyed only by this
                    # icon's message-loop thread, never a playback callback.
                    if lparam == 0x0205:  # WM_RBUTTONUP
                        self.menu = owner._build_menu()
                    return super()._on_notify(wparam, lparam)
            def setup(icon):
                self._ready.set()
                if self._stop_requested.is_set():
                    icon.stop()
                else:
                    self._is_running = True
                    icon.visible = True
            def run():
                try:
                    image = self.create_image()
                    if image is None or self._stop_requested.is_set():
                        return
                    self.icon = OwnedIcon('NeDotify', image, 'NeDotify', self._build_menu())
                    self.icon.run(setup=setup)
                except Exception:
                    logger.warning('System tray failed', exc_info=True)
                finally:
                    self._is_running = False
                    self._ready.set()
            self._thread = threading.Thread(target=run, name='TrayThread', daemon=True)
            self._thread.start()

    def stop(self):
        """A stop before native readiness is applied by the setup callback."""
        self._stop_requested.set()
        icon = self.icon
        if icon is not None and self._ready.is_set():
            try:
                icon.stop()
            except Exception:
                logger.warning('Tray stop failed', exc_info=True)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(2)
        self._is_running = False
