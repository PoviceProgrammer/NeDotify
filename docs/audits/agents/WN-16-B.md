## AREA WN-16 — Tray, legacy asset routes, user-facing error mapping — ROLE B

### 1. Scope reviewed

**Files opened in full (or the cited ranges in full):**

- `core/tray.py` (1–194, whole file)
- `core/ui_assets.py` (1–22, whole file)
- `core/user_errors.py` (1–24, whole file)
- `core/api.py` — L24 (import), L355–459 (`__init__`, `_install_bridge_error_logging`, `cleanup`, `_offline_bridge_result`), L514–600 (`set_window`, `_install_snap_layouts`), L900–1030 (`close`, `close_window`, `minimize`, drag), L1215–1274 (`_on_track_changed`, `_on_audio_error`), L1325–1390 (`report_state`), L2315–2364 (`download_track`), L4170–4194 (`get_downloads`)
- `core/app.py` — L100–130 (`__init__`), L460–579 (`cleanup`)
- `main.py` — L300–379 (base_dir / `_MEIPASS` branch, window creation), L380–499 (`_install_routes`, route recompile, watchdog), L500–584 (shutdown path)
- `setup_pyinstaller.spec` (1–111, whole file)
- `installer.iss` — grep only (ship `dist\NeDotify.exe` only)
- `.venv_win/Lib/site-packages/pystray/__init__.py`, `_base.py`, `_win32.py` (lifecycle semantics of `Icon.run/stop/menu/__del__`)
- `.venv_win/Lib/site-packages/bottle.py` — `Router.match` (static-before-dynamic)
- `.venv_win/Lib/site-packages/webview/platforms/winforms.py`, `edgechromium.py` — `evaluate_js` / `show` / `restore` marshalling
- `ui/web_new_v2/index.html` L47–50 (stylesheet links), `ui/web_new_v2/js/events.js` L255–417, `js/player.js` L1000–1039, `js/feature-controls.js` L70–109, `js/downloads-view.js` L40, `js/utils.js` L1019–1038, `js/ui-style.js` (style switch)
- `core/settings.py` L63, L198–203 (`minimize_to_tray`, `interface.ui_style`)
- `core/proxy.py` L483–537 (token masking / fail-closed)
- Tests: `tests/test_macos_ui.py` (whole), `tests/test_ui_v2_independence.py` (whole), `tests/test_window_visibility.py` L88–130, `tests/test_build_and_brand.py` L380–391, `tests/test_listening_comparison.py` L40–64, `tests/test_repo_hygiene.py` (whole)
- `docs/UI_MACOS.md` L1–40; `ui/MACos_ui/**` (file inventory)

**Callees traced into other areas (defects there are attributed to their owner, not duplicated here):**

- `core/api.py` bridge error wrapper / raw `str(e)` returns → **WN-03 / WN-05 / WN-06 / WN-07 / WN-08 / WN-10** (bridge methods) and **WN-13** (`core/downloader.py`).
- `core/api.py::close()` / `minimize_to_tray` semantics → **WN-04**; `AppApi.cleanup()` / `AppCore.cleanup()` teardown order → **WN-01 / WN-02**.
- `ui/web_new_v2/js/events.js`, `js/feature-controls.js`, `js/downloads-view.js` rendering of error payloads → **WN-28**.
- `ui/MACos_ui/**` CSS content → **WN-33**.
- `core/proxy.py` auth/token → **WN-11**.
- `installer.iss` / PyInstaller `datas` → **WN-01** (only the tray-relevant icon/pack entries are reported here).

**Refutation of a premise in the brief (important):** `ui/MACos_ui/` is **not** a dead legacy pack and `install_macos_assets` is **not** dead code. The pack is a first-class, user-selectable interface style (`Settings → Appearance → Interface style → macOS`), backed by `interface.ui_style` / `interface.macos_mode` / `interface.macos_glass` (`core/settings.py:198–203`), toggled by `ui/web_new_v2/js/ui-style.js` (`document.documentElement.dataset.uiStyle === 'macos'`, read by `js/settings.js`, `js/particles.js`, `js/library.js`, `js/player.js`), and its stylesheets are linked unconditionally by the only UI document (`ui/web_new_v2/index.html:47–50`). Removing it (or its route) would leave the app unstyled for every user who selected that style. Details in §5.

---

### 2. Findings

#### F-WN-16-1  [P1] — The system tray is never started: the only `TrayIcon.start()` call sits after a `return` and is unreachable

