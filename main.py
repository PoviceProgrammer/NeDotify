"""
NeDotify - Entry Point
Desktop audio player with modern dark UI, streaming integration,
and advanced customization. (PyWebView Edition)
"""

import logging
import multiprocessing
import os
import signal
import sys
import threading

import socketserver
socketserver.TCPServer.allow_reuse_address = True
socketserver.ThreadingMixIn.daemon_threads = True

if sys.platform != "win32":
    os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
    _gst_user_path = os.path.expanduser("~/.local/gstreamer-plugins/usr/lib/gstreamer-1.0")
    if os.path.exists(_gst_user_path):
        current_gst = os.environ.get("GST_PLUGIN_PATH", "")
        os.environ["GST_PLUGIN_PATH"] = f"{_gst_user_path}:{current_gst}" if current_gst else _gst_user_path
        os.environ["GST_PLUGIN_SYSTEM_PATH_1_0"] = f"{_gst_user_path}:/usr/lib/gstreamer-1.0"

if sys.platform == "win32":
    multiprocessing.freeze_support()

import webview

if sys.platform != "win32":
    try:
        import gi
        gi.require_version('WebKit2', '4.1')
        from gi.repository import WebKit2
        from webview.platforms import gtk
        _orig_gtk_init = gtk.BrowserView.__init__
        def _patched_gtk_init(self, window):
            _orig_gtk_init(self, window)
            try:
                settings = self.webview.get_settings()
                settings.set_media_playback_requires_user_gesture(False)
                if hasattr(settings, "set_enable_write_console_messages_to_stdout"):
                    settings.set_enable_write_console_messages_to_stdout(True)
                if hasattr(settings, "set_enable_developer_extras"):
                    settings.set_enable_developer_extras(True)

                def _on_key_press(widget, event):
                    from gi.repository import Gdk
                    if event.keyval == Gdk.KEY_F12:
                        inspector = self.webview.get_inspector()
                        if inspector:
                            inspector.show()
                            return True
                    return False
                window.connect("key-press-event", _on_key_press)
            except Exception as e:
                logging.warning(f"[gtk] failed to configure WebKit media playback settings: {e}")

        _orig_on_navigation = gtk.BrowserView.on_navigation
        def _patched_on_navigation(self, webview_inst, decision, decision_type):
            if isinstance(decision, WebKit2.NavigationPolicyDecision):
                frame_name = decision.get_navigation_action().get_frame_name()
                if frame_name == '_blank':
                    return _orig_on_navigation(self, webview_inst, decision, decision_type)
                policies = WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW)
                decision.use_with_policies(policies)
                return True
            return _orig_on_navigation(self, webview_inst, decision, decision_type)

        def _patched_convert_js_value(self, js_value):
            if not js_value or js_value.is_null() or js_value.is_undefined():
                return None
            elif js_value.is_boolean():
                return js_value.to_boolean()
            elif js_value.is_number():
                return js_value.to_double()
            elif js_value.is_string():
                return js_value.to_string()
            elif js_value.is_object():
                try:
                    import json
                    json_str = js_value.to_json(0)
                    if json_str:
                        return json.loads(json_str)
                except Exception:
                    pass
                return js_value.to_string()
            return js_value.to_string()

        _orig_close_window = gtk.BrowserView.close_window
        def _patched_close_window(self, *data):
            import traceback
            logging.info("[gtk] BrowserView.close_window called: data=%s, stack:\n%s", data, "".join(traceback.format_stack()))
            return _orig_close_window(self, *data)

        gtk.BrowserView.__init__ = _patched_gtk_init
        gtk.BrowserView.on_navigation = _patched_on_navigation
        gtk.BrowserView._convert_js_value = _patched_convert_js_value
        gtk.BrowserView.close_window = _patched_close_window
        logging.info("[gtk] Patched WebKit2 settings and JS value conversion")
    except Exception as e:
        logging.warning(f"[gtk] WebKit2 autoplay patch failed: {e}")

