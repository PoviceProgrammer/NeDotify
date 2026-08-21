"""
AURA Music - Artist Profile Service

Builds a real artist profile from YouTube Music: avatar, description, subscriber
count, top tracks and the artist's COMPLETE album list.

Before this service existed the artist page was driven by a hardcoded dictionary of
three artists plus a stock photo for everyone else, and the album shelf was derived
from the `album` field of ordinary search hits - a field the YouTube search parser
never populates - so it was empty for effectively every artist.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

#: get_artist() returns only the first page of albums/singles. When YouTube Music
#: offers browse params we follow them to enumerate the full discography, but still
#: cap the result so a prolific artist cannot produce an unbounded payload.
MAX_ALBUMS = 120

#: Cached profiles are reused for this long. Artist pages get re-opened often and a
#: full profile costs two to three YouTube Music round trips.
PROFILE_TTL = 900


class ArtistService(BaseMusicService):
    """Resolves an artist name to a full profile using the YouTube Music catalogue."""

    def __init__(self, youtube_service=None, settings=None):
        super().__init__()
        self.youtube = youtube_service
        self.settings = settings
        self._profiles: Dict[str, Any] = {}
        self._profiles_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._ytmusic() is not None

    def _ytmusic(self):
        """The YTMusic client owned by YouTubeService, or None when unavailable."""
        client = getattr(self.youtube, "_ytmusic", None)
        if client is None:
            logger.debug("ArtistService: YTMusic client unavailable")
        return client

    # --- cache ---

    def _cache_get(self, key: str) -> Optional[dict]:
        with self._profiles_lock:
            entry = self._profiles.get(key)
            if not entry:
                return None
            ts, data = entry
            if time.time() - ts > PROFILE_TTL:
                self._profiles.pop(key, None)
                return None
            return data

    def _cache_put(self, key: str, data: dict) -> None:
        with self._profiles_lock:
            if len(self._profiles) > 64:
                self._profiles.pop(next(iter(self._profiles)), None)
            self._profiles[key] = (time.time(), data)

    # --- helpers ---

    @staticmethod
    def _best_thumbnail(item: Any) -> str:
        """Largest thumbnail URL from a ytmusicapi item, or an empty string."""
        if isinstance(item, dict):
            thumbs = item.get("thumbnails") or []
        else:
            thumbs = item or []
        if not thumbs:
            return ""
        try:
            best = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
            return best.get("url", "") or ""
        except Exception:
            logger.debug("thumbnail selection failed", exc_info=True)
            last = thumbs[-1]
            return last.get("url", "") if isinstance(last, dict) else ""

    @staticmethod
    def _artists_label(item: dict, fallback: str = "") -> str:
        names = [a.get("name", "") for a in (item.get("artists") or []) if a.get("name")]
        return ", ".join(names) or fallback

    def _normalize_album(self, item: dict, artist_name: str) -> Optional[dict]:
        """Shape one ytmusicapi album/single entry into the app's album dict."""
        browse_id = item.get("browseId") or item.get("playlistId")
        title = item.get("title")
        if not browse_id or not title:
            return None
        raw_year = item.get("year") or ""
        try:
            year = int(str(raw_year)[:4]) if raw_year else 0
        except (TypeError, ValueError):
            year = 0
        cover = self._best_thumbnail(item)
        return {
            "id": "yt_album_" + str(browse_id),
            "source": "youtube",
            "source_id": browse_id,
            "title": title,
            "album": title,
            "artist": self._artists_label(item, artist_name),
            "year": year,
            "cover": cover,
            "cover_url": cover,
            "type": "album",
            "album_type": item.get("type") or "Album",
        }

    def _collect_albums(self, yt, channel_id: str, artist: dict, artist_name: str) -> List[dict]:
        """Full discography: the inline shelves plus every continuation page."""
        albums: List[dict] = []
        seen = set()

        def _absorb(items):
            for raw in items or []:
                album = self._normalize_album(raw, artist_name)
                if album and album["source_id"] not in seen:
                    seen.add(album["source_id"])
                    albums.append(album)

        for shelf_name in ("albums", "singles"):
            shelf = artist.get(shelf_name) or {}
            _absorb(shelf.get("results"))

            # A shelf carrying browse params has more entries behind it than the
            # handful inlined in get_artist().
            params = shelf.get("params")
            if not params or len(albums) >= MAX_ALBUMS:
                continue
            try:
                _absorb(yt.get_artist_albums(channel_id, params, limit=MAX_ALBUMS))
            except Exception:
                # ytmusicapi's continuation parser does not match the shape YouTube
                # Music currently returns for these shelves and raises KeyError on
                # musicCarouselShelfRenderer. The catalogue search below recovers the
                # releases the continuation would have added.
                logger.debug("get_artist_albums(%s) unavailable for %s", shelf_name, artist_name, exc_info=True)

        if len(albums) < MAX_ALBUMS:
            _absorb(self._search_albums_by_artist(yt, artist_name, seen))

        albums.sort(key=lambda a: (-(a.get("year") or 0), a.get("title", "")))
        return albums[:MAX_ALBUMS]

    def _search_albums_by_artist(self, yt, artist_name: str, seen: set) -> List[dict]:
        """Catalogue search for releases credited to this artist.

        Used to complete the discography when the artist-shelf continuation is
        unavailable. Results are filtered on the artist credit so a name-similar
        release by somebody else is not attributed to this artist.
        """
        try:
            hits = yt.search(artist_name, filter="albums", limit=40)
        except Exception:
            logger.debug("album search fallback failed for %s", artist_name, exc_info=True)
            return []

        target = artist_name.strip().lower()
        extra = []
        for hit in hits or []:
            credited = self._artists_label(hit).lower()
            if target not in credited and credited not in target:
                continue
            browse_id = hit.get("browseId") or hit.get("playlistId")
            if not browse_id or browse_id in seen:
                continue
            extra.append(hit)
        return extra

    def _collect_top_tracks(self, artist: dict, artist_name: str) -> List[dict]:
        """The artist's top songs shelf, shaped like the app's track dicts."""
        songs = (artist.get("songs") or {}).get("results") or []
        tracks = []
        for item in songs:
            video_id = item.get("videoId")
            if not video_id:
                continue
            album = item.get("album")
            album_name = album.get("name", "") if isinstance(album, dict) else ""
            tracks.append({
                "id": "yt_" + str(video_id),
                "source": "youtube",
                "source_id": video_id,
                "source_url": "https://www.youtube.com/watch?v=" + str(video_id),
                "title": item.get("title", "Unknown Title"),
                "artist": self._artists_label(item, artist_name),
                "album": album_name,
                "duration": item.get("duration_seconds") or 0,
                "cover_url": self._best_thumbnail(item),
            })
        return tracks

    def _resolve_channel_id(self, yt, artist_name: str) -> Optional[str]:
        """browseId of the closest matching artist channel."""
        try:
            hits = yt.search(artist_name, filter="artists", limit=5)
        except Exception:
            logger.warning("Artist search failed for %r", artist_name, exc_info=True)
            return None
        target = artist_name.strip().lower()
        best = None
        for hit in hits or []:
            browse_id = hit.get("browseId")
            if not browse_id:
                continue
            if (hit.get("artist") or "").strip().lower() == target:
                return browse_id
            if best is None:
                best = browse_id
        return best

    # --- public API ---

    def get_profile(self, artist_name: str,
                    callback: Optional[Callable] = None,
                    error_callback: Optional[Callable] = None):
        """Resolve a full artist profile in the background.

        callback receives a dict with name, avatar_url, bio, subscribers, albums and
        tracks. error_callback receives a message string.
        """
        name = (artist_name or "").strip()
        if not name:
            if error_callback:
                error_callback("Имя исполнителя не указано")
            return None

        cached = self._cache_get(name.lower())
        if cached is not None:
            if callback:
                callback(cached)
            return None

        def _task():
            yt = self._ytmusic()
            if yt is None:
                if error_callback:
                    error_callback("YouTube Music недоступен")
                return

            channel_id = self._resolve_channel_id(yt, name)
            if not channel_id:
                if error_callback:
                    error_callback("Исполнитель не найден: " + name)
                return

            try:
                artist = yt.get_artist(channel_id)
            except Exception as exc:
                logger.warning("get_artist(%s) failed: %s", channel_id, exc, exc_info=True)
                if error_callback:
                    error_callback("Не удалось загрузить профиль: " + type(exc).__name__)
                return

            profile = {
                "name": artist.get("name") or name,
                "channel_id": channel_id,
                "avatar_url": self._best_thumbnail(artist),
                "bio": (artist.get("description") or "").strip(),
                "subscribers": artist.get("subscribers") or "",
                "views": artist.get("views") or "",
                "albums": self._collect_albums(yt, channel_id, artist, name),
                "tracks": self._collect_top_tracks(artist, name),
                "source": "youtube",
            }
            self._cache_put(name.lower(), profile)
            logger.info(
                "Artist profile for %r: %d albums, %d top tracks",
                profile["name"], len(profile["albums"]), len(profile["tracks"]),
            )
            if callback:
                callback(profile)

        submit = getattr(BaseMusicService, "submit", None)
        if callable(submit):
            if submit(_task) is None:
                # Pools are shut down (app exiting): report instead of failing silently.
                if error_callback:
                    error_callback("Сервис недоступен")
        else:
            BaseMusicService._executor.submit(_task)
        return None
