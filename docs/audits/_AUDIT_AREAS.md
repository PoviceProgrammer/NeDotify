# Audit area map — NeDotify full-project audit

Every area gets **two** independent reviewers: **A** = Correctness & Reliability,
**B** = Architecture, Security & Performance.

Common brief: `docs/audits/_AUDIT_CONTEXT.md` (read it first).

| ID | Area | Primary files |
|---|---|---|
| AR-01 | Process bootstrap, startup/shutdown, packaging | `main.py`, `setup_pyinstaller.spec`, `installer.iss`, `requirements.txt`, `requirements-dev.txt`, `run_tests.py`, `pytest.ini` |
| AR-02 | AppCore wiring & subsystem lifecycle | `core/app.py`, `core/session.py`, `core/listening.py`, `core/plugins.py` |
| AR-03 | Bridge core: init, `_emit`, SSRF guard, error logging, offline interception | `core/api.py` lines 1-520 |
| AR-04 | Bridge window management: mini-player, resize, drag, snap, geometry, maximize | `core/api.py` lines 514-1160 + `core/snap_layouts.py` |
| AR-05 | Bridge playback, queue ops, listening, volume, hotkey-affecting settings | `core/api.py` lines 1161-2080 |
| AR-06 | Bridge search, catalog, library listing, favorites, downloads listing | `core/api.py` lines 2077-2360 + `core/api.py` 2727-2733 |
| AR-07 | Bridge playlists, playlist import/export, tags, duplicate handling, local files | `core/api.py` lines 2362-2750, 3399-3460, 3876-4021 |
| AR-08 | Bridge settings, onboarding, autostart, subscription, storage/quota, equalizer | `core/api.py` lines 2750-3195, 4021-4110 |
| AR-09 | Bridge lyrics, cover fetch, home feed, profile, waveform | `core/api.py` lines 3192-3595 |
| AR-10 | Bridge cache cleaning, prefetch, batch downloads, zapret, discord, offline mode, smart playlists | `core/api.py` lines 3595-4228 |
| AR-11 | Loopback HTTP stream proxy | `core/proxy.py` |
| AR-12 | SQLite persistence layer | `core/database.py` |
| AR-13 | Background downloader, download state, transfer control | `core/downloader.py`, `core/download_store.py`, `core/download_transfer.py` |
| AR-14 | Settings manager & hotkey table | `core/settings.py` |
| AR-15 | Stream resolution & playback recovery | `core/resolver.py`, `core/playback_recovery.py`, `core/offline.py`, `utils/stream_urls.py` |
| AR-16 | Tray, legacy asset routes, user-facing error mapping | `core/tray.py`, `core/ui_assets.py`, `core/user_errors.py` |
| AR-17 | Audio engine & playback queue | `audio/engine.py`, `audio/queue.py` |
| AR-18 | Service base class, track resolver, music matching, artist identity | `services/base_service.py`, `services/track_resolver.py`, `services/music_matching.py`, `services/artist_identity.py` |
| AR-19 | YouTube provider | `services/youtube_service.py` |
| AR-20 | SoundCloud provider | `services/soundcloud_service.py` |
| AR-21 | Yandex / VK / Spotify / Last.fm / iTunes providers | `services/yandex_service.py`, `services/vk_service.py`, `services/spotify_service.py`, `services/lastfm_service.py`, `services/itunes_gateway.py` |
| AR-22 | Lyrics services | `services/lyrics_service.py`, `services/lyrics_lookup.py`, `services/lyrics_cache.py` |
| AR-23 | Recommendations & taste profile | `services/recommendation_service.py`, `services/taste_profile.py`, `core/services/recommendation.py` |
| AR-24 | Catalog, artist, playlist-import, smart-playlist services | `services/catalog_service.py`, `services/artist_service.py`, `services/playlist_import_service.py`, `services/smart_playlists.py` |
| AR-25 | Loudness scan, audio fingerprint, watchdog, listening comparison | `services/lufs_scanner.py`, `services/audio_fingerprint_service.py`, `services/watchdog_service.py`, `services/listening_comparison.py` |
| AR-26 | Zapret (network bypass) & Discord RPC | `services/zapret_service.py`, `core/services/discord_rpc.py` |
| AR-27 | Utility modules | `utils/cache_manager.py`, `utils/file_scanner.py`, `utils/search_query.py`, `utils/stream_urls.py`, `utils/tag_parser.py`, `utils/url_safety.py` |
| AR-28 | UI document, bootstrap, event bus, shared utilities | `ui/web_new_v2/index.html`, `ui/web_new_v2/js/boot.js`, `js/main.js`, `js/events.js`, `js/pages.js`, `js/debug.js`, `js/contextmenu.js`, `js/efficiency.js`, `js/utils.js` |
| AR-29 | UI player, equalizer, queue view, visualizer | `ui/web_new_v2/js/player.js`, `js/equalizer.js`, `js/queue.js`, `js/visualizer.js` |
| AR-30 | UI settings, hotkeys, style picker, feature controls, window resize | `ui/web_new_v2/js/settings.js`, `js/settings-view.js`, `js/hotkeys.js`, `js/ui-style.js`, `js/feature-controls.js`, `js/window-resize.js`, `js/appearance-assets.js` |
| AR-31 | UI search, discovery, home, particles | `ui/web_new_v2/js/search.js`, `js/search-discovery.js`, `js/home.js`, `js/home-shell.js`, `js/particles.js` |
| AR-32 | UI library, downloads, smart playlists, lyrics, artist profile, profile, onboarding | `ui/web_new_v2/js/library.js`, `js/library-view.js`, `js/downloads-view.js`, `js/smart-playlists.js`, `js/lyrics.js`, `js/artist_profile.js`, `js/profile.js`, `js/profile-comparison.js`, `js/onboarding.js` |
| AR-33 | UI styling: themes, tokens, component CSS, legacy CSS pack | `ui/web_new_v2/css/**`, `ui/MACos_ui/**` |
| AR-34 | Android data layer | `android/app/src/main/java/ru/nedotify/app/data/**` |
| AR-35 | Android playback layer | `android/app/src/main/java/ru/nedotify/app/player/**` |
| AR-36 | Android UI, downloads, app shell, manifest & build config | `android/app/src/main/java/ru/nedotify/app/ui/**`, `.../downloads/**`, `MainActivity.kt`, `NeDotifyApp.kt`, `AndroidManifest.xml`, `android/app/build.gradle` |
| AR-37 | Test suite | `tests/**` |
| AR-38 | Tooling: performance bench & visual guard | `tools/bench/**`, `tools/visual_guard/**` |

