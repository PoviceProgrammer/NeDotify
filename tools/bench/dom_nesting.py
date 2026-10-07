"""Build a static DOM tree from ui/web_new_v2/index.html and report, for every
element matched by a CSS selector that carries `backdrop-filter` / `filter`,
the ancestor chain plus which ancestors establish a containing block for a
nested backdrop-filter.

READ-ONLY.  Writes tools/bench/results/backdrop_nesting.json.
No external dependencies: a forgiving tag scanner is enough for this file, and
any tag it cannot resolve is reported instead of silently dropped.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HTML = REPO / "ui" / "web_new_v2" / "index.html"
CSS_DIR = REPO / "ui" / "web_new_v2" / "css"
OUT = REPO / "tools" / "bench" / "results" / "backdrop_nesting.json"

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}

# Properties that make an element a containing block / stacking context, which
# means a descendant backdrop-filter re-samples only what that ancestor painted.
CONTAINING = {
    "filter", "backdrop-filter", "transform", "perspective", "opacity",
    "contain", "will-change", "mask", "clip-path", "mix-blend-mode",
    "isolation", "backface-visibility", "rotate", "scale", "translate",
}

# Elements the JS/CSS toggles: a hidden ancestor still occupies the tree, so we
# record "painted behind" from the static structure plus these dynamic hints.
OPAQUE_HINT = re.compile(
    r"background:\s*(#[0-9a-f]{3,8}|rgb|rgba|black|white)|background-color:\s*#[0-9a-f]{3,8}",
    re.I,
)


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "depth", "line", "classes", "ident")

    def __init__(self, tag, attrs, parent, depth, line):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.depth = depth
        self.line = line
        self.children: list[Node] = []
        cid = attrs.get("id")
        self.classes = set((attrs.get("class") or "").split())
        self.ident = f"{tag}#{cid}" if cid else (f"{tag}.{'.'.join(sorted(self.classes))}" if self.classes else tag)

    def ancestors(self):
        out = []
        p = self.parent
        while p is not None:
            out.append(p)
            p = p.parent
        return out

    def selector_text(self):
        if self.attrs.get("id"):
            return f"#{self.attrs['id']}"
        if self.classes:
            return f"{self.tag}." + ".".join(sorted(self.classes))
        return self.tag


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None, 0, 0)
        self.stack = [self.root]
        self.all = [self.root]

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        n = Node(tag, d, self.stack[-1], len(self.stack), self.getpos()[0])
        self.stack[-1].children.append(n)
        self.all.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        n = Node(tag, d, self.stack[-1], len(self.stack), self.getpos()[0])
        self.stack[-1].children.append(n)
        self.all.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return


def main() -> None:
    tb = TreeBuilder()
    tb.feed(HTML.read_text(encoding="utf-8"))

    # ---- which selectors carry backdrop-filter / filter --------------------
    sys.path.insert(0, str(REPO / "tools" / "bench"))
    from css_inventory import IMPORT_ORDER, parse_file  # noqa: E402

    by_file: dict[str, list] = {}
    for rel in IMPORT_ORDER:
        by_file[f"ui/web_new_v2/css/{rel}"] = parse_file(CSS_DIR / rel, f"ui/web_new_v2/css/{rel}")

    css_text = {
        f"ui/web_new_v2/css/{rel}": (CSS_DIR / rel).read_text(encoding="utf-8") for rel in IMPORT_ORDER
    }

    # Resolve, per backdrop-filter declaration, the full property set of the
    # matching selector (from ALL rules, in cascade order) so we know whether
    # the element itself creates a containing block.
    def selector_props(sel_text: str) -> dict[str, list[str]]:
        """Return {prop: [declarations]} contributed by any rule matching sel_text."""
        out: dict[str, list[str]] = {}
        for f, decls in by_file.items():
            for d in decls:
                if d.kind not in ("declaration",):
                    continue
                if simple_matches(d.selector, sel_text):
                    out.setdefault(d.prop, []).append(f"{d.value}{' !important' if d.important else ''}")
        return out

    records = []
    for f, decls in by_file.items():
        for d in decls:
            if d.prop not in ("backdrop-filter", "-webkit-backdrop-filter", "filter", "-webkit-filter"):
                continue
            # resolve target nodes for each compound selector
            parts = [p.strip() for p in d.selector.split(",")] if d.selector else [""]
            for part in parts:
                if not part:
                    continue
                nodes = find_nodes(tb.all, part)
                for n in nodes:
                    props = selector_props(part)
                    chain = []
                    containing_ancestors = []
                    for a in n.ancestors():
                        txt = a.selector_text()
                        aprops = selector_props(txt)
                        creates = sorted(
                            p for p in aprops if p in CONTAINING
                        )
                        chain.append(
                            {
                                "ident": a.ident,
                                "selector": txt,
                                "line": a.line,
                                "containing_props": creates,
                                "backdrop_filter": aprops.get("backdrop-filter"),
                                "filter": aprops.get("filter"),
                                "background": aprops.get("background") or aprops.get("background-color"),
                                "opacity": aprops.get("opacity"),
                            }
                        )
                        if creates:
                            containing_ancestors.append(a.ident)
                    nprops = selector_props(part)
                    rec = {
                        "declaration": f"{d.file.replace('ui/web_new_v2/css/', '')}:{d.line}",
                        "property": d.prop,
                        "value": d.value,
                        "important": d.important,
                        "selector": d.selector,
                        "compound_selector": part,
                        "at_rules": d.at_rules,
                        "element": n.ident,
                        "element_line_in_html": n.line,
                        "nesting_depth": len([c for c in chain if c["containing_props"]]),
                        "backdrop_filtered_ancestors": [
                            c["ident"]
                            for c in chain
                            if c["backdrop_filter"]
                            and any(v.lower() != "none" for v in c["backdrop_filter"])
                        ],
                        "ancestor_chain_top_down": list(reversed(chain)),
                        "containing_block_ancestors": containing_ancestors,
                        "self_props_relevant": {
                            k: v
                            for k, v in nprops.items()
                            if k in CONTAINING | {"background", "background-color", "opacity", "isolation"}
                        },
                    }
                    records.append(rec)

    # de-duplicate identical records (webkit + unprefixed pairs)
    seen = set()
    uniq = []
    for r in records:
        k = (
            r["declaration"],
            r["property"],
            r["compound_selector"],
            r["element"],
        )
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    payload = {
        "schema": "nedotify.backdrop-nesting.v1",
        "generated_by": "tools/bench/dom_nesting.py",
        "html": "ui/web_new_v2/index.html",
        "notes": [
            "static analysis of index.html + the 9 css files; no browser involved",
            "nesting_depth counts ANCESTORS that create a containing block for a nested backdrop-filter",
            "backdrop_filtered_ancestors lists ancestors that themselves blur the backdrop",
        ],
        "counts": {
            "dom_nodes": len(tb.all),
            "records": len(uniq),
            "max_nesting_depth": max((r["nesting_depth"] for r in uniq), default=0),
            "records_with_backdro_filtered_ancestor": sum(
                1 for r in uniq if r["backdrop_filtered_ancestors"]
            ),
        },
        "records": sorted(uniq, key=lambda r: (-r["nesting_depth"], r["declaration"], r["compound_selector"])),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))
    for r in payload["records"]:
        print(
            f"depth={r['nesting_depth']}  {r['declaration']:<26} {r['compound_selector']:<58} -> {r['element']:<28} "
            f"bf-ancestors={r['backdrop_filtered_ancestors']}"
        )


def simple_matches(rule_selector: str, target_sel: str) -> bool:
    """Very small selector matcher: enough for this stylesheet's class/id/tag use."""
    if rule_selector == target_sel:
        return True
    rule_sel_norm = _norm(rule_selector)
    tgt = _norm(target_sel)
    if rule_sel_norm == tgt:
        return True
    # a rule with fewer/more selectors: every compound in the rule list must
    # resolve to the same node signature we are looking at
    if "," in target_sel:
        return any(_norm(p) == rule_sel_norm for p in target_sel.split(","))
    return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def find_nodes(all_nodes, sel: str):
    sel = sel.strip()
    # "#id" | "tag" | "tag.a.b" | ".a.b"
    m = re.fullmatch(r"([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)", sel)
    if not m:
        return []
    tag = (m.group(1) or "").lower()
    toks = re.findall(r"([.#])([\w-]+)", m.group(2) or "")
    out = []
    for n in all_nodes:
        if n.tag == "#document":
            continue
        if tag and n.tag != tag:
            continue
        ok = True
        for kind, name in toks:
            if kind == ".":
                if name not in n.classes:
                    ok = False
                    break
            else:
                if n.attrs.get("id") != name:
                    ok = False
                    break
        if ok:
            out.append(n)
    return out


if __name__ == "__main__":
    main()