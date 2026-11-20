## AREA WN-02 — AppCore wiring & subsystem lifecycle — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/app.py` — **1–586** (whole file; `AppCore` class 91–586, `update_ytdlp_safely` 47–88)
- `core/session.py` — **1–96** (whole file)
- `core/listening.py` — **1–44** (whole file)
- `core/plugins.py` — **1–120** (whole file)

**Callees traced into other areas (read to establish the call chain, not audited as owned defects)**

- `core/api.py` — 256–257 (`_BRIDGE_READONLY_SETTINGS`), 342–392 (`AppApi.__init__`, `self._core.api = self`), 440–459 (`AppApi.cleanup`), 1260–1459 (listening telemetry use of `ListeningSession`)
- `core/proxy.py` — 396–441 (thread-per-connection server), 780–879 (`do_GET` local/cache/offline paths), 1010–1119 (403/410 self-heal → `re_resolve_stream_url_async`), 1259–1334 (`LocalProxyManager.start/stop`)
- `core/downloader.py` — 50–204 (`DownloadManager.__init__`, `_emit`), 884 (`stop`)
- `core/settings.py` — 300–549 (`_load_all`, `get`, `set`, `flush`, `_write_batch`, writer thread)
- `core/database.py` — 145–244 (`_get_connection`, `conn`), 2036–2117 (`set_setting`/`set_settings_batch`), 2400–2489 (`close`)
- `core/resolver.py` — 1–271 (`StreamResolver.resolve` single-flight, `refresh`, `invalidate`)
- `audio/engine.py` — 1–330 (queue/engine wiring, `_resolve_via_network` fallback cascade)
- `audio/queue.py` — 24–45, 110–149 (`current_track`, `set_tracks`)
- `services/base_service.py` — 1–200 (`_SharedExecutor`, `submit`, `shutdown_executor`)
- `services/soundcloud_service.py` — 100–169 (`SoundCloudService.__init__`)
- `services/recommendation_service.py` — 30–109 (`RecommendationService.__init__`)
- `services/watchdog_service.py` — 1–129 (`start/stop`, `observer.join()`)
- `services/zapret_service.py` — 833–1000 (binary download), 1063–1172 (`start`, `_launch`)
- `services/lyrics_service.py` — 1–120, 160–239 (`_LyricsSharedExecutor`, `atexit`)
- `services/track_resolver.py` — 1–120 (`_TrackResolverExecutor`, `atexit`)
- `services/catalog_service.py` — 1–60 (module-level pool, `atexit`)
- `services/lufs_scanner.py` — 40–106 (`start/stop`, direct `db.conn` use)
- `core/services/discord_rpc.py` — 51, 85, 174 (`start`/`stop`)
- `utils/cache_manager.py` — 1–453 (`_executor`, `download_audio_stream`, `save_cover_from_url`)
- `main.py` — 112–161 (global excepthooks), 280–439 (composition root), 490–584 (shutdown paths)
- `setup_pyinstaller.spec` — 27–36 (`extra_datas` — no `plugins` entry)
- `tests/test_lazy_service_deadlock.py` — 1–102; `tests/test_db_core_fixes_f2.py` — 500–623; `tests/test_provider_loading.py` — 110–120; `tests/test_offline_mode.py` — 60–75; `tests/test_offline_resolve_callbacks.py` — 40–60

**Callee ownership note:** defects found *inside* `core/database.py::close()`, `core/proxy.py`, `core/api.py`, `services/zapret_service.py`, `services/watchdog_service.py`, `audio/engine.py` are attributed to their owning areas (WN-12, WN-11, WN-03..WN-10, WN-26, WN-25, WN-17). Only the *way AppCore wires or uses them* is charged to WN-02.

---

### 2. Findings

#### F-WN-02-1  [P1] — `cleanup()`'s `shutdown(wait=False)` does not let the app exit: an in-flight auto-cache yt-dlp download keeps the whole process alive for its full duration

- **File:** `core/app.py:361-374` (trigger), `core/app.py:571-586` (the shutdown that fails to stop it); `utils/cache_manager.py:289-397` (the long task)
- **Confirmed:** yes
- **Description:** `AppCore.cleanup()` tears the thread pools down with `shutdown(wait=False, cancel_futures=True)`. That cancels *queued* work only; a *running* yt-dlp download is unaffected. CPython registers `concurrent.futures.thread._python_exit` via `threading._register_atexit`, and that handler **joins every pool worker thread** at interpreter finalisation. The window therefore disappears but the *process* stays alive until the download finishes.
- **Cause:** the teardown treats "pool shut down" as "no work in flight", but `ThreadPoolExecutor.shutdown(wait=False)` only stops *accepting* work. The `auto_cache_streams` default is `True` (`core/settings.py:147`), so a stream resolution schedules a real yt-dlp download through `CacheManager._executor` (`utils/cache_manager.py:393`) — the exact task the pool shutdown cannot interrupt.
- **Trigger conditions:** the user resolves a stream while `storage.auto_cache_streams` is on (default) and closes the app while that download is still running. The 5 s `threading.Timer` delay (`core/app.py:372`) makes it easy to hit.
- **User impact:** the window closes but NeDotify stays in the task manager / tray-less "ghost process" for the whole download (tens of seconds to minutes for a long track), then exits. If the user relaunches, the single-instance mutex (`main.py:287-301`) has already been released by `on_closed`, so a second instance can start while the first is still draining — two processes against the same `~/.nedotify` DB.
- **Evidence:**
  ```python
  # core/app.py:361-374
  if self.settings and self.settings.get("storage", "auto_cache_streams", False):
      def delayed_download():
          ...
              self.cache.download_audio_stream(source, source_id, stream_url)
      ...
      _t = threading.Timer(5.0, delayed_download)
      _t.daemon = True
      _t.start()
  ```
  ```python
  # core/app.py:583-586
  try:
      _pool.shutdown(wait=False, cancel_futures=True)
  except Exception:
      logger.debug("Thread pool shutdown failed", exc_info=True)
  ```
- **Reproduction / verification:** isolated probe in `%TEMP%\opencode\pool_probe.py` on the project venv (CPython 3.14.7): a pool task sleeping 4 s, `shutdown(wait=False, cancel_futures=True)` returns at **0.30 s**, but the *process* wall clock is **4.13 s**:
  ```
  shutdown(wait=False) returned at 0.30s
  threads alive: ['MainThread', 'probe_0']
  TOTAL WALL: 4,13s
  ```
  The same applies to `CacheManager._executor` (`utils/cache_manager.py:31`, `max_workers=2`) and to every provider pool listed at `core/app.py:572-580`.
- **Suggested fix:** make the teardown *drain-aware*: before shutting the pools down, stop feeding them (`_shutting_down` must gate `download_audio_stream`), then use `shutdown(wait=True, cancel_futures=True)` with an explicit timeout budget, and `os._exit()` after a bounded grace period instead of relying on the interpreter's join.
- **Fix side effects:** `wait=True` can block the exit for the full download; cancelling a yt-dlp download mid-flight leaves a `.part` file in `~/.nedotify/streams/` (the cache writer does not clean partials). A bounded grace period + `os._exit()` trades a clean temp file for a prompt exit.
- **Discovered by:** B

#### F-WN-02-2  [P1] — The proxy self-heal path bypasses `StreamResolver`'s single-flight and spawns one unbounded OS thread per call

