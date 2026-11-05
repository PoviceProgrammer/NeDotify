"""Static-serving micro benchmark: bottle.static_file vs StaticByteCache.

Raises an isolated bottle app on a loopback OS-assigned high port using the
exact threaded wsgiref stack the desktop UI server runs on (_BoundServer /
_RequestHandler from core.ui_server), then measures:

* 200 sequential GETs of the largest bundled CSS file through both serving
  paths (``/old/...`` = bottle.static_file as it was, ``/new/...`` =
  cached_static_file from the in-memory byte cache);
* a simulated window load (every bundled asset requested once) per path.

Passes are interleaved and repeated; the report shows per-phase medians so a
one-off antivirus scan or page-cache miss cannot skew the comparison. It
finishes with functional checks on the cached path: mtime/size invalidation
after a rewrite, If-None-Match -> 304, and a Range request.

No application window is opened; only core.ui_server (bottle) is imported.

Usage:
    python -m tools.bench.bench_static_cache
"""

from __future__ import annotations

import http.client
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bottle  # noqa: E402

from core.ui_server import (  # noqa: E402
    _BoundServer,
    _RequestHandler,
    StaticByteCache,
    cached_static_file,
)

UI_ROOT = ROOT / 'ui' / 'web_new_v2'
ASSET_SUFFIXES = {'.html', '.css', '.js', '.mjs', '.svg', '.png', '.woff2', '.json', '.webp', '.ico'}
REQUESTS = 200
WARMUP = 20
REPS = 5


def get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def timed_gets(host, port, path, count):
    started = time.perf_counter()
    for _ in range(count):
        status, _, body = get(host, port, path)
        assert status == 200, status
        assert body
    return (time.perf_counter() - started) * 1000.0


