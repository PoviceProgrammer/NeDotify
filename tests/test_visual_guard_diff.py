"""Self-tests for the visual guard's diff engine.

The guard's whole value rests on its tolerance arithmetic. If ``compare_png``
accepts too much, real regressions pass; too little and every run is noise.
These tests pin the boundary behaviour with synthetic images, so a future
refactor of the tolerance cannot silently widen or narrow the contract.

They do not need the GUI, the app, or a browser.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.visual_guard import diff as vg_diff  # noqa: E402


def _write(tmp_path: Path, name: str, arr: np.ndarray) -> Path:
    p = tmp_path / name
    Image.fromarray(arr.astype(np.uint8)).save(p)
    return p


@pytest.fixture
def base() -> np.ndarray:
    rng = np.random.default_rng(1234)
    return rng.integers(0, 255, size=(800, 1280, 3), dtype=np.uint8)


def test_identical_images_have_zero_diff(tmp_path, base):
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", base.copy())
    res = vg_diff.compare_png(a, b)
    assert res["diff_pixels"] == 0
    assert res["diff_ratio"] == 0.0
    assert res["ok"] is True
    assert res["bbox_xyxy"] is None


def test_jitter_within_channel_tolerance_is_ignored(tmp_path, base):
    """Raster jitter of <= CHANNEL_TOLERANCE must not count as a diff."""
    noisy = base.astype(np.int16).copy()
    noisy[0, 0] = np.clip(noisy[0, 0] + vg_diff.CHANNEL_TOLERANCE, 0, 255)
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", noisy)
    res = vg_diff.compare_png(a, b)
    assert res["diff_pixels"] == 0
    assert res["ok"] is True


def test_single_pixel_change_is_caught(tmp_path, base):
    changed = base.copy()
    changed[400, 600] = (0, 0, 0)
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", changed)
    res = vg_diff.compare_png(a, b)
    assert res["diff_pixels"] == 1
    assert res["ok"] is True          # 1 px of 1,024,000 is far under 0.1%
    assert res["bbox_xyxy"] == [600, 400, 601, 401]


def test_beyond_pixel_ratio_limit_fails(tmp_path):
    """Just over 0.1% of pixels changed must fail."""
    h, w = 200, 200                      # 40 000 px; 0.1% = 40 px
    base = np.zeros((h, w, 3), dtype=np.uint8)
    changed = base.copy()
    n = 41                               # one pixel over the limit
    changed.reshape(-1, 3)[:n] = 255
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", changed)
    res = vg_diff.compare_png(a, b)
    assert res["diff_pixels"] == n
    assert res["diff_ratio"] > vg_diff.DIFF_PIXEL_RATIO_LIMIT
    assert res["ok"] is False


def test_exactly_at_pixel_ratio_limit_passes(tmp_path):
    h, w = 200, 200
    base = np.zeros((h, w, 3), dtype=np.uint8)
    changed = base.copy()
    n = int(h * w * vg_diff.DIFF_PIXEL_RATIO_LIMIT)   # exactly 40
    changed.reshape(-1, 3)[:n] = 255
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", changed)
    res = vg_diff.compare_png(a, b)
    assert res["diff_pixels"] == n
    assert res["ok"] is True


def test_size_mismatch_fails_loudly(tmp_path, base):
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", base[:400])
    res = vg_diff.compare_png(a, b)
    assert res["ok"] is False
    assert res["reason"] == "size_mismatch"
    assert res["diff_ratio"] == 1.0


def test_diff_artifacts_are_written(tmp_path, base):
    changed = base.copy()
    changed[0:50, 0:50] = 255
    a = _write(tmp_path, "a.png", base)
    b = _write(tmp_path, "b.png", changed)
    out = tmp_path / "_diff"
    side, diff = vg_diff.write_diff_artifacts(a, b, out)
    assert side.exists() and diff.exists()
    with Image.open(side) as im:
        assert im.size == (1280 * 2, 800)          # golden | current
    with Image.open(diff) as im:
        assert im.size == (1280, 800)


def test_compare_sets_reports_missing_and_unexpected(tmp_path):
    gdir, cdir = tmp_path / "goldens", tmp_path / "current"
    gdir.mkdir(); cdir.mkdir()
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    _write(gdir, "kept.png", img)
    _write(gdir, "vanished.png", img)
    _write(cdir, "kept.png", img)
    _write(cdir, "brand_new.png", img)
    res = vg_diff.compare_sets(gdir, cdir)
    assert res["compared"] == 1
    assert res["missing"] == ["vanished.png"]
    assert res["unexpected"] == ["brand_new.png"]
    assert res["ok"] is False
