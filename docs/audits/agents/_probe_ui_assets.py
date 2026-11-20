"""Scratch probe for core/ui_assets.py route installation (read-only)."""
import io
import sys
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import bottle

ROOT = Path(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
sys.path.insert(0, str(ROOT))

from core.ui_assets import install_macos_assets  # noqa: E402

FALLBACK_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00\x00\x00IEND\xaeB`\x82'


def build_app(with_catchall_first=True):
    app = bottle.Bottle()
    if with_catchall_first:
        @app.get('/<file:path>')
        def catchall(file):
            return bottle.HTTPError(404, 'pywebview catch-all')
    install_macos_assets(app, ROOT)

    def _assets_fallback(filepath=''):
        static_file = str(ROOT / "ui" / "web_new_v2" / "assets" / filepath)
        if Path(static_file).exists():
            return bottle.static_file(filepath, root=str(ROOT / "ui" / "web_new_v2" / "assets"))
        bottle.response.content_type = 'image/png'
        return FALLBACK_PNG

    def _close_handler():
        return 'ok'

    app.route('/__aura_close', method='POST')(_close_handler)
    app.route('/assets/<filepath:path>')(_assets_fallback)

    # --- replicate main.py's router recompile verbatim (lines 466-476) ---
    custom_callbacks = {_assets_fallback, _close_handler}
    custom_routes = [r for r in app.routes if getattr(r, 'callback', None) in custom_callbacks]
    other_routes = [r for r in app.routes if getattr(r, 'callback', None) not in custom_callbacks]
    app.routes[:] = custom_routes + other_routes
    app.router.__init__()
    for r in app.routes:
        app.router.add(r.rule, r.method, r, name=r.name)
    return app


def request(app, path, method='GET'):
    env = {}
    setup_testing_defaults(env)
    env.update(PATH_INFO=path, REQUEST_METHOD=method, **{'wsgi.input': io.BytesIO()})
    response = {}

    def start(status, headers, exc_info=None):
        response.update(status=int(status.split()[0]), headers=dict(headers))

    result = app(env, start)
    body = b''.join(result)
    if hasattr(result, 'close'):
        result.close()
    return response['status'], body


app = build_app()
print('routes registered for MACos_ui:',
      sum(1 for r in app.routes if str(getattr(r, 'rule', '')).startswith('/MACos_ui/')))

for path in ['/MACos_ui/tokens.css', '/MACos_ui/interface.css', '/MACos_ui/library.css',
             '/MACos_ui/settings.css', '/MACos_ui/assets/library-wave.svg',
             '/MACos_ui/assets/atmosphere-dusk.png', '/MACos_ui/missing.css',
             '/MACos_ui/../web_new_v2/index.html', '/assets/backgrounds/photo-1519681393784-d120267933ba.jpg']:
    try:
        status, body = request(app, path)
        print(f'{path:60s} -> {status}  {len(body)} bytes  head={body[:40]!r}')
    except Exception as exc:
        print(f'{path:60s} -> EXC {type(exc).__name__}: {exc}')

print()
print('--- missing pack directory ---')
try:
    app2 = bottle.Bottle()
    install_macos_assets(app2, Path(r'C:\definitely\not\here'))
    print('no exception; routes:', len(app2.routes))
except Exception as exc:
    print('RAISED', type(exc).__name__, exc)

print()
print('--- bottle router precedence check ---')
app3 = bottle.Bottle()


@app3.get('/<file:path>')
def catchall3(file):
    return 'CATCHALL'


@app3.get('/MACos_ui/tokens.css')
def exact():
    return 'EXACT'


print('static-before-dynamic:', request(app3, '/MACos_ui/tokens.css'))