def main():
    largest_css = max(UI_ROOT.rglob('*.css'), key=lambda p: p.stat().st_size)
    css_rel = largest_css.relative_to(UI_ROOT).as_posix()
    assets = sorted(
        (p for p in UI_ROOT.rglob('*') if p.is_file() and p.suffix.lower() in ASSET_SUFFIXES),
        key=lambda p: p.relative_to(UI_ROOT).as_posix(),
    )

    mutation_dir = Path(tempfile.mkdtemp(prefix='nedotify-bench-static-'))
    try:
        app = bottle.Bottle()
        timing_cache = StaticByteCache()

        @app.get('/old/<filepath:path>')
        def old(filepath):
            return bottle.static_file(filepath, root=str(UI_ROOT))

        @app.get('/new/<filepath:path>')
        def new(filepath):
            return cached_static_file(filepath, root=str(UI_ROOT), cache=timing_cache)

        @app.get('/mut/<filepath:path>')
        def mut(filepath):
            return cached_static_file(filepath, root=str(mutation_dir), cache=timing_cache)

        httpd = _BoundServer(('127.0.0.1', 0), _RequestHandler)
        # wsgiref closes every connection (HTTP/1.0), so client wall time is
        # dominated by per-request TCP + thread setup that is identical for
        # both serving paths. The timing middleware below accumulates the time
        # spent inside each handler -- the part the byte cache actually changes.
        handler_ms = {'old': 0.0, 'new': 0.0, 'mut': 0.0}
        lock = threading.Lock()

        def timed(environ, start_response):
            key = environ.get('PATH_INFO', '/').split('/', 2)[1] or 'old'
            started = time.perf_counter()
            try:
                return app(environ, start_response)
            finally:
                with lock:
                    handler_ms[key] += (time.perf_counter() - started) * 1000.0

        def reset_and_snapshot():
            with lock:
                snap = dict(handler_ms)
                for key in handler_ms:
                    handler_ms[key] = 0.0
            return snap

        httpd.set_app(timed)
        thread = threading.Thread(target=httpd.serve_forever, name='BenchUiServer', daemon=True)
        thread.start()
        host, port = '127.0.0.1', httpd.server_port
        try:
            # Warmup both paths (page cache, mimetypes/registry init, routes).
            timed_gets(host, port, f'/old/{css_rel}', WARMUP)
            timed_gets(host, port, f'/new/{css_rel}', WARMUP)
            for asset in assets:  # page-cache the whole window-load set
                rel = asset.relative_to(UI_ROOT).as_posix()
                get(host, port, f'/old/{rel}')
            reset_and_snapshot()

            # Phase 1: N GETs of one css, interleaved old/new.
            old_runs, new_runs, old_srv, new_srv = [], [], [], []
            for _ in range(REPS):
                wall = timed_gets(host, port, f'/old/{css_rel}', REQUESTS)
                old_runs.append(wall)
                old_srv.append(reset_and_snapshot()['old'])
                wall = timed_gets(host, port, f'/new/{css_rel}', REQUESTS)
                new_runs.append(wall)
                new_srv.append(reset_and_snapshot()['new'])

            # Phase 2: simulated window load. One cold pass through the cache
            # first (every entry is a miss: stat + read + etag), then
            # interleaved warm-cache vs static_file passes.
            def window_load(prefix, sink):
                started = time.perf_counter()
                for asset in assets:
                    rel = asset.relative_to(UI_ROOT).as_posix()
                    status, _, body = get(host, port, f'{prefix}/{rel}')
                    assert status == 200, (rel, status)
                    assert body == asset.read_bytes(), rel
                wall = (time.perf_counter() - started) * 1000.0
                sink.append(reset_and_snapshot()[prefix.strip('/')])
                return wall

            cold_srv = []
            cold_wall = window_load('/new', cold_srv)
            load_old, load_new, load_old_srv, load_new_srv = [], [], [], []
            for _ in range(REPS):
                load_old.append(window_load('/old', load_old_srv))
                load_new.append(window_load('/new', load_new_srv))

            # Functional: invalidation on rewrite (mtime/size key changes).
            probe = mutation_dir / 'probe.css'
            probe.write_bytes(b'.a{color:#111111}')
            status, _, body = get(host, port, '/mut/probe.css')
            assert status == 200 and body == b'.a{color:#111111}'
            time.sleep(0.01)
            probe.write_bytes(b'.a{color:#222222}')  # different size AND content
            status, _, body = get(host, port, '/mut/probe.css')
            assert status == 200 and body == b'.a{color:#222222}', body

            # Functional: conditional GET -> 304.
            status, headers, _ = get(host, port, '/mut/probe.css')
            etag = next((v for k, v in headers.items() if k.lower() == 'etag'), None)
            assert etag, headers
            status, _, _ = get(host, port, '/mut/probe.css', headers={'If-None-Match': etag})
            assert status == 304, status

            # Functional: single-part Range.
            conn = http.client.HTTPConnection(host, port, timeout=5)
            try:
                conn.request('GET', '/mut/probe.css', headers={'Range': 'bytes=4-8'})
                resp = conn.getresponse()
                ranged = resp.read()
                assert resp.status == 206 and ranged == b'olor:', (resp.status, ranged)
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(2)

        size_kb = largest_css.stat().st_size / 1024
        total_kb = sum(p.stat().st_size for p in assets) / 1024
        old_css = statistics.median(old_runs)
        new_css = statistics.median(new_runs)
        old_css_srv = statistics.median(old_srv)
        new_css_srv = statistics.median(new_srv)
        old_load = statistics.median(load_old)
        new_load = statistics.median(load_new)
        old_load_srv = statistics.median(load_old_srv)
        new_load_srv = statistics.median(load_new_srv)

        print(f'asset under test : {css_rel} ({size_kb:.0f} KB)')
        print(f'window load set  : {len(assets)} files, {total_kb:.0f} KB total')
        print(f'server           : 127.0.0.1:{port} (OS-assigned), threaded wsgiref, 24 slots')
        print(f'repetitions      : {REPS} interleaved passes, medians reported')
        print()
        print(f'{REQUESTS} GET css  : static_file wall {old_css:7.1f} ms / handler {old_css_srv:6.1f} ms | '
              f'cache wall {new_css:7.1f} ms / handler {new_css_srv:6.1f} ms | '
              f'handler x{old_css_srv / new_css_srv:.1f} '
              f'({old_css_srv / REQUESTS:.3f} -> {new_css_srv / REQUESTS:.3f} ms/req)')
        print(f'window-load cold : cache first pass (all misses) wall {cold_wall:7.1f} ms / '
              f'handler {cold_srv[0]:6.1f} ms')
        print(f'window-load warm : static_file wall {old_load:7.1f} ms / handler {old_load_srv:6.1f} ms | '
              f'cache wall {new_load:7.1f} ms / handler {new_load_srv:6.1f} ms | '
              f'handler x{old_load_srv / new_load_srv:.1f}')
        print()
        print('invalidation after rewrite: OK')
        print('If-None-Match -> 304     : OK')
        print('Range bytes=4-8 -> 206    : OK')
    finally:
        shutil.rmtree(mutation_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
