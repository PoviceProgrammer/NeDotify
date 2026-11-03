# -*- mode: python ; coding: utf-8 -*-
"""
NeDotify - PyInstaller Build Specification
Run: pyinstaller setup_pyinstaller.spec

The shared web_new_v2 UI and its optional MACos_ui presentation pack are bundled.
"""

import glob
import os
import sys
import shutil
from pathlib import Path

ROOT = SPECPATH
sys.path.insert(0, ROOT)

from PyInstaller.utils.hooks import collect_data_files
from tools.packaging.native_manifest import (
    release_mode_from_environment,
    validate_native_inputs,
)

block_cipher = None


def _is_ui_cover_cache(path: str) -> bool:
    """True for a runtime album-art cache under any ui/*/covers/ tree.

    Runtime album-art files must not become installed resources. Matching
    '/covers/' inside 'ui/' handles both separators and cannot match a
    directory that merely starts with "covers".
    """
    norm = '/' + path.replace('\\', '/').lstrip('/')
    return '/ui/' in norm and '/covers/' in norm


ui_root = Path(ROOT) / 'ui' / 'web_new_v2'


def _collect_ui_datas(ui_root):
    datas = []
    for source in ui_root.rglob('*'):
        if not source.is_file() or _is_ui_cover_cache(str(source)):
            continue
        rel = source.relative_to(ui_root)
        if (rel.parts[:2] == ('assets', 'backgrounds')
                and source.suffix.lower() in {'.jpg', '.jpeg'}):
            continue
        if (rel.parts[:2] == ('assets', 'backgrounds')
                and source.name.lower() == 'sources.json'):
            continue
        # PyInstaller's second data field is a directory, not a filename.
        datas.append((str(source), (Path('ui/web_new_v2') / rel.parent).as_posix()))
    return datas


ui_datas = _collect_ui_datas(ui_root)

extra_datas = [
    (os.path.join(ROOT, 'licenses'), 'licenses'),
    (os.path.join(ROOT, 'ui', 'MACos_ui'), 'ui/MACos_ui'),
    (os.path.join(ROOT, 'icon.ico'), '.'),
] + ui_datas + collect_data_files('ytmusicapi')
extra_datas.extend(validate_native_inputs(
    ROOT, release_mode=release_mode_from_environment()))

# curl_cffi's wheel stores its native DLLs beside the package. Its import hook
# calls os.add_dll_directory(parent-of-package / "curl_cffi.libs"), so preserve
# that sibling layout in the frozen bundle.
curl_libs = os.path.join(sys.prefix, 'Lib', 'site-packages', 'curl_cffi.libs')
extra_binaries = [(dll, 'curl_cffi.libs') for dll in glob.glob(os.path.join(curl_libs, '*.dll'))]
ffprobe_bin = shutil.which('ffprobe') or (os.path.join(ROOT, 'ffprobe.exe') if os.path.isfile(os.path.join(ROOT, 'ffprobe.exe')) else None)
if ffprobe_bin and os.path.isfile(ffprobe_bin):
    extra_binaries.append((ffprobe_bin, '.'))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=extra_binaries,
    datas=extra_datas,
    hiddenimports=[
        'webview',
        'pypresence',
        'requests',
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen.mp4',
        'mutagen.flac',
        'mutagen.oggvorbis',
        'mutagen.oggopus',
        'mutagen.wave',
        'mutagen.asf',
        'mutagen.aiff',
        'yt_dlp',
        'yandex_music',
        'ytmusicapi',
        'miniaudio',
        'numpy',
        'pystray',
        'PIL',
        'PIL.Image',
        'pyloudnorm',
        'scipy',
        'scipy.signal',
        'sqlite3',
        'clr',
        'pythonnet',
        'watchdog',
        'watchdog.observers',
        'watchdog.events',
        'bottle',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pytest',
        '_pytest',
        'pydoc',
        'PyQt6',
        'vlc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Never ship runtime UI cover caches (see _is_ui_cover_cache).
a.datas = [d for d in a.datas if not _is_ui_cover_cache(d[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NeDotify',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX on a music-downloader exe trips antivirus heuristics and can break WebView2 DLL loading
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --noconsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'icon.ico'),
)
