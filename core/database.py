"""
NeDotify - SQLite Database Manager
Manages local storage: tracks, playlists, history, favorites, settings, cache.
"""

import sqlite3
import os
import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Thread-safe SQLite database manager for NeDotify.
    """

    _local = threading.local()

    def __init__(self, db_path: str = None) -> None:
        if db_path is None:
            app_data = os.path.join(os.path.expanduser("~"), ".nedotify")
            os.makedirs(app_data, exist_ok=True)
            db_path = os.path.join(app_data, "nedotify_storage.db")
        self.db_path = db_path
        self._init_database()

    def get(self, key_or_id: Any = None, default: Any = None, *args, **kwargs) -> Any:
        """Generic get helper supporting setting or track lookup."""
        if isinstance(key_or_id, int):
            return self.get_track(key_or_id)
        if isinstance(key_or_id, str):
            val = self.get_setting("general", key_or_id) if hasattr(self, 'get_setting') else None
            return val if val is not None else default
        return default

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, timeout=20.0)
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")
            self._local.connection.execute("PRAGMA temp_store=MEMORY")
            self._local.connection.execute("PRAGMA cache_size=-64000")
            self._local.connection.execute("PRAGMA foreign_keys=ON")
        return self._local.connection

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_connection()

    def _init_database(self) -> None:
        conn = self.conn
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT DEFAULT 'Unknown Artist',
                album TEXT DEFAULT 'Unknown Album',
                duration REAL DEFAULT 0,
                file_path TEXT UNIQUE,
                source TEXT DEFAULT 'local',
                source_id TEXT,
                source_url TEXT,
                cover_path TEXT,
                cover_url TEXT,
                bitrate INTEGER DEFAULT 0,
                sample_rate INTEGER DEFAULT 0,
                format TEXT,
                file_size INTEGER DEFAULT 0,
                loudness_lufs REAL,
                genre TEXT,
                year INTEGER,
                track_number INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_played TIMESTAMP,
                play_count INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                is_cached INTEGER DEFAULT 0,
                metadata_json TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                cover_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_smart INTEGER DEFAULT 0,
                smart_rules_json TEXT
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                position INTEGER DEFAULT 0,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_listened REAL DEFAULT 0,
                completed INTEGER DEFAULT 0,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                category TEXT DEFAULT 'general',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stream_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                stream_url TEXT,
                cached_file_path TEXT,
                title TEXT,
                artist TEXT,
                cover_url TEXT,
                duration REAL,
                metadata_json TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                UNIQUE(source, source_id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT UNIQUE NOT NULL,
                last_scanned TIMESTAMP,
                auto_scan INTEGER DEFAULT 1
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS listening_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                duration_ms INTEGER NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_favorite ON tracks(is_favorite)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_played ON history(played_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_source ON stream_cache(source, source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pid ON playlist_tracks(playlist_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_tid ON playlist_tracks(track_id)")

        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN is_downloaded INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_downloaded ON tracks(is_downloaded)")

        # Dup cleanup migration
        cursor.execute("SELECT value FROM settings WHERE key = 'migration_dup_cleanup_done'")
        if not cursor.fetchone():
            try:
                cursor.execute(
                    """
                    DELETE FROM playlist_tracks 
                    WHERE id NOT IN (
                        SELECT MIN(id) 
                        FROM playlist_tracks 
                        GROUP BY playlist_id, track_id
                    )
                """
                )
                cursor.execute(
                    """
                    DELETE FROM playlist_tracks
                    WHERE id IN (
                        SELECT pt.id
                        FROM playlist_tracks pt
                        JOIN tracks t ON pt.track_id = t.id
                        WHERE pt.id NOT IN (
                            SELECT MIN(pt2.id)
                            FROM playlist_tracks pt2
                            JOIN tracks t2 ON pt2.track_id = t2.id
                            WHERE pt2.playlist_id = pt.playlist_id
                            GROUP BY LOWER(t2.title), LOWER(t2.artist)
                        )
                    )
                """
                )
                cursor.execute(
                    """
                    DELETE FROM tracks
                    WHERE id IN (
                        SELECT t.id
                        FROM tracks t
                        WHERE t.id NOT IN (
                            SELECT MIN(t2.id)
                            FROM tracks t2
                            GROUP BY LOWER(t2.title), LOWER(t2.artist)
                        )
                    )
                """
                )
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value, category) VALUES ('migration_dup_cleanup_done', '1', 'system')"
                )
            except Exception as e:
                logger.debug(f"Dup migration: {e}")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rule_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                    title, artist, album, genre,
                    content='tracks', content_rowid='id'
                )
            """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
                    INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                    VALUES (new.id, new.title, new.artist, new.album, new.genre);
                END;
            """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre)
                    VALUES('delete', old.id, old.title, old.artist, old.album, old.genre);
                END;
            """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre)
                    VALUES('delete', old.id, old.title, old.artist, old.album, old.genre);
                    INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                    VALUES (new.id, new.title, new.artist, new.album, new.genre);
                END;
            """
            )

            cursor.execute("SELECT COUNT(*) FROM tracks_fts")
            fts_cnt = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tracks")
            trk_cnt = cursor.fetchone()[0]
            if fts_cnt == 0 and trk_cnt > 0:
                cursor.execute(
                    """
                        INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                        SELECT id, title, artist, album, genre FROM tracks
                    """
                )
        except Exception as e:
            logger.warning(f"FTS Migration error: {e}")

        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN lufs REAL DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN peak_volume REAL DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        conn.commit()

    def add_track(
        self,
        title: str,
        artist: str = "Unknown Artist",
        album: str = "Unknown Album",
        duration: float = 0,
        file_path: Optional[str] = None,
        source: str = "local",
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
        cover_path: Optional[str] = None,
        cover_url: Optional[str] = None,
        bitrate: int = 0,
        format_: Optional[str] = None,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        **kwargs: Any,
    ) -> int:
        cursor = self.conn.cursor()

        if source != "local" and source_id:
            cursor.execute(
                "SELECT id, cover_url, file_path FROM tracks WHERE source = ? AND source_id = ?",
                (source, source_id),
            )
            row = cursor.fetchone()
            if row:
                t_id = row["id"]
                if cover_url and not row["cover_url"]:
                    cursor.execute("UPDATE tracks SET cover_url = ? WHERE id = ?", (cover_url, t_id))
                if file_path and not row["file_path"]:
                    cursor.execute(
                        "UPDATE tracks SET file_path = ?, is_downloaded = 1 WHERE id = ?",
                        (file_path, t_id),
                    )
                self.conn.commit()
                return t_id

        if file_path:
            cursor.execute("SELECT id FROM tracks WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            if row:
                return row["id"]

        if title and title != "Unknown":
            cursor.execute(
                "SELECT id, cover_url, file_path FROM tracks WHERE LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)",
                (title, artist),
            )
            row = cursor.fetchone()
            if row:
                t_id = row["id"]
                if cover_url and not row["cover_url"]:
                    cursor.execute("UPDATE tracks SET cover_url = ? WHERE id = ?", (cover_url, t_id))
                if file_path and not row["file_path"]:
                    cursor.execute(
                        "UPDATE tracks SET file_path = ?, is_downloaded = 1 WHERE id = ?",
                        (file_path, t_id),
                    )
                self.conn.commit()
                return t_id

        metadata_json = json.dumps(kwargs) if kwargs else None
        fp_to_save = file_path or None

        cursor.execute(
            """
            INSERT INTO tracks (title, artist, album, duration, file_path,
                source, source_id, source_url, cover_path, cover_url,
                bitrate, format, genre, year, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                title,
                artist,
                album,
                duration,
                fp_to_save,
                source,
                source_id,
                source_url,
                cover_path,
                cover_url,
                bitrate,
                format_,
                genre,
                year,
                metadata_json,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_track_by_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_track_by_source_id(self, source: str, source_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE source = ? AND source_id = ?", (source, source_id))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_tracks(
        self,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: str = "added_at DESC",
    ) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        sql = "SELECT * FROM tracks"
        params: list = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += f" ORDER BY {order_by}"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_tracks_count(self, source: Optional[str] = None) -> int:
        cursor = self.conn.cursor()
        if source:
            cursor.execute("SELECT COUNT(*) FROM tracks WHERE source = ?", (source,))
        else:
            cursor.execute("SELECT COUNT(*) FROM tracks")
        return cursor.fetchone()[0]

    def get_tracks_count_by_favorite(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks WHERE is_favorite = 1")
        return cursor.fetchone()[0]

    def get_favorite_tracks(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE is_favorite = 1 ORDER BY added_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def toggle_favorite(self, track_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT is_favorite FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()
        if not row:
            return False
        new_val = 0 if row["is_favorite"] else 1
        cursor.execute("UPDATE tracks SET is_favorite = ? WHERE id = ?", (new_val, track_id))
        self.conn.commit()
        return bool(new_val)

    def ensure_track_exists(self, track_data: Dict[str, Any]) -> int:
        return self.add_track(
            title=track_data.get("title", "Unknown"),
            artist=track_data.get("artist", "Unknown Artist"),
            album=track_data.get("album", "Unknown Album"),
            duration=track_data.get("duration", 0),
            file_path=track_data.get("file_path"),
            source=track_data.get("source", "local"),
            source_id=track_data.get("source_id"),
            source_url=track_data.get("source_url"),
            cover_path=track_data.get("cover_path"),
            cover_url=track_data.get("cover_url"),
            bitrate=track_data.get("bitrate", 0),
            format_=track_data.get("format"),
            genre=track_data.get("genre"),
            year=track_data.get("year"),
        )

    def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
        self.conn.commit()

    def get_downloaded_tracks(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE is_downloaded = 1 ORDER BY added_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def log_listening_history(self, track_id: int, duration_listened: float = 0, completed: bool = False) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO history (track_id, duration_listened, completed) VALUES (?, ?, ?)",
            (track_id, duration_listened, 1 if completed else 0),
        )
        cursor.execute(
            "UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?",
            (track_id,),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_track_play(self, track_id: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?",
            (track_id,),
        )
        self.conn.commit()

    def search_tracks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        like_query = f"%{query}%"
        cursor.execute(
            """
            SELECT * FROM tracks 
            WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
            ORDER BY play_count DESC
            LIMIT ?
        """,
            (like_query, like_query, like_query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_artists(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        like_query = f"%{query}%"
        cursor.execute(
            """
            SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays
            FROM tracks
            WHERE artist LIKE ?
            GROUP BY artist
            ORDER BY total_plays DESC
            LIMIT ?
        """,
            (like_query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_track(self, track_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_track(self, track_id: int, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        cursor = self.conn.cursor()
        set_clauses = [f"{k} = ?" for k in kwargs.keys()]
        sql = f"UPDATE tracks SET {', '.join(set_clauses)} WHERE id = ?"
        params = list(kwargs.values()) + [track_id]
        cursor.execute(sql, params)
        self.conn.commit()
        return cursor.rowcount > 0

    def add_to_history(self, track_id: int, duration_listened: float = 0, completed: bool = False) -> int:
        return self.log_listening_history(track_id, duration_listened, completed)

    def update_history_duration(self, history_id: int, duration_sec: float, completed: bool = False) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE history SET duration_listened = ?, completed = ? WHERE id = ?",
            (duration_sec, 1 if completed else 0, history_id),
        )
        self.conn.commit()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT h.*, t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id
            FROM history h
            JOIN tracks t ON h.track_id = t.id
            ORDER BY h.played_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_most_played(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM tracks 
            WHERE play_count > 0
            ORDER BY play_count DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_top_artists(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays
            FROM tracks
            WHERE artist != 'Unknown Artist'
            GROUP BY artist
            ORDER BY total_plays DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_analytics_summary(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks")
        total_tracks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM playlists")
        total_playlists = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(duration_listened) FROM history")
        total_time_row = cursor.fetchone()[0]
        total_time = total_time_row if total_time_row else 0

        return {
            "total_tracks": total_tracks,
            "total_playlists": total_playlists,
            "total_listening_time": total_time,
        }

    def create_playlist(self, name: str, description: str = "") -> int:
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO playlists (name, description) VALUES (?, ?)", (name, description))
        self.conn.commit()
        return cursor.lastrowid

    def get_playlists(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT p.*, COUNT(pt.track_id) as track_count
            FROM playlists p
            LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
            GROUP BY p.id
            ORDER BY p.updated_at DESC
        """
        )
        return [dict(row) for row in cursor.fetchall()]

    def add_to_playlist(self, playlist_id: int, track_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        )
        next_pos = cursor.fetchone()[0]
        try:
            cursor.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                (playlist_id, track_id, next_pos),
            )
            cursor.execute("UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (playlist_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to add to playlist: {e}")
            return False

    def get_smart_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
        return self.get_playlist_tracks(playlist_id)

    def get_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT t.*, pt.position, pt.added_at as added_to_playlist_at
            FROM playlist_tracks pt
            JOIN tracks t ON pt.track_id = t.id
            WHERE pt.playlist_id = ?
            ORDER BY pt.position ASC
        """,
            (playlist_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_playlist(self, playlist_id: int) -> bool:
        pid = int(playlist_id)
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (pid,))
        cursor.execute("DELETE FROM playlists WHERE id = ?", (pid,))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_setting(self, key: str, value: str, category: str = "general") -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (key, value, category),
        )
        self.conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

    def get_settings_by_category(self, category: str) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings WHERE category = ?", (category,))
        result = {}
        for row in cursor.fetchall():
            try:
                result[row[0]] = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                result[row[0]] = row[1]
        return result

    def get_all_settings(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        result = {}
        for row in cursor.fetchall():
            try:
                result[row[0]] = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                result[row[0]] = row[1]
        return result

    def set_cached_file(self, source: str, source_id: str, file_path: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE stream_cache SET cached_file_path = ? WHERE source = ? AND source_id = ?",
            (file_path, source, source_id),
        )
        self.conn.commit()

    def get_cached_stream(self, source: str, source_id: str, max_age_seconds: int = 86400) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM stream_cache 
            WHERE source = ? AND source_id = ? 
            AND (strftime('%s', 'now') - strftime('%s', cached_at)) < ?
        """,
            (source, source_id, max_age_seconds),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def cache_stream(
        self,
        source: str,
        source_id: str,
        stream_url: str,
        title: str = "",
        artist: str = "",
        cover_url: str = "",
        duration: float = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        cursor = self.conn.cursor()
        meta_json = json.dumps(metadata) if metadata else None
        cursor.execute(
            """
            INSERT OR REPLACE INTO stream_cache 
            (source, source_id, stream_url, title, artist, cover_url, duration, metadata_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
            (source, source_id, stream_url, title, artist, cover_url, duration, meta_json),
        )
        self.conn.commit()

    def add_scan_folder(self, folder_path: str) -> bool:
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO scan_folders (folder_path) VALUES (?)", (folder_path,))
            self.conn.commit()
            return True
        except Exception:
            return False

    def get_scan_folders(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM scan_folders ORDER BY folder_path ASC")
        return [dict(row) for row in cursor.fetchall()]

    def update_scan_time(self, folder_path: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE scan_folders SET last_scanned = CURRENT_TIMESTAMP WHERE folder_path = ?",
            (folder_path,),
        )
        self.conn.commit()

    def add_listening_time(self, duration_ms: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO listening_stats (duration_ms) VALUES (?)", (duration_ms,))
        self.conn.commit()

    def get_total_listening_time(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM listening_stats")
        return cursor.fetchone()[0]

    def close(self) -> None:
        if hasattr(self._local, "connection") and self._local.connection:
            try:
                self._local.connection.close()
            except Exception:
                pass
            self._local.connection = None
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None
