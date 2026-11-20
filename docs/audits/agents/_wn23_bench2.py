"""WN-23 reviewer-B scratch benchmark #2: scaling of alias rebuilds + history table growth."""
import os
import sys
import tempfile
import time

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import logging  # noqa: E402
from core.database import DatabaseManager          # noqa: E402
from core.settings import SettingsManager          # noqa: E402
from services.taste_profile import UserTasteProfile  # noqa: E402
import services.recommendation_service as rs     # noqa: E402


def build_db(tmp, n_tracks, n_history, n_favorites):
    db = DatabaseManager(os.path.join(tmp, "b.db"))
    ids = []
    for i in range(n_tracks):
        ids.append(db.add_track(title=f"Track {i}", artist=f"Artist {i % 25}",
                                source="youtube", source_id=f"id{i}", duration=200))
    for i in range(n_favorites):
        db.toggle_favorite(ids[i % n_tracks])
    for i in range(n_history):
        db.add_to_history(ids[i % n_tracks], duration_listened=200, completed=True)
    return db


def main():
    tmp = tempfile.mkdtemp(prefix="wn23b_")
    db = build_db(tmp, n_tracks=300, n_history=5000, n_favorites=300)
    settings = SettingsManager(db)

    svc = rs.RecommendationService.__new__(rs.RecommendationService)
    svc.settings = settings
    svc.logger = logging.getLogger("bench")
    profile = UserTasteProfile(settings=settings).build_from_db(db)
    candidates = [{"title": f"C{i}", "artist": f"Artist {i % 20}", "source": "youtube",
                   "source_id": f"c{i}", "duration": 200,
                   "recommendation_relevance": 0.9} for i in range(50)]

    print("=== A. one _rank_tracks(50 candidates) vs number of artist_bindings ===")
    for n_bind in (0, 25, 100, 400):
        bindings = {f"Artist {i}": {"catalog_ids": {"youtube": f"ytid{i}"}} for i in range(n_bind)}
        settings.set("personalization", "artist_bindings", bindings)
        svc._rank_tracks(candidates, profile, 20)          # warm
        t0 = time.perf_counter()
        for _ in range(5):
            svc._rank_tracks(candidates, profile, 20)
        per = (time.perf_counter() - t0) / 5 * 1000
        print(f"  bindings={n_bind:4d} -> {per:9.1f} ms per _rank_tracks (50 candidates, "
              f"{len(profile.favorite_tracks)} favourites)")
    settings.set("personalization", "artist_bindings", {})

    print("\n=== B. alias rebuild COUNT inside one _rank_tracks ===")
    calls = {"n": 0}
    orig = rs.artist_aliases

    def counting(settings=None):
        calls["n"] += 1
        return orig(settings)

    rs.artist_aliases = counting
    try:
        calls["n"] = 0
        svc._rank_tracks(candidates, profile, 20)
        print(f"  artist_aliases() rebuilds: {calls['n']} for 50 candidates")
        calls["n"] = 0
        svc._feedback()
        print(f"  artist_aliases() rebuilds in one _feedback(): {calls['n']}")
    finally:
        rs.artist_aliases = orig

    print("\n=== C. cost of the history table growing (no pruning) ===")
    db2 = DatabaseManager(os.path.join(tmp, "c.db"))
    ids = [db2.add_track(title=f"T{i}", artist=f"A{i % 20}", source="youtube",
                         source_id=f"i{i}", duration=200) for i in range(200)]
    for i in range(500):
        db2.toggle_favorite(ids[i % 200])
    for target in (5_000, 50_000, 200_000):
        while db2.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] < target:
            for k in range(5000):
                db2.add_to_history(ids[k % 200], duration_listened=200, completed=True)
        n = db2.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        t0 = time.perf_counter(); db2.get_history(limit=30); t_hist = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); db2.get_user_history_tracks(limit=30); t_uh = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); db2.get_wrapped_stats(period="all"); t_wrap = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        UserTasteProfile(settings=settings).build_from_db(db2)
        t_prof = (time.perf_counter() - t0) * 1000
        print(f"  history rows={n:7d}: get_history(30)={t_hist:7.1f} ms  get_user_history_tracks(30)={t_uh:7.1f} ms  "
              f"get_wrapped_stats('all')={t_wrap:8.1f} ms  build_from_db={t_prof:7.1f} ms")

    print("\n=== D. does the history table ever get pruned? ===")
    n_before = db2.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    db2.conn.execute("DELETE FROM history WHERE id < 0")
    db2.conn.commit()
    print(f"  rows before={n_before}; there is no DELETE FROM history in core/database.py "
          f"(grep) -> unbounded")

    db.close(); db2.close()


if __name__ == "__main__":
    main()
