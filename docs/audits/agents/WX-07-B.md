## WX-07 — App lifecycle: `main.py` → `AppCore` → `AppApi` → `cleanup()` / watchdog restart / session save-restore — ROLE B

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

| File | Lines read |
|---|---|
| `main.py` | 1–584 (whole file) |
| `core/app.py` | 1–586 (whole file) |
| `core/api.py` | 1–120, 120–329, 330–529, 905–974, 1100–1219, 2190–2239 |
| `core/proxy.py` | 1–150, 366–405, 415–484, 830–859, 945–969, 1255–1334 |
| `core/settings.py` | 295–539 |
| `core/database.py` | 145–214, 2405–2484 |
| `core/session.py` | 1–96 (whole file) |
| `core/tray.py` | 1–194 (whole file) |
| `core/plugins.py` | 100–120 |
| `services/base_service.py` | 60–129 |
| `services/watchdog_service.py` | 1–120 |
| `services/lufs_scanner.py` | 1–97 |
| `services/vk_service.py` | 1–22, 58–77 |
| `services/zapret_service.py` | 1010–1064, 1330–1379 |
| `core/services/discord_rpc.py` | 45–89 |
| `core/downloader.py` | 875–909 |
| `audio/engine.py` | class/method index (20–500, grep) |
| `ui/web_new_v2/js/main.js` | 345–394, 485–524, 630–718 |
| `tools/bench/import_chains.py` | 1–61 |
| `.venv_win/Lib/site-packages/webview/__init__.py` | 60–289 |
| `.venv_win/Lib/site-packages/webview/http.py` | 1–225 (whole file) |
| `.venv_win/Lib/site-packages/webview/util.py` | 60–129, 310–369 |
| `.venv_win/Lib/site-packages/webview/window.py` | 180–239, 540–560 |
| `.venv_win/Lib/site-packages/webview/platforms/winforms.py` | 280–349, 641–700 |
| `.venv_win/Lib/site-packages/webview/js/api.js` | 1–120 |

**Callees traced into other areas (not re-reported here; owner named)**
`core/proxy.py` (WN-11) — SSRF gate + proxy HTTP server lifecycle ·
`core/database.py` (WN-12) — connection/WAL lifecycle ·
`core/settings.py` (WN-14) — writer thread ·
`core/tray.py` (WN-16) — tray lifecycle ·
`services/*` (WN-19/WN-21/WN-25) — provider pools, watchdog observer, LUFS pool, zapret subprocess ·
`ui/web_new_v2/js/main.js` (WN-28) — bridge-ready detection / strike counter ·
`core/api.py` (WN-03…WN-10) — bridge method bodies.

