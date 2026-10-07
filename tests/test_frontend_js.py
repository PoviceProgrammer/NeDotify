"""Static source-level checks for the ui/web_new_v2 frontend.

The Windows frontend is Vanilla-JS ES modules running inside pywebview/WebView2 and
has **no runtime test harness** in this repository. Everything below is therefore a
*static* assertion on the shipped source text (plus a real `node --check` parse when
a Node binary is available). These tests prove the intended wiring is present in the
files; they do NOT prove the UI behaves correctly at runtime. Do not mistake a green
run here for a functional smoke test of the webview.

Covered audit items:
  P0-4  backend `api_error` bridge event must have a real handler in events.js
  P1-8  window.onPythonEvent must go through an order-independent subscriber registry
  P2-14 switch case bodies that declare bindings must be block-scoped
  H-4   artist_profile.js must be backend-driven and free of mock data
"""

import os
import re
import shutil
import subprocess
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROJECT_ROOT, "ui", "web_new_v2", "js")
CORE_API = os.path.join(PROJECT_ROOT, "core", "api.py")

EVENTS_JS = os.path.join(JS_DIR, "events.js")
MAIN_JS = os.path.join(JS_DIR, "main.js")
ARTIST_JS = os.path.join(JS_DIR, "artist_profile.js")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def events_src():
    return read(EVENTS_JS)


@pytest.fixture(scope="module")
def main_src():
    return read(MAIN_JS)


@pytest.fixture(scope="module")
def artist_src():
    return read(ARTIST_JS)


