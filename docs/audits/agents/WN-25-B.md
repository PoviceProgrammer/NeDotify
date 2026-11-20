## AREA WN-25 — Loudness scan, audio fingerprint, watchdog, listening comparison — ROLE B

### 1. Scope reviewed

**Files opened (read in full):**
- `services/lufs_scanner.py` (1–109)
- `services/audio_fingerprint_service.py` (1–134)
- `services/watchdog_service.py` (1–129)
- `services/listening_comparison.py` (1–84)
- `docs/audits/WIN_AUDIT_CONTEXT.md` (1–200), `docs/audits/WIN_AUDIT_AREAS.md` (1–70)

**Callers / callees traced into other areas:**
- `core/app.py` — L23, 28, 32 (imports), 143–145 (construction), 161–171 (start), 508–560 (`cleanup()`), 543–544 (`lufs_scanner.stop`), 541–542 (`watchdog.stop`), 559–560 (`db.close`)
- `core/api.py` — L1161–1193 (`_enrich_track_lufs`), 2532–2543, 2545–2591, 3156–3171 (`get_wrapped_stats`), 3436–3459 (`open_local_file` → `scan_single_file`), 3876–3908 (`find_duplicate_tracks` / `delete_duplicate_track`), 4223–4225 (`get_listening_comparison`), 1122–1159 (`_emit` thread guard)
- `core/database.py` — L155–205 (thread-local connection), 274–294 (`history` table + indexes), 1184–1209 (`get_all_tracks`), 1723–1834 (`get_wrapped_stats`), 2244–2267 (`scan_folders`), 2413–2489 (`close_thread_connection` / `close`)
- `utils/file_scanner.py` — L19–23 (`is_audio_file`), 41–56, 58–109 (`scan_folder`), 111–155 (`_import_file`)
- `ui/web_new_v2/js/profile-comparison.js` (1–56), `js/profile.js` (40–119), `js/home.js` (897–905), `js/player.js` (18, 716–737, 1649–1653), `js/settings.js` (280–301, 3260–3346), `ui/web_new_v2/index.html` (648)
- Third-party (read to establish the contract): `.venv_win/Lib/site-packages/pyloudnorm/meter.py` (28–107), `pyloudnorm/iirfilter.py` (157–170), `miniaudio.py` (1233–1259), `watchdog/utils/__init__.py` (`BaseThread`), `watchdog/observers/api.py` (261–392), `webview/http.py` (57–155)

**Callees whose defect belongs to another area (not double-reported here):**
- `core/database.py::get_wrapped_stats` `ELSE 180.0` / `t.duration` fabrication → owner **WN-12** (surfaced here only as the *divergence* between two screens, F-WN-25-2).
- `utils/file_scanner.py:148-152` and `utils/cache_manager.py:255-265` writing outside `db._write_lock` → owner **WN-27**; the LUFS writer's own instance of the same pattern is F-WN-25-11.
- `core/api.py::_enrich_track_lufs` → owner **WN-05/WN-06** (called from there; the values it enriches are produced here).

**Environment used for measurements:** `.venv_win\Scripts\python.exe` (3.14.7), watchdog 5.0.3, numpy/pyloudnorm/miniaudio/scipy as installed. All probes were scratch files under `%TEMP%\opencode`; no repo file was modified; `~/.nedotify/` was never touched.

---

### 2. Findings

#### F-WN-25-1  [P1] — `listening_comparison` runs a correlated subquery per history row; the "365 days" comparison takes 7.8 minutes on a 120 k-row history

- **File:** `services/listening_comparison.py:56-66`, `services/listening_comparison.py:67-81`; caller `core/api.py:4223-4225`; UI `ui/web_new_v2/js/profile-comparison.js:33,44-50`
- **Confirmed:** yes
- **Description:** The `new_artists` and `returning_artists` queries each embed a correlated `EXISTS` / `NOT EXISTS` subquery over `history JOIN tracks` whose only usable index is `idx_history_played_at` and whose join predicate `LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist))` is an unindexed expression. SQLite evaluates the subquery **once per outer row**, not once per artist group, and `LIMIT 10` is applied only *after* the `GROUP BY`, so it removes none of the work.
- **Cause:** the "artist seen before / not seen before" set is recomputed by re-joining the whole history table for every candidate row instead of being materialised once (e.g. one `SELECT DISTINCT LOWER(TRIM(artist)) … WHERE played_at < ?` anti-joined in memory, or an indexed artist key).
- **Trigger conditions:** any history table larger than a few thousand rows, and any user whose history **spans more than the comparison window** (i.e. anyone who has had the app for longer than the selected period). The "Последние 365 дней" option is a plain `<option value="year">` in `index.html:648` and the query runs on every panel open and every period change.
- **User impact:** the Profile panel "Сравнить периоды прослушивания" spins for **8 minutes** on a 120 k-row library (year) and 12 seconds (week). The bridge call occupies a Bottle worker thread for the whole time (`webview/http.py:57-73` is a `ThreadingMixIn` server, so other calls still work, but the panel never resolves). The user is told nothing until it finishes or the JS `await` is abandoned.
- **Evidence:**
  ```python
  # services/listening_comparison.py:56-66
  AND NOT EXISTS (
      SELECT 1 FROM history old JOIN tracks older ON older.id = old.track_id
      WHERE old.played_at < ? AND old.duration_listened > 0
        AND LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist)))
  GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, t.artist LIMIT 10
  ```
  `EXPLAIN QUERY PLAN` on the real query returns:
  ```
  SEARCH h USING INDEX idx_history_played_at (played_at>? AND played_at<?)
  SEARCH t USING INTEGER PRIMARY KEY (rowid=?)
  CORRELATED SCALAR SUBQUERY 1
    SEARCH old USING INDEX idx_history_played_at (played_at<?)
      SEARCH older USING INTEGER PRIMARY KEY (rowid=?)
  USE TEMP B-TREE FOR GROUP BY
  ```
- **Reproduction / verification:** scratch script `%TEMP%\opencode\wn25_probe12.py` builds a temp DB with 400 artists / 2 000 tracks and a history spread over 1 095 days, then times `listening_comparison(db, period, 180, now=…)`:
  | history rows | week | year |
  |---|---|---|
  | 10 000 | 0.18 s | **34.4 s** |
  | 30 000 | 3.03 s | **118.6 s** |
  | 60 000 | 6.25 s | **236.6 s** |
  | 120 000 | 11.6 s | **467.5 s** |
  A second script `%TEMP%\opencode\wn25_probe9.py` isolates the `new_artists` statement alone: **346.1 s** of the 367.3 s year total.
