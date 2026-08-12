# Investigation Handoff Report — Feature 7 (Dedicated Download Directory) & Feature 9 (Database Update Integrity)

**Agent**: Explorer 2 (Replacement Generation 2)  
**Milestone**: Milestone 2 — Track Downloading & DB Integrity  
**Working Directory**: `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m2_2_gen2`  
**Target Files Analyzed**:
- `utils/cache_manager.py`
- `core/downloader.py`
- `core/database.py`

---

## 1. Observation

### 1.1 Feature 7: Dedicated Download Directory & Cache Eviction Isolation

Direct observations in `utils/cache_manager.py` and `core/downloader.py`:

1. **Missing `_downloads_dir` in `CacheManager.__init__`** (`utils/cache_manager.py`, lines 19-38):
   - `CacheManager` initializes `self._base_dir` (`~/.nedotify`), `self._covers_dir`, `self._streams_dir` (`~/.nedotify/streams`), and `self._temp_dir` (`~/.nedotify/temp`).
   - `self._downloads_dir` is **not initialized** in `__init__`, nor created in the `os.makedirs` loop (lines 29-30).
   - `CacheManager` exposes properties `@property def cache_dir`, `covers_dir`, `streams_dir`, `temp_dir` (lines 39-54), but **has no `downloads_dir` property**.

2. **`DownloadManager` creates directory variable but `CacheManager` ignores it** (`core/downloader.py`, lines 74-75, 86):
   - Line 74: `download_dir = os.path.join(self._core.cache.cache_dir, "downloads")`
   - Line 75: `os.makedirs(download_dir, exist_ok=True)`
   - Line 86: `future = self._core.cache.download_audio_stream(source, source_id, url)`
   - *Observation*: `downloader.py` computes `download_dir`, but does not pass it to `download_audio_stream`.

3. **`CacheManager.download_audio_stream` hardcodes output destination to `self._streams_dir`** (`utils/cache_manager.py`, lines 139, 154):
   - Line 139: `out_template = os.path.join(self._streams_dir, f"{download_id}.%(ext)s")`
   - Line 154: `final_path = os.path.join(self._streams_dir, f"{download_id}.{ext}")`
   - *Observation*: Downloaded track files intended for permanent offline storage are saved directly into the temporary stream cache folder (`streams_dir`).

4. **Flawed Cache Size Calculation & Eviction Routine in `enforce_cache_limit`** (`utils/cache_manager.py`, lines 56-66, 202-229):
   - Lines 56-66 (`get_cache_size`):
     ```python
     def get_cache_size(self) -> int:
         """Get total cache size in bytes."""
         total = 0
         for dirpath, dirnames, filenames in os.walk(self._base_dir):
             for f in filenames:
                 fp = os.path.join(dirpath, f)
                 try:
                     total += os.path.getsize(fp)
                 except OSError:
                     pass
         return total
     ```
     *Observation*: `get_cache_size()` recursively traverses `self._base_dir` (`~/.nedotify`), counting ALL subdirectories (including `downloads` if inside `_base_dir` and `covers`).
   - Lines 202-229 (`enforce_cache_limit`):
     ```python
     def enforce_cache_limit(self, max_mb: int = 500):
         current_mb = self.get_cache_size_mb()
         if current_mb <= max_mb:
             return

         files = []
         for dirpath, _, filenames in os.walk(self._streams_dir):
             for f in filenames:
                 fp = os.path.join(dirpath, f)
                 ...
         files.sort(key=lambda x: x[1])  # Oldest first

         freed = 0
         target_free = (current_mb - max_mb) * 1024 * 1024
         for fp, _, size in files:
             if freed >= target_free:
                 break
             try:
                 os.remove(fp)
                 freed += size
             except OSError:
                 pass
     ```
     *Observation*:
     a) Because downloaded files currently land in `self._streams_dir`, `enforce_cache_limit` will **directly delete permanently downloaded tracks** when total size exceeds 500 MB.
     b) Because `get_cache_size()` includes files outside `streams_dir` (e.g. downloaded tracks), large downloaded files cause `current_mb > max_mb` even when `streams_dir` is small, leading to aggressive premature deletion of stream files.

---

### 1.2 Feature 9: Database Update Integrity

Direct observations in `core/downloader.py` and `core/database.py`:

1. **Source Overwrite in `_download_worker`** (`core/downloader.py`, line 94):
   ```python
   cursor.execute(
       "UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?",
       (file_path, track_id)
   )
   ```
   *Observation*: Upon download completion, `DownloadManager` explicitly sets `source = 'local'`.

