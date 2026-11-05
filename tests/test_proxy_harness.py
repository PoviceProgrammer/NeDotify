"""Proxy daemon-thread and lifecycle regressions without a live application."""
import os
import socketserver
import threading

from core import proxy as proxy_module
from core.proxy import ThreadingHTTPServer
from tests.helpers import PROXY_TOKEN, nedotify_home, proxy, qs, write_bytes


# --- P0-1: request threads must be daemons ---------------------------------

def test_request_threads_are_daemon(proxy, nedotify_home):
    """A buffered track kept the app from closing.

    ThreadingMixIn.daemon_threads defaults to False and nothing overrode it, so
    every request thread was a NON-daemon: sys.exit() blocks joining them, so
    the interpreter never finished while a stream was still being written.
    """
    assert socketserver.ThreadingMixIn.daemon_threads is False, (
        'CPython default changed - re-check the daemon_threads rationale'
    )
    assert ThreadingHTTPServer.daemon_threads is True

    assert proxy.server.daemon_threads is True
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'x' * 32)
    assert proxy.get('/api/cover?' + qs(path=cover, k=proxy.token)).status == 200


# --- H-6: the dead threading._original_Thread indirection -------------------

def test_dead_thread_class_helper_removed(proxy, nedotify_home):
    """get_real_thread_class() read threading._original_Thread, which nothing
    in the project ever sets - it always returned threading.Thread."""
    assert not hasattr(proxy_module, 'get_real_thread_class')
    assert not hasattr(threading, '_original_Thread')

    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'x' * 32)
    assert proxy.get('/api/cover?' + qs(path=cover, k=proxy.token)).status == 200
    # ThreadingMixIn owns its bookkeeping; daemon threads intentionally use
    # socketserver's no-retention sentinel on current CPython versions.
    assert proxy.server.daemon_threads is True
