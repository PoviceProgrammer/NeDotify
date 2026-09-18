"""
AURA Music - Artist Profile Service

Builds a comprehensive artist profile integrating official Spotify, Last.fm,
and MusicBrainz APIs alongside YouTube Music:
- Full categorized discography: Albums, Singles, EPs, Compilations
- Extended bilingual biography (Russian & English/original)
- High-resolution avatars & cover artwork
- Top playable tracks catalogue with streaming resolution
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

#: Maximum releases per category in profile
MAX_ALBUMS = 120

#: Cached profiles are reused for this long (15 minutes).
PROFILE_TTL = 900

#: Resolved avatar URLs live for a week: channel photos change rarely.
AVATAR_TTL = 7 * 24 * 3600


class ArtistService(BaseMusicService):
    """Resolves an artist name to a full profile using Spotify, Last.fm, MusicBrainz and YouTube Music."""

    def __init__(
        self,
        youtube_service=None,
        settings=None,
        spotify_service=None,
        lastfm_service=None,
        musicbrainz_service=None,
    ):
        super().__init__()
        self.youtube = youtube_service
        self.settings = settings
        self.spotify = spotify_service
        self.lastfm = lastfm_service
        self.musicbrainz = musicbrainz_service

        # Lazily initialize secondary providers when settings are provided
        if self.spotify is None and self.settings is not None:
            try:
                from services.spotify_service import SpotifyService
                self.spotify = SpotifyService(self.settings)
            except Exception as exc:
                logger.debug("Could not initialize SpotifyService: %s", exc)

        if self.lastfm is None and self.settings is not None:
            try:
                from services.lastfm_service import LastFMService
                self.lastfm = LastFMService(self.settings)
            except Exception as exc:
                logger.debug("Could not initialize LastFMService: %s", exc)

        if self.musicbrainz is None and self.settings is not None:
            try:
                from services.musicbrainz_service import MusicBrainzService
                self.musicbrainz = MusicBrainzService(self.settings)
            except Exception as exc:
                logger.debug("Could not initialize MusicBrainzService: %s", exc)

        self._profiles: Dict[str, Any] = {}
        self._profiles_lock = threading.Lock()
        self._avatars: Dict[str, Any] = {}
        self._avatars_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return (
            self._ytmusic() is not None
            or self.spotify is not None
            or self.musicbrainz is not None
            or self.lastfm is not None
        )

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
        elif isinstance(item, (list, tuple)):
            thumbs = item
        else:
            thumbs = []
        if not thumbs:
            return ""
        try:
            valid_thumbs = [t for t in thumbs if isinstance(t, dict)]
            if not valid_thumbs:
                return ""
            best = max(valid_thumbs, key=lambda t: (int(t.get("width") or 0)) * (int(t.get("height") or 0)))
            return best.get("url", "") or ""
        except Exception:
            logger.debug("thumbnail selection failed", exc_info=True)
            for last in reversed(thumbs):
                if isinstance(last, dict) and last.get("url"):
                    return last.get("url")
            return ""

    @staticmethod
    def _artists_label(item: Any, fallback: str = "") -> str:
        fallback_str = str(fallback or "").strip()
        if not isinstance(item, dict):
            return fallback_str
        artists_list = item.get("artists")
        if not isinstance(artists_list, list):
            return fallback_str
        names = [str(a.get("name", "")).strip() for a in artists_list if isinstance(a, dict) and a.get("name")]
        return ", ".join([n for n in names if n]) or fallback_str

    def _normalize_album(self, item: Any, artist_name: str) -> Optional[dict]:
        """Shape one ytmusicapi album/single entry into the app's album dict."""
        if not isinstance(item, dict):
            return None
        browse_id = item.get("browseId") or item.get("playlistId")
        title = item.get("title")
        if not browse_id or not title:
            return None
        title_str = str(title).strip()
        if not title_str:
            return None
        raw_year = item.get("year") or ""
        try:
            year = int(str(raw_year)[:4]) if raw_year else 0
        except (TypeError, ValueError):
            year = 0
        cover = self._best_thumbnail(item)
        fallback_artist = str(artist_name or "").strip()
        raw_type = str(item.get("type") or "Album").strip()
        norm_type = "album"
        if "single" in raw_type.lower():
            norm_type = "single"
        elif "ep" in raw_type.lower():
            norm_type = "ep"
        elif "compilation" in raw_type.lower():
            norm_type = "compilation"

        return {
            "id": "yt_album_" + str(browse_id),
            "source": "youtube",
            "source_id": str(browse_id),
            "title": title_str,
            "album": title_str,
            "artist": self._artists_label(item, fallback_artist),
            "year": year,
            "cover": cover,
            "cover_url": cover,
            "type": norm_type,
            "album_type": norm_type,
        }

    def _collect_albums(self, yt, channel_id: str, artist: Any, artist_name: str) -> List[dict]:
        """Full discography from YouTube Music: inline shelves plus continuations."""
        albums: List[dict] = []
        seen = set()
        artist_dict = artist if isinstance(artist, dict) else {}

        def _absorb(items):
            for raw in items or []:
                album = self._normalize_album(raw, artist_name)
                if album and album["source_id"] not in seen:
                    seen.add(album["source_id"])
                    albums.append(album)

        for shelf_name in ("albums", "singles"):
            shelf = artist_dict.get(shelf_name) or {}
            _absorb(shelf.get("results"))

            params = shelf.get("params")
            if not params or len(albums) >= MAX_ALBUMS:
                continue
            try:
                _absorb(yt.get_artist_albums(channel_id, params, limit=MAX_ALBUMS))
            except Exception:
                logger.debug("get_artist_albums(%s) unavailable for %s", shelf_name, artist_name, exc_info=True)

        if len(albums) < MAX_ALBUMS:
            _absorb(self._search_albums_by_artist(yt, artist_name, seen))

        albums.sort(key=lambda a: (-(a.get("year") or 0), str(a.get("title") or "")))
        return albums[:MAX_ALBUMS]

    def _search_albums_by_artist(self, yt, artist_name: str, seen: set) -> List[dict]:
        """Catalogue search for releases credited to this artist."""
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

    def _translate_bio(self, bio: str) -> Tuple[str, str]:
        """Translates artist bio into Russian using the lyrics translation mechanism."""
        if not bio:
            return ("", "")
        bio_orig = bio.strip()

        cyrillic_chars = sum(1 for c in bio_orig if '\u0400' <= c <= '\u04FF')
        latin_chars = sum(1 for c in bio_orig if 'a' <= c.lower() <= 'z')
        if cyrillic_chars > 0 and cyrillic_chars >= latin_chars:
            return (bio_orig, bio_orig)

        try:
            from services.lyrics_service import LyricsService
            ls = LyricsService(self.settings)
            translated = ls.translate_lyrics(bio_orig, target_lang="ru")
            if translated and translated.strip():
                return (translated.strip(), bio_orig)
        except Exception as exc:
            logger.debug("Bio translation failed for artist: %s", exc)

        return (bio_orig, bio_orig)

    def _collect_tracks(self, yt, channel_id: str, artist: Any, artist_name: str, albums: List[dict] = None) -> List[dict]:
        """The artist's full tracks catalogue, shaped like the app's track dicts."""
        tracks: List[dict] = []
        seen_ids = set()
        seen_titles = set()
        artist_dict = artist if isinstance(artist, dict) else {}

        def _absorb(raw_items, default_album=""):
            for item in raw_items or []:
                if not isinstance(item, dict):
                    continue
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
        songs_shelf = artist_dict.get("songs") or {}
        _absorb(songs_shelf.get("results"))

        # 2. Complete songs playlist via browseId
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

    # --- multi-source providers & cascade ---

    def _fetch_spotify(self, artist_name: str) -> Dict[str, Any]:
        sp = self.spotify
        if not sp or not hasattr(sp, "get_artist_catalog"):
            return {"albums": [], "singles": [], "eps": [], "compilations": [], "tracks": [], "avatar_url": "", "genres": ""}
        try:
            return sp.get_artist_catalog(artist_name) or {}
        except Exception as exc:
            logger.debug("Spotify catalog fetch failed for %s: %s", artist_name, exc)
            return {"albums": [], "singles": [], "eps": [], "compilations": [], "tracks": [], "avatar_url": "", "genres": ""}

    def _fetch_lastfm(self, artist_name: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        lfm = self.lastfm
        if not lfm:
            return ({}, [])
        info: Dict[str, Any] = {}
        albums: List[Dict[str, Any]] = []
        try:
            if hasattr(lfm, "artist_get_info"):
                info = lfm.artist_get_info(artist_name, lang="ru") or {}
        except Exception as exc:
            logger.debug("Last.fm artist_get_info failed for %s: %s", artist_name, exc)
        try:
            if hasattr(lfm, "artist_get_top_albums"):
                albums = lfm.artist_get_top_albums(artist_name, limit=30) or []
        except Exception as exc:
            logger.debug("Last.fm artist_get_top_albums failed for %s: %s", artist_name, exc)
        return (info, albums)

    def _fetch_musicbrainz(self, artist_name: str) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str]]:
        mb = self.musicbrainz
        empty_releases = {"albums": [], "singles": [], "eps": [], "compilations": []}
        empty_bio = {"bio": "", "bio_ru": "", "bio_en": "", "bio_original": "", "avatar_url": "", "source": ""}
        if not mb:
            return (empty_releases, empty_bio)
        try:
            artist_match = mb.search_artist(artist_name)
            mbid = artist_match.get("id") if isinstance(artist_match, dict) else None
            releases = mb.get_artist_release_groups(mbid, artist_name=artist_name, limit=100) if mbid else empty_releases
            bio = mb.get_artist_bio(mbid, artist_name)
            return (releases, bio)
        except Exception as exc:
            logger.debug("MusicBrainz fetch failed for %s: %s", artist_name, exc)
            return (empty_releases, empty_bio)

    def _resolve_bio(self, lfm_info: dict, mb_bio: dict, yt_bio_ru: str, yt_bio_orig: str) -> Tuple[str, str, str, str, str]:
        """Resolves rich bio across Last.fm, Wikipedia/MusicBrainz, and YouTube Music.

        Returns (primary_bio, bio_ru, bio_en, bio_original, bio_source).
        """
        lfm_summary = str(lfm_info.get("bio_summary") or "").strip()
        lfm_content = str(lfm_info.get("bio_content") or "").strip()
        lfm_bio = lfm_content or lfm_summary

        mb_ru = str(mb_bio.get("bio_ru") or "").strip()
        mb_en = str(mb_bio.get("bio_en") or "").strip()
        mb_primary = str(mb_bio.get("bio") or "").strip()

        def _is_cyrillic(text: str) -> bool:
            if not text:
                return False
            cyr = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
            lat = sum(1 for c in text if 'a' <= c.lower() <= 'z')
            return cyr > 0 and cyr >= lat

        bio_ru = ""
        bio_en = ""
        bio_source = ""

        # 1. Russian Biography
        if lfm_bio and _is_cyrillic(lfm_bio):
            bio_ru = lfm_bio
            bio_source = "lastfm"
        elif mb_ru:
            bio_ru = mb_ru
            bio_source = "wikipedia"
        elif yt_bio_ru:
            bio_ru = yt_bio_ru
            bio_source = "youtube"

        # 2. English / Original Biography
        if lfm_bio and not _is_cyrillic(lfm_bio):
            bio_en = lfm_bio
            if not bio_source:
                bio_source = "lastfm"
        elif mb_en:
            bio_en = mb_en
            if not bio_source:
                bio_source = "wikipedia"
        elif yt_bio_orig:
            bio_en = yt_bio_orig
            if not bio_source:
                bio_source = "youtube"

        primary_bio = bio_ru or bio_en or mb_primary or lfm_bio or yt_bio_ru or yt_bio_orig
        bio_original = bio_en or bio_ru or yt_bio_orig

        return (primary_bio, bio_ru, bio_en, bio_original, bio_source or "unknown")

    def _merge_discography(
        self,
        sp_data: dict,
        mb_releases: dict,
        lfm_albums: list,
        yt_albums: list,
        artist_name: str,
    ) -> Dict[str, Any]:
        """Merges and deduplicates releases across Spotify, MusicBrainz, Last.fm, and YouTube."""
        categories: Dict[str, List[Dict[str, Any]]] = {
            "albums": [],
            "singles": [],
            "eps": [],
            "compilations": [],
        }
        seen_keys: Dict[str, Dict[str, Dict[str, Any]]] = {
            "albums": {},
            "singles": {},
            "eps": {},
            "compilations": {},
        }

        # Build YouTube browse_id lookup by normalized title to link direct playback
        yt_lookup = {}
        for yta in yt_albums or []:
            t = (yta.get("title") or "").strip().lower()
            if t:
                yt_lookup[t] = yta.get("source_id")

        import re

        def _clean_title(t: str) -> str:
            s = t.strip()
            s = re.sub(r'(?i)\s*[-–]\s*(single|ep)\s*$', '', s)
            s = re.sub(r'(?i)\s*\((single|ep)\)\s*$', '', s)
            return s.strip()

        def _absorb_entry(cat: str, item: dict):
            raw_title = item.get("title") or item.get("album") or ""
            if not raw_title or str(raw_title).lower() in ("null", "undefined", "(null)"):
                return
            clean_t = _clean_title(raw_title)
            norm_key = clean_t.lower()

            if norm_key in seen_keys[cat]:
                existing = seen_keys[cat][norm_key]
                if (not existing.get("cover") or not existing.get("cover_url")) and (item.get("cover") or item.get("cover_url")):
                    c = item.get("cover") or item.get("cover_url")
                    existing["cover"] = c
                    existing["cover_url"] = c
                if (not existing.get("year")) and item.get("year"):
                    existing["year"] = item["year"]
                if not existing.get("yt_source_id") and norm_key in yt_lookup:
                    existing["yt_source_id"] = yt_lookup[norm_key]
                return

            entry = dict(item)
            entry["title"] = clean_t
            entry["album"] = clean_t
            if not entry.get("artist"):
                entry["artist"] = artist_name
            if norm_key in yt_lookup:
                entry["yt_source_id"] = yt_lookup[norm_key]

            singular_type = cat[:-1] if cat.endswith("s") else cat
            entry["type"] = singular_type
            entry["album_type"] = singular_type

            seen_keys[cat][norm_key] = entry
            categories[cat].append(entry)

        # 1. Ingest Spotify (high quality metadata and artwork)
        for cat in ("albums", "singles", "eps", "compilations"):
            for it in (sp_data.get(cat) or []):
                _absorb_entry(cat, it)

        # 2. Ingest MusicBrainz (canonical release-group discography)
        for cat in ("albums", "singles", "eps", "compilations"):
            for it in (mb_releases.get(cat) or []):
                _absorb_entry(cat, it)

        # 3. Ingest YouTube Music releases
        for yta in yt_albums or []:
            y_type = str(yta.get("album_type") or yta.get("type") or "album").lower()
            target_cat = "albums"
            if "single" in y_type:
                target_cat = "singles"
            elif "ep" in y_type:
                target_cat = "eps"
            elif "compilation" in y_type:
                target_cat = "compilations"
            _absorb_entry(target_cat, yta)

        # 4. Ingest Last.fm top albums (if albums are still low)
        if len(categories["albums"]) < 10:
            for la in lfm_albums or []:
                _absorb_entry("albums", la)

        # Sort each category by year DESC, then title
        for cat in categories:
            categories[cat].sort(key=lambda a: (-(a.get("year") or 0), str(a.get("title") or "")))

        # Build combined all releases list
        all_releases = []
        for cat in ("albums", "singles", "eps", "compilations"):
            all_releases.extend(categories[cat])
        all_releases.sort(key=lambda a: (-(a.get("year") or 0), str(a.get("title") or "")))

        return {
            "albums": categories["albums"][:MAX_ALBUMS],
            "singles": categories["singles"][:MAX_ALBUMS],
            "eps": categories["eps"][:MAX_ALBUMS],
            "compilations": categories["compilations"][:MAX_ALBUMS],
            "all_releases": all_releases[:MAX_ALBUMS * 2],
        }

    # --- public API ---

    def get_avatars(self, names: List[str], callback: Optional[Callable] = None):
        """Resolve avatar image URLs for a batch of artist names in the background."""
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
                if callback:
                    callback(result)
        else:
            BaseMusicService._executor.submit(_task)
        return None

    def get_profile(
        self,
        artist_name: str,
        callback: Optional[Callable] = None,
        error_callback: Optional[Callable] = None,
    ):
        """Resolve a full artist profile: discography (albums/singles/EPs), bio, tracks, artwork."""
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
            try:
                # 1. Fetch Spotify catalog (albums, singles, EPs, tracks, artwork)
                sp_data = self._fetch_spotify(name)

                # 2. Fetch Last.fm metadata & bio
                lfm_info, lfm_albums = self._fetch_lastfm(name)

                # 3. Fetch MusicBrainz release-groups & Wikipedia bio
                mb_releases, mb_bio = self._fetch_musicbrainz(name)

                # 4. Fetch YouTube Music data (channel, audio tracks, fallback)
                yt = self._ytmusic()
                yt_channel_id = ""
                yt_albums = []
                yt_tracks = []
                yt_bio_ru = ""
                yt_bio_orig = ""
                yt_avatar = ""
                subscribers = ""
                views = ""

                if yt is not None:
                    try:
                        yt_channel_id = self._resolve_channel_id(yt, name) or ""
                        if yt_channel_id:
                            yt_artist = yt.get_artist(yt_channel_id)
                            if isinstance(yt_artist, dict):
                                yt_albums = self._collect_albums(yt, yt_channel_id, yt_artist, name)
                                yt_tracks = self._collect_tracks(yt, yt_channel_id, yt_artist, name, yt_albums)
                                yt_bio_ru, yt_bio_orig = self._translate_bio((yt_artist.get("description") or "").strip())
                                yt_avatar = self._best_thumbnail(yt_artist)
                                subscribers = yt_artist.get("subscribers") or ""
                                views = yt_artist.get("views") or ""
                    except Exception as yt_exc:
                        logger.warning("YouTube data fetch failed for %s: %s", name, yt_exc)
                        # If YouTube was the ONLY configured source, re-raise to trigger error callback
                        if not sp_data.get("albums") and not mb_releases.get("albums") and not lfm_info:
                            raise yt_exc

                # 5. Merge discography across all sources
                discography = self._merge_discography(sp_data, mb_releases, lfm_albums, yt_albums, name)

                # 6. Resolve extended biography
                primary_bio, bio_ru, bio_en, bio_orig, bio_src = self._resolve_bio(
                    lfm_info, mb_bio, yt_bio_ru, yt_bio_orig
                )

                # 7. Resolve high-resolution avatar
                avatar_url = (
                    sp_data.get("avatar_url")
                    or mb_bio.get("avatar_url")
                    or lfm_info.get("image")
                    or yt_avatar
                    or ""
                )

                # 8. Merge playable tracks catalogue
                tracks: List[Dict[str, Any]] = []
                seen_track_titles = set()
                for trk in yt_tracks:
                    t_title = (trk.get("title") or "").strip().lower()
                    if t_title and t_title not in seen_track_titles:
                        seen_track_titles.add(t_title)
                        tracks.append(trk)

                if len(tracks) < 25:
                    for trk in sp_data.get("tracks") or []:
                        t_title = (trk.get("title") or "").strip().lower()
                        if t_title and t_title not in seen_track_titles:
                            seen_track_titles.add(t_title)
                            tracks.append(trk)

                has_releases = any(
                    len(discography[k]) > 0
                    for k in ("albums", "singles", "eps", "compilations")
                )

                if not has_releases and not tracks and not primary_bio and not avatar_url:
                    if error_callback:
                        error_callback("Исполнитель не найден: " + name)
                    return

                genres = sp_data.get("genres") or (", ".join(lfm_info.get("tags") or [])) or ""
                if not genres and subscribers:
                    genres = f"{subscribers} подписчиков"
                elif not genres:
                    genres = "Исполнитель"

                primary_source = "spotify" if sp_data.get("albums") else ("musicbrainz" if mb_releases.get("albums") else "youtube")

                profile = {
                    "name": name,
                    "channel_id": yt_channel_id,
                    "avatar_url": avatar_url,
                    "bio": primary_bio,
                    "bio_ru": bio_ru,
                    "bio_en": bio_en,
                    "bio_original": bio_orig,
                    "bio_source": bio_src,
                    "subscribers": subscribers,
                    "listeners": lfm_info.get("listeners", 0),
                    "playcount": lfm_info.get("playcount", 0),
                    "views": views,
                    "genres": genres,
                    "albums": discography["albums"],
                    "singles": discography["singles"],
                    "eps": discography["eps"],
                    "compilations": discography["compilations"],
                    "discography": {
                        "albums": discography["albums"],
                        "singles": discography["singles"],
                        "eps": discography["eps"],
                        "compilations": discography["compilations"],
                    },
                    "all_releases": discography["all_releases"],
                    "tracks": tracks,
                    "source": primary_source,
                }

                self._cache_put(name.lower(), profile)
                if avatar_url:
                    with self._avatars_lock:
                        self._avatars[name.lower()] = (time.time(), avatar_url)

                logger.info(
                    "Artist profile for %r: %d albums, %d singles, %d EPs, %d tracks, bio source %s",
                    profile["name"],
                    len(profile["albums"]),
                    len(profile["singles"]),
                    len(profile["eps"]),
                    len(profile["tracks"]),
                    bio_src,
                )

                if callback:
                    callback(profile)

            except Exception as exc:
                logger.warning("get_profile failed for %s: %s", name, exc, exc_info=True)
                if error_callback:
                    error_callback("Не удалось загрузить профиль: " + type(exc).__name__)

        submit = getattr(BaseMusicService, "submit", None)
        if callable(submit):
            if submit(_task) is None:
                if error_callback:
                    error_callback("Сервис недоступен")
        else:
            BaseMusicService._executor.submit(_task)
        return None