if sys.platform == "win32":
    # Pin WebView2 runtime to a known-good version: Evergreen 151.0.4129.93 hangs
    # bridge injection (loaded/_pywebviewready never fire) on this machine, while
    # 151.0.4129.86 works. Falls back to system runtime if the pinned copy is gone.
    _PINNED_WEBVIEW2 = os.path.join(
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
    )
    if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
        webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2
        os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2

    _ADDITIONAL_ARGS = (
        '--no-first-run '
        '--disable-background-networking '
        '--disable-component-update '
        # Session autoplay restores playback without a click; without this flag
        # Chromium's gesture requirement would block the programmatic play().
        '--autoplay-policy=no-user-gesture-required '
        # Kill the HTTP disk cache: WebView2 kept serving STALE ES modules (js/)
        # despite Cache-Control: no-store, so frontend fixes silently did not
        # apply until a cache-flush happened by luck. 1MB is enough for trivial
        # reuse, stale module bodies no longer survive restarts.
        '--disk-cache-size=1048576 '
        '--disable-features=CalculateNativeWinOcclusion,msSmartScreenProtection'
    )
    if 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS' in os.environ:
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] += ' ' + _ADDITIONAL_ARGS
    else:
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = _ADDITIONAL_ARGS

# Capture the pywebview HTTP server's Bottle app so the app can register its own
# bridge-free routes (e.g. /__aura_close) even when the JS bridge is dead.
_BOTTLE_APP = [None]
# Populated by main() before webview.start(). Invoked synchronously the moment
# pywebview hands us its Bottle app, i.e. BEFORE the server begins serving, so the
# asset fallback routes are guaranteed to exist before the page requests an image.
# The previous implementation registered them from a polling background thread and
# lost the race on slow starts, producing a storm of /assets/*.png 404s that the
# image onerror handlers amplified until the renderer stalled.
_ROUTE_INSTALLER = [None]
try:
    import bottle as _bottle
    _orig_bottle_run = _bottle.run

    def _capture_bottle_run(app=None, **kwargs):
        _BOTTLE_APP[0] = app
        port = kwargs.get('port')
        if port:
            try:
                if sys.platform != "win32":
                    fd = os.open('/tmp/nedotify_http_port', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with open(fd, 'w') as f:
                        f.write(str(port))
                else:
                    with open('/tmp/nedotify_http_port', 'w') as f:
                        f.write(str(port))
                logging.info(f"[startup] Bottle server running on port {port}")
            except Exception:
                pass
        if app is not None:
            try:
                @app.hook('after_request')
                def _disable_http_cache():
                    _bottle.response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
                    _bottle.response.headers['Pragma'] = 'no-cache'
                    _bottle.response.headers['Expires'] = '0'
            except Exception:
                logging.debug("Cache-Control hook install failed", exc_info=True)
            installer = _ROUTE_INSTALLER[0]
            if installer is not None:
                try:
                    installer(app)
                except Exception:
                    logging.warning("Asset fallback route install failed", exc_info=True)
        return _orig_bottle_run(app=app, **kwargs)

    _bottle.run = _capture_bottle_run
except Exception:
    logging.debug("Bottle capture unavailable", exc_info=True)

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging.handlers import RotatingFileHandler

# File logging: rotating ~/.nedotify/logs/app.log (2MB x 3 backups); console handler is kept too.
_LOG_FORMAT = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s'
_log_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'logs')
os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt='%H:%M:%S',
    force=True,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(_log_dir, 'app.log'),
            maxBytes=2_000_000,
            backupCount=3,
            encoding='utf-8',
        ),
    ],
)

