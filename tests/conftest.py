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


@pytest.fixture
def redirect_home(tmp_path, monkeypatch):
    """Redirect ``~`` to a throwaway dir (keeps ~/.nedotify clean)."""
    orig = os.path.expanduser
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

    def _patched(path):
        if path == "~" or path.startswith("~" + os.sep):
            return str(home) + path[1:]
        return orig(path)

    monkeypatch.setattr(os.path, "expanduser", _patched)
    return home
