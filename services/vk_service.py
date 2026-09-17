"""
NeDotify - VK Music Service
Basic VK Music integration with manual link support and BaseMusicService caching.
"""

import os
import re
import time
from typing import Callable, Optional
from services.base_service import BaseMusicService

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False


class VKService(BaseMusicService):
    """
    VK Music integration.
    Due to VK's anti-bot protection, full automated parsing is limited.
    Supports direct link playback, caching, and basic yt-dlp extraction.
    """

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings

    @property
    def available(self) -> bool:
        return HAS_YTDLP

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """
        Search VK Music. Limited functionality due to anti-bot protection.
        Falls back to basic yt-dlp VK extractor.
        """
        if not query or not str(query).strip():
            if callback:
                callback([])
            return

        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return

        def _search():
            try:
                cache_key = f"vk_search:{query}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return

                # VK anti-bot requires authentication; return empty for raw query
                tracks = []
                self.set_search_cache(cache_key, tracks)
                if callback:
                    callback(tracks)
            except Exception as e:
                if error_callback:
                    error_callback(str(e))

        BaseMusicService.submit(_search)

    @staticmethod
    def _normalize_url(url_or_id: str) -> str:
        """Normalize URL or raw audio ID into a full VK URL."""
        s = str(url_or_id).strip()
        if s.startswith(('http://', 'https://')):
            return s
        if s.startswith('audio') or s.startswith('video'):
            return f"https://vk.com/{s}"
        return f"https://vk.com/audio?id={s}"

    def get_stream_url(self, vk_url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, quality: str = "high", **kwargs):
        """Extract audio from a VK Music URL with caching and error handling."""
        if not vk_url or not str(vk_url).strip():
            if error_callback:
                error_callback("Пустой или невалидный URL")
            return

        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return

        target_url = self._normalize_url(vk_url)
        cached = self.get_from_cache(str(vk_url).strip()) or self.get_from_cache(target_url)
        if cached and cached.get("stream_url"):
            if callback:
                callback(cached.get("stream_url"), cached)
            return

        def _extract():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'nocheckcertificate': True,
                    'socket_timeout': 10,
                    'retries': 2,
                    'source_address': '0.0.0.0'
                }

                if self.settings:
                    proxy = self.settings.get("auth", "proxy_url", "")
                    if proxy:
                        ydl_opts["proxy"] = proxy
                    cookies = self.settings.get("auth", "cookies_file_path", "")
                    if cookies and os.path.exists(cookies):
                        ydl_opts["cookiefile"] = cookies

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)

                if info:
                    stream_url = info.get('url')
                    if not stream_url and info.get('formats'):
                        audio_fmts = [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')]
                        if audio_fmts:
                            stream_url = audio_fmts[-1].get('url')

                    artist = info.get('artist') or info.get('uploader') or 'Unknown Artist'
                    title = info.get('title') or 'VK Audio'
                    duration = info.get('duration') or 0
                    cover_url = info.get('thumbnail') or ''
                    source_id = str(info.get('id') or target_url)

                    metadata = {
                        'title': title,
                        'artist': artist,
                        'duration': duration,
                        'cover_url': cover_url,
                        'source_id': source_id,
                        'stream_url': stream_url
                    }
                    self.set_to_cache(target_url, metadata)
                    if source_id and source_id != target_url:
                        self.set_to_cache(source_id, metadata)
                    raw_in = str(vk_url).strip()
                    if raw_in not in (target_url, source_id):
                        self.set_to_cache(raw_in, metadata)
                    if callback:
                        callback(stream_url, metadata)
                else:
                    if error_callback:
                        error_callback("Не удалось извлечь информацию о треке VK")
            except Exception as e:
                if error_callback:
                    error_callback(f"VK Music ошибка: {str(e)}")

        BaseMusicService.submit(_extract)

    def play_direct_url(self, url: str) -> dict:
        """Create a track dict from a direct audio URL or local file path."""
        url_str = str(url or "").strip()
        is_http = url_str.startswith(('http://', 'https://'))
        return {
            'title': 'VK Audio',
            'artist': 'Unknown',
            'source': 'vk',
            'source_id': url_str,
            'source_url': url_str if is_http else '',
            'stream_url': url_str if is_http else '',
            'file_path': None if is_http else url_str
        }

    def download_audio_sync(self, source_id: str, output_dir: str) -> str:
        """Download audio synchronously from VK via yt-dlp."""
        if not source_id or not str(source_id).strip():
            raise ValueError("source_id не может быть пустым")

        if not HAS_YTDLP:
            raise Exception("yt-dlp не установлен")

        os.makedirs(output_dir, exist_ok=True)
        target_url = self._normalize_url(source_id)
        raw_token = str(source_id).strip().split('/')[-1].split('?')[0]
        clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_token) or "track"
        ts = int(time.time())
        out_template = os.path.join(output_dir, f"vk_{clean_id}_{ts}.%(ext)s")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'nocheckcertificate': True,
            'socket_timeout': 15,
            'retries': 2,
        }

        if self.settings:
            proxy = self.settings.get("auth", "proxy_url", "")
            if proxy:
                ydl_opts["proxy"] = proxy
            cookies = self.settings.get("auth", "cookies_file_path", "")
            if cookies and os.path.exists(cookies):
                ydl_opts["cookiefile"] = cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                if not info:
                    raise Exception("Не удалось извлечь информацию о треке VK")

                file_path = ydl.prepare_filename(info)
                if os.path.exists(file_path):
                    return file_path

                ext = info.get('ext', 'mp3')
                cand = os.path.join(output_dir, f"vk_{clean_id}_{ts}.{ext}")
                if os.path.exists(cand):
                    return cand

                for e in (".mp3", ".m4a", ".webm", ".opus", ".aac", ".ogg"):
                    cand = os.path.join(output_dir, f"vk_{clean_id}_{ts}{e}")
                    if os.path.exists(cand):
                        return cand

                prefix = f"vk_{clean_id}_{ts}"
                for fname in os.listdir(output_dir):
                    if fname.startswith(prefix) and not (fname.endswith('.part') or fname.endswith('.ytdl')):
                        return os.path.join(output_dir, fname)

                raise Exception("Файл не был найден после загрузки из VK")
        except Exception:
            try:
                prefix = f"vk_{clean_id}_{ts}"
                for fname in os.listdir(output_dir):
                    if fname.startswith(prefix) and (fname.endswith('.part') or fname.endswith('.ytdl')):
                        try:
                            os.remove(os.path.join(output_dir, fname))
                        except OSError:
                            pass
            except Exception:
                pass
            raise
