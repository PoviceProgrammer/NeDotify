import sys
sys.path.insert(0, "/home/fsociety/AURA_Music_backup/AURA_Music_linux")
import os
import time
import threading
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib
from core.settings import DEFAULT_SETTINGS

PORT = 43225

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.abspath('ui/web_new_v2'), **kwargs)

server = HTTPServer(('127.0.0.1', PORT), Handler)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()

win = Gtk.Window()
win.set_default_size(1100, 800)

w = WebKit2.WebView()
settings = w.get_settings()
settings.set_enable_javascript(True)
settings.set_enable_webgl(True)

win.add(w)

from core.app import AppCore
from core.api import AppApi

app = AppCore()
api = AppApi(app)
settings_dict = api.get_settings()
app.cleanup()

win.show_all()

loop = GLib.MainLoop()

verification_results = {}

def on_snapshot_ready(source, result):
    try:
        surface = source.get_snapshot_finish(result)
        out_path = '/home/fsociety/AURA_Music_backup/AURA_Music_linux/.agents/worker_m1/test_fixed_dots_snapshot.png'
        surface.write_to_png(out_path)
        print('Snapshot successfully saved to:', out_path)
    except Exception as e:
        print('Snapshot error:', e)
    loop.quit()

def check_styles():
    check_js = """
    (function() {
        const bg = document.getElementById('particles-bg');
        if (!bg) return { error: 'No #particles-bg found' };
        const cs = window.getComputedStyle(bg);
        const canvas = document.getElementById('particles-canvas');
        return {
            position: cs.position,
            zIndex: cs.zIndex,
            pointerEvents: cs.pointerEvents,
            filter: cs.filter,
            webkitFilter: cs.webkitFilter,
            display: cs.display,
            top: cs.top,
            left: cs.left,
            bottom: cs.bottom,
            right: cs.right,
            hasCanvas: !!canvas,
            canvasWidth: canvas ? canvas.width : 0,
            canvasHeight: canvas ? canvas.height : 0
        };
    })()
    """
    def on_check_done(source, res):
        try:
            js_res = source.run_javascript_finish(res)
            val = js_res.get_js_value()
            json_str = val.to_json(0)
            data = json.loads(json_str)
            print("Computed styles & canvas info:", json.dumps(data, indent=2))
            assert data.get("position") == "fixed", f"Expected position fixed, got {data.get('position')}"
            assert data.get("zIndex") == "20", f"Expected zIndex 20, got {data.get('zIndex')}"
            assert data.get("pointerEvents") == "none", f"Expected pointerEvents none, got {data.get('pointerEvents')}"
            assert data.get("filter") in ("none", "", None), f"Expected filter none, got {data.get('filter')}"
            assert data.get("hasCanvas") is True, "Expected canvas to be created"
            print("CSS & Canvas verification PASSED!")
            w.get_snapshot(WebKit2.SnapshotRegion.FULL_DOCUMENT, WebKit2.SnapshotOptions.NONE, None, on_snapshot_ready)
        except Exception as e:
            print("Check styles assertion error:", e)
            loop.quit()

    w.run_javascript(check_js, None, on_check_done)

def on_load_first(web_view, event):
    if event == WebKit2.LoadEvent.FINISHED:
        w.disconnect(first_conn)
        w.connect('load-changed', on_load_second)
        settings_dict['ui']['particles_shape'] = 'dot'
        escaped_settings = json.dumps(settings_dict)
        js = f"""
        localStorage.setItem('nedotify_cached_settings', JSON.stringify({escaped_settings}));
        localStorage.setItem('nedotify_ui_particles_shape', JSON.stringify('dot'));
        localStorage.setItem('nedotify_ui_particles_enabled', 'true');
        localStorage.setItem('nedotify_onboarding_completed', 'true');
        sessionStorage.setItem('nedotify_bridge_strikes', '0');
        """
        w.run_javascript(js, None, None)
        w.load_uri(f'http://127.0.0.1:{PORT}/index.html')

def on_load_second(web_view, event):
    if event == WebKit2.LoadEvent.FINISHED:
        print('Second load complete. Waiting 6s for app init and particles animation...')
        GLib.timeout_add(6000, check_styles)

first_conn = w.connect('load-changed', on_load_first)
w.load_uri(f'http://127.0.0.1:{PORT}/index.html')
loop.run()
win.destroy()
server.shutdown()
