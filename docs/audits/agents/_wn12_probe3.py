"""WN-12 probe 3: query plans, FTS trigger side effects, WAL leftovers."""
import os, sys, sqlite3, tempfile, threading, time, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.ERROR)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
path = os.path.join(tmp, "f.db")
db = DatabaseManager(path)
c = db.conn

# --- populate
N = 3000
c.executemany("INSERT INTO tracks (title, artist, album, source, source_id, duration, added_at) "
              "VALUES (?,?,?,?,?,?,datetime('now', ?))",
              [(f"Title{i}", f"Artist{i%50}", f"Album{i%20}", "youtube", f"v{i}", 100 + i,
                f"-{i%400} days") for i in range(N)])
c.executemany("INSERT INTO history (track_id, played_at, duration_listened) VALUES (?, datetime('now', ?), 60)",
              [(i % N + 1, f"-{i%400} days") for i in range(N * 2)])
c.execute("INSERT INTO playlists (name) VALUES ('P')")
c.executemany("INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (1, ?, ?)",
              [(i % N + 1, i % N + 1) for i in range(N)])
c.commit()

def plan(sql, params=()):
    print("SQL:", " ".join(sql.split())[:110])
    for r in c.execute("EXPLAIN QUERY PLAN " + sql, params):
        print("   ->", r["detail"])
    print()

plan("SELECT * FROM tracks WHERE LOWER(album) = LOWER(?)", ("Album3",))
plan("SELECT * FROM tracks WHERE play_count > 0 ORDER BY play_count DESC, last_played DESC LIMIT 10")
plan("SELECT * FROM tracks ORDER BY added_at DESC LIMIT 10")
plan("SELECT * FROM tracks WHERE source = ? AND source_id = ?", ("youtube", "v5"))
plan("SELECT * FROM tracks WHERE file_path = ?", ("x",))
plan("SELECT * FROM tracks WHERE is_favorite = 1 ORDER BY added_at DESC")
plan("""SELECT t.id AS track_id, MAX(h.played_at) AS played_at, COUNT(*) AS play_count
         FROM history h JOIN tracks t ON h.track_id = t.id GROUP BY t.id ORDER BY played_at DESC LIMIT 50""")
plan("""SELECT artist, COUNT(*), SUM(play_count) FROM tracks WHERE artist != 'Unknown Artist'
         GROUP BY artist ORDER BY 2 DESC LIMIT 10""")
plan("""SELECT id, source, source_id FROM tracks
         WHERE ((cover_path IS NULL AND (cover_url IS NULL OR cover_url='')) OR title IN ('Unknown Title'))
         AND source != 'local' AND source_id != '' ORDER BY id DESC LIMIT 40""")
plan("SELECT * FROM tracks WHERE title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\' ORDER BY play_count DESC LIMIT 50",
     ("%a%", "%a%", "%a%"))
plan("SELECT COUNT(*) FROM tracks WHERE source = ?", ("youtube",))
plan("SELECT p.*, COUNT(pt.track_id) FROM playlists p LEFT JOIN playlist_tracks pt ON p.id=pt.playlist_id GROUP BY p.id ORDER BY p.updated_at DESC")

# --- FTS trigger side effect: does a play_count bump rewrite the FTS row?
before = c.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]
trg = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='tracks_au'").fetchone()[0]
print("fts rows:", before, "tracks_au trigger present:", trg)
c.execute("UPDATE tracks SET play_count = play_count + 1, last_played = CURRENT_TIMESTAMP WHERE id = 1")
after = c.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]
print("fts rows after a play_count bump:", after)

# --- timing of the hot reads
def timed(label, fn, n=5):
    t0 = time.perf_counter()
    for _ in range(n):
        r = fn()
    dt = (time.perf_counter() - t0) / n
    size = len(r) if hasattr(r, "__len__") else "-"
    print(f"{label:34s} {dt*1000:8.2f} ms  rows={size}")

timed("get_all_tracks() [no limit]", lambda: db.get_all_tracks())
timed("get_all_tracks(source='youtube')", lambda: db.get_all_tracks(source="youtube"))
timed("get_history(50)", lambda: db.get_history(50))
timed("get_wrapped_stats('week')", lambda: db.get_wrapped_stats("week"))
timed("get_top_artists(10)", lambda: db.get_top_artists(10))
timed("get_album_tracks('Album3')", lambda: db.get_album_tracks("Album3"))
timed("search_tracks('Title1')", lambda: db.search_tracks("Title1"))
timed("search_tracks('zzz-no-match')", lambda: db.search_tracks("zzz-no-match"))
timed("get_playlist_tracks(1)", lambda: db.get_playlist_tracks(1))
timed("get_tracks_missing_cover(40)", lambda: db.get_tracks_missing_cover(40))

db.close()
print("TMP:", tmp)
