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
from core.resolver import StreamResolver
from core.session import SessionManager
from core.settings import SettingsManager
from services.lufs_scanner import LufsScannerService
from services.lyrics_service import LyricsService
from services.playlist_import_service import PlaylistImportService
from services.recommendation_service import RecommendationService
from services.soundcloud_service import SoundCloudService
from services.spotify_service import SpotifyService
from services.vk_service import VKService
from services.watchdog_service import WatchdogService
from services.yandex_service import YandexService
from services.youtube_service import YouTubeService
from services.zapret_service import ZapretService
from services.audio_fingerprint_service import AudioFingerprintService
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
        pending_file = os.path.expanduser("~/.nedotify/.ytdlp_update_pending")

        if os.path.exists(stamp_file):
            last_mtime = os.path.getmtime(stamp_file)
            age_hours = (time.time() - last_mtime) / 3600
            if age_hours < 24:
                logger.info(f"yt-dlp update skipped (last update {age_hours:.1f}h ago)")
                return

        # M-5: never pip-install while the app is running (can break the imported
        # yt_dlp mid-session) — schedule the update for the next launch instead.
        if not os.path.exists(pending_file):
            pathlib.Path(pending_file).touch()
            logger.info("yt-dlp update deferred to next launch (never mid-run).")
            return

        try:
            os.remove(pending_file)
        except OSError:
            pass
        # M-5: stable releases only (no --pre)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0:
            # M-5: stamp ONLY after a successful update
            pathlib.Path(stamp_file).touch()
            logger.info("yt-dlp auto-update finished safely.")
        else:
            logger.warning(f"yt-dlp update failed (rc={result.returncode}): {(result.stderr or b'')[:200]}")
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
        self.cache = CacheManager(self.db, self.settings)
        self.scanner = FileScanner(self.db)

        # C-3: stream URL cache + single-flight coordinator
        self.resolver = StreamResolver(self.db)

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
        self.recommendations = RecommendationService(settings=self.settings, db=self.db, soundcloud_service=self.soundcloud, youtube_service=self.youtube)

        # Proxy, Downloader & Plugins
        self.proxy = LocalProxyManager(self)
        self.engine.proxy = self.proxy
        self.downloader = DownloadManager(self)
        self.plugins = PluginManager(self)
        self.zapret = ZapretService(self.settings)
        self.playlist_importer = PlaylistImportService()
        self.watchdog = WatchdogService(self)
        self.lufs_scanner = LufsScannerService(self)
        self.audio_fingerprint = AudioFingerprintService()
        self.discord_rpc = DiscordRPCService(self.settings)
        self.discord_rpc.start()

        # Safe background yt-dlp update
        threading.Thread(target=update_ytdlp_safely, daemon=True).start()

        # Periodic background check for Zapret updates
        if hasattr(self, "zapret") and self.zapret:
            self.zapret.auto_update_in_background()

        # Start Local Stream Proxy & Load Plugins
        self.proxy.start()
        self.plugins.load_plugins()

        # Watchdog: monitor playback health (O-13)
        try:
            self.watchdog.start()
        except Exception as we:
            logger.error(f"Failed to start watchdog: {we}")

        # M-9: LUFS/ReplayGain scanner was never started (ProcessPool was idle)
        try:
            self.lufs_scanner.start()
        except Exception as le:
            logger.warning(f"Failed to start LUFS scanner: {le}")

        # O-3: periodic DB cache cleanup by expires_at (every 10 minutes)
        self._cache_cleanup_stop = threading.Event()

        def _cache_cleanup_loop():
            while not self._cache_cleanup_stop.wait(600):
                try:
                    deleted = self.db.cleanup_expired_cache()
                    if deleted:
                        logger.info("[cache] cleaned %d expired stream_cache rows", deleted)
                except Exception as ce:
                    logger.debug("Cache cleanup error: %s", ce)

        threading.Thread(target=_cache_cleanup_loop, name="CacheCleanup", daemon=True).start()

    def start_zapret_if_enabled(self):
        """Start Zapret only if auto_start is enabled in settings. Called AFTER the WebView2
        window finished loading: a cold Zapret launch (winws DPI-desync) slows
        down WebView2 HTTPS handshakes and delays bridge injection."""
        try:
            auto_start = bool(self.settings.get("zapret", "auto_start", False) or self.settings.get("zapret.auto_start", False))
            if auto_start:
                mode = self.settings.get("zapret", "mode", "youtube_discord")
                custom_args = self.settings.get("zapret", "custom_args", "")
                bin_path = self.settings.get("zapret", "binary_path", "")
                threading.Thread(
                    target=self.zapret.start,
                    kwargs={"mode": mode, "custom_args": custom_args, "binary_path": bin_path},
                    daemon=True
                ).start()
        except Exception as ze:
            logger.error(f"Failed to auto-start Zapret: {ze}")

    def re_resolve_stream_url_async(self, source, source_id, callback=None, on_error=None, quality="high", track=None):
        """Construct lookup URL, call get_stream_url asynchronously and trigger callbacks."""
        def worker():
            url = None
            if source in ("youtube", "spotify"):
                sid_str = str(source_id or "").strip()
                if sid_str.startswith("http://") or sid_str.startswith("https://") or sid_str.startswith("ytsearch"):
                    url = sid_str
                elif track and (not sid_str or sid_str == "None" or sid_str.startswith("spotify_")):
                    t_art = track.get("artist", "")
                    t_tit = track.get("title", "")
                    url = f"ytsearch1:{t_art} - {t_tit}"
                else:
                    url = f"https://www.youtube.com/watch?v={sid_str}"
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
                    # Refresh resolver caches so subsequent requests reuse the fresh URL
                    try:
                        self.resolver.refresh(source, source_id, stream_url)
                    except Exception:
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
                if source == "youtube" and hasattr(self, "soundcloud") and self.soundcloud:
                    # Fallback to SoundCloud with track title/artist
                    try:
                        import re
                        t_art = track.get('artist', '') if track and isinstance(track, dict) else ""
                        t_title = track.get('title', '') if track and isinstance(track, dict) else ""
                        if not t_title:
                            try:
                                db_track = self.db.get_track_by_source_id(source, source_id)
                                if db_track:
                                    t_art = db_track.get('artist', '')
                                    t_title = db_track.get('title', '')
                            except Exception:
                                pass

                        if not t_title or t_title == source_id or (len(t_title) == 11 and " " not in t_title):
                            try:
                                import urllib.request, json
                                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={source_id}&format=json"
                                req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                                with urllib.request.urlopen(req, timeout=3.0) as resp:
                                    o_data = json.loads(resp.read().decode('utf-8'))
                                    if o_data.get('title'):
                                        t_title = o_data['title']
                                    if o_data.get('author_name') and not t_art:
                                        t_art = o_data['author_name']
                            except Exception:
                                pass

                        def clean_noise(text):
                            if not text: return ""
                            t = re.sub(r'[\(\[\{][^\)\]\}]*(?:official|video|audio|клип|релиз|remix|edit|lyric|prod|ft\.|feat\.|4k|hd|hq|live|topic)[^\)\]\}]*[\)\]\}]', '', text, flags=re.IGNORECASE)
                            t = re.sub(r'\b(official\s+video|official\s+audio|music\s+video|lyric\s+video|премьера\s+клипа|клип|релиз)\b', '', t, flags=re.IGNORECASE)
                            t = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', t)
                            return ' '.join(t.split()).strip()

                        clean_t = clean_noise(t_title)
                        clean_a = clean_noise(t_art)
                        c_queries = []
                        if ' - ' in clean_t:
                            parts = clean_t.split(' - ', 1)
                            if len(parts) == 2:
                                c_queries.append(f"{parts[0].strip()} {parts[1].strip()}")
                                c_queries.append(clean_t.replace(' - ', ' '))
                                c_queries.append(parts[1].strip())
                        if clean_a and clean_t:
                            clean_a_short = re.sub(r'\s*-\s*Topic\b', '', clean_a, flags=re.IGNORECASE).strip()
                            if clean_a_short.lower() not in clean_t.lower():
                                c_queries.append(f"{clean_a_short} {clean_t}")
                            else:
                                c_queries.append(clean_t)
                        if clean_t:
                            c_queries.append(clean_t)
                        raw = f"{t_art} {t_title}".strip()
                        if raw:
                            c_queries.append(raw)
                        c_queries.append(str(source_id).replace("https://www.youtube.com/watch?v=", ""))

                        candidates = []
                        for q in c_queries:
                            qn = ' '.join(q.split()).strip()
                            if qn and len(qn) > 1 and qn not in candidates:
                                candidates.append(qn)

                        def try_search_candidates(idx=0):
                            if idx >= len(candidates):
                                if on_error:
                                    on_error(err)
                                return

                            sq = candidates[idx]
                            logger.info(f"YouTube resolution failed; trying SoundCloud fallback ({idx+1}/{len(candidates)}) for: {sq}")

                            def on_sc_search_res(res):
                                if res and len(res) > 0:
                                    target_sc = res[0].get("source_url") or res[0].get("source_id")
                                    self.soundcloud.get_stream_url(target_sc, callback=_on_resolved, error_callback=lambda e: try_search_candidates(idx + 1))
                                else:
                                    try_search_candidates(idx + 1)

                            self.soundcloud.search(sq, max_results=3, callback=on_sc_search_res, error_callback=lambda e: try_search_candidates(idx + 1))

                        try_search_candidates(0)
                        return
                    except Exception as fallback_ex:
                        logger.debug(f"SoundCloud fallback search error: {fallback_ex}")
                if on_error:
                    on_error(err)

            try:
                service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
            except Exception as e:
                _on_err(str(e))

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
        try:
            if getattr(self, "_cache_cleanup_stop", None) is not None:
                self._cache_cleanup_stop.set()
        except Exception:
            pass
        # O-15: shutdown(wait=False) all thread pools so app exit never blocks
        try:
            from services.base_service import BaseMusicService
            BaseMusicService._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        for _pool in (
            getattr(self, "downloader", None) and getattr(self.downloader, "_pool", None),
            getattr(self, "cache", None) and getattr(self.cache, "_executor", None),
            getattr(self, "youtube", None) and getattr(self.youtube, "_executor", None),
            getattr(self, "soundcloud", None) and getattr(self.soundcloud, "_executor", None),
            getattr(self, "yandex", None) and getattr(self.yandex, "_executor", None),
            getattr(self, "spotify", None) and getattr(self.spotify, "_executor", None),
        ):
            if _pool is None:
                continue
            try:
                _pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
