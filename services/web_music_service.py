"""Search public Hitmos and LMusic pages and verify exposed audio streams."""

from html.parser import HTMLParser
import os
import re
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request

from services.base_service import BaseMusicService
from utils.url_safety import guarded_open_url


SITES = {'hitmos': 'https://rus.hitmos.fm', 'lmusic': 'https://lmusic.kz'}
_PAGES = {'hitmos': re.compile(r'/song/(\d+)/?'), 'lmusic': re.compile(r'/mp3/[^/]+/(\d+)/?')}
_HOSTS = {'hitmos': {'hitmos.fm', 'rus.hitmos.fm'}, 'lmusic': {'lmusic.kz'}}


def identify_track_page(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    for source, hosts in _HOSTS.items():
        match = _PAGES[source].fullmatch(parsed.path)
        if parsed.hostname in hosts and match:
            return source, match.group(1)
    return None


def _public_page_url(source, path, sid):
    url = urljoin(SITES[source], path)
    return url if identify_track_page(url) == (source, sid) else ''


class _SearchPage(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.tracks = {}
        self._current = None
        self._capture = None
        self._cover = ''

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = (attr.get('class') or '').split()
        if self.source == 'lmusic' and 'c-card-mp3' in classes:
            sid = attr.get('data-mp3_id') or ''
            page = _public_page_url(self.source, attr.get('data-url') or '', sid)
            if page and attr.get('data-song_name'):
                cover = attr.get('data-cover_url') or ''
                self.tracks[sid] = self._track(sid, page, attr['data-song_name'], attr.get('data-artist_name'),
                                               cover if cover.startswith('https://s3.rs-cont.ru/') else '')
                self._current = self.tracks[sid]
            else:
                self._current = None
        if self.source == 'hitmos' and 'track-item' in classes:
            self._current = None
            self._cover = ''
        if self.source == 'hitmos' and tag == 'img':
            candidate = attr.get('src') or ''
            if candidate.startswith('https://static-c1.hitmos.fm/'):
                self._cover = candidate
        if self.source == 'hitmos' and tag == 'a' and 'track-item__title' in classes:
            path = attr.get('href') or ''
            match = _PAGES['hitmos'].fullmatch(path)
            if match:
                sid = match.group(1)
                self._current = self.tracks.setdefault(sid, self._track(sid, SITES['hitmos'] + path, cover=self._cover))
                self._capture = (tag, 'title')
        if self._current is not None:
            if 'track-item__artist' in classes:
                self._capture = (tag, 'artist')
            elif any(cls.endswith(('__duration', '__time')) for cls in classes):
                self._capture = (tag, 'duration')

    def handle_endtag(self, tag):
        if self._capture and tag == self._capture[0]:
            self._capture = None

    def handle_data(self, text):
        if not self._capture:
            return
        field = self._capture[1]
        text = text.strip()
        if field == 'duration':
            match = re.fullmatch(r'(\d{1,3}):(\d\d)', text)
            if match:
                self._current[field] = int(match[1]) * 60 + int(match[2])
        elif text:
            value = self._current[field]
            if not value:
                self._current[field] = text

    def _track(self, sid, page, title='', artist='', cover=''):
        return {'source': self.source, 'source_id': sid, 'source_url': page, 'title': title,
                'artist': artist or '', 'cover_url': cover, 'duration': 0}


class WebMusicService(BaseMusicService):
    def __init__(self, source):
        super().__init__()
        self.source = source

    def search(self, query, callback, error_callback, result_type=None, is_current=None):
        if result_type not in (None, 'all', 'track', 'tracks') or len(query) < 3:
            callback([])
            return
        key = f'{self.source}:search:{query.casefold()}'
        cached = self.get_search_cache(key)
        if cached is not None:
            callback(cached)
            return
        try:
            parser = _SearchPage(self.source)
            url = SITES[self.source] + '/search?' + urlencode({'q': query})
            with guarded_open_url(url, timeout=5) as response:
                parser.feed(response.read(1024 * 1024).decode('utf-8', errors='replace'))
            tracks = [track for track in parser.tracks.values() if track['title']][:12]
            if tracks:
                self.set_search_cache(key, tracks)
            if not is_current or is_current():
                callback(tracks)
        except (OSError, ValueError) as exc:
            error_callback(exc)

    def resolve_audio(self, source_id):
        sid = str(source_id)
        if self.source != 'lmusic' or not re.fullmatch(r'[0-9]{1,12}', sid):
            return None
        url = SITES[self.source] + '/api/stream/' + sid
        key = f'{self.source}:audio:{sid}'
        if self.get_from_cache(key):
            return url
        request = Request(url, headers={'Range': 'bytes=0-4095', 'Accept-Encoding': 'identity'})
        try:
            with guarded_open_url(request, timeout=4) as response:
                media_type = response.headers.get_content_type()
                if media_type not in ('audio/mpeg', 'audio/mp3', 'application/octet-stream'):
                    return None
                data = response.read(4096)
                if not (data.startswith(b'ID3') or len(data) > 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0):
                    return None
        except (OSError, ValueError):
            return None
        self.set_to_cache(key, {'url': url})
        return url

    def download_audio_sync(self, source_id, directory, download_context=None):
        url = self.resolve_audio(source_id)
        if not url or download_context is None:
            raise ValueError('Аудиофайл на сайте недоступен')
        return download_context.download_http(url, os.path.join(directory, download_context.stem + '_web.mp3'))
