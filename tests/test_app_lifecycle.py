"""AppCore cleanup order under blocked and partial construction states."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from core.app import AppCore, finalize_process
from services.base_service import BaseMusicService
from services.lyrics_service import LyricsService


def _partial_core():
    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    core._shutting_down = threading.Event()
    core._resolution_timers = set()
    core._resolve_threads = set()
    core._cleanup_done = threading.Event()
    core._cleanup_result = None
    core.save_session = lambda: None
    return core


def _patch_global_pools(monkeypatch):
    monkeypatch.setattr(BaseMusicService, "shutdown_executor", classmethod(lambda cls: None))
    monkeypatch.setattr(LyricsService, "shutdown_executor", classmethod(lambda cls, **_kwargs: None))


def test_cleanup_waits_for_blocked_executor_worker_before_database_close(monkeypatch):
    _patch_global_pools(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    worker_done = threading.Event()
    cleanup_done = threading.Event()
    db_closed = threading.Event()
    close_order = []
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cleanup-regression")
    monkeypatch.setattr(BaseMusicService, "_executor", SimpleNamespace(_pool=executor))

    def worker():
        entered.set()
        release.wait(5)
        worker_done.set()

    executor.submit(worker)
    assert entered.wait(1)
    core = _partial_core()
    core.api = None
    core.settings = type("Settings", (), {"close": lambda self: close_order.append("settings")})()

    class Database:
        def close(self):
            assert worker_done.is_set(), "database closed while the executor worker was active"
            close_order.append("database")
            db_closed.set()

    core.db = Database()
    cleanup_thread = threading.Thread(
        target=lambda: (core.cleanup(), cleanup_done.set()), name="CleanupRegression")
    cleanup_thread.start()
    assert not db_closed.wait(0.1)
    release.set()
    cleanup_thread.join(3)

    assert cleanup_done.is_set()
    assert worker_done.is_set()
    assert db_closed.is_set()
    assert close_order == ["settings", "database"]
    assert not cleanup_thread.is_alive()


def test_cleanup_is_safe_and_idempotent_after_partial_initialization(monkeypatch):
    _patch_global_pools(monkeypatch)
    core = _partial_core()

    core.cleanup()
    core.cleanup()

    assert core._cleanup_started is True
    assert core._shutting_down.is_set()


def test_cleanup_bounded_flushes_before_leaving_live_worker_and_cancels_pending(monkeypatch):
    _patch_global_pools(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    worker_done = threading.Event()
    session_flushed = threading.Event()
    settings_flushed = threading.Event()
    db_closed = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bounded-cleanup")
    monkeypatch.setattr(BaseMusicService, "_executor", SimpleNamespace(_pool=executor))

    def blocked_worker():
        entered.set()
        try:
            release.wait()
        finally:
            worker_done.set()

    executor.submit(blocked_worker)
    assert entered.wait(1)
    pending = executor.submit(lambda: None)
    core = _partial_core()
    core.save_session = session_flushed.set

    class Settings:
        def sync_flush_now(self):
            settings_flushed.set()
            return True

        def close(self):
            return True

    class Database:
        def close(self):
            assert worker_done.is_set(), "database closed while the executor worker was active"
            db_closed.set()

    core.settings = Settings()
    core.db = Database()
    try:
        result = core.cleanup(wait_timeout=0.02)
        assert result["durable_flushed"] is True
        assert result["remaining_workers"]
        assert session_flushed.is_set()
        assert settings_flushed.is_set()
        assert pending.cancelled()
        assert not db_closed.is_set(), "database closed under a live executor worker"
        assert core.cleanup(wait_timeout=0.02) == result
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
    assert db_closed.wait(2), "deferred state close did not run after worker completion"


def test_finalize_process_flushes_logs_before_terminating_only_after_durable_flush():
    calls = []
    result = {"durable_flushed": True, "remaining_workers": ("stuck-provider",)}
    finalize_process(lambda: (calls.append("shutdown"), result)[1],
                     lambda: calls.append("logs"),
                     lambda code: calls.append(("terminate", code)))
    assert calls == ["shutdown", "logs", ("terminate", 0)]

    calls.clear()
    failed = {"durable_flushed": False, "remaining_workers": ("stuck-provider",)}
    restarted = finalize_process(lambda: (calls.append("shutdown"), failed)[1],
                                 lambda: calls.append("logs"),
                                 lambda code: calls.append(("terminate", code)),
                                 restart=lambda: calls.append("restart"), exit_code=3)
    assert restarted is False
    assert calls == ["shutdown"]

    calls.clear()
    finalized = finalize_process(
        lambda: (calls.append("shutdown"), result)[1],
        lambda: calls.append("logs"),
        lambda code: calls.append(("terminate", code)),
        restart=lambda: calls.append("restart"),
        exit_code=3,
    )
    assert finalized is True
    assert calls == ["shutdown", "restart", "logs", ("terminate", 3)]


def test_finalize_process_leaves_normal_exit_to_interpreter_when_workers_drained():
    calls = []
    result = {"durable_flushed": True, "remaining_workers": ()}
    finalized = finalize_process(lambda: result, lambda: calls.append("logs"),
                                 lambda code: calls.append(("terminate", code)))
    assert finalized is True
    assert calls == []
