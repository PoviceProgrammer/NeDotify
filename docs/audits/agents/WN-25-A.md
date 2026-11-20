## AREA WN-25 — Loudness scan, audio fingerprint, watchdog, listening comparison — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `services/lufs_scanner.py` L1–109 (whole file: `analyze_lufs` L16–35, `LufsScannerService` L38–109)
- `services/audio_fingerprint_service.py` L1–134 (whole file: `AudioFingerprintService` L20–134)
- `services/watchdog_service.py` L1–129 (whole file: `AudioFileHandler` L26–74, `WatchdogService` L77–129)
- `services/listening_comparison.py` L1–84 (whole file: `_stamp` L9–10, `listening_comparison` L13–84)
- `core/api.py` L342–363 (`AppApi.__init__`), L1090–1193 (`_emit`, `_enrich_track_lufs`), L1445–1484 (`play_track`), L2530–2559 (`get_track_info` / `get_playlist_tracks`), L3410–3479 (`open_local_file`), L3860–3908 (`find_duplicate_tracks`, `delete_duplicate_track`), L4219–4225 (`get_listening_comparison`), L2077–2136 (`search` local source)
- `core/app.py` L100–219 (subsystem wiring, `watchdog.start()`, `lufs_scanner.start()`), L500–586 (`cleanup()`)
- `core/database.py` L15–94 (`TRACKS_UPDATABLE_COLUMNS`), L120–199 (`_get_connection`, thread-local connections), L200–345 (schema: `tracks`, `history`, `scan_folders`), L465–514 (`lufs` / `peak_volume` ALTERs), L1054–1209 (`add_track`, `get_track`, `get_track_by_path`, `get_all_tracks`), L1484–1514 (`delete_track`, `update_track`), L1723–1834 (`get_wrapped_stats`), L2250–2299 (`scan_folders` accessors), L2410–2489 (`close_thread_connection`, `close`)
- `core/downloader.py` L790–844 (download completion → `mark_track_downloaded`)
- `utils/file_scanner.py` L1–181 (`is_audio_file`, `FileScanner._import_file`, `scan_folder`)
- `ui/web_new_v2/js/profile-comparison.js` L1–56, `ui/web_new_v2/js/player.js` L715–744, L1649–1653, L17–18, L172, `ui/web_new_v2/js/settings.js` L270–302, L3258–3346, `ui/web_new_v2/js/profile.js` L40–84, `ui/web_new_v2/index.html` L648
- `tests/test_lufs_resources.py` L1–109, `tests/test_listening_comparison.py` L1–64
- `STATUS.md` L175–214 (`BRIDGE_SYNC_BUDGET` contract), `CODING_STANDARDS.md` (grep), `AGENTS.md`

**Callees traced into other areas (defects there belong to the owning area, not to WN-25)**

- `core/api.py` — `_enrich_track_lufs` (L1161), `get_listening_comparison` (L4223), `find_duplicate_tracks` (L3876), `delete_duplicate_track` (L3884) — WN-03 / WN-08 / WN-10
- `core/database.py` — `get_wrapped_stats` (L1723), `mark_track_downloaded` (L1278), `get_scan_folders` (L2255), `delete_track` (L1484) — WN-12
- `core/app.py` — `AppCore.__init__` / `cleanup()` — WN-02
- `core/downloader.py` — download → `mark_track_downloaded` — WN-13
- `utils/file_scanner.py` — `FileScanner.scan_folder` / `_import_file` — WN-27
- `ui/web_new_v2/js/player.js` — ReplayGain application — WN-29; `js/settings.js` — duplicate delete UI — WN-30; `js/profile-comparison.js` — WN-32

### 2. Findings

#### F-WN-25-1  [P1] — The period comparison blocks the bridge for minutes on a real listening history

- **File:** `services/listening_comparison.py:56-66` (also `:67-81`), reached from `core/api.py:4223-4225`
- **Confirmed:** yes
- **Description:** `listening_comparison()` runs six queries. Five are fast; the `new_artists` query contains a **correlated** `NOT EXISTS` subquery that re-scans the entire `history` table (all rows before `current_start`) for **every outer row** of the current window. On a realistic history this dominates the whole call by three orders of magnitude. The bridge method has no timeout, so the JS promise for the Profile "Сравнить периоды прослушивания" panel stays pending for minutes.
- **Cause:** the "never heard before" test is expressed as a correlated subquery over `history` instead of a pre-aggregated artist set. `EXPLAIN QUERY PLAN` shows `SEARCH old USING INDEX idx_history_played_at (played_at<?)` — an unbounded scan — executed once per outer row.
- **Trigger conditions:** any user whose `history` table is not tiny. The `year` period is the worst (its window covers nearly the whole table).
- **User impact:** the Profile comparison panel appears frozen (the "Обновить" button stays disabled, `aria-busy` never clears). The documented synchronous-bridge budget is `BRIDGE_SYNC_BUDGET = 6.0` s (`core/api.py:67`, `STATUS.md:188`); the measured cost exceeds it by up to ~30×. Re-selecting the period or reopening the panel starts *another* concurrent multi-minute query on the bridge thread (the `generation` counter in `profile-comparison.js:29` only guards the DOM update, not the backend work).
- **Evidence:**
  ```python
  # services/listening_comparison.py:56-66
  new_artists = [dict(row) for row in db.conn.execute('''
      SELECT t.artist, SUM(h.duration_listened) AS seconds
      FROM history h JOIN tracks t ON t.id = h.track_id
      WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0
        AND TRIM(COALESCE(t.artist, '')) != '' AND LOWER(t.artist) != 'unknown artist'
        AND NOT EXISTS (
            SELECT 1 FROM history old JOIN tracks older ON older.id = old.track_id
            WHERE old.played_at < ? AND old.duration_listened > 0
              AND LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist)))
      GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, t.artist LIMIT 10
  ''', (_stamp(current_start), _stamp(moment), _stamp(current_start)))]
  ```
  Measured on a synthetic DB (4 000 tracks / 200 artists / 120 000 history rows, 400 days spread), `services.listening_comparison.py` executed unchanged:
  ```
  period=week   elapsed=  5.39s
  period=month  elapsed= 26.48s
  period=year   elapsed=116.88s
  ```
  Per-query breakdown for the `year` window:
  ```
  totals             0.06s
  artists            0.16s
  daily              0.10s
  new_artists      174.88s   <-- dominant
  returning_artists  0.83s
  ```
  Query plan: `SEARCH old USING INDEX idx_history_played_at (played_at<?)` inside `CORRELATED SCALAR SUBQUERY 1`.
- **Reproduction / verification:** run `%TEMP%\opencode\wn25_perf.py` (builds the synthetic DB and calls `listening_comparison` for week/month/year) and `%TEMP%\opencode\wn25_perf2.py` (per-query timing). Both are read-only against a temp DB. Scale is linear in `history` rows × artist groups, so ~20 000 plays already costs ≈30 s for the `year` period.
- **Suggested fix:** replace the correlated subqueries with a pre-aggregated artist set (e.g. one `GROUP BY LOWER(TRIM(artist))` pass over the pre-window history, joined once), or compute the "new"/"returning" artist sets with a single window-function query. Add a bridge-side deadline for `get_listening_comparison` so a slow call returns a partial result instead of hanging.
- **Fix side effects:** the "returning artist" semantics (heard before `previous_start`, absent in the previous window) must be preserved exactly — the existing test `tests/test_listening_comparison.py:39-44` pins it.
- **Discovered by:** A