- **File:** `core/api.py:571-575` (the dead call site); `core/tray.py:165-185` (the code that never runs); `core/api.py:924-938` (the user-visible consequence); `core/api.py:577-595` (a second dead block in the same method)
- **Confirmed:** yes
- **Description:** `AppApi._install_snap_layouts()` ends with `return False` on line 572. Everything after it — the `self._tray.start()` call and the native-window-icon thread — is unreachable. `core/api.py:575` is the **only** call site of `TrayIcon.start()` in the whole tree, so the tray icon is never created, the tray menu is never built, and `core/tray.py` (194 lines) is unreachable runtime code.
- **Cause:** a code block was appended to the end of a method that always returns, instead of being placed in the caller (`set_window()` / `__init__`). The defect exists in `HEAD` as well (`git show HEAD:core/api.py`), so it is long-standing, not a working-tree artefact.
- **Trigger conditions:** every launch, on every platform.
- **User impact:** (a) no tray icon, so the documented tray playback controls ("Decision 1/2/4" in `core/tray.py`) do not exist; (b) `general.minimize_to_tray` defaults to `True` (`core/settings.py:63`) but is a **no-op that closes the app instead** — `AppApi.close()` computes `tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)`; `TrayIcon.icon` is `None` because `start()` never ran, so the code falls through to `self._window.destroy()`; (c) the packaged app never sets its native window icon (the `_set_icon` block at `core/api.py:577-595` is dead too), so the window/taskbar entry uses the default icon.
- **Evidence:**
  ```python
  # core/api.py
  571:            logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
  572:            return False
  573:
  574:        if getattr(self, "_tray", None):
  575:            self._tray.start()
  ```
  ```python
  # core/api.py
  922:        minimize_to_tray = bool(self._core.settings.get("general", "minimize_to_tray", True))
  923:        tray_mgr = getattr(self, "_tray", None) or getattr(self._core, "tray", None)
  924:        tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)
  925:
  926:        if minimize_to_tray and tray_available:
  ```
- **Reproduction / verification:** AST scan of `core/api.py` (script `_verify_wn16.py`, §4 of its output) reports `UNREACHABLE start() at line 575 inside _install_snap_layouts() (return at line 572)`; a repo-wide AST scan for `_tray.start()` returns exactly `[('core/api.py', 575)]`. `TrayIcon.icon` is initialised to `None` (`core/tray.py:30`) and is only assigned inside `_run_tray` (`core/tray.py:177`), which is only reachable through `start()`.
- **Suggested fix:** move the two dead blocks out of `_install_snap_layouts()` into `AppApi.set_window()` (which already owns window wiring) and start the tray there; then re-check `AppApi.close()`'s `tray_available` probe (it must reflect a *running* icon, not just a non-`None` attribute).
- **Fix side effects:** this activates the whole tray for the first time, which turns the latent defects F-WN-16-2/3/4 into live ones, and it makes `minimize_to_tray` actually hide the window — the tray must be reliable before that switch is honoured. `tests/test_window_visibility.py:93-112` currently *fakes* `tray.icon = object()`, so it will keep passing and will not protect the real path.
- **Discovered by:** B

#### F-WN-16-2  [P2] — `TrayIcon.stop()` cannot stop an icon that has not reached pystray's "ready" state, and after one failed attempt the icon can never be stopped again

