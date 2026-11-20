import os, sys, tempfile, threading, logging
sys.path.insert(0, os.getcwd())
logging.basicConfig(level=logging.DEBUG)
from utils.cache_manager import CacheManager, stream_cache_stem

tmp = tempfile.mkdtemp()

legacy_path = os.path.join(tmp, "legacy.mp3")
open(legacy_path, "wb").write(b"stale"*100)

TRACK_A = "ytsearch1: Сплин - Выхода нет"
from core.database import DatabaseManager
db = DatabaseManager(os.path.join(tmp, "test.db"))
db.set_cached_file("spotify", TRACK_A, legacy_path)
print("row before:", db.get_cached_stream("spotify", TRACK_A, max_age_seconds=2**31-1))

class DeferredExecutor:
    def __init__(self): self.tasks = []
    def submit(self, fn, *a, **k): self.tasks.append(lambda: fn(*a, **k))

cache = CacheManager(db)
cache._streams_dir = os.path.join(tmp, "streams")
cache._temp_dir = os.path.join(tmp, "temp")
os.makedirs(cache._streams_dir, exist_ok=True); os.makedirs(cache._temp_dir, exist_ok=True)
cache._active_downloads = set(); cache._active_downloads_lock = threading.Lock()
cache._executor = DeferredExecutor()
cache.purge_stream_cache = lambda: None
cache.mark_cache_dirty = lambda: None

sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from tests.audio_helpers import wave_bytes
class Response:
    headers = {"Content-Type": "audio/wav", "Content-Length": str(len(wave_bytes()))}
    def __init__(self): self.payload = wave_bytes()
    def read(self, count=-1):
        r, self.payload = self.payload[:count], self.payload[count:]
        return r
    def __enter__(self): return self
    def __exit__(self, *a): return False

import utils.url_safety as us
us.guarded_open_url = lambda *a, **k: Response()

cache.download_audio_stream("spotify", TRACK_A, "https://media.example/audio")
for t in cache._executor.tasks: t()
print("row after:", db.get_cached_stream("spotify", TRACK_A, max_age_seconds=2**31-1))
print("streams dir:", os.listdir(cache._streams_dir))
db.close()
