"""Maximize is queued to WinForms and keeps the browser at the client size."""
import sys
from types import SimpleNamespace
import pytest


class Rect:
    def __init__(self, x, y, width, height):
        self.X, self.Y, self.Width, self.Height = x, y, width, height


class View:
    def __init__(self):
        self.Bounds = Rect(0, 0, 1100, 800)
        self.invalidated = 0

    @property
    def Left(self): return self.Bounds.X
    @property
    def Top(self): return self.Bounds.Y
    @property
    def Width(self): return self.Bounds.Width
    @property
    def Height(self): return self.Bounds.Height
    def Invalidate(self): self.invalidated += 1


class Form:
    def __init__(self):
        self.Handle = 1234
        self._state = 'normal'
        self.Bounds = Rect(-1700, 90, 1100, 800)
        self.webview = View()

    @property
    def ClientRectangle(self): return Rect(0, 0, self.Bounds.Width, self.Bounds.Height)
    @property
    def WindowState(self): return self._state
    @WindowState.setter
    def WindowState(self, state):
        self._state = state
        if state == 'maximized': self.Bounds = self.MaximizedBounds
    def PerformLayout(self): pass


@pytest.fixture
def native_window(api, monkeypatch):
    form = Form()
    api._window = SimpleNamespace(native=form)
    work = Rect(-1920, 0, 1920, 1040)
    monkeypatch.setitem(sys.modules, 'System.Drawing', SimpleNamespace(Rectangle=Rect))
    monkeypatch.setitem(sys.modules, 'System.Windows.Forms', SimpleNamespace(
        FormWindowState=SimpleNamespace(Maximized='maximized', Normal='normal'),
        Screen=SimpleNamespace(FromHandle=lambda handle: SimpleNamespace(WorkingArea=work))))
    monkeypatch.setattr('core.api.sys.platform', 'win32')
    pending = []
    monkeypatch.setattr(api, '_deferred_window_op', lambda delay, fn: pending.append(fn))
    monkeypatch.setattr(api, '_on_window_ui_thread', lambda window, fn: fn())
    return form, work, pending


def test_maximize_and_restore_use_monitor_work_area_and_resize_browser(api, native_window):
    form, work, pending = native_window
    api.maximize()
    assert form.WindowState == 'normal', 'bridge must return before native operations'
    pending.pop(0)()
    assert form.MaximizedBounds is work
    assert form.WindowState == 'maximized'
    assert (form.webview.Width, form.webview.Height) == (1920, 1040)
    assert api._is_maximized is True
    api.maximize()
    pending.pop(0)()
    assert form.WindowState == 'normal'
    assert (form.Bounds.X, form.Bounds.Y, form.Bounds.Width, form.Bounds.Height) == (-1700, 90, 1100, 800)
    assert (form.webview.Width, form.webview.Height) == (1100, 800)
    assert api._is_maximized is False


def test_toggle_recognizes_windows_native_maximize(api, native_window):
    form, work, pending = native_window
    form.MaximizedBounds = work
    form.WindowState = 'maximized'
    api._is_maximized = False
    api.maximize()
    pending.pop(0)()
    assert form.WindowState == 'normal'
    assert api._is_maximized is False


def test_native_resize_fits_webview_without_recreating_it(api, native_window):
    form, work, pending = native_window
    view = form.webview
    form.Bounds = work
    api._on_window_resized(1920, 1040)
    assert form.webview is view
    assert (view.Left, view.Top, view.Width, view.Height) == (0, 0, 1920, 1040)
    assert view.invalidated == 1


def test_windows_restore_clears_maximize_resize_guard(api, native_window):
    form, work, pending = native_window
    api._is_maximized = True
    api._on_window_resized(1100, 800)
    assert api._is_maximized is False
