"""Cascade contracts for the artist carousel, backed by native geometry checks.

The 220px section used to squeeze the padded flex cards until the title's
20px line box was only 10px high. These checks pin the sizing contract in the
stylesheets actually linked by index.html; they do not replace WebView layout.
"""

import re
from pathlib import Path


UI = Path(__file__).resolve().parents[1] / "ui" / "web_new_v2"


def _shipped_css():
    html = (UI / "index.html").read_text(encoding="utf-8")
    return "\n".join(
        (UI / href.split("?")[0]).read_text(encoding="utf-8")
        for href in re.findall(r'<link[^>]+href="([^"]+\.css[^\"]*)"', html)
    )


def _declarations(selector):
    css = re.sub(r"/\*.*?\*/", "", _shipped_css(), flags=re.S)
    declarations = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [part.strip() for part in selectors.split(",")]:
            declarations.update(
                (prop.strip(), value.strip())
                for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", body)
            )
    return declarations


def test_artist_album_section_keeps_intrinsic_card_height():
    section = _declarations(".artist-albums-card")
    assert section["height"] == "auto", "fixed section height vertically clips album titles"
    assert section.get("flex-shrink") == "0", "artist column must not squeeze the album section"


def test_artist_album_cover_keeps_square_aspect_ratio():
    shared = _declarations(".album-cover-wrap")
    cover = _declarations(".artist-albums-carousel .album-cover-wrap")
    assert shared["aspect-ratio"] == "1 / 1"
    assert cover.get("height") == "auto", "fixed 120px height distorts the padded card's cover"
    assert cover.get("flex-shrink") == "0"
