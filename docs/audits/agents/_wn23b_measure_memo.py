"""WN-23-B measurement: the 60 s taste-profile memo vs thread-local connections.

core/database.py hands every thread its own sqlite3.Connection (threading.local).
services/taste_profile.py builds its memo revision key from (conn, total_changes,
data_version, schema_version).  Because `conn` is part of the key, a profile built
on thread A can never be reused on thread B.
"""
import sys, os, time, threading, tempfile
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
os.chdir(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from core.database import DatabaseManager
from services.taste_profile import UserTasteProfile, _profile_cache

tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "t.db"))

# Seed some listening history.
for i in range(40):
    tid = db.add_track(f"Song {i}", artist=f"Artist {i % 5}", source="youtube",
                       source_id=f"s{i}", duration=200)
    db.add_to_history(tid, duration_listened=200, completed=True)

def count_selects(conn):
    stmts = []
    conn.set_trace_callback(stmts.append)
    try:
        p = UserTasteProfile().build_from_db(db)
    finally:
        conn.set_trace_callback(None)
    return p, sum(1 for s in stmts if s.lstrip().upper().startswith("SELECT"))


print("=== same thread (bridge thread) ===")
p1, n1 = count_selects(db.conn)
print(f"  build #1 SELECTs = {n1}")
p2, n2 = count_selects(db.conn)
print(f"  build #2 SELECTs = {n2}   (memo hit -> 0 expected)")

print()
print("=== other thread (worker thread) ===")
res = {}
def worker():
    res["p"], res["n"] = count_selects(db.conn)
t = threading.Thread(target=worker); t.start(); t.join()
print(f"  build on worker thread SELECTs = {res['n']}   (memo MISS -> full re-query expected)")

print()
print("=== second build on the SAME worker thread ===")
def worker2():
    res["p2"], res["n2"] = count_selects(db.conn)
t = threading.Thread(target=worker2); t.start(); t.join()
print(f"  build #2 on worker thread SELECTs = {res['n2']}  (memo hit within the thread)")

print()
print(f"memo entries alive: {len(_profile_cache)}")
print("revision tuple contains the connection object:",
      "conn" in UserTasteProfile._connection_revision(db.conn))

print()
print("=== rebuild cost with a large history ===")
for n_hist in (200, 2000, 8000):
    db2 = DatabaseManager(os.path.join(tmp, f"t{n_hist}.db"))
    ids = [db2.add_track(f"T{i}", artist=f"A{i%50}", source="youtube", source_id=f"x{i}", duration=200)
           for i in range(300)]
    for i in range(n_hist):
        db2.add_to_history(ids[i % 300], duration_listened=180, completed=True)
    t0 = time.perf_counter()
    UserTasteProfile().build_from_db(db2)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  history rows={n_hist:5d} -> cold profile build {dt:8.1f} ms")
    db2.close()

db.close()
