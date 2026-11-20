"""WN-12 probe 2: runtime behaviour checks (thread-local conns, WAL, FK,
system-playlist cleanup, N+1, isolation level)."""
import os, sys, sqlite3, tempfile, threading, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.WARNING)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
path = os.path.join(tmp, "b.db")
db = DatabaseManager(path)

print("--- pragmas on the main connection")
c = db.conn
print("journal_mode :", c.execute("PRAGMA journal_mode").fetchone()[0])
print("foreign_keys :", c.execute("PRAGMA foreign_keys").fetchone()[0])
print("busy_timeout :", c.execute("PRAGMA busy_timeout").fetchone()[0])
print("isolation_level:", repr(c.isolation_level), "autocommit:", c.autocommit)

print("--- closing a foreign-thread connection from the main thread")
box = {}
def worker():
    box["conn"] = db.conn
    box["tid"] = threading.get_ident()
th = threading.Thread(target=worker); th.start(); th.join()
try:
    box["conn"].close()
    print("  close() from another thread: NO ERROR")
except Exception as e:
    print("  close() from another thread ->", type(e).__name__, e)

print("--- can we set WAL from a second connection while another is open?")
print("  db.close() ->")
db.close()
print("  after close, conn property reopens:", db.conn.execute("SELECT 1").fetchone()[0])
db.close()
print("  close() twice: OK")

print("--- FK enforcement: insert history for a non-existent track")
db2 = DatabaseManager(os.path.join(tmp, "c.db"))
try:
    db2.conn.execute("INSERT INTO history (track_id) VALUES (9999)")
    print("  orphan history row ACCEPTED (FK not enforced)")
except Exception as e:
    print("  orphan history row ->", type(e).__name__, e)

print("--- system playlist cleanup: does it eat a USER playlist named 'Локальные'?")
db2.conn.execute("INSERT INTO playlists (name) VALUES ('Локальные')")   # id 1
db2.conn.execute("INSERT INTO playlists (name) VALUES ('Локальные')")   # id 2  <- user's
db2.conn.execute("INSERT INTO playlists (name) VALUES ('Моя подборка')")  # id 3 <- user's, empty
db2.conn.commit()
print("  before:", [dict(r) for r in db2.conn.execute("SELECT id,name FROM playlists")])
db2.create_playlist("Новый плейлист")     # any creation triggers the cleanup
print("  after :", [dict(r) for r in db2.conn.execute("SELECT id,name FROM playlists")])

print("--- N+1 in search_playlists")
db3 = DatabaseManager(os.path.join(tmp, "d.db"))
for i in range(6):
    db3.conn.execute("INSERT INTO playlists (name) VALUES (?)", (f"P{i}",))
db3.conn.commit()
calls = []
orig = db3.get_playlist_track_count
def counting(pid):
    calls.append(pid)
    return orig(pid)
db3.get_playlist_track_count = counting
db3.search_playlists("P", limit=50)
print("  playlists returned, extra count queries issued:", len(calls), calls)

print("--- get_wrapped_stats: number of statements executed")
db4 = DatabaseManager(os.path.join(tmp, "e.db"))
db4.conn.execute("INSERT INTO tracks (title, artist, duration) VALUES ('T','A',100)")
db4.conn.execute("INSERT INTO history (track_id, duration_listened) VALUES (1, 50)")
db4.conn.commit()
stmts = []
class Spy:
    def __init__(self, c): self._c = c
    def execute(self, sql, *a, **k):
        stmts.append(" ".join(sql.split())[:60])
        return self._c.execute(sql, *a, **k)
    def __getattr__(self, n): return getattr(self._c, n)
db4.conn.execute = Spy(db4.conn)
db4.get_wrapped_stats("week")
db4.conn.execute = db4.conn.__class__.execute.__get__(db4.conn)
print("  statements:", len(stmts))
for s in stmts: print("   -", s)
