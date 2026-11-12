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
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(PROJECT_ROOT, "ui", "web_new_v2")
CSS_DIR = os.path.join(UI_DIR, "css")
JS_DIR = os.path.join(UI_DIR, "js")
INDEX_HTML = os.path.join(UI_DIR, "index.html")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def index_html():
    return read(INDEX_HTML)


@pytest.fixture(scope="module")
def linked_css(index_html):
    """Eager hrefs and view-pack slots the loader can fetch, repo-relative."""
    hrefs = re.findall(r'<link[^>]*\brel="stylesheet"[^>]*>', index_html, re.I)
    out = set()
    for tag in hrefs:
        m = re.search(r'\bhref="([^"]+)"', tag, re.I)
        if m:
            href = m.group(1).split("?")[0].split("#")[0]
            out.add(os.path.normpath(os.path.join(UI_DIR, href)))
        slot = re.search(r'data-nedotify-deferred-style="([^"]+)"', tag, re.I)
        if slot:
            manifest = {
                "search": "css/components/search-refresh.css",
                "library": "css/components/library-refresh.css",
                "downloads": "css/components/downloads-view.css",
                "smartPlaylists": "css/components/smart-playlists.css",
                "featureTools": "css/components/feature-tools.css",
                "settings": "css/components/settings-refresh.css",
                "profile": "css/components/profile-refresh.css",
                "stylePicker": "css/components/ui-style-picker.css",
                "macosTokens": "../MACos_ui/tokens.css",
                "macosInterface": "../MACos_ui/interface.css",
                "macosSettings": "../MACos_ui/settings.css",
                "macosLibrary": "../MACos_ui/library.css",
            }
            out.add(os.path.normpath(os.path.join(UI_DIR, manifest[slot.group(1)])))
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


def test_deferred_view_styles_keep_authored_cascade_slots(index_html):
    tags = re.findall(r'<link[^>]*\brel="stylesheet"[^>]*>', index_html, re.I)
    slot_order = [
        re.search(r'data-nedotify-deferred-style="([^"]+)"', tag, re.I).group(1)
        for tag in tags if 'data-nedotify-deferred-style=' in tag
    ]
    assert slot_order == [
        "search", "library", "downloads", "featureTools",
        "settings", "profile", "stylePicker", "macosTokens", "macosInterface",
        "macosSettings", "macosLibrary",
    ]
    assert index_html.index('href="css/themes.css') < index_html.index('href="css/components/visual-polish.css')
    assert index_html.index('href="css/components/visual-polish.css') < index_html.index('data-nedotify-deferred-style="stylePicker"')


def test_custom_background_blur_control_matches_runtime_ceiling(index_html):
    slider = re.search(r'<input[^>]*id="slider-bg-blur"[^>]*>', index_html)
    assert slider and re.search(r'\bmax="16"', slider.group(0))
    appearance = read(os.path.join(JS_DIR, "ui-style.js"))
    assert "Math.min(16, Number(setting('theme', 'bg_blur', 0)) || 0)" in appearance


def test_style_loader_uses_the_real_deferred_slots():
    """Run the production loader with a deterministic DOM/link harness."""
    import json

    from tests.jsdom import run_node

    loader = json.dumps(read(os.path.join(JS_DIR, "style-loader.js")))
    script = f"""
const source = {loader};
const names = ['search','library','downloads','featureTools','settings','profile','stylePicker','macosTokens','macosInterface','macosSettings','macosLibrary'];
const slots = new Map(names.map(name => {{
  const node = {{ _href:'', media:'not all', onload:null, onerror:null }};
  Object.defineProperty(node, 'href', {{get(){{return this._href;}}, set(value){{this._href=value;queueMicrotask(()=>this.onload?.());}}}});
  return [name,node];
}}));
const root = {{dataset:{{uiStyle:'standard'}}, classList:{{values:new Set(),add(v){{this.values.add(v);}},remove(v){{this.values.delete(v);}}}}}};
let mutation;
let activePage = 'library';
globalThis.document = {{documentElement:root,querySelector(selector){{
  if (selector === '#view-settings.active') return activePage === 'settings' ? {{id:'view-settings'}} : null;
  if (selector === '.view-page.active') return {{id:'view-'+activePage}};
  const name=selector.match(/deferred-style=\"([^\"]+)/)?.[1];
  return slots.get(name)||null;
}}}};
globalThis.window = {{}};
globalThis.MutationObserver = class {{constructor(fn){{mutation=fn;}} observe(){{}}}};
eval(source);
await window.NeDotifyStyles.ready;
if ([...slots.values()].some(node=>node.href)) throw new Error('view packs loaded before navigation');
await window.NeDotifyStyles.ensureForPage('library');
for (const name of ['library','downloads']) if (!slots.get(name).href) throw new Error('library pack missing: '+name);
if (slots.get('search').href) throw new Error('unrequested search pack loaded');
if (slots.get('library').media !== 'all') throw new Error('loaded stylesheet remained disabled');
root.dataset.uiStyle='macos';
mutation();
await new Promise(resolve=>setTimeout(resolve,0));
for (const name of ['macosTokens','macosInterface','macosLibrary']) if (!slots.get(name).href) throw new Error('macOS pack missing: '+name);
activePage='settings';
mutation();
await new Promise(resolve=>setTimeout(resolve,0));
if (!slots.get('macosSettings').href) throw new Error('macOS Settings pack missing while its overlay is open');
if (root.classList.values.has('css-loading')) throw new Error('loading guard stuck on');
"""
    run_node(script)