**Instrumentation used** (read-only; `~/.nedotify/` of the real profile was never touched — a temp `HOME` was used for every probe that constructs a `DatabaseManager`):
`python -X importtime`, `tools/bench/import_chains.py`, and four throw-away probe scripts under `%TEMP%\opencode\` (`probe_port.py`, `probe_hijack2.py`, `probe_doh.py`, `probe_proxy2.py`) that instantiate pywebview's own `BottleServer` and the app's own `socket.getaddrinfo` patch.

---

### 1b. RESOURCE-OWNERSHIP TABLE (every resource the app creates)

| # | Resource | Created at | Owner | Released by | Released on **every** exit path? |
|---|---|---|---|---|---|
| R1 | Win32 named mutex `Local\NeDotify_App_Single_Instance_Mutex` | `main.py:260` | `main()` closure | `_release_instance_lock()` `main.py:287-301` | normal: `on_closed` (`main.py:408`) **+ again** `main.py:574`; watchdog: `main.py:514` (before `Popen`). **Too early** → see F-7 |
| R2 | pywebview Bottle/WSGI HTTP server on `127.0.0.1:42001` | inside `webview.start()` → `webview/http.py:141` | pywebview — **no owner in the app** | *never* | **NO** — the parent keeps it until `os._exit(3)` → F-6 |
| R3 | WebView2 browser processes (`msedgewebview2.exe`) | `webview.start()` → `winforms.py:683` | pywebview | window destroy / process exit | process death only |
| R4 | SQLite DB + per-thread connections | `core/app.py:107` → `database.py:165` | `AppCore.db` | `db.close()` `core/app.py:560` | yes (but see F-8 ordering) |
| R5 | `SettingsWriter` thread | `core/settings.py:512` | `SettingsManager` | **never stopped** (daemon) | daemon → dies with the process; `flush()` after `db.close()` fails silently |
| R6 | `BaseMusicService._executor` shared pool (8 workers) | lazily, `base_service.py:96` | class-level | `core/app.py:571` (`_shutdown_shared_pool`) | yes — but **after** `db.close()` → F-8 |
| R7 | per-service pools (youtube/spotify/soundcloud/yandex/recommendations) | lazily | services | `core/app.py:572-586` | yes — but **after** `db.close()` → F-8 |
| R8 | `AppApi._search_executor` (6) + `_prefetch_executor` (2) | `core/api.py:363,369` | `AppApi` | `AppApi.cleanup()` `core/api.py:453-457` | **NO** — not reached on the watchdog path → F-5 |
| R9 | pystray tray icon + `TrayThread` | `core/api.py:386`, started `core/api.py:575` | `AppApi._tray` | `AppApi.cleanup()` → `tray.stop()` `core/api.py:449-450` | **NO** — not reached on the watchdog path → F-5 |
| R10 | Local stream proxy HTTP server + `serve_forever` thread | `core/app.py:158` → `proxy.py:1276-1279` | `LocalProxyManager` | `proxy.stop()` `core/app.py:552` | yes |
| R11 | Proxy per-request threads + their SQLite connections | `proxy.py:438-446` | `ThreadingHTTPServer` | `finish()` → `db.close_thread_connection()` `proxy.py:469-484` | partially — threads are daemon and **not joined** (`block_on_close=False`, `proxy.py:425`) |
| R12 | DownloadManager pool + queue processor thread | `downloader.py:58,89` | `DownloadManager` | `downloader.stop()` `core/app.py:546` (5 s drain) | yes |
| R13 | `watchdog` `Observer` + `AudioFileHandler._processor_thread` | `watchdog_service.py:33,84,95` | `WatchdogService` | `watchdog.stop()` `core/app.py:542` | yes |
| R14 | LUFS scanner thread + pool | `lufs_scanner.py:44,50` | `LufsScannerService` | `lufs_scanner.stop()` `core/app.py:544` | yes — thread **not joined** |
| R15 | Discord RPC socket + connect thread | `core/app.py:147` → `discord_rpc.py:85` | `DiscordRPCService` | `discord_rpc.stop()` `core/app.py:550` | yes |
| R16 | Zapret `winws.exe` subprocess | `zapret_service.py:1167,1201` | `ZapretService` | `zapret.stop()` `core/app.py:554` | yes |
| R17 | `CacheCleanup` thread | `core/app.py:185` | `AppCore` | `_cache_cleanup_stop.set()` `core/app.py:556` | yes (not joined) |
| R18 | yt-dlp auto-update `pip install` subprocess | `core/app.py:76-80` | `update_ytdlp_safely` | **never tracked, never terminated** | **NO** → F-12 |
| R19 | Zapret auto-update thread | `core/app.py:155` → `zapret_service.py:1059` | `ZapretService` | daemon, never joined | process death |
| R20 | One `EmitWorker` thread per UI-thread `_emit` | `core/api.py:1148` | `AppApi` | daemon, unbounded | process death |
| R21 | **Session state** (queue / track / position) | `main.py:561` | `SessionManager` | `save_session()` → `settings.flush()` | **NO** — the watchdog path never saves → F-5 |
| R22 | Log file handle `~/.nedotify/logs/app.log` | `main.py:110` | `RotatingFileHandler` | never closed explicitly | process death (records are flushed per emit) |
| R23 | Import-time process mutations: `TCPServer.allow_reuse_address`, `bottle.run`, `socket.getaddrinfo`, `sys.excepthook`, `threading.excepthook` | `main.py:14, 84, 225, 141-142` | the interpreter | **never restored** | n/a → F-10 |

### 1c. EXIT-PATH MATRIX

| Path | Trigger | Session saved? | `AppCore.cleanup()` | `AppApi.cleanup()` | instance mutex | proxy | DB | tray | search/prefetch pools |
|---|---|---|---|---|---|---|---|---|---|
| **P1** normal close | window destroyed → `webview.start()` returns | **yes** (`main.py:561`) | yes (`575`) | yes (`577`) | released at `on_closed` (`408`) — *too early* | stopped | closed | stopped | shut down |
| **P2** minimise-to-tray | `AppApi.close()` hides the window (`api.py:926-930`) | n/a (process alive) | n/a | n/a | held | running | open | running | running |
| **P3** bridge-free close | `POST /__aura_close` → `window.destroy()` (`main.py:427-434`) | yes | yes | yes | released in `_close_handler` (`429`) — *too early* | stopped | closed | stopped | shut down |
| **P4** watchdog restart | 35 s without `loaded` → `Popen` + `os._exit(3)` | **NO** | yes (`530`) | **NO** | released at `514` before `Popen` | stopped | closed | **NOT stopped** | **NOT shut down** |
| **P5** watchdog gives up | `restart_count >= 1` (`main.py:491-493`) | no | **NO** | **NO** | held (process stays alive with a dead window) | running | open | running | running |
| **P6** second instance | mutex exists → `sys.exit(0)` (`main.py:263`) | no | no (nothing built yet) | no | n/a | n/a | n/a | n/a | n/a |
| **P7** crash inside `webview.start()` | exception propagates out of `main()` | no | **NO** | **NO** | **not released** (handle dies with the process) | running until process death | not closed | running | running |

---

### 2. Findings

#### F-WX-07-1  [P1] — The entire UI is served from a fixed, world-predictable loopback port (42001); a local process that pre-binds it gets its own HTML/JS loaded inside the app's privileged pywebview bridge

- **File:** `main.py:555` (+ `main.py:348-381`), `.venv_win/Lib/site-packages/webview/__init__.py:70,191-196`, `webview/http.py:133,141-153`, `webview/window.py:199-202,548-556`
- **Confirmed:** yes — reproduced empirically (probe output below)
- **Description:** `webview.start(http_server=True, …, private_mode=False)` is called **without** `http_port`. pywebview turns that combination into the hard-coded constant `DEFAULT_HTTP_PORT = 42001`. Every installation of NeDotify therefore serves its whole UI tree from the same, well-known loopback port, and the WebView2 window is navigated to `http://127.0.0.1:42001/index.html`. On Windows, `http.server.HTTPServer.allow_reuse_address` is `True` by default (verified: `HTTPServer.allow_reuse_address = True`), so a **second process can bind the same port while the app holds it**, and the app's own `main.py:14` mutation (`socketserver.TCPServer.allow_reuse_address = True`) pushes that Windows "port hijack" default onto every `TCPServer` in the process. Whichever socket answered first keeps serving. A local process that grabs 42001 *before* the app launches is therefore the one that answers the app's WebView2.
- **Cause:** the port is a **shared global constant** instead of a per-process random port, and pywebview never verifies that its bind succeeded (`server.running = True` is set unconditionally at `webview/http.py:149`).
- **Trigger conditions:** any unprivileged local process (or malware, or a second user on a shared PC) starts before NeDotify and binds `127.0.0.1:42001`. No special privileges needed. The user then launches NeDotify.
- **User impact:** the app's window renders the attacker's page instead of the NeDotify UI. pywebview injects `window.pywebview.api` into whatever page it loads, so the attacker's script gets the **entire `AppApi` bridge** (~200 methods: local-file reads, playlist import, settings, downloads, autostart registry writes, `open_url`, …) with the user's own privileges. The user sees a broken or plausible-looking window and has no error at all — `server.running` is `True` and no exception reaches the log.
- **Evidence:**
  ```python
  # main.py:555
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)

  # webview/__init__.py:70
  DEFAULT_HTTP_PORT = 42001
  # webview/__init__.py:191-196
  if (http.global_server is None) and (http_server or has_local_urls):
      if not _state['private_mode'] and not http_port:
          http_port = DEFAULT_HTTP_PORT          # <-- private_mode=False pins the port
      *_, server = http.start_global_server(http_port=http_port, urls=urls, server=server, **server_args)

  # webview/http.py:133 / :141-151
  server.port = http_port or _get_random_port()
  server.thread = threading.Thread(target=lambda: bottle.run(app=app, server=server_adapter, port=server.port, …), daemon=True)
  server.thread.start()
  server.running = True                       # <-- set without checking the bind
  server.address = f'{protocol}://127.0.0.1:{server.port}/'

  # webview/window.py:548-556  -> the window navigates to that address
  if is_local_url(url) and self._url_prefix and self._common_path is not None:
      filename = os.path.relpath(url, self._common_path)
      return urljoin(self._url_prefix, filename)
  ```
  Measured (`%TEMP%\opencode\probe_hijack2.py`, pywebview 5.4, this machine):
  ```
  === case A: attacker binds FIRST, then pywebview binds ===
  pywebview thread alive?  True
  GET /index.html              -> b'<html><body>ATTACKER</body></html>'
  === case B: pywebview binds FIRST, then attacker binds ===
  GET /index.html              -> b'<!DOCTYPE html>\r\n<html lang="ru" data-theme="dark" …'
  ```
  and (`probe_port.py`):
  ```
  server address      : http://127.0.0.1:42001/
  common_path (root)  : …\ui\web_new_v2
  REBIND 42001        : refused -> [WinError 10048]
  GET /index.html     : 200 209048 bytes
  ```
