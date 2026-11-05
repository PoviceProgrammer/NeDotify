"""Windows 11 Snap Layouts for a frameless pywebview window.

The native resize/maximize styles let Windows handle sizing, Snap and Win+Z.
WM_NCCALCSIZE keeps the entire frameless window available to WebView2, while
WM_NCHITTEST identifies the custom maximize button as HTMAXBUTTON so Windows
can display its Snap flyout on hover. Caption dragging is initiated separately
by AppApi.begin_window_drag.

Everything here is Windows-only and entirely best-effort: any failure returns
a no-op and leaves the app exactly as it was. Missing ctypes, a non-Windows
platform or an hwnd the OS refuses to let us subclass must never break
startup.
"""

import ctypes
import logging
import math
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

# WM_NCHITTEST / return codes
WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
WM_GETMINMAXINFO = 0x0024
HTMAXBUTTON = 9
HTBOTTOM = 15
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTCLIENT = 0x0001
HTCAPTION = 0x0002

# Window styles that let Windows treat the frame as a caption for snapping.
WS_SYSMENU = 0x00080000
WS_MAXIMIZEBOX = 0x00010000
WS_THICKFRAME = 0x00040000
GWL_WNDPROC = -4
GWL_STYLE = -16
SWP_FRAMECHANGED = 0x0020
SWP_KEEP_BOUNDS = 0x0001 | 0x0002 | 0x0004 | 0x0010  # no size/move/z-order/activation


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [('ptReserved', wintypes.POINT), ('ptMaxSize', wintypes.POINT),
                ('ptMaxPosition', wintypes.POINT), ('ptMinTrackSize', wintypes.POINT),
                ('ptMaxTrackSize', wintypes.POINT)]

# A window procedure must be a real ctypes callback object. Passing the bound
# method straight to SetWindowLongPtr fails with "method object cannot be
# interpreted as an integer": ctypes cannot take the address of a Python
# method, only of a function pointer it built itself.
LRESULT = ctypes.c_ssize_t
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
        (u.ScreenToClient, [wintypes.HWND, ctypes.c_void_p]),
        (u.IsZoomed, [wintypes.HWND]),
        (u.GetDpiForWindow, [wintypes.HWND]),
        (u.GetWindowLongW, [wintypes.HWND, ctypes.c_int]),
        (u.SetWindowLongW, [wintypes.HWND, ctypes.c_int, wintypes.LONG]),
        (u.SetWindowPos, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]),
        (u.MonitorFromWindow, [wintypes.HWND, wintypes.DWORD]),
        (u.GetMonitorInfoW, [wintypes.HANDLE, ctypes.c_void_p]),
    ):
        try:
            fn.argtypes = argtypes
            if fn == u.MonitorFromWindow:
                fn.restype = wintypes.HANDLE
            else:
                fn.restype = LRESULT if fn in (u.DefWindowProcW, u.CallWindowProcW) else ctypes.c_int
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
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        return max(1.0, float(dpi) / 96.0) if dpi else 1.0
    except Exception:
        return 1.0


