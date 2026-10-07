"""Single-command entry point for the NeDotify visual guard.

    python tools/visual_guard/run_guard.py --capture     # (re)build goldens
    python tools/visual_guard/run_guard.py --compare     # guard current tree
    python tools/visual_guard/run_guard.py --all         # capture if absent, then compare
    python tools/visual_guard/run_guard.py --write-css-baseline  # re-record the
                                              # guarded declarations of the current tree

Two independent checks run together:

1. PIXELS - goldens vs current, <= 0.1% differing pixels, with side-by-side
   and amplified-diff artifacts for anything that fails so a human can look.
2. CSS DECLARATIONS - every transition/animation/backdrop-filter/filter
   literal plus every custom property that feeds one, recorded in
   ``tools/bench/results/animation_declarations.json`` and diffed against the
   current tree by (file, property, value). This is what catches a changed blur
   radius or easing curve that happens to affect few pixels. A declaration that
   changed or disappeared fails; one that was added is reported but allowed
   (see the block comment above ``css_declaration_guard``).

Both must pass. Exit code 0 only if everything passes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.bench import profile as prof  # noqa: E402
from tools.visual_guard import diff as vg_diff  # noqa: E402
from tools.visual_guard import fixtures as vg_fixtures  # noqa: E402

GUARD_DIR = Path(__file__).resolve().parent
GOLDENS = GUARD_DIR / "goldens"
CURRENT = GUARD_DIR / "current"
REPORTS = GUARD_DIR / "reports"
PYTHON = REPO_ROOT / ".venv_win" / "Scripts" / "python.exe"
CHILD = REPO_ROOT / "tools" / "bench" / "bench_child.py"
ANIM_DECLS = REPO_ROOT / "tools" / "bench" / "results" / "animation_declarations.json"


def log(msg: str) -> None:
    print(f"[guard] {msg}", flush=True)


# --------------------------------------------------------------------------
def _ensure_single_instance_free() -> bool:
    """NeDotify uses a named mutex; a second launch exits immediately."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    h = k.CreateMutexW(None, False, r"Local\NeDotify_App_Single_Instance_Mutex")
    if h and k.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(h)
        return False
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
    return True


