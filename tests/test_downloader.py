"""DownloadManager tests: queue dedup, batch accounting, worker outcomes.

Workers run synchronously via ``_download_worker`` with a stub provider
and ``~`` redirected, so no network and no real home directory are touched.
"""

import os


def test_queue_download_returns_bool_and_dedups(downloader, tmp_db):
    assert downloader.queue_download(1, "youtube", "v1") is True
    # Same track twice -> rejected (DB UNIQUE + in-memory dedup).
    assert downloader.queue_download(1, "youtube", "v1") is False


def test_batch_dedup_shrinks_total(downloader, emitted):
    downloader.start_batch(2)
    downloader._decrement_batch_total_for_dedup()
    assert downloader._batch_total == 1
    downloader._on_batch_task_done(7, success=True)
    kinds = [e for e, _ in emitted]
    assert "batch_download_progress" in kinds
    assert "batch_download_finished" in kinds
    finished = [d for e, d in emitted if e == "batch_download_finished"][-1]
    assert finished["failed"] == 0


def test_batch_counts_failures(downloader, emitted):
    downloader.start_batch(2)
    downloader._on_batch_task_done(1, success=True)
    downloader._on_batch_task_done(2, success=False)
    finished = [d for e, d in emitted if e == "batch_download_finished"][-1]
    assert finished["completed"] == 2
    assert finished["failed"] == 1


def test_cancel_batch_cancels_futures(downloader):
    downloader.start_batch(5)
    downloader.queue_download(21, "youtube", "v21")
    downloader.cancel_batch()
    assert downloader._batch_active is False
    assert downloader._queue == []


def _run_worker(downloader, tmp_db, track_id, source, source_id):
    tmp_db.download_queue_add(track_id, source, source_id)
    downloader._download_worker(
        {"track_id": track_id, "source": source, "source_id": source_id}
    )


def test_worker_youtube_success(downloader, tmp_db, emitted, redirect_home):
    tid = tmp_db.add_track(title="Y", artist="A", source="youtube", source_id="vy1")
    _run_worker(downloader, tmp_db, tid, "youtube", "vy1")
    row = tmp_db.get_track(tid)
    assert row["is_downloaded"] == 1
    assert row["file_path"] and os.path.exists(row["file_path"])
    assert str(row["file_path"]).startswith(str(redirect_home))
    kinds = [e for e, _ in emitted]
    assert "download_complete" in kinds
    assert "download_failed" not in kinds


def test_worker_failure_emits_download_failed(downloader, tmp_db, emitted,
                                              redirect_home, youtube_stub):
    youtube_stub.fail = True
    tid = tmp_db.add_track(title="B", artist="A", source="youtube", source_id="vb1")
    _run_worker(downloader, tmp_db, tid, "youtube", "vb1")
    row = tmp_db.get_track(tid)
    assert row["is_downloaded"] == 0
    failed = [d for e, d in emitted if e == "download_failed"]
    assert len(failed) == 1
    assert failed[0]["track_id"] == tid


def test_worker_spotify_ytsearch_resolves_via_youtube(downloader, tmp_db, emitted,
                                                     redirect_home, youtube_stub):
    tid = tmp_db.add_track(title="S", artist="A", source="spotify",
                           source_id="ytsearch1: A - S")
    _run_worker(downloader, tmp_db, tid, "spotify", "ytsearch1: A - S")
    row = tmp_db.get_track(tid)
    assert row["is_downloaded"] == 1
    assert row["source"] == "spotify"  # provider preserved, not overwritten
    assert youtube_stub.calls, "spotify must fall back to the youtube provider"
    assert youtube_stub.calls[0][0] == "ytsearch1: A - S"
    assert "download_failed" not in [e for e, _ in emitted]


def test_worker_unsupported_source_fails_loudly(downloader, tmp_db, emitted,
                                               redirect_home):
    tid = tmp_db.add_track(title="V", artist="A", source="vk", source_id="vk1")
    _run_worker(downloader, tmp_db, tid, "vk", "vk1")
    failed = [d for e, d in emitted if e == "download_failed"]
    assert len(failed) == 1
    assert tmp_db.download_queue_get_status(tid) == "failed"
