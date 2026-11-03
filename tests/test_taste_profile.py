"""Local recommendation signals stay fresh and reflect actual engagement."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from services.taste_profile import UserTasteProfile


def _track(db, title, artist, **kwargs):
    return db.add_track(title, artist=artist, source="youtube", source_id=title, duration=200, **kwargs)


def test_new_like_and_unlike_refresh_profile_immediately(tmp_db):
    tid = _track(tmp_db, "Song", "Artist")
    assert UserTasteProfile().build_from_db(tmp_db).is_empty()

    tmp_db.toggle_favorite(tid)
    liked = UserTasteProfile().build_from_db(tmp_db)
    assert liked.get_seed_artists() == ["Artist"]
    assert liked.get_seed_tracks()[0]["id"] == tid

    tmp_db.toggle_favorite(tid)
    assert UserTasteProfile().build_from_db(tmp_db).is_empty()


def test_history_update_and_library_signals_refresh_cached_profile(tmp_db, tmp_path):
    tid = _track(tmp_db, "Song", "Artist")
    history_id = tmp_db.add_to_history(tid, duration_listened=1)
    first = UserTasteProfile().build_from_db(tmp_db)
    first_score = first.top_artists[0]["play_count"]

    tmp_db.update_history_duration(history_id, 200, completed=True)
    completed = UserTasteProfile().build_from_db(tmp_db)
    assert completed.top_artists[0]["play_count"] > first_score

    file_path = str(tmp_path / "song.mp3")
    tmp_db.mark_track_downloaded(tid, file_path)
    downloaded = UserTasteProfile().build_from_db(tmp_db)
    assert downloaded.downloaded_tracks[0]["file_path"] == file_path
    assert downloaded.top_artists[0]["play_count"] > completed.top_artists[0]["play_count"]

    playlist_id = tmp_db.create_playlist("Mix")
    tmp_db.add_to_playlist(playlist_id, tid)
    assert UserTasteProfile().build_from_db(tmp_db).playlist_tracks[0]["id"] == tid


def test_commit_on_another_connection_refreshes_cached_profile(tmp_db):
    tid = _track(tmp_db, "Song", "Artist")
    assert UserTasteProfile().build_from_db(tmp_db).is_empty()

    with sqlite3.connect(tmp_db.db_path) as other:
        other.execute("UPDATE tracks SET is_favorite = 1 WHERE id = ?", (tid,))

    assert UserTasteProfile().build_from_db(tmp_db).get_seed_artists() == ["Artist"]


def test_quick_skips_do_not_outweigh_completed_listens_or_likes(tmp_db):
    skipped = _track(tmp_db, "Audition", "Skipped")
    completed = _track(tmp_db, "Full song", "Enjoyed")
    liked = _track(tmp_db, "Favorite", "Liked")
    for _ in range(12):
        tmp_db.add_to_history(skipped, duration_listened=1)
    tmp_db.add_to_history(completed, duration_listened=200, completed=True)
    tmp_db.toggle_favorite(liked)

    profile = UserTasteProfile().build_from_db(tmp_db)
    assert profile.get_seed_artists() == ["Liked", "Enjoyed", "Skipped"]
    assert [track["id"] for track in profile.get_seed_tracks()] == [liked, completed, skipped]


def test_recent_history_is_unique_but_taste_scores_keep_each_play(tmp_db):
    tid = _track(tmp_db, "Repeated song", "Repeat artist")
    tmp_db.add_to_history(tid, duration_listened=200, completed=True)
    tmp_db.add_to_history(tid, duration_listened=200, completed=True)

    profile = UserTasteProfile().build_from_db(tmp_db)

    assert len(profile.recent_history) == 1
    recent = profile.recent_history[0]
    assert recent["id"] == recent["track_id"] == tid
    assert recent["play_count"] == 2
    assert recent["duration_listened"] == 400
    assert recent["completed"] == 1
    assert profile.top_artists[0]["name"] == "Repeat artist"
    assert profile.top_artists[0]["play_count"] > 3.9


def test_local_imports_without_engagement_are_not_seed_tracks(tmp_db, tmp_path):
    for index in range(25):
        tmp_db.add_track(f"Import {index}", artist="Imported", file_path=str(tmp_path / f"{index}.mp3"))
    listened = _track(tmp_db, "Actual favorite", "Enjoyed")
    tmp_db.add_to_history(listened, duration_listened=200, completed=True)

    profile = UserTasteProfile().build_from_db(tmp_db)
    assert profile.get_seed_artists() == ["Enjoyed"]
    assert [track["id"] for track in profile.top_tracks] == [listened]
    assert profile.downloaded_tracks == []


def test_artist_case_and_whitespace_variants_merge(tmp_db):
    first = _track(tmp_db, "First", " PHARAOH  ")
    second = _track(tmp_db, "Second", "pharaoh")
    for tid in (first, second):
        tmp_db.toggle_favorite(tid)

    profile = UserTasteProfile().build_from_db(tmp_db)
    assert len(profile.top_artists) == 1
    assert profile.top_artists[0]["name"].casefold() == "pharaoh"
    assert profile.top_artists[0]["play_count"] == 6


def test_recent_engagement_outranks_old_history(tmp_db):
    old = _track(tmp_db, "Old", "Old artist")
    recent = _track(tmp_db, "Recent", "Recent artist")
    old_history = tmp_db.add_to_history(old, duration_listened=200, completed=True)
    tmp_db.add_to_history(recent, duration_listened=200, completed=True)
    with tmp_db.conn:
        tmp_db.conn.execute("UPDATE history SET played_at = ? WHERE id = ?", (
            (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(), old_history,
        ))

    assert UserTasteProfile().build_from_db(tmp_db).get_seed_tracks()[0]["id"] == recent


def test_timezone_aware_history_does_not_abort_profile(tmp_db):
    tid = _track(tmp_db, "UTC track", "Artist")
    history_id = tmp_db.add_to_history(tid, duration_listened=200, completed=True)
    with tmp_db.conn:
        tmp_db.conn.execute("UPDATE history SET played_at = ? WHERE id = ?", (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), history_id,
        ))

    profile = UserTasteProfile().build_from_db(tmp_db)
    assert profile.get_seed_artists() == ["Artist"]
    assert profile.get_seed_tracks()[0]["id"] == tid


def test_mutating_a_returned_track_does_not_pollute_cached_profile(tmp_db):
    tid = _track(tmp_db, "Actual title", "Artist")
    tmp_db.toggle_favorite(tid)
    first = UserTasteProfile().build_from_db(tmp_db)
    first.favorite_tracks[0]["title"] = "Mutated"
    first.top_tracks[0]["title"] = "Mutated"

    again = UserTasteProfile().build_from_db(tmp_db)
    assert again.favorite_tracks[0]["title"] == "Actual title"
    assert again.top_tracks[0]["title"] == "Actual title"


def test_unchanged_profile_reuses_cache_without_reading_all_signals(tmp_db):
    tid = _track(tmp_db, "Song", "Artist")
    tmp_db.toggle_favorite(tid)
    first = UserTasteProfile().build_from_db(tmp_db)
    statements = []
    tmp_db.conn.set_trace_callback(statements.append)
    try:
        again = UserTasteProfile().build_from_db(tmp_db)
    finally:
        tmp_db.conn.set_trace_callback(None)
    assert again.to_dict() == first.to_dict()
    assert not any(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def test_legacy_tuple_connection_uses_actual_projection_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE tracks (id INTEGER PRIMARY KEY, title TEXT, artist TEXT,
            source TEXT, source_id TEXT, file_path TEXT, is_favorite INTEGER,
            play_count INTEGER);
        CREATE TABLE history (track_id INTEGER, played_at TEXT, completed INTEGER,
            duration_listened REAL);
        INSERT INTO tracks VALUES (1, 'Song', 'Artist', 'local', 'one', 'C:/song.mp3', 1, 0);
    """)
    try:
        profile = UserTasteProfile().build_from_db(conn)
        assert profile.favorite_tracks[0]["artist"] == "Artist"
        assert profile.favorite_tracks[0]["file_path"] == "C:/song.mp3"
        assert profile.get_seed_tracks()[0]["source"] == "local"
    finally:
        conn.close()


