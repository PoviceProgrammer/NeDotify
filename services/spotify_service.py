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
        self._token_lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        if self.settings:
            proxy = self.settings.get("auth", "proxy_url", "")
            if proxy:
                _session.proxies = {"http": proxy, "https": proxy}

    @property
    def available(self) -> bool:
        return True

    def get_access_token(self) -> Optional[str]:
        """Retrieve a cached or configured Spotify access token."""
        with self._token_lock:
            import time
            if self.settings:
                cfg_token = self.settings.get("auth", "spotify_token", "")
                if cfg_token:
                    return cfg_token

            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token

            try:
                url = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
                r = _session.get(url, timeout=2.5)
                if r.status_code == 200:
                    data = r.json()
                    tok = data.get("accessToken")
                    exp_ms = data.get("accessTokenExpirationTimestampMs")
                    if tok:
                        self._access_token = tok
                        if exp_ms and isinstance(exp_ms, (int, float)):
                            self._token_expires_at = exp_ms / 1000.0
                        else:
                            self._token_expires_at = time.time() + 3600
                        return self._access_token
            except Exception as e:
                self.logger.debug(f"Anonymous Spotify token fetch failed: {e}")

            return self._access_token

    def set_access_token(self, token: str, expires_in: int = 3600):
        """Programmatically set or refresh Spotify access token."""
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
            import re
            m = re.search(r"/(?:album|playlist|track)/([a-zA-Z0-9]+)", s)
            if m:
                return m.group(1)
        if s.startswith("spotify:"):
            parts = s.split(":")
            if len(parts) >= 3:
                return parts[2]
        return s

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
        """Fetch album tracks from Spotify Web API or iTunes metadata fallback."""
        def _fetch():
            try:
                if not collection_id:
                    if error_callback:
                        error_callback("Invalid collection ID")
                    return []
                cid = self._extract_id(collection_id, "spotify_album_")
                tracks = []

                # Tier 1: Spotify Web API if access token is available and id is alphanumeric
                tok = self.get_access_token()
                if tok and not cid.isdigit():
                    try:
                        headers = {"Authorization": f"Bearer {tok}"}
                        sp_url = f"https://api.spotify.com/v1/albums/{cid}/tracks?limit={limit}"
                        sp_resp = _session.get(sp_url, headers=headers, timeout=3.5)
                        if sp_resp.status_code == 200:
                            sp_data = sp_resp.json()
                            for item in (sp_data.get("items") or []):
                                if not isinstance(item, dict):
                                    continue
                                artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if isinstance(a, dict)) or "Unknown Artist"
                                title = item.get("name") or "Unknown Title"
                                raw_dur = item.get("duration_ms")
                                duration = int(raw_dur / 1000) if raw_dur and isinstance(raw_dur, (int, float)) else 180
                                tracks.append({
                                    "id": f"spotify_{item.get('id')}",
                                    "title": title,
                                    "artist": artists,
                                    "album": "Spotify Album",
                                    "duration": duration,
                                    "cover_url": None,
                                    "source": "spotify",
                                    "source_id": f"ytsearch1: {artists} - {title}",
                                    "source_url": item.get("external_urls", {}).get("spotify", ""),
                                    "is_favorite": False
                                })
                            if tracks:
                                if callback:
                                    callback(tracks)
                                return tracks
                    except Exception as web_err:
                        self.logger.debug(f"Spotify Web API album tracks failed, falling back: {web_err}")

                # Tier 2: iTunes lookup fallback
                url = f"https://itunes.apple.com/lookup?id={cid}&entity=song&limit={limit}"
                resp = _session.get(url, timeout=4.0)
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
        """Fetch playlist tracks from Spotify Web API, iTunes lookup, or web fallback."""
        def _fetch():
            try:
                if not playlist_id:
                    if error_callback:
                        error_callback("Invalid playlist ID")
                    return []
                pid = self._extract_id(playlist_id, "spotify_playlist_")
                tracks = []

                # Tier 1: Spotify Web API if access token is available and id is alphanumeric
                tok = self.get_access_token()
                if tok and not pid.isdigit():
                    try:
                        headers = {"Authorization": f"Bearer {tok}"}
                        sp_url = f"https://api.spotify.com/v1/playlists/{pid}/tracks?limit={limit}"
                        sp_resp = _session.get(sp_url, headers=headers, timeout=3.5)
                        if sp_resp.status_code == 200:
                            sp_data = sp_resp.json()
                            for row in (sp_data.get("items") or []):
                                if not isinstance(row, dict):
                                    continue
                                item = row.get("track")
                                if not isinstance(item, dict):
                                    continue
                                artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if isinstance(a, dict)) or "Unknown Artist"
                                title = item.get("name") or "Unknown"
                                alb_obj = item.get("album") or {}
                                album_name = alb_obj.get("name") or "Unknown Album"
                                covers = alb_obj.get("images") or []
                                cover_url = covers[0].get("url") if covers and isinstance(covers[0], dict) else None
                                raw_dur = item.get("duration_ms")
                                duration = float(raw_dur) / 1000.0 if raw_dur and isinstance(raw_dur, (int, float)) else 0.0
                                tracks.append({
                                    "id": f"spotify_{item.get('id')}",
                                    "title": title,
                                    "artist": artists,
                                    "album": album_name,
                                    "duration": duration,
                                    "cover_url": cover_url,
                                    "source": "spotify",
                                    "source_id": f"ytsearch1: {artists} - {title}"
                                })
                            if tracks:
                                if callback:
                                    callback(tracks)
                                return tracks
                    except Exception as web_err:
                        self.logger.debug(f"Spotify Web API playlist tracks failed: {web_err}")

                # Tier 2: iTunes lookup if numeric
                if pid.isdigit():
                    url = f"https://itunes.apple.com/lookup?id={pid}&entity=song&limit={limit}"
                    resp = _session.get(url, timeout=4.0)
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
                        if tracks:
                            if callback:
                                callback(tracks)
                            return tracks

                # Tier 3: Web metadata fallback for Spotify playlist URLs
                raw_target = str(playlist_id).strip()
                if "spotify.com/playlist" in raw_target or (not pid.isdigit() and len(pid) >= 15):
                    try:
                        from services.playlist_import_service import PlaylistImportService
                        pis = PlaylistImportService()
                        sp_url = raw_target if raw_target.startswith("http") else f"https://open.spotify.com/playlist/{pid}"
                        resolved = pis._resolve_spotify(sp_url)
                        if resolved and resolved.get("tracks"):
                            tracks = resolved["tracks"][:limit]
                            if callback:
                                callback(tracks)
                            return tracks
                    except Exception as imp_err:
                        self.logger.debug(f"PlaylistImportService fallback failed for {raw_target}: {imp_err}")

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
