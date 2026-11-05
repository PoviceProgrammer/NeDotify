"""Native Linux resource collection, packaging and per-user installation.

No operation touches ~/.nedotify: that directory belongs to the user's library.
The portable archive installer needs only Python's standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGED_MARKER = "nedotify.linux.install.v1"


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except OSError:
        return False


def collect_ui_datas(root: Path) -> list[tuple[str, str]]:
    """Keep runtime assets and both presentations; omit generated cover caches."""
    result = []
    for name in ("web_new_v2", "MACos_ui"):
        folder = root / "ui" / name
        if not folder.is_dir():
            raise FileNotFoundError(f"Missing product UI: {folder}")
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if "covers" in rel.parts or "__pycache__" in rel.parts:
                continue
            # Windows ships optimized wallpaper WebPs, not their source JPEGs.
            if path.parent.name == "backgrounds" and (
                    path.suffix.lower() in {".jpg", ".jpeg"} or path.name.lower() == "sources.json"):
                continue
            result.append((str(path), rel.parent.as_posix()))
    return result


def native_tools() -> dict[str, Path]:
    """Never accidentally bundle a Windows executable from this checkout."""
    if sys.platform != "linux":
        raise RuntimeError("Native tools must be resolved on Linux")
    tools = {}
    for name in ("ffmpeg", "ffprobe", "deno"):
        executable = shutil.which(name)
        if name == "deno":
            # The pip entry point may be a Python wrapper; bundle the actual ELF.
            try:
                import deno
                executable = deno.find_deno_bin()
            except ImportError:
                pass
        path = Path(executable).resolve() if executable else None
        if path is None or not is_elf(path):
            raise RuntimeError(f"Missing native ELF {name}; install FFmpeg and requirements.txt")
        result = subprocess.run([str(path), "--version" if name == "deno" else "-version"],
                                capture_output=True, text=True, timeout=20, check=True)
        if name == "deno":
            version = re.search(r"deno (\d+)\.(\d+)\.(\d+)", result.stdout)
            if not version or tuple(map(int, version.groups())) < (2, 6, 6):
                raise RuntimeError("Deno 2.6.6 or newer is required")
        tools[name] = path
    return tools


def desktop_exec(path: Path) -> str:
    """Escape the Desktop Entry grammar (which is not shell quoting)."""
    value = str(path).replace("%", "%%")
    for token in ("\\", '"', "`", "$"):
        value = value.replace(token, "\\" + token)
    return '"' + value + '"'


def _atomic_text(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, filename = tempfile.mkstemp(prefix=".nedotify-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.chmod(filename, mode)
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def _locations() -> tuple[Path, Path, Path, Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
    bindir = Path.home() / ".local/bin"
    if not data.is_absolute():
        raise ValueError("XDG_DATA_HOME must be absolute")
    return (data / "nedotify-app", bindir / "nedotify",
            data / "applications/org.nedotify.NeDotify.desktop",
            data / "icons/hicolor/256x256/apps/nedotify.png")


def _managed_root() -> tuple[Path, Path, Path, Path]:
    paths = _locations()
    appdir = paths[0]
    # Do not traverse a replacement symlink or accept an unrelated directory.
    if appdir.is_symlink():
        raise ValueError("Refusing a symlink as the application install directory")
    marker = appdir / ".managed"
    if appdir.exists() and (not marker.is_file() or marker.read_text().strip() != MANAGED_MARKER):
        raise ValueError(f"Refusing to replace an unmanaged directory: {appdir}")
    for path in paths[1:]:
        if path.exists() and not marker.exists():
            raise ValueError(f"Refusing to replace an existing launcher/icon: {path}")
    return paths


def _install_launcher(command: list[str], icon_source: Path) -> None:
    appdir, launcher, desktop, icon = _managed_root()
    appdir.mkdir(parents=True, exist_ok=True)
    _atomic_text(appdir / ".managed", MANAGED_MARKER + "\n")
    shell = "#!/bin/sh\n# " + MANAGED_MARKER + "\nexec " + shlex.join(command) + ' "$@"\n'
    _atomic_text(launcher, shell, 0o755)
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_source, icon)
    _atomic_text(desktop, "\n".join([
        "[Desktop Entry]", "Type=Application", "Version=1.0", "Name=NeDotify",
        "GenericName=Music Player", "Exec=" + desktop_exec(launcher), "Icon=" + str(icon),
        "Terminal=false", "Categories=AudioVideo;Audio;Player;", "StartupNotify=true",
        "StartupWMClass=NeDotify", "",
    ]))
    subprocess.run(["update-desktop-database", str(desktop.parent)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if shutil.which("update-desktop-database") else None


def install_source() -> None:
    if not (ROOT / "main.py").is_file() or not (ROOT / ".venv/bin/python").is_file():
        raise RuntimeError("Source installation requires main.py and a Linux .venv")
    _install_launcher(["/usr/bin/env", "bash", str(ROOT / "start_linux.sh")], ROOT / "icon.png")
    print("Installed source launcher. Keep this checkout in place; profile preserved.")


def install_bundle(source: Path) -> None:
    source = source.resolve()
    executable = source / "NeDotify"
    if not is_elf(executable) or not (source / "_internal").is_dir():
        raise ValueError("Select the complete native dist/NeDotify onedir bundle")
    icon_source = source / "icon.png"
    if not icon_source.is_file():
        icon_source = source / "_internal/icon.png"
    if not icon_source.is_file():
        raise FileNotFoundError("Bundle icon.png is missing")
    appdir, _, _, _ = _managed_root()
    appdir.mkdir(parents=True, exist_ok=True)
    _atomic_text(appdir / ".managed", MANAGED_MARKER + "\n")
    release = appdir / "releases" / uuid.uuid4().hex
    release.parent.mkdir(parents=True, exist_ok=True)
    # Every update is staged separately; previous releases remain recoverable.
    shutil.copytree(source, release, symlinks=True)
    os.chmod(release / "NeDotify", 0o755)
    _install_launcher([str(appdir / "current/NeDotify")], icon_source)
    pending = appdir / (".current-" + uuid.uuid4().hex)
    pending.symlink_to(release.relative_to(appdir), target_is_directory=True)
    os.replace(pending, appdir / "current")
    print(f"Installed {release}. Previous releases and ~/.nedotify are preserved.")


def uninstall() -> None:
    appdir, launcher, desktop, icon = _managed_root()
    if not appdir.exists():
        print("No managed installation found.")
        return
    for path in (launcher, desktop, icon):
        path.unlink(missing_ok=True)
    # _managed_root proves ownership; this directory contains app releases only.
    shutil.rmtree(appdir)
    print("Removed application files. Library, downloads, settings and secrets preserved.")


def make_packages(version: str) -> list[Path]:
    if sys.platform != "linux":
        raise RuntimeError("Build Linux archives and Debian packages natively")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*(?:[+~.-][A-Za-z0-9.]+)?", version):
        raise ValueError("Invalid package version")
    bundle = ROOT / "dist/NeDotify"
    if not is_elf(bundle / "NeDotify"):
        raise RuntimeError("Build the native PyInstaller bundle first")
    shutil.copy2(ROOT / "install_linux.sh", bundle)
    (bundle / "packaging").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), bundle / "packaging/linux_support.py")
    shutil.copy2(ROOT / "icon.png", bundle / "icon.png")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if arch is None:
        raise RuntimeError("Packaging supports x86_64 and aarch64 native builders")
    archive = ROOT / "dist" / f"NeDotify-{version}-linux-{arch}.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(bundle, arcname="NeDotify")
    outputs = [archive]
    if shutil.which("dpkg-deb"):
        with tempfile.TemporaryDirectory(prefix="nedotify-deb-") as directory:
            stage = Path(directory)
            shutil.copytree(bundle, stage / "opt/nedotify", symlinks=True)
            (stage / "usr/bin").mkdir(parents=True)
            (stage / "usr/bin/nedotify").symlink_to("/opt/nedotify/NeDotify")
            desktop = stage / "usr/share/applications/org.nedotify.NeDotify.desktop"
            desktop.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "packaging/org.nedotify.NeDotify.desktop", desktop)
            icon = stage / "usr/share/icons/hicolor/256x256/apps/nedotify.png"
            icon.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "icon.png", icon)
            control = stage / "DEBIAN/control"
            control.parent.mkdir()
            control.write_text(
                f"Package: nedotify\nVersion: {version}\nArchitecture: {arch}\n"
                "Maintainer: NeDotify Project\n"
                "Section: sound\nPriority: optional\n"
                "Depends: libc6 (>= 2.39), libegl1, libgl1, libnss3, libnspr4, "
                "libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcomposite1, "
                "libxdamage1, libxrandr2, libxtst6, libasound2t64, libdbus-1-3, "
                "libglib2.0-0t64, libsecret-1-0, libpulse0, libxcb-icccm4, "
                "libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libx11-xcb1, "
                "libxcb-shape0, libxcb-randr0, libxcb-xfixes0, libwayland-client0, "
                "libwayland-cursor0, libwayland-egl1, libfontconfig1, libfreetype6\n"
                "Recommends: gnome-keyring | kwalletmanager, libnotify-bin\n"
                "Description: NeDotify desktop music player\n"
                " Search, stream, download and organize music with both UI presentations.\n",
                encoding="utf-8")
            package = ROOT / "dist" / f"nedotify_{version}_{arch}.deb"
            subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(package)], check=True)
            outputs.append(package)
    manifest = ROOT / "dist/SHA256SUMS"
    checksums = []
    for path in outputs:
        with path.open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
    manifest.write_text("".join(checksums), encoding="utf-8")
    print(json.dumps({"packages": list(map(str, outputs)), "checksums": str(manifest)}, indent=2))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-tools", action="store_true")
    action.add_argument("--install-source", action="store_true")
    action.add_argument("--install-bundle", type=Path)
    action.add_argument("--uninstall", action="store_true")
    action.add_argument("--package", action="store_true")
    parser.add_argument("--version", default="2.5.1")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This command must run natively on Linux")
    if args.check_tools:
        print(json.dumps({key: str(value) for key, value in native_tools().items()}, indent=2))
    elif args.install_source:
        install_source()
    elif args.install_bundle:
        install_bundle(args.install_bundle)
    elif args.uninstall:
        uninstall()
    else:
        make_packages(args.version)


if __name__ == "__main__":
    main()
