"""Autostart registry handling (Q5) and build/branding invariants.

The autostart tests drive core.api.update_autostart against an in-memory fake
winreg, so the real HKCU\\...\\Run key is never touched.
"""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import types

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _read(path):
    """Read a repo file as UTF-8 (the sources carry Cyrillic)."""
    return open(path, encoding="utf-8").read()

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


def test_linux_autostart_uses_xdg_desktop_entry(autostart_api, fake_winreg, monkeypatch, tmp_path):
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setattr(api_module.sys, "platform", "linux")
    assert autostart_api.update_autostart(True) is True
    desktop = config / "autostart/nedotify.desktop"
    text = desktop.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text and "Name=NeDotify" in text
    assert "Exec=" in text and "main.py" in text
    assert "X-GNOME-Autostart-enabled=true" in text
    assert fake_winreg.values == {}
    assert autostart_api.update_autostart(False) is True
    assert not desktop.exists()


# --- Linux installer identity replaces the Windows registry installer --------


def test_linux_has_native_installer_and_no_windows_setup():
    root = Path(PROJECT_ROOT)
    assert not (root / "installer.iss").exists()
    assert (root / "install_linux.sh").is_file()
    assert (root / "build_linux.sh").is_file()
    desktop = root / "packaging/org.nedotify.NeDotify.desktop"
    text = desktop.read_text(encoding="utf-8")
    assert "Name=NeDotify" in text and "Exec=/opt/nedotify/NeDotify" in text
    assert "Icon=nedotify" in text


# --- the deleted PyInstaller GUI-installer pipeline stays deleted ------------

DEAD_INSTALLER_SCRIPTS = ("build_installer.py", "installer_gui.py", "uninstaller_gui.py")


@pytest.mark.parametrize("name", DEAD_INSTALLER_SCRIPTS)
def test_gui_installer_pipeline_is_deleted(name):
    """installer.iss is the canonical installer.

    The removed scripts emitted three byte-identical setup exes
    (NeDotify_Setup.exe / NeDotify_v2.exe / NeDotify_beta5_Setup.exe) and a
    second uninstaller that competed with Inno Setup's. Their mere presence
    invites a rebuild that resurrects the duplicate artifacts.
    """
    path = os.path.join(PROJECT_ROOT, name)
    assert not os.path.exists(path), (
        f"{name} was deleted because installer.iss is the canonical installer; "
        "it only produced duplicate setup exes and a competing uninstaller"
    )


@pytest.mark.parametrize(
    "doc",
    [
        "README.md",
        "CLAUDE.md",
        "AGENTS.md",
        os.path.join(".claude", "skills", "nedotify-build", "SKILL.md"),
    ],
)
def test_no_doc_points_at_a_deleted_installer_script(doc):
    """A doc that still tells the reader to run build_installer.py is a
    dead link: following it fails with 'not recognized as a cmdlet'.

    Excluded by design: STATUS.md, docs/AUDIT.md and CODING_STANDARDS.md.
    Those name the dead scripts deliberately, as a record of what was removed
    and why. STATUS.md still lists them at one point and corrects itself
    further down; CODING_STANDARDS.md carries the retired-folklore table.
    A doc that reports a deletion is the opposite of the failure this gate
    catches - a substring check cannot tell the two apart, so these stay out
    and are excluded on purpose rather than by accident.
    """
    path = os.path.join(PROJECT_ROOT, doc)
    if not os.path.exists(path):
        pytest.skip(f"{doc} not present")
    text = open(path, encoding="utf-8").read()
    stale = [name for name in DEAD_INSTALLER_SCRIPTS if name in text]
    assert not stale, f"{doc} still references the deleted {stale}"


# --- README must describe the build that actually exists --------------------

README = os.path.join(PROJECT_ROOT, "README.md")


def test_readme_advertises_linux_package_outputs():
    text = _read(README)
    assert "NeDotify-2.5.1-linux-amd64.tar.gz" in text
    assert "nedotify_2.5.1_amd64.deb" in text
    assert "bash build_linux.sh" in text


@pytest.mark.parametrize("stale", ["NeDotify_v2.exe", "beta5_Setup.exe", "Beta5_Setup.exe"])
def test_readme_does_not_advertise_a_duplicate_setup(stale):
    """These names came from the deleted pipeline; three identical exes with
    three names is a support trap."""
    assert stale not in _read(README)


def test_readme_python_floor_matches_linux_runtime():
    """Linux supports the Python 3.12 interpreter shipped by Ubuntu 24.04."""
    readme = _read(README)
    assert "Python 3.12+" in readme, "README must state the supported Linux Python floor"
    assert "Python 3.12+" in _read(os.path.join(PROJECT_ROOT, "requirements.txt"))
    assert "3.10" not in readme, "README still advertises the stale 3.10 floor"


def test_readme_run_command_matches_the_entrypoint():
    """`python main.py` only works because main.py has the __main__ guard."""
    readme = _read(README)
    assert "python main.py" in readme
    main_py = _read(os.path.join(PROJECT_ROOT, "main.py"))
    assert 'if __name__ == "__main__":' in main_py


# --- branding: user-visible strings say NeDotify ----------------------------

BRANDED_FILES = {
    "services/lyrics_service.py": "lrclib User-Agent",
    "services/lastfm_service.py": "Last.fm User-Agent",
    "services/recommendation_service.py": "generated-playlist artist fallback",
    os.path.join("ui", "web_new_v2", "js", "search.js"): "playlist author fallback",
    os.path.join("ui", "web_new_v2", "index.html"): "onboarding / autostart / icon-pack labels",
    # The Discord presence had two different app names in one payload - "AURA
    # Music Player" while playing and "NeDotify Player" while paused - because
    # this file was never listed here. `aura_logo` stays: that is the Discord-side
    # asset key pinned by PERSISTENT_KEYS below, and it is not a user-visible
    # string, so it does not trip this sweep.
    os.path.join("core", "services", "discord_rpc.py"): "Discord Rich Presence large_text",
}


