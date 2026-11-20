"""WN-23-B measurement (final): settings-less alias table, 200k history scan,
and negative caching of an empty candidate set."""
import sys, os, time, tempfile
REPO = os.path.join(os.path.expanduser("~"), "NeDotify", "AURA_Music_backup", "AURA_Music_main")
sys.path.insert(0, REPO)
os.chdir(REPO)

from types import SimpleNamespace
from core.database import DatabaseManager
import services.recommendation_service as rs
from services.taste_profile import UserTasteProfile
from services.artist_identity import canonical_artist, track_key

print("=== 1. settings-less profile builder loses the USER alias table ===")


class S:
    def __init__(self, extra=None):
        self.v = {("personalization", "artist_aliases"): {},
                  ("personalization", "artist_bindings"): {},
                  ("personalization", "blocked_artists"): [],
                  ("personalization", "disliked_tracks"): [],
                  ("personalization", "favorite_genres"): [],
                  ("personalization", "discovery_ratio"): 0.2}
        if extra:
            self.v.update(extra)

    def get(self, cat, key, default=None):
        return self.v.get((cat, key), default)

    def set(self, cat, key, value):
        self.v[(cat, key)] = value


alias = "\u041c\u043e\u0435\u043a\u0442"   # "Moekt"
s = S({("personalization", "artist_aliases"): {alias.lower(): "MOEKT"}})
with_s = UserTasteProfile(settings=s)
without_s = UserTasteProfile()
print("  aliases with settings   :", with_s.artist_aliases)
print("  aliases without settings:", without_s.artist_aliases)
row = {"artist": alias, "title": "T"}
print("  track_key(with)    =", track_key(row, with_s.artist_aliases))
print("  track_key(without) =", track_key(row, without_s.artist_aliases))

print()
print("=== 2. get_history() with a 200 000-row history table ===")
tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "big.db"))
ids = [db.add_track("T%d" % i, artist="A%d" % (i % 40), source="youtube",
                    source_id="x%d" % i, duration=200) for i in range(400)]
db.conn.executemany(
    "INSERT INTO history (track_id, duration_listened, completed) VALUES (?, 180, 1)",
    [(ids[i % 400],) for i in range(200000)])
db.conn.commit()
for label, fn in (("get_history(30)", lambda: db.get_history(limit=30)),
                  ("get_user_history_tracks(20)", lambda: db.get_user_history_tracks(limit=20)),
                  ("get_top_artists(10)", lambda: db.get_top_artists(limit=10)),
                  ("get_analytics_summary()", lambda: db.get_analytics_summary()),
                  ("get_wrapped_stats(all)", lambda: db.get_wrapped_stats(period="all")),
                  ("get_recommendation_quality(3650)", lambda: db.get_recommendation_quality(3650))):
    t0 = time.perf_counter()
    fn()
    print("  %-32s %8.1f ms" % (label, (time.perf_counter() - t0) * 1000))
db.close()

print()
print("=== 3. empty candidate set is NOT cached -> every home load re-runs providers ===")
tmp2 = tempfile.mkdtemp(prefix="wn23b_")
db2 = DatabaseManager(os.path.join(tmp2, "t.db"))
for i in range(30):
    tid = db2.add_track("S%d" % i, artist="A%d" % (i % 5), source="youtube",
                        source_id="s%d" % i, duration=200)
    db2.add_to_history(tid, duration_listened=180, completed=True)

calls = {"yt": 0}


def failing_related(*a, **k):
    calls["yt"] += 1
    raise RuntimeError("provider down")


yt = SimpleNamespace(get_related_tracks_sync=failing_related,
                     search_sync=lambda *a, **k: [])
sc = SimpleNamespace(get_related_tracks_sync=failing_related)
lastfm = SimpleNamespace(_resolve_api_keys=lambda: [],
                         artist=SimpleNamespace(getTopTracks=lambda *a, **k: []),
                         track=SimpleNamespace(getSimilar=lambda *a, **k: []))
rs.LastFMService = lambda **kw: lastfm
svc = rs.RecommendationService(settings=S(), db=db2, soundcloud_service=sc, youtube_service=yt)
svc._candidate_executor.shutdown(wait=True)   # keep the fan-out deterministic

for i in range(3):
    before = calls["yt"]
    svc.get_flow_tracks_sync({"artist": "A0", "title": "S0", "source_id": "s0"}, limit=5)
    print("  home load #%d -> provider calls made: %d" % (i + 1, calls["yt"] - before))

print()
print("=== 4. one failing provider + one working provider: is the failure visible? ===")
svc2 = rs.RecommendationService(settings=S(), db=db2, soundcloud_service=sc,
                                youtube_service=SimpleNamespace(
                                    get_related_tracks_sync=failing_related,
                                    search_sync=lambda *a, **k: []))
svc2._candidate_executor.shutdown(wait=True)
profile = UserTasteProfile(settings=S())
profile.top_artists = [{"name": "A0", "play_count": 5}]
profile.recent_history = [{"id": 1, "title": "S0", "artist": "A0", "source": "youtube",
                           "source_id": "s0", "duration": 200}]
profile.favorite_tracks = []
print("  feed with a DOWN provider and a non-empty profile ->",
      svc2._feed_tracks(profile, 10))
print("  (empty list == indistinguishable from 'no taste')")
svc2._candidate_executor.shutdown(wait=True)
db2.close()
