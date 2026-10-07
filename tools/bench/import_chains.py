"""Print the import-tree ancestry chains for a few modules.

Answers "why is this module expensive / who pulls it in" straight from the
-X importtime tree that ``measure_interpreter`` produced.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pyprof as R  # noqa: E402

TARGETS = [
    "_colorize", "traceback", "dataclasses", "inspect", "re", "logging",
    "logging.handlers", "main", "core.app", "webview", "webview.http",
    "wsgiref.simple_server", "http.server", "ssl", "bottle",
    "services.vk_service", "yt_dlp", "yt_dlp.extractor", "yt_dlp.cookies",
    "services.spotify_service", "requests", "services.youtube_service",
    "ytmusicapi", "ytmusicapi.ytmusic", "services.lyrics_service",
    "mutagen", "pypresence", "asyncio", "charset_normalizer", "socket",
]


def main() -> int:
    p = R.fresh_profile("chain")
    proc, _ = R.run([R.PY, "-X", "importtime", "-c", "import main"],
                    R.child_env(p))
    rows = R.parse_importtime(proc.stderr.decode("utf-8", "replace"))
    R._link_parents(rows)
    byname = {}
    for i, r in enumerate(rows):
        byname.setdefault(r["name"], i)

    def chain(n):
        i = byname.get(n)
        if i is None:
            return "<not imported>"
        out = []
        while i is not None:
            out.append(f"{rows[i]['name']}({rows[i]['cum_us'] / 1000:.1f})")
            i = rows[i]["parent"]
        return " <- ".join(out)

    for n in TARGETS:
        print(f"{n}:\n    {chain(n)}")

    ext = [r for r in rows if r["name"].startswith("yt_dlp.extractor")]
    print(f"\nyt_dlp.extractor.* modules imported: {len(ext)}")
    print(f"yt_dlp.extractor.* total self: "
          f"{sum(r['self_us'] for r in ext) / 1000:.1f} ms")
    print(f"yt_dlp.* total self: "
          f"{sum(r['self_us'] for r in rows if r['name'].startswith('yt_dlp')) / 1000:.1f} ms")
    print(f"all modules: {len(rows)}  sum self: "
          f"{sum(r['self_us'] for r in rows) / 1000:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())