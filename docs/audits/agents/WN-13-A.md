## AREA WN-13 — Background downloader, download state, transfer control — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/downloader.py` — L1–909 (whole file: `_downloaded_file_defect`, `DownloadManager.__init__`, `_offline`, `get_downloads`, `pause_download`, `resume_download`, `retry_failed_downloads`, `_call_provider`, `_checkpoint_transfer`, `_record_progress`, `_emit`, `start_batch`, `_decrement_batch_total_for_dedup`, `_on_batch_task_done`, `cancel_batch`, `_init_db_table`, `_resume_pending_downloads`, `queue_download`, `_release_track_id`, `_running_futures`, `_wait_for_free_slot`, `_process_queue`, `_download_spotify_track`, `_mark_queue_cancelled`, `_is_cancelled`, `_abort_cancelled`, `_RETRYABLE_MARKS`, `_is_retryable_error`, `_fetch_from_provider`, `_fetch_with_retry`, `_download_worker`, `_execute_download_worker`, `stop`)
- `core/download_store.py` — L1–71 (`DownloadStore.__init__/update/rows/recover/preserve_shutdown`)
- `core/download_transfer.py` — L1–128 (`DownloadInterrupted`, `DownloadContext.__init__/ydl_options/_ydl_progress/download_http`)
- `core/api.py` — L1122–1171 (`AppApi._emit`), L2294–2360 (`download_track`), L3685–3738 (`download_all_favorites`, `cancel_batch_download`), L4129–4191 (`set_offline_mode`, `get_downloads`, `pause/resume/retry_downloads`)
- `core/app.py` — L120–186 (AppCore wiring, `DownloadManager(self)` at L139), L505–584 (`cleanup()`: `downloader.stop` at L546, `db.close` at L560)
- `core/database.py` — L175–205 (`_get_connection`/`conn`), L1278–1283 (`mark_track_downloaded`), L2284–2411 (`ensure_download_queue_table`, `download_queue_add/set_status/set_downloading/get_status/cancel_pending/get_pending`), L2459–2488 (`close`)
- `core/user_errors.py` — L1–24 (`describe_error`)
- `services/youtube_service.py` — L55–84 (`_YT_GATED_MSG`, `_YT_GATING_MARKS`, `_yt_gating_error`), L130–186 (`_require_audio_file`), L1072–1176 (`download_audio_sync`)
- `services/soundcloud_service.py` — L840–958 (`download_audio_sync`)
- `services/yandex_service.py` — L255–280 (`download_audio_sync`, grep-verified)
- `ui/web_new_v2/js/events.js` — L60–294 (event switch: `download_queue_updated`, `download_progress`, `batch_download_*`, `download_complete`, `download_failed`)
- `ui/web_new_v2/js/downloads-view.js` — L1–193 (`handleDownloadManagerEvent`, `runDownloadAction`, `updateDownloadRow`)
- `ui/web_new_v2/js/library.js` — L60–105 (batch progress UI: `batch_download_started/progress/finished/cancelled`)
- `.venv_win/Lib/site-packages/yt_dlp/YoutubeDL.py` — L1177–1182, L3325–3333, L3470–3491, L3510–3594 (yt-dlp 2026.08.19 `overwrites` / `existing_video_file` semantics)
- `concurrent/futures/thread.py` (Python 3.14.7) — `_python_exit` / `threading._register_atexit`
- Tests read: `tests/conftest.py` L1–176, `tests/test_downloader.py`, `tests/test_downloader_cancel.py` (405 L), `tests/test_download_resume.py` (386 L), `tests/test_download_retry.py` (128 L)
- Git history: `76cab49` ("fix(download): retry transient failures instead of failing the track forever"), `531268a` ("fix(download): refuse a broken download instead of marking it complete")

**Callees traced into other areas**

- WN-19 `services/youtube_service.py::download_audio_sync` — yt-dlp options, file naming, `_require_audio_file`
- WN-20 `services/soundcloud_service.py::download_audio_sync` — yt-dlp options, file naming
- WN-21 `services/yandex_service.py::download_audio_sync` — `DownloadContext.download_http` consumer
- WN-12 `core/database.py` — `download_queue_*` helpers, `mark_track_downloaded`, `close()`
- WN-06 `core/api.py::download_track` (L2294–2360) — caller of `queue_download`
- WN-10 `core/api.py::download_all_favorites` (L3685), `cancel_batch_download` (L3730), `pause/resume/retry` (L4183–4190), `set_offline_mode` (L4132)
- WN-02 `core/app.py::cleanup` — `downloader.stop()` → `db.close()` ordering
- WN-28/WN-32 `ui/web_new_v2/js/events.js`, `js/library.js`, `js/downloads-view.js` — event-name/payload contract

**Reproduction harnesses written (scratch, outside the repo)**

- `%TEMP%\opencode\wn13_repro.py` — batch accounting on pause / cancel race
- `%TEMP%\opencode\wn13_repro2.py` — yt-dlp option capture, `stop()` drain, resume/retry inputs
- `%TEMP%\opencode\wn13_repro3.py` — `stop()` drain with the real processor, crash resume, cancel scope, offline batch
- `%TEMP%\opencode\wn13_repro4.py` — retry classification vs. the provider's message masking
- `%TEMP%\opencode\wn13_repro5.py` — process-exit behaviour of a live `ThreadPoolExecutor` worker

---

### 2. Findings

#### F-WN-13-1  [P1] — Pausing a download silently drops its batch task, so `batch_download_finished` never fires

