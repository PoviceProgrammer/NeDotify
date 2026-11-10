"""
NeDotify - Artist Profile Service

Builds a real artist profile from YouTube Music: avatar, description, subscriber
count, top tracks and the artist's COMPLETE album list.

Before this service existed the artist page was driven by a hardcoded dictionary of
three artists plus a stock photo for everyone else, and the album shelf was derived
from the `album` field of ordinary search hits - a field the YouTube search parser
never populates - so it was empty for effectively every artist.
"""

import logging
import copy
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from services.base_service import BaseMusicService
from services.catalog_service import CatalogService, credited_to
from services.itunes_gateway import ITunesGateway
from services.music_matching import artist_matches
import re

logger = logging.getLogger(__name__)

def clean_artist_bio(bio: str) -> str:
    """Clean HTML tags, Wikipedia footnotes, Last.fm tails, and format plain text."""
    if not bio or not isinstance(bio, str):
        return ""
    import html as html_module
    import re
    text = bio.strip()
    text = re.sub(r'<\s*br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'</\s*p\s*>', '\n\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = html_module.unescape(text)
    text = re.sub(r'(?i)\s*read more on last\.fm.*$', '', text)
    text = re.sub(r'(?i)\s*user-contributed text is available under the creative commons.*$', '', text)
    text = re.sub(r'\[(?:\d+|citation needed|note\s*\d+|\*)\]', '', text, flags=re.I)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append('')
                prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False
    return '\n'.join(cleaned_lines).strip()

#: Cached profiles are reused for this long. Artist pages get re-opened often and a
#: full profile costs two to three YouTube Music round trips.
PROFILE_TTL = 900

class ArtistService(BaseMusicService):
    def _safe_get_artist_albums(self, yt, channel_id: str, params: str, deadline=None, is_current=lambda: True) -> List[dict]:
        """Safely fetch continuation albums/singles, protecting against KeyError on musicCarouselShelfRenderer."""
        deadline = deadline or (time.monotonic() + 8)
        try:
            return self.catalog._call(lambda: yt.get_artist_albums(channel_id, params, limit=None), deadline, is_current) or []
        except KeyError:
            pass
        except Exception:
            pass

        try:
            from ytmusicapi.navigation import nav, SINGLE_COLUMN_TAB, SECTION_LIST
            response = self.catalog._call(lambda: yt._send_request('browse', {'browseId': channel_id, 'params': params}), deadline, is_current)
            if not isinstance(response, dict):
                return []
            sections = nav(response, SINGLE_COLUMN_TAB + SECTION_LIST, True) or []
            recovered = []
            for s in sections:
                if not isinstance(s, dict):
                    continue
                carousel = s.get('musicCarouselShelfRenderer') or s.get('musicShelfRenderer')
                if not isinstance(carousel, dict):
                    continue
                header = carousel.get('header', {}).get('musicCarouselShelfBasicHeaderRenderer', {})
                htitle = (header.get('title', {}).get('runs') or [{}])[0].get('text', '').lower()
                if any(w in htitle for w in ('album', 'single', 'ep')) or not htitle:
                    for it in carousel.get('contents', []):
                        two = it.get('musicTwoRowItemRenderer')
                        if not isinstance(two, dict):
                            continue
                        bid = two.get('navigationEndpoint', {}).get('browseEndpoint', {}).get('browseId')
                        title = (two.get('title', {}).get('runs') or [{}])[0].get('text')
                        if not bid or not title:
                            continue
                        thumbs = two.get('thumbnailRenderer', {}).get('musicThumbnailRenderer', {}).get('thumbnail', {}).get('thumbnails', [])
                        sub_runs = two.get('subtitle', {}).get('runs') or []
                        year = sub_runs[-1].get('text') if sub_runs else ''
                        recovered.append({
                            'browseId': bid,
                            'title': title,
                            'thumbnails': thumbs,
                            'year': year,
                            'type': 'single' if 'single' in htitle else 'album'
                        })
            return recovered
        except Exception as exc:
            logger.debug("Failed manual continuation recovery for %s: %s", channel_id, exc)
            return []

    def _resolve_metadata_fallback(self, artist_name: str, avatar_url: str = '', bio: str = '', deadline=None, is_current=lambda: True) -> tuple[str, str]:
        """Cascade fallback for artist avatar and bio using DeezerService, Wikipedia REST, and Last.fm."""
        avatar = avatar_url or ''
        biography = bio or ''

        # 1. Avatar fallback via DeezerService (gives up to 1000x1000 photo)
        if not avatar and (deadline is None or time.monotonic() < deadline) and is_current():
            try:
                from services.deezer_service import DeezerService
                dz = DeezerService(settings=self.settings)
                dz_artist = dz.get_artist(artist_name)
                if dz_artist and dz_artist.get('avatar_url'):
                    avatar = dz_artist['avatar_url']
            except Exception as exc:
                logger.debug("Deezer avatar fallback failed for %s: %s", artist_name, exc)

        # 2. Bio and avatar fallback via Wikipedia REST API
        if (not biography or not avatar) and (deadline is None or time.monotonic() < deadline) and is_current():
            import urllib.request
            import urllib.parse
            import json
            for lang in ('ru', 'en'):
                if biography and avatar:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                try:
                    quoted = urllib.parse.quote(artist_name)
                    url = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quoted}'
                    req = urllib.request.Request(url, headers={'User-Agent': 'NeDotify/1.0'})
                    timeout = max(0.5, (deadline - time.monotonic())) if deadline else 3.0
                    with urllib.request.urlopen(req, timeout=min(3.0, timeout)) as resp:
                        if resp.status == 200:
                            wdata = json.loads(resp.read().decode('utf-8'))
                            if wdata.get('type') != 'disambiguation':
                                extract = wdata.get('extract')
                                if not biography and extract:
                                    biography = clean_artist_bio(extract)
                                if not avatar:
                                    avatar = wdata.get('originalimage', {}).get('source') or wdata.get('thumbnail', {}).get('source') or ''
                except Exception as exc:
                    logger.debug("Wikipedia (%s) fallback failed for %s: %s", lang, artist_name, exc)

        # 3. Bio fallback via Last.fm
        if not biography and (deadline is None or time.monotonic() < deadline) and is_current():
            try:
                from services.lastfm_service import LastFMService
                lastfm = LastFMService(settings=self.settings)
                if lastfm.has_credentials():
                    info = lastfm._get('artist.getInfo', artist=artist_name)
                    l_bio = (info.get('artist', {}).get('bio', {}).get('content') or info.get('artist', {}).get('bio', {}).get('summary') or '')
                    if l_bio:
                        biography = clean_artist_bio(l_bio)
            except Exception as exc:
                logger.debug("Last.fm bio fallback failed for %s: %s", artist_name, exc)

        return (avatar or '', biography or '')

    """Resolves an artist name to a full profile using the YouTube Music catalogue."""

    def __init__(self, youtube_service=None, settings=None):
        super().__init__()
        self.youtube = youtube_service
        self.settings = settings
        self.catalog = CatalogService(youtube_service, settings)
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

    def _normalize_album(self, item: dict, artist_name: str, channel_id='') -> Optional[dict]:
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
            "artists": item.get("artists") or [],
            "artist_channel_id": channel_id,
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

    def _album_shelf_page(self, yt, channel_id, params, continuation, deadline, is_current):
        """Read one provider page so a deadline never discards previous pages."""
        if not callable(getattr(yt, '_send_request', None)):
            # Other catalogue adapters can implement the high-level operation.
            items = self.catalog._call(lambda: yt.get_artist_albums(channel_id, params, limit=None), deadline, is_current)
            return items or [], None
        body = {'browseId': channel_id, 'params': params}
        raw = self.catalog._call(lambda: yt._send_request('browse', body, continuation or ''), deadline, is_current)

        def shelf(node):
            if isinstance(node, dict):
                for key in ('gridRenderer', 'gridContinuation', 'musicCarouselShelfRenderer', 'musicShelfRenderer'):
                    if isinstance(node.get(key), dict):
                        return node[key]
                for value in node.values():
                    found = shelf(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = shelf(value)
                    if found is not None:
                        return found
            return None

        page = shelf(raw)
        if page is None:
            raise ValueError('Каталог не содержит страницу релизов')
        from ytmusicapi.parsers.library import parse_albums
        from ytmusicapi.continuations import get_continuation_params
        items = parse_albums(page.get('items') or page.get('contents') or [])
        next_page = get_continuation_params(page) if page.get('continuations') else None
        return items, next_page

    def _collect_albums(self, yt, channel_id: str, artist: dict, artist_name: str, deadline=None, is_current=lambda: True,
                        catalog_state=None, existing_albums=None) -> List[dict]:
        """Full discography: the inline shelves plus every continuation page."""
        deadline = deadline or time.monotonic() + 8
        albums: List[dict] = list(existing_albums or [])
        seen = {album['source_id'] for album in albums}
        state = catalog_state if catalog_state is not None else {}

        def _absorb(items):
            for raw in items or []:
                if raw.get("artists") and not credited_to(raw, artist_name, channel_id, self.settings):
                    continue
                album = self._normalize_album(raw, artist_name, channel_id)
                if album and album["source_id"] not in seen:
                    seen.add(album["source_id"])
                    albums.append(album)

        if not state.get('initialized'):
            state.update(initialized=True, pending=[])
            for shelf_name in ('albums', 'singles'):
                inline = artist.get(shelf_name) or {}
                _absorb(inline.get('results'))
                if inline.get('params'):
                    state['pending'].append({'params': inline['params'], 'continuation': None, 'visited': []})
        state['retryable'] = False
        while state['pending'] and is_current() and time.monotonic() < deadline:
            pending = state['pending'][0]
            try:
                items, next_page = self._album_shelf_page(yt, channel_id, pending['params'], pending['continuation'], deadline, is_current)
                _absorb(items)
                if next_page and next_page in pending['visited']:
                    raise ValueError('Каталог повторил страницу продолжения')
                if next_page:
                    pending['visited'].append(next_page)
                    pending['continuation'] = next_page
                else:
                    state['pending'].pop(0)
            except Exception:
                state['retryable'] = True
                break

        if not existing_albums and not state['pending']:
            _absorb(self._search_albums_by_artist(yt, artist_name, seen, channel_id, deadline, is_current))
        # Append-only order keeps album offsets stable when a later request
        # resumes a shelf. Sorting again would skip or repeat completed albums.
        return albums

    def _search_albums_by_artist(self, yt, artist_name: str, seen: set, channel_id='', deadline=None, is_current=lambda: True) -> List[dict]:
        """Catalogue search for releases credited to this artist.

        Used to complete the discography when the artist-shelf continuation is
        unavailable. Results are filtered on the artist credit so a name-similar
        release by somebody else is not attributed to this artist.
        """
        try:
            hits = self.catalog._call(lambda: yt.search(artist_name, filter="albums", limit=40), deadline or time.monotonic()+8, is_current)
        except Exception:
            logger.debug("album search fallback failed for %s", artist_name, exc_info=True)
            return []

        target = artist_name.strip().lower()
        extra = []
        for hit in hits or []:
            credited = self._artists_label(hit).lower()
            if not credited_to(hit, artist_name, channel_id, self.settings):
                continue
            browse_id = hit.get("browseId") or hit.get("playlistId")
            if not browse_id or browse_id in seen:
                continue
            extra.append(hit)
        return extra

    def _translate_bio(self, bio: str, deadline=None) -> tuple[str, str]:
        """Translates artist bio into Russian using the lyrics translation mechanism.
        Returns (bio_ru, bio_original); a failed or refused translation returns
        the original text for both, which the UI renders as a single language.
        """
        if not bio:
            return ("", "")
        bio_orig = bio.strip()

        # Check if already in Russian (predominantly Cyrillic)
        cyrillic_chars = sum(1 for c in bio_orig if '\u0400' <= c <= '\u04FF')
        latin_chars = sum(1 for c in bio_orig if 'a' <= c.lower() <= 'z')
        if cyrillic_chars > 0 and cyrillic_chars >= latin_chars:
            return (bio_orig, bio_orig)

        if deadline is not None and time.monotonic() >= deadline:
            logger.debug("Bio translation skipped for %d remaining chars: deadline reached", len(bio_orig))
            return (bio_orig, bio_orig)

        try:
            from services.lyrics_service import LyricsService
            ls = LyricsService(settings=self.settings)
            translated = ls.translate_lyrics(bio_orig, target_lang="ru")
            if translated and translated.strip():
                return (translated.strip(), bio_orig)
        except Exception as exc:
            logger.debug("Bio translation failed for artist: %s", exc)

        return (bio_orig, bio_orig)

    @staticmethod
    def _is_remix(title):
        return bool(re.search(r"(?:[\[(]\s*[^)\]]*\b(?:remix|rmx|bootleg|rework|ремикс)\b[^)\]]*[)\]]|\s[-–—]\s.*\b(?:remix|rmx|ремикс)\b|\s+(?:remix|rmx|ремикс)\s*$)", title, re.I))

    def _youtube_song(self, item, artist_name, channel_id, default_album=''):
        if not isinstance(item, dict):
            return None
        sid, title = item.get('videoId'), str(item.get('title') or '').strip()
        if not sid or not title:
            return None
        if item.get('artists') and not credited_to(item, artist_name, channel_id, self.settings):
            return None
        album = item.get('album')
        album = album.get('name') if isinstance(album, dict) else album
        duration = item.get('duration_seconds') or 0
        if not duration and item.get('duration'):
            try:
                for part in str(item['duration']).split(':'):
                    duration = duration * 60 + int(part)
            except (ValueError, TypeError):
                duration = 0
        return {'artists':item.get('artists') or [], 'id':'yt_'+str(sid),
                'source':'youtube','source_id':sid,'source_url':'https://www.youtube.com/watch?v='+str(sid),
                'title':title,'artist':self._artists_label(item,artist_name),
                'album':album or default_album,'duration':duration,'cover_url':self._best_thumbnail(item)}

    def _itunes_song(self, item, sid):
        if (item.get('wrapperType') != 'track' or item.get('kind') != 'song'
                or not item.get('trackId') or str(item.get('artistId')) != sid
                or not item.get('trackName')):
            return None
        artist, title = item.get('artistName') or '', item['trackName']
        return {'id':'spotify_'+str(item['trackId']), 'source':'spotify',
                'source_id':f'ytsearch1: {artist} - {title}', 'title':title,'artist':artist,
                'album':item.get('collectionName') or '', 'duration':(item.get('trackTimeMillis') or 0)/1000,
                'cover_url':self._itunes_artwork(item.get('artworkUrl100'))}

    def get_tracks_page(self, artist_ref, offset=0, is_current=lambda: True):
        """Read a bounded batch of album tracklists for a confirmed catalogue ID.

        The cursor counts completed albums, so a failed album can be retried
        without dropping any already returned recordings or skipping a page.
        """
        source, sid = artist_ref.get('source'), str(artist_ref.get('source_id') or '')
        if source not in ('youtube','itunes','deezer') or not sid or (source in ('itunes','deezer') and not sid.isdigit()):
            raise ValueError('Неверный ID исполнителя')
        if isinstance(offset,bool) or not isinstance(offset,int) or offset < 0:
            raise ValueError('Неверная позиция каталога')
        deadline = time.monotonic()+8
        profile = copy.deepcopy(self._cache_get(source+':'+sid))
        if not profile:
            resolved=self.catalog.resolve_artist(artist_ref.get('name') or '',artist_ref,is_current,deadline)
            if resolved.get('status')!='found':
                raise ValueError('Исполнитель не подтверждён')
            raw=resolved.get('profile_data') or {}
            name=resolved['name']
            state = {}
            albums=(self._collect_albums(self._ytmusic(),sid,raw,name,deadline,is_current, catalog_state=state)
                    if source=='youtube' else self._collect_itunes_albums(raw,sid,name) if source=='itunes' else [])
            if source == 'deezer':
                state = {'next_index': 0, 'track_offsets': {}}
            profile = {'name': name, 'albums': albums, 'catalog_state': state,
                       'catalog_source_limited': source == 'itunes' and len(albums) >= 200}
        else:
            name, albums = profile['name'],profile.get('albums') or []
            state = profile.get('catalog_state') or {}
            if source == 'youtube' and state.get('pending'):
                albums = self._collect_albums(self._ytmusic(), sid, {}, name, deadline, is_current,
                                              catalog_state=state, existing_albums=albums)
                profile.update(albums=albums, catalog_state=state)
        if source == 'deezer' and offset >= len(albums) and state.get('next_index', 0) is not None:
            state.setdefault('next_index', 0)
            state.setdefault('track_offsets', {})
            try:
                raw = self.catalog._call(lambda: self.catalog._deezer_get('artist/' + sid + '/albums',
                    index=state['next_index'], limit=100), deadline, is_current)
                items = raw.get('data') or []
                if raw.get('next') and not items:
                    raise ValueError('Deezer повторил пустую страницу релизов')
                seen_albums = {album['source_id'] for album in albums}
                for item in items:
                    album_id = str(item.get('id') or '')
                    if not album_id.isdigit() or album_id in seen_albums:
                        continue
                    seen_albums.add(album_id)
                    albums.append({'id':'deezer_album_'+album_id, 'source':'deezer', 'source_id':album_id,
                                   'title':item.get('title') or '', 'artist':name,
                                   'year':str(item.get('release_date') or '')[:4],
                                   'cover_url':item.get('cover_xl') or item.get('cover_big') or item.get('cover') or '',
                                   'type':item.get('record_type') or 'album'})
                state['next_index'] = state['next_index'] + len(items) if raw.get('next') else None
                state['retryable'] = False
            except Exception:
                state['retryable'] = True
            profile.update(albums=albums, catalog_state=state)
        cursor=offset
        tracks=[]
        seen=set()
        retryable=False
        yt=self._ytmusic() if source=='youtube' else None
        for album in albums[offset:offset+3]:
            if not is_current():
                return {'tracks':[],'next_offset':offset,'has_more':True,'cancelled':True}
            try:
                album_id=str(album['source_id'])
                if source=='youtube':
                    raw=self.catalog._call(lambda:yt.get_album(album_id),deadline,is_current)
                    items=raw.get('tracks') or []
                elif source == 'itunes':
                    raw=ITunesGateway.get(f'https://itunes.apple.com/lookup?id={album_id}&entity=song&limit=200',
                        deadline=deadline,is_current=is_current,settings=self.settings)
                    items=raw.get('results') or []
                else:
                    from services.deezer_service import DeezerService
                    converter = DeezerService(settings=self.settings)
                    track_offsets = state.setdefault('track_offsets', {})
                    track_index = track_offsets.get(album_id, 0)
                    while True:
                        raw = self.catalog._call(lambda: self.catalog._deezer_get('album/' + album_id + '/tracks',
                            index=track_index, limit=100), deadline, is_current)
                        items = raw.get('data') or []
                        if raw.get('next') and not items:
                            raise ValueError('Deezer повторил пустую страницу треков')
                        for item in items:
                            ids = {str((item.get('artist') or {}).get('id'))}
                            ids.update(str(person.get('id')) for person in item.get('contributors') or [] if isinstance(person, dict))
                            if sid not in ids:
                                continue
                            track = converter._track(item)
                            if track['id'] not in seen:
                                seen.add(track['id']); tracks.append(track)
                        if not raw.get('next'):
                            track_offsets.pop(album_id, None)
                            break
                        track_index += len(items)
                        track_offsets[album_id] = track_index
                    cursor += 1
                    continue
                for item in items:
                    track=(self._youtube_song(item,name,sid,album.get('title',''))
                           if source=='youtube' else self._itunes_song(item,sid))
                    if track and track['id'] not in seen:
                        seen.add(track['id']);tracks.append(track)
                cursor+=1
            except Exception:
                retryable=True
                break
        if not is_current():
            return {'tracks':[],'next_offset':offset,'has_more':True,'cancelled':True}
        pending = bool(state.get('pending')) or (source == 'deezer' and state.get('next_index') is not None)
        has_more = cursor < len(albums) or pending
        profile['catalog_partial'] = has_more
        self._cache_put(source+':'+sid, profile)
        return {'tracks':tracks,'next_offset':cursor,'has_more':has_more,
                'retryable':retryable or bool(state.get('retryable')), 'catalog_partial':has_more,
                'catalog_source_limited':bool(profile.get('catalog_source_limited')), 'albums':albums}

    def _collect_tracks(self, yt, channel_id: str, artist: dict, artist_name: str, albums: List[dict] = None, deadline=None, is_current=lambda: True) -> List[dict]:
        """The artist's full tracks catalogue, shaped like the app's track dicts."""
        deadline = deadline or time.monotonic() + 8
        tracks: List[dict] = []
        seen_ids = set()

        def _absorb(raw_items, default_album=""):
            for item in raw_items or []:
                track = self._youtube_song(item, artist_name, channel_id, default_album)
                if not track or track['source_id'] in seen_ids:
                    continue
                seen_ids.add(track['source_id'])
                tracks.append(track)

        # 1. Inline top songs shelf
        songs_shelf = artist.get("songs") or {}
        _absorb(songs_shelf.get("results"))

        # 2. Complete songs playlist via browseId if provided by YouTube Music
        browse_id = songs_shelf.get("browseId")
        if browse_id:
            try:
                playlist_data = self.catalog._call(lambda: yt.get_playlist(browse_id, limit=None), deadline, is_current)
                if playlist_data and playlist_data.get("tracks"):
                    _absorb(playlist_data["tracks"])
            except Exception:
                logger.debug("Failed to get songs playlist %s for %s", browse_id, artist_name, exc_info=True)

        # 3. Catalogue songs search
        if len(tracks) < 50:
            try:
                search_hits = self.catalog._call(lambda: yt.search(artist_name, filter="songs", limit=50), deadline, is_current)
                target = artist_name.strip().lower()
                filtered_hits = []
                for hit in search_hits or []:
                    credited = self._artists_label(hit).lower()
                    if credited_to(hit, artist_name, channel_id, self.settings):
                        filtered_hits.append(hit)
                _absorb(filtered_hits)
            except Exception:
                logger.debug("Catalogue songs search failed for %s", artist_name, exc_info=True)

        # 4. Top albums tracks fallback
        if len(tracks) < 30 and albums:
            for alb in albums[:4]:
                if not is_current() or time.monotonic() >= deadline:
                    break
                alb_id = alb.get("source_id")
                if not alb_id:
                    continue
                try:
                    alb_data = self.catalog._call(lambda: yt.get_album(alb_id), deadline, is_current)
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

    def _resolve_channel_id(self, yt, artist_name):
        resolved = self.catalog.resolve_artist(artist_name)
        return resolved.get('source_id') if resolved.get('status') == 'found' and resolved.get('source') == 'youtube' else None

    # --- iTunes profiles (S4-002/S4-014) -------------------------------------

    @staticmethod
    def _itunes_artwork(url: str) -> str:
        """The 600x600 variant of an iTunes artwork URL (S4-014)."""
        return str(url or '').replace('100x100bb', '600x600bb')

    def _collect_itunes_albums(self, raw: dict, sid: str, artist_name: str) -> List[dict]:
        """Shape the artist lookup's collections, honouring the release type.

        S4-014: covers arrive as artworkUrl100 (upscaled here to 600x600) and
        singles/EPs carried the generic 'album' type - the collectionType from
        iTunes is surfaced instead.
        """
        albums: List[dict] = []
        seen = set()
        for a in raw.get('results', []):
            if a.get('wrapperType') != 'collection' or str(a.get('artistId')) != sid or not a.get('collectionId'):
                continue
            if str(a['collectionId']) in seen:
                continue
            seen.add(str(a['collectionId']))
            collection_type = str(a.get('collectionType') or 'Album').strip()
            release_type = 'single' if collection_type.lower() == 'single' else 'album'
            albums.append({
                'id': 'spotify_album_' + str(a['collectionId']), 'source': 'spotify',
                'source_id': str(a['collectionId']),
                'title': a.get('collectionName'), 'artist': a.get('artistName') or artist_name,
                'type': release_type, 'album_type': collection_type,
                'year': (a.get('releaseDate') or '')[:4],
                'cover_url': self._itunes_artwork(a.get('artworkUrl100')),
            })
        albums.sort(key=lambda alb: (-(int(alb.get('year') or 0)), alb.get('title') or ''))
        return albums

    def _build_itunes_profile(self, raw: dict, sid: str, actual_name: str,
                              deadline=None, is_current=lambda: True) -> dict:
        """Assemble the non-youtube (iTunes) profile (S4-002/S4-014)."""
        albums = self._collect_itunes_albums(raw, sid, actual_name)
        tracks = self._collect_itunes_tracks(sid, deadline, is_current)
        genres = next((h.get('primaryGenreName', '') for h in raw.get('results', [])
                       if h.get('wrapperType') == 'artist' and str(h.get('artistId')) == sid), '')
        avatar_url, bio_text = self._resolve_metadata_fallback(actual_name, deadline=deadline, is_current=is_current)
        bio_ru, bio_original = self._translate_bio(bio_text, deadline=deadline) if bio_text and (deadline is None or time.monotonic() < deadline) else (bio_text, bio_text)
        return {'status': 'found', 'verified': True, 'name': actual_name, 'source': 'itunes',
                'source_id': sid, 'albums': albums, 'tracks': tracks, 'tracks_has_more':bool(albums),
                'catalog_source_limited':len(albums) >= 200,
                'catalog_partial':bool(albums),
                'avatar_url': avatar_url, 'bio': bio_ru or bio_original, 'bio_ru': bio_ru,
                'bio_original': bio_original, 'bio_en': bio_original, 'genres': genres}

    def _collect_itunes_tracks(self, sid: str, deadline=None, is_current=lambda: True) -> List[dict]:
        """The artist's songs via an entity=song lookup (S4-002).

        Pre-fix the iTunes profile always shipped `tracks: []` - the page read
        "artist found, but no tracks" and the Play button was a dead end. Only
        songs credited to the artist's own artistId are collected (features and
        compilations credit somebody else).
        """
        if not str(sid).isdigit():
            return []
        try:
            url = f'https://itunes.apple.com/lookup?id={sid}&entity=song&limit=200'
            data = ITunesGateway.get(url, deadline=deadline or (time.monotonic() + 8),
                                     is_current=is_current, settings=self.settings)
        except Exception:
            logger.debug("iTunes song lookup failed for artist %s", sid, exc_info=True)
            return []
        tracks: List[dict] = []
        for item in data.get('results', []):
            track=self._itunes_song(item,sid)
            if track and all(existing['id'] != track['id'] for existing in tracks): tracks.append(track)
        return tracks

    # --- public API ---

    def get_avatars(self, names, callback=None, is_current=lambda: True, hints=None,
                    source_tracks=None, metadata_loader=None):
        def task():
            mapping = {}
            for name in list(dict.fromkeys(n.strip() for n in names or [] if isinstance(n, str) and n.strip()))[:30]:
                if not is_current():
                    break
                # Each artist gets a budget; a slow first lookup must not starve
                # every later card. Publish photos as they become available.
                deadline = time.monotonic() + 8
                try:
                    hint = (hints or {}).get(name)
                    options = {'is_current': is_current, '_deadline': deadline}
                    if hint:
                        options['artist_ref'] = {'hint_track': hint}
                    resolved = self.catalog.resolve_artist(name, **options)
                    if resolved.get('status') in ('not_found', 'ambiguous'):
                        from services.music_matching import credits
                        people = credits(name)
                        if len(people) > 1 and not any(c.get('matching_track') for c in resolved.get('candidates', [])):
                            resolved = self.catalog.resolve_artist(people[0], **options)
                    if resolved.get('status') == 'ambiguous' and hint:
                        from services.music_matching import normalize
                        photos = [candidate for candidate in resolved.get('candidates', [])
                                  if candidate.get('avatar_url')
                                  and normalize(candidate.get('matching_track')) == normalize(hint)]
                        if len(photos) == 1:
                            resolved = {'status': 'found', 'name': photos[0]['name'],
                                        'profile_data': {'picture_xl': photos[0]['avatar_url']}}
                    if resolved.get('status') == 'ambiguous' and not hint:
                        # Cross-catalogue duplicates are not multiple YouTube
                        # channels. A single exact channel can supply its own
                        # photo without inventing an iTunes identity binding.
                        from services.music_matching import normalize
                        channels = [candidate for candidate in resolved.get('candidates', [])
                                    if candidate.get('source') == 'youtube'
                                    and normalize(candidate.get('name')) == normalize(name)]
                        if len(channels) == 1:
                            resolved = self.catalog.resolve_artist(name, channels[0],
                                is_current=is_current, _deadline=deadline)
                except Exception as exc:
                    logger.debug('Artist avatar lookup failed: %s', type(exc).__name__)
                    continue
                raw = resolved.get('profile_data') or {}
                avatar = ''
                if resolved.get('status') == 'found':
                    avatar = (self._best_thumbnail(raw) or raw.get('picture_xl')
                              or raw.get('picture_big') or raw.get('picture')
                              or self._itunes_artwork(raw.get('artworkUrl100')))
                    if not avatar and time.monotonic() < deadline:
                        avatar, _ = self._resolve_metadata_fallback(
                            resolved.get('name') or name, bio=' ', deadline=deadline, is_current=is_current)
                mapping[name] = avatar
                if not avatar and metadata_loader and is_current():
                    from services.music_matching import normalize, artist_matches
                    for track in (source_tracks or {}).get(name, [])[:3]:
                        if not is_current():
                            break
                        try:
                            metadata = metadata_loader(track) or {}
                            if (artist_matches(name, metadata.get('artist', ''), self.settings)
                                    and normalize(metadata.get('title')) == normalize(track.get('title'))):
                                avatar = metadata.get('artist_avatar_url') or ''
                                if avatar:
                                    mapping[name] = avatar
                                    break
                        except Exception as exc:
                            logger.debug('Source avatar lookup failed: %s', type(exc).__name__)
                if callback and avatar and is_current():
                    callback({name: avatar})
            if callback and not mapping:
                callback(mapping)
        if self.submit(task) is None and callback:
            callback({})

    def get_profile(self, artist_name, callback=None, error_callback=None, artist_ref=None, is_current=lambda: True):
        name = str(artist_name or '').strip()
        def task():
            deadline = time.monotonic() + 8
            resolved = self.catalog.resolve_artist(name, artist_ref, is_current, deadline)
            if not is_current():
                return
            status = resolved.get('status')
            if status != 'found':
                resolved['artist'] = name
                target = callback if status == 'ambiguous' else error_callback
                if target:
                    target(resolved)
                return
            source, sid = resolved['source'], resolved['source_id']
            key = source + ':' + sid
            cached = self._cache_get(key)
            if cached:
                if callback:
                    callback(dict(cached))
                return
            try:
                raw = resolved.get('profile_data') or {}
                actual_name = resolved['name']
                if source == 'youtube':
                    yt = self._ytmusic()
                    catalog_state = {}
                    albums = self._collect_albums(yt, sid, raw, actual_name, deadline, is_current, catalog_state=catalog_state)
                    tracks = self._collect_tracks(yt, sid, raw, actual_name, albums, deadline, is_current)
                    avatar = self._best_thumbnail(raw)
                    bio_raw = clean_artist_bio((raw.get('description') or '').strip())
                    if not avatar or not bio_raw:
                        f_avatar, f_bio = self._resolve_metadata_fallback(actual_name, avatar_url=avatar, bio=bio_raw, deadline=deadline, is_current=is_current)
                        avatar = avatar or f_avatar
                        bio_raw = bio_raw or f_bio
                    bio_ru, bio_original = self._translate_bio(bio_raw, deadline=deadline) if bio_raw and time.monotonic() < deadline else (bio_raw, bio_raw)
                    profile = {'status': 'found', 'verified': True, 'name': actual_name, 'source': source, 'source_id': sid, 'channel_id': sid,
                               'avatar_url': avatar, 'bio': bio_ru or bio_original, 'bio_ru': bio_ru,
                               'bio_original': bio_original, 'bio_en': bio_original, 'subscribers': raw.get('subscribers') or '',
                               'views': raw.get('views') or '', 'albums': albums, 'tracks': tracks,
                               'tracks_has_more':bool(albums) or bool(catalog_state.get('pending')),
                               'catalog_partial':bool(albums) or bool(catalog_state.get('pending')), 'catalog_state':catalog_state}
                elif source == 'deezer':
                    from services.deezer_service import DeezerService
                    avatar = raw.get('picture_xl') or raw.get('picture_big') or raw.get('picture') or ''
                    tracks = []
                    try:
                        data = self.catalog._call(lambda: self.catalog._deezer_get('artist/' + sid + '/top', limit=50), deadline, is_current)
                        converter = DeezerService(settings=self.settings)
                        seen = set()
                        for item in data.get('data', []):
                            # This profile is bound to a catalogue id, never a
                            # same-title cover or a similar artist name.
                            ids = {str((item.get('artist') or {}).get('id'))}
                            ids.update(str(person.get('id')) for person in item.get('contributors', []) if isinstance(person, dict))
                            if sid not in ids:
                                continue
                            try:
                                track = converter._track(item)
                            except (ValueError, TypeError, RuntimeError):
                                continue
                            if track['source_id'] not in seen:
                                tracks.append(track)
                                seen.add(track['source_id'])
                    except Exception:
                        logger.debug('Deezer artist top tracks unavailable')
                    avatar, bio_raw = self._resolve_metadata_fallback(
                        actual_name, avatar_url=avatar, deadline=deadline, is_current=is_current)
                    bio_ru, bio_original = (self._translate_bio(bio_raw, deadline=deadline)
                        if bio_raw and time.monotonic() < deadline else (bio_raw, bio_raw))
                    profile = {'status': 'found', 'verified': True, 'name': actual_name,
                               'source': source, 'source_id': sid,
                               'avatar_url': avatar,
                               'fans': raw.get('nb_fan') or 0, 'bio': bio_ru or bio_original,
                               'bio_ru': bio_ru, 'bio_original': bio_original,
                               'bio_en': bio_original, 'tracks': tracks,
                               'albums': [], 'tracks_has_more': True, 'catalog_partial': True,
                               'catalog_state': {'next_index':0, 'track_offsets':{}}}
                else:
                    profile = self._build_itunes_profile(raw, sid, actual_name, deadline, is_current)
                self._cache_put(key, profile)
                if callback and is_current():
                    callback(profile)
            except Exception as exc:
                if error_callback and is_current():
                    error_callback({'status': 'unavailable', 'artist': name, 'error': str(exc)})
        if self.submit(task) is None and error_callback:
            error_callback({'status': 'unavailable', 'artist': name, 'error': 'Сервис недоступен'})
        return None
