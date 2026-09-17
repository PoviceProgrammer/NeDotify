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
    if not query or not isinstance(query, str) or not query.strip():
        return ()
    encoded_query = urllib.parse.quote(query.strip())
    results = []
    try:
        url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
        resp = _session.get(url, timeout=3.5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                for idx, item in enumerate(data.get("results") or []):
                    if not isinstance(item, dict):
                        continue
                    artist = item.get("artistName") or "Unknown"
                    title = item.get("trackName") or "Unknown"
                    album = item.get("collectionName") or "Spotify Album"
                    raw_dur = item.get("trackTimeMillis")
                    duration = int(raw_dur / 1000) if raw_dur and isinstance(raw_dur, (int, float)) else 180
                    raw_artwork = item.get("artworkUrl100") or ""
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
                        item.get("trackViewUrl") or f"https://open.spotify.com/search/{encoded_query}"
                    ))
    except Exception as e:
        logger.error(f"Error in cached Spotify search: {e}")
    return tuple(results)


@lru_cache(maxsize=256)
def _cached_spotify_album_search(query: str, limit: int = 20) -> tuple:
    if not query or not isinstance(query, str) or not query.strip():
        return ()
    encoded_query = urllib.parse.quote(query.strip())
    results = []
    try:
        url = f"https://itunes.apple.com/search?term={encoded_query}&entity=album&limit={limit}"
        resp = _session.get(url, timeout=3.5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                for idx, item in enumerate(data.get("results") or []):
                    if not isinstance(item, dict):
                        continue
                    artist = item.get("artistName") or "Unknown Artist"
                    title = item.get("collectionName") or "Unknown Album"
                    rel_date = item.get("releaseDate")
                    year = str(rel_date)[:4] if rel_date else ""
                    raw_count = item.get("trackCount")
                    track_count = int(raw_count) if raw_count and isinstance(raw_count, (int, float)) else 0
                    raw_artwork = item.get("artworkUrl100") or ""
                    cover_url = raw_artwork.replace("100x100bb", "600x600bb") if raw_artwork else None
                    collection_id = str(item.get("collectionId", idx))

                    results.append((
                        f"spotify_album_{collection_id}",
                        title,
                        artist,
                        year,
                        track_count,
                        cover_url,
                        "spotify",
                        collection_id,
                        "album"
                    ))
    except Exception as e:
        logger.error(f"Error in cached Spotify album search: {e}")
    return tuple(results)


class SpotifyService(BaseMusicService):
    """Blazingly fast Spotify track search and metadata provider."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=5)
        self.logger = logging.getLogger(__name__)
        if self.settings:
            proxy = self.settings.get("auth", "proxy_url", "")
            if proxy:
                _session.proxies = {"http": proxy, "https": proxy}

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, limit: int = 20, result_type: str = None):
        def _search_thread():
            try:
                if not query or not isinstance(query, str) or not query.strip():
                    if callback:
                        callback([])
                    return []
                is_album_search = result_type in ("albums", "album")
                if is_album_search:
                    raw_tuple = _cached_spotify_album_search(query, limit)
                    albums = []
                    for item in raw_tuple:
                        albums.append({
                            "id": item[0],
                            "title": item[1],
                            "artist": item[2],
                            "album": item[1],
                            "year": item[3],
                            "track_count": item[4],
                            "cover_url": item[5],
                            "source": item[6],
                            "source_id": item[7],
                            "type": item[8]
                        })
                    if callback:
                        callback(albums)
                    return albums
                else:
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

    def get_album_tracks(self, collection_id: str, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        """Fetch album tracks from iTunes metadata."""
        def _fetch():
            try:
                if not collection_id:
                    if error_callback:
                        error_callback("Invalid collection ID")
                    return []
                cid = str(collection_id).strip()
                if "spotify_album_" in cid:
                    cid = cid.replace("spotify_album_", "")
                url = f"https://itunes.apple.com/lookup?id={cid}&entity=song&limit={limit}"
                resp = _session.get(url, timeout=4.0)
                tracks = []
                if resp.status_code == 200:
                    data = resp.json()
                    results = (data.get("results") or []) if isinstance(data, dict) else []
                    song_items = results[1:] if len(results) > 1 else results
                    for idx, item in enumerate(song_items):
                        if not isinstance(item, dict):
                            continue
                        if item.get("wrapperType") != "track" and item.get("kind") != "song":
                            continue
                        artist = item.get("artistName") or "Unknown Artist"
                        title = item.get("trackName") or "Unknown Title"
                        album = item.get("collectionName") or "Album"
                        raw_dur = item.get("trackTimeMillis")
                        duration = int(raw_dur / 1000) if raw_dur and isinstance(raw_dur, (int, float)) else 180
                        raw_artwork = item.get("artworkUrl100") or ""
                        cover_url = raw_artwork.replace("100x100bb", "600x600bb") if raw_artwork else None

                        tracks.append({
                            "id": f"spotify_{item.get('trackId', idx)}",
                            "title": title,
                            "artist": artist,
                            "album": album,
                            "duration": duration,
                            "cover_url": cover_url,
                            "source": "spotify",
                            "source_id": f"ytsearch1: {artist} - {title}",
                            "source_url": item.get("trackViewUrl", ""),
                            "is_favorite": False
                        })
                if callback:
                    callback(tracks)
                return tracks
            except Exception as e:
                self.logger.error(f"Spotify get_album_tracks error: {e}")
                if error_callback:
                    error_callback(str(e))
                return []

        self._executor.submit(_fetch)
        return None

    def get_playlist_tracks(self, playlist_id, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        def _fetch():
            try:
                if not playlist_id:
                    if error_callback:
                        error_callback("Invalid playlist ID")
                    return []
                pid = str(playlist_id).strip()
                url = f"https://itunes.apple.com/lookup?id={pid}&entity=song&limit={limit}"
                resp = _session.get(url, timeout=4.0)
                tracks = []
                if resp.status_code == 200:
                    data = resp.json()
                    results = (data.get("results") or []) if isinstance(data, dict) else []
                    for item in results:
                        if not isinstance(item, dict):
                            continue
                        if item.get("wrapperType") == "track":
                            artist = item.get("artistName") or "Unknown Artist"
                            title = item.get("trackName") or "Unknown"
                            album = item.get("collectionName") or "Unknown Album"
                            raw_dur = item.get("trackTimeMillis")
                            duration = float(raw_dur) / 1000.0 if raw_dur and isinstance(raw_dur, (int, float)) else 0.0
                            raw_artwork = item.get("artworkUrl100") or ""
                            cover_url = raw_artwork.replace("100x100bb", "600x600bb") if raw_artwork else None
                            tracks.append({
                                "id": f"spotify_{item.get('trackId')}",
                                "title": title,
                                "artist": artist,
                                "album": album,
                                "duration": duration,
                                "cover_url": cover_url,
                                "source": "spotify",
                                "source_id": f"ytsearch1: {artist} - {title}"
                            })
                if callback:
                    callback(tracks)
                return tracks
            except Exception as e:
                if error_callback:
                    error_callback(str(e))
                return []
        self._executor.submit(_fetch)

    def get_stream_url(self, url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, **kwargs):
        """Spotify does not provide direct stream URLs; reports error gracefully."""
        if error_callback:
            error_callback("Spotify does not provide direct streams; resolve via YouTube.")
