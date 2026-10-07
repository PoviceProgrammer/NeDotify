"""Keybind contract tests.

The keybind table exists twice - as DEFAULT_KEYBINDS in
``ui/web_new_v2/js/hotkeys.js`` and as ``DEFAULT_SETTINGS["hotkeys"]`` in
``core/settings.py`` - and the frontend overwrites its own defaults with
whatever the backend returns at startup, but only for action ids it actually
knows (``KNOWN_ACTIONS`` in hotkeys.js). That makes the two tables a silent
contract:

* an id the backend spells differently (``mute`` vs ``toggle_mute``) is dropped
  on the floor, so the action quietly keeps whatever the frontend default is;
* an id the backend omits entirely is likewise never applied;
* a value in the wrong format (``Ctrl+K`` instead of the ``e.code`` form
  ``Ctrl+KeyK``) never matches anything ``parseKeyEventCombo`` produces.

None of that raises - the key just stops working, or the Settings list shows
raw ``KeyboardEvent.code`` text. So pin the contract here instead.

These tests parse the sources as text; they need neither Node nor the GUI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOTKEYS_JS = REPO_ROOT / "ui" / "web_new_v2" / "js" / "hotkeys.js"
SETTINGS_JS = REPO_ROOT / "ui" / "web_new_v2" / "js" / "settings.js"
SETTINGS_PY = REPO_ROOT / "core" / "settings.py"


def _frontend_keybinds() -> dict[str, str]:
    """{id: defaultKey} parsed out of DEFAULT_KEYBINDS in hotkeys.js."""
    src = HOTKEYS_JS.read_text(encoding="utf-8")
    start = src.index("DEFAULT_KEYBINDS")
    end = src.index("];", start)
    block = src[start:end]
    return dict(
        re.findall(r"\{\s*id:\s*'([^']+)'\s*,\s*label:\s*'[^']*'\s*,\s*defaultKey:\s*'([^']*)'\s*\}", block)
    )


def _backend_keybinds() -> dict[str, str]:
    """{id: combo} from DEFAULT_SETTINGS["hotkeys"] via the real AST."""
    tree = ast.parse(SETTINGS_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "DEFAULT_SETTINGS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "hotkeys" and isinstance(value, ast.Dict):
                out: dict[str, str] = {}
                for k, v in zip(value.keys, value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        out[k.value] = v.value
                return out
    raise AssertionError("DEFAULT_SETTINGS['hotkeys'] not found in core/settings.py")


def test_frontend_table_parses() -> None:
    keybinds = _frontend_keybinds()
    assert len(keybinds) == 10, f"expected 10 frontend keybinds, parsed {len(keybinds)}: {keybinds}"


def test_backend_table_parses() -> None:
    keybinds = _backend_keybinds()
    assert keybinds, "backend hotkeys table is empty"


def test_backend_ids_are_exactly_the_frontend_ids() -> None:
    """The whole point: no renamed and no missing action ids.

    A renamed id is silently discarded by the frontend's KNOWN_ACTIONS filter;
    a missing one means the backend can never restore that binding.
    """
    frontend = _frontend_keybinds()
    backend = _backend_keybinds()

    assert set(backend) == set(frontend), (
        "core/settings.py DEFAULT_SETTINGS['hotkeys'] has drifted from "
        "DEFAULT_KEYBINDS in ui/web_new_v2/js/hotkeys.js.\n"
        f"  only in backend (frontend will ignore these): {sorted(set(backend) - set(frontend))}\n"
        f"  only in frontend (backend can never restore these): {sorted(set(frontend) - set(backend))}"
    )


def test_backend_values_match_frontend_defaults() -> None:
    frontend = _frontend_keybinds()
    backend = _backend_keybinds()
    mismatched = {
        action: (frontend[action], backend[action])
        for action in frontend
        if action in backend and frontend[action] != backend[action]
    }
    assert not mismatched, f"hotkey defaults disagree (frontend, backend): {mismatched}"


def test_no_legacy_mute_action_id() -> None:
    """`mute` was the backend's old name for what the frontend calls `toggle_mute`.

    Pin it so the rename cannot be reintroduced from the other direction.
    """
    assert "mute" not in _backend_keybinds()
    assert "toggle_mute" in _frontend_keybinds()


def _format_key_name() -> callable:
    """Compile the real formatKeyName() out of settings.js with Node."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")

    src = SETTINGS_JS.read_text(encoding="utf-8")
    start = src.index("function formatBaseKeyName(code)")
    end = src.index("function renderKeybindsList")
    body = src[start:end]

    # The extracted source goes in its own module rather than being inlined as
    # a JS string literal: repr()-escaping a block that contains both quote
    # styles and backslashes into JS source is needlessly fragile.
    body_path = Path(__file__).with_name("_fmtkey_body.js")
    body_path.write_text(body + "\nmodule.exports = formatKeyName;\n", encoding="utf-8")
    runner = "console.log(JSON.stringify(process.argv.slice(2).map(c => require('./_fmtkey_body.js')(c))));\n"
    path = Path(__file__).with_name("_fmtkey_runner.js")
    path.write_text(runner, encoding="utf-8")
    try:
        proc = subprocess.run(
            [node, str(path), "Ctrl+ArrowRight", "Ctrl+ArrowLeft", "Ctrl+KeyK", "Space", ""],
            capture_output=True,
            text=True,
            # Node writes UTF-8 regardless of locale; text=True alone would decode
            # with the ANSI codepage (cp1251 on a Russian Windows install) and
            # mangle every Cyrillic label into a different string.
            encoding="utf-8",
            timeout=60,
            cwd=str(REPO_ROOT),
        )
    finally:
        path.unlink(missing_ok=True)
        body_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        pytest.fail(f"formatKeyName runner failed:\n{proc.stderr}")

    import json

    labels = json.loads(proc.stdout.strip())
    return dict(zip(["Ctrl+ArrowRight", "Ctrl+ArrowLeft", "Ctrl+KeyK", "Space", ""], labels))


