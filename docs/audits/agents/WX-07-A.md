## AREA WX-07 — App lifecycle (main.py → AppCore → AppApi → cleanup, watchdog restart, session save/restore) — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `main.py` | 1–584 (whole file) |
| `core/app.py` | 1–586 (whole file) |
| `core/api.py` | 342–481, 482–541, 542–597, 900–959, 1110–1179, 1290–1319, 1400–1444 |
| `core/session.py` | 1–96 (whole file) |
| `core/settings.py` | 1–589 (whole file) |
| `core/database.py` | 145–224, 2405–2489 |
| `core/proxy.py` | 1258–1334 (LocalProxyManager.start/stop) |
| `core/downloader.py` | 40–99, 870–909 |
| `core/tray.py` | 1–194 (whole file) |
| `core/resolver.py` | 160–239 (`StreamResolver.resolve`) |
| `core/services/discord_rpc.py` | 160–183 (`stop`) |
| `audio/engine.py` | 20–69 |
| `audio/queue.py` | 1–60, 86–159 (`shuffle`/`repeat` properties, `set_tracks`) |
| `services/base_service.py` | 60–189 (`_SharedExecutor`, `shutdown_executor`) |
| `services/watchdog_service.py` | 1–129 (whole file) |
| `services/lufs_scanner.py` | 40–109 |
| `services/zapret_service.py` | 1063–1410 (start/stop, PID-guarded kill) |
| `utils/cache_manager.py` | 285–404 (`download_audio_stream` → `_executor`) |
| `core/plugins.py` | 16–116 (`load_plugins` / `unload_all`) |
| `.venv_win/Lib/site-packages/webview/util.py` | 50–187 (`ImmutableDict`, `base_uri`) |
| `.venv_win/Lib/site-packages/webview/__init__.py` | 60–278 (`settings`, `DEFAULT_HTTP_PORT`, `start`) |
| `.venv_win/Lib/site-packages/webview/http.py` | 1–225 (`BottleServer.start_server`, `start_global_server`) |
| `.venv_win/Lib/site-packages/webview/event.py` | 1–70 (`Event.set` thread semantics) |
| `.venv_win/Lib/site-packages/webview/window.py` | 179–218, 325–349, 545–560 (`_initialize`, `destroy`, `_resolve_url`) |
| `.venv_win/Lib/site-packages/webview/platforms/winforms.py` | 280–325 (`on_close` → `closed.set()` → `Application.Exit()`) |
| `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py` | 80–139 (`evaluate_js` → `Control.Invoke`) |

**Callees traced into other areas**

- `core/database.py` (WN-12) — WAL / `busy_timeout` / `close()`.
- `core/settings.py` (WN-14) — write-behind writer thread, `flush`, `sync_flush_now`.
- `core/proxy.py` (WN-11), `core/downloader.py` (WN-13), `core/tray.py` (WN-16),
  `services/watchdog_service.py` (WN-25), `services/zapret_service.py` (WN-26),
  `core/services/discord_rpc.py` (WN-26), `services/base_service.py` (WN-18),
  `core/resolver.py` (WN-15), `audio/queue.py` (WN-17) — teardown targets.
- `core/api.py` (WN-03/WN-04) — the bridge owns the tray and the search/prefetch executors;
  its `close()` / `_install_snap_layouts` defects are named there but are load-bearing
  for this lifecycle scenario, so they are reported here with the owning area named.

**Verification runs performed (read-only; the real app was never launched)**

1. `webview.settings['WEBVIEW2_RUNTIME_PATH'] = ...` executed in the project venv → `KeyError`.
2. `os.path.exists(<pinned WebView2 dir>)` on this machine → `False` (only `155.0.4283.60/.62` installed).
3. wsgiref double-bind on `127.0.0.1:42001` (blocker first, pywebview-style server second) → bind
   *succeeds*, subsequent HTTP requests fail with `ConnectionResetError` / `ConnectionAbortedError`.
4. `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)` + 4 s task → process wall time 4.11 s
   (the interpreter joins the pool at exit anyway).
5. `from pystray import MenuItem as item, Menu, Separator` → `ImportError` (pystray has no `Separator`).

---

### 2. Findings

#### F-WX-07-1  [P0] — `webview.settings['WEBVIEW2_RUNTIME_PATH'] = …` raises `KeyError` at import time: the app cannot start on any machine that has the pinned WebView2 runtime

- **File:** `main.py:24-30` (also `main.py:547`), root cause in `.venv_win/Lib/site-packages/webview/util.py:62-65` and `webview/__init__.py:72-79`
- **Confirmed:** yes (executed in the project venv)
- **Description:** `webview.settings` is a `webview.util.ImmutableDict`. Its `__setitem__` raises
  `KeyError("Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified.")`
  for any key that is not already present. `WEBVIEW2_RUNTIME_PATH` is **not** one of the six keys
  pywebview ships (`ALLOW_DOWNLOADS`, `ALLOW_FILE_URLS`, `OPEN_EXTERNAL_LINKS_IN_BROWSER`,
  `OPEN_DEVTOOLS_IN_DEBUG`, `REMOTE_DEBUGGING_PORT`, `IGNORE_SSL_ERRORS`). The assignment is at
  **module scope**, unguarded by any `try/except`, and it runs *before* `logging.basicConfig()`
  (`main.py:104`), before the single-instance mutex (`main.py:303`) and before `AppCore` exists.
  The result is an **import-time crash of the whole application**: `python main.py` dies with a
  traceback and the packaged `.exe` dies before any window appears.
- **Cause:** the code was written as if `webview.settings` were a free-form dict. It is a
  read-only-ish registry that only accepts its own keys. (pywebview never reads
  `WEBVIEW2_RUNTIME_PATH` anywhere — grep over the whole `webview` package returns no match —
  so the setting was inert even if it had been accepted.)
