import os
import sys
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.settings import DEFAULT_SETTINGS


class TestFontsM2(unittest.TestCase):
    """Milestone 2 Verification: Font System & Rendering Overhaul."""

    def test_settings_default_font_family(self):
        """Verify that DEFAULT_SETTINGS theme.font_family is normalized to 'default'."""
        self.assertIn("theme", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["theme"].get("font_family"), "default")

    def test_tokens_css_typography_propagation(self):
        """Verify tokens.css defines --font-sans-fallback and propagates --font-family to body and display."""
        tokens_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/css/tokens.css")
        with open(tokens_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check fallback chain includes Linux native desktop fonts
        self.assertIn("--font-sans-fallback:", content)
        fallback_match = re.search(r"--font-sans-fallback:\s*([^;]+);", content)
        self.assertIsNotNone(fallback_match, "Could not find --font-sans-fallback in tokens.css")
        fallback_val = fallback_match.group(1)
        for expected_font in ["system-ui", "Ubuntu", "Cantarell", "Noto Sans", "Liberation Sans", "sans-serif"]:
            self.assertIn(expected_font, fallback_val, f"Expected '{expected_font}' in --font-sans-fallback")

        # Check propagation tokens
        self.assertIn("--font-family: 'Inter', var(--font-sans-fallback);", content)
        self.assertIn("--font-body: var(--font-family);", content)
        self.assertIn("--font-display: 'Sora', var(--font-family);", content)
        self.assertIn("--font-mono: 'Consolas', 'Adwaita Mono', 'Liberation Mono', 'Ubuntu Mono', monospace;", content)

        # Check utility classes
        self.assertIn(".font-display {", content)
        self.assertIn("font-family: var(--font-display) !important;", content)
        self.assertIn(".font-body {", content)
        self.assertIn("font-family: var(--font-body) !important;", content)

    def test_index_html_google_fonts_link(self):
        """Verify index.html imports Inter with Cyrillic support without media=print hack."""
        html_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check stylesheet link with Inter, DM Sans, Sora
        self.assertIn('id="gfonts-stylesheet"', content)
        match = re.search(r'<link id="gfonts-stylesheet"[^>]+>', content)
        self.assertIsNotNone(match, "Could not find gfonts-stylesheet in index.html")
        link_tag = match.group(0)

        self.assertIn("family=Inter:wght@400;500;600;700;800", link_tag)
        self.assertIn("family=DM+Sans", link_tag)
        self.assertIn("family=Sora", link_tag)
        self.assertIn("display=swap", link_tag)

        # Verify media="print" hack is absent
        self.assertNotIn('media="print"', link_tag)
        self.assertNotIn('onload="this.media=\'all\'"', link_tag)

    def test_base_css_antialiasing_and_rendering(self):
        """Verify base.css typography smoothing, blur prevention, and removed hardcoded fonts."""
        base_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/css/components/base.css")
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Antialiasing and subpixel rendering
        match = re.search(r"body,\s*button,\s*input,\s*select,\s*textarea\s*\{([^}]+)\}", content)
        self.assertIsNotNone(match, "Could not find body, button... selector in base.css")
        body_rules = match.group(1)
        self.assertIn("font-family: var(--font-family);", body_rules)
        self.assertIn("text-rendering: optimizeLegibility;", body_rules)
        self.assertIn("-webkit-font-smoothing: subpixel-antialiased;", body_rules)

        # WebKitGTK blur stabilization
        blur_match = re.search(r"\.lyrics-line,\s*\.quick-access-card,\s*\.stat-card,\s*\.track-item\s*\{([^}]+)\}", content)
        self.assertIsNotNone(blur_match, "Could not find WebKitGTK blur stabilization rule in base.css")
        blur_rules = blur_match.group(1)
        self.assertIn("backface-visibility: hidden;", blur_rules)
        self.assertIn("transform: translateZ(0);", blur_rules)

        # No hardcoded Outfit / Plus Jakarta Sans in artist-name-title or fallback-letters
        self.assertNotIn("font-family: 'Outfit', 'Plus Jakarta Sans', sans-serif;", content)

        # Check artist-name-title uses var(--font-display)
        artist_match = re.search(r"\.artist-name-title\s*\{([^}]+)\}", content)
        self.assertIsNotNone(artist_match, "Could not find .artist-name-title in base.css")
        self.assertIn("font-family: var(--font-display);", artist_match.group(1))

        # Check fallback-letters uses var(--font-display)
        fallback_match = re.search(r"\.fallback-letters\s*\{([^}]+)\}", content)
        self.assertIsNotNone(fallback_match, "Could not find .fallback-letters in base.css")
        self.assertIn("font-family: var(--font-display);", fallback_match.group(1))

    def test_settings_js_fonts_architecture(self):
        """Verify settings.js includes Linux fonts, applyFontFamily, card matching, and startup sync."""
        js_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/js/settings.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        # FONTS_LIST Linux support
        self.assertIn("export const FONTS_LIST", content)
        for linux_font in ["Ubuntu", "Cantarell", "Liberation Sans", "Noto Sans", "Inter", "Roboto"]:
            self.assertIn(linux_font, content, f"Expected {linux_font} in FONTS_LIST")

        # applyFontFamily updates all 3 CSS variables
        self.assertIn("export function applyFontFamily(", content)
        apply_start = content.find("export function applyFontFamily(")
        apply_body = content[apply_start:apply_start + 1800]
        self.assertIn("document.documentElement.style.setProperty('--font-family',", apply_body)
        self.assertIn("document.documentElement.style.setProperty('--font-body',", apply_body)
        self.assertIn("document.documentElement.style.setProperty('--font-display',", apply_body)
        self.assertIn("highlightActiveFontCard(", apply_body)

        # highlightActiveFontCard matches dataset.fontId and dataset.font
        self.assertIn("export function highlightActiveFontCard(", content)
        card_start = content.find("export function highlightActiveFontCard(")
        card_body = content[card_start:card_start + 800]
        self.assertIn("card.dataset.fontId", card_body)
        self.assertIn("card.dataset.font", card_body)

        # renderFontCards sets dataset.fontId
        self.assertIn("card.dataset.fontId = f.id;", content)

        # applySettingsFromBackend invokes applyFontFamily
        backend_start = content.find("export function applySettingsFromBackend(")
        backend_body = content[backend_start:backend_start + 6000]
        self.assertIn("applyFontFamily(settings.theme.font_family, settings.theme.font_id, false);", backend_body)


if __name__ == "__main__":
    unittest.main()
