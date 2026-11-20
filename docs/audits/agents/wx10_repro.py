"""WX-10 reviewer-B reproductions (read-only against the repo)."""
import os, sys, types, threading, time, json

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)

# --- stub the tray so AppApi.__init__ does not create a pystray icon ---
fake_tray = types.ModuleType("core.tray")
class _Tray:
    def __init__(self, api): self.api = api
    def update_state(self, **kw): pass
fake_tray.TrayIcon = _Tray
sys.modules["core.tray"] = fake_tray

from core.api import AppApi
from audio.engine import AudioEngine
from audio.queue import PlaybackQueue

EVENTS = []

class Db:
    def get_track(self, i): return None
    def get_cached_stream(self, s, sid, **kw): return None
    def get_downloaded_tracks(self): return []
    def update_track(self, i, **kw): pass
    def ensure_track_exists(self, t): return 1
    def get_track_by_path(self, p): return None
    def get_track_by_source_id(self, s, sid): return None

class Settings:
    def get(self, c, k, d=None): return d
    def set(self, c, k, v): pass

class Proxy:
    port = 8099
    token = "tok"
    def auth_query(self): return "&k=tok"
    def get_proxy_url(self, *a, **k): return "http://127.0.0.1:8099/api/stream?x=1"

def make_core():
    core = types.SimpleNamespace(
        db=Db(), settings=Settings(), engine=AudioEngine(), proxy=Proxy(),
        cache=None, youtube=None, soundcloud=None, yandex=None,
        discord_rpc=None, zapret=None,
    )
    api = AppApi(core)
    api._emit = lambda name, data=None: EVENTS.append((name, data))
    return core, api


def hdr(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


# --------------------------------------------------------------------------- #
hdr("R1: AudioEngine.next_track() returns track X but emits track Y")
# --------------------------------------------------------------------------- #
from audio.engine import AudioEngine

class GateEngine(AudioEngine):
    """Blocks inside _notify_track_changed so a second next_track() can run."""
    def __init__(self):
        super().__init__()
        self.gate = threading.Event()
    def _notify_track_changed(self):
        self.gate.wait(5)
        super()._notify_track_changed()

eng = GateEngine()
emitted = []
eng._on_track_changed = lambda t: emitted.append(t)
eng.queue.set_tracks([{"title": "T0"}, {"title": "T1"}, {"title": "T2"}], 0)

res = {}
def t1():
    res["returned"] = eng.next_track()
th = threading.Thread(target=t1); th.start()
time.sleep(0.3)                 # thread 1 has advanced the queue to index 1
adv = eng.queue.next_track()   # a concurrent "next" from another bridge thread
eng.gate.set()                 # release thread 1
th.join(5)
print("queue.current_track after both calls :", eng.queue.current_track["title"])
print("next_track() RETURNED                :", res["returned"]["title"])
print("track_changed EMITTED                :", [e["title"] for e in emitted])
print(">>> divergence:",
      "YES" if res["returned"]["title"] != emitted[-1]["title"] else "no")


# --------------------------------------------------------------------------- #
hdr("R2: play_track() re-shuffles the queue and wipes the back-history")
# --------------------------------------------------------------------------- #
core, api = make_core()
core.engine.queue.set_tracks(
    [{"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}
     for i in range(5)], 0)
core.engine.queue.shuffle = True
before = [t["title"] for t in core.engine.queue.tracks]
hist_before = len(core.engine.queue._history_stack)

list_in = [{"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}
           for i in range(5)]
core.engine.queue.add_track({"id": 99, "title": "EXTRA", "artist": "A",
                              "source": "youtube", "source_id": "v99"})
extra_before = [t["title"] for t in core.engine.queue.tracks]

# simulate what AppApi.play_track(track, track_list, index) does:
core.engine.play_queue(list_in, 2)
after = [t["title"] for t in core.engine.queue.tracks]
print("queue BEFORE play_queue (with shuffle on):", extra_before)
print("queue AFTER  play_queue(list, 2)          :", after)
print("history stack before/after                :", hist_before, "/", len(core.engine.queue._history_stack))
print(">>> re-shuffled + history wiped:",
      "YES" if after[0] == "T2" and after[1:] != before[1:] else "check")


# --------------------------------------------------------------------------- #
hdr("R3: next play_track() DISCARDS backend-side queue mutations")
# --------------------------------------------------------------------------- #
core, api = make_core()
core.engine.queue.set_tracks(
    [{"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}
     for i in range(3)], 0)
api.add_to_queue({"id": 42, "title": "ADDED", "artist": "A",
                   "source": "youtube", "source_id": "v42"})
print("after add_to_queue          :", [t["title"] for t in core.engine.queue.tracks])
api.reorder_queue(0, 2)
print("after reorder_queue(0,2)    :", [t["title"] for t in core.engine.queue.tracks])
# the frontend now calls play_track(track, window.currentQueue, idx)
snapshot = [{"id": i, "title": f"T{i}", "artist": "A", "source": "youtube", "source_id": f"v{i}"}
            for i in range(3)]          # <- stale frontend snapshot (no ADDED)
core.engine.play_queue(snapshot, 0)
print("after play_queue(snapshot)   :", [t["title"] for t in core.engine.queue.tracks])
print(">>> backend-side add/reorder silently lost:",
      "YES" if "ADDED" not in [t["title"] for t in core.engine.queue.tracks] else "no")


# --------------------------------------------------------------------------- #
hdr("R4: 5 rapid play_track() calls -> how many resolution chains?")
# --------------------------------------------------------------------------- #
core, api = make_core()
started = []
lock = threading.Lock()
def fake_re_resolve(source, source_id, callback=None, on_error=None, quality="high", track=None):
    with lock:
        started.append((source, source_id))
    # emulate a provider that takes a while and never gets cancelled
    def later():
        time.sleep(0.5)
        if callback: callback(f"http://cdn/{source_id}.mp3", {})
    threading.Thread(target=later, daemon=True).start()
core.re_resolve_stream_url_async = fake_re_resolve

def click(i):
    api.play_track({"id": i, "title": f"T{i}", "artist": "A",
                    "source": "youtube", "source_id": f"v{i}"},
                   [{"id": i, "title": f"T{i}", "artist": "A",
                     "source": "youtube", "source_id": f"v{i}"}], 0)

before_threads = threading.active_count()
ts = [threading.Thread(target=click, args=(i,)) for i in range(5)]
for t in ts: t.start()
for t in ts: t.join(10)
time.sleep(0.8)
print("resolution chains started    :", len(started), started)
print("threads alive before/after   :", before_threads, "/", threading.active_count())
print("track_changed events emitted :", len([e for e in EVENTS if e[0] == 'track_changed']))
print("queue_updated events emitted :", len([e for e in EVENTS if e[0] == 'queue_updated']))
print("final queue current track    :", core.engine.queue.current_track["title"])
