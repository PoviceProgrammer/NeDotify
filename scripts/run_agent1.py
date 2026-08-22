import os
import sys
import time
import json
import csv
import logging
from statistics import median

def agent1_driver(app_core, api):
    print("Agent 1 driver started.")
    from main import perf_mark
    
    platforms = [
        {"source": "youtube", "source_id": "jNQXAC9IVRw", "title": "Me at the zoo", "artist": "jawed"},
        {"source": "soundcloud", "source_url": "https://soundcloud.com/monstercat/pegboard-nerds-disconnected", "source_id": "https://soundcloud.com/monstercat/pegboard-nerds-disconnected", "title": "Disconnected", "artist": "Pegboard Nerds"},
        {"source": "spotify", "source_id": "4cOdK2wGLETKBW3PvgPWqT", "title": "Never Gonna Give You Up", "artist": "Rick Astley"}
    ]
    
    results = []
    
    def clear_caches(track):
        try:
            source = track.get("source")
            source_id = track.get("source_id")
            # DB cache
            if hasattr(app_core, 'db') and hasattr(app_core.db, 'execute'):
                app_core.db.execute("DELETE FROM stream_cache WHERE source=? AND source_id=?", (source, source_id))
            # File cache
            if hasattr(app_core, 'cache') and hasattr(app_core.cache, '_streams_dir'):
                streams_dir = app_core.cache._streams_dir
                import re
                safe_source = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source or 'unknown'))
                safe_source_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id or ''))
                cache_name = f"{safe_source}_{safe_source_id}"
                for ext in ("m4a", "webm", "mp3", "ogg"):
                    candidate = os.path.join(streams_dir, f"{cache_name}.{ext}")
                    if os.path.exists(candidate):
                        os.remove(candidate)
        except Exception as e:
            print(f"Failed to clear cache: {e}")

    log_path = os.path.join(os.path.expanduser('~'), '.nedotify', 'logs', 'perf.jsonl')
    
    def get_last_run_logs(start_ts):
        stages = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            if entry.get("ts", 0) > start_ts:
                                stages.append(entry)
                        except: pass
        return stages

    def wait_for_event(event_name, start_ts, timeout=20):
        start = time.time()
        while time.time() - start < timeout:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                entry = json.loads(line)
                                if entry.get("stage") == event_name and entry.get("ts", 0) > start_ts:
                                    return True
                            except: pass
            time.sleep(0.5)
        return False
        
    for p in platforms:
        for i in range(1, 7):
            for is_warm in [False, True]:
                run_type = "warm" if is_warm else "cold"
                if not is_warm:
                    clear_caches(p)
                    
                print(f"Testing {p['source']} - Run {i} - {run_type}")
                start_ts = time.perf_counter()
                
                track_copy = dict(p)
                # play track
                api.play_track(track_copy)
                
                # wait for audio_can_play
                wait_for_event("audio_can_play", start_ts, 15)
                time.sleep(0.5) # buffer
                
                stages = get_last_run_logs(start_ts)
                for s in stages:
                    if s.get("stage") in ["search_sent", "provider_resolved", "stream_url_ready", "proxy_first_byte", "audio_can_play", "audio_playing"]:
                        results.append({
                            "provider": p['source'],
                            "run": i,
                            "type": run_type,
                            "stage": s.get("stage"),
                            "timestamp": s.get("ts")
                        })
                
                # pause audio
                api.emit_event('state_changed', {'state': 'paused'})

    # Write results
    import csv
    for provider in ["youtube", "soundcloud", "spotify"]:
        with open(f"benchmarks/track_load_{provider}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["run", "type", "stage", "timestamp"])
            for r in results:
                if r["provider"] == provider:
                    writer.writerow([r["run"], r["type"], r["stage"], r["timestamp"]])
                    
    print("Agent 1 driver finished. Exiting...")
    api.close_window()
    os._exit(0)

if __name__ == "__main__":
    import subprocess
    env = os.environ.copy()
    env["NEDOTIFY_PERF_DEBUG"] = "1"
    env["NEDOTIFY_AGENT1_TEST"] = "1"
    # delete log
    log_path = os.path.join(os.path.expanduser('~'), '.nedotify', 'logs', 'perf.jsonl')
    try: os.remove(log_path)
    except: pass
    
    print("Launching app for Agent 1 tests...")
    subprocess.run([sys.executable, "-u", "main.py"], env=env)
    print("Agent 1 tests complete.")
