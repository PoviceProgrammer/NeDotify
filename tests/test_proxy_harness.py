"""Shared harness for the core/proxy.py regression tests.

The proxy is exercised over a real loopback socket, because the only way to see
what a browser would see is the status line, the headers and the body actually
written. Everything else is hermetic: a throwaway SQLite database, a redirected
``~`` (so ~/.nedotify never materialises), and a stub engine that RECORDS
resolve_stream_url() calls instead of performing them.
"""
import http.client
import io
import os
import socketserver
import threading
import types
import urllib.parse

import pytest

from core import proxy as proxy_module
from core.proxy import StreamProxyHandler, ThreadingHTTPServer

PROXY_TOKEN = 'test-proxy-token'


def qs(**kwargs):
    """Percent-encoded query string ('/'-free, like the frontend's encodeURIComponent)."""
    parts = []
    for key, value in kwargs.items():
        if value is None:
            continue
        parts.append('{}={}'.format(key, urllib.parse.quote(str(value), safe='')))
    return '&'.join(parts)


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path


class RecordingEngine:
    """Stub resolver. Any call is a bug in these tests - they must be answered
    (or refused) from local state, never from the network."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def resolve_stream_url(self, track):
        self.calls.append(track)
        return self.result


class ProxyResponse:
    def __init__(self, raw):
        self.status = raw.status
        self.reason = raw.reason
        self.headers = raw.headers
        self.body = raw.read()

    def header(self, name, default=None):
        return self.headers.get(name, default)


class ProxyClient:
    def __init__(self, server, token):
        self.server = server
        self.port = server.server_port
        self.token = token

    def url(self, path, **params):
        params.setdefault('k', self.token)
        query = qs(**params)
        return '{}?{}'.format(path, query) if query else path

    def request(self, path, method='GET', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            conn.request(method, path, headers=dict(headers or {}))
            return ProxyResponse(conn.getresponse())
        finally:
            conn.close()

    def get(self, path, headers=None):
        return self.request(path, 'GET', headers)

    def head(self, path, headers=None):
        return self.request(path, 'HEAD', headers)


@pytest.fixture
def nedotify_home(tmp_path, monkeypatch):
    """Redirect ``~`` to a throwaway home and create the managed app tree.

    conftest.redirect_home is not enough here: it only intercepts ``~\\...``
    (os.sep), while core/proxy.py builds every path from the literal
    ``~/.nedotify``, which would still resolve against the real user home.
    """
    home = tmp_path / 'home'
    home.mkdir()
    orig_expanduser = os.path.expanduser

    def _patched(path):
        if path == '~' or path[:2] in ('~' + os.sep, '~/', '~\\'):
            return str(home) + path[1:]
        return orig_expanduser(path)

    monkeypatch.setattr(os.path, 'expanduser', _patched)

    base = os.path.join(str(home), '.nedotify')
    for sub in ('covers', 'avatars', 'streams', 'temp', 'downloads'):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    return base


@pytest.fixture
def app_core(tmp_db, nedotify_home):
    """Fake AppCore: real DB (library rows matter for the /api/stream gate),
    stub cache dirs, and a recording engine."""
    return types.SimpleNamespace(
        db=tmp_db,
        settings=None,
        youtube=None,
        soundcloud=None,
        cache=types.SimpleNamespace(
            _streams_dir=os.path.join(nedotify_home, 'streams'),
            _temp_dir=os.path.join(nedotify_home, 'temp'),
        ),
        engine=RecordingEngine(),
    )


@pytest.fixture
def proxy_factory(app_core):
    """Start loopback proxies; yields a factory taking the auth token."""
    servers = []

    def _make(token=PROXY_TOKEN):
        server = ThreadingHTTPServer(('127.0.0.1', 0), StreamProxyHandler, app_core, token)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True
        )
        thread.start()
        servers.append(server)
        return ProxyClient(server, token)

    yield _make

    for server in servers:
        server.shutdown()
        try:
            server.server_close()
        except AttributeError:
            # Python 3.14's ThreadingMixIn.server_close() ends with
            # self._threads.join(), but this project tracks _threads in a plain
            # list (block_on_close = False). Pre-existing, harmless for the
            # tests: the listening socket is already closed by then.
            pass


@pytest.fixture
def proxy(proxy_factory):
    return proxy_factory()


def offline_handler(app_core, headers=None, token=PROXY_TOKEN):
    """A StreamProxyHandler wired to an in-memory wfile (no socket).

    Used for paths that cannot be reached deterministically over HTTP, e.g. a
    file that disappears between the caller's isfile() check and the open().
    """
    handler = StreamProxyHandler.__new__(StreamProxyHandler)
    handler.server = types.SimpleNamespace(app_core=app_core, auth_token=token)
    handler.headers = dict(headers or {})
    handler.wfile = io.BytesIO()
    handler.request_version = 'HTTP/1.1'
    handler.requestline = 'GET / HTTP/1.1'
    handler._headers_buffer = []
    return handler


# --- P0-1: request threads must be daemons ---------------------------------

def test_request_threads_are_daemon(proxy, nedotify_home):
    """A buffered track kept the app from closing.

    ThreadingMixIn.daemon_threads defaults to False and nothing overrode it, so
    every request thread was a NON-daemon: sys.exit() blocks joining them, so
    the interpreter never finished while a stream was still being written.
    """
    assert socketserver.ThreadingMixIn.daemon_threads is False, (
        'CPython default changed - re-check the daemon_threads rationale'
    )
    assert ThreadingHTTPServer.daemon_threads is True

    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'x' * 32)
    assert proxy.get('/api/cover?' + qs(path=cover, k=proxy.token)).status == 200

    threads = list(proxy.server._threads)
    assert threads, 'the request never spawned a tracked worker thread'
    assert all(t.daemon for t in threads), 'a request thread is not a daemon'


# --- H-6: the dead threading._original_Thread indirection -------------------

def test_dead_thread_class_helper_removed(proxy, nedotify_home):
    """get_real_thread_class() read threading._original_Thread, which nothing
    in the project ever sets - it always returned threading.Thread."""
    assert not hasattr(proxy_module, 'get_real_thread_class')
    assert not hasattr(threading, '_original_Thread')

    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'x' * 32)
    assert proxy.get('/api/cover?' + qs(path=cover, k=proxy.token)).status == 200
    assert all(t.__class__ is threading.Thread for t in proxy.server._threads)