## AREA WN-13 — Background downloader, download state, transfer control — ROLE B

### 1. Scope reviewed

**Files opened (read in full or to the cited ranges):**

- `core/downloader.py` L1–909 (all methods: `DownloadManager.__init__` 56–90, `pause_download` 101–113,
  `resume_download` 115–128, `retry_failed_downloads` 130–138, `_call_provider` 140–150,
  `_checkpoint_transfer` 152–155, `_record_progress` 157–169, `_emit` 171–183, `start_batch` 185–191,
  `_decrement_batch_total_for_dedup` 193–211, `_on_batch_task_done` 213–239, `cancel_batch` 241–285,
  `_init_db_table` 287–331, `_resume_pending_downloads` 333–354, `queue_download` 356–410,
  `_release_track_id` 412–415, `_running_futures` 417–421, `_wait_for_free_slot` 423–435,
  `_process_queue` 437–471, `_download_spotify_track` 473–558, `_mark_queue_cancelled` 560–577,
  `_is_cancelled` 579–585, `_abort_cancelled` 587–608, `_RETRYABLE_MARKS` 612–627,
  `_fetch_from_provider` 629–662, `_fetch_with_retry` 664–711, `_download_worker` 713–743,
  `_execute_download_worker` 745–882, `stop` 884–909; module constants L20–52).
- `core/download_store.py` L1–71 (all of `DownloadStore`).
- `core/download_transfer.py` L1–128 (`DownloadInterrupted`, `DownloadContext`, `download_http`).
- `core/database.py` L150–219 (`_get_connection`/thread-local connections), L1270–1309
  (`mark_track_downloaded`, `get_downloaded_tracks`), L2284–2419 (`ensure_download_queue_table`,
  `download_queue_add`, `download_queue_set_status`, `download_queue_set_downloading`,
  `download_queue_get_status`, `download_queue_cancel_pending`, `download_queue_get_pending`),
  L2455–2489 (`close`).
- `core/api.py` L2277–2362 (`get_downloaded_tracks`, `download_track`), L2590–2734
  (`toggle_favorite`, `_auto_save_favorite`), L3105–3167 (`clear_storage`, `_delete_downloaded_files`),
  L3683–3740 (`download_all_favorites`, `cancel_batch_download`).
- `core/app.py` L130–145 (DownloadManager construction), L488–586 (`cleanup`, `downloader.stop`, `db.close`).
- `services/youtube_service.py` L55–175 (`_yt_gating_error`, `_is_allowed_youtube_target`,
  `_require_audio_file`), L1060–1190 (`download_audio_sync`).
- `services/soundcloud_service.py` L840–974 (`download_audio_sync`).
- `services/yandex_service.py` L245–288 (`download_audio_sync`).
- `services/spotify_service.py` L1–230 (grepped: **no** `download_audio_sync` — it is not a download provider).
- `services/base_service.py` L120–185, L280–330 (shared executor, `_normalize_entry`).
- `services/track_resolver.py` L1–70, L255–330 (resolver construction cost).
- `utils/url_safety.py` L1–37 (`is_safe_media_url`).
- `ui/web_new_v2/js/events.js` L60–130, L235–294; `ui/web_new_v2/js/downloads-view.js` L1–193;
  `ui/web_new_v2/js/feature-controls.js` L85–134; `ui/web_new_v2/js/utils.js` L755–794, L1010–1039;
  `ui/web_new_v2/js/main.js` L95–119; `ui/web_new_v2/js/search.js` L400–439; `ui/web_new_v2/js/player.js` L2018.
- `tests/test_downloader.py` (95 L), `tests/test_downloader_cancel.py` (405 L),
  `tests/test_download_integrity.py` (147 L), `tests/test_download_resume.py` (386 L),
  `tests/test_download_retry.py` (128 L), `tests/conftest.py` L60–176.
- Python 3.14.7 stdlib `concurrent/futures/thread.py` L18–62, L225–274 (interpreter-exit semantics).

**Callees traced into other areas (root cause owned elsewhere, noted, not re-reported here):**

| Callee | Area | Note |
|---|---|---|
| `services/youtube_service.py::download_audio_sync` / `_require_audio_file` | WN-19 | provider fetch strategy, yt-dlp options, its own integrity gate (duplicated from the downloader's) |
| `services/soundcloud_service.py::download_audio_sync` | WN-20 | preview→YouTube fallback, its own `outtmpl` |
| `services/yandex_service.py::download_audio_sync` | WN-21 | the only provider that uses `DownloadContext.download_http` |
| `services/track_resolver.py::TrackResolver` | WN-18 | instantiated per Spotify download by the downloader |
| `core/database.py` (`download_queue_*`, `mark_track_downloaded`, `close`) | WN-12 | table owner, write lock, thread-local connections |
| `core/api.py` (`download_track`, `download_all_favorites`, `clear_storage`, `_auto_save_favorite`) | WN-06 / WN-10 | bridge surface, quota scan, orphan-file policy |
| `core/user_errors.py::describe_error` | WN-16 | error taxonomy used in the `download_failed` payload |
| `utils/url_safety.py::is_safe_media_url` | WN-27 | SSRF guard used by the download path |
| `ui/web_new_v2/js/downloads-view.js`, `events.js`, `feature-controls.js` | WN-32 / WN-28 | consumers of the download events |

**Verification method.** Read-only probes under `%TEMP%\opencode\wn13_verify{,2,3,4}.py` (repo untouched,
no real home directory, no network): real `DatabaseManager` + `DownloadManager` against a temp DB, stub
providers, `~` redirected to a temp dir. `pytest` was not modified; no repo file was written.

---

### 2. Findings

#### F-WN-13-1  [P1] — `download_http` skips the completeness check when the server omits `Content-Length`, so a truncated body is renamed to the final path and returned as a successful download

- **File:** `core/download_transfer.py:100`, `core/download_transfer.py:117-119`; consumer `core/downloader.py:801-819`
- **Confirmed:** yes (probe reproduced; see "Reproduction")
- **Description:** the Yandex path (`services/yandex_service.py:279-280` → `DownloadContext.download_http`)
  is the only provider that transfers bytes itself. Its "did we get everything?" test is
  `if total and downloaded != total: raise IOError(...)`. `total` is derived from the `Content-Length`
  header, and `total = int(response.headers.get('Content-Length') or 0)` yields **0** when the header is
  absent (chunked transfer). `if total and ...` is then short-circuited and the check never runs. The
  truncated `.part` file is `os.replace`d onto the final `.mp3` name and returned as a *successful*
  download. The downloader's integrity gate (`core/downloader.py:807`) does not catch it either (see
  F-WN-13-2), so `tracks.is_downloaded = 1`, `download_queue.status = 'completed'` and `download_complete`
  are emitted for a file that contains only the first bytes of the track.
