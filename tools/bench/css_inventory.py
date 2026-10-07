"""Deterministic CSS declaration extractor for the NeDotify frontend profiling pass.

READ-ONLY with respect to the application.  Writes only into
tools/bench/results/.

Emits
-----
tools/bench/results/animation_declarations_inventory.json
    Every CSS declaration whose property is in GUARD_PROPS (transition*,
    animation*, backdrop-filter, filter, will-change, contain,
    content-visibility, mix-blend-mode, perspective) plus every at-rule and
    every @keyframes step.  This is a line-accurate *reporting* artefact for the
    perf pass.

    It is deliberately kept separate from
    tools/bench/results/animation_declarations.json, which is the *enforced*
    baseline read by tools/visual_guard/run_guard.py::css_declaration_guard.
    That guard keys declarations by (file, property) with no line numbers so
    that inserting or deleting a line cannot silently void the check; writing
    this report to the guard's path used to restore exactly that vacuous
    behaviour.  Do not merge the two files.

tools/bench/results/css_blur_map.json
    Every backdrop-filter / -webkit-backdrop-filter / filter declaration with
    the selector it applies to, the literal value and the source line.

The parser is a hand-rolled brace/quote-aware scanner.  It does NOT resolve
var(), does NOT reorder rules and does NOT dedupe: the output is a faithful,
line-accurate transcription, sorted by (file, line, selector, property, value)
so the JSON is byte-stable across runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CSS_DIR = REPO / "ui" / "web_new_v2" / "css"
OUT_DIR = REPO / "tools" / "bench" / "results"

# Filename of the line-accurate reporting artefact this module emits. It must
# never be "animation_declarations.json" - that path belongs to the enforced
# visual-guard baseline, which uses a different, line-number-free keying.
INVENTORY_FILENAME = "animation_declarations_inventory.json"

# Load order mirrors the @import chain of ui/web_new_v2/css/styles.css, so the
# `declarations` array is emitted in true cascade order.
IMPORT_ORDER = [
    "fonts.css",
    "tokens.css",
    "components/base.css",
    "components/player-bar.css",
    "components/player-view.css",
    "components/lyrics.css",
    "components/home-view.css",
    "components/track-table.css",
    "themes.css",
    "components/visual-polish.css",
]

# The entrypoint itself only carries @import statements; it is parsed too so the
# guard baseline records the load-order contract itself.
ENTRYPOINT = ["styles.css"]

# Declarations the later visual-guard step must never see change.
GUARD_PROPS = {
    "transition",
    "transition-property",
    "transition-duration",
    "transition-delay",
    "transition-timing-function",
    "animation",
    "animation-name",
    "animation-duration",
    "animation-delay",
    "animation-iteration-count",
    "animation-timing-function",
    "animation-direction",
    "animation-fill-mode",
    "animation-play-state",
    "backdrop-filter",
    "-webkit-backdrop-filter",
    "filter",
    "-webkit-filter",
    "will-change",
    "contain",
    "contain-intrinsic-size",
    "content-visibility",
    "mix-blend-mode",
    "perspective",
    "backface-visibility",
}

BLUR_PROPS = {"filter", "-webkit-filter", "backdrop-filter", "-webkit-backdrop-filter"}

# Properties that create a containing block / new stacking context for a
# nested backdrop-filter (CSS spec behaviour), used by the nesting analysis.
CONTAINING_PROPS = {
    "filter",
    "-webkit-filter",
    "backdrop-filter",
    "-webkit-backdrop-filter",
    "transform",
    "-webkit-transform",
    "perspective",
    "contain",
    "will-change",
    "opacity",
    "mask",
    "-webkit-mask",
    "clip-path",
}

_NESTING_AT = re.compile(r"^@(media|supports|layer|container|scope)\b")
_KEYFRAMES_AT = re.compile(r"^@(keyframes|-webkit-keyframes)\b")
_OPAQUE_AT = re.compile(r"^@(font-face|property)\b")
_WS = re.compile(r"\s+")


def _strip_comments_keep_lines(text: str) -> str:
    """Blank out /* ... */ but keep every newline so line numbers stay exact."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                j = n - 1
            for ch in text[i : j + 2]:
                out.append("\n" if ch == "\n" else " ")
            i = j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


@dataclass
class Decl:
    file: str
    line: int
    selector: str
    at_rules: list = field(default_factory=list)
    prop: str = ""
    value: str = ""
    important: bool = False
    kind: str = "declaration"

    @property
    def key(self) -> str:
        return f"{self.file}:{self.line}:{self.selector}|{self.prop}|{self.value}"

    def to_json(self) -> dict:
        return {
            "key": self.key,
            "file": self.file,
            "line": self.line,
            "selector": self.selector,
            "at_rules": list(self.at_rules),
            "property": self.prop,
            "value": self.value,
            "important": self.important,
            "kind": self.kind,
        }


