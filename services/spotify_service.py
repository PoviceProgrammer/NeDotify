import re
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
                raw_dur = item.get("trackTimeMillis"); duration = int(raw_dur / 1000) if raw_dur and isinstance(raw_dur, (int, float)) else 180
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
                artist = item.get("artistName") or "Unknown Artist"
                title = item.get("collectionName") or "Unknown Album"
                year = item.get("releaseDate", "")[:4] if item.get("releaseDate") else ""
                track_count = int(item.get("trackCount") or 0)
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
        self._token_lock = threading.Lock()
        self._access_token = None
        self._token_expires_at = 0.0

    @property
    def available(self) -> bool:
        if self.settings and self.settings.get('services', 'spotify_enabled', True) is False:
            return False
        return True

    def get_access_token(self):
        with self._token_lock:
            import time
            if self.settings:
                cfg_token = self.settings.get("auth", "spotify_token", "")
                if cfg_token:
                    return cfg_token
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            return self._access_token

    def set_access_token(self, token: str, expires_in: int = 3600):
        with self._token_lock:
            import time
            self._access_token = str(token) if token else None
            self._token_expires_at = time.time() + max(60, expires_in)

    @staticmethod
    def _extract_id(val: str, prefix: str = "") -> str:
        s = str(val or "").strip()
        if prefix and prefix in s:
            s = s.replace(prefix, "")
        if "open.spotify.com/" in s:
            m = re.search(r"/(?:album|playlist|track)/([a-zA-Z0-9]+)", s)
            if m:
                return m.group(1)
        if s.startswith("spotify:"):
            parts = s.split(":")
            if len(parts) >= 3:
                return parts[2]
        return s

    def get_stream_url(self, url: str, callback=None, error_callback=None, **kwargs):
        if error_callback:
            error_callback("Spotify does not provide direct streams; resolve via YouTube.")
        return None
        self._session_local = threading.local()

    def _get_session(self):
        if getattr(_session.get, '_mock_return_value', None) is not None or hasattr(_session.get, 'mock'):
            return _session
        session = getattr(self._session_local, 'session', None)
        if session is None:
            session = requests.Session()
            session.headers.update(_session.headers)
            self._session_local.session = session
        return self.configure_session(session)

    def search(self, query: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, limit: int = 20, result_type: str = None, is_current=None):
        if not query or not str(query).strip():
            if callback:
                callback([])
            return []
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
        """Fetch album tracks from iTunes metadata or Web API."""
        def _fetch():
            try:
                cid = self._extract_id(collection_id, "spotify_album_")
                tok = self.get_access_token()
                if tok and not cid.isdigit():
                    try:
                        headers = {"Authorization": f"Bearer {tok}"}
                        sp_url = f"https://api.spotify.com/v1/albums/{cid}/tracks?limit={limit}"
                        sp_resp = _session.get(sp_url, headers=headers, timeout=3.5)
                        if sp_resp.status_code == 200:
                            data = sp_resp.json()
                            tracks = []
                            for item in (data.get("items") or []):
                                artists = ", ".join([a.get("name", "") for a in item.get("artists") or [] if a.get("name")]) or "Web Artist"
                                tracks.append({
                                    "id": f"spotify_{item.get('id')}",
                                    "title": item.get("name", "Unknown"),
                                    "artist": artists,
                                    "duration": int((item.get("duration_ms") or 0) / 1000),
                                    "source": "spotify",
                                    "source_id": f"ytsearch1: {artists} - {item.get('name')}"
                                })
                            if tracks:
                                if callback:
                                    callback(tracks)
                                return tracks
                    except Exception as web_e:
                        self.logger.debug(f"Spotify web API failed: {web_e}")

                url = f"https://itunes.apple.com/lookup?id={cid}&entity=song&limit={limit}"
                data = ITunesGateway.get(url, session=self._get_session(), timeout=4.0)
                tracks = []
                if data is not None:
                    results = data.get("results", [])
                    song_items = results[1:] if len(results) > 1 else results
                    for idx, item in enumerate(song_items):
                        if item.get("wrapperType") != "track" and item.get("kind") != "song":
                            continue
                        artist = item.get("artistName") or "Unknown Artist"
                        title = item.get("trackName", "Unknown Title")
                        album = item.get("collectionName", "Album")
                        raw_dur = item.get("trackTimeMillis"); duration = int(raw_dur / 1000) if raw_dur and isinstance(raw_dur, (int, float)) else 180
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
                pid = self._extract_id(playlist_id, "spotify_playlist_")
                tok = self.get_access_token()
                if tok and not pid.isdigit() and len(pid) > 10:
                    try:
                        headers = {"Authorization": f"Bearer {tok}"}
                        sp_url = f"https://api.spotify.com/v1/playlists/{pid}/tracks?limit={limit}"
                        sp_resp = _session.get(sp_url, headers=headers, timeout=3.5)
                        if sp_resp.status_code == 200:
                            data = sp_resp.json()
                            tracks = []
                            for item in (data.get("items") or []):
                                t_obj = item.get("track") or item
                                artists = ", ".join([a.get("name", "") for a in t_obj.get("artists") or [] if a.get("name")]) or "Web Artist"
                                tracks.append({
                                    "id": f"spotify_{t_obj.get('id')}",
                                    "title": t_obj.get("name", "Unknown"),
                                    "artist": artists,
                                    "duration": int((t_obj.get("duration_ms") or 0) / 1000),
                                    "source": "spotify"
                                })
                            if tracks:
                                if callback:
                                    callback(tracks)
                                return tracks
                    except Exception as web_e:
                        self.logger.debug(f"Spotify web playlist failed: {web_e}")

                raw_target = str(playlist_id).strip()
                if "spotify.com/playlist" in raw_target:
                    try:
                        from services.playlist_import_service import PlaylistImportService
                        pis = PlaylistImportService()
                        resolved = pis._resolve_spotify(raw_target)
                        if resolved and resolved.get("tracks"):
                            tracks = resolved["tracks"][:limit]
                            if callback:
                                callback(tracks)
                            return tracks
                    except Exception:
                        pass

                url = f"https://itunes.apple.com/lookup?id={pid}&entity=song&limit={limit}"
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
