"""Sidebar rail contract: collapsed state + pinned account group.

The nav rail has two behaviours that are easy to break silently because both
are pure CSS/markup with no runtime harness behind them:

* **Collapse.** Clicking the rail title shrinks the rail to icons only. The
  labels have to be wrapped in ``.nav-label`` to be animatable at all - they used
  to be bare text nodes, which no stylesheet can target - and the title needs a
  ``.sidebar-logo-icon`` slot plus two ``.sidebar-logo-text`` variants so that
  collapsing does not have to rewrite ``textContent`` mid-transition.
* **Pinned group.** ``.sidebar-spacer`` (flex:1) has to sit *above* the
  "Аккаунт & Опции" group. Below it, the group floated in the middle with dead
  space underneath instead of resting on the bottom of the rail.

The class name ``is-collapsed`` is the join between three files: ``pages.js``
toggles it, ``base.css`` styles it, and the markup it applies to. A rename in
any one of them disables the feature with no error anywhere, so pin the name.

Static assertions on shipped source, in the spirit of ``test_frontend_js.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "ui" / "web_new_v2" / "index.html"
PAGES_JS = REPO_ROOT / "ui" / "web_new_v2" / "js" / "pages.js"
SETTINGS_JS = REPO_ROOT / "ui" / "web_new_v2" / "js" / "settings.js"
BASE_CSS = REPO_ROOT / "ui" / "web_new_v2" / "css" / "components" / "base.css"

COLLAPSED_CLASS = "is-collapsed"
NAV_ITEM_COUNT = 6
ACCOUNT_PAGES = ("settings", "profile")


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _sidebar_markup() -> str:
    """The <aside id="sidebar"> ... </aside> block."""
    html = _html()
    start = html.index('<aside id="sidebar">')
    end = html.index("</aside>", start) + len("</aside>")
    return html[start:end]


def test_collapsed_class_is_shared_by_js_and_css() -> None:
    """pages.js toggles it, base.css styles it - the names must match."""
    assert COLLAPSED_CLASS in PAGES_JS.read_text(encoding="utf-8"), (
        f"pages.js must toggle .{COLLAPSED_CLASS} on #sidebar"
    )
    css = BASE_CSS.read_text(encoding="utf-8")
    assert f"#sidebar.{COLLAPSED_CLASS}" in css, (
        f"base.css must define #sidebar.{COLLAPSED_CLASS}; pages.js toggles a "
        f"class nothing styles"
    )


def test_collapsed_rail_actually_narrows_and_hides_labels() -> None:
    css = BASE_CSS.read_text(encoding="utf-8")
    block = css[css.index(f"#sidebar.{COLLAPSED_CLASS} {{") :]
    block = block[: block.index("}")]
    assert "width" in block, f"collapsed rail must narrow, got: {block}"
    assert "min-width" in block, (
        "min-width is what actually sizes a flex item; without it the rail "
        "stays 200px wide and the feature looks broken"
    )


def test_every_nav_label_is_wrapped() -> None:
    """Bare text nodes cannot be styled, so nothing would animate."""
    sidebar = _sidebar_markup()
    items = re.findall(r'<div class="nav-item[^"]*" data-page="([^"]+)"[^>]*>(.*?)</div>', sidebar, re.DOTALL)
    assert len(items) == NAV_ITEM_COUNT, f"expected {NAV_ITEM_COUNT} nav items, found {len(items)}"
    for page, body in items:
        assert '<span class="nav-label">' in body, (
            f"nav item {page!r} still has a bare text label; it needs "
            f'<span class="nav-label"> or the collapse animation has nothing to target'
        )


def test_collapsed_icons_have_tooltips() -> None:
    """Icon-only rows are unidentifiable without them."""
    sidebar = _sidebar_markup()
    for page, _ in re.findall(
        r'<div class="nav-item[^"]*" data-page="([^"]+)"([^>]*)>', sidebar
    ):
        assert 'title="' in _, f"nav item {page!r} has no title= tooltip"


def test_logo_has_icon_slot_and_both_title_variants() -> None:
    sidebar = _sidebar_markup()
    assert 'id="sidebar-logo"' in sidebar, "the title must be identifiable as the toggle"
    assert "sidebar-logo-icon" in sidebar, (
        "applyIconPack() rewrites the logo icon; it needs a dedicated slot so it "
        "cannot clobber the title text variants"
    )
    assert "sidebar-logo-full" in sidebar, 'expanded title "NeDotify" is missing'
    assert "sidebar-logo-initial" in sidebar, 'collapsed title "N" is missing'


def test_logo_title_is_the_toggle() -> None:
    sidebar = _sidebar_markup()
    tag = re.search(r'<div class="sidebar-logo"[^>]*>', sidebar)
    assert tag, "sidebar-logo element not found"
    markup = tag.group(0)
    assert 'role="button"' in markup, "the toggle must be announced as a button"
    assert 'tabindex="0"' in markup, "the toggle must be keyboard reachable"


def test_icon_pack_does_not_clobber_the_logo_title() -> None:
    """applyIconPack used to assign logoEl.innerHTML, wiping both title spans."""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    writer = src[src.index("const logoEl = document.querySelector('.sidebar-logo')") :]
    writer = writer[: writer.index("setIcon(")]
    assert "logoEl.innerHTML" not in writer, (
        "applyIconPack still overwrites .sidebar-logo wholesale; that destroys the "
        "collapse toggle's title variants the first time an icon pack is applied"
    )
    assert "sidebar-logo-icon" in writer, (
        "applyIconPack must write into the .sidebar-logo-icon slot instead"
    )


def test_spacer_pins_the_account_group_to_the_bottom() -> None:
    """flex:1 pushes whatever FOLLOWS it to the bottom of the rail."""
    sidebar = _sidebar_markup()
    spacer = sidebar.index('<div class="sidebar-spacer">')
    for page in ACCOUNT_PAGES:
        item = sidebar.index(f'data-page="{page}"')
        assert spacer < item, (
            f".sidebar-spacer sits after the {page!r} item, so Аккаунт & Опции is "
            f"not pushed to the bottom of the rail"
        )
    first_menu = sidebar.index('data-page="home"')
    assert first_menu < spacer, (
        "the spacer must come after the Меню group, otherwise Меню is pushed "
        "down instead of the account group"
    )


def test_no_low_specificity_span_rule_can_beat_the_title_variants() -> None:
    """`.sidebar-logo span` / `.nav-item span` are (0,1,1) and outrank (0,1,0).

    Two legacy "Show text" rules did exactly that: they forced `display: inline`
    on every span, so `.sidebar-logo-initial { display: none }` never applied and
    the rail head rendered "NeDotify" and "N" at the same time. Any such rule
    coming back silently re-breaks it.
    """
    css = BASE_CSS.read_text(encoding="utf-8")
    assert not re.search(r"\.sidebar-logo\s+span\s*\{[^}]*display\s*:\s*inline", css), (
        "a `.sidebar-logo span { display: inline }` rule outranks the title-variant "
        "rules and makes both 'NeDotify' and 'N' visible at once"
    )
    assert not re.search(r"\.nav-item\s+span\s*\{[^}]*display\s*:\s*inline", css), (
        "a `.nav-item span { display: inline }` rule would break .nav-label "
        "collapsing"
    )


def test_title_variants_are_block_level_so_max_width_animates() -> None:
    """max-width is ignored on an inline box, so the collapse would snap."""
    css = BASE_CSS.read_text(encoding="utf-8")
    for sel, needle in (
        (".sidebar-logo-text {", "display: block"),
        (".sidebar-logo-initial {", "display: none"),
        (".nav-label {", "display: block"),
    ):
        start = css.index(sel)
        block = css[start : css.index("}", start)]
        assert needle in block, f"{sel} must declare `{needle}`, got: {block.strip()}"


def test_collapsed_header_shows_only_the_initial_letter() -> None:
    """The pack/logo icon has to go too - icon + N did not fit the 64px rail."""
    css = BASE_CSS.read_text(encoding="utf-8")
    sel = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo-icon"
    assert sel in css, (
        f"collapsed rail must hide {sel}; icon + 'N' side by side overflowed "
        f"the narrow rail"
    )
    start = css.index(sel)
    block = css[start : css.index("}", start)]
    assert "display: none" in block, f"{sel} must hide its slot, got: {block.strip()}"


def test_full_title_hidden_and_initial_shown_when_collapsed() -> None:
    css = BASE_CSS.read_text(encoding="utf-8")

    full_sel = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo-full"
    full = css[css.index(full_sel) : css.index("}", css.index(full_sel))]
    assert "max-width: 0" in full, "expanded title must collapse to zero width"

    init_sel = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo-initial"
    init = css[css.index(init_sel) : css.index("}", css.index(init_sel))]
    # display:flex (not block) - it is absolutely positioned and centres itself
    # with justify-content, so assert the shown/hidden intent, not the value.
    assert re.search(r"display:\s*(block|flex)", init), (
        "the 'N' must be shown when collapsed, otherwise there is no expand target"
    )
    assert "display: none" not in init, "the 'N' must not be hidden when collapsed"


def test_narrow_viewport_still_exposes_the_expand_affordance() -> None:
    """The @media (max-width:900px) rail is icon-only; it must keep the toggle.

    That block blanket-hides every span. Without an explicit re-show of the
    initial, a narrow window would be a dead end: no label and nothing to click.
    """
    css = BASE_CSS.read_text(encoding="utf-8")
    mq_start = css.index("@media (max-width: 900px)")
    mq = css[mq_start : css.index("\n@media", mq_start + 10)] if "\n@media" in css[mq_start + 10 :] else css[mq_start:]
    assert re.search(r"\.sidebar-logo\s+span[^{]*\{[^}]*display\s*:\s*none", mq), (
        "expected the responsive block to hide the rail labels"
    )
    assert re.search(
        r"\.sidebar-logo\s+\.sidebar-logo-initial\s*\{[^}]*display\s*:\s*(block|flex)", mq
    ), (
        "the narrow-viewport rail must still show the 'N' toggle, otherwise the "
        "rail cannot be expanded again once the window is small"
    )
    assert not re.search(
        r"\.sidebar-logo\s+\.sidebar-logo-initial\s*\{[^}]*display\s*:\s*none", mq
    ), "the responsive 'N' toggle must not be hidden"


def test_logo_carries_no_inline_gap() -> None:
    """An inline `gap` outranks CSS, which silently broke collapsed centring.

    The markup used to hard-code `gap:10px` on #sidebar-logo. The collapsed rule
    sets `gap: 0`, but inline styles win, so the gap stayed - and together with
    the still-present zero-width .sidebar-logo-full sibling it pushed the "N" off
    centre in the 64px rail.
    """
    sidebar = _sidebar_markup()
    tag = re.search(r'<div class="sidebar-logo"[^>]*>', sidebar)
    assert tag, "sidebar-logo element not found"
    style = re.search(r'style="([^"]*)"', tag.group(0))
    if style:
        assert "gap" not in style.group(1), (
            f"#sidebar-logo must not hard-code gap inline ({style.group(1)}); it "
            f"outranks the collapsed state's gap:0 and pushes the 'N' off-centre"
        )


def test_collapsed_initial_is_centred_independently_of_siblings() -> None:
    """The 'N' must centre on the rail, not on its flex siblings.

    .sidebar-logo-full has to stay in flow (it is what crossfades), and anything
    it carries - width, margin - participates in the flex layout even at
    max-width:0. A previous attempt centred the 'N' with `width: 100%` on the
    flex item and it still sat left of the icon column, because the wordmark's
    margin-left was still being laid out. Absolute inset removes the dependency.
    """
    css = BASE_CSS.read_text(encoding="utf-8")
    sel = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo-initial"
    block = css[css.index(sel) : css.index("}", css.index(sel))]

    assert "position: absolute" in block, (
        "collapsed 'N' must be taken out of the flex flow so the crossfading "
        "wordmark sibling cannot skew its centring"
    )
    assert "inset: 0" in block, "absolute centring requires inset: 0"
    assert "justify-content: center" in block, "'N' must be centred horizontally"
    assert "align-items: center" in block, "'N' must be centred vertically"
    assert "margin-left: 0" in block, (
        "the expanded wordmark's nudge must not leak into the collapsed 'N'"
    )

    # The container has to be the positioning context for inset:0 to resolve.
    container = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo {{"
    cont_block = css[css.index(container) : css.index("}", css.index(container))]
    assert "position: relative" in cont_block, (
        ".sidebar-logo must be position:relative or `inset: 0` on the 'N' "
        "resolves against the wrong ancestor"
    )

    # And the wordmark itself must not keep its offset while collapsed.
    full = f"#sidebar.{COLLAPSED_CLASS} .sidebar-logo-full"
    full_block = css[css.index(full) : css.index("}", css.index(full))]
    assert "margin-left: 0" in full_block, (
        "the expanded wordmark offset must be reset when collapsed; it otherwise "
        "occupies flex space and offsets the header"
    )


def test_narrow_viewport_centres_the_initial_too() -> None:
    """The responsive rail must centre the 'N' by the same mechanism."""
    css = BASE_CSS.read_text(encoding="utf-8")
    mq_start = css.index("@media (max-width: 900px)")
    rest = css[mq_start + 10 :]
    mq = css[mq_start : mq_start + 10 + (rest.index("\n@media") if "\n@media" in rest else len(rest))]

    m = re.search(r"\.sidebar-logo\s+\.sidebar-logo-initial\s*\{([^}]*)\}", mq)
    assert m, "narrow-viewport rule for the initial not found"
    body = m.group(1)
    assert "position: absolute" in body and "inset: 0" in body, (
        "the responsive rail must centre the 'N' the same way, or it skews the "
        "moment the window crosses 900px"
    )
    assert re.search(r"^\s*\.sidebar-logo\s*\{[^}]*position:\s*relative", mq, re.MULTILINE), (
        "responsive .sidebar-logo needs position:relative as the containing block"
    )


def test_expanded_wordmark_nudge_is_scoped_to_the_full_variant() -> None:
    css = BASE_CSS.read_text(encoding="utf-8")
    m = re.search(r"^\.sidebar-logo-full\s*\{([^}]*)\}", css, re.MULTILINE)
    assert m, "expected a .sidebar-logo-full rule carrying the wordmark offset"
    assert "margin-left" in m.group(1), (
        "the expanded wordmark needs its own offset from the logo icon"
    )


def test_menu_group_is_not_pushed_down_by_the_logo_margin() -> None:
    """The rail owns its free space via .sidebar-spacer, so a big logo
    margin-bottom just pushes Меню away from the title for no reason."""
    css = BASE_CSS.read_text(encoding="utf-8")
    # Anchor to the start of a line: a bare substring search for ".sidebar-logo {"
    # also matches "#sidebar.is-collapsed .sidebar-logo {", which comes first and
    # carries no margin at all.
    m_rule = re.search(r"^\.sidebar-logo\s*\{([^}]*)\}", css, re.MULTILINE)
    assert m_rule, "the base .sidebar-logo rule not found"
    m = re.search(r"margin-bottom:\s*(\d+)px", m_rule.group(1))
    assert m, "expected an explicit margin-bottom on .sidebar-logo"
    assert int(m.group(1)) <= 16, (
        f".sidebar-logo margin-bottom is {m.group(1)}px; the spacer already owns "
        f"the free space, so keep this a small visual gap"
    )


def test_collapse_state_is_persisted_and_toggle_is_wired() -> None:
    src = PAGES_JS.read_text(encoding="utf-8")
    assert "nedotify_sidebar_collapsed" in src, "collapsed state must persist"
    assert "setSidebarCollapsed" in src
    # initPages must actually run the wiring, not just export the helper.
    init_body = src[src.index("export function initPages()") :]
    init_body = init_body[: init_body.index("\n}")]
    assert "initSidebarCollapse()" in init_body, (
        "initPages must call initSidebarCollapse() or the rail never collapses"
    )


def test_nav_items_stay_clickable_when_collapsed() -> None:
    """The rail is only useful if the icons still navigate."""
    sidebar = _sidebar_markup()
    items = re.findall(r'<div class="nav-item[^"]*" data-page="([^"]+)"', sidebar)
    assert items == ["home", "search", "library", "player", "settings", "profile"], (
        f"unexpected nav order/content: {items}"
    )
    src = PAGES_JS.read_text(encoding="utf-8")
    assert ".nav-item[data-page]" in src, "nav click handling must be bound by page id"
    css = BASE_CSS.read_text(encoding="utf-8")
    collapsed_labels = css[css.index(f"#sidebar.{COLLAPSED_CLASS} .nav-label") :]
    collapsed_labels = collapsed_labels[: collapsed_labels.index("}")]
    assert "display: none" not in collapsed_labels and "visibility" not in collapsed_labels, (
        "collapsed labels must collapse visually but stay in the layout; "
        "hiding the row outright breaks the icon hit area"
    )