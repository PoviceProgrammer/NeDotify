"""
NeDotify - Playlist Import Service
Resolves external and local playlist formats (YouTube, SoundCloud, M3U/M3U8, JSON, text lists).
"""

import json
import os
import re
import urllib.parse
from typing import Any, Callable, Dict, List, Optional


class PlaylistImportError(Exception):
    """Generic error when importing a playlist."""
    pass


class UnsupportedPlaylistService(PlaylistImportError):
    """Raised when the URL or playlist format is unsupported."""
    pass


class PlaylistImportService:
    """Service to parse, resolve, and normalize playlists from URLs or local files."""

    def __init__(self, ydl_factory: Optional[Callable] = None):
        self.ydl_factory = ydl_factory

    def _get_ydl(self, options: dict):
        if self.ydl_factory:
            return self.ydl_factory(options)
        try:
            import yt_dlp
            return yt_dlp.YoutubeDL(options)
        except ImportError:
            raise PlaylistImportError("Модуль yt-dlp недоступен для загрузки плейлистов")

    def resolve(self, url_or_path: str) -> Dict[str, Any]:
        """Resolve a playlist URL or file path into a standardized dict."""
        target = (url_or_path or "").strip()
        if not target:
            raise PlaylistImportError("Указана пустая ссылка или путь к плейлисту")

        # 1. Local file or M3U/JSON text content
        if os.path.exists(target) or target.endswith((".m3u", ".m3u8", ".json", ".txt")):
            return self._resolve_local_file(target)

        # 2. YouTube URL
        if "youtube.com" in target or "youtu.be" in target:
            return self._resolve_youtube(target)

        # 3. SoundCloud URL
        if "soundcloud.com" in target:
            return self._resolve_soundcloud(target)

        # Unsupported service
        raise UnsupportedPlaylistService("Поддерживается импорт плейлистов YouTube, M3U/M3U8, JSON и текстовых списков")

    def _resolve_youtube(self, url: str) -> Dict[str, Any]:
        opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
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
        for entry in entries:
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

        if not tracks:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        return {"name": name, "source": "youtube", "tracks": tracks}

    def _resolve_soundcloud(self, url: str) -> Dict[str, Any]:
        opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
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
        for entry in entries:
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

        if not tracks:
            raise PlaylistImportError("В плейлисте не найдено доступных треков")

        return {"name": name, "source": "soundcloud", "tracks": tracks}

    def _resolve_local_file(self, target: str) -> Dict[str, Any]:
        """Parse M3U, JSON, or text playlist files."""
        if not os.path.exists(target):
            raise PlaylistImportError(f"Файл плейлиста не найден: {target}")

        file_name = os.path.splitext(os.path.basename(target))[0]

        try:
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            raise PlaylistImportError(f"Не удалось прочитать файл: {e}")

        # JSON Format
        if target.endswith(".json") or content.strip().startswith("{") or content.strip().startswith("["):
            try:
                data = json.loads(content)
                items = data.get("tracks") if isinstance(data, dict) else data
                if isinstance(items, list):
                    tracks = []
                    for item in items:
                        if isinstance(item, dict):
                            tracks.append({
                                "title": item.get("title", "Unknown Title"),
                                "artist": item.get("artist", "Unknown Artist"),
                                "album": item.get("album", "Unknown Album"),
                                "duration": float(item.get("duration", 0)),
                                "source": item.get("source", "local"),
                                "file_path": item.get("file_path"),
                                "source_id": item.get("source_id"),
                                "source_url": item.get("source_url"),
                            })
                    if tracks:
                        return {"name": data.get("name", file_name) if isinstance(data, dict) else file_name, "tracks": tracks}
            except Exception:
                pass

        # M3U / M3U8 Format
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        tracks = []
        current_title = "Unknown Title"
        current_artist = "Unknown Artist"
        current_dur = 0.0

        for line in lines:
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
                if os.path.exists(path_or_url):
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
                    source = "youtube" if ("youtube" in path_or_url or "youtu.be" in path_or_url) else ("soundcloud" if "soundcloud" in path_or_url else "local")
                    source_id = None
                    if "youtube.com/watch" in path_or_url:
                        m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", path_or_url)
                        if m:
                            source_id = m.group(1)
                    elif "youtu.be/" in path_or_url:
                        m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", path_or_url)
                        if m:
                            source_id = m.group(1)
                    elif "soundcloud.com" in path_or_url:
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
                        "source_id": path_or_url.strip(),
                    })
                elif len(path_or_url) > 2:
                    tracks.append({
                        "artist": "Unknown Artist",
                        "title": path_or_url.strip(),
                        "album": "Unknown Album",
                        "duration": 0.0,
                        "source": "youtube",
                        "source_id": path_or_url.strip(),
                    })
                current_title = "Unknown Title"
                current_artist = "Unknown Artist"
                current_dur = 0.0

        if tracks:
            return {"name": file_name, "tracks": tracks}

        raise PlaylistImportError("Не удалось извлечь треки из файла плейлиста")
