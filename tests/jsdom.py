"""Shared Node execution helpers for DOM and bridge tests."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


JS_DIR = Path(__file__).resolve().parents[1] / "ui" / "web_new_v2" / "js"


def run_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; JavaScript harness not executed")
    result = subprocess.run(
        [node, "--input-type=module"], input=script,
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def source(filename):
    return json.dumps((JS_DIR / filename).read_text(encoding="utf-8"))
