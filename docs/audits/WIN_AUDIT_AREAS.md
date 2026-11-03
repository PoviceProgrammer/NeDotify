# WIN Audit — Area Map (Windows desktop product)

Every area gets **two** independent reviewers: **A** = Correctness & Reliability,
**B** = Architecture, Security & Performance. They do not see each other's output.

Common brief: `docs/audits/WIN_AUDIT_CONTEXT.md` (read it FIRST).

Repo root: `C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main`
Scope: **Windows desktop only.** `android/` is out of scope.

All paths are relative to the repo root. Line numbers are physical 1-based lines.

| ID | Area | Primary files / ranges |
|---|---|---|
| WN-01 | Process bootstrap, startup/shutdown, packaging | `main.py` (584 L), `setup_pyinstaller.spec`, `installer.iss`, `requirements.txt`, `requirements-dev.txt`, `run_tests.py`, `pytest.ini` |
| WN-02 | AppCore wiring & subsystem lifecycle | `core/app.py` (586 L), `core/session.py`, `core/listening.py`, `core/plugins.py` |
| WN-03 | Bridge core: init, `_emit`, SSRF guard, error logging, offline interception | `core/api.py` L1–520 |
| WN-04 | Bridge window management: mini-player, resize, drag, snap, geometry, maximize | `core/api.py` L514–1160, `core/snap_layouts.py` |
| WN-05 | Bridge playback, queue ops, listening telemetry, volume | `core/api.py` L1161–2080 |
| WN-06 | Bridge search, catalog, library listing, favorites, downloads listing | `core/api.py` L2077–2362, L2727–2733 |
| WN-07 | Bridge playlists, import/export, tags, duplicates, local files | `core/api.py` L2362–2750, L3399–3462, L3876–4021 |
| WN-08 | Bridge settings, onboarding, autostart, subscription, storage/quota, equalizer | `core/api.py` L2750–3195, L4021–4110 |
| WN-09 | Bridge lyrics, cover fetch, home feed, artist profile, waveform | `core/api.py` L3192–3595 |
| WN-10 | Bridge cache cleaning, prefetch, batch downloads, zapret, discord, offline mode, smart playlists | `core/api.py` L3595–4228 |
| WN-11 | Loopback HTTP stream proxy | `core/proxy.py` (1334 L) |
| WN-12 | SQLite persistence layer | `core/database.py` (2489 L) |
| WN-13 | Background downloader, download state, transfer control | `core/downloader.py`, `core/download_store.py`, `core/download_transfer.py` |
| WN-14 | Settings manager & hotkey table | `core/settings.py` (589 L) |
| WN-15 | Stream resolution & playback recovery | `core/resolver.py`, `core/playback_recovery.py`, `core/offline.py`, `utils/stream_urls.py` |
| WN-16 | Tray, legacy asset routes, user-facing error mapping | `core/tray.py`, `core/ui_assets.py`, `core/user_errors.py` |
| WN-17 | Audio engine & playback queue | `audio/engine.py`, `audio/queue.py` |
| WN-18 | Service base class, track resolver, music matching, artist identity | `services/base_service.py`, `services/track_resolver.py`, `services/music_matching.py`, `services/artist_identity.py` |
| WN-19 | YouTube provider | `services/youtube_service.py` (1037 L) |
| WN-20 | SoundCloud provider | `services/soundcloud_service.py` (971 L) |
| WN-21 | Yandex / VK / Spotify / Last.fm / iTunes providers | `services/yandex_service.py`, `services/vk_service.py`, `services/spotify_service.py`, `services/lastfm_service.py`, `services/itunes_gateway.py` |
| WN-22 | Lyrics services | `services/lyrics_service.py`, `services/lyrics_lookup.py`, `services/lyrics_cache.py` |
| WN-23 | Recommendations & taste profile | `services/recommendation_service.py`, `services/taste_profile.py`, `core/services/recommendation.py` |
| WN-24 | Catalog, artist, playlist-import, smart-playlist services | `services/catalog_service.py`, `services/artist_service.py`, `services/playlist_import_service.py`, `services/smart_playlists.py` |
| Wn-25 | Loudness scan, audio fingerprint, watchdog, listening comparison | `services/lufs_scanner.py`, `services/audio_fingerprint_service.py`, `services/watchdog_service.py`, `services/listening_comparison.py` |
| WN-26 | Zapret (network bypass) & Discord RPC | `services/zapret_service.py` (1328 L), `core/services/discord_rpc.py` |
| WN-27 | Utility modules | `utils/cache_manager.py`, `utils/file_scanner.py`, `utils/search_query.py`, `utils/stream_urls.py`, `utils/tag_parser.py`, `utils/url_safety.py` |
| WN-28 | UI document, bootstrap, event bus, shared utilities | `ui/web_new_v2/index.html` (2314 L), `js/boot.js`, `js/main.js`, `js/events.js`, `js/pages.js`, `js/debug.js`, `js/contextmenu.js`, `js/efficiency.js`, `js/utils.js` |
| WN-29 | UI player, equalizer, queue view, visualizer | `js/player.js` (2489 L), `js/equalizer.js`, `js/queue.js`, `js/visualizer.js` |
| WN-30 | UI settings, hotkeys, style picker, feature controls, window resize | `js/settings.js` (3111 L), `js/settings-view.js`, `js/hotkeys.js`, `js/ui-style.js`, `js/feature-controls.js`, `js/window-resize.js`, `js/appearance-assets.js` |
| WN-31 | UI search, discovery, home, particles | `js/search.js` (1122 L), `js/search-discovery.js`, `js/home.js`, `js/home-shell.js`, `js/particles.js` |
| WN-32 | UI library, downloads, smart playlists, lyrics, artist profile, profile, onboarding | `js/library.js`, `js/library-view.js`, `js/downloads-view.js`, `js/smart-playlists.js`, `js/lyrics.js`, `js/artist_profile.js`, `js/profile.js`, `js/profile-comparison.js`, `js/onboarding.js` |
| WN-33 | UI styling: themes, tokens, component CSS, legacy CSS pack | `ui/web_new_v2/css/**`, `ui/MACos_ui/**` |
| WN-34 | Test suite | `tests/**` (~100 files) |
| WN-35 | Tooling: performance bench & visual guard | `tools/bench/**`, `tools/visual_guard/**`, `tools/check_lock_nesting.py`, `tools/check_shadow_imports.py` |

