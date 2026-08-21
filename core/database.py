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

# Whitelist of columns that update_track() may write. Mirrors the `tracks`
# CREATE TABLE in _init_database plus the ALTER-added columns (is_downloaded,
# lufs, peak_volume). `id` is deliberately absent: it is the WHERE key of the
# UPDATE, never a SET target. Anything not listed here is refused, so
# caller-supplied kwargs keys can never reach the SQL text.
TRACKS_UPDATABLE_COLUMNS = frozenset({
    "title",
    "artist",
    "album",
    "duration",
    "file_path",
    "source",
    "source_id",
    "source_url",
    "cover_path",
    "cover_url",
    "bitrate",
    "sample_rate",
    "format",
    "file_size",
    "loudness_lufs",
    "genre",
    "year",
    "track_number",
    "added_at",
    "last_played",
    "play_count",
    "is_favorite",
    "is_cached",
    "metadata_json",
    "is_downloaded",
    "lufs",
    "peak_volume",
})

# Whitelist of ORDER BY expressions accepted by get_all_tracks(). The value is
# interpolated into the SQL text, so anything outside this set is replaced by
# the default.
ALLOWED_TRACK_ORDER_BY = frozenset({
    "added_at DESC",
    "added_at ASC",
    "title ASC",
    "title DESC",
    "artist ASC",
    "artist DESC",
    "album ASC",
    "album DESC",
    "duration ASC",
    "duration DESC",
    "play_count DESC",
    "play_count ASC",
    "last_played DESC",
    "last_played ASC",
})

DEFAULT_TRACK_ORDER_BY = "added_at DESC"


