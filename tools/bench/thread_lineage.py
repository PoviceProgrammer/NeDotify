"""Which core/app.py line creates each thread during AppCore construction.

``AppCore.__init__`` starts ~10 threads, most with the default
``Thread-N`` name, so the thread list alone does not say who created what.
This patches ``threading.Thread.__init__`` in the child process only (no
project file is touched), builds ``AppCore``, and prints the creator
``file:line`` + target for every thread, in creation order, followed by which
of them are still alive.

Headless: it never touches ``webview.start()``.

    python tools/bench/thread_lineage.py <scratch_profile_dir>
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def redirect(profile_root: str) -> None:
    p = Path(profile_root)
    p.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(p)
    os.environ["HOMEDRIVE"] = ""
    os.environ["HOMEPATH"] = ""
    expanded = os.path.expanduser("~")
    if Path(expanded).resolve() != p.resolve():
        raise SystemExit(f"profile redirect failed: {expanded!r}")


def _rel(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise SystemExit(__doc__)
    redirect(argv[0])
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    created: list[dict] = []
    orig_init = threading.Thread.__init__

    def patched(self, group=None, target=None, name=None, args=(), kwargs=None,
                *, daemon=None):
        f = sys._getframe(1)
        created.append({
            "order": len(created) + 1,
            "assigned_name": name,
            "target": getattr(target, "__qualname__", None),
            "creator": f"{_rel(f.f_code.co_filename)}:{f.f_lineno}",
            "creator_target_qualname": getattr(
                f.f_locals.get("self"), "__class__", object).__name__
            if f.f_locals.get("self") is not None else None,
        })
        return orig_init(self, group, target, name, args, kwargs, daemon=daemon)

    threading.Thread.__init__ = patched

    import core.app as app_mod  # noqa: E402

    core = app_mod.AppCore()  # noqa: F841
    alive = sorted(t.name for t in threading.enumerate())
    threading.Thread.__init__ = orig_init

    print(json.dumps({
        "profile": argv[0],
        "n_created": len(created),
        "created_in_order": created,
        "alive_after_construction": alive,
        "n_alive": len(alive),
        "gui_launched": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())