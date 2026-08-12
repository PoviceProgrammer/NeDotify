# Handoff Report — Feature 3: Stream TTL & Auto Re-resolution Investigation

## 1. Observation

### 1.1 Summary of Investigated Files
- `core/database.py`: `DatabaseManager.get_cached_stream`, `DatabaseManager.cache_stream`, and SQLite `stream_cache` table schema.
- `core/proxy.py`: `StreamProxyHandler._find_playable_url`, `StreamProxyHandler._resolve_stream_url`, and `StreamProxyHandler._proxy_stream`.
- `core/app.py`: `AppCore.re_resolve_stream_url_async`.

---

### 1.2 Verbatim Code Inspections

#### Observation 1: Stream Cache Schema & 24-Hour Default TTL in `core/database.py`
In `core/database.py`, lines 140–156 and lines 737–771:

```python
140: cursor.execute(
141:     """
142:     CREATE TABLE IF NOT EXISTS stream_cache (
143:         id INTEGER PRIMARY KEY AUTOINCREMENT,
144:         source TEXT NOT NULL,
145:         source_id TEXT NOT NULL,
146:         stream_url TEXT,
147:         cached_file_path TEXT,
148:         title TEXT,
149:         artist TEXT,
150:         cover_url TEXT,
151:         duration REAL,
152:         metadata_json TEXT,
153:         cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
154:         expires_at TIMESTAMP,
155:         UNIQUE(source, source_id)
156:     )
157: """
158: )

...

737: def get_cached_stream(self, source: str, source_id: str, max_age_seconds: int = 86400) -> Optional[Dict[str, Any]]:
738:     cursor = self.conn.cursor()
739:     cursor.execute(
740:         """
741:         SELECT * FROM stream_cache 
742:         WHERE source = ? AND source_id = ? 
743:         AND (strftime('%s', 'now') - strftime('%s', cached_at)) < ?
744:     """,
745:         (source, source_id, max_age_seconds),
746:     )
747:     row = cursor.fetchone()
748:     return dict(row) if row else None

750: def cache_stream(
751:     self,
752:     source: str,
753:     source_id: str,
754:     stream_url: str,
755:     title: str = "",
756:     artist: str = "",
757:     cover_url: str = "",
758:     duration: float = 0,
759:     metadata: Optional[Dict[str, Any]] = None,
760: ) -> None:
761:     cursor = self.conn.cursor()
762:     meta_json = json.dumps(metadata) if metadata else None
763:     cursor.execute(
764:         """
765:         INSERT OR REPLACE INTO stream_cache 
766:         (source, source_id, stream_url, title, artist, cover_url, duration, metadata_json, cached_at)
767:         VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
768:     """,
769:         (source, source_id, stream_url, title, artist, cover_url, duration, meta_json),
770:     )
771:     self.conn.commit()
```
**Finding**: `get_cached_stream` sets default `max_age_seconds = 86400` (24 hours). `cached_at` timestamp is set to `CURRENT_TIMESTAMP`, but `expires_at` is left `NULL`.

---

#### Observation 2: Proxy Using 24-Hour Stream Cache in `core/proxy.py`
In `core/proxy.py`, lines 124–144:

```python
124: def _find_playable_url(self, track_obj):
125:     """Return a cached playable stream URL for the track, or None."""
126:     if not track_obj:
127:         return None
128: 
129:     file_path = track_obj.get('file_path')
130:     if file_path and _is_safe_url(file_path):
131:         return file_path
132: 
133:     source = track_obj.get('source')
134:     source_id = track_obj.get('source_id')
135:     if source and source_id and self.app_core and hasattr(self.app_core, 'db'):
136:         try:
137:             cached_stream = self.app_core.db.get_cached_stream(source, source_id)
138:             if cached_stream and cached_stream.get("stream_url") and \
139:                     _is_safe_url(cached_stream["stream_url"]):
140:                 return cached_stream["stream_url"]
141:         except Exception as e:
142:             logger.error(f"Error reading cached stream in proxy: {e}")
143: 
144:     return None
```
**Finding**: `_find_playable_url` invokes `self.app_core.db.get_cached_stream(source, source_id)` without specifying `max_age_seconds`. It inherits the 24-hour default (86,400s). Because YouTube (`googlevideo.com`) signatures expire after 3–6 hours, 24-hour cached streams are returned as valid when they are actually expired upstream.

---

#### Observation 3: Synchronous 16-Second Proxy Re-resolution in `core/proxy.py`
In `core/proxy.py`, lines 146–175:

```python
146: def _resolve_stream_url(self, source, source_id, track_obj=None):
147:     """Synchronously re-resolve track stream URL via AppCore."""
148:     resolved_url = None
149:     event = threading.Event()
150: 
151:     def callback(url, meta=None):
152:         nonlocal resolved_url
153:         resolved_url = url
154:         event.set()
155: 
156:     def error_cb(err):
157:         event.set()
158: 
159:     try:
160:         if hasattr(self.app_core, 're_resolve_stream_url_async'):
161:             title = track_obj.get("title") if track_obj else None
162:             artist = track_obj.get("artist") if track_obj else None
163:             self.app_core.re_resolve_stream_url_async(
164:                 source=source,
165:                 source_id=source_id,
166:                 title=title,
167:                 artist=artist,
168:                 callback=callback,
169:                 on_error=error_cb
170:             )
171:             event.wait(timeout=16.0)
172:     except Exception as e:
173:         logger.error(f"Failed to re-resolve stream for {source}/{source_id}: {e}")
174: 
175:     return resolved_url
```
**Finding**: `_resolve_stream_url` uses `event.wait(timeout=16.0)`, blocking the HTTP proxy worker thread synchronously for up to 16 seconds.

---

#### Observation 4: Upstream HTTP 403 / 410 Handling in `core/proxy.py`
In `core/proxy.py`, lines 177–228:

```python
177: def _proxy_stream(self, stream_url, source=None, source_id=None, track_id=None):
178:     """Fetch and pipe upstream audio stream back to client with range support and retry logic."""
...
189:     with urllib.request.urlopen(req, timeout=15) as resp:
...
207: except urllib.error.HTTPError as e:
208:     logger.warning(f"Upstream HTTPError {e.code} for {stream_url}")
209:     if e.code in (401, 403, 404, 410) and source and source_id:
210:         # Attempt self-healing re-resolution once
211:         retry_track = None
212:         if track_id and self.app_core and hasattr(self.app_core, 'db'):
213:             try:
214:                 retry_track = self.app_core.db.get_track(int(track_id))
215:             except Exception:
216:                 pass
217:         new_url = self._resolve_stream_url(source, source_id, retry_track)
218:         if new_url and new_url != stream_url:
219:             self._proxy_stream(new_url, source, source_id, track_id)
220:             return
221:     self.send_error(e.code, f"Upstream HTTP Error {e.code}")
```
**Finding**: When `urllib.request.urlopen` returns HTTP 403 or 410, `_proxy_stream` calls `_resolve_stream_url`. The proxy thread blocks for up to 16.0s. Meanwhile:
1. pywebview HTML5 `<audio>` element times out after ~5–8 seconds without response headers, triggering frontend error handlers.
2. The frontend increments error counts and drops playback.
3. When `_proxy_stream` eventually finishes re-resolution after 10+ seconds and attempts to write to `self.wfile`, the client socket has already been closed by pywebview, resulting in `WinError 10053` (`ConnectionResetError`).
4. The invalid stream URL is NOT deleted from `stream_cache` upon 403/410 failure, leaving bad records in SQLite.

---

#### Observation 5: Re-Resolution Bridge Logic in `core/app.py`
In `core/app.py`, lines 116–214:

```python
116: def re_resolve_stream_url_async(self, source, source_id, callback=None, on_error=None, quality="high", title=None, artist=None):
117:     """Construct lookup URL, call get_stream_url asynchronously and trigger callbacks."""
118:     def worker():
...
139:         def _on_resolved(stream_url, metadata=None):
140:             if stream_url:
141:                 try:
142:                     self.db.cache_stream(source, source_id, stream_url)
143:                 except Exception:
144:                     pass
...
155:             if callback:
156:                 callback(stream_url, metadata or {"source": source, "source_id": source_id})
```
**Finding**: `re_resolve_stream_url_async` runs `yt-dlp` on a background daemon thread. When extraction succeeds, it updates the database via `self.db.cache_stream(source, source_id, stream_url)` and invokes `callback(stream_url, metadata)`.

---

## 2. Logic Chain

1. **Premise 1 (Cache Expiration Discrepancy)**: YouTube CDN streams (`googlevideo.com`) use expiring authentication parameters (`expire=...`), valid for 3 to 6 hours. SoundCloud CDN links similarly expire within hours.
2. **Premise 2 (Database Default Over-Retention)**: `DatabaseManager.get_cached_stream` defaults to `max_age_seconds = 86400` (24 hours). `_find_playable_url` in `proxy.py` relies on this default. Thus, stream URLs that are 10–20 hours old are served to pywebview HTML5 `<audio>` elements.
3. **Premise 3 (Upstream 403/410 Error)**: When the proxy sends HTTP GET to an expired URL, upstream YouTube/SoundCloud servers return HTTP 403 Forbidden or 410 Gone.
4. **Premise 4 (16-Second Proxy Thread Block)**: In response to HTTP 403/410, `_proxy_stream` triggers `_resolve_stream_url`, which blocks the proxy handler thread for up to 16 seconds via `event.wait(timeout=16.0)`.
5. **Premise 5 (Frontend HTML5 Audio Timeout)**: pywebview / Chromium HTML5 `<audio>` element times out if no HTTP response headers are received within 5 to 8 seconds. This triggers `handleAudioElementError` in `player.js`, causing UI state failure and incrementing `consecutivePlaybackErrors`.
6. **Premise 6 (Socket Reset / WinError 10053)**: Because pywebview aborted the HTTP request due to timeout, the TCP socket is closed. When `_proxy_stream` finally completes re-resolution and calls `self.wfile.write(chunk)`, Python throws `ConnectionResetError: [WinError 10053]`.

