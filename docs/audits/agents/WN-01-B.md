## AREA WN-01 — Process bootstrap, startup/shutdown, packaging — ROLE B

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

| File | Lines read | Notes |
|---|---|---|
| `main.py` | 1–584 (whole file) | bootstrap, DoH patch, mutex, watchdog, route install, shutdown |
| `setup_pyinstaller.spec` | 1–111 (whole file) | datas / hiddenimports / excludes / EXE |
| `installer.iss` | 1–92 (whole file) | installer sections, registry, uninstall |
| `requirements.txt` | 1–25 (whole file) | runtime pins |
| `requirements-dev.txt` | 1–2 (whole file) | dev pins |
| `run_tests.py` | 1–12 (whole file) | pytest delegate |
| `pytest.ini` | 1–5 (whole file) | testpaths / markers / addopts |

**Callees traced into other areas** (defects inside them are attributed to the owning area, not duplicated here)

- `core/app.py::AppCore.__init__` / `.cleanup()` (WN-02) — read L91–186, L508–586.
- `core/api.py::AppApi.__init__` / `.cleanup()` / `.set_window` (WN-03/WN-04) — read L342–459, L470–600, L614–627.
- `core/proxy.py::LocalProxyManager` (WN-11) — read L1259–1334. `core/proxy.py::ThreadingHTTPServer` L421–447.
- `core/tray.py::TrayIcon._resolve_default_icon_path` (WN-16) — read L1–80.
- `services/zapret_service.py::find_binary` (WN-26) — read L222–291, L316–330, L730–759.
- `core/settings.py::sync_flush_now` / `flush` (WN-14) — read via grep (L298–520).
- `services/watchdog_service.py`, `services/lufs_scanner.py` (WN-25) — thread/daemon flags via grep.
- Third-party runtime contracts (read-only, installed in `.venv_win`): `webview/__init__.py` L70–219, `webview/http.py` L1–230, `webview/util.py` L44–90, `webview/window.py` L172–205 + L548–558, `webview/platforms/winforms.py` L13, `webview/platforms/edgechromium.py` L9–40.

**Environment facts established by direct execution (not assumed)**

- Interpreter: `.venv_win\Scripts\python.exe` = CPython 3.14.7 (AMD64).
- Installed: pywebview 5.4, pythonnet 3.1.0, bottle 0.13.4, PyInstaller 6.22.3, yt-dlp 2026.8.19, curl_cffi 0.16.3, numpy 2.5.3.
- `webview.settings` keys (runtime): `ALLOW_DOWNLOADS, ALLOW_FILE_URLS, IGNORE_SSL_ERRORS, OPEN_DEVTOOLS_IN_DEBUG, OPEN_EXTERNAL_LINKS_IN_BROWSER, REMOTE_DEBUGGING_PORT`. **`WEBVIEW2_RUNTIME_PATH` is not among them.**
- `http.server.HTTPServer.allow_reuse_address` = `True`, `wsgiref.simple_server.WSGIServer.allow_reuse_address` = `True`, `socketserver.TCPServer.allow_reuse_address` = `False` (stdlib default).
- `webview.DEFAULT_HTTP_PORT = 42001`.
- `webview/http.py:141-147` calls `bottle.run(app=app, server=..., port=..., quiet=...)` — **all keyword args**.
- `socket.create_connection` resolves via the module-global `getaddrinfo` → the patched resolver is on the path of every TCP connect in the process.
- `icon.ico` exists in the repo root (85 785 bytes) but is **not** in `extra_datas`.
- `zapret/` and `bin/` do **not** exist in the repo.
- `ui/web_new_v2` = 115 files / 11.2 MB; `ui/web_new_v2/covers` does not exist.
- Import cost (fresh process): `yt_dlp` 272 ms, `numpy` 90 ms, `webview` 76 ms, `core.app` 50 ms → `import main` ≈ 350–400 ms.
- `tests/test_build_and_brand.py` + `tests/test_settings_flush.py`: **50 passed, 1 skipped**.

---

### 2. Findings

#### F-WN-01-1  [P0] — `webview.settings['WEBVIEW2_RUNTIME_PATH'] = …` raises `KeyError` at import time: the app does not start on any machine where the pinned WebView2 IS installed

