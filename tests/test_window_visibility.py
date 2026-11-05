"""Native window visibility reaches the renderer through the safe event bridge."""

import json
import re
import threading
from types import SimpleNamespace

import pytest

from core.api import AppApi, _MAIN_THREAD
from core.tray import TrayIcon


class WindowEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


class VisibilityWindow:
    def __init__(self):
        self.events = SimpleNamespace(**{
            name: WindowEvent() for name in ['minimized', 'restored', 'maximized', 'shown']
        })
        self.hidden = False
        self.operations = []
        self.scripts = []
        self.evaluation_threads = []
        self.evaluated = threading.Event()

    def hide(self):
        self.operations.append('hide')
        self.hidden = True

    def restore(self):
        self.operations.append('restore')

    def show(self):
        self.operations.append('show')
        self.hidden = False

    def evaluate_js(self, script):
        self.scripts.append(script)
        self.evaluation_threads.append(threading.current_thread())
        self.evaluated.set()


def test_native_host_does_not_use_color_key_transparency_when_theme_requests_alpha():
    """Keep WebView2's GPU client input-opaque at the real creation boundary."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
    create = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == 'create_window')
    transparent = next(item.value for item in create.keywords if item.arg == 'transparent')
    enabled_settings = SimpleNamespace(get=lambda *args: True)
    value = eval(compile(ast.Expression(transparent), 'main.py:create_window', 'eval'),
                 {'app_core': SimpleNamespace(settings=enabled_settings)})
    assert value is False


@pytest.mark.parametrize('method,hidden', [('_on_minimized', True), ('_on_restored', False)])
def test_visibility_callbacks_emit_boolean_payload_without_blocking_ui(method, hidden):
    window = VisibilityWindow()
    api = AppApi.__new__(AppApi)
    api._window = window
    assert threading.current_thread() is _MAIN_THREAD

    getattr(api, method)()

    assert window.evaluated.wait(timeout=2)
    assert all(thread is not _MAIN_THREAD for thread in window.evaluation_threads)
    match = re.search(r'window\.onPythonEvent\("window_visibility", (.*)\); \}', window.scripts[0])
    assert match is not None
    assert json.loads(match.group(1)) == {'hidden': hidden}


def test_set_window_wires_native_minimize_restore_maximize_and_show(monkeypatch):
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace()
    window = VisibilityWindow()
    emitted = []
    monkeypatch.setattr(api, '_install_snap_layouts', lambda: True)
    monkeypatch.setattr(api, '_emit', lambda event, data: emitted.append((event, data)))

    api.set_window(window)
    for name in ['minimized', 'restored', 'minimized', 'maximized', 'minimized', 'shown']:
        getattr(window.events, name).fire()

    assert emitted == [
        ('window_visibility', {'hidden': True}),
        ('window_visibility', {'hidden': False}),
        ('window_visibility', {'hidden': True}),
        ('window_visibility', {'hidden': False}),
        ('window_visibility', {'hidden': True}),
        ('window_visibility', {'hidden': False}),
    ]


def test_tray_show_restores_hidden_window_and_publishes_visibility_after_native_operation(monkeypatch):
    api = AppApi.__new__(AppApi)
    api._core = SimpleNamespace(settings=SimpleNamespace(get=lambda *args: True))
    window = VisibilityWindow()
    api._window = window
    tray = TrayIcon.__new__(TrayIcon)
    tray.api = api
    tray.icon = object()
    api._tray = tray
    emitted = []
    monkeypatch.setattr(api, '_emit', lambda event, data: emitted.append((event, data, window.hidden)))

    # X now fully exits. Retain coverage of the tray's explicit restore path
    # for windows hidden by the OS or by an existing native tray action.
    window.hide()
    api._on_minimized()
    tray.on_show()

    assert window.operations == ['hide', 'restore', 'show']
    assert emitted == [
        ('window_visibility', {'hidden': True}, True),
        ('window_visibility', {'hidden': False}, False),
    ]


def test_failed_tray_show_does_not_publish_visible(monkeypatch):
    api = AppApi.__new__(AppApi)
    window = VisibilityWindow()
    api._window = window
    tray = TrayIcon.__new__(TrayIcon)
    tray.api = api
    emitted = []
    monkeypatch.setattr(api, '_emit', lambda event, data: emitted.append((event, data)))

    def failed_show():
        raise RuntimeError('Native window unavailable')

    monkeypatch.setattr(window, 'show', failed_show)
    tray.on_show()

    assert emitted == []
