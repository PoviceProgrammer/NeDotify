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

#: Resolved avatar URLs live for a week: channel photos change rarely, and the
#: home feed re-requests the same top artists on every load.
AVATAR_TTL = 7 * 24 * 3600


class ArtistService(BaseMusicService):
    """Resolves an artist name to a full profile using the YouTube Music catalogue."""

    def __init__(self, youtube_service=None, settings=None):
        super().__init__()
        self.youtube = youtube_service
        self.settings = settings
        self._profiles: Dict[str, Any] = {}
        self._profiles_lock = threading.Lock()
        self._avatars: Dict[str, Any] = {}
        self._avatars_lock = threading.Lock()

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

    def _translate_bio(self, bio: str) -> tuple[str, str]:
        """Translates artist bio into Russian using the lyrics translation mechanism.
        Returns (bio_ru, bio_original).
        """
        if not bio:
            return ("", "")
        bio_orig = bio.strip()

        # Check if already in Russian (predominantly Cyrillic)
        cyrillic_chars = sum(1 for c in bio_orig if '\u0400' <= c <= '\u04FF')
        latin_chars = sum(1 for c in bio_orig if 'a' <= c.lower() <= 'z')
        if cyrillic_chars > 0 and cyrillic_chars >= latin_chars:
            return (bio_orig, bio_orig)

        try:
            from services.lyrics_service import LyricsService
            ls = LyricsService()
            translated = ls.translate_lyrics(bio_orig, target_lang="ru")
            if translated and translated.strip():
                return (translated.strip(), bio_orig)
        except Exception as exc:
            logger.debug("Bio translation failed for artist: %s", exc)

        return (bio_orig, bio_orig)

    def _collect_tracks(self, yt, channel_id: str, artist: dict, artist_name: str, albums: List[dict] = None) -> List[dict]:
        """The artist's full tracks catalogue, shaped like the app's track dicts."""
        tracks: List[dict] = []
        seen_ids = set()
        seen_titles = set()

        def _absorb(raw_items, default_album=""):
            for item in raw_items or []:
                video_id = item.get("videoId")
                title = (item.get("title") or "").strip()
                if not video_id or not title:
                    continue
                if video_id in seen_ids:
                    continue
                title_key = (title.lower(), self._artists_label(item, artist_name).lower())
                if title_key in seen_titles:
                    continue

                album = item.get("album")
                if isinstance(album, dict):
                    album_name = album.get("name", "") or default_album
                elif isinstance(album, str) and album:
                    album_name = album
                else:
                    album_name = default_album

                dur = item.get("duration_seconds")
                if not dur and item.get("duration"):
                    try:
                        parts = [int(p) for p in str(item["duration"]).split(":")]
                        if len(parts) == 2:
                            dur = parts[0] * 60 + parts[1]
                        elif len(parts) == 3:
                            dur = parts[0] * 3600 + parts[1] * 60 + parts[2]
                    except Exception:
                        dur = 0

                cover = self._best_thumbnail(item)
                seen_ids.add(video_id)
                seen_titles.add(title_key)
                tracks.append({
                    "id": "yt_" + str(video_id),
                    "source": "youtube",
                    "source_id": video_id,
                    "source_url": "https://www.youtube.com/watch?v=" + str(video_id),
                    "title": title,
                    "artist": self._artists_label(item, artist_name),
                    "album": album_name,
                    "duration": dur or 0,
                    "cover_url": cover,
                })

        # 1. Inline top songs shelf
        songs_shelf = artist.get("songs") or {}
        _absorb(songs_shelf.get("results"))

        # 2. Complete songs playlist via browseId if provided by YouTube Music
        browse_id = songs_shelf.get("browseId")
        if browse_id:
            try:
                playlist_data = yt.get_playlist(browse_id, limit=100)
                if playlist_data and playlist_data.get("tracks"):
                    _absorb(playlist_data["tracks"])
            except Exception:
                logger.debug("Failed to get songs playlist %s for %s", browse_id, artist_name, exc_info=True)

        # 3. Catalogue songs search
        if len(tracks) < 50:
            try:
                search_hits = yt.search(artist_name, filter="songs", limit=50)
                target = artist_name.strip().lower()
                filtered_hits = []
                for hit in search_hits or []:
                    credited = self._artists_label(hit).lower()
                    if target in credited or credited in target:
                        filtered_hits.append(hit)
                _absorb(filtered_hits)
            except Exception:
                logger.debug("Catalogue songs search failed for %s", artist_name, exc_info=True)

        # 4. Top albums tracks fallback
        if len(tracks) < 30 and albums:
            for alb in albums[:4]:
                alb_id = alb.get("source_id")
                if not alb_id:
                    continue
                try:
                    alb_data = yt.get_album(alb_id)
                    if alb_data and alb_data.get("tracks"):
                        _absorb(alb_data["tracks"], default_album=alb.get("title", ""))
                except Exception:
                    logger.debug("Failed to get album tracks for %s", alb_id, exc_info=True)
                if len(tracks) >= 60:
                    break

        return tracks

    def _collect_top_tracks(self, artist: dict, artist_name: str) -> List[dict]:
        """Backward compatibility alias for _collect_tracks."""
        return self._collect_tracks(self._ytmusic(), "", artist, artist_name)

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

    def get_avatars(self, names: List[str], callback: Optional[Callable] = None):
        """Resolve avatar image URLs for a batch of artist names in the background.

        Costs ONE YouTube Music artist-search round trip per unknown name (no
        get_artist / discography walks). Results are delivered once via
        ``callback({name: url_or_empty})``; resolved URLs and full profiles are
        reused from cache without any network.
        """
        clean: List[str] = []
        seen = set()
        for n in names or []:
            name = (n or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                clean.append(name)
        if not clean:
            if callback:
                callback({})
            return None

        result: Dict[str, str] = {}
        missing: List[str] = []
        now = time.time()
        for name in clean:
            key = name.lower()
            with self._avatars_lock:
                entry = self._avatars.get(key)
                if entry:
                    ts, url = entry
                    if now - ts <= AVATAR_TTL:
                        result[name] = url
                        continue
                    self._avatars.pop(key, None)
            # A previously fetched full profile already contains the photo.
            profile = self._cache_get(key)
            if profile and profile.get("avatar_url"):
                url = profile["avatar_url"]
                with self._avatars_lock:
                    self._avatars[key] = (now, url)
                result[name] = url
                continue
            missing.append(name)

        if not missing:
            if callback:
                callback(result)
            return None

        def _task():
            yt = self._ytmusic()
            if yt is None:
                if callback:
                    callback(result)
                return
            for name in missing:
                url = ""
                try:
                    hits = yt.search(name, filter="artists", limit=3) or []
                except Exception:
                    logger.warning("Avatar search failed for %r", name, exc_info=True)
                    hits = []
                target = name.lower()
                best_item = None
                for hit in hits:
                    if not isinstance(hit, dict) or not hit.get("thumbnails"):
                        continue
                    if (hit.get("artist") or "").strip().lower() == target:
                        best_item = hit
                        break
                    if best_item is None:
                        best_item = hit
                if best_item is not None:
                    url = self._best_thumbnail(best_item)
                if url:
                    with self._avatars_lock:
                        if len(self._avatars) > 256:
                            self._avatars.pop(next(iter(self._avatars)), None)
                        self._avatars[name.lower()] = (time.time(), url)
                result[name] = url
            if callback:
                callback(result)

        submit = getattr(BaseMusicService, "submit", None)
        if callable(submit):
            if submit(_task) is None:
                # Pools are shut down (app exiting).
                if callback:
                    callback(result)
        else:
            BaseMusicService._executor.submit(_task)
        return None

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

            albums_list = self._collect_albums(yt, channel_id, artist, name)
            tracks_list = self._collect_tracks(yt, channel_id, artist, name, albums_list)
            bio_ru, bio_original = self._translate_bio((artist.get("description") or "").strip())

            profile = {
                "name": artist.get("name") or name,
                "channel_id": channel_id,
                "avatar_url": self._best_thumbnail(artist),
                "bio": bio_ru or bio_original,
                "bio_ru": bio_ru,
                "bio_original": bio_original,
                "bio_en": bio_original,
                "subscribers": artist.get("subscribers") or "",
                "views": artist.get("views") or "",
                "albums": albums_list,
                "tracks": tracks_list,
                "source": "youtube",
            }
            self._cache_put(name.lower(), profile)
            if profile.get("avatar_url"):
                with self._avatars_lock:
                    self._avatars[name.lower()] = (time.time(), profile["avatar_url"])
            logger.info(
                "Artist profile for %r: %d albums, %d tracks, bio length %d",
                profile["name"], len(profile["albums"]), len(profile["tracks"]), len(profile["bio"]),
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
