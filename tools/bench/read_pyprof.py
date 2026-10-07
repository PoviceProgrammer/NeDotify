"""Read ``profile_python_startup.json`` and print the numbers used in the report.

Kept separate from ``run_pyprof.py`` so the report can be re-derived from the
stored JSON without re-running (and re-timing) anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default=str(RESULTS / "profile_python_startup.json"))
    ap.add_argument("--section", default="all")
    args = ap.parse_args(argv)
    d = json.loads(Path(args.json).read_text(encoding="utf-8"))
    m = d["measurement"]
    sec = args.section

    def show(title, obj):
        if sec not in ("all", title):
            return
        print("=" * 78)
        print(title.upper())
        print("=" * 78)
        print(json.dumps(obj, ensure_ascii=False, indent=2))

    show("interpreter", {
        k: v for k, v in m["interpreter_and_imports"].items()
        if k not in ("representative_breakdown", "per_run_breakdown")
    })
    show("imports", m["interpreter_and_imports"]["representative_breakdown"])
    show("appcore_init", m["appcore_init"])
    show("cprofile", m["appcore_cprofile"])
    show("breakdown", m["appcore_breakdown"])
    show("idle", m["idle_cpu"])
    show("pyspy", {"pyspy": m.get("pyspy"), "summary": m.get("pyspy_summary")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())