"""Returning from Zapret UAC must not leave a live player hidden."""

import ctypes
from types import SimpleNamespace

import pytest

from services.zapret_service import ZapretService


class NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


@pytest.fixture
def elevation(redirect_home, monkeypatch):
    service = ZapretService()
    state = SimpleNamespace(hwnd=1234, visible=True, minimized=False,
                            alive=True, result=64, shown=[], calls=[], action=None)

    def execute(*args):
        state.calls.append(args)
        if state.action:
            state.action()
        return state.result

    user32 = SimpleNamespace(
        IsWindowVisible=lambda hwnd: state.visible,
        IsIconic=lambda hwnd: state.minimized,
        IsWindow=lambda hwnd: state.alive,
        ShowWindowAsync=NativeCall(lambda hwnd, mode: state.shown.append((hwnd.value, mode))),
    )
    shell32 = SimpleNamespace(ShellExecuteW=NativeCall(execute))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, shell32=shell32))
    service._set_elevation_window(lambda: state.hwnd)
    return service, state


@pytest.mark.parametrize("result", [64, 5, 31])
def test_uac_returns_player_to_screen_on_success_cancel_or_failure(elevation, result):
    service, state = elevation
    state.result = result
    state.action = lambda: setattr(state, "visible", False)
    assert service._shell_execute_elevated("cmd.exe", "/c winws.exe", "C:\\zapret") == result
    assert state.shown == [(1234, 8)]
    owner, verb, exe, params, cwd, show = state.calls[0]
    assert (owner.value, verb, exe, params, cwd, show) == (
        1234, "runas", "cmd.exe", "/c winws.exe", "C:\\zapret", 0)


def test_visible_window_is_not_shown_again(elevation):
    service, state = elevation
    service._shell_execute_elevated("cmd.exe", "", "")
    assert state.shown == []


@pytest.mark.parametrize("visible,minimized", [(False, False), (True, True)])
def test_previously_hidden_or_minimized_player_stays_that_way(elevation, visible, minimized):
    service, state = elevation
    state.visible, state.minimized = visible, minimized
    state.action = lambda: setattr(state, "visible", False)
    service._shell_execute_elevated("cmd.exe", "", "")
    assert state.shown == []


@pytest.mark.parametrize("changed,value", [("hwnd", 5678), ("alive", False), ("minimized", True)])
def test_closed_replaced_or_newly_minimized_window_is_not_restored(elevation, changed, value):
    service, state = elevation

    def action():
        state.visible = False
        setattr(state, changed, value)

    state.action = action
    service._shell_execute_elevated("cmd.exe", "", "")
    assert state.shown == []


def test_headless_launch_does_not_require_a_window(elevation):
    service, state = elevation
    service._set_elevation_window(None)
    assert service._shell_execute_elevated("cmd.exe", "", "") == 64
    assert state.calls[0][0] is None
    assert state.shown == []


def test_api_registers_window_for_both_manual_and_autostart_zapret(api, core_ns, monkeypatch):
    providers = []
    core_ns.zapret = SimpleNamespace(_set_elevation_window=providers.append)
    monkeypatch.setattr(api, "_install_snap_layouts", lambda: None)
    monkeypatch.setattr(api, '_get_hwnd', lambda: 1234)  # validated native handle supplied by the platform layer
    api.set_window(SimpleNamespace(hwnd=1234))
    assert len(providers) == 1
    assert providers[0]() == 1234
