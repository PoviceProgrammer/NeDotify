## AREA WN-10 — Bridge cache cleaning, prefetch, batch downloads, zapret, discord, offline mode, smart playlists — ROLE A

### 1. Scope reviewed

**Primary file (read):**

- `core/api.py` L3595–4228 — `_clean_stream_cache` (3595–3638), `prefetch_track` (3640–3683),
  `download_all_favorites` (3685–3728), `cancel_batch_download` (3730–3738), `get_feed` (3740–3752),
  `get_home_artists` (3754–3763), `get_home_releases` (3765–3780), `get_home_mixes` (3782–3794),
  `toggle_zapret` (3796–3816), `toggle_discord_rpc` (3818–3838), `get_discord_rpc_status` (3840–3844),
  `get_zapret_status` (3846–3858), `check_zapret_update` (3860–3865), `update_zapret` (3867–3874).
- `core/api.py` L4129–4228 — `get_offline_mode` (4129–4130), `set_offline_mode` (4132–4161),
  `get_offline_library` (4163–4164), `recover_stream` (4166–4174), `get_downloads` (4176–4181),
  `pause_download` (4183–4184), `resume_download` (4186–4187), `retry_failed_downloads` (4189–4190),
  `_smart_playlists` (4192–4194), `get_smart_playlists` (4196–4197), `create_smart_playlist` (4199–4202),
  `update_smart_playlist` (4204–4207), `delete_smart_playlist` (4209–4212),
  `get_smart_playlist_tracks` (4214–4217), `get_search_suggestions` (4219–4221),
  `get_listening_comparison` (4223–4225).
- Supporting context in the same file: `__init__` bridge state (L350–392), `cleanup` (446–459),
  `_install_bridge_error_logging` (401–444), `_offline_bridge_result` (461–512),
  `download_track` (2294–2360), `_listening_identity` (1262–1265), `play_track` fast path (1440–1600),
  `_resolve_track` fast path (1665–1694).

**Callees traced into other areas (read):**

- `core/downloader.py` (WN-13) — `DownloadManager`: `__init__` (55–90), `get_downloads` (98–99),
  `pause_download` (101–113), `resume_download` (115–128), `retry_failed_downloads` (130–138),
  `start_batch` (185–191), `_decrement_batch_total_for_dedup` (193–211), `_on_batch_task_done` (213–239),
  `cancel_batch` (241–285), `_init_db_table` (287–331), `_resume_pending_downloads` (333–354),
  `queue_download` (356–410), `_process_queue` (437–471), `_abort_cancelled` (587–608),
  `_fetch_with_retry` (664–711), `_download_worker` (713–743), `_execute_download_worker` (745–882), `stop` (884–909).
- `core/download_store.py` (WN-13) — `DownloadStore` (whole file, 71 lines).
- `core/download_transfer.py` (WN-13) — `DownloadContext` / `DownloadInterrupted` (1–128).
- `core/offline.py` (WN-15) — `is_offline`, `_local_file`, `available_track`, `available_tracks`,
  `offline_library` (whole file, 77 lines).
- `core/playback_recovery.py` (WN-15) — `recover_stream` (95–183), `same_recording` (14–37).
- `core/resolver.py` (WN-15) — `resolve` (165–230), `_persist` (256–267), `get_cached_url` (141–163).
- `utils/cache_manager.py` (WN-27) — `CacheManager` (whole file, 453 lines): `purge_stream_cache` (171–271),
  `download_audio_stream` (289–396), `get_storage_details` (104–135).
- `utils/search_query.py` (WN-27) — `suggest_search_queries` (31–101).
- `services/zapret_service.py` (WN-26) — `sanitize_zapret_args` (203–219), `validate_zapret_binary` (222–262),
  `binary_integrity_error` (177–200), `find_binary` (732–752), `is_running` (756–778),
  `start` (1063–1150), `_launch` (1152–1212), `_launch_elevated` (1264–1334), `stop` (1336+),
  `_ALLOWED_ARG_RE` (90), `_ALLOWED_BINARY_NAMES` (93), `PRESET_STRATEGIES` (77–85).
- `core/services/discord_rpc.py` (WN-26) — `DiscordRPCService` (whole file, 183 lines).
- `services/smart_playlists.py` (WN-24) — `SmartPlaylistService` (whole file, 177 lines).
- `services/listening_comparison.py` (WN-25) — `listening_comparison` (whole file, 84 lines).
- `core/database.py` (WN-12) — `download_queue_add` (2330–2359), `download_queue_set_status` (2361–2370),
  `download_queue_get_status` (2384–2398), `download_queue_cancel_pending` (2400–2406),
  `get_cached_stream` (2149–2160), `set_cached_file` (2134–2147), `cleanup_expired_cache` (2227–2242),
  `add_track` (1054–1164), `get_favorite_tracks` (1224–1227), `get_top_artists` (1708–1721),
  `mark_track_downloaded` (1278–1282).
- `core/app.py` (WN-02) — wiring (100–186), `cleanup` (508–586).
- `core/proxy.py` (WN-11) — only the cache write/read sites that matter for this area: 780–840, 1185–1234.
- `utils/file_scanner.py` (WN-27) — local-track creation (115–144).
- `core/user_errors.py` (WN-16) — `describe_error` (1–24).

**Frontend contract cross-check (read):**

- `ui/web_new_v2/js/downloads-view.js` (1–193) — status labels, status sets, action mapping.
- `ui/web_new_v2/js/library.js` (40–105, 485–545) — batch progress bar lifecycle, smart-playlist paging.
- `ui/web_new_v2/js/smart-playlists.js` (whole file, 185 lines).
- `ui/web_new_v2/js/player.js` (440–509, 1440) — `recover_stream` caller, `prefetch_track` caller.
- `ui/web_new_v2/js/settings.js` (196–213, 1849–2019) — Discord toggle, Zapret panel.
- `ui/web_new_v2/js/feature-controls.js` (1–133) — offline-mode state handling.
- `ui/web_new_v2/js/profile-comparison.js` (1–56) — `get_listening_comparison` caller.
- `ui/web_new_v2/js/events.js` (242–281) — batch + `download_failed` event handling.

**Executable reproductions run** (scratch scripts under `%TEMP%`, no repo or `~/.nedotify/` writes;
`DatabaseManager(":memory:")` used throughout):