2. **Existing Safe Method in `DatabaseManager`** (`core/database.py`, lines 495-498):
   ```python
   def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
       cursor = self.conn.cursor()
       cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
       self.conn.commit()
   ```
   *Observation*: `DatabaseManager` ALREADY has `mark_track_downloaded`, which updates `is_downloaded = 1` and `file_path = ?` while preserving `source`. `DownloadManager` bypasses this method and runs an inline SQL query that corrupts `source`.

3. **Impact of Overwriting `source = 'local'` in `core/database.py`**:
   - `get_track_by_source_id(self, source: str, source_id: str)` (lines 422-426):
     ```python
     cursor.execute("SELECT * FROM tracks WHERE source = ? AND source_id = ?", (source, source_id))
     ```
     When `source` is changed to `'local'`, querying by `("youtube", source_id)` returns `None`.
   - `add_track(...)` (lines 337-353):
     ```python
     if source != "local" and source_id:
         cursor.execute(
             "SELECT id, cover_url, file_path FROM tracks WHERE source = ? AND source_id = ?",
             (source, source_id),
         )
         row = cursor.fetchone()
         if row:
             return t_id
     ```
     Because the existing track row was mutated to `source = 'local'`, subsequent searches or re-adds of the same track fail to match the existing row and create **duplicate track records** in `tracks`.

---

## 2. Logic Chain

### 2.1 Feature 7 Isolation Logic Chain
1. **Observation**: `DownloadManager._download_worker` calls `CacheManager.download_audio_stream(source, source_id, url)`.
2. **Observation**: `CacheManager.download_audio_stream` hardcodes file destination to `self._streams_dir`.
3. **Logic**: Downloaded files land in `streams_dir` instead of `.cache/downloads/` (or `~/.nedotify/downloads/`).
4. **Observation**: `CacheManager.enforce_cache_limit` deletes files in `self._streams_dir` whenever `get_cache_size_mb() > 500`.
5. **Logic**: Downloaded tracks in `streams_dir` are treated as temporary cache files and erased by background eviction routines, violating the requirement that downloaded tracks persist offline.
6. **Observation**: `get_cache_size()` walks `self._base_dir` recursively.
7. **Logic**: Even if downloaded files were moved to `self._downloads_dir`, if `get_cache_size()` counts `downloads_dir`, accumulated downloads will inflate `current_mb`, causing `enforce_cache_limit` to purge stream cache continuously.
8. **Conclusion for Feature 7**:
   - `CacheManager` must establish a dedicated `self._downloads_dir` (`.cache/downloads/` or `~/.nedotify/downloads`).
   - `download_audio_stream` (or a dedicated `download_track` method) must accept a `target_dir` parameter or default to `self._downloads_dir` for permanent downloads.
   - `enforce_cache_limit` and `get_cache_size` must be scoped **exclusively** to `self._streams_dir`, ensuring `downloads_dir` is completely isolated and never inspected or purged by cache eviction routines.

### 2.2 Feature 9 DB Integrity Logic Chain
1. **Observation**: `core/downloader.py` line 94 runs `UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?`.
2. **Observation**: `core/database.py` relies on `source` and `source_id` to uniquely identify cloud provider tracks (`youtube`, `soundcloud`, `spotify`, `yandex`).
3. **Logic**: Overwriting `source` with `'local'` destroys the track's original provider metadata.
4. **Logic**: When a user searches for the track again, `add_track()` looks up `(source, source_id)`. Since `source` was changed to `'local'`, lookup fails and a duplicate row is inserted into `tracks`.
5. **Logic**: In addition, proxy stream re-resolution and UI provider icons break when `source` is changed to `'local'`.
6. **Observation**: `core/database.py` lines 495-498 provides `mark_track_downloaded(track_id, file_path)`, which updates `is_downloaded = 1` and `file_path = ?` while preserving `source`.
7. **Conclusion for Feature 9**:
   - `core/downloader.py` line 94 must be changed to update ONLY `is_downloaded = 1` and `file_path = ?` (or invoke `self._core.db.mark_track_downloaded(track_id, file_path)`).
   - The original `source` provider value (`youtube`, `soundcloud`, `spotify`, `yandex`) must remain unchanged in SQLite.

---

## 3. Caveats

- **Existing DB Migration**: If existing databases already have tracks where `source` was mutated to `'local'`, those records may have lost their original provider string. A lightweight database repair or check is recommended if necessary, but for all future downloads, preserving `source` prevents corruption.
- **Windows Path Handling**: Download file paths stored in `file_path` must use clean, normalized path separators (e.g. `os.path.abspath` / `os.path.normpath`) so SQLite queries and filesystem access work reliably across Windows environments.

