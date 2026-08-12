# Search Optimization & Caching Analysis Report (Milestone 3)

## 1. Observation

### Codebase Integration Points & Search Architecture
- **Backend API Bridge (`core/api.py`, lines 306–352)**:
  `search(self, query: str, source: str = "all", result_type: str = None)` is called via pywebview.
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
  `"yandex"` is completely omitted from the `services` mapping dict in `core/api.py`.

- **Frontend Search Handler (`ui/web_new/js/search.js`, lines 180–200 & 28–48)**:
  - Default source is `'youtube'` (`let currentSource = 'youtube'`).
  - Search input debounced by 300ms (`searchDebounce = setTimeout(..., 300)`).
  - Callback `onSearchResults(data)` contains explicit Yandex exclusion:
    ```javascript
    188: // STRICT RULE: Exclude Yandex Music completely!
    189: const filteredTracks = data.tracks.filter(t => (t.source || '').toLowerCase() !== 'yandex');
    190: if (filteredTracks.length > 0) {
    191:     allResults = allResults.concat(filteredTracks);
    192:     renderResults(allResults);
    193: }
    ```
  - Concatenation line `allResults = allResults.concat(filteredTracks)` performs zero deduplication.

- **Frontend Platform UI (`ui/web_new/index.html`, lines 216–230)**:
  Platform dropdown contains only three single-source items: `youtube`, `soundcloud`, `spotify`. No `"all"` ("Все источники") option exists, nor is `yandex` listed.

- **Provider Modules**:
  1. **`services/spotify_service.py`**:
     - Uses iTunes Search API `https://itunes.apple.com/search?term={query}&entity=song&limit={limit}`.
     - Decorated with `@lru_cache(maxsize=256)` on `_cached_spotify_search`.
     - Request HTTP timeout: 3.5s (`_session.get(url, timeout=3.5)`).
     - Asynchronous dispatch via `self._executor = ThreadPoolExecutor(max_workers=3)`.
  2. **`services/youtube_service.py`**:
     - Uses `ytmusicapi` if installed (`HAS_YTMUSIC`), else falls back to `yt-dlp` (`ytsearch{limit}:{query}`).
     - `ytmusicapi` HTTP session timeout: 15 seconds (`kwargs["timeout"] = 15` in `reset_ydl`).
     - `yt_dlp` options: `socket_timeout: 5`, `retries: 1`.
     - Uses `BaseMusicService` cache key `yt_search:{query}:{max_results}`.
  3. **`services/soundcloud_service.py`**:
     - Uses `yt_dlp` (`scsearch{limit}:{query}`) with `socket_timeout: 5`, `retries: 1`.
     - Silent fail bug on DRM exception (lines 122–126):
       ```python
       122: if "drm" in err_str.lower():
       123:     if err_str not in self._drm_log_cache:
       124:         logger.warning(f"SoundCloud DRM skip: {err_str}")
       125:         self._drm_log_cache.add(err_str)
       126:     return
       ```
       Line 126 returns without invoking `callback` or `error_callback`.
  4. **`services/yandex_service.py`**:
     - Initialized in `AppCore` (`self.yandex = YandexService(self.settings)`).
     - Uses `yandex_music.Client.search(query, type_="track")`.
     - No custom timeout set on SDK request.
     - Uses `BaseMusicService` cache key `ya_search:{query}:{max_results}`.
     - Completely bypassed in `core/api.py` and filtered out in `search.js`.
  5. **`services/vk_service.py`**:
     - `search()` returns `callback([])` due to VK anti-bot limitations.

- **Base Service Search Cache (`services/base_service.py` decompiled)**:
  - Shared class-level dictionary `_search_cache = {}`.
  - TTL: `_SEARCH_CACHE_TTL = 300` (5 minutes).
  - No `threading.Lock()` or mutex protection during `get_search_cache` / `set_search_cache`.
  - No size limit (LRU or max item limit) on `_search_cache`.

- **Database Search (`core/database.py`, lines 526–538)**:
  ```python
  526: def search_tracks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
  527:     cursor = self.conn.cursor()
  528:     like_query = f"%{query}%"
  529:     cursor.execute(
  530:         "SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? ORDER BY play_count DESC LIMIT ?",
  531:         (like_query, like_query, like_query, limit)
  532:     )
  ```
  Unindexed `LIKE %query%` SQL execution, run synchronously inside `api.py` `search()` on main thread.

---

## 2. Logic Chain

1. **Premise**: Milestone 3 requires search to query Spotify, YouTube, SoundCloud, and Yandex asynchronously and in parallel, cache recent queries, deduplicate results, and remain non-blocking to the UI.
2. **Finding 1 (Missing Provider)**:
   - `core/api.py` line 330 omits `"yandex"` from `services`.
   - `ui/web_new/js/search.js` line 189 explicitly filters out Yandex results (`t.source !== 'yandex'`).
   - `ui/web_new/index.html` line 217–228 omits Yandex from platform selector.
   - **Conclusion 1**: Yandex Music search is functionally broken/disabled across both backend and frontend despite `YandexService` existing in `services/yandex_service.py`.
3. **Finding 2 (Thread Blocking)**:
   - In `core/api.py` lines 321–326, `self._core.db.search_tracks(query)` is called synchronously on the main thread inside `api.search()`.
   - SQLite table scans via `LIKE %query%` without indexes can block the main pywebview bridge thread during active DB writes (e.g. playback tracking or downloading).
   - **Conclusion 2**: Local DB search creates main thread blocking before remote searches are even dispatched.