- **File:** `core/app.py:296-506` (esp. 499–506), `core/app.py:305-506` (`worker`), `core/proxy.py:1051` (the call site), `core/resolver.py:165-230` (the single-flight that is bypassed)
- **Confirmed:** yes
- **Description:** `re_resolve_stream_url_async` starts a **new `threading.Thread` per invocation** with no semaphore, no executor and no cap, and it calls `service.get_stream_url(...)` **directly** instead of going through `StreamResolver.resolve()`. The resolver's single-flight (one network cascade per `(source, source_id)`, `core/resolver.py:187-224`) therefore does not apply to this path — the only caller that uses it is `audio/engine.py:149`.
- **Cause:** the self-heal path was written as a standalone callback cascade rather than as a `StreamResolver` client, so it re-implements resolution instead of reusing the coordinator that exists precisely to de-duplicate it.
- **Trigger conditions:** any burst of concurrent proxy stream requests whose upstream answers 403/410 (expired googlevideo URLs). `core/proxy.py` is a `ThreadingHTTPServer` — one thread per connection (`core/proxy.py:439`) — and each such request calls `re_resolve_stream_url_async` at `core/proxy.py:1051`. A 50-track playlist with expired URLs therefore produces 50 concurrent resolution threads, each potentially running a yt-dlp extraction (a subprocess) plus up to ~6 SoundCloud candidate searches.
- **User impact:** a CPU/memory spike and provider rate-limiting right when the app is already struggling; concurrent extractions of the *same* track waste the provider budget; each thread also holds the whole `AppCore` object graph alive (the closure captures `self` and the proxy handler frame).
- **Evidence:**
  ```python
  # core/app.py:499-506
  try:
      if offline_result():
          return
      service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
  except Exception as e:
      _on_err(str(e))

  threading.Thread(target=worker, daemon=True).start()
  ```
  ```python
  # core/proxy.py:1042-1052
  def _on_resolved(url, metadata=None):
      nonlocal new_url
      new_url = url
      resolve_event.set()

  self.server.app_core.re_resolve_stream_url_async(source, source_id, _on_resolved)
  resolve_event.wait(timeout=7)
  ```
  `_SC_FALLBACK_BUDGET_S = 20.0` (`core/app.py:44`) bounds *wall-clock per resolution*, not the *number* of concurrent resolutions.
- **Reproduction / verification:** grep for callers of the resolution entry points: `api.py:1604`, `api.py:1744`, `proxy.py:1051` all call `re_resolve_stream_url_async`; `resolver.resolve(` appears exactly once, at `audio/engine.py:149`. Reading `core/app.py:296-506` shows no semaphore/executor/counter anywhere in the path.
- **Suggested fix:** route the self-heal through `StreamResolver.resolve()` (or a dedicated single-flight keyed on `(source, source_id)`), and bound the number of concurrent resolutions with a small fixed-size executor instead of `threading.Thread`.
- **Fix side effects:** the proxy's 7 s `resolve_event.wait(timeout=7)` (`core/proxy.py:1052`) is shorter than the 20 s fallback budget, so a shared single-flight would make the proxy give up on a resolution another caller is still working on; the two budgets need to be reconciled.
- **Discovered by:** B

#### F-WN-02-3  [P2] — `cleanup()` closes the database *before* stopping the pools that use it, and `DatabaseManager.close()` is not a barrier: the DB reopens and stays writable

- **File:** `core/app.py:559-560` (db.close) vs `core/app.py:571-586` (pool shutdowns); `core/database.py:2459-2489` (`close`), `core/database.py:179-205` (`_get_connection`/`conn`)
- **Confirmed:** yes
- **Description:** the teardown closes the DB first and shuts the executors down afterwards. `DatabaseManager.close()` cannot close another thread's connection (sqlite3 refuses a cross-thread close), and it sets the *calling* thread's slot to `None` — so the very next `self.db.conn` opens a **brand-new connection**. "The DB is closed" is therefore not a barrier: after `cleanup()` the database is fully open and writable again, and the still-running pools keep writing to it.
- **Cause:** `close()` was written as "release the handles I own", not as "make this manager terminal"; and the shutdown order in `AppCore.cleanup()` places the DB teardown ahead of the workers that depend on it.
- **Trigger conditions:** any shutdown that overlaps an in-flight provider / downloader / cache task — i.e. essentially every shutdown with a download or stream resolution running.
- **User impact:** writes land in `~/.nedotify/nedotify_storage.db` after "cleanup" finished (download rows, cached-stream rows, settings), and every connection opened after `close()` is added to `_all_conns` and never closed — a per-shutdown connection leak. The user can also observe the app still writing to the DB after the window is gone.
- **Evidence:**
  ```python
  # core/app.py:555-560 (order: stop cache loop -> flush settings -> close DB)
  if getattr(self, "_cache_cleanup_stop", None) is not None:
      _step("cache_cleanup.stop", self._cache_cleanup_stop.set)
  if getattr(self, "settings", None) and hasattr(self.settings, "flush"):
      _step("settings.flush", self.settings.flush)
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)
  ```
  ```python
  # core/app.py:571-586 — the pools are shut down AFTER the DB was closed
  _step("base_service pool", _shutdown_shared_pool)
  for _pool in (...):
      _pool.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # core/database.py:2470-2471 — close_thread_connection() nulls only the caller's slot
  self._checkpoint_wal()
  self.close_thread_connection()
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\dbclose_probe.py` on a temp DB:
  ```
  main conn id: 2292149645328
  after close(), _local.connection is: None
  main conn after close() id: 2292154848240 -> reopened a NEW connection: True
  write after close() succeeded; rows: [<sqlite3.Row object ...>]
  worker conn usable after db.close(): {'worker_ok': True}
  1 database connection(s) could not be closed from the main thread (created on another thread)
  ```
- **Suggested fix:** (a) make `DatabaseManager.close()` terminal (a `_closed` flag that makes `_get_connection()` refuse or reuse a closed handle); (b) reverse the order in `AppCore.cleanup()` — stop the producers first, then drain the pools, then flush settings, then close the DB last.
- **Fix side effects:** a terminal `close()` would break the tests that reuse a `DatabaseManager` after closing it and `core/database.py`'s own `_init_database()` path; the reordering delays the WAL checkpoint by the pool drain time. **Root-cause owner for `close()` semantics: WN-12.**
- **Discovered by:** B

#### F-WN-02-4  [P2] — `PluginManager.plugins_dir` is derived from `__file__` with no `sys._MEIPASS` branch: in the packaged build the plugin folder is the per-launch temp dir and user plugins never load

- **File:** `core/plugins.py:26-33`; compare `core/tray.py:38`, `core/proxy.py:158`, `services/zapret_service.py:326`
- **Confirmed:** yes
- **Description:** the plugin directory is computed as the parent of the parent of `core/plugins.py`. In a PyInstaller build `__file__` resolves under `sys._MEIPASS`, so `plugins_dir` becomes `<_MEIPASS>/plugins` — a directory inside the per-launch temp tree that (a) contains no user plugins and (b) is deleted when the app exits. The plugin feature is therefore dead in the shipped Windows product, and the code additionally *creates* that stray directory inside the temp tree.
- **Cause:** the path was derived from the source-tree layout, violating the project's own non-negotiable contract #9 ("Frozen vs source assets: any asset lookup needs both `getattr(sys, "_MEIPASS", ...)` branches or it breaks in the packaged exe"). Three sibling modules in the same codebase already do it correctly.
- **Trigger conditions:** any packaged (frozen) run of the Windows app.
- **User impact:** a user who drops a plugin next to `NeDotify.exe` sees it silently ignored — no warning, no log line about the wrong directory — and `general.plugins_enabled` has no effect at all.
- **Evidence:**
  ```python
  # core/plugins.py:26-33
  self.plugins_dir = os.path.join(
      os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
      'plugins'
  )
  try:
      os.makedirs(self.plugins_dir, exist_ok=True)
  except Exception as e:
      logger.warning(f'Could not create plugins dir {self.plugins_dir}: {e}')
  ```
  ```python
  # core/tray.py:38 — the pattern used elsewhere in the same codebase
  base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  ```
  `setup_pyinstaller.spec:27` (`extra_datas = [('ui/web_new_v2', ...), ('ui/MACos_ui', ...)]`) contains **no** `plugins` entry, so nothing is bundled either.
