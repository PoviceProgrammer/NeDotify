"""Scratch #4: (a) real iTunes reachability, (b) leader-failure fan-out to the joined listener."""
import sys
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import requests  # noqa: E402

print("=" * 78)
print("(a) real iTunes Search API reachability from this host")
print("=" * 78)
try:
    r = requests.get("https://itunes.apple.com/search?term=test&entity=song&limit=2", timeout=8)
    print(f"  status={r.status_code} len={len(r.text)}")
    print(f"  body[:200]={r.text[:200]}")
except Exception as e:
    print(f"  request failed: {type(e).__name__}: {e}")

print()
print("=" * 78)
print("(b) leader failure fan-out: does the JOINED (current) listener get the error?")
print("=" * 78)
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


class FailingSession:
    """Simulates iTunes returning HTTP 403 (geo-block) / rate-limit."""

    def __init__(self, status=403, delay=0.05):
        self.status = status
        self.delay = delay
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        time.sleep(self.delay)
        return FakeResponse({"error": "forbidden"}, status=self.status)


ITunesGateway._entries.clear()
ITunesGateway._flights.clear()
ITunesGateway._recent.clear()
ITunesGateway._next_at = 0.0
ITunesGateway._active = False
ss._session = FailingSession(status=403)

svc = SpotifyService(None)
outcomes = {}
lock = threading.Lock()
gen = [0]


def make_is_current(g):
    def _f():
        with lock:
            return g == gen[0]
    return _f


with lock:
    gen[0] = 1
svc.search("same",
           callback=lambda t: outcomes.__setitem__("gen1", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen1", ("error", str(e))),
           is_current=make_is_current(1))
time.sleep(0.05)
with lock:
    gen[0] = 2
svc.search("same",
           callback=lambda t: outcomes.__setitem__("gen2", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen2", ("error", str(e))),
           is_current=make_is_current(2))
time.sleep(1.2)
print(f"  iTunes HTTP calls: {ss._session.calls}")
print(f"  outcomes: {outcomes}")
print("  -> if gen2 is absent, the joined current generation was silently dropped")

print()
print("=" * 78)
print("(c) same, but the leader is superseded BEFORE the gateway is reached")
print("=" * 78)
ITunesGateway._entries.clear()
ITunesGateway._flights.clear()
ITunesGateway._recent.clear()
ITunesGateway._next_at = 0.0
ITunesGateway._active = False
ss._session = FailingSession(status=200)
outcomes2 = {}
svc2 = SpotifyService(None)
with lock:
    gen[0] = 1
svc2.search("q2",
            callback=lambda t: outcomes2.__setitem__("gen1", ("ok", len(t))),
            error_callback=lambda e: outcomes2.__setitem__("gen1", ("error", str(e))),
            is_current=make_is_current(1))
time.sleep(0.30)          # let gen1 get its HTTP under way
with lock:
    gen[0] = 2             # supersede
svc2.search("q2",
            callback=lambda t: outcomes2.__setitem__("gen2", ("ok", len(t))),
            error_callback=lambda e: outcomes2.__setitem__("gen2", ("error", str(e))),
            is_current=make_is_current(2))
time.sleep(1.2)
print(f"  outcomes: {outcomes2}")
print(f"  iTunes HTTP calls: {ss._session.calls}")
