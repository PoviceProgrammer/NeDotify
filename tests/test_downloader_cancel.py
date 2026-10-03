"""DownloadManager cancellation, backpressure and shutdown tests.

Covers the cooperative-cancel contract of ``core/downloader.py``:

* ``cancel_batch()`` really stops queued downloads instead of only pretending
  (the pool cannot cancel work it already accepted, so workers abort by epoch),
* the batch progress bar always terminates with exactly one event,
* an uncancelled batch still completes normally,
* ``stop()`` gives in-flight workers a bounded window before the DB is closed.

Providers are local stubs and ``~`` is redirected, so no network and no real
home directory are touched.
"""

import os
import threading
import time

import pytest

try:
    from core.downloader import _MAX_INFLIGHT
except ImportError:  # keeps the module importable against the pre-fix downloader
    _MAX_INFLIGHT = 2  # the pool width the old code hard-coded


class _GatedStub:
    """Provider stub that blocks inside ``download_audio_sync`` until released.

    Lets a test observe exactly how many downloads the pool started and when.
    """

    def __init__(self):
        self.calls = []
        self.finished = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def download_audio_sync(self, source_id, download_dir):
        with self._lock:
            self.calls.append(source_id)
            n = len(self.calls)
        self.release.wait(timeout=10)
        os.makedirs(download_dir, exist_ok=True)
        fp = os.path.join(download_dir, "gated_%d.mp3" % n)
        with open(fp, "wb") as f:
            f.write(b"ID3\x00\x01gated-audio")
        with self._lock:
            self.finished += 1
        return fp

    @property
    def started(self):
        with self._lock:
            return len(self.calls)


class _NoDownloadYouTube:
    """YouTube stub that records lookups and refuses to produce a file."""

    def __init__(self):
        self.queries = []
        self.downloads = []

    def search_sync(self, query, limit=1):
        self.queries.append(query)
        return []

    def download_audio_sync(self, source_id, download_dir):
        self.downloads.append(source_id)
        raise RuntimeError("stub provider failure")


