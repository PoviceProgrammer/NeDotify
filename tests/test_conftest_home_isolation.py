"""Proof that ``redirect_home`` actually isolates the user profile (H-1).

Bug: the fixture keyed only on ``os.sep``. On Windows that is ``"\\"``, so the
forward-slash literal every production call site uses -- ``"~/.nedotify"`` -- was
never intercepted and the suite wrote into / read from the *real* profile of
whatever account ran pytest.

Both spellings must land inside ``tmp_path``:

* ``expanduser("~/.nedotify/x")``      - the hard-coded literal in core/*.py
* ``expanduser("~\\\\.nedotify\\\\x")``  - the Windows-native spelling

Run this file on the pre-fix conftest and ``test_forward_slash_home_is_redirected``
fails with the real profile path in the assertion message.
"""
import os
import shutil
import subprocess

import pytest

REAL_HOME = os.path.expanduser("~")


# --- the fixture under test ------------------------------------------------

def test_bare_tilde_is_redirected(redirect_home, tmp_path):
    assert os.path.realpath(os.path.expanduser("~")) == os.path.realpath(str(tmp_path / "home"))


def test_forward_slash_home_is_redirected(redirect_home, tmp_path):
    """The spelling that used to escape: "~/.nedotify"."""
    got = os.path.expanduser("~/.nedotify")
    real = os.path.join(REAL_HOME, ".nedotify")

    assert os.path.realpath(got).startswith(os.path.realpath(str(tmp_path)))
    assert os.path.realpath(got) != os.path.realpath(real)
    assert os.path.realpath(got) == os.path.realpath(
        os.path.join(str(tmp_path / "home"), ".nedotify"))


def test_backslash_home_is_redirected(redirect_home, tmp_path):
    """The spelling that happened to work before the fix."""
    got = os.path.expanduser("~\\.nedotify")

    assert os.path.realpath(got).startswith(os.path.realpath(str(tmp_path)))
    assert os.path.realpath(got) == os.path.realpath(
        os.path.join(str(tmp_path / "home"), ".nedotify"))


@pytest.mark.parametrize("raw", [
    "~/.nedotify/settings.json",
    "~\\.nedotify\\settings.json",
    "~/.nedotify/streams/youtube_abc.m4a",
    "~/.nedotify/../escape",          # traversal must stay inside after join
])
def test_nested_paths_stay_in_tmp(redirect_home, tmp_path, raw):
    got = os.path.normpath(os.path.expanduser(raw))
    root = os.path.realpath(str(tmp_path))
    assert os.path.realpath(got).startswith(root), (raw, got, root)


def test_result_is_joined_with_the_os_separator(redirect_home):
    got = os.path.expanduser("~/.nedotify/x")
    assert os.sep in got
    assert "/" not in got[len(str(os.path.expanduser("~"))):]


def test_unrelated_paths_are_untouched(redirect_home):
    assert os.path.expanduser("~notauser\\x") == os.path.expanduser("~notauser\\x")
    assert os.path.expanduser("") == ""
    assert os.path.expanduser("relative/path") == "relative/path"


def test_other_home_users_are_delegated(tmp_path, monkeypatch):
    """``~someone`` must keep native semantics, not be glued onto tmp."""
    from tests.conftest import home_expander

    native = os.path.expanduser  # captured before any patch is installed
    patched = home_expander(tmp_path / "home")
    elsewhere = os.path.join(REAL_HOME, "fake-home-user")
    monkeypatch.setenv("USERPROFILE", elsewhere)
    monkeypatch.setenv("HOME", elsewhere)

    got = patched("~fake-home-user/x")
    assert got == native("~fake-home-user/x")
    assert os.path.realpath(got) != os.path.realpath(str(tmp_path / "home"))


def test_restoration_is_automatic(monkeypatch, tmp_path):
    """Sanity: monkeypatch undoes the patch, i.e. no global leakage."""
    from tests.conftest import home_expander

    before = os.path.expanduser("~")
    monkeypatch.setattr(os.path, "expanduser", home_expander(tmp_path / "home2"))
    assert os.path.expanduser("~") != before
    monkeypatch.undo()
    assert os.path.expanduser("~") == before


def test_no_sandbox_path_leaks_into_the_real_profile(redirect_home):
    """Nothing we hand out may be reachable at the real profile location."""
    for raw in ("~/.nedotify", "~\\.nedotify"):
        got = os.path.realpath(os.path.expanduser(raw))
        real = os.path.realpath(os.path.join(REAL_HOME, ".nedotify"))
        assert got != real
        assert not got.lower().startswith(real.lower())


def test_sandbox_dir_is_actually_usable(redirect_home):
    """The redirect must produce a writable, creatable profile tree."""
    target = os.path.expanduser("~/.nedotify/downloads")
    os.makedirs(target, exist_ok=True)
    fp = os.path.join(target, "probe.bin")
    with open(fp, "wb") as f:
        f.write(b"x")
    assert os.path.isfile(fp)
    assert not os.path.exists(os.path.join(REAL_HOME, ".nedotify", "downloads", "probe.bin"))


def test_expander_uses_os_sep_on_posix_semantics(tmp_path):
    """Pure-function view: no fixture, no monkeypatch."""
    from tests.conftest import home_expander

    home = tmp_path / "h"
    home.mkdir()
    patched = home_expander(home)
    assert patched("~") == str(home)
    assert patched("~/a/b") == str(home) + os.sep + os.path.join("a", "b")


# --- repo hygiene: .gitignore really ignores the runtime noise ------------

IGNORED_PATHS = [
    ".venv/bin/python",
    ".venv_win/Scripts/python.exe",
    ".venv_win_backup/pyvenv.cfg",
    ".agents/scratch/note.md",
    ".pytest_cache/v/cache/lastfailed",
    "__pycache__/conftest.cpython-314.pyc",
    "ui/web_new_v2/covers/abc.jpg",
    "ui/web_new/covers/abc.jpg",
]


def _git_check_ignore(path):
    """Return the matching .gitignore rule for *path*, or None when tracked."""
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "-v", "--", path],
            cwd=repo, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        pytest.skip("git check-ignore failed to run: %s" % exc)
    if proc.returncode == 1:
        return None
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.parametrize("path", IGNORED_PATHS)
def test_gitignore_covers_runtime_noise(path):
    rule = _git_check_ignore(path)
    assert rule, "%s is not ignored by .gitignore" % path
    assert rule.split(":", 1)[0], rule


def test_gitignore_does_not_ignore_the_test_suite():
    """Regression guard for the old rule that silently untracked tests/."""
    for path in ("tests/conftest.py", "tests/test_conftest_home_isolation.py"):
        assert _git_check_ignore(path) is None, path