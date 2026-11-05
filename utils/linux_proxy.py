"""Session-only app SOCKS transport; never persisted over a user's proxy setting."""
import threading

_lock = threading.RLock()
_endpoint = None


def set_endpoint(port=None):
    global _endpoint
    with _lock:
        _endpoint = ('127.0.0.1', int(port)) if port else None


def endpoint():
    with _lock:
        return _endpoint


def proxy_url():
    value = endpoint()
    return f'socks5h://{value[0]}:{value[1]}' if value else ''
