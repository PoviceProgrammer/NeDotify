"""Atomicity and idempotency tests for DatabaseManager.import_playlist_atomic."""

import sqlite3

import pytest


def _playlist_tracks(prefix="batch"):
    return [
        {"source": "youtube", "source_id": f"{prefix}-one", "title": "One", "artist": "Artist"},
        {"source": "youtube", "source_id": f"{prefix}-fail", "title": "Fail", "artist": "Artist"},
    ]


@pytest.mark.parametrize("existing", [False, True])
def test_playlist_import_rolls_back_tracks_and_memberships_on_mid_batch_failure(tmp_db, existing):
    playlist_name = "Existing" if existing else "Must Roll Back"
    before_members = set()
    if existing:
        playlist_id = tmp_db.create_playlist(playlist_name)
        baseline_id = tmp_db.add_track("Baseline", "Artist", source="youtube", source_id="baseline")
        tmp_db.add_tracks_to_playlist(playlist_id, [baseline_id])
        before_members = {row[0] for row in tmp_db.conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=?", (playlist_id,)
        )}

    with tmp_db.conn:
        tmp_db.conn.execute("""
            CREATE TRIGGER fail_atomic_playlist_track
            BEFORE INSERT ON tracks WHEN NEW.source_id LIKE '%-fail'
            BEGIN SELECT RAISE(ABORT, 'injected playlist import failure'); END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="injected playlist import failure"):
        tmp_db.import_playlist_atomic(playlist_name, "imported", _playlist_tracks())

    playlist = next((item for item in tmp_db.get_playlists() if item["name"] == playlist_name), None)
    if existing:
        assert playlist is not None
        members = {row[0] for row in tmp_db.conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=?", (playlist_id,)
        )}
        assert members == before_members
    else:
        assert playlist is None, "new playlist survived a rolled-back import"
    assert tmp_db.get_track_by_source_id("youtube", "batch-one") is None
    assert tmp_db.get_track_by_source_id("youtube", "batch-fail") is None


def test_playlist_import_is_idempotent_for_existing_tracks_and_members(tmp_db):
    playlist_id, imported = tmp_db.import_playlist_atomic("Import", "first", _playlist_tracks("ok"))
    assert imported == 2
    same_id, imported_again = tmp_db.import_playlist_atomic("import", "ignored", _playlist_tracks("ok"))
    assert same_id == playlist_id
    assert imported_again == 0
    assert tmp_db.get_playlist_track_count(playlist_id) == 2
    assert tmp_db.conn.execute("SELECT COUNT(*) FROM tracks WHERE source_id LIKE 'ok-%'").fetchone()[0] == 2


@pytest.mark.parametrize("tracks", [[], [{}], [{"source_id": "bad", "duration": float("inf")}], [{"source_id": "x", "duration": -1}]])
def test_playlist_import_rejects_invalid_batch_before_writing(tmp_db, tracks):
    with pytest.raises(ValueError):
        tmp_db.import_playlist_atomic("Bad", "", tracks)
    assert not any(item["name"] == "Bad" for item in tmp_db.get_playlists())
    assert tmp_db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 0
