"""First-install contracts; no real UAC, driver or service is started."""

import io
import os
import threading
from types import SimpleNamespace
import zipfile

import pytest

import services.zapret_service as m
from tests.test_zapret_binary_integrity import _pe
from tests.test_zapret_lifecycle_a1 import FakeProc
from tests.test_zapret_winapi_b1 import _setup_allowed_elevation


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setattr(m.sys, "frozen", True, raising=False)
    monkeypatch.setattr(m.sys, "executable", str(root / "NeDotify.exe"))
    monkeypatch.setattr(m, "_query_registry_install_location", lambda: str(root))
    service = m.ZapretService()
    return service, root


def test_clean_installed_download_is_eligible_for_existing_uac_gate(installed, monkeypatch):
    service, root = installed
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name in ("winws.exe", "WinDivert.dll", "WinDivert64.sys", "cygwin1.dll"):
            archive.writestr("zapret/binaries/windows-x86_64/" + name, _pe())
    # The real pinned archive is covered separately; this test isolates routing.
    monkeypatch.setattr(service, "_download_zip", lambda *a, **kw: buf.getvalue())
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a: True)
    ok, message = service.download_binaries()
    assert ok, message
    assert service.find_binary() == str(root / "zapret" / "winws.exe")
    assert m._protected_elevation_path(service.find_binary())
    assert os.path.isfile(os.path.join(service.app_dir, "version.json"))


def test_installed_bundle_wins_over_old_non_elevatable_profile_copy(installed):
    service, root = installed
    bundle = root / "zapret"
    bundle.mkdir()
    (bundle / "winws.exe").write_bytes(_pe())
    with open(os.path.join(service.app_dir, "winws.exe"), "wb") as stream:
        stream.write(_pe())
    assert service.find_binary() == str(bundle / "winws.exe")


def test_profile_only_copy_is_reinstalled_into_verified_install(installed, monkeypatch):
    service, root = installed
    with open(os.path.join(service.app_dir, "winws.exe"), "wb") as stream:
        stream.write(_pe())
    calls = []

    def install():
        calls.append(1)
        bundle = root / "zapret"
        bundle.mkdir(exist_ok=True)
        (bundle / "winws.exe").write_bytes(_pe())
        return True, "downloaded"

    monkeypatch.setattr(service, "download_binaries", install)
    monkeypatch.setattr(service, "_get_pending_update", lambda: "")
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda *a: None)
    monkeypatch.setattr(service, "_classify_running_winws", lambda: (None, None))
    launched = []
    monkeypatch.setattr(service, "_launch", lambda exe, args: launched.append(exe) or ("failed", None, "test boundary"))
    service.start()
    assert calls == [1]
    assert launched == [str(root / "zapret" / "winws.exe")]


def test_correcting_rejected_path_allows_next_normal_download(tmp_path, monkeypatch):
    service = m.ZapretService()
    service.base_dir = str(tmp_path)
    assert service.find_binary(str(tmp_path / "missing.exe")) is None
    calls = []
    monkeypatch.setattr(service, "download_binaries", lambda: calls.append(1) or (False, "offline"))
    ok, _ = service.start(binary_path="")
    assert not ok
    assert calls == [1], "a previous rejected path must not poison a corrected attempt"


def test_uac_dispatch_without_process_evidence_is_not_success(tmp_path, monkeypatch):
    service = m.ZapretService()
    exe = os.path.join(service.app_dir, "winws.exe")
    with open(exe, "wb") as stream:
        stream.write(_pe())
    _setup_allowed_elevation(service, monkeypatch, exe)
    monkeypatch.setattr(service, "_read_pidfile", lambda: None)
    monkeypatch.setattr(service, "_scan_pids_with", lambda sig: [])
    monkeypatch.setattr(service, "_scan_all_winws_pids", lambda: [])
    ok, message = service._launch_elevated(exe, "--wf-tcp=80,443")
    assert not ok, "ShellExecute success alone does not prove winws started"
    assert not service.is_running()
    assert service._elevation_pid_unknown
    assert "PID" in message


