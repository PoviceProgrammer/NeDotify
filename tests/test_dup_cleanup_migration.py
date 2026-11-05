"""Regression tests for the P0-01 duplicate-cleanup migration (data safety).

The old startup migration DELETed every track row that was not the MIN(id) of
its (LOWER(title), LOWER(artist)) group and let ON DELETE CASCADE take the
rows' history rows, playlist entries, play count, favourite flag and file
reference with it. The block logged at DEBUG (below the production level), the
transaction was committed by an unconditional conn.commit(), and the desktop
has no backup feature: a track, its listening history and its playlist
membership were destroyed silently and irreversibly.

These tests pin the replacement:

  * no distinct recording is deleted (same title/artist but a different album,
    source, source_id, file_path, spelling or an unknown artist all survive);
  * a true duplicate is MERGED, not dropped: its payload moves into the
    survivor, its history rows and playlist entries are re-pointed at the
    survivor, and only the emptied row is removed;
  * every history row is still present afterwards;
  * every surviving track is still in its playlists - including the track that
    the old second statement could strip;
  * the operation is snapshotted, atomic, idempotent and logged by name.

Every test builds its own throwaway SQLite file. The real ~/.nedotify library
is never opened.
"""

import inspect
import logging
import os

import pytest

from core.database import (
    DatabaseManager,
    TRACK_IDENTITY_SQL,
    TRACK_RECORDING_COLUMNS,
    name_is_meaningful,
)


# --- helpers ------------------------------------------------------------------

def _make_db(path, rows=(), playlists=(), history=(), playlist_tracks=(), legacy_flag=None):
    """A throwaway database that looks like a pre-b6a6553 library.

    The schema is the current one, but the de-duplication migration has never
    run: no versioned record and no ``migration_dup_cleanup_done`` row. That is
    exactly the state of a library written by a build that predates the
    destructive migration.

    ``legacy_flag`` puts the library into the other state: the destructive
    cleanup already ran there (the flag carries its old value '1').
    """
    db = DatabaseManager(str(path))
    cursor = db.conn.cursor()
    for row in rows:
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cursor.execute(
            "INSERT INTO tracks ({}) VALUES ({})".format(columns, placeholders),
            tuple(row.values()),
        )
    for name in playlists:
        cursor.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
    for track_id in history:
        cursor.execute("INSERT INTO history (track_id, played_at) VALUES (?, CURRENT_TIMESTAMP)", (track_id,))
    for playlist_id, track_id in playlist_tracks:
        cursor.execute(
            "INSERT INTO playlist_tracks (playlist_id, track_id) VALUES (?, ?)",
            (playlist_id, track_id),
        )
    # A pre-b6a6553 library carries neither the versioned migration record nor
    # the one-shot flag.
    cursor.execute("DELETE FROM schema_migrations")
    cursor.execute("DELETE FROM settings WHERE key = ?", (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG,))
    if legacy_flag is not None:
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?, ?, 'system')",
            (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG, legacy_flag),
        )
    db.conn.commit()
    db.close()
    return str(path)


def _open(path):
    return DatabaseManager(str(path))


def _rows(db, sql, params=()):
    return [dict(row) for row in db.conn.execute(sql, params).fetchall()]


def _track(**overrides):
    row = {
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "source": "youtube",
        "source_id": "vid1",
        "file_path": None,
        "play_count": 0,
        "is_favorite": 0,
    }
    row.update(overrides)
    return row


def _migration_record(db, version):
    row = db.conn.execute(
        "SELECT version FROM schema_migrations WHERE version = ?", (version,)
    ).fetchone()
    return row is not None


# --- the acceptance criteria --------------------------------------------------

def test_same_title_artist_different_album_survives(tmp_path):
    """A different album is a different recording: it must not be touched."""
    path = _make_db(tmp_path / "a.db", rows=[
        _track(album="Album One"),
        _track(album="Album Two"),
    ])
    db = _open(path)
    try:
        titles = sorted((r["title"], r["album"]) for r in _rows(db, "SELECT title, album FROM tracks"))
        assert titles == [("Song", "Album One"), ("Song", "Album Two")]
    finally:
        db.close()