- **Reproduction / verification:** run `%TEMP%\opencode\probe_hijack2.py` (attacker socket on 127.0.0.1:42001 → `webview.http.BottleServer.start_server(urls=[…/ui/web_new_v2/index.html], http_port=42001)` → `urllib.request.urlopen("http://127.0.0.1:42001/index.html")` returns the attacker's bytes). In the real app the same substitution happens in WebView2 because `window.real_url` is `http://127.0.0.1:42001/index.html`.
- **Suggested fix:** pick a free random port in the app and pass it explicitly (`webview.start(http_port=<chosen>, …)`), and additionally verify after `webview.start()` that the bound socket is really ours before showing the window. Note that `http_port=0` does **not** work: `webview/__init__.py:192` tests `not http_port`, and `0` is falsy, so it would still fall back to 42001. If the HTTP server is not needed at all, loading the UI from a `file://` URL removes the server entirely (`is_local_url()` returns `False` for `file://`).
- **Fix side effects:** the app's own Bottle routes (`/__aura_close`, `/assets/*`, `/covers/*`, `main.py:417-480`) and the frontend's `fetch('/__aura_close')` (`ui/web_new_v2/js/main.js:499,709`) depend on an HTTP origin — a random port keeps that working only if the port is also injected into the frontend (the absolute URLs `'/__aura_close'` are origin-relative, so they survive).
- **Discovered by:** B

---

#### F-WX-07-2  [P2] — Wildcard CORS on the `/js_api/<uuid1>` bridge endpoint, a `uuid1` token that embeds the machine MAC address, and the entire UI tree readable from a fixed port

- **File:** `.venv_win/Lib/site-packages/webview/http.py:83,106-120,153`, `webview/window.py:199-202`, `webview/util.py:337-343`
- **Confirmed:** yes (measured); **partly mitigated** — see below
- **Description:** the pywebview Bottle app registers `POST /js_api/<server.uid>` with `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: PUT, GET, POST, DELETE, OPTIONS`. `server.uid = str(uuid.uuid1())` (`http.py:83`) is **time- and MAC-derived**, not random: the node field of the uuid1 *is* the network adapter's MAC address, and the timestamp field is a 100 ns counter. The uid is also injected into the page (`util.py:342`), so any code running in the WebView knows it. Because the port is fixed (F-1), the endpoint path is the only unknown.
- **Cause:** the bridge URL is a bearer token carried in the URL path over a wildcard-CORS HTTP origin on a well-known port.
- **Trigger conditions:** any process on the machine (or a web page in the user's normal browser, since the CORS header is `*`) can `POST http://127.0.0.1:42001/js_api/<uid>` and **read the response cross-origin**. Guessing the uid needs the MAC address (readable by any local process via `uuid.getnode()`) and the launch timestamp (observable via the process start time) — the search space is small.
- **User impact:** on pywebview 5.4 the practical impact is **limited**: `server.js_callback` is never populated on the Windows/edgechromium backend (`js_callback` appears only in `http.py:81,117-118` across the whole package), so the request returns an empty `200` and pywebview logs *"JS callback function is not set for window …"*. The real bridge on Windows runs over `window.chrome.webview.postMessage` (`webview/js/api.js`), not over HTTP. What *is* exposed is (a) the machine's MAC address, recoverable by anyone who can guess the uid, and (b) the complete `ui/web_new_v2` tree (209 KB `index.html` + 34 ES modules + assets + covers) readable by any local process on a fixed, guessable port.
- **Evidence:**
  ```python
  # webview/http.py:83
  self.uid = str(uuid.uuid1())
  # webview/http.py:106-114
  @app.post(f'/js_api/{server.uid}')
  def js_api():
      bottle.response.headers['Access-Control-Allow-Origin'] = '*'
      bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
      bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'
  ```
  Measured (`probe_port.py`):
  ```
  server.uid (uuid1)  : ea0e6f92-ccc1-11f1-af7a-eebb0b4d0ad3      <-- node eebb0b4d0ad3 == the MAC
  POST /js_api status : 200
    hdr Access-Control-Allow-Origin : *
    hdr Access-Control-Allow-Methods : PUT, GET, POST, DELETE, OPTIONS
  GET /index.html     : 200 209048 bytes
  GET /js/main.js     : 200 35569 bytes
  ```
- **Reproduction / verification:** `probe_port.py` (above). To show the MAC leak explicitly, compare `server.uid.split('-')[-1]` with `uuid.getnode()` formatted as 12 hex digits.
- **Suggested fix:** F-1's random port already removes the "fixed, guessable origin" half. Additionally, avoid `uuid1()` for a security token (use `uuid4()` / `secrets.token_urlsafe`), and pin the CORS header to the app's own origin instead of `*`.
- **Fix side effects:** none for the Windows backend (the HTTP bridge route is dead there); a future pywebview version that routes the bridge over HTTP would make this P1 unless the uid is randomised and the CORS is tightened.
- **Discovered by:** B

---

#### F-WX-07-3  [P2] — The process-wide `socket.getaddrinfo` patch is irreversible and adds a measured **13.7 s** to every failed DNS resolution, inside the SSRF guard on the proxy's hot path

- **File:** `main.py:160-230` (installed at import time, `main.py:227-230`)
- **Confirmed:** yes — measured
- **Description:** `main.py` replaces `socket.getaddrinfo` for the whole interpreter with a wrapper that, on **any** `socket.gaierror`, tries three DNS-over-HTTPS endpoints in the **caller's thread** with a 2 s timeout each. The patch is installed unconditionally at import time, there is no setting to disable it, and — because `_orig_getaddrinfo` is a local of `_enable_doh_fallback()` captured only in the closure — **there is no way to uninstall it** (verified: `main` exposes no `_orig_getaddrinfo` and no restore/uninstall symbol). Every third-party resolver in the process (requests, urllib3, yt-dlp, curl_cffi, Discord, `http.client`, asyncio's default resolver) goes through it.
- **Cause:** the fallback is executed inline on the failure path, with no circuit breaker, no negative cache, and no per-host budget; the cost is paid by whichever thread happened to resolve.
- **Trigger conditions:** any DNS failure — a genuinely dead host, a filtered ISP resolver, or a typo. `core/api.py:145` (`_dns_resolves_to_public_ip` → `socket.getaddrinfo`) is called from `_is_ssrf_safe_url`, which is invoked on **every proxied request** (`core/proxy.py:841`, `:954`) and on every redirect hop (`core/proxy.py:379`) — i.e. inside the proxy's thread-per-request server.
- **User impact:** one unresolvable host stalls a proxy request thread for ~14 s (the source comment at `core/api.py:93-98` assumes "~6 s"). The SSRF guard itself becomes the slowest part of the request path. A handful of failing hosts produces a thread-per-request storm in `ThreadingHTTPServer` (`core/proxy.py:421-446`).
- **Evidence:**
  ```python
  # main.py:180-221
  def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
      try:
          return _orig_getaddrinfo(host, port, family, type, proto, flags)
      except socket.gaierror:
          pass
      ...
      for doh_url in [f"https://1.1.1.1/dns-query?name={host}&type=A", …]:
          with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp: …
      raise socket.gaierror(f"All DoH endpoints failed for {host!r}")
  # main.py:225
  socket.getaddrinfo = _doh_getaddrinfo
  ```
  Measured (`%TEMP%\opencode\probe_doh.py`):
  ```
  single resolution failed after 13.68 s: gaierror: All DoH endpoints failed for 'this-host-does-not-exist-nedotify-probe.invalid'
  socket.getaddrinfo is patched: _doh_getaddrinfo
  original recoverable?        : no module-level handle in main.py
  uninstall helper in main.py?  : False
  ```
  Proxy-env behaviour (measured, `probe_proxy2.py`): the DoH request **does** honour the user's proxy — env vars *and* the WinINET registry (`urllib.request.getproxies()`), the proxy receives only `CONNECT 1.1.1.1:443` and **never the queried hostname**; the hostname is visible only to the DoH operator (Cloudflare / Google / **Yandex 77.88.8.8**), which is inherent to DoH but is an unconditional, undocumented disclosure of every host the app fails to resolve.
- **Reproduction / verification:** `probe_doh.py` (imports `main`, then resolves a `.invalid` host and times it). For the proxy path, request a proxied URL whose `url=` host does not resolve and time the response.
- **Suggested fix:** (a) perform the DoH lookup on a **bounded background thread** with a short budget and return the original `gaierror` immediately, instead of blocking the caller; (b) add a negative cache so a host that failed DoH is not retried for N seconds; (c) expose the patch as an explicit, reversible opt-in (keep `_orig_getaddrinfo` in a module-level variable and add an `uninstall_doh_fallback()`), and make it a user setting rather than an unconditional import-time side effect.
- **Fix side effects:** an immediate `gaierror` makes the "blocked DNS" scenario fail fast instead of being rescued by DoH — that is the whole point of the feature, so the fallback must stay, but it must be asynchronous or strictly time-boxed.
- **Discovered by:** B

---

#### F-WX-07-4  [P2] — The DoH "re-entrancy guard" is a `threading.local`, so it does not serialise concurrent lookups: N failures ⇒ 3N outbound DoH requests in parallel

- **File:** `main.py:167, 193-198, 222-223`
- **Confirmed:** yes — measured
- **Description:** the comment at `main.py:153-158` claims the thread-local guard is "a second line of defence" that keeps nested lookups out of the fallback. It only prevents **same-thread** recursion. Because `_doh_inflight` is a `threading.local`, every *other* thread sees `getattr(_doh_inflight, 'active', False) is False` and enters the DoH path independently. Under a DNS outage, N concurrent resolutions therefore produce **3N simultaneous outbound HTTPS requests** to three external resolvers — an amplification of the app's own failure.
- **Cause:** a per-thread guard was used where a process-wide (or per-host) one was needed.
- **Trigger conditions:** the exact scenario the feature exists for — an ISP-level DNS block — with more than one thread resolving at once (the proxy is thread-per-request; the provider pools have 8+ workers).
- **User impact:** the app turns one DNS outage into a self-inflicted DoH request flood (and the per-request 13.7 s stall of F-3). It also produces the misleading error `socket.gaierror("DoH fallback busy resolving …")` when the guard *does* trip (same-thread nesting).
- **Evidence:**
  ```python
  # main.py:167
  _doh_inflight = threading.local()    # recursion guard
  # main.py:195-198
  if getattr(_doh_inflight, 'active', False):
      raise socket.gaierror(f"DoH fallback busy resolving {host!r}")
  _doh_inflight.active = True
  ```
  Measured (`probe_doh.py`, 4 threads, 4 distinct failing hosts):
  ```
  4 concurrent failing resolutions finished in 13.64 s (per-call: 13.25s, 13.33s, 13.54s, 13.63s)
  ```
  All four ran **in parallel** (wall time ≈ the slowest single call), which is only possible if the guard did not serialise them.
- **Reproduction / verification:** the same probe; add `print(threading.get_ident())` inside `_doh_getaddrinfo` to see concurrent entries.
- **Suggested fix:** replace the thread-local with a process-wide `threading.Lock` plus a short "one DoH lookup in flight" gate (or a global semaphore of 1 with a per-host in-flight map, as `core/resolver.py` already does for stream resolution).
- **Fix side effects:** serialising the fallback makes the 2nd..Nth failing thread wait for the first (up to ~14 s) instead of failing immediately — pair it with the negative cache of F-3, otherwise the worst case gets worse for the caller.
- **Discovered by:** B

---

#### F-WX-07-5  [P2] — The watchdog restart path never saves the session: the queue, the current track and the playback position are lost

- **File:** `main.py:482-541` vs `main.py:557-571`
- **Confirmed:** yes
- **Description:** the only `save_session()` call in the whole app is at `main.py:561`, i.e. **after** `webview.start()` returns. The watchdog path never returns from `webview.start()`: it spawns a child process and calls `os._exit(3)` (`main.py:539`). The restart path flushes the *settings* (`main.py:526,536`) but never the *session*.
- **Cause:** session persistence lives in `main()` after the GUI loop, but the restart path is a second, independent exit path that bypasses it.
- **Trigger conditions:** the watchdog fires — precisely the broken-startup scenario in which the user is most likely to lose their place.
- **User impact:** after an automatic restart the user comes back to an **empty queue**; the restored track and the playback position are gone even though the settings row `session.last_queue` was written by the *previous* successful run (stale by one session). The user must re-queue their music by hand.
- **Evidence:**
  ```python
  # main.py:495-539 (watchdog)
  logging.warning("[startup] bridge not initialized after 35s; reloading (real restart)")
  …
  subprocess.Popen(restart_args, creationflags=creation_flags, close_fds=True, env=env)
  app_core.settings.sync_flush_now()
  app_core.cleanup()
  app_core.settings.sync_flush_now()
  os._exit(3)

  # main.py:557-571 (the only save_session in the repo)
  try:
      engine = app_core.engine
      app_volume = app_core.settings.get("audio", "volume", 70)
      app_core.session.save_session(track_id=…, position=…, volume=…, queue=…, …)
  except Exception as e:
      print(f"Failed to save session: {e}")
  ```
  `grep -n "save_session" main.py core/*.py` → only `main.py:561` (definition in `core/session.py:39`).
- **Reproduction / verification:** set `NEDOTIFY_RESTART_COUNT=0`, make the WebView2 load hang (e.g. block the pinned runtime path), start the app, and compare `session.last_queue` in `~/.nedotify/nedotify_storage.db` before and after the restart — it is unchanged by the restarting process.
- **Suggested fix:** extract a single `save_session_and_cleanup()` helper and call it from **both** exit paths (before `os._exit(3)` and after `webview.start()` returns), using the same `engine.queue` snapshot.
- **Fix side effects:** saving on the watchdog path requires the DB to still be open — it is (`app_core.cleanup()` closes it at `core/app.py:560`, after the save would have to happen); make sure the save runs *before* `cleanup()`.
- **Discovered by:** B

---

#### F-WX-07-6  [P2] — On the watchdog restart the child starts while the parent still owns the fixed HTTP port; the parent's origin keeps answering the child's WebView and the parent then `os._exit(3)`s out from under it

- **File:** `main.py:505-539` (+ `main.py:555`)
- **Confirmed:** yes — code path confirmed, socket behaviour measured
- **Description:** the parent spawns the child at `main.py:515-520` and only then tears itself down (`app_core.cleanup()` at `:530`, which can take up to ~5 s because `downloader.stop(drain_timeout=5.0)` drains running workers — `core/downloader.py:884-909`) and finally `os._exit(3)` at `:539`. Throughout that window the parent still owns `127.0.0.1:42001` (the pywebview server is never stopped — see the resource table R2). The child starts its own pywebview server on the same port; because Windows' `SO_REUSEADDR` allows the second bind, **the child's bind succeeds silently**, but the parent's socket keeps receiving the connections (measured: case B of `probe_hijack2.py`).
- **Cause:** the restart path reasons about the *instance mutex* (released at `main.py:514` before `Popen`) but not about the *HTTP port*, which is a second, equally exclusive resource that the parent keeps for the whole teardown.
- **Trigger conditions:** any watchdog restart — i.e. exactly the broken-startup case.
- **User impact:** the child's WebView loads the parent's origin. It usually *looks* fine (same static files), but it is the parent's server, not the child's; the child then races the parent's `os._exit(3)`. If the parent dies first, the child's own server has to take over a port whose socket was just torn down — a race with no error handling on either side, and no log line either.
- **Evidence:**
  ```python
  # main.py:508-520
  # Release BEFORE spawning. The single-instance guard now runs at
  # the very top of main(), so a child that starts while this process
  # still holds the mutex sees ERROR_ALREADY_EXISTS and exits at once …
  _release_instance_lock()
  subprocess.Popen(restart_args, creationflags=creation_flags, close_fds=True, env=env)
  …
  app_core.cleanup()          # can take ~5s (downloader drain)
  os._exit(3)                 # the HTTP server is still bound at this point
  ```
  Measured socket behaviour (`probe_hijack2.py`, case B): first binder keeps the connections, second bind succeeds and is silently ignored.
- **Reproduction / verification:** run the app with the bridge forced to fail (e.g. point `WEBVIEW2_RUNTIME_PATH` at a broken runtime) and watch `netstat -ano | findstr 42001` while the parent tears down; the port stays owned by the parent for the whole `cleanup()` window.
- **Suggested fix:** stop the pywebview HTTP server (or let the child own the port) before spawning; at minimum, wait for the parent's port to be released before `Popen`, or give the child an explicit, different port (see F-1's random-port fix, which removes the collision entirely).
- **Fix side effects:** the parent cannot stop pywebview's server cleanly (there is no public API for `http.global_server`); using a per-process random port (F-1) is the only clean fix.
- **Discovered by:** B

