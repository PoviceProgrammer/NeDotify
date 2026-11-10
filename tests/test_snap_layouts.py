"""Snap Layouts hit-testing for the frameless window (core/snap_layouts.py).

The Windows side cannot run headless, so the tests drive _hit_test directly
with synthetic WM_NCHITTEST lparams. That is where every real bug lives: an
off-by-one in the grip, a button rectangle read in the wrong coordinate space
(device px vs CSS px), or a hit test that swallows the caption area.
"""

import pytest

from core.snap_layouts import (
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTCLIENT,
    HTLEFT,
    HTMAXBUTTON,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    SnapLayouts,
)

W, H = 1100, 800
GRIP = 6


def _lparam(x, y):
    """Build a WM_NCHITTEST lparam: LOWORD=x, HIWORD=y (both signed short)."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class _FakeUser32:
    """Only GetClientRect is called during a hit test.

    It receives the object behind ctypes.byref(RECT()), which exposes the real
    structure through ``._obj`` - the same way the genuine user32 call works.
    """

    def __init__(self, w, h):
        self._w = w
        self._h = h
        self.origin = (0, 0)
        self.dpi = 96
        self.zoomed = False

    def ScreenToClient(self, hwnd, point):
        point._obj.x -= self.origin[0]
        point._obj.y -= self.origin[1]
        return 1

    def GetDpiForWindow(self, hwnd):
        return self.dpi

    def IsZoomed(self, hwnd):
        return self.zoomed

    def GetClientRect(self, hwnd, rc):
        rc._obj.left = 0
        rc._obj.top = 0
        rc._obj.right = self._w
        rc._obj.bottom = self._h
        return 1


@pytest.fixture
def snap(monkeypatch):
    import ctypes

    s = SnapLayouts(hwnd=1234)
    s._edge_grip = GRIP
    fake = _FakeUser32(W, H)
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": fake})())
    return s


# ── the maximise button ──────────────────────────────────────────────────

def test_hit_inside_maximize_button_reports_htmaxbutton(snap):
    snap.set_button_rect(1040, 4, 40, 28)
    # Centre of the button.
    assert snap._hit_test(_lparam(1060, 18)) == HTMAXBUTTON


def test_button_edges_are_inclusive(snap):
    snap.set_button_rect(100, 100, 30, 20)
    assert snap._hit_test(_lparam(100, 100)) == HTMAXBUTTON
    assert snap._hit_test(_lparam(130, 120)) == HTMAXBUTTON


def test_pixel_outside_button_is_not_htmaxbutton(snap):
    snap.set_button_rect(100, 100, 30, 20)
    assert snap._hit_test(_lparam(131, 110)) != HTMAXBUTTON
    assert snap._hit_test(_lparam(110, 121)) != HTMAXBUTTON


def test_button_takes_priority_over_the_top_edge(snap):
    """A button sitting in the top-right corner must not be read as HTTOPRIGHT."""
    snap.set_button_rect(W - 60, 0, 40, GRIP)
    assert snap._hit_test(_lparam(W - 40, 2)) == HTMAXBUTTON


def test_without_a_reported_rect_no_pixel_is_the_button(snap):
    assert snap._btn_rect is None
    assert snap._hit_test(_lparam(550, 400)) == HTCLIENT


def test_malformed_rect_is_ignored(snap):
    snap.set_button_rect("a", None, {}, [])
    assert snap._hit_test(_lparam(550, 400)) == HTCLIENT


# ── resize grips ────────────────────────────────────────────────────────

@pytest.mark.parametrize("x,y,expected", [
    (0, 0, HTTOPLEFT),
    (W - 1, 0, HTTOPRIGHT),
    (0, H - 1, HTBOTTOMLEFT),
    (W - 1, H - 1, HTBOTTOMRIGHT),
    (0, 400, HTLEFT),
    (W - 1, 400, HTRIGHT),
    (400, 0, HTTOP),
    (400, H - 1, HTBOTTOM),
])
def test_edges_and_corners(snap, x, y, expected):
    assert snap._hit_test(_lparam(x, y)) == expected


def test_interior_is_client(snap):
    assert snap._hit_test(_lparam(550, 400)) == HTCLIENT


def test_one_pixel_inside_the_grip_is_client(snap):
    """Off-by-one guard: the grip must not creep into the content area."""
    assert snap._hit_test(_lparam(GRIP, 400)) == HTCLIENT
    assert snap._hit_test(_lparam(W - GRIP - 1, 400)) == HTCLIENT
    assert snap._hit_test(_lparam(400, H - GRIP - 1)) == HTCLIENT


# ── platform guards ──────────────────────────────────────────────────────

def test_install_is_a_noop_off_windows(snap, monkeypatch):
    monkeypatch.setattr("core.snap_layouts.sys.platform", "linux")
    assert snap.install() is False


def test_install_is_a_noop_without_an_hwnd():
    assert SnapLayouts(hwnd=None).install() is False
    assert SnapLayouts(hwnd=0).install() is False


def test_uninstall_without_install_is_safe(snap):
    snap.uninstall()  # must not raise


def test_windows_sdk_values_are_not_self_referential():
    assert (HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT, HTMAXBUTTON) == (10, 11, 12, 13, 14, 15, 16, 17, 9)


@pytest.mark.parametrize('origin', [(320, 140), (-1500, -250)])
def test_dragged_window_and_negative_monitor_coordinates(snap, origin):
    import ctypes
    ctypes.windll.user32.origin = origin
    x, y = origin
    assert snap._hit_test(_lparam(x, y)) == 13
    assert snap._hit_test(_lparam(x + W - 1, y + H - 1)) == 17
    assert snap._hit_test(_lparam(x + 300, y + 300)) == 1


def test_button_and_edge_scale_after_monitor_dpi_change(snap):
    import ctypes
    fake = ctypes.windll.user32
    fake.dpi = 144
    snap.set_button_rect(600, 10, 40, 20)
    assert snap._hit_test(_lparam(930, 30)) == 9
    assert snap._hit_test(_lparam(8, 300)) == 10
    assert snap._hit_test(_lparam(9, 300)) == 1
    fake.dpi = 192
    assert snap._hit_test(_lparam(11, 300)) == 10
    assert snap._hit_test(_lparam(12, 300)) == 1


def test_maximized_and_mini_windows_do_not_offer_resize(snap):
    import ctypes
    ctypes.windll.user32.zoomed = True
    assert snap._hit_test(_lparam(0, 0)) == 1
    ctypes.windll.user32.zoomed = False
    snap._can_resize = lambda: False
    assert snap._hit_test(_lparam(W - 1, H - 1)) == 1


def test_failed_coordinate_conversion_leaves_client_untouched(snap):
    import ctypes
    ctypes.windll.user32.ScreenToClient = lambda *args: 0
    assert snap._hit_test(_lparam(0, 0)) == 1


@pytest.mark.parametrize('rect', [(0, 0, 0, 0), (1, 2, -30, 20), (float('nan'), 0, 30, 20), (0, 0, float('inf'), 20)])
def test_hidden_or_invalid_button_clears_stale_snap_target(snap, rect):
    snap.set_button_rect(100, 100, 30, 20)
    snap.set_button_rect(*rect)
    assert snap._hit_test(_lparam(110, 110)) == HTCLIENT


@pytest.mark.parametrize('message', [0x00A0, 0x00A1, 0x00A2, 0x0112, 0x0312])
def test_native_hover_click_and_system_commands_reach_original_wndproc(snap, monkeypatch, message):
    snap._old_proc = object()
    calls = []
    # A high-bit LRESULT must not be truncated to a 32-bit C long.
    result = 0x123456789
    monkeypatch.setattr('core.snap_layouts._call_window_proc', lambda *args: calls.append(args) or result)
    assert snap._wndproc(1234, message, 9, -2) == result
    assert calls == [(snap._old_proc, 1234, message, 9, -2)]


@pytest.fixture
def install_native(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    from core.snap_layouts import WNDPROC

    calls = []
    original = WNDPROC(lambda *args: 0)
    previous = ctypes.cast(original, ctypes.c_void_p).value

    class NativeCall:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)

    user32 = SimpleNamespace(
        GetWindowLongW=lambda *args: 0x80000000,
        SetWindowLongW=lambda *args: calls.append(('style', args[2])) or 0x80000000,
        SetWindowLongPtrW=NativeCall(lambda *args: calls.append(('proc', args[2])) or previous),
        GetDpiForWindow=lambda hwnd: 96,
        SetWindowPos=lambda *args: calls.append(('frame', args[-1])) or 1,
    )
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32))
    monkeypatch.setattr('core.snap_layouts.sys.platform', 'win32')
    return user32, calls, original, previous


def test_install_subclasses_before_enabling_native_snap_and_resize_styles(install_native):
    import ctypes
    user32, calls, original, previous = install_native
    snap = SnapLayouts(1234)
    assert snap.install() is True
    assert calls[0][0] == 'proc'
    assert calls[1] == ('style', 0x800D0000)
    assert calls[2] == ('frame', 0x37)
    assert snap._proc is not None
    assert snap.install() is True  # no recursive subclass when called twice
    assert len(calls) == 3
    snap.uninstall()
    assert calls[-3][0] == 'proc'
    assert calls[-3][1].value == previous
    assert calls[-2] == ('style', 0x80000000)
    assert calls[-1] == ('frame', 0x37)
    assert snap._proc is None


def test_failed_subclass_install_rolls_back_style(install_native):
    user32, calls, original, previous = install_native
    user32.SetWindowLongPtrW.fn = lambda *args: 0
    snap = SnapLayouts(1234)
    assert snap.install() is False
    assert calls[-2] == ('style', 0x80000000)
    assert snap._proc is None


def test_failed_uninstall_retains_live_callback(install_native):
    user32, calls, original, previous = install_native
    snap = SnapLayouts(1234)
    assert snap.install() is True
    callback = snap._proc
    user32.SetWindowLongPtrW.fn = lambda *args: 0
    snap.uninstall()
    assert snap._installed is True
    assert snap._proc is callback


def test_native_frame_recalculation_keeps_full_client_area(snap, monkeypatch):
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT(200, 100, 1300, 900)
    monkeypatch.setattr('core.snap_layouts._call_window_proc', lambda *args: pytest.fail('Do not let WinForms add native insets'))
    snap._old_proc = object()
    assert snap._wndproc(1234, 0x0083, 1, ctypes.addressof(rect)) == 0
    assert (rect.left, rect.top, rect.right, rect.bottom) == (200, 100, 1300, 900)


def test_native_maximize_uses_current_monitor_work_area(snap):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.zoomed = True
    user32.MonitorFromWindow = lambda hwnd, flags: 5
    def info(monitor, ptr):
        assert monitor == 5
        ptr._obj.rcWork = wintypes.RECT(-1920, 0, 0, 1040)
        return 1
    user32.GetMonitorInfoW = info
    rect = wintypes.RECT(-1928, -8, 8, 1088)
    assert snap._wndproc(1234, 0x0083, 1, ctypes.addressof(rect)) == 0
    assert (rect.left, rect.top, rect.right, rect.bottom) == (-1920, 0, 0, 1040)


@pytest.mark.parametrize('monitor,work,expected', [
    ((0,0,1920,1080),(0,0,1920,1022),(0,0,1920,1022)),
    ((-1920,0,0,1080),(-1870,0,0,1080),(50,0,1870,1080)),
    ((1920,-1080,3840,0),(1920,-1040,3840,0),(0,40,1920,1040)),
])
def test_native_outer_maximize_excludes_taskbar(snap,monkeypatch,monitor,work,expected):
    import ctypes
    from ctypes import wintypes
    from core.snap_layouts import MINMAXINFO
    user32=ctypes.windll.user32
    user32.MonitorFromWindow=lambda hwnd,flags:5
    def info(handle,ptr):
        ptr._obj.rcMonitor=wintypes.RECT(*monitor)
        ptr._obj.rcWork=wintypes.RECT(*work)
        return 1
    user32.GetMonitorInfoW=info
    limits=MINMAXINFO()
    limits.ptMinTrackSize=wintypes.POINT(600,640)
    monkeypatch.setattr('core.snap_layouts._def_window_proc',lambda *args:0)
    assert snap._wndproc(1234,0x0024,0,ctypes.addressof(limits))==0
    assert (limits.ptMaxPosition.x,limits.ptMaxPosition.y,limits.ptMaxSize.x,limits.ptMaxSize.y)==expected
    assert (limits.ptMinTrackSize.x,limits.ptMinTrackSize.y)==(600,640)


def test_frame_update_failure_restores_original_proc_then_style(install_native):
    user32, calls, original, previous = install_native
    user32.SetWindowPos = lambda *args: 0
    snap = SnapLayouts(1234)
    assert snap.install() is False
    assert calls[-2] == ('proc', previous)
    assert calls[-1] == ('style', 0x80000000)
    assert snap._proc is None


def test_fullscreen_covers_entire_monitor_including_taskbar(snap):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.zoomed = False
    user32.MonitorFromWindow = lambda hwnd, flags: 5
    def info(monitor, ptr):
        assert monitor == 5
        ptr._obj.rcMonitor = wintypes.RECT(0, 0, 1920, 1080)
        ptr._obj.rcWork = wintypes.RECT(0, 0, 1920, 1022)
        return 1
    user32.GetMonitorInfoW = info
    snap._is_fullscreen = lambda: True
    rect = wintypes.RECT(0, 0, 1920, 1080)
    assert snap._wndproc(1234, 0x0083, 1, ctypes.addressof(rect)) == 0
    # Must use full monitor (1080), not work area (1022)
    assert (rect.left, rect.top, rect.right, rect.bottom) == (0, 0, 1920, 1080)


def test_fullscreen_outer_bounds_cover_entire_monitor(snap, monkeypatch):
    import ctypes
    from ctypes import wintypes
    from core.snap_layouts import MINMAXINFO
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow = lambda hwnd, flags: 5
    def info(handle, ptr):
        ptr._obj.rcMonitor = wintypes.RECT(0, 0, 1920, 1080)
        ptr._obj.rcWork = wintypes.RECT(0, 0, 1920, 1022)
        return 1
    user32.GetMonitorInfoW = info
    snap._is_fullscreen = lambda: True
    limits = MINMAXINFO()
    monkeypatch.setattr('core.snap_layouts._def_window_proc', lambda *args: 0)
    assert snap._wndproc(1234, 0x0024, 0, ctypes.addressof(limits)) == 0
    # Fullscreen max size should be the full monitor (1920x1080) with (0,0) position
    assert (limits.ptMaxPosition.x, limits.ptMaxPosition.y) == (0, 0)
    assert (limits.ptMaxSize.x, limits.ptMaxSize.y) == (1920, 1080)
    assert (limits.ptMaxTrackSize.x, limits.ptMaxTrackSize.y) == (1920, 1080)


def test_fullscreen_disables_edge_resize_grips(snap):
    from core.snap_layouts import HTCLIENT
    snap._is_fullscreen = lambda: True
    # Grip at (0, 0) would normally report HTTOPLEFT, but in fullscreen should be HTCLIENT
    assert snap._wndproc(1234, 0x0084, 0, 0) == HTCLIENT
