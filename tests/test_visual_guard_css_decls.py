"""Self-tests for the visual guard's CSS declaration contract.

The CSS half of `tools/visual_guard/run_guard.py` is supposed to be the
*enforced* visual contract: nothing may quietly disappear from the set of
transition / animation / backdrop-filter / filter declarations, and nothing that
is already painted may be retuned.

It used to enforce nothing, for two independent reasons:

  1. keys embedded the 1-based line number (``f"{rel}:{i}:{text}"``), so
     inserting one blank line shifted every later key and the intersection with
     the baseline collapsed to the empty set;
  2. ``ok`` was ``not changed``, where ``changed`` was computed over that
     intersection alone - ``removed`` and ``added`` were reported and then
     ignored.

Together those made the guard pass VACUOUSLY: measured on a clean tree,
baseline 296 / current 745 / intersection 0 / ``ok is True``. Deleting every
transition and every blur in the app still reported PASS.

Every test here runs against a synthetic tree in ``tmp_path`` - no GUI, no
app, no network, and not the real ``ui/`` directory - so they are fast and
hermetic. `tests/test_visual_guard_diff.py` covers the pixel half.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.visual_guard import run_guard  # noqa: E402

CSS = """\
:root {
  --blur-md: 8px;
  --glass-blur: 8px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}

.glass-panel {
  backdrop-filter: blur(var(--blur-md));
  -webkit-backdrop-filter: blur(var(--blur-md));
  transition: background-color 0.2s ease, opacity 0.2s ease;
}

.button {
  animation: fade-in 0.25s ease forwards;
  will-change: transform;
  contain: layout paint;
}
"""

HTML = """\
<div class="overlay" style="backdrop-filter: blur(12px); background: rgba(0,0,0,0.65)">
  <button class="btn" style="transition: width 0.2s ease;">go</button>
