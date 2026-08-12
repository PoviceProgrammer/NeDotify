# Analysis and Recommendations: Stream Retrieval, VLC Integration, and Local Proxy Architecture

## 1. Executive Summary
This analysis document covers the streaming and playback subsystem of NeDotify (AURA Music). It identifies the root causes of playback errors and the infinite skipping loop bug, details the stream retrieval processes across YouTube, SoundCloud, and Yandex Music services, defines header/cookie requirements for successful stream playback, and provides a concrete architectural design for a lightweight, zero-dependency, threading-capable local HTTP proxy built using Python's standard libraries (`http.server`).

---

## 2. VLC Integration & Playback Loop Analysis

### 2.1 How the Playback Loop Works
NeDotify uses a dual-player VLC architecture implemented in `audio/engine.py` with two `vlc.MediaPlayer` instances (`_player_a` and `_player_b`).
1. **Triggering Playback**: The player is initiated by calling `play_track(track)`.
   - **Cloud Tracks**: If the track is from YouTube, SoundCloud, or Yandex Music, and has no `file_path` or was resolved >900 seconds ago, it is sent to `resolver_callback` (which invokes API handlers in `core/api.py` to get the direct stream URL and cache it).
   - Once the direct stream URL is available, the active player's media is initialized via `self._instance.media_new(source)`.
2. **Events**:
   - `MediaPlayerEndReached`: Triggers `_on_end_reached()`, which spawns a daemon thread `_advance()` to fetch the next track from `self.queue` after a 100ms delay and call `play_track(track)`.
   - `MediaPlayerEncounteredError`: Triggers `_on_vlc_error()`, which stops the player and invokes the error callback.
3. **Transitions**: A background thread running `_poll_loop` polls the position and duration every 250ms. If the remaining time is less than the crossfade/gapless threshold, it preloads the upcoming track on the inactive player and triggers a crossfade (fading volumes between active and inactive players) or a gapless swap.

### 2.2 Root Cause of the Infinite Skipping Loop
When a track encounters a playback error (e.g., HTTP 403 Forbidden due to an expired/blocked CDN URL):
1. VLC fires `MediaPlayerEncounteredError`, which triggers `_on_vlc_error()`.
2. `_on_vlc_error()` calls `self.stop()`.
3. In LibVLC, stopping a player or failing to load media triggers the `MediaPlayerEndReached` event.
4. `_on_end_reached()` captures this event and immediately runs `_advance()`.
5. `_advance()` fetches the next track in the queue and starts playing it via `play_track()`.
6. If the next track also fails (due to the same underlying network issue, general block, or expired URLs in a playlist), it triggers the error event and then `MediaPlayerEndReached` again.
7. This loops indefinitely across the entire queue. If repeat modes are on (especially `repeat = "one"`), it tries the same failing track repeatedly at maximum speed, creating a tight CPU-intensive loop, hammering API endpoints, and risking temporary or permanent IP bans.

---

## 3. Stream Retrieval Analysis

### 3.1 YouTube Music (`services/youtube_service.py`)
- **Library**: `yt-dlp` (via Python library wrapper) and `ytmusicapi` for search.
- **Search**: `self._ytmusic.search(query, filter='songs')`.
- **Extraction**: `get_stream_url(video_url)` uses `yt_dlp.YoutubeDL`.
  - Configures format depending on settings (`bestaudio/best`, etc.).
  - Extracts direct URL using `ydl.extract_info(video_url, download=False)`.
  - Resolves to a signed Google Video CDN URL (`https://*.googlevideo.com/videoplayback?...`).
  - Supports loading cookie files (`cookiefile`) or extracting cookies from local browsers (`cookiesfrombrowser`).

### 3.2 SoundCloud (`services/soundcloud_service.py`)
- **Library**: `yt-dlp`.
- **Search**: Uses `yt-dlp` flat extractor with query prefix `scsearch{limit}:{query}`.
- **Extraction**: `get_stream_url(track_url)` extracts the direct audio URL using `ydl.extract_info` with format `bestaudio[protocol^=http]/bestaudio/best`.
  - Resolves to either progressive HTTP stream URLs or HLS `.m3u8` playlist links.

