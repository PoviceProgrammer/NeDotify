"""
NeDotify - Lyrics Service
Fetches verified plain lyrics and progressively upgrades compatible results to karaoke.
"""

import atexit
import concurrent.futures
import json
import logging
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Every outbound lyrics request gets this ceiling so a hung host cannot pin a worker.
HTTP_TIMEOUT = 6.0


class _LyricsSharedExecutor:
    """Lazy, bounded, shutdown-safe ThreadPoolExecutor for lyrics fetching."""

    def __init__(self, max_workers: int = 4, thread_name_prefix: str = "LyricsPool"):
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._shutdown = False

    def submit(self, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Schedule `fn`; return its Future, or None when scheduling is impossible."""
        if self._shutdown or sys.is_finalizing():
            logger.debug(
                "Lyrics executor unavailable (shutdown=%s); dropping task %r",
                self._shutdown,
                getattr(fn, "__name__", fn),
            )
            return None
        pool = self._pool
        if pool is None:
            with self._lock:
                if self._shutdown:
                    logger.debug(
                        "Lyrics executor shut down while acquiring lock; dropping task %r",
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
            logger.debug("Lyrics executor refused task %r: %s", getattr(fn, "__name__", fn), e)
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
            logger.debug("Lyrics executor shutdown error: %s", e, exc_info=True)


# Every independent source can start together; recovery forms run in the same
# job so a slow rich-lyrics host cannot queue out the original sources.
_lyrics_pool = _LyricsSharedExecutor(max_workers=8, thread_name_prefix="LyricsPool")
atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)


class LyricsService:
    def __init__(self, settings=None, *, cache_path=None):
        self.settings = settings
        self._cache = {}
        self._cache_lock = threading.RLock()
        from services.lyrics_lookup import LyricsLookup
        self._lookup = LyricsLookup(self, cache_path=cache_path)

    @classmethod
    def submit(cls, fn: Callable, *args, **kwargs) -> Optional[concurrent.futures.Future]:
        """Submit a task to the shared bounded lyrics thread pool."""
        return _lyrics_pool.submit(fn, *args, **kwargs)

    @classmethod
    def shutdown_executor(cls, wait: bool = False, cancel_futures: bool = True) -> None:
        """Shut down the shared bounded lyrics thread pool."""
        _lyrics_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    def _open_url(self, req_or_url, headers=None, timeout=3.5):
        from services.base_service import BaseMusicService, normalize_proxy_url
        if isinstance(req_or_url, str):
            req = urllib.request.Request(req_or_url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
        else:
            req = req_or_url
        proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', '')) if self.settings else ''
        if proxy:
            return BaseMusicService.open_url(self, req, timeout=timeout)
        # Reuse the verified public transport used for media. System proxy/TUN
        # routing remains in force, while TLS setup and short metadata replies
        # no longer pay for a fresh context/connection on every lyric request.
        from utils.url_safety import guarded_open_url
        return guarded_open_url(req, timeout=timeout)

    # BUG-L2-007: one hung host must not pin the bridge — the whole translation
    # gets this wall-clock budget (checked between chunk requests).
    TRANSLATION_BUDGET_SECONDS = 45.0
    # BUG-L2-010: a single line over the URL budget is force-split on spaces
    # instead of failing the whole translation.
    _CHUNK_URL_LIMIT = 6000

    def translate_lyrics(self, lyrics: str, target_lang="ru") -> str:
        if not lyrics:
            return ""
        deadline = time.monotonic() + self.TRANSLATION_BUDGET_SECONDS
        # Chunk long lyrics: a whole song in one ?q= blows past URL limits (414)
        # and gets rate-limited. 1500 chars keeps each GET well under 8KB quoted.
        chunks, current = [], []

        def _emit(line):
            if current and len(urllib.parse.quote('\n'.join(current + [line])).encode('ascii')) > self._CHUNK_URL_LIMIT:
                chunks.append('\n'.join(current))
                current.clear()
            current.append(line)

        for line in str(lyrics).split('\n'):
            if len(urllib.parse.quote(line).encode('ascii')) > self._CHUNK_URL_LIMIT:
                piece = ''
                for word in re.split(r'(\s+)', line):
                    if piece and len(urllib.parse.quote(piece + word).encode('ascii')) > self._CHUNK_URL_LIMIT:
                        _emit(piece)
                        piece = word.lstrip()
                    else:
                        piece += word
                if piece:
                    _emit(piece)
            else:
                _emit(line)
        if current:
            chunks.append('\n'.join(current))
        if len(chunks) > 64:
            raise ValueError('Текст слишком большой для перевода')
        out = []
        try:
            for ch in chunks:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Перевод превысил бюджет времени')
                url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={urllib.parse.quote(str(target_lang), safe='')}&dt=t&q={urllib.parse.quote(ch)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with self._open_url(req, timeout=min(HTTP_TIMEOUT, max(1.0, deadline - time.monotonic()))) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore'))
                    out.append("".join([x[0] for x in data[0] if x[0]]))
            if not out:
                raise RuntimeError('Сервис перевода не вернул результат')
            return "\n".join(out)
        except Exception as e:
            logger.debug(f"Translation error: {e}")
            raise RuntimeError('Не удалось перевести текст') from e

    def get_lyrics(self, track_name: str, artist_name: str = '', duration_ms=0, file_path=None,
                   album_name='', on_update=None, is_current=None, source='', source_id=''):
        video_id = str(source_id or '') if source == 'youtube' else ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            video_id = ''
        upload_id = str(source_id or '')
        upload_source = source if video_id or source == 'soundcloud' and upload_id.isdigit() else ''
        return self._lookup.get(track_name, artist_name, duration_ms, file_path, album_name, on_update, is_current,
                                video_id=video_id, upload_source=upload_source, upload_id=upload_id)
