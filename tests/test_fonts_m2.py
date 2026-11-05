"""Linux typography regressions against the current shared desktop interface."""

from pathlib import Path
import re

from core.settings import DEFAULT_SETTINGS
from tests.jsdom import run_node, source

UI = Path(__file__).resolve().parents[1] / "ui" / "web_new_v2"


def test_default_fonts_work_offline_with_cyrillic():
    html = (UI / "index.html").read_text(encoding="utf-8")
    css = (UI / "css/fonts.css").read_text(encoding="utf-8")
    assert 'href="css/fonts.css' in html
    assert "font-family: 'NeDotify Cyrillic'" in css
    fonts = re.findall(r"url\(['\"]?([^)'\"]+)", css)
    assert fonts
    assert all((UI / "css" / url).is_file() for url in fonts)
    assert DEFAULT_SETTINGS["theme"]["font_family"] in {"system", "default"}


def test_both_appearances_have_native_linux_font_fallbacks():
    tokens = (UI / "css/tokens.css").read_text(encoding="utf-8")
    mac_tokens = (UI.parent / "MACos_ui/tokens.css").read_text(encoding="utf-8")
    appearance = (UI / "js/ui-style.js").read_text(encoding="utf-8")
    for text in (tokens, mac_tokens, appearance):
        assert "Cantarell" in text
        assert "Ubuntu" in text


def test_optional_picker_fonts_load_from_local_assets_under_same_origin_csp():
    css = (UI / "assets/fonts/picker/fontfaces.css").read_text(encoding="utf-8")
    boot = (UI / "js/boot.js").read_text(encoding="utf-8")
    for family in ("Inter", "Outfit", "Roboto", "Montserrat", "Plus Jakarta Sans"):
        assert f"font-family: '{family}'" in css
    assert "PICKER_FONT_HREF = 'assets/fonts/picker/fontfaces.css'" in boot
    assert "https://fonts.googleapis.com" not in boot
    fonts = re.findall(r"url\(['\"]?([^)'\"]+)", css)
    assert len(fonts) >= 5
    assert all((UI / "assets/fonts/picker" / url).is_file() for url in fonts)
    assert len(list((UI / "assets/fonts/picker").glob("OFL-*.txt"))) == 5


def test_linux_font_selection_migrates_legacy_values_and_keeps_appearances_independent():
    run_node(rf"""
        import assert from 'node:assert/strict';
        const source = {source('settings.js')};
        const fontList = source.match(/export const FONTS_LIST = (\[[\s\S]*?\n\]);/)[1];
        const helpers = source.slice(source.indexOf('const normalizeFont ='), source.indexOf('function renderThemePresets()'));
        const values = new Map(); const saved = [];
        globalThis.document = {{documentElement: {{dataset: {{uiStyle:'current'}}, style: {{setProperty:(key,value)=>values.set(key,value)}}}}, getElementById:()=>null}};
        const saveSetting = (...args) => saved.push(args);
        const {{applyFontFamily,FONTS_LIST,activeFontFamilies}} = new Function('saveSetting',
            `const FONTS_LIST = ${{fontList}}; ${{helpers.replaceAll('export ', '')}}; return {{applyFontFamily,FONTS_LIST,activeFontFamilies}};`)(saveSetting);
        for (const id of ['ubuntu','cantarell','liberation','noto']) assert.ok(FONTS_LIST.some(font=>font.id===id));
        applyFontFamily('default', 'default', false);
        assert.match(values.get('--font-family'), /DM Sans/);
        assert.match(values.get('--font-family'), /NeDotify Cyrillic/);
        const ubuntu = FONTS_LIST.find(font=>font.id==='ubuntu');
        applyFontFamily(ubuntu.family, 'default', false);
        for (const name of ['--font-family','--font-body','--font-display']) assert.equal(values.get(name),ubuntu.family);
        document.documentElement.dataset.uiStyle='macos';
        applyFontFamily('cantarell');
        assert.equal(saved.at(-1)[0],'macos_font_family'); assert.equal(saved.at(-1)[2],'interface');
        assert.equal(activeFontFamilies.current,ubuntu.family);
        assert.match(activeFontFamilies.macos,/Cantarell/);
        document.documentElement.dataset.uiStyle='current';
        applyFontFamily('system');
        assert.deepEqual(saved.at(-1),['font_family','system','theme']);
    """)
