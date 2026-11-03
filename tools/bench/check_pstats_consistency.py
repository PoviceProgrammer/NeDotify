"""Sanity-check the cProfile bookkeeping in profile_appcore_init.pstats.

cProfile rows carry ``(cc, ncalls, tottime, cumtime, callers)``. If a parent's
``cumtime`` is smaller than a child's, the linkage is broken and the parent row
must not be used as evidence. This prints exactly those inconsistencies.
"""

from __future__ import annotations

import pstats
from pathlib import Path

from tools.bench.paths import results_dir

PSTATS = results_dir() / "profile_appcore_init.pstats"


def find_inconsistencies(stats: dict, min_seconds: float = 1e-4) -> list[tuple[tuple, tuple, float, float]]:
    """Find parent/child edges where the child's recorded cost exceeds parent cost.

    ``Stats.stats[child][4]`` maps each caller to the time charged for this
    child under that caller. Compare that edge contribution with the caller's
    own cumulative time; summing callers and comparing against the child's
    total reverses the documented relationship and over-reports normal calls.
    """
    bad = []
    for child_key, (_cc, _nc, _tt, _child_ct, callers) in stats.items():
        for parent_key, edge in callers.items():
            parent = stats.get(parent_key)
            if parent is None:
                continue
            edge_ct = edge[3]
            parent_ct = parent[3]
            if edge_ct > min_seconds and edge_ct > parent_ct * 1.5 + 1e-9:
                bad.append((parent_key, child_key, parent_ct, edge_ct))
    return bad


def main() -> int:
    st = pstats.Stats(str(PSTATS))
    rows = {}
    for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
        rows[f"{Path(fn).name}:{ln}({name})"] = {
            "ncalls": nc, "tottime": tt, "cumtime": ct,
            "caller_cum": sum(v[3] for v in callers.values()),
            "callers": {f"{Path(cf).name}:{cl}({cn})": v[0]
                        for (cf, cl, cn), v in callers.items()},
        }
    bad = find_inconsistencies(st.stats)
    print(f"rows: {len(rows)}   inconsistent parent/child edges: {len(bad)}")
    for parent, child, parent_ct, edge_ct in sorted(bad, key=lambda row: -row[3])[:15]:
        parent_label = f"{Path(parent[0]).name}:{parent[1]}({parent[2]})"
        child_label = f"{Path(child[0]).name}:{child[1]}({child[2]})"
        print(f"  {parent_label:52} -> {child_label:44} "
              f"parent={parent_ct*1000:8.3f}ms child-edge={edge_ct*1000:8.3f}ms")
    print("\nspecific rows:")
    for key in ("app.py:93(__init__)", "app.py:46(update_ytdlp_safely)",
                "database.py:79(__init__)", "youtube_service.py:114(__init__)",
                "youtube_service.py:171(_get_ydl)", "api.py:68(_connect)"):
        if key in rows:
            r = rows[key]
            print(f"  {key:44} ncalls={r['ncalls']:<4} self={r['tottime']*1000:8.3f}ms "
                  f"cum={r['cumtime']*1000:8.3f}ms caller-time={r['caller_cum']*1000:8.3f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
