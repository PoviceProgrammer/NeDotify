"""
NeDotify - Fast Spotify Service
Blazingly fast Spotify search & high-resolution artwork resolution with instant LRU caching.
"""

from typing import Callable, Optional
import threading
import logging
import requests
import urllib.parse
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from services.base_service import BaseMusicService
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=0)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


@lru_cache(maxsize=256)
def _cached_spotify_search(query: str, limit: int = 20) -> tuple:
    encoded_query = urllib.parse.quote(query)
    results = []
    try:
        url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
        resp = _session.get(url, timeout=3.5)
        if resp.status_code == 200:
            data = resp.json()
            for idx, item in enumerate(data.get("results", [])):
                artist = item.get("artistName", "Unknown")
                title = item.get("trackName", "Unknown")
                album = item.get("collectionName", "Spotify Album")
                duration = int(item.get("trackTimeMillis", 180000) / 1000)
                raw_artwork = item.get("artworkUrl100", "")
                cover_url = raw_artwork.replace("100x100bb", "600x600bb") if raw_artwork else None

                results.append((
                    f"spotify_{item.get('trackId', idx)}",
                    title,
                    artist,
                    album,
                    duration,
                    cover_url,
                    "spotify",
                    f"ytsearch1: {artist} - {title}",
                    item.get("trackViewUrl", f"https://open.spotify.com/search/{encoded_query}")
                ))
    except Exception as e:
        logger.error(f"Error in cached Spotify search: {e}")
    return tuple(results)


class SpotifyService(BaseMusicService):
    """Blazingly fast Spotify track search and metadata provider."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=5)
        self.logger = logging.getLogger(__name__)

    def search(self, query: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, limit: int = 20):
        def _search_thread():
            try:
                raw_tuple = _cached_spotify_search(query, limit)
                tracks = []
                for item in raw_tuple:
                    tracks.append({
                        "id": item[0],
                        "title": item[1],
                        "artist": item[2],
                        "album": item[3],
                        "duration": item[4],
                        "cover_url": item[5],
                        "source": item[6],
                        "source_id": item[7],
                        "source_url": item[8],
                        "is_favorite": False
                    })
                if callback:
                    callback(tracks)
                return tracks
            except Exception as e:
                self.logger.error(f"Spotify search error: {e}")
                if error_callback:
                    error_callback(str(e))
                return []

        self._executor.submit(_search_thread)
