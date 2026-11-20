"""Scratch #6: the harmful variant — leader cancelled by is_current() poisons the joined current generation."""
import sys
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import services.spotify_service as ss  # noqa: E402
from services.spotify_service import SpotifyService  # noqa: E402
from services.itunes_gateway import ITunesGateway  # noqa: E402

T0 = time.monotonic()


def ts():
    return f"{time.monotonic() - T0:6.3f}s"


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
        print(f"  {ts()} [iTunes GET] {url}")
        time.sleep(self.delay)
        return FakeResponse({"results": [{"trackName": "T", "artistName": "A", "trackId": 1,
                                          "trackTimeMillis": 200000}]})


ss._session = FakeSession()
ITunesGateway._entries.clear()
ITunesGateway._flights.clear()
ITunesGateway._recent.clear()
ITunesGateway._next_at = time.monotonic() + 1.2   # a previous request just went out
ITunesGateway._active = False

svc = SpotifyService(None)
outcomes = {}
lock = threading.Lock()
gen = [0]


def make_is_current(g):
    def _f():
        with lock:
            return g == gen[0]
    return _f


print(f"{ts()} gen1 search 'song'  -> parks in the 3.5s throttle queue")
with lock:
    gen[0] = 1
svc.search("song",
           callback=lambda t: outcomes.__setitem__("gen1", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen1", ("error", str(e))),
           is_current=make_is_current(1))
time.sleep(0.10)
print(f"{ts()} gen2 search 'song'  (SAME query -> same cache key -> joins gen1)")
with lock:
    gen[0] = 2
svc.search("song",
           callback=lambda t: outcomes.__setitem__("gen2", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen2", ("error", str(e))),
           is_current=make_is_current(2))
time.sleep(4.0)
print(f"{ts()} outcomes: {outcomes}")
print(f"       iTunes HTTP calls: {ss._session.calls}")
print("       gen2 is the CURRENT search. If it reports an error, the current")
print("       search lost every Spotify result because the STALE leader was cancelled.")
