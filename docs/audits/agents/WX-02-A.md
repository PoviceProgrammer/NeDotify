# WX-02 — Download → library → playback — ROLE A (Correctness & Reliability)

## SCENARIO WX-02 — Download → library → playback — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/downloader.py` — 1–909 (whole file: `DownloadManager`, `queue_download`, `_execute_download_worker`,
  `_download_worker`, `_fetch_with_retry`, `_record_progress`, `_emit`, `start_batch`,
  `_decrement_batch_total_for_dedup`, `_on_batch_task_done`, `cancel_batch`, `pause_download`,
  `resume_download`, `_resume_pending_downloads`, `_abort_cancelled`, `stop`)
- `core/download_store.py` — 1–71 (`DownloadStore.update/rows/recover/preserve_shutdown`)
- `core/download_transfer.py` — 1–128 (`DownloadContext.ydl_options`, `download_http`)
- `core/database.py` — 1–130 (schema, thread-local connections, `_write_lock`), 224–343 (`tracks` table),
  1184–1243 (`get_all_tracks`, `get_favorite_tracks`), 1250–1369 (`mark_track_downloaded`,
  `get_downloaded_tracks`), 2270–2489 (`ensure_download_queue_table`, `download_queue_*`)
- `core/api.py` — 1100–1179 (`_emit`), 1437–1606 (`play_track`), 1608–1745 (`_resolve_track`),
  2077–2256 (`search`), 2257–2360 (`get_library`, `get_downloaded_tracks`, `download_track`),
  3293–3362 (`get_home_data`, `get_popular_tracks`), 3660–3739 (`download_all_favorites`,
  `cancel_batch_download`), 4160–4228 (`get_downloads`, `pause_download`, `resume_download`,
  `retry_failed_downloads`, `recover_stream`)
- `core/proxy.py` — 115–272 (`AUDIO_EXTENSIONS`, `_nedotify_root`, `_is_inside_roots`,
  `_safe_stream_local_path`), 700–830 (`do_GET` `/api/stream` local-file branch)
- `core/offline.py` — 1–77 (`_AUDIO_EXTENSIONS`, `available_track`, `offline_library`)
- `core/app.py` — 120–199 (`DownloadManager` construction), 505–584 (`cleanup`)
- `core/user_errors.py` — 1–24 (`describe_error`)
- `audio/engine.py` — 25–154 (`play_queue`, `_notify_track_changed`)
- `utils/stream_urls.py` — 1–26 (`stream_url_expired`)
- `services/base_service.py` — 278–313 (`_parse_yt_entry`)
- `services/youtube_service.py` — 120–163, 293–362, 370–519, 1072–1190
- `services/soundcloud_service.py` — 847–995
- `services/spotify_service.py` — 100–240
- `services/artist_service.py` — 250–279
- `services/catalog_service.py` — 195–250
- `services/recommendation_service.py` — 80–119
- `ui/web_new_v2/js/events.js` — 1–464
- `ui/web_new_v2/js/downloads-view.js` — 1–193
- `ui/web_new_v2/js/library.js` — 1–140, 300–599, 962–963
- `ui/web_new_v2/js/library-view.js` — 111–179
- `ui/web_new_v2/js/utils.js` — 1–40, 688–809, 965–1049
- `ui/web_new_v2/js/player.js` — 80–159, 698–787, 1660–1739
- `ui/web_new_v2/js/feature-controls.js` — 60–135
- `ui/web_new_v2/js/main.js` — 60–134, 525–604, 670–709
- `ui/web_new_v2/js/search.js` — 300–420
- `ui/web_new_v2/js/home.js` — 770–789
- `main.py` — 298–327 (startup order `AppCore()` → `AppApi(app_core)`)
- `tests/conftest.py` — 1–176; `tests/test_downloader.py` — 1–95; `tests/test_downloader_cancel.py` — 140–259

**Callees traced into other areas** (not re-reported here, named as owners):
`core/api.py::_emit` (WN-03), `core/proxy.py::_safe_stream_local_path` / `do_GET` (WN-11),
`core/database.py` (WN-12), `core/downloader.py` (WN-13), `core/offline.py` (WN-15),
`audio/engine.py` (WN-17), `services/youtube_service.py` (WN-19), `services/soundcloud_service.py` (WN-20),
`services/spotify_service.py` (WN-21), `ui/web_new_v2/js/events.js` (WN-28), `ui/web_new_v2/js/utils.js`
+ `js/player.js` (WN-29/WN-32), `ui/web_new_v2/js/library.js` + `js/downloads-view.js` (WN-32),
`ui/web_new_v2/js/feature-controls.js` (WN-30).

**Reproduction assets (written outside the repo, per the ground rules)**

- `%TEMP%\opencode\wx02_repro.py` — 5 scenarios against the real `DownloadManager`
- `%TEMP%\opencode\wx02_repro_f.py` — the "dead end" follow-up for F-1
- `%TEMP%\opencode\wx02_match.js` — a faithful re-implementation of
  `ui/web_new_v2/js/utils.js::matchDownloadTarget` executed with `node`