- **Cause:** the completeness invariant is expressed as "compare against a total that may be unknown"
  instead of "the total must be known, otherwise the transfer is not verifiable".
- **Trigger conditions:** the media host answers with a chunked/`Transfer-Encoding` response or omits
  `Content-Length` (e.g. a CDN edge, a proxy, or a connection cut at the HTTP layer where the socket
  closes cleanly). Any network interruption that ends the body without a length is enough.
- **User impact:** the track appears in the library as downloaded, plays only partially (or not at all),
  and the user is told the download succeeded — there is no error to act on. Offline playback of that
  track is broken until the user manually deletes the file and re-downloads (and the queue row is
  `completed`, so "retry errors" never picks it up).
- **Evidence:**
  ```python
  # core/download_transfer.py:98-100
              else:
                  offset = 0
                  total = int(response.headers.get('Content-Length') or 0)
  # core/download_transfer.py:116-119
              self.checkpoint()
              if total and downloaded != total:
                  raise IOError('Соединение прервано до завершения загрузки')
              os.replace(partial_path, output_path)
  ```
- **Reproduction / verification:** probe with a fake 200 response that has **no** `Content-Length` and a
  body of 2×8192 bytes (a truncated 16 KiB "track"):
  ```
  {"http_truncated_no_len": {"returned": "...\\http_audio.mp3", "size": 16384,
                             "part_left": false, "accepted_as_complete": true}}
  ```
  The function returned the final path, the `.part` was consumed, and no exception was raised.
  Repro script: `%TEMP%\opencode\wn13_verify2.py` (probe 1).
- **Suggested fix:** make the total mandatory for a "complete" verdict — treat a missing
  `Content-Length` as "not verifiable" (either reject, or fall back to decoding the container and
  comparing durations), and never `os.replace` the `.part` onto the final name in that case.
- **Fix side effects:** hosts that legitimately stream without a length would start failing; those need
  an alternative completeness proof (e.g. ffprobe/ mutagen duration check) rather than a silent pass.
- **Discovered by:** B

#### F-WN-13-2  [P2] — `_downloaded_file_defect` cannot distinguish a truncated file from a complete one (extension + 4 KiB floor only)

- **File:** `core/downloader.py:37-52`, applied at `core/downloader.py:807-814`
- **Confirmed:** yes
- **Description:** the gate that decides "is this a usable download?" checks only (a) the file exists,
  (b) the name does not end in `.part`, (c) the extension is in `_AUDIO_DOWNLOAD_EXTS`, (d) the size is
  ≥ 4096 bytes. A file that is 100 KB out of a 5 MB track passes every one of those tests, so the
  downloader marks the track as downloaded and fires `download_complete`. There is no duration,
  container or checksum comparison anywhere in the download path — the only completeness signal is
  "the server told us a length and we got that many bytes" (F-WN-13-1), which is skipped when the
  length is unknown.
- **Cause:** the gate was designed against *shape* defects (0-byte files, `.part` fragments, `sb0.mhtml`
  gate pages) — see the docstring at `core/downloader.py:29-34` — and was never extended to *truncation*.
- **Trigger conditions:** any partial transfer that still produces >4 KiB of bytes: a dropped connection
  without a length (F-1), a provider that returns a preview instead of the full track, a disk that
  filled up mid-write (the write raises, so this one is caught), or a source whose advertised size is
  wrong.
- **User impact:** "downloaded" in the UI, a file in the library, and silence — the same class of bug the
  gate was introduced to prevent (`tests/test_download_integrity.py:1-15` states the original failure
  mode explicitly).
- **Evidence:**
  ```python
  # core/downloader.py:44-52
      if os.path.splitext(name)[1].lower() not in _AUDIO_DOWNLOAD_EXTS:
          return f'скачан не аудиофайл ({name})'
      try:
          size = os.path.getsize(path)
      except OSError as exc:
          return f'не удаётся прочитать файл: {exc}'
      if size < _MIN_AUDIO_BYTES:
          return f'файл повреждён ({size} байт)'
      return ''
  ```
- **Reproduction / verification:** write 100 000 zero bytes to `truncated.mp3` and call the gate:
  `core.downloader._downloaded_file_defect(path)` → `''` (i.e. "this is a good download").
  Probe: `%TEMP%\opencode\wn13_verify.py` → `{"defect_truncated_100kb": ""}`.
- **Suggested fix:** compare the on-disk size against the size the provider advertised
  (`total_bytes` is already tracked in `download_queue`) and/or validate the container
  (duration/stream count) before `mark_track_downloaded`.
- **Fix side effects:** a size comparison needs a trustworthy `total`; for providers that never report
  one (F-1) a duration check is required, which costs a decode per download.
- **Discovered by:** B

#### F-WN-13-3  [P2] — `stop()` does not terminate the executor: the in-flight worker keeps running, and keeps its SQLite connection and file handles, after `stop()` returned

- **File:** `core/downloader.py:884-909`; callers `core/app.py:545-546` (`downloader.stop`) and
  `core/app.py:559-560` (`db.close`)
- **Confirmed:** yes
- **Description:** `stop()` bumps the cancel epoch, clears the queue and calls
  `self._pool.shutdown(wait=False, cancel_futures=True)`. `wait=False` does **not** join the worker
  threads and does **not** interrupt the running task; the worker only notices the epoch at its next
  *stage boundary* (`_abort_cancelled`), which for a provider call means after the whole download
  returns. `stop()` then waits at most `drain_timeout` (5 s) on the futures and gives up. So after
  `stop()` returns, a worker is typically still inside `provider.download_audio_sync` and still owns an
  open SQLite connection (created thread-locally, `core/database.py:179-201`) and an open file handle
  for the `.part` file. `core/app.py::cleanup()` then calls `db.close()`, which cannot close a
  connection created on another thread (`core/database.py:2459-2489`) → every shutdown logs
  *"N database connection(s) could not be closed from the main thread"*, and the handle survives until
  the daemon thread dies.
  The docstring promises more than the code delivers: *"already running workers get a bounded window to
  finish their database bookkeeping instead of writing to a closed connection"*.
