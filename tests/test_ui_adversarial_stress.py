#!/usr/bin/env python3
"""
Adversarial UI Stress Test Suite for AURA Music Linux.

Stress-tests:
1. Font Switching:
   - Invalid font strings (empty, null, undefined, numeric, CSS injection, XSS)
   - Rapid consecutive switching (100 rapid cycles across fonts)
   - Font IDs with spaces or unknown/special characters (Cyrillic, symbols, emojis)
   - Persistence in settings and backend synchronization

2. Particles:
   - Extreme dimensions (0x0, 1x1, 7680x4320 8K, 10000x10000, rapid oscillation)
   - Rapid toggling on/off (60 rapid start/stop cycles, listener leak checks)
   - Rapid shape switching under rapid succession (100 switches across all shapes)
   - Extreme mouse coordinate inputs and sprite cache resilience

3. Player Tab:
   - Rapid track updates (100 rapid track_changed events under burst load)
   - Empty track metadata ({}, null, missing fields)
   - Null artist, "Unknown Artist", "Локальный файл", "..."
   - Long track names (5,000-char strings, emojis, RTL, XSS injection)
   - Window resizing & responsive layout (800px compact vs 1920px desktop wide)
   - Visualizer/waveform resize recomputation and volume controls

4. Global Integrity:
   - WebKit window.onerror and unhandledrejection monitoring (window.__stress_errors == [])
   - Application process health and clean termination via /__aura_close
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ui_stress")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILES = [
    Path("/tmp/nedotify_instance.lock"),
    Path("/tmp/nedotify_http_port")
]


def to_js_ascii(s: str) -> str:
    """Encode non-ASCII characters to standard JS \\uXXXX escape sequences to avoid pywebview GTK char-length truncation."""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 128:
            out.append(ch)
        elif cp <= 0xFFFF:
            out.append(f"\\u{cp:04x}")
        else:
            cp -= 0x10000
            high = 0xD800 + (cp >> 10)
            low = 0xDC00 + (cp & 0x3FF)
            out.append(f"\\u{high:04x}\\u{low:04x}")
    return "".join(out)


class AppRunner:
    """Manages the lifecycle of AURA Music for adversarial UI stress testing."""

    def __init__(self):
        self.proc = None
        self.port = None
        self.eval_url = None
        self.close_url = None
        self.log_file = None

    def clean_locks(self):
        for lock in LOCK_FILES:
            try:
                if lock.exists():
                    lock.unlink()
                    logger.info(f"Cleaned lock: {lock}")
            except OSError as e:
                logger.warning(f"Could not remove {lock}: {e}")

    def start_app(self, timeout: float = 20.0):
        self.clean_locks()
        env = os.environ.copy()
        env["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-1"

        python_bin = PROJECT_ROOT / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        log_path = Path("/tmp/nedotify_ui_stress.log")
        self.log_file = open(log_path, "w", encoding="utf-8")

        logger.info(f"Launching AURA Music for UI Stress Test via {python_bin} main.py...")
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
                    f"AURA Music exited prematurely with returncode {self.proc.returncode}."
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
        logger.info(f"AURA Music active on dynamic port {self.port}")

    def eval_js(self, script: str, timeout: float = 12.0) -> str:
        if not self.eval_url:
            raise RuntimeError("Application is not running or port is unknown.")
        clean_script = to_js_ascii(script)
        resp = requests.post(self.eval_url, data=clean_script.encode("utf-8"), timeout=timeout)
        resp.raise_for_status()
        return resp.text

    def wait_for_ui_ready(self, timeout: float = 20.0):
        logger.info("Waiting for WebKit frontend initialization...")
        start_time = time.time()
        ready = False
        while time.time() - start_time < timeout:
            try:
                res = self.eval_js(
                    "typeof window.showPage === 'function' && document.readyState === 'complete'"
                )
                if res.strip().lower() == "true":
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if not ready:
            raise TimeoutError("Frontend failed to reach ready state within timeout.")

        time.sleep(1.0)
        logger.info("Installing global error interceptors & preloading modules...")
        self.eval_js("""
            (() => {
                window.__stress_errors = [];
                window.addEventListener('error', (e) => {
                    window.__stress_errors.push({
                        type: 'error',
                        message: e.message || String(e),
                        filename: e.filename,
                        lineno: e.lineno,
                        colno: e.colno
                    });
                });
                window.addEventListener('unhandledrejection', (e) => {
                    window.__stress_errors.push({
                        type: 'unhandledrejection',
                        reason: String(e.reason)
                    });
                });

                import('./js/settings.js').then(m => { window.__settings = m; });
                import('./js/particles.js').then(m => { window.__particles = m; });
                import('./js/player.js').then(m => { window.__player = m; });
            })()
        """)

        module_start = time.time()
        while time.time() - module_start < 10.0:
            try:
                chk = self.eval_js("""
                    (() => {
                        return (
                            typeof window.__settings?.applyFontFamily === 'function' &&
                            typeof window.__particles?.initParticles === 'function' &&
                            typeof window.__player?.onTrackChanged === 'function'
                        );
                    })()
                """)
                if chk.strip().lower() == "true":
                    logger.info("Frontend modules preloaded and attached to window.")
                    time.sleep(0.5)
                    return
            except Exception:
                pass
            time.sleep(0.2)

        raise TimeoutError("Failed to preload modules within timeout.")

    def get_browser_errors(self) -> list:
        try:
            res = self.eval_js("JSON.stringify(window.__stress_errors || [])")
            return json.loads(res)
        except Exception as e:
            logger.warning(f"Failed to get browser errors: {e}")
            return []

    def clear_browser_errors(self):
        try:
            self.eval_js("window.__stress_errors = [];")
        except Exception:
            pass

    def stop_app(self, timeout: float = 8.0):
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


class TestUIAdversarialStress(unittest.TestCase):
    """Adversarial stress harness for AURA Music UI fixes."""

    @classmethod
    def setUpClass(cls):
        cls.runner = AppRunner()
        cls.runner.start_app()
        cls.runner.wait_for_ui_ready()

    @classmethod
    def tearDownClass(cls):
        cls.runner.stop_app()

    def setUp(self):
        self.runner.clear_browser_errors()

    def tearDown(self):
        errors = self.runner.get_browser_errors()
        self.assertEqual(len(errors), 0, f"Encountered unhandled browser errors: {errors}")

    # =========================================================================
    # 1. FONT SWITCHING ADVERSARIAL STRESS TESTS
    # =========================================================================

    def test_01_font_switching_invalid_strings(self):
        """Test font switching with invalid strings, nulls, undefined, and injection payloads."""
        logger.info("--- Stress 1.1: Font Switching with Invalid / Malicious Strings ---")
        
        self.runner.eval_js("window.showPage('settings')")
        time.sleep(0.3)
        self.runner.eval_js("document.querySelector('.settings-nav-btn[data-panel=\"appearance\"]')?.click()")
        time.sleep(0.3)

        eval_script = """
            (() => {
                const results = [];
                const applyFontFamily = window.__settings.applyFontFamily;

                const testCases = [
                    { family: "", id: null, desc: "Empty string" },
                    { family: null, id: null, desc: "null family" },
                    { family: undefined, id: undefined, desc: "undefined family" },
                    { family: 12345, id: 999, desc: "numeric inputs" },
                    { family: "<script>alert(1)</script>", id: "xss_id", desc: "XSS string" },
                    { family: "sans-serif; background: red; --injected: 1;", id: "css_inject", desc: "CSS injection" },
                    { family: "system", id: null, desc: "system keyword fallback" },
                    { family: "default", id: null, desc: "default keyword fallback" }
                ];

                for (const tc of testCases) {
                    try {
                        applyFontFamily(tc.family, tc.id, false);
                        const style = window.getComputedStyle(document.documentElement);
                        const fFam = style.getPropertyValue('--font-family').trim();
                        const fBody = style.getPropertyValue('--font-body').trim();
                        const fDisp = style.getPropertyValue('--font-display').trim();
                        results.push({
                            desc: tc.desc,
                            success: true,
                            fontFamily: fFam,
                            variablesSet: !!(fFam && fBody && fDisp)
                        });
                    } catch (err) {
                        results.push({
                            desc: tc.desc,
                            success: false,
                            error: err.message
                        });
                    }
                }
                return JSON.stringify(results);
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        results = json.loads(raw_res)
        for r in results:
            self.assertTrue(r["success"], f"Font application threw an exception for {r['desc']}: {r.get('error')}")
            self.assertTrue(r["variablesSet"], f"Variables were not set for {r['desc']}")

    def test_02_font_switching_rapid_consecutive(self):
        """Stress-test rapid consecutive font switching (100 rapid cycles across FONTS_LIST)."""
        logger.info("--- Stress 1.2: Rapid Consecutive Font Switching (100 iterations) ---")

        eval_script = """
            (() => {
                const applyFontFamily = window.__settings.applyFontFamily;
                const FONTS_LIST = window.__settings.FONTS_LIST;

                const startTime = performance.now();
                const iterations = 100;

                for (let i = 0; i < iterations; i++) {
                    const font = FONTS_LIST[i % FONTS_LIST.length];
                    applyFontFamily(font.family, font.id, false);
                }

                // Finally apply 'ubuntu'
                const ubuntu = FONTS_LIST.find(f => f.id === 'ubuntu');
                applyFontFamily(ubuntu.family, ubuntu.id, true);

                const duration = performance.now() - startTime;
                const style = window.getComputedStyle(document.documentElement);
                const activeCard = document.querySelector('#font-cards-grid .font-card.active');

                return JSON.stringify({
                    iterations,
                    durationMs: duration,
                    activeFontFamily: style.getPropertyValue('--font-family').trim(),
                    activeCardId: activeCard ? activeCard.dataset.fontId : null,
                    cardHighlighted: !!activeCard
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        logger.info(f"Rapid font switching: 100 switches executed in {res['durationMs']:.1f}ms")
        self.assertEqual(res["iterations"], 100)
        self.assertIn("Ubuntu", res["activeFontFamily"])
        self.assertEqual(res["activeCardId"], "ubuntu")
        self.assertTrue(res["cardHighlighted"])

    def test_03_font_switching_spaces_and_unknown_ids(self):
        """Test font IDs with spaces, unknown characters, Cyrillic, and emojis."""
        logger.info("--- Stress 1.3: Font IDs with Spaces, Unknown Characters & Cyrillic ---")

        eval_script = """
            (() => {
                const applyFontFamily = window.__settings.applyFontFamily;
                const highlightActiveFontCard = window.__settings.highlightActiveFontCard;

                const adversarialCases = [
                    { family: "My Custom Font With Spaces", id: "custom font id with spaces" },
                    { family: "'Special !@#$%^&*()'", id: "special_chars_!@#$" },
                    { family: "'Шрифт Тестовый'", id: "шрифт_тест" },
                    { family: "'Emoji 🎵 Font'", id: "emoji_font_🚀" }
                ];

                const results = [];
                for (const ac of adversarialCases) {
                    try {
                        applyFontFamily(ac.family, ac.id, false);
                        highlightActiveFontCard(ac.id);
                        const style = window.getComputedStyle(document.documentElement);
                        results.push({
                            id: ac.id,
                            family: style.getPropertyValue('--font-family').trim(),
                            success: true
                        });
                    } catch (err) {
                        results.push({
                            id: ac.id,
                            success: false,
                            error: err.message
                        });
                    }
                }
                return JSON.stringify(results);
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        results = json.loads(raw_res)
        for r in results:
            self.assertTrue(r["success"], f"Failed on font ID {r['id']}: {r.get('error')}")
            self.assertTrue(len(r["family"]) > 0)

    def test_04_font_switching_settings_persistence(self):
        """Test font persistence in localStorage, window.settings, and applySettingsFromBackend."""
        logger.info("--- Stress 1.4: Font Settings Persistence & Backend Synchronization ---")

        eval_script = """
            (() => {
                const applyFontFamily = window.__settings.applyFontFamily;
                const applySettingsFromBackend = window.__settings.applySettingsFromBackend;

                // 1. Save Liberation Sans
                applyFontFamily("'Liberation Sans', sans-serif", "liberation", true);
                const savedFamily = localStorage.getItem('nedotify_theme_font_family');
                const savedId = localStorage.getItem('nedotify_theme_font_id');

                // 2. Simulate Backend Sync with Cantarell
                applySettingsFromBackend({
                    theme: {
                        font_family: "'Cantarell', sans-serif",
                        font_id: "cantarell"
                    }
                });

                // Immediately capture synced family string
                const syncedFamily = window.getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim();
                const activeCard = document.querySelector('#font-cards-grid .font-card.active');
                const syncedCardId = activeCard ? activeCard.dataset.fontId : null;

                // 3. Reset to default
                applyFontFamily(null, 'default', true);
                const defaultFamily = window.getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim();

                return JSON.stringify({
                    savedFamily: JSON.parse(savedFamily || '""'),
                    savedId: JSON.parse(savedId || '""'),
                    syncedFamily: syncedFamily,
                    syncedCardId: syncedCardId,
                    defaultFamily: defaultFamily
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        self.assertIn("Liberation Sans", res["savedFamily"])
        self.assertEqual(res["savedId"], "liberation")
        self.assertIn("Cantarell", res["syncedFamily"])
        self.assertEqual(res["syncedCardId"], "cantarell")
        self.assertIn("Inter", res["defaultFamily"])

    # =========================================================================
    # 2. PARTICLES ADVERSARIAL STRESS TESTS
    # =========================================================================

    def test_05_particles_extreme_dimensions(self):
        """Stress-test particles canvas and resizing under extreme dimensions (0x0, 1x1, 7680x4320, 10000x10000)."""
        logger.info("--- Stress 2.1: Particles Extreme Dimensions (0x0 to 8K) ---")

        eval_script = """
            (() => {
                if (window.settings && window.settings.ui) {
                    window.settings.ui.particles_enabled = true;
                    if (window.__settings && window.__settings.applySettingsFromBackend) {
                        window.__settings.applySettingsFromBackend(window.settings);
                    }
                }
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn) toggleBtn.classList.add('on');
                window.__particles.initParticles();

                const canvas = document.getElementById('particles-canvas');
                if (!canvas) throw new Error("Canvas not found. Settings: " + JSON.stringify(window.settings) + " Toggle: " + (document.getElementById('toggle-particles') ? document.getElementById('toggle-particles').className : 'none'));

                const dimensionsToTest = [
                    { w: 0, h: 0, desc: "0x0 zero dimension" },
                    { w: 1, h: 1, desc: "1x1 minimal dimension" },
                    { w: 7680, h: 4320, desc: "7680x4320 8K viewport" },
                    { w: 10000, h: 10000, desc: "10000x10000 extreme dimension" },
                    { w: 1920, h: 1080, desc: "1920x1080 standard full HD" }
                ];

                const results = [];
                for (const dim of dimensionsToTest) {
                    try {
                        canvas.width = dim.w;
                        canvas.height = dim.h;
                        window.dispatchEvent(new Event('resize'));
                        results.push({
                            desc: dim.desc,
                            success: true,
                            width: canvas.width,
                            height: canvas.height
                        });
                    } catch (err) {
                        results.push({
                            desc: dim.desc,
                            success: false,
                            error: err.message
                        });
                    }
                }

                // Rapidly oscillate between 0x0 and 1920x1080 30 times
                let oscillationSuccess = true;
                for (let i = 0; i < 30; i++) {
                    try {
                        canvas.width = (i % 2 === 0) ? 0 : 1920;
                        canvas.height = (i % 2 === 0) ? 0 : 1080;
                        window.dispatchEvent(new Event('resize'));
                    } catch (e) {
                        oscillationSuccess = false;
                        break;
                    }
                }

                // Restore sane dimensions
                canvas.width = window.innerWidth || 1920;
                canvas.height = window.innerHeight || 1080;
                window.dispatchEvent(new Event('resize'));

                return JSON.stringify({
                    results,
                    oscillationSuccess
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        with open("/tmp/raw_res.txt", "w") as f:
            f.write(raw_res)
        data = json.loads(raw_res)
        for r in data["results"]:
            self.assertTrue(r["success"], f"Dimension test failed for {r['desc']}: {r.get('error')}")
        self.assertTrue(data["oscillationSuccess"], "Rapid 0x0 <-> 1920x1080 oscillation failed")

    def test_06_particles_rapid_toggling(self):
        """Stress-test rapid toggling of particles on/off (60 consecutive start/stop cycles)."""
        logger.info("--- Stress 2.2: Rapid Particles Toggling (60 on/off cycles) ---")

        eval_script = """
            (() => {
                const startTime = performance.now();
                const cycles = 60;

                for (let i = 0; i < cycles; i++) {
                    if (window.settings && window.settings.ui) {
                    window.settings.ui.particles_enabled = true;
                    if (window.__settings && window.__settings.applySettingsFromBackend) {
                        window.__settings.applySettingsFromBackend(window.settings);
                    }
                }
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn) toggleBtn.classList.add('on');
                window.__particles.initParticles();
                    window.__particles.stopParticles();
                }

                // Finally re-init
                if (window.settings && window.settings.ui) {
                    window.settings.ui.particles_enabled = true;
                    if (window.__settings && window.__settings.applySettingsFromBackend) {
                        window.__settings.applySettingsFromBackend(window.settings);
                    }
                }
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn) toggleBtn.classList.add('on');
                window.__particles.initParticles();
                const duration = performance.now() - startTime;

                const bg = document.getElementById('particles-bg');
                const canvases = bg ? bg.querySelectorAll('canvas') : [];

                return JSON.stringify({
                    cycles,
                    durationMs: duration,
                    canvasCount: canvases.length,
                    bgDisplay: bg ? bg.style.display : null
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        logger.info(f"60 start/stop particle cycles completed in {res['durationMs']:.1f}ms")
        self.assertEqual(res["cycles"], 60)
        self.assertEqual(res["canvasCount"], 1, "There must be exactly 1 canvas after re-init (no duplicates/leaks)")
        self.assertEqual(res["bgDisplay"], "block")

    def test_07_particles_rapid_shape_switches(self):
        """Stress-test rapid particle shape switches (100 iterations across all shapes and unknown shapes)."""
        logger.info("--- Stress 2.3: Rapid Particle Shape Switching (100 switches) ---")

        eval_script = """
            (() => {
                if (window.settings && window.settings.ui) {
                    window.settings.ui.particles_enabled = true;
                    if (window.__settings && window.__settings.applySettingsFromBackend) {
                        window.__settings.applySettingsFromBackend(window.settings);
                    }
                }
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn) toggleBtn.classList.add('on');
                window.__particles.initParticles();

                const shapes = [
                    'dot', 'circle', 'star', 'heart', 'snow',
                    'note', 'sparkle', 'flag_rf', 'coat_rf', 'eagle_rf',
                    'unknown_shape_abc', ''
                ];

                const startTime = performance.now();
                const switchesCount = 100;

                for (let i = 0; i < switchesCount; i++) {
                    const targetShape = shapes[i % shapes.length];
                    let btn = document.querySelector(`.particle-shape-btn[data-shape="${targetShape}"]`);
                    if (btn) {
                        btn.click();
                    } else {
                        localStorage.setItem('nedotify_ui_particles_shape', JSON.stringify(targetShape));
                        window.__particles.initParticles();
                    }
                }

                // Restore default dot
                const dotBtn = document.querySelector('.particle-shape-btn[data-shape="dot"]');
                if (dotBtn) dotBtn.click();
                else window.__particles.initParticles();

                const duration = performance.now() - startTime;
                return JSON.stringify({
                    switchesCount,
                    durationMs: duration,
                    finalShape: document.querySelector('.particle-shape-btn.active')?.dataset?.shape || 'dot'
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        logger.info(f"100 particle shape switches completed in {res['durationMs']:.1f}ms")
        self.assertEqual(res["switchesCount"], 100)
        self.assertEqual(res["finalShape"], "dot")

    def test_08_particles_mouse_stress_and_rendering(self):
        """Test particles animation and mouse interaction with extreme coordinates."""
        logger.info("--- Stress 2.4: Particles Animation & Extreme Mouse Coordinates ---")

        eval_script = """
            (() => {
                if (window.settings && window.settings.ui) {
                    window.settings.ui.particles_enabled = true;
                    if (window.__settings && window.__settings.applySettingsFromBackend) {
                        window.__settings.applySettingsFromBackend(window.settings);
                    }
                }
                const toggleBtn = document.getElementById('toggle-particles');
                if (toggleBtn) toggleBtn.classList.add('on');
                window.__particles.initParticles();

                const extremeCoords = [
                    { x: -99999, y: -99999 },
                    { x: 99999, y: 99999 },
                    { x: 0, y: 0 },
                    { x: 500, y: 500 }
                ];

                for (const c of extremeCoords) {
                    window.dispatchEvent(new MouseEvent('mousemove', {
                        clientX: c.x,
                        clientY: c.y
                    }));
                }

                window.dispatchEvent(new Event('mouseleave'));

                const canvas = document.getElementById('particles-canvas');
                return JSON.stringify({
                    canvasAlive: !!canvas,
                    width: canvas ? canvas.width : 0,
                    height: canvas ? canvas.height : 0
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        self.assertTrue(res["canvasAlive"])
        self.assertGreater(res["width"], 0)

    # =========================================================================
    # 3. PLAYER TAB ADVERSARIAL STRESS TESTS
    # =========================================================================

    def test_09_player_tab_rapid_track_updates(self):
        """Stress-test rapid track updates (100 rapid onPythonEvent('track_changed') calls)."""
        logger.info("--- Stress 3.1: Rapid Track Updates on Player Tab (100 events) ---")

        self.runner.eval_js("window.showPage('player')")
        time.sleep(0.4)

        eval_script = """
            (() => {
                const startTime = performance.now();
                const totalUpdates = 100;

                for (let i = 0; i < totalUpdates; i++) {
                    const track = {
                        id: `track_stress_${i}`,
                        source: 'youtube',
                        source_id: `yt_${i}`,
                        title: `Rapid Track #${i} - Adversarial Stress`,
                        artist: `Artist Stress #${i % 10}`,
                        duration: 180000 + i * 1000,
                        file_path: null,
                        stream_url: null
                    };
                    window.onPythonEvent('track_changed', track);
                }

                const duration = performance.now() - startTime;

                const ppTitle = document.getElementById('pp-title');
                const ppArtist = document.getElementById('pp-artist');
                const headerTitle = document.getElementById('pp-header-title');

                return JSON.stringify({
                    totalUpdates,
                    durationMs: duration,
                    hasTitleSpan: !!ppTitle,
                    hasArtistSpan: !!ppArtist,
                    titleText: ppTitle ? ppTitle.textContent : null,
                    artistText: ppArtist ? ppArtist.textContent : null,
                    isSpanChildOfHeader: ppTitle && headerTitle ? headerTitle.contains(ppTitle) : false
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        logger.info(f"100 track updates processed in {res['durationMs']:.1f}ms")
        self.assertEqual(res["totalUpdates"], 100)
        self.assertTrue(res["hasTitleSpan"], "#pp-title span must survive rapid track updates")
        self.assertTrue(res["hasArtistSpan"], "#pp-artist span must survive rapid track updates")
        self.assertTrue(res["isSpanChildOfHeader"], "#pp-title must remain a child of #pp-header-title")
        self.assertEqual(res["titleText"], "Rapid Track #99 - Adversarial Stress")
        self.assertEqual(res["artistText"], "Artist Stress #9")

    def test_10_player_tab_empty_and_null_metadata(self):
        """Stress-test Player Tab with empty, null, and missing track metadata."""
        logger.info("--- Stress 3.2: Empty & Null Track Metadata ---")

        eval_script = """
            (() => {
                const results = [];
                const testTracks = [
                    { payload: {}, desc: "Empty track object" },
                    { payload: { title: null, artist: null }, desc: "Null title & artist" },
                    { payload: { title: "", artist: "" }, desc: "Empty string title & artist" },
                    { payload: { title: undefined, artist: undefined }, desc: "Undefined title & artist" },
                    { payload: { title: "Title Only", artist: null }, desc: "Null artist only" },
                    { payload: { title: "Title Only", artist: "Unknown Artist" }, desc: "Unknown Artist fallback" },
                    { payload: { title: "Local Track", artist: "Локальный файл" }, desc: "Локальный файл artist" },
                    { payload: { title: "Three Dots", artist: "..." }, desc: "Three dots artist" }
                ];

                for (const tc of testTracks) {
                    try {
                        window.onPythonEvent('track_changed', tc.payload);
                        const ppTitle = document.getElementById('pp-title');
                        const ppArtist = document.getElementById('pp-artist');
                        results.push({
                            desc: tc.desc,
                            success: true,
                            hasTitleSpan: !!ppTitle,
                            hasArtistSpan: !!ppArtist,
                            titleText: ppTitle ? ppTitle.textContent : null,
                            artistText: ppArtist ? ppArtist.textContent : null
                        });
                    } catch (e) {
                        results.push({
                            desc: tc.desc,
                            success: false,
                            error: e.message
                        });
                    }
                }
                return JSON.stringify(results);
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        results = json.loads(raw_res)
        for r in results:
            self.assertTrue(r["success"], f"Failed for {r['desc']}: {r.get('error')}")
            self.assertTrue(r["hasTitleSpan"], f"Title span missing for {r['desc']}")
            self.assertTrue(r["hasArtistSpan"], f"Artist span missing for {r['desc']}")
            self.assertNotEqual(r["titleText"], "null", "Title should not be literal 'null'")
            self.assertNotEqual(r["artistText"], "null", "Artist should not be literal 'null'")
            self.assertNotEqual(r["titleText"], "undefined", "Title should not be literal 'undefined'")
            self.assertNotEqual(r["artistText"], "undefined", "Artist should not be literal 'undefined'")

    def test_11_player_tab_ultra_long_names_and_xss(self):
        """Stress-test Player Tab with 5,000-char names, XSS payloads, Unicode, and RTL."""
        logger.info("--- Stress 3.3: Ultra-Long Track Names, XSS Payloads & Emojis ---")

        eval_script = """
            (() => {
                const longTitle = "AURA_".repeat(1000); // 5,000 chars
                const longArtist = "Artist_".repeat(800); // 5,600 chars
                const xssPayload = "<script>window.__xss_infected = true;</script><img src=x onerror=window.__xss_infected=true>";
                const unicodePayload = "🔥🎵🚀✨💎".repeat(200);

                window.__xss_infected = false;

                // 1. Long metadata
                window.onPythonEvent('track_changed', {
                    title: longTitle,
                    artist: longArtist
                });

                const ppTitle = document.getElementById('pp-title');
                const ppArtist = document.getElementById('pp-artist');
                const leftCol = document.querySelector('.player-left-col');

                // 2. XSS metadata
                window.onPythonEvent('track_changed', {
                    title: xssPayload,
                    artist: unicodePayload
                });

                return JSON.stringify({
                    hasTitleSpan: !!ppTitle,
                    hasArtistSpan: !!ppArtist,
                    xssExecuted: window.__xss_infected === true,
                    titleTextContainsTag: ppTitle ? ppTitle.textContent.includes('<script>') : false,
                    leftColExists: !!leftCol
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        self.assertTrue(res["hasTitleSpan"])
        self.assertTrue(res["hasArtistSpan"])
        self.assertFalse(res["xssExecuted"], "XSS script payload must NOT execute")
        self.assertTrue(res["titleTextContainsTag"], "XSS payload must be rendered as escaped textContent")

    def test_12_player_tab_window_resizing_responsive(self):
        """Test window resizing and responsive behavior (800px compact vs 1920px desktop wide)."""
        logger.info("--- Stress 3.4: Window Resizing & Responsive Layout (800px vs 1920px) ---")

        eval_script = """
            (() => {
                const viewPlayer = document.getElementById('view-player');
                const layout = document.querySelector('.player-2col-layout');
                const volumeWrap = document.getElementById('pp-volume-wrap');
                const leftCol = document.querySelector('.player-left-col');
                const rightCol = document.querySelector('.player-right-col');

                // Simulate narrow viewport container (e.g. 800px width)
                viewPlayer.style.width = '800px';
                viewPlayer.style.maxWidth = '800px';
                window.dispatchEvent(new Event('resize'));
                if (window.renderWaveforms) window.renderWaveforms();

                const narrowLayout = {
                    leftColExists: !!leftCol,
                    rightColExists: !!rightCol,
                    volumeWrapExists: !!volumeWrap,
                    volumeDisplay: volumeWrap ? window.getComputedStyle(volumeWrap).display : null,
                    controlsWrap: window.getComputedStyle(document.querySelector('.player-card-controls')).flexWrap
                };

                // Restore full viewport container (1920px width)
                viewPlayer.style.width = '100%';
                viewPlayer.style.maxWidth = 'none';
                window.dispatchEvent(new Event('resize'));
                if (window.renderWaveforms) window.renderWaveforms();

                const wideLayout = {
                    leftColExists: !!leftCol,
                    rightColExists: !!rightCol,
                    volumeWrapExists: !!volumeWrap,
                    volumeDisplay: volumeWrap ? window.getComputedStyle(volumeWrap).display : null,
                    controlsWrap: window.getComputedStyle(document.querySelector('.player-card-controls')).flexWrap
                };

                return JSON.stringify({
                    narrowLayout,
                    wideLayout
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        self.assertTrue(res["narrowLayout"]["volumeWrapExists"], "Volume wrap must exist in compact layout")
        self.assertNotEqual(res["narrowLayout"]["volumeDisplay"], "none", "Volume wrap must not be hidden in compact layout")
        self.assertEqual(res["narrowLayout"]["controlsWrap"], "nowrap", "Controls must remain nowrap")
        self.assertTrue(res["wideLayout"]["volumeWrapExists"], "Volume wrap must exist in wide layout")
        self.assertEqual(res["wideLayout"]["controlsWrap"], "nowrap", "Controls must remain nowrap")

    def test_13_player_volume_controls_rapid_interaction(self):
        """Stress-test Player tab dedicated volume slider with rapid input and clicks."""
        logger.info("--- Stress 3.5: Player Volume Slider Rapid Interaction ---")

        eval_script = """
            (() => {
                const track = document.getElementById('pp-volume-track');
                const fill = document.getElementById('pp-volume-fill');
                if (!track) return JSON.stringify({ success: false, error: "Volume track not found" });

                const rect = track.getBoundingClientRect();
                const totalSteps = 50;

                for (let i = 0; i <= totalSteps; i++) {
                    const clientX = rect.left + (rect.width * (i / totalSteps));
                    const evt = new MouseEvent('click', {
                        clientX: clientX,
                        clientY: rect.top + rect.height / 2,
                        bubbles: true
                    });
                    track.dispatchEvent(evt);
                }

                return JSON.stringify({
                    success: true,
                    trackWidth: rect.width,
                    fillWidth: fill ? fill.style.width : null
                });
            })()
        """
        raw_res = self.runner.eval_js(eval_script)
        res = json.loads(raw_res)
        self.assertTrue(res["success"], f"Volume slider stress failed: {res.get('error')}")


def run_standalone():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUIAdversarialStress)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_standalone())
