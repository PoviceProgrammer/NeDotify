"""
NeDotify - Entry Point
Desktop audio player with modern dark UI, streaming integration,
and advanced customization. (PyWebView Edition)
"""

import sys
import os
import threading
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

# Capture the pywebview HTTP server's Bottle app so the app can register its own
# bridge-free routes (e.g. /__aura_close) even when the JS bridge is dead.
_BOTTLE_APP = [None]
try:
    import bottle as _bottle
    _orig_bottle_run = _bottle.run

    def _capture_bottle_run(app=None, **kwargs):
        _BOTTLE_APP[0] = app
        return _orig_bottle_run(app=app, **kwargs)

    _bottle.run = _capture_bottle_run
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
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
                    pass
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
    
    html_path = os.path.join(base_dir, "ui", "web_new", "index.html")

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

    # Pass window reference to api
    api.set_window(window)
    logging.info(f"[startup] window created (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")

    def on_loaded():
        logging.info(f"[startup] window loaded (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
        if app_core.engine.queue.current_track:
            app_core.engine._on_track_changed(app_core.engine.queue.current_track)
        # Zapret must start AFTER the window is up: a cold winws DPI-desync launch
        # slows WebView2 HTTPS handshakes and delays bridge injection.
        threading.Thread(target=app_core.start_zapret_if_enabled, daemon=True).start()
            
    window.events.loaded += on_loaded

    # Watchdog: if the JS bridge never comes up (WebView2 init hang), log it,
    # force one reload, and register a bridge-free close endpoint on the local server.
    def _register_close_route():
        import time as _time
        for _ in range(200):
            if _BOTTLE_APP[0] is not None:
                break
            _time.sleep(0.1)
        if _BOTTLE_APP[0] is None:
            logging.warning("[startup] HTTP server app unavailable; bridge-free close disabled")
            return
        try:
            def _close_handler():
                try:
                    window.destroy()
                except Exception:
                    pass
                return 'ok'
            app = _BOTTLE_APP[0]
            route = app.route('/__aura_close', method='POST')(_close_handler)
            # Bottle matches routes in registration order; move ours ahead of the
            # static-file catch-all ('/<file:path>') so it is actually reached.
            routes = getattr(app, 'routes', None)
            if isinstance(routes, list) and route in routes:
                routes.remove(route)
                routes.insert(0, route)
            logging.info(f"[startup] bridge-free close endpoint registered (/__aura_close, page={window.real_url})")
        except Exception as e:
            logging.warning(f"[startup] close endpoint registration failed: {e}")

    def _startup_watchdog():
        # First load may be slow (observed up to ~16s on cold WebView2); give a
        # generous window, then silently reload twice (manual/auto reload is
        # confirmed to restore the bridge). The frontend shows the error overlay
        # only after 45s of bridge absence on the 3rd load (2 reloads done).
        for attempt in range(1, 3):
            if window.events.loaded.wait(45):
                logging.info(f"[startup] bridge initialized after {attempt} load attempt(s)")
                return
            logging.warning(
                f"[startup] bridge not initialized after {attempt * 45}s; "
                f"silently reloading (attempt {attempt}/2)"
            )
            try:
                window.load_url(window.real_url)
            except Exception as e:
                logging.warning(f"[startup] forced reload failed: {e}")
                return
        if not window.events.loaded.wait(45):
            logging.error(
                "[startup] bridge STILL unavailable after 2 auto reloads. "
                "Close via the tray icon or Alt+F4, or reinstall/repair the WebView2 "
                f"runtime (pinned: {_PINNED_WEBVIEW2})."
            )

    threading.Thread(target=_register_close_route, daemon=True).start()
    threading.Thread(target=_startup_watchdog, daemon=True).start()

    # Start the application loop (debug=False disables DevTools; use F12 for debugging via debug flag)
    logging.info(f"[startup] webview loop starting (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
    webview.start(http_server=True, debug=False)

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
    app_core.cleanup()
    try:
        api.cleanup()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    main()
