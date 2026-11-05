"""Repo hygiene: .gitignore must keep generated/local trees out of version control.

These are the paths that actually bit this project:

* `.venv*/` - the rule was once only `.venv/`, so the two Windows copies
  (`.venv_win`, `.venv_win_backup`) showed up as untracked noise.
* `.agents/` - ~700 markdown drafts from earlier agent runs; untracked by
  `ab207a7` but still sitting in the working tree.
* `tests/` - was listed in .gitignore, which silently kept the entire pytest
  suite out of every fresh clone. Its absence must stay that way.
* `ui/web_new*/covers/` - runtime album-art cache; `web_new/covers/` is NOT a
  substring of `web_new_v2/covers/`, which is why both are listed separately.

Every assertion goes through ``git check-ignore --no-index -v`` so it tests the
real rule table rather than a regex re-implementation of it. ``--no-index`` makes
git evaluate the rules even when the path does not exist on disk.

Skips (not fails) when git is unavailable: this assertion is about the
repository, and a machine without git legitimately cannot answer it.
"""

import os
import shutil
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*args):
    """Run git, raising AssertionError with output when it misbehaves."""
    proc = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc


requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed on this machine"
)


def _check_ignore(path):
    """True when git's rule table ignores *path*.

    ``check-ignore --no-index`` exits 0 both for a real match **and** for a
    ``!`` negation rule - rc=0 means "a rule matched", not "the path is
    ignored". ``setup_pyinstaller.spec`` is the live example: it is caught by
    ``*.spec`` and then re-included by ``!setup_pyinstaller.spec``, and
    check-ignore still reports rc=0 while printing the negated pattern. So the
    pattern from the ``-v`` output decides the answer, not the exit code.
    """
    proc = _git("check-ignore", "--no-index", "-v", "--", path)
    # 0 = a rule matched, 1 = no rule matched, anything else = real error.
    assert proc.returncode in (0, 1), (
        f"git check-ignore failed for {path!r} (rc={proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    if proc.returncode == 1:
        return False
    # -v prints "<source>:<linenum>:<pattern>\t<pathname>".
    rule = proc.stdout.split("\t", 1)[0].rsplit(":", 1)[-1].strip()
    return not rule.startswith("!")


# (path, why it must stay ignored)
MUST_BE_IGNORED = [
    (".venv_win_backup/somefile", "stale Windows venv backup"),
    (".agents/x.md", "agent draft notes"),
    (".pytest_cache/x", "pytest runtime cache"),
    ("__pycache__/x.pyc", "compiled bytecode"),
    ("ui/web_new/covers/a.jpg", "legacy UI album-art cache"),
    ("ui/web_new_v2/covers/b.jpg", "active UI album-art cache"),
    # Extra coverage for the variants that actually existed on disk.
    (".venv/lib/x", "POSIX-style venv"),
    (".venv_win/Scripts/python.exe", "the interpreter this suite runs under"),
]


@pytest.mark.parametrize("path,why", MUST_BE_IGNORED, ids=[p for p, _ in MUST_BE_IGNORED])
@requires_git
def test_generated_trees_are_ignored(path, why):
    assert _check_ignore(path), (
        f"{path!r} ({why}) is NOT ignored. Add it to .gitignore - as it is "
        "it will pollute `git status` on every machine."
    )


@requires_git
def test_the_test_suite_is_tracked():
    """The regression suite must survive a fresh clone.

    This is the exact regression that hid the whole suite: `tests/` used to be
    listed in .gitignore, so `pytest -q` after a clone collected nothing.
    """
    assert not _check_ignore("tests/test_repo_hygiene.py"), (
        "tests/ is ignored again - the pytest suite would not survive a clone"
    )


@requires_git
def test_project_docs_are_tracked():
    """STATUS.md / AUDIT.md / AGENTS.md are deliverables, not artifacts."""
    for path in ("STATUS.md", "docs/AUDIT.md", "AGENTS.md", "docs/history/PROJECT.md"):
        assert not _check_ignore(path), f"{path!r} is ignored but must be versioned"


@requires_git
def test_the_project_build_spec_stays_tracked():
    """`*.spec` is ignored, with one negation: the project's own build spec.

    Without the `!setup_pyinstaller.spec` negation the release could not be
    rebuilt from a clone.
    """
    assert _check_ignore("some_other_generator.spec"), (
        "generated *.spec files should be ignored"
    )
    assert not _check_ignore("setup_pyinstaller.spec"), (
        "setup_pyinstaller.spec is ignored - releases cannot be rebuilt"
    )


@requires_git
def test_secrets_and_env_are_ignored():
    """Secrets section of .gitignore must keep working."""
    assert _check_ignore(".env")
