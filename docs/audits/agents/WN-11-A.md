## AREA WN-11 — Loopback HTTP stream proxy — ROLE A

### 1. Scope reviewed

**Files opened (physical 1-based line ranges actually read):**

- `core/proxy.py` — **read in full**, L1–1334. Specifically:
  - helpers L55–365: `_host_matches`, `_host_of`, `_bound_googlevideo_range`, `_host_allows_credentials`,
    `_is_loopback_origin`, `AVATAR_EXTENSIONS`/`COVER_EXTENSIONS`/`AUDIO_EXTENSIONS`, `_avatars_root`,
    `_nedotify_root`, `_cover_roots`, `_is_inside_roots`, `_resolve_inside_roots`, `_referenced_by_library`,
    `_safe_stream_local_path`, `_safe_avatar_path`, `_safe_cover_path`, `_ext_for_response`, `_parse_byte_range`
  - `SafeRedirectHandler` L368–387, `_safe_urlopen` L390–393, `_rewrite_hls_playlist` L396–418
  - `ThreadingHTTPServer` L421–446, `StreamProxyHandler` L449–1256
    (`send_error`/`_safe_send_error`/`finish`/`log_message`/`_authorized`/`_authenticate`/`_reject_unauthorized`/
    `_send_cors_headers`/`serve_local_file`/`_send_range_not_satisfiable`/`do_OPTIONS`/`do_HEAD`/`_send_local_head`/
    `_resolve_stream_local_file`/`do_GET`)
  - `LocalProxyManager` L1259–1334 (`start`/`stop`/`auth_query`/`get_proxy_url`)
- Callees traced into other areas (read for verification; defects there are attributed to the owning area, not re-reported here):
  - `core/api.py` L74–196 (`_COVER_MIME_BY_EXT`, `_is_ssrf_safe_url`, SSRF cache), L1095–1124 (`open_url`),
    L1195–1241 (`_on_track_changed` → `proxy.get_proxy_url`), L1398–1405 (`get_proxy_info` → port+token to JS),
    L2040–2075 (`get_next_track` → builds `/api/stream?...&k=`), L2362–2366
  - `core/database.py` L1166–1180 (`get_track`), L2134–2160 (`set_cached_file`, `get_cached_stream`),
    L2162–2198 (`cache_stream`), L2413–2489 (`close_thread_connection`, `close`)
  - `core/app.py` L120–179 (proxy construction/`start`), L345–369 (`cache_stream` with the **raw** upstream URL),
    L520–586 (`cleanup()` → `proxy.stop`)
  - `core/playback_recovery.py` L160–183 (`proxy.get_proxy_url(...)` → token-bearing URL to the frontend)
  - `audio/engine.py` L80–139 (proxy URL construction), L305–330 (`cache_stream` with the raw upstream URL)
  - `ui/web_new_v2/js/player.js` L97–145 (`normalizeAudioSourceUrl` → `/api/stream?url=…&k=…`, `crossOrigin="anonymous"`,
    `loadAudioSource`), `ui/web_new_v2/js/utils.js` L620–635 (`/api/cover?path=…&k=…`),
    `ui/web_new_v2/js/profile.js` L125–127 (`/api/avatar?path=…&k=…`), `ui/web_new_v2/js/main.js` L30–56 (`get_proxy_info`)
  - `main.py` L348–350, L555 (`webview.start(http_server=True)` → the UI origin is `http://127.0.0.1:<port>`)
  - Test harness / existing tests read for ground truth: `tests/test_proxy_harness.py` (L1–215),
    `tests/test_proxy_ranges.py` (L1–184), `tests/test_proxy_security.py` (L1–204),
    `tests/test_hls_playback.py` (L1–162), `tests/test_offline_proxy.py` (L1–27), `tests/conftest.py` (L1–176)
