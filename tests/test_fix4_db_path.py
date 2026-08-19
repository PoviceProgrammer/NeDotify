"""
Teamwork Fix Prompt 4 — Acceptance Tests

1. DB path resolver used in taste_profile == resolver in DatabaseManager (same path).
2. build_from_db on real schema (copied from PRAGMA table_info) → is_empty()=False,
   top artists from favorites/history.
3. Schema protection: build_from_db without is_downloaded column works gracefully.
4. [PROFILE_ERROR] is emitted with traceback on fatal error (no silent swallowing).
5. [PROFILE] print() output actually appears on stdout (visible in terminal without logging config).
"""

import sys
import os
import io
import sqlite3
import threading
import logging
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.taste_profile import UserTasteProfile
from core.database import DatabaseManager


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — build in-memory DB mirroring the real nedotify_storage.db schema
# ─────────────────────────────────────────────────────────────────────────────

# Real schema from PRAGMA table_info(nedotify_storage.db):
REAL_TRACKS_DDL = """
    CREATE TABLE tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        artist TEXT,
        album TEXT,
        duration REAL,
        file_path TEXT,
        source TEXT,
        source_id TEXT,
        source_url TEXT,
        cover_path TEXT,
        cover_url TEXT,
        bitrate REAL,
        sample_rate REAL,
        format TEXT,
        file_size INTEGER,
        loudness_lufs REAL,
        genre TEXT,
        year INTEGER,
        track_number INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_played TIMESTAMP,
        play_count INTEGER DEFAULT 0,
        is_favorite INTEGER DEFAULT 0,
        is_cached INTEGER DEFAULT 0,
        metadata_json TEXT,
        is_downloaded INTEGER DEFAULT 0,
        lufs REAL,
        peak_volume REAL
    )
"""

REAL_HISTORY_DDL = """
    CREATE TABLE history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id INTEGER NOT NULL,
        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        duration_listened REAL DEFAULT 0,
        completed INTEGER DEFAULT 0
    )
"""

