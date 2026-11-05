# -*- mode: python ; coding: utf-8 -*-
"""Native Ubuntu 24.04+ Qt WebEngine onedir package; no cross-compilation."""
import os
import runpy
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

if sys.platform != "linux":
    raise RuntimeError("Build NeDotify Linux natively on Linux, never with Windows binaries")

ROOT = Path(SPECPATH)
os.environ["QT_API"] = "pyqt6"
os.environ["PYWEBVIEW_GUI"] = "qt"
support = runpy.run_path(str(ROOT / "packaging/linux_support.py"))
ui_datas = support["collect_ui_datas"](ROOT)
tools = support["native_tools"]()

datas = ui_datas + [
    (str(ROOT / "icon.png"), "."),
    (str(ROOT / "logo.png"), "."),
    (str(ROOT / "licenses"), "licenses"),
    (str(ROOT / "LICENSE"), "."),
]
for package in ("ytmusicapi", "yt_dlp", "yt_dlp_ejs", "curl_cffi", "certifi"):
    datas.extend(collect_data_files(package))
for distribution in ("keyring", "yt-dlp", "yt-dlp-ejs", "pywebview", "PyQt6",
                     "PyQt6-WebEngine", "deno", "curl_cffi", "miniaudio"):
    # keyring discovers secure backends through installed entry-point metadata.
    datas.extend(copy_metadata(distribution))

# The QtWebEngineCore/Widgets hooks collect QtWebEngineProcess, Chromium .pak
# resources, locales and the Qt xcb/Wayland plugins in their required layout.
# Include dynamic imports used by the bridge, providers, keyring and D-Bus.
hiddenimports = [
    "linux_runtime", "tools.validate_linux",
    "webview.platforms.qt", "qtpy", "PyQt6.QtCore", "PyQt6.QtGui",
    "PyQt6.QtWidgets", "PyQt6.QtWebChannel", "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets", "PyQt6.QtNetwork", "PyQt6.QtSvg",
    "pypresence", "requests", "mutagen.id3", "mutagen.mp3", "mutagen.mp4",
    "mutagen.flac", "mutagen.oggvorbis", "mutagen.oggopus", "mutagen.wave",
    "mutagen.asf", "mutagen.aiff", "yandex_music", "ytmusicapi", "miniaudio",
    "numpy", "PIL.Image", "pyloudnorm", 'scipy', 'scipy.signal', "sqlite3",
    "watchdog.observers.inotify", "watchdog.events", "bottle", "secretstorage",
    "cryptography.fernet", "socks",
]
for package in ("yt_dlp", "yt_dlp_ejs", "keyring.backends", "dbus_next", "jeepney"):
    hiddenimports.extend(collect_submodules(package))

binaries = [(str(path), "bin") for path in tools.values()]
binaries.extend(collect_dynamic_libs("curl_cffi"))

a = Analysis(
    [str(ROOT / "main.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest", "PyQt5", "PySide2", "PySide6",
              "webview.platforms.winforms", "webview.platforms.gtk", "clr", "pythonnet"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="NeDotify", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NeDotify")
