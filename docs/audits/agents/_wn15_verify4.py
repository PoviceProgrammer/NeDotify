"""WN-15 verification part 4: O6 (missing file) and F-9 (metadata wipe)."""
import os
import sys
import tempfile

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from core.database import DatabaseManager
from core.offline import available_track, available_tracks
from core.resolver import StreamResolver

tmp = tempfile.mkdtemp(prefix="wn15b_")
db = DatabaseManager(db_path=os.path.join(tmp, "t.db"))
audio = os.path.join(tmp, "song.mp3")
with open(audio, "wb") as fh:
    fh.write(b"x" * 5000)

tid = db.add_track("Song", "Artist", source="youtube", source_id="vid1", file_path=audio)
thin = {"id": tid, "source": "youtube", "source_id": "vid1"}

print("=" * 70)
print("O6: a track whose file was deleted -> not offered offline")
print("=" * 70)
os.remove(audio)
print("available_track  ->", available_track(db, thin))
print("available_tracks ->", available_tracks(db, [thin]))
print("=> missing files are filtered out:",
      available_track(db, thin) is None and available_tracks(db, [thin]) == [])

print()
print("=" * 70)
print("F-9: resolver.refresh() wipes the row metadata")
print("=" * 70)
db2 = DatabaseManager(db_path=os.path.join(tmp, "u.db"))
db2.cache_stream("youtube", "v1", "https://cdn.example/a.mp3",
                  title="Real Title", artist="Real Artist",
                  cover_url="https://cdn.example/c.jpg", duration=180)
row = db2.get_cached_stream("youtube", "v1")
print("before refresh:", {k: row[k] for k in ("stream_url", "title", "artist", "cover_url", "duration")})

r = StreamResolver(db=db2)
r.refresh("youtube", "v1", "https://cdn.example/b.mp3")
row = db2.get_cached_stream("youtube", "v1")
print("after  refresh:", {k: row[k] for k in ("stream_url", "title", "artist", "cover_url", "duration")})
print("=> metadata wiped by cache_stream():",
      row["title"] == "" and row["artist"] == "" and row["duration"] == 0)
print("=> cached_file_path untouched:", row["cached_file_path"])

print()
print("=" * 70)
print("F-4: recover_stream stores a foreign-provider URL under the original key")
print("=" * 70)
from core.playback_recovery import recover_stream
from types import SimpleNamespace

db3 = DatabaseManager(db_path=os.path.join(tmp, "w.db"))
resolver = StreamResolver(db=db3)


def provider(url=None, candidates=(), metadata=None):
    svc = SimpleNamespace()
    svc.get_stream_url = lambda target, callback, error_callback: callback(url, metadata or {})
    svc.search = lambda query, max_results, callback, error_callback: callback(list(candidates))
    return svc


wanted = {"title": "Song", "artist": "Artist", "source": "youtube",
          "source_id": "original", "duration": 180, "id": 7}
correct = {**wanted, "source": "soundcloud", "source_id": "right"}
core = SimpleNamespace(
    youtube=provider(), soundcloud=provider("https://cdn.example/right.mp3", candidates=[correct]),
    resolver=resolver, db=db3,
    settings=SimpleNamespace(get=lambda c, k, d=None: False),
    proxy=SimpleNamespace(get_proxy_url=lambda s, i, u, track_id=None: f"http://127.0.0.1:1/?url={u}"),
)
res = recover_stream(core, wanted, 5000)
print("response source/source_id:", res.get("source"), res.get("source_id"))
print("stream_url:", str(res.get("stream_url"))[:90])
row = db3.get_cached_stream("youtube", "original")
print("DB row for ('youtube','original') stream_url:", row and row.get("stream_url"))
print("=> a soundcloud URL stored under the youtube key:",
      bool(row) and "right.mp3" in (row.get("stream_url") or ""))
