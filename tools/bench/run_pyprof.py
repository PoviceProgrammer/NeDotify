"""Orchestrator for the Python-side startup / idle-CPU profile.

Runs every measurement in *separate processes* (import cost and construction
time are per-process facts; a warm in-process repeat would understate both) and
writes two artefacts:

  * ``tools/bench/results/profile_python_startup.json``  - machine readable
  * ``tools/bench/results/profile_appcore_init.pstats``   - cProfile of ``AppCore()``

Everything is headless. ``webview.start()`` is never reached: ``import main`` only
executes ``main.py``'s module body (env setup + ``from core.app import AppCore``),
and the AppCore modes never call ``main()``. A NeDotify instance that is already
running on the machine is therefore untouched.

Usage::

    python tools/bench/run_pyprof.py                # full run
    python tools/bench/run_pyprof.py --quick        # fewer reps, 20 s idle
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = Path(__file__).resolve().parent
RESULTS = TOOLS_DIR / "results"
CHILD = TOOLS_DIR / "pyprof_child.py"


def _load_sleepscan():
    """Import the sibling scanner by path.

    ``tools/bench`` must NOT go on ``sys.path``: ``tools/bench/profile.py``
    shadows the stdlib ``profile`` module, which ``cProfile`` needs.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pyprof_sleepscan", TOOLS_DIR / "sleepscan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
PROFILE_ROOT = Path(os.environ.get("NEDOTIFY_PROF_SCRATCH",
                                   str(Path(os.environ.get("TEMP", ".")) /
                                       "nedotify-pyprof")))
PY = str(REPO_ROOT / ".venv_win" / "Scripts" / "python.exe")
PY_SPY = str(REPO_ROOT / ".venv_win" / "Scripts" / "py-spy.exe")

IMPORTTIME_RE = re.compile(
    r"^import time:\s+(?P<self>\d+) \|\s+(?P<cum>\d+) \| (?P<indent>\s*)(?P<name>\S+)\s*$"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def child_env(profile: Path) -> dict:
    """Environment for every child: redirected ``~``, no GUI, no user secrets."""
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["USERPROFILE"] = str(profile)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # keep the benchmark offline: no Last.fm credentials -> _api_request
    # short-circuits; and no DevTools.
    env.pop("LASTFM_API_KEY", None)
    env.pop("LASTFM_USERNAME", None)
    env.pop("NEDOTIFY_DEVTOOLS", None)
    return env


def run(cmd: list[str], env: dict, cwd: Path = REPO_ROOT, timeout: int = 600):
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, cwd=str(cwd), capture_output=True,
                          timeout=timeout)
    wall = (time.perf_counter() - t0) * 1000.0
    return proc, wall


def stat_block(values: list[float]) -> dict:
    vs = sorted(values)
    n = len(vs)
    return {
        "n_runs": n,
        "min": round(vs[0], 4),
        "median": round(statistics.median(vs), 4),
        "mean": round(statistics.fmean(vs), 4),
        "max": round(vs[-1], 4),
        "stdev": round(statistics.stdev(vs), 4) if n > 1 else 0.0,
        "samples": [round(v, 4) for v in vs],
    }


def fresh_profile(tag: str) -> Path:
    """A brand-new scratch profile per run, so no run inherits another's state."""
    p = PROFILE_ROOT / f"{tag}"
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# 1. interpreter boot + import cost
# ---------------------------------------------------------------------------
def parse_importtime(stderr: str) -> list[dict]:
    rows = []
    for line in stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        m = IMPORTTIME_RE.match(line)
        if not m:
            continue
        indent = m.group("indent")
        rows.append({
            "depth": len(indent) // 2,
            "name": m.group("name"),
            "self_us": int(m.group("self")),
            "cum_us": int(m.group("cum")),
        })
    return rows


def _link_parents(rows: list[dict]) -> None:
    """Attach a parent index to each row.

    ``-X importtime`` prints a module *after* everything it imported (post-order
    DFS), so a parent appears after its children and a single forward pass cannot
    link them. Reversing post-order DFS yields pre-order DFS, which the usual
    indent-stack algorithm handles - so the rows are linked in reverse and the
    result is then re-ordered to the original printing order.
    """
    stack: list[int] = []
    for i in reversed(range(len(rows))):  # reversed == pre-order
        d = rows[i]["depth"]
        while stack and rows[stack[-1]]["depth"] >= d:
            stack.pop()
        rows[i]["parent"] = stack[-1] if stack else None
        stack.append(i)


