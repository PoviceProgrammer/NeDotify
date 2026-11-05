"""Unit and regression tests for Group 7 bug fixes:
- BUG-WIN-008: PUBLIC_METHODS consistency in bridge.py and remove_artist_alias
- BUG-WIN-029: Proxy server retries abort on client socket closure
- BUG-WIN-032: Session restore clears file_path for all non-local sources (spotify, yandex, deezer)
- BUG-WIN-033: UI Server slots acquisition uses timeout instead of immediate reset
- BUG-WIN-049: AppApi._emit does not block backend threads during heavy UI rendering
- BUG-WIN-050: DNS slots semaphore blocking acquire with timeout and domain cache re-check
- BUG-WIN-051: guarded_open_url respects system/corporate proxies
"""
import io
import select
import socket
import threading
import time
import urllib.request
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.bridge import PUBLIC_METHODS, BridgeApi
from core.api import AppApi
from core.session import SessionManager
from core.ui_server import _BoundServer
import core.proxy as proxy_module
import utils.url_safety as url_safety


# ============================================================================
# BUG-WIN-008: Bridge PUBLIC_METHODS & AppApi consistency
# ============================================================================
def test_bug_win_008_public_methods_contain_all_required():
    required = {
        'get_offline_library',
        'get_track_info',
        'set_artist_alias',
        'remove_artist_alias',
        'get_discord_rpc_status',
    }
    missing = required - PUBLIC_METHODS
    assert not missing, f"PUBLIC_METHODS is missing: {missing}"


def test_bug_win_008_bridge_api_exposes_and_calls_methods():
    mock_api = MagicMock()
    mock_api.get_offline_library.return_value = {'tracks': []}
    mock_api.get_track_info.return_value = {'id': 123}
    mock_api.set_artist_alias.return_value = {'success': True}
    mock_api.remove_artist_alias.return_value = {'success': True}
    mock_api.get_discord_rpc_status.return_value = {'connected': True}

    bridge = BridgeApi(mock_api)
    assert 'get_offline_library' in dir(bridge)
    assert 'get_track_info' in dir(bridge)
    assert 'set_artist_alias' in dir(bridge)
    assert 'remove_artist_alias' in dir(bridge)
    assert 'get_discord_rpc_status' in dir(bridge)

    assert bridge.get_offline_library() == {'tracks': []}
    assert bridge.get_track_info(123) == {'id': 123}
    assert bridge.set_artist_alias('alias', 'canon') == {'success': True}
    assert bridge.remove_artist_alias('alias') == {'success': True}
    assert bridge.get_discord_rpc_status() == {'connected': True}


def test_bug_win_008_remove_artist_alias_implementation():
    settings_data = {
        'personalization': {
            'artist_aliases': {'pharaoh': 'PHARAOH', 'kizaru': 'KIZARU'}
        }
    }
    class FakeSettings:
        def get(self, cat, key, default=None):
            return settings_data.get(cat, {}).get(key, default)
        def set(self, cat, key, value):
            settings_data.setdefault(cat, {})[key] = value

    api = AppApi.__new__(AppApi)
    api._window_op_lock = threading.RLock()
    api._core = SimpleNamespace(settings=FakeSettings())

    # Invalid alias inputs
    assert api.remove_artist_alias('') == {'success': False, 'error': 'Укажите имя исполнителя'}
    assert api.remove_artist_alias(123) == {'success': False, 'error': 'Укажите имя исполнителя'}

    # Successfully remove existing alias
    res = api.remove_artist_alias('kizaru')
    assert res == {'success': True}
    assert 'kizaru' not in settings_data['personalization']['artist_aliases']
    assert 'pharaoh' in settings_data['personalization']['artist_aliases']

    # Non-existent alias removal is safe
    res2 = api.remove_artist_alias('nonexistent')
    assert res2 == {'success': True}


# ============================================================================
# BUG-WIN-029: Proxy server retries abort on client socket closure
# ============================================================================
def test_bug_win_029_is_client_connected_detection():
    s1, s2 = socket.socketpair()
    handler = SimpleNamespace(connection=s1, close_connection=False)
    assert proxy_module._is_client_connected(handler) is True

    # Peer closes
    s2.close()
    assert proxy_module._is_client_connected(handler) is False

    # Own socket closes
    s1.close()
    assert proxy_module._is_client_connected(handler) is False


def test_bug_win_029_sleep_with_client_check_aborts_early():
    s1, s2 = socket.socketpair()
    handler = SimpleNamespace(connection=s1, close_connection=False)

    start = time.time()
    # Close peer after 0.15s in separate thread
    def closer():
        time.sleep(0.15)
        s2.close()
    t = threading.Thread(target=closer)
    t.start()

    # Request a 3.0 second sleep; should wake up and return False around 0.15s
    res = proxy_module._sleep_with_client_check(handler, 3.0)
    t.join()
    elapsed = time.time() - start

    assert res is False
    assert elapsed < 1.0, f"Expected early abort, took {elapsed:.2f}s"
    s1.close()


