# Milestone 3 (Search Optimization & Caching) — Backend Investigation Report

## 1. Observation

Direct observations from codebase inspection across `core/api.py`, `core/database.py`, `services/base_service.py`, and `services/soundcloud_service.py`:

### Feature 12: Yandex Search Provider Key in `core/api.py`
- **File & Line**: `core/api.py`, lines 330–335.
- **Verbatim Code**:
  ```python
  330:         services = {
  331:             "youtube": getattr(self._core, "youtube", None),
  332:             "soundcloud": getattr(self._core, "soundcloud", None),
  333:             "spotify": getattr(self._core, "spotify", None),
  334:             "vk": getattr(self._core, "vk", None),
  335:         }
  ```
- **Observation**: `getattr(self._core, "yandex", None)` is missing from the `services` mapping dictionary inside `AppApi.search()`. However, `self.yandex = YandexService(self.settings)` is properly initialized in `AppCore.__init__()` at `core/app.py:82`. Consequently, Yandex search dispatch is never invoked even when requested.

---

### Feature 13: Local Database Search Thread-Blocking & Missing Indexes
- **File & Line 1**: `core/api.py`, lines 321–328.
- **Verbatim Code**:
  ```python
  321:         if source in ("all", "local"):
  322:             try:
  323:                 local_tracks = self._core.db.search_tracks(query)
  324:                 emit_results(local_tracks, "local")
  325:             except Exception as exc:
  326:                 logger.error("Local search failed: %s", exc)
  327:             if source == "local":
  328:                 return {"query": query, "tracks": []}
  ```
- **Observation 1**: `self._core.db.search_tracks(query)` is executed synchronously on the main thread (pywebview JS bridge thread) before any remote provider search is dispatched.
- **File & Line 2**: `core/database.py`, lines 179–180 & 526–538.
- **Verbatim Code**:
  ```python
  179:         cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source)")
  180:         cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_favorite ON tracks(is_favorite)")
  ...
  529:         cursor.execute(
  530:             """
  531:             SELECT * FROM tracks 
  532:             WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
  533:             ORDER BY play_count DESC
  534:             LIMIT ?
  535:         """,
  536:             (like_query, like_query, like_query, limit),
  537:         )
  ```
- **Observation 2**: SQL search filters `WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?` run without SQLite indexes on `tracks(title)` or `tracks(artist)`. While `idx_tracks_source` and `idx_tracks_favorite` exist, indexes for `title` and `artist` are absent in `_init_database()`.

---

### Feature 14: Per-Provider Execution Timeouts, SoundCloud DRM Callback Skip & Completion Event
- **File & Line 1**: `services/soundcloud_service.py`, lines 120–135.
- **Verbatim Code**:
  ```python
  120:             except Exception as e:
  121:                 err_str = str(e)
  122:                 if "drm" in err_str.lower():
  123:                     if err_str not in self._drm_log_cache:
  124:                         logger.warning(f"SoundCloud DRM skip: {err_str}")
  125:                         self._drm_log_cache.add(err_str)
  126:                     return
  127:                 logger.error(f"SoundCloud search error: {e}")
  ```
- **Observation 1**: Line 126 executes a naked `return` when `yt_dlp` encounters a DRM error string on SoundCloud. It neither invokes `callback` nor `error_callback`. As a result, the caller waiting for SoundCloud completion hangs indefinitely or until an outer system timeout.
- **File & Line 2**: `core/api.py`, lines 336–352.
- **Observation 2**: `search()` loops through `requested` providers and calls `service.search()`, but does not track provider completion status, does not enforce a hard 4.0s execution timeout per provider, and does not emit a `search_completed` UI event when all providers finish.

---

### Feature 15: Search Cache Immutability & Thread Safety in `services/base_service.py`
- **File**: `services/base_service.py` (`BaseMusicService` class decompiled/disassembled).
- **Verbatim Disassembly / Implementation**:
  ```python
  class BaseMusicService:
      _search_cache = {}
      _SEARCH_CACHE_TTL = 300

      @classmethod
      def get_search_cache(cls, key: str):
          entry = cls._search_cache.get(key)
          if entry is None:
              return None
          if time.time() - entry['ts'] > cls._SEARCH_CACHE_TTL:
              cls._search_cache.pop(key, None)
              return None
          return entry['data']

      @classmethod
      def set_search_cache(cls, key: str, data: list):
          cls._search_cache[key] = {
              'data': data,
              'ts': time.time()
          }
  ```
- **Observation**:
  1. `_search_cache` is an un-locked standard `dict`.
  2. Concurrent calls from multiple worker threads in `ThreadPoolExecutor` read and modify `_search_cache` without `threading.Lock()`, risking dictionary mutation race conditions.
  3. `set_search_cache` lacks any max capacity limit or LRU eviction strategy.

---

## 2. Logic Chain

