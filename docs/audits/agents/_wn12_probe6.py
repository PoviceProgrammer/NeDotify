"""WN-12 probe 6: in-memory DB across threads, download_queue FK, orphan rows."""
import os, sys, sqlite3, tempfile, threading, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.ERROR)
from core.database import DatabaseManager

print("--- ':memory:' across threads")
db = DatabaseManager(":memory:")
db.conn.execute("INSERT INTO tracks (title, artist) VALUES ('Main','OnlyInMain')")
db.conn.commit()
box = {}
def worker():
    try:
        box["count"] = db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    except Exception as e:
        box["err"] = repr(e)
t = threading.Thread(target=worker); t.start(); t.join()
print("  main thread sees:", db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0])
print("  worker thread sees:", box)

print("--- download_queue has no FK to tracks")
tmp = tempfile.mkdtemp(prefix="wn12_")
db2 = DatabaseManager(os.path.join(tmp, "j.db"))
fk = [r["name"] for r in db2.conn.execute("PRAGMA foreign_key_list(download_queue)")]
print("  foreign keys on download_queue:", fk)
db2.conn.execute("INSERT INTO tracks (title, artist) VALUES ('T','A')")
db2.conn.execute("INSERT INTO download_queue (track_id, source, source_id) VALUES (1,'youtube','v1')")
db2.conn.commit()
db2.delete_track(1)
db2.conn.commit()
print("  after delete_track(1) -> download_queue rows:",
      [dict(r) for r in db2.conn.execute("SELECT * FROM download_queue")])
print("  history rows:", db2.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])

print("--- tracks deleted while a stream_cache row still points at them")
db2.conn.execute("INSERT INTO stream_cache (source, source_id, stream_url, cached_file_path) "
                 "VALUES ('youtube','v1','http://x','C:/tmp/x.mp3')")
db2.conn.commit()
print("  stream_cache rows:", [dict(r) for r in db2.conn.execute("SELECT source,source_id,cached_file_path FROM stream_cache")])

print("--- delete_track does not remove the file or the cover file")
db3 = DatabaseManager(os.path.join(tmp, "k.db"))
tid = db3.add_track(title="T", artist="A", file_path=os.path.join(tmp, "song.mp3"),
                    cover_path=os.path.join(tmp, "cover.jpg"))
db3.conn.execute("INSERT INTO history (track_id) VALUES (?)", (tid,))
db3.conn.commit()
db3.delete_track(tid)
print("  history after delete:", db3.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
print("  file still on disk:", os.path.exists(os.path.join(tmp, "song.mp3")))
