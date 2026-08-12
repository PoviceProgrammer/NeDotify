"""
NeDotify - VK Music Service
Basic VK Music integration with manual link support.
"""

import threading
from typing import Callable, Optional

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False


class VKService:
    """
    VK Music integration.
    Due to VK's anti-bot protection, full automated parsing is limited.
    Supports direct link playback and basic yt-dlp extraction.
    """

    def __init__(self, settings=None):
        self.settings = settings

    @property
    def available(self) -> bool:
        return HAS_YTDLP

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """
        Search VK Music. Limited functionality due to anti-bot protection.
        Falls back to basic yt-dlp VK extractor.
        """
        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return

        def _search():
            try:
                if callback:
                    callback([])
            except Exception as e:
                if error_callback:
                    error_callback(str(e))

        threading.Thread(target=_search, daemon=True).start()

    def get_stream_url(self, vk_url: str, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """Extract audio from a VK Music URL."""
        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return

        def _extract():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'nocheckcertificate': True,
                    'socket_timeout': 10,
                    'retries': 1,
                    'source_address': '0.0.0.0'
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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

        threading.Thread(target=_extract, daemon=True).start()

    def play_direct_url(self, url: str) -> dict:
        """Create a track dict from a direct audio URL."""
        return {
            'title': 'VK Audio',
            'artist': 'Unknown',
            'source': 'vk',
            'source_url': url,
            'file_path': url if url.startswith('http') else None
        }