#### F-WN-25-2  [P1] — The filesystem watchdog watches nothing: no shipping code path ever registers a scan folder

- **File:** `services/watchdog_service.py:104-116` (`_sync_folders`), `services/watchdog_service.py:89-95` (`start`)
- **Confirmed:** yes
- **Description:** `WatchdogService._sync_folders()` derives the watch list from the `scan_folders` DB table. That table is written in exactly one place — `utils/file_scanner.py:99`, inside `FileScanner.scan_folder()` — and `scan_folder()` is never called by the application (`FileScanner.rescan_all_folders()` is its only caller, and `rescan_all_folders` itself has no caller). The `storage.scan_folders` *setting* (`core/settings.py:149`) is a different store and is never read by the watchdog. The result: `AppCore` starts an observer over an empty set of paths.
- **Cause:** the registration path (`FileScanner.scan_folder`) was never wired to any bridge method, UI action, or startup routine; the watcher and the registrar live in different subsystems with no link.
- **Trigger conditions:** always — from a fresh install and from an existing profile, `db.get_scan_folders()` returns `[]`.
- **User impact:** the whole "watch a folder and import new audio" feature is inert. New files appearing in a music folder are never imported, `library_updated` is never emitted for them, and the watchdog's import path (including the bugs below) is unreachable. The subsystem costs an observer thread, a handler thread and a directory watch for nothing.
- **Evidence:**
  ```python
  # services/watchdog_service.py:104-107
  def _sync_folders(self):
      folders = self._core.db.get_scan_folders()
      db_paths = {f['folder_path'] for f in folders if f.get('auto_scan')}
  ```
  ```python
  # utils/file_scanner.py:99  (inside FileScanner.scan_folder -> _scan())
  self.db.add_scan_folder(folder_path)
  ```
  Repo-wide grep for `scan_folder|rescan_all_folders|add_scan_folder` over `*.py` returns only the definitions above plus `tests/`. Grep over `ui/web_new_v2/**/*.js` for `scan_folder|rescan|import_local` returns **no matches**. `core/api.py` has no scan-folder bridge method (the only scanner call is `scan_single_file` at L3449, which does not register a folder).
- **Reproduction / verification:** `DatabaseManager.get_scan_folders()` returns `[]` on a fresh profile; `grep -rn "scan_folder(" --include=*.py .` outside `utils/file_scanner.py` and `tests/` returns nothing. `AppCore.__init__` → `self.watchdog.start()` → `_sync_folders()` → `self.observer.schedule(...)` is never reached.
- **Suggested fix:** wire a folder-registration path (bridge method + UI entry) that calls `db.add_scan_folder(path)`, and/or have `WatchdogService` re-run `_sync_folders()` periodically or on demand so the observer picks up folders added at runtime (see F-WN-25-10). The folder-registration UI itself belongs to WN-06/WN-30.
- **Fix side effects:** once folders *are* watched, the pre-existing defects in F-WN-25-8 (Windows lock probe) and F-WN-25-2 become reachable and must be fixed together, otherwise partial files get imported.
- **Discovered by:** A

#### F-WN-25-3  [P1] — The LUFS scanner never analyses downloaded music (the bulk of the user's library)

- **File:** `services/lufs_scanner.py:63-69`
- **Confirmed:** yes
- **Description:** The scan query selects `WHERE source = 'local'`. But the download path never changes a track's `source`: `core/downloader.py:819` calls `db.mark_track_downloaded(track_id, file_path)`, which runs `UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?` and leaves `source` at the provider value (`youtube`, `soundcloud`, `yandex`, …). Only files imported through the native file dialog (`utils/file_scanner.py:134`, `source="local"`) are ever selected. Consequently the ReplayGain feature never applies to downloaded music.
- **Cause:** the filter uses the *provenance* column (`source`) where the *storage* column (`file_path` / `is_downloaded`) is meant.
- **Trigger conditions:** always — any track the user downloaded.
- **User impact:** the player applies no loudness normalisation to downloaded tracks (`ui/web_new_v2/js/player.js:725-727` reads `track.loudness_lufs`, which stays `NULL` for them), so a downloaded library plays at wildly different relative levels. The LUFS scan also never populates `peak_volume` for them.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:63-69
  cursor.execute("""
      SELECT id, file_path FROM tracks
      WHERE source = 'local'
      AND lufs IS NULL
      AND file_path IS NOT NULL
      LIMIT 20
  """)
  ```
  ```python
  # core/database.py:1278-1282
  def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
  Repo-wide grep: no `UPDATE tracks SET source ...` statement exists anywhere.
- **Reproduction / verification:** download any track, then inspect `SELECT id, source, file_path, lufs FROM tracks WHERE is_downloaded = 1;` — `source` is still the provider and `lufs` stays `NULL` forever (the scan query can never match the row).
- **Suggested fix:** select on `file_path IS NOT NULL AND lufs IS NULL` (optionally restricted to `is_downloaded = 1 OR source = 'local'`), i.e. on the presence of a local file rather than on provenance.
- **Fix side effects:** the scan would start analysing the whole downloaded library — see F-WN-25-6 (memory) and F-WN-25-9 (exit delay), which become materially more important with a larger queue. The `LIMIT 20` batch keeps the rate bounded, but the per-file cost does not.
- **Discovered by:** A

#### F-WN-25-4  [P2] — The duplicate scanner has the same blind spot: it only inspects `source = 'local'` tracks

