"""Print the numbers used by docs/perf/prof_python_startup.md.

Kept as a script (not an inline ``-c``) so PowerShell quoting never mangles it.
Read-only: it only reads profile_python_startup.json.
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
J = RESULTS / "profile_python_startup.json"


def line(st: dict) -> str:
    return (f"median={st['median']} n={st['n_runs']} min={st['min']} "
            f"max={st['max']} sd={st['stdev']} samples={st['samples']}")


def main() -> int:
    d = json.loads(J.read_text(encoding="utf-8"))
    m = d["measurement"]
    print(f"generated {d['generated_at']} | {d['host']['logical_cores']} logical cores")
    print(f"cpu: {d['host']['cpu']}")
    print(f"python: {d['python'].splitlines()[0]}")

    I = m["interpreter_and_imports"]
    print("\n### 1 import")
    for k in ("interpreter_floor_ms", "import_main_wall_ms",
              "import_main_wall_minus_floor_ms", "import_main_import_self_ms",
              "import_main_root_cum_ms"):
        print(f"  {k:38s} {line(I[k])}")
    fb = I["interpreter_floor_importtime"]
    print(f"  boot-only importtime: n_modules={fb['n_modules']} "
          f"sum_all_self={fb['sum_all_self_ms']}ms")
    b = I["representative_breakdown"]
    print(f"  representative: n_modules={b['n_modules']} "
          f"sum_all_self={b['sum_all_self_ms']}ms root_main_cum={b['root_main_cum_ms']}ms")
    print("  main's direct children (inclusive):")
    for x in b["main_direct_children"]:
        print(f"    cum={x['cum_ms']:8.3f} self={x['self_ms']:7.3f}  {x['name']}")
    print("  top-level imports that are NOT present at startup:")
    print("   ", [x["family"] for x in b["watched_families"] if not x["present"]])
    print("  third-party / heavy families (inclusive, disjoint subtrees):")
    for x in b["watched_families"]:
        if x["present"] and x["cum_ms"] >= 3.0:
            print(f"    cum={x['cum_ms']:8.3f} self={x['self_ms']:7.3f} "
                  f"n={x['modules']:<4} {x['family']}")
    print("  heaviest nested subtrees (cum >= 4 ms, not a direct child of main):")
    for x in b["heavy_nested_cum_ge_4ms"][:16]:
        print(f"    cum={x['cum_ms']:8.3f} self={x['self_ms']:7.3f} "
              f"depth={x['depth']} {x['name']}")
    print("  heaviest single modules by SELF time:")
    for x in b["slowest_modules_by_self"][:12]:
        print(f"    self={x['self_ms']:7.3f} cum={x['cum_ms']:8.3f}  {x['name']}")

    print("\n### 2 appcore_init")
    A = m["appcore_init"]
    print(f"  child_reported_ms   {line(A['child_reported_ms'])}")
    print(f"  process_wall_ms     {line(A['process_wall_ms'])}")
    print(f"  python threads after construction: {A['python_threads_after_construction']}")
    print(f"  {A['threads']}")

    print("\n### 3 cprofile")
    C = m["appcore_cprofile"]
    print(f"  wall_ms={C['wall_ms']} profiled_ms={C['profiled_ms']} pstats={C['pstats']}")
    for i, r in enumerate(C["top_cumulative"][:25], 1):
        print(f"  {i:2d}. cum={r['cumtime_ms']:8.3f} self={r['tottime_ms']:8.3f} "
              f"n={r['ncalls']:<5} {r['file']}:{r['line']} {r['func']}")
    print("  top by SELF:")
    for r in C["top_tottime"][:10]:
        print(f"    self={r['tottime_ms']:8.3f} cum={r['cumtime_ms']:8.3f} "
              f"n={r['ncalls']:<5} {r['file']}:{r['line']} {r['func']}")

    print("\n### 4 breakdown")
    D = m["appcore_breakdown"]
    print(f"  total_constructor_ms            {line(D['total_constructor_ms'])}")
    print(f"  async_drain_after_constructor  {line(D['async_drain_after_constructor_ms'])}")
    print(f"  main-thread steps sum={D['main_thread_steps_median_sum_ms']} "
          f"unattributed={D['unattributed_main_thread_ms']}")
    for s in D["steps"]:
        print(f"    {s['median_ms']:8.3f} ms  [{s['min_ms']}..{s['max_ms']}] "
              f"n={s['n_runs']}  {s['label']}  threads={s['threads']}")

    print("\n### 5 idle")
    I2 = m["idle_cpu"]
    for tag in ("with_appcore", "control_no_appcore"):
        x = I2[tag]
        print(f"  -- {tag}")
        for k in ("build_ms", "settle_s", "settle_cpu_s", "window_s",
                  "idle_window_cpu_s", "idle_window_cpu_pct_of_one_core",
                  "harness_cpu_s", "idle_window_cpu_s_excl_harness",
                  "idle_window_cpu_pct_excl_harness",
                  "os_threads_created_during_build", "os_thread_count_at_settle",
                  "os_thread_count_at_end", "os_tids_only_at_one_end",
                  "cpu_after_build_total_s", "cpu_at_end_total_s"):
            print(f"    {k:36s} {x[k]}")
        for r in x["per_os_thread_idle_all"]:
            print(f"      thread {r['idle_cpu_s']:.6f}s "
                  f"{r['idle_cpu_pct_of_one_core']:.4f}%  {r['name']}")
        wl = x["wake_log"]["app"]
        print(f"    app sleeps: {json.dumps(wl['sleeps'], ensure_ascii=False)}")
        print(f"    app waits : {json.dumps(wl['event_waits'], ensure_ascii=False)}")
        print(f"    app timers: {json.dumps(wl['timers_created'], ensure_ascii=False)}")

    print("\n### 6 pyspy")
    P = m["pyspy"]
    print(f"  {json.dumps({k: v for k, v in P.items() if k != 'files'}, ensure_ascii=False)}")
    S = m["pyspy_summary"]
    print(f"  parsed={S.get('parsed')} duration={S.get('recorded_duration_s')}")
    for t in S.get("threads", []):
        print(f"    {t}")
    for f in S.get("self_frames", []):
        print(f"    {f}")
    for ln in S.get("svg_lines", []) or []:
        print(f"    svg| {ln}")

    print("\n### 7 sleep/wait sites")
    W = m["sleep_and_wait_sites"]
    print(f"  n_sites={W['n_sites']} alive_in_idle_window={W['n_sites_alive_in_idle_window']}")
    for s in W["sites"]:
        hz = s["measured_wake_hz"]
        print(f"    {s['file']}:{s['line']:<4} {s['kind']:<14} "
              f"interval={str(s['interval']):<28} while={str(s['inside_while_loop']):<5} "
              f"hz={str(hz):<8} {s['enclosing_function']} :: {s['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())