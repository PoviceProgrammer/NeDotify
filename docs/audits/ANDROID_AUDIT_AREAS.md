# Android audit area map — NeDotify (2026-10-19)

Common brief: `docs/audits/ANDROID_AUDIT_CONTEXT.md` — **read it first**.

Every primary area gets **exactly two** independent reviewers:
**A** = Correctness & Reliability · **B** = Architecture, Security & Performance.
Both receive the same area and the same brief; they never see each other's
output before finishing, so their conclusions are independent by construction.

## Primary areas (27 areas → 54 primary review tasks)

| ID | Area | Primary files |
|---|---|---|
| AN-01 | App shell & runtime lifecycle | `NeDotifyApp.kt`, `MainActivity.kt`, `AndroidManifest.xml`, `res/**` |
| AN-02 | ViewModel orchestration & app state machine | `ui/MusicViewModel.kt`, `ui/PlaybackPreparation.kt`, `ui/PlaybackErrors.kt` |
| AN-03 | MediaSession service: commands, restore, autoplay, offline refresh | `player/PlaybackService.kt` |
| AN-04 | Dual-deck player, crossfade, gain, audio runtime | `player/DualDeckPlayer.kt`, `player/CrossfadePolicy.kt`, `player/OutputGain.kt`, `player/AudioRuntime.kt` |
| AN-05 | Queue selection, pending-selection gate, mutation guard, focus state | `player/QueueSelection.kt`, `player/PendingSelectionGate.kt`, `player/PlaybackMutation.kt`, `player/PlaybackFocusState.kt`, `player/SessionPlayerBridge.kt` |
| AN-06 | Room persistence: entities, DAO, database, repository | `data/Models.kt`, `data/LibraryRepository.kt`, `app/schemas/**`, `data/LocalAudioMetadata.kt`, `data/LocalImportBatch.kt`, `data/LocalImportTitle.kt` |
| AN-07 | Backup codec, merge, backup storage | `data/BackupCodec.kt`, `data/BackupMerge.kt`, `data/LibraryBackupStorage.kt` |
| AN-08 | Desktop library import & converter | `data/DesktopLibraryConverter.kt`, `data/DesktopLibraryImport.kt` |
| AN-09 | Provider connections, PKCE, secure token store, provider HTTP | `data/ProviderConnections.kt`, `data/AuthPkce.kt`, `data/SecureProviderStore.kt`, `data/ProviderHttp.kt` |
| AN-10 | Catalog providers (Spotify / Yandex) & parsers | `data/CatalogProviders.kt`, `data/YandexDownloadInfo.kt` |
| AN-11 | Source resolution, stream cache, signed-URL expiry, deadlines, JSON | `data/Sources.kt`, `data/StreamCache.kt`, `data/SignedUrlExpiry.kt`, `data/SourceDeadline.kt`, `data/SourceJson.kt`, `data/OnlineSource.kt` |
| AN-12 | Search aggregation & catalog matcher | `data/SearchAggregate.kt`, `data/CatalogMatcher.kt` |
| AN-13 | Lyrics cascade, lyrics data, lyrics disk cache | `data/LyricsCascade.kt`, `data/LyricsData.kt`, `data/LyricsDiskCache.kt` |
| AN-14 | Discovery, smart rules, listening reports | `data/DiscoveryController.kt`, `data/DiscoveryEngine.kt`, `data/SmartRules.kt`, `data/ListeningReports.kt` |
| AN-15 | Downloads: worker, manager, storage, keys, offline media source | `downloads/TrackDownloadWorker.kt`, `downloads/Downloads.kt`, `downloads/DownloadStorage.kt`, `downloads/DownloadKeys.kt`, `downloads/OfflineSources.kt` |
| AN-16 | Preferences (DataStore), profile settings, audio settings store | `data/Preferences.kt`, `data/ProfileSettings.kt`, `data/AudioSettings.kt`, `data/AudioSettingsStore.kt` |
| AN-17 | UI shell: navigation, design system, home | `ui/MusicApp.kt`, `ui/Design.kt`, `ui/HomeScreen.kt` |
| AN-18 | UI player screen & mini player | `ui/PlayerScreen.kt`, `ui/MiniPlayer.kt` |
| AN-19 | UI library, browse components, catalog browser, downloads screen, desktop import controls | `ui/LibraryScreen.kt`, `ui/BrowseComponents.kt`, `ui/CatalogBrowser.kt`, `ui/DownloadsScreen.kt`, `ui/DesktopImportControls.kt` |
| AN-20 | UI search & discovery controls | `ui/SearchScreen.kt`, `ui/DiscoveryControls.kt` |
| AN-21 | UI profile, settings, appearance, audio settings controls | `ui/ProfileScreen.kt`, `ui/ProfileComponents.kt`, `ui/SettingsScreen.kt`, `ui/AudioSettingsControls.kt` |
| AN-22 | UI connections & backup controls | `ui/ConnectionsControls.kt`, `ui/BackupControls.kt` |
| AN-23 | Build config, dependencies, lint, SDK levels, packaging | `android/build.gradle`, `android/app/build.gradle`, `android/settings.gradle`, `android/gradle.properties`, `android/gradle/wrapper/*`, `android/verify.ps1` |
| AN-24 | Android unit test suite (JVM) — coverage & test quality | `app/src/test/**` |
| AN-25 | Android instrumentation test suite — coverage & test quality | `app/src/androidTest/**` |
| AN-26 | Desktop-parity oracle: backup format, library DB schema, history semantics | `core/database.py`, `core/api.py`, `core/listening.py`, `services/smart_playlists.py`, `services/listening_comparison.py` (repo root) |
| AN-27 | Docs & porting-status consistency vs code; prior review artifact integrity | `android/PORTING_STATUS.md`, `android/review/**`, `android/AGENTS.md`, `AGENTS.md` |

## Cross-module integration areas (8 areas → 16 integration tasks, stage 5)

| ID | Scenario |
|---|---|
| XI-01 | MediaSession ↔ ViewModel ↔ Compose state consistency (queue, position, play state, error surfacing) |
| XI-02 | Track resolution → `ResolvingDataSource` → HLS/progressive playback → error → recovery end-to-end |
| XI-03 | Download lifecycle end-to-end: enqueue → WorkManager → storage → Room → offline playback |
| XI-04 | Provider auth lifecycle: PKCE → redirect → secure store → API → logout / token expiry / 401 |
| XI-05 | Offline mode end-to-end: toggle → queue source refresh → pause → downloads → lyrics → search |
| XI-06 | App lifecycle & process death: queue restore, `SavedStateHandle`, configuration change, service restart |
| XI-07 | Backup round-trip & desktop import: export → inspect → merge → restore → playable afterwards |
| XI-08 | Rapid user interaction & concurrency: fast next/next, simultaneous play/pause/next, queue mutation during playback |

## Coverage accounting

Every file under `android/app/src/main/java/ru/nedotify/app/` appears in at
least one primary area. Every file under `android/app/src/test/` and
`app/src/androidTest/` appears in AN-24 / AN-25. `AndroidManifest.xml` and
`res/**` are covered by AN-01 and cross-checked by AN-23. Build files are
covered by AN-23. The Python desktop tree is covered by AN-26 as a parity
oracle and by AN-07 / AN-09 / AN-10 / AN-11 as the reference for the shared
contracts.
