# Handoff Report — Track Downloading Architecture Investigation

## 1. Observation

### 1.1 Architecture & Component Mapping
- **`core/downloader.py` (`DownloadManager`)**:
  - Initializes a 2-worker pool via `ThreadPoolExecutor(max_workers=2)` (line 19).
  - Manages SQLite table `download_queue` with columns `(track_id, source, source_id, status, created_at)` (lines 24-32).
  - Resumes pending downloads on app startup via `_resume_pending_downloads()` (lines 34-45).
  - In `_download_worker` (lines 68-122), constructs source URLs for SoundCloud, YouTube, and Yandex, then delegates streaming/download execution to `self._core.cache.download_audio_stream(source, source_id, url)` (line 86).
- **`utils/cache_manager.py` (`CacheManager`)**:
  - `download_audio_stream` (lines 111-167) uses `yt_dlp.YoutubeDL` with `'format': 'bestaudio/best'`.
  - Saves downloaded audio files to `self._streams_dir` (`~/.nedotify/streams/`) using output template `os.path.join(self._streams_dir, f"{download_id}.%(ext)s")` (line 139).
  - Implements `enforce_cache_limit(max_mb=500)` (lines 202-229), which automatically deletes the oldest files in `self._streams_dir` when total size exceeds 500 MB.
- **`core/api.py` (`AppApi.download_track`)**:
  - Exposes `download_track(track_data)` (lines 366-384) to JS frontend. Adds track to DB if `track_id` is missing and calls `self._core.downloader.queue_download(track_id, source, source_id)`.
- **`services/spotify_service.py` (`SpotifyService`)**:
  - Provides search metadata with `"search_fallback_query": f"ytsearch1: {artist} - {title}"` (line 64).
  - Calling `get_stream_url` raises `"Spotify playback resolved via YouTube fallback"` (lines 95-97).
- **`ui/web_new/js/contextmenu.js` & `ui/web_new/js/events.js`**:
  - `contextmenu.js` (lines 64-68): Triggers `window.pywebview.api.download_track(currentTargetTrack)` and displays toast `"Скачивание начато"`.
  - `events.js` (lines 126-130): Listens for Python event `'track_downloaded'` to refresh offline tracks via `loadDownloaded()`.

---

### 1.2 Verbatim Code Snippets of Identified Flaws

1. **Unsupported Spotify Source in `core/downloader.py` (lines 77-84)**:
```python
if source == "soundcloud":
    url = f"https://soundcloud.com/{source_id}" if "/" in str(source_id) else f"https://api-v2.soundcloud.com/tracks/{source_id}"
elif source == "youtube":
    url = f"https://www.youtube.com/watch?v={source_id}"
elif source == "yandex":
    url = f"https://music.yandex.ru/track/{source_id}"
else:
    raise ValueError(f"Unsupported download source: {source}")
```
*Observation*: Spotify is not handled. Calling `download_track` on a Spotify track raises `ValueError: Unsupported download source: spotify` and sets queue status to `'failed'`.

2. **Directory Mismatch and Cache Eviction Risk**:
- `core/downloader.py` line 74: `download_dir = os.path.join(self._core.cache.cache_dir, "downloads")`. Variable created but never passed to `download_audio_stream` or used.
- `utils/cache_manager.py` line 139: Downloads saved to `self._streams_dir` (`~/.nedotify/streams/`).
- `utils/cache_manager.py` line 209: `enforce_cache_limit` purges oldest files from `self._streams_dir`.
*Observation*: Tracks marked as permanently downloaded (`is_downloaded = 1`) are saved in the temporary streams cache and get deleted by `enforce_cache_limit` when cache exceeds 500 MB.

3. **Event Name Mismatch (`core/downloader.py` line 106 vs `ui/web_new/js/events.js` line 126)**:
- `downloader.py` line 106:
  ```python
  self._core.api._emit("download_complete", {"track_id": track_id})
  ```
- `events.js` line 126:
  ```javascript
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
      break;
  ```
*Observation*: Backend emits `download_complete`, but frontend listens for `track_downloaded`. The UI offline track list never automatically refreshes upon download completion.

