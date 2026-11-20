"""Scratch #3: instrument the SpotifyService _join_request fan-out."""
import sys
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import services.spotify_service as ss  # noqa: E402
from services.spotify_service import SpotifyService  # noqa: E402
from services.itunes_gateway import ITunesGateway  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, delay=0.05):
        self.delay = delay
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        print(f"    [fake iTunes] GET {url}")
        time.sleep(self.delay)
        return FakeResponse({"results": [{"trackName": "T", "artistName": "A", "trackId": 1,
                                          "trackTimeMillis": 200000}]})


ITunesGateway._entries.clear()
ITunesGateway._flights.clear()
ITunesGateway._recent.clear()
ITunesGateway._next_at = 0.0
ITunesGateway._active = False
ss._session = FakeSession()

svc = SpotifyService(None)
outcomes = {}
lock = threading.Lock()
gen = [0]


def make_is_current(g):
    def _f():
        with lock:
            return g == gen[0]
    return _f


orig_join = svc._join_request


def traced_join(key, cb, eb):
    leader, c, e = orig_join(key, cb, eb)
    print(f"    [_join_request] key={key!r} leader={leader} pending={list(svc._pending_requests)}")
    return leader, c, e


svc._join_request = traced_join

print("--- gen1 search 'same' ---")
with lock:
    gen[0] = 1
svc.search("same",
           callback=lambda t: outcomes.__setitem__("gen1", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen1", ("error", str(e))),
           is_current=make_is_current(1))
time.sleep(0.05)
print("--- gen2 search 'same' (new generation, same key) ---")
with lock:
    gen[0] = 2
svc.search("same",
           callback=lambda t: outcomes.__setitem__("gen2", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen2", ("error", str(e))),
           is_current=make_is_current(2))
time.sleep(1.5)
print(f"  pending after: {svc._pending_requests}")
print(f"  outcomes: {outcomes}")
print(f"  iTunes HTTP calls: {ss._session.calls}")
print(f"  search cache keys: {list(ss.BaseMusicService._search_cache.keys())}")
