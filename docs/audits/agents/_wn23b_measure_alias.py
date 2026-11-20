"""WN-23-B measurement: alias-table rebuild cost per candidate.

Counts how many times services.artist_identity.artist_aliases() is rebuilt
while RecommendationService._rank_tracks() scores N candidates, and how long
that takes for N configured artist bindings.
"""
import sys, os, time
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
os.chdir(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

import services.artist_identity as ai
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile
from types import SimpleNamespace

calls = {"n": 0}
_orig = ai.artist_aliases


def counting(settings=None):
    calls["n"] += 1
    return _orig(settings)


# Patch the name that recommendation_service imported.
import services.recommendation_service as rs
rs.artist_aliases = counting
# taste_profile also imports it
import services.taste_profile as tp
tp.artist_aliases = counting


class S:
    def __init__(self, bindings):
        self.bindings = bindings

    def get(self, category, key, default=None):
        if category == "personalization":
            if key == "artist_bindings":
                return self.bindings
            if key == "artist_aliases":
                return {}
            if key == "blocked_artists":
                return []
            if key == "disliked_tracks":
                return []
            if key == "favorite_genres":
                return []
            if key == "discovery_ratio":
                return 0.2
        return default


def make_bindings(n):
    return {
        f"Artist {i}": {"catalog_ids": {"youtube": f"vid{i}", "itunes": f"it{i}"}}
        for i in range(n)
    }


def track(sid, title, artist="Artist", **kw):
    return dict(source="youtube", source_id=sid, title=title, artist=artist,
                duration=180, **kw)


def run(n_bindings, n_candidates):
    calls["n"] = 0
    svc = RecommendationService(settings=S(make_bindings(n_bindings)))
    profile = UserTasteProfile()
    profile.top_artists = [{"name": "Artist", "play_count": 30}]
    profile.recent_history = [track("h1", "Known", "Artist")]
    profile.favorite_tracks = [track("f1", "Fav", "Artist")]
    profile.genre_distribution = {"Pop": 1.0}
    candidates = [track(f"c{i}", f"Candidate {i}", f"Artist {i % 7}") for i in range(n_candidates)]
    t0 = time.perf_counter()
    svc._rank_tracks(candidates, profile, 20)
    dt = (time.perf_counter() - t0) * 1000
    svc._candidate_executor.shutdown(wait=True)
    return calls["n"], dt


print("alias rebuilds during _rank_tracks")
for nb, nc in ((0, 10), (0, 50), (50, 50), (50, 200), (200, 50)):
    n, dt = run(nb, nc)
    print(f"  bindings={nb:4d} candidates={nc:4d} -> artist_aliases() calls={n:6d}  elapsed={dt:8.1f} ms")

print()
print("single artist_aliases() rebuild cost")
for nb in (0, 10, 50, 200):
    s = S(make_bindings(nb))
    t0 = time.perf_counter()
    for _ in range(100):
        _orig(s)
    dt = (time.perf_counter() - t0) * 1000 / 100
    print(f"  bindings={nb:4d} -> {dt:8.3f} ms per rebuild")