- **Trigger conditions:** the branch is guarded by
  `os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe'))`, i.e. it fires **exactly
  on the machines the pin was written for**. The comment at `main.py:21-23` says the pin exists
  because "Evergreen 151.0.4129.93 hangs bridge injection … on this machine, while
  151.0.4129.86 works" — i.e. the author’s machine has 151.0.4129.86 installed, so the branch
  fires and the app dies. On this audit machine the pinned folder is absent
  (`C:\Program Files (x86)\Microsoft\EdgeWebView\Application\` contains only `155.0.4283.60` and
  `155.0.4283.62`), which is exactly why the defect survived.
- **User impact:** total launch failure on the target machine. No window, no log entry
  (logging is configured later), no error dialog — just a traceback on the console or a silent
  exit of the frozen exe.
- **Evidence:**
  ```python
  # main.py:24-30
  _PINNED_WEBVIEW2 = os.path.join(
      os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
      'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
  )
  if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2   # <-- raises KeyError
      os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2
  ```
  ```python
  # webview/util.py:62-65
  def __setitem__(self, key, value):
      if key not in self.data:
          raise KeyError(f"Cannot add new key '{key}'. Only existing keys can be modified.")
      super().__setitem__(key, value)
  ```
  ```python
  # webview/__init__.py:72-79
  settings = ImmutableDict({
      'ALLOW_DOWNLOADS': False, 'ALLOW_FILE_URLS': True,
      'OPEN_EXTERNAL_LINKS_IN_BROWSER': True, 'OPEN_DEVTOOLS_IN_DEBUG': True,
      'REMOTE_DEBUGGING_PORT': None, 'IGNORE_SSL_ERRORS': False,
  })
  ```
- **Reproduction / verification:**
  ```
  & ".venv_win\Scripts\python.exe" -c "import webview; webview.settings['WEBVIEW2_RUNTIME_PATH']=r'C:\foo'"
  ```
  → `KeyError: "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."`
  (raised from `webview/util.py:64`).
  Full-app reproduction: install `151.0.4129.86` (or create the folder with an
  `msedgewebview2.exe` in it) and run `main.py` — the process aborts during import.
  `webview.settings.get('WEBVIEW2_RUNTIME_PATH', 'default')` at `main.py:547` is harmless
  (`UserDict.get` does not raise), which is why the crash is invisible in the log.
- **Suggested fix:** delete the `webview.settings[...]` line entirely and keep only the
  `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` env var (that env var is the mechanism the WebView2
  runtime itself honours); wrap the whole pin block in `try/except` so a future pin can never
  abort startup; log the resolved runtime path instead of reading it back out of `webview.settings`.
- **Fix side effects:** the pinned runtime would then actually take effect (currently, on
  machines where the branch is *not* taken, the pin is silently skipped as well, so the
  "151.0.4129.93 hangs bridge injection" regression the pin was written for is currently
  unmitigated everywhere except where the app does not start at all).
- **Discovered by:** A
- **Cross-reference:** this defect was already reported by the previous audit round
  (`docs/audits/FULL_PROJECT_AUDIT.md:60`, "One launch-blocking defect (P0)"). It is re-reported
  here because it is the mandatory check of scenario WX-07 and because the previous round did
  not carry it into the WX register.

---

#### F-WX-07-2  [P1] — pywebview's HTTP server is pinned to the fixed port 42001; a squatter on that port silently bricks the app (no exception, no fallback, no log)

- **File:** `main.py:555` (and `main.py:14`), root cause in `webview/__init__.py:70,192-193`, `webview/http.py:133,141-147`
- **Confirmed:** yes (source read + empirical socket test)
- **Description:** `webview.start(http_server=True, debug=…, private_mode=False, storage_path=…)`
  is called **without `http_port`**. In `webview/__init__.py`:
  ```python
  DEFAULT_HTTP_PORT = 42001
  ...
  if not _state['private_mode'] and not http_port:
      http_port = DEFAULT_HTTP_PORT
  ```
  Because `private_mode=False`, pywebview therefore always binds the **fixed** port 42001
  (`http.py:133`: `server.port = http_port or _get_random_port()` → 42001, not a random port).
  The whole UI is served from that port: `window._initialize()` sets
  `self._url_prefix = server.address` and `real_url = urljoin('http://127.0.0.1:42001/', 'index.html')`,
  so the WebView2 window navigates to `http://127.0.0.1:42001/index.html` and the JS→Python
  bridge is only reachable through `http://127.0.0.1:42001/js_api/<uid>`.
  `main.py:14` sets `socketserver.TCPServer.allow_reuse_address = True` on top of
  `http.server.HTTPServer.allow_reuse_address = True` (already `True` by default), so on Windows
  the second `bind()` to 42001 **succeeds** (no `OSError: [WinError 10048]`, no traceback) —
  but the two listeners then fight over the port and every request is reset. `bottle.run()`
  is executed inside a **daemon thread** (`http.py:141-147`), so even a real bind failure would
  be swallowed into a dead thread while `server.running = True` is still reported.
- **Cause:** a fixed, well-known port is used for a service that must be reachable, and the
  "port already in use" failure mode is not detected on Windows because `SO_REUSEADDR` makes
  the bind succeed. There is no port probe, no fallback to a random port, and no log line
  reporting the failure.
- **Trigger conditions:** any other process holds `127.0.0.1:42001` (a second NeDotify that
  outlived its mutex — see F-WX-07-5/F-WX-07-6; a stale `msedgewebview2.exe`; any user tool).
- **User impact:** the WebView2 window shows a connection error instead of the app; the bridge
  never initialises; `main.py::_startup_watchdog` fires after 35 s, respawns the app once, and
  the second instance hits the same wall (`NEDOTIFY_RESTART_COUNT >= 1` → "no more respawns").
  The user is left with a permanently broken window. In the reverse direction, NeDotify can
  **steal** the port from the other process.
- **Evidence:**
  ```python
  # main.py:14
  socketserver.TCPServer.allow_reuse_address = True
  # main.py:555
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  ```
  ```python
  # webview/__init__.py:70,192-193
  DEFAULT_HTTP_PORT = 42001
  if not _state['private_mode'] and not http_port:
      http_port = DEFAULT_HTTP_PORT
  ```
  ```python
  # webview/http.py:133,141-147
  server.port = http_port or _get_random_port()
  server.thread = threading.Thread(target=lambda: bottle.run(...), daemon=True)
  server.thread.start()
  ```
- **Reproduction / verification:** hold the port and then bind a wsgiref server the same way
  pywebview does (both sockets get `SO_REUSEADDR`):
  ```
  blocker.bind(('127.0.0.1', 42001)); blocker.listen(5)      # a foreign process
  make_server('127.0.0.1', 42001, app)                     # -> SUCCEEDS, no exception
  urllib.request.urlopen('http://127.0.0.1:42001/x')        # -> ConnectionResetError [10054]
                                                                 ConnectionAbortedError [10053]
  ```
  The bind "succeeding" and the requests failing is the whole failure mode.
- **Suggested fix:** pass an explicit `http_port=0` (or a probed free port) to `webview.start`,
  or drop `private_mode=False` so pywebview picks a random port; at minimum, log
  `server.address` and fail loudly if the server thread dies; remove the redundant
  `allow_reuse_address = True` so a real conflict surfaces as an error instead of a split port.
- **Fix side effects:** with `http_port=0` the UI origin changes per run — the frontend uses
  relative URLs, but the `Origin`/`Access-Control-Allow-Origin: *` behaviour of the bridge
  endpoint and any `localStorage` partitioning would have to be re-checked.
- **Discovered by:** A

---

#### F-WX-07-3  [P1] — `AppCore.cleanup()` cannot release the process: `shutdown(wait=False)` does not stop the interpreter from joining every pool worker

- **File:** `core/app.py:562-586` (comment at `:562`), trigger `core/app.py:361-374` + `utils/cache_manager.py:300-393`
- **Confirmed:** yes (empirically measured)
- **Description:** the teardown comment claims *"shutdown(wait=False) all thread pools so app
  exit never blocks"*. That is false on CPython 3.14: `concurrent.futures.thread` registers
  `_python_exit` via `threading._register_atexit(_python_exit)`, and `_python_exit` **joins every
  executor worker thread**:
  ```python
  def _python_exit():
      global _shutdown
      with _global_shutdown_lock: _shutdown = True
      items = list(_threads_queues.items())
      for t, q in items: q.put(None)
      for t, q in items: t.join()
  ```
  `shutdown(wait=False, cancel_futures=True)` only cancels *queued* work; a task that is already
  running keeps its thread alive, and the interpreter waits for it. Measured: a 4 s task →
  process wall time **4.11 s** despite `shutdown(wait=False)`.
- **Cause:** `wait=False` was used as if it released the pool; the interpreter-level join was
  not accounted for.
- **Trigger conditions:** an in-flight task at close time. Realistic candidates:
  `utils/cache_manager.py:300-393` — a full `yt_dlp` download of the current track
  (`retries: 10`, `socket_timeout: 30`, `concurrent_fragment_downloads: 4`), started 5 s after
  every resolved track because `storage.auto_cache_streams` defaults to **True**
  (`core/settings.py:146`); the downloader pool; `AppApi._prefetch_executor` (stream extraction);
  the shared `BaseMusicService._executor` (yt-dlp provider calls).
- **User impact:** the window disappears but the process lingers for minutes; the task manager
  shows a zombie NeDotify; a relaunch is possible because the mutex was already released
  (F-WX-07-5) → two instances with the same DB. Worse: `core/app.py:559-560` closes the database
  *before* the pools are shut down, so the in-flight cache download writes the file to disk and
  then fails on `self.db.set_cached_file(...)` (`utils/cache_manager.py:384`) against the closed
  connection — the cached row is lost and the error is only logged.
- **Evidence:**
  ```python
  # core/app.py:562-586
  # O-15: shutdown(wait=False) all thread pools so app exit never blocks
  def _shutdown_shared_pool():
      from services.base_service import BaseMusicService
      shutdown = getattr(BaseMusicService, "shutdown_executor", None)
      if callable(shutdown): shutdown()
      else: BaseMusicService._executor.shutdown(wait=False, cancel_futures=True)
  _step("base_service pool", _shutdown_shared_pool)
  for _pool in (...):
      try: _pool.shutdown(wait=False, cancel_futures=True)
  ```
- **Reproduction / verification:** the scratch script `pool_exit_test.py` (a 4 s task, then
  `shutdown(wait=False)`) → output `task finished` at 4.00 s, process wall time **4.112 s**.
  In the app, the trigger is `storage.auto_cache_streams=True` + a track played right before exit.
- **Suggested fix:** give the pools a cooperative cancellation token that the long tasks
  (`cache_manager._download_task`, the downloader worker, prefetch) check, and/or make the
  final exit a hard `os._exit()` after the session has been flushed (the pattern the watchdog
  path already uses at `main.py:539`); move `db.close()` after the pool shutdown.
- **Fix side effects:** cancelling a yt-dlp download mid-flight leaves a `.part` file in
  `~/.nedotify/streams/`; the existing `DownloadStore.preserve_shutdown()` path (already used by
  the downloader) is the model to follow.
- **Discovered by:** A
- **Cross-reference:** previously reported as `F-AR-02-1` in `docs/audits/_FINDINGS_SO_FAR.md:68`.

---

#### F-WX-07-4  [P1] — The tray subsystem is constructed but never started (two independent causes); the teardown stops a tray that never ran

- **File:** `core/api.py:571-575` (unreachable call) and `core/tray.py:16-19` (import error); consumer `core/api.py:922-930`; teardown `core/api.py:446-452`
- **Confirmed:** yes (source read + import executed in the project venv)
- **Description:** two independent defects, both fatal for the tray:
  1. **Dead code.** `AppApi.set_window()` (`:514-540`) spawns the Snap-Layouts installer thread;
     `_install_snap_layouts()` ends with an unconditional `return False` at `:572`, so the
     `self._tray.start()` at `:575` (and the whole window-icon block `:577-597`) is **unreachable**.
     `self._tray.start()` occurs exactly once in the whole tree — inside that dead block.
  2. **`pystray` API drift.** `core/tray.py:18` does `from pystray import MenuItem as item, Menu, Separator`;
     the installed pystray does not export `Separator`, so the `try` block fails and
     `HAS_PYSTRAY` is permanently `False`.
  Consequently `TrayIcon.start()` is never reached, `self.icon` stays `None`, and
  `AppApi.close()` computes `tray_available = bool(tray_mgr and hasattr(tray_mgr,'icon') and tray_mgr.icon)`
  → `False` → the window is always destroyed instead of being hidden to the tray, even though
  `general.minimize_to_tray` defaults to `True` (`core/settings.py:64`).
- **Cause:** an early `return` inserted into `_install_snap_layouts` orphaned the tail of the
  former `set_window()` body; and the pystray import was never validated against the installed
  version.
- **Trigger conditions:** every launch.
- **User impact:** minimise-to-tray never happens — closing the window quits the app while the
  user believes it is still running in the background; the app has no way back to the player
  except relaunching. From the lifecycle point of view, the tray is *constructed* (so
  `AppApi.cleanup()` believes it must stop it) but was never *started* — the teardown list and
  the construction list disagree about reality.
- **Evidence:**
  ```python
  # core/api.py:571-597
          logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
          return False

          if getattr(self, "_tray", None):        # <-- unreachable
              self._tray.start()

          try:
              import threading
              def _set_icon(): ...
  ```
  ```python
  # core/tray.py:16-19
      from PIL import Image
      import pystray
      from pystray import MenuItem as item, Menu, Separator   # ImportError in this venv
      HAS_PYSTRAY = True
  except (ImportError, Exception):
      HAS_PYSTRAY = False
  ```
- **Reproduction / verification:**
  ```
  & ".venv_win\Scripts\python.exe" -c "from pystray import MenuItem as item, Menu, Separator"
  -> ImportError: cannot import name 'Separator' from 'pystray'
  ```
  and `grep -n "_tray\.start" -r .` → one hit, `core/api.py:575`, inside the dead block.
- **Suggested fix:** move the tray start + icon helper back into `set_window()` (or into a
  dedicated `start_tray()` called from it), and import `Separator` from `pystray` only if it
  exists (`getattr(pystray, 'Separator', None)`) or use `pystray.Menu.SEPARATOR`.
- **Fix side effects:** once the tray really starts, `TrayIcon.on_exit` → `self.api._window.destroy()`
  becomes a live path and must be re-checked against the session-save ordering (F-WX-07-5).
- **Discovered by:** A
- **Owning area:** WN-16 (`core/tray.py`) for the pystray import; WN-04 (`core/api.py`) for the
  dead block. Reported here because the tray is a mandatory item of the WX-07 shutdown checklist.
- **Cross-reference:** previously reported as `F-AR-04-1` and `F-AR-04-2`
  (`docs/audits/_FINDINGS_SO_FAR.md:65-66`).

---

#### F-WX-07-5  [P2] — The single-instance mutex is released at *window close*, before the session save and the teardown → a relaunch runs concurrently with the dying instance

- **File:** `main.py:406-408` (`on_closed`), `main.py:555-580` (post-`webview.start()` teardown)
- **Confirmed:** yes
- **Description:** `on_closed` is bound to `window.events.closed` and its **only** job is
  `_release_instance_lock()`. pywebview fires `closed` from `winforms.py:309`
  (`self.closed.set()`) *before* `Application.Exit()`, i.e. before `webview.start()` returns.
  From that moment the named mutex `Local\NeDotify_App_Single_Instance_Mutex` is closed, while
  the old process still holds: the SQLite connection, the proxy server, the downloader, the
  watchdog observer, and — crucially — the **not-yet-written session**.
  The session is only saved afterwards, at `main.py:557-571`, i.e. *after* the mutex is gone.
- **Cause:** the mutex is treated as "the window is closed" rather than "the process is done".
- **Trigger conditions:** the user closes the window and immediately relaunches (double-click
  the shortcut again). The window between `closed.set()` and `sys.exit(0)` is short but
  non-zero, and it is lengthened by F-WX-07-3 (the process can linger for minutes *after*
  `sys.exit(0)` is requested).
- **User impact:** two processes with the same `~/.nedotify/nedotify_storage.db` open at once.
  The new instance's `SettingsManager._load_all()` can read the session **before** the old
  instance writes it → the restored queue is the previous one, and the old instance's
  `save_session` then overwrites whatever the new one has written. The DB itself is not
  corrupted (WAL + `busy_timeout=30000`), but a `sqlite3.OperationalError: database is locked`
  is possible if a write transaction exceeds 30 s.
- **Evidence:**
  ```python
  # main.py:406-408
  def on_closed():
      _INTENTIONAL_CLOSE.set()
      _release_instance_lock()
  ...
  # main.py:410-411
  window.events.loaded += on_loaded
  window.events.closed += on_closed
  ```
  ```python
  # main.py:555-580
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  # Save session before exit
  try:
      engine = app_core.engine
      ...
      app_core.session.save_session(...)
  except Exception as e:
      print(f"Failed to save session: {e}")
  # Cleanup after window closed
  _release_instance_lock()
  app_core.cleanup()
  ```
  ```python
  # core/database.py:181-192  (two writers are tolerated, but not silently)
  conn = sqlite3.connect(self.db_path, timeout=30.0)
  pragmas.append("PRAGMA journal_mode=WAL")
  pragmas.extend([..., "PRAGMA busy_timeout=30000", ...])
  ```
- **Reproduction / verification:** static trace of the event order (`winforms.py:309` →
  `webview.start()` returns → `main.py:557` session save). Dynamic check: start the app, close
  the window, and immediately relaunch — `~/.nedotify/logs/app.log` shows the second instance's
  `[startup]` line *before* the first instance's session flush.
- **Suggested fix:** release the mutex only at the very end of `main()` (after
  `app_core.cleanup()` / `api.cleanup()`), and let `on_closed` merely set `_INTENTIONAL_CLOSE`;
  keep the early release only for the watchdog respawn path, where it is explicitly needed.
- **Fix side effects:** if the process is killed between the window close and the final release,
  the mutex stays held until the OS reclaims the handle — acceptable on Windows (handles die with
  the process), but the `/__aura_close` bridge-free route would then need its own early release.
- **Discovered by:** A

---

#### F-WX-07-6  [P2] — The watchdog releases the mutex *before* spawning the respawn: the parent and the child overlap, and the child must reuse the WebView2 user-data folder the dying parent still holds

- **File:** `main.py:490-539` (watchdog), `main.py:549` (`storage_path`)
- **Confirmed:** yes for the overlap; hypothesis for the WebView2 user-data-folder failure
- **Description:** `_startup_watchdog` does, in this order: `_release_instance_lock()` (`:514`)
  → `subprocess.Popen(child)` (`:515-520`) → `app_core.cleanup()` (`:530`) → `os._exit(3)` (`:539`).
  The mutex is therefore free **before** the child exists, and the parent is still fully alive
  (proxy server on its dynamic port, downloader pool, SQLite connection, WebView2 browser
  process) while the child starts and acquires the mutex. Any *user*-initiated launch in the
  gap between `:514` and the child's `CreateMutexW` wins the mutex; the child then hits
  `ERROR_ALREADY_EXISTS` and exits immediately (`main.py:261-263`) → the respawn produced
  nothing and the app is dead (exactly the failure the watchdog exists to escape).
  In addition, `_storage_dir` (`main.py:549`) is a **fixed** path
  (`~/.nedotify/webview2_data`) shared by the parent and the child; the parent reaches
  `os._exit(3)` without destroying the WebView2 window, so the browser process may still be
  holding the Chromium singleton lock on that folder when the child calls
  `EnsureCoreWebView2Async`.
- **Cause:** the mutex is used as a "who may start" token, but the parent is not actually dead
  when it is released; and the respawn reuses the same WebView2 profile directory as the
  process it is replacing.
- **Trigger conditions:** the bridge fails to initialise within 35 s (a cold/slow WebView2 start,
  a hung renderer) — i.e. exactly the situation the watchdog is for.
- **User impact:** the app can end up with *no* instance at all (child lost the race) or with
  two instances (parent still alive for the duration of `cleanup()` + the pool join of
  F-WX-07-3 — and note the parent calls `os._exit(3)`, so it skips `atexit` and does not run
  the `atexit`-registered `SettingsManager.flush`; the code compensates with two explicit
  `sync_flush_now()` calls at `:526` and `:536`, which is correct).
- **Evidence:**
  ```python
  # main.py:508-520
  # Release BEFORE spawning. The single-instance guard now runs at
  # the very top of main(), so a child that starts while this process
  # still holds the mutex sees ERROR_ALREADY_EXISTS and exits at once
  # ...
  _release_instance_lock()
  subprocess.Popen(restart_args, creationflags=creation_flags, close_fds=True, env=env)
  ```
  ```python
  # main.py:549-550
  _storage_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'webview2_data')
  os.makedirs(_storage_dir, exist_ok=True)
  ```
- **Reproduction / verification:** to confirm the WebView2 half: make the bridge fail to
  initialise (e.g. point `_PINNED_WEBVIEW2` at a broken runtime) and watch
  `~/.nedotify/logs/app.log` for the child’s `[startup] WebView2 runtime setting:` line and for
  a WebView2 "user data folder is already in use" error; `Get-Process msedgewebview2` during the
  respawn shows whether the parent’s browser process survived `os._exit`.
- **Suggested fix:** spawn the child *before* releasing the mutex and have the child wait for
  the parent's exit (or use a "handoff" event); give the respawned child a distinct
  `storage_path` (e.g. `webview2_data.<pid>`) so the two never share the Chromium profile.
- **Fix side effects:** a per-PID `storage_path` loses the WebView2 profile (cookies, local
  storage) on every respawn — the UI is a `file://`-served bundle with no login state, so the
  cost is low, but it must be checked against `ui/web_new_v2/js/*` localStorage usage.
- **Discovered by:** A

---

#### F-WX-07-7  [P2] — The teardown order is not the reverse of the construction order: `AppApi.cleanup()` runs *after* `AppCore.cleanup()`, and the DB is closed before the pools are shut down

- **File:** `main.py:575-579`, `core/app.py:541-586`, `core/api.py:446-459`
- **Confirmed:** yes
- **Description:** construction order is
  `db → settings → session → cache → scanner → resolver → engine → youtube/vk/spotify/lyrics/artists
  → proxy → downloader → plugins → zapret → watchdog → lufs_scanner → audio_fingerprint → discord_rpc`
  (`core/app.py:107-147`) and then `AppApi` adds the search/prefetch executors, the engine
  callbacks and the tray (`core/api.py:362-390`).
  The teardown order is
  `flush_listening → watchdog → lufs_scanner → downloader → plugins → discord_rpc → proxy → zapret
  → cache_cleanup → settings.flush → db.close → shared pool → per-pool shutdowns`
  (`core/app.py:541-586`) and only **afterwards** `api.cleanup()` →
  `tray.stop()` + `search_executor.shutdown()` + `prefetch_executor.shutdown()` (`main.py:576-579`).
  Three inversions:
  - **The tray and the bridge executors are torn down after the DB is closed.** A tray click or
    an in-flight search that lands in that window hits a closed connection.
  - **`db.close()` precedes the executor shutdowns** (`core/app.py:559-560` vs `:562-586`), so
    in-flight provider/prefetch tasks write into a closed database.
  - **`zapret.stop()` runs after `proxy.stop()`** even though zapret was constructed *after* the
    proxy (`core/app.py:137` vs `:141`).
- **Cause:** the teardown was assembled step-by-step rather than derived from the construction
  order; `api.cleanup()` was bolted on at the end of `main()`.
- **Trigger conditions:** every close.
- **User impact:** lost writes / logged exceptions during shutdown; a tray action or a late
  search that fails with `sqlite3.ProgrammingError: Cannot operate on a closed database`.
- **Evidence:**
  ```python
  # main.py:573-580
  # Cleanup after window closed
  _release_instance_lock()
  app_core.cleanup()          # <- closes the DB (core/app.py:559-560)
  try:
      api.cleanup()            # <- only NOW stops the tray + the bridge executors
  except Exception:
      logging.debug("_startup_watchdog: suppressed exception", exc_info=True)
  sys.exit(0)
  ```
- **Reproduction / verification:** instrument `core/app.py::cleanup` with a print per step, or
  simply read the two call sites: `db.close` (`core/app.py:560`) precedes
  `BaseMusicService.shutdown_executor()` (`core/app.py:571`) precedes `api.cleanup()`
  (`main.py:577`).
- **Suggested fix:** call `api.cleanup()` **before** `app_core.cleanup()`, and move the pool
  shutdowns before `db.close()` inside `AppCore.cleanup()`.
- **Fix side effects:** shutting the pools down before the DB means in-flight tasks must
  tolerate a closing DB — the downloader already has a cooperative epoch for this
  (`core/downloader.py:884-909`); the provider pool does not.
- **Discovered by:** A

---

#### F-WX-07-8  [P2] — The settings writer thread is never stopped; a write that lands after `db.close()` is silently lost

- **File:** `core/settings.py:508-530` (`_writer_loop`), `core/app.py:557-560` (flush then close)
- **Confirmed:** yes
- **Description:** `SettingsManager._writer_loop()` is an unconditional `while True:` loop with
  no stop flag and no reference kept anywhere else; it is only ever a daemon thread that dies
  with the process. `AppCore.cleanup()` calls `settings.flush()` and then `db.close()`, but never
  asks the writer to stop. The writer sleeps `FLUSH_INTERVAL_SECONDS` (0.5 s) after each wake-up,
  so a `set()` that happens in the window between `db.close()` and the process exit wakes the
  writer, which then calls `flush()` → `self.db.set_settings_batch(...)` → against the **closed**
  connection → `sqlite3.ProgrammingError: Cannot operate on a closed database` → caught inside
  `flush()`, the keys are pushed back into `_dirty` and the change is **lost** with only an
  `ERROR` log line.
- **Cause:** the write-behind worker has no lifecycle; it is treated as "process-scoped".
- **Trigger conditions:** any `settings.set()` during shutdown — e.g. `AppApi.close()` →
  `flush_listening`, the tray, the downloader's `preserve_shutdown`, the cache manager, or a
  provider callback that persists a preference.
- **User impact:** a setting changed in the last moments of the session is lost; the user sees
  an error in `app.log` but no explanation in the UI. The session itself is protected only
  because `SessionManager.save_session()` flushes synchronously (`core/session.py:66-68`).
- **Evidence:**
  ```python
  # core/settings.py:520-530
  def _writer_loop(self) -> None:
      while True:
          self._writer_wake.wait()
          self._writer_wake.clear()
          time.sleep(self.FLUSH_INTERVAL_SECONDS)
          try:
              self.flush()
          except Exception as e:
              logger.error(f"Settings writer thread error: {e}")
  ```
  ```python
  # core/app.py:557-560
  if getattr(self, "settings", None) and hasattr(self.settings, "flush"):
      _step("settings.flush", self.settings.flush)
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)
  ```
- **Reproduction / verification:** add a `settings.set(...)` from a background thread during
  `cleanup()` (or simply close the app while the cache manager is writing) and observe
  `ERROR Settings flush failed, N keys still pending: Cannot operate on a closed database` in
  `~/.nedotify/logs/app.log`.
- **Suggested fix:** give `SettingsManager` a `stop()` that clears `_writer_wake` and joins the
  writer thread, and call it from `AppCore.cleanup()` **before** `db.close()`.
- **Fix side effects:** the writer must be woken reliably (`_writer_wake.set()`) or the join
  will block for the full 0.5 s interval on every exit.
- **Discovered by:** A

---

#### F-WX-07-9  [P3] — The watchdog's 35 s budget starts before `webview.start()`, so a slow cold WebView2 start causes a spurious self-restart

- **File:** `main.py:482-495`, `main.py:543-555`
- **Confirmed:** yes (code trace); the on-screen effect is a hypothesis
- **Description:** the watchdog thread is started at `main.py:544`, i.e. **before**
  `webview.start()` at `:555`. Its budget is `window.events.loaded.wait(35)`, which measures the
  time from *thread start* to the page-load event — i.e. it includes the entire WebView2 cold
  start (runtime discovery, user-data-folder open, renderer spin-up), not just the bridge
  injection. The comment says "First load may take ~10-20s on cold WebView2; give it 35s".
  If the cold start alone takes >35 s, the watchdog concludes "the bridge never came up",
  respawns the app, and the new instance repeats the same cold start.
- **Cause:** the timeout is anchored to the wrong event (thread start rather than the window
  being shown).
- **Trigger conditions:** a cold WebView2 profile, a slow disk, an antivirus scan of the
  `~/.nedotify/webview2_data` folder, or a machine that is simply busy.
- **User impact:** the app restarts itself in front of the user, once; with
  `NEDOTIFY_RESTART_COUNT=1` the second failure is terminal ("showing overlay, no more
  respawns", `main.py:492`).
- **Evidence:**
  ```python
  # main.py:482-495
  def _startup_watchdog():
      # First load may take ~10-20s on cold WebView2; give it 35s.
      if window.events.loaded.wait(35):
          logging.info("[startup] bridge initialized after 1 load attempt(s)")
          return
  ...
  # main.py:543-555
  _ROUTE_INSTALLER[0] = _install_routes
  threading.Thread(target=_startup_watchdog, daemon=True).start()
  ...
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  ```
- **Reproduction / verification:** delete `~/.nedotify/webview2_data` and start the app on a
  slow disk; compare the timestamp of the `[startup] window created` log line with the
  `[startup] bridge not initialized after 35s` line.
- **Suggested fix:** start the 35 s timer after the window is shown (or after `webview.start()`
  has returned control), e.g. wait on `window.events.shown` first.
- **Fix side effects:** the total time before a legitimate restart grows; the user sees a
  longer "nothing happens" period instead of a visible restart.
- **Discovered by:** A

---

#### F-WX-07-10  [P3] — `DatabaseManager.close()` is not idempotent: a second call re-opens the user's database file

- **File:** `core/database.py:2459-2489`, `core/database.py:179-201`
- **Confirmed:** yes
- **Description:** `close()` first calls `_checkpoint_wal()`, which executes on `self.conn` →
  `self._get_connection()`. `close_thread_connection()` (called one line earlier at `:2471`)
  has already set `self._local.connection = None`, so `_get_connection()` **opens a brand-new
  connection** to `~/.nedotify/nedotify_storage.db` during shutdown, runs the checkpoint on it and
  closes it again. So calling `cleanup()` twice re-opens the user's database file, re-runs
  `PRAGMA wal_checkpoint(TRUNCATE)` and re-closes it.
- **Cause:** `close()` assumes the thread-local slot still holds a connection.
- **Trigger conditions:** a second `AppCore.cleanup()` — currently not reachable from `main.py`
  (the two call sites at `:530` and `:575` are mutually exclusive), so this is a robustness
  defect in the "cleanup is safe to call twice" contract rather than an observed user-facing bug.
- **User impact:** none observed today; if the DB folder were removed between the two calls the
  re-open raises `sqlite3.OperationalError: unable to open database file` (caught by
  `_checkpoint_wal`’s `except sqlite3.Error` and logged).
- **Evidence:**
  ```python
  # core/database.py:2470-2471
  self._checkpoint_wal()
  self.close_thread_connection()
  ```
  ```python
  # core/database.py:179-201
  def _get_connection(self) -> sqlite3.Connection:
      if not hasattr(self._local, "connection") or self._local.connection is None:
          conn = sqlite3.connect(self.db_path, timeout=30.0)   # <-- re-opened
  ```
- **Reproduction / verification:** `db = DatabaseManager(); db.close(); db.close()` — the second
  call opens a new connection (visible via `db._all_conns` / a `PRAGMA database_list` trace).
- **Suggested fix:** make `_checkpoint_wal()` use the existing connection only (skip the
  checkpoint when the thread-local slot is empty) and set a `self._closed` flag that
  `close()` honours.
- **Fix side effects:** the WAL checkpoint would no longer run on a second close — acceptable,
  since the first close already checkpointed.
- **Discovered by:** A

---

#### F-WX-07-11  [P3] — `session.last_volume` is written but never read back: the session volume is a dead field (the volume itself is restored through the settings path)

- **File:** `core/session.py:59`, `core/session.py:75`, `main.py:313-330`
- **Confirmed:** yes
- **Description:** `save_session()` persists `session.last_volume`, and `restore_session()`
  returns `"volume": self.settings.get("session", "last_volume", 70)`, but `main.py:313-330`
  never reads `session_data["volume"]` — it only uses `position`, `queue`, `queue_index`,
  `shuffle` and `repeat`. The user's volume is nevertheless restored, but through a different
  route: `AppApi.set_volume` → `settings.set("audio","volume",…)` → the ordinary settings store,
  which the UI reads via `get_settings`. Likewise the mute state is persisted as
  `audio.muted` (`core/api.py:1986`) and read back via `is_muted()` (`core/api.py:1993-1999`),
  not through the session.
- **Cause:** the session schema carries a field that the restore path never consumes.
- **Trigger conditions:** every start/stop cycle.
- **User impact:** none functionally (the volume and the mute do survive a restart) — but
  `session.last_volume` is a misleading, write-only row in the settings table, and the session
  is *not* the place where the volume lives, which matters for anyone reasoning about the
  "session restores the volume" contract.
- **Evidence:**
  ```python
  # core/session.py:57-63
  self.settings.set("session", "last_track_id", track_id)
  self.settings.set("session", "last_position", position)
  self.settings.set("session", "last_volume", volume)
  self.settings.set("session", "last_queue", persisted_queue)
  ...
  # main.py:313-330 — "volume" is never read
  session_position_sec = float(session_data.get("position") or 0.0)
  if queue:
      app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
      app_core.engine.queue.shuffle = session_data.get("shuffle", False)
      app_core.engine.queue.repeat = session_data.get("repeat", "off")
  ```
- **Reproduction / verification:** inspect the `settings` table after a run — the row
  `session.last_volume` exists; grep `main.py` for `["volume"]` → no hit.
- **Suggested fix:** either consume `session_data["volume"]` on restore (and make it
  authoritative) or drop `last_volume` from the session schema.
- **Fix side effects:** making the session authoritative would override a volume the user
  changed in the UI *after* the last session save — a behaviour change that needs a decision.
- **Discovered by:** A

---

### 3. Clean areas

- **Construction order inside `AppCore.__init__` is sound for the dependency graph.** Every
  subsystem is created before its first use: `db` → `settings` (needs `db`) → `session`
  (needs `settings`) → `cache`/`scanner` (need `db`) → `resolver` (needs `db`) → `engine`
  → `engine.proxy` is assigned right after `self.proxy` exists (`core/app.py:137-138`) →
  `downloader`/`plugins`/`zapret`/`watchdog`/`lufs_scanner`/`discord_rpc` →
  `proxy.start()` (`:158`) → `plugins.load_plugins()` (`:159`) → `watchdog.start()` (`:163`) →
  `lufs_scanner.start()` (`:169`). The eager/lazy split for `soundcloud`/`yandex`/
  `recommendations` uses an `RLock` (`core/app.py:101`) precisely to avoid the self-deadlock a
  plain `Lock` would cause — correct, and documented in place.
- **Failure of an optional subsystem does not abort startup.** `watchdog.start()` and
  `lufs_scanner.start()` are individually wrapped in `try/except` (`core/app.py:162-171`);
  `LocalProxyManager.start()` swallows a bind failure and leaves `port = 0`
  (`core/proxy.py:1281-1282`); `DiscordRPCService.start()` runs its connect loop in a daemon
  thread; `TrayIcon` construction is wrapped (`core/api.py:384-388`); the `import clr` icon
  helper is inside a `try/except` in a daemon thread (`core/api.py:577-597`) — so a missing
  pythonnet cannot break startup.
- **A constructor failure does not leave a half-built *hung* process.** All background threads
  created before the failure point are daemons (the `watchdog` observer — `watchdog.utils.BaseThread`
  sets `daemon = True`; the cache-cleanup thread `core/app.py:185`; the yt-dlp thread `:151`;
  the zapret thread `:284`; the `AudioFileHandler._processor_thread`
  `services/watchdog_service.py:33`; the downloader processor `core/downloader.py:89`; the LUFS
  thread `services/lufs_scanner.py:50`; the discord thread `core/services/discord_rpc.py:85`;
  the tray thread `core/tray.py:185`; the EmitWorker `core/api.py:1148`; the `EmitWorker`
  `_set_icon` thread `core/api.py:595`; the snap-layouts thread `core/api.py:538`), so a raise
  inside `AppCore()` or `AppApi()` terminates the process instead of hanging it.
- **`AppCore.cleanup()` isolates every step.** `_step()` (`core/app.py:522-526`) wraps each
  teardown call in its own `try/except` and logs the failure with `exc_info=True`, so one
  failing component cannot abort the remaining steps — this is the correct pattern for the
  "does an exception abort the rest" question.
- **The teardown is genuinely idempotent for every component that can be called twice**:
  `watchdog.stop()` (setting an event + `join()` on an already-stopped thread),
  `lufs_scanner.stop()` (`ThreadPoolExecutor.shutdown` twice is a no-op),
  `downloader.stop()` (`preserve_shutdown()` + `pool.shutdown` are both repeatable),
  `discord_rpc.stop()` (guards on `self.rpc`), `proxy.stop()` (`self.server` is `None` after the
  first call), `zapret.stop()` (PID-guarded, kills only its own `winws.exe`),
  `settings.flush()` (returns immediately when `_dirty` is empty), the shared executor
  (`_SharedExecutor.shutdown` is idempotent), and `api.cleanup()` (both executors tolerate a
  double `shutdown`). Only `db.close()` is not idempotent — see F-WX-07-10.
- **Everything on the shutdown checklist *is* touched**, with the caveats listed in the
  findings: proxy HTTP server (`core/proxy.py:1284-1298` — `shutdown()` + `server_close()`),
  downloader pool (`core/downloader.py:884-909` — cooperative epoch bump + bounded drain),
  watchdog observer (`services/watchdog_service.py:97-102`), zapret subprocess
  (`services/zapret_service.py:1336+` — kills only its own PID, never `taskkill /IM`),
  Discord RPC (`core/services/discord_rpc.py:174-183`), the shared
  `BaseMusicService._executor` (`core/app.py:563-571`), the bridge search/prefetch executors
  (`core/api.py:446-459`), the cache-cleanup thread (`core/app.py:555-556`), the LUFS pool
  (`services/lufs_scanner.py:53-56`), the plugins (`core/app.py:547-548`) and the DB
  (`core/app.py:559-560`). The two entries that are **not** properly closed are the settings
  writer thread (F-WX-07-8) and the resolver's in-flight resolutions
  (`core/resolver.py:165-230` has no shutdown/cancel API — a flight in progress keeps its
  caller blocked for up to `_RESOLVE_TIMEOUT` and then persists to a DB that may already be
  closed; the failure is caught by the `except Exception` at `:216-217`, so it is noisy but not
  fatal).
- **The session save happens before the resources are torn down.** `main.py:557-571` saves the
  session *after* `webview.start()` returns but *before* `app_core.cleanup()` and before
  `db.close()`; `SessionManager.save_session()` flushes synchronously
  (`core/session.py:66-68`), so the data is on disk even though the process is about to exit.
- **The session restore is applied to the engine, not only to the settings.** `main.py:318-321`
  calls `app_core.engine.queue.set_tracks(queue, queue_index)` and sets
  `queue.shuffle` / `queue.repeat`; `PlaybackQueue` exposes writable `shuffle`/`repeat`
  properties (`audio/queue.py:63-117`) and `set_tracks()` clamps the index
  (`audio/queue.py:119-124`), so the restore is well-formed. The `queue_index` is corrected when
  the queue was truncated (`core/session.py:51-55`). The restored track is re-announced in
  `on_loaded` (`main.py:391-392`) and the autoplay decision is delegated to the UI through the
  `session_autoplay` event (`main.py:395-402`, `core/session.py:91-96`).
- **The queue position survives the restart.** `position` comes from
  `engine._last_reported_position`, which the bridge maintains on every
  `report_position` (`core/api.py:1421-1422`), and it is restored into the `session_autoplay`
  payload (`main.py:399`).
- **`_emit` never runs on the UI thread.** `core/api.py:1147-1154` hands the `evaluate_js` call
  to a dedicated `EmitWorker` thread when the caller *is* the main thread; the pywebview WinForms
  backend marshals `evaluate_js` through `Control.Invoke` and then blocks on a semaphore
  (`webview/platforms/edgechromium.py:126-130`), so calling it from the UI thread would
  deadlock — the guard is correct and is the documented non-negotiable rule.
- **The DB is safe against two writers.** `PRAGMA journal_mode=WAL` and
  `PRAGMA busy_timeout=30000` are applied to every connection (`core/database.py:185-190`), and
  all writes go through the per-instance `_write_lock` (`core/database.py:156`). WAL + a 30 s
  busy timeout means the overlap described in F-WX-07-5/F-WX-07-6 cannot corrupt the file; the
  worst case is an `OperationalError: database is locked` after 30 s.
- **The watchdog's respawn is bounded.** `NEDOTIFY_RESTART_COUNT` caps the chain at one
  respawn (`main.py:490-493`), the child is spawned detached
  (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `main.py:499-500`), the `sys.argv` duplication
  bug of the frozen build is handled (`main.py:503-507`), and the two explicit
  `settings.sync_flush_now()` calls compensate for `os._exit(3)` skipping `atexit`
  (`main.py:525-538`).
- **The single-instance guard runs first.** `main()` acquires the named mutex before `AppCore()`
  is constructed (`main.py:303-306`), which is the correct order — the comment at `:239-245`
  documents the historical bug (the guard used to run after the window existed).

### 4. Coverage gaps

- **The real app was never launched** (forbidden by the brief: it would disturb the user's
  profile and `~/.nedotify/`). The WebView2 user-data-folder half of F-WX-07-6 and the
  on-screen effect of F-WX-07-9 therefore remain hypotheses; they need an instrumented run
  with `NEDOTIFY_DEVTOOLS=1` and the `[startup]` timestamps in `~/.nedotify/logs/app.log`.
- **F-WX-07-1 could not be reproduced end-to-end on this machine** because the pinned
  WebView2 `151.0.4129.86` is not installed here (only `155.0.4283.60` / `155.0.4283.62`).
  The `KeyError` itself was reproduced directly against the installed pywebview, and the
  `os.path.exists` guard was evaluated for real; what could not be observed is the frozen-exe
  crash dialog.
- **The `webview` HTTP-server behaviour was verified with a synthetic wsgiref server**, not with
  pywebview's own `BottleServer` (that would have required starting the real GUI). The
  `DEFAULT_HTTP_PORT` selection was read directly from `webview/__init__.py:70,192-193` and the
  bind semantics from `http.py:133` + `wsgiref`/`HTTPServer.allow_reuse_address`.
- **The DB was never opened.** `DatabaseManager()` hard-codes `~/.nedotify/nedotify_storage.db`
  and `AppCore()` takes no `db_path` argument, so constructing an `AppCore` for an idempotency
  test would have written to the user's library — forbidden by the brief. The idempotency
  verdicts in section 3 are therefore derived from reading each `stop()`/`close()`
  implementation, not from executing `cleanup()` twice.
- **`core/listening.py`, `core/plugins.py` plugin bodies and `services/zapret_service.py`'s
  updater thread** were only skimmed for their stop semantics; the plugin `setup(app_core)`
  contract (a plugin could spawn its own non-daemon thread that `unload_all()` does not stop)
  was not audited — that is WN-02/WN-33 territory.
- **`audio/engine.py`'s resolution threads** (`resolve_stream_url` → `threading` usage) were
  only checked for the absence of a `stop()`; the engine keeps no thread registry, so any
  in-flight resolution at shutdown is covered by the generic "resolver has no cancel" note in
  section 3 rather than by a dedicated finding.
