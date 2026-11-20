## AREA WN-02 — AppCore wiring & subsystem lifecycle — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/app.py` L1–586 (whole file)
- `core/session.py` L1–96 (whole file)
- `core/listening.py` L1–44 (whole file)
- `core/plugins.py` L1–120 (whole file)

**Callees traced into other areas (read only, not owned by WN-02)**

- `core/api.py` L330–409 (`AppApi.__init__`, `self._core.api = self`), L905–974 (`close`/`shutdown`), L1160–1466 (`_on_track_changed`, `_listening_for_track`, `_persist_listening`, `flush_listening`, `maybe_log_history`, `report_listening_state`, `report_state`, `report_position`, `play_track`), L1560–1759 (`play_track`/`_resolve_track` → `re_resolve_stream_url_async` callers), L1437–1466
- `core/proxy.py` L1010–1139 (403/410 self-heal → `re_resolve_stream_url_async`), L1260–1319 (`LocalProxyManager.start/stop`)
- `core/downloader.py` L880–909 (`stop()` — drains running futures with a 5 s budget)
- `core/settings.py` L330–529 (`get`/`set`/`flush`/`_write_batch`, batched + transactional)
- `core/database.py` L140–259 (`_get_connection`, thread-local connections), L2400–2489 (`close_thread_connection`, `close`)
- `core/offline.py` L1–77 (`is_offline`, `available_track`)
- `services/base_service.py` L1–329 (`_SharedExecutor`, `_join_request` single-flight, `submit`, `shutdown_executor`)
- `services/youtube_service.py` L880–1128 (`get_stream_url` — callback/error contract, `self._executor.submit(_extract)`)
- `services/soundcloud_service.py` L115–159 (ctor), L560–679 (`get_stream_url` — `_join_request`, cache-hit fast path)
- `services/zapret_service.py` L1005–1099, L1330–1409 (`auto_update_in_background`, `start`, `stop`)
- `services/watchdog_service.py` L60–129, `services/lufs_scanner.py` L36–75, `core/services/discord_rpc.py` L1–120
- `audio/queue.py` L1–70, L110–189 (`set_tracks` shallow-copies the list, shares the track dicts)
- `utils/file_scanner.py` L95–134, `services/lyrics_service.py` L40–99, `services/track_resolver.py` L35–84, `services/catalog_service.py` L14–37 (all module-level pools register `atexit` shutdowns)
- `setup_pyinstaller.spec` L1–111 (onefile `EXE`, `extra_datas`)
- `main.py` L230–409, L500–583 (`AppCore()` → `AppApi()` → `on_loaded` → `cleanup()` → `save_session`)
- `ui/web_new_v2/js/player.js` L520–689 (renderer heartbeat: `report_position` every 5 s, `report_listening_state` on media events)
- `tests/test_db_core_fixes_f2.py` L505–623, `tests/test_offline_resolve_callbacks.py` L1–117 (existing coverage, to avoid duplicating)

---

### 2. Findings

#### F-WN-02-1  [P1] — The plugin folder resolves inside the PyInstaller onefile temp directory, so user plugins are never loaded in the shipped app