- `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro.py` — batch counter leak via `pause_download()`.
- `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro2.py` — batch counter leak via an in-flight worker aborted by a pause.
- `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro3.py` — favourite-protection bypass + dangling DB row in `_clean_stream_cache`.

---

### 2. Findings

#### F-WN-10-1  [P1] — `_clean_stream_cache` deletes the cached audio of favourite/downloaded tracks and of in-flight downloads, and leaves dangling DB rows

- **File:** `core/api.py:3595-3638` (deletion), `core/api.py:3671` (only call site)
  also `utils/cache_manager.py:171-271` (the policy it bypasses), `utils/cache_manager.py:258-265` (the DB sync it omits)
- **Confirmed:** yes (executable reproduction, see below)
- **Description:** `_clean_stream_cache` re-implements stream-cache eviction from scratch and deletes **every**
  file in `~/.nedotify/streams/` that is older than 48 h, plus the oldest ones once the directory
  exceeds 350 MB. It applies **none** of the protections that `CacheManager.purge_stream_cache()`
  applies for the very same directory:
  1. **Favourite / downloaded tracks are not protected.** `purge_stream_cache` explicitly skips
     `tracks` rows with `is_downloaded = 1 OR is_favorite = 1` (both by `file_path` and by
     `f"{source}_{source_id}"` matched against the cache file name). `_clean_stream_cache` has no
     notion of favourites at all → the cached offline copy of a favourite is deleted after 48 h.
  2. **In-flight downloads are not protected.** `purge_stream_cache` skips files matching
     `CacheManager._active_downloads` (the yt-dlp stream download currently writing the file).
     `_clean_stream_cache` does not consult that set, so it can delete the `.part`/target file of a
     stream download that is being written right now.
  3. **The database is not synchronised.** `purge_stream_cache` runs
     `UPDATE stream_cache SET cached_file_path = NULL ...` and
     `UPDATE tracks SET is_cached = 0, file_path = NULL ...` in the same transaction as the deletion.
     `_clean_stream_cache` deletes the file and leaves `stream_cache.cached_file_path` pointing at a
     file that no longer exists (dangling row). `core/api.py:1536` / `core/api.py:1679` /
     `core/proxy.py:797` re-check `os.path.exists()` and degrade gracefully, but
     `services/smart_playlists.py:159` and any future consumer that trusts the row do not.
- **Cause:** the cleaner was written as an independent, self-contained deletion loop instead of
  delegating to the single eviction authority (`CacheManager.purge_stream_cache`), so it silently
  diverged from the documented protection policy.
- **Trigger conditions:** the app plays enough tracks to fill `~/.nedotify/streams/` (the proxy
  caches every streamed track there — `core/proxy.py:1187-1207`), or a cached file simply ages
  past 48 h. `prefetch_track` runs the cleaner at most once every 600 s (`core/api.py:3665-3671`),
  so it fires on ordinary listening, not on an explicit user action.
- **User impact:** a favourite track silently loses its offline copy (it is no longer in
  `get_offline_library()` / `available_track()` although the DB still claims it is cached), and a
  stream download that is in flight can be broken by the cleaner. Nothing is logged or surfaced.
- **Evidence:**
  ```python
  # core/api.py:3609-3636
  for entry in os.scandir(streams_dir):
      if entry.is_file():
          stat = entry.stat()
          total_size += stat.st_size
          files.append((entry.path, stat.st_mtime, stat.st_size))

  kept_files = []
  for path, mtime, size in files:
      if (now - mtime) > max_age_sec:
          try:
              os.remove(path)            # <-- no favourite/downloaded/active check
              total_size -= size
          except Exception:
              kept_files.append((path, mtime, size))
      ...
  ```
  versus the policy it bypasses:
  ```python
  # utils/cache_manager.py:198-234
  cursor.execute("SELECT file_path, source, source_id FROM tracks WHERE is_downloaded = 1 OR is_favorite = 1")
  ...
  if any(p_src in base_name for p_src in protected_sources):   # favourite / downloaded
      continue
  if any(act in base_name for act in active_downloads_copy):    # in-flight download
      continue
  ```
  and the DB sync it omits:
  ```python
  # utils/cache_manager.py:255-265
  self.db.conn.execute("UPDATE stream_cache SET cached_file_path = NULL WHERE cached_file_path = ?", (dfp,))
  self.db.conn.execute("UPDATE tracks SET is_cached = 0, file_path = NULL "
                        "WHERE file_path = ? AND is_downloaded = 0 AND is_favorite = 0", (dfp,))
  ```
- **Reproduction / verification:** `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro3.py`
  (run with `& ".venv_win\Scripts\python.exe"`). It creates a temp streams dir with
  `youtube_abc123.m4a` aged 72 h, a `tracks` row with `is_favorite = 1`,
  `source='youtube', source_id='abc123'`, and a matching `stream_cache.cached_file_path` row, then
  calls `CacheManager.purge_stream_cache(quota_bytes=1)` and `AppApi._clean_stream_cache(stub)`.
  Output:
  ```
  favourite protected by CacheManager.purge_stream_cache? 0 freed bytes (0 == protected)
  after _clean_stream_cache: file exists = False
  stream_cache row still points at: ...\streams\youtube_abc123.m4a | file exists: False
  ```
  i.e. the authoritative purge keeps the file, the api-level cleaner deletes it and leaves the row dangling.
- **Suggested fix:** delete `_clean_stream_cache` and delegate to `CacheManager.purge_stream_cache()`
  (it already implements TTL-by-`expires_at`, quota, protection and DB synchronisation), or at
  minimum reuse `purge_stream_cache` for the size pass and reproduce its protection + DB-sync logic
  for the age pass.
- **Fix side effects:** `purge_stream_cache` has no age dimension of its own (the DB `expires_at`
  cleanup only removes rows *without* a cached file, `core/database.py:2235-2238`), so a purely
  quota-driven policy would never age out stream audio; an age pass would have to be added to
  `CacheManager` (where the protection logic lives) rather than to `core/api.py`.
- **Discovered by:** A

#### F-WN-10-2  [P2] — `_clean_stream_cache` ignores the user's cache quota (including "no limit") and enforces a second, conflicting 350 MB / 48 h policy

- **File:** `core/api.py:3595` (`max_size_mb: int = 350, max_age_hours: int = 48`),
  `core/api.py:3626` (`max_bytes = max_size_mb * 1024 * 1024`), `core/api.py:3671` (call site),
  `core/api.py:4031-4095` (`set_cache_quota`), `utils/cache_manager.py:179-196`
