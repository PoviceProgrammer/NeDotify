"""
NeDotify - Local HTTP Stream Proxy
Proxies cloud stream requests to inject authentication headers/cookies and support self-healing stream URL re-resolution.
"""
import hmac
import os
import re
import secrets
import time
import json
import mimetypes
import http.server
import socketserver
import socket
import random
import urllib.request
import urllib.parse
import urllib.error
import threading
import logging

from core.api import _is_ssrf_safe_url  # mirrors core/api.py:_is_ssrf_safe_url; imported (not copied) — core.api does not import core.proxy, so no import cycle
_is_safe_url = _is_ssrf_safe_url

logger = logging.getLogger(__name__)

HOP_BY_HOP = frozenset({'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization', 'connection', 'te', 'transfer-encoding', 'keep-alive'})

# Query parameter carrying the per-session proxy token.
AUTH_PARAM = 'k'

# Paths the proxy actually serves. The catch-all branch in do_GET() falls back
# to engine.resolve_stream_url() with whatever metadata the query carried, and
# for an empty query that means source='soundcloud' with an empty target - a
# real SoundCloud request that blocks the request thread on event.wait(15).
# Anything outside this set ('/favicon.ico', a typo'd endpoint) is refused here
# instead. '/' is listed because it IS the generic proxying endpoint emitted by
# LocalProxyManager.get_proxy_url() and engine._notify_track_changed().
KNOWN_PROXY_PATHS = ('/', '/api/cover', '/api/avatar', '/api/stream')

# Upstream credentials are attached ONLY when the target host belongs to the
# provider that owns them. Without this, a caller could point ?url= at any host
# and have the user's Yandex OAuth token or provider cookies forwarded to it.
# SoundCloud serves audio from several unrelated-looking domains. Missing
# `soundcloud.cloud` made every stream on playback.media-streaming.soundcloud.cloud
# lose its credentials, so downloads/streaming silently lost whatever the API
# had attached, and source inference fell through leaving `source` unset.
# Kept as one list so host checks cannot drift apart again.
SOUNDCLOUD_HOSTS = ('soundcloud.com', 'sndcdn.com', 'soundcloud.cloud', 'scdn.co')
YOUTUBE_HOSTS = ('youtube.com', 'youtu.be', 'googlevideo.com', 'ytimg.com')
YANDEX_HOSTS = ('yandex.ru', 'yandex.net', 'yandex.com')


def _host_matches(host: str, suffixes) -> bool:
    """True when host equals or is a subdomain of any of `suffixes`."""
    return any(host == sfx or host.endswith('.' + sfx) for sfx in suffixes)


CREDENTIAL_HOSTS = {
    'yandex': YANDEX_HOSTS,
    'youtube': YOUTUBE_HOSTS,
    'soundcloud': SOUNDCLOUD_HOSTS,
}


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or '').lower()
    except Exception:
        return ''


def _host_allows_credentials(url: str, source: str) -> bool:
    """True when `url`'s host is owned by `source`, so its credentials may be sent."""
    suffixes = CREDENTIAL_HOSTS.get(source or '')
    if not suffixes:
        return False
    host = _host_of(url)
    if not host:
        return False
    return any(host == sfx or host.endswith('.' + sfx) for sfx in suffixes)


def _is_loopback_origin(origin: str) -> bool:
    """True for http(s)://127.0.0.1[:port] / localhost[:port] / [::1][:port]."""
    if not origin:
        return False
    try:
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme not in ('http', 'https'):
            return False
        return (parsed.hostname or '').lower() in ('127.0.0.1', 'localhost', '::1')
    except Exception:
        return False


# Extensions a client may fetch through /api/avatar.
AVATAR_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
# Extensions a client may fetch through /api/cover.
COVER_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
# Extensions a client may fetch through /api/stream when the target is a local
# file. /api/stream used to hand out ANY file it could open, which turned a
# token-bearing request into an arbitrary file-read primitive over the disk.
# The container formats come first; the tail mirrors utils/file_scanner.py's
# AUDIO_EXTENSIONS, so a file the library can legitimately hold never becomes
# unplayable.
AUDIO_EXTENSIONS = {
    '.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus', '.webm',
    '.wma', '.alac', '.aiff',
}


def _avatars_root() -> str:
    """The only directory /api/avatar is allowed to serve files from."""
    return os.path.normpath(os.path.join(os.path.expanduser('~'), '.nedotify', 'avatars'))


def _nedotify_root() -> str:
    """The application's own data tree: covers, avatars, streams, downloads."""
    return os.path.normpath(os.path.join(os.path.expanduser('~'), '.nedotify'))


def _cover_roots() -> list:
    """Directories /api/cover is allowed to serve files from.

    Every cover_path written by the app lands in ~/.nedotify/covers (file
    scanner, tag editor); avatars live next door and are harmless images too.
    Older DB rows (and the dev scanner) may also reference the bundled UI
    covers folders (ui/web_new*/covers), so those are served as well when the
    bundle actually ships one - still strictly image extensions, still
    realpath-contained. Roots that do not exist are dropped: they can never
    match a file and only cost a realpath() per request in the cover hot path.
    """
    nedotify = os.path.normpath(os.path.expanduser('~/.nedotify'))
    roots = [
        os.path.join(nedotify, 'covers'),
        os.path.join(nedotify, 'avatars'),
    ]
    try:
        import sys
        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        for ui_name in ('web_new', 'web_new_v2'):
            ui_covers = os.path.join(base, 'ui', ui_name, 'covers')
            if os.path.isdir(ui_covers):
                roots.append(ui_covers)
    except Exception:
        logger.debug('_cover_roots: UI covers roots unavailable', exc_info=True)
    return roots


