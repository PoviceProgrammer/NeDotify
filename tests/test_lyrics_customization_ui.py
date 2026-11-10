"""Tests for NeDotify Windows Lyrics Customization Subsystem.

Validates:
1. HTML markup in index.html for:
   - Lyrics display settings popover (Screenshot #1)
   - Lyrics search and selection modal (Screenshot #2)
   - Custom lyrics editor modal
   - Trigger buttons in page header and overlay
2. CSS typography variables and rules in lyrics.css.
3. JavaScript modules syntax (via node --check) and wiring:
   - lyrics-settings-popover.js
   - lyrics-search-modal.js
   - lyrics-custom-modal.js
   - lyrics.js exports
4. Python bridge method registration and API availability.
5. Absolute absence of Yandex Music in lyrics components.
"""

import os
import shutil
import subprocess
import tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(PROJECT_ROOT, "ui", "web_new_v2", "index.html")
LYRICS_CSS = os.path.join(PROJECT_ROOT, "ui", "web_new_v2", "css", "components", "lyrics.css")
JS_DIR = os.path.join(PROJECT_ROOT, "ui", "web_new_v2", "js")
BRIDGE_PY = os.path.join(PROJECT_ROOT, "core", "bridge.py")
API_PY = os.path.join(PROJECT_ROOT, "core", "api.py")
DATABASE_PY = os.path.join(PROJECT_ROOT, "core", "database.py")


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# -----------------------------------------------------------------------------
# 1. HTML Markup Validation
# -----------------------------------------------------------------------------

def test_index_html_contains_lyrics_popover_and_modals():
    html = read_file(INDEX_HTML)

    # Trigger buttons
    assert 'id="btn-lyrics-settings-page"' in html
    assert 'id="btn-lyrics-settings-overlay"' in html

    # Popover (Screenshot #1)
    assert 'id="lyrics-display-settings-popover"' in html
    assert 'id="slider-lyrics-font-size"' in html
    assert 'id="val-lyrics-font-size"' in html
    assert 'id="slider-lyrics-font-weight"' in html
    assert 'id="val-lyrics-font-weight"' in html
    assert 'id="slider-lyrics-line-height"' in html
    assert 'id="val-lyrics-line-height"' in html
    assert 'id="btn-lyrics-align-left"' in html
    assert 'id="btn-lyrics-align-center"' in html
    assert 'id="btn-lsp-action-research"' in html
    assert 'id="btn-lsp-action-pick-version"' in html
    assert 'id="btn-lsp-action-custom"' in html
    assert 'id="btn-lsp-action-reset"' in html

    # Search Modal (Screenshot #2)
    assert 'id="modal-lyrics-search"' in html
    assert 'id="input-lyrics-search-query"' in html
    assert 'id="btn-lyrics-search-submit"' in html
    assert 'id="lyrics-search-results-list"' in html

    # Custom Lyrics Modal
    assert 'id="modal-custom-lyrics"' in html
    assert 'id="textarea-custom-lyrics"' in html
    assert 'id="custom-lyrics-preview-box"' in html
    assert 'id="btn-custom-lyrics-preview-toggle"' in html
    assert 'id="btn-custom-lyrics-delete"' in html
    assert 'id="btn-custom-lyrics-save"' in html


# -----------------------------------------------------------------------------
# 2. CSS Typography & Styling Validation
# -----------------------------------------------------------------------------

