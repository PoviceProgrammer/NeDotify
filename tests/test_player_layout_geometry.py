"""Player-view layout geometry invariants.

The player page paints the track artwork as an ambient backdrop
(`#player-bg-glow`, filled by ``player.js``) and then puts two glass cards on
top of it. The backdrop layer sits at ``inset: -20px`` and is additionally
scaled up, so it always overruns its parent - which means the visible edge of
the backdrop is the **parent's** ``overflow: hidden`` clip, not the glow's own
``border-radius``. Rounding the glow alone therefore does nothing on screen.

The cards inside are rounded, so a rectangular clip cut a hard square across
the artwork and the page read as "square backdrop, rounded cards". The fix is to
round the clip, and to size that radius so its corner arcs are *concentric* with
the cards' arcs - a rounded rect whose arc centres coincide with the cards'
reads as one continuous shape, while an arbitrary radius does not.

These are static assertions on the shipped CSS. They guard the arithmetic in the
stylesheet; they are not a visual regression test. ``tools/visual_guard`` is
where pixel comparisons live.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYER_CSS = REPO_ROOT / "ui" / "web_new_v2" / "css" / "components" / "player-view.css"
TOKENS_CSS = REPO_ROOT / "ui" / "web_new_v2" / "css" / "tokens.css"


def _block(css: str, selector: str) -> str:
    """Body of the first `selector { ... }` rule, comments stripped."""
    # Match the selector on its own declaration boundary so `.player-glass-card`
    # does not also match `.player-glass-card::after`.
    pattern = re.compile(
        r"(?m)^" + re.escape(selector) + r"\s*\{(.*?)\}", re.DOTALL
    )
    match = pattern.search(css)
    assert match, f"selector {selector!r} not found in {css[:0]}"
    body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.DOTALL)
    return body


def _decl(body: str, prop: str) -> str:
    match = re.search(rf"(?<![\w-]){prop}\s*:\s*([^;]+);", body)
    assert match, f"property {prop!r} not found"
    return match.group(1).strip()


def _token(name: str) -> int:
    """Resolve `--name: 16px` from tokens.css to an int."""
    css = TOKENS_CSS.read_text(encoding="utf-8")
    match = re.search(rf"(?<![\w-]){re.escape(name)}\s*:\s*(\d+(?:\.\d+)?)px\s*;", css)
    assert match, f"token {name} not found in tokens.css"
    return int(float(match.group(1)))


def _resolve(expr: str, radius_token: int) -> tuple[int, int]:
    """Resolve a 1- or 2-value length list to (vertical, horizontal) px.

    Handles `16px`, `16px 20px`, `var(--radius-lg)` and
    `calc(var(--radius-lg) + 8px)`. Each component is either a parenthesised
    group (whose numbers are summed) or a bare length, and components are read
    in source order because that is what carries the vertical/horizontal meaning.
    """
    expr = expr.replace("var(--radius-lg)", f"{radius_token}px")

    values: list[int] = []
    # Either a fully parenthesised group, or a bare number with an optional unit.
    for match in re.finditer(r"\(([^()]*)\)|(-?\d+(?:\.\d+)?)\s*(?:px)?(?=\s|$|;)", expr):
        group, bare = match.group(1), match.group(2)
        if group is not None:
            nums = re.findall(r"-?\d+(?:\.\d+)?", group)
            if nums:
                values.append(sum(int(float(n)) for n in nums))
        elif bare is not None:
            values.append(int(float(bare)))

    assert values, f"could not resolve {expr!r}"
    if len(values) == 1:
        return values[0], values[0]
    return values[0], values[1]


def test_player_layout_clip_is_rounded() -> None:
    """The clip that forms the backdrop's edge must not be a hard square."""
    body = _block(PLAYER_CSS.read_text(encoding="utf-8"), ".player-2col-layout")
    assert "overflow" in body, "layout no longer clips; revisit this test"

    decl = _decl(body, "border-radius")
    vertical, horizontal = _resolve(decl, _token("--radius-lg"))
    assert vertical > 0 and horizontal > 0, (
        f".player-2col-layout clips the cover backdrop with a square "
        f"(border-radius: {decl!r}); the cards it frames are rounded."
    )


def test_clip_radius_is_concentric_with_the_cards() -> None:
    """Clip radius must equal card radius + the layout padding, on both axes.

    The cards are inset by the layout's padding, so their corner-arc centres sit
    at (padding + radius) from the layout's corner. The clip has to use the same
    centres or the backdrop edge and the card edges will not line up.
    """
    css = PLAYER_CSS.read_text(encoding="utf-8")
    radius = _token("--radius-lg")

    layout = _block(css, ".player-2col-layout")
    card = _block(css, ".player-glass-card")

    pad_v, pad_h = _resolve(_decl(layout, "padding"), radius)
    clip_v, clip_h = _resolve(_decl(layout, "border-radius"), radius)
    card_v, card_h = _resolve(_decl(card, "border-radius"), radius)

    assert card_v == card_h == radius, (
        f"expected the cards to use --radius-lg ({radius}px), got "
        f"vertical={card_v} horizontal={card_h}; update the concentricity maths "
        f"in .player-2col-layout if this was intentional."
    )
    assert clip_v == card_v + pad_v, (
        f"vertical clip radius {clip_v}px != card radius {card_v}px + vertical "
        f"padding {pad_v}px - the backdrop edge will not line up with the cards"
    )
    assert clip_h == card_h + pad_h, (
        f"horizontal clip radius {clip_h}px != card radius {card_h}px + "
        f"horizontal padding {pad_h}px - the backdrop edge will not line up "
        f"with the cards"
    )


