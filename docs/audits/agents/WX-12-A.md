## AREA WX-12 — Background/foreground, minimise-to-tray, mini-player, and app restart state continuity — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Ranges read | Why |
|---|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 | mandatory brief |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 | area map / WX table |
| `docs/audits/_FINDINGS_SO_FAR.md` | 1–205 | previous run's register (to avoid double-reporting) |
| `core/api.py` | 330–520 (init/`__init__`/cleanup/offline), 514–1200 (window block), 1195–1450, 1437–1660, 1770–1850, 1950–2030, 2915–2975 | bridge surface for the whole scenario |
| `core/tray.py` | 1–194 (whole file) | tray |
| `core/session.py` | 1–96 (whole file) | session persist/restore |
| `core/settings.py` | 50–160, 160–300, 330–560 | defaults + `SettingsManager` |
| `core/app.py` | 85–165, 500–586 | AppCore wiring + `cleanup()` |
| `core/snap_layouts.py` | 115–155 | cross-check for the DPI pattern |
| `core/services/discord_rpc.py` | 80–169 | presence on restore |
| `main.py` | 1–584 (whole file) | bootstrap, `on_loaded`/`on_closed`, session save |
| `ui/web_new_v2/js/main.js` | 20–79, 120–239, 340–504, 500–629 | bridge gate, mini-player toggle, app init order |
| `ui/web_new_v2/js/events.js` | 1–60, 60–179, 220–299, 400–459 | Python→JS dispatcher, `window_visibility`, `session_autoplay` |
| `ui/web_new_v2/js/player.js` | 30–59, 235–305, 570–649, 826–924, 1195–1264, 1330–1389, 1440–1519, 1973–2040 | volume/mute, `timeupdate`, rAF loop, visibility |
| `ui/web_new_v2/js/efficiency.js` | 1–192 (whole file) | visibility / efficiency throttling |
| `ui/web_new_v2/js/visualizer.js` | 1–140, 140–259, 260–339 | visualizer rAF loop + visibility |
| `ui/web_new_v2/js/particles.js` | 20–109, 330–389, 455–494 | particle rAF loop + visibility + mini-mode guard |
| `ui/web_new_v2/js/queue.js` | 1–179 | queue restore visibility |
| `ui/web_new_v2/js/settings.js` | 700–819, 1265–1304, 1500–1539, 2550–2609 | settings application, mini-player position |
| `ui/web_new_v2/js/lyrics.js` | 295–354, 1060–1119 | `position_changed` consumer |
| `ui/web_new_v2/js/window-resize.js` | 1–22 (whole file) | mini-mode drag/resize guards |
| `ui/web_new_v2/js/boot.js` | 1–72 (whole file) | boot-time globals (no event dispatcher) |
| `ui/web_new_v2/css/components/base.css` | 2550–2629 | `mini-player-active` / `window-hidden` rules |
| `ui/web_new_v2/index.html` | grep for `btn-close`, `mini-player-overlay`, `visualizer-canvas`, `app-container`, script tags | wiring |
| `tests/test_window_visibility.py` | 1–130 (whole file) | what the existing tests actually pin |
| `.venv_win/.../webview/util.py` | 155–234 | `inject_pywebview` — when `loaded` fires vs `pywebviewready` |
| `.venv_win/.../webview/event.py` | 1–93 | `Event.set()` runs handlers in a spawned thread |
| `.venv_win/.../webview/js/finish.js` | 1–12 | `pywebviewready` dispatch point |
| `.venv_win/.../webview/platforms/edgechromium.py` | 108–147 | `evaluate_js` marshalling |
| `.venv_win/.../webview/platforms/winforms.py` | 165–204, 490–529 | `scale_factor` (not `_scale`), `resize()` vs `move()` scaling |

**Callees traced into other areas**

- `core/tray.py` → `pystray` 0.19.5 (installed package) — `Separator` is not exported.
- `core/settings.py` → `core/database.py::set_settings_batch` (write-behind, 0.5 s batch).
- `core/session.py` → `core/settings.py` (`session` category rows in the `settings` table).
- `core/api.py::_emit` → pywebview `evaluate_js` → `window.onPythonEvent` → `js/events.js::dispatchPythonEvent`.
- `main.py::on_loaded` → `core/api.py::_on_track_changed` → `core/services/discord_rpc.py`, `core/api.py::_listening_for_track` → `core/listening.py`.
- `audio/queue.py::set_tracks` (owner: WN-17) — consulted for the restore ordering of shuffle.

**Explicitly not opened:** `android/` (out of scope). No source file was modified.

---

### 2. Findings

#### F-WX-12-1  [P1] — The system tray is never started: `self._tray.start()` sits behind an unconditional `return False`, so "minimise to tray" is impossible and ✕ destroys the window