- **File:** `core/tray.py:187-194`; pystray `.venv_win/Lib/site-packages/pystray/_base.py:244-259`; `.venv_win/Lib/site-packages/pystray/_win32.py:113-134`
- **Confirmed:** yes (logic reproduced against pystray's own guard, see below)
- **Description:** `TrayIcon.start()` sets its own `_is_running = True` **before** `self.icon.run()` (`core/tray.py:178-179`), but pystray's own `_running` flag only becomes `True` inside `_mark_ready()`, which is reached from `_run()` once the Win32 message loop starts. pystray's `Icon.stop()` is guarded by `if self._running:` (`_base.py:249`), so a `stop()` that lands in that window **posts no `WM_STOP` at all** and the message loop keeps running. `TrayIcon.stop()` then sets its own `_is_running = False`, so the guard `if self.icon and self._is_running` makes every later `stop()` a no-op — the icon becomes unkillable for the lifetime of the process.
- **Cause:** the wrapper keeps a *duplicate* liveness flag with different semantics from the library's, and never re-checks it.
- **Trigger conditions:** `AppApi.cleanup()` (`core/api.py:449-452`) or the tray's own "Выход" (`core/tray.py:99-106`) calls `stop()` in the short window between `pystray.Icon(...)` being constructed and the icon's message loop becoming ready.
- **User impact:** a leftover tray icon that cannot be removed until the process dies; `AppApi.cleanup()` believes it released the tray. (Latent today — F-WN-16-1 means the icon is never created.)
- **Evidence:**
  ```python
  # core/tray.py
  177:                self.icon = pystray.Icon("NeDotify", img, "NeDotify", menu)
  178:                self._is_running = True
  179:                self.icon.run()
  ...
  187:    def stop(self):
  188:        """Stop system tray icon."""
  189:        if self.icon and self._is_running:
  190:            try:
  191:                self.icon.stop()
  ```
  ```python
  # pystray/_base.py
  244:    def stop(self):
  249:        if self._running:
  250:            self._stop()
  ```
- **Reproduction / verification:** `_verify_wn16.py` §3 replaces `pystray.Icon` with a stub that reproduces pystray's exact semantics (`_running` becomes `True` only in `_mark_ready()`): after `tray.stop()` the output is `pystray _running = False | stop() actually delivered = 0 | TrayIcon._is_running = False`, and a second `stop()` still delivers `0`.
- **Suggested fix:** do not keep a second liveness flag; drive shutdown off the icon's own state (or a `setup` callback that marks readiness), and make `stop()` idempotent and re-entrant (e.g. an internal `_stopped` flag that is set regardless of the outcome, plus a join of the tray thread with a timeout).
- **Fix side effects:** joining the tray thread is bounded by pystray's `SETUP_THREAD_TIMEOUT = 5.0`; pystray's `Icon.__del__` (`_win32.py:50-55`) already joins the icon thread **without a timeout**, so an explicit bounded join in `stop()` is safer than relying on GC.
- **Discovered by:** B

#### F-WN-16-3  [P2] — The native tray menu is rebuilt from a foreign thread: `icon.menu = …` destroys the `HMENU` the tray thread may currently be tracking

- **File:** `core/tray.py:140-163`; callers `core/api.py:1241-1242` and `core/api.py:1374-1375`; pystray `_base.py:160-163, 261-275` and `_win32.py:99-111, 203-224`
- **Confirmed:** yes for the cross-thread call; the crash/stuck-menu outcome is a hypothesis (missing evidence: a live run of the popup while a rebuild happens — impossible today because of F-WN-16-1)
- **Description:** `TrayIcon.update_state()` is invoked from the engine's track-changed callback thread (`core/api.py:1241-1242`, `_on_track_changed` runs on the background resolution thread) and from the bridge thread (`core/api.py:1374-1375`, `report_state`). It assigns `self.icon.menu = new_menu`, and pystray's `Icon.menu` setter calls `update_menu()` → `_win32.Icon._update_menu()`, which does `win32.DestroyMenu(hmenu)` and rebuilds the menu handle (`_win32.py:99-111`). Meanwhile the pystray thread may be inside `TrackPopupMenuEx(hmenu, …)` displaying that very menu (`_win32.py:215`). Destroying a menu handle that another thread is tracking is undefined behaviour. pystray itself only rebuilds the menu from the icon thread (`_base.Icon._handler` → `update_menu()` after each callback), so the app is violating the library's threading contract. `self._menu_handle` is also replaced without the lock the class otherwise uses.
- **Cause:** the wrapper treats the pystray `Icon` object as if it were a thread-safe value object; it is not — its native handles belong to the icon thread.
- **Trigger conditions:** the user opens the tray menu while a track change or a play/pause report arrives (≤1 Hz, so quite likely).
- **User impact:** the popup menu can vanish, fail to close, or crash the process; in the worst case an orphaned menu window.
- **Evidence:**
  ```python
  # core/tray.py
  158:            try:
  159:                new_menu = self._build_menu()
  160:                if new_menu and self.icon:
  161:                    self.icon.menu = new_menu
  ```
  ```python
  # pystray/_win32.py
   99:    def _update_menu(self):
  100:        try:
  101:            hmenu, callbacks = self._menu_handle
  102:            win32.DestroyMenu(hmenu)
  ```
- **Reproduction / verification:** to activate this, F-WN-16-1 must be fixed first; then right-click the tray icon and start a track. The code path is deterministic from the sources quoted above (caller thread ≠ pystray thread); no live reproduction was performed because the brief forbids running the real app.
- **Suggested fix:** marshal the menu rebuild onto the pystray thread (e.g. keep a pending-state slot and let pystray's own `update_menu()` path — or a small queue drained by the icon thread — apply it), and rebuild only the dynamic labels rather than the whole menu.
- **Fix side effects:** a hand-off queue adds a second synchronisation primitive; the class's existing `threading.Lock` (`core/tray.py:34`) must not be held while blocking on the icon thread (lock-ordering risk against F-WN-16-2's join).
- **Discovered by:** B

#### F-WN-16-4  [P2] — The 1 Hz throttle *drops* state updates instead of coalescing them, so the tray label can stay wrong indefinitely

- **File:** `core/tray.py:140-156`; callers `core/api.py:1241-1242` (`force=True`) and `core/api.py:1374-1375` (not forced)
- **Confirmed:** yes (logic); impact latent behind F-WN-16-1
- **Description:** `update_state()` returns **before** applying `_current_track` / `_is_playing` when the previous applied update was less than one second old. The throttle therefore conflates two different concerns — "how often may I rebuild the native menu" and "what is the current state" — and the state is lost, not deferred. `report_state()` is only called on a *state change*, so a dropped update is never re-sent.
- **Cause:** rate-limiting was applied to the wrong boundary (state application) instead of to the expensive part (menu rebuild).
- **Trigger conditions:** a `report_state('playing')` that arrives within 1 s of the forced track-change update (`core/api.py:1242`) — i.e. autoplay, or the user pausing immediately after a track change.
- **User impact:** the tray menu keeps showing "▶ Воспроизведение" while the track is playing, and shows "⏸ Пауза" while it is paused, until the next state change arrives.
- **Evidence:**
  ```python
  # core/tray.py
  147:        now = time.time()
  148:        if not force and (now - self._last_update_time < 1.0):
  149:            return
  150:
  151:        with self._lock:
  152:            if track is not None:
  153:                self._current_track = track
  154:            if is_playing is not None:
  155:                self._is_playing = bool(is_playing)
  ```
- **Reproduction / verification:** call `tray.update_state(track=t, force=True)` then `tray.update_state(is_playing=True)` within 1 s on a `TrayIcon` whose `icon` is truthy; `_is_playing` stays `False`. (The guard at `core/tray.py:144` also requires `self.icon` to be truthy, which is why this is currently unreachable.)
- **Suggested fix:** always apply the state under the lock; throttle only the `self.icon.menu = new_menu` assignment.
- **Fix side effects:** more frequent menu rebuilds — must be combined with F-WN-16-3's thread hand-off, otherwise the two fixes multiply the same Win32 hazard.
- **Discovered by:** B

#### F-WN-16-5  [P2] — `describe_error` copies the raw exception text into the user-facing `message` for `ValueError`/`TypeError` — the one branch that breaks the module's own contract

- **File:** `core/user_errors.py:21-22`; consumer `ui/web_new_v2/js/feature-controls.js:83-84`
- **Confirmed:** yes for the contract violation and the verbatim copy; **hypothesis** for the "an absolute path reaches it in production" part (see below)
- **Description:** the module's docstring promises *"Stable user-facing error categories without exposing provider internals"*, and nine of the ten branches honour that (constant strings). The `ValueError`/`TypeError` branch is the exception: it puts `str(error)[:240]` — the raw exception text — straight into the `message` field that the UI renders.
- **Cause:** the branch was written to surface a human-readable validation message, but it cannot distinguish a curated message from an incidental one (a path, a URL, a token-bearing proxy URL).
- **Trigger conditions:** any bridge method or worker that raises `ValueError`/`TypeError` (or a subclass such as `json.JSONDecodeError` / `UnicodeDecodeError`).
- **User impact:** an absolute path (`C:\Users\<name>\.nedotify\…`), a provider URL, or any other incidental detail is rendered in the operation-error panel (`feature-controls.js:84`: `message.textContent = detail.user_message || detail.message || …`) and therefore appears in screenshots / screen shares.
- **Evidence:**
  ```python
  # core/user_errors.py
  21:    if isinstance(error, (ValueError, TypeError)):
  22:        return {'code': 'invalid_input', 'title': 'Проверьте введённые данные', 'message': str(error)[:240] or 'Не удалось выполнить действие с этими параметрами.', 'action': None}
  ```
  Verified behaviour (`_verify_wn16.py` §1–2): `describe_error(ValueError("invalid literal for int() with base 10: 'C:\\Users\\artur\\.nedotify\\downloads\\a.mp3'"))` → `code=invalid_input`, `path_leak=True`, `message` contains the path verbatim. The same input as `FileNotFoundError` / `PermissionError` / plain `Exception` → `path_leak=False` (constant, safe messages).
- **Reproduction / verification:** run `_verify_wn16.py` §1–2. **Missing evidence for the production path leak:** no in-repo `raise ValueError(...)` site produces a path — they are all static messages (`core/api.py:2392`, `core/api.py:4134`, `services/smart_playlists.py:23-133`, `core/download_transfer.py:68-97`, `services/zapret_service.py:215-218`). The reachable producers are implicit `ValueError`s from `int()`/`float()`/`json`/`urllib` over user-supplied values, which echo *user input*, not paths. So the confirmed defect is the contract violation; a path leak is a latent risk that becomes real as soon as any code path raises a path-bearing `ValueError`.
- **Suggested fix:** never embed raw exception text. Use a fixed per-category message (and, if a detail is genuinely useful, redact it: strip drive letters, `\\Users\\…` prefixes and `?k=`-style tokens before truncating).
- **Fix side effects:** loses the "which input was wrong" hint for genuine validation errors; that hint should be re-introduced deliberately with an allow-list of user-facing messages rather than by echoing `str(e)`.
- **Discovered by:** B

#### F-WN-16-6  [P2] — The error-mapping layer is advisory, not a boundary: raw `str(e)` still crosses the bridge into the WebView, and the same failure is presented two different ways

- **File:** `core/user_errors.py` (module contract); `core/api.py:434-438`, `core/api.py:1255-1260`, `core/api.py:2331`, `core/api.py:2351`, `core/api.py:4176-4181`; `core/downloader.py:879-880`; `ui/web_new_v2/js/events.js:276-277`; `ui/web_new_v2/js/downloads-view.js:40`
- **Confirmed:** yes for the bypass and the divergent presentation; **hypothesis** for a concrete absolute path reaching the screen
- **Description:** `describe_error` is applied at exactly five places (`core/api.py:437`, `509`, `1258`, `4180`; `core/downloader.py:175`), while ≥30 bridge methods return the raw exception text directly: `core/api.py:990, 1030, 1795, 1805, 1817, 1836, 1851, 1900, 1954, 2414, 2496, 2511, 2568, 2596, 2603, 3100, 3291, 3534, 3816, 3838, 3858, 3865, 3874, 3908, 4000, 4019, 4095, 4108`. There is no enforcement point, so the "stable user-facing error categories" contract holds only where a developer remembered to call the helper.
- **Cause:** the module is a helper, not a boundary. Nothing prevents a new bridge method from returning `str(e)`, and nothing tests that the raw text is absent.
- **Trigger conditions:** any bridge method that fails with an exception whose message contains a path, a URL, or a provider payload.
- **User impact:** the same failure is rendered two ways — the *listing* is sanitised while the *live toast* is not:
  - `get_downloads()` (`core/api.py:4176-4181`) attaches the sanitised `user_error` (rendered by `downloads-view.js:40`) but still ships the raw `error` string in the same payload;
  - the `download_failed` events emitted directly by the bridge (`core/api.py:2331`, `2351`) carry **no `title`**, so `events.js:276-277` renders `"Ошибка скачивания: " + <raw str(e)>` verbatim in a toast;
  - `api_error` (`core/api.py:436`) embeds `f"{type(exc).__name__}: {exc}"` next to the sanitised fields, and `audio_error` (`core/api.py:1259`) **overrides** the sanitised `message` with `str(err)` (the sanitised copy survives only as `user_message`).
- **Evidence:**
  ```python
  # core/api.py
  434:                            inner_self._emit("api_error", {
  435:                                "method": method_name,
  436:                                "error": f"{type(exc).__name__}: {exc}",
  437:                                **describe_error(exc, method_name),
  438:                            })
  ```
  ```python
  # core/api.py
  1257:        err_msg = str(err)
  1258:        details = describe_error(err, 'playback')
  1259:        self._emit("audio_error", {**details, "message": err_msg, "user_message": details['message']})
  ```
  ```javascript
  // ui/web_new_v2/js/events.js
  276:                const dlErr = (data?.error || data?.message || 'Неизвестная ошибка').toString();
  277:                showToast(data?.title || ('Ошибка скачивания: ' + dlErr), 'error');
  ```
- **Reproduction / verification:** the divergence is deterministic from the quoted code: `{"track_id": 1, "error": "..."}` (no `title`) → `showToast('Ошибка скачивания: ...')`; `{"track_id": 1, "error": "...", "title": "Не удалось скачать трек", ...}` (the downloader's `_emit` adds `describe_error`, `core/downloader.py:174-175`) → the sanitised title is shown instead. **Missing evidence:** an in-repo exception whose message provably contains `C:\Users\…` on one of the raw paths. `core/downloader.py:879` (`str(e)` from the worker) is the most likely producer — yt-dlp/postprocessor messages routinely contain the destination path — but it was not reproduced here (network/ffmpeg, out of scope for this run).
- **Suggested fix:** make `describe_error` the single funnel — have the bridge decorator in `core/api.py:420-444` build **all** error payloads (`error` included) from it, have the `download_failed`/`audio_error` emitters use the same helper, and stop shipping the raw string to the UI at all (the full text belongs in `~/.nedotify/logs/app.log`, which already receives it).
- **Fix side effects:** the `error` field is part of the bridge payload contract; `ui/web_new_v2/js/events.js:276` and `js/utils.js:1019` read it, and at least one third-party/consumer script may. A migration must keep `error` populated (e.g. with the sanitised text) rather than removing the key.
- **Discovered by:** B

#### F-WN-16-7  [P3] — `icon.ico` is not in the PyInstaller `datas`, so every runtime `.ico` lookup fails inside the packaged exe

- **File:** `setup_pyinstaller.spec:27`, `setup_pyinstaller.spec:110`; `core/tray.py:37-45`; `core/api.py:590`
- **Confirmed:** yes
- **Description:** `extra_datas` bundles only `ui/web_new_v2` and `ui/MACos_ui`; `icon='icon.ico'` (spec line 110) sets the *executable's* icon and is **not** copied into `sys._MEIPASS`. Consequently `_MEIPASS/icon.ico` does not exist in the packaged build.
- **Cause:** the `.ico` is a build-time resource, not a runtime data file, but two runtime code paths look for it at runtime.
- **Trigger conditions:** running the packaged exe.
- **User impact:** `core/tray.py:37-45` handles this correctly — it probes `os.path.exists` and falls back to `_MEIPASS/ui/web_new_v2/assets/logo.png`, which **is** bundled, so the tray degrades gracefully. `core/api.py:590` does **not**: it builds the path from `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` with no `sys._MEIPASS` branch, so in a frozen build it resolves to a non-existent `_MEIPASS/icon.ico` and the native window icon is silently not set. (Today that line is unreachable — see F-WN-16-1 — so there is no current user impact.)
- **Evidence:**
  ```python
  # setup_pyinstaller.spec
  27: extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')] + collect_data_files('ytmusicapi')
  ...
  110:     icon='icon.ico',
  ```
  ```python
  # core/tray.py
  38:        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  39:        ico_path = os.path.join(base, "icon.ico")
  40:        if os.path.exists(ico_path):
  41:            return ico_path
  42:        png_path = os.path.join(base, "ui", "web_new_v2", "assets", "logo.png")
  ```
- **Reproduction / verification:** `_verify_wn16.py` §5 prints `icon.ico in setup_pyinstaller.spec datas: False` and shows the frozen resolution `C:\fake\meipass\icon.ico` (i.e. the code *asks* for a file the spec does not ship). `tests/test_ui_v2_independence.py:67-73` pins only the PNG fallback.
- **Suggested fix:** either add `('icon.ico', 'icon.ico')` to `extra_datas`, or make every runtime icon lookup use the same `_MEIPASS`-aware, existence-checked resolver as `core/tray.py` (i.e. share one helper — see §5).
- **Fix side effects:** adding `icon.ico` to `datas` grows the onefile payload by the icon size (tens of KB); sharing one resolver is free but touches `core/api.py` (WN-01/WN-04 overlap).
- **Discovered by:** B

#### F-WN-16-8  [P3] — The bundled macOS wallpaper (1.4 MB PNG) ships to every install, including users who never select that style

- **File:** `setup_pyinstaller.spec:27`; `ui/MACos_ui/assets/atmosphere-dusk.png` (1 424 752 bytes); `ui/MACos_ui/interface.css:11`
- **Confirmed:** yes
- **Description:** the whole `ui/MACos_ui` tree is copied into the onefile bundle. Its `assets/atmosphere-dusk.png` alone is 1.4 MB and is referenced from `ui/MACos_ui/interface.css:11` as the macOS backdrop — a style that is off by default (`interface.ui_style` defaults to `"current"`, `core/settings.py:198`).
- **Cause:** asset bundling is all-or-nothing; there is no size budget or lazy/on-demand delivery for the optional style.
- **Trigger conditions:** every build and every install.
- **User impact:** every installer is ~1.4 MB larger than needed, and the PyInstaller onefile extracts the wallpaper to a temp directory on every launch.
- **Evidence:**
  ```python
  # setup_pyinstaller.spec
  27: extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')] + collect_data_files('ytmusicapi')
  ```
  ```css
  /* ui/MACos_ui/interface.css */
  11: html[data-ui-style="macos"] #macos-backdrop { ... background-image: linear-gradient(...),url("assets/atmosphere-dusk.png"); ... }
  ```
  File inventory: `atmosphere-dusk.png` 1 424 752 B, `interface.css` 37 880 B, `settings.css` 18 835 B, `library.css` 11 254 B, `tokens.css` 4 512 B, `library-wave.svg` 1 114 B.
- **Reproduction / verification:** `Get-ChildItem -Recurse ui\MACos_ui -File | Select-Object Name,Length`.
- **Suggested fix:** re-encode the wallpaper (the backdrop is blurred and overlaid by a gradient, so a 1920×1080 WebP/JPEG at quality ~80 would be a fraction of the size), or ship it as an optional component.
- **Fix side effects:** a re-encode changes the visual output — `tools/visual_guard` (WN-35) should be re-run against the macOS style.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct — no finding:

- **`sys._MEIPASS` handling for the tray icon** (`core/tray.py:37-45`): both branches are present (rule #9), the source-tree branch resolves to the repo root, the frozen branch to `sys._MEIPASS`, and each candidate is existence-checked with a graceful fallback to the bundled `logo.png`. Verified by `_verify_wn16.py` §5 and pinned by `tests/test_ui_v2_independence.py:67-73`.
- **`core/ui_assets.py` frozen/source resolution**: the module takes `base_dir` from the caller, and `main.py:333-336` computes it with the dual `sys._MEIPASS` / `os.path.dirname(__file__)` branch, so both the source tree and the packaged exe resolve `ui/MACos_ui` correctly. Missing pack → `root.rglob('*')` yields nothing → no routes, no exception, no crash (graceful degradation).
- **Path traversal in the asset routes** (`core/ui_assets.py:11-14`): the `is_relative_to(root)` check plus the per-file literal route registration make traversal impossible by construction; the suffix allow-list (`{.css, .png, .svg, .woff2}`) prevents serving anything else. `tests/test_macos_ui.py:17-44` pins `../web_new_v2/index.html`, `../../core/settings.py` and `/etc/passwd` → 404.
- **Route precedence over pywebview's catch-all**: bottle's `Router.match` consults `self.static[...]` **before** the dynamic rules, so the literal `/MACos_ui/<file>` routes win over pywebview's `/<file:path>` regardless of insertion order; the `app.router.__init__()` recompile in `main.py:466-474` preserves them (they are not in `custom_callbacks`, so they land in `other_routes` and are re-added as static rules).
- **The tray thread does not block interpreter shutdown**: `core/tray.py:185` starts the thread with `daemon=True`, so it is not joined by `threading._shutdown()`.
- **No lock violation by the tray callbacks**: the pystray callbacks (`on_play_pause`, `on_next`, `on_prev`, `on_toggle_favorite`) only dispatch a `nedotify:tray_action` DOM event (`core/tray.py:59-97`); the frontend handler (`ui/web_new_v2/js/player.js:1010-1033`) then calls exactly the same bridge methods the UI buttons call (`api('next_track')`, `api('prev_track')`, `api('toggle_favorite')`). There is no second, lock-free path into the queue or the player state, so a tray action and a UI action cannot race on Python state — the AGENTS.md single-lock rule holds for this path.
- **No JavaScript injection through the tray**: the `action` values interpolated into the dispatched JS (`core/tray.py:64-68`) are string literals defined in the same module (`toggle_play`, `next`, `prev`, `toggle_like`); track titles/artists are only used as native menu text, never as code.
- **Cross-thread window calls from the tray thread are marshalled by pywebview**: `show()` / `restore()` / `hide()` / `minimize()` use `Control.Invoke` (`webview/platforms/winforms.py`), and `evaluate_js` marshals via `self.webview.Invoke(...)` (`webview/platforms/edgechromium.py`), so `core/tray.py:59-81` does not touch WinForms/WebView2 from the pystray thread.
- **`describe_error` never emits a stack trace**, and 9 of its 10 branches return a constant string. `FileNotFoundError`, `PermissionError`, generic `Exception` and `OSError(ENOSPC)` all map to fixed, path-free texts (verified, `_verify_wn16.py` §1).
- **The proxy auth token does not leak through the error paths**: `core/proxy.py:489` masks `?k=`/`?auth_token=` in every logged request line, the token is minted per session (`secrets.token_urlsafe(24)`, `core/proxy.py:1275`), compared with `hmac.compare_digest` (`core/proxy.py:511`), and an unset token fails closed (`core/proxy.py:504-506`). The rejection body carries no token value (`core/proxy.py:526`).
- **Tray menu rebuild frequency**: bounded to ≤1 Hz by `core/tray.py:148` and the pack has only 6 files, so `install_macos_assets` registers 6 routes — no measurable startup or runtime cost.

---

### 4. Coverage gaps

- **No GUI run.** Per the brief the real app was never launched. The tray's runtime behaviour (icon creation, popup, teardown) was derived from reading `pystray` 0.9.x sources (`_base.py`, `_win32.py`) and reproduced with a stub that mirrors pystray's readiness semantics — not by an end-to-end run. F-WN-16-2 is verified at the library-contract level, not by observing a leftover icon.
- **F-WN-16-1's user-visible impact on `minimize_to_tray`** was established by reading `core/api.py:922-938` and `core/settings.py:63`; it was not reproduced interactively.
- **"Does a path-bearing `ValueError`/`TypeError` occur in production?"** — not answered. Every in-repo `raise ValueError(...)` carries a static message; the reachable implicit producers echo user input. Confirming or refuting this needs either a runtime capture of `api_error`/`operation_error` payloads, or a decision to treat the branch as a defect on contract grounds (which is how it is reported here).
- **"Does a yt-dlp / ffmpeg error on the `download_failed` path contain the absolute download path?"** — not reproduced (network + ffmpeg, and it would write into the user's `~/.nedotify/downloads`).
- `installer.iss` was grepped only; whether the Inno Setup script prunes anything from the bundle was not fully reviewed (WN-01 owns it).
- The CSS content of `ui/MACos_ui/**` was not reviewed (WN-33 owns it); only its wiring, size and route mechanics were checked.
- `core/proxy.py` was read only at the token/authentication level; its own error responses (WN-11) were not audited.
- `tests/test_repo_hygiene.py` was read in full: it is a `.gitignore` test only (`git check-ignore` over generated trees) and pins **nothing** about the tray, the error mapping, or the asset routes.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — The "legacy CSS pack" label is wrong, and it is a load-bearing, user-facing feature.**
`ui/MACos_ui/` is documented as legacy in `AGENTS.md` ("The sole UI is `ui/web_new_v2/`. Legacy version flags and UI directory overrides are retired."), in `docs/audits/WIN_AUDIT_CONTEXT.md:21` and in the area map (`WN-33`: "legacy CSS pack"). The code says otherwise:
- `ui/web_new_v2/index.html:47-50` links `MACos_ui/tokens.css`, `interface.css`, `settings.css`, `library.css` **unconditionally**;
- `core/settings.py:198-203` defines `interface.ui_style` (`current`/`macos`), `macos_mode`, `macos_glass`, `macos_blur`, `macos_font_family`, `macos_font_size` — a first-class settings category with a UI picker (`js/ui-style.js`, `js/settings.js:618-632`);
- the frontend branches on `document.documentElement.dataset.uiStyle === 'macos'` in at least six modules (`js/settings.js`, `js/particles.js`, `js/library.js`, `js/player.js:2513`, `js/settings-view.js`, `js/ui-style.js`);
- `docs/UI_MACOS.md:3` documents the user path: "Настройки → Оформление → Стиль интерфейса → macOS".
Consequence: any cleanup driven by the "legacy" label (dropping `('ui/MACos_ui', 'ui/MACos_ui')` from `setup_pyinstaller.spec:27`, or removing `install_macos_assets`) silently strips the styling of every user who selected that style — the `<link>`s 404 and the app renders unstyled, with no error surfaced (`main.py:454-464` turns image 404s into a 1×1 PNG; a missing CSS simply does not apply). Recommend correcting the label in `AGENTS.md` / the audit brief and renaming the pack to reflect what it is (e.g. `ui/macos_style/`), or, if the style is in fact being retired, removing the *feature* (settings, JS branches, docs) rather than silently orphaning the CSS.

**ARCH-2 — One asset resolver instead of three ad-hoc path builders.**
Three different, mutually inconsistent ways of locating a runtime asset exist: `core/tray.py:38` (`getattr(sys, "_MEIPASS", …)` + existence probe), `core/api.py:590` (`__file__`-relative, **no** `_MEIPASS` branch → broken when frozen, see F-WN-16-7), and `main.py:333-336` (the correct dual branch, used for the HTML and the asset routes). A single `core/assets.py::resolve_asset(*parts)` helper with the dual branch + existence check would remove the whole class of "works in the source tree, silently missing in the exe" defects.

**ARCH-3 — `describe_error` should be a boundary, not a helper.**
Today it is opt-in (5 of ~200 bridge sites). Because the sanitisation is voluntary, the same failure is rendered two ways (F-WN-16-6). A single `AppApi._error_payload(exc, method)` used by the bridge decorator and by every `{"success": False, "error": …}` return would make the contract enforceable, and one test could then assert the invariant "no bridge error payload contains a home directory / drive path / `k=<token>`". A dedicated `tests/test_user_errors.py` is missing entirely — the only coverage is 5 parametrised cases in `tests/test_listening_comparison.py:53-64` (a misfiled home), and it never exercises the `ValueError`/`TypeError` branch (F-WN-16-5).

**ARCH-4 — The tray has no lifecycle owner.**
`AppCore.cleanup()` (`core/app.py:508-579`, the documented owner of resource teardown, WN-02) does not touch the tray; the tray is stopped only by `AppApi.cleanup()` (`core/api.py:446-452`), and that call is missing on one of the two exit paths — the startup-watchdog restart (`main.py:525-539`) calls `app_core.cleanup()` and then `os._exit(3)` without `api.cleanup()`. A native resource (the tray icon) should be owned by `AppCore` (the layer that owns lifecycle) and released in `AppCore.cleanup()`, so that every exit path releases it.

**ARCH-5 — The tray's native handle must be touched only from the tray thread.**
`core/tray.py` treats the pystray `Icon` as a plain object: `self.icon.menu = …` (`core/tray.py:161`), `self.icon.stop()` (`core/tray.py:191`) and `self.icon` reads (`core/tray.py:144`, `189`) are performed from arbitrary threads, while pystray owns a Win32 window class, an `HMENU` and a message loop on its own thread. A thin "tray agent" that owns the `Icon` and accepts commands over a `queue.Queue` (drained on the icon thread) would make the thread rule structural instead of a convention, and would fix F-WN-16-2 and F-WN-16-3 at once.

**ARCH-6 — The optional style's assets are a packaging liability without a budget.**
`ui/MACos_ui` is 1.49 MB, of which 1.42 MB is one wallpaper PNG that only matters when the macOS style is selected (F-WN-16-8). Because `install_macos_assets` registers a route per file at startup and the spec bundles the whole tree, the cost is paid by every user. A size budget in the spec (or a re-encode) would keep the optional style honest.