class DatabaseManager:
    """
    Thread-safe SQLite database manager for NeDotify.
    """

    def __init__(self, db_path: str = None) -> None:
        # Per-instance thread-local storage. This MUST NOT be a class attribute:
        # a shared store makes every DatabaseManager instance hand back the first
        # connection the calling thread ever opened, i.e. the wrong database file.
        self._local = threading.local()
        if db_path is None:
            app_data = os.path.join(os.path.expanduser("~"), ".nedotify")
            os.makedirs(app_data, exist_ok=True)
            db_path = os.path.join(app_data, "nedotify_storage.db")
        self.db_path = db_path
        self._fts_available = False
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
            conn = sqlite3.connect(self.db_path, timeout=20.0)
            conn.row_factory = sqlite3.Row
            try:
                if self.db_path != ":memory:":
                    conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute("PRAGMA cache_size=-8000")
                conn.execute("PRAGMA busy_timeout=10000")
                conn.execute("PRAGMA foreign_keys=ON")
            except Exception:
                pass
            self._local.connection = conn
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
        # One index on history(played_at) is enough - SQLite walks it in either
        # direction, so a second DESC copy would only add write cost.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_played_at ON history(played_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_track_id ON history(track_id);")

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
        # stream_cache(source, source_id) needs no explicit index: the
        # UNIQUE(source, source_id) constraint on the table already provides one.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pid ON playlist_tracks(playlist_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_tid ON playlist_tracks(track_id)")
        # get_track_by_path() runs on every watchdog and LUFS file event, and
        # older databases were created without UNIQUE on file_path, so they have
        # no implicit index to lean on.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_file_path ON tracks(file_path)")
        # Intentionally NOT UNIQUE: existing user databases may already hold
        # duplicate (source, source_id) rows, and a failing CREATE UNIQUE INDEX
        # would abort startup.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_source_sid ON tracks(source, source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_added_at ON tracks(added_at DESC)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_play_count ON tracks(play_count DESC, last_played DESC)"
        )

        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN is_downloaded INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE playlists ADD COLUMN cover_url TEXT")
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

        # Migrate legacy history rows with 0 duration to track duration
        try:
            cursor.execute(
                """
                UPDATE history 
                SET duration_listened = (
                    SELECT COALESCE(NULLIF(t.duration, 0), 180.0) 
                    FROM tracks t 
                    WHERE t.id = history.track_id
                )
                WHERE duration_listened IS NULL OR duration_listened <= 0
                """
            )
        except Exception as e:
            logger.debug(f"History duration migration: {e}")

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
            self._fts_available = True
        except Exception as e:
            self._fts_available = False
            logger.warning(f"FTS Migration error (LIKE fallback will be used): {e}")

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

        is_downloaded = int(kwargs.pop("is_downloaded", 0))
        is_favorite = int(kwargs.pop("is_favorite", 0))
        is_cached = int(kwargs.pop("is_cached", 0))

        metadata_json = json.dumps(kwargs) if kwargs else None
        fp_to_save = file_path or None

        cursor.execute(
            """
            INSERT INTO tracks (title, artist, album, duration, file_path,
                source, source_id, source_url, cover_path, cover_url,
                bitrate, format, genre, year, is_downloaded, is_favorite, is_cached, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                is_downloaded,
                is_favorite,
                is_cached,
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
        order_by: str = DEFAULT_TRACK_ORDER_BY,
    ) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        safe_order_by = (order_by or "").strip()
        if safe_order_by not in ALLOWED_TRACK_ORDER_BY:
            logger.warning(
                f"get_all_tracks: rejected ORDER BY {order_by!r}, "
                f"falling back to {DEFAULT_TRACK_ORDER_BY!r}"
            )
            safe_order_by = DEFAULT_TRACK_ORDER_BY
        sql = "SELECT * FROM tracks"
        params: list = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += f" ORDER BY {safe_order_by}"
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

    def get_most_played_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE play_count > 0 ORDER BY play_count DESC, last_played DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_recently_added_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tracks ORDER BY added_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_user_history_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT t.* FROM tracks t
            JOIN history h ON t.id = h.track_id
            ORDER BY h.played_at DESC LIMIT ?
        """, (limit,))
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
        if duration_listened <= 0:
            cursor.execute("SELECT duration FROM tracks WHERE id = ?", (track_id,))
            t_row = cursor.fetchone()
            if t_row and t_row[0] and float(t_row[0]) > 0:
                duration_listened = float(t_row[0])
            else:
                duration_listened = 180.0
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
        # O-10: FTS5 first, LIKE fallback
        if getattr(self, "_fts_available", False) and query.strip():
            try:
                # Prefix-match each word, escaped for FTS5 quoted strings
                terms = " ".join(
                    '"' + w.replace('"', '""') + '"*'
                    for w in query.split()
                    if w
                )
                if terms:
                    cursor.execute(
                        """
                        SELECT t.* FROM tracks_fts f JOIN tracks t ON t.id = f.rowid
                        WHERE tracks_fts MATCH ?
                        ORDER BY t.play_count DESC
                        LIMIT ?
                    """,
                        (terms, limit),
                    )
                    rows = cursor.fetchall()
                    if rows:
                        return [dict(row) for row in rows]
            except Exception:
                pass  # malformed query / FTS unavailable at query time → LIKE fallback
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
            SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays, SUM(play_count) as play_count, SUM(play_count) as plays
            FROM tracks
            WHERE artist LIKE ?
            GROUP BY artist
            ORDER BY total_plays DESC
            LIMIT ?
        """,
            (like_query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_albums(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        like_query = f"%{query}%"
        cursor.execute(
            """
            SELECT album as title, artist, cover_path, cover_url, COUNT(id) as track_count, MAX(year) as year, 'local' as source, 'album' as type
            FROM tracks
            WHERE (album LIKE ? OR artist LIKE ?) AND album IS NOT NULL AND album != '' AND album != 'Unknown Album'
            GROUP BY LOWER(album), LOWER(artist)
            ORDER BY track_count DESC
            LIMIT ?
        """,
            (like_query, like_query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_playlist_track_count(self, playlist_id: int) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?", (int(playlist_id),))
        row = cursor.fetchone()
        return row[0] if row else 0

    def search_playlists(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        pattern = f"%{query.strip()}%"
        try:
            cursor.execute("SELECT id, name, description, created_at, cover_url FROM playlists WHERE name LIKE ? ORDER BY name ASC LIMIT ?", (pattern, limit))
        except Exception:
            cursor.execute("SELECT id, name, description, created_at, cover_path as cover_url FROM playlists WHERE name LIKE ? ORDER BY name ASC LIMIT ?", (pattern, limit))
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "title": r["name"],
                "name": r["name"],
                "description": dict(r).get("description") or "",
                "author": "Local",
                "artist": "Local",
                "source": "local",
                "source_id": str(r["id"]),
                "type": "playlist",
                "cover_url": dict(r).get("cover_url") or dict(r).get("cover_path") or "",
                "track_count": self.get_playlist_track_count(r["id"]) if hasattr(self, "get_playlist_track_count") else 0,
            }
            for r in rows
        ]

    def get_album_tracks(self, album_title: str, artist: str = None) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        if artist:
            cursor.execute(
                "SELECT * FROM tracks WHERE LOWER(album) = LOWER(?) AND (LOWER(artist) = LOWER(?) OR artist = 'Unknown Artist') ORDER BY track_number ASC, title ASC",
                (album_title, artist)
            )
        else:
            cursor.execute(
                "SELECT * FROM tracks WHERE LOWER(album) = LOWER(?) ORDER BY track_number ASC, title ASC",
                (album_title,)
            )
        return [dict(row) for row in cursor.fetchall()]

    def delete_track(self, track_id: int) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_track(self, track_id: int, **kwargs: Any) -> bool:
        """Update whitelisted columns of one track. Unknown keys are dropped."""
        if not kwargs:
            return False

        set_clauses = []
        params: list = []
        for key, value in kwargs.items():
            if key not in TRACKS_UPDATABLE_COLUMNS:
                logger.warning(f"update_track: ignoring unknown column {key!r}")
                continue
            set_clauses.append(f"{key} = ?")
            params.append(value)

        if not set_clauses:
            logger.warning(f"update_track: no valid columns supplied for track {track_id}")
            return False

        params.append(track_id)
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE tracks SET {', '.join(set_clauses)} WHERE id = ?", params)
        self.conn.commit()
        return cursor.rowcount > 0

    def update_track_metadata(
        self,
        track_id: int,
        title: str,
        artist: str,
        album: Optional[str] = None,
        genre: Optional[str] = None,
        year: Optional[int] = None,
        cover_path: Optional[str] = None
    ) -> bool:
        """Update track metadata in SQLite and explicitly rebuild FTS index row."""
        try:
            old = self.get_track(track_id)
            if not old:
                return False

            cursor = self.conn.cursor()
            query = """
                UPDATE tracks
                SET title = ?,
                    artist = ?,
                    album = COALESCE(?, album),
                    genre = COALESCE(?, genre),
                    year = COALESCE(?, year),
                    cover_path = COALESCE(?, cover_path)
                WHERE id = ?
            """
            cursor.execute(
                query,
                (title, artist, album, genre, year, cover_path, track_id)
            )

            # Explicit FTS index row rebuild (delete old + insert new)
            if getattr(self, "_fts_available", False):
                try:
                    cursor.execute(
                        "INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre) VALUES('delete', ?, ?, ?, ?, ?)",
                        (track_id, old.get("title"), old.get("artist"), old.get("album"), old.get("genre"))
                    )
                    cursor.execute(
                        "INSERT INTO tracks_fts(rowid, title, artist, album, genre) VALUES(?, ?, ?, ?, ?)",
                        (track_id, title, artist, album or old.get("album"), genre or old.get("genre"))
                    )
                except Exception as fts_err:
                    logger.debug(f"FTS resync warning during metadata update: {fts_err}")

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error in update_track_metadata for track {track_id}: {e}")
            return False


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
            SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays, SUM(play_count) as play_count, SUM(play_count) as plays
            FROM tracks
            WHERE artist != 'Unknown Artist'
            GROUP BY artist
            ORDER BY total_plays DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_wrapped_stats(self, period: str = "week") -> Dict[str, Any]:
        """Calculate wrapped listening analytics for the specified period ('week', 'month', 'all')."""
        cursor = self.conn.cursor()
        
        where_clause = ""
        if period == "week":
            where_clause = "WHERE h.played_at >= datetime('now', '-7 days')"
        elif period == "month":
            where_clause = "WHERE h.played_at >= datetime('now', '-30 days')"
        elif period == "year":
            where_clause = "WHERE h.played_at >= datetime('now', '-365 days')"

        # 1. Total listening time & plays count
        query_totals = f"""
            SELECT COUNT(h.id) as total_plays, 
                   COALESCE(SUM(CASE 
                        WHEN h.duration_listened > 0 THEN h.duration_listened 
                        WHEN t.duration > 0 THEN t.duration 
                        ELSE 180.0 
                   END), 0) as total_sec
            FROM history h
            LEFT JOIN tracks t ON h.track_id = t.id
            {where_clause}
        """
        cursor.execute(query_totals)
        row_tot = cursor.fetchone()
        total_plays = row_tot["total_plays"] if row_tot else 0
        total_sec = float(row_tot["total_sec"]) if row_tot else 0.0

        # 2. Top 5 tracks for period
        query_top_tracks = f"""
            SELECT t.id, t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id,
                   COUNT(h.id) as plays, 
                   COALESCE(SUM(CASE 
                        WHEN h.duration_listened > 0 THEN h.duration_listened 
                        WHEN t.duration > 0 THEN t.duration 
                        ELSE 180.0 
                   END), 0) as total_listened_sec
            FROM history h
            JOIN tracks t ON h.track_id = t.id
            {where_clause}
            GROUP BY t.id
            ORDER BY plays DESC, total_listened_sec DESC
            LIMIT 5
        """
        cursor.execute(query_top_tracks)
        top_tracks = [dict(r) for r in cursor.fetchall()]

        # 3. Top 5 artists for period
        query_top_artists = f"""
            SELECT t.artist, 
                   COUNT(h.id) as plays, 
                   COALESCE(SUM(CASE 
                        WHEN h.duration_listened > 0 THEN h.duration_listened 
                        WHEN t.duration > 0 THEN t.duration 
                        ELSE 180.0 
                   END), 0) as total_listened_sec
            FROM history h
            JOIN tracks t ON h.track_id = t.id
            {where_clause}
            AND t.artist IS NOT NULL AND t.artist != '' AND t.artist != 'Unknown Artist'
            GROUP BY LOWER(t.artist)
            ORDER BY plays DESC, total_listened_sec DESC
            LIMIT 5
        """
        cursor.execute(query_top_artists)
        top_artists = [dict(r) for r in cursor.fetchall()]

        # 4. Activity breakdown by day of week (Mon-Sun)
        query_activity = f"""
            SELECT strftime('%w', h.played_at) as day_idx,
                   COUNT(h.id) as plays,
                   COALESCE(SUM(CASE 
                        WHEN h.duration_listened > 0 THEN h.duration_listened 
                        WHEN t.duration > 0 THEN t.duration 
                        ELSE 180.0 
                   END), 0) / 60.0 as minutes
            FROM history h
            LEFT JOIN tracks t ON h.track_id = t.id
            {where_clause}
            GROUP BY day_idx
        """
        cursor.execute(query_activity)
        activity_rows = {str(r["day_idx"]): dict(r) for r in cursor.fetchall()}

        days_map = [
            {"day": "Вс", "idx": "0", "minutes": 0, "plays": 0},
            {"day": "Пн", "idx": "1", "minutes": 0, "plays": 0},
            {"day": "Вт", "idx": "2", "minutes": 0, "plays": 0},
            {"day": "Ср", "idx": "3", "minutes": 0, "plays": 0},
            {"day": "Чт", "idx": "4", "minutes": 0, "plays": 0},
            {"day": "Пт", "idx": "5", "minutes": 0, "plays": 0},
            {"day": "Сб", "idx": "6", "minutes": 0, "plays": 0},
        ]
        for d in days_map:
            if d["idx"] in activity_rows:
                d["minutes"] = round(float(activity_rows[d["idx"]]["minutes"]), 1)
                d["plays"] = int(activity_rows[d["idx"]]["plays"])

        # Reorder to Mon-Sun
        daily_activity = days_map[1:] + [days_map[0]]

        return {
            "period": period,
            "total_plays": total_plays,
            "total_seconds": round(total_sec, 1),
            "total_minutes": round(total_sec / 60.0, 1),
            "total_hours": round(total_sec / 3600.0, 2),
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            "daily_activity": daily_activity
        }

    def get_analytics_summary(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks")
        total_tracks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM playlists")
        total_playlists = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(CASE 
                WHEN h.duration_listened > 0 THEN h.duration_listened 
                WHEN t.duration > 0 THEN t.duration 
                ELSE 180.0 
            END), 0) 
            FROM history h
            LEFT JOIN tracks t ON h.track_id = t.id
        """)
        total_time_row = cursor.fetchone()[0]
        total_time = total_time_row if total_time_row else 0

        return {
            "total_tracks": total_tracks,
            "total_playlists": total_playlists,
            "total_listening_time": total_time,
        }

    def create_playlist(self, name: str, description: str = "") -> int:
        cursor = self.conn.cursor()
        clean_name = (name or "").strip()
        # If playlist with same name already exists (especially system names), reuse it
        cursor.execute("SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) LIMIT 1", (clean_name,))
        row = cursor.fetchone()
        if row:
            return row["id"]

        cursor.execute("INSERT INTO playlists (name, description) VALUES (?, ?)", (clean_name, description))
        self.conn.commit()
        return cursor.lastrowid

    def get_playlists(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        # Clean up duplicate empty system playlists with exact same name
        try:
            cursor.execute("""
                DELETE FROM playlists 
                WHERE name IN ('Локальные', 'Локальные треки') 
                AND id NOT IN (SELECT DISTINCT playlist_id FROM playlist_tracks)
                AND id NOT IN (
                    SELECT MIN(id) FROM playlists 
                    WHERE name IN ('Локальные', 'Локальные треки') 
                    GROUP BY name
                )
            """)
            self.conn.commit()
        except Exception:
            pass

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

    def get_playlists_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM playlists")
        return cursor.fetchone()[0]

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

    @staticmethod
    def _serialize_setting(value: Any) -> str:
        if isinstance(value, (dict, list, bool, int, float)):
            return json.dumps(value)
        if value is None:
            return ""
        return str(value)

    def set_setting(self, key: str, value: Any, category: str = "general") -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (key, self._serialize_setting(value), category),
        )
        self.conn.commit()

    def set_settings_batch(self, items: Any) -> int:
        """Persist many settings inside a single transaction.

        `items` is a sequence of (key, value, category) tuples; returns the
        number of rows written. SettingsManager's write-behind batching uses
        this so a burst of set() calls costs one COMMIT instead of one each.
        """
        rows = [
            (key, self._serialize_setting(value), category)
            for key, value, category in items
        ]
        if not rows:
            return 0
        conn = self.conn
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO settings (key, value, category, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                rows,
            )
        return len(rows)

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return default
        raw_v = row["value"]
        try:
            return json.loads(raw_v)
        except (json.JSONDecodeError, TypeError):
            if raw_v in ("True", "true"):
                return True
            elif raw_v in ("False", "false"):
                return False
            return raw_v

    def get_settings_by_category(self, category: str) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings WHERE category = ?", (category,))
        result = {}
        for row in cursor.fetchall():
            k, raw_v = row[0], row[1]
            try:
                result[k] = json.loads(raw_v)
            except (json.JSONDecodeError, TypeError):
                if raw_v in ("True", "true"):
                    result[k] = True
                elif raw_v in ("False", "false"):
                    result[k] = False
                else:
                    result[k] = raw_v
        return result

    def get_all_settings(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        result = {}
        for row in cursor.fetchall():
            k, raw_v = row[0], row[1]
            try:
                result[k] = json.loads(raw_v)
            except (json.JSONDecodeError, TypeError):
                if raw_v in ("True", "true"):
                    result[k] = True
                elif raw_v in ("False", "false"):
                    result[k] = False
                else:
                    result[k] = raw_v
        return result

    def set_cached_file(self, source: str, source_id: str, file_path: str) -> None:
        # O-3: downloaded files are long-lived — never auto-purged by expires_at
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE stream_cache SET cached_file_path = ?, expires_at = NULL, cached_at = CURRENT_TIMESTAMP "
            "WHERE source = ? AND source_id = ?",
            (file_path, source, source_id),
        )
        self.conn.commit()

    def get_cached_stream(self, source: str, source_id: str, max_age_seconds: int = 14400) -> Optional[Dict[str, Any]]:
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
        # ON CONFLICT DO UPDATE (not INSERT OR REPLACE) preserves cached_file_path
        cursor.execute(
            """
            INSERT INTO stream_cache 
            (source, source_id, stream_url, title, artist, cover_url, duration, metadata_json, cached_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, datetime('now', '+24 hours'))
            ON CONFLICT(source, source_id) DO UPDATE SET
                stream_url = excluded.stream_url,
                title = excluded.title,
                artist = excluded.artist,
                cover_url = excluded.cover_url,
                duration = excluded.duration,
                metadata_json = excluded.metadata_json,
                cached_at = CURRENT_TIMESTAMP,
                expires_at = datetime('now', '+24 hours')
        """,
            (source, source_id, stream_url, title, artist, cover_url, duration, meta_json),
        )
        self.conn.commit()

    def update_cached_stream_url(self, source: str, source_id: str, stream_url: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE stream_cache SET stream_url = ?, cached_at = CURRENT_TIMESTAMP, "
            "expires_at = datetime('now', '+24 hours') WHERE source = ? AND source_id = ?",
            (stream_url, source, source_id),
        )
        self.conn.commit()

    def invalidate_cached_stream(self, source: str, source_id: str) -> None:
        """Clear a dead stream URL but keep the row (downloaded-file rows survive)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE stream_cache SET stream_url = NULL WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        self.conn.commit()

    def cleanup_expired_cache(self) -> int:
        """O-3: purge stream_cache rows past expires_at (skips downloaded-file rows)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM stream_cache WHERE expires_at IS NOT NULL "
            "AND datetime(expires_at) < datetime('now') "
            "AND (cached_file_path IS NULL OR cached_file_path = '')"
        )
        self.conn.commit()
        return cursor.rowcount

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

    def close_thread_connection(self) -> None:
        """Close and forget the calling thread's connection, if it has one.

        Safe to call from any thread, repeatedly, and when no connection was
        ever opened; it never raises. Worker threads (stream proxy requests,
        scan workers) should call this when they finish so their page cache is
        released instead of living until process exit.
        """
        for attr in ("connection", "conn"):
            existing = getattr(self._local, attr, None)
            if existing is None:
                continue
            try:
                existing.close()
            except Exception:
                pass
            try:
                setattr(self._local, attr, None)
            except Exception:
                pass

    def close(self) -> None:
        self.close_thread_connection()
