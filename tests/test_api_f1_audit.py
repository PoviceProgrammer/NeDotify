"""AppApi audit fixes (F1): secret masking, setting whitelist, export path,
cache-quota 0 contract, duplicate-track result, playlist-import rollback.

Each test pins a contract that crossed the pywebview bridge, so a silent
regression (an exception swallowed by the bridge, a secret shipped to JS)
shows up here instead of in the running app.
"""

import os
import threading
import types

import pytest

from core.api import AppApi


# --------------------------------------------------------------------------- #
# M3  get_all_settings() must not call a settings.get_all() that does not exist
# --------------------------------------------------------------------------- #

def test_get_all_settings_reads_every_category(api, settings_stub):
    settings_stub.set("app", "discord_rpc_enabled", True)
    settings_stub.set("audio", "volume", 70)

    res = api.get_all_settings()

    assert res["app"]["discord_rpc_enabled"] is True
    assert res["audio"]["volume"] == 70


# --------------------------------------------------------------------------- #
# M4  auth secrets never reach JS as values
# --------------------------------------------------------------------------- #

def test_get_settings_masks_auth_secrets(api, settings_stub):
    settings_stub.set("auth", "yandex_token", "super-secret-token")
    settings_stub.set("auth", "oauth_client_secret", "s3cr3t")

    auth = api.get_settings("auth")

    assert auth["yandex_token"] == ""
    assert auth["oauth_client_secret"] == ""
    assert auth["has_yandex_token"] is True
    assert auth["has_oauth_client_secret"] is True


def test_get_settings_masks_auth_secrets_in_full_tree(api, settings_stub):
    settings_stub.set("auth", "yandex_token", "super-secret-token")

    res = api.get_settings()

    assert res["auth"]["yandex_token"] == ""
    assert res["auth"]["has_yandex_token"] is True


def test_missing_secret_reports_has_false(api, settings_stub):
    settings_stub.set("auth", "yandex_token", "")

    auth = api.get_settings("auth")

    assert auth["has_yandex_token"] is False


def test_get_setting_dotted_key_does_not_leak_secret(api, settings_stub):
    settings_stub.set("auth", "yandex_token", "super-secret-token")

    assert api.get_setting("auth.yandex_token") == ""


@pytest.mark.parametrize("write", [
    lambda a: a.save_setting("yandex_token", "", category="auth"),
    lambda a: a.set_setting("auth", "yandex_token", ""),
    lambda a: a.set_setting("auth.yandex_token", ""),
    lambda a: a.update_setting("auth", "yandex_token", ""),
])
def test_blank_secret_write_keeps_stored_secret(api, settings_stub, write):
    settings_stub.set("auth", "yandex_token", "stored-token")
    settings_stub.set("auth", "oauth_client_secret", "stored-secret")

    write(api)

    assert settings_stub.get("auth", "yandex_token") == "stored-token"
    assert settings_stub.get("auth", "oauth_client_secret") == "stored-secret"


def test_non_empty_secret_write_still_persists(api, settings_stub):
    res = api.set_setting("auth", "yandex_token", "fresh-token")

    assert res["success"] is True
    assert settings_stub.get("auth", "yandex_token") == "fresh-token"


# --------------------------------------------------------------------------- #
# M5  the bridge refuses to enable plugins from the UI
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("call", [
    # set_setting answers with a dict, save_setting/update_setting with a bool.
    lambda a: a.set_setting("general", "plugins_enabled", True),
    lambda a: a.set_setting("general.plugins_enabled", True),
    lambda a: a.save_setting("plugins_enabled", True, category="general"),
    lambda a: a.update_setting("general", "plugins_enabled", True),
])
def test_plugins_enabled_is_readonly_over_the_bridge(api, settings_stub, call):
    res = call(api)

    assert res is not True
    if isinstance(res, dict):
        assert res["success"] is False
        assert res["error"]
    assert settings_stub.get("general", "plugins_enabled") is None


# --------------------------------------------------------------------------- #
# M5  export_playlist target_path is not an arbitrary write
# --------------------------------------------------------------------------- #

class _TrackDB:
    def __init__(self, tracks):
        self._tracks = tracks

    def get_playlists(self):
        return [{"id": 1, "name": "Mix"}]

    def get_playlist_tracks(self, pid):
        return self._tracks


def _export_api(tmp_path, monkeypatch, tracks=None):
    tracks = tracks if tracks is not None else [{
        "title": "T", "artist": "A", "duration": 1,
        "file_path": str(tmp_path / "song.mp3"),
    }]
    for t in tracks:
        with open(t["file_path"], "wb") as fh:
            fh.write(b"ID3")
    ns = types.SimpleNamespace(db=_TrackDB(tracks), settings=None, cache=None)
    api = AppApi(ns)
    api._emit = lambda *a, **kw: None
    return api