- **Reproduction / verification:** probe `%TEMP%\opencode\plugin_probe.py` (unfrozen) prints `plugins_dir = <repo>\plugins`; in a frozen build the same expression yields `sys._MEIPASS\plugins` because PyInstaller sets `__file__` to `os.path.join(sys._MEIPASS, 'core', 'plugins.py')`. `grep -n "sys.path" core/plugins.py` → only the docstring at line 5 (contract holds, see §3). **Packaging-side counterpart: WN-01.**
- **Suggested fix:** resolve the plugin directory as `~/.nedotify/plugins` (user data, survives upgrades) with a `sys._MEIPASS` fallback for a bundled sample plugin; log the resolved directory at INFO so a user can see where the loader looked.
- **Fix side effects:** moving the directory changes the meaning of the existing `general.plugins_enabled` flag and invalidates any plugin a user already placed in the old location; the loader would need to look in both places for one release.
- **Discovered by:** B

#### F-WN-02-5  [P2] — A plugin whose `setup()` raises is never registered and never torn down; its module stays in `sys.modules` and its side effects leak

- **File:** `core/plugins.py:91-107` (load), `core/plugins.py:109-120` (`unload_all`)
- **Confirmed:** yes
- **Description:** `module.setup(self._core)` is called **before** `self.plugins.append(module)`. If `setup()` raises, the exception escapes to the outer `except`, the module is never registered, and — because the `sys.modules.pop` on the failure path only covers `exec_module` failures (line 96) and the "no setup attribute" path (line 104) — the half-initialised module **stays in `sys.modules['aura_plugins.<name>']`**. `unload_all()` iterates `self.plugins` only, so the plugin's `teardown()` is never called.
- **Cause:** registration happens after the side-effecting call, so a partially-initialised plugin has no owner and therefore no teardown path.
- **Trigger conditions:** a plugin whose `setup()` starts a thread, registers a timer or opens a socket and then raises.
- **User impact:** the plugin's background work keeps running for the rest of the session with no way to stop it, the module stays importable under `aura_plugins.*` for the whole process lifetime, and the only trace is one `logger.error` line.
- **Evidence:**
  ```python
  # core/plugins.py:99-107
  if hasattr(module, 'setup') and callable(module.setup):
      module.setup(self._core)
      self.plugins.append(module)
      logger.info(f'Loaded plugin: {module_name}')
  else:
      sys.modules.pop(qualified_name, None)
      logger.warning(f'Plugin {module_name} missing setup(app_core) function. Ignored.')
  except Exception as e:
      logger.error(f'Failed to load plugin {module_name}: {e}', exc_info=True)
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\plugin_probe.py` (a plugin whose `setup()` records a side effect and then raises):
  ```
  registered plugins: []
  'aura_plugins.boom_plugin' still in sys.modules: True
  module side effect recorded: ['started-thread']
  after unload_all, module still in sys.modules: True
  teardown ever called: False
  ```
- **Suggested fix:** append the module to `self.plugins` *before* calling `setup()`, and wrap `setup()` so that a failure triggers the module's own `teardown()` (if present) plus `sys.modules.pop`.
- **Fix side effects:** registering before `setup()` means `unload_all()` will call `teardown()` on a plugin that never completed setup — `teardown()` must tolerate a partially-initialised module.
- **Discovered by:** B

#### F-WN-02-6  [P2] — The zapret shutdown guard is a pre-check only: a 30–40 s binary download inside `ZapretService.start()` can launch an orphaned **elevated** `winws.exe` after `cleanup()` has finished

- **File:** `core/app.py:267-292` (the guard), `core/app.py:534-539` (5 s join), `core/app.py:553-554` (`zapret.stop()`); `services/zapret_service.py:1078-1085`, `:1093-1108`, `:1150`, `:1167+` (`_launch` → `Popen`/`ShellExecuteW runas`)
- **Confirmed:** yes (code path proven; the orphan itself needs a live run)
- **Description:** the autostart worker checks `_shutting_down` **before** calling `self.zapret.start(...)` (`core/app.py:270`). `ZapretService.start()` may then spend 30–40 s downloading the winws bundle (`_download_zip(..., timeout=30.0/40.0)`, `services/zapret_service.py:893`/`974`) before it reaches `_launch()`. `cleanup()` waits only **5 s** for that thread and then calls `zapret.stop()` — which finds nothing running. The download finishes afterwards and `Popen`/`ShellExecuteW(runas)` starts an elevated `winws.exe` that nobody will ever stop.
- **Cause:** the shutdown guard is a point-in-time check, not a cancellation; the join budget (5 s) is far shorter than the operation it is waiting for (30–40 s).
- **Trigger conditions:** zapret enabled + `auto_start` on, and the winws binary is not yet on disk (first run, or after a user deletes it) — the download then runs during the app's own lifetime. Closing the app during that window orphans the process.
- **User impact:** a DPI-bypass process running **with administrator rights** survives the app it belongs to, for the rest of the session or indefinitely; the user has no UI indication that it is there, and the next launch adopts it (`services/zapret_service.py:1300-1324`).
- **Evidence:**
  ```python
  # core/app.py:267-273
  def _start_worker():
      # Re-checked on this thread: cleanup() may have started
      # between the check below and here.
      if self._shutting_down.is_set():
          logger.info("Zapret autostart skipped: shutdown in progress")
          return
      self.zapret.start(mode=mode, custom_args=custom_args, binary_path=binary_path)
  ```
  ```python
  # core/app.py:534-539 — 5 s is far less than the 30-40 s download inside start()
  _zapret_thread = getattr(self, "_zapret_start_thread", None)
  if _zapret_thread is not None and _zapret_thread.is_alive():
      try:
          _zapret_thread.join(5)
      ```
  ```python
  # services/zapret_service.py:1078-1085 — download happens inside start()
  logger.info("Zapret binary not found. Attempting automatic download...")
  ok, dl_msg = self.download_binaries()
  ```
- **Reproduction / verification:** code-path trace: `core/app.py:270` (guard passes) → `core/app.py:273` → `services/zapret_service.py:1080` (30–40 s) → `core/app.py:537` (join times out at 5 s) → `core/app.py:554` (`zapret.stop()`, nothing running) → download completes → `services/zapret_service.py:1150` `_launch()` → `services/zapret_service.py:1167` `subprocess.Popen(...)` / the elevated `ShellExecuteW` path at `:1300+`. Not executed end-to-end (running the real app is out of bounds for this audit).
- **Suggested fix:** pass a cancellation callback / `threading.Event` into `ZapretService.start()` and re-check it after the download and immediately before `_launch()`; raise the join budget to cover the download or abort the download on shutdown.
- **Fix side effects:** aborting the download leaves a partially extracted bundle in `~/.nedotify/zapret/`; the zip writer must be atomic (extract to a temp dir, then rename).
- **Discovered by:** B

#### F-WN-02-7  [P2] — `update_ytdlp_safely()` runs `pip install -U yt-dlp[default]` *during* a normal launch, in the background — the exact thing its own comment says must never happen