- **Confirmed:** yes
- **Description:** the user-facing quota is `storage.cache_quota_gb` (GB, default 5, `0` = "no limit",
  set through `set_cache_quota` → `CacheManager.purge_stream_cache(quota_bytes=…)`). The
  `_clean_stream_cache` path used by `prefetch_track` uses a **hardcoded** 350 MB ceiling and a
  48 h TTL and is completely independent of that setting. A user who explicitly sets the quota to
  0 ("no limit") still loses cached files after 48 h; a user who sets 1 GB still loses files at
  350 MB. `set_cache_quota` also reports `freed_bytes` computed only from the quota purge, so the
  UI under-reports what was actually deleted.
- **Cause:** two independent eviction policies for one directory, owned by two different modules.
- **Trigger conditions:** any `prefetch_track` call more than 600 s after the previous one
  (`core/api.py:3665-3671`).
- **User impact:** the quota the user configured in Settings → Storage is not what actually
  governs disk usage; cached tracks disappear earlier than the user asked for and no UI number
  reflects it.
- **Evidence:**
  ```python
  # core/api.py:3595, 3626-3627, 3665-3671
  def _clean_stream_cache(self, max_size_mb: int = 350, max_age_hours: int = 48):
  ...
      max_bytes = max_size_mb * 1024 * 1024
      if total_size > max_bytes:
  ...
      prune = now - getattr(self, "_last_stream_clean", 0.0) > 600.0
      if prune:
          self._last_stream_clean = now
      if prune:
          self._clean_stream_cache()
  ```
  versus the quota the user sets:
  ```python
  # core/api.py:4085-4087
  freed = self._core.cache.purge_stream_cache(quota_bytes=quota_val * 1024 * 1024 * 1024)
  details = self._core.cache.get_storage_details()
  ```
- **Reproduction / verification:** set the quota to 0 GB (`set_cache_quota(cache_quota_gb=0)` →
  `storage.cache_quota_gb = 0`), then play >48 h old cached streams and let `prefetch_track` fire;
  `CacheManager.purge_stream_cache` returns 0 (`quota_bytes == 0 and not force_all_temporary` →
  `return 0`, `utils/cache_manager.py:189-190`) while `_clean_stream_cache` still deletes the files.
  Static confirmation of the divergence is sufficient (the two constants never meet).
- **Suggested fix:** make the cleaner read `storage.cache_quota_gb` through
  `CacheManager` (and skip entirely when it is 0), instead of carrying a private 350 MB constant.
- **Fix side effects:** with the default 5 GB quota the streams directory would keep far more
  audio than the current 350 MB cap; the "Storage" page numbers would jump. That is the user's
  stated intent, but it is a visible behaviour change.
- **Discovered by:** A

#### F-WN-10-3  [P1] — Pausing downloads leaks the batch counters: `batch_download_finished` is never emitted and the library progress bar hangs forever

- **File:** `core/api.py:4183-4184` (`pause_download` bridge), `core/api.py:4139-4142`
  (`set_offline_mode` → `downloader.pause_download()`), `core/downloader.py:101-113`
  (`pause_download`), `core/downloader.py:587-608` (`_abort_cancelled`),
  `core/downloader.py:213-239` (`_on_batch_task_done`), `core/downloader.py:241-285` (`cancel_batch`),
  `ui/web_new_v2/js/library.js:78-105`
- **Confirmed:** yes (two executable reproductions)
- **Description:** the batch accounting has exactly two exits for a queued item:
  `_on_batch_task_done()` (worker finished) and `_decrement_batch_total_for_dedup()` (item was a
  duplicate). A **pause** uses neither:
  - `DownloadManager.pause_download()` removes the queued items from `self._queue` and marks the
    rows `paused`, but never calls `_on_batch_task_done()` / `_decrement_batch_total_for_dedup()`.
  - An **in-flight** worker that aborts because the track was paused returns from
    `_abort_cancelled()` at `core/downloader.py:597-599` (`if paused: self._store.update(...); return True`)
    — that path deliberately skips `_on_batch_task_done()` (which is only reached for a *cancelled*
    epoch, `core/downloader.py:602-607`).
  Result: `_batch_total` stays at N, `_batch_completed` stays below it and `_batch_active` stays
  `True` forever. `batch_download_finished` is never emitted, so the library view keeps the batch
  progress box on screen with a frozen percentage (`ui/web_new_v2/js/library.js:92-101` only hides
  it on `batch_download_finished` or `batch_download_cancelled`).
- **Cause:** the batch state machine has no "suspended" state; pausing a download is neither a
  success, a failure nor a dedup, and no transition exists for it.
- **Trigger conditions:** the user starts "Скачать все избранное" (`download_all_favorites`, which
  calls `start_batch(len(to_download))` at `core/api.py:3708`) and then either
  (a) presses "Пауза всех" in the download manager (`ui/web_new_v2/js/downloads-view.js:143` →
  `pause_download()` with no track id), or
  (b) enables offline mode, which pauses every pending download (`core/api.py:4141-4142`).
- **User impact:** the batch progress bar in the Library page never completes and never hides; the
  "Загрузка завершена" toast never appears; the user has to press "Отменить" to clear it. The
  stuck `_batch_active` flag also makes the *next* `batch_download_progress` percentages
  meaningless.
- **Evidence:**
  ```python
  # core/downloader.py:108-113  (pause_download)
  with self._queue_lock:
      self._queue = [item for item in self._queue if item['track_id'] not in targets]
  for target in targets:
      self._store.update(target, status='paused', resume_on_restart=0)
  self._emit('download_queue_updated', {'status': 'paused'})
  return {'success': True, 'count': len(targets)}
  ```
  ```python
  # core/downloader.py:592-601  (_abort_cancelled, paused branch)
  except DownloadInterrupted:
      if not self._is_cancelled(epoch):
          with self._lock:
              paused = track_id in self._paused_track_ids
          if paused:
              self._store.update(track_id, status='paused')
          return True          # <-- _on_batch_task_done() is NOT called here
  ```
  and the only terminator the UI waits for:
  ```javascript
  // ui/web_new_v2/js/library.js:92-101
  document.addEventListener('nedotify:batch_download_finished', (e) => { ... });
  document.addEventListener('nedotify:batch_download_cancelled', () => { ... });
  ```