- **File:** `main.py:24-30` (also `main.py:19`)
- **Confirmed:** yes — reproduced empirically (see Reproduction).
- **Description:** The WebView2 "pin" block assigns a **new** key into `webview.settings`. In pywebview 5.4 `settings` is an `ImmutableDict` whose `__setitem__` raises `KeyError` for keys that do not already exist. The assignment is at module scope and is **not** wrapped in `try/except`, so it aborts the import of `main.py` → the process exits before `main()` is ever called.
- **Cause:** The code treats `webview.settings` as a free-form dict. It is not; it is a closed, pre-seeded mapping. The author assumed (as the surrounding comment implies) that setting a pywebview setting would make pywebview use that WebView2 runtime. In pywebview 5.4 **no code path reads `WEBVIEW2_RUNTIME_PATH`** (grep over the whole `webview` package returns zero hits), so the assignment was both illegal and semantically inert. The only part of the pin that can work is the neighbouring `os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER']` — and it is unreachable on exactly the machines the pin was written for, because the crashing line sits immediately before it.
- **Trigger conditions:** `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\151.0.4129.86\msedgewebview2.exe` exists. That is precisely the machine class the comment describes ("151.0.4129.93 hangs bridge injection … 151.0.4129.86 works"). On every other machine the `os.path.exists` guard is `False`, the whole block is skipped, and the app starts — which is why the defect is invisible on most machines and fatal on the reference machine.
- **User impact:** Total launch failure. No window, no log file entry (the `RotatingFileHandler` is installed at `main.py:110`, *after* the crash), no error dialog — the process simply exits with a traceback on stderr, which in the `console=False` build goes to `os.devnull`.
- **Evidence:**
  ```python
  # main.py:24-30
  _PINNED_WEBVIEW2 = os.path.join(
      os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
      'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
  )
  if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2   # <-- KeyError
      os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2
  ```
  ```
  .venv_win\Lib\site-packages\webview\util.py:64
       raise KeyError(f"Cannot add new key '{key}'. Only existing keys can be modified.")
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -c "import webview; webview.settings['WEBVIEW2_RUNTIME_PATH']='X'"` → `KeyError: "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."` Full import reproduction (scratch script, `os.path.exists` faked to report the pinned path as present):
  ```
  File "...\main.py", line 29, in <module>
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2
  KeyError: "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."
  ```
  On this machine the pinned folder is absent (`Application\` contains `155.0.4283.60`, `155.0.4283.62`), so the guard is `False` and the app starts — i.e. the crash is version-pinned, not machine-pinned.
- **Suggested fix:** Delete the `webview.settings[...]` assignment (it is dead configuration) and keep only the `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` env var, which the WebView2 loader honours on its own. If a pywebview-level pin is genuinely wanted, it must be expressed through a key pywebview actually consumes, or through the WebView2 loader env vars only.
- **Fix side effects:** None for the app. Removing the assignment does not change the runtime behaviour on machines where the pin does not fire (the key was never read). On machines where it does fire, the env-var override then actually takes effect — which is the original intent, but should be re-validated on the "151.0.4129.93 hangs bridge injection" machine.
- **Discovered by:** B

---

#### F-WN-01-2  [P1] — `private_mode=False` silently pins the pywebview HTTP server to the fixed port 42001: predictable local surface, and a blank/bridge-less app when the port is taken

- **File:** `main.py:555` (also `main.py:544-550`)
- **Confirmed:** yes — the pywebview code path was read and traced; the port value was read from the installed package.
- **Description:** `webview.start(http_server=True, …, private_mode=False, …)` does not pass `http_port`. In pywebview 5.4, `private_mode=False` selects a **fixed** port instead of a random one:
  ```python
  # webview/__init__.py:191-193
  if (http.global_server is None) and (http_server or has_local_urls):
      if not _state['private_mode'] and not http_port:
          http_port = DEFAULT_HTTP_PORT          # = 42001
  ```
  So the app's whole UI **and** the pywebview JS-bridge HTTP endpoint (`POST /js_api/<uuid1>`, served with `Access-Control-Allow-Origin: *`) are bound to a well-known port. `main.py` never passes `http_port=0`, so the random-port path (`_get_random_port()`) is never taken.
- **Cause:** `private_mode` is being used for two unrelated purposes — "persist the WebView2 profile" (the actual intent, given `storage_path=~/.nedotify/webview2_data`) and, as a side effect in pywebview, "use the default fixed HTTP port". The two are silently coupled inside pywebview and nothing in `main.py` records the coupling.
- **Trigger conditions:**
  1. *Port occupied* — anything already listening on `127.0.0.1:42001`. `start_global_server` runs inside a **daemon thread** (`webview/http.py:141-147`), so the `OSError [WinError 10048]` from `bind` is swallowed by the thread excepthook; `http.global_server` stays `None`. `window._initialize()` is then called without a server, `_url_prefix` is `None`, `js_api_endpoint` is `None`, and `_resolve_url()` returns the bare local path — the window loads without a bridge. `main.py:482`'s watchdog then waits 35 s, respawns the app (`NEDOTIFY_RESTART_COUNT=1`), the child hits the same occupied port, waits another 35 s and gives up ("showing overlay, no more respawns"). Net user-visible result: a window that never becomes interactive.
  2. *Two Windows sessions on one machine* — the single-instance mutex is `Local\` (per-session, `main.py:260`), so a second session/RDP/fast-user-switching instance is allowed to start, but the HTTP port is per-machine. The second instance hits case (1).
  3. *Local attacker* — `wsgiref.simple_server.WSGIServer.allow_reuse_address = 1` (verified `True`), i.e. `SO_REUSEADDR`, which on Windows allows a second process to bind `127.0.0.1:42001` and take new connections. The bridge uid is `str(uuid.uuid1())` — time+MAC derived, not a CSPRNG token.
- **User impact:** (a) the app silently fails to become usable when 42001 is taken — a 70-second hang followed by a dead window; (b) the app's UI and bridge are reachable at a fixed, guessable address by any local process.
- **Evidence:**
  ```python
  # main.py:555
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  ```
  ```
  webview/__init__.py:70      DEFAULT_HTTP_PORT = 42001
  webview/__init__.py:192-193 if not _state['private_mode'] and not http_port: http_port = DEFAULT_HTTP_PORT
  webview/http.py:127-129     bottle.response.set_header('Cache-Control', ...)   # ui served from here
  webview/http.py:104-108     Access-Control-Allow-Origin: '*'                  # bridge endpoint
  ```
- **Reproduction / verification:** (a) `Get-Content .venv_win\Lib\site-packages\webview\__init__.py | Select-Object -Skip 188 -First 8` shows the port selection; (b) `netstat -ano | findstr :42001` before launching — if a listener exists, the app starts with a non-functional bridge; (c) `python -c "import socket;s=socket.socket();s.bind(('127.0.0.1',42001));s.listen(1)"` in another terminal, then launch the app → observe the 35 s + 35 s watchdog cycle and the log lines `[startup] bridge not initialized after 35s; reloading (real restart)` / `[startup] bridge still not initialized after 1 auto-restart; showing overlay, no more respawns.`
- **Suggested fix:** Pass an explicit `http_port=0` (or a per-run ephemeral port) to `webview.start()` so the server never uses a fixed port, and keep `private_mode=False` purely for profile persistence. Do not depend on pywebview's `private_mode` → `DEFAULT_HTTP_PORT` coupling.
- **Fix side effects:** The UI is then served from a random port; anything that hard-codes `42001` (docs, the `nedotify-run` skill, bookmarks) must be updated. Because the app already loads the UI through pywebview's local server, nothing in the frontend depends on the port value.
- **Discovered by:** B

---

#### F-WN-01-3  [P1] — Process-wide `socket.getaddrinfo` monkey-patch: no opt-out, no scope limit, up to ~6 s of blocking per DNS failure on the caller's thread, and it leaks the queried names to any environment proxy

- **File:** `main.py:160-230` (install at `main.py:225` and `main.py:227-230`)
- **Confirmed:** yes — the stdlib source of `socket.create_connection` was read; the `https_proxy` interaction is derived from `urllib.request`'s `ProxyHandler` + `Request.set_proxy` semantics.
- **Description:** `_enable_doh_fallback()` replaces `socket.getaddrinfo` **process-wide** at import time. Because `socket.create_connection` resolves through the module-global `getaddrinfo`, this puts the patched resolver on the path of *every* TCP connection made by *every* library in the process — `requests`/`urllib3`, `http.client`, `yt-dlp`, `curl_cffi`, the Discord RPC client, Last.fm, iTunes, the local proxy's outbound fetches, and the SSRF guard in `core/api.py:145` / `utils/url_safety.py:25`. On a `gaierror` the patched resolver performs up to **three** HTTPS requests with `timeout=2.0` each and then raises — i.e. up to ~6 s of *synchronous blocking plus three TLS handshakes* on whichever thread happened to make the call.
- **Cause:** The fallback was designed as a narrow escape hatch for a blocked ISP resolver, but it is installed as a global interpreter-wide patch with no feature flag, no env-var opt-out, no thread-scoping, and no request classification. Its cost model (a 6 s worst case) was designed for a rare event, but in the exact scenario it exists for — DNS is blocked — *every* resolution failure takes the slow path.
- **Trigger conditions:**
  1. Any host the system resolver cannot resolve. The repo already documents the cost: `core/api.py:93-98` — *"main.py patches socket.getaddrinfo with a DoH fallback over 3 endpoints at 2s each, so a single unresolvable host could block a proxy thread for ~6s"*.
  2. **`https_proxy`/`http_proxy` set in the environment.** The DoH requests themselves go through `urllib.request.urlopen`, which honours the proxy environment. In that case (i) the DNS query names (`?name=<host>`) are sent to the proxy operator in cleartext in the URL path — the very leak DoH was supposed to prevent, and (ii) the fallback becomes useless, because the proxy hostname itself has to be resolved through the patched resolver.
  3. The re-entrancy guard (`main.py:195-196`) raises a *fabricated* `socket.gaierror("DoH fallback busy resolving …")` in place of the original error, so the real `EAI_NONAME`/errno diagnosis is lost from every library that inspects the exception.
- **User impact:** Playback stalls of up to 6 s per unresolvable host inside proxy/download threads; yt-dlp extraction retries multiply the stall; the user's network activity (queried hostnames) is handed to an environment proxy the user may not know is configured; diagnostics in `app.log` lose the true DNS error.
- **Evidence:**
  ```python
  # main.py:180-225 (abridged)
  def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
      try:
          return _orig_getaddrinfo(host, port, family, type, proto, flags)
      except socket.gaierror:
          pass
      ...
      for doh_url in [f"https://1.1.1.1/dns-query?name={host}&type=A", ...]:
          try:
              ctx = ssl.create_default_context()
              req = urllib.request.Request(doh_url, headers={"accept": "application/dns-json", ...})
              with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp:
                  ...
          except Exception:
              continue
      raise socket.gaierror(f"All DoH endpoints failed for {host!r}")
  ...
  socket.getaddrinfo = _doh_getaddrinfo      # main.py:225
  ```
  ```
  # CPython 3.14 socket.py, create_connection:
  for res in getaddrinfo(host, port, 0, SOCK_STREAM):     # module global -> the patch
  ```
- **Reproduction / verification:** `python -c "import socket,inspect; print(inspect.getsource(socket.create_connection))"` shows the module-global lookup. To see the latency without leaving the machine: install the patch from `main.py` with a `socket.getaddrinfo` that raises `gaierror` and time `socket.create_connection(("nonexistent.invalid", 443))` — expect three 2 s timeouts. To see the proxy leak: `set HTTPS_PROXY=http://proxy.invalid:8080` and observe that `urllib.request.urlopen` resolves `proxy.invalid` instead of `1.1.1.1`.
- **Suggested fix:** Make the fallback opt-in and narrow: (a) gate it behind an env var (`NEDOTIFY_DOH=1`) or a settings toggle; (b) scope it to the app's own outbound clients (a dedicated `urllib3`/`requests` resolver) instead of patching the stdlib; (c) use a `socket.getaddrinfo` wrapper that preserves the original exception on failure and caches negative results with a short TTL; (d) build the DoH request with an opener that has `ProxyHandler({})` so the fallback never routes through an environment proxy.
- **Fix side effects:** Turning it off by default changes behaviour on the blocked-ISP networks the feature was written for — that needs a staged rollout (opt-in plus a clear "DNS problems?" affordance). Scoping it to the app's clients means third-party libraries (yt-dlp in particular) lose the fallback unless they are configured explicitly.
- **Discovered by:** B

---

#### F-WN-01-4  [P2] — The single-instance lock is validated by name only: any local process can squat the mutex and permanently block launches, and the second launch dies silently instead of surfacing the running window

- **File:** `main.py:249-303` (mutex at `main.py:260-263`)
- **Confirmed:** yes — code read; the "no identity validation" and "silent exit" properties are directly readable. The squatting scenario is a hypothesis about *another* process's behaviour, not a runtime observation.
- **Description:** The guard creates the named mutex `Local\NeDotify_App_Single_Instance_Mutex` and, if `GetLastError() == ERROR_ALREADY_EXISTS`, calls `sys.exit(0)`. The decision is based **only on the existence of the name**. There is no PID, no process start time, no image path and no owner validation — the standard defence against mutex squatting.
- **Cause:** The lock is used as a *flag*, not as an *identity token*. Any process in the same session that calls `CreateMutexW` with that name — including a buggy installer, a stale helper, or an unrelated program that picked the same name — makes the mutex "exist"; NeDotify then refuses to start. Because the mutex is released by the OS when the owner dies, a *crashed* NeDotify does not block the next launch, so this only bites while the squatting process is alive.
- **Trigger conditions:** A third process holds `Local\NeDotify_App_Single_Instance_Mutex`. Additionally, on the **normal** path the second launch is terminated with `sys.exit(0)` and **no user feedback**: the running window is not raised, not focused, and no message is shown. The user double-clicks the shortcut and *nothing happens*.
- **User impact:** A local process can make NeDotify unlaunchable for the duration of its own lifetime; the everyday "the app is already running" case is indistinguishable from "the app did not start".
- **Evidence:**
  ```python
  # main.py:260-263
  _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\NeDotify_App_Single_Instance_Mutex")
  if _INSTANCE_MUTEX and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
      logging.info("[startup] Another instance of NeDotify is already running; exiting cleanly.")
      sys.exit(0)
  ```
- **Reproduction / verification:** Squat the name from any account on the same session:
  ```powershell
  $m = [System.Threading.Mutex]::new($false, 'Local\NeDotify_App_Single_Instance_Mutex')
  # leave $m alive, then launch NeDotify -> the app exits immediately, window never appears
  ```
  For the silent-exit half: start NeDotify, launch it again → the second process exits with code 0 and no window is raised.
- **Suggested fix:** Validate the mutex owner before bailing (e.g. store PID + process start time in a companion file/section and compare), and on the "already running" path signal the live instance (a named event / `WM_` message / the existing `__aura_close`-style HTTP route) to raise and focus its window instead of exiting silently.
- **Fix side effects:** Identity validation adds a second synchronization object that can itself go stale (a crashed process leaves a stale PID file) — it must be validated with a start-time check, not a bare PID, or it will trade one hang for another. Raising the existing window requires the running instance to expose an activation channel (the `Local\` namespace already permits this).
- **Discovered by:** B

---

#### F-WN-01-5  [P2] — The shutdown path is not authoritative: `api.cleanup()` — the only code that stops the tray — is skipped on the watchdog restart path and on every exception path

- **File:** `main.py:506-539` (watchdog) vs `main.py:557-580` (normal); `core/api.py:446-459` (callee, WN-03)
- **Confirmed:** yes — code read on both sides.
- **Description:** There are three distinct exit paths and they do not agree:
  1. **Normal close** (`main.py:573-580`): `_release_instance_lock()` → `app_core.cleanup()` → `api.cleanup()` → `sys.exit(0)`.
  2. **Watchdog restart** (`main.py:514-539`): `_release_instance_lock()` → `subprocess.Popen` → `settings.sync_flush_now()` → `app_core.cleanup()` → `settings.sync_flush_now()` → `os._exit(3)` — **`api.cleanup()` is never called**.
  3. **Exception anywhere in `main()`** (e.g. `AppCore()` raising, `webview.start()` raising because the .NET runtime is missing): the exception escapes `main()`, hits `sys.excepthook` (`main.py:141`), and **no cleanup runs at all**.
  `AppApi.cleanup()` is the *only* place the pystray tray is stopped (`core/api.py:449-452`), and `AppCore.cleanup()` has no tray step of its own.
- **Cause:** Cleanup is distributed over two objects with no owner that guarantees "teardown happened exactly once". The watchdog path was written as an emergency branch and duplicates the flush/cleanup sequence by hand instead of calling a shared `shutdown()` routine.
- **Trigger conditions:**
  - Watchdog restart: the JS bridge never comes up within 35 s (WebView2 init hang — the exact scenario the watchdog exists for). The tray icon and the `SearchWorker`/`StreamWarmup` thread pools are never shut down before `os._exit(3)`.
  - Exception path: `webview.start()` calls `guilib.initialize()` which does `import clr` (`webview/platforms/winforms.py:13`). If the .NET runtime is unavailable, `webview.start()` raises → `main()` aborts → the proxy server thread, the downloader pool, the Discord RPC client, the cache-cleanup thread and the DB connection are all abandoned mid-flight, and the settings writer thread's pending writes are only flushed by the `atexit` handler in `core/settings.py:313` (which `os._exit` skips but a normal exception does not).
  - The mutex is released in `on_closed` (`main.py:406-408`) and again at `main.py:574`, i.e. **before** `app_core.cleanup()` finishes — a second launch can start while the first still holds the SQLite connection and the proxy port.
- **User impact:** Leaked tray icons and thread pools on the watchdog path; abandoned resources and possibly-unsaved settings on the exception path; a restart race in which two processes briefly share `~/.nedotify/nedotify_storage.db`.
- **Evidence:**
  ```python
  # main.py:514-539 (watchdog) -- note: no api.cleanup()
  _release_instance_lock()
  subprocess.Popen(restart_args, creationflags=creation_flags, close_fds=True, env=env)
  try: app_core.settings.sync_flush_now()
  except Exception: ...
  try: app_core.cleanup()
  except Exception: ...
  try: app_core.settings.sync_flush_now()
  except Exception: ...
  os._exit(3)
  ```
  ```python
  # main.py:573-580 (normal) -- the only path that calls api.cleanup()
  _release_instance_lock()
  app_core.cleanup()
  try:
      api.cleanup()
  except Exception:
      logging.debug("_startup_watchdog: suppressed exception", exc_info=True)
  sys.exit(0)
  ```
  ```python
  # core/api.py:446-452 -- the ONLY tray stop in the codebase
  def cleanup(self):
      try:
          if getattr(self, "_tray", None):
              self._tray.stop()
  ```
- **Reproduction / verification:** Force the watchdog path by making the bridge fail: set `NEDOTIFY_RESTART_COUNT=0`, start the app with an occupied `127.0.0.1:42001` (see F-WN-01-2) so the window never gets a bridge → after 35 s the watchdog respawns. Observe in `~/.nedotify/logs/app.log` that `Cleaning up AppCore resources...` appears but no tray-stop log follows, and the respawned child starts while the parent's teardown is still running. For the exception path, temporarily make `webview.start` raise (e.g. `PYTHONNET_RUNTIME` pointing at a missing runtime) and confirm no `Cleaning up AppCore resources...` line is written.
- **Suggested fix:** Introduce one `shutdown(reason)` routine that is idempotent and owns the whole teardown order (`api.cleanup()` → `app_core.cleanup()` → release mutex last), and call it from all three paths plus a `try/finally` around the body of `main()`. Release the instance lock **after** teardown, not in `on_closed`.
- **Fix side effects:** Moving the mutex release after teardown widens the window in which a second launch is refused (the user must wait for the first instance to finish cleaning up) — that is the correct trade-off, but it must be paired with the "raise the existing window" behaviour from F-WN-01-4 so a double-click is never a no-op.
- **Discovered by:** B

---

#### F-WN-01-6  [P2] — `icon.ico` is not bundled, so the packaged app has no window icon and the tray silently falls back to `logo.png`

- **File:** `setup_pyinstaller.spec:27-30` and `:110`; consumers at `core/tray.py:37-45` and `core/api.py:588-592`
- **Confirmed:** yes — `icon.ico` exists in the repo root; the spec's `extra_datas` does not include it; the consumers resolve it against the bundle root.
- **Description:** The spec embeds `icon.ico` as the *executable resource* (`icon='icon.ico'`), which is correct for the taskbar/Explorer icon, but two runtime code paths load the **file** from the bundle root and are not given the file:
  ```python
  # core/tray.py:37-45
  def _resolve_default_icon_path(self) -> str:
      base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
      ico_path = os.path.join(base, "icon.ico")
      if os.path.exists(ico_path): return ico_path
      png_path = os.path.join(base, "ui", "web_new_v2", "assets", "logo.png")
      if os.path.exists(png_path): return png_path
      return ico_path
  ```
  ```python
  # core/api.py:588-592
  import clr
  clr.AddReference('System.Drawing')
  from System.Drawing import Icon
  icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico")
  if os.path.exists(icon_path):
      self._window.native.Icon = Icon(icon_path)
  ```
  In the frozen build `sys._MEIPASS` is the extraction directory, so the path is `<_MEIPASS>\icon.ico` — which the spec never creates.
- **Cause:** The spec's `datas` list was assembled from the UI tree and the `ytmusicapi` package; the repo-root `icon.ico` was treated as build-time-only metadata (for the `EXE(icon=…)` argument) even though two runtime paths need the bytes at runtime.
- **Trigger conditions:** Any packaged build.
- **User impact:** The native window icon is never applied (the `if os.path.exists` guard silently skips it) → the taskbar shows the default PyInstaller/Python icon; the system-tray icon silently degrades from `icon.ico` to `ui/web_new_v2/assets/logo.png` (a different image), or to a generated purple square if that is missing too. The `clr`/`System.Drawing` code path runs in a daemon thread whose only outcome is a cosmetic difference — the user cannot tell that the intended icon was lost.
- **Evidence:**
  ```python
  # setup_pyinstaller.spec:27-30
  extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')] + collect_data_files('ytmusicapi')
  for extra_folder in ['zapret', 'bin']:
      if os.path.exists(extra_folder):
          extra_datas.append((extra_folder, extra_folder))
  ```
  ```
  PS> Test-Path icon.ico      -> True   (85785 bytes, repo root)
  PS> Select-String -Path setup_pyinstaller.spec -Pattern "icon.ico"  -> only line 110 (icon='icon.ico')
  ```
- **Reproduction / verification:** Build with `pyinstaller setup_pyinstaller.spec`, then check the bundle: `Get-ChildItem "$env:TEMP\_MEI*" -Filter icon.ico` → not found; and at runtime `os.path.exists(os.path.join(sys._MEIPASS,'icon.ico'))` → `False`. Cheaper static check: assert that `'icon.ico'` appears in the spec's `datas`, not only in `EXE(icon=…)` (no such test exists today).
- **Suggested fix:** Add `('icon.ico', '.')` to `extra_datas` (or `('icon.ico', 'ui/web_new_v2')` if the runtime path is changed to match), and add a build-time test asserting every file the app opens from the bundle root is present in `datas`.
- **Fix side effects:** +85 KB in the bundle. The `EXE(icon=…)` resource and the file can drift out of sync — a single source (the datas entry plus the `icon=` argument pointing at the same file) keeps them consistent.
- **Discovered by:** B

---

#### F-WN-01-7  [P2] — Neither the executable nor the installer is code-signed, and the spec explicitly disables UPX because of antivirus heuristics

- **File:** `setup_pyinstaller.spec:100-101`, `:108`; `installer.iss:6-28` (no `[Setup] SignTool=` / `SignTool=` directive)
- **Confirmed:** yes — the spec sets `codesign_identity=None` and the installer has no signing directive.
- **Description:** The shipped artefacts are unsigned. The spec's own comment shows the author is aware of antivirus sensitivity ("UPX on a music-downloader exe trips antivirus heuristics and can break WebView2 DLL loading") but the mitigation chosen was to not compress rather than to sign. `installer.iss` likewise has no `SignTool=` / `SignedUninstaller=yes` / `AppPublisher` verification.
- **Cause:** Signing requires a code-signing certificate and a secret, which the project does not have; the pipeline therefore has no provenance story for the binaries it distributes.
- **Trigger conditions:** Every installation on every machine.
- **User impact:** (a) SmartScreen shows "Windows protected your PC" with an unknown-publisher warning on every fresh install — users must click "More info → Run anyway"; (b) antivirus engines have no publisher reputation to lean on for a binary whose job is downloading and launching media files and an elevated `winws.exe`, so heuristic quarantine is likely; (c) users cannot verify the provenance of a binary that handles their Yandex/Spotify OAuth tokens; (d) `installer.iss:18` sets `PrivilegesRequired=lowest` so no UAC prompt appears, which means the "unverified publisher" warning is the *only* signal the user gets.
- **Evidence:**
  ```python
  # setup_pyinstaller.spec:100-101, 108
  upx=False,  # UPX on a music-downloader exe trips antivirus heuristics and can break WebView2 DLL loading
  ...
  codesign_identity=None,
  ```
  ```
  # installer.iss [Setup] section — grep for AppId|AppMutex|SignTool|Architectures returns ZERO hits
  ```
- **Reproduction / verification:** Build the installer and run `Get-AuthenticodeSignature .\dist\NeDotify_Setup.exe` → `Status: NotSigned`. On a clean Windows account, launching it triggers the SmartScreen interstitial.
- **Suggested fix:** Add an Authenticode signing step to the release pipeline (`signtool sign /tr … /fd SHA256 …`) for both `dist\NeDotify.exe` and `dist\NeDotify_Setup.exe`, and add `SignedUninstaller=yes` + `SignTool=` to `installer.iss`. Until a certificate exists, publish the SHA-256 of the artefacts in the release notes so users have a verifiable fingerprint.
- **Fix side effects:** Signing requires a certificate (OV/EV) and a CI secret; an expired certificate invalidates an already-distributed build's reputation. Timestamping (`/tr`) must be used so signatures survive certificate expiry.
- **Discovered by:** B

---

#### F-WN-01-8  [P2] — `installer.iss` has no `AppId`, no `AppMutex`, and uninstalls with `filesandordirs` over the whole `{app}` tree

- **File:** `installer.iss:6-28` (`[Setup]`), `installer.iss:61-65` (`[Run]`, `[UninstallDelete]`)
- **Confirmed:** yes — the file was read in full and grepped.
- **Description:** Three packaging defects in one file:
  1. **No `AppId`.** Inno Setup 6 auto-generates one from `AppName` + `AppPublisher` + `DefaultDirName`. Any change to `AppName` (`"NeDotify"` → `"NeDotify Beta"`) or to `DefaultDirName` silently produces a *different* app identity → Inno installs a second, parallel copy, the old uninstaller is orphaned, and `UninstallDelete` on `{app}` then removes the new install.
  2. **No `AppMutex`.** The app *has* a well-named mutex (`Local\NeDotify_App_Single_Instance_Mutex`, `main.py:260`), and Inno Setup's `AppMutex=` directive exists exactly to detect it during install/uninstall. Without it, an upgrade over a running instance is only detected by `CloseApplications=yes` (Restart Manager), which is best-effort.
  3. **`[UninstallDelete] Type: filesandordirs; Name: "{app}"`** deletes the entire install directory recursively on uninstall — including anything the user or a third party placed there, not just the files Inno installed. Inno's own documentation warns against `filesandordirs` on the app directory for exactly this reason.
- **Cause:** The installer was written as a minimal, hand-rolled script with no identity/upgrade story, and the uninstall step was chosen for convenience ("leave nothing behind") instead of precision.
- **Trigger conditions:** (1) any rename of `AppName`/`DefaultDirName`; (2) upgrading while the app is running — the new `[Run]` entry (`installer.iss:62`, `nowait postinstall`) launches `NeDotify.exe` immediately, the running instance still holds the mutex, the new process hits `ERROR_ALREADY_EXISTS` and `sys.exit(0)`s → **the user clicks "Finish" and nothing appears to happen**; (3) any uninstall where the user has put files under `{localappdata}\Programs\NeDotify`.
- **User impact:** Orphaned installs and a possible double-install; an upgrade that silently appears to do nothing; silent deletion of user-placed files in the install directory. The user's actual library (`~/.nedotify`) is *not* touched by the uninstaller, which is correct.
- **Evidence:**
  ```ini
  ; installer.iss:11-28 (excerpt) -- no AppId, no AppMutex
  DefaultDirName={localappdata}\Programs\NeDotify
  ...
  CreateUninstallRegKey=yes
  CloseApplications=yes
  RestartIfNeededByRun=no
  ```
  ```ini
  ; installer.iss:61-65
  [Run]
  Filename: "{app}\NeDotify.exe"; Description: "{cm:LaunchProgram,NeDotify}"; Flags: nowait postinstall skipifsilent

  [UninstallDelete]
  Type: filesandordirs; Name: "{app}"
  ```
- **Reproduction / verification:** `Select-String -Path installer.iss -Pattern "AppId|AppMutex"` → no hits. For (2): start NeDotify, run `NeDotify_Setup.exe` over it, and watch `~/.nedotify/logs/app.log` for `[startup] Another instance of NeDotify is already running; exiting cleanly.` immediately after the install completes. For (3): create `…\Programs\NeDotify\mynotes.txt`, uninstall, and check whether the file is gone.
- **Suggested fix:** Pin an explicit `AppId={{GUID}` (and keep it stable forever), add `AppMutex=NeDotify_App_Single_Instance_Mutex` (Inno appends `Local\` itself for a non-global name), and replace the blanket `[UninstallDelete]` with `Type: files; Name: "{app}\NeDotify.exe"` plus a `dirs` entry, or scope `filesandordirs` to a dedicated subdirectory the app owns.
- **Fix side effects:** Adding an explicit `AppId` changes the identity for existing installations — Inno will then treat the new build as a *new* product and install side-by-side on users who already have the app installed with the auto-generated id. That needs a migration step (or accepting the one-time parallel install). `AppMutex=` makes the installer detect the running app and offer to close it, which changes the upgrade UX.
- **Discovered by:** B

---

#### F-WN-01-9  [P3] — The spec bundles `zapret`/`bin` only if those folders exist relative to the process CWD; neither exists in the repo, so the bundling is dead code

- **File:** `setup_pyinstaller.spec:28-30`; consumer at `services/zapret_service.py:326` and `:740-746` (WN-26)
- **Confirmed:** yes — `Test-Path zapret` → `False`, `Test-Path bin` → `False`.
- **Description:** The spec tries to bundle two directories that do not exist in the repository:
  ```python
  for extra_folder in ['zapret', 'bin']:
      if os.path.exists(extra_folder):
          extra_datas.append((extra_folder, extra_folder))
  ```
  The guard is `False` for both, so **no zapret binary is ever packaged**. The paths are also *relative*, so the guard's result depends on the working directory from which `pyinstaller` is invoked — running the build from anywhere other than the repo root silently changes what gets bundled.
- **Cause:** The spec's asset list was written against an expected repository layout that the repository does not have. Nothing asserts the relationship between the layout and the spec.
- **Trigger conditions:** Every packaged build.
- **User impact:** The Zapret (DPI-bypass) feature has no bundled `winws.exe` in the installed product; it depends entirely on the runtime auto-download into `~/.nedotify/zapret`. `services/zapret_service.py:740-746` then searches `app_dir`, `cwd/bin`, `cwd/zapret` — all empty in an installed app — and returns `None`, so the feature reports "Файл winws.exe не найден." until the user triggers the update.
- **Evidence:**
  ```python
  # setup_pyinstaller.spec:28-30
  for extra_folder in ['zapret', 'bin']:
      if os.path.exists(extra_folder):
          extra_datas.append((extra_folder, extra_folder))
  ```
  ```
  PS> Test-Path zapret   -> False
  PS> Test-Path bin      -> False
  ```
  ```python
  # services/zapret_service.py:740-746
  candidates = [
      os.path.join(self.app_dir, "winws.exe"),
      os.path.join(self.app_dir, "zapret.exe"),
      os.path.join(self.app_dir, "bin", "winws.exe"),
      os.path.join(os.getcwd(), "bin", "winws.exe"),
      os.path.join(os.getcwd(), "zapret", "winws.exe")
  ]
  ```
- **Reproduction / verification:** `Test-Path zapret; Test-Path bin` in the repo root → `False`/`False`; then run `pyinstaller setup_pyinstaller.spec --log-level DEBUG` and grep the Analysis output for a `zapret` or `bin` datas entry → none.
- **Suggested fix:** Either drop the two entries and document that Zapret binaries are fetched at runtime, or make the asset list explicit and absolute (`os.path.join(SPECPATH, ...)`) with a build-time assertion that each referenced folder exists. `SPECPATH` should be used instead of the CWD for all relative paths in the spec.
- **Fix side effects:** Using `SPECPATH` changes the semantics of the existing `('ui/web_new_v2', 'ui/web_new_v2')` entries from "relative to CWD" to "relative to the spec file" — correct, but it will change behaviour for anyone currently building from a different directory.
- **Discovered by:** B

---

#### F-WN-01-10  [P3] — `requirements.txt` contradicts its own version policy (`yt-dlp` is uncapped) and `curl_cffi`'s floor overlaps the versions yt-dlp refuses

- **File:** `requirements.txt:1-14`
- **Confirmed:** yes — file read; yt-dlp's own metadata read from the installed distribution.
- **Description:** Two concrete defects:
  1. `yt-dlp[default]>=2026.8.19` has **no upper bound**, while the file header states: *"Versions are capped at the next major to keep installs reproducible while still allowing patch/minor updates. Bump caps deliberately, not silently."* yt-dlp is date-versioned and ships breaking extractor/behaviour changes in every release; an uncapped date-versioned dependency is the one dependency where "no cap" is most dangerous.
  2. `curl_cffi>=0.7.0,<1` permits `0.7.x`, `0.8.x` and `0.9.x`, which yt-dlp's own `curl-cffi` extra **explicitly excludes**: `curl-cffi!=0.6.*,!=0.7.*,!=0.8.*,!=0.9.*,<0.17,>=0.5.10`. The repo installs `curl_cffi` directly (not via the extra), so pip sees no conflict and happily keeps a version yt-dlp refuses to use for impersonation — exactly the failure the requirements comment is trying to prevent ("attempting impersonation, but no impersonate target is available").
- **Cause:** The dependency policy was written for semver-shaped packages and applied verbatim to a date-versioned one; the `curl_cffi` floor was set from the yt-dlp *extra*'s older wording rather than from the extra's current exclusion list.
- **Trigger conditions:** (1) any `pip install -r requirements.txt` on a machine where a newer yt-dlp exists — the installed version floats; (2) an environment that already has `curl_cffi` 0.7–0.9 satisfies the declared range and blocks the upgrade yt-dlp needs.
- **User impact:** Stream extraction can break with no code change and no commit (yt-dlp upstream extractor changes are routine); the "SoundCloud metadata fetches fail" symptom the comment describes can reappear after a dependency resolution.
- **Evidence:**
  ```
  # requirements.txt:5-9
  # Versions are capped at the next major to keep installs reproducible while
  # still allowing patch/minor updates. Bump caps deliberately, not silently.
  ...
  yt-dlp[default]>=2026.8.19
  ```
  ```
  # requirements.txt:14
  curl_cffi>=0.7.0,<1
  ```
  ```
  # installed yt-dlp metadata (Requires-Dist)
  "curl-cffi!=0.6.*,!=0.7.*,!=0.8.*,!=0.9.*,<0.17,>=0.5.10; ... extra == 'curl-cffi'"
  ```
- **Reproduction / verification:** `python -m pip install --dry-run -r requirements.txt` → shows yt-dlp floating to the newest release; `python -c "import importlib.metadata as m; print(m.metadata('yt-dlp').get_all('Requires-Dist'))"` → the exclusion list above.
- **Suggested fix:** Give `yt-dlp` an explicit ceiling (a dated pin, e.g. `yt-dlp[default]>=2026.8.19,<=2026.9.x`) and align the `curl_cffi` floor with yt-dlp's exclusion list (`curl_cffi>=0.10,<0.17`). Add a lock file (or `pip-tools`/`uv` output) with hashes so a build is reproducible.
- **Fix side effects:** A yt-dlp ceiling means extractor fixes published after the ceiling need a deliberate bump — that is the stated intent of the file header, but it must be paired with a scheduled bump process, otherwise the app silently ages into broken extraction.
- **Discovered by:** B

---

#### F-WN-01-11  [P3] — `socketserver.TCPServer.allow_reuse_address = True` at import time is a redundant global mutation of a stdlib base class

- **File:** `main.py:13-14`
- **Confirmed:** yes — the class attributes were read from the installed interpreter.
- **Description:** The bootstrap mutates a stdlib base class as its first executable statement:
  ```python
  import socketserver
  socketserver.TCPServer.allow_reuse_address = True
  ```
  Both servers the application actually runs already set the attribute in their own class bodies — `http.server.HTTPServer.allow_reuse_address` is `True` (used by `core/proxy.py::ThreadingHTTPServer`) and `wsgiref.simple_server.WSGIServer.allow_reuse_address` is `True` (used by pywebview's HTTP server). The base-class default is `False`. The patch therefore changes **nothing** for either server, and only alters the default for any *other* `socketserver.TCPServer` subclass that happens to be imported later in the process.
- **Cause:** The patch was written without checking that the subclasses already override the attribute — a global mutation applied "just in case", at import time, before any server exists.
- **Trigger conditions:** Always (import of `main`).
- **User impact:** None observed today. The risk is that the line reads as "SO_REUSEADDR is required for our servers" — and on Windows `SO_REUSEADDR` is precisely the flag that enables *port hijacking* by a second local process. A future maintainer who adds a server with a **fixed** port would silently inherit Windows' hijack-enabling semantics from a line whose only purpose was to be harmless.
- **Evidence:**
  ```
  PS> python -c "import http.server, wsgiref.simple_server, socketserver; print(http.server.HTTPServer.allow_reuse_address, wsgiref.simple_server.WSGIServer.allow_reuse_address, socketserver.TCPServer.allow_reuse_address)"
  True True False
  ```
  ```python
  # core/proxy.py:421-430 (callee) — already inherits HTTPServer.allow_reuse_address = 1
  class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
  ```
- **Reproduction / verification:** The `python -c` line above; then `python -c "import http.server, socketserver; socketserver.TCPServer.allow_reuse_address = True; print(http.server.HTTPServer.allow_reuse_address)"` → still `True` (the subclass attribute wins, the base patch is inert).
- **Suggested fix:** Delete `main.py:13-14`. If a specific server really needs a specific `allow_reuse_address`/`allow_reuse_port` policy, set it on that class (`core/proxy.py::ThreadingHTTPServer`), not on the stdlib base.
- **Fix side effects:** None — both servers already behave identically with and without the line.
- **Discovered by:** B

---

#### F-WN-01-12  [P3] — `main.py` has zero test coverage and is structurally untestable: five global side effects at import time

- **File:** `main.py:14`, `:53-86`, `:88-92`, `:99-117`, `:160-230`
- **Confirmed:** yes — the whole test tree was grepped for `import main`; the only hits are comments in `tests/test_api_audit_b.py`, `tests/test_build_and_brand.py` and `tests/test_settings_flush.py`.
- **Description:** Importing `main` performs, irreversibly and process-wide:
  1. `socketserver.TCPServer.allow_reuse_address = True` (`main.py:14`) — stdlib mutation.
  2. `bottle.run = _capture_bottle_run` (`main.py:84`) — stdlib/third-party function replacement.
  3. `logging.basicConfig(...)` with a `RotatingFileHandler` writing to `~/.nedotify/logs/app.log` (`main.py:104-117`) — reconfigures the root logger for the whole process and creates a directory in the user's profile.
  4. `sys.excepthook` / `threading.excepthook` replacement (`main.py:141-142`).
  5. `socket.getaddrinfo = _doh_getaddrinfo` (`main.py:225`).
  Because of these, `import main` cannot be done from a test without (a) touching `~/.nedotify`, (b) reconfiguring global logging, (c) patching the stdlib resolver for every other test in the same process, and (d) leaving `bottle.run` replaced. The result is that **the module that owns startup and shutdown has no tests at all**.
- **Cause:** All bootstrap logic lives at module scope instead of behind an explicit `Bootstrap`/`startup()` entry point with injectable dependencies. The nested-function style (`_acquire_instance_lock`, `_install_routes`, `_startup_watchdog` are closures over `app_core`, `window`, `api`) makes them impossible to call without constructing the whole application.
- **Trigger conditions:** Always; the effect on the test suite is that WN-01 defects (such as F-WN-01-1) ship undetected.
- **User impact:** The startup/shutdown sequence is the least verified part of the product. `tests/test_settings_flush.py:209-229` documents the watchdog contract by *re-implementing* the call order (`sync_flush_now() -> cleanup() -> sync_flush_now()`) instead of driving `main.py`'s code — the test passes even if `main.py` changes.
- **Evidence:**
  ```python
  # main.py:84
  _bottle.run = _capture_bottle_run
  ```
  ```python
  # main.py:104-117
  logging.basicConfig(
      level=logging.INFO, format=_LOG_FORMAT, datefmt='%H:%M:%S',
      handlers=[logging.StreamHandler(), RotatingFileHandler(os.path.join(_log_dir, 'app.log'), ...)],
  )
  ```
  ```python
  # tests/test_settings_flush.py:209-215
  def test_watchdog_pattern_flushes_before_db_close():
      """Document what main.py::_startup_watchdog relies on.
      The watchdog does sync_flush_now() -> cleanup() -> sync_flush_now() -> os._exit(3).
      This asserts each step works when driven in that order, and ...
      """
      sm, db = _manager()
  ```
- **Reproduction / verification:** `Select-String -Path tests\*.py -Pattern "import main|from main import"` → no executable hits (only docstring text). `Select-String -Path main.py -Pattern "^import|^from|bottle.run =|logging.basicConfig|sys.excepthook|socket.getaddrinfo ="` enumerates the import-time side effects.
- **Suggested fix:** Move every import-time side effect behind an explicit `configure_runtime()`/`Bootstrap` object invoked from `main()`, so `import main` is inert and the pieces (lock acquisition, route installation, watchdog, shutdown ordering) become unit-testable with fakes. At minimum, wrap the `bottle.run` and `socket.getaddrinfo` replacements so they can be installed and uninstalled.
- **Fix side effects:** A larger refactor of `main.py`. The DoH patch in particular must stay installed for the process lifetime, so it has to become an explicitly-managed global rather than an import side effect — that is the point of the refactor, but it touches every line that currently relies on the implicit ordering.
- **Discovered by:** B

---

#### F-WN-01-13  [P3] — The watchdog releases the single-instance mutex *before* spawning the respawn, so a third launch can steal the lock and kill the respawn

- **File:** `main.py:508-520`
- **Confirmed:** yes — code read; the race is a scheduling argument, not an observed crash.
- **Description:** The watchdog releases the instance mutex and only then spawns the replacement:
  ```python
  _release_instance_lock()
  subprocess.Popen(restart_args, creationflags=creation_flags, close_fds=True, env=env)
  ```
  The mutex is therefore unowned for the (small) window between the two calls. A user double-clicking the shortcut in that window — or any other launcher — creates the mutex first; the respawned child then sees `ERROR_ALREADY_EXISTS` and `sys.exit(0)`s, so **the watchdog's whole purpose (escaping the hang) is defeated** and the user is left with the hung original, which is about to `os._exit(3)`.
- **Cause:** The mutex was released early to avoid the child dying on `ERROR_ALREADY_EXISTS` (the comment at `main.py:508-513` explains this correctly), but the fix was "release then spawn" rather than "hand the lock over" (e.g. create the mutex with `bInitialOwner=True` and have the child inherit/duplicate the handle, or use a distinct "restart" mutex name for the respawn).
- **Trigger conditions:** A user click (or any process) during the ~millisecond gap between the release and the `Popen` completing — plus the parent is still alive and still holding the SQLite connection and the proxy port while the child starts.
- **User impact:** An intermittent "the app restarted and then nothing happened" failure, exactly in the scenario where the user is already suffering from a hung app. Additionally, for the duration of the parent's teardown the child and the parent both have `~/.nedotify/nedotify_storage.db` open.
- **Evidence:** quoted above; `main.py:508-513` comment: *"Release BEFORE spawning. The single-instance guard now runs at the very top of main(), so a child that starts while this process still holds the mutex sees ERROR_ALREADY_EXISTS and exits at once — the watchdog would then kill the app and start nothing, which is precisely the hang it exists to escape."*
- **Reproduction / verification:** Add a `time.sleep(0.5)` between the two lines in a scratch copy and launch a second instance in that window; the child logs `[startup] Another instance of NeDotify is already running; exiting cleanly.` and dies.
- **Suggested fix:** Spawn the child first with the lock still held and let the child wait for the mutex to become free (or pass a "restart token" so the child skips the mutex check once), instead of releasing before spawning. Alternatively use a second, dedicated "restart in progress" mutex to serialise restarts.
- **Fix side effects:** Spawning before releasing briefly keeps the mutex held by the parent while the child starts — the child must therefore tolerate a short wait, which adds up to the hang-detection budget. The `NEDOTIFY_RESTART_COUNT` cap (already present) keeps the loop bounded.
- **Discovered by:** B

---

#### F-WN-01-14  [P3] — Two startup/shutdown failure paths report through `print()` only, which is discarded in the packaged windowed build

- **File:** `main.py:330`, `main.py:571` (and `main.py:234`)
- **Confirmed:** yes — code read; the `sys.stdout` behaviour in a frozen windowed build was verified against the installed pywebview source.
- **Description:** Two error paths use `print()` instead of `logging`:
  ```python
  except Exception as e:
      print(f"Failed to restore session: {e}")     # main.py:330
  ...
  except Exception as e:
      print(f"Failed to save session: {e}")        # main.py:571
  ```
  The spec builds with `console=False` (`setup_pyinstaller.spec:104`). In a frozen windowed PyInstaller build `sys.stdout` is `None`/devnull, and pywebview explicitly replaces it: `webview/http.py:8-14` sets `sys.stdout = open(os.devnull, 'w')` for frozen apps. The messages therefore vanish. `main.py:234`'s `print("Starting NeDotify...")` is lost the same way.
- **Cause:** The bootstrap already installs a rotating file logger at `main.py:104-117`; these three call sites simply were not converted. The `logging` module is used everywhere else in the file.
- **Trigger conditions:** Any packaged build; and a session restore/save failure (a corrupt `~/.nedotify` session blob, a full disk, a closed DB) is exactly when the message matters.
- **User impact:** "Failed to restore session" / "Failed to save session" never appear in `~/.nedotify/logs/app.log`, so a user whose session is not being restored has no evidence and no diagnostic. The session is silently lost or silently not restored.
- **Evidence:**
  ```python
  # main.py:329-330
  except Exception as e:
      print(f"Failed to restore session: {e}")
  ```
  ```
  # webview/http.py:8-14
  if sys.platform == 'win32' and ('pythonw.exe' in sys.executable or getattr(sys, 'frozen', False)):
      if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
      if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
  ```
- **Reproduction / verification:** Launch a packaged build with a deliberately corrupted session file and check `~/.nedotify/logs/app.log` — the "Failed to restore session" line is absent. In a dev run (`python main.py`) the same line appears on the console, which is why the defect is invisible in development.
- **Suggested fix:** Replace the three `print()` calls with `logging.warning(...)` / `logging.info(...)`. The logger is configured at `main.py:104`, before any of them run.
- **Fix side effects:** None. The console output in dev becomes a log line instead of a bare print — which is the intended behaviour everywhere else in the file.
- **Discovered by:** B

---

### 3. Clean areas

- **Route registration ordering (WN-01's own fix).** `main.py:61-86` + `:417-480`: the `bottle.run` capture installs the asset/close routes **synchronously before** `bottle.run` starts serving, so the `/assets/*` storm the comment describes cannot race. Verified against the installed pywebview: `webview/http.py:141-147` calls `bottle.run(app=app, server=…, port=…, quiet=…)` with **keyword arguments only**, so the `_capture_bottle_run(app=None, **kwargs)` signature is safe (a positional call would have raised `TypeError`). The `after_request` hook that sets `Cache-Control: no-cache` is redundant with `webview/http.py:127-129` but harmless.
- **WebView2 runtime override mechanism itself.** `os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER']` (`main.py:30`) is the documented WebView2 loader override and is honoured because pywebview does not pass a `browserExecutableFolder` in its `CoreWebView2Environment` options (`webview/platforms/edgechromium.py:98-107`). Only the illegal `webview.settings` line next to it is broken (F-WN-01-1).
- **Chromium flags.** `main.py:32-49` — the WebView2 additional-arguments block is well-formed, and the `--disk-cache-size=1048576` / `--autoplay-policy=no-user-gesture-required` choices are explained in-line and match the symptoms they address.
- **DoH endpoint safety properties.** `main.py:150-159`: only IP-hosted DoH endpoints are used, so the HTTPS request itself never needs a name resolution and cannot recurse; the re-entrancy guard is thread-local; the positive-result cache is TTL-bounded (300 s) and size-capped (256) with a lock. The *scope* of the patch is the problem (F-WN-01-3), not these three properties.
- **Mutex mechanics.** `main.py:252-263`: `CreateMutexW` is called with explicit `argtypes`/`restype`, `GetLastError()` is read immediately after on the same thread (correct — `ctypes.windll` does not use `use_last_error`), and the non-Windows branch (`main.py:266-285`) writes a PID file and validates liveness with `os.kill(pid, 0)`. The gap is identity validation, not the Win32 mechanics.
- **Watchdog budget and restart cap.** `main.py:482-495`: the 35 s first-load budget matches the documented 10–20 s cold start, and `NEDOTIFY_RESTART_COUNT` bounds the respawn loop to one attempt.
- **Session save/restore.** `main.py:312-330` and `:557-571` restore the queue, index, shuffle and repeat and re-notify the UI of the restored track (`main.py:324-325`); the `on_loaded` autoplay path is guarded by `should_autoplay`.
- **Settings flush ordering in the watchdog.** `main.py:525-538`: `sync_flush_now()` → `cleanup()` → `sync_flush_now()` → `os._exit(3)` is the right order, and `core/settings.py:420` (`sync_flush_now`) exists with the documented hard-exit semantics. `tests/test_settings_flush.py` pins the *pattern* (see F-WN-01-12 for its limitation).
- **`pythonnet` / `clr` is not loaded at import time.** `import clr` appears exactly once in the tree (`core/api.py:587`), inside a daemon thread and inside a `try/except` that logs a warning; the `System.Windows.Forms` / `System.Drawing` imports at `core/api.py:624, 808-809, 845, 1062-1063` are safe because pywebview itself does `import clr` at `webview/platforms/winforms.py:13`. `pythonnet` is also a declared dependency of pywebview on win32 (`Requires-Dist: pythonnet; sys_platform == "win32"`), so its presence in `requirements.txt` is correct, not gratuitous. The residual risk — pywebview raising at `webview.start()` when the .NET runtime is absent — is covered by F-WN-01-5 (no cleanup on the exception path).
- **`installer.iss` correctness of the parts it does implement.** `PrivilegesRequired=lowest` + `{localappdata}\Programs\NeDotify` means a per-user, non-elevated install with no UAC prompt; the `Run` value is `HKCU` and its name is kept in sync with `core/api.py::AUTOSTART_RUN_VALUE` by `tests/test_build_and_brand.py::test_installer_writes_the_same_run_value_name`; the legacy `AURA Music` Run value is deleted on `ssPostInstall`; the user's library (`~/.nedotify`) is outside `{app}` and survives the uninstall.
- **`setup_pyinstaller.spec` cover-cache stripping.** The `_is_ui_cover_cache` predicate (`:16-24`) correctly normalises separators and matches only `/ui/` + `/covers/`, and `tests/test_build_and_brand.py::test_spec_strips_both_covers_caches` exercises the real predicate rather than the source text. (`ui/web_new_v2/covers` does not currently exist, so the filter is preventive rather than load-bearing today.)
- **`pytest.ini` / `run_tests.py`.** `pytest.ini` is a clean single source of truth (`testpaths`, the `network` marker, `addopts = -m "not network"` — `-m` receives `not network` as one argument because pytest shlex-splits `addopts`), and `run_tests.py` delegates to `pytest.main([])` without adding flags, so the ini governs everything. `requirements-dev.txt` pins `pytest==9.1.1` / `pytest-asyncio==1.4.0` exactly, and the installed versions match. `tests/test_build_and_brand.py` + `tests/test_settings_flush.py`: **50 passed, 1 skipped**.
- **`sys._MEIPASS` handling.** `main.py:333-339` resolves the UI directory through `sys._MEIPASS` with a source-tree fallback, satisfying the "frozen vs source assets" contract; `core/tray.py:38` and `services/zapret_service.py:326` do the same for their own assets.

---

### 4. Coverage gaps

- **No packaged build was produced.** The `PyInstaller` build, the Inno Setup compile (`iscc`) and the resulting `NeDotify_Setup.exe` were not executed — `iscc` is not on this machine and building would write into the repo tree. Every packaging finding (F-WN-01-6, -7, -8, -9) is derived from reading the spec/installer plus the runtime code that consumes the bundle, and from verified facts about the installed packages; the *runtime* behaviour inside a real bundle is inferred, not observed.
- **The DoH fallback was not exercised against a live resolver.** F-WN-01-3 is established from the code, the stdlib `socket.create_connection` source, and the acknowledged cost in `core/api.py:93-98`. The ~6 s worst case and the `https_proxy` interaction were not measured end-to-end, to avoid real network I/O and to avoid disturbing the user's connectivity.
- **The port-42001 collision path (F-WN-01-2) was not reproduced live.** The pywebview code path was read and the port value confirmed (`DEFAULT_HTTP_PORT = 42001`), but no second instance was actually launched with the port occupied, because that would start the real application.
- **Single-instance squatting (F-WN-01-4) was not demonstrated with a squatting process.** The absence of identity validation is a direct reading of `main.py:260-263`; the actual squat is a hypothesis about a third party's behaviour.
- **`~/.nedotify/` was not touched.** All runtime checks were executed with `HOME`/`USERPROFILE` redirected to a scratch directory under `%TEMP%`; the repository tree was not modified.
- **`core/api.py`, `core/proxy.py`, `core/tray.py`, `services/zapret_service.py` were read only at the call sites needed to trace WN-01's callees.** Defects found inside them are attributed to WN-03/WN-04/WN-11/WN-16/WN-26 and are not duplicated above; the specific callee-side risks I noted (the `from System.Windows.Forms import …` ordering dependency at `core/api.py:624`; the fixed-port bridge surface, whose auth model belongs to WN-03) should be picked up by those areas' reviewers.
- **`android/` was not opened.**

---

### 5. Architecture improvements (ARCH)

Architecture improvements **without** a proven defect. These are not counted in section 2.

- **ARCH-1 — `main.py` mixes six responsibilities in one module: process policy (mutex), network policy (DoH), HTTP server policy (bottle capture + routes), the WebView2 lifecycle, the startup watchdog, and the session/telemetry contract.** Each is independently testable and independently replaceable, and each currently reaches for a global (`socket`, `bottle`, `sys.path`, `logging`). A `bootstrap/` package with one module per responsibility — `single_instance.py`, `doh.py`, `routes.py`, `watchdog.py`, `shutdown.py` — would make the import-time side effects explicit and the parts unit-testable (see F-WN-01-12 for the testability angle).

- **ARCH-2 — The single-instance guard, the HTTP server port and the `~/.nedotify` data directory have three different, uncoordinated scopes.** The mutex is `Local\` (per Windows session), the HTTP port is per machine, and the data directory is per user. Any two of them can be in a state the third does not expect. A single, explicit statement of "one NeDotify per user profile" — with the mutex named accordingly and the port chosen per process — would remove the class of problem entirely.

- **ARCH-3 — The DoH fallback is the wrong layer.** It is implemented as an interpreter-wide monkey-patch of `socket.getaddrinfo` to work around one provider's DNS problem, and it now affects every network client in the product (yt-dlp, requests, Discord RPC, the SSRF guard, the proxy). A dedicated resolver used by the app's own outbound clients — or a per-client `requests`/`urllib3` adapter — would deliver the same escape hatch with a bounded blast radius.

- **ARCH-4 — The spec's asset list is decoupled from the repository layout.** `setup_pyinstaller.spec` hard-codes folder names (`ui/web_new_v2`, `ui/MACos_ui`, `zapret`, `bin`) that must exist, resolve them relative to the CWD, and assert nothing. A small manifest (or `SPECPATH`-relative paths plus a build-time existence check) would make "what ends up in the exe" a reviewable, testable list rather than a convention.

- **ARCH-5 — `requirements.txt` is a range document with no reproducibility artefact.** Ranges for a rapidly-moving date-versioned dependency (`yt-dlp`) plus no lock file means the artefact that ships to users is not the one that was tested. A `uv.lock`/`requirements.lock` with hashes, produced by CI and installed by the build, would make the packaged binary's dependency set reviewable.

- **ARCH-6 — `_BOTTLE_APP` (`main.py:53`, written at `:66`) is dead state.** It is never read. The real hand-off is `_ROUTE_INSTALLER` (`main.py:60`, `:543`), which *is* read. Removing `_BOTTLE_APP` and renaming `_ROUTE_INSTALLER` to something like `_pending_route_installer` would leave one obvious mechanism instead of two half-mechanisms.

- **ARCH-7 — The shutdown contract is implicit.** `AppCore.cleanup()` (WN-02), `AppApi.cleanup()` (WN-03) and the `on_closed` callback are three independent teardown surfaces with no declared ordering and no idempotency guarantee. Declaring a single shutdown owner — "the process exits through `AppCore.shutdown(reason)`, which is idempotent and owns the ordering" — would remove the class of leaks described in F-WN-01-5 rather than patching each path.
