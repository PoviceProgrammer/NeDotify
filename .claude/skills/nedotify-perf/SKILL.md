---
name: nedotify-perf
description: Measure NeDotify startup time and UI CPU, memory, scroll and search costs using the isolated tools/bench harness. Use to investigate slow startup, lag, resource use, or to validate a performance change with measurements.
---

# Measuring NeDotify performance

## Existing harness

Run from the repository root with the project interpreter:

```powershell
& ".venv_win\Scripts\python.exe" tools\bench\run_bench.py --help
& ".venv_win\Scripts\python.exe" tools\bench\run_bench.py --scenario startup --reps 5 --profile-mode warm
& ".venv_win\Scripts\python.exe" tools\bench\run_bench.py --scenario idle_states --reps 3 --seconds 60
& ".venv_win\Scripts\python.exe" tools\bench\run_bench.py --scenario combo --reps 3 --tracks 2000
```

The available scenarios are defined by argparse in `tools/bench/run_bench.py`:
`startup`, `idle`, `idle_states`, `cpu_attribution`, `scroll`, `search`, `feed`,
and `combo`. Use `--help` for current flags.

- `tools/bench/profile.py` creates deterministic covers, track fixtures and a
  scratch user profile. Only the benchmark child's environment redirects
  `USERPROFILE`; do not change the user's shell profile or clear their library.
- `run_bench.py` starts `bench_child.py` as a real subprocess and aggregates
  repeated runs. Startup includes interpreter and module import time.
- `procsampler.py` samples the process tree; `cdp.py` and `scenarios.py` drive
  the WebView2 UI. Inspect the chosen scenario before interpreting its results.
- JSON results go to `tools/bench/results/` by default; `NEDOTIFY_BENCH_OUT`
  selects another output directory.
- `tools/bench/pyprof_child.py --help` describes Python profiling modes.
  Read its profile-isolation requirements before running a mode.

The old `scripts/` / `benchmarks/` harness was retired. Do not add missing
`perf_mark` hooks or recreate its scripts to run an existing benchmark.

## Measurement choices

`--profile-mode warm` reuses a scratch profile across repetitions and models
subsequent launches. `--profile-mode fresh` creates one per repetition and
includes first-run WebView2 profile creation. Report which one was measured.

`--cookie-mode pinned` uses an empty cookie jar and avoids reading browser
cookies. `--cookie-mode real` exercises actual browser-cookie detection; report
it explicitly because its cost and access differ.

Keep track count, scenarios, runtime, profile mode and cookie mode comparable
between before and after runs. Report medians and repetition counts from the
result JSON; check exit codes and error fields before accepting a sample.
Use `--warmup-sec` for scenarios that need a settle period. Do not silently
discard failed samples or claim an unmeasured speedup.

A fixture that cannot resolve real audio does not establish time to first audio
or playback decode cost. State those limits when reporting results.

## References and user data

Historical measurements and methodology are in `docs/perf/baseline.md`,
`docs/perf/prof_python_startup.md` and `docs/perf/prof_frontend.md`. They are
dated observations, not measurements of the current checkout. Current feature
notes are in `docs/RESOURCE_OPTIMIZATION.md` and
`docs/PLAYBACK_LYRICS_PERFORMANCE.md`.

The real library is `~/.nedotify/` (database `nedotify_storage.db`, streams,
downloads and logs). Never clear it for a benchmark. Let the harness manage its
own scratch profiles.