- **Reproduction / verification:**
  `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro.py` (queued items dropped by the pause):
  ```
  before pause: total= 3 active= True queue= 3
  after  pause: total= 3 active= True queue= 0 completed= 0
  batch_download_finished emitted: False
  ```
  `C:\Users\Артур\AppData\Local\Temp\opencode\wn10_repro2.py` (in-flight worker aborted by the pause):
  ```
  abort returned: True
  batch total: 1 completed: 0 active: True
  batch_download_finished emitted: False
  store row status: paused
  ```
  End-to-end: start a favourites batch, press "Пауза всех" → the library progress box stays visible
  with the percentage frozen at the last `batch_download_progress`.
- **Suggested fix:** give the batch state machine an explicit suspended transition — on pause,
  either decrement `_batch_total` for every paused item (so the batch can still reach 100 %) or
  mark the batch as suspended and emit `batch_download_finished` with a "paused" flag; and make
  `_abort_cancelled`'s paused branch call `_on_batch_task_done(track_id, success=False)` (or an
  equivalent "suspended" accounting) so `_batch_completed` and `_batch_total` stay in sync.
- **Fix side effects:** counting a paused item as "completed" would report a wrong
  `completed`/`failed` split in `batch_download_finished`; the fix should carry an explicit
  `paused` count instead of overloading `failed`.
- **Discovered by:** A

#### F-WN-10-4  [P2] — `download_all_favorites` tries to download local (already-on-disk) favourites and fails each one with a raw English "missing source_id"

- **File:** `core/api.py:3692` (filter), `core/api.py:3717-3718` (loop), `core/api.py:2337-2344`
  (`download_track` refusal), `core/downloader.py:27` (`_SUPPORTED_SOURCES`), `utils/file_scanner.py:128-139`
- **Confirmed:** yes
- **Description:** `to_download = [t for t in favs if not t.get("is_downloaded")]` only looks at
  `is_downloaded`. A track imported by the file scanner (`utils/file_scanner.py:128-139`) is stored
  with `source="local"`, `source_id=NULL`, `file_path=<path>` and **`is_downloaded = 0`**
  (`core/database.py:1129-1163` only sets `is_downloaded` when the caller passes it). Such a track
  therefore passes the filter and is sent to `download_track`, which refuses it with
  `"missing source_id"` — a technical English string that is emitted **directly** through
  `AppApi._emit`, bypassing `describe_error()`, so the user sees
  *"Ошибка скачивания: missing source_id"* as a toast for every local favourite.
  (A favourite whose `source` is `local` but which *does* have a `source_id` would instead reach
  the downloader and fail there with "No download provider for source 'local'.")
- **Cause:** the "not yet downloaded" predicate is not the same as "downloadable"; the filter does
  not exclude sources that have no download provider.
- **Trigger conditions:** the user favourites a track that was added by the local file scanner
  (or by "Import" → `open_local_file`), then presses "Скачать избранное".
- **User impact:** a burst of spurious error toasts for tracks the user already has on disk, and
  failed rows in the download manager's list (`download_queue` rows with `status='failed'`).
  The batch counter itself still completes, because `download_track` calls
  `_decrement_batch_total_for_dedup()` on the refusal path (`core/api.py:2343`).
- **Evidence:**
  ```python
  # core/api.py:3692
  to_download = [t for t in favs if not t.get("is_downloaded")]
  ```
  ```python
  # core/api.py:2337-2344
  if not source_id:
      logger.warning(f"download_track: missing source_id for track {track_id}, refusing to queue")
      try:
          self._emit("download_failed", {"track_id": track_id, "error": "missing source_id"})
      except Exception:
          pass
      self._core.downloader._decrement_batch_total_for_dedup()
      return False
  ```
  versus the provider allow-list the downloader enforces:
  ```python
  # core/downloader.py:27
  _SUPPORTED_SOURCES = frozenset({'youtube', 'soundcloud', 'yandex', 'spotify', 'spotify_album'})
  ```
  and the UI toast that shows the raw string:
  ```javascript
  // ui/web_new_v2/js/events.js:276-277
  const dlErr = (data?.error || data?.message || 'Неизвестная ошибка').toString();
  showToast(data?.title || ('Ошибка скачивания: ' + dlErr), 'error');
  ```
- **Reproduction / verification:** scan a folder with `FileScanner` (a local track is created with
  `source='local'`, `source_id=NULL`, `is_downloaded=0`), favourite it
  (`toggle_favorite`), then call `download_all_favorites()`. The log line
  `download_track: missing source_id for track <id>, refusing to queue` appears and a
  `download_failed` event with `error="missing source_id"` is emitted.
  Static confirmation is sufficient: `core/database.py:1129` shows `is_downloaded` is only set from
  the caller's kwarg, and `utils/file_scanner.py:128-139` does not pass it.
- **Suggested fix:** filter `to_download` on the same predicate the downloader enforces
  (source ∈ `_SUPPORTED_SOURCES` and a non-empty `source_id`), and/or treat a track that already
  has an existing `file_path` as "already available" instead of "to download"; route the
  `download_failed` emissions of `download_track` through `describe_error()` like
  `core/downloader.py:174-175` does.
- **Fix side effects:** the reported `count`/`total` of the batch would drop (fewer items) — the
  UI shows `res.count` as the denominator (`ui/web_new_v2/js/library.js:51`), so the numbers
  change but stay consistent because `batch_download_started` uses the same list.
- **Discovered by:** A

#### F-WN-10-5  [P2] — `toggle_discord_rpc(False)` never closes the Discord connection: the IPC socket stays open and `get_discord_rpc_status()` keeps reporting `connected: True`

- **File:** `core/api.py:3818-3838` (`toggle_discord_rpc`), `core/api.py:3840-3844`
  (`get_discord_rpc_status`), `core/services/discord_rpc.py:164-183` (`clear_presence` / `stop`),
  `core/app.py:549-550` (only place `stop()` is called)
- **Confirmed:** yes
- **Description:** the disable branch of `toggle_discord_rpc` calls **only**
  `self._core.discord_rpc.clear_presence()`. `clear_presence()` clears the presence payload but
  leaves `self.rpc` (the live Discord IPC socket) and `self.connected == True` untouched — only
  `DiscordRPCService.stop()` closes the socket and resets `connected`. `stop()` is called exactly
  once in the whole application: in `AppCore.cleanup()` at app exit. Consequences:
  - the app keeps an open IPC connection to the running Discord client for the rest of the
    session even though the user switched the feature off;
  - `get_discord_rpc_status()` returns `{"enabled": False, "connected": True}` — a self-contradictory
    answer (the field is read directly from the live object, not from the setting).
  (`update_presence()` is protected: it re-checks `is_enabled()` and stops sending updates, so no
  stale presence is shown — the damage is limited to the leaked connection and the wrong status.)
