"""Zapret lifecycle fixes (audit A1: BUG-002/003/005/007/009/013/014/015/017/
022/023/024/025/043/046/047).

Everything here is hermetic: process scans, the machine guard mutex, the Job
Object, Popen and the survival window are faked; no real winws, UAC or system
mutation ever runs. Message assertions match the user-facing Russian text only
on stable substrings.
"""

import json
import os
import threading
import time
import types

import pytest

import services.zapret_service as m
from services.zapret_service import ZapretService


# ─── fixtures & fakes ────────────────────────────────────────────────────────


class FakeProc:
    """Popen stand-in: alive until `crash()` is called."""

    def __init__(self, pid=5555):
        self.pid = pid
        self._handle = 0
        self.returncode = None
        self._dead = threading.Event()
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._dead.wait()
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.crash(0)

    def crash(self, code):
        self.returncode = code
        self._dead.set()


@pytest.fixture
def svc(tmp_path, redirect_home, monkeypatch):
    """ZapretService with its system touchpoints faked out."""
    service = ZapretService()
    monkeypatch.setattr(service, "app_dir", str(tmp_path / "zapret"), raising=False)
    monkeypatch.setattr(service, "pid_file", os.path.join(str(tmp_path / "zapret"), "run.pid"), raising=False)
    monkeypatch.setattr(service, "cmd_file", os.path.join(str(tmp_path / "zapret"), "run.cmd"), raising=False)
    os.makedirs(service.app_dir, exist_ok=True)
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a, **k: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda handle: None)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (None, None))
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: "C:\\fake\\winws.exe")
    monkeypatch.setattr(ZapretService, "_get_pending_update", lambda self: "")
    monkeypatch.setattr(ZapretService, "_scan_pids_with", lambda self, sig: [])
    monkeypatch.setattr(ZapretService, "_scan_all_winws_pids", lambda self: [])
    service._launch_confirm_window = 0.0
    return service


def _pe_bytes():
    # Minimal valid-PE-shaped content so binary_integrity_error passes.
    import struct
    body = m._PE_MIN_SIZE + 64
    out = bytearray(b"MZ" + b"\x00" * 0x3A)
    out += struct.pack("<I", 0x40)
    out += b"\x00" * (0x40 - len(out))
    out += b"PE\0\0" + struct.pack("<H", 0x8664)
    out += b"\x00" * (body - len(out))
    return bytes(out)


def _healthy_binary(svc, monkeypatch):
    """find_binary returns a real file that passes the integrity gate."""
    path = os.path.join(svc.app_dir, "winws.exe")
    os.makedirs(svc.app_dir, exist_ok=True)
    with open(path, "wb") as f:
        f.write(_pe_bytes())
    monkeypatch.setattr(ZapretService, "find_binary", lambda self, p=None: path)
    return path


# ─── state machine / generation (BUG-002/003 service side) ──────────────────


def test_stop_during_start_download_cancels_the_stale_launch(svc, monkeypatch):
    """A stop() that arrives while start() is still preparing (download) must
    prevent the later launch — the stale epoch never reaches _launch."""
    path = os.path.join(svc.app_dir, "winws.exe")
    with open(path, "wb") as f:
        f.write(_pe_bytes())
    calls = []

    def find(self, p=None):
        calls.append(1)
        return path if len(calls) >= 2 else None  # first look: binary missing

    monkeypatch.setattr(ZapretService, "find_binary", find)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    launched = []

    def download(self):
        # Simulates a toggle-off/cleanup landing mid-download.
        svc.stop()
        return True, "ok"

    monkeypatch.setattr(ZapretService, "download_binaries", download)
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start()
    assert ok is False
    assert "отменён" in msg
    assert launched == [], "a superseded start must never launch winws"
    assert svc._state == m._STATE_STOPPED


def test_newer_start_supersedes_an_older_in_flight_start(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    launched = []
    first_started = threading.Event()
    release_first = threading.Event()
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)

    def slow_pending_update(self):
        first_started.set()
        release_first.wait(5)
        return ""

    monkeypatch.setattr(ZapretService, "_get_pending_update", slow_pending_update)
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(("launch", self._generation)) or ("started", FakeProc(), "ok"))

    results = {}

    def first():
        results["first"] = svc.start()

    worker = threading.Thread(target=first, daemon=True)
    worker.start()
    assert first_started.wait(5)
    results["second"] = svc.start()
    release_first.set()
    worker.join(5)

    assert results["second"][0] is True
    assert results["first"][0] is False, "the older start must be cancelled"
    assert len(launched) == 1 and launched[0][1] == svc._generation, \
        "only the newest start may launch"