- **Suggested fix:** compute the "artist already present before the window" set once per call (single pass over `history JOIN tracks` restricted to `played_at < current_start`) and anti-join it in Python; alternatively pre-compute a normalised artist key column with an index. The `LIMIT 10` should also be pushed to an outer query over an aggregated sub-select so the expensive per-row subquery only runs for the 10 groups that survive.
- **Fix side effects:** materialising the artist set costs one extra full pass over the pre-window history (memory: one row per distinct artist) and changes the semantics of "new artist" from "no row for this artist" to "no row for this normalised artist" — the two must be kept identical to avoid a new divergence with `get_wrapped_stats`.
- **Discovered by:** B

#### F-WN-25-2  [P1] — Two different "total listening time" numbers are shown for the same period on the same Profile screen (1000 s vs 0 s)

- **File:** `services/listening_comparison.py:29-33` (comparison) vs `core/database.py:1736-1746` (`get_wrapped_stats`); UI `ui/web_new_v2/js/profile-comparison.js:33` and `ui/web_new_v2/js/profile.js:63` / `js/home.js:900`
- **Confirmed:** yes (the `ELSE 180.0` fabrication itself is owned by **WN-12**; the *duplication and the resulting visible divergence* are owned here)
- **Description:** `services/listening_comparison.py` re-implements the listening aggregation from scratch with a different definition of a "play": it filters `duration_listened > 0` and sums only measured seconds. `core/database.py::get_wrapped_stats` uses `CASE WHEN h.duration_listened > 0 THEN h.duration_listened WHEN t.duration > 0 THEN t.duration ELSE 180.0 END` and counts every `history` row. The same library therefore reports two different totals for the same week.
- **Cause:** the aggregation rule lives in two places and has already diverged; the service bypasses the persistence layer entirely and re-derives the period/boundary logic itself instead of sharing one definition.
- **Trigger conditions:** any play with `duration_listened = 0` — i.e. every skipped/paused-immediately track, which is the normal case for the "skip" gesture and for streams that fail to report position. Also any artist string that is empty-after-trim or a differently-cased `Unknown Artist`.
- **User impact:** on the Profile page the user can see "Сравнить периоды" reporting **0 прослушиваний / 0 секунд** next to the Wrapped block reporting **5 прослушиваний / 16.7 минут** for the very same five plays. The artist lists also disagree: the Wrapped block lists a blank artist (`'   '`) and `unknown artist` as top artists, the Comparison panel shows an empty list.
- **Evidence:**
  ```python
  # services/listening_comparison.py:29-33
  SELECT COUNT(*) AS plays, COALESCE(SUM(MAX(0, duration_listened)), 0) AS seconds, …
  FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
  ```
  ```python
  # core/database.py:1736-1746
  COALESCE(SUM(CASE
      WHEN h.duration_listened > 0 THEN h.duration_listened
      WHEN t.duration > 0 THEN t.duration
      ELSE 180.0
  END), 0) as total_sec
  FROM history h LEFT JOIN tracks t ON h.track_id = t.id
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe6.py` inserts 5 tracks (200 s each) with `duration_listened = 0` and prints both:
  ```
  get_wrapped_stats   : plays=5  seconds=1000.0  (16.7 min)
  listening_comparison: plays=0  seconds=0.0
  ```
  and, with artists `'unknown artist'`, `'   '`, `'Unknown Artist'`:
  ```
  get_wrapped_stats   top_artists: [('   ', 120.0), ('unknown artist', 120.0)]
  listening_comparison top_artists: []
  ```
- **Suggested fix:** move the "what counts as a play" rule into one place (the persistence layer) and have `services/listening_comparison.py` build on it, so the Wrapped block and the Comparison panel cannot disagree; align the artist-normalisation predicate (`TRIM` + case-fold + the `unknown artist` bucket) with the same helper.
- **Fix side effects:** fixing `get_wrapped_stats` to use only measured time will make the Wrapped totals drop for users who skipped many tracks (the numbers were inflated) — that is a product-visible change and belongs to WN-12, not to this area.
- **Discovered by:** B

#### F-WN-25-3  [P1] — The WatchdogService watches nothing: the `scan_folders` table it reads is never populated by the current code

- **File:** `services/watchdog_service.py:104-116` (`_sync_folders`), `services/watchdog_service.py:118-129` (`_on_new_file`); producer `utils/file_scanner.py:99` (`self.db.add_scan_folder(folder_path)`) inside `utils/file_scanner.py:58-109` (`scan_folder`); table `core/database.py:331-335`, insert `core/database.py:2250`
- **Confirmed:** yes
- **Description:** `WatchdogService._sync_folders()` reads the `scan_folders` table and schedules a watch for each row with `auto_scan`. The only `INSERT INTO scan_folders` in the whole repository is `core/database.py:2250` (`add_scan_folder`), and its only caller is `utils/file_scanner.py:99`, inside `FileScanner.scan_folder()`. `scan_folder()` has **no production caller** (`rescan_all_folders()` at `utils/file_scanner.py:157` is the only other caller and it has none either; no bridge method calls it — `core/api.py` only calls `scan_single_file` at :3449). Consequently, on any database created by the current code the table is empty, `db_paths` is the empty set, and the observer is scheduled with **zero watches**.
- **Cause:** the folder-registration entry point was removed or never wired to the bridge, but the watcher, its handler, its polling thread and the `watchdog` runtime dependency were all kept and are still started at boot.
- **Trigger conditions:** always, for every install whose `scan_folders` table is empty (i.e. every fresh install; only a legacy DB that already contains rows would still watch anything).
- **User impact:** the "auto-import new files from my music folder" capability does not exist: no new file is ever detected, `_on_new_file` is never called, and `library_updated` is never emitted from this path. Meanwhile the app still pays the cost of the subsystem: a 1 Hz polling thread, an observer thread, the `watchdog>=4.0.0,<6` runtime dependency (`requirements.txt`), and 129 lines of code that the project's own profile attributes **0.0775 % of one core and 0.9932 wake-ups/second** (`docs/perf/prof_python_startup.md:479, 546`).
- **Evidence:**
  ```python
  # services/watchdog_service.py:104-116
  def _sync_folders(self):
      folders = self._core.db.get_scan_folders()
      db_paths = {f['folder_path'] for f in folders if f.get('auto_scan')}
      for path in db_paths:
          if path not in self._watched_paths:
              if not os.path.isdir(path):
                  continue
              try:
                  self.observer.schedule(self.handler, path, recursive=True)
  ```
  ```python
  # utils/file_scanner.py:99 (inside scan_folder, which nothing calls)
  self.db.add_scan_folder(folder_path)
  ```
