# Handoff Report: Streaming and Playback Loop Analysis

## 1. Observation

Direct observations from the codebase files:

### A. VLC Integration and Events
- **File**: `audio/engine.py` (lines 81-90)
  Event manager attaches `MediaPlayerEndReached` and `MediaPlayerEncounteredError` event listeners:
  ```python
  # Set up event handlers for player A
  events_a = self._player_a.event_manager()
  events_a.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end_reached)
  events_a.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)
  ```
- **File**: `audio/engine.py` (lines 444-462)
  `_on_end_reached` triggers queue advancement in a daemon thread:
  ```python
  def _on_end_reached(self, event):
      """Handle end of media event."""
      if not self._crossfade_active:
          # Auto-advance to next track
          if self._on_track_end:
              self._on_track_end()

          def _advance():
              time.sleep(0.1)
              track = self.queue.next_track()
              if track:
                  self.play_track(track)
              else:
                  self._is_playing = False
                  self._is_paused = False
                  if self._on_state_changed:
                      self._on_state_changed("stopped")

          threading.Thread(target=_advance, daemon=True).start()
  ```
- **File**: `audio/engine.py` (lines 464-470)
  `_on_vlc_error` stops the engine:
  ```python
  def _on_vlc_error(self, event):
      """Handle VLC playback error (e.g. HTTP 403)."""
      logger.error("VLC encountered an error during playback.")
      self.stop()
      if self._on_error:
          self._on_error("VLC player error: Не удалось воспроизвести поток (возможно, трек заблокирован)")
  ```

### B. Cloud Services and Cookies Configuration
- **File**: `services/youtube_service.py` (lines 92-100)
  ```python
  # Cascading cookie import priority logic
  if self.settings:
      cookies_file_path = self.settings.get("auth", "cookies_file_path", "")
      browser_cookies = self.settings.get("auth", "browser_cookies", "none")
      
      if cookies_file_path and os.path.exists(cookies_file_path):
          opts['cookiefile'] = cookies_file_path
      elif browser_cookies and browser_cookies != "none":
          opts['cookiesfrombrowser'] = (browser_cookies, )
  ```
- **File**: `services/yandex_service.py` (lines 38-42)
  ```python
  token = self.settings.get("auth", "yandex_token", "") if self.settings else ""
  if token:
      try:
          self._client = Client(token).init()
  ```
- **File**: `requirements.txt`
  Contains only general libraries: `pywebview`, `python-vlc`, `mutagen`, `yt-dlp`, `colorthief`, `Pillow`, `pyloudnorm`, `soundfile`. It does not contain any third-party HTTP servers or clients (like `requests`, `Flask`, `aiohttp`).

---

## 2. Logic Chain

1. **VLC Error Handling and Stopping**: When a stream fails (e.g. HTTP 403 / 410 on video URLs), VLC fires `MediaPlayerEncounteredError` (Observation 1A). This calls `self._on_vlc_error`, which invokes `self.stop()`.
2. **Infinite Skipping Loop**: Because `self.stop()` resets states and terminates playback, VLC flags the current item as finished, firing the `MediaPlayerEndReached` event. This calls `self._on_end_reached` (Observation 1A), which calls `_advance()` after a 100ms sleep. `_advance` grabs the next track from the queue and calls `self.play_track()`. If that track also fails, the chain repeats. In repeat/loop modes, this results in an infinite high-speed skipping loop.
3. **Cookie and User-Agent Bindings**: YouTube stream links extracted by `yt-dlp` are tied to the client IP address and require the exact same User-Agent header (Observation 1B). For restricted tracks, browser/Netscape cookies configured in the YouTube service settings must be included in the requests. Currently, VLC makes direct connections without cookie injection, leading to HTTP 403 Forbidden.
4. **Lightweight Proxy Server**: Since no HTTP server packages exist in the project dependencies (Observation 1B), Python's built-in `http.server.HTTPServer` with `socketserver.ThreadingMixIn` is the best solution. It allows routing VLC's requests locally, dynamically injecting headers/cookies from the backend, and implementing a transparent self-healing re-resolution mechanism.

---

## 3. Caveats

- **Network-Level Issues**: If the user's internet connection is completely down, all tracks will fail. The self-healing logic must check for this case or abort skipping early (which the proposed counter fixes).
- **VLC Event Handlers**: On some OS platforms, the sequence of VLC events (`MediaPlayerEncounteredError` vs `MediaPlayerEndReached`) can vary. Using a consecutive failure counter inside `_advance` is robust against event-ordering differences.
- **Browser Cookies Decryption**: If the browser's database is locked or permissions are denied, cookie extraction via `cookiesfrombrowser` can fail. The proxy code handles this gracefully with warning logging and fallback to cookies.txt.

---

## 4. Conclusion

The dual-player VLC architecture works efficiently but lacks error protection, leading to infinite skipping loops when encountering expired or cookie-restricted cloud URLs.
By implementing a failure counter (aborting after 3 consecutive failures) in `audio/engine.py` and a built-in threading local HTTP proxy in `core/app.py`, the player can cleanly bypass cookie/user-agent restrictions and dynamically refresh expired CDN stream links.

---

## 5. Verification Method

1. **Verify Infinite skipping bug**:
   - In a playlist, queue a few tracks with invalid `file_path` values (e.g. `http://invalid.url/track.mp3`).
   - Start playback. Observe that the queue skips through all tracks at high speed without stopping.
2. **Verify HTTP Proxy functionality**:
   - Run python mock tests locally (e.g. using `unittest` or a separate script) to test `StreamProxyHandler` with range requests:
     ```bash
     curl -I -H "Range: bytes=0-100" "http://127.0.0.1:<PORT>/stream?source=youtube&url=<TEST_URL>"
     ```
   - Verify that it returns `206 Partial Content` and the headers contain `Content-Range`.

---

## 6. Remaining Work (Implementation Steps)

1. **Implement `StreamProxyServer` and `LocalProxyManager`** in a new file `core/proxy.py` or directly inside `core/app.py`.
2. **Wire the Proxy** into `core/app.py`'s lifecycle (init starts the server on port `0`, cleanup stops the server).
3. **Update `AudioEngine.play_track()`** to rewrite stream URLs pointing to `youtube`, `soundcloud`, and `yandex` so that they route through the local proxy.
4. **Add error loop protection** inside `audio/engine.py` using `self._consecutive_failures`. Abort automatic skipping when the counter reaches 3.
