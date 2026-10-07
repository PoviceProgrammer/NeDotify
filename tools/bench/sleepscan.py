"""Static inventory of every sleep/wait site in the shipped Python code.

Purpose: item 5 of the startup profile asks for "every place where a thread does
``time.sleep`` in a polling loop, and what the interval is, with file:line".
The *measured* wake counts only cover the loops that are alive during the idle
window; this scan covers the whole tree, so nothing is missing.

Read-only: it parses source, never writes it. The measured counts live in
``profile_python_startup.json`` under ``measurement.idle_cpu`` and are joined to
these sites by ``file:line``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"tests", "docs", "ui", "tools", "build", "dist", "__pycache__",
             ".venv_win", ".pytest_cache", ".test_runs", ".git"}


def _literal(node: ast.AST):
    """Return the source-ish literal of an argument, or a short description."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        try:
            return ast.unparse(node)
        except Exception:  # pragma: no cover
            return "<expr>"


def _enclosing(node: ast.AST, parents: dict) -> tuple[str, bool]:
    """(enclosing function name, is inside a ``while`` loop)."""
    fn = "<module>"
    in_while = False
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = cur.name
        elif isinstance(cur, ast.While):
            in_while = True
    return fn, in_while


def scan_file(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        kind = None
        arg = None
        recv = None
        if isinstance(f, ast.Attribute):
            if f.attr == "sleep" and isinstance(f.value, ast.Name) \
                    and f.value.id == "time":
                kind = "time.sleep"
            elif f.attr == "wait":
                kind = "<expr>.wait"
                recv = ast.unparse(f.value)
        if not kind:
            continue
        # ``Event.wait(timeout=1.0)`` passes the timeout by keyword, so look at
        # the keywords too, not only positional args.
        if node.args:
            arg = _literal(node.args[0])
        else:
            kw = next((k for k in node.keywords
                       if k.arg in ("timeout", "seconds", "interval")), None)
            arg = _literal(kw.value) if kw is not None else None
        fn, in_while = _enclosing(node, parents)
        out.append({
            "file": path.resolve().relative_to(REPO_ROOT).as_posix(),
            "line": node.lineno,
            "kind": kind,
            "receiver": recv,
            "interval": arg,
            "inside_while_loop": in_while,
            "enclosing_function": fn,
            "classification": _classify(kind, arg, in_while, path, node.lineno),
        })
    return out


def _classify(kind: str, interval, in_while: bool, path: Path, line: int) -> str:
    """periodic-polling vs bounded-retry vs one-shot."""
    if kind == "time.sleep" and not in_while:
        return "one-shot sleep (no surrounding loop)"
    if kind == "time.sleep" and in_while:
        try:
            sec = float(interval)
        except (TypeError, ValueError):
            return "polling loop, computed interval"
        if sec < 1.0:
            return "polling loop, faster than 1 Hz"
        if sec <= 1.0:
            return "polling loop, 1 Hz"
        return "polling loop, low frequency"
    if kind == "<expr>.wait":
        if interval is None:
            return "event-driven wait (blocks until signalled)"
        try:
            sec = float(interval)
        except (TypeError, ValueError):
            return "event-driven wait, computed timeout"
        if sec < 1.0:
            return "timeout-bounded wait, faster than 1 Hz"
        if sec <= 1.0:
            return "timeout-bounded wait, 1 Hz (wakes on timeout even when idle)"
        return "timeout-bounded wait, low frequency"
    return "other"


def scan(root: Path = REPO_ROOT) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.resolve().relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rows.extend(scan_file(p))
    return rows


def main(argv=None) -> int:
    rows = scan()
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())