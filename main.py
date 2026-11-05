"""
NeDotify - Entry Point
Desktop audio player with modern dark UI, streaming integration,
and advanced customization. (PyWebView Edition)
"""

import logging
import multiprocessing
import os
import subprocess
import sys
import threading
import signal

from linux_runtime import configure_environment, InstanceLock

configure_environment()


if sys.platform == "win32":
    multiprocessing.freeze_support()

import webview

# Pin WebView2 runtime to a known-good version: Evergreen 151.0.4129.93 hangs
# bridge injection (loaded/_pywebviewready never fire) on this machine, while
# 151.0.4129.86 works. Falls back to system runtime if the pinned copy is gone.
if sys.platform == "win32":
    _PINNED_WEBVIEW2 = os.path.join(
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
    )
    if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
        # pywebview's ImmutableDict does not define WEBVIEW2_RUNTIME_PATH. WebView2
        # reads this environment variable before runtime initialization instead.
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

import bottle as _bottle
from core.ui_server import LocalUiServer, cached_static_file

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

from core.app import AppCore, finalize_process
from core.api import AppApi
from core.bridge import BridgeApi, install_bridge_guard

install_bridge_guard()

def _enable_doh_fallback():
    from core.dns_fallback import install
    install()

try:
    _enable_doh_fallback()
except Exception:
    logging.warning('DNS fallback initialization failed', exc_info=True)


def _patch_pywebview_winforms_move():
    """Fix pywebview 5.4's WinForms move(): it passes None as the size
    arguments of SetWindowPos, which this ctypes build rejects, so EVERY
    window.move() raises ArgumentError - including the pywebview-drag-region
    title-bar drag, which fires pywebviewMoveWindow on every mousemove and
    floods the log with bridge errors. Replace the module-level dispatcher
    with a SetWindowPos call carrying real integers."""
    if sys.platform != 'win32':
        return
    try:
        from ctypes import windll
        from webview.platforms import winforms

        def _fixed_move(x, y, uid):
            instance = winforms.BrowserView.instances.get(uid)
            if not instance:
                return
            try:
                handle = instance.Handle
                if not handle:
                    return
                scale = getattr(instance, 'scale_factor', 1) or 1
                SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW = 0x0001, 0x0004, 0x0040
                windll.user32.SetWindowPos(
                    handle.ToInt32(), None,
                    int(round(x * scale)), int(round(y * scale)),
                    0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW,
                )
            except Exception:
                logging.debug('Patched WinForms move failed', exc_info=True)

        winforms.move = _fixed_move
        logging.info('[startup] patched pywebview WinForms move() for this runtime')
    except Exception:
        logging.warning('pywebview move() patch failed', exc_info=True)