def test_same_title_artist_different_source_survives(tmp_path):
    """A different provider is a different recording."""
    path = _make_db(tmp_path / "b.db", rows=[
        _track(source="youtube", source_id="vid1"),
        _track(source="local", source_id=None),
    ])
    db = _open(path)
    try:
        sources = sorted(r["source"] for r in _rows(db, "SELECT source FROM tracks"))
        assert sources == ["local", "youtube"]
    finally:
        db.close()


def test_same_title_artist_different_source_id_survives(tmp_path):
    """Two different provider tracks with the same title are two recordings."""
    path = _make_db(tmp_path / "c.db", rows=[
        _track(source_id="vid1"),
        _track(source_id="vid2"),
    ])
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2
    finally:
        db.close()


def test_same_title_artist_different_file_path_survives(tmp_path):
    """Two different files are two different recordings: neither file may be
    orphaned by the migration."""
    path = _make_db(tmp_path / "d.db", rows=[
        _track(file_path="C:/music/one.mp3"),
        _track(file_path="C:/music/two.mp3"),
    ])
    db = _open(path)
    try:
        files = sorted(r["file_path"] for r in _rows(db, "SELECT file_path FROM tracks"))
        assert files == ["C:/music/one.mp3", "C:/music/two.mp3"]
    finally:
        db.close()


def test_same_title_artist_different_case_survives(tmp_path):
    """A different spelling is not a proof that the rows are the same
    recording, so the rows stay."""
    path = _make_db(tmp_path / "e.db", rows=[
        _track(title="Song", artist="Artist"),
        _track(title="song", artist="artist"),
    ])
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2
    finally:
        db.close()


def test_null_artist_rows_survive(tmp_path):
    """An unknown artist carries no identity: such a row is never collapsed."""
    path = _make_db(tmp_path / "f.db", rows=[
        _track(artist=None),
        _track(artist=None),
    ])
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2
    finally:
        db.close()


def test_placeholder_names_are_never_collapsed(tmp_path):
    """The creation path refuses to de-duplicate placeholder names; the
    migration must use the same guard."""
    path = _make_db(tmp_path / "g.db", rows=[
        _track(title="Unknown Title", artist="Unknown Artist"),
        _track(title="Unknown Title", artist="Unknown Artist"),
    ])
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2
    finally:
        db.close()


def test_true_duplicate_is_merged_not_dropped(tmp_path):
    """The duplicate is merged into the survivor: one row, and the survivor
    carries the payload of both."""
    path = _make_db(tmp_path / "h.db", rows=[
        _track(play_count=3, is_favorite=0, last_played="2026-01-01 10:00:00"),
        _track(play_count=5, is_favorite=1, last_played="2026-02-02 11:00:00"),
    ])
    db = _open(path)
    try:
        tracks = _rows(db, "SELECT * FROM tracks")
        assert len(tracks) == 1
        survivor = tracks[0]
        assert survivor["play_count"] == 8
        assert survivor["is_favorite"] == 1
        assert survivor["last_played"] == "2026-02-02 11:00:00"
        # the merge is recorded, so the corrective migration can undo it
        merges = _rows(db, "SELECT * FROM track_merges")
        assert len(merges) == 1
        assert merges[0]["duplicate_id"] != merges[0]["survivor_id"]
    finally:
        db.close()


def test_history_row_of_a_duplicate_is_still_present(tmp_path):
    """A history row must never lose its track."""
    path = _make_db(
        tmp_path / "i.db",
        rows=[_track(), _track()],
        history=[2],
    )
    db = _open(path)
    try:
        history = _rows(db, "SELECT id, track_id FROM history")
        assert len(history) == 1, "the history row was destroyed"
        # and it still resolves to a track that exists
        assert _rows(db, "SELECT id FROM tracks WHERE id = ?", (history[0]["track_id"],))
    finally:
        db.close()


def test_duplicate_stays_in_its_playlist(tmp_path):
    """A track that is in a playlist is still in that playlist afterwards."""
    path = _make_db(
        tmp_path / "j.db",
        rows=[_track(), _track()],
        playlists=["Mix"],
        playlist_tracks=[(1, 1), (1, 2)],
    )
    db = _open(path)
    try:
        entries = _rows(db, "SELECT playlist_id, track_id FROM playlist_tracks")
        assert entries, "the playlist lost every entry"
        assert {e["track_id"] for e in entries} <= {
            r["id"] for r in _rows(db, "SELECT id FROM tracks")
        }
    finally:
        db.close()