def test_start_during_stopping_is_refused_with_a_clear_message(svc, monkeypatch):
    def stop_slowly(self, bump_generation=True):
        with svc._lock:
            svc._state = m._STATE_STOPPING
        time.sleep(0.3)
        with svc._lock:
            svc._state = m._STATE_STOPPED
        return True, "остановлен"

    monkeypatch.setattr(ZapretService, "_stop_impl", stop_slowly)
    stopper = threading.Thread(target=svc.stop, daemon=True)
    stopper.start()
    time.sleep(0.05)
    ok, msg = svc.start()
    stopper.join(5)
    assert ok is False
    assert "останавливается" in msg


# ─── app.py: autostart races (BUG-002/003/022/024) ──────────────────────────


class _WorkerSettings:
    def __init__(self, enabled_sequence):
        self._enabled_sequence = list(enabled_sequence)
        self.writes = {}

    def get(self, category, key, default=None):
        if category == "zapret" and key == "enabled":
            if len(self._enabled_sequence) > 1:
                return self._enabled_sequence.pop(0)
            return self._enabled_sequence[0]
        if category == "zapret" and key == "auto_start":
            return True
        return default

    def set(self, category, key, value):
        self.writes[(category, key)] = value


def _worker_core(settings, zapret, shutting_down=None):
    return types.SimpleNamespace(
        settings=settings,
        zapret=zapret,
        _shutting_down=shutting_down or threading.Event(),
        _zapret_start_thread=None,
        _service_lock=threading.RLock(),
    )


def test_autostart_rereads_the_toggle_before_starting(monkeypatch):
    """BUG-003: the toggle flips off while the worker sits queued — no start."""
    settings = _WorkerSettings([True, False])
    calls = []
    zapret = types.SimpleNamespace(
        start=lambda **kw: calls.append("start") or (True, "ok"),
        is_running=lambda: False,
        stop=lambda: (True, "stopped"),
    )
    core = _worker_core(settings, zapret)
    from core.app import AppCore
    AppCore.start_zapret_if_enabled(core)
    if core._zapret_start_thread is not None:
        core._zapret_start_thread.join(5)
    assert calls == []


def test_autostart_writes_enabled_from_the_real_process_state(monkeypatch):
    """BUG-022: autostart must not discard its result; `enabled` mirrors
    is_running() with the same semantics as toggle_zapret."""
    settings = _WorkerSettings([True])
    calls = []
    zapret = types.SimpleNamespace(
        start=lambda **kw: calls.append("start") or (True, "активен"),
        is_running=lambda: True,
        stop=lambda: (True, "stopped"),
    )
    core = _worker_core(settings, zapret)
    from core.app import AppCore
    AppCore.start_zapret_if_enabled(core)
    core._zapret_start_thread.join(5)
    assert calls == ["start"]
    assert settings.writes[("zapret", "enabled")] is True


def test_autostart_failure_does_not_leave_enabled_true(monkeypatch):
    settings = _WorkerSettings([True])
    zapret = types.SimpleNamespace(
        start=lambda **kw: (False, "сеть недоступна"),
        is_running=lambda: False,
        stop=lambda: (True, "stopped"),
    )
    core = _worker_core(settings, zapret)
    from core.app import AppCore
    AppCore.start_zapret_if_enabled(core)
    core._zapret_start_thread.join(5)
    assert settings.writes[("zapret", "enabled")] is False


def test_autostart_cancelled_by_shutdown_does_not_persist_enabled(monkeypatch):
    """BUG-002 follow-up: a start cancelled by shutdown must not write
    enabled=False — that would disable the user's choice for the next session."""
    settings = _WorkerSettings([True])
    shutting_down = threading.Event()

    def start(**kw):
        shutting_down.set()  # cleanup() lands during the (slow) start
        return (False, "cancelled")

    zapret = types.SimpleNamespace(start=start, is_running=lambda: False,
                                   stop=lambda: (True, "stopped"))
    core = _worker_core(settings, zapret, shutting_down=shutting_down)
    from core.app import AppCore
    AppCore.start_zapret_if_enabled(core)
    core._zapret_start_thread.join(5)
    assert ("zapret", "enabled") not in settings.writes


