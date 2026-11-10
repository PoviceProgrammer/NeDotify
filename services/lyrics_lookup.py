"""Identity-checked lyrics, progressive results and one bounded lookup budget."""
import collections
import concurrent.futures
import copy
import html
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from services.music_matching import title_metadata, artist_matches, similarity, normalize
from services.artist_identity import artist_aliases, canonical_artist, name_key
from services.lyrics_translit import alt_script_artist, has_ascii_letters, has_cyrillic, to_latin
from services.lyrics_metadata import lyrics_metadata, native_lyrics_name

logger = logging.getLogger(__name__)

# A speed edit or remix can share words with the original, but live, acoustic
# and cover performances may change the lyrics themselves. Keep the lyrics
# fallback contract narrower than catalogue search's version recovery set.
BASE_FALLBACK_VERSIONS = frozenset({'sped', 'slowed', 'remix'})


class LyricsLookup:
    BUDGET = 8.0
    MEMORY_ENTRIES = 2048

    def __init__(self, service, *, cache_path=None, db=None):
        self.service = service
        self.db = db
        # All shared lookup state belongs to LyricsService's existing cache lock.
        self.service._cache = collections.OrderedDict()
        self.service._inflight = {}
        self._request_local = threading.local()
        self._source_cooldowns = {}
        from services.lyrics_cache import LyricsDiskCache
        self.disk_cache = LyricsDiskCache(cache_path) if cache_path else None
        from services.lyrics_providers import RichLyricsProviders
        self.rich = RichLyricsProviders(self)
        from services.lyrics_fallbacks import PublicLyricsFallbacks
        self.public = PublicLyricsFallbacks(self)

    @staticmethod
    def plain(text):
        text = re.sub(r'\[[^\]]*\]', '', str(text or '')).strip()
        return '\n'.join(line for line in text.splitlines() if not re.match(r'^\s*(?:作词|作曲|编曲|词|曲)\s*[:：]', line)).strip()

    @staticmethod
    def _contains_cyrillic(value):
        if isinstance(value, list):
            return any(LyricsLookup._contains_cyrillic(item) for item in value)
        if isinstance(value, dict):
            return LyricsLookup._contains_cyrillic(str(value.get('name') or value.get('artistName') or ''))
        return has_cyrillic(str(value or ''))

    @staticmethod
    def _latin_names(value):
        """Project artist credits into the Latin domain (cyrillic -> latin)."""
        if isinstance(value, list):
            return [LyricsLookup._latin_names(item) for item in value]
        if isinstance(value, dict):
            item = dict(value)
            for field in ('name', 'artistName'):
                if field in item:
                    item[field] = to_latin(str(item.get(field) or ''))
            return item
        return to_latin(str(value or ''))

    @staticmethod
    def _single_script_names(value):
        """True when every credit on this side uses exactly one script.

        A name mixing Cyrillic and Latin letters ('PHАRAOH' with a homoglyph
        'А') is a spoof pattern, not a transcription: the Latin projection
        would erase exactly the distinction the strict pass must keep, so such
        names never take the cross-script pass.
        """
        if isinstance(value, list):
            return all(LyricsLookup._single_script_names(item) for item in value) if value else True
        if isinstance(value, dict):
            return LyricsLookup._single_script_names(str(value.get('name') or value.get('artistName') or ''))
        name = str(value or '')
        return has_cyrillic(name) != has_ascii_letters(name)

    def _artists_agree(self, wanted, offered):
        """BUG-L2-002: providers index Russian artists under both scripts.

        The primary comparison is the untouched strict one. Only when it fails
        across a script boundary (one side Cyrillic, the other Latin-only,
        neither side mixed) do both sides get projected into the Latin domain
        (deterministic transcription, not fuzzy matching) for one more strict
        pass, so 'Скриптонит' can match 'Skriptonit' while 'ШОК' still cannot
        match 'Shock' and unrelated names stay unrelated.
        """
        if artist_matches(wanted, offered, self.service.settings):
            return True
        wanted_cyrillic = self._contains_cyrillic(wanted)
        if wanted_cyrillic != self._contains_cyrillic(offered):
            if self._single_script_names(wanted) and self._single_script_names(offered):
                if artist_matches(self._latin_names(wanted), self._latin_names(offered), self.service.settings):
                    return True
        # Feat / collaboration tolerance for lyrics lookup (BUG-WIN-003):
        # Lyrics providers often index tracks under the primary artist only
        # (e.g. "Drake" instead of "Drake feat. 21 Savage"), or vice-versa.
        from services.artist_identity import artist_aliases, canonical_artist
        from services.music_matching import credits, normalize
        from services.lyrics_translit import to_latin
        aliases = artist_aliases(self.service.settings)
        w_list = [canonical_artist(p, aliases) for name in (wanted if isinstance(wanted, list) else [wanted]) for p in credits(name)]
        o_list = [canonical_artist(p, aliases) for name in (offered if isinstance(offered, list) else [offered]) for p in credits(name)]
        if w_list and o_list:
            w_norm = [normalize(x) for x in w_list if normalize(x)]
            o_norm = [normalize(x) for x in o_list if normalize(x)]
            if w_norm and o_norm:
                w_set = set(w_norm)
                o_set = set(o_norm)
                if w_norm[0] in o_set or o_norm[0] in w_set:
                    return True
                w_latin = [normalize(to_latin(x)) for x in w_norm]
                o_latin = [normalize(to_latin(x)) for x in o_norm]
                if (self._single_script_names(wanted) and self._single_script_names(offered)
                        and w_latin and o_latin and (w_latin[0] in set(o_latin) or o_latin[0] in set(w_latin))):
                    return True
        return False

    def accept(self, form, title, artists, duration, synced, plain, source, instrumental=False):
        expected = form['metadata']
        offered = lyrics_metadata(native_lyrics_name(title) if source == 'Genius' else title, artists)
        score = similarity(expected['base_title'], offered['base_title'])
        if score < .85 and self._contains_cyrillic(expected['base_title']) != self._contains_cyrillic(offered['base_title']):
            if self._single_script_names(expected['base_title']) and self._single_script_names(offered['base_title']):
                # Cross-script titles require exact deterministic transcription.
                if normalize(to_latin(expected['base_title'])) == normalize(to_latin(offered['base_title'])):
                    score = 1.0
        if score < .85:
            return None
        if expected['artists'] and not self._artists_agree(expected['artists'], offered['artists']):
            return None
        if not expected['artists'] and (score != 1 or not offered['artists'] or not form['duration']):
            return None
        version, offered_version = expected['version'], offered['version']
        base = bool(version and not offered_version and (version in BASE_FALLBACK_VERSIONS
                    or form.get('fallback') and version in ('live', 'acoustic', 'cover')))
        if version != offered_version and not base:
            return None
        if instrumental and version not in ('', 'instrumental'):
            return None
        try:
            duration = float(duration or 0)
        except (ValueError, TypeError):
            duration = 0
        wanted = form['duration']
        plain_tol = max(15.0, wanted * 0.05)
        synced_tol = max(6.0, wanted * 0.035)
        if not base and wanted > 0 and duration > 0 and abs(wanted - duration) > plain_tol:
            if not (expected.get('video') and score == 1 and expected['artists'] and not instrumental):
                return None
        if not expected['artists'] and duration <= 0:
            return None
        synced_ok = bool(synced and re.search(r'\[\d+:\d{2}(?:[.:]\d+)?\]', synced)
                         and not base and wanted > 0 and duration > 0 and abs(wanted - duration) <= synced_tol)
        original = synced or plain
        text = self.plain(plain or synced)
        if not text and not instrumental:
            return None
        if instrumental:
            text, synced, synced_ok = '', None, False
        return {'status': 'found', 'syncedLyrics': synced if synced_ok else None, 'plainLyrics': text or None,
                'instrumental': bool(instrumental), 'weight': 1 if synced_ok else 2, 'source': source,
                'match_type': 'base' if base else 'exact', 'matched_title': title, 'matched_artist': ', '.join(offered['artists']),
                'matched_duration': duration, 'confidence': score,
                'originalFormat': 'lrc' if synced else 'plain', 'originalLyrics': original or ''}

    # Original and additional sources share one ceiling and eight workers.
    # Recovery forms remain sequential within each source's allowance.
    PROVIDER_REQUEST_CAP = 4
    REQUEST_CAP = 51

    def _read(self, url, deadline, headers=None):
        host = urllib.parse.urlsplit(url).hostname
        with self.service._cache_lock:
            if self._source_cooldowns.get(host, 0) > time.monotonic():
                raise TimeoutError('Lyrics source is rate limited')
        budget = getattr(self._request_local, 'budget', None)
        if budget is not None:
            with self.service._cache_lock:
                if not budget['current']():
                    raise concurrent.futures.CancelledError('Lyrics lookup is no longer current')
                provider_budget = getattr(self._request_local, 'provider_budget', None)
                if provider_budget is not None and provider_budget['requests'] >= provider_budget.get('limit', self.PROVIDER_REQUEST_CAP):
                    raise TimeoutError('Достигнут лимит запросов источника')
                if budget['requests'] >= self.REQUEST_CAP:
                    raise TimeoutError('Достигнут лимит запросов текста')
                budget['requests'] += 1
                if provider_budget is not None:
                    provider_budget['requests'] += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Lyrics deadline exceeded')
        req = urllib.request.Request(url, headers=headers or {'User-Agent': 'NeDotify/1.0'})
        try:
            with self.service._open_url(req, timeout=min(6.0, remaining)) as response:
                return response.read(2 * 1024 * 1024).decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                from email.utils import parsedate_to_datetime
                value = exc.headers.get('Retry-After', '60') if exc.headers else '60'
                try:
                    seconds = float(value)
                except ValueError:
                    try:
                        seconds = parsedate_to_datetime(value).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 60
                seconds = seconds if math.isfinite(seconds) else 60
                with self.service._cache_lock:
                    self._source_cooldowns[host] = time.monotonic() + max(1, seconds)
            raise

    def accept_format(self, form, title, artists, duration, text, fmt, source):
        from services.lyrics_formats import parse_lyrics, plain_text, to_lrc
        try:
            model = parse_lyrics(text, fmt, float(duration or 0) * 1000)
            result = self.accept(form, title, artists, duration, to_lrc(model), plain_text(model), source)
            if result:
                if result.get('syncedLyrics'):
                    result.update(model)
                result.update(originalFormat=fmt, originalLyrics=text)
            return result
        except (ValueError, TypeError):
            return None

    def _json(self, url, deadline, headers=None):
        return json.loads(self._read(url, deadline, headers))

    def _artist_spellings(self, form):
        """BUG-L2-002: artist spellings to query, best first.

        The metadata spelling is always queried first; the deterministic
        other-script transcription (Скриптонит<->Skriptonit) is a second QUERY
        inside the same provider job, not a duplicate cascade job: providers
        report a miss for the one script and a hit for the other, and the
        retry only fires when the first spelling found nothing at all. The
        expected metadata/accept stays bound to the ORIGINAL identity.
        """
        artist = str(form.get('query_artist') or '')
        alt = alt_script_artist(artist)
        if form['metadata']['version'] in BASE_FALLBACK_VERSIONS and not form['fallback']:
            return [artist]
        if alt and alt != artist:
            return [artist, alt]
        return [artist]

    def lrclib(self, form, deadline, offer):
        if form['fallback'] and has_cyrillic(form['query_title']):
            return self._lrclib_title_search(form, deadline, offer)
        best = None
        spellings = self._artist_spellings(form)
        for index, artist in enumerate(spellings):
            best = self._lrclib_query(dict(form, query_artist=artist, search_only=index > 0), deadline, offer)
            if best:
                break
        if not best and (not form['metadata']['version'] or form.get('fallback')):
            best = self._lrclib_title_search(form, deadline, offer)
        return best

    def _lrclib_title_search(self, form, deadline, offer):
        # Cyrillic titles can be indexed under a different artist spelling.
        # Search the catalogue by title, then verify every artist as usual.
        title = form['query_title']
        result = self._lrclib_title_query(form, title, deadline, offer)
        if not result and has_cyrillic(title) and self._single_script_names(form['metadata']['base_title']):
            result = self._lrclib_title_query(form, to_latin(title), deadline, offer)
        return result

    def _lrclib_title_query(self, form, title, deadline, offer):
        data = self._json('https://lrclib.net/api/search?' + urllib.parse.urlencode({'track_name': title}), deadline)
        if not isinstance(data, list):
            raise ValueError('Invalid LRCLIB response')
        best = None
        for item in data[:50]:
            result = self.accept(form, item.get('trackName', ''), item.get('artistName', ''), item.get('duration'),
                                 item.get('syncedLyrics'), item.get('plainLyrics'), 'LRCLIB', item.get('instrumental', False))
            if result:
                offer(result)
                if best is None or self._quality(result) > self._quality(best):
                    best = result
        return best

    def _lrclib_query(self, form, deadline, offer):
        people, title = form['query_artist'], form['query_title']
        params = {'artist_name': people, 'track_name': title}
        if form['duration'] and not form['fallback']:
            params['duration'] = round(form['duration'])
        if form['album']:
            params['album_name'] = form['album']
        best = None
        try:
            data = {} if form.get('search_only') else self._json('https://lrclib.net/api/get?' + urllib.parse.urlencode(params), deadline)
            best = self.accept(form, data.get('trackName', ''), data.get('artistName', ''), data.get('duration'),
                               data.get('syncedLyrics'), data.get('plainLyrics'), 'LRCLIB', data.get('instrumental', False))
            if best:
                offer(best)
                if best['syncedLyrics'] or best['instrumental']:
                    return best
        except urllib.error.HTTPError as exc:
            if exc.code not in (400, 404):
                raise
        data = self._json('https://lrclib.net/api/search?' + urllib.parse.urlencode({'q': f'{people} {title}'.strip()}), deadline)
        if not isinstance(data, list):
            raise ValueError('Invalid LRCLIB response')
        # LRCLIB returns a bounded result page. Do not throw away its tail:
        # alternate releases can push the compatible duration below position 15.
        for item in data[:50]:
            result = self.accept(form, item.get('trackName', ''), item.get('artistName', ''), item.get('duration'),
                                 item.get('syncedLyrics'), item.get('plainLyrics'), 'LRCLIB', item.get('instrumental', False))
            if result:
                offer(result)
                if best is None or self._quality(result) > self._quality(best):
                    best = result
        return best

    def netease(self, form, deadline, offer):
        best = None
        for artist in self._artist_spellings(form):
            best = self._netease_query(dict(form, query_artist=artist), deadline, offer)
            if best:
                break
        return best

    def _netease_query(self, form, deadline, offer):
        query = urllib.parse.quote(f"{form['query_artist']} {form['query_title']}".strip())
        headers = {'User-Agent': 'NeDotify/1.0', 'Referer': 'https://music.163.com/'}
        data = self._json(f'https://music.163.com/api/cloudsearch/pc?type=1&offset=0&limit=12&s={query}', deadline, headers)
        if data.get('code', 200) != 200:
            raise ValueError('Netease search unavailable')
        candidates = (data.get('result') or {}).get('songs') or []
        best, attempts = None, 0
        for song in sorted(candidates, key=lambda s: (similarity(form['metadata']['base_title'], s.get('name')),
                           -abs(form['duration'] - (s.get('dt') or s.get('duration') or 0) / 1000)), reverse=True):
            people = song.get('ar') or song.get('artists') or []
            duration = (song.get('dt') or song.get('duration') or 0) / 1000
            if not self.accept(form, song.get('name', ''), people, duration, None, 'candidate', 'Netease'):
                continue
            attempts += 1
            payload = self._json(f"https://music.163.com/api/song/lyric?id={song['id']}&lv=1&kv=1&tv=-1&yv=1", deadline, headers)
            synced = (payload.get('lrc') or {}).get('lyric')
            yrc = (payload.get('yrc') or {}).get('lyric')
            result = self.accept_format(form, song.get('name', ''), people, duration, yrc, 'yrc', 'Netease') if yrc else None
            if not result:
                result = self.accept(form, song.get('name', ''), people, duration, synced, self.plain(synced), 'Netease')
            if result:
                offer(result)
                if best is None or self._quality(result) > self._quality(best):
                    best = result
                if result.get('syncedLyrics') or not form['duration']:
                    return best
            # A matching release may have no text; try other verified editions
            # rather than making a missing first lyric a missing whole song.
            if attempts >= 4:
                break
        return best

    def qqmusic(self, form, deadline, offer):
        query = urllib.parse.quote(f"{form['query_artist']} {form['query_title']}".strip())
        headers = {'User-Agent': 'NeDotify/1.0', 'Referer': 'https://y.qq.com/'}
        data = self._json(f'https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={query}&format=json&p=1&n=12', deadline, headers)
        candidates = ((data.get('data') or {}).get('song') or {}).get('list') or []
        best, attempts = None, 0
        for song in sorted(candidates, key=lambda s: (similarity(form['metadata']['base_title'], s.get('songname')),
                           -abs(form['duration'] - (s.get('interval') or 0))), reverse=True):
            people = song.get('singer') or []
            duration = song.get('interval') or 0
            if not self.accept(form, song.get('songname', ''), people, duration, None, 'candidate', 'QQ Music'):
                continue
            attempts += 1
            payload = self._json(f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={urllib.parse.quote(str(song['songmid']))}&format=json&nobase64=1", deadline, headers)
            synced = html.unescape(payload.get('lyric') or '')
            result = self.accept_format(form, song.get('songname', ''), people, duration, synced, 'qrc', 'QQ Music') if '<' in synced else None
            if not result:
                result = self.accept(form, song.get('songname', ''), people, duration, synced, self.plain(synced), 'QQ Music')
            if result:
                offer(result)
                if best is None or self._quality(result) > self._quality(best):
                    best = result
                if result.get('syncedLyrics') or not form['duration']:
                    return best
            if attempts >= 4:
                break
        return best

    def genius(self, form, deadline, offer):
        for artist in self._artist_spellings(form):
            result = self._genius_query(dict(form, query_artist=artist), deadline, offer)
            if result:
                return result
        return None

    def _genius_query(self, form, deadline, offer):
        query = urllib.parse.quote(f"{form['query_artist']} {form['query_title']}".strip())
        data = self._json(f'https://genius.com/api/search/multi?per_page=5&q={query}', deadline)
        for section in (data.get('response') or {}).get('sections') or []:
            for hit in section.get('hits') or []:
                song = hit.get('result') or {}
                people = [song.get('primary_artist') or {}] + (song.get('featured_artists') or [])
                if not self.accept(form, song.get('title', ''), people, 0, None, 'candidate', 'Genius'):
                    continue
                url = song.get('url') or ''
                if urllib.parse.urlparse(url).hostname not in ('genius.com', 'www.genius.com'):
                    continue
                page = self._read(url, deadline)
                # BUG-L2-008: Genius is an unofficial endpoint and its markup
                # changes without notice. A parse miss is "this source has
                # nothing", never a cascade failure — no candidate markup means
                # no text, so fall through to the next hit/source cleanly.
                parts = re.findall(r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', page, re.S)
                if not parts:
                    continue
                text = html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', '\n'.join(parts), flags=re.I))).strip()
                if not text:
                    continue
                return self.accept(form, song.get('title', ''), people, 0, None, text, 'Genius')
        return None

    def megalobiz(self, form, deadline, offer):
        query = urllib.parse.quote(f"{form['query_artist']} {form['query_title']}".strip())
        page = self._read(f'https://www.megalobiz.com/search/all?qry={query}', deadline)
        links = re.findall(r'href="(/lrc/maker/[^"]+)"', page)
        for link in list(dict.fromkeys(links))[:2]:
            page = self._read('https://www.megalobiz.com' + link, deadline)
            body = re.search(r'<(?:div|span) id="lrc_[^"]*"[^>]*>(.*?)</(?:div|span)>', page, re.S)
            if not body:
                continue
            text = html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', body.group(1), flags=re.I)))
            tags = {name.lower(): value for name, value in re.findall(r'\[(ti|ar|length):([^\]]+)\]', text, re.I)}
            duration = 0
            try:
                mins, secs = tags.get('length', '0:0').split(':')
                duration = float(mins) * 60 + float(secs)
            except ValueError:
                pass
            result = self.accept(form, tags.get('ti', ''), tags.get('ar', ''), duration, text, self.plain(text), 'Megalobiz')
            if result:
                return result
        return None

    @staticmethod
    def _quality(result):
        rank = {'plain': 0, 'line': 1, 'word': 2, 'syllable': 3}.get(result.get('syncType'), int(bool(result.get('syncedLyrics'))))
        return (not result.get('identity_recovered'), result.get('match_type') != 'base', rank, result.get('confidence', 0))

    @staticmethod
    def _normalize_result(result, duration_ms=0):
        from services.lyrics_formats import parse_lyrics, validate_lyrics
        result = copy.deepcopy(result)
        if result.get('instrumental'):
            return dict(result, syncType='plain', lines=[])
        try:
            if result.get('lines') and result.get('syncType'):
                model = {'syncType': result['syncType'], 'lines': result['lines']}
                if not validate_lyrics(model, duration_ms):
                    return None
            else:
                text = result.get('syncedLyrics') or result.get('plainLyrics') or ''
                fmt = 'lrc' if result.get('syncedLyrics') else 'plain'
                model = parse_lyrics(text, fmt, duration_ms)
            if result.get('match_type') == 'base' and model['syncType'] != 'plain':
                model = parse_lyrics(result.get('plainLyrics') or '', 'plain')
            result.update(model)
            result.setdefault('originalFormat', 'lrc' if result.get('syncedLyrics') else 'plain')
            result.setdefault('originalLyrics', result.get('syncedLyrics') or result.get('plainLyrics') or '')
            result.setdefault('updatedAt', time.time())
            return result
        except (ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def _ttl(result):
        # Plain hits are refreshed sooner so later karaoke contributions become
        # visible. Verified timings and instrumental declarations are reusable.
        return 30 * 86400 if result.get('syncedLyrics') or result.get('instrumental') else 86400

    def _remember(self, key, result):
        if result['status'] not in ('found', 'not_found'):
            return
        ttl = self._ttl(result) if result['status'] == 'found' else 30
        with self.service._cache_lock:
            self.service._cache[key] = (time.monotonic() + ttl, copy.deepcopy(result))
            self.service._cache.move_to_end(key)
            while len(self.service._cache) > self.MEMORY_ENTRIES:
                self.service._cache.popitem(last=False)
        if self.disk_cache and result['status'] == 'found':
            self.disk_cache.put(key, result, ttl)

    def get(self, title, artist='', duration_ms=0, file_path=None, album='', on_update=None, is_current=None, video_id='', upload_source='', upload_id=''):
        if self.service.settings and not self.service.settings.get('lyrics', 'enabled', True):
            return {'status': 'disabled', 'weight': 3}
        active = is_current or (lambda: True)
        # Stream URLs expire and signed tokens change on each resolution. Only
        # local files contribute a path/mtime identity or embedded tag lookup.
        if isinstance(file_path, str) and file_path.lstrip().casefold().startswith(('http://', 'https://')):
            file_path = None
        metadata = lyrics_metadata(title, artist)
        try:
            duration = max(0, float(duration_ms or 0) / 1000)
            if not math.isfinite(duration):
                duration = 0
        except (ValueError, TypeError):
            duration = 0
        file_stamp = None
        if file_path:
            try:
                file_stamp = os.stat(file_path).st_mtime_ns
            except OSError:
                pass
        aliases = artist_aliases(self.service.settings)
        key = (normalize(metadata['title']), tuple(canonical_artist(a, aliases) for a in metadata['artists']), metadata['version'],
               normalize(album), round(duration, 2), str(file_path or ''), file_stamp)
        if video_id:
            key += ('youtube', video_id)
        if upload_source == 'soundcloud' and upload_id:
            key += ('soundcloud', upload_id)
        listener = (on_update, active)
        with self.service._cache_lock:
            hit = self.service._cache.get(key)
            if hit and hit[0] > time.monotonic():
                self.service._cache.move_to_end(key)
                result = dict(copy.deepcopy(hit[1]), revision=1, phase='final')
            else:
                result = None
                self.service._cache.pop(key, None)
                flight = self.service._inflight.get(key)
                owner = flight is None
                if owner:
                    flight = {'event': threading.Event(), 'listeners': [], 'best': None, 'revision': 0}
                    self.service._inflight[key] = flight
                flight['listeners'].append(listener)
                previous = copy.deepcopy(flight['best'])
        if result is not None:
            if on_update and active():
                on_update(copy.deepcopy(result))
            return result
        if not owner:
            if previous and on_update and active():
                on_update(previous)
            flight['event'].wait(self.BUDGET)
            return copy.deepcopy(flight.get('result') or {'status': 'unavailable', 'weight': 3})
        deadline = time.monotonic() + self.BUDGET
        admission_deadline = deadline
        request_budget = {'deadline': None, 'requests': 0}
        def current():
            return not flight.get('closed') and any(check() for _, check in flight['listeners'])
        request_budget['current'] = current
        def offer(result, final=False):
            if not result:
                return
            if result.get('status') == 'found':
                result = self._normalize_result(result, duration * 1000)
                if result is None:
                    return
                result['trackIdentity'] = {'title': metadata['title'], 'artists': metadata['artists'],
                                           'version': metadata['version'], 'durationMs': duration * 1000,
                                           'videoId': video_id}
            with self.service._cache_lock:
                if flight.get('closed') or (not final and (not current() or time.monotonic() >= deadline)):
                    return
                best = flight['best']
                if not final and best and self._quality(result) <= self._quality(best):
                    return
                flight['revision'] += 1
                payload = dict(result, revision=flight['revision'], phase='final' if final else 'partial')
                flight['best'] = payload
                listeners = list(flight['listeners'])
            for callback, check in listeners:
                if callback and check():
                    try:
                        callback(copy.deepcopy(payload))
                    except Exception:
                        logger.debug('Lyrics listener failed', exc_info=True)
        futures = set()
        refresh_legacy = False
        failed = False  # офлайн-режим удалён: раньше здесь был shortcut is_offline
        try:
            if getattr(self, 'db', None):
                try:
                    override = None
                    if video_id:
                        override = self.db.get_track_lyrics_override(identity_key=f"youtube:{video_id}")
                    elif upload_source and upload_id:
                        override = self.db.get_track_lyrics_override(identity_key=f"{upload_source}:{upload_id}")
                    elif file_path:
                        override = self.db.get_track_lyrics_override(identity_key=f"local:{os.path.normcase(os.path.abspath(file_path))}")
                    if not override:
                        comp_artist = ','.join(canonical_artist(a, aliases) for a in metadata['artists'])
                        override = self.db.get_track_lyrics_override(identity_key=f"meta:{normalize(metadata['title'])}\0{comp_artist}\0{metadata.get('version', '')}")
                    if override and (override.get('synced_lyrics') or override.get('plain_lyrics')):
                        synced = override.get('synced_lyrics')
                        plain = override.get('plain_lyrics') or self.plain(synced)
                        override_payload = {
                            'status': 'found',
                            'source': override.get('source_name', 'Пользовательский'),
                            'match_type': 'exact',
                            'confidence': 1.0,
                            'syncedLyrics': synced,
                            'plainLyrics': plain,
                            'syncType': override.get('sync_type', 'line' if synced else 'plain'),
                            'weight': 1 if synced else 2,
                            'instrumental': False,
                            'isOverride': True,
                            'overrideType': override.get('override_type', 'chosen_version'),
                            'offsetMs': override.get('offset_ms', 0),
                        }
                        offer(override_payload, final=True)
                        return copy.deepcopy(flight['best'])
                except Exception as ex:
                    logger.debug("Database override check failed: %s", ex)
            saved_entry = self.disk_cache.get(key, with_ttl=True) if self.disk_cache else None
            if saved_entry:
                saved, remaining_ttl = saved_entry
                refresh_legacy = 'syncType' not in saved
                normalized = self._normalize_result(saved, duration * 1000)
                if normalized is not None:
                    offer(normalized, final=not refresh_legacy)
                    if not refresh_legacy:
                        # Promote without rewriting the disk record/renewing TTL.
                        with self.service._cache_lock:
                            self.service._cache[key] = (time.monotonic() + max(0, min(86400, remaining_ttl)), copy.deepcopy(flight['best']))
                            self.service._cache.move_to_end(key)
                            while len(self.service._cache) > self.MEMORY_ENTRIES:
                                self.service._cache.popitem(last=False)
                        return copy.deepcopy(flight['best'])
            if file_path and file_stamp is not None:
                from utils.tag_parser import extract_embedded_lyrics, parse_tags
                text = extract_embedded_lyrics(file_path).strip()
                if text:
                    tags = parse_tags(file_path)
                    embedded_meta = title_metadata(tags.get('title'), tags.get('artist'))
                    if tags.get('duration', 0) > 0 and (tags.get('title') and similarity(metadata['base_title'], embedded_meta['base_title']) < .85
                            or tags.get('artist') not in ('', None, 'Unknown Artist') and metadata['artists'] and not artist_matches(metadata['artists'], tags['artist'], self.service.settings)):
                        text = ''
                if text:
                    synced = text if duration and re.search(r'\[\d+:\d+', text) else None
                    offer({'status': 'found', 'source': 'Embedded', 'match_type': 'exact', 'confidence': 1,
                           'syncedLyrics': synced, 'plainLyrics': self.plain(text), 'weight': 1 if synced else 2, 'instrumental': False})
            if not flight['best'] or refresh_legacy:
                forms = [{'metadata': metadata, 'query_title': metadata['title'], 'query_artist': ', '.join(metadata['artists']),
                          'duration': duration, 'album': album, 'fallback': False, 'video_id': video_id,
                          'upload_source': upload_source}]
                if metadata['version'] in BASE_FALLBACK_VERSIONS:
                    forms.append(dict(forms[0], query_title=metadata['base_title'], fallback=True))
                if metadata['embedded']:
                    person, song = metadata['embedded']
                    embedded = lyrics_metadata(song, person)
                    embedded['video'] = metadata.get('video', False)
                    # Uploaders often occupy the artist field. Search the
                    # explicit title credit before spending this provider's
                    # request cap on uploader metadata, while accept() still
                    # checks the credited artist and recording version.
                    query_people = []
                    for name in embedded['artists']:
                        canonical = canonical_artist(name, aliases)
                        query_people.append(canonical if canonical != name_key(name) and not canonical.startswith('@catalog:') else name)
                    query_artist = ', '.join(query_people)
                    credited_forms = [dict(forms[0], metadata=embedded, query_title=embedded['title'],
                                           query_artist=query_artist, fallback=False)]
                    if embedded['version'] in BASE_FALLBACK_VERSIONS:
                        credited_forms.append(dict(credited_forms[0], query_title=embedded['base_title'], fallback=True))
                    forms = credited_forms + forms
                if metadata.get('reverse_credit'):
                    person, song = metadata['reverse_credit']
                    inferred = title_metadata(song, person)
                    forms.append(dict(forms[0], metadata=inferred, query_title=inferred['title'], query_artist=person, fallback=False))
                # BUG-L2-002: the alternate-script spelling (Скриптонит<->
                # Skriptonit) is retried INSIDE each provider (see
                # _artist_spellings) rather than submitted as duplicate jobs:
                # retries share each provider's bounded sequential job.

                def run(provider, form, following=()):
                    with self.service._cache_lock:
                        if request_budget['deadline'] is None:
                            request_budget['deadline'] = time.monotonic() + self.BUDGET
                        provider_deadline = request_budget['deadline']
                    self._request_local.budget = request_budget
                    # BUG-L2-009: a per-provider sub-budget keeps late sources
                    # (QQ Music, Megalobiz, fallback forms) from starving when
                    # LRCLIB/NetEase finish their own request allowance first.
                    key = getattr(provider, '__name__', str(provider))
                    providers = request_budget.setdefault('providers', {})
                    limit = 6 if key == 'recover_upload' else 5 if key == 'lrclib' else self.PROVIDER_REQUEST_CAP
                    self._request_local.provider_budget = providers.setdefault(key, {'requests': 0, 'limit': limit})
                    last_error = None
                    for candidate_form in (form, *following):
                        if not current() or time.monotonic() >= provider_deadline:
                            return None
                        try:
                            found = provider(candidate_form, provider_deadline, offer)
                        except Exception as exc:
                            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429):
                                raise
                            if not following:
                                raise
                            last_error = exc
                            continue
                        if found:
                            return found
                    if last_error is not None:
                        raise last_error
                    return None
                jobs = [(provider, forms[0]) for provider in
                        (self.rich.unison, self.rich.betterlyrics, self.rich.simpmusic,
                         self.lrclib, self.netease, self.genius, self.qqmusic, self.megalobiz,
                         self.public.better_qq, self.public.kugou, self.public.ovh,
                         self.public.recover_upload)]
                for provider, form in jobs:
                    # A slow credited GET must retain room for its search and
                    # base-title fallback; uploader jobs cannot spend LRCLIB's
                    # four-request cap concurrently. Other providers still fan
                    # out immediately, and ordinary lookups keep their schedule.
                    following = forms[1:]
                    future = self.service.submit(run, provider, form, following)
                    if future:
                        futures.add(future)
                    else:
                        # Executor shutdown/overload is not evidence that no
                        # lyrics exist; do not poison the short negative cache.
                        failed = True
                while futures and current():
                    deadline = request_budget['deadline'] or admission_deadline
                    if time.monotonic() >= deadline:
                        break
                    done, futures = concurrent.futures.wait(futures, timeout=min(.1, deadline - time.monotonic()), return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        try:
                            offer(future.result())
                        except Exception:
                            failed = True
                    best = flight['best']
                    # Unknown duration makes every karaoke candidate unsafe, so
                    # an exact plain hit cannot improve further in this lookup.
                    if best and (best.get('syncType') in ('word', 'syllable') or best.get('instrumental') or not duration) and best.get('match_type') == 'exact' and best.get('confidence') == 1:
                        break
                if futures:
                    failed = True
                if not current():
                    failed = True
            result = flight['best'] or {'status': 'unavailable' if failed else 'not_found', 'syncedLyrics': None, 'plainLyrics': None, 'instrumental': False, 'weight': 3}
            offer(result, final=True)
            result = flight['best']
            self._remember(key, result)
            return copy.deepcopy(result)
        finally:
            for future in futures:
                future.cancel()
            with self.service._cache_lock:
                flight['closed'] = True
                flight['result'] = copy.deepcopy(flight['best'] or {'status': 'unavailable', 'weight': 3})
                flight['event'].set()
                self.service._inflight.pop(key, None)