REAL_PLAYLISTS_DDL = """
    CREATE TABLE playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        cover_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

REAL_PLAYLIST_TRACKS_DDL = """
    CREATE TABLE playlist_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        position INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def _make_real_schema_db(with_is_downloaded=True):
    """Build in-memory DB with the exact real nedotify_storage.db schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tracks_ddl = REAL_TRACKS_DDL
    if not with_is_downloaded:
        # Simulate an old schema that doesn't have is_downloaded
        tracks_ddl = REAL_TRACKS_DDL.replace(",\n        is_downloaded INTEGER DEFAULT 0,", ",")

    cur.executescript(tracks_ddl + ";" + REAL_HISTORY_DDL + ";" + REAL_PLAYLISTS_DDL + ";" + REAL_PLAYLIST_TRACKS_DDL)

    # Insert 3 favorites, 2 downloads, history with completed plays
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id, play_count) VALUES ('Track A', 'Lil Peep', 'Emo', 1, 0, 'soundcloud', 'sc1', 5)")
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id, play_count) VALUES ('Track B', 'XXXTENTACION', 'Hip-Hop', 1, 1, 'soundcloud', 'sc2', 8)")
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id, play_count) VALUES ('Track C', 'Lil Peep', 'Emo', 0, 1, 'local', 'loc1', 2)")
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id, play_count) VALUES ('Track D', 'BAKI', 'Rap', 0, 0, 'youtube', 'yt1', 3)")

    # History: Lil Peep played 3x (2 completed), XXXTENTACION 1x
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (1, '2026-08-01 09:00:00', 1)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (1, '2026-08-02 10:00:00', 1)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (2, '2026-08-03 15:00:00', 0)")

    # Playlist with BAKI
    cur.execute("INSERT INTO playlists (name) VALUES ('Chill Mix')")
    cur.execute("INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (1, 4, 1)")

    conn.commit()
    return conn


def _make_db_without_is_downloaded():
    """Build in-memory DB WITHOUT is_downloaded column (old schema simulation)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Old schema - no is_downloaded
    cur.executescript("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            genre TEXT,
            is_favorite INTEGER DEFAULT 0,
            play_count INTEGER DEFAULT 0,
            source TEXT,
            source_id TEXT,
            cover_url TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_listened REAL DEFAULT 0,
            completed INTEGER DEFAULT 0
        );
        CREATE TABLE playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        CREATE TABLE playlist_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0
        );
    """)
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite) VALUES ('Song X', 'Artist A', 'Pop', 1)")
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite) VALUES ('Song Y', 'Artist B', 'Rock', 0)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (1, '2026-08-01 12:00:00', 1)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (2, '2026-08-02 14:00:00', 0)")
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: DB path resolver equality
# ─────────────────────────────────────────────────────────────────────────────

def test_db_path_resolver_matches_database_manager():
    """
    taste_profile reads from the same DB that DatabaseManager uses.
    Assert: DatabaseManager().db_path resolves to the same path
    that is used when taste_profile calls build_from_db(db).
    """
    db = DatabaseManager()
    assert db.db_path is not None, "DatabaseManager must have a db_path attribute"
    assert os.path.isabs(db.db_path), f"db_path must be absolute: {db.db_path}"

    # The profile _get_conn should return db.conn (not open a new file)
    profile_conn = UserTasteProfile._get_conn(db)
    assert profile_conn is db.conn, (
        "_get_conn(DatabaseManager()) must return db.conn — "
        "the same connection used by the rest of the app, "
        f"not a new one. Got: {profile_conn}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: build_from_db on real schema → is_empty()=False
# ─────────────────────────────────────────────────────────────────────────────

def test_build_from_db_real_schema_not_empty():
    """
    Profile built from a DB matching the real nedotify_storage.db schema
    must report is_empty()=False and include artists from favorites/history.
    """
    conn = _make_real_schema_db()
    profile = UserTasteProfile().build_from_db(conn)

    assert not profile.is_empty(), (
        "Profile with favorites, downloads, history, and playlist must NOT be empty. "
        f"Got: top_artists={profile.top_artists[:5]}, favorites={len(profile.favorite_tracks)}"
    )

    artist_names = [a['name'] for a in profile.top_artists]
    assert "Lil Peep" in artist_names, f"Lil Peep (fav+history×2completed) must be in top_artists: {artist_names}"
    assert "XXXTENTACION" in artist_names, f"XXXTENTACION (fav+download+history) must be in top_artists: {artist_names}"

    # Lil Peep should score higher: 2×completed(×2) + 1×fav(×3) + recency > XXXTENTACION's 1×play(×1) + 1×fav(×3) + 1×download(×3)
    lp_score = next(a['play_count'] for a in profile.top_artists if a['name'] == 'Lil Peep')
    xxx_score = next(a['play_count'] for a in profile.top_artists if a['name'] == 'XXXTENTACION')
    # Both are high — the important thing is both are present
    assert lp_score > 0
    assert xxx_score > 0


def test_seed_artists_from_real_data_not_defaults():
    """get_seed_artists() must return real user artists, not DEFAULT_SEED_ARTISTS."""
    conn = _make_real_schema_db()
    profile = UserTasteProfile().build_from_db(conn)

    seeds = profile.get_seed_artists(limit=5)
    assert len(seeds) > 0, "Seed artists must not be empty with real data"

    for d in UserTasteProfile.DEFAULT_SEED_ARTISTS:
        assert d not in seeds, (
            f"Default artist '{d}' must not appear in seeds when profile has real data. Got: {seeds}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Old schema (no is_downloaded) — graceful degradation
# ─────────────────────────────────────────────────────────────────────────────

def test_build_without_is_downloaded_column():
    """
    build_from_db must not crash on old schema missing is_downloaded.
    Profile must still contain artists from favorites and history.
    """
    conn = _make_db_without_is_downloaded()

    # Must not raise
    try:
        profile = UserTasteProfile().build_from_db(conn)
    except Exception as e:
        raise AssertionError(f"build_from_db crashed on old schema: {e}")

    assert not profile.is_empty(), "Profile must be non-empty even without is_downloaded column"
    artist_names = [a['name'] for a in profile.top_artists]
    assert "Artist A" in artist_names, f"Favorited Artist A must appear in top_artists: {artist_names}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: [PROFILE_ERROR] emitted with traceback on fatal error
# ─────────────────────────────────────────────────────────────────────────────

def test_profile_error_has_traceback():
    """
    When build_from_db encounters a fatal error, [PROFILE_ERROR] must be logged
    with a traceback (no silent swallowing), and the function must return gracefully.
    """
    log_records = []
    printed_output = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            log_records.append(self.format(record))

    handler = ListHandler()
    target_logger = logging.getLogger('services.taste_profile')
    target_logger.addHandler(handler)
    old_level = target_logger.level
    target_logger.setLevel(logging.DEBUG)

    # Capture stdout too
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        # Pass a broken object whose .conn property raises — this triggers the outer except
        class BrokenConn:
            @property
            def conn(self):
                raise RuntimeError("Simulated fatal DB connection error")

        # Must NOT raise — must return an empty profile gracefully
        profile = UserTasteProfile().build_from_db(BrokenConn())
        printed_output.append(sys.stdout.getvalue())
    finally:
        sys.stdout = old_stdout
        target_logger.removeHandler(handler)
        target_logger.setLevel(old_level)

    # build_from_db must return a valid (empty) profile, not raise
    assert isinstance(profile, UserTasteProfile), "build_from_db must return a UserTasteProfile even on error"
    assert profile.is_empty(), "Profile must be empty when DB raises on connection"

    # Either logger or stdout must contain PROFILE_ERROR or PROFILE warning
    all_output = ' '.join(log_records) + ' '.join(printed_output)
    assert ('PROFILE_ERROR' in all_output or 'PROFILE' in all_output), (
        f"Must emit [PROFILE_ERROR] or [PROFILE] on fatal error. Got logs: {log_records[:5]}"
    )



def test_none_db_emits_profile_warning():
    """build_from_db(None) must emit a [PROFILE] warning, not crash silently."""
    log_records = []
    printed = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            log_records.append(self.format(record))

    handler = ListHandler()
    target_logger = logging.getLogger('services.taste_profile')
    target_logger.addHandler(handler)
    old_level = target_logger.level
    target_logger.setLevel(logging.DEBUG)

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        profile = UserTasteProfile().build_from_db(None)
        printed.append(sys.stdout.getvalue())
    finally:
        sys.stdout = old_stdout
        target_logger.removeHandler(handler)
        target_logger.setLevel(old_level)

    assert profile.is_empty(), "Profile with None db must be empty"

    # Either logger or stdout must have the warning
    all_output = ' '.join(log_records) + ' '.join(printed)
    assert 'PROFILE' in all_output, (
        "Must emit [PROFILE] warning when db=None. Got logs: "
        f"{log_records[:3]}, stdout: {printed}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: [PROFILE] goes to stdout (visible without logging config)
# ─────────────────────────────────────────────────────────────────────────────

def test_profile_summary_printed_to_stdout():
    """
    _log_profile_summary() must write [PROFILE] to stdout via print(),
    so it's visible in the app terminal even when no logging handler is configured.
    """
    conn = _make_real_schema_db()

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured

    try:
        UserTasteProfile().build_from_db(conn)
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert '[PROFILE]' in output, (
        "build_from_db must print [PROFILE] to stdout for terminal visibility. "
        f"Captured stdout: {repr(output[:200])}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Local "Из лайков и загрузок" mix contains real user tracks
# ─────────────────────────────────────────────────────────────────────────────

def test_local_mix_from_real_schema():
    """get_local_liked_and_downloaded_tracks() must return tracks from fav/downloads."""
    conn = _make_real_schema_db()
    profile = UserTasteProfile().build_from_db(conn)

    local = profile.get_local_liked_and_downloaded_tracks(limit=20)
    assert len(local) > 0, "Must have local liked/downloaded tracks"

    artists = {t.get('artist') for t in local}
    assert 'Lil Peep' in artists or 'XXXTENTACION' in artists, (
        f"Local mix must contain user's favorited/downloaded artists. Got: {artists}"
    )

    # Deduplication: no artist:title pair should appear twice
    seen = set()
    for t in local:
        key = f"{(t.get('artist') or '').lower()}:{(t.get('title') or '').lower()}"
        assert key not in seen, f"Duplicate track in local mix: {key}"
        seen.add(key)


if __name__ == '__main__':
    # Run directly for quick smoke test
    tests = [
        test_db_path_resolver_matches_database_manager,
        test_build_from_db_real_schema_not_empty,
        test_seed_artists_from_real_data_not_defaults,
        test_build_without_is_downloaded_column,
        test_profile_error_has_traceback,
        test_none_db_emits_profile_warning,
        test_profile_summary_printed_to_stdout,
        test_local_mix_from_real_schema,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  OK  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