def test_second_autostart_is_refused_while_the_first_worker_is_alive(monkeypatch):
    """BUG-024 (app side): a repeated start_zapret_if_enabled must not
    overwrite the live worker reference."""
    settings = _WorkerSettings([True])
    release = threading.Event()
    started = threading.Event()
    calls = []

    def start(**kw):
        calls.append("start")
        started.set()
        release.wait(5)
        return (True, "ok")

    zapret = types.SimpleNamespace(start=start, is_running=lambda: True,
                                   stop=lambda: (True, "stopped"))
    core = _worker_core(settings, zapret)
    from core.app import AppCore
    AppCore.start_zapret_if_enabled(core)
    first_worker = core._zapret_start_thread
    assert started.wait(5)
    AppCore.start_zapret_if_enabled(core)  # e.g. a second `loaded` event
    assert core._zapret_start_thread is first_worker
    release.set()
    first_worker.join(5)
    assert calls == ["start"]


def test_cleanup_stops_zapret_again_after_joining_the_autostart_worker(monkeypatch):
    """BUG-002: cleanup's first stop can run into an empty field while the
    autostart worker is still launching; a second stop after the join must
    close that window."""
    from core.app import AppCore
    from services.base_service import BaseMusicService
    from services.lyrics_service import LyricsService
    monkeypatch.setattr(BaseMusicService, "shutdown_executor", lambda: None, raising=False)
    monkeypatch.setattr(LyricsService, "shutdown_executor", lambda **kwargs: None)

    order = []

    def fake_start(**kw):
        order.append("start")
        time.sleep(0.3)  # simulate a slow start (binary download)
        order.append("start.done")
        return (True, "ok")

    def fake_stop():
        order.append("stop")

    core = types.SimpleNamespace(
        settings=_WorkerSettings([True]),
        zapret=types.SimpleNamespace(start=fake_start, stop=fake_stop,
                                     is_running=lambda: False),
        _shutting_down=threading.Event(),
        _zapret_start_thread=None,
        _service_lock=threading.RLock(),
    )
    for name in ("watchdog", "lufs_scanner", "downloader", "plugins",
                 "discord_rpc", "proxy", "db", "cache",
                 "youtube", "_soundcloud", "_yandex", "spotify", "api",
                 "_cache_cleanup_stop", "_cache_cleanup_thread", "scanner"):
        setattr(core, name, None)

    AppCore.start_zapret_if_enabled(core)
    worker = core._zapret_start_thread
    assert worker is not None
    deadline = time.time() + 5
    while "start" not in order and time.time() < deadline:
        time.sleep(0.01)
    AppCore.cleanup(core, wait_timeout=5.0)
    worker.join(5)

    # The autostart worker is joined before the final stop step: the stop that
    # lands after "start.done" is the one closing the BUG-002 window.
    assert order.count("stop") >= 2, "stop must run before AND after the join"
    last_stop = max(i for i, value in enumerate(order) if value == "stop")
    assert order.index("start.done") < last_stop


# ─── pre-launch scan / adoption / foreign refusal (BUG-013) ─────────────────


def test_orphaned_winws_is_adopted_instead_of_duplicated(svc, monkeypatch):
    path = _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (777, None))
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: pid == 777)
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start()
    assert ok is True
    assert "подключён" in msg or "активен" in msg
    assert launched == [], "a second winws over the orphan must not be spawned"
    assert svc._read_pidfile() == 777
    record = svc._read_pidfile_record()
    assert record["uid"] == svc._known_uid and svc._known_uid


def test_foreign_winws_blocks_the_launch_with_a_clear_message(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (None, 888))
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start()
    assert ok is False
    assert "другой экземпляр" in msg and "888" in msg
    assert launched == []


def test_vanished_orphan_falls_through_to_a_normal_launch(svc, monkeypatch):
    path = _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (777, None))
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: False)
    launched = []
    proc = FakeProc()
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", proc, "ok"))

    ok, msg = svc.start()
    assert ok is True
    assert launched == [path]


def test_orphan_running_a_different_strategy_is_restarted_not_falsely_adopted(svc, monkeypatch):
    """Adopting an orphan while recording the REQUESTED args would desync
    run.cmd from reality: the process keeps running the old strategy while the
    state claims the new one, and a later start() silently no-ops. The orphan
    must be restarted precisely (kill the verified PID, launch fresh)."""
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (777, None))
    svc._write_cmd_file("--wf-tcp=80,443 --filter-tcp=80,443")  # the orphan's strategy
    alive = {777: True}
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: alive.get(pid, False))
    killed = []
    monkeypatch.setattr(ZapretService, "_kill_pid",
                        lambda self, pid: killed.append(pid) or alive.__setitem__(pid, False) or True)
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(args) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start(mode="aggressive")
    assert ok is True
    assert killed == [777], "the verified orphan must be killed by PID, not duplicated"
    assert len(launched) == 1 and "--dpi-desync=disorder2" in launched[0], \
        "the fresh launch must carry the requested strategy"
    record = svc._read_pidfile_record()
    assert record is None or svc._record_pids(record) != [777]


