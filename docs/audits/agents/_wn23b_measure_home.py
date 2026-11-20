"""WN-23-B measurement: one home-page load -> how many taste-profile builds?

Drives the real AppApi bridge methods (get_feed / get_home_releases /
get_home_mixes) against a real DatabaseManager and the real
RecommendationService (provider clients stubbed out), counting
UserTasteProfile.build_from_db() calls and how many of them were full
re-queries (cache miss) vs memo hits.
"""
import sys, os, time, tempfile, threading
from types import SimpleNamespace

sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
os.chdir(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from core.database import DatabaseManager
from core.api import AppApi
import services.recommendation_service as rs
from services.taste_profile import UserTasteProfile

tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "t.db"))

for i in range(120):
    tid = db.add_track(f"Song {i}", artist=f"Artist {i % 6}", source="youtube",
                       source_id=f"s{i}", duration=200, genre="Pop")
    db.add_to_history(tid, duration_listened=180, completed=True)
for i in range(8):
    db.toggle_favorite(db.add_track(f"Fav {i}", artist=f"Artist {i}", source="youtube",
                                    source_id=f"f{i}", duration=200))


class Settings:
    def __init__(self):
        self._d = {("personalization", "artist_aliases"): {},
                  ("personalization", "artist_bindings"): {},
                  ("personalization", "blocked_artists"): [],
                  ("personalization", "disliked_tracks"): [],
                  ("personalization", "favorite_genres"): [],
                  ("personalization", "discovery_ratio"): 0.2}

    def get(self, cat, key, default=None):
        return self._d.get((cat, key), default)

    def set(self, cat, key, value):
        self._d[(cat, key)] = value


settings = Settings()

# --- instrument the profile build -----------------------------------------
orig_build = UserTasteProfile.build_from_db
stats = {"calls": 0, "misses": 0, "selects": 0}
lock = threading.Lock()


def counting_build(self, db_):
    with lock:
        stats["calls"] += 1
    stmts = []
    conn = db_.conn
    conn.set_trace_callback(stmts.append)
    try:
        return orig_build(self, db_)
    finally:
        conn.set_trace_callback(None)
        n = sum(1 for s in stmts if s.lstrip().upper().startswith("SELECT"))
        with lock:
            stats["selects"] += n
            if n > 0:
                stats["misses"] += 1


UserTasteProfile.build_from_db = counting_build

# --- stub the recommendation service --------------------------------------
yt = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [],
                     search_sync=lambda *a, **k: [])
sc = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [])
lastfm = SimpleNamespace(_resolve_api_keys=lambda: [],
                          artist=SimpleNamespace(getTopTracks=lambda *a, **k: []),
                          track=SimpleNamespace(getSimilar=lambda *a, **k: []),
                          chart=SimpleNamespace(getTopTracks=lambda *a, **k: [],
                                                getTopArtists=lambda *a, **k: []),
                          user=SimpleNamespace(getTopArtists=lambda *a, **k: []))
rs.LastFMService = lambda **kw: lastfm

rec = rs.RecommendationService(settings=settings, db=db, soundcloud_service=sc,
                               youtube_service=yt)

core = SimpleNamespace(db=db, settings=settings, cache=None,
                       recommendations=rec, youtube=yt, soundcloud=sc)
api = AppApi(core)

emitted = []
api._emit = lambda name, data=None: emitted.append((name, data))

print("=== one home-page load: get_feed + get_home_releases + get_home_mixes ===")
stats.update(calls=0, misses=0, selects=0)
t0 = time.perf_counter()
api.get_feed(20)
api.get_home_releases(10)
api.get_home_mixes(10)
time.sleep(2.0)   # let the shared executor drain
dt = (time.perf_counter() - t0) * 1000
print(f"  build_from_db calls = {stats['calls']}  (cache misses = {stats['misses']}, SELECTs = {stats['selects']})")
print(f"  wall time = {dt:.0f} ms")
print(f"  events emitted: {[n for n, _ in emitted]}")

print()
print("=== repeated: 5 sequential get_feed() calls ===")
stats.update(calls=0, misses=0, selects=0)
for _ in range(5):
    api.get_feed(20)
time.sleep(2.5)
print(f"  build_from_db calls = {stats['calls']}  (cache misses = {stats['misses']}, SELECTs = {stats['selects']})")

print()
print("=== get_history() cost as the history table grows (full GROUP BY t.id) ===")
for n in (1000, 10000, 50000):
    db2 = DatabaseManager(os.path.join(tmp, f"h{n}.db"))
    ids = [db2.add_track(f"T{i}", artist=f"A{i%30}", source="youtube", source_id=f"x{i}", duration=200)
           for i in range(200)]
    for i in range(n):
        db2.add_to_history(ids[i % 200], duration_listened=180, completed=True)
    t0 = time.perf_counter()
    db2.get_history(limit=30)
    dt = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    db2.get_analytics_summary()
    dt2 = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    db2.get_wrapped_stats(period="all")
    dt3 = (time.perf_counter() - t0) * 1000
    print(f"  history rows={n:6d}: get_history(30)={dt:8.1f} ms | get_analytics_summary={dt2:7.1f} ms | get_wrapped_stats(all)={dt3:8.1f} ms")
    db2.close()

rec._candidate_executor.shutdown(wait=True)
db.close()
