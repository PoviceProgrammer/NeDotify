# Handoff Report: Milestone 3 — Features 14 & 15 Investigation

## 1. Observation

### Feature 14: Search Execution Timeouts & Error Handling
1. **Backend Search Dispatcher (`core/api.py`, lines 306–352)**:
   ```python
   306: def search(self, query: str, source: str = "all", result_type: str = None):
   307:     """Search without blocking the UI bridge or spawning duplicate worker pools."""
   ...
   337: for service_name in requested:
   338:     service = services.get(service_name)
   339:     if not service:
   340:         continue
   341:     try:
   342:         service.search(
   343:             query,
   344:             callback=lambda tracks, name=service_name: emit_results(tracks, name),
   345:             error_callback=lambda error, name=service_name: logger.info(
   346:                 "%s search failed: %s", name, error
   347:             ),
   348:         )
   349:     except Exception as exc:
   350:         logger.error("%s search could not start: %s", service_name, exc)
   351: 
   352: return {"query": query, "tracks": []}
   ```
   - **No Hard Timeout**: `service.search(...)` submits a task `_search()` to the service's internal `ThreadPoolExecutor` and returns `None` immediately. `api.py` does not track futures or enforce a 4.0s timeout per provider. If a provider's underlying HTTP network call (e.g. `ytmusicapi` 15s timeout or `yt-dlp` scraping) hangs, the search request remains incomplete indefinitely or takes over 15 seconds.
   - **No `search_completed` Event**: `api.py` never tracks when all requested search providers have finished. No `search_completed` event is emitted to signal completion to the frontend pywebview layer.

2. **SoundCloud DRM Error Handling Branch (`services/soundcloud_service.py`, lines 120–135)**:
   ```python
   120: except Exception as e:
   121:     err_str = str(e)
   122:     if "drm" in err_str.lower():
   123:         if err_str not in self._drm_log_cache:
   124:             logger.warning(f"SoundCloud DRM skip: {err_str}")
   125:             self._drm_log_cache.add(err_str)
   126:         return
   127:     logger.error(f"SoundCloud search error: {e}")
   ```
   - Line 126 performs a direct `return` without calling `callback` or `error_callback`. As a result, when a DRM error occurs in `SoundCloudService.search()`, neither callback is invoked, leaving `emit_results` uncalled for SoundCloud and preventing provider completion tracking.

3. **Frontend Event Handling (`ui/web_new/js/events.js`, lines 31–34 & `ui/web_new/js/search.js`, lines 180–200)**:
   - `events.js` handles `search_results` by calling `onSearchResults(data)` in `search.js`.
   - `search.js` line 196 clears the loading spinner and inserts `<div class="empty-state">Ничего не найдено</div>` as soon as any single provider returns 0 tracks while `allResults.length === 0`, even if other providers are still processing.
   - There is no handler for a `search_completed` event.

### Feature 15: Thread-Safe LRU Search Cache
1. **Existing Cache Implementation (`services/base_service.pyc` / `services/base_service.py`)**:
   Decompiled structure of `BaseMusicService`:
   ```python
   class BaseMusicService:
       _stream_cache: Dict[str, Any] = {}
       _MAX_CACHE_SIZE = 100
       _search_cache: Dict[str, Dict[str, Any]] = {}
       _SEARCH_CACHE_TTL = 300  # 5 minutes
       
       @classmethod
       def get_search_cache(cls, key: str) -> Optional[Any]:
           entry = cls._search_cache.get(key)
           if entry is None:
               return None
           if time.time() - entry['ts'] > cls._SEARCH_CACHE_TTL:
               cls._search_cache.pop(key, None)
               return None
           return entry['data']

       @classmethod
       def set_search_cache(cls, key: str, data: Any) -> None:
           cls._search_cache[key] = {
               'data': data,
               'ts': time.time()
           }
   ```
   - **Unsynchronized Dictionary**: `_search_cache` is a standard static `dict`. `YouTubeService`, `SoundCloudService`, and `YandexService` run in separate threads of their respective `ThreadPoolExecutor` instances and concurrently invoke `get_search_cache` and `set_search_cache` without any mutex protection (`threading.Lock()`). Concurrent dictionary mutations can cause race conditions (`RuntimeError: dictionary changed size during iteration`) or cache corruption.
   - **No LRU Eviction or Capacity Limit**: `_search_cache` has no upper bound (`_MAX_SEARCH_CACHE_SIZE`). Search entries remain in memory indefinitely until explicitly retrieved after TTL expiration. If a query is never searched again, it leaks memory permanently.

