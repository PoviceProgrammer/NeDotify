"""
NeDotify - Apple/iTunes metadata catalogue (legacy SpotifyService import).
"""

from typing import Callable, Optional
import threading
import logging
import requests
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from services.base_service import BaseMusicService, normalize_proxy_url
from requests.adapters import HTTPAdapter
from services.itunes_gateway import ITunesGateway

logger = logging.getLogger(__name__)

_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=0)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


def _cached_spotify_search(query: str, limit: int = 20, is_current=None, session=None) -> tuple:
    encoded_query = urllib.parse.quote(query)
    results = []
    try:
        url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit={limit}"
        data = ITunesGateway.get(url, session=session or _session, timeout=3.5, is_current=is_current)
        if data is not None:
            for idx, item in enumerate(data.get("results", [])):
                artist = item.get("artistName", "Unknown")
                title = item.get("trackName", "Unknown")
                album = item.get("collectionName", "Album")
                duration = int((item.get("trackTimeMillis") or 0) / 1000)
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
        raise
    return tuple(results)


def _cached_spotify_album_search(query: str, limit: int = 20, is_current=None, session=None) -> tuple:
    encoded_query = urllib.parse.quote(query)
    results = []
    try:
        url = f"https://itunes.apple.com/search?term={encoded_query}&entity=album&limit={limit}"
        data = ITunesGateway.get(url, session=session or _session, timeout=3.5, is_current=is_current)
        if data is not None:
            for idx, item in enumerate(data.get("results", [])):
                artist = item.get("artistName", "Unknown Artist")
                title = item.get("collectionName", "Unknown Album")
                year = item.get("releaseDate", "")[:4] if item.get("releaseDate") else ""
                track_count = item.get("trackCount", 0)
                raw_artwork = item.get("artworkUrl100", "")
                cover_url = raw_artwork.replace("100x100bb", "600x600bb") if raw_artwork else None
                if not item.get("collectionId"):
                    continue
                collection_id = str(item["collectionId"])

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
        raise
    return tuple(results)


class SpotifyService(BaseMusicService):
    """Apple catalogue metadata; legacy source IDs remain compatible."""
    display_name = "Apple Music / iTunes"

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=5)
        self.logger = logging.getLogger(__name__)
        self._session_local = threading.local()

    def _get_session(self):
        session = getattr(self._session_local, 'session', None)
        if session is None:
            session = requests.Session()
            session.headers.update(_session.headers)
            self._session_local.session = session
        return self.configure_session(session)

    def search(self, query: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, limit: int = 20, result_type: str = None, is_current=None):
        key = f'spotify_search:{query}:{result_type}:{limit}'
        cached = self.get_search_cache(key)
        if cached is not None:
            if callback:
                callback(cached)
            return None
        original_callback = callback
        error_callback = error_callback or (lambda error: original_callback([]) if original_callback else None)
        leader, callback, error_callback = self._join_request((key, id(is_current) if is_current else None), callback, error_callback)
        if not leader:
            return None
        def _search_thread():
            try:
                if is_current and not is_current():
                    raise RuntimeError('Запрос устарел')
                if result_type in ("playlists", "playlist"):
                    if callback:
                        callback([])
                    return []
                is_album_search = result_type in ("albums", "album")
                if is_album_search:
                    raw_tuple = _cached_spotify_album_search(query, limit, is_current, session=self._get_session())
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
                    if albums:
                        self.set_search_cache(key, albums)
                    if callback:
                        callback(albums)
                    return albums
                else:
                    raw_tuple = _cached_spotify_search(query, limit, is_current, session=self._get_session())
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
                    if tracks:
                        self.set_search_cache(key, tracks)
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
                url = f"https://itunes.apple.com/lookup?id={collection_id}&entity=song&limit={limit}"
                data = ITunesGateway.get(url, session=self._get_session(), timeout=4.0)
                tracks = []
                if data is not None:
                    results = data.get("results", [])
                    song_items = results[1:] if len(results) > 1 else results
                    for idx, item in enumerate(song_items):
                        if item.get("wrapperType") != "track" and item.get("kind") != "song":
                            continue
                        artist = item.get("artistName", "Unknown Artist")
                        title = item.get("trackName", "Unknown Title")
                        album = item.get("collectionName", "Album")
                        duration = int((item.get("trackTimeMillis") or 0) / 1000)
                        raw_artwork = item.get("artworkUrl100", "")
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
            except Exception as e:
                self.logger.error(f"Spotify get_album_tracks error: {e}")
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_fetch)
        return None

    def get_playlist_tracks(self, playlist_id, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        def _fetch():
            try:
                # Lookup tracks or fallback
                url = f"https://itunes.apple.com/lookup?id={playlist_id}&entity=song&limit={limit}"
                data = ITunesGateway.get(url, session=self._get_session(), timeout=4.0)
                tracks = []
                if data is not None:
                    for item in data.get("results", []):
                        if item.get("wrapperType") == "track":
                            tracks.append({
                                "id": f"spotify_{item.get('trackId')}",
                                "title": item.get("trackName", "Unknown"),
                                "artist": item.get("artistName", "Unknown Artist"),
                                "album": item.get("collectionName", "Unknown Album"),
                                "duration": float(item.get("trackTimeMillis", 0)) / 1000.0,
                                "cover_url": (item.get("artworkUrl100") or "").replace("100x100bb", "600x600bb"),
                                "source": "spotify",
                                "source_id": f"ytsearch1: {item.get('artistName', '')} - {item.get('trackName', '')}"
                            })
                if callback:
                    callback(tracks)
                return tracks
            except Exception as e:
                if error_callback:
                    error_callback(str(e))
                return []
        self._executor.submit(_fetch)