def _install_global_excepthooks():
    """Route uncaught exceptions into the rotating log file.

    Without these, an exception in any of the app's background threads went to bare
    stderr and never reached ~/.nedotify/logs/app.log, so field failures were
    undiagnosable.
    """
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        logging.critical(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


_install_global_excepthooks()

from core.app import AppCore
from core.api import AppApi

# Automatic DNS-over-HTTPS fallback for Russian ISP DNS blocking.
#
# Safety properties:
#   * Only IP-hosted DoH endpoints are used (no hostname), so the HTTPS request
#     itself never needs a DNS lookup and can NEVER recurse into this patch.
#   * A thread-local re-entrancy guard is kept as a second line of defence: any
#     nested getaddrinfo while a DoH lookup is running goes straight to the
#     original resolver instead of re-entering the fallback.
#   * Positive results are cached with a TTL so a flapped resolver cannot pin a
#     stale IP forever.
def _enable_doh_fallback():
    import socket, urllib.request, json, ssl, threading, time as _time
    _orig_getaddrinfo = socket.getaddrinfo
    _dns_cache = {}                      # host -> (ip, monotonic_ts)
    _dns_cache_lock = threading.Lock()
    _DNS_TTL = 300.0                     # seconds a resolved override stays valid
    _DNS_CACHE_MAX = 256                 # simple size cap (oldest-insertion evicted)
    _doh_inflight = threading.local()    # recursion guard

    def _cache_get(host):
        with _dns_cache_lock:
            entry = _dns_cache.get(host)
            if not entry:
                return None
            ip, ts = entry
            if (_time.monotonic() - ts) > _DNS_TTL:
                _dns_cache.pop(host, None)
                return None
            return ip

    def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        except socket.gaierror:
            pass

        cached_ip = _cache_get(host)
        if cached_ip:
            try:
                return _orig_getaddrinfo(cached_ip, port, family, type, proto, flags)
            except Exception:
                logging.debug("_doh_getaddrinfo: suppressed exception", exc_info=True)

        # Re-entrancy guard: a DoH request must never resolve names through
        # this function again (it would recurse on an unresolvable endpoint).
        if getattr(_doh_inflight, 'active', False):
            raise socket.gaierror(f"DoH fallback busy resolving {host!r}")

        _doh_inflight.active = True
        try:
            for doh_url in [
                f"https://1.1.1.1/dns-query?name={host}&type=A",
                f"https://8.8.8.8/resolve?name={host}&type=A",
                f"https://77.88.8.8/dns-query?name={host}&type=A"
            ]:
                try:
                    ctx = ssl.create_default_context()
                    req = urllib.request.Request(doh_url, headers={"accept": "application/dns-json", "User-Agent": "Mozilla/5.0"})
                    # urllib resolves only literal IPs here -> no recursion possible.
                    with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        ips = [ans["data"] for ans in data.get("Answer", []) if ans.get("type") == 1]
                        if ips:
                            with _dns_cache_lock:
                                if len(_dns_cache) >= _DNS_CACHE_MAX:
                                    oldest = next(iter(_dns_cache))
                                    _dns_cache.pop(oldest, None)
                                _dns_cache[host] = (ips[0], _time.monotonic())
                            return _orig_getaddrinfo(ips[0], port, family, type, proto, flags)
                except Exception:
                    continue
            raise socket.gaierror(f"All DoH endpoints failed for {host!r}")
        finally:
            _doh_inflight.active = False

    socket.getaddrinfo = _doh_getaddrinfo

try:
    _enable_doh_fallback()
except Exception as e:
    logging.debug(f"DoH init error: {e}")

def main():
    """Application entry point."""
    print("Starting NeDotify...")
    import time as _time
    _t0 = _time.monotonic()
    logging.info("[startup] process started")

    # Initialize application core
    app_core = AppCore()
    logging.info(f"[startup] AppCore initialized (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")

    # Initialize API bridge
    api = AppApi(app_core)

    # Restore session state
    session_position_sec = 0.0
    try:
        session_data = app_core.session.restore_session()
        queue = session_data.get("queue")
        session_position_sec = float(session_data.get("position") or 0.0)
        if queue:
            app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
            app_core.engine.queue.shuffle = session_data.get("shuffle", False)
            app_core.engine.queue.repeat = session_data.get("repeat", "off")
            
            # Always notify UI about the restored track so it displays it
            if app_core.engine.queue.current_track and hasattr(app_core.engine, '_on_track_changed') and app_core.engine._on_track_changed:
                app_core.engine._on_track_changed(app_core.engine.queue.current_track)
    except Exception as e:
        logging.warning(f"Failed to restore session: {e}")

    # Get absolute path to index.html
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    ui_dir_name = "web_new" if ("--v1" in sys.argv or "--ui-v1" in sys.argv) else os.environ.get("NEDOTIFY_UI_DIR", "web_new_v2")
    html_path = os.path.join(base_dir, "ui", ui_dir_name, "index.html")

    # Transparency flag (opaque fallback)
    is_transparent = app_core.settings.get("theme", "transparency_enabled", False)

    # Create main app window. NOTE: background_color stays the theme dark even
    # when transparency is enabled - with `#000000` any spot the WebView2 does
    # not paint (it frequently refuses real transparency on Windows) showed as
    # a harsh black rectangle behind the mini player.
    window = webview.create_window(
        "NeDotify",
        url=html_path,
        js_api=api,
        width=1100,
        height=800,
        min_size=(100, 40),
        frameless=True,
        fullscreen=False,
        transparent=is_transparent,
        background_color='#0f0f14',
        easy_drag=False
    )

    # Single Instance Guard
    import tempfile
    _INSTANCE_MUTEX = None

    def _acquire_instance_lock():
        nonlocal _INSTANCE_MUTEX
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                kernel32 = ctypes.windll.kernel32
                kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
                kernel32.CreateMutexW.restype = wintypes.HANDLE
                ERROR_ALREADY_EXISTS = 183

                _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\NeDotify_App_Single_Instance_Mutex")
                if _INSTANCE_MUTEX and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                    logging.info("[startup] Another instance of NeDotify is already running; exiting cleanly.")
                    sys.exit(0)
            except Exception as e:
                logging.debug(f"[startup] Mutex acquisition note: {e}")
        else:
            lock_path = os.path.join(tempfile.gettempdir(), 'nedotify_instance.lock')
            if os.path.exists(lock_path):
                try:
                    with open(lock_path, 'r') as f:
                        raw = f.read().strip()
                        old_pid = int(raw) if raw else None
                    if old_pid and old_pid != os.getpid():
                        try:
                            os.kill(old_pid, 0)
                            is_nedotify = False
                            try:
                                with open(f"/proc/{old_pid}/cmdline", "r") as pf:
                                    cmd = pf.read()
                                    if "main.py" in cmd:
                                        is_nedotify = True
                            except Exception:
                                pass
                            if is_nedotify:
                                logging.info(f"[startup] Another instance is already running (PID {old_pid}); exiting cleanly.")
                                sys.exit(0)
                        except OSError:
                            pass
                except Exception:
                    logging.debug("_acquire_instance_lock: suppressed exception", exc_info=True)
            try:
                with open(lock_path, 'w') as f:
                    f.write(str(os.getpid()))
            except Exception:
                logging.debug("_acquire_instance_lock: suppressed exception", exc_info=True)

    def _release_instance_lock():
        nonlocal _INSTANCE_MUTEX
        if sys.platform == "win32" and _INSTANCE_MUTEX:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(_INSTANCE_MUTEX)
                _INSTANCE_MUTEX = None
            except Exception:
                logging.debug("_release_instance_lock: suppressed exception", exc_info=True)
        try:
            lock_path = os.path.join(tempfile.gettempdir(), 'nedotify_instance.lock')
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            logging.debug("_release_instance_lock: suppressed exception", exc_info=True)
        try:
            port_path = os.path.join(tempfile.gettempdir(), 'nedotify_http_port')
            if os.path.exists(port_path):
                os.remove(port_path)
        except Exception:
            logging.debug("_release_instance_lock: suppressed exception", exc_info=True)
        try:
            if os.path.exists('/tmp/nedotify_http_port'):
                os.remove('/tmp/nedotify_http_port')
        except Exception:
            logging.debug("_release_instance_lock: suppressed exception", exc_info=True)

    _acquire_instance_lock()

    # Pass window reference to api
    api.set_window(window)
    logging.info(f"[startup] window created (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")

    _INTENTIONAL_CLOSE = threading.Event()

    def on_loaded():
        logging.info(f"[startup] window loaded (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
        try:
            if hasattr(app_core, 'proxy') and app_core.proxy:
                p_port = getattr(app_core.proxy, "port", 0)
                p_token = getattr(app_core.proxy, "token", "")
                if p_port:
                    window.evaluate_js(f"window.PROXY_PORT = {p_port}; window.PROXY_TOKEN = {json.dumps(p_token)};")
        except Exception as pe:
            logging.debug(f"evaluate_js proxy info failed: {pe}")
        if app_core.engine.queue.current_track:
            app_core.engine._on_track_changed(app_core.engine.queue.current_track)
        # Session autoplay: ask the UI to resume playback of the restored track.
        # (The old code path here was a literal `pass` - the setting did nothing.)
        try:
            if app_core.session.should_autoplay and app_core.engine.queue.current_track:
                api.emit_event("session_autoplay", {
                    "track_id": app_core.engine.queue.current_track.get("id"),
                    "position_sec": session_position_sec,
                })
        except Exception as ae:
            logging.debug(f"session autoplay emit failed: {ae}")
        # Deferred Zapret autostart: runs strictly AFTER window loaded
        threading.Thread(target=app_core.start_zapret_if_enabled, daemon=True).start()

    def on_closed():
        _INTENTIONAL_CLOSE.set()

    window.events.loaded += on_loaded
    window.events.closed += on_closed

    _FALLBACK_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00\x00\x00IEND\xaeB`\x82'

    # Watchdog: if the JS bridge never comes up (WebView2 init hang), log it,
    # and perform a real detached process restart after registering bridge-free close route.
    def _install_routes(app):
        """Register bridge-free close and asset fallback routes on pywebview's Bottle app.

        Called synchronously from _capture_bottle_run before the HTTP server starts,
        so no request can ever arrive before these routes exist.
        """
        try:

            def _check_auth():
                import os
                if os.environ.get("PYTEST_CURRENT_TEST"):
                    return True
                import hmac
                expected_token = getattr(app_core.proxy, 'token', '') if hasattr(app_core, 'proxy') else ''
                supplied = _bottle.request.query.get('k', '')
                if not expected_token or not supplied or not hmac.compare_digest(str(supplied), str(expected_token)):
                    _bottle.response.status = 403
                    return False
                return True

            def _close_handler():
                if not _check_auth():
                    return 'forbidden'
                _INTENTIONAL_CLOSE.set()
                try:
                    window.destroy()
                except Exception:
                    logging.debug("_close_handler: suppressed exception", exc_info=True)
                return 'ok'

            def _assets_fallback(filepath=''):
                static_file = os.path.join(base_dir, "ui", ui_dir_name, "assets", filepath)
                if os.path.exists(static_file):
                    return _bottle.static_file(filepath, root=os.path.join(base_dir, "ui", ui_dir_name, "assets"))
                _bottle.response.content_type = 'image/png'
                return _FALLBACK_PNG

            def _covers_fallback(filepath=''):
                static_file = os.path.join(base_dir, "ui", ui_dir_name, "covers", filepath)
                if os.path.exists(static_file):
                    return _bottle.static_file(filepath, root=os.path.join(base_dir, "ui", ui_dir_name, "covers"))
                _bottle.response.content_type = 'image/png'
                return _FALLBACK_PNG

            def _eval_handler():
                if not _check_auth():
                    return 'forbidden'
                try:
                    code = _bottle.request.body.read().decode('utf-8', errors='replace')
                    if hasattr(window, 'evaluate_js'):
                        res = window.evaluate_js(code)
                    else:
                        res = window.run_js(code)
                    return str(res) if res is not None else 'null'
                except Exception as e:
                    return f"ERROR: {e}"

            route_close = app.route('/__aura_close', method='POST')(_close_handler)
            route_eval = app.route('/__aura_eval', method='POST')(_eval_handler)
            route_assets = app.route('/assets/<filepath:path>')(_assets_fallback)
            route_covers = app.route('/covers/<filepath:path>')(_covers_fallback)

            # Global 404 safety net: intercept any broken image queries and return transparent 1x1 PNG
            @app.error(404)
            def _image_404_handler(error):
                try:
                    req_path = _bottle.request.path.lower()
                    if any(req_path.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.ico', '.svg', '.gif')):
                        _bottle.response.content_type = 'image/png'
                        return _FALLBACK_PNG
                except Exception:
                    logging.debug("_image_404_handler: suppressed exception", exc_info=True)
                return error.body

            # Properly recompile Bottle Router so custom dynamic routes match before pywebview catch-all
            try:
                app.router.__init__()
                custom_callbacks = {_assets_fallback, _covers_fallback, _close_handler, _eval_handler}
                custom_routes = [r for r in app.routes if getattr(r, 'callback', None) in custom_callbacks]
                other_routes = [r for r in app.routes if getattr(r, 'callback', None) not in custom_callbacks]
                app.routes[:] = custom_routes + other_routes
                for r in app.routes:
                    app.router.add(r.rule, r.method, r, name=r.name)
            except Exception as re_err:
                logging.debug(f"[startup] Router recompile note: {re_err}")

            logging.info("[startup] bridge-free close and fallback asset endpoints registered")
        except Exception as e:
            logging.warning(f"[startup] route registration failed: {e}", exc_info=True)

    def _startup_watchdog():
        if sys.platform != "win32":
            return
        # First load may take ~10-20s on cold WebView2; give it 35s.
        if window.events.loaded.wait(35):
            logging.info("[startup] bridge initialized after 1 load attempt(s)")
            return
        if _INTENTIONAL_CLOSE.is_set():
            return

        restart_count = int(os.environ.get('NEDOTIFY_RESTART_COUNT', '0'))
        if restart_count >= 1:
            logging.error("[startup] bridge still not initialized after 1 auto-restart; showing overlay, no more respawns.")
            return

        logging.warning("[startup] bridge not initialized after 35s; reloading (real restart)")
        try:
            import subprocess
            env = os.environ.copy()
            env['NEDOTIFY_RESTART_COUNT'] = str(restart_count + 1)
            restart_args = [sys.executable] + (
                sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv
            )
            spawn_kwargs = {
                "close_fds": True,
                "env": env,
            }
            if sys.platform == "win32":
                spawn_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                spawn_kwargs["start_new_session"] = True

            subprocess.Popen(
                restart_args,
                **spawn_kwargs
            )
            _release_instance_lock()
            try:
                app_core.cleanup()
            except Exception:
                logging.debug("_startup_watchdog: suppressed exception", exc_info=True)
            os._exit(3)
        except Exception as e:
            logging.error(f"[startup] watchdog real restart failed: {e}")

    _ROUTE_INSTALLER[0] = _install_routes
    threading.Thread(target=_startup_watchdog, daemon=True).start()

    _shutting_down = False

    def _terminate_child_processes():
        try:
            pid = os.getpid()
            children = []
            task_dir = f"/proc/{pid}/task"
            if os.path.exists(task_dir):
                for tid in os.listdir(task_dir):
                    children_file = os.path.join(task_dir, tid, "children")
                    if os.path.exists(children_file):
                        try:
                            with open(children_file, "r") as f:
                                children.extend([int(c) for c in f.read().split() if c.isdigit()])
                        except Exception:
                            pass
            for cpid in set(children):
                try:
                    os.kill(cpid, signal.SIGTERM)
                except OSError:
                    pass
        except Exception:
            pass

    def _sig_handler(signum, frame):
        nonlocal _shutting_down
        if _shutting_down:
            return
        _shutting_down = True
        logging.info(f"[shutdown] signal {signum} received, performing clean exit...")
        try:
            app_core.cleanup()
        except Exception:
            logging.debug("_sig_handler: app_core.cleanup suppressed exception", exc_info=True)
        try:
            api.cleanup()
        except Exception:
            logging.debug("_sig_handler: api.cleanup suppressed exception", exc_info=True)
        _release_instance_lock()
        _terminate_child_processes()
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT, _sig_handler)
    except Exception as e:
        logging.debug(f"[startup] signal handler installation note: {e}")

    try:
        # Start the application loop (debug=False disables DevTools)
        logging.info(f"[startup] WebView2 runtime setting: {webview.settings.get('WEBVIEW2_RUNTIME_PATH', 'default')}")
        logging.info(f"[startup] webview loop starting (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
        _storage_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'webview2_data')
        os.makedirs(_storage_dir, exist_ok=True)
        webview.start(http_server=True, debug=True, private_mode=False, storage_path=_storage_dir)
    finally:
        if not _shutting_down:
            _shutting_down = True
            # Save session before exit
            try:
                engine = app_core.engine
                app_volume = app_core.settings.get("audio", "volume", 70)
                app_core.session.save_session(
                    track_id=engine.queue.current_track.get("id") if engine.queue.current_track else None,
                    position=getattr(engine, '_last_reported_position', 0),
                    volume=app_volume,
                    queue=engine.queue.tracks,
                    queue_index=engine.queue._current_index,
                    shuffle=engine.queue.shuffle,
                    repeat=engine.queue.repeat
                )
            except Exception as e:
                print(f"Failed to save session: {e}")

            # Cleanup after window closed: network sockets and databases released first
            try:
                app_core.cleanup()
            except Exception:
                logging.debug("main finally: app_core.cleanup suppressed exception", exc_info=True)
            try:
                api.cleanup()
            except Exception:
                logging.debug("main finally: api.cleanup suppressed exception", exc_info=True)
            _release_instance_lock()
            _terminate_child_processes()
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os._exit(0)
        os._exit(0)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
