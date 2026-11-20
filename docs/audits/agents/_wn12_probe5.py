"""WN-12 probe 5: statement counts, bridge payload size, LIKE escaping."""
import os, sys, sqlite3, tempfile, json, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.ERROR)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
db = DatabaseManager(os.path.join(tmp, "i.db"))
c = db.conn

N = 4000
c.executemany("INSERT INTO tracks (title, artist, album, source, source_id, duration, added_at, metadata_json) "
              "VALUES (?,?,?,?,?,?,datetime('now'),?)",
              [(f"Title {i}", f"Artist {i}", f"Album {i}", "youtube", f"vid{i}", 200,
                json.dumps({"extra": "x"*200, "bpm": 120})) for i in range(N)])
c.executemany("INSERT INTO history (track_id, played_at, duration_listened) VALUES (?, datetime('now'), 60)",
              [(i % N + 1,) for i in range(N * 3)])
c.commit()

stmts = []
c.set_trace_callback(lambda s: stmts.append(" ".join(s.split())[:70]))
db.get_wrapped_stats("week")
c.set_trace_callback(None)
print("get_wrapped_stats -> %d statements" % len(stmts))
for s in stmts: print("   -", s)

stmts = []
c.set_trace_callback(lambda s: stmts.append(" ".join(s.split())[:70]))
db.get_history(50)
c.set_trace_callback(None)
print("get_history(50) -> %d statements:" % len(stmts), stmts)

rows = db.get_all_tracks()
payload = json.dumps(rows, ensure_ascii=False, default=str)
print("get_all_tracks(): rows=%d  json bytes=%d (%.1f MB)" % (len(rows), len(payload), len(payload)/1048576))

# --- LIKE escaping behaviour
c.execute("INSERT INTO tracks (title, artist, album, source) VALUES ('100% Pure', 'AC_DC', 'a_b', 'local')")
c.execute("INSERT INTO tracks (title, artist, album, source) VALUES ('ACDC', 'ACDC', 'x', 'local')")
c.commit()
print("search '%'      ->", [r['title'] for r in db.search_tracks("%")])
print("search 'AC_DC'  ->", [r['title'] for r in db.search_tracks("AC_DC")])
print("search 'a_b'    ->", [r['title'] for r in db.search_tracks("a_b")])
print("search '100%'   ->", [r['title'] for r in db.search_tracks("100%")])
print("search '\\\\'     ->", [r['title'] for r in db.search_tracks("\\")])

# --- order_by whitelist
print("order_by injection attempt ->", len(db.get_all_tracks(order_by="added_at DESC; DROP TABLE tracks --")), "rows; table alive:",
      c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0])