4. **Finding 3 (Provider Timeouts & Silent Failures)**:
   - `YouTubeService` sets `ytmusicapi` HTTP timeout to 15 seconds (`kwargs["timeout"] = 15`).
   - Neither `YouTubeService`, `SoundCloudService`, nor `YandexService` wrap their worker execution in a strict per-provider execution timeout (e.g. 3–5 seconds).
   - `SoundCloudService.search` line 126 returns early on DRM errors without calling `callback` or `error_callback`.
   - Frontend `search.js` line 196 sets container innerHTML to `"Ничего не найдено"` if the first returning provider has 0 results while other providers are still running, or hangs indefinitely if a provider fails silently.
   - **Conclusion 3**: Slow or failing providers cause search delay spikes (up to 15s+) or UI freeze in loading state.
5. **Finding 4 (Caching Flaws)**:
   - `BaseMusicService._search_cache` is an unsynchronized static dictionary (`dict.pop` / `dict[]` without a lock across `ThreadPoolExecutor` threads).
   - `_search_cache` lacks LRU eviction or max size limits, leading to memory growth.
   - Spotify uses `@lru_cache` while YouTube/SoundCloud/Yandex use `BaseMusicService._search_cache`, creating fragmented caching behavior. Local search is uncached.
   - **Conclusion 4**: Current search caching lacks thread safety, memory safety, consistency, and persistence.
6. **Finding 5 (Lack of Deduplication & Result Aggregation)**:
   - Frontend `onSearchResults` simply does `allResults = allResults.concat(filteredTracks)` as each provider asynchronously responds.
   - The same song present on YouTube, SoundCloud, Spotify, or Local DB appears 2–4 times in the result list.
   - Re-rendering on each provider response causes UI list jumping.
   - **Conclusion 5**: The UI lacks track deduplication and unified result ranking.

---

## 3. Caveats

- **VK Service**: `VKService.search` currently returns `callback([])` due to VK anti-bot protections. This is expected behavior and should remain non-blocking.
- **iTunes API for Spotify**: `SpotifyService` queries iTunes Search API for Spotify metadata due to Spotify web API token requirements. This metadata search works fast (~3.5s timeout) and should be preserved.
- **yt-dlp Execution Overhead**: Scraping YouTube and SoundCloud via `yt-dlp` without API keys inherently incurs network latency (1–4 seconds). Search caching is vital for responsive UX.

---

## 4. Conclusion & Optimization Recommendations (Milestone 3)

### Core Recommendations:

1. **Restore & Integrate Yandex Music Search**:
   - Add `"yandex": getattr(self._core, "yandex", None)` to `services` dict in `core/api.py`.
   - Remove line 188–189 Yandex filtering in `ui/web_new/js/search.js`.
   - Add Yandex item and an **"All Providers" ("Все источники")** option to the platform selector in `index.html` and default search `currentSource` to `'all'`.

2. **Asynchronous Local DB Search**:
   - Offload `self._core.db.search_tracks(query)` to a thread pool executor alongside remote services in `core/api.py`, eliminating main thread blocking.

3. **Per-Provider Hard Timeouts & Silent Failure Patch**:
   - Implement a per-provider timeout wrapper (3.5 – 5.0 seconds maximum) in backend search dispatcher.
   - Fix `SoundCloudService.search` DRM error branch to always call `error_callback` or `callback([])`.
   - Emit a `search_completed` or provider completion status event so frontend UI reliably hides spinner even if a provider fails or times out.

4. **Thread-Safe & Bounded Search Cache**:
   - Refactor `BaseMusicService._search_cache` to use `threading.Lock()` and an LRU eviction policy with a maximum capacity (e.g. 300 entries).
   - Normalize cache keys (`f"{source}:{query.lower().strip()}:{limit}"`).
   - Add short TTL caching for local DB search results.

5. **Track Deduplication & Unified Ranking**:
   - Implement frontend or backend track deduplication based on normalized key `f"{clean(artist)} - {clean(title)}"`.
   - Merge duplicate tracks from different providers into a single result item, prioritizing higher quality metadata/covers while storing alternative source stream IDs.
   - Sort results by relevance (exact title/artist match, followed by popularity/play count).

6. **Database Indexing**:
   - Add SQLite indexes on `tracks(title)` and `tracks(artist)` in `core/database.py` to accelerate `LIKE` query execution times.

---

## 5. Verification Method

To independently verify these findings and future Milestone 3 fixes:

1. **Verify Yandex Exclusion**:
   - Inspect `core/api.py` line 330 (confirm absence of `"yandex"` key).
   - Inspect `ui/web_new/js/search.js` line 188–189 (confirm `filter(t => t.source !== 'yandex')`).
   - Inspect `ui/web_new/index.html` line 216–230 (confirm absence of `yandex` and `all` platform choices).

2. **Verify Main Thread DB Search**:
   - Inspect `core/api.py` line 321–326 (confirm synchronous `db.search_tracks` call).

3. **Verify SoundCloud DRM Silent Fail**:
   - Inspect `services/soundcloud_service.py` line 122–126 (confirm early `return` without callback execution).

4. **Verify Cache Implementation**:
   - Inspect `services/base_service.py` (confirm unsynchronized `_search_cache` dictionary).

5. **Automated Verification Command**:
   - Run search unit tests:
     `python -m pytest tests/test_nedotify.py -k search`
