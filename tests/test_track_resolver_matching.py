"""Metadata resolution must not select a same-title song by another artist."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.track_resolver import TrackResolver


@pytest.fixture(params=["manager", "raw_tuple", "raw_row"])
def local_db(request, tmp_db):
    if request.param == "manager":
        yield tmp_db, tmp_db.add_track
        return

    conn = sqlite3.connect(":memory:")
    if request.param == "raw_row":
        conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY, title TEXT, artist TEXT, cover_url TEXT,
            cover_path TEXT, source TEXT, source_id TEXT, source_url TEXT,
            duration REAL, file_path TEXT
        )
    """)

    def add_track(title, artist="Unknown Artist", **fields):
        values = {
            "title": title, "artist": artist, "source": "local", "duration": 0,
            "cover_url": None, "cover_path": None, "source_id": None,
            "source_url": None, "file_path": None,
            **fields,
        }
        columns = list(values)
        cursor = conn.execute(
            f"INSERT INTO tracks ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [values[column] for column in columns],
        )
        conn.commit()
        return cursor.lastrowid

    try:
        yield conn, add_track
    finally:
        conn.close()


def test_known_artist_rejects_title_only_row_by_another_artist(local_db):
    db, add = local_db
    add("Hello", artist="Adele", file_path="C:/library/adele.mp3")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Hello", "Lionel Richie") is None


def test_matching_local_row_keeps_database_id_and_file_path(local_db):
    db, add = local_db
    add("Hello", artist="Adele", file_path="C:/library/adele.mp3")
    wanted_id = add(
        "Hello", artist="Lionel Richie", duration=249,
        file_path="C:/library/lionel.mp3", cover_path="C:/library/lionel.jpg",
    )
    resolver = TrackResolver(db=db)

    result = resolver._search_local("hello", "LIONEL RICHIE")
    assert result["id"] == wanted_id
    assert result["source"] == "local"
    assert result["source_id"] == str(wanted_id)
    assert result["file_path"] == "C:/library/lionel.mp3"
    assert result["source_url"] == "C:/library/lionel.mp3"
    assert result["cover_url"] == "C:/library/lionel.jpg"
    assert result["duration"] == 249


def test_unknown_artist_legacy_row_still_matches_by_title(local_db):
    db, add = local_db
    legacy_id = add("Hello", artist="Unknown Artist", file_path="C:/library/legacy.mp3")
    resolver = TrackResolver(db=db)

    result = resolver._search_local("Hello", "Lionel Richie")
    assert result["id"] == legacy_id
    assert result["file_path"] == "C:/library/legacy.mp3"


def test_known_matching_artist_is_preferred_over_earlier_legacy_row(local_db):
    db, add = local_db
    add("Hello", artist="Unknown Artist", file_path="C:/library/legacy.mp3")
    wanted_id = add("Hello", artist="Lionel Richie", file_path="C:/library/lionel.mp3")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Hello", "Lionel Richie")["id"] == wanted_id


def test_punctuation_in_known_artist_can_match_a_plausible_same_title_row(local_db):
    db, add = local_db
    wanted_id = add("Thunderstruck", artist="AC/DC", file_path="C:/library/acdc.mp3")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Thunderstruck", "AC DC")["id"] == wanted_id


def test_missing_requested_artist_keeps_title_only_lookup(local_db):
    db, add = local_db
    wanted_id = add("Hello", artist="Adele")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Hello", "")["id"] == wanted_id
    assert resolver._search_local("Hello", "Unknown Artist")["id"] == wanted_id


def test_empty_stored_artist_does_not_bypass_known_artist_check(local_db):
    db, add = local_db
    add("Hello", artist="")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Hello", "Lionel Richie") is None


def test_rejected_local_row_falls_through_to_matching_provider(local_db):
    db, add = local_db
    add("Hello", artist="Adele", file_path="C:/library/adele.mp3")
    provider_hit = {
        "source": "soundcloud", "source_id": "123", "title": "Hello",
        "artist": "Lionel Richie", "duration": 249,
    }
    sc = SimpleNamespace(search=Mock(side_effect=lambda query, **kwargs: kwargs["callback"]([provider_hit])))
    yt = SimpleNamespace(search=Mock(side_effect=AssertionError("SoundCloud match should stop fallback")))
    resolver = TrackResolver(db=db, soundcloud_service=sc, youtube_service=yt)

    result = resolver.resolve_track("Hello", "Lionel Richie")
    assert result["source"] == "soundcloud"
    assert result["source_id"] == "123"
    assert result["artist"] == "Lionel Richie"
    yt.search.assert_not_called()


def test_existing_downloaded_provider_row_keeps_its_original_identity(local_db):
    db, add = local_db
    wanted_id = add(
        "Hello", artist="Lionel Richie", source="youtube", source_id="dQw4w9WgXcQ",
        source_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        file_path="C:/library/download.mp3",
    )
    resolver = TrackResolver(db=db)

    result = resolver._search_local("Hello", "Lionel Richie")
    assert result["id"] == wanted_id
    assert result["source"] == "youtube"
    assert result["source_id"] == "dQw4w9WgXcQ"
    assert result["file_path"] == "C:/library/download.mp3"


def test_wrong_title_or_empty_title_does_not_select_local_row(local_db):
    db, add = local_db
    add("Hello", artist="Lionel Richie")
    resolver = TrackResolver(db=db)

    assert resolver._search_local("Goodbye", "Lionel Richie") is None
    assert resolver._search_local("", "Lionel Richie") is None
