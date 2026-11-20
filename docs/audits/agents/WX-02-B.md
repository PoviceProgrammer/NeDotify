## WX-02 — Download → library → playback — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `core/downloader.py` | 1–909 (whole) |
| `core/download_store.py` | 1–71 (whole) |
| `core/download_transfer.py` | 1–128 (whole) |
| `core/database.py` | 100–384 (schema/indexes), 1050–1233 (`add_track`/`get_all_tracks`/`get_favorite_tracks`), 1240–1369 (`mark_track_downloaded`, `get_downloaded_tracks`), 2280–2429 (`download_queue_*`), 2455–2489 (`close`) |
| `core/api.py` | 1110–1179 (`_emit`), 1500–1719 (`play_track`/`_resolve_track`), 2277–2361 (`get_downloaded_tracks`/`download_track`), 2650–2719 (auto-download), 3010–3169 (storage info / `clear_storage` / `_delete_downloaded_files`), 3680–3749 (`download_all_favorites`), 4090–4199 (`clear_storage_cache`, `get_downloads`) |
| `core/proxy.py` | 120–319 (`AUDIO_EXTENSIONS`, `_is_inside_roots`, `_referenced_by_library`, `_safe_stream_local_path`), 630–955 (`do_HEAD`/`do_GET` local-file branches) |
| `core/offline.py` | 1–77 (whole) |
| `core/app.py` | 530–586 (cleanup ordering) |
| `services/youtube_service.py` | 120–199 (`_require_audio_file`), 293–372 (`_get_ydl_opts`), 1060–1189 (`download_audio_sync`) |
| `services/soundcloud_service.py` | 840–959 (`download_audio_sync`) |
| `services/yandex_service.py` | 245–288 (`download_audio_sync`) |
| `utils/cache_manager.py` | 180–319 (purge + protected paths) |
| `utils/file_scanner.py` | 1–30 |
| `utils/tag_parser.py` | 23–29 (`SUPPORTED_FORMATS`) |
| `ui/web_new_v2/js/events.js` | 1–464 (whole) |
| `ui/web_new_v2/js/library.js` | 1–70, 310–569, 950–967 |
| `ui/web_new_v2/js/downloads-view.js` | 1–193 (whole) |
| `ui/web_new_v2/js/feature-controls.js` | 80–135 |
| `ui/web_new_v2/js/utils.js` | 985–1054 |
| `ui/web_new_v2/js/player.js` | 85–154, 1650–1739 |
| `ui/web_new_v2/js/main.js` | 515–694 |
| `tests/test_download_integrity.py`, `tests/test_api_download.py`, `tests/test_proxy_security.py` | whole / relevant ranges |
| `.venv_win/Lib/site-packages/yt_dlp/utils/_utils.py` | `sanitize_filename` |
| `.venv_win/Lib/site-packages/webview/window.py`, `webview/platforms/winforms.py` | `evaluate_js` |

**Callees traced into other areas**

- `core/database.py::mark_track_downloaded` / `get_downloaded_tracks` (WN-12)
- `core/proxy.py::_safe_stream_local_path` (WN-11)
- `core/api.py::get_downloaded_tracks` / `clear_storage` / `download_all_favorites` (WN-06, WN-08, WN-10)
- `services/{youtube,soundcloud,yandex}_service.py::download_audio_sync` (WN-19, WN-20, WN-21)
- `utils/cache_manager.py::purge_stream_cache` (WN-27)
- `core/offline.py::offline_library` (WN-15)
- `services/smart_playlists.py` “downloaded” rule, `services/taste_profile.py` download signal (WN-23, WN-24)

