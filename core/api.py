"""
NeDotify - Web API Bridge
Exposes Python backend methods to the JavaScript frontend via pywebview.
"""


import hashlib
import json
import logging
import inspect
import math
import os
import queue as queue_module
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import webview
from utils.stream_urls import stream_url_expired
from utils.cache_manager import stream_cache_stem
from core.offline import offline_library
from core.user_errors import describe_error
from utils.url_safety import safe_public_url, guarded_open_url

logger = logging.getLogger(__name__)

# Captured once: evaluate_js must never be awaited on this thread (see _emit).
_MAIN_THREAD = threading.main_thread()
_UNSET = object()

# --- Licensing (Q3 decision: no subscription is planned) -------------------
# License/subscription validation is intentionally disabled and stays dead code:
# nothing in the UI calls validate_subscription_key / get_subscription_info, and
# the flag below has no consumer other than those two stubs. They are kept (not
# deleted) as the documented seam where a server-owned licensing service would
# plug in, so nobody re-adds a client-side key check later. Do not wire any new
# UI to them.
LICENSE_VALIDATION_ENABLED = False

# --- Autostart: the Windows "Run" value name --------------------------------
# Single source of truth for the value name written to
#   HKCU\Software\Microsoft\Windows\CurrentVersion\Run
# installer.iss writes the SAME name in its [Registry] section. Inno Setup
# cannot read a Python constant, so the literal "NeDotify" is repeated there;
# tests/test_build_and_brand.py fails the build when the two sides diverge.
# Hive, key path and value name must match on both sides: while this method
# wrote "AURA Music" and the installer wrote "NeDotify", Windows logged the user
# in, started the app twice and no single toggle could switch both entries off.
AUTOSTART_RUN_VALUE = "NeDotify"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # under HKCU

# Run value names written by earlier builds. They have to be deleted on EVERY
# toggle, not only when autostart is switched off: a leftover "AURA Music"
# entry keeps launching whatever path it points at, so enabling autostart with
# the stale entry still around produced a second launch at logon.
AUTOSTART_RUN_LEGACY_VALUES = ("AURA Music",)

# Hard per-provider search deadline. Raised from 4.0 to 6.0: yt-dlp socket_timeout
# is 6s and YTMusic session timeout is 15s; a 4s bridge deadline forced a
# visible "nothing found" before the provider even answered.
PROVIDER_SEARCH_TIMEOUT = 6.0

# Total wall-clock budget for a bridge method that must answer synchronously.
# pywebview serves the call on a bridge thread and the JS caller is awaiting it, so
# a long block is felt as a frozen UI. Multi-stage lookups share this one budget
# instead of each stage getting its own timeout.
BRIDGE_SYNC_BUDGET = 6.0

# Window geometry: main window and compact mini player.
# MINI_WINDOW_SIZE is in LOGICAL (CSS) pixels: toggle_mini_player multiplies it
# by the display scale factor before calling window.resize(), which takes
# PHYSICAL pixels (pywebview's WinForms backend passes the size to SetWindowPos
# unscaled). Without the multiplication the card shrinks on 125%/150% DPI.
MAIN_WINDOW_SIZE = (1100, 800)
MINI_WINDOW_SIZE = (340, 64)
MAIN_WINDOW_MIN_SIZE = (600, 640)

# Cover image formats the tag editor and the /api/cover proxy both accept.
# A cached cover MUST keep its real extension: core/proxy.py serves the file
# with mimetypes.guess_type(<path>), so PNG/WebP bytes under a ".jpg" name were
# published as image/jpeg and the browser refused to decode them.
_COVER_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_COVER_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _is_ssrf_safe_url(url: str) -> bool:
    return safe_public_url(url)


_URL_IN_TEXT_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)


def _extract_first_url(raw: str) -> str:
    if not raw:
        return ''
    match = _URL_IN_TEXT_RE.search(str(raw).strip())
    if not match:
        return str(raw).strip()
    url = match.group(0).rstrip('.,;:!?"\'')
    for opening, closing in (('(', ')'), ('[', ']'), ('{', '}')):
        while url.endswith(closing) and url.count(closing) > url.count(opening):
            url = url[:-1]
    return url