- **File:** `core/app.py:47-88` (esp. 64–80), `core/app.py:150-151` (the launcher)
- **Confirmed:** yes
- **Description:** the function's stated invariant is "never pip-install while the app is running (can break the imported yt_dlp mid-session) — schedule the update for the next launch instead". The implementation defers by one *launch*, but the install then runs **inside** that launch, on a background thread, while the app is fully running. `pip install -U` unconditionally replaces the `yt_dlp` package on disk while the process has `yt_dlp` imported and in use (e.g. a cache download at `utils/cache_manager.py:316`).
- **Cause:** the "deferred" flag is consumed at the *start* of the next launch, so the pip invocation happens in exactly the situation the comment forbids. The "stamp" logic also ping-pongs: launch 1 writes the pending file, launch 2 installs, launch 5 installs again, launch 8 again — i.e. the upgrade fires roughly every third launch after the 24 h window, not once per day.
- **Trigger conditions:** any unfrozen (source/venv) run; the install fires on the 2nd, then every 3rd launch after 24 h. In the packaged build `getattr(sys, 'frozen', False)` short-circuits it (`core/app.py:49-50`), so the packaged app is unaffected.
- **User impact:** in a dev/portable install the app silently mutates its own virtualenv from PyPI without user consent, on an unpinned `-U` upgrade (a new major version can be pulled in), and can break an in-flight `yt_dlp` call mid-download (`ImportError` on a partially replaced package). From a supply-chain point of view this is an unattended, unconditional self-update of a network-parsing dependency.
- **Evidence:**
  ```python
  # core/app.py:64-80
  # M-5: never pip-install while the app is running (can break the imported
  # yt_dlp mid-session) — schedule the update for the next launch instead.
  if not os.path.exists(pending_file):
      pathlib.Path(pending_file).touch()
      logger.info("yt-dlp update deferred to next launch (never mid-run).")
      return

  try:
      os.remove(pending_file)
  except OSError:
      pass
  # M-5: stable releases only (no --pre)
  result = subprocess.run(
      [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
      capture_output=True,
      timeout=120,
  )
  ```
  ```python
  # core/app.py:150-151 — started on every unfrozen, online launch
  if not is_offline(self.settings):
      threading.Thread(target=update_ytdlp_safely, daemon=True).start()
  ```
- **Reproduction / verification:** trace the state machine over consecutive launches: (1) no stamp → pending created → return; (2) no stamp, pending exists → pending removed → **pip install runs** → stamp written; (3) age < 24 h → skip; (4) age ≥ 24 h, no pending → pending created → return; (5) age ≥ 24 h, pending exists → **pip install runs** again. The install therefore always happens while the app is running.
- **Suggested fix:** either drop the self-update entirely (the packaged app never uses it) or move it to an explicit, user-triggered action with a pinned version and an integrity check; if it stays automatic, pin the version and run it *before* the app imports `yt_dlp`.
- **Fix side effects:** removing it means dev installs stop receiving yt-dlp fixes automatically — which is the correct trade for a silent, unpinned self-upgrade of a security-relevant dependency.
- **Discovered by:** B

#### F-WN-02-8  [P2] — `restore_session()` performs no type validation: a non-numeric `last_position` aborts the *entire* session restore, queue included

- **File:** `core/session.py:70-89`; consumer `main.py:314-330`
- **Confirmed:** yes
- **Description:** `restore_session()` returns the persisted values verbatim. `main.py` parses the position with `float(session_data.get("position") or 0.0)` inside the *same* `try` block that restores the queue, so a single corrupt `session.last_position` value discards the queue, the shuffle flag, the repeat mode and the restored position together.
- **Cause:** the session blob is treated as trusted, well-typed data; nothing validates or coerces it at the boundary.
- **Trigger conditions:** a partially written / hand-edited / migrated `settings` row, a value written by an older build with a different type, or a `last_position` written as a string.
- **User impact:** the user relaunches the app and the whole queue, playback position and shuffle/repeat state are gone, with only a bare `print("Failed to restore session: ...")` on stdout (`main.py:330`) — no entry in `~/.nedotify/logs/app.log` and nothing in the UI.
- **Evidence:**
  ```python
  # core/session.py:72-80
  session = {
      "track_id": self.settings.get("session", "last_track_id"),
      "position": self.settings.get("session", "last_position", 0),
      "volume": self.settings.get("session", "last_volume", 70),
      "queue": self.settings.get("session", "last_queue", []),
      "queue_index": self.settings.get("session", "last_queue_index", 0),
      "shuffle": self.settings.get("session", "shuffle", False),
      "repeat": self.settings.get("session", "repeat", "off"),
  }
  ```
  ```python
  # main.py:314-330 — one try wraps the parse AND the queue restore
  try:
      session_data = app_core.session.restore_session()
      queue = session_data.get("queue")
      session_position_sec = float(session_data.get("position") or 0.0)
      if queue:
          app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
          ...
  except Exception as e:
      print(f"Failed to restore session: {e}")
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\sess_probe.py`: after `st.set("session", "last_position", "not-a-number")`, `float(session_data["position"])` raises `ValueError: could not convert string to float: 'not-a-number'` — exactly the exception that aborts `main.py`'s restore block.
- **Suggested fix:** validate and coerce in `SessionManager.restore_session()` (numeric `position`/`volume`/`queue_index`, `queue` must be a list of dicts, `shuffle`/`repeat` must be bool/enum); return per-field defaults instead of raising, and log a warning naming the offending field.
- **Fix side effects:** a stricter reader will silently reset a session whose values were written in an unexpected but previously tolerated shape (e.g. `repeat` as an int) — the coercion table must cover the shapes the current writer can produce.
- **Discovered by:** B

#### F-WN-02-9  [P2] — `restore_session()` hands out and mutates the live `SettingsManager` cache: the restored queue aliases the settings cache

- **File:** `core/session.py:76`, `core/session.py:82-87`; `core/settings.py:368-370` (`get` returns the cached object by reference); `audio/queue.py:119-124` (`set_tracks` copies the *list*, not the dicts), `audio/queue.py:24-28` (`current_track` returns the live dict)
- **Confirmed:** yes
- **Description:** `SettingsManager.get()` returns the cached object itself, not a copy. `restore_session()` therefore puts the *live* `session.last_queue` list into the returned dict and then **mutates each track dict in place** (`track["file_path"] = None; track["resolved_at"] = 0`). `main.py:319` passes that list to `engine.queue.set_tracks(...)`, which copies the list but keeps the same dict objects — so the playback queue's track dicts *are* the settings cache's track dicts.
- **Cause:** `SessionManager` reaches into another object's private cache instead of working on a copy; `SettingsManager.get()` does not hand out immutable snapshots for container values.
- **Trigger conditions:** every normal app start.
- **User impact:** any later in-place mutation of a queued track (for example `track["duration"] = dur` at `audio/engine.py:194`, or `resolved_at` updates) writes straight into the settings cache, so the persisted session blob and the in-memory queue diverge and the session that gets saved on exit can contain fields the queue never intended to persist. `restore_session()` is also not idempotent — a second call operates on the already-mutated list.
- **Evidence:**
  ```python
  # core/session.py:76 and 82-87
  "queue": self.settings.get("session", "last_queue", []),
  ...
  for track in session.get("queue", []):
      if not isinstance(track, dict):
          continue
      if track.get("source") in ("youtube", "soundcloud", "vk"):
          track["file_path"] = None
          track["resolved_at"] = 0
  ```
  ```python
  # core/settings.py:368-370 — the cached object is returned as-is
  with self._lock:
      if category in self._cache and key in self._cache[category]:
          val = self._cache[category][key]
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\sess_probe.py`:
  ```
  cached list id: 1923402009152
  restore_session() queue is the SAME object as the settings cache list: True
  mutated cache entry now: {'id': 1, ..., 'file_path': None, 'resolved_at': 0}
  cache list now has file_path/resolved_at keys: True True
  ```
