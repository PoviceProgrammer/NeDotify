"""
NeDotify - Stream URL Resolution Coordinator (C-3)

Cache layer in front of the network resolution cascade:
    in-memory dict -> DB stream_cache -> network cascade (single-flight).

Single-flight: concurrent requests for the same (source, source_id) share one
background resolution instead of each triggering the full network cascade.
"""

import logging
import threading
import time
from typing import Callable, Optional, Tuple

from utils.stream_urls import stream_url_expired

logger = logging.getLogger(__name__)

_MEM_TTL = 3600.0        # in-memory URL lifetime (seconds)
_MEM_MAX_SIZE = 1024     # in-memory cache cap; least recently used entry is evicted on overflow
_RESOLVE_TIMEOUT = 35.0  # owner and waiters share one cascade deadline
_DB_MAX_AGE = 14400      # DB stream_cache max age (seconds) — googlevideo URLs expire in ~6h
#: A key whose cascade just produced nothing is skipped for this long. Short on
#: purpose: a DRM-protected or deleted track keeps the same answer for good,
#: while a network blip is retried two minutes later instead of forever.
_FAIL_TTL = 120.0
_FAIL_MAX_SIZE = 512


class _Flight:
    __slots__ = ("event", "url", "error", "deadline")

    def __init__(self):
        self.event = threading.Event()
        self.url = None
        self.error = None
        self.deadline = 0.0


