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

# Upstream credentials are attached ONLY when the target host belongs to the
# provider that owns them. Without this, a caller could point ?url= at any host
# and have the user's Yandex OAuth token or provider cookies forwarded to it.
CREDENTIAL_HOSTS = {
    'yandex': ('yandex.ru', 'yandex.net', 'yandex.com'),
    'youtube': ('youtube.com', 'youtu.be', 'googlevideo.com', 'ytimg.com', 'google.com'),
    'soundcloud': ('soundcloud.com', 'sndcdn.com'),
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


def _avatars_root() -> str:
    """The only directory /api/avatar is allowed to serve files from."""
    return os.path.normpath(os.path.join(os.path.expanduser('~'), '.nedotify', 'avatars'))


def _cover_roots() -> list:
    """Directories /api/cover is allowed to serve files from.

    Every cover_path written by the app lands in ~/.nedotify/covers (file
    scanner, tag editor); avatars live next door and are harmless images too.
    Older DB rows (and the dev scanner) also reference the bundled UI covers
    folders (ui/web_new*/covers), so those are served as well - still strictly
    image extensions, still realpath-contained.
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
            roots.append(os.path.join(base, 'ui', ui_name, 'covers'))
    except Exception:
        logger.debug('_cover_roots: UI covers roots unavailable', exc_info=True)
    return roots


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
        for root in roots:
            resolved_root = os.path.realpath(root)
            try:
                if os.path.commonpath([resolved, resolved_root]) != resolved_root:
                    continue
            except ValueError:
                # Different drives on Windows -> commonpath raises.
                continue
            if os.path.isfile(resolved):
                return resolved
            return ''
    except Exception:
        logger.debug('_resolve_inside_roots rejected %r', raw_path, exc_info=True)
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


def _is_valid_audio_cache_file(file_path: str) -> bool:
    """Check if a cached file exists, has a plausible audio size (>64KB), and is not a text/playlist file."""
    try:
        if not file_path or not os.path.exists(file_path):
            return False
        if os.path.getsize(file_path) < 65536:
            return False
        with open(file_path, 'rb') as f:
            hdr = f.read(64)
            if hdr.startswith(b'#EXTM3U') or hdr.startswith(b'<!DOCTYPE') or hdr.startswith(b'<html') or hdr.startswith(b'{'):
                return False
        return True
    except Exception:
        return False


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
        if 'mpegurl' in base or 'text' in base or 'html' in base or 'json' in base:
            return ''
        return _RESPONSE_EXTS.get(base, '')
    except Exception:
        return ''


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

    def __init__(self, server_address, RequestHandlerClass, app_core, auth_token=''):
        self.app_core = app_core
        self.auth_token = auth_token or ''
        self._threads_lock = threading.Lock()
        super().__init__(server_address, RequestHandlerClass)

    def process_request(self, request, client_address):
        thread_cls = get_real_thread_class()
        t = thread_cls(target=self.process_request_thread, args=(request, client_address))
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
    protocol_version = "HTTP/1.1"

    def send_error(self, code, message=None, explain=None):
        try:
            super().send_error(code, message, explain)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

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
        """
        expected = getattr(self.server, 'auth_token', '') or ''
        if not expected:
            return False
        supplied = (query_params.get(AUTH_PARAM) or [''])[0]
        # Legacy alias some frontend helpers still send.
        if not supplied:
            supplied = (query_params.get('auth_token') or [''])[0]
        if not supplied:
            return False
        return hmac.compare_digest(str(supplied), str(expected))

    def _reject_unauthorized(self):
        self.send_response(403)
        self.send_header('Content-Type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        try:
            self.wfile.write(b'{"error": "forbidden: missing or invalid proxy token"}')
        except OSError:
            pass

    def _send_cors_headers(self):
        """Echo a loopback Origin or fallback to * so WebKit audio elements never fail CORS."""
        origin = self.headers.get('Origin', '')
        if _is_loopback_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Credentials', 'true')
            self.send_header('Vary', 'Origin')
        else:
            self.send_header('Access-Control-Allow-Origin', '*')

    def serve_local_file(self, file_path):
        file_size = os.path.getsize(file_path)
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'audio/mp4'
        range_header = self.headers.get('Range', None)
        if range_header and range_header.startswith('bytes='):
            try:
                range_match = range_header.replace('bytes=', '').split('-')
                start_byte = int(range_match[0]) if range_match[0] else 0
                end_byte = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
                end_byte = min(end_byte, file_size - 1)
                start_byte = max(0, min(start_byte, end_byte))
                length = end_byte - start_byte + 1
                self.send_response(206)
                self.send_header('Content-Type', content_type)
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
                self.send_header('Content-Length', str(length))
                self._send_cors_headers()
                self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization, X-Requested-With')
                self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
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
                    self.send_error(500, 'Range processing error')
                except Exception:
                    logger.debug("serve_local_file: suppressed exception", exc_info=True)
        else:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(file_size))
            self._send_cors_headers()
            self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization, X-Requested-With')
            self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
            self.end_headers()
            try:
                with open(file_path, 'rb') as f:
                    import shutil
                    shutil.copyfileobj(f, self.wfile)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
                logger.debug("serve_local_file disconnect: %s", ce)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization, X-Requested-With')
        self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
        self.end_headers()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if not self._authorized(query_params):
            self._reject_unauthorized()
            return None

        if parsed_path.path in ('/__aura_eval', '/api/control/eval'):
            is_debug = os.environ.get('NEDOTIFY_DEBUG') == '1'
            if not is_debug and hasattr(self.server.app_core, 'settings'):
                is_debug = self.server.app_core.settings.get('debug')
            if not is_debug:
                self.send_error(403, "Endpoint disabled")
                return None
            try:
                length = int(self.headers.get('Content-Length', 0))
                code = self.rfile.read(length).decode('utf-8')
                api = getattr(self.server.app_core, 'api', None)
                win = getattr(self.server.app_core, 'window', None) or getattr(api, '_window', None) or getattr(api, '_main_window', None)
                if win:
                    if hasattr(win, 'evaluate_js'):
                        res = win.evaluate_js(code)
                    else:
                        res = win.run_js(code)
                    resp_bytes = json.dumps({"result": res}).encode('utf-8')
                else:
                    resp_bytes = json.dumps({"error": "no window"}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return None
        self.send_error(404, 'Endpoint not found')
        return None

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if not self._authorized(query_params):
            logger.warning('Rejected unauthenticated proxy request: %s', parsed_path.path)
            self._reject_unauthorized()
            return None

        if parsed_path.path == '/api/control/play':
            try:
                title = query_params.get('title', [''])[0]
                artist = query_params.get('artist', [''])[0]
                source_id = query_params.get('source_id', [''])[0]
                source = query_params.get('source', ['youtube'])[0]
                file_path = query_params.get('file_path', [''])[0]
                track = {
                    'title': title or 'Test Track',
                    'artist': artist or 'Test Artist',
                    'source': source,
                    'source_id': source_id,
                    'file_path': file_path or None,
                }
                api = getattr(self.server.app_core, 'api', None)
                if api and hasattr(api, 'play_track'):
                    api.play_track(track, [track], 0)
                    resp = {"status": "playing", "track": track}
                else:
                    resp = {"error": "api not available"}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
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

        return self._handle_stream(query_params)

    def _handle_stream(self, query_params):
        url_param = query_params.get('url', [None])[0] or query_params.get('file_path', [None])[0]
        track_id = query_params.get('track_id', [None])[0]
        source = query_params.get('source', [None])[0]
        source_id = query_params.get('source_id', [None])[0]
        title = query_params.get('title', [''])[0]
        artist = query_params.get('artist', [''])[0]

        def _clean_local_path(candidate):
            if not candidate or not isinstance(candidate, str):
                return None
            p = candidate.strip()
            if p.startswith('file:///'):
                p = urllib.request.url2pathname(p[7:])
            elif p.startswith('file://'):
                p = urllib.request.url2pathname(p[6:])
            return p

        # 1. If url_param points directly to a local file, serve it immediately!
        cleaned_url = _clean_local_path(url_param)
        if cleaned_url and (os.path.isabs(cleaned_url) or os.path.exists(cleaned_url)) and os.path.isfile(cleaned_url):
            self.serve_local_file(cleaned_url)
            return None

        int_track_id = None
        if track_id:
            try:
                parsed_id = int(track_id)
                if parsed_id > 0:
                    int_track_id = parsed_id
            except (ValueError, TypeError):
                pass

        track = None
        if int_track_id and hasattr(self.server.app_core, 'db'):
            track = self.server.app_core.db.get_track(int_track_id)

        if not track:
            track = {
                'id': int_track_id or 0,
                'source': source if source else 'youtube',
                'source_id': source_id if source_id else f"{artist} {title}".strip(),
                'title': title,
                'artist': artist,
                'file_path': url_param,
            }

        source = track.get('source') or source
        source_id = track.get('source_id') or source_id

        # 2. Local source check
        if source == 'local':
            fp = _clean_local_path(url_param or track.get('file_path') or track.get('url'))
            if fp and os.path.exists(fp) and os.path.isfile(fp):
                self.serve_local_file(fp)
                return None
            self.send_error(404, 'Local file not found')
            return None

        # 3. Check DB stream cache for local cached file
        if source and source_id and hasattr(self.server.app_core, 'db'):
            cached_stream = self.server.app_core.db.get_cached_stream(source, str(source_id))
            if cached_stream and cached_stream.get('cached_file_path'):
                cfp = cached_stream['cached_file_path']
                if _is_valid_audio_cache_file(cfp):
                    self.serve_local_file(cfp)
                    return None
                elif os.path.exists(cfp):
                    try:
                        os.remove(cfp)
                    except Exception:
                        pass

        # 4. Check on-disk cache directly
        safe_source = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source or 'unknown'))
        safe_source_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id or ''))
        cache_name = f"{safe_source}_{safe_source_id}" if safe_source_id else (f"track_{int_track_id}" if int_track_id else f"temp_{int(time.time()*1000)}")

        streams_dir = getattr(self.server.app_core.cache, '_streams_dir', None)
        if streams_dir and os.path.exists(streams_dir) and safe_source_id:
            for ext in ("m4a", "webm", "mp3", "ogg"):
                candidate_path = os.path.join(streams_dir, f"{cache_name}.{ext}")
                if _is_valid_audio_cache_file(candidate_path):
                    if hasattr(self.server.app_core, 'db') and hasattr(self.server.app_core.db, 'set_cached_file'):
                        self.server.app_core.db.set_cached_file(source, str(source_id), candidate_path)
                    self.serve_local_file(candidate_path)
                    return None
                elif os.path.exists(candidate_path):
                    try:
                        os.remove(candidate_path)
                    except Exception:
                        pass

        # 5. Determine target URL
        target_url = url_param
        if not target_url or any(domain in target_url for domain in ('soundcloud.com', 'youtube.com', 'youtu.be')):
            target_url = self.server.app_core.engine.resolve_stream_url(track)
            if hasattr(target_url, '_mock_return_value') or not isinstance(target_url, str):
                target_url = str(target_url) if (target_url and not hasattr(target_url, '_mock_return_value')) else ''

        if not target_url:
            self.send_error(404, 'Stream not found')
            return None

        # If target_url resolved to a local file
        target_local = _clean_local_path(target_url)
        if target_local and (os.path.isabs(target_local) or os.path.exists(target_local)) and os.path.isfile(target_local):
            self.serve_local_file(target_local)
            return None

        # Infer source if not specified
        if not source:
            h = _host_of(target_url)
            if any(h == sfx or h.endswith('.' + sfx) for sfx in ('googlevideo.com', 'youtube.com', 'youtu.be')):
                source = 'youtube'
            elif any(h == sfx or h.endswith('.' + sfx) for sfx in ('sndcdn.com', 'soundcloud.com')):
                source = 'soundcloud'
            elif any(h == sfx or h.endswith('.' + sfx) for sfx in ('yandex.net', 'yandex.ru')):
                source = 'yandex'

        # SSRF validation
        if not _is_ssrf_safe_url(target_url):
            logger.warning(f'SSRF guard blocked proxied URL: {target_url[:120]}')
            try:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'URL blocked: SSRF validation failed'}).encode('utf-8'))
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
                pass
            return None

        # 6. Parse Range request headers
        range_header = self.headers.get('Range', '')
        range_start = 0
        range_end = None
        has_range_request = False
        if range_header and range_header.startswith('bytes='):
            has_range_request = True
            try:
                parts = range_header[6:].split('-')
                range_start = int(parts[0]) if parts[0] else 0
                range_end = int(parts[1]) if len(parts) > 1 and parts[1] else None
            except (ValueError, IndexError):
                has_range_request = False

        is_cachable_request = (not has_range_request) or (range_start == 0 and range_end is None)
        unique_tag = f"{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000)}"
        temp_path = os.path.join(self.server.app_core.cache._temp_dir, f"{cache_name}_{unique_tag}.tmp") if streams_dir else None

        def _inject_ydl_cookies(ydl, req_obj):
            cj = getattr(ydl, '_cookiejar', None) or getattr(ydl, 'cookiejar', None)
            if cj:
                try:
                    cj.add_cookie_header(req_obj)
                except Exception as ex:
                    logger.debug(f'Cookie injection failed: {ex}')

        def _inject_credentials(r, u, s):
            if not _host_allows_credentials(u, s):
                return
            if s == 'youtube':
                try:
                    ydl = self.server.app_core.youtube._get_ydl('high')
                    _inject_ydl_cookies(ydl, r)
                except Exception as ex:
                    logger.warning(f'Error injecting YouTube cookies: {ex}')
            elif s == 'soundcloud':
                try:
                    ydl = self.server.app_core.soundcloud._get_ydl()
                    _inject_ydl_cookies(ydl, r)
                except Exception as ex:
                    logger.warning(f'Error injecting SoundCloud cookies: {ex}')
            elif s == 'yandex':
                token = ''
                if self.server.app_core.settings:
                    token = self.server.app_core.settings.get('auth', 'yandex_token', '')
                if token:
                    r.add_header('Authorization', f'OAuth {token}')

        req = urllib.request.Request(target_url)
        if has_range_request:
            req.add_header('Range', range_header)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        _inject_credentials(req, target_url, source)

        resp = None
        max_retries = 3
        had_connection_issue = False

        for attempt in range(max_retries + 1):
            try:
                resp = _safe_urlopen(req, timeout=12.0)
                if had_connection_issue and hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
                    self.server.app_core.api.emit_event('proxy_status', {'proxy': 'connected'})
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404, 410) and source and source_id and attempt == 0:
                    logger.info(f'Received HTTP {e.code} for {source}:{source_id}. Invalidating cache and self-healing re-resolution...')
                    try:
                        resolver = getattr(self.server.app_core, 'resolver', None)
                        if resolver is not None:
                            resolver.invalidate(source, str(source_id))
                    except Exception:
                        pass
                    try:
                        resolve_event = threading.Event()
                        new_url = None

                        def _on_resolved(url, metadata=None):
                            nonlocal new_url
                            new_url = url
                            resolve_event.set()

                        self.server.app_core.re_resolve_stream_url_async(source, str(source_id), _on_resolved)
                        resolve_event.wait(timeout=7)

                        if new_url and _is_ssrf_safe_url(new_url):
                            target_url = new_url
                            req = urllib.request.Request(new_url)
                            if has_range_request:
                                req.add_header('Range', range_header)
                            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                            _inject_credentials(req, new_url, source)
                            continue  # Retry request with newly resolved URL!
                        else:
                            self.send_response(e.code)
                            self._send_cors_headers()
                            self.end_headers()
                            return None
                    except Exception as re_err:
                        logger.warning(f'Re-resolution failed: {re_err}')
                        self.send_response(e.code)
                        self._send_cors_headers()
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
                        self._send_cors_headers()
                        self.end_headers()
                        return None
            except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError) as e:
                had_connection_issue = True
                if attempt < max_retries:
                    backoff = 1.5 ** attempt + random.uniform(0.1, 0.5)
                    logger.warning(f'Network error {e}, retrying in {backoff:.2f}s...')
                    time.sleep(backoff)
                    continue
                else:
                    self.send_error(502, 'Bad Gateway / Upstream connection failed')
                    return None
            except Exception as e:
                logger.error(f'Unexpected proxy error: {e}')
                self.send_error(500, 'Internal Server Error')
                return None

        if resp is None:
            self.send_error(502, 'Bad Gateway / Upstream connection failed')
            return None

        status_code = getattr(resp, 'status', getattr(resp, 'code', 200))
        resp_headers = resp.getheaders() if hasattr(resp, 'getheaders') else resp.info().items()

        # Upstream gave 200 OK instead of 206 Partial Content.
        # We pass it through directly without emulating Range to avoid tight loop CPU burns.

        # Standard 200 / 206 response
        self.send_response(status_code)
        for header, val in resp_headers:
            h_low = header.lower()
            if h_low not in HOP_BY_HOP and not h_low.startswith('access-control-'):
                self.send_header(header, val)

        self._send_cors_headers()
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization, X-Requested-With')
        self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
        self.end_headers()

        try:
            cache_ext = _ext_for_response(resp) if is_cachable_request else ''
            if is_cachable_request and status_code in (200, 206) and temp_path and streams_dir and cache_ext:
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

                final_path = os.path.join(streams_dir, f"{cache_name}{cache_ext}")
                bytes_written = 0
                with open(temp_path, 'wb') as tmp:
                    while True:
                        chunk = resp.read(32768)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        self.wfile.write(chunk)
                        tmp.write(chunk)

                if (bytes_written >= 65536 and 
                    (expected_len is None or bytes_written == expected_len) and
                    _is_valid_audio_cache_file(temp_path)):
                    try:
                        os.replace(temp_path, final_path)
                        if hasattr(self.server.app_core, 'db'):
                            self.server.app_core.db.set_cached_file(source, str(source_id), final_path)
                        logger.info(f'Stream cached successfully to {final_path}')
                    except Exception as pe:
                        logger.warning(f'Could not save stream cache {final_path}: {pe}')
                else:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
            else:
                while True:
                    chunk = resp.read(32768)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            if is_cachable_request and temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f'Error proxying stream: {e}')
            if is_cachable_request and temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        finally:
            if resp is not None and hasattr(resp, "close"):
                try:
                    resp.close()
                except Exception:
                    pass
        return None


def get_real_thread_class():
    import threading
    return getattr(threading, '_original_Thread', threading.Thread)


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
            thread_cls = get_real_thread_class()
            self.thread = thread_cls(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info(f'Local HTTP stream proxy started on port {self.port}')
            try:
                with open('/tmp/nedotify_proxy_info', 'w') as f:
                    f.write(f"{self.port}:{self.token}")
            except Exception:
                pass
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
        if original_url:
            params['url'] = original_url
        if not params:
            return original_url or ''
        if self.token:
            params[AUTH_PARAM] = self.token
        query = urllib.parse.urlencode(params)
        return f'http://127.0.0.1:{self.port}/api/stream?{query}'