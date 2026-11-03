"""Copied desktop databases retain a stable identity for Android imports."""

import uuid

from core.database import DatabaseManager


def test_library_identity_survives_changes_reopen_and_copy(tmp_path):
    path = tmp_path / "library.db"
    db = DatabaseManager(str(path))
    identity = db.get_setting("portable_library_id")
    assert str(uuid.UUID(identity)) == identity
    track = db.add_track(title="Song", artist="Artist")
    db.delete_track(track)
    # SQLite's backup API copies committed WAL contents as well.
    import sqlite3
    with sqlite3.connect(str(tmp_path / "copy.db")) as target:
        db.conn.backup(target)
    db.close()
    for candidate in (path, tmp_path / "copy.db"):
        reopened = DatabaseManager(str(candidate))
        try:
            assert reopened.get_setting("portable_library_id") == identity
        finally:
            reopened.close()


def test_independent_libraries_have_different_identities(tmp_path):
    left = DatabaseManager(str(tmp_path / "left.db"))
    right = DatabaseManager(str(tmp_path / "right.db"))
    try:
        assert left.get_setting("portable_library_id") != right.get_setting("portable_library_id")
    finally:
        left.close()
        right.close()
