## AREA WN-16 — Tray, legacy asset routes, user-facing error mapping — ROLE A

### 1. Scope reviewed

Files opened (path: line ranges actually read):

- `core/tray.py` — 1–194 (whole file; `class TrayIcon`, 167 non-empty lines)
- `core/ui_assets.py` — 1–22 (whole file; `install_macos_assets`)
- `core/user_errors.py` — 1–24 (whole file; `describe_error`)
- `core/api.py` — 24 (`import describe_error`), 370–589 (`__init__`, `_install_bridge_error_logging`, `cleanup`, `_offline_bridge_result`, `set_window`, `_install_snap_layouts`), 905–1014 (`close`, `close_window`, `begin_window_drag`), 1175–1404 (`_on_track_changed`, `_on_audio_error`, `report_state`), 1780–1959 (queue ops, `set_setting`, `yandex_device_auth`), 2294–2363 (`download_track`), 4155–4204 (`get_downloads`)
- `core/downloader.py` — 140–209 (`_emit`), 294–879 (failure/logging sites: 467, 697, 809–879)
- `core/app.py` — 500–579 (`cleanup`)
- `main.py` — 50–119 (`_capture_bottle_run`), 325–354 (`base_dir`/`_MEIPASS`), 370–584 (`_install_routes`, `_startup_watchdog`, shutdown)
- `ui/web_new_v2/js/events.js` — 60–189, 255–419 (`operation_error`, `download_failed`, `api_error`, `audio_error`)
- `ui/web_new_v2/js/feature-controls.js` — 50–135 (`runErrorAction`, `showOperationError`)
- `ui/web_new_v2/js/player.js` — 990–1059 (`nedotify:tray_action` listener), 2105–2174 (`api()` helper)
- `ui/web_new_v2/js/downloads-view.js` — 40 (`item.user_error?.message`)
- `ui/web_new_v2/index.html` — 47–50 (`MACos_ui/*.css` link tags)
- `ui/MACos_ui/library.css` — 60, 64; `ui/MACos_ui/interface.css` — 11 (`url()` references)
- `setup_pyinstaller.spec` — 1–110 (`extra_datas`, `icon='icon.ico'`)
- `tests/test_window_visibility.py` — 1–130; `tests/test_macos_ui.py` — 1–60; `tests/test_ui_v2_independence.py` — 1–73
- Third-party (installed, read-only): `pystray 0.19.5` `_base.py`, `_win32.py`, `_util/__init__.py`; `bottle 0.13.4` `Router.match/add`; `webview/http.py` (`BottleServer.start_server`)

Callees traced into other areas (root cause owned elsewhere, not re-reported here):

- `core/api.py::_install_snap_layouts` (WN-04, `core/api.py` L514–1160) — unreachable `self._tray.start()`.
- `core/api.py::close` (WN-04) — the "close to tray" gate depends on `TrayIcon.icon` being non-None.
- `main.py::_install_routes` / `_capture_bottle_run` (WN-01) — bottle route install + router recompile that `install_macos_assets` depends on.
- `core/downloader.py` (WN-13) — `_emit` maps download failures through `describe_error`.
- `core/database.py` (WN-12) — sqlite3 error taxonomy used by `describe_error`.
- `ui/web_new_v2/js/*` (WN-28/WN-30/WN-32) — the consumers of the error payload shape.

Verification harnesses used (scratch, outside the repo):
`%TEMP%\opencode\audit_reports\_probe_user_errors.py`, `%TEMP%\opencode\audit_reports\_probe_ui_assets.py` (both read-only against the repo; nothing in the repo tree was modified).

### 2. Findings

#### F-WN-16-1  [P1] — The system tray is never started: `TrayIcon.start()` is called only from unreachable dead code in `core/api.py`

