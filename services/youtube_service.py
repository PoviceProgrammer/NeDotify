"""
NeDotify - YouTube Service
Search and stream audio from YouTube/YouTube Music via yt-dlp.
"""

import time

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

try:
    from ytmusicapi import YTMusic
    HAS_YTMUSIC = True
except ImportError:
    HAS_YTMUSIC = False





class YouTubeService(BaseMusicService):
    """Client-side YouTube audio extraction using yt-dlp."""



    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._ytmusic = None
        if HAS_YTMUSIC:
            import requests
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
                        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
                    except Exception:





                        pass
                    kwargs["ssl_context"] = ctx


                    return super().init_poolmanager(*args, **kwargs)



            class TimeoutSession(requests.Session):
                def request(self, *args, **kwargs):
                    kwargs["timeout"] = 15
                    return super().request(*args, **kwargs)

            session = TimeoutSession()
            adapter = CustomSSLAdapter(pool_connections=30, pool_maxsize=30, max_retries=2)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.verify = False
            proxy = self.settings.get("auth", "proxy_url", "") if self.settings else ""
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
            self._ytmusic = YTMusic(requests_session=session)

        self._ydl = None
        self._ydl_fallback = None

        if HAS_YTDLP:
            self._executor.submit(self._get_ydl, "high")


    def reset_ydl(self):
        self._ydl = None
        self._ydl_fallback = None











        if HAS_YTMUSIC:
            if self.settings:
                proxy = self.settings.get("auth", "proxy_url", "")









                import requests
                from requests.adapters import HTTPAdapter

                class TimeoutSession(requests.Session):
                    def request(self, *args, **kwargs):
                        kwargs["timeout"] = 15
                        return super().request(*args, **kwargs)

                session = TimeoutSession()
                adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=2)






                session.mount("https://", adapter)





                session.mount("http://", adapter)
                if proxy:
                    session.proxies = {"http": proxy, "https": proxy}
                self._ytmusic = YTMusic(requests_session=session)

    def _get_ydl(self, quality="high", fallback=False):
        quality_map = {
            "low": "bestaudio/best",
            "medium": "bestaudio/best",
            "high": "bestaudio/best",
            "lossless": "bestaudio/best",
        }

        if fallback:
            if not self._ydl_fallback:
                opts = self._get_ydl_opts("bestaudio/best", fallback=True)
                self._ydl_fallback = yt_dlp.YoutubeDL(opts)
            return self._ydl_fallback





















        if not self._ydl:
            opts = self._get_ydl_opts(quality_map.get(quality, "bestaudio/best"))
            self._ydl = yt_dlp.YoutubeDL(opts)
        return self._ydl

    def _prefetch_top_tracks(self, tracks: list):
        """Background daemon thread to pre-resolve stream URLs for top search results."""
        for trk in tracks[:2]:
            try:
                sid = trk.get("source_id")
                surl = trk.get("source_url") or sid
                if surl and not self.get_from_cache(surl):
                    self.get_stream_url(surl, quality="high")
            except Exception:
                continue

    def _get_ydl_opts(self, format_str, fallback=False):
        import os

        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": format_str or "bestaudio/best",
            "noplaylist": True,
            "nocheckcertificate": True,
            "skip_download": True,
            "extractor_args": {"youtube": ["player_client=android,mweb,ios,web"]},
            "socket_timeout": 5,
            "retries": 1,
            "extractor_retries": 1,
            "source_address": "0.0.0.0",
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        }

        if fallback:
            opts["extractor_args"] = {"youtube": ["player_client=mweb,ios,web,tv"]}
            opts["format"] = "bestaudio/best/ba/b/worst"
            opts["ignoreerrors"] = True

        if self.settings:
            if not fallback:
                cookies_file_path = self.settings.get("auth", "cookies_file_path", "")
                if cookies_file_path and os.path.exists(cookies_file_path):
                    opts["cookiefile"] = cookies_file_path
                proxy = self.settings.get("auth", "proxy_url", "")
                if proxy:
                    opts["proxy"] = proxy
        return opts

    @property
    def available(self) -> bool:
        return HAS_YTDLP

    def search(self, query: str, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
        """Search YouTube for tracks. Runs in background thread."""
        if not HAS_YTDLP or not HAS_YTMUSIC:
            if error_callback:
                error_callback("yt-dlp или ytmusicapi не установлены")
            return None


        def _search():
            try:

                cache_key = f"yt_search:{query}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return None

                results = self._ytmusic.search(query, filter=None, limit=max_results)

                tracks = []
                seen_ids = set()
                for item in results:
                    rtype = item.get("resultType", "")
                    if rtype not in ("song", "video"):
                        continue
                    vid = item.get("videoId")
                    if not vid or vid in seen_ids:
                        continue

                    seen_ids.add(vid)

                    source_id = vid
                    title = item.get("title", "Unknown Title")

                    artists_list = item.get("artists", [])
                    artist = ", ".join([a["name"] for a in artists_list if "name" in a])
                    if not artist:
                        artist = "Unknown Artist"

                    duration = item.get("duration_seconds", 0)
                    if duration == 0 and item.get("duration"):
                        try:
                            parts = item["duration"].split(":")
                            if len(parts) == 2:
                                duration = int(parts[0]) * 60 + int(parts[1])
                            elif len(parts) == 3:
                                duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        except:
                            duration = 0

                    cover_url = ""
                    if item.get("thumbnails") and len(item["thumbnails"]) > 0:
                        cover_url = item["thumbnails"][-1]["url"]
                    else:
                        cover_url = f"https://img.youtube.com/vi/{source_id}/hqdefault.jpg"

                    track = {
                        "title": title,
                        "artist": artist,
                        "cover_url": cover_url,
                        "duration": duration,
                        "source": "youtube",
                        "source_id": source_id,
                        "source_url": f"https://www.youtube.com/watch?v={source_id}",
                    }
                    tracks.append(track)

                self.set_search_cache(cache_key, tracks)

                if tracks:
                    self._executor.submit(self._prefetch_top_tracks, tracks)
                if callback:
                    callback(tracks)
                return None
            except Exception as e:
                self.logger.exception("Ошибка при поиске YouTube")
                if error_callback:
                    error_callback(f"Произошла ошибка: {type(e).__name__} - {str(e)}")
                return None

        self._executor.submit(_search)
        return None

    def _extract_info_safe(self, video_url: str, quality: str, fallback: bool = False):
        opts = self._get_ydl_opts("bestaudio/best", fallback=fallback)
        if not fallback and self._ydl:
            ydl = self._ydl
        else:
            ydl = yt_dlp.YoutubeDL(opts)

        try:
            return ydl.extract_info(video_url, download=False)
        except Exception as e:
            err_msg = str(e)
            err_lower = err_msg.lower()

            if any(k in err_lower for k in ("database", "locked", "sqlite", "profile")):
                logger.warning("YouTube cookies locked. Retrying extraction without cookies.")
                clean_opts = opts.copy()
                clean_opts.pop("cookiesfrombrowser", None)
                clean_opts.pop("cookiefile", None)

                try:
                    with yt_dlp.YoutubeDL(clean_opts) as ydl_clean:
                        return ydl_clean.extract_info(video_url, download=False)
                except Exception as e_clean:
                    err_msg = str(e_clean)
                    err_lower = err_msg.lower()

            if any(k in err_lower for k in ("confirm your age", "sign in", "inappropriate")):
                configured_browser = "none"
                if self.settings:
                    configured_browser = self.settings.get("auth", "browser_cookies", "none")

                browsers = ["chrome", "edge", "firefox", "opera"]
                for browser in browsers:
                    if browser == configured_browser:
                        continue
                    logger.info(f"Age gate bypass: trying cookies from browser: {browser}")
                    cookie_opts = opts.copy()
                    cookie_opts["cookiesfrombrowser"] = (browser,)

                    try:
                        with yt_dlp.YoutubeDL(cookie_opts) as ydl_cookie:
                            return ydl_cookie.extract_info(video_url, download=False)
                    except Exception as cookie_err:
                        logger.warning(f"Bypassing age gate with browser '{browser}' failed: {cookie_err}")
            raise e

    def get_stream_url(self, video_url: str, callback: Callable = None, error_callback: Callable = None, quality: str = "high"):
        """Extract direct audio stream URL from a YouTube video."""
        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return None

        info = self.get_from_cache(video_url)
        if info:
            if callback:
                callback(info.get("stream_url"), info)
            return None

        def _extract():
            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    info = None
                    try:
                        info = self._extract_info_safe(video_url, quality, fallback=False)
                    except Exception as exc:
                        err_msg = str(exc)
                        err_lower = err_msg.lower()

                        if any(k in err_lower for k in ("database", "locked", "sqlite", "profile")):
                            if error_callback:
                                error_callback("Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt")
                            return None


                        logger.debug(f"First extraction failed: {err_msg}. Trying fallback...")
                        try:
                            info = self._extract_info_safe(video_url, quality, fallback=True)
                        except Exception as exc2:
                            err_msg2 = str(exc2)
                            err_lower2 = err_msg2.lower()
                            if any(k in err_lower2 for k in ("database", "locked", "sqlite", "profile")):
                                if error_callback:
                                    error_callback("Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt")
                                return None

                            if error_callback:
                                error_callback(err_msg2)
                            return None

                    if info:
                        if info.get("_type") == "playlist" and "entries" in info and len(info["entries"]) > 0:
                            info = info["entries"][0]

                        stream_url = info.get("url")
                        if not stream_url and info.get("requested_formats"):
                            for fmt in info["requested_formats"]:
                                if fmt.get("acodec") != "none" and fmt.get("url"):
                                    stream_url = fmt.get("url")
                                    break
                        if not stream_url and info.get("formats"):
                            audio_fmts = [f for f in info["formats"] if f.get("acodec") != "none" and f.get("url")]
                            if audio_fmts:
                                audio_fmts.sort(key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True)
                                stream_url = audio_fmts[0].get("url")
                            elif len(info["formats"]) > 0:
                                stream_url = info["formats"][-1].get("url")

                        if not stream_url:
                            logger.warning(f"No stream_url found in info for {video_url}")
                            if error_callback:
                                error_callback("Не удалось извлечь аудио поток")
                            return None

                        metadata = {
                            "title": info.get("title", "Unknown"),
                            "artist": info.get("uploader") or info.get("channel", "Unknown"),
                            "duration": info.get("duration", 0),
                            "cover_url": info.get("thumbnail", ""),
                            "source_id": info.get("id", ""),
                            "stream_url": stream_url,
                            "format": info.get("ext", "unknown"),
                            "bitrate": info.get("abr", 0),
                        }

                        self.set_to_cache(video_url, metadata)

                        if callback:
                            callback(stream_url, metadata)
                        return None

                except Exception as e:
                    if attempt < max_attempts - 1:
                        self.logger.warning(f"Attempt {attempt + 1} failed, retrying in 1s: {e}")
                        time.sleep(1)
                        continue
                    self.logger.exception("Ошибка при извлечении потока YouTube")
                    if error_callback:
                        error_callback(f"Произошла ошибка: {type(e).__name__} - {str(e)}")
                    return None

        self._executor.submit(_extract)
        return None

    def download_audio(self, video_url: str, output_path: str, callback: Callable = None, progress_callback: Callable = None, error_callback: Callable = None, quality: str = "high"):
        """Download audio from YouTube to a local file."""
        if not HAS_YTDLP:
            if error_callback:
                error_callback("yt-dlp не установлен")
            return None

        def _download():
            try:
                quality_map = {
                    "low": "192",
                    "medium": "256",
                    "high": "320",
                    "lossless": "best",
                }

                def _progress_hook(d):
                    if progress_callback and d.get("status") == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                        downloaded = d.get("downloaded_bytes", 0)
                        if total > 0:
                            progress_callback(downloaded / total)

                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": "bestaudio/best",
                    "outtmpl": output_path,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": quality_map.get(quality, "320"),
                        }
                    ],
                    "progress_hooks": [_progress_hook],
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

                if callback:
                    callback(output_path)
                return None
            except Exception as e:
                self.logger.exception("Ошибка при загрузке аудио с YouTube")
                if error_callback:
                    error_callback(f"Произошла ошибка: {type(e).__name__} - {str(e)}")
                return None

        self._executor.submit(_download)
        return None