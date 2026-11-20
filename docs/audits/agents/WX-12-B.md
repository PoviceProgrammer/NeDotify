## WX-12 — Background/foreground, minimise-to-tray, mini-player, and app restart state continuity — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` L1–120 (module header, `_MAIN_THREAD`, window size constants), L240–305 (secret masking), L330–520 (`__init__`, bridge wrapping, `cleanup`), **L514–600** (`set_window`, `_install_snap_layouts`, `_on_minimized`/`_on_restored`), L605–630 (`_fit_window_content`, `_on_window_resized`), L629–760 (DPI/workarea/geometry), **L721–736** (`_deferred_window_op`), L737–748 (`_on_window_ui_thread`), L749–772 (`_native_window_geometry`), **L773–916** (`toggle_mini_player`, `_enter_mini_mode`, `_exit_mini_mode`, `_set_native_window_corners`, `set_mini_player_position`, `_apply_window_pos`, `set_windows`), **L917–938** (`close`), L940–1052 (`shutdown`, `minimize`, `begin_window_drag`, `begin_window_resize`, `_get_hwnd`), L1053–1160 (`_change_maximized_state`, `restore`, `maximize`, `_emit`), L1195–1270 (`_on_track_changed`), L1950–2010 (`set_volume`, `toggle_mute`), L2730–2760 (`set_snap_button_rect`), L2750–2840 (`complete_onboarding`), L2918–2965 (`get_settings`/`save_setting`)
- `core/snap_layouts.py` L1–357 (whole file: `install`, `uninstall`, `_wndproc`, `_hit_test`, `_refresh_frame`)
- `core/tray.py` L1–194 (whole file)
- `core/session.py` L1–96 (whole file)
- `core/settings.py` L52–118 (defaults incl. `session`, `efficiency`, `optimization`), L290–360 (`__init__`, `_load_all`), L401–530 (`set`/`flush`/`sync_flush_now`/writer thread)
- `core/database.py` L145–200 (db path, WAL pragmas), L2036–2132 (`set_setting`, `set_settings_batch`, `get_all_settings`)
- `core/app.py` L94–163 (`__init__` wiring), L508–586 (`cleanup`)
- `main.py` L232–330 (bootstrap, mutex, session restore), **L348–412** (window creation, `set_window`, `on_loaded`, `on_closed`), L415–545 (routes, watchdog), **L555–584** (post-`webview.start()` session save + cleanup)
- `ui/web_new_v2/js/main.js` L25–84 (`awaitBridge`), L172–206 (`toggleMiniPlayerMode`), L208–350 (`restorePreferences`, battery saver), L350–390 (init trigger), **L390–545** (`init()` order), L600–620 (`app_ready`)
- `ui/web_new_v2/js/events.js` L40–140 (`dispatchPythonEvent`, `initEvents`, `window_visibility` case), L405–460 (`session_autoplay`)
- `ui/web_new_v2/js/efficiency.js` L1–192 (whole file)
- `ui/web_new_v2/js/particles.js` L1–65 (visibility plumbing), L240–272 (`stopParticles`), L273–380 (`initParticles`), L470–557 (animate loop, efficiency/battery events)
- `ui/web_new_v2/js/visualizer.js` L60–140 (visibility plumbing), L240–250 (`syncVisualizerAnimation`), L330–400 (`draw` loop)
- `ui/web_new_v2/js/player.js` L590–640 (`timeupdate` handler), L860–920 (`togglePlayPause`), L922–1001 (`initPlayer`), L1340–1425 (`animateProgress`, `isPlayerUiHidden`), L1424–1500 (`checkPlaybackLookahead`, `syncPlayerVisibility`), L1625–1690 (`onTrackChanged`), L1925–1971 (`onPositionChanged`), L2485–2620 (orbit glow)
- `ui/web_new_v2/js/queue.js` L70–140 (`loadQueue`)
- `ui/web_new_v2/css/components/base.css` L14–30 (`html.window-hidden` animation pause), L2554–2620 (mini-player CSS)
- `tests/test_window_visibility.py` (whole), `tests/test_window_maximize.py` (whole), `tests/test_window_resize_api.py` (whole), `tests/test_player_layout_geometry.py` (whole), `tests/test_player_resources.py` L100–162, `tests/test_visual_effects_lifecycle.py` L160–240
- `tools/bench/build_hotspots.py` L39–144 (the repo's own rAF-loop table — used only as a cross-check, its line numbers are stale)
- pywebview (venv, read-only, for API-contract verification): `webview/event.py` L30–93, `webview/util.py` L162–232, `webview/platforms/winforms.py` L260–350, L396–410, L440–560, `webview/platforms/edgechromium.py` L55–135, L300–314, `webview/js/finish.js`, `webview/window.py` L330–410

**Callees traced into other areas**

- `core/database.py::set_settings_batch` (WN-12) — where the session is actually persisted
- `core/settings.py::SettingsManager.flush/_writer_loop` (WN-14) — write-behind batching + `atexit`
- `core/app.py::AppCore.cleanup` (WN-02) — teardown order
- `ui/web_new_v2/js/events.js` (WN-28) — the only Python→JS dispatcher
- `ui/web_new_v2/js/player.js / particles.js / visualizer.js / efficiency.js` (WN-29/WN-28/WN-31) — the background-cost consumers
- `core/proxy.py::LocalProxyManager.start` (WN-11) — dynamic port (checked for the two-instance scenario)
- pywebview internals — the contract for `minimized/restored/maximized/shown/resized`, `hide()`, `evaluate_js()`, `Event.set()`

**Verification commands run (read-only)**

- `pytest tests/test_window_visibility.py tests/test_window_maximize.py tests/test_window_resize_api.py tests/test_snap_layouts.py -q` → **72 passed**
- AST proof (`%TEMP%/opencode/wx12_proof.py`, outside the repo) proving that `core/api.py:574` and `:577` are the only statements after the top-level `return` in `_install_snap_layouts`, and that `core/api.py:575` is the **only** `_tray.start()` call site in the whole tree.

---

### 2. Findings

#### F-WX-12-1  [P1] — The system tray is never started: `core/api.py:572` ends `_install_snap_layouts` with an unconditional `return`, making `self._tray.start()` (`:575`) and `_set_icon` (`:577-597`) dead code — minimise-to-tray therefore never works and the app exits instead of hiding

- **File:** `core/api.py:542-597` (dead code), `core/api.py:917-938` (the gate that depends on it), `core/tray.py:165-185` (the only producer of `TrayIcon.icon`)
- **Confirmed:** yes
- **Description:** `_install_snap_layouts` is the *only* place that was meant to start the tray once the native HWND exists. Its body is:
  `for _ in range(attempts): … if hwnd: … if snap.install(): … return True / return False …` → `logger.warning("Snap Layouts skipped…")` → **`return False`** (`:572`) → and only *then* the tray/`_set_icon` block. Every path through the function returns before line 574, so the block is unreachable. The AST proof confirms: the two top-level statements after the `Return` are the `If` at `:574` and the `Try` at `:577`; the only `self._tray.start()` call site in the entire repository is `core/api.py:575`.
  The consequence cascades: `TrayIcon.icon` is only assigned inside the tray thread (`core/tray.py:177`), so it stays `None` forever. `AppApi.close()` gates the hide-to-tray branch on `tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)` (`:924`) → always `False` → the `minimize_to_tray` branch at `:926-930` is dead → `close()` always falls through to `self.flush_listening()` + `self._window.destroy()`.
- **Cause:** The "start the tray + set the icon" step was appended *after* the snap-layout installer's early-return ladder instead of being scheduled independently of it. The three responsibilities (install the WndProc subclass / start the tray / set the window icon) were glued into one function whose control flow makes the last two conditional on the first failing.
- **Trigger conditions:** Always. Every launch, on every platform where `sys.platform == "win32"` (the only supported platform). The success path returns at `:564`; the failure paths return at `:566`/`:569`/`:572`.
- **User impact:** With `general.minimize_to_tray = True` (the shipped default, `core/settings.py:63`) the X button / "close" **quits the application and stops the music** instead of hiding it to the tray. The tray menu (play/pause, next/prev, favourite, "Открыть NeDotify", "Выход", `core/tray.py:108-138`) is unreachable — there is no tray icon at all. The `tray_action` CustomEvent consumer in `js/player.js:1010-1033` can therefore never fire. As a secondary effect the same dead block also skipped the native icon assignment (`core/api.py:577-597`), so the taskbar/window shows the default pywebview icon instead of `icon.ico`.
- **Evidence:**
  ```python
  # core/api.py:570-577
          time.sleep(delay)
      logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
      return False                       # <-- line 572: unconditional end of the function

      if getattr(self, "_tray", None):  # <-- line 574: UNREACHABLE
          self._tray.start()             # <-- line 575: UNREACHABLE (only call site in the repo)
  ```
  ```python
  # core/api.py:922-930
          minimize_to_tray = bool(self._core.settings.get("general", "minimize_to_tray", True))
          tray_mgr = getattr(self, "_tray", None) or getattr(self._core, "tray", None)
          tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)
          if minimize_to_tray and tray_available:
              try:
                  self._window.hide()
                  self._on_minimized()
                  return {"success": True, "message": "Minimized to tray"}
  ```
  ```python
  # core/tray.py:171-179  — the ONLY assignment of TrayIcon.icon
          def _run_tray():
              try:
                  img = self.create_image()
                  if not img:
                      return
                  menu = self._build_menu()
                  self.icon = pystray.Icon("NeDotify", img, "NeDotify", menu)   # never reached
  ```
- **Reproduction / verification:** (a) `& ".venv_win\Scripts\python.exe" "C:\Users\Артур\AppData\Local\Temp\opencode\wx12_proof.py"` → prints `line 574` / `line 577` as the statements after the first top-level `return`, and lists `core\api.py:575` as the only `_tray.start()` call site. (b) Static: `grep -n "_tray.start" -r .` → 1 hit, in the unreachable block. (c) Runtime, with the app: set "Свёртывать в трей" on, close the window → the process exits and no tray icon appears. (d) The unit test `tests/test_window_visibility.py:93-112` *fakes* the tray (`tray.icon = object()`), so it passes while the real tray is never created — that is exactly why the defect is invisible to the suite.
- **Suggested fix:** Decouple the three steps: start the tray from `set_window()` (or from a small `startup` task) once the window exists, independent of the snap-layout installer's return value; e.g. move `self._tray.start()` and the `_set_icon` thread into `set_window()` after the `threading.Thread(target=self._install_snap_layouts, …)` call, or give `_install_snap_layouts` a `finally:` that performs them. Do not rely on the installer's success to gate unrelated startup work.
- **Fix side effects:** Starting the tray changes the shutdown semantics: `AppApi.cleanup()` (`core/api.py:446-459`) already calls `self._tray.stop()`, and `TrayIcon.on_exit` (`core/tray.py:99-106`) destroys the window — with a live tray, "X" will now hide the window instead of exiting, so the "Выход" tray item becomes the only way to quit. The exit path must therefore be verified to still reach `main.py:557-580` (session save + cleanup) — see F-WX-12-2.
- **Discovered by:** B

---

#### F-WX-12-2  [P1] — The single-instance mutex is released in `on_closed` **before** the session is persisted, so a relaunch inside that window restores a stale session and two instances fight over the same session rows

- **File:** `main.py:406-408` (release) vs `main.py:557-571` (session write), `main.py:574-575`
- **Confirmed:** yes
- **Description:** The shutdown order is inverted with respect to the state the user expects to survive the restart:
  1. `main.py:406-408` — `def on_closed(): _INTENTIONAL_CLOSE.set(); _release_instance_lock()`. pywebview fires `closed` from the WinForms `FormClosed` handler (`webview/platforms/winforms.py:309` → `self.closed.set()`), which runs *before* `Application.Exit()` (`winforms.py:312`) completes the message loop.
  2. `webview.start()` (`main.py:555`) returns only after that loop exits.
  3. **Only then** `main.py:557-571` writes the session (`app_core.session.save_session(...)` → `settings.set(...)` × 7 → `settings.flush()`).
  4. `main.py:574` releases the mutex again (a no-op — `_INSTANCE_MUTEX` is already `None`).
  So the guard is dropped while the first instance is still alive (WebView2 child process, proxy, downloader, Discord RPC) and *before* the queue/position it is about to persist has been written.
- **Cause:** The mutex was placed on the "window closed" callback (a lifecycle event) instead of on "the process has finished persisting its state". The persisted state and the exclusivity guard are two different lifetimes and were bound to the same event.
- **Trigger conditions:** The user closes the app and relaunches it (or the user double-clicks the launcher icon again) within the shutdown window — i.e. exactly the "app restart state continuity" scenario. The window between the mutex release and the session write contains at least the unwinding of `webview.start()` and the `save_session` call with its SQLite transaction — tens to hundreds of milliseconds — and during that whole window the first instance's WebView2 child process, proxy, downloader and Discord RPC are still running.
- **User impact:** The second instance calls `app_core.session.restore_session()` (`main.py:315`) and gets the *previous* run's queue/position — the track the user was listening to when they closed the app is gone from the UI. Then the first instance's `save_session` overwrites the very rows the second instance just read, and the second instance's own `save_session` (on its exit) overwrites the first one's. The user sees the wrong track restored and, if both instances are alive, two Discord RPC clients and two downloaders on the same `~/.nedotify/nedotify_storage.db`. Note that the whole first instance is still *alive* during that window (the downloader, the proxy and the Discord RPC are only stopped later, in `app_core.cleanup()` at `main.py:575` → `core/app.py:541-560`), so the two instances really do run side by side.
- **Evidence:**
  ```python
  # main.py:406-411
      def on_closed():
          _INTENTIONAL_CLOSE.set()
          _release_instance_lock()          # <-- mutex released here

      window.events.loaded += on_loaded
      window.events.closed += on_closed
  ```
  ```python
  # main.py:555-575
      webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)

      # Save session before exit                       <-- session written here, AFTER the release
      try:
          engine = app_core.engine
          app_volume = app_core.settings.get("audio", "volume", 70)
          app_core.session.save_session(
              track_id=engine.queue.current_track.get("id") if engine.queue.current_track else None,
              position=getattr(engine, '_last_reported_position', 0),
              ...
          )
      ...
      _release_instance_lock()
      app_core.cleanup()
  ```
- **Reproduction / verification:** Static ordering proof above (the `closed` event provably precedes `webview.start()` returning — `winforms.py:309` vs `winforms.py:312`). Runtime: close the app and immediately relaunch it (or set `general.minimize_to_tray` aside and just double-click the exe twice in a row); the second window opens with the previous session. A deterministic test can be written with a fake `webview.start` that returns immediately and an `on_closed` that is invoked synchronously, asserting the mutex is still held at the moment `save_session` runs.
- **Suggested fix:** Release the mutex *after* the session has been persisted and the core cleaned up — i.e. move `_release_instance_lock()` out of `on_closed` and keep only the `_INTENTIONAL_CLOSE.set()` there (that flag is about the watchdog, not exclusivity). If the guard must be dropped early to avoid a stuck instance on a crash, persist the session *before* releasing, or write the session on every queue/position change rather than only at exit.
- **Fix side effects:** Holding the mutex a little longer means a crashed instance keeps the lock until the OS reclaims the handle — acceptable, since `CreateMutexW` handles are released by the kernel on process death. The watchdog restart path (`main.py:514`) already releases the lock *before* spawning the child, deliberately; that path must stay as it is or the child would refuse to start (see the comment at `main.py:508-513`).
- **Discovered by:** B

---

#### F-WX-12-3  [P1] — The restored track and the session autoplay/position are emitted before the frontend installs its event dispatcher, so they are silently dropped — the restart continuity depends on an event nobody is listening to yet

- **File:** `main.py:389-402` (emitter), `ui/web_new_v2/js/events.js:46-73` + `:89-96` + `:418-427` (consumer), `ui/web_new_v2/js/main.js:350-372` + `:390-545` (dispatcher bootstrap)
- **Confirmed:** yes (ordering is deterministic in code; the *observable* symptom is a race whose window is 0–300 ms — see below)
- **Description:** The restore sequence is:
  - `main.py:315-325` — the queue is restored into the engine and `_on_track_changed(current_track)` is called **before the window exists** (`api.set_window(window)` is at `main.py:384`), so `AppApi._emit` returns immediately (`core/api.py:1124-1125`: `if not self._window: return`). That first publication is lost by construction.
  - `main.py:389-392` — `on_loaded` re-publishes it: `app_core.engine._on_track_changed(app_core.engine.queue.current_track)` → `_emit("track_changed", …)`.
  - `main.py:395-402` — `on_loaded` also emits `session_autoplay` with the saved `position_sec`.
  On the frontend the only consumer of both events is the `coreEventHandler` installed by `initEvents()` (`js/events.js:71-73`). `dispatchPythonEvent` (`js/events.js:50-65`) drops every event while `coreEventHandler` is `null`, and `initEvents()` is called at `js/main.js:528` — **after** the first `await` in `init()`, namely the Icons step (`js/main.js:516-527`) which resolves from `requestIdleCallback(..., {timeout: 300})` or a 50 ms timer.
  The backend emits from the `loaded` event, which pywebview fires from `webview/util.py:221` right after the `finish.js` injection script has run. `finish.js` is what dispatches `pywebviewready`, and `pywebviewready` is what starts `init()` (`js/main.js:360-364`). Therefore the ordering in the renderer is: `pywebviewready` → microtask → `init()` starts → `init()` suspends at the Icons await → **only then** do the `track_changed` and `session_autoplay` scripts (submitted by Python immediately after `loaded.set()`) execute → `coreEventHandler` is still `null` → both events are dropped. There is no compensating path: the frontend never re-requests the current track (`initPlayer()`, `js/player.js:922-1001`, does not call `get_queue`/`get_current_track`), and the backend has no "give me the current state" handshake.
- **Cause:** The backend treats "the page loaded" as "the UI is ready to receive events", but in this bridge the page's *event dispatcher* is installed hundreds of milliseconds later, after an `await` on an idle callback. A push model with a fire-and-forget emitter and no readiness handshake has no way to guarantee delivery.
- **Trigger conditions:** Every cold start with a non-empty saved session. The race window is the gap between the `loaded` event and `initEvents()`; the `requestIdleCallback` timeout of 300 ms bounds it. On a fast machine the idle callback usually wins the race *after* the two event scripts, which is the failing order.
- **User impact:** The app opens with the restored queue visible in the queue drawer (that comes from `get_queue()`, `js/queue.js:76-85`) but **no track loaded in the player** (no `track_changed` → `currentTrack` stays `null`, `js/player.js:1644`). With autoplay enabled, the saved playback position is also lost: `session_autoplay` is the only carrier of `position_sec` (`main.py:397-400` → `js/events.js:418-427`), and the frontend's own seek fallback (`js/events.js:425`) never runs. The user must press play and re-seek manually.
- **Evidence:**
  ```python
  # main.py:389-402
      def on_loaded():
          logging.info(f"[startup] window loaded (+{(_time.monotonic() - _t0) * 1000:.0f}ms)")
          if app_core.engine.queue.current_track:
              app_core.engine._on_track_changed(app_core.engine.queue.current_track)   # track_changed
          try:
              if app_core.session.should_autoplay and app_core.engine.queue.current_track:
                  api.emit_event("session_autoplay", {                                   # session_autoplay
                      "track_id": app_core.engine.queue.current_track.get("id"),
                      "position_sec": session_position_sec,
                  })
  ```
  ```javascript
  // js/events.js:50-56, 71-73
  export function dispatchPythonEvent(eventName, data) {
      if (coreEventHandler) {            // <-- null until initEvents() runs
          try { coreEventHandler(eventName, data); } catch (err) { … }
      }
      for (const fn of pythonEventHandlers.slice()) { … }
  }
  export function initEvents() {
      window.onPythonEvent = dispatchPythonEvent;
      coreEventHandler = function(eventName, data) { … }   // <-- the only place track_changed /
  }                                                        //     session_autoplay are handled
  ```
  ```javascript
  // js/main.js:516-528 — initEvents() is behind an idle-callback await
  await safeInit('Icons', () => new Promise((resolve) => {
      const runIcons = () => { … resolve(); };
      if (window.requestIdleCallback) { window.requestIdleCallback(runIcons, { timeout: 300 }); }
      else { setTimeout(runIcons, 50); }
  }));
  await safeInit('Events', () => initEvents());   // <-- dispatcher installed here
  ```
- **Reproduction / verification:** (a) Static: the three code excerpts above establish the ordering; `js/main.js:528` is the only `initEvents()` call site in the tree. (b) Runtime: start the app with `audio.autoplay = true` and a saved queue, then watch the WebView2 console (`NEDOTIFY_DEVTOOLS=1`, `main.py:552-554`): `events.js:74` logs `Python Event: track_changed` and `Python Event: session_autoplay`, but no `track_changed` handler runs and the player stays empty — i.e. the events arrive with `coreEventHandler === null`. (c) A deterministic regression can be built with the existing node harness style used in `tests/test_player_resources.py:139-162`: evaluate `events.js` *without* calling `initEvents()` and assert that `window.onPythonEvent('session_autoplay', …)` is a no-op.
- **Suggested fix:** Make the restore **pull-based** instead of push-based: after `initEvents()` installs the dispatcher, the frontend asks the backend for the current state (`get_queue()` already returns `current_track` — `core/api.py:1772-1780` — and `get_settings()`/`get_queue()` are available), and the backend exposes the saved `position_sec` on that payload. Alternatively, have the backend hold the restore payload and re-emit it on an explicit "ui ready" call from the frontend (e.g. `api.ui_ready()` → re-emit `track_changed` + `session_autoplay`). The frontend must also stop relying on fixed `setTimeout(…, 400)` / `setTimeout(…, 600)` in `js/events.js:422-426`.
- **Fix side effects:** A pull-based handshake adds one bridge round-trip at startup and requires the frontend to distinguish "restored track" from "user-selected track" (the current `onTrackChanged` treats the first event as an initial load and pauses it — `js/player.js:1675-1684`). The autoplay path must also become event-driven instead of a 400 ms timer, otherwise a slow stream resolution re-introduces the same race one level down.
- **Discovered by:** B

---

#### F-WX-12-4  [P2] — The window state is not a state machine: three independent representations (backend booleans, the native window, the CSS class) are updated at three different moments, and the maximize → mini → exit round trip destroys the user's pre-maximize geometry

- **File:** `core/api.py:351-353, 560, 615-627, 773-859, 1001, 1053-1095`; `ui/web_new_v2/js/main.js:175-205`; `ui/web_new_v2/js/events.js:89-96, 234-238`
- **Confirmed:** yes
- **Description:** There is no single owner of the window state. The full inventory of state that encodes "normal / minimised / mini / maximised / hidden":

  | Variable | Owner | Written at | Read at |
  |---|---|---|---|
  | `AppApi._is_mini_active` | `core/api.py:351` (init) | `:777` (`toggle_mini_player`, synchronously, before the native op) | `:560` (snap `can_resize`), `:889` (position guard), `:1001` (resize guard) |
  | `AppApi._is_maximized` | *not initialised in `__init__`*; created on first write | `:625` (`_on_window_resized`), `:802` (`_enter_mini_mode`), `:1081`/`:1089` (`_change_maximized_state`) | `:560`, `:1001`, `:1084` |
  | `AppApi._last_geometry` | — | `:1073` (pre-maximize bounds) | `:1078` (restore) |
  | `AppApi._saved_main_geometry` | — | `:799` (`_enter_mini_mode`, = `GetWindowRect` of the *current* window) | `:832` (`_exit_mini_mode`) |
  | `AppApi._saved_mini_pos` | — | `:886` | `:816`, `:895` |
  | `native.WindowState` (Normal/Minimized/Maximized) | WinForms | `:810` (mini → Normal), `:1075`/`:1077` (max), pywebview `minimize()`/`restore()` | `:625`, `:1068`, `:1010` (`IsZoomed`) |
  | `native.MinimumSize` | WinForms | `:811` (mini → 1×1), `:846` (exit → 600×640) | WinForms |
  | `target_win.on_top` (TopMost) | WinForms | `:813` (mini → True), `:840` (exit → False) | — |
  | `body.mini-player-active` (CSS) | `js/main.js:180`, `js/events.js:235` | optimistic, at t=0 | `js/particles.js:52/357/475`, `js/window-resize.js:10`, `base.css:2554-2618` |
  | `documentElement.window-hidden` | `js/events.js:93` | on the `window_visibility` event | `particles.js:48`, `visualizer.js:99`, `player.js:1360`, `efficiency.js:98`, `base.css:22-29` |
  | `document.hidden` | Chromium/WebView2 | — | all of the above |
  | `documentVisible` | `js/visualizer.js:102` | `:104` | `:243`, `:331` |
  | `efficiencyPaused` | `js/particles.js:548`, `js/visualizer.js` | the `nedotify:efficiency_state` event | the loop guards |
  | `settings.general.minimize_to_tray` | settings table | `js/onboarding.js:171` → `api.complete_onboarding` | `core/api.py:922` |

  The three representations of "mini" are updated at t = 0 (CSS class, `js/main.js:180`), t = 0 (backend boolean, `core/api.py:777`) and t = 250 ms (the native window, `core/api.py:820-822`) — a ≥250 ms window in which any of the three can disagree, and no rollback path if the native op fails (see F-WX-12-8).
  A concrete, permanent divergence: **maximize → mini → exit mini loses the pre-maximize geometry.** `_enter_mini_mode` saves `self._saved_main_geometry = self._native_window_geometry(target_win)` (`:798-799`), i.e. `GetWindowRect` of the *currently maximized* window = the monitor rect, and it clears `self._is_maximized = False` (`:802`). `_exit_mini_mode` then restores exactly that screen-sized rect (`:832-853`). `_last_geometry` — the only record of the user's real normal bounds — is *not* used by the exit path. The window is now screen-sized while the backend believes it is "normal"; the next maximize press reads `native.WindowState == Normal` (`:1068`) and overwrites `_last_geometry` with the screen rect (`:1072-1073`), so the original geometry is gone for good.
- **Cause:** The state was modelled as a set of independent booleans/fields mutated at the call sites that happen to need them, instead of one enum (`NORMAL / MINIMIZED / MINI / MAXIMIZED / HIDDEN`) owned by one object, with a single transition function that applies the native operation and the CSS class together and reports the result.
- **Trigger conditions:** maximize the window → open the mini player → close the mini player. Also: any failed deferred native op (F-WX-12-8) leaves the CSS class and the native size permanently out of sync.
- **User impact:** After the mini round trip the app occupies the whole screen and the "restore" button no longer returns the window to its previous size; the user's window layout is silently lost. Rapid mini toggles can leave a 380×110 window with the full UI, or a full-size window with the mini overlay.
- **Evidence:** the table above; the two decisive excerpts:
  ```python
  # core/api.py:797-803
              # Save main window geometry to restore exactly upon exit
              geometry = self._native_window_geometry(target_win)     # GetWindowRect of the MAXIMIZED window
              self._saved_main_geometry = geometry or (*MAIN_WINDOW_SIZE, None, None)
              # Entering mini from a maximized window must clear the stale flag:
              # otherwise the next maximize button press restores first.
              self._is_maximized = False
              w, h = MINI_WINDOW_SIZE
  ```
  ```python
  # core/api.py:832-853 (excerpt)
              gw, gh, gx, gy = getattr(self, '_saved_main_geometry', (*MAIN_WINDOW_SIZE, None, None))
              w = int(gw or MAIN_WINDOW_SIZE[0]); h = int(gh or MAIN_WINDOW_SIZE[1])
              def _restore():
                  …
                  target_win.resize(w, h)          # the screen-sized rect
                  if gx is not None and gy is not None and hasattr(target_win, 'move'):
                      target_win.move(int(gx), int(gy))
  ```
- **Reproduction / verification:** Static: the two excerpts plus `_native_window_geometry` (`core/api.py:749-771`, `GetWindowRect`) and `_change_maximized_state` (`core/api.py:1072-1073`) prove the loss. Runtime: maximize → mini (KeyP / the title-bar button) → expand → the window stays screen-sized and the "restore" button grows it further instead of shrinking it. A regression test is easy to add by faking `GetWindowRect` to return the monitor rect while `_last_geometry` holds the normal bounds and asserting that `_exit_mini_mode` picks `_last_geometry` when the window was maximized.
- **Suggested fix:** Introduce a single `WindowState` enum + a single `apply_state(target)` transition function that owns: the native operation, the backend flags, the CSS class and the geometry bookkeeping (choosing `_last_geometry` over `_saved_main_geometry` when the previous state was MAXIMIZED). The CSS class should be applied by the backend's confirmation (or by an event), not optimistically by the frontend.
- **Fix side effects:** A single transition function serialises all window operations, which changes the current "last writer wins" behaviour of `_deferred_window_op` (see F-WX-12-5) and requires the frontend's optimistic class swap to be reconciled (the frontend currently toggles the class itself at `js/main.js:180`).
- **Discovered by:** B

---

#### F-WX-12-5  [P2] — `_deferred_window_op` starts a fresh thread per operation with no generation counter, so two quick toggles can apply their native operations in the wrong order

- **File:** `core/api.py:721-735` (the helper), `:820-822` (mini), `:855-857` (exit mini), `:895` (mini position), `:1095` (maximize)
- **Confirmed:** yes
- **Description:**
  ```python
  def _deferred_window_op(self, delay: float, fn):
      def _run():
          time.sleep(delay)
          try:
              with self._window_op_lock:
                  fn()
          except Exception as e:
              logger.warning("Deferred window operation failed: %s", e, exc_info=True)
      threading.Thread(target=_run, daemon=True).start()
  ```
  Each call spawns a thread that sleeps for a fixed delay and then runs `fn` under `_window_op_lock`. The lock serialises the *execution* but establishes no *order*: two operations scheduled 10 ms apart wake up ~10 ms apart and race for the (non-FIFO) `RLock`. There is no generation/sequence number, no cancellation of a superseded operation, and no coalescing.
  With the mini-player delay of 0.25 s, a user who presses the mini hotkey twice quickly (KeyP is bound in `core/settings.py:142` and `js/hotkeys.js:235-238`) produces two pending operations — "enter mini" and "exit mini" — whose relative execution order is not guaranteed. If the exit runs first, the window ends up 380×110 while the backend flag `_is_mini_active` is `False` and the CSS class has been removed.
- **Cause:** The delay was introduced to avoid the WinForms deadlock (correctly documented at `core/api.py:721-727`), but it was implemented as "spawn a thread and sleep" instead of "a single serialised worker with a cancellable/coalescing queue".
- **Trigger conditions:** Two toggles within ~250 ms (fast double-tap on the mini button, a held/repeated hotkey, or a toggle immediately followed by a maximise). Also: a toggle followed by an app close — the deferred thread may run against a destroyed window (the exception is caught and logged only as a warning, `core/api.py:733-734`).
- **User impact:** The window can end up in the wrong size/mode relative to the UI (mini overlay on a full-size window or vice versa); the failure is silent apart from a log line.
- **Evidence:** the `_deferred_window_op` source above plus the two call sites with different delays:
  ```python
  # core/api.py:820-822
              self._deferred_window_op(
                  0.25, lambda: self._on_window_ui_thread(target_win, _apply_mini_geometry)
              )
  # core/api.py:855-857
              self._deferred_window_op(
                  0.25, lambda: self._on_window_ui_thread(target_win, _restore)
              )
  ```
- **Reproduction / verification:** Unit-level: call `api.toggle_mini_player(True)` then `api.toggle_mini_player(False)` and assert that the *last* native operation to run is the restore. Deterministically reproducible by monkeypatching `time.sleep` in the deferred thread to a barrier so both threads wake simultaneously, then recording the order of the `resize` calls. The existing test `tests/test_window_maximize.py:57` monkeypatches `_deferred_window_op` away entirely (`lambda delay, fn: pending.append(fn)`) and pops `pending[0]()` — it therefore never exercises the ordering at all.
- **Suggested fix:** Replace the per-call thread with a single long-lived "window operation" worker that keeps a *desired state* and an incrementing generation; a queued operation whose generation is stale is dropped. The lock then only needs to protect the state, not the ordering.
- **Fix side effects:** A serialised worker means a slow native op delays the next one; the 250 ms "let the bridge reply first" window must be preserved (the bridge reply happens before the op is queued). Any code that relies on two ops running concurrently (none found) would change behaviour.
- **Discovered by:** B

---

#### F-WX-12-6  [P2] — The orbit-glow rAF loop keeps running at 30 Hz in mini-player mode, writing CSS variables into two `display:none` elements and reading the FFT analyser for nothing

- **File:** `ui/web_new_v2/js/player.js:2510-2542` (`syncOrbitGlowState`), `:2546-2592` (`startOrbitGlowLoop`), `ui/web_new_v2/css/components/base.css:2596-2610` (mini-player CSS)
- **Confirmed:** yes
- **Description:** `syncOrbitGlowState` decides whether to run the loop from `isWindowFocused = !isPlayerUiHidden() && !document.body.classList.contains('unfocused-animations-disabled')` (`js/player.js:2515`). In the mini player the window *is* visible, so the condition is true and the loop runs — but the mini-player CSS hides both of its output targets:
  ```css
  body.mini-player-active #app-container,
  body.mini-player-active #title-bar,
  body.mini-player-active #sidebar,
  body.mini-player-active #main-content,
  body.mini-player-active #player-bar,          <-- the orbit-glow target
  …
  { display: none !important; visibility: hidden !important; pointer-events: none !important; }
  ```
  and `.player-glass-card` lives inside `#main-content`. So for the whole duration of the mini player the loop performs an `AnalyserNode.getByteFrequencyData()` FFT read plus 4 `style.setProperty()` writes per 33 ms tick (`js/player.js:2557-2588`) into elements that are not rendered. The mini player's own bar does not use `--orbit-glow-*`.
- **Cause:** The loop's stop conditions cover "window hidden" and "perf preset changed" but not "the CSS layout no longer contains the targets". Every other rAF loop in the app has a layout-aware stop condition (the visualizer checks `offsetParent !== null` — `js/visualizer.js:340`; the particles check `body.mini-player-active` — `js/particles.js:52`), so this is an omission rather than a design decision.
- **Trigger conditions:** Every use of the mini player while a track is playing and the performance preset is `high` (the default `optimization.performance_preset` is `"balanced"` — `core/settings.py:106`; `balanced` maps to `(18, 30, 45, "lq", "subtle", 6)` in `core/api.py:2808-2815`, and the orbit-glow stop condition at `js/player.js:2511-2513` only stops on `perf-low`/`battery-saver`/`macos`, so `balanced` still runs the loop).
- **User impact:** A permanently armed 30 Hz rAF chain plus a Web-Audio FFT read while the app is in its smallest, most "background" state. On a laptop on battery this is measurable; it is exactly the state the user leaves running for hours.
- **Evidence:** the excerpts above; the loop body:
  ```javascript
  // js/player.js:2557-2588
      function loop(now) {
          if (!isOrbitGlowRunning) return;
          if (now - lastTime >= 33) {          // 30 FPS
              lastTime = now;
              if (analyserNode) { analyserNode.getByteFrequencyData(dataArray); … }
              const opacity = …; const scale = …;
              if (pb) { pb.style.setProperty('--orbit-glow-opacity', opacity); … }
              if (ppCard) { ppCard.style.setProperty('--orbit-glow-opacity', opacity); … }
          }
          orbitGlowRafId = requestAnimationFrame(loop);
      }
  ```
- **Reproduction / verification:** In the existing node harness style (`tests/test_player_resources.py`), set `body.mini-player-active` and assert that no frame is scheduled; today a frame is scheduled. Runtime: open the mini player, play a track, and observe with WebView2 DevTools (`NEDOTIFY_DEVTOOLS=1`) that the `requestAnimationFrame` chain for the orbit glow keeps ticking while the mini player is open.
- **Suggested fix:** Add the mini-player condition to `syncOrbitGlowState` (the same `document.body.classList.contains('mini-player-active')` test the particles already use), or make the loop verify that its targets are rendered (`offsetParent !== null`) before writing.
- **Fix side effects:** None visible — the mini player has no orbit-glow styling. If a future mini-player skin wants the glow, the condition must be revisited then.
- **Discovered by:** B

---

#### F-WX-12-7  [P3] — The mini-player CSS class is swapped 250 ms before the native resize, so a stretched mini card with a 24 px backdrop blur is painted over the full-size window for a quarter of a second

- **File:** `ui/web_new_v2/js/main.js:175-205`, `core/api.py:805-822`, `ui/web_new_v2/css/components/base.css:2554-2594`
- **Confirmed:** yes
- **Description:** The frontend swaps the class optimistically and immediately:
  ```javascript
  // js/main.js:179-185
      // Optimistic class swap for an instant visual response...
      document.body.classList.toggle('mini-player-active', targetState);
      …
          const res = await window.pywebview.api.toggle_mini_player(targetState);
  ```
  The native resize only happens 250 ms later in the deferred thread (`core/api.py:820-822`). In between, the window is still 1100×800 while the DOM is already in mini mode: `#mini-player-overlay` is `position: fixed !important; inset: 0 !important` with `backdrop-filter: blur(24px) !important` (`base.css:2566-2587`) and the whole app (`#app-container`, `#sidebar`, `#main-content`, `#player-bar`, `#particles-bg`, `#aura-orbs-container`, …) is `display: none !important` (`base.css:2596-2610`).
- **Cause:** The class swap and the native resize are two independent actions separated by a fixed delay, with the delay chosen to let the bridge reply first (`core/api.py:721-727`) — but the delay is applied only to the native half.
- **Trigger conditions:** Every mini-player entry and exit.
- **User impact:** A 250 ms flash of a mini card stretched over the full window, plus a 24 px backdrop blur over a 1100×800 surface (a real GPU cost for a full-screen blur) immediately followed by a window resize. On exit the same flash happens in reverse.
- **Evidence:** the excerpts above; the CSS:
  ```css
  /* base.css:2587 */
      backdrop-filter: blur(24px) !important;
  ```
- **Reproduction / verification:** Runtime: toggle the mini player with the window at its default 1100×800 and record the screen (the DevTools "paint flashing" mode makes it obvious). A DOM-level test can assert the class only appears after the backend acknowledges the resize.
- **Suggested fix:** Have the backend publish the applied state (an event, e.g. `mini_player_state`) after the native op has actually run, and let the frontend apply the class on that event. If the optimistic path must stay, shrink the mismatch by resizing the native window first and swapping the class on confirmation.
- **Fix side effects:** The switch would no longer be instantaneous from the user's point of view (the class swap would move after the resize, adding ~1 frame). The alternative — keeping the optimistic class — would need the overlay to be sized to the *window* rather than the viewport, which is not expressible in CSS.
- **Discovered by:** B

---

#### F-WX-12-8  [P3] — `toggle_mini_player` can never report failure, so the frontend's documented rollback is dead code and a failed native operation leaves the state permanently divergent

- **File:** `core/api.py:773-790`, `core/api.py:823-824`, `core/api.py:858-859`, `ui/web_new_v2/js/main.js:196-203`
- **Confirmed:** yes
- **Description:**
  ```python
  # core/api.py:773-790
      def toggle_mini_player(self, enable: bool):
          logger.info(f"toggle_mini_player called with enable={enable}")
          try:
              self._is_mini_active = enable
              if enable:
                  self._enter_mini_mode()
              else:
                  self._exit_mini_mode()
              # The frontend already applies this state optimistically and rolls
              # it back from the bridge result on failure. …
              return {"success": True, "is_mini": enable}
          except Exception as e:
              logger.error(f"Error toggling mini player: {e}")
              return {"success": False, "is_mini": not enable}
  ```
  `_enter_mini_mode` / `_exit_mini_mode` each wrap their body in `try/except … logger.debug(...)` (`:823-824`, `:858-859`), so they never raise. The only statement that could raise is `self._is_mini_active = enable`, which cannot. The method therefore always returns `{"success": True}`, and the frontend's rollback branch (`js/main.js:197-203`) is unreachable. Meanwhile the actual native work happens later, in a deferred thread whose exception handler only logs (`core/api.py:733-734`).
- **Cause:** The error contract is implemented at the wrong level: the bridge method acknowledges the *request*, while the operation that can fail happens afterwards and its result is never reported back.
- **Trigger conditions:** Any failure of the native operation — the window handle is gone, the form is being destroyed, `SetWindowPos` is refused, the WinForms call throws cross-thread.
- **User impact:** A failed mini switch leaves the CSS class and `_is_mini_active` saying "mini" while the window is not mini (or vice versa) — permanently, with no error toast (the toast at `js/main.js:199-201` is dead) and only a `logger.debug` line.
- **Evidence:** the excerpts above; the frontend's rollback:
  ```javascript
  // js/main.js:196-203
      // ...rolled back when the native resize/move actually failed.
      if (!backendOk) {
          document.body.classList.toggle('mini-player-active', isCurrentlyMini);
          window.dispatchEvent(new CustomEvent('nedotify:toast', {
              detail: { msg: 'Не удалось переключить мини-плеер', type: 'error' }
          }));
          return isCurrentlyMini;
      }
  ```
- **Reproduction / verification:** Unit: make `api._window.resize` raise, call `api.toggle_mini_player(True)` and assert the result is `{"success": False}` — today it is `{"success": True}`. The frontend rollback is then proven unreachable. The existing suite never calls `toggle_mini_player` at all (grep: no test references it).
- **Suggested fix:** Return the real outcome: make the deferred operation report back (e.g. via a `mini_player_state` event or a future) and let the bridge answer with the applied state, or perform the geometry work synchronously inside the bridge call's error scope and return its result.
- **Fix side effects:** Reporting the real outcome means the frontend must tolerate an asynchronous answer, which interacts with the optimistic swap (F-WX-12-7).
- **Discovered by:** B

---

#### F-WX-12-9  [P3] — Persisted and in-memory state that is written but never read: `session.last_volume`, `general.start_minimized`, the whole `set_windows` / `_mini_window` dual-window API, and the never-emitted `mini_player_toggled` event channel

- **File:** `core/session.py:57-63` and `:75`; `main.py:313-330`; `core/settings.py:64`; `core/api.py:889`, `:910-915`; `ui/web_new_v2/js/events.js:233-239`; `ui/web_new_v2/js/particles.js:349-353`
- **Confirmed:** yes
- **Description:** Four pieces of state in the restart-continuity path are dead:
  1. **`session.last_volume`** — written on every shutdown (`core/session.py:59`) and read back by `restore_session()` (`core/session.py:75`), but `main.py:313-330` uses only `queue`, `queue_index`, `shuffle`, `repeat` and `position` from the restored session. The restored `volume` is discarded. (The *effective* volume does survive, through the separate `audio.volume` setting written by `AppApi.set_volume`, `core/api.py:1956-1958` — so this is a redundant/misleading field, not a functional loss.)
  2. **`general.start_minimized`** — declared in the schema (`core/settings.py:64`) but referenced nowhere in the whole tree (no Python reader, no JS reader, no UI control). "Start minimised" does not exist as a feature; the setting is a promise the code never keeps.
  3. **`set_windows` / `_mini_window`** — a dual-window API (`core/api.py:910-915`) that is never called; `_mini_window` is therefore always `None`, and the mini player is a *CSS mode of the same HWND*, not a second window. The guard at `core/api.py:889` (`if not self._is_mini_active and not self._mini_window: return`) only works by accident: with `and` it would let the *main* window be moved whenever a mini window existed, so the condition is latently wrong for the API it was written for.
  4. **The `mini_player_toggled` event channel** — `js/events.js:233-239` handles a `mini_player_toggled` Python event and toggles `body.mini-player-active` from it, and `js/particles.js:349-353` re-syncs the particle loop on `nedotify:mini_player_toggled`. **The backend never emits that event** (the only occurrences of the string in the tree are in `tools/bench` and `tests`; `AppApi.toggle_mini_player` deliberately does not emit — `core/api.py:782-785`). The mini-player class is therefore set in exactly one place, the frontend's own optimistic swap (`js/main.js:180`), and the "the backend confirms the state" channel does not exist.
- **Cause:** State accumulated around features that were re-scoped (the mini player became a CSS mode, the volume moved to the settings table) without the leftovers being removed, and the schema advertises a feature that was never implemented.
- **Trigger conditions:** Always (they are unconditional).
- **User impact:** Mostly maintenance debt, with two user-visible edges: a user who sets "start minimised" (if any UI ever exposes it) sees no effect, and a reader of `restore_session()["volume"]` is misled into thinking the volume is restored through the session.
- **Evidence:**
  ```python
  # core/session.py:57-63, 72-80
          self.settings.set("session", "last_track_id", track_id)
          self.settings.set("session", "last_position", position)
          self.settings.set("session", "last_volume", volume)      # written
          …
          "volume": self.settings.get("session", "last_volume", 70),  # read…
  ```
  ```python
  # main.py:313-330 — …and never used
      session_position_sec = 0.0
      try:
          session_data = app_core.session.restore_session()
          queue = session_data.get("queue")
          session_position_sec = float(session_data.get("position") or 0.0)
          if queue:
              app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
              app_core.engine.queue.shuffle = session_data.get("shuffle", False)
              app_core.engine.queue.repeat = session_data.get("repeat", "off")
  ```
  The AST/walk proof in `%TEMP%/opencode/wx12_proof.py` lists every `_mini_window` / `set_windows` occurrence: only the initialiser (`:350`), the `or self._window` fallbacks, the guard, the setter (`:913`) and the shutdown reset (`:944`) — no caller.
- **Reproduction / verification:** `grep -rn "start_minimized" --include=*.py --include=*.js .` → 1 hit (the schema). `grep -rn "set_windows" .` → only the definition and the `_UNWRAPPED` set. `grep -rn "last_volume"` → the settings default, `session.py`, and one settings-flush test — no consumer.
- **Suggested fix:** Either implement `start_minimized` (it needs a native "start hidden" path, which `main.py` does not have) or remove it from the schema; drop `session.last_volume` or actually apply it; delete `set_windows`/`_mini_window` and simplify the three `self._mini_window or self._window` expressions to `self._window`.
- **Fix side effects:** Removing `start_minimized` from `DEFAULT_SETTINGS` changes the settings hash; `SettingsManager._load_all` preserves unknown stored keys, so old rows survive. Removing `_mini_window` touches `core/api.py:793/827/889/892` and the `set_windows` bridge method (removing a bridge method is safe — no JS calls it).
- **Discovered by:** B

---

#### F-WX-12-10  [P3] — `_window_op_lock` is shared between the native window operations and the listening/track-change bookkeeping, so a blocked native window op stalls the playback-state callbacks

- **File:** `core/api.py:353` (the lock), `:731` (window ops), `:1211`, `:1269`, `:1298`, `:1310`, `:1334`, `:1364`, `:1411`, `:1452`, `:2236`, `:2253`, `:2256`, `:2985`, `:3006`, `:3466`, `:3481`, `:3484` (listening / playback state)
- **Confirmed:** yes
- **Description:** One `threading.RLock` guards two unrelated concerns: the serialisation of native window operations (`_deferred_window_op`, `core/api.py:731`) and the listening-session / playback-state bookkeeping (`_listening_for_track`, `_on_track_changed`, the report_* methods). A deferred window op holds the lock for the whole duration of `fn()`, which includes `target_win.resize()` / `move()` — cross-thread WinForms calls that are marshalled onto the UI thread (`_on_window_ui_thread`, `core/api.py:737-747`) and therefore block for as long as the UI thread is busy.
- **Cause:** The lock was introduced as a general "serialise state mutations" primitive and then reused for two different critical sections. The repo's own rule (`AGENTS.md`: "A new shared field joins its class's existing lock rather than opening a second one") was followed in letter, but the lock's scope was never narrowed.
- **Trigger conditions:** A window operation that has to wait for the UI thread (minimise/restore/maximise/mini transitions during a busy UI frame) while a track change or a position report arrives.
- **User impact:** The playback-state callbacks (listening sessions, scrobble reports) are delayed by the window operation. Because the listening data is what the profile/统计 views are built from, a delayed flush can mis-attribute a session — a reliability, not a crash, issue.
- **Evidence:**
  ```python
  # core/api.py:728-735
          def _run():
              time.sleep(delay)
              try:
                  with self._window_op_lock:      # <-- held across the whole native operation
                      fn()
  ```
  ```python
  # core/api.py:1207-1212
          self._listening_for_track(track_copy)
          self._enrich_track_lufs(track_copy)
          with self._window_op_lock:
              self._history_logged_key = None
  ```
- **Reproduction / verification:** Static: the two excerpts share the same lock object. A runtime proof would instrument `AppApi._window_op_lock` and record the hold time during a mini-player transition on a busy UI thread. The `tools/check_lock_nesting.py` helper exists in the repo but does not check lock *scope*.
- **Suggested fix:** Split the lock: a dedicated `_window_state_lock` for the native window operations, and keep the existing lock for the listening/playback bookkeeping (or vice versa — but not both). The window-op lock should ideally not be held across the cross-thread WinForms call at all; the state mutation and the native call can be separated.
- **Fix side effects:** Splitting the lock removes the implicit mutual exclusion between window operations and playback state; if any code relied on that ordering it must be re-checked (the affected sites are all short bookkeeping blocks, so the risk is low).
- **Discovered by:** B

---

#### F-WX-12-11  [P3] — The session is stored in the same plaintext settings table as the OAuth secrets (`auth.yandex_token`, `auth.oauth_client_secret`) in `~/.nedotify/nedotify_storage.db`

- **File:** `core/session.py:57-63`; `core/settings.py:256-264` and `:401-418`; `core/database.py:160-162`, `:2049-2082`; `core/api.py:240-269`
- **Confirmed:** yes
- **Description:** **There is no separate session file.** `SessionManager` stores the session as seven rows of the `settings` table (`core/session.py:57-63` → `SettingsManager.set` → `DatabaseManager.set_settings_batch`, `core/database.py:2049-2082`) inside `~/.nedotify/nedotify_storage.db` (`core/database.py:160-162`), in WAL mode (`core/database.py:185`). Consequences for the questions asked:
  - **Atomicity:** the seven session rows are written by one `executemany` inside a single SQLite transaction (`core/database.py:2070-2079`), so a crash mid-write cannot leave a half-written session — SQLite either commits all seven rows or none. `SettingsManager.flush()` treats a short write as a failure and re-queues the keys (`core/settings.py:468-483`), and `SessionManager.save_session` forces the flush before exit (`core/session.py:65-68`). **A torn session is not possible.** (`PRAGMA synchronous=NORMAL` in WAL mode means a *power loss* can lose the last commits, but cannot corrupt them.)
  - **Location:** `~/.nedotify/nedotify_storage.db` — inside the user's library, as required by `AGENTS.md`.
  - **Content:** the session itself is not sensitive: `last_track_id`, `last_position`, `last_volume`, `last_queue_index`, `shuffle`, `repeat` and `last_queue` — the queue reduced to 9 fields per track (`core/session.py:10-20`), with `file_path` kept only for local tracks (`:36`). So the session leaks listening history and local file paths to anyone who can read the user's profile directory.
  - **The real exposure is the table it lives in:** the same `settings` table stores `auth.yandex_token` and `auth.oauth_client_secret` (`core/settings.py:251-255`) as plaintext JSON. The bridge masks them on read (`core/api.py:240-245`, `_mask_secrets`) and refuses to overwrite them with a blank value (`core/api.py:267-269`), but on disk they are plain strings in the same rows neighbourhood as the session.
- **Cause:** One generic key/value table for all persisted state, with the secret masking implemented at the API boundary rather than at the storage boundary.
- **Trigger conditions:** Always (any user account on a machine where another local process or another user account can read `%USERPROFILE%\.nedotify\nedotify_storage.db`).
- **User impact:** The session itself is harmless; the co-located OAuth client secret and Yandex token are not. On a shared machine, or with a backup/sync tool that copies `~/.nedotify/`, the credentials travel with the library.
- **Evidence:**
  ```python
  # core/settings.py:242-250
      "auth": {
          "cookies_file_path": "",
          "browser_cookies": "none",
          "yandex_token": "",
          "proxy_url": "",
          "oauth_client_id": "",
          "oauth_client_secret": "",          # <-- plaintext in the settings table
      },
  ```
  ```python
  # core/database.py:2070-2079
          with self._write_lock:
              conn = self.conn
              try:
                  with conn:                                   # one transaction
                      conn.executemany(
                          "INSERT OR REPLACE INTO settings (key, value, category, updated_at) "
                          "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                          rows,
                      )
                  return len(rows)
  ```
- **Reproduction / verification:** `sqlite3 ~/.nedotify/nedotify_storage.db "select key, substr(value,1,40) from settings where category='session' or category='auth';"` — read-only, run on a copy, not on the live profile. Static proof of atomicity: `core/database.py:2070-2079`.
- **Suggested fix:** Move the two secrets out of the generic `settings` table — the OS credential store (Windows Credential Manager) or a separate file with restrictive ACLs — or at minimum encrypt them at rest with a per-user key. This is **not** owned by the window-state area: the owning area for the secrets is WN-14 (`core/settings.py`) / WN-12 (`core/database.py`); the session rows themselves need no change.
- **Fix side effects:** Moving the secrets out of `settings` changes the `get_settings`/`save_setting` contract for the `auth` category and the `_mask_secrets` logic (`core/api.py:240-269`), and requires a migration for existing rows. It must not touch the `~/.nedotify/` library without the user's consent (`AGENTS.md` rule 3).
- **Discovered by:** B

---

### 3. Clean areas

- **No native-resource leak per mini/maximise toggle.** `SnapLayouts` is instantiated exactly once (`core/api.py:560`, inside the single `_install_snap_layouts` call from `set_window`, `core/api.py:538`) and is never re-created or re-subclassed on a toggle. The `WNDPROC` callback object is held alive by `self._snap_layouts._proc` (`core/snap_layouts.py:165`, comment at `:145`), so the shell never calls into freed memory. `SnapLayouts.uninstall()` (`core/snap_layouts.py:222-240`) is never called by the application — and that is **correct**: the subclass lives for the whole process and the HWND dies with it, and the module's own docstring warns "Never release a callback while Windows might still reference it" (`:193`). Calling `uninstall()` during shutdown would restore a WndProc on a window that is about to be destroyed, for no benefit.
- **The deferred window-op threads do not leak.** Each `_deferred_window_op` thread is a daemon that sleeps once and terminates (`core/api.py:728-735`); no handle, no queue and no native resource is retained. The problem is the *ordering* of those threads (F-WX-12-5), not their lifetime.
- **The rAF loops really do park when the window is hidden.** All four background loops stop on the native minimise signal, and they do so *without* relying on `document.hidden` (which WebView2 does not necessarily change when the host form is minimised — pywebview never touches `CoreWebView2Controller.IsVisible`):
  | Loop | File:line | Stop condition | Parks on native minimise? |
  |---|---|---|---|
  | particles | `js/particles.js:473-480`, sync at `:51-61` | `isWindowHidden()` → `document.hidden` **or** `html.window-hidden` | **Yes** — `animFrameId = null; return` (`:475-478`) |
  | visualizer | `js/visualizer.js:330-334`, sync at `:242-249` | `documentVisible` flag fed by `nedotify:window_visibility_changed` (`:102-108`) | **Yes** — `animFrameId = null; return` (`:331-334`) |
  | player progress | `js/player.js:1371-1379`, sync at `:1489-1497` | `isPlayerUiHidden()` → `document.hidden` **or** `html.window-hidden` | **Yes** — `animFrameId = null; return` (`:1376-1379`) |
  | orbit glow | `js/player.js:2510-2542` | `!isPlayerUiHidden()` (`:2515`) → `stopOrbitGlowLoop()` | **Yes** — but **not** in mini mode (F-WX-12-6) |
  | CSS animations (aura orbs, spinners) | `ui/web_new_v2/css/components/base.css:22-29` | `html.window-hidden * { animation-play-state: paused !important; }` | **Yes** — independent of the efficiency settings |
  The signal chain is solid: pywebview `minimized` event (`core/api.py:522`) → `_on_minimized` → `_emit('window_visibility', {'hidden': True})` (`:599-600`) → `js/events.js:89-96` toggles `html.window-hidden` and dispatches `nedotify:window_visibility_changed` → every consumer listens for it. The events are de-duplicated (`js/events.js:92` breaks when the state is unchanged) so a repeated native event cannot restart the loops.
- **The `timeupdate` handler is cheap and deliberately keeps prefetching alive.** `js/player.js:592-616` does DOM writes only in the `currentDuration === 0` edge case, dispatches one local `nedotify:position_changed` event (consumed by the lyrics sync, `js/lyrics.js:304`) and reports the position to the backend every 5 s. When the window is hidden it still calls `checkPlaybackLookahead` (`:595-597`) so the next track is pre-resolved — the repo pins this deliberately (`tests/test_player_resources.py:130-132`).
- **The session write is atomic and the write-behind is flushed before exit.** `SettingsManager.flush()` writes the whole pending set in one transaction and re-queues anything that did not land (`core/settings.py:443-483`); `SessionManager.save_session` forces that flush explicitly (`core/session.py:65-68`); `atexit.register(self.flush)` (`core/settings.py:313`) is the last-resort net; and `AppCore.cleanup()` flushes again before `db.close()` (`core/app.py:557-560`).
- **`_emit` never runs on the UI thread.** `AppApi._emit` detects the main thread and hands the `evaluate_js` to an `EmitWorker` thread (`core/api.py:1147-1154`), pinned by `tests/test_emit_thread_safety.py`. (Note: the *comment* at `core/api.py:1141-1146` claims "the pywebview `loaded` event runs on the UI thread" — in this pywebview version the `loaded` handlers run in a fresh thread (`webview/event.py:55-60`), so the real UI-thread trigger is the WinForms event handlers such as `minimized`/`resized`; the guard is still correct, only its rationale is stale.)
- **The window-drag / resize path is sound.** `begin_window_drag` (`core/api.py:959-990`) and `begin_window_resize` (`:992-1030`) marshal `WM_NCLBUTTONDOWN` to the UI thread via `BeginInvoke` (`:737-747`), set the `SendMessageW` `argtypes` correctly so the 64-bit `lparam` is not truncated, and correctly refuse to resize a maximised or mini window (`:1001-1002`).
- **The DPI-aware geometry maths is correct.** `_get_scale_factor` / `_logical_workarea` / `_saved_pos_coords` (`core/api.py:629-719`) convert the physical `MONITORINFO.rcWork` into the logical pixels that `Window.move()` expects, and `_native_window_geometry` reads the bounds through `GetWindowRect` to avoid cross-thread WinForms getters (`:749-771`).

---

### 4. Coverage gaps

- **I did not run the application.** Per the ground rules the real app was not started (it would disturb the user's profile). Every runtime statement above is derived from the shipped sources plus the vendored pywebview sources; the *exact* frequency of the F-WX-12-3 race (whether the two event scripts beat the `requestIdleCallback`) can only be measured in a running instance. The static ordering argument is deterministic, the symptom's frequency is not.
- **No end-to-end minimise/tray/mini test exists**, so F-WX-12-1, -2, -3 and -4 are invisible to the suite: `tests/test_window_visibility.py:93-112` injects a fake tray with `tray.icon = object()` (so the real tray is never exercised), `:76` monkeypatches `_install_snap_layouts` away (so the unreachable block is never executed), and no test calls `toggle_mini_player` at all. `tests/test_window_maximize.py:57` replaces `_deferred_window_op` with an ordered list, so the real timing/ordering is not exercised. `tests/test_window_resize_api.py` covers only the native message constants. `tests/test_player_layout_geometry.py` is a **pure CSS-arithmetic** test (border radii, `player-view.css` / `tokens.css`) with no relation to the window state machine — it pins nothing in WX-12.
- **The `window-hidden` signal is only tested on the JS side.** `tests/test_visual_effects_lifecycle.py:181-196` and `tests/test_player_resources.py:123-136` prove that the *frontend* parks the loops when the class is set, and `tests/test_player_resources.py:139-162` proves the bridge event toggles the class. Nothing proves that the *native* minimise actually produces that event in a real WebView2 (i.e. that pywebview's `minimized` event fires for a frameless `Form.WindowState = Minimized`), nor that it fires for the frameless/maximised/snapped variants. That link is the load-bearing one for the whole background-cost story and it is untested.
- **The hidden-window CPU cost was not measured.** The repo's own harness `tools/bench/scenarios.py:55-60, 289-292` can drive `ShowWindow(SW_MINIMIZE)` and sample, but its results file `tools/bench/results/startup-200trk-20261003-212819.json` was aborted ("Another instance of NeDotify is already running") and contains no usable numbers (`tools/bench/build_hotspots.py:245-252`). All background-cost statements in this report are therefore **static** (code-level), not measured. Note also that `tools/bench/build_hotspots.py:90` still describes the player progress loop as "PARTIAL — the loop RE-SCHEDULES itself while hidden (player.js:1067)"; that is **stale** — the current `js/player.js:1376-1379` parks the loop. The benchmark artefact should be re-generated or corrected so it does not mislead the next reader.
- **The `_window_op_lock` contention (F-WX-12-10) was not reproduced under load** — the hold-time argument is from the code, not from a profile.
- **`~/.nedotify/` was not inspected** (forbidden by the ground rules), so the F-WX-12-11 statements about the on-disk secrets are derived from `core/database.py` / `core/settings.py` rather than from the actual file.
- **The WinForms minimise→restore semantics** (whether WinForms restores a maximised window to `Maximized` or to `Normal`, and how `Form.WindowState` reports it afterwards) were not verified on a live form. The part of that question that *is* verified by code is the mini-player geometry loss (F-WX-12-4), which does not depend on it.

---

### 5. Architecture improvements (ARCH)

- **ARCH-1 — One window-state object instead of seven booleans and three representations.** A single `WindowState` enum (`NORMAL / MINIMIZED / MINI / MAXIMIZED / HIDDEN`) owned by a `WindowController` that owns the native window, the geometry bookkeeping (`_last_geometry`, `_saved_main_geometry`, `_saved_mini_pos`), the `mini-player-active` CSS class and the `window-hidden` class, and that exposes a single `apply(desired_state)` transition. Today the state is spread over `core/api.py` (three booleans + three geometry fields), the WinForms form (`WindowState`, `MinimumSize`, `TopMost`) and the DOM (two CSS classes), and each of them is written from a different place (see the table in F-WX-12-4). This is the root cause of F-WX-12-4, -5, -7 and -8.
- **ARCH-2 — A readiness handshake instead of a fire-and-forget event channel.** The backend assumes "page loaded ⇒ the UI receives events"; the frontend installs its dispatcher ~0–300 ms later. A `ui_ready()` call from the frontend (or a pull-based `get_state()`) makes the restore deterministic and removes the whole class of "the event was sent before anyone listened" bugs (F-WX-12-3) — and it also removes the need for the fixed `setTimeout(…, 400)` / `setTimeout(…, 600)` heuristics in `js/events.js:422-426`.
- **ARCH-3 — One serialised window-operation worker instead of a thread per operation.** `_deferred_window_op` spawns a thread that sleeps and hopes. A single worker with a "desired state + generation counter" queue would give ordering, cancellation and coalescing for free, and would let the mini-player transition collapse a burst of toggles into one native op (F-WX-12-5, -7).
- **ARCH-4 — Split the lock scopes.** `_window_op_lock` currently covers both the native window operations and the listening/playback bookkeeping (F-WX-12-10). The repo's own rule ("a new shared field joins its class's existing lock") is about *not* opening a second lock for the same class, not about reusing one lock for two different critical sections; a `_window_state_lock` and a `_playback_state_lock` would each have a clear, documented scope.
- **ARCH-5 — Replace the dead dual-window API and the dead `mini_player_toggled` channel with the truth.** `set_windows`/`_mini_window` (never called) suggests a design where the mini player is a second window; the implementation is a CSS mode of one HWND. Likewise, `js/events.js:233-239` implements a "the backend confirms the mini state" event that the backend never sends. Either implement the second window / the confirmation event, or delete both seams, so the guard at `core/api.py:889` stops depending on `_mini_window` being `None` for correctness and the frontend stops carrying a channel that can never fire (F-WX-12-9).
- **ARCH-6 — A lifecycle registry for native resources.** `SnapLayouts` is installed by a side effect of a function whose job is something else, and the tray/icon start-up is another side effect of the same function (F-WX-12-1). A tiny "startup tasks" list on the window (install snap subclass → start tray → set icon), each with its own retry policy and its own log line, would make the failure of one visible and would remove the class of "unreachable because it sits after a `return`" defects. It also gives the missing teardown symmetry (install/uninstall, start/stop) for the tray and the window subclass.
- **ARCH-7 — Make the "state I persist" list and the "state I read" list one list.** `session.last_volume` and `general.start_minimized` are written but never read (F-WX-12-9); the same class of drift will produce the next one. A declarative session schema (a list of field names used by both `save_session` and `restore_session`, with a test asserting the symmetry) would prevent it.
- **ARCH-8 — Move the secrets out of the generic settings table.** `auth.yandex_token` / `auth.oauth_client_secret` are plaintext rows next to the session rows (F-WX-12-11). The masking at the API boundary is a good practice, but the storage boundary is where the protection belongs.
- **ARCH-9 — Re-generate the benchmark artefacts or delete them.** `tools/bench/build_hotspots.py:90` still claims the player progress loop keeps re-scheduling itself while hidden, which the current `js/player.js:1376-1379` no longer does. A stale perf artefact in the repo is worse than none: it was the first thing that made me suspect a background-CPU defect that does not exist.