- **Suggested fix:** `restore_session()` should build its result from a deep copy of the persisted queue; `SettingsManager.get()` should return a copy for mutable container values (or expose an explicit `get_copy`).
- **Fix side effects:** deep-copying a 200-track queue on every restore costs a few hundred microseconds — negligible, but `SettingsManager.get()` returning copies would change the behaviour of the many hot call sites that currently rely on getting the live list (`core/settings.py:388-392`).
- **Discovered by:** B

#### F-WN-02-10  [P2] — `AppCore.cleanup()` is not the single authoritative teardown: `AppApi.cleanup()` is a second one, owned by nobody, and it is skipped entirely on the watchdog-restart path

- **File:** `core/app.py:508-586` (`AppCore.cleanup`), `core/app.py:530-531` (the core reaching into the bridge); `core/api.py:446-459` (`AppApi.cleanup`); `main.py:529-532` (watchdog path) vs `main.py:575-579` (normal path)
- **Confirmed:** yes
- **Description:** the application has two teardown paths that do not know about each other. `AppApi.cleanup()` owns the bridge's `_search_executor` (6 workers), `_prefetch_executor` (2 workers) and the tray icon; `AppCore.cleanup()` owns everything else. `main.py` calls them in sequence — `app_core.cleanup()` **then** `api.cleanup()` — so the bridge's executors are still live while the core is closing the DB underneath them. And on the startup-watchdog restart path (`main.py:529-532`) `api.cleanup()` is **never called at all**, so the bridge's executors and the tray thread are left running until `os._exit(3)`.
- **Cause:** the composition root (`main.py`) owns the lifecycle but the lifecycle is split across two objects that each own half of it, and one of the two is invoked from the outside rather than from the core.
- **Trigger conditions:** every normal shutdown; the watchdog path only when the WebView2 bridge fails to initialise within 35 s.
- **User impact:** in-flight bridge searches/prefetches run against a database the core already declared closed; the tray icon is not stopped on the watchdog path (mitigated only by `os._exit`); and `AppCore.cleanup()` cannot be reasoned about as "the teardown" — a reader must know that `main.py` calls a second function afterwards.
- **Evidence:**
  ```python
  # core/app.py:528-531 — the core depends on the bridge for one teardown step
  # Wait for an in-flight zapret autostart before stopping zapret, so the
  # start cannot finish (and spawn the process) after stop() returned.
  if getattr(self, 'api', None) and hasattr(self.api, 'flush_listening'):
      _step('listening history', self.api.flush_listening)
  ```
  ```python
  # core/api.py:446-459 — a second, independent teardown
  def cleanup(self):
      """O-15: release the shared search executor without blocking app exit."""
      try:
          if getattr(self, "_tray", None):
              self._tray.stop()
      ...
          if getattr(self, "_search_executor", None) is not None:
              self._search_executor.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # main.py:575-579 — the normal path
  app_core.cleanup()
  try:
      api.cleanup()
  ```
  ```python
  # main.py:529-532 — the watchdog path: no api.cleanup()
  try:
      app_core.cleanup()
  except Exception:
      logging.debug("_startup_watchdog: suppressed exception", exc_info=True)
  ```
  The back-reference is installed by the bridge, not the core: `core/api.py:347` `self._core.api = self`.
- **Reproduction / verification:** read the two shutdown paths side by side: `main.py:529-539` (watchdog → `app_core.cleanup()` → `os._exit(3)`, **no** `api.cleanup()`) vs `main.py:573-580` (normal → `app_core.cleanup()` → `api.cleanup()` → `sys.exit(0)`); `core/api.py:446-459` is the only definition of `AppApi.cleanup`; `core/app.py:508-586` is the only definition of `AppCore.cleanup` and it never calls `self.api.cleanup()` (it only calls `self.api.flush_listening` at `:531`).
- **Suggested fix:** make `AppCore` the single owner of the bridge's resources: construct `AppApi` from inside `AppCore` (or register it with `AppCore.register_teardown(api.cleanup)`), so `AppCore.cleanup()` runs every teardown exactly once in a declared order.
- **Fix side effects:** `AppCore.__init__` currently does not know about `AppApi`; moving the construction into the core creates a `core.app → core.api` import (currently only `main.py` imports `core.api`) — check for an import cycle (`core.api` imports `core.offline`, `core.user_errors`, `utils.stream_urls`; it does **not** import `core.app`, so the cycle risk is low).
- **Discovered by:** B

#### F-WN-02-11  [P2] — The YouTube→SoundCloud fallback cascade exists in two divergent copies: `AppCore.re_resolve_stream_url_async` and `AudioEngine._resolve_via_network`

- **File:** `core/app.py:379-497` vs `audio/engine.py:213-330`
- **Confirmed:** yes
- **Description:** the same provider policy — "YouTube extraction failed → look the track up on SoundCloud → strip noise from the title/artist → try N query variants" — is implemented twice, with copy-pasted regexes, and the two copies have already diverged: the engine caps the candidate list at 3 and applies a per-stage timeout (2.5 s search / 3.0 s stream) plus a 20 s cascade deadline; the `AppCore` copy builds up to ~6 candidates, has **no per-stage timeout** and uses a separate 20 s budget constant (`_SC_FALLBACK_BUDGET_S`, `core/app.py:44`).
- **Cause:** the fallback was re-implemented when the proxy self-heal path was added, instead of being extracted into a shared resolver component.
- **Trigger conditions:** any YouTube extraction failure — i.e. every expired/blocked/Deleted video.
- **User impact:** the two paths have different latency profiles (the proxy path can block a handler thread much longer per candidate), and a fix applied to one copy — e.g. adding a provider, tightening the noise regex, adding a per-stage timeout — silently does not apply to the other. A single behavioural change to the fallback policy now has to be made in two places or the app behaves differently depending on which entry point resolved the track.
- **Evidence:**
  ```python
  # audio/engine.py:279-305 — 3 candidates, per-stage timeouts
  candidates = _build_queries(track_artist, track_title)[:3]
  for sc_query in candidates:
      if time.monotonic() >= cascade_deadline:
          break
      ...
      remaining = max(0.5, cascade_deadline - time.monotonic())
      sc_event.wait(timeout=min(2.5, remaining))
  ```
  ```python
  # core/app.py:446-492 — unbounded candidate count, no per-stage timeout
  def try_search_candidates(idx=0, _started=None):
      ...
      if idx >= len(candidates) or elapsed > _SC_FALLBACK_BUDGET_S:
      ...
      self.soundcloud.search(sq, max_results=3, callback=on_sc_search_res, error_callback=on_sc_search_err)
  ```
  The identical `clean_noise` regex body appears at `audio/engine.py:237-242` and `core/app.py:411-416`.
- **Reproduction / verification:** diff the two blocks: `core/app.py:411-416` vs `audio/engine.py:237-242` (identical regexes), `core/app.py:440-444` vs `audio/engine.py:268-273` (identical de-duplication), and the differing candidate cap (`core/app.py:440-444` has no `[:3]`) and the differing per-stage timeouts.
- **Suggested fix:** extract one `SoundCloudFallback` component (query building + budget + per-stage timeouts) and have both `AudioEngine` and `AppCore.re_resolve_stream_url_async` call it; keep the single 20 s budget in one place.
- **Fix side effects:** the engine's current 3-candidate/2.5 s behaviour would become the shared behaviour, changing the proxy path's success rate and latency; this is a behavioural change that needs a side-by-side measurement. **Owner for the engine copy: WN-17.**
- **Discovered by:** B

#### F-WN-02-12  [P3] — The resolve callback is invoked with no exception guard: an exception kills the resolution thread and the UI is never told