- **Reproduction / verification:** `rg "scan_folder\(|rescan_all_folders|add_scan_folder" --type py` over the repo (excluding `android/`) returns only the definitions above plus `core/database.py:2244` — no production call site. Reproduce at runtime: open a fresh `~/.nedotify/nedotify_storage.db`, `SELECT COUNT(*) FROM scan_folders` → 0, and `WatchdogService(self).observer._watches` → empty set, while `AudioFileHandler._processor_thread` is alive and ticking at 1 Hz.
- **Suggested fix:** either wire a real "add watched folder" bridge method that calls `db.add_scan_folder()` and then re-syncs the observer, or delete `services/watchdog_service.py`, its start/stop wiring in `core/app.py`, and the `watchdog` dependency.
- **Fix side effects:** restoring the feature means the recursive watch (`recursive=True`) and the `_import_file` path become live, so the debounce/locking behaviour of F-WN-25-13 and the private-method coupling of F-WN-25-14 must be fixed first; removing the feature changes the `requirements.txt`/installer contents.
- **Discovered by:** B

#### F-WN-25-4  [P1] — LUFS analysis decodes the whole file and holds ~32 bytes per audio frame in RAM: +424 MB for a 5-minute track, +4.7 GiB for a one-hour file

- **File:** `services/lufs_scanner.py:16-35` (`analyze_lufs`), `services/lufs_scanner.py:80` (submit to the pool)
- **Confirmed:** yes
- **Description:** `analyze_lufs` decodes the **entire** file into an `array('h')` of int16 PCM, copies it into a `float32` numpy array, and then hands the whole array to `pyln.Meter.integrated_loudness`, which itself takes a **full copy** and then promotes the signal to `float64` twice (once inside `scipy.signal.lfilter`, once for the `passband_gain` multiply). Nothing is chunked and there is no streaming path. Peak resident memory is therefore ≈ 32 bytes per frame (8 float32 source + 8 float32 copy + 8 float64 lfilter output + 8 float64 scaled output) on top of the file's own decoded buffer, and it scales linearly with the file length.
- **Cause:** the decoder (`miniaudio.decode_file`, whole-file API) and the meter (`pyloudnorm`, whole-array API) both require the complete signal; the service never bounds the input, never resamples down, and never limits the duration it feeds in.
- **Trigger conditions:** any local track in the library. `miniaudio.decode_file` defaults to `nchannels=2, sample_rate=44100`, so the cost is identical for a mono file and a 5.1 file: **44100 frames/s × 2 ch**.
- **User impact:** a single long file can push the whole app process to ~5 GB RSS and trigger a MemoryError / page-file thrash on a 8–16 GB machine; the scanner keeps no bound and processes the next file immediately afterwards.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:23-33
  decoded = miniaudio.decode_file(filepath)
  audio_data = np.asarray(decoded.samples, dtype=np.float32)
  audio_data /= 32768.0
  …
  del decoded
  meter = pyln.Meter(rate)
  loudness = meter.integrated_loudness(audio_data)
  ```
  ```python
  # .venv_win/Lib/site-packages/pyloudnorm/meter.py:54
  input_data = data.copy()
  # .venv_win/Lib/site-packages/pyloudnorm/iirfilter.py:170
  return self.passband_gain * scipy.signal.lfilter(self.b, self.a, data)   # b/a are float64 -> float64 output
  ```
  ```python
  # .venv_win/Lib/site-packages/miniaudio.py:1233-1239
  def decode_file(filename, output_format=SampleFormat.SIGNED16, nchannels=2, sample_rate=44100, …)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe5.py` (peak RSS sampled every 5 ms via `psutil`, modules pre-imported so the measurement isolates the audio data):
  | file | wall time | peak RSS delta | bytes/frame | max UI-thread stall |
  |---|---|---|---|---|
  | 300 s stereo 44.1 kHz WAV (52.9 MB) | 0.81 s | **+423.8 MB** | 32.0 | 16.8 ms |
  | 900 s stereo 44.1 kHz WAV (158.8 MB) | 4.62 s | **+1 267.3 MB** | 31.9 | 77.6 ms |
  Linear extrapolation from the measured 32.0 B/frame: **10 min → +848 MB**, **60 min → +5 086 MB (4.74 GiB)**. The measured curve is exactly linear (31.9 and 32.0 B/frame at two different lengths).
- **Suggested fix:** bound the analysis (decode at a reduced sample rate / mono, and cap the analysed duration, e.g. the first N minutes, which is what ReplayGain reference tools do), or stream the decode (`miniaudio.decode_file_stream`) into fixed-size blocks and implement the BS.1770 gating block accumulation yourself instead of calling `pyln.Meter.integrated_loudness` on the whole array.
- **Fix side effects:** a duration cap changes the measured LUFS for long files (a podcast would be measured on its first minutes only) and the reference value must then be documented; streaming means re-implementing the gating algorithm, which must be validated against `pyloudnorm` to keep the existing numbers.
- **Discovered by:** B

#### F-WN-25-5  [P2] — Failed analyses write fabricated loudness values into the DB, and those values drive the ReplayGain playback gain

- **File:** `services/lufs_scanner.py:78-82`, `services/lufs_scanner.py:86-95`; consumer `ui/web_new_v2/js/player.js:18, 725-729, 1649-1653`
- **Confirmed:** yes
- **Description:** Two different failure modes are recorded as if they were measurements. A track whose file is missing is written as `lufs = 0.0`; a track whose file cannot be decoded is written as `lufs = -14.0, peak_volume = 1.0`. Both are indistinguishable from a real measurement in the DB and in every API response. The frontend then uses the value to compute the playback gain: `currentReplayGain = clamp(10^((TARGET_LUFS - lufs)/20), 0.1, 2.0)` with `TARGET_LUFS = -14.0`.
- **Cause:** the scanner's work queue is "`lufs IS NULL`", so any non-NULL value — including a placeholder — marks the row as done. The failure path has no separate "error" column, so a placeholder is the only way to stop the retry loop.
- **Trigger conditions:** a local file that was moved/deleted (the DB row survives), a file on a disconnected drive, an unreadable/corrupt file, or any codec miniaudio cannot decode. The `lufs = 0.0` case is the dangerous one.
- **User impact:** a track stored with `lufs = 0.0` is played at `10^((-14-0)/20) = 0.1995` of the user's volume — i.e. **14 dB / 5× too quiet**, with no indication in the UI. The `lufs = -14.0` case yields gain 1.0 (silently no normalisation), and both values are permanently cached (never retried).
- **Evidence:**
  ```python
  # services/lufs_scanner.py:78-82
  if os.path.exists(filepath):
      futures[self._pool.submit(analyze_lufs, filepath)] = track_id
  else:
      self._update_db(track_id, 0.0, 0.0)          # <-- 0.0 LUFS is a real-looking value
  # services/lufs_scanner.py:90-95
  else:
      logger.error(f'LUFS scan failed for track {track_id}: {err}')
      self._update_db(track_id, -14.0, 1.0)         # <-- fabricated -14 LUFS / peak 1.0
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:18, 725-729
  const TARGET_LUFS = -14.0;
  currentReplayGain = Math.min(2.0, Math.max(0.1, Math.pow(10, (TARGET_LUFS - Number(trackLufs)) / 20)));
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe7.py` (section c) drives `LufsScannerService._update_db` exactly as the scan loop does for a missing file and an undecodable file and dumps the rows:
  ```
  {'id': 1, 'title': 'Missing', 'lufs': 0.0, 'loudness_lufs': 0.0, 'peak_volume': 0.0}
  {'id': 2, 'title': 'Broken',  'lufs': -14.0, 'loudness_lufs': -14.0, 'peak_volume': 1.0}
  ```
  Both rows now satisfy `lufs IS NOT NULL` and are never re-analysed.
- **Suggested fix:** store the failure separately (leave `lufs` NULL and record the error in a dedicated column or a `lufs_status` field), and make the frontend fall back to gain 1.0 whenever the loudness is absent or flagged as failed; if a placeholder must be kept, it must be outside the range of valid LUFS values and must be rejected by the player.
- **Fix side effects:** changing the schema means a migration for the two existing columns; existing rows that already contain the `-14.0`/`0.0` placeholders are indistinguishable from real measurements and would need a one-off scrub.
- **Discovered by:** B

#### F-WN-25-6  [P2] — `miniaudio.decode_file`'s default stereo output inflates every mono track by exactly +3.01 dB

- **File:** `services/lufs_scanner.py:23` (`miniaudio.decode_file(filepath)` — no `nchannels`/`sample_rate` arguments)
- **Confirmed:** yes
- **Description:** `miniaudio.decode_file` defaults to `nchannels=2, sample_rate=44100`. A mono source is therefore up-mixed to dual-mono, and the BS.1770 channel-weighted sum over L+R counts the same signal twice: the measured integrated loudness is **3.01 dB higher** than the correct mono measurement. The value is then used as the ReplayGain reference, so every mono track is normalised against a wrong target.
- **Cause:** the decode call does not state the channel layout it intends to measure; the measurement basis is an accident of a third-party default rather than an explicit contract.
- **Trigger conditions:** every mono local file (voice tracks, podcasts, mono rips) — and, separately, every file whose native rate is not 44 100 Hz, which is silently resampled before the measurement.
- **User impact:** mono tracks are played ~3 dB (1.41×) quieter than they should be relative to correctly-measured stereo tracks, because the player computes the gain from the inflated value (`10^((-14-(-12.97))/20) = 0.888` instead of `10^((-14-(-15.98))/20) = 1.256`). The 48 kHz resample adds a further small error (+0.215 dB measured on a 48 kHz test signal) and costs CPU on every file.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:23-28
  decoded = miniaudio.decode_file(filepath)      # defaults: nchannels=2, sample_rate=44100
  audio_data = np.asarray(decoded.samples, dtype=np.float32)
  …
  rate = decoded.sample_rate
  ```
  ```python
  # .venv_win/Lib/site-packages/miniaudio.py:1233-1239
  def decode_file(filename, output_format=SampleFormat.SIGNED16, nchannels=2, sample_rate=44100, …)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe8.py` writes a 5 s mono 44.1 kHz WAV and measures it two ways:
  ```
  miniaudio: nchannels=2 rate=44100
    L channel == R channel ? True
    LUFS as measured by analyze_lufs (stereo path): -12.97
    LUFS measured correctly on the MONO signal:    -15.98
    ERROR introduced by the forced stereo upmix:    +3.01 dB
  ```
  and a 48 kHz stereo file: `source rate 48000 -> miniaudio rate 44100`, `LUFS at the native 48000 Hz: -13.19 (delta +0.215 dB)`.
