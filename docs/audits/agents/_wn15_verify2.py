"""WN-15 verification part 2: core/offline.py behaviour with a real SQLite DB."""
import os
import sys
import tempfile

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from core.database import DatabaseManager
from core.offline import available_track, available_tracks, offline_library, is_offline

tmp = tempfile.mkdtemp(prefix="wn15_")
db = DatabaseManager(db_path=os.path.join(tmp, "t.db"))

audio = os.path.join(tmp, "song.mp3")
with open(audio, "wb") as fh:
    fh.write(b"x" * 5000)

# 1) a track row in the DB that carries a file_path
tid = db.add_track("Song", "Artist", source="youtube", source_id="vid1", file_path=audio)
print("inserted track id:", tid)

db_row = db.get_track(tid)
print("db row file_path:", db_row.get("file_path"))

print()
print("=" * 70)
print("O1: available_track (single) finds the file via the DB row")
print("=" * 70)
# the in-memory track dict has NO file_path (e.g. it came from the frontend queue)
thin = {"id": tid, "source": "youtube", "source_id": "vid1", "title": "Song", "artist": "Artist"}
one = available_track(db, thin)
print("available_track ->", None if one is None else one.get("file_path"))
print("=> found via db.get_track():", one is not None)

print()
print("=" * 70)
print("O2: available_tracks (plural) MISSES the same track")
print("=" * 70)
many = available_tracks(db, [thin])
print("available_tracks ->", many)
print("=> the same track is 'available' to one helper and 'unavailable' to the other:",
      (one is not None) and (not many))

print()
print("=" * 70)
print("O3: offline_library over the whole table")
print("=" * 70)
lib = offline_library(db)
print("offline_library ->", [(t.get("id"), t.get("file_path")) for t in lib])
print("=> the DB row itself IS found (it carries file_path):", len(lib) == 1)

print()
print("=" * 70)
print("O4: available_tracks ignores the DB row but honours the cached_file_path")
print("=" * 70)
db.cache_stream("youtube", "vid2", "https://cdn.example/x.mp3")
db.set_cached_file("youtube", "vid2", audio)
thin2 = {"id": None, "source": "youtube", "source_id": "vid2", "title": "Song2"}
print("available_tracks([thin2]) ->",
      [t.get("file_path") for t in available_tracks(db, [thin2])])
print("available_track(thin2) ->",
      (available_track(db, thin2) or {}).get("file_path"))

print()
print("=" * 70)
print("O5: is_offline() with the real SettingsManager")
print("=" * 70)
from core.settings import SettingsManager
s = SettingsManager(db_path=os.path.join(tmp, "s.db"))
print("default:", is_offline(s))
s.set("network", "offline_mode", True)
print("after set(True):", is_offline(s))
s.set("network", "offline_mode", "true")
print("after set('true'):", is_offline(s))
s.set("network", "offline_mode", "1")
print("after set('1'):", is_offline(s), " <- string '1' is NOT treated as on")
s.set("network", "offline_mode", False)
print("after set(False):", is_offline(s))

print()
print("=" * 70)
print("O6: a track whose file was deleted -> not offered offline")
print("=" * 70)
os.remove(audio)
print("available_track ->", available_track(db, thin))
print("available_tracks ->", available_tracks(db, [thin]))
print("=> missing files are filtered out:",
      available_track(db, thin) is None and available_tracks(db, [thin]) == [])