- **File:** `core/app.py:376-377`, `core/app.py:300-303`, `core/app.py:342-345`
- **Confirmed:** yes
- **Description:** `re_resolve_stream_url_async` invokes the caller's `callback` / `on_error` with no `try/except`. The callbacks reach `AppApi._on_track_changed` → `_enrich_track_lufs` → `proxy.get_proxy_url` → `tray.update_state` (all unguarded in `core/api.py`). An exception there propagates out of `_on_resolved`, kills the worker thread, and the UI never receives the resolved URL or an error.
- **Cause:** the async contract has no error boundary around the consumer-supplied callback.
- **Trigger conditions:** any exception inside the consumer's callback chain (e.g. `self._core.proxy` is `None` during the startup window, or the tray is `None`).
- **User impact:** the track silently never plays — the UI sits in its loading state. `main.py:119-145` installs `threading.excepthook`, so the trace now reaches `app.log` at CRITICAL (this was previously lost entirely), but the user still sees no error and the player does not recover.
- **Evidence:**
  ```python
  # core/app.py:376-377
  if callback:
      callback(stream_url, metadata or {"source": source, "source_id": source_id})
  ```
  ```python
  # core/app.py:300-303 — the offline branch is equally unguarded
  if local and callback:
      callback(local['file_path'], local)
  elif not local and on_error:
      on_error('В офлайн-режиме доступна только сохранённая музыка')
  ```
- **Reproduction / verification:** read `core/app.py:296-506` — there is no `try`/`except` around any of the four `callback(...)` / `on_error(...)` call sites (lines 301, 303, 335, 343, 345, 377, 464, 475, 486, 497). `grep -n "threading.excepthook" main.py` → `main.py:142` confirms the exception is logged but not surfaced to the UI.
- **Suggested fix:** wrap every consumer callback in `try/except`, log with `exc_info=True`, and route the failure to the `on_error` channel so the UI can leave its loading state.
- **Fix side effects:** swallowing the exception changes the semantics for the two in-tree callers (`core/api.py:1604`, `core/api.py:1744`, `core/proxy.py:1051`), which currently rely on the exception propagating to kill the thread in order to stop waiting — `core/proxy.py:1052` waits on an `Event` that the callback sets *before* it can raise, so the proxy is unaffected.
- **Discovered by:** B

#### F-WN-02-13  [P3] — The lazy-service `RLock` is documented as load-bearing but is no longer nested; the test that claims to guard it cannot fail

- **File:** `core/app.py:96-101` (comment + lock), `core/app.py:187-234` (the three lazy properties), `core/app.py:213-230` (`recommendations`); `tests/test_lazy_service_deadlock.py:15-19`
- **Confirmed:** yes
- **Description:** the comment at `core/app.py:96-101` states that `recommendations` "acquires this lock and then reads `self.soundcloud`, which acquires it again". The current code resolves `self.soundcloud` and `self.youtube` **before** taking the lock (`core/app.py:219-220`, with the reason spelled out in the comment at `:216-218`), so there is no nested acquisition left anywhere and the `RLock` is no longer required for that reason. The guarding test asserts only that a lock *the test itself just assigned* is an `RLock` — it never executes `core/app.py:101`.
- **Cause:** the code was restructured (dependencies hoisted out of the critical section) but the rationale comment and the test were left behind, so the regression guard now guards nothing.
- **Trigger conditions:** any future change that reintroduces a nested acquisition (or that switches `threading.RLock()` → `threading.Lock()` at `core/app.py:101`) — the test suite would not notice.
- **User impact:** none today; the risk is a silent reintroduction of the self-deadlock the comment describes ("every later reader (search, home feed) blocks on it, and no provider is ever dispatched"), which would present as a UI stuck on "Поиск..." forever.
- **Evidence:**
  ```python
  # core/app.py:213-230 — dependencies are resolved BEFORE the lock
  @property
  def recommendations(self):
      if self._recommendations is None:
          # Resolve dependencies BEFORE taking the lock: these constructors do
          # network I/O, and holding the lock across it would stall every other
          # lazy-property reader (search included) for the whole handshake.
          sc_service = self.soundcloud
          yt_service = self.youtube
          with self._service_lock:
              if self._recommendations is None:
                  ...
  ```
  ```python
  # tests/test_lazy_service_deadlock.py:15-19 — the lock is supplied by the test
  def test_service_lock_is_reentrant():
      assert isinstance(AppCore.__init__.__doc__ or "", (str, type(None)))
      core = AppCore.__new__(AppCore)
      core._service_lock = threading.RLock()
      assert isinstance(core._service_lock, type(threading.RLock()))
  ```
- **Reproduction / verification:** probe `%TEMP%\opencode\lock_probe.py` reproduces the test's exact scenario with a **plain `threading.Lock()`** — the nested access still completes (`plain Lock -> nested lazy access finished within 3s: True`), proving that (a) the current code no longer deadlocks and (b) the test's assertion is independent of `core/app.py:101`.
- **Suggested fix:** either restore a genuine nested acquisition (and keep the `RLock`) or update the comment to match the code; replace the test with one that constructs the lock through the real code path (e.g. a factory method `AppCore._make_service_lock()`) so `core/app.py:101` is actually executed.
- **Fix side effects:** none — the production behaviour is unchanged; only the comment and the test's coupling to the production line change. **Test-file owner: WN-34.**
- **Discovered by:** B

#### F-WN-02-14  [P3] — `AppCore.__init__` is never executed by any test: the entire subsystem wiring is untested

- **File:** `core/app.py:94-185`; evidence in `tests/` (see reproduction)
- **Confirmed:** yes
- **Description:** no test in the suite ever constructs an `AppCore`. Every test that needs one uses `AppCore.__new__(AppCore)` and hand-assigns the attributes it cares about. The constructor — which creates 21 subsystems, starts the proxy server, loads plugins, starts the watchdog observer and the LUFS scanner, starts the Discord RPC, spawns the yt-dlp updater thread and the cache-cleanup thread — has zero coverage.
- **Cause:** the constructor mixes object graph construction with process-level side effects (threads, a listening socket, an FS observer, a subprocess), so it cannot be instantiated in a test.
- **Trigger conditions:** permanent — a regression in the wiring (a subsystem constructed with the wrong argument, a start step that silently fails) is invisible to the suite.
- **User impact:** a broken wiring (e.g. `self.engine.proxy = self.proxy` missing, or `self.discord_rpc.start()` raising) reaches production with no test signal; `AppCore.__init__` has no `try/except` around `self.proxy.start()` (`core/app.py:158`) or `self.plugins.load_plugins()` (`core/app.py:159`), so a failure there aborts startup with a raw traceback.
- **Evidence:** every `AppCore` reference in the suite is `__new__` + manual assignment:
  ```
  tests/test_lazy_service_deadlock.py:17:    core = AppCore.__new__(AppCore)
  tests/test_lazy_service_deadlock.py:23:    core = AppCore.__new__(AppCore)
  tests/test_lazy_service_deadlock.py:63:    core = AppCore.__new__(AppCore)
  tests/test_offline_mode.py:67:    core = AppCore.__new__(AppCore)
  tests/test_provider_loading.py:114:    core = AppCore.__new__(AppCore)
  tests/test_db_core_fixes_f2.py:527/536/545/556/581: AppCore.start_zapret_if_enabled(core)
  tests/test_db_core_fixes_f2.py:619: AppCore.cleanup(core)
  ```
  (`grep -n "AppCore(" tests/*.py` → **no matches**.)