- **Suggested fix:** decode with the source's real channel layout (probe the file first, or pass `nchannels=1`/the native count) and measure at the native rate, or state explicitly in the service contract that only stereo 44.1 kHz is supported and reject other layouts instead of silently mis-measuring them.
- **Fix side effects:** changing the measurement basis invalidates every LUFS value already stored (`tracks.lufs`, `tracks.loudness_lufs`); the column would need re-analysis and the stored values re-validated against the new basis.
- **Discovered by:** B

#### F-WN-25-7  [P2] — `LufsScannerService.stop()` does not wait for the in-flight analysis; the result is written to a closed database and silently lost

- **File:** `services/lufs_scanner.py:53-56` (`stop`), `services/lufs_scanner.py:80-95` (in-flight completion), `core/app.py:543-544` (stop) and `core/app.py:559-560` (`db.close`)
- **Confirmed:** yes (the code path is deterministic; the precise exception text is inferred, the loss of the result is verified by reading the code)
- **Description:** `stop()` calls `self._pool.shutdown(wait=False, cancel_futures=True)`. `cancel_futures=True` cancels *queued* work only; the analysis that is currently running keeps going (up to several seconds for a long file) and the `_scan_loop` thread is still inside `as_completed(futures)`. `cleanup()` then continues and reaches `self.db.close()` (`core/app.py:559-560`), which closes **every** connection in `_all_conns`, including the LUFS thread's own thread-local connection (`core/database.py:2459-2489`). When the analysis finally returns, `_update_db` executes against a closed connection, the `sqlite3.ProgrammingError` is swallowed by the bare `except Exception` at `services/lufs_scanner.py:108-109`, and the measurement is thrown away.
- **Cause:** `stop()` is asynchronous and the shutdown order does not wait for the worker; the LUFS thread has no shutdown handshake with the database layer.
- **Trigger conditions:** the user closes the window while a loudness analysis is in progress — i.e. any time the app is closed in the first minutes after it imported local files.
- **User impact:** the analysis is paid for and thrown away; the track stays `lufs IS NULL` and is analysed again on the next launch (repeated minutes of CPU). The failure is invisible: it is logged at `error` level as "Failed to update LUFS DB".
- **Evidence:**
  ```python
  # services/lufs_scanner.py:53-56
  def stop(self):
      self._running = False
      if self._pool:
          self._pool.shutdown(wait=False, cancel_futures=True)
  ```
  ```python
  # core/database.py:2459-2482  (close() closes every tracked connection)
  with self._conns_lock:
      for conn in list(self._all_conns):
          conn.close()
  ```
