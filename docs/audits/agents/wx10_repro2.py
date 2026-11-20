"""WX-10 reviewer-B: emit storm + double-resolution quantification."""
import os, sys, types, threading, time, json, random

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)

fake_tray = types.ModuleType("core.tray")
class _Tray:
    def __init__(self, api): self.api = api
    def update_state(self, **kw): pass
fake_tray.TrayIcon = _Tray
sys.modules["core.tray"] = fake_tray

from core.api import AppApi
from audio.engine import AudioEngine

EVENTS = []
class Db:
    def get_track(self, i): return None
    def get_cached_stream(self, s, sid, **kw): return None
    def get_downloaded_tracks(self): return []
    def update_track(self, i, **kw): pass
    def ensure_track_exists(self, t): return 1
class Settings:
    def get(self, c, k, d=None): return d
    def set(self, c, k, v): pass
class Proxy:
    port = 8099; token = "tok"
    def auth_query(self): return "&k=tok"
    def get_proxy_url(self, *a, **k): return "http://127.0.0.1:8099/api/stream?x=1"

def make_core():
    core = types.SimpleNamespace(db=Db(), settings=Settings(), engine=AudioEngine(),
                                 proxy=Proxy(), cache=None, youtube=None, soundcloud=None,
                                 yandex=None, discord_rpc=None, zapret=None)
    api = AppApi(core)
    api._emit = lambda name, data=None: EVENTS.append((name, data))
    return core, api

def hdr(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


# --------------------------------------------------------------------------- #
hdr("R5: _emit() from the UI thread spawns ONE THREAD PER EVENT (no queue)")
# --------------------------------------------------------------------------- #
core, api = make_core()

class FakeWindow:
    def __init__(self): self.calls = []
    def evaluate_js(self, code):
        time.sleep(random.uniform(0.001, 0.02))   # simulate Control.Invoke latency
        self.calls.append(code)

api._window = FakeWindow()
base = threading.active_count()
for i in range(50):
    api._emit("track_changed", {"i": i})
peak = threading.active_count()
print("threads before / peak during 50 emits :", base, "/", peak)
print(">>> one OS thread per event:", "YES" if peak - base > 10 else "NO")


# --------------------------------------------------------------------------- #
hdr("R6: ONE user click (play_track with a list) starts TWO resolution chains")
# --------------------------------------------------------------------------- #
core, api = make_core()
started = []
def fake_re_resolve(source, source_id, callback=None, on_error=None, quality="high", track=None):
    started.append((source, source_id))
    def later():
        time.sleep(0.05)
        if callback: callback(f"http://cdn/{source_id}.mp3", {})
    threading.Thread(target=later, daemon=True).start()
core.re_resolve_stream_url_async = fake_re_resolve

track = {"id": 1, "title": "T1", "artist": "A", "source": "youtube", "source_id": "v1"}
api.play_track(track, [dict(track)], 0)
time.sleep(0.2)
print("after ONE play_track(track, list):   resolution chains =", len(started), started)

# now simulate the frontend reacting to the track_changed event that carries no
# stream_url: player.js:1695-1705 calls play_track(pendingTrack) WITHOUT the list.
EVENTS.clear()
pending = {k: v for k, v in track.items() if k not in ("file_path", "stream_url")}
api.play_track(pending)          # <- the frontend's automatic re-request
time.sleep(0.2)
print("after the frontend's automatic re-request: chains =", len(started), started)
print(">>> duplicate resolution for one click:", "YES" if len(started) == 2 else "NO")


# --------------------------------------------------------------------------- #
hdr("R7: 5 rapid clicks -> 5 abandoned resolutions, 0 cancelled")
# --------------------------------------------------------------------------- #
core, api = make_core()
started = []
cancelled = []
def fake_re_resolve2(source, source_id, callback=None, on_error=None, quality="high", track=None):
    started.append(source_id)
    def later():
        time.sleep(1.0)
        if callback: callback(f"http://cdn/{source_id}.mp3", {})
    threading.Thread(target=later, daemon=True).start()
core.re_resolve_stream_url_async = fake_re_resolve2

def click(i):
    t = {"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}
    api.play_track(t, [dict(t)], 0)

ts = [threading.Thread(target=click, args=(i,)) for i in range(5)]
for t in ts: t.start()
for t in ts: t.join(10)
time.sleep(1.4)
print("resolutions started:", len(started), started)
print("resolutions cancelled:", len(cancelled))
print("track_changed events:", len([e for e in EVENTS if e[0] == 'track_changed']))
print("queue_updated events:", len([e for e in EVENTS if e[0] == 'queue_updated']))
print("total bridge events for 5 clicks:", len(EVENTS))
print("final queue current:", core.engine.queue.current_track["title"])
