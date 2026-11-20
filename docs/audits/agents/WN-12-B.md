## AREA WN-12 — SQLite persistence layer — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/database.py` — read in FULL, 2489 physical lines:
  - L1–146 module header, `TRACKS_UPDATABLE_COLUMNS`, `ALLOWED_TRACK_ORDER_BY`, `TRACK_IDENTITY_SQL`, `TRACK_RECORDING_COLUMNS`, `DUP_CARRY_OVER_COLUMNS`, `PLACEHOLDER_TRACK_NAMES`, `name_is_meaningful`, `_is_empty_value`, `_latest_timestamp`
  - L146–206 `__init__`, `get`, `_get_connection` (thread-local + pragmas), `conn` property
  - L207–523 `_init_database` (schema, indexes, ALTERs, FTS5 + triggers, migration invocation)
  - L524–653 `_run_dup_cleanup_migration`
  - L655–719 `_run_dup_cleanup_restore`
  - L721–757 `_ensure_migration_tables`
  - L759–796 `_snapshot_before_dup_cleanup`
  - L798–846 `_plan_track_merges`
  - L848–869 `_apply_track_merges`
  - L871–966 `_merge_track_row_into`
  - L968–985 `_remove_exact_duplicate_playlist_entries`
  - L987–1052 `_restore_merged_tracks`
  - L1054–1553 tracks: `add_track`, `get_track*`, `get_all_tracks`, counts, favourites, `toggle_favorite`, `ensure_track_exists`, `mark_track_downloaded`, `log_listening_history`, `update_track_play`, `_like_pattern`, `search_tracks`, `search_artists`, `search_albums`, `search_playlists`, `get_album_tracks`, `delete_track`, `update_track`, `update_track_metadata`
  - L1555–1861 history/listening: `begin_listening_session`, `get_recommendation_quality`, `update_history_duration`, `get_history`, `get_tracks_missing_cover`, `set_track_cover`, `backfill_track_metadata`, `get_most_played`, `get_top_artists`, `get_wrapped_stats`, `get_analytics_summary`
  - L1862–2028 playlists: `create_playlist`, `create_playlist_ex`, `_cleanup_duplicate_empty_system_playlists`, `get_playlists`, `add_to_playlist`, `add_tracks_to_playlist`, `get_playlist_tracks`, `delete_playlist`
  - L2029–2133 settings: `_serialize_setting`, `set_setting`, `set_settings_batch`, `get_setting`, `get_settings_by_category`, `get_all_settings`
  - L2134–2243 stream cache: `set_cached_file`, `get_cached_stream`, `cache_stream`, `update_cached_stream_url`, `invalidate_cached_stream`, `cleanup_expired_cache`
  - L2244–2283 scan folders / listening time
  - L2284–2412 download queue: `ensure_download_queue_table`, `download_queue_add`, `download_queue_set_status`, `download_queue_set_downloading`, `download_queue_get_status`, `download_queue_cancel_pending`, `download_queue_get_pending`
  - L2413–2489 lifecycle: `close_thread_connection`, `_checkpoint_wal`, `close`

**Callers traced into other areas** (read, not owned by WN-12)

- `core/api.py` — L2267–2271 (`get_library` → `get_all_tracks()`), L2370–2414 (playlist import → `create_playlist_ex` / `delete_playlist`), L2498–2530 (playlist CRUD), L2620–2731 (favourites / auto-download), L3192–3260 (cover backfill), L3290–3400 (profile stats), L3420–3434 (`create_local_playlist`), L3876–3908 (`delete_duplicate_track`), L4129–4209 (offline / smart playlists)
- `core/app.py` — L173–185 (`cleanup_expired_cache` every 10 min, dedicated `CacheCleanup` thread), L508–560 (`cleanup()` → `db.close()`)
- `core/proxy.py` — L460–489 (`finish()` → `close_thread_connection()`), L797–810, L1207–1214 (`set_cached_file`)
- `core/settings.py` — L315–342 (`_load_all` → `get_all_settings`), L443–506 (`flush` → `set_settings_batch` / `set_setting`), L520–530 (`SettingsWriter` thread)
- `core/downloader.py` — L274–370, L490–495, L564–576, L739–876 (writes through `db._write_lock` + `db.conn` directly)
- `core/offline.py` — L56–77 (`get_all_tracks()` no limit)
- `utils/cache_manager.py` — L252–271 (DB sync after file purge), L289–395 (`set_cached_file`)
- `utils/file_scanner.py` — L115–152 (`db.conn.execute` + `db.conn.commit()` outside the write lock)
- `services/audio_fingerprint_service.py` — L65–133 (`get_all_tracks(source="local")`, `delete_duplicate_track`)
- `services/smart_playlists.py` — L79–177 (`db.conn`, `db._write_lock`)
- `services/taste_profile.py` — L526 (`return db.conn` — hands the raw connection to callers)
- `services/lufs_scanner.py` — L62–106 (`db.conn.execute` + `db.conn.commit()` outside the write lock)
- `services/listening_comparison.py` — L29–67 (raw `db.conn.execute` queries)
- `ui/web_new_v2/js/profile.js` L179, `js/library-view.js` L37/L139, `js/library.js` L503, `js/artist_profile.js` L190–192 — the UI consumers
- `tests/test_dup_cleanup_migration.py`, `tests/test_db_integrity.py` — to establish what is already pinned