</div>
"""

JS = """\
function show(el) {
  el.style.transition = 'opacity 0.2s ease';
  el.style.filter = 'blur(var(--player-glow-blur)) brightness(0.35)';
  requestAnimationFrame(function () { el.classList.add('on'); });
}
"""


def _write_tree(root: Path, css: str = CSS, html: str = HTML, js: str = JS) -> Path:
    (root / "ui" / "app" / "css").mkdir(parents=True, exist_ok=True)
    (root / "ui" / "app" / "js").mkdir(parents=True, exist_ok=True)
    (root / "ui" / "app" / "css" / "main.css").write_text(css, encoding="utf-8")
    (root / "ui" / "app" / "index.html").write_text(html, encoding="utf-8")
    (root / "ui" / "app" / "js" / "app.js").write_text(js, encoding="utf-8")
    return root


def _edit(root: Path, rel: str, text: str) -> None:
    (root / rel).write_text(text, encoding="utf-8")


def _guard(root: Path) -> dict:
    return run_guard.css_declaration_guard(root=root)


def _baseline(root: Path) -> dict:
    """Record the current tree as the baseline, exactly like the CLI flag does."""
    n = run_guard.write_css_baseline(root=root)
    return _guard(root)


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    """A synthetic tree with a freshly recorded baseline."""
    _write_tree(tmp_path)
    res = _baseline(tmp_path)
    assert res["ok"] is True, res
    return {"root": tmp_path, "clean": res}


# --------------------------------------------------------------------------
# 1. line-number independence - the bug that made the guard vacuous
# --------------------------------------------------------------------------
def test_inserting_a_blank_line_is_not_a_regression(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css", "\n" + CSS)          # one blank line, top
    res = _guard(root)
    assert res["changed"] == []
    assert res["removed"] == []
    assert res["ok"] is True


def test_inserting_unrelated_lines_is_not_a_regression(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          "/* a new banner comment that mentions a transition on purpose */\n"
          ".totally-unrelated { color: red; }\n" + CSS)
    res = _guard(root)
    assert res["removed"] == []
    assert res["changed"] == []
    assert res["ok"] is True


def test_removing_unrelated_lines_is_not_a_regression(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace(".button {\n", ".button {\n  padding: 4px;\n"))
    res = _guard(root)
    assert res["changed"] == []
    assert res["removed"] == []
    assert res["ok"] is True


def test_reordering_declarations_inside_a_file_is_not_a_regression(tree):
    root = tree["root"]
    # same declarations, `.button` block moved above `.glass-panel`
    blocks = CSS.split("\n\n")
    reordered = "\n\n".join([blocks[0], blocks[2], blocks[1]]) + "\n"
    _edit(root, "ui/app/css/main.css", reordered)
    res = _guard(root)
    assert res["changed"] == []
    assert res["removed"] == []
    assert res["ok"] is True


def test_baseline_comparison_is_not_vacuous(tree):
    """A passing run must actually have compared something."""
    res = _guard(tree["root"])
    assert res["ok"] is True
    assert res["baseline_declarations"] > 10
    assert res["current_declarations"] == res["baseline_declarations"]
    assert res["intersection_keys"] > 0
    assert res["vacuous"] is False


# --------------------------------------------------------------------------
# 2. changing an existing value is a regression
# --------------------------------------------------------------------------
def test_changing_a_transition_value_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("transition: background-color 0.2s ease, opacity 0.2s ease;",
                      "transition: background-color 0.05s linear, opacity 0.2s ease;"))
    res = _guard(root)
    assert res["ok"] is False
    assert len(res["changed"]) == 1
    assert res["changed"][0]["key"] == "ui/app/css/main.css|transition"
    assert any("background-color 0.2s ease" in v for v in res["changed"][0]["before"])
    assert any("0.05s linear" in v for v in res["changed"][0]["after"])
    assert res["removed"], "the retuned value must also be reported as removed"


def test_changing_an_easing_curve_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("--ease-out: cubic-bezier(0.16, 1, 0.3, 1);",
                      "--ease-out: cubic-bezier(0.4, 0, 0.2, 1);"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/css/main.css|--ease-out"]


def test_changing_an_animation_duration_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("animation: fade-in 0.25s ease forwards;",
                      "animation: fade-in 1s ease forwards;"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/css/main.css|animation"]


def test_changing_a_will_change_value_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("will-change: transform;", "will-change: opacity, transform;"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/css/main.css|will-change"]


# --------------------------------------------------------------------------
# 3. deleting a declaration is a regression
# --------------------------------------------------------------------------
def test_deleting_a_backdrop_filter_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("  backdrop-filter: blur(var(--blur-md));\n", ""))
    res = _guard(root)
    assert res["ok"] is False
    assert res["removed"], "a deleted backdrop-filter must be reported"
    assert any("ui/app/css/main.css|backdrop-filter" in r for r in res["removed"])
    assert not any("|backdrop-filter" in c["key"] for c in res["changed"])


def test_deleting_a_webkit_backdrop_filter_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("  -webkit-backdrop-filter: blur(var(--blur-md));\n", ""))
    res = _guard(root)
    assert res["ok"] is False
    assert any("|-webkit-backdrop-filter" in r for r in res["removed"])


def test_deleting_every_guarded_declaration_fails(tree):
    """The regression the original guard could not see: the whole contract gone."""
    root = tree["root"]
    _edit(root, "ui/app/css/main.css", ".glass-panel { color: red; }\n")
    _edit(root, "ui/app/index.html", "<div>nothing guarded here</div>\n")
    _edit(root, "ui/app/js/app.js", "function show(el) { el.classList.add('on'); }\n")
    res = _guard(root)
    assert res["current_declarations"] == 0
    assert res["intersection_keys"] == 0
    assert res["ok"] is False, "deleting the entire contract must FAIL"
    assert len(res["removed"]) == tree["clean"]["baseline_declarations"]
    assert res["changed"] == []


def test_deleting_a_whole_file_fails(tree):
    root = tree["root"]
    (root / "ui" / "app" / "js" / "app.js").unlink()
    res = _guard(root)
    assert res["ok"] is False
    assert any(r.startswith("ui/app/js/app.js|") for r in res["removed"])


def test_removing_a_custom_property_definition_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("  --blur-md: 8px;\n", ""))
    res = _guard(root)
    assert res["ok"] is False
    assert any("|--blur-md" in r for r in res["removed"])


# --------------------------------------------------------------------------
# 4. adding a declaration is allowed (accessibility / polish work adds rules)
# --------------------------------------------------------------------------
def test_adding_a_focus_visible_rule_is_allowed(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css", CSS + """
.btn:focus-visible {
  outline: 2px solid var(--accent);
  transition: outline-color 0.15s ease;
}
""")
    res = _guard(root)
    assert res["changed"] == []
    assert res["removed"] == []
    assert res["added"], "an addition must still be reported"
    assert any("outline-color 0.15s ease" in a for a in res["added"])
    assert res["ok"] is True, "adding a rule must not fail the contract"


def test_adding_a_new_inline_style_in_html_is_allowed(tree):
    root = tree["root"]
    _edit(root, "ui/app/index.html",
          HTML.replace("</div>", '  <span style="will-change: contents;">x</span>\n</div>'))
    res = _guard(root)
    assert res["ok"] is True
    assert any("ui/app/index.html|will-change" in a for a in res["added"])


# --------------------------------------------------------------------------
# 5. guarded custom properties: a changed VALUE is caught even though the
#    consuming declaration text (`blur(var(--blur-md))`) did not change
# --------------------------------------------------------------------------
def test_changing_a_guard_custom_property_value_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("--blur-md: 8px;", "--blur-md: 18px;"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/css/main.css|--blur-md"]
    assert res["changed"][0]["before"] == ["8px"]
    assert res["changed"][0]["after"] == ["18px"]


@pytest.mark.parametrize("prop,old,new", [
    ("--blur-md", "8px", "18px"),
    ("--glass-blur", "8px", "16px"),
    ("--app-bg-opacity", "1", "0.8"),
    ("--blur-lg", "12px", "0px"),
    ("--player-glow-blur", "40px", "10px"),
    ("--glow-strength", "0.5", "0.2"),
    ("--transition-fast", "120ms", "0ms"),
    ("--anim-duration", "0.3s", "0.9s"),
    ("--ease-standard", "ease", "linear"),
    ("--dur-slow", "1s", "0.2s"),
    ("--duration-x", "0.2s", "0.4s"),
])
def test_every_watched_variable_prefix_is_guarded(tmp_path, prop, old, new):
    """A watched variable's DEFINITION must be guarded, not just its uses."""
    def write(value: str) -> None:
        _write_tree(tmp_path, css=(
            ":root {\n"
            f"  {prop}: {value};\n"
            "}\n\n"
            ".glass-panel {\n"
            "  backdrop-filter: blur(var(--blur-md));\n"
            "  transition: opacity 0.2s ease;\n"
            "}\n"
        ), html="", js="")

    write(old)
    assert _baseline(tmp_path)["ok"] is True
    write(new)
    res = _guard(tmp_path)
    assert res["ok"] is False, f"{prop} must be guarded"
    assert [c["key"] for c in res["changed"]] == [f"ui/app/css/main.css|{prop}"]
    assert res["changed"][0]["before"] == [old]
    assert res["changed"][0]["after"] == [new]


