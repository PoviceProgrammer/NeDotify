"""WN-12 probe 1: does the dup-cleanup restore path work when the merged
duplicate had a non-NULL file_path? (tracks.file_path is UNIQUE)"""
import os, sys, sqlite3, tempfile, json, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.INFO)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
path = os.path.join(tmp, "a.db")

# --- build a pre-migration library with two identical local rows (same file_path)
db = DatabaseManager(path)
cur = db.conn.cursor()
for _ in range(2):
    cur.execute(
        "INSERT INTO tracks (title, artist, album, source, source_id, file_path) "
        "VALUES ('Song','Artist','Album','local',NULL,?)",
        (os.path.join(tmp, "song.mp3"),),
    )
cur.execute("INSERT INTO playlists (name) VALUES ('Mix')")
cur.execute("INSERT INTO history (track_id, played_at) VALUES (2, CURRENT_TIMESTAMP)")
cur.execute("INSERT INTO playlist_tracks (playlist_id, track_id) VALUES (1, 2)")
cur.execute("DELETE FROM schema_migrations")
cur.execute("DELETE FROM settings WHERE key = ?", (DatabaseManager.LEGACY_DUP_CLEANUP_FLAG,))
db.conn.commit()
print("BEFORE tracks:", [dict(r) for r in cur.execute("SELECT id,title,file_path,play_count FROM tracks")])
db.close()

# --- run the migration
db = DatabaseManager(path)
print("AFTER  tracks:", [dict(r) for r in db.conn.execute("SELECT id,title,file_path,play_count FROM tracks")])
print("merges:", [dict(r) for r in db.conn.execute("SELECT * FROM track_merges")])
print("backup rows:", [dict(r) for r in db.conn.execute("SELECT id,title,file_path FROM tracks_backup")])
dup_id = db.conn.execute("SELECT duplicate_id FROM track_merges").fetchone()[0]
db.close()

# --- pretend an older merge version and re-run the corrective step
db = DatabaseManager(path)
db.conn.execute("UPDATE track_merges SET merged_by = 'dup_cleanup_v1'")
db.conn.execute("DELETE FROM schema_migrations WHERE version = ?",
                (DatabaseManager.DUP_CLEANUP_RESTORE_VERSION,))
db.conn.commit()
db.close()

db = DatabaseManager(path)
restored = [dict(r) for r in db.conn.execute("SELECT id,title,file_path FROM tracks")]
hist = [dict(r) for r in db.conn.execute("SELECT id,track_id FROM history")]
pl = [dict(r) for r in db.conn.execute("SELECT id,playlist_id,track_id FROM playlist_tracks")]
print("RESTORED tracks:", restored)
print("RESTORED history:", hist)
print("RESTORED playlist_tracks:", pl)
print("RESTORE RESULT: duplicate_id=%s restored=%s" % (dup_id, any(r['id']==dup_id for r in restored)))
db.close()
print("TMPDIR", tmp)