def _families(rows: list[dict], names: list[str]) -> list[dict]:
    """Inclusive cost of each named top-level package family.

    A family's cumulative cost is the sum of the ``cum_us`` of its *outermost*
    nodes only (nodes whose parent is not in the same family), because ``cum_us``
    is inclusive and would otherwise double-count nested submodules.
    """
    out = []
    for fam in names:
        fams = [i for i, r in enumerate(rows) if r["name"].split(".")[0] == fam]
        if not fams:
            out.append({"family": fam, "present": False, "cum_ms": 0.0,
                        "self_ms": 0.0, "modules": 0})
            continue
        fset = set(fams)
        outer = [i for i in fams if rows[i]["parent"] not in fset]
        cum = sum(rows[i]["cum_us"] for i in outer)
        self_us = sum(rows[i]["self_us"] for i in fams)
        out.append({
            "family": fam,
            "present": True,
            "cum_ms": round(cum / 1000.0, 3),
            "self_ms": round(self_us / 1000.0, 3),
            "modules": len(fams),
            "imported_from": sorted({rows[rows[i]["parent"]]["name"]
                                     for i in fams
                                     if rows[i]["parent"] is not None}),
        })
    out.sort(key=lambda e: -e["cum_ms"])
    return out


# Families worth naming explicitly: the heavy third-party stack the task asks
# about, plus the stdlib chunks they drag in.
WATCH_FAMILIES = [
    "webview", "clr", "yt_dlp", "ytmusicapi", "numpy", "scipy", "PIL", "requests",
    "urllib3", "mutagen", "pypresence", "watchdog", "pystray", "bottle", "ssl",
    "socket", "cryptography", "asyncio", "sqlite3", "http", "urllib", "email",
    "re", "json", "xml", "zipfile", "compression", "colorama", "_colorize",
    "charset_normalizer", "certifi", "idna", "logging", "concurrent", "wave",
    "threading", "ctypes", "webbrowser", "socketserver",
]


def aggregate_imports(rows: list[dict]) -> dict:
    """Break the ``-X importtime`` tree down into report-ready groups.

    ``self_us`` is exclusive of descendants and therefore additive: summing it
    over every row gives the CPU actually spent executing module bodies.
    ``cum_us`` is inclusive, so it must only be summed over *disjoint* subtrees.
    """
    _link_parents(rows)
    top_level = [r for r in rows if r["depth"] == 0]
    total_self_us = sum(r["self_us"] for r in rows)
    main_cum = next((r["cum_us"] for r in top_level if r["name"] == "main"), 0)

    def row_out(r: dict) -> dict:
        return {"name": r["name"], "depth": r["depth"],
                "self_ms": round(r["self_us"] / 1000.0, 3),
                "cum_ms": round(r["cum_us"] / 1000.0, 3)}

    main_children = [r for r in rows
                     if r["depth"] == 1 and r["parent"] is not None
                     and rows[r["parent"]]["name"] == "main"]

    # every node >= 4 ms inclusive that is not already a child of main
    heavy_nested = [row_out(r) for r in rows
                    if r["cum_us"] >= 4000 and r not in main_children
                    and r["name"] != "main"]

    by_family_self: dict = {}
    for r in rows:
        fam = r["name"].split(".")[0]
        e = by_family_self.setdefault(fam, {"family": fam, "self_us": 0, "modules": 0,
                                            "max_depth": 0})
        e["self_us"] += r["self_us"]
        e["modules"] += 1
        e["max_depth"] = max(e["max_depth"], r["depth"])
    fams = sorted(by_family_self.values(), key=lambda e: -e["self_us"])
    for e in fams:
        e["self_ms"] = round(e.pop("self_us") / 1000.0, 3)

    return {
        "n_modules": len(rows),
        "root_main_cum_ms": round(main_cum / 1000.0, 3),
        "sum_all_self_ms": round(total_self_us / 1000.0, 3),
        "top_level": [row_out(r) for r in
                      sorted(top_level, key=lambda r: -r["cum_us"])],
        "main_direct_children": [row_out(r) for r in
                                 sorted(main_children, key=lambda r: -r["cum_us"])],
        "watched_families": _families(rows, WATCH_FAMILIES),
        "by_family_self": fams,
        "heavy_nested_cum_ge_4ms": sorted(heavy_nested, key=lambda r: -r["cum_ms"])[:30],
        "slowest_modules_by_self": [row_out(r) for r in
                                    sorted(rows, key=lambda r: -r["self_us"])[:25]],
    }