- **File:** `services/audio_fingerprint_service.py:71`
- **Confirmed:** yes
- **Description:** `find_duplicates()` scans `db_manager.get_all_tracks(source="local")`. For the same reason as F-WN-25-3, downloaded tracks (the ones most likely to be duplicated — the same song fetched from two providers) carry a provider `source` and are never fingerprinted.
- **Cause:** provenance used where "has a local file" is meant.
- **Trigger conditions:** always.
- **User impact:** the Settings → "Сканирование медиатеки на дубликаты" button (`ui/web_new_v2/js/settings.js:287-291`) reports "Дубликатов не обнаружено" for a library that actually contains duplicates.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:71
  all_tracks = db_manager.get_all_tracks(source="local")
  ```
- **Reproduction / verification:** two rows with the same `file_path` content but `source='youtube'` are never returned by `get_all_tracks(source="local")` → `find_duplicates` returns `[]`.
- **Suggested fix:** fingerprint every track that has an existing `file_path` (`get_all_tracks()` plus a `file_path IS NOT NULL` filter), or filter on `is_downloaded = 1 OR source = 'local'`.
- **Fix side effects:** more files to hash (the fingerprint reads ≤192 KB per file, so this is cheap), and more false-positive exposure through the delete path (F-WN-25-7).
- **Discovered by:** A

#### F-WN-25-5  [P2] — Failed and missing analyses write fabricated loudness values that the UI presents as measurements

- **File:** `services/lufs_scanner.py:78-95`
- **Confirmed:** yes
- **Description:** Three different outcomes are collapsed into "a number in the DB". A missing file is stored as `lufs = 0.0`; a decode/analysis failure is stored as `lufs = -14.0, peak = 1.0`; both are then read back by `core/api.py::_enrich_track_lufs` and shown to the player as if they had been measured. `0.0 LUFS` is not a neutral value — it is the loudest possible reading, and the player turns it into a **-14 dB attenuation**.
- **Cause:** the error branches pick a hard-coded "plausible" value instead of leaving the column `NULL` (which the scan query uses as "not yet measured").
- **Trigger conditions:** a track whose file was moved/deleted after import (→ `0.0`); a corrupt, unsupported or shorter-than-0.4 s file (→ `-14.0`).
- **User impact:** the affected track plays ~14 dB too quiet (`0.0` → ReplayGain `10^((-14-0)/20) = 0.1995` → `player.js:727` clamps to 0.1..2.0 → 0.1995) — or, for the `-14.0` case, the UI shows a plausible "-14.0 LUFS" that was never measured. Because the fabricated value is non-`NULL`, the row is also permanently excluded from the `lufs IS NULL` scan query, so the file is **never re-measured** even if it reappears.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:78-95
  if os.path.exists(filepath):
      futures[self._pool.submit(analyze_lufs, filepath)] = track_id
  else:
      self._update_db(track_id, 0.0, 0.0)          # <-- fabricated
  ...
  lufs, peak, err = future.result()
  if lufs is not None:
      self._update_db(track_id, lufs, peak)
  else:
      logger.error(f'LUFS scan failed for track {track_id}: {err}')
      self._update_db(track_id, -14.0, 1.0)        # <-- fabricated
  ```
  ```python
  # ui/web_new_v2/js/player.js:725-727
  const trackLufs = track.loudness_lufs !== undefined && track.loudness_lufs !== null ? track.loudness_lufs : track.lufs;
  if (trackLufs !== undefined && trackLufs !== null && !isNaN(Number(trackLufs))) {
      currentReplayGain = Math.min(2.0, Math.max(0.1, Math.pow(10, (TARGET_LUFS - Number(trackLufs)) / 20)));
  ```
  Verified end-to-end against the real `DatabaseManager`:
  ```
  after missing-file write:  'loudness_lufs': 0.0,  'lufs': 0.0,  'peak_volume': 0.0
  after failed-analysis write:'loudness_lufs': -14.0,'lufs': -14.0,'peak_volume': 1.0
  ```
  `analyze_lufs` really does fail for short/corrupt input (measured):
  ```
  short file (<0.4 s) analyze: (None, None, 'Audio must have length greater than the block size.')
  corrupt file analyze:        (None, None, "('failed to decode file', -1)")
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe.py` — creates a `tracks` row with a non-existent `file_path`, calls `LufsScannerService._update_db(tid, 0.0, 0.0)` and `(tid, -14.0, 1.0)`, and dumps the row. For the short/corrupt cases, decode a <0.4 s WAV and a bogus `.mp3` through `analyze_lufs`.
- **Suggested fix:** leave the column `NULL` on failure (and record the reason in a log/telemetry field) so the row stays eligible for a retry; use a sentinel that the player can distinguish from a measurement, or simply omit the value. If a "never measured" marker is required, it must be outside the numeric LUFS field.
- **Fix side effects:** leaving the row `NULL` means the scan query keeps re-selecting it every cycle → an endless retry loop for a permanently broken file. A "failed" marker column (or a bounded retry counter) is needed to avoid that.
- **Discovered by:** A

#### F-WN-25-6  [P2] — A silent track produces `-inf` LUFS, which is written to the DB and shipped to the frontend as a non-finite number

