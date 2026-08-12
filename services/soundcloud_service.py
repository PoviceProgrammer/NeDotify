"""
NeDotify - SoundCloud Service
Search and stream audio from SoundCloud via yt-dlp.
"""

from typing import Callable, Optional
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False


import requests
import re
import urllib.parse as urllib
import ssl
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class CustomSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        except Exception:
            pass
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

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
        
        self._session = requests.Session()
        adapter = CustomSSLAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)
        self._session.verify = False
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
            
            
            fallbacks = ['IPx78YJ43STMUuy4PfGaiGEwNaWfQ4zq', 'iZ8g4fkSUAYLLflw8bkKmDGEDFGDVFm1', 'a3e059563d7fd3372b49b37f00a00bcf', 'YUKOSUSEbL28wJ3vN3sVNeX34R1h11a0']
            for cid in fallbacks:
                try:
                    r = self._session.get(f'https://api-v2.soundcloud.com/search/tracks?q=test&client_id={cid}&limit=1', timeout=5.0)
                    if r.status_code == 200:
                        self._client_id = cid
                        return cid
                except Exception:
                    pass
            
            
            try:
                r = self._session.get('https://soundcloud.com', timeout=8.0)
                if r.status_code == 200:
                    script_urls = re.findall(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', r.text)
                    for url in reversed(script_urls[-5:]):
                        try:
                            js = self._session.get(url, timeout=5.0).text
                            match = re.search(r'client_id[:=]"([a-zA-Z0-9]{32})"', js)
                            if match:
                                self._client_id = match.group(1)
                                return self._client_id
                        except Exception:
                            pass
            except Exception as e:
                self.logger.warning(f'Could not scrape SoundCloud client_id: {e}')
            pass
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
                        encoded = urllib.parse.quote(query)
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
                                
                                track = {
                                    'title': item.get('title', 'Unknown Title'),
                                    'artist': artist,
                                    'duration': duration,
                                    'source': 'soundcloud',
                                    'source_id': str(item.get('id')),
                                    'source_url': item.get('permalink_url') or f"https://soundcloud.com/{item.get('permalink', item.get('id'))}",
                                    'cover_url': artwork
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
                    from services.youtube_service import YoutubeService
                    yt = YoutubeService(self.settings)
                    
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

    def get_stream_url(self, track_url: str, callback: Callable = None, error_callback: Callable = None):
        """Extract direct audio stream URL from a SoundCloud track."""
        info = self.get_from_cache(track_url)
        if info:
            if callback:
                callback(info.get('stream_url'), info)
            return
            
        

        def _extract():
            try:
                cid = self._get_client_id()
                track_id = None
                if track_url.isdigit():
                    track_id = track_url
                elif 'tracks/' in track_url:
                    parts = track_url.split('tracks/')
                    if len(parts) > 1:
                        possible = parts[1].split('/')[0].split('?')[0]
                        if possible.isdigit():
                            track_id = possible

                if cid and track_id:
                    try:
                        t_url = f"https://api-v2.soundcloud.com/tracks/{track_id}?client_id={cid}"
                        r = self._session.get(t_url, timeout=2.5)
                        if r.status_code == 200:
                            t_data = r.json()
                            media = t_data.get('media', {})
                            transcodings = media.get('transcodings', [])
                            stream_url = None
                            
                            
                            
                            sorted_tc = sorted(transcodings, key=lambda x: 0 if x.get('format', {}).get('protocol') == 'progressive' else 1)
                            
                            for tc in sorted_tc:
                                tc_url = f"{tc['url']}?client_id={cid}"
                                tc_resp = self._session.get(tc_url, timeout=2.0)
                                if tc_resp.status_code == 200:
                                    s_candidate = tc_resp.json().get('url')
                                    
                                    if s_candidate and '.m3u8' not in s_candidate and 'playlist' not in s_candidate and 'preview' not in s_candidate:
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
                        self.logger.warning(f"Fast SoundCloud stream extraction failed, trying yt-dlp: {api_ex}")
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
        except Exception:
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