def test_orphan_with_a_different_strategy_refuses_when_unkillable(svc, monkeypatch):
    """An elevated orphan cannot be killed without rights: launching a second
    driver over it would stack two WinDivert engines — refuse honestly."""
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(ZapretService, "_classify_running_winws", lambda self: (777, None))
    svc._write_cmd_file("--wf-tcp=80,443 --filter-tcp=80,443")
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_kill_pid", lambda self, pid: False)
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start(mode="aggressive")
    assert ok is False
    assert "другой стратегией" in msg and "777" in msg
    assert launched == [], "a second winws over the unkillable orphan must not spawn"
    assert svc._state == m._STATE_STOPPED


# ─── state files: atomicity + degraded writes (BUG-014/015) ─────────────────


def test_state_files_are_written_atomically(svc, monkeypatch):
    pid_path = svc.pid_file
    with open(pid_path, "w", encoding="utf-8") as f:
        f.write("1111")

    real_replace = os.replace
    failures = []

    def failing_replace(src, dst):
        if dst == pid_path:
            failures.append(1)
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    svc._write_pidfile(2222)
    monkeypatch.setattr(os, "replace", real_replace)

    assert failures, "the injected failure must have been exercised"
    assert svc._state_write_failed is True
    # The old content survives untouched; no .tmp debris is left behind.
    with open(pid_path, "r", encoding="utf-8") as f:
        assert f.read().strip() == "1111"
    assert not os.path.exists(pid_path + ".tmp")


def test_successful_atomic_write_leaves_no_tmp_and_clears_the_flag(svc):
    svc._state_write_failed = True
    assert svc._write_cmd_file("--wf-tcp=80,443") is True
    assert svc._state_write_failed is False
    assert svc._read_cmd_file() == "--wf-tcp=80,443"
    assert not os.path.exists(svc.cmd_file + ".tmp")


def test_lost_cmd_file_with_live_process_is_a_no_op_not_a_restart(svc, monkeypatch):
    """BUG-014: run.cmd lost after an app restart — the running winws must
    not be restarted (the old code read '' != args and recycled the process)."""
    _healthy_binary(svc, monkeypatch)
    svc._write_pidfile(4321)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: True)
    launched = []
    monkeypatch.setattr(ZapretService, "_launch",
                        lambda self, exe, args: launched.append(exe) or ("started", FakeProc(), "ok"))

    ok, msg = svc.start(mode="aggressive")
    assert ok is True
    assert msg == "Zapret активен"
    assert launched == [], "a live process with a lost signature must be left alone"


def test_stop_reports_degraded_result_when_state_write_failed(svc, monkeypatch):
    """BUG-015: with state writes broken and nothing visible to the scans,
    'Zapret остановлен' would be a guess — the message must carry the doubt."""
    svc._state_write_failed = True
    ok, msg = svc.stop()
    assert ok is True
    assert "не удалась" in msg and "диспетчер задач" in msg


def test_stop_with_healthy_state_reports_a_clean_stop(svc):
    ok, msg = svc.stop()
    assert ok is True
    assert msg == "Zapret остановлен"
    assert svc._state == m._STATE_STOPPED


def test_stop_skips_the_wmi_scan_when_the_pidfile_yields_live_targets(svc, monkeypatch):
    """The signature scan costs ~10s of WMI; with every launched PID recorded
    in the pidfile it is pure shutdown latency. It must run only when the
    pidfile yields nothing (the elevated-discovery-failure case)."""
    svc._write_pidfile(33)
    svc._write_cmd_file("--filter-tcp=80,443")
    alive = {33: True}
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: alive.get(pid, False))
    monkeypatch.setattr(ZapretService, "_is_our_winws_process",
                        lambda self, pid, signature="", signature_verified=False: pid == 33)
    monkeypatch.setattr(ZapretService, "_kill_pid",
                        lambda self, pid: alive.__setitem__(pid, False) or True)
    scans = []
    monkeypatch.setattr(ZapretService, "_scan_pids_with",
                        lambda self, sig: scans.append(sig) or [])

    ok, msg = svc.stop()
    assert ok is True and msg == "Zapret остановлен"
    assert scans == [], "record-derived targets make the WMI scan redundant"


