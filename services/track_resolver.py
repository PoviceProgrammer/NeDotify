"""
NeDotify / AURA Music - Track Resolution Helper
Resolves metadata (title, artist) to a playable UI track dictionary using:
1. Local Database search
2. SoundCloud Service search
3. YouTube Service search fallback
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TrackResolver:
    """Helper class to resolve track metadata (title, artist) into playable UI track dictionaries."""

    def __init__(self, db=None, soundcloud_service=None, youtube_service=None):
        self.db = db
        self.sc_service = soundcloud_service
        self.yt_service = youtube_service
        self.logger = logging.getLogger(self.__class__.__name__)
        self._executor = ThreadPoolExecutor(max_workers=5)

    def _search_local(self, title: str, artist: str) -> Optional[Dict[str, Any]]:
        if not self.db:
            return None

        conn = None
        if hasattr(self.db, 'conn'):
            conn = self.db.conn
        elif hasattr(self.db, 'cursor'):
            conn = self.db

        if not conn:
            return None

        try:
            cursor = conn.cursor()
            query = """
                SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                FROM tracks
                WHERE LOWER(title) = LOWER(?) AND (LOWER(artist) = LOWER(?) OR artist = 'Unknown Artist' OR ? = '')
                LIMIT 1
            """
            cursor.execute(query, (title, artist, artist))
            row = cursor.fetchone()

            if not row and title:
                query_title = """
                    SELECT id, title, artist, cover_url, cover_path, source, source_id, source_url, duration, file_path
                    FROM tracks
                    WHERE LOWER(title) = LOWER(?)
                    LIMIT 1
                """
                cursor.execute(query_title, (title,))
                row = cursor.fetchone()

            if row:
                if hasattr(row, 'keys'):
                    r = dict(row)
                else:
                    r = {
                        'id': row[0],
                        'title': row[1],
                        'artist': row[2],
                        'cover_url': row[3],
                        'cover_path': row[4],
                        'source': row[5],
                        'source_id': row[6],
                        'source_url': row[7],
                        'duration': row[8],
                        'file_path': row[9],
                    }
                return {
                    'title': r.get('title') or title,
                    'artist': r.get('artist') or artist,
                    'cover_url': r.get('cover_url') or r.get('cover_path') or '',
                    'source': r.get('source') or 'local',
                    'source_id': str(r.get('source_id') or r.get('id') or ''),
                    'source_url': r.get('source_url') or r.get('file_path') or '',
                    'duration': float(r.get('duration') or 0),
                }
            return None
        except Exception as e:
            logger.warning(f"Local track search error: {e}")
            return None

    def _search_soundcloud(self, query: str) -> Optional[Dict[str, Any]]:
        if not self.sc_service:
            try:
                from services.soundcloud_service import SoundCloudService
                self.sc_service = SoundCloudService()
            except Exception as e:
                logger.warning(f"Failed to instantiate SoundCloudService: {e}")
                return None

        results = []
        done_event = threading.Event()

        def cb(trks):
            nonlocal results
            results = trks
            done_event.set()

        def err_cb(err):
            done_event.set()

        try:
            self.sc_service.search(query, max_results=1, callback=cb, error_callback=err_cb)
            done_event.wait(timeout=5.0)

            if results and isinstance(results, list):
                top = results[0]
                return {
                    'title': top.get('title', 'Unknown Title'),
                    'artist': top.get('artist', 'Unknown Artist'),
                    'cover_url': top.get('cover_url', ''),
                    'source': 'soundcloud',
                    'source_id': str(top.get('source_id', '')),
                    'source_url': top.get('source_url', ''),
                    'duration': float(top.get('duration', 0)),
                }
        except Exception as e:
            logger.warning(f"SoundCloud track resolution error: {e}")
            return None
        return None

    def _search_youtube(self, query: str) -> Optional[Dict[str, Any]]:
        if not self.yt_service:
            try:
                from services.youtube_service import YouTubeService
                self.yt_service = YouTubeService()
            except Exception as e:
                logger.warning(f"Failed to instantiate YouTubeService: {e}")
                return None

        results = []
        done_event = threading.Event()

        def cb(trks):
            nonlocal results
            results = trks
            done_event.set()

        def err_cb(err):
            done_event.set()

        try:
            self.yt_service.search(query, max_results=1, callback=cb, error_callback=err_cb)
            done_event.wait(timeout=5.0)

            if results and isinstance(results, list):
                top = results[0]
                return {
                    'title': top.get('title', 'Unknown Title'),
                    'artist': top.get('artist', 'Unknown Artist'),
                    'cover_url': top.get('cover_url', ''),
                    'source': 'youtube',
                    'source_id': str(top.get('source_id', '')),
                    'source_url': top.get('source_url', ''),
                    'duration': float(top.get('duration', 0)),
                }
        except Exception as e:
            logger.warning(f"YouTube track resolution error: {e}")
            return None
        return None

    def resolve_track(self, title: str, artist: str = '') -> Dict[str, Any]:
        if artist:
            query = f"{artist} {title}".strip()
        else:
            query = title.strip()

        local_res = self._search_local(title, artist)
        if local_res:
            return local_res

        sc_res = self._search_soundcloud(query)
        if sc_res:
            return sc_res

        yt_res = self._search_youtube(query)
        if yt_res:
            return yt_res

        return {
            'title': title,
            'artist': artist or 'Unknown Artist',
            'cover_url': '',
            'source': 'unknown',
            'source_id': '',
            'source_url': '',
            'duration': 0,
        }

    def resolve_track_async(self, title: str, artist: str = '', callback: Callable = None):
        def _task():
            res = self.resolve_track(title, artist)
            if callback:
                callback(res)
            return res

        self._executor.submit(_task)


def resolve_track(title: str, artist: str = '', db: Any = '', soundcloud_service: Any = None,
                  youtube_service: Any = None) -> Dict[str, Any]:
    resolver = TrackResolver(db=db, soundcloud_service=soundcloud_service, youtube_service=youtube_service)
    return resolver.resolve_track(title, artist)