---

## 2. Logic Chain

### Feature 14 (Search Timeouts & Error Handling):
1. **Observation 1**: `api.py` `search()` dispatches requests to `youtube`, `soundcloud`, `spotify`, and `yandex` without tracking futures or enforcing a hard timeout.
2. **Observation 2**: Heavy scrapers (yt-dlp, ytmusicapi) can take 15+ seconds or freeze on network drops.
3. **Logic 1**: Wrapping each provider's execution in a coordinator wrapper with `threading.Event.wait(timeout=4.0)` ensures that every provider search is strictly bounded to 4.0 seconds. If `wait(4.0)` returns `False`, the dispatcher logs a timeout warning, emits an empty result for that provider, and proceeds without blocking UI or other providers.
4. **Observation 3**: In `services/soundcloud_service.py` line 126, DRM errors log a warning and return early without executing `callback` or `error_callback`.
5. **Logic 2**: Changing line 126 to invoke `if callback: callback([])` (or `if error_callback: error_callback(...)`) guarantees that `SoundCloudService` always signals completion, allowing the search dispatcher's provider counter to resolve cleanly.
6. **Observation 4**: The frontend UI needs to know when all requested search providers have finished or timed out.
7. **Logic 3**: Maintaining a count/set of pending providers in `api.py` and emitting `self._emit("search_completed", {"query": query, "source": source})` when all providers finish (or hit 4.0s timeout) provides a clear signal for `events.js` and `search.js` to hide loading spinners and display final results.

### Feature 15 (Thread-Safe LRU Search Cache):
1. **Observation 1**: `BaseMusicService._search_cache` is shared across services and accessed concurrently from multiple worker threads without locking.
2. **Logic 1**: Adding a class-level `_search_cache_lock = threading.Lock()` and acquiring it inside `get_search_cache` and `set_search_cache` guarantees thread safety across all provider workers.
3. **Observation 2**: `_search_cache` currently grows unbounded without an LRU eviction policy or capacity limit.
4. **Logic 2**: Refactoring `_search_cache` to use `collections.OrderedDict` allows O(1) LRU management. On cache hit (`get_search_cache`), `_search_cache.move_to_end(key)` marks the key as recently used. On insert (`set_search_cache`), if `len(_search_cache) > 300`, calling `_search_cache.popitem(last=False)` evicts the least recently used entry, maintaining a strict 300-entry capacity bound.

---

## 3. Caveats

1. **Python Thread Non-Interruptibility**: When a provider search times out at 4.0s in `api.py`, the underlying worker thread inside the service's `ThreadPoolExecutor` cannot be forcibly killed due to Python GIL limitations. It will finish its background network call silently, but any late callback will be ignored because the dispatcher has already marked the provider done.
2. **Missing `base_service.py` Source File**: The repository currently contains `services/base_service.pyc` but lacks `services/base_service.py`. Implementers must write out `services/base_service.py` completely based on the decompiled structure documented in this report.
3. **Sub-Type Filtering**: `search_completed` should carry `{"query": query, "source": source}` so frontend `search.js` can ignore stale search completion events if the user typed a new query.

---

## 4. Conclusion & Proposed Implementation Details

### A. Feature 14 Proposed Code Changes

#### 1. SoundCloud DRM Callback Fix in `services/soundcloud_service.py`
Modify lines 120–134 of `services/soundcloud_service.py`:
```python
except Exception as e:
    err_str = str(e)
    if "drm" in err_str.lower():
        if err_str not in self._drm_log_cache:
            logger.warning(f"SoundCloud DRM skip: {err_str}")
            self._drm_log_cache.add(err_str)
        if callback:
            callback([])
        elif error_callback:
            error_callback(f"SoundCloud DRM skip: {err_str}")
        return
    logger.error(f"SoundCloud search error: {e}")
    if "cookie" in err_str.lower() or "database is locked" in err_str.lower():
        if error_callback:
            error_callback("Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt")
        elif callback:
            callback([])
        return
    if error_callback:
        error_callback(f"Ошибка поиска SoundCloud: {e}")
    elif callback:
        callback([])
    return
```