- **File:** `core/downloader.py:108-112` (queue item removed, no batch accounting), `core/downloader.py:587-599` (`_abort_cancelled` paused branch), `core/downloader.py:213-226` (`_on_batch_task_done` is the only place `_batch_completed` grows), `core/downloader.py:225` (`finished = completed >= total`)
- **Confirmed:** yes
- **Description:** `pause_download()` removes the paused tracks from the in-memory queue and, for a track that is currently downloading, the worker aborts through `_abort_cancelled()`. Neither path accounts the task to the batch: `_batch_completed` is only incremented in `_on_batch_task_done()`, and the paused branch of `_abort_cancelled()` returns `True` **without** calling it. The batch denominator therefore keeps a task that will never report, so `completed >= total` is never reached and `batch_download_finished` is never emitted.
- **Cause:** the batch accounting lives only on the "task finished" path; "task removed/paused" is not a terminal state the accounting knows about.
- **Trigger conditions:** any batch download in progress + the user presses "Пауза" on one track, or "Пауза всех", or toggles offline mode (which calls `downloader.pause_download()` from `core/api.py:4142`).
- **User impact:** the batch progress bar in the library view freezes at `N-1 / N` forever, the "✅ Загрузка завершена" toast never appears, and `_batch_active` stays `True` so the next batch's counters start from a corrupted base. The user must cancel the batch to get the UI unstuck.
- **Evidence:**
  ```python
  # core/downloader.py:104-113  (pause_download)
  with self._lock:
      for target in targets:
          self._paused_track_ids.add(target)
          self._track_generations[target] = self._track_generations.get(target, 0) + 1
  with self._queue_lock:
      self._queue = [item for item in self._queue if item['track_id'] not in targets]
  for target in targets:
      self._store.update(target, status='paused', resume_on_restart=0)
  ```
  ```python
  # core/downloader.py:587-599  (_abort_cancelled) - the paused branch returns
  # True WITHOUT calling _on_batch_task_done()
  if context:
      try:
          context.checkpoint()
      except DownloadInterrupted:
          if not self._is_cancelled(epoch):
              with self._lock:
                  paused = track_id in self._paused_track_ids
              if paused:
                  self._store.update(track_id, status='paused')
              return True
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro.py`
  - S1 (pending item paused): `start_batch(2)`, queue 2 tracks, `pause_download(t1)` → queue `[t2]`, `batch_total=2 completed=0 active=True`; after the surviving worker finishes → `batch_total=2 completed=1 active=True`, emitted batch events `['batch_download_progress']` — **no `batch_download_finished`**.
  - S2 (in-flight item paused): `start_batch(1)`, a gated provider, `pause_download(t)` mid-transfer → worker exits, `batch_total=1 completed=0 active=True`, emitted batch events `[]` — **no `batch_download_finished`**.
  - Frontend contract that is broken: `ui/web_new_v2/js/library.js:92-101` only hides the progress box on `nedotify:batch_download_finished`.
- **Suggested fix:** give "paused / de-queued" a terminal accounting path — e.g. `_on_batch_task_done(track_id, success=False)` (or a dedicated "skipped" counter) when `pause_download()` removes an item from `_queue`, and in the paused branch of `_abort_cancelled()`.
- **Fix side effects:** the batch would then report the paused track as failed/finished; the UI text "Загрузка завершена (N треков)" would count it. Need to decide whether "skipped" gets its own counter so the message is not misleading.
- **Discovered by:** A

#### F-WN-13-2  [P2] — Offline mode makes `queue_download()` report "queued" while queueing nothing, so the batch can never finish

- **File:** `core/downloader.py:378-383` (`queue_download`, offline branch), `core/downloader.py:185-191` (`start_batch`), `core/api.py:3717-3718` (`download_all_favorites` loop)
- **Confirmed:** yes
- **Description:** in offline mode `queue_download()` adds the track to `_paused_track_ids`, sets the row to `paused` and returns `True` — but the item is never appended to `self._queue`, so no worker will ever run for it and no `_on_batch_task_done()` will ever be called for it. The caller (`api.download_track`) counts it as queued, and `download_all_favorites` has already sized the batch with it.
- **Cause:** the offline branch returns the same `True` as the "really queued" path but takes a completely different code path (no queue entry, no future).
- **Trigger conditions:** offline mode enabled + "Скачать все избранное" (or any batch containing an offline-paused track). `DownloadManager.__init__` also calls `self.pause_download()` when offline (`core/downloader.py:87-88`).
- **User impact:** the batch progress box shows `0 / N` and never terminates; the batch denominator stays inflated for every later batch.
- **Evidence:**
  ```python
  # core/downloader.py:378-383
  if self._offline():
      with self._lock:
          self._paused_track_ids.add(track_id)
      self._store.update(track_id, status='paused', error='')
      self._emit('download_queue_updated', {'track_id': track_id, 'status': 'paused'})
      return True
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro3.py` S10: offline settings + `start_batch(1)` + `queue_download(...)` → returns `True`, `in-memory queue: []`, `row status: paused`, `batch_total=1 completed=0 active=True`, emitted batch events `[]`.
- **Suggested fix:** either return `False` from the offline branch (and let `download_all_favorites` shrink the denominator), or account the task as skipped immediately.
- **Fix side effects:** `api.download_track` returns `False` to the UI, which currently shows the download button as not queued; the UI would need to show the "paused because offline" reason instead.
- **Discovered by:** A

#### F-WN-13-3  [P2] — `cancel_batch()` cancels downloads that were never part of the batch

- **File:** `core/downloader.py:249-251` (`self._queue.clear()`), `core/downloader.py:281-282` (all `pending`/`downloading`/`cancelled` rows → `cancelled`), `core/downloader.py:249` (global epoch bump)
- **Confirmed:** yes
- **Description:** `cancel_batch()` clears the *entire* in-memory queue and marks *every* queue row `pending`/`downloading` as `cancelled`. The batch counters are the only batch-scoped structure; the queue and the epoch are global. A single track the user queued from the track menu (not part of any batch) is therefore cancelled together with the batch, and its DB row is flipped to `cancelled` even though the user never asked for that.
- **Cause:** the queue and the cancellation epoch are global, but the concept "batch" is only a counter triple — there is no per-batch membership.
- **Trigger conditions:** the user queues one track individually, then starts "Скачать все избранное", then presses "Отменить" in the batch progress box (`ui/web_new_v2/js/library.js:67-74`).
- **User impact:** the individual download is silently cancelled; its row shows "Отменено" and the track is not downloaded even though the user never cancelled it.
- **Evidence:**
  ```python
  # core/downloader.py:249-251
  self._cancel_epoch += 1
  with self._queue_lock:
      self._queue.clear()
  ```
  ```python
  # core/downloader.py:281-282
  for row in self._store.rows(('pending', 'downloading', 'cancelled'), limit=5000):
      self._store.update(row['track_id'], status='cancelled', resume_on_restart=0)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro3.py` S9: queue a "single" track, `start_batch(1)`, queue a batch track, `cancel_batch()` → `status of the SINGLE (non-batch) download: cancelled`.