class CssParser:
    def __init__(self, text: str, rel: str):
        self.s = _strip_comments_keep_lines(text)
        self.n = len(self.s)
        self.pos = 0
        self.rel = rel
        self.decls: list[Decl] = []
        self.at_stack: list[str] = []
        self._newlines: list[int] = []
        idx = self.s.find("\n")
        while idx != -1:
            self._newlines.append(idx)
            idx = self.s.find("\n", idx + 1)

    # -- helpers ------------------------------------------------------------
    def _skip_ws(self, idx: int) -> int:
        """Advance past whitespace so `line_at()` points at the declaration itself."""
        while idx < self.n and self.s[idx] in " \t\r\n":
            idx += 1
        return idx

    def line_at(self, idx: int) -> int:
        lo, hi = 0, len(self._newlines)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._newlines[mid] < idx:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    # -- entry point --------------------------------------------------------
    def parse(self) -> list[Decl]:
        self._parse_rules()
        return self.decls

    def _parse_rules(self) -> None:
        """Parse a sequence of `sel { ... }` rules / at-rules until a bare `}`.

        `token_start` tracks where the current selector/statement text begins so
        the prelude can be sliced correctly (the `{` is *after* the prelude).
        """
        token_start = self.pos
        while self.pos < self.n:
            c = self.s[self.pos]
            if c == "}":
                self.pos += 1
                return
            if c == ";":
                stmt = self.s[token_start : self.pos]
                self.pos += 1
                if stmt.strip():
                    self._emit_at_statement(stmt, token_start)
                token_start = self.pos
                continue
            if c == "{":
                prelude = _WS.sub(" ", self.s[token_start : self.pos].strip()).strip()
                self.pos += 1
                if _KEYFRAMES_AT.match(prelude):
                    self._parse_keyframes(prelude.split(None, 1)[1].strip())
                    token_start = self.pos
                    continue
                if _OPAQUE_AT.match(prelude):
                    self._parse_declarations(prelude)
                    token_start = self.pos
                    continue
                if _NESTING_AT.match(prelude):
                    self.at_stack.append(prelude)
                    self._parse_rules()
                    self.at_stack.pop()
                    token_start = self.pos
                    continue
                if prelude.startswith("@"):
                    # unknown at-rule with a block: descend generically
                    self.at_stack.append(prelude)
                    self._parse_rules()
                    self.at_stack.pop()
                    token_start = self.pos
                    continue
                self._parse_declarations(prelude)
                token_start = self.pos
                continue
            self.pos += 1

    # -- block readers ------------------------------------------------------
    def _parse_declarations(self, selector: str) -> None:
        buf: list[str] = []
        # the first declaration of a block starts right after `{`; skip the
        # whitespace/newline so line_at() points at the property, not the `{`
        decl_start = self._skip_ws(self.pos)
        while self.pos < self.n:
            c = self.s[self.pos]
            if c in "\"'":
                q = c
                buf.append(q)
                self.pos += 1
                while self.pos < self.n and self.s[self.pos] != q:
                    if self.s[self.pos] == "\\":
                        buf.append(self.s[self.pos])
                        self.pos += 1
                    if self.pos < self.n:
                        buf.append(self.s[self.pos])
                        self.pos += 1
                if self.pos < self.n:
                    buf.append(q)
                    self.pos += 1
                continue
            if c == ";":
                self._emit(selector, "".join(buf), decl_start)
                buf = []
                self.pos += 1
                decl_start = self._skip_ws(self.pos)
                continue
            if c == "{":
                # CSS nesting: `parent { nested { ... } }`
                nested_prelude = _WS.sub(" ", "".join(buf).strip()).strip()
                self.pos += 1
                nested_sel = f"{selector} {nested_prelude}".strip()
                self.decls.append(
                    Decl(
                        file=self.rel,
                        line=self.line_at(self.pos - 1),
                        selector=nested_sel,
                        at_rules=list(self.at_stack),
                        prop="<nested-rule>",
                        value="",
                        kind="nested-rule",
                    )
                )
                self._parse_declarations(nested_sel)
                buf = []
                decl_start = self._skip_ws(self.pos)
                continue
            if c == "}":
                self._emit(selector, "".join(buf), decl_start)
                self.pos += 1
                return
            buf.append(c)
            self.pos += 1
        self._emit(selector, "".join(buf), decl_start)

    def _parse_keyframes(self, name: str) -> None:
        """Parse the body of an @keyframes rule.  The opening `{` is already consumed."""
        self.at_stack.append(f"@keyframes {name}")
        while self.pos < self.n:
            step_start = self.pos
            while self.pos < self.n and self.s[self.pos] not in "{}":
                self.pos += 1
            step = _WS.sub(" ", self.s[step_start : self.pos].strip())
            if self.pos < self.n and self.s[self.pos] == "{":
                self.pos += 1
                self._parse_declarations(step)
                continue
            if self.pos < self.n and self.s[self.pos] == "}":
                self.pos += 1
                break
        self.at_stack.pop()

    # -- emitters -----------------------------------------------------------
    def _emit(self, selector: str, raw: str, idx: int) -> None:
        raw = raw.strip()
        if not raw:
            return
        if raw.startswith("@"):
            self._emit_at_statement(raw, idx)
            return
        if ":" not in raw:
            return
        prop, _, value = raw.partition(":")
        prop = prop.strip().lower()
        value = _WS.sub(" ", value.strip())
        important = value.lower().endswith("!important")
        if important:
            value = value[: -len("!important")].strip()
        in_keyframes = any(a.startswith("@keyframes") for a in self.at_stack)
        self.decls.append(
            Decl(
                file=self.rel,
                line=self.line_at(idx),
                selector=selector,
                at_rules=list(self.at_stack),
                prop=prop,
                value=value,
                important=important,
                kind="keyframe-step" if in_keyframes else "declaration",
            )
        )

    def _emit_at_statement(self, stmt: str, idx: int | None = None) -> None:
        stmt = _WS.sub(" ", stmt.strip())
        self.decls.append(
            Decl(
                file=self.rel,
                line=self.line_at(idx if idx is not None else self.pos),
                selector=" ".join(self.at_stack),
                at_rules=list(self.at_stack),
                prop="@",
                value=stmt,
                kind="at-rule",
            )
        )