**Scratch probes run (outside the repo, `%TEMP%\opencode\`)**

- `wx02_verify.py` — `download_queue_add` re-arm semantics; `clear_storage('all')` DB aftermath.
- `wx02_perf.py` — cost of one `get_downloaded_tracks()` / `get_library()` on a 2 000-track library.

---

### 2. Findings

#### F-WX-02-1  [P1] — One completed download causes 5 (up to 8) full-library re-reads over the bridge

- **File:** `ui/web_new_v2/js/events.js:258-264`, `ui/web_new_v2/js/library.js:329-371`, `ui/web_new_v2/js/library.js:379-392`, `ui/web_new_v2/js/library.js:548-550`, `ui/web_new_v2/js/library.js:962-964`, `ui/web_new_v2/js/events.js:211-231`
- **Confirmed:** yes (static trace + measured per-call cost)
- **Description:** The backend emits three events per finished download (`library_updated`, `download_queue_updated`, `download_complete` — `core/downloader.py:835,838,839`). The frontend reacts to `download_complete` in three independent places, and the “library updated” reaction runs again 300 ms later:
  1. `events.js:260` `loadDownloaded()` → `library.js:549` `refreshActiveLibraryView()` → `library.js:380` `loadLibrarySummary()` → `get_favorites()` + `get_downloaded_tracks()`.
  2. `events.js:262` `window.refreshActiveLibraryView()` → the same `loadLibrarySummary()` again.
  3. `events.js:263` dispatches `nedotify:track_downloaded`; `library.js:962-964` listens and calls `loadDownloaded()` → `refreshActiveLibraryView()` → `loadLibrarySummary()` a **third** time.
  4. `events.js:211-231` (`library_updated`, 300 ms debounce) → `loadLibrary()` (`library.js:322`) → `loadLibrarySummary()` + `loadPlaylists()` + `loadLibraryOverview()` (`get_library()`, the *entire* table, `core/database.py:1199` has no LIMIT) + `loadSmartPlaylists()`, then `loadPlaylists()` again, then `refreshActiveLibraryView()` → `loadLibrarySummary()` a **fifth** time.
  With the “Офлайн треки” section open, `refreshActiveLibraryView()` also calls `selectSection('offline')` → `get_downloaded_tracks()` a 6th–8th time (`library.js:503-504`).
  Per completed download the bridge therefore serves **5 × `get_downloaded_tracks()`, 5 × `get_favorites()`, 3 × `get_playlists()`, 1–2 × `get_library()` (whole table), 1 × `get_downloads()` (whole queue + JOIN)**.
- **Cause:** `loadDownloaded()` is defined as a bare alias of `refreshActiveLibraryView()` (`library.js:548-550`), yet `events.js` calls *both* and a third call arrives through the `nedotify:track_downloaded` CustomEvent. There is no single owner of the “library changed” reaction, and the only way the frontend can learn what changed is a full re-read (contract #7 forbids `file_path` in `download_complete`), so every duplicate reaction costs a full library fetch.
- **Trigger conditions:** any completed download. Worst case: “Скачать все избранное” (`core/api.py:3685`) with the library page open and a large library.
- **User impact:** measurable CPU/IO and bridge traffic. Measured on this machine with a 2 000-track downloaded library: one `get_downloaded_tracks()` = **29.9 ms** DB+stat (2 000 × `os.path.exists`) + **4.9 ms** `json.dumps` = **1.21 MB** of JSON per call. ×5 per download = **175 ms CPU and 6.0 MB of JSON per finished download**; a 200-track batch ≈ 35 s CPU and **1.2 GB** of JSON across the bridge, plus WebView2 `JSON.parse` of 1.2 MB × 5 on the UI thread per download. The download workers are not the bottleneck, but the UI thread is: the window visibly stalls while each 1.2 MB payload is parsed and re-rendered.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/events.js:258-264
  case 'download_complete':
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
      document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
      break;
  ```
  ```js
  // ui/web_new_v2/js/library.js:548-550
  export async function loadDownloaded() {
      refreshActiveLibraryView();
  }
  ```
  ```js
  // ui/web_new_v2/js/library.js:962-964
  document.addEventListener('nedotify:track_downloaded', () => {
      loadDownloaded();
  });
  ```
  ```python
  # core/api.py:2282-2292  (what each of those calls costs)
  tracks = self._core.db.get_downloaded_tracks() or []
  ...
  for t in tracks:
      if fp and os.path.exists(fp):
          result.append(t)
  ```
- **Reproduction / verification:**
  1. Run `& ".venv_win\Scripts\python.exe" "$env:TEMP\opencode\wx02_perf.py"` (scratch script) → prints `get_downloaded_tracks(): 2000 rows in 29.9 ms`, `json.dumps(payload): 4.9 ms, 1.21 MB`, `x5 per completed download: 174 ms … 6.04 MB of JSON`.
  2. Static count: instrument `AppApi.get_downloaded_tracks` with a counter and download one track in the running app → expect ≥ 5 calls.
  3. DevTools → Network/`pywebview` trace, or `strace`-equivalent: 5 JSON payloads of ~1.2 MB per finished download.
- **Suggested fix:** give the “library changed” reaction exactly one owner. Make `loadDownloaded()` a no-op alias removal (or have `events.js` call *one* of `loadDownloaded()` / `refreshActiveLibraryView()`), drop the `nedotify:track_downloaded` → `loadDownloaded()` listener, and coalesce the `library_updated` debounce with the `download_complete` reaction (one timer, one refresh).
- **Fix side effects:** removing the third call changes when the download button flips to “Скачан” — `utils.js:1008-1017` listens to `nedotify:track_downloaded` and must keep working (that listener reads the DOM, not the library, so it is safe).
- **Discovered by:** B

---

#### F-WX-02-2  [P2] — The downloader accepts `.mp4` but the proxy refuses it: a “downloaded” track that cannot be played

- **File:** `core/downloader.py:32-34` + `core/downloader.py:37-52` (accept), `core/proxy.py:125-128` + `core/proxy.py:259` (refuse), `core/proxy.py:886-901` (404), `services/youtube_service.py:348` (format ladder that can produce `.mp4`)
- **Confirmed:** yes (code + extension-set diff); the end-to-end `.mp4` download was **not** executed (no network) — see Coverage gaps
- **Description:** “Is this file playable audio?” is decided by **five different, divergent** extension sets:
  | set | file | contains `.mp4`? |
  |---|---|---|
  | `_AUDIO_DOWNLOAD_EXTS` | `core/downloader.py:32` | **yes** |
  | `_AUDIO_DOWNLOAD_EXTS` | `services/youtube_service.py:137` | **yes** |
  | `_AUDIO_EXTENSIONS` | `core/offline.py:7` | **yes** |
  | `AUDIO_EXTENSIONS` | `core/proxy.py:125` | **no** |
  | `AUDIO_EXTENSIONS` | `utils/file_scanner.py:16` (= `SUPPORTED_FORMATS` + `.opus/.alac/.aiff`) | **no** |
  The downloader’s integrity gate therefore accepts `download_<track>_<digest>_<id>.mp4` and writes `is_downloaded=1` + `file_path`; the library lists it; the frontend proxies it (`ui/web_new_v2/js/player.js:97-103` → `/api/stream?url=C:\...\x.mp4`); the proxy refuses the extension at `core/proxy.py:259` and answers `404 "Local audio file not found: x.mp4"` (`core/proxy.py:901`). The track is in the library and cannot be played.
- **Cause:** no single source of truth for the audio-container set. The existing guard `tests/test_proxy_security.py:133-144` pins `file_scanner.AUDIO_EXTENSIONS ⊆ proxy.AUDIO_EXTENSIONS` — the *downloader’s* set is not covered by that invariant.
- **Trigger conditions:** a video whose `bestaudio` is unavailable so yt-dlp falls back to the `worst` rung of the ladder `"bestaudio/best/ba/b/worst"` (`services/youtube_service.py:348`) — a progressive `.mp4` with an audio track. Rare but reachable.
- **User impact:** the track shows as downloaded in the library/offline section and refuses to play with a “Local audio file not found” 404; re-downloading produces the same container again.
- **Evidence:**
  ```python
  # core/downloader.py:32-34
  _AUDIO_DOWNLOAD_EXTS = ('.m4a', '.mp3', '.opus', '.webm', '.aac', '.ogg',
                          '.mp4', '.flac', '.wav')
  ```
  ```python
  # core/proxy.py:125-128
  AUDIO_EXTENSIONS = {
      '.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus', '.webm',
      '.wma', '.alac', '.aiff',
  }
  ```
  ```python
  # core/proxy.py:257-260
  candidate = os.path.normpath(raw)
  if not os.path.splitdrive(candidate)[0]:
      return ''
  if os.path.splitext(candidate)[1].lower() not in AUDIO_EXTENSIONS:
      return ''
  ```
- **Reproduction / verification:**
  1. `& ".venv_win\Scripts\python.exe" -c "from core.downloader import _AUDIO_DOWNLOAD_EXTS as D; from core.proxy import AUDIO_EXTENSIONS as P; print(sorted(set(D)-set(P)))"` → `['.mp4']`.
  2. Unit-level: place a file `x.mp4` under a faked `~/.nedotify/downloads/`, call `core.proxy._safe_stream_local_path(path, db)` → returns `''`; while `_downloaded_file_defect(path)` returns `''` (accepted). The two gates disagree on the same file.
  3. End-to-end requires a network download of a `worst`-fallback video (not performed here).
- **Suggested fix:** one shared `AUDIO_EXTENSIONS` (e.g. in `utils/tag_parser.py` or a new `core/audio_formats.py`) imported by the downloader, the proxy, `offline.py` and the scanner; extend `tests/test_proxy_security.py` so the invariant covers the *downloader* set too, not just the scanner’s.
- **Fix side effects:** adding `.mp4` to the proxy allow-list widens what `/api/stream` may serve — but only files inside `~/.nedotify` or referenced by a `tracks` row, so the blast radius is the app’s own tree. Removing `.mp4` from the downloader set instead makes such downloads fail loudly (also acceptable).
- **Discovered by:** B

---

#### F-WX-02-3  [P2] — `clear_storage('all')` deletes the user’s music but leaves `is_downloaded=1`, permanently blocking re-download

- **File:** `core/api.py:3105-3136` (`clear_storage`), `core/api.py:3138-3154` (`_delete_downloaded_files`), `core/database.py:1282` (`mark_track_downloaded`), `core/api.py:2671-2677` (auto-download skip), `core/api.py:3692` (batch-download skip)
- **Confirmed:** yes (executed)
- **Description:** `_delete_downloaded_files()` removes the files from disk but nothing resets `tracks.is_downloaded` or `tracks.file_path`. The rows stay as “downloaded” and therefore:
  - `download_all_favorites()` (`core/api.py:3692`, `to_download = [t for t in favs if not t.get("is_downloaded")]`) skips the track and answers “Все любимые треки уже скачаны!”;
  - the auto-download of a favourited track returns early (`core/api.py:2671-2677`);
  - the “downloaded” smart-playlist rule (`services/smart_playlists.py:146`) and the taste profile (`services/taste_profile.py:175`) count the track as downloaded;
  - `db.get_downloaded_tracks()` (`core/database.py:1286`) still returns it, so `get_storage_info` (`core/api.py:3068-3077`) reports a non-zero track count with 0 bytes.
  Only `AppApi.get_downloaded_tracks()` (`core/api.py:2289-2291`) filters the dead rows out, so the *library view* looks right while every other consumer is wrong.
- **Cause:** the delete and the state reset are in different layers and the reset was never written. The `tracks` row and the file on disk are two records of the same fact with no owner keeping them in sync.
- **Trigger conditions:** `AppApi.clear_storage("all")` — a bridge method that the current UI does not call (`ui/web_new_v2/js/settings.js:231-232` calls `clear_storage_cache`, which only clears the cache manager and never touches `~/.nedotify/downloads`), but which is reachable from any JS in the WebView, from a plugin (`core/plugins.py`) or from a future UI button.
- **User impact:** the user’s downloaded music is gone while the app insists it is still there; the affected tracks cannot be re-downloaded by the two download entry points that consult `is_downloaded`.
- **Evidence:**
  ```python
  # core/api.py:3138-3154
  def _delete_downloaded_files(self) -> int:
      """Delete every downloaded track file from disk. Returns files removed."""
      removed = 0
      tracks = self._core.db.get_downloaded_tracks() or []
      for t in tracks:
          ...
          if os.path.isfile(fp):
              os.remove(fp)
              removed += 1
      return removed
  ```
  (no `UPDATE tracks SET is_downloaded = 0, file_path = NULL` anywhere in the file)
- **Reproduction / verification:** executed probe (`%TEMP%\opencode\wx02_verify.py`):
  ```
  before clear: {'id': 2, 'is_downloaded': 1, 'file_path': '...\\song.mp3'}
  file exists before: True
  clear_storage('all') -> True
  file exists after: False
  track row after:    {'id': 2, 'is_downloaded': 1, 'file_path': '...\\song.mp3'}
  db.get_downloaded_tracks() -> [2]
  api.get_downloaded_tracks() -> []
  ```
  i.e. the row is dangling and only the API-level filter hides it.
- **Suggested fix:** in `_delete_downloaded_files()`, reset the row in the same transaction (`UPDATE tracks SET is_downloaded = 0, file_path = NULL WHERE id = ?`) and clear the matching `download_queue` row; better, make the “downloaded” flag derive from the file’s existence everywhere instead of caching it in a column.
- **Fix side effects:** `tracks.file_path` is `UNIQUE` (`core/database.py:219`); nulling it frees the uniqueness slot, which is desirable, but any code that relies on `file_path` to mean “local copy” must be re-checked (`core/proxy.py:221` `_referenced_by_library` will simply stop matching — correct, the file is gone).
- **Discovered by:** B — **owning area: WN-08** (`core/api.py` settings/storage/quota). The cross-component symptom (the library view disagrees with the rest of the app) is what makes it a WX-02 finding.

---

#### F-WX-02-4  [P2] — Re-arming a failed download keeps the *old* `source_id`: the retry downloads the wrong audio

- **File:** `core/database.py:2330-2359` (`download_queue_add`), `core/downloader.py:356-410` (`queue_download`), `core/downloader.py:130-138` (`retry_failed_downloads`)
- **Confirmed:** yes (executed)
- **Description:** `download_queue_add()` upserts with `ON CONFLICT(track_id) DO UPDATE SET status = 'pending', added_at = CURRENT_TIMESTAMP WHERE download_queue.status IN ('failed','cancelled')`. The `DO UPDATE` clause refreshes **only** `status` and `added_at` — the row keeps its original `source` and `source_id`. The downloader then reads the queue row, not the `tracks` row, and downloads the stale id:
  - `core/downloader.py:130-138` `retry_failed_downloads()` → `queue_download(row['track_id'], row['source'], row['source_id'])` → `queue_download` calls `download_queue_add(...)`, which returns “re-armed” **without** writing the new source;
  - `core/downloader.py:335-352` `_resume_pending_downloads()` → same, from the persisted row.
  So a track whose provider id changed (e.g. a YouTube video re-uploaded / re-resolved to a new videoId, or a source that was migrated from `youtube` to `soundcloud`) is re-downloaded from the *old* id, and the file is then attached to the track row by `mark_track_downloaded(track_id, file_path)` — the library ends up holding the wrong audio under the right title.
- **Cause:** `download_queue` keeps a *second, independent* copy of `(source, source_id)` — the same identity that already lives in `tracks` — and the upsert treats that copy as immutable. The two copies can silently disagree; nothing owns the reconciliation.
- **Trigger conditions:** a failed download whose `(source, source_id)` changed between the first attempt and the retry; or a user who re-triggers a download of a track whose provider id was updated in the `tracks` row in the meantime.
- **User impact:** the retried download produces the previous track’s audio; the library row is overwritten with it and the user believes the correct track is stored offline.
- **Evidence:**
  ```sql
  -- core/database.py:2347-2351
  cursor.execute(
      'INSERT INTO download_queue (track_id, source, source_id) VALUES (?, ?, ?) '
      "ON CONFLICT(track_id) DO UPDATE SET status = 'pending', added_at = CURRENT_TIMESTAMP "
      "WHERE download_queue.status IN ('failed', 'cancelled')",
      (track_id, source, source_id),
  )
  ```
- **Reproduction / verification:** executed probe (`%TEMP%\opencode\wx02_verify.py`):
  ```
  add #1 -> True          (source_id='vid-OLD')
  re-add  -> True         (asked for source_id='vid-NEW')
  row after re-arm: {'track_id': 1, 'source': 'youtube', 'source_id': 'vid-OLD', 'status': 'pending'}
  EXPECT source_id == 'vid-NEW' -> False   (actual: vid-OLD)
  ```
- **Suggested fix:** either drop `source`/`source_id` from `download_queue` and always resolve them from `tracks` at download time, or make the upsert refresh them: `DO UPDATE SET status='pending', added_at=CURRENT_TIMESTAMP, source=excluded.source, source_id=excluded.source_id WHERE …`.
- **Fix side effects:** if the queue becomes the sole source of the id, `_resume_pending_downloads` must join `tracks` to fill it — a schema/migration change. The upsert fix is one line but changes behaviour for rows queued before a provider id change (they will now fetch the new id, which is the intent).
- **Discovered by:** B — **owning area: WN-12** (`core/database.py`) with the consumer in WN-13.

---

#### F-WX-02-5  [P2] — The “mark downloaded” fallback repeats the failing statement: one transient DB error turns a good download into a failed one and orphans the file

- **File:** `core/downloader.py:818-827`, `core/downloader.py:863-882`
- **Confirmed:** yes (code read; the failure is reachable but not reproduced against a locked DB)
- **Description:** On success the worker calls `db.mark_track_downloaded(track_id, file_path)`. If that raises, the handler runs a **verbatim copy of the same statement** inline:
  ```python
  try:
      self._core.db.mark_track_downloaded(track_id, file_path)
  except Exception as me:
      logger.error(f'mark_track_downloaded failed for {track_id}: {me}')
      with self._core.db._write_lock:
          with self._core.db.conn:
              self._core.db.conn.execute(
                  "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
                  (file_path, track_id),
              )
  ```
  The fallback is not wrapped in its own `try`, and it performs the identical `UPDATE` under the identical lock, so it fails for the identical reason (DB busy/locked, closed connection, or the `UNIQUE(file_path)` constraint at `core/database.py:219`). The exception then escapes to the outer handler (`core/downloader.py:863`), which marks the queue row `failed` and emits `download_failed` — even though the file was downloaded and passed the integrity gate. The file stays on disk in `~/.nedotify/downloads/` with **no** `tracks` row pointing at it: an orphan the user cannot see and cannot reclaim (the library never lists it, and the file is not in the `tracks` table so the cache manager does not protect it either).
- **Cause:** the fallback was meant as a “different path to the same write”, but it is the same write; and it is not error-contained, so a *recovery* path escalates a recoverable error into a terminal one.
- **Trigger conditions:** any error in `mark_track_downloaded` — a `sqlite3.OperationalError: database is locked` (30 s busy timeout, `core/database.py:189`), a closed connection during shutdown, or a `UNIQUE` collision on `tracks.file_path` (two rows pointing at the same file, e.g. after a re-import of a local file into a second row).
- **User impact:** “Ошибка скачивания: database is locked” for a track that is in fact on disk; the user retries, downloads a second copy, and the first copy becomes invisible disk garbage.
- **Evidence:** see the quoted block above; compare with `core/database.py:1282`
  ```python
  cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
  — byte-for-byte the same statement.
- **Reproduction / verification:** monkeypatch `db.mark_track_downloaded` to raise `sqlite3.OperationalError("database is locked")` and drive `DownloadManager._download_worker` (the pattern used by `tests/test_downloader_cancel.py`); assert that `download_failed` is emitted, the queue row becomes `failed`, and the file is still on disk with `tracks.is_downloaded = 0`.
- **Suggested fix:** drop the duplicated statement — call `db.mark_track_downloaded` once inside a `try`, and on failure treat the download as *failed but keep the file path* (log it and mark the row `failed` with the path in `download_queue.error`), or retry the single write with the DB’s own busy timeout instead of re-issuing it inline. Wrap any fallback in its own `try/except`.
- **Fix side effects:** if the write keeps failing, the file is still orphaned — the durable fix is to record the pending path in `download_queue` so a later pass can bind it to the row.
- **Discovered by:** B — **owning area: WN-13** (`core/downloader.py`).

---

#### F-WX-02-6  [P3] — `library_updated` carries two different payload shapes for one event name

- **File:** `core/downloader.py:835` (`True`), `core/api.py:3264` (`{"covers": updated}`), `core/api.py:3454,3898,3904,3993` (`True`), `services/watchdog_service.py:129` (`True`), `ui/web_new_v2/js/events.js:211-231` (consumer)
- **Confirmed:** yes
- **Description:** The same event name is emitted with a boolean payload by six call sites and with a dict payload by one. The current consumer ignores the payload, so nothing breaks today — but the contract is undefined, and the only emitter that carries *any* information (which covers were refreshed) is the one the frontend cannot use, because `events.js` reacts to `library_updated` with a blind full re-read.
- **Cause:** the event is used as a bare “something changed” ping from seven independent producers, with no payload schema.
- **Trigger conditions:** any future consumer that reads `library_updated`’s payload (e.g. to refresh only the covers that changed) will work for one producer and mis-handle six.
- **User impact:** none today; latent.
- **Evidence:**
  ```python
  # core/downloader.py:835
  self._emit('library_updated', True)
  ```
  ```python
  # core/api.py:3263-3264
  if updated:
      self._emit("library_updated", {"covers": updated})
  ```
- **Reproduction / verification:** `Select-String -Path core\*.py,services\*.py -Pattern '_emit\(.library_updated'` → seven hits, two payload shapes.
- **Suggested fix:** standardise on a dict (`{"reason": "download" | "covers", ...}`) and document it next to the event name, or drop the payload-bearing emitter.
- **Fix side effects:** `events.js` would need to tolerate the new shape; it currently ignores the payload, so no change is required there.
- **Discovered by:** B

---

#### F-WX-02-7  [P3] — The download processor thread is never joined; a worker can keep writing to the database after `db.close()`

- **File:** `core/downloader.py:89-90` (thread start), `core/downloader.py:884-909` (`stop`), `core/app.py:545-546` + `core/app.py:559-560` (ordering)
- **Confirmed:** yes
- **Description:** `stop()` shuts the pool down (`wait=False, cancel_futures=True`), bumps the cancel epoch and waits up to `drain_timeout = 5.0 s` for the running futures — but `_processor_thread` is never joined. `core/app.py` then calls `db.close()`. Two windows remain:
  1. The processor can still be inside `self._pool.submit(...)`; the `RuntimeError` from a shut-down pool is caught, and the processor calls `self._on_batch_task_done(...)` → `self._emit('batch_download_progress', …)` on a manager whose app is closing.
  2. A worker that missed the 5 s drain deadline keeps running. Its next `self._core.db.…` call goes through `DatabaseManager._get_connection()`, which **opens a fresh connection** if the thread-local one is gone (`core/database.py:179-201`) and writes to the database file *after* the application declared it closed. `db.close()` only closes the connections it knows about (`core/database.py:2459-2489`) and explicitly documents that handles owned by other threads “survive until their own thread ends”.
- **Cause:** `stop()` bounds the wait but does not guarantee it, and the DB lifetime is not tied to the downloader’s thread lifetime.
- **Trigger conditions:** closing the app while a download is in flight (a >5 s provider stall, or a retry sleep of 20 s / 40 s — `core/downloader.py:621,704-708` sleeps in 1 s slices but the whole sleep is inside the worker).
- **User impact:** a `download_queue` row can be written as `downloading`/`failed` by a worker after the app has closed the DB; the next start’s `DownloadStore.recover()` (`core/download_store.py:58-64`) resets it, so the visible damage is limited to a spurious `downloading` row and a stray log line. No user data is lost.
- **Evidence:**
  ```python
  # core/downloader.py:89-90
  self._processor_thread = threading.Thread(target=self._process_queue, daemon=True)
  self._processor_thread.start()
  ```
  ```python
  # core/downloader.py:884-909  (no join of _processor_thread anywhere)
  def stop(self, drain_timeout: float = 5.0):
      self._store.preserve_shutdown()
      self._running = False
      self._cancel_epoch += 1
      ...
      self._pool.shutdown(wait=False, cancel_futures=True)
      deadline = time.monotonic() + max(0.0, float(drain_timeout))
      for fut in self._running_futures():
          ...
  ```
- **Reproduction / verification:** grep — `Select-String -Path core\downloader.py -Pattern "_processor_thread"` → only the two lines above; no `join(` anywhere for it. Runtime check: start a download, close the app during it, and look for `downloader.emit batch_download_progress failed` or a `download_queue` UPDATE after `db.close` in `~/.nedotify/logs/app.log`.
- **Suggested fix:** `stop()` should `self._processor_thread.join(timeout=…)` after clearing the queue, and the drain deadline should be enforced on the workers’ *DB writes* (e.g. a `self._closing` flag checked before each `db` write), or `db.close()` should be deferred until the downloader threads are gone.
- **Fix side effects:** joining the processor adds up to ~1 s to shutdown (its idle wait is `self._queue_event.wait(timeout=1.0)`); `stop()` already sets the event, so the join returns immediately in the common case.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (brief):

- **The file is written atomically.** Every provider writes to a `.part` sidecar and renames on success: yt-dlp’s own `<outtmpl>.part` → rename, and `core/download_transfer.py:109-125` writes `output_path + '.part'` and finishes with `os.replace(partial_path, output_path)` (same volume → atomic). A crash leaves a `.part`, never a truncated final file.
- **The DB row is written only after the file passed the integrity gate.** `core/downloader.py:801-819`: `_downloaded_file_defect(file_path)` runs *before* `mark_track_downloaded`; a rejected file is removed (`core/downloader.py:811`) and the download is reported as failed. Pinned by `tests/test_download_integrity.py`.
- **The download filename is NOT derived from the title/artist — the “crafted title” path-traversal hypothesis does not hold.** The stem is `download_{sanitised track_id}_{sha256(source:source_id)[:16]}` (`core/download_transfer.py:18-20`), and the per-provider fallbacks are `yt_{re.sub(r'[^a-zA-Z0-9_-]','_',source_id)}_{ts}` (`services/youtube_service.py:1079-1081`), `sc_{ts}` / `sc_yt_{ts}` (`services/soundcloud_service.py:911,931`) and `ya_{safe_id}_{ts}.mp3` (`services/yandex_service.py:271-272`, already sanitised — the contract-#8 note in `WIN_AUDIT_CONTEXT.md:92-94` is stale). `AC/DC` and `Foo: Bar` cannot reach a filename, so no illegal Windows character and no traversal is possible from metadata. As defence in depth, yt-dlp’s `sanitize_filename` maps `\/|*<>` to `\0_` and `:` to a substitute (verified in `.venv_win/Lib/site-packages/yt_dlp/utils/_utils.py`), and `download_context.download_http` re-validates every redirect target with `is_safe_media_url` (`core/download_transfer.py:65-78`).
- **The proxy gate is sound.** `core/proxy.py:238-272` refuses UNC and `file:` URLs before any FS access, requires a drive letter, requires an allow-listed audio extension, `realpath`s the candidate, and then requires it to be inside `~/.nedotify` **or** referenced by a `tracks.file_path`/`cover_path` row (`core/proxy.py:209-235`). A path written into the DB by the downloader can only be inside `~/.nedotify/downloads`, so the `tracks`-row branch cannot be abused to read arbitrary files from the download path.
- **Download concurrency is bounded.** `_MAX_INFLIGHT = 2` (`core/downloader.py:22`), the pool is `max_workers=2` (`core/downloader.py:58`) and `_wait_for_free_slot()` applies backpressure (`core/downloader.py:423-435`), so a 200-track batch cannot open 200 sockets.
- **The progress write is throttled and the DB write is inside the throttle.** `_record_progress` (`core/downloader.py:157-169`) returns early when less than 0.75 s has passed *before* the `self._store.update(...)` and the `_emit`, so neither the WAL commit nor the bridge round trip happens per chunk. `download_context.download_http` calls `self.progress(...)` after every 128 KiB chunk, but the throttle absorbs that.
- **Contract #7 is honoured.** `download_complete` carries `{'track_id': track_id}` only — no `file_path` (`core/downloader.py:839`).
- **The status vocabulary is consistent between the backend and the frontend.** `pending|downloading|paused|completed|failed|cancelled` in `core/download_store.py:43-44` and `core/database.py:2350,2404,2410` matches `statusLabels` in `ui/web_new_v2/js/downloads-view.js:9-12`.
- **A crash does not leave the row stuck in “downloading”.** `DownloadStore.recover()` (`core/download_store.py:58-64`) flips `downloading` (and `resume_on_restart=1`) back to `pending` at startup, and `_resume_pending_downloads()` re-queues them (`core/downloader.py:333-354`).
- **The progress listener does not accumulate.** `addPythonEventHandler` is called exactly three times, all during `init()` (`ui/web_new_v2/js/main.js:538,592,678`); `handleDownloadManagerEvent` is a module-level function, not a per-download closure.
- **A track cannot be queued twice.** `ux_download_queue_track` is a UNIQUE index on `download_queue(track_id)` (`core/database.py:2309-2311`), and `download_queue_add` re-arms only terminal states (`core/database.py:2347-2351`).
- **`download_complete` reaches the UI even though `events.js` treats `download_queue_updated`/`download_progress` as no-ops** (`ui/web_new_v2/js/events.js:76-80`): the queue view is fed by the second, independent subscriber registered in `ui/web_new_v2/js/main.js:538` → `ui/web_new_v2/js/feature-controls.js:104-106`.

### 4. Coverage gaps

- **No live download was performed.** The `.mp4` mismatch (F-WX-02-2) is derived from the format ladder (`services/youtube_service.py:348`) and the extension-set diff, not from an observed `.mp4` download. Confirming it end-to-end needs a network download of a video that only has progressive formats.
- **Frontend call counts are static, not instrumented.** The “5 × `get_downloaded_tracks()`” figure comes from reading `events.js` / `library.js` / `feature-controls.js` / `downloads-view.js`; no browser run or bridge tracer was used. The *per-call* cost (30 ms, 1.21 MB) is measured; the *call count* is derived.
- **pywebview’s `evaluate_js` blocking behaviour is inferred** from the repository’s own note (`AGENTS.md`, `core/api.py:1141-1146`: “pywebview’s WinForms backend marshals evaluate_js through Control.Invoke”) and from `webview/platforms/winforms.py` using `Control.Invoke`. I did not instrument the WebView to measure the round-trip latency.
- **The provider internals were read only as far as the WX-02 contract requires** (filename construction, atomicity, integrity gate). yt-dlp’s own `.part`→rename behaviour was read from the installed package, not from a live download.
- **Shutdown beyond `AppCore.cleanup()` was not traced** (`main.py`’s watchdog-restart path is WX-07’s scope); F-WX-02-7 therefore bounds the claim to “the DB may be written after `db.close()`”, not to what the watchdog does with it.
- **`core/api.py`’s remaining ~4 200 lines were not read end-to-end**; only the download/storage/playback methods in the WX-02 path were opened.
- **Plugin and user-script reachability of `clear_storage("all")`** (F-WX-02-3) was not tested; only the code path from the bridge method down to the file deletion was executed.

---

### 5. Architecture improvements (ARCH)

No proven defect in these items — engineering directions only.

#### ARCH-1 — There is no single owner of the “download completion” contract

The contract that turns “bytes on disk” into “a playable track in the library” is spread over **9 files** and **15 distinct contract points**. `core/downloader.py` is the de-facto owner of the *emission*, but the *state* lives in two tables and the *reaction* lives in two dispatchers and four views.

| # | Contract point | Defined in | Consumed in | Copies |
|---|---|---|---|---|
| 1 | event `download_complete`, payload `{track_id}` | `core/downloader.py:839` | `events.js:258`, `feature-controls.js:104`, `library.js:962`, `utils.js:1008` | 4 consumers / 2 dispatchers |
| 2 | event `download_failed` (+ `describe_error` merge) | `core/downloader.py:171-183,858,879` | `events.js:266`, `feature-controls.js:104`, `utils.js:1019` | 3 |
| 3 | event `download_progress` `{downloaded_bytes,total_bytes,track_id,percent}` | `core/downloader.py:157-169` | `feature-controls.js:104` → `downloads-view.js:183` | 2 |
| 4 | event `download_queue_updated` `{track_id?, status}` | `core/downloader.py:112,127,137,284,382,409,787,838,860,881` (10 sites) | `events.js:78` (no-op), `feature-controls.js:104` | 2 dispatchers |
| 5 | event `library_updated` (two payload shapes) | `core/downloader.py:835`, `api.py:3264/3454/3898/3904/3993`, `watchdog_service.py:129` | `events.js:211` | 7 producers, 1 shape-drift |
| 6 | events `batch_download_{started,progress,finished,cancelled}` | `core/downloader.py:211,228,235,283`, `core/api.py:3715` | `events.js:242-256`, `library.js:85` | 2 |
| 7 | DB column `tracks.is_downloaded` | `core/database.py:371` | `downloader.py:819/825`, `api.py:2673/3692`, `smart_playlists.py:146`, `taste_profile.py:175`, `cache_manager.py:204` | 6 readers |
| 8 | DB column `tracks.file_path` (`UNIQUE`) | `core/database.py:219` | `downloader.py:819`, `proxy.py:221`, `offline.py:38`, `api.py:1660`, `cache_manager.py:204` | 5 readers |
| 9 | `download_queue.status` vocabulary (6 strings) | `core/database.py:2294`, `download_store.py:43-44` | `downloader.py` (41 literals), `download_store.py` (6), `database.py` (7), `downloads-view.js` (7) | **62 literals in 5 files** |
| 10 | `download_queue.{downloaded_bytes,total_bytes,error,attempt,resume_on_restart}` | `core/download_store.py:4-10` | `downloader.py`, `download_store.py`, `downloads-view.js` (percent derived) | 3 |
| 11 | download directory `~/.nedotify/downloads` | `core/downloader.py:789` | `core/api.py:2700` (quota scan), `core/proxy.py:264` (`_nedotify_root`) | 3 |
| 12 | file-path stem `download_{track}_{digest}` | `core/download_transfer.py:18-20` | `youtube_service.py:1169`, `soundcloud_service.py:956`, `yandex_service.py:279` | 3 |
| 13 | “is this an audio file?” extension set | `downloader.py:32`, `youtube_service.py:137`, `proxy.py:125`, `offline.py:7`, `file_scanner.py:16` | — | **5 divergent copies** (F-2) |
| 14 | “is this a valid download?” gate | `downloader.py:37-52`, `youtube_service.py:142-163` | — | **2 identical copies** |
| 15 | the “mark downloaded” DB write | `downloader.py:819` (+ verbatim copy at `825`), `database.py:1282` | — | 2 copies of one SQL |

Direction: introduce a single `DownloadContract` module (status enum, event names + payload schemas, the audio-extension set, the integrity gate) and have `core/downloader.py`, `core/download_store.py`, `core/database.py` and the two frontend dispatchers import/derive from it. On the JS side, fold the second dispatcher (`feature-controls.js:104`) into `events.js` so every bridge event has exactly one switch.

#### ARCH-2 — The completion event carries no incremental payload, so the only way to refresh is a full re-read

`download_complete` deliberately carries no `file_path` (contract #7) — but it also carries no title, artist, duration or byte count, and no “this row changed” information. Every consumer therefore has to re-read the whole library to learn that one track appeared. Combined with the three duplicate reactions in F-WX-02-1, the cost is 4–8 full library fetches per download. Direction: let `download_complete` carry a *display-ready* delta (id, title, artist, duration, file size — no absolute path), so the library can append one row instead of re-reading the table; keep the path server-side.

#### ARCH-3 — The download state machine is spread over two tables with two copies of the track identity

`tracks` (metadata + `is_downloaded` + `file_path`) and `download_queue` (status + a second `source`/`source_id` + progress columns) both describe the same download, and nothing owns the reconciliation. This produced F-WX-02-4 (stale `source_id`) and F-WX-02-3 (dangling `is_downloaded`). Direction: keep `tracks` as the only owner of the track identity, let `download_queue` own *only* the transfer state, and derive “is downloaded” from the file’s existence (or keep the flag but repair it in one place).

#### ARCH-4 — The frontend has no coalescing layer for library refreshes

`library_updated` is debounced by 300 ms (`events.js:215-230`) but `download_complete` is not, and the debounce is per-event-name, not per-resource. Direction: one `scheduleLibraryRefresh()` used by every library-affecting event, with a “dirty resource” set, so a burst of N downloads produces one refresh instead of 4–8N.

#### ARCH-5 — Progress is push-only on the Python side and poll-on-unknown on the JS side

`downloads-view.js:181-193` reacts to `download_progress` in place but falls back to `scheduleRefresh()` (a full `get_downloads()`) for every event it cannot apply — including a progress event for a track that is not yet in its item list. Direction: let the progress payload carry the fields the row needs (status, title, artist) so the view never has to re-read the queue to draw one row.
