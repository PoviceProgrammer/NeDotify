"""

NeDotify - SQLite Database Manager

Manages local storage: tracks, playlists, history, favorites, settings, cache.

"""



import sqlite3

import os

import json

import logging

import re

import threading

import uuid

import time

import functools

import unicodedata

import shutil

from datetime import datetime

from typing import Any, Dict, List, Optional, Tuple



from services import music_matching
from core.dpapi import (
    dpapi_encrypt,
    dpapi_decrypt,
    is_dpapi_encrypted,
    is_sensitive_setting,
)



logger = logging.getLogger(__name__)



@functools.lru_cache(maxsize=16384)

def _unicode_casefold_str(value: Any) -> str:

    """Matches services.music_matching.normalize semantics (NFKC + casefold + ё→е)."""

    return unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е')



@functools.lru_cache(maxsize=16384)

def _artist_primary_str(value: Any) -> str:

    """Semantics of services.music_matching.credits for primary credit aggregation."""

    from services.music_matching import credits

    parts = credits(value)

    return (parts[0] if parts else str(value or '').strip())



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



# --- The application's track identity ----------------------------------------------

# ONE definition, shared by the creation path (DatabaseManager.add_track) and the

# de-duplication migration (DatabaseManager._run_dup_cleanup_migration), so the two

# can never disagree about what "the same track" is.

#

# LOWER() on both sides is the case-insensitive comparison the creation path has

# always used, and a NULL never matches (SQLite's `=` semantics): a row whose

# artist is unknown carries no identity and must never be treated as a duplicate.

TRACK_IDENTITY_SQL = "LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)"



# The recording fields. Two rows may only be collapsed into one when they agree on

# ALL of them: the identity alone is too coarse - the same song title with a

# different album, a different provider id or a different file is a DIFFERENT

# recording, and the migration must not destroy it.

TRACK_RECORDING_COLUMNS = ("title", "artist", "album", "source", "source_id", "file_path")



# The payload that moves into the survivor when a duplicate is merged. The

# aggregates (play_count, is_favorite, last_played) are handled apart.

DUP_CARRY_OVER_COLUMNS = (

    "file_path", "cover_path", "cover_url", "source_id", "source_url",

    "duration", "bitrate", "sample_rate", "format", "file_size",

    "genre", "year", "track_number", "metadata_json", "is_cached",

    "is_downloaded", "loudness_lufs", "lufs", "peak_volume",

)



# Placeholder names carry no identity: the creation path has always refused to

# de-duplicate them (every placeholder matched every other one), and the

# migration must use the same guard or it would collapse rows the app treats as

# unrelated.

PLACEHOLDER_TRACK_NAMES = frozenset({

    "", "unknown", "unknown title", "unknown artist",

    "none", "null", "неизвестный трек",

})



# get_history is a recent-activity feed, so cap both the returned tracks and

# the event rows it aggregates. This keeps bridge calls bounded even when the

# library has years of listening history or a single track has many repeats.

HISTORY_RESULT_LIMIT = 200

HISTORY_EVENT_WINDOW = 20_000





def name_is_meaningful(title: Any, artist: Any) -> bool:

    """True when a title/artist pair identifies a track at all.



    A placeholder name ("Unknown Title") matches every other placeholder, so it

    carries no identity. The creation path and the de-duplication migration must

    agree on that, or the migration would collapse rows the app considers

    unrelated.

    """

    return bool(

        title

        and str(title).strip().lower() not in PLACEHOLDER_TRACK_NAMES

        and str(artist or "").strip().lower() not in PLACEHOLDER_TRACK_NAMES

    )





def _is_empty_value(value: Any) -> bool:

    """True for a column that carries no information yet (NULL, '', 0)."""

    if value is None:

        return True

    if isinstance(value, str):

        return value.strip() == ""

    if isinstance(value, (int, float)) and not isinstance(value, bool):

        return value == 0

    return False





# --- S4-003: YouTube-channel artifacts in provider metadata -------------------------

# Provider "artist" values often carry the channel name rather than the artist:

# autogenerated topic channels ("Artist - Topic"), label VEVO channels

# ("EminemVEVO", "Artist - Official") and re-upload channels. These must never

# replace a real name in the library, and a stripped-but-real name is only

# written when the row it lands on is a placeholder.

_CHANNEL_ARTIST_SUFFIX_RE = re.compile(

    r'\s*(?:[-–—]\s*)?(?:topic|vevo|official(?:\s+(?:artist|channel|music|audio|video))?)\s*$',

    re.IGNORECASE,

)

_CHANNEL_ARTIST_MIN_LEN = 2





def _clean_channel_artist(value: Any) -> str:

    """Strip channel-name artifacts ('- Topic', 'VEVO', 'Official') from a name.



    Returns the cleaned name, or '' when nothing meaningful remains (the caller

    must not write an empty artist over anything).

    """

    name = str(value or '').strip()

    # Repeatedly peel trailing segments: "Artist - Topic" and "EminemVEVO" both

    # end in exactly one artifact token, but "Artist - Official - Topic" exists.

    while name:

        stripped = _CHANNEL_ARTIST_SUFFIX_RE.sub('', name).strip()

        if stripped == name or len(stripped) < _CHANNEL_ARTIST_MIN_LEN:

            break

        name = stripped

    return name





def _is_placeholder_name(value: Any) -> bool:

    """True for the literal placeholders written when extraction failed."""

    return str(value or '').strip().lower() in {

        "", "unknown", "unknown title", "unknown artist", "unknown album",

        "none", "null", "неизвестный трек", "неизвестный артист",

    }





def _latest_timestamp(left: Any, right: Any) -> Any:

    """The later of two timestamps.



    SQLite stores CURRENT_TIMESTAMP as 'YYYY-MM-DD HH:MM:SS', so the strings

    compare correctly; a non-string value is ignored rather than guessed at.

    """

    if isinstance(left, str) and isinstance(right, str):

        return max(left, right)

    return left if left is not None else right





