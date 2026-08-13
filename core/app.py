"""
NeDotify - Application Core
Initializes and wires all application components.
"""

import logging
import os
import pathlib
import subprocess
import sys
import threading
import time

from audio.engine import AudioEngine
from core.database import DatabaseManager
from core.downloader import DownloadManager
from core.plugins import PluginManager
from core.proxy import LocalProxyManager
from core.session import SessionManager
from core.settings import SettingsManager
from services.lufs_scanner import LufsScannerService
from services.lyrics_service import LyricsService
from services.playlist_import_service import PlaylistImportService
from services.p2p_service import P2PService
from services.recommendation_service import RecommendationService
from services.soundcloud_service import SoundCloudService
from services.spotify_service import SpotifyService
from services.vk_service import VKService
from services.watchdog_service import WatchdogService
from services.yandex_service import YandexService
from services.youtube_service import YouTubeService
from services.zapret_service import ZapretService
from core.services.discord_rpc import DiscordRPCService
from utils.cache_manager import CacheManager
from utils.file_scanner import FileScanner

logger = logging.getLogger(__name__)


def update_ytdlp_safely():
    """Update yt-dlp safely if not frozen and last update > 24h ago."""
    if getattr(sys, 'frozen', False):
        return

    try:
        stamp_file = os.path.expanduser("~/.nedotify/.last_ytdlp_update")
        os.makedirs(os.path.dirname(stamp_file), exist_ok=True)

        if os.path.exists(stamp_file):
            last_mtime = os.path.getmtime(stamp_file)
            age_hours = (time.time() - last_mtime) / 3600
            if age_hours < 24:
                logger.info(f"yt-dlp update skipped (last update {age_hours:.1f}h ago)")
                return

        pathlib.Path(stamp_file).touch()
        subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], capture_output=True, timeout=30)
        logger.info("yt-dlp auto-update finished safely.")
    except Exception as e:
        logger.warning(f"Failed to auto-update yt-dlp: {e}")


class AppCore:
    """Central application object that owns and initializes all sub-services."""

    def __init__(self):
        self.update_lock = threading.Lock()

        # Database & Base Services
        self.db = DatabaseManager()
        self.settings = SettingsManager(self.db)
        self.session = SessionManager(self.settings)
        self.cache = CacheManager(self.db)
        self.scanner = FileScanner(self.db)

        # Audio Playback
        self.engine = AudioEngine()
        self.engine.app_core = self

        # Streaming Services
        self.youtube = YouTubeService(self.settings)
        self.soundcloud = SoundCloudService(self.settings)
        self.vk = VKService(self.settings)
        self.yandex = YandexService(self.settings)
        self.spotify = SpotifyService(self.settings)
        self.lyrics = LyricsService(self.settings)
        self.recommendations = RecommendationService(self.db, self.soundcloud, self.youtube)

        # Proxy, Downloader & Plugins
        self.proxy = LocalProxyManager(self)
        self.downloader = DownloadManager(self)
        self.plugins = PluginManager(self)
        self.p2p = P2PService(self.db, self.settings)
        self.zapret = ZapretService(self.settings)
        self.playlist_importer = PlaylistImportService()
        self.watchdog = WatchdogService(self)
        self.lufs_scanner = LufsScannerService(self.db)
        self.discord_rpc = DiscordRPCService(self.settings)
        self.discord_rpc.start()

        # Safe background yt-dlp update
        threading.Thread(target=update_ytdlp_safely, daemon=True).start()

        # Auto-start Zapret if enabled
        try:
            if self.settings.get("zapret", "enabled", False):
                mode = self.settings.get("zapret", "mode", "youtube_discord")
                custom_args = self.settings.get("zapret", "custom_args", "")
                bin_path = self.settings.get("zapret", "binary_path", "")
                self.zapret.start(mode=mode, custom_args=custom_args, binary_path=bin_path)
        except Exception as ze:
            logger.error(f"Failed to auto-start Zapret: {ze}")

        # Start Local Stream Proxy & Load Plugins
        self.proxy.start()
        self.plugins.load_plugins()

    def re_resolve_stream_url_async(self, source, source_id, callback=None, on_error=None, quality="high"):
        """Construct lookup URL, call get_stream_url asynchronously and trigger callbacks."""
        def worker():
            url = None
            if source == "youtube":
                url = f"https://www.youtube.com/watch?v={source_id}"
                service = self.youtube
            elif source == "soundcloud":
                if "/" in str(source_id):
                    url = f"https://soundcloud.com/{source_id}"
                else:
                    url = f"https://api-v2.soundcloud.com/tracks/{source_id}"
                service = self.soundcloud
            elif source == "yandex":
                url = f"https://music.yandex.ru/track/{source_id}"
                service = self.yandex
            else:
                if on_error:
                    on_error(f"Unsupported source: {source}")
                return

            def _on_resolved(stream_url, metadata=None):
                if stream_url:
                    try:
                        self.db.cache_stream(source, source_id, stream_url)
                    except Exception:
                        pass

                    if self.settings and self.settings.get("storage", "auto_cache_streams", False):
                        def delayed_download():
                            try:
                                if getattr(self, "engine", None) and self.engine.queue.current_track:
                                    curr = self.engine.queue.current_track
                                    if curr.get("source_id") == source_id:
                                        self.cache.download_audio_stream(source, source_id, url)
                            except Exception:
                                pass
                        threading.Timer(5.0, delayed_download).start()

                if callback:
                    callback(stream_url, metadata or {"source": source, "source_id": source_id})

            def _on_err(err):
                if on_error:
                    on_error(err)

            try:
                service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
            except Exception as e:
                if on_error:
                    on_error(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def cleanup(self):
        """Clean up all resources upon exit."""
        logger.info("Cleaning up AppCore resources...")
        try:
            if hasattr(self, "watchdog") and self.watchdog:
                self.watchdog.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "lufs_scanner") and self.lufs_scanner:
                self.lufs_scanner.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "downloader") and self.downloader:
                self.downloader.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "p2p") and self.p2p:
                self.p2p.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "plugins") and self.plugins:
                self.plugins.unload_all()
        except Exception:
            pass
        try:
            if hasattr(self, "proxy") and self.proxy:
                self.proxy.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "zapret") and self.zapret:
                self.zapret.stop()
        except Exception:
            pass
