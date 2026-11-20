"""WN-23-B measurement (v2): the 60 s taste-profile memo vs thread-local connections.

The memo revision key is (conn, total_changes, data_version, schema_version).
core/database.py gives every thread its own sqlite3.Connection (threading.local),
so the `conn` element can never match across threads.
"""
import sys, os, time, threading, tempfile
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
os.chdir(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from core.database import DatabaseManager
from services.taste_profile import UserTasteProfile, _profile_cache

tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "t.db"))
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


print("=== MAIN thread: two consecutive builds ===")
_, n1 = count_selects(db.conn)
_, n2 = count_selects(db.conn)
print(f"  build #1 SELECTs = {n1}")
print(f"  build #2 SELECTs = {n2}   <- memo hit")

print()
print("=== WORKER thread: two consecutive builds on the SAME worker thread ===")
out = {}
def worker():
    _, out["a"] = count_selects(db.conn)
    _, out["b"] = count_selects(db.conn)
    out["conn_id"] = id(db.conn)
t = threading.Thread(target=worker); t.start(); t.join()
print(f"  build #1 SELECTs = {out['a']}")
print(f"  build #2 SELECTs = {out['b']}   <- memo hit inside the thread")
print(f"  worker conn id = {out['conn_id']}, main conn id = {id(db.conn)}  (different objects)")

rev = UserTasteProfile._connection_revision(db.conn)
print()
print(f"revision tuple = {rev[:1]!r}...  -> element 0 is the Connection object: {rev[0] is db.conn}")

print()
print("=== 5 sequential bridge-style calls, alternating threads ===")
for i in range(5):
    r = {}
    th = threading.Thread(target=lambda r=r: r.update(n=count_selects(db.conn)[1]))
    th.start(); th.join()
    print(f"  call {i+1} on a fresh thread -> {r['n']} SELECTs")

print()
print(f"memo entries alive: {len(_profile_cache)}  (max is {UserTasteProfile._CACHE_MAX_ENTRIES})")
db.close()
