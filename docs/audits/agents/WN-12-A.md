## AREA WN-12 — SQLite persistence layer — ROLE A

### 1. Scope reviewed

- `core/database.py` — **read in full, physical lines 1–2489** (no range skipped).
  - helpers: `name_is_meaningful` L109-121, `_is_empty_value` L124-132, `_latest_timestamp` L135-143,
    `TRACKS_UPDATABLE_COLUMNS` L22-50, `ALLOWED_TRACK_ORDER_BY` L55-70,
    `TRACK_IDENTITY_SQL` L82, `TRACK_RECORDING_COLUMNS` L88, `DUP_CARRY_OVER_COLUMNS` L92-97,
    `PLACEHOLDER_TRACK_NAMES` L103-106.
  - `DatabaseManager`: `__init__` L151-165, `get` L167-177, `_get_connection` L179-201, `conn` L203-205,
    `_init_database` L207-505 (schema DDL L211-368, ALTERs L288-296/L370-377/L477-496,
    `ensure_download_queue_table` call L383, migrations L392-395, history-duration repair L399-412,
    FTS5 L425-475, `portable_library_id` L501-505).
  - dup-cleanup migration: `_run_dup_cleanup_migration` L524-653, `_run_dup_cleanup_restore` L655-719,
    `_ensure_migration_tables` L721-757, `_snapshot_before_dup_cleanup` L759-796,
    `_plan_track_merges` L798-846, `_apply_track_merges` L848-869,
    `_merge_track_row_into` L871-966, `_remove_exact_duplicate_playlist_entries` L968-985,
    `_restore_merged_tracks` L987-1052.
  - tracks: `add_track` L1054-1164, `get_track*` L1166-1246, `toggle_favorite` L1248-1258,
    `ensure_track_exists` L1260-1276, `mark_track_downloaded` L1278-1282,
    `log_listening_history` L1289-1318, `record_listening_once` L1320-1338,
    `update_track_play` L1340-1347, `_like_pattern` L1349-1364, `search_*` L1366-1437,
    `delete_track` L1484-1489, `update_track` L1491-1514, `update_track_metadata` L1516-1552.
  - history/listening: `add_to_history` L1555, `begin_listening_session` L1558-1567,
    `get_recommendation_quality` L1569-1584, `update_history_duration` L1586-1597,
    `get_history` L1599-1624, `get_tracks_missing_cover` L1626-1655, `backfill_track_metadata` L1665-1693,
    `get_wrapped_stats` L1723-1834, `get_analytics_summary` L1836-1860.
  - playlists: `create_playlist` L1862, `create_playlist_ex` L1867-1890,
    `_cleanup_duplicate_empty_system_playlists` L1892-1929, `get_playlists` L1931-1943,
    `add_to_playlist` L1950-1970, `add_tracks_to_playlist` L1972-1999,
    `get_playlist_tracks` L2004-2016, `delete_playlist` L2018-2026.
  - settings: `_serialize_setting` L2028-2034, `set_setting` L2036-2047, `set_settings_batch` L2049-2082,
    `get_setting` L2084-2098, `get_settings_by_category` L2100-2115, `get_all_settings` L2117-2132.
  - stream cache: `set_cached_file` L2134-2147, `get_cached_stream` L2149-2160, `cache_stream` L2162-2197,
    `update_cached_stream_url` L2199-2211, `invalidate_cached_stream` L2213-2225,
    `cleanup_expired_cache` L2227-2242.
  - scan folders / listening time L2244-2282; download queue L2284-2411;
    lifecycle `close_thread_connection` L2413-2438, `_checkpoint_wal` L2440-2457, `close` L2459-2489.
- Callers traced (read, not reviewed — defects there are attributed to the owning area):
  - `core/api.py` L483, 1177-1183, 1290-1330, 1533, 1676, 2144-2148, 2271, 2300-2360, 2385-2410,
    2500-2560, 2619-2680, 2945-3020, 3141-3170, 3236-3260, 3295-3350, 3391-3435.
  - `core/settings.py` L290-341 (`_load_all`), L401-418 (`set`), L443-506 (`flush`/`_write_batch`).
  - `core/downloader.py` L101-138 (pause/resume/retry), L255-285 (cancel), L287-354
    (`_init_db_table`, `_resume_pending_downloads`), L356-394 (`queue_download`), L560-610,
    L739-790, L802-880.
  - `core/download_store.py` L1-71 (adds `resume_on_restart`/`paused` etc. to `download_queue`).
  - `core/proxy.py` L469-487 (`finish()` → `close_thread_connection`), L762-835 (`get_cached_stream`,
    `set_cached_file`), L1284-1298 (`stop()`).
  - `core/resolver.py` L141-163 (`get_cached_stream`), L252-265 (`invalidate_cached_stream`,
    `cache_stream`).
  - `core/app.py` L168-185 (periodic `cleanup_expired_cache`), L508-586 (`cleanup()` → `db.close`).
  - `main.py` L512-539 (watchdog restart → `cleanup()` → `os._exit(3)`).
  - `utils/cache_manager.py` L142-270 (the on-disk stream files are purged there, not by the DB).