---

## 4. Conclusion

Both Feature 7 and Feature 9 require precise, focused fixes:

1. **Feature 7 (Dedicated Download Directory)**:
   - In `utils/cache_manager.py`:
     - Add `self._downloads_dir = os.path.join(self._base_dir, "downloads")` to `__init__` and ensure directory creation.
     - Add `@property def downloads_dir(self) -> str:` property.
     - Update `download_audio_stream` to accept `target_dir: Optional[str] = None` (defaulting to `self._downloads_dir` when downloading permanent tracks, or `self._streams_dir` when caching streams).
     - Refactor `get_cache_size` / `get_stream_cache_size` to calculate size of `self._streams_dir` ONLY.
     - Ensure `enforce_cache_limit` calculates size and deletes files ONLY within `self._streams_dir`.

2. **Feature 9 (Database Update Integrity)**:
   - In `core/downloader.py`:
     - Replace line 94 SQL `UPDATE tracks SET is_downloaded = 1, file_path = ?, source = 'local' WHERE id = ?` with `self._core.db.mark_track_downloaded(track_id, file_path)` or `UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?`.
     - Ensure `is_downloaded = 1` and `file_path` are set, while `source` remains intact (`youtube`, `soundcloud`, `spotify`, `yandex`).

---

## 5. Recommended Code Changes

### Recommended Change 1: `utils/cache_manager.py` (Feature 7)

```python
# In CacheManager.__init__ (around line 27):
self._downloads_dir = os.path.join(self._base_dir, "downloads")

# Ensure directories exist (around line 29):
for d in [self._covers_dir, self._streams_dir, self._temp_dir, self._downloads_dir]:
    os.makedirs(d, exist_ok=True)

# Add property (around line 55):
@property
def downloads_dir(self) -> str:
    return self._downloads_dir

# Update get_cache_size to scope to streams_dir (around line 56):
def get_cache_size(self) -> int:
    """Get total stream cache size in bytes (excludes permanent downloads)."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(self._streams_dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total

# Update download_audio_stream signature and out_template (around line 111):
def download_audio_stream(self, source: str, source_id: str, url: str = None, *, sc_url: str = None, target_dir: str = None):
    ...
    dest_dir = target_dir or self._downloads_dir
    out_template = os.path.join(dest_dir, f"{download_id}.%(ext)s")
    ...
```

### Recommended Change 2: `core/downloader.py` (Feature 9 & Feature 7)

```python
# In DownloadManager._download_worker (around lines 74-96):
download_dir = self._core.cache.downloads_dir
os.makedirs(download_dir, exist_ok=True)

...

future = self._core.cache.download_audio_stream(source, source_id, url, target_dir=download_dir)
file_path = future.result() if future else None

if file_path and os.path.exists(file_path):
    logger.info(f"Download complete: {file_path}")
    # Fix Feature 9: Use DB helper or execute UPDATE without changing 'source'
    self._core.db.mark_track_downloaded(track_id, file_path)
    
    cursor = self._core.db.conn.cursor()
    self._ensure_queue_table(cursor)
    cursor.execute(
        "UPDATE download_queue SET status = 'completed' WHERE track_id = ?",
        (track_id,)
    )
    self._core.db.conn.commit()
```

---

## 6. Verification Method

1. **Unit & Integration Verification Command**:
   Run automated test suite:
   ```bash
   python run_tests.py
   ```
   Or pytest directly:
   ```bash
   pytest tests/
   ```

2. **Feature 7 Verification**:
   - Inspect `.cache/downloads/` (or `~/.nedotify/downloads/`) after running a track download. Confirm the downloaded audio file is saved in `downloads/`, NOT `streams/`.
   - Call `CacheManager.enforce_cache_limit(max_mb=1)` with populated `downloads/` directory. Verify files in `downloads/` remain untouched while `streams/` directory files are cleaned.

3. **Feature 9 Verification**:
   - Queue download for a YouTube track with `source = 'youtube'` and `source_id = 'test_id'`.
   - After completion, query SQLite database:
     ```sql
     SELECT id, title, source, source_id, is_downloaded, file_path FROM tracks WHERE id = <track_id>;
     ```
   - Verify `is_downloaded == 1`, `file_path` is populated, and `source` **remains `'youtube'`** (NOT `'local'`).
   - Query track by `get_track_by_source_id('youtube', 'test_id')` to confirm non-null result and no duplicate rows created.