# --------------------------------------------------------------------------
# multiple declarations of the same property in one file
# --------------------------------------------------------------------------
def test_repeated_property_in_one_file_keeps_a_list_per_key(tmp_path):
    """Two `transition` declarations in one file must not collide silently."""
    _write_tree(tmp_path, css="""\
.a { transition: opacity 0.2s ease; }
.b { transition: opacity 0.2s ease; }
.c { transition: transform 0.4s ease; }
""", html="", js="")
    buckets = run_guard.collect_declarations(tmp_path)
    assert buckets == {"ui/app/css/main.css|transition":
                       ["opacity 0.2s ease", "opacity 0.2s ease",
                        "transform 0.4s ease"]}


def test_deleting_one_of_two_identical_declarations_fails(tree):
    """A duplicate value is still two declarations; losing one is a removal."""
    root = tree["root"]
    doubled = CSS.replace("  will-change: transform;",
                          "  will-change: transform;\n  will-change: transform;")
    _edit(root, "ui/app/css/main.css", doubled)
    _baseline(root)                       # re-record the doubled baseline
    _edit(root, "ui/app/css/main.css", CSS)
    res = _guard(root)
    assert res["ok"] is False, "losing one of two identical declarations is a removal"
    assert res["changed"] == []           # nothing was substituted, one was lost
    assert res["removed"] == ["ui/app/css/main.css|will-change = transform"]


