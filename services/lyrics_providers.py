"""Bounded adapters for rich lyric sources.

Each method makes at most one request through LyricsLookup's deadline-aware
reader. Provider text is kept verbatim alongside the normalized model so the
renderer can use genuine word or syllable timings.
"""
import math
import re
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from services.lyrics_formats import parse_lyrics, plain_text, to_lrc, validate_lyrics
from services.music_matching import normalize


_YOUTUBE_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
# Numeric Unison confidence is a 0..1 score. For title-only matches, require
# 0.8; its documented categorical `high` level maps to the same accepted band.
_UNISON_MIN_CONFIDENCE = 0.8


class RichLyricsProviders:
    """Adapters that share the lookup engine's bounded transport and matcher."""

    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _video_id(form):
        value = str(form.get('video_id') or '').strip()
        return value if _YOUTUBE_ID.fullmatch(value) else ''

    @staticmethod
    def _number(value):
        try:
            result = float(value)
            return result if math.isfinite(result) and result > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _ttml_metadata(text):
        """Read explicit identity metadata; lyric prose is never treated as identity."""
        if not isinstance(text, str) or len(text) > 2 * 1024 * 1024 or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
            return None
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, TypeError, ValueError):
            return None
        values = {'artists': []}
        aliases = {'musicname': 'title', 'songname': 'title', 'trackname': 'title',
                   'artistname': 'artist', 'artists': 'artist', 'albumname': 'album'}
        for node in root.iter():
            tag = node.tag.rsplit('}', 1)[-1].casefold()
            keys = {tag}
            for key, value in node.attrib.items():
                key = key.rsplit('}', 1)[-1].casefold()
                if key in ('name', 'property', 'role', 'type', 'key'):
                    keys.add(str(value).rsplit(':', 1)[-1].casefold())
            content = (node.text or node.attrib.get('value') or node.attrib.get('content') or '').strip()
            for key in keys:
                key = aliases.get(key, key)
                if content and key in ('title', 'song', 'track', 'artist', 'creator', 'album', 'duration'):
                    if key == 'artist':
                        values['artists'].append(content)
                    else:
                        values.setdefault(key, content)
                if key == 'duration' and node.attrib.get('value'):
                    values.setdefault(key, node.attrib['value'])
        title = values.get('title') or values.get('song') or values.get('track')
        artist = values.get('artist') or values.get('creator') or values['artists']
        if isinstance(artist, list):
            artist = ', '.join(dict.fromkeys(artist))
        if not title or not artist:
            return None
        return {
            'title': title,
            'artist': artist,
            'album': values.get('album') or '',
            'duration': RichLyricsProviders._number(values.get('duration')),
        }

    @staticmethod
    def _identity(form, title=None, artist=None, duration=0):
        metadata = form['metadata']
        title = title if title is not None else form.get('query_title') or metadata.get('title', '')
        artist = artist if artist is not None else metadata.get('artists') or form.get('query_artist', '')
        return title, artist, duration

    def _accepted_model(self, form, text, source_format, source, duration, title=None, artist=None, original=None):
        """Parse, identity-check, and enrich a normalized provider result."""
        try:
            duration_ms = int(max(0, self._number(duration) * 1000))
            model = parse_lyrics(text, source_format, duration_ms=duration_ms)
            if not isinstance(model, dict) or not model.get('lines') or not validate_lyrics(model, duration_ms=duration_ms):
                return None
            line_lrc = to_lrc(model)
            plain = plain_text(model)
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        if not plain:
            return None
        title, artist, duration = self._identity(form, title, artist, duration)
        accepted = self.engine.accept(form, title, artist, duration, line_lrc, plain, source)
        if not accepted:
            return None
        # The canonical acceptor intentionally strips timings for base-title
        # fallback or duration mismatch. Keep that downgrade in the rich model.
        if accepted.get('match_type') == 'base' or not accepted.get('syncedLyrics'):
            model = parse_lyrics(plain, 'plain')
        accepted.update({
            'syncType': model.get('syncType', 'plain'),
            'lines': model.get('lines') or [],
            'originalFormat': source_format,
            'originalLyrics': text if original is None else original,
        })
        return accepted

    def unison(self, form, deadline, offer):
        """An ID miss must not hide a verified metadata-indexed edition."""
        video_id = self._video_id(form)
        if video_id and not form.get('fallback'):
            budget = getattr(getattr(self.engine, '_request_local', None), 'provider_budget', None)
            seen = budget.setdefault('video_ids', set()) if budget is not None else set()
            if video_id not in seen:
                seen.add(video_id)
                missing = []
                try:
                    result = self._unison_lookup(form, deadline, offer, missing)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    result = None
                    missing.append(True)
                if result:
                    return result
                if not missing:
                    return None
            return self._unison_lookup(dict(form, video_id=''), deadline, offer)
        return self._unison_lookup(dict(form, video_id=''), deadline, offer)

    def _unison_lookup(self, form, deadline, offer, missing=None):
        """Read Unison only by a confirmed video id or a bounded exact identity."""
        video_id = self._video_id(form)
        if video_id and form.get('fallback'):
            return None
        if video_id:
            url = 'https://unison.boidu.dev/lyrics?' + urllib.parse.urlencode({'v': video_id})
            verified_by_id = True
        else:
            metadata = form['metadata']
            title = str(form.get('query_title') or metadata.get('title') or '').strip()
            artists = metadata.get('artists') or []
            artist = ', '.join(map(str, artists)) if isinstance(artists, (list, tuple)) else str(artists)
            if not title or not artist:
                return None
            params = {'song': title, 'artist': artist}
            if form.get('album'):
                params['album'] = str(form['album'])
            if self._number(form.get('duration')):
                params['duration'] = str(round(self._number(form['duration'])))
            url = 'https://unison.boidu.dev/lyrics?' + urllib.parse.urlencode(params)
            verified_by_id = False
        body = self.engine._json(url, deadline)
        if isinstance(body, dict) and body.get('success') is False and missing is not None:
            missing.append(True)
        if not isinstance(body, dict) or body.get('success') is not True or not isinstance(body.get('data'), dict):
            return None
        data = body['data']
        if verified_by_id:
            if str(data.get('videoId') or '') != video_id:
                return None
        elif not (data.get('song') and data.get('artist')):
            # An exact lookup response without identity fields is ambiguous.
            return None
        confidence = data.get('confidence')
        if isinstance(confidence, bool):
            return None
        if isinstance(confidence, (int, float)):
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                return None
            if not verified_by_id and confidence < _UNISON_MIN_CONFIDENCE:
                return None
        elif isinstance(confidence, str):
            level = confidence.casefold().strip()
            if level not in ('high', 'medium', 'low') or (not verified_by_id and level != 'high'):
                return None
        elif not verified_by_id:
            return None
        expected_album = str(form.get('album') or '').strip()
        offered_album = str(data.get('album') or '').strip()
        if expected_album and offered_album and normalize(expected_album) != normalize(offered_album):
            return None
        text, fmt = data.get('lyrics'), str(data.get('format') or '').casefold()
        if not isinstance(text, str) or not text.strip() or fmt not in ('ttml', 'lrc', 'plain'):
            return None
        raw_duration = data.get('duration')
        if verified_by_id and raw_duration is None:
            duration = self._number(form.get('duration'))
        else:
            duration = self._number(raw_duration)
            if verified_by_id and duration <= 0:
                return None
        title, artist, _ = self._identity(form, data.get('song'), data.get('artist'), duration)
        result = self._accepted_model(form, text, fmt, 'Unison', duration, title, artist)
        if result:
            offer(result)
        return result

    def betterlyrics(self, form, deadline, offer):
        """Request one default TTML response; require explicit TTML identity."""
        metadata = form['metadata']
        title = str(form.get('query_title') or metadata.get('title') or '').strip()
        artists = metadata.get('artists') or []
        artist = ', '.join(map(str, artists)) if isinstance(artists, (list, tuple)) else str(artists)
        album = str(form.get('album') or '').strip()
        duration = self._number(form.get('duration'))
        if not title or not artist or not album or not duration:
            return None
        url = 'https://api.betterlyrics.org/getLyrics?' + urllib.parse.urlencode({
            's': title, 'a': artist, 'al': album, 'd': round(duration),
        })
        body = self.engine._json(url, deadline)
        if not isinstance(body, dict) or not isinstance(body.get('ttml'), str) or not body['ttml'].strip():
            return None
        raw = body['ttml']
        identity = self._ttml_metadata(raw)
        # The public response is documented as {ttml}, so query parameters are
        # not evidence that the returned body belongs to the requested version.
        if not identity:
            return None
        if identity['album'] and normalize(identity['album']) != normalize(album):
            return None
        result = self._accepted_model(form, raw, 'ttml', 'Better Lyrics', identity['duration'] or duration,
                                      identity['title'], identity['artist'])
        if result:
            offer(result)
        return result

    def simpmusic(self, form, deadline, offer):
        """Fetch community lyrics for exactly the current YouTube video id."""
        video_id = self._video_id(form)
        if not video_id or form.get('fallback'):
            return None
        url = 'https://api-lyrics.simpmusic.org/v1/' + urllib.parse.quote(video_id, safe='')
        body = self.engine._json(url, deadline)
        if not isinstance(body, dict) or body.get('success') is not True or not isinstance(body.get('data'), list):
            return None
        best = None
        for item in body['data'][:10]:
            if not isinstance(item, dict) or str(item.get('videoId') or '') != video_id:
                continue
            # The pinned client calls GET /v1/{videoId} and consumes the first
            # record from data[], whose documented lyric fields are
            # songTitle/artistName/plainLyric/syncedLyrics.
            original = item.get('richSync') or item.get('syncedLyrics') or item.get('plainLyric') or item.get('lyrics')
            if not isinstance(original, str) or not original.strip():
                continue
            fmt = str(item.get('format') or '').casefold()
            if not fmt:
                fmt = ('richsync' if re.search(r'<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>', original)
                       else 'lrc' if re.search(r'\[\d{1,3}:\d{2}', original) else 'plain')
            if fmt not in ('richsync', 'simp_music', 'simpmusic', 'lrc', 'ttml', 'qrc', 'yrc', 'plain'):
                continue
            raw_duration = item.get('duration') if 'duration' in item else item.get('durationSeconds')
            if raw_duration is None:
                duration = self._number(form.get('duration'))
            else:
                duration = self._number(raw_duration)
                if duration <= 0:
                    continue
            text = self._simpmusic_lrc(original) if fmt == 'richsync' else original
            title, artist, _ = self._identity(form, item.get('songTitle') or item.get('song') or item.get('title'),
                                              item.get('artistName') or item.get('artist') or item.get('artists'), duration)
            best = self._accepted_model(form, text, fmt, 'SimpMusic', duration, title, artist, original)
            if best:
                break
        if best:
            offer(best)
        return best

    @staticmethod
    def _simpmusic_lrc(text):
        """Add line stamps around SimpMusic's ``<time>word`` rich-sync rows.

        SimpMusic marks every word with an angle-bracket timestamp and uses
        newlines as line boundaries. The shared parser's enhanced-LRC reader
        also needs a line timestamp; this compatibility envelope leaves every
        original word marker and word intact.
        """
        output = []
        marker = re.compile(r'<(\d{1,3}:\d{2}(?:[.:]\d{1,3})?)>')
        for row in str(text).splitlines():
            match = marker.search(row)
            if not match:
                continue
            timestamp = match.group(1)
            output.append(f'[{timestamp}] {row}')
        return '\n'.join(output)
