# Windows → Linux parity — 2026-11-05

Reference: the current **working tree** of `../NeDotify_Windows`, including
uncommitted recommendation changes and new files. Windows, Android, archives,
existing virtual environments and user profiles are not modified.

## Current Validation Status (Host Python Test Suite)

- **Total Test Cases**: 2947 (2946 executed, 1 deselected)
- **Passed**: 2941 (100% of applicable tests)
- **Failed**: 0 (zero failures)
- **Skipped**: 5 (Windows-only Authenticode signing / kernel driver fixtures)
- **Test Report**: `docs/validation/pytest-windows-host.xml`
- **Source Inventory**: 227 identical, 38 adapted, 0 missing (`docs/windows-source-inventory.json`)
- **Adapted Legacy Suites**: 100% passing across all 9 suites (147/147 tests)
- **Platform Integration**: `core/linux_integration.py`, `core/mpris.py`, `core/secret_store.py`, `services/linux_zapret.py`, `linux_runtime.py` (14/14 tests passing)
- **Temporary-Copy Migration**: Verified on temporary copies; legacy schemas upgraded, secrets encrypted via Secret Service / Fernet, queues/playlists preserved.

**Work in progress. Native verification is pending.** This host runs Windows;
`wsl --list --verbose` reports that WSL is not installed. Windows pytest/Node
checks do not establish Linux launch, sound, desktop integration or packaging.
Old screenshots in this repository are historical, not evidence for this port.

The generated `windows-source-inventory.json` enumerates every reference product
file with its SHA-256, Linux counterpart and Python classes/methods. It covers
the actual filesystem rather than only committed files. A source-identical file
is evidence of code transfer, **not** evidence of native runtime behavior.

States: `WIP` = implementation in progress; `ported` = source present;
`adapted` = Linux implementation present; `tested` = named automated checks pass;
`pending native` = requires a real supported Linux desktop.