def _is_inside_roots(resolved: str, roots) -> bool:
    """True when `resolved` (already realpath'd) sits inside one of `roots`."""
    for root in roots:
        resolved_root = os.path.realpath(root)
        try:
            if os.path.commonpath([resolved, resolved_root]) == resolved_root:
                return True
        except ValueError:
            # Different drives on Windows -> commonpath raises.
            continue
    return False


def _resolve_inside_roots(raw_path: str, roots, extensions) -> str:
    """Resolve `raw_path` to a servable file strictly inside one of `roots`.

    Returns '' unless the path resolves (realpath, so symlinks/junctions are
    collapsed) inside an allowed root, exists and carries an allow-listed
    extension. Traversal attempts, UNC paths and arbitrary disk reads are all
    refused.
    """
    try:
        if not raw_path:
            return ''
        candidate = raw_path
        if candidate.startswith('file:///'):
            candidate = candidate[len('file:///'):]
        candidate = os.path.normpath(urllib.parse.unquote(candidate))
        ext = os.path.splitext(candidate)[1].lower()
        if ext not in extensions:
            return ''
        resolved = os.path.realpath(candidate)
        if _is_inside_roots(resolved, roots):
            return resolved if os.path.isfile(resolved) else ''
    except Exception:
        logger.debug('_resolve_inside_roots rejected %r', raw_path, exc_info=True)
    return ''


def _referenced_by_library(candidates, db) -> bool:
    """True when any of `candidates` is a file_path/cover_path in `tracks`.

    A local library may live in any folder the user imported, so a folder
    whitelist alone would break playback. The database row is what makes a
    local path legitimate; paths are compared case-insensitively because the
    stored spelling may differ from the one the client sent.
    """
    conn = getattr(db, 'conn', None)
    if conn is None:
        return False
    queries = (
        'SELECT id FROM tracks WHERE LOWER(file_path) = LOWER(?) LIMIT 1',
        'SELECT id FROM tracks WHERE LOWER(cover_path) = LOWER(?) LIMIT 1',
    )
    for candidate in candidates:
        if not candidate:
            continue
        for sql in queries:
            try:
                row = conn.execute(sql, (candidate,)).fetchone()
            except Exception:
                logger.debug('_referenced_by_library lookup failed for %r', candidate, exc_info=True)
                row = None
            if row:
                return True
    return False


def _safe_stream_local_path(raw_path, db) -> str:
    """Resolve `raw_path` to a local audio file /api/stream is allowed to serve.

    Returns '' unless the path is an existing, allow-listed audio file that
    either lives inside a managed application root (~/.nedotify/..., where the
    stream cache and downloads are) or is referenced by a row in the `tracks`
    table (an imported local library). Everything else is refused, so a
    token-bearing request cannot read arbitrary files off the disk.
    """
    try:
        if not raw_path:
            return ''
        candidate = os.path.normpath(str(raw_path))
        if os.path.splitext(candidate)[1].lower() not in AUDIO_EXTENSIONS:
            return ''
        resolved = os.path.realpath(candidate)
        if not os.path.isfile(resolved):
            return ''
        if _is_inside_roots(resolved, [_nedotify_root()]):
            return resolved
        if _referenced_by_library((candidate, resolved), db):
            return resolved
        logger.warning('Refused /api/stream read of unlisted local file: %s', candidate)
        return ''
    except Exception:
        logger.debug('_safe_stream_local_path rejected %r', raw_path, exc_info=True)
    return ''


def _safe_avatar_path(raw_path: str) -> str:
    """Resolve `raw_path` to a servable avatar file inside the avatars root."""
    return _resolve_inside_roots(raw_path, [_avatars_root()], AVATAR_EXTENSIONS)


def _safe_cover_path(raw_path: str) -> str:
    """Resolve `raw_path` to a servable cover file inside the allowed roots."""
    return _resolve_inside_roots(raw_path, _cover_roots(), COVER_EXTENSIONS)


# Content-Type -> stream cache file extension. The on-disk cache probe in
# do_GET() already looks for all of these, so saving under the real container
# keeps later lookups and MIME handling consistent.
_RESPONSE_EXTS = {
    'audio/mp4': '.m4a',
    'audio/x-m4a': '.m4a',
    'audio/m4a': '.m4a',
    'video/mp4': '.m4a',
    'audio/webm': '.webm',
    'video/webm': '.webm',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/ogg': '.ogg',
    'application/ogg': '.ogg',
    'audio/opus': '.ogg',
}


def _ext_for_response(resp) -> str:
    """Pick a cache extension from the upstream response's Content-Type."""
    try:
        ct = ''
        if hasattr(resp, 'headers') and resp.headers is not None:
            ct = resp.headers.get('Content-Type') or ''
        elif hasattr(resp, 'info'):
            info = resp.info()
            ct = (info.get('Content-Type') if info else '') or ''
        base = ct.split(';', 1)[0].strip().lower()
        return _RESPONSE_EXTS.get(base, '.m4a')
    except Exception:
        return '.m4a'


