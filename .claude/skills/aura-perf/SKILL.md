---
name: aura-perf
description: Measure and profile AURA Music performance — cold/warm startup timeline, time-to-first-audio per provider, and idle/playback CPU & GPU cost per UI scenario. Use when asked about startup time, lag, stutter, high CPU or GPU usage, visualizer/blur cost, or when validating an optimization with numbers instead of guesses.
---

# Performance measurement

The harness lives in `scripts/` and writes to `benchmarks/`. Everything is
driven from the project venv: `& ".venv\Scripts\python.exe" scripts\<script>`.

## Three measurement tracks

| Agent | Question | Script | Output |
|---|---|---|---|
| 1 | Time-to-first-audio per provider (YouTube / SoundCloud / Spotify), cold cache | `scripts/run_agent1.py` — `agent1_driver(app_core, api)` | `~/.nedotify/logs/perf.jsonl` stages |
| 2 | Startup timeline, stage by stage | `scripts/run_agent2.py` | `benchmarks/startup_timeline.csv`, optional `benchmarks/startup.prof` |
| 3 | CPU/GPU per UI scenario (idle, playback ±visualizer, scroll, settings, blur, fullscreen glow) | `scripts/run_agent3.py` — `agent3_driver(app_core, api)` | CSV + console |

Parsers: `scripts/parse_agent2.py` (per-run window-shown medians, run 1 is the
discarded warmup) and `scripts/parse_agent2_stages.py` (stage breakdown for
run 2, offsets relative to `process_spawn`).

## Sampling probes

- `scripts/cpu.ps1` — summed `PercentProcessorTime` for all `python*` and
  `msedgewebview2*` processes. Divide by core count for a percentage;
  `run_agent3.py` currently hardcodes **12 cores** — fix that constant before
  trusting absolute numbers on other hardware.
- `scripts/gpu.ps1` — summed `GPUEngine.UtilizationPercentage` matched per PID
  via `pid_<id>_luid`. Returns 0 when the GPU counters are unavailable, which
  looks identical to "no GPU load" — sanity-check against Task Manager.

Both are invoked as `powershell -ExecutionPolicy Bypass -File scripts/<x>.ps1`
from the repo root, so run them with the working directory at the root.

## Instrumentation contract

`run_agent1.py` does `from main import perf_mark` and `run_agent2.py` sets
`NEDOTIFY_PERF_DEBUG=1`. **Neither `perf_mark` nor that env var is currently
implemented in `main.py`** — the harness is work in progress on
`perf/measurement-2026-08-22`. Before running agents 1 or 2, add the hook:
`perf_mark(stage: str)` appending `{"run", "stage", "timestamp"}` JSON lines to
`~/.nedotify/logs/perf.jsonl`, gated on `NEDOTIFY_PERF_DEBUG`, with marks at
`process_spawn`, `python_imports_done`, `db_init_done`, `webview_window_shown`.
Use `time.perf_counter()` — the existing CSV timestamps are perf-counter values,
not wall clock.

## Method

- Discard the first run as warmup; report the **median** of the rest (the
  parsers already assume this).
- Clear caches between cold-start runs the way `run_agent1.clear_caches` does:
  delete the `stream_cache` row and the `.cache/streams/<source>_<id>.<ext>`
  file. Do not wipe `aura.db` or the whole cache directory.
- Measure before and after any optimization, and quote both numbers. A change
  claimed as a speedup without a before/after median is not validated.
- Startup cost is dominated by WebView2 bring-up, not Python imports — check
  the stage breakdown before optimizing import time.
