# Handoff Report — Explorer 1 (Milestone 1: Audio Playback & Local HTTP Proxy Fixes)

## 1. Observation

### 1.1 Direct Code Observations in `core/proxy.py`

#### Feature 1: Unhandled Socket Disconnections in `StreamProxyHandler._proxy_stream`
- **Location**: `core/proxy.py`, lines 201–206 and lines 222–228.
- **Code snippet**:
  ```python
  201: while True:
  202:     chunk = resp.read(32768)
  203:     if not chunk:
  204:         break
  205:     self.wfile.write(chunk)
  ...
  222: except Exception as e:
  223:     logger.error(f"Error proxying stream {stream_url}: {e}")
  224:     try:
  225:         self.send_error(500, f"Proxy Stream Error: {e}")
  226:     except Exception:
  227:         pass
  ```
- **Observed Behavior & Exceptions**:
  When an HTML5 `<audio>` element in pywebview seeks, pauses, changes tracks, or teardowns during crossfade, it closes its TCP socket connection to `http://127.0.0.1:<port>/api/stream`.
  Subsequent calls to `self.wfile.write(chunk)` raise client socket disconnection exceptions:
  - `ConnectionResetError` (which manifests as `[WinError 10053] An established connection was aborted by the software in your host machine` on Windows, or `Errno 104` on POSIX).
  - `BrokenPipeError` (`[Errno 32] Broken pipe` on POSIX / Unix).
  - `ConnectionAbortedError` (`[WinError 10053]` or `[Errno 103]`).
  - `socket.error` / `OSError` (base exception classes).
  Because there is no dedicated exception handler around `self.wfile.write(chunk)` or within `_proxy_stream()`, the error falls through to `except Exception as e:` at line 222.
  This triggers `logger.error(...)` (logging false errors) and attempts `self.send_error(500)` on an already-closed socket, throwing secondary nested socket errors.

#### Feature 2: Local Disk File Rejection by SSRF Validator
- **Location**: `core/proxy.py`, lines 36–51, lines 118–120, and lines 129–131.
- **Code snippet**:
  ```python
  36: def _is_safe_url(url: str) -> bool:
  ...
  41:     if parsed.scheme not in ('http', 'https'):
  42:         return False
  ...
  118: if not real_url or not _is_safe_url(real_url):
  119:     self.send_error(400, "Invalid or unsafe stream URL")
  120:     return
  ...
  129: file_path = track_obj.get('file_path')
  130: if file_path and _is_safe_url(file_path):
  131:     return file_path
  ```
- **Observed Behavior**:
  For downloaded tracks, `track_obj['file_path']` contains a local filesystem path (e.g. `C:\Users\...\track.mp3` or `.cache/downloads/track.mp3`).
  `urllib.parse.urlparse(file_path).scheme` evaluates to `'c'` or `''` (not `'http'` or `'https'`).
  Therefore, `_is_safe_url(file_path)` returns `False`.
  Line 130 rejects local disk paths in `_find_playable_url()`, and line 118 rejects them in `do_GET()`, responding with HTTP `400 Invalid or unsafe stream URL`. Furthermore, local files need direct byte-streaming via `open(file_path, 'rb')` rather than `urllib.request.urlopen()`.

#### Feature 4: Incomplete Range Request Handling & Partial Content Math
- **Location**: `core/proxy.py`, lines 84–122 (`do_GET()`) and lines 177–206 (`_proxy_stream()`).
- **Code snippet**:
  ```python
  181: range_header = self.headers.get('Range')
  182: if range_header:
  183:     req.add_header('Range', range_header)
  ...
  194: # Forward safe headers
  195: for key, val in resp.headers.items():
  196:     if key.lower() not in HOP_BY_HOP:
  197:         self.send_header(key, val)
  ```
- **Observed Behavior**:
  While `_proxy_stream()` forwards the client's `Range` header to upstream servers, it does not explicitly guarantee `Accept-Ranges: bytes` header injection if upstream omits it.
  More critically, when streaming local disk files (Feature 2), there is no mechanism in `proxy.py` to parse `Range: bytes=start-end`, construct proper `206 Partial Content` responses (`Content-Range: bytes start-end/total`, `Content-Length`, `Accept-Ranges: bytes`), or perform chunked file seeking/reading.

---

## 2. Logic Chain

1. **Client Disconnection Cause & Effect (Feature 1)**:
   - *Observation*: HTML5 `<audio>` elements close HTTP requests when skipping, seeking, pausing, or tearing down crossfade instances.
   - *Deduction*: `self.wfile.write(chunk)` fails with `ConnectionResetError`, `BrokenPipeError`, `ConnectionAbortedError`, `socket.error`, `OSError` (specifically `[WinError 10053]`).
   - *Conclusion*: Wrapping `self.wfile.write(chunk)` in a `try...except CLIENT_DISCONNECT_ERRORS` block and breaking out of the streaming loop suppresses error logging and prevents redundant `send_error(500)` calls on closed sockets.

