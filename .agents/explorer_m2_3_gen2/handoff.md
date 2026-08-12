# Handoff Report — Feature 8 & Feature 11 Investigation

**Agent**: Explorer 3 (replacement generation 2)  
**Milestone**: Milestone 2 (Track Downloading & DB Integrity)  
**Working Directory**: `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m2_3_gen2`  
**Primary Scope**:
- **Feature 8**: Downloader UI Events & Error Handling (`core/downloader.py`, `core/api.py`, `ui/web_new/js/events.js`, `ui/web_new/js/contextmenu.js`)
- **Feature 11**: Downloader Queue Status & Error Reporting Resilience (`core/downloader.py`)

---

## 1. Observation

### 1.1 Summary of Relevant Components & Locations

1. **`core/downloader.py` (`DownloadManager`)**:
   - Handles background downloading using `ThreadPoolExecutor(max_workers=2)` (line 19).
   - Manages SQLite table `download_queue` with columns `(track_id, source, source_id, status, created_at)` (lines 24–32).
   - Executes background download jobs in `_download_worker` (lines 68–122).
   - On completion (lines 104–106), calls `self._core.api._emit("library_updated", True)` and `self._core.api._emit("download_complete", {"track_id": track_id})`.
   - On failure (lines 110–121), catches `Exception as e`, logs `logger.error(...)`, updates `download_queue` status to `'failed'`, but **emits no Python event** to `AppApi`.

2. **`core/api.py` (`AppApi`)**:
   - Implements thread-safe JS event bridge method `_emit(event_name, data=None)` (lines 164–178).
   - Exposes `download_track(track_data)` (lines 366–384) which delegates to `self._core.downloader.queue_download(...)`.

3. **`ui/web_new/js/events.js` (`window.onPythonEvent`)**:
   - Receives events dispatched from Python via `_emit` (lines 12–198).
   - Contains a `switch (eventName)` block:
     - Handles `'track_downloaded'` (lines 126–130) by calling `loadDownloaded()`, `loadPlaylists()`, and dispatching custom DOM event `nedotify:track_downloaded`.
     - **Missing handler**: Has no `case 'download_failed':`. Incoming `download_failed` events fall through to `default: console.log('Unknown event:', eventName)`.

4. **`ui/web_new/js/contextmenu.js` (`initContextMenu`)**:
   - Triggers download action on line 66 via `window.pywebview.api.download_track(currentTargetTrack)`.
   - Fires a client-side toast on line 67: `window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {msg: 'Скачивание начато'}}))`.

5. **`ui/web_new/js/library.js` (`loadDownloaded`)**:
   - Implements `loadDownloaded()` (lines 326–335) which re-queries backend via `window.pywebview.api.get_downloaded_tracks()` and updates the "Offline tracks" view.
   - Subscribes to `nedotify:track_downloaded` DOM event on lines 485–487.

---

### 1.2 Verbatim Code Evidence of Defects

#### Defect A: Mismatch in Event Name & Omission of `file_path` Payload (Feature 8)
- **`core/downloader.py` lines 103–107**:
  ```python
  if hasattr(self._core, "api") and getattr(self._core, "api", None):
      if hasattr(self._core.api, "_emit"):
          self._core.api._emit("library_updated", True)
          self._core.api._emit("download_complete", {"track_id": track_id})
  ```
  - *Verbatim Line 106*: Backend emits `"download_complete"`, but `events.js` line 126 expects `'track_downloaded'`.
  - *Payload Defect*: Backend sends `{"track_id": track_id}`. `PROJECT.md` §Interface Contracts & `SCOPE.md` require `{"track_id": track_id, "file_path": file_path}`.

#### Defect B: Missing Backend Error Event Emission (`download_failed`) (Feature 8 & Feature 11)
- **`core/downloader.py` lines 110–121**:
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
  - *Observation*: Upon exception in `_download_worker`, `download_queue` status is updated to `'failed'`, but `self._core.api._emit("download_failed", ...)` is **never invoked**.