4. **Source Overwrite in Database (`core/downloader.py` lines 93-96)**:
```python
cursor.execute(
    "UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?",
    (file_path, track_id)
)
```
*Observation*: Setting `source = 'local'` overwrites the track's original provider (`youtube`, `soundcloud`, `spotify`). This breaks DB track uniqueness checks (`WHERE source = ? AND source_id = ?`) and causes duplicate rows when searching or re-adding the track.

5. **Missing UI Error Feedback (`core/downloader.py` lines 110-121)**:
```python
except Exception as e:
    logger.error(f"Download worker failed for {track_id}: {e}")
    try:
        cursor = self._core.db.conn.cursor()
        self._ensure_queue_table(cursor)
        cursor.execute(
            "UPDATE download_queue SET status = 'failed' WHERE track_id = ?",
            (track_id,)
        )
        self._core.db.conn.commit()
    except Exception:
        pass
```
*Observation*: When a download fails, `download_queue` is updated to `'failed'`, but no event is emitted to `AppApi._emit`. The user receives no toast or visual indication that the download failed.

6. **Filename & Path Sanitization**:
- `utils/cache_manager.py` line 139 formats filenames as `{source}_{source_id}.{ext}`.
- There is no filename sanitization function (e.g. removing Windows illegal characters `< > : " / \ | ? *`, control characters, trailing dots/spaces, or normalizing Cyrillic Unicode characters).

---

## 2. Logic Chain

1. **Spotify Download Failure**:
   - *Observation*: `services/spotify_service.py` provides tracks with `source: "spotify"`. `core/downloader.py` checks `source` against `soundcloud`, `youtube`, and `yandex`, throwing `ValueError` for `spotify`.
   - *Logic*: Spotify tracks cannot be downloaded directly via Spotify URLs (due to DRM/lack of direct stream endpoints). However, Spotify tracks possess `title` and `artist` metadata (and `search_fallback_query`). When downloading a Spotify track, `DownloadManager` should fall back to searching YouTube for `"{artist} - {title}"`, resolving the YouTube video ID, and downloading the corresponding YouTube audio stream.

2. **Downloaded Track Eviction Bug**:
   - *Observation*: `downloader.py` creates `download_dir` (`.cache/downloads/` or `~/.nedotify/downloads`) but calls `CacheManager.download_audio_stream`, which places files into `streams_dir` (`~/.nedotify/streams/`). `CacheManager.enforce_cache_limit` purges `streams_dir`.
   - *Logic*: Saving permanent downloads into the stream cache directory exposes them to automatic cache truncation. Downloaded tracks must be saved to a dedicated target directory (`.cache/downloads/`), isolated from stream cache cleanup routines.

3. **UI Event Disconnect**:
   - *Observation*: `downloader.py` emits `download_complete`; `events.js` listens for `track_downloaded`.
   - *Logic*: Because the event names do not match, the frontend SSE handler ignores the backend event. Emitting `track_downloaded` (or registering `download_complete` in JS) resolves the UI sync issue.

4. **Database Identity Mutation**:
   - *Observation*: `downloader.py` updates `source = 'local'` in `tracks` table upon download completion.
   - *Logic*: Overwriting `source` breaks relational queries relying on `(source, source_id)`. The `tracks` table already has `is_downloaded = 1` and `file_path` to indicate local offline availability. `source` should remain its original provider name (`youtube`, `soundcloud`, `spotify`, `yandex`).

5. **Silent Downloader Failures**:
   - *Observation*: `downloader._download_worker` catches exceptions without notifying `AppApi`.
   - *Logic*: Updating `download_queue` status to `'failed'` in SQLite is necessary but insufficient. Emitting a `download_failed` event with track ID and error message allows `events.js` to trigger a user-facing toast and update queue UI state.

---

## 3. Caveats

- **No DRM Bypass**: In accordance with project constraints, DRM-protected content (e.g. encrypted streams) must not be decrypted or bypassed. If a SoundCloud track returns `DRM_PROTECTED` or yt-dlp fails due to content protection, the downloader must gracefully register a failed status and report the error to the UI.
- **Network / yt-dlp Variations**: `yt-dlp` extractor rules depend on upstream YouTube/SoundCloud web updates. Safe fallback option switches (e.g. `mweb,ios,web`) in `YouTubeService` are essential for download reliability.