**35 areas × 2 independent reviewers = 70 primary review tasks.**

## Cross-module integration checks (stage 5) — WX

Each scenario also gets **two** independent reviewers (A / B).

| ID | Scenario |
|---|---|
| WX-01 | Track resolution → proxy → frontend playback: `play_track` → `_resolve_track` → `StreamResolver` → `core/proxy.py` → `js/player.js` `loadAudioSource` |
| WX-02 | Download → library → playback: `core/downloader.py` → `download_complete` event → `js/events.js` → `core/database.py` → queue |
| WX-03 | Settings round-trip: `core/settings.py` defaults ↔ `js/settings.js` ↔ `AppApi.get_settings/save_setting` ↔ hotkey mirror |
| WX-04 | Listening telemetry: `AppApi.report_position` → `core/listening.py` → `core/database.py` → `services/listening_comparison.py` → UI profile |
| WX-05 | Search fan-out: `AppApi.search` → `BaseMusicService.submit` → provider services → `services/track_resolver.py` → cache |
| WX-06 | Lyrics cascade: `AppApi.get_lyrics` → `services/lyrics_service.py` → `lyrics_lookup.py` → `lyrics_cache.py` → UI lyrics view |
| WX-07 | App lifecycle: `main.py` → `AppCore` → `AppApi` → `cleanup()` on close, watchdog restart path, session save/restore |
| WX-08 | Recommendation loop: taste profile → recommendations → feedback → taste profile update |
| WX-09 | Offline mode across playback, library, proxy, downloads |
| WX-10 | Rapid track switching / concurrent play-pause-next commands → queue + engine + proxy state consistency |
| WX-11 | Network loss during playback and recovery after connectivity returns (stream expiry + re-resolve) |
| WX-12 | Background/foreground, minimise-to-tray, mini-player, and app restart state continuity |