def _as_float(value):
    """Best-effort float conversion; None when the value is not numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


# Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
_SECRET_SETTING_KEYS = {"auth": ("yandex_token", "yandex_refresh_token", "vk_token", "spotify_token", "spotify_refresh_token", "oauth_client_secret", "proxy_url", "lastfm_api_key", "lastfm_api_secret"),
                        "services": ("lastfm_api_key", "lastfm_api_secret")}


def _mask_secrets(category: str, data: dict) -> dict:
    """Replace stored secrets with "" plus has_<key> booleans for the bridge."""
    secret_keys = _SECRET_SETTING_KEYS.get(category)
    if not secret_keys or not isinstance(data, dict):
        return data
    masked = dict(data)
    for key in secret_keys:
        if key in masked:
            masked[f"has_{key}"] = bool(masked[key])
            masked[key] = ""
    return masked


# Settings the bridge refuses to write: enabling plugins runs third-party code.
_BRIDGE_READONLY_SETTINGS = {("general", "plugins_enabled")}


def _bridge_write_error(category: str, key: str, value):
    """Error message when a bridge write must be refused, else None."""
    if (category, key) in _BRIDGE_READONLY_SETTINGS:
        return f"{category}.{key} cannot be changed from the UI"
    return None


def _is_empty_secret_write(category: str, key: str, value) -> bool:
    """A blank secret from the UI (masked read echoed back) must not wipe the stored one."""
    return key in _SECRET_SETTING_KEYS.get(category, ()) and value == ""


def _normalize_cache_quota(quota_gb=None, cache_size_mb=None, cache_quota_gb=None):
    gb = _as_float(cache_quota_gb if cache_quota_gb is not None else quota_gb)
    mb = _as_float(cache_size_mb)
    if gb is None:
        if mb is None:
            return None, None
        gb = mb / 1024
    return max(0.0, gb), max(0.0, gb * 1024)


def _missing_local_file_message(track, file_path=None) -> str:
    """Human-readable reason a local track cannot be played."""
    label = "Трек"
    if isinstance(track, dict):
        title = str(track.get("title") or "").strip()
        artist = str(track.get("artist") or "").strip()
        if title:
            label = f"«{title}»" + (f" — {artist}" if artist else "")
    where = f" ({file_path})" if file_path else ""
    return f"{label}: аудиофайл не найден{where}"


class AppApi:
    _emitter_init_lock = threading.Lock()
    """JS Bridge API passed to PyWebView create_window(js_api=...)."""

    def __init__(self, core):
        self._core = core
        self._core.api = self
        self._window = None
        self._main_window = None
        self._mini_window = None
        self._is_mini_active = False
        self._saved_mini_pos = "bottom-right"
        self._window_op_lock = threading.RLock()
        self._listening_sessions = {}
        self._active_listening_token = None
        self._closed = False
        self._ui_ready_event = threading.Event()
        # Renderer liveness (see frontend_heartbeat); monotonic clock domain.
        self._ui_heartbeat_monotonic = None
        self._ui_visibility = 'visible'
        self._emit_queue = queue_module.Queue(maxsize=512)
        self._emit_worker = None
        self._playback_epoch = 0
        self._queue_revision = 0
        self._bridge_call_depth = threading.local()
        self._search_futures = set()
        self._search_timers = set()

        # C-2: lyrics cascade counter (verification: exactly one cascade per request)
        self._lyrics_cascade_count = 0
        self._lyrics_lock = threading.Lock()

        # Dedicated search executor for non-blocking provider and DB searches
        from concurrent.futures import ThreadPoolExecutor
        self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")
        self._search_lock = threading.Lock()
        self._search_generation = 0
        # Warming a stream can wait for a provider; never queue it behind search
        # or let an entire playlist flood the provider pool. Shared bookkeeping
        # uses the existing search lock; queued + running warmups are capped at 2.
        self._prefetch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="StreamWarmup")
        self._prefetch_pending = set()
        self._playback_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="PlaybackResolve")
        # Queued-but-unstarted resolution tasks (BUG-A1-009): a play/next/prev
        # epoch bump cancels them instead of letting each burn a worker slot
        # on a full network cascade for a track nobody waits for anymore.
        self._resolution_futures = set()
        self._resolution_futures_lock = threading.Lock()
        self._metadata_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="Metadata")
        self._lyrics_request_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="LyricsRequest")
        self._waveform_cache = {}
        self._waveform_flights = {}

        # Connect engine event callbacks
        if hasattr(self._core, "engine") and self._core.engine:
            self._core.engine._on_track_changed = self._on_track_changed
            # H-5: this hook existed on the engine but nothing ever assigned it,
            # so reaching the end of the queue produced neither an event nor any
            # autoplay. Wired up here; the frontend handles the track end by
            # calling next_track(), whose None result it already treats as
            # "stopped", so this only publishes the backend-side fact.
            self._core.engine._on_queue_end = self._on_queue_end
            if hasattr(self._core.engine, "on_error"):
                self._core.engine.on_error(self._on_audio_error)

        try:
            from core.tray import TrayIcon
            self._tray = TrayIcon(self)
        except Exception as te:
            logger.debug(f"Tray initialization ignored: {te}")
            self._tray = None
        self._core.tray = self._tray

        self._install_bridge_error_logging()

    # Methods that must never be wrapped: the wrapper itself, lifecycle hooks that
    # run while the window reference is being torn down, and the emit primitives it
    # depends on (wrapping those would recurse on failure).
    _UNWRAPPED = frozenset({
        "cleanup", "shutdown", "set_window", "set_windows", "emit_event",
    })

    def _install_bridge_error_logging(self):
        """Wrap every exposed bridge method so exceptions are logged and surfaced.

        pywebview turns an exception inside a js_api call into a rejected JS promise
        with no server-side trace, which is why a broken bridge method used to look
        like a button that silently does nothing. The wrapper logs the full traceback
        and pushes an `api_error` event to the UI, then re-raises so no caller's
        contract or return type changes.
        """
        import functools
        import types

        for name in dir(type(self)):
            if name.startswith("_") or name in self._UNWRAPPED:
                continue
            attr = getattr(type(self), name, None)
            if not callable(attr):
                continue

            def _make(func, method_name):
                @functools.wraps(func)
                def _wrapped(inner_self, *args, **kwargs):
                    depth = getattr(inner_self._bridge_call_depth, 'value', 0)
                    inner_self._bridge_call_depth.value = depth + 1
                    try:
                        if getattr(inner_self, '_closed', False):
                            return None
                        return func(inner_self, *args, **kwargs)
                    except Exception as exc:
                        details = describe_error(exc, method_name)
                        logger.error("bridge call %s() failed: %s [%s]", method_name, type(exc).__name__, details['code'])
                        try:
                            inner_self._emit("api_error", {
                                "method": method_name,
                                "error": details['message'],
                                **details,
                            })
                        except Exception:
                            logger.debug("api_error emit failed", exc_info=True)
                        raise RuntimeError(details['message']) from None
                    finally:
                        inner_self._bridge_call_depth.value = depth
                        if depth == 0 and threading.current_thread() is not _MAIN_THREAD:
                            close = getattr(getattr(inner_self._core, 'db', None), 'close_thread_connection', None)
                            if callable(close):
                                close()
                _wrapped.__signature__ = inspect.signature(func)
                return _wrapped

            setattr(self, name, types.MethodType(_make(attr, name), self))

    def cleanup(self):
        """Quiesce callbacks before the window or database is torn down."""
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self._window = None
        self.shutdown()
        ready = getattr(self, '_ui_ready_event', None)
        if ready:
            ready.set()
        events = getattr(self, '_emit_queue', None)
        if events is not None:
            try:
                while True:
                    pending = events.get_nowait()
                    if pending:
                        pending[1].set()
            except queue_module.Empty:
                pass
            events.put_nowait(None)
        for timer in list(getattr(self, '_search_timers', ())):
            timer.cancel()
        for name in ('_search_executor', '_prefetch_executor', '_playback_executor', '_metadata_executor', '_lyrics_request_executor'):
            executor = getattr(self, name, None)
            shutdown = getattr(executor, 'shutdown', None)
            if callable(shutdown):
                shutdown(wait=False, cancel_futures=True)
        tray = getattr(self, '_tray', None)
        if tray:
            tray.stop()
        worker = getattr(self, '_emit_worker', None)
        if worker and worker is not threading.current_thread():
            worker.join(2)

    def set_window(self, window):
        """Set main webview window reference."""
        self._window = window
        self._main_window = window
        zapret = getattr(self._core, "zapret", None)
        if zapret and hasattr(zapret, "_set_elevation_window"):
            zapret._set_elevation_window(self._get_hwnd)
        # BUG-025: ZapretService reports late crashes (and a still-running
        # elevated process at shutdown) through an event hook; the service
        # never imports this layer, so the bridge is attached from here.
        if zapret and hasattr(zapret, "set_event_callback"):
            zapret.set_event_callback(self._emit_zapret_event)
        if hasattr(self._window, 'events'):
            self._window.events.minimized += self._on_minimized
            self._window.events.restored += self._on_restored
            self._window.events.maximized += self._on_restored
            self._window.events.shown += self._on_restored
            if hasattr(self._window.events, 'resized'):
                self._window.events.resized += self._on_window_resized

        if getattr(self, '_tray', None) and not os.environ.get('PYTEST_CURRENT_TEST'):
            self._tray.start()

        # Windows 11 Snap Layouts: a frameless window has no caption, so Windows
        # never offers the layout grid on the maximise button. Best-effort - a
        # failure here must not stop the app from starting.
        #
        # Deferred on purpose: at set_window() time the native handle usually
        # does not exist yet (pywebview has not created the WinForms window),
        # and a plain "hwnd is None, try nothing" would silently skip the whole
        # feature. A short retry loop covers that race instead.
        try:
            threading.Thread(target=self._install_snap_layouts, daemon=True).start()
        except Exception as e:
            logger.warning("Snap Layouts unavailable: %s", type(e).__name__)

    def _install_snap_layouts(self, attempts: int = 120, delay: float = 0.25):
        """Install the Snap Layouts WndProc once the HWND exists."""
        if sys.platform != "win32":
            return False
        try:
            from core.snap_layouts import SnapLayouts
        except Exception as e:
            logger.warning("Snap Layouts module unavailable: %s", type(e).__name__)
            return False

        for _ in range(attempts):
            if getattr(self, "_closed", False):
                return False
            hwnd = None
            try:
                hwnd = self._get_hwnd()
            except Exception:
                logger.debug("Snap Layouts hwnd lookup failed", exc_info=True)
            if hwnd:
                try:
                    snap = SnapLayouts(hwnd, can_resize=lambda: not (getattr(self, '_is_maximized', False) or self._is_mini_active))
                    if snap.install():
                        self._snap_layouts = snap
                        pending_rect = getattr(self, '_pending_snap_rect', None)
                        if pending_rect:
                            snap.set_button_rect(*pending_rect)
                        self._set_native_icon()
                        logger.info("Snap Layouts enabled on hwnd=%s", hwnd)
                        return True
                    logger.warning("Snap Layouts subclass rejected (hwnd=%s)", hwnd)
                    return False
                except Exception as e:
                    logger.warning("Snap Layouts install failed: %s", type(e).__name__)
                    return False
            time.sleep(delay)
        logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
        return False

    def _on_minimized(self):
        self._ui_visibility = 'hidden'
        self._window_was_minimized = True
        self._ui_heartbeat_monotonic = time.monotonic()
        save = getattr(getattr(self, '_core', None), 'save_session', None)
        if callable(save):
            save()
        self._emit('window_visibility', {'hidden': True})

    def _on_restored(self):
        self._ui_visibility = 'visible'
        self._ui_heartbeat_monotonic = time.monotonic()
        self._emit('window_visibility', {'hidden': False})
        # WHITE-001: reloading the page on every minimize→restore was the old
        # self-heal for a stale compositor surface, but the reload itself is a
        # race against the restore animation: if the navigation lands while the
        # host is still re-attaching its GPU surface (probabilistic after 1..N
        # cycles) the user keeps a white page. The page is never reloaded here
        # any more; `resized` already refits the WebView bounds on the UI
        # thread, the frontend kicks a repaint when it sees this
        # window_visibility event, and the render watchdog in main.py remains
        # the bounded last resort for a genuinely dead renderer.
        if (sys.platform == 'win32' and getattr(self, '_window', None)
                and getattr(self, '_window_was_minimized', False)):
            self._window_was_minimized = False
            window = self._window
            self._deferred_window_op(0.05, lambda: self._on_window_ui_thread(
                window, lambda: self._fit_window_content(window)))

    def _fit_window_content(self, target_win):
        """Match WebView2 to the client area, on the WinForms UI thread."""
        native = getattr(target_win, 'native', None)
        view = getattr(native, 'webview', None)
        if view is None:
            return
        native.PerformLayout()
        area = native.ClientRectangle
        if (view.Left, view.Top, view.Width, view.Height) != (area.X, area.Y, area.Width, area.Height):
            view.Bounds = area
            view.Invalidate()

    def _recalc_native_frame(self, hwnd):
        """Force a WM_NCCALCSIZE pass on the frameless host window.

        WHITE-001 root cause (reproduced live): after minimize → restore the
        DWM keeps showing a blank surface for a window whose WM_NCCALCSIZE is
        overridden (our frameless SnapLayouts setup), even though the WebView2
        renderer keeps producing correct frames (verified via CDP screenshots:
        renderer dark, screen white). Repaints of the child do not help; a
        SetWindowPos with SWP_FRAMECHANGED re-runs the NCCALCSIZE handler and
        reattaches the window to its surface instantly.

        Fires only when zoom/iconic state changed between two consecutive
        resize events, so plain drag-resizes never pay for it. Min→restore
        itself is two events: the minimize event stores the iconic marker, the
        restore event sees the change and re-runs NCCALCSIZE.
        """
        if sys.platform != 'win32' or not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            marker = (bool(user32.IsZoomed(int(hwnd))), bool(user32.IsIconic(int(hwnd))))
            previous = getattr(self, '_last_state_marker', None)
            self._last_state_marker = marker
            if previous is None or previous == marker:
                return
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
            SWP_FRAMECHANGED, SWP_NOACTIVATE = 0x0020, 0x0010
            user32.SetWindowPos(
                int(hwnd), None, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE)
        except Exception:
            logger.debug('Frame recalc after window state change failed', exc_info=True)

    def _on_window_resized(self, *size):
        window = getattr(self, '_window', None)
        if sys.platform != 'win32' or not window or getattr(self, '_closed', False):
            return
        with self._window_op_lock:
            if getattr(self, '_resize_queued', False):
                return
            self._resize_queued = True
        def fit():
            try:
                if getattr(self, '_closed', False):
                    return
                native = getattr(window, 'native', None)
                if native is not None and hasattr(native, 'WindowState'):
                    from System.Windows.Forms import FormWindowState
                    self._is_maximized = native.WindowState == FormWindowState.Maximized
                    if not self._is_maximized and not self._is_mini_active:
                        bounds = native.Bounds
                        self._last_geometry = (bounds.X, bounds.Y, bounds.Width, bounds.Height)
                self._fit_window_content(window)
                # WHITE-001: re-sync the frameless window surface whenever its
                # state transitioned (restore/maximize/minimize detached it).
                self._recalc_native_frame(self._get_hwnd())
            finally:
                with self._window_op_lock:
                    self._resize_queued = False
        try:
            self._on_window_ui_thread(window, fit)
        except Exception:
            with self._window_op_lock:
                self._resize_queued = False
            raise

    def _get_scale_factor(self):
        """Use the same scale as pywebview's WinForms move() implementation."""
        native = getattr(getattr(self, '_window', None), 'native', None)
        for value in (getattr(native, 'scale_factor', None),
                      (getattr(native, 'DeviceDpi', 96) or 96) / 96):
            try:
                scale = float(value)
                if math.isfinite(scale) and .5 <= scale <= 8:
                    return scale
            except (TypeError, ValueError):
                pass
        return 1.0

    def _logical_workarea(self):
        """(x, y, w, h) of the work area (taskbar excluded) under the window,
        in LOGICAL pixels - matching what Window.move() expects."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            hwnd = self._get_hwnd()
            rect = RECT()
            got = False
            if hwnd:
                mon_rc = RECT()

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD),
                                ("rcMonitor", RECT),
                                ("rcWork", RECT),
                                ("dwFlags", wintypes.DWORD)]

                hmon = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
                if hmon:
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                        mon_rc = mi.rcWork
                        got = True
            if not got:
                # Primary monitor work area fallback
                if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    return None
                mon_rc = rect

            s = self._get_scale_factor()
            x = int(mon_rc.left / s)
            y = int(mon_rc.top / s)
            w = int((mon_rc.right - mon_rc.left) / s)
            h = int((mon_rc.bottom - mon_rc.top) / s)
            return x, y, w, h
        except Exception as e:
            logger.debug(f"_logical_workarea failed: {type(e).__name__}")
            return None

    def _saved_pos_coords(self, pos: str, w: int, h: int):
        """Compute screen coordinates (logical px) for a mini-player position."""
        area = self._logical_workarea()
        if not area:
            return None
        ax, ay, aw, ah = area
        scale = self._get_scale_factor()
        w, h = round(w / scale), round(h / scale)
        margin = 20
        if pos == 'top-left':
            return ax + margin, ay + margin
        if pos == 'top-center':
            return ax + (aw - w) // 2, ay + margin
        if pos == 'top-right':
            return ax + aw - w - margin, ay + margin
        if pos == 'bottom-left':
            return ax + margin, ay + ah - h - margin
        if pos == 'bottom-center':
            return ax + (aw - w) // 2, ay + ah - h - margin
        if pos == 'bottom-right':
            return ax + aw - w - margin, ay + ah - h - margin
        if pos == 'center':
            return ax + (aw - w) // 2, ay + (ah - h) // 2
        return ax + aw - w - margin, ay + margin

    def _deferred_window_op(self, delay: float, fn):
        """Run a native window operation on a background thread after a short delay.

        Calling pywebview window.resize()/move() synchronously from a JS bridge
        call deadlocks the WinForms UI thread. Let the bridge reply and the
        optimistic frontend state settle before sending native window messages.
        """
        def _run():
            time.sleep(delay)
            try:
                with self._window_op_lock:
                    if not getattr(self, '_closed', False):
                        fn()
            except Exception:
                logger.warning("Deferred window operation failed", exc_info=True)
        threading.Thread(target=_run, daemon=True).start()

    def _on_window_ui_thread(self, target_win, fn):
        """Queue a WinForms operation without blocking the JS bridge thread."""
        native = getattr(target_win, "native", None)
        try:
            if native is not None and native.InvokeRequired:
                from System import Action
                native.BeginInvoke(Action(fn))
                return
        except Exception:
            logger.debug("Could not queue window operation on UI thread", exc_info=True)
        fn()

    def _native_window_geometry(self, target_win):
        """Read window bounds through Win32, avoiding cross-thread Form getters."""
        if sys.platform != "win32":
            return None
        hwnd = self._get_hwnd()
        if not hwnd:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

            rect = RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                raise ctypes.WinError(ctypes.get_last_error())
            scale = self._get_scale_factor()
            # resize() accepts physical sizes; move() multiplies positions by
            # scale_factor in pywebview's WinForms backend.
            return (int(rect.right - rect.left), int(rect.bottom - rect.top),
                    round(rect.left / scale), round(rect.top / scale))
        except Exception:
            logger.debug("Could not read native window geometry", exc_info=True)
            return None

    def toggle_mini_player(self, enable: bool, request_id=None):
        """Apply only the latest native mini-player request and acknowledge completion."""
        if not isinstance(enable, bool) or not self._window:
            return {'success': False, 'is_mini': getattr(self, '_is_mini_active', False), 'request_id': request_id}
        import uuid
        rid = str(request_id or uuid.uuid4().hex)
        window = self._mini_window or self._window
        with self._window_op_lock:
            generation = getattr(self, '_mini_generation', 0) + 1
            self._mini_generation = generation
        def apply():
            if getattr(self, '_closed', False) or generation != self._mini_generation:
                return
            previous = getattr(self, '_native_mini_applied', False)
            try:
                native = getattr(window, 'native', None)
                if enable:
                    if not previous:
                        self._saved_main_geometry = self._native_window_geometry(window) or (*MAIN_WINDOW_SIZE, None, None)
                    if native is not None:
                        from System.Drawing import Size
                        from System.Windows.Forms import FormWindowState
                        self._saved_main_maximized = native.WindowState == FormWindowState.Maximized if not previous else getattr(self, '_saved_main_maximized', False)
                        native.WindowState = FormWindowState.Normal
                        native.MinimumSize = Size(1, 1)
                    window.on_top = True
                    self._set_native_window_corners(True)
                    scale = self._get_scale_factor()
                    # resize() takes PHYSICAL pixels; MINI_WINDOW_SIZE is logical
                    mini_w = int(MINI_WINDOW_SIZE[0] * scale)
                    mini_h = int(MINI_WINDOW_SIZE[1] * scale)
                    window.resize(mini_w, mini_h)
                    # _saved_pos_coords expects PHYSICAL dims (it normalizes to
                    # logical itself before comparing against the work area)
                    self._apply_window_pos(window, self._saved_mini_pos, mini_w, mini_h)
                else:
                    width, height, x, y = getattr(self, '_saved_main_geometry', (*MAIN_WINDOW_SIZE, None, None))
                    window.on_top = False
                    self._set_native_window_corners(False)
                    window.resize(int(width), int(height))
                    if native is not None:
                        from System.Drawing import Size
                        from System.Windows.Forms import FormWindowState
                        native.MinimumSize = Size(*MAIN_WINDOW_MIN_SIZE)
                        if getattr(self, '_saved_main_maximized', False):
                            native.WindowState = FormWindowState.Maximized
                    if x is not None and y is not None:
                        # Positioning must never fail the exit: the resize above
                        # already restored the main size, so the UI state has to
                        # follow it even if this move hiccups.
                        self._native_move_window(window, int(x), int(y))
                self._is_mini_active = enable
                self._native_mini_applied = enable
                self._emit('mini_player_toggled', {'success': True, 'is_mini': enable, 'request_id': rid})
            except Exception:
                self._is_mini_active = previous
                logger.warning('Mini-player native operation failed', exc_info=True)
                self._emit('mini_player_toggled', {'success': False, 'is_mini': previous, 'request_id': rid})
        try:
            self._on_window_ui_thread(window, apply)
        except Exception:
            return {'success': False, 'is_mini': getattr(self, '_is_mini_active', False), 'request_id': rid}
        return {'success': True, 'pending': True, 'is_mini': enable, 'request_id': rid}

    def _enter_mini_mode(self):
        """Internal compatibility hook; use the same correlated native transition."""
        return self.toggle_mini_player(True)

    def _exit_mini_mode(self):
        """Internal compatibility hook; use the same correlated native transition."""
        return self.toggle_mini_player(False)

    def _set_native_window_corners(self, rounded: bool):
        """Ask Windows 11 to clip the frameless mini window to rounded corners."""
        if sys.platform != "win32":
            return
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        try:
            import ctypes
            preference = ctypes.c_int(2 if rounded else 0)  # DWMWCP_ROUND / DEFAULT
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)
            )
            if result != 0:
                logger.debug("DWM corner preference was not applied (HRESULT 0x%08X)", result)
        except Exception:
            logger.debug("DWM corner preference is unavailable", exc_info=True)

    def set_mini_player_position(self, pos: str):
        """Move mini player window to a screen position (top-left, top-right, bottom-left, bottom-right, center).

        The position is remembered even while the mini player is inactive so it
        applies on the next entry; the native move only happens in mini mode.
        """
        if pos:
            self._saved_mini_pos = pos

        # CRITICAL GUARD: Only move native window if mini-player mode is active!
        if not self._is_mini_active and not self._mini_window:
            return

        target_win = self._mini_window or self._window
        if not target_win:
            return
        scale = self._get_scale_factor()
        mini_w = int(MINI_WINDOW_SIZE[0] * scale)
        mini_h = int(MINI_WINDOW_SIZE[1] * scale)
        self._deferred_window_op(0.1, lambda: self._apply_window_pos(target_win, pos, mini_w, mini_h))

    def _apply_window_pos(self, target_win, pos: str, w: int, h: int):
        """Compute target screen position for size (w x h) and move the window.

        w and h are PHYSICAL pixels: _saved_pos_coords normalizes them to
        logical before comparing against the logical work area.
        """
        try:
            coords = self._saved_pos_coords(pos, w, h)
            if not coords:
                logger.debug("No work area available for position %r", pos)
                return
            x, y = coords
            self._native_move_window(target_win, x, y)
        except Exception as e:
            logger.debug(f"Failed to move window to position {pos}: {type(e).__name__}")

    def _native_move_window(self, target_win, x, y):
        """Move the window via Win32 with real integer arguments.

        pywebview's WinForms move() passes None as the size arguments of
        SetWindowPos, which this ctypes build rejects - every Window.move()
        call raises ArgumentError. x and y are LOGICAL pixels, scaled to
        physical exactly like move() would. Failures are logged and swallowed:
        positioning is cosmetic and must never abort a mode transition.
        """
        if sys.platform != 'win32':
            try:
                target_win.move(int(x), int(y))
            except Exception:
                pass
            return
        hwnd = self._get_hwnd()
        if not hwnd:
            logger.debug('Native move skipped: window handle is unavailable')
            return
        try:
            import ctypes
            scale = self._get_scale_factor()
            SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW = 0x0001, 0x0004, 0x0040
            ctypes.windll.user32.SetWindowPos(
                int(hwnd), None,
                int(round(x * scale)), int(round(y * scale)),
                0, 0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW,
            )
        except Exception:
            logger.debug('Native window move failed', exc_info=True)

    def set_windows(self, main_window, mini_window):
        """Register dual window references for main player and mini player."""
        self._main_window = main_window
        self._mini_window = mini_window
        if not self._window:
            self._window = main_window

    def close(self):
        """The close button exits; ordinary minimize remains a separate action."""
        if not self._window:
            return {"success": True, "message": "No active window"}
        with self._window_op_lock:
            if getattr(self, '_close_requested', False):
                return {"success": True, "message": "Window closing..."}
            self._close_requested = True
        rpc = getattr(self._core, 'discord_rpc', None)
        if rpc:
            try:
                rpc.stop()
            except Exception:
                logger.debug('Discord stop request failed during window close', exc_info=True)
        self.flush_listening()
        closer = threading.Timer(0.1, self._window.destroy)
        closer.daemon = True
        closer.start()
        return {"success": True, "message": "Window closing..."}

    def shutdown(self):
        snap = getattr(self, '_snap_layouts', None)
        if snap is not None:
            try:
                snap.uninstall()
            except Exception:
                logger.warning('Snap subclass cleanup failed', exc_info=True)
            self._snap_layouts = None
        self._window = None
        self._main_window = None
        self._mini_window = None

    def close_window(self):
        """Close application window asynchronously."""
        return self.close()

    def minimize(self):
        """Minimize application window."""
        if self._window:
            self._window.minimize()

    def minimize_window(self):
        """Minimize application window."""
        self.minimize()

    def begin_window_drag(self):
        """Start a native caption drag for frameless-window drag handles."""
        if sys.platform != "win32":
            return {"success": False, "error": "Native dragging is only available on Windows"}
        hwnd = self._get_hwnd()
        if not hwnd:
            return {"success": False, "error": "Window handle is unavailable"}

        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            user32 = ctypes.windll.user32
            cursor = POINT()
            if not user32.GetCursorPos(ctypes.byref(cursor)):
                raise OSError("GetCursorPos failed")
            user32.ReleaseCapture()
            # WM_NCLBUTTONDOWN + HTCAPTION lets Windows own the drag loop,
            # keeping it smooth across monitors and DPI settings.
            packed = ((cursor.y & 0xFFFF) << 16) | (cursor.x & 0xFFFF)
            lparam = ctypes.c_ssize_t(ctypes.c_int32(packed).value)
            send = self._native_message_function()
            self._on_window_ui_thread(self._window, lambda: send(hwnd, 0x00A1, 2, lparam))
            return {"success": True}
        except Exception as exc:
            logger.warning("Native window drag failed: %s", type(exc).__name__, exc_info=True)
            return {"success": False, "error": describe_error(exc)['message']}

    def begin_window_resize(self, direction: str):
        """Let Windows own a border/corner drag initiated inside WebView2."""
        from core.snap_layouts import HTLEFT, HTRIGHT, HTTOP, HTBOTTOM, HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT
        edges = {'n': HTTOP, 's': HTBOTTOM, 'w': HTLEFT, 'e': HTRIGHT,
                 'nw': HTTOPLEFT, 'ne': HTTOPRIGHT, 'sw': HTBOTTOMLEFT, 'se': HTBOTTOMRIGHT}
        if not isinstance(direction, str) or direction not in edges:
            return {'success': False, 'error': 'Invalid resize direction'}
        if sys.platform != 'win32' or not self._window:
            return {'success': False, 'error': 'Native resizing is only available on Windows'}
        if getattr(self, '_is_maximized', False) or self._is_mini_active:
            return {'success': False, 'error': 'Restore the main window before resizing'}
        hwnd = self._get_hwnd()
        if not hwnd:
            return {'success': False, 'error': 'Window handle is unavailable'}
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            if user32.IsZoomed(hwnd):
                return {'success': False, 'error': 'Window is maximized'}
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                raise OSError('GetCursorPos failed')
            packed = ((point.y & 0xffff) << 16) | (point.x & 0xffff)
            snap = getattr(self, '_snap_layouts', None)
            if not snap or not getattr(snap, '_installed', False):
                return {'success': False, 'error': 'Window resizing is not ready'}
            get_style = getattr(user32, 'GetWindowLongW', None)
            if get_style is not None and not get_style(hwnd, -16) & 0x00040000:
                return {'success': False, 'error': 'Window resize style is missing'}
            send = self._native_message_function()
            def start_sizing():
                try:
                    # Capture belongs to the WinForms/WebView UI thread. Queue
                    # asynchronously so the JS bridge can return before sizing.
                    user32.ReleaseCapture()
                    send(hwnd, 0x00A1, edges[direction], ctypes.c_ssize_t(ctypes.c_int32(packed).value))
                except Exception:
                    logger.warning('Native sizing loop failed', exc_info=True)
            self._on_window_ui_thread(self._window, start_sizing)
            return {'success': True}
        except Exception as exc:
            logger.warning('Native window resize failed: %s', type(exc).__name__, exc_info=True)
            return {'success': False, 'error': describe_error(exc)['message']}

    def _get_hwnd(self):
        """Return only a native handle that belongs to this process."""
        window = getattr(self, '_window', None)
        if window is None:
            return None
        candidates = [getattr(window, 'hwnd', None)]
        for native in (getattr(window, 'native', None), getattr(window, 'gui_window', None)):
            if native is not None and getattr(native, 'IsHandleCreated', True):
                try:
                    handle = native.Handle
                    candidates.append(int(handle.ToInt64()) if hasattr(handle, 'ToInt64') else int(handle))
                except Exception:
                    logger.debug('Native window handle is not ready')
        if sys.platform != 'win32':
            return None
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        is_window = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(('IsWindow', user32))
        owner = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.HWND,
                                   ctypes.POINTER(wintypes.DWORD))(('GetWindowThreadProcessId', user32))
        for candidate in candidates:
            try:
                handle = int(candidate or 0)
                pid = wintypes.DWORD()
                if handle and is_window(handle) and owner(handle, ctypes.byref(pid)) and pid.value == os.getpid():
                    return handle
            except (TypeError, ValueError, OSError):
                continue
        return None

    def _change_maximized_state(self, maximized=None):
        target_win = self._window
        if not target_win:
            return

        def change():
            try:
                native = getattr(target_win, 'native', None)
                if sys.platform == 'win32' and native is not None:
                    from System.Drawing import Rectangle
                    from System.Windows.Forms import FormWindowState, Screen

                    # Use WinForms state/bounds once, on its owning UI thread.
                    # Mixing SetWindowPos with pywebview.resize from the bridge
                    # left the host form and the embedded browser out of sync.
                    is_max = native.WindowState == FormWindowState.Maximized
                    requested = not is_max if maximized is None else maximized
                    if requested:
                        if not is_max:
                            bounds = native.Bounds
                            self._last_geometry = (bounds.X, bounds.Y, bounds.Width, bounds.Height)
                        native.MaximizedBounds = Screen.FromHandle(native.Handle).WorkingArea
                        native.WindowState = FormWindowState.Maximized
                    else:
                        native.WindowState = FormWindowState.Normal
                        geometry = getattr(self, '_last_geometry', None)
                        if geometry:
                            native.Bounds = Rectangle(*map(int, geometry))
                    self._is_maximized = requested
                    self._fit_window_content(target_win)
                else:
                    requested = not getattr(self, '_is_maximized', False) if maximized is None else maximized
                    if requested:
                        target_win.maximize()
                    else:
                        target_win.restore()
                    self._is_maximized = requested
                logger.info('[WINDOW] %s using current monitor work area', 'Maximized' if self._is_maximized else 'Restored')
            except Exception:
                logger.warning('Could not change window state', exc_info=True)

        # Reply to the JS bridge before dispatching native window messages.
        self._deferred_window_op(.03, lambda: self._on_window_ui_thread(target_win, change))

    def restore(self):
        """Restore normal bounds without reloading or recreating the WebView."""
        self._change_maximized_state(False)

    def maximize(self):
        """Toggle native maximize within the monitor work area (taskbar visible)."""
        self._change_maximized_state()

    def toggle_fullscreen(self):
        """Legacy handler redirecting to maximize() to guarantee Windows taskbar visibility."""
        self.maximize()

    def open_url(self, url: str):
        """Open web URL in user's default browser."""
        if url and _is_ssrf_safe_url(url):
            webbrowser.open(url)

    def open_external_url(self, url: str):
        """Open external URL safely in default browser."""
        self.open_url(url)

    def emit_event(self, event_name: str, data: dict = None):
        if event_name == 'download_queue_updated' and (data or {}).get('status') in ('pending','paused'):
            with self._window_op_lock:
                if getattr(self, '_queue_events_suspended', 0):
                    return
        self._emit(event_name, data)

    def _emit(self, event_name: str, data=None):
        """One bounded FIFO owns evaluate_js; the UI thread never waits on it."""
        if event_name in ('download_complete', 'download_failed', 'library_updated'):
            self._storage_metrics_cache = None
            self._storage_info_cache = None
        if getattr(self, '_closed', False) or not getattr(self, '_window', None):
            return
        try:
            payload_json = json.dumps(data if data is not None else {}, allow_nan=False)
            code = f"if (window.onPythonEvent) {{ window.onPythonEvent({json.dumps(event_name)}, {payload_json}); }}"
        except Exception:
            logger.error('emit %s payload serialization failed', event_name)
            return
        with self._emitter_init_lock:
            if not getattr(self, '_emit_worker', None):
                if not hasattr(self, '_emit_queue'):
                    self._emit_queue = queue_module.Queue(maxsize=512)
                if not hasattr(self, '_ui_ready_event'):
                    self._ui_ready_event = threading.Event()
                    self._ui_ready_event.set()
                def deliver():
                    self._ui_ready_event.wait()
                    while not getattr(self, '_closed', False):
                        item = self._emit_queue.get()
                        if item is None:
                            break
                        js, completed = item
                        try:
                            window = getattr(self, '_window', None)
                            if window and not getattr(self, '_closed', False):
                                window.evaluate_js(js)
                        except Exception:
                            logger.warning('Frontend event delivery failed')
                        finally:
                            completed.set()
                self._emit_worker = threading.Thread(target=deliver, daemon=True, name='EmitWorker')
                self._emit_worker.start()
        completed = threading.Event()
        try:
            self._emit_queue.put_nowait((code, completed))
        except queue_module.Full:
            try:
                stale = self._emit_queue.get_nowait()
                if stale:
                    stale[1].set()
                self._emit_queue.put_nowait((code, completed))
            except (queue_module.Full, queue_module.Empty):
                logger.warning('Frontend event backlog is full')
                return
        engine = getattr(getattr(self, '_core', None), 'engine', None)
        locks = (getattr(engine, 'command_lock', None), getattr(self, '_window_op_lock', None))
        # Never wait for the renderer while holding a command/state lock. RLock
        # ownership is available on the supported CPython runtime; an unknown
        # lock implementation conservatively gets asynchronous delivery too.
        lock_held = any(lock is not None and
                        (not callable(getattr(lock, '_is_owned', None)) or lock._is_owned())
                        for lock in locks)
        # Bound the synchronous wait to at most 0.05s so heavy UI rendering does
        # not block backend threads for up to 2 seconds (BUG-WIN-049).
        if not lock_held and threading.current_thread() is not _MAIN_THREAD and self._ui_ready_event.is_set():
            completed.wait(0.05)

    def _enrich_track_lufs(self, track_dict: dict) -> dict:
        """Ensure loudness_lufs and lufs fields are populated from DB if available."""
        if not isinstance(track_dict, dict):
            return track_dict

        lufs = track_dict.get("loudness_lufs") if track_dict.get("loudness_lufs") is not None else track_dict.get("lufs")
        if lufs is not None:
            track_dict["loudness_lufs"] = lufs
            track_dict["lufs"] = lufs
            return track_dict

        try:
            db_track = None
            t_id = track_dict.get("id") or track_dict.get("track_id")
            if t_id:
                try:
                    db_track = self._core.db.get_track(int(t_id))
                except (ValueError, TypeError):
                    pass
            if not db_track and track_dict.get("file_path"):
                db_track = self._core.db.get_track_by_path(track_dict["file_path"])
            if not db_track and track_dict.get("source") and track_dict.get("source_id"):
                db_track = self._core.db.get_track_by_source_id(track_dict["source"], str(track_dict["source_id"]))

            if db_track:
                val = db_track.get("loudness_lufs") if db_track.get("loudness_lufs") is not None else db_track.get("lufs")
                if val is not None:
                    track_dict["loudness_lufs"] = val
                    track_dict["lufs"] = val
        except Exception:
            logger.debug("_enrich_track_lufs lookup failed", exc_info=True)

        return track_dict

    def _on_track_changed(self, track):
        if not isinstance(track, dict) or not track or getattr(self, '_closed', False):
            return
        with self._playback_guard():
            current = self._core.engine.queue.current_track
            if not current:
                return
            if self._listening_identity(track)[:2] != self._listening_identity(current)[:2]:
                return
            if track.get('entry_id') and current.get('entry_id') and track['entry_id'] != current['entry_id']:
                return
            track_copy = dict(track)
            epoch = self._playback_epoch
            track_copy['playback_epoch'] = epoch
            restoring = getattr(self, '_restoring_session', False)
            track_copy['autoplay'] = bool(getattr(self, '_restore_autoplay', False)) if restoring else True
            if restoring:
                track_copy['restore_position_sec'] = getattr(self, '_restore_position_sec', 0)
            fp = track_copy.get('file_path') or track_copy.get('url')
            usable = bool(fp and ((str(fp).startswith(('http://', 'https://')) and not stream_url_expired(fp))
                          or (not str(fp).startswith(('http://', 'https://')) and os.path.isfile(str(fp)))))
            if fp and not usable:
                track_copy.pop('file_path', None)
                track_copy.pop('stream_url', None)
                current.pop('file_path', None)
                current.pop('stream_url', None)
            track_copy['resolution_status'] = 'ready' if usable or track_copy.get('stream_url') else 'resolving'
            if track_copy.get('id'):
                stored = self._core.db.get_track(track_copy['id'])
                if stored:
                    track_copy['is_favorite'] = bool(stored.get('is_favorite', False))
                    # Older compact session entries can contain duration=0 even
                    # though the library already knows the recording's length.
                    # Restore the seek timeline without another provider request.
                    duration = _as_float(stored.get('duration')) or 0
                    if (_as_float(track_copy.get('duration')) or 0) <= 0 and duration > 0:
                        track_copy['duration'] = current['duration'] = duration
            self._listening_for_track(track_copy)
            self._enrich_track_lufs(track_copy)
            current['listening_session'] = track_copy['listening_session']
            current['playback_epoch'] = epoch
            current['resolution_status'] = track_copy['resolution_status']
            self._current_track = track_copy
            previous_rpc_track = getattr(self, '_discord_facts', {}).get('track', {})
            def rpc_identity(item):
                return (item.get('entry_id'), item.get('source'), item.get('source_id'), item.get('id'))
            if rpc_identity(previous_rpc_track) != rpc_identity(track_copy):
                self._discord_sync('paused' if restoring and not track_copy['autoplay'] else 'loading', position_sec=0, track=track_copy)
            else:
                self._discord_sync(track=track_copy)
            self._emit('track_changed', track_copy)
            tray = getattr(self, '_tray', None)
            if tray:
                tray.update_state(track=track_copy, force=True)
            if track_copy['resolution_status'] == 'resolving' and track_copy['autoplay'] and current.get('_resolution_epoch') != epoch:
                current['_resolution_epoch'] = epoch
                self._resolve_track(current, lambda resolved: None)

    def _on_queue_end(self):
        with self._playback_guard():
            self._playback_epoch += 1
            self._discord_sync('stopped')
            self._emit('queue_ended', {'reason': 'queue_exhausted', 'playback_epoch': self._playback_epoch})

    def _on_audio_error(self, err):
        self._discord_sync('error')
        details = describe_error(err, 'playback')
        details['playback_epoch'] = self._playback_epoch
        self._emit('audio_error', dict(details, user_message=details['message']))
        self._emit('error', details['message'])

    @staticmethod
    def _listening_identity(track):
        return (str(track.get('source') or ''), str(track.get('source_id') or track.get('id') or ''),
                str(track.get('artist') or ''), str(track.get('title') or ''))

    def _listening_for_track(self, track, force=False):
        from core.listening import ListeningSession
        with self._window_op_lock:
            sessions = self._listening_sessions
            current = sessions.get(self._active_listening_token)
            incoming = sessions.get(track.get('listening_session'))
            if not force and incoming and not incoming.closed and self._listening_identity(incoming.track) == self._listening_identity(track):
                session = incoming
            elif not force and current and not current.closed and self._listening_identity(current.track) == self._listening_identity(track):
                session = current
            else:
                if current:
                    current.state(False)
                    current.closed = True
                    self._persist_listening(current)
                session = ListeningSession(dict(track))
                sessions[session.token] = session
                while len(sessions) > 32:
                    sessions.pop(next(iter(sessions)))
            self._active_listening_token = session.token
            track['listening_session'] = session.token
            return session

    def _persist_listening(self, session):
        measured = (session.seconds, session.completed, session.media_seconds, session.closed)
        if session.history_id is not None and measured != session.last_saved:
            self._core.db.update_history_duration(session.history_id, session.seconds, session.completed,
                                                 media_listened=session.media_seconds, session_finished=session.closed)
            session.last_saved = measured

    def flush_listening(self):
        with self._window_op_lock:
            for session in getattr(self, '_listening_sessions', {}).values():
                session.state(False)
                session.closed = True
                self._persist_listening(session)

    def maybe_log_history(self):
        """One zero-duration measured history row per actual audible playback."""
        try:
            track = getattr(self, '_current_track', None)
            if not isinstance(track, dict):
                return
            with self._window_op_lock:
                session = self._listening_for_track(track)
                if session.history_id is not None:
                    return
                t_id = track.get('id')
                try:
                    t_id = int(t_id)
                except (TypeError, ValueError):
                    t_id = self._core.db.ensure_track_exists(track)
                if not t_id:
                    return
                track['id'] = t_id
                session.track['id'] = t_id
                begin = getattr(self._core.db, 'begin_listening_session', None)
                if callable(begin):
                    session.history_id = begin(int(t_id), track.get('recommendation_origin', ''))
                else:
                    session.history_id = self._core.db.add_to_history(int(t_id))
                self._history_logged_key = track.get('source_id') or t_id
            self._emit('history_updated', {'track_id': t_id, 'history_id': session.history_id})
        except Exception:
            logger.debug('Measured history start failed', exc_info=True)

    def report_listening_state(self, listening_session, audible=False, ended=False, duration_sec=0, playback_rate=1):
        """Renderer reports actual audio, buffering and seeking independently of UI state."""
        with self._window_op_lock:
            session = self._listening_sessions.get(listening_session)
            if session is None or (session.closed and not ended):
                return False
            if audible and listening_session != self._active_listening_token:
                return False
            if audible and session.history_id is None:
                self.maybe_log_history()
            try:
                if 0 < float(duration_sec) <= 86400:
                    session.track['duration'] = float(duration_sec)
            except (TypeError, ValueError):
                pass
            # Finish the elapsed interval at its previous speed. The renderer
            # reports ratechange immediately; the new rate applies from this
            # boundary onward, not retroactively to the preceding interval.
            session.tick()
            try:
                rate = float(playback_rate)
                if math.isfinite(rate):
                    session.playback_rate = min(4, max(.25, rate))
            except (TypeError, ValueError):
                pass
            session.state(audible, ended=ended)
            self._persist_listening(session)
            if listening_session == self._active_listening_token:
                self._discord_sync('stopped' if ended else ('playing' if audible else ('paused' if getattr(self, '_last_reported_state', '') == 'paused' else 'loading')),
                                   duration_sec=duration_sec, playback_rate=playback_rate)
        return True

    def _discord_snapshot(self):
        """Actual renderer-selected deck facts; outgoing crossfade reports cannot replace them."""
        with self._window_op_lock:
            return dict(getattr(self, '_discord_facts', {}))

    def _discord_sync(self, state=None, *, position_sec=None, duration_sec=None, playback_rate=None, track=None):
        service = getattr(self._core, 'discord_rpc', None)
        now = time.monotonic()
        with self._window_op_lock:
            previous = getattr(self, '_discord_facts', {})
            position = previous.get('position_sec', 0)
            if previous.get('state') == 'playing':
                position += max(0, now - previous.get('updated_at', now)) * previous.get('playback_rate', 1)
            selected = dict(track if track is not None else (getattr(self, '_current_track', None) or previous.get('track', {})))
            facts = {'track': selected, 'state': state or previous.get('state', 'stopped'),
                     'position_sec': position if position_sec is None else max(0, float(position_sec or 0)),
                     'duration_sec': duration_sec if duration_sec is not None and duration_sec > 0 else selected.get('duration', previous.get('duration_sec', 0)),
                     'playback_rate': playback_rate if playback_rate is not None else previous.get('playback_rate', 1),
                     'updated_at': now}
            self._discord_facts = facts
        if not service:
            return
        if hasattr(service, 'update_snapshot'):
            service.set_snapshot_provider(self._discord_snapshot)
            service.update_snapshot(**facts)
        elif facts['state'] in ('playing', 'paused'):
            service.update_presence(track_title=selected.get('title', ''), track_artist=selected.get('artist', ''),
                                    is_playing=facts['state'] == 'playing', duration_sec=facts['duration_sec'], current_pos_sec=facts['position_sec'])
        elif hasattr(service, 'clear_presence'):
            service.clear_presence()

    def report_state(self, state: str, elapsed_ms: int = 0, listening_session=None):
        """Report playback state update (playing, paused, stopped)."""
        # Remembered so play_pause() can answer with the real last state instead
        # of pretending it performed a pause/resume it cannot do.
        if listening_session and listening_session != self._active_listening_token:
            return False
        self._last_reported_state = state
        if state == 'playing':
            self.maybe_log_history()
        with self._window_op_lock:
            session = self._listening_sessions.get(self._active_listening_token)
            if session:
                session.state(state == 'playing', ended=state == 'ended')
                if state == 'stopped':
                    session.closed = True
                self._persist_listening(session)
            if state == 'stopped':
                self._history_logged_key = None
        self._emit("state_changed", {"state": state, "elapsed_ms": elapsed_ms})
        if getattr(self, "_tray", None):
            self._tray.update_state(is_playing=(state == "playing"))
        try:
            self._discord_sync(state, position_sec=elapsed_ms / 1000.0 if elapsed_ms else 0)
        except Exception:
            logger.debug("report_state: suppressed exception", exc_info=True)

    def get_proxy_info(self):
        """Return proxy port and auth token for local asset requests."""
        if hasattr(self._core, 'proxy') and self._core.proxy:
            return {
                "port": getattr(self._core.proxy, "port", 0),
                "token": getattr(self._core.proxy, "token", "")
            }
        return {"port": 0, "token": ""}

    def report_position(self, pos_ms: int, dur_ms: int = 0, duration_ms: int = 0, listening_session=None):
        """Report position update."""
        if listening_session and listening_session != self._active_listening_token:
            return False
        with self._window_op_lock:
            session = self._listening_sessions.get(self._active_listening_token)
            if session:
                session.tick()
                if (dur_ms or duration_ms) > 0:
                    session.track['duration'] = (dur_ms or duration_ms) / 1000
                self._persist_listening(session)
        duration = dur_ms or duration_ms
        pos_sec = pos_ms / 1000.0 if pos_ms else 0.0
        dur_sec = duration / 1000.0 if duration else 0.0
        if hasattr(self._core, "engine") and self._core.engine:
            self._core.engine._last_reported_position = pos_sec
        self._discord_sync(position_sec=pos_sec, duration_sec=dur_sec)
        return True

    def _notify_queue_updated(self):
        """Emit queue_updated so the drawer never goes stale after a queue swap."""
        try:
            self._emit("queue_updated", self.get_queue())
        except Exception:
            logger.debug("_notify_queue_updated failed", exc_info=True)

    def play_track(self, track: dict, track_list: list = None, index: int = 0):
        import uuid
        if not isinstance(track, dict) or not track:
            return {'success': False, 'error': 'Трек не указан'}
        def identity(item):
            return (str(item.get('source') or 'local'), str(item.get('source_id') or item.get('track_id') or item.get('id') or ''))
        with self._playback_guard():
            queue = self._core.engine.queue
            live = queue.tracks
            if track_list is None or track.get('entry_id'):
                found = next((i for i, item in enumerate(live) if
                    (item.get('entry_id') == track['entry_id'] if track.get('entry_id') else identity(item) == identity(track))), None)
                if track.get('entry_id') and found is None:
                    return {'success': False, 'code': 'stale_queue'}
                if found is not None:
                    tracks, index = live, found
                else:
                    tracks, index = [dict(track)], 0
            elif not isinstance(track_list, list) or not track_list or any(not isinstance(t, dict) for t in track_list):
                return {'success': False, 'error': 'Некорректная очередь'}
            else:
                tracks = [dict(item) for item in track_list]
                index = next((i for i, item in enumerate(tracks) if identity(item) == identity(track)),
                             max(0, min(int(index or 0), len(tracks) - 1)))
            selected = tracks[index]
            if selected.get('source', 'local') == 'local':
                local_path = selected.get('file_path')
                from core.offline import _local_file
                valid_path = _local_file(local_path)
                if not valid_path:
                    tid = selected.get('id') or selected.get('track_id')
                    if tid and hasattr(self._core.db, 'invalidate_offline_track'):
                        self._core.db.invalidate_offline_track(tid)
                    self._on_audio_error('Аудиофайл не найден')
                    return {'success': False, 'code': 'file_missing'}
                selected['file_path'] = valid_path
            self._restoring_session = False
            self._playback_epoch += 1
            self._cancel_stale_resolutions()
            epoch = self._playback_epoch
            seen_entries = set()
            for item in tracks:
                if item.get('track_id'):
                    item['id'] = item['track_id']
                if not item.get('entry_id') or item['entry_id'] in seen_entries:
                    item['entry_id'] = uuid.uuid4().hex
                seen_entries.add(item['entry_id'])
            selected['playback_epoch'] = epoch
            selected.pop('_resolution_epoch', None)
            self._queue_revision += 1
            self._core.engine.play_queue(tracks, index)
            self._notify_queue_updated()
            return {'success': True, 'playback_epoch': epoch,
                    'resolution_status': getattr(self, '_current_track', {}).get('resolution_status', 'resolving')}

    def _cancel_stale_resolutions(self):
        """Cancel queued-but-unstarted resolution futures from a superseded epoch."""
        with self._resolution_futures_lock:
            pending = [f for f in self._resolution_futures if not f.done()]
        cancelled = []
        for future in pending:
            try:
                if future.cancel():
                    cancelled.append(future)
            except Exception:
                pass
        with self._resolution_futures_lock:
            self._resolution_futures.difference_update(cancelled)

    def _resolve_track(self, track: dict, play_callback):
        """All foreground resolutions use the resolver and one playback intent token."""
        epoch = self._playback_epoch
        def active():
            return (not getattr(self, '_closed', False) and self._playback_epoch == epoch
                    and self._core.engine.queue.current_track is track)
        def resolve():
            # BUG-A1-009: with 2 workers a queued task could start long after a
            # newer play_track superseded it; drop it before any network work.
            if not active():
                return
            error = None
            url = None
            try:
                if track.get('source', 'local') == 'local':
                    candidate = track.get('file_path')
                    if not candidate or not os.path.isfile(str(candidate)):
                        row = self._core.db.get_track(int(track.get('id') or 0)) if track.get('id') else None
                        candidate = (row or {}).get('file_path')
                    if not candidate or not os.path.isfile(str(candidate)):
                        cache_dir = getattr(getattr(self._core, 'cache', None), '_streams_dir', None)
                        source_id = str(track.get('source_id') or '')
                        if cache_dir and source_id:
                            # Hashed cache naming (BUG-A1-006): the stem is a
                            # digest of (source, source_id), unique per track.
                            stem = stream_cache_stem(track.get('source') or 'local', source_id)
                            candidate = next((os.path.join(cache_dir, f'{stem}{ext}')
                                for ext in ('.m4a', '.mp3', '.ogg', '.wav', '.flac')
                                if os.path.isfile(os.path.join(cache_dir, f'{stem}{ext}'))), None)
                    from core.offline import _local_file
                    if candidate and _local_file(candidate):
                        url = candidate
                    else:
                        tid = track.get('id') or track.get('track_id')
                        if tid and hasattr(self._core.db, 'invalidate_offline_track'):
                            self._core.db.invalidate_offline_track(tid)
                        error = 'Аудиофайл не найден'
                else:
                    cancel_token = lambda: not active()
                    try:
                        url = self._core.engine.resolve_stream_url(dict(track), cancel_token=cancel_token)
                    except TypeError:
                        url = self._core.engine.resolve_stream_url(dict(track))
                    if not url:
                        error = 'Не удалось найти аудиопоток'
            except Exception as exc:
                error = describe_error(exc, 'playback')['message']
            with self._playback_guard():
                if not active():
                    return
                if not url:
                    track['resolution_status'] = 'failed'
                    self._on_audio_error(error or 'Не удалось найти аудиопоток')
                    return
                track['file_path'] = url
                track.pop('stream_url', None)
                track['resolution_status'] = 'ready'
                if callable(play_callback):
                    play_callback(dict(track))
                self._core.engine._notify_track_changed()
        executor = getattr(self, '_playback_executor', None)
        if executor:
            def _resolution_done(future):
                with self._resolution_futures_lock:
                    self._resolution_futures.discard(future)
            try:
                future = executor.submit(resolve)
            except RuntimeError:
                return threading.Thread(target=resolve, name='PlaybackResolve', daemon=True).start()
            with self._resolution_futures_lock:
                self._resolution_futures.add(future)
            future.add_done_callback(_resolution_done)
            return future
        return threading.Thread(target=resolve, name='PlaybackResolve', daemon=True).start()

    def play_pause(self) -> str:
        """Report the last playback state the frontend observed.

        The audio element lives in the frontend, so the backend cannot pause or
        resume it - and it must not guess: it receives no argument telling it
        whether the user asked to play or to pause, so any state change here
        would desync the UI. The frontend drives <audio> itself (its own
        togglePlayPause) and reports the result through report_state(). This
        method is still called from the library "play all" buttons and the
        mediaSession handlers, so it answers with the truth instead of None:
        "playing", "paused", "stopped", or "" when nothing was reported yet.
        """
        state = getattr(self, "_last_reported_state", "") or ""
        return state

    def next_track(self, force_advance: bool = True):
        with self._playback_guard():
            self._restoring_session = False
            self._playback_epoch += 1
            self._cancel_stale_resolutions()
            self._queue_revision += 1
            result = self._core.engine.next_track(force_advance=force_advance)
            self._notify_queue_updated()
            return dict(result) if result else None

    def prev_track(self):
        with self._playback_guard():
            self._restoring_session = False
            self._playback_epoch += 1
            self._cancel_stale_resolutions()
            self._queue_revision += 1
            result = self._core.engine.prev_track()
            self._notify_queue_updated()
            return dict(result) if result else None

    def get_queue(self):
        import uuid
        with self._playback_guard():
            queue = self._core.engine.queue
            for track in queue.tracks:
                track.setdefault('entry_id', uuid.uuid4().hex)
            if hasattr(queue, 'snapshot'):
                state = queue.snapshot()
            else:
                state = {'tracks': [dict(t) for t in queue.tracks], 'current_index': queue._current_index,
                    'current_track': dict(queue.current_track) if queue.current_track else None,
                    'shuffle': queue.shuffle, 'repeat': queue.repeat}
            return dict(state, queue_revision=self._queue_revision)

    def reorder_queue(self, old_index: int, new_index: int, expected_key=None, revision=None):
        with self._playback_guard():
            queue = self._core.engine.queue
            if revision is not None and int(revision) != self._queue_revision:
                return {'success': False, 'code': 'stale_queue'}
            old_index, new_index = int(old_index), int(new_index)
            if not 0 <= old_index < len(queue.tracks) or not 0 <= new_index < len(queue.tracks):
                return {'success': False, 'code': 'stale_queue'}
            if expected_key and queue.tracks[old_index].get('entry_id') != expected_key:
                return {'success': False, 'code': 'stale_queue'}
            queue.move_track(old_index, new_index)
            self._queue_revision += 1
            self._notify_queue_updated()
            return {'success': True}

    def play_next(self, track):
        import uuid
        if not isinstance(track, dict) or not track:
            return {'success': False}
        with self._playback_guard():
            self._core.engine.add_to_queue(dict(track, entry_id=uuid.uuid4().hex), play_next=True)
            self._queue_revision += 1
            self._notify_queue_updated()
        return {'success': True}

    def add_to_queue(self, track):
        import uuid
        if not isinstance(track, dict) or not track:
            return {'success': False}
        with self._playback_guard():
            self._core.engine.add_to_queue(dict(track, entry_id=uuid.uuid4().hex), play_next=False)
            self._queue_revision += 1
            self._notify_queue_updated()
        return {'success': True}

    def add_tracks_to_queue(self, tracks):
        import uuid
        if not isinstance(tracks, list) or not tracks or len(tracks) > 1000 or any(not isinstance(track,dict) for track in tracks):
            return {'success': False}
        with self._playback_guard():
            self._core.engine.add_tracks_to_queue([dict(track,entry_id=uuid.uuid4().hex) for track in tracks])
            self._queue_revision += 1
            self._notify_queue_updated()
        return {'success': True, 'count': len(tracks)}

    def remove_from_queue(self, index, expected_key=None, revision=None):
        with self._playback_guard():
            if revision is not None and int(revision) != self._queue_revision:
                return {'success': False, 'code': 'stale_queue'}
            queue = self._core.engine.queue
            index = int(index)
            if not 0 <= index < len(queue.tracks) or (expected_key and queue.tracks[index].get('entry_id') != expected_key):
                return {'success': False, 'code': 'stale_queue'}
            if index == queue._current_index:
                return {'success': False, 'error': 'Нельзя удалить текущий трек'}
            queue.remove_track(index)
            self._queue_revision += 1
            self._notify_queue_updated()
            return {'success': True}

    def clear_queue(self):
        with self._playback_guard():
            queue = self._core.engine.queue
            current = queue.current_track
            queue.set_tracks([current] if current else [], 0 if current else -1)
            self._queue_revision += 1
            self._notify_queue_updated()
        return {'success': True}

    def get_setting(self, key: str, default=None):
        """Get a setting by dotted key 'category.key'."""
        try:
            if "." in key:
                cat, k = key.split(".", 1)
                val = self._core.settings.get(cat, k, default)
                # Secrets leave the backend only as a has_* flag, never as a value.
                if k in _SECRET_SETTING_KEYS.get(cat, ()):
                    return "" if val else default
                return val
            # Bare keys are ambiguous (they used to silently hit the 'zapret'
            # category); refuse them instead of returning a surprise value.
            logger.warning("get_setting: bare key %r rejected, pass 'category.key'", key)
            return default
        except Exception as e:
            logger.error(f"get_setting error: {type(e).__name__}")
            return default

    def set_setting(self, section: str, key=None, value=_UNSET):
        if value is _UNSET:
            if '.' not in str(section):
                return {'success': False, 'error': 'Укажите category.key'}
            category, name = str(section).split('.', 1)
            value = key
        else:
            category, name = str(section), key
        success = self.save_setting(name, value, category)
        return success if isinstance(success, dict) else {'success': bool(success)}

    def yandex_device_auth(self):
        """Start Yandex Music device-code authorization (O-1)."""
        try:
            svc = getattr(self._core, "yandex", None)
            if not svc:
                return {"success": False, "message": "Yandex Music сервис недоступен"}

            def _on_code(code):
                user_code = getattr(code, "user_code", "") or ""
                ver_url = getattr(code, "verification_url", "") or "https://passport.yandex.ru/device"
                self._emit("yandex_device_auth_code", {
                    "user_code": user_code,
                    "verification_url": ver_url
                })

            def _worker():
                try:
                    from yandex_music import Client
                    if not hasattr(Client, "device_auth"):
                        self._emit("yandex_device_auth_result", {
                            "success": False,
                            "message": "Установленная библиотека yandex-music не поддерживает device-авторизацию. Введите токен вручную в поле ниже."
                        })
                        return
                    client = svc._get_client()
                    if client is None:
                        client = Client()
                    token = client.device_auth(on_code=_on_code, timeout=300)
                    if token and getattr(token, "access_token", ""):
                        from core.oauth import store_yandex_token
                        store_yandex_token(self._core.settings, token)
                        svc.reset_client()
                        self._emit("yandex_device_auth_result", {
                            "success": True,
                            "message": "Авторизация Яндекс Музыки выполнена успешно"
                        })
                    else:
                        self._emit("yandex_device_auth_result", {
                            "success": False,
                            "message": "Не удалось получить токен Яндекс Музыки"
                        })
                except Exception as e:
                    logger.error("Yandex device auth failed: %s", type(e).__name__)
                    self._emit("yandex_device_auth_result", {
                        "success": False,
                        "message": f"Ошибка авторизации Яндекс Музыки: {type(e).__name__}"
                    })

            threading.Thread(target=_worker, daemon=True).start()
            return {"success": True, "message": "Запрос авторизации запущен"}
        except Exception as e:
            logger.error("yandex_device_auth error: %s", type(e).__name__)
            return {"success": False, "message": describe_error(e)['message']}

    def set_volume(self, volume: int):
        """Set playback volume (0-100)."""
        if isinstance(volume, bool) or _as_float(volume) is None or not 0 <= float(volume) <= 100:
            return False
        self._core.settings.set("audio", "volume", round(float(volume)))
        return True

    def get_volume(self):
        """Return current volume level."""
        return self._core.settings.get("audio", "volume", 70)

    def toggle_mute(self):
        """Toggle the persisted mute state and return the NEW state.

        The HTML5 element on the frontend does the actual attenuation; the
        backend owns the flag so the value is consistent and truthful instead of
        the old hardcoded ``return False`` (which read as "sound is on" no matter
        what the user had muted). DEFAULT_SETTINGS already ships ``audio.muted``
        and nothing used to read or write it.

        Returns True when audio is muted from now on, False when unmuted.
        """
        settings = getattr(self._core, "settings", None)
        if settings is None:
            # Without a settings store there is nothing truthful to report.
            return False
        try:
            current = bool(settings.get("audio", "muted", False))
        except Exception:
            logger.debug("toggle_mute: could not read audio.muted", exc_info=True)
            current = False
        new_state = not current
        try:
            settings.set("audio", "muted", new_state)
        except Exception as e:
            logger.error(f"toggle_mute: could not persist audio.muted: {type(e).__name__}")
            return current
        self._emit("mute_changed", {"muted": new_state})
        return new_state

    def is_muted(self) -> bool:
        """Return the persisted mute state without changing it."""
        settings = getattr(self._core, "settings", None)
        if settings is None:
            return False
        try:
            return bool(settings.get("audio", "muted", False))
        except Exception:
            logger.debug("is_muted: suppressed exception", exc_info=True)
            return False

    def toggle_shuffle(self):
        """Toggle queue shuffle mode."""
        enabled = self._core.engine.toggle_shuffle()
        self._emit("shuffle_changed", {"state": enabled})
        return enabled

    def toggle_repeat(self):
        """Cycle repeat mode (off -> all -> one -> off)."""
        mode = self._core.engine.toggle_repeat()
        self._emit("repeat_changed", {"state": mode})
        return mode

    def get_next_track(self, *args, **kwargs):
        """Return metadata and stream URL for the upcoming track in the queue without advancing index."""
        try:
            queue = self._core.engine.queue
            # BUG-A1-017: read the list, the index and the repeat mode from one
            # consistent snapshot; two separate locked reads let a queue edit
            # between them point the prefetch at a track that is no longer next.
            if hasattr(queue, 'snapshot'):
                snapshot = queue.snapshot()
            else:
                snapshot = {'tracks': [dict(t) for t in queue.tracks],
                            'current_index': queue.current_index, 'repeat': queue.repeat}
            tracks = snapshot.get('tracks') or []
            if not tracks:
                return None
            current_idx = snapshot.get('current_index')
            if snapshot.get('repeat') == 'one' and current_idx is not None and current_idx >= 0:
                return dict(tracks[current_idx])
            # current_index is -1 for an empty queue and can only be meaningful
            # once something is actually current; there is no "next" to preview.
            if current_idx < 0:
                return None
            # PlaybackQueue.next_track() returns None at the end of the queue
            # unless repeat == "all", in which case it wraps to index 0. The old
            # unconditional (current_idx + 1) % len(tracks) wrapped anyway, so a
            # preloading frontend cached the FIRST track in vain on the last
            # track (and always with a single-track queue).
            at_end = current_idx >= len(tracks) - 1
            if at_end and queue.repeat != "all":
                return None
            next_idx = 0 if at_end else current_idx + 1
            if 0 <= next_idx < len(tracks):
                raw_track = tracks[next_idx]
                if not raw_track or not isinstance(raw_track, dict):
                    return None
                
                track = {
                    "id": raw_track.get("id"),
                    "title": str(raw_track.get("title") or "Unknown Title"),
                    "artist": str(raw_track.get("artist") or "Unknown Artist"),
                    "album": str(raw_track.get("album") or "Unknown Album"),
                    "duration": float(raw_track.get("duration") or 0),
                    "cover_url": str(raw_track.get("cover_url") or raw_track.get("cover_path") or ""),
                    "source": str(raw_track.get("source") or "local"),
                    "source_id": str(raw_track.get("source_id") or ""),
                    "stream_url": str(raw_track.get("stream_url") or "")
                }
                
                if not track["stream_url"]:
                    if track["source"] == "local":
                        track["stream_url"] = str(raw_track.get("url") or raw_track.get("file_path") or "")
                    elif raw_track.get("file_path") and os.path.exists(str(raw_track["file_path"])):
                        track["stream_url"] = str(raw_track["file_path"])
                    elif self._core.engine.proxy and getattr(self._core.engine.proxy, "port", None):
                        import urllib.parse as urllib_parse
                        t_id = track.get("id") or 0
                        src = track.get("source") or "youtube"
                        src_id = urllib_parse.quote(str(track.get("source_id") or ""))
                        title = urllib_parse.quote(str(track.get("title") or ""))
                        artist = urllib_parse.quote(str(track.get("artist") or ""))
                        auth = self._core.engine.proxy.auth_query() if hasattr(self._core.engine.proxy, "auth_query") else ""
                        track["stream_url"] = (f"http://127.0.0.1:{self._core.engine.proxy.port}/api/stream"
                                               f"?track_id={t_id}&source={src}&source_id={src_id}"
                                               f"&title={title}&artist={artist}{auth}")
                return track
        except Exception as e:
            logger.error(f"get_next_track error: {type(e).__name__}")
        return None

    def search(self, query: str, source: str = "all", result_type: str = None, request_id=None):
        """Search without blocking the UI bridge.

        Providers run in parallel, each bounded by PROVIDER_SEARCH_TIMEOUT seconds.
        Results arrive via the search_results / search_completed events.
        """
        query = str(query or '').strip()[:500]
        self.cancel_search()
        with self._search_lock:
            generation = self._search_generation
        # DEBUG, not INFO: search fires once per keystroke batch on the bridge
        # hot path and this line dominated app.log during normal use.
        logger.debug('Search requested from provider %s', source if source in ('all','local','youtube','soundcloud','spotify','deezer','yandex') else 'unsupported')
        if not query:
            self._emit('search_completed', {'query': '', 'source': source, 'type': result_type, 'request_id': request_id})
            return {'query': '', 'tracks': []}

        def is_current():
            with self._search_lock:
                return generation == self._search_generation

        DISABLED_UI_PROVIDERS = {"vk", "vkontakte", "zeno"}
        if source == "all":
            if result_type in ("artists", "artist"):
                requested_providers = ["local", "youtube", "deezer"]
            else:
                requested_providers = ["local", "youtube", "soundcloud", "spotify", "deezer", "yandex"]
        elif source == "local":
            requested_providers = ["local"]
        elif source in DISABLED_UI_PROVIDERS:
            requested_providers = []
        else:
            requested_providers = [source]

        # Track-only providers must not masquerade their songs as artist entities.
        if result_type in ('artists', 'artist'):
            requested_providers = [p for p in requested_providers if p in ('local', 'youtube', 'deezer')]

        requested_providers = [provider for provider in requested_providers
            if provider not in ('youtube', 'soundcloud')
            or self._core.settings.get('services', provider + '_enabled', True)]

        def emit_results(tracks, service_name):
            if not is_current():
                return
            with pending_lock:
                observed_tracks.extend(t for t in (tracks or []) if isinstance(t, dict))
            self._emit("search_results", {
                "query": query,
                "source": service_name,
                "type": result_type,
                "request_id": request_id,
                "tracks": tracks or [],
            })

        pending_lock = threading.Lock()
        pending_providers = set(requested_providers)
        completion_emitted = [False]
        observed_tracks = []
        lyrics_started = [False]

        def lyric_fallback():
            try:
                if is_current():
                    from services.lyrics_search import find_lyric_tracks
                    tracks = find_lyric_tracks(query, self._core.lyrics, self._core.youtube, is_current, self._core.deezer)
                    for provider in ('youtube', 'deezer'):
                        batch = [track for track in tracks if track.get('source') == provider]
                        if batch:
                            emit_results(batch, provider)
            except Exception as exc:
                logger.debug('Lyric search unavailable: %s', type(exc).__name__)
            finally:
                mark_done('__lyrics__')

        def mark_done(provider_name):
            start_lyrics = False
            with pending_lock:
                pending_providers.discard(provider_name)
                if not pending_providers and not completion_emitted[0]:
                    from services.lyrics_search import should_search_lyrics
                    if (not lyrics_started[0] and source == 'all' and result_type in (None, 'all', 'tracks', 'track')
                            and 'youtube' in requested_providers and is_current()
                            and should_search_lyrics(query, observed_tracks)):
                        lyrics_started[0] = True
                        pending_providers.add('__lyrics__')
                        start_lyrics = True
                    else:
                        completion_emitted[0] = True
                        if is_current():
                            self._emit("search_completed", {"query": query, "source": source, "type": result_type, "request_id": request_id})
            if start_lyrics:
                submit(lyric_fallback)

        if not requested_providers:
            # All providers filtered out (e.g. DISABLED_UI_PROVIDERS): do not hang,
            # emit completion immediately so the UI stops its spinner.
            self._emit("search_completed", {"query": query, "source": source, "type": result_type, "request_id": request_id})
            return {"query": query, "tracks": []}

        def submit(fn, *values):
            future = self._search_executor.submit(fn, *values)
            if future is not None:
                with self._search_lock:
                    self._search_futures.add(future)
                def finished(done):
                    with self._search_lock:
                        self._search_futures.discard(done)
                future.add_done_callback(finished)
            return future

        # Local DB Search
        if "local" in requested_providers:
            def _run_local():
                try:
                    if not is_current():
                        return
                    if result_type in ("albums", "album"):
                        local_results = self._core.db.search_albums(query)
                    elif result_type in ("playlists", "playlist"):
                        local_results = self._core.db.search_playlists(query) if hasattr(self._core.db, "search_playlists") else []
                    elif result_type in ("artists", "artist"):
                        local_results = self._core.db.search_artists(query) if hasattr(self._core.db, "search_artists") else []
                    else:
                        local_results = self._core.db.search_tracks(query)
                    if not local_results:
                        from utils.search_query import convert_layout
                        alt_query = convert_layout(query)
                        if alt_query:
                            if result_type in ("albums", "album"):
                                local_results = self._core.db.search_albums(alt_query)
                            elif result_type in ("playlists", "playlist"):
                                local_results = self._core.db.search_playlists(alt_query) if hasattr(self._core.db, "search_playlists") else []
                            elif result_type in ("artists", "artist"):
                                local_results = self._core.db.search_artists(alt_query) if hasattr(self._core.db, "search_artists") else []
                            else:
                                local_results = self._core.db.search_tracks(alt_query)
                    if result_type in ('artists', 'artist'):
                        local_results = [dict(item, type='artist', source='local',
                                              name=item.get('artist') or item.get('name') or '',
                                              title=item.get('artist') or item.get('name') or '')
                                         for item in local_results]
                    emit_results(local_results, "local")
                except Exception as exc:
                    logger.error("Local search failed: %s", type(exc).__name__)
                    emit_results([], "local")
                finally:
                    mark_done("local")

            if source == "local":
                _run_local()
            else:
                submit(_run_local)

        # Async Remote Provider Searches — hard timeout per provider
        for service_name in requested_providers:
            if service_name == "local":
                continue

            def _run_provider(name):
                if not is_current():
                    mark_done(name)
                    return
                is_done = [False]
                retried_alt = [False]
                options_holder = [{}]
                # Cached provider results can invoke the layout-retry callback
                # synchronously, re-entering _finish on this same thread.
                lock = threading.RLock()

                def _finish(tracks):
                    with lock:
                        if is_done[0]:
                            return
                        if not tracks and not retried_alt[0]:
                            from utils.search_query import convert_layout
                            alt_query = convert_layout(query)
                            if alt_query:
                                retried_alt[0] = True
                                try:
                                    srv = getattr(self._core, name, None)
                                    if srv and is_current():
                                        srv.search(alt_query, **options_holder[0])
                                        return
                                except Exception:
                                    logger.debug("%s layout fallback search failed", name, exc_info=True)
                        is_done[0] = True
                    # Release the deadline timer immediately; leaving it armed kept a
                    # live thread per keystroke and delayed process exit.
                    try:
                        timer.cancel()
                        with self._search_lock:
                            self._search_timers.discard(timer)
                    except Exception:
                        logger.debug("search timer cancel failed", exc_info=True)
                    emit_results(tracks or [], name)
                    mark_done(name)

                def _on_success(tracks):
                    _finish(tracks)

                def _on_error(err):
                    logger.info("%s search failed [%s]", name, describe_error(err)["code"])
                    _finish([])

                # SoundCloud's first query includes discovery of its public key.
                _timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT

                def _on_timeout():
                    with lock:
                        if is_done[0]:
                            return
                    logger.warning("%s search timed out after %.1fs", name, _timeout)
                    _finish([])

                timer = threading.Timer(_timeout, _on_timeout)
                timer.daemon = True
                with self._search_lock:
                    if generation != self._search_generation:
                        return
                    self._search_timers.add(timer)
                timer.start()

                try:
                    # Lazy providers are constructed only when selected, off
                    # the bridge thread; local-only search stays entirely offline.
                    srv = getattr(self._core, name, None)
                    if not srv or not is_current():
                        _finish([])
                        return
                    options = {'callback': _on_success, 'error_callback': _on_error}
                    parameters = inspect.signature(srv.search).parameters
                    variadic = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
                    if result_type and ('result_type' in parameters or variadic):
                        options['result_type'] = result_type
                    if 'is_current' in parameters or variadic:
                        options['is_current'] = is_current
                    options_holder[0] = options
                    srv.search(query, **options)
                except Exception as exc:
                    logger.error("%s search could not start: %s", name, type(exc).__name__)
                    _finish([])

            submit(_run_provider, service_name)

        return {"query": query, "tracks": []}

    def _catalog_service(self):
        from services.catalog_service import CatalogService
        with self._window_op_lock:
            service = getattr(self, '_catalog_instance', None)
            if service is None:
                artists = getattr(self._core, 'artists', None)
                service = getattr(artists, 'catalog', None) or CatalogService(getattr(self._core, 'youtube', None), getattr(self._core, 'settings', None))
                self._catalog_instance = service
            return service

    def get_album_tracks(self, album_data: dict):
        if not isinstance(album_data, dict) or not album_data:
            return []
        result = self._catalog_service().album_details(album_data, self._core.db.get_album_tracks)
        return result.get('tracks', []) if result.get('status') == 'found' else []

    def get_album_details(self, album_data: dict, request_id=None):
        import uuid
        rid = str(request_id or uuid.uuid4().hex)
        with self._window_op_lock:
            self._album_request_id = rid
        def current():
            with self._window_op_lock:
                return getattr(self, '_album_request_id', None) == rid
        def run():
            if not current():
                return
            result = self._catalog_service().album_details(album_data if isinstance(album_data, dict) else {}, self._core.db.get_album_tracks, current)
            if current():
                self._emit('album_details_ready', dict(result, request_id=rid))
        self._search_executor.submit(run)
        return {'status': 'loading', 'request_id': rid}

    def get_library(self, limit=200, offset=0, include_total=False):
        limit, offset = min(500, max(1, int(limit))), max(0, int(offset))
        page = getattr(self._core.db, 'get_library_page', None)
        tracks = page(limit=limit, offset=offset) if callable(page) else self._core.db.get_all_tracks(limit=limit, offset=offset)
        total = self._core.db.get_tracks_count() if include_total is True else None
        if include_total is True:
            return {'tracks': tracks, 'total': total, 'limit': limit, 'offset': offset,
                    'has_more': offset + len(tracks) < total}
        return tracks

    def get_favorites(self, limit=None):
        """Read all favorites, or only the leading artwork rows when requested."""
        if limit is None:
            return self.get_favorite_tracks()
        return self._core.db.get_favorite_tracks(limit=max(1,min(500,int(limit))))

    def get_library_summary(self):
        """Counts and legacy favorite deduplication keys without track payloads."""
        db = self._core.db
        favorites = list(db.conn.execute('SELECT id,source_id FROM tracks WHERE is_favorite=1'))
        # Preserve get_downloaded_tracks' exists semantics (including paths
        # that are not audio) while reading only the one required column.
        downloaded_count = sum(bool(row[0] and os.path.exists(row[0])) for row in db.conn.execute(
            'SELECT file_path FROM tracks WHERE is_downloaded=1'))
        keys = {str(row['id']) for row in favorites}
        keys.update(str(row['source_id']) for row in favorites if row['source_id'])
        return {'favorite_count': len(favorites), 'favorite_ids': sorted(keys),
                'downloaded_count': downloaded_count}

    def get_downloaded_tracks(self):
        """Get list of downloaded local tracks (missing files filtered out)."""
        try:
            tracks = self._core.db.get_downloaded_tracks() or []
        except Exception:
            return []
        result = []
        for t in tracks:
            if not isinstance(t, dict):
                continue
            fp = t.get("file_path")
            if fp and os.path.exists(fp):
                result.append(t)
        return result

    def download_track(self, track_data: dict):
        if not isinstance(track_data, dict) or not track_data:
            return False
        track = dict(track_data)
        row = None
        raw_id = track.get('track_id') or track.get('id')
        if isinstance(raw_id, int) or (isinstance(raw_id, str) and raw_id.isdecimal()):
            candidate = self._core.db.get_track(int(raw_id))
            if candidate and (not track.get('source_id') or
                    (str(candidate.get('source_id')) == str(track.get('source_id'))
                     and candidate.get('source') == track.get('source', candidate.get('source')))):
                row = candidate
        if row:
            track = dict(track, **row)
        source = track.get('source') or 'youtube'
        source_id = track.get('source_id')
        def fail(message, row_id=None):
            self._emit('download_failed', {'track_id': row_id or raw_id, 'source': source,
                'source_id': source_id, 'error': message})
            decrement = getattr(self._core.downloader, '_decrement_batch_total_for_dedup', None)
            if callable(decrement):
                decrement()
            return False
        if source == 'local' or not source_id:
            return fail('Для этого трека загрузка недоступна', row.get('id') if row else None)
        try:
            track.pop('id', None)
            track.pop('track_id', None)
            track_id = row['id'] if row else self._core.db.ensure_track_exists(track)
            if not track_id:
                return fail('Не удалось сохранить трек в библиотеке')
            queued = self._core.downloader.queue_download(int(track_id), source, str(source_id))
            if not queued:
                self._emit('download_failed', {'track_id': track_id, 'source': source, 'source_id': source_id,
                    'error': 'Трек уже загружается или очередь отклонила запрос', 'code': 'not_queued'})
            return bool(queued)
        except Exception as exc:
            return fail(describe_error(exc, 'download')['message'], row.get('id') if row else None)

    def import_external_playlist(self, url: str, name: str | None = None):
        url = _extract_first_url(url or '')
        local_path=os.path.abspath(os.path.expanduser(url.strip('"'))) if url else ''
        local_playlist=bool(local_path and os.path.splitext(local_path)[1].lower() in ('.m3u','.m3u8','.json','.txt') and os.path.isfile(local_path))
        if not url or (not local_playlist and not _is_ssrf_safe_url(url)):
            return {'success': False, 'error': 'Некорректная ссылка или путь к плейлисту'}
        if local_playlist:url=local_path
        try:
            importer = getattr(self._core, 'playlist_importer', None)
            if importer is None:
                return {'success': False, 'error': 'Сервис импорта недоступен'}
            resolved = importer.resolve(url)
            tracks = resolved.get('tracks') if isinstance(resolved, dict) else None
            if not tracks:
                return {'success': False, 'error': 'В плейлисте не найдено доступных треков'}
            playlist_name = str(name or resolved.get('name') or 'Импортированный плейлист').strip()[:200]
            playlist_id, count = self._core.db.import_playlist_atomic(playlist_name, 'Imported playlist', tracks)
            self._emit('playlists_updated', {'playlist_id': playlist_id})
            return {'success': True, 'playlist_id': playlist_id, 'playlist_name': playlist_name, 'imported_count': count}
        except Exception as exc:
            from services.deezer_service import DeezerError
            from services.playlist_import_service import UnsupportedPlaylistService
            if isinstance(exc, (DeezerError, UnsupportedPlaylistService)):
                return {'success': False, 'error': str(exc)}
            details = describe_error(exc, 'import')
            logger.warning('Playlist import failed: %s', details['code'])
            return {'success': False, 'error': details['message']}

    def export_playlist(self, playlist_id: int, format: str = "m3u8", target_path: str = None) -> dict:
        """Export playlist tracks to standard M3U8 playlist file or specified format."""
        try:
            if str(format).lower() not in ('m3u','m3u8'):
                return {'success':False,'error':'Поддерживается только экспорт M3U'}
            def line(value):
                return ' '.join(str(value or '').splitlines())
            pid = int(playlist_id)
            playlists = self._core.db.get_playlists() or []
            pl_info = next((p for p in playlists if p.get("id") == pid or p.get("ID") == pid), None)
            pl_name = pl_info.get("name", f"playlist_{pid}") if pl_info else f"playlist_{pid}"
            safe_name = "".join(c for c in pl_name if c.isalnum() or c in (' ', '_', '-')).strip() or f"playlist_{pid}"

            tracks = self._core.db.get_playlist_tracks(pid) or []
            if not tracks:
                return {"success": False, "error": "В плейлисте нет треков для экспорта"}

            music_dir = os.path.expanduser("~/Music")
            if not os.path.exists(music_dir):
                music_dir = os.path.expanduser("~/Downloads")
            if not os.path.exists(music_dir):
                music_dir = os.path.expanduser("~")

            out_file = os.path.join(music_dir, f"{safe_name}.m3u8")
            if target_path:
                # Only playlist extensions, and only inside the user's home: the
                # bridge must not be a way to write arbitrary files on disk.
                target_abs = os.path.realpath(os.path.expanduser(str(target_path)))
                home_abs = os.path.realpath(os.path.expanduser("~"))
                if os.path.splitext(target_abs)[1].lower() not in (".m3u8", ".m3u"):
                    return {"success": False, "error": "Допустимы только файлы .m3u8 и .m3u"}
                try:
                    inside_home = os.path.commonpath([target_abs, home_abs]) == home_abs
                except ValueError:
                    # Different drives (Windows): no shared prefix at all.
                    inside_home = False
                if not inside_home or not os.path.isdir(os.path.dirname(target_abs)):
                    return {"success": False, "error": "Путь экспорта должен быть внутри домашнего каталога"}
                out_file = target_abs

            m3u_lines = ["#EXTM3U", f"#PLAYLIST:{line(pl_name)}"]
            exported_count = 0
            skipped_count = 0

            for t in tracks:
                title = t.get("title") or "Unknown"
                artist = t.get("artist") or "Unknown"
                duration = int(_as_float(t.get('duration')) or 0)
                file_path = t.get("file_path")
                source_url = t.get("source_url") or t.get("stream_url")

                target_uri = None
                if file_path and os.path.exists(file_path):
                    target_uri = os.path.abspath(file_path)
                elif source_url and source_url.startswith(("http://", "https://")):
                    target_uri = source_url
                elif t.get("source") == "youtube" and t.get("source_id"):
                    target_uri = f"https://www.youtube.com/watch?v={t.get('source_id')}"
                elif t.get("source") == "soundcloud" and t.get("source_id"):
                    target_uri = f"https://soundcloud.com/{t.get('source_id')}"

                if target_uri and not any(char in str(target_uri) for char in ('\r','\n','\0')):
                    m3u_lines.append(f"#EXTINF:{duration},{line(artist)} - {line(title)}")
                    m3u_lines.append(target_uri)
                    exported_count += 1
                else:
                    skipped_count += 1

            if exported_count == 0:
                return {"success": False, "error": "Не удалось сформировать пути к аудиофайлам для треков"}

            import tempfile
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(out_file), delete=False) as output:
                    temporary = output.name
                    output.write('\n'.join(m3u_lines) + '\n')
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, out_file)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

            logger.info("Exported playlist '%s' to '%s' (%d tracks)", pl_name, out_file, exported_count)
            return {
                "success": True,
                "file_path": out_file,
                "exported_count": exported_count,
                "skipped_count": skipped_count,
                "playlist_name": pl_name
            }
        except Exception as e:
            logger.error("export_playlist error: %s", type(e).__name__)
            return {"success": False, "error": describe_error(e)['message']}

    def create_playlist(self, name: str, description: str = ""):
        """Create new user playlist."""
        pid = self._core.db.create_playlist(name, description)
        self._emit("playlists_updated", self.get_playlists())
        return pid

    def delete_playlist(self, playlist_id: int):
        """Delete user playlist."""
        try:
            res = self._core.db.delete_playlist(int(playlist_id))
            self._emit("playlists_updated", self.get_playlists())
            return {"success": True, "res": res}
        except Exception as e:
            return {"success": False, "error": describe_error(e)['message']}

    def get_playlists(self):
        """Get list of user playlists."""
        return self._core.db.get_playlists()

    def rename_playlist(self, playlist_id: int, name: str):
        name = str(name or '').strip()
        if not name or len(name) > 200:
            return {'success': False, 'error': 'Введите название длиной от 1 до 200 символов'}
        success = self._core.db.rename_playlist(int(playlist_id), name)
        if success:
            self._emit('playlists_updated', self.get_playlists())
        return {'success': success}

    def remove_from_playlist(self, playlist_id: int, track_id: int):
        success = self._core.db.remove_from_playlist(int(playlist_id), int(track_id))
        if success:
            self._emit('playlist_changed', {'playlist_id': int(playlist_id)})
        return {'success': success}

    def add_to_playlist(self, playlist_id: int, track_data: dict):
        """Add track to playlist."""
        track_id = track_data.get("id")
        if not track_id:
            track_id = self._core.db.add_track(
                title=track_data.get("title") or "Unknown",
                artist=track_data.get("artist", "Unknown Artist"),
                source=track_data.get("source", "local"),
                source_id=track_data.get("source_id"),
                duration=track_data.get("duration", 0)
            )
        res = self._core.db.add_to_playlist(playlist_id, track_id)
        self._emit("playlist_changed", {"playlist_id": playlist_id})
        return res

    def get_track_info(self, track_id: int):
        """Get track metadata including LUFS ReplayGain loudness from database."""
        if not track_id:
            return None
        try:
            track = self._core.db.get_track(int(track_id))
            if track:
                self._enrich_track_lufs(track)
            return track
        except Exception as e:
            logger.error(f"get_track_info error for id {track_id}: {type(e).__name__}")
            return None

    def get_playlist_tracks(self, playlist_id, source: str = "local", limit=None):
        """Get tracks for a playlist by source (local / youtube / soundcloud / spotify). Synchronous."""
        source = (source or "local").lower()

        if source == "local":
            try:
                db_tracks = (self._core.db.get_playlist_tracks(playlist_id, limit=limit)
                             if limit is not None else self._core.db.get_playlist_tracks(playlist_id)) or []
                formatted = []
                for t in db_tracks:
                    if isinstance(t, dict):
                        cov = t.get("cover_path") or t.get("cover_url") or ""
                        item = dict(t)
                        item["cover"] = cov
                        item["cover_url"] = cov
                        item["source"] = t.get("source") or "local"
                        item["source_id"] = str(t.get("source_id") or t.get("id") or "")
                        self._enrich_track_lufs(item)
                        formatted.append(item)
                return {"success": True, "tracks": formatted}
            except Exception as e:
                logger.error(f"get_playlist_tracks local error: {type(e).__name__}")
                return {"success": False, "error": describe_error(e)['message']}

        services = {
            "youtube": getattr(self._core, "youtube", None),
            "soundcloud": getattr(self._core, "soundcloud", None),
            "spotify": getattr(self._core, "spotify", None),
            "deezer": getattr(self._core, "deezer", None),
        }
        srv = services.get(source)
        if srv is None or not hasattr(srv, "get_playlist_tracks"):
            return {"success": False, "error": f"Неизвестный источник плейлистов: {source}"}

        result = {}
        done = threading.Event()

        def _on_success(tracks):
            formatted = []
            for t in (tracks or []):
                if isinstance(t, dict):
                    cov = t.get("cover_url") or t.get("cover") or ""
                    item = t.copy()
                    item["cover"] = cov
                    item["cover_url"] = cov
                    self._enrich_track_lufs(item)
                    formatted.append(item)
            result["tracks"] = formatted
            done.set()

        def _on_error(err):
            result["error"] = describe_error(err)['message']
            done.set()

        try:
            srv.get_playlist_tracks(playlist_id, limit=50 if limit is None else limit, callback=_on_success, error_callback=_on_error)
        except Exception as e:
            logger.error(f"get_playlist_tracks {source} error: {type(e).__name__}")
            return {"success": False, "error": describe_error(e)['message']}

        if not done.wait(timeout=BRIDGE_SYNC_BUDGET):
            return {"success": False, "error": "Таймаут получения треков плейлиста"}
        if "error" in result:
            return {"success": False, "error": result["error"]}
        return {"success": True, "tracks": result.get("tracks", [])}

    def get_yt_playlist_tracks(self, playlist_id, limit: int = 50):
        """Legacy wrapper for get_playlist_tracks with source='youtube'."""
        return self.get_playlist_tracks(playlist_id, source="youtube", limit=limit)

    def toggle_favorite(self, track_data: dict):
        """Toggle favorite status for track."""
        if not isinstance(track_data, dict):
            return {'success': False, 'error': 'Некорректный трек'}
        track_id = self._core.db.ensure_track_exists(track_data)
        status = self._core.db.toggle_favorite(track_id)
        with self._playback_guard():
            active = getattr(self, '_current_track', None)
            if active and self._listening_identity(active)[:2] == self._listening_identity(track_data)[:2]:
                active['is_favorite'] = status
                tray = getattr(self, '_tray', None)
                if tray:
                    tray.update_state(track=active, force=True)
        self._emit("favorites_updated", self.get_favorite_tracks())
        result = {"success": True, "is_favorite": status}
        if status:
            # Only on the way in: un-liking must never delete anything.
            try:
                auto = self._auto_save_favorite(track_data, track_id)
                if auto:
                    result["auto_download"] = auto
            except Exception as e:
                # A failed side-effect must not break the like itself.
                logger.warning("auto-download on favorite failed: %s", type(e).__name__)
        return result

    def _auto_save_favorite(self, track_data: dict, track_id):
        """Cache the stream now, then download it in the background.

        Returns a short status dict for the caller (surfaced as
        ``auto_download``) or None when the feature is off or nothing to do.
        """
        if not getattr(self._core, "settings", None):
            return None
        if not self._core.settings.get("storage", "auto_download_favorites", False):
            return None

        source = track_data.get("source") or "local"
        # Local files are already on disk: there is nothing to fetch.
        if source == "local":
            return None

        source_id = track_data.get("source_id")
        if not source_id and track_id is not None:
            try:
                row = self._core.db.get_track(int(track_id))
            except (ValueError, TypeError):
                row = None
            except Exception:
                logger.debug("auto-download DB lookup failed", exc_info=True)
                row = None
            if row:
                source_id = row.get("source_id") or source_id
                source = row.get("source") or source
        if not source_id:
            return None

        already = False
        try:
            already = bool(self._core.db.get_track(int(track_id)).get("is_downloaded")) if track_id else False
        except Exception:
            logger.debug("auto-download is_downloaded check failed", exc_info=True)
        if already:
            return None

        # 1) Immediate stream cache so playback starts without a second fetch.
        cached = False
        cache = getattr(self._core, "cache", None)
        url = track_data.get("stream_url") or track_data.get("url") or ""
        if cache is not None:
            try:
                cache.download_audio_stream(source, str(source_id), url)
                cached = True
            except Exception:
                logger.warning("favorite stream cache failed", exc_info=True)

        # 2) Background download to ~/downloads, gated by its own quota.
        quota_gb = self._core.settings.get("storage", "auto_download_favorites_quota_gb", 20)
        try:
            quota_gb = float(quota_gb)
        except (TypeError, ValueError):
            quota_gb = 20.0
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024) if quota_gb > 0 else 0

        used = 0
        try:
            from core.download_processing import download_directory
            dl_dir = download_directory(self._core.settings)
            if os.path.isdir(dl_dir):
                for name in os.listdir(dl_dir):
                    fp = os.path.join(dl_dir, name)
                    try:
                        if os.path.isfile(fp):
                            used += os.path.getsize(fp)
                    except OSError:
                        continue
        except Exception:
            logger.debug("auto-download size scan failed", exc_info=True)

        if quota_bytes and used >= quota_bytes:
            return {"cached": cached, "queued": False,
                    "reason": f"Достигнут лимит автозагрузки ({int(quota_gb)} ГБ)"}

        payload = dict(track_data)
        payload["id"] = track_id
        payload["source"] = source
        payload["source_id"] = str(source_id)
        # Not a user-initiated batch: no batch counter, no progress modal.
        # queue_download(track_id, source, source_id) is positional.
        queued = bool(self._core.downloader.queue_download(track_id, source, str(source_id)))
        if queued:
            self._emit("favorites_updated", self.get_favorite_tracks())
        return {"cached": cached, "queued": queued, "reason": None if queued else "Не удалось поставить в очередь"}

    def get_favorite_tracks(self):
        """Get list of favorite tracks."""
        return self._core.db.get_favorite_tracks()

    def set_snap_button_rect(self, x, y, width, height):
        """Report the maximise button's client-relative rect (CSS pixels).

        The frontend measures #btn-maximize and sends the rectangle here; the
        WM_NCHITTEST handler then answers HTMAXBUTTON over it, which is what
        makes Windows 11 show the Snap Layout flyout on hover.
        """
        values = tuple(float(value) for value in (x, y, width, height))
        if not all(math.isfinite(value) and abs(value) <= 100_000 for value in values):
            return {"success": False}
        self._pending_snap_rect = values
        snap = getattr(self, "_snap_layouts", None)
        if snap is None:
            return {"success": False}
        try:
            snap.set_button_rect(x, y, width, height)
            return {"success": True}
        except Exception as e:
            logger.debug("set_snap_button_rect failed: %s", type(e).__name__)
            return {"success": False}

    def save_theme(self, theme: str):
        """Save theme setting."""
        if theme not in ('dark', 'midnight', 'mint', 'light'):
            return False
        self._core.settings.set("theme", "theme", theme)
        self._emit("theme_changed", theme)
        return True

    def complete_onboarding(self, settings_data: dict):
        """Persist chosen preferences before acknowledging first-launch completion.

        An empty payload means skip: keep every existing preference unchanged.
        """
        if not isinstance(settings_data, dict):
            return {"success": False, "error": "Некорректные параметры настройки"}
        boolean_keys = ("particles_enabled", "crossfade_enabled", "volume_normalization", "autostart", "minimize_to_tray")
        for key in boolean_keys:
            if key in settings_data and not isinstance(settings_data[key], bool):
                return {"success": False, "error": "Некорректное значение переключателя"}
        theme = settings_data.get("theme")
        mode = settings_data.get("theme_mode")
        preset = settings_data.get("performance_preset")
        if theme is not None and theme not in ("dark", "midnight", "mint", "light"):
            return {"success": False, "error": "Выберите доступную тему"}
        if mode is not None and mode not in ("dark", "light", "system"):
            return {"success": False, "error": "Выберите доступный режим оформления"}
        if preset is not None and preset not in ("high", "balanced", "low"):
            return {"success": False, "error": "Выберите режим производительности"}
        device = settings_data.get("audio_device")
        if device is not None and (not isinstance(device, str) or not device.strip() or len(device) > 512):
            return {"success": False, "error": "Выберите аудиоустройство"}
        accent = settings_data.get("accent_color")
        if accent is not None and (not isinstance(accent, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent)):
            return {"success": False, "error": "Некорректный цвет оформления"}
        style = settings_data.get("ui_style")
        if "ui_style" in settings_data and style not in ("current", "macos"):
            return {"success": False, "error": "Выберите доступный интерфейс"}
        sources = settings_data.get("sources", {})
        if not isinstance(sources, dict) or any(name not in ("youtube", "soundcloud")
                or not isinstance(enabled, bool) for name, enabled in sources.items()):
            return {"success": False, "error": "Выберите доступные источники музыки"}
        if "download_format" in settings_data and settings_data["download_format"] not in ("source", "mp3", "m4a", "opus", "flac", "wav"):
            return {"success": False, "error": "Выберите доступный формат скачивания"}
        if "download_quality" in settings_data and settings_data["download_quality"] not in ("best", "128", "192", "256", "320"):
            return {"success": False, "error": "Выберите доступное качество скачивания"}

        settings = self._core.settings
        previous_flags = (settings.get("general", "first_launch_done", False),
                          settings.get("personalization", "onboarding_completed", False))
        try:
            if "autostart" in settings_data:
                enabled = settings_data["autostart"]
                if enabled != settings.get("general", "autostart", False) and not self.update_autostart(enabled):
                    return {"success": False, "error": "Не удалось изменить автозапуск. Выключите его или повторите попытку."}
            mapping = {
                "accent_color": ("theme", "accent_color"),
                "particles_enabled": ("ui", "particles_enabled"),
                "crossfade_enabled": ("audio", "crossfade_enabled"),
                "volume_normalization": ("audio", "volume_normalization"),
                "autostart": ("general", "autostart"),
                "minimize_to_tray": ("general", "minimize_to_tray"),
                "audio_device": ("audio", "output_device"),
                "ui_style": ("interface", "ui_style"),
                "download_format": ("downloads", "format"),
                "download_quality": ("downloads", "quality"),
            }
            if theme is not None or mode is not None:
                selected = theme or ("light" if mode == "light" else "dark")
                selected_mode = mode or ("light" if selected == "light" else "dark")
                for key, value in {"theme": selected, "theme_mode": selected_mode, "mode": selected_mode,
                                   "custom_palette_enabled": False, "custom_primary": "", "custom_accent": ""}.items():
                    settings.set("theme", key, value)
                if style == "macos":
                    settings.set("interface", "macos_mode", selected_mode)
            if preset is not None:
                profiles = {
                    "high": (24, 60, 60, "hq", "full", 14),
                    "balanced": (18, 30, 45, "lq", "subtle", 6),
                    "low": (10, 15, 30, "off", "off", 0),
                }
                particles, visualizer, ui, blur, glow, glass = profiles[preset]
                for key, value in {"performance_preset": preset, "fps_particles": particles, "fps_visualizer": visualizer,
                                   "fps_ui": ui, "blur_quality": blur, "glow_quality": glow, "resource_blur": glass > 0}.items():
                    settings.set("optimization", key, value)
                settings.set("theme", "glass_blur", glass)
                settings.set("ui", "particles_enabled", settings_data.get("particles_enabled", preset != "low"))
            for key, target in mapping.items():
                if key in settings_data and settings_data[key] is not None:
                    settings.set(target[0], target[1], settings_data[key])
            for name, enabled in sources.items():
                settings.set("services", f"{name}_enabled", enabled)
            if "particles_enabled" in settings_data or preset is not None:
                settings.set("optimization", "resource_particles", settings.get("ui", "particles_enabled", True))
            if "autostart" in settings_data:
                settings.set("app", "autostart", settings_data["autostart"])
            flush = getattr(settings, "sync_flush_now", None)
            if callable(flush) and not flush():
                return {"success": False, "error": "Не удалось сохранить настройки. Повторите попытку."}
            settings.set("general", "first_launch_done", True)
            settings.set("personalization", "onboarding_completed", True)
            if callable(flush) and not flush():
                raise RuntimeError("Onboarding completion was not persisted")
            return {"success": True, "settings": self.get_settings()}
        except Exception:
            logger.exception("Failed to complete onboarding")
            settings.set("general", "first_launch_done", previous_flags[0])
            settings.set("personalization", "onboarding_completed", previous_flags[1])
            return {"success": False, "error": "Не удалось сохранить настройки. Повторите попытку."}

    def update_autostart(self, enabled: bool):
        """Toggle the app autostart registry entry on Windows.

        Writes AUTOSTART_RUN_VALUE under AUTOSTART_RUN_KEY in HKCU - the exact
        hive/key/value-name triple that installer.iss writes, so enabling
        autostart leaves ONE Run entry instead of two. Legacy names from
        pre-NeDotify builds (AUTOSTART_RUN_LEGACY_VALUES, i.e. "AURA Music")
        are removed on both the enable and the disable path: they survived
        enabling (second launch at logon) and only the old code, on disable,
        removed the pair.
        """
        if sys.platform != "win32":
            return False
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                if enabled:
                    if getattr(sys, 'frozen', False):
                        exe_path = f'"{sys.executable}"'
                    else:
                        # Anchor to this file, not the CWD: launching the app from a
                        # different working directory used to register a broken
                        # autostart entry.
                        main_py = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
                        )
                        exe_path = f'"{sys.executable}" "{main_py}"'
                    winreg.SetValueEx(key, AUTOSTART_RUN_VALUE, 0, winreg.REG_SZ, exe_path)
                # Only the legacy names are dropped on the enable path: the value
                # just written above must survive. On disable, the current name
                # goes too, otherwise the toggle could never turn autostart off.
                stale_names = (
                    AUTOSTART_RUN_LEGACY_VALUES if enabled
                    else (AUTOSTART_RUN_VALUE,) + tuple(AUTOSTART_RUN_LEGACY_VALUES)
                )
                for name in stale_names:
                    try:
                        winreg.DeleteValue(key, name)
                    except (FileNotFoundError, OSError):
                        pass
            finally:
                try:
                    winreg.CloseKey(key)
                except OSError:
                    logger.debug("Registry key close failed", exc_info=True)
            self._core.settings.set("general", "autostart", enabled)
            self._core.settings.set("app", "autostart", enabled)
            return True
        except (OSError, Exception) as e:
            logger.error(f"Failed to update autostart: {type(e).__name__}")
            return False

    def validate_subscription_key(self, key: str):
        """Report licence status for `key`. Validation intentionally disabled.

        Licensing is not enforced in this build: LICENSE_VALIDATION_ENABLED is
        False and no caller exists (the UI never asks), so every key is reported
        as valid. The stub is kept on purpose - it is the documented seam for a
        remote, server-owned licensing service - and the flag is honoured here
        rather than the result being hardcoded, so flipping it cannot be
        forgotten: with validation on and no service wired up, access is denied
        instead of silently granted. Do not add UI that calls this.
        """
        if not LICENSE_VALIDATION_ENABLED:
            return {"valid": True, "is_valid": True, "success": True, "expire": "never", "valid_until": 0}
        logger.warning("Licence validation is enabled but no validation service is configured")
        return {"valid": False, "is_valid": False, "success": False,
                "error": "Сервис проверки лицензий недоступен", "valid_until": 0}

    def get_subscription_info(self):
        """Return current licence information. Validation intentionally disabled.

        See validate_subscription_key: the stub exists for a future server-side
        licensing service and has no caller today.
        """
        if not LICENSE_VALIDATION_ENABLED:
            return {"valid": True, "is_valid": True, "success": True, "expire": "never",
                    "valid_until": 0, "key": "OPEN-SOURCE"}
        logger.warning("Licence validation is enabled but no validation service is configured")
        return {"valid": False, "is_valid": False, "success": False,
                "error": "Сервис проверки лицензий недоступен", "valid_until": 0, "key": ""}

    def get_settings(self, category: str = None):
        """Get settings dict."""
        if category:
            return _mask_secrets(category, self._core.settings.get_category(category))

        from core.settings import DEFAULT_SETTINGS
        categories = set(DEFAULT_SETTINGS)
        category_names = getattr(self._core.settings, 'categories', None)
        if callable(category_names):
            categories.update(category_names())
        res = {}
        for c in sorted(categories):
            try:
                cat_data = self._core.settings.get_category(c)
                if cat_data:
                    res[c] = _mask_secrets(c, cat_data)
            except Exception:
                logger.debug("settings category %s unavailable", c, exc_info=True)
        return res

    def _store_setting(self, category, key, value, *, clear_legacy=False):
        """A bridge save acknowledges durable storage, with rollback on failure."""
        changes = [(category, key, value)]
        if clear_legacy:
            changes.append(('auth', key, ''))
        return self._store_settings(changes)

    def _store_settings(self, changes):
        """Persist one settings action as a batch before acknowledging it."""
        settings = self._core.settings
        with self._window_op_lock:
            previous = [(category, key, settings.get(category, key))
                        for category, key, _ in changes]
            for category, key, value in changes:
                settings.set(category, key, value)
            flush = getattr(settings, 'sync_flush_now', None)
            try:
                saved = not callable(flush) or flush() is not False
            except Exception:
                logger.error('Settings action persistence failed')
                saved = False
            if not saved:
                for category, key, value in previous:
                    settings.set(category, key, value)
            return saved

    def save_setting(self, key: str, value, category: str = 'app'):
        if not isinstance(key, str) or not isinstance(category, str):
            return False
        if '.' in key:
            category, key = key.split('.', 1)
        if category == 'app' and key == 'discord_rpc_enabled':
            return self.toggle_discord_rpc(value)
        if category == 'app' and key.startswith('discord_'):
            if key not in {'discord_show_title', 'discord_show_artist', 'discord_show_cover',
                           'discord_show_time', 'discord_show_listen', 'discord_clear_on_stop'} or not isinstance(value, bool):
                return False
        if category == 'atmosphere':
            from core.settings import validate_atmosphere_setting
            try:
                value = validate_atmosphere_setting(key, value, self._core.settings.get(category, key))
            except ValueError:
                return False
        error = _bridge_write_error(category, key, value)
        if error:
            return {'success': False, 'error': error}
        if _is_empty_secret_write(category, key, value):
            return True
        clear_legacy = category == 'services' and key in ('lastfm_api_key', 'lastfm_api_secret') and value is None
        if key in _SECRET_SETTING_KEYS.get(category, ()) and value is None:
            value = ''
        if key == 'autostart':
            previous_autostart = self._core.settings.get('general', 'autostart', False)
            if not isinstance(value, bool) or not self.update_autostart(value):
                return False
            category = 'general'
        if category == 'audio' and key == 'volume':
            value = _as_float(value)
            if value is None or not 0 <= value <= 100:
                return False
            value = round(value)
        if category == 'services' and key in ('lastfm_enabled', 'youtube_enabled', 'soundcloud_enabled') and not isinstance(value, bool):
            return False
        if key == 'border_radius' and category in ('theme', 'interface'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 24:
                return False
        saved = self._store_setting(category, key, value, clear_legacy=clear_legacy)
        if saved and category == 'app' and key.startswith('discord_'):
            service = getattr(self._core, 'discord_rpc', None)
            if service and hasattr(service, 'refresh'):
                service.refresh()
        if not saved and key == 'autostart':
            self.update_autostart(bool(previous_autostart))
        return saved

    def get_all_settings(self):
        return self.get_settings()

    def get_settings_by_category(self, category: str):
        return _mask_secrets(category, self._core.settings.get_category(category))

    def update_setting(self, category: str, key: str, value):
        return self.save_setting(key, value, category)

    def get_personalization(self):
        return self._core.settings.get_category("personalization")

    def get_recommendation_feedback(self, track):
        from services.artist_identity import artist_aliases, canonical_artist, track_key
        if not isinstance(track, dict):
            return {'track': False, 'artist': False}
        aliases = artist_aliases(self._core.settings)
        artist = canonical_artist(track.get('artist'), aliases)
        content = track_key(track, aliases)
        blocked = self._core.settings.get('personalization', 'blocked_artists', [])
        disliked = self._core.settings.get('personalization', 'disliked_tracks', [])
        return {'artist': any(canonical_artist(a, aliases) == artist for a in blocked) if isinstance(blocked, list) else False,
                'track': any(isinstance(t, dict) and track_key(t, aliases) == content for t in disliked) if isinstance(disliked, list) else False}

    def set_recommendation_feedback(self, track, kind='track', blocked=True):
        from services.artist_identity import artist_aliases, canonical_artist, track_key
        if not isinstance(track, dict) or kind not in ('track', 'artist') or not str(track.get('artist') or '').strip():
            return {'success': False, 'error': 'Не указан исполнитель'}
        if kind == 'track' and not str(track.get('title') or '').strip():
            return {'success': False, 'error': 'Не указан трек'}
        with self._window_op_lock:
            aliases = artist_aliases(self._core.settings)
            artist, content = canonical_artist(track['artist'], aliases), track_key(track, aliases)
            key = 'blocked_artists' if kind == 'artist' else 'disliked_tracks'
            values = self._core.settings.get('personalization', key, [])
            values = list(values) if isinstance(values, list) else []
            if kind == 'artist':
                values = [a for a in values if canonical_artist(a, aliases) != artist]
                if blocked:
                    values.append(str(track['artist']).strip()[:200])
            else:
                values = [t for t in values if not (isinstance(t, dict) and track_key(t, aliases) == content)]
                if blocked:
                    values.append({'artist': str(track['artist']).strip()[:200], 'title': str(track['title']).strip()[:300]})
            if not self._store_setting('personalization', key, values[-1000:]):
                return {'success': False, 'error': 'Не удалось сохранить предпочтение'}
        return {'success': True, **self.get_recommendation_feedback(track)}

    def set_artist_alias(self, alias, canonical):
        from services.artist_identity import name_key, artist_aliases
        if not isinstance(alias, str) or not isinstance(canonical, str) or not name_key(alias) or not name_key(canonical):
            return {'success': False, 'error': 'Укажите два имени исполнителя'}
        with self._window_op_lock:
            stored = self._core.settings.get('personalization', 'artist_aliases', {})
            aliases = dict(stored) if isinstance(stored, dict) else {}
            if len(aliases) >= 500 and name_key(alias) not in aliases:
                return {'success': False, 'error': 'Достигнут предел связей имён'}
            aliases[name_key(alias)] = canonical.strip()[:200]
            effective = artist_aliases(self._core.settings)
            effective.update({name_key(k): v for k, v in aliases.items()})
            seen, key = set(), name_key(alias)
            while key in effective and name_key(effective[key]) != key:
                if key in seen:
                    return {'success': False, 'error': 'Циклическая связь имён'}
                seen.add(key)
                key = name_key(effective[key])
            self._core.settings.set('personalization', 'artist_aliases', aliases)
        return {'success': True}

    def remove_artist_alias(self, alias):
        from services.artist_identity import name_key
        if not isinstance(alias, str) or not name_key(alias):
            return {'success': False, 'error': 'Укажите имя исполнителя'}
        with self._window_op_lock:
            stored = self._core.settings.get('personalization', 'artist_aliases', {})
            aliases = dict(stored) if isinstance(stored, dict) else {}
            key = name_key(alias)
            if key in aliases:
                del aliases[key]
                self._core.settings.set('personalization', 'artist_aliases', aliases)
        return {'success': True}

    def get_recommendation_quality(self, days=30):
        return self._core.db.get_recommendation_quality(days)

    def save_personalization(self, data: dict):
        from core.settings import DEFAULT_SETTINGS
        if not isinstance(data, dict) or len(data) > 40:
            return False
        allowed = DEFAULT_SETTINGS.get('personalization', {})
        if any(key not in allowed for key in data):
            return False
        if len(json.dumps(data, ensure_ascii=False)) > 200_000:
            return False
        for key, value in data.items():
            if isinstance(value, (list, dict)) and len(value) > 1000:
                return False
            if value is not None and not isinstance(value, type(allowed[key])):
                return False
        for key, value in data.items():
            self._core.settings.set('personalization', key, value)
        return True

    #: get_storage_info walks the whole cache tree, which is far too slow to redo on
    #: every settings-screen render. Result is reused for this many seconds.
    _STORAGE_INFO_TTL = 30.0

    def get_storage_info(self):
        details = self._storage_metrics()
        self._emit('storage_info', details)
        return details

    def clear_storage(self, storage_type: str = 'cache', confirmed: bool = False) -> bool:
        storage_type = str(storage_type or 'cache').lower()
        if storage_type not in ('cache', 'all') or (storage_type == 'all' and confirmed is not True):
            return False
        cache = getattr(self._core, 'cache', None)
        if cache is None:
            return False
        cache.clear_all()
        if storage_type == 'all':
            downloader = getattr(self._core, 'downloader', None)
            if downloader and hasattr(downloader, 'cancel_batch'):
                downloader.cancel_batch()
            self._delete_downloaded_files()
        self._storage_info_cache = None
        self._storage_metrics_cache = None
        return True

    def _delete_downloaded_files(self) -> int:
        from pathlib import Path
        root = Path(os.path.expanduser('~/.nedotify/downloads')).resolve()
        removed = 0
        for track in self._core.db.get_downloaded_tracks() or []:
            if not isinstance(track, dict) or track.get('source') == 'local' or not track.get('file_path'):
                continue
            candidate = Path(track['file_path']).resolve()
            if candidate == root or not candidate.is_relative_to(root):
                continue
            try:
                if candidate.is_file():
                    candidate.unlink()
                    removed += 1
                self._core.db.clear_download_state(track['id'])
            except OSError:
                logger.warning('Could not remove an app-owned download')
        return removed

    def get_wrapped_stats(self, period: str = "week"):
        """Get NeDotify Wrapped analytics stats (top 5 tracks/artists, total minutes, activity graph)."""
        try:
            return self._core.db.get_wrapped_stats(period=period)
        except Exception as e:
            logger.error(f"Error fetching wrapped stats: {type(e).__name__}")
            return {
                "period": period,
                "total_plays": 0,
                "total_seconds": 0,
                "total_minutes": 0,
                "total_hours": 0,
                "top_tracks": [],
                "top_artists": [],
                "daily_activity": []
            }

    def get_equalizer(self):
        return {'preamp': self._core.settings.get('equalizer', 'preamp', 0),
            'bands': self._core.settings.get('equalizer', 'bands', [0] * 10),
            'mode': self._core.settings.get('equalizer', 'mode', '10')}

    def set_equalizer(self, preamp: float = 0, bands: list = None, mode=None):
        if mode is not None and str(mode) not in ('3', '6', '10'):
            return False
        preamp = _as_float(preamp)
        if preamp is None or not -24 <= preamp <= 24:
            return False
        if bands is not None:
            if not isinstance(bands, list) or len(bands) not in (0, 3, 10):
                return False
            values = [_as_float(v) for v in bands]
            if any(v is None or not -24 <= v <= 24 for v in values):
                return False
        if mode is not None:
            if str(mode) not in ('3', '6', '10'):
                return False
        changes = [('equalizer', 'preamp', preamp)]
        if bands is not None:
            changes.append(('equalizer', 'bands', values))
        if mode is not None:
            changes.append(('equalizer', 'mode', str(mode)))
        return self._store_settings(changes)

    def get_lyrics(self, track_name: str, artist_name: str, duration_ms=0, file_path=None, album_name='', request_id=None, source='', source_id=''):
        import uuid
        import inspect
        rid = str(request_id or uuid.uuid4().hex)
        with self._lyrics_lock:
            self._lyrics_cascade_count += 1
            cascade_no = self._lyrics_cascade_count
            playback_epoch = self._playback_epoch
        def current():
            with self._lyrics_lock:
                return (not getattr(self, '_closed', False) and cascade_no == self._lyrics_cascade_count
                        and playback_epoch == self._playback_epoch)
        published = [False]
        def publish(data):
            if current():
                published[0] = True
                payload = dict(data or {}, request_id=rid, track_key=str(track_name) + '\0' + str(artist_name))
                self._emit('lyrics_ready', payload)
        def run():
            if not current():
                return
            try:
                service = self._core.lyrics
                if 'on_update' in inspect.signature(service.get_lyrics).parameters:
                    identity = {'source': source, 'source_id': source_id} if 'source' in inspect.signature(service.get_lyrics).parameters else {}
                    data = service.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path,
                                              album_name=album_name, on_update=publish, is_current=current, **identity)
                else:
                    data = service.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path)
                if not published[0]:
                    publish(dict(data or {}, revision=1, phase='final'))
            except Exception as exc:
                logger.warning('Lyrics request failed: %s', type(exc).__name__)
                if not published[0]:
                    publish({'status': 'unavailable', 'syncedLyrics': None, 'plainLyrics': None, 'weight': 3, 'revision': 1, 'phase': 'final'})
        with self._lyrics_lock:
            previous = getattr(self, '_lyrics_future', None)
            if previous:
                previous.cancel()
            self._lyrics_future = self._lyrics_request_executor.submit(run)
        return {'status': 'loading', 'cascade': cascade_no, 'request_id': rid}

    def fetch_missing_covers(self, limit=40):
        limit = max(1,min(40,int(limit)))
        with self._window_op_lock:
            if getattr(self, '_cover_backfill_busy', False):
                return {'updated':0, 'scanned':0}
            self._cover_backfill_busy = True
            before = getattr(self, '_cover_before_id', None)
            attempts = getattr(self, '_cover_attempts', {})
            self._cover_attempts = attempts
        updated, scanned = 0, 0
        try:
            rows = self._core.db.get_tracks_missing_cover(limit=limit, before_id=before)
            if not rows:
                self._cover_before_id = None
                return {'updated':0,'scanned':0}
            deadline = time.monotonic() + BRIDGE_SYNC_BUDGET
            for row in rows:
                if getattr(self, '_closed', False) or time.monotonic() >= deadline:
                    break
                self._cover_before_id = row['id']
                scanned += 1
                if time.monotonic() - attempts.get(row['id'], -1e9) < 3600:
                    continue
                attempts[row['id']] = time.monotonic()
                while len(attempts) > 4096:
                    attempts.pop(next(iter(attempts)))
                future = self._metadata_executor.submit(self._resolve_track_metadata, row['source'], str(row['source_id']))
                try:
                    extra = future.result(timeout=max(.01,deadline-time.monotonic())) or {}
                    cover = str(extra.get('cover_url') or '')
                    if cover:
                        self._core.db.backfill_track_metadata(int(row['id']), cover,
                            title=str(extra.get('title') or ''), artist=str(extra.get('artist') or ''))
                        updated += 1
                except Exception:
                    future.cancel()
            if updated:
                self._emit('library_updated', {'covers':updated})
            return {'updated':updated,'scanned':scanned}
        finally:
            with self._window_op_lock:
                self._cover_backfill_busy = False

    def _resolve_track_metadata(self, source: str, source_id: str) -> dict:
        """Ask the owning provider for one track's artwork and real names."""
        svc = None
        if source == "soundcloud":
            svc = getattr(self._core, "soundcloud", None)
        elif source == "youtube":
            svc = getattr(self._core, "youtube", None)
        getter = getattr(svc, "get_track_metadata", None) if svc else None
        if not callable(getter):
            return {}
        try:
            return getter(source_id) or {}
        except Exception:
            logger.debug("_resolve_track_metadata(%s/%s) failed", source, source_id, exc_info=True)
            return {}

    def _resolve_track_cover(self, source: str, source_id: str) -> str:
        return str(self._resolve_track_metadata(source, source_id).get("cover_url") or "")

    def get_lyrics_translation(self, lyrics_text: str, target_lang: str = 'ru'):
        try:
            text = self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
            return {'success': True, 'text': str(text or ''), 'error': None}
        except Exception as exc:
            return {'success': False, 'text': '', 'error': describe_error(exc, 'translation')['message']}

    def get_home_data(self):
        """Get home feed dashboard statistics and data."""
        history = self._core.db.get_history(limit=10) or []
        for h in history:
            if isinstance(h, dict) and h.get("track_id"):
                h["id"] = h["track_id"]
        total_time_ms = self._core.db.get_total_listening_time() or 0
        top_tracks = self._core.db.get_most_played(limit=10) or []
        top_artists = self._core.db.get_top_artists(limit=10) or []
        return {
            "history": history,
            "favorites_count": self._core.db.get_tracks_count_by_favorite(),
            "total_listening_ms": total_time_ms,
            "total_tracks": self._core.db.get_tracks_count(),
            "playlists": self.get_playlists(),
            "analytics": {
                "total_time_seconds": total_time_ms / 1000,
                "top_tracks": top_tracks,
                "top_artists": top_artists,
            }
        }

    def get_popular_tracks(self, region: str = "US", request_id=None):
        """Request popular tracks and echo request IDs to reject stale UI results."""
        fallback = self._core.db.get_history(limit=10) or []
        def publish(tracks, error=None):
            payload = (tracks or [])
            if request_id is not None:
                payload = {"request_id": str(request_id), "tracks": payload}
            if error and isinstance(payload, dict):
                payload['error'] = describe_error(error, 'recommendations')['message']
            self._emit("popular_results", payload)
        try:
            provider = getattr(self._core.recommendations, "get_charts", None)
            if provider:
                provider(region, callback=publish, error_callback=lambda error: publish([], error))
            else:
                self._core.recommendations.get_releases(
                    [region], callback=publish, error_callback=lambda error: publish([], error)
                )
        except Exception as exc:
            logger.info("Popular tracks fallback: %s", type(exc).__name__)
            publish([], exc)
        return {"request_id": str(request_id), "status": "pending"} if request_id is not None else []

    def get_authentic_home_feed(self, limit: int = 20):
        """Emit authentic home recommendations based on history & taste profile."""
        try:
            if hasattr(self._core.db, "get_user_history_tracks"):
                history = self._core.db.get_user_history_tracks(limit=limit)
            else:
                history = self._core.db.get_history(limit=limit)

            def _format_section_items(items):
                formatted = []
                for it in (items or []):
                    if isinstance(it, dict):
                        item_copy = dict(it)
                        if "type" not in item_copy:
                            item_copy["type"] = "track"
                        self._enrich_track_lufs(item_copy)
                        formatted.append(item_copy)
                return formatted

            def _on_feed(feed_data):
                sections = []
                if isinstance(feed_data, list):
                    sections = [{"title": "Рекомендации", "items": _format_section_items(feed_data)}]
                elif isinstance(feed_data, dict):
                    if "sections" in feed_data and isinstance(feed_data["sections"], list):
                        sections = []
                        for sec in feed_data["sections"]:
                            if isinstance(sec, dict):
                                sec_copy = dict(sec)
                                sec_copy["items"] = _format_section_items(sec_copy.get("items", []))
                                sections.append(sec_copy)
                    elif "items" in feed_data and isinstance(feed_data["items"], list):
                        sections = [{"title": "Рекомендации", "items": _format_section_items(feed_data["items"])}]
                self._emit("authentic_home_ready", {"sections": sections})

            def _on_err(err):
                logger.warning(f"get_authentic_home_feed error: {type(err).__name__}")
                # Fallback to popular tracks / default sections
                self._emit("authentic_home_ready", {"sections": []})

            if hasattr(self._core, "recommendations") and self._core.recommendations:
                self._core.recommendations.get_feed(
                    history=history, max_results=limit, callback=_on_feed, error_callback=_on_err,
                )
            else:
                self._emit("authentic_home_ready", {"sections": []})
        except Exception as e:
            logger.error(f"get_authentic_home_feed exception: {type(e).__name__}")
            self._emit("authentic_home_ready", {"sections": []})
        return {}

    def get_profile_stats(self):
        """Get profile stats (counts via COUNT(*), not full-row fetches)."""
        return {
            "total_tracks": self._core.db.get_tracks_count(),
            "favorite_count": self._core.db.get_tracks_count_by_favorite(),
            "playlist_count": self._core.db.get_playlists_count(),
            "total_listening_time_ms": self._core.db.get_total_listening_time(),
            "most_played": self._core.db.get_most_played(limit=5),
            "recently_played": self._core.db.get_history(limit=5)
        }

    def select_avatar(self):
        """Open native file dialog to select avatar image."""
        if not self._window:
            return None
        try:
            dialog_type = getattr(webview, 'FileDialog', webview).OPEN if hasattr(webview, 'FileDialog') else webview.OPEN_DIALOG
            res = self._window.create_file_dialog(dialog_type, allow_multiple=False, file_types=("Image Files (*.jpg;*.png;*.webp)",))
            if res and len(res) > 0:
                src = res[0]
                avatars_dir = os.path.join(self._core.cache.cache_dir, "avatars")
                os.makedirs(avatars_dir, exist_ok=True)
                ext = os.path.splitext(src)[1]
                dest = os.path.join(avatars_dir, f"avatar_{int(time.time())}{ext}")
                shutil.copy(src, dest)
                self._core.settings.set("personalization", "avatar_path", dest)
                self._core.settings.set("app", "avatar_path", dest)
                return dest
        except Exception as e:
            logger.error(f"Select avatar error: {type(e).__name__}")
        return None

    def create_local_playlist(self, name: str, tracks: list = None):
        """Create a playlist from supplied tracks or the current local library."""
        pid = self.create_playlist(name)
        track_list = tracks if tracks is not None else self._core.db.get_all_tracks(source="local")
        track_ids = []
        for track in track_list:
            t_id = track.get("id") if isinstance(track, dict) else None
            if not t_id and isinstance(track, dict):
                t_id = self._core.db.ensure_track_exists(track)
            if t_id:
                track_ids.append(t_id)
        if track_ids:
            self._core.db.add_tracks_to_playlist(pid, track_ids)
        self._emit("playlists_updated", {"playlist_id": pid})
        return pid

    def open_local_file(self):
        if not self._window:
            return {'success': False, 'error': 'Окно приложения недоступно'}
        try:
            dialog_type = webview.FileDialog.OPEN if hasattr(webview, 'FileDialog') else webview.OPEN_DIALOG
            files = self._window.create_file_dialog(dialog_type, allow_multiple=True,
                file_types=('Audio Files (*.mp3;*.flac;*.wav;*.ogg;*.m4a;*.aac;*.wma)',))
            if not files:
                return {'success': False, 'cancelled': True, 'count': 0}
            imported = [row for path in files if (row := self._core.scanner.scan_single_file(path))]
            if not imported:
                return {'success': False, 'count': 0, 'error': 'Аудиофайлы не найдены'}
            self._emit('library_updated', True)
            self.play_track(imported[0], imported, 0)
            return {'success': True, 'count': len(imported), 'tracks': imported}
        except Exception as exc:
            return {'success': False, 'error': describe_error(exc, 'import')['message']}

    def _store_artist_binding(self, local_name, profile, context=None):
        from services.artist_identity import binding_key, name_key
        source, sid = profile.get('source'), profile.get('source_id') or profile.get('channel_id')
        if source not in ('youtube', 'itunes', 'deezer') or not sid or not profile.get('name'):
            return
        with self._window_op_lock:
            existing = self._core.settings.get('personalization', 'artist_bindings', {})
            bindings = dict(existing) if isinstance(existing, dict) else {}
            binding = {'local_name': local_name, 'canonical_name': profile['name'], 'catalog_ids': {source: str(sid)}}
            if isinstance(context, dict) and context.get('source') and context.get('source_id'):
                binding['context'] = {'source': str(context['source']), 'source_id': str(context['source_id'])}
            bindings[binding_key(local_name, context)] = binding
            if not binding.get('context'):
                bindings[name_key(profile['name'])] = dict(binding)
            self._core.settings.set('personalization', 'artist_bindings', bindings)

    def remove_artist_binding(self, local_name: str, context=None):
        """Remove a stored homonym artist binding by local name and optional context."""
        from services.artist_identity import binding_key, name_key
        if not local_name:
            return {'success': False, 'error': 'Имя исполнителя не указано'}
        with self._window_op_lock:
            existing = self._core.settings.get('personalization', 'artist_bindings', {})
            if not isinstance(existing, dict):
                return {'success': True, 'removed': False}
            bindings = dict(existing)
            bkey = binding_key(local_name, context)
            nkey = name_key(local_name)
            removed = False
            if bkey in bindings:
                bindings.pop(bkey, None)
                removed = True
            if not context and nkey in bindings:
                bindings.pop(nkey, None)
                removed = True
            for k in list(bindings.keys()):
                entry = bindings[k]
                if isinstance(entry, dict):
                    if entry.get('local_name') == local_name:
                        if context is None or entry.get('context') == context:
                            bindings.pop(k, None)
                            removed = True
            if removed:
                self._core.settings.set('personalization', 'artist_bindings', bindings)
            return {'success': True, 'removed': removed}

    def get_artist_profile(self, artist_name: str, artist_ref=None, request_id=None):
        import uuid
        name = str(artist_name or '').strip()
        rid = str(request_id or uuid.uuid4().hex)
        with self._window_op_lock:
            self._artist_request_id = rid
        def current():
            with self._window_op_lock:
                return not getattr(self, '_closed', False) and getattr(self, '_artist_request_id', None) == rid
        def fail(message):
            if not current():
                return
            data = dict(message) if isinstance(message, dict) else {'status': 'unavailable', 'error': describe_error(message)['message']}
            if data.get('error'):
                data['error'] = describe_error(data['error'])['message']
            self._emit('artist_profile_error', dict(data, artist=name, request_id=rid))
        svc = getattr(self._core, 'artists', None)
        if not name or svc is None:
            fail({'status': 'not_found' if not name else 'unavailable', 'error': 'Имя исполнителя не указано' if not name else 'Сервис исполнителей недоступен'})
            return {'status': 'loading', 'artist': name, 'request_id': rid}
        def ok(profile):
            if not current():
                return
            result = dict(profile, request_id=rid, artist=name, context=artist_ref.get('context') if isinstance(artist_ref, dict) else None)
            result.setdefault('status', 'found')
            # S4-001: echo the query-as-artist marker so the UI can show the
            # real search results under the candidate list.
            result['require_candidates'] = bool(isinstance(artist_ref, dict) and artist_ref.get('require_candidates'))
            if result['status'] == 'found' and isinstance(artist_ref, dict) and artist_ref.get('source_id'):
                self._store_artist_binding(name, result, artist_ref.get('context'))
            self._emit('artist_profile_ready', result)
            if result['status'] == 'ambiguous' and result.get('candidates') and hasattr(svc, 'catalog'):
                def preview():
                    candidates = svc.catalog.preview_artists(result['candidates'], current)
                    if current():
                        self._emit('artist_candidates_ready', {'request_id': rid, 'artist': name, 'candidates': candidates, 'context': result.get('context')})
                self._search_executor.submit(preview)
        try:
            svc.get_profile(name, callback=ok, error_callback=fail, artist_ref=artist_ref, is_current=current)
        except TypeError:
            svc.get_profile(name, callback=ok, error_callback=fail)
        return {'status': 'loading', 'artist': name, 'request_id': rid}

    def get_canonical_artist_names(self, names):
        """Resolve a batch of displayed artist credits with the shared identity rules."""
        if not isinstance(names, (list, tuple)):
            return []
        from services.artist_identity import artist_aliases, canonical_artist
        aliases = artist_aliases(getattr(self._core, 'settings', None))
        return [canonical_artist(name, aliases) if isinstance(name, str) else ''
                for name in names[:500]]

    def get_artist_tracks_page(self, artist_ref, offset=0):
        if not isinstance(artist_ref, dict):
            return {'success':False,'error':'Неверный ID исполнителя'}
        service=getattr(self._core,'artists',None)
        if service is None:
            return {'success':False,'error':'Сервис исполнителей недоступен'}
        with self._window_op_lock:
            request_id=getattr(self,'_artist_request_id',None)
        def current():
            with self._window_op_lock:
                return not getattr(self,'_closed',False) and getattr(self,'_artist_request_id',None)==request_id
        try:
            return dict(service.get_tracks_page(dict(artist_ref),offset,is_current=current),success=True)
        except Exception:
            return {'success':False,'error':'Не удалось загрузить каталог. Повторите попытку.'}

    def get_artists_avatars(self, names):
        """Resolve avatar photos for a batch of artist names (home feed).

        One artist-search round trip per unknown name, cached for a week.
        Delivered through the artists_avatars_ready event as {"avatars": {name: url}}.
        """
        if not isinstance(names, (list, tuple)):
            return {"status": "error", "error": "names must be a list"}
        svc = getattr(self._core, "artists", None)
        if svc is None:
            return {"status": "error", "error": "Сервис исполнителей недоступен"}

        def current():
            # Independent home shelves can request different artist batches.
            # A later batch must not cancel photos for the earlier shelf.
            return not getattr(self, '_closed', False)
        def _done(mapping):
            if current():
                self._emit('artists_avatars_ready', {'avatars':mapping or {}})

        try:
            options = {'callback':_done}
            if 'is_current' in inspect.signature(svc.get_avatars).parameters:
                options['is_current'] = current
            if 'hints' in inspect.signature(svc.get_avatars).parameters:
                requested = {n.strip() for n in names if isinstance(n, str)}
                hints = {}
                source_tracks = {}
                for track in self._core.db.get_history(limit=500) or []:
                    artist = (track.get('artist') or '').strip()
                    if artist in requested and track.get('title'):
                        hints.setdefault(artist, track['title'])
                        if track.get('source') in ('soundcloud', 'youtube'):
                            source_tracks.setdefault(artist, []).append(track)
                options['hints'] = hints
                if 'source_tracks' in inspect.signature(svc.get_avatars).parameters:
                    options['source_tracks'] = source_tracks
                    options['metadata_loader'] = lambda track: (
                        self._core.youtube.get_artist_avatar_metadata(track.get('source_id') or '')
                        if track.get('source') == 'youtube' else
                        self._core.soundcloud.get_track_metadata(track.get('source_id') or track.get('source_url') or ''))
            svc.get_avatars([n[:200] for n in names if isinstance(n,str)][:30], **options)
        except Exception as exc:
            logger.warning("get_artists_avatars failed: %s", type(exc).__name__)
            return {"status": "error", "error": describe_error(exc)['message']}
        return {"status": "loading"}

    def get_recommendations(self, track_data, max_results=10, request_id=None):
        import uuid
        rid = str(request_id or uuid.uuid4().hex)
        count = max(0, min(100, int(max_results)))
        def publish(tracks=None, error=None):
            payload = {'request_id': rid, 'tracks': (tracks or [])[:count]}
            if error:
                payload['error'] = describe_error(error, 'recommendations')['message']
            self._emit('recommendations_ready', payload)
        try:
            self._core.recommendations.get_recommendations(track_data, max_results=count,
                callback=publish, error_callback=lambda error: publish(error=error))
        except Exception as exc:
            publish(error=exc)
        return {'status':'pending', 'request_id':rid}

    def get_track_wave(self, track_data: dict, limit: int = 15, exclude_ids: list = None, request_id=None):
        """Get smart wave / radio of related tracks for a seed track (async, O-4).

        Returns [] immediately; results are delivered via the track_wave_ready event.
        request_id is optional and echoed so a replaced wave can ignore late results.
        """
        def publish(tracks=None, error=None):
            payload = {"tracks": tracks or []}
            if request_id is not None:
                payload["request_id"] = request_id
            if error:
                payload["error"] = describe_error(error)['message']
            self._emit("track_wave_ready", payload)

        if not track_data or not isinstance(track_data, dict):
            publish(error="Трек для волны не выбран")
            return []
        try:
            self._core.recommendations.get_wave_for_track(
                track_data, limit=limit, exclude_ids=exclude_ids or [],
                callback=lambda tracks: publish(tracks),
                error_callback=lambda e: publish(error=e),
            )
        except Exception as e:
            logger.error(f"Error in get_track_wave: {type(e).__name__}")
            publish(error=e)
        return []

    def get_waveform(self, track_data):
        if not isinstance(track_data, dict):
            return []
        url = str(track_data.get('waveform_url') or '')
        if not url or len(url) > 4096:
            return []
        with self._search_lock:
            for key, pending in tuple(self._waveform_flights.items()):
                if pending.done():
                    self._waveform_flights.pop(key, None)
            cached = self._waveform_cache.get(url)
            if cached and time.monotonic() - cached[0] < 3600:
                return list(cached[1])
            future = self._waveform_flights.get(url)
            if future is None:
                if len(self._waveform_flights) >= 4:
                    return []
                def fetch():
                    if not safe_public_url(url):
                        return []
                    return self._core.soundcloud.get_waveform_data_sync(url)
                future = self._metadata_executor.submit(fetch)
                self._waveform_flights[url] = future
        try:
            values = future.result(timeout=4)
            peaks = [max(0, min(1, float(value))) for value in (values or [])[:1000] if _as_float(value) is not None]
            with self._search_lock:
                self._waveform_flights.pop(url, None)
                self._waveform_cache[url] = (time.monotonic(), peaks)
                while len(self._waveform_cache) > 64:
                    self._waveform_cache.pop(next(iter(self._waveform_cache)))
            return peaks
        except Exception:
            with self._search_lock:
                if future.done():
                    self._waveform_flights.pop(url, None)
            return []

    def _clean_stream_cache(self, max_size_mb=None, max_age_hours=None):
        """CacheManager alone owns eviction and its protected-file policy."""
        cache = getattr(self._core, 'cache', None)
        if cache:
            return cache.purge_stream_cache()
        return 0

    def prefetch_track(self, track_data: dict):
        """Background pre-caching / stream resolution for seamless instant next track switching."""
        if not track_data or not isinstance(track_data, dict):
            return False
        source, source_id = track_data.get('source'), track_data.get('source_id')
        if source == 'local':
            return True
        if not source or not source_id:
            return False
        key = (str(source), str(source_id))
        with self._search_lock:
            if key in self._prefetch_pending:
                return True
            if len(self._prefetch_pending) >= 2:
                return False
            self._prefetch_pending.add(key)
        # The resolver may annotate candidates; a warmup must never mutate the
        # frontend queue object or start playback/listening accounting.
        candidate = dict(track_data)
        def _prefetch_task():
            try:
                self._core.engine.resolve_stream_url(candidate)
                # Cache pruning is throttled: it used to run a full scandir of the
                # streams directory on every single track change. Do this AFTER
                # warming so disk housekeeping cannot delay the playable URL.
                now = time.monotonic()
                with self._search_lock:
                    prune = now - getattr(self, "_last_stream_clean", 0.0) > 600.0
                    if prune:
                        self._last_stream_clean = now
                if prune:
                    self._clean_stream_cache()
            except Exception as e:
                logger.debug(f"Prefetch task ignored error: {type(e).__name__}")
            finally:
                with self._search_lock:
                    self._prefetch_pending.discard(key)
        try:
            self._prefetch_executor.submit(_prefetch_task)
        except RuntimeError:
            with self._search_lock:
                self._prefetch_pending.discard(key)
            return False
        return True

    def download_all_favorites(self):
        """Download all favorite tracks for offline playback with disk space validation and batch progress."""
        try:
            favs = self._core.db.get_favorite_tracks() or []
            if not favs:
                return {"success": False, "message": "В избранном нет треков для загрузки"}

            to_download = [track for track in favs if track.get('source') in ('youtube','soundcloud','yandex','spotify','deezer','vk')
                           and not os.path.isfile(str(track.get('file_path') or ''))]
            if not to_download:
                return {"success": True, "count": 0, "total": len(favs), "message": "Все любимые треки уже скачаны!"}

            from core.download_processing import download_directory
            from pathlib import Path
            app_dir = Path(download_directory(self._core.settings))
            while not app_dir.exists() and app_dir != app_dir.parent:
                app_dir = app_dir.parent
            total, used, free = shutil.disk_usage(str(app_dir))
            needed_bytes = len(to_download) * 5 * 1024 * 1024
            if free < needed_bytes:
                free_mb = free / (1024 * 1024)
                needed_mb = needed_bytes / (1024 * 1024)
                return {
                    "success": False,
                    "message": f"Недостаточно места на диске. Нужно ~{int(needed_mb)} МБ, доступно {int(free_mb)} МБ"
                }

            if hasattr(self._core, "downloader"):
                self._core.downloader.start_batch(len(to_download))

            # Announce the batch BEFORE anything is queued: with a fast pool the
            # per-track batch_download_progress events emitted by
            # queue_download() used to reach the frontend first, and a UI that
            # initializes its counter from batch_download_started then reset it
            # to the progress values.
            self._emit("batch_download_started", {"total": len(to_download), "current": 0})

            with self._window_op_lock:
                self._queue_events_suspended = getattr(self, '_queue_events_suspended', 0) + 1
            try:
                for track in to_download:
                    self.download_track(track)
            finally:
                with self._window_op_lock:
                    self._queue_events_suspended -= 1
                    publish = self._queue_events_suspended == 0
                if publish:
                    self._emit('download_queue_updated', {'status':'pending','bulk':True})

            return {
                "success": True,
                "count": len(to_download),
                "total": len(favs),
                "message": f"Добавлено в очередь на скачивание: {len(to_download)} треков"
            }
        except Exception as e:
            logger.error(f"Error in download_all_favorites: {type(e).__name__}")
            return {"success": False, "message": f"Ошибка скачивания: {type(e).__name__}"}

    def cancel_batch_download(self):
        """Cancel ongoing batch download and clear remaining queue."""
        try:
            if hasattr(self._core, "downloader"):
                return self._core.downloader.cancel_batch()
            return True
        except Exception as e:
            logger.error(f"Error cancelling batch download: {type(e).__name__}")
            return False

    def get_feed(self, max_results: int = 20, request_id=None):
        """Request recommendations without blocking the UI bridge."""
        max_results = max(0, min(100, int(max_results)))
        history = self._core.db.get_history(limit=30) or []
        def publish(tracks, error=None):
            items = (tracks or [])[:max_results]
            payload = {"request_id": str(request_id), "tracks": items} if request_id is not None else items
            if error and isinstance(payload, dict):
                payload['error'] = describe_error(error, 'recommendations')['message']
            self._emit("feed_ready", payload)
        try:
            self._core.recommendations.get_feed(
                history, max_results=max_results, callback=publish,
                error_callback=lambda error: publish([], error),
            )
        except Exception as exc:
            logger.info("Feed fallback: %s", type(exc).__name__)
            publish([], exc)
        return {"request_id": str(request_id), "status": "pending"} if request_id is not None else []

    def get_home_artists(self, max_results: int = 10, request_id=None):
        """Return top artists and tag async UI responses with their request ID."""
        max_results = max(0, min(100, int(max_results)))
        artists = self._core.db.get_top_artists(limit=max_results) or []
        payload = {"request_id": str(request_id), "artists": artists} if request_id is not None else artists
        self._emit("artists_ready", payload)
        return payload

    def get_home_releases(self, max_results: int = 10, request_id=None):
        """Request new releases and publish a request-tagged fallback on failure."""
        max_results = max(0, min(100, int(max_results)))
        def publish(tracks, error=None):
            items = (tracks or [])[:max_results]
            payload = {"request_id": str(request_id), "tracks": items} if request_id is not None else items
            if error and isinstance(payload, dict):
                payload['error'] = describe_error(error, 'recommendations')['message']
            self._emit("releases_ready", payload)
        try:
            artists = [
                row.get("artist") or row.get("name")
                for row in (self._core.db.get_top_artists(limit=5) or [])
            ]
            self._core.recommendations.get_releases(
                [artist for artist in artists if artist], max_results=max_results,
                callback=publish, error_callback=lambda error: publish([], error),
            )
        except Exception as exc:
            logger.info("Releases fallback: %s", type(exc).__name__)
            publish([], exc)
        return {"request_id": str(request_id), "status": "pending"} if request_id is not None else []

    def get_home_mixes(self, max_results: int = 10, request_id=None, refresh=False):
        """Request generated mixes and publish a request-tagged fallback on failure."""
        max_results = max(0, min(100, int(max_results)))
        if refresh is True:
            self._core.recommendations.reset_service()
        history = self._core.db.get_history(limit=30) or []
        def publish(tracks, error=None):
            items = (tracks or [])[:max_results]
            payload = {"request_id": str(request_id), "tracks": items} if request_id is not None else items
            if error and isinstance(payload, dict):
                payload['error'] = describe_error(error, 'recommendations')['message']
            self._emit("mixes_ready", payload)
        try:
            self._core.recommendations.get_mixes(
                history, max_results=max_results, callback=publish,
                error_callback=lambda error: publish([], error),
            )
        except Exception as exc:
            logger.info("Mixes fallback: %s", type(exc).__name__)
            publish([], exc)
        return {"request_id": str(request_id), "status": "pending"} if request_id is not None else []

    def _emit_zapret_event(self, event_name: str, payload=None):
        """Translate ZapretService hook events into bridge events.

        Runs on service threads; _emit is queue-backed and drops everything
        once the app is closing, so a failure here is never fatal."""
        try:
            self._emit(event_name, payload if payload is not None else {})
        except Exception:
            logger.debug("zapret event %s could not be emitted", event_name, exc_info=True)

    def toggle_zapret(self, enabled: bool, mode: str = "youtube_discord", custom_args: str = "", binary_path: str = ""):
        """Toggle DPI bypass Zapret service."""
        try:
            if enabled:
                success, msg = self._core.zapret.start(mode=mode, custom_args=custom_args, binary_path=binary_path)
            else:
                success, msg = self._core.zapret.stop()
            # BUG-009: `enabled` must reflect the ACTUAL process state. The old
            # `enabled and success` wrote False while a failed stop left an
            # elevated winws running, desyncing settings from reality (and
            # hiding the live bypass from the next autostart decision).
            is_running = self._core.zapret.is_running()
            self._core.settings.set("zapret", "enabled", is_running)
            self._core.settings.set("zapret", "mode", mode)
            self._core.settings.set("zapret", "custom_args", custom_args or "")
            self._core.settings.set("zapret", "binary_path", binary_path or "")
            return {
                "success": success,
                "running": is_running,
                "enabled": is_running,
                "message": msg,
                "error": None if success else msg
            }
        except Exception as e:
            # Same honesty contract as the happy path (BUG-009): report the
            # ACTUAL process state instead of assuming the toggle changed
            # nothing — the start/stop above may have landed before raising.
            try:
                actually_running = bool(self._core.zapret.is_running())
            except Exception:
                actually_running = False
            return {"success": False, "running": actually_running, "enabled": actually_running,
                    "error": describe_error(e)['message'], "message": describe_error(e)['message']}

    def toggle_discord_rpc(self, enabled: bool):
        """Toggle Discord Rich Presence integration."""
        if not isinstance(enabled, bool):
            return {"success": False, "error": "Некорректное значение переключателя"}
        with self._window_op_lock:
            previous = self._core.settings.get("app", "discord_rpc_enabled", False)
            if not self._store_setting('app', 'discord_rpc_enabled', enabled):
                return {"success": False, "enabled": previous,
                        "error": "Не удалось сохранить настройки Discord"}
            service = getattr(self._core, 'discord_rpc', None)
            try:
                if service:
                    if enabled:
                        service.start()
                        # Reuse the selected deck's position/rate; enabling RPC
                        # mid-song must not reset its timer or invent playback.
                        self._discord_sync(getattr(self, '_last_reported_state', 'stopped'))
                    else:
                        service.stop()
                return {"success": True, "enabled": enabled}
            except Exception as e:
                self._store_setting('app', 'discord_rpc_enabled', previous)
                try:
                    if service:
                        service.start() if previous else service.stop()
                except Exception:
                    logger.debug('Discord state restore failed', exc_info=True)
                logger.error(f"Error toggling Discord RPC: {type(e).__name__}")
                return {"success": False, "enabled": previous, "error": describe_error(e)['message']}

    def get_discord_rpc_status(self):
        """Get Discord Rich Presence status."""
        enabled = self._core.settings.get("app", "discord_rpc_enabled", False)
        service = getattr(self._core, 'discord_rpc', None)
        if service and hasattr(service, 'get_status'):
            return service.get_status()
        connected = getattr(service, 'connected', False)
        return {"enabled": enabled, "connected": connected,
                "state": 'CONNECTED' if connected else ('DISCONNECTED' if enabled else 'DISABLED')}

    def get_zapret_status(self):
        """Get current Zapret service status."""
        try:
            status = self._core.zapret.get_status()
            status["mode"] = self._core.settings.get("zapret", "mode", "youtube_discord")
            status["enabled"] = self._core.settings.get("zapret", "enabled", False)
            status["auto_start"] = self._core.settings.get("zapret", "auto_start", False)
            status["autoupdate"] = self._core.settings.get("zapret", "autoupdate", False)
            status["custom_args"] = self._core.settings.get("zapret", "custom_args", "")
            status["binary_path"] = self._core.settings.get("zapret", "binary_path", "")
            return status
        except Exception as e:
            return {"running": False, "enabled": False, "auto_start": False, "mode": "youtube_discord", "error": describe_error(e)['message'], "binary_found": False}

    def check_zapret_update(self, request_id=None):
        """Check the release service outside the bridge and correlate completion."""
        import uuid
        rid = str(request_id or uuid.uuid4().hex)
        with self._window_op_lock:
            pending = getattr(self, '_zapret_check_future', None)
            if pending is not None and not pending.done():
                # BUG-020: report the ACTIVE request id, not the caller's. The
                # completion event carries the rid captured at submit time, so
                # the UI must correlate against it to keep waiting instead of
                # timing out on an id the event will never use.
                return {'status': 'busy',
                        'request_id': str(getattr(self, '_zapret_check_request_id', '') or rid)}

            def check():
                try:
                    result = dict(self._core.zapret.check_for_updates() or {})
                except Exception as exc:
                    result = {'update_available': False, 'error': describe_error(exc, 'zapret')['message']}
                self._emit('zapret_update_checked', dict(result, request_id=rid))

            self._zapret_check_request_id = rid
            self._zapret_check_future = self._metadata_executor.submit(check)
        return {'status': 'pending', 'request_id': rid}

    def update_zapret(self, force: bool = False):
        """Update Zapret binary bundle to latest version."""
        try:
            success, msg = self._core.zapret.update_zapret(force=force)
            status = self._core.zapret.get_status()
            return {"success": success, "message": msg, "status": status}
        except Exception as e:
            return {"success": False, "message": f"Ошибка обновления: {type(e).__name__}", "error": describe_error(e)['message']}

    def find_duplicate_tracks(self):
        """Scan local tracks and return duplicate track groups with identical file content."""
        try:
            return self._core.audio_fingerprint.find_duplicates(self._core.db)
        except Exception as e:
            logger.error(f"Error finding duplicate tracks: {type(e).__name__}")
            return []

    def delete_duplicate_track(self, track_id: int, delete_file: bool = False, keeper_id=None):
        """Merge only a verified exact-file duplicate and preserve its keeper."""
        try:
            track = self._core.db.get_track(track_id)
            path = (track or {}).get('file_path')
            success = self._core.audio_fingerprint.delete_duplicate_track(
                self._core.db, track_id, delete_file=delete_file, keeper_id=keeper_id)
            if not success:
                return {'success': False, 'error': 'Подтверждённая идентичная копия не найдена'}
            self._emit('library_updated', True)
            owners = []
            if delete_file and path and os.path.isfile(path):
                owners = [row for row in self._core.db.get_all_tracks()
                          if row.get('file_path') and os.path.normcase(os.path.realpath(row['file_path'])) == os.path.normcase(os.path.realpath(path))]
                if not owners:
                    return {'success': False, 'partial': True, 'error': 'Запись объединена, но файл остался на диске'}
            return {'success': True}
        except Exception as exc:
            return {'success': False, 'error': describe_error(exc, 'duplicate')['message']}

    def update_track_tags(self, track_id, tags):
        if not isinstance(tags, dict):
            return {'success': False, 'error': 'Некорректные теги'}
        track = self._core.db.get_track(int(track_id))
        if not track:
            return {'success': False, 'error': 'Трек не найден'}
        values = {key: str(tags[key] or '').strip() if key in tags else str(track.get(key) or '')
                  for key in ('title','artist','album','genre')}
        if not values['title'] or not values['artist'] or any(len(value) > 2000 for value in values.values()):
            return {'success': False, 'error': 'Укажите название и исполнителя'}
        clear_year = 'year' in tags and (tags['year'] is None or not str(tags['year']).strip())
        raw_year = tags.get('year', track.get('year'))
        year = None if clear_year or raw_year is None else int(str(raw_year).strip())
        if year is not None and not 1 <= year <= 9999:
            return {'success': False, 'error': 'Некорректный год'}
        cover_bytes, cover_mime, cover_path = None, 'image/jpeg', track.get('cover_path')
        selected = tags.get('cover_path') or tags.get('cover_file')
        if selected:
            selected = os.path.realpath(str(selected))
            stat = os.stat(selected)
            approved = getattr(self, '_approved_cover_paths', {}).get(selected)
            if approved != (stat.st_size, stat.st_mtime_ns):
                return {'success': False, 'error': 'Выберите изображение через диалог обложки'}
            cover_bytes, cover_mime = self._read_cover_image(selected)
        path = track.get('file_path')
        if path and os.path.isfile(path):
            from utils.tag_parser import write_tags
            if not write_tags(path, **values, year=year if 'year' in tags else None,
                              clear_year=clear_year, cover_bytes=cover_bytes, cover_mime=cover_mime):
                return {'success': False, 'error': 'Не удалось сохранить теги аудиофайла'}
        if cover_bytes:
            from utils.tag_parser import save_cover_to_file
            folder = os.path.expanduser('~/.nedotify/covers')
            cover_path = save_cover_to_file(cover_bytes, cover_mime, folder, int(track_id))
            if not cover_path:
                return {'success': False, 'error': 'Не удалось сохранить обложку'}
        if not self._core.db.update_track_metadata(int(track_id), **values, year=year, cover_path=cover_path):
            return {'success': False, 'error': 'Не удалось обновить запись в библиотеке'}
        if clear_year:
            self._core.db.update_track(int(track_id), year=None)
        updated = self._core.db.get_track(int(track_id))
        self._emit('library_updated', True)
        self._emit('track_updated', updated)
        return {'success': True, 'track': updated}

    def choose_cover_image(self):
        if not self._window:
            return {'success': False, 'error': 'Окно недоступно'}
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
            file_types=('Изображения (*.jpg;*.jpeg;*.png;*.webp)',))
        if not result:
            return {'success': False, 'cancelled': True}
        path = os.path.realpath(str(result[0]))
        self._read_cover_image(path)
        stat = os.stat(path)
        with self._window_op_lock:
            approved = getattr(self, '_approved_cover_paths', {})
            approved[path] = (stat.st_size, stat.st_mtime_ns)
            while len(approved) > 16:
                approved.pop(next(iter(approved)))
            self._approved_cover_paths = approved
        return {'success': True, 'path': path}

    def get_storage_details(self):
        return self._storage_metrics()

    def set_cache_quota(self, quota_gb=None, cache_size_mb=None, cache_quota_gb=None):
        for value in (quota_gb, cache_size_mb, cache_quota_gb):
            if value is not None and (isinstance(value, bool) or _as_float(value) is None or float(value) < 0):
                return {'success': False, 'error': 'Некорректный размер кэша'}
        gb, _ = _normalize_cache_quota(quota_gb, cache_size_mb, cache_quota_gb)
        if gb is None:
            return {'success': False, 'error': 'Не указан размер кэша'}
        quota = 0 if gb == 0 else max(1, round(gb))
        if not self._store_settings([('storage', 'cache_quota_gb', quota),
                                     ('storage', 'cache_size_mb', quota * 1024)]):
            return {'success': False, 'error': 'Не удалось сохранить размер кэша'}
        cache = getattr(self._core, 'cache', None)
        freed = cache.purge_stream_cache(quota_bytes=quota*1024**3) if cache and quota else 0
        self._storage_metrics_cache = None
        self._storage_info_cache = None
        details = self.get_storage_details()
        self._emit('storage_updated', details)
        return {'success': True, 'freed_bytes': freed, 'details': details}

    def clear_storage_cache(self):
        if not self.clear_storage('cache'):
            return {'success': False, 'error': 'Кэш недоступен'}
        details = self.get_storage_details()
        self._emit('storage_updated', details)
        return {'success': True, 'details': details}

    def get_offline_library(self):
        return offline_library(self._core.db)

    def recover_stream(self, track, position_ms=0):
        from core.playback_recovery import recover_stream
        return recover_stream(self._core, track, position_ms)

    def get_downloads(self):
        downloads = self._core.downloader.get_downloads()
        for item in downloads:
            if item.get('status') == 'failed':
                item['user_error'] = describe_error(item.get('error'), 'download')
                if item.get('error_code') in ('missing_yt_dlp', 'missing_ffmpeg', 'missing_ffprobe', 'dependencies_busy', 'lossy_source'):
                    item['user_error'] = {'code': item['error_code'], 'message': item.get('error'), 'action': 'setup'}
                item['error'] = item['user_error']['message']
        return downloads

    def pause_download(self, track_id=None):
        return self._core.downloader.pause_download(track_id)

    def resume_download(self, track_id=None):
        return self._core.downloader.resume_download(track_id)

    def retry_failed_downloads(self):
        return self._core.downloader.retry_failed_downloads()

    def cancel_download(self, track_id):
        return self._core.downloader.cancel_download(track_id)

    def download_tracks(self, tracks):
        """Admit a collection through the same persistent per-track queue."""
        if not isinstance(tracks, list) or len(tracks) > 5000:
            return {'success': False, 'message': 'Выберите от 1 до 5000 треков'}
        candidates = [track for track in tracks if isinstance(track, dict)
                      and track.get('source') not in (None, 'local') and track.get('source_id')
                      and not os.path.isfile(str(track.get('file_path') or ''))]
        if not candidates:
            return {'success': True, 'count': 0, 'message': 'Нет новых треков для скачивания'}
        self._core.downloader.start_batch(len(candidates))
        self._emit('batch_download_started', {'total': len(candidates), 'current': 0})
        with self._window_op_lock:
            self._queue_events_suspended = getattr(self, '_queue_events_suspended', 0) + 1
        try:
            count = sum(int(bool(self.download_track(track))) for track in candidates)
        finally:
            with self._window_op_lock:
                self._queue_events_suspended -= 1
            self._emit('download_queue_updated', {'status': 'pending', 'bulk': True})
        return {'success': True, 'count': count, 'message': f'Добавлено в очередь: {count}'}

    def download_playlist(self, playlist_id, source='local'):
        result = self.get_playlist_tracks(playlist_id, source, limit=5000)
        if isinstance(result, dict) and not result.get('success', True):
            return result
        return self.download_tracks(result.get('tracks', []) if isinstance(result, dict) else result)

    def retry_download(self, track_id):
        return self._core.downloader.retry_download(track_id)

    def get_setup_status(self, deep=False, check_sources=False):
        return self._core.setup.get_status(deep=bool(deep), check_sources=bool(check_sources))

    def repair_setup_tools(self, tools=None, update=False):
        return self._core.setup.start_repair(tools=tools, update=bool(update))

    def cancel_setup(self):
        return self._core.setup.cancel()

    def configure_setup(self, options):
        result = self._core.setup.configure(options)
        if result.get('success') and options.get('library_directory'):
            path = os.path.realpath(options['library_directory'])
            self._core.db.add_scan_folder(path)
            scanner = getattr(self._core, 'scanner', None)
            with self._window_op_lock:
                if scanner and not getattr(scanner, '_scanning', False):
                    scanner.on_progress(lambda current, total, _path: self._emit('scan_progress', {'current': current, 'total': total}))
                    scanner.on_complete(lambda tracks: (self._emit('scan_complete', {'success': True, 'count': len(tracks or [])}), self._emit('library_updated', True)))
                    result['scan_started'] = bool(scanner.scan_folder(path))
                else:
                    result['scan_started'] = False
            watchdog = getattr(self._core, 'watchdog', None)
            if watchdog and getattr(watchdog, '_started', False):
                watchdog._sync_folders()
        return result

    def check_setup_updates(self):
        return self._core.setup.check_updates()

    def select_setup_directory(self, kind='download'):
        if kind not in ('download', 'library') or not self._window:
            return {'success': False, 'message': 'Окно выбора папки недоступно'}
        import webview
        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return {'success': bool(selected), 'path': str(selected[0]) if selected else ''}

    def get_search_suggestions(self, query):
        from utils.search_query import suggest_search_queries
        return suggest_search_queries(self._core.db, query)

    def get_listening_comparison(self, period='week', utc_offset_minutes=180, timezone_name=None):
        from services.listening_comparison import listening_comparison
        offset = _as_float(utc_offset_minutes)
        if offset is None or not -720 <= offset <= 840:
            raise ValueError('Invalid UTC offset')
        if timezone_name is not None and (not isinstance(timezone_name, str) or len(timezone_name) > 100):
            raise ValueError('Invalid timezone')
        return listening_comparison(self._core.db, period, int(offset), timezone_name=timezone_name)

    def frontend_heartbeat(self, state='visible'):
        """Liveness pulse from the renderer.

        WebView2 occasionally stalls its compositor while the process stays
        alive - the user sees a solid window-background-colored screen (the
        "black screen" reports) with no crash logged anywhere. The runtime
        watchdog in main.py compares this timestamp against real time and
        reloads the renderer when the pulse stops while the page is visible.
        """
        self._ui_heartbeat_monotonic = time.monotonic()
        self._ui_visibility = 'hidden' if state == 'hidden' else 'visible'
        return True

    def ui_ready(self, renderer_id=None):
        """Replay durable state only after frontend subscribers are installed."""
        with self._playback_guard():
            first = not self._ui_ready_event.is_set()
            changed = renderer_id is not None and renderer_id != getattr(self, '_renderer_id', None)
            self._renderer_id = renderer_id
            self._ui_ready_event.set()
            if first or changed:
                queue = getattr(getattr(self._core, 'engine', None), 'queue', None)
                if queue and queue.current_track:
                    if not first:
                        self._restore_position_sec = max(0, getattr(self._core.engine, '_last_reported_position', 0) or 0)
                        self._restore_autoplay = getattr(self, '_last_reported_state', '') == 'playing'
                    self._restoring_session = True
                    self._on_track_changed(dict(queue.current_track))
                self._notify_queue_updated()
            return {'success': True, 'playback_epoch': self._playback_epoch}

    def filter_artist_tracks(self, tracks, artist_name):
        from services.artist_identity import canonical_artist, artist_aliases
        aliases = artist_aliases(self._core.settings)
        artist = canonical_artist(artist_name, aliases)
        return [dict(track) for track in (tracks or []) if isinstance(track, dict)
            and canonical_artist(track.get('artist'), aliases) == artist]

    def cancel_search(self):
        with self._search_lock:
            self._search_generation += 1
            for future in self._search_futures:
                future.cancel()
            self._search_futures.clear()
            for timer in self._search_timers:
                timer.cancel()
            self._search_timers.clear()
        return True

    def _playback_guard(self):
        return getattr(self._core.engine, 'command_lock', self._window_op_lock)

    def _set_native_icon(self):
        if os.environ.get('PYTEST_CURRENT_TEST') or not self._window:
            return
        try:
            import clr
            clr.AddReference('System.Drawing')
            from System.Drawing import Icon
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            icon_path = os.path.join(base, 'icon.ico')
            if os.path.isfile(icon_path):
                window = self._window
                self._on_window_ui_thread(window, lambda: setattr(window.native, 'Icon', Icon(icon_path)))
        except Exception:
            logger.warning('Could not set native icon', exc_info=True)

    def clear_listening_history(self, confirmed=False):
        """Erase listening/taste signals only after a dedicated UI confirmation."""
        if confirmed is not True:
            return {'success': False, 'confirmation_required': True}
        with self._window_op_lock:
            for session in self._listening_sessions.values():
                session.audible = False
                session.closed = True
            self._listening_sessions.clear()
            self._active_listening_token = None
            self._history_logged_key = None
            self._core.db.clear_listening_history()
            for key, value in {'last_queue': [], 'last_track_id': None, 'last_queue_index': 0, 'last_position': 0}.items():
                self._core.settings.set('session', key, value)
            recommendations = getattr(self._core, '_recommendations', None)
            if recommendations:
                recommendations.reset_service()
                clear = getattr(getattr(recommendations, 'lastfm', None), 'clear_response_cache', None)
                if callable(clear):
                    clear()
            from services.taste_profile import _profile_cache, _profile_cache_lock
            with _profile_cache_lock:
                _profile_cache.clear()
            current = getattr(self, '_current_track', None)
            token = None
            if isinstance(current, dict) and current:
                current.pop('listening_session', None)
                token = self._listening_for_track(current, force=True).token
                live = getattr(getattr(self._core, 'engine', None), 'queue', None)
                if live and live.current_track:
                    live.current_track['listening_session'] = token
        self._emit('listening_history_cleared', {'success': True, 'listening_session': token})
        self._emit('history_updated', {'cleared': True})
        return {'success': True}

    def import_music_folder(self):
        """Choose a local folder and start the registered scanner asynchronously."""
        if not self._window:
            return {'success': False, 'error': 'Окно недоступно'}
        scanner = self._core.scanner
        with self._window_op_lock:
            if getattr(scanner, '_scanning', False):
                return {'success': False, 'error': 'Дождитесь завершения текущего импорта'}
            selected = self._window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if not selected:
                return {'success': False, 'cancelled': True}
            path = os.path.realpath(str(selected[0]))
            if not os.path.isdir(path):
                return {'success': False, 'error': 'Папка недоступна'}
            scanner.on_progress(lambda current, total, _path:
                                self._emit('scan_progress', {'current': current, 'total': total}))
            def complete(tracks):
                if getattr(self, '_closed', False):
                    return
                self._core.db.add_scan_folder(path)
                watchdog = getattr(self._core, 'watchdog', None)
                if watchdog:
                    if getattr(watchdog, '_started', False):
                        watchdog._sync_folders()
                    else:
                        watchdog.start()
                self._emit('scan_complete', {'success': True, 'count': len(tracks or [])})
                self._emit('library_updated', True)
            scanner.on_complete(complete)
            if not scanner.scan_folder(path):
                return {'success': False, 'error': 'Не удалось начать импорт'}
            return {'success': True, 'pending': True, 'path': path}

    def _storage_metrics(self):
        cached = getattr(self, '_storage_metrics_cache', None)
        if cached and time.monotonic() - cached[0] < 15:
            return dict(cached[1])
        cache = getattr(self._core, 'cache', None)
        details = dict(cache.get_storage_details()) if cache else {
            'used_bytes': 0, 'total_cache_bytes': 0, 'quota_gb': 5,
            'quota_bytes': 5 * 1024**3, 'protected_count': 0}
        base = os.path.expanduser('~/.nedotify')
        def measure(folder):
            count, size = 0, 0
            for directory, dirs, files in os.walk(folder, followlinks=False):
                dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(directory,name))]
                for name in files:
                    path = os.path.join(directory,name)
                    try:
                        if not os.path.islink(path):
                            size += os.path.getsize(path)
                            count += 1
                    except OSError:
                        pass
            return count, size
        tracks_count, tracks_bytes = measure(os.path.join(base,'downloads'))
        covers_count, covers_bytes = measure(os.path.join(base,'covers'))
        total = details.get('total_cache_bytes', details.get('used_bytes',0)) + tracks_bytes
        details.update(total_bytes=total, total=round(total/1024**2,2), total_mb=round(total/1024**2,2),
            tracks={'count':tracks_count,'size':f'{tracks_bytes/1024**2:.2f} MB'},
            covers={'count':covers_count,'size':f'{covers_bytes/1024**2:.2f} MB'}, cache_dir=base)
        self._storage_metrics_cache = (time.monotonic(), dict(details))
        return details

    def _native_message_function(self):
        import ctypes
        from ctypes import wintypes
        library = ctypes.windll.user32
        if getattr(library, '_handle', None):
            return ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      ctypes.c_size_t, ctypes.c_ssize_t)(('SendMessageW', library))
        return library.SendMessageW

    def _read_cover_image(self, path):
        from PIL import Image
        import io
        if not os.path.isfile(path) or not 0 < os.path.getsize(path) <= 8*1024*1024:
            raise ValueError('Invalid cover image size')
        with open(path, 'rb') as source:
            data = source.read(8*1024*1024+1)
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('JPEG','PNG','WEBP','GIF') or image.width*image.height > 20_000_000:
                raise ValueError('Unsupported cover image')
            mime = Image.MIME[image.format]
            image.verify()
        return data, mime
