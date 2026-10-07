"""Query a ``.pstats`` file produced by ``pyprof_child.py appcore_cprofile``.

``pstats.Stats.print_*`` renders to stdout with ANSI escapes and Windows console
codepages mangling the non-ASCII path segments, so this reads the stats dict
directly and prints stable, quotable numbers.
"""

from __future__ import annotations

import argparse
import json
import pstats
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"


def rel(path: str) -> str:
    if path == "~":
        return "<builtin>"
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pstats", default=str(RESULTS / "profile_appcore_init.pstats"))
    ap.add_argument("--match", nargs="*", default=[],
                    help="substring filters applied to 'file:line(func)'")
    ap.add_argument("--top", type=int, default=0, help="also list the N heaviest")
    ap.add_argument("--callers-of", default=None,
                    help="print the callers of the first frame matching this substring")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    st = pstats.Stats(args.pstats)
    rows = []
    for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
        rows.append({"at": f"{rel(fn)}:{ln}({name})", "file": rel(fn), "line": ln,
                     "func": name, "ncalls": nc,
                     "tottime_ms": round(tt * 1000, 4),
                     "cumtime_ms": round(ct * 1000, 4),
                     "_callers": callers})

    if args.callers_of:
        needle = args.callers_of
        for r in sorted(rows, key=lambda r: -r["cumtime_ms"]):
            if needle in r["at"]:
                print(f"{r['at']}  cum={r['cumtime_ms']}ms  ncalls={r['ncalls']}")
                for (cf, cl, cn), (cn2, _cc, _tt, cct) in sorted(
                        r["_callers"].items(), key=lambda kv: -kv[1][3]):
                    print(f"    <- {rel(cf)}:{cl}({cn})  x{cn2}  cum={cct*1000:.3f}ms")
                break
        return 0

    if args.match:
        rows = [r for r in rows if any(m in r["at"] for m in args.match)]

    rows.sort(key=lambda r: -r["cumtime_ms"])
    if args.top:
        rows = rows[:args.top]
    for r in rows:
        r.pop("_callers", None)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"cum={r['cumtime_ms']:9.3f}ms self={r['tottime_ms']:9.3f}ms "
                  f"n={r['ncalls']:<6} {r['at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())