def test_stop_still_scans_by_signature_when_the_pidfile_yields_nothing(svc, monkeypatch):
    """Elevated-discovery failure (BUG-040) leaves no usable pidfile record:
    the signature scan is the only way to find the process — it must run, and
    its result must not be re-scanned a second time."""
    svc._write_cmd_file("--filter-tcp=80,443 --hostlist-domains=x")
    alive = {42: True}
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: alive.get(pid, False))
    checks = []

    def ownership(self, pid, signature="", signature_verified=False):
        checks.append(signature_verified)
        return pid == 42

    monkeypatch.setattr(ZapretService, "_is_our_winws_process", ownership)
    monkeypatch.setattr(ZapretService, "_kill_pid",
                        lambda self, pid: alive.__setitem__(pid, False) or True)
    monkeypatch.setattr(ZapretService, "_scan_pids_with", lambda self, sig: [42])

    ok, msg = svc.stop()
    assert ok is True and msg == "Zapret остановлен"
    assert checks == [True], "a scan-found PID must not trigger the redundant second scan"


def test_exception_mid_start_never_leaves_a_stuck_STARTING(svc, monkeypatch):
    """The finally-transition is the safety net for exception paths: after a
    start() raises, the state must be RUNNING or STOPPED — never STARTING."""
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)

    def boom(self, gen, mode, custom_args, binary_path):
        raise RuntimeError("download exploded")

    monkeypatch.setattr(ZapretService, "_start_with_generation", boom)
    with pytest.raises(RuntimeError):
        svc.start()
    assert svc._state == m._STATE_STOPPED


# ─── storage degradation (BUG-017) ──────────────────────────────────────────


def test_unwritable_data_directory_degrades_instead_of_crashing(tmp_path, monkeypatch):
    real_makedirs = os.makedirs

    def broken_makedirs(path, *args, **kwargs):
        if ".nedotify" in str(path):
            raise OSError("access denied")
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", broken_makedirs)
    service = ZapretService()  # must NOT raise
    assert service._storage_unavailable is True

    ok, msg = service.start()
    assert ok is False
    assert "недоступен" in msg


# ─── pidfile records: multi-PID + legacy (BUG-046) ──────────────────────────


def test_partial_stop_preserves_every_surviving_pid(svc, monkeypatch):
    svc._write_pidfile(11, pids=[11, 22], uid="abc")
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_is_our_winws_process",
                        lambda self, pid, signature="", signature_verified=False: True)
    monkeypatch.setattr(ZapretService, "_kill_pid", lambda self, pid: False)

    ok, msg = svc.stop()
    assert ok is False
    record = svc._read_pidfile_record()
    assert sorted(svc._record_pids(record)) == [11, 22], \
        "the old code stored only failed_pids[0] and lost the rest"
    assert record["uid"] == "abc"
    assert svc._state == m._STATE_RUNNING


def test_successful_stop_after_partial_failure_clears_everything(svc, monkeypatch):
    svc._write_pidfile(11, pids=[11, 22], uid="abc")
    svc._write_cmd_file("--filter-tcp=80,443")
    alive = {11: True, 22: True}
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: alive.get(pid, False))
    monkeypatch.setattr(ZapretService, "_is_our_winws_process",
                        lambda self, pid, signature="", signature_verified=False: True)

    def kill(self, pid):
        alive[pid] = False
        return True

    monkeypatch.setattr(ZapretService, "_kill_pid", kill)

    ok, msg = svc.stop()
    assert ok is True
    assert svc._read_pidfile_record() is None
    assert svc._read_cmd_file() == ""
    assert svc._last_args == ""


def test_pidfile_reads_legacy_single_int_files(svc):
    with open(svc.pid_file, "w", encoding="utf-8") as f:
        f.write("4321")
    assert svc._read_pidfile() == 4321
    assert svc._read_pidfile_pids() == [4321]
    assert svc._read_pidfile_record() == {"pid": 4321, "uid": ""}


def test_pidfile_record_roundtrip_with_uid_and_created(svc, monkeypatch):
    monkeypatch.setattr(ZapretService, "_get_process_creation_time",
                        lambda self, pid: 12345678 if pid == 99 else None)
    svc._write_pidfile(99, uid="deadbeef")
    record = svc._read_pidfile_record()
    assert record == {"pid": 99, "uid": "deadbeef", "created": {"99": 12345678}}
    assert svc._read_pidfile() == 99


# ─── ownership (BUG-005/047) ────────────────────────────────────────────────


