"""
NeDotify / AURA Music - Track Resolution Helper
Resolves metadata (title, artist) to a playable UI track dictionary using:
1. Local Database search
2. SoundCloud Service search
3. YouTube Service search fallback
"""

import atexit
import collections
import concurrent.futures
import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class _TrackResolverExecutor:
    """Lazy, bounded, shutdown-safe ThreadPoolExecutor for track resolution."""

    def __init__(self, max_workers: int = 8, thread_name_prefix: str = "TrackResolver"):
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._shutdown = False

    def submit(self, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Schedule `fn`; return its Future, or None when scheduling is impossible."""
        if self._shutdown or sys.is_finalizing():
            logger.debug(
                "TrackResolver executor unavailable (shutdown=%s); dropping task %r",
                self._shutdown,
                getattr(fn, "__name__", fn),
            )
            return None
        pool = self._pool
        if pool is None:
            with self._lock:
                if self._shutdown:
                    logger.debug(
                        "TrackResolver executor shut down while acquiring lock; dropping task %r",
                        getattr(fn, "__name__", fn),
                    )
                    return None
                if self._pool is None:
                    self._pool = concurrent.futures.ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix=self._thread_name_prefix,
                    )
                pool = self._pool
        try:
            return pool.submit(fn, *args, **kwargs)
        except RuntimeError as e:
            self._shutdown = True
            logger.debug("TrackResolver executor refused task %r: %s", getattr(fn, "__name__", fn), e)
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
            logger.debug("TrackResolver executor shutdown error: %s", e, exc_info=True)


_resolver_pool = _TrackResolverExecutor(max_workers=8, thread_name_prefix="TrackResolver")
atexit.register(_resolver_pool.shutdown, wait=False, cancel_futures=True)


class TrackResolver:
    """Helper class to resolve track metadata (title, artist) into playable UI track dictionaries."""

    #: Successful resolutions are remembered this long (seconds); misses far shorter so
    #: a temporary network hiccup does not poison a whole feed.
    MEMO_TTL = 300.0
    MISS_TTL = 15.0
    MEMO_MAX_ENTRIES = 512
    #: Wall-clock ceiling for a whole batch — not per track.
    BATCH_TIMEOUT = 10.0
    MAX_CONCURRENCY = 8

    def __init__(self, db=None, soundcloud_service=None, youtube_service=None):
        self.db = db
        self.sc_service = soundcloud_service
        self.yt_service = youtube_service
        self.logger = logging.getLogger(self.__class__.__name__)
        self._memo: 'collections.OrderedDict[str, Tuple[float, Dict[str, Any]]]' = collections.OrderedDict()
        self._memo_lock = threading.Lock()
        self._db_lock = threading.Lock()

    @classmethod
    def submit(cls, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Submit a task to the shared bounded track resolver pool."""
        return _resolver_pool.submit(fn, *args, **kwargs)

    @classmethod
    def shutdown_executor(cls, wait: bool = False, cancel_futures: bool = True) -> None:
        """Shut down the shared bounded track resolver thread pool."""
        _resolver_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    # ─── Resolution memo (shared by the sync and batched paths) ───

    @staticmethod
    def _memo_key(title: str, artist: str) -> str:
        return f'{(title or "").strip().lower()}\x00{(artist or "").strip().lower()}'

    def _memo_get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._memo_lock:
            entry = self._memo.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.time() > expires_at:
                self._memo.pop(key, None)
                return None
            self._memo.move_to_end(key)
            return dict(value)

    def _memo_put(self, key: str, value: Dict[str, Any]) -> None:
        if not isinstance(value, dict):
            return
        ttl = self.MEMO_TTL if value.get('source') in ('soundcloud', 'youtube', 'local') else self.MISS_TTL
        with self._memo_lock:
            self._memo[key] = (time.time() + ttl, dict(value))
            self._memo.move_to_end(key)
            while len(self._memo) > self.MEMO_MAX_ENTRIES:
                self._memo.popitem(last=False)

    @staticmethod
    def _unresolved(title: str, artist: str) -> Dict[str, Any]:
        return {
            'title': title,
            'artist': artist or 'Unknown Artist',
            'cover_url': '',
            'source': 'unknown',
            'source_id': '',
            'source_url': '',
            'duration': 0,
        }

    def _search_local(self, title: str, artist: str) -> Optional[Dict[str, Any]]:
        if not self.db:
            return None

        conn = None
        has_local_conn_prop = hasattr(self.db, 'conn')
        if has_local_conn_prop:
            conn = self.db.conn
        elif hasattr(self.db, 'cursor'):
            conn = self.db

        if not conn:
            return None

        try:
            # Protect raw non-thread-local sqlite connections with _db_lock
            if not has_local_conn_prop:
                with self._db_lock:
                    cursor = conn.cursor()
                    query = """
                        SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                        FROM tracks
                        WHERE LOWER(title) = LOWER(?) AND (LOWER(artist) = LOWER(?) OR artist = 'Unknown Artist' OR ? = '')
                        LIMIT 1
                    """
                    cursor.execute(query, (title, artist, artist))
                    row = cursor.fetchone()

                    if not row and title:
                        query_title = """
                            SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                            FROM tracks
                            WHERE LOWER(title) = LOWER(?)
                            LIMIT 1
                        """
                        cursor.execute(query_title, (title,))
                        row = cursor.fetchone()
            else:
                cursor = conn.cursor()
                query = """
                    SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                    FROM tracks
                    WHERE LOWER(title) = LOWER(?) AND (LOWER(artist) = LOWER(?) OR artist = 'Unknown Artist' OR ? = '')
                    LIMIT 1
                """
                cursor.execute(query, (title, artist, artist))
                row = cursor.fetchone()

                if not row and title:
                    query_title = """
                        SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                        FROM tracks
                        WHERE LOWER(title) = LOWER(?)
                        LIMIT 1
                    """
                    cursor.execute(query_title, (title,))
                    row = cursor.fetchone()

            if row:
                if hasattr(row, 'keys'):
                    r = dict(row)
                else:
                    r = {
                        'id': row[0],
                        'title': row[1],
                        'artist': row[2],
                        'cover_url': row[3],
                        'cover_path': row[4],
                        'source': row[5],
                        'source_id': row[6],
                        'source_url': row[7],
                        'duration': row[8],
                        'file_path': row[9],
                    }
                return {
                    'title': r.get('title') or title,
                    'artist': r.get('artist') or artist,
                    'cover_url': r.get('cover_url') or r.get('cover_path') or '',
                    'source': r.get('source') or 'local',
                    'source_id': str(r.get('source_id') or r.get('id') or ''),
                    'source_url': r.get('source_url') or r.get('file_path') or '',
                    'duration': float(r.get('duration') or 0),
                }
            return None
        except Exception as e:
            logger.warning(f"Local track search error: {e}")
            return None

    def _search_soundcloud(self, query: str) -> Optional[Dict[str, Any]]:
        if not self.sc_service:
            try:
                from services.soundcloud_service import SoundCloudService
                self.sc_service = SoundCloudService()
            except Exception as e:
                logger.warning(f"Failed to instantiate SoundCloudService: {e}")
                return None

        results = []
        done_event = threading.Event()

        def cb(trks):
            nonlocal results
            results = trks
            done_event.set()

        def err_cb(err):
            done_event.set()

        try:
            self.sc_service.search(query, max_results=1, callback=cb, error_callback=err_cb)
            done_event.wait(timeout=5.0)

            if results and isinstance(results, list):
                top = results[0]
                return {
                    'title': top.get('title', 'Unknown Title'),
                    'artist': top.get('artist', 'Unknown Artist'),
                    'cover_url': top.get('cover_url', ''),
                    'source': 'soundcloud',
                    'source_id': str(top.get('source_id', '')),
                    'source_url': top.get('source_url', ''),
                    'duration': float(top.get('duration', 0)),
                }
        except Exception as e:
            logger.warning(f"SoundCloud track resolution error: {e}")
            return None
        return None

    def _search_youtube(self, query: str) -> Optional[Dict[str, Any]]:
        if not self.yt_service:
            try:
                from services.youtube_service import YouTubeService
                self.yt_service = YouTubeService()
            except Exception as e:
                logger.warning(f"Failed to instantiate YouTubeService: {e}")
                return None

        results = []
        done_event = threading.Event()

        def cb(trks):
            nonlocal results
            results = trks
            done_event.set()

        def err_cb(err):
            done_event.set()

        try:
            self.yt_service.search(query, max_results=1, callback=cb, error_callback=err_cb)
            done_event.wait(timeout=5.0)

            if results and isinstance(results, list):
                top = results[0]
                return {
                    'title': top.get('title', 'Unknown Title'),
                    'artist': top.get('artist', 'Unknown Artist'),
                    'cover_url': top.get('cover_url', ''),
                    'source': 'youtube',
                    'source_id': str(top.get('source_id', '')),
                    'source_url': top.get('source_url', ''),
                    'duration': float(top.get('duration', 0)),
                }
        except Exception as e:
            logger.warning(f"YouTube track resolution error: {e}")
            return None
        return None

    def resolve_track(self, title: str, artist: str = '') -> Dict[str, Any]:
        memo_key = self._memo_key(title, artist)
        cached = self._memo_get(memo_key)
        if cached is not None:
            return cached

        result = self._resolve_uncached(title, artist)
        self._memo_put(memo_key, result)
        return result

    def _resolve_uncached(self, title: str, artist: str = '') -> Dict[str, Any]:
        if artist:
            query = f"{artist} {title}".strip()
        else:
            query = title.strip()

        local_res = self._search_local(title, artist)
        if local_res:
            return local_res

        sc_res = self._search_soundcloud(query)
        if sc_res:
            return sc_res

        yt_res = self._search_youtube(query)
        if yt_res:
            return yt_res

        return self._unresolved(title, artist)

    def resolve_tracks(self, pairs: Iterable[Sequence[str]], timeout: float = None) -> List[Dict[str, Any]]:
        """Resolve many (title, artist) pairs concurrently with bounded concurrency.

        Returns one dict per input pair, in exact input order, each identical in shape to
        `resolve_track`'s return value. The whole batch is bounded by `timeout`
        (default `BATCH_TIMEOUT`), so total wall time is ~one timeout instead of
        N x timeout; pairs that do not land in time come back unresolved.
        """
        items: List[Tuple[str, str]] = [
            ((pair[0] if len(pair) > 0 else '') or '', (pair[1] if len(pair) > 1 else '') or '')
            for pair in pairs
        ]
        if not items:
            return []

        results: List[Optional[Dict[str, Any]]] = [None] * len(items)
        pending: Dict[concurrent.futures.Future, List[int]] = {}
        unique_keys_to_indices: Dict[str, List[int]] = collections.defaultdict(list)

        for idx, (title, artist) in enumerate(items):
            key = self._memo_key(title, artist)
            cached = self._memo_get(key)
            if cached is not None:
                results[idx] = cached
            else:
                unique_keys_to_indices[key].append(idx)

        # Submit resolution tasks only for unique uncached tracks
        for key, indices in unique_keys_to_indices.items():
            first_idx = indices[0]
            title, artist = items[first_idx]

            future = _resolver_pool.submit(self.resolve_track, title, artist)
            if future is None:
                # Shared pool unavailable (shutting down): fall back to inline resolution.
                res = self.resolve_track(title, artist)
                for idx in indices:
                    results[idx] = res
            else:
                pending[future] = indices

        if pending:
            wait_timeout = self.BATCH_TIMEOUT if timeout is None else timeout
            _done, not_done = concurrent.futures.wait(
                list(pending.keys()),
                timeout=wait_timeout,
            )
            for future, indices in pending.items():
                first_idx = indices[0]
                title, artist = items[first_idx]
                key = self._memo_key(title, artist)

                if future in not_done:
                    logger.debug(f"Batch resolve timed out for '{artist} - {title}'")
                    unresolved = self._unresolved(title, artist)
                    self._memo_put(key, unresolved)
                    for idx in indices:
                        results[idx] = unresolved
                    continue

                try:
                    res = future.result()
                    if not isinstance(res, dict):
                        res = self._unresolved(title, artist)
                except Exception as e:
                    logger.warning(f"Batch resolve failed for '{artist} - {title}': {e}")
                    res = self._unresolved(title, artist)

                for idx in indices:
                    results[idx] = res

        return [r if r is not None else self._unresolved(*items[i]) for i, r in enumerate(results)]

    def prefetch(self, pairs: Iterable[Sequence[str]], timeout: float = None) -> None:
        """Warm the resolution memo for `pairs` in parallel with bounded concurrency so a following
        sequential loop over `resolve_track` runs at memory speed."""
        try:
            self.resolve_tracks(pairs, timeout=timeout)
        except Exception as e:
            logger.warning(f'Track resolution prefetch failed: {e}')

    def resolve_track_async(self, title: str, artist: str = '', callback: Callable = None):
        """Asynchronously resolve a track with the bounded resolver pool."""
        def _task():
            res = self.resolve_track(title, artist)
            if callback:
                try:
                    callback(res)
                except Exception as e:
                    logger.warning(f"resolve_track_async callback error for '{artist} - {title}': {e}")
            return res

        future = _resolver_pool.submit(_task)
        if future is None:
            logger.debug(f"resolve_track_async dropped for '{artist} - {title}': resolver executor unavailable")
            if callback:
                try:
                    callback(self.resolve_track(title, artist))
                except Exception as e:
                    logger.warning(f"resolve_track_async fallback callback error: {e}")


def resolve_track(title: str, artist: str = '', db: Any = None, soundcloud_service: Any = None,
                  youtube_service: Any = None) -> Dict[str, Any]:
    resolver = TrackResolver(db=db, soundcloud_service=soundcloud_service, youtube_service=youtube_service)
    return resolver.resolve_track(title, artist)


def resolve_tracks(pairs: Iterable[Sequence[str]], timeout: float = None, db: Any = None,
                   soundcloud_service: Any = None, youtube_service: Any = None) -> List[Dict[str, Any]]:
    resolver = TrackResolver(db=db, soundcloud_service=soundcloud_service, youtube_service=youtube_service)
    return resolver.resolve_tracks(pairs, timeout=timeout)