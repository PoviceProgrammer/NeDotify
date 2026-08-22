import csv
from statistics import median

data = {}
with open('benchmarks/startup_timeline.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        run = int(row['run'])
        stage = row['stage']
        ts = float(row['timestamp'])
        if run not in data: data[run] = {}
        data[run][stage] = ts

print("Agent 2 (Startup) Results:")
for run in sorted(data.keys()):
    if run == 1: continue # skip warmup
    stages = data[run]
    try:
        t0 = stages['process_spawn']
        py_init = stages['python_imports_done'] - t0
        db_init = stages.get('db_init_done', 0) - stages.get('python_imports_done', 0)
        window = stages.get('webview_window_shown', 0) - t0
        print(f"Run {run}: Window shown {window:.3f}s")
    except KeyError:
        pass
