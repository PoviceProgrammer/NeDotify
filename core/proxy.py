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
        super().__init__(server_address, RequestHandlerClass)

    def process_request(self, request, client_address):
        thread_cls = get_real_thread_class()
        t = thread_cls(target=self.process_request_thread, args=(request, client_address))
        t.daemon = self.daemon_threads
        if self._threads is None or not isinstance(self._threads, list):
            self._threads = []
        self._threads = [th for th in self._threads if hasattr(th, "is_alive") and th.is_alive()]
        self._threads.append(t)
        t.start()


class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP Request Handler to proxy cloud streams and handle credentials and re-resolution.
    """

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
            return True  # token generation failed; fail open rather than break playback
        supplied = (query_params.get(AUTH_PARAM) or [''])[0]
        return hmac.compare_digest(str(supplied), str(expected))

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
                    pass
        else:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(file_size))
            self._send_cors_headers()
            self.end_headers()
            with open(file_path, 'rb') as f:
                import shutil
                shutil.copyfileobj(f, self.wfile)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if not self._authorized(query_params):
            logger.warning('Rejected unauthenticated proxy request: %s', parsed_path.path)
            self._reject_unauthorized()
            return None

        if parsed_path.path == '/api/stream':
            track_id = query_params.get('track_id', [None])[0]
            source = query_params.get('source', [None])[0]
            source_id = query_params.get('source_id', [None])[0]
            title = query_params.get('title', [''])[0]
            artist = query_params.get('artist', [''])[0]

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
                if not source_id and not int_track_id:
                    self.send_error(400, 'Missing track_id or source_id')
                    return None
                source = source if source else 'youtube'
                track = {
                    'id': int_track_id or 0,
                    'source': source,
                    'source_id': source_id if source_id else f"{artist} {title}".strip(),
                    'title': title,
                    'artist': artist,
                }

            source = track.get('source') or source or 'youtube'
            source_id = track.get('source_id') or source_id

            if source == 'local':
                file_path = track.get('file_path') or track.get('url')
                if file_path and os.path.exists(file_path):
                    self.serve_local_file(file_path)
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

            target_url = self.server.app_core.engine.resolve_stream_url(track)
            if not target_url:
                try:
                    self.send_error(404, 'Stream not found')
                except Exception:
                    pass
                return None

            # Same SSRF gate as the ?url= branch: a resolver or a poisoned DB cache
            # row must never be able to make the proxy fetch an internal address.
            if not _is_ssrf_safe_url(target_url):
                logger.warning('SSRF guard blocked resolved stream URL for %s:%s', source, source_id)
                try:
                    self.send_error(400, 'Resolved stream URL blocked by SSRF validation')
                except Exception:
                    pass
                return None

            final_path = os.path.join(streams_dir, f"{cache_name}.m4a")
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

            is_webpage = target_url and any(domain in target_url for domain in ('soundcloud.com', 'youtube.com', 'youtu.be'))

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

            # SSRF guard: reject URLs resolving to internal/private hosts (same logic as core/api.py).
            if not _is_ssrf_safe_url(target_url):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'URL blocked: SSRF validation failed'}).encode('utf-8'))
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
        import random
        import socket
        import time
        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                resp = _safe_urlopen(req, timeout=12.0)
                if hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
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
                            pass
                        try:
                            import threading
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

                bytes_written = 0
                with open(temp_path, 'wb') as tmp:
                    while True:
                        chunk = resp.read(32768)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        self.wfile.write(chunk)
                        try:
                            self.wfile.flush()
                        except Exception:
                            pass
                        tmp.write(chunk)

                if bytes_written > 0 and (expected_len is None or bytes_written == expected_len):
                    os.replace(temp_path, final_path)
                    self.server.app_core.db.set_cached_file(source, source_id, final_path)
                    logger.info(f'Stream cached successfully to {final_path}')
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
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
            logger.debug(f'Stream client disconnected: {ce}')
            if is_cachable_request and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f'Error proxying stream: {e}')
            if is_cachable_request and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        finally:
            resp.close()

        return None


def get_real_thread_class():
    import sys
    import importlib
    import threading
    if threading.Thread.__name__ != 'Thread':
        patched_threading = sys.modules.pop('threading', None)
        try:
            real_threading = importlib.import_module('threading')
            return real_threading.Thread
        finally:
            if patched_threading is not None:
                sys.modules['threading'] = patched_threading
    return threading.Thread


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
        except Exception as e:
            logger.error(f'Failed to start local proxy server: {e}')

    def stop(self):
        self.token = ''
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            try:
                self.server.server_close()
            except Exception:
                pass
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