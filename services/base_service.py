"""
NeDotify - Base Music Service
Provides shared caching, background worker configuration, and abstract
service contracts for the different music providers.
"""

import logging
import sys
import time
import threading
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Proxy schemes a provider client can actually dial. Anything else is not a
# proxy we know how to use.
_PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks4a", "socks5", "socks5h"})


def normalize_proxy_url(raw: Any) -> str:
    """Return `raw` when it is a usable proxy URL, otherwise "" (direct egress).

    `auth.proxy_url` is a free-text settings field, and both `requests` and
    yt-dlp accept a bare token in it: they prepend "http://" and dial that name.
    So an unparseable value does not fail loudly at the point of configuration -
    it becomes the proxy for EVERY provider call and takes search, stream
    resolution and downloads down together with

        ProxyError: Unable to connect to proxy, NameResolutionError(...)

    which reads like a network outage rather than a bad settings value, even
    though direct egress works fine.

    Requiring an explicit scheme matches what the UI documents for the field
    (placeholder "http://127.0.0.1:1080" in ui/web_new_v2/index.html). Ignoring
    an unusable value is strictly better than applying it, and the rejection is
    logged so the cause stays visible instead of silently changing behaviour.
    """
    if not raw or not isinstance(raw, str):
        return ""
    value = raw.strip()
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
    except ValueError:
        scheme, hostname = "", None
    if scheme in _PROXY_SCHEMES and hostname:
        return value
    logger.warning(
        "Ignoring unusable auth.proxy_url %r: expected a full URL such as "
        "'http://127.0.0.1:1080'. Falling back to a direct connection.",
        raw,
    )
    return ""


class _SharedExecutor:
    """Lazy, shutdown-safe stand-in for the shared ThreadPoolExecutor.

    The real pool is only built on the first submit (behind a lock), so importing
    a service never spawns threads. `submit()` returns None instead of raising
    once the pool has been shut down or the interpreter is finalizing, which is
    what used to produce `RuntimeError: cannot schedule new futures after
    interpreter shutdown` during teardown.
    """

    def __init__(self, max_workers: int, thread_name_prefix: str = 'aura-shared'):
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._pool: Optional[ThreadPoolExecutor] = None
        self._shutdown = False

    def submit(self, fn: Callable, *args, **kwargs) -> Optional[Future]:
        """Schedule `fn`; return its Future, or None when scheduling is impossible."""
        if self._shutdown or sys.is_finalizing():
            logger.debug('Shared executor unavailable (shutdown=%s); dropping task %r',
                         self._shutdown, getattr(fn, '__name__', fn))
            return None
        pool = self._pool
        if pool is None:
            with self._lock:
                if self._shutdown:
                    logger.debug('Shared executor shut down while acquiring lock; dropping task %r',
                                 getattr(fn, '__name__', fn))
                    return None
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix=self._thread_name_prefix,
                    )
                pool = self._pool
        try:
            return pool.submit(fn, *args, **kwargs)
        except RuntimeError as e:
            self._shutdown = True
            logger.debug('Shared executor refused task %r: %s', getattr(fn, '__name__', fn), e)
            return None

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        """Stop accepting work and tear the pool down without blocking."""
        with self._lock:
            self._shutdown = True
            pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            pool.shutdown(wait=wait, cancel_futures=cancel_futures)
        except Exception as e:
            logger.debug('Shared executor shutdown error: %s', e, exc_info=True)


