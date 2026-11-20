## AREA WN-04 — Bridge window management: mini-player, resize, drag, snap, geometry, maximize — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` L1–360 (imports, `_is_ssrf_safe_url`, `_dns_resolves_to_public_ip`, `AppApi.__init__`), L360–514 (`cleanup`, `_install_bridge_error_logging`, `_offline_bridge_result`), **L514–1160 (the assigned area, in full)**, L2725–2764 (`set_snap_button_rect`).
- `core/snap_layouts.py` L1–357 (whole file).
- `core/app.py` L505–586 (`AppCore.cleanup`).
- `core/tray.py` (grep: `on_show`, `on_quit`, `api._emit` usage).
- `main.py` L330–409, L525–584 (window creation, `api.set_window`, `webview.start`, shutdown path).
- `ui/web_new_v2/js/window-resize.js` (whole file), `ui/web_new_v2/js/main.js` L160–219 & L440–509, `ui/web_new_v2/js/player.js` L1090–1129.
- `utils/url_safety.py` (whole file).
- `tests/test_window_resize_api.py`, `tests/test_window_maximize.py`, `tests/test_window_visibility.py`, `tests/test_player_layout_geometry.py`, `tests/test_snap_layouts.py` (L1–60), `tests/test_emit_thread_safety.py` (grep).
- pywebview (installed dependency, read as the callee that defines the contract): `.venv_win/Lib/site-packages/webview/event.py`, `platforms/winforms.py` (whole file), `platforms/edgechromium.py` L95–174, `window.py`, `util.py` L185–260, `__init__.py`, `http.py` L100–169.

**Callees traced into other areas**

