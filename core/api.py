"""
NeDotify - Web API Bridge
Exposes Python backend methods to the JavaScript frontend via pywebview.
"""


import hashlib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import webview

logger = logging.getLogger(__name__)

# Temporary feature flag: license validation and VK-based activation are disabled
# until they are replaced with a remote, server-owned licensing service.
LICENSE_VALIDATION_ENABLED = False

# Hard per-provider search deadline. Single source of truth: the docstring, the
# timer below and the test suite all read this constant.
PROVIDER_SEARCH_TIMEOUT = 4.0

# Total wall-clock budget for a bridge method that must answer synchronously.
# pywebview serves the call on a bridge thread and the JS caller is awaiting it, so
# a long block is felt as a frozen UI. Multi-stage lookups share this one budget
# instead of each stage getting its own timeout.
BRIDGE_SYNC_BUDGET = 6.0

# Window geometry: main window and compact mini player.
MAIN_WINDOW_SIZE = (1100, 800)
MINI_WINDOW_SIZE = (380, 110)


def _is_ssrf_safe_url(url: str) -> bool:
    """SSRF Protection: Validates URLs to prevent internal network scanning and SSRF."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False
        if hostname in ("localhost", "0.0.0.0", "::1"):
            return False

        # Check numeric integer IP representations (e.g. 2130706433 -> 127.0.0.1)
        if hostname.isdigit():
            try:
                num_ip = ipaddress.ip_address(int(hostname))
                if num_ip.is_loopback or num_ip.is_private or num_ip.is_link_local or num_ip.is_reserved or num_ip.is_multicast or num_ip.is_unspecified:
                    return False
            except Exception:
                return False

        # Check direct IP address (IPv4 / IPv6 / hex)
        try:
            direct_ip = ipaddress.ip_address(hostname)
            if direct_ip.is_loopback or direct_ip.is_private or direct_ip.is_link_local or direct_ip.is_reserved or direct_ip.is_multicast or direct_ip.is_unspecified:
                return False
        except Exception:
            logger.debug("_is_ssrf_safe_url: suppressed exception", exc_info=True)

        # Resolve all DNS records (IPv4 & IPv6)
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    return False
        except Exception:
            # If DNS resolution fails, fallback string check
            if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("127."):
                return False
        return True
    except Exception:
        return False


class AppApi:
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

        # C-2: lyrics cascade counter (verification: exactly one cascade per request)
        self._lyrics_cascade_count = 0
        self._lyrics_lock = threading.Lock()

        # Dedicated search executor for non-blocking provider and DB searches
        from concurrent.futures import ThreadPoolExecutor
        self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")

        # Connect engine event callbacks
        if hasattr(self._core, "engine") and self._core.engine:
            self._core.engine._on_track_changed = self._on_track_changed
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
                    try:
                        return func(inner_self, *args, **kwargs)
                    except Exception as exc:
                        logger.error(
                            "bridge call %s() failed: %s: %s",
                            method_name, type(exc).__name__, exc, exc_info=True,
                        )
                        try:
                            inner_self._emit("api_error", {
                                "method": method_name,
                                "error": f"{type(exc).__name__}: {exc}",
                            })
                        except Exception:
                            logger.debug("api_error emit failed", exc_info=True)
                        raise
                return _wrapped

            setattr(self, name, types.MethodType(_make(attr, name), self))

    def cleanup(self):
        """O-15: release the shared search executor without blocking app exit."""
        try:
            if getattr(self, "_tray", None):
                self._tray.stop()
        except Exception:
            logger.debug("cleanup: suppressed exception", exc_info=True)
        try:
            if getattr(self, "_search_executor", None) is not None:
                self._search_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.debug("cleanup: suppressed exception", exc_info=True)

    def set_window(self, window):
        """Set main webview window reference."""
        self._window = window
        self._main_window = window
        if hasattr(self._window, 'events'):
            self._window.events.minimized += self._on_minimized
            self._window.events.restored += self._on_restored

        if getattr(self, "_tray", None):
            self._tray.start()
            
        try:
            import threading
            def _set_icon():
                import time
                time.sleep(0.2)
                try:
                    if getattr(self._window, 'native', None):
                        import os
                        import clr
                        clr.AddReference('System.Drawing')
                        from System.Drawing import Icon
                        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico")
                        if os.path.exists(icon_path):
                            self._window.native.Icon = Icon(icon_path)
                except Exception as ex:
                    logger.warning(f"Could not set native window icon: {ex}")
            threading.Thread(target=_set_icon, daemon=True).start()
        except Exception:
            logger.debug("_set_icon: suppressed exception", exc_info=True)

    def _on_minimized(self):
        pass

    def _on_restored(self):
        pass

    def _get_scale_factor(self) -> float:
        """Logical-to-physical DPI scale of the window's current monitor.

        pywebview's move()/resize() take LOGICAL pixels and convert internally;
        every coordinate we compute must be in the same space or positioning
        breaks on any display scaled above 100%.
        """
        try:
            native = getattr(self._window, "native", None)
            scale = getattr(native, "_scale", None)
            if callable(scale):
                try:
                    scale = scale.fget(native) if hasattr(scale, "fget") else scale()
                except Exception:
                    scale = getattr(native, "_scale", None)
            val = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
            return val
        except Exception:
            logger.debug("_get_scale_factor fallback", exc_info=True)
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
            logger.debug(f"_logical_workarea failed: {e}")
            return None

    def _saved_pos_coords(self, pos: str, w: int, h: int):
        """Compute screen coordinates (logical px) for a mini-player position."""
        area = self._logical_workarea()
        if not area:
            return None
        ax, ay, aw, ah = area
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
        call deadlocks the WinForms UI thread (app freezes with "wait for
        response"). Running the op deferred on a daemon thread prevents that.
        """
        def _run():
            time.sleep(delay)
            try:
                with self._window_op_lock:
                    fn()
            except Exception as e:
                logger.debug(f"Deferred window op failed: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def toggle_mini_player(self, enable: bool):
        """Switch view between main window and mini player window."""
        logger.info(f"toggle_mini_player called with enable={enable}")
        try:
            self._is_mini_active = enable
            if enable:
                self._enter_mini_mode()
            else:
                self._exit_mini_mode()
            self._emit("mini_player_toggled", {"is_mini": enable})
            return {"success": True, "is_mini": enable}
        except Exception as e:
            logger.error(f"Error toggling mini player: {e}")
            # Frontend rolls its optimistic CSS state back on success=False.
            return {"success": False, "is_mini": not enable}

    def _enter_mini_mode(self):
        target_win = self._mini_window or self._window
        if not target_win:
            return
        try:
            # Save main window geometry to restore exactly upon exit
            self._saved_main_geometry = (
                getattr(target_win, 'width', MAIN_WINDOW_SIZE[0]) or MAIN_WINDOW_SIZE[0],
                getattr(target_win, 'height', MAIN_WINDOW_SIZE[1]) or MAIN_WINDOW_SIZE[1],
                getattr(target_win, 'x', None),
                getattr(target_win, 'y', None)
            )
            # Entering mini from a maximized window must clear the stale flag:
            # otherwise the next maximize button press restores first.
            self._is_maximized = False
            if hasattr(target_win, 'on_top'):
                target_win.on_top = True
            w, h = MINI_WINDOW_SIZE
            # All native ops go through the deferred path like every other
            # bridge-initiated window operation (single threading model).
            self._deferred_window_op(0.05, lambda: (
                target_win.resize(w, h),
                self._apply_window_pos(target_win, self._saved_mini_pos, w, h),
            ))
        except Exception as err:
            logger.debug(f"Failed setting mini size: {err}")

    def _exit_mini_mode(self):
        target_win = self._mini_window or self._window
        if not target_win:
            return
        try:
            logger.info("Restoring main window geometry")
            if hasattr(target_win, 'on_top'):
                target_win.on_top = False
            gw, gh, gx, gy = getattr(self, '_saved_main_geometry', (*MAIN_WINDOW_SIZE, None, None))
            # Restore EXACTLY what the user had; the old max(...,800/600) clamp
            # silently enlarged deliberately smaller windows.
            w = int(gw or MAIN_WINDOW_SIZE[0])
            h = int(gh or MAIN_WINDOW_SIZE[1])

            def _restore():
                target_win.resize(w, h)
                if gx is not None and gy is not None and hasattr(target_win, 'move'):
                    target_win.move(int(gx), int(gy))
                else:
                    area = self._logical_workarea()
                    if area and hasattr(target_win, 'move'):
                        ax, ay, aw, ah = area
                        target_win.move(ax + max(0, (aw - w) // 2), ay + max(0, (ah - h) // 2))

            self._deferred_window_op(0.05, _restore)
        except Exception as err:
            logger.debug(f"Failed restoring main size: {err}")

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
        self._deferred_window_op(0.1, lambda: self._apply_window_pos(target_win, pos, *MINI_WINDOW_SIZE))

    def _apply_window_pos(self, target_win, pos: str, w: int, h: int):
        """Compute target screen position for size (w x h) and move the window."""
        try:
            coords = self._saved_pos_coords(pos, w, h)
            if not coords:
                logger.debug("No work area available for position %r", pos)
                return
            x, y = coords
            if hasattr(target_win, 'move'):
                target_win.move(x, y)
        except Exception as e:
            logger.debug(f"Failed to move window to position {pos}: {e}")

    def set_windows(self, main_window, mini_window):
        """Register dual window references for main player and mini player."""
        self._main_window = main_window
        self._mini_window = mini_window
        if not self._window:
            self._window = main_window

    def close(self):
        """Close window or minimize to tray depending on general.minimize_to_tray setting."""
        if not self._window:
            return {"success": True, "message": "No active window"}

        minimize_to_tray = bool(self._core.settings.get("general", "minimize_to_tray", True))
        tray_mgr = getattr(self, "_tray", None) or getattr(self._core, "tray", None)
        tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)

        if minimize_to_tray and tray_available:
            try:
                self._window.hide()
                return {"success": True, "message": "Minimized to tray"}
            except Exception as e:
                logger.warning(f"Failed to hide window to tray: {e}")

        closer = threading.Timer(0.1, self._window.destroy)
        closer.daemon = True
        closer.start()
        return {"success": True, "message": "Window closing..."}

    def shutdown(self):
        """Release API-owned resources before the application exits."""
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

    def _get_hwnd(self):
        if not self._window:
            return None
        if hasattr(self._window, "hwnd") and self._window.hwnd:
            return self._window.hwnd
        if hasattr(self._window, "gui_window") and hasattr(self._window.gui_window, "Handle"):
            try:
                return int(self._window.gui_window.Handle)
            except Exception:
                logger.debug("_get_hwnd: suppressed exception", exc_info=True)
        if sys.platform == "win32":
            try:
                import ctypes
                title = getattr(self._window, "title", "NeDotify")
                hwnd = ctypes.windll.user32.FindWindowW(None, title)
                if hwnd:
                    return hwnd
            except Exception:
                logger.debug("_get_hwnd: suppressed exception", exc_info=True)
        return None

    def restore(self):
        """Restore window from maximized state to original unmaximized geometry."""
        if not self._window:
            return
        try:
            print("[WINDOW] restore called", flush=True)
            hwnd = self._get_hwnd()
            if hasattr(self, "_last_geometry") and self._last_geometry:
                x, y, w, h = self._last_geometry
                if sys.platform == "win32" and hwnd:
                    try:
                        import ctypes
                        ctypes.windll.user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), 0x0004 | 0x0040)
                    except Exception:
                        logger.debug("restore: suppressed exception", exc_info=True)
                if hasattr(self._window, "move") and hasattr(self._window, "resize"):
                    try:
                        self._window.move(int(x), int(y))
                        self._window.resize(int(w), int(h))
                    except Exception:
                        logger.debug("restore: suppressed exception", exc_info=True)
            else:
                if hasattr(self._window, "resize"):
                    self._window.resize(1100, 800)
            self._is_maximized = False
            logger.info("[WINDOW] Restored window to unmaximized geometry")
        except Exception as e:
            logger.error(f"Restore window error: {e}")

    def maximize(self):
        """Toggle maximize/restore frameless window state while keeping Windows taskbar visible."""
        if not self._window:
            return
        try:
            is_max = getattr(self, "_is_maximized", False)
            print(f"[WINDOW] maximize called (is_maximized={is_max})", flush=True)
            if is_max:
                self.restore()
            else:
                hwnd = self._get_hwnd()
                if sys.platform == "win32" and hwnd:
                    try:
                        import ctypes
                        from ctypes import wintypes
                        
                        # Store current geometry for restore
                        if hasattr(self._window, "x") and hasattr(self._window, "y") and hasattr(self._window, "width") and hasattr(self._window, "height"):
                            self._last_geometry = (self._window.x, self._window.y, self._window.width, self._window.height)
                        
                        rect = wintypes.RECT()
                        # SPI_GETWORKAREA = 0x0030: Get Windows work area (excludes taskbar)
                        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        
                        # SWP_NOZORDER (0x0004) | SWP_SHOWWINDOW (0x0040)
                        ctypes.windll.user32.SetWindowPos(hwnd, 0, rect.left, rect.top, w, h, 0x0004 | 0x0040)
                        
                        if hasattr(self._window, "move") and hasattr(self._window, "resize"):
                            try:
                                self._window.move(rect.left, rect.top)
                                self._window.resize(w, h)
                            except Exception:
                                logger.debug("maximize: suppressed exception", exc_info=True)

                        self._is_maximized = True
                        logger.info("[WINDOW] Maximized window to Work Area (Taskbar visible)")
                        return
                    except Exception as ex:
                        logger.warning(f"Win32 SetWindowPos workarea maximize exception: {ex}")
                
                # Fallback PyWebView move & resize to Work Area if hwnd fail
                try:
                    import ctypes
                    from ctypes import wintypes
                    rect = wintypes.RECT()
                    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    self._window.move(rect.left, rect.top)
                    self._window.resize(w, h)
                except Exception:
                    logger.debug("maximize: suppressed exception", exc_info=True)
                self._is_maximized = True
        except Exception as e:
            logger.error(f"Maximize window error: {e}")

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
        """Emit JS event to frontend webview."""
        self._emit(event_name, data)

    def _emit(self, event_name: str, data=None):
        """Internal thread-safe handler to evaluate JS event dispatch."""
        if not self._window:
            return

        payload_json = json.dumps(data or {})
        js_code = (
            f"if (window.onPythonEvent) {{ window.onPythonEvent("
            f"{json.dumps(event_name)}, {payload_json}); }}"
        )
        try:
            self._window.evaluate_js(js_code)
        except Exception as e:
            logger.debug(f"Failed to evaluate JS event {event_name}: {e}")

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
        """Callback invoked whenever active track changes."""
        if not track:
            return

        track_copy = dict(track)
        self._enrich_track_lufs(track_copy)
        # A new active track starts a fresh history session: the next real
        # playback start is allowed to log exactly one history entry.
        self._history_logged_key = None
        # Proxy cloud stream URL if the track already has a resolvable stream/file.
        # Tracks whose stream is still being resolved keep an empty stream_url so the
        # frontend can show a loading state instead of hanging on the proxy.
        if track_copy.get("source") in ("youtube", "soundcloud", "yandex", "vk"):
            if not track_copy.get("stream_url") and track_copy.get("file_path"):
                proxy_url = self._core.proxy.get_proxy_url(
                    track_copy.get("source"),
                    track_copy.get("source_id"),
                    track_copy.get("file_path") or track_copy.get("source_url"),
                    track_id=track_copy.get("id")
                )
                if proxy_url:
                    track_copy["stream_url"] = proxy_url

        self._current_track = track_copy
        try:
            if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
                self._core.discord_rpc.update_presence(
                    track_title=track_copy.get("title", ""),
                    track_artist=track_copy.get("artist", ""),
                    is_playing=True,
                    duration_sec=track_copy.get("duration", 0),
                    current_pos_sec=0
                )
        except Exception as dre:
            logger.debug(f"Discord RPC update error: {dre}")

        self._emit("track_changed", track_copy)
        if getattr(self, "_tray", None):
            self._tray.update_state(track=track_copy, force=True)

    def _on_audio_error(self, err):
        """Callback invoked when audio engine encounters playback error."""
        err_msg = str(err)
        self._emit("audio_error", {"message": err_msg})
        self._emit("error", err_msg)

    def maybe_log_history(self):
        """Log one history entry per successful playback start of a track.

        Called when the frontend reports a real 'playing' state (HTML5 audio
        actually started). Deduplicated until the active track changes or
        playback is stopped, so pause/resume cycles and backend re-resolution
        notifications never inflate play_count.
        """
        try:
            track = getattr(self, "_current_track", None)
            if not isinstance(track, dict):
                return
            key = track.get("id") or track.get("source_id")
            if key is None:
                key = f"{track.get('artist', '')}::{track.get('title', '')}"
            if not key or getattr(self, "_history_logged_key", None) == key:
                return
            self._history_logged_key = key
            t_id = track.get("id")
            if t_id:
                try:
                    self._core.db.add_to_history(int(t_id))
                except (ValueError, TypeError):
                    logger.debug("maybe_log_history: non-numeric track id %r", t_id)
        except Exception:
            logger.debug("maybe_log_history: suppressed exception", exc_info=True)

    def report_state(self, state: str, elapsed_ms: int = 0):
        """Report playback state update (playing, paused, stopped)."""
        if state == "playing":
            self.maybe_log_history()
        elif state == "stopped":
            # A manual stop ends the playback session: replaying the same track
            # afterwards counts as a new play.
            self._history_logged_key = None
        self._emit("state_changed", {"state": state, "elapsed_ms": elapsed_ms})
        if getattr(self, "_tray", None):
            self._tray.update_state(is_playing=(state == "playing"))
        try:
            if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
                curr = getattr(self, "_current_track", None) or {}
                if state == "playing":
                    self._core.discord_rpc.update_presence(
                        track_title=curr.get("title", ""),
                        track_artist=curr.get("artist", ""),
                        is_playing=True,
                        duration_sec=curr.get("duration", 0),
                        current_pos_sec=elapsed_ms / 1000.0 if elapsed_ms else 0
                    )
                elif state == "paused":
                    self._core.discord_rpc.update_presence(
                        track_title=curr.get("title", ""),
                        track_artist=curr.get("artist", ""),
                        is_playing=False
                    )
                elif state == "stopped":
                    self._core.discord_rpc.clear_presence()
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

    def report_position(self, pos_ms: int, dur_ms: int = 0, duration_ms: int = 0):
        """Report position update."""
        duration = dur_ms or duration_ms
        pos_sec = pos_ms / 1000.0 if pos_ms else 0.0
        dur_sec = duration / 1000.0 if duration else 0.0
        self._emit("position_changed", {
            "pos": pos_sec,
            "duration": dur_sec,
            "position_ms": pos_ms,
            "duration_ms": duration
        })

    def play_track(self, track: dict, track_list: list = None, index: int = 0):
        """Play given track data object."""
        logger.info(f"api.py -> play_track called! track={track.get('title') if isinstance(track, dict) else track}, has_track_list={bool(track_list)}, index={index}")
        if isinstance(track, dict):
            if track.get("track_id"):
                track["id"] = track["track_id"]
            self._enrich_track_lufs(track)
        if track_list and isinstance(track_list, list):
            for t in track_list:
                if isinstance(t, dict):
                    if t.get("track_id"):
                        t["id"] = t["track_id"]
                    self._enrich_track_lufs(t)

        # NOTE: listening history is intentionally NOT written here. play_track()
        # is also invoked by frontend stream-error retries and background
        # re-resolution, which used to inflate play_count and pollute history
        # with plays that never happened. History is logged once per successful
        # playback start instead - see report_state()/maybe_log_history().

        if track_list:
            if index is None or index == 0:
                if track and isinstance(track, dict):
                    t_src_id = track.get("source_id")
                    t_id = track.get("id")
                    found = False
                    if t_src_id:
                        for i, t in enumerate(track_list):
                            if isinstance(t, dict) and t.get("source_id") and str(t.get("source_id")) == str(t_src_id):
                                index = i
                                found = True
                                break
                    if not found and t_id:
                        for i, t in enumerate(track_list):
                            if isinstance(t, dict) and t.get("id") and str(t.get("id")) == str(t_id):
                                index = i
                                found = True
                                break
                    if not found and track.get("title"):
                        t_title = str(track.get("title", "")).strip().lower()
                        t_artist = str(track.get("artist", "")).strip().lower()
                        for i, t in enumerate(track_list):
                            if isinstance(t, dict):
                                c_title = str(t.get("title", "")).strip().lower()
                                c_artist = str(t.get("artist", "")).strip().lower()
                                if c_title == t_title and (not t_artist or c_artist == t_artist):
                                    index = i
                                    break

            safe_index = max(0, min(index, len(track_list) - 1)) if track_list else 0
            target_track = track_list[safe_index] if (isinstance(track_list, list) and safe_index < len(track_list)) else track

            source = target_track.get("source", "local") if isinstance(target_track, dict) else "local"
            source_id = target_track.get("source_id") if isinstance(target_track, dict) else None

            def _fp_usable(fp):
                if not fp:
                    return False
                if fp.startswith("http://") or fp.startswith("https://"):
                    return True
                try:
                    return os.path.exists(fp) and os.path.getsize(fp) > 1024
                except OSError:
                    return False

            fp = target_track.get("file_path") if isinstance(target_track, dict) else None
            if source == "local" or _fp_usable(fp):
                logger.info(f"api.py -> play_track fast path: source={source}, file_path={str(fp)[:80] if fp else None}")
                self._core.engine.play_queue(track_list, safe_index)
                return

            # Check DB stream cache (local file or fresh url)
            if source_id:
                cached = self._core.db.get_cached_stream(source, source_id)
                if cached:
                    cfp = cached.get("cached_file_path")
                    if cfp and os.path.exists(cfp) and os.path.getsize(cfp) > 1024:
                        target_track["file_path"] = cfp
                        logger.info(f"api.py -> play_track cache hit (local file): {cfp}")
                        self._core.engine.play_queue(track_list, safe_index)
                        return
                    c_url = cached.get("stream_url")
                    if c_url and (c_url.startswith("http://") or c_url.startswith("https://")):
                        target_track["file_path"] = c_url
                        logger.info(f"api.py -> play_track cache hit (url): {c_url[:80]}")
                        self._core.engine.play_queue(track_list, safe_index)
                        return

            # Check on-disk streams directory
            import re
            streams_dir = getattr(self._core.cache, "_streams_dir", None)
            if streams_dir and os.path.exists(streams_dir):
                safe_source = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source or 'unknown'))
                safe_source_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id or ''))
                cache_id = f"{safe_source}_{safe_source_id}"
                found_local = False
                for ext in ("m4a", "webm", "mp3", "ogg"):
                    cand = os.path.join(streams_dir, f"{cache_id}.{ext}")
                    if os.path.exists(cand) and os.path.getsize(cand) > 1024:
                        target_track["file_path"] = cand
                        found_local = True
                        break
                if found_local:
                    logger.info(f"api.py -> play_track streams dir hit: {target_track['file_path']}")
                    self._core.engine.play_queue(track_list, safe_index)
                    return

            # Start queue playback immediately (frontend shows loading state),
            # resolve the target stream in background and notify again when ready.
            self._core.engine.play_queue(track_list, safe_index)

            def on_queue_resolved(stream_url, metadata=None):
                if not stream_url:
                    logger.warning(f"api.py -> queue resolve FAILED: {source}/{source_id}")
                    if self._core.engine.queue.current_track is target_track:
                        self._on_audio_error(f"Не удалось найти поток для {target_track.get('title') or source_id}")
                    return
                logger.info(f"api.py -> queue track resolved! stream_url={stream_url[:80]}")
                if self._core.engine.queue.current_track is target_track:
                    target_track["file_path"] = stream_url
                    if metadata and isinstance(metadata, dict):
                        if metadata.get("duration") and not target_track.get("duration"):
                            target_track["duration"] = metadata["duration"]
                    # Re-notify only. Re-running play_queue() here used to reset
                    # the queue history stack and re-shuffle on every resolve.
                    self._core.engine._notify_track_changed()

            def on_queue_error(err):
                logger.warning(f"api.py -> queue resolve error: {err}")
                if self._core.engine.queue.current_track is target_track:
                    self._on_audio_error(f"Не удалось найти поток для {target_track.get('title') or source_id}")

            self._core.re_resolve_stream_url_async(source, source_id, callback=on_queue_resolved, on_error=on_queue_error, track=target_track)
        else:
            self._resolve_track(track, lambda t: self._core.engine.play_track(t))

    def _resolve_track(self, track: dict, play_callback):
        """Ensure stream for an online track. Keeps the queue intact when the track is already current."""
        source = track.get("source", "local")
        source_id = track.get("source_id")

        def _fp_usable(fp):
            if not fp:
                return False
            if fp.startswith("http://") or fp.startswith("https://"):
                return True
            try:
                return os.path.exists(fp) and os.path.getsize(fp) > 1024
            except OSError:
                return False

        def _is_current():
            cur = self._core.engine.queue.current_track
            if cur is track:
                return True
            if not cur or not source_id:
                return False
            return cur.get("source") == source and cur.get("source_id") == source_id

        def _deliver():
            if _is_current() and len(self._core.engine.queue.tracks) > 1:
                cur = self._core.engine.queue.current_track
                cur["file_path"] = track.get("file_path")
                self._core.engine._notify_track_changed()
            else:
                play_callback(track)

        fp = track.get("file_path")
        if source == "local" or _fp_usable(fp):
            logger.info(f"api.py -> _resolve_track fast path: source={source}, file_path={str(fp)[:80] if fp else None}")
            _deliver()
            return

        # Check DB cached stream first
        if source_id:
            cached = self._core.db.get_cached_stream(source, source_id)
            if cached:
                cfp = cached.get("cached_file_path")
                if cfp and os.path.exists(cfp) and os.path.getsize(cfp) > 1024:
                    track["file_path"] = cfp
                    logger.info(f"api.py -> _resolve_track cache hit (local file): {cfp}")
                    _deliver()
                    return
                c_url = cached.get("stream_url")
                if c_url and (c_url.startswith("http://") or c_url.startswith("https://")):
                    track["file_path"] = c_url
                    logger.info(f"api.py -> _resolve_track cache hit (url): {c_url[:80]}")
                    _deliver()
                    return

        # Check on-disk streams directory
        import re
        streams_dir = getattr(self._core.cache, "_streams_dir", None)
        if streams_dir and os.path.exists(streams_dir):
            safe_source = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source or 'unknown'))
            safe_source_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id or ''))
            cache_id = f"{safe_source}_{safe_source_id}"
            for ext in ("m4a", "webm", "mp3", "ogg"):
                cand = os.path.join(streams_dir, f"{cache_id}.{ext}")
                if os.path.exists(cand) and os.path.getsize(cand) > 1024:
                    track["file_path"] = cand
                    logger.info(f"api.py -> _resolve_track streams dir hit: {cand}")
                    _deliver()
                    return

        # Re-resolve stream url asynchronously
        cur_start = self._core.engine.queue.current_track

        def on_resolved(stream_url, metadata=None):
            if not stream_url:
                logger.warning(f"api.py -> on_resolved FAILED: {source}/{source_id}")
                if _is_current():
                    self._on_audio_error(f"Не удалось найти поток для {track.get('title') or source_id}")
                return
            logger.info(f"api.py -> on_resolved! stream_url={stream_url[:80]}")
            track["file_path"] = stream_url
            if metadata and isinstance(metadata, dict):
                if metadata.get("duration") and not track.get("duration"):
                    track["duration"] = metadata["duration"]
            if _is_current():
                cur = self._core.engine.queue.current_track
                cur["file_path"] = stream_url
                if metadata and isinstance(metadata, dict):
                    if metadata.get("duration") and not cur.get("duration"):
                        cur["duration"] = metadata["duration"]
                self._core.engine._notify_track_changed()
            elif self._core.engine.queue.current_track is cur_start:
                # Selection unchanged since resolution started: safe to deliver
                play_callback(track)
            # else: user moved on - drop stale resolution

        def on_resolve_error(err):
            logger.warning(f"api.py -> on_resolve error: {err}")
            if _is_current():
                self._on_audio_error(f"Не удалось найти поток для {track.get('title') or source_id}")

        self._core.re_resolve_stream_url_async(source, source_id, callback=on_resolved, on_error=on_resolve_error, track=track)

    def stop_track(self):
        """Stop audio playback."""
        pass # Handled by frontend

    def play_pause(self):
        """Toggle play/pause audio state."""
        pass # Handled by frontend

    def next_track(self):
        """Play next track in queue. Returns the next track or None at queue end."""
        if hasattr(self._core.engine, 'next_track'):
            return self._core.engine.next_track()
        return None

    def prev_track(self):
        """Play previous track in queue."""
        if hasattr(self._core.engine, 'prev_track'):
            self._core.engine.prev_track()

    def get_queue(self):
        """Return current queue state."""
        return {
            "tracks": self._core.engine.queue.tracks,
            "current_index": self._core.engine.queue._current_index,
            "current_track": self._core.engine.queue.current_track,
            "shuffle": self._core.engine.queue.shuffle,
            "repeat": self._core.engine.queue.repeat,
        }

    def reorder_queue(self, old_index: int, new_index: int):
        """Move track from old_index to new_index in queue."""
        self._core.engine.queue.move_track(old_index, new_index)
        self._emit("queue_updated", self.get_queue())

    def play_next(self, track: dict):
        """Insert track at the next position in the queue (O-1)."""
        try:
            self._core.engine.add_to_queue(track, play_next=True)
            self._emit("queue_updated", self.get_queue())
            return {"success": True}
        except Exception as e:
            logger.error(f"play_next error: {e}")
            return {"success": False, "error": str(e)}

    def add_to_queue(self, track: dict):
        """Append track to the end of the queue (O-1)."""
        try:
            self._core.engine.add_to_queue(track, play_next=False)
            self._emit("queue_updated", self.get_queue())
            return {"success": True}
        except Exception as e:
            logger.error(f"add_to_queue error: {e}")
            return {"success": False, "error": str(e)}

    def remove_from_queue(self, index):
        """Remove a track from the queue by index (O-1)."""
        try:
            try:
                index = int(index)
            except (TypeError, ValueError):
                return {"success": False, "error": "Неверный индекс очереди"}
            queue = self._core.engine.queue
            if not (0 <= index < len(queue.tracks)):
                return {"success": False, "error": "Неверный индекс очереди"}
            if index == queue._current_index:
                return {"success": False, "error": "Cannot remove current track"}
            queue.remove_track(index)
            self._emit("queue_updated", self.get_queue())
            return {"success": True}
        except Exception as e:
            logger.error(f"remove_from_queue error: {e}")
            return {"success": False, "error": str(e)}

    def get_setting(self, key: str, default=None):
        """Get a setting by dotted key 'category.key'."""
        try:
            if "." in key:
                cat, k = key.split(".", 1)
                return self._core.settings.get(cat, k, default)
            # Bare keys are ambiguous (they used to silently hit the 'zapret'
            # category); refuse them instead of returning a surprise value.
            logger.warning("get_setting: bare key %r rejected, pass 'category.key'", key)
            return default
        except Exception as e:
            logger.error(f"get_setting error: {e}")
            return default

    def set_setting(self, section: str, key=None, value=None):
        """Persist a setting value. Supports set_setting('zapret.auto_start', True) and set_setting('zapret', 'auto_start', True)."""
        try:
            if value is None and key is not None:
                full_key = str(section)
                val = key
                if "." in full_key:
                    cat, k = full_key.split(".", 1)
                else:
                    cat, k = "zapret", full_key
                self._core.settings.set(cat, k, val)
                self._emit("setting_changed", {"category": cat, "key": k, "value": val})
                return {"success": True}
            else:
                self._core.settings.set(section, key, value)
                self._emit("setting_changed", {"category": section, "key": key, "value": value})
                return {"success": True}
        except Exception as e:
            logger.error(f"set_setting error: {e}")
            return {"success": False, "error": str(e)}

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
                        self._core.settings.set("auth", "yandex_token", token.access_token)
                        self._core.settings.set("auth", "yandex_token_valid", True)
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
                    logger.error("Yandex device auth failed: %s", e)
                    self._emit("yandex_device_auth_result", {
                        "success": False,
                        "message": f"Ошибка авторизации Яндекс Музыки: {type(e).__name__}"
                    })

            threading.Thread(target=_worker, daemon=True).start()
            return {"success": True, "message": "Запрос авторизации запущен"}
        except Exception as e:
            logger.error("yandex_device_auth error: %s", e)
            return {"success": False, "message": str(e)}

    def set_volume(self, volume: int):
        """Set playback volume (0-100)."""
        self._core.settings.set("audio", "volume", volume)

    def get_volume(self):
        """Return current volume level."""
        return self._core.settings.get("audio", "volume", 70)

    def toggle_mute(self):
        """Toggle audio mute state."""
        return False # Handled by frontend

    def set_position(self, pos_ms: int):
        """Seek playback position in milliseconds."""
        pass # Handled by frontend

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
            if not self._core.engine.queue.tracks:
                return None
            current_idx = self._core.engine.queue._current_index
            next_idx = (current_idx + 1) % len(self._core.engine.queue.tracks)
            if next_idx < len(self._core.engine.queue.tracks):
                raw_track = self._core.engine.queue.tracks[next_idx]
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
            logger.error(f"get_next_track error: {e}")
        return None

    def search(self, query: str, source: str = "all", result_type: str = None):
        """Search without blocking the UI bridge.

        Providers run in parallel, each bounded by PROVIDER_SEARCH_TIMEOUT seconds.
        Results arrive via the search_results / search_completed events.
        """
        logger.info(f"api.py -> search called: query='{query}', source='{source}', result_type='{result_type}'")
        query = (query or "").strip()
        if not query:
            return {"query": "", "tracks": []}

        services = {
            "youtube": getattr(self._core, "youtube", None),
            "soundcloud": getattr(self._core, "soundcloud", None),
            "spotify": getattr(self._core, "spotify", None),
            "yandex": getattr(self._core, "yandex", None),
            "vk": getattr(self._core, "vk", None),
        }

        DISABLED_UI_PROVIDERS = {"yandex", "vk", "vkontakte", "zeno"}
        if source == "all":
            requested_providers = ["local", "youtube", "soundcloud", "spotify"]
        elif source == "local":
            requested_providers = ["local"]
        elif source in DISABLED_UI_PROVIDERS:
            requested_providers = []
        else:
            requested_providers = [source]

        def emit_results(tracks, service_name):
            self._emit("search_results", {
                "query": query,
                "source": service_name,
                "type": result_type,
                "tracks": tracks or [],
            })

        pending_lock = threading.Lock()
        pending_providers = set(requested_providers)
        completion_emitted = [False]

        def mark_done(provider_name):
            with pending_lock:
                pending_providers.discard(provider_name)
                if not pending_providers and not completion_emitted[0]:
                    completion_emitted[0] = True
                    self._emit("search_completed", {"query": query, "source": source})

        # Local DB Search
        if "local" in requested_providers:
            def _run_local():
                try:
                    if result_type in ("albums", "album"):
                        local_results = self._core.db.search_albums(query)
                    elif result_type in ("playlists", "playlist"):
                        local_results = self._core.db.search_playlists(query) if hasattr(self._core.db, "search_playlists") else []
                    else:
                        local_results = self._core.db.search_tracks(query)
                    emit_results(local_results, "local")
                except Exception as exc:
                    logger.error("Local search failed: %s", exc)
                    emit_results([], "local")
                finally:
                    mark_done("local")

            if source == "local":
                _run_local()
            else:
                self._search_executor.submit(_run_local)

        # Async Remote Provider Searches — hard timeout per provider
        for service_name in requested_providers:
            if service_name == "local":
                continue

            service = services.get(service_name)
            if not service:
                mark_done(service_name)
                continue

            def _run_provider(name, srv):
                is_done = [False]
                lock = threading.Lock()

                def _finish(tracks):
                    with lock:
                        if is_done[0]:
                            return
                        is_done[0] = True
                    # Release the deadline timer immediately; leaving it armed kept a
                    # live thread per keystroke and delayed process exit.
                    try:
                        timer.cancel()
                    except Exception:
                        logger.debug("search timer cancel failed", exc_info=True)
                    emit_results(tracks or [], name)
                    mark_done(name)

                def _on_success(tracks):
                    _finish(tracks)

                def _on_error(err):
                    logger.info("%s search failed: %s", name, err)
                    _finish([])

                def _on_timeout():
                    with lock:
                        if is_done[0]:
                            return
                    logger.warning("%s search timed out after %.1fs", name, PROVIDER_SEARCH_TIMEOUT)
                    _finish([])

                timer = threading.Timer(PROVIDER_SEARCH_TIMEOUT, _on_timeout)
                timer.daemon = True
                timer.start()

                try:
                    if result_type:
                        try:
                            srv.search(query, result_type=result_type, callback=_on_success, error_callback=_on_error)
                        except TypeError:
                            srv.search(query, callback=_on_success, error_callback=_on_error)
                    else:
                        srv.search(query, callback=_on_success, error_callback=_on_error)
                except Exception as exc:
                    logger.error("%s search could not start: %s", name, exc)
                    _finish([])

            self._search_executor.submit(_run_provider, service_name, service)

        return {"query": query, "tracks": []}

    def get_album_tracks(self, album_data: dict):
        """Fetch all tracks for an album given its metadata dictionary."""
        if not album_data or not isinstance(album_data, dict):
            return []

        source = album_data.get("source", "youtube")
        source_id = album_data.get("source_id") or album_data.get("id") or ""
        album_title = album_data.get("title") or album_data.get("album") or ""
        artist_name = album_data.get("artist") or ""

        deadline = time.monotonic() + BRIDGE_SYNC_BUDGET

        def _remaining():
            """Seconds left in the shared budget, never negative."""
            return max(0.0, deadline - time.monotonic())

        # 1. Local DB tracks
        if source == "local" or not source_id:
            tracks = self._core.db.get_album_tracks(album_title, artist_name)
            if tracks:
                return tracks

        # 2. Spotify / iTunes album lookup
        if source == "spotify" and hasattr(self._core, "spotify") and self._core.spotify:
            coll_id = source_id.replace("spotify_album_", "")
            res = []
            done_event = threading.Event()
            def _cb(trks):
                nonlocal res
                res = trks or []
                done_event.set()
            def _err(e):
                done_event.set()
            self._core.spotify.get_album_tracks(coll_id, callback=_cb, error_callback=_err)
            done_event.wait(timeout=_remaining())
            if res:
                return res

        # 3. YouTube Music album lookup
        if source == "youtube" and hasattr(self._core, "youtube") and self._core.youtube:
            browse_id = source_id.replace("yt_album_", "")
            if browse_id.startswith("MPRE") or browse_id.startswith("OLAK"):
                res = []
                done_event = threading.Event()
                def _cb(trks):
                    nonlocal res
                    res = trks or []
                    done_event.set()
                def _err(e):
                    done_event.set()
                self._core.youtube.get_album_tracks(browse_id, callback=_cb, error_callback=_err)
                done_event.wait(timeout=_remaining())
                if res:
                    return res

        # 4. Fallback search by Artist + Album Title
        search_q = f"{artist_name} {album_title}".strip()
        if search_q and hasattr(self._core, "youtube") and self._core.youtube:
            res = []
            done_event = threading.Event()
            def _cb(trks):
                nonlocal res
                res = trks or []
                done_event.set()
            def _err(e):
                done_event.set()
            self._core.youtube.search(search_q, max_results=15, callback=_cb, error_callback=_err)
            done_event.wait(timeout=_remaining())
            if res:
                return res

        return []

    def get_library(self):
        """Get all tracks in local library."""
        return self._core.db.get_all_tracks()

    def get_favorites(self):
        """Get favorite tracks list."""
        return self.get_favorite_tracks()

    def get_downloaded_tracks(self):
        """Get list of downloaded local tracks."""
        return self._core.db.get_downloaded_tracks()

    def download_track(self, track_data: dict):
        """Queue track for background download."""
        if not track_data:
            return False

        track_id = track_data.get("id")
        source = track_data.get("source", "youtube")
        source_id = track_data.get("source_id") or str(track_id)

        if not track_id:
            track_id = self._core.db.add_track(
                title=track_data.get("title", "Unknown"),
                artist=track_data.get("artist", "Unknown Artist"),
                source=source,
                source_id=source_id,
                duration=track_data.get("duration", 0)
            )

        return self._core.downloader.queue_download(track_id, source, source_id)

    def import_external_playlist(self, url: str, name: str | None = None):
        """Resolve a supported external playlist and persist its tracks locally."""
        url = (url or "").strip()
        if not _is_ssrf_safe_url(url):
            logger.warning("SSRF block triggered for playlist import URL: %s", url)
            return {"success": False, "error": "Некорректная или небезопасная ссылка"}

        playlist_id = None
        try:
            importer = getattr(self._core, "playlist_importer", None)
            if importer is None:
                return {"success": False, "error": "Сервис импорта плейлистов недоступен"}

            resolved = importer.resolve(url)
            tracks = resolved.get("tracks") if isinstance(resolved, dict) else None
            if not tracks:
                return {"success": False, "error": "В плейлисте не найдено доступных треков"}

            resolved_name = str(resolved.get("name") or "").strip()
            playlist_name = str(name or "").strip() or resolved_name or f"Imported Playlist ({int(time.time())})"
            playlist_id = self._core.db.create_playlist(playlist_name, f"Imported from {url}")

            added_count = 0
            for track in tracks:
                if not isinstance(track, dict):
                    raise ValueError("Resolver вернул некорректную структуру трека")
                track_id = self._core.db.ensure_track_exists(track)
                if not track_id or not self._core.db.add_to_playlist(playlist_id, track_id):
                    raise RuntimeError("Не удалось добавить все треки в локальный плейлист")
                added_count += 1

            self._emit("playlists_updated", {"playlist_id": playlist_id})
            return {
                "success": True,
                "playlist_id": playlist_id,
                "playlist_name": playlist_name,
                "imported_count": added_count,
            }
        except Exception as exc:
            if playlist_id is not None:
                try:
                    self._core.db.delete_playlist(playlist_id)
                except Exception:
                    logger.exception("Failed to clean up incomplete imported playlist")
            logger.error("Playlist import failed: %s", exc)
            return {"success": False, "error": str(exc) or "Не удалось импортировать плейлист"}

    def export_playlist(self, playlist_id: int, format: str = "m3u8", target_path: str = None) -> dict:
        """Export playlist tracks to standard M3U8 playlist file or specified format."""
        try:
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

            out_file = target_path or os.path.join(music_dir, f"{safe_name}.m3u8")

            m3u_lines = ["#EXTM3U", f"#PLAYLIST:{pl_name}"]
            exported_count = 0
            skipped_count = 0

            for t in tracks:
                title = t.get("title") or "Unknown"
                artist = t.get("artist") or "Unknown"
                duration = int(t.get("duration") or 0)
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

                if target_uri:
                    m3u_lines.append(f"#EXTINF:{duration},{artist} - {title}")
                    m3u_lines.append(target_uri)
                    exported_count += 1
                else:
                    skipped_count += 1

            if exported_count == 0:
                return {"success": False, "error": "Не удалось сформировать пути к аудиофайлам для треков"}

            with open(out_file, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_lines) + "\n")

            logger.info("Exported playlist '%s' to '%s' (%d tracks)", pl_name, out_file, exported_count)
            return {
                "success": True,
                "file_path": out_file,
                "exported_count": exported_count,
                "skipped_count": skipped_count,
                "playlist_name": pl_name
            }
        except Exception as e:
            logger.error("export_playlist error: %s", e)
            return {"success": False, "error": str(e)}

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
            return {"success": False, "error": str(e)}

    def get_playlists(self):
        """Get list of user playlists."""
        return self._core.db.get_playlists()

    def add_to_playlist(self, playlist_id: int, track_data: dict):
        """Add track to playlist."""
        track_id = track_data.get("id")
        if not track_id:
            track_id = self._core.db.add_track(
                title=track_data.get("title", "Unknown"),
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
            logger.error(f"get_track_info error for id {track_id}: {e}")
            return None

    def get_playlist_tracks(self, playlist_id, source: str = "local", limit: int = 50):
        """Get tracks for a playlist by source (local / youtube / soundcloud / spotify). Synchronous."""
        source = (source or "local").lower()

        if source == "local":
            try:
                db_tracks = self._core.db.get_playlist_tracks(playlist_id) or []
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
                logger.error(f"get_playlist_tracks local error: {e}")
                return {"success": False, "error": str(e)}

        services = {
            "youtube": getattr(self._core, "youtube", None),
            "soundcloud": getattr(self._core, "soundcloud", None),
            "spotify": getattr(self._core, "spotify", None),
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
            result["error"] = str(err)
            done.set()

        try:
            srv.get_playlist_tracks(playlist_id, limit=limit, callback=_on_success, error_callback=_on_error)
        except Exception as e:
            logger.error(f"get_playlist_tracks {source} error: {e}")
            return {"success": False, "error": str(e)}

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
        track_id = track_data.get("id")
        if not track_id:
            track_id = self._core.db.add_track(
                title=track_data.get("title", "Unknown"),
                artist=track_data.get("artist", "Unknown Artist"),
                source=track_data.get("source", "local"),
                source_id=track_data.get("source_id"),
                duration=track_data.get("duration", 0)
            )
        status = self._core.db.toggle_favorite(track_id)
        self._emit("favorites_updated", self.get_favorite_tracks())
        return {"success": True, "is_favorite": status}

    def get_favorite_tracks(self):
        """Get list of favorite tracks."""
        return self._core.db.get_favorite_tracks()

    def save_theme(self, theme: str):
        """Save theme setting."""
        self._core.settings.set("theme", "current_theme", theme)
        self._emit("theme_changed", theme)
        return True

    def complete_onboarding(self, settings_data: dict):
        """Mark onboarding complete and save preferences into their real categories."""
        self._core.settings.set("general", "first_launch_done", True)
        self._core.settings.set("personalization", "onboarding_completed", True)
        if isinstance(settings_data, dict):
            mapping = {
                "theme_mode": ("theme", "mode"),
                "accent_color": ("theme", "accent_color"),
                "particles_enabled": ("ui", "particles_enabled"),
                "crossfade_enabled": ("audio", "crossfade_enabled"),
                "volume_normalization": ("audio", "volume_normalization"),
                "autostart": ("general", "autostart"),
                "minimize_to_tray": ("general", "minimize_to_tray"),
                "audio_device": ("audio", "output_device"),
                "performance_preset": ("optimization", "performance_preset"),
            }
            for k, v in settings_data.items():
                target = mapping.get(k)
                if target:
                    self._core.settings.set(target[0], target[1], v)
            if "autostart" in settings_data:
                try:
                    self.update_autostart(bool(settings_data["autostart"]))
                except Exception as e:
                    logger.warning(f"Failed to sync autostart in complete_onboarding: {e}")
        return True

    def update_autostart(self, enabled: bool):
        """Toggle app autostart registry entry on Windows."""
        if sys.platform != "win32":
            return False
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            app_name = "AURA Music"
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
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            else:
                for name in (app_name, "NeDotify"):
                    try:
                        winreg.DeleteValue(key, name)
                    except (FileNotFoundError, OSError):
                        pass
            try:
                winreg.CloseKey(key)
            except OSError:
                logger.debug("Registry key close failed", exc_info=True)
            self._core.settings.set("general", "autostart", enabled)
            self._core.settings.set("app", "autostart", enabled)
            return True
        except (OSError, Exception) as e:
            logger.error(f"Failed to update autostart: {e}")
            return False

    def validate_subscription_key(self, key: str):
        """Report licence status for `key`.

        Licensing is not enforced in this build (LICENSE_VALIDATION_ENABLED is False),
        so every key is reported as valid. The flag is honoured here rather than the
        result being hardcoded, so enabling it cannot be forgotten: with validation on
        and no remote service wired up, access is denied instead of silently granted.
        """
        if not LICENSE_VALIDATION_ENABLED:
            return {"valid": True, "is_valid": True, "success": True, "expire": "never", "valid_until": 0}
        logger.warning("Licence validation is enabled but no validation service is configured")
        return {"valid": False, "is_valid": False, "success": False,
                "error": "Сервис проверки лицензий недоступен", "valid_until": 0}

    def get_subscription_info(self):
        """Return current licence information. See validate_subscription_key."""
        if not LICENSE_VALIDATION_ENABLED:
            return {"valid": True, "is_valid": True, "success": True, "expire": "never",
                    "valid_until": 0, "key": "OPEN-SOURCE"}
        logger.warning("Licence validation is enabled but no validation service is configured")
        return {"valid": False, "is_valid": False, "success": False,
                "error": "Сервис проверки лицензий недоступен", "valid_until": 0, "key": ""}

    def get_settings(self, category: str = None):
        """Get settings dict."""
        if category:
            return self._core.settings.get_category(category)
        
        if hasattr(self._core.settings, 'get_all'):
            return self._core.settings.get_all()
            
        if hasattr(self._core.settings, '_settings'):
            import copy
            return copy.deepcopy(self._core.settings._settings)
            
        categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay', 'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance', 'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services', 'session', 'zapret']
        res = {}
        for c in categories:
            try:
                cat_data = self._core.settings.get_category(c)
                if cat_data:
                    res[c] = cat_data
            except Exception:
                logger.debug("settings category %s unavailable", c, exc_info=True)
        return res

    def save_setting(self, key: str, value, category: str = "app"):
        """Save a setting value."""
        self._core.settings.set(category, key, value)
        if key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart"):
            try:
                self.update_autostart(bool(value))
            except Exception as e:
                logger.warning(f"Failed to sync autostart in save_setting: {e}")
        self._emit("setting_changed", {"category": category, "key": key, "value": value})
        return True

    def get_all_settings(self):
        return self._core.settings.get_all()

    def get_settings_by_category(self, category: str):
        return self._core.settings.get_category(category)

    def update_setting(self, category: str, key: str, value):
        return self.save_setting(key, value, category)

    def get_personalization(self):
        return self._core.settings.get_category("personalization")

    def save_personalization(self, data: dict):
        if isinstance(data, dict):
            for k, v in data.items():
                self._core.settings.set("personalization", k, v)
        return True

    #: get_storage_info walks the whole cache tree, which is far too slow to redo on
    #: every settings-screen render. Result is reused for this many seconds.
    _STORAGE_INFO_TTL = 30.0

    def get_storage_info(self):
        """Get cache, covers & downloaded storage size info (cached for 30s)."""
        cached = getattr(self, "_storage_info_cache", None)
        if cached and (time.monotonic() - cached[0]) < self._STORAGE_INFO_TTL:
            self._emit("storage_info", cached[1])
            return cached[1]
        try:
            cache_dir = self._core.cache.cache_dir
            covers_dir = getattr(self._core.scanner, "_covers_dir", os.path.expanduser("~/.nedotify/covers"))

            cache_bytes = 0
            if os.path.exists(cache_dir):
                for root, _, files in os.walk(cache_dir):
                    for f in files:
                        try:
                            cache_bytes += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            logger.debug("get_storage_info: suppressed exception", exc_info=True)

            covers_bytes = 0
            covers_count = 0
            if os.path.exists(covers_dir):
                for root, _, files in os.walk(covers_dir):
                    for f in files:
                        covers_count += 1
                        try:
                            covers_bytes += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            logger.debug("get_storage_info: suppressed exception", exc_info=True)

            downloaded_tracks = self._core.db.get_downloaded_tracks() or []
            track_bytes = 0
            track_count = len(downloaded_tracks)
            for tr in downloaded_tracks:
                fp = tr.get("file_path")
                if fp and os.path.exists(fp):
                    try:
                        track_bytes += os.path.getsize(fp)
                    except Exception:
                        logger.debug("get_storage_info: suppressed exception", exc_info=True)

            total_bytes = cache_bytes + covers_bytes + track_bytes
            total_mb = round(total_bytes / (1024 * 1024), 2)
            track_mb = round(track_bytes / (1024 * 1024), 2)
            cover_mb = round(covers_bytes / (1024 * 1024), 2)

            res = {
                "total": total_mb,
                "total_mb": total_mb,
                "tracks": {"count": track_count, "size": f"{track_mb} MB"},
                "covers": {"count": covers_count, "size": f"{cover_mb} MB"},
                "cache_dir": cache_dir
            }
            self._storage_info_cache = (time.monotonic(), res)
            self._emit("storage_info", res)
            return res
        except Exception as e:
            err_res = {
                "total": 0.0,
                "total_mb": 0.0,
                "tracks": {"count": 0, "size": "0 MB"},
                "covers": {"count": 0, "size": "0 MB"},
                "error": str(e)
            }
            self._emit("storage_info", err_res)
            return err_res

    def clear_storage(self, storage_type: str = "cache"):
        """Clear cache or storage folder."""
        try:
            if storage_type in ("cache", "all"):
                self._core.cache.clear_all()
            return True
        except Exception as e:
            logger.error(f"Clear storage failed: {e}")
            return False

    def get_wrapped_stats(self, period: str = "week"):
        """Get NeDotify Wrapped analytics stats (top 5 tracks/artists, total minutes, activity graph)."""
        try:
            return self._core.db.get_wrapped_stats(period=period)
        except Exception as e:
            logger.error(f"Error fetching wrapped stats: {e}")
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
        """Get equalizer preamp and bands."""
        return {
            "preamp": self._core.settings.get("equalizer", "preamp", 0),
            "bands": self._core.settings.get("equalizer", "bands", [0] * 10)
        }

    def set_equalizer(self, preamp: float = 0, bands: list = None):
        """Persist equalizer settings.

        The actual DSP lives in the frontend WebAudio graph (player.js setEq);
        the backend only stores the values. The old engine.set_equalizer()
        call here targeted a method AudioEngine never had and silently no-op'd.
        """
        self._core.settings.set("equalizer", "preamp", preamp)
        if bands:
            self._core.settings.set("equalizer", "bands", bands)
        return True

    def get_lyrics(self, track_name: str, artist_name: str, duration_ms: int = 0, file_path: str = None):
        """Get lyrics for track asynchronously to prevent blocking UI (C-2).

        Returns {"status": "loading"} immediately; a single background cascade
        delivers the result via the lyrics_ready event.
        """
        with self._lyrics_lock:
            self._lyrics_cascade_count += 1
            cascade_no = self._lyrics_cascade_count
        logger.info(f"[lyrics] cascade call #{cascade_no} for {artist_name} - {track_name}")

        def _is_latest():
            with self._lyrics_lock:
                return cascade_no == self._lyrics_cascade_count

        def run():
            try:
                data = self._core.lyrics.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path)
            except Exception as e:
                logger.warning("lyrics cascade #%d failed: %s", cascade_no, e, exc_info=True)
                data = {"synced": False, "lyrics": f"Could not fetch lyrics: {e}"}
            # Skipping publication of a superseded cascade: without this, switching
            # tracks quickly let a slow earlier lookup overwrite the current track's
            # lyrics, because whichever request finished last won.
            if _is_latest():
                self._emit("lyrics_ready", data)
            else:
                logger.debug("Discarding superseded lyrics cascade #%d", cascade_no)

        threading.Thread(target=run, daemon=True, name=f"Lyrics-{cascade_no}").start()
        return {"status": "loading", "cascade": cascade_no}

    def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
        """Get translation for lyrics text."""
        try:
            return self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
        except Exception as e:
            return {"error": str(e)}

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

    def get_popular_tracks(self, region: str = "US"):
        """Request popular tracks and deliver them through the frontend event contract.

        With no local listening history and no chart provider response the UI
        receives an empty list and shows its own empty state. The old hardcoded
        "Blinding Lights / Levitating ..." fallback presented fake charts to new
        users, which looked like real recommendations.
        """
        fallback = self._core.db.get_history(limit=10) or []
        try:
            provider = getattr(self._core.recommendations, "get_charts", None)
            if provider:
                provider(region, callback=lambda tracks: self._emit("popular_results", tracks or []))
            else:
                self._core.recommendations.get_releases(
                    [region], callback=lambda tracks: self._emit("popular_results", tracks or [])
                )
        except Exception as exc:
            logger.info("Popular tracks fallback: %s", exc)
            self._emit("popular_results", fallback)
        return []

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
                logger.warning(f"get_authentic_home_feed error: {err}")
                # Fallback to popular tracks / default sections
                self._emit("authentic_home_ready", {"sections": []})

            if hasattr(self._core, "recommendations") and self._core.recommendations:
                self._core.recommendations.get_feed(history=history, callback=_on_feed, error_callback=_on_err)
            else:
                self._emit("authentic_home_ready", {"sections": []})
        except Exception as e:
            logger.error(f"get_authentic_home_feed exception: {e}")
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
            logger.error(f"Select avatar error: {e}")
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
        """Open native file dialog to select and play/import local audio file(s)."""
        if not self._window:
            return False
        try:
            file_types = ("Audio Files (*.mp3;*.flac;*.wav;*.ogg;*.m4a)", "All Files (*.*)")
            dialog_type = getattr(webview, 'FileDialog', webview).OPEN if hasattr(webview, 'FileDialog') else webview.OPEN_DIALOG
            res = self._window.create_file_dialog(dialog_type, allow_multiple=True, file_types=file_types)
            if not res:
                return False

            imported = []
            for file_path in res:
                meta = self._core.scanner.scan_single_file(file_path)
                if meta:
                    imported.append(meta)

            if imported:
                self._emit("library_updated", True)
                self.play_track(imported[0], track_list=imported, index=0)
                return True
        except Exception as e:
            logger.error(f"Error opening local file: {e}")
        return False

    def get_artist_profile(self, artist_name: str):
        """Request a full artist profile: avatar, bio, subscribers, discography, top tracks.

        Resolution needs two or three YouTube Music round trips, so it is delivered
        through the artist_profile_ready / artist_profile_error events rather than
        blocking the bridge thread.
        """
        name = (artist_name or "").strip()
        if not name:
            self._emit("artist_profile_error", {"artist": "", "error": "Имя исполнителя не указано"})
            return {"status": "error", "error": "Имя исполнителя не указано"}

        svc = getattr(self._core, "artists", None)
        if svc is None:
            self._emit("artist_profile_error", {"artist": name, "error": "Сервис исполнителей недоступен"})
            return {"status": "error", "error": "Сервис исполнителей недоступен"}

        def _ok(profile):
            self._emit("artist_profile_ready", profile)

        def _err(message):
            logger.info("Artist profile for %r unavailable: %s", name, message)
            self._emit("artist_profile_error", {"artist": name, "error": str(message)})

        svc.get_profile(name, callback=_ok, error_callback=_err)
        return {"status": "loading", "artist": name}

    def get_recommendations(self, track_data: dict, max_results: int = 10):
        """Get recommended tracks for seed track synchronously with timeout."""
        res = []
        evt = threading.Event()
        def callback(tracks):
            if tracks:
                res.extend(tracks)
            evt.set()
        try:
            self._core.recommendations.get_recommendations(track_data, callback=callback)
            evt.wait(timeout=3.0)
        except Exception as e:
            logger.error(f"Error in get_recommendations: {e}")
        return res[:max_results]

    def get_track_wave(self, track_data: dict, limit: int = 15, exclude_ids: list = None):
        """Get smart wave / radio of related tracks for a seed track (async, O-4).

        Returns [] immediately; results are delivered via the track_wave_ready event.
        """
        if not track_data or not isinstance(track_data, dict):
            return []
        try:
            self._core.recommendations.get_wave_for_track(
                track_data, limit=limit, exclude_ids=exclude_ids or [],
                callback=lambda tracks: self._emit("track_wave_ready", {"tracks": tracks or []}),
                error_callback=lambda e: self._emit("track_wave_ready", {"tracks": [], "error": str(e)}),
            )
        except Exception as e:
            logger.error(f"Error in get_track_wave: {e}")
            self._emit("track_wave_ready", {"tracks": [], "error": str(e)})
        return []

    def get_waveform(self, track_data: dict):
        """Get sound wave peak amplitude points (0.0..1.0) for waveform scrubber."""
        if not track_data or not isinstance(track_data, dict):
            return []
        waveform_url = track_data.get("waveform_url") or ""
        if waveform_url and hasattr(self._core, "soundcloud"):
            try:
                return self._core.soundcloud.get_waveform_data_sync(waveform_url)
            except Exception as e:
                logger.warning(f"Error fetching waveform: {e}")
        return []

    def _clean_stream_cache(self, max_size_mb: int = 350, max_age_hours: int = 48):
        """Clean cached audio streams using LRU and TTL to prevent disk bloat."""
        try:
            # Use the CacheManager's actual streams dir; the old hardcoded
            # ~/.nedotify/streams silently drifted if the root ever moved.
            streams_dir = getattr(self._core.cache, "_streams_dir", None) or os.path.join(
                os.path.expanduser("~"), ".nedotify", "streams"
            )
            if not os.path.exists(streams_dir):
                return
            now = time.time()
            max_age_sec = max_age_hours * 3600
            files = []
            total_size = 0
            for entry in os.scandir(streams_dir):
                if entry.is_file():
                    stat = entry.stat()
                    total_size += stat.st_size
                    files.append((entry.path, stat.st_mtime, stat.st_size))
            
            kept_files = []
            for path, mtime, size in files:
                if (now - mtime) > max_age_sec:
                    try:
                        os.remove(path)
                        total_size -= size
                    except Exception:
                        kept_files.append((path, mtime, size))
                else:
                    kept_files.append((path, mtime, size))

            max_bytes = max_size_mb * 1024 * 1024
            if total_size > max_bytes:
                kept_files.sort(key=lambda x: x[1])
                for path, mtime, size in kept_files:
                    if total_size <= max_bytes * 0.7:
                        break
                    try:
                        os.remove(path)
                        total_size -= size
                    except Exception:
                        logger.debug("_clean_stream_cache: suppressed exception", exc_info=True)
        except Exception as e:
            logger.debug(f"Stream cache cleanup ignored: {e}")

    def prefetch_track(self, track_data: dict):
        """Background pre-caching / stream resolution for seamless instant next track switching."""
        if not track_data or not isinstance(track_data, dict):
            return False
        def _prefetch_task():
            try:
                # Cache pruning is throttled: it used to run a full scandir of the
                # streams directory on every single track change.
                now = time.monotonic()
                if now - getattr(self, "_last_stream_clean", 0.0) > 600.0:
                    self._last_stream_clean = now
                    self._clean_stream_cache()
                source = track_data.get("source")
                source_id = track_data.get("source_id")
                source_url = track_data.get("source_url") or source_id
                if source == "soundcloud" and hasattr(self._core, "soundcloud"):
                    self._core.soundcloud.get_stream_url(source_url or source_id, quality="high")
                elif source == "youtube" and hasattr(self._core, "youtube"):
                    yt_url = source_url if source_url and "youtube.com" in source_url else f"https://www.youtube.com/watch?v={source_id}"
                    self._core.youtube.get_stream_url(yt_url, quality="high")
            except Exception as e:
                logger.debug(f"Prefetch task ignored error: {e}")
        self._search_executor.submit(_prefetch_task)
        return True

    def download_all_favorites(self):
        """Download all favorite tracks for offline playback with disk space validation and batch progress."""
        try:
            favs = self._core.db.get_favorite_tracks() or []
            if not favs:
                return {"success": False, "message": "В избранном нет треков для загрузки"}

            to_download = [t for t in favs if not t.get("is_downloaded")]
            if not to_download:
                return {"success": True, "count": 0, "total": len(favs), "message": "Все любимые треки уже скачаны!"}

            app_dir = os.path.expanduser("~/.nedotify")
            total, used, free = shutil.disk_usage(app_dir if os.path.exists(app_dir) else os.path.expanduser("~"))
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

            for track in to_download:
                self.download_track(track)

            self._emit("batch_download_started", {"total": len(to_download), "current": 0})

            return {
                "success": True,
                "count": len(to_download),
                "total": len(favs),
                "message": f"Добавлено в очередь на скачивание: {len(to_download)} треков"
            }
        except Exception as e:
            logger.error(f"Error in download_all_favorites: {e}")
            return {"success": False, "message": f"Ошибка скачивания: {e}"}

    def cancel_batch_download(self):
        """Cancel ongoing batch download and clear remaining queue."""
        try:
            if hasattr(self._core, "downloader"):
                return self._core.downloader.cancel_batch()
            return True
        except Exception as e:
            logger.error(f"Error cancelling batch download: {e}")
            return False

    def get_feed(self, max_results: int = 20):
        """Request recommendations without blocking the UI bridge."""
        history = self._core.db.get_history(limit=10)
        try:
            self._core.recommendations.get_feed(
                history, callback=lambda tracks: self._emit("feed_ready", (tracks or [])[:max_results])
            )
        except Exception as exc:
            logger.info("Feed fallback: %s", exc)
            self._emit("feed_ready", history[:max_results])
        return []

    def get_home_artists(self, max_results: int = 10):
        """Get top artists for the home page.

        No fabricated fallback: with empty history the UI receives an empty
        list and renders its own "пока пусто" state instead of pretending the
        user listens to The Weeknd.
        """
        artists = self._core.db.get_top_artists(limit=max_results) or []
        self._emit("artists_ready", artists)
        return artists

    def get_home_releases(self, max_results: int = 10):
        """Request new releases and publish a fallback on failure."""
        try:
            self._core.recommendations.get_releases(
                ["Pop", "Rock"], callback=lambda tracks: self._emit("releases_ready", (tracks or [])[:max_results])
            )
        except Exception as exc:
            logger.info("Releases fallback: %s", exc)
            self._emit("releases_ready", [])
        return []

    def get_home_mixes(self, max_results: int = 10):
        """Request generated mixes and publish a fallback on failure."""
        top_artists = self._core.db.get_top_artists(limit=3)
        try:
            self._core.recommendations.get_mixes(
                top_artists, callback=lambda tracks: self._emit("mixes_ready", (tracks or [])[:max_results])
            )
        except Exception as exc:
            logger.info("Mixes fallback: %s", exc)
            self._emit("mixes_ready", [])
        return []

    def toggle_zapret(self, enabled: bool, mode: str = "youtube_discord", custom_args: str = "", binary_path: str = ""):
        """Toggle DPI bypass Zapret service."""
        try:
            if enabled:
                success, msg = self._core.zapret.start(mode=mode, custom_args=custom_args, binary_path=binary_path)
            else:
                success, msg = self._core.zapret.stop()
            self._core.settings.set("zapret", "enabled", enabled and success)
            self._core.settings.set("zapret", "mode", mode)
            self._core.settings.set("zapret", "custom_args", custom_args or "")
            self._core.settings.set("zapret", "binary_path", binary_path or "")
            is_running = self._core.zapret.is_running()
            return {
                "success": success,
                "running": is_running,
                "enabled": enabled and success,
                "message": msg,
                "error": None if success else msg
            }
        except Exception as e:
            return {"success": False, "running": False, "enabled": False, "error": str(e), "message": str(e)}

    def toggle_discord_rpc(self, enabled: bool):
        """Toggle Discord Rich Presence integration."""
        try:
            self._core.settings.set("app", "discord_rpc_enabled", enabled)
            if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
                if enabled:
                    self._core.discord_rpc.start()
                    curr = getattr(self, "_current_track", None)
                    if curr:
                        self._core.discord_rpc.update_presence(
                            track_title=curr.get("title", ""),
                            track_artist=curr.get("artist", ""),
                            is_playing=True,
                            duration_sec=curr.get("duration", 0)
                        )
                else:
                    self._core.discord_rpc.clear_presence()
            return {"success": True, "enabled": enabled}
        except Exception as e:
            logger.error(f"Error toggling Discord RPC: {e}")
            return {"success": False, "error": str(e)}

    def get_discord_rpc_status(self):
        """Get Discord Rich Presence status."""
        enabled = self._core.settings.get("app", "discord_rpc_enabled", True)
        connected = getattr(self._core.discord_rpc, "connected", False) if hasattr(self._core, "discord_rpc") else False
        return {"enabled": enabled, "connected": connected}

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
            return {"running": False, "enabled": False, "auto_start": False, "mode": "youtube_discord", "error": str(e), "binary_found": False}

    def check_zapret_update(self):
        """Check for updates to the Zapret binary bundle."""
        try:
            return self._core.zapret.check_for_updates()
        except Exception as e:
            return {"update_available": False, "error": str(e)}

    def update_zapret(self, force: bool = False):
        """Update Zapret binary bundle to latest version."""
        try:
            success, msg = self._core.zapret.update_zapret(force=force)
            status = self._core.zapret.get_status()
            return {"success": success, "message": msg, "status": status}
        except Exception as e:
            return {"success": False, "message": f"Ошибка обновления: {e}", "error": str(e)}

    def find_duplicate_tracks(self):
        """Scan local tracks and return duplicate track groups based on acoustic fingerprint."""
        try:
            return self._core.audio_fingerprint.find_duplicates(self._core.db)
        except Exception as e:
            logger.error(f"Error finding duplicate tracks: {e}")
            return []

    def delete_duplicate_track(self, track_id: int, delete_file: bool = False):
        """Delete duplicate track entry from database and optionally remove local file."""
        try:
            res = self._core.audio_fingerprint.delete_duplicate_track(self._core.db, track_id, delete_file=delete_file)
            if res:
                self._emit("library_updated", True)
            return {"success": res}
        except Exception as e:
            logger.error(f"Error deleting duplicate track: {e}")
            return {"success": False, "error": str(e)}

    def update_track_tags(self, track_id: int, tags: dict) -> dict:
        """Update physical ID3/Vorbis/MP4 tags and SQLite metadata for a track."""
        try:
            track = self._core.db.get_track(track_id)
            if not track:
                return {"success": False, "error": f"Трек с ID {track_id} не найден в базе данных"}

            file_path = track.get("file_path")
            title = (tags.get("title") or track.get("title") or "").strip()
            artist = (tags.get("artist") or track.get("artist") or "").strip()
            album = (tags.get("album") or track.get("album") or "").strip()
            genre = (tags.get("genre") or track.get("genre") or "").strip()

            raw_year = tags.get("year")
            year = None
            if raw_year is not None and str(raw_year).strip():
                try:
                    year = int(str(raw_year).strip()[:4])
                except (ValueError, TypeError):
                    year = None

            cover_path = track.get("cover_path")
            cover_bytes = None
            cover_mime = "image/jpeg"

            # Check for new cover image provided
            new_cover_path = tags.get("cover_path") or tags.get("cover_file")
            if new_cover_path and os.path.exists(new_cover_path):
                try:
                    with open(new_cover_path, "rb") as cf:
                        cover_bytes = cf.read()
                    if new_cover_path.lower().endswith(".png"):
                        cover_mime = "image/png"
                    elif new_cover_path.lower().endswith(".webp"):
                        cover_mime = "image/webp"

                    # Save copy to ~/.nedotify/covers/ for fast UI loading
                    covers_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "covers")
                    os.makedirs(covers_dir, exist_ok=True)
                    cached_cover = os.path.join(covers_dir, f"{track_id}.jpg")
                    with open(cached_cover, "wb") as f:
                        f.write(cover_bytes)
                    cover_path = cached_cover
                except Exception as ce:
                    logger.warning(f"Error caching new cover image: {ce}")

            # Write physical audio tags if file exists on disk
            if file_path and os.path.exists(file_path):
                if not os.access(file_path, os.W_OK):
                    return {"success": False, "error": "Файл доступен только для чтения (нет прав на запись)"}

                from utils.tag_parser import write_tags
                write_tags(
                    file_path,
                    title=title,
                    artist=artist,
                    album=album,
                    genre=genre,
                    year=year,
                    cover_bytes=cover_bytes,
                    cover_mime=cover_mime
                )

            # Update database record and FTS index
            db_res = self._core.db.update_track_metadata(
                track_id=track_id,
                title=title,
                artist=artist,
                album=album,
                genre=genre,
                year=year,
                cover_path=cover_path
            )

            if not db_res:
                return {"success": False, "error": "Не удалось обновить запись в базе данных"}

            updated_track = self._core.db.get_track(track_id)
            self._emit("library_updated", True)
            self._emit("track_updated", updated_track)

            return {"success": True, "track": updated_track}

        except Exception as e:
            logger.error(f"Error in update_track_tags: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def choose_cover_image(self) -> dict:
        """Open native file dialog to select a cover art image."""
        try:
            if not self._window:
                return {"success": False, "error": "Окно приложения недоступно"}
            file_types = ('Изображения (*.jpg;*.jpeg;*.png;*.webp)', 'Все файлы (*.*)')
            dialog_type = getattr(webview, 'FileDialog', webview).OPEN if hasattr(webview, 'FileDialog') else webview.OPEN_DIALOG
            result = self._window.create_file_dialog(
                dialog_type,
                allow_multiple=False,
                file_types=file_types
            )
            if result and len(result) > 0:
                return {"success": True, "path": result[0]}
            return {"success": False, "cancelled": True}
        except Exception as e:
            logger.error(f"Error selecting cover image: {e}")
            return {"success": False, "error": str(e)}

    def get_storage_details(self) -> dict:
        """Get storage metrics including used bytes, quota bytes, and protected tracks count."""
        try:
            if hasattr(self._core, "cache") and self._core.cache:
                return self._core.cache.get_storage_details()
            return {"used_bytes": 0, "quota_bytes": 5 * 1024 * 1024 * 1024, "quota_gb": 5, "protected_count": 0}
        except Exception as e:
            logger.error(f"Error getting storage details: {e}")
            return {"used_bytes": 0, "quota_bytes": 5 * 1024 * 1024 * 1024, "quota_gb": 5, "protected_count": 0}

    def set_cache_quota(self, quota_gb: int) -> dict:
        """Set storage cache quota in GB and trigger LRU eviction if quota is exceeded."""
        try:
            quota_val = max(0, int(quota_gb))
            if hasattr(self._core, "settings") and self._core.settings:
                self._core.settings.set("storage", "cache_quota_gb", quota_val)

            freed = 0
            if hasattr(self._core, "cache") and self._core.cache:
                freed = self._core.cache.purge_stream_cache(quota_bytes=quota_val * 1024 * 1024 * 1024 if quota_val > 0 else 0)
                details = self._core.cache.get_storage_details()
            else:
                details = {"quota_gb": quota_val, "used_bytes": 0}

            self._emit("storage_updated", details)
            return {"success": True, "freed_bytes": freed, "details": details}
        except Exception as e:
            logger.error(f"Error setting cache quota: {e}")
            return {"success": False, "error": str(e)}

    def clear_storage_cache(self) -> dict:
        """Safely clear temporary stream cache and cover caches."""
        try:
            if hasattr(self._core, "cache") and self._core.cache:
                self._core.cache.clear_all()
                details = self._core.cache.get_storage_details()
                self._emit("storage_updated", details)
                return {"success": True, "details": details}
            return {"success": False, "error": "Кэш-менеджер недоступен"}
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return {"success": False, "error": str(e)}

    def get_flow_tracks(self, seed_track: dict, limit: int = 6, exclude_ids: list = None) -> list:
        """
        Generate smart autoplay / flow tracks for continuous listening (Phase 3).
        Directly returns a list of tracks synchronously to the JS Promise (Decision 2).
        """
        if not seed_track or not isinstance(seed_track, dict):
            return []
        try:
            if hasattr(self._core, "recommendations") and self._core.recommendations:
                return self._core.recommendations.get_flow_tracks_sync(
                    seed_track=seed_track,
                    limit=limit,
                    exclude_ids=exclude_ids or []
                )
            return []
        except Exception as e:
            logger.warning(f"Flow tracks retrieval failed: {e}")
            return []