def test_adding_a_second_declaration_of_an_existing_property_is_allowed(tree):
    root = tree["root"]
    _edit(root, "ui/app/css/main.css",
          CSS.replace("  will-change: transform;",
                      "  will-change: transform;\n  will-change: opacity;"))
    res = _guard(root)
    assert res["changed"] == []
    assert res["removed"] == []
    assert any("opacity" in a for a in res["added"])
    assert res["ok"] is True


# --------------------------------------------------------------------------
# html / js inline styles are part of the contract
# --------------------------------------------------------------------------
def test_inline_styles_in_html_and_js_are_tracked(tree):
    res = _guard(tree["root"])
    assert res["ok"] is True
    buckets = run_guard.collect_declarations(tree["root"])
    assert "ui/app/index.html|backdrop-filter" in buckets
    assert "ui/app/index.html|transition" in buckets
    assert "ui/app/js/app.js|transition" in buckets
    assert "ui/app/js/app.js|filter" in buckets


def test_changing_a_js_inline_transition_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/js/app.js",
          JS.replace("el.style.transition = 'opacity 0.2s ease';",
                     "el.style.transition = 'opacity 0.8s ease';"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/js/app.js|transition"]


def test_changing_an_html_inline_backdrop_filter_fails(tree):
    root = tree["root"]
    _edit(root, "ui/app/index.html",
          HTML.replace("backdrop-filter: blur(12px)", "backdrop-filter: blur(2px)"))
    res = _guard(root)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/index.html|backdrop-filter"]


def test_lines_that_paint_nothing_are_not_tracked(tmp_path):
    """Comments, selectors and plain JS calls are deliberately out of scope."""
    _write_tree(tmp_path, css="""\
/* remember to keep the transition on .card */
.perf-low #sidebar, #player-bar {
  color: red;
}
.button { animation: fade-in 0.25s ease; }
""", html="<!-- a transition used to live here -->\n<div>ok</div>\n",
        js="requestAnimationFrame(draw);\nconst disableAnimations = true;\n")
    buckets = run_guard.collect_declarations(tmp_path)
    assert buckets == {"ui/app/css/main.css|animation": ["fade-in 0.25s ease"]}


# --------------------------------------------------------------------------
# baseline writer + backward compatibility with older baseline shapes
# --------------------------------------------------------------------------
def test_written_baseline_has_the_documented_shape(tree):
    root = tree["root"]
    path = root / "tools" / "bench" / "results" / "animation_declarations.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "nedotify.animation-declarations.v2"
    assert payload["declarations"]
    for rec in payload["declarations"]:
        assert set(rec) >= {"key", "file", "property", "value", "text"}
        assert rec["key"] == f"{rec['file']}|{rec['property']}"
    # no line numbers anywhere: they are what used to break the comparison
    assert "line" not in payload["declarations"][0]


def test_legacy_v0_baseline_still_loads_and_compares(tmp_path):
    """The ORIGINAL shape - key = '<file>:<line>:<text>' - must still work."""
    _write_tree(tmp_path)
    legacy = {"declarations": [
        {"key": "ui/app/css/main.css:4:.glass-panel {",
         "text": ".glass-panel { backdrop-filter: blur(var(--blur-md)); }"},
        {"key": "ui/app/css/main.css:5:",
         "text": "transition: background-color 0.2s ease, opacity 0.2s ease;"},
    ]}
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    buckets = run_guard._load_baseline(p)
    assert buckets == {
        "ui/app/css/main.css|backdrop-filter": ["blur(var(--blur-md))"],
        "ui/app/css/main.css|transition":
            ["background-color 0.2s ease, opacity 0.2s ease"],
    }
    # and those values do match the tree, so a guard run is clean for them
    cur = run_guard.collect_declarations(tmp_path)
    for k, v in buckets.items():
        assert k in cur
        assert set(v) <= set(cur[k])


def test_legacy_v1_css_inventory_baseline_still_loads(tmp_path):
    """The css_inventory.py shape - file/line/property/value - must still work."""
    _write_tree(tmp_path)
    legacy = {"declarations": [
        {"key": "ui/app/css/main.css:4:.glass-panel|backdrop-filter|blur(var(--blur-md))",
         "file": "ui/app/css/main.css", "line": 4, "selector": ".glass-panel",
         "property": "backdrop-filter", "value": "blur(var(--blur-md))",
         "important": False, "kind": "declaration"},
    ]}
    p = tmp_path / "legacy1.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    buckets = run_guard._load_baseline(p)
    assert buckets == {"ui/app/css/main.css|backdrop-filter": ["blur(var(--blur-md))"]}


def test_garbage_baseline_does_not_crash_the_guard(tmp_path):
    _write_tree(tmp_path)
    p = tmp_path / "junk.json"
    p.write_text(json.dumps({"declarations": [
        "not even a dict", {"key": "ui/app/css/main.css:1:opacity: 1"},
        {"no": "fields at all"}, {"key": "", "text": ""},
    ]}), encoding="utf-8")
    assert isinstance(run_guard._load_baseline(p), dict)


def test_unreadable_baseline_reports_an_error(tmp_path):
    _write_tree(tmp_path)
    path = run_guard._baseline_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    res = _guard(tmp_path)
    assert res["ok"] is False
    assert "unreadable" in res["error"]


def test_missing_baseline_reports_the_regeneration_hint(tmp_path):
    _write_tree(tmp_path)
    res = _guard(tmp_path)
    assert res["ok"] is False
    assert "missing" in res["error"]
    assert "--write-css-baseline" in res["hint"]


# --------------------------------------------------------------------------
# the watch lists and the scan scope are part of the contract itself
# --------------------------------------------------------------------------
def test_watch_lists_still_cover_the_documented_properties():
    for token in ("transition", "animation", "backdrop-filter", "filter:",
                  "will-change", "contain:"):
        assert token in run_guard.WATCHED_VALUE_TOKENS, token
    for var in ("--blur-", "--glass-blur", "--app-bg-opacity", "--player-glow-",
                "--glow", "--transition", "--anim", "--ease", "--dur",
                "--duration"):
        assert var in run_guard.WATCHED_VARS, var


def test_scan_scope_is_css_html_and_js():
    assert set(run_guard.GUARDED_SUFFIXES) == {".css", ".html", ".js"}


def test_custom_property_definitions_are_guarded_because_of_their_consumers(tmp_path):
    """The consumer line is byte-identical; only `--blur-md` moved. Still a fail.

    This is the gap the second class of guarded declarations exists for: rules
    read `backdrop-filter: blur(var(--blur-md))`, so recording only the literal
    text would show no diff while the painted radius changed.
    """
    consumer = ".glass-panel {\n  backdrop-filter: blur(var(--blur-md));\n}\n"

    def write(blur: str) -> None:
        _write_tree(tmp_path, css=f":root {{\n  --blur-md: {blur};\n}}\n" + consumer,
                    html="", js="")

    write("8px")
    assert _baseline(tmp_path)["ok"] is True
    write("18px")
    res = _guard(tmp_path)
    assert res["ok"] is False
    assert [c["key"] for c in res["changed"]] == ["ui/app/css/main.css|--blur-md"]
    # the consumer declaration itself is untouched, and must not be reported
    assert not any("backdrop-filter" in c["key"] for c in res["changed"])


# --------------------------------------------------------------------------
# public contract of the returned dict
# --------------------------------------------------------------------------
def test_result_keeps_its_public_keys(tree):
    res = _guard(tree["root"])
    for key in ("ok", "baseline_declarations", "current_declarations",
                "removed", "added", "changed", "note"):
        assert key in res, key
    assert isinstance(res["ok"], bool)
    assert isinstance(res["removed"], list)
    assert isinstance(res["added"], list)
    assert isinstance(res["changed"], list)
    assert isinstance(res["note"], str)


def test_guard_works_without_a_root_argument():
    """The default must still be the repository root - it is just slower."""
    res = run_guard.css_declaration_guard()
    assert "ok" in res
    assert res.get("baseline_declarations", 0) > 0
