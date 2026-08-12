## 2026-08-07T15:31:09Z
You are Worker 1 for Milestone 3: Search Optimization & Caching in AURA Music.

Working Directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m3_1

Mandatory Reading:
1. ORIGINAL_REQUEST.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. PROJECT.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. SCOPE.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m3_gen3/SCOPE.md
4. Explorer 1 Handoff: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m3_1/handoff.md
5. Explorer 2 Handoff: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m3_2/handoff.md
6. Explorer 3 Handoff: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_m3_3/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Assigned Scope & Tasks (Features 12, 13, 14, 15, 16):

1. **Feature 12: Restore & Integrate Yandex Music Search**
   - In `core/api.py`, add `"yandex": getattr(self._core, "yandex", None)` into `services` dict inside `search()` method.
   - In `ui/web_new/js/search.js`, set default `currentSource = 'all'` and remove Yandex exclusion filter line `filter(t => (t.source || '').toLowerCase() !== 'yandex')`.
   - In `ui/web_new/index.html`, add `<div class="platform-option active" data-source="all">` ("Все источники") and `<div class="platform-option" data-source="yandex">` ("Яндекс Музыка") options to the platform dropdown menu.

2. **Feature 13: Asynchronous Non-blocking DB Search & DB Indexing**
   - In `core/api.py`, offload local SQLite DB search (`self._core.db.search_tracks(query)`) off the main pywebview thread into a `ThreadPoolExecutor` worker task.
   - In `core/database.py`, add SQLite indexes `CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)` and `CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)` in `_init_database()`.

3. **Feature 14: Provider Hard Timeouts (4.0s) & Silent Failure Fix**
   - In `core/api.py`, implement a per-provider execution timeout wrapper enforcing a strict 4.0 seconds limit per provider. Emit empty results if a provider times out, log a warning, and do not block remaining provider results or UI.
   - In `services/soundcloud_service.py`, fix lines 122-126 DRM exception handling: if `"drm" in err_str.lower()`, invoke `if callback: callback([])` or `elif error_callback: error_callback(...)` so caller callbacks are never skipped.
   - Emit a `search_completed` event (`{"query": query, "source": source}`) when all requested search providers have finished or timed out.
   - In `ui/web_new/js/events.js` and `ui/web_new/js/search.js`, handle `search_completed` event to clear the loading spinner cleanly without premature "Ничего не найдено" state.

4. **Feature 15: Thread-Safe Bounded LRU Search Cache**
   - In `services/base_service.py` (create or update `services/base_service.py`), refactor `BaseMusicService._search_cache` using `collections.OrderedDict()`, `_cache_lock = threading.Lock()` (or `RLock`), maximum capacity limit of 300 entries (`_MAX_SEARCH_CACHE_SIZE = 300`), and TTL of 300 seconds (`_SEARCH_CACHE_TTL = 300`).
   - `get_search_cache(cls, key)` must acquire `_cache_lock`, check TTL, move key to end on hit (`move_to_end(key)`), and pop if expired.
   - `set_search_cache(cls, key, data)` must acquire `_cache_lock`, set entry, move key to end, and evict least recently used entries (`popitem(last=False)`) when `len(_search_cache) > 300`.

5. **Feature 16: Track Deduplication & UI Result Merging**
   - In `ui/web_new/js/search.js`, implement track deduplication using a normalized composite key based on `f"{clean(artist)} - {clean(title)}"`.
   - Perform string normalization: lowercasing, Cyrillic NFC normalization, stripping bracketed tags like `(Official Video)` or `[HD]`, extra whitespace, and punctuation.
   - Merge duplicate tracks from multiple providers, aggregating stream sources / badges and preventing UI result list jumping/jittering.

6. **Test Suite Verification**
   - Run existing test suite: `python run_tests.py`.
   - Add new concurrency and unit tests in `tests/test_search_concurrency.py` verifying search cache lock thread-safety, 300-entry LRU capacity eviction, provider 4.0s timeout handling, Yandex integration, and track deduplication.
   - Ensure all tests pass.

Write your implementation report to:
`c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m3_1/handoff.md`
