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
        r"(?<![\w-])" + re.escape(selector) + r"\s*\{(.*?)\}", re.DOTALL
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
