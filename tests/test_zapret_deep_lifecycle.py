"""Adversarial lifecycle regressions; all process and UAC operations are fake.

These tests never launch winws, alter routes, or operate on the user's VPN.
The suite profile is isolated by tests/conftest.py before service import.
"""

import ctypes
import json
import os
import struct
import subprocess
import threading
from types import SimpleNamespace

import pytest

import services.zapret_service as m
from services.zapret_service import ZapretService


class WindowsChild:
    """Match Windows Popen's real native handle name: _handle, never handle."""

    def __init__(self, pid=76543):
        self.pid = pid
        self._handle = 0x123456789
        self.returncode = None
        self.exited = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake winws", timeout)
        return self.returncode

    def terminate(self):
        self.crash(0)

    def crash(self, returncode=1):
        self.returncode = returncode
        self.exited.set()


def _pe_bytes():
    data = bytearray(m._PE_MIN_SIZE + 64)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x40)
    data[0x40:0x46] = b"PE\0\0\x64\x86"
    return data


@pytest.fixture
def lifecycle(monkeypatch, tmp_path, redirect_home):
    service = ZapretService()
    app_dir = tmp_path / "zapret"
    app_dir.mkdir()
    service.app_dir = str(app_dir)
    service.pid_file = str(app_dir / "run.pid")
    service.cmd_file = str(app_dir / "run.cmd")
    service.log_file = str(tmp_path / "zapret.log")
    exe = app_dir / "winws.exe"
    exe.write_bytes(_pe_bytes())
    service._launch_confirm_window = 0
    service._elevation_scan_window = 0.1
    monkeypatch.setattr(service, "find_binary", lambda custom_path=None: str(exe))
    monkeypatch.setattr(service, "_binary_directory", lambda: service.app_dir)
    monkeypatch.setattr(service, "_get_pending_update", lambda: "")
    monkeypatch.setattr(service, "_get_process_creation_time", lambda pid: 123456789)
    monkeypatch.setattr(service, "_classify_running_winws", lambda: (None, None))
    monkeypatch.setattr(service, "_scan_pids_with", lambda signature: [])
    monkeypatch.setattr(service, "_scan_all_winws_pids", lambda: [])
    monkeypatch.setattr(service, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(service, "_ensure_lifecycle_watcher", lambda: None)
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *args, **kwargs: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda handle: None)
    monkeypatch.setattr(m, "_win32_create_kill_on_close_job", lambda: None)
    # A missed mock must fail safely rather than touch any native process.
    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Unmocked Popen"))
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unmocked subprocess.run"))
    monkeypatch.setattr(service, "_shell_execute_elevated", lambda *args: pytest.fail("Unmocked UAC"))
    monkeypatch.setattr(service, "_kill_pid", lambda *args, **kwargs: pytest.fail("Unmocked process termination"))
    return service, str(exe)


@pytest.mark.skipif(os.name != "nt", reason="Windows native Popen interface")
def test_direct_start_assigns_the_real_popen_native_handle(lifecycle, monkeypatch):
    service, _ = lifecycle
    child = WindowsChild()
    assigned = []
    monkeypatch.setattr(m.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(m, "_win32_create_kill_on_close_job", lambda: 0x9999)
    monkeypatch.setattr(m, "_win32_assign_process_to_job", lambda job, handle: assigned.append((job, handle)) or True)
    monkeypatch.setattr(m, "_win32_close_handle", lambda handle: None)
    try:
        assert service.start()[0]
        assert assigned == [(0x9999, child._handle)]
        assert service._read_pidfile() == child.pid
    finally:
        service._close_log_handle()
        child.crash(0)


def _allow_fake_elevation(service, exe, monkeypatch):
    monkeypatch.setattr(m, "_protected_elevation_path", lambda path: True)

    def system_directory(buffer, size):
        buffer.value = r"C:\Windows\System32"
        return len(buffer.value)

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
        kernel32=SimpleNamespace(GetSystemDirectoryW=system_directory)))
    monkeypatch.setattr(service, "_is_winws_process", lambda pid: True)
    monkeypatch.setattr(service, "_get_process_exe_path", lambda pid: exe)

    def launch(exe, args):
        service._known_uid = "fake-uac-attempt"
        service._last_args = args
        service._write_cmd_file(args)
        return "elevate", None, ""

    monkeypatch.setattr(service, "_launch", launch)


