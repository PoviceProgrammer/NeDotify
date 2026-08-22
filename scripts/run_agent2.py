import os
import sys
import time
import json
import subprocess
import csv
from statistics import median
import ctypes

def get_perf_log_path():
    return os.path.join(os.path.expanduser('~'), '.nedotify', 'logs', 'perf.jsonl')

def clear_perf_log():
    try:
        os.remove(get_perf_log_path())
    except FileNotFoundError:
        pass

def run_startup_test(run_id, use_cprofile=False):
    clear_perf_log()
    env = os.environ.copy()
    env["NEDOTIFY_PERF_DEBUG"] = "1"
    
    cmd = [sys.executable, "main.py"]
    if use_cprofile:
        cmd = [sys.executable, "-m", "cProfile", "-o", "benchmarks/startup.prof", "main.py"]
        
    print(f"Running iteration {run_id}...")
    p = subprocess.Popen(cmd, env=env)
    
    # Wait for js_boot_done
    start_time = time.time()
    boot_done = False
    
    while time.time() - start_time < 30:
        if os.path.exists(get_perf_log_path()):
            with open(get_perf_log_path(), 'r', encoding='utf-8') as f:
                content = f.read()
                if "js_boot_done" in content:
                    boot_done = True
                    break
        time.sleep(0.5)
        
    if boot_done:
        # Give it a second to render
        time.sleep(1)
        # Simulate click in the center of the screen
        try:
            screen_width = ctypes.windll.user32.GetSystemMetrics(0)
            screen_height = ctypes.windll.user32.GetSystemMetrics(1)
            ctypes.windll.user32.SetCursorPos(screen_width // 2, screen_height // 2)
            # MOUSEEVENTF_LEFTDOWN = 0x0002, MOUSEEVENTF_LEFTUP = 0x0004
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        except Exception as e:
            print(f"Failed to click: {e}")
            
        time.sleep(1) # wait for first_interactive log
        
    # Terminate gracefully if possible, or kill
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        
    # Read the log
    stages = []
    if os.path.exists(get_perf_log_path()):
        with open(get_perf_log_path(), 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        stages.append(entry)
                    except Exception:
                        pass
    return stages

def main():
    results = []
    
    # Warmup
    print("Running warmup...")
    run_startup_test("warmup")
    
    # Real runs
    for i in range(1, 6):
        stages = run_startup_test(i)
        for s in stages:
            s['run'] = i
        results.extend(stages)
        
    # Run 6 with cProfile
    print("Running cProfile run...")
    cprof_stages = run_startup_test(6, use_cprofile=True)
    
    # Write to CSV
    with open("benchmarks/startup_timeline.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "stage", "timestamp"])
        for r in results:
            writer.writerow([r.get("run"), r.get("stage"), r.get("ts")])
            
    print("Agent 2 done.")

if __name__ == "__main__":
    main()
