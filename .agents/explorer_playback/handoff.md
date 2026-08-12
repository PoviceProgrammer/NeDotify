# Handoff Report — Audio Playback & Local HTTP Proxy Architecture Investigation

## 1. Observation

### 1.1 Codebase Structure and Key Files Identified
The Audio Playback, Local HTTP Proxy, and Stream Resolving system comprises the following components:

- **Local HTTP Proxy**: `core/proxy.py` (`LocalProxyManager`, `ThreadingHTTPServer`, `StreamProxyHandler`, `_is_safe_url`, `_proxy_stream`, `_resolve_stream_url`, `_find_playable_url`).
- **Application Core & Re-Resolution Bridge**: `core/app.py` (`AppCore.re_resolve_stream_url_async`, `AppCore.proxy`, `AppCore.youtube`, `AppCore.soundcloud`, `AppCore.yandex`, `AppCore.spotify`).
- **Web API Bridge (pywebview interface)**: `core/api.py` (`AppApi._on_track_changed`, `AppApi.play_track`, `AppApi._resolve_track`, `AppApi._emit`).
- **Audio Engine (Python Queue Coordinator)**: `audio/engine.py` (`AudioEngine._notify_track_changed`, `AudioEngine.resolve_stream_url`, `AudioEngine.play_queue`).
- **Audio Queue Data Structure**: `audio/queue.py` (`PlaybackQueue`).
- **Frontend Player & Dual HTML5 Audio Engine**: `ui/web_new/js/player.js` (`playTrack`, `setupAudioEvents`, `handleAudioElementError`, `cancelActiveFade`, `audioA`, `audioB`).
- **Frontend Event Listener & Bridge**: `ui/web_new/js/events.js` (`window.onPythonEvent`, `track_changed`, `state_changed`, `position_changed`).
- **FastAPI/SSE Fallback Bridge**: `core/fastapi_app.py`, `ui/web_new/js/apiclient.js`.
- **Music Services & Stream Resolvers**:
  - `services/youtube_service.py` (`YouTubeService.get_stream_url`, `_get_ydl_opts`, `yt-dlp` integration).
  - `services/soundcloud_service.py` (`SoundCloudService.get_stream_url`, DRM handling, fallback).
  - `services/spotify_service.py` (`SpotifyService.get_stream_url`, fallback to YouTube).
  - `services/yandex_service.py` (`YandexService.get_stream_url`, `yandex_music` client direct links).
- **Storage & Caching Managers**:
  - `core/database.py` (`DatabaseManager.get_cached_stream`, `DatabaseManager.cache_stream`, `stream_cache` table).
  - `utils/cache_manager.py` (`CacheManager.download_audio_stream`, `CacheManager.enforce_cache_limit`).
  - `core/downloader.py` (`DownloadManager._download_worker`, `queue_download`).

---

### 1.2 Verbatim Code & Behavioral Observations

#### Observation A: Unhandled Socket Connection Aborts (`WinError 10053`) in `core/proxy.py`
In `core/proxy.py`, lines 188–228:
```python
188: try:
189:     with urllib.request.urlopen(req, timeout=15) as resp:
190:         status_code = resp.getcode()
191:         self.send_response(status_code)
192:         self._send_cors_headers()
...
201:         while True:
202:             chunk = resp.read(32768)
203:             if not chunk:
204:                 break
205:             self.wfile.write(chunk)
...
222: except Exception as e:
223:     logger.error(f"Error proxying stream {stream_url}: {e}")
224:     try:
225:         self.send_error(500, f"Proxy Stream Error: {e}")
226:     except Exception:
227:         pass
```
When pywebview / Chromium HTML5 `<audio>` element cancels or seeks a stream, `self.wfile.write(chunk)` raises `ConnectionResetError: [WinError 10053] An established connection was aborted by the software in your host machine` (or `BrokenPipeError` / `ConnectionAbortedError`).
Because there is no dedicated exception handler for client disconnections around `wfile.write()`, the error falls into `except Exception as e:`, logs a severe error, and then attempts `self.send_error(500)` on the already-closed socket, throwing a secondary nested socket error.

#### Observation B: Flawed SSRF URL Checker Blocking Local Files in `core/proxy.py`
In `core/proxy.py`, lines 36–51 and lines 124–131:
```python
36: def _is_safe_url(url: str) -> bool:
37:     """SSRF Protection: Ensure stream URL is HTTP(S) and targets allowed audio domains or safe public hosts."""
...
41:         if parsed.scheme not in ('http', 'https'):
42:             return False
...
124: def _find_playable_url(self, track_obj):
129:     file_path = track_obj.get('file_path')
130:     if file_path and _is_safe_url(file_path):
131:         return file_path
```
For local files (e.g. `C:\Users\...\download.mp3`), `urllib.parse.urlparse(file_path).scheme` returns `'c'` or `''`.
`_is_safe_url` returns `False`.
Thus `_find_playable_url()` rejects local file paths and downloaded files, causing `StreamProxyHandler.do_GET()` to return HTTP `400 Invalid or unsafe stream URL`.