1. **Feature 12 Reasoning**:
   - `AppCore` initializes `self.yandex = YandexService(self.settings)` at `core/app.py:82`.
   - In `core/api.py:330-335`, the `services` mapping dictionary contains `"youtube"`, `"soundcloud"`, `"spotify"`, `"vk"`, but omits `"yandex"`.
   - When a user performs a search with `source="all"` or `source="yandex"`, `search()` looks up `services.get("yandex")` which returns `None` and skips searching Yandex Music.
   - Adding `"yandex": getattr(self._core, "yandex", None)` restores Yandex Music search in backend dispatcher.

2. **Feature 13 Reasoning**:
   - `self._core.db.search_tracks(query)` at `core/api.py:323` runs synchronous SQLite reads on pywebview's UI bridge thread.
   - If SQLite performs table scans on `tracks` without indexes during background database writes (e.g., playback history logging or track downloading), pywebview IPC is blocked, causing UI lag.
   - Offloading `db.search_tracks(query)` to a dedicated `ThreadPoolExecutor` worker pool in `core/api.py` ensures the pywebview main thread returns immediately.
   - Creating SQLite indexes `idx_tracks_title` on `tracks(title)` and `idx_tracks_artist` on `tracks(artist)` in `core/database.py:_init_database()` turns `LIKE` title/artist queries from full table scans into indexed range lookups.

3. **Feature 14 Reasoning**:
   - In `services/soundcloud_service.py`, DRM errors trigger early return at line 126 without invoking `callback` or `error_callback`. Consequently, caller callbacks never fire.
   - Updating lines 122–126 to invoke `if callback: callback([])` or `if error_callback: error_callback(err_str)` guarantees caller notification.
   - Remote search providers (such as YouTube via `ytmusicapi` with a 15s session timeout) can hang search requests.
   - Enforcing a 4.0s hard per-provider execution timeout guard using `threading.Timer` or `concurrent.futures` in `core/api.py` search dispatcher guarantees that slow/hung providers do not delay overall search completion beyond 4.0 seconds.
   - Emitting `search_completed` payload `{"query": query, "source": source}` when all requested providers complete or timeout notifies the JS frontend (`search.js`) to terminate the loading spinner cleanly.

4. **Feature 15 Reasoning**:
   - `BaseMusicService`'s search cache uses a plain dictionary `_search_cache = {}` without mutex synchronization.
   - Because search tasks run across `ThreadPoolExecutor` worker threads, simultaneous read/write calls to `_search_cache` can throw `RuntimeError: dictionary changed size during iteration` or lose entries.
   - Refactoring `_search_cache` to use `collections.OrderedDict()`, wrapped in `threading.Lock()`, with a maximum capacity limit (300 entries) and LRU eviction (`move_to_end` on hit, `popitem(last=False)` on overflow) ensures thread safety, bounded memory usage, and optimal cache hit performance.

---

## 3. Caveats

- **VK Service**: `VKService.search` returns `callback([])` due to VK anti-bot limitations. It completes instantly and non-blockingly, which works cleanly with the timeout dispatcher.
- **iTunes API Fallback in `SpotifyService`**: `SpotifyService` queries iTunes Search API for metadata search with a 3.5s HTTP timeout, which fits comfortably within the 4.0s hard provider timeout.
- **SQLite LIKE Pattern Limitations**: SQLite `LIKE %query%` queries with leading wildcards can only partially leverage indexes, but `idx_tracks_title` and `idx_tracks_artist` significantly improve query plan estimation and index scan speed.

---

## 4. Conclusion & Implementation Recommendations

### Recommended Code Snippets & Edits

#### 1. `core/api.py` (Features 12, 13, 14)

```python
# In AppApi.__init__(self, core):
self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")

# In AppApi.search(self, query: str, source: str = "all", result_type: str = None):
def search(self, query: str, source: str = "all", result_type: str = None):
    logger.info(f"api.py -> search called: query='{query}', source='{source}', result_type='{result_type}'")
    query = (query or "").strip()
    if not query:
        return {"query": "", "tracks": []}

    def emit_results(tracks, service_name):
        self._emit("search_results", {
            "query": query,
            "source": service_name,
            "type": result_type,
            "tracks": tracks or [],
        })

    services = {
        "youtube": getattr(self._core, "youtube", None),
        "soundcloud": getattr(self._core, "soundcloud", None),
        "spotify": getattr(self._core, "spotify", None),
        "yandex": getattr(self._core, "yandex", None),
        "vk": getattr(self._core, "vk", None),
    }

    if source == "all":
        requested_providers = ["local", "youtube", "soundcloud", "spotify", "yandex", "vk"]
    elif source == "local":
        requested_providers = ["local"]
    else:
        requested_providers = [source]

    pending_lock = threading.Lock()
    pending_providers = set(requested_providers)
    completion_emitted = [False]

    def mark_done(provider_name):
        with pending_lock:
            if provider_name in pending_providers:
                pending_providers.remove(provider_name)
            if not pending_providers and not completion_emitted[0]:
                completion_emitted[0] = True
                self._emit("search_completed", {"query": query, "source": source})

    # Dispatch Local DB Search Asynchronously (Feature 13)
    if "local" in requested_providers:
        def _run_local():
            try:
                local_tracks = self._core.db.search_tracks(query)
                emit_results(local_tracks, "local")
            except Exception as exc:
                logger.error("Local search failed: %s", exc)
            finally:
                mark_done("local")

        self._search_executor.submit(_run_local)

    # Dispatch Remote Providers with 4.0s Hard Timeout (Feature 12 & 14)
    for service_name in requested_providers:
        if service_name == "local":
            continue

        service = services.get(service_name)
        if not service:
            mark_done(service_name)
            continue

        done_event = threading.Event()

        def _make_on_success(name):
            def _on_success(tracks):
                if not done_event.is_set():
                    done_event.set()
                    emit_results(tracks, name)
                    mark_done(name)
            return _on_success

        def _make_on_error(name):
            def _on_error(error):
                if not done_event.is_set():
                    done_event.set()
                    logger.info("%s search failed: %s", name, error)
                    mark_done(name)
            return _on_error

        def _make_on_timeout(name):
            def _on_timeout():
                if not done_event.is_set():
                    done_event.set()
                    logger.warning("%s search timed out after 4.0s", name)
                    mark_done(name)
            return _on_timeout

        timer = threading.Timer(4.0, _make_on_timeout(service_name))
        timer.daemon = True
        timer.start()

        try:
            service.search(
                query,
                callback=_make_on_success(service_name),
                error_callback=_make_on_error(service_name)
            )
        except Exception as exc:
            logger.error("%s search could not start: %s", service_name, exc)
            if not done_event.is_set():
                done_event.set()
                mark_done(service_name)

    return {"query": query, "tracks": []}
```

