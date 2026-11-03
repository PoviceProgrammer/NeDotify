"""Native sizing messages are tested without opening any application window."""
import ctypes
from types import SimpleNamespace
import pytest


class MessageRecorder:
    def __init__(self):
        self.calls=[]

    def __call__(self,*args):
        self.calls.append(args)
        return 0


@pytest.mark.parametrize('direction,hit',[('n',12),('s',15),('w',10),('e',11),('nw',13),('ne',14),('sw',16),('se',17)])
def test_resize_sends_the_correct_native_edge_message(api,monkeypatch,direction,hit):
    api._snap_layouts=SimpleNamespace(_installed=True)
    api._window=SimpleNamespace()
    monkeypatch.setattr(api,'_get_hwnd',lambda:1234)
    monkeypatch.setattr('core.api.sys.platform','win32')
    sent=MessageRecorder();released=[]
    def cursor(point):
        point._obj.x=-1200;point._obj.y=450;return 1
    fake=SimpleNamespace(IsZoomed=lambda hwnd:False,GetWindowLongW=lambda hwnd,index:0x00040000,
                         GetCursorPos=cursor,ReleaseCapture=lambda:released.append(True),SendMessageW=sent)
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=fake))
    assert api.begin_window_resize(direction)=={'success':True}
    hwnd,message,edge,position=sent.calls[0]
    assert (hwnd,message,edge)==(1234,0x00A1,hit)
    assert ctypes.c_short(position.value & 0xffff).value==-1200
    assert ctypes.c_short((position.value >> 16) & 0xffff).value==450
    assert released==[True]


@pytest.mark.parametrize('direction',['',None,[],{},'diagonal',17])
def test_invalid_directions_are_rejected_without_native_calls(api,direction):
    assert api.begin_window_resize(direction)['success'] is False


@pytest.mark.parametrize('mode',['maximized','mini'])
def test_fixed_window_modes_reject_sizing(api,monkeypatch,mode):
    monkeypatch.setattr('core.api.sys.platform','win32')
    api._window=SimpleNamespace()
    api._snap_layouts=SimpleNamespace(_installed=True)
    api._is_maximized=mode=='maximized';api._is_mini_active=mode=='mini'
    monkeypatch.setattr(api,'_get_hwnd',lambda:pytest.fail('Native work should not run'))
    assert api.begin_window_resize('se')['success'] is False


def test_resize_is_a_noop_without_a_native_window(api):
    api._window=None
    assert api.begin_window_resize('se')['success'] is False


def test_native_capture_and_sizing_are_queued_without_blocking_the_bridge(api,monkeypatch):
    api._window=SimpleNamespace()
    api._snap_layouts=SimpleNamespace(_installed=True)
    monkeypatch.setattr('core.api.sys.platform','win32')
    monkeypatch.setattr(api,'_get_hwnd',lambda:1234)
    pending=[];released=[];sent=MessageRecorder()
    def cursor(point):
        point._obj.x=100;point._obj.y=200;return 1
    fake=SimpleNamespace(IsZoomed=lambda hwnd:False,GetWindowLongW=lambda hwnd,index:0x00040000,
                         GetCursorPos=cursor,ReleaseCapture=lambda:released.append(True),SendMessageW=sent)
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=fake))
    monkeypatch.setattr(api,'_on_window_ui_thread',lambda window,fn:pending.append(fn))
    assert api.begin_window_resize('se')['success'] is True
    assert not sent.calls and not released
    pending[0]()
    assert released==[True] and sent.calls[0][2]==17


def test_snap_button_bridge_preserves_css_units_and_clears_hidden_target(api):
    from core.snap_layouts import SnapLayouts
    api._snap_layouts=SnapLayouts(1234)
    assert api.set_snap_button_rect(100.5,4,40,28)=={'success':True}
    assert api._snap_layouts._btn_rect==(100.5,4,40,28)
    assert api.set_snap_button_rect(0,0,0,0)=={'success':True}
    assert api._snap_layouts._btn_rect is None


def test_snap_button_bridge_can_retry_until_native_subclass_is_ready(api):
    api._snap_layouts=None
    assert api.set_snap_button_rect(100,4,40,28)=={'success':False}


def test_resize_rejects_until_snap_subclass_is_installed(api,monkeypatch):
    api._window=SimpleNamespace()
    api._snap_layouts=SimpleNamespace(_installed=False)
    monkeypatch.setattr('core.api.sys.platform','win32')
    monkeypatch.setattr(api,'_get_hwnd',lambda:1234)
    class User32:
        IsZoomed=staticmethod(lambda hwnd:False)
        GetCursorPos=staticmethod(lambda point:1)
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=User32()))
    assert api.begin_window_resize('se')=={'success':False,'error':'Window resizing is not ready'}


def test_resize_rejects_window_without_thickframe_style(api,monkeypatch):
    api._window=SimpleNamespace()
    api._snap_layouts=SimpleNamespace(_installed=True)
    monkeypatch.setattr('core.api.sys.platform','win32')
    monkeypatch.setattr(api,'_get_hwnd',lambda:1234)
    class User32:
        IsZoomed=staticmethod(lambda hwnd:False)
        GetWindowLongW=staticmethod(lambda hwnd,index:0)
        GetCursorPos=staticmethod(lambda point:1)
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=User32()))
    assert api.begin_window_resize('se')=={'success':False,'error':'Window resize style is missing'}