def test_glass_blur_tokens_have_one_owner_and_a_surface_ceiling():
    from tinycss2 import parse_declaration_list, parse_stylesheet

    token_css = read(os.path.join(CSS_DIR, "tokens.css"))
    base_css = read(os.path.join(CSS_DIR, "components", "base.css"))
    tokens = ("--glass-blur", "--blur-surface-cap", "--blur-sm", "--blur-md", "--blur-lg", "--blur-xl")
    for token in tokens:
        assert re.search(rf"{re.escape(token)}\s*:", token_css)
        assert not re.search(rf"{re.escape(token)}\s*:", base_css)
    assert "--blur-surface-cap: 16px" in token_css
    assert "min(calc(var(--glass-blur) * 2), var(--blur-surface-cap))" in token_css

    mac_files = ("interface.css", "library.css", "settings.css")
    for name in mac_files:
        mac_css = read(os.path.join(PROJECT_ROOT, "ui", "MACos_ui", name))
        assert "min(var(--mac-panel-blur,38px),var(--blur-surface-cap,16px))" in mac_css


    # Resolve authored blur declarations for representative real DOM nodes.
    # This catches an accidental return to a larger literal on a heavy surface.
    import cssselect2
    from lxml import html

    markup = html.fromstring("""
    <html><body>
      <div id="lyrics-overlay"></div><div id="queue-drawer"></div>
      <div id="player-bar"></div><div class="settings-modal-card"></div>
      <div class="search-suggestions-dropdown"></div>
    </body></html>
    """)
    wrapper = cssselect2.ElementWrapper.from_html_root(markup)
    targets = {el.etree_element.get("id") or el.etree_element.get("class") for el in wrapper.iter_subtree()}
    assert {"lyrics-overlay", "queue-drawer", "player-bar", "settings-modal-card", "search-suggestions-dropdown"} <= targets

    css_paths = [
        os.path.join(CSS_DIR, "components", name)
        for name in ("base.css", "player-bar.css", "lyrics.css")
    ]
    for path in css_paths:
        rules = parse_stylesheet(read(path), skip_comments=True, skip_whitespace=True)
        for rule in rules:
            if rule.type != "qualified-rule":
                continue
            selector_text = "".join(token.serialize() for token in rule.prelude)
            try:
                selectors = cssselect2.compile_selector_list(selector_text)
            except cssselect2.SelectorError:
                continue
            if not any(selector.pseudo_element is None and selector.test(element)
                       for selector in selectors for element in wrapper.iter_subtree()):
                continue
            declarations = parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
            for declaration in declarations:
                if declaration.type == "declaration" and declaration.lower_name in ("backdrop-filter", "-webkit-backdrop-filter"):
                    value = "".join(part.serialize() for part in declaration.value)
                    assert not re.search(r"blur\(\s*(?:20|24|28|32|40)px", value), (path, selector_text, value)


def test_css_dedup_preserves_effective_transitions_and_glow_defaults():
    base_css = read(os.path.join(CSS_DIR, "components", "base.css"))
    token_css = read(os.path.join(CSS_DIR, "tokens.css"))

    context_rules = re.findall(r"(?m)^\.context-menu-item\s*\{([^}]*)\}", base_css)
    assert len(context_rules) == 1
    assert "padding: 10px 20px" in context_rules[0]
    assert "gap: 10px" in context_rules[0]
    assert "transition: background 0.2s" in context_rules[0]
    assert ".context-menu-item:hover { background: rgba(255,255,255,0.1); }" in base_css

    settings_rule = re.search(
        r"#view-settings\.view-page\.settings-overlay\s*\{([^}]*)\}", base_css
    )
    assert settings_rule
    assert "backdrop-filter: none" in settings_rule.group(1)
    assert "transition: none" in settings_rule.group(1)
    settings_refresh = read(os.path.join(CSS_DIR, "components", "settings-refresh.css"))
    assert "#view-settings.view-page.settings-overlay { transition: none; }" in settings_refresh
    assert "backdrop-filter: blur(var(--glass-blur))" in settings_refresh
    assert "--player-glow-opacity: 0.55" in token_css


