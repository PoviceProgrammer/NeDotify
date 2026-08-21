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
from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)


class _TTLCache:
    """M-8: bounded cache with TTL and LRU eviction. Thread-safe: instances are
    shared across the service's worker pool, so every mutation happens under a
    lock and the OrderedDict is touched in exactly one place per operation."""

    def __init__(self, max_entries=100, ttl_seconds=600):
        self._data = collections.OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

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
from requests.adapters import HTTPAdapter

class SoundCloudService(BaseMusicService):
    """Client-side SoundCloud audio extraction using high-speed v2 REST API & yt-dlp fallback."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=10)
        self.logger = logging.getLogger(__name__)
        self._ydl = None
        self._ydl_search = None
        self._client_id = None
        self._client_id_lock = threading.Lock()
        self._related_cache = _TTLCache(max_entries=100, ttl_seconds=600)
        self._waveform_cache = _TTLCache(max_entries=100, ttl_seconds=600)
        
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        
        self._executor.submit(self._get_client_id)
        if HAS_YTDLP:
            self._executor.submit(self._get_ydl)

    def _get_client_id(self) -> Optional[str]:
        """Fetch active SoundCloud client_id from soundcloud.com scripts."""
        if self._client_id:
            return self._client_id
        
        with self._client_id_lock:
            if self._client_id:
                return self._client_id
            
            
            fallbacks = [
                'UMY1dzQ68n2QbCuypNe8JOivmV2FO2Ep',
                'IPx78YJ43STMUuy4PfGaiGEwNaWfQ4zq',
                'iZ8g4fkSUAYLLflw8bkKmDGEDFGDVFm1',
                'a3e059563d7fd3372b49b37f00a00bcf',
                'YUKOSUSEbL28wJ3vN3sVNeX34R1h11a0'
            ]
            for cid in fallbacks:
                try:
                    r = self._session.get(f'https://api-v2.soundcloud.com/search/tracks?q=test&client_id={cid}&limit=1', timeout=4.0)
                    if r.status_code == 200:
                        self._client_id = cid
                        return cid
                except Exception as e:
                    self.logger.debug(f'SoundCloud fallback client_id {cid[:6]}... rejected: {e}', exc_info=True)

            try:
                r = self._session.get('https://soundcloud.com', timeout=8.0)
                if r.status_code == 200:
                    script_urls = re.findall(r'src="(https://[a-zA-Z0-9\.-]+\.sndcdn\.com/assets/[^"]+\.js)"', r.text)
                    for url in reversed(script_urls[-8:]):
                        try:
                            js = self._session.get(url, timeout=5.0).text
                            matches = re.findall(r'client_id[:=]["\']([a-zA-Z0-9]{32})["\']', js) + re.findall(r'client_id=([a-zA-Z0-9]{32})', js)
                            for m in matches:
                                test_r = self._session.get(f'https://api-v2.soundcloud.com/search/tracks?q=test&client_id={m}&limit=1', timeout=3.0)
                                if test_r.status_code == 200:
                                    self._client_id = m
                                    return self._client_id
                        except Exception as e:
                            self.logger.debug(f'SoundCloud client_id scrape failed for {url}: {e}', exc_info=True)
            except Exception as e:
                self.logger.warning(f'Could not scrape SoundCloud client_id: {e}')
        return None

    def reset_ydl(self):
        self._ydl = None
        self._ydl_search = None
        self._client_id = None

    def _get_ydl(self):
        if not self._ydl:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestaudio[protocol^=http]/bestaudio/best',
                'nocheckcertificate': True,
                'legacy_server_connect': True,
                'socket_timeout': 10,
                'retries': 1,
                'extractor_retries': 1,
                'source_address': '0.0.0.0',
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            }
            if self.settings:
                proxy = self.settings.get('auth', 'proxy_url', '')
                if proxy:
                    ydl_opts['proxy'] = proxy
                import os
                cookies_file_path = self.settings.get('auth', 'cookies_file_path', '')
                if cookies_file_path and os.path.exists(cookies_file_path):
                    ydl_opts['cookiefile'] = cookies_file_path
            self._ydl = yt_dlp.YoutubeDL(ydl_opts)
        return self._ydl

    def _get_ydl_search(self):
        if not self._ydl_search:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'nocheckcertificate': True,
                'legacy_server_connect': True,
                'socket_timeout': 10,
                'retries': 1,
                'extractor_retries': 1,
                'source_address': '0.0.0.0',
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
            }
            proxy = self.settings.get('auth', 'proxy_url', '') if self.settings else ''
            if proxy:
                ydl_opts['proxy'] = proxy
            self._ydl_search = yt_dlp.YoutubeDL(ydl_opts)
        return self._ydl_search

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
        """Search SoundCloud for tracks (Direct API + yt-dlp fallback)."""
        
        def _search():
            try:
                cache_key = f"sc_search:{query}"
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
                        r = self._session.get(url, timeout=3.0)
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
                                duration = int(item.get('duration', 0) / 1000)
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
                self.logger.warning(f'SoundCloud search failed: {e}. Performing Youtube fallback...')
                try:
                    from services.youtube_service import YouTubeService
                    yt = YouTubeService(self.settings)
                    
                    def yt_cb(tracks):
                        for t in tracks:
                            t['source'] = 'soundcloud'
                        if callback:
                            callback(tracks)
                            
                    yt.search(query, max_results=max_results, callback=yt_cb, error_callback=error_callback)
                except Exception as fall_err:
                    if error_callback:
                        error_callback(f'Поиск недоступен: {fall_err}')
        self._executor.submit(_search)

    def get_playlist_tracks(self, playlist_id, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        """Fetch SoundCloud playlist/set tracks (v2 REST API with yt-dlp fallback)."""
        def _fetch():
            try:
                cache_key = f"sc_playlist:{playlist_id}:{limit}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return

                raw = str(playlist_id).strip()
                cid = self._get_client_id()
                if cid:
                    try:
                        if raw.isdigit():
                            url = f"https://api-v2.soundcloud.com/playlists/{raw}?client_id={cid}"
                        else:
                            url = f"https://api-v2.soundcloud.com/resolve?url={urllib_parse.quote(raw)}&client_id={cid}"
                        r = self._session.get(url, timeout=5.0)
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
                                duration = int(item.get('duration', 0) / 1000)
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

    def get_stream_url(self, track_url: str, callback: Callable = None, error_callback: Callable = None, quality: str = "high", **kwargs):
        """Extract direct audio stream URL from a SoundCloud track."""
        info = self.get_from_cache(track_url)
        if info:
            if callback:
                callback(info.get('stream_url'), info)
            return
            
        

        def _extract():
            stream_url = None
            try:
                cid = self._get_client_id()
                track_id = None
                t_url = None

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
                        r = self._session.get(t_url, timeout=3.5)
                        if r.status_code == 200:
                            t_data = r.json()
                            media = t_data.get('media', {})
                            transcodings = media.get('transcodings', [])
                            stream_url = None

                            sorted_tc = sorted(transcodings, key=lambda x: 0 if x.get('format', {}).get('protocol') == 'progressive' else 1)

                            for tc in sorted_tc:
                                tc_url = f"{tc['url']}?client_id={cid}"
                                tc_resp = self._session.get(tc_url, timeout=2.5)
                                if tc_resp.status_code == 200:
                                    s_candidate = tc_resp.json().get('url')
                                    if s_candidate and 'preview' not in s_candidate:
                                        stream_url = s_candidate
                                        break

                            if stream_url:
                                artwork = t_data.get('artwork_url') or ''
                                if artwork and 'large.jpg' in artwork:
                                    artwork = artwork.replace('large.jpg', 't500x500.jpg')
                                metadata = {
                                    'title': t_data.get('title', 'Unknown'),
                                    'artist': t_data.get('user', {}).get('username', 'Unknown'),
                                    'duration': int(t_data.get('duration', 0) / 1000),
                                    'cover_url': artwork,
                                    'source_id': str(t_data.get('id')),
                                    'stream_url': stream_url
                                }
                                self.set_to_cache(track_url, metadata)
                                if callback:
                                    callback(stream_url, metadata)
                                return
                    except Exception as api_ex:
                        self.logger.warning(f"Fast SoundCloud stream extraction failed: {api_ex}")
                if HAS_YTDLP:
                    url_to_extract = track_url
                    if not url_to_extract.startswith('http'):
                        if url_to_extract.isdigit():
                            url_to_extract = f'https://api-v2.soundcloud.com/tracks/{url_to_extract}'
                        else:
                            url_to_extract = f'https://soundcloud.com/{url_to_extract}'
                        
                    ydl = self._get_ydl()
                    info = ydl.extract_info(url_to_extract, download=False)
                    
                    if info:
                        s_candidate = info.get('url')
                        if s_candidate and '.m3u8' not in s_candidate and 'playlist' not in s_candidate and 'preview' not in s_candidate:
                            stream_url = s_candidate
                            
                    if not stream_url:
                        
                        self.logger.warning('SoundCloud stream is unavailable or preview-only. Falling back to YouTube.')
                        from services.youtube_service import YouTubeService
                        yt = YouTubeService(self.settings)
                        
                        search_title = info.get('title', '') if info else ''
                        search_artist = info.get('uploader', '') if info else ''
                        
                        if not search_title and not search_artist:
                            cached_info = self.get_from_cache(track_url)
                            if cached_info:
                                search_title = cached_info.get('title', '')
                                search_artist = cached_info.get('artist', '')
                                
                        if not search_title:
                            if error_callback:
                                error_callback('Не удалось извлечь метаданные SoundCloud для резервного поиска')
                            return
                            
                        query = f'{search_artist} - {search_title}'.strip(' -')
                        
                        def yt_search_cb(tracks):
                            if tracks:
                                best_match = tracks[0]
                                def yt_stream_cb(yt_url, yt_meta):
                                    final_metadata = {
                                        'title': search_title,
                                        'artist': search_artist,
                                        'duration': best_match.get('duration', track_info.get('duration', 0) if 'track_info' in locals() else 0),
                                        'cover_url': info.get('thumbnail', '') if info else '',
                                        'source_id': str(info.get('id') or '') if info else '',
                                        'stream_url': yt_url
                                    }
                                    self.set_to_cache(track_url, final_metadata)
                                    if callback:
                                        callback(yt_url, final_metadata)
                                        
                                def yt_err_cb(err):
                                    if error_callback:
                                        error_callback(f'Ошибка резервного YouTube-потока: {err}')
                                        
                                yt.get_stream_url(best_match['source_url'], callback=yt_stream_cb, error_callback=yt_err_cb)
                            else:
                                if error_callback:
                                    error_callback('Трек не найден на SoundCloud и YouTube')
                                    
                        def yt_search_err(err):
                            if error_callback:
                                error_callback(f'Ошибка резервного поиска YouTube: {err}')
                                
                        yt.search(query, max_results=1, callback=yt_search_cb, error_callback=yt_search_err)
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
                        self.set_to_cache(track_url, metadata)
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
        self._executor.submit(_extract)
    def download_audio_sync(self, sc_url: str, output_dir: str) -> str:
        """Download audio synchronously, falling back to YouTube if SoundCloud gives preview."""
        import os, time
        if not HAS_YTDLP:
            raise Exception('yt-dlp is missing')
            
        file_name = f'sc_{int(time.time())}.mp3'
        output_path = os.path.join(output_dir, file_name)


        ydl_opts = {'quiet': True, 'no_warnings': True, 'format': 'bestaudio'}
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        
        try:
            info = ydl.extract_info(sc_url, download=False)
        except Exception as e:
            self.logger.debug(f'SoundCloud metadata probe failed for {sc_url}: {e}', exc_info=True)
            info = None
            
        is_preview = False
        if info:
            url_candidate = info.get('url', '')
            if 'preview' in url_candidate:
                is_preview = True
                
        if not info or is_preview:

            from services.youtube_service import YouTubeService
            yt = YouTubeService(self.settings)
            title = info.get('title', 'Unknown') if info else 'Unknown'
            artist = info.get('uploader', 'Unknown') if info else 'Unknown'
            query = f'{artist} - {title}'.strip(' -')
            if not query or query == 'Unknown - Unknown':
                raise Exception('Cannot extract metadata for YouTube fallback')


            yt_dlp_opts = {
                'quiet': True, 'no_warnings': True, 'format': 'bestaudio',
                'outtmpl': output_path,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
            }
            with yt_dlp.YoutubeDL(yt_dlp_opts) as yt_ydl:
                search_res = yt_ydl.extract_info(f'ytsearch1:{query}', download=True)
                if not search_res or not search_res.get('entries'):
                    raise Exception('YouTube fallback search failed')
            return output_path
                
        else:


            dl_opts = {
                'quiet': True, 'no_warnings': True, 'format': 'bestaudio',
                'outtmpl': output_path,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
            }
            with yt_dlp.YoutubeDL(dl_opts) as sc_ydl:
                sc_ydl.download([sc_url])
            return output_path

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
                    duration = int(item.get('duration', 0) / 1000)
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
            r = self._session.get(json_url, timeout=4.0)
            if r.status_code == 200:
                data = r.json()
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