- **Cause:** the bridge treats "disable" as "clear the payload" instead of "stop the service";
  `DiscordRPCService` exposes two distinct operations and only one of them is used.
- **Trigger conditions:** the user toggles Discord Rich Presence off in Settings
  (`ui/web_new_v2/js/settings.js:206-212` → `toggle_discord_rpc(false)`) while Discord is running.
- **User impact:** the Discord client keeps an IPC connection it did not ask for; any consumer of
  `get_discord_rpc_status()` is told the integration is connected when it is disabled. The
  current UI does not display that status, so today the visible symptom is limited to the leaked
  connection.
- **Evidence:**
  ```python
  # core/api.py:3821-3835
  self._core.settings.set("app", "discord_rpc_enabled", enabled)
  if hasattr(self._core, "discord_rpc") and self._core.discord_rpc:
      if enabled:
          self._core.discord_rpc.start()
          ...
      else:
          self._core.discord_rpc.clear_presence()     # <-- never stop()
  return {"success": True, "enabled": enabled}
  ```
  ```python
  # core/services/discord_rpc.py:164-183
  def clear_presence(self):
      with self._lock:
          if not self.connected or not self.rpc:
              return
          try:
              self.rpc.clear()
          except Exception:
              pass

  def stop(self):
      self.clear_presence()
      if self.rpc:
          try:
              self.rpc.close()
          except Exception:
              pass
          self.rpc = None
          self.connected = False
  ```
  ```python
  # core/api.py:3840-3844
  def get_discord_rpc_status(self):
      enabled = self._core.settings.get("app", "discord_rpc_enabled", True)
      connected = getattr(self._core.discord_rpc, "connected", False) if hasattr(self._core, "discord_rpc") else False
      return {"enabled": enabled, "connected": connected}
  ```
- **Reproduction / verification:** with Discord running, toggle Rich Presence off
  (`window.pywebview.api.toggle_discord_rpc(false)`), then call
  `window.pywebview.api.get_discord_rpc_status()` → `{"enabled": false, "connected": true}`.
  Static confirmation: `clear_presence()` contains no assignment to `self.connected` and
  `self.rpc` is only cleared in `stop()`, which `toggle_discord_rpc` never calls
  (`grep -n "discord_rpc" core/api.py` → only `start`, `clear_presence`, `connected`).
- **Suggested fix:** in the disable branch call `self._core.discord_rpc.stop()` (and `start()`
  in the enable branch), and make `get_discord_rpc_status()` derive `connected` from
  `enabled and service.connected`.
- **Fix side effects:** `stop()` sets `self.rpc = None`; a later `start()` creates a fresh
  `Presence` object, which briefly re-establishes the IPC connection — acceptable, but the
  re-enable path must not race with an in-flight `_connect()` thread
  (`self._connecting` is cleared outside the lock, `core/services/discord_rpc.py:83`).
- **Discovered by:** A

#### F-WN-10-6  [P3] — `recover_stream` in offline mode crashes on a non-numeric `position_ms` and returns a different type than the online path

- **File:** `core/api.py:4166-4174`, `core/playback_recovery.py:99-105`
- **Confirmed:** yes
- **Description:** the offline branch does `max(0, float(position_ms))` with no guard, while the
  online branch delegates to `core/playback_recovery.py::recover_stream`, which explicitly
  tolerates a bad value:
  ```python
  # core/playback_recovery.py:99-105
  try:
      position = float(position_ms)
      if not math.isfinite(position):
          raise ValueError
  except (ValueError, TypeError):
      position = 0
  position = max(0, round(position))
  ```
  So `recover_stream(track, None)` or `recover_stream(track, "abc")` succeeds online (position 0)
  but raises `TypeError`/`ValueError` offline → the pywebview promise rejects and the player treats
  it as a failed recovery (`ui/web_new_v2/js/player.js:484-489`).
  The two paths also disagree on the type of `position_ms`: offline returns a float
  (`max(0, float(...))`), online returns an int (`round(...)`).
- **Cause:** the offline shortcut re-implements a small part of the recovery contract instead of
  reusing the guarded conversion.
- **Trigger conditions:** any caller that passes a non-numeric or `None` position while offline
  mode is on. The current UI always passes an integer
  (`Math.round((audio.currentTime || 0) * 1000)`, `ui/web_new_v2/js/player.js:463`), so this is
  latent for the shipped UI and reachable through the bridge.
- **User impact:** an avoidable exception in the recovery path; the player stops instead of
  retrying when offline.
- **Evidence:**
  ```python
  # core/api.py:4166-4174
  def recover_stream(self, track, position_ms=0):
      from core.playback_recovery import recover_stream
      if is_offline(self._core.settings):
          local = available_track(self._core.db, track)
          if local:
              return {'ok': True, 'stream_url': local['file_path'],
                      'position_ms': max(0, float(position_ms)),   # <-- unguarded float()
  ```
- **Reproduction / verification:** with offline mode on, call
  `window.pywebview.api.recover_stream({source:'youtube',source_id:'x'}, null)` → the promise
  rejects with `TypeError: float() argument must be a string or a real number, not 'NoneType'`;
  with offline mode off the same call returns `{'ok': False, 'code': ..., 'position_ms': 0}`.
- **Suggested fix:** reuse the guarded conversion (e.g. call a small shared helper from
  `core/playback_recovery.py`) and return `round()`-ed integer positions on both paths.
- **Fix side effects:** none; the online path already behaves this way.
- **Discovered by:** A

#### F-WN-10-7  [P3] — `get_listening_comparison` lets `ValueError`/`TypeError` escape and rejects valid UTC offsets beyond ±12 h