def test_uncertain_uac_dispatch_blocks_duplicate_launch(monkeypatch):
    service = m.ZapretService()
    service._elevation_pid_unknown = True
    launched = []
    monkeypatch.setattr(service, "_launch", lambda *a: launched.append(1))
    ok, message = service.start()
    assert not ok
    assert not launched
    assert "PID" in message


def test_start_discards_pre_toggle_status_cache(monkeypatch):
    service = m.ZapretService()
    service._status_cache = {"running": False, "message": "old stopped status"}
    monkeypatch.setattr(service, "_start_with_generation", lambda *a: (True, "started"))
    service.start()
    assert service._status_cache is None


def test_stop_discards_pre_toggle_status_cache(monkeypatch):
    service = m.ZapretService()
    service._status_cache = {"running": True, "message": "old running status"}
    monkeypatch.setattr(service, "_stop_impl", lambda **kw: (True, "stopped"))
    service.stop()
    assert service._status_cache is None


def test_installed_archive_missing_driver_does_not_replace_bundle(installed, monkeypatch):
    service, root = installed
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("zapret/windows-x86_64/winws.exe", _pe())
    monkeypatch.setattr(service, "_download_zip", lambda *a, **kw: buf.getvalue())
    monkeypatch.setattr(m, "_verify_zip_sha256", lambda *a: True)
    ok, message = service.download_binaries()
    assert not ok
    assert "windivert64.sys" in message
    assert not (root / "zapret" / "winws.exe").exists()


def test_uncertain_launch_cannot_claim_successful_stop(monkeypatch):
    service = m.ZapretService()
    service._elevation_pid_unknown = True
    monkeypatch.setattr(m, "_global_zapret_guard_acquire", lambda *a: None)
    monkeypatch.setattr(m, "_global_zapret_guard_release", lambda *a: None)
    monkeypatch.setattr(service, "_scan_all_winws_pids", lambda: [])
    monkeypatch.setattr(service, "_scan_pids_with", lambda sig: [])
    ok, message = service.stop()
    assert not ok
    assert service._elevation_pid_unknown
    assert "PID" in message


@pytest.mark.parametrize("allow_elevation,accepted", [(False, True), (True, True), (True, False)])
def test_only_explicit_stop_can_request_uac(monkeypatch, allow_elevation, accepted):
    service = m.ZapretService()
    state = {"alive": True, "uac": []}
    monkeypatch.setattr(service, "_pid_alive", lambda pid: state["alive"])
    monkeypatch.setattr(service, "_is_winws_process", lambda pid: True)
    monkeypatch.setattr(service, "_is_our_winws_process", lambda pid: True)
    monkeypatch.setattr(service, "_get_process_exe_path", lambda pid: r"C:\verified\winws.exe")
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(m.time, "sleep", lambda *a: None)
    ticks = iter(range(100))
    monkeypatch.setattr(m.time, "time", lambda: next(ticks))

    def elevate(exe, params, cwd):
        state["uac"].append((exe, params))
        if accepted:
            state["alive"] = False
        return 42 if accepted else 5

    monkeypatch.setattr(service, "_shell_execute_elevated", elevate)
    assert service._kill_pid(1234, allow_elevation=allow_elevation) is (allow_elevation and accepted)
    assert len(state["uac"]) == int(allow_elevation)
    if allow_elevation:
        exe, params = state["uac"][0]
        assert exe.lower().endswith("taskkill.exe")
        assert "/PID 1234" in params
        assert "winws.exe" in params


def test_elevated_process_crash_resyncs_state_and_emits_event(monkeypatch):
    service = m.ZapretService()
    service._state = m._STATE_RUNNING
    service._status_cache = {"running": True}
    service._write_pidfile(4321)
    events = []
    service.set_event_callback(lambda *args: events.append(args))
    monkeypatch.setattr(service, "_pid_alive", lambda pid: False)
    service._watch_elevated_lifecycle(4321, service._generation)
    assert service._state == m._STATE_STOPPED
    assert service._status_cache is None
    assert service._read_pidfile() is None
    assert events[0][0] == "zapret_crashed"


