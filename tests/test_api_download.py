"""AppApi download surface: return contracts, failure signals, offline filter."""

import pytest

from core.api import AppApi
from core.downloader import DownloadManager


@pytest.fixture
def wired(core_ns):
    """Api + DownloadManager attached to the same fake core (no workers)."""
    api = AppApi(core_ns)
    dm = DownloadManager(core_ns)
    dm._running = False
    dm._queue_event.set()
    core_ns.downloader = dm
    events = []
    api._emit = lambda name, data=None: events.append((name, data))
    yield api, dm, events
    try:
        dm.stop()
    except Exception:
        pass


def test_download_track_queues_and_returns_true(wired, tmp_db):
    api, dm, events = wired
    ok = api.download_track({"title": "T", "artist": "A",
                             "source": "youtube", "source_id": "vid1"})
    assert ok is True


def test_download_track_duplicate_returns_false(wired):
    api, dm, events = wired
    payload = {"title": "T", "artist": "A",
               "source": "youtube", "source_id": "vid1"}
    assert api.download_track(payload) is True
    assert api.download_track(payload) is False


def test_download_track_missing_source_id_fails_loudly(wired, tmp_db):
    api, dm, events = wired
    ok = api.download_track({"id": 987654, "title": "X", "artist": "Y",
                             "source": "youtube"})
    assert ok is False
    failed = [d for e, d in events if e == "download_failed"]
    assert len(failed) == 1
    assert failed[0]["track_id"] == 987654


def test_download_track_invalid_payload(wired):
    api, dm, events = wired
    assert api.download_track(None) is False
    assert api.download_track("not-a-dict") is False


def test_get_downloaded_tracks_filters_missing_files(wired, tmp_db, tmp_path):
    api, dm, events = wired
    real = tmp_path / "keep.mp3"
    real.write_bytes(b"ID3data")
    tid_keep = tmp_db.add_track(title="Keep", artist="A", source="youtube",
                                source_id="k1")
    tmp_db.mark_track_downloaded(tid_keep, str(real))
    tid_gone = tmp_db.add_track(title="Gone", artist="A", source="youtube",
                                source_id="g1")
    tmp_db.mark_track_downloaded(tid_gone, str(tmp_path / "gone.mp3"))
    tracks = api.get_downloaded_tracks()
    ids = [t["id"] for t in tracks]
    assert tid_keep in ids
    assert tid_gone not in ids