- **File:** `core/api.py:4223-4225`, `services/listening_comparison.py:13-18`
- **Confirmed:** yes
- **Description:** `get_listening_comparison` has no `try/except`; the callee raises
  `ValueError('Выберите неделю, месяц или год')` for an unknown period and
  `ValueError('Некорректный часовой пояс')` for an offset outside `-720..840`, and
  `int(utc_offset_minutes)` raises `TypeError` for `None`/a non-numeric value. The bridge wrapper
  turns the exception into a rejected promise plus an `api_error` event
  (`core/api.py:428-441`). The shipped UI handles the rejection
  (`ui/web_new_v2/js/profile-comparison.js:37-38`), so the visible effect is an extra
  `api_error` toast for an invalid period, not a crash.
  The offset range is also asymmetric with the JS caller: the UI sends
  `-new Date().getTimezoneOffset()` (`ui/web_new_v2/js/profile-comparison.js:33`), i.e. UTC+13 →
  `-780` and UTC+14 → `-840`, both **outside** the accepted `-720..840` range → a hard error for
  users in Tonga/Samoa/Kiritimati, while UTC-12 (720) is accepted.
- **Cause:** the bridge method does not validate/normalise its arguments, and the callee's range
  check does not cover the full set of real UTC offsets.
- **Trigger conditions:** a period value outside `{week, month, year}` (e.g. from a stale UI
  selection or a direct bridge call), or a machine in UTC+13/+14.
- **User impact:** "Не удалось сравнить периоды" in the Profile page for a small set of users;
  a spurious global error toast.
- **Evidence:**
  ```python
  # services/listening_comparison.py:13-18
  def listening_comparison(db, period='week', utc_offset_minutes=180, *, now=None):
      if period not in _DAYS:
          raise ValueError('Выберите неделю, месяц или год')
      offset = int(utc_offset_minutes)
      if not -720 <= offset <= 840:
          raise ValueError('Некорректный часовой пояс')
  ```
  ```python
  # core/api.py:4223-4225
  def get_listening_comparison(self, period='week', utc_offset_minutes=180):
      from services.listening_comparison import listening_comparison
      return listening_comparison(self._core.db, period, utc_offset_minutes)
  ```
- **Reproduction / verification:** call
  `window.pywebview.api.get_listening_comparison('decade', 180)` → the promise rejects with
  `ValueError: Выберите неделю, месяц или год`; on a UTC+14 machine
  `get_listening_comparison('week', -840)` rejects with `ValueError: Некорректный часовой пояс`.
- **Suggested fix:** wrap the call in the bridge method and return a structured error
  (`{"success": False, "error": ...}`) instead of raising, and widen the offset range to
  `-840 <= offset <= 840` (all real UTC offsets).
- **Fix side effects:** the JS caller currently treats a rejection as "cannot compare"; returning a
  structured error requires the JS to check `success` — a one-line change in
  `ui/web_new_v2/js/profile-comparison.js`.
- **Discovered by:** A

#### F-WN-10-8  [P3] — `set_offline_mode(True)` irreversibly discards the playback queue and never restores it

- **File:** `core/api.py:4132-4161`, `core/offline.py:62-73`
- **Confirmed:** yes (code), user impact depends on runtime queue composition
- **Description:** when offline mode is enabled, the queue is rewritten to contain only
  offline-playable tracks and, if none is playable, it is **cleared**:
  ```python
  # core/api.py:4143-4158
  queue = getattr(getattr(self._core, 'engine', None), 'queue', None)
  if queue and queue.tracks:
      current = available_track(self._core.db, queue.current_track)
      active_available = current is not None
      tracks = available_tracks(self._core.db, queue.tracks)
      ...
      else:
          queue.clear()
          self._notify_queue_updated()
  ```
  Switching offline mode back off does **not** restore the queue (there is no snapshot of the
  pre-offline queue), so the user's queue — including its order and the current position — is lost.
  Secondary: `available_tracks()` (used here) has **no** DB-by-id fallback, unlike the singular
  `available_track()` (`core/offline.py:44-53`); a queue entry that carries only a track id and no
  `file_path` is therefore dropped even when the file exists in the DB.
  Also note `active_available` is only computed while enabling, so the emitted state for
  `enabled=False` always carries `active_available: True`.
- **Cause:** the queue rewrite is destructive and one-way; the two availability helpers disagree
  about how a track's file is located.
- **Trigger conditions:** enabling offline mode while the queue contains tracks that are not
  offline-playable (or only ids).
- **User impact:** the playback queue is silently emptied; the user must rebuild it after
  switching offline mode back off.
- **Evidence:**
  ```python
  # core/offline.py:35-59 vs 62-73
  def available_track(db, track):
      ...
      identifier = track.get('track_id') or track.get('id')
      if identifier is not None:
          stored = db.get_track(int(identifier))      # <-- DB fallback exists here
  ...
  def available_tracks(db, tracks):
      cached = {(row['source'], str(row['source_id'])): row['cached_file_path'] ...}
      for track in tracks:
          path = _local_file(track.get('file_path')) or _local_file(
              cached.get((track.get('source'), str(track.get('source_id')))), cached=True)
          # <-- no db.get_track() fallback here
  ```
- **Reproduction / verification:** build a queue from streamed (non-downloaded) tracks, then call
  `window.pywebview.api.set_offline_mode(true)` → `queue.clear()` runs, `queue_updated` is emitted
  with an empty queue, and `set_offline_mode(false)` leaves the queue empty.
  *Missing evidence for the `available_tracks` sub-claim:* whether a real queue entry ever carries
  an id but no `file_path` depends on how the frontend populates the queue at runtime; the code
  asymmetry is confirmed, the reachable trigger is not.
- **Suggested fix:** snapshot the queue before rewriting it and restore it when offline mode is
  switched off; make `available_tracks()` use the same DB-by-id fallback as `available_track()`.
  (The `available_tracks` root cause lives in `core/offline.py` → **WN-15**; the destructive
  one-way queue rewrite is the WN-10 part.)
- **Fix side effects:** restoring a queue that contains tracks which were removed from the library
  in the meantime needs re-validation; the `active_available` flag consumed by
  `ui/web_new_v2/js/feature-controls.js:18-22` must keep its current semantics.
- **Discovered by:** A

#### F-WN-10-9  [P3] — `get_downloads` silently truncates the download queue at 500 rows with no way to see the rest

- **File:** `core/api.py:4176-4181`, `core/download_store.py:32-46`,
  `ui/web_new_v2/js/downloads-view.js:58-87`