- **Suggested fix:** track batch membership per queue item (e.g. a `batch_id` on the item) and scope both the queue purge and the epoch bump to it, or give `cancel_batch()` a "cancel everything" semantic that the UI states explicitly.
- **Fix side effects:** the "cancel batch" button would stop cancelling individually queued downloads — behaviour change the user may or may not want; the batch epoch would need to become per-batch rather than global.
- **Discovered by:** A

#### F-WN-13-4  [P2] — `DownloadContext.ydl_options()` forces `overwrites=False`, neutralising the provider's "do not reuse a leftover" guard

- **File:** `core/download_transfer.py:24-32` (`'overwrites': False`), `services/youtube_service.py:1102-1108` (`"overwrites": True` then the context update), `services/youtube_service.py:1151-1176` (the file-lookup paths)
- **Confirmed:** yes
- **Description:** `YouTubeService.download_audio_sync()` deliberately sets `overwrites: True` — with the comment *"A previous partial download of the same id must not be reused: yt-dlp skips an existing file by default, so a 0-byte or truncated leftover silently became 'the download'"* — but it applies the `DownloadContext` options **after** that, and `DownloadContext.ydl_options()` hard-codes `'overwrites': False`. The downloader always creates a `DownloadContext` (`core/downloader.py:730-733`), so the guard is dead in exactly the path it was written for. With `overwrites=False`, yt-dlp's `existing_video_file()` returns the pre-existing file and the download is skipped entirely ("has already been downloaded").
- **Cause:** option-merging order — the context's fixed option set wins over the caller's explicit override.
- **Trigger conditions:** any leftover file at the deterministic final path `download_<track_id>_<digest>_<videoid>.<ext>` (a 0-byte/truncated file left by an earlier interrupted run, or by an older build that used the `yt_<id>_<ts>` naming).
- **User impact:** yt-dlp reports success without transferring a byte. The downloader then applies `_downloaded_file_defect()`: a sub-4 KiB or non-audio leftover is deleted and the track is marked **failed permanently** (the message "файл повреждён (N байт)" is not in `_RETRYABLE_MARKS`), so the user's first attempt fails and a second click is needed; a larger leftover passes the gate and is marked *downloaded* even though it is not the audio.
- **Evidence:**
  ```python
  # core/download_transfer.py:24-32
  def ydl_options(self, output_dir):
      self.checkpoint()
      return {
          'outtmpl': os.path.join(output_dir, self.stem + '_%(id)s.%(ext)s'),
          'continuedl': True,
          'overwrites': False,     # <-- clobbers the provider's overwrites=True
          'nopart': False,
          'progress_hooks': [self._ydl_progress],
      }
  ```
  ```python
  # services/youtube_service.py:1102-1108
  # A previous partial download of the same id must not be reused:
  # yt-dlp skips an existing file by default, so a 0-byte or truncated
  # leftover silently became "the download".
  "overwrites": True,
  })
  if download_context:
      ydl_opts.update(download_context.ydl_options(output_dir))   # <-- sets it back to False
  ```
  yt-dlp 2026.08.19 `YoutubeDL.py:3325-3333`:
  ```python
  def existing_file(self, filepaths, *, default_overwrite=True):
      existing_files = list(filter(os.path.exists, orderedSet(filepaths)))
      if existing_files and not self.params.get('overwrites', default_overwrite):
          return existing_files[0]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro2.py` S5 captures the real options the downloader hands to yt-dlp: `outtmpl: ...\download_1_fbed31a39fab4846_%(id)s.%(ext)s`, `continuedl: True`, **`overwrites: False`**, `nopart: False` — although `youtube_service.py:1105` sets `True`.
- **Suggested fix:** do not let the context override an option the caller set explicitly (e.g. only supply `overwrites` when the caller did not), or set `"overwrites": True` after the context update; `continuedl`/`nopart`/`outtmpl` should stay context-owned.
- **Fix side effects:** re-downloading over an existing complete file costs bandwidth; the resume feature relies on `.part` files, not on the final file, so `overwrites: True` does not break resume (`continuedl` is unaffected).
- **Discovered by:** A (the clobbering half lives in WN-13 `core/download_transfer.py`; the option it clobbers is set in WN-19 `services/youtube_service.py`)

#### F-WN-13-5  [P1] — The retry fix never fires for the canonical transient YouTube failure: the provider replaces the message before the classifier sees it

