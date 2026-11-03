"""
Regression tests for Group №6: Windows UI, macOS-style, and interaction fixes.
Bug IDs:
- BUG-WIN-021: Playlist context menu calls openPlaylistActions
- BUG-WIN-022: blur-disabled class cleared when leaving macOS style
- BUG-WIN-023: Modals close on Escape key and backdrop click via openModalFocusTrap
- BUG-WIN-045: Hotkey KeyL toggles lyrics; like hotkey targets pb-btn-like
- BUG-WIN-046: Floating mini-lyrics PiP clamped to viewport bounds
- BUG-WIN-047: Track context menu max-height clamped to viewport with overflow scroll
- BUG-WIN-048: Sync player bar like/heart button with context menu favorite toggle
- BUG-WIN-054: escapeHtml applied to playlist.track_count in search template
- BUG-WIN-055: Dead listener app:artists_ready removed from home.js
- BUG-WIN-056: Dead covers array removed from artist_profile.js
"""

import os
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui" / "web_new_v2"
JS_DIR = UI_DIR / "js"
CSS_DIR = UI_DIR / "css"


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_bug_win_021_playlist_context_menu_calls_open_playlist_actions():
    """BUG-WIN-021: playlist context menu invokes openPlaylistActions instead of missing showPlaylistContextMenu."""
    contextmenu_js = read_file(JS_DIR / "contextmenu.js")
    library_view_js = read_file(JS_DIR / "library-view.js")

    # contextmenu.js should import openPlaylistActions and call it
    assert "import { openPlaylistActions } from './library-view.js';" in contextmenu_js
    assert "openPlaylistActions(playlist, e)" in contextmenu_js

    # library-view.js exposes openPlaylistActions globally
    assert "window.openPlaylistActions = openPlaylistActions" in library_view_js or \
           "window.NeDotify.openPlaylistActions = openPlaylistActions" in library_view_js


def test_bug_win_022_blur_disabled_cleaned_up_on_style_switch():
    """BUG-WIN-022: Switching away from macOS style cleans up blur-disabled unless explicitly disabled."""
    ui_style_js = read_file(JS_DIR / "ui-style.js")

    # In ui-style.js, syncResources manages blur-disabled for standard style
    assert "root.classList.toggle?.('blur-disabled', standardBlur === 0)" in ui_style_js
    # apply() should invoke syncResources()
    assert "syncResources()" in ui_style_js


def test_bug_win_023_modals_focus_trap_handles_escape_and_backdrop():
    """BUG-WIN-023: openModalFocusTrap integrates Escape key and backdrop click to close modals."""
    utils_js = read_file(JS_DIR / "utils.js")
    library_js = read_file(JS_DIR / "library.js")

    # utils.js: openModalFocusTrap should handle Escape and backdrop
    assert 'e.key === "Escape"' in utils_js or "e.key === 'Escape'" in utils_js
    assert "e.target === modal" in utils_js
    assert "closeModalFocusTrap" in utils_js

    # modal-edit-tags uses openModalFocusTrap with close callback
    assert "modal-edit-tags" in utils_js
    assert "openModalFocusTrap(modal, closeModal)" in utils_js or "openModalFocusTrap(modal, closeHandler)" in utils_js or "openModalFocusTrap(modal" in utils_js

    # library.js: modalIP and modal-delete-playlist pass onClose callback
    assert "modal-import-playlist" in library_js or "modalIP" in library_js
    assert "modal-delete-playlist" in library_js
    assert "openModalFocusTrap(modalIP, () =>" in library_js or "openModalFocusTrap(modalIP" in library_js
    assert "openModalFocusTrap(modal, () =>" in library_js or "openModalFocusTrap(modal" in library_js


def test_bug_win_045_hotkeys_lyrics_toggle_and_like_button_id():
    """BUG-WIN-045: KeyL toggles lyrics overlay (closes if open); like hotkey clicks pb-btn-like."""
    hotkeys_js = read_file(JS_DIR / "hotkeys.js")
    lyrics_js = read_file(JS_DIR / "lyrics.js")

    # hotkeys.js: like hotkey should check pb-btn-like
    assert "pb-btn-like" in hotkeys_js

    # lyrics.js: openLyricsOverlay or toggleLyricsOverlay should handle toggling
    assert "lyrics-overlay" in lyrics_js
    # Ensure overlay is toggled/closed when active
    assert "closeLyricsOverlay()" in lyrics_js or "overlay.classList.contains('active')" in lyrics_js or "overlay.classList.contains(\"active\")" in lyrics_js


def test_retired_pip_has_no_widget_or_handler():
    lyrics_js = read_file(JS_DIR / "lyrics.js")
    assert "toggleMiniLyrics" not in lyrics_js
    assert "initMiniLyricsWidget" not in lyrics_js


def test_bug_win_047_track_context_menu_max_height_and_scroll():
    """BUG-WIN-047: .rich-track-menu has max-height and overflow-y: auto, and positioning clamps height."""
    base_css = read_file(CSS_DIR / "components" / "base.css")
    utils_js = read_file(JS_DIR / "utils.js")

    # CSS check: .rich-track-menu has max-height calc(100vh - 24px) and overflow-y: auto
    assert re.search(r"\.rich-track-menu\s*\{[^}]*max-height:\s*calc\(100vh\s*-\s*24px\)", base_css)
    assert re.search(r"\.rich-track-menu\s*\{[^}]*overflow-y:\s*auto", base_css)

    # JS check: utils.js clamps menu height / top within window bounds
    assert "rich-track-menu" in utils_js
    assert "window.innerHeight" in utils_js


def test_bug_win_048_sync_player_bar_like_with_context_menu():
    """BUG-WIN-048: Dispatches nedotify:favorites_updated / nedotify:track_favorite_toggled and player updates like button."""
    events_js = read_file(JS_DIR / "events.js")
    utils_js = read_file(JS_DIR / "utils.js")
    player_js = read_file(JS_DIR / "player.js")

    # events.js dispatches favorites_updated
    assert "nedotify:favorites_updated" in events_js

    # utils.js dispatches track_favorite_toggled
    assert "nedotify:track_favorite_toggled" in utils_js

    # player.js listens to sync events and updates like button
    assert "nedotify:favorites_updated" in player_js
    assert "nedotify:track_favorite_toggled" in player_js
    assert "updateLikeButtons" in player_js


def test_bug_win_054_playlist_track_count_escaped_in_search():
    """BUG-WIN-054: escapeHtml applied to playlist.track_count in search template."""
    search_js = read_file(JS_DIR / "search.js")

    assert "escapeHtml(String(playlist.track_count" in search_js or \
           "escapeHtml(playlist.track_count" in search_js or \
           "escapeHtml(String(p.track_count" in search_js


def test_bug_win_055_dead_artists_ready_listener_removed():
    """BUG-WIN-055: dead listener app:artists_ready removed from home.js."""
    home_js = read_file(JS_DIR / "home.js")

    assert "app:artists_ready" not in home_js


def test_bug_win_056_dead_covers_array_removed():
    """BUG-WIN-056: dead covers array removed from artist_profile.js."""
    artist_profile_js = read_file(JS_DIR / "artist_profile.js")

    assert "const covers = [" not in artist_profile_js
    assert "let covers = [" not in artist_profile_js
    assert "var covers = [" not in artist_profile_js
