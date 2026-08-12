# Search Optimization & Caching Integration & Risk Analysis Report (Milestone 3 — Features 12-16)

## 1. Observation

### Codebase & Test Harness Survey

1. **Test Harness Architecture & Limitations (`run_tests.py` & `tests/test_nedotify.py`)**:
   - `run_tests.py` executes 8 pytest files: `test_recommendation.py`, `test_lastfm_taste_profile.py`, `test_m3_recommendation.py`, `test_new_recommendations.py`, `test_event_delivery_contract.py`, `test_personalization_p3.py`, `test_fix4_db_path.py`, `test_nedotify.py`.
   - `tests/test_nedotify.py` (lines 55–57) globally monkey-patches standard concurrency classes before any services are imported:
     ```python
     55: import concurrent.futures
     56: concurrent.futures.ThreadPoolExecutor = SynchronousExecutor
     57: threading.Thread = SynchronousThread
     ```
   - `SynchronousExecutor` (lines 29–43) immediately executes submitted tasks inline on the caller thread.
   - `test_f3_cross_search_multi_source` (lines 1069–1081):
     ```python
     1069: def test_f3_cross_search_multi_source(self):
     1070:     emitted = []
     1071:     self.api._emit = lambda event, data: emitted.append((event, data))
     1072:     self.api.search("lofi", source="all")
     1073:     sources = [d['source'] for ev, d in emitted if ev == 'search_results']
     1074:     self.assertIn('local', sources)
     1075:     self.assertIn('youtube', sources)
     1076:     self.assertIn('soundcloud', sources)
     1077:     self.assertIn('vk', sources)
     ```
     - **Verbatim Observations**:
       1. `yandex` source is completely absent from test assertions.
       2. No assertions exist for provider 4.0s execution timeouts.
       3. No assertions exist for `search_completed` completion events.
       4. No assertions exist for multi-threaded cache lock safety or LRU capacity eviction.
       5. Because of `SynchronousExecutor`, actual multi-threaded execution, race conditions, thread starvation, and timeout logic cannot be exercised by existing unit tests.

2. **Base Music Service Cache Implementation (`services/base_service.pyc`)**:
   - Bytecode inspection of `BaseMusicService`:
     - Class attributes: `_search_cache = {}`, `_SEARCH_CACHE_TTL = 300` (5 minutes).
     - `get_search_cache(cls, key)` disassembly:
       ```
       LOAD_FAST_BORROW 0 (cls) -> LOAD_ATTR (_search_cache) -> LOAD_ATTR (get)
       ...
       # TTL check: time.time() - entry['ts'] > _SEARCH_CACHE_TTL
       # Expiration branch: cls._search_cache.pop(key, None) -> return None
       # Valid branch: return entry['data']
       ```
     - `set_search_cache(cls, key, data)` disassembly:
       ```
       STORE_SUBSCR into cls._search_cache[key] = {'data': data, 'ts': time.time()}
       ```
     - **Verbatim Observations**:
       1. `_search_cache` is a static Python dictionary shared across all subclasses (`YouTubeService`, `SoundCloudService`, `YandexService`, `SpotifyService`).
       2. No `threading.Lock()` or mutex synchronization exists during cache reads, writes, or expiration pops.
       3. No capacity limit or LRU eviction mechanism exists for `_search_cache` (unlike `_stream_cache` which has `_MAX_CACHE_SIZE = 2000`).