- **File:** `core/plugins.py:26-33` (+ `setup_pyinstaller.spec:27-30`, `setup_pyinstaller.spec:90-111`)
- **Confirmed:** yes
- **Description:** `PluginManager.plugins_dir` is derived from `__file__` of `core/plugins.py`. In the packaged Windows build that module lives inside the PyInstaller bundle, never next to the installed executable. The manager therefore looks for plugins in a throwaway temp folder that is recreated and deleted on every run, so a plugin the user dropped into the installation folder is never discovered.
- **Cause:** the path is computed only from the module location, with no frozen/source split. The project's own non-negotiable rule #9 ("any asset lookup needs both `getattr(sys, "_MEIPASS", ...)` branches or it breaks in the packaged exe") is not honoured here — `core/plugins.py` contains no `_MEIPASS` branch at all. The spec also does not ship a `plugins` data folder (`extra_datas` lists only `ui/web_new_v2`, `ui/MACos_ui`, `ytmusicapi` data, plus `zapret`/`bin`), so the folder is not even present in the bundle.
- **Trigger conditions:** any packaged build (the spec produces a single-file `EXE`, i.e. `sys._MEIPASS` = `%TEMP%\_MEIxxxxxx`). `general.plugins_enabled` must also be ON, which is itself hard to reach (see F-WN-02-10).
- **User impact:** the whole opt-in plugin feature is inoperable in the product that ships. The user copies a plugin into `<install>\plugins\`, enables plugins, restarts — nothing loads, and the only trace is `PluginManager` pointing at a temp path the user never sees.
- **Evidence:**
  ```python
  # core/plugins.py:26-29
  self.plugins_dir = os.path.join(
      os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
      'plugins'
  )
  ```
  ```python
  # setup_pyinstaller.spec:27-30
  extra_datas = [('ui/web_new_v2', 'ui/web_new_v2'), ('ui/MACos_ui', 'ui/MACos_ui')] + collect_data_files('ytmusicapi')
  for extra_folder in ['zapret', 'bin']:
      if os.path.exists(extra_folder):
          extra_datas.append((extra_folder, extra_folder))
  ```
  ```python
  # setup_pyinstaller.spec:90-111  — onefile EXE (no COLLECT): _MEIPASS is a temp dir
  exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], name='NeDotify', ...)
  ```
- **Reproduction / verification:** build the installer, create `<install>\plugins\my_plugin.py` with a `setup(app_core)` function, set `general.plugins_enabled = true` in `~/.nedotify/nedotify_storage.db`, start the packaged exe, and inspect `~/.nedotify/logs/app.log`: the plugin is never mentioned, and `PluginManager.plugins_dir` resolves to `%TEMP%\_MEIxxxxxx\plugins`. Source-mode cross-check: `python -c "import core.plugins as p; print(p.PluginManager(None).plugins_dir)"` prints the repo-root `plugins` folder (exists and is empty in the repo), confirming the source/frozen divergence.
- **Suggested fix:** resolve the plugin folder next to `sys.executable` when `getattr(sys, "frozen", False)` (and keep the source-relative path otherwise); optionally ship an empty `plugins` data folder so the directory exists next to the exe.
- **Fix side effects:** a user-writable directory next to the exe is the intended threat model here — `sys.path` must still never be extended (rule #10), and the plugin folder must stay out of the bundle's import path.
- **Discovered by:** A

#### F-WN-02-2  [P2] — `cleanup()` closes the database *before* the worker pools are stopped, so in-flight tasks write to a closed connection

- **File:** `core/app.py:555-586` (db close at L559-560, pool shutdowns at L571-586), `core/database.py:2459-2489`
- **Confirmed:** yes
- **Description:** `cleanup()` runs `db.close()` and only afterwards shuts the shared service pool, the cache pool and the four provider pools. `DatabaseManager.close()` closes **every** tracked connection — including connections owned by other threads — and does not invalidate their thread-local slots, so the next use of that connection from its own thread raises `sqlite3.ProgrammingError: Cannot operate on a closed database.` Only the downloader defends itself against this (`core/downloader.py:884-898` drains its running futures for up to 5 s and its docstring explicitly says "core/app.py closes the database right after this call"). Every other pool, plus the LUFS scan thread and the settings writer thread, is still live when the DB is closed.
- **Cause:** inverted teardown order — resources are closed before the workers that use them are drained. The `_step()` wrapper isolates failures but does not change the ordering, so the failure is silent: the affected tasks catch the exception themselves (e.g. `core/app.py:370-371`, `core/app.py:357-359`).
- **Trigger conditions:** the user closes the app while a provider resolution, a stream-cache write or the 5-second delayed stream download is in flight. Concrete victim: the `threading.Timer(5.0, delayed_download)` created at `core/app.py:372-374` — it is never cancelled by `cleanup()`, so it can fire *after* `db.close()` and its `self.cache.download_audio_stream(...)` write is swallowed by `except Exception: logger.debug(...)`.
- **User impact:** the fresh stream URL is not written to the cache, so the next play of that track re-resolves from scratch (extra network round trip, slower start); the settings writer's pending keys are re-queued onto a dead connection and never persisted; the LUFS scan thread dies with `ProgrammingError` instead of finishing its batch.
- **Evidence:**
  ```python
  # core/app.py:555-560
  if getattr(self, "_cache_cleanup_stop", None) is not None:
      _step("cache_cleanup.stop", self._cache_cleanup_stop.set)
  if getattr(self, "settings", None) and hasattr(self.settings, "flush"):
      _step("settings.flush", self.settings.flush)
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)          # <-- DB closed here

  # core/app.py:571-586  (pools stopped only AFTER the close)
  _step("base_service pool", _shutdown_shared_pool)
  for _pool in (..., getattr(self.cache, "_executor", None), ...):
      ...
      _pool.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # core/database.py:2474-2482 — closes other threads' connections, slots stay "valid"
  with self._conns_lock:
      for conn in list(self._all_conns):
          try:
              conn.close()
  ```
- **Reproduction / verification:** add a temporary `time.sleep(6)` inside `services/youtube_service.py::_extract` (or start a long provider resolution), close the app window while it runs, and look for `Cannot operate on a closed database` in `~/.nedotify/logs/app.log`; the same is observable today through the 5 s `delayed_download` timer by resolving a track and closing the window within 5 seconds.
- **Suggested fix:** stop and drain the pools (and the LUFS/settings threads) *before* `db.close()`, and cancel the pending `threading.Timer` instances.
- **Fix side effects:** draining the pools with `wait=True` would delay exit; the downloader already shows the bounded pattern (`drain_timeout=5.0`) to copy.
- **Discovered by:** A

#### F-WN-02-3  [P2] — The yt-dlp updater thread is never stopped or joined, so a `pip install` can outlive the app and rewrite `yt_dlp` under a running instance

- **File:** `core/app.py:150-151` (start), `core/app.py:47-88` (worker), `core/app.py:508-586` (`cleanup()` has no step for it)
- **Confirmed:** yes for the untracked thread; the corrupted-install consequence is a hypothesis
- **Description:** `AppCore.__init__` starts `update_ytdlp_safely` on a daemon thread and never records it. `cleanup()` has no matching stop/join step, and the worker itself can spawn a 120-second `pip install` subprocess.
- **Cause:** the thread handle is discarded, so no teardown can wait for it. On interpreter exit a daemon thread is killed at an arbitrary point; its `subprocess.run` child is a separate Windows process and survives.
- **Trigger conditions:** the deferred-update logic means the *second* launch is the one that really installs: launch #1 creates `~/.nedotify/.ytdlp_update_pending`, launch #2 finds it and runs `pip install -U yt-dlp[default]`. Closing the app inside that 120 s window kills the Python side while pip keeps writing into the venv.
- **User impact:** if the app is restarted while pip is still writing `site-packages/yt_dlp`, the new process can import a half-written package → `HAS_YTDLP` becomes False → every YouTube track fails with "yt-dlp не установлен" until the next successful update.
- **Evidence:**
  ```python
  # core/app.py:150-151
  if not is_offline(self.settings):
      threading.Thread(target=update_ytdlp_safely, daemon=True).start()
  ```
  ```python
  # core/app.py:76-80
  result = subprocess.run(
      [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
      capture_output=True,
      timeout=120,
  )
  ```
  `cleanup()` (L508-586) contains no reference to this thread.
- **Reproduction / verification:** run the app twice so the pending stamp exists, watch `~/.nedotify/logs/app.log` for "yt-dlp auto-update", then close the app during the install and check whether a `python -m pip` child process is still running (`Get-Process python | Select-Object Id,StartTime`).
- **Suggested fix:** keep the thread handle, join it with a bounded timeout in `cleanup()`, and skip the install when `self._shutting_down` is set.
- **Fix side effects:** joining adds up to the remaining install time to shutdown; it must be bounded and must not block the teardown of the other subsystems.
- **Discovered by:** A

#### F-WN-02-4  [P2] — `SessionManager.save_session` resumes the WRONG track when the queue exceeds 200 entries and the current track sits in the dropped head

- **File:** `core/session.py:50-55` (consumer: `main.py:561-569`)
- **Confirmed:** yes
- **Description:** the persisted queue is capped at `MAX_PERSISTED_QUEUE = 200` and the head is cut. The index is shifted by `dropped`, but clamped with `max(0, …)`, so when the current track was inside the dropped head the index silently becomes 0 — pointing at a different song. The separately stored `session.last_track_id` still holds the original track, so the restored state is internally inconsistent.
- **Cause:** the clamp protects the list index but loses the identity of the current track. There is no check that `queue_index >= dropped`.
- **Trigger conditions:** a queue longer than 200 entries with the current track among the first `dropped` positions (e.g. 250 tracks, playing the 30th).
- **User impact:** on restart the app restores the wrong track as "current", and `session_autoplay` resumes the wrong song at the saved position of a different one.
- **Evidence:**
  ```python
  # core/session.py:50-55
  full_queue = list(queue or [])
  dropped = max(0, len(full_queue) - self.MAX_PERSISTED_QUEUE)
  persisted_queue = [self._slim_track(t) for t in full_queue[dropped:]]
  if dropped and isinstance(queue_index, int):
      # Keep the index pointing at the same track after the head is cut.
      queue_index = max(0, queue_index - dropped)
  ```
- **Reproduction / verification:** `SessionManager(settings).save_session(track_id=30, position=12.0, queue=[{'id': i, 'source': 'local'} for i in range(250)], queue_index=29)` → the persisted `last_queue` holds entries 50..249 and `last_queue_index` is `0` (entry 50), not entry 29.
- **Suggested fix:** when `queue_index < dropped`, keep the current track by appending it to the persisted list (or persist the current track separately and re-anchor the index on restore) instead of clamping to 0.
- **Fix side effects:** the persisted payload grows by one entry; `restore_session` and `main.py`'s `set_tracks` index handling must stay in sync.
- **Discovered by:** A

#### F-WN-02-5  [P2] — `ListeningSession.tick()` caps *every* accounting interval at 15 s, so any heartbeat gap longer than 15 s is silently discarded

- **File:** `core/listening.py:22-30` (heartbeat source: `core/api.py:1414`, renderer at `ui/web_new_v2/js/player.js:613-616`)
- **Confirmed:** yes
- **Description:** `seconds` (audible wall-clock) and `media_seconds` are the **sum of clamped intervals**. The clamp is applied to every gap, not only to pathological ones, so a single gap longer than 15 s contributes only 15 s and the remainder is lost forever. The clamp was meant to reject "a suspended computer" but it also truncates legitimate long intervals.
- **Cause:** the clamp is a hard cap on the interval rather than a validity check on the interval. There is no way to distinguish "the renderer was suspended for 5 minutes" from "the user listened for 5 minutes".
- **Trigger conditions:** the 5-second `report_position` heartbeat stops for >15 s — the WebView2 renderer is backgrounded (window minimised to tray), the renderer is blocked, or the machine resumes from sleep. `report_position` → `session.tick()` is the only thing that advances the counter between media events.
- **User impact:** the listening history (`history.duration`) under-reports, and because `completed` requires `media_seconds >= duration * 0.8`, a fully played track can stay marked "not completed" — which feeds the taste profile / recommendations (WN-23) and the profile statistics.
- **Evidence:**
  ```python
  # core/listening.py:22-30
  def tick(self, now=None):
      now = time.monotonic() if now is None else now
      if self.audible and not self.closed:
          # Position heartbeats arrive every 5s. Do not turn a suspended
          # computer or unresponsive renderer into hours of listening.
          delta = max(0.0, min(15.0, now - self.last_tick))
          self.seconds += delta
          self.media_seconds += delta * self.playback_rate
      self.last_tick = now
  ```
- **Reproduction / verification:** `s = ListeningSession({'duration': 100}); s.audible = True; t0 = s.last_tick; s.tick(t0 + 60)` → `s.seconds == 15.0` (expected 60.0). The same gap in the real app is produced by blocking the renderer for 60 s.
- **Suggested fix:** distinguish "the heartbeat is late because the app was suspended" from "the user was listening": e.g. treat a gap above the clamp as an explicit discontinuity (reset the window and mark the session as having an unknown interval) rather than silently crediting 15 s.
- **Fix side effects:** a real discontinuity marker changes what the history rows mean; `services/listening_comparison.py` (WN-25) consumes `seconds`/`completed` and may need to tolerate the new state.
- **Discovered by:** A

#### F-WN-02-6  [P2] — `re_resolve_stream_url_async` has no completion deadline on the primary path: neither callback is guaranteed to fire

- **File:** `core/app.py:296-506` (budget at L44, L446-465, dispatch at L502)
- **Confirmed:** yes for the missing deadline; the "provider never calls back" trigger is a hypothesis about the callee
- **Description:** the only wall-clock budget in the function (`_SC_FALLBACK_BUDGET_S = 20.0`) applies to the **YouTube→SoundCloud fallback chain** only. The primary `service.get_stream_url(...)` call has no timeout of the AppCore's own: the function returns immediately and the caller must trust the provider to call one of the two callbacks. The proxy compensates with its own wait (`core/proxy.py:1052`, `resolve_event.wait(timeout=7)`), but the bridge path does not: `core/api.py:1604` and `core/api.py:1744` pass `on_error`/`callback` with no timeout of their own.
- **Cause:** the "exactly one of callback/on_error is invoked" contract is delegated entirely to the provider and is never enforced or bounded by the owner of the contract.
- **Trigger conditions:** a provider task that never completes — a saturated provider executor (`youtube_service.py:1069` submits to a 10-worker pool; each yt-dlp extraction can run for tens of seconds), a socket read without a timeout, or a task dropped because the pool was shut down (`BaseMusicService.submit` returns `None` instead of raising — `services/base_service.py:82-106`).
- **User impact:** the frontend's loading state is never resolved and no error is surfaced. The UI has its own stall fallback, so this is not always a permanent spinner, but the backend contract is unenforced.
- **Evidence:**
  ```python
  # core/app.py:502-504
  try:
      if offline_result():
          return
      service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
  except Exception as e:
      _on_err(str(e))
  ```
  ```python
  # core/app.py:454-465 — the only budget, and it covers the SC fallback only
  if idx >= len(candidates) or elapsed > _SC_FALLBACK_BUDGET_S:
      logger.warning("SoundCloud fallback exhausted for %s ...")
      if on_error:
          on_error(err)
      return
  ```
- **Reproduction / verification:** stub `core.youtube` with a provider whose `get_stream_url` stores the callbacks and returns without invoking either (the shape used by `tests/test_offline_resolve_callbacks.py::DeferredStreamProvider`), call `AppCore.re_resolve_stream_url_async(core, 'youtube', 'x', callback=cb, on_error=err)` and wait: neither `cb` nor `err` is ever called.
- **Suggested fix:** wrap the resolution in an `threading.Timer`/deadline inside `re_resolve_stream_url_async` and guarantee that exactly one of `callback`/`on_error` is invoked (guard with a one-shot flag so a late provider callback cannot double-fire).
- **Fix side effects:** an added deadline must be generous enough not to cut off slow but successful extractions; the proxy's own 7 s wait would have to be reconciled with it.
- **Discovered by:** A

#### F-WN-02-7  [P2] — In the YouTube fallback, an exception raised outside the inner `try` aborts `_on_err` before `on_error` is invoked

- **File:** `core/app.py:379-497` (critical line L382, `try:` at L384, `on_error` at L496-497), invoked from `core/app.py:504` and from the provider's callback wrapper (`services/youtube_service.py:922-930`)
- **Confirmed:** yes
- **Description:** `_on_err` is supposed to end in `if on_error: on_error(err)`. But the guard `hasattr(self, "soundcloud") and self.soundcloud` is evaluated **outside** the `try:` block that begins at L384. `hasattr` swallows only `AttributeError`; any other exception raised by the lazy `soundcloud` property (the import of `services.soundcloud_service`, or `SoundCloudService.__init__` raising) propagates out of `_on_err`. The same shape exists one level deeper: `self.soundcloud.get_stream_url(...)` at L479 runs inside the provider's callback wrapper, where an exception (e.g. `RuntimeError: cannot schedule new futures after shutdown` once `cleanup()` has shut the pool) is swallowed by the provider and `on_error` is never called.
- **Cause:** the error path is only partially guarded. `_on_err` is called either from the provider's `finish()` wrapper (which catches and only logs: `logger.exception("YouTube stream callback failed")`) or from `core/app.py:504` (`except Exception as e: _on_err(str(e))`) — in both cases the escaping exception kills the worker thread (or is swallowed) and the error callback is lost.
- **Trigger conditions:** a failing YouTube extraction while the SoundCloud service cannot be constructed/imported; or any provider-side exception raised inside the fallback chain.
- **User impact:** the track stays in the frontend's permanent loading state — no error message, no fallback, no log entry that points at the real cause beyond a thread traceback.
- **Evidence:**
  ```python
  # core/app.py:379-384 and 494-497
  def _on_err(err):
      if offline_result():
          return
      if source == "youtube" and hasattr(self, "soundcloud") and self.soundcloud:   # <-- outside the try
          try:
              import re
              ...
          except Exception as fallback_ex:
              logger.debug(f"SoundCloud fallback search error: {fallback_ex}")
      if on_error:
          on_error(err)
  ```
  ```python
  # services/youtube_service.py:922-930 — provider wrapper swallows callback exceptions
  for on_stream, on_error in listeners:
      try:
          ...
      except Exception:
          logger.exception("YouTube stream callback failed")
  ```
- **Reproduction / verification:** stub `core.youtube` so that `get_stream_url` calls `error_callback('boom')` (as `tests/test_offline_resolve_callbacks.py` does), and make the lazy `soundcloud` property raise (e.g. temporarily point `core.app`'s import of `services.soundcloud_service` at a module that raises on import). Assert that `errors` stays empty while a traceback appears in the log.
- **Suggested fix:** wrap the whole body of `_on_err` (including the `hasattr`/property access) in a `try/finally` that guarantees `on_error(err)` is called exactly once if it has not been called already.
- **Fix side effects:** a one-shot "already notified" flag must be shared with `_on_resolved` so the success path is not double-notified.
- **Discovered by:** A

#### F-WN-02-8  [P3] — `restore_session()` mutates the live `SettingsManager` cache in place (shared references)

- **File:** `core/session.py:82-87`, `core/settings.py:351-399` (the `get()` that returns the cached object by reference), `audio/queue.py:119-124` (shallow copy — the dicts are shared), `core/api.py:1723-1729`
- **Confirmed:** yes
- **Description:** `SettingsManager.get()` returns the cached object **by reference** (only the *defaults* are deep-copied — `core/settings.py:334`). `restore_session()` therefore hands out the very list stored in `_cache["session"]["last_queue"]` and then writes `track["file_path"] = None` / `track["resolved_at"] = 0` into those dicts. `engine.queue.set_tracks()` copies the list but not the dicts, so a later `cur["file_path"] = stream_url` writes a live, expiring CDN URL back into the settings cache.
- **Cause:** no copy is taken between the settings store and the session/queue consumers, so the "settings" and "live playback" representations of the same track are the same objects.
- **Trigger conditions:** every normal start (restore) followed by a successful resolution.
- **User impact:** the in-memory settings state and the persisted state can disagree; `settings.get("session", "last_queue")` between restore and the next `save_session` returns a queue mutated by playback. The persisted value stays clean because `_slim_track` re-projects the entries and drops `file_path` for non-local sources.
- **Evidence:**
  ```python
  # core/session.py:82-87
  for track in session.get("queue", []):
      if not isinstance(track, dict):
          continue
      if track.get("source") in ("youtube", "soundcloud", "vk"):
          track["file_path"] = None
          track["resolved_at"] = 0
  ```
  ```python
  # audio/queue.py:122-123 — list copied, dicts shared
  self._tracks = tracks.copy()
  self._original_order = tracks.copy()
  ```
- **Reproduction / verification:** `s = settings.get("session", "last_queue")`; `s[0]["file_path"] = "X"` → a second `settings.get("session", "last_queue")[0]["file_path"]` is also `"X"`.
- **Suggested fix:** return a deep copy from `restore_session()` (or make `SettingsManager.get()` copy mutable values), so the session restore cannot mutate the settings store.
- **Fix side effects:** copying a 200-entry queue on every restore costs a little memory/time; the settings store's own contract (`get` returns references) is used elsewhere and should not be changed globally without checking its callers.
- **Discovered by:** A

#### F-WN-02-9  [P3] — A plugin whose `setup()` raises stays in `sys.modules` and never receives `teardown()`

- **File:** `core/plugins.py:91-107`, `core/plugins.py:109-120`
- **Confirmed:** yes
- **Description:** `sys.modules[qualified_name] = module` is popped only when `exec_module` fails (L96) or when the module has no `setup` (L104). If `module.setup(self._core)` raises (L100), the outer `except Exception` (L106) logs the error, but the module stays registered in `sys.modules` and the plugin is never appended to `self.plugins` — so `unload_all()` cannot call its `teardown` and cannot remove it from `sys.modules`.
- **Cause:** the cleanup of the half-imported module is attached to the wrong failure points.
- **Trigger conditions:** any plugin whose `setup()` raises after partially initialising itself (starting a thread, registering a hook, opening a file).
- **User impact:** a broken plugin leaks whatever it started for the rest of the session; the stale module stays importable under `aura_plugins.<name>` for the process lifetime.
- **Evidence:**
  ```python
  # core/plugins.py:91-107
  module = importlib.util.module_from_spec(spec)
  sys.modules[qualified_name] = module
  try:
      spec.loader.exec_module(module)
  except Exception:
      sys.modules.pop(qualified_name, None)
      raise

  if hasattr(module, 'setup') and callable(module.setup):
      module.setup(self._core)          # <-- raises here: nothing pops the module
      self.plugins.append(module)
  else:
      sys.modules.pop(qualified_name, None)
  ```
- **Reproduction / verification:** drop a plugin whose `setup(app_core)` raises `RuntimeError('boom')` into the plugins folder, enable plugins, start the app: `sys.modules` contains `aura_plugins.<name>` after startup, and `PluginManager.plugins` is empty.
- **Suggested fix:** pop the module from `sys.modules` in the `except` handler around `setup()` as well, and call `teardown()` best-effort for a plugin that failed mid-setup.
- **Fix side effects:** none material; the plugin is being discarded anyway.
- **Discovered by:** A

#### F-WN-02-10  [P3] — `plugins.load_plugins()` runs before `AppApi` exists, so `core.api` is undefined for the whole of `setup(app_core)`

- **File:** `core/app.py:159`, `core/api.py:347` (`self._core.api = self`), `main.py:306-310`
- **Confirmed:** yes
- **Description:** `AppCore.__init__` loads and initialises the plugins at L159. `AppApi` — the object that sets `core.api` — is only constructed afterwards in `main.py` (`app_core = AppCore()` then `api = AppApi(app_core)`). During `setup(self._core)` the attribute `core.api` does not exist yet.
- **Cause:** the plugin loader is invoked inside the core's constructor, i.e. before the bridge exists. The rest of the codebase guards for this (`core/proxy.py:1019`, `services/watchdog_service.py:125-128` all use `hasattr(self._core, 'api')`), the plugin API does not.
- **Trigger conditions:** a plugin that touches `core.api` (e.g. to emit an event or register a bridge callback) inside `setup()`.
- **User impact:** the plugin raises `AttributeError`, is dropped by `core/plugins.py:106`, and is silently unavailable for the whole session — with only a log line to explain it.
- **Evidence:**
  ```python
  # core/app.py:157-159
  # Start Local Stream Proxy & Load Plugins
  self.proxy.start()
  self.plugins.load_plugins()
  ```
  ```python
  # core/api.py:345-347
  def __init__(self, core):
      self._core = core
      self._core.api = self
  ```
- **Reproduction / verification:** a plugin whose `setup(core)` does `core.api.emit_event('x', {})` → `AttributeError: 'AppCore' object has no attribute 'api'` logged as "Failed to load plugin".
- **Suggested fix:** defer `load_plugins()` until after the bridge exists (e.g. call it from `main.py` right after `AppApi(app_core)`), or pass the api to the plugins when they are set up.
- **Fix side effects:** plugins would then load slightly later; `cleanup()` must still call `unload_all()` for plugins that were never loaded.
- **Discovered by:** A

#### F-WN-02-11  [P3] — The callback thread differs by mode: offline resolves synchronously on the caller's thread, online resolves on a provider worker thread

- **File:** `core/app.py:298-304` (offline, synchronous) vs `core/app.py:305-506` (online, worker thread at L506)
- **Confirmed:** yes
- **Description:** in offline mode `callback(...)` is invoked directly on the thread that called `re_resolve_stream_url_async` (the pywebview bridge thread); in online mode it is always invoked from a provider worker thread. The contract is not documented and is mode-dependent.
- **Cause:** the offline branch returns before the `threading.Thread(target=worker, ...).start()` at L506.
- **Trigger conditions:** toggling offline mode with a pending resolution — i.e. exactly the scenario `tests/test_offline_resolve_callbacks.py` exercises.
- **User impact:** the bridge callback mutates the engine queue (`_notify_track_changed`) and emits events; it now runs inside the caller's bridge call in offline mode and on a foreign thread online. `AppApi._emit` only special-cases the *UI* thread, so both are "safe", but any future caller that assumes "the callback is always off the calling thread" (e.g. to avoid re-entrancy into the engine) will break in one of the two modes.
- **Evidence:**
  ```python
  # core/app.py:298-304
  if is_offline(self.settings):
      local = available_track(self.db, track or {'source': source, 'source_id': source_id})
      if local and callback:
          callback(local['file_path'], local)     # <-- same thread as the caller
      elif not local and on_error:
          on_error('В офлайн-режиме доступна только сохранённая музыка')
      return
  ```
- **Reproduction / verification:** call `AppCore.re_resolve_stream_url_async` from a thread you name, with offline mode on and a saved local file, and print `threading.current_thread().name` inside the callback — it is the caller's thread; with offline mode off it is `Thread-N (worker)`.
- **Suggested fix:** make the offline branch dispatch through the same worker thread as the online branch, so the callback thread is invariant.
- **Fix side effects:** the offline path gains a thread hop (a few ms) — the bridge call would return before the callback, which is the behaviour callers already expect online.
- **Discovered by:** A

---

### 3. Clean areas

- **Lazy service properties (`core/app.py:187-234`)** — the double-checked locking is correct: the outer `if self._x is None` read is only an optimisation, the construction happens under `self._service_lock`, and the second `is None` check inside the lock prevents double construction. Two threads racing on `core.soundcloud` yield exactly one `SoundCloudService`. The `RLock` (not `Lock`) is required and present, and the `recommendations` property resolves its dependencies *before* taking the lock, so no lock is held across network I/O. `cleanup()` reads the private attributes (`_soundcloud`, `_yandex`) rather than the properties, so teardown never *creates* a service it did not use.
- **Zapret shutdown ordering (`core/app.py:113-119, 236-294, 508-554`)** — the `_shutting_down` Event is set as the first act of `cleanup()`, the start worker re-checks it on its own thread, the thread handle is stored and joined with a bounded 5 s timeout, and `zapret.stop()` runs *after* the join — so a start cannot land after the stop and orphan a `winws.exe` process. The behaviour is pinned by `tests/test_db_core_fixes_f2.py:524-623`.
- **`cleanup()` isolation and idempotency (`core/app.py:508-586`)** — every teardown step runs through `_step()`, so one failing subsystem cannot abort the rest, and each failure is logged with a traceback. Re-running `cleanup()` is safe: `_step` swallows, `zapret.stop()` finds no process, `proxy.stop()` sees `server is None`, `plugins.unload_all()` iterates an already-cleared list, `ThreadPoolExecutor.shutdown()` and `_SharedExecutor.shutdown()` are idempotent, `settings.flush()` is a no-op when nothing is dirty, and `db.close()` re-opens a fresh thread-local connection rather than touching a closed one.
- **Subsystem shutdown coverage** — watchdog, LUFS scanner, downloader, plugins, Discord RPC, proxy, zapret, the cache-cleanup loop, the settings writer, the shared provider pool and the four provider instance pools all have a matching stop step in `cleanup()`. The downloader additionally drains its running workers for 5 s and its docstring documents the `db.close()` ordering explicitly. The three module-level pools (`services/catalog_service.py:15`, `services/lyrics_service.py:88`, `services/track_resolver.py:76`) register their own `atexit` shutdowns, so they cannot block interpreter exit.
- **Plugin loader isolation (`core/plugins.py:46-67, 99-107`)** — a plugin that raises during import or during `setup()` is caught and logged; the app keeps running. `sys.path` is **never** extended anywhere in the file (non-negotiable rule #10 is honoured); plugins are imported via `importlib.util.spec_from_file_location` under the `aura_plugins.` namespace, so a `plugins/json.py` cannot shadow the stdlib. `unload_all()` calls `teardown()` per plugin with per-plugin exception isolation and removes each module from `sys.modules`.
- **Plugin opt-in gate (`core/plugins.py:35-44`)** — plugins stay off unless `general.plugins_enabled` is set, and a settings read failure fails closed (keeps plugins disabled).
- **`SessionManager` persistence semantics (`core/session.py:39-68`)** — the seven `set()` calls update the in-memory cache synchronously and the subsequent `flush()` writes them in a **single transaction** (`core/settings.py:443-484`, `DatabaseManager.set_settings_batch`), so the persisted session cannot be torn by a crash between the individual `set()` calls. A short batch is re-queued rather than reported as success. The persisted payload is projected through `_slim_track`, so arbitrary track payloads are not written to the settings store.
- **`ListeningSession` completion semantics (`core/listening.py:32-44`)** — `duration` is parsed defensively (`float(... or 0)` with `TypeError/ValueError` caught), `math.isfinite(duration)` rejects `NaN`/`inf` (which the renderer can produce for `audio.duration` on a failed metadata load), a zero/absent duration never marks a track completed, and `completed` is sticky (`self.completed or ...`). Seeking to the end does not mark a track completed, because the counter is wall-clock based, not position based.
- **Offline short-circuit in `re_resolve_stream_url_async` (`core/app.py:298-304, 338-346`)** — `available_track()` always sets `file_path` on the returned dict, so `local['file_path']` cannot raise `KeyError`; the "going offline while a resolution is pending" behaviour is pinned by `tests/test_offline_resolve_callbacks.py`.
- **`AppCore.__init__` construction order (`core/app.py:94-186`)** — every dependency exists before its first use: `db` → `settings` → `session`/`cache`/`scanner` → `resolver` → `engine` (`engine.app_core` assigned immediately) → `proxy` → `engine.proxy` → `downloader`/`plugins`/`zapret`/`watchdog`/`lufs_scanner`. The proxy starts only after the cache, engine and resolver exist; the watchdog starts only after `scanner` exists; `engine.app_core` is set before the engine can be called.
- **Failure isolation in `__init__`** — `watchdog.start()` and `lufs_scanner.start()` are wrapped individually (`core/app.py:162-171`), `LocalProxyManager.start()` swallows and logs its own failures (`core/proxy.py:1281-1282`), `DiscordRPCService.start()` cannot raise (`core/services/discord_rpc.py:51-85`), `PluginManager.__init__`/`load_plugins` swallow directory errors, and `ZapretService.auto_update_in_background` catches everything inside its worker.

---

### 4. Coverage gaps

- **The frozen-build claim in F-WN-02-1 was not executed.** I did not build the PyInstaller bundle (build time and the rule "never run the real app"); the conclusion is derived from `setup_pyinstaller.spec` (single-file `EXE`, no `plugins` entry in `extra_datas`) and standard PyInstaller `_MEIPASS` semantics. Verification would be a single `print(PluginManager(None).plugins_dir)` inside the packaged exe.
- **Provider-internal callback contracts were read, not fuzzed.** `services/youtube_service.py` and `services/soundcloud_service.py` were read only along the paths `AppCore` drives. The "provider never calls back" trigger in F-WN-02-6 is therefore a hypothesis about the callees; the *missing deadline* in `core/app.py` is confirmed.
- **No live run.** All findings are from static reading plus the arithmetic reproductions quoted inline; the app was not started and `~/.nedotify/` was not touched. The reproductions for F-WN-02-4 and F-WN-02-5 are unit-level and were derived by hand from the quoted code, not executed (the interpreter was not invoked against the repo's venv in this pass).
- **Concurrent-startup behaviour of the lazy properties** was verified by reading, not by a stress test; `tests/test_lazy_service_deadlock.py` exists and was not re-run.
- **The `main.py` session-loss path on the watchdog restart** (`main.py:526-539` calls `cleanup()` without `save_session()`) was observed but **not** reported: `main.py` is owned by WN-01, and the root cause is there.
- **The `api.py` ordering quirk** where `session.playback_rate` is assigned *after* `session.state(...)` (`core/api.py:1347-1349`) causes a one-interval lag in `media_seconds`; it is in WN-05's file and is only noted here, not filed as a WN-02 finding.
- **`services/lufs_scanner.py:62` uses `self._core.db.conn` from its own thread** — safe because `DatabaseManager.conn` is a thread-local property (`core/database.py:203-205`), but the interaction with F-WN-02-2 (the DB closed underneath it) was not reproduced end to end.
