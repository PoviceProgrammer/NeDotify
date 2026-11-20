"""Scratch harness for WN-21 (Role A). Read-only wrt the repo."""
import os
import sys
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from services.itunes_gateway import ITunesGateway, CatalogueUnavailable  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Simulates iTunes latency; records call order."""

    def __init__(self, delay=0.2):
        self.delay = delay
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append((url, time.monotonic()))
        time.sleep(self.delay)
        return FakeResponse({"results": [{"trackName": "T", "artistName": "A"}]})


def reset_gateway():
    ITunesGateway._entries.clear()
    ITunesGateway._flights.clear()
    ITunesGateway._recent.clear()
    ITunesGateway._next_at = 0.0
    ITunesGateway._active = False


print("=" * 78)
print("EXPERIMENT 1: global 3.5s throttle vs the 6s bridge provider timeout")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.4)

# search #1 (query "a") -> immediate slot
t0 = time.monotonic()
ITunesGateway.get("https://itunes.apple.com/search?term=a", session=session, timeout=3.5)
print(f"  request#1 'a' completed after {time.monotonic() - t0:.2f}s")

# search #2 (query "ab") issued 0.3s later -> must wait for _next_at
time.sleep(0.3)
t1 = time.monotonic()
ITunesGateway.get("https://itunes.apple.com/search?term=ab", session=session, timeout=3.5)
d2 = time.monotonic() - t1
print(f"  request#2 'ab' completed after {d2:.2f}s (started {t1 - t0:.2f}s after #1)")
print(f"  -> request#2 alone took {d2:.2f}s; bridge kills the provider at 6.00s")

print()
print("=" * 78)
print("EXPERIMENT 2: how many queued iTunes requests fit in the 8s gateway deadline?")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.1)
errors = []
oks = []


def worker(i):
    t = time.monotonic()
    try:
        ITunesGateway.get(f"https://itunes.apple.com/search?term=q{i}", session=session, timeout=3.5)
        oks.append((i, time.monotonic() - t))
    except CatalogueUnavailable as e:
        errors.append((i, round(time.monotonic() - t, 2), str(e)))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
for th in threads:
    th.start()
for th in threads:
    th.join()
print(f"  ok      : {[(i, round(d, 2)) for i, d in oks]}")
print(f"  failed  : {errors}")

print()
print("=" * 78)
print("EXPERIMENT 3: stale generation's cancellation error poisons the current generation")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.05)

# --- emulate core/api.py::search generation bookkeeping ---
search_lock = threading.Lock()
search_generation = [0]
generation = [0]


def is_current_for(gen):
    with search_lock:
        return gen == search_generation[0]


with search_lock:
    search_generation[0] += 1
    gen1 = search_generation[0]

# gen1 starts a Spotify search for "same query"
results = {}


def spotify_search(query, is_current, label):
    """Mirrors SpotifyService.search -> _cached_spotify_search -> ITunesGateway.get."""
    try:
        data = ITunesGateway.get("https://itunes.apple.com/search?term=same", session=session,
                                 timeout=3.5, is_current=is_current)
        results[label] = ("ok", len(data.get("results", [])))
    except Exception as e:
        results[label] = ("error", type(e).__name__, str(e))


th1 = threading.Thread(target=spotify_search, args=("same", is_current_for(gen1), "gen1"))
th1.start()
time.sleep(0.05)  # gen1 is inside the gateway, queued behind the throttle

# a NEW search arrives (new generation) with the SAME query -> same cache key
with search_lock:
    search_generation[0] += 1
    gen2 = search_generation[0]

# gen2 JOINS the pending request via BaseMusicService._join_request (same key)
from services.base_service import BaseMusicService  # noqa: E402


class FakeSpotify(BaseMusicService):
    pass


svc = FakeSpotify()
key = "spotify_search:same:None:20"
leader, cb2, eb2 = svc._join_request(key, lambda *a: results.__setitem__("gen2_cb", ("ok", a)),
                                     lambda e: results.__setitem__("gen2_cb", ("error", str(e))))
print(f"  gen2 joined the pending request as leader? {leader}  (False => piggyback)")
th1.join()
time.sleep(0.2)
print(f"  results: {results}")

print()
print("=" * 78)
print("EXPERIMENT 4: does a stale request's failure reach the joined (current) listener?")
print("=" * 78)
reset_gateway()
session = FakeSession(delay=0.05)
results2 = {}


def spotify_search2(is_current, label):
    try:
        data = ITunesGateway.get("https://itunes.apple.com/search?term=same2", session=session,
                                 timeout=3.5, is_current=is_current)
        results2[label] = ("ok", len(data.get("results", [])))
    except Exception as e:
        results2[label] = ("error", type(e).__name__, str(e))


with search_lock:
    search_generation[0] += 1
    genA = search_generation[0]

thA = threading.Thread(target=spotify_search2, args=(is_current_for(genA), "genA"))
thA.start()
time.sleep(0.02)

# genB (current) joins the SAME cache key while genA is still queued in the gateway
svc2 = FakeSpotify()
leader, cbB, ebB = svc2._join_request("spotify_search:same2:None:20",
                                      lambda *a: results2.__setitem__("genB", ("ok", a)),
                                      lambda e: results2.__setitem__("genB", ("error", str(e))))
print(f"  genB leader? {leader}")
# genB becomes current -> genA is now stale
with search_lock:
    search_generation[0] += 1
    genB_cur = search_generation[0]
print(f"  genA is_current now? {is_current_for(genA)}  genB is_current? {is_current_for(genB_cur)}")
thA.join()
time.sleep(0.3)
print(f"  results2: {results2}")
print("  -> if genB got ('error', CatalogueUnavailable) then the CURRENT search lost its results")