def measure_interpreter(reps: int) -> dict:
    env = child_env(PROFILE_ROOT / "floor")
    floors, floor_self = [], []
    for _ in range(reps):
        proc, wall = run([PY, "-c", "pass"], env)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
        floors.append(wall)

    # floor with importtime so the boot-only import cost is also broken out
    proc, wall = run([PY, "-X", "importtime", "-c", "pass"], env)
    boot_rows = parse_importtime(proc.stderr.decode("utf-8", "replace"))
    for r in boot_rows:
        floor_self.append(r["self_us"])

    imports = []
    per_run = []
    for i in range(reps):
        p = fresh_profile(f"import_{i}")
        e = child_env(p)
        proc, wall = run([PY, "-X", "importtime", "-c", "import main"], e)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
        imports.append(wall)
        rows = parse_importtime(proc.stderr.decode("utf-8", "replace"))
        per_run.append(aggregate_imports(rows))

    # median run's aggregation = the representative breakdown
    median_run = min(range(len(per_run)),
                     key=lambda i: abs(per_run[i]["sum_all_self_ms"]
                                        - statistics.median(
                                            [r["sum_all_self_ms"] for r in per_run])))
    return {
        "interpreter_floor_ms": stat_block(floors),
        "interpreter_floor_importtime": aggregate_imports(boot_rows),
        "import_main_wall_ms": stat_block(imports),
        "import_main_wall_minus_floor_ms": stat_block(
            [w - f for w, f in zip(imports, floors)]),
        "import_main_import_self_ms": stat_block(
            [r["sum_all_self_ms"] for r in per_run]),
        "import_main_root_cum_ms": stat_block(
            [r["root_main_cum_ms"] for r in per_run]),
        "representative_breakdown": per_run[median_run],
        "per_run_breakdown": per_run,
        "evidence": {
            "command_floor": f"{PY} -c pass",
            "command_import": f"{PY} -X importtime -c \"import main\"",
        },
    }


# ---------------------------------------------------------------------------
# 2/3. AppCore construction
# ---------------------------------------------------------------------------
def measure_appcore_init(reps: int) -> dict:
    walls, imports_at_child, payloads = [], [], []
    for i in range(reps):
        p = fresh_profile(f"appcore_{i}")
        out = RESULTS / "raw" / f"appcore_init_{i}.json"
        proc, wall = run([PY, str(CHILD), "appcore_init", "--profile", str(p),
                          "--json", str(out)], child_env(p))
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
        walls.append(wall)
        payloads.append(json.loads(out.read_text(encoding="utf-8")))
    # the child's own timer excludes interpreter start + `import core.app`
    internal = [d["ms"] for d in payloads]
    n_threads = payloads[0]["n_threads_after"]
    return {
        "child_reported_ms": stat_block(internal),
        "process_wall_ms": stat_block(walls),
        "python_threads_after_construction": n_threads,
        "threads": payloads[0]["threads_after"],
        "evidence": {"command": f"{PY} {CHILD} appcore_init --profile <scratch>"},
    }


def measure_cprofile() -> dict:
    p = fresh_profile("cprofile")
    pstats = RESULTS / "profile_appcore_init.pstats"
    out = RESULTS / "raw" / "appcore_cprofile.json"
    proc, wall = run([PY, str(CHILD), "appcore_cprofile", "--profile", str(p),
                      "--pstats", str(pstats), "--json", str(out), "--top", "40"],
                     child_env(p))
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    d = json.loads(out.read_text(encoding="utf-8"))
    return {
        "wall_ms": round(wall, 3),
        "profiled_ms": round(d["ms"], 3),
        "pstats": str(pstats.relative_to(REPO_ROOT)).replace("\\", "/"),
        "top_cumulative": d["top_cumulative"][:25],
        "top_tottime": d["top_tottime"][:15],
        "top_cumulative_callers": d["top_cumulative_callers"],
        "threads_after": d["threads_after"],
        "evidence": {"command": f"{PY} {CHILD} appcore_cprofile --pstats ..."},
    }


