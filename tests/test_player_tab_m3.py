import os
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestPlayerTabM3(unittest.TestCase):
    """Milestone 3 Verification: Player Tab Layout & Functionality Fixes."""

    def setUp(self):
        self.html_path = os.path.join(PROJECT_ROOT, "ui/web_new_v2/index.html")
        self.player_view_css = os.path.join(PROJECT_ROOT, "ui/web_new_v2/css/components/player-view.css")
        self.player_bar_css = os.path.join(PROJECT_ROOT, "ui/web_new_v2/css/components/player-bar.css")
        self.player_js = os.path.join(PROJECT_ROOT, "ui/web_new_v2/js/player.js")
        self.pages_js = os.path.join(PROJECT_ROOT, "ui/web_new_v2/js/pages.js")

        with open(self.html_path, "r", encoding="utf-8") as f:
            self.html_content = f.read()
        with open(self.player_view_css, "r", encoding="utf-8") as f:
            self.view_css_content = f.read()
        with open(self.player_bar_css, "r", encoding="utf-8") as f:
            self.bar_css_content = f.read()
        with open(self.player_js, "r", encoding="utf-8") as f:
            self.player_js_content = f.read()
        with open(self.pages_js, "r", encoding="utf-8") as f:
            self.pages_js_content = f.read()

    # ----------------------------------------------------------------------
    # Fix 1: Title/Artist Spans Preservation
    # ----------------------------------------------------------------------
    def test_fix1_dom_spans_in_html(self):
        """Verify #pp-header-title contains <span id='pp-title'> and <span id='pp-artist'>."""
        self.assertIn('id="pp-header-title"', self.html_content)
        self.assertIn('id="pp-title"', self.html_content)
        self.assertIn('id="pp-artist"', self.html_content)
        span_pattern = r'<div class="player-header-title" id="pp-header-title">\s*<span id="pp-title">.*?</span>\s*—\s*<span id="pp-artist">.*?</span>\s*</div>'
        self.assertIsNotNone(re.search(span_pattern, self.html_content, re.DOTALL))

    def test_fix1_player_js_preserves_spans(self):
        """Verify updateTrackUI does NOT wipe headerEl.textContent with a raw string."""
        # Ensure headerEl.textContent = headerTitle is NOT present
        self.assertNotIn("headerEl.textContent = headerTitle", self.player_js_content)
        # Ensure it updates pp-title and pp-artist directly
        self.assertIn("let ppTitle = document.getElementById('pp-title');", self.player_js_content)
        self.assertIn("let ppArtist = document.getElementById('pp-artist');", self.player_js_content)
        self.assertIn("ppTitle.textContent = track?.title || 'Трек не выбран';", self.player_js_content)

    # ----------------------------------------------------------------------
    # Fix 2: Player Tab 2-Column Layout & 300px Void Elimination
    # ----------------------------------------------------------------------
    def test_fix2_player_left_col_layout(self):
        """Verify .player-left-col uses space-between and height: 100% to eliminate bottom void."""
        self.assertIn(".player-left-col {", self.view_css_content)
        left_col_match = re.search(r"\.player-left-col\s*\{([^}]+)\}", self.view_css_content)
        self.assertIsNotNone(left_col_match)
        block = left_col_match.group(1)
        self.assertIn("justify-content: space-between;", block)
        self.assertIn("height: 100%;", block)

    def test_fix2_player_cover_section_flex(self):
        """Verify .player-cover-section uses flex: 1 and min-height: 0 to scale dynamically."""
        cover_sec_match = re.search(r"\.player-cover-section\s*\{([^}]+)\}", self.view_css_content)
        self.assertIsNotNone(cover_sec_match)
        block = cover_sec_match.group(1)
        self.assertIn("flex: 1;", block)
        self.assertIn("min-height: 0;", block)

    def test_fix2_player_card_controls_no_wrap(self):
        """Verify .player-card-controls uses flex-wrap: nowrap and wider grid columns."""
        controls_match = re.search(r"\.player-card-controls\s*\{([^}]+)\}", self.view_css_content)
        self.assertIsNotNone(controls_match)
        block = controls_match.group(1)
        self.assertIn("flex-wrap: nowrap;", block)

        layout_match = re.search(r"\.player-2col-layout\s*\{([^}]+)\}", self.view_css_content)
        self.assertIsNotNone(layout_match)
        layout_block = layout_match.group(1)
        self.assertIn("grid-template-columns: minmax(390px, 440px) 1fr;", layout_block)

    # ----------------------------------------------------------------------
    # Fix 3: Dedicated Volume Controls on Player Tab
    # ----------------------------------------------------------------------
    def test_fix3_volume_controls_html(self):
        """Verify dedicated volume controls exist in the Player view of index.html."""
        self.assertIn('id="pp-volume-wrap"', self.html_content)
        self.assertIn('id="pp-volume-btn"', self.html_content)
        self.assertIn('id="pp-volume-track"', self.html_content)
        self.assertIn('id="pp-volume-fill"', self.html_content)

    def test_fix3_volume_controls_css(self):
        """Verify .player-card-volume is styled in player-view.css."""
        self.assertIn(".player-card-volume {", self.view_css_content)
        self.assertIn(".player-card-volume .volume-track {", self.view_css_content)

    def test_fix3_volume_controls_js_binding(self):
        """Verify player.js binds drag and mute events for pp-volume controls."""
        self.assertIn("setupDragBar('pp-volume-track'", self.player_js_content)
        self.assertIn("const ppVolBtn = document.getElementById('pp-volume-btn');", self.player_js_content)
        self.assertIn("setEl('pp-volume-fill', 'width',", self.player_js_content)
        self.assertIn("'pp-volume-btn'", self.player_js_content)

    # ----------------------------------------------------------------------
    # Fix 4: Viewport Height Overrun & Scrollbar Elimination
    # ----------------------------------------------------------------------
    def test_fix4_view_player_height_constraints(self):
        """Verify #view-player sets min-height: 0, height: 100%, and box-sizing: border-box."""
        for css_content, source in [(self.view_css_content, "player-view.css"), (self.bar_css_content, "player-bar.css")]:
            match = re.search(r"#view-player\s*\{([^}]+)\}", css_content)
            self.assertIsNotNone(match, f"#view-player rule not found in {source}")
            block = match.group(1)
            self.assertIn("min-height: 0;", block, f"min-height: 0 missing in {source}")
            self.assertIn("height: 100%;", block, f"height: 100% missing in {source}")
            self.assertIn("box-sizing: border-box;", block, f"box-sizing: border-box missing in {source}")
            self.assertIn("overflow: hidden;", block, f"overflow: hidden missing in {source}")

    # ----------------------------------------------------------------------
    # Fix 5: Responsive Media Query Targeting .player-2col-layout
    # ----------------------------------------------------------------------
    def _extract_media_query_body(self, css_content, query_str):
        idx = css_content.find(query_str)
        if idx == -1:
            return None
        start_brace = css_content.find("{", idx)
        if start_brace == -1:
            return None
        depth = 1
        pos = start_brace + 1
        while pos < len(css_content) and depth > 0:
            if css_content[pos] == "{":
                depth += 1
            elif css_content[pos] == "}":
                depth -= 1
            pos += 1
        return css_content[start_brace + 1:pos - 1]

    def test_fix5_media_query_player_bar_css(self):
        """Verify @media (max-width: 900px) in player-bar.css targets .player-2col-layout."""
        self.assertNotIn(".player-page-container {\n        grid-template-columns: 1fr;", self.bar_css_content)
        mq_body = self._extract_media_query_body(self.bar_css_content, "@media (max-width: 900px)")
        self.assertIsNotNone(mq_body, "Media query @media (max-width: 900px) not found in player-bar.css")
        self.assertIn(".player-2col-layout", mq_body)
        self.assertIn("grid-template-columns: 1fr;", mq_body)

    def test_fix5_media_query_player_view_css(self):
        """Verify @media (max-width: 900px) in player-view.css targets .player-2col-layout."""
        mq_body = self._extract_media_query_body(self.view_css_content, "@media (max-width: 900px)")
        self.assertIsNotNone(mq_body, "Media query @media (max-width: 900px) not found in player-view.css")
        self.assertIn(".player-2col-layout", mq_body)
        self.assertIn("grid-template-columns: 1fr;", mq_body)
        self.assertIn("overflow-y: auto;", mq_body)

    # ----------------------------------------------------------------------
    # Fix 6: Waveform & Canvas Resize on Tab Switch
    # ----------------------------------------------------------------------
    def test_fix6_pages_js_player_tab_hook(self):
        """Verify showPage('player') in pages.js resets waveform cache and triggers resize."""
        self.assertIn("if (pageId === 'player')", self.pages_js_content)
        self.assertIn("document.querySelectorAll('.waveform-canvas')", self.pages_js_content)
        self.assertIn("cv._wfW = undefined;", self.pages_js_content)
        self.assertIn("cv._wfH = undefined;", self.pages_js_content)
        self.assertIn("window.dispatchEvent(new Event('resize'));", self.pages_js_content)
        self.assertIn("window.NeDotify.renderWaveforms()", self.pages_js_content)

    def test_fix6_player_js_exposes_render_waveforms(self):
        """Verify player.js exposes window.NeDotify.renderWaveforms."""
        self.assertIn("window.NeDotify.renderWaveforms = renderWaveforms;", self.player_js_content)

    # ----------------------------------------------------------------------
    # Fix 7: Deduplicate Queue Click Handler
    # ----------------------------------------------------------------------
    def test_fix7_no_duplicate_queue_listener(self):
        """Verify player.js does not attach a competing click listener to #pp-btn-queue."""
        self.assertNotIn("ppQueue.addEventListener('click'", self.player_js_content)
        self.assertNotIn("document.getElementById('pp-btn-queue').addEventListener", self.player_js_content)


if __name__ == "__main__":
    unittest.main()
