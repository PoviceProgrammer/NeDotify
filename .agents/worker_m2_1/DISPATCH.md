## 2026-08-07T18:31:14Z

You are the Worker (`teamwork_preview_worker`) for Milestone 2: Track Downloading & DB Integrity in AURA Music.

Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m2_1

Mandatory Reading Files:
1. ORIGINAL_REQUEST.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. PROJECT.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. SCOPE.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m2/SCOPE.md
4. Explorer 1 Report: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m2_1_gen2/handoff.md
5. Explorer 2 Report: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m2_2_gen2/handoff.md
6. Explorer 3 Report: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m2_3_gen2/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Assigned Implementation Tasks (Features 6-11):

1. **Feature 10: Windows Path & Filename Sanitization (`utils/path_utils.py`)**:
   - Create `utils/path_utils.py` if not present.
   - Implement `sanitize_filename(filename, replacement="_")` and `sanitize_path(path)`.
   - Handle Unicode NFC normalization (`unicodedata.normalize('NFC', text)`), illegal Windows characters (`\ / : * ? " < > |`), Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), trailing dots/spaces, and length bounds.

2. **Feature 6: Downloader Spotify Fallback (`core/downloader.py`)**:
   - In `_download_worker`, handle `source == "spotify"`.
   - Retrieve track metadata (`title`, `artist`) from SQLite database for `track_id`.
   - Construct YouTube search query `ytsearch1:{artist} - {title}` (or search YouTube service), download audio stream via yt-dlp/CacheManager, and preserve original `source = "spotify"` in SQLite DB.

3. **Feature 7: Dedicated Download Directory (`utils/cache_manager.py` & `core/downloader.py`)**:
   - In `utils/cache_manager.py`, initialize `self._downloads_dir` (`.cache/downloads/` or `~/.nedotify/downloads/`) and expose property `downloads_dir`.
   - Parameterize `CacheManager.download_audio_stream` to accept `target_dir=...` (defaulting to `streams_dir`).
   - Route track downloads in `core/downloader.py` to `downloads_dir`.
   - Ensure `CacheManager.get_cache_size` and `CacheManager.enforce_cache_limit` strictly calculate and clear `self._streams_dir` only, isolating downloaded tracks from stream cache deletion.

4. **Feature 8 & 11: UI Events & Error Feedback & Queue Resilience (`core/downloader.py`, `core/api.py`, `ui/web_new/js/events.js`)**:
   - In `core/downloader.py`, emit `track_downloaded` event with `{"track_id": track_id, "file_path": file_path}` upon success.
   - On download error in `_download_worker`, emit `download_failed` event with `{"track_id": track_id, "error": str(e)}`, update `download_queue` status to `'failed'`, log the error, and ensure `is_downloaded` remains `0`.
   - In `ui/web_new/js/events.js`, handle `track_downloaded` (refreshing offline list & playlists) and `download_failed` (showing error toast via `showToast`).

5. **Feature 9: Database Downloaded Status Integrity (`core/downloader.py`)**:
   - In `core/downloader.py`, update `tracks` table with `is_downloaded = 1` and `file_path = ?` upon download completion without setting `source = 'local'`. Keep original `source` provider intact.

6. **Build & Test Verification**:
   - Run tests using command `python run_tests.py` (or `pytest tests/test_nedotify.py`).
   - Document exact test commands executed and results in your `handoff.md`.

Output Requirements:
- Write `handoff.md` in your working directory (`c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m2_1/handoff.md`).
- Update your `progress.md` liveness heartbeat.
- Send a message to parent when done referencing `handoff.md`.
