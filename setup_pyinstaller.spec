# -*- mode: python ; coding: utf-8 -*-
"""
NeDotify - PyInstaller Build Specification
Run: pyinstaller setup_pyinstaller.spec

Both UI trees are still bundled (main.py picks web_new_v2 by default and
web_new only with --v1), so nothing here may be removed while that flag lives.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None


def _is_ui_cover_cache(path: str) -> bool:
    """True for a runtime album-art cache under any ui/*/covers/ tree.

    web_new/covers/ and web_new_v2/covers/ are written by the proxy/cover
    endpoints while the app runs. The old filter matched the literal
    'web_new/covers/', which is not a substring of 'web_new_v2/covers/' - so the
    active UI's cover cache was shipped inside the exe (it is the directory that
    actually grows during normal use). Matching '/covers/' inside 'ui/' catches
    every current and future variant, both separators, and cannot match a
    directory that merely starts with "covers".
    """
    norm = '/' + path.replace('\\', '/').lstrip('/')
    return '/ui/' in norm and '/covers/' in norm


extra_datas = [('ui/web_new', 'ui/web_new'), ('ui/web_new_v2', 'ui/web_new_v2')] + collect_data_files('ytmusicapi')
for extra_folder in ['zapret', 'bin']:
    if os.path.exists(extra_folder):
        extra_datas.append((extra_folder, extra_folder))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
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

# Never ship the runtime cover caches of either UI tree (see _is_ui_cover_cache).
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
    icon='icon.ico',
)