class SnapLayouts:
    """Installs native sizing and Snap handlers on one frameless window."""

    def __init__(self, hwnd, js_button_selector="#btn-maximize", can_resize=None):
        self.hwnd = int(hwnd) if hwnd else 0
        self.js_button_selector = js_button_selector
        self._old_wndproc = None
        self._old_proc = None
        self._old_style = None
        self._can_resize = can_resize
        self._installed = False
        # Client-relative rect of the maximise button, filled by JS.
        self._btn_rect = None
        self._edge_grip = EDGE_GRIP_CSS
        # The live WINFUNCTYPE callback; must outlive the subclass.
        self._proc = None

    # ── public ────────────────────────────────────────────────────────────

    def install(self):
        if self._installed:
            return True
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
            self._old_style = old_style
            # Install WM_NCCALCSIZE BEFORE enabling native sizing. Without that
            # handler a standard non-client frame can steal WebView2's client
            # area and leave the content black. The OS gets resize/snap styles;
            # our entire window remains client content, without native buttons.
            user32.SetWindowLongW(self.hwnd, GWL_STYLE, old_style | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU)
            self._refresh_frame()
            self._installed = True
            logger.info("SnapLayouts: installed on hwnd=%s", self.hwnd)
            return True
        except Exception as e:
            # Roll the style back: a mutated style with no live WndProc left the
            # frameless window rendering as a black rectangle.
            # Never release a callback while Windows might still reference it.
            if self._old_wndproc:
                try:
                    if not SetWindowLongPtr(self.hwnd, GWL_WNDPROC, self._old_wndproc):
                        raise OSError("WndProc rollback returned 0")
                    self._old_wndproc = None
                except Exception:
                    logger.exception("SnapLayouts: WndProc rollback failed; retaining callback")
                    self._installed = True
                    return True  # caller must retain this live subclass
            self._proc = None
            if old_style is not None:
                try:
                    ctypes.windll.user32.SetWindowLongW(self.hwnd, -16, old_style)
                    self._refresh_frame()
                except Exception:
                    logger.debug("SnapLayouts: style rollback failed", exc_info=True)
            logger.warning("SnapLayouts: not installed (%s)", e)
            self._installed = False
            return False

    def set_button_rect(self, x, y, w, h):
        """Client-relative rectangle of the maximise button, in CSS pixels."""
        try:
            rect = (float(x), float(y), float(w), float(h))
            self._btn_rect = rect if all(math.isfinite(v) for v in rect) and rect[2] > 0 and rect[3] > 0 else None
        except (TypeError, ValueError):
            self._btn_rect = None

    def uninstall(self):
        if not self._installed or not self.hwnd:
            return
        try:
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
            SetWindowLongPtr.restype = LONG_PTR
            if not SetWindowLongPtr(self.hwnd, GWL_WNDPROC, LONG_PTR(self._old_wndproc or 0)):
                raise OSError("WndProc restore returned 0")
            self._installed = False
            self._proc = None
            self._old_wndproc = None
            self._old_proc = None
            if self._old_style is not None:
                ctypes.windll.user32.SetWindowLongW(self.hwnd, GWL_STYLE, self._old_style)
                self._refresh_frame()
            logger.info("SnapLayouts: removed")
        except Exception as e:
            logger.debug("SnapLayouts: uninstall failed", exc_info=True)

    # ── the window procedure ──────────────────────────────────────────────

    def _refresh_frame(self):
        if not ctypes.windll.user32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, SWP_FRAMECHANGED | SWP_KEEP_BOUNDS):
            raise OSError('SetWindowPos(SWP_FRAMECHANGED) failed')

    def _frameless_client(self, lparam):
        # NCCALCSIZE_PARAMS starts with the proposed client RECT in screen px.
        # In the normal case keep it untouched: the whole window is client area.
        user32 = ctypes.windll.user32
        if user32.IsZoomed(self.hwnd):
            # Native maximize can extend the outer frame beyond the monitor.
            # Keep WebView content inside this monitor's work area/taskbar.
            monitor = user32.MonitorFromWindow(self.hwnd, 2)  # nearest
            info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
                rect.left, rect.top = info.rcWork.left, info.rcWork.top
                rect.right, rect.bottom = info.rcWork.right, info.rcWork.bottom
        return 0

    def _maximize_work_area(self, lparam):
        # Clipping only NCCALCSIZE leaves an oversized native frame below the
        # browser, covering the taskbar with an unpainted white/black strip.
        # Constrain the OUTER maximized bounds too, including Win+Up and Snap.
        user32 = ctypes.windll.user32
        monitor = user32.MonitorFromWindow(self.hwnd, 2)
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            limits = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            limits.ptMaxPosition.x = info.rcWork.left - info.rcMonitor.left
            limits.ptMaxPosition.y = info.rcWork.top - info.rcMonitor.top
            limits.ptMaxSize.x = info.rcWork.right - info.rcWork.left
            limits.ptMaxSize.y = info.rcWork.bottom - info.rcWork.top

    def _hit_test(self, lparam):
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        user32 = ctypes.windll.user32
        point = wintypes.POINT(x, y)
        # WM_NCHITTEST carries signed SCREEN pixels, not client/CSS pixels.
        if not user32.ScreenToClient(self.hwnd, ctypes.byref(point)):
            return HTCLIENT
        x, y = point.x, point.y
        scale = _dpi_scale(self.hwnd)

        # 1) The maximise button: this is what makes Win11 offer Snap Layouts
        #    on hover, and what gives the button the system cursor.
        if self._btn_rect:
            bx, by, bw, bh = (value * scale for value in self._btn_rect)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return HTMAXBUTTON

        # 2) Edge grips, so a frameless window can still be resized by its
        #    borders (there is no visible frame to grab otherwise).
        if user32.IsZoomed(self.hwnd) or (self._can_resize and not self._can_resize()):
            return HTCLIENT
        g = max(1, int(round(EDGE_GRIP_CSS * scale)))
        try:
            rc = wintypes.RECT()
            if not user32.GetClientRect(self.hwnd, ctypes.byref(rc)):
                return HTCLIENT
            w, h = rc.right, rc.bottom
        except Exception:
            return HTCLIENT
        if not (0 <= x < w and 0 <= y < h):
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
        # Leave non-client hover/click and Win+Z handling to Windows. Only the
        # hit-test is customized; LRESULT remains pointer-sized on 64-bit Windows.
        try:
            if msg == WM_GETMINMAXINFO and lparam:
                # Let WinForms supply the normal minimum tracking size first.
                result = _call_window_proc(self._old_proc, hwnd, msg, wparam, lparam) if self._old_proc else _def_window_proc(hwnd, msg, wparam, lparam)
                self._maximize_work_area(lparam)
                return result
            if msg == WM_NCCALCSIZE and wparam and lparam:
                return self._frameless_client(lparam)
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
