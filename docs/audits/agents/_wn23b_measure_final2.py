"""WN-23-B measurement: empty candidate set is not cached; provider failure is
indistinguishable from 'no taste'."""
import sys, os, time, tempfile
REPO = os.path.join(os.path.expanduser("~"), "NeDotify", "AURA_Music_backup", "AURA_Music_main")
sys.path.insert(0, REPO)
os.chdir(REPO)

from types import SimpleNamespace
from core.database import DatabaseManager
import services.recommendation_service as rs
from services.taste_profile import UserTasteProfile


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


tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "t.db"))
for i in range(30):
    tid = db.add_track("S%d" % i, artist="A%d" % (i % 5), source="youtube",
                        source_id="s%d" % i, duration=200)
    db.add_to_history(tid, duration_listened=180, completed=True)

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
svc = rs.RecommendationService(settings=S(), db=db, soundcloud_service=sc, youtube_service=yt)

print("=== 3. empty candidate set is NOT cached -> every home load re-runs providers ===")
for i in range(3):
    before = calls["yt"]
    out = svc.get_flow_tracks_sync({"artist": "A0", "title": "S0", "source_id": "s0",
                                    "source": "youtube"}, limit=5)
    print("  home load #%d -> provider calls made: %d, result: %r" % (i + 1, calls["yt"] - before, out))

print()
print("=== 4. provider down + non-empty profile -> the feed is [] (same as 'no taste') ===")
profile = UserTasteProfile(settings=S())
profile.top_artists = [{"name": "A0", "play_count": 5}]
profile.recent_history = [{"id": 1, "title": "S0", "artist": "A0", "source": "youtube",
                           "source_id": "s0", "duration": 200}]
profile.favorite_tracks = []
feed = svc._feed_tracks(profile, 10)
print("  _feed_tracks(profile, 10) with the provider down ->", feed)

print()
print("=== 5. empty profile + provider down -> curated welcome tracks (no error surfaced) ===")
empty = UserTasteProfile(settings=S())
feed2 = svc._feed_tracks(empty, 10)
print("  _feed_tracks(empty_profile, 10) ->", [t["title"] for t in feed2])

svc._candidate_executor.shutdown(wait=True)
db.close()
