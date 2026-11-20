## AREA WN-01 — Process bootstrap, startup/shutdown, packaging — ROLE A

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

| File | Lines read |
|---|---|
| `main.py` | 1–584 (whole file) |
| `setup_pyinstaller.spec` | 1–111 (whole file) |
| `installer.iss` | 1–92 (whole file) |
| `requirements.txt` | 1–25 (whole file) |
| `requirements-dev.txt` | 1–2 (whole file) |
| `run_tests.py` | 1–12 (whole file) |
| `pytest.ini` | 1–5 (whole file) |
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–201 |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 |

**Callees traced into other areas (read only to attribute defects, not to re-review)**

| Callee | Read | Owning area |
|---|---|---|
| `core/app.py` — `AppCore.__init__`, `cleanup()` (108–142, 508–586) | yes | WN-02 |
| `core/api.py` — `AppApi.__init__` engine wiring (374), `_on_track_changed` (1195–1242), `update_autostart` / `AUTOSTART_RUN_VALUE` (38–56, 2839–2888) | yes | WN-03 / WN-08 |
| `core/session.py` — `SessionManager.save_session/restore_session/should_autoplay` (whole file, 96 L) | yes | WN-02 |
| `core/settings.py` — `set/flush/sync_flush_now` (401–506, 256–264) | yes | WN-14 |
| `core/ui_assets.py` — `install_macos_assets` (whole file, 22 L) | yes | WN-16 |
| `audio/queue.py` — `PlaybackQueue.shuffle/repeat/set_tracks` (1–125) | yes | WN-17 |
| `audio/engine.py` — `_on_track_changed` init (30), notify (119) | yes | WN-17 |
| `core/database.py` — `set_setting/set_settings_batch/get_all_settings` | yes | WN-12 |
| `core/proxy.py` — `ThreadingHTTPServer` (421), bind (1276) | yes | WN-11 |
| `core/tray.py` — pystray import (13–19) | yes | WN-16 |
| pywebview 5.4 (`webview/__init__.py`, `webview/http.py`, `webview/util.py`, `webview/event.py`, `webview/window.py`, `webview/platforms/{winforms,edgechromium}.py`) | yes | third-party |
| bottle 0.13.4 (`Router.add/match`, `Bottle.error`) | yes | third-party |
| PyInstaller 6.22.3 (`building/build_main.py`, `building/utils.py`, `building/datastruct.py`), `yt_dlp/__pyinstaller/hook-yt_dlp.py`, `webview/__pyinstaller/hook-webview.py` | yes | third-party |

