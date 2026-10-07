"""Pixel diff for the NeDotify visual guard.

Tolerance: <= 0.1% of differing pixels, i.e. at 1280x800x1 that is ~1024 pixels.
Anything above is reported together with a side-by-side and an amplified diff
image so a human can look at it - the task explicitly requires eyeballing
differences, not trusting the number alone.

Anti-aliasing tolerance: a channel delta of <= 2/255 counts as equal, because
GPU rasterisation of the same content can differ by a hair between runs. This
tolerance is applied identically to the golden run and to every later run, so
it cannot mask a real regression.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

CHANNEL_TOLERANCE = 2       # per-channel 0..255 slack for raster jitter
DIFF_PIXEL_RATIO_LIMIT = 0.001


def load_rgb(path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.int16)


def compare_png(golden_path, current_path) -> dict:
    g = load_rgb(golden_path)
    c = load_rgb(current_path)

    if g.shape != c.shape:
        return {
            "ok": False,
            "reason": "size_mismatch",
            "golden_size": [int(x) for x in g.shape[:2]],
            "current_size": [int(x) for x in c.shape[:2]],
            "diff_ratio": 1.0,
        }

    delta = np.abs(g - c)
    per_pixel = delta.max(axis=2)
    diff_mask = per_pixel > CHANNEL_TOLERANCE
    n_diff = int(diff_mask.sum())
    total = int(diff_mask.size)
    ratio = n_diff / total if total else 0.0

    # bounding box of the change, so the report can point at a region
    bbox = None
    if n_diff:
        rows = np.where(diff_mask.any(axis=1))[0]
        cols = np.where(diff_mask.any(axis=0))[0]
        bbox = [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1]

    return {
        "ok": ratio <= DIFF_PIXEL_RATIO_LIMIT,
        "diff_pixels": n_diff,
        "total_pixels": total,
        "diff_ratio": round(ratio, 6),
        "diff_percent": round(ratio * 100, 4),
        "max_channel_delta": int(per_pixel.max()) if total else 0,
        "mean_channel_delta": round(float(delta.mean()), 3) if total else 0.0,
        "bbox_xyxy": bbox,
        "tolerance": {
            "channel": CHANNEL_TOLERANCE,
            "pixel_ratio": DIFF_PIXEL_RATIO_LIMIT,
        },
    }


def write_diff_artifacts(golden_path, current_path, out_dir: Path,
                         amplified: int = 6) -> tuple[Path, Path]:
    """Write `name__side.png` (golden|current) and `name__diff.png` (hot)."""
    g = load_rgb(golden_path).astype(np.int16)
    c = load_rgb(current_path).astype(np.int16)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    side = np.concatenate([g, c], axis=1).clip(0, 255).astype(np.uint8)
    side_path = out_dir / f"{Path(golden_path).stem}__side.png"
    Image.fromarray(side).save(side_path)

    delta = np.abs(g - c).max(axis=2)
    hot = (delta > CHANNEL_TOLERANCE).astype(np.uint8) * 255
    hot = np.clip(hot.astype(np.int16) * amplified, 0, 255).astype(np.uint8)
    diff_path = out_dir / f"{Path(golden_path).stem}__diff.png"
    Image.fromarray(np.stack([hot] * 3, axis=2)).save(diff_path)
    return side_path, diff_path


def compare_sets(golden_dir, current_dir, out_dir=None,
                 limit: float = DIFF_PIXEL_RATIO_LIMIT) -> dict:
    golden_dir, current_dir = Path(golden_dir), Path(current_dir)
    out_dir = Path(out_dir) if out_dir else current_dir / "_diff"

    goldens = {p.name: p for p in sorted(golden_dir.glob("*.png"))}
    currents = {p.name: p for p in sorted(current_dir.glob("*.png"))}

    missing = sorted(set(goldens) - set(currents))
    extra = sorted(set(currents) - set(goldens))

    results = []
    for name in sorted(set(goldens) & set(currents)):
        res = compare_png(goldens[name], currents[name])
        res["name"] = name
        if not res["ok"] and out_dir:
            side, diff = write_diff_artifacts(goldens[name], currents[name], out_dir)
            res["artifacts"] = {"side_by_side": side.name, "diff": diff.name}
        results.append(res)

    failures = [r for r in results if not r["ok"]]
    return {
        "ok": not failures and not missing,
        "tolerance_pixel_ratio": limit,
        "channel_tolerance": CHANNEL_TOLERANCE,
        "compared": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "missing": missing,
        "unexpected": extra,
        "failures": failures,
        "worst": sorted(results, key=lambda r: -r.get("diff_ratio", 0))[:10],
    }
