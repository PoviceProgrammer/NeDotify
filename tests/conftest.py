"""Shared fixtures for the AURA Music Windows test-suite.

All tests are hermetic: a throwaway SQLite file per test, stub services
instead of network providers, and ``~`` redirected for download paths.
Nothing here touches the real ``~/.nedotify`` tree or the network.
"""

import os
import sys
import types

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.api import AppApi
from core.database import DatabaseManager
from core.downloader import DownloadManager


class SettingsStub:
    """Minimal dict-backed stand-in for SettingsManager."""

    def __init__(self):
        self._d = {}

    def get(self, category, key, default=None):
        return self._d.get((category, key), default)

    def set(self, category, key, value):
        self._d[(category, key)] = value

    def get_category(self, category):
        return {k: v for (c, k), v in self._d.items() if c == category}


class ServiceStub:
    """Fake audio provider: writes a small local file instead of downloading."""

    def __init__(self):
        self.calls = []
        self.fail = False
        self.n = 0

    def download_audio_sync(self, source_id, download_dir):
        self.calls.append((source_id, download_dir))
        if self.fail:
            raise RuntimeError("stub provider failure")
        self.n += 1
        os.makedirs(download_dir, exist_ok=True)
        fp = os.path.join(download_dir, "stub_%d.mp3" % self.n)
        with open(fp, "wb") as f:
            f.write(b"ID3\x00\x01stub-audio")
        return fp


@pytest.fixture
def tmp_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    yield db
    try:
        db.close()
    except Exception:
        pass


@pytest.fixture
def settings_stub():
    return SettingsStub()


@pytest.fixture
def youtube_stub():
    return ServiceStub()


@pytest.fixture
def core_ns(tmp_db, settings_stub, youtube_stub):
    """Fake AppCore namespace: real DB + stub settings/services."""
    ns = types.SimpleNamespace(
        db=tmp_db,
        settings=settings_stub,
        youtube=youtube_stub,
        soundcloud=youtube_stub,
        cache=None,
    )
    return ns


@pytest.fixture
def api(core_ns):
    app_api = AppApi(core_ns)
    return app_api


@pytest.fixture
def emitted(api, monkeypatch):
    """Capture bridge events emitted via api._emit."""
    events = []

    def _capture(event_name, data=None):
        events.append((event_name, data))

    monkeypatch.setattr(api, "_emit", _capture)
    return events


@pytest.fixture
def downloader(core_ns):
    """Real DownloadManager with its background processor halted.

    Workers are driven synchronously via ``_download_worker`` in tests,
    so there is no race with the processor thread.
    """
    dm = DownloadManager(core_ns)
    dm._running = False
    dm._queue_event.set()
    yield dm
    try:
        dm.stop()
    except Exception:
        pass


# Home-path spellings that must be redirected. ``os.sep`` alone was not enough:
# every production call site spells the profile as the literal "~/.nedotify"
# (forward slash, hard-coded in core/*.py and services/*.py), while native
# Windows callers use "~\\...". Keying only on os.sep == "\\" therefore let
# "~/.nedotify" escape the sandbox and hit the real user profile.
_HOME_SEP_CHARS = tuple(c for c in {"/", os.sep, os.altsep} if c)
# The separator that is NOT native to this OS; only rewritten when it exists.
_FOREIGN_SEP = "/" if os.sep != "/" else None


def home_expander(home):
    """Build a drop-in ``os.path.expanduser`` that maps ``~`` onto *home*.

    Accepts ``~``, ``~/x``, ``~\\x`` and mixed forms; returns a path joined with
    the OS-native separator. Anything else (``~user``, relative paths, non-str)
    is delegated to the original implementation.
    """
    orig = os.path.expanduser
    base = str(home)

    def _patched(path):
        if not isinstance(path, str) or not path.startswith("~"):
            return orig(path)
        rest = path[1:]
        if rest and rest[0] not in _HOME_SEP_CHARS:
            # "~someone-else" is a real home on POSIX; leave it to nt/posixpath.
            return orig(path)
        while rest and rest[0] in _HOME_SEP_CHARS:
            rest = rest[1:]
        if _FOREIGN_SEP:
            # Re-join natively so the value behaves like any other Windows path
            # (on POSIX "/" is already native, and "\" is a legal filename char).
            rest = rest.replace(_FOREIGN_SEP, os.sep)
        return base + (os.sep + rest if rest else "")

    return _patched


@pytest.fixture
def redirect_home(tmp_path, monkeypatch):
    """Redirect ``~`` to a throwaway dir (keeps ~/.nedotify clean)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(os.path, "expanduser", home_expander(home))
    return home