def test_surviving_track_keeps_its_playlist_entry(tmp_path):
    """The old second statement removed the playlist entry of a track that
    SURVIVED the migration (arbiter reproduction #2). That must not happen."""
    path = _make_db(
        tmp_path / "k.db",
        rows=[
            _track(title="Song", artist="Artist", source_id="vid1"),
            _track(title="song", artist="artist", source_id="vid2"),
        ],
        playlists=["Mix"],
        playlist_tracks=[(1, 1), (1, 2)],
    )
    db = _open(path)
    try:
        entries = _rows(db, "SELECT playlist_id, track_id FROM playlist_tracks")
        assert len(entries) == 2, "a surviving track lost its playlist entry"
        assert {e["track_id"] for e in entries} == {1, 2}
    finally:
        db.close()


def test_no_distinct_recording_is_deleted(tmp_path):
    """The whole synthetic library: every distinct recording comes out."""
    rows = [
        _track(album="Album One"),
        _track(album="Album Two"),
        _track(source="local", source_id=None, file_path="C:/music/one.mp3"),
        _track(source="local", source_id=None, file_path="C:/music/two.mp3"),
        _track(title="song", artist="artist"),
        _track(artist=None),
        _track(artist=None),
    ]
    path = _make_db(tmp_path / "l.db", rows=rows, playlists=["Mix"], playlist_tracks=[(1, i) for i in range(1, 8)])
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == len(rows)
    finally:
        db.close()


# --- the operation ------------------------------------------------------------

def test_snapshot_is_taken_before_the_merge(tmp_path):
    """A snapshot of the library is kept, and the corrective migration can
    restore a retired row from it."""
    path = _make_db(tmp_path / "m.db", rows=[_track(), _track()])
    db = _open(path)
    try:
        backup = _rows(db, "SELECT * FROM tracks_backup")
        assert len(backup) == 2, "the snapshot does not hold the pre-merge rows"
        # A stable one-shot copy sits next to the database. Keeping one named
        # snapshot avoids accumulating a full database copy on every startup.
        snapshot = f"{path}.{DatabaseManager.DUP_CLEANUP_VERSION}.snapshot.db"
        assert os.path.isfile(snapshot), "no file snapshot was written"
    finally:
        db.close()


def test_merge_fails_closed_when_snapshot_cannot_be_written(tmp_path, caplog):
    path = _make_db(tmp_path / "snapshot-blocked.db", rows=[_track(), _track()])
    blocked_snapshot = f"{path}.{DatabaseManager.DUP_CLEANUP_VERSION}.snapshot.db"
    os.mkdir(blocked_snapshot)  # VACUUM INTO cannot replace a directory.

    with caplog.at_level(logging.ERROR, logger="core.database"):
        db = _open(path)
        try:
            assert len(_rows(db, "SELECT id FROM tracks")) == 2
            assert not _migration_record(db, DatabaseManager.DUP_CLEANUP_VERSION)
            assert db.conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG,),
            ).fetchone() is None
        finally:
            db.close()

    assert any("refusing to merge because file snapshot" in record.getMessage()
               for record in caplog.records)
    os.rmdir(blocked_snapshot)


def test_log_names_what_was_touched(tmp_path, caplog):
    """The operation is visible: a WARNING names what it touched."""
    path = _make_db(tmp_path / "n.db", rows=[_track(), _track()])
    with caplog.at_level(logging.WARNING, logger="core.database"):
        db = _open(path)
        try:
            pass
        finally:
            db.close()
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert messages, "the migration logged nothing at WARNING or above"
    assert any("merged" in m and "history" in m for m in messages), messages


