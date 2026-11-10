"""Adversarial bridge/autostart contracts; no real processes or networking."""
import threading
from types import SimpleNamespace

import pytest

from core.api import AppApi
from core.app import AppCore


class Settings:
    def __init__(self, **values):
        self.values = {('zapret', key): value for key, value in values.items()}
    def get(self, category, key, default=None):
        return self.values.get((category, key), default)
    def set(self, category, key, value):
        self.values[category, key] = value


def api_for(settings):
    calls = []
    service = SimpleNamespace(
        start=lambda **kw: calls.append(('start', kw)) or (False, 'rejected'),
        select_strategy=lambda **kw: calls.append(('select', kw)) or (False, 'rejected', kw['preferred']),
        stop=lambda: calls.append(('stop', {})) or (True, 'stopped'),
        is_running=lambda: False)
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace(settings=settings, zapret=service)
    return api, calls


@pytest.mark.parametrize('enabled', ['false', 'true', 1, 0, None, {}])
def test_toggle_rejects_nonboolean_commands_without_launching(enabled):
    api, calls = api_for(Settings(strategy_selected=True))
    result = api.toggle_zapret(enabled)
    assert not result['success']
    assert calls == []


def test_disabled_toggle_preserves_the_saved_strategy_configuration():
    settings = Settings(mode='custom', custom_args='--wf-tcp=443', binary_path='C:/approved/winws.exe')
    api, _ = api_for(settings)
    assert api.toggle_zapret(False)['success']
    assert settings.get('zapret', 'mode') == 'custom'
    assert settings.get('zapret', 'custom_args') == '--wf-tcp=443'
    assert settings.get('zapret', 'binary_path') == 'C:/approved/winws.exe'


def test_failed_start_cannot_poison_last_saved_working_strategy():
    settings = Settings(strategy_selected=True, mode='standard', custom_args='', binary_path='')
    api, _ = api_for(settings)
    assert not api.toggle_zapret(True, mode='invalid-preset')['success']
    assert settings.get('zapret', 'mode') == 'standard'


def test_string_false_selection_flag_does_not_skip_first_selection():
    api, calls = api_for(Settings(strategy_selected='false'))
    api.toggle_zapret(True)
    assert calls[0][0] == 'select'


def test_user_mode_switch_can_request_rights_to_stop_its_old_strategy():
    api, calls = api_for(Settings(strategy_selected=True))
    api.toggle_zapret(True, mode='aggressive')
    assert calls[0][1]['interactive'] is True


@pytest.mark.parametrize('changed', ['auto_start', 'mode'])
def test_queued_autostart_observes_current_settings(monkeypatch, changed):
    import core.app as app_module
    settings = Settings(enabled=True, auto_start=True, mode='standard')
    starts = []
    pending = []
    class QueuedWorker:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            pending.append(self.target)
        def is_alive(self):
            return True
    core = SimpleNamespace(settings=settings, _shutting_down=threading.Event(),
        _service_lock=threading.RLock(), _zapret_start_thread=None,
        zapret=SimpleNamespace(start=lambda **kw: starts.append(kw) or (True, 'ok'),
                               is_running=lambda: False))
    monkeypatch.setattr(app_module.threading, 'Thread', QueuedWorker)
    AppCore.start_zapret_if_enabled(core)
    assert len(pending) == 1
    settings.set('zapret', changed, False if changed == 'auto_start' else 'multisplit')
    pending[0]()
    if changed == 'auto_start':
        assert starts == []
    else:
        assert starts[0]['mode'] == 'multisplit'