def test_lyrics_css_contains_customization_rules():
    css = read_file(LYRICS_CSS)

    # CSS Custom Properties
    assert "--lyrics-font-size" in css
    assert "--lyrics-font-weight" in css
    assert "--lyrics-line-height" in css
    assert "--lyrics-text-align" in css

    # Alignment variants
    assert '.lyrics-viewport[data-align="left"]' in css
    assert '.lyrics-viewport[data-align="center"]' in css

    # Popover styling (Screenshot #1)
    assert ".lyrics-settings-popover" in css
    assert ".lsp-header" in css
    assert ".lsp-slider" in css
    assert ".lsp-segmented-control" in css
    assert ".lsp-action-btn" in css
    assert "font-size: var(--lyrics-font-size" in css
    assert ".lyric-word" in css

    # Search Modal styling (Screenshot #2)
    assert ".lyrics-search-results-list" in css
    assert ".lyrics-search-item" in css
    assert ".badge-source" in css
    assert ".badge-synced" in css
    assert ".badge-plain" in css

    # Custom Lyrics styling
    assert ".custom-lyrics-preview" in css
    assert ".cl-timestamp" in css


# -----------------------------------------------------------------------------
# 3. JavaScript Syntax & Integration Check
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename",
    [
        "lyrics-settings-popover.js",
        "lyrics-search-modal.js",
        "lyrics-custom-modal.js",
        "lyrics.js",
    ],
)
def test_lyrics_js_files_parse_as_es_modules(filename):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; syntax check skipped")
    src = os.path.join(JS_DIR, filename)
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, filename.replace(".js", ".mjs"))
        shutil.copyfile(src, copy)
        proc = subprocess.run(
            [node, "--check", copy],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert proc.returncode == 0, f"{filename} failed node --check:\n{proc.stderr}"


def test_lyrics_js_exports_and_wiring():
    lyrics_src = read_file(os.path.join(JS_DIR, "lyrics.js"))

    assert "export function invalidateLyricsKineticLayout" in lyrics_src
    assert "export function reloadCurrentTrackLyrics" in lyrics_src
    assert "export function getCurrentLyricsData" in lyrics_src
    assert "window.NeDotify.invalidateLyricsKineticLayout = invalidateLyricsKineticLayout" in lyrics_src
    assert "window.NeDotify.reloadCurrentTrackLyrics = reloadCurrentTrackLyrics" in lyrics_src
    assert "initLyricsSettingsPopover();" in lyrics_src
    assert "initLyricsSearchModal();" in lyrics_src
    assert "initLyricsCustomModal();" in lyrics_src


# -----------------------------------------------------------------------------
# 4. Bridge & API Method Registration Check
# -----------------------------------------------------------------------------

def test_bridge_public_methods_whitelist():
    bridge_src = read_file(BRIDGE_PY)

    required_methods = [
        "search_lyrics",
        "apply_lyrics_candidate",
        "save_custom_lyrics",
        "delete_custom_lyrics",
        "get_lyrics_display_settings",
        "save_lyrics_display_settings",
    ]
    for method in required_methods:
        assert f"'{method}'" in bridge_src, f"{method} is not in PUBLIC_METHODS"


def test_core_api_implements_methods():
    api_src = read_file(API_PY)

    required_defs = [
        "def search_lyrics(",
        "def apply_lyrics_candidate(",
        "def save_custom_lyrics(",
        "def delete_custom_lyrics(",
        "def get_lyrics_display_settings(",
        "def save_lyrics_display_settings(",
    ]
    for fn in required_defs:
        assert fn in api_src, f"{fn} is not implemented in core/api.py"


# -----------------------------------------------------------------------------
# 5. Zero Yandex Music in Lyrics Subsystem Check
# -----------------------------------------------------------------------------

def test_no_yandex_music_in_lyrics_files():
    files_to_check = [
        os.path.join(PROJECT_ROOT, "services", "lyrics_search_service.py"),
        os.path.join(PROJECT_ROOT, "services", "lyrics_lookup.py"),
        os.path.join(PROJECT_ROOT, "services", "lyrics_service.py"),
        os.path.join(JS_DIR, "lyrics-settings-popover.js"),
        os.path.join(JS_DIR, "lyrics-search-modal.js"),
        os.path.join(JS_DIR, "lyrics-custom-modal.js"),
    ]
    for path in files_to_check:
        content = read_file(path)
        assert "yandex" not in content.lower(), f"Forbidden yandex reference found in {path}"