def test_recent_history_compatibility_fallback_deduplicates_and_keeps_latest_flags():
    rows = [
        {"id": 7, "title": "Song", "played_at": "2026-10-22T12:00:00",
         "completed": 1, "duration_listened": 180},
        {"id": 7, "title": "Song", "played_at": "2026-10-22T11:00:00",
         "completed": 0, "duration_listened": 20},
    ]

    recent = UserTasteProfile._recent_history_fallback(rows)

    assert len(recent) == 1
    assert recent[0]["id"] == recent[0]["track_id"] == 7
    assert recent[0]["played_at"] == "2026-10-22T12:00:00"
    assert recent[0]["completed"] == 1
    assert recent[0]["play_count"] == 2
    assert recent[0]["duration_listened"] == 200
    assert recent[0]["latest_duration_listened"] == 180


@pytest.mark.parametrize("row,expected", [
    ({"duration": 200, "duration_listened": 170, "completed": False}, 1.0),
    ({"duration": 200, "duration_listened": 200, "completed": False}, 1.0),
    ({"duration": 200, "duration_listened": 80, "completed": False}, 1.0),
    ({"duration": 0, "duration_listened": 0, "completed": False}, 1.0),
])
def test_partial_and_unknown_listens_keep_established_weights(row, expected):
    assert UserTasteProfile._listening_weight(row) == expected
