"""Windows 11 Snap Layouts for a frameless pywebview window.

Win11 opens its Snap Layout flyout when the window manager sees either of two
things, both of which a frameless custom titlebar denies by default:

1. WM_NCHITTEST returns HTMAXBUTTON for the maximise button, so the cursor
   becomes the system one and hovering the button offers the layout grid.
2. The window is dragged to the top edge of the screen, which requires
   NCHITTEST to report HTMAXBUTTON over the resize/top strip as well, and
   WS_SYSMENU + WS_MAXIMIZEBOX so the frame is treated as a real caption.

A frameless window has no caption at all, so Windows never asks. This module
subclasses the HWND's window procedure and answers WM_NCHITTEST itself.

Everything here is Windows-only and entirely best-effort: any failure returns
a no-op and leaves the app exactly as it was. Missing ctypes, a non-Windows
platform or an hwnd the OS refuses to let us subclass must never break
startup.
"""

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

# WM_NCHITTEST / return codes
WM_NCHITTEST = 0x0084
HTMAXBUTTON = 0x0020
HTBOTTOM = 0x0007
HTLEFT = 0x0010
HTRIGHT = 0x0011
HTTOP = 0x0012
HTTOPLEFT = 0x0013
HTTOPRIGHT = 0x0014
HTBOTTOMLEFT = 0x0016
HTBOTTOMRIGHT = 0x0017
HTCLIENT = 0x0001
HTCAPTION = 0x0002

# Window styles that let Windows treat the frame as a caption for snapping.
WS_SYSMENU = 0x00080000
WS_MAXIMIZEBOX = 0x00010000
WS_THICKFRAME = 0x00040000
GWL_WNDPROC = -4

# How many CSS pixels from the edge count as a resize/snap grip. The JS side
# reports the button rectangle; the edges are a fixed inset so the grip does
# not move when the window does.
EDGE_GRIP_CSS = 6

LONG_PTR = ctypes.c_ssize_t if sys.maxsize > 2 ** 32 else ctypes.c_int


def _dpi_scale(hwnd):
    """Physical pixels per CSS pixel, so the grip keeps the same feel on 4K."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        return max(1.0, float(dpi) / 96.0) if dpi else 1.0
    except Exception:
        return 1.0


class SnapLayouts:
    """Installs the WM_NCHITTEST handler on one frameless window."""

    def __init__(self, hwnd, js_button_selector="#btn-maximize"):
        self.hwnd = int(hwnd) if hwnd else 0
        self.js_button_selector = js_button_selector
        self._old_wndproc = None
        self._installed = False
        # Client-relative rect of the maximise button, filled by JS.
        self._btn_rect = None
        self._edge_grip = EDGE_GRIP_CSS

    # ── public ────────────────────────────────────────────────────────────

    def install(self):
        if sys.platform != "win32" or not self.hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            # Without these Windows refuses to snap a window it does not
            # consider a normal, caption-bearing top-level window.
            style = user32.GetWindowLongW(self.hwnd, -16)  # GWL_STYLE
            user32.SetWindowLongW(self.hwnd, -16, style | WS_SYSMENU | WS_MAXIMIZEBOX | WS_THICKFRAME)

            self._edge_grip = int(round(EDGE_GRIP_CSS * _dpi_scale(self.hwnd)))
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
            SetWindowLongPtr.restype = LONG_PTR
            self._old_wndproc = SetWindowLongPtr(self.hwnd, GWL_WNDPROC, LONG_PTR(self._wndproc))
            if not self._old_wndproc:
                raise OSError("SetWindowLongPtr(GWL_WNDPROC) returned 0")
            self._installed = True
            logger.info("SnapLayouts: installed on hwnd=%s", self.hwnd)
            return True
        except Exception as e:
            logger.warning("SnapLayouts: not installed (%s)", e)
            self._installed = False
            return False

    def set_button_rect(self, x, y, w, h):
        """Client-relative rectangle of the maximise button, in CSS pixels."""
        try:
            self._btn_rect = (float(x), float(y), float(w), float(h))
        except (TypeError, ValueError):
            self._btn_rect = None

    def uninstall(self):
        if not self._installed or not self.hwnd:
            return
        try:
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
            SetWindowLongPtr.restype = LONG_PTR
            SetWindowLongPtr(self.hwnd, GWL_WNDPROC, LONG_PTR(self._old_wndproc or 0))
            self._installed = False
            logger.info("SnapLayouts: removed")
        except Exception as e:
            logger.debug("SnapLayouts: uninstall failed", exc_info=True)

    # ── the window procedure ──────────────────────────────────────────────

    def _hit_test(self, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value

        # 1) The maximise button: this is what makes Win11 offer Snap Layouts
        #    on hover, and what gives the button the system cursor.
        if self._btn_rect:
            bx, by, bw, bh = self._btn_rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return HTMAXBUTTON

        # 2) Edge grips, so a frameless window can still be resized by its
        #    borders (there is no visible frame to grab otherwise).
        g = self._edge_grip
        try:
            rc = wintypes.RECT()
            ctypes.windll.user32.GetClientRect(self.hwnd, ctypes.byref(rc))
            w, h = rc.right, rc.bottom
        except Exception:
            return HTCLIENT

        # Half-open interval: `x < g` keeps the grip exactly g pixels wide
        # (0..g-1). `x <= g` would eat one extra pixel of content on every
        # side, making the first and last row/column of text unselectable.
        left = x < g
        right = x >= w - g
        top = y < g
        bottom = y >= h - g
        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM
        return HTCLIENT

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_NCHITTEST:
                return self._hit_test(lparam)
        except Exception:
            logger.debug("SnapLayouts: hit test failed", exc_info=True)
        # Anything else goes to the original window procedure (DefWindowProc
        # for the messages the original one does not care about).
        try:
            if self._old_wndproc:
                return ctypes.windll.user32.CallWindowProcW(
                    LONG_PTR(self._old_wndproc), wintypes.HWND(hwnd), msg, wparam, lparam)
        except Exception:
            logger.debug("SnapLayouts: CallWindowProc failed", exc_info=True)
        return ctypes.windll.user32.DefWindowProcW(wintypes.HWND(hwnd), msg, wparam, lparam)
