"""Linux atmosphere compatibility after moving from particles to one renderer."""

from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "ui" / "web_new_v2"


def test_particles_compatibility_uses_current_atmosphere_lifecycle():
    facade = (UI / "js/particles.js").read_text(encoding="utf-8")
    assert "initParticles = initAtmosphere" in facade
    assert "stopParticles = stopAtmosphere" in facade
    assert "setParticlesFps = setAtmosphereFps" in facade
    assert "requestAnimationFrame" not in facade


def test_linux_atmosphere_is_visible_above_opaque_panels_without_intercepting_input():
    css = (UI / "css/components/base.css").read_text(encoding="utf-8")
    rules = re.search(r"#particles-bg\s*\{([^}]+)\}", css).group(1)
    assert "inset: 0" in rules
    assert "pointer-events: none" in rules
    assert "z-index: 20" in rules
    assert "filter: none" in rules


def test_atmosphere_no_longer_depends_on_windows_emoji_fonts():
    engine = (UI / "js/atmosphere-engine.js").read_text(encoding="utf-8")
    effects = (UI / "js/atmosphere-effects.js").read_text(encoding="utf-8")
    assert "Segoe UI Emoji" not in engine + effects
    assert "getContext('2d'" in engine
    assert "visibilitychange" in engine
    assert "prefers-reduced-motion" in engine