#### Defect C: Missing Frontend Event Handler for `download_failed` (Feature 8)
- **`ui/web_new/js/events.js` lines 126–131**:
  ```javascript
  case 'track_downloaded':
      loadDownloaded();
      loadPlaylists();
      document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
      break;
  ```
  - *Observation*: `events.js` has no `case 'download_failed':`. When `download_failed` is dispatched, the frontend log prints `Unknown event: download_failed` and no toast notification or UI update occurs.

#### Defect D: Silent DB Update Failure Suppressions & Risk of False `is_downloaded` State (Feature 11)
- **`core/downloader.py` lines 117–121**:
  ```python
  except Exception:
      pass
  ```
  - *Observation*: In `_download_worker`'s error block, if the SQLite transaction fails (e.g. database lock), `except Exception: pass` silently suppresses the database error without logging it.
  - *False `is_downloaded` Flag Risk*: If a download fails after file allocation or if a track was already marked as downloaded before a failed retry, `tracks.is_downloaded` is not verified or reset on failure. The `tracks` table should be guaranteed to retain `is_downloaded = 0` if `file_path` does not exist on disk.

---

## 2. Logic Chain

1. **Event Contract Breakdown (Feature 8)**:
   - *Observation*: `core/downloader.py:106` emits `download_complete` with payload `{"track_id": track_id}`.
   - *Observation*: `ui/web_new/js/events.js:126` listens for `track_downloaded`.
   - *Step 1 Reason*: Because `"download_complete"` does not match `'track_downloaded'`, `events.js` ignores the completion event. The offline library (`loadDownloaded()`) and playlist view (`loadPlaylists()`) do not auto-refresh.
   - *Step 2 Reason*: Omitting `file_path` from the payload violates the contract specified in `PROJECT.md` and `SCOPE.md`.
   - *Conclusion*: `downloader.py` must emit `"track_downloaded"` with payload `{"track_id": track_id, "file_path": file_path}`.

2. **Silent Failure & UI Blindness (Feature 8 & Feature 11)**:
   - *Observation*: `core/downloader.py:110-121` catches all exceptions during download execution and updates `download_queue` status to `'failed'`, but calls no API emit function.
   - *Observation*: `events.js` lacks a handler for `download_failed`.
   - *Step 1 Reason*: Without an emitted event, the JS runtime is unaware of download errors.
   - *Step 2 Reason*: The user sees the context menu toast `"Скачивание начато"`, but receives no failure notification when the download crashes (e.g., HTTP 404, network failure, unsupported format).
   - *Conclusion*: Backend `_download_worker` must emit `download_failed` with `{"track_id": track_id, "error": str(e)}`, and `events.js` must handle `download_failed` by calling `showToast('Ошибка скачивания: ' + (data?.error || 'Неизвестная ошибка'), 'error')`.

3. **Queue Resilience & Database Integrity (Feature 11)**:
   - *Observation*: `core/downloader.py:120` suppresses DB update exceptions via `pass`.
   - *Step 1 Reason*: Silent suppression masks SQLite locking or schema issues, making debugging queue failures impossible.
   - *Step 2 Reason*: On worker failure, if the track row in `tracks` table was previously mutated or had invalid `file_path`, failing to explicitly clean up or check `is_downloaded` leaves corrupted records.
   - *Conclusion*: Failures in queue DB updates must be cleanly logged (`logger.error(...)`). On worker failure, `is_downloaded` in `tracks` table must remain `0` (or be reset to `0` if `file_path` is invalid/absent).

---

## 3. Caveats

1. **Read-Only Scope**: Per instructions, Explorer 3 (gen2) did NOT alter any source files (`core/downloader.py`, `core/api.py`, `ui/web_new/js/events.js`, `ui/web_new/js/contextmenu.js`). All proposed changes are documented below for Implementer consumption.
2. **PyWebview Bridge Availability**: `self._core.api._emit` depends on `self._window` existing in `AppApi`. Guard checks (`if hasattr(self._core, "api") and self._core.api:`) must remain in place for unit testing environments where `AppApi` or `webview.Window` may be mocked.

---

## 4. Conclusion

Features 8 and 11 require targeted modifications in `core/downloader.py` and `ui/web_new/js/events.js`:

1. **Backend Event Correction (`core/downloader.py`)**:
   - Replace event name `"download_complete"` with `"track_downloaded"`.
   - Include `"file_path"` in `track_downloaded` payload: `{"track_id": track_id, "file_path": file_path}`.
   - Emit `"download_failed"` event on worker exception: `{"track_id": track_id, "error": str(e)}`.

