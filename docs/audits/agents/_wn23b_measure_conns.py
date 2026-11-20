"""WN-23-B measurement: connection growth in core/database.py::_all_conns.

core/database.py keeps every connection it ever handed out in `self._all_conns`
(a strong set).  pywebview dispatches each js_api call on its own worker
thread, and DatabaseManager._get_connection() is thread-local, so a thread
per bridge call opens a NEW sqlite3 connection that is then strongly held by
_all_conns forever - even after that thread has exited.
"""
import sys, os, threading, tempfile, gc
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
os.chdir(r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn23b_")
db = DatabaseManager(os.path.join(tmp, "t.db"))
print(f"after init:            _all_conns = {len(db._all_conns)}")


def bridge_call():
    db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()


for i in range(1, 51):
    t = threading.Thread(target=bridge_call)
    t.start()
    t.join()
    if i in (1, 5, 10, 25, 50):
        print(f"after {i:3d} js_api-style calls: _all_conns = {len(db._all_conns)}")

gc.collect()
print(f"after gc.collect():     _all_conns = {len(db._all_conns)}")
print("=> the set keeps the closed-or-not connection objects alive; they are never"
      "\n   released by the thread that opened them.")

# Same, but with close_thread_connection() called by the worker thread.
def bridge_call_closing():
    db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()
    db.close_thread_connection()


for i in range(1, 51):
    t = threading.Thread(target=bridge_call_closing)
    t.start()
    t.join()
    if i in (1, 50):
        print(f"with close_thread_connection(): after {i:3d} calls: _all_conns = {len(db._all_conns)}")
