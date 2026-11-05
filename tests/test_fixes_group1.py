"""
Regression and verification tests for Group 1 fixes:
- BUG-WIN-005: Corrupted SQLite recovery with timestamped backup of DB, WAL, SHM
- BUG-WIN-007: Dup cleanup restore not blocked by premature execution
- BUG-WIN-009: Thread-safe data_revision without lock races
- BUG-WIN-026: Fast search, FTS5 usage, and cached unicode_casefold / artist_primary UDFs
- BUG-WIN-030: Safe dead connection cleanup handling close/total_changes exceptions
- BUG-WIN-057: Bounded shutdown and process termination when durable/WAL flush fails
"""

import os
import glob
import json
import sqlite3
import threading
import time
import pytest

from core.database import (
    DatabaseManager,
    _unicode_casefold_str,
    _artist_primary_str,
)
from core.app import finalize_process


# ==============================================================================
# BUG-WIN-005: Corrupted SQLite Database Recovery
# ==============================================================================

def test_bug_win_005_corrupted_database_recovery(tmp_path):
    """When nedotify_storage.db is corrupted, DatabaseManager must not crash.
    It must preserve the corrupted DB and its WAL/SHM sidecars as .corrupted.<timestamp>
    and initialize a fresh, operational database."""
    db_path = str(tmp_path / "corrupted_test.db")
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"

    junk_content = b"GARBAGE_NOT_A_SQLITE_DATABASE_DATA_12345"
    with open(db_path, "wb") as f:
        f.write(junk_content)
    with open(wal_path, "wb") as f:
        f.write(b"GARBAGE_WAL")
    with open(shm_path, "wb") as f:
        f.write(b"GARBAGE_SHM")

    # Initializing DatabaseManager must recover gracefully
    db = DatabaseManager(db_path)
    try:
        # Check that db is now valid and writable
        tid = db.add_track(title="Test Song", artist="Test Artist", source="local", file_path="test.mp3")
        assert tid > 0
        track = db.get_track(tid)
        assert track is not None
        assert track["title"] == "Test Song"

        # Check that backup files were created
        backups = glob.glob(f"{db_path}.corrupted.*")
        # Must find the main backup file (not ending in -wal or -shm)
        main_backups = [b for b in backups if not b.endswith("-wal") and not b.endswith("-shm")]
        assert len(main_backups) >= 1
        with open(main_backups[0], "rb") as f:
            assert f.read() == junk_content

        wal_backups = [b for b in backups if b.endswith("-wal")]
        assert len(wal_backups) >= 1
        with open(wal_backups[0], "rb") as f:
            assert f.read() == b"GARBAGE_WAL"

        shm_backups = [b for b in backups if b.endswith("-shm")]
        assert len(shm_backups) >= 1
        assert os.path.getsize(shm_backups[0]) > 0
    finally:
        db.close()


# ==============================================================================
# BUG-WIN-007: Dup Cleanup Restore Rescues Merged Tracks
# ==============================================================================

def test_bug_win_007_dup_cleanup_restore_not_blocked(tmp_path):
    """If DUP_CLEANUP_RESTORE_VERSION was previously marked with restored=0
    (due to the premature call on line 488 before the snapshot table existed),
    a subsequent run with candidate merges must still restore them."""
    db_path = str(tmp_path / "dup_restore_test.db")
    db = DatabaseManager(db_path)
    try:
        t1 = db.add_track(title="Song", artist="Artist", album="Album", source="local", file_path="s1.mp3")
        t2 = db.add_track(title="Song", artist="Artist", album="Album", source="local", file_path="s2.mp3")
        # Simulate that t2 was retired by an older migration 'dup_cleanup_v1'
        db.conn.execute("CREATE TABLE IF NOT EXISTS tracks_backup AS SELECT * FROM tracks")
        db.conn.execute(
            "INSERT OR REPLACE INTO track_merges (duplicate_id, survivor_id, merged_by) VALUES (?, ?, ?)",
            (t2, t1, "dup_cleanup_v1")
        )
        db.conn.execute("DELETE FROM tracks WHERE id = ?", (t2,))
        # Simulate premature entry with restored = 0
        db.conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, applied_at, details) VALUES (?, CURRENT_TIMESTAMP, ?)",
            (DatabaseManager.DUP_CLEANUP_RESTORE_VERSION, json.dumps({"restored": 0}))
        )
        db.conn.commit()
    finally:
        db.close()

    # Reopen database - the fix must detect that candidates exist and restore t2
    db2 = DatabaseManager(db_path)
    try:
        restored_track = db2.get_track(t2)
        assert restored_track is not None
        assert restored_track["id"] == t2
    finally:
        db2.close()


# ==============================================================================
# BUG-WIN-009: Thread-Safe data_revision
# ==============================================================================

