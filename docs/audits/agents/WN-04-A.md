## AREA WN-04 — Bridge window management: mini-player, resize, drag, snap, geometry, maximize — ROLE A

### 1. Scope reviewed

Files opened (physical line ranges actually read):

- `core/api.py` L1–200 (imports, `_is_ssrf_safe_url`, window size constants), L280–420 (`AppApi.__init__`, bridge error-logging wrapper, `cleanup`), L419–520 (`_offline_bridge_result`), **L490–1189 (the whole WN-04 band: `set_window` … `_emit`)**, L2720–2779 (`set_snap_button_rect`).
- `core/snap_layouts.py` L1–357 (whole file: `_configure_user32`, `_def_window_proc`, `_call_window_proc`, `_dpi_scale`, `SnapLayouts`).
- `main.py` L1–584 (whole file: `main()`, `on_loaded`, `on_closed`, `_install_routes`, `_startup_watchdog`, window creation).
- `core/tray.py` L1–194 (whole file — callee of `set_window`'s dead tail and of `close()`).
- `core/app.py` L505–584 (`AppCore.cleanup`).
- `core/settings.py` L63 (`general.minimize_to_tray` default).
- pywebview runtime (`.venv_win/Lib/site-packages/webview/`): `window.py` L30–149, L217–224, L300–429; `platforms/winforms.py` L157–276, L277–409, L490–569, L850–929; `platforms/edgechromium.py` L205–244; `event.py` L1–93; `util.py` L234–327. Used to pin the *actual* semantics of `Window.move/resize/hwnd/native`, `BrowserForm.scale_factor`, `Event.set` threading and `js_bridge_call` threading.
- Frontend callers (contract check only): `ui/web_new_v2/js/main.js` L160–239, L440–559; `ui/web_new_v2/js/player.js` L1060–1129; `ui/web_new_v2/js/window-resize.js` L1–22; `ui/web_new_v2/js/settings.js` L2562–2581.
- Existing tests: `tests/test_window_maximize.py`, `tests/test_window_resize_api.py`, `tests/test_window_visibility.py` (read to see what is already pinned).

Callees traced into other areas (defect owned there, not reported as WN-04 findings unless the *caller's* misuse is the defect):

- `core/tray.py::TrayIcon.start/stop/update_state` — WN-16. The defect is **not** in the tray itself; it is that WN-04's `set_window` never calls `start()` (see F-WN-04-1).
- `core/settings.py` (`general.minimize_to_tray`) — WN-14. The setting is read correctly; it is the consumer that is dead (F-WN-04-1).
- `core/api.py::_is_ssrf_safe_url` (L161–195) — WN-03. Verified safe for `open_url`/`open_external_url` (see §3).
- `core/api.py::_emit` — nominally WN-03 by topic, but physically inside WN-04's band (L1122–1159); reviewed here, no defect found beyond a thread-per-emit note in §3.
- pywebview internals (`webview/window.py`, `webview/platforms/winforms.py`) — third-party; used as the contract reference for "logical vs physical pixels".

### 2. Findings

#### F-WN-04-1  [P1] — `set_window`'s tail became unreachable dead code: the tray is never started, so "minimize to tray" and the custom window icon are dead

- **File:** `core/api.py:542-597` (dead block at 574–597), `core/api.py:924-930` (`close()`), `core/api.py:574-575` (`self._tray.start()`)
- **Confirmed:** yes (AST-verified)
- **Description:** `set_window()` ends at L540. The block that used to follow it — start the system tray, then set the window icon — is now the *body* of `_install_snap_layouts`, positioned after that function's unconditional `return False` at L572. It can never execute.
- **Cause:** A merge/edit moved the tail of `set_window` into `_install_snap_layouts` without removing the early `return`. AST dump of `_install_snap_layouts` (lines 542–597) shows the statement order `For(552-570) → Expr(571) → Return(572) → If(574-575) → Try(577-597)`: everything after the `Return` is unreachable.
- **Trigger conditions:** Every application start. `TrayIcon.start()` has **no other caller in the whole repository** (`Select-String -Path core\*.py -Pattern '_tray\.start'` → only `core/api.py:575`).
- **User impact:** (a) No NeDotify icon in the notification area; the tray menu (play/pause, next, exit) is unavailable. (b) `close()` computes `tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)`; `TrayIcon.icon` stays `None` because `start()` never ran → the `minimize_to_tray` branch is never taken → **the window is destroyed instead of hidden to the tray, even though `general.minimize_to_tray` defaults to `True`** (`core/settings.py:63`). The user clicks ✕ and the app exits, contradicting the setting. (c) The custom `icon.ico` is never applied to the form.
- **Evidence:**
  ```python
  # core/api.py:552-597
  for _ in range(attempts):
      ...
  logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
  return False                      # <-- L572: everything below is unreachable

  if getattr(self, "_tray", None):  # <-- L574: dead code
      self._tray.start()            # <-- L575: the ONLY tray.start() in the repo
      ...
      def _set_icon(): ...
      threading.Thread(target=_set_icon, daemon=True).start()
  ```
  ```python
  # core/api.py:922-930
  minimize_to_tray = bool(self._core.settings.get("general", "minimize_to_tray", True))
  tray_mgr = getattr(self, "_tray", None) or getattr(self._core, "tray", None)
  tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)
  if minimize_to_tray and tray_available:
      self._window.hide(); self._on_minimized(); return {...}
  ```
- **Reproduction / verification:**
  ```
  & ".venv_win\Scripts\python.exe" -c "import ast;t=ast.parse(open('core/api.py',encoding='utf-8').read());[print(n.name,n.lineno,n.end_lineno,[ (s.lineno,s.end_lineno,type(s).__name__) for s in n.body]) for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name=='_install_snap_layouts']"
  ```
  → `_install_snap_layouts 542 597 [(543,543,'Expr'),(544,545,'If'),(546,550,'Try'),(552,570,'For'),(571,571,'Expr'),(572,572,'Return'),(574,575,'If'),(577,597,'Try')]` → the `Return` at 572 is followed by two more statements.
  Manual: start the app → no tray icon; press the window's ✕ → the process exits instead of hiding to the tray.
- **Suggested fix:** Move the `if getattr(self, "_tray", None): self._tray.start()` block and the `_set_icon` helper back into `set_window()` (or call `self._tray.start()` from `set_window` right after the snap-layouts thread is spawned).
- **Fix side effects:** The tray thread starts → `TrayIcon.update_state()` (called at `core/api.py:1241` and `:1374`) becomes effective and now mutates the tray menu ~1×/s. The `_set_icon` helper needs `clr` (pythonnet); it is already wrapped in `try/except` and guarded by `PYTEST_CURRENT_TEST`, so it stays best-effort. `close()` will then take the hide-to-tray branch, which changes the meaning of the ✕ button — the frontend has a bridge-free `/__aura_close` fallback for that, but the ✕ button (`ui/web_new_v2/js/main.js:493-504`) calls `close_window()` first and only falls back to the HTTP route when the bridge is missing, so a hidden-to-tray window must still be reachable from the tray (it will be, once the tray starts).
- **Discovered by:** A

#### F-WN-04-2  [P1] — `_get_scale_factor()` always returns 1.0, so the mini player is positioned outside the screen on any display scaled above 100 %

- **File:** `core/api.py:629-648` (`_get_scale_factor`), `core/api.py:650-696` (`_logical_workarea`), `core/api.py:698-719` (`_saved_pos_coords`), `core/api.py:897-908` (`_apply_window_pos`), `core/api.py:805-816` (`_apply_mini_geometry`)
- **Confirmed:** yes
- **Description:** `_logical_workarea()` is documented to return the work area "in LOGICAL pixels - matching what `Window.move()` expects", but it never converts: `_get_scale_factor()` returns `1.0` unconditionally, so the physical `rcWork` rectangle is returned unchanged. `Window.move()` in pywebview's WinForms backend **does** multiply its arguments by the device scale factor before `SetWindowPos`, so the position is scaled twice.
- **Cause:** `_get_scale_factor()` reads `getattr(native, "_scale", None)`. pywebview's WinForms `BrowserForm` publishes the factor as the **public** attribute `scale_factor` (`webview/platforms/winforms.py:178`: `self.scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100 if is_chromium else 1`). There is **no `_scale` attribute anywhere in pywebview** (verified by grep over `site-packages/webview/*.py` and `platforms/*.py`), and .NET `Form` has no `_scale` member. Therefore `scale` is `None`, `isinstance(scale, (int, float))` is False and the method returns `1.0` on every call.
- **Trigger conditions:** Any display whose scale factor ≠ 100 % (i.e. most laptops). Also mixed-DPI: pywebview's factor comes from `GetScaleFactorForDevice(0)` = the **primary** monitor, so a secondary monitor with a different DPI gets the wrong factor even if the app's own scale lookup were fixed to use the device factor.
- **User impact:** Entering the mini player moves the window to a wrong position. Example: 1920×1080 physical work area, scale 1.5 → `_logical_workarea()` returns `(0, 0, 1920, 1040)`; `_saved_pos_coords('bottom-right', 380, 110)` returns `(1520, 910)`; `move(1520, 910)` → pywebview scales to `(2280, 1365)` → **the mini player is off-screen to the right and below**, with the full UI hidden. The user sees the main window vanish and cannot get the mini player back.
- **Evidence:**
  ```python
  # core/api.py:636-645
  native = getattr(self._window, "native", None)
  scale = getattr(native, "_scale", None)      # <-- attribute does not exist
  if callable(scale): ...
  val = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
  return val                                     # <-- always 1.0
  ```
  ```python
  # webview/platforms/winforms.py:512-528 (third-party contract)
  def move(self, x, y):
      if self.scale_factor != 1:
          x_modified = x * self.scale_factor
          y_modified = y * self.scale_factor
          windll.user32.SetWindowPos(self.Handle.ToInt32(), None, int(x_modified), int(y_modified), ...)
  ```
  Note the asymmetry inside pywebview itself: `resize()` (`winforms.py:500-510`) passes width/height to `SetWindowPos` **without** scaling, while `move()` scales. The app mixes the two spaces.
- **Reproduction / verification:** Set the display scale to 125/150 % (Windows → Settings → System → Display), start the app, press the mini-player button. Compare the resulting window position with the taskbar corner. Static check: `Select-String -Path .venv_win\Lib\site-packages\webview\*.py,.venv_win\Lib\site-packages\webview\platforms\*.py -Pattern '_scale\b'` → no matches (only `scale_factor`).
- **Suggested fix:** Read the real scale: `getattr(native, "scale_factor", None)` and prefer the per-window DPI (`GetDpiForWindow(hwnd)/96`, already used in `core/snap_layouts.py:122-128`) so a window dragged to a differently-scaled monitor re-reads it; divide the work area by that value.
- **Fix side effects:** With the factor applied, `_logical_workarea()` returns logical values and `move()` scales them back → positions land inside the work area. But `_exit_mini_mode` (F-WN-04-3) then becomes *more* wrong, because it feeds *physical* values into the same logical API — both must be fixed together. Also the mini window will physically be 380×110 px (pywebview's `resize` is unscaled) → the mini player will look smaller than its CSS size at 150 %; that is pywebview's behaviour and should be compensated by scaling `MINI_WINDOW_SIZE`.
- **Discovered by:** A

#### F-WN-04-3  [P2] — `_exit_mini_mode` restores the window position in physical pixels through pywebview's logical-pixel `move()`, so the main window reappears at the wrong offset

- **File:** `core/api.py:749-771` (`_native_window_geometry`), `core/api.py:826-859` (`_exit_mini_mode` / `_restore`)
- **Confirmed:** yes
- **Description:** `_native_window_geometry()` reads `GetWindowRect` → **physical** pixels, and stores them in `_saved_main_geometry`. On exit, `_restore()` calls `target_win.resize(w, h)` (pywebview does *not* scale → the size is restored correctly) but `target_win.move(int(gx), int(gy))` (pywebview *does* scale → the position is multiplied by the device scale factor a second time).
- **Cause:** The saved geometry and the `move()` contract use different coordinate spaces; nothing converts between them.
- **Trigger conditions:** Leaving mini mode on a scaled display (the same condition as F-WN-04-2), or any device with scale ≠ 1.
- **User impact:** The main player reappears 1.5× further from the screen origin than the user left it (e.g. from x=100 to x=150, from x=1900 to x=2850 → off-screen). Combined with F-WN-04-2 the mini→main round trip does not preserve the window position at all.
- **Evidence:**
  ```python
  # core/api.py:764-768
  if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
      raise ctypes.WinError(ctypes.get_last_error())
  return (int(rect.right - rect.left), int(rect.bottom - rect.top),
          int(rect.left), int(rect.top))          # physical pixels
  ```
  ```python
  # core/api.py:847-848
  if gx is not None and gy is not None and hasattr(target_win, 'move'):
      target_win.move(int(gx), int(gy))          # move() expects LOGICAL pixels
  ```
- **Reproduction / verification:** 150 % display; drag the main window to the right edge; switch to the mini player and back; observe the window's position/size. Static: compare `core/api.py:767-768` (GetWindowRect → physical) with `webview/platforms/winforms.py:516-519` (move() multiplies by `scale_factor`).
- **Suggested fix:** Convert the saved rectangle to logical pixels before storing it (divide by the per-window DPI factor), or bypass pywebview and use `SetWindowPos` directly with physical coordinates.
- **Fix side effects:** Must be done together with F-WN-04-2, otherwise the two conversions cancel out in one direction and double in the other.
- **Discovered by:** A

#### F-WN-04-4  [P2] — Mini-player enter/exit operations are unordered: a fast double toggle can leave a 380×110 window showing the full player UI

- **File:** `core/api.py:773-790` (`toggle_mini_player`), `core/api.py:792-824` (`_enter_mini_mode`), `core/api.py:826-859` (`_exit_mini_mode`), `core/api.py:721-735` (`_deferred_window_op`)
- **Confirmed:** yes
- **Description:** Each toggle schedules an independent deferred operation with the same delay (0.25 s). `_deferred_window_op` starts a **new thread per call**; the two threads wake at essentially the same instant and race for `self._window_op_lock`. The lock serialises them but does **not** order them, and nothing cancels a superseded operation.
- **Cause:** No generation counter / cancellation token on the pending window operations, and no dedicated single-consumer queue for window ops.
- **Trigger conditions:** Toggling mini-player on and off within ~0.25 s (a double-click on the mini button, a fast keyboard shortcut, or the mini overlay's expand button pressed right after entering). The frontend (`ui/web_new_v2/js/main.js:175-205`) applies the CSS class optimistically and does not serialise calls either.
- **User impact:** The window ends up at the mini geometry (380×110, `on_top=True`, rounded corners) while `_is_mini_active` is `False` and the frontend shows the **full** player UI inside a 380×110 window. The user sees a tiny, unusable window and cannot restore it (the expand button lives inside the mini overlay, which is not rendered).
- **Evidence:**
  ```python
  # core/api.py:728-735
  def _run():
      time.sleep(delay)
      try:
          with self._window_op_lock:
              fn()
          ...
  threading.Thread(target=_run, daemon=True).start()
  ```
  ```python
  # core/api.py:776-781
  self._is_mini_active = enable
  if enable:  self._enter_mini_mode()
  else:      self._exit_mini_mode()
  ```
  (`_enter_mini_mode` → `_deferred_window_op(0.25, ...)` at L820, `_exit_mini_mode` → `_deferred_window_op(0.25, ...)` at L855.)
- **Reproduction / verification:** From the DevTools console (`NEDOTIFY_DEVTOOLS=1`), run `pywebview.api.toggle_mini_player(true); pywebview.api.toggle_mini_player(false)` repeatedly with < 250 ms between the calls; observe `GetWindowRect` of the form vs `api._is_mini_active`. The two threads' relative order is scheduler-dependent, so the bug is intermittent — instrument `_deferred_window_op` with a print of the op name and the timestamp.
- **Suggested fix:** Add a monotonically increasing window-op generation (e.g. `self._window_op_seq += 1`) captured by each deferred op; the op aborts if its generation is stale. Alternatively run window ops through a single-consumer queue thread so they are strictly ordered.
- **Fix side effects:** A stale-op check must also be applied to `_change_maximized_state` (which has the same 0.03 s deferral) so a pending maximize does not fight a pending mini-enter.
- **Discovered by:** A

#### F-WN-04-5  [P2] — `_change_maximized_state` restores a stale `_last_geometry`, so the window jumps back to an old position/size

- **File:** `core/api.py:1053-1095` (`_change_maximized_state`), `core/api.py:617-627` (`_on_window_resized`, the only other writer of `_is_maximized`)
- **Confirmed:** yes
- **Description:** `_last_geometry` is written **only** inside `change()` on the maximise path and is never refreshed or invalidated. A maximise that happens *natively* (Win+Up, the Snap flyout, the OS caption) updates `_is_maximized` (through `_on_window_resized`) but leaves `_last_geometry` pointing at an old rectangle. The next restore then forces the window back to that old rectangle.
- **Cause:** The "previous normal rect" is captured on one code path only; the other path into the maximised state (native) is not mirrored.
- **Trigger conditions:** maximise via the bridge button → restore → move the window → maximise natively (Win+Up / Snap) → click the maximise button again (which now restores, because `is_max` is True → `requested = False`).
- **User impact:** The window jumps to a stale position and size, ignoring where the user actually put it.
- **Evidence:**
  ```python
  # core/api.py:1070-1080
  if requested:
      if not is_max:
          bounds = native.Bounds
          self._last_geometry = (bounds.X, bounds.Y, bounds.Width, bounds.Height)
      ...
  else:
      native.WindowState = FormWindowState.Normal
      geometry = getattr(self, '_last_geometry', None)
      if geometry:
          native.Bounds = Rectangle(*map(int, geometry))   # <-- may be a very old rect
  ```
  `_on_window_resized` (L617-627) sets `self._is_maximized` but never `_last_geometry`.
- **Reproduction / verification:** Follow the trigger sequence above and compare `native.Bounds` before/after the restore; the rectangle equals the one captured at the *first* maximise, not the current one.
- **Suggested fix:** Capture the normal rectangle in the transition handler itself (whenever `WindowState` flips to `Maximized`, e.g. inside `_on_window_resized`), and clear `_last_geometry` after a restore.
- **Fix side effects:** `_on_window_resized` runs on a pywebview event thread (`webview/event.py:59` spawns a thread per `Event.set`), so it must read `native.Bounds` on the UI thread (i.e. inside the existing `_on_window_ui_thread` callback) — the same discipline `_change_maximized_state` already uses.
- **Discovered by:** A

#### F-WN-04-6  [P2] — Native resize silently does nothing (yet reports success) when the Snap Layouts subclass is not installed, because only that subclass adds `WS_THICKFRAME`

- **File:** `core/api.py:992-1030` (`begin_window_resize`), `core/api.py:542-572` (`_install_snap_layouts`), `core/snap_layouts.py:150-212` (`install`, which adds `WS_THICKFRAME|WS_MAXIMIZEBOX|WS_SYSMENU` at L185), `ui/web_new_v2/js/window-resize.js:9-18`
- **Confirmed:** code path yes; the "Windows refuses to size a window without WS_THICKFRAME" part is a strong hypothesis (documented Win32 behaviour, not executed here)
- **Description:** The frameless form has no native frame, so the only way to size it is the CSS overlay of 8 handles (`ui/web_new_v2/js/window-resize.js`), which calls `begin_window_resize('se')` → `WM_NCLBUTTONDOWN` + `SC_SIZE`. That sizing loop requires `WS_THICKFRAME`, which is added **exclusively** by `SnapLayouts.install()` (see the module's own comment: *"The OS gets resize/snap styles"*). If the subclass was never installed — the HWND was not found within 20 × 0.25 s, `SetWindowLongPtr` failed, or the module could not be imported — `begin_window_resize` still returns `{'success': True}` and the window does not move.
- **Cause:** The bridge reports the *dispatch* of the native message, not the *outcome*; there is no check that the window actually carries the required style, and no fallback when the style is missing.
- **Trigger conditions:** Late HWND creation (slow WebView2 start), a `SetWindowLongPtr` failure, an import failure of `core.snap_layouts`, or a non-Windows-11/32-bit Python (see F-WN-04-11).
- **User impact:** The window cannot be resized at all: the 8 CSS handles do nothing, there is no native frame, and the user gets no error (the JS only shows a toast when the *promise rejects*, and it resolves successfully).
- **Evidence:**
  ```python
  # core/snap_layouts.py:181-186
  # Install WM_NCCALCSIZE BEFORE enabling native sizing. ...
  # The OS gets resize/snap styles; our entire window remains client content, without native buttons.
  user32.SetWindowLongW(self.hwnd, GWL_STYLE, old_style | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU)
  ```
  ```python
  # core/api.py:1018-1027
  def start_sizing():
      try:
          user32.ReleaseCapture()
          user32.SendMessageW(hwnd, 0x00A1, edges[direction], ctypes.c_ssize_t(ctypes.c_int32(packed).value))
      except Exception: ...
  self._on_window_ui_thread(self._window, start_sizing)
  return {'success': True}        # <-- success is reported before the outcome is known
  ```
- **Reproduction / verification:** Force the subclass to fail (e.g. run with `core/snap_layouts.py` temporarily renamed, or block `FindWindowW` so the retry loop gives up) and drag a resize handle: the cursor changes to the resize cursor only if the hit-test subclass is installed; otherwise nothing happens while the bridge call resolves with `success: True`. Check `~/.nedotify/logs/app.log` for `"Snap Layouts skipped: no window handle after 5.0s"` or `"SnapLayouts: not installed"`.
- **Suggested fix:** Verify the required style before dispatching (`GetWindowLongW(hwnd, GWL_STYLE) & WS_THICKFRAME`) and return `{'success': False, 'error': ...}` when it is missing; alternatively install the resize styles independently of the Snap subclass.
- **Fix side effects:** Returning an error makes the frontend show the toast (`window-resize.js:16`), which is the intended UX. Splitting the style install from the subclass install would let resize work even when the hit-test subclass fails.
- **Discovered by:** A

#### F-WN-04-7  [P2] — The Snap Layouts install gives up after 5 s and the maximize-button rectangle reported by the frontend is lost, so the Win11 Snap flyout never appears

- **File:** `core/api.py:542-572` (`_install_snap_layouts`), `core/api.py:2733-2748` (`set_snap_button_rect`), `ui/web_new_v2/js/main.js:455-492` (frontend retry logic), `tests/test_window_resize_api.py:78-80`
- **Confirmed:** yes (the give-up and the lost rectangle are directly readable in the code)
- **Description:** `set_snap_button_rect` is the *only* way the frontend tells the backend where the maximise button is, and it fails while `self._snap_layouts` is `None`. The install loop gives up permanently after 20 × 0.25 s = 5 s. The frontend retries at most 12 × 500 ms = 6 s. When the install lands after the frontend's budget is exhausted, the rectangle is **never re-sent** (the frontend only re-reports on window resize or a `ResizeObserver` callback), so `SnapLayouts._btn_rect` stays `None` and `WM_NCHITTEST` never answers `HTMAXBUTTON`.
- **Cause:** The two sides use independent, unsynchronised timers, and the bridge keeps no copy of the last reported rectangle.
- **Trigger conditions:** A slow WebView2 start (the HWND appears after ~1-2 s is common; the app's own watchdog allows 35 s), a late `FindWindowW` hit, or any hiccup in the install.
- **User impact:** The Windows 11 Snap Layouts flyout never appears when hovering the maximise button; the user only gets maximise/restore, which is the feature's whole point.
- **Evidence:**
  ```python
  # core/api.py:552-572
  for _ in range(attempts):        # attempts = 20
      hwnd = self._get_hwnd()
      if hwnd: ... return True/False
      time.sleep(delay)            # delay = 0.25  -> 5 s budget
  logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
  return False
  ```
  ```python
  # core/api.py:2740-2742
  snap = getattr(self, "_snap_layouts", None)
  if snap is None:
      return {"success": False}    # <-- rectangle dropped, never replayed
  ```
  ```javascript
  // ui/web_new_v2/js/main.js:473-476
  if (snapBridgeRetries++ < 12) { clearTimeout(snapRetryTimer); snapRetryTimer = setTimeout(reportSnapButton, 500); }
  ```
- **Reproduction / verification:** Start the app with a cold WebView2 profile and watch `~/.nedotify/logs/app.log` for `"Snap Layouts skipped: no window handle after 5.0s"`; in that case hovering `#btn-maximize` shows no layout flyout. Even when the install succeeds late, the rect is lost unless a resize happens afterwards.
- **Suggested fix:** Cache the last reported rectangle on the API (`self._snap_btn_rect`) and apply it in `_install_snap_layouts` right after `snap.install()` succeeds; alternatively let the frontend re-report when `set_snap_button_rect` returns `success: False` (it already retries, but the budget is too small and the rect is not replayed after a *late* success).
- **Fix side effects:** Minimal — storing the rect and applying it on install closes the race. Note `tests/test_window_resize_api.py:78-80` is named *"test_snap_button_bridge_can_retry_until_native_subclass_is_ready"* but asserts the opposite (`{'success': False}`); that test pins the current behaviour and would need to be updated together with the fix.
- **Discovered by:** A

#### F-WN-04-8  [P3] — `begin_window_drag` calls `ReleaseCapture()` on the bridge thread, where it is a documented no-op

- **File:** `core/api.py:959-990` (`begin_window_drag`), `core/api.py:1018-1026` (`begin_window_resize` → `start_sizing`)
- **Confirmed:** yes (Win32 semantics: *ReleaseCapture releases the mouse capture from a window in the current thread only*)
- **Description:** The drag path calls `user32.ReleaseCapture()` directly on the pywebview bridge thread (L978). The capture at that moment belongs to the UI thread (WebView2/Chromium captured the pointer during `mousedown`), so the call does nothing. The resize path does it correctly — inside `_on_window_ui_thread`, i.e. on the UI thread (L1022).
- **Cause:** Inconsistent threading between two sibling code paths that perform the same "let Windows own the pointer" dance.
- **Trigger conditions:** Every mini-player drag.
- **User impact:** Low — the system's own `SC_MOVE` loop takes the capture, so the drag still works; but the intended "release the WebView2 capture first" step never executes, and the two paths behave differently (the resize path releases a real capture, the drag path does not).
- **Evidence:**
  ```python
  # core/api.py:978 (bridge thread)
  user32.ReleaseCapture()
  # core/api.py:986
  user32.SendMessageW(hwnd, 0x00A1, 2, lparam)
  ```
  vs.
  ```python
  # core/api.py:1022 (UI thread, via _on_window_ui_thread)
  user32.ReleaseCapture()
  ```
- **Reproduction / verification:** Instrument: log `GetCapture()` (the window that owns the capture) and `GetCurrentThreadId()` immediately before `ReleaseCapture()` in the drag path; the captured window's thread differs from the calling thread → the release is ineffective.
- **Suggested fix:** Send the whole drag sequence through `_on_window_ui_thread(self._window, ...)` exactly like `begin_window_resize` does.
- **Fix side effects:** The bridge thread would then return before the drag finishes — the JS promise resolves earlier, which is an improvement (today `SendMessageW` blocks the bridge thread for the whole drag, because `WM_NCLBUTTONDOWN` is dispatched synchronously to the UI thread and the modal move loop runs there).
- **Discovered by:** A

#### F-WN-04-9  [P3] — `_get_hwnd()` resolves the window handle by window title and never validates it

- **File:** `core/api.py:1032-1051` (`_get_hwnd`), `core/api.py:663-681` (`_logical_workarea`), `core/api.py:753-768` (`_native_window_geometry`), `core/api.py:861-877` (`_set_native_window_corners`), `core/api.py:963-965` / `core/api.py:1003-1005` (drag/resize)
- **Confirmed:** yes
- **Description:** The first two branches are dead: pywebview's `Window` exposes **neither** `hwnd` **nor** `gui_window` (verified in `.venv_win/Lib/site-packages/webview/window.py`: the only native handle is `window.native.Handle`, where `native` is the WinForms `BrowserForm`). The only working path is `FindWindowW(None, self._window.title)` → i.e. *"the first top-level window whose caption is 'NeDotify'"*. The result is not validated with `IsWindow` and not cached, so every native operation re-runs a top-level window enumeration.
- **Cause:** The handle is derived from a mutable, non-unique caption instead of from the WinForms handle that pywebview already exposes (`self._window.native.Handle.ToInt32()`).
- **Trigger conditions:** (a) The caption is changed (pywebview `set_title`; the app never calls it today, but it is one call away); (b) another process owns a top-level window titled "NeDotify"; (c) the window was destroyed and the HWND value was recycled by the OS.
- **User impact:** Every native capability (drag, resize, snap install, DWM corner rounding, geometry read, work-area read) fails at once with "Window handle is unavailable" — or, in case (b)/(c), acts on a **foreign** window (moving/resizing someone else's window).
- **Evidence:**
  ```python
  # core/api.py:1032-1051
  def _get_hwnd(self):
      if not self._window: return None
      if hasattr(self._window, "hwnd") and self._window.hwnd:      # pywebview Window has no .hwnd
          return self._window.hwnd
      if hasattr(self._window, "gui_window") and hasattr(self._window.gui_window, "Handle"):  # no .gui_window
          return int(self._window.gui_window.Handle)
      if sys.platform == "win32":
          title = getattr(self._window, "title", "NeDotify")
          hwnd = ctypes.windll.user32.FindWindowW(None, title)      # <-- caption lookup
          if hwnd: return hwnd
      return None
  ```
- **Reproduction / verification:** `Select-String -Path .venv_win\Lib\site-packages\webview\window.py -Pattern 'hwnd|gui_window'` → no matches. Runtime proof of the caption dependency: `window.py:217-224` shows `title` is a plain string property; calling `api._window.title = 'x'` from Python makes `FindWindowW(None, 'x')` fail (the WinForms caption is only updated through `set_title`, so the two diverge even earlier).
- **Suggested fix:** Prefer `int(self._window.native.Handle.ToInt32())` (guarded by try/except), cache it per window, and re-validate with `user32.IsWindow(hwnd)` before use.
- **Fix side effects:** `native.Handle` must be read on the UI thread if the handle does not exist yet; caching means the value must be invalidated when the window is recreated.
- **Discovered by:** A

#### F-WN-04-10  [P3] — `shutdown()` is never called: the API keeps a dangling window reference and pending deferred window ops can outlive the window

- **File:** `core/api.py:940-944` (`shutdown`), `core/api.py:446-459` (`cleanup`), `main.py:573-579` (the only teardown path), `core/api.py:721-735` (`_deferred_window_op`)
- **Confirmed:** yes (no caller anywhere: `Select-String -Path **\*.py -Pattern '\.shutdown\(\)'` finds only `core/proxy.py:1288` (its own server) and `core/database.py` (unrelated))
- **Description:** `AppApi.shutdown()` ("Release API-owned resources before the application exits") is never invoked; `main.py` calls `api.cleanup()`, which only stops the tray and the two thread pools. `self._window` therefore keeps pointing at a destroyed window after the form is closed.
- **Cause:** The lifecycle hook was added to the bridge but never wired into `main.py`'s teardown.
- **Trigger conditions:** Every application exit.
- **User impact:** Low, but it is exactly the hook this area is supposed to provide: after the window is gone, `_emit` still calls `evaluate_js` on the dead window (harmless today only because pywebview's `evaluate_js` looks the instance up by uid and returns `None`), and a deferred window op scheduled 0.25 s earlier (mini-enter/exit, maximize) can still run against a destroyed form. `_on_window_ui_thread` then falls back to calling `fn()` inline on its worker thread (see F-WN-04-12) and touches WinForms objects of a disposed form.
- **Evidence:**
  ```python
  # core/api.py:940-944
  def shutdown(self):
      """Release API-owned resources before the application exits."""
      self._window = None
      self._main_window = None
      self._mini_window = None
  ```
  ```python
  # main.py:576-579
  try:
      api.cleanup()
  except Exception: ...
  ```
  (`api.cleanup()` at `core/api.py:446` stops the tray + executors and never clears `_window`.)
- **Reproduction / verification:** `Select-String -Path core\*.py,main.py -Pattern 'shutdown'` → only the definition. Runtime: toggle the mini player and immediately close the app → `~/.nedotify/logs/app.log` may contain `"Deferred window operation failed"` from the op that ran against the destroyed form.
- **Suggested fix:** Call `api.shutdown()` at the start of `main.py`'s teardown (before `app_core.cleanup()`), and cancel/invalidate pending deferred window ops there (e.g. bump the generation counter of F-WN-04-4).
- **Fix side effects:** `_emit` returns early when `_window is None` (`core/api.py:1124`) → events emitted during shutdown are dropped, which is the intended behaviour.
- **Discovered by:** A

#### F-WN-04-11  [P3] — `_configure_user32()` configures all prototypes or none: one missing export disables the pointer-safe `LPARAM` handling the module depends on

- **File:** `core/snap_layouts.py:75-98` (`_configure_user32`), `core/snap_layouts.py:59-72` (the `LPARAM` rationale), `core/snap_layouts.py:115-119` (the import-time call)
- **Confirmed:** yes
- **Description:** The list of (function, argtypes) pairs is materialised **as the `for` statement's iterable**, i.e. *before* the loop body — so `u.GetDpiForWindow` (and every other attribute) is resolved eagerly. On a system where `GetDpiForWindow` does not exist (Windows 8.x, Windows 10 1507/1511) the `AttributeError` escapes the *inner* `try/except` and the **entire** prototype configuration is skipped: `DefWindowProcW`/`CallWindowProcW` keep the default `c_int` argument conversion, which is precisely the failure the module's own comment warns about.
- **Cause:** One `try/except` around the whole batch instead of one per function.
- **Trigger conditions:** A pre-1607 Windows 10 or Windows 8.x host (both EOL). On Windows 11 / Win10 1607+ `GetDpiForWindow` exists and the configuration succeeds.
- **User impact:** On such a host every 64-bit `lparam` raises `OverflowError: int too long to convert` inside the callback ("Exception ignored while calling ctypes callback function") → the frameless window loses its WndProc → the app renders as a black rectangle (the failure mode described at `core/snap_layouts.py:190-192`).
- **Evidence:**
  ```python
  # core/snap_layouts.py:77-98
  u = ctypes.windll.user32
  for fn, argtypes in (                     # <-- tuple evaluated here: AttributeError escapes
      (u.DefWindowProcW, [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, LPARAM]),
      ...
      (u.GetDpiForWindow, [wintypes.HWND]),
      ...):
      try:
          fn.argtypes = argtypes
          ...
      except Exception:
          logger.debug("could not configure %s", ...)
  ```
  ```python
  # core/snap_layouts.py:115-119
  if sys.platform == "win32":
      try:
          _configure_user32()
      except Exception:
          logging.getLogger(__name__).debug("user32 not configured yet", exc_info=True)
  ```
- **Reproduction / verification:** Simulate on any host: `del ctypes.windll.user32.GetDpiForWindow` (monkeypatch) and re-import `core.snap_layouts` → `ctypes.windll.user32.DefWindowProcW.argtypes` stays `None` (default conversion) instead of the pointer-sized list. Confirm the default: `ctypes.windll.user32.DefWindowProcW.argtypes` → `None` before `_configure_user32()` runs.
- **Suggested fix:** Configure each function in its own `try/except` (iterate over names, resolve with `getattr(u, name, None)` and skip missing ones).
- **Fix side effects:** None on supported systems; on EOL systems the module degrades to "no snap layouts" instead of "black window".
- **Discovered by:** A

#### F-WN-04-12  [P3] — `set_mini_player_position` performs the native move on a worker thread and silently accepts an invalid position

- **File:** `core/api.py:879-895` (`set_mini_player_position`), `core/api.py:897-908` (`_apply_window_pos`), `core/api.py:698-719` (`_saved_pos_coords`)
- **Confirmed:** yes (threading path and the `None` handling are directly readable); the WinForms-side consequence is a hypothesis
- **Description:** Two issues in one method. (a) The native move is dispatched through `_deferred_window_op`, whose callable runs on a **worker thread** — unlike every other window operation, which is marshalled to the UI thread via `_on_window_ui_thread` (compare `_apply_mini_geometry` at L805-816, which calls the very same `_apply_window_pos` from the UI thread). pywebview's `BrowserForm.move()` reads `self.Handle` and calls `SetWindowPos` on that worker thread. (b) The `pos` argument is used unvalidated: `if pos: self._saved_mini_pos = pos` skips `None`, but the move is still dispatched with `pos=None`, and `_saved_pos_coords` falls through every branch to its default → **top-right**.
- **Cause:** The position helper is shared by two callers with different threading contracts, and the parameter is not validated before use.
- **Trigger conditions:** (a) always, for the settings-page mini-player position control; (b) any JS caller passing a non-string (e.g. `null` from a stale localStorage value).
- **User impact:** (a) the WinForms `Location` cache and the real window position can drift, and `Control.Handle` is read off-thread (safe only because the handle already exists); (b) the mini player silently jumps to the top-right corner while the stored preference is left unchanged, so the next mini-enter uses the *old* position — the UI and the window disagree.
- **Evidence:**
  ```python
  # core/api.py:885-895
  if pos:
      self._saved_mini_pos = pos
  if not self._is_mini_active and not self._mini_window:
      return
  target_win = self._mini_window or self._window
  if not target_win: return
  self._deferred_window_op(0.1, lambda: self._apply_window_pos(target_win, pos, *MINI_WINDOW_SIZE))
  ```
  ```python
  # core/api.py:698-719  (pos=None falls through to the last line)
  if pos == 'center': return ax + (aw - w) // 2, ay + (ah - h) // 2
  return ax + aw - w - margin, ay + margin          # <-- default = top-right
  ```
- **Reproduction / verification:** `pywebview.api.set_mini_player_position(null)` while the mini player is active → the window moves to the top-right while `api._saved_mini_pos` keeps its old value. Threading: log `threading.current_thread().name` inside `_apply_window_pos` — it is a plain worker thread, whereas the same function called from `_apply_mini_geometry` runs inside the `BeginInvoke` callback on the UI thread.
- **Suggested fix:** Validate `pos` against the known set and return `{'success': False}` for anything else; dispatch the move through `_on_window_ui_thread` like the other window ops.
- **Fix side effects:** The frontend (`ui/web_new_v2/js/settings.js:2569-2578`) passes one of the seven documented values, so a strict allow-list is safe; it ignores the return value, so no frontend change is required.
- **Discovered by:** A

### 3. Clean areas

- **URL validation before handing a URL to the OS (`open_url` / `open_external_url`, `core/api.py:1109-1116`)** — verified safe. `_is_ssrf_safe_url` (`core/api.py:161-195`) rejects everything whose `urlparse(...).scheme` is not `http`/`https`, so `file://`, `javascript:`, `ms-msdt:` (Follina), `data:` and UNC paths never reach `webbrowser.open` → no shell/command injection and no local-file launch. `webbrowser.open` on Windows uses `os.startfile`, which passes the URL as ShellExecute's *file* argument (no argument injection). Residual (informational, not a finding): the guard also blocks legitimate `http://localhost/...` targets, and the DNS resolution in `_dns_resolves_to_public_ip` runs synchronously on the bridge thread — but neither method is currently called from the UI (no JS caller for `open_url`/`open_external_url` in `ui/web_new_v2/`), so the surface is inert today.
- **Mouse-coordinate packing for the native drag/resize messages** — `core/api.py:981-982` and `core/api.py:1015` pack `GetCursorPos` (physical screen pixels, exactly what `WM_NCLBUTTONDOWN` expects) into `LPARAM` as `(y << 16) | (x & 0xFFFF)` with an explicit `c_int32` sign extension, so negative coordinates survive. The existing test (`tests/test_window_resize_api.py:26-31`) pins the signed round-trip. HiDPI-correct.
- **`WM_NCHITTEST` hit-testing in `core/snap_layouts.py:277-333`** — the screen→client conversion, the per-hit-test DPI re-read (`_dpi_scale`, so the grip keeps its physical size on a 4K panel) and the half-open edge intervals (`x < g` rather than `x <= g`, which would steal one content column) are all correct. The maximise-button rectangle is evaluated *before* the "zoomed / not resizable" early return, which is what makes the Snap flyout reachable while maximised.
- **The ctypes callback lifetime in `core/snap_layouts.py`** — the `WNDPROC` object is stored on the instance (`self._proc`, L146/165) and the instance is kept alive by `AppApi._snap_layouts` (L562), so the callback cannot be collected while Windows still points at it; the failure path explicitly keeps the subclass alive ("caller must retain this live subclass", L202) and only drops `self._proc` after the original WndProc has been restored (L194-203). `LONG_PTR` is chosen per-bitness (L113) and `WNDPROC`/`LPARAM` use pointer-sized types (L63-72), which removes the documented `OverflowError` failure mode.
- **`SnapLayouts.install()` rollback** — on any failure after the style was mutated, the original WndProc and the original `GWL_STYLE` are restored (`core/snap_layouts.py:190-212`), so a failed install cannot leave the frameless window as a black rectangle. 32-bit Python is handled: `SetWindowLongPtrW` does not exist there, the `AttributeError` is caught, the style is rolled back and the feature is simply disabled (`core/snap_layouts.py:158`, `LONG_PTR` at L113).
- **`_install_snap_layouts` retry loop** — bounded (20 × 0.25 s = 5 s), runs in a daemon thread (no thread leak at exit), and stops as soon as the HWND appears; it cannot fire after the window is gone because `FindWindowW` then returns 0 and the loop simply expires (the only side effect is a warning log).
- **`_on_window_resized` / `_fit_window_content` re-entrancy** — the resize event is delivered on a pywebview event thread (`webview/event.py:59` spawns a thread per `Event.set`), the handler marshals the actual work to the UI thread through `_on_window_ui_thread`, and the work only touches the **child** WebView2 control (`view.Bounds = area`), never the form's own size → it cannot trigger another `Form.Resize`, so there is no resize loop. The comparison `(view.Left, view.Top, view.Width, view.Height) != (area.X, area.Y, area.Width, area.Height)` makes the assignment a no-op in the normal docked case.
- **`_emit` (`core/api.py:1122-1159`)** — the JSON serialisation is inside the `try` (a non-serialisable payload is logged, not raised), and the UI-thread guard `if threading.current_thread() is _MAIN_THREAD:` hands the `evaluate_js` to an `EmitWorker` thread, honouring the project's non-negotiable rule that `_emit` must never run on the UI thread. (`_emit` is physically inside WN-04's band but topically owned by WN-03; no defect found.)
- **`close()` / `close_window()` idempotency** — `close()` hides to the tray when possible and otherwise schedules `self._window.destroy` on a 0.1 s `threading.Timer`; pywebview's `destroy_window` looks the browser instance up by uid and returns early once the form is gone (`webview/platforms/winforms.py:905-915`), so a second `close()` is harmless.
- **`begin_window_resize` input validation** — the direction is checked against an explicit allow-list of eight edges *before* any native call, and both the "maximised" and "mini mode" guards reject early with a user-readable error (`core/api.py:995-1005`); the existing tests pin all of it.
- **`_change_maximized_state` work-area handling** — `native.MaximizedBounds = Screen.FromHandle(native.Handle).WorkingArea` is applied on the UI thread, so the maximised window respects the taskbar; `core/snap_layouts.py:263-275` additionally constrains `WM_GETMINMAXINFO`, which covers Win+Up and Snap.
- **`_get_hwnd` fallback chain** — although the first two branches are dead (F-WN-04-9), the third branch is correct for the current app: the form caption is the literal "NeDotify" (`main.py:349`), the app never calls `set_title`, and the single-instance mutex (`main.py:249-274`) prevents a second app window from confusing the lookup.

### 4. Coverage gaps

- **No live Windows session was exercised.** The rules forbid running the real app, so every native claim (the modal move/size loops, `WS_THICKFRAME` being required for `SC_SIZE`, the DWM corner attribute, `MonitorFromWindow` under mixed DPI) is derived from the source of pywebview in `.venv_win/Lib/site-packages/webview` and from Win32 documentation, not from an executed trace. The two findings marked as partially hypothetical (F-WN-04-6's "Windows refuses to size without WS_THICKFRAME", F-WN-04-12's WinForms-side drift) should be confirmed on a scaled Windows 11 machine.
- **The mixed-DPI / multi-monitor behaviour could not be measured.** `_get_scale_factor` (F-WN-04-2) and pywebview's own `GetScaleFactorForDevice(0)` are both *primary-monitor* based; the per-window re-read on a monitor switch (the `WM_DPICHANGED` path) is implemented nowhere in this area — `core/snap_layouts.py::_dpi_scale` does re-read `GetDpiForWindow` per hit test, but the *geometry* helpers do not. A two-monitor 100 %/150 % test would be needed to quantify the drift.
- **The tray defect (F-WN-04-1) was verified statically only** (AST + repo-wide grep). Confirming the user-visible half ("the app exits instead of hiding to the tray") requires running the app, which is out of bounds here.
- **`core/snap_layouts.py` was reviewed for Win32 correctness only**; the `_hit_test` grip geometry was checked by reading, not by measuring the actual cursor targets against the rendered frameless window.
- **The `snap_layouts` module is never uninstalled.** `SnapLayouts.uninstall()` (`core/snap_layouts.py:222-240`) has no caller in the repo, and `AppApi` never drops `_snap_layouts`. Today this is harmless (the process exits with the window), but a future in-process window recreation would subclass a stale HWND. Not raised as a finding because no such path exists in the reviewed code.
- **No test coverage was added or modified** (reviewer role). The suite already pins several of the reviewed behaviours: `tests/test_window_maximize.py` (maximize/restore/work area, `_fit_window_content`, the resize guard) and `tests/test_window_resize_api.py` (direction allow-list, capture/size dispatch, snap-button bridge). Notably **nothing** covers `_get_scale_factor`, `_logical_workarea`, `_saved_pos_coords`, the mini-player enter/exit geometry, or the tray start — which is why F-WN-04-1, F-WN-04-2, F-WN-04-3 and F-WN-04-4 went unnoticed.