**Verification environment:** `.venv_win\Scripts\python.exe` (Python 3.14, pywebview 5.4, bottle 0.13.4, PyInstaller 6.22.3). All scratch scripts live in `%TEMP%\opencode\audit_reports\`. No repo file was modified; `~/.nedotify/` was never touched (the import reproduction ran with a redirected `HOME`/`USERPROFILE` and a fake `ProgramFiles(x86)`).

---

### 2. Findings

#### F-WN-01-1  [P0] — `webview.settings['WEBVIEW2_RUNTIME_PATH'] = …` raises `KeyError` at import: the app cannot start on any machine that has the pinned WebView2 build

- **File:** `main.py:28-30` (+ `main.py:19` for the import order, `main.py:104-117` for the logging that never happens)
- **Confirmed:** yes — reproduced end-to-end (see verification)
- **Description:** `webview.settings` in pywebview ≥ 4 is an `ImmutableDict` that **refuses new keys**. `WEBVIEW2_RUNTIME_PATH` is not one of the six keys pywebview ships (`ALLOW_DOWNLOADS`, `ALLOW_FILE_URLS`, `OPEN_EXTERNAL_LINKS_IN_BROWSER`, `OPEN_DEVTOOLS_IN_DEBUG`, `REMOTE_DEBUGGING_PORT`, `IGNORE_SSL_ERRORS`). The assignment therefore raises `KeyError` at **module import time**, before `main()` runs, before `logging.basicConfig()` installs the rotating file handler, and before the excepthook is installed. The whole process dies with exit code 1.
- **Cause:** the code was written against a pywebview version whose `settings` was a plain `dict` (or that had the key). `requirements.txt:6` allows `pywebview>=5.0.0,<6`, and the installed 5.4 raises. The statement is at module top level with **no `try/except`**, so the failure is not contained.
- **Trigger conditions:** the pinned WebView2 runtime folder exists on the machine, i.e. `os.path.join(ProgramFiles(x86), 'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86', 'msedgewebview2.exe')` — exactly the machine class the code was written for ("Evergreen 151.0.4129.93 hangs bridge injection … on this machine").
- **User impact:** **the application does not start at all.** There is no window, no tray icon, no log entry: the exception happens before the file handler is created, and in the packaged build `console=False` means stderr is `os.devnull` (pywebview's `webview/http.py:8-12` redirects it). The user sees a process that exits instantly. The failure is completely invisible.
- **Evidence:**
  ```python
  # main.py:24-30
  _PINNED_WEBVIEW2 = os.path.join(
      os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
      'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
  )
  if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2
      os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/util.py:58-66
  class ImmutableDict(UserDict):
      def __setitem__(self, key, value):
          if key not in self.data:
              raise KeyError(f"Cannot add new key '{key}'. Only existing keys can be modified.")
  ```
- **Reproduction / verification:** copied `main.py` to a temp dir, pointed `ProgramFiles(x86)` at a fake tree containing `Microsoft/EdgeWebView/Application/151.0.4129.86/msedgewebview2.exe`, redirected `HOME`/`USERPROFILE` to a temp dir, and imported the module:
  ```
  returncode: 1
  Traceback (most recent call last):
    File "…\main_probe.py", line 29, in <module>
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2
  File "…\webview\util.py", line 64, in __setitem__
      raise KeyError(f"Cannot add new key '{key}'. Only existing keys can be modified.")
  KeyError: "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."
  --- fake home tree ---            <- no ~/.nedotify/logs/app.log was created
  ```
  Independently: `webview.settings` keys are `['ALLOW_DOWNLOADS','ALLOW_FILE_URLS','OPEN_EXTERNAL_LINKS_IN_BROWSER','OPEN_DEVTOOLS_IN_DEBUG','REMOTE_DEBUGGING_PORT','IGNORE_SSL_ERRORS']`; `webview.settings['WEBVIEW2_RUNTIME_PATH']='x'` → `SET FAILED: KeyError`.
  Note this machine has WebView2 `155.0.4283.60/62` only, so the condition is *not* met here — the bug is latent on this box and fires on any machine with the pinned build.
- **Suggested fix:** do not use `webview.settings` for this. Either drop the assignment (see F-WN-01-2 — the setting is not read by pywebview 5.x anyway) or guard it with `try/except KeyError` and verify that the target pywebview actually consumes the value before relying on it.
- **Fix side effects:** if the pin is genuinely needed, restoring it requires a pywebview that supports `WEBVIEW2_RUNTIME_PATH` **or** passing `browserExecutableFolder` to `CoreWebView2Environment.CreateAsync` — pywebview 5.4 does not expose that, so a pin would need a pywebview patch/upgrade. Removing the pin means machines with the "bad" Evergreen build may hit the documented bridge-injection hang again.
- **Discovered by:** A

#### F-WN-01-2  [P2] — The WebView2 pin is inert under the whole allowed pywebview range: neither `webview.settings['WEBVIEW2_RUNTIME_PATH']` nor `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` is read by pywebview 5.x

- **File:** `main.py:21-30`, `main.py:547`; `requirements.txt:6`
- **Confirmed:** yes (by source inspection of the installed pywebview 5.4)
- **Description:** the documented workaround ("pin WebView2 to 151.0.4129.86 because 151.0.4129.93 hangs bridge injection") cannot take effect with the pinned dependency range. pywebview 5.4 never reads `WEBVIEW2_RUNTIME_PATH` (the string does not occur anywhere in the `webview` package), and `CoreWebView2Environment.CreateAsync` is called with only `userDataFolder=` — no `browserExecutableFolder`. `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` is a Playwright-style variable that the WebView2 runtime does not read. Consequently `main.py:547` always logs `WebView2 runtime setting: default`.
- **Cause:** the pin was written against a pywebview API that the version floor in `requirements.txt` (`>=5.0.0,<6`) no longer provides. The two mechanisms are also independent of each other (one is a pywebview setting, the other an env var), so even one working would not be enough.
- **Trigger conditions:** always — on every machine, with every supported pywebview 5.x.
- **User impact:** the app always runs the Evergreen runtime that WebView2 auto-updates. On a machine where the auto-updated runtime is the "hanging" one, the bridge never becomes ready → the window stays blank for 35 s → the watchdog respawns (F-WN-01-5) → the app appears to be in a restart loop, with no indication of the cause.
- **Evidence:**
  ```python
  # main.py:28-30
  if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2
      os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/edgechromium.py:98-108
  def setup_webview2_environment(self):
      environment = CoreWebView2Environment.CreateAsync(
          userDataFolder=_state['storage_path']
      )
  ```
  grep over `.venv_win\Lib\site-packages\webview\**\*.py` for `WEBVIEW2_RUNTIME_PATH|WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` → **no output**; `inspect.getsource(edgechromium)` contains neither `WEBVIEW2_RUNTIME_PATH` nor `BROWSER_EXECUTABLE`.
- **Reproduction / verification:** `Select-String -Path .venv_win\Lib\site-packages\webview\platforms\*.py -Pattern "WEBVIEW2|browserExecutableFolder"` → the only hits are `WebView2` type names; `edgechromium mentions RUNTIME_PATH: False`, `edgechromium mentions BROWSER_EXECUTABLE: False` (checked with `inspect.getsource`). `webview.settings.get('WEBVIEW2_RUNTIME_PATH','default')` → `default`.
- **Suggested fix:** decide whether the pin is still needed; if yes, implement it through a mechanism pywebview 5.x actually honours (e.g. `CoreWebView2EnvironmentOptions` / a pywebview upgrade), and if no, delete the block together with the misleading comment and the `main.py:547` log line.
- **Fix side effects:** deleting the pin removes the only (non-functional) mitigation for the documented bridge-injection hang; keeping a non-functional pin costs nothing but invites the P0 crash in F-WN-01-1.
- **Discovered by:** A

#### F-WN-01-3  [P1] — The single-instance mutex is released *before* the teardown finishes → two full instances can run against the same profile

- **File:** `main.py:406-408` (`on_closed`), `main.py:427-434` (`_close_handler`), `main.py:557-580` (the real teardown)
- **Confirmed:** yes (ordering read from the source and from pywebview's event semantics)
- **Description:** pywebview fires `window.events.closed` *while the window is being destroyed*, i.e. **before** `webview.start()` returns. `on_closed` releases the instance mutex at that moment. The actual teardown — session save, `app_core.cleanup()`, `api.cleanup()` — happens afterwards, at `main.py:557-580`, and `app_core.cleanup()` joins thread pools and can take seconds. During that window the mutex is free, so a second launch is admitted and builds a complete second instance against the same `~/.nedotify` database, the same settings writer and the same fixed UI port (F-WN-01-4).
- **Cause:** the lock is released on "window closed" rather than on "process finished"; the release is not deferred to the point where the instance has actually stopped owning the shared resources.
- **Trigger conditions:** the user relaunches the app (taskbar shortcut / Start-menu entry / autostart) in the seconds between the window closing and the process exiting. The window is measured in seconds when a download or a provider call is in flight (`core/app.py:562-586` joins the shared pools; the previous audit run measured 4.15 s for a 4 s task).
- **User impact:** two instances write the same settings rows and the same SQLite DB; the second instance's window can end up talking to the *first* instance's pywebview server, in which case its bridge is dead — buttons do nothing and the UI reports nothing. The user sees a window that looks hung.
- **Evidence:**
  ```python
  # main.py:406-411
  def on_closed():
      _INTENTIONAL_CLOSE.set()
      _release_instance_lock()
  window.events.loaded += on_loaded
  window.events.closed += on_closed
  ```
  ```python
  # main.py:555-580  (only reached AFTER webview.start() returns)
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  try:
      ... app_core.session.save_session(...)
  ...
  _release_instance_lock()
  app_core.cleanup()
  ```
  and `main.py:427-434` releases the lock *before* `window.destroy()` is even attempted:
  ```python
  def _close_handler():
      _INTENTIONAL_CLOSE.set()
      _release_instance_lock()
      try:
          window.destroy()
      except Exception:
          logging.debug("_close_handler: suppressed exception", exc_info=True)
  ```
- **Reproduction / verification:** static ordering proof (pywebview `webview/platforms/winforms.py:267` `self.FormClosed += self.on_close` → `self.closed.set()` fires during the window's destruction, before `webview.start()` returns). Timing proof of the teardown length: `core/app.py:562-586` (`shutdown(wait=False)` on every pool) — CPython's `concurrent.futures.thread._python_exit` joins the pool threads at interpreter exit, so an in-flight yt-dlp stream-cache download keeps the process alive for its full duration.
- **Suggested fix:** release the mutex only after `app_core.cleanup()` / `api.cleanup()` have finished (i.e. at the very end of `main()`), and move the release in `_close_handler` to *after* `window.destroy()` succeeds.
- **Fix side effects:** holding the mutex a few seconds longer means a relaunch during that window exits immediately with "another instance is running" instead of starting — the intended single-instance behaviour, but the user must retry a moment later.
- **Discovered by:** A

#### F-WN-01-4  [P2] — The pywebview UI server always binds the fixed port 42001 with `SO_REUSEADDR` → a second instance binds the same port and the bridge traffic is split; a plain port clash kills only the daemon server thread

- **File:** `main.py:13-14`, `main.py:555`
- **Confirmed:** yes — the double-bind was reproduced on this machine; the split-traffic consequence is the documented Windows `SO_REUSEADDR` behaviour
- **Description:** `webview.start(http_server=True, private_mode=False, …)` with no `http_port` makes pywebview substitute `DEFAULT_HTTP_PORT = 42001` (`webview/__init__.py:70,191-196`). The server is a `wsgiref` `WSGIServer`, which has `allow_reuse_address = True` → `SO_REUSEADDR` is set. On Windows that allows a **second** process to bind the same address/port while the first is still LISTENing. Combined with F-WN-01-3 (the mutex is free during teardown) and with the watchdog respawn (F-WN-01-5), two live instances can hold port 42001 simultaneously, and the OS splits the connections between them. The bridge callback endpoint is per-window (`/js_api/<uid>`), so a POST that lands on the wrong server is answered with `JS callback function is not set for window <uid>` — the bridge of the new window is silently dead.
  Separately, if the port is simply occupied by something else, `bottle.run` raises inside the **daemon** server thread: the thread dies, `webview.start()` still returns, and the window navigates to `http://127.0.0.1:42001/index.html` → "connection refused" → a blank window with no in-app explanation.
