"""WN-08 F: destructive path of clear_storage('all') against a local media file."""
import os
import sys
import tempfile
import types

PROJECT_ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from core.api import AppApi
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn08_")
db_path = os.path.join(tmp, "t.db")
media_dir = os.path.join(tmp, "MyMusic")
os.makedirs(media_dir, exist_ok=True)
user_mp3 = os.path.join(media_dir, "Artist - Title.mp3")
with open(user_mp3, "wb") as fh:
    fh.write(b"ID3\x00\x01" + b"\x00" * 8192)

db = DatabaseManager(db_path)

# 1) The user played the track online -> a library row WITHOUT a file_path.
t1 = db.add_track(title="Title", artist="Artist", album="A", duration=180,
                  source="youtube", source_id="yt123")
row = db.get_track(t1)
print("1) online row: id=%s is_downloaded=%s file_path=%r"
      % (t1, row["is_downloaded"], row["file_path"]))

# 2) The user adds their music folder -> the scanner imports the local file.
t2 = db.add_track(title="Title", artist="Artist", album="A", duration=180,
                  file_path=user_mp3, source="local")
row = db.get_track(t2)
print("2) after local import: same id=%s is_downloaded=%s file_path=%r"
      % (t2, row["is_downloaded"], row["file_path"]))
print("   downloaded tracks now:", [(d["id"], d["file_path"]) for d in db.get_downloaded_tracks()])


class FakeCache:
    cache_dir = os.path.join(tmp, "cache")
    _covers_dir = os.path.join(tmp, "cache", "covers")
    _streams_dir = os.path.join(tmp, "cache", "streams")
    _temp_dir = os.path.join(tmp, "cache", "temp")

    def clear_all(self):
        print("   [cache.clear_all called]")

    def get_storage_details(self):
        return {"used_bytes": 0, "quota_bytes": 0, "quota_gb": 0, "protected_count": 0}


core = types.SimpleNamespace(db=db, settings=None, cache=FakeCache(),
                              scanner=types.SimpleNamespace(_covers_dir=FakeCache._covers_dir))
api = AppApi(core)
api._emit = lambda *a, **k: None

print("3) file exists before clear_storage('all'):", os.path.exists(user_mp3))
res = api.clear_storage("all")
print("4) clear_storage('all') ->", res)
print("5) file exists AFTER  clear_storage('all'):", os.path.exists(user_mp3))
print("6) DB rows still say:",
      [(d["id"], d["is_downloaded"], d["file_path"]) for d in db.get_downloaded_tracks()])
db.close()
print("tmpdir:", tmp)