3. **Backend Search Dispatcher (`core/api.py`, lines 306–352)**:
   - `search(self, query: str, source: str = "all", result_type: str = None)`:
     ```python
     321: if source in ("all", "local"):
     322:     try:
     323:         local_tracks = self._core.db.search_tracks(query)
     324:         emit_results(local_tracks, "local")
     325:     except Exception as exc: ...
     ...
     330: services = {
     331:     "youtube": getattr(self._core, "youtube", None),
     332:     "soundcloud": getattr(self._core, "soundcloud", None),
     333:     "spotify": getattr(self._core, "spotify", None),
     334:     "vk": getattr(self._core, "vk", None),
     335: }
     ```
     - **Verbatim Observations**:
       1. Line 323 executes `self._core.db.search_tracks(query)` synchronously on the main pywebview bridge thread.
       2. Line 330 omits `"yandex"` from `services` mapping.
       3. `service.search(...)` is dispatched asynchronously per provider, but `api.search()` has no `ThreadPoolExecutor` futures tracking, no 4.0s timeout enforcement wrapper, and emits no `search_completed` event.

4. **SoundCloud DRM Error Handling (`services/soundcloud_service.py`, lines 120–135)**:
   ```python
   120: except Exception as e:
   121:     err_str = str(e)
   122:     if "drm" in err_str.lower():
   123:         if err_str not in self._drm_log_cache:
   124:             logger.warning(f"SoundCloud DRM skip: {err_str}")
   125:             self._drm_log_cache.add(err_str)
   126:         return
   ```
   - **Verbatim Observation**: Line 126 returns immediately without calling `callback` or `error_callback`, creating a silent failure branch.

5. **Frontend Search Handler & Deduplication (`ui/web_new/js/search.js`, lines 180–200)**:
   ```javascript
   180: export function onSearchResults(data) {
   ...
   188:     // STRICT RULE: Exclude Yandex Music completely!
   189:     const filteredTracks = data.tracks.filter(t => (t.source || '').toLowerCase() !== 'yandex');
   190:     if (filteredTracks.length > 0) {
   191:         allResults = allResults.concat(filteredTracks);
   192:         renderResults(allResults);
   193:     }
   ...
   ```
   - **Verbatim Observations**:
     1. Line 189 explicitly filters out Yandex Music tracks.
     2. Line 191 performs direct array concatenation `allResults = allResults.concat(filteredTracks)` without track deduplication.
     3. Line 197 sets UI container innerHTML to `"Ничего не найдено"` if an empty result arrives while other providers are still working.

---

## 2. Logic Chain

1. **Test Harness Risk Logic**:
   - Because `test_nedotify.py` monkey-patches `ThreadPoolExecutor` with `SynchronousExecutor`, all tests run single-threaded inline.
   - Consequently, adding `threading.Lock()` or timeout logic in `BaseMusicService` or `api.py` will appear to pass in `test_nedotify.py` even if severe concurrency bugs (such as deadlocks, race conditions, or hanging threads) are present.
   - **Conclusion**: A dedicated asynchronous integration test file (e.g. `tests/test_search_concurrency.py`) MUST be created to test multi-threaded search dispatching, lock contention, LRU eviction, and provider timeouts without synchronous mocking.

2. **Thread Safety & Lock Contention Risk Logic**:
   - Currently, multiple provider threads (YouTube, SoundCloud, Yandex, Spotify) access `BaseMusicService._search_cache` concurrently without synchronization.
   - Adding a class-level `threading.Lock()` to `BaseMusicService` protects dict integrity, but introduces critical deadlock and blocking risks:
     - If a worker thread holds `_cache_lock` while executing I/O calls (`yt_dlp` search, iTunes network GET) or calling provider callbacks (`callback(tracks)`), all other provider search threads block waiting for the lock.
     - This turns parallel 4-provider search into sequential search, causing execution times to stack up (0.5s + 1.5s + 2.0s + 3.0s = 7.0s), guaranteeing 4.0s timeout breaches.
     - If a service method holding `_cache_lock` calls another method that attempts to acquire `_cache_lock` (non-reentrant `threading.Lock`), a deadlock will freeze the worker thread.
   - **Conclusion**: Lock scope must strictly cover ONLY dictionary reads/writes/pops (`get_search_cache` and `set_search_cache`), using `threading.RLock()` or short context managers (`with self._cache_lock:`), NEVER enclosing network I/O or callback execution.