---

#### F-WX-07-7  [P2] — The single-instance mutex is released in `on_closed`, up to ~5 s before the process actually exits, so a second full instance can start

- **File:** `main.py:287-301, 406-408, 427-434, 574`
- **Confirmed:** yes
- **Description:** the instance guard is a named Win32 mutex whose *existence* (not ownership) is the test — `CreateMutexW(None, False, "Local\\NeDotify_App_Single_Instance_Mutex")` with `bInitialOwner=False` (`main.py:260`). The mutex object therefore disappears as soon as the **last handle** is closed. `on_closed` closes that handle the moment the window is destroyed (`main.py:408`), and `_close_handler` does the same before `window.destroy()` (`main.py:429`). The process, however, keeps running for the whole of `save_session` + `app_core.cleanup()` (up to ~5 s of downloader drain) before `sys.exit(0)` (`main.py:580`).
- **Cause:** the guard is released on a *UI* event rather than at process termination, and the teardown between the two is long and variable.
- **Trigger conditions:** the user closes the window and relaunches the app (or an autostart entry fires) inside that window.
- **User impact:** a **second complete instance** starts while the first is still running: two windows, two tray icons, two stream proxies, two sets of provider threads, and two writers on the same SQLite file. With the fixed port (F-1) the second instance's WebView also silently renders the first instance's origin.
- **Evidence:**
  ```python
  # main.py:406-408
  def on_closed():
      _INTENTIONAL_CLOSE.set()
      _release_instance_lock()          # <-- released here, ~5s before exit
  # main.py:427-434
  def _close_handler():
      _INTENTIONAL_CLOSE.set()
      _release_instance_lock()          # <-- released here too
      try:
          window.destroy()
  # main.py:287-295
  def _release_instance_lock():
      if sys.platform == "win32" and _INSTANCE_MUTEX:
          ctypes.windll.kernel32.CloseHandle(_INSTANCE_MUTEX)   # destroys the named object
          _INSTANCE_MUTEX = None
  ```