def test_bug_win_009_data_revision_concurrent_writes(tmp_path):
    """Multiple threads concurrently writing to the database while calling
    data_revision must not raise race conditions, deadlocks, or SQLite errors."""
    db_path = str(tmp_path / "concurrent_rev.db")
    db = DatabaseManager(db_path)
    errors = []
    stop_event = threading.Event()

    def writer(thread_id):
        try:
            for i in range(25):
                db.add_track(
                    title=f"Title {thread_id}_{i}",
                    artist=f"Artist {thread_id}",
                    source="local",
                    file_path=f"path_{thread_id}_{i}.mp3"
                )
                time.sleep(0.002)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            while not stop_event.is_set():
                rev = db.data_revision
                assert isinstance(rev, int)
                assert rev >= 0
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    reader_thread = threading.Thread(target=reader)

    reader_thread.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stop_event.set()
    reader_thread.join()

    db.close()
    assert not errors, f"Encountered errors during concurrent data_revision: {errors}"


def test_bug_win_009_data_revision_resilient_to_dead_conn_error(tmp_path):
    """If a connection in _all_conns fails during total_changes access,
    data_revision must catch the exception gracefully and return a valid int."""
    db_path = str(tmp_path / "conn_err_rev.db")
    db = DatabaseManager(db_path)

    class BrokenConn:
        @property
        def total_changes(self):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database")

    with db._conns_lock:
        db._all_conns.add(BrokenConn())

    try:
        rev = db.data_revision
        assert isinstance(rev, int)
    finally:
        db.close()


# ==============================================================================
# BUG-WIN-026: Fast Search, FTS5 & Cached UDFs
# ==============================================================================

def test_bug_win_026_cached_udf_functions():
    """UDFs _unicode_casefold_str and _artist_primary_str must be LRU-cached."""
    _unicode_casefold_str.cache_clear()
    _artist_primary_str.cache_clear()

    res1 = _unicode_casefold_str("Ёлка")
    res2 = _unicode_casefold_str("Ёлка")
    assert res1 == "елка"
    assert res2 == "елка"
    assert _unicode_casefold_str.cache_info().hits >= 1

    prim1 = _artist_primary_str("Queen feat. David Bowie")
    prim2 = _artist_primary_str("Queen feat. David Bowie")
    assert prim1 == "Queen"
    assert prim2 == "Queen"
    assert _artist_primary_str.cache_info().hits >= 1