2. **Local File Proxy Path Validation (Feature 2)**:
   - *Observation*: `_is_safe_url()` expects `scheme in ('http', 'https')` and rejects local file paths (`C:\...` or `/path/...`).
   - *Deduction*: Downloaded tracks with valid `file_path` are rejected with HTTP 400.
   - *Conclusion*: Introducing `_is_local_file(path)` (verifying `os.path.isfile(path)`) allows local paths to be validated and routed to a dedicated `_serve_local_file(file_path)` method, bypassing SSRF domain checks safely.

3. **HTTP 206 Partial Content Compliance (Feature 4)**:
   - *Observation*: HTML5 audio elements issue Range requests (`Range: bytes=0-` or `Range: bytes=1000-2000`) for audio seeking and probing.
   - *Deduction*: Serving local files requires parsing byte range boundaries (`start`, `end`), validating bounds against `file_size`, sending HTTP `206 Partial Content` (or `416 Range Not Satisfiable`), returning `Content-Range: bytes start-end/total`, setting `Content-Length: end - start + 1`, and seeking `f.seek(start)` before streaming.
   - *Conclusion*: Combining range parsing with chunked file reading and disconnect suppression delivers fully compliant HTTP 206 streaming for local tracks and robust 200/206 proxying for remote streams.

---

## 3. Caveats

- **Network-Level Disconnections**: Remote stream proxying relies on `urllib.request.urlopen()`. If upstream drops connection midway (e.g. YouTube server reset), `resp.read()` might raise `http.client.IncompleteRead` or `socket.timeout`. These should be handled cleanly without crashing the proxy thread.
- **File System Permissions**: On Windows, file paths with Cyrillic characters or long paths must be accessed using standard Python `open(path, 'rb')` which handles Unicode paths natively in Python 3.

---

## 4. Conclusion

`core/proxy.py` requires three key modifications to achieve complete stability for Milestone 1:
1. **Client Disconnection Suppression**: Catch `(ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error, OSError)` inside `_proxy_stream` write loops and exit cleanly without `logger.error` or `send_error(500)`.
2. **Local File Proxy Routing**: Introduce `_is_local_file()` check to route downloaded tracks (`file_path`) directly to `_serve_local_file()`.
3. **HTTP Range & 206 Partial Content Engine**: Implement `_parse_range_header()` and `_serve_local_file()` with exact `Content-Range`, `Content-Length`, `Accept-Ranges: bytes` headers, precise byte math, and chunked disconnect-safe streaming.

---

## 5. Verification Method

1. **Unit & Integration Test Suite**:
   Run the proxy test script to verify Range request handling and stream response codes:
   ```powershell
   python test_proxy.py
   ```
2. **Disconnect Suppression Verification**:
   Inspect `_proxy_stream()` and `_serve_local_file()`. Ensure `CLIENT_DISCONNECT_ERRORS` catches `ConnectionResetError` (WinError 10053) around `wfile.write()` and breaks loop without calling `logger.error` or `send_error(500)`.
3. **Local File Stream Verification**:
   Pass a local MP3 file path to `_find_playable_url()` and test HTTP request to proxy URL. Verify response status is HTTP `200 OK` (without Range) or HTTP `206 Partial Content` (with `Range: bytes=0-`), and headers contain `Content-Range` and `Content-Length`.

---

## 6. Proposed Code Implementation for `core/proxy.py`

Below is the complete, exact Python code formulated for `core/proxy.py`:

```python
"""
NeDotify - Local HTTP Stream Proxy
Proxies cloud stream requests to inject authentication headers/cookies,
support local file streaming, range requests, and socket abort resilience.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import mimetypes
import os
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

CLIENT_DISCONNECT_ERRORS = (
    ConnectionResetError,
    BrokenPipeError,
    ConnectionAbortedError,
    socket.error,
    OSError,
)

HOP_BY_HOP = frozenset({
    'connection', 'keep-alive', 'proxy-authenticate',
    'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'
})

ALLOWED_STREAM_DOMAINS = (
    'youtube.com', 'youtu.be', 'googlevideo.com',
    'soundcloud.com', 'sndcdn.com',
    'yandex.ru', 'yandex.net',
    'spotify.com', 'scdn.co',
    'vk.com', 'vkuseraudio.net', 'userapi.com'
)

ALLOWED_CORS_ORIGINS = (
    'http://localhost', 'http://127.0.0.1', 'app://nedotify', 'file://'
)


def _is_local_file(path: str) -> bool:
    """Check if given string represents an existing valid local file."""
    if not path:
        return False
    try:
        if path.startswith('file://'):
            parsed = urllib.parse.urlparse(path)
            path = urllib.request.url2pathname(parsed.path)
        return os.path.exists(path) and os.path.isfile(path)
    except Exception:
        return False


def _is_safe_url(url: str) -> bool:
    """SSRF Protection: Ensure stream URL is HTTP(S) and targets safe public hosts."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = (parsed.hostname or '').lower()
        if not hostname or hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1') or hostname.startswith('169.254.'):
            return False
        if hostname.startswith('10.') or hostname.startswith('192.168.'):
            return False
        return True
    except Exception:
        return False


def _parse_range_header(range_header: str, file_size: int):
    """
    Parses HTTP Range header string (e.g. 'bytes=1000-2000' or 'bytes=1000-').
    Returns (start, end, content_length) or None if invalid.
    """
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        byte_range = range_header.split("bytes=", 1)[1].strip()
        if "," in byte_range:
            byte_range = byte_range.split(",", 1)[0].strip()
        parts = byte_range.split("-", 1)
        if len(parts) != 2:
            return None
        start_str, end_str = parts[0].strip(), parts[1].strip()
        if not start_str and not end_str:
            return None
        if not start_str:
            suffix_len = int(end_str)
            if suffix_len <= 0:
                return None
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        elif not end_str:
            start = int(start_str)
            end = file_size - 1
        else:
            start = int(start_str)
            end = int(end_str)
        if start < 0 or start >= file_size or start > end:
            return None
        end = min(end, file_size - 1)
        content_length = end - start + 1
        return (start, end, content_length)
    except Exception:
        return None


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server."""
    daemon_threads = True
    allow_reuse_address = True


class StreamProxyHandler(BaseHTTPRequestHandler):
    """HTTP Handler for proxying streaming requests."""

    app_core = None

    def log_message(self, format, *args):
        """Suppress default HTTP server stderr logging."""
        pass

    def _send_cors_headers(self):
        """Inject CORS headers with whitelist origin validation."""
        origin = self.headers.get('Origin', '')
        if any(origin.startswith(allowed) for allowed in ALLOWED_CORS_ORIGINS) or not origin:
            self.send_header('Access-Control-Allow-Origin', origin if origin else '*')
        else:
            self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1')
        self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')

    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()
        except CLIENT_DISCONNECT_ERRORS:
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        track_id = params.get('track_id', [None])[0]
        url = params.get('url', [None])[0]
        source = params.get('source', [None])[0]
        source_id = params.get('source_id', [None])[0]

        real_url = url
        track_obj = None

        if track_id and self.app_core and hasattr(self.app_core, 'db'):
            try:
                track_obj = self.app_core.db.get_track(int(track_id))
                if track_obj:
                    source = track_obj.get('source', source)
                    source_id = track_obj.get('source_id', source_id)
            except Exception as e:
                logger.error(f"Error fetching track {track_id} in proxy: {e}")

        if track_obj:
            real_url = self._find_playable_url(track_obj)
            if not real_url:
                real_url = self._resolve_stream_url(source, source_id, track_obj)
            if not real_url:
                real_url = track_obj.get('source_url') or track_obj.get('file_path') or url

        if not real_url and source and source_id and self.app_core:
            real_url = self._resolve_stream_url(source, source_id, track_obj)

        if not real_url:
            try:
                self.send_error(400, "Invalid or missing stream URL")
            except Exception:
                pass
            return

        if _is_local_file(real_url):
            self._serve_local_file(real_url)
        elif _is_safe_url(real_url):
            self._proxy_stream(real_url, source, source_id, track_id)
        else:
            try:
                self.send_error(400, "Invalid or unsafe stream URL")
            except Exception:
                pass

    def _find_playable_url(self, track_obj):
        """Return a cached playable stream URL or local file path for the track, or None."""
        if not track_obj:
            return None

        file_path = track_obj.get('file_path')
        if file_path and _is_local_file(file_path):
            return file_path

        source = track_obj.get('source')
        source_id = track_obj.get('source_id')
        if source and source_id and self.app_core and hasattr(self.app_core, 'db'):
            try:
                cached_stream = self.app_core.db.get_cached_stream(source, source_id)
                if cached_stream and cached_stream.get("stream_url") and \
                        _is_safe_url(cached_stream["stream_url"]):
                    return cached_stream["stream_url"]
            except Exception as e:
                logger.error(f"Error reading cached stream in proxy: {e}")

        return None

    def _resolve_stream_url(self, source, source_id, track_obj=None):
        """Synchronously re-resolve track stream URL via AppCore."""
        resolved_url = None
        event = threading.Event()

        def callback(url, meta=None):
            nonlocal resolved_url
            resolved_url = url
            event.set()

        def error_cb(err):
            event.set()

        try:
            if hasattr(self.app_core, 're_resolve_stream_url_async'):
                title = track_obj.get("title") if track_obj else None
                artist = track_obj.get("artist") if track_obj else None
                self.app_core.re_resolve_stream_url_async(
                    source=source,
                    source_id=source_id,
                    title=title,
                    artist=artist,
                    callback=callback,
                    on_error=error_cb
                )
                event.wait(timeout=16.0)
        except Exception as e:
            logger.error(f"Failed to re-resolve stream for {source}/{source_id}: {e}")

        return resolved_url

    def _serve_local_file(self, file_path: str):
        """Serve a local audio file with HTTP 200/206 Range support and client disconnect suppression."""
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            try:
                self.send_error(404, "Local File Not Found")
            except Exception:
                pass
            return

        try:
            file_size = os.path.getsize(file_path)
        except Exception as e:
            logger.error(f"Error accessing file size for {file_path}: {e}")
            try:
                self.send_error(500, "Internal Server Error")
            except Exception:
                pass
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        content_type = mime_type or 'audio/mpeg'

        range_header = self.headers.get('Range')

        if range_header:
            range_res = _parse_range_header(range_header, file_size)
            if range_res is None:
                try:
                    self.send_response(416)
                    self._send_cors_headers()
                    self.send_header('Content-Range', f'bytes */{file_size}')
                    self.end_headers()
                except CLIENT_DISCONNECT_ERRORS:
                    pass
                except Exception:
                    pass
                return

            start, end, content_length = range_res
            try:
                self.send_response(206)
                self._send_cors_headers()
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(content_length))
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
            except CLIENT_DISCONNECT_ERRORS:
                return
            except Exception:
                return
        else:
            start = 0
            end = file_size - 1
            content_length = file_size
            try:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(content_length))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
            except CLIENT_DISCONNECT_ERRORS:
                return
            except Exception:
                return

        bytes_remaining = content_length
        chunk_size = 32768

        try:
            with open(file_path, 'rb') as f:
                f.seek(start)
                while bytes_remaining > 0:
                    to_read = min(chunk_size, bytes_remaining)
                    chunk = f.read(to_read)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except CLIENT_DISCONNECT_ERRORS as conn_err:
                        logger.debug(f"Client disconnected during local file stream: {conn_err}")
                        break
                    bytes_remaining -= len(chunk)
        except CLIENT_DISCONNECT_ERRORS as conn_err:
            logger.debug(f"Client socket closed while streaming local file {file_path}: {conn_err}")
        except Exception as e:
            logger.error(f"Error streaming local file {file_path}: {e}")

    def _proxy_stream(self, stream_url, source=None, source_id=None, track_id=None):
        """Fetch and pipe upstream audio stream back to client with range support and disconnect protection."""
        req = urllib.request.Request(stream_url)

        range_header = self.headers.get('Range')
        if range_header:
            req.add_header('Range', range_header)

        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                self.send_response(status_code)
                self._send_cors_headers()

                has_accept_ranges = False
                for key, val in resp.headers.items():
                    if key.lower() not in HOP_BY_HOP:
                        self.send_header(key, val)
                        if key.lower() == 'accept-ranges':
                            has_accept_ranges = True
                
                if not has_accept_ranges:
                    self.send_header('Accept-Ranges', 'bytes')

                self.end_headers()

                while True:
                    chunk = resp.read(32768)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except CLIENT_DISCONNECT_ERRORS as conn_err:
                        logger.debug(f"Client disconnected during stream proxy: {conn_err}")
                        break

        except urllib.error.HTTPError as e:
            logger.warning(f"Upstream HTTPError {e.code} for {stream_url}")
            if e.code in (401, 403, 404, 410) and source and source_id:
                retry_track = None
                if track_id and self.app_core and hasattr(self.app_core, 'db'):
                    try:
                        retry_track = self.app_core.db.get_track(int(track_id))
                    except Exception:
                        pass
                new_url = self._resolve_stream_url(source, source_id, retry_track)
                if new_url and new_url != stream_url:
                    self._proxy_stream(new_url, source, source_id, track_id)
                    return
            try:
                self.send_error(e.code, f"Upstream HTTP Error {e.code}")
            except Exception:
                pass

        except CLIENT_DISCONNECT_ERRORS as conn_err:
            logger.debug(f"Client socket disconnect during proxy stream: {conn_err}")

        except Exception as e:
            logger.error(f"Error proxying stream {stream_url}: {e}")
            try:
                self.send_error(500, f"Proxy Stream Error: {e}")
            except Exception:
                pass
```
