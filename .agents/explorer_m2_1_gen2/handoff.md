# Handoff Report — Downloader Spotify Fallback & Windows Path Sanitization (Milestone 2)

## 1. Observation

### 1.1 Feature 6: Downloader Spotify Fallback Search (`core/downloader.py`)
- **Location**: `core/downloader.py` (lines 68-122)
- **Current Behavior**:
  In `DownloadManager._download_worker` (lines 77-84):
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
- **Finding**: Attempting to download any Spotify track (`source == "spotify"`) falls into the `else:` branch, raising `ValueError("Unsupported download source: spotify")`. This catches in the `except Exception as e:` block (line 110), marks the `download_queue` status as `'failed'` (line 116), and logs `Download worker failed for <track_id>: Unsupported download source: spotify`.
- **Existing Fallback Contract**:
  - `services/spotify_service.py` (line 64) already specifies: `"search_fallback_query": f"ytsearch1: {artist} - {title}"`.
  - `services/spotify_service.py` (lines 95-97) states: `Spotify playback resolved via YouTube fallback`.
  - `core/app.py` (lines 164-200) implements stream re-resolution fallback to YouTube when non-YouTube streams fail.
  - However, `core/downloader.py` lacks the logic to query `tracks` table for `artist` and `title` when `source == "spotify"` and construct the `ytsearch1:{artist} - {title}` search URL for `yt-dlp` / audio extraction.

### 1.2 Feature 10: Windows Path & Filename Sanitization (`utils/path_utils.py`)
- **Location**: `utils/path_utils.py` does NOT currently exist in the codebase.
- **Current Sanitization Gaps**:
  - `utils/cache_manager.py` (line 139) outputs files using template `os.path.join(self._streams_dir, f"{download_id}.%(ext)s")` where `download_id` is `{source}_{source_id}`.
  - When raw track titles or artists are used for saved track files (e.g. `.cache/downloads/{artist} - {title}.mp3`), characters illegal in Windows paths (`\ / : * ? " < > |`), control characters (`0x00-0x1F`), trailing spaces/dots, or Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) cause `OSError: [Errno 22] Invalid argument` or `[Errno 2] No such file or directory`.
  - Cyrillic characters under NFD Unicode decomposition (common when copied from certain macOS/Linux sources or Web APIs) can cause string mismatch or filesystem issues if not normalized to NFC (`unicodedata.normalize('NFC', text)`).
  - Filenames exceeding 255 characters cause `MAX_PATH` overflow errors on Windows unless truncated while preserving extension.
- **Reference Contract in Tests**:
  - `tests/test_downloader_e2e.py` (lines 35-84) includes a reference implementation of `sanitize_filename` and `sanitize_path` to validate Feature 10 requirements across 10 specific test cases (`T1-41` through `T2-50`).

### 1.3 Interconnected Downloader Flaws in Scope
- **Database Source Overwrite**: `core/downloader.py` (line 94) executes `UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?`. Overwriting `source` with `'local'` destroys provider origin metadata (breaking Feature 9).
- **Directory Isolation**: `downloader.py` (line 74) creates `download_dir` (`.cache/downloads/`), but delegates streaming to `cache.download_audio_stream`, which places files in `streams_dir` where `enforce_cache_limit` purges them when total size exceeds 500 MB (breaking Feature 7).
- **UI Event Name Disconnect**: `downloader.py` (line 106) emits `download_complete`, whereas `ui/web_new/js/events.js` (line 126) listens for `track_downloaded` (breaking Feature 8).
- **Silent Failure Notification**: `downloader.py` (lines 110-121) catches worker errors and updates `download_queue` status to `'failed'`, but fails to emit `download_failed` event to UI (breaking Feature 8 & 11).

---

## 2. Logic Chain

1. **Spotify Fallback Download Failure**:
   - *Observation*: `services/spotify_service.py` provides tracks with `source: "spotify"`. `core/downloader.py` checks `source` against `soundcloud`, `youtube`, and `yandex`, throwing `ValueError` for `spotify`.
   - *Logic*: Spotify tracks cannot be downloaded directly via Spotify URLs due to DRM. However, Spotify track records in SQLite contain `title` and `artist`. When downloading a Spotify track, `_download_worker` must query SQLite for `(artist, title)` of `track_id`, construct a search query `f"{artist} - {title}"`, format the target URL as `f"ytsearch1:{query}"`, and pass it to `yt-dlp` / download execution.
   - *Conclusion*: Adding `if source == "spotify":` in `_download_worker` to look up metadata and set `url = f"ytsearch1:{query}"` resolves YouTube fallback downloads for Spotify tracks while preserving `source = "spotify"` in the database.