#### 2. Provider Hard Timeouts & `search_completed` Emission in `core/api.py`
Refactor `search()` method in `core/api.py`:
```python
def search(self, query: str, source: str = "all", result_type: str = None):
    """Search with 4.0s per-provider hard timeout, non-blocking dispatch, and search_completed emission."""
    logger.info(f"api.py -> search called: query='{query}', source='{source}', result_type='{result_type}'")
    query = (query or "").strip()
    if not query:
        return {"query": "", "tracks": []}

    services = {
        "local": "local",
        "youtube": getattr(self._core, "youtube", None),
        "soundcloud": getattr(self._core, "soundcloud", None),
        "spotify": getattr(self._core, "spotify", None),
        "yandex": getattr(self._core, "yandex", None),
        "vk": getattr(self._core, "vk", None),
    }

    if source == "all":
        requested_names = [k for k, v in services.items() if v is not None]
    else:
        requested_names = [source] if source in services and services[source] is not None else []

    if not requested_names:
        self._emit("search_completed", {"query": query, "source": source})
        return {"query": query, "tracks": []}

    pending_providers = set(requested_names)
    lock = threading.Lock()
    completed_emitted = False

    def emit_results(tracks, service_name):
        self._emit("search_results", {
            "query": query,
            "source": service_name,
            "type": result_type,
            "tracks": tracks or [],
        })

    def mark_provider_done(service_name):
        nonlocal completed_emitted
        with lock:
            pending_providers.discard(service_name)
            if not pending_providers and not completed_emitted:
                completed_emitted = True
                self._emit("search_completed", {"query": query, "source": source})

    def run_provider_search(provider_name):
        done_event = threading.Event()
        result_holder = []

        def on_success(tracks):
            result_holder.append(tracks or [])
            done_event.set()

        def on_error(err_msg):
            logger.info(f"{provider_name} search error: {err_msg}")
            done_event.set()

        try:
            if provider_name == "local":
                local_tracks = self._core.db.search_tracks(query)
                on_success(local_tracks)
            else:
                service = services[provider_name]
                service.search(query, callback=on_success, error_callback=on_error)
        except Exception as exc:
            logger.error(f"{provider_name} search dispatch failed: {exc}")
            done_event.set()

        # Hard execution timeout of 4.0 seconds per provider
        success = done_event.wait(timeout=4.0)
        if not success:
            logger.warning(f"Search provider '{provider_name}' timed out after 4.0s for query '{query}'")
            emit_results([], provider_name)
        elif result_holder:
            emit_results(result_holder[0], provider_name)
        else:
            emit_results([], provider_name)

        mark_provider_done(provider_name)

    # Dispatch provider searches concurrently on a daemon thread
    def coordinator():
        threads = []
        for p_name in requested_names:
            t = threading.Thread(target=run_provider_search, args=(p_name,), daemon=True)
            threads.append(t)
            t.start()

    threading.Thread(target=coordinator, daemon=True).start()
    return {"query": query, "tracks": []}
```

#### 3. Frontend Handler in `ui/web_new/js/events.js` and `ui/web_new/js/search.js`
In `events.js`:
```javascript
case 'search_completed':
    onSearchCompleted(data);
    break;
```
In `search.js`:
```javascript
export function onSearchCompleted(data) {
    if (data && data.query && currentSearchQuery && data.query !== currentSearchQuery) {
        return; // Stale search completed event
    }
    const container = document.getElementById('search-results');
    if (container && container.querySelector('.spinner')) {
        if (allResults.length === 0) {
            container.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        } else {
            renderResults(allResults);
        }
    }
}
```

---

### B. Feature 15 Proposed Code Changes

Create/Update `services/base_service.py` with thread-safe `threading.Lock()` and 300-entry `OrderedDict` LRU cache:

```python
"""
NeDotify - Base Music Service
Provides shared caching, thread synchronization, and abstract service contracts.
"""

from typing import Callable, Optional, Dict, Any
import logging
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class BaseMusicService:
    """Base class for all music service providers with thread-safe stream & LRU search caches."""

    _stream_cache: Dict[str, Any] = {}
    _MAX_CACHE_SIZE = 100
    _stream_cache_lock: threading.Lock = threading.Lock()

    # Bounded Thread-Safe LRU Search Cache
    _search_cache: OrderedDict = OrderedDict()
    _SEARCH_CACHE_TTL = 300  # 5 minutes
    _MAX_SEARCH_CACHE_SIZE = 300  # Capacity limit of 300 entries
    _search_cache_lock: threading.Lock = threading.Lock()

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @classmethod
    def get_from_cache(cls, key: str) -> Optional[Any]:
        with cls._stream_cache_lock:
            return cls._stream_cache.get(key)

    @classmethod
    def set_to_cache(cls, key: str, data: Any) -> None:
        with cls._stream_cache_lock:
            if len(cls._stream_cache) >= cls._MAX_CACHE_SIZE:
                oldest_key = next(iter(cls._stream_cache))
                cls._stream_cache.pop(oldest_key, None)
            cls._stream_cache[key] = data

    @classmethod
    def get_search_cache(cls, key: str) -> Optional[Any]:
        """Thread-safe retrieval from bounded LRU search cache with TTL expiration."""
        with cls._search_cache_lock:
            entry = cls._search_cache.get(key)
            if entry is None:
                return None

            # Check TTL
            if time.time() - entry['ts'] > cls._SEARCH_CACHE_TTL:
                cls._search_cache.pop(key, None)
                return None

            # Move accessed key to end (mark as most recently used)
            cls._search_cache.move_to_end(key)
            return entry['data']

    @classmethod
    def set_search_cache(cls, key: str, data: Any) -> None:
        """Thread-safe insertion into bounded LRU search cache with max capacity 300."""
        with cls._search_cache_lock:
            if key in cls._search_cache:
                cls._search_cache.move_to_end(key)
            cls._search_cache[key] = {
                'data': data,
                'ts': time.time()
            }

            # LRU Eviction: purge least recently used items beyond capacity 300
            while len(cls._search_cache) > cls._MAX_SEARCH_CACHE_SIZE:
                cls._search_cache.popitem(last=False)

    @classmethod
    def clear_search_cache(cls) -> None:
        """Clear all search cache entries in a thread-safe manner."""
        with cls._search_cache_lock:
            cls._search_cache.clear()

    @property
    def available(self) -> bool:
        return False

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        raise NotImplementedError

    def get_stream_url(self, url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        raise NotImplementedError
```

---

## 5. Verification Method

### 1. Automated Verification
Run the search tests in the project test suite:
`python -m pytest tests/test_nedotify.py -k search`

### 2. Verification Script for LRU & Thread Safety (Feature 15)
Run a concurrent thread test against `BaseMusicService`:
```python
import threading
from services.base_service import BaseMusicService

# 1. Verify capacity limit of 300
for i in range(400):
    BaseMusicService.set_search_cache(f"key_{i}", [f"track_{i}"])

assert len(BaseMusicService._search_cache) == 300, f"Expected 300 entries, got {len(BaseMusicService._search_cache)}"
assert BaseMusicService.get_search_cache("key_0") is None, "key_0 should have been evicted by LRU"
assert BaseMusicService.get_search_cache("key_399") == ["track_399"], "key_399 should be present"

# 2. Verify thread safety under heavy concurrent access
def worker(id_):
    for i in range(100):
        BaseMusicService.set_search_cache(f"thread_{id_}_{i}", [i])
        BaseMusicService.get_search_cache(f"thread_{id_}_{i}")

threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
for t in threads: t.start()
for t in threads: t.join()

assert len(BaseMusicService._search_cache) <= 300
print("Feature 15 Thread-Safe LRU Search Cache test PASSED!")
```

### 3. Verification of Provider Timeouts & `search_completed` (Feature 14)
- **SoundCloud DRM callback check**: Inspect `services/soundcloud_service.py` to confirm `if callback: callback([])` is executed inside `if "drm" in err_str.lower():`.
- **4.0s timeout check**: In `core/api.py`, mock a slow provider with `time.sleep(10)` and verify that `search()` emits `search_results` with `[]` for that provider and emits `search_completed` after exactly 4.0 seconds without hanging the application.
