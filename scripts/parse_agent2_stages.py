import csv
data=[r for r in csv.DictReader(open('benchmarks/startup_timeline.csv')) if int(r['run'])==2]
t0=float([r for r in data if r['stage']=='process_spawn'][0]['timestamp'])
for r in data:
    print(f"{r['stage']}: {float(r['timestamp'])-t0:.3f}s")