- `%TEMP%\opencode\wx02_scratch.py`, `wx02_scratch2.py` — SQLite affinity/rowcount probes

---

### 2. Findings

#### F-WX-02-1  [P1] — A download whose track id is a provider id (not a DB rowid) never reaches the library: `mark_track_downloaded` updates 0 rows

- **File:** `core/api.py:2294-2360` (`download_track`), `core/downloader.py:819`
  (`mark_track_downloaded`), `core/database.py:1278-1282` (`mark_track_downloaded`),
  `core/database.py:213-239` (`tracks.id INTEGER PRIMARY KEY AUTOINCREMENT`)
- **Confirmed:** yes
- **Description:** the frontend passes the provider's track object straight to the bridge
  (`ui/web_new_v2/js/utils.js:779` → `js/main.js:107` → `window.pywebview.api.download_track(track)`).
  Several providers put a **provider id** in the `id` field:
  `services/spotify_service.py:196` `"id": f"spotify_{item.get('trackId', idx)}"`,
  `services/artist_service.py:263` `"id": "yt_" + str(video_id)`,
  `services/catalog_service.py:208` `'id': 'spotify_' + str(h['trackId'])`.
  `AppApi.download_track` only creates a DB row when the id is *falsy*:

  ```python
  track_id = track_data.get("id")
  ...
  if not track_id:
      track_id = self._core.db.add_track(...)      # core/api.py:2319-2327
  ```

  A non-empty provider id therefore skips `add_track` and is written into
  `download_queue.track_id` as **TEXT**. When the download finishes,
  `core/downloader.py:819` calls
  `UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?` with that TEXT value.
  `tracks.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so the comparison is INTEGER vs TEXT and
  matches **no row**: the update is a silent no-op. The file is on disk, `download_complete`
  and `library_updated` fire, the UI re-reads the library — and the track is not there.
  Worse, the queue row is now `completed`, so `download_queue_add`'s
  `ON CONFLICT ... DO UPDATE ... WHERE status IN ('failed','cancelled')` does not re-arm it:
  **every later click on "Скачать" is rejected and the track can never enter the library.**
- **Cause:** the bridge conflates "provider track identity" with "SQLite rowid". The queue,
  the downloader and the DB writer all assume `track_id` is a `tracks.id`; only the
  `if not track_id:` branch guarantees that.
- **Trigger conditions:** download a track from a Spotify search result, a Spotify album/playlist
  detail, or an artist page. (YouTube/SoundCloud *search* results have no `id` at all, so they
  take the `add_track` branch and are unaffected.)
- **User impact:** the audio file is downloaded to `~/.nedotify/downloads/` but the track never
  appears under "Офлайн треки" / `get_downloaded_tracks()`, so it can never be played offline
  and the disk file is orphaned. The download button flips to "Скачан" (the payload id matches
  the row's `id`), so the UI claims success. A second click does nothing and the spinner
  spins forever (see F-WX-02-3).
- **Evidence:**
  - `core/api.py:2319-2327` — `if not track_id: track_id = self._core.db.add_track(...)`
  - `core/database.py:1278-1282` — `cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))`
  - `core/database.py:213-215` — `id INTEGER PRIMARY KEY AUTOINCREMENT,`
  - `core/database.py:2347-2352` — the upsert only re-arms `('failed','cancelled')`
- **Reproduction / verification:** `%TEMP%\opencode\wx02_repro.py`, scenario A:

  ```
  queue_download returned: True
  download_queue rows: [{'track_id': 'spotify_1234567', ..., 'status': 'pending', ...}]
  events: ['download_queue_updated', 'download_queue_updated', 'library_updated',
           'download_queue_updated', 'download_complete']
  get_downloaded_tracks() -> []
  tracks rows: []
  files on disk: ['stub_1.mp3']
  RESULT: file on disk = True | track visible in library = False
  ```

  `%TEMP%\opencode\wx02_repro_f.py` (the dead end):

  ```
  1st download_track -> True
  queue status: completed
  library: []
  2nd download_track (user clicks download again) -> False
  provider calls: [('ytsearch1: A - S', ...)]      # never called again
  tracks table: []
  files: ['stub_1.mp3']
  ```

  SQLite affinity probe (`%TEMP%\opencode\wx02_scratch.py`):
  `updated rows for TEXT id: 0` vs `updated rows for INT id: 1`.
- **Suggested fix:** in `AppApi.download_track`, resolve the incoming id to a **numeric DB rowid**
  before queueing: if `track_id` is not an integer, look the track up by
  `(source, source_id)` and, if there is no row, create one with `add_track(...)` and use the
  returned id. The same normalisation belongs in `DownloadManager.queue_download` as a guard.
- **Fix side effects:** `download_queue.track_id` values change from provider ids to rowids for
  the affected tracks; existing TEXT rows in a user's DB would no longer match a re-queue, so a
  one-off migration of non-numeric `download_queue.track_id` rows would be needed.
- **Discovered by:** A — **owning area: WN-06** (`core/api.py::download_track`); the silent
  no-op in `core/database.py::mark_track_downloaded` (WN-12) is the amplifier, not the root cause.

---

#### F-WX-02-2  [P2] — `download_complete` carries a DB rowid that the search rows cannot match, so the download button spins forever

- **File:** `core/downloader.py:839` (payload), `ui/web_new_v2/js/events.js:258-264` (dispatch),
  `ui/web_new_v2/js/utils.js:977-992` (`matchDownloadTarget`), `ui/web_new_v2/js/utils.js:694`
  (`item.dataset.trackSourceId`), `ui/web_new_v2/js/utils.js:1008-1017` (the only in-place updater)
- **Confirmed:** yes
- **Description:** `download_complete` carries only `{"track_id": <DB rowid>}` (contract #7 —
  correct, and **no JS reads `file_path` from it**; verified across the whole `ui/web_new_v2/js`
  tree). The only consumer that updates the button in place is
  `utils.js::matchDownloadTarget`, which compares the payload id against
  `el.dataset.trackSourceId` (`String(track.source_id || track.id || '')`) and
  `_trackData.id` / `_trackData.source_id`.
  A YouTube/SoundCloud **search** result has **no `id` field at all**
  (`services/youtube_service.py:490-498` and `services/soundcloud_service.py:341-347` build
  `{source, source_id, title, artist, duration, cover_url, album}`), so the row is identified by
  `source_id` only. The payload's `track_id` is the numeric rowid → no match → the spinner is
  never replaced by the check mark.
- **Cause:** the event's identifier space (DB rowid) and the UI's identifier space
  (`source_id`) are different, and the event carries only the former.
- **Trigger conditions:** download any track from the search page (YouTube or SoundCloud),
  then look at the same row without re-running the search.
- **User impact:** the download button keeps the spinning "loader" icon forever, although the
  track was downloaded. The user believes the download is still running and clicks again
  (→ the duplicate path of F-WX-02-3). The library itself is correct, so the defect is
  confined to the button state until the results are re-rendered.
- **Evidence:**
  - `core/downloader.py:839` — `self._emit('download_complete', {'track_id': track_id})`
  - `ui/web_new_v2/js/utils.js:981-989`:
    ```js
    const tid = (data.track_id !== undefined && data.track_id !== null) ? String(data.track_id) : '';
    const sid = (data.source_id !== undefined && data.source_id !== null) ? String(data.source_id) : '';
    ...
    const ds = el.dataset && el.dataset.trackSourceId ? String(el.dataset.trackSourceId) : '';
    if (ds && ((tid && ds === tid) || (sid && ds === sid))) return true;
    ```
  - `ui/web_new_v2/js/utils.js:694` — `item.dataset.trackSourceId = String(track.source_id || track.id || '');`
- **Reproduction / verification:** `%TEMP%\opencode\wx02_match.js` (a faithful copy of
  `matchDownloadTarget`, run with `node v24.19.0`):

  ```
  YT search row  vs download_complete{track_id:42} -> false
  Spotify row    vs download_complete{track_id:"spotify_1234567"} -> true
  Home feed row  vs download_complete{track_id:42} -> true
  ```

  (The home feed works because `ui/web_new_v2/js/home.js:780` copies `track_id` into `id`.)
- **Suggested fix:** add `source_id` (and/or `source`) to the `download_complete` payload so the
  UI can match provider rows, or let the UI resolve the rowid → `source_id` mapping through
  `get_downloads()`/`get_downloaded_tracks()`. Extending the payload keeps contract #7 intact
  (it forbids `file_path`, not extra identifying fields).
- **Fix side effects:** a payload change must stay in sync with `matchDownloadTarget` and with
  `tests/test_downloader.py:60` / `tests/test_downloader_cancel.py:201,220`, which assert on the
  payload's presence, not its exact shape.
- **Discovered by:** A — **owning area: WN-32** (`ui/web_new_v2/js/utils.js`); the payload
  producer is WN-13 (`core/downloader.py`).

---

#### F-WX-02-3  [P2] — The download button's spinner is never cleared when the bridge refuses the request (`download_track` → `False`) or the call rejects

- **File:** `ui/web_new_v2/js/utils.js:764-790` (the click handler), `ui/web_new_v2/js/main.js:104-109`
  (`window.NeDotify.downloadTrack`), `core/api.py:2356-2360` (`download_track` returning `False`)
- **Confirmed:** yes
- **Description:** the click handler always sets the "downloading" state first and relies
  **exclusively** on the `download_complete` / `download_failed` events to clear it:

  ```js
  downloadBtn.classList.add('downloading');
  downloadBtn.innerHTML = '<i data-lucide="loader-2" class="spin-icon" ...>';
  ...
  if (window.NeDotify?.downloadTrack) {
      window.NeDotify.downloadTrack(track);          // result discarded
  } else if (window.pywebview?.api?.download_track) {
      try { await window.pywebview.api.download_track(track); } catch(err) { ...clear... }
  }
  ```

  `window.NeDotify.downloadTrack` always exists (`js/main.js:82-109`), so the `else if` branch
  with its `try/catch` is **unreachable**. `window.pywebview.api.download_track(track)` returns a
  promise that is neither awaited nor inspected, and the bridge's documented boolean contract
  ("Returns True if queued, False otherwise", `core/api.py:2294-2295`) is ignored. When the
  bridge answers `False` (the track already has a queue row —
  `core/downloader.py:374-376` / `405-406`, or the queue insert was skipped) **no event is
  emitted at all**: neither `download_complete` nor `download_failed` will ever arrive for that
  click.
- **Cause:** the UI treats the download as fire-and-forget and has no synchronous "refused"
  channel, while the bridge has a synchronous "refused" channel that nobody reads.
- **Trigger conditions:** click "Скачать" twice on the same track, or on a track that is already
  downloaded (its queue row is `completed`, which `download_queue_add` does not re-arm).
- **User impact:** the button spins forever on a request that was rejected; a rejected bridge
  promise becomes an unhandled rejection and the spinner still spins.
- **Evidence:**
  - `ui/web_new_v2/js/utils.js:770-790` — the `downloading` class is set and only the two
    events can clear it
  - `ui/web_new_v2/js/main.js:104-109` — `downloadTrack: (track) => { ... window.pywebview.api.download_track(track); }`
  - `core/api.py:2356-2360` — `if not queued: return False` (no event emitted)
  - `core/downloader.py:374-376` — `if not added: self._decrement_batch_total_for_dedup(); return False`
- **Reproduction / verification:** in the app: search a track, download it, wait for it to
  finish, then click the download button on the same (now `downloaded`) row — the button flips
  to the spinner and stays there. Equivalently: call `download_track` twice for the same track
  in the repro harness of F-WX-02-1 (`2nd download_track -> False`, no `download_failed` event
  in the emitted list).
- **Suggested fix:** make `window.NeDotify.downloadTrack` async, `await` the bridge call and
  inspect the boolean; on `false` (or on a rejection) restore the idle button and show a short
  "уже в очереди" toast.
- **Fix side effects:** the `else if` branch becomes live again and the `catch` handler must
  restore the button; the "Скачивание 'X'…" toast is currently shown before the request and
  would need to stay consistent.
- **Discovered by:** A — **owning area: WN-32** (`ui/web_new_v2/js/utils.js` + `js/main.js`);
  the bridge's `False` contract itself is WN-06 and is fine.

---

#### F-WX-02-4  [P1] — Pausing one download of a batch loses a unit of batch accounting: the batch progress bar never reaches 100 %

- **File:** `core/downloader.py:587-608` (`_abort_cancelled`, the "paused" branch),
  `core/downloader.py:213-239` (`_on_batch_task_done`),
  `ui/web_new_v2/js/library.js:85-101` (the batch progress bar), `core/downloader.py:101-113`
  (`pause_download`)
- **Confirmed:** yes
- **Description:** `pause_download` pauses a single track and bumps its generation; the running
  worker then aborts at its next checkpoint with `DownloadInterrupted`. `_abort_cancelled`
  handles the *paused* case **without any batch accounting**:

  ```python
  except DownloadInterrupted:
      if not self._is_cancelled(epoch):
          with self._lock:
              paused = track_id in self._paused_track_ids
          if paused:
              self._store.update(track_id, status='paused')
          return True          # <-- no _on_batch_task_done(...)
  ```

  Compare with the *cancelled* branch, which does call
  `self._on_batch_task_done(track_id, success=False)`. Because the paused track never reports
  back, `_batch_completed` can never reach `_batch_total`, `finished` stays `False`, and
  **`batch_download_finished` is never emitted**. The UI's batch bar
  (`ui/web_new_v2/js/library.js:85-90`) therefore stays at e.g. `9 / 10` forever, and the
  "✅ Загрузка завершена" toast / the 1.2 s auto-hide never happen.
- **Cause:** the batch counter is decremented/advanced only in `_on_batch_task_done`, and the
  pause path returns from the worker without ever calling it (nor decrementing the total).
- **Trigger conditions:** start "Скачать все избранное" (a batch) and press "Пауза" on any one
  of the queued rows in the downloads manager while the batch is running.
- **User impact:** the batch progress indicator is stuck forever and the user never gets the
  "download finished" confirmation, although every other download in the batch completed.
  The paused track itself is correctly marked `paused` and can be resumed.
- **Evidence:** the quoted `_abort_cancelled` branch above versus
  `core/downloader.py:607` — `self._on_batch_task_done(track_id, success=False)` in the
  cancelled branch; `core/downloader.py:225` — `finished = completed >= total`.
- **Reproduction / verification:** `%TEMP%\opencode\wx02_repro.py`, scenario B:

  ```
  events: ['download_queue_updated', 'download_queue_updated']
  batch active: True total: 1 completed: 0
  RESULT: 'batch_download_finished' emitted = False
  ```

  In the app: library → "Избранное" → "Скачать все" → immediately press "Пауза" on the first
  row of the "Загрузки" panel.
- **Suggested fix:** in the paused branch of `_abort_cancelled`, account for the task the same
  way the cancelled branch does (either `_on_batch_task_done(track_id, success=False)` or a
  `_decrement_batch_total_for_dedup()`), or have `pause_download` shrink the batch denominator
  for the tracks it pauses.
- **Fix side effects:** the batch would then report the paused track as "not completed"; if
  `_on_batch_task_done` is reused, `batch_download_finished.failed` would count it as a failure.
  A resumed track (`resume_download` → `queue_download`) would then be counted a second time
  when it finishes, so the denominator needs to be re-armed consistently.
- **Discovered by:** A — **owning area: WN-13** (`core/downloader.py`); the UI that renders the
  stuck bar is WN-32.

---

#### F-WX-02-5  [P2] — A deduplicated batch member makes the batch report "finished" (100 %) while downloads are still running

- **File:** `core/downloader.py:193-211` (`_decrement_batch_total_for_dedup`),
  `core/downloader.py:213-239` (`_on_batch_task_done`), `core/api.py:3717-3718`
  (`download_all_favorites` loop), `core/downloader.py:402-406` (in-memory dedup)
- **Confirmed:** yes
- **Description:** `download_all_favorites` calls `start_batch(len(to_download))` and then
  `download_track(track)` for each track. When a track is already queued (a duplicate),
  `queue_download` returns `False` and `_decrement_batch_total_for_dedup()` shrinks the
  denominator — **but the duplicate is still in the queue and will still call
  `_on_batch_task_done` when it finishes.** The batch therefore mixes two different notions:
  the denominator counts only the *newly* queued items, while `_batch_completed` counts
  *every* worker that reports back, including the pre-existing duplicate.
  The result is that `completed >= total` becomes true too early:
  `batch_download_finished` fires while other tracks of the same batch are still downloading,
  and the later completions are swallowed by `if not self._batch_active: return`.
- **Cause:** the denominator is decremented for a dedup, but the corresponding worker is not
  excluded from the numerator; the two counters no longer describe the same set of tasks.
- **Trigger conditions:** a batch is started while one of its tracks is already queued
  (e.g. the user clicked "Скачать" on a favourite manually first, or two favourites share the
  same DB row).
- **User impact:** the batch bar jumps to 100 % and the "✅ Загрузка завершена (N треков)"
  toast appears while downloads are still running; the remaining tracks report no progress
  at all, and the downloads manager shows them as still running.
- **Evidence:**
  ```python
  # core/downloader.py:193-206
  if self._batch_total > 0:
      self._batch_total = max(0, self._batch_total - 1)
  if self._batch_total == 0 or self._batch_completed >= self._batch_total:
      self._batch_active = False
  ```
  ```python
  # core/downloader.py:215-227
  if not self._batch_active:
      return
  self._batch_completed += 1
  ...
  finished = completed >= total
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx02_repro.py`, scenario C:

  ```
  queue A -> True
  queue A again (dedup) -> False
  queue B -> True
  events so far: [..., 'batch_download_progress', 'batch_download_finished']
  batch active: False total: 1 completed: 1
  events after B: [..., 'batch_download_progress', 'batch_download_finished',
                    'download_queue_updated', 'library_updated', 'download_queue_updated',
                    'download_complete']          # <- B finished, no progress event
  RESULT: 'batch_download_finished' emitted before B finished = True
  ```
- **Suggested fix:** make the batch account per *task*, not per *queue row*: give every
  queued item a batch token and count that token in `_on_batch_task_done`, or keep the
  denominator and the numerator in one set of identifiers.
- **Fix side effects:** the `batch_download_progress`/`finished` payloads
  (`{current,total,percent,track_id}` / `{total,completed,failed}`) are consumed by
  `ui/web_new_v2/js/library.js:85-101`; a per-task counter changes the `total` semantics the
  UI shows and must be adjusted together.
- **Discovered by:** A — **owning area: WN-13** (`core/downloader.py`).

---

#### F-WX-02-6  [P2] — Queuing a download while offline returns "queued", so the batch denominator is never reduced and the batch bar never terminates

- **File:** `core/downloader.py:378-383` (the offline branch of `queue_download`),
  `core/downloader.py:213-239` (`_on_batch_task_done`),
  `core/api.py:3685-3725` (`download_all_favorites` — no offline guard)
- **Confirmed:** yes
- **Description:** with offline mode on, `queue_download` takes the early branch

  ```python
  if self._offline():
      with self._lock:
          self._paused_track_ids.add(track_id)
      self._store.update(track_id, status='paused', error='')
      self._emit('download_queue_updated', {'track_id': track_id, 'status': 'paused'})
      return True          # <-- "queued", but the task will never run
  ```

  `download_track` therefore returns `True` to the caller and the batch denominator is **not**
  decremented, yet the track is parked as `paused` and will never call
  `_on_batch_task_done`. `download_all_favorites` has no offline guard, so the batch is started
  with N tracks and stays at `0 / N` forever.
- **Cause:** `queue_download` reports success for a task that was only parked; the batch
  accounting has no "will never run" case.
- **Trigger conditions:** enable offline mode and press "Скачать все" in the favourites
  collection.
- **User impact:** the batch progress bar shows `0 / N` and never moves; no
  `batch_download_finished` is emitted, so the "Загрузка завершена" toast never appears and the
  bar is not auto-hidden. The individual rows correctly show "На паузе".
- **Evidence:** the quoted `queue_download` branch; `core/api.py:3707-3718`
  (`start_batch(len(to_download))` then `download_track(track)` for each track, no
  `is_offline` check).
- **Reproduction / verification:** `%TEMP%\opencode\wx02_repro.py`, scenario D:

  ```
  queue_download -> True
  queue status: paused
  batch active: True total: 1 completed: 0
  events: ['download_queue_updated']
  RESULT: 'batch_download_finished' emitted = False
  ```
- **Suggested fix:** either refuse the batch in offline mode (`download_all_favorites` should
  report "включите сеть"), or make the offline branch of `queue_download` return `False` /
  reduce the batch denominator, exactly like the dedup path.
- **Fix side effects:** `queue_download` returning `False` in offline mode changes
  `AppApi.download_track`'s return value and the frontend's handling of it (see F-WX-02-3);
  the offline-mode behaviour is also in scope for WX-09.
- **Discovered by:** A — **owning area: WN-13** (`core/downloader.py`); the missing guard is
  WN-10 (`core/api.py::download_all_favorites`).

---

#### F-WX-02-7  [P3] — The set of extensions the downloader accepts and the set the proxy is willing to serve disagree on `.mp4`

- **File:** `core/downloader.py:32-33` (`_AUDIO_DOWNLOAD_EXTS`),
  `services/youtube_service.py:137-138` (`_AUDIO_DOWNLOAD_EXTS`),
  `core/proxy.py:125-128` (`AUDIO_EXTENSIONS`), `core/proxy.py:259` (the extension gate),
  `core/offline.py:7` (`_AUDIO_EXTENSIONS`)
- **Confirmed:** hypothesis (the mismatch is confirmed; the reachability depends on the format
  yt-dlp picks)
- **Description:** the downloader's integrity gate accepts `.mp4` and will therefore mark such
  a file as a completed download; `core/proxy.py` refuses to serve `.mp4` through
  `/api/stream`, and `core/offline.py` accepts it. The four sets are:

  | extension | downloader | proxy (`AUDIO_EXTENSIONS`) | offline |
  |---|---|---|---|
  | .m4a .mp3 .opus .webm .aac .ogg .flac .wav | yes | yes | yes |
  | **.mp4** | **yes** | **no** | yes |
  | .wma .alac .aiff | no | yes | yes |

  A track marked `is_downloaded = 1` with a `.mp4` payload therefore appears in the library
  and in the offline collection, but every playback attempt gets a 404 from the proxy
  ("Refused /api/stream read of unlisted local file" is not even reached — the extension gate
  returns `''` first, `core/proxy.py:259-260`).
- **Cause:** three independent copies of "what counts as audio" with no single source of truth.
- **Trigger conditions:** yt-dlp resolves to a video-only `mp4` container. With
  `format = "bestaudio/best"` (`services/youtube_service.py:306`) this is unlikely, but the
  fallback ladder is `"bestaudio/best/ba/b/worst"` (`services/youtube_service.py:348`), and
  `best`/`worst` may select a video-only `mp4` stream — which would additionally produce a file
  with no audio track at all.
- **User impact:** a track shows as downloaded in the library but cannot be played
  ("Не удалось воспроизвести трек"). The file also passes the downloader's integrity gate
  (extension + size), so nothing catches it earlier.
- **Evidence:**
  ```python
  # core/downloader.py:32-33
  _AUDIO_DOWNLOAD_EXTS = ('.m4a', '.mp3', '.opus', '.webm', '.aac', '.ogg',
                          '.mp4', '.flac', '.wav')
  # core/proxy.py:125-128
  AUDIO_EXTENSIONS = {
      '.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus', '.webm',
      '.wma', '.alac', '.aiff',
  }
  # core/proxy.py:259-260
  if os.path.splitext(candidate)[1].lower() not in AUDIO_EXTENSIONS:
      return ''
  ```
- **Reproduction / verification:** missing evidence — the exact format yt-dlp selects for the
  affected track. To confirm: run a download whose resolved format is a video-only `mp4`,
  then request `http://127.0.0.1:<port>/api/stream?url=<the stored path>&k=<token>` and check
  for a 404, and confirm `tracks.file_path` ends in `.mp4` with `is_downloaded = 1`.
