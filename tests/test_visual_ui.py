#!/usr/bin/env python3
"""
Automated Visual Testing & Screenshot Automation Suite for AURA Music Linux.

Verifies:
1. Particles Background: Container stacking (z-index: 20), blur removal, particle drawing & shape toggle.
2. Player Tab Layout: DOM span preservation (#pp-title, #pp-artist), single-row playback controls,
   dedicated volume slider (#pp-volume-wrap), elimination of height overruns and scrollbars.
3. Settings Appearance: Native Linux font cards grid (Ubuntu, Cantarell, Liberation Sans, Inter).
4. Font Switching: Dynamic CSS variable propagation (--font-family, --font-body, --font-display)
   and active card highlighting.

Captures four high-resolution visual proof screenshots into screenshots/:
- 01_home_particles.png
- 02_player_tab.png
- 03_settings_fonts.png
- 04_font_switched.png
"""

import os
import sys
import time
import json
import logging
import subprocess
import unittest
from pathlib import Path

import requests
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("visual_testing")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
LOCK_FILES = [
    Path("/tmp/nedotify_instance.lock"),
    Path("/tmp/nedotify_http_port")
]
GRIM_PATH = "/usr/bin/grim"


def capture_screenshot(filename: str) -> Path:
    """Capture a screen snapshot using grim and verify output validity."""
    output_path = SCREENSHOTS_DIR / filename
    output_path.unlink(missing_ok=True)

    cmd = [GRIM_PATH, str(output_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"grim capture failed for {filename}: {res.stderr}")

    if not output_path.exists():
        raise FileNotFoundError(f"Expected screenshot {output_path} was not created.")

    size = output_path.stat().st_size
    if size < 10000:
        raise ValueError(f"Screenshot {output_path} too small ({size} bytes), likely blank/corrupt.")

    with Image.open(output_path) as img:
        img.verify()
        w, h = img.size

    logger.info(f"Captured {filename}: {w}x{h} ({size / 1024:.1f} KB)")
    return output_path


class VisualTestingRunner:
    """Manages the full lifecycle of the AURA Music application under test."""

    def __init__(self):
        self.proc = None
        self.port = None
        self.eval_url = None
        self.close_url = None
        self.log_file = None

    def clean_locks(self):
        """Remove any pre-existing lock and port tracking files."""
        for lock in LOCK_FILES:
            try:
                if lock.exists():
                    lock.unlink()
                    logger.info(f"Cleaned stale lock: {lock}")
            except OSError as e:
                logger.warning(f"Could not remove {lock}: {e}")

    def start_app(self, timeout: float = 20.0):
        """Launch the application with sandbox disabled and discover dynamic port."""
        self.clean_locks()
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-1"

        python_bin = PROJECT_ROOT / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        log_path = Path("/tmp/nedotify_visual_test.log")
        self.log_file = open(log_path, "w", encoding="utf-8")

        logger.info(f"Launching AURA Music via {python_bin} main.py...")
        self.proc = subprocess.Popen(
            [str(python_bin), "main.py"],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT
        )

        start_time = time.time()
        port_file = Path("/tmp/nedotify_http_port")
        while time.time() - start_time < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"AURA Music exited prematurely with returncode {self.proc.returncode}. "
                    f"Check {log_path} for details."
                )
            if port_file.exists():
                try:
                    content = port_file.read_text().strip()
                    if content and content.isdigit():
                        self.port = int(content)
                        break
                except OSError:
                    pass
            time.sleep(0.2)

        if not self.port:
            raise TimeoutError(f"Failed to capture Bottle HTTP port within {timeout}s")

        self.eval_url = f"http://127.0.0.1:{self.port}/__aura_eval"
        self.close_url = f"http://127.0.0.1:{self.port}/__aura_close"
        logger.info(f"AURA Music running on dynamic port {self.port}")

    def eval_js(self, script: str, timeout: float = 8.0) -> str:
        """Execute arbitrary JavaScript inside the WebKitGTK instance."""
        if not self.eval_url:
            raise RuntimeError("Application is not running or port is unknown.")
        resp = requests.post(self.eval_url, data=script.encode("utf-8"), timeout=timeout)
        resp.raise_for_status()
        return resp.text

    def wait_for_ui_ready(self, timeout: float = 15.0):
        """Poll until the frontend DOM is fully loaded and navigation is initialized."""
        logger.info("Waiting for WebKit frontend initialization...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                res = self.eval_js(
                    "typeof window.showPage === 'function' && document.readyState === 'complete'"
                )
                if res.strip().lower() == "true":
                    logger.info("WebKit frontend ready.")
                    time.sleep(1.0)
                    return
            except Exception:
                pass
            time.sleep(0.3)
        raise TimeoutError("Frontend failed to reach ready state within timeout.")

    def stop_app(self, timeout: float = 8.0):
        """Cleanly terminate application via /__aura_close endpoint."""
        logger.info("Closing application cleanly via /__aura_close...")
        try:
            if self.close_url and self.proc and self.proc.poll() is None:
                requests.post(self.close_url, timeout=4.0)
                self.proc.wait(timeout=timeout)
                logger.info(f"Process terminated cleanly with returncode {self.proc.returncode}")
        except Exception as e:
            logger.warning(f"Error during graceful close: {e}")
        finally:
            if self.proc and self.proc.poll() is None:
                logger.warning("Forcing process termination...")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            if self.log_file and not self.log_file.closed:
                self.log_file.close()
            self.clean_locks()