**Runtime verification** (throwaway SQLite files under `%TEMP%`, the real `~/.nedotify/` was never opened; interpreter `.venv_win\Scripts\python.exe`, Python 3.14.7 / SQLite 3.50.4):
probe scripts `_wn12_probe1..7.py` in `%TEMP%\opencode\audit_reports\` (scratch, outside the repo).

---

### 2. Findings

#### F-WN-12-1  [P2] — The dup-cleanup "corrective" restore can never undo a merge performed by this build; the safety net is inert
- **File:** `core/database.py:1001-1005` (+ `core/database.py:961-965`, `core/database.py:655-663`)
- **Confirmed:** yes
- **Description:** `_restore_merged_tracks` selects its candidates with `WHERE merged_by <> ?` bound to `self.DUP_CLEANUP_VERSION`. The only merge implementation in the tree writes `merged_by = self.DUP_CLEANUP_VERSION` into `track_merges`. Therefore, for any library merged by this build, the candidate set is always empty, `restored` is 0, and the corrective migration logs "nothing to restore - this library was never damaged". The `tracks_backup` table and the dated `VACUUM INTO` copy exist but no shipped code path can use them to undo a merge this build performed. The existing test can only exercise the restore by *faking* an older version.
- **Cause:** the restore filter was written for "a PREVIOUS merge migration" and never reconciled with the fact that the current build is itself the merge author. The version check is one-directional.
- **Trigger conditions:** the merge retired a row and the user (or a future migration) wants it back — e.g. a false-positive merge, or a user who wants the duplicate track back.
- **User impact:** the merge is irreversible through the app. The only recovery is manually replacing `~/.nedotify/nedotify_storage.db` with the dated `<db>.dup-cleanup-<ts>.db` copy — an undocumented, all-or-nothing procedure that also discards everything the user did after the snapshot. The docstring at L540–543 and the remediation tracker both advertise a recoverable snapshot; no code delivers it.
- **Evidence:**
  ```python
  # core/database.py:1001-1005
  cursor.execute(
      "SELECT duplicate_id, survivor_id FROM track_merges "
      "WHERE merged_by <> ? AND duplicate_id NOT IN (SELECT id FROM tracks)",
      (self.DUP_CLEANUP_VERSION,),
  )
  ```
  ```python
  # core/database.py:961-965  (the merge writes exactly that version)
  cursor.execute(
      "INSERT OR REPLACE INTO track_merges (duplicate_id, survivor_id, merged_by, merged_at) "
      "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
      (duplicate_id, survivor_id, self.DUP_CLEANUP_VERSION),
  )
  ```
  ```python
  # tests/test_dup_cleanup_migration.py:602  (the test must fake an older version)
  db.conn.execute("UPDATE track_merges SET merged_by = 'dup_cleanup_v1'")
  ```
- **Reproduction / verification:** open a throwaway DB, let the migration merge a duplicate pair, then `DELETE FROM schema_migrations WHERE version = 'dup_cleanup_restore_v1'` and re-open. The log says `Dup cleanup restore: nothing to restore - this library was never damaged by the legacy cleanup.` although a row was retired one second earlier. `SELECT * FROM track_merges` still shows `merged_by = 'dup_cleanup_v2'`.
- **Suggested fix:** make the restore able to undo the current version too (e.g. a dedicated, explicitly-invoked "undo merge" path keyed on `track_merges`), or drop the `merged_by <> current` filter and expose a documented restore entry point. At minimum, correct the docstring/tracker claim so the snapshot is not advertised as recoverable when it is not.
- **Fix side effects:** allowing the restore to re-insert a retired row re-introduces the duplicate the merge removed, and `INSERT OR IGNORE` (L1026) will silently skip any row whose `file_path` collides with the survivor's `UNIQUE(file_path)` — so a naive fix silently half-works.
- **Discovered by:** B

#### F-WN-12-2  [P2] — `_cleanup_duplicate_empty_system_playlists` silently deletes a USER playlist named "Локальные" / "Локальные треки"
- **File:** `core/database.py:1908-1924` (+ `core/database.py:1876-1890`, `ui/web_new_v2/js/profile.js:179`)
- **Confirmed:** yes
- **Description:** the cleanup identifies a "system" playlist purely by its *name* — there is no `is_system`/`origin` column on `playlists`. The row it deletes is any playlist with that name that is empty and is not the `MIN(id)` for that name. "Локальные" is exactly the name the **user** creates from the profile page (`api.create_local_playlist('Локальные')`). The cleanup runs inside every `create_playlist_ex`, i.e. on every playlist creation and every playlist import. The deletion is not logged and the return value is discarded, so the playlist disappears from the UI with no notice and no undo.
- **Cause:** housekeeping was keyed on a user-visible label instead of on provenance, and the "keep the oldest" rule does not distinguish the app's row from the user's row.
- **Trigger conditions:** two playlists with the same name exist (e.g. the user created "Локальные" and a playlist import produced another one, or the user renamed/created a second one) and the newer one is empty. Then *any* subsequent playlist creation silently deletes the user's empty playlist.
- **User impact:** the user's playlist row is deleted from `~/.nedotify/nedotify_storage.db`. Because `playlist_tracks` rows are `ON DELETE CASCADE`, an empty-at-the-moment playlist is harmless — but the moment it is deleted the UI no longer lists it, and the user has no way to know it existed.
- **Evidence:**
  ```python
  # core/database.py:1908-1917
  sql = """
      DELETE FROM playlists
      WHERE name IN ('Локальные', 'Локальные треки')
      AND id NOT IN (SELECT DISTINCT playlist_id FROM playlist_tracks)
      AND id NOT IN (
          SELECT MIN(id) FROM playlists
          WHERE name IN ('Локальные', 'Локальные треки')
          GROUP BY name
      )
  """
  ```
  ```python
  # core/database.py:1882 (runs on EVERY create_playlist_ex)
  self._cleanup_duplicate_empty_system_playlists(cursor)
  ```
- **Reproduction / verification:** throwaway DB → insert two `playlists` rows named "Локальные" (ids 1 and 2) → `db.create_playlist("Новый плейлист")` → `SELECT id,name FROM playlists` returns ids 1, 3 — **row id 2 was deleted by an unrelated playlist creation**. Reproduced in `_wn12_probe2.py`.
- **Suggested fix:** add an explicit provenance column (`origin` / `is_system`) set by the code path that owns the system playlist, and restrict the cleanup to rows with that flag; log every deletion at INFO with the playlist name and id.
- **Fix side effects:** existing libraries have no such column — the flag would have to be back-filled (by name) or the cleanup retired, which re-opens the duplicate-row cosmetic issue it was written for.
- **Discovered by:** B

#### F-WN-12-3  [P2] — `get_library()` ships the entire tracks table to the WebView on every library render (no limit, `SELECT *`)
- **File:** `core/database.py:1184-1209` (+ `core/api.py:2267-2271`, `core/offline.py:77`, `core/api.py:3423`)
- **Confirmed:** yes
- **Description:** `get_all_tracks()` defaults to `limit=None` and selects `*`, including the `metadata_json` blob column. `AppApi.get_library()` calls it with no limit and hands the result to the pywebview bridge. The library view, the artist profile and the offline library all call `get_library()` on every render, so the whole library is materialised as Python dicts, JSON-serialised and pushed into the WebView each time.
- **Cause:** the read API has no pagination/projection contract; the only knob (`limit`/`offset`) is used by exactly one caller (`core/services/recommendation.py:194`, `limit=200`).
- **Trigger conditions:** a library of a few thousand tracks — the normal case for a music player.
- **User impact:** multi-megabyte JSON payloads over the WebView2 IPC bridge on every library/profile render → visible UI stall, a large transient memory spike in both the Python and the WebView process, and O(N) work per render that grows with the library.
- **Evidence:**
  ```python
  # core/database.py:1199-1209
  sql = "SELECT * FROM tracks"
  ...
  if limit:
      sql += " LIMIT ? OFFSET ?"
  cursor.execute(sql, params)
  return [dict(row) for row in cursor.fetchall()]
  ```
  ```python
  # core/api.py:2267-2271
  def get_library(self):
      """Get all tracks in local library."""
      if is_offline(self._core.settings):
          return offline_library(self._core.db)
      return self._core.db.get_all_tracks()
  ```
- **Reproduction / verification:** 4000 tracks with a 200-byte `metadata_json` → `db.get_all_tracks()` returns 4000 dicts in ~20 ms and `json.dumps(rows)` is **3.0 MB** (`_wn12_probe5.py`). `get_playlist_tracks(1)` on the same fixture: 3000 rows / 22.9 ms, dominated by `dict(row)` conversion of the 28-column `tracks` row.
- **Suggested fix:** give the read layer an explicit projection (only the columns the library view uses) and a paginated API; make `get_library()` request a page instead of the whole table.
- **Fix side effects:** the UI currently relies on the full row (it is not paged); changing the payload shape touches WN-06 / WN-32.
- **Discovered by:** B

#### F-WN-12-4  [P2] — `_all_conns` never evicts connections whose owning thread died: one leaked SQLite handle per short-lived DB-touching thread
- **File:** `core/database.py:179-201` (+ `core/database.py:2413-2438`, `core/database.py:2459-2489`)
- **Confirmed:** yes
- **Description:** `_get_connection` registers every connection it opens in the instance-wide set `self._all_conns` (L199-200). The set holds a **strong reference**, so a connection whose thread has died is never garbage-collected and never closed. The only removal path is `close_thread_connection()`, which must be called *by the owning thread* before it exits. Every thread in the app that touches the DB and does not call it leaks one connection (one sqlite3 handle + the `.db`/`-wal`/`-shm` file handles + the 8 MB page-cache budget the proxy's own comment cites at `core/proxy.py:471-475`).
- **Cause:** the registry has no liveness check (no thread-id → connection map) and no weak references; dead threads cannot be detected.
- **Trigger conditions:** any per-item or per-request thread that touches the DB. Today the proxy is well-behaved (`core/proxy.py:477-486` calls `close_thread_connection()` in `finish()`), and the pools are bounded (`core/api.py:363` 6 search workers, `core/api.py:369` 2 prefetch workers, `core/downloader.py:58` fixed pool, `services/lufs_scanner.py:44` 1 worker), so the leak is currently bounded — but the pattern is one line away from being unbounded (`core/api.py:3224` already spawns a fresh `Lyrics-<n>` thread per lyrics request).
- **User impact:** file-handle growth and growing memory over a long session; at shutdown `close()` then fails to close every one of them, so the "N connections could not be closed" warning (see F-WN-12-10) grows with the leak.
- **Evidence:**
  ```python
  # core/database.py:198-200
  self._local.connection = conn
  with self._conns_lock:
      self._all_conns.add(conn)
  ```
  ```python
  # core/database.py:2424-2438  (only path that removes one)
  existing = getattr(self._local, "connection", None)
  ...
  with self._conns_lock:
      self._all_conns.discard(existing)
  ```
- **Reproduction / verification:** 50 short-lived threads each doing one `db.get_tracks_count()` → `len(db._all_conns)` grows from **1 to 51** after `gc.collect()`; the same 50 threads calling `db.close_thread_connection()` before exiting leave it at 51 (no further growth). Reproduced in `_wn12_probe7.py`.
- **Suggested fix:** track connections in a `threading.local`-per-thread registry with the owning thread id, and evict entries whose thread is no longer alive (or use `weakref.finalize` on the thread-local slot); make `close_thread_connection()` the documented contract and call it from every DB-touching worker.
- **Fix side effects:** a finalizer-based eviction can close a connection that a dying thread was still using — the eviction must be restricted to threads that are provably finished.
- **Discovered by:** B

#### F-WN-12-5  [P2] — `get_history()` scans the whole tracks table and the whole history table to return 50 rows
- **File:** `core/database.py:1599-1624`
- **Confirmed:** yes
- **Description:** the query groups the join by `t.id` and then sorts by `MAX(h.played_at)`. SQLite's plan is `SCAN t` → `SEARCH h USING INDEX idx_history_track_id (track_id=?)` → `USE TEMP B-TREE FOR ORDER BY`: every track row is visited and every history row is visited, and the LIMIT is applied only at the very end. The `history` table grows without bound (one row per play, never pruned anywhere in the codebase), so this cost grows with the lifetime of the install.
- **Cause:** the "one row per track" collapse is implemented as a post-join GROUP BY over the full join, instead of "take the N most recent history rows first, then collapse".
- **Trigger conditions:** any profile/home render (`core/api.py:3295`, `:3323`, `:3396`, `:3742`, `:3784` — `get_history(limit=10..30)`).
- **User impact:** the "recently played" panel gets slower the longer the app is used, on every render.
- **Evidence:**
  ```python
  # core/database.py:1608-1623
  cursor.execute(
      """
      SELECT t.id AS track_id, MAX(h.played_at) AS played_at, COUNT(*) AS play_count, ...
      FROM history h
      JOIN tracks t ON h.track_id = t.id
      GROUP BY t.id
      ORDER BY played_at DESC
      LIMIT ?
  """, (limit,))
  ```
- **Reproduction / verification:** `EXPLAIN QUERY PLAN` on a 3000-track / 6000-history fixture prints `SCAN t` + `SEARCH h USING INDEX idx_history_track_id` + `USE TEMP B-TREE FOR ORDER BY` (`_wn12_probe3.py`).
- **Suggested fix:** select the N most recent `history` rows first (`ORDER BY played_at DESC LIMIT N` over `history` using `idx_history_played_at`) and collapse only those; add a covering index `history(track_id, played_at)`.
- **Fix side effects:** collapsing only the newest N history rows changes the `play_count`/`duration_listened` figures shown for tracks whose plays fall outside the window.
- **Discovered by:** B

#### F-WN-12-6  [P2] — `get_wrapped_stats()` runs four independent full scans of the history table
- **File:** `core/database.py:1723-1834` (queries at L1736, L1753, L1772, L1792)
- **Confirmed:** yes
- **Description:** the method computes totals, top tracks, top artists and day-of-week activity in four separate statements, each of which scans `history` and groups it. For `period="all"` there is no `WHERE` clause at all, so the entire history table is scanned four times per call. `ui/web_new_v2/js/profile.js:135` calls `get_wrapped_stats('all')` on every profile render, together with `get_profile_stats` and `get_playlists` in the same `Promise.allSettled`.
- **Cause:** four report sections are computed independently instead of from one pass over the data.
- **Trigger conditions:** any profile render on a library with a long history.
- **User impact:** the profile screen does 4× the necessary I/O; with the unbounded `history` table this is the slowest read in the app.
- **Evidence:**
  ```python
  # core/database.py:1736-1746  (query 1 of 4, all with the same FROM/JOIN shape)
  query_totals = f"""
      SELECT COUNT(h.id) as total_plays,
             COALESCE(SUM(CASE ... END), 0) as total_sec
      FROM history h
      LEFT JOIN tracks t ON h.track_id = t.id
      {where_clause}
  """
  ```
- **Reproduction / verification:** `conn.set_trace_callback` around `db.get_wrapped_stats("week")` records exactly **4 statements**, each a full `FROM history h ... JOIN tracks t` scan (`_wn12_probe5.py`).
- **Suggested fix:** compute the four sections from a single CTE/pass (e.g. one scan into per-track aggregates plus a per-day aggregate), or cache the result per period with a short TTL.
- **Fix side effects:** the "top artists" query groups by `LOWER(t.artist)` while the totals do not — unifying the pass must preserve that case-folding.
- **Discovered by:** B

#### F-WN-12-7  [P2] — `search_playlists()` is an N+1: one extra COUNT query per returned playlist
- **File:** `core/database.py:1445-1468` (the N+1 is at L1465)
- **Confirmed:** yes
- **Description:** the method selects the playlists and then, inside the list comprehension, calls `self.get_playlist_track_count(r["id"])` for every row — a separate `SELECT COUNT(*)` per playlist. `get_playlists()` (L1931-1943) already solves the same problem with a single `LEFT JOIN ... GROUP BY`. The search path is called on every keystroke of the search box (`core/api.py:2146`).
- **Cause:** the track count was added to the projection after the query was written, instead of being folded into it.
- **Trigger conditions:** any playlist search.
- **User impact:** up to `limit + 1` queries (51 by default) per keystroke instead of 1 — visible input latency on a slow disk / large DB.
- **Evidence:**
  ```python
  # core/database.py:1462-1467
  "cover_url": dict(r).get("cover_url") or dict(r).get("cover_path") or "",
  "track_count": self.get_playlist_track_count(r["id"]) if hasattr(self, "get_playlist_track_count") else 0,
  ```
  ```python
  # core/database.py:1439-1443
  def get_playlist_track_count(self, playlist_id: int) -> int:
      cursor = self.conn.cursor()
      cursor.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?", (int(playlist_id),))
  ```
- **Reproduction / verification:** monkey-patch `get_playlist_track_count` with a counting wrapper; `db.search_playlists("P", limit=50)` over 6 playlists issues **6** extra COUNT queries (`_wn12_probe2.py`).
- **Suggested fix:** reuse the `get_playlists()` shape — one `LEFT JOIN playlist_tracks ... GROUP BY p.id` — and drop the per-row call.
- **Fix side effects:** the `search_playlists` result is also consumed as a "remote playlist" shape (`title`/`author`/`type`), so the join must not change the returned keys.
- **Discovered by:** B

#### F-WN-12-8  [P2] — No index supports the hot album/artist lookups: `get_album_tracks`, `search_albums` and `get_tracks_missing_cover` full-scan the tracks table
- **File:** `core/database.py:1470-1482`, `core/database.py:1422-1437`, `core/database.py:1626-1655` (index list at `core/database.py:350-368`)
- **Confirmed:** yes
- **Description:** the index set covers `source`, `is_favorite`, `artist` (exact), `file_path`, `(source, source_id)`, `added_at DESC`, `(play_count DESC, last_played DESC)` and `is_downloaded` — but nothing for `LOWER(album)`, `LOWER(artist)` or the missing-cover predicate. `get_album_tracks` filters on `LOWER(album) = LOWER(?)` → `SCAN tracks`. `search_albums` groups by `LOWER(album), LOWER(artist)` → `SCAN tracks`. `get_tracks_missing_cover` filters on a disjunction of five conditions → `SCAN tracks`; it is the periodic cover backfill (`core/api.py:3227-3236`).
- **Cause:** the indexes were created for the exact-match access paths of `add_track`/`get_track_by_*`, not for the read-side case-folding the queries actually use.
- **Trigger conditions:** opening an album view, an album search, or the periodic cover backfill on a large library.
- **User impact:** three full table scans per album/session on a library of tens of thousands of tracks.
- **Evidence:**
  ```python
  # core/database.py:1472-1476
  cursor.execute(
      "SELECT * FROM tracks WHERE LOWER(album) = LOWER(?) AND (LOWER(artist) = LOWER(?) OR artist = 'Unknown Artist') ORDER BY track_number ASC, title ASC",
      (album_title, artist)
  )
  ```
  ```python
  # core/database.py:352  (only the exact-match artist index exists)
  cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
  ```
- **Reproduction / verification:** `EXPLAIN QUERY PLAN` prints `SCAN tracks` for `LOWER(album) = LOWER(?)` and for the missing-cover predicate (`_wn12_probe3.py`). `get_album_tracks('Album3')` over 3000 tracks = 150 rows / 1.29 ms; the scan grows linearly.
- **Suggested fix:** add expression indexes `tracks(LOWER(album))` and `tracks(LOWER(artist))`, plus a partial index for the missing-cover predicate; alternatively normalise the case at write time.
- **Fix side effects:** expression indexes must be created by a new idempotent `CREATE INDEX IF NOT EXISTS` in `_init_database`; they add write cost on every `tracks` insert/update.
- **Discovered by:** B

#### F-WN-12-9  [P2] — `download_queue` has no foreign key to `tracks`: `delete_track` leaves a dangling queue row behind
- **File:** `core/database.py:2293-2302` (DDL) + `core/database.py:1484-1489` (`delete_track`)
- **Confirmed:** yes
- **Description:** `download_queue.track_id INTEGER NOT NULL` is declared without a `FOREIGN KEY`, unlike `playlist_tracks` and `history`, which both reference `tracks(id) ON DELETE CASCADE`. `delete_track` deletes only the `tracks` row, so a `download_queue` row for the deleted track survives with a `track_id` that points at nothing. `stream_cache` has the same problem (it is keyed by `source`/`source_id`, so a deleted track leaves a `cached_file_path` row behind).
- **Cause:** the two tables were added at different times by different code paths (`ensure_download_queue_table` is also called by `core/downloader.py:291`), and only the later ones were given FK constraints.
- **Trigger conditions:** deleting a track that is (or was) queued for download — the "remove duplicate" flow (`core/api.py:3884` → `services/audio_fingerprint_service.py:130` → `db.delete_track`) or any future delete path.
- **User impact:** the downloader picks the orphaned row up (`download_queue_get_pending` returns `track_id, source, source_id`), downloads the file and calls `mark_track_downloaded` (`core/database.py:1278-1282`), which updates **0 rows** — the file lands in `~/.nedotify/downloads` with no row pointing at it (orphan file) while the UI reports the download as successful. The write-side consequence belongs to WN-13; the missing constraint belongs to WN-12.
- **Evidence:**
  ```python
  # core/database.py:2293-2302
  ddl = """
      CREATE TABLE IF NOT EXISTS download_queue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          track_id INTEGER NOT NULL,
          source TEXT,
          source_id TEXT,
          status TEXT DEFAULT 'pending',
          added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
  """
  ```
  ```python
  # core/database.py:1484-1489
  def delete_track(self, track_id: int) -> bool:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
              return cursor.rowcount > 0
  ```
- **Reproduction / verification:** insert a track + a `download_queue` row, `delete_track(1)`, commit → `PRAGMA foreign_key_list(download_queue)` returns `[]` and the queue row `{id:1, track_id:1, ...}` is still there while the track is gone (`_wn12_probe6.py`).
- **Suggested fix:** add `FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE` (requires the 12-step table rebuild for existing databases) or delete the matching `download_queue` rows inside `delete_track`.
- **Fix side effects:** the unique index `ux_download_queue_track` and the `download_queue_add` upsert (`core/database.py:2347-2352`) assume one row per track; a cascade delete interacts correctly with it, but the rebuild must preserve both the index and the existing rows.
- **Discovered by:** B

#### F-WN-12-10  [P3] — `close()` can never close the connections owned by other threads; the WAL checkpoint result is discarded; every shutdown logs a spurious WARNING
- **File:** `core/database.py:2459-2489` (+ `core/database.py:2440-2457`, `core/database.py:2413-2438`)
- **Confirmed:** yes
- **Description:** three separate issues in the shutdown path:
  1. `close()` iterates `self._all_conns` and calls `conn.close()`. sqlite3 refuses to close a connection from a thread that did not create it, so **every** non-main-thread connection raises `sqlite3.ProgrammingError` and is only counted, not closed. The connections are released by the OS when their thread exits — i.e. at process exit, not at `close()`.
  2. `_checkpoint_wal()` executes `PRAGMA wal_checkpoint(TRUNCATE)` and **ignores the returned `(busy, log, checkpointed)` triple**, so a busy checkpoint (another connection mid-read) is silent and the `-wal` file is left large.
  3. `close()` calls `self._checkpoint_wal()` *before* `close_thread_connection()`; `_checkpoint_wal` goes through the `conn` property, so on a thread that never touched the DB it **opens a brand-new connection** just to checkpoint and close it.
- **Cause:** the thread-local connection model is incompatible with "close everything from one place"; the shutdown contract was never pushed down to the subsystems that own the connections.
- **Trigger conditions:** every application shutdown.
- **User impact:** `~/.nedotify/logs/app.log` gets a `WARNING: N database connection(s) could not be closed from the main thread` line on every exit, where N is the number of live worker connections (CacheCleanup, SettingsWriter, downloader pool + processor, watchdog, LUFS scanner, search/prefetch pools). The user's `-wal` file may be left un-truncated when the checkpoint is busy. The connections themselves are released at process exit, so there is no lasting corruption — the defect is the noise, the ignored checkpoint status and the missing deterministic release.
- **Evidence:**
  ```python
  # core/database.py:2454-2457
  try:
      self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
  except sqlite3.Error as e:
      logger.warning("WAL checkpoint failed: %s", e)
  ```
  ```python
  # core/database.py:2474-2489
  with self._conns_lock:
      for conn in list(self._all_conns):
          try:
              conn.close()
          except Exception as e:
              failed += 1
              ...
  ```
- **Reproduction / verification:** create a connection in a worker thread, then call `conn.close()` from the main thread → `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.` The `db.close()` path then logs `1 database connection(s) could not be closed from the main thread (created on another thread)` (`_wn12_probe2.py`, `_wn12_probe4.py`). Positive control: with no other thread holding a connection, `db.close()` truncates the `-wal` to 0 bytes.
- **Suggested fix:** give each subsystem an explicit "release my DB connection" hook and call it from `AppCore.cleanup()` before `db.close()`; read the checkpoint triple and log a warning when `busy != 0`; avoid opening a connection inside `_checkpoint_wal` (use the existing thread-local handle if there is one).
- **Fix side effects:** the checkpoint must run after the last reader has gone, otherwise it stays busy; ordering the cleanup steps is a WN-02 concern.
- **Discovered by:** B

#### F-WN-12-11  [P3] — `tracks_backup` is a one-shot `CREATE TABLE IF NOT EXISTS` and is never refreshed, so a re-run of the merge would restore from a stale snapshot
- **File:** `core/database.py:791-794` (+ `core/database.py:759-796`, `core/database.py:511-512`)
- **Confirmed:** yes (latent — the trigger is a future version bump)
- **Description:** the byte-level copy (`VACUUM INTO`, L782-789) is refreshed on every run because the file name carries a timestamp. The `tracks_backup` table is not: `CREATE TABLE IF NOT EXISTS tracks_backup AS SELECT * FROM tracks` is a no-op once the table exists, so it keeps the content from the *first* time it was created. The docstring states the one-shot guard is deliberate ("it is written once, so it cannot grow without bound"), and `DUP_CLEANUP_VERSION` is documented as the way to re-run the merge (L511-512).
- **Cause:** the "one-shot" guard is implemented on the snapshot artefact instead of on the migration version, so the two lifetimes diverge.
- **Trigger conditions:** `DUP_CLEANUP_VERSION` is bumped (the documented way to re-run the merge) on a library that already ran a previous version.
- **User impact:** the corrective migration would restore rows from the *old* snapshot — pre-merge `title`, `file_path`, `play_count`, `added_at` — and re-point history/playlist entries at a row whose current state has since changed (e.g. the user renamed the track, or the file was moved). A restore from stale data is worse than no restore.
- **Evidence:**
  ```python
  # core/database.py:791-794
  try:
      cursor.execute("CREATE TABLE IF NOT EXISTS tracks_backup AS SELECT * FROM tracks")
  except sqlite3.Error as exc:
      logger.error("Dup cleanup: the tracks_backup snapshot could not be created: %s", exc)
  ```
  ```python
  # core/database.py:511-512
  # The version of the merge migration. Bump it to re-run the merge.
  DUP_CLEANUP_VERSION = "dup_cleanup_v2"
  ```
- **Reproduction / verification:** run the migration on a fixture, then change a track's `title`, bump `DUP_CLEANUP_VERSION`, re-open → `tracks_backup` still holds the pre-change title, while the dated `.dup-cleanup-<ts>.db` file holds the current one. The two snapshots disagree.
- **Suggested fix:** version the backup table (`tracks_backup_v2`) or key the one-shot guard on the migration version, so the table is refreshed whenever the merge version changes.
- **Fix side effects:** refreshing `tracks_backup` on every version bump costs one full `SELECT *` copy of `tracks`; a stale backup is arguably safer than a large one — but it must be paired with the version key.
- **Discovered by:** B

#### F-WN-12-12  [P3] — The LIKE fallback in the search paths uses a leading wildcard and cannot use an index
- **File:** `core/database.py:1392-1404` (`search_tracks`), `core/database.py:1406-1420` (`search_artists`), `core/database.py:1422-1437` (`search_albums`)
- **Confirmed:** yes
- **Description:** `_like_pattern` wraps the query in `%...%`, so the pattern cannot use any index. `search_tracks` tries FTS5 first and only falls back to LIKE when FTS returns no rows or is unavailable — but `search_artists` and `search_albums` use the LIKE form unconditionally. The escaping itself is correct (see §3), so this is a performance issue only, not a correctness one.
- **Cause:** the LIKE fallback exists for FTS-unavailable databases and for FTS misses; the wildcard semantics were chosen for substring matching.
- **Trigger conditions:** a search that FTS cannot satisfy (a typo, a substring, a token FTS does not index), any artist search, any album search.
- **User impact:** full scan of `tracks` per keystroke. `EXPLAIN QUERY PLAN` for the LIKE fallback: `SCAN tracks USING INDEX idx_tracks_play_count` — the index is used only for the `ORDER BY play_count DESC`, every row is still visited.
- **Evidence:**
  ```python
  # core/database.py:1358-1364
  escaped = (
      str(query if query is not None else "")
      .replace("\\", "\\\\")
      .replace("%", "\\%")
      .replace("_", "\\_")
  )
  return f"%{escaped}%"
  ```
  ```python
  # core/database.py:1393-1403
  cursor.execute(
      """
      SELECT * FROM tracks
      WHERE title LIKE ? ESCAPE '\\'
         OR artist LIKE ? ESCAPE '\\'
         OR album LIKE ? ESCAPE '\\'
      ORDER BY play_count DESC
      LIMIT ?
  """, (like_query, like_query, like_query, limit))
  ```
- **Reproduction / verification:** `EXPLAIN QUERY PLAN` on the LIKE variant prints `SCAN tracks USING INDEX idx_tracks_play_count` (`_wn12_probe3.py`); `_wn12_probe5.py` shows the FTS path answering `search_tracks("Title1")` in 0.69 ms while the LIKE path is the fallback.
- **Suggested fix:** for the artist/album paths use a prefix pattern (`escaped + "%"`) so `LOWER(artist)`/`LOWER(album)` expression indexes (F-WN-12-8) can be used, or route them through FTS as well.
- **Fix side effects:** prefix matching changes the result set for mid-word queries; the UI's expectations for artist/album search would change.
- **Discovered by:** B

#### F-WN-12-13  [P3] — The startup migration silently de-duplicates (playlist, track) pairs across ALL user playlists, without logging
- **File:** `core/database.py:968-985` (+ `core/database.py:602-605`)
- **Confirmed:** yes
- **Description:** `_remove_exact_duplicate_playlist_entries` deletes every `playlist_tracks` row that is not the `MIN(id)` of its `(playlist_id, track_id)` group — across every playlist, user-created ones included — and it runs even when the merge plan was empty (nothing was merged). The count is written into the migration's `details` JSON but is never surfaced to the user at INFO level (the INFO branch only mentions "same-title rows left in place").
- **Cause:** the statement was kept from the old destructive migration (re-scoped to the same (playlist, track) pair) but it is a global mutation of user data disguised as merge housekeeping.
- **Trigger conditions:** the user listed the same track twice in one playlist (the UI's "add to playlist" appends unconditionally — `add_to_playlist`, `core/database.py:1950-1970` — so a double click creates one).
- **User impact:** the second entry disappears the first time the migration runs (once per library). Cosmetic, but it is a silent mutation of user-curated data with no log line and no undo.
- **Evidence:**
  ```python
  # core/database.py:977-985
  cursor.execute(
      """
      DELETE FROM playlist_tracks
      WHERE id NOT IN (
          SELECT MIN(id) FROM playlist_tracks GROUP BY playlist_id, track_id
      )
  """)
  return max(cursor.rowcount, 0)
  ```
  ```python
  # core/database.py:602-605  (runs even when plan == [])
  stats["playlist_entries_removed"] = (
      0 if legacy_ran
      else self._remove_exact_duplicate_playlist_entries(cursor)
  )
  ```
- **Reproduction / verification:** insert the same `track_id` twice into one playlist, open the DB with a fresh `schema_migrations` table → the second `playlist_tracks` row is gone and the migration log does not mention it.
- **Suggested fix:** scope the de-duplication to the playlists actually touched by the merge, and log the number of removed entries at INFO.
- **Fix side effects:** scoping it to the merged playlists leaves the pre-existing duplicate entries elsewhere in place — which is the cosmetic problem the original statement was written for.
- **Discovered by:** B

#### F-WN-12-14  [P3] — Bare `except sqlite3.OperationalError: pass` around the schema `ALTER TABLE`s swallows real errors and can leave a permanently broken schema
- **File:** `core/database.py:370-378`, `core/database.py:477-495`, `core/database.py:487-491`
- **Confirmed:** yes
- **Description:** four migrations use a bare `except sqlite3.OperationalError: pass`:
  ```python
  try:
      cursor.execute("ALTER TABLE tracks ADD COLUMN is_downloaded INTEGER DEFAULT 0")
  except sqlite3.OperationalError:
      pass
  ```
  The same file's `history` ALTERs (L292-296) do it correctly — they re-raise anything that is not "duplicate column name". The bare form also swallows "database is locked", "disk I/O error" and "malformed database schema".
- **Cause:** the duplicate-column error was treated as the only expected outcome, so the handler could not distinguish it from a real failure.
- **Trigger conditions:** any `OperationalError` other than "duplicate column name" during startup — e.g. the busy timeout expiring on a contended DB, or a transient I/O error.
- **User impact:** the column is never added, and every later write that names it fails hard: `add_track`'s INSERT lists `is_downloaded` (`core/database.py:1136-1142`) → `sqlite3.OperationalError: no such column: is_downloaded` → **the library can no longer be written to at all**, with the root cause visible only as a swallowed exception at startup.
- **Evidence:**
  ```python
  # core/database.py:370-377  (bare except)
  try:
      cursor.execute("ALTER TABLE tracks ADD COLUMN is_downloaded INTEGER DEFAULT 0")
  except sqlite3.OperationalError:
      pass
  try:
      cursor.execute("ALTER TABLE playlists ADD COLUMN cover_url TEXT")
  except sqlite3.OperationalError:
      pass
  ```
  ```python
  # core/database.py:292-296  (the correct pattern, same file)
  try:
      cursor.execute(f'ALTER TABLE history ADD COLUMN {name} {definition}')
  except sqlite3.OperationalError as exc:
      if 'duplicate column name' not in str(exc).lower():
          raise
  ```
- **Reproduction / verification:** create a DB, drop the `is_downloaded` column, then execute `ALTER TABLE tracks ADD COLUMN is_downloaded INTEGER DEFAULT 0` against a read-only/locked handle — the `OperationalError` is swallowed and the column stays missing; the next `add_track` raises `no such column: is_downloaded`.
- **Suggested fix:** use the same "duplicate column name" filter used for `history`; log and re-raise anything else so a failed migration is visible at startup.
- **Fix side effects:** re-raising turns a previously silent degradation into a startup failure — which is the correct trade for a migration, but it needs the startup path (WN-01/WN-02) to tolerate a failed DB init.
- **Discovered by:** B

---

### 3. Clean areas

- **SQL injection surface — clean.** Every user-controlled value reaches SQLite as a bound parameter. The only two interpolated fragments are (a) the `ORDER BY` in `get_all_tracks`, which is validated against the `ALLOWED_TRACK_ORDER_BY` whitelist (`core/database.py:55-70`, `1192-1198`) — an injection attempt (`"added_at DESC; DROP TABLE tracks --"`) was rejected and the table survived — and (b) the `UPDATE tracks SET ...` column lists in `update_track` (`core/database.py:1491-1514`) and `backfill_track_metadata` (`core/database.py:1665-1693`), both restricted to hard-coded column names / the `TRACKS_UPDATABLE_COLUMNS` whitelist. `ALTER TABLE history ADD COLUMN {name} {definition}` interpolates only module-level constants.
- **LIKE escaping — correct.** `_like_pattern` (`core/database.py:1349-1364`) escapes `\`, `%` and `_` in that order (escape char first) and every query that uses it declares `ESCAPE '\'`. Verified live: `search_tracks("%")` returned only the literal title "100% Pure"; `"AC_DC"` matched `artist='AC_DC'` but not `artist='ACDC'`; `"a_b"` matched the literal album `a_b`.
- **FTS5 quoting — correct.** `search_tracks` builds `"word"*` terms with `""` doubling (`core/database.py:1372-1376`); a malformed query raises inside FTS and is caught, falling back to LIKE.
- **WAL is load-bearing and correctly enabled.** `PRAGMA journal_mode=WAL` is set on every connection (`core/database.py:186`), `PRAGMA synchronous=NORMAL`, `busy_timeout=30000` and `timeout=30.0` on `sqlite3.connect` (`core/database.py:181`). Verified at runtime: `journal_mode = wal`, `busy_timeout = 30000`.
- **Foreign keys are ON and declared.** `PRAGMA foreign_keys=ON` (`core/database.py:191`) is executed on every connection before any transaction, and it is effective (verified: an orphan `history` row raises `IntegrityError: FOREIGN KEY constraint failed`). `playlist_tracks` and `history` both declare `ON DELETE CASCADE` to `tracks`/`playlists`. (The `download_queue` table is the exception — F-WN-12-9.)
- **The dup-cleanup merge is atomic and idempotent.** The whole merge — payload carry-over, history re-point, playlist re-point, download-queue re-point, the row deletion, the redundant-entry cleanup and both version records — runs inside one `with conn:` block, so a failure rolls the whole thing back and the migration simply runs again next start (`core/database.py:596-624`). The flag is written only inside that transaction, so it can never claim a migration that did not commit. `schema_migrations` is keyed by version, so the migration does not re-merge on the next start.
- **The merge heuristic is conservative — the blast radius of a false merge is small.** A row is only collapsed into a survivor when *all* of `title, artist, album, source, source_id, file_path` are identical (`TRACK_RECORDING_COLUMNS`, `core/database.py:88`). Because `tracks.file_path` is `UNIQUE` in the current schema, two rows can only share a non-NULL `file_path` in a legacy DB that predates the constraint — i.e. the same physical file. Rows that merely share a title/artist (different album, provider id, file, spelling, or an "Unknown Artist" placeholder) are left untouched, and placeholder names are excluded by the shared `name_is_meaningful` guard used by both the creation path and the migration.
- **The merge preserves the user's data.** History rows, playlist entries and download-queue rows are re-pointed at the survivor *before* the duplicate row is deleted; `play_count` is summed, `is_favorite` OR-ed, `last_played` takes the later stamp, and non-empty payload columns are carried over. This is a genuine improvement over the destructive migration it replaces.
- **Write-lock discipline inside `core/database.py` is consistent.** Every mutating method takes `self._write_lock` (an `RLock`) and then `with self.conn:` — i.e. the write is serialised and committed in one transaction. `isolation_level` is the Python default `""` (legacy implicit transactions), so DML inside `with conn:` is genuinely transactional and DDL runs in autocommit (which is what makes the `VACUUM INTO` snapshot work after the explicit `commit()` at `core/database.py:778`).
- **`cleanup_expired_cache` does not orphan files.** It only deletes rows with `cached_file_path IS NULL OR = ''` (`core/database.py:2234-2238`), and `set_cached_file` sets `expires_at = NULL` for on-disk files (`core/database.py:2142`), so a cached file's row is never purged while the file exists. The file side of the lifecycle is `utils/cache_manager.purge_stream_cache` (WN-27), which deletes the files and syncs the DB in one transaction — consistent, no unbounded growth.
- **`delete_playlist` is clean** (`core/database.py:2018-2026`): it removes the `playlist_tracks` rows and the playlist row in one transaction; playlists have no cover file in practice (`playlists.cover_path` is never written by any app code path), so there is no orphaned file.
- **No upward coupling.** `core/database.py` imports only `sqlite3, os, json, logging, threading, uuid, datetime, typing` — it does not know about `AppApi`, `AppCore` or any service. The dependency direction is one-way.