- **Empirical probes** (scratch scripts written to `%TEMP%\opencode\`, nothing in the repo was modified):
  `wn11_probe.py`, `wn11_probe2.py`, `wn11_probe3.py`, `wn11_probe4.py`, `wn11_probe5.py`, `wn11_probe6.py`,
  `wn11_lower.py`. They drove the **real** `ThreadingHTTPServer`/`StreamProxyHandler` over a loopback socket with a
  throwaway SQLite DB and a redirected `~` (no `~/.nedotify` touched, no real network).

### 2. Findings

#### F-WN-11-1  [P2] — A non-ASCII `k=` token raises an unhandled `TypeError`, killing the request with no HTTP response

- **File:** `core/proxy.py:511` (also `core/proxy.py:515`, `core/proxy.py:698`, `core/proxy.py:634`)
- **Confirmed:** yes
- **Description:** `_authorized()` compares the supplied token with `hmac.compare_digest(str(supplied), str(expected))`.
  `hmac.compare_digest` refuses non-ASCII `str` operands and raises `TypeError`. The exception escapes `_authorized`
  → `_authenticate` → `do_GET`/`do_HEAD`, so the request handler dies with an unhandled exception instead of
  answering 403.
- **Cause:** the token is a `str` taken straight from `urllib.parse.parse_qs`, and `parse_qs` decodes percent-escapes
  to arbitrary Unicode (including U+FFFD for invalid UTF-8). `compare_digest` only accepts ASCII `str`.
- **Trigger conditions:** any request carrying a non-ASCII `k` (or legacy `auth_token`) parameter, e.g.
  `GET /api/cover?path=x.jpg&k=%C3%A9` or `k=%FF`. This is **pre-authentication**, so no token is needed.
- **User impact:** the client gets a dropped connection (`http.client.RemoteDisconnected`) instead of a clean 403, and
  `socketserver` prints a full traceback to stderr for every such request. Any local process can spam the console/log.
- **Evidence:**
  ```python
  # core/proxy.py:503-511
  expected = getattr(self.server, 'auth_token', '') or ''
  ...
  supplied = (query_params.get(AUTH_PARAM) or [''])[0]
  if not supplied:
      supplied = (query_params.get('auth_token') or [''])[0]
  return hmac.compare_digest(str(supplied), str(expected))
  ```
  Probe output:
  ```
  === A. non-ASCII token ===
  EXCEPTION from client: RemoteDisconnected Remote end closed connection without response
  ...
    File "...\core\proxy.py", line 511, in _authorized
      return hmac.compare_digest(str(supplied), str(expected))
  TypeError: comparing strings with non-ASCII characters is not supported
  ```
  (identical result for `k=%FF`).
- **Reproduction / verification:** start the real proxy (`ThreadingHTTPServer(('127.0.0.1', 0), StreamProxyHandler,
  app_core, token)`) and issue `GET /api/cover?path=x.jpg&k=%C3%A9` → `RemoteDisconnected` + the traceback above.
  A regression test would assert `resp.status == 403` for `k=%C3%A9`.
- **Suggested fix:** compare bytes, e.g. `hmac.compare_digest(supplied.encode('utf-8', 'surrogatepass'),
  expected.encode('utf-8'))`, or short-circuit non-ASCII input to `False` before comparing.
- **Fix side effects:** `str.encode` can itself raise on lone surrogates; use `surrogatepass`/`latin-1` carefully.
  Constant-time comparison must be preserved (it is a bearer token).
- **Discovered by:** A

---

#### F-WN-11-2  [P2] — The `'/'` endpoint has no offline gate: offline mode still performs the upstream fetch and then truncates the body

- **File:** `core/proxy.py:863-968` (the `'/'` branch), contrast `core/proxy.py:814-816`
- **Confirmed:** yes
- **Description:** Only the `/api/stream` branch checks `is_offline()` *before* contacting the network. The `'/'`
  branch has no such check; the only offline test there lives **inside the body loops** (L1195, L1229), where
  `raise ConnectionAbortedError('Offline mode enabled')` aborts the transfer *after* the response headers (including
  the upstream's `Content-Length`) have already been sent.
- **Cause:** the offline guard was placed inside one branch instead of on the shared remote path.
- **Trigger conditions:** offline mode enabled + any request to `'/?url=https://…'` (the endpoint used for
  non-YouTube/SoundCloud hosts, for VK/Yandex CDN URLs and for **every rewritten HLS segment**).
- **User impact:** (a) the app still makes the outbound request in offline mode; (b) the client receives
  `200` + `Content-Length: N` but **zero** body bytes → `IncompleteRead` / `ERR_CONTENT_LENGTH_MISMATCH` in the
  browser instead of the clean `503` that `/api/stream` returns.
- **Evidence:**
  ```python
  # core/proxy.py:814-816 (ONLY in the /api/stream branch)
  if is_offline(getattr(self.server.app_core, 'settings', None)):
      self._safe_send_error(503, 'Offline mode: track is not saved locally')
      return None
  ```
  ```python
  # core/proxy.py:1193-1199 / 1228-1231 (inside the body loop, headers already sent)
  with open(temp_path, 'wb') as tmp:
      while True:
          if is_offline(getattr(self.server.app_core, 'settings', None)):
              raise ConnectionAbortedError('Offline mode enabled')
  ```
  Probe output:
  ```
  === 1. OFFLINE: '/' branch has no offline gate ===
  offline GET /?url=https://cdn.example/audio.mp3 -> 200 body: b'INCOMPLETE:IncompleteRead(0 bytes read, 1000 more expected)'
  upstream fetches performed: 1 ['https://cdn.example/audio.mp3']
  offline GET /api/stream?source=youtube -> 503
  ```
- **Reproduction / verification:** set `settings['network']['offline_mode'] = True`, then
  `GET /?url=<https url>&k=<token>` → the upstream is fetched and the response is truncated with a 200 status;
  `GET /api/stream?source=youtube&source_id=x&k=<token>` → 503. The existing test
  `tests/test_offline_proxy.py:6-13` only covers `/api/stream`, which is why the gap is invisible.
- **Suggested fix:** hoist the offline check to the top of `do_GET` (after the local-file branches, before any
  upstream resolution/fetch) and answer `503` for every remote path, including `'/'` and the HLS segment URLs.
- **Fix side effects:** the local-file endpoints (`/api/cover`, `/api/avatar`, the local part of `/api/stream`) must
  keep working offline, so the gate must be placed only on the remote path; the HLS manifest branch must also be
  gated or it will keep fetching manifests offline.
- **Discovered by:** A

---

#### F-WN-11-3  [P2] — `_resolve_inside_roots` does not refuse UNC paths before the filesystem call: a crafted `path=` blocks the request thread for ~21 s in an SMB connect attempt

- **File:** `core/proxy.py:183-206` (the `realpath` call is L201), reached via `core/proxy.py:275-282`;
  contrast the explicit UNC guard in `core/proxy.py:253-255`
- **Confirmed:** yes (measured 20.93 s against a TEST-NET address `192.0.2.55`)
- **Description:** `_resolve_inside_roots()` canonicalises the candidate with `os.path.realpath(candidate)`. On
  Windows `realpath` resolves a path with `GetFinalPathNameByHandle`, which **opens** the path — for a UNC path that
  is an SMB connection to the remote host. `_safe_stream_local_path()` explicitly refuses UNC/`file://host/` paths
  for exactly this reason; `_resolve_inside_roots()` (used by `/api/cover` and `/api/avatar`) does not.
- **Cause:** the UNC/`file:` pre-filter exists only in `_safe_stream_local_path`; the sibling resolver was not given it.
- **Trigger conditions:** `GET /api/cover?path=\\host\share\x.jpg&k=<token>` (also `/api/avatar`). The path is
  eventually refused (404), so no file content leaks.
- **User impact:** every such request pins a proxy thread for the whole SMB/TCP connect timeout (measured **20.93 s**;
  a black-holed host can hold it for the full TCP SYN retry budget). With thread-per-request and no socket timeout
  (see F-WN-11-7) this is a cheap local thread-exhaustion lever. The attempt also makes an outbound SMB connection
  and answers the server's NTLM challenge, which is why `_safe_stream_local_path` was hardened — the cover/avatar
  path was left behind.
- **Evidence:**
  ```python
  # core/proxy.py:195-203  (_resolve_inside_roots - NO UNC guard)
  candidate = os.path.normpath(urllib.parse.unquote(candidate))
  ext = os.path.splitext(candidate)[1].lower()
  if ext not in extensions:
      return ''
  resolved = os.path.realpath(candidate)      # <-- opens a UNC path
  ```
  ```python
  # core/proxy.py:251-255  (_safe_stream_local_path - HAS the guard)
  if raw.startswith(('\\\\', '//')) or raw.lower().startswith('file:'):
      logger.warning('Refused /api/stream read of UNC/file-URL path: %s', raw[:120])
      return ''
  ```
  Probe output:
  ```
  === F. UNC path through /api/cover ===
  GET UNC cover -> 404 elapsed 20.93s
  ```
- **Reproduction / verification:** `GET /api/cover?path=\\192.0.2.55\share\x.jpg&k=<token>` → the response takes
  ~21 s instead of returning immediately; compare with a local path (same request returns in ms).
- **Suggested fix:** apply the same `raw.startswith(('\\\\', '//')) or raw.lower().startswith('file:')` pre-filter to
  `_resolve_inside_roots` (and reject `file://host/` forms) before any `realpath`/`isfile` call.
- **Fix side effects:** none — legitimate cover/avatar paths are never UNC. (Role B should separately confirm the
  NTLM-credential aspect; I report only the blocking/consistency defect here to avoid double-reporting.)
- **Discovered by:** A

---

#### F-WN-11-4  [P2] — `do_HEAD` answers 404 for resources that `GET` serves (`file://` URLs and DB-cached streams)

- **File:** `core/proxy.py:622-652` (esp. L649-651), `core/proxy.py:684-692`; contrast `core/proxy.py:744-747`
  (the `file://` stripping in `do_GET`) and `core/proxy.py:796-812` (the DB + on-disk cache in `do_GET`)
- **Confirmed:** yes
- **Description:** `do_HEAD` resolves the target with `_resolve_stream_local_file(url or file_path)` only. It never
  (a) strips the `file://` scheme from the `url` parameter and (b) never consults the `stream_cache` DB row or the
  on-disk stream cache that `do_GET` uses. So for two very common request shapes HEAD and GET disagree.
- **Cause:** `do_HEAD` re-implements a much smaller resolution order than `do_GET` instead of sharing it.
- **Trigger conditions:**
  1. `url=file:///C:/…/song.mp3` — `player.js:98-100` builds exactly this URL for a `file://` source;
  2. `track_id=…&source=…&source_id=…` where the stream is already in the DB/on-disk cache.
- **User impact:** HEAD/GET are not equivalent (RFC 9110 §9.3.2). A client that probes with HEAD gets a false
  "not found" for a track that plays fine, and the frontend's `file://` path is broken for any HEAD-based probe.
- **Evidence:**
  ```python
  # core/proxy.py:648-651
  # '/' and /api/stream: same local-file gate GET applies.
  self._send_local_head(self._resolve_stream_local_file(
      query_params.get('url', [''])[0] or query_params.get('file_path', [''])[0] or ''
  ))
  ```
  ```python
  # core/proxy.py:744-747  (do_GET strips the scheme BEFORE the gate)
  if local_path.startswith('file:///'):
      local_path = urllib.request.url2pathname(local_path[7:])
  elif local_path.startswith('file://'):
      local_path = urllib.request.url2pathname(local_path[6:])
  ```
  Probe output:
  ```
  GET  /api/stream?url=file://... -> 200 len 2051 ct audio/mpeg
  HEAD /api/stream?url=file://... -> 404 cl 466 ct text/html;charset=utf-8
  GET  /api/stream?url=<raw path> -> 200 len 2051
  HEAD /api/stream?url=<raw path> -> 200 cl 2051
  GET  /api/stream?track_id=..&source_id=vid1 -> 200 len 2051
  HEAD /api/stream?track_id=..&source_id=vid1 -> 404 cl 466
  ```
- **Reproduction / verification:** as printed above — one GET and one HEAD of the same URL.
- **Suggested fix:** factor the "resolve a local/cached file for `url`/`file_path`/`track_id`" logic into one helper
  used by both `do_GET` and `do_HEAD` (scheme stripping + DB cache + on-disk cache), keeping the deliberate rule that
  a HEAD must not trigger an upstream fetch.
- **Fix side effects:** HEAD on `/api/stream?track_id=…` would start answering 200/206 from the cache — that is the
  intended RFC behaviour, but it means HEAD now touches the DB cache row.
- **Discovered by:** A

---

#### F-WN-11-5  [P2] — Rewritten HLS segment URLs go through `'/'`, whose `is_webpage` check resolves them as tracks instead of fetching the segment

- **File:** `core/proxy.py:396-418` (`_rewrite_hls_playlist`, the emitted URL at L406-408);
  `core/proxy.py:904` (`is_webpage`); `core/proxy.py:917-925`
- **Confirmed:** yes
- **Description:** `_rewrite_hls_playlist` rewrites every segment/key URL to `'/?url=<absolute>&source=…&k=…'`.
  The `'/'` branch then computes
  `is_webpage = target_url and _host_matches(_host_of(target_url), ('soundcloud.com', 'youtube.com', 'youtu.be'))`
  and, when that is true, **replaces** the URL with `engine.resolve_stream_url(track_info)` instead of fetching it.
  A segment hosted on one of those hosts is therefore never fetched — the proxy asks the resolver to "resolve" a
  media segment as if it were a track page.
- **Cause:** the rewrite reuses the generic proxying endpoint, whose `?url=` semantics are ambiguous
  ("page URL to resolve" vs "exact media URL to fetch").
- **Trigger conditions:** an HLS manifest (master or media) whose segment/variant URL is on `soundcloud.com`,
  `youtube.com` or `youtu.be`.
- **User impact:** HLS playback of such manifests plays the wrong content or fails. It also re-creates exactly the
  hazard the code documents at L33-40: "the catch-all branch … falls back to `engine.resolve_stream_url()` with
  whatever metadata the query carried, and for an empty query that means `source='soundcloud'` with an empty target —
  a real SoundCloud request that blocks the request thread on `event.wait(15)`".
- **Evidence:**
  ```python
  # core/proxy.py:904
  is_webpage = target_url and _host_matches(_host_of(target_url), ('soundcloud.com', 'youtube.com', 'youtu.be'))
  ...
  # core/proxy.py:917-925
  if not target_url or is_webpage:
      track_info = {'source': source if source else 'soundcloud', 'source_id': source_id, ...}
      target_url = self.server.app_core.engine.resolve_stream_url(track_info)
  ```
  Probe output (manifest containing `https://soundcloud.com/segment.m4s`):
  ```
  segment GET -> 200 | engine.resolve calls: 1
    [{'source': 'soundcloud', 'source_id': None, 'source_url': 'https://soundcloud.com/segment.m4s', ...}]
  upstream fetched: ['https://cdn.sndcdn.com/playlist.m3u8', 'https://resolved.example/other.mp3']
  ```
  The segment was never fetched; the resolver's answer was.
- **Reproduction / verification:** serve a manifest whose segment line is `https://soundcloud.com/segment.m4s`
  through `_rewrite_hls_playlist`, then GET the rewritten line against the real proxy with a recording engine.
- **Suggested fix:** mark the rewritten resource URLs distinctly (a dedicated path or an explicit
  `direct=1`/`kind=media` flag) so the `'/'` branch fetches them verbatim instead of resolving them, while keeping
  the pre-HLS behaviour for a `?url=` that points at a provider *page*.
- **Fix side effects:** the `?url=<provider page>` resolution path must keep working, so the discriminator has to be
  additive, not a change of the existing heuristic.
- **Discovered by:** A

---

#### F-WN-11-6  [P2] — `serve_local_file` announces a `Content-Length` taken from a different `stat()` than the bytes written, so a vanishing/shrinking file yields a truncated 200

- **File:** `core/proxy.py:538-597` (L540 `getsize`, L558 `Content-Length`, L561-567 the 200 branch,
  L569-590 the 206 branch); the guard for the same race exists only for the `getsize` call
- **Confirmed:** yes
- **Description:** `serve_local_file` stats the file, announces `Content-Length: file_size`, and only then opens it.
  If the file changes size — or disappears — between the two, the response body no longer matches the announced
  length: the client receives a truncated (or short) body under a 200/206 status. The code even documents the race
  ("the file can still vanish in between (scanner, user, cache eviction)") but only guards the `getsize` call, not
  the `open()`.
- **Cause:** the length is taken before the file handle exists and is never reconciled with the bytes actually sent.
- **Trigger conditions:** the stream-cache file is replaced while it plays (the proxy's own writer uses
  `os.replace`, the downloader rewrites `~/.nedotify/downloads/…`), the cache is evicted, or the user edits the file.
- **User impact:** the media element reports a network/media error (`ERR_CONTENT_LENGTH_MISMATCH` /
  `IncompleteRead`) instead of a clean failure or a retry — a broken playback right at the moment the file changed.
- **Evidence:**
  ```python
  # core/proxy.py:540-566
  file_size = os.path.getsize(file_path)
  ...
  self.send_header('Content-Length', str(file_size))
  ...
  try:
      with open(file_path, 'rb') as f:
          import shutil
          shutil.copyfileobj(f, self.wfile)
  except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
      logger.debug("serve_local_file disconnect: %s", ce)
  ```
  Probe output (file truncated to 10 bytes right after `getsize` reported 4096):
  ```
  -> 200 Content-Length: 4096 body: b'INCOMPLETE:IncompleteRead(10 bytes read, 4086 more expected)'
  ```
- **Reproduction / verification:** as above; equivalently, delete the file between `os.path.isfile()` and `open()`
  and observe a 200 with `Content-Length: N` and an empty body (the `open` error is swallowed by the `OSError`
  branch and logged as "disconnect").
- **Suggested fix:** open the file first, `f.seek(0, 2)`/`os.fstat` the open handle to get the authoritative length,
  announce that, and copy exactly that many bytes (or clamp the copy to the announced length).
- **Fix side effects:** none; the announced length becomes the size of the open handle, which is the size the client
  will actually receive.
- **Discovered by:** A

---

#### F-WN-11-7  [P2] — No socket timeout and no thread cap: an idle or slow client pins a request thread forever

- **File:** `core/proxy.py:421-446` (`ThreadingHTTPServer`), `core/proxy.py:449` (`StreamProxyHandler` defines no
  `timeout` class attribute)
- **Confirmed:** yes
- **Description:** `BaseHTTPRequestHandler.timeout` is unset (it defaults to `None`), so `setup()` never calls
  `self.connection.settimeout(...)`. `handle_one_request()` therefore blocks indefinitely in
  `self.rfile.readline(65537)` waiting for a request line, and `process_request` spawns an **unbounded** thread per
  connection. `protocol_version` is the stdlib default `HTTP/1.0`, so every request opens a new connection.
- **Cause:** no timeout was configured on the handler or the socket, and `process_request` has no concurrency limit.
- **Trigger conditions:** any local process opens N TCP connections to `127.0.0.1:<port>` and sends nothing (or
  sends a partial request line). The same applies to a client that stops reading in the middle of a long stream
  write.
- **User impact:** the thread count (and its stacks) grows without limit; the proxy becomes unable to serve the app
  itself. `daemon_threads = True` keeps the interpreter from hanging on exit, but the resource leak persists for the
  lifetime of the session.
- **Evidence:**
  ```python
  # core/proxy.py:438-446
  def process_request(self, request, client_address):
      t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
      t.daemon = self.daemon_threads
      ...
      t.start()
  ```
  Probe output:
  ```
  handler timeout attr: None
  protocol_version: HTTP/1.0
  daemon_threads: True block_on_close: False
  ```
- **Reproduction / verification:** `socket.create_connection(('127.0.0.1', port))` without sending anything; watch
  `server._threads` (the proxy's own tracked list) grow by one per connection and never shrink.
- **Suggested fix:** set a `timeout` on the handler class (e.g. 30–120 s) so `setup()` arms a socket timeout, and
  put a cap on concurrently served requests (reject or queue beyond the cap).
- **Fix side effects:** the timeout must exceed the longest legitimate transfer (a long stream write is a write
  timeout, not a read timeout, so a read timeout on the request line is safe for long media responses).
- **Discovered by:** A

---

#### F-WN-11-8  [P3] — `ThreadingHTTPServer.process_request` replaces `socketserver`'s `_threads` object with a plain list, so `server_close()` always raises `AttributeError`

- **File:** `core/proxy.py:438-446` (L441-445), triggered from `core/proxy.py:1292` (`server_close()`)
- **Confirmed:** yes
- **Description:** `socketserver.ThreadingMixIn` keeps `self._threads` as a `_Threads`/`_NoThreads` object and its
  `server_close()` ends with `self._threads.join()`. The custom `process_request` assigns a **plain `list`** to
  `self._threads`, so `join()` does not exist.
- **Cause:** the override re-implements the thread bookkeeping instead of using `ThreadingMixIn`'s container.
- **Trigger conditions:** any request that has already been served (the first `process_request` call replaces the
  container).
- **User impact:** `LocalProxyManager.stop()` calls `server_close()` inside `try/except Exception` and swallows the
  `AttributeError` at DEBUG level, so the failure is invisible. The listening socket *is* closed first (the port is
  released — verified by rebinding), so there is no functional leak today; but the override breaks the stdlib
  contract, and `block_on_close = True` (or any future stdlib change) would break in a much more visible way.
- **Evidence:**
  ```python
  # core/proxy.py:441-445
  with self._threads_lock:
      if self._threads is None or not isinstance(self._threads, list):
          self._threads = []
      self._threads = [th for th in self._threads if hasattr(th, "is_alive") and th.is_alive()]
      self._threads.append(t)
  ```
  Probe output:
  ```
  server._threads type: <class 'list'>
  server_close RAISED: AttributeError 'list' object has no attribute 'join'
  listening socket fileno after close: -1
  port rebind: OK (released)
  ```
- **Reproduction / verification:** serve one request, then call `server.server_close()` → `AttributeError`;
  `LocalProxyManager.stop()` swallows it (proxy.py:1291-1294).
- **Suggested fix:** keep the stdlib container (`socketserver._Threads()`) and prune it, or keep the tracking list in a
  separate attribute and leave `self._threads` to the stdlib.
- **Fix side effects:** `_Threads.append()` does bookkeeping that the current code does not need; pruning must keep
  using `is_alive()`.
- **Discovered by:** A

---

#### F-WN-11-9  [P3] — A 206 upstream response is cached verbatim as a complete stream file when the proxy thinks the request is cacheable

- **File:** `core/proxy.py:1174` (`if is_cachable_request and status_code in (200, 206)`),
  `core/proxy.py:1187-1190` (the final path), `core/proxy.py:1204-1215` (the `os.replace` + `set_cached_file`)
- **Confirmed:** yes for the mechanism; the production trigger is a hypothesis
- **Description:** When `is_cachable_request` is true (no `Range` header, or exactly `bytes=0-`) the proxy accepts a
  `206` from the upstream as if it were the whole entity and writes the partial body to the stream cache, then points
  the `stream_cache` row at it. The upstream's `Content-Range` total is never compared with the number of bytes
  received.
- **Cause:** `status_code in (200, 206)` conflates "partial content" with "complete entity" for the caching branch.
- **Trigger conditions (hypothesis):** an upstream that answers `206` to a request that carried no `Range` header (or
  exactly `bytes=0-`). For the built-in providers the `Range` is not forwarded for non-Googlevideo hosts
  (proxy.py:860-862) and Googlevideo ranges are clamped + de-cached (proxy.py:1014-1015), so the common CDNs do not
  trigger it — but nothing in the code enforces that assumption.
- **User impact:** the track is served as a truncated stub (`200` + a few hundred bytes) until the cache expires.
- **Evidence:**
  ```python
  # core/proxy.py:1174
  if is_cachable_request and status_code in (200, 206):
  ```
  Probe output (upstream answered `206 bytes 0-99/5000`):
  ```
  first -> 206 len 100 Content-Range: bytes 0-99/5000
  db row cached_file_path: ...\.nedotify\streams\soundcloud_sid1.mp3
  cached file size: 100 (upstream entity = 5000 bytes)
  second -> 200 len 100 Content-Length: 100
  ```
- **Reproduction / verification:** make the upstream return a 206 for a Range-less request and observe the 100-byte
  cache file and the second request answering `200` with 100 bytes.
- **Suggested fix:** only cache when the upstream status is `200`, or when the `Content-Range` total equals the number
  of bytes written.
- **Fix side effects:** an upstream that returns 200 with a chunked body and no `Content-Length` would stop being
  cached — acceptable, and arguably safer.
- **Discovered by:** A

---

#### F-WN-11-10  [P3] — `_referenced_by_library`'s "case-insensitive" comparison is case-sensitive for non-ASCII paths

- **File:** `core/proxy.py:209-235` (the queries at L221-222)
- **Confirmed:** yes
- **Description:** The library-membership check uses `WHERE LOWER(file_path) = LOWER(?)`. SQLite's `LOWER()` folds
  ASCII only, so for a Cyrillic/other non-ASCII path the comparison is effectively case-**sensitive**, contradicting
  the docstring ("paths are compared case-insensitively because the stored spelling may differ from the one the
  client sent").
- **Cause:** reliance on SQLite's ASCII-only `LOWER()` for a Unicode-aware comparison.
- **Trigger conditions:** the requested path differs from the stored `file_path` only in non-ASCII letter case (a
  Russian/Cyrillic file or folder name — very likely for this app's user base).
- **User impact:** the local file is refused (`404 Local file not found`) even though it exists and is in the
  library → the track silently fails to play.
- **Evidence:**
  ```python
  # core/proxy.py:220-223
  queries = (
      'SELECT id FROM tracks WHERE LOWER(file_path) = LOWER(?) LIMIT 1',
      'SELECT id FROM tracks WHERE LOWER(cover_path) = LOWER(?) LIMIT 1',
  )
  ```
  Probe output:
  ```
  stored: C:/Music/Артист Песня.mp3
  asked : C:/Music/артист песня.mp3
  LOWER() match (cyrillic): []
  ascii LOWER works: (1,)
  ```
- **Reproduction / verification:** insert a `tracks` row with a Cyrillic `file_path`, then request the same path in
  lower case through `/api/stream?url=…` → 404 instead of 200.
- **Suggested fix:** do the comparison in Python (normalise with `os.path.normcase`/`casefold()` on the realpath'd
  values, or compare the `realpath` result against the row's `file_path` after `normcase`) instead of relying on
  SQLite's `LOWER()`.
- **Fix side effects:** `COLLATE NOCASE` is ASCII-only in SQLite too, so it does **not** fix this; a Python-side
  comparison costs one extra row fetch per candidate (the current SQL already full-scans `tracks` per candidate —
  a performance point for Role B).
- **Discovered by:** A

---

#### F-WN-11-11  [P3] — `_parse_byte_range` answers 416 for a range-set RFC 7233 classifies as *invalid* (must be ignored), and accepts a `+`-signed first-byte-pos

- **File:** `core/proxy.py:318-365` (the classification at L345-365)
- **Confirmed:** yes
- **Description:** Two deviations from RFC 7233 in the parser:
  1. `bytes=100-50` (last-byte-pos < first-byte-pos) is returned as `('invalid', None, None)` → the proxy answers
     **416**. RFC 7233 §2.1 defines such a byte-range-spec as *invalid*, and §4 says an origin server **MUST ignore**
     a `Range` field containing an invalid ranges-specifier (answer 200 with the whole entity).
  2. `bytes=+0-10` is accepted as `('range', 0, 10)`; `+` is not part of the `first-byte-pos` ABNF
     (`DIGIT`), so the range-set is invalid and must be ignored.
- **Cause:** the parser treats "invalid" and "unsatisfiable" as one bucket, and uses `int()` (which accepts a sign and
  surrounding whitespace) instead of a strict digit-only parse.
- **Trigger conditions:** a client sending a malformed `Range` header. Browsers do not normally do this, so the
  practical impact is small — but a 416 is a hard failure where the RFC wants the entity, and a syntactically
  invalid range is honoured as if it were valid.
- **User impact:** a malformed range yields "Requested Range Not Satisfiable" instead of the whole track; the media
  element errors out instead of playing.
- **Evidence:**
  ```python
  # core/proxy.py:359-365
  start = int(first)
  end = int(last) if last else size - 1
  ...
  if start < 0 or end < start or start >= size:
      return ('invalid', None, None)
  return ('range', start, min(end, size - 1))
  ```
  Probe output:
  ```
  'bytes=100-50'   size=1024 -> ('invalid', None, None)
  'bytes=+0-10'    size=1024 -> ('range', 0, 10)
  'bytes=0 - 10'   size=1024 -> ('range', 0, 10)
  'bytes=00-10'    size=1024 -> ('range', 0, 10)
  ```
- **Reproduction / verification:** the unit table above; end-to-end, `GET` with `Range: bytes=100-50` returns 416
  (see also `tests/test_proxy_ranges.py:82,146`, which pins this behaviour).
- **Suggested fix:** distinguish "invalid" (ignore → 200) from "unsatisfiable" (416), and parse the byte positions
  with a strict `^[0-9]+$` match.
- **Fix side effects:** `tests/test_proxy_ranges.py:79-89` pins the current classification and would have to change;
  the 416-for-unsatisfiable cases (`bytes=1024-`, `bytes=2048-3000`) must stay.
- **Discovered by:** A

---

#### F-WN-11-12  [P3] — One non-http(s) URI attribute aborts the whole HLS manifest with a 502

- **File:** `core/proxy.py:402-408` (the `ValueError`), handled at `core/proxy.py:1148-1149`
- **Confirmed:** yes
- **Description:** `local_url()` raises `ValueError('Unsupported HLS resource scheme')` for any URI whose scheme is
  not http/https. Because the rewrite applies the substitution to **every** `URI="…"` attribute in **every** tag
  line, a single such attribute (e.g. `URI="data:…"`, `URI="skd://…"` for FairPlay, or a relative URI that
  `urljoin` resolves to a non-http scheme) makes the whole manifest fail with `502 Invalid upstream HLS playlist`.
- **Cause:** the scheme check is applied to every URI attribute uniformly, with no distinction between "this is a
  resource we must proxy" and "this is an opaque URI we must leave alone".
- **Trigger conditions:** an upstream manifest containing a non-http(s) URI attribute.
- **User impact:** HLS playback fails completely for that track instead of degrading (the offending attribute could
  simply have been left untouched).
- **Evidence:**
  ```python
  # core/proxy.py:402-408
  def local_url(value):
      absolute = urllib.parse.urljoin(upstream_url, value)
      if urllib.parse.urlsplit(absolute).scheme not in ('http', 'https'):
          raise ValueError('Unsupported HLS resource scheme')
      return '/?' + urllib.parse.urlencode({...})
  ```
  ```python
  # core/proxy.py:1148-1149
  except (ValueError, UnicodeError):
      self._safe_send_error(502, 'Invalid upstream HLS playlist')
  ```
  (The `file://` case is deliberate — `tests/test_hls_playback.py:79-82` pins the `ValueError` — so only the
  over-broad application of the check is at fault.)
- **Reproduction / verification:** `module._rewrite_hls_playlist('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://key"\n', …)`
  raises `ValueError` → the caller answers 502 for the whole manifest.
- **Suggested fix:** treat only the *local-file* schemes (`file:`, UNC) as fatal (keep the security behaviour) and
  leave other non-http schemes untouched in the rewritten manifest.
- **Fix side effects:** the `file://` key must still be refused (that is the security property the existing test pins).
- **Discovered by:** A

### 3. Clean areas

Checked and found correct (no finding raised):

- **`_parse_byte_range` core semantics** (proxy.py:318-365) — verified by direct unit probing: `bytes=0-99` →
  `(range,0,99)`; `bytes=100-` → `(range,100,1023)`; `bytes=0-` → `(range,0,1023)`; end beyond EOF is clamped
  (`bytes=1000-9999` → `(range,1000,1023)`); **suffix ranges are correct** (`bytes=-500` → `(range,524,1023)`,
  `bytes=-99999` → `(range,0,1023)`) — the classic "suffix answered as 0-500" bug is fixed; `bytes=-0` and
  `bytes=1024-` are unsatisfiable; multi-range (`bytes=0-100,200-300`) and garbage (`bytes=abc`,
  `bytes=--5`, `bytes=`) are ignored and answered 200 with the whole entity (RFC 7233 allows ignoring).
- **MP3 seeking over a cached stream works end-to-end**: the first `Range: bytes=0-` request fetches and caches the
  full entity; the next `Range: bytes=1000-` is answered **206 `Content-Range: bytes 1000-4999/5000`** *from the
  local cache with no upstream request at all* (probe output in F-WN-11-9's run: `upstream: []`).
- **`serve_local_file` / `_send_local_head` header set**: `Accept-Ranges: bytes` on every response; `Content-Type`
  from `mimetypes.guess_type` (verified: `.mp3`→`audio/mpeg`, `.m4a`→`audio/mp4`, `.flac`→`audio/x-flac`,
  `.opus`→`audio/ogg`; only `.alac` falls back to `audio/mp4`); 404 (not 500) when the file is missing;
  `416` + `Content-Range: bytes */<size>` for an unsatisfiable range — including on HEAD, with no body.
- **HEAD vs GET on a local file** (same path, same headers): `HEAD` → 200 + `Content-Length: 4096` + no body;
  `HEAD` + `Range: bytes=100-199` → 206 + `Content-Range: bytes 100-199/4096` + `Content-Length: 100` + no body.
  Python's `send_error` correctly omits the body for HEAD.
- **Authentication**: `hmac.compare_digest` is used (constant time); the token is `secrets.token_urlsafe(24)`
  (192-bit) minted per `LocalProxyManager.start()`; `_authorized` **fails closed** when no token is configured
  (proxy.py:503-506) and every GET/HEAD path goes through `_authenticate` — `/api/cover`, `/api/avatar`,
  `/api/stream` and `'/'` are all gated (the only unauthenticated endpoint is `do_OPTIONS`, which is a CORS
  preflight and returns no data).
- **Token hygiene**: the token is **redacted from the request log** (`log_message`, proxy.py:488-489 — probe confirmed
  `"GET /api/cover?path=x.jpg&k=*** HTTP/1.1"` and no occurrence of the raw token in any captured record), and it is
  **never written to the database**: every `cache_stream()` call site (`core/app.py:357`, `core/resolver.py:265`,
  `audio/engine.py:327`) passes the **raw upstream URL**, never the proxy URL. The token-bearing URLs
  (`core/api.py:1218`, `core/api.py:2069`, `core/playback_recovery.py:181`, `audio/engine.py:97-117`) only travel
  to the WebView.
- **Local-file gate**: the extension allow-list + "managed app root **OR** referenced by a `tracks` row" rule refuses
  traversal (`.../streams/../../outside.mp3`), foreign `.txt`/`.env` files, foreign audio files and resolver-returned
  foreign paths (all confirmed 4xx with no content).
- **SSRF / credential scoping**: the resolved URL is validated with `_is_ssrf_safe_url` on both branches
  (proxy.py:841, 954) and on every redirect hop (`SafeRedirectHandler.redirect_request`, proxy.py:379); redirects are
  capped at 5; the provider bearer/cookies are only attached when the target host belongs to that provider
  (`_host_allows_credentials`), and are stripped on a cross-host redirect (proxy.py:382-386). Verified: a
  `soundcloud` source targeting `cdn.example` logs "Withholding soundcloud credentials".
- **CORS**: only a loopback `Origin` is echoed (`ACAO` absent for `https://evil.example` and for `Origin: null`,
  echoed for `http://localhost:3000`); `Vary: Origin` is set; the upstream's own `access-control-*` headers are
  stripped from the relay (proxy.py:1164).
- **Resource release**: `finish()` (proxy.py:469-486) closes the request thread's SQLite connection — measured:
  `db._all_conns` stays bounded across repeated requests; `ThreadingMixIn.process_request_thread` always calls
  `shutdown_request`, so no socket is leaked; the listening socket is closed and the port is rebindable after
  `stop()` (verified).
- **googlevideo range clamp** (proxy.py:74-88 + 1014-1015): an open-ended `bytes=N-` is clamped to 1 MB and the
  response is explicitly *not* cached, so a partial response can never become a full cache entry.
- **HLS rewrite basics**: `#EXT-X-MAP`, `#EXT-X-KEY` and segment URIs are all rewritten through the same `URI="…"`
  regex, relative URIs are resolved against the post-redirect `resp.geturl()`, the token is added to every rewritten
  URL and never forwarded to the CDN, the manifest is served with `Cache-Control: no-store` and is never written to
  the stream cache, and the manifest body is size-capped at 2 MB.

### 4. Coverage gaps

- **No live upstream was exercised** (no real CDN, no provider): the retry/back-off ladder, the `403/410` self-heal
  path (`resolver.invalidate` + `re_resolve_stream_url_async` + the 7 s `Event.wait`), the Yandex `Authorization:
  OAuth` injection and the yt-dlp cookie injection were read but not executed end-to-end.
- **The redirect + credential-stripping path in `SafeRedirectHandler`** was read, not exercised against a real
  redirect chain; the `_bound_googlevideo_range` clamp is computed from the **pre-redirect** URL
  (`req.full_url`, proxy.py:81), so a redirect into/out of `googlevideo.com` is not clamped — noted as an observation
  only, not raised as a finding because I could not show a concrete failure.
- **The packaged-exe branch of `_cover_roots()`** (`sys._MEIPASS`) was not exercised (dev mode only).
- **Windows-specific path semantics** (8.3 short names, device names `CON`/`NUL`/`COM1`, drive-relative `C:foo`,
  trailing separators) were reasoned about from `os.path.realpath` behaviour on this machine rather than probed
  exhaustively. One data point: `os.path.realpath` *did* expand the 8.3 short name `E8E5~1` to the long user name,
  so short-name aliasing does not create a containment escape; `os.path.isfile` on a device name returns `False`, so
  device names are refused.
- **`_referenced_by_library` TOCTOU** (row deleted between the check and the open) was not exploited; the window is
  tiny and the impact would be "one extra file served".
- **Load/soak behaviour** was not measured: thread count, ephemeral-port/TIME_WAIT pressure under a long media
  session, and the effect of `protocol_version = HTTP/1.0` (one TCP connection per request) on port exhaustion were
  not quantified (that belongs to Role B).
- **The pywebview origin was simulated**, not observed in a live WebView2 window; I assumed
  `http://127.0.0.1:<port>` from `webview.start(http_server=True)` (main.py:555), which is what makes
  `audioEl.crossOrigin = "anonymous"` (player.js:84) compatible with the proxy's loopback-only CORS echo.
- **The `finish()` / `send_error()` socket-reuse behaviour** was checked by inspection of the stdlib
  (`StreamRequestHandler.finish()` swallows `socket.error`) plus the observed connection teardown; it was not
  measured with a keep-alive client (there is none — the server is HTTP/1.0).
