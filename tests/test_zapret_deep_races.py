"""Additional scheduling regressions. All handles/processes/network are fake."""
import threading
import pytest

import services.zapret_service as m
from tests.test_zapret_deep_lifecycle import lifecycle, WindowsChild
from tests.test_zapret_deep_install_update import service as update_service, _provide_archive


def test_old_stop_waiting_for_guard_cannot_terminate_a_new_generation(lifecycle, monkeypatch):
    service, _ = lifecycle
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    def acquire(*args):
        if threading.get_ident() != main_thread:
            entered.set()
            assert release.wait(3)
        return None
    monkeypatch.setattr(m, '_global_zapret_guard_acquire', acquire)
    result = []
    worker = threading.Thread(target=lambda: result.append(service.stop()))
    worker.start()
    new_child = WindowsChild(76544)
    closed = []
    monkeypatch.setattr(m, '_win32_close_handle', lambda handle: closed.append(handle))
    try:
        assert entered.wait(3)
        with service._lock:
            service._generation += 1
            service.process = new_child
            service._job_handle = 12345
            service._state = m._STATE_RUNNING
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert not result[0][0]
    assert service.process is new_child and new_child.poll() is None
    assert service._state == m._STATE_RUNNING
    assert closed == [], 'stale stop must not close the newer kill-on-close Job'


def test_stale_status_probe_cannot_publish_a_network_outage(lifecycle, monkeypatch):
    service, exe = lifecycle
    service._last_network_ok = True
    events = []
    service.set_event_callback(lambda name, data: events.append(name))
    monkeypatch.setattr(service, 'is_running', lambda: True)
    def network_probe():
        with service._lock:
            service._generation += 1
            service._state = m._STATE_STOPPED
        return False
    monkeypatch.setattr(m, 'check_internet', network_probe)
    service._build_status()
    assert events == [], 'a discarded status snapshot must not emit an outage'
    assert service._last_network_ok is True


def test_update_cannot_replace_binaries_during_another_launch(update_service, monkeypatch):
    service = update_service
    _provide_archive(service, monkeypatch)
    service._state = m._STATE_STARTING
    service._start_owner = -1
    extractions = []
    monkeypatch.setattr(service, '_extract_zip', lambda data: extractions.append(True))
    assert not service.update_zapret(force=True)[0]
    assert extractions == []


def test_launch_cannot_enter_while_binary_swap_is_in_progress(update_service, monkeypatch):
    service = update_service
    _provide_archive(service, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = service._extract_zip
    def extract(data):
        original(data)
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(service, '_extract_zip', extract)
    launches = []
    monkeypatch.setattr(service, '_launch', lambda *args: launches.append(True) or ('failed', None, 'boundary'))
    results = []
    worker = threading.Thread(target=lambda: results.append(service.update_zapret(force=True)))
    worker.start()
    try:
        assert entered.wait(3)
        assert not service.start()[0]
        assert launches == []
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize('extraction_fails', [False, True])
def test_user_stop_during_update_cancels_automatic_restart(update_service, monkeypatch, extraction_fails):
    service = update_service
    _provide_archive(service, monkeypatch)
    alive = {'value': True}
    monkeypatch.setattr(service, 'is_running', lambda: alive['value'])
    def stop():
        with service._lock:
            service._generation += 1
        alive['value'] = False
        return True, 'stopped'
    monkeypatch.setattr(service, 'stop', stop)
    original = service._extract_zip
    def extract(data):
        original(data)
        stop()  # newer explicit stop while update IO was in progress
        if extraction_fails:
            raise OSError('injected swap failure')
    monkeypatch.setattr(service, '_extract_zip', extract)
    starts = []
    monkeypatch.setattr(service, 'start', lambda **kw: starts.append(kw) or (True, 'started'))
    service.update_zapret(force=True)
    assert starts == [], 'neither restart nor rollback recovery may override a newer stop'