- **File:** `core/api.py:571-575` (root cause, WN-04 range), `core/tray.py:165-185` (the never-invoked `start()`), `core/api.py:917-932` (`close()` — the close-to-tray gate)
- **Confirmed:** yes
- **Owning area:** WN-04 (the dead statement lives in `core/api.py`); reported here because it disables the entire WN-16 tray surface. Do not double-count in WN-04.
- **Description:** `AppApi._install_snap_layouts()` ends with `return False` on line 572; the two statements that follow it — `if getattr(self, "_tray", None): self._tray.start()` (574-575) and the whole `_set_icon()` thread block (577-597) — are unreachable. `TrayIcon.start()` has **no other call site in the whole repository**, so the pystray icon is never created and the native window icon is never applied.
- **Cause:** the block that starts the tray and sets the window icon was appended below an unconditional `return False` inside an unrelated helper (`_install_snap_layouts`) instead of being called from `set_window()` / `on_loaded()`.
- **Trigger conditions:** every application start — the code path is deterministic, not a race.
- **User impact:** (a) no tray icon at all — the tray menu (play/pause, next, prev, favourite, open, exit) is unreachable; (b) `general.minimize_to_tray` defaults to `True` (`core/settings.py:63`) but `AppApi.close()` only hides the window when a live tray icon exists (`tray_available = bool(tray_mgr and hasattr(tray_mgr, "icon") and tray_mgr.icon)`, `core/api.py:924`), so closing the window **quits the app** instead of minimising to the tray — the setting is a silent no-op; (c) the frameless window shows the default WebView2 icon instead of `icon.ico`.
- **Evidence:**
  ```python
  # core/api.py:571-577
          logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
          return False

          if getattr(self, "_tray", None):
              self._tray.start()

          try:
              import threading
              def _set_icon():
  ```
  AST scan of `core/api.py` (statements after a `return` in the same function body):
  ```
  _install_snap_layouts: line 572 return -> unreachable stmt at line 574: If(test=Call(func=Name(id='getattr'...
  ```
  Repo-wide grep for a tray start call: the only hit is `core/api.py:575` (`self._tray.start()`); `core/tray.py:165` (`def start`) is never invoked. `core/app.py` and `main.py` contain no tray start at all.
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -c "import ast;t=ast.parse(open('core/api.py',encoding='utf-8').read());[print(f.name,st.lineno) for n in ast.walk(t) if isinstance(n,ast.FunctionDef) for i,st in enumerate(n.body[:-1]) if isinstance(st,ast.Return)]"` → `_install_snap_layouts 572`; then `Select-String -Path core\*.py,main.py -Pattern "\.start\(\)"` shows the tray start only at the unreachable line. `tests/test_window_visibility.py:93-113` builds `TrayIcon.__new__(TrayIcon)` and sets `tray.icon = object()` by hand, so the suite never exercises `start()` and stays green.
- **Suggested fix:** move the tray start into its own method (e.g. `_start_tray()`) and call it from `set_window()` or `on_loaded()`; move the `_set_icon` block into the same place.
- **Fix side effects:** once the tray actually runs, F-WN-16-2 (cross-thread menu swap) and F-WN-16-9 (stop-before-start race) become live; fix or re-verify them in the same change.
- **Discovered by:** A

#### F-WN-16-2  [P1] — `icon.menu` is replaced from the bridge thread while pystray's message loop owns the Win32 menu handle (use-after-destroy)

- **File:** `core/tray.py:140-163` (`update_state`, assignment at 161), `core/tray.py:108-138` (`_build_menu`)
- **Confirmed:** yes (code-level race is certain; the crash manifestation is a hypothesis — it cannot be observed today only because F-WN-16-1 prevents the tray from starting)
- **Description:** `update_state()` is invoked from the bridge/engine thread (`core/api.py:1241-1242` `_on_track_changed` and `core/api.py:1374-1375` `report_state`), never from the `TrayThread`. It assigns `self.icon.menu = new_menu`. In pystray 0.19.5 that setter is `self._menu = value; self.update_menu()` → `_win32.Icon._update_menu()`, which does `win32.DestroyMenu(hmenu)` and then creates a brand-new `HMENU`, replacing `self._menu_handle`. Meanwhile the `TrayThread` may be inside `TrackPopupMenuEx(hmenu, ...)` using exactly the handle the other thread destroyed.
- **Cause:** pystray's Win32 backend keeps OS menu handles that are only safe to create/destroy on the thread running its message loop; the tray code mutates pystray state from a foreign thread with no hand-off.
- **Trigger conditions:** the user opens the tray menu at the same moment a track change (`_on_track_changed`, `force=True`) or a play/pause state change (`report_state`) arrives — i.e. exactly when the menu is being rendered.
- **User impact:** an access-violation crash of the whole app process (a crash loses the session mid-playback), or a popup menu that shows stale/garbled entries. `_menu_handle` is also read/written without any synchronisation.
- **Evidence:** installed pystray source —
  ```python
  # pystray/_base.py
      @menu.setter
      def menu(self, value):
          self._menu = value
          self.update_menu()
  # pystray/_win32.py
      def _update_menu(self):
          try:
              hmenu, callbacks = self._menu_handle
              win32.DestroyMenu(hmenu)          # <-- handle freed here
          except:
              pass
          ...
          hmenu = self._create_menu(self.menu, callbacks)
          self._menu_handle = (hmenu, callbacks)
  # pystray/_win32.py  (tray thread)
          hmenu, descriptors = self._menu_handle
          index = win32.TrackPopupMenuEx(hmenu, ...)
  ```
  and in the app: `core/tray.py:161` `self.icon.menu = new_menu` executed on the bridge thread.
- **Reproduction / verification:** unit-level: create a `TrayIcon`, stub `self.icon` with an object whose `menu` setter records the calling thread, then call `update_state(track={...}, force=True)` from a non-tray thread and assert the setter runs on that thread. Live-level (after fixing F-WN-16-1): open the tray menu repeatedly while tracks change; a crash in `TrackPopupMenuEx`/`DestroyMenu` is the expected signature.
- **Suggested fix:** marshal the menu swap onto the pystray thread (e.g. push the new `Menu` into a `queue.Queue` drained by the tray thread's own loop, or use pystray's `run_detached`/setup-callback thread and rebuild the menu there); alternatively rebuild the menu only from the tray thread and keep the state under `self._lock`.
- **Fix side effects:** the menu rebuild is then asynchronous (up to one queue-hop later); the 1/s throttle must be preserved so the queue cannot grow without bound.
- **Discovered by:** A

#### F-WN-16-3  [P2] — `update_state()` drops the play/pause state instead of deferring it: the throttle returns before the state is applied

- **File:** `core/tray.py:140-163` (throttle at 148-149, state assignment at 151-156)
- **Confirmed:** yes
- **Description:** the 1-second throttle check happens **before** the state is written under the lock, so a throttled call is discarded entirely — `_is_playing` is never updated. `update_state(track=..., force=True)` from `_on_track_changed` sets `_last_update_time = now`; the frontend then reports `'playing'` a few milliseconds later through `report_state` → `update_state(is_playing=True)` (no `force`) → throttled → dropped.
- **Cause:** throttle and state mutation are the same code path; the throttle guards the *menu rebuild*, but it also gates the *state update*.
- **Trigger conditions:** starting playback (or pausing) within one second of the previous tray update — the normal case, because the track-change event always precedes the `'playing'` report.
- **User impact:** the tray menu shows "▶ Воспроизведение" (and the status line "⏸" only for the title prefix) while the track is actually playing; the label only corrects itself after the next state report that lands more than a second later. A user who opens the tray right after pressing play is told to press "play" on an already-playing track.
- **Evidence:**
  ```python
  # core/tray.py:147-156
          now = time.time()
          if not force and (now - self._last_update_time < 1.0):
              return                      # <-- state update lost, not deferred

          with self._lock:
              if track is not None:
                  self._current_track = track
              if is_playing is not None:
                  self._is_playing = bool(is_playing)
  ```
  call order: `core/api.py:1240-1242` (`update_state(track=track_copy, force=True)`) → `core/api.py:1373-1375` (`update_state(is_playing=(state == "playing"))`, no force).
- **Reproduction / verification:** `tray = TrayIcon.__new__(TrayIcon); tray._is_running = True; tray.icon = object(); tray._lock = threading.Lock(); tray._current_track = None; tray._is_playing = False; tray.update_state(track={'title':'x'}, force=True); tray.update_state(is_playing=True); print(tray._is_playing)` → prints `False` although the track is playing.
- **Suggested fix:** always apply `track` / `is_playing` under the lock; apply the 1/s throttle only to the *menu rebuild* (or keep a "pending rebuild" flag).
- **Fix side effects:** the rebuild may then happen more than once per second; cap the rebuild rate separately from the state update.
- **Discovered by:** A

#### F-WN-16-4  [P2] — `describe_error` is bypassed at ~30 bridge call sites: raw exception text (incl. local paths) is returned to and displayed by the UI

- **File:** `core/user_errors.py:1-24` (the mapping that is bypassed), `core/api.py` (the bypass sites, listed below)
- **Confirmed:** yes
- **Description:** `describe_error` exists to turn an exception into a stable, user-facing category ("Stable user-facing error categories without exposing provider internals", `core/user_errors.py:1`), but it is used at only **5** call sites: `core/api.py:437` (bridge wrapper), `core/api.py:509` (offline stub), `core/api.py:1258` (audio error), `core/api.py:4180` (downloads list), `core/downloader.py:175` (download_failed). Every other error path returns the raw `str(e)`:
  `core/api.py:990, 1030, 1795, 1805, 1817, 1836, 1851, 1900, 1954, 2331, 2351, 2414, 2496, 2511, 2568, 2596, 2603, 3100, 3291, 3534, 3816, 3838, 3858, 3865, 3874, 3908, 4000, 4019, 4095, 4108`.
  The frontend renders those strings verbatim, e.g. `js/library.js:195` (`res?.error || 'Не удалось импортировать плейлист'`), `js/library-view.js:162`, `js/utils.js:1493` (tag save), `js/settings.js:271` (cache quota), `js/settings.js:3336` (duplicate delete), `js/queue.js:109,205`, `js/smart-playlists.js:122,170`, `js/library.js:472,506`.
  Worst case is the **inconsistent duplicate of the same event**: the downloader worker path (`core/downloader.py:175`) maps the failure through `describe_error` and emits `download_failed` with `title`/`message`/`action`, while the bridge-side failure path emits the same event **without** any mapping — `core/api.py:2331` `self._emit("download_failed", {"track_id": None, "error": str(e)})` and `core/api.py:2351` (same for the queueing failure). `js/events.js:276-277` then renders it as `'Ошибка скачивания: ' + <raw exception>`.
- **Cause:** the mapping was applied per call site instead of at the boundary; the `_install_bridge_error_logging` wrapper (`core/api.py:401-444`) already centralises every bridge exception but only emits the mapped payload — methods that catch their own exceptions and return `{"success": False, "error": str(e)}` never reach it.
- **Trigger conditions:** any bridge method whose internals raise — e.g. a mutagen/OS error while saving tags (`core/api.py:4000`) or exporting a playlist (`core/api.py:2496`) puts an absolute path such as `C:\Users\<name>\Music\...` into the returned `error`.
- **User impact:** the user sees internal text (absolute local paths, SQL fragments, yt-dlp/requests internals) instead of a stable Russian message; the same failure is presented in two different formats depending on which layer raised it.
- **Evidence:**
  ```python
  # core/api.py:2328-2334
              logger.error(f"download_track: failed to persist track: {e}")
              try:
                  self._emit("download_failed", {"track_id": None, "error": str(e)})
  # core/downloader.py:174-175  (the mapped sibling of the same event)
              if event_name == 'download_failed' and isinstance(data, dict):
                  data = dict(data, **describe_error(data.get('error'), 'download'), method='download_track')
  # js/events.js:276-277
                  const dlErr = (data?.error || data?.message || 'Неизвестная ошибка').toString();
                  showToast(data?.title || ('Ошибка скачивания: ' + dlErr), 'error');
  ```
- **Reproduction / verification:** `Select-String -Path core\api.py -Pattern '"error": str\(|str\(e\)\}'` → 30 hits; each named method's `error` key is rendered by the JS lines quoted above. Concrete: make `core/database.py.add_track` raise `sqlite3.OperationalError("database is locked")` during a download → the user gets a toast with the raw SQLite text instead of the mapped "Не удалось скачать трек / Попробуйте ещё раз…".
- **Suggested fix:** map at the boundary — in the `_install_bridge_error_logging` wrapper and/or by replacing the `str(e)` returns with `describe_error(e, method_name)['message']` (+ `code`/`title`/`action`); map the two `core/api.py` `download_failed` emissions the same way `core/downloader.py:175` does.
- **Fix side effects:** the frontend reads `result.error` in ~15 places, so either keep the mapped text in the `error` key or update all readers; the zapret methods (`core/api.py:3816-3874`) are owned by WN-26 and would need a separate change.
- **Discovered by:** A

#### F-WN-16-5  [P2] — `describe_error` puts the raw exception text (and local paths) into the user-facing `message` for `ValueError`/`TypeError`

- **File:** `core/user_errors.py:21-22`, `ui/web_new_v2/js/feature-controls.js:84`, `ui/web_new_v2/js/events.js:335-341`
- **Confirmed:** yes
- **Description:** the `invalid_input` branch returns `'message': str(error)[:240]`. The frontend error panel renders `detail.user_message || detail.message`; `api_error` payloads (produced by `core/api.py:434-438`) carry **no** `user_message` — they only spread `describe_error(...)` — so `detail.message` (the raw exception text) is what the user reads.
- **Cause:** the mapping treats "the user typed something wrong" and "the backend threw an internal error" as the same category and reuses the exception text as the message.
- **Trigger conditions:** any `ValueError`/`TypeError` reaching the bridge wrapper or a `describe_error` call with a real exception object — e.g. a `ValueError` carrying an absolute file path.
- **User impact:** the error panel and the toast show internal text such as `Invalid audio file: C:\Users\<name>\AppData\...\secret.mp3`, disclosing the user's local directory layout (and any ID/URL embedded in the exception) in the UI.
- **Evidence:**
  ```python
  # core/user_errors.py:21-22
      if isinstance(error, (ValueError, TypeError)):
          return {'code': 'invalid_input', 'title': 'Проверьте введённые данные', 'message': str(error)[:240] or '...', 'action': None}
  # js/feature-controls.js:83-84
      title.textContent = detail.title || 'Не удалось выполнить действие';
      message.textContent = detail.user_message || detail.message || 'Попробуйте ещё раз или проверьте подключение к сети.';
  ```
  Probe output (`describe_error(ValueError(r"Invalid audio file: C:\Users\Bob\AppData\Roaming\NeDotify\secret.mp3"))`):
  ```
  ValueError(path leak)   -> code=invalid_input  action=None
                             message='Invalid audio file: C:\\Users\\Bob\\AppData\\Roaming\\NeDotify\\secret.mp3'
  ```
- **Reproduction / verification:** run the probe script `%TEMP%\opencode\audit_reports\_probe_user_errors.py` (it prints the mapping for 22 representative exceptions).
- **Suggested fix:** return a fixed Russian message for `invalid_input` (the concrete field name may be extracted, the raw text must not be); keep the raw text in the log only — `core/api.py:429-432` already logs `exc_info=True`.
- **Fix side effects:** users lose the specific detail in the panel; keep the exception text in the log line so support can still see it.
- **Discovered by:** A

#### F-WN-16-6  [P3] — `describe_error` has no `sqlite3.Error`/`KeyError` branch, and the keyword checks run before the type checks

- **File:** `core/user_errors.py:6-24`
- **Confirmed:** yes
- **Description:** (a) `sqlite3.Error` is not mapped at all: `sqlite3.OperationalError("database is locked")`, `sqlite3.IntegrityError("UNIQUE constraint failed: tracks.title")` and `sqlite3.OperationalError("unable to open database file")` all fall through to `code='unexpected'`, `action='retry'` — a "Повторить" button for a database error. (b) `KeyError` (the most likely exception for a malformed payload) is likewise unmapped; `str(KeyError('x'))` is `"'x'"`, so the `invalid_input` branch cannot be reused verbatim. (c) The keyword heuristics run **before** the type checks, so a `ValueError`/`TypeError` whose text contains `connection`, `404`, `offline`, `ssl`… is classified by keyword instead of as `invalid_input` (e.g. `ValueError("Invalid connection id")` → `code='network'`).
- **Cause:** the mapping is a flat list of substring heuristics with type checks only for two exception classes, and no branch for the storage layer.
- **Trigger conditions:** any database error inside a bridge call (the DB is a WAL SQLite file under `~/.nedotify/`), or a malformed payload.
- **User impact:** a wrong category and a misleading action button ("Повторить" for a locked database); no crash, no data loss.
- **Evidence:** probe output —
  ```
  sqlite3.OperationalError(locked)      -> code=unexpected     action=retry
  sqlite3.IntegrityError                -> code=unexpected     action=retry
  sqlite3.OperationalError(no db file)  -> code=unexpected     action=retry
  KeyError('title')                     -> code=unexpected     action=retry
  ```
  and `core/user_errors.py:21` — the `isinstance(error, (ValueError, TypeError))` branch sits **after** all the keyword branches (lines 9-20).
- **Reproduction / verification:** the probe script above; the classification order is visible directly in `core/user_errors.py:9-22`.
- **Suggested fix:** add explicit branches for `sqlite3.Error` (e.g. `code='storage'`, no retry action) and for `KeyError`/`IndexError`; move the type checks before the substring heuristics.
- **Fix side effects:** reordering the type checks changes the classification of exceptions whose text contains keywords — each existing mapping should be re-checked (the probe script is the regression harness).
- **Discovered by:** A

#### F-WN-16-7  [P3] — The tray's favourite entry never reflects the real state (`is_favorite` is not part of the track payload) and is not refreshed after a tray toggle

- **File:** `core/tray.py:119-120` (`is_fav = bool(self._current_track.get('is_favorite', False))`), `core/tray.py:95-97` (`on_toggle_favorite` → `_dispatch_js("toggle_like")`), `core/api.py:2615-2628` (`toggle_favorite` returns `is_favorite`)
- **Confirmed:** hypothesis (the track dict that reaches the tray comes from the frontend/provider payload, which does not carry the DB column `is_favorite`)
- **Description:** `_build_menu` decides between "❤️ В любимые" and "💔 Удалить из любимых" from `self._current_track.get('is_favorite')`. `AppApi._on_track_changed` copies the engine/queue track dict (`core/api.py:1200` `track_copy = dict(track)`); `audio/queue.py` stores the dicts it receives and nothing in `audio/` adds `is_favorite` (grep over `audio/` finds none) — the flag exists only as a DB column (`core/database.py:236`) and as the return value of `toggle_favorite` (`core/api.py:2628`). In addition, `on_toggle_favorite` only dispatches a JS event and never refreshes the tray state, so the label stays stale until the next track change.
- **Cause:** the tray derives UI state from a payload field the backend does not maintain.
- **Trigger conditions:** playing any track that is already in the favourites.
- **User impact:** the tray menu offers "В любимые" for a track that is already a favourite, and the entry does not flip after the user adds/removes the favourite from the tray.
- **Evidence:** `core/tray.py:119` `is_fav = bool(self._current_track.get('is_favorite', False))`; `grep -n "is_favorite" audio/*.py` → no match; `core/api.py:2628` `result = {"success": True, "is_favorite": status}` (the flag exists only in the toggle response).
- **Reproduction / verification:** play a favourite track, open the tray menu → the entry reads "❤️ В любимые". Confirm the payload empirically by logging `track_copy` in `_on_track_changed` (the flag's absence is the missing evidence that would close the hypothesis).
- **Suggested fix:** have the backend put the favourite state into the track payload it publishes (`_on_track_changed`) or query it, and refresh the tray state after `toggle_favorite` succeeds.
- **Fix side effects:** an extra DB read per track change; the tray update path must then be thread-safe (see F-WN-16-2).
- **Discovered by:** A

#### F-WN-16-8  [P3] — `TrayIcon.stop()` is a no-op when it is called before the tray thread has created the icon → a tray icon can outlive the app

- **File:** `core/tray.py:187-194` (`stop`), `core/tray.py:171-185` (`_run_tray` / `start`)
- **Confirmed:** hypothesis (the race window is real in the code; triggering it needs the app to exit within milliseconds of the tray start)
- **Description:** `stop()` requires **both** `self.icon` and `self._is_running`, and both are set only inside `_run_tray` on the `TrayThread` (`core/tray.py:177-178`). A `stop()` that arrives before the thread reaches line 177 is silently dropped — no "stop requested" flag exists — and the thread then creates and runs the icon anyway. `AppApi.cleanup()` (`core/api.py:449-450`) is the only exit-time stop, and it runs after `AppCore.cleanup()` (`main.py:575-577`), i.e. seconds into the teardown.
- **Cause:** `stop()` does not record the intent; it only inspects the current state of two fields owned by another thread.
- **Trigger conditions:** the app is closed within the first few milliseconds after the tray is started (fast start + immediate quit), or the tray thread is delayed by GIL/scheduling pressure.
- **User impact:** a stale tray icon is left in the notification area after the app has exited (it disappears only when the user hovers over it or Explorer restarts), and the "Выход" menu entry appears to do nothing.
- **Evidence:**
  ```python
  # core/tray.py:187-194
      def stop(self):
          """Stop system tray icon."""
          if self.icon and self._is_running:
              try:
                  self.icon.stop()
              except Exception:
                  pass
              self._is_running = False
  # core/tray.py:177-178  (on TrayThread)
                  self.icon = pystray.Icon("NeDotify", img, "NeDotify", menu)
                  self._is_running = True
  ```
- **Reproduction / verification:** unit-level: `tray = TrayIcon(api); tray.stop(); tray.start()` → the icon is still created (patch `_run_tray` with a `time.sleep(0.05)` before `pystray.Icon(...)` and call `stop()` during that window to make it deterministic).
- **Suggested fix:** set a `self._stop_requested` flag in `stop()` and check it in `_run_tray` before creating the icon; call `self.icon.stop()` unconditionally when an icon object exists (pystray's own `stop()` already no-ops when not running).
- **Fix side effects:** none; pystray's `Icon.stop()` handles the "not running" case.
- **Discovered by:** A

### 3. Clean areas

- **`core/ui_assets.py` — clean.** `install_macos_assets()` is **not** dead code: `ui/web_new_v2/index.html:47-50` links `MACos_ui/tokens.css`, `interface.css`, `settings.css`, `library.css` unconditionally, so the pack is load-bearing for every user. Verified end-to-end with a WSGI probe that reproduces `main.py`'s exact registration order *and* its router recompile (`core/api.py`/`main.py:466-476`): all four stylesheets, `assets/library-wave.svg` and `assets/atmosphere-dusk.png` return **200** with the correct MIME types; `/MACos_ui/missing.css` and `/MACos_ui/../web_new_v2/index.html` return **404** (the `is_relative_to` + suffix guard in `core/ui_assets.py:12` holds; no path traversal). Bottle 0.13.4's `Router.match` checks `self.static` **before** the dynamic routes, so the exact `/MACos_ui/<file>` rules win over pywebview's `/<file:path>` catch-all — confirmed by probe (`static-before-dynamic: (200, b'EXACT')`), and the comment at `core/ui_assets.py:16-18` is accurate. The packaged-exe path is correct: `main.py:333-336` passes `base_dir = sys._MEIPASS`, and `setup_pyinstaller.spec:27` bundles `('ui/MACos_ui', 'ui/MACos_ui')`. A **missing** pack directory does not raise — `Path.rglob` on a non-existent directory yields nothing (probe: "no exception; routes: 0"), so the route installer degrades silently instead of breaking startup.
- **Tray icon resource loading honours contract #9** (`core/tray.py:38`): both the frozen (`sys._MEIPASS`) and source (repo root) branches are present. In the packaged exe `icon.ico` is *not* in `extra_datas`, so the fallback `ui/web_new_v2/assets/logo.png` (318 KB, RGBA 736×735) is used — it is bundled and pystray's Win32 backend converts it through `serialized_image(image, 'ICO')` → `image.save(f, format='ICO')`, which handles large sources by downscaling to the standard ICO sizes.
- **A missing icon cannot break startup** (`core/tray.py:13-19, 47-57`): the `pystray`/`PIL` import is guarded, `create_image()` falls back to a generated 64×64 RGBA pixel grid, and `TrayIcon.__init__` only calls `os.path.exists`.
- **The tray menu actions are wired to real endpoints**: `on_play_pause`→`toggle_play`, `on_next`→`next`, `on_prev`→`prev`, `on_toggle_favorite`→`toggle_like` (`core/tray.py:83-97`) are consumed by `ui/web_new_v2/js/player.js:1010-1033`, which calls `togglePlayPause()` (`js/player.js:859`), `api('next_track')`/`api('prev_track')` (`core/api.py:1761,1767`) and `api('toggle_favorite', currentTrack)` (`core/api.py:2615`) — all exist. A left-click on the tray icon restores the window because the status item is registered with `default=True` (`core/tray.py:128`) and pystray's `Icon.__call__` invokes the default menu item.
- **`TrayIcon.stop()` is called on app exit**: `AppApi.cleanup()` (`core/api.py:446-452`, `cleanup` is in `_UNWRAPPED`, so it is never wrapped) is invoked from `main.py:576-579` after the webview loop ends; `AppCore.cleanup()` (`core/app.py:508-560`) isolates every step in `_step()` and therefore cannot abort the sequence (with the F-WN-16-8 race window as the only exception).
- **`describe_error` output shape matches the frontend contract**: `{'code','title','message','action'}` — `js/feature-controls.js:83-87` consumes `title`, `message`/`user_message` and `action` (its label table `online|storage|library|search|retry` exactly matches the actions `describe_error` can emit), and `js/downloads-view.js:40` consumes `user_error.message`.
- **`describe_error` covers the provider/network families**: probe results — `requests.ConnectionError`/`ReadTimeout` → `network`; `requests.HTTPError` 403/404 → `unavailable`; `yt_dlp.utils.DownloadError("Video unavailable")` → `unavailable`; `"Private video"` → `unavailable`; `"Requested format is not available"` → `unavailable`; `OSError(ENOSPC)` → `disk_full`; `FileNotFoundError` → `file_missing`; `PermissionError` → `permission`; `"offline"` → `offline`. Unknown exceptions become the generic `code='unexpected'` message ("Подробности сохранены в журнале приложения").
- **The original error is preserved for the log at every mapped site**: the bridge wrapper logs `logger.error(..., exc_info=True)` (`core/api.py:429-432`), the downloader logs `logger.error(f'Download worker failed for {track_id}: {err_msg}')` (`core/downloader.py:848,866`) before emitting `download_failed`, and `get_downloads` keeps the raw text in `item['error']` next to the mapped `item['user_error']` (`core/api.py:4176-4181`).

### 4. Coverage gaps

- **No live run.** Per the ground rules the real app was not started, so the pystray behaviour (F-WN-16-2's crash, F-WN-16-8's stale icon, the actual Windows notification-area behaviour of the menu) is reasoned from the installed pystray 0.19.5 source plus unit-level probes, not observed. A live confirmation of F-WN-16-2 needs the tray actually running, i.e. after F-WN-16-1 is fixed.
- **`describe_error` was probed with 22 representative exceptions**, not with an exhaustive corpus of the provider/yt-dlp/requests messages the app can raise; the keyword heuristics may still misclassify untested phrasings (the substring list at `core/user_errors.py:9-20` is open-ended).
- **The `is_favorite` payload question (F-WN-16-7) is a hypothesis**: confirming it requires logging the real `track_copy` produced by the engine/queue during playback, which needs a running app; static analysis shows the flag is absent from `audio/` and from the provider track payloads.
- **Other areas' error paths were not audited in depth** — the ~30 bypass sites listed in F-WN-16-4 were identified mechanically (AST/grep), but the *correctness* of each method's own error handling belongs to WN-03…WN-10 and WN-26 and was not re-reviewed here.
- **`core/api.py` lines outside the ranges listed in section 1** (e.g. WN-06…WN-10 method bodies) were only read where they intersect the error-mapping contract.
- The `android/` subtree was not opened (out of scope per the brief).