2. **Windows Path Sanitization Requirement**:
   - *Observation*: `utils/path_utils.py` is absent, and raw filenames containing Cyrillic NFD text, Windows reserved characters (`\ / : * ? " < > |`), trailing dots/spaces, or reserved device names (`CON`, `PRN`, etc.) crash file operations on Windows.
   - *Logic*: Creating `utils/path_utils.py` with `sanitize_filename(filename, replacement="_")` and `sanitize_path(path)` ensures:
     1. `unicodedata.normalize('NFC', text)` normalizes Cyrillic and Unicode characters.
     2. `re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', replacement, filename)` strips illegal characters.
     3. `.strip(" .")` removes trailing periods and spaces.
     4. Checking `RESERVED_WINDOWS_NAMES` prefixes reserved names with `_`.
     5. Length check truncates filenames > 255 characters preserving file extension.
     6. Default fallback `"untitled"` for empty/invalid input.
   - *Conclusion*: Implementing `utils/path_utils.py` according to this specification fulfills Feature 10 and provides safe path resolution for `DownloadManager` and `CacheManager`.

3. **Database Provider Preservation (Feature 9)**:
   - *Observation*: `downloader.py` line 94 sets `source = 'local'` when marking tracks downloaded.
   - *Logic*: `tracks` table already tracks offline availability via `is_downloaded = 1` and `file_path`. Overwriting `source` breaks queries filtering by provider (`source = 'spotify'`). Removing `source = 'local'` from the SQL UPDATE query keeps original provider metadata intact.

4. **UI Event Synchronization (Feature 8 & 11)**:
   - *Observation*: `downloader.py` line 106 emits `download_complete`, but `events.js` line 126 listens for `track_downloaded`. Errors are logged but not emitted.
   - *Logic*: Emitting `track_downloaded` with payload `{"track_id": track_id, "file_path": file_path}` on success and `download_failed` with payload `{"track_id": track_id, "error": str(e)}` on failure syncs backend state with UI toasts and auto-refreshes offline track lists.

---

## 3. Caveats

- **No DRM Bypass**: In strict compliance with project constraints, DRM-protected content must not be bypassed or decrypted. Spotify downloads rely solely on searching YouTube for equivalent public audio streams. If a track is unavailable on YouTube or returns no search results, the download gracefully fails, queue status becomes `'failed'`, and `download_failed` event is emitted.
- **yt-dlp Network Dependencies**: YouTube search extraction relies on `yt-dlp`'s `ytsearch1:` extractor. Network timeouts or yt-dlp version mismatches are caught by exception handlers and converted to structured `download_failed` UI notifications.

---

## 4. Conclusion

The Downloader module (`core/downloader.py`) requires two key structural improvements:
1. **Feature 6 (Spotify Fallback)**: Enable Spotify track downloading in `core/downloader.py` by querying DB for track metadata (`artist`, `title`), building `ytsearch1:{artist} - {title}` search URL, downloading via YouTube audio stream, and preserving original `source = "spotify"` in SQLite.
2. **Feature 10 (Path Sanitization)**: Create `utils/path_utils.py` with `sanitize_filename` and `sanitize_path` to handle Cyrillic NFC normalization, illegal Windows character replacement (`\ / : * ? " < > |`), trailing period/space trimming, reserved device names (`CON`, `PRN`, etc.), and 255-char MAX_PATH limits.

---

## 5. Recommended Code Changes

### Change 1: Create `utils/path_utils.py` (Feature 10)

Target File: `utils/path_utils.py`

```python
"""
AURA Music - Windows Path & Filename Sanitization Utility
Handles Cyrillic Unicode normalization (NFC), removal of illegal Windows characters,
reserved filenames, trailing dot/space trimming, and MAX_PATH length limits.
"""

import os
import re
import unicodedata

RESERVED_WINDOWS_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

ILLEGAL_CHARS_PATTERN = re.compile(r'[\x00-\x1f\x7f\\/:*?"<>|]')


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """
    Sanitizes a single filename string for Windows filesystem compatibility.
    """
    if not filename or not isinstance(filename, str):
        return "untitled"

    # 1. Unicode normalization (NFC) for Cyrillic and international text
    filename = unicodedata.normalize("NFC", filename)

    # 2. Prevent path traversal
    filename = filename.replace("../", "").replace("..\\", "")

    # 3. Replace illegal Windows characters & control characters
    filename = ILLEGAL_CHARS_PATTERN.sub(replacement, filename)

    # 4. Trim leading/trailing spaces and dots
    filename = filename.strip(" .")
    if not filename:
        return "untitled"

    # 5. Check Windows reserved names
    stem = os.path.splitext(filename)[0].upper()
    if stem in RESERVED_WINDOWS_NAMES:
        filename = f"_{filename}"

    # 6. MAX_PATH safety: truncate long filenames preserving extension
    if len(filename) > 255:
        base, ext = os.path.splitext(filename)
        max_base_len = max(1, 255 - len(ext))
        filename = base[:max_base_len] + ext

    return filename


def sanitize_path(path: str) -> str:
    """
    Sanitizes a full file system path safely.
    Preserves drive letters (e.g. C:) while sanitizing all individual directory and filename components.
    """
    if not path or not isinstance(path, str):
        return ""

    path = unicodedata.normalize("NFC", path)
    path = path.replace("../", "").replace("..\\", "")
    parts = path.replace("\\", "/").split("/")
    
    sanitized_parts = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i == 0 and len(part) == 2 and part[1] == ":":
            sanitized_parts.append(part)
        else:
            sanitized_parts.append(sanitize_filename(part))

    res = "/".join(sanitized_parts)
    if path.startswith("/") and not res.startswith("/"):
        res = "/" + res

    return os.path.normpath(res)
```