@pytest.mark.parametrize("rel", sorted(BRANDED_FILES))
def test_no_brand_leak_in_user_visible_strings(rel):
    """These strings reach the user: HTTP User-Agent headers, the artist shown
    on generated playlists, onboarding copy, the autostart label."""
    path = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} not present")
    text = _read(path)
    for needle in ("AURA Music", "AURA-Music", "AURA-Music/"):
        assert needle not in text, f"{rel} still says {needle!r} ({BRANDED_FILES[rel]})"


def test_user_agents_are_neutral():
    """lrclib/Last.fm only need a stable identifier; nothing in the repo
    compares the old value, so a neutral one is safe."""
    lyrics = _read(os.path.join(PROJECT_ROOT, "services", "lyrics_lookup.py"))
    assert "headers=headers or {'User-Agent': 'NeDotify/1.0'}" in lyrics
    assert 'https://lrclib.net/api/get?' in lyrics and 'https://lrclib.net/api/search?' in lyrics
    lastfm = _read(os.path.join(PROJECT_ROOT, "services", "lastfm_service.py"))
    assert "'User-Agent': 'NeDotify/1.0 (RecommendationEngine)'" in lastfm


# --- branding control: persistent identifiers must NOT have been renamed ------

PERSISTENT_KEYS = [
    # (relpath, needle, why renaming is destructive)
    (os.path.join("ui", "web_new_v2", "js", "settings.js"), "aura_orbs_enabled",
     "settings key stored in the DB; renaming resets the user's toggle"),
    (os.path.join("ui", "web_new_v2", "js", "onboarding.js"), "aura_onboarding_done",
     "localStorage flag; renaming re-runs onboarding for everyone"),
    (os.path.join("ui", "web_new_v2", "index.html"), 'data-id="aura_neon"',
     "icon-pack id; renaming orphans the saved selection and its artwork"),
    (os.path.join("ui", "web_new_v2", "js", "settings.js"), "aura_neon",
     "PACK_ICON_MAPS key for the icon pack"),
    (os.path.join("core", "services", "discord_rpc.py"), "aura_logo",
     "Discord-side asset key; renaming blanks the presence image"),
    ("core/plugins.py", "aura_plugins", "importlib namespace for plugins"),
    ("main.py", "/__aura_close", "route called from main.js on both sides"),
    ("services/base_service.py", "aura-shared", "thread_name_prefix"),
    ("utils/tag_parser.py", "aura_tag_backup_", "tag backup file prefix"),
]


@pytest.mark.parametrize("rel,needle,why", PERSISTENT_KEYS, ids=[p[1] for p in PERSISTENT_KEYS])
def test_persistent_aura_identifiers_are_untouched(rel, needle, why):
    """Positive control for the brand sweep above: the sweep only targets
    strings the user reads. Anything persisted or cross-process must keep its
    name, otherwise this test is a false-negative generator."""
    path = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} not present")
    assert needle in _read(path), f"{needle!r} must stay in {rel}: {why}"


def test_onboarding_legacy_localstorage_key_is_migrated_to_backend():
    """Legacy completion is consumed, then removed after the canonical save.

    Runtime migration and failed-save behavior are exercised in
    test_onboarding_ui; rebuilding a second persistent flag would recreate
    the split source of truth from the audit.
    """
    path = os.path.join(PROJECT_ROOT, "ui", "web_new_v2", "js", "onboarding.js")
    if not os.path.exists(path):
        pytest.skip("onboarding.js not present")
    text = _read(path)
    assert "localStorage.getItem('aura_onboarding_done')" in text, "read side lost the key"
    assert 'removeItem(key)' in text
    assert "localStorage.setItem('aura_onboarding_done', 'true')" not in text


# --- syntax gate for the edited .js (skipped when node is unavailable) ------

EDITED_JS = [
    os.path.join("ui", "web_new_v2", "js", "search.js"),
]


@pytest.mark.parametrize("rel", EDITED_JS)
def test_edited_js_parses(rel):
    """The brand sweep rewrote JS string literals inside template
    expressions; a stray quote would only show up in the browser."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    path = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} not present")
    result = subprocess.run(
        [node, "--check", path], capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"node --check failed for {rel}: {result.stderr}"


# --- PyInstaller spec: covers cache must be stripped from BOTH UI copies -----

SPEC = os.path.join(PROJECT_ROOT, "setup_pyinstaller.spec")


def test_spec_strips_both_covers_caches():
    """web_new_v2 is the active UI; a filter matching the literal
    'web_new/covers/' does not match 'web_new_v2/covers/', so the runtime art
    cache of the active UI used to ship inside the exe.

    The predicate is loaded out of the spec and exercised directly, so this
    asserts the real behaviour rather than the spelling of the source.
    """
    support = runpy.run_path(str(Path(PROJECT_ROOT) / "packaging/linux_support.py"))
    data = support["collect_ui_datas"](Path(PROJECT_ROOT))
    published = {(Path(destination) / Path(source).name).as_posix() for source, destination in data}
    assert "ui/web_new_v2/index.html" in published
    assert "ui/web_new_v2/js/player.js" in published
    assert any(path.startswith("ui/MACos_ui/") for path in published)
    assert not any("covers" in Path(path).parts for path in published)


# --- tray icon must point at the active UI ----------------------------------

def test_tray_icon_uses_active_ui():
    text = open(os.path.join(PROJECT_ROOT, "core", "tray.py"), encoding="utf-8").read()
    assert "web_new_v2" in text, "tray still loads its icon from the legacy web_new UI"
