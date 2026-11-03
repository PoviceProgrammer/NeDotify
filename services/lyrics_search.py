"""Bounded lyric-line discovery; playback results still require catalogue identity."""
import html
import re
import time
import urllib.parse

from services.music_matching import artist_matches, normalize, title_metadata
from services.lyrics_metadata import native_lyrics_name as _native_name


def should_search_lyrics(query, tracks):
    words = normalize(query).split()
    if not 3 <= len(words) <= 60:
        return False
    if any(normalize(t.get('title')) == normalize(query) or
           normalize(t.get('artist')) == normalize(query) for t in tracks):
        return False
    return not tracks or len(words) >= 5


def find_lyric_tracks(query, lyrics, youtube, is_current=lambda: True, deezer=None):
    """One full-text request and at most two YT / two Deezer catalogue searches.

    Endpoint/shape: LyricsGenius PublicAPI.search_lyrics -> search/lyric,
    response.sections[].hits[].result and highlights[].value.
    Reuse the lyrics transport for timeout, proxy and host cooldown handling.
    """
    deadline = time.monotonic() + 8
    if not is_current():
        return []
    url = 'https://genius.com/api/search/lyric?' + urllib.parse.urlencode({'q': query, 'per_page': 3, 'page': 1})
    payload = lyrics._lookup._json(url, deadline)
    needle = normalize(query)
    result, seen = [], set()
    candidates = []
    for section in (payload.get('response') or {}).get('sections', []):
        for hit in section.get('hits', []):
            song = hit.get('result') or {}
            title = _native_name(song.get('title'))
            artist = _native_name((song.get('primary_artist') or {}).get('name'))
            snippets = [normalize(html.unescape(re.sub(r'<[^>]+>', '', str(h.get('value') or ''))))
                        for h in hit.get('highlights', []) if isinstance(h, dict) and h.get('property') == 'lyrics']
            if title and artist and any(needle in snippet for snippet in snippets):
                key = (normalize(title), normalize(artist))
                if key not in seen:
                    seen.add(key)
                    candidates.append((title, artist))
    for title, artist in candidates[:2]:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not is_current():
            break
        def matching(hits):
            for track in hits or []:
                if normalize(title_metadata(track.get('title'), track.get('artist'))['title']) != normalize(title):
                    continue
                offered_artist = track.get('artists') or track.get('artist')
                agrees = getattr(lyrics._lookup, '_artists_agree', None)
                if not (agrees(artist, offered_artist) if agrees else
                        artist_matches(artist, offered_artist, getattr(lyrics, 'settings', None))):
                    continue
                return dict(track, matched_by='lyrics')
            return None
        try:
            track = matching(youtube.search_sync(f'{artist} - {title}', limit=5, timeout=min(2.0, remaining)))
        except Exception:
            track = None
        if not track and deezer is not None and is_current() and time.monotonic() < deadline:
            # Public catalogue fallback when YouTube Music is unavailable. Use
            # the existing Deezer track shape, never its 30-second preview URL.
            try:
                url = 'https://api.deezer.com/search?' + urllib.parse.urlencode({'q': f'{artist} {title}', 'limit': 5})
                data = lyrics._lookup._json(url, min(deadline, time.monotonic() + 3))
                hits = []
                for row in data.get('data', [])[:5]:
                    try:
                        hits.append(deezer._track(row))
                    except (ValueError, TypeError, RuntimeError):
                        continue
                track = matching(hits)
            except Exception:
                pass
        if track:
            result.append(track)
    return result if is_current() else []
