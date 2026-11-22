"""Search public Hitmos and LMusic pages and resolve the MP3 files they expose."""

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
# Media is served from the sites' own CDNs. Anything else is not this provider's
# audio, so it must never reach the player or the downloader.
_AUDIO_HOSTS = {'hitmos': ('hitmos.fm',), 'lmusic': ('lmusic.kz',)}
_AUDIO_TYPES = frozenset({'audio/mpeg', 'audio/mp3', 'application/octet-stream'})
# A search page lists dozens of rows; the song page embeds one. Both are
# bounded so a hostile or runaway page cannot exhaust memory.
_PAGE_BYTES = 2 * 1024 * 1024
_MAX_PAGE_URLS = 64

# Hitmos embeds its rows as a Next.js flight payload: escaped JSON with the
# track id, its play URL and its download URL side by side.
_HITMOS_TRACK_JSON = re.compile(
    r'"id":(\d{1,12}),"title":"(?:[^"\\]|\\.)*?","artist":"(?:[^"\\]|\\.)*?",'
    r'"duration":(?:null|\d+),"play":"([^"]*)","download":"([^"]*)"')


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


def _audio_url(source, url):
    """Accept only a plain HTTPS MP3 served from the source's own CDN."""
    try:
        parsed = urlsplit(str(url or ''))
    except ValueError:
        return ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ''
    host = (parsed.hostname or '').lower()
    if not any(host == suffix or host.endswith('.' + suffix) for suffix in _AUDIO_HOSTS[source]):
        return ''
    if not parsed.path.lower().endswith('.mp3') or re.search(r'[\s\\\'"<>]', parsed.path):
        return ''
    return url


def _hitmos_audio_urls(markup):
    """Track id -> MP3 URL, read from the payload a Hitmos page embeds."""
    urls = {}
    for match in _HITMOS_TRACK_JSON.finditer(markup.replace('\\"', '"')):
        url = _audio_url('hitmos', match.group(3)) or _audio_url('hitmos', match.group(2))
        if url:
            urls.setdefault(match.group(1), url)
    return urls


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
        # Audio URLs the last search page already carried, so resolving a
        # listed track needs no second page request. Bounded by _MAX_PAGE_URLS.
        self._page_urls = {}

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
                markup = response.read(_PAGE_BYTES).decode('utf-8', errors='replace')
            parser.feed(markup)
            tracks = [track for track in parser.tracks.values() if track['title']][:12]
            if self.source == 'hitmos':
                urls = _hitmos_audio_urls(markup)
                self._remember_page_urls({track['source_id']: urls[track['source_id']]
                                          for track in tracks if track['source_id'] in urls})
            if tracks:
                self.set_search_cache(key, tracks)
            if not is_current or is_current():
                callback(tracks)
        except (OSError, ValueError) as exc:
            error_callback(exc)

    def resolve_audio(self, source_id):
        """Return a playable/downloadable MP3 URL for a track id, or None."""
        sid = str(source_id)
        if not re.fullmatch(r'[0-9]{1,12}', sid):
            return None
        key = f'{self.source}:audio:{sid}'
        cached = self.get_from_cache(key)
        if isinstance(cached, dict) and cached.get('url'):
            return cached['url']
        url = self._candidate_audio_url(sid)
        if not url or not self._audio_stream_ok(url):
            return None
        self.set_to_cache(key, {'url': url})
        return url

    def _remember_page_urls(self, urls):
        """Replace the remembered map atomically; guarded by the class cache lock."""
        with self._cache_lock:
            self._page_urls = dict(urls)

    def _page_url(self, sid):
        with self._cache_lock:
            return self._page_urls.get(sid, '')

    def _remember_page_url(self, sid, url):
        with self._cache_lock:
            if len(self._page_urls) >= _MAX_PAGE_URLS:
                return
            self._page_urls[sid] = url

    def _candidate_audio_url(self, sid):
        """The provider's own URL for this track, before it is verified."""
        if self.source == 'lmusic':
            return SITES['lmusic'] + '/api/stream/' + sid
        return self._hitmos_audio_url(sid)

    def _hitmos_audio_url(self, sid):
        known = self._page_url(sid)
        if known:
            return known
        # Reached for ids from an imported playlist or a saved row: the search
        # page that carried them is long gone, so read the song page instead.
        request = Request(SITES['hitmos'] + '/song/' + sid, headers={'Accept-Encoding': 'identity'})
        try:
            with guarded_open_url(request, timeout=5) as response:
                markup = response.read(_PAGE_BYTES).decode('utf-8', errors='replace')
        except (OSError, ValueError):
            return ''
        url = _hitmos_audio_urls(markup).get(sid, '')
        if url:
            self._remember_page_url(sid, url)
        return url

    def invalidate_stream_url(self, source_id):
        """Forget a CDN URL the proxy or the downloader saw rejected."""
        sid = str(source_id or '').strip()
        if re.fullmatch(r'[0-9]{1,12}', sid):
            self.invalidate_stream_cache_keys(f'{self.source}:audio:{sid}')
            with self._cache_lock:
                self._page_urls.pop(sid, None)

    @staticmethod
    def _audio_stream_ok(url):
        """Confirm the URL really is a complete MP3 before offering it."""
        request = Request(url, headers={'Range': 'bytes=0-4095', 'Accept-Encoding': 'identity'})
        try:
            with guarded_open_url(request, timeout=4) as response:
                if response.headers.get_content_type() not in _AUDIO_TYPES:
                    return False
                data = response.read(4096)
        except (OSError, ValueError):
            return False
        return data.startswith(b'ID3') or len(data) > 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0

    def download_audio_sync(self, source_id, directory, download_context=None):
        url = self.resolve_audio(source_id)
        if not url or download_context is None:
            raise ValueError('Аудиофайл на сайте недоступен')
        return download_context.download_http(url, os.path.join(directory, download_context.stem + '_web.mp3'))
