"""Validate the desktop test and JavaScript module inventory in source_manifest.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("tools/source_manifest.json")
SCOPES = {
    "desktop_tests": ("tests", "*.py"),
    "desktop_ui_modules": ("ui/web_new_v2/js", "*.js"),
}


def _git_files(root: Path, scope: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", scope],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {line.replace("\\", "/") for line in result.stdout.splitlines() if line}


def validate(root: Path = ROOT, require_tracked: bool = False) -> list[str]:
    """Return actionable diagnostics; an empty list means inventory is complete."""
    manifest_path = root / MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read {MANIFEST.as_posix()}: {exc}"]

    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), dict):
        return [f"{MANIFEST.as_posix()} must have schema_version=1 and a sources object"]

    diagnostics: list[str] = []
    declared_all: set[str] = set()
    for name, (directory, suffix) in SCOPES.items():
        declared = manifest["sources"].get(name)
        if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
            diagnostics.append(f"sources.{name} must be a list of repository-relative paths")
            continue
        normalized = {item.replace("\\", "/") for item in declared}
        if len(normalized) != len(declared):
            diagnostics.append(f"sources.{name} contains duplicate paths")
        declared_all.update(normalized)

        actual = {
            path.relative_to(root).as_posix()
            for path in (root / directory).rglob(f"*{suffix[1:]}")
            if path.is_file()
        } if (root / directory).exists() else set()
        # Use the exact extension and only source files in this owned scope.
        actual = {path for path in actual if path.startswith(directory + "/")}
        for path in sorted(actual - normalized):
            diagnostics.append(f"Unlisted {name} source file: {path}")
        for path in sorted(normalized - actual):
            diagnostics.append(f"Manifest path is missing from checkout: {path}")

        if require_tracked:
            try:
                tracked = _git_files(root, directory)
            except (OSError, subprocess.CalledProcessError) as exc:
                diagnostics.append(f"Cannot read tracked paths with git ls-files in {root}: {exc}")
                continue
            for path in sorted(actual - tracked):
                diagnostics.append(f"Untracked source file (refusing CI inventory): {path}")

    # A path listed under both scopes is almost certainly a manifest mistake.
    if len(declared_all) != sum(
        len(set(str(item).replace("\\", "/") for item in values))
        for values in manifest["sources"].values()
        if isinstance(values, list)
    ):
        diagnostics.append("A source path appears in more than one inventory scope")
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-tracked", action="store_true",
                        help="reject source files that git ls-files does not report")
    parser.add_argument("--root", type=Path, default=ROOT,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    errors = validate(args.root.resolve(), require_tracked=args.require_tracked)
    if errors:
        print("Source inventory check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("Source inventory is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