#### Observation C: Stream Expiration and Synchronous Proxy Blocking
In `core/database.py`, line 737:
```python
737: def get_cached_stream(self, source: str, source_id: str, max_age_seconds: int = 86400) -> Optional[Dict[str, Any]]:
```
Default `max_age_seconds` is `86400` (24 hours). However, YouTube (`googlevideo.com`) signatures expire in 4–6 hours.
When an expired URL returns `403` or `410` upstream, `proxy.py` calls `_resolve_stream_url()` (lines 146–175):
```python
171: event.wait(timeout=16.0)
```
This synchronously blocks the proxy worker thread for up to 16 seconds. In pywebview, `<audio>` elements time out after 5–10 seconds of unreceived HTTP headers, triggering frontend media errors (`MEDIA_ERR_NETWORK` / `MEDIA_ERR_SRC_NOT_SUPPORTED`).

#### Observation D: Dual Audio Crossfade Socket Leak in `ui/web_new/js/player.js`
In `ui/web_new/js/player.js`, lines 21–25, lines 31–42, and lines 254–280:
```python
21: let audioA = new Audio();
23: let audioB = new Audio();
...
31: function cancelActiveFade() {
32:     if (activeFade) {
33:         if (activeFade.intervalId) clearInterval(activeFade.intervalId);
34:         if (activeFade.oldAudio) {
35:             try {
36:                 activeFade.oldAudio.pause();
37:                 activeFade.oldAudio.currentTime = 0;
38:             } catch (e) {}
39:         }
40:         activeFade = null;
41:     }
42: }
```
When track changes or crossfade occurs, `oldAudio.pause()` is called, but `oldAudio.src` is NOT cleared (`oldAudio.removeAttribute('src'); oldAudio.load()`).
Chromium keeps the HTTP connection open to buffer data for `oldAudio` in the background, leading to socket pollution, resource competition, and `WinError 10053` when the proxy connection eventually drops.

---

## 2. Logic Chain

1. **Premise 1 (WinError 10053)**:
   HTML5 `<audio>` element sends Range requests (`Range: bytes=0-`) to probe audio metadata or buffers audio ahead of current playback position. When user skips tracks, seeks, or when crossfade pauses `oldAudio`, Chromium closes the TCP socket to `http://127.0.0.1:<port>/api/stream`.
2. **Premise 2 (Proxy Write Loop)**:
   In `StreamProxyHandler._proxy_stream`, the `while True:` loop attempts to write 32KB chunks via `self.wfile.write(chunk)` to the client socket without checking socket state or catching socket disconnection exceptions.
3. **Premise 3 (Exception Escapes to Logger)**:
   `self.wfile.write(chunk)` throws `ConnectionResetError` (`WinError 10053`). The generic `except Exception as e` block logs it as a fatal proxy error and invokes `self.send_error(500)` on the closed socket, generating double errors and polluting log output.
4. **Premise 4 (Local File Stream Failures)**:
   When tracks are downloaded locally (`is_downloaded = 1`), `file_path` points to a local disk path. `proxy.py` passes `file_path` through `_is_safe_url()`, which requires `scheme in ('http', 'https')`. Local paths fail this check, causing `400 Bad Request` responses on local playback through proxy.
5. **Premise 5 (Stream Expiration & Stale Caching)**:
   YouTube and SoundCloud URLs expire within hours due to URL signature expiration parameters (`expire=...`). Database `get_cached_stream` allows cached URLs up to 24 hours old. When proxy tries to fetch an expired URL, upstream returns HTTP `403 Forbidden` or `410 Gone`.
6. **Premise 6 (Proxy Resolution Delay & Frontend Error Cascade)**:
   `_proxy_stream` attempts self-healing re-resolution via `_resolve_stream_url()`, which blocks synchronously for up to 16 seconds (`event.wait(16.0)`). While proxy waits, pywebview `<audio>` element times out and triggers `handleAudioElementError`, incrementing `consecutivePlaybackErrors`. After 3 consecutive errors, playback stops completely.

---

## 3. Caveats

- **Zapret DPI Bypass Interaction**: `ZapretService` (`services/zapret_service.py`) manages WinDivert/zapret for YouTube/Discord DPI bypass. If Zapret is running, local socket connections to remote YouTube CDNs pass through WinDivert drivers. This investigation focused on `proxy.py` socket handling rather than Zapret driver behavior.
- **PyWebView Platform Specifics**: Behavior was evaluated under Windows (`winforms` / `MSHTML` / `Edge Chromium` webview engine). On macOS/Linux, socket reset exceptions manifest as `BrokenPipeError` or `ConnectionResetError` rather than `WinError 10053`, but the root cause and required fix in `proxy.py` are identical.

