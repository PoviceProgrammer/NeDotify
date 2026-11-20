"""WX-10 reviewer-B: stale-resolution race -> the queue is replaced by the stale track."""
import os, sys, types, threading, time

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

core = types.SimpleNamespace(db=Db(), settings=Settings(), engine=AudioEngine(),
                             proxy=Proxy(), cache=None, youtube=None, soundcloud=None,
                             yandex=None, discord_rpc=None, zapret=None)
api = AppApi(core)
api._emit = lambda name, data=None: EVENTS.append((name, data))

pending_cbs = []
def fake_re_resolve(source, source_id, callback=None, on_error=None, quality="high", track=None):
    pending_cbs.append((source_id, callback))
core.re_resolve_stream_url_async = fake_re_resolve

def T(i):
    return {"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}

print("=" * 78)
print("SCENARIO: click A -> (frontend auto re-request) -> click B -> A's resolution lands")
print("=" * 78)

# 1) user clicks A in a list
list1 = [T(0), T(1), T(2)]
api.play_track(T(0), list1, 0)
print("after click A  -> queue:", [t["title"] for t in core.engine.queue.tracks],
      "current:", core.engine.queue.current_track["title"])
print("  resolution chains pending:", [s for s, _ in pending_cbs])

# 2) the user now clicks B (a different track) while A is still resolving
list2 = [T(0), T(1), T(2)]
api.play_track(T(1), list2, 1)
print("after click B  -> queue:", [t["title"] for t in core.engine.queue.tracks],
      "current:", core.engine.queue.current_track["title"])

# 3) the frontend reacts to track_changed(A) (no stream_url) and asks again,
#    WITHOUT the queue  -> player.js:1704  play_track(pendingTrack)
pendingA = {k: v for k, v in T(0).items() if k not in ("file_path", "stream_url")}
api.play_track(pendingA)
print("  resolution chains pending:", [s for s, _ in pending_cbs])

# 4) A's resolution finally lands (the stale one)
print("\n-- firing A's stale resolution --")
for sid, cb in pending_cbs:
    if sid == "v0":
        cb("http://cdn/v0.mp3", {})

print("FINAL queue       :", [t["title"] for t in core.engine.queue.tracks])
print("FINAL current     :", core.engine.queue.current_track["title"])
print("track_changed log :", [e[1]["title"] for e in EVENTS if e[0] == "track_changed"])
print()
print(">>> the user's selection B was replaced by the stale A:",
      "YES" if core.engine.queue.current_track["title"] == "T0" else "no")
print(">>> the whole queue was collapsed to a single track:",
      "YES" if len(core.engine.queue.tracks) == 1 else "no")