def _parse_byte_range(range_header, file_size):
    """Parse a single-range `Range: bytes=...` header per RFC 7233.

    Returns ``(kind, start, end)`` where kind is:

    * ``'range'``  - a satisfiable single range; answer 206 with that slice.
    * ``'full'``   - no Range, an unparsable one, or a multi-range request;
      answer 200 with the whole entity (RFC 7233 explicitly allows ignoring a
      Range header it cannot satisfy at the syntax level).
    * ``'invalid'``- syntactically valid but unsatisfiable (start beyond EOF,
      end before start, zero-length suffix); answer 416.

    The old parser read the field positionally, so a suffix range
    (``bytes=-500``, what HTML5 audio sends) was answered as 0-500 and an
    unsatisfiable range was silently clamped into a *different* range.
    """
    size = int(file_size or 0)
    if not range_header:
        return ('full', 0, max(size - 1, 0))
    header = str(range_header).strip()
    unit, sep, spec = header.partition('=')
    if not sep or unit.strip().lower() != 'bytes':
        return ('full', 0, max(size - 1, 0))
    spec = spec.strip()
    if not spec or ',' in spec or '-' not in spec:
        # Multipart ranges are legal to ignore.
        return ('full', 0, max(size - 1, 0))
    first, _, last = spec.partition('-')
    first, last = first.strip(), last.strip()
    try:
        if not first:
            # Suffix form: the final N bytes of the entity.
            if not last:
                return ('full', 0, max(size - 1, 0))
            suffix_len = int(last)
            if suffix_len < 0:
                # e.g. `bytes=--5`: not a range we can even name.
                return ('full', 0, max(size - 1, 0))
            if suffix_len == 0 or size <= 0:
                return ('invalid', None, None)
            return ('range', max(0, size - suffix_len), size - 1)
        start = int(first)
        end = int(last) if last else size - 1
    except (TypeError, ValueError):
        return ('full', 0, max(size - 1, 0))
    if start < 0 or end < start or start >= size:
        return ('invalid', None, None)
    return ('range', start, min(end, size - 1))


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Custom redirect handler that validates all redirect destinations against SSRF protection."""
    def __init__(self, max_redirects=5):
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.HTTPError(req.full_url, code, "Too many redirects (max 5)", headers, fp)
        if not _is_ssrf_safe_url(newurl):
            raise urllib.error.HTTPError(req.full_url, code, f"SSRF blocked redirect destination: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_urlopen(req, timeout=12.0):
    """Open URL using custom SafeRedirectHandler enforcing strict SSRF checks on every redirect."""
    opener = urllib.request.build_opener(SafeRedirectHandler(max_redirects=5))
    return opener.open(req, timeout=timeout)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Multi-threaded HTTP server holding a reference to the application core.
    """
    block_on_close = False
    # socketserver.ThreadingMixIn.daemon_threads defaults to False, and nothing
    # in the app overrode it, so every in-flight request thread was a
    # non-daemon: sys.exit() blocked on the interpreter's atexit join while a
    # buffered track was still being served, and the app could not close.
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, app_core, auth_token=''):
        self.app_core = app_core
        self.auth_token = auth_token or ''
        self._threads_lock = threading.Lock()
        super().__init__(server_address, RequestHandlerClass)

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = self.daemon_threads
        with self._threads_lock:
            if self._threads is None or not isinstance(self._threads, list):
                self._threads = []
            self._threads = [th for th in self._threads if hasattr(th, "is_alive") and th.is_alive()]
            self._threads.append(t)
        t.start()