- **Confirmed:** yes
- **Description:** `get_downloads()` calls `self._core.downloader.get_downloads()` →
  `DownloadStore.rows()` with the default `limit=500`. The download manager UI renders at most
  `downloadItems.length` rows and offers a "Показать ещё" button that only raises `visibleLimit`
  (capped by the 500 already fetched), so rows beyond 500 can never be displayed, no matter how
  many queue rows exist. `download_queue` holds one row per track and the library can hold
  thousands.
- **Cause:** the bridge hard-codes a page size equal to the UI's maximum and offers no
  continuation token.
- **Trigger conditions:** more than 500 tracks have been queued for download at some point in the
  app's lifetime (rows are never purged from `download_queue`).
- **User impact:** old download rows ("completed"/"failed") silently disappear from the download
  manager once the table passes 500 rows; the user cannot inspect or retry them.
- **Evidence:**
  ```python
  # core/api.py:4176-4181
  def get_downloads(self):
      downloads = self._core.downloader.get_downloads()
      for item in downloads:
          if item.get('status') == 'failed':
              item['user_error'] = describe_error(item.get('error'), 'download')
      return downloads
  ```
  ```python
  # core/download_store.py:32-46
  def rows(self, statuses=None, limit=500):
      ...
      parameters.append(max(1, min(int(limit), 5000)))
      ...
      " ORDER BY CASE queue.status WHEN 'downloading' THEN 0 ... LIMIT ?", parameters
  ```
  ```javascript
  // ui/web_new_v2/js/downloads-view.js:81-82
  more.hidden = downloadItems.length <= visibleLimit;
  more.textContent = `Показать ещё (${Math.max(0, downloadItems.length - visibleLimit)})`;
  ```
- **Reproduction / verification:** insert 600 rows into `download_queue` (or download 600 tracks)
  and call `window.pywebview.api.get_downloads()` → the array has 500 entries; the UI's
  "Показать ещё" button disappears at `visibleLimit = 480` and no further page is ever requested.
- **Suggested fix:** return a page plus a total/has-more flag and let the UI request the next
  page (or filter by status server-side, e.g. hide `completed` rows by default).
- **Fix side effects:** pagination needs a stable ORDER BY; the current ordering mixes four
  different status buckets and `queue.id DESC`, which is not a stable key for offset paging when
  rows change status concurrently.
- **Discovered by:** A

#### F-WN-10-10  [P3] — `cancel_batch_download` reports success unconditionally in the UI and cancels *all* pending downloads, not just the batch's

- **File:** `core/api.py:3730-3738`, `core/downloader.py:241-285`,
  `ui/web_new_v2/js/library.js:67-75`
- **Confirmed:** yes
- **Description:** two issues in the cancel path:
  1. `cancel_batch_download()` returns the boolean from `DownloadManager.cancel_batch()`, but the UI
     ignores the return value and unconditionally shows
     *"Пакетное скачивание отменено"* — a failure is reported as a success.
  2. `cancel_batch()` cancels **every** pending/downloading row, not only the items of the running
     batch: `download_queue_cancel_pending()` does
     `UPDATE download_queue SET status='cancelled' WHERE status='pending'` (all rows) and the
     subsequent loop marks every `pending`/`downloading`/`cancelled` row as `cancelled`. A single
     download queued individually by the user is cancelled together with the batch.
  Additionally, an already-running provider transfer is not stopped immediately — the cancellation
  is cooperative (epoch bump + `DownloadContext.checkpoint()`), so a yt-dlp based transfer only
  aborts at the next stage boundary (that behaviour is documented in `cancel_batch`'s docstring and
  belongs to WN-13).
- **Cause:** the bridge method is a thin wrapper whose result is dropped by the caller, and the
  downloader's cancel operation is not scoped to the batch.
- **Trigger conditions:** the user presses "Отменить" on the favourites batch while other
  downloads are queued individually.
- **User impact:** individually queued downloads are cancelled as a side effect; the user is told
  the cancellation succeeded even when it failed.
- **Evidence:**
  ```python
  # core/api.py:3730-3738
  def cancel_batch_download(self):
      try:
          if hasattr(self._core, "downloader"):
              return self._core.downloader.cancel_batch()
          return True
      except Exception as e:
          logger.error(f"Error cancelling batch download: {e}")
          return False
  ```
  ```javascript
  // ui/web_new_v2/js/library.js:67-75
  btnBatchCancel.addEventListener('click', async () => {
      if (window.pywebview?.api?.cancel_batch_download) {
          await window.pywebview.api.cancel_batch_download();   // result ignored
          if (batchProgressBox) batchProgressBox.style.display = 'none';
          window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Пакетное скачивание отменено', type: 'warning' } }));
      }
  });
  ```
  ```python
  # core/downloader.py:273-282
  if hasattr(self._core.db, 'download_queue_cancel_pending'):
      self._core.db.download_queue_cancel_pending()      # -> UPDATE ... WHERE status='pending' (all rows)
  ...
  for row in self._store.rows(('pending', 'downloading', 'cancelled'), limit=5000):
      self._store.update(row['track_id'], status='cancelled', resume_on_restart=0)
  ```
- **Reproduction / verification:** queue one download individually, start a favourites batch, press
  "Отменить" → `download_queue` shows `status='cancelled'` for the individually queued track as
  well.
- **Suggested fix:** scope the cancellation to the batch's track ids, and have the UI branch on
  the returned boolean.
- **Fix side effects:** scoping the cancel to the batch requires the downloader to remember which
  track ids belong to the active batch (it currently only keeps counters) — a non-trivial change
  in WN-13.
- **Discovered by:** A

---

### 3. Clean areas

- **`toggle_zapret` argument and binary handling — no injection, no arbitrary exe.**
  `custom_args` is only used in `mode == "custom"`; every token must match
  `^--[A-Za-z0-9][A-Za-z0-9\-]*(=[A-Za-z0-9,.:_/\-\\ ]*)?$`
  (`services/zapret_service.py:90, 203-219`), which excludes quotes, `;`, `&`, `|`, `>`, `%`, `^`.
  `subprocess.Popen(args_list, …)` is called with a **list** (`services/zapret_service.py:1167-1173`),
  never with `shell=True`. `binary_path` goes through `validate_zapret_binary()`
  (`services/zapret_service.py:222-262`): absolute drive-letter path only (no UNC), must live inside
  `~/.nedotify/zapret` or the app directory, the basename must be in
  `{winws.exe, zapret.exe, winws}`, and the file must be a valid PE image. The bypass itself is
  host-scoped (`--hostlist-domains=` with `ZAPRET_SCOPED_HOSTS`), so it does not affect the whole
  system.