## Cross-module integration checks (stage 5)

| ID | Scenario |
|---|---|
| XI-01 | Track resolution → proxy → frontend playback: `play_track` → `_resolve_track` → `StreamResolver` → `core/proxy.py` → `ui/.../player.js` `loadAudioSource` |
| XI-02 | Download → library → playback: `core/downloader.py` → `download_complete` event → `ui/.../events.js` → `core/database.py` → queue |
| XI-03 | Settings round-trip: `core/settings.py` defaults ↔ `ui/.../settings.js` ↔ `AppApi.get_settings/save_setting` ↔ hotkey mirror |
| XI-04 | Listening telemetry: `AppApi.report_position` → `core/listening.py` → `core/database.py` → `services/listening_comparison.py` → UI profile |
| XI-05 | Search fan-out: `AppApi.search` → `BaseMusicService.submit` → provider services → `services/track_resolver.py` → cache |
| XI-06 | Lyrics cascade: `AppApi.get_lyrics` → `services/lyrics_service.py` → `lyrics_lookup.py` → `lyrics_cache.py` → UI lyrics view |
| XI-07 | App lifecycle: `main.py` → `AppCore` → `AppApi` → `cleanup()` on close, watchdog restart path, session save/restore |
| XI-08 | Recommendation loop: taste profile → recommendations → feedback → taste profile update |
| XI-09 | Offline mode across playback, library, proxy, downloads |
| XI-10 | Android ↔ desktop parity for the shared contracts (library DB schema, backup codec, source contracts) |
