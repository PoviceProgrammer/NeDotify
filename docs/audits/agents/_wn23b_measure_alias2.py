"""WN-23-B measurement: alias-table rebuild blow-up + memo deepcopy cost."""
import sys, os, time, copy, threading
REPO = os.path.join(os.path.expanduser("~"), "NeDotify", "AURA_Music_backup", "AURA_Music_main")
sys.path.insert(0, REPO)
os.chdir(REPO)

import services.artist_identity as ai
import services.recommendation_service as rs
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile

calls = {"n": 0}
_orig = ai.artist_aliases
rs.artist_aliases = lambda s=None: (calls.__setitem__("n", calls["n"] + 1), _orig(s))[1]


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


def track(sid, title, artist="Artist", **kw):
    return dict(source="youtube", source_id=sid, title=title, artist=artist, duration=180, **kw)


def scenario(n_disliked, n_favourites, n_candidates=50):
    disliked = [{"artist": "D%d" % i, "title": "DT%d" % i} for i in range(n_disliked)]
    s = S({("personalization", "disliked_tracks"): disliked})
    svc = RecommendationService(settings=s)
    profile = UserTasteProfile()
    profile.top_artists = [{"name": "Artist", "play_count": 30}]
    profile.favorite_tracks = [track("f%d" % i, "Fav %d" % i, "FavArtist %d" % i) for i in range(n_favourites)]
    profile.recent_history = [track("h", "Hist", "Artist")]
    profile.genre_distribution = {"Pop": 1.0}
    candidates = [track("c%d" % i, "C%d" % i, "Artist %d" % (i % 5)) for i in range(n_candidates)]
    calls["n"] = 0
    t0 = time.perf_counter()
    svc._rank_tracks(candidates, profile, 20)
    dt = (time.perf_counter() - t0) * 1000
    svc._candidate_executor.shutdown(wait=True)
    return calls["n"], dt


print("=== _rank_tracks(50 candidates): alias rebuilds vs feedback/favourite volume ===")
for nd, nf in ((0, 0), (100, 0), (1000, 0), (0, 200), (0, 1000), (1000, 1000)):
    n, dt = scenario(nd, nf)
    print("  disliked=%5d favourites=%5d -> artist_aliases() calls=%7d  elapsed=%8.1f ms" % (nd, nf, n, dt))

print()
print("=== memo state deepcopy cost (module-global lock held during both copies) ===")
profile = UserTasteProfile()
profile.recent_history = [track("h%d" % i, "H%d" % i, "A%d" % (i % 30)) for i in range(1500)]
profile.favorite_tracks = [track("f%d" % i, "F%d" % i, "A%d" % (i % 30)) for i in range(1500)]
profile.downloaded_tracks = [track("d%d" % i, "D%d" % i, "A%d" % (i % 30)) for i in range(1500)]
profile.playlist_tracks = [track("p%d" % i, "P%d" % i, "A%d" % (i % 30)) for i in range(1500)]
profile.top_tracks = profile.recent_history[:20]
profile.top_artists = [{"name": "A%d" % i, "play_count": 1.0} for i in range(20)]
profile.genre_distribution = {"G%d" % i: 0.1 for i in range(50)}
state = {f: getattr(profile, f) for f in UserTasteProfile._STATE_FIELDS}
t0 = time.perf_counter()
for _ in range(20):
    copy.deepcopy(state)
print("  deepcopy of a 6000-row profile state: %.2f ms per copy" % ((time.perf_counter() - t0) * 1000 / 20))
print("  (one copy on cache GET, one on cache PUT, both under _profile_cache_lock)")

print()
print("=== settings-less profile builders: alias table not applied ===")
s = S({("personalization", "artist_aliases"): {"\u0444\u0430\u0440\u0430\u043e\u043d": "PHARAOH"}})
with_settings = UserTasteProfile(settings=s)
without = UserTasteProfile()
print("  artist_aliases(settings) =", with_settings.artist_aliases)
print("  artist_aliases(None)     =", without.artist_aliases)
from services.artist_identity import canonical_artist
print("  canonical_artist(alias, with)    =", canonical_artist("\u0444\u0430\u0440\u0430\u043e\u043d", with_settings.artist_aliases))
print("  canonical_artist(alias, without) =", canonical_artist("\u0444\u0430\u0440\u0430\u043e\u043d", without.artist_aliases))