- **Cause:** a fixed default port plus a global `allow_reuse_address` opt-in, with no `http_port` argument and no readiness check on the server thread.
- **Trigger conditions:** a second instance starting while the first is alive (relauch during teardown, watchdog respawn, or the `Local\`-namespace gap in F-WN-01-16); or any other process on the machine holding 42001.
- **User impact:** a blank window with no error, or a window whose controls do nothing. Both look like "the app is broken" and neither is reported to the user or to `app.log`.
- **Evidence:**
  ```python
  # main.py:555
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/__init__.py:70 and 191-196
  DEFAULT_HTTP_PORT = 42001
  if not _state['private_mode'] and not http_port:
      http_port = DEFAULT_HTTP_PORT
  ```
  ```python
  # main.py:13-14  — note: this monkeypatch is a NO-OP for both servers in use
  import socketserver
  socketserver.TCPServer.allow_reuse_address = True
  ```
  Measured: `WSGIServer.allow_reuse_address = True`, `HTTPServer.allow_reuse_address = True`, `TCPServer.allow_reuse_address = False` — so the patch changes nothing for `webview/http.py` (wsgiref) or `core/proxy.py` (http.server); the `SO_REUSEADDR` that causes the split comes from the stdlib defaults.
- **Reproduction / verification:**
  ```
  first server listening on 55088 SO_REUSEADDR = 1
  SECOND BIND ON THE SAME PORT SUCCEEDED -> ('127.0.0.1', 55088)
  ```
  (two `wsgiref.simple_server.make_server('127.0.0.1', …)` instances on the same port, after `socketserver.TCPServer.allow_reuse_address = True`.)
- **Suggested fix:** pass an explicit free `http_port` (or let pywebview pick a random one by not forcing `private_mode=False` semantics for the port), and set `private_mode=False` without pinning the port; at minimum, detect the server thread's failure and report it instead of showing a blank window. Remove the misleading `main.py:13-14` monkeypatch or narrow it to the server that actually needs it.
- **Fix side effects:** a random port means the URL the WebView navigates to changes per launch; the proxy/UI URLs are internal so this is safe, but any code that hard-codes `42001` would break (grep shows no such reference outside pywebview).
- **Discovered by:** A

#### F-WN-01-5  [P2] — `on_loaded` runs an unguarded `engine._on_track_changed(...)` **before** the session-autoplay emit and the zapret autostart: one exception silently disables both, and the traceback never reaches `app.log`

- **File:** `main.py:389-404`
- **Confirmed:** yes (source reading + pywebview event semantics); the "callback raises" part is confirmed by the previous audit run, which observed `AttributeError: 'NoneType' object has no attribute 'get_proxy_url'` from this exact callback
- **Description:** `on_loaded` is a single handler with three effects: notify the engine of the restored track, emit `session_autoplay`, and start zapret. The first one is an unguarded call into `AppApi._on_track_changed`, which does a DB lookup, a LUFS enrichment, a proxy-URL lookup, a Discord RPC update, an `_emit` and a tray update. The other two are downstream of it and are skipped when it raises.
- **Cause:** ordering plus a missing `try/except` around a call into a subsystem that is known to be able to raise. pywebview's `Event.set()` catches the exception itself (`except Exception as e: logger.exception(e)`) and continues with the *next* handler — but `on_loaded` is one handler, so the remainder of the function is abandoned, and the traceback goes to the **pywebview logger** (stderr only), not to `~/.nedotify/logs/app.log`.
- **Trigger conditions:** any exception inside `AppApi._on_track_changed` while a session is being restored (offline-mode lookup, LUFS enrichment with a partially initialised proxy, a closed/unavailable DB, a tray update failure).
- **User impact:** (a) the restored track never resumes playing — the `session_autoplay` event is never emitted and the UI sits idle; (b) **zapret is never started**, so the anti-censorship bypass is silently off for the whole session; (c) neither is reported anywhere the user or the maintainer looks.
- **Evidence:**
  ```python
  # main.py:389-404
  def on_loaded():
      logging.info(f"[startup] window loaded (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
      if app_core.engine.queue.current_track:
          app_core.engine._on_track_changed(app_core.engine.queue.current_track)   # <-- unguarded
      try:
          if app_core.session.should_autoplay and app_core.engine.queue.current_track:
              api.emit_event("session_autoplay", {...})
      except Exception as ae:
          logging.debug(f"session autoplay emit failed: {ae}")
      threading.Thread(target=app_core.start_zapret_if_enabled, daemon=True).start()
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/event.py:37-56
  def set(self, *args, **kwargs):
      def execute():
          for func in self._items:
              try:
                  ... value = func(*args, **kwargs)
              except Exception as e:
                  logger.exception(e)          # <-- swallowed into the pywebview logger
  ```
  and `webview/window.py:163`: `self.events.loaded = Event(self)` → `should_lock=False` → the handler runs in a throw-away thread, so the exception never reaches `threading.excepthook` either.
- **Reproduction / verification:** `AppApi._on_track_changed` (`core/api.py:1195-1242`) contains several unguarded calls (`available_track(...)`, `self._enrich_track_lufs(track_copy)`, `self._core.proxy.get_proxy_url(...)`, `self._tray.update_state(...)`); `core/api.py:1583-1604`/`1716-1744` were the site of the previously observed `AttributeError` on the same callback. pywebview's swallow is confirmed by reading `webview/event.py` and `webview/window.py` above.
- **Suggested fix:** wrap the `_on_track_changed` call in its own `try/except` (log at ERROR) and move the `session_autoplay` emit and the zapret start **above** it, so no optional callback can suppress a mandatory startup step.
- **Fix side effects:** reordering means the autoplay event may be emitted before the engine knows about the track — the UI receives `session_autoplay` and then `track_changed`; the frontend must tolerate that order (it currently tolerates the reverse).
- **Discovered by:** A

#### F-WN-01-6  [P2] — The 404 "safety net" returns the PNG body with HTTP status **404**, so the browser still treats the image as broken and the `onerror` storm it was written to stop still happens

- **File:** `main.py:454-464` (+ the module comment at `main.py:56-59`)
- **Confirmed:** yes — reproduced against bottle 0.13.4 with a faithful replica of `_install_routes`
- **Description:** `@app.error(404)` returns the 1×1 PNG body for image-looking paths, but bottle applies the `HTTPError`'s status **after** the handler returns, so the response is `404 Not Found` with `Content-Type: image/png`. Browsers decide image success from the HTTP status, not the body: Chromium's image resource fetcher treats any non-2xx as a failed image, discards the body and fires `onerror`. The fallback therefore does not stop the failure it was written for.
- **Cause:** the handler replaces the body but not the status; there is no `bottle.response.status = 200` (and no `bottle.HTTPResponse(..., status=200)`).
- **Trigger conditions:** any image request that is not under `/assets/` or `/covers/` and does not exist on disk — the generic case the comment describes ("Global 404 safety net: intercept any broken image queries").
- **User impact:** the exact failure the module comment blames on "a storm of /assets/*.png 404s that the image onerror handlers amplified until the renderer stalled" still occurs for every image outside the two hard-coded prefixes. (Requests under `/assets/` and `/covers/` *are* handled correctly — see the clean-areas section.)
- **Evidence:**
  ```python
  # main.py:454-464
  @app.error(404)
  def _image_404_handler(error):
      try:
          req_path = _bottle.request.path.lower()
          if any(req_path.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.ico', '.svg', '.gif')):
              _bottle.response.content_type = 'image/png'
              return _FALLBACK_PNG
      except Exception:
          logging.debug("_image_404_handler: suppressed exception", exc_info=True)
      return error.body
  ```
- **Reproduction / verification:** faithful replica of `main.py:417-480` executed against bottle 0.13.4:
  ```
  GET  /assets/logo.png        -> 200 OK            ct=image/png  body=b'REALPNG'
  GET  /assets/missing.png     -> 200 OK            ct=image/png  body=b'\x89PNG\r\n\x1a\nFALLBACK'
  GET  /covers/missing.jpg     -> 200 OK            ct=image/png  body=b'\x89PNG\r\n\x1a\nFALLBACK'
  GET  /images/whatever.png    -> 404 Not Found     ct=image/png  body=b'\x89PNG\r\n\x1a\nFALLBACK'
      calls=[('pywebview-catchall','images/whatever.png'), ('_image_404_handler','404 Not Found')]
  GET  /nope.html              -> 404 Not Found     ct=text/html   body=b'File does not ex'
  POST /__aura_close           -> 200 OK            body=b'ok'
  ```
- **Suggested fix:** set `bottle.response.status = 200` (and keep the PNG body) inside the 404 handler for image paths, so the browser accepts the image; or serve the fallback through an explicit route instead of an error handler.
- **Fix side effects:** returning 200 for a missing asset hides genuine 404s from the UI and from server-side logs; the fallback should be distinguishable (e.g. a dedicated header) if that matters.
- **Discovered by:** A

#### F-WN-01-7  [P2] — The PyInstaller spec never collects `curl_cffi`'s native library → the packaged exe's SoundCloud / impersonation path cannot load `libcurl-impersonate-*.dll`

- **File:** `setup_pyinstaller.spec:27`, `setup_pyinstaller.spec:37-66` (hiddenimports)
- **Confirmed:** yes (file layout verified in the venv; the hook's behaviour read from yt-dlp's own PyInstaller hook)
- **Description:** `curl_cffi` 0.16.3 is a delvewheel wheel: the native DLL lives **outside** the package, in `site-packages/curl_cffi.libs/libcurl-impersonate-<hash>.dll` (3.9 MB), and `curl_cffi/__init__.py` adds that sibling directory to the DLL search path with `os.add_dll_directory(...)` — but only `if os.path.isdir(libs_dir)`. The spec's only involvement with `curl_cffi` is indirect: yt-dlp's own hook (`yt_dlp/__pyinstaller/hook-yt_dlp.py`) yields `'curl_cffi'` as a hidden import and collects `collect_data_files('curl_cffi', includes=['cacert.pem'])`. Neither the hook nor the spec collects `curl_cffi.libs`. In a onefile build the package lands in `sys._MEIPASS/curl_cffi`, so the sibling path becomes `sys._MEIPASS/curl_cffi.libs`, which does not exist → `os.add_dll_directory` is skipped → `import curl_cffi._wrapper` fails to load the DLL.
- **Cause:** a delvewheel-style `.libs` sibling directory is invisible to `collect_data_files('curl_cffi')` (it lives outside the package) and to PyInstaller's dependency scanner (the DLL is not in any collected binary's directory).
- **Trigger conditions:** any use of the impersonating HTTP stack in the packaged build — i.e. the SoundCloud extractor, which `requirements.txt:10-13` explicitly states must have it ("Without it the extractor logs 'attempting impersonation, but no impersonate target is available' and SoundCloud metadata fetches fail").
- **User impact:** in the installed app, SoundCloud metadata lookups fail with an impersonation error while the same code works in the dev venv. The failure surfaces as an empty/failed SoundCloud search, which reads like "SoundCloud is broken" rather than "the packaging missed a DLL".
- **Evidence:**
  ```
  .venv_win/Lib/site-packages/curl_cffi.libs/libcurl-impersonate-1172405423dc93b7aeed557f2a2ca325.dll  (3 885 056 bytes)
  ```
  ```python
  # .venv_win/Lib/site-packages/curl_cffi/__init__.py:1-8
  def _delvewheel_patch_1_13_1():
      import os
      if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'curl_cffi.libs'))):
          os.add_dll_directory(libs_dir)
  ```
  ```python
  # .venv_win/Lib/site-packages/yt_dlp/__pyinstaller/hook-yt_dlp.py
  yield from ('mutagen', 'brotli', 'certifi', 'secretstorage', 'curl_cffi')
  datas = collect_data_files('curl_cffi', includes=['cacert.pem'])
  datas += collect_data_files('yt_dlp_ejs', includes=['**/*.js'])
  ```
  (`cacert.pem` does not even exist in curl_cffi 0.16.3 — the wheel's RECORD lists only the `.pyd` and the `.dll`.)
- **Reproduction / verification:** listed `site-packages/curl_cffi*` — the package contains only `.py` files plus `_wrapper.pyd`; the DLL is in the sibling `curl_cffi.libs` directory, which no hook in `.venv_win\Lib\site-packages\_pyinstaller_hooks_contrib` or in `yt_dlp/__pyinstaller` collects (`hook-curl_cffi.py` does not exist in pyinstaller-hooks-contrib).
- **Suggested fix:** add `collect_dynamic_libs('curl_cffi.libs')` (or `collect_data_files('curl_cffi.libs')`) to `datas` in the spec, and verify the frozen exe can `import curl_cffi` and perform an impersonated request.
- **Fix side effects:** +3.9 MB on the onefile exe; the DLL must be shipped next to the package at exactly `curl_cffi.libs` (delvewheel's layout) or `add_dll_directory` must be bypassed.
- **Discovered by:** A

#### F-WN-01-8  [P2] — The DoH fallback is inert whenever any proxy is configured, because `urllib.request.urlopen` honours the system/env proxy and resolving the *proxy's* name re-enters the patched resolver

- **File:** `main.py:199-223` (the DoH request loop), `main.py:225` (the global patch)
- **Confirmed:** yes — the proxy handling and the re-entrant resolution were both reproduced
- **Description:** `_doh_getaddrinfo` resolves the DoH endpoint with `urllib.request.urlopen`. `urlopen` uses the default opener, which contains a `ProxyHandler` built from `getproxies()` (on Windows: the registry `ProxyEnable`/`ProxyServer`, plus `HTTPS_PROXY`). When a proxy is configured, `urlopen` connects to the **proxy host by name**; that name lookup goes through the patched `socket.getaddrinfo`, whose thread-local re-entrancy guard is already active → it raises `gaierror` → `urlopen` fails → the `except Exception: continue` swallows it and the next endpoint is tried — all three fail the same way → `socket.gaierror("All DoH endpoints failed for …")`.
- **Cause:** the DoH transport uses the same resolver stack it is trying to replace, and the recursion guard (correctly) refuses to resolve the proxy name — but no transport-level bypass of the proxy was added.
- **Trigger conditions:** any HTTP(S) proxy configured for the user (system proxy, `HTTPS_PROXY`, a corporate proxy). This machine is in exactly that state (see evidence).
- **User impact:** the DNS fallback is dead exactly in the filtered-DNS environment it was written for, and the failure is invisible: the lookup still fails with the original `gaierror`, so the caller sees "DNS failure" and never learns that the fallback ran and gave up.
- **Evidence:**
  ```python
  # main.py:200-220
  for doh_url in [
      f"https://1.1.1.1/dns-query?name={host}&type=A",
      f"https://8.8.8.8/resolve?name={host}&type=A",
      f"https://77.88.8.8/dns-query?name={host}&type=A"
  ]:
      try:
          ctx = ssl.create_default_context()
          req = urllib.request.Request(doh_url, headers={...})
          with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp:
              ...
      except Exception:
          continue
  raise socket.gaierror(f"All DoH endpoints failed for {host!r}")
  ```
  ```python
  # main.py:195-196
  if getattr(_doh_inflight, 'active', False):
      raise socket.gaierror(f"DoH fallback busy resolving {host!r}")
  ```
- **Reproduction / verification:**
  ```
  getproxies(): {'ag_ls': 'http://127.0.0.1:53129', 'no': '127.0.0.1,localhost,::1', 'https': 'http://127.0.0.1:53129'}
  ProxyHandler proxies: {… 'https': 'http://proxy.local:3128'}
  connect failed as expected: gaierror [Errno 11001] getaddrinfo failed
  getaddrinfo calls during connect: [('proxy.local', 3128)]
  ```
  (i.e. `http.client` → `socket.create_connection` → the module-global `getaddrinfo`, which `main.py` has replaced.)
- **Suggested fix:** build the DoH transport with an opener that has **no** proxy handler (`urllib.request.build_opener(urllib.request.ProxyHandler({}))`) — the endpoints are IP literals, so they are reachable directly — or resolve/connect to them over a raw socket.
- **Fix side effects:** a proxy-only network (no direct route to 1.1.1.1/8.8.8.8/77.88.8.8) would stop working for the DoH path; the current behaviour "works" only when there is no proxy at all.
- **Discovered by:** A

#### F-WN-01-9  [P2] — A failed DNS lookup blocks the calling thread for up to ~6 s (3 × 2 s DoH timeouts) — inside a bridge whose whole budget is 6 s

- **File:** `main.py:180-223`
- **Confirmed:** yes (code path + timeout arithmetic)
- **Description:** `_doh_getaddrinfo` first calls the original resolver (which itself may block for the OS DNS timeout) and then tries up to three DoH endpoints with `timeout=2.0` each, sequentially, on the caller's thread. The fallback therefore converts a fast `gaierror` into a multi-second stall for **every** thread that resolves a name.
- **Cause:** the DoH attempts are synchronous and serial inside the patched `getaddrinfo`; there is no overall deadline and no negative caching of "this host does not resolve".
- **Trigger conditions:** any DNS failure (offline, filtered DNS, a dead provider host) on any thread — including the pywebview bridge thread.
- **User impact:** a provider whose host does not resolve makes the corresponding bridge call consume the entire `BRIDGE_SYNC_BUDGET` (6 s, `core/api.py:67`) before it can even report the error → the UI shows a frozen control for seconds instead of a fast error. With several providers failing, the calls serialise behind each other.
- **Evidence:**
  ```python
  # main.py:209
  with urllib.request.urlopen(req, timeout=2.0, context=ctx) as resp:
  ```
  ```python
  # main.py:180-184
  def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
      try:
          return _orig_getaddrinfo(host, port, family, type, proto, flags)
      except socket.gaierror:
          pass
  ```
- **Reproduction / verification:** three sequential `urlopen(..., timeout=2.0)` calls ⇒ a worst case of 6 s per name, on top of the OS resolver's own timeout; the `for`/`continue` structure guarantees all three are attempted before the final `gaierror`.
- **Suggested fix:** give the fallback a single overall deadline (e.g. 2 s for all endpoints), try the endpoints in parallel, and/or add a short negative cache so a repeatedly failing host is not re-resolved through DoH on every call.
- **Fix side effects:** a tighter deadline lowers the chance of getting a DoH answer on a slow link; a negative cache delays picking up a host that starts resolving later (keep the negative TTL short).
- **Discovered by:** A

#### F-WN-01-10  [P3] — The DoH cache evicts by *insertion* position, so a refreshed entry is the first one evicted

- **File:** `main.py:212-217`
- **Confirmed:** yes (CPython dict semantics)
- **Description:** the size cap pops `next(iter(_dns_cache))`, i.e. the oldest *inserted* key. Re-assigning an existing key (`_dns_cache[host] = …`) updates the value but does **not** move the key to the end of the iteration order, so a host whose TTL was just renewed keeps its original (old) position and is evicted before the other entries.
- **Cause:** `dict` insertion order is not affected by re-assignment, but the eviction logic assumes it is.
- **Trigger conditions:** more than 256 distinct hosts are resolved through the fallback and at least one of them is refreshed.
- **User impact:** the host that was just renewed can be evicted from the cache immediately → the next lookup for it pays the full DoH round trip again (up to 6 s, F-WN-01-9). Cosmetic-to-mild performance impact.
- **Evidence:**
  ```python
  # main.py:213-217
  with _dns_cache_lock:
      if len(_dns_cache) >= _DNS_CACHE_MAX:
          oldest = next(iter(_dns_cache))
          _dns_cache.pop(oldest, None)
      _dns_cache[host] = (ips[0], _time.monotonic())
  ```
- **Reproduction / verification:** `dict` semantics — `d={'a':1,'b':2}; d['a']=3; list(d)` → `['a','b']` (position unchanged). The cache is also not an `OrderedDict`/`move_to_end` structure.
- **Suggested fix:** pop the entry and re-insert it (`_dns_cache.pop(host, None)` before the assignment) so a refresh moves it to the end, or evict by the oldest `monotonic` timestamp instead of by iteration order.
- **Fix side effects:** none; the cache stays bounded at `_DNS_CACHE_MAX`.
- **Discovered by:** A

#### F-WN-01-11  [P3] — The session is persisted only on the window-close path; there is no signal, `atexit` or `WM_QUERYENDSESSION` handling, so any other exit loses the queue and the playback position

- **File:** `main.py:557-580` (the only `save_session` call), `main.py:88-145` (no signal/atexit registration)
- **Confirmed:** yes
- **Description:** `save_session` is called exactly once, after `webview.start()` returns. There is no `signal.signal(SIGTERM, …)`, no `atexit.register` for the session and no Windows `WM_QUERYENDSESSION` / `CTRL_CLOSE_EVENT` handling in `main.py`. `core/settings.py:313` registers `atexit.register(self.flush)` — that only flushes *pending* settings writes, it never writes the session, because the session is only written by `save_session`.
- **Cause:** the shutdown path is modelled exclusively on "the user closed the window".
- **Trigger conditions:** `taskkill /f`, End-Task in Task Manager, a Windows logoff/shutdown that kills the process, an unhandled crash, or a `SIGTERM` from a script/service manager.
- **User impact:** the user's queue (up to 200 tracks), the current track and the playback position are lost — the next launch starts with an empty queue. Downloaded files and the library are unaffected (they are in the DB and on disk).
- **Evidence:**
  ```python
  # main.py:557-571
  # Save session before exit
  try:
      engine = app_core.engine
      ...
      app_core.session.save_session(...)
  except Exception as e:
      print(f"Failed to save session: {e}")
  ```
  `grep -n "signal\|atexit" main.py` → no matches.
- **Reproduction / verification:** static — `save_session` appears once in `main.py`; `core/session.py:39-68` shows the session is stored exclusively through `settings.set("session", …)`.
- **Suggested fix:** register an `atexit` handler (and a `SIGTERM` handler where the platform provides one) that performs the same `save_session` + `settings.flush()` pair, guarded so it does not double-write on the normal path.
- **Fix side effects:** `atexit` handlers do not run on `os._exit()` (the watchdog path already flushes settings explicitly there); a crash-time save may write a partially-updated queue — the session writer must be defensive about `queue_index` vs. the actual queue length.
- **Discovered by:** A

#### F-WN-01-12  [P3] — Startup and shutdown failures are reported with `print()`, which is a no-op in the packaged (`console=False`) build

- **File:** `main.py:330`, `main.py:571` (+ `setup_pyinstaller.spec:104` `console=False`)
- **Confirmed:** yes
- **Description:** the two failure paths of the bootstrap sequence report through `print()` instead of `logging`. In the frozen build there is no console: `console=False` → `sys.stdout` is `None` → `print()` silently does nothing. The rotating log handler is installed *after* these points in the module, but at the time these two lines run it is already active — the messages simply never reach it.
- **Cause:** `print` was used before the logging configuration existed and was never converted.
- **Trigger conditions:** an exception while restoring the session (`main.py:329-330`) or while saving it (`main.py:570-571`).
- **User impact:** the app starts with no queue and no explanation in `app.log`; the user sees a "forgotten" library/queue with zero diagnostics. This is exactly the "failure mode here is silence" the project rules call out.
- **Evidence:**
  ```python
  # main.py:329-330
  except Exception as e:
      print(f"Failed to restore session: {e}")
  ...
  # main.py:570-571
  except Exception as e:
      print(f"Failed to save session: {e}")
  ```
- **Reproduction / verification:** `setup_pyinstaller.spec:104` sets `console=False`; `webview/http.py:8-12` shows the frozen process has `sys.stdout is None` (pywebview redirects stderr, stdout stays `None`), and CPython's `print()` is a no-op when `sys.stdout` is `None`.
- **Suggested fix:** use `logging.exception(...)` (or `logging.error(..., exc_info=True)`) in both places.
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-01-13  [P3] — Three bottle-layer failures are logged at `logging.debug` while the root logger is at INFO → the route installer, the cache hook and the router recompile can fail invisibly

- **File:** `main.py:74-75`, `main.py:85-86`, `main.py:475-476` (+ the root level at `main.py:104-117`)
- **Confirmed:** yes
- **Description:** `logging.basicConfig(level=logging.INFO, …)` sets the root logger to INFO, so every `logging.debug(...)` in `main.py` is dropped. The three bottle-layer failure paths — the `after_request` cache hook, the bottle capture itself, and the router recompile — are logged exclusively at debug level. The router recompile in particular is the step that makes the custom routes beat pywebview's catch-all; if it fails halfway, the router is left partially rebuilt and **every** URL 404s, with nothing in `app.log`.
- **Cause:** `logging.debug` was used where a degraded-but-operational state should be recorded at WARNING/ERROR.
- **Trigger conditions:** any exception inside `app.hook('after_request')`, inside `app.router.add(...)` (e.g. a malformed rule coming from a `ui/MACos_ui` file name), or a bottle API change.
- **User impact:** the app starts and serves nothing (blank page), and the maintainer finds no entry in `~/.nedotify/logs/app.log` explaining why.
- **Evidence:**
  ```python
  # main.py:74-75
  except Exception:
      logging.debug("Cache-Control hook install failed", exc_info=True)
  # main.py:85-86
  except Exception:
      logging.debug("Bottle capture unavailable", exc_info=True)
  # main.py:475-476
  except Exception as re_err:
      logging.debug(f"[startup] Router recompile note: {re_err}")
  ```
- **Reproduction / verification:** `logging.basicConfig(level=logging.INFO)` → the root logger's effective level is INFO; `logging.debug(...)` on the root logger is therefore filtered out (no handler is invoked). The file handler installed at `main.py:110-115` does not change the level.
- **Suggested fix:** log these three failures at WARNING/ERROR with `exc_info=True`; the router recompile in particular must be ERROR, because a partial router is fatal.
- **Fix side effects:** more log noise if the cache hook fails for benign reasons — but the cache hook failing is not benign.
- **Discovered by:** A

#### F-WN-01-14  [P3] — `bottle` is imported directly by application code but is absent from `requirements.txt`

- **File:** `main.py:62` (`import bottle as _bottle`), `core/ui_assets.py:6` (`import bottle`), `requirements.txt:1-25`
- **Confirmed:** yes
- **Description:** `main.py` imports `bottle` at module level to capture `bottle.run` and to install the cache hook / routes, and `core/ui_assets.py` imports it to register the legacy CSS pack. `requirements.txt` does not list `bottle`; it is only present transitively because `pywebview` requires it (`pywebview-5.4.dist-info/METADATA: Requires-Dist: bottle`).
- **Cause:** the dependency was never declared although the code imports it directly.
- **Trigger conditions:** any environment where pywebview drops or changes its `bottle` requirement (pywebview is allowed to move to 6.0 by `<6` → 6 is excluded, but the requirement itself is unpinned and unversioned) or where a future pywebview bundles bottle differently.
- **User impact:** the bottle route capture (and with it the bridge-free close route, the asset fallbacks and the no-cache headers) silently disappears — the `except Exception` at `main.py:85-86` swallows the ImportError — and the app degrades to "no bridge-free close" with no diagnostic.
- **Evidence:**
  ```python
  # main.py:61-66
  try:
      import bottle as _bottle
      _orig_bottle_run = _bottle.run
  …
  except Exception:
      logging.debug("Bottle capture unavailable", exc_info=True)
  ```
- **Reproduction / verification:** an AST scan of all application modules (excluding `android/`, `tests/`, `tools/`) lists the third-party top-level imports: `PIL, System, bottle, clr, miniaudio, mutagen, numpy, pyloudnorm, pypresence, pystray, requests, watchdog, webview, yandex_music, yt_dlp, ytmusicapi` (+ `pytest` in `run_tests.py`). Every one of them is in `requirements.txt` / `requirements-dev.txt` **except `bottle`**.
- **Suggested fix:** add `bottle>=0.13,<1` to `requirements.txt`.
- **Fix side effects:** none — the installed version already satisfies it.
- **Discovered by:** A

#### F-WN-01-15  [P3] — `pystray>=0.19.5,<0.21` admits 0.19.5, which does not export `Separator`; `core/tray.py` imports it unconditionally, so the tray is permanently disabled with an allowed version

- **File:** `requirements.txt:18`, `core/tray.py:13-19`
- **Confirmed:** yes — the installed 0.19.5 has no `Separator`
- **Description:** the requirement range starts at exactly the version that broke the import. `core/tray.py` does `from pystray import MenuItem as item, Menu, Separator` inside a `try`, and the `except (ImportError, Exception)` sets `HAS_PYSTRAY = False` for the whole process. The spec's `hiddenimports` include `pystray` and `PIL`, so the packaging is fine — the *version floor* is wrong.
- **Cause:** the requirement was written without checking the API the code actually uses.
- **Trigger conditions:** any install that resolves pystray to 0.19.5 (the floor of the allowed range) — which is what the project venv has.
- **User impact:** the system-tray icon and its menu never appear; "minimise to tray" cannot work and the app quits instead. (The tray defect itself belongs to WN-16 / `core/tray.py`; the *requirements* defect is WN-01's.)
- **Evidence:**
  ```python
  # core/tray.py:13-19
  try:
      from PIL import Image
      import pystray
      from pystray import MenuItem as item, Menu, Separator
      HAS_PYSTRAY = True
  except (ImportError, Exception):
      HAS_PYSTRAY = False
  ```
  ```python
  # requirements.txt:18
  pystray>=0.19.5,<0.21
  ```
  Measured in the project venv: `pystray` exports `['Icon','Menu','MenuItem','os','sys']` → `has Separator: False`; `pystray.Menu.SEPARATOR` **does** exist (`hasattr(pystray.Menu,'SEPARATOR') → True`).
- **Reproduction / verification:** `python -c "import pystray; print(hasattr(pystray,'Separator'))"` → `False`. Consequently `from pystray import … Separator` raises `ImportError` and `HAS_PYSTRAY` is `False` for the whole process.
- **Suggested fix:** either raise the floor to the pystray release that exports `Separator`, or (better, and it also fixes WN-16) change `core/tray.py` to use `Menu.SEPARATOR`, which exists in 0.19.5 as well.
- **Fix side effects:** raising the floor forces a reinstall for existing users; using `Menu.SEPARATOR` requires no dependency change at all.
- **Discovered by:** A

#### F-WN-01-16  [P3] — The `network` marker is never used and `pytest-asyncio` is an unused dependency → the documented "network tests are deselected by default" guarantee is inert

- **File:** `pytest.ini:3-5`, `requirements-dev.txt:2`
- **Confirmed:** yes
- **Description:** `pytest.ini` declares a `network` marker and `addopts = -m "not network"`, and the project brief states that the network marker is deselected by default. **No test in `tests/` uses that marker** (0 matches for `pytest.mark.network` / `mark.network`), so the deselection excludes nothing. Conversely `pytest-asyncio` is installed and pinned but no test uses `pytest.mark.asyncio` and `pytest.ini` sets no `asyncio_mode`, so the plugin is loaded and does nothing.
- **Cause:** the marker vocabulary and the plugin were added without the corresponding tests, or the tests that used them were converted/removed and the configuration was not updated.
- **Trigger conditions:** always.
- **User impact:** the safety net that is supposed to keep the default suite offline is not actually enforced by the marker — it currently rests solely on every test being individually hermetic (`tests/conftest.py` redirects `~` and stubs the providers). If a network-touching test is added without the marker, it will run in the default suite.
- **Evidence:**
  ```ini
  # pytest.ini
  [pytest]
  testpaths = tests
  markers =
      network: test performs real network I/O (deselected by default)
  addopts = -m "not network"
  ```
  ```text
  # requirements-dev.txt
  pytest==9.1.1
  pytest-asyncio==1.4.0
  ```
  Measured: `Select-String tests\*.py -Pattern "mark\.network"` → **0**; `Select-String tests\*.py -Pattern "pytest\.mark\.asyncio|asyncio_mode|pytest_asyncio"` → **0**.
- **Suggested fix:** either mark the tests that really touch the network (and keep the deselection), or delete the unused marker, the unused `addopts` filter and the unused `pytest-asyncio` dependency so the configuration reflects reality.
- **Fix side effects:** adding the marker to the currently-unmarked network-touching tests would change how long the default suite takes and might require network access in CI; removing it changes nothing today.
- **Discovered by:** A

#### F-WN-01-17  [P3] — The installer forces Russian text on every language, including the English one it offers

- **File:** `installer.iss:48`, `installer.iss:68-75` (+ the language list at `installer.iss:30-32`)
- **Confirmed:** yes
- **Description:** the installer declares an English language (`Name: "english"; MessagesFile: "compiler:Default.isl"`), but `InitializeWizard` overwrites the welcome-page caption with hard-coded Russian text, and the Start-menu uninstall shortcut is named `"Удалить NeDotify"` regardless of the selected language.
- **Cause:** the strings were hard-coded instead of being put in the `.isl` files / referenced through `{cm:…}` constants.
- **Trigger conditions:** installing with the English language selected (or any language other than Russian).
- **User impact:** an English-speaking user gets a Russian welcome page and a Russian-named uninstall shortcut. Cosmetic, but it is the first thing a user sees of the product and it contradicts the declared language support.
- **Evidence:**
  ```ini
  ; installer.iss:47-48
  Name: "{group}\NeDotify"; Filename: "{app}\NeDotify.exe"; …
  Name: "{group}\Удалить NeDotify"; Filename: "{uninstallexe}"
  ```
  ```pascal
  ; installer.iss:68-75
  procedure InitializeWizard();
  begin
    WizardForm.WelcomeLabel2.Caption :=
      'Добро пожаловать в установщик NeDotify Beta 5.' + #13#10 + #13#10 + …
  end;
  ```
- **Reproduction / verification:** static read of `installer.iss:30-32` (both languages declared) versus `:48` and `:68-75` (hard-coded Russian).
- **Suggested fix:** move the caption and the shortcut name into the language files (or use `{cm:…}` constants) and select them per language.
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-01-18  [P3] — The single-instance mutex lives in the `Local\` namespace, so two Windows sessions of the same user can each start an instance against the same `~/.nedotify` profile

- **File:** `main.py:260`
- **Confirmed:** yes (namespace semantics); the practical impact is an inference
- **Description:** the mutex is created as `"Local\\NeDotify_App_Single_Instance_Mutex"`. The `Local\` namespace is per **logon session**, not per user. A user signed in simultaneously on the console and over RDP (or two fast-user-switching sessions) therefore gets two independent mutexes, and both instances open the same `~/.nedotify/nedotify_storage.db`, the same downloads folder and the same fixed UI port 42001 (F-WN-01-4).
- **Cause:** a session-scoped object was used to enforce a user-scoped invariant.
- **Trigger conditions:** the same Windows user active in two sessions at the same time.
- **User impact:** two writers on one SQLite DB (WAL keeps it consistent, but the settings rows and the download queue fight), two instances racing for port 42001, and — because the second instance's `pywebview` server may lose the port — a blank window.
- **Evidence:**
  ```python
  # main.py:260
  _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\NeDotify_App_Single_Instance_Mutex")
  ```
- **Reproduction / verification:** the `Local\` / `Global\` prefix semantics of the Win32 named-object namespace (`Local\` = the session's namespace). Confirmed by reading the creation call; the concurrent-session scenario was not reproduced here (no second session available on the audit machine).
- **Suggested fix:** use `"Global\\NeDotify_App_Single_Instance_Mutex"` (a `Global\` object needs no extra privilege when created by the same user) or additionally guard on the profile directory.
- **Fix side effects:** a `Global\` mutex is visible to all sessions of the machine — the intended behaviour — but it must still be per-user, so include the user SID in the name to avoid one user blocking another.
- **Discovered by:** A

---

### 3. Clean areas

- **The Bottle route capture is correct, lossless and correctly ordered** (`main.py:61-86`, `main.py:417-480`). Reproduced against bottle 0.13.4 with a faithful replica: `bottle.run` is called by pywebview as `bottle.run(app=app, server=…, port=…, quiet=…)` — keyword `app` — so the wrapper's `app=None, **kwargs` signature intercepts it; `_BOTTLE_APP[0]` and `_ROUTE_INSTALLER[0]` are both populated before the server starts (`_ROUTE_INSTALLER[0] = _install_routes` at `main.py:543` precedes `webview.start()` at `main.py:555`). The router recompile (`app.router.__init__()` + re-`add` in `app.routes` order) is **not** lossy: all six routes survive, no duplicates, and the custom routes (`/__aura_close`, `/assets/…`, `/covers/…`) are matched before pywebview's `/<file:path>` catch-all. Measured: `GET /assets/logo.png → 200`, `GET /assets/missing.png → 200 + PNG`, `GET /covers/missing.jpg → 200 + PNG`, `POST /__aura_close → 200`. Note the reordering depends on the `app.router.__init__()` reset — without it, `Router.add` overwrites in place and the catch-all keeps priority.
- **The `/assets/` and `/covers/` fallback routes work as intended** — missing files return **HTTP 200** with the 1×1 PNG and `Content-Type: image/png`; existing files are served by `bottle.static_file` with the correct content type.
- **The `after_request` cache hook is installed on the right object** (`app.hook('after_request')` on the captured Bottle app) and sets `Cache-Control/Pragma/Expires` on the pywebview server's responses.
- **The single-instance lock is crash-safe and leaves no stale lock.** `CreateMutexW` is a kernel object: the handle is closed by `CloseHandle` on the normal paths and by the OS when the process dies, so a crashed run never leaves the mutex behind. `GetLastError()` is read immediately after `CreateMutexW` and the handle is checked first (`if _INSTANCE_MUTEX and kernel32.GetLastError() == ERROR_ALREADY_EXISTS`), so the "already running" detection is correct. The non-Windows PID-file fallback also tolerates a stale file (it probes `os.kill(pid, 0)`), although that branch is dead code for this product.
- **The watchdog respawn is correctly capped at one.** `NEDOTIFY_RESTART_COUNT` is read from the environment, `restart_count >= 1` aborts the respawn, the child inherits `NEDOTIFY_RESTART_COUNT=1`, so the loop cannot run forever. `restart_args` is correct in both modes (`[sys.executable] + sys.argv[1:]` when frozen, `[sys.executable] + sys.argv` otherwise). The watchdog also checks `_INTENTIONAL_CLOSE` after the wait, so a user closing a hung window does not trigger a respawn.
- **The excepthook installation is correct.** `sys.excepthook` forwards `KeyboardInterrupt` to `sys.__excepthook__` and logs everything else at CRITICAL with `exc_info`; `threading.excepthook` ignores `SystemExit` (so a normal `sys.exit(0)` is not logged as a crash) and records the thread name. Both land in `~/.nedotify/logs/app.log` via the rotating handler installed at `main.py:104-117`.
- **The session write ordering on the normal close path is correct**: `save_session()` (which calls `settings.flush()` synchronously) runs **before** `app_core.cleanup()` closes the database, so the queue, index, position, shuffle and repeat are durable when the user closes the window. `settings.sync_flush_now()` is called before `os._exit(3)` in the watchdog path, so the `os._exit` does not lose pending settings.
- **`sys._MEIPASS` handling in `main.py:333-339` is correct** for the onefile build (`base_dir = sys._MEIPASS`, `html_path = <MEIPASS>/ui/web_new_v2/index.html`), and the spec bundles `ui/web_new_v2` and `ui/MACos_ui` to exactly those relative destinations.
- **The PyInstaller datas filter does work** (contrary to a first reading): `Analysis.__init__` expands the directory tuples into individual `(dest, src, 'DATA')` entries **before** the spec's `a.datas = [...]` filter runs, and `d[0]` is the *destination* path — so `ui/web_new_v2/covers/**` is correctly excluded. (The directory does not currently exist in the repo, so the filter is presently a no-op, but it is not broken.)
- **The packaging collects the pieces it needs**: pywebview's own hook (`webview/__pyinstaller/hook-webview.py`) collects `webview/lib` (the WebView2 interop DLLs) and `webview/js`; yt-dlp's hook collects the 941 extractors, `yt_dlp_ejs`'s `*.js` challenge scripts and `curl_cffi`; `pystray`, `clr`/`pythonnet`, `bottle`, `miniaudio`, `numpy`, `pyloudnorm`, `mutagen.*`, `PIL` are all in `hiddenimports`; `upx=False` and `console=False` are deliberate and documented.
- **The installer↔application autostart contract holds**: both write `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` with the value name `NeDotify` (`installer.iss:59` vs `core/api.py:49`), both write the frozen path quoted, and the installer's `RemoveLegacyAutostart()` drops the stale "AURA Music" value after install. `UninstallDelete` is scoped to `{app}` only, so the user's `~/.nedotify/` library survives an uninstall (per the project's non-negotiable rule 3).
- **`run_tests.py` / `pytest.ini` are consistent**: `run_tests.py` delegates to `pytest.main([])`, so `pytest.ini` stays the single source of truth (`testpaths = tests`, the `network` marker, the `-m "not network"` filter). `pytest.main([])` correctly falls back to `testpaths`.

---

### 4. Coverage gaps

- **No packaged build was produced.** PyInstaller and Inno Setup were not executed (the environment has PyInstaller 6.22.3 but no Inno Setup compiler), so the packaging findings (F-WN-01-7) rest on the wheel/hook layout and on the stdlib/PyInstaller sources, not on an actual frozen exe. A real build would also settle whether any *other* runtime data file is missing.
- **The WebView2 runtime behaviour could not be exercised.** No WebView2 runtime was launched (running the real app is forbidden by the audit rules). F-WN-01-1 was reproduced by importing `main.py` in isolation; F-WN-01-2 rests on reading pywebview 5.4's `edgechromium`/`winforms` sources. Whether a pinned runtime can be selected at all with pywebview 5.x was not tested on a live window.
- **The "traffic split on port 42001" consequence in F-WN-01-4 was not observed end-to-end** — the double *bind* was reproduced, but not the resulting split of `/js_api/<uid>` requests between two live instances (that needs two real windows).
- **The DoH findings (F-WN-01-8/9/10) were verified statically and with an offline proxy simulation**, not against a genuinely DNS-blocked ISP. The "no proxy → DoH works" direction was not exercised either (it would require outbound network access to 1.1.1.1/8.8.8.8/77.88.8.8).
- **The crash-safety of `core/app.py::cleanup()` (thread-pool joins, DB close ordering) was not re-reviewed** — it belongs to WN-02 and was only read to establish the length of the teardown window used in F-WN-01-3.
- **The Inno Setup semantics of `CloseApplications` for the *uninstaller*** were not verified (Inno Setup is not installed here). If the uninstaller does not close a running `NeDotify.exe`, `UninstallDelete`'s `filesandordirs` on `{app}` would fail with "Access is denied" — I did not want to report that without the Inno documentation at hand, so it is left out of the finding list.
- **`main.py`'s interaction with `core/api.py::update_autostart` was only checked for the registry contract**; the WN-08 behaviour of the autostart toggle itself was not reviewed.
- **`setup_pyinstaller.spec` was not validated against a real `pyinstaller` run**, so the completeness of `hiddenimports` for every dynamically imported module in `core/` and `services/` (e.g. `yandex_music`, `pypresence`, `miniaudio` submodules) is unproven beyond the static listing above.
- **The `~/.nedotify/` profile was never opened**, so the real on-disk shape of the restored session (and whether `last_queue_index` round-trips as an `int` in practice) was verified only from the serialization code (`core/database.py::_serialize_setting` + `get_all_settings` JSON round-trip), not from a live profile.
