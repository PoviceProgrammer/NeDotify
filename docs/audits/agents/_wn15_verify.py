"""WN-15 verification scratch script (read-only against the repo)."""
import os
import sys
import time
import threading

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from core.resolver import StreamResolver
import core.resolver as resolver_module
from core.playback_recovery import same_recording, _callback_result

print("=" * 70)
print("V1: single-flight waiter timeout (12s) vs slow cascade")
print("=" * 70)

r = StreamResolver(db=None, resolve_timeout=1.0)   # shrink the wait for the test
calls = {"n": 0}


def slow_cascade():
    calls["n"] += 1
    time.sleep(2.5)          # slower than resolve_timeout
    return "https://cdn.example/ok.mp3", None


results = {}


def worker(name):
    results[name] = r.resolve("youtube", "vid1", slow_cascade)


t1 = threading.Thread(target=worker, args=("owner",))
t2 = threading.Thread(target=worker, args=("waiter",))
t1.start()
time.sleep(0.2)
t2.start()
t1.join()
t2.join()
print("resolver_fn invocations:", calls["n"], "(1 == single-flight held)")
print("owner result:", results["owner"])
print("waiter result:", results["waiter"])
print("=> waiter got None while the flight succeeded:", results["owner"] is not None and results["waiter"] is None)
print("stats:", r.stats())

print()
print("=" * 70)
print("V2: the flight is NOT left behind after an exception")
print("=" * 70)
r2 = StreamResolver(db=None)


def boom():
    raise RuntimeError("provider exploded")


print("first resolve ->", r2.resolve("youtube", "vid2", boom))
print("inflight after exception:", r2._inflight)
print("=> leaked flight:", bool(r2._inflight))

print()
print("=" * 70)
print("V3: a HANGING resolver_fn leaves the flight behind forever")
print("=" * 70)
r3 = StreamResolver(db=None, resolve_timeout=0.5)


def hang():
    time.sleep(30)
    return "https://cdn.example/late.mp3", None


holder = {}


def owner():
    holder["v"] = r3.resolve("youtube", "vid3", hang)


th = threading.Thread(target=owner, daemon=True)
th.start()
time.sleep(0.3)
print("inflight while owner hangs:", list(r3._inflight.keys()))
print("second resolve ->", r3.resolve("youtube", "vid3", lambda: ("X", None)))
print("inflight still:", list(r3._inflight.keys()))
print("=> key is permanently stalled while the owner hangs")

print()
print("=" * 70)
print("V4: resolve() never records a 'failed' verdict of its own")
print("=" * 70)
r4 = StreamResolver(db=None)
print("resolve with no URL ->", r4.resolve("youtube", "vid4", lambda: (None, "network down")))
print("failed memo:", r4._failed)
print("is_unavailable:", r4.is_unavailable("youtube", "vid4"))
print("=> a transient network failure is NOT blacklisted:", not r4._failed)

print()
print("=" * 70)
print("V5: mark_unavailable TTL")
print("=" * 70)
r5 = StreamResolver(db=None)
r5.mark_unavailable("soundcloud", "123")
print("immediately unavailable:", r5.is_unavailable("soundcloud", "123"))
print("resolve answers None:", r5.resolve("soundcloud", "123", lambda: ("https://x/y.mp3", None)))
print("failed memo:", r5._failed)

print()
print("=" * 70)
print("V6: same_recording with an unknown (0) duration")
print("=" * 70)
print("wanted dur=0 vs offered 'Totally Different Song' dur=180:",
      same_recording({"title": "Song", "artist": "Artist", "duration": 0},
                     {"title": "Totally Different Song", "artist": "Artist", "duration": 180}))
print("wanted dur=180 vs offered dur=0 (provider gave no duration):",
      same_recording({"title": "Song", "artist": "Artist", "duration": 180},
                     {"title": "Song", "artist": "Artist", "duration": 0}))
print("same title, different artist, dur unknown:",
      same_recording({"title": "Song", "artist": "Artist", "duration": 0},
                     {"title": "Song", "artist": "Other", "duration": 0}))

print()
print("=" * 70)
print("V7: _callback_result timeout does NOT bound a blocking invoke()")
print("=" * 70)
t0 = time.monotonic()
val, meta = _callback_result(lambda ok, bad: time.sleep(2.0), 0.2)
dt = time.monotonic() - t0
print(f"timeout was 0.2s, invoke blocked 2.0s -> returned after {dt:.2f}s, value={val}")
print("=> the timeout only bounds the WAIT after invoke() returned:", dt > 1.0)

print()
print("=" * 70)
print("V8: _callback_result ignores a late callback after the timeout")
print("=" * 70)
holder2 = {}


def late(d, f):
    holder2["cb"] = d


def blocking_invoke(ok, bad):
    def fire_later():
        time.sleep(0.5)
        ok("https://cdn.example/late.mp3", {"title": "x"})
    threading.Thread(target=fire_later, daemon=True).start()


val, meta = _callback_result(blocking_invoke, 0.1)
print("returned:", val, meta)
time.sleep(0.8)
print("late callback was ignored (no crash, no late mutation):", val is None)

print()
print("=" * 70)
print("V9: stream_url_expired on URLs without an expiry token")
print("=" * 70)
from utils.stream_urls import stream_url_expired
print("plain CDN url:", stream_url_expired("https://cdn.example/a.mp3"))
print("google with expire in the future:",
      stream_url_expired(f"https://r1.googlevideo.com/videoplayback?expire={int(time.time())+3600}"))
print("google with expire in the past:",
      stream_url_expired(f"https://r1.googlevideo.com/videoplayback?expire={int(time.time())-10}"))
print("http-date Expires param:",
      stream_url_expired("https://cdn.example/a.mp3?Expires=Wed,%2021%20Oct%202015%2007:28:00%20GMT"))
print("expire within the 60s margin:",
      stream_url_expired(f"https://r1.googlevideo.com/videoplayback?expire={int(time.time())+10}"))

print()
print("=" * 70)
print("V10: DB hit refreshes the mem timestamp (TTL restart)")
print("=" * 70)


class FakeDB:
    def __init__(self):
        self.rows = {}

    def get_cached_stream(self, source, source_id, max_age_seconds=14400):
        return self.rows.get((source, source_id))

    def cache_stream(self, source, source_id, url):
        self.rows[(source, source_id)] = {"stream_url": url}

    def invalidate_cached_stream(self, source, source_id):
        self.rows.pop((source, source_id), None)


db = FakeDB()
db.rows[("youtube", "v")] = {"stream_url": "https://cdn.example/db.mp3"}
r10 = StreamResolver(db=db, mem_ttl=3600.0)
print("db hit:", r10.get_cached_url("youtube", "v"))
entry = r10._mem[("youtube", "v")]
print("mem entry timestamp age (s):", round(time.time() - entry[1], 3))
print("=> the mem TTL restarts from the DB read, not from cached_at")

print()
print("=" * 70)
print("V11: _mem cap and LRU")
print("=" * 70)
print("_MEM_MAX_SIZE:", resolver_module._MEM_MAX_SIZE, "_FAIL_MAX_SIZE:", resolver_module._FAIL_MAX_SIZE)
print("_MEM_TTL:", resolver_module._MEM_TTL, "_RESOLVE_TIMEOUT:", resolver_module._RESOLVE_TIMEOUT,
      "_DB_MAX_AGE:", resolver_module._DB_MAX_AGE, "_FAIL_TTL:", resolver_module._FAIL_TTL)
