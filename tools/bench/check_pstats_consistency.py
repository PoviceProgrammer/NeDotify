"""Sanity-check the cProfile bookkeeping in profile_appcore_init.pstats.

cProfile rows carry ``(cc, ncalls, tottime, cumtime, callers)``. If a parent's
``cumtime`` is smaller than a child's, the linkage is broken and the parent row
must not be used as evidence. This prints exactly those inconsistencies.
"""

from __future__ import annotations

import pstats
from pathlib import Path

PSTATS = Path(__file__).resolve().parent / "results" / "profile_appcore_init.pstats"


def main() -> int:
    st = pstats.Stats(str(PSTATS))
    rows = {}
    for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
        rows[f"{Path(fn).name}:{ln}({name})"] = {
            "ncalls": nc, "tottime": tt, "cumtime": ct,
            "children_cum": sum(v[3] for v in callers.values()),
            "callers": {f"{Path(cf).name}:{cl}({cn})": v[0]
                        for (cf, cl, cn), v in callers.items()},
        }
    bad = []
    for key, r in rows.items():
        if r["children_cum"] > r["cumtime"] * 1.5 + 1e-9 and r["children_cum"] > 1e-4:
            bad.append((key, r))
    print(f"rows: {len(rows)}   inconsistent (children_cum >> cumtime): {len(bad)}")
    for key, r in sorted(bad, key=lambda kv: -kv[1]["children_cum"])[:15]:
        print(f"  {key:52} ncalls={r['ncalls']:<4} cumtime={r['cumtime']*1000:8.3f}ms "
              f"children_cum={r['children_cum']*1000:8.3f}ms")
    print("\nspecific rows:")
    for key in ("app.py:93(__init__)", "app.py:46(update_ytdlp_safely)",
                "database.py:79(__init__)", "youtube_service.py:114(__init__)",
                "youtube_service.py:171(_get_ydl)", "api.py:68(_connect)"):
        if key in rows:
            r = rows[key]
            print(f"  {key:44} ncalls={r['ncalls']:<4} self={r['tottime']*1000:8.3f}ms "
                  f"cum={r['cumtime']*1000:8.3f}ms children={r['children_cum']*1000:8.3f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())