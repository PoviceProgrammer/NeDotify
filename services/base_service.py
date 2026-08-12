"""
NeDotify - Base Music Service
Provides shared caching, background worker configuration, and abstract
service contracts for the different music providers.
"""

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional


class BaseMusicService:
    """Base class for music services providing a shared thread pool and caching."""

    _executor = ThreadPoolExecutor(max_workers=15)
    _cache_lock = threading.RLock()
    _stream_cache: Dict[str, Any] = {}
    _MAX_CACHE_SIZE = 2000
    _search_cache: Dict[str, Dict[str, Any]] = {}
    _SEARCH_CACHE_TTL = 300

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @classmethod
    def get_from_cache(cls, key: str) -> Optional[dict]:
        """Retrieve an item from the stream cache."""
        with cls._cache_lock:
            return cls._stream_cache.get(key)

    @classmethod
    def set_to_cache(cls, key: str, data: dict) -> None:
        """Save an item to the stream cache, respecting the max size."""
        with cls._cache_lock:
            if len(cls._stream_cache) >= cls._MAX_CACHE_SIZE:
                oldest_key = next(iter(cls._stream_cache))
                cls._stream_cache.pop(oldest_key, None)
            cls._stream_cache[key] = data

    @classmethod
    def get_search_cache(cls, key: str) -> Optional[Any]:
        """Retrieve an item from the search cache if it has not expired."""
        with cls._cache_lock:
            entry = cls._search_cache.get(key)
            if entry is None:
                return None
            if time.time() - entry['ts'] > cls._SEARCH_CACHE_TTL:
                cls._search_cache.pop(key, None)
                return None
            return entry['data']

    @classmethod
    def set_search_cache(cls, key: str, data: Any) -> None:
        """Save an item to the search cache together with a timestamp."""
        with cls._cache_lock:
            cls._search_cache[key] = {'data': data, 'ts': time.time()}

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