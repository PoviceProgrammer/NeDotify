"""Tool preparation never replaces working files with unverified downloads."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import threading
import zipfile

import pytest

from core.setup_engine import SetupDependencyError, SetupEngine, resolve_managed_tool


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, category, key=None, default=None):
        return self.values.get((category, key), default)

    def set(self, category, key, value):
        self.values[category, key] = value

    def sync_flush_now(self):
        return True


class Response:
    def __init__(self, content=b"", status=200, headers=None, json_data=None, fail_after=None):
        self.content, self.status_code, self.headers = content, status, headers or {}
        self.json_data, self.fail_after, self.closed = json_data, fail_after, False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError("HTTP unavailable")

    def json(self):
        return self.json_data

    def iter_content(self, size):
        if self.fail_after is not None:
            yield self.content[:self.fail_after]
            raise OSError("Connection interrupted")
        yield self.content

    def close(self):
        self.closed = True


class OfficialServer:
    def __init__(self, *, corrupt=False, interrupted=False, missing_probe=False):
        self.calls = []
        self.corrupt, self.interrupted, self.missing_probe = corrupt, interrupted, missing_probe
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("build/bin/ffmpeg.exe", b"ffmpeg version 7.1")
            if not missing_probe:
                zipped.writestr("build/bin/ffprobe.exe", b"ffprobe version 7.1")
            zipped.writestr("build/LICENSE.txt", b"GPL license notice fixture")
            zipped.writestr("../../unwanted.exe", b"must never extract")
        self.data = {"yt_dlp": b"2026.10.26", "ffmpeg": archive.getvalue()}
        self.versions = {"yt_dlp": "2026.10.26", "ffmpeg": "latest"}

    def release(self, tool):
        asset_name = "yt-dlp.exe" if tool == "yt_dlp" else "ffmpeg-master-latest-win64-gpl.zip"
        repo = "yt-dlp/yt-dlp" if tool == "yt_dlp" else "yt-dlp/FFmpeg-Builds"
        digest = hashlib.sha256(self.data[tool]).hexdigest()
        assets = [{"name": asset_name, "size": len(self.data[tool]), "digest": "sha256:" + digest,
                   "browser_download_url": f"https://github.com/{repo}/releases/download/stable/{asset_name}"},
                  {"name": "SHA2-256SUMS" if tool == "yt_dlp" else "checksums.sha256",
                   "browser_download_url": f"https://github.com/{repo}/releases/download/stable/checksums"}]
        return {"id": 101 if tool == "yt_dlp" else 102, "tag_name": self.versions[tool], "assets": assets}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        tool = "ffmpeg" if "FFmpeg-Builds" in url else "yt_dlp"
        if url.startswith("https://api.github.com/"):
            return Response(json_data=self.release(tool))
        if url.endswith("/checksums"):
            release = self.release(tool)
            asset = release["assets"][0]
            return Response((hashlib.sha256(self.data[tool]).hexdigest() + "  " + asset["name"]).encode())
        data = self.data[tool] + (b"!" if self.corrupt else b"")
        offset = int(kwargs.get("headers", {}).get("Range", "bytes=0-")[6:-1])
        if self.interrupted and not offset:
            self.interrupted = False
            return Response(data, fail_after=4)
        if offset:
            return Response(data[offset:], 206, {"Content-Range": f"bytes {offset}-{len(data)-1}/{len(data)}"})
        return Response(data)

    def close(self):
        pass


@pytest.fixture
def engine(tmp_path, monkeypatch):
    server = OfficialServer()
    done = threading.Event()
    events = []
    def emit(name, payload):
        events.append((name, payload))
        if name == "setup_status":
            done.set()
    setup = SetupEngine(Settings(), emit=emit, profile_dir=tmp_path, http_session=server)
    monkeypatch.setattr(setup, "_module_version", lambda name: "1.0" if name != "yt_dlp" else None)
    original_resolve = setup._resolve_tool
    monkeypatch.setattr(setup, "_resolve_tool", lambda name: (setup._managed_path(name), "managed") if setup._managed_path(name) else (None, None))
    monkeypatch.setattr(setup, "_asset_name", lambda tool: "yt-dlp.exe" if tool == "yt_dlp" else "ffmpeg-master-latest-win64-gpl.zip")
    monkeypatch.setattr(setup, "_probe", lambda path, name: (True, Path(path).read_text()))
    setup.done, setup.events, setup.server, setup.original_resolve = done, events, server, original_resolve
    yield setup
    setup.close()


def repair(engine, tools=None, update=False):
    engine.done.clear()
    assert engine.start_repair(tools, update)["success"] is True
    assert engine.done.wait(5), "Preparation did not finish"
    return engine.get_status()


def test_quick_status_is_offline_and_never_launches_tools(engine, monkeypatch):
    monkeypatch.setattr(engine, "_probe", lambda *args: pytest.fail("Fast startup must not execute a process"))
    snapshot = engine.get_status()
    assert snapshot["ready"] is False
    assert engine.server.calls == []
    assert {i["code"] for i in snapshot["issues"]} == {"missing_yt_dlp", "missing_ffmpeg", "missing_ffprobe"}


def test_missing_extractor_has_actionable_download_error(engine):
    with pytest.raises(SetupDependencyError) as raised:
        with engine.acquire_download_tools():
            pass
    assert raised.value.as_dict()["code"] == "missing_yt_dlp"
    assert raised.value.recoverable


def test_direct_http_download_does_not_require_unrelated_extractor(engine):
    with engine.acquire_download_tools(require_yt_dlp=False) as tools:
        assert tools["yt_dlp_path"] is None
        assert engine.get_status()["active_downloads"] == 1
    assert engine.get_status()["active_downloads"] == 0


def test_python_module_can_download_source_without_ffmpeg_and_releases_lease(engine, monkeypatch):
    monkeypatch.setattr(engine, "_module_version", lambda name: "2026.10.26")
    with engine.acquire_download_tools() as tools:
        assert tools["yt_dlp_module"] is True
        assert tools["ffmpeg_path"] is None
        assert engine.start_repair()["code"] == "dependencies_busy"
    with pytest.raises(SetupDependencyError, match="FFmpeg"):
        with engine.acquire_download_tools(require_ffmpeg=True):
            pass
    assert engine.get_status()["active_downloads"] == 0


def test_verified_install_exposes_both_tools_and_preserves_notices(engine):
    snapshot = repair(engine)
    assert snapshot["ready"] is True
    assert snapshot["operation"]["status"] == "completed"
    with engine.acquire_download_tools(require_ffmpeg=True) as tools:
        assert Path(tools["ffmpeg_path"]).read_bytes() == b"ffmpeg version 7.1"
        assert Path(tools["ffprobe_path"]).read_bytes() == b"ffprobe version 7.1"
    assert resolve_managed_tool("ffprobe", engine.profile) == snapshot["paths"]["ffprobe_path"]
    assert list(engine.tools_dir.rglob("LICENSE-0.txt"))
    assert not (engine.profile / "unwanted.exe").exists()
    assert any(name == "setup_progress" and payload["downloaded_bytes"] > 0 for name, payload in engine.events)
    assert SetupEngine(engine.settings, profile_dir=engine.profile).get_status()["dependencies"]["ffmpeg"]["available"]


def test_bad_checksum_or_size_never_replaces_working_install(engine):
    first = repair(engine)
    manifest = engine._manifest_path.read_bytes()
    previous = first["paths"]
    engine.server.corrupt = True
    result = repair(engine, ["yt_dlp"], update=True)
    assert result["operation"]["status"] == "failed"
    assert engine._manifest_path.read_bytes() == manifest
    assert engine.get_status()["paths"] == previous


def test_failed_post_install_launch_rolls_manifest_back(engine, monkeypatch):
    repair(engine)
    manifest = engine._manifest_path.read_bytes()
    original_probe = engine._probe
    def probe(path, name):
        if name == "yt_dlp" and ".staging" not in str(path):
            return False, "cannot launch new binary"
        return original_probe(path, name)
    monkeypatch.setattr(engine, "_probe", probe)
    result = repair(engine, ["yt_dlp"], update=True)
    assert result["operation"]["error"]["code"] == "update_rolled_back"
    assert engine._manifest_path.read_bytes() == manifest


def test_truncated_transfer_resumes_from_exact_offset_before_verification(engine):
    engine.server.interrupted = True
    result = repair(engine)
    assert result["ready"] is True
    assert any(options.get("headers", {}).get("Range") == "bytes=4-" for _, options in engine.server.calls)


def test_missing_probe_in_archive_leaves_no_manifest_entry(engine):
    engine.server = OfficialServer(missing_probe=True)
    engine._session = engine.server
    result = repair(engine, ["ffmpeg"])
    assert result["operation"]["status"] == "failed"
    assert engine._manifest.get("tools", {}) == {}
    assert engine._managed_path("ffmpeg") is None


def test_deep_check_detects_binary_corruption(engine):
    first = repair(engine)
    binary = Path(first["paths"]["ffmpeg_path"])
    binary.write_bytes(b"broken")
    snapshot = engine.get_status(deep=True)
    assert snapshot["dependencies"]["ffmpeg"]["available"] is False
    assert any(issue["code"] == "missing_ffmpeg" for issue in snapshot["issues"])
    assert engine.get_status()["dependencies"]["ffmpeg"]["available"] is False


def test_cancellation_never_changes_previous_manifest(engine, monkeypatch):
    repair(engine)
    manifest = engine._manifest_path.read_bytes()
    def cancelled_release(tool):
        engine.cancel()
        engine._check_cancelled()
    monkeypatch.setattr(engine, "_release", cancelled_release)
    snapshot = repair(engine, ["yt_dlp"], update=True)
    assert snapshot["operation"]["status"] == "cancelled"
    assert engine._manifest_path.read_bytes() == manifest
    assert snapshot["updating"] is False


def test_download_cannot_acquire_lease_during_installation(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def blocked_install(tool):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(engine, "_install", blocked_install)
    assert engine.start_repair(["yt_dlp"])["success"]
    assert entered.wait(5)
    try:
        with pytest.raises(SetupDependencyError) as raised:
            with engine.acquire_download_tools():
                pass
        assert raised.value.code == "dependencies_busy"
        assert engine.start_repair()["success"] is False
    finally:
        release.set()
    assert engine.done.wait(5)


@pytest.mark.parametrize("options", [{"format": []}, {"format": "bad"}, {"quality": "999"},
    {"max_concurrent": True}, {"max_concurrent": 5}, {"directory": "relative"},
    {"embed_cover": "yes"}, {"auto_update_tools": 1}])
def test_invalid_configuration_does_not_write_preferences(engine, options):
    engine.settings.set("general", "scan_folders", ["C:/old-library"])
    before = dict(engine.settings.values)
    assert engine.configure(options)["success"] is False
    assert engine.settings.values == before


def test_configuration_adds_folder_without_resetting_library_or_theme(engine, tmp_path):
    engine.settings.set("general", "scan_folders", ["C:/old-library"])
    engine.settings.set("theme", "theme", "mint")
    result = engine.configure({"directory": str(tmp_path / "Music"), "library_directory": str(tmp_path / "Local"), "format": "source", "max_concurrent": 3})
    assert result["success"] is True
    assert result["settings"]["scan_folders"] == ["C:/old-library", str(tmp_path / "Local")]
    assert engine.settings.get("theme", "theme") == "mint"
    assert (tmp_path / "Music").is_dir()


def test_manifest_path_traversal_is_rejected(engine, tmp_path):
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"not a tool")
    engine.tools_dir.mkdir()
    payload = {"schema_version": 1, "tools": {"ffmpeg": {"paths": {"ffmpeg": "../outside.exe"}}}}
    engine._manifest_path.write_text(json.dumps(payload))
    assert resolve_managed_tool("ffmpeg", engine.profile) is None
    assert engine.get_status()["dependencies"]["ffmpeg"]["available"] is False


def test_update_check_does_not_replace_tools_or_run_on_startup(engine):
    snapshot = repair(engine)
    original = engine._manifest_path.read_bytes()
    updates = engine.check_updates()
    assert all(not item["available"] for item in updates.values())
    assert snapshot["ready"]
    assert engine._manifest_path.read_bytes() == original


def test_optional_auto_update_is_disabled_by_default_and_runs_only_once(engine, monkeypatch):
    called = threading.Event()
    monkeypatch.setattr(engine, "check_updates", lambda: called.set() or {})
    assert engine.maybe_auto_update()["started"] is False
    assert called.is_set() is False
    engine.settings.set("downloads", "auto_update_tools", True)
    assert engine.maybe_auto_update()["started"] is True
    assert called.wait(2)
    assert engine.maybe_auto_update()["started"] is False


def test_optional_auto_update_does_not_start_while_download_uses_tools(engine, monkeypatch):
    engine.settings.set("downloads", "auto_update_tools", True)
    with engine.acquire_download_tools(require_yt_dlp=False):
        assert engine.maybe_auto_update()["started"] is False
    assert engine.server.calls == []


def test_shutdown_is_bounded_and_rejects_new_preparation(engine, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def blocked_install(tool):
        entered.set()
        release.wait(2)
        engine._check_cancelled()
    monkeypatch.setattr(engine, "_install", blocked_install)
    assert engine.start_repair(["yt_dlp"])["success"]
    assert entered.wait(2)
    assert engine.shutdown(timeout=0) is False
    assert engine.start_repair()["code"] == "setup_closed"
    release.set()
    assert engine.done.wait(2)
    assert engine.shutdown(timeout=1) is True


def test_corrupt_manifest_does_not_reset_other_settings(engine):
    engine.tools_dir.mkdir()
    engine._manifest_path.write_text('{"schema_version":1,"tools":{"ffmpeg":"invalid"}}')
    restored = SetupEngine(engine.settings, profile_dir=engine.profile)
    assert restored.get_status()["dependencies"]["ffmpeg"]["source"] != "managed"
    assert restored.settings is engine.settings
    restored.close()


def test_transient_windows_sharing_violation_keeps_atomic_install(engine, monkeypatch):
    import os
    original = os.replace
    blocked = []
    def replace(source, target):
        if not blocked and Path(source).is_dir():
            blocked.append(str(source))
            raise PermissionError("sharing violation")
        return original(source, target)
    monkeypatch.setattr(os, "replace", replace)
    assert repair(engine)["ready"] is True
    assert blocked


def test_stale_external_wrapper_does_not_disable_available_python_extractor(engine, monkeypatch, tmp_path):
    wrapper = tmp_path / 'yt-dlp.exe'
    wrapper.write_bytes(b'old wrapper')
    monkeypatch.setattr(engine, '_resolve_tool', lambda name: (str(wrapper), 'system') if name=='yt_dlp' else (None,None))
    monkeypatch.setattr(engine, '_module_version', lambda name: '2026.10.26')
    monkeypatch.setattr(engine, '_probe', lambda path, name: (False,'cannot launch wrapper'))
    dependency = engine.get_status(deep=True)['dependencies']['yt_dlp']
    assert dependency['available'] is True
    assert dependency['source'] == 'python'
    assert dependency['path'] is None


def test_new_managed_extractor_takes_precedence_over_old_python_module(engine, monkeypatch):
    repair(engine)
    monkeypatch.setattr(engine, '_module_version', lambda name: '2026.01.01')
    with engine.acquire_download_tools() as tools:
        assert tools['yt_dlp_module'] is True
        assert tools['prefer_executable'] is True
    monkeypatch.setattr(engine, '_module_version', lambda name: '2026.10.26')
    with engine.acquire_download_tools() as tools:
        assert tools['prefer_executable'] is False


def test_frozen_and_portable_tool_paths_are_discovered(tmp_path, monkeypatch):
    import sys
    bundle = tmp_path/'frozen'
    bundle.mkdir()
    (bundle/'ffmpeg.exe').write_bytes(b'bundled executable fixture')
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    setup = SetupEngine(Settings(), profile_dir=tmp_path/'profile')
    assert setup._resolve_tool('ffmpeg') == (str(bundle/'ffmpeg.exe'), 'bundled')
    monkeypatch.delattr(sys, '_MEIPASS')
    portable = tmp_path/'portable'
    portable.mkdir()
    monkeypatch.setattr(sys, 'executable', str(portable/'NeDotify.exe'))
    (portable/'ffprobe.exe').write_bytes(b'portable executable fixture')
    assert setup._resolve_tool('ffprobe') == (str(portable/'ffprobe.exe'), 'bundled')
    setup.close()