---

#### 2. `core/database.py` (Feature 13 Indexes)

In `_init_database()` (lines 179–181):
```python
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_favorite ON tracks(is_favorite)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
```

---

#### 3. `services/soundcloud_service.py` (Feature 14 DRM Patch)

In `search()` (lines 122–126):
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
```

---

#### 4. `services/base_service.py` (Feature 15 Thread-Safe LRU Cache)

Source code structure for `services/base_service.py`:
```python
"""
NeDotify - Base Music Service
Provides abstract base class for music providers with thread-safe bounded LRU caching.
"""

import collections
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class BaseMusicService:
    """Base class for music services providing shared thread pool and thread-safe LRU search cache."""

    _executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="MusicServiceWorker")
    _stream_cache: Dict[str, Any] = {}
    _search_cache = collections.OrderedDict()
    _cache_lock = threading.Lock()

    _SEARCH_CACHE_TTL = 300  # 5 minutes
    _MAX_SEARCH_CACHE_SIZE = 300
    _MAX_CACHE_SIZE = 2000

    def __init__(self, settings=None):
        self.settings = settings

    @classmethod
    def get_search_cache(cls, key: str) -> Optional[Any]:
        with cls._cache_lock:
            entry = cls._search_cache.get(key)
            if entry is None:
                return None
            if time.time() - entry.get("ts", 0) > cls._SEARCH_CACHE_TTL:
                cls._search_cache.pop(key, None)
                return None
            cls._search_cache.move_to_end(key)
            return entry.get("data")

    @classmethod
    def set_search_cache(cls, key: str, data: Any) -> None:
        with cls._cache_lock:
            if key in cls._search_cache:
                cls._search_cache[key] = {"data": data, "ts": time.time()}
                cls._search_cache.move_to_end(key)
            else:
                cls._search_cache[key] = {"data": data, "ts": time.time()}
                while len(cls._search_cache) > cls._MAX_SEARCH_CACHE_SIZE:
                    cls._search_cache.popitem(last=False)

    @classmethod
    def get_from_cache(cls, key: str) -> Optional[Any]:
        return cls._stream_cache.get(key)

    @classmethod
    def set_to_cache(cls, key: str, data: Any) -> None:
        if len(cls._stream_cache) >= cls._MAX_CACHE_SIZE:
            oldest_key = next(iter(cls._stream_cache))
            cls._stream_cache.pop(oldest_key, None)
        cls._stream_cache[key] = data

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        raise NotImplementedError

    def get_stream_url(self, url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        raise NotImplementedError
```

---

## 5. Verification Method

1. **Yandex Integration Verification**:
   - Inspect `core/api.py` `services` dictionary (confirm `"yandex": getattr(self._core, "yandex", None)` is present).

2. **Non-blocking DB Search & Index Verification**:
   - Inspect `core/database.py` `_init_database()` for `idx_tracks_title` and `idx_tracks_artist`.
   - Run SQLite schema check via python:
     `python -c "import sqlite3; conn=sqlite3.connect('aura.db'); print(conn.execute(\"PRAGMA index_list('tracks')\").fetchall())"`

3. **SoundCloud DRM & Timeout Verification**:
   - Inspect `services/soundcloud_service.py` DRM exception branch (confirm callback/error_callback execution).
   - Inspect `core/api.py` dispatcher (confirm 4.0s timeout timer and `search_completed` event).

4. **Thread-Safe LRU Search Cache Verification**:
   - Run unit test for search cache concurrent access and eviction:
     `python -m pytest tests/ -k search`