---

## 3. Caveats

- **Network Speeds & `yt-dlp` Latency**: `yt-dlp` resolution time depends on network speed and whether YouTube DPI bypass (`ZapretService`) is active. Under high latency, `yt-dlp` extraction can take 2.5–5 seconds.
- **No DRM Bypass**: DRM-protected tracks (e.g. certain SoundCloud/Spotify tracks) cannot be resolved by `yt-dlp`. `AppCore.re_resolve_stream_url_async` already includes YouTube fallback search when `title`/`artist` are available.

---

## 4. Conclusion

Stream playback failures and pywebview audio timeouts caused by Feature 3 stem from:
1. Excessive 24-hour stream cache TTL in `core/database.py` and `core/proxy.py`.
2. Stale cache retention in SQLite (`stream_cache` table) after HTTP 403/410 upstream failures.
3. Long 16-second synchronous blocking during stream re-resolution in `core/proxy.py`, exceeding HTML5 `<audio>` element timeout limits.

---

## 5. Verification Method

1. **Unit Test Verification**:
   Run `pytest tests/test_proxy.py` or execute manual proxy test script:
   ```powershell
   python run_tests.py
   ```
2. **Stream TTL Reduction Inspection**:
   Inspect `core/database.py` (`get_cached_stream`) and `core/proxy.py` (`_find_playable_url`). Confirm maximum cache age is capped at 10800 seconds (3 hours).
3. **403/410 Invalidation Inspection**:
   Inspect `core/proxy.py` (`_proxy_stream`). Confirm expired entries are deleted from `stream_cache` upon 403/410 status codes.
4. **Fast Re-resolution Timeout Inspection**:
   Inspect `core/proxy.py` (`_resolve_stream_url`). Confirm `event.wait(timeout=...)` is reduced to `<= 3.5` seconds.

---

## 6. Exact Recommendations for Implementation

### Recommendation 3.1: Reduce Stream Cache TTL to 3 Hours (10800 Seconds)
1. In `core/database.py` (`get_cached_stream`, line 737):
   Change default `max_age_seconds` parameter from `86400` to `10800`:
   ```python
   def get_cached_stream(self, source: str, source_id: str, max_age_seconds: int = 10800) -> Optional[Dict[str, Any]]:
   ```
2. In `core/proxy.py` (`_find_playable_url`, line 137):
   Explicitly pass `max_age_seconds=10800`:
   ```python
   cached_stream = self.app_core.db.get_cached_stream(source, source_id, max_age_seconds=10800)
   ```

### Recommendation 3.2: Immediate Cache Purge on Upstream 403/410 Errors
In `core/proxy.py` (`_proxy_stream`, lines 207–221):
When upstream returns 403/410, immediately delete the invalid entry from `stream_cache` before attempting re-resolution:
```python
except urllib.error.HTTPError as e:
    logger.warning(f"Upstream HTTPError {e.code} for {stream_url}")
    if e.code in (401, 403, 404, 410) and source and source_id:
        # Purge stale stream from cache so it won't be reused
        if self.app_core and hasattr(self.app_core, 'db'):
            try:
                cursor = self.app_core.db.conn.cursor()
                cursor.execute("DELETE FROM stream_cache WHERE source = ? AND source_id = ?", (source, source_id))
                self.app_core.db.conn.commit()
            except Exception as db_err:
                logger.debug(f"Failed to purge stale stream cache: {db_err}")
```

### Recommendation 3.3: Fast Inline Re-resolution Timeout (3.5 Seconds Max)
In `core/proxy.py` (`_resolve_stream_url`, line 171):
Reduce `event.wait(timeout=16.0)` to `event.wait(timeout=3.5)` to ensure the proxy responds before pywebview HTML5 audio times out (5–8s):
```python
event.wait(timeout=3.5)
```

### Recommendation 3.4: Non-Blocking Fallback & Event Notification
If inline re-resolution exceeds 3.5 seconds:
1. Return `HTTP 503 Service Unavailable` with `Retry-After: 1` header instead of stalling the thread indefinitely.
2. In `core/app.py` (`re_resolve_stream_url_async`): When background re-resolution completes, emit a JS event `stream_refreshed` (`{"source": source, "source_id": source_id, "track_id": track_id}`).
3. In `ui/web_new/js/player.js`: Listen for `stream_refreshed` event; if it matches the active track, update `audio.src` and resume playback seamlessly.
