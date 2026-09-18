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

    def get_artist_catalog(self, artist_name: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Fetch artist discography (albums, singles, EPs, compilations), top tracks, and artwork."""
        name = (artist_name or "").strip()
        if not name:
            empty = {"albums": [], "singles": [], "eps": [], "compilations": [], "tracks": [], "avatar_url": "", "genres": ""}
            if callback:
                callback(empty)
            return empty

        def _task():
            albums = []
            singles = []
            eps = []
            compilations = []
            tracks = []
            avatar_url = ""
            genres = []

            # Tier 1: Spotify Web API if access token is available
            tok = self.get_access_token()
            if tok:
                try:
                    headers = {"Authorization": f"Bearer {tok}"}
                    encoded = urllib.parse.quote(name)
                    search_url = f"https://api.spotify.com/v1/search?q={encoded}&type=artist&limit=5"
                    s_resp = _session.get(search_url, headers=headers, timeout=3.5)
                    if s_resp.status_code == 200:
                        s_data = s_resp.json()
                        art_items = (s_data.get("artists") or {}).get("items") or []
                        target = name.lower()
                        best_art = None
                        for art in art_items:
                            if not isinstance(art, dict):
                                continue
                            if (art.get("name") or "").lower() == target:
                                best_art = art
                                break
                            if best_art is None:
                                best_art = art

                        if best_art:
                            art_id = best_art.get("id")
                            genres = best_art.get("genres") or []
                            art_images = best_art.get("images") or []
                            if art_images and isinstance(art_images, list) and isinstance(art_images[0], dict):
                                avatar_url = art_images[0].get("url") or ""

                            # Fetch releases
                            alb_url = f"https://api.spotify.com/v1/artists/{art_id}/albums?include_groups=album,single,compilation&limit=50"
                            alb_resp = _session.get(alb_url, headers=headers, timeout=3.5)
                            if alb_resp.status_code == 200:
                                alb_data = alb_resp.json()
                                seen_titles = set()
                                for item in (alb_data.get("items") or []):
                                    if not isinstance(item, dict):
                                        continue
                                    item_id = item.get("id")
                                    item_title = (item.get("name") or "").strip()
                                    if not item_id or not item_title:
                                        continue
                                    norm_title = item_title.lower()
                                    if norm_title in seen_titles:
                                        continue
                                    seen_titles.add(norm_title)

                                    album_group = (item.get("album_group") or item.get("album_type") or "album").lower()
                                    total_tracks = int(item.get("total_tracks") or 1)
                                    rel_date = str(item.get("release_date") or "")
                                    year = int(rel_date[:4]) if len(rel_date) >= 4 and rel_date[:4].isdigit() else 0

                                    imgs = item.get("images") or []
                                    cover = imgs[0].get("url") if imgs and isinstance(imgs[0], dict) else ""

                                    is_comp = album_group == "compilation"
                                    has_ep_title = norm_title.endswith(" - ep") or " (ep)" in norm_title or " ep" in norm_title or norm_title.startswith("ep ")
                                    has_single_title = norm_title.endswith(" - single") or " (single)" in norm_title

                                    if is_comp:
                                        rel_type = "compilation"
                                    elif has_ep_title:
                                        rel_type = "ep"
                                    elif has_single_title:
                                        rel_type = "single"
                                    elif album_group == "single":
                                        rel_type = "ep" if 4 <= total_tracks <= 6 else "single"
                                    else:
                                        rel_type = "album"

                                    release_entry = {
                                        "id": f"spotify_album_{item_id}",
                                        "source": "spotify",
                                        "source_id": item_id,
                                        "title": item_title,
                                        "album": item_title,
                                        "artist": name,
                                        "year": year,
                                        "release_date": rel_date,
                                        "track_count": total_tracks,
                                        "cover": cover,
                                        "cover_url": cover,
                                        "type": rel_type,
                                        "album_type": rel_type,
                                    }

                                    if rel_type == "compilation":
                                        compilations.append(release_entry)
                                    elif rel_type == "single":
                                        singles.append(release_entry)
                                    elif rel_type == "ep":
                                        eps.append(release_entry)
                                    else:
                                        albums.append(release_entry)

                            # Fetch top tracks
                            tt_url = f"https://api.spotify.com/v1/artists/{art_id}/top-tracks?market=US"
                            tt_resp = _session.get(tt_url, headers=headers, timeout=3.5)
                            if tt_resp.status_code == 200:
                                tt_data = tt_resp.json()
                                for trk in (tt_data.get("tracks") or []):
                                    if not isinstance(trk, dict):
                                        continue
                                    t_id = trk.get("id")
                                    t_title = trk.get("name") or "Unknown"
                                    dur_ms = trk.get("duration_ms") or 0
                                    alb_obj = trk.get("album") or {}
                                    alb_name = alb_obj.get("name") or "Spotify"
                                    alb_imgs = alb_obj.get("images") or []
                                    c_url = alb_imgs[0].get("url") if alb_imgs and isinstance(alb_imgs[0], dict) else None
                                    tracks.append({
                                        "id": f"spotify_{t_id}",
                                        "title": t_title,
                                        "artist": name,
                                        "album": alb_name,
                                        "duration": int(dur_ms / 1000) if dur_ms else 180,
                                        "cover_url": c_url,
                                        "source": "spotify",
                                        "source_id": f"ytsearch1: {name} - {t_title}",
                                        "popularity": trk.get("popularity", 0),
                                    })
                except Exception as sp_exc:
                    self.logger.debug(f"Spotify Web API artist catalog failed: {sp_exc}")

            # Tier 2: iTunes API album & song search fallback (always runs if albums and singles are empty)
            if not albums and not singles:
                try:
                    encoded_artist = urllib.parse.quote(name)
                    itunes_url = f"https://itunes.apple.com/search?term={encoded_artist}&entity=album&limit=100"
                    resp = _session.get(itunes_url, timeout=4.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        seen_titles = set()
                        target_low = name.lower()
                        for item in (data.get("results") or []):
                            if not isinstance(item, dict):
                                continue
                            artist_credit = (item.get("artistName") or "").lower()
                            if target_low not in artist_credit and artist_credit not in target_low:
                                continue

                            coll_name = (item.get("collectionName") or "").strip()
                            coll_id = str(item.get("collectionId") or "")
                            if not coll_name or not coll_id:
                                continue

                            norm_title = coll_name.lower()
                            if norm_title in seen_titles:
                                continue
                            seen_titles.add(norm_title)

                            track_count = int(item.get("trackCount") or 0)
                            rel_date = str(item.get("releaseDate") or "")
                            year = int(rel_date[:4]) if len(rel_date) >= 4 and rel_date[:4].isdigit() else 0
                            raw_art = item.get("artworkUrl100") or ""
                            cover = raw_art.replace("100x100bb", "600x600bb") if raw_art else ""

                            is_comp = item.get("collectionType") == "Compilation"
                            has_ep_title = norm_title.endswith(" - ep") or " (ep)" in norm_title or " ep" in norm_title or norm_title.startswith("ep ")
                            has_single_title = norm_title.endswith(" - single") or " (single)" in norm_title

                            if is_comp:
                                rel_type = "compilation"
                            elif has_ep_title:
                                rel_type = "ep"
                            elif has_single_title:
                                rel_type = "single"
                            elif 4 <= track_count <= 6:
                                rel_type = "ep"
                            elif 1 <= track_count <= 3:
                                rel_type = "single"
                            else:
                                rel_type = "album"

                            entry = {
                                "id": f"spotify_album_{coll_id}",
                                "source": "spotify",
                                "source_id": coll_id,
                                "title": coll_name,
                                "album": coll_name,
                                "artist": item.get("artistName") or name,
                                "year": year,
                                "release_date": rel_date,
                                "track_count": track_count,
                                "cover": cover,
                                "cover_url": cover,
                                "type": rel_type,
                                "album_type": rel_type,
                            }

                            if rel_type == "compilation":
                                compilations.append(entry)
                            elif rel_type == "single":
                                singles.append(entry)
                            elif rel_type == "ep":
                                eps.append(entry)
                            else:
                                albums.append(entry)
                except Exception as itunes_exc:
                    self.logger.debug(f"iTunes artist album fallback failed: {itunes_exc}")

            # Top tracks fallback via iTunes if tracks are empty
            if not tracks:
                try:
                    encoded_artist = urllib.parse.quote(name)
                    itunes_song_url = f"https://itunes.apple.com/search?term={encoded_artist}&entity=song&limit=30"
                    resp = _session.get(itunes_song_url, timeout=4.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        target_low = name.lower()
                        for item in (data.get("results") or []):
                            if not isinstance(item, dict):
                                continue
                            artist_credit = (item.get("artistName") or "").lower()
                            if target_low not in artist_credit and artist_credit not in target_low:
                                continue
                            track_id = str(item.get("trackId") or "")
                            track_name = (item.get("trackName") or "").strip()
                            if not track_id or not track_name:
                                continue
                            dur_ms = item.get("trackTimeMillis")
                            dur = int(dur_ms / 1000) if dur_ms and isinstance(dur_ms, (int, float)) else 180
                            raw_art = item.get("artworkUrl100") or ""
                            c_url = raw_art.replace("100x100bb", "600x600bb") if raw_art else None
                            tracks.append({
                                "id": f"spotify_{track_id}",
                                "title": track_name,
                                "artist": item.get("artistName") or name,
                                "album": item.get("collectionName") or "Single",
                                "duration": dur,
                                "cover_url": c_url,
                                "source": "spotify",
                                "source_id": f"ytsearch1: {name} - {track_name}",
                            })
                except Exception as it_tr_exc:
                    self.logger.debug(f"iTunes artist song fallback failed: {it_tr_exc}")

            # Sort by year DESC
            albums.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
            singles.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
            eps.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
            compilations.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))

            res = {
                "albums": albums,
                "singles": singles,
                "eps": eps,
                "compilations": compilations,
                "tracks": tracks,
                "avatar_url": avatar_url,
                "genres": ", ".join(genres) if isinstance(genres, list) else str(genres or ""),
            }
            if callback:
                callback(res)
            return res

        if callback:
            self._executor.submit(_task)
            return {}
        return _task()