def test_cards_are_still_rounded() -> None:
    """Guard the other half of the pair: the cards must keep their radius."""
    body = _block(PLAYER_CSS.read_text(encoding="utf-8"), ".player-glass-card")
    vertical, horizontal = _resolve(_decl(body, "border-radius"), _token("--radius-lg"))
    assert vertical > 0 and horizontal > 0


def _player_cascade(style, width):
    """Resolve actual qualified rules, including later overrides and media packs."""
    import xml.etree.ElementTree as ET
    import cssselect2
    import tinycss2
    tree = ET.fromstring(f'''<html data-ui-style="{style}" data-macos-mode="dark"><body>
      <div id="view-player"><div class="player-2col-layout">
       <div class="player-left-col player-glass-card"><div class="player-cover-section" /></div>
       <div class="player-right-col player-glass-card" />
      </div></div><div id="player-bar"><div class="pb-progress pb-progress-surface">
       <div id="pb-progress-track" class="progress-track" />
      </div><div class="pb-controls"><div class="pb-buttons" /></div></div></body></html>''')
    matcher = cssselect2.Matcher()
    files = ["ui/web_new_v2/css/components/base.css", "ui/web_new_v2/css/components/player-bar.css",
             "ui/web_new_v2/css/components/player-view.css", "ui/web_new_v2/css/components/home-refresh.css",
             "ui/MACos_ui/tokens.css", "ui/MACos_ui/interface.css"]
    def add_rules(rules):
        for rule in rules:
            if rule.type == "at-rule" and rule.content:
                condition = tinycss2.serialize(rule.prelude)
                if rule.lower_at_keyword == "media":
                    limits = re.findall(r"(min|max)-width\s*:\s*(\d+)px", condition)
                    if any((width < int(n) if kind == "min" else width > int(n)) for kind,n in limits):
                        continue
                if rule.lower_at_keyword in ("media", "supports", "layer"):
                    add_rules(tinycss2.parse_rule_list(rule.content, skip_whitespace=True, skip_comments=True))
            elif rule.type == "qualified-rule":
                try:
                    selectors = cssselect2.compile_selector_list(tinycss2.serialize(rule.prelude))
                except cssselect2.SelectorError:
                    continue
                declarations = [d for d in tinycss2.parse_declaration_list(rule.content, skip_whitespace=True, skip_comments=True) if d.type == "declaration"]
                for selector in selectors:
                    matcher.add_selector(selector, declarations)
    for file in files:
        add_rules(tinycss2.parse_stylesheet((REPO_ROOT/file).read_text(encoding="utf-8"), skip_comments=True, skip_whitespace=True))
    result = {}
    for element in cssselect2.ElementWrapper.from_html_root(tree).iter_subtree():
        values, keys = {}, {}
        for specificity, order, pseudo, declarations in matcher.match(element):
            if pseudo:
                continue
            for declaration in declarations:
                key = (declaration.important, specificity, order)
                if key >= keys.get(declaration.name, (False, (-1,-1,-1), -1)):
                    values[declaration.name] = tinycss2.serialize(declaration.value).strip()
                    keys[declaration.name] = key
        identifier = element.etree_element.get("id") or element.etree_element.get("class") or element.etree_element.tag
        result[identifier] = values
    return result


def test_player_cards_keep_their_style_specific_layout_and_visible_lyrics():
    for width in (600,850,1084,1280):
        for style in ("current","macos"):
            rules = _player_cascade(style,width)
            card = rules["player-left-col player-glass-card"]
            if style == 'macos':
                assert card['display'] == 'grid', (style,width,card)
                assert card['grid-template-columns'] == 'minmax(0, 1fr) auto'
                assert rules['player-cover-section']['grid-area'] == ('1 / 1 / 2 / 3' if width <= 760 else '2 / 1 / 3 / 3')
            else:
                assert card["display"] == "flex", (style,width,card)
                assert card["flex-direction"] == "column"
            assert rules["player-right-col player-glass-card"]["display"] != "none", (style,width)


def test_macos_bottom_bar_uses_shared_responsive_geometry():
    geometry = ("left","right","bottom","height","padding","padding-inline","gap","grid-template-columns")
    for width in (600,760,850,1084,1280):
        current,macos = (_player_cascade(style,width) for style in ("current","macos"))
        for selector in ("html","player-bar","pb-progress-track"):
            for prop in geometry:
                assert current[selector].get(prop) == macos[selector].get(prop), (width,selector,prop)


def test_full_bar_seek_surface_is_not_reassigned_to_the_old_mobile_grid_row():
    for style in ('current', 'macos'):
        surface = _player_cascade(style, 600)['pb-progress pb-progress-surface']
        assert surface['position'] == 'absolute'
        assert surface.get('margin-right', '0') == '0'
        assert surface.get('grid-row', 'auto') == 'auto'


def test_mobile_transport_buttons_stay_above_the_seek_surface():
    for style in ('current', 'macos'):
        rules = _player_cascade(style, 600)
        assert int(rules['pb-buttons'].get('z-index', '0')) > int(rules['pb-progress pb-progress-surface']['z-index'])