- **Cause:** `stop()` treats "stop waiting" as "stopped"; there is no hard deadline that the worker
  itself observes, and no separation between "the manager is closed" and "the transfer must abort".
- **Trigger conditions:** any shutdown while a download is in flight — the common case, since the user
  usually closes the app *during* a download.
- **User impact:** the app still exits (the pool threads are daemon threads, created by the daemon
  `_processor_thread` at `core/downloader.py:89`), but the shutdown path is not actually bounded: the
  worker keeps running against a database that `cleanup()` considers closed, and the app log carries a
  misleading warning on every exit.
- **Evidence:**
  ```python
  # core/downloader.py:892-909
          self._store.preserve_shutdown()
          self._running = False
          self._cancel_epoch += 1
          ...
          self._pool.shutdown(wait=False, cancel_futures=True)
          deadline = time.monotonic() + max(0.0, float(drain_timeout))
          for fut in self._running_futures():
              remaining = deadline - time.monotonic()
              if remaining <= 0:
                  break
              try:
                  fut.result(timeout=remaining)
              except Exception as e:
                  logger.debug(f'Download worker did not finish before shutdown: {e}')
  ```
- **Reproduction / verification:** probe with a provider that sleeps 20 s:
  ```
  {"stop_return_seconds": 1.01, "pool_threads_alive_after_stop": ["download_worker_0"],
   "pool_threads_daemon_flag": {"download_worker_0": true}}
  ```
  `stop(drain_timeout=1.0)` returned after 1.01 s while `download_worker_0` was still inside the
  provider. Probe: `%TEMP%\opencode\wn13_verify2.py` (probe 2). The cross-thread connection warning was
  reproduced in every probe run.
- **Suggested fix:** give the worker an explicit "the manager is closed" deadline it checks itself
  (the `DownloadContext.checkpoint` already runs on every yt-dlp progress hook and every 128 KiB HTTP
  chunk), and make `stop()` assert that the pool is empty before returning; alternatively run the
  transfer in a subprocess that can be killed.
- **Fix side effects:** `shutdown(wait=True)` would block app exit for the full duration of a stalled
  download — the opposite defect. The fix must be a *hard* abort, not a longer wait.
- **Discovered by:** B

#### F-WN-13-4  [P2] — A cancelled or aborted download leaves a complete file in `~/.nedotify/downloads/` that nothing references and nothing ever deletes

- **File:** `core/downloader.py:798-800` (abort *after* the provider returned the file),
  `core/downloader.py:560-577` (`_mark_queue_cancelled`),
  `core/api.py:3138-3154` (`_delete_downloaded_files` — the only deleter of download files),
  `core/api.py:2698-2714` (the auto-download quota scan counts every file in the directory)
