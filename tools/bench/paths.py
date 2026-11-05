"""Shared destinations for generated benchmark and visual-guard artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def results_dir() -> Path:
    """Return the explicit benchmark output path or a temp-directory default."""
    configured = os.environ.get("NEDOTIFY_BENCH_OUT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "NeDotify" / "bench" / "results"


def visual_artifacts_dir() -> Path:
    """Return the explicit visual artifact path or a temp-directory default."""
    configured = os.environ.get("NEDOTIFY_VISUAL_GUARD_OUT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "NeDotify" / "visual_guard"
