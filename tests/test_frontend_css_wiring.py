"""Static checks that every shipped stylesheet is actually applied.

Why this file exists
--------------------
`ui/web_new_v2/css/components/visual-polish.css` shipped for a long time
without ever being loaded: `index.html` links each component file individually
and never links `css/styles.css`, which was the only place that had an
`@import` for it. 22 of its 65 selectors were therefore inert - including the
only `:focus-visible` rings on `.nav-item` / `.track-item` / `.feed-card` and
the `prefers-reduced-motion` rule. Nothing failed: the app booted, the test
suite was green, and the visual guard was green too.

That last part is the real lesson, and the reason for these tests.
`tools/visual_guard/run_guard.py::css_declaration_guard` validates the *values*
of transition / animation / backdrop-filter / filter / will-change / contain
declarations. It scans every `.css` file under `ui/` **whether or not the
document links it**. So it is structurally incapable of noticing that a whole
stylesheet started (or stopped) being applied - the exact class of regression
that hid the polish layer. A pixel diff would catch it, but the golden
screenshots were never successfully captured, so nothing did.

These tests close that gap at the level a static check can: they assert the
wiring between the files on disk and the document that loads them.

They are static source assertions, not a runtime smoke test - see the header of
`test_frontend_js.py` for why this repository has no webview test harness.
"""

import os
import re

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(PROJECT_ROOT, "ui", "web_new_v2")
CSS_DIR = os.path.join(UI_DIR, "css")
INDEX_HTML = os.path.join(UI_DIR, "index.html")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def index_html():
    return read(INDEX_HTML)


@pytest.fixture(scope="module")
def linked_css(index_html):
    """Stylesheet hrefs the document actually loads, as repo-relative paths."""
    hrefs = re.findall(r'<link[^>]*\brel="stylesheet"[^>]*>', index_html, re.I)
    out = set()
    for tag in hrefs:
        m = re.search(r'\bhref="([^"]+)"', tag, re.I)
        if m:
            href = m.group(1).split("?")[0].split("#")[0]
            out.add(os.path.normpath(os.path.join(UI_DIR, href)))
    return out


def css_files_on_disk():
    found = set()
    for dirpath, _dirnames, filenames in os.walk(CSS_DIR):
        for name in filenames:
            if name.endswith(".css"):
                found.add(os.path.normpath(os.path.join(dirpath, name)))
    return found


# Files that are allowed to exist without being linked. Each entry is a
# *deliberate* exclusion, and adding to this list requires a reason.
#
#   styles.css - a reference index of the intended cascade order. index.html
#                links the component files individually; loading this file too
#                would import every one of them a second time and reorder the
#                cascade. It is documentation, not an asset.
INTENTIONALLY_UNLINKED = {
    os.path.normpath(os.path.join(CSS_DIR, "styles.css")),
}


def test_index_html_links_a_stylesheet_at_all(index_html):
    assert re.search(r'<link[^>]*\brel="stylesheet"', index_html, re.I), \
        "index.html loads no stylesheet - the UI would be unstyled"


def test_every_component_stylesheet_is_linked(linked_css):
    """The regression that started this file.

    Any `.css` under ui/web_new_v2/css that nothing links is dead weight at
    best and a silently missing feature at worst.
    """
    on_disk = css_files_on_disk()
    orphans = sorted(
        p for p in on_disk
        if p not in linked_css and p not in INTENTIONALLY_UNLINKED
    )
    assert not orphans, (
        "stylesheet(s) present in ui/web_new_v2/css but never linked from "
        "index.html, so every rule in them is inert:\n  "
        + "\n  ".join(os.path.relpath(p, UI_DIR) for p in orphans)
        + "\n\nEither add a <link rel=\"stylesheet\"> for it, or - if it is "
          "meant to stay a reference - record it in INTENTIONALLY_UNLINKED "
          "with a comment explaining why."
    )


def test_visual_polish_is_linked(linked_css):
    """Named explicitly because it was the actual silent regression."""
    polish = os.path.normpath(os.path.join(CSS_DIR, "components", "visual-polish.css"))
    assert polish in linked_css, (
        "components/visual-polish.css is not linked from index.html. It holds "
        "the :focus-visible rings for .nav-item/.track-item/.feed-card and the "
        "prefers-reduced-motion block; none of that is applied while it is "
        "unlinked."
    )


def test_styles_index_is_not_linked(linked_css):
    """styles.css imports everything index.html already links.

    Linking it as well would double-load ~200 KB of CSS and place the whole
    import chain after themes.css, changing the cascade.
    """
    styles = os.path.normpath(os.path.join(CSS_DIR, "styles.css"))
    assert styles not in linked_css, (
        "css/styles.css must not be linked: every file it @imports is already "
        "linked individually, so linking it re-imports them all and reorders "
        "the cascade."
    )


def test_polish_layer_is_linked_last(index_html):
    """Position is load-bearing, not cosmetic.

    visual-polish.css is the override layer: it must resolve after tokens.css,
    the component sheets and themes.css, or themes.css silently wins over the
    rules meant to override it.
    """
    order = [
        m.group(1).split("?")[0]
        for m in re.finditer(r'<link[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"', index_html, re.I)
    ]
    polish_positions = [i for i, h in enumerate(order) if "visual-polish" in h]
    assert polish_positions, "visual-polish.css is not linked at all"
    assert polish_positions[-1] == len(order) - 1, (
        "visual-polish.css must be the LAST stylesheet; got order "
        f"{order} - themes.css would otherwise override the polish layer"
    )


def test_focus_ring_token_is_defined_in_a_linked_sheet(linked_css):
    """`--ring` is consumed by :focus-visible rules.

    If only an unlinked sheet defines it, every `box-shadow: var(--ring)`
    resolves to nothing and keyboard focus stays invisible - the state this
    whole change set set out to fix.
    """
    defining = []
    for path in linked_css:
        if not path.endswith(".css") or not os.path.isfile(path):
            continue
        if re.search(r"--ring\s*:", read(path)):
            defining.append(os.path.relpath(path, UI_DIR))
    assert defining, (
        "no linked stylesheet defines --ring, so the :focus-visible rules "
        "resolve box-shadow: var(--ring) to nothing and keyboard focus is "
        "invisible"
    )


def test_unlinked_allowlist_entries_still_exist():
    """Keep the allowlist honest - a stale entry silently weakens the check."""
    missing = [
        os.path.relpath(p, UI_DIR)
        for p in INTENTIONALLY_UNLINKED
        if not os.path.isfile(p)
    ]
    assert not missing, (
        "INTENTIONALLY_UNLINKED references files that no longer exist: "
        f"{missing}"
    )