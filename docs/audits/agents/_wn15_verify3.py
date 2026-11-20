"""WN-15 verification part 3: is_offline() with the real SettingsManager."""
import os
import sys
import tempfile

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

from core.database import DatabaseManager
from core.settings import SettingsManager
from core.offline import is_offline

tmp = tempfile.mkdtemp(prefix="wn15s_")
db = DatabaseManager(db_path=os.path.join(tmp, "t.db"))
s = SettingsManager(db)

print("default                :", is_offline(s))
s.set("network", "offline_mode", True)
print("after set(True)        :", is_offline(s))
s.set("network", "offline_mode", "true")
print("after set('true')      :", is_offline(s))
s.set("network", "offline_mode", "1")
print("after set('1')         :", is_offline(s), " <- string '1' is NOT treated as ON")
s.set("network", "offline_mode", 1)
print("after set(1)           :", is_offline(s))
s.set("network", "offline_mode", False)
print("after set(False)       :", is_offline(s))
print("raw settings value     :", repr(s.get("network", "offline_mode", False)))

print()
print("--- round trip through the DB (flush + reload) ---")
s.set("network", "offline_mode", True)
s.sync_flush_now()
s2 = SettingsManager(db)
print("after reload           :", is_offline(s2))

print()
print("--- what the bridge stores (api.save_setting path) ---")
db2 = DatabaseManager(db_path=os.path.join(tmp, "u.db"))
s3 = SettingsManager(db2)
for v in (True, False, "true", "1", 1):
    s3.set("network", "offline_mode", v)
    print(f"set {v!r:>8} -> is_offline={is_offline(s3)}  raw={s3.get('network','offline_mode',False)!r}")