# --------------------------------------------------------------------------
# Syntax: the frontend has no runtime tests, so at least parse it for real.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename",
    ["events.js", "main.js", "artist_profile.js", "utils.js", "boot.js"],
)
def test_js_files_parse_as_es_modules(filename):
    """node --check on a .mjs copy: a syntax error breaks the whole webview."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; syntax check skipped")
    src = os.path.join(JS_DIR, filename)
    with tempfile.TemporaryDirectory() as tmp:
        # ES modules need the .mjs extension for node's parser.
        copy = os.path.join(tmp, filename.replace(".js", ".mjs"))
        shutil.copyfile(src, copy)
        proc = subprocess.run(
            [node, "--check", copy],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert proc.returncode == 0, f"{filename} failed node --check:\n{proc.stderr}"


# --------------------------------------------------------------------------
# P0-4: the backend pushes `api_error`; the UI must surface it.
# --------------------------------------------------------------------------

def test_backend_emits_api_error_with_method_and_error():
    """Guards the payload contract the JS handler is written against."""
    src = read(CORE_API)
    assert '_emit("api_error"' in src
    assert '"method": method_name' in src
    assert '"error": f"{type(exc).__name__}: {exc}"' in src


def test_events_js_handles_api_error(events_src):
    assert "case 'api_error':" in events_src, (
        "events.js has no api_error case: the event falls into default: and the "
        "user only sees 'button does nothing' again"
    )


def test_api_error_case_shows_toast_and_logs(events_src):
    """The case body must surface the failure, not just console.log it."""
    match = re.search(r"case 'api_error':\s*\{(.*?)\n\s*\}", events_src, re.S)
    assert match, "api_error case body is not block-scoped / not found"
    body = match.group(1)
    assert "showToast(" in body, "api_error must raise a visible toast"
    assert "console.error(" in body, "api_error must be logged for diagnostics"
    assert ".method" in body, "api_error handler must read data.method"
    assert ".error" in body, "api_error handler must read data.error"


def test_api_error_is_not_a_silent_default(events_src):
    """`api_error` must appear exactly once, as a real case label."""
    assert events_src.count("case 'api_error':") == 1


# --------------------------------------------------------------------------
# P1-8: order-independent bridge-event registry.
# --------------------------------------------------------------------------

def test_events_js_exports_subscriber_registry(events_src):
    assert "export function addPythonEventHandler(" in events_src


def test_events_js_installs_dispatcher_outside_init(events_src):
    """The dispatcher must be installed at module evaluation, not only by initEvents().

    Installing it inside initEvents() is what made the old decorators
    order-dependent, so the assignment has to exist in module top-level scope.
    """
    assert re.search(r"^window\.onPythonEvent = dispatchPythonEvent;$",
                     events_src, re.M), (
        "window.onPythonEvent must be bound to the stable dispatcher at module level"
    )
    # initEvents() must re-install it too, so a late clobber cannot strand subscribers.
    assert re.search(r"function initEvents\(\)\s*\{\s*window\.onPythonEvent = dispatchPythonEvent;",
                     events_src), "initEvents() must re-install the dispatcher"


def test_events_js_dispatcher_survives_subscriber_errors(events_src):
    """One throwing subscriber must not stop the others."""
    assert "Python event subscriber failed" in events_src


def test_subscribers_run_even_before_or_without_init_events(events_src):
    """P1-8(b): registration order must not change the outcome.

    The subscriber loop must sit at the top level of dispatchPythonEvent, outside
    the `if (coreEventHandler)` guard, so a listener registered before (or without)
    initEvents() still gets called.
    """
    loop = [ln for ln in events_src.splitlines()
            if "pythonEventHandlers.slice()" in ln]
    assert len(loop) == 1, "dispatcher must iterate the subscriber list exactly once"
    indent = len(loop[0]) - len(loop[0].lstrip())
    assert indent == 4, (
        f"subscriber loop is nested (indent {indent}); a listener registered before "
        "initEvents() would be skipped"
    )
    guard = [ln for ln in events_src.splitlines() if "if (coreEventHandler)" in ln]
    assert len(guard) == 1
    guard_indent = len(guard[0]) - len(guard[0].lstrip())
    assert guard_indent == 4


def test_only_events_js_assigns_on_python_event():
    """No module may bypass the registry (P1-8a: no stray assignments)."""
    offenders = []
    for name in sorted(os.listdir(JS_DIR)):
        if not name.endswith(".js") or name in ("hls.min.js", "lucide.min.js"):
            continue
        # events.js owns the registry; everywhere else must use addPythonEventHandler.
        if name == "events.js":
            continue
        src = read(os.path.join(JS_DIR, name))
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if re.search(r"window\.onPythonEvent\s*=", stripped):
                offenders.append(f"{name}: {stripped}")
    assert not offenders, "window.onPythonEvent assigned outside the registry:\n" + "\n".join(offenders)


def test_registry_owner_always_binds_the_same_dispatcher(events_src):
    """Both assignment sites in events.js must target the one stable function, so a
    re-install can never strand the subscribers list."""
    assignments = re.findall(r"window\.onPythonEvent\s*=\s*(\w+)\s*;", events_src)
    assert assignments, "events.js never binds window.onPythonEvent"
    assert set(assignments) == {"dispatchPythonEvent"}, (
        f"unexpected dispatcher bound: {sorted(set(assignments))}"
    )
    assert assignments.count("dispatchPythonEvent") >= 2, (
        "initEvents() must re-install the dispatcher as well as module evaluation"
    )


def test_main_js_does_not_decorate_on_python_event(main_src):
    assert not re.search(r"window\.onPythonEvent\s*=", main_src), (
        "main.js must not wrap window.onPythonEvent; use addPythonEventHandler()"
    )
    assert "addPythonEventHandler" in main_src
    assert re.search(r"import\s*\{[^}]*\binitEvents\b[^}]*\baddPythonEventHandler\b[^}]*\}\s*from\s*'\./events\.js'",
                     main_src), "main.js must import addPythonEventHandler from ./events.js"


def test_main_js_still_initialises_events(main_src):
    """P1-8c: the existing initEvents() call must survive the refactor."""
    assert "initEvents()" in main_src


def test_events_js_still_exports_init_events(events_src):
    assert "export function initEvents()" in events_src


def test_main_js_registers_both_original_subscribers(main_src):
    """Lyrics track sync + network banner + greeting must all be subscribed."""
    assert main_src.count("addPythonEventHandler(") >= 2
    for marker in ("_lyricsTrackSync(eventName, data)",
                   "_handleNetworkEvent(eventName, data)",
                   "updateGreeting()"):
        assert marker in main_src, f"lost subscriber body: {marker}"


# --------------------------------------------------------------------------
# P2-14: declaration-bearing switch cases must be block-scoped.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "case_label",
    [
        "'state_changed'",
        "'position_changed'",
        "'authentic_home_error'",
        "'error'",
        "'audio_error'",
        "'api_error'",
    ],
)
def test_declaring_case_bodies_are_braced(events_src, case_label):
    assert re.search(r"case\s+" + re.escape(case_label) + r":\s*\{", events_src), (
        f"case {case_label} declares bindings but its body is not wrapped in {{ }}"
    )


def test_no_unbraced_case_body_declares_bindings(events_src):
    """Generic guard: any `case 'x':` whose next non-blank line declares a binding
    without an opening brace is a latent SyntaxError once the name is duplicated."""
    offenders = []
    lines = events_src.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"\s*case\s+'[^']+':\s*$", line)
        if not m:
            continue
        for follow in lines[idx + 1:]:
            if not follow.strip():
                continue
            if re.match(r"\s*(const|let|var)\s+", follow):
                offenders.append(f"line {idx + 1}: {line.strip()} -> {follow.strip()}")
            break
    assert not offenders, "unbraced case bodies with declarations:\n" + "\n".join(offenders)


# --------------------------------------------------------------------------
# H-4: artist_profile.js must be driven by the real backend, no mock data.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "marker",
    [
        "MOCK_ARTISTS",
        "STATIC_TRACKS_",
        "mapStaticTracks",
        "mockBadge",
        "isMock",
        "MOCK (DEV)",
        "TODO: Replace this mock data",
    ],
)
def test_artist_profile_has_no_mock_markers(artist_src, marker):
    assert marker not in artist_src, f"mock marker still present in artist_profile.js: {marker}"


def test_artist_profile_uses_the_real_bridge(artist_src):
    """Primary data path must be core/api.py::get_artist_profile."""
    assert "window.pywebview.api.get_artist_profile(" in artist_src
    assert "fetchArtistProfileFromBridge" in artist_src


def test_artist_profile_subscribes_to_profile_events(artist_src):
    for event in ("nedotify:artist_profile_ready",
                  "nedotify:artist_profile_error"):
        assert event in artist_src


def test_events_js_still_bridges_profile_events(events_src):
    """H-4: the producer side of the contract must stay intact."""
    for event in ("artist_profile_ready", "artist_profile_error"):
        assert f"case '{event}':" in events_src
    assert "window.dispatchEvent(new CustomEvent('app:artist_profile_ready'" in events_src


def test_artist_profile_avatar_comes_from_backend(artist_src):
    """No more name->hardcoded-thumbnail mapping; avatars come from the bridge."""
    assert "window.pywebview.api.get_artists_avatars(" in artist_src
    assert "'app:artists_avatars_ready'" in artist_src
    # The old heuristic hardcoded one artist's thumbnail as the universal default.
    assert "artistData.avatarUrl || 'https://" not in artist_src


def test_backend_get_artists_avatars_exists():
    src = read(CORE_API)
    assert "def get_artists_avatars(" in src
    assert '_emit("artists_avatars_ready"' in src


def test_backend_get_artist_profile_exists():
    src = read(CORE_API)
    assert "def get_artist_profile(" in src