class BaseMusicService:
    """Base class for music services providing a shared thread pool and caching."""

    _executor = _SharedExecutor(max_workers=8)
    _cache_lock = threading.RLock()
    _stream_cache: Dict[str, Any] = {}
    _MAX_CACHE_SIZE = 2000
    # Provider stream URLs (googlevideo & co.) typically expire after ~6 hours,
    # so cached entries older than that are dead weight: serving them forces a
    # guaranteed 403 round trip through the proxy self-heal path.
    _STREAM_CACHE_TTL = 6 * 3600.0
    _search_cache: Dict[str, Dict[str, Any]] = {}
    _SEARCH_CACHE_TTL = 300
    _SEARCH_CACHE_MAX_SIZE = 300

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @classmethod
    def submit(cls, fn: Callable, *args, **kwargs) -> Optional[Future]:
        """Submit work to the shared pool. Returns None (never raises) when the
        pool is gone — e.g. after cleanup or during interpreter shutdown."""
        executor = cls._executor
        try:
            return executor.submit(fn, *args, **kwargs)
        except RuntimeError as e:
            logger.debug('Rejected task %r: %s', getattr(fn, '__name__', fn), e)
            return None

    @classmethod
    def shutdown_executor(cls) -> None:
        """Shut the shared pool down without waiting; later submits become no-ops."""
        executor = cls._executor
        shutdown = getattr(executor, 'shutdown', None)
        if not callable(shutdown):
            return
        try:
            shutdown(wait=False, cancel_futures=True)
        except Exception as e:
            logger.debug('shutdown_executor failed: %s', e, exc_info=True)

    @classmethod
    def get_from_cache(cls, key: str) -> Optional[dict]:
        """Retrieve an item from the stream cache, honouring the entry TTL.

        Values written through set_to_cache() are wrapped with a timestamp;
        raw values placed directly into _stream_cache (tests, external code)
        are returned as-is for backwards compatibility.
        """
        with cls._cache_lock:
            entry = cls._stream_cache.get(key)
            if entry is None:
                return None
            if isinstance(entry, dict) and 'data' in entry and 'ts' in entry:
                if time.time() - entry['ts'] > cls._STREAM_CACHE_TTL:
                    cls._stream_cache.pop(key, None)
                    return None
                # Hit: re-insert with the ORIGINAL timestamp, so the entry
                # becomes most-recently-used for eviction purposes only and the
                # TTL is not extended by reading.
                cls._cache_recent(cls._stream_cache, key, cls._MAX_CACHE_SIZE)
                cls._stream_cache[key] = entry
                return entry['data']
            return entry

    @classmethod
    def set_to_cache(cls, key: str, data: dict) -> None:
        """Save an item to the stream cache with a TTL stamp, size-capped (LRU)."""
        with cls._cache_lock:
            cls._cache_recent(cls._stream_cache, key, cls._MAX_CACHE_SIZE)
            cls._stream_cache[key] = {'data': data, 'ts': time.time()}

    @staticmethod
    def _cache_recent(cache: Dict[str, Any], key: str, max_size: int) -> None:
        """Prepare `cache` for `key = ...`, keeping insertion order == LRU order.

        Dicts keep insertion order, and re-assigning an existing key leaves its
        position untouched. So before every write the key must be dropped: on a
        write that is what makes it most-recently-used, and on a hit (where the
        stored timestamp must be preserved) the caller re-inserts it right
        after. Without this the "oldest entry" was really the first-inserted
        one -- FIFO -- so a key that had just been served from the cache was the
        next to be evicted.

        Keeping plain dicts (rather than OrderedDict) matters:
        services/yandex_service.py::reset_client iterates these caches directly.
        Must be called under _cache_lock.
        """
        cache.pop(key, None)
        if len(cache) >= max_size:
            cache.pop(next(iter(cache)), None)

    @classmethod
    def get_search_cache(cls, key: str) -> Optional[Any]:
        """Retrieve an item from the search cache if it has not expired.

        Symmetric with get_from_cache(): raw values placed directly into
        _search_cache (tests, external code) are returned as-is instead of
        raising KeyError on the missing 'ts'/'data' wrapper.
        """
        with cls._cache_lock:
            entry = cls._search_cache.get(key)
            if entry is None:
                return None
            if isinstance(entry, dict) and 'data' in entry and 'ts' in entry:
                if time.time() - entry['ts'] > cls._SEARCH_CACHE_TTL:
                    cls._search_cache.pop(key, None)
                    return None
                # Hit: re-insert with the ORIGINAL timestamp (recency only, TTL untouched).
                cls._cache_recent(cls._search_cache, key, cls._SEARCH_CACHE_MAX_SIZE)
                cls._search_cache[key] = entry
                return entry['data']
            return entry

    @classmethod
    def set_search_cache(cls, key: str, data: Any) -> None:
        """Save an item to the search cache together with a timestamp (LRU eviction)."""
        with cls._cache_lock:
            cls._cache_recent(cls._search_cache, key, cls._SEARCH_CACHE_MAX_SIZE)
            cls._search_cache[key] = {'data': data, 'ts': time.time()}

    @classmethod
    def clear_search_cache(cls) -> None:
        """Clear all search cache entries."""
        with cls._cache_lock:
            cls._search_cache.clear()

    @staticmethod
    def _parse_yt_entry(entry: dict) -> Optional[dict]:
        """Convert a yt-dlp entry dict into a standardized track dictionary.

        Returns None for entries with no id or with ie_key values outside
        the allowed set.
        """
        if not entry:
            return None
        ie_key = entry.get('ie_key')
        if ie_key and ie_key.lower() not in ('youtube', 'video', 'url'):
            return None
        if not entry.get('id'):
            return None
        cover_url = ''
        if entry.get('thumbnails'):
            cover_url = entry['thumbnails'][-1].get('url', '')
        elif entry.get('thumbnail'):
            cover_url = entry['thumbnail']
        source_id = entry.get('id')
        if not (cover_url and isinstance(cover_url, str) and cover_url.startswith('http')):
            if source_id:
                cover_url = f'https://img.youtube.com/vi/{source_id}/hqdefault.jpg'
        artist = entry.get('uploader', 'Unknown Artist')
        if artist.endswith(' - Topic'):
            artist = artist[:-8]
        source_id = entry.get('id')
        return {
            'title': entry.get('title', 'Unknown Title'),
            'artist': artist,
            'duration': entry.get('duration', 0),
            'source': 'youtube',
            'source_id': source_id,
            'source_url': entry.get('url') or f'https://www.youtube.com/watch?v={source_id}',
            'cover_url': cover_url,
        }

    @property
    def available(self) -> bool:
        """Override in subclasses to report the availability status."""
        return False

    def search(self, query: str, max_results: int = 20,
               callback: Optional[Callable] = None,
               error_callback: Optional[Callable] = None):
        raise NotImplementedError

    def get_stream_url(self, url: str,
                       callback: Optional[Callable] = None,
                       error_callback: Optional[Callable] = None,
                       **kwargs):
        raise NotImplementedError