---

### Change 2: Update `core/downloader.py` (Feature 6, 8, 9, 11)

Target File: `core/downloader.py`

**Before (lines 77-121)**:
```python
            if source == "soundcloud":
                url = f"https://soundcloud.com/{source_id}" if "/" in str(source_id) else f"https://api-v2.soundcloud.com/tracks/{source_id}"
            elif source == "youtube":
                url = f"https://www.youtube.com/watch?v={source_id}"
            elif source == "yandex":
                url = f"https://music.yandex.ru/track/{source_id}"
            else:
                raise ValueError(f"Unsupported download source: {source}")

            future = self._core.cache.download_audio_stream(source, source_id, url)
            file_path = future.result() if future else None

            if file_path and os.path.exists(file_path):
                logger.info(f"Download complete: {file_path}")
                cursor = self._core.db.conn.cursor()
                self._ensure_queue_table(cursor)
                cursor.execute(
                    "UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?",
                    (file_path, track_id)
                )
                cursor.execute(
                    "UPDATE download_queue SET status = 'completed' WHERE track_id = ?",
                    (track_id,)
                )
                self._core.db.conn.commit()

                if hasattr(self._core, "api") and getattr(self._core, "api", None):
                    if hasattr(self._core.api, "_emit"):
                        self._core.api._emit("library_updated", True)
                        self._core.api._emit("download_complete", {"track_id": track_id})
            else:
                raise Exception("Download returned None or file missing.")

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

**After (Proposed Replacement)**:
```python
            if source == "spotify":
                # Retrieve track from DB to extract title & artist for YouTube fallback search
                track = self._core.db.get_track(track_id) if self._core and hasattr(self._core, "db") else None
                artist = (track.get("artist") if track else None) or ""
                title = (track.get("title") if track else None) or ""
                if artist and title and artist != "Unknown Artist" and title != "Unknown":
                    query = f"{artist} - {title}"
                elif title and title != "Unknown":
                    query = title
                elif artist and artist != "Unknown Artist":
                    query = artist
                else:
                    query = f"track {track_id}"
                url = f"ytsearch1:{query}"
            elif source == "soundcloud":
                url = f"https://soundcloud.com/{source_id}" if "/" in str(source_id) else f"https://api-v2.soundcloud.com/tracks/{source_id}"
            elif source == "youtube":
                url = f"https://www.youtube.com/watch?v={source_id}"
            elif source == "yandex":
                url = f"https://music.yandex.ru/track/{source_id}"
            else:
                raise ValueError(f"Unsupported download source: {source}")

            future = self._core.cache.download_audio_stream(source, source_id, url)
            file_path = future.result() if future else None

            if file_path and os.path.exists(file_path):
                logger.info(f"Download complete: {file_path}")
                cursor = self._core.db.conn.cursor()
                self._ensure_queue_table(cursor)
                # Preserve original source provider in DB (do NOT set source = 'local')
                cursor.execute(
                    "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
                    (file_path, track_id)
                )
                cursor.execute(
                    "UPDATE download_queue SET status = 'completed' WHERE track_id = ?",
                    (track_id,)
                )
                self._core.db.conn.commit()

                if hasattr(self._core, "api") and getattr(self._core, "api", None):
                    if hasattr(self._core.api, "_emit"):
                        self._core.api._emit("library_updated", True)
                        self._core.api._emit("track_downloaded", {"track_id": track_id, "file_path": file_path})
                        self._core.api._emit("download_complete", {"track_id": track_id})
            else:
                raise Exception("Download returned None or file missing.")

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

            if hasattr(self._core, "api") and getattr(self._core, "api", None):
                if hasattr(self._core.api, "_emit"):
                    self._core.api._emit("download_failed", {"track_id": track_id, "error": str(e)})
```

---

## 6. Verification Method

To verify these implementations:

1. **Run Unit & E2E Test Suite**:
   ```powershell
   pytest tests/test_downloader_e2e.py
   ```
   All 60 test cases (including Feature 6 `TestFeature6SpotifyFallback` and Feature 10 `TestFeature10WindowsPathSanitization`) should pass.

2. **Files to Inspect**:
   - `utils/path_utils.py` (New file)
   - `core/downloader.py` (Updated source handling, DB query, event emission)
   - `tests/test_downloader_e2e.py`

3. **Manual Invalidation Conditions**:
   - If downloading a Spotify track raises `ValueError: Unsupported download source: spotify`, Feature 6 implementation is missing/invalid.
   - If downloading a track with Cyrillic characters or Windows reserved characters (`:`, `?`, `"`) throws `OSError` or `[Errno 22]`, Feature 10 path sanitization is failing.
