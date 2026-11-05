# Linux verification

Native target: Ubuntu 24.04 x86_64, Python 3.12, Qt/PyQt6 WebEngine,
session D-Bus, audio service, X11 and Wayland sessions. Native execution is
**pending** on the Windows authoring host (WSL is not installed).

## Automated checks

Run `python -m pytest` from this checkout, using its Linux venv. Shared fixtures
redirect HOME/USERPROFILE before collection and give each test its own profile.
Keep provider mocks for deterministic regressions. `-m network` is a separate
opt-in run; its failures must not be folded into mocked-provider results.

`docs/validation/pytest-windows-host.xml` records available host checks:
- Total: 2947 (2946 executed, 1 deselected)
- Passed: 2941 (100% of applicable suite)
- Failed: 0
- Skipped: 5 (Windows-only signing fixtures)
- Duration: 114.12s
POSIX locks, D-Bus sessions, Linux symlinks and actual GUI rendering need the
native commands below; skips are not successful native checks.

Historical `test_visual_ui`, `test_ui_adversarial_stress` and
`test_lifecycle_stress` target an old GTK process with global `/tmp` files,
disabled sandbox and unauthenticated `/__aura_eval`. They remain as historical
source but are excluded from collection. They are replaced by the protected
native Qt runner, current player/UI contracts and Linux lock tests.
Windows Inno/Authenticode tests are not Linux packaging checks. In-memory
WinAPI fixtures remain runnable where they exercise shared regression logic.

## Source and package GUI smoke

```bash
.venv/bin/python tools/validate_linux.py --output reports/native-source
bash build_linux.sh
.venv/bin/python tools/validate_linux.py \
  --executable dist/NeDotify/NeDotify --output reports/native-package
```

The runner launches the real entry point in a marked temporary HOME; it never
resets the user's profile. It waits for bridge acknowledgement, switches both
presentations, navigates home/search/library/player/profile/settings, waits
for fonts/images, captures the actual Qt widget on the Qt thread, reports JS
errors, and checks process exit. Fixture tracks are silent local WAV files.
It does not certify audible sound, live providers, desktop interactions or
every menu/dialog. The report says so explicitly. Chromium sandbox is retained.
No debug/eval HTTP endpoint is added.

For an unattended smoke: `dbus-run-session -- xvfb-run -a -s '-screen 0
1440x1000x24' .venv/bin/python tools/validate_linux.py --output reports/native-source`.
This is Linux/Xvfb evidence, not real Wayland or audio-device evidence.

## Manual native acceptance (required before declaring parity complete)

Use a separate temporary account/profile with copies of legacy settings/DB and
test downloads. Save distro, kernel, session type, Qt/Python/tool versions,
commands, screenshots and actual failures to the report directory.

1. Source and package: visible launch, second launch, bridge readiness,
   close-to-tray/quit, SIGTERM, restart; no orphan audio or stuck workers.
2. Both styles: home, search, library, favorites, playlists, artist, profile,
   settings, onboarding and setup. Open queue, context menus, import/export,
   metadata edit, errors, download panel and first-run states. Capture each.
3. Check Cyrillic fonts/artwork, wheel and keyboard scroll, focus traversal,
   reduced motion, 100%/150%/200% scale, minimum window size, resize/drag,
   maximize, always on top, full player and mini-player.
4. Per live provider: record authentication/region, query and result IDs;
   play, pause, seek, next/previous, repeat/shuffle, queue restore. Confirm
   actual sound and proxy activity. Spotify metadata is not a Spotify stream.
5. Download a track and a playlist: progress/cancel/retry/resume, quality,
   processing, covers/tags. Disconnect network and play the downloaded files.
6. Add favorites, import folders/playlists, export, edit metadata, restart;
   verify original provider and saved paths/settings survive migration.
7. Daily mixes, discovery modes, recommendation explanations, dislikes/hidden
   artists, playlist/favorites recommendations and continuous wave refill.
8. Synchronized lyrics + fallbacks/translation, EQ presets/effects, crossfade,
   visualizer and output selection. Judge audio by sound, not solely by UI.
9. Session D-Bus: `playerctl -l`, `playerctl -p nedotify play-pause`, next/seek,
   metadata/state changes. Test media keys, tray, notifications, autostart,
   Discord and compositor shortcuts on X11 and Wayland.
10. Install/update/uninstall tar and Debian packages on the declared baseline;
    check rollback and preserved temporary library/downloads/secrets.

## Platform differences to record

- Wayland controls absolute positioning/topmost/global shortcut policy. Native
  Qt gestures are used where possible; compositor bindings provide media
  shortcuts via MPRIS.
- A desktop without a tray host cannot display a tray icon. GNOME may require
  its AppIndicator extension. Quit/restore must still be tested.
- Secret Service/KWallet requires an accessible session; private Fernet storage
  is the encrypted fallback. Back up its key with the profile. Windows DPAPI
  ciphertext requires reauthentication; preserve original values.
- `tpws` handles application TCP through SOCKS; system UDP/QUIC/Discord voice
  needs separately configured privileged `nfqws`.
- Native package compatibility is declared only for the tested distro/arch;
  PyInstaller is not a Windows-to-Linux cross compiler.