def measure_breakdown(reps: int) -> dict:
    runs = []
    for i in range(reps):
        p = fresh_profile(f"breakdown_{i}")
        out = RESULTS / "raw" / f"breakdown_{i}.json"
        proc, wall = run([PY, str(CHILD), "appcore_breakdown", "--profile", str(p),
                          "--json", str(out)], child_env(p))
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
        runs.append(json.loads(out.read_text(encoding="utf-8")))

    labels: dict = {}
    for r in runs:
        for step in r["steps"]:
            labels.setdefault(step["label"], []).append(step["ms_total"])
    steps = []
    for label, vals in labels.items():
        st = stat_block(vals)
        threads = next((s["threads"] for r in runs for s in r["steps"]
                        if s["label"] == label), [])
        steps.append({"label": label, "median_ms": st["median"], "n_runs": st["n_runs"],
                      "min_ms": st["min"], "max_ms": st["max"],
                      "samples": st["samples"], "threads": threads})
    steps.sort(key=lambda s: -s["median_ms"])
    total = stat_block([r["total_ms"] for r in runs])
    drain = stat_block([r["async_drain_ms"] for r in runs])
    measured = sum(s["median_ms"] for s in steps if s["threads"] == ["MainThread"])
    return {
        "total_constructor_ms": total,
        "async_drain_after_constructor_ms": drain,
        "main_thread_steps_median_sum_ms": round(measured, 3),
        "unattributed_main_thread_ms": round(total["median"] - measured, 3),
        "steps": steps,
        "evidence": {"command": f"{PY} {CHILD} appcore_breakdown --profile <scratch>"},
    }


