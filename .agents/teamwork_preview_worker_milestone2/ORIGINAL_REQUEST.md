## 2026-07-13T17:55:43Z
You are the Implementation Worker.
Your working directory is: c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\teamwork_preview_worker_milestone2

Please implement the local HTTP proxy and skipping loop prevention according to the following design:

1. Create a new file `core/proxy.py` containing the local HTTP proxy.
Requirements:
- Class `ThreadingHTTPServer` inheriting from `socketserver.ThreadingMixIn` and `http.server.HTTPServer`. Its `__init__` should accept `server_address`, `RequestHandlerClass`, and `app_core`, and save `self.app_core = app_core`.
- Class `StreamProxyHandler` inheriting from `http.server.BaseHTTPRequestHandler`.
  - Implement `do_GET` to extract `url`, `source`, and `source_id` query parameters.
  - Forward the request to the target URL using `urllib.request.Request`.
  - Handle `Range` header by forwarding it if present in `self.headers`.
  - Add standard browser `User-Agent`.
  - Inject cookies/headers from core services based on `source`:
    - For `youtube`: call `self.server.app_core.youtube._get_ydl('high')` and if it has a `cookiejar`, call `ydl.cookiejar.add_cookie_header(req)`.
    - For `soundcloud`: call `self.server.app_core.soundcloud._get_ydl()` and if it has a `cookiejar`, call `ydl.cookiejar.add_cookie_header(req)`.
    - For `yandex`: add `Authorization: OAuth <token>` if `auth.yandex_token` is present in settings.
  - Forward response status and headers back to the client (VLC), excluding hop-by-hop headers (connection, keep-alive, proxy-authenticate, proxy-authorization, te, trailer, transfer-encoding, upgrade).
  - Stream chunks of data (e.g. 64KB) to the client.
  - Implement self-healing re-resolution: if the target server returns 403 or 410, call `new_url = self.server.app_core.re_resolve_stream_url(source, source_id)` synchronously and retry the connection with the new URL.
- Class `LocalProxyManager` to manage start/stop lifecycle of the server, automatically binding to 127.0.0.1 on a dynamic port (using server_address=('127.0.0.1', 0)) and running in a daemon thread. Implement `get_proxy_url(source, source_id, original_url)`.

2. Update `core/app.py`:
- Import `LocalProxyManager` from `core.proxy`.
- In `AppCore.__init__()`:
  - Instantiate `self.proxy = LocalProxyManager(self)`.
  - Start the proxy: `self.proxy.start()`.
  - Inject proxy into the audio engine: `self.engine.proxy = self.proxy`.
- In `AppCore.cleanup()`:
  - Stop the proxy: `self.proxy.stop()`.
- Add `re_resolve_stream_url(self, source, source_id)` helper method:
  - Construct the lookup URL based on `source` (youtube, soundcloud, yandex) and `source_id`.
  - Call the service's `get_stream_url(url, callback, error_callback)` and wait synchronously for resolution using `threading.Event()`.
  - Return the resolved stream URL (and update the DB stream cache).

3. Update `audio/engine.py`:
- In `__init__()`:
  - Initialize `self.proxy = None`.
  - Initialize `self._consecutive_failures = 0`.
  - Initialize `self._playback_failed = False`.
- In `play_track()`:
  - Modify `is_cloud` to include `yandex`:
    `is_cloud = track.get("source") in ("youtube", "soundcloud", "vk", "yandex")`.
  - When playing, if the source is a cloud URL (`track.get("source") in ("youtube", "soundcloud", "yandex")` and startswith http), wrap it via `self.proxy.get_proxy_url(track.get("source"), track.get("source_id"), source)` if `self.proxy` is available.
- In `_poll_loop()`:
  - Reset `self._consecutive_failures = 0` and `self._playback_failed = False` once the track plays successfully (position > 1000ms).
- In `_on_vlc_error()`:
  - Set `self._playback_failed = True`.
  - Increment `self._consecutive_failures`.
- In `_on_end_reached()`:
  - Check if `self._playback_failed` is True:
    - If yes, set `self._playback_failed = False`.
    - If `self._consecutive_failures >= 3`:
      - Reset `self._consecutive_failures = 0`.
      - Stop playback and emit event (call state changed to "stopped" and do NOT advance to the next track).
      - Return immediately.
- In `next()`, `previous()`, and `play_queue()`:
  - Reset `self._consecutive_failures = 0`.

4. Run the test suite:
- Run `python -m unittest tests/test_nedotify.py` to verify that everything builds and passes.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## 2026-07-13T18:10:11Z
**Context**: Checking implementer progress.
**Content**: Hello, we noticed that your progress.md has not been updated for a while. Could you please provide a status update on the implementation of the proxy and error skipping loop?
**Action**: Please reply with your current status or update your progress.md.