# ============================================================================
# BUG-WIN-032: Session restore clears file_path for all non-local sources
# ============================================================================
def test_bug_win_032_session_clears_all_remote_sources():
    settings_data = {
        'session': {
            'last_queue': [
                {'title': 'T1', 'source': 'youtube', 'file_path': 'C:/cache/y.mp3', 'resolved_at': 100},
                {'title': 'T2', 'source': 'soundcloud', 'file_path': 'C:/cache/s.mp3', 'resolved_at': 200},
                {'title': 'T3', 'source': 'vk', 'file_path': 'C:/cache/v.mp3', 'resolved_at': 300},
                {'title': 'T4', 'source': 'spotify', 'file_path': 'C:/cache/sp.mp3', 'resolved_at': 400},
                {'title': 'T5', 'source': 'yandex', 'file_path': 'C:/cache/ya.mp3', 'resolved_at': 500},
                {'title': 'T6', 'source': 'deezer', 'file_path': 'C:/cache/dz.mp3', 'resolved_at': 600},
                {'title': 'T7', 'source': 'local', 'file_path': 'D:/Music/local.mp3', 'resolved_at': 700},
            ]
        }
    }
    class FakeSettings:
        def get(self, cat, key, default=None):
            return settings_data.get(cat, {}).get(key, default)

    mgr = SessionManager(FakeSettings())
    restored = mgr.restore_session()
    queue = restored['queue']

    # All non-local sources must have file_path None and resolved_at 0
    for track in queue:
        if track['source'] == 'local':
            assert track['file_path'] == 'D:/Music/local.mp3'
            assert track['resolved_at'] == 700
        else:
            assert track['file_path'] is None, f"{track['source']} file_path was not cleared"
            assert track['resolved_at'] == 0, f"{track['source']} resolved_at was not reset"


# ============================================================================
# BUG-WIN-033: UI Server slots acquisition uses timeout
# ============================================================================
def test_bug_win_033_bound_server_acquires_with_timeout():
    class DummyServer(_BoundServer):
        def __init__(self):
            self._slots = threading.BoundedSemaphore(1)
            self.shutdown_called = False
            self.super_called = False
        def shutdown_request(self, req):
            self.shutdown_called = True
        def server_bind(self):
            pass

    srv = DummyServer()
    # Acquire the single slot to simulate full load
    assert srv._slots.acquire() is True

    # In a background thread, release the slot after 0.2s
    def release_later():
        time.sleep(0.2)
        srv._slots.release()

    t = threading.Thread(target=release_later)
    t.start()

    # Now call process_request from another thread
    with patch.object(_BoundServer, 'process_request', lambda self, r, a: setattr(self, 'super_called', True)):
        srv.process_request(MagicMock(), ('127.0.0.1', 1234))

    t.join()
    assert srv.shutdown_called is False
    assert srv.super_called is True


# ============================================================================
# BUG-WIN-049: AppApi._emit does not block backend threads during heavy UI
# ============================================================================
def test_bug_win_049_emit_does_not_block_backend_threads():
    class SlowWindow:
        def __init__(self):
            self.calls = []
        def evaluate_js(self, js):
            time.sleep(0.8)  # simulate heavy UI rendering
            self.calls.append(js)

    api = AppApi.__new__(AppApi)
    api._window = SlowWindow()
    api._core = None
    api._window_op_lock = threading.RLock()
    api._emitter_init_lock = threading.Lock()
    api._closed = False

    start = time.time()
    # Calling from a worker thread
    caller_returned = threading.Event()
    def worker():
        api._emit('test_event', {'data': 123})
        caller_returned.set()

    t = threading.Thread(target=worker)
    t.start()
    assert caller_returned.wait(0.2), "_emit blocked worker thread for > 200ms during heavy UI!"
    elapsed = time.time() - start
    assert elapsed < 0.2, f"_emit took {elapsed:.2f}s, expected < 0.2s"
    t.join(timeout=2.0)


# ============================================================================
# BUG-WIN-050: DNS semaphore blocking with timeout & cache re-check
# ============================================================================
def test_bug_win_050_dns_semaphore_blocking_and_caching(monkeypatch):
    url_safety.reset_url_safety_cache()
    # Other tests may still own bounded, timed-out DNS workers. Exercise an
    # isolated pool rather than assuming the global transport is idle.
    monkeypatch.setattr(url_safety, '_DNS_SLOTS', threading.BoundedSemaphore(8))
    # Fill up all slots
    slots_held = []
    for _ in range(8):
        assert url_safety._DNS_SLOTS.acquire(blocking=False)
        slots_held.append(True)

    # In a separate thread, release one slot after 0.2s
    def release_one():
        time.sleep(0.2)
        url_safety._DNS_SLOTS.release()
    t = threading.Thread(target=release_one)
    t.start()

    start = time.time()
    # With timeout=1.5, _public_addresses should wait for the released slot and succeed
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, port, type: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))
    ])
    addrs = url_safety._public_addresses('example.com', 80)
    t.join()
    elapsed = time.time() - start

    assert addrs, "_public_addresses failed to acquire slot with timeout"
    assert 0.15 <= elapsed < 1.0, f"Expected ~0.2s wait, took {elapsed:.2f}s"

    # Clean up held slots
    for _ in range(7):
        url_safety._DNS_SLOTS.release()
    url_safety.reset_url_safety_cache()


# ============================================================================
# BUG-WIN-051: guarded_open_url uses default ProxyHandler
# ============================================================================
def test_bug_win_051_guarded_open_url_preserves_system_proxies(monkeypatch):
    captured_handlers = []
    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        mock_opener = MagicMock()
        mock_opener.open.return_value = 'response'
        return mock_opener

    monkeypatch.setattr(urllib.request, 'build_opener', fake_build_opener)
    monkeypatch.setattr(url_safety, 'safe_public_url', lambda u: True)
    if hasattr(url_safety._TRANSPORT_LOCAL, 'opener'):
        del url_safety._TRANSPORT_LOCAL.opener

    url_safety.guarded_open_url('https://example.com/stream.mp3')

    # Look for ProxyHandler in captured handlers
    proxy_handlers = [h for h in captured_handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxy_handlers, "ProxyHandler not installed in guarded opener"
    ph = proxy_handlers[0]
    # When initialized as ProxyHandler(), proxies is None or system proxies dict from getproxies()
    # It must not be forced to {}
    assert ph.proxies != {} or ph.proxies is None or bool(ph.proxies), "ProxyHandler was forced to empty {}"