def test_elevated_watcher_never_clears_newer_process(monkeypatch):
    service = m.ZapretService()
    service._state = m._STATE_RUNNING
    service._write_pidfile(9876)
    service._generation = 2
    events = []
    service.set_event_callback(lambda *args: events.append(args))
    monkeypatch.setattr(service, "_pid_alive", lambda pid: False)
    service._watch_elevated_lifecycle(4321, 1)
    assert service._read_pidfile() == 9876
    assert events == []


def test_status_builder_cannot_publish_snapshot_from_before_stop(monkeypatch):
    service = m.ZapretService()
    running = {"value": True}
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(service, "find_binary", lambda *a: "winws.exe")
    monkeypatch.setattr(service, "is_running", lambda: running["value"])
    monkeypatch.setattr(service, "get_local_version", lambda: m.ZAPRET_VERSION)
    monkeypatch.setattr(service, "_get_pending_update", lambda: "")
    monkeypatch.setattr(m, "_probe_covered_host", lambda: True)

    def probe():
        entered.set()
        assert release.wait(3)
        return True

    def stop(**kwargs):
        running["value"] = False
        return True, "stopped"

    monkeypatch.setattr(m, "check_internet", probe)
    monkeypatch.setattr(service, "_stop_impl", stop)
    worker = threading.Thread(target=service._build_status)
    worker.start()
    assert entered.wait(3)
    service.stop()
    release.set()
    worker.join(3)
    assert service._status_cache is None, "pre-stop running snapshot must be discarded"


def test_get_status_is_safe_when_refresh_invalidates_cache(monkeypatch):
    service = m.ZapretService()
    monkeypatch.setattr(service, "_refresh_status_async", lambda: setattr(service, "_status_cache", None))
    status = service.get_status()
    assert isinstance(status, dict)
    assert status["running"] is False


def test_popen_late_crash_invalidates_status_snapshot():
    service = m.ZapretService()
    service._state = m._STATE_RUNNING
    service.process = proc = FakeProc()
    service._status_cache = {"running": True}
    epoch = service._status_epoch
    proc.crash(2)
    service._watch_child_lifecycle(proc, service._generation)
    assert service._status_cache is None
    assert service._status_epoch > epoch


def test_popen_watcher_rearms_for_new_generation(monkeypatch):
    service = m.ZapretService()
    service._state = m._STATE_RUNNING
    service.process = proc = FakeProc()
    started = []
    from types import SimpleNamespace
    monkeypatch.setattr(m.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: started.append(kw)))
    service._ensure_lifecycle_watcher()
    service._ensure_lifecycle_watcher()
    service._generation += 1
    service._ensure_lifecycle_watcher()
    assert len(started) == 2
    assert started[1]["target"] == service._watch_child_lifecycle
    assert started[1]["args"] == (proc, service._generation)


@pytest.mark.parametrize("command", ["start", "stop", "stop_interactive"])
def test_commands_that_leave_detached_process_running_rearm_watcher(monkeypatch, command):
    service = m.ZapretService()
    service._state = m._STATE_RUNNING
    service._write_pidfile(1234)
    armed = []
    monkeypatch.setattr(service, "_ensure_lifecycle_watcher", lambda: armed.append(service._generation))

    def start(*args):
        service._state = m._STATE_RUNNING
        return True, "already running"

    def stop(**kwargs):
        service._generation += 1
        service._state = m._STATE_RUNNING
        return False, "still running"

    monkeypatch.setattr(service, "_start_with_generation", start)
    monkeypatch.setattr(service, "_stop_impl", stop)
    getattr(service, command)()
    assert armed == [service._generation]