- **Reproduction / verification:** `Select-String -Path "tests\*.py" -Pattern "AppCore\("` → no output; the list above is the complete set of `AppCore` references in `tests/`.
- **Suggested fix:** split the constructor into `AppCore.build()` (pure graph construction, injectable factories) and `AppCore.start()` (side effects), so a test can build the graph with stub factories and assert the wiring; add a smoke test that constructs the real graph against a temp DB.
- **Fix side effects:** splitting the constructor changes `main.py`'s call site and every `__new__`-based test; the `_MEIPASS`/frozen paths must keep working.
- **Discovered by:** B

#### F-WN-02-15  [P3] — `VKService` is constructed on every startup and never used

- **File:** `core/app.py:27` (import), `core/app.py:130` (construction)
- **Confirmed:** yes
- **Description:** `AppCore.__init__` imports and instantiates `VKService(self.settings)`. Nothing in the codebase ever reads `self.vk`. The module comment itself states it has no production consumer (`tests/test_downloader_cancel.py:356`: "Documents the deferred VK download branch: VKService exposes no ...").
- **Cause:** leftover wiring from a deferred feature; the service was kept "for later" at the cost of an eager import and an eager object.
- **Trigger conditions:** every startup.
- **User impact:** the `services.vk_service` module is imported at every startup (import cost + memory) for a service that is never called. `docs/perf/prof_python_startup.md` already flags `core/app.py`'s eager provider imports as ~175 ms of import time.
- **Evidence:**
  ```python
  # core/app.py:27, 130
  from services.vk_service import VKService
  ...
  self.vk = VKService(self.settings)
  ```
  `Select-String -Path "core\*.py","services\*.py","audio\*.py","utils\*.py","main.py" -Pattern "\bkv\b"` → the only hit is `lyrics_lookup.py:134` (`&lv=1&kv=1&tv=-1`, an unrelated NetEase lyric query parameter). `grep "VKService"` → only `core/app.py:27,130`, `services/vk_service.py:16` and the bench harness `tools/bench/pyprof_child.py:256,286`.
- **Reproduction / verification:** `Select-String -Path "core\*.py","services\*.py","audio\*.py","utils\*.py","main.py" -Pattern "\bkv\b"` returns exactly one line (`lyrics_lookup.py:134`, an unrelated NetEase query parameter); `Select-String -Path "core\*.py","services\*.py","audio\*.py","utils\*.py","main.py" -Pattern "VKService"` returns only `core/app.py:27`, `core/app.py:130` and the service's own definition — no consumer of `self.vk` exists anywhere in the tree.
- **Suggested fix:** drop the import and the instance (or make it lazy, like `soundcloud`/`yandex`), so the provider is only constructed when it is actually used.
- **Fix side effects:** if a VK code path is planned, the lazy-property pattern used for `soundcloud`/`yandex` gives the same behaviour without the startup cost.
- **Discovered by:** B

#### F-WN-02-16  [P3] — The untracked `threading.Timer` in `_on_resolved` can fire after `cleanup()` and keeps the whole object graph alive

- **File:** `core/app.py:362-374`
- **Confirmed:** yes
- **Description:** the auto-cache download is scheduled with a bare `threading.Timer(5.0, delayed_download)`. The timer object is not stored, not cancelled at shutdown and not gated on `_shutting_down`; its closure captures `self` (the `AppCore`), which keeps the entire subsystem graph reachable for the timer's lifetime.
- **Cause:** the timer is fire-and-forget, outside the teardown's inventory of things that must be stopped.
- **Trigger conditions:** a stream resolution completes within 5 s of the app being closed.
- **User impact:** a task fires after teardown and calls `self.cache.download_audio_stream(...)` on a shut-down executor (`utils/cache_manager.py:392-396` catches the `RuntimeError`, so no crash) and on a database that `close()` already declared closed — a write after teardown (see F-WN-02-3). The `AppCore` graph also stays alive for up to 5 s after shutdown, which delays reclamation of the proxy server object and the DB handles.
- **Evidence:**
  ```python
  # core/app.py:372-374
  _t = threading.Timer(5.0, delayed_download)
  _t.daemon = True
  _t.start()
  ```
- **Reproduction / verification:** read `core/app.py:296-506` — `_t` is never stored on `self`, never passed to `cleanup()`, and `cleanup()` (`core/app.py:508-586`) contains no timer inventory. `_shutting_down` is checked only in `start_zapret_if_enabled` (`core/app.py:270, 281`).
- **Suggested fix:** keep the timer handles in a list on the core, cancel them in `cleanup()`, and check `_shutting_down` inside `delayed_download` before touching the cache.
- **Fix side effects:** cancelling the timer means the auto-cache download for a track resolved right at shutdown is skipped — the stream is still cached by the normal resolver path, so the loss is limited to the redundant copy.
- **Discovered by:** B

#### F-WN-02-17  [P3] — `ListeningSession.state()` applies the playback rate one interval late

- **File:** `core/listening.py:22-34`, `core/api.py:1347-1351`
- **Confirmed:** yes
- **Description:** `state()` calls `tick(now)` (which uses the **current** `self.playback_rate`) and only afterwards does the caller assign the new rate (`core/api.py:1347` then `:1349`). So the interval that contains a rate change is scaled with the *previous* rate.
- **Cause:** the rate is written after the interval it should have scaled has already been accumulated.
- **Trigger conditions:** the user changes the playback speed while a track is playing.
- **User impact:** `media_seconds` is mis-scaled by up to one heartbeat interval (5 s) × the rate delta per rate change, which feeds the "media listened" statistic and the 80 % completion threshold. The error is bounded and self-correcting on the next interval.
- **Evidence:**
  ```python
  # core/api.py:1347-1351
  session.state(audible, ended=ended)
  try:
      session.playback_rate = min(4, max(.25, float(playback_rate)))
  except (TypeError, ValueError):
      pass
  ```
  ```python
  # core/listening.py:28-29 — the tick uses the rate as it was before the update
  self.seconds += delta
  self.media_seconds += delta * self.playback_rate
  ```
- **Reproduction / verification:** read `core/listening.py:22-34` together with `core/api.py:1332-1353`; the rate assignment strictly follows `session.state(...)`.
- **Suggested fix:** set `session.playback_rate` before calling `session.state(...)` in `core/api.py` (one-line reorder), or have `state()` accept the rate as a parameter.
- **Fix side effects:** none — the reorder makes the interval use the rate the user just selected, which is the intended semantics. **Bridge-side owner: WN-05.**
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