def test_the_migration_is_atomic(tmp_path, monkeypatch):
    """A failure inside the block leaves the library untouched and the
    migration runs again on the next start."""
    path = _make_db(
        tmp_path / "o.db",
        rows=[_track(), _track()],
        history=[2],
        playlists=["Mix"],
        playlist_tracks=[(1, 2)],
    )

    boom = {"count": 0}
    original = DatabaseManager._merge_track_row_into

    def exploding(self, cursor, survivor, duplicate, stats, columns=None):
        boom["count"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(DatabaseManager, "_merge_track_row_into", exploding)
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2, "a half-migrated library"
        assert len(_rows(db, "SELECT id FROM history")) == 1
        assert len(_rows(db, "SELECT id FROM playlist_tracks")) == 1
        assert not _migration_record(db, DatabaseManager.DUP_CLEANUP_VERSION), (
            "the versioned record was written although the migration failed"
        )
    finally:
        db.close()

    # the next start runs the migration again - and now it succeeds
    monkeypatch.setattr(DatabaseManager, "_merge_track_row_into", original)
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 1
        assert len(_rows(db, "SELECT id FROM history")) == 1
        assert _migration_record(db, DatabaseManager.DUP_CLEANUP_VERSION)
    finally:
        db.close()


def test_the_flag_is_written_only_after_a_successful_commit(tmp_path, monkeypatch):
    """The one-shot key is written inside the transaction, so a failure cannot
    leave the flag set."""
    path = _make_db(tmp_path / "p.db", rows=[_track(), _track()])

    def exploding(self, cursor):
        raise RuntimeError("boom")

    monkeypatch.setattr(DatabaseManager, "_apply_track_merges", exploding)
    db = _open(path)
    try:
        row = db.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG,)
        ).fetchone()
        assert row is None, "the flag was written although the migration failed"
    finally:
        db.close()


def test_fresh_database_is_a_noop(tmp_path):
    """A fresh library is not touched at all."""
    path = str(tmp_path / "q.db")
    db = _open(path)
    try:
        assert _rows(db, "SELECT id FROM tracks") == []
        assert _rows(db, "SELECT id FROM history") == []
        assert _rows(db, "SELECT id FROM playlist_tracks") == []
        assert not [n for n in os.listdir(tmp_path) if ".dup-cleanup-" in n], (
            "an empty library was snapshotted"
        )
    finally:
        db.close()


def test_database_with_the_legacy_flag_is_left_alone(tmp_path):
    """A library that already ran the destructive cleanup is not touched
    again: the damage is done, and there is nothing this build can undo."""
    path = _make_db(tmp_path / "r.db", rows=[_track(), _track()], legacy_flag="1")
    db = _open(path)
    try:
        assert len(_rows(db, "SELECT id FROM tracks")) == 2, "the library was touched"
        row = db.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG,)
        ).fetchone()
        assert row["value"] == "1", "the historical flag was overwritten"
    finally:
        db.close()


def test_the_migration_is_idempotent(tmp_path):
    """Running it twice changes nothing the second time."""
    path = _make_db(tmp_path / "s.db", rows=[_track(), _track()])
    db = _open(path)
    try:
        first = _rows(db, "SELECT * FROM tracks")
        assert len(first) == 1
    finally:
        db.close()

    db = _open(path)
    try:
        assert len(_rows(db, "SELECT * FROM tracks")) == 1
        assert len(_rows(db, "SELECT * FROM track_merges")) == 1
    finally:
        db.close()


def test_an_old_schema_without_the_newer_columns_is_migrated(tmp_path):
    """A library written by an old build does not have every column the merge
    writes (the lufs columns are added by a later ALTER). The migration must
    not fail on such a library - otherwise it would retry on every start."""
    import sqlite3

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tracks (
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
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_played TIMESTAMP,
            play_count INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            is_cached INTEGER DEFAULT 0,
            metadata_json TEXT
        );
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_listened REAL DEFAULT 0,
            completed INTEGER DEFAULT 0
        );
        CREATE TABLE playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            cover_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE playlist_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            category TEXT DEFAULT 'general',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for _ in range(2):
        conn.execute(
            "INSERT INTO tracks (title, artist, album, source, source_id, play_count) "
            "VALUES ('Song', 'Artist', 'Album', 'youtube', 'vid1', 2)"
        )
    conn.execute("INSERT INTO history (track_id) VALUES (2)")
    conn.commit()
    conn.close()

    db = _open(path)
    try:
        tracks = _rows(db, "SELECT * FROM tracks")
        assert len(tracks) == 1, "the old library was not merged"
        assert tracks[0]["play_count"] == 4
        assert len(_rows(db, "SELECT id FROM history")) == 1
    finally:
        db.close()