---

### 4. Coverage gaps

- **The `android/` subtree was not opened** (out of scope by instruction).
- **The real `~/.nedotify/` library was never opened.** All runtime verification used throwaway SQLite files under `%TEMP%`; I could not measure the actual row counts, `history` table size or `-wal` size of a real user install, so the absolute cost of F-WN-12-3/5/6 is extrapolated from synthetic fixtures (3 000–4 000 tracks, 6 000–12 000 history rows) rather than measured on the user's data.
- **`core/database.py` was read in full, but the ~15 callers that bypass it were only sampled.** `core/downloader.py`, `utils/cache_manager.py`, `utils/file_scanner.py`, `services/lufs_scanner.py`, `services/smart_playlists.py`, `services/taste_profile.py` and `services/listening_comparison.py` all write through `db.conn` / `db._write_lock` directly; I verified the pattern and its consequences but did not audit each call site exhaustively (those belong to WN-13 / WN-25 / WN-27 / WN-23).
- **`core/offline.py`'s `available_tracks` / `offline_library` filtering** was read only where it touches the DB (`core/offline.py:56-77`); the "missing file" filtering rules themselves are WN-15/WN-09 territory.
- **I did not run the project's pytest suite** (read-only review); the existing pins in `tests/test_dup_cleanup_migration.py` and `tests/test_db_integrity.py` were read to establish what is already covered, and every finding above is *outside* those pins.
- **F-WN-12-11 is latent:** it requires `DUP_CLEANUP_VERSION` to be bumped. I verified the mechanism (the `CREATE TABLE IF NOT EXISTS` no-op and the timestamped file copy) but could not observe the trigger in this tree.
- **`PRAGMA wal_checkpoint(TRUNCATE)` under contention** was not reproduced end-to-end (F-WN-12-10's "busy" branch): I confirmed the return value is discarded and that the pragma reports `busy`/`log`/`checkpointed`, but I did not hold a read transaction open across the shutdown path to force `busy=1` in the real app's ordering.
- **`_plan_track_merges` cost on a large legacy library** was not benchmarked: the per-group `SELECT * FROM tracks WHERE LOWER(title)=? AND LOWER(artist)=?` is an unindexed lookup repeated once per duplicate group, but I did not measure it against a realistic number of groups.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — `DatabaseManager` is a god class; there is no repository/DAO seam.**
2489 lines, ~60 public methods spanning tracks, playlists, history, settings, stream cache, scan folders, listening stats, download queue, FTS maintenance, two schema migrations and the WAL lifecycle — with `sqlite3` visible in every signature (`self.conn` is a public property). The measurable consequence is not aesthetic: because there is no seam, five modules bypass the API and write through `db.conn` / `db._write_lock` directly — `core/downloader.py:276-278, 298-300, 318-326, 364-366, 490-491, 569-571, 759-760, 773-775, 822-833, 853-855, 874-876`; `utils/cache_manager.py:255-265`; `utils/file_scanner.py:148-152`; `services/lufs_scanner.py:62-106`; `services/smart_playlists.py:94-125`; `services/taste_profile.py:526` (which literally returns the raw connection to its callers). The write-lock invariant that `DatabaseManager` establishes is therefore not enforced outside the class — `utils/file_scanner.py` and `services/lufs_scanner.py` commit on a connection no other thread's lock covers. Direction: split into `TrackRepository`, `PlaylistRepository`, `HistoryRepository`, `SettingsStore`, `StreamCacheStore`, `DownloadQueueRepository` behind narrow protocols, keep `DatabaseManager` as the connection/transaction owner, and make `conn`/`_write_lock` private.

**ARCH-2 — The `:memory:` escape hatch is a trap: the thread-local connection model gives every thread its own empty database.**
`DatabaseManager(db_path=":memory:")` is explicitly supported (the WAL pragma is skipped for it, `core/database.py:184-185`), but `_get_connection` opens a *new* `sqlite3.connect(":memory:")` per thread, so the second thread sees a database with no schema at all. Verified: the main thread saw 1 row, the worker thread raised `OperationalError: no such table: tracks`. Any multi-threaded test or future in-memory deployment silently operates on an empty DB. Direction: use `file::memory:?cache=shared` with a held keeper connection, or refuse `:memory:` explicitly and document that tests must use a temp file.

**ARCH-3 — The read API has no projection contract, so every read ships whole rows.**
Every read method does `SELECT *` and returns `dict(sqlite3.Row)` — a 28-column dict per row, including the `metadata_json` blob. `get_all_tracks()` on 4 000 rows produced 3.0 MB of JSON and 112 000 dict entries for data the library view does not use. Combined with F-WN-12-3/5/6 this makes the persistence layer the dominant cost of every UI render. Direction: define small, purpose-built row shapes (a `TrackSummary` dataclass / `SELECT` list per use case) and let the repository own the projection.

**ARCH-4 — The migration mechanism is a single-purpose, hard-coded pair instead of a general one.**
`schema_migrations` (L723-731) exists and is the right idea, but it is used for exactly two hard-coded versions and the version strings are compared to constants in the class body. There is no `PRAGMA user_version`, no ordered list of migrations, and the `ALTER TABLE` statements are hand-rolled `try/except` blocks rather than a migration list (F-WN-12-14). Direction: an ordered, declarative migration list keyed on `schema_migrations.version`, executed in order, each step in its own transaction, with the "duplicate column" problem solved by inspecting `PRAGMA table_info` instead of catching exceptions.

**ARCH-5 — The schema has no way to express the domain's concepts.**
There is no `origin`/`is_system` flag on `playlists` (hence F-WN-12-2), no `state`/`attempts`/`error` on `download_queue` (hence F-WN-12-9 and the downloader's ad-hoc `status` strings: `'pending'`, `'downloading'`, `'completed'`, `'failed'`, `'cancelled'` are string literals spread over `core/database.py:2330-2411` and `core/downloader.py`), and no relation between `tracks` and `stream_cache` even though the two describe the same recording by `(source, source_id)`. Direction: model these as columns/foreign keys so the invariants can be enforced by the database rather than by convention in five modules.

**ARCH-6 — Query composition is duplicated instead of centralised.**
`get_playlists()` (L1931) already solves the "list with track counts" problem with a `LEFT JOIN ... GROUP BY`, yet `search_playlists()` (L1445) re-implements it with an N+1 (F-WN-12-7); the "tracks of a playlist" query exists twice (`get_playlist_tracks` L2004 and `get_smart_playlist_tracks` L2001, which just delegates); the "recently played" query exists three times with three different shapes (`get_history` L1599, `get_user_history_tracks` L1239, `get_most_played_tracks` L1229). Direction: a small query-builder/repository layer with named, parameterised queries and shared projections.
