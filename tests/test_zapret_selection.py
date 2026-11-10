from types import SimpleNamespace
import threading
import pytest
import requests

from services.zapret_service import ZapretService, PRESET_STRATEGIES
from core.api import AppApi


def prepare(monkeypatch, checks):
    service = ZapretService()
    calls = []
    results = iter(checks)
    monkeypatch.setattr(service, 'start', lambda **kw: calls.append(kw['mode']) or (True, 'ok'))
    monkeypatch.setattr(service, 'is_running', lambda: True)
    monkeypatch.setattr(service, '_probe_selection_youtube', lambda: next(results))
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: (True, 'stopped'))
    return service, calls


def test_selection_stops_at_first_verified_strategy(monkeypatch):
    service, calls = prepare(monkeypatch, [False, True])
    ok, message, mode = service.select_strategy()
    assert ok
    assert len(calls) == 2
    assert mode == calls[-1]
    assert not service._selection_active


def test_selection_never_accepts_process_without_https(monkeypatch):
    service, calls = prepare(monkeypatch, [False] * len(PRESET_STRATEGIES))
    ok, _, _ = service.select_strategy()
    assert not ok
    assert len(calls) == len(PRESET_STRATEGIES)


def test_selection_aborts_if_previous_process_cannot_stop(monkeypatch):
    service, calls = prepare(monkeypatch, [False])
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: (False, 'cannot stop'))
    ok, message, _ = service.select_strategy()
    assert not ok
    assert message == 'cannot stop'
    assert len(calls) == 1


def test_cancel_during_probe_never_accepts_success(monkeypatch):
    service, calls = prepare(monkeypatch, [])
    def probe():
        service._selection_cancel.set()
        return True
    monkeypatch.setattr(service, '_probe_selection_youtube', probe)
    ok, _, _ = service.select_strategy()
    assert not ok
    assert len(calls) == 1


def test_probe_exception_stops_our_process_and_allows_retry(monkeypatch):
    service, _ = prepare(monkeypatch, [])
    stops = []
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: stops.append(kw) or (True, 'ok'))
    def broken():
        raise RuntimeError('probe unavailable')
    monkeypatch.setattr(service, '_probe_selection_youtube', broken)
    assert not service.select_strategy()[0]
    assert len(stops) == 1
    assert not service._selection_active
    monkeypatch.setattr(service, '_probe_selection_youtube', lambda: True)
    assert service.select_strategy()[0]


def test_start_exception_after_process_creation_is_cleaned_up(monkeypatch):
    service, _ = prepare(monkeypatch, [])
    stops = []
    def broken_start(**kwargs):
        raise RuntimeError('state write failed after launch')
    monkeypatch.setattr(service, 'start', broken_start)
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: stops.append(kw) or (True, 'ok'))
    assert not service.select_strategy()[0]
    assert len(stops) == 1
    assert not service._selection_active


def test_cancel_after_probe_reports_failed_cleanup(monkeypatch):
    service, _ = prepare(monkeypatch, [])
    def probe():
        service.cancel_selection()
        return True
    monkeypatch.setattr(service, '_probe_selection_youtube', probe)
    monkeypatch.setattr(service, '_stop_impl', lambda **kw: (False, 'stop denied'))
    ok, message, _ = service.select_strategy()
    assert not ok
    assert message == 'stop denied'


def test_new_start_during_selection_cannot_replace_its_process(monkeypatch):
    service = ZapretService()
    entered, release = threading.Event(), threading.Event()
    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return False, 'test boundary'
    monkeypatch.setattr(service, '_start_with_generation', launch)
    result = []
    worker = threading.Thread(target=lambda: result.append(service.select_strategy()))
    worker.start()
    try:
        assert entered.wait(3)
        assert not service.start(mode='standard')[0]
        assert service.cancel_selection()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert not result[0][0]


def test_api_cancel_does_not_overwrite_selected_mode(monkeypatch):
    service, _ = prepare(monkeypatch, [True])
    values = {}
    settings = SimpleNamespace(
        get=lambda c, k, default=None: values.get((c, k), default),
        set=lambda c, k, value: values.update({(c, k): value}))
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace(zapret=service, settings=settings)
    def probe():
        response = api.toggle_zapret(False, mode='aggressive')
        assert response['pending']
        assert ('zapret', 'mode') not in values
        return True
    monkeypatch.setattr(service, '_probe_selection_youtube', probe)
    result = api.toggle_zapret(True)
    assert not result['success']
    assert not values.get(('zapret', 'strategy_selected'), False)


def test_api_saves_selected_mode_and_skips_selection_on_next_start(monkeypatch):
    service, calls = prepare(monkeypatch, [False, True])
    values = {}
    settings = SimpleNamespace(
        get=lambda c, k, default=None: values.get((c, k), default),
        set=lambda c, k, value: values.update({(c, k): value}))
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace(zapret=service, settings=settings)
    assert api.toggle_zapret(True)['success']
    mode = calls[-1]
    assert values[('zapret', 'mode')] == mode
    assert values[('zapret', 'strategy_selected')] is True
    assert api.toggle_zapret(True, mode=mode)['success']
    assert len(calls) == 3


@pytest.mark.parametrize('statuses,expected', [([204, 200], True), ([204, 403], False), ([302], False)])
def test_probe_requires_both_https_endpoints_and_bypasses_environment_proxy(monkeypatch, statuses, expected):
    import services.zapret_probe as media_probe
    monkeypatch.setattr(media_probe, 'probe_youtube_audio', lambda cancelled: True)
    service = ZapretService()
    called = []
    class Response:
        def __init__(self, status):
            self.status_code = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs['timeout'] == (4, 4)
            called.append(url)
            return Response(statuses[len(called) - 1])
    monkeypatch.setattr(requests, 'Session', Session)
    assert service._probe_selection_youtube() is expected
    if expected:
        assert len(called) == 2


def test_stop_during_probe_cannot_be_accepted_as_success(monkeypatch):
    service, _ = prepare(monkeypatch, [])
    stops = []
    def stop(**kwargs):
        stops.append(kwargs)
        service._generation += 1
        return True, 'ok'
    monkeypatch.setattr(service, '_stop_impl', stop)
    def probe():
        service.stop()
        return True
    monkeypatch.setattr(service, '_probe_selection_youtube', probe)
    assert not service.select_strategy()[0]
    assert len(stops) == 1
