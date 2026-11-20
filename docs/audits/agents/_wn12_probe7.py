"""WN-12 probe 7: do short-lived threads leak connections held in _all_conns?"""
import os, sys, sqlite3, tempfile, threading, gc, logging
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")
logging.basicConfig(level=logging.ERROR)
from core.database import DatabaseManager

tmp = tempfile.mkdtemp(prefix="wn12_")
path = os.path.join(tmp, "k.db")
db = DatabaseManager(path)
db.conn.execute("INSERT INTO tracks (title, artist) VALUES ('T','A')")
db.conn.commit()

def count_open_handles():
    n = 0
    try:
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        psapi = ctypes.WinDLL('psapi')
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        count = wintypes.DWORD()
        handles = (wintypes.HANDLE * 4096)()
        if not psapi.EnumProcessHandles(kernel32.GetCurrentProcess(), handles, 4096, ctypes.byref(count)):
            return -1
        for i in range(count.value):
            buf = ctypes.create_unicode_buffer(512)
            n = ctypes.wintypes.DWORD(0)
            if kernel32.GetFinalPathNameByHandleW(handles[i], buf, 512, 0) and path in buf.value:
                pass
            else:
                # cheap check by trying to read the handle name
                pass
        return count.value
    except Exception as e:
        return "n/a: %r" % (e,)

print("connections tracked before:", len(db._all_conns))
for i in range(50):
    t = threading.Thread(target=lambda: db.get_tracks_count())
    t.start(); t.join()
gc.collect()
print("connections tracked after 50 short-lived threads:", len(db._all_conns))
print("  (each dead thread's connection is still strongly referenced by _all_conns)")

# the same threads, but calling close_thread_connection first
for i in range(50):
    def w():
        db.get_tracks_count()
        db.close_thread_connection()
    t = threading.Thread(target=w); t.start(); t.join()
gc.collect()
print("connections tracked after 50 well-behaved threads:", len(db._all_conns))
print("TMP:", tmp)