### 3.3 Yandex Music (`services/yandex_service.py`)
- **Library**: `yandex-music` Python library (wrapper around Yandex Music API).
- **Authentication**: Initializes `Client` with a user's Yandex OAuth token if configured; falls back to anonymous client.
- **Extraction**: `get_stream_url(track_id)` fetches track info using `client.tracks([track_id])`.
  - Calls `track.get_download_info(get_direct_links=True)`.
  - Iterates to find the highest-bitrate MP3 stream.
  - The stream URL is a direct Yandex Storage CDN URL (`https://storage.mds.yandex.net/get-mp3/...`).

---

## 4. Cookie and Header Requirements

### 4.1 YouTube
- **User-Agent**: **Crucial.** Must match the User-Agent that extracted the URL. Otherwise, YouTube CDN returns HTTP 403 Forbidden.
- **Cookies**: Required for age-restricted/restricted tracks, or to bypass bot verification checks. The request must include cookies (like `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `__Secure-3PAPISID`, `__Secure-3PSID`, etc.) linked to the IP address.
- **IP Binding**: YouTube stream links are bound to the client IP address. Passing links between different network interfaces or servers will fail.

### 4.2 SoundCloud
- **User-Agent**: Standard desktop browser header.
- **Cookies / OAuth**: Restrictive tracks require `Authorization: OAuth <token>` or client ID query parameters.

### 4.3 Yandex Music
- **User-Agent**: Standard user agent or Yandex Music mobile client user agent.
- **Auth Headers**: Accessing non-public/subscription tracks requires Yandex auth token headers (`Authorization: OAuth <token>`) or session cookies (`Session_id`).
- **Expiration**: Yandex CDN links expire in ~2 hours. Cached URLs must be refreshed.

---

## 5. Proposed Solution: Lightweight Local HTTP Proxy

### 5.1 Architecture Overview
Since NeDotify does not bundle heavy frameworks (like Flask or FastAPI) and depends only on standard Python libraries, we can implement a local HTTP proxy server using Python's built-in `http.server` module.
The proxy server will run in a background thread and handle HTTP Range requests from VLC, injecting the necessary user-agent, cookies, and tokens dynamically.

### 5.2 Stream Proxy Code Design
Here is a complete, ready-to-integrate implementation sketch for a threading-based HTTP proxy:

```python
import urllib.parse
import urllib.request
import http.server
import socketserver
import threading
import logging

logger = logging.getLogger(__name__)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Threading HTTP Server.
    Uses ThreadingMixIn to support concurrent stream requests (crucial for crossfading/preloading).
    """
    def __init__(self, server_address, RequestHandlerClass, app_core):
        super().__init__(server_address, RequestHandlerClass)
        self.app_core = app_core

class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP requests in main logs
        logger.debug(format % args)

    def do_GET(self):
        # Parse target query parameters
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        
        target_url = query.get('url', [None])[0]
        source = query.get('source', [None])[0]
        source_id = query.get('source_id', [None])[0]
        
        if not target_url:
            self.send_error(400, "Missing target URL ('url')")
            return

        # Prepare request to the actual streaming CDN
        req = urllib.request.Request(target_url)
        
        # Support HTTP Range requests (Critical for VLC seeking and buffering)
        range_header = self.headers.get('Range')
        if range_header:
            req.add_header('Range', range_header)
            
        # Set standard browser user-agent
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # Inject authentication and cookies based on source
        if source == 'youtube':
            try:
                # Access the yt-dlp cookiejar
                ydl = self.server.app_core.youtube._get_ydl('high')
                if ydl and ydl.cookiejar:
                    ydl.cookiejar.add_cookie_header(req)
            except Exception as e:
                logger.warning(f"Error appending YouTube cookies: {e}")
                
        elif source == 'soundcloud':
            try:
                ydl = self.server.app_core.soundcloud._get_ydl()
                if ydl and ydl.cookiejar:
                    ydl.cookiejar.add_cookie_header(req)
            except Exception as e:
                logger.warning(f"Error appending SoundCloud cookies: {e}")
                
        elif source == 'yandex':
            try:
                token = self.server.app_core.settings.get("auth", "yandex_token", "")
                if token:
                    req.add_header('Authorization', f'OAuth {token}')
            except Exception as e:
                logger.warning(f"Error appending Yandex headers: {e}")

        # Pipe remote stream to VLC client
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                # Send corresponding status and headers back to VLC
                self.send_response(response.status)
                for header, value in response.getheaders():
                    # Strip hop-by-hop headers to prevent proxy conflicts
                    if header.lower() not in (
                        'connection', 'keep-alive', 'proxy-authenticate', 
                        'proxy-authorization', 'te', 'trailer', 
                        'transfer-encoding', 'upgrade'
                    ):
                        self.send_header(header, value)
                self.end_headers()
                
                # Stream the chunks
                chunk_size = 64 * 1024  # 64 KB
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    
        except urllib.error.HTTPError as he:
            logger.error(f"Proxy CDN request failed with code {he.code}")
            
            # Dynamic Self-Healing Re-resolution:
            # If the CDN returns 403 or 410 (link expired), request a fresh link
            # from the core and retry the connection seamlessly.
            if he.code in (403, 410) and source_id:
                logger.info(f"Triggering dynamic re-resolution for {source} track {source_id}")
                try:
                    new_url = self.server.app_core.re_resolve_stream_url(source, source_id)
                    if new_url:
                        # Retry the request with the new URL
                        req_retry = urllib.request.Request(new_url)
                        if range_header:
                            req_retry.add_header('Range', range_header)
                        req_retry.add_header('User-Agent', 'Mozilla/5.0 ...')
                        # (Re-inject cookies...)
                        with urllib.request.urlopen(req_retry, timeout=15) as resp_retry:
                            self.send_response(resp_retry.status)
                            for h, v in resp_retry.getheaders():
                                if h.lower() not in ('connection', 'keep-alive', 'transfer-encoding'):
                                    self.send_header(h, v)
                            self.end_headers()
                            while True:
                                chunk = resp_retry.read(chunk_size)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                            return
                except Exception as ex:
                    logger.error(f"Self-healing re-resolution failed: {ex}")
            
            # If not healed, return the HTTP error code to VLC
            try:
                self.send_error(he.code, str(he))
            except:
                pass
        except Exception as e:
            logger.error(f"Proxy streaming failed: {e}")
            # Gracefully handle socket closures (e.g. user skips track)
            try:
                self.send_error(500, str(e))
            except:
                pass

class LocalProxyManager:
    """Manages lifecycle of the local stream proxy."""
    def __init__(self, app_core):
        self.app_core = app_core
        self.server = None
        self.port = None
        self.thread = None

    def start(self):
        # Auto-allocates an open port from the OS using port=0
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), StreamProxyHandler, self.app_core)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Local stream proxy running on http://127.0.0.1:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Local stream proxy stopped.")

    def get_proxy_url(self, source, source_id, original_url):
        escaped_url = urllib.parse.quote_plus(original_url)
        return f"http://127.0.0.1:{self.port}/stream?source={source}&source_id={source_id}&url={escaped_url}"
```

---

## 6. Recommendations & Implementation Plan

### Recommendation 1: Fix the Infinite Skipping Loop in `audio/engine.py`
Add failure tracking to the playback queue.
- **Implement a counter** `self._consecutive_failures` inside `AudioEngine`.
- **Reset on Successful Playback**: Clear the counter to 0 inside `_poll_loop` when the position exceeds 1000ms.
- **Handle VLC Playback Errors**: In `_on_vlc_error()`, increment the counter and set a flag `self._playback_failed = True`.
- **Modify Advancement Logic**: In `_on_end_reached()`, check the counter. If `self._consecutive_failures >= 3`, log the error, reset the counter, fire the error notification via `_on_error`, and call `self.stop()` without calling `_advance()`.

### Recommendation 2: Wire the `LocalProxyManager` into `AppCore`
- Instantiate `LocalProxyManager` inside `AppCore.__init__()` (`core/app.py`) and call `.start()`.
- Add cleanup call `.stop()` inside `AppCore.cleanup()`.
- Expose a helper method `re_resolve_stream_url(source, source_id)` in `AppCore` that performs a synchronous lookup to fetch a fresh stream URL.

### Recommendation 3: Intercept Playback URLs in `AudioEngine.play_track()`
- Inside `play_track(track)`, check if the `source` is a cloud track (`youtube`, `soundcloud`, `yandex`).
- If yes, wrap the resolved `file_path` URL with `self.proxy.get_proxy_url(source, source_id, file_path)`.
- Pass this proxy URL directly to `self._instance.media_new()`.
- This ensures VLC streams from the local proxy, and the proxy injects headers/cookies and performs self-healing.