- **File:** `core/downloader.py:612-627` (`_RETRYABLE_MARKS`, `_is_retryable_error`), `core/downloader.py:689-694` (classification inside `_fetch_with_retry`), `services/youtube_service.py:1129-1139` and `:75-79` (`_yt_gating_error` masking — WN-19)
- **Confirmed:** yes
- **Description:** commit `76cab49` ("retry transient failures instead of failing the track forever") adds the mark `'page needs to be reloaded'` to `_RETRYABLE_MARKS` — the exact yt-dlp text for the "PO token not refreshed" case named in the commit message. But the only provider that produces that text is the YouTube provider, and it **rewrites** it: `_yt_gating_error()` sees `"needs to be reloaded"` in `_YT_GATING_MARKS` and replaces the exception with `_YT_GATED_MSG` (a Russian anti-bot message). The downloader classifies only `str(exc)` of the top-level exception, so the retryable mark is unreachable and the track fails permanently on the first attempt.
- **Cause:** the classifier matches on a user-facing message that the callee has already translated; the original text survives only in `exc.__cause__` (the provider uses `raise ... from exc`), which is never inspected.
- **Trigger conditions:** any YouTube download that hits the anti-bot/PO-token gate ("The page needs to be reloaded", "Sign in to confirm you're not a bot", "confirm you're not a bot").
- **User impact:** exactly the scenario the fix was written for still fails the track permanently; the user must retry manually and the "Повторить ошибки" button does not help either (the same gate is hit again).
- **Evidence:**
  ```python
  # core/downloader.py:612-619
  _RETRYABLE_MARKS = (
      'page needs to be reloaded', 'unable to download webpage',
      ...
  )
  ```
  ```python
  # services/youtube_service.py:75-79  (WN-19)
  def _yt_gating_error(exc):
      """Map yt-dlp anti-bot failures to an actionable message."""
      if any(m in str(exc).lower() for m in _YT_GATING_MARKS):
          return Exception(_YT_GATED_MSG)
      return exc
  ```
  ```python
  # core/downloader.py:689-694
  except Exception as exc:
      if self._abort_cancelled(track_id, epoch, 'provider-interrupted'):
          return None
      last_error = exc
      if not self._is_retryable_error(exc):
          raise
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro4.py`:
  `raw yt-dlp message : ERROR: [youtube] abc: The page needs to be reloaded. Please reload the page.`
  `after provider mask: YouTube не отдал аудиоформаты (anti-bot гейт: доступны только превью). …`
  `retryable(raw yt-dlp message)   : True`
  `retryable(message the app sees) : False`
- **Suggested fix:** classify on the whole exception chain (`exc`, `exc.__cause__`, `exc.__context__`) and/or keep the original yt-dlp text on the raised exception (e.g. attach it as `__cause__` and match on it); alternatively add the provider's Russian gating message to `_RETRYABLE_MARKS` — but that would also retry genuinely DRM/gated tracks.
- **Fix side effects:** retrying the anti-bot gate three times with 20 s + 40 s backoff occupies a worker slot for a minute and may hammer the provider, which is exactly what the backoff was meant to avoid. The gate is only transient with valid cookies / a refreshed PO token.
- **Discovered by:** A (classifier in WN-13; the message masking is in WN-19)

#### F-WN-13-6  [P2] — The retryable classification is inverted for the common HTTP cases: 404 is retried, 500 is not, 401/403 are

- **File:** `core/downloader.py:612-627` (`_RETRYABLE_MARKS` / `_is_retryable_error`), `core/downloader.py:664-711` (`_fetch_with_retry`)
- **Confirmed:** yes
- **Description:** `_is_retryable_error()` is a pure substring test over a fixed mark list. The list contains `'unable to download webpage'`, which is yt-dlp's wrapper for *any* non-2xx page fetch — including 404. So a deleted/private video is retried 3× with 20 s + 40 s of backoff. At the same time a bare `HTTP Error 500` is **not** retried (only 502/503/504 are listed), although a 500 is a textbook transient error. `401`/`403` **are** retried, although they are usually permanent (geo-block, age gate, DRM).
- **Cause:** mark-based classification on free-form provider text instead of on a status code; the marks were picked per yt-dlp phrase rather than per failure class.
- **Trigger conditions:** any unavailable video (404), any provider 5xx that is not 502/503/504, any geo-blocked/DRM track.
- **User impact:** unavailable tracks burn 60 s of worker time each. With `_MAX_INFLIGHT = 2` (`core/downloader.py:22`) two such tracks block the whole download queue for a minute — the visible symptom is "the download bar does not move" rather than "this track failed".
- **Evidence:**
  ```python
  # core/downloader.py:612-619
  _RETRYABLE_MARKS = (
      'page needs to be reloaded', 'unable to download webpage',
      'unable to download api page', 'unable to download json metadata',
      'http error 429', 'http error 502', 'http error 503', 'http error 504',
      'timed out', 'timeout', 'connection', 'temporarily unavailable',
      'rate limit', 'rate-limited', 'try again later', 'ssl', 'handshake',
      'unauthorized', 'forbidden',
  )
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro4.py` output:
  ```
  FAIL     HTTP Error 404: Not Found
  RETRY    HTTP Error 403: Forbidden
  RETRY    HTTP Error 429: Too Many Requests
  FAIL     HTTP Error 500: Internal Server Error
  RETRY    HTTP Error 502: Bad Gateway
  RETRY    HTTP Error 503: Service Unavailable
  RETRY    HTTP Error 401: Unauthorized
  FAIL     This video is DRM protected
  FAIL     Video unavailable. This video is private.
  FAIL     Sign in to confirm you're not a bot
  RETRY    Unable to download webpage: HTTP Error 404: Not Found
  RETRY    Connection reset by peer
  FAIL     The uploader has not made this video available in your country
  ```
  Note the two 404 lines: the bare status is *not* retried, but the same 404 wrapped in yt-dlp's "Unable to download webpage" prefix **is** — and that wrapped form is what yt-dlp actually produces.
- **Suggested fix:** parse the status code out of the message (`http error (\d{3})`) and classify on it (retry 408/429/5xx; do not retry 401/403/404), and treat the "unable to download webpage" wrapper as transparent rather than as a retryable mark in itself.
- **Fix side effects:** a provider that only reports a generic "unable to download webpage" without a status would stop being retried; keep the generic mark as a fallback only when no status can be parsed.
- **Discovered by:** A

#### F-WN-13-7  [P1] — `stop()` returns while a worker is still running: the DB is closed under it and the process cannot exit

