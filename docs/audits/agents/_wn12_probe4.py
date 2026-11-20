"""WN-12 probe 4: WAL lifecycle at shutdown, FTS trigger cost, checkpoint busy."""
import os, sys, sqlite3, tempfile, threading, time, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.ERROR)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
path = os.path.join(tmp, "g.db")
db = DatabaseManager(path)

# --- a worker thread keeps a connection open (exactly what the proxy /
# --- cache-cleanup / settings-writer threads do in the running app)
hold = threading.Event()
def worker():
    conn = db.conn
    hold.set()
    while True:
        time.sleep(0.05)
t = threading.Thread(target=worker, daemon=True); t.start(); hold.wait()

# --- the app writes a lot (history churn) from the main thread
c = db.conn
c.executemany("INSERT INTO tracks (title, artist, source) VALUES (?,?,?)",
              [(f"T{i}", "A", "youtube") for i in range(4000)])
c.commit()
for i in range(4000):
    c.execute("INSERT INTO history (track_id, duration_listened) VALUES (1, 10)")
c.commit()

print("wal size before close:", os.path.getsize(path + "-wal"))
print("checkpoint pragma result (busy, log, ckpt):",
      c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())

# --- simulate the app shutdown: db.close() from the main thread
db.close()
print("wal size after db.close():", os.path.getsize(path + "-wal"),
      "bytes (main db:", os.path.getsize(path), ")")
print("wal files present:", [f for f in os.listdir(tmp)])

# --- FTS trigger cost: every play rewrites the FTS row
db2 = DatabaseManager(os.path.join(tmp, "h.db"))
c2 = db2.conn
c2.executemany("INSERT INTO tracks (title, artist, album, genre) VALUES (?,?,?,?)",
               [(f"Title{i}", "Artist", "Album", "Rock") for i in range(3000)])
c2.commit()
def bench(label, fn, n):
    t0 = time.perf_counter()
    for _ in range(n): fn()
    dt = (time.perf_counter() - t0) / n
    print(f"{label:48s} {dt*1000:8.3f} ms")
bench("UPDATE tracks SET play_count=play_count+1 (FTS trigger ON)",
      lambda: c2.execute("UPDATE tracks SET play_count=play_count+1 WHERE id=1"), 300)
c2.execute("DROP TRIGGER IF EXISTS tracks_au")
c2.commit()
bench("same UPDATE with the FTS trigger dropped",
      lambda: c2.execute("UPDATE tracks SET play_count=play_count+1 WHERE id=1"), 300)
print("TMP:", tmp)
