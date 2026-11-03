"""DatabaseManager tests: tracks dedup, download flags, download queue."""

import os
import pytest
from core.database import HISTORY_EVENT_WINDOW


def test_add_track_dedups_by_source(tmp_db):
    a = tmp_db.add_track(title="Song", artist="Art", source="youtube", source_id="vid1")
    b = tmp_db.add_track(title="Song", artist="Art", source="youtube", source_id="vid1")
    assert a == b
    # Same title/artist without a source_id falls back to title/artist dedup.
    c = tmp_db.add_track(title="Song", artist="Art", source="youtube", source_id="vid2")
    assert c == a
    d = tmp_db.add_track(title="Other", artist="Art", source="youtube", source_id="vid3")
    assert d != a


def test_mark_downloaded_and_filter(tmp_db, tmp_path):
    real = tmp_path / "real.mp3"
    real.write_bytes(b"ID3data")
    tid = tmp_db.add_track(title="Dl", artist="A", source="youtube", source_id="v9")
    tmp_db.mark_track_downloaded(tid, str(real))
    row = tmp_db.get_track(tid)
    assert row["is_downloaded"] == 1
    assert row["file_path"] == str(real)
    assert row["source"] == "youtube"  # source provider preserved


def test_mark_downloaded_refuses_a_path_owned_by_another_track(tmp_db, tmp_path):
    first = tmp_db.add_track("First", artist="A", source="youtube", source_id="first")
    second = tmp_db.add_track("Second", artist="B", source="youtube", source_id="second")
    path = tmp_path / "download.mp3"
    path.write_bytes(b"placeholder")
    tmp_db.mark_track_downloaded(first, str(path))

    with pytest.raises(ValueError, match="already assigned"):
        tmp_db.mark_track_downloaded(second, str(path))

    assert tmp_db.get_track(first)["file_path"] == str(path)
    assert tmp_db.get_track(second)["file_path"] is None
    assert tmp_db.get_track(second)["is_downloaded"] == 0


def test_download_queue_add_is_unique(tmp_db):
    tmp_db.conn.execute("INSERT INTO tracks(id,title) VALUES(11,'Queue')")
    tmp_db.conn.commit()
    assert tmp_db.download_queue_add(11, "youtube", "vid11") is True
    assert tmp_db.download_queue_add(11, "youtube", "vid11") is False


def test_download_queue_status_roundtrip(tmp_db):
    tmp_db.conn.execute("INSERT INTO tracks(id,title) VALUES(12,'Queue')")
    tmp_db.conn.commit()
    tmp_db.download_queue_add(12, "soundcloud", "sc12")
    tmp_db.download_queue_set_status(12, "downloading")
    assert tmp_db.download_queue_get_status(12) == "downloading"
    tmp_db.download_queue_set_status(12, "completed")
    assert tmp_db.download_queue_get_status(12) == "completed"


def test_cancel_download_queue_is_one_bulk_update_and_clears_resume_state(tmp_db):
    tmp_db.conn.execute("ALTER TABLE download_queue ADD COLUMN resume_on_restart INTEGER NOT NULL DEFAULT 0")
    with tmp_db.conn:
        for track_id, status in ((21, "pending"), (22, "downloading"), (23, "completed")):
            tmp_db.conn.execute("INSERT INTO tracks(id,title) VALUES (?,?)", (track_id, f"T{track_id}"))
            tmp_db.conn.execute(
                "INSERT INTO download_queue(track_id,status,resume_on_restart) VALUES (?,?,1)",
                (track_id, status),
            )
    statements = []
    tmp_db.conn.set_trace_callback(statements.append)
    tmp_db.download_queue_cancel_pending()
    tmp_db.conn.set_trace_callback(None)

    updates = [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE DOWNLOAD_QUEUE")]
    assert len(updates) == 1
    rows = tmp_db.conn.execute(
        "SELECT track_id,status,resume_on_restart FROM download_queue ORDER BY track_id"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        (21, "cancelled", 0), (22, "cancelled", 0), (23, "completed", 1),
    ]


def test_get_history_bounds_rows_and_clamps_nonpositive_limits(tmp_db):
    old_id = tmp_db.add_track("Old only", "Artist", source="local", file_path="old.mp3")
    recent_id = tmp_db.add_track("Recent repeat", "Artist", source="local", file_path="recent.mp3")
    with tmp_db.conn:
        tmp_db.conn.execute(
            "INSERT INTO history(track_id,played_at,duration_listened) VALUES (?,?,?)",
            (old_id, "2000-01-01 00:00:00", 30),
        )
        tmp_db.conn.executemany(
            "INSERT INTO history(track_id,played_at,duration_listened) VALUES (?,?,?)",
            [(recent_id, "2026-01-01 00:00:00", 1)] * HISTORY_EVENT_WINDOW,
        )

    assert tmp_db.get_history(-1) == []
    assert tmp_db.get_history(0) == []
    rows = tmp_db.get_history(10_000)
    assert len(rows) == 1
    assert rows[0]["track_id"] == recent_id
    assert rows[0]["play_count"] == HISTORY_EVENT_WINDOW
    assert rows[0]["duration_listened"] == HISTORY_EVENT_WINDOW


def test_search_tracks_punctuation_uses_literal_like_matching(tmp_db):
    slash = tmp_db.add_track("AC/DC", "Band", source="local", file_path="ac-dc.mp3")
    underscore = tmp_db.add_track("AC_DC", "Band", source="local", file_path="ac_dc.mp3")

    underscore_rows = tmp_db.search_tracks("AC_DC")
    slash_rows = tmp_db.search_tracks("AC/DC")

    assert [row["id"] for row in underscore_rows] == [underscore]
    assert [row["id"] for row in slash_rows] == [slash]
