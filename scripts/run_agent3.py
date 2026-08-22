import os
import sys
import time
import json
import csv
import subprocess

def agent3_driver(app_core, api):
    print("Agent 3 driver started.")
    
    # 7 scenarios
    # 1. Idle (wait 5s, then measure 10s)
    # 2. Playback no-viz
    # 3. Playback w/ viz
    # 4. Scroll (trigger scroll in JS)
    # 5. Settings
    # 6. Blur (show background blur - UI overlay)
    # 7. Fullscreen bg-glow (particles + blur)
    
    results = []
    
    def measure(scenario_name, duration=10):
        print(f"Measuring {scenario_name}...")
        start = time.time()
        cpu_vals = []
        gpu_vals = []
        while time.time() - start < duration:
            try:
                cpu = subprocess.check_output(['powershell', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/cpu.ps1'], text=True).strip()
                if cpu: cpu_vals.append(float(cpu) / 12.0) # approx 12 cores
                
                gpu = subprocess.check_output(['powershell', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/gpu.ps1'], text=True).strip()
                if gpu: gpu_vals.append(float(gpu))
            except: pass
            time.sleep(1.0)
            
        c_med = sorted(cpu_vals)[len(cpu_vals)//2] if cpu_vals else 0
        g_med = sorted(gpu_vals)[len(gpu_vals)//2] if gpu_vals else 0
        
        results.append({
            "scenario": scenario_name,
            "cpu_median": c_med,
            "gpu_median": g_med
        })
        
    time.sleep(3)
    api.emit_event('state_changed', {'state': 'paused'})
    measure("Idle", 10)
    
    # Playback no-viz
    api.play_track({'source': 'youtube', 'source_id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'artist': 'Rick Astley'})
    time.sleep(5)
    measure("Playback no-viz", 10)
    
    # Playback w/ viz
    api._window.evaluate_js("if(window.toggleVisualizer) toggleVisualizer(true);")
    time.sleep(2)
    measure("Playback w/ viz", 10)
    
    # Scroll
    api._window.evaluate_js("window.scrollInterval = setInterval(() => { const el = document.querySelector('.feed-scroll'); if(el) el.scrollBy(0, 50); }, 50);")
    measure("Scroll", 10)
    api._window.evaluate_js("clearInterval(window.scrollInterval);")
    
    # Settings
    api._window.evaluate_js("if(window.showPage) window.showPage('settings');")
    time.sleep(2)
    measure("Settings", 10)
    
    # Blur
    api._window.evaluate_js("document.body.style.backdropFilter = 'blur(20px)';")
    measure("Blur", 10)
    
    # Fullscreen bg-glow
    api._window.evaluate_js("if(window.toggleFullscreen) toggleFullscreen();")
    time.sleep(2)
    measure("Fullscreen bg-glow", 10)
    
    with open("benchmarks/cpu_gpu_scenarios.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["scenario", "cpu_median", "gpu_median"])
        for r in results:
            writer.writerow([r["scenario"], r["cpu_median"], r["gpu_median"]])
            
    print("Agent 3 driver finished.")
    api.close_window()
    os._exit(0)

if __name__ == "__main__":
    env = os.environ.copy()
    env["NEDOTIFY_AGENT3_TEST"] = "1"
    subprocess.run([sys.executable, "main.py"], env=env)