3. **LRU Eviction & Caching Edge Cases Logic**:
   - Replacing unbounded `_search_cache` with a bounded LRU cache (capacity limit e.g. 300) introduces four edge cases:
     1. *LRU Read Update*: In `collections.OrderedDict`, accessing an entry via `get(key)` does not automatically update its recency position unless `cache.move_to_end(key)` is explicitly called.
     2. *TTL Expiration during Lookup*: If a key exists but `time.time() - entry['ts'] > TTL`, `get_search_cache` must acquire the lock, pop the expired key, release the lock, and return `None`.
     3. *Capacity Overflow*: Eviction (`cache.popitem(last=False)`) must only trigger when inserting a *new* key while `len(cache) >= max_capacity`. Updating an existing key must not trigger eviction.
     4. *Query Key Normalization & Mutability*: Queries like `"Lofi "` and `"lofi"` must map to normalized cache keys (`f"{source}:{query.strip().lower()}:{limit}"`). Returned track objects must be deep-copied or immutable to prevent frontend in-place modifications (e.g., `is_downloaded` or `is_favorite` flags) from polluting cached data across queries.

4. **Track Deduplication & Normalization Edge Cases Logic**:
   - Merging duplicate tracks across Spotify, YouTube, SoundCloud, Yandex, and Local DB requires a normalized composite key (`clean(artist) + " - " + clean(title)`).
   - Edge Cases:
     1. *Missing Artist / Title*: YouTube or SoundCloud tracks frequently lack structured `artist` fields (e.g., `artist: ""`, `title: "Queen - Bohemian Rhapsody (Official Video)"`). If `artist` is empty, deduplication must parse `"Artist - Title"` from `title`.
     2. *Unicode & Cyrillic Normalization*: Cyrillic titles (e.g. `"Скриптонит - Цепь"`) must undergo Unicode normalization (NFC form) and case-folding. Special punctuation (`«...»`, `"..."`, `"-"`, `"/"`), bracketed tags (`(Official Video)`, `[HD]`, `(Remastered 2011)`), and trailing whitespace must be sanitized before generating the deduplication hash.
     3. *Metadata & Source Merging*: When duplicates match, metadata from high-quality sources (Spotify/iTunes with structured album art and track metadata) must be retained as primary display data, while alternative stream sources (`youtube`, `soundcloud`, `yandex`) are attached to an internal `sources` map for playback resolution.
     4. *Incremental Stream Jittering*: As provider responses arrive asynchronously at different times, deduplication must re-evaluate over the accumulated result set for the current `currentSearchQuery`, replacing existing UI entries cleanly without layout shifting.

5. **Provider Hard Timeout (4.0s) & Future Management Risk Logic**:
   - In Python `concurrent.futures.ThreadPoolExecutor`, calling `future.cancel()` on an already running thread returns `False` and cannot interrupt underlying C-extension or socket calls.
   - If a provider (e.g. `yt_dlp` or `ytmusicapi`) hangs in socket read without internal timeouts, the worker thread remains alive indefinitely.
   - If user performs 5 searches in succession, hanging threads will exhaust the pool (`max_workers=5`), causing all subsequent search requests to hang in queue.
   - SoundCloud DRM error returns early without calling callbacks, causing the dispatcher to wait forever for SoundCloud unless a hard timeout catches it.
   - **Conclusion**:
     1. Socket-level timeouts in provider HTTP clients / `yt-dlp` options MUST be capped at <= 3.5s (`socket_timeout: 3.5`).
     2. Dispatcher in `core/api.py` must use `concurrent.futures.wait(futures, timeout=4.0)`.
     3. SoundCloud DRM skip must call `callback([])` or `error_callback(...)`.
     4. Upon timeout or completion, `api.py` must emit `search_completed` event with query metadata, and late-arriving futures must be flagged as stale so their callbacks do not push results to subsequent search queries.

