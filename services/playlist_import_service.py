"""
NeDotify - Playlist Import Service
Resolves external and local playlist formats (YouTube, SoundCloud, M3U/M3U8, JSON, text lists).
"""

import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
import math
import itertools
from typing import Any, Callable, Dict, List, Optional


class PlaylistImportError(Exception):
    """Generic error when importing a playlist."""
    pass


class UnsupportedPlaylistService(PlaylistImportError):
    """Raised when the URL or playlist format is unsupported."""
    pass


class PlaylistImportService:
    def _resolve_spotify(self, url: str):
        raise UnsupportedPlaylistService("Поддерживается импорт YouTube, SoundCloud, Deezer, M3U/M3U8, JSON и текстовых списков")

    """Service to parse, resolve, and normalize playlists from URLs or local files."""

    def __init__(self, ydl_factory: Optional[Callable] = None, settings: Any = None):
        self.ydl_factory = ydl_factory
        self.settings = settings

    def _get_ydl(self, options: dict):
        if self.ydl_factory:
            return self.ydl_factory(options)
        try:
            import yt_dlp
            from yt_dlp.networking import Response
            from yt_dlp.networking.exceptions import HTTPError
            from utils.url_safety import guarded_open_url
            class GuardedPlaylistYDL(yt_dlp.YoutubeDL):
                def urlopen(self, request):
                    if isinstance(request, str):
                        req = urllib.request.Request(request)
                    else:
                        req = urllib.request.Request(request.url, data=request.data,
                                                     headers=dict(request.headers), method=request.method)
                    try:
                        raw = guarded_open_url(req, timeout=6.0)
                    except urllib.error.HTTPError as exc:
                        raise HTTPError(Response(exc, exc.url, exc.headers, exc.code)) from exc
                    return Response(raw, raw.url, raw.headers, raw.status)
            return GuardedPlaylistYDL(options)
        except ImportError:
            raise PlaylistImportError("Модуль yt-dlp недоступен для загрузки плейлистов")

    def resolve(self, url_or_path: str) -> Dict[str, Any]:
        """Resolve a playlist URL or file path into a standardized dict."""
        target = (url_or_path or "").strip()
        if not target:
            raise PlaylistImportError("Указана пустая ссылка или путь к плейлисту")

        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme in ('http', 'https'):
            from utils.url_safety import safe_public_url, guarded_open_url
            if not safe_public_url(target):
                raise PlaylistImportError('Недопустимая ссылка плейлиста')
            if parsed.path.lower().endswith(('.m3u', '.m3u8', '.json', '.txt')):
                with guarded_open_url(target, timeout=6) as response:
                    content = response.read(self.MAX_BYTES + 1)
                if len(content) > self.MAX_BYTES:
                    raise PlaylistImportError('Плейлист слишком большой')
                return self._parse_content(content.decode('utf-8-sig'), os.path.basename(parsed.path), target)
        # 1. Local file or M3U/JSON text content
        if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
            return self._resolve_local_file(target)

        # 2. YouTube URL
        if parsed.hostname in ('youtube.com', 'www.youtube.com', 'music.youtube.com', 'm.youtube.com', 'youtu.be'):
            return self._resolve_youtube(target)

        # 3. SoundCloud URL
        if parsed.hostname in ('soundcloud.com', 'www.soundcloud.com', 'on.soundcloud.com'):
            from utils.soundcloud_urls import resolve_playlist_share_url
            try:
                target = resolve_playlist_share_url(target)
            except ValueError as exc:
                raise UnsupportedPlaylistService(str(exc)) from exc
            return self._resolve_soundcloud(target)

        if parsed.scheme == 'https' and parsed.hostname in ('deezer.com', 'www.deezer.com', 'link.deezer.com'):
            if parsed.hostname == 'link.deezer.com':
                from utils.url_safety import guarded_open_url
                with guarded_open_url(target, timeout=6) as response:
                    parsed = urllib.parse.urlsplit(response.geturl())
            match = re.fullmatch(r'/(?:[a-z]{2}/)?playlist/(\d+)/?', parsed.path)
            if parsed.hostname not in ('deezer.com', 'www.deezer.com') or not match:
                raise PlaylistImportError('Укажите ссылку на публичный плейлист Deezer')
            from services.deezer_service import DeezerService
            return DeezerService(self.settings).collection('playlist', match.group(1), self.MAX_TRACKS, require_complete=True)

        # Unsupported service
        raise UnsupportedPlaylistService("Поддерживается импорт YouTube, SoundCloud, Deezer, M3U/M3U8, JSON и текстовых списков")

    def _resolve_youtube(self, url: str) -> Dict[str, Any]:
        opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 6,
            "playlistend": self.MAX_TRACKS + 1,
        }
        try:
            with self._get_ydl(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise PlaylistImportError(f"Ошибка при считывании YouTube плейлиста: {e}")

        if not info:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        name = info.get("title") or info.get("playlist_title") or "YouTube Playlist"
        entries = info.get("entries") or []

        tracks = []
        for entry in itertools.islice(entries, self.MAX_TRACKS + 1):
            if not isinstance(entry, dict):
                continue
            source_id = entry.get("id")
            if not source_id:
                continue
            title = entry.get("title") or "Unknown Title"
            artist = entry.get("uploader") or entry.get("artist") or "Unknown Artist"
            if artist.endswith(" - Topic"):
                artist = artist[:-8]

            duration = 0.0
            dur_val = entry.get("duration")
            if dur_val is not None:
                try:
                    duration = float(dur_val)
                except (ValueError, TypeError):
                    duration = 0.0

            cover_url = ""
            thumbnails = entry.get("thumbnails")
            if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
                cover_url = thumbnails[-1].get("url", "")
            elif entry.get("thumbnail"):
                cover_url = entry["thumbnail"]
            if not cover_url:
                cover_url = f"https://img.youtube.com/vi/{source_id}/hqdefault.jpg"

            source_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={source_id}"

            tracks.append({
                "title": title,
                "artist": artist,
                "album": "Unknown Album",
                "duration": duration,
                "source": "youtube",
                "source_id": str(source_id),
                "source_url": source_url,
                "cover_url": cover_url,
            })

        if len(tracks) > self.MAX_TRACKS or int(info.get('playlist_count') or 0) > self.MAX_TRACKS:
            raise PlaylistImportError(f'Плейлист превышает лимит {self.MAX_TRACKS} треков')
        if not tracks:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        return {"name": name, "source": "youtube", "tracks": tracks}

    def _resolve_soundcloud(self, url: str) -> Dict[str, Any]:
        opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "socket_timeout": 6,
            "playlistend": self.MAX_TRACKS + 1,
        }
        try:
            with self._get_ydl(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise PlaylistImportError(f"Ошибка при считывании SoundCloud плейлиста: {e}")

        if not info:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        name = info.get("title") or "SoundCloud Playlist"
        entries = info.get("entries") or []

        tracks = []
        for entry in itertools.islice(entries, self.MAX_TRACKS + 1):
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            source_id = str(entry["id"])
            title = entry.get("title") or "Unknown Title"
            artist = entry.get("uploader") or entry.get("user", {}).get("username") or "Unknown Artist"
            dur_val = entry.get("duration", 0)
            try:
                duration = float(dur_val)
            except (ValueError, TypeError):
                duration = 0.0

            tracks.append({
                "title": title,
                "artist": artist,
                "album": "Unknown Album",
                "duration": duration,
                "source": "soundcloud",
                "source_id": source_id,
                "source_url": entry.get("url") or f"https://soundcloud.com/{source_id}",
                "cover_url": entry.get("thumbnail") or "",
            })

        if len(tracks) > self.MAX_TRACKS or int(info.get('playlist_count') or 0) > self.MAX_TRACKS:
            raise PlaylistImportError(f'Плейлист превышает лимит {self.MAX_TRACKS} треков')
        if not tracks:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        # extract_flat="in_playlist" gives SoundCloud entries with an id but no
        # title/uploader/thumbnail, so every track came back as
        # "Unknown Title" and the whole import looked broken. Fill the gaps
        # from the SoundCloud API, which is one cheap call per track.
        self._enrich_soundcloud_tracks(tracks)

        return {"name": name, "source": "soundcloud", "tracks": tracks}

    def _enrich_soundcloud_tracks(self, tracks: List[Dict[str, Any]]) -> None:
        """Fill in missing title/artist/cover for flat-extracted entries."""
        missing = [
            t for t in tracks
            if not t.get("title") or t["title"] == "Unknown Title"
            or not t.get("artist") or t["artist"] == "Unknown Artist"
        ]
        if not missing:
            return

        svc = None
        try:
            from services.soundcloud_service import SoundCloudService
            svc = SoundCloudService(settings=self.settings)
        except Exception:
            return

        # Bounded concurrency: 33 sequential API calls would take ~20s.
        from concurrent.futures import ThreadPoolExecutor
        def _fetch(track):
            try:
                return svc.get_track_metadata(str(track.get("source_id") or ""))
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=6) as pool:
            for track, meta in zip(missing, pool.map(_fetch, missing)):
                if not meta:
                    continue
                if not track.get("title") or track["title"] == "Unknown Title":
                    if meta.get("title"):
                        track["title"] = meta["title"]
                if not track.get("artist") or track["artist"] == "Unknown Artist":
                    if meta.get("artist"):
                        track["artist"] = meta["artist"]
                if not track.get("cover_url") and meta.get("cover_url"):
                    track["cover_url"] = meta["cover_url"]
                if not track.get("source_url") and meta.get("source_url"):
                    track["source_url"] = meta["source_url"]

    def _resolve_local_file(self, target: str) -> Dict[str, Any]:
        """Parse M3U, JSON, or text playlist files."""
        if not os.path.exists(target):
            raise PlaylistImportError(f"Файл плейлиста не найден: {target}")

        file_name = os.path.splitext(os.path.basename(target))[0]

        try:
            with open(target, "r", encoding="utf-8-sig", errors="ignore") as f:
                content = f.read(self.MAX_BYTES + 1)
        except Exception as e:
            raise PlaylistImportError(f"Не удалось прочитать файл: {e}")
        if len(content.encode('utf-8')) > self.MAX_BYTES:
            raise PlaylistImportError('Плейлист слишком большой')
        return self._parse_content(content, file_name, target)

    def _parse_content(self, content, file_name, target):

        # JSON Format
        if target.endswith(".json") or content.strip().startswith("{") or content.strip().startswith("["):
            try:
                data = json.loads(content)
                items = data.get("tracks") if isinstance(data, dict) else data
                if isinstance(items, list):
                    if len(items) > self.MAX_TRACKS:
                        raise PlaylistImportError(f'Плейлист превышает лимит {self.MAX_TRACKS} треков')
                    tracks = []
                    for item in items:
                        if isinstance(item, dict):
                            try:
                                duration = float(item.get('duration') or 0)
                                if not math.isfinite(duration) or duration < 0:
                                    duration = 0
                            except (ValueError, TypeError):
                                duration = 0
                            file_path=item.get('file_path')
                            if file_path:
                                if urllib.parse.urlsplit(target).scheme in ('http','https'):
                                    raise PlaylistImportError('Онлайн-плейлист не может содержать локальные пути')
                                file_path=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(target)),os.path.expanduser(str(file_path))))
                            source=item.get('source') or ('local' if file_path else 'youtube')
                            sid=item.get('source_id')
                            source_url=item.get('source_url')
                            if not sid and source=='youtube':
                                if source_url:
                                    parsed_url=urllib.parse.urlsplit(str(source_url))
                                    sid=(urllib.parse.parse_qs(parsed_url.query).get('v') or [None])[0]
                                    if parsed_url.hostname=='youtu.be':sid=parsed_url.path.strip('/')
                                if not sid:
                                    artist=str(item.get('artist') or '').strip()
                                    title=str(item.get('title') or '').strip()
                                    if not title:continue
                                    sid='ytsearch1:'+(' - '.join(value for value in (artist,title) if value))
                            elif not sid and source=='soundcloud':sid=source_url
                            tracks.append({
                                "title": item.get("title", "Unknown Title"),
                                "artist": item.get("artist", "Unknown Artist"),
                                "album": item.get("album", "Unknown Album"),
                                "duration": duration,
                                "source": source,
                                "file_path": file_path,
                                "source_id": sid,
                                "source_url": source_url,
                                "cover_url": item.get("cover_url"),
                            })
                    if tracks:
                        return {"name": data.get("name", file_name) if isinstance(data, dict) else file_name, "tracks": tracks}
                raise PlaylistImportError('JSON не содержит треков')
            except (ValueError, TypeError) as exc:
                raise PlaylistImportError('Повреждённый JSON-плейлист') from exc

        # M3U / M3U8 Format
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        tracks = []
        current_title = "Unknown Title"
        current_artist = "Unknown Artist"
        current_dur = 0.0

        for line in lines:
            if len(tracks) >= self.MAX_TRACKS and not line.startswith('#'):
                raise PlaylistImportError(f'Плейлист превышает лимит {self.MAX_TRACKS} треков')
            if line.startswith("#EXTINF:"):
                # Parse #EXTINF:123,Artist - Title
                match = re.match(r"#EXTINF:(-?\d+),(.*)", line)
                if match:
                    try:
                        dur_sec = float(match.group(1))
                        current_dur = max(0.0, dur_sec)
                    except ValueError:
                        current_dur = 0.0
                    full_name = match.group(2).strip()
                    if " - " in full_name:
                        parts = full_name.split(" - ", 1)
                        current_artist = parts[0].strip()
                        current_title = parts[1].strip()
                    else:
                        current_title = full_name
            elif not line.startswith("#"):
                # Path or URL line
                path_or_url = line
                base = urllib.parse.urlsplit(target)
                remote_playlist = base.scheme in ('http', 'https')
                if not remote_playlist and not urllib.parse.urlsplit(line).scheme and not os.path.isabs(line):
                    relative = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(target)), line))
                    if os.path.isfile(relative):
                        path_or_url = relative
                if not remote_playlist and os.path.isfile(path_or_url):
                    title = current_title if current_title != "Unknown Title" else os.path.splitext(os.path.basename(path_or_url))[0]
                    tracks.append({
                        "title": title,
                        "artist": current_artist,
                        "album": "Unknown Album",
                        "duration": current_dur,
                        "source": "local",
                        "file_path": path_or_url,
                    })
                elif path_or_url.startswith("http"):
                    host = urllib.parse.urlsplit(path_or_url).hostname
                    source = ('youtube' if host in ('youtube.com', 'www.youtube.com', 'music.youtube.com', 'm.youtube.com', 'youtu.be')
                              else 'soundcloud' if host in ('soundcloud.com', 'www.soundcloud.com')
                              else 'deezer' if host in ('deezer.com', 'www.deezer.com') else 'local')
                    source_id = None
                    if source == 'deezer':
                        match = re.fullmatch(r'/(?:[a-z]{2}/)?track/(\d+)/?', urllib.parse.urlsplit(path_or_url).path)
                        if match:
                            from services.deezer_service import DeezerService
                            tracks.append(DeezerService(self.settings).get_track(match.group(1)))
                            current_title, current_artist, current_dur = 'Unknown Title', 'Unknown Artist', 0.0
                            continue
                        raise PlaylistImportError('Некорректная ссылка трека Deezer')
                    if source == 'youtube' and host != 'youtu.be':
                        m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", path_or_url)
                        if m:
                            source_id = m.group(1)
                    elif source == 'youtube' and host == 'youtu.be':
                        m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", path_or_url)
                        if m:
                            source_id = m.group(1)
                    elif source == 'soundcloud':
                        source_id = path_or_url.strip()

                    if not source_id:
                        source_id = f"{current_artist} {current_title}".strip() if current_title != "Unknown Title" else path_or_url.strip()

                    tracks.append({
                        "title": current_title,
                        "artist": current_artist,
                        "album": "Unknown Album",
                        "duration": current_dur,
                        "source": source,
                        "source_id": str(source_id),
                        "source_url": path_or_url,
                    })
                elif " - " in path_or_url:
                    parts = path_or_url.split(" - ", 1)
                    tracks.append({
                        "artist": parts[0].strip(),
                        "title": parts[1].strip(),
                        "album": "Unknown Album",
                        "duration": 0.0,
                        "source": "youtube",
                        "source_id": 'ytsearch1:' + path_or_url.strip(),
                    })
                elif len(path_or_url) > 2:
                    tracks.append({
                        "artist": "Unknown Artist",
                        "title": path_or_url.strip(),
                        "album": "Unknown Album",
                        "duration": 0.0,
                        "source": "youtube",
                        "source_id": 'ytsearch1:' + path_or_url.strip(),
                    })
                current_title = "Unknown Title"
                current_artist = "Unknown Artist"
                current_dur = 0.0

        if tracks:
            return {"name": file_name, "tracks": tracks}

        raise PlaylistImportError("Не удалось извлечь треки из файла плейлиста")
    MAX_TRACKS = 2000
    MAX_BYTES = 4 * 1024 * 1024