def test_creation_path_and_migration_share_the_identity_key():
    """The creation path and the migration must use the SAME identity
    expression - otherwise the migration would clean up rows the app
    considers different, or the other way round (P0-01)."""
    source = inspect.getsource(DatabaseManager.add_track)
    assert "TRACK_IDENTITY_SQL" in source, (
        "add_track no longer uses the shared identity expression"
    )
    assert "LOWER(title)" in TRACK_IDENTITY_SQL
    assert "LOWER(artist)" in TRACK_IDENTITY_SQL
    # the migration groups by the same columns
    plan_source = inspect.getsource(DatabaseManager._plan_track_merges)
    assert "LOWER(title)" in plan_source and "LOWER(artist)" in plan_source
    # and the recording refinement covers the columns that tell two
    # recordings apart
    for column in ("album", "source", "source_id", "file_path"):
        assert column in TRACK_RECORDING_COLUMNS


def test_the_creation_path_agrees_with_the_merged_survivor(tmp_path):
    """After the merge the creation path must return the survivor - the two
    sides of the identity agree."""
    path = _make_db(tmp_path / "t.db", rows=[_track(), _track()])
    db = _open(path)
    try:
        survivor = _rows(db, "SELECT id FROM tracks")[0]
        assert db.add_track(title="Song", artist="Artist", album="Album",
                            source="youtube", source_id="vid1") == survivor["id"]
    finally:
        db.close()


def test_name_guard_is_shared():
    """The placeholder guard is one definition, used by both paths."""
    assert name_is_meaningful("Song", "Artist") is True
    assert name_is_meaningful("Unknown Title", "Unknown Artist") is False
    assert name_is_meaningful(None, "Artist") is False
    # an unknown artist carries no identity either - the creation path has
    # always refused to de-duplicate such a row, and so does the migration
    assert name_is_meaningful("Song", None) is False
    source = inspect.getsource(DatabaseManager.add_track)
    assert "name_is_meaningful(title, artist)" in source


# --- the corrective migration -------------------------------------------------

def test_corrective_migration_restores_a_retired_row(tmp_path):
    """The corrective migration restores a row a previous merge retired, from
    the snapshot - and the row's history and playlist entries follow it back."""
    path = _make_db(
        tmp_path / "u.db",
        rows=[_track(), _track()],
        history=[2],
        playlists=["Mix"],
        playlist_tracks=[(1, 2)],
    )
    db = _open(path)
    try:
        merges = _rows(db, "SELECT * FROM track_merges")
        assert len(merges) == 1
        duplicate_id = merges[0]["duplicate_id"]
    finally:
        db.close()

    # pretend the merge was an older version and re-run the corrective step
    db = _open(path)
    try:
        db.conn.execute("UPDATE track_merges SET merged_by = 'dup_cleanup_v1'")
        db.conn.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (DatabaseManager.DUP_CLEANUP_RESTORE_VERSION,),
        )
        db.conn.commit()
    finally:
        db.close()

    db = _open(path)
    try:
        restored = _rows(db, "SELECT id FROM tracks WHERE id = ?", (duplicate_id,))
        assert restored, "the retired row was not restored"
        history = _rows(db, "SELECT track_id FROM history")
        assert history[0]["track_id"] == duplicate_id, (
            "the history row was not moved back to the restored track"
        )
    finally:
        db.close()


def test_corrective_migration_does_not_resurrect_a_deleted_track(tmp_path):
    """A track the user deleted after the migration ran is not brought back."""
    path = _make_db(tmp_path / "v.db", rows=[_track(), _track()])
    db = _open(path)
    try:
        survivor = _rows(db, "SELECT id FROM tracks")[0]["id"]
        # the user deletes the surviving track after the migration
        db.delete_track(survivor)
        db.conn.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (DatabaseManager.DUP_CLEANUP_RESTORE_VERSION,),
        )
        db.conn.commit()
    finally:
        db.close()

    db = _open(path)
    try:
        assert _rows(db, "SELECT id FROM tracks WHERE id = ?", (survivor,)) == []
    finally:
        db.close()


def test_legacy_damage_is_reported_plainly(tmp_path, caplog):
    """A library that ran the destructive cleanup is told, in the log, that
    the loss is not recoverable - and is pointed at the re-scan."""
    path = _make_db(tmp_path / "w.db", rows=[_track()], legacy_flag="1")

    with caplog.at_level(logging.ERROR, logger="core.database"):
        db = _open(path)
        try:
            pass
        finally:
            db.close()
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert messages, "the legacy damage was not reported"
    text = " ".join(messages).lower()
    assert "not recoverable" in text or "cannot be restored" in text, messages
    assert "re-scan" in text, messages


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
