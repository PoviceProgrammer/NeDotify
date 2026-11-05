"""Qt system tray with StatusNotifierItem support on X11 and Wayland."""
import json
import logging
from pathlib import Path
import sys
import threading

from core.linux_integration import on_ui_thread

logger = logging.getLogger(__name__)


class LinuxTrayIcon:
    def __init__(self, api, icon_path=None):
        self.api = api
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        self.icon_path = str(icon_path or base / 'icon.png')
        self.icon = None
        self._menu = None
        self._lock = threading.RLock()
        self._current_track = None
        self._is_playing = False
        self._is_running = False
        self._stopped = False
        self._started = False

    def _dispatch_js(self, action):
        window = self.api._window
        if window and not self._stopped:
            window.evaluate_js("window.dispatchEvent(new CustomEvent('nedotify:tray_action', {detail:{action:" + json.dumps(action) + '}}));')

    def _worker(self, callback):
        # evaluate_js waits for Chromium. Never wait on it in a Qt slot.
        threading.Thread(target=callback, name='TrayControl', daemon=True).start()

    def on_show(self, *args):
        window = self.api._window
        if window:
            window.restore()
            window.show()
            self.api._on_restored()

    def on_play_pause(self, *args):
        self._dispatch_js('toggle_play')

    def on_next(self, *args):
        self._dispatch_js('next')

    def on_prev(self, *args):
        self._dispatch_js('prev')

    def on_toggle_favorite(self, *args):
        self._dispatch_js('toggle_like')

    def on_exit(self, *args):
        self.api.close()

    def update_state(self, track=None, is_playing=None, force=False):
        with self._lock:
            if track is not None:
                self._current_track = dict(track)
            if is_playing is not None:
                self._is_playing = bool(is_playing)

    def _build_menu(self):
        self._menu.clear()
        with self._lock:
            track = dict(self._current_track or {})
            playing = self._is_playing
        title = (str(track.get('title') or '') + ' — ' + str(track.get('artist') or '')).strip(' —') or 'NeDotify'
        self.icon.setToolTip(title[:200])
        status = self._menu.addAction(title[:160])
        status.setEnabled(False)
        self._menu.addSeparator()
        for label, callback in (
            ('Пауза' if playing else 'Воспроизведение', self.on_play_pause),
            ('Следующий трек', self.on_next), ('Предыдущий трек', self.on_prev),
            ('Удалить из любимых' if track.get('is_favorite') else 'В любимые', self.on_toggle_favorite),
            ('Открыть NeDotify', self.on_show), ('Выход', self.on_exit),
        ):
            self._menu.addAction(label).triggered.connect(lambda checked=False, fn=callback: self._worker(fn))

    def start(self):
        if self._started or self._stopped:
            return
        self._started = True
        window = self.api._window
        self._owner_window = window
        def loaded(*args):
            if self._stopped:
                return
            def create():
                if self._stopped or self.icon is not None:
                    return
                try:
                    from PyQt6.QtGui import QIcon
                    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
                    if not QSystemTrayIcon.isSystemTrayAvailable():
                        logger.info('No desktop tray host; use the window and MPRIS controls')
                        return
                    native = getattr(window, 'native', None)
                    self.icon = QSystemTrayIcon(QIcon(self.icon_path), native)
                    self._menu = QMenu(native)
                    self._menu.aboutToShow.connect(self._build_menu)
                    self.icon.setContextMenu(self._menu)
                    self.icon.activated.connect(lambda reason: self._worker(self.on_show)
                        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
                    self._build_menu()
                    self.icon.show()
                    self._is_running = True
                except Exception:
                    logger.warning('Linux system tray could not start', exc_info=True)
            on_ui_thread(window, create)
        if getattr(window, 'native', None) is not None:
            loaded()
        else:
            window.events.loaded += loaded

    def stop(self):
        self._stopped = True
        self._is_running = False
        icon = self.icon
        window = getattr(self, '_owner_window', None)
        if icon is not None and window:
            on_ui_thread(window, icon.hide)
