"""Public lyric adapters and conservative catalogue recovery for reuploads.

No audio analysis or model inference is involved. All requests share the
lookup's deadline, byte limit, cancellation and provider request allowance.
"""
import base64
import binascii
import re
import urllib.parse
import urllib.error

from services.artist_identity import canonical_artist, artist_aliases
from services.lyrics_metadata import lyrics_metadata
from services.music_matching import normalize


class PublicLyricsFallbacks:
    def __init__(self, engine):
        self.engine = engine

    def _optional_json(self, url, deadline):
        try:
            return self.engine._json(url, deadline)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}
            raise

    def ovh(self, form, deadline, offer):
        """The public API binds plain text to an exact artist/title path."""
        artist = form.get('query_artist') or ''
        title = form.get('query_title') or ''
        if not artist or not title:
            return None
        url = 'https://api.lyrics.ovh/v1/' + '/'.join(
            urllib.parse.quote(str(value), safe='') for value in (artist, title))
        data = self._optional_json(url, deadline)
        text = data.get('lyrics') if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            return None
        result = self.engine.accept(form, title, artist, 0, None, text.strip(), 'lyrics.ovh')
        if result:
            offer(result)
        return result

    def better_qq(self, form, deadline, offer):
        """QQ's provider endpoint does not require a key for cache misses.

        Unlike the query, explicit QRC identity is evidence. Without an
        explicit duration the words are usable but their timing is not.
        """
        artist, title = form.get('query_artist'), form.get('query_title')
        if not artist or not title:
            return None
        params = {'s': title, 'a': artist, 'al': form.get('album') or '',
                  'd': round(form.get('duration') or 0)}
        data = self._optional_json('https://api.betterlyrics.org/qq/getLyrics?' + urllib.parse.urlencode(params), deadline)
        if not isinstance(data, dict) or data.get('provider') != 'qq':
            return None
        raw = data.get('lyrics')
        if not isinstance(raw, str):
            return None
        tags = {key.casefold(): value.strip() for key, value in
                re.findall(r'\[(ti|ar|length|total):([^\]]*)\]', raw, re.I)}
        if not tags.get('ti') or not tags.get('ar'):
            return None
        duration = self.engine.rich._number(data.get('duration'))
        if not duration and tags.get('total'):
            duration = self.engine.rich._number(tags['total']) / 1000
        if not duration and tags.get('length'):
            try:
                minutes, seconds = tags['length'].split(':')
                duration = float(minutes) * 60 + float(seconds)
            except (ValueError, TypeError):
                pass
        result = self.engine.accept_format(form, tags['ti'], tags['ar'], duration,
                                           raw, 'qrc', 'Better Lyrics QQ')
        if result:
            offer(result)
        return result

    def kugou(self, form, deadline, offer):
        """Search actual lyric candidates before downloading an LRC body."""
        query = ' '.join(str(form.get(k) or '') for k in ('query_artist', 'query_title')).strip()
        if not query:
            return None
        params = {'keyword': query, 'duration': round((form.get('duration') or 0) * 1000),
                  'client': 'pc', 'ver': 1, 'man': 'yes'}
        data = self.engine._json('https://lyrics.kugou.com/search?' + urllib.parse.urlencode(params), deadline)
        candidates = data.get('candidates') if isinstance(data, dict) else None
        if not isinstance(candidates, list):
            return None
        for candidate in candidates[:20]:
            if not isinstance(candidate, dict):
                continue
            duration = self.engine.rich._number(candidate.get('duration')) / 1000
            if not self.engine.accept(form, candidate.get('song', ''), candidate.get('singer', ''),
                                       duration, None, 'candidate', 'Kugou'):
                continue
            sid, access = str(candidate.get('id') or ''), str(candidate.get('accesskey') or '')
            if not sid.isdigit() or not access or len(access) > 256:
                continue
            params = {'id': sid, 'accesskey': access, 'fmt': 'lrc', 'charset': 'utf8', 'client': 'pc', 'ver': 1}
            body = self.engine._json('https://lyrics.kugou.com/download?' + urllib.parse.urlencode(params), deadline)
            content = body.get('content') if isinstance(body, dict) else None
            if not isinstance(content, str) or len(content) > 2 * 1024 * 1024:
                continue
            try:
                raw = base64.b64decode(content, validate=True).decode('utf-8-sig')
            except (binascii.Error, UnicodeError, ValueError):
                continue
            result = self.engine.accept_format(form, candidate.get('song', ''), candidate.get('singer', ''),
                                               duration, raw, 'lrc', 'Kugou')
            if result:
                offer(result)
                return result
        return None

    def _recording_agrees(self, form, title, artist, duration):
        wanted = form['metadata']
        offered = lyrics_metadata(title, artist)
        if (not offered['artists'] or normalize(wanted['base_title']) != normalize(offered['base_title'])
                or wanted['version'] != offered['version']):
            return False
        # Recovery has a tighter duration window than ordinary lyric matching.
        # Never infer an original artist for a speed edit from title alone.
        duration = self.engine.rich._number(duration)
        wanted_duration = form.get('duration') or 0
        return bool(duration and wanted_duration and
                    abs(duration - wanted_duration) <= max(2, min(5, wanted_duration * .02)))

    def recover_upload(self, form, deadline, offer):
        """Two independent catalogues must agree on one recording identity.

        Only identified YouTube/SoundCloud uploads take this fallback. Ordinary
        library artists keep strict matching; a title twin or conflicting
        catalogue evidence cannot silently become the original artist.
        """
        if (form.get('upload_source') not in ('youtube', 'soundcloud') or not form.get('duration')
                or form['metadata'].get('embedded') or form.get('fallback')):
            return None
        title = form['query_title']
        data = self.engine._json('https://api.deezer.com/search?' + urllib.parse.urlencode(
            {'q': 'track:"' + title.replace('"', '') + '"', 'limit': 25}), deadline)
        deezer = []
        for row in data.get('data', [])[:25]:
            artist = row.get('artist') or {}
            if self._recording_agrees(form, row.get('title'), artist.get('name'), row.get('duration')):
                deezer.append(row)
        if not deezer:
            return None
        headers = {'User-Agent': 'NeDotify/1.0', 'Referer': 'https://music.163.com/'}
        data = self.engine._json('https://music.163.com/api/cloudsearch/pc?' + urllib.parse.urlencode(
            {'type': 1, 'offset': 0, 'limit': 25, 's': title}), deadline, headers)
        aliases = artist_aliases(self.engine.service.settings)
        matches = {}
        for song in (data.get('result') or {}).get('songs', [])[:25]:
            people = song.get('ar') or song.get('artists') or []
            duration = self.engine.rich._number(song.get('dt') or song.get('duration')) / 1000
            if not self._recording_agrees(form, song.get('name'), people, duration):
                continue
            for row in deezer:
                artist = row['artist']['name']
                if self.engine._artists_agree(artist, people):
                    key = (row['artist'].get('id'), canonical_artist(artist, aliases))
                    matches.setdefault(key, (row, song, people, duration))
        if len(matches) != 1:
            return None
        row, song, people, duration = next(iter(matches.values()))
        if self.engine._artists_agree(form['metadata']['artists'], people):
            return None
        verified = dict(form, metadata=lyrics_metadata(song['name'], people),
                        query_title=song['name'], query_artist=row['artist']['name'])
        sid = str(song.get('id') or '')
        if not sid.isdigit():
            return None
        data = self.engine._json('https://music.163.com/api/song/lyric?' + urllib.parse.urlencode(
            {'id': sid, 'lv': 1, 'kv': 1, 'tv': -1, 'yv': 1}), deadline, headers)
        raw = (data.get('lrc') or {}).get('lyric')
        result = self.engine.accept(verified, song['name'], people, duration, None,
                                    self.engine.plain(raw), 'Netease')
        if not result:
            # Catalogue presence does not imply lyric availability. The same
            # independently verified identity can query another lyric source.
            result = self.engine.genius(verified, deadline, lambda result: None)
        if not result:
            return None
        # The original upload may have an unmarked intro or changed offset.
        # Recover words, without claiming original karaoke timing is valid.
        result.update(identity_recovered=True, identity_evidence=[
            {'source': 'Deezer', 'id': str(row['id']), 'artist': row['artist']['name'],
             'title': row['title'], 'duration': row['duration']},
            {'source': 'Netease', 'id': sid, 'artist': result['matched_artist'],
             'title': song['name'], 'duration': duration}])
        offer(result)
        return result