@pytest.mark.parametrize("administrator,cancel_first_uac", [(True, False), (False, False), (False, True)])
def test_actual_bridge_first_install_toggle_stop_retry(installed, monkeypatch, administrator, cancel_first_uac):
    """Real bridge + service + extraction + gate; only OS/network are faked."""
    from core.api import AppApi
    service, root = installed
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        for name in m._REQUIRED_BUNDLE_FILES:
            archive.writestr('zapret/windows-x86_64/' + name, _pe())
    monkeypatch.setattr(service, '_download_zip', lambda *a, **kw: payload.getvalue())
    monkeypatch.setattr(m, '_verify_zip_sha256', lambda *a: True)
    monkeypatch.setattr(m, '_global_zapret_guard_acquire', lambda *a: None)
    monkeypatch.setattr(m, '_global_zapret_guard_release', lambda *a: None)
    monkeypatch.setattr(m, '_win32_create_kill_on_close_job', lambda: None)
    monkeypatch.setattr(service, '_classify_running_winws', lambda: (None, None))
    state = {'alive': False, 'cancel': cancel_first_uac, 'uac': 0, 'process': None}
    service._launch_confirm_window = 0
    service._elevation_scan_window = .01

    def popen(*a, **kw):
        if not administrator:
            error = OSError('Elevation required')
            error.winerror = 740
            raise error
        state['process'] = FakeProc(pid=1234)
        return state['process']

    def elevate(*a):
        state['uac'] += 1
        if state['cancel']:
            return 5
        state['alive'] = True
        return 42

    def alive(pid):
        proc = state['process']
        return bool(pid == 1234 and (proc.poll() is None if proc else state['alive']))

    monkeypatch.setattr(m.subprocess, 'Popen', popen)
    monkeypatch.setattr(service, '_shell_execute_elevated', elevate)
    monkeypatch.setattr(service, '_pid_alive', alive)
    monkeypatch.setattr(service, '_get_process_creation_time', lambda pid: 111)
    monkeypatch.setattr(service, '_is_our_winws_process', lambda pid, *a, **kw: pid == 1234)
    monkeypatch.setattr(service, '_scan_pids_with', lambda sig: [1234] if alive(1234) else [])
    monkeypatch.setattr(service, '_scan_all_winws_pids', lambda: [])
    monkeypatch.setattr(service, '_kill_pid', lambda pid, **kw: state.update(alive=False) or True)
    values = {}
    settings = SimpleNamespace(set=lambda cat, key, value: values.update({(cat, key): value}),
                               get=lambda cat, key, default=None: values.get((cat, key), default))
    monkeypatch.setattr(service, '_probe_selection_youtube', lambda: True)
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace(zapret=service, settings=settings)
    first = api.toggle_zapret(True)
    assert first['success'] is (not cancel_first_uac)
    assert first['running'] is (not cancel_first_uac)
    assert values[('zapret', 'enabled')] is first['running']
    if cancel_first_uac:
        assert 'UAC' in first['message']
        state['cancel'] = False
        assert api.toggle_zapret(True)['success']
    assert service.find_binary() == str(root / 'zapret/winws.exe')
    assert service.is_running()
    stopped = api.toggle_zapret(False)
    assert stopped['success'] and not stopped['running']
    assert values[('zapret', 'enabled')] is False
    assert state['uac'] == (0 if administrator else 2 if cancel_first_uac else 1)


@pytest.mark.network
def test_real_pinned_archive_first_install_without_starting_driver(installed):
    service, root = installed
    ok, message = service.download_binaries()
    assert ok, message
    assert service.find_binary() == str(root / "zapret" / "winws.exe")
    assert m._protected_elevation_path(service.find_binary())
    for name in m._REQUIRED_BUNDLE_FILES:
        assert m.is_valid_windows_binary(str(root / "zapret" / name)), name
    assert service.get_local_version() == m.ZAPRET_VERSION
    assert not service.is_running()