- **Reproduction / verification:** close the window and immediately re-launch; `netstat -ano | findstr 42001` shows two owning PIDs, and `~/.nedotify/logs/app.log` shows two `[startup] process started` entries with no "Another instance" line.
- **Suggested fix:** release the mutex only in an `atexit`/`finally` block around the whole `main()` body, i.e. after `app_core.cleanup()`; keep `_INTENTIONAL_CLOSE` on the UI event.
- **Fix side effects:** if the process is killed (`TerminateProcess`, power loss), the handle is closed by the OS anyway — so moving the release later does not make the guard leak; the `Local\` namespace already scopes it to the session.
- **Discovered by:** B

---

#### F-WX-07-8  [P2] — `AppCore.cleanup()` closes the database *before* shutting the worker thread pools down

- **File:** `core/app.py:555-586` (order), `core/database.py:2413-2438, 2459-2484`
- **Confirmed:** yes for the ordering; the failure mode is a hypothesis (needs a live run to observe)
- **Description:** the teardown closes the DB at `core/app.py:560` and only afterwards shuts down the shared provider pool (`core/app.py:571`) and the six per-service pools (`core/app.py:572-586`) — all with `wait=False, cancel_futures=True`, i.e. in-flight tasks are **not** drained. `DatabaseManager.close()` (`core/database.py:2459-2484`) closes every tracked connection but leaves each worker thread's `threading.local` slot pointing at the closed handle, so any later `_get_connection()` returns a closed connection and raises `sqlite3.ProgrammingError: Cannot operate on a closed database.` The proxy's request threads are likewise not joined (`core/proxy.py:425` `block_on_close = False`, `daemon_threads = True`) and can still be inside `do_GET` when `db.close()` runs.
- **Cause:** the teardown order was written "DB last" in the comments but the implementation puts the DB close *before* the pools it depends on.
- **Trigger conditions:** the user closes the app while a provider lookup, a stream resolution (`core/resolver.py:256` → `db.cache_stream`) or a proxied request is in flight.
- **User impact:** the in-flight task fails. Because the failure is swallowed by the `Future` (nobody calls `future.result()`), the loss is **silent**: the resolved stream URL is not cached and the UI never learns why. `db.close()` also runs `PRAGMA wal_checkpoint(TRUNCATE)` (`core/database.py:2455`) which needs an exclusive WAL lock — with `busy_timeout=30000` (`core/database.py:190`) a concurrent writer can stall the shutdown for up to 30 s.
- **Evidence:**
  ```python
  # core/app.py:555-586
  if getattr(self, "_cache_cleanup_stop", None) is not None:
      _step("cache_cleanup.stop", self._cache_cleanup_stop.set)
  if getattr(self, "settings", None) and hasattr(self.settings, "flush"):
      _step("settings.flush", self.settings.flush)
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)              # <-- DB closed here (line 560)

  # O-15: shutdown(wait=False) all thread pools so app exit never blocks
  def _shutdown_shared_pool(): …
  _step("base_service pool", _shutdown_shared_pool)   # <-- pools stopped here (line 571), i.e. AFTER
  for _pool in (downloader._pool, cache._executor, youtube._executor, …):
      _pool.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # core/database.py:2424-2438
  existing = getattr(self._local, "connection", None)   # other threads' slots still hold the closed conn
  if existing is None: return
  try: existing.close()
  …
  self._local.connection = None                         # only the CALLING thread's slot is cleared
  ```
- **Reproduction / verification:** start a search (so the shared provider pool has an in-flight task), then close the window; `app.log` should show `LUFS scan loop error` / `Cannot operate on a closed database` (the LUFS loop at `services/lufs_scanner.py:62-97` logs such errors rather than crashing — that path is already visible in the code).
- **Suggested fix:** move `db.close()` to the very end of `cleanup()`, after every pool has been shut down; additionally give the pools a bounded drain (`wait=True` with a timeout) instead of `wait=False`.
- **Fix side effects:** a bounded drain lengthens the shutdown by up to the drain budget; the current design chose `wait=False` specifically to avoid blocking exit ("O-15"), so a *bounded* wait (e.g. 2–3 s) is the compromise.
- **Discovered by:** B (owning area for the ordering: **WN-02** `core/app.py`; the DB handle semantics belong to **WN-12**)

---

#### F-WX-07-9  [P2] — The watchdog waits for the *page* `loaded` event, not for the bridge, and the frontend's bridge-dead counter lives in `sessionStorage`, which a process restart resets — so the documented recovery can never complete

- **File:** `main.py:482-495` (+ `main.py:21-23`), `ui/web_new_v2/js/main.js:374-388`
- **Confirmed:** yes for the code paths; the `sessionStorage` reset is standard browser semantics (not verified against a live WebView2 run — see Coverage gaps)
- **Description:** the watchdog's stated purpose is *"if the JS bridge never comes up (WebView2 init hang)"* (`main.py:415-416`), but it waits on `window.events.loaded` (`main.py:484`) — the **page** load, not the bridge. The frontend has a *different*, bridge-level detector: `ui/web_new_v2/js/main.js:377-388` counts "loads that happened without a bridge" in `sessionStorage` and shows the error overlay only after **3 strikes** within 45 s. Its own comment says *"the backend watchdog silently reloads twice"* — but the backend watchdog does not reload the page, it **restarts the process** (`main.py:505-539`), which creates a new WebView2 browsing context and therefore a **fresh, empty `sessionStorage`**.
- **Cause:** two independent recovery mechanisms (backend process restart, frontend strike counter) that were designed for different recovery models (reload vs restart) and were never reconciled. The backend log message at `main.py:492` even claims *"showing overlay, no more respawns"* although the code only logs and returns.
- **Trigger conditions:** the bridge fails to initialise while the page itself loads — the exact "Evergreen 151.0.4129.93 hangs bridge injection (loaded/_pywebviewready never fire)" case named in `main.py:21-23`, and the case the frontend overlay was written for.
- **User impact:** the user is left with a window whose bridge is dead, **with no error overlay** (the strike counter can never reach 3 because every restart resets it) and no further automatic recovery (the child inherits `NEDOTIFY_RESTART_COUNT=1` and gives up after 35 s). The only escape is closing the app.
- **Evidence:**
  ```python
  # main.py:482-495
  def _startup_watchdog():
      # First load may take ~10-20s on cold WebView2; give it 35s.
      if window.events.loaded.wait(35):
          logging.info("[startup] bridge initialized after 1 load attempt(s)")
          return
      …
      restart_count = int(os.environ.get('NEDOTIFY_RESTART_COUNT', '0'))
      if restart_count >= 1:
          logging.error("[startup] bridge still not initialized after 1 auto-restart; showing overlay, no more respawns.")
          return
  ```
  ```javascript
  // ui/web_new_v2/js/main.js:374-388
  // Bridge-dead last resort: count page loads that happened without a bridge
  // (the backend watchdog silently reloads twice), and only then show the error
  // overlay — after 45s of bridge absence on the 3rd load (initial + 2 reloads).
  if (!isBridgeReady()) {
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0') + 1;
      sessionStorage.setItem('nedotify_bridge_strikes', String(strikes));
  }
  setTimeout(() => {
      if (isBridgeReady()) return;
      const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0');
      if (strikes >= 3) { … showBridgeError(); }
  }, 45000);
  ```
  Note also that the *only* UI affordance for a reload is the overlay's "Перезагрузить" button (`main.js:704-706`), so the strike counter can never be incremented from the UI either — the overlay is unreachable by construction.
- **Reproduction / verification:** break the bridge (e.g. set `WEBVIEW2_RUNTIME_PATH` to a runtime where the injected `api.js` fails), start the app, let the watchdog fire, and observe that the new process shows no overlay and that `sessionStorage['nedotify_bridge_strikes']` is `1` again. Alternatively, unit-test the counter logic with a fresh `sessionStorage` per "process".
- **Suggested fix:** pick one owner for the "bridge is dead" decision. Either (a) the backend waits for a bridge-level signal (pywebview exposes `window.events._pywebviewready`, which the frontend already listens for — `main.js:363`) and restarts the process, or (b) the backend restarts *the page* (`window.evaluate_js("location.reload()")`) so `sessionStorage` survives and the frontend's counter works as designed. Move the strike counter from `sessionStorage` to `localStorage` if (a) is chosen.
- **Fix side effects:** option (b) loses the "fresh process" benefit of the watchdog (a wedged WebView2 process usually needs a process restart, not a page reload); option (a) requires the backend to know when the bridge is ready, which the frontend can report via one `_emit` call.
- **Discovered by:** B (cross-component: the watchdog is **WN-01** `main.py`; the strike counter and overlay are **WN-28** `ui/web_new_v2/js/main.js`)

---

#### F-WX-07-10  [P3] — Five irreversible process-wide mutations are executed at import time of `main.py`, including a stdlib class attribute, `bottle.run`, `socket.getaddrinfo` and both excepthooks

- **File:** `main.py:13-14, 61-86, 119-145, 160-230`
- **Confirmed:** yes
- **Description:** merely importing `main` (the process entry point, but also any module that imports it — a test, a tool, a plugin) permanently changes the interpreter:
  1. `socketserver.TCPServer.allow_reuse_address = True` (`main.py:14`) — a **stdlib class attribute** mutated process-wide. (Effect on the app's own servers: none — `http.server.HTTPServer.allow_reuse_address` is already `True` (verified on Python 3.14.7), and both the proxy's `ThreadingHTTPServer` and pywebview's `WSGIServer` inherit from it. The mutation only lowers the safety default for any *other* `TCPServer` subclass in the process.)
  2. `bottle.run = _capture_bottle_run` (`main.py:84`) — a third-party module's public function replaced for the whole process, never restored.
  3. `sys.excepthook` and `threading.excepthook` replaced (`main.py:141-142`) — the originals are not saved; the new hook also stops printing to stderr, so an unhandled main-thread exception is now only in `app.log`.
  4. `socket.getaddrinfo` replaced (`main.py:225`) — irreversible (F-3).
  5. `logging.basicConfig(...)` + a `RotatingFileHandler` on `~/.nedotify/logs/app.log` (`main.py:104-117`) — opens a file at import time, and `basicConfig` is a no-op if the root logger already has handlers, so in an embedding process the app's log level silently does not apply.
  Additionally `sys.path.insert(0, …)` (`main.py:95`) mutates the import path at import time.
- **Cause:** bootstrap concerns are implemented as module-level side effects rather than as an explicit, ordered bootstrap function.
- **Trigger conditions:** any `import main`.
- **User impact:** none directly for the packaged app (the process is dedicated to NeDotify); the practical cost is testability — a pytest session that imports `main` cannot restore the resolver, so every test afterwards runs with the DoH patch and the mutated `bottle.run` (F-3's 13.7 s stall is therefore also a *test-suite* hazard).
- **Evidence:**
  ```python
  # main.py:13-14
  import socketserver
  socketserver.TCPServer.allow_reuse_address = True
  # main.py:84
  _bottle.run = _capture_bottle_run
  # main.py:141-145
  sys.excepthook = _hook
  threading.excepthook = _thread_hook
  _install_global_excepthooks()
  # main.py:225
  socket.getaddrinfo = _doh_getaddrinfo
  ```
  Verified on Python 3.14.7: `TCPServer.allow_reuse_address = False` → `True` after `main.py:14`; `HTTPServer.allow_reuse_address = True` (already, so the app's servers are unaffected).
- **Reproduction / verification:** `python -c "import socket, socketserver, main; print(socketserver.TCPServer.allow_reuse_address, socket.getaddrinfo.__name__)"` → `True _doh_getaddrinfo`.
- **Suggested fix:** move all five side effects into an explicit `bootstrap()` called from `main()` under `if __name__ == "__main__"`, keep the original objects in module-level variables (`_ORIG_GETADDRINFO`, `_ORIG_BOTTLE_RUN`, `_ORIG_EXCEPTHOOK`) and provide `restore()` helpers so tests can undo them.
- **Fix side effects:** `logging.basicConfig` must still run before anything logs; the DoH patch must be installed before the first network call — both are satisfied inside `bootstrap()`.
- **Discovered by:** B

---

#### F-WX-07-11  [P3] — Startup import cost is ~350–490 ms, of which **154 ms (44 %)** is `yt_dlp` pulled in eagerly by `services/vk_service.py`, and the SQLite schema is created eagerly before the window exists

- **File:** `services/vk_service.py:9-13`, `core/app.py:14-35, 107-108, 122-159`, `main.py:306, 348`
- **Confirmed:** yes — measured
- **Description:** the import graph that runs before `main()` is entered is dominated by `yt_dlp`, and `yt_dlp` is pulled in by `services/vk_service.py:10` — a module-level `import yt_dlp` for a **single** call site (`vk_service.py:69`). `core/app.py:26` imports `VKService` eagerly, so every launch pays for it. The DB is opened and the whole schema (20 tables) is created in `AppCore.__init__` (`core/app.py:107` → `database.py:165`) — i.e. **before** `webview.create_window()` (`main.py:348`), so the DB work is on the critical path of the first paint. The proxy is likewise started inside `AppCore.__init__` (`core/app.py:158`), before the window exists.
- **Cause:** eager, module-level imports of heavy optional dependencies; the DB/proxy initialisation is not moved off the UI-critical path.
- **Trigger conditions:** every launch.
- **User impact:** ~0.2 s of avoidable blank time before the window appears on every start, on top of the ~0.35–0.49 s of import time.
- **Evidence:** project bench tool (`tools/bench/import_chains.py`, fresh profile):
  ```
  main:                              main(348.1)
  core.app:                          core.app(264.4) <- main(348.1)
  services.vk_service:               services.vk_service(154.5) <- core.app(264.4)
  yt_dlp:                            yt_dlp(154.2) <- services.vk_service(154.5)
  yt_dlp.cookies:                    yt_dlp.cookies(101.1) <- yt_dlp(154.2)
  webview:                           webview(48.9) <- main(348.1)
  services.spotify_service/requests: services.spotify_service(46.8) / requests(45.8)
  ```
  My own measurement in this repo (warm `.pyc`): `import main` = **461 ms**; `DatabaseManager()` = 11 ms (empty DB, 20 tables); `SettingsManager()` = 6.7 ms.
- **Reproduction / verification:** `& .venv_win\Scripts\python.exe tools\bench\import_chains.py`; `python -X importtime -c "import main"`.
- **Suggested fix:** make `yt_dlp` a lazy import inside the single VK method (as `core/app.py:151` already does for the updater); consider deferring the DB schema creation and the proxy start to a background thread with a readiness handshake, so the first paint is not gated on them.
- **Fix side effects:** deferring the DB open means the first bridge call may race the initialisation — the schema must be complete before any query, so this needs an explicit "DB ready" event rather than a blind deferral.
- **Discovered by:** B (import graph: **WN-19/WN-21** own the provider modules; the eager `AppCore.__init__` is **WN-02**)

---

#### F-WX-07-12  [P3] — The yt-dlp auto-update `pip install` subprocess is untracked and never terminated, so it can outlive the app

- **File:** `core/app.py:47-88` (thread `core/app.py:151`)
- **Confirmed:** yes
- **Description:** `update_ytdlp_safely()` runs `subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"], capture_output=True, timeout=120)` on a daemon thread started from `AppCore.__init__`. The `Popen` handle is never kept, so nothing can cancel or terminate it. On Windows a child process is **not** killed when the parent exits — including on the `os._exit(3)` watchdog path (`main.py:539`).
- **Cause:** the subprocess is fire-and-forget with no lifecycle ownership.
- **Trigger conditions:** the user has `~/.nedotify/.ytdlp_update_pending` present (i.e. a previous run deferred the update) and launches the app; the update then runs for up to 120 s.
- **User impact:** an orphaned `pip install` keeps running (and keeps writing to the site-packages) after the app is closed or after a watchdog restart — a second app start can then race the same `pip install` on the same `site-packages`.
- **Evidence:**
  ```python
  # core/app.py:76-80
  result = subprocess.run(
      [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
      capture_output=True,
      timeout=120,
  )
  ```
  No `Popen` object is stored, and `AppCore.cleanup()` (`core/app.py:508-586`) has no step for it.