- Runtime probes (throwaway SQLite files under `%TEMP%\opencode`, never the real `~/.nedotify/`):
  `repro_wn12.py`, `repro_wn12_b.py`, `repro_wn12_c.py` — interpreter
  `& ".venv_win\Scripts\python.exe"`. No repo file was modified.

### 2. Findings

#### F-WN-12-1  [P1] — The dup-cleanup merge loses play counts, the favourite flag and `last_played` when a partition has 3+ rows (stale survivor snapshot)

- **File:** `core/database.py:848-869` (`_apply_track_merges`), `core/database.py:892-923`
  (`_merge_track_row_into`); secondary `core/database.py:798-846` (`_plan_track_merges`).
- **Confirmed:** yes (runtime, deterministic).
- **Description:** the plan stores the survivor as a **dict read at plan time**. `_merge_track_row_into`
  then writes **absolute** values computed from that stale dict (`play_count = ?`, `is_favorite = ?`,
  `last_played = ?`) instead of reading the row's current state or using relative SQL. With a
  partition of 3+ rows, the second merge overwrites what the first merge already wrote.
- **Cause:** `_apply_track_merges` re-uses `entry["survivor"]` for every duplicate of the partition
  and never refreshes it; the UPDATE at L920-923 assigns absolute values.
- **Trigger conditions:** a `LOWER(title)/LOWER(artist)` group whose members share **all six**
  recording fields (`title, artist, album, source, source_id, file_path`) — i.e. 3+ rows in one
  partition. Reachable in a legacy library whose `tracks` table predates `file_path TEXT UNIQUE`
  (the code itself documents this at L357-360: *"older databases were created without UNIQUE on
  file_path"*), or with `file_path IS NULL` rows (NULLs do not collide under UNIQUE).
- **User impact:** silent loss of listening counts (plays disappear from "Most played" / Wrapped),
  a **favourite flag that is silently cleared**, and `last_played` moving **backwards** — the track
  then looks unplayed. This happens inside the migration that is supposed to be the *safe* one.
- **Evidence:**
  ```python
  # core/database.py:863-869  - the survivor dict is captured once, at plan time
  for entry in plan:
      survivor = entry["survivor"]
      for duplicate in entry["duplicates"]:
          if self._merge_track_row_into(cursor, survivor, duplicate, stats, columns):
              stats["merged"] += 1
  # core/database.py:905-913 - absolute assignment from the STALE dict
  if "play_count" in columns:
      assignments.append("play_count = ?")
      params.append((survivor.get("play_count") or 0) + (duplicate.get("play_count") or 0))
  if "is_favorite" in columns:
      assignments.append("is_favorite = ?")
      params.append(1 if (survivor.get("is_favorite") or duplicate.get("is_favorite")) else 0)
  if "last_played" in columns:
      assignments.append("last_played = ?")
      params.append(_latest_timestamp(survivor.get("last_played"), duplicate.get("last_played")))
  ```
  Measured (3 rows in one partition, play_count 3/5/7, favourite on the middle row,
  `last_played` 2026-01-01 / 2026-02-02 / 2026-03-03):
  ```
  rows: [(1, 10, 0, '2026-03-03 12:00:00')]      # actual
  EXPECTED                                play_count=15  is_favorite=1  last_played='2026-03-03 12:00:00'
  ```
  With the favourite + newest stamp on the **middle** row:
  ```
  rows: [(1, 10, 0, '2026-03-03 12:00:00')]      # actual
  EXPECTED                                play_count=15  is_favorite=1  last_played='2026-09-09 23:59:59'
  ```
  → `last_played` regressed from 2026-09-09 to 2026-03-03, the favourite flag was cleared, 5 plays lost.
  With only **2** rows in the partition the result is correct
  (`[(1, 8, 1, '2026-02-02 11:00:00')]`), which is why the existing test
  `tests/test_dup_cleanup_migration.py::test_true_duplicate_is_merged_not_dropped` (2 rows) passes.
- **Reproduction / verification:** build a `tracks` table **without** `file_path TEXT UNIQUE`
  (legacy shape) holding three rows with identical `title/artist/album/source/source_id/file_path`,
  insert them, then open the DB with `DatabaseManager(path)` and read
  `SELECT id,play_count,is_favorite,last_played FROM tracks`.
  Probe: `%TEMP%\opencode\repro_wn12_b.py` PROBE A/B (also PROBE C = the 2-row control).
- **Suggested fix:** make the merge relative instead of absolute — `play_count = play_count + ?`,
  `is_favorite = MAX(is_favorite, ?)`, `last_played = MAX(last_played, ?)` — or re-read the survivor
  row (`SELECT * FROM tracks WHERE id = ?`) at the top of `_merge_track_row_into` and compute from the
  fresh values. Also re-read before the "carry the payload over where the survivor has none" step.
- **Fix side effects:** re-reading changes "first non-empty wins" to "current non-empty wins" for the
  carried-over columns; the relative `play_count = play_count + ?` form is the minimal, behaviour-
  preserving fix. `MAX(last_played, ?)` on TEXT timestamps is lexicographic and matches
  `_latest_timestamp`'s string comparison.
- **Discovered by:** A

#### F-WN-12-2  [P2] — The "corrective" restore migration can never undo a merge: the safety net is inert

- **File:** `core/database.py:1001-1005` (`_restore_merged_tracks` candidate query),
  `core/database.py:668-672` (restore version guard), `core/database.py:961-965`
  (the only writer of `track_merges`).
- **Confirmed:** yes (runtime).
- **Description:** the restore looks for `track_merges` rows whose `merged_by <> DUP_CLEANUP_VERSION`,
  but the **only** code that writes `track_merges` writes `merged_by = DUP_CLEANUP_VERSION`
  (`'dup_cleanup_v2'`). The candidate set is therefore always empty. In addition the restore's own
  version record (`dup_cleanup_restore_v1`) is written during the *same* startup, so it can never run
  a second time either.
- **Cause:** the exclusion predicate is the exact value the only writer produces, and the version
  guard is written before any later merge could exist.
- **Trigger conditions:** always — the restore can never fire, in any library state.
- **User impact:** the corrective migration advertised in `docs/REMEDIATION_TRACKER.md` ("1.5
  corrective migration that restores from the backup table where one exists") provides **no**
  protection. `tracks_backup`, `track_merges`, `history_track_remap` and
  `playlist_tracks_track_remap` are permanent dead weight in the user's DB, and a future buggy merge
  version would not be rolled back by anything. (Even if it fired, the undo is partial: only
  `play_count` is subtracted from the survivor — `is_favorite`, `last_played` and the carried-over
  payload columns are *not* restored.)
- **Evidence:**
  ```python
  # core/database.py:961-965 - the only writer of track_merges
  cursor.execute(
      "INSERT OR REPLACE INTO track_merges (duplicate_id, survivor_id, merged_by, merged_at) "
      "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
      (duplicate_id, survivor_id, self.DUP_CLEANUP_VERSION),   # 'dup_cleanup_v2'
  )
  # core/database.py:1001-1005 - the restore excludes exactly that value
  cursor.execute(
      "SELECT duplicate_id, survivor_id FROM track_merges "
      "WHERE merged_by <> ? AND duplicate_id NOT IN (SELECT id FROM tracks)",
      (self.DUP_CLEANUP_VERSION,),
  )
  ```
  Measured after a real 2-row merge:
  ```
  tracks after v2 merge: [(1, 8)]
  track_merges: [(2, 1, 'dup_cleanup_v2', '2026-10-20 19:23:26')]
  schema_migrations: [('dup_cleanup_restore_v1',), ('dup_cleanup_v2',)]
  tracks_backup rows: 2
  ```
  The merged row stayed merged, `track_merges` names it, and the restore did nothing.
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12_c.py` PROBE E — open a legacy DB with
  two identical rows, let the migration run, then read `track_merges` and `tracks`.
- **Suggested fix:** either drop the restore migration and the four bookkeeping tables, or make it
  version-aware in the other direction (restore rows whose `merged_by` is *any known-bad* version) and
  give it a version record that is only written when the merge it corrects is known to be complete.
- **Fix side effects:** re-enabling the restore would resurrect rows for libraries where the legacy
  destructive cleanup already ran — the `legacy_destructive_migration_ran` branch must keep
  excluding them.
- **Discovered by:** A

#### F-WN-12-3  [P1] — `close()` can block for 30 s on the WAL TRUNCATE checkpoint, freezing app shutdown

- **File:** `core/database.py:2440-2457` (`_checkpoint_wal`), `core/database.py:2459-2489` (`close`);
  caller `core/app.py:559-560` (`_step("db.close", self.db.close)`), `main.py:530` (watchdog path).
- **Confirmed:** yes (runtime, measured).
- **Description:** `close()` runs `PRAGMA wal_checkpoint(TRUNCATE)` on the calling thread's
  connection. TRUNCATE must wait for **every** other reader to finish; the busy timeout is 30 000 ms
  (both `sqlite3.connect(..., timeout=30.0)` at L181 and `PRAGMA busy_timeout=30000` at L190). If any
  other connection holds a read lock, `close()` blocks for the full 30 s.
- **Cause:** a blocking checkpoint mode combined with a 30-second busy timeout, executed on the
  shutdown path.
- **Trigger conditions:** any concurrent reader at shutdown — an in-flight proxy request thread
  (`core/proxy.py` is thread-per-request; `daemon_threads = True`, and `LocalProxyManager.stop()`
  at `core/proxy.py:1284-1298` calls `server.shutdown()` which does **not** join handler threads),
  the settings writer thread (`core/settings.py:520-530`), or a downloader worker.
  Note `app.py` stops the proxy at L551-552 and closes the DB at L559-560, but `stop()` does not
  wait for the request threads that already hold a connection.
- **User impact:** the app appears frozen on exit for up to 30 s (window still up, tray "quit"
  unresponsive); on the watchdog restart path (`main.py:514-539`) the process is held in `cleanup()`
  before `os._exit(3)`.
- **Evidence:**
  ```python
  # core/database.py:2454-2457
  try:
      self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
  except sqlite3.Error as e:
      logger.warning("WAL checkpoint failed: %s", e)
  # core/database.py:181 / 190
  conn = sqlite3.connect(self.db_path, timeout=30.0)
  ...
  "PRAGMA busy_timeout=30000",
  ```
  Measured with a second connection holding a read transaction:
  ```
  close() took 32.33s while a reader held a read lock
  ```
  (without the reader: instant).
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12_c.py` PROBE F — open a DB, start a
  second `sqlite3.connect`, `BEGIN` + `SELECT`, then time `db.close()`.
- **Suggested fix:** use `PRAGMA wal_checkpoint(PASSIVE)` (never blocks) or `RESTART` with a short
  busy timeout; or checkpoint before the proxy is stopped and set `busy_timeout` low for the
  shutdown connection.
- **Fix side effects:** PASSIVE may leave the `-wal` file populated; SQLite still recovers it on the
  next open, so no data is lost — but the WAL file is not truncated, so the "reset the -wal file"
  benefit of TRUNCATE is lost.
- **Discovered by:** A

#### F-WN-12-4  [P2] — Settings round trip silently changes the type of string values; `None` comes back as `""` and permanently overrides the shipped default

- **File:** `core/database.py:2028-2034` (`_serialize_setting`), `core/database.py:2084-2098`
  (`get_setting`), `core/database.py:2100-2132` (`get_settings_by_category`, `get_all_settings`);
  consumer `core/settings.py:315-342` (`_load_all`).
- **Confirmed:** yes (runtime).
- **Description:** `_serialize_setting` writes a `str` verbatim, but every reader starts with
  `json.loads(raw_v)`. A string whose content happens to be valid JSON is therefore converted:
  `"123"` → `123`, `"1.5"` → `1.5`, `"true"` → `True`, `"null"` → `None`, `"[1,2]"` → `[1,2]`,
  `'{"a":1}'` → `{'a':1}`. Separately, `None` is stored as the empty string `""` and read back as
  `""` (not `None`).
- **Cause:** the storage format does not record the *type* of the value; the reader has to guess.
- **Trigger conditions:** any setting whose string value is valid JSON. In the shipped defaults
  (`core/settings.py:61-284`) no string default is numeric, but the values are user-editable from
  the UI (`save_setting` → `SettingsManager.set` → flush → `set_settings_batch`).
- **User impact:** (a) the UI receives a number/bool/`null` where it sent a string, so a value can
  change type across a restart; (b) a setting written as `null` is stored as `""`, and because
  `core/settings.py:324-334` only falls back to the shipped default when the key is **absent**,
  the empty string permanently overrides the default (e.g. `quality: "high"` → `""`).
- **Evidence:**
  ```python
  # core/database.py:2028-2034
  @staticmethod
  def _serialize_setting(value: Any) -> str:
      if isinstance(value, (dict, list, bool, int, float)):
          return json.dumps(value)
      if value is None:
          return ""                       # <-- None becomes the empty string
      return str(value)                  # <-- a str is written untyped
  # core/database.py:2084-2098
  raw_v = row["value"]
  try:
      return json.loads(raw_v)           # <-- applied to EVERY stored value
  except (json.JSONDecodeError, TypeError):
      ...
  ```
  Measured:
  ```
  CHANGED  set '123'          -> got 123 (int)
  CHANGED  set 'true'         -> got True (bool)
  CHANGED  set 'null'         -> got None (NoneType)
  CHANGED  set '[1,2]'        -> got [1, 2] (list)
  CHANGED  set '{"a":1}'      -> got {'a': 1} (dict)
  OK       set 'hello'        -> got 'hello' (str)
  None round-trip -> ''
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12.py` PROBE 3 — `set_setting(k, "123")`
  then `get_setting(k)`.
- **Suggested fix:** store an explicit envelope (e.g. `json.dumps({"t": "str", "v": value})`) or
  prefix non-JSON strings (e.g. a `s:` marker) so the reader can tell a string from JSON; keep
  `None` distinguishable from `""`.
- **Fix side effects:** a format change invalidates every already-stored setting row — a
  migration (or a tolerant reader that accepts the old raw form) is required, otherwise every
  existing user's settings silently revert to their defaults on the first start after the change.
- **Discovered by:** A

#### F-WN-12-5  [P2] — `tracks.file_path` is UNIQUE, so `mark_track_downloaded`/`update_track` can raise IntegrityError; the downloader's fallback repeats the failing statement and wedges the queue row in `downloading`

- **File:** `core/database.py:219` (`file_path TEXT UNIQUE`), `core/database.py:1278-1282`
  (`mark_track_downloaded`), `core/database.py:1491-1514` (`update_track`).
  Caller: `core/downloader.py:818-827` (the fallback) and `core/downloader.py:828-840`.
- **Confirmed:** yes (runtime for the DB side; the caller side is read from the source).
- **Description:** `mark_track_downloaded(track_id, file_path)` writes `file_path` unconditionally.
  If another `tracks` row already owns that path, SQLite raises
  `IntegrityError: UNIQUE constraint failed: tracks.file_path`. The downloader catches it and then
  **re-executes the identical UPDATE** inside the `except` block — which raises again, this time
  uncaught → the worker dies before `download_queue_set_status(track_id, 'completed')` runs.
- **Cause:** the DB applies the UNIQUE constraint (correctly); the caller's error path re-runs the
  statement that just failed.
- **Trigger conditions:** two track rows resolving to the same download filename (same
  artist/title from different providers, or a re-download of a track whose row still holds the old
  path).
- **User impact:** the download-queue row stays `'downloading'` forever. On the next start
  `download_queue_get_pending()` (`core/database.py:2408-2411`) returns it again and the download is
  retried — a permanent loop. `download_complete` never fires, so the UI never learns the file is
  there.
- **Evidence:**
  ```python
  # core/database.py:219
  file_path TEXT UNIQUE,
  # core/database.py:1278-1282
  def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
  Measured:
  ```
  update_track -> IntegrityError: UNIQUE constraint failed: tracks.file_path
  mark_track_downloaded -> IntegrityError: UNIQUE constraint failed: tracks.file_path
  ```
  ```python
  # core/downloader.py:818-827 - the fallback repeats the failing statement
  try:
      self._core.db.mark_track_downloaded(track_id, file_path)
  except Exception as me:
      logger.error(f'mark_track_downloaded failed for {track_id}: {me}')
      with self._core.db._write_lock:
          with self._core.db.conn:
              self._core.db.conn.execute(
                  "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
                  (file_path, track_id),          # <-- raises the same IntegrityError, uncaught
              )
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12.py` PROBE 4 — add two tracks, then
  `mark_track_downloaded(t2, "<path already owned by t1>")`.
- **Suggested fix:** the DB side should make the write collision-tolerant (e.g. clear the stale
  `file_path` of the other row, or use `file_path = NULL` on conflict); the caller side
  (`core/downloader.py`, area WN-13) must not re-execute the statement that just failed and must
  still mark the queue row terminal.
- **Fix side effects:** relaxing the UNIQUE constraint would remove the "one row per file" guarantee
  that `add_track` and `get_track_by_path` rely on; prefer resolving the collision explicitly.
- **Discovered by:** A (DB contract; the unhandled retry belongs to WN-13)

#### F-WN-12-6  [P3] — The download-queue state machine cannot re-arm a `paused` row, so a paused download cannot be re-triggered through `download_queue_add`

- **File:** `core/database.py:2330-2359` (`download_queue_add`), `core/database.py:2361-2370`
  (`download_queue_set_status`), `core/database.py:2408-2411` (`download_queue_get_pending`).
  Caller: `core/downloader.py:356-376` (`queue_download`).
- **Confirmed:** yes (code + the pinned behaviour in `tests/test_db_core_fixes_f2.py:71-74`, which
  asserts `download_queue_add(...) is False` for a non-terminal status).
- **Description:** the statuses written by the system are `pending`, `downloading`, `completed`,
  `failed`, `cancelled` and `paused`. `download_queue_add` re-arms **only** `failed` and
  `cancelled`; for a `paused` row the `ON CONFLICT ... DO UPDATE ... WHERE` does not match, so
  `rowcount == 0` and the helper returns `False`. `download_queue_get_pending` only returns
  `pending`/`downloading`, so a `paused` row is also invisible to the resume-on-start path.
- **Cause:** the re-arm list and the pending list are two separate, hand-maintained whitelists that
  do not cover every status the code writes.
- **Trigger conditions:** the user queues a download while offline (`core/downloader.py:378-383`
  writes `status='paused'`), or pauses a download
  (`core/downloader.py:101-113`), and then clicks "download" again on that track.
- **User impact:** `queue_download` returns `False`, `AppApi.download_track` returns `False`
  (`core/api.py:2346-2360`) and **no event is emitted** — the click appears to do nothing. Only the
  explicit "resume" action (`core/downloader.py:115-128`, which writes `status='pending'` through
  `DownloadStore`) recovers it.
- **Evidence:**
  ```python
  # core/database.py:2347-2352
  cursor.execute(
      'INSERT INTO download_queue (track_id, source, source_id) VALUES (?, ?, ?) '
      "ON CONFLICT(track_id) DO UPDATE SET status = 'pending', added_at = CURRENT_TIMESTAMP "
      "WHERE download_queue.status IN ('failed', 'cancelled')",
      (track_id, source, source_id),
  )
  # core/database.py:2408-2411
  cursor.execute("SELECT track_id, source, source_id FROM download_queue WHERE status IN ('pending', 'downloading')")
  ```
- **Reproduction / verification:** `db.download_queue_add(1,'yt','v1')` → `db.download_queue_set_status(1,'paused')`
  → `db.download_queue_add(1,'yt','v1')` returns `False` and the status stays `paused`.
- **Suggested fix:** derive the re-armable set from one shared constant (e.g. `TERMINAL_STATES =
  {'failed','cancelled','paused'}`), and make sure `download_queue_get_pending` and the resume path
  agree on which states are resumable.
- **Fix side effects:** re-arming `paused` on a plain download click would restart a download the
  user explicitly paused; the pause state would then have to be tracked separately from the queue
  row.
- **Discovered by:** A

#### F-WN-12-7  [P3] — A `settings` table without a `category` column makes `DatabaseManager.__init__` raise (no ALTER for `settings`, unlike `tracks`/`history`/`playlists`)

- **File:** `core/database.py:298-307` (`CREATE TABLE IF NOT EXISTS settings`),
  `core/database.py:501-504` (the `portable_library_id` INSERT), `core/database.py:621-624`
  (the flag INSERT inside the migration).
- **Confirmed:** yes (runtime) — **but not reachable through this repository's own history**:
  `git show b6a6553:core/database.py` (the first commit touching the file) already declares
  `category TEXT DEFAULT 'general'` and `updated_at`. Every column added to `tracks`, `history` and
  `playlists` since then *does* get an `ALTER TABLE ... ADD COLUMN` (L288-296, L370-377, L477-496);
  `settings` does not.
- **Description:** `CREATE TABLE IF NOT EXISTS` never touches an existing table, so a `settings`
  table with a different shape survives `_init_database` unchanged and the first write that mentions
  `category` raises.
- **Trigger conditions:** a database whose `settings` table predates the `category` column (a
  hand-made DB, a restored backup from another build/fork, or an export from the Android product).
- **User impact:** `DatabaseManager.__init__` raises → the app cannot start at all. In the
  migration path the failure is contained (L621-624 → the migration rolls back and logs an ERROR),
  but the `portable_library_id` INSERT at L501-504 is not guarded → the constructor raises and the
  whole app dies at boot.
- **Evidence:**
  ```python
  # core/database.py:501-504 - not wrapped in try/except
  cursor.execute(
      "INSERT OR IGNORE INTO settings (key, value, category) VALUES (?, ?, ?)",
      ("portable_library_id", str(uuid.uuid4()), "general"),
  )
  ```
  Measured with a legacy `settings (key TEXT PRIMARY KEY, value TEXT)` table:
  ```
  Dup cleanup: the migration failed and was rolled back - the library is unchanged and the migration
  runs again on the next start: table settings has no column named category
  ...
  File "core/database.py", line 501, in _init_database
    cursor.execute("INSERT OR IGNORE INTO settings (key, value, category) VALUES (?, ?, ?)")
  sqlite3.OperationalError: table settings has no column named category
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12_c.py` PROBE I.
- **Suggested fix:** add the same `ALTER TABLE settings ADD COLUMN category / updated_at` guard that
  the other tables use, and wrap the `portable_library_id` insert in the same tolerant pattern.
- **Fix side effects:** none — the ALTER is a no-op on an up-to-date DB.
- **Discovered by:** A

#### F-WN-12-8  [P3] — A repeatedly failing dup-cleanup migration leaves one full copy of the library per app start

- **File:** `core/database.py:759-796` (`_snapshot_before_dup_cleanup`), `core/database.py:781-784`
  (the timestamped file name and the `VACUUM INTO`), `core/database.py:595` (when the snapshot is
  taken).
- **Confirmed:** yes (code reading).
- **Description:** the snapshot is a **dated** copy: `<db>.dup-cleanup-<YYYYmmdd-HHMMSS-ffffff>.db`.
  The one-shot guard mentioned in the docstring is the `tracks_backup` **table**; the **file** has no
  guard and no cleanup. A migration that fails (e.g. an `IntegrityError` inside
  `_apply_track_merges`) rolls back and re-runs on the next start, and each attempt writes another
  full copy of the database next to it.
- **Cause:** the snapshot file name is unique per attempt and nothing ever prunes it.
- **Trigger conditions:** a migration that keeps failing on the same library.
- **User impact:** unbounded growth of `~/.nedotify/` (one full library copy per start) and an
  accumulation of full copies of the user's listening history on disk.
- **Evidence:**
  ```python
  # core/database.py:781-784
  stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
  snapshot_path = f"{self.db_path}.dup-cleanup-{stamp}.db"
  try:
      self.conn.execute("VACUUM INTO ?", (snapshot_path,))
  ```
  The docstring at L760-761 claims *"One-shot: it is never overwritten"* — true for the file, but
  the file is *added* on every attempt.
- **Reproduction / verification:** run the migration against a DB that makes `_apply_track_merges`
  raise, restart the app twice, and list `~/.nedotify/*.dup-cleanup-*.db` (not executed here — the
  real profile was not touched).
- **Suggested fix:** keep one snapshot file per library (fixed name, replaced on each attempt) or
  delete the previous snapshot when a new one is written.
- **Fix side effects:** a fixed name means the "original pre-migration state" is overwritten by a
  later attempt — the `tracks_backup` table would then be the only durable pre-merge copy.
- **Discovered by:** A

#### F-WN-12-9  [P3] — `close()` cannot close other threads' connections, drops the handles anyway, and is not final

- **File:** `core/database.py:2459-2489` (`close`), `core/database.py:2413-2438`
  (`close_thread_connection`).
- **Confirmed:** yes (runtime).
- **Description:** sqlite3 refuses a cross-thread `close()`, so `close()` cannot release the
  connections created by the proxy/downloader threads; it counts the failures, logs one summary
  line, and then `self._all_conns.clear()` — the handles are dropped from the manager's bookkeeping
  and are never retried. The connections stay alive until their owning thread ends. In addition,
  after `close()` the manager still answers `self.conn` by opening a **new** connection.
- **Cause:** `sqlite3.Connection.close()` is thread-affine; the manager has no way to ask another
  thread to close its handle other than the cooperative `close_thread_connection()`.
- **Trigger conditions:** every shutdown with at least one other thread that touched the DB.
- **User impact:** the "closed" state is not final — a late call on the manager re-opens the
  database. The lingering connections are bounded (one per thread) and are released when the thread
  dies, and the proxy already calls `close_thread_connection()` in `finish()`
  (`core/proxy.py:469-487`), so the practical impact is small.
- **Evidence:**
  ```python
  # core/database.py:2474-2482
  with self._conns_lock:
      for conn in list(self._all_conns):
          try:
              conn.close()
          except Exception as e:
              failed += 1
              ...
      self._all_conns.clear()          # <-- dropped even when the close failed
  ```
  Measured:
  ```
  1 database connection(s) could not be closed from the main thread (created on another thread);
     they were released when that thread exited. First error: SQLite objects created in a thread
     can only be used in that same thread. ...
  use after close(): <sqlite3.Row ...>   - a NEW connection was opened (close is not final)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\repro_wn12.py` PROBE 2.
- **Suggested fix:** keep the failed handles in `_all_conns` so a later `close_thread_connection()`
  can still discard them, and set an explicit "closed" flag that makes `conn` raise instead of
  silently re-opening the DB.
- **Fix side effects:** making `conn` raise after `close()` would break any late caller that
  currently "works by accident" (e.g. `main.py`'s post-cleanup settings flush).
- **Discovered by:** A

### 3. Clean areas

- **Per-thread connections, `check_same_thread` respected.** `_get_connection` (L179-201) keeps the
  connection in an **instance-level** `threading.local()` (correctly not a class attribute) and never
  passes `check_same_thread=False`, so a connection is only ever used by the thread that opened it.
  `core/proxy.py:469-487` calls `close_thread_connection()` from the per-request `finish()`, so the
  proxy's thread-per-request connections are released instead of accumulating (each holds an 8 MB
  page cache).
- **WAL is load-bearing and actually on.** `PRAGMA journal_mode=WAL` (L185), `synchronous=NORMAL`,
  `temp_store=MEMORY`, `cache_size=-8000`, `busy_timeout=30000`, **`foreign_keys=ON`** (L191).
  Verified on both the main thread and a worker thread: `journal_mode=wal`, `foreign_keys=1`.
  Because the pragma runs on a brand-new connection (no transaction open), `foreign_keys=ON` is not
  silently a no-op — the `ON DELETE CASCADE` declarations really fire (verified: deleting a track
  removes its `history` rows).
- **The dup-cleanup merge is atomic and snapshot-first.** Plan (read-only, L594) → snapshot
  (`VACUUM INTO` + `tracks_backup`, L595/L759-796) → **one** transaction (`with conn:` L596-624)
  containing the merge, the version record and the legacy flag. A failure is caught, logged at ERROR
  and rolled back (L625-631); the next start retries. The flag is written **inside** the transaction
  (L621-624), so it can only become `'2'` after a successful commit.
- **No history row or playlist entry is lost by the merge.** Verified: 3 duplicates with 3 history
  rows and 3 playlist entries merged into 1 survivor → all 3 history rows re-pointed to the survivor,
  the 3 playlist entries collapsed to 1, `track_merges` and `history_track_remap` recorded
  (`repro_wn12_c.py` PROBE D). The old "strip the entry of a *surviving* track" statement is gone —
  `_remove_exact_duplicate_playlist_entries` (L968-985) only removes a redundant second entry for
  the *same* `(playlist_id, track_id)` pair.
- **The merge key is conservative.** `TRACK_RECORDING_COLUMNS` (L88) requires agreement on
  title/artist/album/source/source_id/file_path, and `name_is_meaningful` (L109-121) excludes
  placeholder names — so two genuinely different recordings (different album / provider id / file /
  spelling / unknown artist) are never collapsed, and the creation path and the migration share the
  one identity expression `TRACK_IDENTITY_SQL` (L82).
- **`add_track` is race-safe inside the process.** The `_write_lock` (RLock) serialises the
  check-then-insert; two concurrent `add_track` calls for the same title/artist returned the **same**
  id and produced **one** row (`repro_wn12.py` PROBE H). The dedup key is `(source, source_id)` for
  remote sources and `file_path` for local ones, plus the shared `TRACK_IDENTITY_SQL` fallback.
- **SQL-injection surface is closed.** `update_track` writes only whitelisted columns
  (L22-50, L1498-1503), `get_all_tracks` only whitelisted ORDER BY expressions (L55-70, L1192-1198),
  and `_like_pattern` (L1349-1364) escapes `%`/`_`/`\` with the matching `ESCAPE '\'` clause.
- **Aggregates never return `None`.** `get_history` (L1599-1624), `get_wrapped_stats`
  (L1723-1834) and `get_analytics_summary` (L1836-1860) wrap every `SUM` in `COALESCE(..., 0)` and
  every `COUNT` in `COUNT(id)`, so an empty library yields zeros and empty lists, never `None`.
  `get_wrapped_stats` on an empty DB returns `total_plays=0, total_seconds=0.0` and a seven-entry
  `daily_activity` with zeros.
- **Date arithmetic is timezone-consistent.** `CURRENT_TIMESTAMP` (UTC) is compared with
  `datetime('now', '-N days')` (UTC) — no local-time mismatch. (The weekday grouping uses the UTC
  weekday; a user in UTC+3 can see a play attributed to the previous day — cosmetic only.)
- **`cleanup_expired_cache` never orphans a file.** It deletes only rows whose `cached_file_path` is
  empty (L2234-2238); the downloaded-file rows are intentionally kept (`expires_at = NULL`,
  L2141-2145). The audio files themselves are purged by `utils/cache_manager.py:221-270` (WN-27),
  so there is no dangling-file leak.
- **`close()` is idempotent** and never raises (`repro_wn12.py` PROBE 2: a second `close()` is a
  no-op).
- **Caller misuse spotted and attributed elsewhere:** `core/downloader.py:278/572/776/833/855/876`
  execute raw `UPDATE download_queue` statements, but each one is inside `with self._core.db.conn:`,
  so the transactions do commit — no defect there. The one genuine caller-side defect found while
  tracing is in F-WN-12-5 (`core/downloader.py:818-827`, area WN-13).

### 4. Coverage gaps

- The real `~/.nedotify/` library, its `-wal`/`-shm` files and the Windows filesystem behaviour were
  **not** touched, as required. Every probe used throwaway SQLite files under `%TEMP%\opencode`.
- The **reachability** of a 3+ member partition (F-WN-12-1) was not measured on a live user
  library. Git history shows `file_path TEXT UNIQUE` was present in the very first commit of
  `core/database.py` (`b6a6553`), so a *current* database can only produce such a partition through
  rows with `file_path IS NULL` or through a pre-UNIQUE legacy database (which the code itself
  acknowledges at L357-360). The defect is proven at runtime; only its real-world frequency is
  unmeasured.
- The 30-second WAL-checkpoint block (F-WN-12-3) was reproduced with a second connection holding a
  read transaction. I did **not** reproduce it against the real proxy under load, so the probability
  of the overlap at shutdown is unmeasured.
- The UI behaviour for a `paused` download row (F-WN-12-6) was not traced — whether the downloads
  view offers an explicit "resume" that the user would find is area WN-32.
- The `settings`-schema gap (F-WN-12-7) is **not** reachable through this repository's history; I
  did not test databases produced by other forks or by the Android product's export.
- I did not audit `utils/cache_manager.py`, `core/download_store.py` (WN-13) or `core/settings.py`
  (WN-14) beyond the call sites needed to judge the DB contract; defects found there are attributed
  to those areas.
- The `download_queue` extra columns (`resume_on_restart`, `downloaded_bytes`, `total_bytes`,
  `error`, `attempt`) are added by `core/download_store.py:12-19` *after* the DB creates the table;
  the ordering is correct today, but it is a cross-area coupling I did not verify under a
  concurrent-startup race.