class DatabaseManager:

    """

    Thread-safe SQLite database manager for NeDotify.

    """



    def __init__(self, db_path: str = None) -> None:

        # Per-instance thread-local storage. This MUST NOT be a class attribute:

        # a shared store makes every DatabaseManager instance hand back the first

        # connection the calling thread ever opened, i.e. the wrong database file.

        self._local = threading.local()

        self._write_lock = threading.RLock()

        self._conns_lock = threading.Lock()

        self._all_conns = set()

        self._conn_owners = {}

        self._closed = False

        self._data_revision = 0

        if db_path is None:

            app_data = os.path.join(os.path.expanduser("~"), ".nedotify")

            os.makedirs(app_data, exist_ok=True)

            db_path = os.path.join(app_data, "nedotify_storage.db")

        self.db_path = db_path

        self._fts_available = False

        try:

            self._init_database()

        except sqlite3.DatabaseError as exc:

            if self.db_path == ":memory:":

                raise

            logger.critical("Corrupted database detected at %s: %s. Initiating recovery...", self.db_path, exc)

            self._recover_corrupted_database(exc)

            self._init_database()



    def _recover_corrupted_database(self, exc: Exception) -> None:

        """Move corrupted database file and sidecars to a timestamped backup and reset connections."""

        if not self.db_path or self.db_path == ":memory:":

            return



        ts = int(time.time())

        corrupted_path = f"{self.db_path}.corrupted.{ts}"

        counter = 1

        while os.path.exists(corrupted_path):

            corrupted_path = f"{self.db_path}.corrupted.{ts}_{counter}"

            counter += 1



        # Preserve WAL/SHM sidecars BEFORE closing SQLite connections, as SQLite's

        # internal close hook deletes -wal and -shm files automatically on close.

        for suffix in ["-wal", "-shm", ".wal", ".shm"]:

            sidecar = f"{self.db_path}{suffix}"

            if os.path.exists(sidecar):

                try:

                    shutil.copy2(sidecar, f"{corrupted_path}{suffix}")

                    logger.warning("Corrupted database sidecar %s preserved at %s%s", sidecar, corrupted_path, suffix)

                except Exception as e:

                    logger.error("Failed to preserve sidecar %s: %s", sidecar, e)



        # Close all active connections to free Windows file locks

        with self._conns_lock:

            for c in list(self._all_conns):

                try:

                    c.close()

                except Exception:

                    pass

            self._all_conns.clear()

            self._conn_owners.clear()

        if hasattr(self._local, "connection"):

            try:

                if self._local.connection is not None:

                    self._local.connection.close()

            except Exception:

                pass

            self._local.connection = None



        import gc

        gc.collect()



        # Move the main corrupted database file with retry for Windows file locks

        replaced = False

        for attempt in range(5):

            try:

                if os.path.exists(self.db_path):

                    os.replace(self.db_path, corrupted_path)

                    logger.warning("Corrupted database file %s moved to %s", self.db_path, corrupted_path)

                replaced = True

                break

            except Exception as e:

                time.sleep(0.05 * (attempt + 1))

                gc.collect()



        if not replaced and os.path.exists(self.db_path):

            try:

                shutil.copy2(self.db_path, corrupted_path)

                with open(self.db_path, "wb") as f:

                    f.truncate(0)

                logger.warning("Corrupted database file %s copied to %s and truncated", self.db_path, corrupted_path)

            except Exception as e:

                logger.error("Failed to move/truncate corrupted database %s: %s", self.db_path, e)



        # Remove any lingering original sidecar files if still present

        for suffix in ["-wal", "-shm", ".wal", ".shm"]:

            sidecar = f"{self.db_path}{suffix}"

            if os.path.exists(sidecar):

                try:

                    os.unlink(sidecar)

                except Exception:

                    pass



    def get(self, key_or_id: Any = None, default: Any = None, *args, **kwargs) -> Any:

        """Generic get helper supporting setting or track lookup."""

        # bool is a subclass of int, so without the explicit exclusion

        # get(True) silently became get_track(1) and returned whatever track

        # happens to hold rowid 1.

        if isinstance(key_or_id, int) and not isinstance(key_or_id, bool):

            return self.get_track(key_or_id)

        if isinstance(key_or_id, str):

            val = self.get_setting("general", key_or_id) if hasattr(self, 'get_setting') else None

            return val if val is not None else default

        return default



    def _get_connection(self) -> sqlite3.Connection:

        if self._closed:

            raise RuntimeError("Database is closed")

        # Bridge calls run on disposable threads. Release their handles on

        # the next admission rather than retaining one connection per call.

        with self._conns_lock:

            for old, owner in list(self._conn_owners.items()):

                if not owner.is_alive():

                    try:

                        self._data_revision += old.total_changes

                    except Exception:

                        pass

                    try:

                        old.close()

                    except Exception:

                        pass

                    self._all_conns.discard(old)

                    self._conn_owners.pop(old, None)

        if not hasattr(self._local, "connection") or self._local.connection is None:

            conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)

            # BUG-S4-008/009: SQLite LIKE and LOWER() ignore Unicode case and

            # treat ё≠е, so Cyrillic queries missed rows that differ only by

            # case/yo-form. This fold matches services.music_matching.normalize

            # semantics (NFKC + casefold + ё→е) inside SQL for LIKE and GROUP BY.

            conn.create_function("unicode_casefold", 1, _unicode_casefold_str, deterministic=True)

            conn.create_function("artist_primary", 1, _artist_primary_str, deterministic=True)

            conn.row_factory = sqlite3.Row

            pragmas = []

            if self.db_path != ":memory:":

                pragmas.append("PRAGMA journal_mode=WAL")

            pragmas.extend([

                "PRAGMA synchronous=NORMAL",

                "PRAGMA temp_store=MEMORY",

                "PRAGMA cache_size=-8000",

                "PRAGMA busy_timeout=5000",

                "PRAGMA foreign_keys=ON",

            ])

            for pragma_name in pragmas:

                try:

                    conn.execute(pragma_name)

                except Exception as e:

                    logger.warning("Database PRAGMA %s failed: %s", pragma_name, e)

            self._local.connection = conn

            with self._conns_lock:

                self._all_conns.add(conn)

                self._conn_owners[conn] = threading.current_thread()

        return self._local.connection



    @property

    def conn(self) -> sqlite3.Connection:

        return self._get_connection()



    @property

    def data_revision(self):

        with self._write_lock:

            with self._conns_lock:

                total = self._data_revision

                for conn in list(self._all_conns):

                    try:

                        total += conn.total_changes

                    except Exception:

                        pass

                return total



    def _init_database(self) -> None:

        conn = self.conn

        cursor = conn.cursor()



        if self.db_path and self.db_path != ":memory:":

            check = cursor.execute("PRAGMA quick_check(1)").fetchone()

            if not check or check[0] != "ok":

                raise sqlite3.DatabaseError(f"Database quick_check failed: {check[0] if check else 'empty'}")



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

        for name, definition in (('listening_measured', 'INTEGER DEFAULT 0'),

                                 ('session_finished', 'INTEGER DEFAULT 0'),

                                 ('media_listened', 'REAL DEFAULT 0'),

                                 ('recommendation_context', "TEXT DEFAULT ''")):

            try:

                cursor.execute(f'ALTER TABLE history ADD COLUMN {name} {definition}')

            except sqlite3.OperationalError as exc:

                if 'duplicate column name' not in str(exc).lower():

                    raise



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

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist_lower ON tracks(LOWER(artist))")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album_lower ON tracks(LOWER(album))")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title_lower ON tracks(LOWER(title))")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_play_count_artist ON tracks(play_count DESC, artist)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stream_cache_file ON stream_cache(cached_file_path)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_track_time ON history(track_id, played_at DESC)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_time ON history(played_at DESC)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_missing_cover ON tracks(added_at) WHERE cover_path IS NULL AND (cover_url IS NULL OR cover_url = '')")

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

        except sqlite3.OperationalError as error:

            if "duplicate column" not in str(error).lower():

                raise

        try:

            cursor.execute("ALTER TABLE playlists ADD COLUMN cover_url TEXT")

        except sqlite3.OperationalError as error:

            if "duplicate column" not in str(error).lower():

                raise

        if 'is_system' not in {row['name'] for row in cursor.execute('PRAGMA table_info(playlists)')}:

            cursor.execute('ALTER TABLE playlists ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0')

        if 'category' not in {row['name'] for row in cursor.execute('PRAGMA table_info(settings)')}:

            cursor.execute("ALTER TABLE settings ADD COLUMN category TEXT DEFAULT 'general'")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_downloaded ON tracks(is_downloaded)")



        # The download queue table used to be created lazily by DownloadManager,

        # so any code touching the db helpers first (or two processes racing at

        # startup) hit "no such table". Create it here, idempotently.

        self.ensure_download_queue_table(cursor=cursor)



        # Dup cleanup migration. P0-01: the old block DELETed every track row

        # that was not the MIN(id) of its (LOWER(title), LOWER(artist)) group and

        # let ON DELETE CASCADE take the rows' history, playlist entries, play

        # counts, favourite flags and file references with it - silently (the

        # block logged at DEBUG) and irreversibly (the desktop has no backup

        # feature). The replacement merges instead of deleting; see

        # _run_dup_cleanup_migration.

        self._run_dup_cleanup_migration()

        # The corrective migration: it restores what a previous merge retired

        # from the snapshot, and says plainly when there is nothing to restore.

        self._run_dup_cleanup_restore()



        # Only legacy inferred rows may be repaired. Measured zero is honest

        # and must survive restart; unknown-length songs stay zero too.

        try:

            self._run_data_migration(cursor, 'history_duration_backfill_v1', [

                """

                UPDATE history 

                SET duration_listened = (

                    SELECT COALESCE(t.duration, 0)

                    FROM tracks t 

                    WHERE t.id = history.track_id

                )

                WHERE listening_measured = 0 AND (duration_listened IS NULL OR duration_listened <= 0)

                """

            ])

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

            # Replace the old unconditional trigger on existing libraries too.

            trigger = cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='tracks_au'").fetchone()

            if trigger and 'AFTER UPDATE OF' not in trigger['sql'].upper():

                cursor.execute('DROP TRIGGER tracks_au')

            cursor.execute(

                """

                CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE OF title, artist, album, genre ON tracks

                WHEN old.title IS NOT new.title OR old.artist IS NOT new.artist

                  OR old.album IS NOT new.album OR old.genre IS NOT new.genre BEGIN

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

            cursor.execute("ALTER TABLE tracks ADD COLUMN loudness_lufs REAL DEFAULT NULL")

        except sqlite3.OperationalError as error:

            if "duplicate column" not in str(error).lower():

                raise



        try:

            cursor.execute("ALTER TABLE tracks ADD COLUMN lufs REAL DEFAULT NULL")

        except sqlite3.OperationalError as error:

            if "duplicate column" not in str(error).lower():

                raise



        try:

            self._run_data_migration(cursor, 'lufs_columns_backfill_v1', [

                "UPDATE tracks SET loudness_lufs = lufs WHERE loudness_lufs IS NULL AND lufs IS NOT NULL",

                "UPDATE tracks SET lufs = loudness_lufs WHERE lufs IS NULL AND loudness_lufs IS NOT NULL",

            ])

        except Exception:

            pass



        try:

            cursor.execute("ALTER TABLE tracks ADD COLUMN peak_volume REAL DEFAULT NULL")

        except sqlite3.OperationalError as error:

            if "duplicate column" not in str(error).lower():

                raise



        self._init_lyrics_overrides_table(cursor)

        self._init_availability_tracking(cursor)



        # A copied library keeps its identity even after tracks are removed or

        # new listening sessions are added. Android uses it to make repeated

        # desktop imports idempotent without conflating two PCs' row ids.

        cursor.execute(

            "INSERT OR IGNORE INTO settings (key, value, category) VALUES (?, ?, ?)",

            ("portable_library_id", str(uuid.uuid4()), "general"),

        )

        conn.commit()



    def _run_data_migration(self, cursor, version, statements):

        """Record a successful backfill in the same transaction as its writes."""

        if cursor.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():

            return

        for statement in statements:

            cursor.execute(statement)

        cursor.execute('INSERT INTO schema_migrations(version) VALUES (?)', (version,))



    def _init_lyrics_overrides_table(self, cursor):
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS track_lyrics_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER,
                identity_key TEXT NOT NULL UNIQUE,
                override_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_id TEXT,
                synced_lyrics TEXT,
                plain_lyrics TEXT NOT NULL,
                sync_type TEXT NOT NULL,
                offset_ms INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_lyrics_overrides_key ON track_lyrics_overrides(identity_key)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_lyrics_overrides_track_id ON track_lyrics_overrides(track_id)"
        )

    def _init_availability_tracking(self, cursor):

        # Scoped revision: listening progress and loudness writes do not expire

        # an availability index. Triggers also cover direct SQL cache changes.

        cursor.execute('CREATE TABLE IF NOT EXISTS library_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)')

        cursor.execute('INSERT OR IGNORE INTO library_revision VALUES (1,0)')

        for table, columns in [('tracks', ('file_path', 'source', 'source_id', 'added_at')),

                               ('stream_cache', ('source', 'source_id', 'cached_file_path'))]:

            for action in ('INSERT', 'DELETE'):

                cursor.execute(f'''CREATE TRIGGER IF NOT EXISTS availability_{table}_{action.lower()}

                    AFTER {action} ON {table} BEGIN UPDATE library_revision SET revision=revision+1 WHERE id=1; END''')

            changed = ' OR '.join(f'old.{name} IS NOT new.{name}' for name in columns)

            cursor.execute(f'''CREATE TRIGGER IF NOT EXISTS availability_{table}_update

                AFTER UPDATE OF {','.join(columns)} ON {table} WHEN {changed}

                BEGIN UPDATE library_revision SET revision=revision+1 WHERE id=1; END''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS lufs_analysis (

            track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,

            file_path TEXT, mtime_ns INTEGER, status TEXT)''')

        if 'file_size' not in {row['name'] for row in cursor.execute('PRAGMA table_info(lufs_analysis)')}:

            cursor.execute('ALTER TABLE lufs_analysis ADD COLUMN file_size INTEGER')

        cursor.execute('''CREATE TABLE IF NOT EXISTS lufs_pending (

            track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,

            generation INTEGER NOT NULL DEFAULT 1)''')

        cursor.execute('''CREATE TRIGGER IF NOT EXISTS lufs_track_insert AFTER INSERT ON tracks

            WHEN NULLIF(new.file_path,'') IS NOT NULL BEGIN

            INSERT INTO lufs_pending(track_id) VALUES(new.id)

            ON CONFLICT(track_id) DO UPDATE SET generation=generation+1; END''')

        cursor.execute('''CREATE TRIGGER IF NOT EXISTS lufs_track_path_update AFTER UPDATE OF file_path ON tracks

            WHEN old.file_path IS NOT new.file_path AND NULLIF(new.file_path,'') IS NOT NULL BEGIN

            INSERT INTO lufs_pending(track_id) VALUES(new.id)

            ON CONFLICT(track_id) DO UPDATE SET generation=generation+1; END''')



    @property

    def availability_revision(self):

        return self.conn.execute('SELECT revision FROM library_revision WHERE id=1').fetchone()[0]



    def enqueue_lufs_path(self, path):

        with self._write_lock, self.conn:

            self.conn.execute('''INSERT INTO lufs_pending(track_id) SELECT id FROM tracks WHERE file_path=?

                ON CONFLICT(track_id) DO UPDATE SET generation=generation+1''', (path,))



    # ------------------------------------------------------------------

    # De-duplication migration (P0-01) - non-destructive by construction

    # ------------------------------------------------------------------

    #

    # The version of the merge migration. Bump it to re-run the merge.

    DUP_CLEANUP_VERSION = "dup_cleanup_v3"

    # The version of the corrective (restore) migration.

    DUP_CLEANUP_RESTORE_VERSION = "dup_cleanup_restore_v2"

    # The legacy one-shot boolean. The destructive migration wrote '1'; this

    # build writes '2' into the same key, so a library that still carries '1'

    # was damaged by the old code and a library that carries '2' was cleaned by

    # this one. The flag is only ever written INSIDE the migration's

    # transaction, i.e. after a successful commit - and a library that already

    # carries the old value '1' keeps it: that value is a historical fact, and

    # this build leaves such a library exactly as it is.

    LEGACY_DUP_CLEANUP_FLAG = "migration_dup_cleanup_done"



    def _run_dup_cleanup_migration(self) -> None:

        """Merge duplicate tracks instead of deleting them (P0-01).



        What the old block did: it DELETed every track row that was not the

        MIN(id) of its (LOWER(title), LOWER(artist)) group, and ON DELETE

        CASCADE then took the row's history, playlist entries, play count,

        favourite flag, last-played stamp and file reference with it. It also

        stripped playlist entries by a playlist-local MIN(id) rule that could

        hit a track that SURVIVED the migration. The block logged at DEBUG

        (below the production level), the transaction was committed by the

        unconditional conn.commit() further down, and the desktop has no backup

        feature: a track, its listening history and its playlist membership

        were destroyed silently and irreversibly.



        What this block does:



        * it SNAPSHOTS the library first - a versioned VACUUM INTO copy next to

          the database plus a one-shot ``tracks_backup`` table (the corrective

          migration restores from it). The snapshot is taken only when there is

          something to merge: an empty library has nothing to lose;

        * it groups the rows by the application's own track identity

          (TRACK_IDENTITY_SQL - the same key DatabaseManager.add_track uses) and

          collapses only the rows that are additionally the SAME RECORDING

          (identical title, artist, album, source, source_id and file_path).

          Two rows that merely share a title/artist - a different album, a

          different provider id, a different file, a different spelling, an

          unknown artist - are DIFFERENT recordings and are left untouched;

        * a collapsed duplicate is MERGED, not dropped: its play count, favourite

          flag, last-played stamp and every other non-empty column move into

          the survivor, its history rows, playlist entries and download-queue

          rows are re-pointed at the survivor, and only then is the (now empty)

          duplicate row removed. No history row ever loses its track;

        * the playlist cleanup can no longer remove the entry of a surviving

          track: only a redundant second entry for the SAME (playlist, track)

          pair is removed;

        * the whole block runs in one transaction and the versioned record is

          written inside it, so a failure leaves the library untouched and the

          migration simply runs again on the next start;

        * everything it touched is named in a WARNING.

        """

        conn = self.conn

        cursor = conn.cursor()

        self._ensure_migration_tables(cursor)

        if cursor.execute(

            "SELECT version FROM schema_migrations WHERE version = ?",

            (self.DUP_CLEANUP_VERSION,),

        ).fetchone():

            return  # one shot - already applied, and the merge is idempotent



        legacy_value = None

        row = cursor.execute(

            "SELECT value FROM settings WHERE key = ?", (self.LEGACY_DUP_CLEANUP_FLAG,)

        ).fetchone()

        if row:

            legacy_value = row["value"]

        legacy_ran = legacy_value is not None and str(legacy_value) != "2"



        try:

            with self._write_lock:

                # The plan is computed read-only, BEFORE anything is written:

                # the snapshot is only taken when there is something to merge.

                if legacy_ran:

                    # The destructive migration already ran on this library. Its

                    # damage is done and cannot be undone (it took no snapshot),

                    # and the library is left exactly as it is: this migration

                    # only records that it ran. The corrective migration says so

                    # in the log.

                    plan, kept = [], 0

                    snapshot = None

                else:

                    plan, kept = self._plan_track_merges(cursor)

                    snapshot = self._snapshot_before_dup_cleanup(cursor) if plan else None

                with conn:

                    stats = self._apply_track_merges(cursor, plan)

                    stats["kept"] = kept

                    # A library that already ran the destructive cleanup is left

                    # exactly as it is - not even the redundant playlist entries

                    # are touched.

                    stats["playlist_entries_removed"] = (

                        0 if legacy_ran

                        else self._remove_exact_duplicate_playlist_entries(cursor)

                    )

                    details = json.dumps({

                        "snapshot": snapshot or "",

                        "legacy_destructive_migration_ran": legacy_ran,

                        **{k: v for k, v in stats.items()},

                    }, ensure_ascii=False)

                    cursor.execute(

                        "INSERT OR REPLACE INTO schema_migrations (version, applied_at, details) "

                        "VALUES (?, CURRENT_TIMESTAMP, ?)",

                        (self.DUP_CLEANUP_VERSION, details),

                    )

                    if not legacy_ran:

                        # The library never ran the destructive cleanup, so the

                        # key may be written - and only now, inside the

                        # transaction, i.e. after a successful commit. The value

                        # '2' marks the safe cleanup; the old code wrote '1'.

                        cursor.execute(

                            "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?, '2', 'system')",

                            (self.LEGACY_DUP_CLEANUP_FLAG,),

                        )

        except Exception as exc:

            logger.error(

                "Dup cleanup: the migration failed and was rolled back - the library is "

                "unchanged and the migration runs again on the next start: %s",

                exc, exc_info=True,

            )

            return



        if stats["merged"]:

            logger.warning(

                "Dup cleanup: merged %d duplicate track row(s) into %d survivor(s); "

                "%d history row(s) and %d playlist entr(y/ies) re-pointed, %d redundant "

                "playlist entr(y/ies) removed; %d same-title row(s) left in place because "

                "they are different recordings; snapshot: %s",

                stats["merged"], stats["survivors"], stats["history_moved"],

                stats["playlist_entries_moved"], stats["playlist_entries_removed"],

                stats["kept"], snapshot or "(none)",

            )

        elif legacy_ran:

            logger.error(

                "Dup cleanup: the legacy duplicate cleanup already ran on this library. "

                "It may have deleted tracks, listening history and playlist entries "

                "without a backup; missing data is not recoverable. The audio files "

                "may still be on disk - re-scan your music folders to restore tracks."

            )

        else:

            logger.info(

                "Dup cleanup: no duplicate recording found (%d same-title row(s) left in "

                "place - they are different recordings); snapshot: %s",

                stats["kept"], snapshot or "(none)",

            )



    def _run_dup_cleanup_restore(self) -> None:

        """Restore the rows a PREVIOUS merge migration retired (P0-01, R1.1 §1.6).



        The rows that were deleted by the legacy destructive migration cannot be

        restored: it took no snapshot, so there is nothing to restore them from.

        That is said plainly in the log instead of pretending the loss is

        repairable - the audio files are still on disk and a library re-scan

        brings the missing tracks back, but the listening history and the

        playlist entries are gone for good.

        """

        conn = self.conn

        cursor = conn.cursor()

        self._ensure_migration_tables(cursor)

        restore_row = cursor.execute(

            "SELECT details FROM schema_migrations WHERE version = ?",

            (self.DUP_CLEANUP_RESTORE_VERSION,),

        ).fetchone()

        if restore_row:

            try:

                details = json.loads(restore_row["details"] or "{}")

                if details.get("restored", 0) > 0:

                    return

            except (ValueError, TypeError):

                return

            tables = {

                r["name"] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()

            }

            if not {"tracks_backup", "track_merges"} <= tables:

                return

            has_candidates = cursor.execute(

                "SELECT 1 FROM track_merges WHERE merged_by <> ? AND duplicate_id NOT IN (SELECT id FROM tracks)",

                (self.DUP_CLEANUP_VERSION,),

            ).fetchone()

            if not has_candidates:

                return



        legacy_ran = False

        row = cursor.execute(

            "SELECT details FROM schema_migrations WHERE version = ?",

            (self.DUP_CLEANUP_VERSION,),

        ).fetchone()

        if row and row["details"]:

            try:

                legacy_ran = bool(json.loads(row["details"]).get("legacy_destructive_migration_ran"))

            except (ValueError, TypeError):

                legacy_ran = False



        try:

            with self._write_lock:

                with conn:

                    restored = self._restore_merged_tracks(cursor)

                    cursor.execute(

                        "INSERT OR REPLACE INTO schema_migrations (version, applied_at, details) "

                        "VALUES (?, CURRENT_TIMESTAMP, ?)",

                        (self.DUP_CLEANUP_RESTORE_VERSION, json.dumps({"restored": restored})),

                    )

        except Exception as exc:

            logger.error(

                "Dup cleanup restore: failed and was rolled back: %s", exc, exc_info=True

            )

            return



        if restored:

            logger.warning(

                "Dup cleanup restore: re-inserted %d track row(s) from the snapshot and "

                "re-pointed their history and playlist entries at them.",

                restored,

            )

        elif legacy_ran:

            logger.error(

                "Dup cleanup restore: the legacy duplicate cleanup (shipped with v2.0.0) "

                "already ran on this library. It deleted tracks, listening history and "

                "playlist entries WITHOUT taking a backup, so that data is NOT "

                "recoverable. The audio files are still on disk - re-scan your music "

                "folders to bring the missing tracks back; the listening history and the "

                "playlist entries cannot be restored."

            )

        else:

            logger.info(

                "Dup cleanup restore: nothing to restore - this library was never "

                "damaged by the legacy cleanup."

            )



    def _ensure_migration_tables(self, cursor) -> None:

        """The versioned migration record and the merge audit tables."""

        cursor.execute(

            """

            CREATE TABLE IF NOT EXISTS schema_migrations (

                version TEXT PRIMARY KEY,

                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                details TEXT

            )

            """

        )

        cursor.execute(

            """

            CREATE TABLE IF NOT EXISTS track_merges (

                duplicate_id INTEGER PRIMARY KEY,

                survivor_id INTEGER NOT NULL,

                merged_by TEXT NOT NULL,

                merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )

            """

        )

        cursor.execute(

            """

            CREATE TABLE IF NOT EXISTS history_track_remap (

                history_id INTEGER PRIMARY KEY,

                original_track_id INTEGER NOT NULL

            )

            """

        )

        cursor.execute(

            """

            CREATE TABLE IF NOT EXISTS playlist_tracks_track_remap (

                playlist_tracks_id INTEGER PRIMARY KEY,

                original_track_id INTEGER NOT NULL

            )

            """

        )



    def _snapshot_before_dup_cleanup(self, cursor) -> Optional[str]:

        """Take the pre-migration snapshot. One-shot: it is never overwritten.



        Two artefacts, both taken BEFORE anything is changed:



        * a versioned byte-level copy of the whole database next to it

          (``<db>.<migration-version>.snapshot.db``), produced by VACUUM INTO. It is

          a complete, restorable copy of the library as it was before the

          merge;

        * ``tracks_backup`` - a copy of the tracks table the corrective

          migration restores a retired row from. The one-shot guard is the

          table itself (CREATE TABLE IF NOT EXISTS): it is written once, so it

          cannot grow without bound.

        """

        snapshot_path: Optional[str] = None

        if self.db_path and self.db_path != ":memory:":

            # VACUUM INTO cannot run inside a transaction, and the schema

            # statements above may have opened one.

            try:

                self.conn.commit()

            except sqlite3.Error:

                pass

            snapshot_path = f"{self.db_path}.{self.DUP_CLEANUP_VERSION}.snapshot.db"

            try:

                if not os.path.isfile(snapshot_path):

                    self.conn.execute("VACUUM INTO ?", (snapshot_path,))

                if not os.path.isfile(snapshot_path) or os.path.getsize(snapshot_path) == 0:

                    raise sqlite3.DatabaseError("snapshot file is missing or empty")

                snapshot_conn = sqlite3.connect(snapshot_path)

                try:

                    check = snapshot_conn.execute("PRAGMA quick_check").fetchone()

                    has_tracks = snapshot_conn.execute(

                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tracks'"

                    ).fetchone()

                    if not check or check[0] != "ok" or not has_tracks:

                        raise sqlite3.DatabaseError("snapshot failed integrity validation")

                finally:

                    snapshot_conn.close()

            except (OSError, sqlite3.Error) as exc:

                logger.error(

                    "Dup cleanup: refusing to merge because file snapshot %s failed: %s",

                    snapshot_path, exc,

                )

                raise RuntimeError("duplicate cleanup snapshot failed") from exc



        try:

            with self.conn:

                backup_marker = cursor.execute(

                    "SELECT version FROM schema_migrations WHERE version = ?",

                    (self.DUP_CLEANUP_VERSION + '_snapshot',),

                ).fetchone()

                if not backup_marker:

                    # Keep the older repair source, then atomically replace the

                    # current one and its marker in the same SQLite transaction.

                    has_backup = cursor.execute(

                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tracks_backup'"

                    ).fetchone()

                    if has_backup:

                        cursor.execute(

                            "CREATE TABLE IF NOT EXISTS tracks_backup_previous AS "

                            "SELECT * FROM tracks_backup"

                        )

                    cursor.execute('DROP TABLE IF EXISTS tracks_backup')

                    cursor.execute('CREATE TABLE tracks_backup AS SELECT * FROM tracks')

                    cursor.execute(

                        'INSERT INTO schema_migrations(version,details) VALUES (?,?)',

                        (self.DUP_CLEANUP_VERSION + '_snapshot', '{}'),

                    )

        except sqlite3.Error as exc:

            logger.error(

                "Dup cleanup: refusing to merge because the table snapshot failed: %s", exc

            )

            raise RuntimeError("duplicate cleanup table snapshot failed") from exc



        return snapshot_path



    def _plan_track_merges(self, cursor) -> Tuple[List[Dict[str, Any]], int]:

        """Work out which rows may be collapsed into which. Read-only.



        The rows are grouped by TRACK_IDENTITY_SQL - the application's own

        track identity, the same key the creation path uses. Within a group the

        rows are partitioned by TRACK_RECORDING_COLUMNS, and only the rows of

        one partition (the same recording) may be collapsed into each other.

        A row that merely shares a title and an artist with another row is a

        different recording and is left exactly as it is.



        Returns the plan and the number of same-title rows that are left in

        place because they are different recordings.

        """

        cursor.execute(

            """

            SELECT LOWER(title) AS k_title, LOWER(artist) AS k_artist, COUNT(*) AS n

            FROM tracks

            WHERE title IS NOT NULL AND artist IS NOT NULL

            GROUP BY LOWER(title), LOWER(artist)

            HAVING n > 1

            """

        )

        plan: List[Dict[str, Any]] = []

        kept = 0

        for group in cursor.fetchall():

            cursor.execute(

                "SELECT * FROM tracks WHERE LOWER(title) = ? AND LOWER(artist) = ? ORDER BY id",

                (group["k_title"], group["k_artist"]),

            )

            members = [dict(row) for row in cursor.fetchall()]

            members = [m for m in members if name_is_meaningful(m.get("title"), m.get("artist"))]

            if len(members) < 2:

                continue



            partitions: Dict[tuple, List[dict]] = {}

            for member in members:

                key = tuple(member.get(column) for column in TRACK_RECORDING_COLUMNS)

                partitions.setdefault(key, []).append(member)



            for rows in partitions.values():

                if len(rows) < 2:

                    # A same-title row that is a different recording: left alone.

                    kept += 1

                    continue

                plan.append({

                    "survivor": rows[0],  # ORDER BY id -> the oldest row of the group

                    "duplicates": rows[1:],

                })

        return plan, kept



    def _apply_track_merges(self, cursor, plan: List[Dict[str, Any]]) -> Dict[str, int]:

        """Collapse the planned duplicates into their survivor."""

        stats = {

            "merged": 0,

            "survivors": 0,

            "history_moved": 0,

            "playlist_entries_moved": 0,

            "kept": 0,

        }

        # An old database may not have every column the merge writes (the

        # lufs columns are added by a later ALTER), so the columns are taken

        # from the table itself and not from a hard-coded list.

        columns = {

            row["name"] for row in cursor.execute("PRAGMA table_info(tracks)").fetchall()

        }

        for entry in plan:

            survivor = entry["survivor"]

            for duplicate in entry["duplicates"]:

                if self._merge_track_row_into(cursor, survivor, duplicate, stats, columns):

                    stats["merged"] += 1

            stats["survivors"] += 1

        return stats



    def _merge_track_row_into(

        self,

        cursor,

        survivor: dict,

        duplicate: dict,

        stats: Dict[str, int],

        columns: Optional[set] = None,

    ) -> bool:

        """Fold one duplicate row into the survivor and retire the duplicate.



        The duplicate is only ever retired after its history rows, playlist

        entries and download-queue rows have been re-pointed at the survivor,

        so no history row loses its track and no playlist loses an entry.

        """

        survivor_id = survivor["id"]

        duplicate_id = duplicate["id"]

        live = cursor.execute('SELECT * FROM tracks WHERE id = ?', (survivor_id,)).fetchone()

        if live is None:

            return False

        survivor = dict(live)

        if columns is None:

            columns = {

                row["name"] for row in cursor.execute("PRAGMA table_info(tracks)").fetchall()

            }



        # 1. the payload moves into the survivor

        updates: Dict[str, Any] = {}

        for column in DUP_CARRY_OVER_COLUMNS:

            if column not in columns:

                continue

            if _is_empty_value(survivor.get(column)) and not _is_empty_value(duplicate.get(column)):

                updates[column] = duplicate.get(column)



        assignments = []

        params: List[Any] = []

        for column, value in updates.items():

            assignments.append(f"{column} = ?")

            params.append(value)

        if "play_count" in columns:

            assignments.append("play_count = ?")

            params.append((survivor.get("play_count") or 0) + (duplicate.get("play_count") or 0))

        if "is_favorite" in columns:

            assignments.append("is_favorite = ?")

            params.append(1 if (survivor.get("is_favorite") or duplicate.get("is_favorite")) else 0)

        if "last_played" in columns:

            assignments.append("last_played = ?")

            params.append(_latest_timestamp(survivor.get("last_played"), duplicate.get("last_played")))

        if not assignments:

            logger.warning(

                "Dup cleanup: track %d was not merged - the tracks table has none of the "

                "expected columns.", duplicate_id,

            )

            return False

        params.append(survivor_id)

        cursor.execute(

            "UPDATE tracks SET {} WHERE id = ?".format(", ".join(assignments)), params

        )



        # 2. the history rows follow the survivor

        cursor.execute(

            "INSERT OR REPLACE INTO history_track_remap (history_id, original_track_id) "

            "SELECT id, ? FROM history WHERE track_id = ?",

            (duplicate_id, duplicate_id),

        )

        cursor.execute("UPDATE history SET track_id = ? WHERE track_id = ?", (survivor_id, duplicate_id))

        stats["history_moved"] += max(cursor.rowcount, 0)



        # 3. the playlist entries follow the survivor

        cursor.execute(

            "INSERT OR REPLACE INTO playlist_tracks_track_remap (playlist_tracks_id, original_track_id) "

            "SELECT id, ? FROM playlist_tracks WHERE track_id = ?",

            (duplicate_id, duplicate_id),

        )

        cursor.execute(

            "UPDATE playlist_tracks SET track_id = ? WHERE track_id = ?", (survivor_id, duplicate_id)

        )

        stats["playlist_entries_moved"] += max(cursor.rowcount, 0)



        # 4. the download queue follows the survivor too

        cursor.execute("SELECT id FROM download_queue WHERE track_id = ?", (duplicate_id,))

        for queue_row in cursor.fetchall():

            taken = cursor.execute(

                "SELECT id FROM download_queue WHERE track_id = ?", (survivor_id,)

            ).fetchone()

            if taken:

                cursor.execute("DELETE FROM download_queue WHERE id = ?", (queue_row["id"],))

            else:

                cursor.execute(

                    "UPDATE download_queue SET track_id = ? WHERE id = ?", (survivor_id, queue_row["id"])

                )



        # 5. the duplicate row itself - it is empty now: its payload is in the

        #    survivor, its history and its playlist entries point at the survivor

        cursor.execute("DELETE FROM tracks WHERE id = ?", (duplicate_id,))

        cursor.execute(

            "INSERT OR REPLACE INTO track_merges (duplicate_id, survivor_id, merged_by, merged_at) "

            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",

            (duplicate_id, survivor_id, self.DUP_CLEANUP_VERSION),

        )

        return True



    def _remove_exact_duplicate_playlist_entries(self, cursor) -> int:

        """Keep one entry per (playlist, track) pair.



        The same track listed twice in one playlist is a redundancy, not a loss:

        one of the two entries goes, the track stays in the playlist. The old

        second statement went further and removed entries by a playlist-local

        MIN(id) rule over (LOWER(title), LOWER(artist)), which could strip the

        entry of a track that SURVIVED the migration - that statement is gone.

        """

        cursor.execute(

            """

            DELETE FROM playlist_tracks

            WHERE id NOT IN (

                SELECT MIN(id) FROM playlist_tracks GROUP BY playlist_id, track_id

            )

            """

        )

        return max(cursor.rowcount, 0)



    def _restore_merged_tracks(self, cursor) -> int:

        """Re-insert the rows a PREVIOUS merge migration retired.



        Only the rows the merge log names are candidates, so a track the user

        deleted after the migration ran is never resurrected. The data comes

        from the snapshot table the merge took before it changed anything.

        """

        tables = {

            row["name"]

            for row in cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()

        }

        if not {"tracks_backup", "track_merges"} <= tables:

            return 0



        cursor.execute(

            "SELECT duplicate_id, survivor_id FROM track_merges "

            "WHERE merged_by <> ? AND duplicate_id NOT IN (SELECT id FROM tracks)",

            (self.DUP_CLEANUP_VERSION,),

        )

        candidates = cursor.fetchall()

        if not candidates:

            return 0



        backup_columns = [

            row["name"] for row in cursor.execute("PRAGMA table_info(tracks_backup)").fetchall()

        ]

        live_columns = [

            row["name"] for row in cursor.execute("PRAGMA table_info(tracks)").fetchall()

        ]

        columns = [name for name in live_columns if name in backup_columns]

        if not columns:

            return 0

        column_list = ", ".join(columns)



        restored = 0

        for candidate in candidates:

            duplicate_id = candidate["duplicate_id"]

            survivor_id = candidate["survivor_id"]

            cursor.execute(

                "INSERT OR IGNORE INTO tracks ({cols}) SELECT {cols} FROM tracks_backup WHERE id = ?".format(

                    cols=column_list

                ),

                (duplicate_id,),

            )

            if not cursor.rowcount:

                continue

            restored += 1

            # the play count the merge folded into the survivor goes back

            cursor.execute(

                "UPDATE tracks SET play_count = MAX(play_count - "

                "(SELECT COALESCE(play_count, 0) FROM tracks_backup WHERE id = ?), 0) WHERE id = ?",

                (duplicate_id, survivor_id),

            )

            cursor.execute('UPDATE tracks SET play_count=MAX(COALESCE(play_count,0),COALESCE((SELECT play_count FROM tracks_backup WHERE id=?),0)) WHERE id=?', (survivor_id, survivor_id))

            if "history_track_remap" in tables:

                cursor.execute(

                    "UPDATE history SET track_id = ? WHERE id IN "

                    "(SELECT history_id FROM history_track_remap WHERE original_track_id = ?)",

                    (duplicate_id, duplicate_id),

                )

            if "playlist_tracks_track_remap" in tables:

                cursor.execute(

                    "UPDATE playlist_tracks SET track_id = ? WHERE id IN "

                    "(SELECT playlist_tracks_id FROM playlist_tracks_track_remap WHERE original_track_id = ?)",

                    (duplicate_id, duplicate_id),

                )

        return restored



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

        with self._write_lock:

            conn = self.conn

            with conn:

                cursor = conn.cursor()



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

                        return t_id



                if file_path:

                    cursor.execute("SELECT id FROM tracks WHERE file_path = ?", (file_path,))

                    row = cursor.fetchone()

                    if row:

                        return row["id"]



                # Only dedupe by name when the name actually identifies the

                # track. The old guard compared against "Unknown", but the real

                # placeholder is "Unknown Title" -- so every placeholder track

                # matched every other one and a 33-track playlist import

                # collapsed onto a single row. Placeholder names carry no

                # identity, so fall through to INSERT; for non-local sources

                # the source/source_id check above already handles repeats.

                #

                # The key itself is TRACK_IDENTITY_SQL - the SAME expression the

                # de-duplication migration groups by, so the creation path and

                # the migration can never disagree about what "the same track"

                # is (P0-01).

                if name_is_meaningful(title, artist) and not (source == 'local' and file_path):

                    cursor.execute(

                        "SELECT id, cover_url, file_path FROM tracks WHERE " + TRACK_IDENTITY_SQL,

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

        if limit is not None:

            sql += " LIMIT ? OFFSET ?"

            params.extend([max(0, int(limit)), max(0, int(offset))])

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



    def get_favorite_tracks(self, limit=None) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        query = "SELECT * FROM tracks WHERE is_favorite = 1 ORDER BY added_at DESC"
        if limit is None:
            cursor.execute(query)
        else:
            cursor.execute(query + " LIMIT ?", (max(1,min(500,int(limit))),))

        return [dict(row) for row in cursor.fetchall()]



    def get_most_played_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:

        return self.get_most_played(limit)



    def get_recently_added_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM tracks ORDER BY added_at DESC LIMIT ?", (limit,))

        return [dict(row) for row in cursor.fetchall()]



    def get_user_history_tracks(self, limit: int = 10) -> List[Dict[str, Any]]:

        return self.get_history(limit)



    def toggle_favorite(self, track_id: int) -> bool:

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute("SELECT is_favorite FROM tracks WHERE id = ?", (track_id,))

                row = cursor.fetchone()

                if not row:

                    return False

                new_val = 0 if row["is_favorite"] else 1

                cursor.execute("UPDATE tracks SET is_favorite = ? WHERE id = ?", (new_val, track_id))

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

        if not isinstance(track_id, int) or isinstance(track_id, bool) or track_id <= 0:

            raise ValueError("track_id must be a positive integer")

        if not isinstance(file_path, str) or not file_path.strip():

            raise ValueError("file_path must be a non-empty path")

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                owner = cursor.execute(

                    "SELECT id FROM tracks WHERE file_path = ? AND id != ? LIMIT 1",

                    (file_path, track_id),

                ).fetchone()

                if owner:

                    raise ValueError(f"Downloaded file is already assigned to track {owner['id']}")

                cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))

                if cursor.rowcount != 1:

                    raise LookupError(f"Track {track_id} is no longer in the library")



    def clear_download_state(self, track_id: int) -> None:

        with self._write_lock, self.conn:

            self.conn.execute('UPDATE tracks SET is_downloaded=0, is_cached=0, file_path=NULL WHERE id=?', (track_id,))

            self.conn.execute('DELETE FROM download_queue WHERE track_id=?', (track_id,))



    def merge_duplicate_track(self, duplicate_id: int, keeper_id: int) -> bool:

        if int(duplicate_id) == int(keeper_id):

            return False

        with self._write_lock, self.conn:

            keeper, duplicate = self.get_track(keeper_id), self.get_track(duplicate_id)

            if not keeper or not duplicate:

                return False

            self._ensure_migration_tables(self.conn.cursor())

            return self._merge_track_row_into(self.conn.cursor(), keeper, duplicate,

                {'history_moved': 0, 'playlist_entries_moved': 0})



    def get_library_page(self, limit=200, offset=0, source=None):

        fields = 'id,title,artist,album,duration,file_path,source,source_id,source_url,cover_path,cover_url,genre,year,added_at,last_played,play_count,is_favorite,is_downloaded,is_cached,loudness_lufs,format'

        where, values = (' WHERE source=?', [source]) if source else ('', [])

        return [dict(row) for row in self.conn.execute(

            f'SELECT {fields} FROM tracks{where} ORDER BY {DEFAULT_TRACK_ORDER_BY} LIMIT ? OFFSET ?',

            (*values, max(1, min(int(limit), 1000)), max(0, int(offset))))]



    def get_downloaded_tracks(self) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM tracks WHERE is_downloaded = 1 ORDER BY added_at DESC")

        return [dict(row) for row in cursor.fetchall()]



    def log_listening_history(self, track_id: int, duration_listened: float = 0, completed: bool = False) -> int:

        with self._write_lock:

            with self.conn:

                return self._log_listening_locked(

                    self.conn.cursor(), track_id, duration_listened, completed

                )



    def _log_listening_locked(self, cursor, track_id: int, duration_listened: float = 0, completed: bool = False) -> int:

        """Body of log_listening_history for an already-open transaction.



        The caller owns ``_write_lock`` and the ``with self.conn:`` block.

        """

        if duration_listened <= 0:

            cursor.execute("SELECT duration FROM tracks WHERE id = ?", (track_id,))

            t_row = cursor.fetchone()

            if t_row and t_row[0] and float(t_row[0]) > 0:

                duration_listened = float(t_row[0])

            else:

                # Unknown length: record an honest 0 instead of a fabricated

                # three-minute listen that skewed total-time statistics.

                duration_listened = 0.0

        cursor.execute(

            "INSERT INTO history (track_id, duration_listened, completed) VALUES (?, ?, ?)",

            (track_id, duration_listened, 1 if completed else 0),

        )

        cursor.execute(

            "UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?",

            (track_id,),

        )

        return cursor.lastrowid



    def record_listening_once(self, track_id: int, dedup_key: str) -> bool:

        """DEPRECATED and unused - do not reintroduce.



        It claimed ``listen_dedup:<dedup_key>`` as a row in `settings` to make

        the history write idempotent. With the key being the *track* id that

        made every track count as played exactly once for the lifetime of the

        library (play_count, history and the Wrapped statistics froze after the

        first play), and it grew `settings` by one row per track played, all of

        them scanned by get_all_settings() at startup.



        Playback deduplication belongs to the caller and stays process-local:

        AppApi.maybe_log_history() keeps _history_logged_key under

        _window_op_lock and resets it when the track changes or playback stops.

        """

        raise NotImplementedError(

            "record_listening_once was removed: persistent per-track dedup "

            "broke play counting. Use AppApi.maybe_log_history() / "

            "log_listening_history()."

        )



    def update_track_play(self, track_id: int) -> None:

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute(

                    "UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?",

                    (track_id,),

                )



    @staticmethod

    def _like_pattern(query: str) -> str:

        """Build a LIKE pattern whose wildcards are literal.



        Without this the user owns the wildcards: "AC_DC" matched every

        "AC/DC" row and "100%" matched the whole library. The backslash is the

        escape character, so every query using this pattern must declare

        ``ESCAPE '\\'``.

        """

        escaped = (

            str(query if query is not None else "")

            .replace("\\", "\\\\")

            .replace("%", "\\%")

            .replace("_", "\\_")

        )

        return f"%{escaped}%"



    def search_tracks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        # O-10: FTS5 first, LIKE fallback

        query_words = query.split()

        # FTS tokenizes punctuation, so AC_DC and AC/DC become the same token

        # phrase. Use the escaped LIKE path for punctuation-bearing input to

        # preserve the literal query characters instead of returning aliases.

        if (getattr(self, "_fts_available", False) and query.strip()

                and all(word.isalnum() for word in query_words)):

            try:

                # Prefix-match each word, escaped for FTS5 quoted strings

                terms = " ".join(

                    '"' + w.replace('"', '""') + '"*'

                    for w in query_words

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

        like_query = self._like_pattern(query)

        folded_like = _unicode_casefold_str(like_query)

        cursor.execute(

            """

            SELECT * FROM tracks

            WHERE unicode_casefold(title) LIKE ? ESCAPE '\\'

               OR unicode_casefold(artist) LIKE ? ESCAPE '\\'

               OR unicode_casefold(album) LIKE ? ESCAPE '\\'

            ORDER BY play_count DESC

            LIMIT ?

        """,

            (folded_like, folded_like, folded_like, limit),

        )

        return [dict(row) for row in cursor.fetchall()]



    def search_artists(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        query_words = query.split()

        if (getattr(self, "_fts_available", False) and query.strip()

                and all(word.isalnum() for word in query_words)):

            try:

                terms = " ".join('artist : "' + w.replace('"', '""') + '"*' for w in query_words if w)

                if terms:

                    cursor.execute(

                        """

                        SELECT t.artist, COUNT(*) as track_count, SUM(t.play_count) as total_plays,

                               SUM(t.play_count) as play_count, SUM(t.play_count) as plays

                        FROM tracks_fts f JOIN tracks t ON t.id = f.rowid

                        WHERE tracks_fts MATCH ?

                        GROUP BY unicode_casefold(t.artist)

                        ORDER BY total_plays DESC

                        LIMIT ?

                    """,

                        (terms, limit),

                    )

                    rows = cursor.fetchall()

                    if rows:

                        return [dict(row) for row in rows]

            except Exception:

                pass

        like_query = self._like_pattern(query)

        folded_like = _unicode_casefold_str(like_query)

        cursor.execute(

            """

            SELECT artist, COUNT(*) as track_count, SUM(play_count) as total_plays, SUM(play_count) as play_count, SUM(play_count) as plays

            FROM tracks

            WHERE unicode_casefold(artist) LIKE ? ESCAPE '\\'

            GROUP BY unicode_casefold(artist)

            ORDER BY total_plays DESC

            LIMIT ?

        """,

            (folded_like, limit),

        )

        return [dict(row) for row in cursor.fetchall()]



    def search_albums(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        query_words = query.split()

        if (getattr(self, "_fts_available", False) and query.strip()

                and all(word.isalnum() for word in query_words)):

            try:

                terms = " ".join('{album artist} : "' + w.replace('"', '""') + '"*' for w in query_words if w)

                if terms:

                    cursor.execute(

                        """

                        SELECT t.album as title, t.artist, t.cover_path, t.cover_url, COUNT(t.id) as track_count,

                               MAX(t.year) as year, 'local' as source, 'album' as type

                        FROM tracks_fts f JOIN tracks t ON t.id = f.rowid

                        WHERE tracks_fts MATCH ?

                          AND t.album IS NOT NULL AND t.album != '' AND t.album != 'Unknown Album'

                        GROUP BY unicode_casefold(t.album), unicode_casefold(t.artist)

                        ORDER BY track_count DESC

                        LIMIT ?

                    """,

                        (terms, limit),

                    )

                    rows = cursor.fetchall()

                    if rows:

                        return [dict(row) for row in rows]

            except Exception:

                pass

        like_query = self._like_pattern(query)

        folded_like = _unicode_casefold_str(like_query)

        cursor.execute(

            """

            SELECT album as title, artist, cover_path, cover_url, COUNT(id) as track_count, MAX(year) as year, 'local' as source, 'album' as type

            FROM tracks

            WHERE (unicode_casefold(album) LIKE ? ESCAPE '\\' OR unicode_casefold(artist) LIKE ? ESCAPE '\\')

              AND album IS NOT NULL AND album != '' AND album != 'Unknown Album'

            GROUP BY unicode_casefold(album), unicode_casefold(artist)

            ORDER BY track_count DESC

            LIMIT ?

        """,

            (folded_like, folded_like, limit),

        )

        return [dict(row) for row in cursor.fetchall()]



    def get_playlist_track_count(self, playlist_id: int) -> int:

        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?", (int(playlist_id),))

        row = cursor.fetchone()

        return row[0] if row else 0



    def search_playlists(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        pattern = self._like_pattern(query.strip())

        try:

            cursor.execute("SELECT p.id, p.name, p.description, p.created_at, p.cover_url, COUNT(pt.track_id) AS track_count FROM playlists p LEFT JOIN playlist_tracks pt ON p.id=pt.playlist_id WHERE p.name LIKE ? ESCAPE '\\' GROUP BY p.id ORDER BY p.name ASC LIMIT ?", (pattern, limit))

        except Exception:

            cursor.execute("SELECT id, name, description, created_at, cover_path as cover_url FROM playlists WHERE name LIKE ? ESCAPE '\\' ORDER BY name ASC LIMIT ?", (pattern, limit))

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

                "track_count": dict(r).get('track_count', 0),

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

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))

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

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute(f"UPDATE tracks SET {', '.join(set_clauses)} WHERE id = ?", params)

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



            with self._write_lock:

                with self.conn:

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

                    return True

        except Exception as e:

            logger.error(f"Error in update_track_metadata for track {track_id}: {e}")

            return False





    def add_to_history(self, track_id: int, duration_listened: float = 0, completed: bool = False) -> int:

        return self.log_listening_history(track_id, duration_listened, completed)



    def begin_listening_session(self, track_id: int, recommendation_context: str = '') -> int:

        """An actual playback start has zero measured duration, never a full song."""

        context = recommendation_context if recommendation_context in ('feed', 'mix', 'wave', 'flow', 'artist') else ''

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute('INSERT INTO history (track_id, duration_listened, completed, listening_measured, recommendation_context) VALUES (?, 0, 0, 1, ?)',

                               (track_id, context))

                cursor.execute('UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = ?', (track_id,))

                return cursor.lastrowid



    def get_recommendation_quality(self, days: int = 30) -> dict:

        """Local observed outcomes, grouped by recommendation entry point."""

        days = max(1, min(365, int(days)))

        rows = self.conn.execute('''

            SELECT h.recommendation_context AS context, COUNT(*) AS starts,

                   SUM(h.completed) AS completions,

                   SUM(CASE WHEN h.listening_measured = 1 AND h.session_finished = 1 AND h.completed = 0

                             AND h.duration_listened < 10 AND t.duration > 0

                             AND COALESCE(NULLIF(h.media_listened, 0), h.duration_listened) < t.duration * 0.1 THEN 1 ELSE 0 END) AS skips,

                   ROUND(SUM(h.duration_listened), 2) AS listened_seconds,

                   COUNT(DISTINCT CASE WHEN t.is_favorite = 1 THEN t.id END) AS currently_liked_tracks

            FROM history h JOIN tracks t ON t.id = h.track_id

            WHERE h.recommendation_context != '' AND h.played_at >= datetime('now', ?)

            GROUP BY h.recommendation_context

        ''', (f'-{days} days',)).fetchall()

        return {'days': days, 'groups': [dict(row) for row in rows]}



    def update_history_duration(self, history_id: int, duration_sec: float, completed: bool = False, media_listened=None, session_finished=False) -> None:

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                if media_listened is not None:

                    cursor.execute('UPDATE history SET duration_listened=?, completed=?, media_listened=?, session_finished=? WHERE id=?',

                                   (duration_sec, int(bool(completed)), media_listened, int(bool(session_finished)), history_id))

                    return

                cursor.execute(

                    "UPDATE history SET duration_listened = ?, completed = ? WHERE id = ?",

                    (duration_sec, 1 if completed else 0, history_id),

                )



    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:

        """Recently played tracks, one entry per track.



        Aggregate only the newest HISTORY_EVENT_WINDOW events, then return at

        most HISTORY_RESULT_LIMIT tracks. Counts and listened duration in these

        feed rows describe that bounded recent window, not lifetime totals.

        """

        try:

            result_limit = max(0, min(int(limit), HISTORY_RESULT_LIMIT))

        except (TypeError, ValueError, OverflowError):

            result_limit = 50

        if result_limit == 0:

            return []



        cursor = self.conn.cursor()

        cursor.execute(

            """

            WITH recent AS (

                SELECT id, track_id, played_at, duration_listened, completed,

                       listening_measured, media_listened, session_finished

                FROM history

                ORDER BY played_at DESC, id DESC

                LIMIT ?

            ), ranked AS (

                SELECT recent.*,

                       ROW_NUMBER() OVER (

                           PARTITION BY track_id ORDER BY played_at DESC, id DESC

                       ) AS rn

                FROM recent

            )

            SELECT t.id AS id, t.id AS track_id,

                   MAX(r.played_at) AS played_at,

                   COUNT(*) AS play_count,

                   COALESCE(SUM(r.duration_listened), 0) AS duration_listened,

                   t.title, t.artist, t.album, t.cover_path, t.cover_url,

                   t.duration, t.file_path, t.is_favorite, t.is_downloaded,

                   t.source, t.source_id, t.source_url,

                   MAX(CASE WHEN r.rn = 1 THEN r.duration_listened END) AS latest_duration_listened,

                   MAX(CASE WHEN r.rn = 1 THEN r.completed END) AS completed,

                   MAX(CASE WHEN r.rn = 1 THEN r.listening_measured END) AS listening_measured,

                   MAX(CASE WHEN r.rn = 1 THEN r.media_listened END) AS media_listened,

                   MAX(CASE WHEN r.rn = 1 THEN r.session_finished END) AS session_finished

            FROM ranked r

            JOIN tracks t ON r.track_id = t.id

            GROUP BY t.id

            ORDER BY MAX(r.played_at) DESC,

                     MAX(CASE WHEN r.rn = 1 THEN r.id END) DESC

            LIMIT ?

        """,

            (HISTORY_EVENT_WINDOW, result_limit),

        )

        return [dict(row) for row in cursor.fetchall()]



    def clear_listening_history(self):

        with self._write_lock, self.conn:

            self.conn.execute('DELETE FROM history')

            self.conn.execute('DELETE FROM listening_stats')

            self.conn.execute('UPDATE tracks SET play_count=0,last_played=NULL')

        return True



    def prune_history(self, retention_days=None):

        """Explicit opt-in retention; never discard the user's history by default."""

        if retention_days is None:

            return 0

        days = max(1, int(retention_days))

        with self._write_lock, self.conn:

            return self.conn.execute("DELETE FROM history WHERE played_at < datetime('now',?)", (f'-{days} days',)).rowcount



    def get_tracks_missing_cover(self, limit: int = 40, before_id=None) -> List[Dict[str, Any]]:

        """Rows whose artwork (or real title/artist) is still missing.



        A row qualifies when EITHER it has no artwork at all (neither cover_path

        nor cover_url) OR it still carries the 'Unknown Title' / 'Unknown

        Artist' placeholders written when metadata extraction failed. These are

        deliberately separate OR'd branches: gating the placeholder branch on

        cover_path IS NULL hid exactly the rows that need fixing, because

        backfill_track_metadata() repairs the placeholder names whether or not

        artwork was already stored. A row with artwork AND real names is

        skipped, otherwise it would be re-resolved on every pass forever

        (backfill writes cover_url, never cover_path).

        """

        cursor = self.conn.cursor()

        cursor.execute(

            """

            SELECT id, source, source_id FROM tracks

            WHERE (

                    (cover_path IS NULL AND (cover_url IS NULL OR cover_url = ''))

                 OR title IS NULL OR title IN ('', 'Unknown', 'Unknown Title')

                 OR artist IS NULL OR artist IN ('', 'Unknown', 'Unknown Artist')

              )

              AND source IS NOT NULL AND source != 'local'

              AND source_id IS NOT NULL AND source_id != ''

              AND id < ?

            ORDER BY id DESC

            LIMIT ?

            """,

            (int(before_id) if before_id else 9223372036854775807, max(0,min(200,int(limit)))),

        )

        return [dict(row) for row in cursor.fetchall()]



    def set_track_cover(self, track_id: int, cover_url: str) -> None:

        with self._write_lock:

            with self.conn:

                self.conn.execute(

                    "UPDATE tracks SET cover_url = ? WHERE id = ?",

                    (cover_url, track_id),

                )



    def backfill_track_metadata(self, track_id: int, cover_url: str,

                                title: str = "", artist: str = "") -> None:

        """Store artwork, and repair placeholder title/artist with real values.



        Provider metadata arrives as the raw video title and the channel name

        ("Artist - Topic"), so it is NEVER written over genuine values

        unconditionally (BUG-S4-003). The current row values are read first:



        * a literal placeholder ('Unknown Title' / 'Unknown Artist') is the

          backfill's legitimate target and is replaced by the provider value -

          the raw title is parsed through music_matching.title_metadata, which

          strips "(Official Video)"-style decorations and lifts an embedded

          "Artist - " credit out of the title, and the channel name has its

          "- Topic" / "VEVO" artifacts stripped;

        * a genuine value is only replaced by a near-identical cosmetic variant

          of the same record (canonical similarity >= 0.85) - which means the

          honest "no opinion" outcome for rows selected merely because they

          lack artwork.

        """

        placeholders = {"", "unknown", "unknown title", "unknown artist",

                        "unknown album", "none", "null", "неизвестный трек"}

        new_title = str(title or '').strip()

        new_artist = _clean_channel_artist(artist)



        with self._write_lock:

            with self.conn:

                row = self.conn.execute(

                    "SELECT title, artist FROM tracks WHERE id = ?", (track_id,)

                ).fetchone()

                if row is None:

                    return

                current_title = str(row['title'] or '').strip()

                current_artist = str(row['artist'] or '').strip()



                # Placeholder targets: parse the raw video title so decorations

                # and embedded credits do not become library data. Genuine

                # values are compared against the provider values as-is.

                parsed = None

                if (new_title and re.search(r'[\[(]|[-–—]', new_title)

                        and (_is_placeholder_name(current_title)

                             or _is_placeholder_name(current_artist))):

                    try:

                        parsed = music_matching.title_metadata(new_title, '')

                    except Exception:

                        parsed = None



                if (_is_placeholder_name(current_title) and parsed

                        and str(parsed.get('title') or '').strip()):

                    new_title = str(parsed['title']).strip()



                if _is_placeholder_name(current_artist):

                    extracted = [str(a).strip() for a in (parsed.get('artists') or [])

                                 if str(a).strip()] if parsed else []

                    if extracted:

                        extracted_str = ', '.join(extracted)

                        if not new_artist:

                            new_artist = extracted_str

                        elif not music_matching.artist_matches(extracted, new_artist):

                            # The channel that uploaded the video is not among

                            # the title's credits: a re-uploader channel name

                            # must not become the artist of the row.

                            new_artist = extracted_str

                    if new_artist and new_artist.lower() in placeholders:

                        new_artist = ''



                sets, args = [], []

                if cover_url:

                    sets.append("cover_url = ?")

                    args.append(cover_url)

                if (new_title and new_title.lower() not in placeholders

                        and self._may_replace_metadata_value(

                            current_title, new_title)):

                    sets.append("title = ?")

                    args.append(new_title)

                if (new_artist and new_artist.lower() not in placeholders

                        and self._may_replace_metadata_value(

                            current_artist, new_artist)):

                    sets.append("artist = ?")

                    args.append(new_artist)

                if not sets:

                    return

                args.append(track_id)

                self.conn.execute(

                    f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", args

                )



    @staticmethod

    def _may_replace_metadata_value(current: str, new: str,

                                    min_similarity: float = 0.85) -> bool:

        """Guard for one metadata value (title/artist) during backfill.



        A placeholder is always replaceable. A genuine value only gives way to

        a cosmetic variant of itself (differing case/punctuation, a stray

        "(Official Video)" remnant); a different name never wins.

        """

        if _is_placeholder_name(current):

            return True

        try:

            return music_matching.similarity(current, new) >= min_similarity

        except Exception:

            return False



    # ------------------------------------------------------------------

    # Manual repair for libraries already damaged by the pre-S4-003 backfill

    # ------------------------------------------------------------------

    #

    # Older builds overwrote genuine title/artist values with the raw video

    # title and the channel name ("Artist - Topic"). The damage is

    # characterisable: the corrupted artist is a channel artifact. This repair

    # is deliberate and user-invoked - never run automatically at startup -

    # and every touched row is backed up for rollback.



    METADATA_REPAIRS_BACKUP_TABLE = "metadata_repairs_backup"



    def _ensure_metadata_repairs_backup_table(self, cursor) -> None:

        cursor.execute(

            f"""

            CREATE TABLE IF NOT EXISTS {self.METADATA_REPAIRS_BACKUP_TABLE} (

                track_id INTEGER PRIMARY KEY,

                old_title TEXT,

                old_artist TEXT,

                new_title TEXT,

                new_artist TEXT,

                repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )

        """

        )



    def _detect_channel_corrupted_rows(self, cursor) -> list:

        """Rows whose artist is a YouTube-channel artifact ('Artist - Topic').



        Only the unambiguous channel markers are repaired; a channel that is a

        plain real-looking name without a suffix cannot be told apart from a

        genuine artist and is left alone.

        """

        rows = cursor.execute(

            """

            SELECT id, title, artist FROM tracks

            WHERE artist IS NOT NULL

              AND (

                    artist LIKE '%- topic'

                 OR artist LIKE '%- Topic'

                 OR artist LIKE '%VEVO'

                 OR artist LIKE '%- Official'

              )

            ORDER BY id

            """

        ).fetchall()

        detected = []

        for row in rows:

            cleaned = _clean_channel_artist(row['artist'])

            if cleaned and cleaned != str(row['artist']).strip():

                detected.append({

                    'id': int(row['id']),

                    'title': str(row['title'] or ''),

                    'artist': str(row['artist'] or ''),

                    'clean_artist': cleaned,

                })

        return detected



    @staticmethod

    def _clean_corrupted_title(title: str) -> str:

        """Peel presentation decorations off a raw video title."""

        cleaned = str(title or '')

        try:

            parsed = music_matching.title_metadata(cleaned, '')

        except Exception:

            parsed = None

        if parsed and str(parsed.get('title') or '').strip():

            cleaned = str(parsed['title']).strip()

        return ' '.join(cleaned.split())



    def repair_channel_corrupted_metadata(self) -> Dict[str, Any]:

        """Detect and repair rows corrupted by the old cover backfill.



        Returns a summary dict; every repaired row is first copied into

        ``metadata_repairs_backup`` so ``rollback_channel_corrupted_metadata``

        can undo the repair. Runs in one transaction: a failure leaves the

        library untouched.

        """

        repaired = 0

        detected = []

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                self._ensure_metadata_repairs_backup_table(cursor)

                detected = self._detect_channel_corrupted_rows(cursor)

                for row in detected:

                    new_artist = row['clean_artist']

                    new_title = self._clean_corrupted_title(row['title'])

                    if (new_artist == str(row['artist']).strip()

                            and new_title == str(row['title']).strip()):

                        continue

                    cursor.execute(

                        f"INSERT OR REPLACE INTO {self.METADATA_REPAIRS_BACKUP_TABLE} "

                        "(track_id, old_title, old_artist, new_title, new_artist) "

                        "VALUES (?, ?, ?, ?, ?)",

                        (row['id'], row['title'], row['artist'],

                         new_title or row['title'], new_artist or row['artist']),

                    )

                    cursor.execute(

                        "UPDATE tracks SET title = ?, artist = ? WHERE id = ?",

                        (new_title or row['title'], new_artist or row['artist'],

                         row['id']),

                    )

                    repaired += 1

        if repaired:

            logger.warning(

                "Metadata repair: %d channel-corrupted row(s) repaired; rollback "

                "available via rollback_channel_corrupted_metadata()",

                repaired,

            )

        return {'repaired': repaired, 'detected': detected}



    def rollback_channel_corrupted_metadata(self) -> Dict[str, Any]:

        """Undo repair_channel_corrupted_metadata for rows unchanged since.



        A row whose title/artist no longer equal the repair's ``new`` values

        was edited afterwards and is left alone. Successfully restored backup

        rows are removed from the backup table.

        """

        restored, skipped = 0, 0

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                try:

                    rows = cursor.execute(

                        f"SELECT track_id, old_title, old_artist, new_title, new_artist "

                        f"FROM {self.METADATA_REPAIRS_BACKUP_TABLE}"

                    ).fetchall()

                except sqlite3.OperationalError:

                    return {'restored': 0, 'skipped': 0}

                for row in rows:

                    current = cursor.execute(

                        "SELECT title, artist FROM tracks WHERE id = ?",

                        (row['track_id'],),

                    ).fetchone()

                    if current is None:

                        skipped += 1

                        continue

                    same_title = str(current['title'] or '') == str(row['new_title'] or '')

                    same_artist = str(current['artist'] or '') == str(row['new_artist'] or '')

                    if same_title and same_artist:

                        cursor.execute(

                            "UPDATE tracks SET title = ?, artist = ? WHERE id = ?",

                            (row['old_title'], row['old_artist'], row['track_id']),

                        )

                        cursor.execute(

                            f"DELETE FROM {self.METADATA_REPAIRS_BACKUP_TABLE} WHERE track_id = ?",

                            (row['track_id'],),

                        )

                        restored += 1

                    else:

                        skipped += 1

        return {'restored': restored, 'skipped': skipped}



    def get_most_played(self, limit: int = 10) -> List[Dict[str, Any]]:

        limit = max(0, min(200, int(limit)))

        cursor = self.conn.cursor()

        cursor.execute(

            """

            SELECT * FROM tracks 

            WHERE play_count > 0

            ORDER BY play_count DESC, last_played DESC, id DESC

            LIMIT ?

        """,

            (limit,),

        )

        return [dict(row) for row in cursor.fetchall()]



    def get_top_artists(self, limit: int = 10) -> List[Dict[str, Any]]:

        limit = max(0, min(200, int(limit)))

        cursor = self.conn.cursor()

        cursor.execute(

            """

            SELECT MIN(artist) AS artist, MIN(artist) AS name,

                   COUNT(*) as track_count, SUM(play_count) as total_plays,

                   SUM(play_count) as play_count, SUM(play_count) as plays

            FROM tracks

            WHERE artist IS NOT NULL AND TRIM(artist) != ''

                  AND LOWER(artist) != 'unknown artist' AND play_count > 0

            GROUP BY unicode_casefold(artist_primary(artist))

            ORDER BY total_plays DESC, name

            LIMIT ?

        """,

            (limit,),

        )

        return [dict(row) for row in cursor.fetchall()]



    def get_wrapped_stats(self, period: str = "week") -> Dict[str, Any]:

        """Materialise the selected history once; preserve measured zeroes."""

        days = {'week': 7, 'month': 30, 'year': 365}.get(period)

        where = "WHERE h.played_at >= datetime('now', ?)" if days else ''

        parameters = (f'-{days} days',) if days else ()

        query = f"""

            WITH events AS MATERIALIZED (

                SELECT h.*, t.title, t.artist, t.album, t.cover_path, t.cover_url, t.source, t.source_id,

                       COALESCE(h.duration_listened, 0) AS listened

                FROM history h JOIN tracks t ON t.id=h.track_id {where}

            ), tracks_ranked AS (

                SELECT track_id AS id,title,artist,album,cover_path,cover_url,source,source_id,

                       COUNT(*) AS plays,SUM(listened) AS total_listened_sec

                FROM events GROUP BY track_id ORDER BY plays DESC,total_listened_sec DESC LIMIT 5

            ), artists_ranked AS (

                SELECT artist_primary(artist) AS artist,COUNT(*) AS plays,SUM(listened) AS total_listened_sec

                FROM events WHERE artist IS NOT NULL AND artist NOT IN ('','Unknown Artist')

                GROUP BY unicode_casefold(artist_primary(artist)) ORDER BY plays DESC,total_listened_sec DESC LIMIT 5

            ), activity AS (

                SELECT strftime('%w',played_at) AS day_idx,COUNT(*) AS plays,SUM(listened)/60.0 AS minutes

                FROM events GROUP BY day_idx

            )

            SELECT COUNT(*) AS total_plays,COALESCE(SUM(listened),0) AS total_sec,

              (SELECT json_group_array(json_object('id',id,'title',title,'artist',artist,'album',album,

                'cover_path',cover_path,'cover_url',cover_url,'source',source,'source_id',source_id,

                'plays',plays,'total_listened_sec',total_listened_sec)) FROM tracks_ranked) AS top_tracks,

              (SELECT json_group_array(json_object('artist',artist,'plays',plays,'total_listened_sec',total_listened_sec)) FROM artists_ranked) AS top_artists,

              (SELECT json_group_array(json_object('day_idx',day_idx,'plays',plays,'minutes',minutes)) FROM activity) AS activity

            FROM events

        """

        row = self.conn.execute(query, parameters).fetchone()

        seconds = float(row['total_sec'])

        activity = {entry['day_idx']: entry for entry in json.loads(row['activity'])}

        daily = []

        for day, index in [('Пн','1'),('Вт','2'),('Ср','3'),('Чт','4'),('Пт','5'),('Сб','6'),('Вс','0')]:

            item = activity.get(index, {})

            daily.append({'day':day,'idx':index,'plays':int(item.get('plays',0)), 'minutes':round(float(item.get('minutes',0)),1)})

        return {'period':period,'total_plays':int(row['total_plays']), 'total_seconds':round(seconds,1),

                'total_minutes':round(seconds/60,1),'total_hours':round(seconds/3600,2),

                'top_tracks':json.loads(row['top_tracks']),'top_artists':json.loads(row['top_artists']),'daily_activity':daily}



    def get_analytics_summary(self) -> Dict[str, Any]:

        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM tracks")

        total_tracks = cursor.fetchone()[0]



        cursor.execute("SELECT COUNT(*) FROM playlists")

        total_playlists = cursor.fetchone()[0]



        total_time = self.get_total_listening_time() / 1000



        return {

            "total_tracks": total_tracks,

            "total_playlists": total_playlists,

            "total_listening_time": total_time,

        }



    def create_playlist(self, name: str, description: str = "", is_system: bool = False) -> int:

        """Return the id of the playlist called `name`, creating it if needed."""

        playlist_id, _created = self.create_playlist_ex(name, description, is_system=is_system)

        return playlist_id



    def create_playlist_ex(self, name: str, description: str = "", is_system: bool = False) -> tuple:

        """create_playlist, but also reporting whether the row is new.



        Returns ``(playlist_id, created)``. ``created`` is False when an

        existing playlist of that name was reused. Callers that undo their own

        partial work (playlist import) must roll back only a playlist they

        created themselves - deleting a playlist the user already had would

        take their tracks with it (ON DELETE CASCADE).

        """

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                clean_name = (name or "").strip()

                # Run before the lookup so the id handed back is always the one

                # this cleanup keeps. Reentrant lock: safe to nest.

                self._cleanup_duplicate_empty_system_playlists(cursor)

                # If playlist with same name already exists (especially system names), reuse it

                cursor.execute("SELECT id FROM playlists WHERE LOWER(name) = LOWER(?) AND is_system = ? LIMIT 1", (clean_name, int(is_system)))

                row = cursor.fetchone()

                if row:

                    return row["id"], False



                cursor.execute("INSERT INTO playlists (name, description, is_system) VALUES (?, ?, ?)", (clean_name, description, int(is_system)))

                return cursor.lastrowid, True



    def _cleanup_duplicate_empty_system_playlists(self, cursor=None) -> int:

        """Drop duplicate EMPTY system playlists ('Локальные'/'Локальные треки').



        Those two names were historically created by several code paths, so a

        database can hold several rows for one of them and the UI then lists

        the same (empty) playlist two or three times. The oldest row per name

        survives; rows that still hold tracks are never touched.



        Lives here rather than in get_playlists(): that getter is called on

        every playlist view render (and by import/export helpers), so a DELETE

        plus a COMMIT on the calling thread's connection turned a read into a

        write, ran outside ``_write_lock`` like every other writer does, and

        could commit unrelated in-flight work on that thread's connection.

        Playlist creation is the only event that can reintroduce the

        duplicates, so that is where it runs.

        """

        sql = """

            DELETE FROM playlists

            WHERE is_system = 1 AND name IN ('Локальные', 'Локальные треки')

            AND id NOT IN (SELECT DISTINCT playlist_id FROM playlist_tracks)

            AND id NOT IN (

                SELECT MIN(id) FROM playlists

                WHERE is_system = 1 AND name IN ('Локальные', 'Локальные треки')

                GROUP BY name

            )

        """

        own_cursor = cursor is None

        try:

            if own_cursor:

                with self._write_lock:

                    with self.conn:

                        return self.conn.execute(sql).rowcount

            return cursor.execute(sql).rowcount

        except Exception as e:

            # Never let housekeeping break playlist creation / a view render;

            # a stale duplicate is cosmetic, a raised error is not.

            logger.warning("Failed to clean up duplicate system playlists: %s", e, exc_info=True)

            return 0



    def get_playlists(self) -> List[Dict[str, Any]]:

        """All playlists with their track counts. Pure read: no writes, no commit."""

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



    def get_playlists_count(self) -> int:

        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM playlists")

        return cursor.fetchone()[0]



    def add_to_playlist(self, playlist_id: int, track_id: int) -> bool:

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?",

                        (playlist_id,),

                    )

                    row = cursor.fetchone()

                    next_pos = row[0] if row else 1

                    cursor.execute(

                        "INSERT INTO playlist_tracks (playlist_id, track_id, position) SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?)",

                        (playlist_id, track_id, next_pos, playlist_id, track_id),

                    )

                    cursor.execute("UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (playlist_id,))

                return True

            except Exception as e:

                logger.error(f"Failed to add to playlist: {e}")

                return False



    def add_tracks_to_playlist(self, playlist_id: int, track_ids: List[int]) -> int:

        """Batch add tracks to a playlist in a single atomic transaction."""

        if not track_ids:

            return 0

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "SELECT COALESCE(MAX(position), 0) FROM playlist_tracks WHERE playlist_id = ?",

                        (playlist_id,),

                    )

                    row = cursor.fetchone()

                    current_pos = row[0] if row else 0

                    rows = []

                    existing = {r[0] for r in cursor.execute('SELECT track_id FROM playlist_tracks WHERE playlist_id = ?', (playlist_id,))}

                    for t_id in track_ids:

                        if t_id in existing:

                            continue

                        existing.add(t_id)

                        current_pos += 1

                        rows.append((playlist_id, t_id, current_pos))

                    cursor.executemany(

                        "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",

                        rows,

                    )

                    cursor.execute("UPDATE playlists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (playlist_id,))

                return len(rows)

            except Exception as e:

                logger.error(f"Failed to batch add to playlist: {e}")

                return 0



    def invalidate_offline_track(self, track_id: int) -> None:
        from core.offline import invalidate_offline_track
        invalidate_offline_track(self, track_id)

    def get_smart_playlist_tracks(self, playlist_id: int, limit: int = 500, offset: int = 0, available_only: bool = False) -> List[Dict[str, Any]]:
        from services.smart_playlists import SmartPlaylistService
        return SmartPlaylistService(self).tracks(playlist_id, limit=limit, offset=offset, available_only=available_only)



    def get_playlist_tracks(self, playlist_id: int, limit=None) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        cursor.execute(

            """

            SELECT t.*, pt.position, pt.added_at as added_to_playlist_at

            FROM playlist_tracks pt

            JOIN tracks t ON pt.track_id = t.id

            WHERE pt.playlist_id = ?

            ORDER BY pt.position ASC

        """ + (' LIMIT ?' if limit is not None else ''),

            (playlist_id, max(0, int(limit))) if limit is not None else (playlist_id,),

        )

        return [dict(row) for row in cursor.fetchall()]



    def rename_playlist(self, playlist_id: int, name: str) -> bool:
        """Rename only a user collection, preserving its identity and members."""
        name = str(name or '').strip()
        if not name or len(name) > 200:
            return False
        with self._write_lock, self.conn:
            cursor = self.conn.execute(
                'UPDATE playlists SET name = ? WHERE id = ? AND COALESCE(is_system, 0) = 0',
                (name, int(playlist_id)))
            return cursor.rowcount > 0

    def remove_from_playlist(self, playlist_id: int, track_id: int) -> bool:
        """Remove membership only; never delete the track or downloaded file."""
        with self._write_lock, self.conn:
            cursor = self.conn.execute(
                'DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ? '
                'AND EXISTS (SELECT 1 FROM playlists WHERE id = ? AND COALESCE(is_system, 0) = 0)',
                (int(playlist_id), int(track_id), int(playlist_id)))
            return cursor.rowcount > 0

    def delete_playlist(self, playlist_id: int) -> bool:

        pid = int(playlist_id)

        with self._write_lock:

            conn = self.conn

            with conn:

                cursor = conn.cursor()

                cursor.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (pid,))

                cursor.execute("DELETE FROM playlists WHERE id = ?", (pid,))

                return cursor.rowcount > 0



    @staticmethod
    def _serialize_setting(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _deserialize_setting(raw_v: Any) -> Any:
        if not isinstance(raw_v, str):
            return raw_v
        try:
            return json.loads(raw_v)
        except (json.JSONDecodeError, TypeError):
            if raw_v in ("True", "true"):
                return True
            elif raw_v in ("False", "false"):
                return False
            return raw_v

    def set_setting(self, key: str, value: Any, category: str = "general") -> None:
        with self._write_lock:
            conn = self.conn
            try:
                with conn:
                    cursor = conn.cursor()
                    if is_sensitive_setting(key, category) and isinstance(value, str) and value:
                        stored_val = dpapi_encrypt(value)
                    else:
                        stored_val = self._serialize_setting(value)
                    cursor.execute(
                        "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (key, stored_val, category),
                    )
            except Exception as e:
                logger.error(f"set_setting failed for {key}: {e}")

    def set_settings_batch(self, items: Any) -> int:
        """Persist many settings inside a single transaction.

        `items` is a sequence of (key, value, category) tuples; returns the
        number of rows written, and 0 on any failure (serialization included -
        it used to run outside the try, so an unserializable value raised
        straight out of the caller's flush). SettingsManager's write-behind
        batching uses this so a burst of set() calls costs one COMMIT instead
        of one each, and it keys its "were they written?" decision off the
        returned count.
        """
        try:
            rows = []
            for key, value, category in items:
                if is_sensitive_setting(key, category) and isinstance(value, str) and value:
                    stored_val = dpapi_encrypt(value)
                else:
                    stored_val = self._serialize_setting(value)
                rows.append((key, stored_val, category))
        except Exception as e:
            logger.error(f"set_settings_batch failed: {e}")
            return 0
        if not rows:
            return 0
        with self._write_lock:
            conn = self.conn
            try:
                with conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO settings (key, value, category, updated_at) "
                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        rows,
                    )
                return len(rows)
            except Exception as e:
                logger.error(f"set_settings_batch failed: {e}")
                return 0

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value, category FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return default
        raw_v = row["value"]
        cat = row["category"] if "category" in row.keys() else "general"

        if is_dpapi_encrypted(raw_v):
            return dpapi_decrypt(raw_v)

        val = self._deserialize_setting(raw_v)
        if is_sensitive_setting(key, cat) and isinstance(val, str) and val:
            try:
                with self._write_lock:
                    with self.conn:
                        self.conn.cursor().execute(
                            "UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                            (dpapi_encrypt(val), key),
                        )
            except Exception as e:
                logger.warning(f"Transparent migration failed for {key}: {e}")
        return val

    def get_settings_by_category(self, category: str) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings WHERE category = ?", (category,))
        result = {}
        to_migrate = []
        for row in cursor.fetchall():
            k, raw_v = row[0], row[1]
            if is_dpapi_encrypted(raw_v):
                result[k] = dpapi_decrypt(raw_v)
            else:
                val = self._deserialize_setting(raw_v)
                result[k] = val
                if is_sensitive_setting(k, category) and isinstance(val, str) and val:
                    to_migrate.append((k, val))

        if to_migrate:
            try:
                with self._write_lock:
                    with self.conn:
                        for k, val in to_migrate:
                            self.conn.cursor().execute(
                                "UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                                (dpapi_encrypt(val), k),
                            )
            except Exception as e:
                logger.warning(f"Transparent migration failed for category {category}: {e}")
        return result

    def get_all_settings(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value, category FROM settings")
        result = {}
        to_migrate = []
        for row in cursor.fetchall():
            k, raw_v, cat = row[0], row[1], row[2]
            if is_dpapi_encrypted(raw_v):
                result[k] = dpapi_decrypt(raw_v)
            else:
                val = self._deserialize_setting(raw_v)
                result[k] = val
                if is_sensitive_setting(k, cat) and isinstance(val, str) and val:
                    to_migrate.append((k, val))

        if to_migrate:
            try:
                with self._write_lock:
                    with self.conn:
                        for k, val in to_migrate:
                            self.conn.cursor().execute(
                                "UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                                (dpapi_encrypt(val), k),
                            )
            except Exception as e:
                logger.warning(f"Transparent migration failed for all settings: {e}")
        return result


    def set_track_lyrics_override(
        self,
        identity_key: str,
        override_type: str,
        source_name: str,
        plain_lyrics: str,
        synced_lyrics: Optional[str] = None,
        sync_type: str = "plain",
        source_id: Optional[str] = None,
        track_id: Optional[int] = None,
        offset_ms: int = 0,
    ) -> bool:
        """Store or update a user-chosen or custom lyric override for a track."""
        if not identity_key or not plain_lyrics:
            return False
        now = time.time()
        with self._write_lock:
            with self.conn:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO track_lyrics_overrides (
                        track_id, identity_key, override_type, source_name, source_id,
                        synced_lyrics, plain_lyrics, sync_type, offset_ms, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(identity_key) DO UPDATE SET
                        track_id = COALESCE(excluded.track_id, track_lyrics_overrides.track_id),
                        override_type = excluded.override_type,
                        source_name = excluded.source_name,
                        source_id = excluded.source_id,
                        synced_lyrics = excluded.synced_lyrics,
                        plain_lyrics = excluded.plain_lyrics,
                        sync_type = excluded.sync_type,
                        offset_ms = excluded.offset_ms,
                        updated_at = excluded.updated_at
                    """,
                    (
                        track_id,
                        identity_key,
                        override_type,
                        source_name,
                        source_id,
                        synced_lyrics,
                        plain_lyrics,
                        sync_type,
                        offset_ms,
                        now,
                        now,
                    ),
                )
                return True

    def get_track_lyrics_override(
        self,
        identity_key: Optional[str] = None,
        track_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a lyric override by persistent identity_key or library track_id."""
        cursor = self.conn.cursor()
        if identity_key:
            cursor.execute(
                "SELECT * FROM track_lyrics_overrides WHERE identity_key = ?",
                (identity_key,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        if track_id is not None and track_id > 0:
            cursor.execute(
                "SELECT * FROM track_lyrics_overrides WHERE track_id = ?",
                (track_id,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def delete_track_lyrics_override(
        self,
        identity_key: Optional[str] = None,
        track_id: Optional[int] = None,
    ) -> bool:
        """Remove a lyric override by identity_key or library track_id."""
        with self._write_lock:
            with self.conn:
                cursor = self.conn.cursor()
                deleted = False
                if identity_key:
                    cursor.execute(
                        "DELETE FROM track_lyrics_overrides WHERE identity_key = ?",
                        (identity_key,),
                    )
                    deleted = deleted or (cursor.rowcount > 0)
                if track_id is not None and track_id > 0:
                    cursor.execute(
                        "DELETE FROM track_lyrics_overrides WHERE track_id = ?",
                        (track_id,),
                    )
                    deleted = deleted or (cursor.rowcount > 0)
                return deleted

    def set_cached_file(self, source: str, source_id: str, file_path: str) -> None:

        # O-3: downloaded files are long-lived — never auto-purged by expires_at.

        # Upsert: a fresh download may finish without a prior URL row from the

        # resolver (BUG-A1-006 fix registers the hashed path unconditionally),

        # and a silent UPDATE-only no-op would leave the file unregistered.

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "INSERT INTO stream_cache (source, source_id, cached_file_path, cached_at) "

                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "

                        "ON CONFLICT(source, source_id) DO UPDATE SET "

                        "cached_file_path = excluded.cached_file_path, "

                        "expires_at = NULL, cached_at = CURRENT_TIMESTAMP",

                        (source, source_id, file_path),

                    )

            except Exception as e:

                logger.debug(f"set_cached_file suppressed: {e}")



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

        meta_json = json.dumps(metadata) if metadata else None

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

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

            except Exception as e:

                logger.error(f"cache_stream failed: {e}")



    def update_cached_stream_url(self, source: str, source_id: str, stream_url: str) -> None:

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "INSERT INTO stream_cache(source, source_id, stream_url, expires_at) VALUES (?, ?, ?, datetime('now', '+24 hours')) "

                        "ON CONFLICT(source, source_id) DO UPDATE SET stream_url = excluded.stream_url, cached_at = CURRENT_TIMESTAMP, expires_at = excluded.expires_at",

                        (source, source_id, stream_url),

                    )

            except Exception as e:

                logger.error(f"update_cached_stream_url failed: {e}")



    def invalidate_cached_stream(self, source: str, source_id: str) -> None:

        """Clear a dead stream URL but keep the row (downloaded-file rows survive)."""

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "UPDATE stream_cache SET stream_url = NULL WHERE source = ? AND source_id = ?",

                        (source, source_id),

                    )

            except Exception as e:

                logger.error(f"invalidate_cached_stream failed: {e}")



    def cleanup_expired_cache(self) -> int:

        """O-3: purge stream_cache rows past expires_at (skips downloaded-file rows)."""

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "DELETE FROM stream_cache WHERE expires_at IS NOT NULL "

                        "AND datetime(expires_at) < datetime('now') "

                        "AND (cached_file_path IS NULL OR cached_file_path = '')"

                    )

                    return cursor.rowcount

            except Exception as e:

                logger.error(f"cleanup_expired_cache failed: {e}")

                return 0



    def add_scan_folder(self, folder_path: str) -> bool:

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute("INSERT INTO scan_folders (folder_path) VALUES (?)", (folder_path,))

                return True

            except Exception:

                return False



    def get_scan_folders(self) -> List[Dict[str, Any]]:

        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM scan_folders ORDER BY folder_path ASC")

        return [dict(row) for row in cursor.fetchall()]



    def update_scan_time(self, folder_path: str) -> None:

        with self._write_lock:

            conn = self.conn

            try:

                with conn:

                    cursor = conn.cursor()

                    cursor.execute(

                        "UPDATE scan_folders SET last_scanned = CURRENT_TIMESTAMP WHERE folder_path = ?",

                        (folder_path,),

                    )

            except Exception as e:

                logger.error(f"update_scan_time failed: {e}")



    def add_listening_time(self, duration_ms: int) -> None:

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                cursor.execute("INSERT INTO listening_stats (duration_ms) VALUES (?)", (duration_ms,))



    def get_total_listening_time(self) -> int:

        cursor = self.conn.cursor()

        cursor.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM listening_stats")

        return cursor.fetchone()[0]



    def ensure_download_queue_table(self, cursor=None) -> None:

        """Create the download queue table + uniqueness guard, idempotently.



        Used by ``_init_database`` (with its cursor) and preferred by

        ``DownloadManager._init_db_table`` over its own fallback DDL, so both

        paths converge on one schema. Older databases may hold duplicate rows

        per track, which are collapsed (newest attempt wins) before the unique

        index is created.

        """

        ddl = """

            CREATE TABLE IF NOT EXISTS download_queue (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,

                source TEXT,

                source_id TEXT,

                status TEXT DEFAULT 'pending',

                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )

        """

        dedup = """

            DELETE FROM download_queue

            WHERE id NOT IN (

                SELECT MAX(id) FROM download_queue GROUP BY track_id

            )

        """

        unique_index = (

            "CREATE UNIQUE INDEX IF NOT EXISTS ux_download_queue_track "

            "ON download_queue(track_id)"

        )

        if cursor is not None:

            cursor.execute(ddl)

            try:

                cursor.execute(dedup)

            except sqlite3.OperationalError:

                pass

            cursor.execute(unique_index)

            cursor.execute('CREATE TRIGGER IF NOT EXISTS download_queue_track_delete AFTER DELETE ON tracks BEGIN DELETE FROM download_queue WHERE track_id=old.id; END')

            return

        with self._write_lock:

            with self.conn:

                self.conn.execute(ddl)

                try:

                    self.conn.execute(dedup)

                except sqlite3.OperationalError:

                    pass

                self.conn.execute(unique_index)

                self.conn.execute('CREATE TRIGGER IF NOT EXISTS download_queue_track_delete AFTER DELETE ON tracks BEGIN DELETE FROM download_queue WHERE track_id=old.id; END')



    def download_queue_add(self, track_id, source, source_id) -> bool:

        """Ensure the track has a queue row. Returns True when one is now queued.



        Verified against the unique index ux_download_queue_track: the row that

        already exists is neither deleted nor reset by this call - a failed or

        cancelled attempt used to leave the track permanently unqueueable,

        because the INSERT raised IntegrityError and the caller took it as

        "already queued" and moved on. The upsert re-arms exactly those two

        terminal states and leaves every other status (pending / downloading /

        completed) untouched, so a double click still cannot start a second

        download of the same track. No new column: status and added_at are all

        it needs.

        """

        with self._write_lock:

            try:

                with self.conn:

                    cursor = self.conn.cursor()

                    cursor.execute(

                        'INSERT INTO download_queue (track_id, source, source_id) VALUES (?, ?, ?) '

                        "ON CONFLICT(track_id) DO UPDATE SET status = 'pending', added_at = CURRENT_TIMESTAMP "

                    "WHERE download_queue.status IN ('failed', 'cancelled', 'paused')",

                        (track_id, source, source_id),

                    )

                    # rowcount is 0 when the conflict was not re-armed (the

                    # DO UPDATE ... WHERE did not match), i.e. an existing

                    # non-terminal row was kept as-is.

                    return cursor.rowcount > 0

            except Exception as e:

                logger.debug(f'Download queue insert skipped for track {track_id}: {e}')

                return False



    def download_queue_set_status(self, track_id, status: str) -> None:

        with self._write_lock:

            try:

                with self.conn:

                    self.conn.execute(

                        "UPDATE download_queue SET status = ? WHERE track_id = ?",

                        (status, track_id),

                    )

            except Exception:

                logger.debug("download_queue_set_status failed", exc_info=True)



    def download_queue_set_downloading(self, track_id) -> None:

        with self._write_lock:

            try:

                with self.conn:

                    self.conn.execute(

                        "UPDATE download_queue SET status = 'downloading' "

                        "WHERE track_id = ? AND status != 'completed'",

                        (track_id,),

                    )

            except Exception:

                pass



    def download_queue_get_status(self, track_id):

        cursor = self.conn.cursor()

        try:

            cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))

            row = cursor.fetchone()

        except Exception:

            return None

        if not row:

            return None

        try:

            if isinstance(row, dict) or hasattr(row, 'keys'):

                return row['status']

            return row[0]

        except Exception:

            return None



    def download_queue_cancel_pending(self) -> None:

        with self._write_lock:

            try:

                with self.conn:

                    columns = {row[1] for row in self.conn.execute("PRAGMA table_info(download_queue)")}

                    resume_reset = ", resume_on_restart = 0" if "resume_on_restart" in columns else ""

                    self.conn.execute(

                        "UPDATE download_queue SET status = 'cancelled'" + resume_reset +

                        " WHERE status IN ('pending', 'downloading')"

                    )

            except Exception:

                pass



    def download_queue_get_pending(self):

        cursor = self.conn.cursor()

        cursor.execute("SELECT track_id, source, source_id FROM download_queue WHERE status IN ('pending', 'downloading')")

        return [dict(r) if hasattr(r, 'keys') else {"track_id": r[0], "source": r[1], "source_id": r[2]} for r in cursor.fetchall()]



    def close_thread_connection(self) -> None:

        """Close and forget the calling thread's connection, if it has one.



        Safe to call from any thread, repeatedly, and when no connection was

        ever opened; it never raises. Worker threads (stream proxy requests,

        scan workers) should call this when they finish so their page cache is

        released instead of living until process exit.

        """

        # Only "connection" exists: _get_connection() is the single writer of

        # the thread-local slot, so probing a second attribute name could only

        # ever miss.

        existing = getattr(self._local, "connection", None)

        if existing is None:

            return

        changes = 0

        try:

            changes = existing.total_changes

            existing.close()

        except Exception as e:

            # A handle owned by this thread should always close cleanly; if it

            # does not, the connection leaks and the error must be visible.

            logger.warning("close_thread_connection: failed to close connection: %s", e)

        try:

            self._local.connection = None

        except Exception:

            pass

        with self._conns_lock:

            self._data_revision += changes

            self._all_conns.discard(existing)

            self._conn_owners.pop(existing, None)



    def _checkpoint_wal(self) -> None:

        """Fold this connection's WAL back into the main database file.



        Closing a WAL connection does NOT checkpoint it: the last writer's

        frames stay in the -wal file, which is then discarded along with the

        connection handle. On a database file that was already checkpointed by

        SQLite's own cleanup this is a no-op; where it was not, the recent

        writes are lost without a word. TRUNCATE also resets the -wal file so

        the next writer starts from an empty log.



        Runs on the calling thread's own connection (the thread-local model is

        unchanged) and never raises: ":memory:" databases have no WAL, where

        the pragma reports success without doing anything.

        """

        try:

            self.conn.execute("PRAGMA busy_timeout=200")

            self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

        except Exception as e:

            logger.warning("WAL checkpoint failed: %s", e)



    def close(self) -> None:

        """Close all connections tracked by this database manager instance.



        A connection created on another thread cannot be used (let alone

        closed) from here - sqlite3 raises ProgrammingError - so those handles

        survive until their own thread ends and are released when their thread

        dies. That used to be swallowed with a bare ``except: pass``; the

        failure is now reported, but as ONE summary line: there can be hundreds

        of these at shutdown, and logging each one flooded app.log with the same

        message and turned the signal into noise.

        """

        if self._closed:

            return

        self._checkpoint_wal()

        self._closed = True

        self.close_thread_connection()

        failed = 0

        first_error = None

        with self._conns_lock:

            for conn in list(self._all_conns):

                try:

                    conn.close()

                except Exception as e:

                    failed += 1

                    if first_error is None:

                        first_error = str(e)

            self._all_conns.clear()

            self._conn_owners.clear()

        if failed:

            logger.warning(

                "%d database connection(s) could not be closed from the main "

                "thread (created on another thread); they were released when "

                "that thread exited. First error: %s",

                failed, first_error,

            )



    def import_playlist_atomic(self, name, description, tracks):

        """Create/reuse a playlist and import every row in one transaction."""

        import math
        import hashlib

        if not isinstance(tracks, list) or not tracks or len(tracks) > 2000:

            raise ValueError('Playlist must contain between 1 and 2000 tracks')

        clean_name = str(name or '').strip()[:200]

        if not clean_name:

            raise ValueError('Playlist name is required')

        prepared = []

        for item in tracks:

            if not isinstance(item, dict):

                raise ValueError('Invalid playlist track')

            source = str(item.get('source') or 'youtube')

            source_id = str(item.get('source_id') or '').strip()
            file_path=str(item.get('file_path') or '').strip() or None
            if source=='local' and file_path and not source_id:
                source_id='local_'+hashlib.sha256(os.path.normcase(os.path.abspath(file_path)).encode('utf-8')).hexdigest()
            downloaded=int(bool(file_path and os.path.isfile(file_path)))

            title, artist = str(item.get('title') or 'Unknown Title'), str(item.get('artist') or 'Unknown Artist')

            duration = float(item.get('duration') or 0)

            if not source_id or len(source_id) > 2048 or not math.isfinite(duration) or not 0 <= duration <= 86400:

                raise ValueError('Invalid playlist track identity or duration')

            prepared.append((source, source_id, title[:2000], artist[:2000], duration,

                             str(item.get('album') or 'Unknown Album')[:2000],

                             item.get('source_url'), item.get('cover_url'), file_path, downloaded))

        with self._write_lock:

            with self.conn:

                cursor = self.conn.cursor()

                row = cursor.execute('SELECT id FROM playlists WHERE LOWER(name)=LOWER(?) AND is_system=0 LIMIT 1', (clean_name,)).fetchone()

                if row:

                    playlist_id = row['id']

                else:

                    cursor.execute('INSERT INTO playlists(name,description,is_system) VALUES (?,?,0)', (clean_name, str(description or '')[:4096]))

                    playlist_id = cursor.lastrowid

                existing = {row[0] for row in cursor.execute('SELECT track_id FROM playlist_tracks WHERE playlist_id=?', (playlist_id,))}

                position = cursor.execute('SELECT COALESCE(MAX(position),0) FROM playlist_tracks WHERE playlist_id=?', (playlist_id,)).fetchone()[0]

                imported = 0

                for source, source_id, title, artist, duration, album, source_url, cover_url, file_path, downloaded in prepared:

                    row = cursor.execute('SELECT id FROM tracks WHERE source=? AND source_id=? LIMIT 1', (source,source_id)).fetchone()

                    if row is None and file_path:
                        row=cursor.execute('SELECT id FROM tracks WHERE file_path=? LIMIT 1',(file_path,)).fetchone()

                    if row is None and name_is_meaningful(title, artist):

                        row = cursor.execute('SELECT id FROM tracks WHERE '+TRACK_IDENTITY_SQL+' LIMIT 1', (title,artist)).fetchone()

                    if row:

                        track_id = row['id']
                        if file_path:
                            cursor.execute("UPDATE tracks SET file_path=?,is_downloaded=? WHERE id=? AND (file_path IS NULL OR file_path='')",(file_path,downloaded,track_id))
                        if cover_url:
                            cursor.execute("UPDATE tracks SET cover_url=? WHERE id=? AND (cover_url IS NULL OR cover_url='')",(cover_url,track_id))

                    else:

                        cursor.execute('INSERT INTO tracks(title,artist,album,duration,source,source_id,source_url,cover_url,file_path,is_downloaded) VALUES (?,?,?,?,?,?,?,?,?,?)',

                                       (title,artist,album,duration,source,source_id,source_url,cover_url,file_path,downloaded))

                        track_id = cursor.lastrowid

                    if track_id not in existing:

                        existing.add(track_id)

                        position += 1

                        cursor.execute('INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES (?,?,?)', (playlist_id,track_id,position))

                        imported += 1

                cursor.execute('UPDATE playlists SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (playlist_id,))

                return playlist_id, imported