def test_path_prefix_requires_the_separator():
    assert ZapretService._path_under_root("c:\\nedotify\\winws.exe", "C:\\NeDotify") is True
    assert ZapretService._path_under_root("c:\\nedotify\\x\\winws.exe", "C:\\NeDotify") is True
    # The old bare startswith() accepted sibling directories.
    assert ZapretService._path_under_root("c:\\nedotifyevil\\winws.exe", "C:\\NeDotify") is False
    assert ZapretService._path_under_root("c:\\nedotify-old\\winws.exe", "C:\\NeDotify") is False


def _ownership_svc(svc, monkeypatch, record):
    if record is None:
        monkeypatch.setattr(ZapretService, "_read_pidfile_record", lambda self: None)
    else:
        monkeypatch.setattr(ZapretService, "_read_pidfile_record", lambda self: record)
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_is_winws_process", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_get_process_exe_path", lambda self, pid: None)
    monkeypatch.setattr(ZapretService, "_scan_pids_with", lambda self, sig: [])


def test_unreadable_path_fallback_requires_our_uid(svc, monkeypatch):
    """BUG-047: exe path unreadable + saved_pid == pid used to adopt a foreign
    elevated winws. The uid marker must gate the fallback, and even a matching
    uid is refused without the recorded creation time."""
    record = {"pid": 999, "uid": "abc"}
    _ownership_svc(svc, monkeypatch, record)

    svc._known_uid = ""
    assert svc._is_our_winws_process(999) is False, "fresh session must not trust a bare pid"

    svc._known_uid = "other"
    assert svc._is_our_winws_process(999) is False, "a foreign uid must not match"

    svc._known_uid = "abc"
    assert svc._is_our_winws_process(999) is False, \
        "a uid without the creation-time marker stays rejected (strict by design)"


def test_unreadable_path_fallback_requires_the_recorded_creation_time(svc, monkeypatch):
    """A reused PID carries a different creation time — the fallback must
    reject it even with a matching uid."""
    record = {"pid": 999, "uid": "abc", "created": {"999": 111}}
    _ownership_svc(svc, monkeypatch, record)
    svc._known_uid = "abc"

    monkeypatch.setattr(ZapretService, "_get_process_creation_time", lambda self, pid: 111)
    assert svc._is_our_winws_process(999) is True

    monkeypatch.setattr(ZapretService, "_get_process_creation_time", lambda self, pid: 222)
    assert svc._is_our_winws_process(999) is False, "PID reuse must not be adopted"

    monkeypatch.setattr(ZapretService, "_get_process_creation_time", lambda self, pid: None)
    assert svc._is_our_winws_process(999) is False


def test_matching_arguments_alone_cannot_authorize_process_ownership(svc, monkeypatch):
    scans = []

    def fake_scan(self, sig):
        scans.append(sig)
        return [7]

    monkeypatch.setattr(ZapretService, "_scan_pids_with", fake_scan)
    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_is_winws_process", lambda self, pid: True)
    monkeypatch.setattr(ZapretService, "_get_process_exe_path", lambda self, pid: None)

    assert svc._is_our_winws_process(7, "sig", signature_verified=True) is False
    assert svc._is_our_winws_process(7, "sig") is False
    assert scans == [], "shared arguments are not identity evidence"


# ─── Job Object (BUG-023) ───────────────────────────────────────────────────


def test_child_is_bound_to_a_kill_on_close_job(svc, monkeypatch):
    path = _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    jobs, assignments, closes = [], [], []

    monkeypatch.setattr(m, "_win32_create_kill_on_close_job", lambda: 4242)
    monkeypatch.setattr(m, "_win32_assign_process_to_job",
                        lambda job, handle: assignments.append((job, handle)) or True)
    monkeypatch.setattr(m, "_win32_close_handle", lambda handle: closes.append(handle))

    real_popen = m.subprocess.Popen
    proc = FakeProc(pid=5555)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: proc)

    ok, msg = svc.start()
    assert ok is True
    assert assignments == [(4242, 0)], "the child handle must be assigned to the job"
    assert svc._job_handle == 4242

    monkeypatch.setattr(ZapretService, "_pid_alive", lambda self, pid: False)
    monkeypatch.setattr(ZapretService, "_is_our_winws_process",
                        lambda self, pid, signature="", signature_verified=False: False)
    ok, msg = svc.stop()
    assert ok is True
    assert closes == [4242], "stop must release the job handle"
    assert svc._job_handle is None
    monkeypatch.setattr(m.subprocess, "Popen", real_popen)