- **Reproduction / verification:** start the scanner on a library with pending local tracks, then call `AppCore.cleanup()` while `analyze_lufs` is running; observe `sqlite3.ProgrammingError: Cannot operate on a closed database` in `~/.nedotify/logs/app.log` under the message "Failed to update LUFS DB", and `SELECT lufs FROM tracks` still `NULL`. (Not executed here: the instructions forbid touching `~/.nedotify/`; the code path above is deterministic.)
- **Suggested fix:** make `stop()` bounded and cooperative — signal the loop, wait (with a timeout) for the current analysis, and skip the DB write if the database is closing; or have the scan loop check a shutdown flag before `_update_db`.
- **Fix side effects:** a bounded wait lengthens the shutdown by up to one analysis; it must be capped so a long file cannot delay the exit.
- **Discovered by:** B

#### F-WN-25-8  [P2] — `AudioFingerprintService` is a byte-sample hash, not an audio fingerprint: it cannot find the same song in two encodings and its "confidence" is a constant

- **File:** `services/audio_fingerprint_service.py:1-4` (docstring), `services/audio_fingerprint_service.py:26-61` (`compute_file_fingerprint`), `services/audio_fingerprint_service.py:99-110` (confidence)
- **Confirmed:** yes
- **Description:** The service hashes the **raw file bytes** at three sampled offsets (first 64 KiB, middle 64 KiB, last 64 KiB) and combines the digest with the file size. It never decodes audio, so: (a) the same song stored as MP3 and as FLAC has completely different bytes and is **not** detected as a duplicate — the primary use case; (b) the module docstring's claim that the fingerprint is "MD5 content hash + file size + **audio duration**" is false — the duration is not part of it; (c) the reported `match_confidence` is not a similarity measure at all: it is `100.0` when the file is ≤ 192 KiB (`"full_hash": file_size <= sample_bytes * 3`) and a hard-coded `90.0` for every real audio file. The UI renders it as "Совпадение 90 %".
- **Cause:** the algorithm was chosen as "fast and robust" against re-encoding, but it samples the container bytes, where a re-encode changes every byte, rather than the decoded signal, where it changes nothing meaningful.
- **Trigger conditions:** always. Any library that contains the same track in two formats, or a download plus a local rip, is reported as "no duplicates found".
- **User impact:** the "Сканирование медиатеки на дубликаты" feature in Settings reports a confident "90 % match" for byte-identical files and silently misses genuine duplicates. Because the same screen offers a button that **deletes the file from disk** (`ui/web_new_v2/js/settings.js:3324-3341` → `delete_duplicate_track(trackId, true)` → `os.remove(file_path)` at `services/audio_fingerprint_service.py:126`), a wrong grouping can lead the user to delete the only copy of a track.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:36-58
  with open(filepath, "rb") as f:
      head = f.read(sample_bytes)
      md5_hash.update(head)
      if file_size > sample_bytes * 3:
          f.seek(file_size // 2);  mid  = f.read(sample_bytes); md5_hash.update(mid)
          f.seek(file_size - sample_bytes); tail = f.read(sample_bytes); md5_hash.update(tail)
      …
      "full_hash": file_size <= sample_bytes * 3,
      "signature": f"{fingerprint_hash}_{file_size}"
  ```
  ```python
  # services/audio_fingerprint_service.py:104-107
  "match_confidence": (
      FULL_HASH_MATCH_CONFIDENCE if all(t.get("full_hash") for t in tracks_list)
      else SAMPLED_MATCH_CONFIDENCE      # 90.0, a constant
  ),
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe7.py` (section b) shows the digest is taken over file bytes: two files with identical audio but different container bytes hash differently, and the only way to reach the `100.0` branch is a file ≤ 192 KiB. The module's own docstring (`audio_fingerprint_service.py:1-4`) states "MD5 content hash + file size + audio duration", and `compute_file_fingerprint` returns no duration field at all (`services/audio_fingerprint_service.py:53-58`).
- **Suggested fix:** either rename the feature to what it is ("identical-file detection") and drop the fake confidence number, or compute the fingerprint from the decoded signal (e.g. a chromaprint/landmark hash of the PCM) so re-encodes match; the delete path should additionally verify that the two entries really are the same audio before offering a destructive action.
- **Fix side effects:** a signal-level fingerprint costs a full decode per file (the memory problem of F-WN-25-4 applies) or a chunked decode, and changes the matching results for existing users.
- **Discovered by:** B

#### F-WN-25-9  [P3] — The duplicate scan re-reads every local file on every button press and keeps two full copies of the track table in memory

- **File:** `services/audio_fingerprint_service.py:63-113` (`find_duplicates`), `services/audio_fingerprint_service.py:36-50` (per-file reads); caller `core/api.py:3876-3882`; UI `ui/web_new_v2/js/settings.js:284-301`
- **Confirmed:** yes
- **Description:** `find_duplicates` calls `db_manager.get_all_tracks(source="local")`, which is `SELECT * FROM tracks WHERE source = 'local'` with no limit (`core/database.py:1184-1209`) and materialises every row as a dict. It then copies each row again (`track_entry = dict(track)`, line 90) into the fingerprint map, and re-opens and re-reads 3 × 64 KiB from every file on every call. Nothing is cached between calls.
- **Cause:** the service has no persistent fingerprint store (no column on `tracks`), so the whole library is re-hashed each time the user presses the button.
- **Trigger conditions:** a large local library (the "Медиатека" is the app's own local-files area) and repeated clicks on "Сканировать дубликаты".
- **User impact:** the button re-does the full scan each time; measured 0.63 s for 2 000 tracks on a warm page cache and 0.62 s for the second identical call (no caching). Memory grows linearly with the library (two dict copies of every local track row) and the scan scales linearly with the number of files.
- **Evidence:**
  ```python
  # services/audio_fingerprint_service.py:71-94
  all_tracks = db_manager.get_all_tracks(source="local")
  …
  for track in all_tracks:
      …
      fp = self.compute_file_fingerprint(file_path)
      …
      track_entry = dict(track)          # second full copy of every row
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe7.py` (section b) creates 2 000 local tracks with real files and times two consecutive `find_duplicates` calls: `0.63s` then `0.62s` — identical, i.e. nothing is cached. (Note: the call is made on a Bottle worker thread, not the UI thread, so it does not freeze the window — but it does occupy a bridge thread and holds the GIL for the row-materialisation part.)
- **Suggested fix:** persist the fingerprint and its file size/mtime on the `tracks` row (invalidated by mtime+size) and only re-hash changed files; select only the columns the scan needs instead of `SELECT *`.
- **Fix side effects:** a new column plus a migration; the first scan after the upgrade is still O(N), and stale fingerprints must be invalidated by mtime/size or the results become wrong.
- **Discovered by:** B

#### F-WN-25-10  [P3] — The LUFS writer bypasses the database manager's write lock and transaction context

- **File:** `services/lufs_scanner.py:100-109`; convention `core/database.py:1248-1253`, `core/database.py:1561-1566` (`with self._write_lock: with self.conn:`)
- **Confirmed:** yes
- **Description:** `_update_db` executes a raw `UPDATE` + `commit()` on `self._core.db.conn` without taking `db._write_lock` and without the `with self.conn:` transaction context that every other writer in `core/database.py` uses. The project's own audit register already lists this call site: "`three production call sites write outside both` … `services/lufs_scanner.py:102-106`" (`docs/audits/_FINDINGS_SO_FAR.md:96`).
- **Cause:** the service reaches into the manager's connection instead of using a manager-level write helper; there is no API on `DatabaseManager` for "update these three columns on a track".
- **Trigger conditions:** whenever the LUFS scanner writes while another thread writes (the downloader, the cache manager, the UI thread).
- **User impact:** low in practice — the statements are single-row and SQLite's `busy_timeout=30000` absorbs the contention — but the app-level serialisation guarantee that `_write_lock` provides (it is what keeps multi-statement transactions from interleaving with other writers) is not applied here, and the LUFS write is the one that fires in bursts of 20 rows at a time.
- **Evidence:**
  ```python
  # services/lufs_scanner.py:100-109
  def _update_db(self, track_id, lufs, peak):
      try:
          self._core.db.conn.execute(
              'UPDATE tracks SET lufs = ?, loudness_lufs = ?, peak_volume = ? WHERE id = ?',
              (lufs, lufs, peak, track_id)
          )
          self._core.db.conn.commit()
  ```
  vs. the convention in `core/database.py:1248-1253`:
  ```python
  def toggle_favorite(self, track_id: int) -> bool:
      with self._write_lock:
          with self.conn:
  ```
- **Reproduction / verification:** static — `rg "_write_lock" core/database.py core/downloader.py core/download_store.py services/smart_playlists.py` shows every other writer takes the lock; `services/lufs_scanner.py` does not appear in the list. (The same pattern exists at `utils/file_scanner.py:148-152` and `utils/cache_manager.py:255-265` — those are owned by WN-27.)
- **Suggested fix:** add a manager-level method (e.g. `DatabaseManager.set_track_loudness(track_id, lufs, peak)`) that takes `_write_lock` and the transaction context, and call that from the scanner.
- **Fix side effects:** none functionally; it only serialises the write against the other writers.
- **Discovered by:** B

#### F-WN-25-11  [P3] — A single fixed UTC offset is applied to every day of the window, so the DST transition day is mis-bucketed by one hour

- **File:** `services/listening_comparison.py:25` (`modifier = f'{offset:+d} minutes'`), `services/listening_comparison.py:41-45` (`date(played_at, ?)`); caller `ui/web_new_v2/js/profile-comparison.js:33` (`-new Date().getTimezoneOffset()`)
- **Confirmed:** yes
- **Description:** The window boundaries are computed as rolling `timedelta` intervals (`current_start = moment - timedelta(days=days)`, `previous_start = current_start - timedelta(days=days)`), i.e. exactly 7 × 24 h, while the per-day buckets are computed by shifting every timestamp by **one** fixed offset taken from the browser at call time. Across a DST transition the local offset changes by one hour inside the window, so one hour of listening is attributed to the neighbouring local day, and the "week" is not a calendar week.
- **Cause:** the offset is a single scalar rather than a per-timestamp timezone conversion; the window is a fixed number of 24-hour blocks rather than a calendar period.
- **Trigger conditions:** any user in a DST timezone who opens the Profile comparison in the days after a transition (Europe: last Sunday of March and October; US: 2nd Sunday of March/November; Russia and most of Asia: no DST, so unaffected).
- **User impact:** the daily bar chart is off by one hour for the transition day, and the "7 days" window is one hour short/long of a calendar week; the headline totals are unaffected.
- **Evidence:**
  ```python
  # services/listening_comparison.py:22-25, 41-45
  days = _DAYS[period]
  current_start = moment - timedelta(days=days)
  previous_start = current_start - timedelta(days=days)
  modifier = f'{offset:+d} minutes'
  …
  SELECT date(played_at, ?) AS day, COUNT(*) AS plays, SUM(duration_listened) AS seconds
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn25_probe6.py` (case 4/5) inserts two plays around the Berlin 2026-10-25 transition and shows the same instants landing in different buckets purely because of the scalar offset:
  ```
  daily buckets with offset +60  (Berlin CET): [('2026-10-25', 2)]
  daily buckets with offset +120 (Berlin CEST): [('2026-10-25', 1), ('2026-10-26', 1)]
  ```
  and `%TEMP%\opencode\wn25_probe7.py` (a) shows the rolling window's first/last day buckets are partial: window `2026-10-08T12:00 .. 2026-10-15T12:00` → buckets `2026-10-08 (1 play)` and `2026-10-15 (1 play)`.
- **Suggested fix:** derive the per-day boundaries from a real timezone (`zoneinfo.ZoneInfo` from the browser's IANA name) instead of a fixed minute offset, and decide explicitly whether the period is a rolling interval or a calendar period.
- **Fix side effects:** switching to calendar periods changes the window boundaries and therefore the numbers shown in F-WN-25-2's comparison; the frontend would have to send an IANA zone name rather than an offset.
- **Discovered by:** B

#### F-WN-25-12  [P3] — The watchdog's handler holds its lock across a blocking file open, and `stop()` joins the observer without a timeout

- **File:** `services/watchdog_service.py:57-66` (lock held across `open()`), `services/watchdog_service.py:97-102` (`stop`), `services/watchdog_service.py:36-50` (`_add_pending` takes the same lock)
- **Confirmed:** yes for the code shape; the hang itself is a hypothesis (needs a blocking `open()`)
- **Description:** `_process_pending` holds `self._lock` while it probes each pending file with `open(path, 'rb')`. The watchdog's event thread needs the same lock in `_add_pending`, so a blocked `open()` stalls the observer thread. `WatchdogService.stop()` then calls `self.observer.join()` with **no timeout**, and `cleanup()` calls it synchronously — a blocked observer thread would hang the application shutdown.
- **Cause:** a potentially blocking I/O call is performed under a lock that the event-dispatch path also needs, and the shutdown join is unbounded.
- **Trigger conditions:** a watched folder on a disconnected network share, a USB drive that is spinning up, or a file held by a filter driver that blocks instead of failing fast. (Today this cannot be reached on a fresh install, because of F-WN-25-3; it becomes reachable the moment the folder registration is restored.)
- **User impact:** the app would not exit; the user would have to kill the process.
- **Evidence:**
  ```python
  # services/watchdog_service.py:57-66
  with self._lock:
      for path, timestamp in list(self._pending_files.items()):
          if now - timestamp >= 3.0:
              try:
                  with open(path, 'rb'):        # blocking I/O under the lock
                      ready_files.append(path)
  ```
  ```python
  # services/watchdog_service.py:97-102
  def stop(self):
      if self.handler: self.handler.stop()
      if self.observer:
          self.observer.stop()
          self.observer.join()                 # no timeout
  ```
- **Reproduction / verification:** the blocking-`open()` hang could not be reproduced here (it needs a hung network device); the code path is quoted above. The **positive** part of the shutdown chain was verified: `watchdog` 5.0.3's `BaseThread` sets `daemon = True` (`watchdog/utils/__init__.py`), `BaseObserver.on_thread_stop()` calls `unschedule_all()` (`watchdog/observers/api.py:375-376`), and `core/app.py:541-542` calls `watchdog.stop()` from `cleanup()`, which `main.py:575` runs after the window closes. The handler's own processor thread is explicitly `daemon=True` (`services/watchdog_service.py:33`).
- **Suggested fix:** do the probe `open()` outside the lock (or use `os.stat` instead), and give `observer.join()` a bounded timeout with a forced fallback.
- **Fix side effects:** moving the probe outside the lock requires a second lock acquisition to remove the entry; a bounded join may leave the observer thread running for a moment (it is a daemon, so the process still exits).
- **Discovered by:** B

---

### 3. Clean areas

- **`analyze_lufs` does not run on the bridge/UI thread.** The scan loop is a daemon thread (`services/lufs_scanner.py:50`) and the analysis runs in a dedicated `ThreadPoolExecutor(max_workers=1)` (`:44`, `:80`). The window is never frozen by the loudness scan; the measured worst-case GIL stall on the UI thread was 16.8 ms (5-min file) / 77.6 ms (15-min file).
- **The pool is genuinely serial.** `tests/test_lufs_resources.py:88-109` pins that only one analysis runs at a time, so the memory spike of F-WN-25-4 is not multiplied by the batch size of 20.
- **The decoded buffer is released promptly.** `del decoded` (`:29`) happens before the meter is created, and `tests/test_lufs_resources.py:21-56` pins this with weak references (`assert all(reference() is None for reference in decoded_refs)` inside `Meter.__init__`). The measurement confirms the int16 buffer is not held during the loudness phase.
- **The watchdog threads are daemonised and the observer is stopped on shutdown.** `AudioFileHandler._processor_thread` is `daemon=True` (`:33`); watchdog's own threads are daemons; `core/app.py:541-542` → `watchdog.stop()` → `observer.stop()` (which triggers watchdog's `unschedule_all()` → emitters stopped) and `observer.join()`. An un-stopped observer cannot keep the process alive, and `main.py:575` runs `app_core.cleanup()` after the window closes.
- **Event debouncing exists.** `AudioFileHandler` coalesces events per path with a 3 s quiet period and a 1 s poll (`:48-66`), so a download that fires dozens of write events results in **one** import, not dozens.
- **The handler does not re-scan the library.** On each settled file it calls a single `_import_file` (one tag parse + one INSERT) and emits `library_updated`; it never triggers a full DB re-scan.
- **The DB access is thread-safe.** Both the watchdog handler and the LUFS scanner reach the database only through `db.conn`, which is a `threading.local` property (`core/database.py:155`, `:179-205`), so each worker thread gets its own SQLite connection and no connection is shared across threads.
- **The fingerprint service does not read whole files.** `compute_file_fingerprint` reads at most 3 × 64 KiB per file (192 KiB) regardless of the file size; the "reads the entire file into memory" concern does not apply (the *quality* of the resulting hash is a different problem — F-WN-25-8).
- **`AudioFingerprintService` is not dead code.** It is wired end-to-end: `core/api.py:3879` → `ui/web_new_v2/js/settings.js:289` (scan) and `core/api.py:3889` → `js/settings.js:3331` (delete), with a confirmation modal (`js/settings.js:3260-3292`) before the destructive action.
- **Division by zero is handled.** `services/listening_comparison.py:54` guards the percentage (`percent = round((after - before) / before * 100, 1) if before else None`), and the frontend renders `null` as "Раньше прослушиваний не было" / "Без изменений" (`js/profile-comparison.js:6-10`); `tests/test_listening_comparison.py:32-36` pins it. No `ZeroDivisionError` is possible.
- **No naive/aware datetime mixing.** `listening_comparison` works exclusively with aware datetimes (`datetime.now(timezone.utc)`, `:19-21`, with a defensive `replace(tzinfo=timezone.utc)` for a naive `now=`), converts them to UTC strings (`:9-10`), and `history.played_at` is written by SQLite's `CURRENT_TIMESTAMP` default (`core/database.py:277`), which is also UTC. The string bounds therefore compare correctly against the stored values, and `core/database.py::get_wrapped_stats` uses `datetime('now', …)` (UTC) consistently. No `TypeError: can't compare offset-naive and offset-aware datetimes` is reachable through this path.
- **The two comparison windows are equal and non-overlapping** (`services/listening_comparison.py:23-24, 50`), so the headline percentage is not biased by a partial current window (unlike the Android port, which is documented as biased in `docs/audits/ANDROID_FINDINGS_REGISTER.md:382`).
- **The bridge call is not on the UI thread.** pywebview's HTTP server is a `ThreadingMixIn` (`webview/http.py:57-73`), so a long `get_listening_comparison` or `find_duplicate_tracks` occupies a worker thread, not the WebView2 UI thread.
- **The existing WN-25 tests all pass**: `tests/test_lufs_resources.py`, `tests/test_listening_comparison.py`, `tests/test_measured_listening.py` → `24 passed in 1.02s`.

---

### 4. Coverage gaps

- **I did not run the real application** (forbidden by the brief), so the following are argued from code and measured in isolation rather than observed live: the 467 s "year" comparison as the user sees it; the watchdog's non-functioning in a live install (the `scan_folders` table was confirmed empty by exhaustive static search, but I did not open a live `~/.nedotify/nedotify_storage.db`); and the F-WN-25-7 shutdown race (no live DB was touched).
- **The LUFS memory figure is measured with WAV input.** A 5-minute WAV at 44.1 kHz stereo is bit-identical in decoded size to a 5-minute MP3/FLAC, and the decoder always outputs 2 × 44 100 frames/s, so the byte counts transfer; but the *wall-clock* cost for compressed formats (MP3/FLAC decode + resample) was not measured and is certainly higher than the 0.81 s measured for WAV.
- **The DST finding was reproduced with synthetic offsets**, not with a real DST-aware browser. The frontend passes `-new Date().getTimezoneOffset()`, which is the offset at the moment of the call — I could not execute the WebView2 renderer to confirm the value it produces across a transition.
- **The `find_duplicates` cost was measured with 2 000 synthetic 200 KiB files** on a warm page cache. The cold-cache case (real files on a spinning disk or a network share) will be slower; the 0.63 s figure is a lower bound.
- **I did not measure the multi-hour / multi-day behaviour of the LUFS scanner against a realistic library** (2000+ local tracks) end-to-end; the per-file figures are measured, the aggregate is extrapolated from `LIMIT 20` batches.
- **`services/listening_comparison.py` was measured only against synthetic history data** with a uniform artist distribution. Real data with skewed artists (a few hundred dominant artists plus a long tail) may change the constants but not the asymptotic behaviour, which is confirmed by the `EXPLAIN QUERY PLAN` output.
- **I did not verify the `Android`/`macOS-legacy` counterparts** — out of scope for this run.
- **I did not audit `services/smart_playlists.py` / `services/taste_profile.py`**, which the project's own register notes re-implement the same aggregation rules; they belong to WN-23/WN-24 and were only referenced.

---

### 5. Architecture improvements (ARCH)

- **ARCH-1 — One "listening period" definition, owned by one layer.** `services/listening_comparison.py` and `core/database.py::get_wrapped_stats` independently re-derive "what counts as a play in the last N days" (F-WN-25-2), and `services/smart_playlists.py` / `services/taste_profile.py` re-implement related rules. The persistence layer already owns the schema and half of the rules; the service layer re-implements them in raw SQL, reaching past `DatabaseManager` into `db.conn` and `db._write_lock`. A single `ListeningPeriod` value object (window, play predicate, artist normalisation) in the data layer, consumed by every consumer, would make the two Profile panels agree by construction and would let the correlated-subquery optimisation (F-WN-25-1) be written once.
- **ARCH-2 — The loudness service should own an explicit measurement contract, not inherit one from a decoder's defaults.** `analyze_lufs` currently depends on `miniaudio.decode_file`'s implicit `nchannels=2, sample_rate=44100` (F-WN-25-6) and on `pyloudnorm`'s implicit whole-array API (F-WN-25-4). A small `LoudnessProfile` (channel layout, sample rate, max analysed duration, target reference) declared at the call site would make the basis of every stored number explicit, make the stored value auditable, and let the decode be streamed/bounded.
- **ARCH-3 — Separate "measurement" from "measurement outcome".** `tracks.lufs` currently carries three different meanings: not yet measured (NULL), measured, and failed (a placeholder). A dedicated status/`error` column (or a `loudness_measurements` table keyed by track id + file mtime + size) would remove the need for fabricated values, make retries and invalidation possible, and would make the file-level cache the prompt asks about ("is the result cached per path+mtime?") a first-class object rather than an accident of the `lufs IS NULL` work queue.
- **ARCH-4 — The bridge contract between `services/` and the app core is inverted.** `WatchdogService._on_new_file` calls `self._core.scanner._import_file(...)` — a *private* method of another class — and `self._core.api._emit(...)` — a *private* method of the bridge class. `FileScanner` already exposes `scan_single_file()` for exactly this purpose (`utils/file_scanner.py:52-56`). Reaching into a private method couples the watcher to the scanner's internals: any change to the import contract (adding a lock, a source tag, a normalisation step) silently desynchronises the watchdog path from the user-driven path. The watcher should depend on a public interface (e.g. `core.scanner.import_file(path)`) and on a published event, not on two private members of two other subsystems.
- **ARCH-5 — Give the fingerprint a storage contract.** `AudioFingerprintService` recomputes everything on every call (F-WN-25-9) because there is nowhere to put a fingerprint. Persisting `(fingerprint, file_size, mtime)` next to the track would make the scan incremental, would let the "duplicate" verdict be re-verified at delete time (the destructive action currently trusts a 90 % constant), and would separate "hashing" from "grouping" from "acting on a group" — three responsibilities currently in one 60-line method.
- **ARCH-6 — Feature-flag the heavyweight subsystems at the wiring point.** Both the watchdog (`core/app.py:143, 161-165`) and the loudness scanner (`:144, 167-171`) are constructed and started unconditionally at boot, even though the watchdog currently has nothing to watch (F-WN-25-3) and the loudness scanner has no user-visible setting. Startup cost, idle CPU (the project's own profile measures the watchdog's 1 Hz poll) and the dependency footprint could all be tied to an explicit opt-in, and the "feature exists but is unreachable" class of bug (F-WN-25-3) would disappear with it.
