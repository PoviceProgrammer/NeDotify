"""
NeDotify / AURA Music - Stream URL Resolution Coordinator (C-3)

Cache layer in front of the network resolution cascade:
    in-memory dict -> DB stream_cache -> network cascade (single-flight).

Single-flight: concurrent requests for the same (source, source_id) share one
background resolution instead of each triggering the full network cascade.
"""

import logging
import threading
import time
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

_MEM_TTL = 3600.0        # in-memory URL lifetime (seconds)
_RESOLVE_TIMEOUT = 12.0  # max wait for a single-flight resolution
_DB_MAX_AGE = 86400      # DB stream_cache max age (seconds)


class _Flight:
    __slots__ = ("event", "url", "error")

    def __init__(self):
        self.event = threading.Event()
        self.url = None
        self.error = None


class StreamResolver:
    """Coordinates stream URL resolution: cache lookup, then single-flight network cascade."""

    def __init__(self, db, mem_ttl: float = _MEM_TTL, resolve_timeout: float = _RESOLVE_TIMEOUT,
                 db_max_age: int = _DB_MAX_AGE):
        self._db = db
        self._mem_ttl = mem_ttl
        self._resolve_timeout = resolve_timeout
        self._db_max_age = db_max_age
        self._lock = threading.Lock()
        self._mem = {}      # key -> (url, ts)
        self._inflight = {} # key -> _Flight
        self._stats = {
            "mem_hits": 0,
            "db_hits": 0,
            "network_cascades": 0,
            "single_flight_waits": 0,
        }

    @staticmethod
    def _key(source: str, source_id) -> Tuple[str, str]:
        return (source, str(source_id))

    def get_cached_url(self, source: str, source_id) -> Optional[str]:
        """Return a cached stream URL (in-memory first, then DB), or None."""
        key = self._key(source, source_id)
        now = time.time()
        with self._lock:
            entry = self._mem.get(key)
            if entry and now - entry[1] <= self._mem_ttl:
                self._stats["mem_hits"] += 1
                return entry[0]
            self._mem.pop(key, None)

        if self._db is not None:
            try:
                cached = self._db.get_cached_stream(source, str(source_id), max_age_seconds=self._db_max_age)
                if cached and cached.get("stream_url"):
                    with self._lock:
                        self._mem[key] = (cached["stream_url"], now)
                    self._stats["db_hits"] += 1
                    return cached["stream_url"]
            except Exception as e:
                logger.debug(f"DB stream cache lookup failed: {e}")
        return None

    def resolve(self, source: str, source_id, resolver_fn: Callable[[], Tuple[Optional[str], Optional[str]]]) -> Optional[str]:
        """Return a stream URL for (source, source_id).

        resolver_fn runs the network cascade and returns (url, error).
        Single-flight: concurrent callers wait on the same in-flight resolution.
        Success is persisted to DB and the in-memory cache.
        """
        key = self._key(source, source_id)

        cached = self.get_cached_url(source, source_id)
        if cached:
            return cached

        owner = False
        with self._lock:
            flight = self._inflight.get(key)
            if flight is None:
                flight = _Flight()
                self._inflight[key] = flight
                owner = True
            else:
                self._stats["single_flight_waits"] += 1

        if owner:
            try:
                self._stats["network_cascades"] += 1
                url, error = resolver_fn()
                flight.url = url
                flight.error = error
                if url:
                    self._persist(source, source_id, url)
            except Exception as e:
                flight.error = str(e)
            finally:
                with self._lock:
                    if self._inflight.get(key) is flight:
                        self._inflight.pop(key, None)
                flight.event.set()
        else:
            flight.event.wait(timeout=self._resolve_timeout)

        if flight.url:
            return flight.url
        if flight.error:
            logger.warning(f"Stream resolution failed for {source}:{source_id}: {flight.error}")
        return None

    def refresh(self, source: str, source_id, stream_url: str) -> None:
        """Overwrite cached URL (e.g. after a successful re-resolution/reconnect)."""
        if not stream_url:
            return
        key = self._key(source, source_id)
        with self._lock:
            self._mem[key] = (stream_url, time.time())
        if self._db is not None:
            try:
                self._db.cache_stream(source, str(source_id), stream_url)
            except Exception as e:
                logger.debug(f"Failed to cache refreshed stream URL: {e}")

    def _persist(self, source: str, source_id, url: str) -> None:
        key = self._key(source, source_id)
        with self._lock:
            self._mem[key] = (url, time.time())
        if self._db is not None:
            try:
                self._db.cache_stream(source, str(source_id), url)
            except Exception as e:
                logger.debug(f"Failed to cache stream URL: {e}")

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)