# ---------------------------------------------------------------------------
# 4. idle CPU
# ---------------------------------------------------------------------------
def measure_idle(seconds: int, settle: int) -> dict:
    p = fresh_profile("idle")
    out = RESULTS / "raw" / "idle.json"
    proc, wall = run([PY, str(CHILD), "idle", "--profile", str(p),
                      "--seconds", str(seconds), "--settle", str(settle),
                      "--json", str(out)], child_env(p), timeout=seconds + settle + 180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    idle = json.loads(out.read_text(encoding="utf-8"))

    pc = fresh_profile("idle_control")
    outc = RESULTS / "raw" / "idle_control.json"
    procc, wallc = run([PY, str(CHILD), "idle_control", "--profile", str(pc),
                        "--seconds", str(seconds), "--settle", str(settle),
                        "--json", str(outc)], child_env(pc),
                       timeout=seconds + settle + 180)
    if procc.returncode != 0:
        raise RuntimeError(procc.stderr.decode("utf-8", "replace"))
    control = json.loads(outc.read_text(encoding="utf-8"))
    return {"with_appcore": idle, "control_no_appcore": control,
            "evidence": {"command": f"{PY} {CHILD} idle --seconds {seconds}"}}


def measure_pyspy(seconds: int) -> dict:
    """py-spy sampling of a headless AppCore process, for cross-checking."""
    if not Path(PY_SPY).exists():
        return {"available": False, "reason": f"{PY_SPY} not found"}
    p = fresh_profile("pyspy")
    out = RESULTS / "raw" / "pyspy_idle_hold.json"
    svg = RESULTS / "pyspy_idle.svg"
    spd = RESULTS / "pyspy_idle.speedscope.json"
    env = child_env(p)
    proc = subprocess.Popen(
        [PY, str(CHILD), "idle_hold", "--profile", str(p),
         "--seconds", str(seconds + 60), "--json", str(out)],
        env=env, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    pid = None
    deadline = time.time() + 120
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            pid = json.loads(line)["pid"]
            break
        except (ValueError, KeyError):
            continue
    if pid is None:
        proc.kill()
        return {"available": False, "reason": "child never reported its pid"}

    # give construction-time background work (zapret +5s, lufs +10s) time to finish
    time.sleep(15)
    time.sleep(0)  # flush
    res = {"available": True, "pid": pid, "duration_s": seconds,
           "rate_hz": 100, "attempts": []}
    for fmt, path in (("speedscope", spd), ("raw", svg)):
        cmd = [PY_SPY, "record", "--pid", str(pid), "--duration", str(seconds),
               "--rate", "100", "--format", fmt, "--output", str(path),
               "--nonblocking", "--threads"]
        t0 = time.perf_counter()
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=seconds + 180)
            res["attempts"].append({
                "format": fmt,
                "returncode": r.returncode,
                "wall_s": round(time.perf_counter() - t0, 2),
                "output": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
                "stderr_tail": r.stderr.decode("utf-8", "replace")[-800:],
            })
        except subprocess.TimeoutExpired:
            res["attempts"].append({"format": fmt, "error": "timeout"})
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    for fmt, path in (("speedscope", spd), ("raw", svg)):
        if not path.exists():
            continue
        if fmt == "speedscope":
            try:
                res.setdefault("files", {})[fmt] = json.loads(path.read_text("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                res.setdefault("files", {})[fmt] = {"error": str(e)}
        else:
            # py-spy's "raw" flamegraph: one line per thread,
            # "thread (tid);frame;frame... <self_sample_count>"
            try:
                lines = [ln for ln in path.read_text("utf-8").splitlines() if ln.strip()]
            except (ValueError, UnicodeDecodeError) as e:
                lines = [f"<undecodable: {e}>"]
            res.setdefault("files", {})[fmt] = {
                "format": "folded stacks, trailing number = self samples",
                "svg_lines": lines,
            }
    return res


def _where(frame: dict) -> str:
    f = frame.get("file") or "?"
    ln = frame.get("line")
    return f"{f}:{ln}" if ln else f


def summarize_pyspy(res: dict) -> dict:
    """Turn the py-spy output into per-thread self-time.

    IMPORTANT INTERPRETATION NOTE: an idle NeDotify spends its time blocked in
    ``time.sleep`` / ``WaitForSingleObject``, i.e. with the GIL released and no
    Python frame on top of the stack. py-spy therefore captures only a handful
    of samples. A small "sampled weight" below means "the sampler rarely caught
    this thread executing Python code", **not** "this thread uses no CPU".
    Per-thread CPU really has to come from ``psutil``'s ``Process.threads()``
    accounting; this output is only a cross-check.
    """
    out: dict = {"parsed": False}
    files = res.get("files", {})
    spd = files.get("speedscope")
    if isinstance(spd, dict) and "shared" in spd:
        frames = spd["shared"]["frames"]
        per_thread = []
        leaf: dict = {}
        for prof in spd["profiles"]:
            tname = prof.get("name", "?")
            weights = prof.get("weights", [])
            samples = prof.get("samples", [])
            total_w = 0.0
            for w, stack in zip(weights, samples):
                total_w += w
                if not stack:
                    continue
                fr = frames[stack[0]]
                key = (tname, fr.get("name", "?"), _where(fr))
                leaf[key] = leaf.get(key, 0.0) + w
            per_thread.append({
                "thread": tname,
                "n_samples": len(samples),
                "sampled_weight_s": round(total_w, 4),
                "endValue": prof.get("endValue"),
            })
        out = {
            "parsed": True,
            "unit": spd.get("unit"),
            "recorded_duration_s": res.get("duration_s"),
            "threads": sorted(per_thread, key=lambda t: -t["sampled_weight_s"]),
            "self_frames": [
                {"thread": k[0], "func": k[1], "at": k[2], "sampled_s": round(v, 4)}
                for k, v in sorted(leaf.items(), key=lambda kv: -kv[1])[:30]
            ],
        }
    raw = files.get("raw")
    if isinstance(raw, dict) and "svg_lines" in raw:
        out["svg_lines"] = raw["svg_lines"]
    return out


def join_sleep_sites(payload: dict) -> dict:
    """Static inventory of every sleep/wait site + the measured wake counts.

    The measured counts come from ``idle``'s wake log (keyed ``file:line``); a
    site with no measured entry was simply not awake during the 60 s window.
    """
    sites = _load_sleepscan().scan()
    idle = payload["measurement"]["idle_cpu"]["with_appcore"]
    # The wake log is installed BEFORE the settle phase, so it covers
    # settle + window. Dividing by the window alone would overstate the rate.
    observed_s = idle["settle_s"] + idle["window_s"]
    measured: dict = {}
    for kind in ("sleeps", "event_waits"):
        for site, row in idle["wake_log"]["app"][kind].items():
            f, _, ln = site.rpartition(":")
            measured.setdefault(f"{f}:{ln}", []).append({
                "call_kind": "time.sleep" if kind == "sleeps" else "Event.wait",
                "calls_observed": row["calls"],
                "blocked_s": round(row.get("blocked_s", 0.0), 3),
                "timeout_wakes": row.get("timeout_wakes"),
                "declared": row.get("declared_s", row.get("declared")),
            })
    for s in sites:
        key = f"{s['file']}:{s['line']}"
        s["measured"] = measured.get(key, [])
        s["measured_wake_hz"] = (
            round(max(r["calls_observed"] for r in s["measured"]) / observed_s, 4)
            if s["measured"] else None)
    sites.sort(key=lambda s: (-bool(s["measured"]),
                              -(s["measured"][0]["calls_observed"] if s["measured"] else 0),
                              s["file"], s["line"]))
    return {
        "source": "tools/bench/sleepscan.py (AST scan of shipped *.py, read-only)",
        "idle_window_s": idle["window_s"],
        "settle_s": idle["settle_s"],
        "wake_log_observed_s": round(observed_s, 2),
        "note": "measured_wake_hz = calls_observed / wake_log_observed_s; the last "
                "sleep in flight at process exit is counted as a call but "
                "contributes no blocked_s",
        "n_sites": len(sites),
        "n_sites_alive_in_idle_window": sum(1 for s in sites if s["measured"]),
        "sites": sites,
    }


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--idle-seconds", type=int, default=60)
    ap.add_argument("--settle", type=int, default=15)
    ap.add_argument("--pyspy-seconds", type=int, default=60)
    ap.add_argument("--skip-pyspy", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="fewer reps and a 20 s idle window (smoke run)")
    ap.add_argument("--rejoin-sites-only", action="store_true",
                    help="recompute only the static sleep/wait section from an "
                         "existing result JSON; re-times nothing")
    args = ap.parse_args(argv)
    if args.quick:
        args.reps = 3
        args.idle_seconds = 20
        args.pyspy_seconds = 20

    out = RESULTS / "profile_python_startup.json"
    if args.rejoin_sites_only:
        payload = json.loads(out.read_text(encoding="utf-8"))
        payload["measurement"]["sleep_and_wait_sites"] = join_sleep_sites(payload)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"rejoined sleep/wait sites -> {out}")
        return 0

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    env0 = child_env(PROFILE_ROOT / "root")

    payload: dict = {
        "label": "profile_python_startup",
        "scenario": "python_startup_and_idle",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version,
        "python_executable": PY,
        "repo_root": str(REPO_ROOT),
        "profile_isolation": {
            "how": "USERPROFILE (plus cleared HOMEDRIVE/HOMEPATH) pointed at a fresh "
                   "scratch dir before any project import; the project hard-codes "
                   "os.path.expanduser('~') + '/.nedotify' with no override env var",
            "scratch_root": str(PROFILE_ROOT),
            "gui": "never launched - webview.start() is not reached by any mode",
        },
        "host": {},
        "measurement": {},
    }
    for key, cmd in (("cpu", ["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor).Name"]),
                     ("logical_cores", ["powershell", "-NoProfile", "-Command",
                                        "(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors"])):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            payload["host"][key] = r.stdout.decode("utf-8", "replace").strip()
        except Exception as e:  # pragma: no cover
            payload["host"][key] = f"<unavailable: {e}>"

    print("[1/5] interpreter boot + import cost ...", flush=True)
    payload["measurement"]["interpreter_and_imports"] = measure_interpreter(args.reps)

    print("[2/5] AppCore() construction (plain timing) ...", flush=True)
    payload["measurement"]["appcore_init"] = measure_appcore_init(args.reps)

    print("[3/5] AppCore() cProfile ...", flush=True)
    payload["measurement"]["appcore_cprofile"] = measure_cprofile()

    print("[4/5] per-step breakdown ...", flush=True)
    payload["measurement"]["appcore_breakdown"] = measure_breakdown(args.reps)

    print(f"[5/5] idle CPU ({args.idle_seconds}s) + control ...", flush=True)
    payload["measurement"]["idle_cpu"] = measure_idle(args.idle_seconds, args.settle)

    if args.skip_pyspy:
        payload["measurement"]["pyspy"] = {"available": False, "reason": "skipped by flag"}
    else:
        print(f"      py-spy record {args.pyspy_seconds}s ...", flush=True)
        payload["measurement"]["pyspy"] = measure_pyspy(args.pyspy_seconds)

    payload["measurement"]["pyspy_summary"] = summarize_pyspy(
        payload["measurement"]["pyspy"])
    payload["measurement"]["sleep_and_wait_sites"] = join_sleep_sites(payload)

    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())