class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP Request Handler to proxy cloud streams and handle credentials and re-resolution.
    """

    def send_error(self, code, message=None, explain=None):
        try:
            super().send_error(code, message, explain)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _safe_send_error(self, code, message=None, explain=None):
        """send_error() that never raises on a dead client socket (WinError 10053)."""
        try:
            self.send_error(code, message, explain)
        except OSError:
            pass
        except Exception:
            logger.debug("_safe_send_error suppressed", exc_info=True)

    def finish(self):
        """Release this request thread's SQLite connection before the thread dies.

        The server is thread-per-request and DatabaseManager caches one connection
        per thread, each holding an 8MB page cache. Without an explicit release the
        connections were only reclaimed whenever the GC happened to collect the dead
        thread's locals.
        """
        try:
            super().finish()
        finally:
            try:
                db = getattr(self.server.app_core, 'db', None)
                closer = getattr(db, 'close_thread_connection', None)
                if callable(closer):
                    closer()
            except Exception:
                logger.debug('Per-request DB connection release failed', exc_info=True)

    def log_message(self, format, *args):
        logger.debug(format % args)

    def _authorized(self, query_params) -> bool:
        """Constant-time check of the per-session proxy token.

        The loopback proxy forwards provider credentials and serves cached audio,
        so an unauthenticated port is readable by any local process or by any web
        page that guesses the port. Every request must carry ?k=<token>.

        An unset token fails CLOSED. LocalProxyManager.start() always mints one
        and, when the server cannot be built, no port is ever announced - so an
        empty token can only mean "not configured", and serving anyway would
        expose the proxy with no bearer at all.
        """
        expected = getattr(self.server, 'auth_token', '') or ''
        if not expected:
            logger.error('Proxy token is not configured - refusing request (fail-closed)')
            return False
        supplied = (query_params.get(AUTH_PARAM) or [''])[0]
        # Legacy alias some frontend helpers still send.
        if not supplied:
            supplied = (query_params.get('auth_token') or [''])[0]
        return hmac.compare_digest(str(supplied), str(expected))

    def _authenticate(self, parsed_path, query_params) -> bool:
        """Entry gate shared by GET and HEAD: reject unauthenticated callers."""
        if not self._authorized(query_params):
            logger.warning('Rejected unauthenticated proxy request: %s', parsed_path.path)
            self._reject_unauthorized()
            return False
        return True

    def _reject_unauthorized(self):
        self.send_response(403)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            self.wfile.write(b'{"error": "forbidden: missing or invalid proxy token"}')
        except OSError:
            pass

    def _send_cors_headers(self):
        """Echo a loopback Origin only. A wildcard would let any web page read
        proxied responses, including provider-authenticated ones."""
        origin = self.headers.get('Origin', '')
        if _is_loopback_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def serve_local_file(self, file_path):
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            # Callers check os.path.isfile() first, but the file can still
            # vanish in between (scanner, user, cache eviction). Unguarded,
            # that race answered 500 with a traceback.
            self._safe_send_error(404, 'File not found')
            return None
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'audio/mp4'
        range_kind, start_byte, end_byte = _parse_byte_range(self.headers.get('Range'), file_size)
        if range_kind == 'invalid':
            self._send_range_not_satisfiable(file_size)
            return None
        if range_kind == 'full':
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(file_size))
            self._send_cors_headers()
            self.end_headers()
            try:
                with open(file_path, 'rb') as f:
                    import shutil
                    shutil.copyfileobj(f, self.wfile)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
                logger.debug("serve_local_file disconnect: %s", ce)
            return None

        length = end_byte - start_byte + 1
        try:
            self.send_response(206)
            self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
            self.send_header('Content-Length', str(length))
            self._send_cors_headers()
            self.end_headers()
            with open(file_path, 'rb') as f:
                f.seek(start_byte)
                chunk_size = 8192
                bytes_sent = 0
                while bytes_sent < length:
                    read_size = min(chunk_size, length - bytes_sent)
                    data = f.read(read_size)
                    if not data:
                        break
                    self.wfile.write(data)
                    bytes_sent += len(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            return None
        except Exception as e:
            logger.error(f'Error serving Range request: {e}')
            try:
                self._safe_send_error(500, 'Range processing error')
            except Exception:
                logger.debug("serve_local_file: suppressed exception", exc_info=True)
        return None

    def _send_range_not_satisfiable(self, file_size):
        """416 for a Range the RFC calls unsatisfiable, with the required
        `Content-Range: bytes * /<size>` (RFC 7233 section 4.4)."""
        try:
            self.send_response(416)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.send_header('Content-Length', '0')
            self._send_cors_headers()
            self.end_headers()
        except OSError:
            pass
        except Exception:
            logger.debug('_send_range_not_satisfiable suppressed', exc_info=True)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
        self.end_headers()

    def do_HEAD(self):
        """Answer HEAD with GET's headers and no body (RFC 9110 9.3.2).

        CORS advertises HEAD, but BaseHTTPRequestHandler has no do_HEAD and
        answered 501. Only what GET can answer from local state is resolved
        here: fetching an upstream stream purely to throw its body away would
        be pure waste, so a HEAD that would need one reports 404.
        """
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if not self._authenticate(parsed_path, query_params):
            return None

        if parsed_path.path not in KNOWN_PROXY_PATHS:
            self._safe_send_error(404, 'Not Found')
            return None

        if parsed_path.path == '/api/cover':
            self._send_local_head(_safe_cover_path(query_params.get('path', [''])[0] or ''))
            return None

        if parsed_path.path == '/api/avatar':
            self._send_local_head(_safe_avatar_path(query_params.get('path', [''])[0] or ''))
            return None

        # '/' and /api/stream: same local-file gate GET applies.
        self._send_local_head(self._resolve_stream_local_file(
            query_params.get('url', [''])[0] or query_params.get('file_path', [''])[0] or ''
        ))
        return None

    def _send_local_head(self, file_path):
        """Emit the headers GET would send for `file_path` (or 404), no body."""
        if not file_path:
            self._safe_send_error(404, 'Local file not found')
            return None
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            self._safe_send_error(404, 'File not found')
            return None
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'audio/mp4'
        range_kind, start_byte, end_byte = _parse_byte_range(self.headers.get('Range'), file_size)
        if range_kind == 'invalid':
            self._send_range_not_satisfiable(file_size)
            return None
        if range_kind == 'range':
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
            self.send_header('Content-Length', str(end_byte - start_byte + 1))
        else:
            self.send_response(200)
            self.send_header('Content-Length', str(file_size))
        self.send_header('Content-Type', content_type)
        self.send_header('Accept-Ranges', 'bytes')
        self._send_cors_headers()
        self.end_headers()
        return None

    def _resolve_stream_local_file(self, local_path):
        """The local audio file `/` and /api/stream may serve, or ''.

        A local library can live in any folder the user imported, so the gate
        is "managed app root OR referenced by a tracks row", never a fixed
        folder list.
        """
        db = getattr(getattr(self.server, 'app_core', None), 'db', None)
        return _safe_stream_local_path(local_path, db)

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if not self._authenticate(parsed_path, query_params):
            return None

        # Everything outside the served set is refused here: the catch-all
        # branch below resolves with empty metadata, which for SoundCloud is a
        # real network call that blocks the request thread for up to 15s.
        if parsed_path.path not in KNOWN_PROXY_PATHS:
            logger.info('Refusing unknown proxy path: %s', parsed_path.path)
            self._safe_send_error(404, 'Not Found')
            return None

        if parsed_path.path == '/api/cover':
            path_param = query_params.get('path', [None])[0]
            if not path_param:
                self.send_error(400, 'Missing path parameter')
                return None
            cover_file = _safe_cover_path(path_param)
            if cover_file:
                self.serve_local_file(cover_file)
                return None
            self.send_error(404, 'Cover file not found')
            return None

        if parsed_path.path == '/api/avatar':
            path_param = query_params.get('path', [None])[0]
            if not path_param:
                self.send_error(400, 'Missing path parameter')
                return None
            avatar_file = _safe_avatar_path(urllib.parse.unquote(path_param))
            if avatar_file:
                self.serve_local_file(avatar_file)
                return None
            self.send_error(404, 'Avatar file not found')
            return None

        if parsed_path.path == '/api/stream':
            url_param = query_params.get('url', [None])[0] or query_params.get('file_path', [None])[0]
            track_id = query_params.get('track_id', [None])[0]
            source = query_params.get('source', [None])[0]
            source_id = query_params.get('source_id', [None])[0]
            title = query_params.get('title', [''])[0]
            artist = query_params.get('artist', [''])[0]

            # If url_param points directly to a local file, serve it immediately!
            if url_param:
                local_path = url_param.strip()
                if local_path.startswith('file:///'):
                    local_path = urllib.request.url2pathname(local_path[7:])
                elif local_path.startswith('file://'):
                    local_path = urllib.request.url2pathname(local_path[6:])
                allowed_local = self._resolve_stream_local_file(local_path)
                if allowed_local:
                    self.serve_local_file(allowed_local)
                    return None

            int_track_id = None
            if track_id:
                try:
                    parsed_id = int(track_id)
                    if parsed_id > 0:
                        int_track_id = parsed_id
                except (ValueError, TypeError):
                    pass

            track = self.server.app_core.db.get_track(int_track_id) if int_track_id else None
            if not track:
                if not source_id and not int_track_id and not url_param:
                    self.send_error(400, 'Missing track_id or source_id')
                    return None
                source = source if source else 'youtube'
                track = {
                    'id': int_track_id or 0,
                    'source': source,
                    'source_id': source_id if source_id else f"{artist} {title}".strip(),
                    'title': title,
                    'artist': artist,
                    'file_path': url_param,
                }

            source = track.get('source') or source or 'youtube'
            source_id = track.get('source_id') or source_id

            if source == 'local':
                file_path = url_param or track.get('file_path') or track.get('url')
                if file_path:
                    local_path = file_path.strip()
                    if local_path.startswith('file:///'):
                        local_path = urllib.request.url2pathname(local_path[7:])
                    elif local_path.startswith('file://'):
                        local_path = urllib.request.url2pathname(local_path[6:])
                    allowed_local = self._resolve_stream_local_file(local_path)
                    if allowed_local:
                        self.serve_local_file(allowed_local)
                        return None
                self.send_error(404, 'Local file not found')
                return None

            # 1. Check DB stream cache
            cached_stream = self.server.app_core.db.get_cached_stream(source, source_id)
            if cached_stream and cached_stream.get('cached_file_path') and os.path.exists(cached_stream['cached_file_path']):
                self.serve_local_file(cached_stream['cached_file_path'])
                return None

            # 2. Check on-disk cache directly
            streams_dir = self.server.app_core.cache._streams_dir
            safe_source = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source or 'unknown'))
            safe_source_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id or ''))
            cache_name = f"{safe_source}_{safe_source_id}" if safe_source_id else (f"track_{int_track_id}" if int_track_id else f"temp_{int(time.time()*1000)}")

            for ext in ("m4a", "webm", "mp3", "ogg"):
                candidate_path = os.path.join(streams_dir, f"{cache_name}.{ext}")
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1024:
                    self.server.app_core.db.set_cached_file(source, source_id, candidate_path)
                    self.serve_local_file(candidate_path)
                    return None

            target_url = url_param or self.server.app_core.engine.resolve_stream_url(track)
            if hasattr(target_url, '_mock_return_value') or not isinstance(target_url, str):
                target_url = str(target_url) if (target_url and not hasattr(target_url, '_mock_return_value')) else ''
            if not target_url:
                try:
                    self.send_error(404, 'Stream not found')
                except Exception:
                    logger.debug("do_GET: suppressed exception", exc_info=True)
                return None

            # If resolved stream is a local file or file:// URL, serve directly
            if target_url:
                local_path = target_url.strip()
                if local_path.startswith('file:///'):
                    local_path = urllib.request.url2pathname(local_path[7:])
                elif local_path.startswith('file://'):
                    local_path = urllib.request.url2pathname(local_path[6:])
                allowed_local = self._resolve_stream_local_file(local_path)
                if allowed_local:
                    self.serve_local_file(allowed_local)
                    return None

            # Same SSRF gate as the ?url= branch: a resolver or a poisoned DB cache
            # row must never be able to make the proxy fetch an internal address.
            if not _is_ssrf_safe_url(target_url):
                logger.warning('SSRF guard blocked resolved stream URL for %s:%s', source, source_id)
                try:
                    self.send_error(400, 'Resolved stream URL blocked by SSRF validation')
                except Exception:
                    logger.debug("do_GET: suppressed exception", exc_info=True)
                return None

            # NOTE: the cache file extension is decided from the upstream
            # Content-Type once the response arrives (see _ext_for_response);
            # hardcoding .m4a here previously cached webm/opus bytes under an
            # m4a name and served them with a mismatched MIME type.
            unique_tag = f"{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000)}"
            temp_path = os.path.join(self.server.app_core.cache._temp_dir, f"{cache_name}_{unique_tag}.tmp")

            range_header = self.headers.get('Range', '')
            is_cachable_request = (not range_header) or (range_header == 'bytes=0-')

            req = urllib.request.Request(target_url)
            if not is_cachable_request:
                req.add_header('Range', range_header)
        else:
            target_url = query_params.get('url', [None])[0]
            source = query_params.get('source', [None])[0]
            source_id = query_params.get('source_id', [None])[0]
            title = query_params.get('title', [''])[0]
            artist = query_params.get('artist', [''])[0]

            # If target_url points to a local file or file:// URL, serve directly or fallback to online resolution
            if target_url:
                local_path = target_url.strip()
                if local_path.startswith('file:///'):
                    local_path = urllib.request.url2pathname(local_path[7:])
                elif local_path.startswith('file://'):
                    local_path = urllib.request.url2pathname(local_path[6:])

                is_local_candidate = bool(
                    target_url.startswith('file://') or
                    re.match(r'^[a-zA-Z]:[\\/]', target_url) or
                    target_url.startswith('/') or
                    target_url.startswith('\\')
                )

                if is_local_candidate:
                    allowed_local = self._resolve_stream_local_file(local_path)
                    if allowed_local:
                        self.serve_local_file(allowed_local)
                        return None
                    # If file doesn't exist on disk, attempt online resolution if track metadata present
                    if (source and source_id) or title:
                        logger.info(f"Local file not found on disk ({local_path[:60]}), resolving online stream for {title or source_id}...")
                        track_info = {
                            'source': source if source else 'youtube',
                            'source_id': source_id,
                            'title': title,
                            'artist': artist,
                        }
                        target_url = self.server.app_core.engine.resolve_stream_url(track_info)
                    else:
                        self.send_error(404, f"Local audio file not found: {os.path.basename(local_path)}")
                        return None

            is_webpage = target_url and any(domain in target_url for domain in ('soundcloud.com', 'youtube.com', 'youtu.be'))

            # '/' is a real endpoint (audio/engine.py builds direct-stream proxy
            # URLs as http://127.0.0.1:<port>/?url=...), so it stays in
            # KNOWN_PROXY_PATHS. But a request that carries neither a url nor any
            # track metadata has nothing to resolve: falling through would call
            # engine.resolve_stream_url with an empty target, and the SoundCloud
            # branch then performs a real network round trip on a blank id and
            # blocks this request thread for up to 15s.
            if not target_url and not (source or source_id or title or artist):
                self.send_error(400, "Missing 'url' query parameter")
                return None

            if not target_url or is_webpage:
                track_info = {
                    'source': source if source else 'soundcloud',
                    'source_id': source_id,
                    'source_url': target_url,
                    'title': title,
                    'artist': artist,
                }
                target_url = self.server.app_core.engine.resolve_stream_url(track_info)

            if not target_url:
                self.send_error(400, "Missing 'url' query parameter and could not resolve stream")
                return None

            # Check if resolved stream is a local file
            if target_url:
                local_path = target_url.strip()
                if local_path.startswith('file:///'):
                    local_path = urllib.request.url2pathname(local_path[7:])
                elif local_path.startswith('file://'):
                    local_path = urllib.request.url2pathname(local_path[6:])
                allowed_local = self._resolve_stream_local_file(local_path)
                if allowed_local:
                    self.serve_local_file(allowed_local)
                    return None

            # Infer source if not specified
            if not source and target_url:
                h = _host_of(target_url)
                if _host_matches(h, YOUTUBE_HOSTS):
                    source = 'youtube'
                elif _host_matches(h, SOUNDCLOUD_HOSTS):
                    source = 'soundcloud'
                elif _host_matches(h, YANDEX_HOSTS):
                    source = 'yandex'

            # SSRF guard: reject URLs resolving to internal/private hosts (same logic as core/api.py).
            if not _is_ssrf_safe_url(target_url):
                try:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'URL blocked: SSRF validation failed'}).encode('utf-8'))
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
                    pass
                logger.warning(f'SSRF guard blocked proxied URL: {target_url[:120]}')
                return None
            req = urllib.request.Request(target_url)
            if 'Range' in self.headers:
                req.add_header('Range', self.headers['Range'])
            is_cachable_request = False

        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        def _inject_ydl_cookies(ydl, req):
            """Try to inject cookies from a yt-dlp instance into a urllib.request.Request."""
            cj = getattr(ydl, '_cookiejar', None) or getattr(ydl, 'cookiejar', None)
            if cj:
                try:
                    cj.add_cookie_header(req)
                except Exception as e:
                    logger.debug(f'Cookie injection failed: {e}')
                return None
            return None

        token = ''
        if not _host_allows_credentials(target_url, source):
            if source in CREDENTIAL_HOSTS:
                logger.warning(
                    'Withholding %s credentials: target host %r is not owned by that provider',
                    source, _host_of(target_url)
                )
        elif source == 'youtube':
            try:
                ydl = self.server.app_core.youtube._get_ydl('high')
                _inject_ydl_cookies(ydl, req)
            except Exception as e:
                logger.warning(f'Error injecting YouTube cookies: {e}')
        elif source == 'soundcloud':
            try:
                ydl = self.server.app_core.soundcloud._get_ydl()
                _inject_ydl_cookies(ydl, req)
            except Exception as e:
                logger.warning(f'Error injecting SoundCloud cookies: {e}')
        elif source == 'yandex':
            if self.server.app_core.settings:
                token = self.server.app_core.settings.get('auth', 'yandex_token', '')
            if token:
                req.add_header('Authorization', f'OAuth {token}')

        resp = None
        max_retries = 3
        had_connection_issue = False

        for attempt in range(max_retries + 1):
            try:
                resp = _safe_urlopen(req, timeout=12.0)
                # Announce recovery only after a visible problem: emitting
                # 'connected' on every single stream open spammed the bridge.
                if had_connection_issue and hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
                    self.server.app_core.api.emit_event('proxy_status', {'proxy': 'connected'})
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404, 410):
                    if e.code in (403, 410) and source and source_id and attempt == 0:
                        logger.info(f'Received HTTP {e.code} for {source}:{source_id}. Invalidating cache and self-healing re-resolution...')
                        try:
                            resolver = getattr(self.server.app_core, 'resolver', None)
                            if resolver is not None:
                                resolver.invalidate(source, source_id)
                        except Exception:
                            logger.debug("_inject_ydl_cookies: suppressed exception", exc_info=True)
                        try:
                            # NB: no local `import threading` here. A function-local
                            # import makes `threading` a local name for the WHOLE
                            # do_GET body, so the earlier use at the cache-tag line
                            # raised UnboundLocalError and every stream request
                            # through the proxy died before reaching the upstream.
                            # threading is imported at module scope instead.
                            resolve_event = threading.Event()
                            new_url = None

                            def _on_resolved(url, metadata=None):
                                # AppCore.re_resolve_stream_url_async invokes this with
                                # (stream_url, metadata); a 1-arg signature raised TypeError
                                # here, so the event was never set and every expired URL
                                # stalled for the full 7s timeout before failing.
                                nonlocal new_url
                                new_url = url
                                resolve_event.set()

                            self.server.app_core.re_resolve_stream_url_async(source, source_id, _on_resolved)
                            resolve_event.wait(timeout=7)

                            if new_url and not _is_ssrf_safe_url(new_url):
                                logger.warning('SSRF guard blocked re-resolved URL for %s:%s', source, source_id)
                                new_url = None
                            if new_url:
                                req = urllib.request.Request(new_url)
                                if 'Range' in self.headers:
                                    req.add_header('Range', self.headers['Range'])
                                req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

                                if not _host_allows_credentials(new_url, source):
                                    logger.warning(
                                        'Withholding %s credentials on re-resolved host %r',
                                        source, _host_of(new_url)
                                    )
                                elif source == 'youtube':
                                    ydl = self.server.app_core.youtube._get_ydl('high')
                                    if hasattr(ydl, '_cookiejar') and ydl._cookiejar:
                                        ydl._cookiejar.add_cookie_header(req)
                                elif source == 'soundcloud':
                                    ydl = self.server.app_core.soundcloud._get_ydl()
                                    if hasattr(ydl, '_cookiejar') and ydl._cookiejar:
                                        ydl._cookiejar.add_cookie_header(req)
                                elif source == 'yandex':
                                    if token:
                                        req.add_header('Authorization', f'OAuth {token}')
                            else:
                                self.send_response(e.code)
                                self.end_headers()
                                return None
                        except Exception:
                            self.send_response(e.code)
                            self.end_headers()
                            return None
                    else:
                        self.send_response(e.code)
                        self.end_headers()
                        return None
                else:
                    if attempt < max_retries:
                        backoff = 1.5 ** attempt + random.uniform(0.1, 0.5)
                        logger.warning(f'HTTPError {e.code}, retrying in {backoff:.2f}s...')
                        time.sleep(backoff)
                        continue
                    else:
                        self.send_response(e.code)
                        self.end_headers()
                        return None
            except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError) as e:
                had_connection_issue = True
                if attempt < max_retries:
                    backoff = 1.5 ** attempt + random.uniform(0.1, 0.5)
                    logger.warning(f'Network error {e}, retrying in {backoff:.2f}s...')
                    if hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
                        self.server.app_core.api.emit_event('proxy_status', {
                            'proxy': 'reconnecting',
                            'attempt': attempt + 1,
                            'max_attempts': max_retries,
                            'next_retry_in_ms': int(backoff * 1000),
                        })
                    time.sleep(backoff)
                    continue
                else:
                    if hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
                        self.server.app_core.api.emit_event('proxy_status', {'proxy': 'failed'})
                    self.send_error(502, 'Bad Gateway / Upstream connection failed')
                    return None
            except Exception as e:
                logger.error(f'Unexpected proxy error: {e}')
                self.send_error(500, 'Internal Server Error')
                return None

        status_code = getattr(resp, 'status', getattr(resp, 'code', 200))
        self.send_response(status_code)

        if hasattr(resp, 'getheaders'):
            headers_list = resp.getheaders()
        else:
            headers_list = resp.info().items()

        for header, val in headers_list:
            h_low = header.lower()
            if h_low not in HOP_BY_HOP and not h_low.startswith('access-control-'):
                self.send_header(header, val)

        self._send_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
        self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
        self.end_headers()

        try:
            if is_cachable_request and status_code in (200, 206):
                expected_len = None
                cl_val = None
                if hasattr(resp, 'headers') and resp.headers:
                    cl_val = resp.headers.get('Content-Length')
                elif hasattr(resp, 'info') and resp.info():
                    cl_val = resp.info().get('Content-Length')
                if cl_val:
                    try:
                        expected_len = int(cl_val)
                    except (ValueError, TypeError):
                        expected_len = None

                final_path = os.path.join(
                    streams_dir,
                    f"{cache_name}{_ext_for_response(resp)}",
                )

                bytes_written = 0
                with open(temp_path, 'wb') as tmp:
                    while True:
                        chunk = resp.read(32768)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        self.wfile.write(chunk)
                        tmp.write(chunk)

                if bytes_written > 0 and (expected_len is None or bytes_written == expected_len):
                    try:
                        os.replace(temp_path, final_path)
                        self.server.app_core.db.set_cached_file(source, source_id, final_path)
                        logger.info(f'Stream cached successfully to {final_path}')
                    except PermissionError:
                        # File is currently opened by another thread or reader (Windows WinError 32)
                        time.sleep(0.05)
                        try:
                            os.replace(temp_path, final_path)
                            self.server.app_core.db.set_cached_file(source, source_id, final_path)
                            logger.info(f'Stream cached successfully on retry to {final_path}')
                        except Exception as pe:
                            logger.warning(f'Could not replace stream file {final_path} (locked): {pe}')
                else:
                    logger.warning(f'Incomplete stream received ({bytes_written} bytes vs expected {expected_len}). Removing temp file.')
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            else:
                while True:
                    chunk = resp.read(32768)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
            logger.debug(f'Stream client disconnected: {ce}')
            if is_cachable_request and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    logger.debug("_on_resolved: suppressed exception", exc_info=True)
        except Exception as e:
            logger.error(f'Error proxying stream: {e}')
            if is_cachable_request and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    logger.debug("_on_resolved: suppressed exception", exc_info=True)
        finally:
            if resp is not None and hasattr(resp, "close"):
                try:
                    resp.close()
                except Exception:
                    pass

        return None


class LocalProxyManager:
    """
    Manages start/stop lifecycle of the local stream proxy on a dynamic port.
    """

    def __init__(self, app_core):
        self.app_core = app_core
        self.server = None
        self.thread = None
        self.port = 0
        # Per-session bearer for the loopback proxy. Regenerated on every start so a
        # token captured from an earlier run is useless.
        self.token = ''

    def start(self):
        try:
            self.token = secrets.token_urlsafe(24)
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), StreamProxyHandler, self.app_core, self.token)
            self.port = self.server.server_port
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info(f'Local HTTP stream proxy started on port {self.port}')
        except Exception as e:
            logger.error(f'Failed to start local proxy server: {e}')

    def stop(self):
        self.token = ''
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                logger.debug("stop: suppressed exception", exc_info=True)
            try:
                self.server.server_close()
            except Exception:
                logger.debug("stop: suppressed exception", exc_info=True)
            self.server = None
        self.thread = None
        self.port = 0
        logger.info('Local HTTP stream proxy stopped')

    def auth_query(self) -> str:
        """'&k=<token>' fragment for callers that assemble proxy URLs themselves."""
        return f'&{AUTH_PARAM}={urllib.parse.quote(self.token)}' if self.token else ''

    def get_proxy_url(self, source, source_id, original_url=None, track_id=None):
        if not self.port:
            return original_url or ''
        if original_url and not any(d in original_url for d in ('youtube.com', 'youtu.be', 'soundcloud.com')):
            params = {
                'url': original_url,
                'source': source if source else '',
                'source_id': source_id if source_id else '',
            }
            if self.token:
                params[AUTH_PARAM] = self.token
            query = urllib.parse.urlencode(params)
            return f'http://127.0.0.1:{self.port}/?{query}'
        
        params = {}
        if track_id:
            try:
                if int(track_id) > 0:
                    params['track_id'] = track_id
            except (ValueError, TypeError):
                pass
        if source:
            params['source'] = source
        if source_id:
            params['source_id'] = source_id
        if not params:
            return ''
        if self.token:
            params[AUTH_PARAM] = self.token
        query = urllib.parse.urlencode(params)
        return f'http://127.0.0.1:{self.port}/api/stream?{query}'