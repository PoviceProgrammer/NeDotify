import os
import sys
import json
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.settings import DEFAULT_SETTINGS

class TestParticlesM1(unittest.TestCase):
    def test_settings_default_shape(self):
        """Verify that DEFAULT_SETTINGS has particles_shape set to 'dot'."""
        self.assertIn("ui", DEFAULT_SETTINGS)
        self.assertEqual(DEFAULT_SETTINGS["ui"].get("particles_shape"), "dot")

    def test_base_css_particles_styling(self):
        """Verify ui/web_new_v2/css/components/base.css styling for #particles-bg."""
        css_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/css/components/base.css")
        with open(css_path, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"#particles-bg\s*\{([^}]+)\}", content)
        self.assertIsNotNone(match, "Could not find #particles-bg rule in base.css")
        rules = match.group(1)

        self.assertIn("position: fixed;", rules)
        self.assertIn("inset: 0;", rules)
        self.assertIn("pointer-events: none !important;", rules)
        self.assertIn("z-index: 20;", rules)
        self.assertIn("overflow: hidden;", rules)
        self.assertIn("display: block;", rules)
        self.assertIn("filter: none;", rules)
        self.assertIn("-webkit-filter: none;", rules)
        self.assertNotIn("filter: blur", rules)

    def test_particles_js_implementation(self):
        """Verify particles.js has Noto Color Emoji, no desynchronized, persistent listeners, and circle alias."""
        js_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/js/particles.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Noto Color Emoji fallback in getCoatRfSprite
        self.assertIn('"Noto Color Emoji"', content)
        coat_rf_start = content.find("function getCoatRfSprite")
        self.assertNotEqual(coat_rf_start, -1)
        coat_rf_block = content[coat_rf_start:coat_rf_start + 1500]
        self.assertIn('"Noto Color Emoji"', coat_rf_block)

        # No desynchronized: true
        self.assertNotIn("desynchronized: true", content)
        self.assertIn("canvas.getContext('2d', { alpha: true })", content)

        # Circle alias
        self.assertIn("if (resolvedShape === 'circle') resolvedShape = 'dot';", content)
        self.assertIn("p.shape === 'dot' || p.shape === 'circle'", content)

        # Module-scope persistent listeners
        self.assertRegex(content, r"function onResize\(\)")
        self.assertRegex(content, r"function onMiniPlayerToggled\(\)")
        self.assertRegex(content, r"function onMouseMove\(")
        self.assertRegex(content, r"function onMouseLeave\(\)")

    def test_main_js_toggle_sync(self):
        """Verify main.js synchronizes #toggle-particles on startup."""
        main_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/js/main.js")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("const togglePart = document.getElementById('toggle-particles');", content)
        self.assertIn("if (togglePart) togglePart.classList.toggle('on', particlesEnabled);", content)

if __name__ == "__main__":
    unittest.main()
