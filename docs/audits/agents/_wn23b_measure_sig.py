"""WN-23-B measurement: cost of the feed cache-key signature."""
import sys, os, time, hashlib
REPO = os.path.join(os.path.expanduser("~"), "NeDotify", "AURA_Music_backup", "AURA_Music_main")
sys.path.insert(0, REPO)
os.chdir(REPO)

from services.taste_profile import UserTasteProfile


def track(sid, title, artist="Artist", **kw):
    return dict(source="youtube", source_id=sid, title=title, artist=artist, duration=180, **kw)


profile = UserTasteProfile()
profile.recent_history = [track("h%d" % i, "H%d" % i, "A%d" % (i % 40)) for i in range(50)]
profile.favorite_tracks = [track("f%d" % i, "F%d" % i, "A%d" % (i % 40)) for i in range(1500)]
profile.downloaded_tracks = [track("d%d" % i, "D%d" % i, "A%d" % (i % 40)) for i in range(1500)]
profile.playlist_tracks = [track("p%d" % i, "P%d" % i, "A%d" % (i % 40)) for i in range(1500)]
profile.top_tracks = profile.favorite_tracks[:20]
profile.top_artists = [{"name": "A%d" % i, "play_count": 1.0} for i in range(20)]

known = profile.recent_history + profile.favorite_tracks + profile.downloaded_tracks \
    + profile.playlist_tracks + profile.top_tracks
print("known tracks in the profile:", len(known))

t0 = time.perf_counter()
seed_signature = tuple((track.get("id"), track.get("title"), track.get("artist"),
                         track.get("source"), track.get("source_id"), track.get("file_path"),
                         track.get("weighted_score"), track.get("is_favorite"),
                         track.get("is_downloaded"), track.get("duration_listened"),
                         track.get("completed"), track.get("media_listened"),
                         track.get("session_finished")) for track in known)
t1 = time.perf_counter()
blob = repr(seed_signature)
t2 = time.perf_counter()
digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
t3 = time.perf_counter()
print("  build seed_signature : %8.2f ms" % ((t1 - t0) * 1000))
print("  repr() size          : %8.1f KiB" % (len(blob) / 1024))
print("  repr()               : %8.2f ms" % ((t2 - t1) * 1000))
print("  sha256               : %8.2f ms" % ((t3 - t2) * 1000))
print("  TOTAL per _feed_tracks call (this part alone): %8.2f ms" % ((t3 - t0) * 1000))