---

## 3. Caveats

- **Free-Threaded / GIL Behavior**: CPython GIL protects simple dict operations from crashing the interpreter, but logical race conditions (e.g. stale cache overwrites or double-pops) still occur under concurrent threads.
- **VK Service**: `VKService.search` currently returns `callback([])` due to VK anti-bot protections. It must remain included in `search_completed` tracking.
- **iTunes Metadata vs Direct Stream IDs**: Spotify tracks use iTunes Search API for fast metadata (~3.5s timeout). Deduplication between iTunes metadata and YouTube/SoundCloud streams requires matching on clean title/artist text.

---

## 4. Conclusion & Actionable Recommendations

### Recommendation Matrix for Features 12–16

| Feature | Primary Risk / Edge Case | Required Implementation Strategy |
|---------|--------------------------|----------------------------------|
| **F12: Yandex Integration** | Complete omission in `api.py` & explicit JS filter line 189 | Restore `"yandex"` in `core/api.py` `services` dict; remove JS line 189 filter; add Yandex & "All Providers" ("Все источники") to `index.html`. |
| **F13: Non-blocking DB Search** | Synchronous `db.search_tracks` on main pywebview bridge thread | Offload `db.search_tracks` to `ThreadPoolExecutor` worker alongside remote services; add SQLite indexes on `tracks(title)` and `tracks(artist)`. |
| **F14: 4.0s Hard Timeouts & Silent Failure Patch** | Hanging provider threads; silent return on SoundCloud DRM error | Wrap provider futures in `concurrent.futures.wait(futures, timeout=4.0)`; emit `search_completed` event; fix SoundCloud DRM branch to invoke `callback([])`. |
| **F15: Thread-Safe Bounded LRU Cache** | Race conditions on static dict; LRU hit ordering; mutable track pollution | Refactor `BaseMusicService._search_cache` using `threading.RLock()` + `collections.OrderedDict(maxsize=300)`; call `move_to_end(key)` on hit; normalize keys; deep-copy tracks. |
| **F16: Deduplication & UI Result Merging** | Cyrillic/Unicode NFC mismatches; missing artist strings; UI list jittering | Implement normalized deduplication key `f"{clean(artist)} - {clean(title)}"`; parse artist from title if empty; merge provider sources; re-render cleanly on `search_completed`. |
| **Test Suite Alignment** | `test_nedotify.py` monkey-patches `ThreadPoolExecutor` to synchronous | Add `tests/test_search_concurrency.py` using real `ThreadPoolExecutor` to test 4.0s timeouts, cache lock safety under 100 concurrent threads, LRU eviction, and Cyrillic deduplication. |

---

## 5. Verification Method

### Automated Unit & Concurrency Test Verification Command

Run pytest on the test suite:
```bash
python run_tests.py
```
And execute dedicated search concurrency tests:
```bash
python -m pytest tests/test_search_concurrency.py -v
```

### Manual Inspection & Verification Points

1. **Verify Test Harness Isolation**:
   - Inspect `tests/test_nedotify.py` lines 55–57 to confirm `ThreadPoolExecutor` monkey-patching scope.
2. **Verify Cache Lock Scope & LRU Behavior**:
   - Inspect `services/base_service.py` to confirm `threading.RLock()` protection around `OrderedDict` without wrapping I/O calls.
3. **Verify Timeout & Dispatcher Logic**:
   - Inspect `core/api.py` `search()` method to verify `concurrent.futures.wait(..., timeout=4.0)` and emission of `search_completed`.
4. **Verify SoundCloud DRM Fix**:
   - Inspect `services/soundcloud_service.py` line 126 to verify `callback([])` is invoked on DRM error.
5. **Verify Deduplication & Yandex Integration**:
   - Inspect `ui/web_new/js/search.js` to verify removal of line 189 Yandex exclusion filter and inclusion of Cyrillic NFC normalized track deduplication.