def test_job_assignment_failure_is_reported_not_fatal(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    monkeypatch.setattr(m, "_win32_create_kill_on_close_job", lambda: 4242)
    monkeypatch.setattr(m, "_win32_assign_process_to_job", lambda job, handle: False)
    closes = []
    monkeypatch.setattr(m, "_win32_close_handle", lambda handle: closes.append(handle))

    proc = FakeProc()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: proc)
    ok, msg = svc.start()
    assert ok is True
    assert closes == [4242], "an unassignable job handle must be released immediately"
    assert svc._job_handle is None


# ─── launch confirmation & late crash events (BUG-025) ─────────────────────


def test_launch_refusal_leaves_no_signature_artifacts(svc):
    """_launch validates the arguments BEFORE writing run.cmd: a refused
    launch must not leave a signature file that makes the next stop() pay for
    a multi-second WMI scan for a process that never existed."""
    os.makedirs(svc.app_dir, exist_ok=True)
    exe = os.path.join(svc.app_dir, "winws.exe")
    with open(exe, "wb") as f:
        f.write(_pe_bytes())

    kind, proc, msg = svc._launch(exe, "definitely --not; allowed")
    assert kind == "failed"
    assert "Недопустимый" in msg or "Неподдерживаемый" in msg
    assert svc._last_args == ""
    assert not os.path.exists(svc.cmd_file), "run.cmd must not describe a refused launch"


def test_crash_inside_the_confirmation_window_fails_the_start_and_emits(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    svc._launch_confirm_window = 5.0

    proc = FakeProc()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: proc)
    # Alive through the in-lock fast-path polls (~0.6s), dead inside the
    # extended confirmation window.
    threading.Timer(1.0, proc.crash, args=(3,)).start()

    ok, msg = svc.start()
    assert ok is False
    assert "Код завершения: 3" in msg
    assert events and events[0][0] == "zapret_crashed"
    assert events[0][1]["returncode"] == 3
    assert svc._state == m._STATE_STOPPED
    assert svc._read_pidfile_record() is None


def test_surviving_child_confirms_after_the_window_and_watches(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))

    proc = FakeProc()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: proc)
    ok, msg = svc.start()
    assert ok is True
    assert msg == "Zapret активен"
    assert svc._state == m._STATE_RUNNING
    assert events == [], "a healthy launch must not report a crash"
    # The watcher is parked on a still-living fake process: nothing fires.


def test_late_crash_after_success_is_reported_through_the_hook(svc):
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    proc = FakeProc()
    gen = svc._generation
    svc._state = m._STATE_RUNNING

    def crash_later():
        time.sleep(0.05)
        proc.crash(2)

    threading.Thread(target=crash_later, daemon=True).start()
    svc._watch_child_lifecycle(proc, gen)

    assert events and events[0][0] == "zapret_crashed"
    assert events[0][1]["late"] is True and events[0][1]["returncode"] == 2
    assert svc._state == m._STATE_STOPPED


def test_intentional_stop_after_success_emits_no_crash(svc):
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    proc = FakeProc()
    gen = svc._generation

    def stop_later():
        time.sleep(0.05)
        svc._generation += 1  # what stop() does
        proc.crash(0)

    threading.Thread(target=stop_later, daemon=True).start()
    svc._watch_child_lifecycle(proc, gen)
    assert events == []


def test_crash_of_a_cancelled_epoch_is_silent(svc, monkeypatch):
    """The confirmation window raced a stop(): the newer command owns the
    outcome, the stale start must not double-report a 'crash'."""
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    svc._generation += 1
    proc = FakeProc()
    proc.crash(1)
    ok, msg = svc._confirm_launch(proc, svc._generation - 1)
    assert ok is False
    assert "отменён" in msg
    assert events == []


def test_stop_during_the_confirmation_window_cancels_without_crash_event(svc, monkeypatch):
    _healthy_binary(svc, monkeypatch)
    monkeypatch.setattr(ZapretService, "is_running", lambda self: False)
    events = []
    svc.set_event_callback(lambda name, payload: events.append((name, payload)))
    svc._launch_confirm_window = 5.0

    proc = FakeProc()
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: proc)

    results = {}

    def racing_start():
        results["start"] = svc.start()

    worker = threading.Thread(target=racing_start, daemon=True)
    worker.start()
    time.sleep(0.2)  # let the start reach its confirmation window
    results["stop"] = svc.stop()
    proc.crash(0)
    worker.join(5)

    assert results["start"][0] is False
    assert "отменён" in results["start"][1]
    assert events == [], "an intentional stop must not look like a crash"


