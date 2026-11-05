"""Bound-before-publish loopback server for the privileged desktop interface."""

import email.utils
import hashlib
import json
import logging
import mimetypes
import os
import socket
import threading
import time
import uuid
from collections import OrderedDict
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

import bottle

logger = logging.getLogger(__name__)


class StaticByteCache:
    """Process-wide byte cache for files served on the UI origin.

    The browser cache stays deliberately disabled (Cache-Control: no-store
    works around a WebView2 stale-ES-module bug), so every window load
    re-requests ~60 assets and ``bottle.static_file`` would open()+read()
    each one from disk. This cache keeps the bytes in memory instead and
    re-``stat()``s the file on every hit: an mtime_ns/size change (hot reload
    during development, a cover being rewritten) invalidates the entry, so
    callers always observe current file contents.
    """

    def __init__(self, max_bytes=64 * 1024 * 1024):
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        # abspath -> (stat_key, data, content_type, etag, last_modified)
        self._entries = {}
        self._order = OrderedDict()  # LRU order for eviction
        self._used = 0

    def load(self, path):
        """Return the cache entry for *path*, or None when unreadable.

        Entries are immutable tuples, so a returned entry stays safe to read
        outside the lock even while another thread replaces it.
        """
        try:
            stat = os.stat(path)
        except OSError:
            return None
        stat_key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get(path)
            if entry is not None and entry[0] == stat_key:
                self._order.move_to_end(path)
                return entry
        # Read outside the lock: concurrent first-hits may double-read, but
        # disk IO must never serialize the 24 request slots.
        try:
            with open(path, 'rb') as handle:
                data = handle.read(stat.st_size)
        except OSError:
            return None
        if len(data) != stat.st_size:
            return None  # file changed mid-read; the next hit re-reads
        mimetype, encoding = mimetypes.guess_type(path)
        if encoding == 'gzip':
            mimetype = 'application/gzip'
        elif encoding:
            mimetype = 'application/x-' + encoding
        if mimetype and 'charset=' not in mimetype and (
                mimetype[:5] == 'text/' or mimetype == 'application/javascript'):
            mimetype += '; charset=UTF-8'
        etag = hashlib.sha1(
            f'{stat.st_dev}:{stat.st_mtime_ns}:{stat.st_size}:{path}'.encode()
        ).hexdigest()
        entry = (stat_key, data, mimetype, etag,
                 email.utils.formatdate(stat.st_mtime, usegmt=True))
        with self._lock:
            previous = self._entries.get(path)
            if previous is not None:
                self._used -= len(previous[1])
            self._entries[path] = entry
            self._order[path] = None
            self._used += len(data)
            while self._used > self._max_bytes and len(self._order) > 1:
                oldest = next(iter(self._order))
                del self._order[oldest]
                evicted = self._entries.pop(oldest, None)
                if evicted is not None:
                    self._used -= len(evicted[1])
        return entry

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._order.clear()
            self._used = 0


static_cache = StaticByteCache()


def cached_static_file(filepath, root, cache=None):
    """``bottle.static_file`` equivalent served from :class:`StaticByteCache`.

    Mirrors the parts of bottle's static_file that this server relies on:
    root-escape protection, 404/403 errors, charset-annotated Content-Type,
    ETag/Last-Modified, If-None-Match/If-Modified-Since revalidation, HEAD
    and single-part Range requests. Bodies come from memory instead of an
    ``open()`` per request.
    """
    cache = cache if cache is not None else static_cache
    root = os.path.join(os.path.abspath(root), '')
    path = os.path.abspath(os.path.join(root, str(filepath).strip('/\\')))
    if not path.startswith(root):
        return bottle.HTTPError(403, 'Access denied.')
    entry = cache.load(path)
    if entry is None:
        return bottle.HTTPError(404, 'File does not exist.')
    _stat_key, data, mimetype, etag, last_modified = entry

    headers = {'Content-Length': len(data),
               'Last-Modified': last_modified,
               'Date': email.utils.formatdate(time.time(), usegmt=True),
               'ETag': etag}
    if mimetype:
        headers['Content-Type'] = mimetype

    environ = bottle.request.environ
    check = environ.get('HTTP_IF_NONE_MATCH')
    if check and check == etag:
        return bottle.HTTPResponse(status=304, **headers)
    ims = environ.get('HTTP_IF_MODIFIED_SINCE')
    if ims:
        ims = bottle.parse_date(ims.split(';')[0].strip())
        if ims is not None and ims >= entry[0][0] / 1e9:
            return bottle.HTTPResponse(status=304, **headers)

    headers['Accept-Ranges'] = 'bytes'
    range_header = environ.get('HTTP_RANGE')
    if range_header:
        ranges = list(bottle.parse_range_header(range_header, len(data)))
        if not ranges:
            return bottle.HTTPError(416, 'Requested Range Not Satisfiable')
        offset, end = ranges[0]
        rlen = end - offset
        headers['Content-Range'] = f'bytes {offset}-{end - 1}/{len(data)}'
        headers['Content-Length'] = rlen
        body = data[offset:offset + rlen]
        if bottle.request.method == 'HEAD':
            body = b''
        return bottle.HTTPResponse(body, status=206, **headers)
    body = b'' if bottle.request.method == 'HEAD' else data
    return bottle.HTTPResponse(body, **headers)