def _wait_until(predicate, timeout=5.0, what=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError("timed out waiting for: %s" % what)


def _start_processor(dm):
    """Run the real queue processor thread.

    The ``downloader`` fixture halts the processor by setting ``_running=False``,
    which normally makes its thread exit, so a fresh one is started here (after
    checking that the old one is really gone, otherwise it would be reused).
    """
    dm._running = True
    if dm._processor_thread.is_alive():
        dm._queue_event.set()
        return
    dm._processor_thread = threading.Thread(target=dm._process_queue, daemon=True)
    dm._processor_thread.start()
    dm._queue_event.set()


def _inflight(dm):
    with dm._futures_lock:
        return [f for f in dm._futures if not f.done()]


def _add_tracks(tmp_db, count, source="youtube", prefix="v"):
    ids = []
    for i in range(count):
        tid = tmp_db.add_track(title="T%d" % i, artist="A", source=source,
                              source_id="%s%d" % (prefix, i))
        ids.append(tid)
    return ids


def test_cancel_batch_stops_already_queued_downloads(downloader, core_ns, tmp_db,
                                                     emitted, redirect_home):
    """No download may start once cancel_batch() returned (cooperative cancel).

    Would fail before the fix: ``Future.cancel()`` returns False for work the
    pool already accepted, so the remaining 4 tasks kept downloading and marked
    their tracks as downloaded after the user was told the batch was cancelled.
    """
    stub = _GatedStub()
    core_ns.youtube = stub
    _start_processor(downloader)
    ids = _add_tracks(tmp_db, 6)
    downloader.start_batch(len(ids))
    for tid in ids:
        assert downloader.queue_download(tid, "youtube", "v%d" % tid) is True
    try:
        _wait_until(lambda: stub.started >= _MAX_INFLIGHT, 5, "workers inside provider")
        # Backpressure: the queue is not drained into the pool in one go.
        assert len(_inflight(downloader)) <= _MAX_INFLIGHT

        downloader.cancel_batch()
        started_before_release = stub.started

        stub.release.set()
        _wait_until(lambda: not downloader._queue and not _inflight(downloader), 10,
                    "queue drained after cancel")

        assert stub.started == started_before_release, "downloads started after the cancel"
        for tid in ids:
            assert tmp_db.get_track(tid)["is_downloaded"] == 0
            assert tmp_db.download_queue_get_status(tid) == "cancelled"
    finally:
        stub.release.set()


def test_full_cancel_terminates_batch_progress_exactly_once(downloader, core_ns, tmp_db,
                                                            emitted, redirect_home):
    """A cancelled batch emits exactly one terminator and no progress leftovers.

    ``batch_download_cancelled`` stays the single progress terminator (the web
    frontend listens for it, see ui/web_new_v2/js/library.js), so no
    ``batch_download_finished`` may follow from the aborted workers.
    """
    stub = _GatedStub()
    core_ns.youtube = stub
    _start_processor(downloader)
    ids = _add_tracks(tmp_db, 3)
    downloader.start_batch(len(ids))
    for tid in ids:
        downloader.queue_download(tid, "youtube", "v%d" % tid)
    try:
        _wait_until(lambda: stub.started >= _MAX_INFLIGHT, 5, "workers inside provider")
        downloader.cancel_batch()
        assert downloader.cancel_batch.__doc__  # payload contract documented
        stub.release.set()
        _wait_until(lambda: not downloader._queue and not _inflight(downloader), 10,
                    "queue drained after cancel")
    finally:
        stub.release.set()

    kinds = [e for e, _ in emitted]
    assert kinds.count("batch_download_cancelled") == 1
    assert kinds.count("batch_download_finished") == 0
    assert "batch_download_progress" not in kinds
    payload = [d for e, d in emitted if e == "batch_download_cancelled"][0]
    assert payload is True, "frontend contract: payload stays the literal True"


def test_stale_task_aborts_without_emitting_download_complete(downloader, tmp_db,
                                                              youtube_stub, emitted,
                                                              redirect_home):
    """A task queued before the cancel aborts even when the pool runs it later.

    Deterministic (no processor thread): the item keeps the epoch it was queued
    with, so it aborts at the very first stage check.
    """
    downloader.start_batch(2)
    assert downloader.queue_download(1, "youtube", "v1") is True
    with downloader._queue_lock:
        stale_item = downloader._queue.pop(0)
    downloader.cancel_batch()

    downloader._download_worker(stale_item)

    kinds = [e for e, _ in emitted]
    assert youtube_stub.calls == [], "cancelled task must not call the provider"
    assert "download_complete" not in kinds
    assert kinds.count("batch_download_finished") == 0
    assert tmp_db.download_queue_get_status(1) == "cancelled"


def test_download_queued_after_cancel_runs_normally(downloader, tmp_db, youtube_stub,
                                                     emitted, redirect_home):
    """The cancel epoch must not poison later downloads (no stuck global flag)."""
    old_id, new_id = _add_tracks(tmp_db, 2)
    downloader.start_batch(1)
    downloader.queue_download(old_id, "youtube", "old")
    downloader.cancel_batch()

    assert downloader.queue_download(new_id, "youtube", "vnew") is True
    downloader._download_worker(downloader._queue.pop(0))

    assert youtube_stub.calls, "the post-cancel task must download"
    assert tmp_db.get_track(new_id)["is_downloaded"] == 1
    assert tmp_db.download_queue_get_status(old_id) == "cancelled"
    assert "download_complete" in [e for e, _ in emitted]


def test_uncancelled_batch_completes_once(downloader, core_ns, tmp_db, emitted,
                                          redirect_home):
    """Regression guard: a normal batch still runs to a single finished event."""
    stub = _GatedStub()
    core_ns.youtube = stub
    stub.release.set()  # no gating: the whole batch can stream through
    _start_processor(downloader)
    ids = _add_tracks(tmp_db, 4)
    downloader.start_batch(len(ids))
    for tid in ids:
        downloader.queue_download(tid, "youtube", "v%d" % tid)

    _wait_until(lambda: [e for e, _ in emitted].count("batch_download_finished") == 1,
                20, "batch finished")
    time.sleep(0.2)  # let any stray late event show up

    kinds = [e for e, _ in emitted]
    assert kinds.count("batch_download_finished") == 1
    finished = [d for e, d in emitted if e == "batch_download_finished"][0]
    assert finished["completed"] == len(ids)
    assert finished["failed"] == 0
    assert len(stub.calls) == len(ids)
    for tid in ids:
        assert tmp_db.get_track(tid)["is_downloaded"] == 1
        assert tmp_db.download_queue_get_status(tid) == "completed"


def test_stop_waits_for_inflight_worker(downloader, core_ns, tmp_db, redirect_home):
    """stop() must not return while a worker still needs the database.

    core/app.py::cleanup calls downloader.stop() and then db.close(), so a
    worker still running at that point writes into a closed connection. The
    worker aborts at its next stage check (stop() bumps the epoch), which is
    only observable once stop() has waited for it.
    """
    stub = _GatedStub()
    core_ns.youtube = stub
    _start_processor(downloader)
    tid = _add_tracks(tmp_db, 1)[0]
    downloader.queue_download(tid, "youtube", "v0")
    try:
        _wait_until(lambda: stub.started == 1, 5, "worker inside provider")

        stopper = threading.Thread(target=downloader.stop)
        stopper.start()
        time.sleep(0.3)
        assert stopper.is_alive(), "stop() must wait for the in-flight download"

        stub.release.set()
        stopper.join(10)
        assert not stopper.is_alive(), "stop() did not return"
        assert stub.finished == 1, "worker must have finished before stop() returned"
        assert tmp_db.download_queue_get_status(tid) == "cancelled"
    finally:
        stub.release.set()


def test_stop_is_idle_without_inflight_work(downloader, tmp_db):
    """stop() stays cheap (no artificial delay) when nothing is downloading."""
    start = time.monotonic()
    downloader.stop()
    assert time.monotonic() - start < 1.0
    assert downloader._running is False


def test_queue_processor_applies_backpressure(downloader, core_ns, tmp_db,
                                              redirect_home):
    """_process_queue must not hand the whole queue to the pool at once.

    Would fail before the fix: all items were submitted immediately, so
    len(_futures) grew to the full queue size and cancel_batch() could not stop
    them.
    """
    stub = _GatedStub()
    core_ns.youtube = stub
    _start_processor(downloader)
    ids = _add_tracks(tmp_db, 12)
    downloader.start_batch(len(ids))
    for tid in ids:
        downloader.queue_download(tid, "youtube", "v%d" % tid)
    try:
        _wait_until(lambda: stub.started >= _MAX_INFLIGHT, 5, "workers inside provider")
        time.sleep(0.3)
        assert len(_inflight(downloader)) <= _MAX_INFLIGHT
        assert stub.started <= _MAX_INFLIGHT
        assert len(downloader._queue) == len(ids) - _MAX_INFLIGHT
    finally:
        stub.release.set()
        downloader.stop()


@pytest.mark.parametrize("case", ["in-memory-dup", "db-dup"])
def test_batch_finished_is_never_emitted_under_a_lock(downloader, tmp_db,
                                                       emitted, monkeypatch, case):
    """_emit crosses the pywebview bridge and must run outside our locks.

    ``_decrement_batch_total_for_dedup`` is reached both with and without
    ``_queue_lock`` held (in-memory duplicate vs. DB duplicate), and used to
    emit ``batch_download_finished`` from inside ``_lock`` in both cases.
    """
    seen = []
    real_emit = downloader._emit

    def _spy(event_name, data=None):
        seen.append((event_name,
                     downloader._queue_lock.locked(),
                     downloader._lock.locked()))
        real_emit(event_name, data)

    monkeypatch.setattr(downloader, "_emit", _spy)
    downloader.start_batch(1)
    assert downloader.queue_download(1, "youtube", "v1") is True
    if case == "in-memory-dup":
        # from_db skips the INSERT, so the in-memory queue hit (and with it the
        # _queue_lock held by queue_download) is the one that shrinks the batch.
        assert downloader.queue_download(1, "youtube", "v1", from_db=True) is False
    else:
        # Let the DB row survive but drop the in-memory entry: the second
        # queue_download then fails on the UNIQUE index instead.
        downloader._queue.clear()
        assert downloader.queue_download(1, "youtube", "v1") is False

    finished = [s for s in seen if s[0] == "batch_download_finished"]
    assert finished, "dedup to zero total must still finish the batch"
    for _name, queue_locked, lock_locked in finished:
        assert not queue_locked, "emit under _queue_lock"
        assert not lock_locked, "emit under _lock"


def test_vk_source_fails_with_source_specific_error(downloader, tmp_db, emitted,
                                                    redirect_home):
    """VK has no download provider yet: fail loudly, but name the real reason.

    Documents the deferred VK download branch: VKService exposes no
    ``download_audio_sync``, so the worker must mark the row failed without
    claiming a provider returned a missing file and without faking
    is_downloaded.
    """
    tid = tmp_db.add_track(title="VK", artist="A", source="vk", source_id="-12345_1")
    downloader.start_batch(1)
    assert downloader.queue_download(tid, "vk", "-12345_1") is True

    downloader._download_worker(downloader._queue.pop(0))

    failed = [d for e, d in emitted if e == "download_failed"]
    assert len(failed) == 1
    assert failed[0]["track_id"] == tid
    assert "no download provider for source 'vk'" in failed[0]["error"].lower()
    assert "returned none or file missing" not in failed[0]["error"]
    assert tmp_db.get_track(tid)["is_downloaded"] == 0
    assert tmp_db.get_track(tid)["file_path"] is None
    assert tmp_db.download_queue_get_status(tid) == "failed"
    kinds = [e for e, _ in emitted]
    assert kinds.count("batch_download_finished") == 1


def test_spotify_id_source_id_is_not_used_as_search_query(downloader, core_ns, tmp_db,
                                                          emitted, redirect_home,
                                                          monkeypatch):
    """The old ``query_hint`` no-op passed ``spotify_<id>`` to YouTube search.

    Would fail before the fix: ``query_hint = sid`` ran unconditionally, so a
    metadata-less Spotify row searched YouTube for the literal string
    ``spotify_123`` instead of failing fast. TrackResolver is stubbed out so the
    test can never reach a real provider service.
    """
    from services.track_resolver import TrackResolver

    monkeypatch.setattr(TrackResolver, "resolve_track",
                        lambda self, title, artist="": {})
    stub = _NoDownloadYouTube()
    core_ns.youtube = stub
    tid = tmp_db.add_track(title="", artist="", source="spotify",
                           source_id="spotify_123")
    downloader.queue_download(tid, "spotify", "spotify_123")

    downloader._download_worker(downloader._queue.pop(0))

    assert not [q for q in stub.queries if "spotify_123" in q], \
        "spotify ids carry no searchable text"
    assert stub.downloads == [], "must not ask the provider to fetch the id"
    assert "download_failed" in [e for e, _ in emitted]
    assert tmp_db.get_track(tid)["is_downloaded"] == 0