# ─── machine-global guard (BUG-043) ─────────────────────────────────────────


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_global_guard_mutex_roundtrip():
    handle = m._global_zapret_guard_acquire(timeout_ms=500)
    try:
        assert handle, "the guard mutex must be acquirable"
        # Same-thread re-entry (the restart path stops while holding the
        # guard) must not deadlock: Windows mutexes are recursive.
        nested = m._global_zapret_guard_acquire(timeout_ms=500)
        assert nested
        m._global_zapret_guard_release(nested)
    finally:
        m._global_zapret_guard_release(handle)
    # After release another acquire succeeds immediately.
    again = m._global_zapret_guard_acquire(timeout_ms=500)
    assert again
    m._global_zapret_guard_release(again)


# ─── api layer: enabled mirrors reality (BUG-009) ───────────────────────────


def test_toggle_off_with_unkillable_process_keeps_enabled_true():
    class _Settings:
        def __init__(self):
            self.d = {}

        def get(self, c, k, d=None):
            return self.d.get((c, k), d)

        def set(self, c, k, v):
            self.d[(c, k)] = v

    settings = _Settings()
    zapret = types.SimpleNamespace(
        start=lambda **kw: (True, "ok"),
        stop=lambda: (False, "Не удалось остановить"),
        is_running=lambda: True,
    )
    core = types.SimpleNamespace(settings=settings, zapret=zapret)
    from core.api import AppApi
    api = AppApi.__new__(AppApi)
    api._core = core
    result = api.toggle_zapret(False)
    assert result["success"] is False
    assert result["running"] is True
    assert result["enabled"] is True
    assert settings.d[("zapret", "enabled")] is True, \
        "a failed stop with a live process must not write enabled=False"

    zapret.is_running = lambda: False
    zapret.stop = lambda: (True, "остановлен")
    result = api.toggle_zapret(False)
    assert result["enabled"] is False
    assert settings.d[("zapret", "enabled")] is False


def test_toggle_on_failure_reports_enabled_consistently():
    class _Settings:
        def __init__(self):
            self.d = {}

        def get(self, c, k, d=None):
            return self.d.get((c, k), d)

        def set(self, c, k, v):
            self.d[(c, k)] = v

    settings = _Settings()
    zapret = types.SimpleNamespace(
        start=lambda **kw: (False, "нет winws.exe"),
        select_strategy=lambda **kw: (False, "нет winws.exe", "youtube_discord"),
        stop=lambda: (True, "остановлен"),
        is_running=lambda: False,
    )
    core = types.SimpleNamespace(settings=settings, zapret=zapret)
    from core.api import AppApi
    api = AppApi.__new__(AppApi)
    api._core = core
    result = api.toggle_zapret(True)
    assert result["success"] is False
    assert result["enabled"] is False
    assert settings.d[("zapret", "enabled")] is False


def test_toggle_exception_reports_the_actual_process_state():
    """BUG-009 honesty holds on the exception path too: a start/stop may have
    landed before the error, so running/enabled must come from is_running()."""
    class _Settings:
        def __init__(self):
            self.d = {}

        def get(self, c, k, d=None):
            return self.d.get((c, k), d)

        def set(self, c, k, v):
            self.d[(c, k)] = v

    settings = _Settings()

    def broken_stop():
        raise RuntimeError("bridge exploded")

    zapret = types.SimpleNamespace(
        start=lambda **kw: (True, "ok"),
        stop=broken_stop,
        is_running=lambda: True,
    )
    core = types.SimpleNamespace(settings=settings, zapret=zapret)
    from core.api import AppApi
    api = AppApi.__new__(AppApi)
    api._core = core
    result = api.toggle_zapret(False)
    assert result["success"] is False
    assert result["running"] is True
    assert result["enabled"] is True

    def broken_running():
        raise RuntimeError("probe failed")

    zapret.is_running = broken_running
    result = api.toggle_zapret(False)
    assert result["running"] is False and result["enabled"] is False


def test_api_wires_the_zapret_event_callback():
    from core.api import AppApi
    registered = []
    core = types.SimpleNamespace(
        zapret=types.SimpleNamespace(
            _set_elevation_window=lambda provider: None,
            set_event_callback=lambda cb: registered.append(cb),
        ),
    )
    api = AppApi.__new__(AppApi)
    api._core = core
    api.set_window(types.SimpleNamespace())
    assert len(registered) == 1
    # The hook translates into bridge events without importing anything.
    emitted = []
    api._emit = lambda name, data=None: emitted.append((name, data))
    registered[0]("zapret_crashed", {"message": "x"})
    assert emitted == [("zapret_crashed", {"message": "x"})]
