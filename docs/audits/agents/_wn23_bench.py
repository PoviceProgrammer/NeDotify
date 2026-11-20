"""WN-23 reviewer-B scratch benchmark. Read-only against the repo; uses a temp DB."""
import os
import sys
import tempfile
import threading
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from core.database import DatabaseManager          # noqa: E402
from core.settings import SettingsManager          # noqa: E402
from services.taste_profile import UserTasteProfile  # noqa: E402


def seed(db, n_tracks=200, n_history=5000, n_favorites=300):
    ids = []
    for i in range(n_tracks):
        tid = db.add_track(title=f"Track {i}", artist=f"Artist {i % 25}",
                           source="youtube", source_id=f"id{i}", duration=200)
        ids.append(tid)
    for i in range(n_favorites):
        db.toggle_favorite(ids[i % n_tracks])
    for i in range(n_history):
        db.add_to_history(ids[i % n_tracks], duration_listened=200, completed=True)


def timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return (time.perf_counter() - t0) * 1000.0, out


def main():
    tmp = tempfile.mkdtemp(prefix="wn23_")
    db = DatabaseManager(os.path.join(tmp, "bench.db"))
    settings = SettingsManager(db)
    seed(db)
    print(f"db rows: tracks={db.get_tracks_count()} history={db.conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]}")

    # ---------- 1. profile build cost, same thread vs another thread ----------
    print("\n=== 1. UserTasteProfile.build_from_db ===")
    ms_cold, _ = timed(UserTasteProfile(settings=settings).build_from_db, db)
    print(f"  cold build (first)          : {ms_cold:8.1f} ms")
    ms_warm, _ = timed(UserTasteProfile(settings=settings).build_from_db, db)
    print(f"  warm build (same thread)    : {ms_warm:8.1f} ms   <- memo hit")

    other = {}

    def from_other_thread():
        other["ms"], _p = timed(UserTasteProfile(settings=settings).build_from_db, db)

    t = threading.Thread(target=from_other_thread)
    t.start(); t.join()
    print(f"  build from another thread   : {other['ms']:8.1f} ms   <- memo MISS (revision embeds conn)")

    # prove it: the revision contains the thread-local connection object
    from services import taste_profile as tp
    conn_a = db.conn
    try:
        print("  raw PRAGMA data_version ->", conn_a.execute('PRAGMA data_version').fetchone()[0])
    except Exception as e:
        print("  raw PRAGMA data_version raised", type(e).__name__, e)
    rev_a = UserTasteProfile._connection_revision(conn_a)
    print("  rev_a =", type(rev_a).__name__, rev_a if not isinstance(rev_a, tuple) else (rev_a[1], rev_a[2], rev_a[3]))

    revs = {}

    def grab_rev(name):
        c = db.conn                      # thread-local connection, created here
        revs[name] = UserTasteProfile._connection_revision(c)

    for name in ("t1", "t2", "t3"):
        th = threading.Thread(target=grab_rev, args=(name,)); th.start(); th.join()
    rev_b = revs["t1"]
    print(f"  revision equal across connections? {rev_a == rev_b}   (rev_a[0] is rev_b[0]: {rev_a[0] is rev_b[0]})")
    print(f"  rev_t1 == rev_t2 (two worker threads): {revs['t1'] == revs['t2']}")
    print(f"  cache_key identical across threads? {UserTasteProfile._cache_key(db) == UserTasteProfile._cache_key(db)}")

    # ---------- 2. connection accounting ----------
    print("\n=== 2. DatabaseManager._all_conns ===")
    print(f"  tracked connections after 1 bridge-ish thread + 1 worker thread: {len(db._all_conns)}")
    n0 = len(db._all_conns)
    threads = []
    for _ in range(12):
        th = threading.Thread(target=lambda: db.conn.execute('SELECT 1').fetchone())
        th.start(); threads.append(th)
    for th in threads:
        th.join()
    print(f"  tracked connections after 12 short-lived threads: {len(db._all_conns)} (was {n0})")
    print("  -> dead threads keep their sqlite handle in _all_conns until process exit")

    # ---------- 3. artist_aliases / _content_key cost vs N bindings ----------
    print("\n=== 3. alias table rebuild cost vs number of artist_bindings ===")
    import services.recommendation_service as rs
    from services.artist_identity import artist_aliases
    svc = rs.RecommendationService.__new__(rs.RecommendationService)
    svc.settings = settings
    svc.logger = __import__("logging").getLogger("bench")

    for n_bind in (0, 10, 50, 200):
        bindings = {}
        for i in range(n_bind):
            bindings[f"Artist {i}"] = {"catalog_ids": {"youtube": f"ytid{i}"}}
        settings.set("personalization", "artist_bindings", bindings)
        t0 = time.perf_counter()
        for _ in range(1000):
            artist_aliases(settings)
        per = (time.perf_counter() - t0) / 1000 * 1000
        t0 = time.perf_counter()
        for _ in range(1000):
            svc._content_key({"title": "Song", "artist": "Artist 3", "source": "youtube", "source_id": "x"})
        per_key = (time.perf_counter() - t0) / 1000 * 1000
        print(f"  bindings={n_bind:4d}  artist_aliases()={per:7.3f} ms/call   _content_key()={per_key:7.3f} ms/call")

    settings.set("personalization", "artist_bindings", {})

    # ---------- 4. how many alias rebuilds does one _rank_tracks do? ----------
    print("\n=== 4. alias rebuilds inside one _rank_tracks call ===")
    calls = {"n": 0}
    orig = rs.artist_aliases

    def counting(settings=None):
        calls["n"] += 1
        return orig(settings)

    rs.artist_aliases = counting
    try:
        profile = UserTasteProfile(settings=settings).build_from_db(db)
        candidates = [{"title": f"C{i}", "artist": f"Artist {i % 20}", "source": "youtube",
                       "source_id": f"c{i}", "duration": 200,
                       "recommendation_relevance": 0.9} for i in range(50)]
        calls["n"] = 0
        ms, ranked = timed(svc._rank_tracks, candidates, profile, 20)
        print(f"  candidates=50  favourites={len(profile.favorite_tracks)}  "
              f"recent={len(profile.recent_history)}  ranked={len(ranked)}")
        print(f"  artist_aliases() rebuilds inside _rank_tracks : {calls['n']}")
        print(f"  wall time                                      : {ms:8.1f} ms")
    finally:
        rs.artist_aliases = orig

    # ---------- 5. history table growth: get_history query plan ----------
    print("\n=== 5. query plans on the (unbounded) history table ===")
    cur = db.conn.cursor()
    for sql in (
        "SELECT t.id, MAX(h.played_at) FROM history h JOIN tracks t ON h.track_id=t.id "
        "GROUP BY t.id ORDER BY 2 DESC LIMIT 30",
    ):
        for row in cur.execute("EXPLAIN QUERY PLAN " + sql):
            print("   ", row[-1])
    sql = ("SELECT t.artist, COUNT(h.id) FROM history h JOIN tracks t ON h.track_id=t.id "
           "GROUP BY LOWER(t.artist) ORDER BY 2 DESC LIMIT 5")
    for row in cur.execute("EXPLAIN QUERY PLAN " + sql):
        print("   ", row[-1])
    sql = ("SELECT t.* FROM tracks t JOIN history h ON t.id=h.track_id "
           "ORDER BY h.played_at DESC LIMIT 30")
    for row in cur.execute("EXPLAIN QUERY PLAN " + sql):
        print("   ", row[-1])

    db.close()


if __name__ == "__main__":
    main()