- **Confirmed:** yes
- **Description:** when the cancel epoch is bumped while a transfer is running, the worker aborts at the
  `after-provider` stage and returns — the file the provider just wrote stays on disk. The queue row
  becomes `cancelled`, `tracks.is_downloaded` stays 0 and `tracks.file_path` stays NULL. The file is
  therefore invisible to the library, invisible to `clear_storage("all")` (which only walks
  `tracks.file_path`), and invisible to "retry errors" (which only re-arms `failed` rows — see
  `core/database.py:2330-2356`, whose `ON CONFLICT ... WHERE status IN ('failed','cancelled')` does not
  include `cancelled`… and even for `cancelled` the user has to press "Повторить ошибки", which selects
  only `failed`). The orphan is permanent disk usage inside the user's library directory — and
  `~/.nedotify/` is explicitly *not* a cleanup area (contract #3).
- **Cause:** the cancel path has no "reclaim the half-finished artefact" step; the queue state machine
  has no state that means "file exists, not registered".
- **Trigger conditions:** the user cancels a batch, pauses a download, or closes the app while a
  transfer is in flight — i.e. routinely.
- **User impact:** `~/.nedotify/downloads/` grows without bound with files the app never mentions; the
  auto-download quota (`core/api.py:2691-2714`) is computed from the whole directory, so orphans
  silently eat the user's quota and eventually block legitimate auto-downloads with
  *"Достигнут лимит автозагрузки"*.
- **Evidence:**
  ```python
  # core/downloader.py:796-800
              file_path = self._fetch_with_retry(source, source_id, download_dir, track_id, epoch)

              if self._abort_cancelled(track_id, epoch, 'after-provider'):
                  return
  # core/api.py:3138-3154 (only tracks.file_path is ever deleted)
      def _delete_downloaded_files(self) -> int:
          """Delete every downloaded track file from disk. Returns files removed."""
          removed = 0
          tracks = self._core.db.get_downloaded_tracks() or []
  ```
- **Reproduction / verification:** probe — queue a download, let the provider write a 9 KB file, call
  `cancel_batch()`, let the provider return:
  ```
  {"files_left_in_downloads_dir": ["download_1_abc.mp3"], "track_is_downloaded": 0,
   "track_file_path": null, "queue_status": "cancelled",
   "failed_rows_retry_would_pick": [], "cancelled_rows_present": [1]}
  ```
  Probe: `%TEMP%\opencode\wn13_verify3.py`. The same mechanism applies to a paused download
  (`core/downloader.py:110-111` + the `DownloadInterrupted` path in `core/download_transfer.py:109-115`,
  which intentionally keeps the `.part`).
- **Suggested fix:** give the queue a `cancelled`/`abandoned` state that records the produced path, and
  add a reconciliation step (at startup, next to `DownloadStore.recover()`) that either registers the
  file or deletes/reclaims it; alternatively make the quota scan and `clear_storage("all")` operate on
  the directory, not on `tracks.file_path`.
- **Fix side effects:** deleting on cancel would destroy the resumable `.part` of a paused transfer —
  the reclaim must distinguish "partial artefact" (keep, for resume) from "complete but unregistered"
  (register or delete).
- **Discovered by:** B

#### F-WN-13-5  [P2] — A non-integer `track_id` yields a download that reports "completed" but is never registered, and can never be retried

- **File:** `core/downloader.py:356-410` (`queue_download` performs no type validation on `track_id`),
  `core/downloader.py:819` (`mark_track_downloaded`), `core/database.py:1278-1282`
  (`UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?`)
- **Confirmed:** the failure mode is confirmed; UI reachability is a hypothesis (see below)
- **Description:** `download_queue.track_id` is declared `INTEGER NOT NULL`, but SQLite type affinity
  keeps a non-numeric string as TEXT. `mark_track_downloaded('ytABC123XYZ', path)` then matches **0
  rows** and raises nothing — the `UPDATE` silently affects no row. The worker continues, writes
  `download_queue.status = 'completed'` and emits `download_complete`. The result is a download that
  the UI shows as *Готово*, a file that exists on disk, and a track that is **not** in the library as
  downloaded. Because `download_queue_add` only re-arms rows in `('failed','cancelled')`
  (`core/database.py:2349-2350`), a `completed` row can never be re-queued → the state is permanent
  for that track.
- **Cause:** `track_id` is treated as an opaque value by `DownloadManager` even though every consumer
  (`tracks.id`, `download_queue.track_id`) is an integer primary key; the "0 rows updated" outcome of a
  `UPDATE ... WHERE id = ?` is never checked.
- **Trigger conditions:** any caller that forwards a UI-supplied `id` verbatim:
  `core/api.py:2299` (`track_id = track_data.get("id")`), `core/api.py:2617` (`toggle_favorite`) and
  `core/api.py:2722` (`queue_download(track_id, ...)` in `_auto_save_favorite`) — all pass the value
  through without an `int()` coercion or a validation that the row exists.
- **User impact:** the track never appears in the downloaded library, the file is invisible, and the
  download panel claims it is finished; re-clicking download is rejected as "already queued".
- **Evidence:**
  ```python
  # core/downloader.py:819
                  self._core.db.mark_track_downloaded(track_id, file_path)
  # core/database.py:1278-1282
      def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
          with self._write_lock:
              with self.conn:
                  cursor = self.conn.cursor()
                  cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
- **Reproduction / verification:** probe with a TEXT id:
  ```
  {"queue_track_id_types": [["ytABC123XYZ", "text"]],
   "tracks_rows_matching_text_id": 0, "track_is_downloaded": 0,
   "requeue_returns_added": false, "status_after_requeue_attempt": "completed"}
  ```
  `mark_track_downloaded` raised no exception, matched 0 rows, and the row could not be re-armed.
  Probe: `%TEMP%\opencode\wn13_verify4.py`.
  **Missing evidence for full confirmation:** a runtime trace of the `download_track` payloads showing a
  non-integer `id`. The UI paths I traced (`js/search.js:416` builds `id: 'playlist_<idx>'` for playlist
  cards, `js/home-shell.js:33`, `js/profile.js:20` normalise to `track.track_id`, i.e. an integer DB id)
  did not show a download button on a non-integer-id track — but `js/utils.js:778-782`,
  `js/player.js:2018` and `js/main.js:104-108` forward whatever object the caller holds.
- **Suggested fix:** coerce and validate `track_id` to `int` in `queue_download` (reject with
  `download_failed` if it is not a positive integer that exists in `tracks`), and make
  `mark_track_downloaded` assert that exactly one row was updated.
- **Fix side effects:** a validation that rejects unknown ids would also reject the legitimate
  "download before the track was persisted" flow — but that flow already resolves the id inside
  `core/api.py:2319-2335` (`add_track`), so the downloader can safely require an integer.
- **Discovered by:** B

#### F-WN-13-6  [P2] — `cancel_batch()` performs an O(N) write storm (one write transaction per row) on top of a redundant bulk UPDATE, all under the global DB write lock

- **File:** `core/downloader.py:272-284`; `core/download_store.py:21-30` (`DownloadStore.update` opens
  its own transaction per call and takes `database._write_lock`)
- **Confirmed:** yes
- **Description:** `cancel_batch()` first runs a bulk
  `UPDATE download_queue SET status = 'cancelled' WHERE status = 'pending'`, and then loops over
  `self._store.rows(('pending','downloading','cancelled'), limit=5000)` and issues **one UPDATE
  transaction per row** — including rows that the bulk statement already set to `cancelled` (they are in
  the filter). `DownloadStore.update` takes `DatabaseManager._write_lock` and opens a transaction for
  every single row, so cancelling a 500-track batch performs 501 write transactions and takes the
  global write lock 501 times, blocking every other DB writer and reader (the UI's `get_downloads`,
  the proxy's reads, the settings writer) for the duration.
- **Cause:** the bulk update and the per-row loop overlap; the per-row loop was added to also clear
  `resume_on_restart` but was not folded into a single statement.
- **Trigger conditions:** cancelling a large batch (`download_all_favorites` on a big favourites list,
  `core/api.py:3685-3728`) or any cancel with many queue rows.
- **User impact:** a visible stall on the bridge call (`cancel_batch_download`), and the queue table is
  written N+1 times for no reason.
- **Evidence:**
  ```python
  # core/downloader.py:272-284
          try:
              if hasattr(self._core.db, 'download_queue_cancel_pending'):
                  self._core.db.download_queue_cancel_pending()
              else:
                  ...
          except Exception:
              pass
          for row in self._store.rows(('pending', 'downloading', 'cancelled'), limit=5000):
              self._store.update(row['track_id'], status='cancelled', resume_on_restart=0)
  ```
- **Reproduction / verification:** probe with 200 pending rows, counting the SQL statements executed
  against `download_queue` via `sqlite3.Connection.set_trace_callback`:
  `{"cancel_batch_seconds_200_rows": 0.026, "cancel_batch_update_statements": 201}` — 201 UPDATEs for
  200 rows. Probe: `%TEMP%\opencode\wn13_verify.py` (probe 5).
- **Suggested fix:** one statement —
  `UPDATE download_queue SET status='cancelled', resume_on_restart=0 WHERE status IN ('pending','downloading')`
  — and drop the redundant per-row loop.
- **Fix side effects:** none material; the bulk statement must not touch `completed` rows.
- **Discovered by:** B

#### F-WN-13-7  [P3] — `DownloadStore.rows()` — a pure read — takes the global database write lock

- **File:** `core/download_store.py:39-46`
- **Confirmed:** yes (by code inspection; the lock scope is explicit)
- **Description:** `DownloadStore.rows()` wraps its `SELECT ... LEFT JOIN tracks ... ORDER BY <CASE>
  LIMIT ?` in `with self.database._write_lock:`. Every read of the download queue therefore serialises
  behind every DB writer in the process — including the 0.75 s-throttled progress writes of the two
  download workers, the settings writer, and the proxy's reads. `rows()` is called on the UI path
  (`core/api.py:4176-4181` → `js/downloads-view.js:89-120`), and the UI refreshes it on a 180 ms
  debounce driven by every `download_progress` / `download_queue_updated` / `download_complete` event
  (`ui/web_new_v2/js/feature-controls.js:104-106`).
- **Cause:** the module docstring says *"using the database manager's existing write lock"* — the write
  lock was used as a general "database access" serialiser, which is exactly what WAL + a per-thread
  connection already provide safely.
- **Trigger conditions:** any download activity; the effect scales with the number of queue rows because
  the query is a full scan + sort of `download_queue` joined with `tracks`.
- **User impact:** increased contention on the single global DB lock; the UI download panel can lag
  behind a busy batch. Bounded, but it is a self-inflicted cost in a WAL database that supports
  concurrent readers.
- **Evidence:**
  ```python
  # core/download_store.py:39-46
          with self.database._write_lock:
              rows = self.database.conn.execute(
                  'SELECT queue.*, tracks.title, tracks.artist FROM download_queue AS queue '
                  'LEFT JOIN tracks ON tracks.id = queue.track_id ' + where +
                  " ORDER BY CASE queue.status WHEN 'downloading' THEN 0 WHEN 'pending' THEN 1 "
                  "WHEN 'paused' THEN 2 WHEN 'failed' THEN 3 ELSE 4 END, queue.id DESC LIMIT ?",
                  parameters,
              ).fetchall()
  ```
- **Reproduction / verification:** inspect the lock scope at `core/download_store.py:39` — the `SELECT`
  is inside the `with` block. (A runtime probe could not instrument `sqlite3.Connection.execute`, whose
  attribute is read-only; the code path is unambiguous.)
- **Suggested fix:** read outside the write lock (the connection is thread-local and WAL readers do not
  block), and reserve `_write_lock` for writes.
- **Fix side effects:** with a per-thread connection the read is already isolated; the only risk is
  seeing a slightly stale snapshot, which the UI already tolerates (it polls).
- **Discovered by:** B

#### F-WN-13-8  [P3] — No per-download deadline: a stalled provider occupies a worker, and with `_MAX_INFLIGHT = 2` two stalled downloads freeze the entire queue

- **File:** `core/downloader.py:22` (`_MAX_INFLIGHT = 2`), `core/downloader.py:140-150` (`_call_provider`),
  `core/downloader.py:664-711` (`_fetch_with_retry`); provider timeouts
  `services/youtube_service.py:1092-1094` (`socket_timeout: 30`, `retries: 5`, `fragment_retries: 5`),
  `services/soundcloud_service.py:938-942`
- **Confirmed:** yes (by code inspection; the concrete stall duration is provider-dependent)
- **Description:** `_call_provider` imposes no timeout of its own; the effective bound is the provider's
  own options (yt-dlp: 30 s socket timeout × 5 retries × 5 fragment retries — minutes in the worst
  case). Cancellation is cooperative and only observed where the provider calls back into the
  `DownloadContext` — yt-dlp's `progress_hooks` (`core/download_transfer.py:31`, `34-39`) and every
  128 KiB HTTP chunk (`core/download_transfer.py:111`) — but **not** during `extract_info`, i.e. during
  the metadata/resolution phase, which is exactly where the YouTube anti-bot gate stalls. During that
  window a cancel is not honoured and the worker cannot be interrupted.
  With `_MAX_INFLIGHT = 2` and `ThreadPoolExecutor(max_workers=_MAX_INFLIGHT)` (`core/downloader.py:58`),
  two such stalls block the whole queue: nothing downloads, nothing reports progress, and "cancel"
  appears to do nothing.
- **Cause:** the queue has no notion of a per-item deadline; backpressure is expressed only as a
  concurrency cap.
- **Trigger conditions:** a provider that stalls during resolution (rate limiting, an anti-bot gate, a
  dead CDN edge), which is common on YouTube.
- **User impact:** the download queue appears frozen; the user cannot cancel it (the cancel is only
  honoured at the next progress hook) and cannot start anything else.
- **Evidence:**
  ```python
  # core/downloader.py:140-150
      def _call_provider(self, provider, source_id, download_dir):
          context = getattr(self._worker_context, 'context', None)
          method = provider.download_audio_sync
          try:
              accepts_context = 'download_context' in inspect.signature(method).parameters
          except (TypeError, ValueError):
              accepts_context = False
          if context and accepts_context:
              context.checkpoint()
              return method(source_id, download_dir, download_context=context)
          return method(source_id, download_dir)
  ```
  (no timeout, no deadline; the cancel checkpoint is only the pre-call one.)
- **Reproduction / verification:** read `core/downloader.py:140-150` (no deadline) together with
  `services/youtube_service.py:1087-1106` (`retries: 5`, `fragment_retries: 5`, `socket_timeout: 30`)
  and `services/youtube_service.py:1123-1141` (`extract_info` runs with no `checkpoint()` inside it).
  A direct runtime repro needs a stalling provider; the code path is unambiguous.
- **Suggested fix:** give the worker a wall-clock deadline (e.g. 10 min per track) that the
  `DownloadContext.checkpoint` enforces, and check the epoch during provider resolution, not only
  around it.
- **Fix side effects:** a deadline large enough not to kill legitimate slow downloads will still allow
  a long stall; the deadline must be paired with an abort mechanism the provider honours.
- **Discovered by:** B

#### F-WN-13-9  [P3] — `DownloadManager._emit` swallows every bridge failure at `debug` level, so a dropped `download_complete` is invisible

- **File:** `core/downloader.py:171-183`
- **Confirmed:** yes
- **Description:** every event the downloader produces goes through `_emit`, whose only error handling
  is `except Exception: logger.debug("downloader emit %s failed", event_name, exc_info=True)`. If the
  pywebview bridge is not ready (the app is still starting, or the WebView is being torn down), the
  `download_complete` / `download_failed` events are dropped with **no** trace at the default log level
  (`~/.nedotify/logs/app.log`). The UI then keeps the track in the "downloading" state until the panel
  is refreshed, and the user has no indication that anything went wrong.
- **Cause:** the safety net is one level too quiet for an event that is the *only* completion signal
  (contract #7 — there is no SSE/WebSocket fallback, contract #6).
- **Trigger conditions:** any emit that raises — a bridge that is not ready, a payload that fails to
  serialise, a window that is closing.
- **User impact:** a stale UI state and no diagnostic in `app.log`; this is exactly the "failure mode
  is silence" the project rules warn about.
- **Evidence:**
  ```python
  # core/downloader.py:182-183
          except Exception:
              logger.debug("downloader emit %s failed", event_name, exc_info=True)
  ```
- **Reproduction / verification:** read `core/downloader.py:171-183`; the `except` clause is the only
  error handling in the method and the level is `debug`.
- **Suggested fix:** log at `warning` (or `error` for `download_complete`/`download_failed`) and, for
  terminal events, fall back to a state refresh so the UI can resynchronise.
- **Fix side effects:** a bridge that is permanently unavailable would produce one warning per event —
  bound it (log once per event name per session).
- **Discovered by:** B

#### F-WN-13-10  [P3] — Cancel/complete race: the queue row and `tracks.is_downloaded` can end up inconsistent (`is_downloaded=1` with status `cancelled`, or `is_downloaded=0` with status `completed`)

- **File:** `core/downloader.py:281-282` (cancel writes `cancelled`), `core/downloader.py:818-838`
  (worker writes `mark_track_downloaded` + `completed`), `core/database.py:2330-2356`
- **Confirmed:** the interleaving is confirmed by code inspection; the exact outcome is a race
- **Description:** `cancel_batch()` and the worker write the same row without a shared lock or a
  compare-and-set. The worker only checks the epoch at the `after-provider` boundary
  (`core/downloader.py:798`); a cancel that lands *after* that check but *before* the worker's
  `download_queue_set_status(track_id, 'completed')` leaves the row in whichever order the two writes
  happen to land. In the losing order the track is registered as downloaded (`is_downloaded=1`, a real
  file on disk) while the queue row says `cancelled`, and the Downloads panel shows "Отменено" for a
  track that is in the library. In the other order the row says `completed` while `is_downloaded` is
  still 0 (the worker's `mark_track_downloaded` ran before the cancel's `UPDATE`), so a genuinely
  finished download is presented as failed and — because `download_queue_add` does not re-arm a
  `completed` row — the file is never registered.
- **Cause:** two independent writers to the same row with no state transition guard (the DB update is a
  blind `UPDATE ... WHERE track_id = ?`, not a compare-and-set on the expected previous status).
- **Trigger conditions:** the user cancels exactly while a transfer is finishing.
- **User impact:** a wrong label in the download panel; in the worst interleaving a finished download
  is silently discarded (the file stays on disk as an orphan, see F-WN-13-4).
- **Evidence:**
  ```python
  # core/downloader.py:281-282
          for row in self._store.rows(('pending', 'downloading', 'cancelled'), limit=5000):
              self._store.update(row['track_id'], status='cancelled', resume_on_restart=0)
  # core/downloader.py:828-833 (unguarded write of the same row)
                  if hasattr(self._core.db, 'download_queue_set_status'):
                      self._core.db.download_queue_set_status(track_id, 'completed')
  ```
- **Reproduction / verification:** interleaving analysis of the two write sites above; the two writes
  are not serialised by any lock shared between the bridge thread and the worker thread.
- **Suggested fix:** make the terminal transition a compare-and-set
  (`UPDATE download_queue SET status='completed' WHERE track_id=? AND status='downloading'`) and have
  the cancel path use the same guard, so exactly one of the two terminal states wins.
- **Fix side effects:** the guard must not block a legitimate completion after a `paused → pending`
  re-arm; the status set to compare against has to include the resumed state.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (brief):

- **Filename construction — the audit brief's hypothesis is NOT confirmed.** The download path never
  uses the track title in a filename. `DownloadContext.stem`
  (`core/download_transfer.py:18-20`) is `download_{re.sub(r'[^a-zA-Z0-9_-]','_',track_id)}_{sha256(source:source_id)[:16]}`;
  verified with a hostile `source_id` (`'../../evil?/AC:DC*'`) → `download_42_8cd7ef0e33a8ac20` — no
  Windows-invalid character (`< > : " / \ | ? *`), no path separator, no traversal. The provider
  templates add only `%(id)s`/`%(ext)s` (`core/download_transfer.py:27`), and the legacy branches
  (`services/youtube_service.py:1081`, `services/soundcloud_service.py:871/911/931`) sanitise the id
  with the same `[^a-zA-Z0-9_-]` rule. **Contract #8 is stale for `services/yandex_service.py`**: the
  current code sanitises the id (`services/yandex_service.py:271`,
  `safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)`), and the legacy `ya_<id>_<ts>.mp3` branch is dead
  in the download path because the `download_context` is always passed
  (`core/downloader.py:140-150`, `services/yandex_service.py:273-280`).
- **`_wait_for_free_slot` is bounded** (`core/downloader.py:423-435`): the loop condition is
  `self._running`, and each `wait(..., timeout=0.2)` returns within 200 ms, so it cannot wait forever
  and `stop()` is noticed promptly.
- **Futures do not grow unboundedly** (`core/downloader.py:417-421`, `460-463`): finished futures are
  pruned on every processor iteration and after every submit; the list stays at ≤ `_MAX_INFLIGHT`.
- **Progress emission is throttled** (`core/downloader.py:157-169`): the 0.75 s window gates *both* the
  DB write and the `download_progress` event, so there is no write amplification (≈1.3 writes/s per
  download). The final state is flushed with `force=True` in the `finally` of `_download_worker`
  (`core/downloader.py:736-742`), so the last byte count is not lost.
- **Per-download resources are closed**: `download_http` closes the HTTP response in a `finally`
  (`core/download_transfer.py:126-128`), including on the redirect and `416` paths
  (`core/download_transfer.py:73-85`); the `.part` file handle is closed by the `with` block
  (`core/download_transfer.py:109`); yt-dlp is used as a context manager
  (`services/youtube_service.py:1123`, `services/soundcloud_service.py:916/946`).
- **The audio file is written atomically** on the paths that write it themselves: `download_http`
  writes `.part` and then `os.replace(partial_path, output_path)`
  (`core/download_transfer.py:109/119`); yt-dlp uses the same `.part` + rename convention (verified by
  `tests/test_download_resume.py:340-386`). The DB state `completed` is only written *after* the
  integrity gate passes (`core/downloader.py:807-838`), i.e. the "downloaded" flag is never set before
  the file exists and passed the gate — the ordering the brief asked about is correct.
- **`stop()` is idempotent** (`core/downloader.py:884-909`): a second call re-runs
  `preserve_shutdown()`, `shutdown()` (a no-op on an already-shut-down pool) and an empty future list.
- **`_resume_pending_downloads` cannot double-queue** (`core/downloader.py:333-354`): the unique index
  `ux_download_queue_track` (`core/database.py:2309-2312`) guarantees one row per track, and the
  in-memory checks against `self._queue` and `self._active_track_ids` cover the in-process case. The
  startup path also resets `downloading → pending` first (`core/download_store.py:58-64`).
- **The event contract holds.** `download_complete` carries **only** `{'track_id': ...}` — no
  `file_path` (`core/downloader.py:839`) — exactly as contract #7 requires; `download_failed` carries
  `track_id` + `error` plus the `describe_error` fields (`code`, `action`, `title`, `message`,
  `method`) added at `core/downloader.py:174-175`, which is what
  `ui/web_new_v2/js/events.js:266-281` and `ui/web_new_v2/js/utils.js:1019-1038` consume. The
  `download_progress` payload (`downloaded_bytes`, `total_bytes`, `track_id`, `percent`) matches
  `ui/web_new_v2/js/downloads-view.js:181-193`, which does `Object.assign(item, payload)`.
- **The status vocabulary matches the UI.** The downloader writes
  `{pending, downloading, paused, completed, failed, cancelled}`; the UI renders exactly those six
  labels (`ui/web_new_v2/js/downloads-view.js:9-12`) and the same set is produced by
  `core/download_store.py:43-44`'s ordering CASE — no unknown status can reach the renderer.
- **The pool threads are daemon threads**, so a stuck download cannot block interpreter exit: they are
  created by `self._pool.submit(...)` from `_process_queue`, which runs on the daemon
  `_processor_thread` (`core/downloader.py:89`), and `threading.Thread` inherits the daemon flag
  (verified: `download_worker_0` → `daemon=True`).
- **The retry policy is sensibly separated** (`core/downloader.py:612-627`, `664-711`): only transient
  marks are retried, the backoff doubles (20 s → 40 s), and the wait is sliced into 1 s steps so a
  cancel is honoured immediately. `_RETRYABLE_MARKS` does not contain the substring `timeout` *and*
  `timed out` redundantly in a harmful way (`'timed out'` is a superstring check of the same idea), and
  `'unauthorized'`/`'forbidden'` are deliberately classified as transient.

---

### 4. Coverage gaps

- **No live app run** (forbidden by the brief): all behaviour was verified through read-only probes
  with a temporary SQLite DB, stub providers and a redirected `~`. The real yt-dlp / requests behaviour
  (chunked responses, `Content-Length` presence on the actual Yandex CDN, yt-dlp's own `.part`
  handling) was **not** observed on the wire — F-WN-13-1's trigger depends on the remote host's
  response headers.
- **UI reachability of F-WN-13-5 was not established**: a runtime trace of the `download_track` payloads
  (which `id` values actually reach the bridge) is needed. The failure mode itself is confirmed.
- **Provider-side behaviour was sampled, not audited**: `services/youtube_service.py`'s anti-bot
  handling, `services/soundcloud_service.py`'s preview→YouTube fallback and
  `services/yandex_service.py`'s client are WN-19/WN-20/WN-21 territory; I only read the parts the
  download path touches (outtmpl construction, the `download_context` parameter, the returned path).
- **`tools/bench` and `tools/visual_guard`** were not used; there is no download-throughput benchmark
  in the repo, so the performance numbers above are structural (query/write counts), not measurements
  of throughput.
- **The `EmitWorker` hand-off** (`core/api.py::_emit`) was not audited in depth — it is WN-03 — but
  note that `DownloadManager._emit` runs on the *worker* thread, never on the UI thread, which
  satisfies contract #1.
- **Cross-area observation, not re-reported here:** `core/api.py:2331/2340/2351` emit `download_failed`
  *without* the `describe_error` enrichment that `DownloadManager._emit` adds
  (`core/downloader.py:174-175`), so those three failures lose the `code`/`action`/`title` fields the
  error panel expects (`ui/web_new_v2/js/events.js:277`,
  `ui/web_new_v2/js/feature-controls.js:85-95`). Root cause is in the emitter (WN-06/WN-03).
- **Cross-area observation:** `core/api.py:2698-2714` walks the whole `~/.nedotify/downloads`
  directory on *every* favourite toggle to compute the auto-download quota, and counts orphan files
  (F-WN-13-4). Root cause is in WN-10; it is aggravated by the orphan behaviour in WN-13.
- **Cross-area observation (WN-34, test suite) — the test suite writes into the user's real
  `~/.nedotify/downloads/`.** The `downloader` fixture (`tests/conftest.py:115-129`) does **not** depend
  on `redirect_home` (`tests/conftest.py:170-176`), so any test that runs a worker with the
  `youtube_stub` provider but without that fixture writes `stub_<n>.mp3` into the *real* profile
  directory (`tests/conftest.py:52-61`). The user's real `~/.nedotify/downloads/` currently contains
  9 `gated_*.mp3` files (16 bytes, 2026-10-03, from `_GatedStub` in
  `tests/test_downloader_cancel.py:45-49`) and a `stub_1.mp3` (8207 bytes, written during this audit
  run by a concurrent pytest invocation). `~/.nedotify/` is the user's library (contract #3) and the
  audit brief forbids touching it — the `redirect_home` isolation is therefore not enforced for the
  download path. The existing guard `tests/test_conftest_home_isolation.py` only tests the fixture
  itself, not the downloader tests. *(I did not run pytest and none of my probes wrote these files;
  they are produced by `ServiceStub`/`_GatedStub`.)*

---

### 5. Architecture improvements (ARCH)

- **ARCH-1 — `DownloadManager` is a god object with no visible seams.** One class (909 lines) owns:
  batch accounting (`start_batch`/`_on_batch_task_done`/`_decrement_batch_total_for_dedup`), the queue
  and its backpressure (`_queue`/`_process_queue`/`_wait_for_free_slot`), provider dispatch
  (`_fetch_from_provider`/`_call_provider`/`_download_spotify_track`), retry policy
  (`_fetch_with_retry`/`_is_retryable_error`), progress emission (`_record_progress`), cooperative
  cancellation (`_cancel_epoch`/`_abort_cancelled`/generations), persistence (`DownloadStore` +
  `core/database.py`) and file IO policy (`_downloaded_file_defect`). The three seams the brief asks
  about are *not* visible: there is no provider strategy interface (the provider is chosen by an
  `if/elif` chain at `core/downloader.py:638-656`), the queue is entangled with the pool
  (`_MAX_INFLIGHT` must stay in sync with `max_workers`, as the comment at `core/downloader.py:20-22`
  admits), and persistence is split between two owners of the same table. *Direction*: split into
  `DownloadQueue` (pure queue + backpressure), `DownloadPolicy` (retry/backoff/limits),
  `DownloadProvider` strategies behind one interface, `DownloadProgressReporter`, and let
  `DownloadStore` own the `download_queue` table exclusively.

- **ARCH-2 — `_download_spotify_track` is a provider strategy implemented as a special case inside the
  manager.** `core/downloader.py:473-558` hard-codes the Spotify resolution chain (ytsearch shortcut →
  `TrackResolver` → YouTube search → raw `ytsearch1:`) and bypasses `self._core.spotify` entirely
  (`services/spotify_service.py` has **no** `download_audio_sync`). It also constructs a **fresh
  `TrackResolver` per download** (`core/downloader.py:515-522`), which in turn constructs a fresh
  `SoundCloudService` (`services/track_resolver.py:251-252`) whose `_search_cache` starts empty even
  though `BaseMusicService` shares a class-level cache (`services/base_service.py:124`) — so every
  Spotify download repeats a SoundCloud search that the app could have answered from cache.
  *Direction*: make "resolve a track to a downloadable provider id" a provider strategy
  (`SpotifyDownloadStrategy`), and let the manager depend on the strategy interface rather than on
  `source == 'spotify'`.

- **ARCH-3 — Provider/transfer cooperation is expressed by reflective duck-typing.**
  `core/downloader.py:140-150` decides whether to pass the `DownloadContext` by inspecting the
  callee's signature, and silently falls back to the legacy call `method(source_id, download_dir)`
  when the parameter is missing. That fallback is the only path where the legacy, differently-named
  output templates are used (`services/youtube_service.py:1081`,
  `services/soundcloud_service.py:871`) — i.e. the safety of the filename construction depends on a
  reflective check rather than on a type. `inspect.signature` also costs ~50–100 µs per attempt.
  *Direction*: declare a `DownloadProvider` protocol with `download_audio_sync(source_id, output_dir,
  download_context)`, and adapt the legacy services once instead of reflecting on every call.

- **ARCH-4 — The download-queue table has two owners with two different locking conventions.**
  `core/download_store.py` writes `download_queue` under `DatabaseManager._write_lock`; the sibling
  methods in `core/database.py` (`download_queue_add` 2330, `download_queue_set_status` 2361,
  `download_queue_get_pending` 2408) use the same lock for writes but `download_queue_get_status`
  (2384) reads **without** it. `DownloadManager._init_db_table` (287-331) still carries a complete
  fallback DDL + dedup + unique-index implementation that duplicates
  `core/database.py::ensure_download_queue_table` (2284-2328).
  *Direction*: one owner — either move the table into `core/download_store.py` and delete the
  `database.py` methods, or the reverse — and one locking convention.

- **ARCH-5 — The status vocabulary is duplicated in four places with no single source of truth:**
  `core/downloader.py` (the strings it writes), `core/database.py` (SQL literals in
  `download_queue_add` 2350 and `download_queue_set_downloading` 2377), `core/download_store.py`
  (the ordering CASE, 43-44) and `ui/web_new_v2/js/downloads-view.js:9-12` (`statusLabels`). Adding a
  state requires four coordinated edits and nothing fails if one is missed — the UI falls back to
  `statusLabels[item.status] || item.status` (`downloads-view.js:49`), so an unknown status silently
  renders as a raw English token.
  *Direction*: define the state set once in Python, expose it to the bridge (e.g. in
  `get_downloads`), and generate/validate the JS labels from it.

- **ARCH-6 — The integrity policy is duplicated and can drift.** `core/downloader.py:37-52`
  (`_downloaded_file_defect`) and `services/youtube_service.py:142-163` (`_require_audio_file`)
  implement the *same* policy — audio extension whitelist, `.part` rejection, 4 KiB floor — with
  different exception/message shapes and slightly different extension lists
  (`_AUDIO_DOWNLOAD_EXTS` is defined twice, `core/downloader.py:32-33` and
  `services/youtube_service.py:137-138`). A change to one (e.g. adding `.m4b`) will not reach the
  other, and the two gates disagree on the failure message the user sees.
  *Direction*: one shared predicate in a small module (e.g. `core/audio_integrity.py`) used by both
  the downloader and the providers.

- **ARCH-7 — The provider result is trusted by path, not by handle.** The whole contract between the
  downloader and a provider is "return a path that exists". The downloader then re-derives the file's
  identity from that path (`os.path.basename`, extension, size), which is why the extension whitelist
  has to be duplicated (ARCH-6) and why truncation cannot be detected (F-WN-13-2). A provider returning
  a structured result (`path`, `bytes_expected`, `bytes_written`, `container_ok`) would make both the
  integrity gate and the "complete" decision first-class.
  *Direction*: change the provider interface to return a small result object.

- **ARCH-8 — `DownloadContext` is the right seam, but the download queue's state machine is spread
  across three modules.** The cancellation model (epoch + per-track generation + `paused_track_ids`)
  lives in `core/downloader.py:69-76`, the transfer-level interrupt in `core/download_transfer.py`, and
  the durable part of the state in `core/download_store.py` (`recover`/`preserve_shutdown`). The
  `_abort_cancelled` helper (`core/downloader.py:587-608`) has to reason about both the in-memory
  epoch and the durable status by hand, and it does so correctly — but the resulting state machine
  ("pending / downloading / paused / completed / failed / cancelled" × "epoch / generation /
  resume_on_restart") has no single owner and no single place where the transitions are validated.
  *Direction*: one `DownloadState` object owning the transitions, with the epoch/generation logic
  expressed as a precondition on each transition.