| Windows subsystem / complete scenarios | Implementation and Linux adaptation | Verification / status |
|---|---|---|
| Startup, single instance, bridge readiness, watchdog, bounded shutdown | `main.py`, `core/app.py`, `core/ui_server.py`; QtWebEngine, user-specific POSIX lock, signal handling | WIP; pending native |
| Explicit JS bridge surface, protected internals, events, thread safety | `core/bridge.py`, `core/api.py`; preserve PUBLIC_METHODS and event payloads | WIP; bridge + emit tests |
| Standard and macOS UI, every page, shared behavior | `ui/web_new_v2`, `ui/MACos_ui`; complete scoped presentation pack and shared modules | WIP; frontend asset graph + Node tests; pending native |
| Fonts, Cyrillic, icons, wallpapers, palettes, themes, glass, animation, particles, reduced motion | Complete static assets; Linux font fallbacks, preserved Linux particle fixes; sandbox stays enabled | WIP; CSS/resource tests; pending screenshots |
| Home, search, catalogue, artist profiles, albums, related releases | `home.js`, `search.js`, artist/catalogue services and API | WIP; search/catalogue/UI suites |
| Library, favorite tracks, playlists, sorting/filtering, virtualization | `library.js`, database and API; preserve provider metadata on downloads | WIP; database/library suites |
| Context menus, dialogs, toasts, loading/errors, keyboard/focus, scaling | Shared UI modules, regular + macOS presentation | WIP; Node tests; pending visual inspection |
| Six-step onboarding, live previews, completion migration, setup repair/cancel/update | `onboarding.js`, `core/setup_engine.py`; native Linux tools and paths | WIP; onboarding/setup tests; pending native |
| Normal/full/mini player, artwork, transport, volume, output selection | `player.js`, `audio/engine.py`; POSIX file routing, Qt WebAudio/media | WIP; player tests; pending live sound |
| Queue, seek, next/previous, shuffle/repeat, persisted session/autoplay | `audio/queue.py`, session/API + frontend queue/player | WIP; queue/session/restore tests |
| Prefetch, stream caching, gapless/crossfade, recovery, offline resolution | Resolver, engine, proxy, cache + dual HTML audio | WIP; resolver/cache/recovery/offline suites |
| Authenticated loopback audio proxy, ranges, HLS, URL validation, socket disconnects | Full current proxy, loopback token and file restrictions | WIP; proxy security/range/harness tests |
| YouTube, SoundCloud, Yandex, VK, Spotify metadata, Deezer/catalogue and fallback matching | Entire `services/` reference, TLS impersonation/EJS scripts, Linux tools | WIP; mocked provider suites; pending separate live checks |
| Search fan-out, smart search, cancellation, cache/single-flight, DNS/reconnect | Full services and `core/dns_fallback.py`; shared lock/pools retained | WIP; concurrency/search/DNS tests |
| Track/playlist/collection/bulk downloads, progress, pause/cancel/retry/resume | Full download manager + bridge + JS states | WIP; downloader/API/resume tests; pending live track + playlist |
| Quality/formats, FFmpeg processing, tags/covers, validation and atomic output | Downloader and provider processing; Linux executable permissions/paths | WIP; download processing/metadata tests |
| Auto-download favorites, restored queue, failed download recovery | Current settings, download manager and API | WIP; favorites/download tests |
| Local folder import/watch, scanning, offline playback | File scanner, watchdog, import/local library API; POSIX file URLs | WIP; scanner/offline suites; pending disconnected playback |
| Stream/cover/temp caches, size limits, cleanup, storage settings | Cache manager + settings + API; existing `~/.nedotify` kept | WIP; cache/storage suites |
| Playlist import/export (all current providers), metadata editing, covers, duplicates | Playlist import/export services, tag parser, database/API | WIP; imports/tags/duplicates suites |
| Profile, measured listening/history/statistics, comparisons, settings persistence | Current database migrations, measured listening + profile view | WIP; history/profile/settings suites |
| Recommendations, daily mixes, discoveries, taste, feedback, exclusions | Entire recommendation/taste/catalogue code | WIP; recommendation/signals/taste suites |
| Continuous wave, playlist/favorites recommendations, novelty modes, explanations | Includes all 2026-11-04 uncommitted/new Windows modules | WIP; continuous-wave/controls/playlist recommendation suites |
| Synchronized/plain lyrics, translations, rich/public fallbacks and matching | All current lyrics adapters, matching/upload recovery | WIP; lyrics suites; pending live lyrics |
| Equalizer, presets, DSP effects, LUFS/loudness, fingerprinting, visualizations | WebAudio modules + processing services; QtWebEngine media runtime | WIP; EQ/audio/UI tests; pending audible verification |
| Provider authorization, tokens, secrets, legacy settings migrations | Linux Secret Service through keyring; no new plaintext fallback | WIP; secret/settings tests; pending keyring session |
| In-app/global shortcuts, media keys, tray/close behavior | Qt tray; MPRIS on session D-Bus; compositor restrictions documented | WIP; platform/keybind tests; pending X11 + Wayland |
| Window controls, resize, maximize, mini-player, drag, always on top | Qt API/platform support; compositor-mediated Wayland operations | WIP; window contracts; pending desktop verification |
| Notifications and autostart | Linux desktop notifications and XDG autostart entry | WIP; temporary-profile platform tests; pending desktop |
| Discord Rich Presence, plugins, remaining integrations | Current Discord/plugin/service source; Linux IPC/platform paths | WIP; plugin tests; pending real client |
| Network bypass / Zapret controls and lifecycle | Linux nfqws/system service equivalent; never run Windows drivers or silently elevate | WIP; exact privilege/setup differences to document |
| App/tool setup, updates, cancellation, rollback and integrity | Native Linux assets/package flow, no Windows binary downloads | WIP; setup/update tests; pending native build |
| Build/install/update/uninstall, resources and runtime libraries | Linux PyInstaller onedir + desktop integration, reproducible native CI | WIP; packaging contracts; **native artifact not built** |
| Database/settings/download preservation and migrations | Keep existing profile and IDs; exercise migrations only on temporary copies | WIP; isolated DB/settings/migration tests |

## Required native acceptance evidence

Ubuntu 24.04 x86_64, a real desktop session (X11 and Wayland where applicable),
audio device/PipeWire or PulseAudio, unlocked Secret Service and network access:

- Source app and packaged app launch, visible window, bridge acknowledgement,
  clean shutdown and second-instance behavior.
- Both UI styles: home/search/library/favorites/playlist/artist/profile/settings,
  onboarding, queue, full/mini player, menus/dialogs, loading/errors; screenshots.
- Every provider: live search and available playback, seek/next/repeat/shuffle;
  retain network errors and authentication requirements as results.
- Live track + playlist downloads, progress/cancel/retry/recovery, tags/covers;
  disable network and play the downloaded tracks.
- Session restore, continuous wave, recommendations, import/favorites, synced
  lyrics, EQ/effects and persistence across restart.
- Tray, media keys/MPRIS, shortcuts, notifications, autostart, Discord, window
  resize/drag and minimum geometry, fonts/artwork/scroll/scale/focus.
- Install/update/uninstall the built package and verify existing temporary user
  data survives. Keep mocked-provider and live-network reports separate.

These acceptance items remain open until actual evidence is recorded.