2. **Backend Queue Resilience & DB Cleanup (`core/downloader.py`)**:
   - Ensure `download_queue` status is updated to `'failed'` upon error.
   - Explicitly log any exceptions during queue DB updates.
   - Ensure `is_downloaded` remains `0` on failed downloads.

3. **Frontend Event Handling (`ui/web_new/js/events.js`)**:
   - Verify `case 'track_downloaded':` triggers `loadDownloaded()`, `loadPlaylists()`, custom DOM event, and a success toast (`showToast('Трек скачан', 'success')`).
   - Add `case 'download_failed':` to display an error toast notification (`showToast('Ошибка скачивания: ' + (data?.error || 'Неизвестная ошибка'), 'error')`) and dispatch `nedotify:download_failed` DOM event.

---

## 5. Specific Proposed Code Changes

### Proposal 1: `core/downloader.py` (Worker Completion & Error Handling)

**Target File**: `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/core/downloader.py`  
**Lines 103–122**

```python
<<<< BEFORE (lines 103-122)
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
==== AFTER
                if hasattr(self._core, "api") and getattr(self._core, "api", None):
                    if hasattr(self._core.api, "_emit"):
                        self._core.api._emit("library_updated", True)
                        self._core.api._emit("track_downloaded", {"track_id": track_id, "file_path": file_path})
            else:
                raise Exception("Download returned None or file missing.")

        except Exception as e:
            logger.error(f"Download worker failed for track {track_id}: {e}")
            try:
                cursor = self._core.db.conn.cursor()
                self._ensure_queue_table(cursor)
                cursor.execute(
                    "UPDATE download_queue SET status = 'failed' WHERE track_id = ?",
                    (track_id,)
                )
                # Ensure tracks table does not retain false is_downloaded flag
                cursor.execute(
                    "UPDATE tracks SET is_downloaded = 0 WHERE id = ? AND (file_path IS NULL OR is_downloaded = 0)",
                    (track_id,)
                )
                self._core.db.conn.commit()
            except Exception as db_err:
                logger.error(f"Failed to update download queue status to failed for track {track_id}: {db_err}")

            if hasattr(self._core, "api") and getattr(self._core, "api", None):
                if hasattr(self._core.api, "_emit"):
                    self._core.api._emit("download_failed", {"track_id": track_id, "error": str(e)})
>>>>
```

---

### Proposal 2: `ui/web_new/js/events.js` (Event Bridge Handlers)

**Target File**: `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/ui/web_new/js/events.js`  
**Lines 126–131**

```javascript
<<<< BEFORE (lines 126-131)
            case 'track_downloaded':
                loadDownloaded();
                loadPlaylists();
                document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
                break;
==== AFTER
            case 'track_downloaded':
                loadDownloaded();
                loadPlaylists();
                showToast('Трек успешно скачан', 'success');
                document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
                break;

            case 'download_failed':
                showToast('Ошибка скачивания: ' + (data?.error || 'Неизвестная ошибка'), 'error');
                document.dispatchEvent(new CustomEvent('nedotify:download_failed', { detail: data }));
                break;
>>>>
```

---

## 6. Verification Method

### Automated Tests
Run test suite to verify event dispatches and queue integrity:
```bash
python run_tests.py
```
or run pytest directly:
```bash
pytest tests/test_nedotify.py
```

### Manual Inspection & Verification Steps
1. **Successful Download Event Verification**:
   - Trigger track download via context menu in UI.
   - Inspect webview console log for: `Python Event: track_downloaded { track_id: ..., file_path: ... }`.
   - Check that UI displays success toast `"Трек успешно скачан"` and "Offline tracks" list refreshes automatically.
2. **Failed Download Event Verification**:
   - Attempt download on unavailable or broken stream source.
   - Check that `download_queue` status in `aura.db` is set to `'failed'`.
   - Check webview console log for: `Python Event: download_failed { track_id: ..., error: ... }`.
   - Verify UI displays red error toast `"Ошибка скачивания: ..."` and `tracks.is_downloaded` remains `0`.