def parse_file(path: Path, rel: str) -> list[Decl]:
    return CssParser(path.read_text(encoding="utf-8"), rel).parse()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_decls: list[Decl] = []
    per_file: dict[str, int] = {}
    for rel in ENTRYPOINT + IMPORT_ORDER:
        d = parse_file(CSS_DIR / rel, f"ui/web_new_v2/css/{rel}")
        all_decls.extend(d)
        per_file[rel] = len(d)

    cascade_index = {id(d): i for i, d in enumerate(all_decls)}
    all_decls.sort(key=lambda d: (d.file, d.line, d.selector, d.prop, d.value))

    guard = [
        d
        for d in all_decls
        if d.prop in GUARD_PROPS or d.kind in ("at-rule", "nested-rule")
    ]
    by_prop: dict[str, int] = {}
    for d in guard:
        by_prop[d.prop] = by_prop.get(d.prop, 0) + 1

    payload = {
        "schema": "nedotify.animation-declarations.v1",
        "generated_by": "tools/bench/css_inventory.py",
        "root": "ui/web_new_v2/css",
        "import_order": [f"ui/web_new_v2/css/{r}" for r in IMPORT_ORDER],
        "guard_properties": sorted(GUARD_PROPS),
        "sort_key": "(file, line, selector, property, value)",
        "counts": {
            "total_declarations_parsed": len(all_decls),
            "guard_declarations": len(guard),
            "declarations_per_file": per_file,
            "by_kind": {
                k: sum(1 for d in all_decls if d.kind == k)
                for k in ("declaration", "keyframe-step", "at-rule", "nested-rule")
            },
            "by_property": dict(sorted(by_prop.items())),
        },
        "declarations": [],
    }
    for d in guard:
        rec = d.to_json()
        rec["cascade_index"] = cascade_index[id(d)]
        payload["declarations"].append(rec)
    # NOTE: this inventory is deliberately NOT written to
    # "animation_declarations.json". That path is the *enforced baseline* of
    # tools/visual_guard/run_guard.py::css_declaration_guard, and the guard
    # keys declarations by (file, property) with no line numbers, while this
    # report keys them by (file, line, selector, property, value). Overwriting
    # the baseline with this file used to silently return the visual contract to
    # its vacuous state (empty key intersection => ok=True no matter what). Keep
    # the two artefacts separate.
    (OUT_DIR / INVENTORY_FILENAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    blur = [d for d in all_decls if d.prop in BLUR_PROPS]
    blur_payload = {
        "schema": "nedotify.css-blur-map.v1",
        "generated_by": "tools/bench/css_inventory.py",
        "sort_key": "(file, line, selector, property, value)",
        "counts": {
            "total_blur_declarations": len(blur),
            "backdrop_filter_active": sum(
                1 for d in blur if "backdrop-filter" in d.prop and d.value.lower() != "none"
            ),
            "backdrop_filter_none": sum(
                1 for d in blur if "backdrop-filter" in d.prop and d.value.lower() == "none"
            ),
            "filter_with_blur_fn": sum(
                1 for d in blur if "backdrop" not in d.prop and re.search(r"blur\s*\(", d.value)
            ),
        },
        "declarations": [],
    }
    for d in blur:
        rec = d.to_json()
        rec["cascade_index"] = cascade_index[id(d)]
        rec["is_backdrop"] = "backdrop-filter" in d.prop
        rec["has_blur_fn"] = bool(re.search(r"blur\s*\(", d.value))
        rec["blur_is_none"] = d.value.lower() == "none"
        rec["blur_radii"] = re.findall(r"blur\(\s*([^)]*)\)", d.value)
        blur_payload["declarations"].append(rec)
    (OUT_DIR / "css_blur_map.json").write_text(
        json.dumps(blur_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"parsed {len(all_decls)} declarations across {len(IMPORT_ORDER)} files")
    for rel, c in per_file.items():
        print(f"  {rel:38s} {c}")
    print(f"guard declarations: {len(guard)}")
    print(f"blur declarations:   {len(blur)}")
    for k, v in sorted(by_prop.items()):
        print(f"  {k:26s} {v}")


if __name__ == "__main__":
    main()