def test_format_key_name_renders_compound_combos() -> None:
    """A modifier must not defeat translation.

    formatKeyName used to look the whole combo string up in a map of bare
    codes, miss, and return the input verbatim - so `Ctrl+ArrowRight` rendered
    as the literal text "Ctrl+ArrowRight" while plain `ArrowRight` correctly
    rendered as "Стрелка Вправо".
    """
    labels = _format_key_name()
    assert labels["Ctrl+ArrowRight"] == "Ctrl + Стрелка Вправо"
    assert labels["Ctrl+ArrowLeft"] == "Ctrl + Стрелка Влево"
    # unmodified combos must keep working exactly as before
    assert labels["Space"] == "Пробел"
    assert labels[""] == "Не назначено"


def test_format_key_name_never_leaks_raw_codes() -> None:
    labels = _format_key_name()
    leaked = {combo: label for combo, label in labels.items() if "Arrow" in label or "Key" in label}
    assert not leaked, f"raw KeyboardEvent.code leaked into the Settings UI: {leaked}"


def test_no_duplicate_hotkey_dispatcher() -> None:
    """There must be exactly one action-id -> behaviour switch.

    settings.js used to carry a second copy (triggerKeybindAction) that nothing
    called. It had already drifted - it was missing `like` and `search` - and a
    stale second dispatcher is how a rebind silently stops reaching the player.
    """
    dup = re.search(r"function\s+triggerKeybindAction\b", SETTINGS_JS.read_text(encoding="utf-8"))
    assert dup is None, (
        "ui/web_new_v2/js/settings.js defines triggerKeybindAction again. "
        "hotkeys.js:executeHotkeysAction is the only dispatcher; a second copy "
        "will drift."
    )


def test_every_default_keybind_has_a_dispatcher_branch() -> None:
    """Each action id in the table must be handled by the one dispatcher."""
    src = HOTKEYS_JS.read_text(encoding="utf-8")
    start = src.index("export function executeHotkeysAction")
    switch = src[start : src.index("\n}", start)]
    for action in _frontend_keybinds():
        assert f"case '{action}'" in switch, f"executeHotkeysAction has no branch for '{action}'"