- **File:** `core/downloader.py:884-909` (`stop`), `core/app.py:546` (`downloader.stop`) and `core/app.py:560` (`db.close`), `core/downloader.py:22` (`_MAX_INFLIGHT`)
- **Confirmed:** yes
- **Description:** `stop(drain_timeout=5.0)` bumps the epoch and waits up to the timeout for the running futures. The timeout **is** honoured, but a worker blocked inside a provider call that does not poll the checkpoint (yt-dlp sitting in a socket read — `socket_timeout: 30`, `retries: 5`) is still running when `stop()` returns. `core/app.py::cleanup()` then closes the database (`db.close()` at L560) while that worker is alive, so the worker's next DB call hits `sqlite3.ProgrammingError: Cannot operate on a closed database` (the thread-local connection object is still set, so `_get_connection()` hands back the closed handle). Worse: `ThreadPoolExecutor`'s `concurrent.futures.thread._python_exit` is registered with `threading._register_atexit`, so the interpreter joins the pool worker threads at exit — the process stays alive (window gone, process still there) until the transfer finishes.
- **Cause:** the drain is bounded by a timeout, but nothing enforces the abort on a provider that does not poll `DownloadContext.checkpoint()`, and the pool's atexit hook is not accounted for in the shutdown budget.
- **Trigger conditions:** the user closes the app (or the watchdog restarts it) while a YouTube/SoundCloud transfer is in a socket read. The provider only polls the checkpoint in the yt-dlp *progress hook*, so a long metadata extraction or a stalled fragment is not interruptible.
- **User impact:** the app does not exit promptly after the window closes (up to minutes with yt-dlp's 30 s × 5 retries); the log fills with "Cannot operate on a closed database"; the queue row is left in `downloading` until the worker finally aborts (it is recoverable: `preserve_shutdown()` sets `resume_on_restart = 1`, so the next start re-arms it).
- **Evidence:**
  ```python
  # core/downloader.py:893-907
  self._running = False
  self._cancel_epoch += 1
  self._queue_event.set()
  with self._queue_lock:
      self._queue.clear()
  self._pool.shutdown(wait=False, cancel_futures=True)
  deadline = time.monotonic() + max(0.0, float(drain_timeout))
  for fut in self._running_futures():
      remaining = deadline - time.monotonic()
      if remaining <= 0:
          break
      try:
          fut.result(timeout=remaining)
      except Exception as e:
          logger.debug(f"Download worker did not finish before shutdown: {e}")
  ```
  ```python
  # core/app.py:545-560
  if getattr(self, "downloader", None):
      _step("downloader.stop", self.downloader.stop)
  ...
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro3.py` S6b (provider that never calls `checkpoint()`):
  ```
  inflight futures: 1
  stop() returned after 1.00s (drain_timeout=1.0)
  worker still alive after stop()?  True
  queue row status after stop(): downloading
  ```
  `%TEMP%\opencode\wn13_repro5.py` (process lifetime): a script whose `main()` returns immediately while a 4 s pool task runs → **process wall time 4.29 s** — the interpreter waits for the pool thread via `concurrent.futures.thread._python_exit`.
- **Suggested fix:** make the abort observable to a provider that is not polling (e.g. a socket/connect timeout well under the drain budget, or a `socket_timeout` that shrinks once the epoch is bumped), and treat the pool's atexit join as part of the shutdown budget (e.g. `os._exit` after cleanup, or a watchdog that force-kills the pool).
- **Fix side effects:** a shorter provider timeout means more spurious failures on slow links; forcing the exit can truncate a WAL checkpoint (the DB is already closed at that point in `cleanup()`, so the risk is limited to the log).
- **Discovered by:** A

#### F-WN-13-8  [P2] — `cancel_batch()` can emit a second batch terminator (`batch_download_finished` next to `batch_download_cancelled`)

- **File:** `core/downloader.py:249` (epoch bump), `core/downloader.py:267-271` (`_batch_active = False` under `_lock`), `core/downloader.py:604-607` (`_abort_cancelled` → `_on_batch_task_done`)
- **Confirmed:** yes
- **Description:** `cancel_batch()` bumps the global epoch **first** and closes the batch (`_batch_active = False`) a few instructions later. A worker that observes the epoch bump in that window aborts, calls `_on_batch_task_done(success=False)`, and — because `_batch_active` is still `True` — increments `_batch_completed` and can emit `batch_download_finished`. `cancel_batch()` then emits `batch_download_cancelled`. The UI receives two terminators for one batch.
- **Cause:** the epoch bump and the batch close are not atomic with respect to each other; the batch is closed *after* the cancellation is already observable.
- **Trigger conditions:** the user cancels a batch while a transfer is finishing — a narrow but real window.
- **User impact:** the library view shows the success toast "✅ Загрузка завершена (1 треков)" for a batch the user just cancelled, and the progress box is hidden twice. The repo's own contract test (`tests/test_downloader_cancel.py:150-180`, "the batch progress bar always terminates with exactly one event") documents that exactly one terminator is required — the test only passes because its stub blocks the provider for 10 s.
- **Evidence:**
  ```python
  # core/downloader.py:249 and :267-271
  self._cancel_epoch += 1
  ...
  with self._lock:
      self._batch_active = False
      self._batch_total = 0
  ```
  ```python
  # core/downloader.py:604-607
  self._mark_queue_cancelled(track_id)
  # Account for the batch. Right after a cancel_batch() the batch is already
  # closed (_batch_active False), so this is a no-op and emits nothing
  self._on_batch_task_done(track_id, success=False)
  ```
  The comment states the assumption ("Right after a cancel_batch() the batch is already closed") — which the epoch-first ordering does not guarantee.
- **Reproduction / verification:** `%TEMP%\opencode\wn13_repro.py` S4 (the epoch is bumped inside the cancel window, i.e. exactly what happens when the worker wins the race):
  ```
  emitted batch events: ['batch_download_progress', 'batch_download_finished', 'batch_download_cancelled']
  RESULT: finished+cancelled together is a double terminator: True
  ```
- **Suggested fix:** close the batch (`_batch_active = False`) **before** bumping the epoch, and/or make `_on_batch_task_done` a no-op for a cancelled generation (e.g. pass the epoch and ignore stale ones).
- **Fix side effects:** closing the batch first means a worker that aborts a few microseconds earlier is not counted at all — which is the intended behaviour for a cancelled batch.
- **Discovered by:** A

#### F-WN-13-9  [P3] — A late exception after the "completed" write flips the row to `failed` while `is_downloaded = 1`

- **File:** `core/downloader.py:828-840` (success path) vs `core/downloader.py:863-882` (the catch-all handler)
- **Confirmed:** hypothesis (the window is narrow; not reproduced with a deterministic stub)
- **Description:** the success path writes `is_downloaded = 1`, `download_queue_set_status(track_id, 'completed')`, then calls `self._store.update(track_id, status='completed', ..., downloaded_bytes=os.path.getsize(file_path), total_bytes=os.path.getsize(file_path))`. If anything in that tail raises (the file is deleted between the two `os.path.getsize()` calls, or the DB is closed — see F-WN-13-7), the catch-all handler runs and sets the queue row to `failed` and emits `download_failed`, while the track is already `is_downloaded = 1` with a valid `file_path`.
- **Cause:** the catch-all handler cannot distinguish "the download failed" from "something failed *after* the download succeeded".
- **Trigger conditions:** the audio file is removed concurrently (clean-up job, the user in Explorer) or the DB is closed under the worker at shutdown.
- **User impact:** contradictory state — the track is in the library and downloadable, but the queue shows "Ошибка" and the user gets a red "Ошибка скачивания" toast for a download that actually succeeded.
- **Evidence:**
  ```python
  # core/downloader.py:836-839
  self._store.update(track_id, status='completed', error='', resume_on_restart=0,
                     downloaded_bytes=os.path.getsize(file_path), total_bytes=os.path.getsize(file_path))
  ...
  self._emit('download_complete', {'track_id': track_id})
  ```
  ```python
  # core/downloader.py:863-882 (catch-all)
  except Exception as e:
      if self._abort_cancelled(track_id, epoch, 'worker-interrupted'):
          return
      logger.error(f'Download worker failed for {track_id}: {e}')
      if hasattr(self._core.db, 'download_queue_set_status'):
          try:
              self._core.db.download_queue_set_status(track_id, 'failed')
  ```
- **Reproduction / verification:** not reproduced (no deterministic trigger found in the sandbox); the ordering is visible in the source above. Missing evidence: a way to delete the file between L836 and L837 deterministically — e.g. a `DownloadStore.update` monkeypatch that removes the file before delegating.
- **Suggested fix:** set the terminal state once, at the very end of the success path (or guard the catch-all with "was the row already marked completed?").
- **Fix side effects:** a genuinely failed `mark_track_downloaded` must still produce a `failed` row — the guard has to distinguish "the DB write failed" from "a post-success step failed".
- **Discovered by:** A

#### F-WN-13-10  [P3] — The integrity gate only checks the extension and a 4 KiB floor, so a truncated audio file is still marked "complete"

- **File:** `core/downloader.py:37-52` (`_downloaded_file_defect`), `core/downloader.py:801-814` (the gate before `mark_track_downloaded`), `core/downloader.py:32-34` (`_AUDIO_DOWNLOAD_EXTS`, `_MIN_AUDIO_BYTES = 4 * 1024`)
- **Confirmed:** yes
- **Description:** the gate added by commit `531268a` rejects a missing file, a `.part` name, a non-audio extension and anything under 4 KiB. A truncated-but-large audio file (e.g. a 2 MB fragment of a 9 MB track) passes all four checks and is then written into the library as `is_downloaded = 1` with `download_complete` emitted — the exact failure mode the commit set out to eliminate, only narrowed to a size floor.
- **Cause:** the check is a static file inspection; there is no structural validation (duration, decodability) and no comparison against an expected size (the provider knows `Content-Length` / the yt-dlp `filesize`, but it is not passed on).
- **Trigger conditions:** the transfer is cut after 4 KiB but the file is renamed into place (or the file is truncated on disk later).
- **User impact:** the track appears in the library and silently plays only a fragment, or plays nothing.
- **Evidence:**
  ```python
  # core/downloader.py:37-52
  def _downloaded_file_defect(path: str) -> str:
      """Why *path* is not a usable download, or '' when it looks fine."""
      if not path or not os.path.isfile(path):
          return 'файл не найден'
      name = os.path.basename(path)
      if name.endswith('.part'):
          return f'незавершённая загрузка ({name})'
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
- **Reproduction / verification:** by inspection — any file ≥ 4096 bytes with an audio extension returns `''` from `_downloaded_file_defect` and is accepted at `core/downloader.py:807-819`.
- **Suggested fix:** compare the final size against the size the provider reported (`total_bytes` is already tracked in the queue row via `_record_progress`), and/or probe the container (mutagen/ffprobe) for a decodable duration.
- **Fix side effects:** an expected-size comparison needs the provider to report a trustworthy total (yt-dlp's `filesize` is an estimate for some formats); a duration probe costs a file open per download.
- **Discovered by:** A

#### F-WN-13-11  [P3] — The retry backoff sleeps while holding one of only two worker slots

- **File:** `core/downloader.py:22` (`_MAX_INFLIGHT = 2`), `core/downloader.py:700-709` (the sliced sleep inside `_fetch_with_retry`), `core/downloader.py:423-435` (`_wait_for_free_slot`)
- **Confirmed:** yes
- **Description:** the 20 s + 40 s backoff is implemented as `time.sleep()` **inside the pool worker**, so a retrying track occupies one of the two pool slots for up to a minute while doing nothing. Two transiently failing tracks therefore stall every other download in the queue for a minute each; the UI shows "0 / 2" progress and no explanation.
- **Cause:** the backoff is coupled to the worker thread instead of being scheduled outside the pool.
- **Trigger conditions:** two consecutive transient provider errors (429, timeout, SSL) — exactly the situation the backoff was written for.
- **User impact:** the download queue appears frozen; unrelated tracks are not started for up to a minute.
- **Evidence:**
  ```python
  # core/downloader.py:701-709
  # Sleep in slices so a cancel_batch() is honoured immediately
  # instead of after the full delay.
  slept = 0.0
  while slept < delay:
      if self._abort_cancelled(track_id, epoch, 'retry-wait'):
          return None
      time.sleep(min(1.0, delay - slept))
      slept += 1.0
  delay *= 2
  ```
  ```python
  # core/downloader.py:22
  _MAX_INFLIGHT = 2
  ```
- **Reproduction / verification:** by inspection of the pool width plus the sleep location; `tests/test_download_retry.py:81-88` pins the 20 s/40 s/80 s growth but not the slot occupancy.
- **Suggested fix:** release the worker slot during the backoff (re-queue the task with a "not before" timestamp) or raise `_MAX_INFLIGHT` and keep the provider-facing concurrency at 2 via a separate semaphore.
- **Fix side effects:** re-queueing needs an extra timestamp field in the queue row and complicates the epoch/generation bookkeeping; a separate semaphore adds a second concurrency control to keep in sync.
- **Discovered by:** A

#### F-WN-13-12  [P3] — `api.download_track`'s error path shrinks the batch denominator for a track that was actually queued (call site in WN-06)

- **File:** `core/api.py:2346-2355` (`download_track` → `queue_download` → `_decrement_batch_total_for_dedup()`), `core/downloader.py:193-211` (`_decrement_batch_total_for_dedup`), `core/downloader.py:405-410` (the tail of `queue_download` that can raise)
- **Confirmed:** hypothesis (the exception path needs a failing `DownloadStore.update`; the code path itself is confirmed)
- **Description:** `queue_download()` appends the item to the queue and *then* calls `self._store.update(track_id, error='')` and `self._emit(...)`. If the DB write raises at that point (closed DB, locked file), the exception reaches `api.download_track`, which calls `_decrement_batch_total_for_dedup()` — but the track **is** queued and will still run and call `_on_batch_task_done()`. The batch denominator is one too small, so the batch finishes one task early and the progress count is wrong.
- **Cause:** the caller assumes "an exception from `queue_download` means nothing was queued", which is false for exceptions raised after the queue append.
- **Trigger conditions:** the DB is closed/locked while a batch is being queued (shutdown race) — `queue_download` is called from the bridge thread.
- **User impact:** the batch progress shows `N-1 / N` and terminates one track early; the last track still downloads, but its `batch_download_progress` event arrives after `batch_download_finished`.
- **Evidence:**
  ```python
  # core/api.py:2346-2355
  try:
      queued = self._core.downloader.queue_download(track_id, source, str(source_id))
  except Exception as e:
      logger.error(f"download_track: queue_download failed for {track_id}: {e}")
      try:
          self._emit("download_failed", {"track_id": track_id, "error": str(e)})
      except Exception:
          pass
      self._core.downloader._decrement_batch_total_for_dedup()
      return False
  ```
  ```python
  # core/downloader.py:405-410 (the tail that can raise after the append)
  if duplicate:
      self._decrement_batch_total_for_dedup()
      return False
  logger.info(f'Queued download for track {track_id} from {source}:{source_id}')
  self._store.update(track_id, error='')          # <-- can raise here
  self._emit('download_queue_updated', {'track_id': track_id, 'status': 'pending'})
  return True
  ```
- **Reproduction / verification:** not reproduced; the ordering is confirmed by reading `queue_download` (`core/downloader.py:388-410`). Missing evidence: a deterministic way to make `DownloadStore.update` raise (e.g. closing the DB between the append and the update) — the harness would need to close `db.conn` while `download_all_favorites` is looping.
- **Suggested fix:** have `queue_download()` report *whether* it queued (e.g. return a tri-state or raise only before the append), and let the caller decrement only on "not queued".
- **Fix side effects:** `queue_download()` is used by `api.download_track`, `resume_download`, `retry_failed_downloads` and `_resume_pending_downloads`; the return contract is shared with the UI (`download_track` returns a bool).
- **Discovered by:** A (root cause in WN-13 `queue_download`; the call site is in WN-06 `core/api.py::download_track`)

---

### 3. Clean areas

Checked and found correct:

- **Cancellation epoch (`_is_cancelled` / `_abort_cancelled`, `core/downloader.py:579-608`).** The epoch is a single monotonic counter, captured per queue item at `queue_download` time (`core/downloader.py:396`) and compared with `!=`; a stale epoch can therefore never abort a download queued *after* a cancel, and a cancel cannot leave a "stuck global cancelled" flag. Items queued after `cancel_batch()` carry the new epoch and run normally — verified by the repo's own `tests/test_downloader_cancel.py:206-220` and re-confirmed here. The stale-epoch abort never writes the file or marks the row complete: the abort is checked at five stage boundaries (`before-start`, `before-db-mark`, `after-db-mark`, `before-provider`, `after-provider`) *and* after the provider returns (`core/downloader.py:798`), before `mark_track_downloaded`.
- **Pause/resume generation mechanism (`core/downloader.py:101-128`, `core/downloader.py:718-728`).** `pause_download` bumps `_track_generations[track]`; `resume_download` re-queues with the *current* generation, so the old in-flight worker sees `stale` and aborts while the new worker runs. No duplicate download and no stale write (verified by `tests/test_download_resume.py:60-90`).
- **The "refuse a broken download" gate placement (`core/downloader.py:801-819`).** `_downloaded_file_defect()` runs **before** `mark_track_downloaded()`, before `download_queue_set_status(..., 'completed')` and before `download_complete` is emitted — the fix from commit `531268a` is wired in the right order (its *strength* is limited, see F-WN-13-10).
- **Atomic file creation.** The final audio file is only created by a rename: yt-dlp writes `<final>.part` and renames (WN-19/WN-20), and `DownloadContext.download_http` writes `<final>.part` and `os.replace()`s it (`core/download_transfer.py:109-119`). The downloader never truncates or writes the final path itself, so a crash cannot leave a half-written file at the final path — with the caveat of F-WN-13-4 (yt-dlp may *skip* a re-download when a leftover exists).
- **Cooperative transfer wiring (`core/download_transfer.py`, `core/downloader.py:140-155`, `core/downloader.py:718-733`).** `DownloadContext.checkpoint` is wired into every provider: `ydl_options()` calls `checkpoint()` before returning the options and the yt-dlp progress hook calls it on every chunk (`core/download_transfer.py:34-39`); `download_http` calls it before the request, on every 128 KiB chunk and before the rename (`core/download_transfer.py:45, 66, 111, 116`). The YouTube, SoundCloud and Yandex providers all accept `download_context` and poll it. Cancellation therefore interrupts an in-flight transfer, not just the queue.
- **`download_complete` payload contract.** `self._emit('download_complete', {'track_id': track_id})` (`core/downloader.py:839`) carries **no** `file_path`, matching contract #7 and `ui/web_new_v2/js/events.js:258-264`.
- **`download_failed` payload.** `{'track_id', 'error'}` enriched with `describe_error()` (`core/downloader.py:171-183`) → JSON-serialisable, with `code`/`title`/`message`/`action`; matches what `ui/web_new_v2/js/events.js:266-280` reads (`data.error`, `data.title`).
- **No `_emit` on the UI thread.** The downloader's `_emit` (`core/downloader.py:171-183`) only delegates to `api._emit`, and `AppApi._emit` (`core/api.py:1122-1159`) hands the call to an `EmitWorker` thread when it runs on the main thread. The downloader itself never touches `evaluate_js`. All downloader emits happen on pool/processor threads.
- **Emits are not made while holding the internal locks.** `_decrement_batch_total_for_dedup` and `_on_batch_task_done` copy their payloads inside `_lock` and emit after releasing it; the repo's regression test `tests/test_downloader_cancel.py:314-349` pins this.
- **Backpressure and slot accounting (`core/downloader.py:412-471`).** `_MAX_INFLIGHT` (2) matches the pool width; `_wait_for_free_slot` waits on `FIRST_COMPLETED` with a 0.2 s bound so `stop()` is noticed; the slot is released by the future's done-callback (`_release_track_id`) in all paths, including the `_pool.submit` failure path (`core/downloader.py:465-467`). The queue cannot stall on a dead worker.
- **Crash recovery (`_resume_pending_downloads`, `core/downloader.py:333-354`, `DownloadStore.recover`, `core/download_store.py:58-64`).** Rows left in `downloading` are reset to `pending` and re-queued exactly once at startup; the manager is constructed in `core/app.py:139`, so the recovery runs on every start. Verified end-to-end: a row left in `downloading` produced exactly **one** provider call after the restart and ended `completed` / `is_downloaded = 1` (`%TEMP%\opencode\wn13_repro3.py` S7b). `from_db=True` correctly skips the DB insert, and the in-memory + `_active_track_ids` guards prevent a double download.
- **`stop()` DB bookkeeping.** `DownloadStore.preserve_shutdown()` (`core/download_store.py:66-71`) marks `pending`/`downloading` rows `resume_on_restart = 1`, and `DownloadStore.recover()` clears it on the next start, so a row cannot be resumed twice.
- **Retry mechanics.** The attempt count is bounded (`_RETRY_ATTEMPTS = 3`), the delay grows (`20 s → 40 s`), the wait is sliced into 1 s steps so a cancel is honoured immediately, and every attempt re-enters the cancellation check (`core/downloader.py:680-709`). A 404 in its bare form is **not** retried. There is no unbounded retry loop.
- **State separation between resume and retry.** `resume_download` only picks rows in `paused` (`core/downloader.py:118`), `retry_failed_downloads` only picks rows in `failed` (`core/downloader.py:133`), and `pause_download`/`resume_download`/`retry_failed_downloads` on an unknown `track_id` return `{'success': True, 'count': 0}` without side effects (verified). A permanently failed track cannot be "resumed" — only retried.
- **`download_queue` schema convergence.** `ensure_download_queue_table()` (`core/database.py:2284-2328`) and the fallback DDL in `_init_db_table` (`core/downloader.py:287-331`) produce the same table plus the `ux_download_queue_track` unique index, and the duplicate-row collapse runs in both paths.

---

### 4. Coverage gaps

- **No live provider was exercised.** The sandbox has no network and the audit rules forbid touching the real `~/.nedotify/`. All provider error strings used in the classification analysis (`HTTP Error 404/500/…`, "Unable to download webpage: …", "The page needs to be reloaded") are taken from yt-dlp 2026.08.19's own message formats (`YoutubeDL.py`, `extractor/common.py`) and from the repo's `_YT_GATING_MARKS`; the *masking* behaviour itself was verified by calling `_yt_gating_error()` directly, not by a real download.
- **`core/api.py` was read, not exercised.** The pywebview bridge (`_emit` → `window.onPythonEvent`) was verified by reading `core/api.py:1122-1159` and `js/events.js`, not with a live WebView2 window; the claim "the downloader never emits on the UI thread" rests on code reading plus the existing `tests/test_emit_thread_safety.py`.
- **The `%%` filename sanitisation / Windows reserved-name question was not tested** for the `DownloadContext.stem` name (`download_<track_id>_<digest>`) — the digest is hex and the track id is sanitised to `[A-Za-z0-9_-]`, so it looked safe by inspection, but no file was created with a hostile track id.
- **`stop()` under a *live* app shutdown was not observed.** The 4.29 s process-exit measurement (`wn13_repro5.py`) used a bare `ThreadPoolExecutor`, not the app's own `cleanup()` path, and the "DB closed under a running worker" consequence was shown at the code level (`DatabaseManager.close()` closes every handle in `_all_conns`, `core/database.py:2474-2482`) rather than with the real `AppCore`.
- **The `.part` resume path with a real provider** (HTTP `Range`/`If-Range` handling in `core/download_transfer.py:41-128`) was exercised only through the repo's own unit tests (`tests/test_download_resume.py:225-317`), which I read but did not re-run.
- **The whole test suite was not run.** Only the six download-related test files were read; the numbers in the commit messages (919 passed) were not re-verified.
- **The `spotify` / `spotify_album` source path** (`core/downloader.py:473-558`) was reviewed against the general path (progress, cancel, defect check, DB update, batch accounting) and found consistent — it reuses the same `DownloadContext`, the same `_call_provider` and therefore the same file naming scheme (`download_<track_id>_<digest>`); but it was not exercised end-to-end, because it needs `TrackResolver` plus a live YouTube/SoundCloud provider.
- **Disk-quota estimation for batch downloads** (`core/api.py:3698`, `len(to_download) * 5 * 1024 * 1024`) lives in WN-10 and was not reviewed here.
