"""WN-23 reviewer-B scratch benchmark #3: bridge-thread cost of get_flow_tracks_sync."""
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import logging  # noqa: E402
from core.database import DatabaseManager          # noqa: E402
from core.settings import SettingsManager          # noqa: E402
import services.recommendation_service as rs     # noqa: E402
from services.base_service import BaseMusicService  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="wn23c_")
    db = DatabaseManager(os.path.join(tmp, "b.db"))
    settings = SettingsManager(db)
    ids = [db.add_track(title=f"T{i}", artist=f"A{i % 10}", source="youtube",
                         source_id=f"i{i}", duration=200) for i in range(50)]
    for i in range(20):
        db.toggle_favorite(ids[i])
    for i in range(500):
        db.add_to_history(ids[i % 50], duration_listened=200, completed=True)

    slow = {"delay": 0.0}

    def related(sid, **kw):
        time.sleep(slow["delay"])
        return [{"title": "New", "artist": "Other", "source": "youtube",
                 "source_id": "newid", "duration": 200}]

    yt = SimpleNamespace(get_related_tracks_sync=related, search_sync=lambda *a, **k: [])
    sc = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [])
    lastfm = SimpleNamespace(_resolve_api_keys=lambda: [], artist=SimpleNamespace(getTopTracks=lambda *a, **k: []),
                             track=SimpleNamespace(getSimilar=lambda *a, **k: []))
    rs.LastFMService = lambda **kw: lastfm

    svc = rs.RecommendationService(settings=settings, db=db, soundcloud_service=sc, youtube_service=yt)

    # count profile builds
    builds = {"n": 0}
    import services.taste_profile as tp
    orig_build = tp.UserTasteProfile.build_from_db

    def counting(self, database):
        builds["n"] += 1
        return orig_build(self, database)

    tp.UserTasteProfile.build_from_db = counting
    try:
        seed = {"title": "Seed", "artist": "A1", "source": "youtube", "source_id": "seedid", "id": 1}

        for delay in (0.0, 3.0, 9.0):
            slow["delay"] = delay
            n0 = len(db._all_conns)
            builds["n"] = 0
            out = {}
            # unique seed id -> defeats the 'recommendation:candidates:' cache
            seed = {"title": "Seed", "artist": "A1", "source": "youtube",
                    "source_id": f"seedid-{delay}", "id": 1}

            def run():
                t0 = time.perf_counter()
                out["tracks"] = svc.get_flow_tracks_sync(seed, limit=6, exclude_ids=[])
                out["ms"] = (time.perf_counter() - t0) * 1000

            th = threading.Thread(target=run)   # exactly how pywebview dispatches a js_api call
            th.start(); th.join()
            print(f"  provider delay={delay:4.1f}s -> get_flow_tracks_sync blocked {out['ms']:8.1f} ms on the "
                  f"bridge thread, {builds['n']} profile build(s), "
                  f"{len(db._all_conns) - n0} new SQLite connection(s) left in _all_conns, "
                  f"tracks={len(out['tracks'])}")

        # 20 sequential track transitions, each on its own thread (pywebview model)
        n0 = len(db._all_conns)
        for i in range(20):
            seed_i = {"title": "Seed", "artist": "A1", "source": "youtube",
                      "source_id": f"seedid-loop{i}", "id": 1}

            def run_i(s=seed_i):
                svc.get_flow_tracks_sync(s, limit=6, exclude_ids=[])

            th = threading.Thread(target=run_i)
            th.start(); th.join()
        print(f"\n  20 sequential flow requests (one per track change) -> "
              f"{len(db._all_conns) - n0} SQLite connections added to _all_conns and never closed")
    finally:
        tp.UserTasteProfile.build_from_db = orig_build
        svc._candidate_executor.shutdown(wait=True)
    db.close()


if __name__ == "__main__":
    main()