def _launch(spec: dict, theme_name: str, profile_root: Path,
            port: int, timeout: float = 900.0) -> dict:
    covers = prof.write_covers(profile_root)
    theme = vg_fixtures.THEMES[theme_name]
    seed = prof.seed_db(Path(profile_root) / ".nedotify" / "nedotify_storage.db",
                        prof.make_track_specs(spec.get("tracks", 200)),
                        covers, history_per_track=0,
                        settings=theme["settings"])

    spec = dict(spec)
    spec["profile_root"] = str(profile_root)
    spec["theme"] = theme_name
    spec_file = profile_root / "bench_spec.json"
    results_file = profile_root / "bench_results.json"
    spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")

    env = prof.child_env(profile_root, debug_port=port)
    env["NEDOTIFY_BENCH_SPEC"] = str(spec_file)
    env["NEDOTIFY_BENCH_RESULTS"] = str(results_file)
    env["NEDOTIFY_BENCH_PORT"] = str(port)
    env["NEDOTIFY_BENCH_MODE"] = "capture"

    proc = subprocess.Popen([str(PYTHON), str(CHILD)], cwd=str(REPO_ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        out += "\n[guard] TIMEOUT"
    payload = {}
    if results_file.exists():
        try:
            payload = json.loads(results_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"exit_code": proc.returncode, "seed": seed, "child": payload,
            "stdout_tail": (out or "")[-3000:]}


def capture(out_dir: Path, themes: list[str], screens: list[str],
            tracks: int, port: int, viewports, dprs) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for theme_name in themes:
        if not _ensure_single_instance_free():
            raise RuntimeError(
                "A NeDotify instance is already running (single-instance mutex "
                "Local\\NeDotify_App_Single_Instance_Mutex is held). Close it "
                "and re-run; the guard cannot run two windows at once.")
        log(f"capturing theme '{theme_name}' ...")
        profile_root = prof.make_scratch_profile(prefix=f"guard-{theme_name}-")
        try:
            spec = {"scenario": "capture", "out_dir": str(out_dir),
                    "screens": screens, "viewports": [list(v) for v in viewports],
                    "dprs": dprs, "tracks": tracks, "settle_sec": 2.0}
            r = _launch(spec, theme_name, profile_root, port)
            summary[theme_name] = r
            n = len(list(out_dir.glob(f"{theme_name}__*.png")))
            log(f"  theme '{theme_name}': exit={r['exit_code']} files={n}")
            if r["exit_code"] != 0 or not n:
                for line in r["stdout_tail"].splitlines()[-25:]:
                    log(f"  | {line}")
        finally:
            shutil.rmtree(profile_root, ignore_errors=True)
        time.sleep(2.0)
    return summary


# --------------------------------------------------------------------------
# The CSS-declaration half of the visual contract.
#
# Two classes of declaration are guarded:
#
#   1. transition / animation / backdrop-filter / filter *literals*. This is
#      what catches a changed easing curve or a changed blur radius written
#      inline in a rule.
#   2. The CSS custom properties those rules *consume* - `--blur-*`,
#      `--glass-blur`, `--app-bg-opacity`, `--player-glow-*` and friends.
#
# Class 2 exists because of a real gap found while building this guard: rules
# are written as ``backdrop-filter: blur(var(--blur-md))``. Recording only the
# literal text would show no diff if someone changed ``--blur-md` in tokens.css,
# yet the rendered radius on screen would change - precisely the thing the
# visual contract forbids. So the *definitions* of any custom property
# referenced by a guarded value are guarded as well.
#
# KEYING - why this is `file|property` and not `file:line:text`
# --------------------------------------------------------------
# The original implementation keyed each declaration as
# ``f"{rel}:{i}:{text}"`` with ``i`` the 1-based line number, and computed
# ``ok`` from ``base_keys & cur_keys`` alone. Both halves of that are broken:
#
#   * Inserting or deleting one blank line shifts every later line number, so
#     every later key changes and the intersection collapses to the empty set.
#   * ``changed`` was derived only from the intersection, and ``removed`` /
#     ``added`` never influenced ``ok``. An empty intersection therefore meant
#     ``changed == []`` and ``ok is True`` - the guard passed *vacuously* on a
#     tree that had no intersection at all with its own baseline. Measured on a
#     clean tree: baseline 296 / current 745 / intersection 0 / ok True.
#
# So declarations are keyed by CONTENT: ``"<relative/file>|<property>"`` with
# the normalised value(s) kept in a LIST under that key. Using a list per key
# (rather than a positional discriminator like a line number or an occurrence
# index) is the deliberate choice: an occurrence index is derived from position
# and would re-introduce exactly the shift bug for the second and later
# declarations of the same property in one file. A multiset of values is
# position-independent, so reordering declarations inside a file - or moving
# them - is correctly seen as "no visual change", while deleting one of two
# identical `transition` declarations in the same file is correctly seen as a
# removal. Line numbers are not recorded in the baseline at all: they are
# exactly what used to break this comparison, and re-recording them on every
# unrelated edit would guarantee drift between the baseline and the tree.
#
# SEMANTICS
# ---------
# A declaration is identified by its (file, property, value) triple, so the
# comparison runs per value inside a key, not per key:
#
#   changed - under one file+property, a baseline value went away AND a new
#             value arrived: an existing declaration was retuned.
#             REGRESSION -> fails.
#   removed - a baseline value no longer exists (its whole key vanished, or it
#             was substituted).                       REGRESSION -> fails.
#   added   - a value that is new relative to the baseline.  ALLOWED, reported.
#             Accessibility/polish work legitimately ADDS rules (e.g.
#             `:focus-visible` rings) without altering what is already painted,
#             so additions must not break the build - but they are still counted
#             and listed so a reviewer sees them.
#   ok = not changed and not removed
#
# Note that adding a *second* declaration of a property a file already uses is
# an `added`, not a `changed`: only a substitution is a retune.
#
# WHY ADDITIONS ARE ALLOWED BUT REMOVALS ARE NOT: the contract protects what is
# painted. Deleting a transition or a backdrop-filter silently changes the
# rendered result (motion lost, glass flattened); adding a new rule in a new
# selector can only paint something that was not painted before. An addition
# that *does* repaint an existing element will show up in the pixel half of the
# guard (`vg_diff.compare_sets`), which is where that belongs.
WATCHED_VALUE_TOKENS = ("transition", "animation", "backdrop-filter",
                        "filter:", "will-change", "contain:")
WATCHED_VARS = ("--blur-", "--glass-blur", "--app-bg-opacity",
                "--player-glow-", "--glow", "--transition", "--anim",
                "--ease", "--dur", "--duration")

# Extensions scanned under <root>/ui. Inline styles and inline `style.cssText`
# assignments are part of the contract too, not just .css files.
GUARDED_SUFFIXES = (".css", ".html", ".js")

_WS_RE = re.compile(r"\s+")
# the tokens without their trailing ':' so they can be matched as substrings of
# a property name (`filter` must match both `filter` and `-webkit-filter`)
_WATCHED_TOKENS_NC = tuple(t.rstrip(":") for t in WATCHED_VALUE_TOKENS)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/")
# `prop:` where prop is a CSS custom property or a normal ident
_DECL_RE = re.compile(r"(--[A-Za-z0-9_-]+|-?[A-Za-z_][A-Za-z0-9_-]*)\s*:")
# a legacy key's `<path>:<1-based line number>:` prefix
_LEGACY_LINE_RE = re.compile(r"^(.*?):\d+:")


def _normalize_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces and trim."""
    return _WS_RE.sub(" ", text).strip()


def _watched_property(prop: str) -> str | None:
    """Return `prop` lowercased if it is a guarded property, else None."""
    p = prop.strip().lower()
    if not p:
        return None
    for var in WATCHED_VARS:
        if p.startswith(var):
            return p
    # WATCHED_VALUE_TOKENS are matched as SUBSTRINGS on purpose: "animation"
    # also has to cover animation-duration, "-webkit-backdrop-filter" and
    # friends, which is exactly how the pre-existing line-level filter behaved.
    for tok in _WATCHED_TOKENS_NC:
        if tok in p:
            return p
    return None


_COMMENT_LINE_RE = re.compile(r"^\s*(//|/\*|\*)")
# `name = value` - a runtime assignment such as `el.style.transition = "..."`.
# Kept separately from the CSS `prop: value` form because inline styles set from
# JS paint exactly as much as inline styles in CSS do.
_ASSIGN_RE = re.compile(r"([-\w]+)\s*=\s*(.+)$")
# A minified vendor bundle can put a whole library on one line; clamp the value
# so one such line cannot dominate the baseline file.
_VALUE_MAX = 200


def _trim_value(raw: str) -> str:
    """Normalize a declaration value.

    Collapses whitespace, drops a trailing `;`, a trailing `}` that closes an
    inline block, and stray quotes/angle brackets left by HTML attributes. A
    value that legitimately ends in `)` (``blur(12px)``) is left alone: the
    closing paren is only stripped when it is unmatched.
    """
    v = _normalize_ws(raw)
    # an inline `style="..."` attribute ends at its closing quote, so cut the
    # value there; a JS assignment starts *inside* its quotes, so unwrap those.
    if v[:1] in ("\"", "'"):
        q = v[0]
        end = v.find(q, 1)
        v = v[1:end] if end != -1 else v[1:]
    else:
        for q in ("\"", "'"):
            if q in v:
                v = v.split(q, 1)[0]
                break
    while v:
        last = v[-1]
        if last in ";\"'":
            v = v[:-1].rstrip()
            continue
        if last == "}":
            v = v[:-1].rstrip()
            continue
        if last == ">":
            v = v[:-1].rstrip()
            continue
        if last == ")" and v.count(")") > v.count("("):
            v = v[:-1].rstrip()
            continue
        break
    v = v.lstrip("<").strip()
    if len(v) > _VALUE_MAX:
        v = v[:_VALUE_MAX] + " ..[clamped]"
    return v


# Real CSS properties that the token filter is meant to catch. A match on one
# of these is trusted wherever it appears, because `transition:` in a JS object
# literal or in an HTML style attribute is a declaration. A match that only
# *contains* a token (`attributeFilter:`, `disableAnimations =`,
# `container =`) is a plain JS identifier, so it additionally has to sit in a
# style-ish context (something before it says `style`) to count.
CANONICAL_PROPS = frozenset({
    "transition", "transition-property", "transition-duration",
    "transition-delay", "transition-timing-function",
    "animation", "animation-name", "animation-duration", "animation-delay",
    "animation-iteration-count", "animation-timing-function",
    "animation-direction", "animation-fill-mode", "animation-play-state",
    "backdrop-filter", "-webkit-backdrop-filter",
    "filter", "-webkit-filter",
    "will-change",
    "contain", "contain-intrinsic-size", "content-visibility",
})


def extract_declaration(line: str) -> dict:
    """Split a guarded source line into its ``(property, value)`` pair.

    Returns ``{"property", "value", "text"}``. Both the CSS form
    (``transition: opacity .2s``) and the JS assignment form
    (``el.style.transition = "opacity .2s"``) are recognised, and the property
    may sit inside a quoted HTML attribute - that is why the scan is textual
    rather than a full CSS parser.

    ``property`` is "" when the line carries no guarded declaration at all: a
    comment, a selector (``.perf-low #sidebar {``), a ``requestAnimationFrame``
    call, a JS variable whose name merely contains "animation". Those lines are
    deliberately NOT tracked. Keying them by their whole text - the obvious
    fallback - makes the guard fire on comment rewording and on any reformat of
    a minified bundle, i.e. it trades a vacuous guard for a noisy one. A line
    that cannot be reduced to a guarded ``property: value`` / ``property =
    value`` pair paints nothing, so there is nothing to contract.
    """
    text = _normalize_ws(_BLOCK_COMMENT_RE.sub(" ", line))
    if not text or _COMMENT_LINE_RE.match(text):
        return {"property": "", "value": "", "text": ""}

    # the LAST guarded `prop: value` (or `prop = value`) on the line wins: for
    # `.a { transition: none; }` that is the transition, and a comment earlier
    # on the same line cannot shadow it.
    candidates = [(m.group(1), m.end()) for m in _DECL_RE.finditer(text)]
    m_assign = _ASSIGN_RE.search(text)
    if m_assign is not None:
        candidates.append((m_assign.group(1), m_assign.start(2)))
    for raw_name, value_at in reversed(candidates):
        name = _watched_property(raw_name)
        if not name:
            continue
        if (name not in CANONICAL_PROPS and not name.startswith("--")
                and "style" not in text[:value_at].lower()):
            continue          # a JS identifier, not a declaration
        value = _trim_value(text[value_at:])
        return {"property": name, "value": value, "text": f"{name}: {value}"}

    return {"property": "", "value": "", "text": ""}


def collect_declarations(root: Path | None = None) -> dict[str, list[str]]:
    """Map ``"file|property"`` -> sorted list of values for the current tree.

    This is the single source of truth for both the guard comparison and the
    baseline writer, so a freshly written baseline always compares clean.
    """
    base = Path(root) if root is not None else REPO_ROOT
    ui = base / "ui"
    buckets: dict[str, list[str]] = {}
    if not ui.is_dir():
        return buckets
    for path in sorted(ui.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in GUARDED_SUFFIXES:
            continue
        rel = path.relative_to(base).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            low = line.lower()
            if not (any(t in low for t in WATCHED_VALUE_TOKENS)
                    or any(v in low for v in WATCHED_VARS)):
                continue
            decl = extract_declaration(line)
            if not decl["property"]:
                continue
            key = f"{rel}|{decl['property']}"
            buckets.setdefault(key, []).append(decl["value"])
    return {k: sorted(v) for k, v in buckets.items()}


def _load_baseline(path: Path) -> dict[str, list[str]]:
    """Read the baseline into the same ``key -> [values]`` shape.

    Backward compatible with every shape this file has ever had:

    * v2 (written by ``--write-css-baseline``): ``file`` / ``property`` /
      ``value`` - read verbatim, so a fresh baseline round-trips exactly.
    * v1 (``tools/bench/css_inventory.py``): ``file`` / ``property`` / ``value``
      plus a ``key`` of the form ``<file>:<line>:<selector>|<prop>|<value>``.
      The structured fields are used, the line number is discarded.
    * v0 (the original run_guard.py): only ``key`` = ``<file>:<line>:<text>``
      and ``text``. The property is recovered by re-parsing ``text`` and the
      line number is dropped, so the entry becomes comparable instead of being
      an unmatched key that would look removed forever.

    Nothing here raises on an unknown shape: an entry that cannot be keyed by
    property is kept under ``<file>|<unknown>`` with its whole text as the
    value, which reports as removed rather than silently passing.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"unreadable: {e}") from e

    buckets: dict[str, list[str]] = {}
    for rec in raw.get("declarations", []) or []:
        if not isinstance(rec, dict):
            continue
        rec_key = str(rec.get("key") or "").strip()
        rel = str(rec.get("file") or "").strip() or _strip_line_from_key(rec_key)
        prop = str(rec.get("property") or "").strip().lower()
        raw_value = rec.get("value")
        if prop and raw_value is not None:
            name = _watched_property(prop) or prop
            value = _trim_value(str(raw_value))
        else:
            # v0: rebuild the comparable pair from the recorded text.
            text = rec.get("text")
            if text is None:
                # last resort: a bare key like "<file>:<line>:<text>"
                text = rec_key.partition(":")[2] if ":" in rec_key else rec_key
            decl = extract_declaration(str(text))
            name = decl["property"]
            value = decl["value"] or _normalize_ws(str(text))
        buckets.setdefault(f"{rel}|{name}", []).append(value)
    for k in buckets:
        buckets[k] = sorted(buckets[k])
    return buckets


def _strip_line_from_key(key: str) -> str:
    """Reduce a legacy key to its file path.

    Handles every key shape this guard has ever written:
      ``ui/a.css:79:sel|transition|x``         (css_inventory.py)
      ``ui/a.css:79:.a { transition: none; }`` (original run_guard.py)
      ``ui/a.css|transition``                  (current shape - unchanged)
    """
    head = key.split("|", 1)[0]
    m = _LEGACY_LINE_RE.match(head)
    return m.group(1) if m else head


def _baseline_path(root: Path | None) -> Path:
    """Where the baseline lives for a given tree root.

    With no root that is the repository's own baseline; with a root (tests,
    scratch trees) it is the same relative path inside that root, so a test can
    never overwrite the real one.
    """
    if root is None:
        return ANIM_DECLS
    return Path(root) / "tools" / "bench" / "results" / "animation_declarations.json"


def _multiset_diff(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """``(gone, new)`` - the values only in `before` / only in `after`.

    Order-insensitive and multiplicity-aware, because a declaration is
    identified by its (file, property, value) triple: declaring
    `transition: none` twice in one file is two declarations, so deleting one
    of them must show up as a removal even though the *set* of values is
    unchanged.
    """
    pool = list(after)
    gone = []
    for v in before:
        if v in pool:
            pool.remove(v)
        else:
            gone.append(v)
    pool = list(before)
    new = []
    for v in after:
        if v in pool:
            pool.remove(v)
        else:
            new.append(v)
    return gone, new


def css_declaration_guard(root: Path | None = None) -> dict:
    """Diff the recorded animation/filter literals against the committed ones.

    `root` defaults to the repository root; it exists so tests can point the
    guard at a synthetic tree. See the block comment above for the keying
    scheme and the changed/removed/added semantics.
    """
    base_root = Path(root) if root is not None else REPO_ROOT
    baseline_path = _baseline_path(root)
    if not baseline_path.exists():
        rel = (baseline_path.relative_to(base_root).as_posix()
               if _is_relative_to(baseline_path, base_root) else str(baseline_path))
        return {"ok": False, "error": f"missing {rel}",
                "hint": ("generate it before using the guard: "
                         "python tools/visual_guard/run_guard.py --write-css-baseline")}
    try:
        base_map = _load_baseline(baseline_path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    cur_map = collect_declarations(base_root)

    base_keys = set(base_map)
    cur_keys = set(cur_map)

    changed: list[dict] = []
    removed: list[str] = []
    added: list[str] = []

    for k in sorted(base_keys & cur_keys):
        before, after = base_map[k], cur_map[k]
        if before == after:
            continue
        gone, new = _multiset_diff(before, after)
        # A substitution - something went AND something new arrived under the
        # same file+property - is a retune of a declaration that is already
        # painted, so it is a regression. A pure addition under an existing key
        # is not: it is a new declaration, which the contract allows.
        if gone and new:
            changed.append({"key": k, "before": before, "after": after,
                            "removed_values": gone, "added_values": new})
        removed.extend(f"{k} = {v}" for v in gone)
        added.extend(f"{k} = {v}" for v in new)

    # a key that vanished entirely: every value under it is gone
    for k in sorted(base_keys - cur_keys):
        removed.extend(f"{k} = {v}" for v in base_map[k])
    # a key that is new: informational only, deliberately NOT a failure
    for k in sorted(cur_keys - base_keys):
        added.extend(f"{k} = {v}" for v in cur_map[k])

    overlap = base_keys & cur_keys
    return {
        "ok": not changed and not removed,
        "baseline_declarations": sum(len(v) for v in base_map.values()),
        "current_declarations": sum(len(v) for v in cur_map.values()),
        "removed": sorted(removed),
        "added": sorted(added),
        "changed": changed,
        "note": ("A removed declaration is as much a visual change as a modified "
                 "one: ok = not changed and not removed. A declaration is a "
                 "(file, property, value) triple, so 'changed' means a value was "
                 "substituted under an existing file+property, while 'added' - a "
                 "brand new declaration, including a second declaration of a "
                 "property a file already uses - is ALLOWED and only reported: "
                 "accessibility/polish work adds rules (e.g. :focus-visible "
                 "rings) without altering what is already painted, and the pixel "
                 "half of this guard is what catches repainting. Keys are "
                 "content-keyed ('<file>|<property>' -> multiset of values) with "
                 "no line numbers anywhere, so inserting or deleting an "
                 "unrelated line cannot shift the comparison. Custom properties "
                 "feeding blur/transition values are included."),
        "baseline_path": str(baseline_path),
        "files_with_declarations": len({k.split("|", 1)[0] for k in cur_keys}),
        "intersection_keys": len(overlap),
        "baseline_keys": len(base_keys),
        "current_keys": len(cur_keys),
        "vacuous": len(overlap) == 0 and bool(base_keys) and bool(cur_keys),
    }


def write_css_baseline(root: Path | None = None, out_path: Path | None = None) -> int:
    """(Re)generate the baseline from the current tree. Returns the count.

    Written records carry ``file``/``property``/``value`` explicitly so the
    reader never has to re-parse text to rebuild a key, plus a human-readable
    ``text`` and a report-only ``occurrence`` label. Line numbers are
    deliberately NOT recorded: they are exactly what used to make this guard
    vacuous, and re-recording them on every unrelated edit would guarantee
    drift between the baseline and the tree.
    """
    base_root = Path(root) if root is not None else REPO_ROOT
    target = out_path or _baseline_path(root)
    buckets = collect_declarations(base_root)
    decls = []
    for key in sorted(buckets):
        rel, _, prop = key.partition("|")
        for i, value in enumerate(buckets[key]):
            decls.append({"key": key, "file": rel, "property": prop,
                          "value": value, "text": f"{prop}: {value}",
                          "occurrence": i})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(
        {"schema": "nedotify.animation-declarations.v2",
         "generated_by": "tools/visual_guard/run_guard.py --write-css-baseline",
         "scanned": [f"ui/**/{ext}" for ext in GUARDED_SUFFIXES],
         "watched_value_tokens": list(WATCHED_VALUE_TOKENS),
         "watched_vars": list(WATCHED_VARS),
         "keying": "<relative/path>|<property> -> multiset of normalized values; "
                   "position independent, so line numbers never enter a key and "
                   "`occurrence` is a report label only",
         "counts": {"declarations": len(decls), "keys": len(buckets),
                    "files": len({d["file"] for d in decls})},
         "declarations": decls},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(decls)


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="NeDotify visual guard")
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--themes", default=",".join(vg_fixtures.THEMES.keys()))
    ap.add_argument("--screens", default=",".join(vg_fixtures.ALL_SCREENS))
    ap.add_argument("--tracks", type=int, default=200)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--skip-css", action="store_true")
    ap.add_argument("--write-css-baseline", action="store_true",
                    help="regenerate tools/bench/results/animation_declarations.json "
                         "from the current tree and exit (no capture, no compare)")
    args = ap.parse_args()

    if args.write_css_baseline:
        n = write_css_baseline()
        log(f"css baseline written: {n} declarations -> {ANIM_DECLS}")
        check = css_declaration_guard()
        log(f"  self-check: ok={check.get('ok')} "
            f"baseline={check.get('baseline_declarations')} "
            f"current={check.get('current_declarations')} "
            f"changed={len(check.get('changed') or [])} "
            f"removed={len(check.get('removed') or [])} "
            f"added={len(check.get('added') or [])}")
        return 0 if check.get("ok") else 1

    if not (args.capture or args.compare or args.all):
        print(__doc__)
        return 2

    themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    screens = [s.strip() for s in args.screens.split(",") if s.strip()]
    unknown = [t for t in themes if t not in vg_fixtures.THEMES]
    if unknown:
        log(f"unknown themes: {unknown}; known={list(vg_fixtures.THEMES)}")
        return 2

    do_capture = args.capture or (args.all and not GOLDENS.exists())
    if args.all:
        do_capture = True

    capture_summary = None
    if do_capture:
        if GOLDENS.exists() and args.capture:
            log(f"rebuilding goldens in {GOLDENS} (old set removed)")
            shutil.rmtree(GOLDENS, ignore_errors=True)
        capture_summary = capture(CURRENT if args.compare else GOLDENS, themes,
                                  screens, args.tracks, args.port,
                                  vg_fixtures.VIEWPORTS, vg_fixtures.DPRS)

    exit_code = 0
    report: dict = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "code_fingerprint": prof.tree_fingerprint_short(prof.fingerprint_tree()),
        "goldens": str(GOLDENS), "current": str(CURRENT),
        "screens": screens, "themes": themes,
        "viewports": vg_fixtures.VIEWPORTS, "dprs": vg_fixtures.DPRS,
    }

    if args.compare or args.all:
        log(f"comparing {len(screens)} screens x {len(themes)} themes "
            f"x {len(vg_fixtures.VIEWPORTS)} viewports x {len(vg_fixtures.DPRS)} dpr")
        pixel = vg_diff.compare_sets(GOLDENS, CURRENT, out_dir=CURRENT / "_diff")
        report["pixels"] = pixel
        log(f"  pixels: {pixel['passed']}/{pixel['compared']} passed, "
            f"{pixel['failed']} failed, {len(pixel['missing'])} missing")
        for f in pixel["failures"][:15]:
            log(f"    FAIL {f['name']}  diff={f.get('diff_percent')}%  "
                f"bbox={f.get('bbox_xyxy')}")
        if not pixel["ok"]:
            exit_code = 1

    if not args.skip_css:
        css = css_declaration_guard()
        report["css"] = css
        if css.get("ok"):
            log(f"  css declarations: {css.get('current_declarations')} tracked, "
                f"{len(css.get('added') or [])} added (allowed)")
        else:
            if css.get("error"):
                log(f"  css declarations: ERROR ({css['error']})")
                log(f"    hint: {css.get('hint') or 'regenerate with --write-css-baseline'}")
            else:
                log(f"  css declarations: REGRESSION "
                    f"({len(css.get('changed') or [])} changed, "
                    f"{len(css.get('removed') or [])} removed, "
                    f"{len(css.get('added') or [])} added)")
                for c in (css.get("changed") or [])[:20]:
                    log(f"    ~ {c['key']}\n        - {c['before']}\n        + {c['after']}")
                for k in (css.get("removed") or [])[:20]:
                    log(f"    - {k}")
            for k in (css.get("added") or [])[:20]:
                log(f"    + {k}")
            exit_code = 1

    if capture_summary:
        report["capture"] = {k: {"exit_code": v["exit_code"],
                                  "screens": len(v["child"].get("data", {}).get("captured") or [])}
                             for k, v in capture_summary.items()}

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"guard-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"report: {out}")
    log("RESULT: PASS" if exit_code == 0 else "RESULT: FAIL")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