- **File:** `services/lufs_scanner.py:31-33`, `services/lufs_scanner.py:100-107`
- **Confirmed:** yes
- **Description:** `pyloudnorm` returns `-inf` for a file whose gated loudness is below the absolute gate. `analyze_lufs` converts it with `float(loudness)` and returns it with `error = None`, so the scan loop treats it as a successful measurement and stores `-inf` in `tracks.lufs` / `tracks.loudness_lufs`. `json.dumps` renders `-inf` as the bare literal `-Infinity`, which is **not valid JSON** (`json.dumps(..., allow_nan=False)` raises `ValueError`), and the player then clamps the resulting ReplayGain to `2.0`.
- **Cause:** no finiteness check on the measured value before it is persisted and emitted.
- **Trigger conditions:** any track that is digitally silent, or whose content is entirely below -70 LUFS (a silence intro, a placeholder file, a corrupted-but-decodable file).
- **User impact:** (a) a non-finite float is stored in the library DB; (b) any strict-JSON consumer of that payload breaks (`ValueError`); (c) the player applies a `2.0` ReplayGain (a +6 dB boost) to that track because `!isNaN(Number(-Infinity))` is true and `Math.pow(10, Infinity)` is `Infinity` → clamped to 2.0.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:30-33
  meter = pyln.Meter(rate)
  loudness = meter.integrated_loudness(audio_data)
  peak = max(abs(float(audio_data.min())), abs(float(audio_data.max())))
  return float(loudness), float(peak), None
  ```
  Measured:
  ```
  analyze_lufs(<10 min silent wav>)  ->  (-inf, 0.0, None)
  sqlite -inf round trip: (-inf, -inf, 0.0)
  json.dumps: {"loudness_lufs": -Infinity}
  json allow_nan=False -> ValueError Out of range float values are not JSON compliant: -inf
  ```
  ```python
  # ui/web_new_v2/js/player.js:726-727
  if (trackLufs !== undefined && trackLufs !== null && !isNaN(Number(trackLufs))) {
      currentReplayGain = Math.min(2.0, Math.max(0.1, Math.pow(10, (TARGET_LUFS - Number(trackLufs)) / 20)));
  ```
  (`Number(-Infinity)` is `-Infinity`, `isNaN(-Infinity)` is `false`.)
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe.py` (first block) inserts `-inf` into a `tracks`-shaped table and dumps the row + `json.dumps` output; the silent-WAV case is reproduced in the LUFS measurement run (`analyze_lufs` on a 10-minute zero-filled WAV returns `(-inf, 0.0, None)`).
- **Suggested fix:** treat a non-finite loudness as a failed measurement (same path as F-WN-25-5) and never persist `-inf`/`nan`.
- **Fix side effects:** silent tracks will then be reported as "not measured" rather than as a boosted track — a behaviour change in the player, but a correct one.
- **Discovered by:** A

#### F-WN-25-7  [P2] — The Windows "still locked by the writer" probe never fires, so a partially written file is imported

- **File:** `services/watchdog_service.py:59-66`
- **Confirmed:** yes
- **Description:** `_process_pending()` opens the pending file read-only to decide whether the writer is done. On Windows, CPython opens files with share-deny-none, so the probe **succeeds on a file that another process is still writing**; the `IOError` branch (and the `self._pending_files[path] = now` re-queue) is dead code on this platform. The only remaining protection is the flat 3-second debounce.
- **Cause:** a POSIX file-locking assumption applied to Windows, where `open()` does not fail on a file open for writing.
- **Trigger conditions:** any copy/download into a watched folder that takes longer than 3 seconds — i.e. every large file on a slow link or a slow disk. (Currently masked by F-WN-25-2: no folder is watched.)
- **User impact:** the file is handed to `FileScanner._import_file` while incomplete → tags parsed from a truncated file (wrong/absent duration, artist), a DB row created for the partial file, and `library_updated` emitted for it. `FileScanner._import_file` returns `None` for a path that is already in the DB (`utils/file_scanner.py:114-116`), so when the copy finishes the file is **never re-imported** — the library keeps the truncated metadata forever.
- **Evidence:**
  ```python
  # services/watchdog_service.py:56-66
  with self._lock:
      for path, timestamp in list(self._pending_files.items()):
          if now - timestamp >= 3.0:
              try:
                  with open(path, 'rb'):
                      ready_files.append(path)
                      del self._pending_files[path]
              except IOError as e:
                  logger.debug(f'Watchdog: {path} still locked by the writer: {e}')
                  self._pending_files[path] = now
  ```
  Measured on this Windows host: a file held open for writing by another handle is opened successfully by `open(path, 'rb')`:
  ```
  OPEN-WHILE-WRITING: SUCCEEDED, read 100 bytes -> no lock detection
  ```
  End-to-end through the real `AudioFileHandler`: a file still open for writing was passed to the callback after the 3 s debounce:
  ```
  callback fired for a file still being written: ['...\\song.mp3']
  -> the 'still locked by the writer' guard did NOT block it: True
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_watchdog.py` — holds a file open for writing, calls `handler._add_pending(target)`, waits 4.5 s and prints whether the callback fired.
- **Suggested fix:** on Windows use a size-stability check (the file size must be unchanged across two consecutive polls) in addition to the age debounce, and/or attempt an exclusive open (`os.open` with `O_EXCL` semantics are not enough on Windows — an exclusive-create probe or a `msvcrt.locking` attempt is). The generic fix is "size unchanged between polls".
- **Fix side effects:** a size-stability check delays the import of files that are being written slowly but continuously; the debounce must be raised accordingly.
- **Discovered by:** A

#### F-WN-25-8  [P2] — A duplicate can be deleted from disk while the app reports "could not delete"

- **File:** `services/audio_fingerprint_service.py:115-134`, consumed by `core/api.py:3884-3908`
- **Confirmed:** yes
- **Description:** `delete_duplicate_track()` removes the file from disk **first** and only then deletes the DB row. If `db_manager.delete_track(track_id)` raises (DB locked beyond the 30 s busy timeout, a FK/trigger error, disk error), the exception is swallowed by the service's `except`, the service returns `False`, and the API returns `{"success": False, "error": "Не удалось удалить дубликат"}` — **but the file is already gone**. The DB row survives and now points at a non-existent file.
- **Cause:** irreversible filesystem mutation ordered before the transactional part, with the failure of the second step masked.
- **Trigger conditions:** a DB write error during the delete (lock contention is the realistic one: `busy_timeout=30000` in `core/database.py:190`).
- **User impact:** the user is told the delete failed and keeps using the track, but the audio file has been permanently removed from disk with no way back. The library shows a row whose file is gone.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:120-131
  try:
      track = db_manager.get_track(track_id)
      if track and delete_file:
          file_path = track.get("file_path")
          if file_path and os.path.exists(file_path):
              try:
                  os.remove(file_path)
              except Exception as fe:
                  logger.warning(f"Could not remove duplicate file {file_path}: {fe}")
      db_manager.delete_track(track_id)
      return True
  except Exception as e:
      logger.error(f"Failed to delete duplicate track {track_id}: {e}")
      return False
  ```
  ```python
  # core/api.py:3889-3891
  res = self._core.audio_fingerprint.delete_duplicate_track(self._core.db, track_id, delete_file=delete_file)
  if not res:
      return {"success": False, "error": "Не удалось удалить дубликат"}
  ```
- **Reproduction / verification:** monkeypatch `db_manager.delete_track` to raise, call `AudioFingerprintService().delete_duplicate_track(db, track_id, delete_file=True)` against a temp DB with a real file → the file is removed and the method returns `False`.
- **Suggested fix:** delete the DB row first and only remove the file after the row is gone; or make the two steps transactional in the right order (row first, file second, and report "row removed, file left behind" — the shape the API already models with `partial: True` for the opposite case).
- **Fix side effects:** if the file removal then fails, the user is left with an orphan file on disk — a nuisance, not data loss, and the API already has a `partial` response shape for it.
- **Discovered by:** A

#### F-WN-25-9  [P2] — A running LUFS analysis delays process exit (Python joins pool workers at interpreter shutdown)

- **File:** `services/lufs_scanner.py:53-56` (`stop`), `core/app.py:543-544` (cleanup step)
- **Confirmed:** yes
- **Description:** `LufsScannerService.stop()` shuts the pool down with `wait=False, cancel_futures=True`. The already-running `analyze_lufs` call is not cancelled, and in CPython 3.9+ `concurrent.futures.thread._python_exit()` (registered via `threading._register_atexit`) **joins every pool worker thread** at interpreter shutdown. The app therefore cannot exit until the in-flight decode+analysis of the current file finishes.
- **Cause:** the pool's worker threads are non-daemon and are joined at exit; the service has no way to interrupt a decode in progress.
- **Trigger conditions:** the user closes the app while the scanner is analysing a file (the scan starts 10 s after launch and re-runs continuously).
- **User impact:** the window closes but the process lingers for the remaining analysis time (measured decode+analysis of a 10-minute file: ~2.7 s; a 1-hour file is proportionally longer). During that time the process still holds its DB connections and the ~300 MB decode buffer (F-WN-25-10).
- **Evidence:**
  ```python
  # services/lufs_scanner.py:53-56
  def stop(self):
      self._running = False
      if self._pool:
          self._pool.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # .venv_win/Lib/site-packages/concurrent/futures/thread.py (CPython 3.14.7)
  def _python_exit():
      ...
      for t, q in items:
          t.join()
  threading._register_atexit(_python_exit)
  ```
  Measured (a 5 s task in a `ThreadPoolExecutor(max_workers=1)` with no `shutdown()`):
  ```
  TOTAL PROCESS WALL TIME: 5,1 s
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_exit.py` — submit `time.sleep(5)` to a pool, end the script, and time the process.
- **Suggested fix:** bound the work per file (decode in chunks / cap the analysed duration), and/or make the scanner abortable (a cancellation flag checked between chunks) so `stop()` can return promptly. A dedicated daemon-thread worker instead of `ThreadPoolExecutor` would also avoid the exit join, at the price of the `max_workers=1` serialisation guarantee.
- **Fix side effects:** a chunked decoder changes the measured result for very long files unless the gating blocks are stitched correctly; the existing test `tests/test_lufs_resources.py:21-56` pins the sample layout and must keep passing.
- **Discovered by:** A

#### F-WN-25-10  [P2] — The whole file is decoded into memory: hundreds of MB per track

- **File:** `services/lufs_scanner.py:23-29`
- **Confirmed:** yes
- **Description:** `miniaudio.decode_file(filepath)` decodes the **entire** file to PCM in memory, and `np.asarray(decoded.samples, dtype=np.float32)` then doubles the footprint. `miniaudio.decode_file` defaults to `nchannels=2, sample_rate=44100` and `SampleFormat.SIGNED16`, so every file is resampled to 44.1 kHz stereo — the cost is fixed at 176 400 bytes per second of audio, regardless of the source format.
- **Cause:** a whole-file decode with no chunking; the float32 working copy is unavoidable given the current `pyloudnorm` API usage.
- **Trigger conditions:** every scanned file; the peak scales linearly with duration (≈318 MB for a 10-minute file, ≈1.9 GB for a 1-hour file).
- **User impact:** a large RSS spike in the app process during background analysis; on a 32-bit-limited or memory-constrained machine this can raise `MemoryError` (which `analyze_lufs` would convert into the fabricated `-14.0` of F-WN-25-5). It does **not** run on the bridge/UI thread — the scan loop is a daemon thread — so the window is not blocked.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:23-29
  decoded = miniaudio.decode_file(filepath)
  audio_data = np.asarray(decoded.samples, dtype=np.float32)
  audio_data /= 32768.0
  if decoded.nchannels > 1:
      audio_data = audio_data.reshape(-1, decoded.nchannels)
  rate = decoded.sample_rate
  del decoded
  ```
  ```python
  # .venv_win/Lib/site-packages/miniaudio.py
  def decode_file(filename, output_format=SampleFormat.SIGNED16, nchannels=2, sample_rate=44100, dither=DitherMode.NONE)
  ```
  Measured on a 10-minute stereo WAV (105.8 MB on disk): decode + integrated loudness took **2.7 s**, and the in-memory footprint is 105.8 MB (int16 PCM) + 211.7 MB (float32 copy) ≈ **318 MB** peak, plus the transient `frombytes` buffer inside `miniaudio.decode_file`.
- **Reproduction / verification:** generate a 10-minute 44.1 kHz stereo WAV, run `analyze_lufs` on it, and watch the process working set (the analysis itself is deterministic: `(-inf, 0.0, None)` for a silent file).
- **Suggested fix:** decode in frames (e.g. 10 s at a time) and feed the meter block by block, keeping only one chunk in memory; or use a bounded analysis window (BS.1770 gating over a representative sample) and record the analysed length.
- **Fix side effects:** chunked decoding changes the peak loudness result for files whose loudness varies strongly over time; the gating must be recomputed over the full stream, not per chunk.
- **Discovered by:** A

#### F-WN-25-11  [P2] — The LUFS cache has no mtime component, so a replaced file keeps its old measurement forever

- **File:** `services/lufs_scanner.py:63-69`, `services/lufs_scanner.py:100-107`
- **Confirmed:** yes
- **Description:** The only cache is the `tracks.lufs` / `tracks.loudness_lufs` columns. The scan query selects `lufs IS NULL` and nothing ever writes `NULL` back or compares the file's mtime/size. A file that is replaced on disk (re-download, re-encode, sync conflict) keeps the loudness measured from the old content, and the row is never re-scanned.
- **Cause:** the cache key is the track row, not (path, mtime, size); there is no invalidation hook on the file-mutation paths.
- **Trigger conditions:** a file is overwritten in place while the track row stays the same. Note that `FileScanner._import_file` returns `None` for an existing path (`utils/file_scanner.py:114-116`), so the replacement is not re-imported either — the DB keeps the old tags *and* the old LUFS.
- **User impact:** ReplayGain is computed from stale data → the track is normalised to the wrong level. There is no way for the user to force a re-measure (no bridge method resets `lufs` to `NULL`).
- **Evidence:**
  ```python
  # services/lufs_scanner.py:63-69
  SELECT id, file_path FROM tracks
  WHERE source = 'local'
  AND lufs IS NULL
  AND file_path IS NOT NULL
  LIMIT 20
  ```
  Repo-wide grep for `lufs = NULL` / `SET lufs` → no match outside this file's own UPDATE.
- **Reproduction / verification:** import a file, let the scanner fill `lufs`, overwrite the file with a different recording of the same track, restart the app → the row still holds the old `lufs` and the scanner never selects it again.
- **Suggested fix:** store the analysed (path, mtime, size) alongside the value and re-scan when they change; expose a "re-analyse loudness" action.
- **Fix side effects:** re-scanning on every mtime change means a file touched by a sync client is re-decoded (see F-WN-25-10 for the cost).
- **Discovered by:** A

#### F-WN-25-12  [P2] — The "acoustic fingerprint" is a file-byte hash, and the module/API contract claims otherwise

- **File:** `services/audio_fingerprint_service.py:1-4`, `:26-61`, `core/api.py:3876-3877`
- **Confirmed:** yes
- **Description:** The module docstring promises "acoustic fingerprints (MD5 content hash + file size + **audio duration**)" and the bridge method is documented as "duplicate track groups based on **acoustic fingerprint**". The implementation never decodes audio and never computes a duration: it is an MD5 over up to three 64 KB byte ranges of the file, plus the file size. The algorithm is deterministic and cheap (≤192 KB read per file) — but it only detects *byte-identical* copies, so two different encodings of the same song (a 320 kbps MP3 and a FLAC, or two provider rips) are never reported as duplicates, and no duration is ever available to corroborate a match.
- **Cause:** the fingerprint is a content hash, not an audio fingerprint; the documentation describes a different (unimplemented) algorithm.
- **Trigger conditions:** always; the mismatch is visible whenever the two features disagree (byte-identical copies detected, acoustically identical copies missed).
- **User impact:** the duplicate scanner both over- and under-reports relative to what the UI promises ("Сканирование медиатеки на дубликаты", "Совпадение 90 %"). A user who ripped the same album twice in two formats gets no report.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:1-4
  """
  NeDotify - Audio Fingerprint & Duplicate Detection Service
  Scans local audio tracks, computes acoustic fingerprints (MD5 content hash + file size + audio duration),
  and identifies duplicate song entries in the library.
  """
  ```
  ```python
  # services/audio_fingerprint_service.py:36-51
  with open(filepath, "rb") as f:
      head = f.read(sample_bytes)
      md5_hash.update(head)
      if file_size > sample_bytes * 3:
          f.seek(file_size // 2); mid = f.read(sample_bytes); md5_hash.update(mid)
          f.seek(file_size - sample_bytes); tail = f.read(sample_bytes); md5_hash.update(tail)
      else:
          f.seek(sample_bytes); md5_hash.update(f.read())
  ```
  (`sample_bytes` defaults to 65536, so the "full hash" threshold is 192 KB; for smaller files the whole file is hashed and `full_hash` is correctly `True` — that part is consistent.)
- **Reproduction / verification:** hash the same song encoded twice (`ffmpeg -b:a 320k` vs `-b:a 128k`) → different `signature` → no duplicate group. Hash the same file copied to two paths → identical → one group.
- **Suggested fix:** either align the documentation with the implementation (call it a content hash) or implement the promised acoustic fingerprint (a spectral hash plus the duration) — the latter is a much larger change.
- **Fix side effects:** an acoustic fingerprint needs decoding (see F-WN-25-10 for the memory profile) and would change the `match_confidence` semantics the UI displays.
- **Discovered by:** A

#### F-WN-25-13  [P3] — The "delete duplicate" UI offers a destructive action on a 90 %-confidence, sampled match

- **File:** `services/audio_fingerprint_service.py:14-17`, `:104-107`; `ui/web_new_v2/js/settings.js:3320`, `:3326-3337`; `core/api.py:3884-3905`
- **Confirmed:** yes (confidence semantics) / hypothesis (probability of an actual false positive)
- **Description:** For files larger than 192 KB the fingerprint covers only head + middle + tail, and the group is reported with `match_confidence = 90.0` (`SAMPLED_MATCH_CONFIDENCE`). The UI nevertheless renders a "Удалить" button on **every** track of the group and calls `delete_duplicate_track(trackId, true)` — `delete_file = true` — which removes the file from disk. The confirmation modal (`settings.js:3260-3289`) does not mention the confidence, the sampled nature of the hash, or which copy will be kept.
- **Cause:** a destructive, irreversible action is offered on a heuristic match with no disclosure of the confidence and no protection against deleting the last copy in a group.
- **Trigger conditions:** a group formed by a sampled hash (90 %) that is actually a false positive, or the user deleting every member of a true-duplicate group.
- **User impact:** irrecoverable loss of a unique audio file (the app has no trash/undo for this path).
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:14-17
  FULL_HASH_MATCH_CONFIDENCE = 100.0
  SAMPLED_MATCH_CONFIDENCE = 90.0
  ```
  ```javascript
  // ui/web_new_v2/js/settings.js:3320
  <div style="font-weight:700; color:var(--primary); margin-bottom:6px;">Группа дубликатов #${idx + 1} (Совпадение ${group.match_confidence}%)</div>
  // ui/web_new_v2/js/settings.js:3331
  const res = await window.pywebview.api.delete_duplicate_track(trackId, true);
  ```
- **Reproduction / verification:** place two different files of identical size in the library whose head/mid/tail 64 KB coincide → one group with `match_confidence: 90.0` → the delete button removes one of them from disk. (The probability of a genuine 192 KB collision between unrelated files is low; the exposure is the *mechanism*, not a demonstrated collision.)
- **Suggested fix:** require `full_hash` for the destructive "delete from disk" action, and surface the confidence and the "keep one copy" rule in the confirmation modal. The backend could refuse `delete_file=True` for a sampled group unless the caller passes an explicit acknowledgement flag.
- **Fix side effects:** legitimate duplicates that differ in their sampled regions would no longer be deletable from disk in one click; the DB row could still be removed.
- **Discovered by:** A

#### F-WN-25-14  [P3] — The LUFS writer bypasses the database write lock used by every other writer

- **File:** `services/lufs_scanner.py:100-107`
- **Confirmed:** yes
- **Description:** Every other write path in `core/database.py` serialises on the manager's `_write_lock` (`with self._write_lock: with self.conn:` — see `add_track` L1072, `delete_track` L1485, `update_track` L1510, `mark_track_downloaded` L1279). The LUFS scanner writes with a bare `conn.execute(...)` + `conn.commit()` and no lock. Because connections are per-thread (`core/database.py:179-201`), this is not a corruption risk, but it is a contract deviation: two writers can now contend for SQLite's single-writer lock and one of them waits out the 30 s `busy_timeout`.
- **Cause:** the service reaches into `db.conn` directly instead of using a `DatabaseManager` method.
- **Trigger conditions:** a LUFS write coinciding with any other write (import, download completion, tag update).
- **User impact:** a stall (up to the busy timeout) in an unrelated operation; a "database is locked" error surfacing in the log. Low severity.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:100-107
  def _update_db(self, track_id, lufs, peak):
      try:
          self._core.db.conn.execute(
              'UPDATE tracks SET lufs = ?, loudness_lufs = ?, peak_volume = ? WHERE id = ?',
              (lufs, lufs, peak, track_id)
          )
          self._core.db.conn.commit()
  ```
- **Reproduction / verification:** code inspection against `core/database.py:1072`, `:1279`, `:1485`, `:1510`; the same pattern also exists in `utils/file_scanner.py:148-152` (WN-27).
- **Suggested fix:** add a `DatabaseManager.set_track_loudness(track_id, lufs, peak)` method that takes `_write_lock`, and call it from the scanner.
- **Fix side effects:** none beyond a negligible lock-hold time.
- **Discovered by:** A

#### F-WN-25-15  [P3] — `_sync_folders()` is only called once, at startup

- **File:** `services/watchdog_service.py:89-95`, `:104-116`
- **Confirmed:** yes
- **Description:** `start()` calls `_sync_folders()` a single time. Nothing re-runs it, so a folder registered after startup, a folder that appears later (a removable drive, a network share that was offline), or a folder whose `auto_scan` flag is toggled is never watched until the app restarts. `_watched_paths` is never pruned either, so a folder deleted from the DB keeps its watch.
- **Cause:** the folder list is resolved once instead of being kept in sync with the DB.
- **Trigger conditions:** any runtime change to the `scan_folders` table.
- **User impact:** once F-WN-25-2 is fixed and folders can actually be registered, the watcher will still miss folders added during the session. Today the defect is latent (nothing registers folders at all).
- **Evidence:**
  ```python
  # services/watchdog_service.py:89-95
  def start(self):
      if not HAS_WATCHDOG:
          return None
      if not self.observer:
          return None
      self._sync_folders()
      self.observer.start()
  ```
  Repo-wide grep: `_sync_folders` appears only at L94 and L104.
- **Reproduction / verification:** add a row to `scan_folders` after startup and check `WatchdogService._watched_paths` — it does not change and no watch is scheduled.
- **Suggested fix:** re-run `_sync_folders()` on a timer or right after a folder-registration bridge call, and unschedule folders that disappear from the DB.
- **Fix side effects:** `observer.schedule()` on an already-watched path raises; the `_watched_paths` set must be the single source of truth for idempotency.
- **Discovered by:** A

#### F-WN-25-16  [P3] — `observer.join()` raises when `start()` never ran

- **File:** `services/watchdog_service.py:97-102`
- **Confirmed:** yes
- **Description:** `stop()` unconditionally calls `self.observer.join()`. If `start()` was never called (or raised before `observer.start()`), joining a thread that was never started raises `RuntimeError: cannot join thread before it is started`. `AppCore.cleanup` wraps the call in `_step(...)` (`core/app.py:522-526, 541-542`), so the exception is swallowed and logged — no crash — but the teardown step is reported as failed.
- **Cause:** `stop()` assumes `start()` succeeded.
- **Trigger conditions:** `WatchdogService.start()` raising before `self.observer.start()` (e.g. `_sync_folders()` raising) — `AppCore.__init__` catches that and continues (`core/app.py:162-165`).
- **User impact:** a spurious "Cleanup step 'watchdog.stop' failed" warning in `~/.nedotify/logs/app.log`; no functional impact.
- **Evidence:**
  ```python
  # services/watchdog_service.py:97-102
  def stop(self):
      if self.handler:
          self.handler.stop()
      if self.observer:
          self.observer.stop()
          self.observer.join()
  ```
  Verified: `join() on never-started observer RAISES: RuntimeError cannot join thread before it is started`.
- **Reproduction / verification:** `obs = Observer(); obs.join()` → RuntimeError (see `%TEMP%\opencode\wn25_watchdog.py`).
- **Suggested fix:** track a `self._started` flag (or check `self.observer.is_alive()`) before joining.
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-25-17  [P3] — The day buckets use one fixed UTC offset for the whole window (no DST handling), and the period boundaries are not local calendar days

- **File:** `services/listening_comparison.py:23-25`, `:42-45`
- **Confirmed:** yes
- **Description:** The `daily` grouping applies a single modifier, `f'{offset:+d} minutes'`, to every row in the window, and the frontend supplies the *current* offset (`-new Date().getTimezoneOffset()`, `ui/web_new_v2/js/profile-comparison.js:33`). For a window that spans a DST change, the local-day boundaries are off by one hour for part of the range. Separately, the windows themselves are exact UTC spans (`moment - timedelta(days=days)`), so "Последние 7 дней" means "the last 168 hours from now", not "the last 7 local calendar days".
- **Cause:** a fixed offset instead of a per-instant local offset; the window is anchored to "now" rather than to a local midnight.
- **Trigger conditions:** a DST-observing timezone (the default +180 does not observe DST) and a period that straddles a transition.
- **User impact:** one day in the daily chart is split or merged around the transition hour; the current/previous windows are not aligned to the user's day boundaries. Low severity for the shipped default.
- **Evidence:**
  ```python
  # services/listening_comparison.py:23-25
  current_start = moment - timedelta(days=days)
  previous_start = current_start - timedelta(days=days)
  modifier = f'{offset:+d} minutes'
  ```
  ```python
  # services/listening_comparison.py:42-45
  SELECT date(played_at, ?) AS day, COUNT(*) AS plays, SUM(duration_listened) AS seconds
  FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
  GROUP BY day ORDER BY day
  ```
  The SQLite modifier itself is correct for a fixed offset (verified: `'+180 minutes'` → `2026-10-16`, `'-330 minutes'` → `2026-10-15`, `'+0 minutes'` → `2026-10-15`).
- **Reproduction / verification:** run `listening_comparison(db, 'year', -300)` (a DST zone) with plays recorded around the transition instant and observe the day bucket shift.
- **Suggested fix:** derive the offset per row from the stored instant (e.g. a `local_tz` table or a zone-aware helper) instead of a single constant, and anchor the windows to local midnights if calendar alignment is intended.
- **Fix side effects:** a per-row offset makes the `daily` GROUP BY non-indexable, which interacts with F-WN-25-1 (the query cost problem) — fix that first.
- **Discovered by:** A

#### F-WN-25-18  [P3] — The Profile page shows two different "week" play counts (comparison vs. wrapped stats)

- **File:** `services/listening_comparison.py:29-33` (mine) vs. `core/database.py:1736-1746` (owner: WN-12) and `core/api.py:3156-3159` (owner: WN-08)
- **Confirmed:** yes
- **Description:** `listening_comparison` counts only rows with `duration_listened > 0`. `get_wrapped_stats` counts **every** history row in the period and substitutes `t.duration` (or 180 s) for rows with zero measured time. The two widgets are rendered on the same Profile page (`ui/web_new_v2/js/profile.js:63` and `ui/web_new_v2/js/profile-comparison.js:33`), so the user sees two different "plays"/"time" numbers for the same period. The comparison panel does state "Учитываем фактически прослушанное время", so the difference is documented — but the wrapped-stats panel does not say that it counts skips.
- **Cause:** two independent definitions of "listening time" in the same UI surface.
- **Trigger conditions:** any user with skipped tracks (a row with `duration_listened = 0`).
- **User impact:** the user cannot reconcile the two numbers and may distrust the statistics. No crash or data loss.
- **Evidence:**
  ```python
  # services/listening_comparison.py:29-33
  SELECT COUNT(*) AS plays, COALESCE(SUM(MAX(0, duration_listened)), 0) AS seconds, ...
  FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
  ```
  ```python
  # core/database.py:1736-1746  (owner: WN-12)
  SELECT COUNT(h.id) as total_plays,
         COALESCE(SUM(CASE WHEN h.duration_listened > 0 THEN h.duration_listened
                           WHEN t.duration > 0 THEN t.duration ELSE 180.0 END), 0) as total_sec
  FROM history h LEFT JOIN tracks t ON h.track_id = t.id {where_clause}
  ```
- **Reproduction / verification:** insert one history row with `duration_listened = 0` and compare `get_wrapped_stats('week')['total_plays']` with `listening_comparison(db,'week')['current']['plays']`.
- **Suggested fix:** align the two definitions in one place (the counting rule belongs to WN-12's `get_wrapped_stats`); until then, label the comparison panel's rule in the wrapped-stats panel too.
- **Fix side effects:** changing `get_wrapped_stats` alters the numbers the Home/Profile "wrapped" widgets have shown since the feature shipped.
- **Discovered by:** A (root cause attributed to WN-12 / WN-08 — not re-reported there)

### 3. Clean areas

- **Tuple order of `analyze_lufs` is correct.** The function returns `(loudness, peak, error)` (`services/lufs_scanner.py:33`) and the only caller unpacks it the same way (`services/lufs_scanner.py:87` → `lufs, peak, err = future.result()`). `core/api.py::_enrich_track_lufs` (L1161-1193) does **not** call `analyze_lufs` at all — it reads the DB columns — so there is no cross-module order mismatch. `_enrich_track_lufs` also correctly prefers `loudness_lufs` over `lufs` and uses `is not None` (not truthiness), so a legitimate `0.0` is not discarded.
- **`analyze_lufs` exception handling is otherwise sound**: every failure is converted to `(None, None, message)` and the message is logged by the caller — no exception escapes to the thread. The `del decoded` at L29 does release the int16 PCM (verified by `tests/test_lufs_resources.py:21-56`), so the *decoded* buffer is not leaked.
- **The fingerprint algorithm is deterministic and cheap**: for files ≤ 192 KB it hashes the whole file; for larger files it hashes head+mid+tail; `full_hash` is computed consistently with the branch actually taken; at most 192 KB is read per file, so memory and I/O are trivial. It is **not** dead code — it is reachable from `core/api.py:3876-3882` (Settings → "Сканирование медиатеки на дубликаты") and the delete path is reachable from `core/api.py:3884-3905`.
- **`AudioFingerprintService` handles a missing file** (`compute_file_fingerprint` returns `None`, L28-29) and `find_duplicates` skips rows without an existing path (L79-80) — no exception, no crash.
- **`find_duplicates` uses `dict` rows correctly**: `get_all_tracks` returns `List[Dict]` (`core/database.py:1209`), so `track.get("file_path")` is valid.
- **The duplicate-delete path reports partial failure correctly when the FILE removal fails**: `core/api.py:3892-3903` re-checks `os.path.exists(file_path)` and returns `{"success": False, "partial": True, ...}` — the inverse of F-WN-25-8 is handled.
- **Bridge field names/types match the frontend** for both features:
  - LUFS → `loudness_lufs` and `lufs` (float) — consumed as `track.loudness_lufs ?? track.lufs` in `ui/web_new_v2/js/player.js:725, 1649`. The only type problem is the non-finite value (F-WN-25-6).
  - Fingerprint groups → `group_id`, `signature`, `match_confidence`, `count`, `tracks[]` with `fingerprint`, `file_size_bytes`, `full_hash` — the UI reads `group.match_confidence`, `track.title`, `track.artist`, `track.file_size_bytes`, `track.id`; all are present (`ui/web_new_v2/js/settings.js:3302-3331`).
  - Comparison → `period`, `days`, `utc_offset_minutes`, `current/previous.{start,end,plays,seconds,tracks,top_artists,daily}`, `delta.<key>.{absolute,percent}`, `new_artists`, `returning_artists` — the UI reads `current.seconds/plays/tracks`, `delta.*.absolute/percent`, `current.top_artists[].{artist,seconds}`, `new_artists[].artist`, `returning_artists[].artist`, `days`; all present (`ui/web_new_v2/js/profile-comparison.js:12-22`).
- **`listening_comparison` window arithmetic is correct**: two equal, non-overlapping, half-open windows `[current_start, moment)` and `[previous_start, current_start)`; `_stamp` renders UTC `'%Y-%m-%d %H:%M:%S'`, which is exactly the format SQLite's `CURRENT_TIMESTAMP` writes, so the string comparison in SQL is lexicographically correct (verified). The `date(played_at, '+NNN minutes')` modifier is valid SQLite for every offset the function accepts (verified for +180, -330, +0, -720, +840).
- **No `ZeroDivisionError` / `inf` in the percentage calculation**: `percent = round((after - before) / before * 100, 1) if before else None` (`services/listening_comparison.py:54`) returns `None` for a zero baseline, and the UI renders `null` as "Раньше прослушиваний не было" (`ui/web_new_v2/js/profile-comparison.js:7`). The empty case is safe and pinned by `tests/test_listening_comparison.py:32-36`.
- **No naive/aware datetime mixing**: `moment` is forced aware (`services/listening_comparison.py:19-21`) and every value passed to `_stamp` derives from it, so `astimezone()` never has to guess a local zone. `_stamp` itself would silently treat a naive argument as local time, but it is a private helper with a single call site.
- **Period and offset validation** is explicit and correct: an unknown period or an out-of-range offset raises `ValueError` with a Russian message (`:14-18`); the UI's `<select>` only offers week/month/year (`ui/web_new_v2/index.html:648`), matching `_DAYS`.
- **The LUFS scan does not run on the bridge/UI thread**: `LufsScannerService.start()` spawns a daemon thread (`services/lufs_scanner.py:50`) and the pool has `max_workers=1`, so at most one decode is in flight (`tests/test_lufs_resources.py:88-108` pins the serialisation). The scan loop's outer `try/except` prevents a hot error loop.
- **The watchdog observer thread is a daemon** (`watchdog.observers.api.BaseThread` sets `daemon = True`; verified at runtime), so it does not keep the process alive; `WatchdogService.stop()` stops and joins it, and `AppCore.cleanup()` calls it (`core/app.py:541-542`). The `AudioFileHandler._processor_thread` is also a daemon and `stop()` makes it exit within ~1 s.
- **The `AudioFileHandler` pending map is correctly lock-protected** (`services/watchdog_service.py:49-50`, `:57-66`): the dict is only mutated under `self._lock`, and the callback is invoked **outside** the lock, so a slow import cannot block the watcher thread.
- **The LUFS/fingerprint services do not touch the user's `~/.nedotify/` tree directly** except through the DB — no file is deleted by the LUFS scanner, and the fingerprint service only deletes a file when explicitly asked with `delete_file=True`.
- **`core/api.py::get_listening_comparison` and `find_duplicate_tracks` are exception-safe at the bridge level**: `find_duplicate_tracks` catches everything and returns `[]` (`core/api.py:3880-3882`); `get_listening_comparison` lets `ValueError` propagate, which the UI catches and renders as "Не удалось сравнить периоды" (`ui/web_new_v2/js/profile-comparison.js:37-38`).

### 4. Coverage gaps

- **pywebview is not installed in `.venv_win`**, so I could not inspect the exact bridge dispatch/serialisation code of the pinned version. The claim that "bridge calls run on a bridge thread and the JS promise stays pending" is taken from `STATUS.md:188` and `core/api.py:1141-1154` (the app's own contract), not from the library source. Whether a `json.dumps`-ed `-Infinity` survives the real pywebview return path (it is embedded as a JS literal, not parsed as strict JSON) is therefore a **hypothesis**; the confirmed part is that `-inf` is persisted in the DB and that `json.dumps(..., allow_nan=False)` rejects it.
- **I did not run the real app** (per the ground rules) and did not touch `~/.nedotify/`. All measurements used synthetic databases and generated WAV files under `%TEMP%`.
- **The false-positive rate of the sampled fingerprint was not quantified** — I demonstrated the *mechanism* (a 90 %-confidence group whose delete button removes the file) but did not construct a real 192 KB collision between two distinct songs, so F-WN-25-13 remains a mechanism-level finding, not a measured data-loss event.
- **Long-running watchdog behaviour was not exercised end-to-end** with a real observer + real file copies (the observer currently has no folders to watch, see F-WN-25-2). The Windows share-mode behaviour and the handler's debounce were verified directly against `AudioFileHandler`, but the full "copy a file into a watched folder" path could not be exercised.
- **The `new_artists` performance finding was measured on synthetic data** (120 000 uniformly-spread history rows over 400 days, 200 artists). Real histories are more clustered, so the absolute numbers will differ; the *shape* of the cost (outer rows × pre-window history scan) is what the finding rests on, and it is confirmed by the query plan.
- **I did not audit `core/database.py::get_wrapped_stats` or `core/api.py:3156` beyond the comparison in F-WN-25-18** — those belong to WN-12 / WN-08, and the `180.0`-per-skip rule and the `date(played_at, ...)` bucketing there were not reviewed in depth.
- **The `tools/bench/pyprof_child.py` hooks** for these four modules were not executed (they need the real app's startup path).
