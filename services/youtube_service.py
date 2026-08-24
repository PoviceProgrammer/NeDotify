"""
NeDotify - YouTube Service
Search and stream audio from YouTube/YouTube Music via yt-dlp.
"""

import time

from typing import Callable, Optional
import re
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
            from requests.adapters import HTTPAdapter

            class TimeoutSession(requests.Session):
                def request(self, *args, **kwargs):
                    kwargs["timeout"] = 15
                    return super().request(*args, **kwargs)

            session = TimeoutSession()
            adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=2)
            session.mount("https://", adapter)
            proxy = self.settings.get("auth", "proxy_url", "") if self.settings else ""
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
            self._ytmusic = YTMusic(language="ru", location="RU", requests_session=session)

        # One YoutubeDL instance per thread: yt-dlp objects carry mutable shared
        # state (cookie jars, internal caches) and are NOT safe to use
        # concurrently. A single shared instance caused intermittent extraction
        # races under parallel stream resolution.
        self._ydl_tls = threading.local()
        self._ydl_lock = threading.Lock()

        if HAS_YTDLP:
            self._executor.submit(self._get_ydl, "high")

    def reset_ydl(self):
        # Replacing the thread-local storage drops cached instances in every
        # thread at once; each thread rebuilds lazily on next use.
        self._ydl_tls = threading.local()

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
                if proxy:
                    session.proxies = {"http": proxy, "https": proxy}
                self._ytmusic = YTMusic(language="ru", location="RU", requests_session=session)

    def _get_ydl(self, quality="high", fallback=False):
        """Return this thread's YoutubeDL instance (created on first use)."""
        store = getattr(self._ydl_tls, "instances", None)
        if store is None:
            store = {}
            self._ydl_tls.instances = store

        quality_map = {
            "low": "bestaudio/best",
            "medium": "bestaudio/best",
            "high": "bestaudio/best",
            "lossless": "bestaudio/best",
        }
        fmt = quality_map.get(quality, "bestaudio/best")
        key = ("fallback", "best") if fallback else ("main", fmt)

        ydl = store.get(key)
        if ydl is None:
            ydl = yt_dlp.YoutubeDL(self._get_ydl_opts(fmt, fallback=fallback))
            store[key] = ydl
        return ydl

    def _prefetch_top_tracks(self, tracks: list):
        """Pre-resolve stream URLs for the top search results.

        Opt-in only (see `search(..., prefetch=True)`): running it on every search
        fired a full yt-dlp extraction per keystroke of a debounced search box.
        """
        for trk in tracks[:2]:
            try:
                sid = trk.get("source_id")
                surl = trk.get("source_url") or sid
                if surl and not self.get_from_cache(surl):
                    self.get_stream_url(surl, quality="high")
            except Exception as e:
                logger.debug(f"Prefetch skipped for {trk.get('source_id')}: {e}", exc_info=True)
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
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb", "web_embedded"],
                    "player_skip": ["configs", "webpage"]
                }
            },
            "socket_timeout": 5,
            "retries": 0,
            "extractor_retries": 0,
            "source_address": "0.0.0.0",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            },
        }

        if fallback:
            opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["android", "ios", "mweb"],
                    "player_skip": ["configs"]
                }
            }
            opts["format"] = "bestaudio/best/ba/b/worst"
            opts["ignoreerrors"] = True

        if self.settings:
            if not fallback:
                cookies_file_path = self.settings.get("auth", "cookies_file_path", "")
                if cookies_file_path and os.path.exists(cookies_file_path):
                    opts["cookiefile"] = cookies_file_path
                configured_browser = self.settings.get("auth", "browser_cookies", "none")
                if configured_browser and configured_browser != "none":
                    opts["cookiesfrombrowser"] = (configured_browser,)
                proxy = self.settings.get("auth", "proxy_url", "")
                if proxy:
                    opts["proxy"] = proxy
        return opts


    @property
    def available(self) -> bool:
        return HAS_YTDLP

    def search(self, query: str, max_results: int = 20, result_type: str = None, callback: Callable = None, error_callback: Callable = None, prefetch: bool = False):
        """Search YouTube for tracks or albums. Runs in background thread.

        `prefetch` is off by default: turning it on pre-resolves stream URLs for the
        top hits, which costs a full yt-dlp extraction per result.
        """
        if not HAS_YTDLP or not HAS_YTMUSIC:
            if error_callback:
                error_callback("yt-dlp или ytmusicapi не установлены")
            return None

        def _search():
            try:
                is_album_search = result_type in ("albums", "album")
                is_playlist_search = result_type in ("playlists", "playlist")
                yt_filter = "playlists" if is_playlist_search else ("albums" if is_album_search else None)
                cache_key = f"yt_search:{query}:{yt_filter}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return None

                results = self._ytmusic.search(query, filter=yt_filter, limit=max_results)

                tracks = []
                seen_ids = set()
                for idx, item in enumerate(results):
                    if is_playlist_search:
                        browse_id = item.get("browseId") or item.get("playlistId")
                        if not browse_id or browse_id in seen_ids:
                            continue
                        seen_ids.add(browse_id)
                        title = item.get("title", "Unknown Playlist")
                        author = ", ".join([a.get("name", "") for a in item.get("artists", []) or [] if a.get("name")]) or (item.get("author") or "YouTube Music")
                        thumbnails = item.get("thumbnails", []) or []
                        cover_url = thumbnails[-1]["url"] if thumbnails else ""
                        tracks.append({
                            "source": "youtube",
                            "source_id": browse_id,
                            "title": title,
                            "artist": author,
                            "author": author,
                            "cover_url": cover_url,
                            "type": "playlist",
                            "track_count": item.get("track_count") or item.get("itemCount") or 0
                        })
                    elif is_album_search:
                        bid = item.get("browseId") or item.get("playlistId") or f"yt_album_{idx}"
                        if bid in seen_ids:
                            continue
                        seen_ids.add(bid)

                        title = item.get("title", "Unknown Album")
                        artists_list = item.get("artists", []) or []
                        artist = ", ".join([a["name"] for a in artists_list if "name" in a]) or "Unknown Artist"
                        thumbnails = item.get("thumbnails", []) or []
                        cover_url = thumbnails[-1]["url"] if thumbnails else ""
                        year = item.get("year") or ""

                        tracks.append({
                            "id": f"yt_album_{bid}",
                            "source": "youtube",
                            "source_id": bid,
                            "title": title,
                            "artist": artist,
                            "album": title,
                            "year": year,
                            "cover_url": cover_url,
                            "type": "album",
                            "track_count": item.get("track_count") or 0
                        })
                    else:
                        rtype = item.get("resultType", "")
                        if rtype not in ("song", "video"):
                            continue
                        vid = item.get("videoId")
                        if not vid or vid in seen_ids:
                            continue

                        seen_ids.add(vid)

                        source_id = vid
                        title = item.get("title", "Unknown Title")

                        artists_list = item.get("artists", []) or []
                        artist = ", ".join([a["name"] for a in artists_list if "name" in a])
                        if not artist:
                            artist = "Unknown Artist"

                        duration_str = item.get("duration", "0:00")
                        duration = 0
                        if duration_str:
                            parts = duration_str.split(":")
                            if len(parts) == 2:
                                duration = int(parts[0]) * 60 + int(parts[1])
                            elif len(parts) == 3:
                                duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

                        thumbnails = item.get("thumbnails", []) or []
                        cover_url = thumbnails[-1]["url"] if thumbnails else ""

                        tracks.append({
                            "source": "youtube",
                            "source_id": source_id,
                            "title": title,
                            "artist": artist,
                            "duration": duration,
                            "cover_url": cover_url,
                            "album": item.get("album", {}).get("name", "") if isinstance(item.get("album"), dict) else "",
                        })

                self.set_search_cache(cache_key, tracks)
                if callback:
                    callback(tracks)

                if prefetch and not is_album_search and not is_playlist_search:
                    self._executor.submit(self._prefetch_top_tracks, tracks)

            except Exception as e:
                logger.error(f"YouTube search error: {e}")
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_search)
        return None

    def search_sync(self, query: str, limit: int = 20, result_type: str = None, timeout: float = 6.0) -> list:
        """Synchronous search wrapper over YouTube search with timeout <= 6s.
        Returns list of track dictionaries, or [] on any error/timeout (never raises).
        """
        import threading
        result = []
        event = threading.Event()

        def _on_success(tracks):
            nonlocal result
            if isinstance(tracks, list):
                result = tracks
            event.set()

        def _on_error(err):
            event.set()

        try:
            self.search(
                query=query,
                max_results=limit,
                result_type=result_type,
                callback=_on_success,
                error_callback=_on_error,
                prefetch=False
            )
            event.wait(timeout=min(timeout, 6.0))
        except Exception as e:
            logger.debug(f"YouTube search_sync failed: {e}")
        return result or []

    def get_album_tracks(self, browse_id: str, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        """Fetch YouTube Music album tracks via ytmusicapi. Runs in background thread."""
        if not HAS_YTDLP or not HAS_YTMUSIC:
            if error_callback:
                error_callback("yt-dlp или ytmusicapi не установлены")
            return None

        def _fetch():
            try:
                data = self._ytmusic.get_album(browse_id)
                entries = data.get("tracks", []) if isinstance(data, dict) else []
                album_title = data.get("title", "Album")
                album_artist = ", ".join([a["name"] for a in data.get("artists", []) if "name" in a]) or "Unknown Artist"
                thumbnails = data.get("thumbnails", [])
                album_cover = thumbnails[-1].get("url", "") if thumbnails else ""

                tracks = []
                seen_ids = set()
                for item in entries:
                    vid = item.get("videoId")
                    if not vid or vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    title = item.get("title", "Unknown Title")
                    artists_list = item.get("artists", []) or []
                    artist = ", ".join([a["name"] for a in artists_list if "name" in a]) or album_artist

                    duration = item.get("duration_seconds", 0) or 0
                    if isinstance(duration, str):
                        parts = duration.split(":")
                        if len(parts) == 2:
                            duration = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        else:
                            duration = 0

                    tracks.append({
                        "source": "youtube",
                        "source_id": vid,
                        "title": title,
                        "artist": artist,
                        "album": album_title,
                        "duration": duration,
                        "cover_url": album_cover,
                    })
                    if limit and len(tracks) >= limit:
                        break

                if callback:
                    callback(tracks)
            except Exception as e:
                logger.error(f"YouTube get_album_tracks error: {e}")
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_fetch)
        return None

    def get_playlist_tracks(self, playlist_id: str, limit: int = 50, callback: Callable = None, error_callback: Callable = None):
        """Fetch YouTube Music playlist tracks via ytmusicapi. Runs in background thread."""
        if not HAS_YTDLP or not HAS_YTMUSIC:
            if error_callback:
                error_callback("yt-dlp или ytmusicapi не установлены")
            return None

        def _fetch():
            try:
                data = self._ytmusic.get_playlist(playlist_id)
                entries = data.get("tracks", []) if isinstance(data, dict) else []

                tracks = []
                seen_ids = set()
                for item in entries:
                    vid = item.get("videoId")
                    if not vid or vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    title = item.get("title", "Unknown Title")

                    artists_list = item.get("artists", []) or []
                    artist = ", ".join([a["name"] for a in artists_list if "name" in a])
                    if not artist:
                        artist = "Unknown Artist"

                    duration = item.get("duration_seconds", 0) or 0
                    if isinstance(duration, str):
                        parts = duration.split(":")
                        if len(parts) == 2:
                            duration = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        else:
                            duration = 0

                    thumbnails = item.get("thumbnails", []) or []
                    cover_url = ""
                    if thumbnails:
                        best = thumbnails[-1]
                        for t in thumbnails:
                            if (t.get("width") or 0) * (t.get("height") or 0) > (best.get("width") or 0) * (best.get("height") or 0):
                                best = t
                        cover_url = best.get("url", "")

                    tracks.append({
                        "source": "youtube",
                        "source_id": vid,
                        "title": title,
                        "artist": artist,
                        "duration": duration,
                        "cover_url": cover_url,
                        "album": item.get("album", {}).get("name", "") if isinstance(item.get("album"), dict) else "",
                    })
                    if limit and len(tracks) >= limit:
                        break

                if callback:
                    callback(tracks)

            except Exception as e:
                logger.error(f"YouTube playlist fetch error: {e}")
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_fetch)
        return None

    def _extract_info_safe(self, video_url: str, quality: str, fallback: bool = False):
        ydl = self._get_ydl(quality, fallback=fallback)
        opts = self._get_ydl_opts("bestaudio/best", fallback=fallback)

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

                if configured_browser and configured_browser != "none":
                    logger.info(f"Age gate bypass: trying cookies from configured browser: {configured_browser}")
                    cookie_opts = opts.copy()
                    cookie_opts["cookiesfrombrowser"] = (configured_browser,)
                    try:
                        with yt_dlp.YoutubeDL(cookie_opts) as ydl_cookie:
                            return ydl_cookie.extract_info(video_url, download=False)
                    except Exception as cookie_err:
                        logger.warning(f"Browser cookies extraction failed: {cookie_err}")
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
            max_attempts = 1
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

                        if any(k in err_lower for k in ("bot", "sign in", "confirm you", "drm")):
                            logger.info("YouTube bot/auth challenge detected, triggering fast fallback.")
                            if error_callback:
                                error_callback(err_msg)
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

    def download_audio_sync(self, source_id: str, output_dir: str) -> str:
        """Download audio synchronously from YouTube via yt-dlp."""
        import os
        import time
        if not HAS_YTDLP:
            raise Exception("yt-dlp не установлен")

        clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))
        file_name = f"yt_{clean_id}_{int(time.time())}.mp3"
        output_path = os.path.join(output_dir, file_name)

        url = source_id if str(source_id).startswith("http") or str(source_id).startswith("ytsearch") else f"https://www.youtube.com/watch?v={source_id}"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": output_path,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(output_path):
            base, _ = os.path.splitext(output_path)
            for ext in (".mp3", ".m4a", ".webm", ".opus"):
                if os.path.exists(base + ext):
                    return base + ext
            raise Exception("Файл не был создан после загрузки с YouTube")

        return output_path