- **Reproduction / verification:** create `~/.nedotify/.ytdlp_update_pending`, start the app, close it within a second, and check `tasklist | findstr pip` / the `python.exe -m pip` child.
- **Suggested fix:** use `subprocess.Popen` and keep the handle on `AppCore`; terminate it in `AppCore.cleanup()`; or move the whole update to a separate helper process that is allowed to finish independently of the app.
- **Fix side effects:** terminating mid-install can leave a partially upgraded `yt-dlp`; the "defer to next launch" design (`core/app.py:66-69`) already accepts that, but a clean kill is still better than an orphan.
- **Discovered by:** B (owning area: **WN-13/ WN-01** — the updater lives in `core/app.py`, the update policy in `core/app.py`)

---

### 3. Clean areas

- **The single-instance guard itself is sound in design**: it is created *before* any resource exists (`main.py:239-303` — "deliberately the FIRST thing main() does"), it uses `bInitialOwner=False` correctly so that `CloseHandle` genuinely releases the name, and it is released *before* `Popen` in the watchdog path (`main.py:514`) with a comment that explains exactly why — this reasoning is right; only the *timing* of the release on the normal path is wrong (F-7).
- **The watchdog respawn is bounded — there is no fork-bomb.** `NEDOTIFY_RESTART_COUNT` is incremented in the child's environment (`main.py:490-502`) and the guard `if restart_count >= 1: return` (`main.py:491-493`) caps the chain at **two** processes total. The counter is per-launch (environment only), so it cannot persist across reboots and cannot be inherited by an unrelated process. The frozen-vs-source argv handling (`main.py:503-507`) is also correct.
- **The proxy is well designed security-wise**: dynamic port (`core/proxy.py:1276`), a per-session bearer token regenerated on every start (`core/proxy.py:1275`), a per-source credential allow-list (`core/proxy.py:60-64`), a strict path allow-list (`core/proxy.py:40`) and an SSRF gate on every request and redirect. This is a *much* better posture than the pywebview server's fixed port (F-1).
- **`_emit` never runs on the UI thread** — `core/api.py:1147-1154` correctly hands the call to an `EmitWorker` daemon thread when the caller is the main thread. The contract in `AGENTS.md` holds.
- **The lazy service properties avoid a first-access stall and a deadlock**: `AppCore.soundcloud` / `.yandex` / `.recommendations` (`core/app.py:187-234`) use the existing `_service_lock` (`RLock`) and resolve dependencies *before* taking the lock, exactly as the project's locking rule requires.
- **`BaseMusicService`'s shared pool is genuinely lazy** (`services/base_service.py:65-118`): importing a service spawns no threads, and `submit()` degrades to a no-op after shutdown instead of raising "cannot schedule new futures after interpreter shutdown".
- **`ThreadingHTTPServer.daemon_threads = True` + `block_on_close = False`** (`core/proxy.py:425-430`) is the right choice — it prevents `sys.exit()` from blocking on an in-flight proxied stream.
- **The proxy releases its per-request SQLite connection** in `finish()` (`core/proxy.py:469-484`), which prevents the 8 MB-per-thread page cache from accumulating.
- **`AppCore.cleanup()` isolates every step** (`core/app.py:522-526`) so one failing subsystem cannot abort the rest, and each failure is logged — a genuine improvement over the silent `except: pass` it replaced.
- **The `atexit` settings flush** (`core/settings.py:313`) plus the explicit `sync_flush_now()` calls on the hard-exit path (`main.py:526,536`) correctly address the "`os._exit` skips atexit" problem for settings.
- **The session restore path is defensive**: `main.py:314-330` wraps the whole restore in `try/except` so a corrupt session row cannot prevent the app from starting, and `core/session.py:26-37` slims the persisted queue to 200 entries.
- **The Bottle route capture is well engineered**: the custom routes are installed *synchronously* before the server starts serving (`main.py:61-86` → `webview/http.py:141-147`), and the router is recompiled so the custom dynamic routes win over pywebview's catch-all (`main.py:466-476`).