- `webview/platforms/winforms.py::BrowserForm.{resize,move,on_resize}` and `webview/event.py::Event.set` — pywebview internals; the *caller-side* misuse of their semantics is reported here, the framework behaviour itself is not a repo defect.
- `webview/util.py::get_functions` — decides which `AppApi` methods are reachable from JS (drives F-WN-04-12/F-WN-04-13).
- `core/api.py::_is_ssrf_safe_url` / `_dns_resolves_to_public_ip` — owned by **WN-03**; only its use as the URL gate of `open_url` is reported here.
- `main.py` window lifecycle (`create_window`, `webview.start`, `api.cleanup`) — owned by **WN-01**; the dead `api.shutdown()` call-site gap is reported here because the resource it is supposed to release (the Snap Layouts WndProc subclass) belongs to WN-04.
- `core/tray.py::TrayIcon.on_show` — owned by **WN-16**; it re-enters `AppApi._on_restored` (this area).
- `ui/web_new_v2/js/main.js::reportSnapButton` — owned by **WN-30**; it calls `set_snap_button_rect` on every rAF of a window resize (this area's bridge method).
- `js/events.js` event bus — owned by **WN-28**; it consumes the events `emit_event` can spoof (this area's bridge method).

---

### 2. Findings

#### F-WN-04-1  [P1] — Resize handling is unthrottled: every WinForms `Resize` spawns a Python thread and posts an unbounded queue of UI-thread work

- **File:** `core/api.py:617-627` (`_on_window_resized`), `core/api.py:605-615` (`_fit_window_content`), `core/api.py:737-747` (`_on_window_ui_thread`)
- **Confirmed:** yes (mechanism fully traced; magnitude not runtime-measured — see Reproduction)
- **Description:** `_on_window_resized` is registered on `window.events.resized` and does **no throttling, no coalescing and no de-duplication**. For each event it allocates a closure and posts one `BeginInvoke` to the WinForms UI thread, where `_fit_window_content` runs `native.PerformLayout()`, reads `native.ClientRectangle`, assigns `view.Bounds` and calls `view.Invalidate()`. The size argument pywebview passes (`*size`) is **completely ignored**, so even a resize event that changes nothing still triggers a full `PerformLayout()`.
- **Cause:** pywebview raises `events.resized` from `BrowserForm.on_resize`, i.e. **once per WM_SIZE** (i.e. per mouse-move during a drag). `webview/event.py:55-60` dispatches every non-locking event by **spawning a brand-new Python thread**:
  ```python
  if self._should_lock:
      execute()
  else:
      t = threading.Thread(target=execute)
      t.start()
  ```
  so one native resize produces one OS thread + one queued `System.Action` on the UI thread. The producer (WM_SIZE on the UI thread) is strictly faster than the consumer (the same UI thread draining `BeginInvoke` messages), so the WinForms message queue grows without bound during a drag.
- **Trigger conditions:** any drag-resize of the frameless window (also the native edge grips in `window-resize.js`, Win+Arrow, or the Snap Layouts flyout).
- **User impact:** the window lags behind the mouse during the drag and keeps processing hundreds of stale layout jobs *after* the drag ends (the "window catches up" effect). Thread churn (100–200 threads/s created and destroyed) also steals the GIL from the WebView2/JS side, so the UI feels sluggish exactly while the user is interacting with the window.
- **Evidence:**
  ```python
  # core/api.py:617
  def _on_window_resized(self, *size):
      target_win = self._window
      if sys.platform == 'win32' and target_win:
          def fit():
              native = getattr(target_win, 'native', None)
              ...
              self._fit_window_content(target_win)
          self._on_window_ui_thread(target_win, fit)
  ```
  ```python
  # core/api.py:605
  def _fit_window_content(self, target_win):
      ...
      native.PerformLayout()
      area = native.ClientRectangle
      if (view.Left, view.Top, view.Width, view.Height) != (area.X, area.Y, area.Width, area.Height):
          view.Bounds = area
          view.Invalidate()
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/winforms.py:349
  self.pywebview_window.events.resized.set(self.Width, self.Height)
  ```
- **Reproduction / verification:** drag the window border for ~2 s and count Python threads (`len(threading.enumerate())` from the DevTools console is not available; instead add a temporary counter in `_on_window_resized`) or watch `Get-Process python | Select-Object Threads`. Deterministic proof of the mechanism without the GUI: `webview/event.py` shows one thread per event and `Event.set` is called from `on_resize` on every WM_SIZE. A static proof that the work is redundant: `*size` is never read in `_on_window_resized`.
- **Suggested fix:** coalesce — keep the last size, ignore an event whose size equals the current one, and schedule at most one pending fit (a single `System.Windows.Forms.Timer` / `BeginInvoke` guarded by an "already pending" flag) instead of one per event.
- **Fix side effects:** the WebView2 control must still be re-fitted promptly after a *real* size change; a naive "only fit on the last event" would leave a stale client size when a drag ends without a final event (the last WM_SIZE is normally delivered, but a debounce must not drop it).
- **Discovered by:** B

---

#### F-WN-04-2  [P1] — `_get_scale_factor()` is dead code that always returns 1.0, so the whole "logical pixel" contract of the geometry layer is a no-op

- **File:** `core/api.py:629-648` (`_get_scale_factor`), `core/api.py:650-696` (`_logical_workarea`), `core/api.py:698-719` (`_saved_pos_coords`)
- **Confirmed:** yes (empirically verified, see Reproduction)
- **Description:** `_get_scale_factor()` documents itself as *"Logical-to-physical DPI scale of the window's current monitor … every coordinate we compute must be in the same space or positioning breaks on any display scaled above 100%"* — but it reads `getattr(native, "_scale", None)`. pywebview's WinForms backend never creates a `_scale` attribute; the BrowserForm exposes the factor as **`scale_factor`** (`webview/platforms/winforms.py:178`: `self.scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100`). There is **no `_scale` anywhere in the whole pywebview package** (verified by grep over `.venv_win/Lib/site-packages/webview`). Therefore the function always falls through to `val = 1.0`, and `_logical_workarea()` returns **physical** monitor pixels while its docstring promises logical ones.
- **Cause:** the attribute name was guessed rather than read from the platform layer; the `except Exception` + `getattr(..., None)` pattern converts the mistake into a silent, always-1.0 result.
- **Trigger conditions:** every call, on every machine. The *consequence* only appears on a display whose scale ≠ 100 %.
- **User impact:** the mini player is positioned at `scale ×` the intended location, i.e. **off-screen** on a 150 % display (see F-WN-04-3), and the whole `_logical_workarea → _saved_pos_coords → move()` chain silently uses the wrong unit.
- **Evidence:**
  ```python
  # core/api.py:636
  native = getattr(self._window, "native", None)
  scale = getattr(native, "_scale", None)
  ...
  val = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
  return val
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/winforms.py:176-179
  # for chromium edge, need this factor to modify the coordinates
  try:
      self.scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100 if is_chromium else 1
  except:
      self.scale_factor = 1
  ```
- **Reproduction / verification:** verified by running the real code against a stub that mimics pywebview's attribute name:
  ```
  scale_factor on native : 1.5
  _get_scale_factor()    : 1.0
  ```
  (script: `%TEMP%\opencode\probe_wn04.py`, `AppApi.__new__(AppApi)` + `SimpleNamespace(native=SimpleNamespace(scale_factor=1.5))`). A second probe confirmed `webview.window.Window` has neither `hwnd` nor `gui_window` (see F-WN-04-4).
- **Suggested fix:** obtain the factor from the real source (`native.scale_factor`, or better `GetDpiForWindow(hwnd)/96` for a per-monitor value) and fail loudly (log + raise into the geometry helpers) instead of silently returning 1.0.
- **Fix side effects:** `GetDpiForWindow` is per-window, while pywebview's `move()` applies the **device-wide** `scale_factor` — the two must be reconciled, otherwise the position would be scaled twice. Also `GetScaleFactorForDevice(0)` describes device 0 (primary), not the window's monitor, so a mixed-DPI multi-monitor setup still needs per-monitor handling.
- **Discovered by:** B

---

#### F-WN-04-3  [P1] — Physical-pixel geometry is fed into pywebview's logical-pixel `move()`, so the mini player lands off-screen and the main window is restored at the wrong position on scaled displays

- **File:** `core/api.py:749-771` (`_native_window_geometry`), `core/api.py:826-859` (`_exit_mini_mode`), `core/api.py:805-822` (`_enter_mini_mode`), `core/api.py:897-908` (`_apply_window_pos`)
- **Confirmed:** yes for the code paths; the visible misplacement is conditional on a display scale ≠ 100 % (the audit machine is 96 DPI / 100 %, so `scale_factor == 1.0` here — stated as an evidence gap below)
- **Description:** `_native_window_geometry()` returns **physical** pixels (`GetWindowRect`). `_exit_mini_mode()` feeds those coordinates straight into `target_win.move(int(gx), int(gy))`. But pywebview's `Window.move()` is a **logical-pixel** API: `BrowserForm.move()` multiplies its arguments by `self.scale_factor` before calling `SetWindowPos` (`webview/platforms/winforms.py:512-538`). Meanwhile `Window.resize()` does **not** scale at all (`winforms.py:500-510` uses the raw width/height in `SetWindowPos`). The mini player's *size* and *position* therefore live in two different coordinate spaces.
- **Cause:** the geometry layer mixes three spaces — Win32 physical px (`GetWindowRect`, `MonitorFromWindow`), WinForms device-independent px (`native.Bounds`, `ClientRectangle`) and pywebview's "logical" px (`move()`), with a single conversion helper (`_get_scale_factor`) that is broken (F-WN-04-2).
- **Trigger conditions:** Windows display scaling > 100 % (or a secondary monitor with a different scale, because pywebview uses the *primary* device factor).
- **User impact:** on a 150 % display, `_saved_pos_coords('bottom-right', 380, 110)` yields (1520, 910) from a 1920×1040 physical work area; `move()` then scales it to (2280, 1365) → **the mini player is created off-screen** and the user cannot see or reach it. Exiting mini mode restores the main window at 1.5× its original coordinates instead of at the position the user left it.
- **Evidence:**
  ```python
  # core/api.py:764-768
  if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
      raise ctypes.WinError(ctypes.get_last_error())
  return (int(rect.right - rect.left), int(rect.bottom - rect.top),
          int(rect.left), int(rect.top))
  ```
  ```python
  # core/api.py:847-848
  if gx is not None and gy is not None and hasattr(target_win, 'move'):
      target_win.move(int(gx), int(gy))
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/platforms/winforms.py:512-538 (pywebview)
  def move(self, x, y):
      ...
      if self.scale_factor != 1:
          x_modified = x * self.scale_factor
          y_modified = y * self.scale_factor
          windll.user32.SetWindowPos(self.Handle.ToInt32(), None, int(x_modified), int(y_modified), None, None, ...)
  ```
- **Reproduction / verification:** set the display scale to 125/150 % (Windows Settings → System → Display → Scale), start the app, switch to the mini player (`btn-mini-player`) and observe that it is placed outside the visible area; switch back and observe that the window is no longer where it was. Static proof: `_native_window_geometry` returns `GetWindowRect` values (physical) and `Window.move` scales by `scale_factor` (verified in the installed pywebview source).
- **Suggested fix:** pick one canonical space for the whole layer (physical Win32 px is the most natural for this code), convert explicitly at the pywebview boundary (`move(x / scale, y / scale)`), and derive the scale from the window's own monitor, not from `GetScaleFactorForDevice(0)`.
- **Fix side effects:** pywebview's `resize()` does not scale, so making `move()` physical while `resize()` stays physical is consistent — but the mini player's *CSS* size (380×110 CSS px) would then be interpreted as physical px, so the mini-player CSS must be checked against the WebView2 device scale factor (belongs to WN-30/WN-33).
- **Discovered by:** B

---

#### F-WN-04-4  [P2] — The native window handle is resolved by window **caption**, not by the real handle; the app can subclass and restyle a foreign or stale window

- **File:** `core/api.py:1032-1051` (`_get_hwnd`), `core/api.py:749-753` (`_native_window_geometry` ignores its `target_win` argument), `core/snap_layouts.py:150-212` (`SnapLayouts.install`)
- **Confirmed:** yes (the attribute probe is empirical; the "foreign window" consequence follows directly from `FindWindowW` semantics)
- **Description:** `_get_hwnd()` tries `self._window.hwnd`, then `self._window.gui_window.Handle`, then falls back to `ctypes.windll.user32.FindWindowW(None, title)`. pywebview's `Window` class has **neither** `hwnd` **nor** `gui_window` (verified: `hasattr(Window(...), 'hwnd') == False`, `hasattr(..., 'gui_window') == False`), so **every** call ends in the caption lookup. `FindWindowW` returns *any* top-level window with that exact caption, including one belonging to another process or to a previous instance of this app that has not finished exiting. The handle is then used for `SetWindowLongPtr(GWL_WNDPROC)` + `SetWindowLongW(GWL_STYLE)` (snap_layouts.py:173-185), for `WM_NCLBUTTONDOWN` drags, for `GetWindowRect` and for the DWM corner attribute.
- **Cause:** the platform layer never exposes the real handle, so the code re-implements a lookup instead of using `self._window.native.Handle` (the `BrowserForm`'s handle, which is exactly the window pywebview created).
- **Trigger conditions:** (a) a fast app restart while the previous instance's window still exists; (b) any other process with a top-level window captioned "NeDotify"; (c) `_install_snap_layouts`'s background thread still polling during shutdown (see F-WN-04-5) — it can latch onto any window that appears with that caption.
- **User impact:** the app installs its window procedure and style changes on a **foreign** window (a visible side effect in another application), or on the *old* instance's window — in which case drag/resize/corner-rounding act on a window the user cannot see, and the current instance's window loses the resize grips and the Snap Layouts flyout.
- **Evidence:**
  ```python
  # core/api.py:1032
  def _get_hwnd(self):
      if not self._window:
          return None
      if hasattr(self._window, "hwnd") and self._window.hwnd:
          return self._window.hwnd
      if hasattr(self._window, "gui_window") and hasattr(self._window.gui_window, "Handle"):
          ...
      if sys.platform == "win32":
          try:
              import ctypes
              title = getattr(self._window, "title", "NeDotify")
              hwnd = ctypes.windll.user32.FindWindowW(None, title)
  ```
  ```python
  # core/snap_layouts.py:173-185 — the found handle is subclassed and restyled
  prev = SetWindowLongPtr(self.hwnd, GWL_WNDPROC, proc_addr)
  ...
  user32.SetWindowLongW(self.hwnd, GWL_STYLE, old_style | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU)
  ```
- **Reproduction / verification:** create a second top-level window with the caption "NeDotify" (e.g. a tiny WinForms/PowerShell window) *before* starting the app and observe that the Snap Layouts subclass is installed on that window (`SetWindowLongPtr` on the wrong HWND) instead of on the app's own window. Static proof that the fallback is the *only* path: `hasattr(webview.window.Window, 'hwnd') == False`.
- **Suggested fix:** resolve the handle once, from `self._window.native.Handle` (the `BrowserForm`), cache it, and validate it with `IsWindow()` before every use; drop the caption lookup entirely.
- **Fix side effects:** `native` is `None` until pywebview has created the form, so the resolution must stay retryable (the existing retry loop can keep that role) — but it must re-read `native.Handle`, not search by title.
- **Discovered by:** B

---

#### F-WN-04-5  [P2] — The Snap Layouts window-procedure subclass is never uninstalled, and `AppApi.shutdown()` is dead code that cannot release it

- **File:** `core/api.py:940-944` (`shutdown`), `core/api.py:446-459` (`cleanup`), `core/api.py:542-572` (`_install_snap_layouts`), `core/snap_layouts.py:222-240` (`SnapLayouts.uninstall`)
- **Confirmed:** yes
- **Description:** `SnapLayouts` installs a raw `ctypes.WINFUNCTYPE` callback as the window procedure and keeps it alive only through `self._snap_layouts` on the `AppApi`. `SnapLayouts.uninstall()` exists and correctly restores the original WndProc and style *before* dropping the callback — but **nothing ever calls it**. `AppApi.shutdown()` (the only method that looks like a teardown) merely nulls three window references; it does not uninstall the subclass, does not clear `_snap_layouts`, and does not cancel the pending deferred operations. `shutdown()` is itself never called: `main.py:576-579` calls `api.cleanup()` (tray + thread pools only) and `core/app.py:508-586` (`AppCore.cleanup`) never calls `api.shutdown()`.
- **Cause:** the teardown contract of the bridge was never wired to the native resources the bridge owns.
- **Trigger conditions:** every application exit; and the `_install_snap_layouts` retry thread (up to 20 × 0.25 s = 5 s) keeps polling `self._get_hwnd()` → `FindWindowW` *after* the window is gone, so during shutdown it can latch onto **any** window that carries the caption "NeDotify" and subclass it (compounding F-WN-04-4).
- **User impact:** the WndProc subclass and the `WS_THICKFRAME|WS_MAXIMIZEBOX|WS_SYSMENU` style change outlive the app's own teardown. Today the damage is bounded because the HWND dies with the process and the callback object stays referenced by `self._snap_layouts` (no use-after-free) — but that is accidental: nothing enforces it, and the retry thread can actively subclass a foreign window during shutdown.
- **Evidence:**
  ```python
  # core/api.py:940
  def shutdown(self):
      """Release API-owned resources before the application exits."""
      self._window = None
      self._main_window = None
      self._mini_window = None
  ```
  ```python
  # core/snap_layouts.py:222 — the correct teardown exists but is never called
  def uninstall(self):
      if not self._installed or not self.hwnd:
          return
      ...
      if not SetWindowLongPtr(self.hwnd, GWL_WNDPROC, LONG_PTR(self._old_wndproc or 0)):
          raise OSError("WndProc restore returned 0")
      self._installed = False
      self._proc = None
  ```
- **Reproduction / verification:** grep the repo for `uninstall(` → only the definition; grep for `api.shutdown` / `.shutdown()` → no call site in `main.py`/`core/app.py`. Add a temporary `print` in `SnapLayouts.uninstall` and restart the app: it never prints.
- **Suggested fix:** call `snap.uninstall()` from `AppApi.cleanup()` (which *is* on the exit path) before dropping the window reference, and make `cleanup()` also cancel pending deferred window operations.
- **Fix side effects:** `uninstall()` restores the original WndProc — it must run *before* the HWND is destroyed, i.e. before `Window.destroy()`, otherwise the restore targets a dead window. Ordering with `main.py`'s `app_core.cleanup()` / `api.cleanup()` must be explicit.
- **Discovered by:** B

---

#### F-WN-04-6  [P2] — `_on_window_ui_thread` falls back to running WinForms code on a non-UI thread when `BeginInvoke` fails

- **File:** `core/api.py:737-747` (`_on_window_ui_thread`)
- **Confirmed:** yes
- **Description:**
  ```python
  def _on_window_ui_thread(self, target_win, fn):
      native = getattr(target_win, "native", None)
      try:
          if native is not None and native.InvokeRequired:
              from System import Action
              native.BeginInvoke(Action(fn))
              return
      except Exception:
          logger.debug("Could not queue window operation on UI thread", exc_info=True)
      fn()
  ```
  The `try` covers *both* the `InvokeRequired` probe **and** the `BeginInvoke` call. Any exception (a disposed form → `ObjectDisposedException`; a destroyed handle → `InvalidOperationException`) is swallowed at debug level and the code then **executes `fn()` on the calling thread**. `fn()` is WinForms UI code (`native.PerformLayout()`, `native.ClientRectangle`, `view.Bounds = ...`, `native.WindowState = ...`, `native.MinimumSize = ...`).
- **Cause:** the exception handler conflates "cannot determine whether an invoke is needed" with "the invoke failed"; the safe fallback for the second case is to *drop* the operation, not to run it off-thread.
- **Trigger conditions:** the form is disposed/closed between the `InvokeRequired` probe and the `BeginInvoke` — exactly the window in which the 0.25 s deferred operations (`_enter_mini_mode`, `_exit_mini_mode`) fire while the app is closing.
- **User impact:** cross-thread WinForms access raises `InvalidOperationException: Cross-thread operation not valid` (logged by pywebview's `Event.set` handler, invisible to the user) or corrupts the control's layout state; the operation is silently lost, so the window can be left in mini geometry with the main window's chrome, or with `MinimumSize = (1,1)` still applied.
- **Evidence:** the quoted block above; compare with the *correct* pattern used elsewhere in the same file (`_change_maximized_state.change()` wraps its body in `try/except`, `begin_window_resize.start_sizing()` likewise).
- **Reproduction / verification:** close the app within the 0.25 s window after toggling the mini player (`toggle_mini_player(True)` then immediately `close_window()`), and grep the log for `Could not queue window operation on UI thread` followed by `Cross-thread operation not valid`.
- **Suggested fix:** separate the two cases — if `BeginInvoke` fails, log a warning and **return** (drop the operation) instead of calling `fn()` off-thread.
- **Fix side effects:** dropping the operation means the window keeps its pre-op geometry; that is preferable to a cross-thread mutation, but the caller should be told (e.g. via the deferred-op result) so the optimistic frontend state can be rolled back.
- **Discovered by:** B

---

#### F-WN-04-7  [P2] — Unprotected Python delegates run on the WinForms UI thread; an exception there becomes an unhandled .NET exception (process-level crash)

- **File:** `core/api.py:805-816` (`_apply_mini_geometry`), `core/api.py:838-853` (`_restore`), `core/api.py:621-626` (`fit`)
- **Confirmed:** yes
- **Description:** `_on_window_ui_thread` marshals `fn` to the UI thread as `native.BeginInvoke(Action(fn))`. When `fn` raises, the exception is raised **inside the delegate invocation on the UI thread**, i.e. inside the WinForms message loop. pywebview installs **no** `Application.ThreadException` handler and no `Application.SetUnhandledExceptionMode` call (grep over the whole installed pywebview package: no match), so the exception takes the CLR's default unhandled-exception path (error dialog and/or process termination) instead of being logged by the app.
- **Cause:** the two mini-player delegates (`_apply_mini_geometry`, `_restore`) and the resize `fit` closure have **no** `try/except` inside the delegate body, while the sibling delegates in the same file (`_change_maximized_state.change`, `begin_window_resize.start_sizing`) do. The protection is inconsistent.
- **Trigger conditions:** the form is disposed between the deferred delay and the delegate's execution — e.g. `toggle_mini_player(True)` followed by a close within 0.25 s; or `native.MinimumSize = Size(1, 1)` / `target_win.resize(...)` / `target_win.move(...)` touching a destroyed handle.
- **User impact:** the whole application dies with a .NET exception dialog instead of a clean shutdown or a logged warning.
- **Evidence:**
  ```python
  # core/api.py:805 — no try/except inside the delegate body
  def _apply_mini_geometry():
      native = getattr(target_win, "native", None)
      if native is not None:
          from System.Drawing import Size
          from System.Windows.Forms import FormWindowState
          native.WindowState = FormWindowState.Normal
          native.MinimumSize = Size(1, 1)
      ...
      target_win.resize(w, h)
      self._apply_window_pos(target_win, self._saved_mini_pos, w, h)
  ```
  vs. the protected sibling:
  ```python
  # core/api.py:1058
  def change():
      try:
          ...
      except Exception:
          logger.warning('Could not change window state', exc_info=True)
  ```
- **Reproduction / verification:** `toggle_mini_player(True)` immediately followed by `close_window()` (or by killing the WebView) and watch for a .NET "Unhandled exception" dialog / non-zero exit code; alternatively call `api._deferred_window_op(0.0, lambda: api._on_window_ui_thread(api._window, lambda: 1/0))` against a closed window in a scratch harness.
- **Suggested fix:** wrap every delegate body in `try/except Exception: logger.warning(..., exc_info=True)` — a single, uniform guard at the `_on_window_ui_thread` boundary would cover all call sites.
- **Fix side effects:** swallowing the exception hides a genuine geometry failure; the caller should therefore get an explicit failure result (see F-WN-04-8) rather than a silent success.
- **Discovered by:** B

---

#### F-WN-04-8  [P2] — `toggle_mini_player` returns success **before** the native operation runs, so the frontend's documented rollback path is unreachable

- **File:** `core/api.py:773-790` (`toggle_mini_player`), `core/api.py:792-824` (`_enter_mini_mode`), `ui/web_new_v2/js/main.js:175-205`
- **Confirmed:** yes
- **Description:** the bridge method returns `{"success": True, "is_mini": enable}` synchronously, but the actual resize/move happens **0.25 s later** in a background thread (`_deferred_window_op(0.25, ...)`). Every native failure is swallowed by `except Exception as err: logger.debug(f"Failed setting mini size: {err}")` (api.py:823-824) and can never influence the return value. The frontend explicitly documents the opposite contract: *"rolled back when the native resize/move actually failed"* (`main.js:196`) — but `backendOk = !res || res.success !== false` is always `true`, so the rollback branch (main.js:197-203) is **dead code**.
- **Cause:** the bridge API is synchronous by design, but the native operation was made asynchronous (correctly, to avoid blocking the UI thread) without adding a completion signal (no `_emit('mini_player_state', ...)`), so success/failure is unobservable.
- **Trigger conditions:** any failure of the deferred native step — the HWND lookup returning a stale/foreign handle (F-WN-04-4), the window being closed in the meantime, or `BeginInvoke` failing (F-WN-04-6).
- **User impact:** the UI shows the mini player while the OS window is still the full-size window (or the reverse). The user sees a "mini player" that is really the full window (or a full window with mini-player CSS), with no error message and no automatic recovery.
- **Evidence:**
  ```python
  # core/api.py:786
  return {"success": True, "is_mini": enable}
  ...
  # core/api.py:820 — the real work happens 0.25 s later, on another thread
  self._deferred_window_op(0.25, lambda: self._on_window_ui_thread(target_win, _apply_mini_geometry))
  ```
  ```javascript
  // ui/web_new_v2/js/main.js:196-203
  // ...rolled back when the native resize/move actually failed.
  if (!backendOk) { ... }
  ```
- **Reproduction / verification:** make the native step fail (e.g. set `api._window = None` right after the call, or close the app within 0.25 s) and observe that `toggle_mini_player` still returns `{"success": true}` while the window never changes size. Static proof: the only `return` in the method is the unconditional success dict, and the native work is deferred.
- **Suggested fix:** emit a completion event (`mini_player_state` with `{"is_mini": bool, "ok": bool}`) from the deferred worker and let the frontend reconcile — or perform the native step synchronously on the UI thread via `Invoke` and return the real result.
- **Fix side effects:** an event-based contract changes the frontend protocol (WN-30 owns `main.js`); the frontend already has an optimistic path, so the event would only be needed to *correct* it.
- **Discovered by:** B

---

#### F-WN-04-9  [P3] — The window-state fields are shared across three threads without joining the class's existing lock (AGENTS.md rule #2)

- **File:** `core/api.py:351-353` (field declarations), `core/api.py:625` / `802` / `1081` / `1089` (writes), `core/api.py:560` / `777` / `886` / `1001` (reads), `core/api.py:721-735` (`_deferred_window_op`, the only lock user)
- **Confirmed:** yes
- **Description:** `_is_maximized`, `_is_mini_active`, `_saved_mini_pos`, `_saved_main_geometry` and `_last_geometry` form a shared mutable group that is written from the UI thread (`_on_window_resized` → `fit`, `_change_maximized_state` → `change`), from the bridge thread (`toggle_mini_player`, `set_mini_player_position`, `_enter_mini_mode`) and from the deferred worker thread. The class's existing lock is `self._window_op_lock` (api.py:353) and it is taken **only** inside `_deferred_window_op`; none of these fields is guarded by it. AGENTS.md states: *"A new shared field joins its class's existing lock rather than opening a second one."*
- **Cause:** the window-state group was added without a defined owner; each writer "helpfully" writes the flag it knows about, so several components own parts of the same state.
- **Trigger conditions:** maximize + resize + mini-mode changes interleaved (all of which happen during ordinary use).
- **User impact:** `_is_maximized` is the guard used by `begin_window_resize` (api.py:1001) and by `SnapLayouts._hit_test` (snap_layouts.py:297). A stale value either blocks a legitimate resize ("Restore the main window before resizing") or lets a native sizing loop start on a maximized window (Windows then un-maximizes it unexpectedly). `_is_mini_active` is read by the Snap Layouts hit test on the UI thread while being written by the bridge thread.
- **Evidence:**
  ```python
  # core/api.py:351-353
  self._is_mini_active = False
  self._saved_mini_pos = "bottom-right"
  self._window_op_lock = threading.RLock()
  ```
  ```python
  # core/api.py:620-626 — written on the UI thread, outside any lock
  def fit():
      native = getattr(target_win, 'native', None)
      if native is not None and hasattr(native, 'WindowState'):
          from System.Windows.Forms import FormWindowState
          self._is_maximized = native.WindowState == FormWindowState.Maximized
  ```
  ```python
  # core/api.py:802 — written on the bridge thread
  self._is_maximized = False
  ```
- **Reproduction / verification:** static: grep every `self._is_maximized` / `self._is_mini_active` assignment and observe that none is inside `with self._window_op_lock:`. A runtime check would need a thread-sanitizer style instrument; the consequence is a stale-flag read, not memory corruption (CPython attribute assignment is atomic).
- **Suggested fix:** funnel all window-state mutations through one lock-protected accessor (e.g. `_set_window_state(maximized=..., mini=...)` under `self._window_op_lock`), and read the flags through the same accessor, so the group has a single owner.
- **Fix side effects:** taking an RLock on the UI thread inside `fit()` while the bridge thread holds it during a deferred op could serialise the UI thread behind a slow deferred op — keep the critical sections tiny.
- **Discovered by:** B

---

#### F-WN-04-10  [P3] — The Snap Layouts install is a 5-second blind polling loop started *before* the window exists; a slow startup silently loses the feature

- **File:** `core/api.py:529-572` (`set_window` → `_install_snap_layouts`), `main.py:384` (`api.set_window(window)`), `main.py:555` (`webview.start(...)`)
- **Confirmed:** yes
- **Description:** `set_window()` is called at `main.py:384`, but the native handle does not exist until pywebview constructs the `BrowserForm` inside `webview.start()` at `main.py:555`. The installer therefore polls `self._get_hwnd()` 20 times with a 0.25 s delay — a budget that starts **before** the window is created and is consumed by the whole remaining startup. If the HWND is not found within 5 s of `set_window()`, the feature is abandoned with a single `logger.warning("Snap Layouts skipped: no window handle after %.1fs", ...)` and the user silently loses the Snap Layouts flyout and the edge resize grips (the `WM_NCHITTEST` subclass is what provides both).
- **Cause:** a time-based poll is used where an event-based signal exists (`window.events.shown` fires when the form is up).
- **Trigger conditions:** a slow startup — route installation, the startup watchdog, a cold WebView2 profile, an antivirus scan — between `main.py:384` and `main.py:555`.
- **User impact:** the maximise button shows no Snap Layouts flyout and the window borders are no longer draggable, with no visible error and no way to recover without restarting.
- **Evidence:**
  ```python
  # core/api.py:552-571
  for _ in range(attempts):
      ...
      if hwnd:
          ...
      time.sleep(delay)
  logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
  ```
- **Reproduction / verification:** insert a `time.sleep(6)` between `main.py:384` and `main.py:555` (or delay `webview.start()`), start the app and observe the warning in `~/.nedotify/logs/app.log` and the missing Snap flyout.
- **Suggested fix:** drive the installation from `window.events.shown` (plus a bounded retry for the "shown before the handler was attached" race) instead of a wall-clock budget that starts before the window exists.
- **Fix side effects:** the subclass would then be installed slightly later (after `shown`), so the first hover over the maximise button may not yet show the flyout — the frontend already retries `set_snap_button_rect` 12× (main.js:473), which covers the button-rect side.
- **Discovered by:** B

---

#### F-WN-04-11  [P3] — `open_url` / `open_external_url`: the scheme allowlist is sound, but the SSRF guard fails **open** on a DNS failure and blocks the bridge thread on resolution; no UI code path reaches these methods

- **File:** `core/api.py:1109-1116` (`open_url`, `open_external_url`), `core/api.py:161-195` (`_is_ssrf_safe_url`), `core/api.py:133-158` (`_dns_resolves_to_public_ip`), `core/api.py:93-102` (the DoH-fallback note)
- **Confirmed:** yes for the allowlist and the fail-open behaviour; the "no UI caller" statement is confirmed by grep
- **Description:** the brief's main hypothesis — a malicious track title / playlist name / lyric line injecting `file://`, `\\server\share`, `javascript:`, `ms-msdt:`, `search-ms:` or `data:` into the OS — **does not materialise**: `_is_ssrf_safe_url` accepts only `http`/`https` schemes (`parsed.scheme not in ("http", "https") → False`), so every dangerous scheme is rejected before the URL ever reaches `webbrowser.open`. Two real defects remain:
  1. **Fail-open on DNS failure.** `_dns_resolves_to_public_ip` initialises `verdict = True` and only flips it on an *exception* if the hostname starts with `169.254.`/`10.`/`192.168.`/`127.`:
     ```python
     verdict = True
     try:
         addr_info = socket.getaddrinfo(hostname, None)
         ...
     except Exception:
         if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("127."):
             verdict = False
     ```
     A host that does not resolve (or resolves only to an address form the fallback does not match) is therefore classified **safe**. `main.py` additionally patches `socket.getaddrinfo` with a DoH fallback over three endpoints, so the app's verdict can disagree with the browser's own (system-resolver) answer — classic split-horizon / rebinding divergence. The stated intent "fail closed" is not implemented.
  2. **Blocking resolution on the bridge thread.** The check performs a synchronous `getaddrinfo` on the bottle worker thread; with the DoH fallback (3 endpoints × 2 s) an unresolvable host can block that worker for ~6 s — the exact hazard the `_SSRF_CACHE` comment above describes.
  3. **Dead surface.** Grep over `ui/web_new_v2/**` (js + html) finds **no** caller of `open_url` or `open_external_url`; the only URL-accepting bridge method the UI uses is `import_external_playlist` (WN-07), which uses the same guard. The methods are still reachable from JS because pywebview exposes every public method of the `js_api` object (`webview/util.py:185-208`).
- **Cause:** the guard was designed for *fetching* URLs (SSRF) but is reused for *handing a URL to the OS browser*, where the threat model is different (local scheme handlers, `file://`, UNC); and the DNS verdict is computed optimistically instead of negatively.
- **Trigger conditions:** a JS caller passing a URL whose host does not resolve, or resolves differently under DoH vs. the system resolver.
- **User impact:** low. The URL is opened in the user's own default browser, which applies its own protections; the practical damage is a blocked bridge worker and a browser tab that the SSRF guard should have refused.
- **Evidence:** the quoted blocks above; `core/api.py:1111`: `if url and _is_ssrf_safe_url(url): webbrowser.open(url)`.
- **Reproduction / verification:** `python -c "from core.api import _is_ssrf_safe_url as f; print(f('http://this-host-does-not-exist.invalid/'), f('file:///C:/Windows/System32/drivers/etc/hosts'), f('search-ms:query=x'), f('javascript:alert(1)'), f('http://127.0.0.1:8080/'))"` → the first is `True` (fail-open), the others `False`. Confirmed no UI caller: `Select-String -Path ui\web_new_v2\js\*.js,ui\web_new_v2\index.html -Pattern "open_url|open_external_url"` → no match.
- **Suggested fix:** make the verdict negative (`verdict = False` unless every resolved address is public *and* resolution succeeded), and — better — separate the two intents: `open_url` should validate against a *scheme* allowlist only (http/https) and let the browser handle the rest, without the SSRF/DNS machinery.
- **Fix side effects:** failing closed on DNS failure would block legitimate URLs whose host is temporarily unresolvable — for a *browser hand-off* that is acceptable; for `import_external_playlist` (WN-07) it would change existing behaviour and must be coordinated with that area.
- **Discovered by:** B

---

#### F-WN-04-12  [P3] — `emit_event` is an unvalidated public bridge method: any script in the WebView can inject arbitrary events into the frontend bus

- **File:** `core/api.py:1118-1120` (`emit_event`), `core/api.py:1122-1159` (`_emit`)
- **Confirmed:** yes
- **Description:** `emit_event(event_name, data)` forwards an arbitrary name and payload to `window.onPythonEvent(name, payload)`. pywebview exposes **every public method** of the `js_api` object to JS (`webview/util.py:185-208`, `get_functions` skips only `_`-prefixed names), and `emit_event` is deliberately *not* excluded (it is in `_UNWRAPPED` only to avoid error-wrapper recursion, api.py:397-399). There is no allowlist of event names and no payload schema check.
- **Cause:** the method exists for *internal* Python→JS use (`core/downloader.py:180`, `core/proxy.py:1019-1118`, `main.py:397`) but is exposed on the same public surface as the user-facing API.
- **Trigger conditions:** any script execution inside the WebView (an XSS in the remote-sourced track/lyric/artist metadata, a devtools session — the app ships a documented `NEDOTIFY_DEVTOOLS=1` flag, `main.py:551-554`).
- **User impact:** a spoofed `download_complete` (the contract in WIN_AUDIT_CONTEXT.md rule #7 says the backend event carries **no** `file_path`, but nothing prevents a caller from adding one) or a spoofed `track_changed` / `proxy_status` desynchronises the player UI and the download list from the real backend state.
- **Evidence:**
  ```python
  # core/api.py:1118
  def emit_event(self, event_name: str, data: dict = None):
      """Emit JS event to frontend webview."""
      self._emit(event_name, data)
  ```
  ```python
  # core/api.py:1133-1136 — the name is interpolated verbatim into the JS source
  js_code = (
      f"if (window.onPythonEvent) {{ window.onPythonEvent("
      f"{json.dumps(event_name)}, {payload_json}); }}"
  )
  ```
- **Reproduction / verification:** from the WebView console (or any injected script): `await window.pywebview.api.emit_event('download_complete', {track_id: 1, file_path: 'C:/Windows/System32/config/SAM'})` → the frontend's event bus receives it as a genuine backend event. Confirm the exposure rule by reading `webview/util.py:185-208`.
- **Suggested fix:** rename the internal emitter to a private method (`_emit` already exists and is the real implementation) and expose a *curated* public `emit_event` that validates the name against a fixed allowlist and rejects unknown payloads.
- **Fix side effects:** `core/proxy.py` and `core/downloader.py` call `api.emit_event(...)` through the public attribute — renaming requires updating those call sites (WN-11 / WN-13).
- **Discovered by:** B

---

#### F-WN-04-13  [P3] — `close()` is not idempotent, and the JS-exposed lifecycle mutators (`shutdown`, `set_window`, `set_windows`) can permanently disable the app's own close button

- **File:** `core/api.py:917-938` (`close`), `core/api.py:940-948` (`shutdown`, `close_window`), `core/api.py:910-915` (`set_windows`), `core/api.py:397-399` (`_UNWRAPPED`)
- **Confirmed:** yes
- **Description:** (a) `close()` schedules `threading.Timer(0.1, self._window.destroy)`; a second `close()` schedules a second destroy → `i.Invoke(...)` on an already-closed form raises inside the Timer thread → an unhandled exception traceback on stderr and a lost `close()` (no `try/except` around the timer body). `close()` never stops the tray, never cancels the pending deferred window operations and never un-registers the pywebview event handlers it added in `set_window` (`self._window.events.minimized += self._on_minimized` etc., api.py:521-527 — pywebview's `Event.__iadd__` **appends** to a list, so a second `set_window()` duplicates every handler).
  (b) `shutdown`, `set_window` and `set_windows` are public methods of the `js_api` object and are therefore callable from the WebView (pywebview exposes all public methods). `shutdown()` sets `self._window = None`, after which `_emit` returns immediately (`api.py:1124-1125`) — **all** backend→UI events are silently dropped — and `close()` returns `{"success": True, "message": "No active window"}`, so the close button (`js/main.js:493-495` → `close_window()` → `close()`) becomes a no-op and the app can only be killed from the task manager. `set_window(<js value>)` overwrites the window reference with a non-window object and breaks the whole bridge the same way. `set_windows(null, "x")` sets `_mini_window` to a truthy non-window, and the next `toggle_mini_player(True)` then operates on a string (`target_win.resize(...)` → `AttributeError`, swallowed by `except Exception as err: logger.debug(...)`).
- **Cause:** lifecycle methods and internal state mutators share one public surface; there is no separation between "commands the UI may issue" and "operations the backend performs on itself".
- **Trigger conditions:** a stray/duplicate call, or any script execution in the WebView (see F-WN-04-12).
- **User impact:** the application can end up in a state where it still runs but can no longer be closed or updated from the UI; in the normal (non-malicious) flow the duplicate-handler accumulation is latent only.
- **Evidence:**
  ```python
  # core/api.py:934-938
  self.flush_listening()
  closer = threading.Timer(0.1, self._window.destroy)
  closer.daemon = True
  closer.start()
  return {"success": True, "message": "Window closing..."}
  ```
  ```python
  # core/api.py:940-944 — public, JS-reachable, and it kills the bridge
  def shutdown(self):
      self._window = None
      self._main_window = None
      self._mini_window = None
  ```
  ```python
  # .venv_win/Lib/site-packages/webview/event.py:84-85 — handlers are appended, never replaced
  def __iadd__(self, item: Callable[..., Any]) -> Self:
      self._items.append(item)
      return self
  ```
- **Reproduction / verification:** from the WebView console: `await window.pywebview.api.shutdown()` → the close button stops working and no further backend events arrive; `await window.pywebview.api.set_windows(null, 'x')` → the mini player stops resizing (debug log: `Failed setting mini size: 'str' object has no attribute 'resize'`).
- **Suggested fix:** keep the lifecycle mutators internal (`_shutdown`, `_set_windows`) and expose a narrow, validated command surface to the UI; make `close()` idempotent with a `_closing` flag and wrap the timer body in `try/except`.
- **Fix side effects:** `set_windows`/`shutdown` are currently not called by the app or by the UI, so renaming them is low risk; `main.py` would need to call the renamed `_shutdown` if the intent was for it to run.
- **Discovered by:** B

---

#### F-WN-04-14  [P3] — The native drag/resize path mutates the process-global `SendMessageW` signature and blocks a bridge worker for the whole drag

- **File:** `core/api.py:959-990` (`begin_window_drag`), `core/api.py:992-1030` (`begin_window_resize`), `core/api.py:1016-1017`
- **Confirmed:** yes
- **Description:** both methods set `user32.SendMessageW.argtypes` / `.restype` on the **shared** `ctypes.windll.user32` function object. The values they set are consistent with each other, but the mutation is process-global and invisible: any other module that sets a different signature for the same function (e.g. `restype = c_int`) silently truncates the 64-bit LPARAM — the exact failure mode documented in `core/snap_layouts.py:67-71` ("*Without explicit argtypes ctypes coerces a 64-bit lparam into a 32-bit C int … OverflowError: int too long to convert from inside the callback*"). `begin_window_drag` additionally issues `SendMessageW(WM_NCLBUTTONDOWN, HTCAPTION)` **synchronously** from the bottle worker thread: the message is dispatched on the UI thread, which enters the modal drag loop, so the worker thread (and the HTTP request behind it) stays blocked until the user releases the mouse.
- **Cause:** per-call-site signature configuration of a shared ctypes function instead of one central, module-level configuration (which `core/snap_layouts.py::_configure_user32()` already implements for the other user32 entry points).
- **Trigger conditions:** any drag of the frameless window (`player.js:1105` → `begin_window_drag`), any edge-grip resize (`window-resize.js:16` → `begin_window_resize`).
- **User impact:** during a drag, one bottle worker thread and one HTTP connection are pinned for the duration of the drag; the JS promise for `begin_window_drag` resolves only after the mouse is released. Harmless at the current scale, but it scales with the number of concurrent drags and it makes the ctypes signature a hidden global coupling.
- **Evidence:**
  ```python
  # core/api.py:983-986
  user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   ctypes.c_size_t, ctypes.c_ssize_t]
  user32.SendMessageW.restype = ctypes.c_ssize_t
  user32.SendMessageW(hwnd, 0x00A1, 2, lparam)
  ```
  ```python
  # core/snap_layouts.py:67-71 — the failure mode this mutation can reintroduce
  # LPARAM/WPARAM are pointer-sized. Without explicit argtypes ctypes coerces a
  # 64-bit lparam into a 32-bit C int ... "OverflowError: int too long to convert"
  ```
- **Reproduction / verification:** in a scratch harness, set `ctypes.windll.user32.SendMessageW.restype = ctypes.c_int` after `begin_window_drag` has run, then call it again with a high-bit LPARAM and observe the truncation/OverflowError. For the blocking behaviour: `time` the `begin_window_drag` bridge call against a manual drag.
- **Suggested fix:** configure `SendMessageW` once in a shared, platform module (e.g. `core/snap_layouts.py::_configure_user32`, which already owns the other user32 prototypes) and never mutate it at a call site; consider `PostMessage` instead of `SendMessage` for the drag initiation so the bridge thread is not pinned.
- **Fix side effects:** `PostMessage` returns immediately, so the "drag started" acknowledgement becomes optimistic — the frontend already treats `begin_window_drag` as fire-and-forget (`player.js:1105`), so the risk is low.
- **Discovered by:** B

---

### 3. Clean areas

- **URL scheme allowlist (`open_url` / `open_external_url`)** — `_is_ssrf_safe_url` rejects every scheme except `http`/`https`, so `file://`, UNC/`\\server\share`, `javascript:`, `data:`, `ms-msdt:`, `search-ms:` cannot reach `webbrowser.open`. The brief's "malicious track title → OS executes something" scenario has **no code path**: no UI file calls either method (verified by grep over `ui/web_new_v2/**`), and the only URL-taking bridge method in use (`import_external_playlist`) belongs to WN-07 and uses the same guard.
- **Contract #1 (`_emit` never on the UI thread) is respected by this area's code.** pywebview dispatches `minimized` / `restored` / `maximized` / `shown` / `resized` handlers on a **separate thread** (`webview/event.py:55-60`, `should_lock=False`), so `_on_minimized` / `_on_restored` never execute on the WinForms message-loop thread; `_emit`'s `evaluate_js` marshals correctly through `webview.Invoke`. `toggle_mini_player` deliberately does **not** emit (api.py:782-786) and `close()` emits only after the native hide.
- **`_change_maximized_state` is well built** — it uses WinForms state/bounds on the owning UI thread, records `_last_geometry` before maximizing, pins `MaximizedBounds` to the current monitor's working area, and restores the recorded bounds exactly. Its delegate body is wrapped in `try/except`, and the whole native step is deferred so the bridge answers first (api.py:1053-1095). `tests/test_window_maximize.py` pins this behaviour faithfully.
- **`_fit_window_content` correctness** — it compares the WebView2 control's bounds against `native.ClientRectangle` before assigning, so no redundant `Bounds` write when the size is unchanged, and it never recreates the WebView (`tests/test_window_maximize.py:90-97`).
- **`begin_window_resize` input validation** — the direction string is validated against a fixed map before any native call (api.py:994-998), the window must be neither maximized nor in mini mode, and `IsZoomed` is re-checked natively. The `WM_NCLBUTTONDOWN` + edge-code packing is correct (signed 16-bit halves, pointer-sized LPARAM).
- **`SnapLayouts` failure handling** — `install()` rolls the window style back if the subclass fails, keeps the callback alive if the WndProc rollback fails (never releasing a callback Windows may still call), and `uninstall()` restores the WndProc *before* dropping the callback reference. `_hit_test` uses a half-open grip interval so the edge pixels are not swallowed, and `set_button_rect` rejects non-finite / zero-size rectangles.
- **`_get_hwnd` never returns a wrong *type*** — every failure path returns `None` and every caller checks it before using it.

### 4. Coverage gaps

- **No runtime measurement of the resize storm.** The mechanism (one thread + one queued `BeginInvoke` per WM_SIZE) is proven statically, but the *magnitude* (threads/s, queue depth) was not measured — the GUI was not launched, per the ground rules. Confirming evidence needed: a thread counter during a 2 s drag.
- **DPI behaviour could not be exercised.** The audit machine reports `GetDpiForSystem() == 96` and `GetScaleFactorForDevice(0) == 100` (i.e. 100 % scaling), so pywebview's `scale_factor` is `1.0` here and F-WN-04-2/F-WN-04-3 are latent on this host. Confirming evidence needed: a host with 125/150 % scaling, or a run with a synthetic `scale_factor != 1`.
- **`GetScaleFactorForDevice(0)` semantics are unresolved.** The installed pywebview calls it with one argument although the documented prototype takes an out-parameter; on this machine the call returns `100` (the scale percentage) and the two-argument probe returned `hr=100, factor=0`. Whether it reports the *primary* device or device 0 of an enumeration, and whether it can fail on other systems, could not be established without a scaled/multi-monitor host.
- **`tests/test_player_layout_geometry.py` does not test window geometry at all.** It is a static CSS assertion file for `.player-2col-layout` / `.player-glass-card` radii in `ui/web_new_v2/css/components/player-view.css` — it pins nothing about mini-player size, work-area maths or DPI. It was listed in the brief as a window-geometry test; it provides **no** coverage of this area (false confidence if cited as such).
- **The tests in this area are structurally unable to catch the threading/lifecycle defects.** `tests/test_window_maximize.py:57-58` monkeypatches `_deferred_window_op` to run inline and `_on_window_ui_thread` to run inline, so the deferral, the cross-thread marshalling, the exception path and the timing are all bypassed. `tests/test_window_visibility.py:56-68` calls the visibility callbacks **from the test's main thread**, so it proves the `_MAIN_THREAD` branch of `_emit` works — it does **not** prove the real pywebview UI thread is protected (that thread is a .NET STA thread created in `webview/platforms/winforms.py:683-686` and is *not* `threading.main_thread()`; the guard happens to be safe today only because pywebview dispatches event handlers on their own threads). `tests/test_window_resize_api.py` stubs `ctypes.windll` wholesale. There is **no** test for `_get_scale_factor`, `_logical_workarea`, `_saved_pos_coords`, `_native_window_geometry`, `_enter_mini_mode` / `_exit_mini_mode` geometry round-trip, `_get_hwnd`, `close()` idempotency, or the Snap Layouts install/uninstall lifecycle.
- **The `js/events.js` consumer contract was not audited** (WN-28's area) — the impact statements about spoofed events assume the frontend dispatches on the event name without further validation, which was not verified.
- **No WN-03 cross-check of the SSRF cache interaction** was performed beyond reading `_dns_resolves_to_public_ip`; the DoH `getaddrinfo` patch in `main.py` was not traced in full.

---

### 5. Architecture improvements (ARCH)

- **ARCH-1 — Extract the platform layer.** `core/api.py` L514–1160 mixes bridge commands with Win32/ctypes/WinForms code: `_get_hwnd`, `_logical_workarea`, `_native_window_geometry`, `_set_native_window_corners`, `begin_window_drag`, `begin_window_resize` all inline `ctypes`/`System.*` calls, while `core/snap_layouts.py` already demonstrates the right shape (a self-contained, best-effort, Windows-only module with a documented failure policy). Moving the geometry/DPI code into a `core/window_geometry.py` (pure functions: `logical_workarea(scale)`, `saved_pos_coords(area, pos, w, h)`, `native_geometry(hwnd)`) would make the arithmetic unit-testable without a Windows host — which is exactly what the current tests cannot do.
- **ARCH-2 — One canonical coordinate space.** The layer currently mixes Win32 physical px, WinForms device-independent px and pywebview logical px with no explicit boundary. Declaring "all internal geometry is physical Win32 px; convert once at the pywebview `move()` boundary" (and expressing the scale factor as an explicit parameter rather than an implicit lookup) removes F-WN-04-2/F-WN-04-3 by construction and makes the DPI story reviewable in one place.
- **ARCH-3 — Split the bridge surface into "commands" and "lifecycle".** `AppApi` is exposed to JS wholesale (pywebview's `get_functions`), so lifecycle mutators (`shutdown`, `set_window`, `set_windows`, `cleanup`, `emit_event`) are reachable from the WebView. A dedicated, curated façade object (or an explicit `@bridge_command` allowlist) would remove the F-WN-04-12 / F-WN-04-13 exposure without touching the ~200 real API methods.
- **ARCH-4 — A single owner for window state.** `_is_maximized`, `_is_mini_active`, `_saved_mini_pos`, `_saved_main_geometry`, `_last_geometry` are a coherent state group spread across three threads. A small `WindowState` object with one lock and explicit transitions (`enter_mini`, `exit_mini`, `maximize`, `restore`) would satisfy AGENTS.md rule #2 structurally instead of by convention, and would make F-WN-04-8 (asynchronous completion reporting) natural to implement.
- **ARCH-5 — Asynchronous operations need completion events.** The bridge answered synchronously while the native work was deferred by 0.25 s, which is why the frontend's rollback path (main.js:196-203) can never fire. A small convention — "every deferred native operation emits `<op>_state` with `{ok: bool}`" — removes the optimistic/actual divergence across the whole area (`_enter_mini_mode`, `_exit_mini_mode`, `_change_maximized_state`, `set_mini_player_position`).
- **ARCH-6 — Native resources need an explicit owner with a teardown.** `SnapLayouts` (and its ctypes callback) is created in `_install_snap_layouts` and never released; `AppApi.shutdown()` is dead code. Introducing an explicit "native subsystem" registry on `AppApi` with `install()`/`uninstall()` pairs, driven from `AppApi.cleanup()` (which *is* on the exit path), makes the lifetime of the WndProc subclass a contract rather than an accident.
- **ARCH-7 — Throttle at the source, not at the consumer.** Because pywebview turns every WM_SIZE into a thread, the cheapest fix is to stop asking for a per-pixel event: subscribe to the size *only* when it changes (the size argument pywebview already provides is currently discarded) and coalesce the fit into a single pending UI-thread operation.
- **ARCH-8 — `close()` should be a state machine.** "Closing → tray-hidden → destroyed" is currently expressed as three independent side effects (`hide()`, `_on_minimized()`, a `threading.Timer` calling `destroy()`), none of them idempotent and none of them cancelling the other. A single `_closing` flag plus an ordered teardown list (cancel deferred ops → uninstall native subclass → hide/destroy → stop tray) would make close/shutdown reproducible and testable.