- **`toggle_zapret` state persistence.** `zapret.enabled` is stored as `enabled and success`, so a
  failed start is not persisted as "enabled"; `get_zapret_status` /
  `check_zapret_update` / `update_zapret` are fully exception-guarded and return dicts containing
  every key the UI reads (`running`, `mode`, `auto_start`, `autoupdate`, `custom_args`,
  `binary_path`, `version`).
- **`prefetch_track` concurrency and side effects.** The pending set is guarded by the existing
  `_search_lock` (no second lock), the executor saturation is handled (`RuntimeError` on submit →
  the key is discarded and `False` returned, `core/api.py:3677-3682`), the same track is never
  prefetched twice concurrently, and the resolver's single-flight
  (`core/resolver.py:187-224`) prevents a duplicate provider extraction. The prefetch copies the
  track (`candidate = dict(track_data)`) and never mutates the frontend queue object, and it does
  **not** start playback or listening accounting. It does write the URL cache row
  (`db.cache_stream` via `StreamResolver._persist`, `core/resolver.py:256-267`).
- **Download status string sets match on both sides.** The backend writes exactly
  `{pending, downloading, paused, completed, failed, cancelled}` —
  `core/downloader.py:111` (`paused`), `:770` (`downloading`), `:829` (`:833`) (`completed`),
  `:850` (`:855`) (`failed`), `:564` / `:278` (`cancelled`), `core/download_store.py:43-44` (the
  ordering that lists the same set) — and `ui/web_new_v2/js/downloads-view.js:9-12` declares
  exactly the same six labels; the "pausable / resumable" predicates
  (`['pending','downloading']` / `'paused'`, `downloads-view.js:51-52`) match
  `DownloadManager.pause_download` (which selects `('pending','downloading')`) and
  `resume_download` (which selects `('paused',)`). `get_downloads` adds `user_error` exactly for
  `status == 'failed'`, and `describe_error` returns the `{message}` the JS reads
  (`downloads-view.js:40`).
- **`retry_failed_downloads` really re-arms the failed rows.**
  `core/database.py:2347-2356` upserts with
  `ON CONFLICT(track_id) DO UPDATE SET status='pending' … WHERE status IN ('failed','cancelled')`,
  so the retry is not silently swallowed by the unique index (the naive `INSERT` path would have
  been).
- **Smart playlists: rule validation, SQL injection, pagination.**
  `normalize_rule` (`services/smart_playlists.py:20-51`) rejects unknown keys, non-`int`/out-of-range
  periods, non-`bool` filters, over-long artist names and an unknown sort; `_name` and `_id`
  validate the name and the id. The artist filter escapes `%`, `_` and `\` and uses
  `LIKE ? ESCAPE '\'` (`services/smart_playlists.py:152-155`); the ORDER BY comes from the fixed
  `SORTS` whitelist (`:7-13`); the dynamic SQL only ever concatenates values from that whitelist
  plus parameterised conditions. `tracks()` validates `limit` (1..500) and `offset` (0..100000)
  and applies them **after** the offline availability filter, so pagination is consistent in both
  modes. An empty playlist returns `[]`, not an error, and the JS renders its own empty state
  (`ui/web_new_v2/js/library.js:519`).
- **`get_offline_library` returns only tracks whose file actually exists.**
  `offline_library(db)` → `available_tracks()` → `_local_file()` checks
  `os.path.isfile(path)` and a size floor (4096 bytes for cached files, `core/offline.py:17-26`),
  so a dangling `stream_cache` row cannot surface a non-existent track.
- **`get_search_suggestions` validates its input** (`utils/search_query.py:31-38`): a non-string or a
  query shorter than 3 / longer than 120 characters returns `[]`; the candidate set is capped at
  4000 entries and no vocabulary is persisted.
- **`cancel_batch` internals are sound** (epoch bump + cooperative checkpoints, queue rows closed,
  `batch_download_cancelled` emitted exactly once, `_batch_active` reset) — the defect is only that
  the *pause* path has no equivalent transition (F-WN-10-3).
- **`get_feed` / `get_home_artists` / `get_home_releases` / `get_home_mixes`** are asynchronous with
  error fallbacks, emit their own `*_ready` events and fabricate no data
  (`core/api.py:3740-3794`); `get_feed` clamps `max_results` to 0..50 in the service
  (`services/recommendation_service.py:627`).

---

### 4. Coverage gaps

- **Not verified at runtime:** the real app was never started (per the ground rules) and
  `~/.nedotify/` was never touched. All reproductions used `DatabaseManager(":memory:")` and temp
  directories under `%TEMP%`; the three scratch scripts live outside the repo.
- **Windows file-locking semantics** of `os.remove` against a file currently served by the proxy
  were not observed live; the analysis of F-WN-10-1 relies on CPython's default Windows share
  flags (the proxy opens files read-only, so the delete is refused with `PermissionError` and the
  file is kept — this is why F-WN-10-1 is about *which* files are chosen, not about files being
  deleted while open).
- **WN-11 (proxy) was only read at the cache write/read sites** (780–840, 1185–1234) that matter
  for this area; the proxy's own serving, auth and self-healing logic was not audited.
- **Cross-area root cause, flagged but not owned here:** `services/zapret_service.py:1281-1285`
  builds the elevated launch as a `cmd.exe /c "…"` **string** and interpolates `exe` into it. `exe`
  is validated to be inside `~/.nedotify/zapret` or the app directory, but a user profile path
  containing a cmd metacharacter (e.g. `C:\Users\John & Jane\…`) would break — and in principle
  split — that command. The root cause belongs to **WN-26**; the WN-10 part (`toggle_zapret`
  forwarding `binary_path` verbatim) is only the trigger.
- **Cross-area root cause, flagged but not owned here:** `services/smart_playlists.py:159` uses
  `NULLIF(sc.cached_file_path,'') IS NOT NULL` as an availability predicate without checking that
  the file exists; it happens to be safe today because `available_tracks()` re-filters afterwards,
  but a dangling row (which F-WN-10-1 produces) makes the SQL over-approximate — **WN-24**.
- **Runtime composition of the playback queue** (whether entries carry `file_path`) was not
  observed live, so the reachability of the `available_tracks` sub-claim in F-WN-10-8 is a
  hypothesis; the code asymmetry itself is confirmed.
- **The Android subtree was not opened** (out of scope for this run).