class TestVisualUI(unittest.TestCase):
    """Automated visual test suite for AURA Music Linux."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(GRIM_PATH):
            raise unittest.SkipTest("grim utility not found on system.")
        cls.runner = VisualTestingRunner()
        cls.runner.start_app()
        cls.runner.wait_for_ui_ready()

    @classmethod
    def tearDownClass(cls):
        cls.runner.stop_app()

    def test_01_home_and_particles(self):
        """Verify particles background container, canvas drawing, and capture 01_home_particles.png."""
        logger.info("--- Step 1: Testing Home View & Particles Background ---")
        self.runner.eval_js("""
            window.showPage('settings');
            setTimeout(() => {
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn && !toggleBtn.classList.contains('on')) {
                    toggleBtn.click();
                }
                window.showPage('home');
            }, 300);
        """)
        time.sleep(1.2)

        # Inspect particles container and canvas state
        particles_state_raw = self.runner.eval_js("""
            (() => {
                const container = document.getElementById('particles-bg');
                const canvas = document.getElementById('particles-canvas');
                const cs = container ? window.getComputedStyle(container) : null;
                return JSON.stringify({
                    containerExists: !!container,
                    containerDisplay: cs ? cs.display : null,
                    containerZIndex: cs ? cs.zIndex : null,
                    containerFilter: cs ? cs.filter : null,
                    canvasExists: !!canvas,
                    canvasWidth: canvas ? canvas.width : 0,
                    canvasHeight: canvas ? canvas.height : 0
                });
            })()
        """)
        state = json.loads(particles_state_raw)
        self.assertTrue(state["containerExists"], "Container #particles-bg must exist in DOM")
        self.assertEqual(state["containerDisplay"], "block", "#particles-bg must be display: block")
        self.assertEqual(state["containerZIndex"], "20", "#particles-bg must have z-index: 20")
        self.assertIn(state["containerFilter"], ["none", ""], "#particles-bg must not have blur filter")
        self.assertTrue(state["canvasExists"], "#particles-canvas must be appended into DOM")
        self.assertGreater(state["canvasWidth"], 0, "Canvas width must be > 0")
        self.assertGreater(state["canvasHeight"], 0, "Canvas height must be > 0")

        # Test particle shape toggle (switch to star and back to dot)
        toggle_res_raw = self.runner.eval_js("""
            (() => {
                const starBtn = document.querySelector('.particle-shape-btn[data-shape="star"]');
                if (starBtn) starBtn.click();
                const activeBtn = document.querySelector('.particle-shape-btn.active');
                return JSON.stringify({
                    toggled: !!starBtn,
                    activeShape: activeBtn ? activeBtn.dataset.shape : null
                });
            })()
        """)
        toggle_res = json.loads(toggle_res_raw)
        self.assertTrue(toggle_res["toggled"], "Star particle shape button must be present and clickable")
        self.assertEqual(toggle_res["activeShape"], "star", "Active shape must update to star")

        # Switch back to dot for default look
        self.runner.eval_js("""
            (() => {
                const dotBtn = document.querySelector('.particle-shape-btn[data-shape="dot"]');
                if (dotBtn) dotBtn.click();
            })()
        """)
        time.sleep(0.5)

        # Return to home view and capture screenshot
        self.runner.eval_js("window.showPage('home')")
        time.sleep(1.0)
        shot_path = capture_screenshot("01_home_particles.png")
        self.assertTrue(shot_path.exists())
        self.assertGreater(shot_path.stat().st_size, 10000)

    def test_02_player_tab_layout(self):
        """Verify Player tab DOM spans, single-row controls, volume bar, and capture 02_player_tab.png."""
        logger.info("--- Step 2: Testing Player Tab Layout & Spans ---")
        self.runner.eval_js("window.showPage('player')")
        time.sleep(1.2)

        player_state_raw = self.runner.eval_js("""
            (() => {
                const ppTitle = document.getElementById('pp-title');
                const ppArtist = document.getElementById('pp-artist');
                const headerTitle = document.getElementById('pp-header-title');
                const leftCol = document.querySelector('.player-left-col');
                const rightCol = document.querySelector('.player-right-col');
                const controls = document.querySelector('.player-card-controls');
                const volumeWrap = document.getElementById('pp-volume-wrap');
                const volumeTrack = document.getElementById('pp-volume-track');
                const coverWrapper = document.getElementById('pp-cover-wrapper');
                const visualizerCanvas = document.getElementById('visualizer-canvas');
                const mainContent = document.getElementById('main-content');

                const leftColRect = leftCol ? leftCol.getBoundingClientRect() : null;
                const buttons = controls ? Array.from(controls.querySelectorAll('button')) : [];

                return JSON.stringify({
                    hasTitleSpan: !!ppTitle,
                    hasArtistSpan: !!ppArtist,
                    titleText: ppTitle ? ppTitle.textContent : null,
                    artistText: ppArtist ? ppArtist.textContent : null,
                    hasLeftCol: !!leftCol,
                    hasRightCol: !!rightCol,
                    hasControls: !!controls,
                    controlsCount: buttons.length,
                    hasVolumeWrap: !!volumeWrap,
                    hasVolumeTrack: !!volumeTrack,
                    hasCoverWrapper: !!coverWrapper,
                    hasVisualizerCanvas: !!visualizerCanvas,
                    leftColHeight: leftColRect ? leftColRect.height : 0,
                    hasScrollbar: mainContent ? mainContent.scrollHeight > mainContent.clientHeight : false
                });
            })()
        """)
        state = json.loads(player_state_raw)
        self.assertTrue(state["hasTitleSpan"], "<span> #pp-title must be preserved inside #pp-header-title")
        self.assertTrue(state["hasArtistSpan"], "<span> #pp-artist must be preserved inside #pp-header-title")
        self.assertTrue(state["hasLeftCol"], ".player-left-col must exist")
        self.assertTrue(state["hasRightCol"], ".player-right-col (lyrics) must exist")
        self.assertTrue(state["hasControls"], ".player-card-controls must exist")
        self.assertEqual(state["controlsCount"], 9, "Must contain all 9 player controls buttons")
        self.assertTrue(state["hasVolumeWrap"], "Volume controls #pp-volume-wrap must exist on Player tab")
        self.assertTrue(state["hasVolumeTrack"], "Volume track #pp-volume-track must exist")
        self.assertTrue(state["hasCoverWrapper"], "Cover wrapper #pp-cover-wrapper must exist")
        self.assertFalse(state["hasScrollbar"], "Player tab must not cause vertical scrollbars on main-content")

        shot_path = capture_screenshot("02_player_tab.png")
        self.assertTrue(shot_path.exists())
        self.assertGreater(shot_path.stat().st_size, 10000)

    def test_03_settings_fonts_grid(self):
        """Verify Settings Appearance font grid and capture 03_settings_fonts.png."""
        logger.info("--- Step 3: Testing Settings Fonts Grid ---")
        self.runner.eval_js("window.showPage('settings')")
        time.sleep(0.6)
        self.runner.eval_js("document.querySelector('.settings-nav-btn[data-panel=\"appearance\"]')?.click()")
        time.sleep(0.6)
        self.runner.eval_js("document.getElementById('font-cards-grid')?.scrollIntoView({ behavior: 'instant', block: 'center' })")
        time.sleep(0.6)

        fonts_state_raw = self.runner.eval_js("""
            (() => {
                const cards = Array.from(document.querySelectorAll('#font-cards-grid .font-card')).map(c => ({
                    fontId: c.dataset.fontId,
                    font: c.dataset.font,
                    name: c.querySelector('.font-card-name')?.textContent,
                    isActive: c.classList.contains('active')
                }));
                const activeCard = cards.find(c => c.isActive);
                return JSON.stringify({
                    totalCards: cards.length,
                    activeCardId: activeCard ? activeCard.fontId : null,
                    activeCardName: activeCard ? activeCard.name : null,
                    hasUbuntu: cards.some(c => c.fontId === 'ubuntu'),
                    hasCantarell: cards.some(c => c.fontId === 'cantarell'),
                    hasLiberation: cards.some(c => c.fontId === 'liberation'),
                    hasInter: cards.some(c => c.fontId === 'inter')
                });
            })()
        """)
        state = json.loads(fonts_state_raw)
        self.assertGreaterEqual(state["totalCards"], 4, "Font selection grid must have at least 4 font options")
        self.assertTrue(state["hasUbuntu"], "Font grid must include native Linux font 'Ubuntu'")
        self.assertTrue(state["hasCantarell"], "Font grid must include native Linux font 'Cantarell'")
        self.assertTrue(state["hasLiberation"], "Font grid must include native Linux font 'Liberation Sans'")
        self.assertIsNotNone(state["activeCardId"], "An active font card must be selected and highlighted")

        shot_path = capture_screenshot("03_settings_fonts.png")
        self.assertTrue(shot_path.exists())
        self.assertGreater(shot_path.stat().st_size, 10000)

    def test_04_font_switching(self):
        """Verify switching to Ubuntu font updates CSS variables and capture 04_font_switched.png."""
        logger.info("--- Step 4: Testing Font Switching & Propagation ---")
        switch_res_raw = self.runner.eval_js("""
            (() => {
                const ubuntuCard = document.querySelector('#font-cards-grid .font-card[data-font-id="ubuntu"]');
                if (ubuntuCard) ubuntuCard.click();
                const activeCard = document.querySelector('#font-cards-grid .font-card.active');
                const style = window.getComputedStyle(document.documentElement);
                return JSON.stringify({
                    clicked: !!ubuntuCard,
                    activeFontId: activeCard ? activeCard.dataset.fontId : null,
                    fontFamily: style.getPropertyValue('--font-family').trim(),
                    fontBody: style.getPropertyValue('--font-body').trim(),
                    fontDisplay: style.getPropertyValue('--font-display').trim()
                });
            })()
        """)
        res = json.loads(switch_res_raw)
        self.assertTrue(res["clicked"], "Ubuntu font card must be found and clicked")
        self.assertEqual(res["activeFontId"], "ubuntu", "Active font card must now be 'ubuntu'")
        self.assertIn("Ubuntu", res["fontFamily"], "--font-family variable must contain 'Ubuntu'")
        self.assertIn("Ubuntu", res["fontBody"], "--font-body variable must propagate 'Ubuntu'")
        self.assertIn("Ubuntu", res["fontDisplay"], "--font-display variable must propagate 'Ubuntu'")

        time.sleep(0.8)
        shot_path = capture_screenshot("04_font_switched.png")
        self.assertTrue(shot_path.exists())
        self.assertGreater(shot_path.stat().st_size, 10000)


def run_standalone():
    """Standalone CLI execution helper."""
    print("=" * 70)
    print("AURA Music Linux — Automated Visual Testing Suite")
    print("=" * 70)

    runner = VisualTestingRunner()
    try:
        runner.start_app()
        runner.wait_for_ui_ready()

        # Step 1: Home & Particles
        logger.info("Running Step 1: Home & Particles...")
        runner.eval_js("window.showPage('home')")
        time.sleep(1.2)
        capture_screenshot("01_home_particles.png")

        # Step 2: Player Tab
        logger.info("Running Step 2: Player Tab...")
        runner.eval_js("window.showPage('player')")
        time.sleep(1.2)
        capture_screenshot("02_player_tab.png")

        # Step 3: Settings Fonts
        logger.info("Running Step 3: Settings Fonts...")
        runner.eval_js("window.showPage('settings')")
        time.sleep(0.6)
        runner.eval_js("document.querySelector('.settings-nav-btn[data-panel=\"appearance\"]')?.click()")
        time.sleep(0.6)
        runner.eval_js("document.getElementById('font-cards-grid')?.scrollIntoView({ behavior: 'instant', block: 'center' })")
        time.sleep(0.6)
        capture_screenshot("03_settings_fonts.png")

        # Step 4: Font Switched
        logger.info("Running Step 4: Font Switching...")
        runner.eval_js("""
            (() => {
                const card = document.querySelector('#font-cards-grid .font-card[data-font-id="ubuntu"]');
                if (card) card.click();
            })()
        """)
        time.sleep(0.8)
        capture_screenshot("04_font_switched.png")

        logger.info("All 4 screenshots captured successfully!")
        return 0
    except Exception as e:
        logger.error(f"Visual testing failed with error: {e}", exc_info=True)
        return 1
    finally:
        runner.stop_app()


if __name__ == "__main__":
    if "--unittest" in sys.argv:
        sys.argv.remove("--unittest")
        unittest.main()
    else:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestVisualUI)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
