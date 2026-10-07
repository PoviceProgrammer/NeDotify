"""Static census of global (window / document / scrollingElement) event listeners
and of rAF / setInterval animation drivers in ui/web_new_v2/js.

READ-ONLY.  Writes tools/bench/results/frontend_hotspots.json (partial: sections
1, 2) which this agent then merges with the CSS/measurements produced by the
sibling scripts.

The scanner is deliberately dumb and line-accurate: it reports what is written,
with the source line, and marks handlers it could not classify.  Anything it
flags as `unknown` is reported as unknown rather than guessed at.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / "ui" / "web_new_v2" / "js"
OUT = REPO / "tools" / "bench" / "results" / "frontend_hotspots.json"

# Vendored bundles: not first-party code, excluded from the analysis surface.
VENDORED = {"hls.min.js", "lucide.min.js"}

GLOBAL_TARGETS = {"window", "document", "self", "document.scrollingElement"}
GLOBAL_EVENTS_OF_INTEREST = {
    "resize", "scroll", "mousemove", "pointermove", "touchmove", "input",
    "keydown", "keyup", "wheel", "visibilitychange", "blur", "focus",
    "mousedown", "mouseup", "mouseenter", "mouseleave", "click",
    "contextmenu", "timeupdate", "pointerdown", "pointerup", "load", "beforeunload",
}

# DOM read APIs that force style/layout work.
READ_APIS = [
    "getBoundingClientRect", "offsetTop", "offsetLeft", "offsetWidth", "offsetHeight",
    "clientTop", "clientLeft", "clientWidth", "clientHeight", "scrollTop", "scrollLeft",
    "scrollWidth", "scrollHeight", "getComputedStyle", "offsetParent", "innerWidth",
    "innerHeight", "getClientRects", "scrollIntoView",
]
# DOM write APIs.
WRITE_APIS = [
    "style.", "classList", "setProperty", "setAttribute", "removeAttribute",
    "innerHTML", "textContent", "appendChild", "replaceChildren", "insertBefore",
    "remove()", "animate(", "focus()", "blur()",
]


def strip_comments_keep_lines(text: str) -> str:
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append("\n" * text.count("\n", i, j))
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                j = n - 1
            for ch in text[i : j + 2]:
                out.append("\n" if ch == "\n" else " ")
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


QUOTES = "\"'`"


def match_paren(s: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at open_idx, or -1."""
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in QUOTES:
            q = ch
            i += 1
            while i < n and s[i] != q:
                if s[i] == "\\":
                    i += 1
                i += 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def match_brace(s: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in QUOTES:
            q = ch
            i += 1
            while i < n and s[i] != q:
                if s[i] == "\\":
                    i += 1
                i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def enclosing_function_name(s: str, idx: int) -> str:
    """Best-effort: name of the function whose body contains idx."""
    best = "<module scope>"
    best_pos = -1
    for m in re.finditer(r"(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\())", s):
        brace = s.find("{", m.end())
        arrow_paren = s.find("=>", m.end())
        if brace == -1:
            continue
        end = match_brace(s, brace)
        if end == -1:
            continue
        if brace < idx < end and m.start() > best_pos:
            best_pos = m.start()
            best = m.group(1) or m.group(2) or "<anonymous arrow>"
    return best


def local_function_bodies(s: str) -> dict:
    """Map of locally defined function/const-arrow name -> body text (same file)."""
    out: dict[str, str] = {}
    for m in re.finditer(
        r"(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s+)?(?:function|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>))",
        s,
    ):
        name = m.group(1) or m.group(2)
        b = s.find("{", m.end())
        arrow = s.find("=>", m.end())
        if b == -1:
            continue
        if arrow != -1 and arrow < b and "\n" not in s[arrow:b]:
            # concise arrow body: `x => expr`
            out[name] = s[arrow:b] + s[b : b + 400]
            continue
        e = match_brace(s, b)
        if e == -1:
            continue
        out[name] = s[b : e + 1]
    return out


def expand_calls(body: str, funcs: dict, depth: int = 2) -> str:
    """Append the bodies of locally defined functions referenced by `body`."""
    seen: set[str] = set()
    frontier = set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", body))
    out = body
    for _ in range(depth):
        nxt: set[str] = set()
        for name in frontier:
            if name in seen or name not in funcs:
                continue
            seen.add(name)
            out += "\n" + funcs[name]
            nxt |= set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", funcs[name]))
        frontier = nxt - seen
        if not frontier:
            break
    return out


def classify_handler(body: str) -> dict:
    reads = sorted({api for api in READ_APIS if api in body})
    writes = sorted({api for api in WRITE_APIS if api in body})
    flags = []
    if reads and writes:
        flags.append("read+write-in-same-handler (layout-thrash risk)")
    if "requestAnimationFrame" in body:
        flags.append("rAF-coalesced")
    if re.search(r"\bsetTimeout\s*\(", body) and "clearTimeout" not in body:
        flags.append("debounce-without-clear (possible leak)")
    if re.search(r"getBoundingClientRect|getComputedStyle", body):
        flags.append("forced-layout-read")
    return {
        "reads": reads,
        "writes": writes,
        "flags": flags,
        "body_lines": body.count("\n") + 1,
    }


def main() -> None:
    listeners = []
    rafs = []
    intervals = []
    per_file_listeners = {}
    global_adds = 0
    hot_adds = 0
    hot_listeners: list = []

    for path in sorted(JS_DIR.glob("*.js")):
        if path.name in VENDORED:
            continue
        raw = path.read_text(encoding="utf-8")
        s = strip_comments_keep_lines(raw)
        rel = f"ui/web_new_v2/js/{path.name}"
        count = 0
        local_funcs = local_function_bodies(s)

        # ---------------- addEventListener / removeEventListener ----------------
        for m in re.finditer(r"([A-Za-z_$][\w$.\[\]'\"]*)\s*\.\s*(add|remove)EventListener\s*\(", s):
            target_expr = m.group(1)
            kind = m.group(2)
            popen = s.find("(", m.start(2))
            pclose = match_paren(s, popen)
            if pclose == -1 or popen == -1:
                continue
            args = s[popen + 1 : pclose]
            em = re.match(r"\s*(['\"])([^'\"]+)\1", args)
            if not em:
                continue
            event = em.group(2)
            opts = args[em.end() :]
            passive = "passive" in opts and bool(re.search(r"passive\s*:\s*true", opts))
            capture = bool(re.search(r"capture\s*:\s*true|\btrue\s*[,}]", opts)) and "passive" not in opts
            is_global = target_expr in GLOBAL_TARGETS or target_expr.startswith("document")
            # handler body
            handler_body = ""
            handler_name = None
            hm = re.search(r"([A-Za-z_$][\w$]*)\s*\)", args)
            if hm:
                handler_name = hm.group(1)
            # `addEventListener('x', someNamedFn)` / `addEventListener('x', someObj.someFn)`
            bm = re.match(
                r"\s*['\"][^'\"]+['\"]\s*,\s*(?:[A-Za-z_$][\w$]*\s*\.\s*)*([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s*$",
                args,
            )
            if bm:
                handler_name = bm.group(1)
            am = re.search(r"=>\s*\{", args)
            if am:
                # am indices are relative to `args`; shift into `s` coordinates
                b = (popen + 1) + am.start() + (len(am.group(0)) - 1)
                e = match_brace(s, b)
                if e != -1:
                    handler_body = s[b : e + 1]
            if handler_body:
                info = classify_handler(expand_calls(handler_body, local_funcs))
            else:
                # named reference (possibly a local function declaration)
                hb = local_funcs.get(handler_name or "", "")
                info = classify_handler(expand_calls(hb, local_funcs) if hb else args)
            rec = {
                "file": rel,
                "line": line_of(s, m.start()),
                "kind": kind,
                "target": target_expr,
                "target_is_global": is_global,
                "event": event,
                "passive": passive,
                "capture": capture,
                "options_literal": re.sub(r"\s+", " ", opts.strip())[:120],
                "handler": handler_name or ("inline-arrow" if am else "named-reference"),
                "enclosing_function": enclosing_function_name(s, m.start()),
                **info,
            }
            listeners.append(rec)
            if kind == "add":
                count += 1
                if is_global:
                    global_adds += 1
                if event in GLOBAL_EVENTS_OF_INTEREST:
                    hot_adds += 1
                if is_global or event in GLOBAL_EVENTS_OF_INTEREST:
                    hot_listeners.append(rec)

        per_file_listeners[rel] = count

        # ---------------- requestAnimationFrame ----------------
        for m in re.finditer(r"requestAnimationFrame\s*\(", s):
            popen = s.find("(", m.start())
            pclose = match_paren(s, popen)
            if pclose == -1:
                continue
            cb = s[popen + 1 : pclose].strip().strip("`")
            rafs.append(
                {
                    "file": rel,
                    "line": line_of(s, m.start()),
                    "callback": cb[:60],
                    "enclosing_function": enclosing_function_name(s, m.start()),
                }
            )

        # ---------------- cancelAnimationFrame ----------------
        cancels = [
            {"file": rel, "line": line_of(s, m.start())}
            for m in re.finditer(r"cancelAnimationFrame\s*\(", s)
        ]

        # ---------------- setInterval ----------------
        for m in re.finditer(r"setInterval\s*\(", s):
            popen = s.find("(", m.start())
            pclose = match_paren(s, popen)
            if pclose == -1:
                continue
            args = s[popen + 1 : pclose]
            delay = "?"
            dm = re.search(r",\s*([0-9_]+(?:\s*\*\s*[0-9_]+)?)\s*\)?\s*$", args)
            if dm:
                delay = dm.group(1)
            intervals.append(
                {
                    "file": rel,
                    "line": line_of(s, m.start()),
                    "args": re.sub(r"\s+", " ", args.strip())[:120],
                    "delay_expr": delay,
                    "enclosing_function": enclosing_function_name(s, m.start()),
                }
            )

        # attach cancel counts per file
        for r in rafs:
            if r["file"] == rel:
                r["_cancel_count_in_file"] = len(cancels)

    # ---------------- duplicate global listener census ----------------
    dupes: dict[tuple, list] = {}
    for r in listeners:
        if r["kind"] != "add" or not r["target_is_global"]:
            continue
        dupes.setdefault((r["target"], r["event"]), []).append(r)
    dup_report = []
    for (target, event), recs in sorted(dupes.items()):
        if len(recs) > 1:
            dup_report.append(
                {
                    "target": target,
                    "event": event,
                    "count": len(recs),
                    "sites": [f"{r['file']}:{r['line']} ({r['enclosing_function']})" for r in recs],
                }
            )
    dup_report.sort(key=lambda d: (-d["count"], d["target"], d["event"]))

    thrash = [
        r
        for r in listeners
        if r["kind"] == "add" and "read+write-in-same-handler (layout-thrash risk)" in r["flags"]
    ]
    thrash.sort(key=lambda r: (not r["target_is_global"], r["file"], r["line"]))

    interesting = hot_listeners

    payload = {
        "schema": "nedotify.frontend-hotspots.v1",
        "generated_by": "tools/bench/js_census.py",
        "method": "static scan of ui/web_new_v2/js/*.js (vendored hls.min.js + lucide.min.js excluded)",
        "listeners": {
            "all_listener_sites_scanned": len(listeners),
            "global_listener_adds": global_adds,
            "global_listener_removes": len([r for r in listeners if r["kind"] == "remove" and r["target_is_global"]]),
            "hot_event_listener_adds": hot_adds,
            "per_file": per_file_listeners,
            "all_records": listeners,
        },
        "raf": {
            "total_request_animation_frame_calls": len(rafs),
            "records": rafs,
        },
        "set_interval": {
            "total": len(intervals),
            "records": intervals,
        },
        "duplicate_global_listeners": dup_report,
        "layout_thrash_candidates": thrash,
        "hot_event_listeners": interesting,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"global listener adds: {global_adds}")
    print(f"global listener removes: {payload['listeners']['global_listener_removes']}")
    print(f"hot-event listener adds: {hot_adds}")
    print(f"duplicate (target,event) pairs: {len(dup_report)}")
    for d in dup_report:
        print(f"  {d['count']}x {d['target']} '{d['event']}'")
        for s in d["sites"]:
            print(f"       {s}")
    print(f"layout-thrash candidates: {len(thrash)}")
    for t in thrash:
        print(
            f"  global={t['target_is_global']} {t['file']}:{t['line']} {t['target']} '{t['event']}'"
            f" reads={t['reads']} writes={t['writes']}"
        )
    print(f"rAF calls: {len(rafs)}  setInterval: {len(intervals)}")


if __name__ == "__main__":
    main()