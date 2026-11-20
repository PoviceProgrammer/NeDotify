"""Scratch harness #2 for WN-21 (Role A): real SpotifyService + real ITunesGateway."""
import sys
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import services.itunes_gateway as ig  # noqa: E402
from services.itunes_gateway import ITunesGateway, CatalogueUnavailable  # noqa: E402
from services.spotify_service import SpotifyService  # noqa: E402
from services.base_service import BaseMusicService  # noqa: E402


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
        time.sleep(self.delay)
        return FakeResponse({"results": [{"trackName": "T", "artistName": "A", "trackId": 1,
                                          "trackTimeMillis": 200000}]})


def reset_gateway():
    ITunesGateway._entries.clear()
    ITunesGateway._flights.clear()
    ITunesGateway._recent.clear()
    ITunesGateway._next_at = 0.0
    ITunesGateway._active = False


# ---------------------------------------------------------------
print("=" * 78)
print("EXPERIMENT 3 (real SpotifyService): two generations, SAME query")
print("  gen1 starts, gen2 starts before gen1 finished -> same cache key ->")
print("  does gen2 piggyback on gen1's request?  And what happens when gen1")
print("  is superseded (is_current() -> False) while queued in the gateway?")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.05)
ig._session = session
svc = SpotifyService(None)

lock = threading.Lock()
gen = [0]
outcomes = {}


def make_is_current(g):
    def _f():
        with lock:
            return g == gen[0]
    return _f


# gen1: search "same" (generation 1)
with lock:
    gen[0] = 1
svc.search("same", callback=lambda t: outcomes.__setitem__("gen1", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen1", ("error", str(e))),
           is_current=make_is_current(1))
time.sleep(0.02)

# gen2: SAME query again (new generation) -> same cache key
with lock:
    gen[0] = 2
svc.search("same", callback=lambda t: outcomes.__setitem__("gen2", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen2", ("error", str(e))),
           is_current=make_is_current(2))
time.sleep(1.2)
print(f"  iTunes HTTP calls made: {session.calls}  (1 => gen2 piggybacked on gen1)")
print(f"  outcomes: {outcomes}")

print()
print("=" * 78)
print("EXPERIMENT 3b: gen2 arrives AFTER gen1 was superseded but while gen1 is")
print("  still queued behind the 3.5s throttle -> gen1 raises CatalogueUnavailable")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.05)
ig._session = session
svc = SpotifyService(None)
outcomes = {}

# gen1 begins, but the gateway slot is busy -> gen1 waits in the throttle queue
ITunesGateway._next_at = time.monotonic() + 1.0   # pretend a previous request just went out
with lock:
    gen[0] = 1
svc.search("q", callback=lambda t: outcomes.__setitem__("gen1", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen1", ("error", str(e))),
           is_current=make_is_current(1))
time.sleep(0.10)          # gen1 is parked in the throttle queue
with lock:
    gen[0] = 2             # a new search supersedes gen1
svc.search("q", callback=lambda t: outcomes.__setitem__("gen2", ("ok", len(t))),
           error_callback=lambda e: outcomes.__setitem__("gen2", ("error", str(e))),
           is_current=make_is_current(2))
time.sleep(2.0)
print(f"  iTunes HTTP calls made: {session.calls}")
print(f"  outcomes: {outcomes}")
print("  -> gen2 (the CURRENT search) receiving an error means it silently lost")
print("     all Spotify results because the STALE generation was cancelled.")

print()
print("=" * 78)
print("EXPERIMENT 4: gateway waiter 'flight[\"data\"]' KeyError when owner dies hard")
print("=" * 78)
reset_gateway()


class BoomSession:
    def get(self, url, timeout=None):
        raise BaseException("simulated hard death")


res = {}


def waiter():
    try:
        ITunesGateway.get("https://itunes.apple.com/x", session=BoomSession(), timeout=1.0)
        res["waiter"] = "ok"
    except BaseException as e:
        res["waiter"] = f"{type(e).__name__}: {e}"


th = threading.Thread(target=waiter)
th.start()
th.join(3)
print(f"  waiter outcome: {res}")
print("  (BaseException in the owner leaves flight without 'data'/'error')")