class _RequestHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        self.request.settimeout(10)
        super().setup()


class _BoundServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, address):
        if not self._slots.acquire(blocking=True, timeout=5.0):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._slots.release()


class LocalUiServer:
    """pywebview server protocol with an exclusive, OS-assigned socket."""

    route_installer = None
    common_path = None

    def __init__(self):
        self.uid = uuid.uuid4().hex
        self.js_callback = {}
        self.running = False

    @classmethod
    def start_server(cls, urls, http_port=None, keyfile=None, certfile=None):
        if keyfile or certfile:
            raise ValueError('LocalUiServer supports loopback HTTP only')
        paths = [os.path.abspath(str(url).split('#', 1)[0]) for url in urls]
        if not paths or any('://' in str(url) for url in urls):
            raise ValueError('The desktop UI must be a local file')
        server = cls()
        server.root_path = os.path.dirname(os.path.commonpath(paths))
        cls.common_path = server.root_path
        # Bind synchronously and retain the socket. A free-port probe followed by
        # a second bind would let another process serve privileged UI content.
        server._httpd = _BoundServer(('127.0.0.1', 0), _RequestHandler)
        server.port = server._httpd.server_port
        server.address = f'http://127.0.0.1:{server.port}/'
        server.js_api_endpoint = f'{server.address}js_api/{server.uid}'
        origin = server.address.rstrip('/')
        authority = f'127.0.0.1:{server.port}'
        app = bottle.Bottle()

        @app.post(f'/js_api/{server.uid}')
        def js_api():
            try:
                body = json.loads(bottle.request.body.read(1_048_577).decode('utf-8'))
                if not isinstance(body, dict):
                    raise ValueError()
                callback = server.js_callback.get(body.get('uid'))
                if not callback:
                    bottle.abort(404)
                return json.dumps(callback(body), allow_nan=False)
            except (UnicodeError, ValueError, TypeError):
                bottle.abort(400, 'Invalid bridge request')

        installer = cls.route_installer
        if installer:
            try:
                installer(app)
            except BaseException:
                server._httpd.server_close()
                raise

        @app.get('/')
        def index():
            return cached_static_file(os.path.basename(paths[0]), root=server.root_path)

        @app.get('/<filepath:path>')
        def asset(filepath):
            return cached_static_file(filepath, root=server.root_path)

        def guarded(environ, start_response):
            remote_origin = environ.get('HTTP_ORIGIN')
            denied = (environ.get('HTTP_HOST') != authority or
                      remote_origin is not None and remote_origin != origin or
                      environ.get('HTTP_SEC_FETCH_SITE') not in (None, '', 'none', 'same-origin'))
            try:
                length = int(environ.get('CONTENT_LENGTH') or 0)
            except (TypeError, ValueError):
                length = -1
            if denied or length < 0 or length > 1_048_576:
                status = '403 Forbidden' if denied else '413 Payload Too Large'
                start_response(status, [('Content-Type', 'text/plain'), ('Content-Length', '0')])
                return [b'']

            def secured_response(status, headers, exc_info=None):
                headers = [(key, value) for key, value in headers
                           if not key.lower().startswith('access-control-') and
                           key.lower() not in ('cache-control', 'pragma', 'expires')]
                headers.extend([('Cache-Control', 'no-store, max-age=0'),
                                ('X-Content-Type-Options', 'nosniff')])
                return start_response(status, headers, exc_info)
            return app(environ, secured_response)

        server._httpd.set_app(guarded)
        server.running = True
        server.thread = threading.Thread(target=server._httpd.serve_forever,
                                         name='UiHttpServer', daemon=True)
        server.thread.start()
        return server.address, server.root_path, server

    @property
    def is_running(self):
        return self.running

    def stop(self):
        if self.running:
            self.running = False
            self._httpd.shutdown()
            self._httpd.server_close()
            if self.thread is not threading.current_thread():
                self.thread.join(2)
