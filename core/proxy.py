"""
NeDotify - Local HTTP Stream Proxy
Proxies cloud stream requests to inject authentication headers/cookies and support self-healing stream URL re-resolution.
"""
import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import threading
import logging

logger = logging.getLogger(__name__)

HOP_BY_HOP = frozenset({'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization', 'connection', 'te', 'transfer-encoding', 'keep-alive'})


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Multi-threaded HTTP server holding a reference to the application core.
    """
    block_on_close = False

    def __init__(self, server_address, RequestHandlerClass, app_core):
        self.app_core = app_core
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
    def serve_local_file(self, file_path):
        import os
        import mimetypes
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
                self.send_header('Access-Control-Allow-Origin', '*')
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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(file_path, 'rb') as f:
                import shutil
                shutil.copyfileobj(f, self.wfile)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)
        if parsed_path.path == '/api/stream':
            track_id = query_params.get('track_id', [None])[0]
            if not track_id:
                self.send_error(400, 'Missing track_id')
                return None
            import os
            try:
                track_id = int(track_id)
            except ValueError:
                pass

            track = self.server.app_core.db.get_track(track_id)
            if not track:
                source = query_params.get('source', ['youtube'])[0]
                source_id = query_params.get('source_id', [None])[0]
                title = query_params.get('title', [''])[0]
                artist = query_params.get('artist', [''])[0]
                track = {
                    'id': track_id,
                    'source': source if source else 'youtube',
                    'source_id': source_id if source_id else f"{artist} {title}".strip(),
                    'title': title,
                    'artist': artist,
                }

            source = track.get('source')
            source_id = track.get('source_id')

            if source == 'local':
                file_path = track.get('file_path') or track.get('url')
                if file_path and os.path.exists(file_path):
                    self.serve_local_file(file_path)
                    return None
                self.send_error(404, 'Local file not found')
                return None

            cached_stream = self.server.app_core.db.get_cached_stream(source, source_id)
            if cached_stream and cached_stream.get('cached_file_path') and os.path.exists(cached_stream['cached_file_path']):
                self.serve_local_file(cached_stream['cached_file_path'])
                return None

            target_url = self.server.app_core.engine.resolve_stream_url(track)
            if not target_url:
                try:
                    self.send_error(404, 'Stream not found')
                except Exception:
                    pass
                return None

            streams_dir = self.server.app_core.cache._streams_dir
            temp_path = os.path.join(self.server.app_core.cache._temp_dir, f"{track_id}.tmp")
            final_path = os.path.join(streams_dir, f"{track_id}.m4a")

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

        if source == 'youtube':
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
            token = ''
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
                resp = urllib.request.urlopen(req, timeout=12.0)
                if hasattr(self.server.app_core, 'api') and hasattr(self.server.app_core.api, 'emit_event'):
                    self.server.app_core.api.emit_event('proxy_status', {'proxy': 'connected'})
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404, 410):
                    if e.code in (403, 410) and source and source_id and attempt == 0:
                        logger.info(f'Received HTTP {e.code} for {source}:{source_id}. Attempting self-healing re-resolution...')
                        try:
                            import threading
                            resolve_event = threading.Event()
                            new_url = None

                            def _on_resolved(url):
                                nonlocal new_url
                                new_url = url
                                resolve_event.set()

                            self.server.app_core.re_resolve_stream_url_async(source, source_id, _on_resolved)
                            resolve_event.wait(timeout=15)

                            if new_url:
                                req = urllib.request.Request(new_url)
                                if 'Range' in self.headers:
                                    req.add_header('Range', self.headers['Range'])
                                req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

                                if source == 'youtube':
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

        cors_sent = False
        for header, val in headers_list:
            h_low = header.lower()
            if h_low not in HOP_BY_HOP:
                if h_low == 'access-control-allow-origin':
                    cors_sent = True
                self.send_header(header, val)

        if not cors_sent:
            self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
        self.end_headers()

        import os

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

    def start(self):
        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), StreamProxyHandler, self.app_core)
            self.port = self.server.server_port
            thread_cls = get_real_thread_class()
            self.thread = thread_cls(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info(f'Local HTTP stream proxy started on port {self.port}')
        except Exception as e:
            logger.error(f'Failed to start local proxy server: {e}')

    def stop(self):
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

    def get_proxy_url(self, source, source_id, original_url=None, track_id=None):
        if not self.port:
            return original_url
        if track_id:
            return f'http://127.0.0.1:{self.port}/api/stream?track_id={track_id}'
        if not original_url:
            return ''
        params = {
            'url': original_url,
            'source': source if source else '',
            'source_id': source_id if source_id else '',
        }
        query = urllib.parse.urlencode(params)
        return f'http://127.0.0.1:{self.port}/?{query}'