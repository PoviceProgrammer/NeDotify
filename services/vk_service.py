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
        if not _has_ytdlp():
            if error_callback:
                error_callback("yt-dlp не установлен")
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
                        'title': info.get('title', 'Unknown'),
                        'artist': info.get('artist', info.get('uploader', 'Unknown')),
                        'duration': info.get('duration', 0),
                        'cover_url': info.get('thumbnail', ''),
                        'source_id': str(info.get('id', '')),
                        'stream_url': stream_url
                    }
                    if callback:
                        callback(stream_url, metadata)
            except Exception as e:
                if error_callback:
                    error_callback(f"VK Music ошибка: {str(e)}")

        if self.submit_playback(_extract) is None and error_callback:
            error_callback('Сервис завершает работу')

    def play_direct_url(self, url: str) -> dict:
        """Create a track dict from a direct audio URL."""
        return {
            'title': 'VK Audio',
            'artist': 'Unknown',
            'source': 'vk',
            'source_url': url,
            'file_path': url if url.startswith('http') else None
        }
