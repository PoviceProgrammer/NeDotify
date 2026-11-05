"""Linux desktop integration without shell interpolation or elevated processes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import threading

logger = logging.getLogger(__name__)
_dispatchers = {}
_dispatcher_lock = threading.RLock()


def application_command():
    if getattr(sys, 'frozen', False):
        data_root = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'nedotify-app'
        executable = Path(sys.executable).resolve()
        sentinel = data_root / '.managed'
        launcher = Path.home() / '.local' / 'bin' / 'nedotify'
        try:
            if executable.is_relative_to((data_root / 'releases').resolve()) and sentinel.read_text().strip() == 'nedotify.linux.install.v1' and launcher.is_file():
                return [str(launcher)]
        except OSError:
            pass
        return [str(executable)]
    return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve().parents[1] / 'main.py')]


def desktop_exec(arguments):
    """Quote an Exec field according to the Desktop Entry specification."""
    def quote(value):
        value = str(value).replace('%', '%%')
        return '"' + ''.join('\\' + c if c in '\\"`$' else c for c in value) + '"'
    return ' '.join(quote(value) for value in arguments)


def update_autostart(enabled):
    directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'autostart'
    target = directory / 'nedotify.desktop'
    if not enabled:
        target.unlink(missing_ok=True)
        return True
    directory.mkdir(parents=True, exist_ok=True)
    entry = ('[Desktop Entry]\nType=Application\nName=NeDotify\n'
             'Comment=Music player\nExec=' + desktop_exec(application_command()) + '\n'
             'Icon=nedotify\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
    temporary = target.with_suffix('.desktop.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as output:
        output.write(entry)
        output.flush()
        os.fsync(output.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, target)
    return True


def on_ui_thread(window, callback):
    """Marshal native Qt/GTK operations; pywebview methods marshal themselves."""
    native = getattr(window, 'native', None)
    if native is None:
        callback()
        return
    if hasattr(native, 'windowHandle'):
        from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None or QThread.currentThread() == app.thread():
            callback()
            return
        with _dispatcher_lock:
            dispatcher = _dispatchers.get(id(window))
            if dispatcher is None:
                class Dispatcher(QObject):
                    invoke = pyqtSignal(object)

                    def __init__(self):
                        super().__init__()
                        self.invoke.connect(self.execute, Qt.ConnectionType.QueuedConnection)

                    def execute(self, operation):
                        try:
                            operation()
                        except Exception:
                            logger.warning('Linux window operation failed', exc_info=True)
                dispatcher = Dispatcher()
                dispatcher.moveToThread(app.thread())
                _dispatchers[id(window)] = dispatcher
            dispatcher.invoke.emit(callback)
        return
    if hasattr(native, 'get_window'):
        from gi.repository import GLib
        def run():
            callback()
            return False
        GLib.idle_add(run)
        return
    callback()


def native_geometry(window):
    native = getattr(window, 'native', None)
    if native is not None and hasattr(native, 'geometry'):
        bounds = native.geometry()
        return bounds.width(), bounds.height(), bounds.x(), bounds.y()
    if native is not None and hasattr(native, 'get_size'):
        width, height = native.get_size()
        x, y = native.get_position()
        return width, height, x, y
    return window.width, window.height, getattr(window, 'x', None), getattr(window, 'y', None)


def workarea(window):
    native = getattr(window, 'native', None)
    if native is not None and hasattr(native, 'screen'):
        bounds = native.screen().availableGeometry()
        return bounds.x(), bounds.y(), bounds.width(), bounds.height()
    if native is not None and hasattr(native, 'get_display'):
        display = native.get_display()
        monitor = display.get_monitor_at_window(native.get_window())
        bounds = monitor.get_workarea()
        return bounds.x, bounds.y, bounds.width, bounds.height
    return None


def set_minimum_size(window, width, height):
    native = getattr(window, 'native', None)
    if native is not None and hasattr(native, 'setMinimumSize'):
        native.setMinimumSize(width, height)
    elif native is not None and hasattr(native, 'set_geometry_hints'):
        from gi.repository import Gdk
        geometry = Gdk.Geometry()
        geometry.min_width, geometry.min_height = width, height
        native.set_geometry_hints(None, geometry, Gdk.WindowHints.MIN_SIZE)


def begin_window_gesture(window, direction=None):
    native = getattr(window, 'native', None)
    if native is None:
        return {'success': False, 'error': 'Window is not ready'}
    if hasattr(native, 'windowHandle'):
        from PyQt6.QtCore import Qt
        def apply():
            handle = native.windowHandle()
            if not handle:
                return
            if direction is None:
                handle.startSystemMove()
            else:
                edges = {'n': Qt.Edge.TopEdge, 's': Qt.Edge.BottomEdge,
                         'w': Qt.Edge.LeftEdge, 'e': Qt.Edge.RightEdge}
                value = Qt.Edge(0)
                for character in direction:
                    value |= edges[character]
                handle.startSystemResize(value)
        on_ui_thread(window, apply)
        return {'success': True}
    if hasattr(native, 'begin_move_drag'):
        def apply():
            from gi.repository import Gdk, Gtk
            pointer = native.get_display().get_default_seat().get_pointer()
            _, x, y = pointer.get_position()
            timestamp = Gtk.get_current_event_time()
            if direction is None:
                native.begin_move_drag(1, x, y, timestamp)
            else:
                edges = {'n': Gdk.WindowEdge.NORTH, 's': Gdk.WindowEdge.SOUTH,
                         'w': Gdk.WindowEdge.WEST, 'e': Gdk.WindowEdge.EAST,
                         'nw': Gdk.WindowEdge.NORTH_WEST, 'ne': Gdk.WindowEdge.NORTH_EAST,
                         'sw': Gdk.WindowEdge.SOUTH_WEST, 'se': Gdk.WindowEdge.SOUTH_EAST}
                native.begin_resize_drag(edges[direction], 1, x, y, timestamp)
        on_ui_thread(window, apply)
        return {'success': True}
    return {'success': False, 'error': 'Native window gestures are unavailable in this backend'}


class LinuxDesktopIntegration:
    """One session-bus owner for MPRIS, desktop notifications and media keys."""
    def __init__(self, api):
        self.api = api
        self._stop = threading.Event()
        self._thread = None
        self._loop = None
        self._bus = None
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='DesktopControl')
        self._last_notification = None

    def start(self):
        if sys.platform != 'linux' or self._thread is not None:
            return
        self.api._linux_desktop = self
        def run():
            try:
                asyncio.run(self._run())
            except Exception:
                logger.warning('Desktop session bus unavailable; MPRIS/notifications could not start', exc_info=True)
        self._thread = threading.Thread(target=run, name='LinuxDesktop', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
        self._workers.shutdown(wait=False, cancel_futures=True)

    def dispatch(self, action, value=None):
        if self._stop.is_set():
            return
        def execute():
            if action in ('next', 'prev', 'toggle_like'):
                window = self.api._window
                if window:
                    window.evaluate_js("window.dispatchEvent(new CustomEvent('nedotify:tray_action', {detail:{action:" + json.dumps(action) + '}}));')
            elif action == 'raise':
                window = self.api._window
                if window:
                    window.restore()
                    window.show()
            elif action == 'quit':
                self.api.close()
            else:
                self._system_event(action, value)
        try:
            self._workers.submit(execute)
        except RuntimeError:
            pass

    def _system_event(self, action, value):
        payload = json.dumps({'action': action, 'value': value})
        window = self.api._window
        if window and not self._stop.is_set():
            window.evaluate_js("window.dispatchEvent(new CustomEvent('nedotify:system_media', {detail:" + payload + '}));')

    def snapshot(self):
        facts = self.api._discord_snapshot()
        track = facts.get('track') or {}
        identity = str(track.get('source', '')) + ':' + str(track.get('id') or track.get('source_id') or '')
        state = facts.get('state', 'stopped')
        position = float(facts.get('position_sec') or 0)
        if state == 'playing':
            import time
            position += max(0, time.monotonic() - facts.get('updated_at', time.monotonic())) * facts.get('playback_rate', 1)
        queue = self.api._core.engine.queue
        return {'track': track, 'track_id': '/org/mpris/MediaPlayer2/track/' + hashlib.sha256(identity.encode()).hexdigest(),
                'state': {'playing': 'Playing', 'paused': 'Paused'}.get(state, 'Stopped'),
                'position': max(0, round(position * 1_000_000)),
                'duration': max(0, round(float(facts.get('duration_sec') or track.get('duration') or 0) * 1_000_000)),
                'volume': self.api.get_volume() / 100,
                'shuffle': bool(queue.shuffle), 'repeat': queue.repeat}

    async def _run(self):
        from dbus_next.aio import MessageBus
        from dbus_next.constants import RequestNameReply
        from core.mpris import create_interfaces
        self._loop = asyncio.get_running_loop()
        self._bus = await MessageBus().connect()
        try:
            reply = await self._bus.request_name('org.mpris.MediaPlayer2.nedotify')
            if reply not in (RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER):
                logger.warning('Another application already owns the NeDotify MPRIS name')
                return
            root, player = create_interfaces(self)
            self._bus.export('/org/mpris/MediaPlayer2', root)
            self._bus.export('/org/mpris/MediaPlayer2', player)
            previous = {}
            while not self._stop.is_set():
                values = player.properties()
                changed = {key: value for key, value in values.items() if previous.get(key) != value}
                if changed:
                    player.emit_properties_changed(changed)
                previous = values
                await asyncio.sleep(.25)
        finally:
            self._bus.disconnect()
            self._bus = None

    def notify(self, title, body):
        if self._stop.is_set() or self._bus is None or self._loop is None:
            return
        if not self.api._core.settings.get('general', 'show_notifications', True):
            return
        async def send():
            from dbus_next import Message
            try:
                await self._bus.call(Message(destination='org.freedesktop.Notifications',
                    path='/org/freedesktop/Notifications', interface='org.freedesktop.Notifications',
                    member='Notify', signature='susssasa{sv}i',
                    body=['NeDotify', 0, 'nedotify', str(title)[:200], __import__('html').escape(str(body)[:1000]), [], {}, 5000]))
            except Exception:
                logger.debug('Desktop notification unavailable', exc_info=True)
        try:
            asyncio.run_coroutine_threadsafe(send(), self._loop)
        except RuntimeError:
            pass