- **File:** `core/api.py:542-597` (dead block `:574-597`), consumer `core/api.py:917-938`; second blocker `core/tray.py:13-19`
- **Confirmed:** yes (proved by AST + by executing the import in the project venv)
- **Description:** `_install_snap_layouts()` ends with `return False` on **every** code path, so the two statements that follow it — the tray start and the native window-icon helper — are unreachable. `self._tray.start()` occurs exactly once in the whole repository and that occurrence is inside the dead block. The tray therefore never runs, `TrayIcon.icon` stays `None`, and `AppApi.close()`'s `tray_available` test is always `False`; the ✕ button / `mp-btn-close` therefore take the "destroy the window" branch and the application exits instead of hiding to the tray. Independently, `core/tray.py` would still refuse to start: `from pystray import MenuItem as item, Menu, Separator` raises `ImportError` on the installed pystray 0.19.5 (which exports only `Icon`, `Menu`, `MenuItem`), the broad `except` swallows it, and `HAS_PYSTRAY` is permanently `False`.
- **Cause:** a `return` statement was left in the middle of a function whose remainder was later appended below it (the tray/icon block was evidently meant to run after the snap-layout install). The second cause is an import that names a symbol pystray does not export.
- **Trigger conditions:** every launch. There is no code path that starts the tray.
- **User impact:** the `general.minimize_to_tray` setting (default `True`) has no effect. Clicking ✕ (or the mini-player ✕) quits the app instead of hiding it; "minimise to tray" and the tray menu (restore / play-pause / next / prev / exit) do not exist for the user. The window also keeps the default pywebview taskbar icon instead of `icon.ico`.
- **Evidence:**
  ```python
  # core/api.py:571-597
      logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
      return False

      if getattr(self, "_tray", None):     # <-- unreachable
          self._tray.start()

      try:                                  # <-- unreachable
          import threading
          def _set_icon():
              ...
  ```
  ```python
  # core/api.py:917-938
  def close(self):
      """Close window or minimize to tray depending on general.minimize_to_tray setting."""
      ...
      tray_mgr = getattr(self, "_tray", None) or getattr(self._core, "tray", None)
      tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)

      if minimize_to_tray and tray_available:
          self._window.hide(); self._on_minimized(); return {...}
      self.flush_listening()
      closer = threading.Timer(0.1, self._window.destroy)
  ```
  ```python
  # core/tray.py:13-19
  try:
      from PIL import Image
      import pystray
      from pystray import MenuItem as item, Menu, Separator   # Separator does not exist
      HAS_PYSTRAY = True
  except (ImportError, Exception):
      HAS_PYSTRAY = False
  ```
- **Reproduction / verification:**
  1. AST proof that the block is dead:
     ```
  & ".venv_win\Scripts\python.exe" -c "
  import ast; t=ast.parse(open('core/api.py',encoding='utf-8').read())
  for n in ast.walk(t):
      if isinstance(n,ast.FunctionDef) and n.name=='_install_snap_layouts':
          for i,s in enumerate(n.body):
              if isinstance(s,ast.Return): print(i, s.lineno, [ (type(x).__name__, x.lineno) for x in n.body[i+1:] ])"
  ```
     → `5 572 [('If', 574), ('Try', 577)]` — two statements follow the last `return`.
  2. `& ".venv_win\Scripts\python.exe" -c "import core.tray as t; print(t.HAS_PYSTRAY)"` → `False` (pystray 0.19.5 installed).
  3. `Select-String -Path core\*.py,main.py -Pattern '_tray\.start'` → 1 hit, `core/api.py:575` (inside the dead block).
  4. Runtime (needs the real app): the ✕ button closes the process instead of hiding it; no tray icon appears.
- **Suggested fix:** move the tray start + icon helper **above** the final `return`, or into their own method invoked from `set_window()`/`_install_snap_layouts()`; import `Separator` from `pystray` only if it exists (pystray ≥ 0.19 exposes `pystray.Separator`? — verify: it does **not**; use `pystray.Menu.SEPARATOR` / build the separator from `pystray.MenuItem` instead), and log loudly when `HAS_PYSTRAY` is `False` instead of `logger.info`.
- **Fix side effects:** starting the tray changes the ✕ semantics — `close()` will start hiding the window instead of quitting, so the app would keep running in the background and `main.py`'s exit path (session save) would only run when the user picks "Выход" in the tray. `TrayIcon.on_exit` calls `self.api._window.destroy()`, which does return control to `webview.start()` and therefore triggers the session save — that path must be verified once the tray actually runs.
- **Discovered by:** A
- **Cross-reference (not a new finding):** the previous run recorded the same two root causes as `F-AR-04-1` and `F-AR-04-2` in `docs/audits/_FINDINGS_SO_FAR.md:65-66`. The owning area is **WN-04** (bridge window management) / **WN-16** (tray). It is repeated here because WX-12 is the scenario that makes it user-visible; it is **one** root cause with two independent blockers, not two findings.

---

#### F-WX-12-2  [P1] — The persisted volume is never restored to the player: the frontend hard-codes 70 % and nothing ever reads `audio.volume`

