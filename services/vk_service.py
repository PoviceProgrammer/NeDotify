import os
import re
import time
"""
NeDotify - VK Music Service
Basic VK Music integration with manual link support.
"""

import threading
from typing import Callable, Optional
from urllib.parse import urlsplit
from services.base_service import BaseMusicService, normalize_proxy_url

def _ytdlp():
    """Return the yt-dlp module, importing it on first use.

    yt-dlp costs ~125ms to import and VK extraction only runs on an
    explicit user link, so the import stays off the startup path. Tests
    may monkeypatch the module-level ``yt_dlp`` global; that override
    wins over the import.
    """
    module = globals().get('yt_dlp')
    if module is None:
        try:
            import yt_dlp as module
        except ImportError:
            module = False
        globals()['yt_dlp'] = module
    return module or None


def _has_ytdlp():
    """Availability flag honouring a monkeypatched HAS_YTDLP global."""
    flag = globals().get('HAS_YTDLP')
    if flag is None:
        flag = _ytdlp() is not None
    return flag


def __getattr__(name):
    # PEP 562: resolve 'yt_dlp'/'HAS_YTDLP' before the lazy import ran.
    if name == 'yt_dlp':
        return _ytdlp()
    if name == 'HAS_YTDLP':
        return _has_ytdlp()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


class VKService(BaseMusicService):
    """
    VK Music integration.
    Due to VK's anti-bot protection, full automated parsing is limited.
    Supports direct link playback and basic yt-dlp extraction.
    """

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings

    @property
    def available(self) -> bool:
        # Direct links can be extracted, but this provider has no search API.
        return False

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """
        Search VK Music. Limited functionality due to anti-bot protection.
        Falls back to basic yt-dlp VK extractor.
        """
        if error_callback:
            error_callback('Поиск VK Music недоступен; поддерживаются только прямые ссылки')
        elif callback:
            callback([])

    def get_stream_url(self, vk_url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None, quality: str = "high", **kwargs):
        """Extract audio from a VK Music URL."""
        if not vk_url or not str(vk_url).strip():
            if error_callback:
                error_callback("Пустой или невалидный URL")
            return
        if not _has_ytdlp():
            if error_callback:
                error_callback("yt-dlp не установлен")
            return

        cached = self.get_from_cache(str(vk_url).strip())
        if cached and cached.get("stream_url"):
            if callback:
                callback(cached.get("stream_url"), cached)
            return

        target = urlsplit(str(vk_url or ''))
        if target.scheme != 'https' or target.hostname not in ('vk.com', 'www.vk.com', 'vkvideo.ru'):
            if error_callback:
                error_callback('Нужна HTTPS-ссылка VK')
            return

        def _extract():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'socket_timeout': 10,
                    'retries': 1,
                    'source_address': '0.0.0.0'
                }
                proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', '')) if self.settings else ''
                if proxy:
                    ydl_opts['proxy'] = proxy

                with _ytdlp().YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(vk_url, download=False)

                if info:
                    stream_url = info.get('url')
                    metadata = {
                        'title': info.get('title') or 'VK Hit',
                        'artist': info.get('artist') or info.get('uploader') or 'Unknown Artist',
                        'duration': info.get('duration', 0),
                        'cover_url': info.get('thumbnail', ''),
                        'source_id': str(info.get('id', '')),
                        'stream_url': stream_url
                    }
                    self.set_to_cache(str(vk_url).strip(), metadata)
                    sid = str(info.get('id') or '')
                    if sid:
                        self.set_to_cache(sid, metadata)
                    if callback:
                        callback(stream_url, metadata)
            except Exception as e:
                if error_callback:
                    error_callback(f"VK Music ошибка: {str(e)}")

        if self.submit_playback(_extract) is None and error_callback:
            error_callback('Сервис завершает работу')

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

        if not _has_ytdlp():
            raise Exception("yt-dlp не установлен")

        os.makedirs(output_dir, exist_ok=True)
        clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))
        ts = int(time.time())
        out_template = os.path.join(output_dir, f"vk_{clean_id}_{ts}.%(ext)s")

        target_url = str(source_id).strip()
        if not target_url.startswith(('http://', 'https://')):
            if target_url.startswith('audio'):
                target_url = f"https://vk.com/{target_url}"
            else:
                target_url = f"https://vk.com/audio?id={target_url}"

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
            proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", ""))
            if proxy:
                ydl_opts["proxy"] = proxy
            cookies = self.settings.get("auth", "cookies_file_path", "")
            if cookies and os.path.exists(cookies):
                ydl_opts["cookiefile"] = cookies

        try:
            with _ytdlp().YoutubeDL(ydl_opts) as ydl:
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
                    if fname.startswith(prefix) and not fname.endswith('.part'):
                        return os.path.join(output_dir, fname)

                raise Exception("Файл не был найден после загрузки из VK")
        except Exception:
            try:
                for fname in os.listdir(output_dir):
                    if fname.startswith(f"vk_{clean_id}_") and fname.endswith(".part"):
                        try:
                            os.remove(os.path.join(output_dir, fname))
                        except OSError:
                            pass
            except Exception:
                pass
            raise
