"""DatabaseManager tests: tracks dedup, download flags, download queue."""

import os


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


def test_download_queue_add_is_unique(tmp_db):
    assert tmp_db.download_queue_add(11, "youtube", "vid11") is True
    assert tmp_db.download_queue_add(11, "youtube", "vid11") is False


def test_download_queue_status_roundtrip(tmp_db):
    tmp_db.download_queue_add(12, "soundcloud", "sc12")
    tmp_db.download_queue_set_status(12, "downloading")
    assert tmp_db.download_queue_get_status(12) == "downloading"
    tmp_db.download_queue_set_status(12, "completed")
    assert tmp_db.download_queue_get_status(12) == "completed"
