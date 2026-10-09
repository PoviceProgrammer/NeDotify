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

    def GetClientRect(self, hwnd, rc):
        rc._obj.left = 0
        rc._obj.top = 0
        rc._obj.right = self._w
        rc._obj.bottom = self._h


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