- **Suggested fix:** derive all three sets from one shared constant (e.g. in
  `utils/file_scanner.py`, which the proxy's comment already names as the mirror), and drop
  `.mp4` from the downloader's accepted set (a video container is not an audio download).
- **Fix side effects:** a user who already has a `.mp4` row marked as downloaded would see it
  disappear from the library once the filter is tightened; the proxy's set is deliberately
  narrow for security reasons, so widening it needs care.
- **Discovered by:** A — **owning area: WN-13 / WN-11** (the two sets must be reconciled;
  the duplication itself is also a WN-27 concern).

---

#### F-WX-02-8  [P3] — The shared download context silently overrides the provider's `overwrites: True`

- **File:** `services/youtube_service.py:1101-1108`, `core/download_transfer.py:24-32`
- **Confirmed:** yes (the override); hypothesis (a harmful leftover being reused)
- **Description:** the YouTube provider deliberately sets `overwrites: True` and documents why:

  ```python
  # A previous partial download of the same id must not be reused:
  # yt-dlp skips an existing file by default, so a 0-byte or
  # truncated leftover silently became "the download".
  "overwrites": True,
  ```

  but the next statement replaces the whole option set with the shared context's:

  ```python
  if download_context:
      ydl_opts.update(download_context.ydl_options(output_dir))
  ```

  and `DownloadContext.ydl_options` returns `'overwrites': False, 'continuedl': True`.
  The provider's protection therefore never applies on the production download path
  (the only path that goes through `DownloadManager`).
- **Cause:** two owners of the yt-dlp option dictionary; the last writer wins and the
  provider's intent is lost.
- **Trigger conditions:** a file with the deterministic name
  `download_<track_id>_<sha256(source:source_id)[:16]>_<id>.<ext>` already exists in
  `~/.nedotify/downloads/` and is larger than the 4 KiB floor but is not the intended audio
  (e.g. a truncated remnant of a hard kill that happened after yt-dlp's final rename, or a
  file whose extension changed between attempts).
- **User impact:** the stale file is accepted, `is_downloaded = 1` is written for it, and the
  newly downloaded audio is orphaned on disk. The downloader's integrity gate
  (`core/downloader.py:37-52`) only rejects `.part` names, non-audio extensions and files
  below 4 KiB, so it does not catch this.
- **Evidence:** the two quoted snippets (`services/youtube_service.py:1101-1108` and
  `core/download_transfer.py:24-32`).
- **Reproduction / verification:** missing evidence — an actual leftover file in the state
  described above. To confirm: place a >4 KiB file named
  `download_<tid>_<digest>_<videoid>.m4a` in `~/.nedotify/downloads/` and start the download;
  yt-dlp will report "has already been downloaded" and the downloader will mark that file.
- **Suggested fix:** let the provider keep ownership of `overwrites`, or make
  `DownloadContext.ydl_options` accept/merge provider options instead of replacing them.
- **Fix side effects:** `overwrites: True` would discard a resumable `.part` file's final
  content in some yt-dlp versions; the resume behaviour pinned by
  `tests/test_download_resume.py` must keep passing.
- **Discovered by:** A — **owning area: WN-13** (`core/download_transfer.py`) vs WN-19
  (`services/youtube_service.py`).

---

### 3. Clean areas

- **Event names (contract #7).** Every event the download path emits is consumed by
  `ui/web_new_v2/js/events.js`; the only name handled but never emitted is the alias
  `track_downloaded` (`events.js:259`), which is harmless because `events.js` itself
  dispatches the `nedotify:track_downloaded` DOM event that the alias would have fed.
  `download_complete` carries exactly `{"track_id": ...}` and **no `file_path`**; a grep of
  the whole `ui/web_new_v2/js` tree shows no code reading `file_path` from a download event
  (the only `file_path` reads are on *track objects*: `js/player.js:1693`, `js/utils.js:13`,
  `js/lyrics.js:29`).
- **Status strings.** The six backend statuses — `pending`, `downloading`, `paused`,
  `completed`, `failed`, `cancelled` — and the six labels in
  `ui/web_new_v2/js/downloads-view.js:9-12` match **exactly**; there is no status the backend
  can write without a label and no label without a backend status.
  `core/download_store.py:43-44`'s `ORDER BY` covers `downloading/pending/paused/failed` and
  buckets `completed`/`cancelled` into the `ELSE` branch.
- **The DB write.** `core/database.py:1278-1282` updates `is_downloaded` and `file_path` in a
  **single `UPDATE` inside one `with self._write_lock: with self.conn:` transaction** — the two
  fields can never diverge. The path stored is the very path the provider returned and that
  `core/downloader.py:807` had just verified with `_downloaded_file_defect` (exists, not a
  `.part`, audio extension, ≥ 4 KiB), so the DB path and the on-disk path match.
- **Event/DB ordering.** `mark_track_downloaded` (line 819) and
  `download_queue_set_status(..., 'completed')` (line 829) both happen **before**
  `library_updated` (835) and `download_complete` (839). There is **no race** between the
  event arriving and the DB commit: a `get_downloaded_tracks()` triggered by the event always
  sees the row. (The only two writes are not atomic *with each other* — `tracks` and
  `download_queue` are two transactions — but a crash between them is repaired by
  `DownloadStore.recover()` on the next start.)
- **Library refresh.** `download_complete` → `events.js:258-264` → `loadDownloaded()` →
  `refreshActiveLibraryView()` (`js/library.js:379-391`) → `loadLibrarySummary()`
  (`get_downloaded_tracks()`) and, for the open section, `selectSection('offline')` →
  `get_downloaded_tracks()` (`js/library.js:503`). The new track therefore does appear in
  "Офлайн треки" and the offline counter is updated.
- **Resume across restart.** `DownloadStore.recover()` (`core/download_store.py:58-64`) maps
  every `downloading` row (and every `resume_on_restart = 1` row) back to `pending`;
  `_resume_pending_downloads()` (`core/downloader.py:333-354`) then re-queues them via
  `queue_download(..., from_db=True)`. A track left in `downloading` by a hard kill **is**
  recovered — it is not stuck forever. `paused` rows stay paused (correct) and `failed` rows
  stay failed until the user presses "Повторить ошибки".
- **Cancel.** `cancel_batch()` bumps the cancel epoch, clears the queue, cancels the
  not-yet-started futures, and marks `pending`/`downloading` rows `cancelled`; the running
  workers observe the epoch at every stage boundary (`_abort_cancelled`) and abort, so no file
  is written past the cancel point. The half-written data stays as yt-dlp's `<name>.part`
  file (or `<name>.part.json` for the HTTP path) inside `~/.nedotify/downloads/`; it is
  **not** in the library (`is_downloaded` is never set) and it is the correct resume artefact.
  `core/downloader.py:822-827`'s fallback UPDATE for a failed `mark_track_downloaded` is
  harmless (it re-raises the same error into the outer handler).
- **Playback of a just-downloaded track.** The stored path is an absolute Windows path;
  `ui/web_new_v2/js/player.js:97-103` (`normalizeAudioSourceUrl`) turns it into
  `http://127.0.0.1:<port>/api/stream?url=<encoded>&k=<token>`, and
  `audio/engine.py:106-117` builds the same kind of proxy URL from `file_path`.
  `core/proxy.py:742-751` resolves it through `_safe_stream_local_path`
  (`core/proxy.py:238-272`), which accepts it because the file lives inside
  `~/.nedotify/` (`_is_inside_roots(resolved, [_nedotify_root()])`, line 264) and has an
  allow-listed extension. `AppApi.play_track`'s fast path (`core/api.py:1510-1529`) accepts the
  local file via `_fp_usable` (exists and > 1 KiB). So the chain
  download → DB → `get_downloaded_tracks` → `play_track` → proxy → `<audio>` works — provided
  the track actually reached the DB (F-WX-02-1) and the extension is servable (F-WX-02-7).
- **Batch dedup accounting.** `_decrement_batch_total_for_dedup()` is called from exactly one
  place per rejection path (`core/downloader.py:375` for the DB-level duplicate and
  `core/downloader.py:405` for the in-memory duplicate; `core/api.py:2334/2343/2354` for the
  three pre-queue failures), so a deduplicated track is decremented **exactly once**. The
  problem is the *other* side of the counter (F-WX-02-5), not a double decrement.
- **`download_queue_add` semantics.** The `ON CONFLICT(track_id) DO UPDATE ... WHERE status IN
  ('failed','cancelled')` upsert returns `rowcount > 0` correctly: 0 for an existing
  `pending`/`downloading`/`completed` row, 1 for a fresh insert or a re-armed terminal row
  (verified with a standalone SQLite probe).

---

### 4. Coverage gaps

- **No live run.** The ground rules forbid running the real app, so every provider
  interaction (yt-dlp format selection, SoundCloud's preview fallback, the YouTube-fallback
  path of the SoundCloud service) was verified by code reading and by driving the real
  `DownloadManager` with a stub provider (`%TEMP%\opencode\wx02_repro.py`). The end-to-end
  WebView2/pywebview hop (`AppApi._emit` → `window.onPythonEvent`) was traced by reading
  `core/api.py:1122-1159` and `ui/web_new_v2/js/events.js:50-72`, not executed.
- **F-WX-02-7 and F-WX-02-8 are hypotheses**: they need a real yt-dlp download to observe
  which container/format is produced and which leftover files exist in
  `~/.nedotify/downloads/`. The *code-level* mismatch/override is confirmed; the user-visible
  consequence is not.
- **The frontend was not executed in a browser.** F-WX-02-2 was confirmed by re-implementing
  `matchDownloadTarget` verbatim in Node against the real provider payload shapes; the DOM
  behaviour (the spinning icon) follows from that function's return value but was not observed
  on screen.
- **The batch accounting findings (F-WX-02-4/5/6) were reproduced with the real
  `DownloadManager` but with the processor thread halted** (as `tests/conftest.py:116-130`
  does), so the interleaving with the live pool differs from production; the counter
  arithmetic itself is deterministic and therefore unaffected.
- **`_resume_pending_downloads` was not exercised end to end** — the recovery logic was read
  (`core/downloader.py:333-354`, `core/download_store.py:58-71`) and the
  `downloading → pending → re-queue` chain verified by inspection; a real app restart with a
  killed download was not performed.
- **Not examined (out of this scenario's scope):** the `library_updated` debounce interaction
  with page visibility (`events.js:211-231`), the `Скачанное` locked playlist (it is a
  user-created playlist; nothing in the backend creates or maintains it), smart playlists and
  the LUFS/fingerprint scanners, and the `android/` subtree.