---

## 4. Conclusion

The Track Downloading architecture in AURA Music has a solid foundation (`DownloadManager`, `ThreadPoolExecutor`, `download_queue` table), but contains 6 critical bugs/flaws preventing robust operation:
1. **Missing Spotify Fallback**: Downloading Spotify tracks fails with `ValueError`.
2. **Directory & Cache Eviction Flaw**: Downloads are stored in stream cache (`streams_dir`) instead of `.cache/downloads/`, causing them to be deleted by cache size enforcement.
3. **Event Name Mismatch**: Backend emits `download_complete`, frontend expects `track_downloaded`.
4. **Database Source Overwrite**: Setting `source = 'local'` corrupts track provider metadata and causes DB duplicates.
5. **Silent Error Handling**: Failures are logged but never reported to UI.
6. **Lack of Path Sanitization**: Missing safety checks for Windows reserved characters and Cyrillic filenames.

---

## 5. Specific Fix Recommendations for Milestone 2

1. **Implement Spotify Fallback in `core/downloader.py`**:
   - When `source == "spotify"`:
     - Query track details (`title`, `artist`) from DB.
     - Execute YouTube search using `self._core.youtube.search(f"{artist} {title}", max_results=1)`.
     - Extract YouTube video ID (`source_id`) and download via YouTube mechanism while preserving original Spotify `track_id` in DB.

2. **Fix Download Destination & Separate from Stream Cache**:
   - Move download output path to `.cache/downloads/` (or `os.path.join(cache_dir, "downloads")`).
   - Ensure `CacheManager.enforce_cache_limit` only operates on `streams_dir` and never touches `downloads_dir`.

3. **Sanitize Windows File Paths**:
   - Add a `sanitize_filename(filename)` utility:
     - Remove illegal Windows characters: `\ / : * ? " < > |`.
     - Handle Cyrillic and unicode normalization (`unicodedata.normalize('NFC', ...)`).
     - Trim trailing dots and spaces.
   - Format downloaded file paths cleanly (e.g., `.cache/downloads/{sanitized_artist} - {sanitized_title}.{ext}`).

4. **Fix Database Update Logic**:
   - Update `tracks` table with `is_downloaded = 1` and `file_path = ?`, but **do NOT change `source` to `'local'`**. Keep original `source`.

5. **Fix UI Events & Error Feedback**:
   - Update `downloader.py` to emit `track_downloaded`:
     ```python
     self._core.api._emit("track_downloaded", {"track_id": track_id, "file_path": file_path})
     self._core.api._emit("library_updated", True)
     ```
   - On error in `_download_worker`:
     ```python
     self._core.api._emit("download_failed", {"track_id": track_id, "error": str(e)})
     ```
   - Update `events.js` to handle `download_failed` and display an error toast (`showToast("Ошибка скачивания: " + data.error, "error")`).

6. **Enhance Queue Schema & API**:
   - Add `error_message` column to `download_queue` table.
   - Expose `get_download_queue()` and `retry_download(track_id)` in `AppApi`.

---

## 6. Verification Method

To verify the fixes independently in Milestone 2:

1. **Automated Test Execution**:
   Run the test suite:
   ```bash
   python run_tests.py
   ```
   Or run pytest directly:
   ```bash
   pytest tests/test_nedotify.py
   ```

2. **Files to Inspect**:
   - `core/downloader.py`
   - `utils/cache_manager.py`
   - `core/api.py`
   - `ui/web_new/js/events.js`
   - `ui/web_new/js/contextmenu.js`

3. **Manual Verification Steps**:
   - Queue YouTube track download -> verify file is created in `.cache/downloads/`, `is_downloaded = 1` in SQLite DB, and frontend updates "Offline tracks" view automatically.
   - Queue Spotify track download -> verify YouTube fallback search resolves video, downloads track successfully to `.cache/downloads/`, and marks track downloaded.
   - Trigger failed download (e.g. invalid URL) -> verify frontend receives `download_failed` event and displays error toast.