---

### 4. Coverage gaps

- **The real app was never run** (per the ground rules: "Never run the real app"). All Windows-behaviour claims about WebView2, pystray and the Win32 mutex come from reading the installed sources (`webview/platforms/winforms.py`, `core/tray.py`) plus isolated probes; the WebView2-specific consequences (e.g. whether an orphaned `msedgewebview2.exe` survives `os._exit(3)`) are **not** verified.
- **The `sessionStorage` reset across a WebView2 process restart** (F-9) follows standard browser semantics (sessionStorage is per browsing context and is not persisted), but it was not observed on a live WebView2. Verification would need a run with a broken bridge and DevTools (`NEDOTIFY_DEVTOOLS=1`).
- **`PRAGMA wal_checkpoint(TRUNCATE)` blocking for up to `busy_timeout=30000`** during shutdown (F-8) is a hypothesis: the code path is confirmed, but the blocking was not observed (it requires a concurrent writer at exactly that moment).
- **The `sqlite3.ProgrammingError` on in-flight provider tasks after `db.close()`** (F-8) is a hypothesis for the same reason — the ordering is confirmed, the observable failure is not.
- **The proxy's in-flight request threads not being joined** (`core/proxy.py:425`) was not stress-tested; the window is narrow (8 teardown steps between `proxy.stop()` and `db.close()`).
- **The `core/api.py` `_emit` thread-per-call pattern** (`core/api.py:1148`) was reviewed for unbounded growth but not measured under an emit storm.
- **`core/audio/engine.py`** was reviewed by structure only (it owns no threads, timers or file handles of its own — everything is callback-driven), so it produced no findings; the deeper playback behaviour belongs to WN-17.
- **The `install_macos_assets` route** (`core/ui_assets.py`, invoked from `main.py:425`) was not reviewed in depth; it only affects what the fixed HTTP port exposes (F-1/F-2).
- **`services/zapret_service.py`** was reviewed only for its subprocess lifecycle (`start`/`stop`/`auto_update_in_background`); the network-bypass behaviour itself belongs to WN-26.