def test_base_refresh_conflicts_match_the_reviewed_allowlist():
    import json
    from collections import defaultdict

    from tools.bench.css_inventory import parse_file

    files = [os.path.join(CSS_DIR, "components", "base.css")]
    files.extend(sorted(
        os.path.join(CSS_DIR, "components", name)
        for name in os.listdir(os.path.join(CSS_DIR, "components"))
        if name.endswith("-refresh.css")
    ))
    groups = defaultdict(list)
    for path in files:
        rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
        for declaration in parse_file(Path(path), rel):
            if declaration.kind == "declaration":
                groups[declaration.selector, declaration.prop].append(declaration)

    current = []
    for (selector, prop), declarations in sorted(groups.items()):
        if len({item.value for item in declarations}) < 2:
            continue
        scopes = sorted({scope for item in declarations for scope in item.at_rules})
        stateful = any(token in selector.lower() for token in (
            ":hover", ":focus", ":active", ":disabled", ":checked", ".active",
            ".hidden", ".selected", ".perf-", ".battery-", ".no-backdrop",
            ".unfocused-", "[data-theme", "[data-ui-style", "[data-macos",
        ))
        reason = "conditional-cascade-override" if scopes else "state-selector-override" if stateful else "unconditional-conflict"
        current.append({
            "selector": selector,
            "property": prop,
            "reason": reason,
            "variants": [{
                "file": item.file.replace("\\", "/"), "line": item.line,
                "value": item.value, "at_rules": list(item.at_rules),
                "important": item.important,
            } for item in sorted(declarations, key=lambda item: (item.file, item.line, item.value))],
        })

    manifest_path = os.path.join(PROJECT_ROOT, "docs", "audits", "remediation", "CSS_CONFLICT_ALLOWLIST.json")
    manifest = json.loads(read(manifest_path))
    assert current == manifest["entries"], "New or changed base/refresh conflict: classify it and review the CSS allowlist"
    # Collection layout consolidation and removal of the retired genre tiles
    # removed obsolete sidebar/tab/search conflicts.
    # Equality above still pins every reviewed selector, value, scope and line.
    # Native dialogs animate on open and disable that motion when requested.
    # Atmosphere owns reduced-motion lifecycle; the retired particle display
    # override no longer hides a still-running canvas through CSS.
    assert len(current) == 220
    assert sum(item["reason"] == "conditional-cascade-override" for item in current) == 219
    assert sum(item["reason"] == "state-selector-override" for item in current) == 1
    assert not any(item["reason"] == "unconditional-conflict" for item in current)


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


def test_dark_palette_has_one_owner():
    themes = read(os.path.join(CSS_DIR, "themes.css"))
    refresh = read(os.path.join(CSS_DIR, "components", "home-refresh.css"))
    assert len(re.findall(r":root\[data-theme=\"dark\"\]", themes)) == 1
    assert ':root[data-theme="dark"]' not in refresh


def test_player_bar_tokens_cover_the_home_refresh_responsive_range():
    refresh = read(os.path.join(CSS_DIR, "components", "home-refresh.css"))
    assert "@media (max-width: 900px) and (min-width: 761px)" in refresh
    assert "--player-bar-height: 80px; --player-bar-offset: 16px;" in refresh


def test_local_cyrillic_font_fallback_is_bundled_and_external_font_hosts_are_removed(index_html):
    fonts_css = read(os.path.join(CSS_DIR, "fonts.css"))
    assert "font-family: 'NeDotify Cyrillic'" in fonts_css
    assert "unicode-range: U+0301, U+0400-045F" in fonts_css
    fonts = os.path.join(UI_DIR, "assets", "fonts")
    for name in (
        "noto-sans-cyrillic-400-normal.woff2", "noto-sans-cyrillic-ext-400-normal.woff2",
        "noto-sans-cyrillic-600-normal.woff2", "noto-sans-cyrillic-ext-600-normal.woff2",
        "noto-sans-cyrillic-700-normal.woff2", "noto-sans-cyrillic-ext-700-normal.woff2",
        "LICENSE-NotoSans.txt",
    ):
        assert os.path.isfile(os.path.join(fonts, name)), name
    assert "fonts.googleapis.com" not in index_html
    assert "fonts.gstatic.com" not in index_html
