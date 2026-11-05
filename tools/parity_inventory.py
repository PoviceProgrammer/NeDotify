"""Audit the *working tree* of the Windows desktop reference without modifying it."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

PRODUCT_DIRS = ("core", "audio", "services", "utils", "plugins", "ui/web_new_v2", "ui/MACos_ui")
EXCLUDED = {"__pycache__", "covers", ".git", "node_modules"}


def product_files(root):
    for name in ("main.py", "icon.png", "logo.png", "cover.png", "LICENSE"):
        path = root / name
        if path.is_file():
            yield path
    for folder in PRODUCT_DIRS:
        for path in sorted((root / folder).rglob("*")):
            rel = path.relative_to(root)
            if not path.is_file() or any(part in EXCLUDED for part in rel.parts):
                continue
            if path.suffix.lower() in {".pyc", ".exe", ".dll", ".db", ".log"}:
                continue
            yield path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def symbols(path):
    if path.suffix != ".py":
        return []
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(node.name)
        elif isinstance(node, ast.ClassDef):
            result.append(node.name)
            result.extend(node.name + "." + method.name for method in node.body
                          if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return result


def inventory(source, target):
    rows = []
    for path in product_files(source):
        relative = path.relative_to(source).as_posix()
        digest = sha(path)
        target_digest = sha(target / relative)
        rows.append({"path": relative, "source_sha256": digest, "linux_sha256": target_digest,
                     "status": "identical" if digest == target_digest else "adapted" if target_digest else "missing",
                     "symbols": symbols(path)})
    git = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"],
                         cwd=source, text=True, encoding="utf-8", errors="replace", capture_output=True)
    return {"source": str(source), "target": str(target), "source_git_status": git.stdout.splitlines(),
            "scope": list(PRODUCT_DIRS), "files": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.source.resolve(), args.target.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {state: sum(row["status"] == state for row in report["files"])
              for state in ("identical", "adapted", "missing")}
    print(json.dumps(counts))
    return bool(counts["missing"])


if __name__ == "__main__":
    raise SystemExit(main())