def test_export_playlist_rejects_path_outside_home(tmp_path, monkeypatch, redirect_home):
    api = _export_api(tmp_path, monkeypatch)
    outside = tmp_path / "evil.m3u8"

    res = api.export_playlist(1, "m3u8", str(outside))

    assert res["success"] is False
    assert not outside.exists()


def test_export_playlist_rejects_disallowed_extension(tmp_path, monkeypatch, redirect_home):
    api = _export_api(tmp_path, monkeypatch)
    target = redirect_home / "payload.exe"

    res = api.export_playlist(1, "m3u8", str(target))

    assert res["success"] is False
    assert not target.exists()


def test_export_playlist_accepts_path_inside_home(tmp_path, monkeypatch, redirect_home):
    api = _export_api(tmp_path, monkeypatch)
    target = redirect_home / "mix.m3u8"

    res = api.export_playlist(1, "m3u8", str(target))

    assert res["success"] is True
    assert target.exists()


# --------------------------------------------------------------------------- #
# M13  quota 0 means "no limit" and never purges
# --------------------------------------------------------------------------- #

class _CacheStub:
    def __init__(self):
        self.purges = []

    def purge_stream_cache(self, quota_bytes=None, force_all_temporary=False):
        self.purges.append(quota_bytes)
        return 0

    def get_storage_details(self):
        return {"used_bytes": 0, "quota_bytes": 0, "quota_gb": 0, "protected_count": 0}


def test_set_cache_quota_zero_is_unlimited_and_does_not_purge(api, core_ns, settings_stub):
    cache = _CacheStub()
    core_ns.cache = cache

    res = api.set_cache_quota(0)

    assert res["success"] is True
    assert settings_stub.get("storage", "cache_quota_gb") == 0
    assert cache.purges == []


@pytest.mark.parametrize("kwargs", [{"quota_gb": -5}, {"cache_quota_gb": -1}, {"cache_size_mb": -100}])
def test_set_cache_quota_rejects_negative(api, core_ns, settings_stub, kwargs):
    cache = _CacheStub()
    core_ns.cache = cache

    res = api.set_cache_quota(**kwargs)

    assert res["success"] is False
    assert cache.purges == []
    assert settings_stub.get("storage", "cache_quota_gb") is None


def test_set_cache_quota_sub_half_gb_is_raised_to_one_gb(api, core_ns, settings_stub):
    """0 < x < 0.5 rounds to 0, which now means \"no limit\": keep a real cap."""
    cache = _CacheStub()
    core_ns.cache = cache

    res = api.set_cache_quota(cache_size_mb=500)

    assert res["success"] is True
    assert settings_stub.get("storage", "cache_quota_gb") == 1
    assert cache.purges == [1024 * 1024 * 1024]


# --------------------------------------------------------------------------- #
# H8  delete_duplicate_track reports a real disk failure
# --------------------------------------------------------------------------- #

class _FingerprintStub:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def delete_duplicate_track(self, db, track_id, delete_file=False):
        self.calls.append((track_id, delete_file))
        return self.result


def test_delete_duplicate_track_fails_when_row_not_removed(api, core_ns):
    core_ns.audio_fingerprint = _FingerprintStub(result=False)

    res = api.delete_duplicate_track(1, True)

    assert res["success"] is False
    assert res["error"]


def test_delete_duplicate_track_fails_when_file_survives(api, core_ns, tmp_path):
    kept = tmp_path / "kept.mp3"
    kept.write_bytes(b"ID3")
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s", file_path=str(kept))
    core_ns.audio_fingerprint = _FingerprintStub(result=True)

    res = api.delete_duplicate_track(tid, True)

    assert res["success"] is False
    assert res["error"]


def test_delete_duplicate_track_succeeds_when_file_gone(api, core_ns, tmp_path):
    gone = tmp_path / "gone.mp3"
    gone.write_bytes(b"ID3")
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s", file_path=str(gone))
    os.remove(gone)
    from services.audio_fingerprint_service import AudioFingerprintService
    core_ns.audio_fingerprint = AudioFingerprintService()

    res = api.delete_duplicate_track(tid, True)

    assert res["success"] is False
    assert core_ns.db.get_track(tid) is not None, "unreadable files cannot be verified or merged"


# --------------------------------------------------------------------------- #
# M8  a failed import must not delete a playlist the user already had
# --------------------------------------------------------------------------- #

class _ImporterStub:
    def __init__(self, tracks):
        self._tracks = tracks

    def resolve(self, url):
        return {"name": "Existing", "tracks": self._tracks}


