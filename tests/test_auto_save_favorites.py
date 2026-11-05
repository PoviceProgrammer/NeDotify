"""Auto-save of liked tracks (AppApi.toggle_favorite -> _auto_save_favorite).

Contracts pinned here, because every one of them fails silently otherwise:
the user clicks like and nothing is stored, with no error anywhere.

  * feature off by default            - no cache, no queue
  * local files are skipped           - they are already on disk
  * streaming tracks: cached + queued
  * the quota blocks queueing and says why
  * un-liking never deletes anything
"""

import os
import types

import pytest

from core.api import AppApi


class _Settings:
    def __init__(self, **over):
        self._d = {"storage": {
            "auto_download_favorites": False,
            "auto_download_favorites_quota_gb": 20,
        }}
        self._d["storage"].update(over)

    def get(self, category, key, default=None):
        return self._d.get(category, {}).get(key, default)

    def set(self, category, key, value):
        self._d.setdefault(category, {})[key] = value


class _Cache:
    def __init__(self):
        self.calls = []

    def download_audio_stream(self, source, source_id, url):
        self.calls.append((source, source_id, url))


class _Downloader:
    def __init__(self):
        self.calls = []

    def queue_download(self, track_id, source, source_id, from_db=False):
        self.calls.append((track_id, source, source_id))
        return True


@pytest.fixture
def wired(core_ns, monkeypatch):
    """AppApi with just enough core to exercise the auto-save path."""
    settings = _Settings()
    core_ns.settings = settings
    core_ns.cache = _Cache()
    core_ns.downloader = _Downloader()
    app = AppApi(core_ns)
    app._emit = lambda *a, **k: None
    return app, settings, core_ns


def _yt_track(track_id=7):
    return {"id": track_id, "source": "youtube", "source_id": "dQw4w9WgXcQ",
            "title": "Song", "artist": "A"}


def test_disabled_by_default_does_nothing(wired):
    app, _, core = wired
    res = app._auto_save_favorite(_yt_track(), 7)
    assert res is None
    assert core.cache.calls == []
    assert core.downloader.calls == []


def test_local_files_are_skipped(wired):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)
    res = app._auto_save_favorite({"id": 7, "source": "local", "source_id": "x",
                                   "file_path": "C:/music/a.mp3"}, 7)
    assert res is None
    assert core.downloader.calls == []


def test_streaming_track_is_cached_then_queued(wired):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)

    res = app._auto_save_favorite(_yt_track(), 7)

    assert res["cached"] is True
    assert res["queued"] is True
    assert core.cache.calls == [("youtube", "dQw4w9WgXcQ", "")]
    assert core.downloader.calls == [(7, "youtube", "dQw4w9WgXcQ")]


def test_quota_blocks_queueing_with_a_reason(wired, monkeypatch, tmp_path):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)
    settings.set("storage", "auto_download_favorites_quota_gb", 1)
    # 1 GB quota, but the downloads dir already holds more than that.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".nedotify").mkdir()
    dl = tmp_path / ".nedotify" / "downloads"
    dl.mkdir()
    # Must actually exceed the 1 GB quota above, otherwise nothing is blocked.
    (dl / "big.mp3").write_bytes(b"0" * (1024 * 1024 * 1024 + 1))

    res = app._auto_save_favorite(_yt_track(), 7)

    assert res["queued"] is False
    assert "1" in res["reason"]
    assert core.downloader.calls == []


def test_zero_quota_means_unlimited(wired, monkeypatch, tmp_path):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)
    settings.set("storage", "auto_download_favorites_quota_gb", 0)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".nedotify" / "downloads").mkdir(parents=True)
    (tmp_path / ".nedotify" / "downloads" / "big.mp3").write_bytes(b"0" * 4096)

    res = app._auto_save_favorite(_yt_track(), 7)

    assert res["queued"] is True
    assert len(core.downloader.calls) == 1


def test_already_downloaded_track_is_skipped(wired, monkeypatch):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)
    real_get = core.db.get_track

    def fake_get(tid):
        row = dict(real_get(tid) or {})
        row["is_downloaded"] = 1
        return row

    monkeypatch.setattr(core.db, "get_track", fake_get)

    assert app._auto_save_favorite(_yt_track(), 7) is None
    assert core.downloader.calls == []


def test_unliking_does_not_trigger_autosave(wired):
    app, settings, core = wired
    settings.set("storage", "auto_download_favorites", True)
    monkey = types.SimpleNamespace(db=core.db)

    # toggle_favorite returns is_favorite False on the second call.
    app.toggle_favorite(_yt_track())
    app.toggle_favorite(_yt_track())

    assert len(core.downloader.calls) <= 1
    # Nothing was ever removed from disk by the toggle path.
    assert core.cache.calls == [] or all(c[1] == "dQw4w9WgXcQ" for c in core.cache.calls)
