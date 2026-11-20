"""WX-10 reviewer-B: _emit thread-per-event check (corrected)."""
import os, sys, types, threading, time, random

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)

fake_tray = types.ModuleType("core.tray")
class _Tray:
    def __init__(self, api): self.api = api
    def update_state(self, **kw): pass
fake_tray.TrayIcon = _Tray
sys.modules["core.tray"] = fake_tray

from core.api import AppApi, _MAIN_THREAD

core = types.SimpleNamespace(db=None, settings=None, engine=None, proxy=None)
api = AppApi(core)

class FakeWindow:
    def __init__(self): self.calls = []
    def evaluate_js(self, code):
        time.sleep(random.uniform(0.005, 0.03))   # simulate Control.Invoke latency
        self.calls.append(code)

api._window = FakeWindow()
print("main thread is _MAIN_THREAD:", threading.current_thread() is _MAIN_THREAD)

base = threading.active_count()
peak = base
stop = False
def sampler():
    global peak
    while not stop:
        peak = max(peak, threading.active_count())
        time.sleep(0.001)

s = threading.Thread(target=sampler); s.start()
for i in range(50):
    api._emit("track_changed", {"i": i})
stop = True; s.join()
print("threads before / peak during 50 emits :", base, "/", peak)
print(">>> one OS thread per event:", "YES" if peak - base > 10 else "NO")
print("evaluate_js calls:", len(api._window.calls))