def main():
    """Application entry point."""
    logging.info("Starting NeDotify...")
    import time as _time
    _t0 = _time.monotonic()
    logging.info("[startup] process started")
    _patch_pywebview_winforms_move()

    # Single Instance Guard - deliberately the FIRST thing main() does.
    # It used to run after AppCore() and after the window was created, which
    # defeats the point: a second launch still opened ~/.nedotify, started the
    # proxy port, the downloader threads and the yt-dlp update, spawned the
    # WebView2 runtime and only then bailed out. Everything below can call
    # sys.exit(0) from inside the guard, so nothing may exist yet at this
    # point that needs tearing down.
    import tempfile
    _INSTANCE_MUTEX = None
    _INSTALLER_MUTEX = None
    _linux_instance = InstanceLock()

    def _acquire_instance_lock():
        nonlocal _INSTANCE_MUTEX, _INSTALLER_MUTEX
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
                kernel32.CreateMutexW.restype = wintypes.HANDLE
                ERROR_ALREADY_EXISTS = 183

                import hashlib
                identity = os.path.normcase(os.path.expanduser('~'))
                user_key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
                _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Global\\NeDotify_" + user_key)
                if not _INSTANCE_MUTEX:
                    raise OSError("Could not acquire the single-instance mutex")
                if _INSTANCE_MUTEX and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                    logging.info("[startup] Another instance of NeDotify is already running; exiting cleanly.")
                    sys.exit(0)
                _INSTALLER_MUTEX = kernel32.CreateMutexW(None, False, r'Local\NeDotify_Installer_Guard')
                if not _INSTALLER_MUTEX:
                    raise OSError('Could not create installer coordination mutex')
            except Exception as e:
                logging.error("Single-instance protection failed", exc_info=True)
                raise
        else:
            if not _linux_instance.acquire():
                logging.info('[startup] Another NeDotify instance owns this user profile; exiting.')
                sys.exit(0)

    def _release_instance_lock():
        nonlocal _INSTANCE_MUTEX, _INSTALLER_MUTEX
        if sys.platform == "win32" and (_INSTANCE_MUTEX or _INSTALLER_MUTEX):
            try:
                import ctypes
                from ctypes import wintypes
                kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                for handle in (_INSTANCE_MUTEX, _INSTALLER_MUTEX):
                    if handle:
                        kernel32.CloseHandle(handle)
                _INSTANCE_MUTEX = None
                _INSTALLER_MUTEX = None
            except Exception:
                logging.debug("_release_instance_lock: suppressed exception", exc_info=True)
        if sys.platform != 'win32':
            _linux_instance.release()

    _acquire_instance_lock()

    if sys.platform.startswith('linux') and os.environ.get('NEDOTIFY_VALIDATION_OUTPUT'):
        from tools.validate_linux import prepare_validation
        prepare_validation()

    app_core = None
    api = None
    window = None
    desktop_integration = None
    _INTENTIONAL_CLOSE = threading.Event()
    _shutdown_lock = threading.Lock()
    _shutdown_complete = False
    _shutdown_done = threading.Event()
    _shutdown_result = None

    def _shutdown_once():
        nonlocal _shutdown_complete, _shutdown_result
        with _shutdown_lock:
            if _shutdown_complete:
                owner = False
            else:
                _shutdown_complete = True
                owner = True
        if not owner:
            _shutdown_done.wait(45)
            return _shutdown_result
        _INTENTIONAL_CLOSE.set()
        try:
            if desktop_integration is not None:
                desktop_integration.stop()
            if app_core is not None:
                _shutdown_result = app_core.cleanup()
            elif api is not None:
                api.cleanup()
                _shutdown_result = {'durable_flushed': False, 'remaining_workers': ()}
            else:
                _shutdown_result = {'durable_flushed': True, 'remaining_workers': ()}
        except Exception:
            logging.exception("Application cleanup failed")
            _shutdown_result = {'durable_flushed': False, 'remaining_workers': ()}
        finally:
            try:
                server = getattr(webview.http, 'global_server', None)
                if isinstance(server, LocalUiServer):
                    server.stop()
            except Exception:
                logging.exception('UI server cleanup failed')
            finally:
                _release_instance_lock()
                _shutdown_done.set()
        return _shutdown_result

    import atexit
    atexit.register(_shutdown_once)
    try:
        # Retain the object even if a later initialization step fails, so the
        # same finally path can close partially-created resources.
        app_core = AppCore.__new__(AppCore)
        app_core.__init__()
        logging.info("[startup] AppCore initialized (+%.0fms)", (_time.monotonic()-_t0)*1000)
        app_core.warm_playback_sources()
        api = AppApi(app_core)
        app_core.plugins.load_plugins()
        try:
            session = app_core.session.restore_session()
            queue = session.get('queue')
            if queue:
                app_core.engine.queue.set_tracks(queue, session.get('queue_index', 0))
                app_core.engine.queue.shuffle = session.get('shuffle', False)
                app_core.engine.queue.repeat = session.get('repeat', 'off')
            api._restore_position_sec = float(session.get('position') or 0)
            api._restore_autoplay = bool(app_core.session.should_autoplay)
        except Exception:
            logging.exception("Failed to restore session")
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        ui_root = os.path.join(base_dir, 'ui', 'web_new_v2')
        html_path = os.path.join(ui_root, 'index.html')
        window = webview.create_window(
            'NeDotify', url=html_path, js_api=BridgeApi(api),
            width=1100, height=800, min_size=(600, 640), frameless=True,
            resizable=True, fullscreen=False,
            # Color-keyed WinForms transparency makes WebView2's GPU surface
            # transparent to native mouse hit testing on some runtimes. Keep
            # the HWND solid; theme alpha and glass stay inside the page.
            transparent=False,
            background_color='#0f0f14', easy_drag=False,
        )
        api.set_window(window)
        if sys.platform.startswith('linux'):
            from core.linux_integration import LinuxDesktopIntegration
            desktop_integration = LinuxDesktopIntegration(api)
            desktop_integration.start()

        def on_signal(signum, frame):
            logging.info('Received signal %s; closing NeDotify', signum)
            _INTENTIONAL_CLOSE.set()
            threading.Thread(target=window.destroy, name='SignalClose', daemon=True).start()

        if sys.platform.startswith('linux'):
            signal.signal(signal.SIGTERM, on_signal)
            signal.signal(signal.SIGINT, on_signal)
        logging.info("[startup] window created (+%.0fms)", (_time.monotonic()-_t0)*1000)

        _window_loaded_handled = threading.Event()

        def on_loaded():
            logging.info("[startup] window loaded (+%.0fms)", (_time.monotonic()-_t0)*1000)
            # BUG-024: the render watchdog reloads this page after a compositor
            # hang, so `loaded` fires more than once per process. A second run
            # used to spawn a duplicate autostart worker (overwriting
            # `_zapret_start_thread`, so cleanup waited on the wrong thread)
            # and a second render-watchdog loop. Handle the event once; the
            # watchdog keeps working across reloads via the heartbeat.
            if _window_loaded_handled.is_set():
                logging.info("[startup] window reload detected; autostart/watchdog already running")
                return
            _window_loaded_handled.set()
            app_core.setup.maybe_auto_update()
            # Playback restoration is published only after the frontend has
            # installed its subscribers and acknowledged api.ui_ready().
            threading.Thread(target=app_core.start_zapret_if_enabled,
                             name='ZapretAutostart', daemon=True).start()
            threading.Thread(target=render_watchdog, name='RenderWatchdog', daemon=True).start()

        def render_watchdog():
            """Self-heal the recurring WebView2 black-window hang.

            The renderer's compositor sometimes stalls while the process
            stays perfectly alive (no crash event, DOM intact behind a frozen
            frame) - the user just sees the window background color. The
            frontend beats frontend_heartbeat() every 4s while visible; a
            long silent stretch while visible means the page is wedged, so
            the renderer is reloaded, and if that fails too the app restarts
            itself once. Hidden pages throttle their timers, so gaps while
            hidden are never treated as a hang.
            """
            reloaded_at = None
            reloads = 0
            while not _INTENTIONAL_CLOSE.is_set():
                _time.sleep(5)
                if _INTENTIONAL_CLOSE.is_set():
                    return
                last = getattr(api, '_ui_heartbeat_monotonic', None)
                if last is None or getattr(api, '_ui_visibility', 'visible') != 'visible':
                    continue
                silent = _time.monotonic() - last
                if reloaded_at is not None:
                    if _time.monotonic() - reloaded_at < 15:
                        continue
                    if last > reloaded_at:
                        logging.info('[watchdog] renderer recovered after reload')
                        reloaded_at = None
                        continue
                    logging.error('[watchdog] renderer still silent 15s after reload; restarting app')
                    try:
                        count = int(os.environ.get('NEDOTIFY_RESTART_COUNT', '0'))
                    except ValueError:
                        count = 1
                    if count >= 1:
                        logging.error('[watchdog] restart budget exhausted; giving up')
                        return
                    env = dict(os.environ, NEDOTIFY_RESTART_COUNT=str(count + 1))
                    args = [sys.executable] + (sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv)
                    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0

                    def launch_restart():
                        subprocess.Popen(args, creationflags=flags, close_fds=True, env=env)

                    finalize_process(_shutdown_once, logging.shutdown, os._exit,
                                     restart=launch_restart, exit_code=3)
                    return
                if silent > 20:
                    if reloads >= 2:
                        logging.error('[watchdog] renderer reload budget exhausted; giving up')
                        return
                    reloads += 1
                    logging.warning('[watchdog] no renderer heartbeat for %.0fs while visible; reloading page', silent)
                    reloaded_at = _time.monotonic()
                    def reload_renderer():
                        try:
                            window.evaluate_js('location.reload();')
                        except Exception:
                            logging.exception('[watchdog] reload dispatch failed')
                    # A wedged renderer can block evaluate_js itself; keep the
                    # watchdog able to enforce its bounded restart deadline.
                    threading.Thread(target=reload_renderer, name='RenderReload', daemon=True).start()

        def on_closed():
            _INTENTIONAL_CLOSE.set()

        window.events.loaded += on_loaded
        window.events.closed += on_closed
        fallback_png = bytes.fromhex(
            '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
            '0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082')

        def install_routes(app):
            from core.ui_assets import install_macos_assets, install_library_artwork
            install_macos_assets(app, base_dir)
            install_library_artwork(app)

            @app.post('/__aura_close')
            def close_handler():
                _INTENTIONAL_CLOSE.set()
                window.destroy()
                return 'ok'

            def image_asset(folder, filepath):
                # Served from the in-memory byte cache (mtime/size invalidation
                # covers rewritten covers); missing art falls back to a 1x1 PNG.
                result = cached_static_file(filepath, root=os.path.join(ui_root, folder))
                if result.status_code != 404:
                    return result
                _bottle.response.content_type = 'image/png'
                return fallback_png

            @app.get('/assets/<filepath:path>')
            def assets(filepath):
                return image_asset('assets', filepath)

            @app.get('/covers/<filepath:path>')
            def covers(filepath):
                return image_asset('covers', filepath)

            @app.error(404)
            def image_404(error):
                if _bottle.request.path.lower().endswith(('.png','.jpg','.jpeg','.webp','.ico','.svg','.gif')):
                    _bottle.response.status = 200
                    _bottle.response.content_type = 'image/png'
                    return fallback_png
                return error.body
            logging.info('[startup] close and fallback routes registered before serving')

        LocalUiServer.route_installer = install_routes

        def startup_watchdog():
            if api._ui_ready_event.wait(35):
                logging.info('[startup] frontend acknowledged bridge readiness')
                return
            if _INTENTIONAL_CLOSE.is_set():
                return
            try:
                count = int(os.environ.get('NEDOTIFY_RESTART_COUNT', '0'))
            except ValueError:
                count = 1
            if count >= 1:
                logging.error('[startup] frontend did not initialize after one restart')
                return
            logging.warning('[startup] frontend not ready after 35 seconds; restarting once')
            import subprocess
            env = dict(os.environ, NEDOTIFY_RESTART_COUNT=str(count+1))
            args = [sys.executable] + (sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv)
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
            def launch_restart():
                subprocess.Popen(args, creationflags=flags, close_fds=True, env=env)
            finalize_process(_shutdown_once, logging.shutdown, os._exit,
                             restart=launch_restart, exit_code=3)

        threading.Thread(target=startup_watchdog, name='StartupWatchdog', daemon=True).start()
        storage_dir = os.path.join(os.path.expanduser('~'), '.nedotify',
                                   'webview2_data' if sys.platform == 'win32' else 'webview_data')
        os.makedirs(storage_dir, exist_ok=True)
        debug = os.environ.get('NEDOTIFY_DEVTOOLS', '').strip().lower() in ('1','true','yes','on')
        logging.info('[startup] WebView2 runtime setting: %s',
                     os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'default'))
        if sys.platform.startswith('linux'):
            from linux_runtime import install_qt_capture
            install_qt_capture()
            if os.environ.get('NEDOTIFY_VALIDATION_OUTPUT'):
                from tools.validate_linux import validate_running_app
                threading.Thread(target=validate_running_app, args=(api, window),
                                 name='NativeValidation', daemon=True).start()
        webview.start(gui='qt' if sys.platform.startswith('linux') else None,
                      http_server=True, server=LocalUiServer, debug=debug,
                      private_mode=False, storage_path=storage_dir)
    except Exception:
        logging.exception('Application startup or runtime failed')
        raise
    finally:
        result = _shutdown_once()
        atexit.unregister(_shutdown_once)
        # Python's ThreadPoolExecutor atexit hook joins running workers without
        # a timeout. If a provider is stuck, the app has already flushed its
        # durable state and left DB handles open; terminate to honor the bounded
        # shutdown contract instead of waiting forever during interpreter exit.
        finalized = finalize_process(lambda: result, logging.shutdown, os._exit)
        if not finalized:
            try:
                logging.shutdown()
            finally:
                os._exit(1)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
