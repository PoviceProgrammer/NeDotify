"""
NeDotify - SoundCloud Service
Search and stream audio from SoundCloud via yt-dlp.
"""

from typing import Callable, Optional
import threading
import logging
import time
import collections
from concurrent.futures import ThreadPoolExecutor
from services.base_service import BaseMusicService, normalize_proxy_url

logger = logging.getLogger(__name__)


class _TTLCache:
    """M-8: bounded cache with TTL and LRU eviction. Thread-safe: instances are
    shared across the service's worker pool, so every mutation happens under a
    lock and the OrderedDict is touched in exactly one place per operation."""

    def __init__(self, max_entries=100, ttl_seconds=600, lock=None):
        self._data = collections.OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = lock if lock is not None else threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            timestamp, value = entry
            if time.time() - timestamp > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)  # refresh recency
            return value

    def set(self, key, value):
        with self._lock:
            now = time.time()
            for old_key, (stamp, _) in list(self._data.items()):
                if now - stamp > self._ttl:
                    self._data.pop(old_key, None)
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def __len__(self):
        with self._lock:
            return len(self._data)


try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False


import requests
import re
import urllib.parse as urllib_parse
from utils.requests_transport import PublicHTTPAdapter


#: Extraction failures that no retry can fix. yt-dlp raises these for
#: DRM/licence-protected uploads (its own "This video is DRM protected",
#: extractor/soundcloud.py::report_drm), and for private or deleted tracks.
#: The same answer comes back on every re-resolution, so re-asking is what
#: turned one unplayable track into an endless retry loop.
_UNAVAILABLE_MARKS = (
    'drm',
    'private video',
    'video unavailable',
    'this video is unavailable',
    'has been removed',
    'does not exist',
)

#: How long a track stays marked unplayable. Long enough to outlive the retry
#: storm around one click (proxy self-heal plus the two player.js retries all
#: land within seconds), short enough that a track its owner re-enables is
#: picked up again in the same session.
_UNAVAILABLE_TTL = 3600

_UNAVAILABLE_MSG = 'Трек недоступен: защищён DRM или снят автором'


def _is_drm_transcoding(transcoding: dict) -> bool:
    """True when a transcoding is DRM-protected.

    Same rule yt-dlp applies in `extractor/soundcloud.py::_extract_info_dict`:
    a ``ctr-``/``cbc-`` protocol means common-encryption media, which the
    player cannot decode and which the CDN answers with 403. Reusing the rule
    instead of guessing from the media URL keeps the two extractors in step.
    """
    protocol = str(((transcoding or {}).get('format') or {}).get('protocol') or '').lower()
    return protocol.startswith(('ctr-', 'cbc-'))


def _is_unplayable_error(exc) -> bool:
    """True when an extraction error describes the track, not the network."""
    text = str(exc).lower()
    return any(mark in text for mark in _UNAVAILABLE_MARKS)


#: HTTP statuses that mean "this media is not for you", as opposed to a server
#: that is busy or a socket that timed out. Only these are treated as final;
#: 5xx and transport errors leave the track retryable.
_MEDIA_DENIED_STATUSES = frozenset({401, 403, 404, 410})


def _unavailable_key(track_url) -> str:
    """One key per track, however the caller spelled the id.

    ``2301904229``, ``https://api-v2.soundcloud.com/tracks/2301904229`` and a
    permalink must share one entry, or the memo misses the very call that was
    going to repeat the failure.
    """
    raw = str(track_url or '').strip()
    numeric = re.search(r'/tracks/(\d+)', raw) or re.fullmatch(r'(\d+)', raw)
    if numeric:
        return f'sc_unavailable:{numeric.group(1)}'
    return f'sc_unavailable:{raw.lower()}'