- **The "plugin folder is never added to `sys.path`" contract HOLDS.** `core/plugins.py` contains zero `sys.path` mutations (the only occurrence of the string is the docstring at line 5). The loader uses `importlib.util.spec_from_file_location` under the `aura_plugins.` namespace (`core/plugins.py:82-92`) with `submodule_search_locations` scoped to the plugin's own package, so a `plugins/json.py` cannot shadow the stdlib for the process. `importlib` is not added to `sys.path` either.
- **`plugins_enabled` cannot be flipped from the UI.** `core/api.py:256-257` puts `("general", "plugins_enabled")` in `_BRIDGE_READONLY_SETTINGS`, and `tests/test_api_f1_audit.py:95-112` pins that the bridge refuses every write spelling. So "arbitrary code execution" requires a deliberate out-of-band edit of the settings table — a defensible posture.
- **`cleanup()` isolates every step.** The `_step()` helper (`core/app.py:522-527`) catches and logs each failure independently, so one failing `close()` cannot abort the rest of the teardown. The docstring's claim holds.
- **The zapret shutdown *ordering* is correct** (`_shutting_down` set as the very first act at `core/app.py:519-520`, then join-before-stop at `:534-539` / `:553-554`). The ordering is sound; only the 5 s budget is too short (F-WN-02-6).
- **The lazy-property double-checked locking is correct.** The inner re-check happens *under* the lock and the construction is inside the critical section (`core/app.py:221-229`), so two threads racing on `recommendations` cannot produce two instances or a lost update. The `_RLock` is simply no longer needed for the reason its comment claims (F-WN-02-13).
- **`SessionManager.save_session()` is atomic and bounded.** All seven session keys are written in a single `set_settings_batch` transaction (`core/settings.py:456-470` → `core/database.py:2049`), and `MAX_PERSISTED_QUEUE = 200` plus the `PERSISTED_TRACK_FIELDS` whitelist (`core/session.py:9-20`) bound both the size of the persisted blob and the fields it may contain — a stale `stream_url` cannot survive a restart.
- **`ListeningSession`'s arithmetic is sound.** Wall-clock `seconds` is kept separate from rate-scaled `media_seconds` (2× speed does not double the counted time), the per-tick delta is capped at 15 s (so a suspended machine cannot fabricate hours), and the 80 %-of-media-time completion threshold correctly rejects a seek to the last second. Verified by probe: a fully played 20 s track accumulates exactly 20.0 s.
- **There is no import cycle between the core and the bridge.** `core/app.py` does **not** import `core/api.py`; the back-reference is installed by the bridge (`core/api.py:347`), so the coupling is a runtime attribute, not an import cycle.
- **The provider pools are shutdown-safe by design.** `_SharedExecutor` / `_LyricsSharedExecutor` / `_TrackResolverExecutor` return `None` instead of raising when the pool is gone (`services/base_service.py:82-106`), which is what keeps `RuntimeError: cannot schedule new futures after interpreter shutdown` out of the teardown path. The module-level pools (`services/lyrics_service.py:88`, `services/track_resolver.py:76`, `services/catalog_service.py:15`) additionally register `atexit` shutdowns.
- **`update_ytdlp_safely()` does not run in the packaged app** (`core/app.py:49-50`, `getattr(sys, 'frozen', False)`), so F-WN-02-7 is scoped to unfrozen/dev runs.

---

### 4. Coverage gaps

- **No frozen build was produced.** The `_MEIPASS` consequence in F-WN-02-4 is derived from PyInstaller's documented `__file__` semantics plus the `setup_pyinstaller.spec` datas list, not observed in a built exe.
- **The real app was never run** (forbidden by the audit rules), and `~/.nedotify/` was never touched. F-WN-02-1 (exit hang), F-WN-02-6 (orphaned elevated `winws.exe`) and F-WN-02-16 (post-teardown timer) were proven by code-path analysis plus isolated probes against a temp DB and a synthetic pool, not end-to-end.
- **No live proxy load test.** The concurrency claim in F-WN-02-2 is derived from `ThreadingHTTPServer`'s thread-per-connection model (`core/proxy.py:439`) and the three call sites; the actual number of concurrent resolutions under a real playlist load was not measured.
- **`core/api.py` was only traced, not audited** — the bridge is owned by WN-03…WN-10. In particular `AppApi._emit`'s per-event thread creation, the SSRF guard and the error-logging wrapper were noted but not evaluated here.
- **`core/database.py` was probed, not audited** — owned by WN-12. `close()`'s non-terminal semantics (F-WN-02-3) is reported from the WN-02 side; the fix belongs to WN-12.
- **`services/zapret_service.py` was traced only** along `start()` → `download_binaries()` → `_launch()`; the rest of the module (argument sanitisation, PID verification, elevation) is owned by WN-26 and was not evaluated.
- **`audio/engine.py` was compared, not audited** — WN-17. Only the fallback cascade (F-WN-02-11) and the `track["duration"]` mutation used by F-WN-02-9 were inspected.
- **`services/watchdog_service.py`, `services/lufs_scanner.py`, `core/services/discord_rpc.py`, `services/artist_service.py`, `services/playlist_import_service.py`, `services/audio_fingerprint_service.py`** were only checked for "does AppCore tear this down" — their internals belong to WN-25 / WN-24 / WN-26 / WN-23.
- **The `general.plugins_enabled` write paths other than the bridge were not enumerated** — only the bridge's read-only guard was checked; a settings-import or DB-level path could still flip it.
- **The `AppCore` ↔ `AppApi` coupling was not quantified** beyond the two attributes involved (`_core.api`, `_core.tray`); a full coupling census of the bridge against the core (which would quantify the god-object concern) belongs to WN-03.

---

### 5. Architecture improvements (ARCH)

No proven defect — improvement proposals only.

- **ARCH-1 — `AppCore` is a composition root with 24 subsystems and one piece of provider logic in it.** It constructs 21 subsystems eagerly (`core/app.py:107-147`) plus 3 lazily (`core/app.py:187-234`), owns the teardown of all of them, *and* contains a ~200-line provider cascade (F-WN-02-11) plus the yt-dlp self-updater. Direction: split into a `ServiceRegistry` (pure graph construction, injectable factories) and a `StreamResolutionService` (the cascade), leaving `AppCore` as a thin lifecycle shell. The split is what makes F-WN-02-14 testable.
- **ARCH-2 — The composition root depends on a leaf.** `AppCore.cleanup()` calls `self.api.flush_listening` (`core/app.py:530`), and `AppApi.__init__` mutates `self._core.api` / `self._core.tray` and monkey-patches `self._core.engine._on_track_changed` (`core/api.py:347, 374-390`). Direction: introduce a `ListeningRecorder` that `AppCore` owns and that persists measurements itself, so the core never reaches into the bridge and the bridge never reaches back into the core's attributes.
- **ARCH-3 — Lazy services are exposed as raw attributes with public setters that bypass the lock.** `soundcloud.setter` / `yandex.setter` / `recommendations.setter` (`core/app.py:196-198, 209-211, 232-234`) write the backing field without `_service_lock`, so an assignment racing a lazy initialisation can be lost. Direction: a `ServiceRegistry` with an explicit `inject(name, service)` / `reset(name)` API for tests, and a single guarded accessor.
- **ARCH-4 — `cleanup()` has no declared order and no per-step timeout.** The sequence is implicit in the method body; the only bounded wait is the zapret 5 s join, and `watchdog.stop()` performs an unbounded `observer.join()` (`services/watchdog_service.py:102`). Direction: give each subsystem a `stop(timeout)` contract and declare the shutdown order (producers → consumers → persistence) as data, so the ordering becomes reviewable and testable.
- **ARCH-5 — `SessionManager` writes 7 separate settings keys for one logical blob.** `save_session()` (`core/session.py:57-63`) issues 7 `set()` calls that the settings writer later batches. Direction: one `session.state` key holding a versioned JSON document — fewer rows, one atomic read, one place to version the schema, and a natural place for the validation that F-WN-02-8 shows is missing.
- **ARCH-6 — `ListeningSession` is a pure dataclass whose persistence lives in `AppApi`.** `core/listening.py` computes the numbers; `core/api.py:1290-1302` writes them. Direction: give `ListeningSession` a `persist(db)` method and a `Recorder` that owns the session map, so the measurement rules and the write path cannot drift apart.
- **ARCH-7 — Plugin loading belongs in its own host with a capability surface.** `PluginManager` currently hands the plugin the entire live `AppCore` (`core/plugins.py:100`), so a plugin can reach the DB, the settings (including provider tokens) and the proxy auth token. Even with plugins disabled by default, a read-only facade (or an explicit allow-list of subsystems) would make the trust boundary visible in the code. Combined with F-WN-02-4/F-WN-02-5, the loader would also need a bounded `setup()` (timeout) so a hanging plugin cannot block startup — which today happens *before* the startup watchdog is armed (`main.py:544` starts the watchdog, `main.py:306` constructs `AppCore`).