class StreamResolver:
    """Coordinates stream URL resolution: cache lookup, then single-flight network cascade."""

    def __init__(self, db, mem_ttl: float = _MEM_TTL, resolve_timeout: float = _RESOLVE_TIMEOUT,
                 db_max_age: int = _DB_MAX_AGE, settings=None):
        self._db = db
        self._mem_ttl = mem_ttl
        self._resolve_timeout = resolve_timeout
        self._db_max_age = db_max_age
        self._settings = settings
        self._lock = threading.Lock()
        self._mem = {}      # key -> (url, ts)
        self._inflight = {} # key -> _Flight
        self._failed = {}   # key -> ts of a cascade that produced no URL
        self._stats = {
            "mem_hits": 0,
            "db_hits": 0,
            "network_cascades": 0,
            "single_flight_waits": 0,
        }

    @staticmethod
    def _key(source: str, source_id) -> Tuple[str, str]:
        return (source, str(source_id))

    def _mem_set(self, key, value: Tuple[str, float]) -> None:
        """Insert into the in-memory cache, evicting the least recently used entry past the cap.

        Plain dicts preserve insertion order, so the re-insert below is what
        makes this LRU rather than FIFO: assigning an existing key keeps its
        original position, which would let a key that is being hit constantly
        be evicted first. Caller must hold ``self._lock``.
        """
        # Drop first: on an overwrite this makes the key most-recently-used, and
        # on a fresh insert it stops it from counting against the cap itself.
        self._mem.pop(key, None)
        if len(self._mem) >= _MEM_MAX_SIZE:
            self._mem.pop(next(iter(self._mem)), None)
        self._mem[key] = value

    def _mark_failed(self, key) -> None:
        """Remember that this key's cascade produced no URL. Caller must hold ``self._lock``."""
        self._failed.pop(key, None)
        if len(self._failed) >= _FAIL_MAX_SIZE:
            self._failed.pop(next(iter(self._failed)), None)
        self._failed[key] = time.time()

    def _is_failed(self, key) -> bool:
        """True while a fresh "no URL" verdict stands for this key."""
        with self._lock:
            failed_at = self._failed.get(key)
            if failed_at is None:
                return False
            if time.time() - failed_at > _FAIL_TTL:
                self._failed.pop(key, None)
                return False
            return True

    def is_unavailable(self, source: str, source_id) -> bool:
        """True when this track is known not to resolve (see ``mark_unavailable``)."""
        return self._is_failed(self._key(source, source_id))

    def mark_unavailable(self, source: str, source_id, reason: Optional[str] = None) -> None:
        """Record that this track cannot be resolved, without running the cascade.

        For a provider that can tell "this track is gone" apart from "the
        network hiccupped" — a DRM-protected, private or deleted upload. The
        next :meth:`resolve` answers None straight away, so the caller can move
        on to the next track instead of walking the same cascade again. Pass the
        provider's own verdict through ``mark_unavailable`` rather than letting
        every failed cascade be remembered: this one is deliberately not a
        fallback for ``resolve`` returning nothing on its own.
        """
        key = self._key(source, source_id)
        with self._lock:
            self._mark_failed(key)
        logger.info(
            f"Marked {source}:{source_id} unavailable: {reason or 'no playable stream'}"
        )

    def clear_unavailable(self, source: str, source_id) -> None:
        """Forget a recorded "no URL" verdict, so the track is tried again."""
        with self._lock:
            self._failed.pop(self._key(source, source_id), None)

    @staticmethod
    def _url_expired(url: Optional[str]) -> bool:
        """Reject explicit expired CDN tokens without a network round trip."""
        return stream_url_expired(url, now=time.time())

    def _mem_get(self, key, now):
        """Read and touch a valid memory entry. Caller holds ``self._lock``."""
        entry = self._mem.get(key)
        if entry and now - entry[1] <= self._mem_ttl and not self._url_expired(entry[0]):
            self._stats["mem_hits"] += 1
            # LRU recency changes; the original TTL timestamp does not.
            self._mem_set(key, entry)
            return entry[0]
        if entry:
            self._mem.pop(key, None)
        return None

    def get_cached_url(self, source: str, source_id) -> Optional[str]:
        """Return a cached stream URL (in-memory first, then DB), or None."""
        key = self._key(source, source_id)
        now = time.time()
        with self._lock:
            cached = self._mem_get(key, now)
            if cached:
                return cached

        if self._db is not None:
            try:
                cached = self._db.get_cached_stream(source, str(source_id), max_age_seconds=self._db_max_age)
                if cached and cached.get("stream_url"):
                    if self._url_expired(cached["stream_url"]):
                        self.invalidate(source, str(source_id))
                        return None
                    expires_at = cached.get("expires_at")
                    if expires_at:
                        try:
                            from datetime import datetime
                            exp_ts = datetime.fromisoformat(str(expires_at)).timestamp() if isinstance(expires_at, str) else expires_at.timestamp()
                            if exp_ts <= now:
                                self.invalidate(source, str(source_id))
                                return None
                        except Exception:
                            pass
                    with self._lock:
                        # Memory must not extend the persisted URL's lifetime.
                        stamp = cached.get("cached_at")
                        try:
                            from datetime import datetime
                            cached_at = datetime.fromisoformat(str(stamp)).timestamp()
                        except (TypeError, ValueError):
                            cached_at = now - self._mem_ttl
                        self._mem_set(key, (cached["stream_url"], min(now, cached_at)))
                        self._stats["db_hits"] += 1
                    return cached["stream_url"]
            except Exception as e:
                logger.debug(f"DB stream cache lookup failed: {e}")
        return None

    def resolve(self, source: str, source_id, resolver_fn: Callable[[], Tuple[Optional[str], Optional[str]]],
                cancel_token: Optional[Callable[[], bool]] = None) -> Optional[str]:
        """Return a stream URL for (source, source_id).

        resolver_fn runs the network cascade and returns (url, error).
        Single-flight: concurrent callers wait on the same in-flight resolution.
        Success is persisted to DB and the in-memory cache.
        """
        key = self._key(source, source_id)

        cached = self.get_cached_url(source, source_id)
        if cached:
            return cached

        # A track a provider already declared unplayable costs nothing to skip.
        # Without this the whole cascade (up to three provider searches plus two
        # stream extractions) reruns on every request for the same dead track.
        if self._is_failed(key):
            logger.info(
                f"Skipping resolution of {source}:{source_id}: already known unavailable"
            )
            return None

        owner = False
        with self._lock:
            # A previous owner can finish after our initial cache miss but
            # before this lock. Re-check atomically with creating the flight,
            # otherwise prefetch + Play can extract the same track twice.
            cached = self._mem_get(key, time.time())
            if cached:
                return cached
            flight = self._inflight.get(key)
            if flight is None:
                flight = _Flight()
                flight.deadline = time.monotonic() + self._resolve_timeout
                self._inflight[key] = flight
                owner = True
                # Counted here, inside the same critical section that decides
                # who owns the flight, so the counter can never disagree with
                # the single-flight bookkeeping (and stats() reads it under the
                # very same lock). Was incremented after releasing the lock,
                # which is a read-modify-write on a shared dict.
                self._stats["network_cascades"] += 1
            else:
                self._stats["single_flight_waits"] += 1

        def run_owner():
            try:
                url, error = resolver_fn()
                with self._lock:
                    if self._inflight.get(key) is not flight or flight.event.is_set():
                        return
                    flight.url, flight.error = url, error
                if url:
                    self._persist(source, source_id, url)
                elif not url and error:
                    verdict = str(error).lower()
                    if "403" in verdict or "forbidden" in verdict:
                        self.invalidate(source, str(source_id))
                    if any(mark in verdict for mark in ("deleted", "removed", "private video", "not available", "drm protected")):
                        self.mark_unavailable(source, source_id, str(error))
            except Exception as e:
                flight.error = str(e)
                if "403" in str(e).lower() or "forbidden" in str(e).lower():
                    self.invalidate(source, str(source_id))
            finally:
                with self._lock:
                    if self._inflight.get(key) is flight:
                        self._inflight.pop(key, None)
                flight.event.set()

        if owner:
            # A provider may block before invoking its callback. A daemon owns
            # that call so every caller still gets the same finite deadline.
            threading.Thread(target=run_owner, name="StreamResolve", daemon=True).start()
        while cancel_token and not flight.event.is_set():
            if cancel_token():
                return None
            remaining = flight.deadline - time.monotonic()
            if remaining <= 0:
                break
            flight.event.wait(timeout=min(0.1, remaining))
        if not flight.event.wait(timeout=max(0.0, flight.deadline - time.monotonic()) if not cancel_token else 0):
            with self._lock:
                if self._inflight.get(key) is flight:
                    self._inflight.pop(key, None)
                    flight.error = "Stream resolution deadline exceeded"
                    flight.event.set()

        if flight.url:
            return flight.url
        if flight.error:
            logger.warning(f"Stream resolution failed for {source}:{source_id}: {flight.error}")
        return None

    def refresh(self, source: str, source_id, stream_url: str) -> None:
        """Overwrite cached URL (e.g. after a successful re-resolution/reconnect)."""
        if not stream_url:
            return
        self._persist(source, source_id, stream_url)

    def invalidate(self, source: str, source_id) -> None:
        """Drop a dead URL from memory and clear it in the DB (keeps downloaded-file rows).

        Deliberately leaves any "known unavailable" verdict in place: the proxy
        calls this on every upstream 403 and then re-resolves, so clearing it
        here would re-open the retry loop this memo exists to stop. A URL that
        was merely expired carries no verdict to preserve, and a real recovery
        goes through :meth:`refresh`, which clears it.
        """
        key = self._key(source, source_id)
        with self._lock:
            self._mem.pop(key, None)
        if self._db is not None:
            try:
                self._db.invalidate_cached_stream(source, str(source_id))
            except Exception as e:
                logger.debug(f"Failed to invalidate cached stream URL: {e}")

    def _persist(self, source: str, source_id, url: str) -> None:
        key = self._key(source, source_id)
        with self._lock:
            self._mem_set(key, (url, time.time()))
            # A URL that exists is proof the track resolves, so any recorded
            # verdict for it is stale.
            self._failed.pop(key, None)
        if self._db is not None:
            try:
                self._db.update_cached_stream_url(source, str(source_id), url)
            except Exception as e:
                logger.debug(f"Failed to cache stream URL: {e}")

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)