def test_bug_win_026_search_performance_and_correctness(tmp_path):
    """search_tracks, search_artists, and search_albums should use FTS5/indexes
    and pre-folded query strings without full scan UDF evaluation."""
    db_path = str(tmp_path / "search_test.db")
    db = DatabaseManager(db_path)
    try:
        db.add_track(title="Звезда по имени Солнце", artist="Кино", album="Звезда", source="local", file_path="k1.mp3")
        db.add_track(title="Группа крови", artist="Кино", album="Группа крови", source="local", file_path="k2.mp3")
        db.add_track(title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera", source="local", file_path="q1.mp3")

        # Test Cyrillic casefold with ё/e
        results = db.search_tracks("звезда")
        assert len(results) == 1
        assert results[0]["title"] == "Звезда по имени Солнце"

        # Search artists
        artists = db.search_artists("кино")
        assert len(artists) == 1
        assert artists[0]["artist"] == "Кино"

        # Search albums
        albums = db.search_albums("opera")
        assert len(albums) == 1
        assert albums[0]["title"] == "A Night at the Opera"

        # get_top_artists
        db.conn.execute("UPDATE tracks SET play_count = 10 WHERE artist = 'Кино'")
        db.conn.commit()
        top = db.get_top_artists(10)
        assert len(top) >= 1
        assert top[0]["artist"] == "Кино"

        # Check that title_lower index exists
        indices = {
            row["name"] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "idx_tracks_title_lower" in indices
        assert "idx_tracks_play_count_artist" in indices
    finally:
        db.close()


# ==============================================================================
# BUG-WIN-030: Dead Connection Cleanup Safety
# ==============================================================================

def test_bug_win_030_dead_connection_close_safety(tmp_path):
    """If a dead thread's connection raises an exception on close() or total_changes,
    _get_connection() must not crash."""
    db_path = str(tmp_path / "dead_conn_test.db")
    db = DatabaseManager(db_path)

    class DummyDeadThread:
        def is_alive(self):
            return False

    class BrokenConnection:
        @property
        def total_changes(self):
            raise sqlite3.ProgrammingError("Cannot read total_changes")

        def close(self):
            raise sqlite3.OperationalError("Already closed or locked")

    dead_thread = DummyDeadThread()
    broken_conn = BrokenConnection()

    with db._conns_lock:
        db._all_conns.add(broken_conn)
        db._conn_owners[broken_conn] = dead_thread

    # Calling _get_connection must clean up dead threads without raising
    conn = db._get_connection()
    assert conn is not None

    with db._conns_lock:
        assert broken_conn not in db._all_conns
        assert broken_conn not in db._conn_owners

    db.close()


# ==============================================================================
# BUG-WIN-057: Bounded Shutdown & Process Termination on Failed Flush
# ==============================================================================

def test_bug_win_057_finalize_process_terminates_on_failed_flush():
    """When shutting down without restart and durable state flush fails (e.g. WAL flush failed),
    finalize_process must flush logs and invoke terminate to prevent process hangs."""
    calls = []
    failed_result = {"durable_flushed": False, "remaining_workers": ()}

    finalized = finalize_process(
        shutdown=lambda: failed_result,
        flush_logs=lambda: calls.append("logs"),
        terminate=lambda code: calls.append(("terminate", code)),
        restart=None,
        exit_code=0
    )

    # Must have flushed logs and terminated with non-zero exit code
    assert finalized is False
    assert "logs" in calls
    assert ("terminate", 1) in calls


def test_bug_win_057_finalize_process_withholds_restart_on_failed_flush():
    """When restart callback is provided and durable flush fails,
    finalize_process must NOT invoke restart callback."""
    calls = []
    failed_result = {"durable_flushed": False, "remaining_workers": ()}

    finalized = finalize_process(
        shutdown=lambda: failed_result,
        flush_logs=lambda: calls.append("logs"),
        terminate=lambda code: calls.append(("terminate", code)),
        restart=lambda: calls.append("restart"),
        exit_code=3
    )

    assert finalized is False
    assert "restart" not in calls
    assert "terminate" not in [c[0] if isinstance(c, tuple) else c for c in calls]


# ==============================================================================
# AUDIT 1B REPAIRS & VERIFICATION TESTS
# ==============================================================================

def test_bug_win_026_search_albums_does_not_match_track_title(tmp_path):
    """search_albums must only match album or artist, never matching track title."""
    db_path = str(tmp_path / "album_search_test.db")
    db = DatabaseManager(db_path)
    try:
        db.add_track(
            title="Bohemian Rhapsody",
            artist="Queen",
            album="A Night at the Opera",
            source="local",
            file_path="queen_bohemian.mp3"
        )

        # Searching for track title must NOT return the album
        albums_by_title = db.search_albums("Bohemian")
        assert len(albums_by_title) == 0

        # Searching for album name words must return the album
        albums_by_album = db.search_albums("Opera")
        assert len(albums_by_album) == 1
        assert albums_by_album[0]["title"] == "A Night at the Opera"

        # Searching for artist must return the album
        albums_by_artist = db.search_albums("Queen")
        assert len(albums_by_artist) == 1
        assert albums_by_artist[0]["title"] == "A Night at the Opera"
    finally:
        db.close()


def test_bug_win_026_search_special_characters_and_punctuation(tmp_path):
    """Punctuation, symbols and underscores in searches must fall back to LIKE cleanly."""
    db_path = str(tmp_path / "spec_chars_test.db")
    db = DatabaseManager(db_path)
    try:
        db.add_track(title="Thunderstruck", artist="AC/DC", album="The Razors Edge", source="local", file_path="acdc1.mp3")
        db.add_track(title="Sweet Child O' Mine", artist="Guns N' Roses", album="Appetite for Destruction", source="local", file_path="gnr1.mp3")
        db.add_track(title="Track_100%", artist="Artist_Special", album="Album_100%", source="local", file_path="spec1.mp3")

        # AC/DC search
        artists = db.search_artists("AC/DC")
        assert len(artists) == 1
        assert artists[0]["artist"] == "AC/DC"

        # Guns N' Roses search
        artists = db.search_artists("Guns N'")
        assert len(artists) == 1
        assert artists[0]["artist"] == "Guns N' Roses"

        # Underscore & percent literal search
        tracks = db.search_tracks("Track_100%")
        assert len(tracks) == 1
        assert tracks[0]["title"] == "Track_100%"

        albums = db.search_albums("Album_100%")
        assert len(albums) == 1
        assert albums[0]["title"] == "Album_100%"
    finally:
        db.close()


def test_bug_win_005_corrupted_database_truncate_fallback(tmp_path, monkeypatch):
    """When os.replace fails due to Windows sharing violation/permission error,
    _recover_corrupted_database must fall back to copy2 and truncation."""
    db_path = str(tmp_path / "corrupted_truncate_test.db")
    with open(db_path, "wb") as f:
        f.write(b"CORRUPTED_RAW_GARBAGE_BYTES_54321")

    # Mock os.replace to raise PermissionError
    orig_replace = os.replace
    def failing_replace(src, dst):
        if str(src) == db_path:
            raise PermissionError("[WinError 32] File in use by another process")
        return orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)

    db = DatabaseManager(db_path)
    try:
        # Check that db is now valid and writable
        tid = db.add_track(title="Recovered Song", artist="Artist", source="local", file_path="test_rec.mp3")
        assert tid > 0

        # Backup file must have been created via copy2
        backups = glob.glob(f"{db_path}.corrupted.*")
        assert len(backups) >= 1
        with open(backups[0], "rb") as f:
            assert f.read() == b"CORRUPTED_RAW_GARBAGE_BYTES_54321"
    finally:
        db.close()
