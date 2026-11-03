"""Exercise snapshot membership and task restrictions in real PowerShell."""

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest


POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
ANDROID = Path(__file__).resolve().parents[1] / "android"
pytestmark = [
    pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable"),
    pytest.mark.skipif(not ANDROID.is_dir(), reason="Android product tree is not present"),
]


def run_script(command):
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )


def quoted(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.mark.parametrize("mutation,expected", [
    # The four kinds of drift the snapshot reports. The messages are the ones
    # tools/SourceSnapshot.ps1 prints today; the detection must fail the gate
    # in every case, so the return code is asserted separately below.
    ("new", "New ("),
    ("change", "Changed ("),
    ("remove", "Removed ("),
    ("unlisted", "No longer a source, but still on disk ("),
])
def test_snapshot_rejects_membership_and_content_drift(tmp_path, mutation, expected):
    source = tmp_path / "app" / "build.gradle"
    source.parent.mkdir()
    source.write_text("// baseline\n")
    (tmp_path / "review").mkdir()
    common = quoted(ANDROID / "tools" / "SourceSnapshot.ps1")
    root = quoted(tmp_path)
    create = run_script(f"$ErrorActionPreference='Stop'; . {common}; Write-ReviewSnapshot {root}; Test-ReviewSnapshot {root}")
    assert create.returncode == 0, create.stdout + create.stderr
    if mutation == "new":
        (source.parent / "new.kt").write_text("// new source\n")
    elif mutation == "change":
        source.write_text("// different source\n")
    elif mutation == "remove":
        source.unlink()
    else:
        # A file that the manifest names but that is no longer a source under
        # the current rules (the manifest was written with a broader rule
        # set). The file is still on disk, so it is "unlisted", not "removed".
        # The extension must be one the rule set does not cover.
        note = tmp_path / "notes.bin"
        note.write_bytes(b"// history\n")
        digest = hashlib.sha256(note.read_bytes()).hexdigest()
        with (tmp_path / "review" / "SOURCE_SHA256.txt").open("a", encoding="ascii") as handle:
            handle.write(f"{digest}  notes.bin\n")
    result = run_script(f"$ErrorActionPreference='Stop'; . {common}; Test-ReviewSnapshot {root}")
    assert result.returncode != 0
    assert expected in result.stdout + result.stderr
    # The report must name the file that drifted, not only the count.
    named = {"new": "new.kt", "change": "build.gradle", "remove": "build.gradle",
             "unlisted": "notes.bin"}[mutation]
    assert named in result.stdout + result.stderr


@pytest.mark.parametrize("task", [":app:assembleDebug", ":app:connectedDebugAndroidTest", ":app:aD", "--init-script"])
def test_source_gate_rejects_packaging_device_abbreviations_and_options(task):
    common = quoted(ANDROID / "tools" / "SourceTasks.ps1")
    result = run_script(f"$ErrorActionPreference='Stop'; . {common}; Assert-SourceTasks @('{task}')")
    assert result.returncode != 0
    assert "outside the source-only gate" in result.stdout + result.stderr