- **File:** `core/api.py:1956-1962` (writer), `core/settings.py:71-85` (storage), `ui/web_new_v2/js/player.js:15, 1973-1992` (reader), `ui/web_new_v2/js/main.js:390-423` (settings load), `core/api.py:2922-2938` (`get_settings` shape)
- **Confirmed:** yes
- **Description:** `AppApi.set_volume()` persists the volume into `audio.volume` (a DB row). The only frontend reader is `applySettings(settings)` in `player.js`, which reads **`settings.volume` at the top level** — but `get_settings()` returns a *category* dictionary (`{app: {...}, audio: {volume: 70, ...}, ...}`), so `settings.volume` is always `undefined` and the assignment never runs. `applyAudioSettings()` (the function that does handle the `audio` sub-dictionary) only looks at `output_device`. The frontend never calls `get_volume()`, and `currentVolume` stays at its module-level literal `70`. The mute flag, by contrast, *is* restored (via `is_muted()`), so the mute state and the volume state are restored from two different places and only one of them works.
- **Cause:** a shape mismatch between the producer (`get_settings()` → `{category: {...}}`) and the consumer (`settings.volume` at the top level). The same class of bug is already known for `settings.shuffle` / `settings.repeat` (`_FINDINGS_SO_FAR.md:72`, `FULL_PROJECT_AUDIT.md:72`).
- **Trigger conditions:** every application restart after the user changed the volume.
- **User impact:** the playback volume silently snaps back to 70 % on every restart, regardless of the user's setting; the volume slider in the player bar also shows 70 %. A user who had turned the music down to 20 % to avoid disturbing others gets a full-volume blast on the next launch.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/player.js:14-15
  let animFrameId = null;
  let currentVolume = 70;          // <-- the only initial value

  // ui/web_new_v2/js/player.js:1986-1988  (applySettings)
  if (settings.volume !== undefined) {
      currentVolume = settings.volume;   // never true: get_settings() is a category map
  }

  // ui/web_new_v2/js/player.js:241-248  (applyAudioSettings — the audio sub-map)
  export function applyAudioSettings(settings = {}) {
      if (settings.output_device !== undefined) { ... }   // volume is not handled
  }
  ```
  ```python
  # core/api.py:1956-1962
  def set_volume(self, volume: int):
      """Set playback volume (0-100)."""
      self._core.settings.set("audio", "volume", volume)
  ```
  ```python
  # core/api.py:2929-2938 — the shape the frontend receives
  categories = ['app', 'appearance', 'player', ..., 'audio', ..., 'theme', ...]
  res = {}
  for c in categories:
      cat_data = self._core.settings.get_category(c)
      if cat_data: res[c] = _mask_secrets(c, cat_data)
  return res
  ```
  Grep proof that nothing else restores it: `grep -rn "get_volume\|settings.audio.volume\|audio?.volume" ui/web_new_v2/js` → only `player.js:1986` (`settings.volume`) and `settings.js:877` (`settings.audio.volume_normalization`, a different key). `api('get_volume')` has **zero** call sites in the UI.
- **Reproduction / verification:**
  1. Set the volume to 15 % (the slider calls `api('set_volume', 15)` → `settings.set("audio","volume",15)` → DB row `audio.volume` = 15).
  2. Quit the app and relaunch it.
  3. Observe: the player-bar volume slider is at 70 % and the audio element plays at 0.7 (`player.js:15`, `player.js:1986-1991` never fire).
  4. Static equivalent: `get_settings()` returns `{'audio': {'volume': 15, ...}}`; `settings.volume` → `undefined`; `applySettings` leaves `currentVolume` at 70.
- **Suggested fix:** restore the volume explicitly on the frontend — e.g. in `applyAudioSettings()` read `settings.volume` from the `audio` sub-map and call the same code path as the volume drag (`currentVolume = v; setEl('pb-volume-fill', …); activeAudio.volume = …`), or have the frontend call `get_volume()` next to the existing `is_muted()` call in `initPlayer()`.
- **Fix side effects:** the restored value must be clamped to 0–100 and re-applied to `activeAudio` after a track change; `player.js` currently assumes the volume only changes through user gestures, so a restore path also needs to survive the `applyMuteState()` interaction (mute is stored separately and must win over the restored level).
- **Discovered by:** A
- **Cross-reference:** the shape mismatch family is owned by **WX-03 / WN-14**; this entry is the WX-12-visible consequence (a setting that does not survive a restart).

---

#### F-WX-12-3  [P1] — The restart restore (`track_changed` + `session_autoplay`) is emitted before the frontend's event dispatcher exists and is never replayed, so the restored track and position can be lost

- **File:** `main.py:389-402` (emitter), `main.py:313-330` (the pre-window restore), `core/api.py:1122-1159` (`_emit`), `ui/web_new_v2/js/events.js:46-65, 71-73` (dispatcher), `ui/web_new_v2/js/main.js:350-372, 506-545` (init order)
- **Confirmed:** the ordering is **yes** (proved); whether the event is actually dropped is a **race** that is heavily biased towards "lost" on a cold start
- **Description:** `main.py::on_loaded` re-emits the restored track and the autoplay request. pywebview fires `loaded` from `inject_pywebview()` immediately after `run_js(finish_script)` returns — and `finish.js` is the script that dispatches `pywebviewready`, i.e. the event that starts the frontend's `init()`. So the restore events are pushed into the renderer within a few milliseconds of `init()` starting, while `initEvents()` — the function that installs the handler that actually processes `track_changed` / `session_autoplay` — sits behind `awaitBridge()` **plus** an awaited `requestIdleCallback`/`setTimeout` ("Icons" step). `dispatchPythonEvent()` drops any event whose `coreEventHandler` is still `null`, and there is no queue or replay. There is no `get_current_track` bridge method and the frontend never polls for the current track, so the `track_changed` event is the *only* way the UI learns about the restored track.
- **Cause:** the backend's restore path is fire-and-forget over a one-way bridge with no readiness handshake and no replay buffer; the frontend's event handler is registered asynchronously *after* the bridge becomes available, i.e. after the point at which the backend starts emitting.
- **Trigger conditions:** every restart with a non-empty saved session. The outcome depends on whether the renderer's `requestIdleCallback` fires before the Python→JS `evaluate_js` round trip completes — on a cold WebView2 start (the normal restart case) the renderer is busy, the rIC is late, and the restore events arrive first and are dropped.
- **User impact:** after a restart the player can come up with **no track, no position and no queue highlight**, even though the backend has the restored queue in memory. The queue itself is still recoverable (opening the queue drawer calls `get_queue()`), but the "now playing" state and the resume position are gone. Because `session_autoplay` is lost together with `track_changed`, the autoplay path cannot even self-start (`events.js:423` calls `togglePlayPause()`, which needs `currentTrack`, set only by `onTrackChanged`).
- **Evidence:**
  ```python
  # main.py:389-402
  def on_loaded():
      logging.info(...)
      if app_core.engine.queue.current_track:
          app_core.engine._on_track_changed(app_core.engine.queue.current_track)
      try:
          if app_core.session.should_autoplay and app_core.engine.queue.current_track:
              api.emit_event("session_autoplay", {...})
  ```
  ```js
  // ui/web_new_v2/js/events.js:46-65
  let coreEventHandler = null;                 // null until initEvents() runs
  function dispatchPythonEvent(eventName, data) {
      if (coreEventHandler) { ... }             // <-- silently dropped when null
      for (const fn of pythonEventHandlers.slice()) { ... }
  }
  ```
  ```js
  // ui/web_new_v2/js/main.js:516-528  (initEvents is behind an awaited rIC)
  await safeInit('Icons', () => new Promise((resolve) => {
      if (window.requestIdleCallback) { window.requestIdleCallback(runIcons, { timeout: 300 }); }
      else { setTimeout(runIcons, 50); }
  }));
  await safeInit('Events', () => initEvents());
  ```
  ```python
  # .venv_win/.../webview/util.py:215-222  (loaded fires right after finish.js ran)
  window.run_js(finish_script % {'functions': json.dumps(func_list)})
  window.events.loaded.set()
  ```
  ```python
  # .venv_win/.../webview/event.py:55-60  (the handler runs in a spawned thread)
  if self._items:
      if self._should_lock: execute()
      else:
          t = threading.Thread(target=execute); t.start()
  ```
- **Reproduction / verification:**
  1. Play a track, let the queue fill, quit the app (so `session.last_queue` / `last_track_id` are written).
  2. Relaunch. With `NEDOTIFY_DEVTOOLS=1` open the WebView2 DevTools console.
  3. Look for `Python Event: track_changed` (it *is* logged by `events.js:74` `console.log('Python Event:', ...)`) **before** `[Init] Events loaded` (`main.js:509`). If `track_changed` is logged before the Events module is initialised, the handler did not exist and the restore was dropped.
  4. Deterministic static equivalent: the restore is emitted from `on_loaded`, and `initEvents()` is only reachable after `awaitBridge()` + a `requestIdleCallback`; `pywebviewready` (which unblocks `awaitBridge`) is dispatched by the same `finish.js` whose completion triggers `loaded`. There is no ordering guarantee in the frontend's favour.
  5. Cross-check that no other channel exists: `grep -n "def get_current_track\|def get_player_state" core/api.py` → no matches; the frontend never polls.
- **Suggested fix:** make the restore explicit and acknowledged — e.g. have the frontend, once `initEvents()` has run, ask the backend for the current state (`get_current_track()` / `get_queue()`) instead of relying on a push; or have the backend queue events emitted before the frontend is ready and flush them when the frontend signals readiness (`nedotify:app_ready` is already dispatched at `main.js:617`).
- **Fix side effects:** a pull-based restore must not fight the normal `track_changed` flow (double `onTrackChanged` → a duplicate listening session); a push-based replay must be bounded and must not replay stale events after a deliberate "clear queue".
- **Discovered by:** A
- **Cross-reference:** the missing replay buffer in `core/api.py::_emit` is owned by **WN-03** (already noted as a P3 in `_FINDINGS_SO_FAR.md:146`: "events emitted before the UI installs `window.onPythonEvent` are dropped with no queue or replay"). The `on_loaded` ordering is **WX-07 / WN-01** territory. The consequence is reported here because WX-12 is the scenario in which it is user-visible.

---

#### F-WX-12-4  [P2] — The mini-player transition can never report failure: the native op runs 250 ms later on a worker thread while the bridge has already answered `success: true`, so the CSS state and the native window can diverge silently

- **File:** `core/api.py:773-790` (`toggle_mini_player`), `:792-824` (`_enter_mini_mode`), `:826-859` (`_exit_mini_mode`), `:721-735` (`_deferred_window_op`), `ui/web_new_v2/js/main.js:175-205` (frontend)
- **Confirmed:** yes
- **Description:** `toggle_mini_player()` sets `_is_mini_active`, calls `_enter_mini_mode()` / `_exit_mini_mode()` and returns `{"success": True, "is_mini": enable}` immediately. The actual WinForms work is deferred: `_deferred_window_op(0.25, …)` sleeps 250 ms on a background thread and then runs the geometry change on the UI thread. Every failure inside `_enter_mini_mode` / `_exit_mini_mode` is swallowed by their own `except Exception as err: logger.debug(...)`, and `_deferred_window_op` only logs a warning — so `toggle_mini_player` can never return `success: False`. The frontend's rollback path (`main.js:197-203`, which removes the optimistic `mini-player-active` class and shows a toast) is therefore dead code.
- **Cause:** the bridge acknowledges an *intent* instead of a *result*, and the two callees swallow their own errors, so no failure can ever propagate back to the caller.
- **Trigger conditions:** any mini-player toggle whose native part fails — a `SetWindowPos`/`resize` that the OS refuses, a window handle that is momentarily invalid, a display-change during the 250 ms window, or a fast double-toggle.
- **User impact:** the UI can show the compact mini-player card while the native window is still the full 1100×800 window (or the reverse). The user sees a 380×110 window with a full-size layout, or a full-size window with a mini-player layout; no error is shown and no toast appears.
- **Evidence:**
  ```python
  # core/api.py:773-790
  def toggle_mini_player(self, enable: bool):
      try:
          self._is_mini_active = enable
          if enable: self._enter_mini_mode()
          else:     self._exit_mini_mode()
          return {"success": True, "is_mini": enable}
      except Exception as e:
          return {"success": False, "is_mini": not enable}
  ```
  ```python
  # core/api.py:823-824  (inside _enter_mini_mode)
  except Exception as err:
      logger.debug(f"Failed setting mini size: {err}")
  ```
  ```python
  # core/api.py:721-735
  def _deferred_window_op(self, delay: float, fn):
      def _run():
          time.sleep(delay)
          try:
              with self._window_op_lock: fn()
          except Exception as e:
              logger.warning("Deferred window operation failed: %s", e, exc_info=True)
      threading.Thread(target=_run, daemon=True).start()
  ```
  ```js
  // ui/web_new_v2/js/main.js:196-203 — unreachable in practice
  if (!backendOk) {
      document.body.classList.toggle('mini-player-active', isCurrentlyMini);
      window.dispatchEvent(new CustomEvent('nedotify:toast', {...}));
      return isCurrentlyMini;
  }
  ```
- **Reproduction / verification:**
  1. Enter the mini player (the `btn-mini-player` button or the `KeyP` hotkey) on a machine where `resize()` fails — e.g. dock the window to a display that is being disconnected, or force `self._window.resize` to raise via a debugger.
  2. Observe: the bridge promise resolves with `{success: true}`, no toast appears, and `document.body.classList.contains('mini-player-active')` stays `true` while the native window never shrank.
  3. Static equivalent: monkey-patch `AppApi._enter_mini_mode` to raise — the outer `try` in `toggle_mini_player` would catch it and return `success: False`, but the *inner* `try/except` inside `_enter_mini_mode` already ate the exception, so the outer handler is unreachable for native failures.
  4. Also observable: the deferred ops are unordered — two toggles 100 ms apart schedule two `_deferred_window_op` calls that can run in either order (`_deferred_window_op` has no sequencing token), so a fast mini→full toggle can leave the window in the wrong mode.
- **Suggested fix:** make the native op report its result back to the frontend (e.g. have the deferred op emit a `mini_player_state` event with the real geometry, and let the frontend reconcile the CSS class with it), and stop swallowing the exceptions in `_enter_mini_mode` / `_exit_mini_mode` — at minimum log at `warning` and let `toggle_mini_player` return a failure the frontend can roll back.
- **Fix side effects:** returning a real failure means the frontend must roll back the optimistic class — that path exists (`main.js:197-203`) but has never been exercised, so it needs a test. Making the transition event-driven adds a round trip that can arrive after the user has toggled again; the event must carry a generation/sequence number.
- **Discovered by:** A
- **Cross-reference:** the previous run recorded the two halves as P2 items in `_FINDINGS_SO_FAR.md:98-99` ("The mini-player transition is not atomic…" and "Deferred window operations are unordered…"). The owning area is **WN-04**.

---

#### F-WX-12-5  [P2] — The session is written only at process exit: hiding/minimising the window persists nothing, and the resume position is sampled at most every 5 s

- **File:** `main.py:557-571` (the only `save_session` call), `core/session.py:39-68`, `core/api.py:1407-1422` (`report_position`), `ui/web_new_v2/js/player.js:610-616` (the 5 s report throttle), `core/api.py:917-938` (`close`)
- **Confirmed:** yes
- **Description:** `save_session()` has exactly **one** call site in the whole repository: `main.py:561`, after `webview.start()` has returned. Nothing is written when the window is minimised, when it is hidden to the tray, or on any other lifecycle event. Consequently the persisted "last queue / last position" is only ever as fresh as the last clean exit. The saved position is `engine._last_reported_position`, which the frontend refreshes at most every 5 s (`player.js:612-616`), so the resumed position can be up to 5 s stale — and is `0` if the frontend never reported (e.g. the app was killed within the first 5 s of playback).
- **Cause:** session persistence was implemented as a shutdown hook rather than as a periodic/checkpointed save; the `close()` path that hides the window to the tray deliberately does not exit the process, so it never reaches the save.
- **Trigger conditions:** minimise the window (or hide it to the tray, once F-WX-12-1 is fixed) and then end the process abnormally — Task Manager, a crash, an OS shutdown, a power loss. A clean exit is fine.
- **User impact:** after such an exit the user's queue and resume position are lost; the app comes up with an empty queue, and with `audio.autoplay` enabled there is nothing to resume. The user has to rebuild the queue by hand.
- **Evidence:**
  ```python
  # main.py:557-571 — the ONLY save_session() call site in the repo
  # Save session before exit
  try:
      engine = app_core.engine
      app_volume = app_core.settings.get("audio", "volume", 70)
      app_core.session.save_session(
          track_id=engine.queue.current_track.get("id") if engine.queue.current_track else None,
          position=getattr(engine, '_last_reported_position', 0),
          volume=app_volume, queue=engine.queue.tracks,
          queue_index=engine.queue._current_index,
          shuffle=engine.queue.shuffle, repeat=engine.queue.repeat)
  except Exception as e:
      print(f"Failed to save session: {e}")
  ```
  ```js
  // ui/web_new_v2/js/player.js:611-616
  const now = performance.now();
  if (now - (window._lastReportTime || 0) > 5000) {
      window._lastReportTime = now;
      api('report_position', currentPosMs, currentDuration, 0, currentTrack?.listening_session);
  }
  ```
  ```python
  # core/session.py:57-68 — what is actually written (one settings row per key)
  self.settings.set("session", "last_track_id", track_id)
  self.settings.set("session", "last_position", position)
  ...
  flush = getattr(self.settings, "flush", None)
  if callable(flush): flush()
  ```
- **Reproduction / verification:**
  1. `Select-String -Path *.py,core\*.py -Pattern 'save_session'` → 2 hits (`core/session.py:39` definition, `main.py:561` call).
  2. Play a track, let it run for 30 s, press the minimise button (the app keeps running), then kill the process from Task Manager. Relaunch: the queue is empty and `session.last_position` in the DB is the value from the *previous* exit.
  3. The 5 s granularity is visible in the DB: `SELECT value FROM settings WHERE key='session.last_position'` changes only every ~5 s while playing.
- **Suggested fix:** checkpoint the session periodically (e.g. on the existing 5 s position report, or on a 15–30 s timer) and on the hide-to-tray path, so the persisted state is at most a few seconds old; the write is cheap (7 settings rows, batched by `SettingsManager`).
- **Fix side effects:** a periodic `save_session()` writes `session.last_queue` (up to 200 track dicts) on every checkpoint — that is a JSON blob in the `settings` table, so the flush interval matters (`SettingsManager.FLUSH_INTERVAL_SECONDS = 0.5`). Writing it every 5 s would add measurable DB churn; a 30 s cadence plus a checkpoint on hide/close is the safer trade-off.
- **Discovered by:** A
- **Cross-reference:** the "session is written once, at exit" design is already noted in the previous register (`_FINDINGS_SO_FAR.md:44`: "`core/session.py:9,50-55` caps the persisted queue at 200 entries and writes once, at exit") — the *consequence* for WX-12 (nothing is persisted on minimise-to-tray) is reported here.

---

#### F-WX-12-6  [P2] — `_exit_mini_mode` restores the window *position* in physical pixels into a logical-pixel API, and `_get_scale_factor()` always returns `1.0`, so on a scaled display the restored window lands in the wrong place

- **File:** `core/api.py:629-648` (`_get_scale_factor`), `:650-696` (`_logical_workarea`), `:749-771` (`_native_window_geometry`), `:826-859` (`_exit_mini_mode`), `:897-908` (`_apply_window_pos`)
- **Confirmed:** the attribute mismatch is **yes** (pywebview 5.4 exposes `scale_factor`, not `_scale`); the on-screen displacement is a **hypothesis** (it needs a scaled display to observe)
- **Description:** `_exit_mini_mode()` reads the saved geometry with `GetWindowRect` (physical pixels) and feeds the position straight back into `target_win.move(int(gx), int(gy))`. pywebview's WinForms `move()` multiplies its argument by `self.scale_factor` before calling `SetWindowPos`, so a physical coordinate is scaled a second time. The same physical/logical confusion exists on the mini-player placement path, because `_logical_workarea()` divides the physical `GetMonitorInfoW` rectangle by `_get_scale_factor()` — and `_get_scale_factor()` reads `native._scale`, an attribute pywebview does not have, so it always returns `1.0` and the "conversion" is a no-op.
- **Cause:** the module mixes three coordinate spaces: Win32 physical pixels (`GetWindowRect`, `GetMonitorInfoW`), pywebview logical pixels (`resize()`, `move()`), and a scale factor that is read from a non-existent attribute. The repository already contains the correct pattern elsewhere (`core/snap_layouts.py::_dpi_scale` uses `GetDpiForWindow`).
- **Trigger conditions:** a display scaled above 100 % (150 % / 125 % is the common case), and the mini-player enter/exit cycle.
- **User impact:** on a 150 % display the mini player is placed outside the visible work area (the coordinates are 1.5× too large) and the restored full window opens at a position 1.5× further right/down than where the user left it — potentially off-screen, so the window appears to vanish.
- **Evidence:**
  ```python
  # core/api.py:636-648
  native = getattr(self._window, "native", None)
  scale = getattr(native, "_scale", None)          # pywebview has `scale_factor`
  ...
  val = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
  return val
  ```
  ```python
  # .venv_win/.../webview/platforms/winforms.py:512-528
  def move(self, x, y):
      if self.scale_factor != 1:
          x_modified = x * self.scale_factor        # <-- the argument is LOGICAL
          y_modified = y * self.scale_factor
          windll.user32.SetWindowPos(self.Handle.ToInt32(), None, int(x_modified), int(y_modified), ...)
  ```
  ```python
  # core/api.py:847-848
  if gx is not None and gy is not None and hasattr(target_win, 'move'):
      target_win.move(int(gx), int(gy))             # gx/gy come from GetWindowRect (physical)
  ```
  Note that the *size* restore is fine (`resize()` passes its arguments straight to `SetWindowPos`), so only the position is double-scaled.
- **Reproduction / verification:**
  1. Static: `grep -rn "scale_factor" .venv_win/Lib/site-packages/webview/platforms/winforms.py` → the attribute is `scale_factor`; `grep -rn "_scale" .venv_win/Lib/site-packages/webview/` → no match. Therefore `_get_scale_factor()` returns `1.0` on every machine.
  2. On a 150 % display, enter the mini player with the position set to `bottom-right`: `_logical_workarea()` returns the physical work area (e.g. 2880×1706 for a 1920×1138 logical area) → `_saved_pos_coords` computes a physical x of ~2820 → `move(2820, …)` → pywebview multiplies by 1.5 → 4230 physical → off-screen.
  3. Same for `_exit_mini_mode`: the window reappears at 1.5× its original offset.
- **Suggested fix:** read the real scale factor (`native.scale_factor`, or better `GetDpiForWindow(hwnd)` as `core/snap_layouts.py` does) and keep one coordinate space end-to-end; convert the Win32 physical rectangle to logical coordinates before calling `move()`.
- **Fix side effects:** on a 100 % display nothing changes (factor 1.0), so the change is low-risk; but on multi-monitor setups with different per-monitor DPI, pywebview's `scale_factor` is the **primary device's** factor (`GetScaleFactorForDevice(0)`), so it is only an approximation — a per-window DPI query is the correct source.
- **Discovered by:** A
- **Cross-reference:** already recorded as `F-AR-04-3` in `_FINDINGS_SO_FAR.md:67`; the owning area is **WN-04**. Repeated here because the mini-player transition is the WX-12 surface where it is user-visible.

---

#### F-WX-12-7  [P3] — Two persisted state fields are dead: `session.last_volume` is written but never read, and `general.start_minimized` has no reader anywhere

- **File:** `core/session.py:57-63, 70-80`, `core/settings.py:60-70, 256-264`, `main.py:313-320, 557-569`
- **Confirmed:** yes
- **Description:** `save_session(volume=…)` writes `session.last_volume`, and `restore_session()` returns it as `session["volume"]` — but `main.py` reads only `position` and `queue` from the restored blob, so the value is never applied anywhere. Separately, `general.start_minimized` is declared in `DEFAULT_SETTINGS` but has **zero** readers and **zero** writers outside the defaults table: there is no UI toggle and no Python consumer, so "start minimised" is not a feature.
- **Cause:** the session blob was designed for a restore contract that only the queue/index/shuffle/repeat half of it implements.
- **Trigger conditions:** always (dead data).
- **User impact:** `session.last_volume` duplicates `audio.volume` and can drift from it without any consequence, which makes the session table misleading for anyone reading it to answer "what is restored?". `general.start_minimized` gives the false impression that the app can start hidden.
- **Evidence:**
  ```python
  # core/session.py:57-63
  self.settings.set("session", "last_volume", volume)
  ```
  ```python
  # core/session.py:74-76 — returned …
  "volume": self.settings.get("session", "last_volume", 70),
  ```
  ```python
  # main.py:315-317 — … and never read
  session_data = app_core.session.restore_session()
  queue = session_data.get("queue")
  session_position_sec = float(session_data.get("position") or 0.0)
  ```
  ```python
  # core/settings.py:60-70
  "general": {
      ...
      "minimize_to_tray": True,
      "start_minimized": False,      # <-- no reader anywhere
      ...
  },
  ```
  Grep proof: `grep -rn "start_minimized" --include=*.py --include=*.js .` → 1 hit, `core/settings.py:64`. `grep -rn "last_volume" --include=*.py .` → `core/session.py` only.
- **Reproduction / verification:** the two greps above.
- **Suggested fix:** either delete `session.last_volume` and `general.start_minimized`, or implement them (apply the restored volume on start — which is what F-WX-12-2 needs anyway — and honour `start_minimized` by hiding the window on the first `shown` event).
- **Fix side effects:** removing a `settings` key changes the settings-table shape; the loader preserves unknown keys, so removal is safe for existing profiles. Implementing `start_minimized` needs the tray to work (F-WX-12-1), otherwise the app would start with no visible window and no way to reach it.
- **Discovered by:** A

---

#### F-WX-12-8  [P3] — Discord Rich Presence is told the restored track is "playing" before any playback starts, and stays that way

- **File:** `core/api.py:1195-1242` (`_on_track_changed`), `main.py:324-325`, `main.py:391-392`, `core/services/discord_rpc.py:87-162`
- **Confirmed:** yes
- **Description:** `_on_track_changed` unconditionally calls `discord_rpc.update_presence(..., is_playing=True, current_pos_sec=0)`. On startup that hook fires twice for the restored track — once at `main.py:325` (before the window exists) and once at `main.py:392` (inside `on_loaded`) — long before anything is playing. The presence is only corrected when the frontend reports a real state (`report_state` → `core/api.py:1355-1373`), and the frontend sends no state until the user actually presses play. With the default `audio.autoplay = False` the restored track is therefore shown in Discord as *playing*, with a running timestamp, indefinitely.
- **Cause:** the track-changed hook conflates "this is the current track" with "this is playing".
- **Trigger conditions:** every restart with a saved session and the Discord RPC enabled (`app.discord_rpc_enabled` defaults to `True`) and Discord running.
- **User impact:** the Discord status shows the last-played track as actively playing (with a progress bar that advances from 0) while the app is idle — the user's friends see a false "now playing".
- **Evidence:**
  ```python
  # core/api.py:1228-1236
  try:
      if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
          self._core.discord_rpc.update_presence(
              track_title=track_copy.get("title", ""),
              track_artist=track_copy.get("artist", ""),
              is_playing=True,
              duration_sec=track_copy.get("duration", 0),
              current_pos_sec=0)
  ```
  ```python
  # core/services/discord_rpc.py:124-147
  if is_playing:
      payload = {... "small_image": "play", "small_text": "Воспроизводится", ...}
      ...
      self.rpc.update(**payload)
  ```
  ```python
  # main.py:391-392 — the second, post-window call
  if app_core.engine.queue.current_track:
      app_core.engine._on_track_changed(app_core.engine.queue.current_track)
  ```
- **Reproduction / verification:**
  1. Enable the Discord RPC, play a track, quit the app.
  2. Relaunch with Discord running and `audio.autoplay` off.
  3. Observe the Discord status: the restored track is listed as playing with a live progress timestamp, and it stays that way until the user presses play or pause.
  4. Static: `grep -n "is_playing=True" core/api.py` → 1 hit (`_on_track_changed`); `report_state` is the only other writer of the presence and is only called by the frontend on a real play/pause.
- **Suggested fix:** pass the real playback state into `_on_track_changed` (or set `is_playing=False` / publish a "paused" presence) for the startup restore, and let `report_state` flip it to "playing" when playback actually starts.
- **Fix side effects:** the presence would briefly show "paused" for a restored track before the autoplay kicks in; that is the truthful state and is what the user expects.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found **correct** (no finding raised):

1. **Minimise does not stop the music.** The `<audio>` element is untouched by the visibility path — `player.js::syncPlayerVisibility` (`:1489-1500`) only cancels/resumes the progress rAF; no `pause()` is issued on minimise, hide or mini-mode. The playback continues while the window is minimised or hidden, as it should.
2. **The background rAF loops are all stopped when the window is hidden.** Three independent loops are guarded and all three listen to **both** `document.visibilitychange` and the backend's `nedotify:window_visibility_changed`:
   - progress bar — `player.js:1489-1500` + `isPlayerUiHidden()` (`:1359-1361`);
   - visualizer — `visualizer.js:98-108` (`documentVisible`) + `syncVisualizerAnimation` (`:242-249`);
   - particles — `particles.js:47-65` (`isWindowHidden()`, `syncParticleAnimation`) and the per-frame guard at `particles.js:475`.
   The backend side is correct too: `set_window` wires `minimized/restored/maximized/shown` to `_on_minimized`/`_on_restored` (`core/api.py:521-527`), which emit `window_visibility` and the frontend toggles the `window-hidden` class (`events.js:89-96`) — so the loops stop even when `document.hidden` is not set by the browser (pywebview's `window.hide()` path).
3. **The `timeupdate` handler does not cause DOM churn while hidden.** The per-tick `nedotify:position_changed` dispatch (`player.js:609`) reaches `lyrics.js::updateLyricsPosition`, which is written to do a binary search and **zero** layout work unless the active line index actually changes (`lyrics.js:1068-1100`). The 5 s `report_position` call is the correct behaviour for the listening statistics and is deliberately *not* paused.
4. **The mini-player CSS class and the native geometry are both driven and both reversible.** `main.js:175-205` toggles `body.mini-player-active` optimistically and `core/api.py:792-859` saves the pre-mini geometry (`_native_window_geometry`), restores the exact size, the `on_top` flag, the rounded corners and `MinimumSize` on exit. The size restore is exact (`_exit_mini_mode` no longer clamps to 800/600, as the comment at `:833-834` records) and the *position* restore is in the right coordinate space (see F-WX-12-6 for the size/position asymmetry).
5. **The mini-player position preference is persisted and restored.** `player.mp_pos` is written by `settings.js:2702` (`saveSetting('mp_pos', pos, 'player')`) and re-applied on boot by `applySettingsFromBackend` → `applyMpPos` → `api.set_mini_player_position` (`settings.js:923`, `:2569-2578`), and `set_mini_player_position` stores it in `_saved_mini_pos` **before** the early-return guard (`core/api.py:885-890`), so the preference survives the "mini player inactive" case and the next entry applies it.
6. **The queue really is restored to the queue (not just to the settings).** `main.py:318-321` restores the tracks, the index, shuffle and repeat into `engine.queue` (`audio/queue.py::set_tracks`), and the frontend reads them back from the backend with `get_queue()` when the drawer opens (`queue.js:76-85`). The shuffle flag is assigned **after** `set_tracks()`, so the restored queue is not re-shuffled by `set_tracks()`'s own shuffle branch (`queue.py:126-132`) — correct.
7. **The persisted queue is bounded and the index is re-based.** `session.py:9, 50-55` caps the queue at 200 entries and adjusts `queue_index` by the number of dropped head entries. `restore_session()` also nulls `file_path` and zeroes `resolved_at` for the cloud providers so a stale stream URL cannot survive into the player (`session.py:82-88`).
8. **Mute is restored correctly and is independent of the volume.** `toggle_mute()` persists `audio.muted` and returns the new state (`core/api.py:1964-1991`); `is_muted()` reads it back (`core/api.py:1993-2002`); the frontend applies it at `initPlayer()` (`player.js:1216-1219`) and also reacts to the `mute_changed` event (`events.js:393`). Mute being a separate flag from the volume means the pre-mute level is preserved by construction — this is the one persistence path in the scenario that works end to end.
9. **The theme is restored from the DB and the palette wins over the mode.** `settings.js:591` writes the palette to `theme.theme`; `applySettingsFromBackend` (`settings.js:724-746`) reads `settings.theme?.theme` first and only falls back to `theme_mode` when no palette is stored — the exact ordering the comment describes.
10. **`general.minimize_to_tray` is honoured by `close()`** — the *decision* logic is right (`core/api.py:922-926`); it is only the tray's existence that is broken (F-WX-12-1).
11. **The mini-player drag/resize guards behave.** `window-resize.js:10` refuses to start a native resize while `mini-player-active`, and `player.js:1102-1108` routes the mini-player drag through `begin_window_drag` (native `WM_NCLBUTTONDOWN`), not through a JS drag.

### 4. Coverage gaps

- **No live application run.** Per the ground rules the real app was never started (it would disturb `~/.nedotify/`, open network sessions and drive real provider accounts). Every native/DPI/WebView2 claim above is derived from the pinned sources in `.venv_win` (pywebview 5.4, pystray 0.19.5) plus the repo source, and is labelled hypothesis where it needs a real window.
- **F-WX-12-3 (the restore-event race) could not be settled.** The ordering is proven from the sources, but whether `requestIdleCallback` wins the race on a given machine needs a live run with DevTools (`NEDOTIFY_DEVTOOLS=1`) watching for `Python Event: track_changed` versus `[Init] Events loaded`.
- **F-WX-12-6 (the DPI displacement) was not measured** — it needs a scaled display (125 %/150 %) and the mini-player cycle.
- **The exact HTTP/WebView2 traffic of the restore was not traced at runtime** (no bridge-level tracing was performed).
- **`audio/queue.py` and `audio/engine.py` were read only where the restore touches them** (`set_tracks`, `current_track`, `_current_index`, `_last_reported_position`); their own playback semantics belong to WN-17 / WX-01 / WX-10 and were not re-reviewed here.
- **`core/listening.py`, `core/database.py` and `services/discord_rpc.py` were read only as far as the restore path needs them**; the listening-telemetry correctness is WX-04's scope.
- **The `js/settings.js` (3111 L) and `js/player.js` (2489 L) files were read in the regions relevant to this scenario only** (volume/mute/theme/mini-player/efficiency/visibility). The rest of the settings and player surfaces belong to WX-03 / WN-29 / WN-30 and were not re-reviewed.
- **The `ui/web_new_v2/css/**` tree was read only for the `mini-player-active` / `window-hidden` rules** (`css/components/base.css:2550-2629`); the rest of the styling is WN-33's scope.
- **`tools/bench` and `tools/visual_guard` were not run**; in particular `tools/bench/build_hotspots.py` already flags a particle-listener leak (`initParticles()` re-creating listeners) that this scenario touches, but that was not independently verified here.