class SoundCloudService(BaseMusicService):
    """Client-side SoundCloud audio extraction using high-speed v2 REST API & yt-dlp fallback."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=10)
        # Reserve independent workers for playback so a search fan-out cannot
        # occupy every provider thread and stall the Play path.
        self._playback_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="SoundCloudPlayback"
        )
        self.logger = logging.getLogger(__name__)
        self._ydl = None
        self._ydl_search = None
        self._ydl_lock = threading.Lock()
        self._ydl_tls = threading.local()
        self._client_id = None
        self._client_id_lock = threading.Lock()
        self._client_id_retry_at = 0.0
        self._client_id_cache = None
        self._rejected_client_ids = collections.deque(maxlen=16)
        self._related_cache = _TTLCache(max_entries=100, ttl_seconds=600)
        self._waveform_cache = _TTLCache(max_entries=100, ttl_seconds=600)
        self._track_metadata_cache = _TTLCache(max_entries=200, ttl_seconds=60,
                                              lock=self._cache_lock)
        # Tracks that cannot be extracted at all (DRM / private / deleted).
        # Reuses the bounded _TTLCache, so a bad track cannot grow the memo and
        # a fixed one comes back after the TTL.
        self._unavailable_cache = self._shared_unavailable
        # Media URLs already probed as servable this session. A cache hit that
        # has not been through the probe yet still has to be checked, so a URL
        # cached before an upload became DRM-protected is not handed to the
        # player; after the first check the replay cost is gone.
        self._verified_cache = self._shared_verified
        
        self._session = requests.Session()
        # The UI search deadline is 8s. Adapter retries multiplied a single
        # read timeout into 24s before the provider fallback could even start.
        adapter = PublicHTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        if self.settings:
            proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
            if proxy:
                self._session.proxies = {'http': proxy, 'https': proxy}
        
        self._executor.submit(self._get_client_id)
        if HAS_YTDLP:
            self._executor.submit(self._get_ydl)

    def _get_client_id(self) -> Optional[str]:
        """Fetch active SoundCloud client_id from soundcloud.com scripts."""
        self.configure_session(self._session)
        if self._client_id:
            return self._client_id
        
        with self._client_id_lock:
            if self._client_id:
                return self._client_id
            # A successful yt-dlp fallback already learned the public app ID.
            # Reuse its cache rather than downloading the homepage/assets again.
            # Only use an existing cache reader: never allocate another yt-dlp
            # instance just to inspect this optional cache.
            with self._cache_lock:
                cache = getattr(self, '_client_id_cache', None)
            if cache is not None:
                try:
                    cached = cache.load('soundcloud', 'client_id')
                    if (isinstance(cached, str) and re.fullmatch(r'[A-Za-z0-9]{32}', cached)
                            and cached not in getattr(self, '_rejected_client_ids', ())):
                        self._client_id = cached
                        return cached
                except Exception:
                    self.logger.debug('SoundCloud public client cache unavailable')
            if time.monotonic() < self._client_id_retry_at:
                return None
            deadline = time.monotonic() + 6.0
            def remaining():
                return max(0.1, min(3.0, deadline - time.monotonic()))
            try:
                r = self._session.get('https://soundcloud.com', timeout=remaining())
                if r.status_code == 200:
                    script_urls = re.findall(r'<script[^>]+src="(https://[a-zA-Z0-9\.-]+\.sndcdn\.com/assets/[^"]+\.js)"', r.text)
                    for url in reversed(script_urls[-4:]):
                        if time.monotonic() >= deadline:
                            break
                        try:
                            js = self._session.get(url, timeout=remaining()).text
                            matches = re.findall(r'client_id\s*[:=]\s*["\']([a-zA-Z0-9]{32})["\']', js)
                            for m in matches:
                                if time.monotonic() >= deadline:
                                    break
                                if m in getattr(self, '_rejected_client_ids', ()):
                                    continue
                                # The real catalog request validates this ID;
                                # _api_get already refreshes a 401/403 once.
                                # Riff likewise uses the ID from the official
                                # asset directly, without a throwaway search.
                                self._client_id = m
                                with self._cache_lock:
                                    cache = getattr(self, '_client_id_cache', None)
                                if cache is not None:
                                    try:
                                        cache.store('soundcloud', 'client_id', m)
                                    except Exception:
                                        self.logger.debug('SoundCloud public client cache could not be saved')
                                return self._client_id
                        except Exception as e:
                            self.logger.debug(f'SoundCloud client_id scrape failed for {url}: {e}', exc_info=True)
            except Exception as e:
                self.logger.warning(f'Could not scrape SoundCloud client_id: {e}')
            # A failed warm-up should not immediately repeat the same scrape
            # on every query. Network/auth setting changes reset this cooldown.
            self._client_id_retry_at = time.monotonic() + 10.0
        return None

    def _api_get(self, url, timeout=4.0):
        """Refresh a rejected public client id once instead of caching it forever."""
        self.configure_session(self._session)
        response = self._session.get(url, timeout=timeout)
        if response.status_code == 429:
            try:
                retry = min(60, max(1, float(response.headers.get('Retry-After', '5'))))
            except (ValueError, TypeError):
                retry = 5
            raise RuntimeError(f'SoundCloud ограничил запросы; повторите через {retry:g} сек.')
        if response.status_code not in (401, 403):
            return response
        parsed = urllib_parse.urlsplit(url)
        query = urllib_parse.parse_qs(parsed.query)
        rejected = (query.get('client_id') or [''])[0]
        with self._client_id_lock:
            rejected_ids = getattr(self, '_rejected_client_ids', None)
            if rejected_ids is None:
                rejected_ids = self._rejected_client_ids = collections.deque(maxlen=16)
            if rejected and rejected not in rejected_ids:
                rejected_ids.append(rejected)
            if self._client_id == rejected:
                self._client_id = None
                self._client_id_retry_at = 0.0
        cid = self._get_client_id()
        if not cid:
            raise RuntimeError('SoundCloud не выдал действующий client_id; повторите позднее')
        query['client_id'] = [cid]
        refreshed = urllib_parse.urlunsplit(parsed._replace(query=urllib_parse.urlencode(query, doseq=True)))
        return self._session.get(refreshed, timeout=timeout)

    def _get_youtube_fallback(self):
        """Reuse the app provider and its caches/pools across fallback requests."""
        with self._cache_lock:
            provider = getattr(self, 'youtube_service', None)
            if provider is None:
                from services.youtube_service import YouTubeService
                provider = self.youtube_service = YouTubeService(self.settings)
            return provider

    def reset_ydl(self):
        self._ydl_tls = threading.local()
        with self._cache_lock:
            self._client_id_cache = None
        with self._client_id_lock:
            self._client_id = None
            self._client_id_retry_at = 0.0
            self._rejected_client_ids = collections.deque(maxlen=16)

    def _public_json(self, url, timeout=4.0):
        """Payload-derived URLs use DNS-pinned public-only redirect handling."""
        from utils.url_safety import guarded_open_url
        import json
        host = (urllib_parse.urlsplit(url).hostname or '').lower()
        if not any(host == suffix or host.endswith('.' + suffix) for suffix in ('soundcloud.com', 'sndcdn.com', 'soundcloud.cloud')):
            raise ValueError('Недопустимый адрес SoundCloud')
        with guarded_open_url(url, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Ответ SoundCloud слишком большой')
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def _get_ydl(self):
        store = getattr(self._ydl_tls, "instances", None)
        if store is None:
            store = {}
            self._ydl_tls.instances = store
        if "main" not in store:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestaudio[protocol^=http]/bestaudio/best',
                'legacy_server_connect': True,
                'socket_timeout': 10,
                'retries': 1,
                'extractor_retries': 1,
                'source_address': '0.0.0.0',
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            }
            if self.settings:
                proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
                if proxy:
                    ydl_opts['proxy'] = proxy
                import os
                cookies_file_path = self.settings.get('auth', 'cookies_file_path', '')
                if cookies_file_path and os.path.exists(cookies_file_path):
                    ydl_opts['cookiefile'] = cookies_file_path
            store["main"] = yt_dlp.YoutubeDL(ydl_opts)
            with self._cache_lock:
                self._client_id_cache = getattr(store['main'], 'cache', None)
        return store["main"]

    def _get_ydl_search(self):
        store = getattr(self._ydl_tls, "instances", None)
        if store is None:
            store = {}
            self._ydl_tls.instances = store
        if "search" not in store:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'legacy_server_connect': True,
                'socket_timeout': 10,
                'retries': 1,
                'extractor_retries': 1,
                'source_address': '0.0.0.0',
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            }
            if self.settings:
                proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
                if proxy:
                    ydl_opts['proxy'] = proxy
            store["search"] = yt_dlp.YoutubeDL(ydl_opts)
            with self._cache_lock:
                self._client_id_cache = getattr(store['search'], 'cache', None)
        return store["search"]

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
        """Search SoundCloud for tracks (Direct API + yt-dlp fallback)."""
        if self.settings and self.settings.get('services', 'soundcloud_enabled', True) is False:
            if callback:
                callback([])
            return None

        cache_key = f'sc_search:{query}:{max_results}'
        cached = self.get_search_cache(cache_key)
        if cached is not None:
            if callback:
                callback(cached)
            return None
        leader, callback, error_callback = self._join_request(cache_key, callback, error_callback)
        if not leader:
            return None
        
        def _search():
            try:
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return
                
                
                cid = self._get_client_id()
                if cid:
                    try:
                        encoded = urllib_parse.quote(query)
                        url = f"https://api-v2.soundcloud.com/search/tracks?q={encoded}&client_id={cid}&limit={max_results}"
                        r = self._api_get(url, timeout=4.0)
                        if r.status_code == 200:
                            data = r.json()
                            tracks = []
                            for item in data.get('collection', []):
                                if not item or not item.get('id'):
                                    continue
                                if 'media' in item:
                                    self._track_metadata_cache.set(str(item['id']), item)
                                artwork = item.get('artwork_url') or ''
                                if artwork and 'large.jpg' in artwork:
                                    artwork = artwork.replace('large.jpg', 't500x500.jpg')
                                
                                user_info = item.get('user', {})
                                artist = user_info.get('username') or user_info.get('full_name') or 'SoundCloud Artist'
                                duration = int((item.get('duration') or 0) / 1000)
                                waveform_url = item.get('waveform_url') or ''
                                
                                track = {
                                    'title': item.get('title', 'Unknown Title'),
                                    'artist': artist,
                                    'duration': duration,
                                    'source': 'soundcloud',
                                    'source_id': str(item.get('id')),
                                    'source_url': item.get('permalink_url') or f"https://soundcloud.com/{item.get('permalink', item.get('id'))}",
                                    'cover_url': artwork,
                                    'waveform_url': waveform_url,
                                }
                                tracks.append(track)
                                
                            if tracks:
                                self.set_search_cache(cache_key, tracks)
                                if callback:
                                    callback(tracks)
                                return
                    except Exception as api_err:
                        self.logger.warning(f"Fast SoundCloud REST API search failed, trying yt-dlp: {api_err}")
                
                
                if HAS_YTDLP:
                    ydl = self._get_ydl_search()
                    result = ydl.extract_info(f'scsearch{max_results}:{query}', download=False)
                    tracks = []
                    if result and 'entries' in result:
                        for entry in result['entries']:
                            if entry:
                                track = {
                                    'title': entry.get('title', 'Unknown'),
                                    'artist': entry.get('uploader', 'Unknown'),
                                    'duration': entry.get('duration', 0),
                                    'source': 'soundcloud',
                                    'source_id': str(entry.get('id') or ''),
                                    'source_url': entry.get('url', entry.get('webpage_url', '')),
                                    'cover_url': entry.get('thumbnail', '')
                                }
                                tracks.append(track)
                    self.set_search_cache(cache_key, tracks)
                    if callback:
                        callback(tracks)
                    return
                
                if error_callback:
                    error_callback('Поиск SoundCloud недоступен')

            except Exception as e:
                if self.settings and self.settings.get('services', 'youtube_enabled', True) is False:
                    if error_callback:
                        error_callback('SoundCloud недоступен; резервный источник YouTube отключён')
                    return
                self.logger.warning(f'SoundCloud search failed: {e}. Performing Youtube fallback...')
                try:
                    yt = self._get_youtube_fallback()
                    
                    def yt_cb(tracks):
                        for t in tracks:
                            t['source'] = 'youtube'
                        if callback:
                            callback(tracks)
                            
                    yt.search(query, max_results=max_results, callback=yt_cb, error_callback=error_callback)
                except Exception as fall_err:
                    if error_callback:
                        error_callback(f'Поиск недоступен: {fall_err}')
        self._executor.submit(_search)

    def get_playlist_tracks(self, playlist_id, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        """Fetch SoundCloud playlist/set tracks (v2 REST API with yt-dlp fallback)."""
        if self.settings and self.settings.get('services', 'soundcloud_enabled', True) is False:
            if callback:
                callback([])
            return None
        def _fetch():
            try:
                cache_key = f"sc_playlist:{playlist_id}:{limit}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return

                raw = str(playlist_id).strip()
                from utils.soundcloud_urls import resolve_playlist_share_url
                raw = resolve_playlist_share_url(raw)
                cid = self._get_client_id()
                if cid:
                    try:
                        if raw.isdigit():
                            url = f"https://api-v2.soundcloud.com/playlists/{raw}?client_id={cid}&limit={limit}"
                        else:
                            url = f"https://api-v2.soundcloud.com/resolve?url={urllib_parse.quote(raw)}&client_id={cid}&limit={limit}"
                        r = self._api_get(url, timeout=4.0)
                        if r.status_code == 200:
                            data = r.json()
                            tracks = []
                            for item in data.get('tracks') or []:
                                if not item or not item.get('id') or not item.get('title'):
                                    continue
                                artwork = item.get('artwork_url') or ''
                                if artwork and 'large.jpg' in artwork:
                                    artwork = artwork.replace('large.jpg', 't500x500.jpg')
                                user_info = item.get('user', {})
                                artist = user_info.get('username') or user_info.get('full_name') or 'SoundCloud Artist'
                                duration = int((item.get('duration') or 0) / 1000)
                                track = {
                                    'title': item.get('title', 'Unknown Title'),
                                    'artist': artist,
                                    'duration': duration,
                                    'source': 'soundcloud',
                                    'source_id': str(item.get('id')),
                                    'source_url': item.get('permalink_url') or f"https://soundcloud.com/{item.get('permalink', item.get('id'))}",
                                    'cover_url': artwork,
                                }
                                tracks.append(track)
                                if limit and len(tracks) >= limit:
                                    break
                            if tracks:
                                self.set_search_cache(cache_key, tracks)
                                if callback:
                                    callback(tracks)
                                return
                    except Exception as api_err:
                        self.logger.warning(f"SoundCloud REST playlist fetch failed: {api_err}")

                if HAS_YTDLP:
                    url_to_extract = raw if raw.startswith('http') else f'https://soundcloud.com/{raw}'
                    ydl = self._get_ydl_search()
                    result = ydl.extract_info(url_to_extract, download=False)
                    tracks = []
                    if result and result.get('entries'):
                        for entry in result['entries']:
                            if not entry:
                                continue
                            track = {
                                'title': entry.get('title', 'Unknown'),
                                'artist': entry.get('uploader', 'Unknown'),
                                'duration': entry.get('duration', 0),
                                'source': 'soundcloud',
                                'source_id': str(entry.get('id') or ''),
                                'source_url': entry.get('url', entry.get('webpage_url', '')),
                                'cover_url': entry.get('thumbnail', '')
                            }
                            tracks.append(track)
                            if limit and len(tracks) >= limit:
                                break
                    if tracks:
                        self.set_search_cache(cache_key, tracks)
                        if callback:
                            callback(tracks)
                        return

                if error_callback:
                    error_callback('Не удалось получить треки плейлиста SoundCloud')

            except Exception as e:
                self.logger.warning(f'SoundCloud playlist fetch failed: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_fetch)

    def get_track_metadata(self, track_id: str) -> dict:
        """Fetch a single track's metadata by numeric id or public permalink.

        Used to backfill cover_url for rows stored before artwork was persisted
        on playback, so library grids stop showing empty placeholders.
        """
        try:
            cid = self._get_client_id()
            if not cid:
                return {}
            target = str(track_id).strip()
            numeric = re.fullmatch(r'\d+', target) or re.search(r'/tracks/(\d+)(?:[/?]|$)', target)
            if numeric:
                sid = numeric.group(1) if numeric.lastindex else numeric.group(0)
                url = f'https://api-v2.soundcloud.com/tracks/{sid}?client_id={cid}'
            elif urllib_parse.urlsplit(target).hostname in ('soundcloud.com', 'www.soundcloud.com'):
                url = f'https://api-v2.soundcloud.com/resolve?url={urllib_parse.quote(target)}&client_id={cid}'
            else:
                return {}
            r = self._api_get(
                url,
                timeout=4.0,
            )
            if r.status_code != 200:
                return {}
            data = r.json() or {}
        except Exception:
            self.logger.debug("get_track_metadata(%s) failed", track_id, exc_info=True)
            return {}

        artwork = data.get("artwork_url") or ""
        if artwork and "large.jpg" in artwork:
            # t500 keeps the download small while staying sharp on a grid tile.
            artwork = artwork.replace("large.jpg", "t500x500.jpg")
        return {
            "title": data.get("title") or "",
            "artist": (data.get("user") or {}).get("username") or "",
            "artist_avatar_url": (data.get("user") or {}).get("avatar_url") or "",
            "cover_url": artwork,
            "source_id": str(data.get("id") or track_id),
            "source_url": data.get("permalink_url") or f"https://soundcloud.com/{track_id}",
            "duration": float(data.get('duration') or 0) / 1000,
        }

    def _mark_unavailable(self, track_url, reason: str) -> None:
        """Remember a track no retry can fix, and drop its cached stream URL.

        Two things have to happen together. The memo makes the next
        ``get_stream_url`` answer from memory, so a proxy 403 no longer turns
        into another full resolution; dropping the cached URL stops the dead
        one from being handed out again before that memo is consulted.
        """
        self.logger.info(f'SoundCloud {track_url} cannot be extracted: {reason}')
        self._unavailable_cache.set(_unavailable_key(track_url), reason)
        # The service cache is shared with every other provider; the
        # "soundcloud:" prefix keeps this from touching another provider's entry.
        with self._cache_lock:
            self._stream_cache.pop(f'soundcloud:{track_url}', None)

    def invalidate_stream_url(self, track_url):
        """Forget provider URL variants after the proxy receives an upstream denial."""
        raw = str(track_url or '').strip()
        if not raw:
            return
        candidates = {raw}
        match = re.search(r'/tracks/(\d+)', raw) or re.fullmatch(r'(\d+)', raw)
        if match:
            track_id = match.group(1)
            candidates.update((track_id, f'https://api-v2.soundcloud.com/tracks/{track_id}'))
        self.invalidate_stream_cache_keys(*(f'soundcloud:{candidate}' for candidate in candidates))

    def _media_url_is_servable(self, url: str) -> bool:
        """Ask the CDN for the first byte instead of trusting the URL.

        The api-v2 payload lists a media URL for DRM-protected tracks too, and
        that URL answers 403 to every playback attempt. Caching it unchecked is
        what made each play start with a 403 that the proxy then tried to
        "heal" into the same dead URL. One ranged GET settles it here, where the
        answer can still change the outcome, instead of at the player.

        Only a denial counts as final: a 5xx or a transport error returns True
        so a flaky network cannot mark a perfectly good track unplayable.
        """
        try:
            import urllib.request
            from utils.url_safety import guarded_open_url
            path = urllib_parse.urlsplit(url).path
            manifest = path.endswith('.m3u8') or '/playlist/' in path
            headers = {} if manifest else {'Range': 'bytes=0-1'}
            with guarded_open_url(urllib.request.Request(url, headers=headers), timeout=3.0) as probe:
                status = probe.status
                # Consume short range replies/manifests so their verified TLS
                # socket can serve the player's next request. Large or unknown
                # bodies remain bounded and are closed without downloading.
                try:
                    length = int(getattr(probe, 'headers', {}).get('Content-Length', '0'))
                except (TypeError, ValueError):
                    length = 0
                if 0 < length <= 65536:
                    body = probe.read(length)
                    content_type = str(getattr(probe, 'headers', {}).get('Content-Type', '')).lower()
                    if (status == 200 and 'mpegurl' in content_type and body.startswith(b'#EXTM3U')
                            and b'#EXT-X-ENDLIST' in body):
                        # The player is about to request this same static VOD
                        # playlist. Reuse its verified body, not another GET.
                        # Never cache live playlists, keys or audio segments.
                        self._shared_manifests.set(url, {'body': body, 'content_type': content_type})
            return status not in _MEDIA_DENIED_STATUSES
        except Exception as e:
            if getattr(e, 'code', None) in _MEDIA_DENIED_STATUSES or isinstance(e, ValueError):
                return False
            self.logger.debug(f'SoundCloud media probe failed for {url[:80]}: {e}')
            return True

    def get_cached_manifest(self, url):
        """A tiny, short-lived VOD playlist already fetched by the media probe."""
        from utils.stream_urls import stream_url_expired
        if stream_url_expired(url):
            return None
        return self._shared_manifests.get(url)

    def get_stream_url(self, track_url: str, callback: Callable = None, error_callback: Callable = None, quality: str = "high", **kwargs):
        """Extract direct audio stream URL from a SoundCloud track."""
        if self.settings and self.settings.get('services', 'soundcloud_enabled', True) is False:
            if error_callback:
                error_callback('Источник SoundCloud отключён в настройках')
            return None
        cache_key = f"soundcloud:{track_url}"
        info = self.get_from_cache(cache_key)
        youtube_enabled = not self.settings or self.settings.get('services', 'youtube_enabled', True) is not False
        if info and info.get('resolved_source') == 'youtube' and not youtube_enabled:
            info = None
        cached_url = info.get('stream_url') if info else None
        if cached_url and self._verified_cache.get(cached_url):
            if callback:
                callback(cached_url, info)
            return

        # A track the CDN already refused to serve once is not asked again.
        # The cache lookup above comes first on purpose: when the YouTube
        # fallback below succeeded, its URL lives in that cache and must keep
        # being served. Only a fresh resolution is short-circuited here, which
        # is what stops proxy 403 -> invalidate -> re-resolve from repeating
        # the same permanent failure on every click.
        unavailable = self._unavailable_cache.get(_unavailable_key(track_url))
        if unavailable and not cached_url:
            self.logger.info(
                f'SoundCloud {track_url} is unavailable ({unavailable}); not re-resolving'
            )
            if error_callback:
                error_callback(_UNAVAILABLE_MSG)
            return

        leader, callback, error_callback = self._join_request(
            f'sc-stream:{cache_key}', callback, error_callback)
        if not leader:
            return None

        def _extract():
            stream_url = None
            try:
                # A prefetch may have finished between the initial cache miss
                # and registration of this worker. Also keep the first probe
                # of an old cache entry inside single-flight, off the caller's
                # thread: simultaneous Play and prefetch must not each spend
                # another CDN round trip checking the same URL.
                cached = self.get_from_cache(cache_key)
                if cached and cached.get('resolved_source') == 'youtube' and not youtube_enabled:
                    cached = None
                cached_url = cached.get('stream_url') if cached else None
                if cached_url:
                    if (cached.get('resolved_source') == 'youtube' or self._verified_cache.get(cached_url)
                            or self._media_url_is_servable(cached_url)):
                        self._verified_cache.set(cached_url, True)
                        callback(cached_url, cached)
                        return
                    # An expired CDN token is not a permanent track verdict.
                    with self._cache_lock:
                        self._stream_cache.pop(cache_key, None)
                cid = self._get_client_id()
                track_id = None
                t_url = None
                api_meta = {}
                preview_only = False

                if str(track_url).isdigit():
                    track_id = str(track_url)
                    t_url = f"https://api-v2.soundcloud.com/tracks/{track_id}?client_id={cid}"
                elif 'tracks/' in str(track_url):
                    parts = str(track_url).split('tracks/')
                    if len(parts) > 1:
                        possible = parts[1].split('/')[0].split('?')[0]
                        if possible.isdigit():
                            track_id = possible
                            t_url = f"https://api-v2.soundcloud.com/tracks/{track_id}?client_id={cid}"
                elif str(track_url).startswith('http'):
                    import urllib.parse
                    t_url = f"https://api-v2.soundcloud.com/resolve?url={urllib.parse.quote(str(track_url))}&client_id={cid}"

                if cid and t_url:
                    try:
                        t_data = self._track_metadata_cache.get(track_id) if track_id else None
                        if t_data is None:
                            r = self._api_get(t_url, timeout=4.0)
                            t_data = r.json() if r.status_code == 200 else None
                        if t_data:
                            preview_only = t_data.get('policy') == 'SNIP'
                            media = t_data.get('media') or {}
                            transcodings = media.get('transcodings', [])
                            stream_url = None

                            # The YouTube fallback below needs a query even when
                            # extraction is impossible, and this payload is the
                            # only place left to read the title from.
                            api_meta = {
                                'title': t_data.get('title', '') or '',
                                'uploader': (t_data.get('user') or {}).get('username', '') or '',
                                'duration': int((t_data.get('duration') or 0) / 1000),
                            }

                            # A DRM transcoding resolves to a media URL the CDN
                            # answers with 403 and no player can decode, so it
                            # must never become a cached stream_url: caching one
                            # is what made every later play start with a 403.
                            has_drm = False
                            sorted_tc = sorted(transcodings, key=lambda x: 0 if (x.get('format') or {}).get('protocol') == 'progressive' else 1)

                            for tc in sorted_tc:
                                if _is_drm_transcoding(tc):
                                    has_drm = True
                                    continue
                                # These are explicitly 30-second samples, or
                                # the broken adaptive format yt-dlp also skips.
                                if (tc.get('snipped') or t_data.get('policy') == 'SNIP'
                                        or str(tc.get('preset', '')).startswith('abr_')):
                                    continue
                                tc_url = f"{tc['url']}?client_id={cid}"
                                tc_data = self._public_json(tc_url, timeout=4.0)
                                if tc_data:
                                    s_candidate = tc_data.get('url')
                                    if s_candidate and 'preview' not in s_candidate:
                                        stream_url = s_candidate
                                        break

                            if stream_url:
                                if self._media_url_is_servable(stream_url):
                                    # The first replay used to repeat the very
                                    # same probe because this result was lost.
                                    self._verified_cache.set(stream_url, True)
                                else:
                                    stream_url = None

                            if stream_url:
                                artwork = t_data.get('artwork_url') or ''
                                if artwork and 'large.jpg' in artwork:
                                    artwork = artwork.replace('large.jpg', 't500x500.jpg')
                                metadata = {
                                    'title': t_data.get('title', 'Unknown'),
                                    'artist': t_data.get('user', {}).get('username', 'Unknown'),
                                    'duration': int((t_data.get('duration') or 0) / 1000),
                                    'cover_url': artwork,
                                    'source_id': str(t_data.get('id')),
                                    'stream_url': stream_url
                                }
                                self.set_to_cache(cache_key, metadata)
                                if callback:
                                    callback(stream_url, metadata)
                                return
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                            TimeoutError, ConnectionError) as api_ex:
                        # The SDK transport may still work when this session
                        # times out (observed with TUN routing). Keep that
                        # same-source fallback before searching another site.
                        # A transient outage must not mark the song unavailable.
                        self.logger.warning('SoundCloud API connection failed: %s', type(api_ex).__name__)
                    except Exception as api_ex:
                        self.logger.warning(f"Fast SoundCloud stream extraction failed: {api_ex}")
                if HAS_YTDLP:
                    url_to_extract = track_url
                    if not url_to_extract.startswith('http'):
                        if url_to_extract.isdigit():
                            url_to_extract = f'https://api-v2.soundcloud.com/tracks/{url_to_extract}'
                        else:
                            url_to_extract = f'https://soundcloud.com/{url_to_extract}'
                        
                    try:
                        # API already identified a preview-only track. Repeating
                        # extraction cannot turn that sample into a full song.
                        info = None if preview_only else self._get_ydl().extract_info(url_to_extract, download=False)
                    except Exception as exc:
                        if not _is_unplayable_error(exc):
                            raise
                        # DRM, private or deleted: this verdict is about the
                        # track, not the network, and yt-dlp will repeat it on
                        # every re-resolution. Remember it, then fall through to
                        # the YouTube fallback instead of aborting the track.
                        self._mark_unavailable(track_url, str(exc))
                        info = None
                    
                    if info:
                        s_candidate = info.get('url')
                        if (s_candidate and 'preview' not in s_candidate
                                and not re.search(r'/playlist/0/30/', s_candidate)):
                            stream_url = s_candidate
                            
                    if not stream_url:
                        if not youtube_enabled:
                            if error_callback:
                                error_callback('SoundCloud недоступен; резервный источник YouTube отключён')
                            return
                        self.logger.warning('SoundCloud stream is unavailable or preview-only. Falling back to YouTube.')
                        yt = self._get_youtube_fallback()
                        
                        search_title = info.get('title', '') if info else ''
                        search_artist = info.get('uploader', '') if info else ''
                        
                        if not search_title and not search_artist:
                            cached_info = self.get_from_cache(cache_key)
                            if cached_info:
                                search_title = cached_info.get('title', '')
                                search_artist = cached_info.get('artist', '')
                            else:
                                search_title = api_meta.get('title', '')
                                search_artist = api_meta.get('uploader', '')
                                
                        if not search_title:
                            if error_callback:
                                error_callback('Не удалось извлечь метаданные SoundCloud для резервного поиска')
                            return
                            
                        query = f'{search_artist} - {search_title}'.strip(' -')
                        
                        def yt_search_cb(tracks):
                            if tracks:
                                from core.playback_recovery import same_recording
                                wanted = {'title': search_title, 'artist': search_artist,
                                          'duration': info.get('duration', 0) if info else api_meta.get('duration', 0)}
                                best_match = next((candidate for candidate in tracks
                                                   if same_recording(wanted, candidate)), None)
                                if best_match is None:
                                    if error_callback:
                                        error_callback('Резервный источник не содержит подходящей версии трека')
                                    return
                                def yt_stream_cb(yt_url, yt_meta):
                                    final_metadata = {
                                        'title': search_title,
                                        'artist': search_artist,
                                        'duration': best_match.get('duration', (info.get('duration', 0) if info else 0)),
                                        'cover_url': info.get('thumbnail', '') if info else '',
                                        'source_id': str(info.get('id') or '') if info else '',
                                        'stream_url': yt_url
                                    }
                                    final_metadata['resolved_source'] = 'youtube'
                                    final_metadata['resolved_source_id'] = best_match.get('source_id')
                                    self.set_to_cache(cache_key, final_metadata)
                                    if callback:
                                        callback(yt_url, final_metadata)
                                        
                                def yt_err_cb(err):
                                    if error_callback:
                                        error_callback(f'Ошибка резервного YouTube-потока: {err}')
                                        
                                # A YouTube search result carries no 'source_url'
                                # key (youtube_service builds it with only
                                # source/source_id/...). Indexing it raised
                                # KeyError('source_url') and killed the whole
                                # fallback; the video id is the correct input.
                                yt_target = best_match.get('source_url') or best_match.get('source_id')
                                if yt_target:
                                    yt.get_stream_url(yt_target, callback=yt_stream_cb, error_callback=yt_err_cb)
                                elif error_callback:
                                    error_callback('Резервный YouTube-поиск не вернул идентификатор трека')
                            else:
                                if error_callback:
                                    error_callback('Трек не найден на SoundCloud и YouTube')
                                    
                        def yt_search_err(err):
                            if error_callback:
                                error_callback(f'Ошибка резервного поиска YouTube: {err}')
                                
                        yt.search(query, max_results=5, callback=yt_search_cb, error_callback=yt_search_err)
                        return
                        
                    if stream_url:
                        metadata = {
                            'title': info.get('title', 'Unknown'),
                            'artist': info.get('uploader', 'Unknown'),
                            'duration': info.get('duration', 0),
                            'cover_url': info.get('thumbnail', ''),
                            'source_id': str(info.get('id') or ''),
                            'stream_url': stream_url
                        }
                        self.set_to_cache(cache_key, metadata)
                        if callback:
                            callback(stream_url, metadata)
                        return
                        
                if error_callback:
                    error_callback('Не удалось получить аудиопоток SoundCloud')
                
            except Exception as e:
                self.logger.exception('Ошибка при извлечении потока SoundCloud')
                if error_callback:
                    error_callback(f'Произошла ошибка: {type(e).__name__} - {str(e)}')
                    return
                return
        self._playback_executor.submit(_extract)
    def download_audio_sync(self, sc_url: str, output_dir: str, download_context=None) -> str:
        """Download audio synchronously, falling back to YouTube if SoundCloud gives preview."""
        import os, time
        if not HAS_YTDLP:
            raise Exception('yt-dlp is missing')

        # Single timestamp for every filename derived from this call, otherwise
        # output_path and outtmpl drift apart by a second and the existence
        # fallback below can never match the real download.
        ts = int(time.time())

        raw_input = str(sc_url).strip()
        sc_url_str = raw_input
        if not sc_url_str.startswith('http'):
            if sc_url_str.isdigit():
                # Bare numeric track id: yt-dlp cannot fetch a permalink from it,
                # the api-v2 track URL is the only resolvable form.
                sc_url_str = f'https://api-v2.soundcloud.com/tracks/{sc_url_str}'
            else:
                # Permalink slug such as "artist/track": qualify it. A value that
                # already contains a slash is used as-is after the host prefix;
                # a bare slug without slash is also prefixed (best effort).
                sc_url_str = f'https://soundcloud.com/{sc_url_str.lstrip("/")}'

        file_name = f'sc_{ts}.mp3'
        output_path = os.path.join(output_dir, file_name)

        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'format': 'bestaudio/best',
            'socket_timeout': 10, 'extractor_retries': 1,
        }
        if self.settings:
            proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
            if proxy:
                ydl_opts['proxy'] = proxy
            cookie_file = self.settings.get('auth', 'cookies_file_path', '')
            if cookie_file and os.path.isfile(cookie_file):
                ydl_opts['cookiefile'] = cookie_file
        if download_context:
            download_context.checkpoint()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(sc_url_str, download=False)
        except Exception as e:
            self.logger.debug(f'SoundCloud metadata probe failed for {sc_url_str}: {e}', exc_info=True)
            if not _is_unplayable_error(e):
                # A timeout must reach the queue's retry policy. Turning it
                # into missing metadata made an ordinary disconnect permanent.
                raise
            info = None
        if download_context:
            download_context.checkpoint()
            
        is_preview = False
        if info:
            url_candidate = info.get('url', '')
            if 'preview' in url_candidate or re.search(r'/playlist/0/30/', url_candidate):
                is_preview = True
                
        if not info or is_preview:
            yt = self._get_youtube_fallback()
            title = info.get('title', 'Unknown') if info else 'Unknown'
            artist = info.get('uploader', 'Unknown') if info else 'Unknown'
            query = f'{artist} - {title}'.strip(' -')
            if not query or query == 'Unknown - Unknown':
                # Try getting cached metadata
                cached = (self.get_from_cache(f"soundcloud:{sc_url}")
                          or self.get_from_cache(f"soundcloud:{sc_url_str}")
                          or self.get_track_metadata(sc_url_str))
                if cached:
                    title = cached.get('title', 'Unknown')
                    artist = cached.get('artist', 'Unknown')
                    query = f'{artist} - {title}'.strip(' -')
                    info = {'duration': cached.get('duration', 0)}
                if not query or query == 'Unknown - Unknown':
                    raise Exception('Cannot extract metadata for YouTube fallback')

            from core.playback_recovery import same_recording
            wanted = {'title': title, 'artist': artist, 'duration': (info or {}).get('duration', 0)}
            candidates = yt.search_sync(query, limit=5)
            if download_context:
                download_context.checkpoint()
            match = next((item for item in candidates or [] if item.get('source_id')
                          and same_recording(wanted, item)), None)
            if match is None:
                raise Exception('Резервный источник не содержит подходящей версии трека')
            return yt.download_audio_sync(match['source_id'], output_dir, download_context=download_context)
                
        else:
            dl_opts = {
                **ydl_opts,
                'quiet': True,
                'no_warnings': True,
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(output_dir, f'sc_{ts}.%(ext)s'),
                # Same throughput settings as the YouTube path: without them
                # yt-dlp fetches one connection with a small buffer, which is
                # the slowest configuration available.
                'concurrent_fragment_downloads': 4,
                'http_chunk_size': 10 * 1024 * 1024,
                'buffersize': 1024 * 1024,
                'retries': 10,
                'extractor_retries': 3,
                'fragment_retries': 10,
                'file_access_retries': 3,
                'socket_timeout': 30,
            }
            if download_context:
                dl_opts.update(download_context.ydl_options(output_dir))
            with yt_dlp.YoutubeDL(dl_opts) as sc_ydl:
                # The preview check just extracted the complete format list.
                # Reprocess it with download options instead of repeating the
                # page/API/manifest requests before transferring any bytes.
                sc_info = sc_ydl.process_ie_result(info, download=True)
                if sc_info:
                    sc_file = sc_ydl.prepare_filename(sc_info)
                    if os.path.exists(sc_file):
                        return sc_file
            if os.path.exists(output_path):
                return output_path
            # Check directory for sc_ file
            for f in os.listdir(output_dir):
                if f.startswith(download_context.stem if download_context else f'sc_{ts}') and not f.endswith('.part'):
                    return os.path.join(output_dir, f)
            # A missing file is a hard failure, not a path (the old silent
            # `return output_path` made the loader blame a "missing" provider
            # response instead of the failed extraction).
            raise Exception('Провайдер soundcloud не создал аудиофайл')

    def get_related_tracks_sync(self, track_id_or_urn: str, limit: int = 15) -> list:
        """Fetch related tracks from SoundCloud API v2 with caching and graceful failover."""
        import time
        if not track_id_or_urn:
            return []

        raw_id = str(track_id_or_urn).strip()
        if "soundcloud:tracks:" in raw_id:
            raw_id = raw_id.split("soundcloud:tracks:")[-1]
        elif "/" in raw_id:
            raw_id = raw_id.rstrip("/").split("/")[-1]

        cache_key = f"sc_rel:{raw_id}:{limit}"
        cached = self._related_cache.get(cache_key)
        if cached is not None:
            return cached

        cid = self._get_client_id()
        if not cid:
            return []

        try:
            url = f"https://api-v2.soundcloud.com/tracks/{raw_id}/related?client_id={cid}&limit={limit}"
            r = self._session.get(url, timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                tracks = []
                for item in data.get('collection', []):
                    if not item or not item.get('id'):
                        continue
                    artwork = item.get('artwork_url') or ''
                    if artwork and 'large.jpg' in artwork:
                        artwork = artwork.replace('large.jpg', 't500x500.jpg')
                    user_info = item.get('user', {})
                    artist = user_info.get('username') or user_info.get('full_name') or 'SoundCloud Artist'
                    duration = int((item.get('duration') or 0) / 1000)
                    waveform_url = item.get('waveform_url') or ''
                    track = {
                        'title': item.get('title', 'Unknown Title'),
                        'artist': artist,
                        'duration': duration,
                        'source': 'soundcloud',
                        'source_id': str(item.get('id')),
                        'source_url': item.get('permalink_url') or f"https://soundcloud.com/{item.get('permalink', item.get('id'))}",
                        'cover_url': artwork,
                        'waveform_url': waveform_url,
                        'genre': item.get('genre') or '',
                    }
                    tracks.append(track)

                if tracks:
                    self._related_cache.set(cache_key, tracks)
                    return tracks
        except Exception as e:
            self.logger.warning(f"SoundCloud related tracks fetch error for {raw_id}: {e}")

        return []

    def get_waveform_data_sync(self, waveform_url: str) -> list:
        """Fetch and normalize audio waveform peaks (samples) to an array of 0.0..1.0 values."""
        if not waveform_url:
            return []

        json_url = waveform_url
        if json_url.endswith('.png'):
            json_url = json_url[:-4] + '.json'

        cached = self._waveform_cache.get(json_url)
        if cached is not None:
            return cached

        try:
            data = self._public_json(json_url, timeout=4.0)
            if data:
                samples = data.get('samples', [])
                height = float(data.get('height') or max(samples or [1]) or 1)

                if samples:
                    normalized = [round(min(1.0, max(0.05, s / height)), 3) for s in samples]
                    target_len = 100
                    if len(normalized) > target_len:
                        step = len(normalized) / float(target_len)
                        resampled = []
                        for i in range(target_len):
                            idx = int(i * step)
                            chunk = normalized[idx : idx + max(1, int(step))]
                            resampled.append(round(max(chunk) if chunk else 0.1, 3))
                        normalized = resampled

                    self._waveform_cache.set(json_url, normalized)
                    return normalized
        except Exception as e:
            self.logger.warning(f"Failed to fetch waveform JSON from {json_url}: {e}")

        return []
    _shared_unavailable = _TTLCache(max_entries=200, ttl_seconds=_UNAVAILABLE_TTL, lock=BaseMusicService._cache_lock)
    _shared_verified = _TTLCache(max_entries=200, ttl_seconds=120, lock=BaseMusicService._cache_lock)
    _shared_manifests = _TTLCache(max_entries=8, ttl_seconds=10, lock=BaseMusicService._cache_lock)
