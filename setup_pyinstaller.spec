# -*- mode: python ; coding: utf-8 -*-
"""
NeDotify - PyInstaller Build Specification
Run: pyinstaller setup_pyinstaller.spec
"""

import os

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

extra_datas = [('ui', 'ui')] + collect_data_files('ytmusicapi')
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
        'soundfile',
        'colorthief',
        'sqlite3',
        'zeroconf',
        'ifaddr',
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
    upx=True,
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
