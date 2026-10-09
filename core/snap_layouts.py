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
GWL_STYLE = -16

# A window procedure must be a real ctypes callback object. Passing the bound
# method straight to SetWindowLongPtr fails with "method object cannot be
# interpreted as an integer": ctypes cannot take the address of a Python
# method, only of a function pointer it built itself.
LRESULT = ctypes.c_long
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             ctypes.c_size_t, ctypes.c_ssize_t)

# WPARAM/LPARAM are pointer-sized. Without explicit argtypes ctypes coerces a
# 64-bit lparam into a 32-bit C int and every call carrying a high-bit message
# parameter dies with "OverflowError: int too long to convert" from inside the
# callback - printed as "Exception ignored while calling ctypes callback
# function", which is how the frameless window lost its WndProc.
LPARAM = ctypes.c_ssize_t


def _configure_user32():
    """Pin argument types once; ctypes caches the function object."""
    u = ctypes.windll.user32
    for fn, argtypes in (
        (u.DefWindowProcW, [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, LPARAM]),
        (u.CallWindowProcW, [WNDPROC, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, LPARAM]),
        (u.GetClientRect, [wintypes.HWND, ctypes.c_void_p]),
    ):
        try:
            fn.argtypes = argtypes
            fn.restype = LRESULT if fn is not u.GetClientRect else ctypes.c_int
        except Exception:
            logger.debug("could not configure %s", getattr(fn, "__name__", fn), exc_info=True)


def _def_window_proc(hwnd, msg, wparam, lparam):
    return ctypes.windll.user32.DefWindowProcW(wintypes.HWND(hwnd), msg, wparam, LPARAM(lparam))


def _call_window_proc(proc, hwnd, msg, wparam, lparam):
    return ctypes.windll.user32.CallWindowProcW(proc, wintypes.HWND(hwnd), msg, wparam, LPARAM(lparam))

# How many CSS pixels from the edge count as a resize/snap grip. The JS side
# reports the button rectangle; the edges are a fixed inset so the grip does
# not move when the window does.
EDGE_GRIP_CSS = 6

LONG_PTR = ctypes.c_ssize_t if sys.maxsize > 2 ** 32 else ctypes.c_int

if sys.platform == "win32":
    try:
        _configure_user32()
    except Exception:
        logging.getLogger(__name__).debug("user32 not configured yet", exc_info=True)


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
        # The live WINFUNCTYPE callback; must outlive the subclass.
        self._proc = None

    # ── public ────────────────────────────────────────────────────────────

    def install(self):
        if sys.platform != "win32" or not self.hwnd:
            return False
        old_style = None
        try:
            user32 = ctypes.windll.user32
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
            SetWindowLongPtr.restype = LONG_PTR

            # The callback object must be kept alive for as long as the window
            # uses it: once _proc is collected the shell calls into freed
            # memory, so it is stored on self alongside the instance.
            self._proc = WNDPROC(self._wndproc)

            old_style = user32.GetWindowLongW(self.hwnd, GWL_STYLE)
            # Only WS_MAXIMIZEBOX is added. Adding WS_THICKFRAME (or WS_SYSMENU)
            # to a frameless window without a matching WS_CAPTION makes Windows
            # recompute the non-client area, which collapses the client rect and
            # leaves the WebView2 child rendering as a black rectangle - the
            # window became unusable while this line was in place. MAXIMIZEBOX
            # alone is what tells Windows the window may maximise, which is the
            # flag the Snap Layout flyout keys off, and it cannot affect layout.
            user32.SetWindowLongW(self.hwnd, GWL_STYLE, old_style | WS_MAXIMIZEBOX)

            self._edge_grip = int(round(EDGE_GRIP_CSS * _dpi_scale(self.hwnd)))
            # argtypes[2] is LONG_PTR, so pass a plain integer address. Passing
            # the c_void_p object itself raises "argument 3: 'c_void_p' object
            # cannot be interpreted as an integer".
            proc_addr = ctypes.cast(self._proc, ctypes.c_void_p).value
            prev = SetWindowLongPtr(self.hwnd, GWL_WNDPROC, proc_addr)
            if not prev:
                raise OSError("SetWindowLongPtr(GWL_WNDPROC) returned 0")
            self._old_wndproc = prev
            # CallWindowProcW needs a callable, not a bare address, or the
            # original procedure is invoked through the wrong signature.
            self._old_proc = WNDPROC(prev)
            self._installed = True
            logger.info("SnapLayouts: installed on hwnd=%s", self.hwnd)
            return True
        except Exception as e:
            # Roll the style back: a mutated style with no live WndProc left the
            # frameless window rendering as a black rectangle.
            self._proc = None
            if old_style is not None:
                try:
                    ctypes.windll.user32.SetWindowLongW(self.hwnd, -16, old_style)
                except Exception:
                    logger.debug("SnapLayouts: style rollback failed", exc_info=True)
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
        # Registered as a WINFUNCTYPE, so the return value must be LRESULT.
        # Returning a bare int works for small codes but is not the declared
        # type; ctypes truncates it the same way either way.
        try:
            if msg == WM_NCHITTEST:
                return LRESULT(self._hit_test(lparam)).value
        except Exception:
            logger.debug("SnapLayouts: hit test failed", exc_info=True)
        # Anything else goes to the original window procedure (DefWindowProc
        # for the messages the original one does not care about).
        try:
            if self._old_proc:
                return _call_window_proc(self._old_proc, hwnd, msg, wparam, lparam)
        except Exception:
            logger.debug("SnapLayouts: CallWindowProc failed", exc_info=True)
        return _def_window_proc(hwnd, msg, wparam, lparam)
