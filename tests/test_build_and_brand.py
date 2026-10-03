"""Autostart registry handling (Q5) and build/branding invariants.

The autostart tests drive core.api.update_autostart against an in-memory fake
winreg, so the real HKCU\\...\\Run key is never touched.
"""
import os
import sys
import types

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import api as api_module  # noqa: E402


class FakeWinreg(types.ModuleType):
    """Minimal winreg stand-in backed by a dict of {value_name: data}."""

    ERROR = OSError

    def __init__(self, initial=None):
        super().__init__("winreg")
        self.HKEY_CURRENT_USER = "HKCU"
        self.HKEY_LOCAL_MACHINE = "HKLM"
        self.REG_SZ = 1
        self.KEY_SET_VALUE = 2
        self.values = dict(initial or {})
        self.opened = []

    def OpenKey(self, hive, path, access=0, flags=0):
        self.opened.append((hive, path))
        return object()

    def SetValueEx(self, key, name, reserved, vtype, data):
        self.values[name] = data

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]

    def CloseKey(self, key):
        return None


@pytest.fixture
def fake_winreg(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(api_module.sys, "platform", "win32")
    return fake


@pytest.fixture
def autostart_api(tmp_db, settings_stub, monkeypatch):
    core = types.SimpleNamespace(
        db=tmp_db,
        settings=settings_stub,
    )
    return api_module.AppApi(core)


def test_enable_writes_the_run_value_and_keeps_it(autostart_api, fake_winreg):
    """Regression: the enable path must not delete the value it just wrote.

    A previous revision ran the cleanup loop unconditionally, so enabling
    autostart wrote "NeDotify" and deleted it again in the next statement -
    autostart silently never worked.
    """
    assert autostart_api.update_autostart(True) is True
    assert fake_winreg.values.get(api_module.AUTOSTART_RUN_VALUE), (
        "autostart was enabled but the Run value is missing"
    )


def test_enable_removes_legacy_entry(autostart_api, fake_winreg):
    """Users who enabled autostart before the rename keep a stale "AURA Music"
    entry; leaving it produces a second launch at logon."""
    fake_winreg.values["AURA Music"] = r'"C:\old\AURA Music.exe"'

    autostart_api.update_autostart(True)

    assert "AURA Music" not in fake_winreg.values
    assert api_module.AUTOSTART_RUN_VALUE in fake_winreg.values


def test_disable_removes_current_and_legacy(autostart_api, fake_winreg):
    fake_winreg.values[api_module.AUTOSTART_RUN_VALUE] = r'"C:\NeDotify.exe"'
    fake_winreg.values["AURA Music"] = r'"C:\old\AURA Music.exe"'

    assert autostart_api.update_autostart(False) is True

    assert fake_winreg.values == {}, "disable must clear every autostart entry"


def test_autostart_uses_hkcu_and_the_documented_key(autostart_api, fake_winreg):
    autostart_api.update_autostart(True)
    hive, path = fake_winreg.opened[-1]
    assert hive == fake_winreg.HKEY_CURRENT_USER
    assert path == api_module.AUTOSTART_RUN_KEY
    assert r"Run" in path


def test_non_windows_is_a_noop(autostart_api, fake_winreg, monkeypatch):
    monkeypatch.setattr(api_module.sys, "platform", "linux")
    assert autostart_api.update_autostart(True) is False
    assert fake_winreg.values == {}


# --- installer.iss / api.py must agree on the Run value name ----------------

ISS = os.path.join(PROJECT_ROOT, "installer.iss")


def test_installer_writes_the_same_run_value_name():
    if not os.path.exists(ISS):
        pytest.skip("installer.iss not present")
    text = open(ISS, encoding="utf-8").read()

    assert f'ValueName: "{api_module.AUTOSTART_RUN_VALUE}"' in text, (
        "installer.iss and core/api.py disagree on the Run value name; the app "
        "would write one entry and the installer another"
    )
    assert "Root: HKCU;" in text, "installer must use the same hive as the app"


def test_installer_does_not_emit_legacy_run_name():
    if not os.path.exists(ISS):
        pytest.skip("installer.iss not present")
    text = open(ISS, encoding="utf-8").read()
    run_section = text.split("[Registry]", 1)[-1].split("[", 1)[0]
    assert "AURA Music" not in run_section


def test_installer_output_name_matches_readme():
    if not os.path.exists(ISS):
        pytest.skip("installer.iss not present")
    text = open(ISS, encoding="utf-8").read()
    assert "OutputBaseFilename=NeDotify_Setup" in text


# --- PyInstaller spec: covers cache must be stripped from BOTH UI copies -----

SPEC = os.path.join(PROJECT_ROOT, "setup_pyinstaller.spec")


def test_spec_strips_both_covers_caches():
    """web_new_v2 is the active UI; a filter matching the literal
    'web_new/covers/' does not match 'web_new_v2/covers/', so the runtime art
    cache of the active UI used to ship inside the exe.

    The predicate is loaded out of the spec and exercised directly, so this
    asserts the real behaviour rather than the spelling of the source.
    """
    if not os.path.exists(SPEC):
        pytest.skip("setup_pyinstaller.spec not present")
    predicate = _load_spec_cover_predicate()

    must_strip = (
        "ui/web_new/covers/a.png",
        "ui/web_new_v2/covers/b.png",
        "ui\\web_new_v2\\covers\\c.jpg",
    )
    must_keep = (
        "ui/web_new/js/player.js",
        "ui/web_new_v2/index.html",
        "covers/loose.png",
        "ui/web_new_assets/keep.png",
    )
    for sample in must_strip:
        assert predicate(sample), f"{sample} would ship in the exe"
    for sample in must_keep:
        assert not predicate(sample), f"{sample} would be wrongly stripped"


def _load_spec_cover_predicate():
    """Execute the spec's filter helper without running the whole build."""
    source = open(SPEC, encoding="utf-8").read()
    start = source.index("def _is_ui_cover_cache")
    end = source.index("\n\n", source.index("return '/ui/' in norm"))
    namespace = {}
    exec(source[start:end], namespace)
    return namespace["_is_ui_cover_cache"]


# --- tray icon must point at the active UI ----------------------------------

def test_tray_icon_uses_active_ui():
    text = open(os.path.join(PROJECT_ROOT, "core", "tray.py"), encoding="utf-8").read()
    assert "web_new_v2" in text, "tray still loads its icon from the legacy web_new UI"