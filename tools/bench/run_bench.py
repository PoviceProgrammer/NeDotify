"""Parent driver for the NeDotify benchmark.

Owns the scratch profile, the fixture, the repetitions and the aggregation.
Runs the app as a real subprocess so cold start includes interpreter boot and
module import - an in-process measurement would silently omit exactly the cost
we care most about.

Usage
-----
    python tools/bench/run_bench.py --scenario startup --reps 5
    python tools/bench/run_bench.py --scenario combo --reps 5 --tracks 2000
    python tools/bench/run_bench.py --list
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# The app logs Cyrillic; a cp1251 console would raise UnicodeEncodeError and
# kill the runner mid-report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from tools.bench import profile as prof  # noqa: E402

RESULTS_DIR = Path(os.environ.get("NEDOTIFY_BENCH_OUT", REPO_ROOT / "tools" / "bench" / "results"))
PYTHON = REPO_ROOT / ".venv_win" / "Scripts" / "python.exe"
CHILD = Path(__file__).resolve().parent / "bench_child.py"

# library scroller + search results scroller, per ui/web_new_v2/index.html
DEFAULT_SCROLL_TARGETS = [
    ("#lib-active-tracks", "library_2000"),
    ("#search-results", "search_results"),
]


# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[bench] {msg}", flush=True)


def parse_startup_log(profile_root: Path) -> tuple[dict, dict]:
    """Return (markers, absolute_epoch_timestamps) parsed from app.log.

    The log line prefix is ``HH:MM:SS.mmm`` which, combined with the parent's
    own Popen timestamp, yields a true end-to-end cold start that includes
    interpreter start-up and module import.
    """
    markers: dict[str, float] = {}
    epochs: dict[str, float] = {}
    log_file = profile_root / ".nedotify" / "logs" / "app.log"
    if not log_file.exists():
        return markers, epochs
    today = dt.date.today()
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return markers, epochs
    for line in lines:
        if "[startup]" not in line:
            continue
        try:
            stamp, rest = line.split(" ", 1)
            h, m, s = stamp.split(":")
            sec, ms = s.split(".")
            when = dt.datetime.combine(
                today, dt.time(int(h), int(m), int(sec), int(ms) * 1000))
            label_part = rest.split("INFO: ", 1)[-1]
            label = label_part.split("(+", 1)[0].replace("[startup] ", "").strip()
            epochs[label] = when.timestamp()
            if "(+" in label_part:
                markers[label] = float(label_part.split("(+", 1)[1].split("ms)", 1)[0])
        except (ValueError, IndexError):
            continue
    return markers, epochs


# --------------------------------------------------------------------------
def run_once(spec: dict, timeout: float = 300.0, debug_port: int = 9222,
             profile_root: Path | None = None) -> dict:
    """One isolated, seeded, measured app launch.

    ``profile_root=None`` creates a throwaway profile (first-ever launch: the
    WebView2 user-data folder does not exist yet). Passing a directory reuses
    it, which is what a real user's *second* launch looks like - measured at
    ~1.5 s versus ~12.3 s for the first, so the distinction matters a lot.
    """
    owns_profile = profile_root is None
    if owns_profile:
        profile_root = prof.make_scratch_profile()
    profile_root = Path(profile_root)
    try:
        covers = prof.write_covers(profile_root)
        seed_info = prof.seed_db(
            profile_root / ".nedotify" / "nedotify_storage.db",
            prof.make_track_specs(spec.get("tracks", 2000)),
            covers, history_per_track=spec.get("history_per_track", 0),
            cookie_mode=spec.get("cookie_mode", "pinned"))

        results_file = profile_root / "bench_results.json"
        spec_file = profile_root / "bench_spec.json"
        spec = dict(spec)
        spec["profile_root"] = str(profile_root)
        spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        env = prof.child_env(profile_root, debug_port=debug_port)
        env["NEDOTIFY_BENCH_SPEC"] = str(spec_file)
        env["NEDOTIFY_BENCH_RESULTS"] = str(results_file)
        env["NEDOTIFY_BENCH_PORT"] = str(debug_port)

        t_popen = time.time()
        t0 = time.monotonic()
        proc = subprocess.Popen(
            [str(PYTHON), str(CHILD)],
            cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            out += "\n[bench] TIMEOUT - killed"
        wall = time.monotonic() - t0
        exit_code = proc.returncode

        markers, epochs = parse_startup_log(profile_root)
        cold: dict = {}
        if epochs:
            cold = {
                "interpreter_and_import_ms": round((epochs.get("process started", t_popen) - t_popen) * 1000, 1),
                "to_window_created_ms": round((epochs.get("window created", t_popen) - t_popen) * 1000, 1),
                "to_window_loaded_ms": round((epochs.get("window loaded", t_popen) - t_popen) * 1000, 1),
                "to_webview_loop_ms": round((epochs.get("webview loop starting", t_popen) - t_popen) * 1000, 1),
            }

        payload = {}
        if results_file.exists():
            try:
                payload = json.loads(results_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {"error": "unreadable results file"}

        return {
            "ok": exit_code == 0 and not payload.get("error"),
            "exit_code": exit_code,
            "wall_sec": round(wall, 2),
            "cold_start": cold,
            "startup_markers_ms": markers,
            "seed": seed_info,
            "child": payload,
            "stdout_tail": (out or "")[-4000:],
            "profile_root": str(profile_root),
        }
    finally:
        if owns_profile and not spec.get("keep_profile"):
            shutil.rmtree(profile_root, ignore_errors=True)


# --------------------------------------------------------------------------
def _median(values: list[float]) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(statistics.median(vals), 2)


def _flatten(node, prefix: str, out: dict) -> None:
    """Collect every numeric leaf under `node` keyed by its path."""
    if isinstance(node, dict):
        for k, v in node.items():
            _flatten(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _flatten(v, f"{prefix}[{i}]", out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out[prefix] = node


def aggregate(runs: list[dict]) -> dict:
    """Median across repetitions of every numeric leaf (the task's >=5 rule)."""
    per_run: list[dict] = []
    for r in runs:
        flat: dict = {}
        _flatten({"cold_start": r.get("cold_start"), "child": r.get("child")}, "", flat)
        per_run.append(flat)
    keys = sorted({k for f in per_run for k in f})
    agg = {}
    for k in keys:
        med = _median([f.get(k) for f in per_run])
        if med is not None:
            agg[k] = med
    return {"n_runs": len(runs), "medians": agg}


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="NeDotify performance benchmark")
    ap.add_argument("--scenario", default="startup",
                    choices=["startup", "idle", "idle_states", "cpu_attribution",
                             "scroll", "search", "feed", "combo"])
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--tracks", type=int, default=2000)
    ap.add_argument("--history-per-track", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=60.0, help="idle sample window")
    ap.add_argument("--rounds", type=int, default=3, help="scroll/search rounds per rep")
    ap.add_argument("--query", default="Daft Punk")
    ap.add_argument("--settle-sec", type=float, default=2.0)
    ap.add_argument("--sample-interval", type=float, default=1.0)
    ap.add_argument("--warmup-sec", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--cookie-mode", default="pinned", choices=["pinned", "real"],
                    help="pinned: empty cookie jar, never reads the real browser "
                         "(hermetic, but omits the ~121 ms Firefox-cookie cost). "
                         "real: auto-detection as a user gets it, reads the real "
                         "browser profile.")
    ap.add_argument("--profile-mode", default="warm", choices=["warm", "fresh"],
                    help="warm: reuse one profile across reps (a user's 2nd+ launch, "
                         "the honest baseline). fresh: throwaway profile each rep "
                         "(first-ever launch incl. WebView2 profile creation).")
    ap.add_argument("--reverse-conditions", action="store_true",
                    help="cpu_attribution: run the condition list backwards, to "
                         "separate a causal effect from session-position drift")
    ap.add_argument("--keep-profile", action="store_true")
    ap.add_argument("--label", default=None, help="name recorded in the result file")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("scenarios: startup, idle, scroll, search, feed, combo")
        return 0

    if not PYTHON.exists():
        log(f"venv python not found at {PYTHON}")
        return 2

    spec = {
        "scenario": args.scenario,
        "tracks": args.tracks,
        "history_per_track": args.history_per_track,
        "seconds": args.seconds,
        "rounds": args.rounds,
        "query": args.query,
        "settle_sec": args.settle_sec,
        "sample_interval": args.sample_interval,
        "warmup_sec": args.warmup_sec,
        "keep_profile": args.keep_profile,
        "targets": DEFAULT_SCROLL_TARGETS,
        "url_filter": "index.html",
        "cookie_mode": args.cookie_mode,
        "reverse_conditions": args.reverse_conditions,
    }

    fingerprint = prof.fingerprint_tree()

    # Warm profile: one persistent scratch profile reused across reps, so rep 1
    # is a throwaway that pays the WebView2 user-data-folder creation cost.
    warm_root = None
    if args.profile_mode == "warm":
        warm_root = RESULTS_DIR / "_warm_profile"
        if warm_root.exists() and not args.keep_profile:
            shutil.rmtree(warm_root, ignore_errors=True)
        warm_root.mkdir(parents=True, exist_ok=True)
        log(f"warm profile at {warm_root} (rep 1 primes it, reps 2+ are steady state)")

    runs = []
    if warm_root is not None:
        # A brand-new profile spends ~10 s creating the WebView2 user-data
        # folder and does not expose the CDP endpoint reliably, so prime it with
        # one throwaway launch before any measurement is recorded.
        log("priming warm profile (throwaway launch, not recorded) ...")
        run_once(spec, timeout=args.timeout, debug_port=args.port,
                 profile_root=warm_root)
        time.sleep(2.0)

    for i in range(args.reps):
        log(f"=== rep {i + 1}/{args.reps} (scenario={args.scenario}, "
            f"profile={args.profile_mode}) ===")
        r = run_once(spec, timeout=args.timeout, debug_port=args.port,
                     profile_root=warm_root)
        status = "ok" if r["ok"] else "FAILED"
        log(f"    {status}  wall={r['wall_sec']}s exit={r['exit_code']} "
            f"to_window_loaded={r['cold_start'].get('to_window_loaded_ms')}ms")
        if not r["ok"]:
            log("    ---- child output tail ----")
            for line in r["stdout_tail"].splitlines()[-30:]:
                log(f"    | {line}")
        runs.append(r)
        time.sleep(2.0)      # let the single-instance mutex fully release

    if args.profile_mode == "warm" and not args.keep_profile:
        shutil.rmtree(warm_root, ignore_errors=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = args.label or f"{args.scenario}-{args.tracks}trk"
    out_file = RESULTS_DIR / f"{label}-{stamp}.json"

    payload = {
        "label": label,
        "scenario": args.scenario,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "command": " ".join([sys.executable, *sys.argv]),
        "args": vars(args),
        "code_fingerprint": prof.tree_fingerprint_short(fingerprint),
        "code_fingerprint_files": fingerprint,
        "aggregate": aggregate(runs),
        "runs": runs,
    }
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {out_file}")

    ok_runs = sum(1 for r in runs if r["ok"])
    log(f"reps ok: {ok_runs}/{len(runs)}")
    med = payload["aggregate"]["medians"]
    for k in sorted(med):
        log(f"  {k} = {med[k]}")
    return 0 if ok_runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