---

### 5. Architecture improvements (ARCH)

These are **not** defects — they are engineering improvements without a proven failure.

- **ARCH-1 — One authoritative shutdown owner.** The shutdown contract is currently split across three owners with no single authority: `main.py` (session save + instance lock + `sys.exit`), `AppCore.cleanup()` (every subsystem except the tray and the bridge executors) and `AppApi.cleanup()` (tray + search/prefetch executors). `AppCore.cleanup()` does **not** call `AppApi.cleanup()`, and `AppApi.cleanup()` does **not** call `AppCore.cleanup()`; `main.py` is the only place that calls both, and only on **one** of the two exit paths (F-5). Proposal: make `AppCore` the single owner of `AppApi` (it already is, via `AppApi.__init__` → `self._core.api = self`, `core/api.py:347`), give `AppCore.cleanup()` a final `self.api.cleanup()` step, and reduce `main.py` to `try: … finally: app_core.cleanup()`.
- **ARCH-2 — Collapse the three exit paths into one.** Paths P1/P3 (normal close, bridge-free close) already converge; P4/P5 (watchdog) do not. A single `def _shutdown(reason)` that (a) saves the session, (b) runs `app_core.cleanup()`, (c) releases the instance mutex, and (d) exits with the right code would remove the divergence that produced F-5, F-6 and F-7 in one go.
- **ARCH-3 — The circular `AppCore` ↔ `AppApi` ownership.** `AppApi.__init__` writes `self._core.api = self` (`core/api.py:347`) and `AppCore.cleanup()` then reaches back into the API (`core/app.py:530-531`, `getattr(self, 'api', None) and hasattr(self.api, 'flush_listening')`). The attribute is not declared in `AppCore.__init__`, so the contract is implicit. Declaring `self.api: Optional["AppApi"] = None` in `AppCore.__init__` and having `AppCore` own the API's lifetime would make the dependency explicit and remove the `getattr` guard.
- **ARCH-4 — A lifecycle registry instead of a hand-written cleanup list.** `AppCore.cleanup()` is a 78-line ordered script of `if getattr(self, "x", None): _step("x.stop", …)`. A tiny `Resource`/`Closable` protocol with an ordered registry (acquire → register → release in reverse order) would make the "released on **every** exit path" property structural rather than something a reader has to verify by hand — and would have caught F-5 and F-8 automatically.
- **ARCH-5 — Replace the "wait for `loaded`" watchdog with a real readiness handshake.** The backend and the frontend currently each implement their own, incompatible notion of "the app is up" (`main.py:484` vs `ui/web_new_v2/js/main.js:377-388`). A single explicit contract — e.g. the frontend calls `api.on_bridge_ready()` once `window.pywebview.api` is available, and the backend's watchdog waits for *that* — would remove F-9 and make the 35 s budget meaningful.
- **ARCH-6 — Move the app off a shared global port and onto an explicit, verified origin.** `webview.start(http_port=…)` with an app-chosen free port, plus a post-start assertion that the bound socket is the app's own, removes both F-1 and F-6 and makes the `/__aura_close` fallback (`main.py:417-480`) safe by construction. The same applies to `core/proxy.py`'s pattern of a random port + a per-session token — the pywebview server should use the same discipline.
- **ARCH-7 — Make the network bootstrap a first-class, reversible component.** The DNS fallback, the excepthooks and the `bottle.run` capture are all process-wide and irreversible (F-10). A `core/net_bootstrap.py` exposing `install()` / `restore()` (keeping `_ORIG_GETADDRINFO`, `_ORIG_BOTTLE_RUN`, `_ORIG_EXCEPTHOOK`) would make the behaviour testable, make the DoH fallback a user setting rather than a silent default, and let the SSRF guard's cost (F-3) be bounded by an explicit policy.
- **ARCH-8 — Turn the "eager import" graph into an explicit startup budget.** `tools/bench/import_chains.py` already produces the numbers; the 154 ms `yt_dlp` edge (F-11) and the eager DB/proxy start could be guarded by a perf test in `tools/bench` that fails the build when `import main` exceeds a threshold. That keeps the startup cost from silently regressing as more providers are added.
