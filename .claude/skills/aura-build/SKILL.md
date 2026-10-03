---
name: aura-build
description: Package NeDotify into NeDotify.exe and the Inno Setup installer. Use when asked to build, package, ship a release, produce an installer, or when a change might break frozen mode (asset paths, sys._MEIPASS, hidden imports, bundled data files).
---

# Packaging NeDotify

## Full installer build

Two sequential steps; the second aborts the build if the first failed:

1. `pyinstaller setup_pyinstaller.spec` → `dist\NeDotify.exe`
2. `iscc installer.iss` → `dist\NeDotify_Setup.exe`

`installer.iss` is the **only** installer source: it owns shortcuts, the
HKCU autostart `Run` value and the uninstaller. There is no PyInstaller-built
GUI installer and no second, custom uninstaller — that pipeline was deleted
because it produced three byte-identical setup exes and an uninstaller that
competed with Inno Setup's.

A full build is slow and rewrites `build/` and `dist/`. For a spec-only
iteration: `& ".venv\Scripts\python.exe" -m PyInstaller --clean setup_pyinstaller.spec`.

## Frozen-mode rules

- Resolve every static asset (icons, `ui/web_new/**`, templates) through
  `sys._MEIPASS` when frozen and `os.path.dirname(__file__)` in source mode.
  A path that works in `python main.py` and breaks in the exe is the single
  most common packaging regression here.
- New runtime files (JS, CSS, HTML, `.env.example`, icons) must be added to the
  `datas` list in `setup_pyinstaller.spec`, not just dropped in the tree.
- New dependencies often need `hiddenimports` — `yt-dlp`, `miniaudio`,
  `pythonnet`/`clr_loader`, `pystray` and `yandex_music` all pull in modules
  PyInstaller cannot see statically. Verify by launching the built exe, not by
  a clean build log.
- The WebView2 runtime pin in `main.py` applies to the frozen app too; the
  pinned folder is a machine path, not bundled.

## Before shipping

Run the test suite (see `aura-test`) and launch `dist/NeDotify.exe` at least
once — playback, search and a download — since asset and hidden-import
breakage only shows at runtime. Do not commit `dist/` or `build/` artifacts.
