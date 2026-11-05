"""Portable tests for Linux package/resource and installer safety boundaries."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nedotify_linux_packaging", ROOT / "packaging/linux_support.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def test_ui_collection_preserves_both_styles_and_runtime_wallpapers(tmp_path):
    files = [
        "ui/web_new_v2/index.html", "ui/web_new_v2/js/player.js",
        "ui/web_new_v2/assets/fonts/cyrillic.woff2",
        "ui/web_new_v2/assets/backgrounds/lake.webp",
        "ui/web_new_v2/assets/backgrounds/lake.jpg",
        "ui/web_new_v2/assets/backgrounds/sources.json",
        "ui/MACos_ui/assets/backgrounds/SOURCES.json",
        "ui/web_new_v2/covers/private-cover.jpg",
        "ui/MACos_ui/css/macos.css", "ui/MACos_ui/js/macos.js",
        "ui/MACos_ui/covers/private-cover.png",
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    mapping = support.collect_ui_datas(tmp_path)
    packed = {Path(source).relative_to(tmp_path).as_posix(): destination for source, destination in mapping}
    assert "ui/MACos_ui/css/macos.css" in packed
    assert packed["ui/web_new_v2/assets/fonts/cyrillic.woff2"] == "ui/web_new_v2/assets/fonts"
    assert "ui/web_new_v2/assets/backgrounds/lake.webp" in packed
    assert not any("covers/" in path or path.lower().endswith((".jpg", "sources.json")) for path in packed)


def test_native_tool_validation_rejects_windows_executable(tmp_path, monkeypatch):
    binary = tmp_path / "ffmpeg"
    binary.write_bytes(b"MZ" + b"\0" * 100)
    monkeypatch.setattr(support.sys, "platform", "linux")
    monkeypatch.setattr(support.shutil, "which", lambda _: str(binary))
    with pytest.raises(RuntimeError, match="native ELF ffmpeg"):
        support.native_tools()


def test_install_does_not_replace_unmanaged_data_directory(tmp_path, monkeypatch):
    appdir = tmp_path / "nedotify-app"
    appdir.mkdir()
    original = appdir / "personal.txt"
    original.write_text("keep")
    monkeypatch.setattr(support, "_locations", lambda: (appdir, tmp_path / "bin/nedotify", tmp_path / "app.desktop", tmp_path / "icon.png"))
    with pytest.raises(ValueError, match="unmanaged directory"):
        support.uninstall()
    assert original.read_text() == "keep"


def test_uninstall_removes_managed_app_but_keeps_profile(tmp_path, monkeypatch):
    profile = tmp_path / ".nedotify"
    profile.mkdir()
    (profile / "nedotify_storage.db").write_bytes(b"user database")
    appdir = tmp_path / "nedotify-app"
    appdir.mkdir()
    (appdir / ".managed").write_text(support.MANAGED_MARKER + "\n")
    launcher, desktop, icon = (tmp_path / name for name in ("launcher", "app.desktop", "icon.png"))
    for path in (launcher, desktop, icon):
        path.write_text("managed")
    monkeypatch.setattr(support, "_locations", lambda: (appdir, launcher, desktop, icon))
    support.uninstall()
    assert not appdir.exists()
    assert not any(path.exists() for path in (launcher, desktop, icon))
    assert (profile / "nedotify_storage.db").read_bytes() == b"user database"


def test_desktop_exec_escapes_field_codes_and_reserved_characters():
    text = support.desktop_exec(Path('/home/test/Music Player/100%/$data`"/nedotify'))
    assert text.startswith('"') and text.endswith('"')
    assert "100%%" in text
    assert "\\$data\\`\\\"" in text


def test_packaging_fails_instead_of_omitting_missing_macos_ui(tmp_path):
    (tmp_path / "ui/web_new_v2").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="MACos_ui"):
        support.collect_ui_datas(tmp_path)


@pytest.mark.skipif(sys.platform != "linux", reason="Native Linux symlink install/update verification")
def test_bundle_update_switches_current_and_retains_previous_release(tmp_path, monkeypatch):
    source = tmp_path / "download/NeDotify"
    (source / "_internal").mkdir(parents=True)
    (source / "NeDotify").write_bytes(b"\x7fELF" + b"release-one")
    (source / "_internal/icon.png").write_bytes(b"icon")
    appdir = tmp_path / "data/nedotify-app"
    paths = (appdir, tmp_path / "bin/nedotify", tmp_path / "data/app.desktop", tmp_path / "data/icon.png")
    monkeypatch.setattr(support, "_locations", lambda: paths)
    monkeypatch.setattr(support.shutil, "which", lambda _: None)
    support.install_bundle(source)
    first = (appdir / "current").resolve()
    (source / "NeDotify").write_bytes(b"\x7fELF" + b"release-two")
    support.install_bundle(source)
    second = (appdir / "current").resolve()
    assert first != second
    assert (first / "NeDotify").read_bytes().endswith(b"release-one")
    assert (second / "NeDotify").read_bytes().endswith(b"release-two")
    assert "current/NeDotify" in paths[1].read_text()


@pytest.mark.skipif(sys.platform != "linux", reason="Native Linux symlink install/update verification")
def test_failed_bundle_staging_keeps_running_release(tmp_path, monkeypatch):
    source = tmp_path / "download/NeDotify"
    (source / "_internal").mkdir(parents=True)
    (source / "NeDotify").write_bytes(b"\x7fELF" + b"release-one")
    (source / "_internal/icon.png").write_bytes(b"icon")
    appdir = tmp_path / "data/nedotify-app"
    paths = (appdir, tmp_path / "bin/nedotify", tmp_path / "data/app.desktop", tmp_path / "data/icon.png")
    monkeypatch.setattr(support, "_locations", lambda: paths)
    monkeypatch.setattr(support.shutil, "which", lambda _: None)
    support.install_bundle(source)
    first = (appdir / "current").resolve()
    def failed_copy(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(support.shutil, "copytree", failed_copy)
    with pytest.raises(OSError, match="disk full"):
        support.install_bundle(source)
    assert (appdir / "current").resolve() == first
    assert (first / "NeDotify").read_bytes().endswith(b"release-one")