---

## 4. Conclusion

The primary causes of audio playback instability, `WinError 10053` errors, and pywebview stream failures in AURA Music are:
1. **Unhandled Client Socket Disconnections in `core/proxy.py`**: Client socket resets (from seek, pause, track change, crossfade) throw `WinError 10053` on `self.wfile.write()`, which is improperly treated as a server failure.
2. **Defective Local File Validation**: `_is_safe_url()` blocks local disk paths and downloaded files.
3. **Stale Stream URL Cache**: 24-hour stream cache TTL allows expired YouTube/SoundCloud links to be served, causing HTTP 403 errors.
4. **Synchronous Proxy Re-resolution Bottleneck**: 16-second synchronous wait in proxy handler causes HTML5 Audio timeout.
5. **Dangling Frontend Audio Sockets**: Crossfade dual-audio elements do not clear `src` on inactive audio, leaking HTTP streams.

---

## 5. Verification Method

To verify these findings and validate future fixes:

1. **Run Existing Test Suite**:
   ```powershell
   python run_tests.py
   ```
   Or run specific unit tests:
   ```powershell
   python test_proxy.py
   ```

2. **Proxy Socket Abort Verification**:
   Inspect `core/proxy.py`. Verify that `_proxy_stream` catches `(ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error, OSError)` around `self.wfile.write(chunk)` and cleanly breaks from the loop without logging errors or calling `send_error()`.

3. **Local File Proxy Verification**:
   Pass a local file path (`C:/Users/.../track.mp3`) to `get_proxy_url()`. Verify HTTP proxy returns `200 OK` or `206 Partial Content` instead of `400 Invalid or unsafe stream URL`.

4. **Stream Re-Resolution TTL Verification**:
   Inspect `get_cached_stream` calls in `proxy.py` and `database.py`. Verify YouTube stream TTL is limited to <= 3 hours (10800 seconds).

5. **Frontend Socket Cleanup Verification**:
   Inspect `ui/web_new/js/player.js`. Verify `cancelActiveFade()` and `handleAudioElementError()` execute:
   ```javascript
   oldAudio.pause();
   oldAudio.removeAttribute('src');
   oldAudio.load();
   ```

---

## 6. Specific Recommendations & Fix Strategies for Milestone 1

### Strategy 1: Safe Socket Writing and Disconnection Suppression in `core/proxy.py`
In `StreamProxyHandler._proxy_stream`:
- Wrap `self.wfile.write(chunk)` and `self.wfile.flush()` in a try-except block specifically catching client disconnections:
  ```python
  try:
      self.wfile.write(chunk)
  except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error, OSError) as conn_err:
      logger.debug(f"Client disconnected during stream proxy: {conn_err}")
      break
  ```
- Suppress calls to `self.send_error()` if headers have already been sent or if the error is a client socket disconnection.

### Strategy 2: Support Local File Streaming & Refined SSRF Validation
In `core/proxy.py`:
- Update `_is_safe_url(url)` to allow local files when explicitly serving local tracks, or handle local files in `do_GET()` directly:
  ```python
  if file_path and os.path.exists(file_path):
      # Stream local file directly with 200/206 Range support
      return self._serve_local_file(file_path)
  ```
- Ensure `ALLOWED_STREAM_DOMAINS` includes all YouTube, SoundCloud, Yandex, Spotify, and VK CDN domain patterns.

### Strategy 3: HTTP Range Request & 206 Partial Content Compliance
In `core/proxy.py` (`_proxy_stream`):
- Preserve and forward `Content-Range`, `Content-Length`, and `Accept-Ranges` headers accurately.
- When client requests a bounded Range (e.g. `bytes=0-1023`), stop writing after the requested byte count is delivered to prevent superfluous network transfer and socket aborts.

### Strategy 4: Reduced Stream Cache TTL & Non-Blocking Re-resolution
- In `core/proxy.py` / `core/database.py`: Set YouTube/SoundCloud stream cache TTL to 3 hours (`10800` seconds).
- On HTTP `403` / `410` upstream errors, perform quick async re-resolution with a shorter timeout (3–5s) or trigger frontend stream refresh.

### Strategy 5: Clean Audio Element Teardown in Frontend (`player.js`)
In `ui/web_new/js/player.js`:
- In `cancelActiveFade()` and `handleAudioElementError()`:
  ```javascript
  if (oldAudio) {
      try {
          oldAudio.pause();
          oldAudio.removeAttribute('src');
          oldAudio.load();
      } catch(e) {}
  }
  ```
- Prevent rapid error accumulation from stopping playback prematurely when individual track URLs fail.