def test_stop_during_uac_cannot_resurrect_a_stale_start(lifecycle, monkeypatch):
    service, exe = lifecycle
    _allow_fake_elevation(service, exe, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    alive = set()
    monkeypatch.setattr(service, "_pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(service, "_scan_pids_with", lambda args: sorted(alive))

    def shell_execute(*args):
        entered.set()
        assert release.wait(3)
        alive.add(76543)
        return 64

    def kill(pid, **kwargs):
        alive.discard(pid)
        return True

    monkeypatch.setattr(service, "_shell_execute_elevated", shell_execute)
    monkeypatch.setattr(service, "_kill_pid", kill)
    result = []
    worker = threading.Thread(target=lambda: result.append(service.start()))
    worker.start()
    try:
        assert entered.wait(3)
        # UAC has not returned, so stop can cancel the generation but cannot
        # truthfully confirm termination yet.
        assert not service.stop()[0]
        assert not service.start()[0], "no duplicate launch while UAC is pending"
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert result and not result[0][0], "a superseded UAC launch cannot report success"
    assert not alive, "the delayed UAC child must be cleaned up after toggle-off"
    assert not service.is_running()


def test_unreadable_foreign_process_cannot_be_owned_by_shared_arguments(lifecycle, monkeypatch):
    service, _ = lifecycle
    # A normal option string is not an instance identity. Another bypass can
    # run exactly these arguments while Windows hides its executable path.
    signature = "--wf-tcp=443 --filter-tcp=443"
    service._write_cmd_file(signature)
    monkeypatch.setattr(service, "_pid_alive", lambda pid: pid == 76543)
    monkeypatch.setattr(service, "_is_winws_process", lambda pid: True)
    monkeypatch.setattr(service, "_get_process_exe_path", lambda pid: None)
    monkeypatch.setattr(service, "_scan_pids_with", lambda args: [76543])
    killed = []
    monkeypatch.setattr(service, "_kill_pid", lambda pid, **kwargs: killed.append(pid) or False)
    service.stop()
    assert killed == [], "matching a common command line must not authorize killing a foreign process"


def test_unstoppable_untracked_child_retains_authoritative_popen_handle(lifecycle, monkeypatch):
    service, _ = lifecycle
    child = WindowsChild()
    service.process = child
    service._state = m._STATE_RUNNING
    service._state_write_failed = True
    monkeypatch.setattr(child, "terminate", lambda: None)
    monkeypatch.setattr(child, "wait", lambda timeout=None: (_ for _ in ()).throw(
        subprocess.TimeoutExpired("fake winws", timeout)))
    ok, _ = service.stop()
    assert not ok, "a child which survived termination cannot be reported as stopped"
    assert service.process is child, "retain the process handle so a later stop can retry"
    assert service.is_running()


class PauseAfterFirstRelease:
    """Schedule a newer start precisely between two crash-cleanup sections."""

    def __init__(self, entered, release):
        self.lock = threading.RLock()
        self.entered = entered
        self.release = release
        self.target = None
        self.paused = False
        self.depth = threading.local()

    def __enter__(self):
        self.lock.acquire()
        self.depth.value = getattr(self.depth, 'value', 0) + 1
        return self

    def __exit__(self, *args):
        self.depth.value -= 1
        should_pause = threading.get_ident() == self.target and not self.paused and self.depth.value == 0
        if should_pause:
            self.paused = True
        self.lock.release()
        if should_pause:
            self.entered.set()
            assert self.release.wait(3)


def test_old_confirmation_cannot_clear_a_newer_successful_start(lifecycle, monkeypatch):
    service, _ = lifecycle
    old_child, new_child = WindowsChild(76543), WindowsChild(76544)
    old_child.crash(1)
    service.process = old_child
    service._generation = 1
    service._state = m._STATE_STARTING
    entered, release = threading.Event(), threading.Event()
    gated_lock = PauseAfterFirstRelease(entered, release)
    service._lock = gated_lock
    events = []
    service.set_event_callback(lambda name, payload: events.append((name, payload)))

    def launch(exe, args):
        service.process = new_child
        service._write_pidfile(new_child.pid)
        service._write_cmd_file(args)
        service._last_args = args
        return "started", new_child, ""

    monkeypatch.setattr(service, "_launch", launch)
    result = []

    def confirm_old():
        gated_lock.target = threading.get_ident()
        result.append(service._confirm_launch(old_child, 1))

    worker = threading.Thread(target=confirm_old)
    worker.start()
    try:
        assert entered.wait(3)
        assert service.start(mode="standard")[0]
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert service.process is new_child
    assert service._state == m._STATE_RUNNING, "an old crash cannot overwrite the new generation"
    assert service._read_pidfile() == new_child.pid
    assert events == [], "a superseded start must not emit a crash for the new process"
    assert result and result[0][0] is False, 'the confirmation thread must finish without exceptions'


@pytest.mark.parametrize("pids", [1, True, 1.5])
def test_malformed_pid_list_does_not_break_liveness(lifecycle, pids):
    service, _ = lifecycle
    with open(service.pid_file, "w", encoding="utf-8") as stream:
        json.dump({"pid": 76543, "pids": pids}, stream)
    assert service.is_running() is False


@pytest.mark.parametrize('value', [float('inf'), float('nan'), 1.5, True, -1, 2**40])
def test_corrupt_pid_values_are_ignored_instead_of_truncated(value):
    assert ZapretService._record_pids({'pid': value, 'pids': [value]}) == []


def test_failed_pidfile_write_retains_live_identity_in_memory(lifecycle, monkeypatch):
    service, _ = lifecycle
    service._known_uid = 'live-instance'
    monkeypatch.setattr(service, '_atomic_write_text', lambda *args: False)
    monkeypatch.setattr(service, '_pid_alive', lambda pid: pid == 76543)
    monkeypatch.setattr(service, '_is_winws_process', lambda pid: True)
    monkeypatch.setattr(service, '_get_process_exe_path', lambda pid: None)
    service._write_pidfile(76543, uid=service._known_uid)
    assert service._read_pidfile() == 76543
    assert service.is_running()
    assert service._is_our_winws_process(76543)
    killed = []
    monkeypatch.setattr(service, '_kill_pid', lambda pid, **kwargs: killed.append(pid) or True)
    alive = {'value': True}
    monkeypatch.setattr(service, '_pid_alive', lambda pid: alive['value'] and pid == 76543)
    def kill(pid, **kwargs):
        killed.append(pid)
        alive['value'] = False
        return True
    monkeypatch.setattr(service, '_kill_pid', kill)
    assert service.stop()[0]
    assert killed == [76543]
    assert service._read_pidfile() is None


def test_uac_cleanup_refusal_preserves_the_discovered_live_pid(lifecycle, monkeypatch):
    service, exe = lifecycle
    _allow_fake_elevation(service, exe, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    alive = set()
    monkeypatch.setattr(service, "_pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(service, "_scan_pids_with", lambda args: sorted(alive))

    def shell_execute(*args):
        entered.set()
        assert release.wait(3)
        alive.add(76543)
        return 64

    monkeypatch.setattr(service, "_shell_execute_elevated", shell_execute)
    monkeypatch.setattr(service, "_kill_pid", lambda *args, **kwargs: False)
    result = []
    worker = threading.Thread(target=lambda: result.append(service.start()))
    worker.start()
    try:
        assert entered.wait(3)
        assert not service.stop()[0]
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert result and not result[0][0]
    assert service._read_pidfile() == 76543
    assert service.is_running()
    assert service._state == m._STATE_RUNNING


def test_nonempty_log_without_pid_keeps_duplicate_launch_guard(lifecycle, monkeypatch):
    service, exe = lifecycle
    _allow_fake_elevation(service, exe, monkeypatch)
    service._elevation_scan_window = 0

    def shell_execute(*args):
        with open(service.log_file, "ab") as stream:
            stream.write(b"diagnostic startup output: filter installed\n")
        return 64

    monkeypatch.setattr(service, "_shell_execute_elevated", shell_execute)
    ok, _ = service.start()
    assert not ok
    assert service._elevation_pid_unknown, "diagnostic log output is not proof that an undiscovered child exited"
    assert not service.start()[0]


def test_pid_discovery_exception_after_dispatch_keeps_duplicate_launch_guard(lifecycle, monkeypatch):
    service, exe = lifecycle
    _allow_fake_elevation(service, exe, monkeypatch)
    monkeypatch.setattr(service, "_shell_execute_elevated", lambda *args: 64)

    def broken_scan(signature):
        raise RuntimeError("injected discovery failure")

    monkeypatch.setattr(service, "_scan_pids_with", broken_scan)
    try:
        service.start()
    except RuntimeError as error:
        assert str(error) == "injected discovery failure"
    assert service._elevation_pid_unknown, "a failed scanner cannot disprove a dispatched UAC child"
    assert not service.start()[0]


def test_secondary_survivor_counts_as_running_after_primary_exits(lifecycle, monkeypatch):
    service, _ = lifecycle
    service._write_pidfile(76543, pids=[76543, 76544], uid="known")
    monkeypatch.setattr(service, "_pid_alive", lambda pid: pid == 76544)
    monkeypatch.setattr(service, "_is_our_winws_process", lambda pid, *args, **kwargs: pid == 76544)
    assert service.is_running(), "a multi-PID record must not hide its secondary live process"


def test_primary_exit_watcher_preserves_a_secondary_survivor(lifecycle, monkeypatch):
    service, _ = lifecycle
    service._write_pidfile(76543, pids=[76543, 76544], uid="known")
    service._state = m._STATE_RUNNING
    monkeypatch.setattr(service, "_pid_alive", lambda pid: pid == 76544)
    monkeypatch.setattr(service, "_is_our_winws_process", lambda pid, *args, **kwargs: pid == 76544)
    events = []
    service.set_event_callback(lambda name, payload: events.append((name, payload)))
    service._watch_elevated_lifecycle(76543, service._generation)
    assert service._state == m._STATE_RUNNING
    assert 76544 in service._read_pidfile_pids(), "a secondary survivor must remain available to stop()"
    assert events == []


def test_working_directory_does_not_grant_foreign_process_ownership(lifecycle, monkeypatch, tmp_path):
    service, _ = lifecycle
    foreign = str(tmp_path / "unrelated-bypass" / "winws.exe")
    monkeypatch.setattr(m.os, "getcwd", lambda: str(tmp_path))
    monkeypatch.setattr(service, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(service, "_is_winws_process", lambda pid: True)
    monkeypatch.setattr(service, "_get_process_exe_path", lambda pid: foreign)
    assert not service._is_our_winws_process(76543), "a broad inherited CWD is not an application installation root"


def test_selection_cannot_label_an_unknown_existing_strategy_as_preferred(lifecycle, monkeypatch):
    service, _ = lifecycle
    child = WindowsChild()
    service.process = child
    service._state = m._STATE_RUNNING
    launched = []

    def launch(exe, args):
        launched.append(args)
        service.process = WindowsChild(76544)
        return "started", service.process, ""

    monkeypatch.setattr(service, "_launch", launch)
    monkeypatch.setattr(service, "_probe_selection_youtube", lambda: True)
    ok, _, selected = service.select_strategy(preferred="aggressive")
    assert ok and selected == "aggressive"
    assert launched, "first-use selection must actually apply the strategy it saves, even when run.cmd was lost"


def test_interactive_mode_change_passes_stop_elevation_permission(lifecycle, monkeypatch):
    service, _ = lifecycle
    service.process = WindowsChild()
    service._state = m._STATE_RUNNING
    service._last_args = m.PRESET_STRATEGIES['standard'].format(hosts=','.join(m.ZAPRET_SCOPED_HOSTS))
    stops = []
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: stops.append(kw) or (False, 'test boundary'))
    assert not service.start(mode='aggressive', interactive=True)[0]
    assert stops == [{'bump_generation': False, 'allow_elevation': True}]


def test_interactive_mode_change_applies_strategy_when_old_arguments_were_lost(lifecycle, monkeypatch):
    service, _ = lifecycle
    service.process = WindowsChild()
    service._state = m._STATE_RUNNING
    launches = []
    def launch(exe, args):
        launches.append(args)
        service.process = WindowsChild(76544)
        return 'started', service.process, ''
    monkeypatch.setattr(service, '_launch', launch)
    assert service.start(mode='aggressive', interactive=True)[0]
    assert launches, 'an explicit mode change must apply the requested rules even if run.cmd was lost'


def test_stop_after_uac_discovery_does_not_restore_unknown_guard(lifecycle, monkeypatch):
    service, exe = lifecycle
    _allow_fake_elevation(service, exe, monkeypatch)
    alive = set()
    monkeypatch.setattr(service, '_pid_alive', lambda pid: pid in alive)
    monkeypatch.setattr(service, '_scan_pids_with', lambda args: sorted(alive))
    monkeypatch.setattr(service, '_shell_execute_elevated', lambda *args: alive.add(76543) or 64)
    monkeypatch.setattr(service, '_kill_pid', lambda pid, **kw: alive.discard(pid) or True)
    discover = service._launch_elevated_attempt
    def discover_then_stop(*args):
        result = discover(*args)
        assert result[0]
        assert service.stop()[0]
        return result
    monkeypatch.setattr(service, '_launch_elevated_attempt', discover_then_stop)
    assert not service.start()[0]
    assert not alive
    assert not service._elevation_pid_unknown, 'a confirmed stop must not become an unknown UAC result'
