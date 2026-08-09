"""
NeDotify - Web API Bridge
Exposes Python backend methods to the JavaScript frontend via pywebview.
"""


import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import webview

logger = logging.getLogger(__name__)

SECRET_KEY = b"NEDOTIFY_SECRET_SIGNATURE_KEY"

# Temporary feature flag: license validation and VK-based activation are disabled
# until they are replaced with a remote, server-owned licensing service.
LICENSE_VALIDATION_ENABLED = False


def _is_ssrf_safe_url(url: str) -> bool:
    """SSRF Protection: Validates external playlist import URLs to prevent internal network scanning."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        # Block localhost / loopback
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        # Block cloud metadata endpoint & private IP blocks
        if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168."):
            return False
        if hostname.startswith("172."):
            try:
                parts = hostname.split(".")
                second_octet = int(parts[1])
                if 16 <= second_octet <= 31:
                    return False
            except Exception:
                pass
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

        # Dedicated search executor for non-blocking provider and DB searches
        from concurrent.futures import ThreadPoolExecutor
        self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")

        # Connect engine event callbacks
        if hasattr(self._core, "engine") and self._core.engine:
            self._core.engine._on_track_changed = self._on_track_changed
            if hasattr(self._core.engine, "on_error"):
                self._core.engine.on_error(self._on_audio_error)

    def set_window(self, window):
        """Set main webview window reference."""
        self._window = window
        self._main_window = window
        if hasattr(self._window, 'events'):
            self._window.events.minimized += self._on_minimized
            self._window.events.restored += self._on_restored
            
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
            pass

    def _on_minimized(self):
        pass

    def _on_restored(self):
        pass

    def _set_window_pos_native(self, x, y, w, h, topmost=False):
        """Native Windows resize to bypass pywebview restrictions."""
        try:
            if not getattr(self._window, 'native', None):
                return False
            
            import ctypes
            form = self._window.native
            hwnd = form.Handle.ToInt64()
            hwnd_ptr = ctypes.c_void_p(hwnd)
            
            try:
                import clr
                clr.AddReference('System.Drawing')
                from System.Drawing import Size
                form.MinimumSize = Size(0, 0)
            except Exception:
                pass
                
            user32 = ctypes.windll.user32
            if user32.IsZoomed(hwnd_ptr) or user32.IsIconic(hwnd_ptr):
                user32.ShowWindowAsync(hwnd_ptr, 9)
                
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_ASYNCWINDOWPOS = 0x4000
            
            flags = SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS | SWP_SHOWWINDOW
            insert_after = ctypes.c_void_p(HWND_TOPMOST if topmost else HWND_NOTOPMOST)
            
            user32.SetWindowPos(hwnd_ptr, insert_after, int(x), int(y), int(w), int(h), flags)
            return True
        except Exception as e:
            logger.warning(f"Native SetWindowPos failed: {e}")
            return False

    def toggle_mini_player(self, enable: bool):
        """Switch view between main window and mini player window."""
        logger.info(f"toggle_mini_player called with enable={enable}")
        try:
            if enable:
                if self._window:
                    mini_w, mini_h = 360, 140
                    try:
                        import ctypes
                        user32 = ctypes.windll.user32
                        screen_w = user32.GetSystemMetrics(0)
                        x = (screen_w - mini_w) // 2
                        y = 20
                        
                        self._window.on_top = True
                        self._window.resize(mini_w, mini_h)
                        self._window.move(x, y)
                        
                        import threading
                        def _move():
                            import time
                            for _ in range(5):
                                time.sleep(0.05)
                                self._set_window_pos_native(x, y, mini_w, mini_h, topmost=True)
                        threading.Thread(target=_move, daemon=True).start()
                    except:
                        pass
            else:
                if self._window:
                    logger.info("Resizing window to 1100x800")
                    self._window.resize(1100, 800)
                    if hasattr(self._window, 'on_top'):
                        self._window.on_top = False
            return enable
        except Exception as e:
            logger.error(f"Error toggling mini player: {e}")

    def resize_mini_window(self, expanded: bool):
        """Resize mini player window dynamically."""
        logger.info(f"resize_mini_window called with expanded={expanded}")
        if self._window:
            w, h = (360, 420) if expanded else (360, 140)
            try:
                logger.info(f"Resizing mini window to {w}x{h}")
                self._window.resize(w, h)
                
                import threading
                def _force_resize():
                    import time
                    for _ in range(5):
                        time.sleep(0.05)
                        try:
                            import ctypes
                            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                            x = (screen_w - w) // 2
                            self._set_window_pos_native(x, 20, w, h, topmost=True)
                        except:
                            pass
                threading.Thread(target=_force_resize, daemon=True).start()
            except Exception as e:
                logger.error(f"Failed to resize mini window: {e}")

    def set_windows(self, main_window, mini_window):
        """Register dual window references for main player and mini player."""
        self._main_window = main_window
        self._mini_window = mini_window
        if not self._window:
            self._window = main_window

    def close(self):
        """Close window and shutdown application."""
        if self._window:
            self._window.destroy()

    def shutdown(self):
        """Release API-owned resources before the application exits."""
        self._window = None
        self._main_window = None
        self._mini_window = None

    def close_window(self):
        """Close application window."""
        self.close()

    def minimize(self):
        """Minimize application window."""
        if self._window:
            self._window.minimize()

    def minimize_window(self):
        """Minimize application window."""
        self.minimize()

    def maximize(self):
        """Toggle maximize/restore window state."""
        if self._window:
            self._window.toggle_fullscreen()

    def toggle_fullscreen(self):
        """Toggle window full-screen mode."""
        self.maximize()

    def start_drag(self):
        """Trigger native frameless window drag."""
        if self._window and hasattr(self._window, "start_drag"):
            try:
                self._window.start_drag()
            except Exception as e:
                logger.debug(f"Native drag failed: {e}")

    def resize_mini_window(self, expanded: bool):
        """Resize mini player window dynamically."""
        if self._mini_window:
            w, h = (380, 520) if expanded else (340, 130)
            try:
                self._mini_window.resize(w, h)
            except Exception as e:
                logger.error(f"Failed to resize mini window: {e}")

    def toggle_mini_player(self, enable: bool):
        """Switch view between main window and mini player window."""
        try:
            if enable:
                if self._window:
                    self._window.resize(380, 520)
            else:
                if self._window:
                    self._window.resize(1100, 800)
            return enable
        except Exception as e:
            logger.error(f"Error toggling mini player: {e}")

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

    def _on_track_changed(self, track):
        """Callback invoked whenever active track changes."""
        if not track:
            return

        track_copy = dict(track)
        # Proxy cloud stream URL if needed
        if track_copy.get("source") in ("youtube", "soundcloud", "yandex", "vk"):
            proxy_url = self._core.proxy.get_proxy_url(
                track_copy.get("source"),
                track_copy.get("source_id"),
                track_copy.get("file_path") or track_copy.get("source_url"),
                track_id=track_copy.get("id")
            )
            if proxy_url:
                track_copy["file_path"] = proxy_url

        self._emit("track_changed", track_copy)

    def _on_audio_error(self, err):
        """Callback invoked when audio engine encounters playback error."""
        self._emit("audio_error", {"message": str(err)})

    def report_state(self, state: str, elapsed_ms: int = 0):
        """Report playback state update (playing, paused, stopped)."""
        self._emit("state_changed", {"state": state, "elapsed_ms": elapsed_ms})

    def report_position(self, pos_ms: int, dur_ms: int = 0):
        """Report position update."""
        self._emit("position_changed", {"position_ms": pos_ms, "duration_ms": dur_ms})

    def play_track(self, track: dict, track_list: list = None, index: int = 0):
        """Play given track data object."""
        logger.info(f"api.py -> play_track called! track={track.get('title')}, has_track_list={bool(track_list)}")
        if track_list:
            if index == 0 and track:
                # Try to find the actual index of the clicked track
                t_id = track.get("id") or track.get("source_id") or track.get("file_path") or track.get("title")
                for i, t in enumerate(track_list):
                    c_id = t.get("id") or t.get("source_id") or t.get("file_path") or t.get("title")
                    if t_id and c_id and str(t_id) == str(c_id):
                        index = i
                        break
            self._core.engine.play_queue(track_list, index)
        else:
            self._resolve_track(track, lambda t: self._core.engine.play_track(t))

    def _resolve_track(self, track: dict, play_callback):
        """Resolve stream URL for online track before sending to player."""
        source = track.get("source", "local")
        source_id = track.get("source_id")

        if source == "local" or not source_id:
            play_callback(track)
            return

        # Check DB cached stream first
        cached = self._core.db.get_cached_stream(source, source_id)
        if cached and cached.get("stream_url"):
            track["file_path"] = cached["stream_url"]
            play_callback(track)
            return

        # Re-resolve stream url asynchronously
        def on_resolved(stream_url, metadata=None):
            logger.info(f"api.py -> on_resolved! stream_url={stream_url}")
            if stream_url:
                track["file_path"] = stream_url
                play_callback(track)
            else:
                self._on_audio_error(f"Could not resolve stream for {source}/{source_id}")

        self._core.re_resolve_stream_url_async(source, source_id, callback=on_resolved)

    def stop_track(self):
        """Stop audio playback."""
        pass # Handled by frontend

    def play_pause(self):
        """Toggle play/pause audio state."""
        pass # Handled by frontend

    def next_track(self):
        """Play next track in queue."""
        if hasattr(self._core.engine, 'next_track'):
            self._core.engine.next_track()

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

    def set_volume(self, volume: int):
        """Set playback volume (0-100)."""
        self._core.settings.set("audio", "volume", volume)

    def get_volume(self):
        """Return current volume level."""
        return self._core.settings.get("audio", "volume", 70)

    def report_position(self, pos_ms: int, duration_ms: int):
        """Called by JS to report playback position."""
        pass

    def report_state(self, state: str):
        """Called by JS to report playback state (playing/paused)."""
        pass

    def toggle_mute(self):
        """Toggle audio mute state."""
        return False # Handled by frontend

    def set_position(self, pos_ms: int):
        """Seek playback position in milliseconds."""
        pass # Handled by frontend

    def toggle_shuffle(self):
        """Toggle queue shuffle mode."""
        enabled = self._core.engine.toggle_shuffle()
        self._emit("shuffle_changed", enabled)
        return enabled

    def toggle_repeat(self):
        """Cycle repeat mode (off -> all -> one -> off)."""
        mode = self._core.engine.toggle_repeat()
        self._emit("repeat_changed", mode)
        return mode

    def search(self, query: str, source: str = "all", result_type: str = None):
        """Search without blocking the UI bridge. Providers run in parallel with 6s timeout each."""
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

        if source == "all":
            requested_providers = ["local", "youtube", "soundcloud", "spotify", "yandex", "vk"]
        elif source == "local":
            requested_providers = ["local"]
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

        # Async Local DB Search
        if "local" in requested_providers:
            def _run_local():
                try:
                    local_tracks = self._core.db.search_tracks(query)
                    emit_results(local_tracks, "local")
                except Exception as exc:
                    logger.error("Local search failed: %s", exc)
                    emit_results([], "local")
                finally:
                    mark_done("local")

            self._search_executor.submit(_run_local)

        # Async Remote Provider Searches — hard timeout per provider (12s)
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
                    logger.warning("%s search timed out after 12.0s", name)
                    _finish([])

                timer = threading.Timer(12.0, _on_timeout)
                timer.start()

                try:
                    srv.search(query, callback=_on_success, error_callback=_on_error)
                except Exception as exc:
                    logger.error("%s search could not start: %s", name, exc)
                    _finish([])

            self._search_executor.submit(_run_provider, service_name, service)

        return {"query": query, "tracks": []}

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

    def create_playlist(self, name: str, description: str = ""):
        """Create new user playlist."""
        pid = self._core.db.create_playlist(name, description)
        self._emit("playlists_updated", self.get_playlists())
        return pid

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

    def get_playlist_tracks(self, playlist_id: int):
        """Get tracks for specified playlist."""
        return self._core.db.get_playlist_tracks(playlist_id)

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
        """Mark onboarding complete and save preferences."""
        self._core.settings.set("app", "onboarding_completed", True)
        if isinstance(settings_data, dict):
            for k, v in settings_data.items():
                self._core.settings.set("app", k, v)
        return True

    def update_autostart(self, enabled: bool):
        """Toggle app autostart registry entry on Windows."""
        if sys.platform != "win32":
            return False
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            app_name = "NeDotify"
            if enabled:
                exe_path = f'"{sys.executable}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            self._core.settings.set("app", "autostart", enabled)
            return True
        except Exception as e:
            logger.error(f"Failed to update autostart: {e}")
            return False

    def validate_subscription_key(self, key: str):
        """Stub: license system removed for open source."""
        return {"valid": True, "is_valid": True, "success": True, "expire": "never", "valid_until": 0}

    def get_subscription_info(self):
        """Stub: license system removed for open source."""
        return {"valid": True, "is_valid": True, "success": True, "expire": "never", "valid_until": 0, "key": "OPEN-SOURCE"}

    def get_settings(self, category: str = None):
        """Get settings dict."""
        if category:
            return self._core.settings.get_category(category)
        
        if hasattr(self._core.settings, 'get_all'):
            return self._core.settings.get_all()
            
        if hasattr(self._core.settings, '_settings'):
            import copy
            return copy.deepcopy(self._core.settings._settings)
            
        categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay', 'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance', 'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services', 'session', 'subscription']
        res = {}
        for c in categories:
            try:
                cat_data = self._core.settings.get_category(c)
                if cat_data:
                    res[c] = cat_data
            except:
                pass
        return res

    def save_setting(self, key: str, value, category: str = "app"):
        """Save a setting value."""
        self._core.settings.set(category, key, value)
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

    def get_storage_info(self):
        """Get cache & downloaded storage size info."""
        try:
            cache_dir = self._core.cache.cache_dir
            total_bytes = 0
            for root, dirs, files in os.walk(cache_dir):
                for f in files:
                    total_bytes += os.path.getsize(os.path.join(root, f))
            return {"total_size_mb": round(total_bytes / (1024 * 1024), 2), "cache_dir": cache_dir}
        except Exception as e:
            return {"total_size_mb": 0, "error": str(e)}

    def clear_storage(self, storage_type: str = "cache"):
        """Clear cache or storage folder."""
        try:
            if storage_type in ("cache", "all"):
                self._core.cache.clear_all()
            return True
        except Exception as e:
            logger.error(f"Clear storage failed: {e}")
            return False

    def get_equalizer(self):
        """Get equalizer preamp and bands."""
        return {
            "preamp": self._core.settings.get("equalizer", "preamp", 0),
            "bands": self._core.settings.get("equalizer", "bands", [0] * 10)
        }

    def set_equalizer(self, preamp: float = 0, bands: list = None):
        """Set equalizer settings."""
        self._core.settings.set("equalizer", "preamp", preamp)
        if bands:
            self._core.settings.set("equalizer", "bands", bands)
        if hasattr(self._core.engine, "set_equalizer"):
            self._core.engine.set_equalizer(preamp, bands)
        return True

    def get_lyrics(self, track_name: str, artist_name: str, duration_ms: int = 0, file_path: str = None):
        """Get lyrics for track."""
        try:
            return self._core.lyrics.get_lyrics(track_name, artist_name, duration_ms=duration_ms, file_path=file_path)
        except Exception as e:
            return {"synced": False, "lyrics": f"Could not fetch lyrics: {e}"}

    def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
        """Get translation for lyrics text."""
        try:
            return self._core.lyrics.translate(lyrics_text, target_lang=target_lang)
        except Exception as e:
            return {"error": str(e)}

    def get_home_data(self):
        """Get home feed dashboard statistics and data."""
        return {
            "history": self._core.db.get_history(limit=10),
            "favorites_count": len(self.get_favorite_tracks()),
            "total_listening_ms": self._core.db.get_total_listening_time(),
            "total_tracks": len(self._core.db.get_all_tracks()),
            "playlists": self.get_playlists()
        }

    def get_popular_tracks(self, region: str = "US"):
        """Request popular tracks and deliver them through the frontend event contract."""
        fallback = self._core.db.get_history(limit=10)
        try:
            provider = getattr(self._core.recommendations, "get_charts", None)
            if provider:
                provider(region, callback=lambda tracks: self._emit("popular_results", tracks or fallback))
            else:
                self._core.recommendations.get_releases(
                    [region], callback=lambda tracks: self._emit("popular_results", tracks or fallback)
                )
        except Exception as exc:
            logger.info("Popular tracks fallback: %s", exc)
            self._emit("popular_results", fallback)
        return []

    def get_authentic_home_feed(self, limit: int = 20):
        """Get personalized home feed recommendations."""
        history = self._core.db.get_history(limit=limit)
        return self._core.recommendations.get_feed(history)

    def get_yt_playlist_tracks(self, playlist_id: str, limit: int = 50):
        """Get YouTube playlist tracks."""
        try:
            return self._core.youtube.get_playlist_tracks(playlist_id, limit=limit)
        except Exception as e:
            return []

    def get_profile_stats(self):
        """Get profile stats."""
        return {
            "total_tracks": len(self._core.db.get_all_tracks()),
            "favorite_count": len(self.get_favorite_tracks()),
            "playlist_count": len(self.get_playlists()),
            "total_listening_time_ms": self._core.db.get_total_listening_time(),
            "most_played": self._core.db.get_most_played(limit=5),
            "recently_played": self._core.db.get_history(limit=5)
        }

    def select_avatar(self):
        """Open native file dialog to select avatar image."""
        if not self._window:
            return None
        try:
            res = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=("Image Files (*.jpg;*.png;*.webp)",))
            if res and len(res) > 0:
                src = res[0]
                avatars_dir = os.path.join(self._core.cache.cache_dir, "avatars")
                os.makedirs(avatars_dir, exist_ok=True)
                ext = os.path.splitext(src)[1]
                dest = os.path.join(avatars_dir, f"avatar_{int(time.time())}{ext}")
                shutil.copy(src, dest)
                self._core.settings.set("app", "avatar_path", dest)
                return dest
        except Exception as e:
            logger.error(f"Select avatar error: {e}")
        return None

    def create_local_playlist(self, name: str, tracks: list = None):
        """Create a playlist from supplied tracks or the current local library."""
        pid = self.create_playlist(name)
        for track in (tracks if tracks is not None else self._core.db.get_all_tracks(source="local")):
            self.add_to_playlist(pid, track)
        return pid

    def open_local_file(self):
        """Open native file dialog to select and play/import local audio file(s)."""
        if not self._window:
            return False
        try:
            file_types = ("Audio Files (*.mp3;*.flac;*.wav;*.ogg;*.m4a)", "All Files (*.*)")
            res = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True, file_types=file_types)
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

    def get_recommendations(self, track_data: dict, max_results: int = 10):
        """Get recommended tracks for seed track."""
        res = []
        self._core.recommendations.get_recommendations(track_data, callback=lambda tracks: res.extend(tracks))
        return res[:max_results]

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
        """Get top artists for home page."""
        artists = self._core.db.get_top_artists(limit=max_results)
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
                res = self._core.zapret.start(mode=mode, custom_args=custom_args, binary_path=binary_path)
            else:
                res = self._core.zapret.stop()
            self._core.settings.set("zapret", "enabled", enabled)
            self._core.settings.set("zapret", "mode", mode)
            return {"success": res}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_zapret_status(self):
        """Get current Zapret service status."""
        try:
            return {"running": self._core.zapret.is_running(), "mode": self._core.settings.get("zapret", "mode", "youtube_discord")}
        except Exception as e:
            return {"running": False, "error": str(e)}