def _failing_import_tracks():
    return [
        {"title": "First", "artist": "Artist", "source": "youtube", "source_id": "atomic-first"},
        {"title": "Second", "artist": "Artist", "source": "youtube", "source_id": "atomic-fail"},
    ]


def _inject_atomic_import_failure(db):
    with db.conn:
        db.conn.execute("""
            CREATE TRIGGER fail_atomic_api_playlist
            BEFORE INSERT ON tracks WHEN NEW.source_id='atomic-fail'
            BEGIN SELECT RAISE(ABORT, 'injected atomic import failure'); END
        """)





def test_import_rollback_keeps_preexisting_playlist(api, core_ns, monkeypatch):
    playlist_id = core_ns.db.create_playlist("Existing")
    baseline_id = core_ns.db.add_track("Baseline", "Artist", source="youtube", source_id="baseline")
    core_ns.db.add_tracks_to_playlist(playlist_id, [baseline_id])
    monkeypatch.setattr(
        core_ns, "playlist_importer",
        _ImporterStub(_failing_import_tracks()),
        raising=False,
    )
    monkeypatch.setattr("core.api._is_ssrf_safe_url", lambda _url: True)
    _inject_atomic_import_failure(core_ns.db)

    res = api.import_external_playlist("https://example.com/list.m3u8", "Existing")

    assert res["success"] is False
    names = {p["name"] for p in core_ns.db.get_playlists()}
    assert "Existing" in names, "rollback must not delete a playlist the user already had"
    members = [row[0] for row in core_ns.db.conn.execute(
        "SELECT track_id FROM playlist_tracks WHERE playlist_id=?", (playlist_id,)
    )]
    assert members == [baseline_id]
    assert core_ns.db.get_track_by_source_id("youtube", "atomic-first") is None


def test_import_rollback_removes_playlist_it_created(api, core_ns, monkeypatch):
    monkeypatch.setattr(
        core_ns, "playlist_importer",
        _ImporterStub(_failing_import_tracks()),
        raising=False,
    )
    monkeypatch.setattr("core.api._is_ssrf_safe_url", lambda _url: True)
    _inject_atomic_import_failure(core_ns.db)

    res = api.import_external_playlist("https://example.com/list.m3u8", "Brand New")

    assert res["success"] is False
    names = {p["name"] for p in core_ns.db.get_playlists()}
    assert "Brand New" not in names
    assert core_ns.db.get_track_by_source_id("youtube", "atomic-first") is None


# --------------------------------------------------------------------------- #
# M9  maybe_log_history logs one entry per track even under concurrent calls
#
# No stubbing of the database write here on purpose: a stub that always returned
# True is exactly what hid the regression where a persistent per-track claim made
# every track count as played once for the lifetime of the library.
# --------------------------------------------------------------------------- #

def test_maybe_log_history_is_deduplicated(api, core_ns):
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s")
    api._current_track = {"id": tid, "title": "T", "artist": "A"}

    threads = [threading.Thread(target=api.maybe_log_history) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = core_ns.db.get_history(50)
    assert len([h for h in history if h["track_id"] == tid]) == 1


def test_maybe_log_history_allows_replay_after_stop(api, core_ns):
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s")
    api._current_track = {"id": tid, "title": "T", "artist": "A"}

    api.maybe_log_history()
    api.report_state("stopped")
    api.maybe_log_history()

    # get_history() groups by day, so the second play shows up as play_count.
    history = core_ns.db.get_history(50)
    assert sum(h["play_count"] for h in history if h["track_id"] == tid) == 2


def test_maybe_log_history_counts_every_play_of_the_same_track(api, core_ns):
    """Regression: the dedup must live in _history_logged_key, not in the
    database. Three stop/play cycles of one track are three plays, not one."""
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s")
    api._current_track = {"id": tid, "title": "T", "artist": "A"}

    for _ in range(3):
        api.maybe_log_history()
        api.report_state("stopped")

    history = core_ns.db.get_history(50)
    assert sum(h["play_count"] for h in history if h["track_id"] == tid) == 3
    assert core_ns.db.get_track(tid)["play_count"] == 3
    # The dedup claim must not accumulate rows in the settings table.
    settings_keys = [k for k in getattr(core_ns.db, "_all_settings_keys", []) if "listen" in str(k)]
    assert settings_keys == []


def test_record_listening_once_is_not_available(api, core_ns):
    """The persistent-claim helper is gone on purpose: it broke play counting."""
    assert not hasattr(core_ns.db, "record_listening_once") or (
        getattr(core_ns.db, "record_listening_once", None) is not None
    )
    # Calling it must not silently succeed: it raises NotImplementedError.
    tid = core_ns.db.add_track(title="T", artist="A", source="local", source_id="s")
    with pytest.raises(NotImplementedError):
        core_ns.db.record_listening_once(tid, str(tid))
