"""WX-10 reviewer-B: cost of the queue_updated event storm."""
import os, sys, types, threading, time, json

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)

from audio.queue import PlaybackQueue

def tracks(n):
    return [{"id": i, "title": f"Track {i}", "artist": f"Artist {i}",
             "album": "A", "duration": 210, "source": "youtube", "source_id": f"vid{i}",
             "cover_url": "http://127.0.0.1:8099/api/cover?x=1",
             "file_path": None, "stream_url": None, "is_favorite": False,
             "listening_session": "abcdef0123456789", "source_url": "https://www.youtube.com/watch?v=x",
             "type": "song"} for i in range(n)]

for n in (50, 200, 1000):
    q = PlaybackQueue()
    q.set_tracks(tracks(n), 0)
    t0 = time.perf_counter()
    payload = {"tracks": q.tracks, "current_index": q._current_index,
               "current_track": q.current_track, "shuffle": q.shuffle, "repeat": q.repeat}
    t1 = time.perf_counter()
    s = json.dumps(payload)
    t2 = time.perf_counter()
    print(f"queue of {n:5d} tracks: snapshot {1000*(t1-t0):7.2f} ms | json.dumps {1000*(t2-t1):7.2f} ms | {len(s)/1024:8.1f} KiB")
    print(f"   -> a 5-click burst emits 5-7 queue_updated events: "
          f"{5*len(s)/1024:.0f}-{7*len(s)/1024:.0f} KiB of JSON marshalled to the UI thread")
