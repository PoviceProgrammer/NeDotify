"""Fail-closed validation for optional native bundle directories."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


MANIFEST = Path(__file__).with_name("native_dependencies.json")


def is_valid_pe(path: Path) -> bool:
    """Check enough of the PE structure to reject placeholders and truncation."""
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return False
            stream.seek(0x3C)
            offset_data = stream.read(4)
            if len(offset_data) != 4:
                return False
            pe_offset = int.from_bytes(offset_data, "little")
            if pe_offset < 64 or pe_offset > path.stat().st_size - 24:
                return False
            stream.seek(pe_offset)
            return stream.read(4) == b"PE\0\0"
    except OSError:
        return False


def validate_native_inputs(root: str | Path, *, release_mode: bool = False,
                           manifest_path: str | Path = MANIFEST) -> list[tuple[str, str]]:
    """Return PyInstaller data mappings, rejecting partial native directories.

    The directories are optional for source/debug builds. If one exists, it
    must include one of its declared runnable PE entrypoints. Release mode
    additionally requires at least one native entrypoint across all groups.
    """
    base = Path(root).resolve()
    manifest: dict[str, Any] = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("schema") != "nedotify.native-dependencies.v1":
        raise ValueError("unsupported native-dependency manifest schema")

    mapped: list[tuple[str, str]] = []
    found_entrypoint = False
    for group in manifest.get("directories", []):
        source_name = str(group.get("source", ""))
        destination = str(group.get("destination", ""))
        if not source_name or Path(source_name).is_absolute() or ".." in Path(source_name).parts:
            raise ValueError(f"unsafe native dependency source: {source_name!r}")
        folder = (base / source_name).resolve()
        if base not in folder.parents:
            raise ValueError(f"native dependency source escapes root: {source_name!r}")
        if not folder.exists():
            continue
        if not folder.is_dir():
            raise ValueError(f"native dependency path is not a directory: {folder}")
        entrypoints = [folder / name for name in group.get("entrypoints", [])]
        valid = [path for path in entrypoints if path.is_file() and is_valid_pe(path)]
        if not valid:
            raise ValueError(
                f"native dependency directory {source_name!r} exists but has no valid "
                f"entrypoint ({', '.join(map(str, entrypoints))})")
        found_entrypoint = True
        mapped.append((str(folder), destination))

    if release_mode and not found_entrypoint:
        raise ValueError(
            "release packaging requires a valid winws.exe or zapret.exe under "
            "zapret/ or bin/; prepare the external native bundle first")
    return mapped


def release_mode_from_environment() -> bool:
    return os.environ.get("NEDOTIFY_RELEASE_BUILD", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
