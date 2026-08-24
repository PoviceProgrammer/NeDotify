"""
NeDotify - Entry Point
Desktop audio player with modern dark UI, streaming integration,
and advanced customization. (PyWebView Edition)
"""

import logging
import multiprocessing
import os
import sys
import threading

if sys.platform == "win32":
    multiprocessing.freeze_support()

import webview

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

# Automatic DNS-over-HTTPS fallback for Russian ISP DNS blocking
def _enable_doh_fallback():
    import socket, urllib.request, json, ssl
    _orig_getaddrinfo = socket.getaddrinfo
    _dns_cache = {}

    def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        except socket.gaierror:
            if host in _dns_cache:
                try:
                    return _orig_getaddrinfo(_dns_cache[host], port, family, type, proto, flags)
                except Exception:
                    logging.debug("_doh_getaddrinfo: suppressed exception", exc_info=True)
            for doh_url in [
                f"https://1.1.1.1/dns-query?name={host}&type=A",
                f"https://dns.google/resolve?name={host}&type=A",
                f"https://77.88.8.8/dns-query?name={host}&type=A"
            ]:
                try:
                    ctx = ssl.create_default_context()
                    req = urllib.request.Request(doh_url, headers={"accept": "application/dns-json", "User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        ips = [ans["data"] for ans in data.get("Answer", []) if ans.get("type") == 1]
                        if ips:
                            _dns_cache[host] = ips[0]
                            return _orig_getaddrinfo(ips[0], port, family, type, proto, flags)
                except Exception:
                    continue
            raise

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
    try:
        session_data = app_core.session.restore_session()
        queue = session_data.get("queue")
        if queue:
            app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
            app_core.engine.queue.shuffle = session_data.get("shuffle", False)
            app_core.engine.queue.repeat = session_data.get("repeat", "off")
            
            # Always notify UI about the restored track so it displays it
            if app_core.engine.queue.current_track and hasattr(app_core.engine, '_on_track_changed') and app_core.engine._on_track_changed:
                app_core.engine._on_track_changed(app_core.engine.queue.current_track)

            # If autoplay is enabled, start playback
            if app_core.session.should_autoplay and app_core.engine.queue.current_track:
                pass
    except Exception as e:
        print(f"Failed to restore session: {e}")

    # Get absolute path to index.html
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    ui_dir_name = "web_new_v2" if ("--v2" in sys.argv or "--ui-v2" in sys.argv) else os.environ.get("NEDOTIFY_UI_DIR", "web_new")
    html_path = os.path.join(base_dir, "ui", ui_dir_name, "index.html")

    # Transparency flag (opaque fallback)
    is_transparent = app_core.settings.get("theme", "transparency_enabled", False)

    # Create main app window (solid dark background, 100% stable, no white box)
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
        background_color='#000000' if is_transparent else '#0f0f14',
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
                        old_pid = int(f.read().strip())
                    if old_pid != os.getpid():
                        try:
                            os.kill(old_pid, 0)
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

    _acquire_instance_lock()

    # Pass window reference to api
    api.set_window(window)
    logging.info(f"[startup] window created (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")

    _INTENTIONAL_CLOSE = threading.Event()

    def on_loaded():
        logging.info(f"[startup] window loaded (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
        if app_core.engine.queue.current_track:
            app_core.engine._on_track_changed(app_core.engine.queue.current_track)
        # Deferred Zapret autostart: runs strictly AFTER window loaded
        threading.Thread(target=app_core.start_zapret_if_enabled, daemon=True).start()

    def on_closed():
        _INTENTIONAL_CLOSE.set()
        _release_instance_lock()

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

            def _close_handler():
                _INTENTIONAL_CLOSE.set()
                _release_instance_lock()
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

            route_close = app.route('/__aura_close', method='POST')(_close_handler)
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
                custom_callbacks = {_assets_fallback, _covers_fallback, _close_handler}
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
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            env = os.environ.copy()
            env['NEDOTIFY_RESTART_COUNT'] = str(restart_count + 1)
            subprocess.Popen(
                [sys.executable] + sys.argv,
                creationflags=creation_flags,
                close_fds=True,
                env=env
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

    # Start the application loop (debug=False disables DevTools)
    logging.info(f"[startup] WebView2 runtime setting: {webview.settings.get('WEBVIEW2_RUNTIME_PATH', 'default')}")
    logging.info(f"[startup] webview loop starting (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
    _storage_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'webview2_data')
    os.makedirs(_storage_dir, exist_ok=True)
    webview.start(http_server=True, debug=False, private_mode=False, storage_path=_storage_dir)

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

    # Cleanup after window closed
    _release_instance_lock()
    app_core.cleanup()
    try:
        api.cleanup()
    except Exception:
        logging.debug("_startup_watchdog: suppressed exception", exc_info=True)
    sys.exit(0)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
