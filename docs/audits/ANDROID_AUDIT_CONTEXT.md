# Shared context — NeDotify Android full-project audit (2026-10-19)

**Read this file completely before reviewing.** It is the common brief for every
reviewer agent. Your area prompt follows it.

## 1. What you are auditing

**NeDotify** is a music player. This audit's primary subject is the **Android
port** — a native Kotlin / Jetpack Compose / Media3 / Room application under
`android/`. The repository also contains the older **Windows desktop** app
(Python 3.14 + pywebview + vanilla JS) at the repo root. The desktop app is an
**oracle / reference**, not the audit subject (see §5).

The Android port is **not committed to git** (`git status` shows `?? android/`),
so there is no diff to review. Review the code **as it stands**.

Repo root: `C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main`
Android module: `android/app/`

## 2. Android repository map

```
android/
  build.gradle, settings.gradle, gradle.properties, gradle/wrapper/   build config
  app/build.gradle                                                     deps, SDK levels, lint
  app/src/main/AndroidManifest.xml                                     permissions, services, intent filters
  app/src/main/res/                                                    drawable, values/styles.xml, xml/backup_rules.xml, xml/data_extraction_rules.xml
  app/src/main/java/ru/nedotify/app/
    NeDotifyApp.kt          Application: DI, repository, downloads, audio cache, ioScope
    MainActivity.kt         Activity: Compose host, intents, permissions, SAF pickers, notification channel
    data/                   models, Room DB, sources, providers, backup, lyrics, discovery, preferences
    player/                 PlaybackService (MediaSessionService), DualDeckPlayer, queue/gate/history helpers
    downloads/              WorkManager worker, download manager, storage, keys, offline media source
    ui/                     Compose screens, MusicViewModel, design system
  app/src/test/           JVM unit tests (40 files)
  app/src/androidTest/    instrumentation tests (14 files)
  app/schemas/            exported Room schemas (version 3)
  review/                 prior review artifacts, SHA256 snapshots, validation logs
  PORTING_STATUS.md       porting status / known gaps
  AGENTS.md               android-specific rules
```

Approx. 74 Kotlin main sources (~7 000 lines) + ~3 500 lines of tests.

### Key types and where they live

| Concern | File |
|---|---|
| Room entities, `LibraryDao`, `LibraryDatabase` (v3) | `data/Models.kt` |
| Repository facade over DAO + preferences + network | `data/LibraryRepository.kt` |
| `MusicNetwork` (OkHttp), `SoundCloudClient`, `InnerTubeClient`, `LyricsClient` | `data/Sources.kt` |
| Spotify / Yandex catalog clients + parsers | `data/CatalogProviders.kt` |
| Provider auth, token store, PKCE | `data/ProviderConnections.kt`, `data/AuthPkce.kt`, `data/SecureProviderStore.kt`, `data/ProviderHttp.kt` |
| Stream resolution + cache + signed-URL TTL | `data/StreamCache.kt`, `data/SignedUrlExpiry.kt`, `data/SourceDeadline.kt`, `data/SourceJson.kt`, `data/OnlineSource.kt` |
| Backup encode/decode/merge | `data/BackupCodec.kt`, `data/BackupMerge.kt`, `data/LibraryBackupStorage.kt` |
| Desktop library import | `data/DesktopLibraryConverter.kt`, `data/DesktopLibraryImport.kt` |
| Lyrics cascade | `data/LyricsCascade.kt`, `data/LyricsData.kt`, `data/LyricsDiskCache.kt` |
| Discovery / smart rules / reports | `data/DiscoveryController.kt`, `data/DiscoveryEngine.kt`, `data/SmartRules.kt`, `data/ListeningReports.kt` |
| Preferences (DataStore) / audio settings | `data/Preferences.kt`, `data/ProfileSettings.kt`, `data/AudioSettings.kt`, `data/AudioSettingsStore.kt` |
| `PlaybackService` (MediaSessionService) | `player/PlaybackService.kt` |
| Dual deck / crossfade | `player/DualDeckPlayer.kt`, `player/CrossfadePolicy.kt`, `player/OutputGain.kt`, `player/AudioRuntime.kt` |
| Queue selection / gates / history | `player/QueueSelection.kt`, `player/PendingSelectionGate.kt`, `player/SessionPlayerBridge.kt`, `player/PlaybackMutation.kt`, `player/PlaybackFocusState.kt`, `player/ListeningClock.kt`, `player/ListeningHistory.kt` |
| Downloads | `downloads/TrackDownloadWorker.kt`, `downloads/Downloads.kt`, `downloads/DownloadStorage.kt`, `downloads/DownloadKeys.kt`, `downloads/OfflineSources.kt` |
| ViewModel orchestration | `ui/MusicViewModel.kt` |
| Compose screens | `ui/*.kt` |

## 3. Non-negotiable contracts of this codebase

Taken from `AGENTS.md` (root), `android/AGENTS.md`, and the project's own docs.
Violating one is a finding. Implementing one in a way that provably does not
hold is **also** a finding.

1. **Player ownership stays in `MediaSessionService`** — not in a composable or
   Activity. A composable must not drive the player directly.
2. **Do not fetch stream URLs for the whole queue before playback starts.**
   Resolution is per-item and lazy.
3. **Minimum API 26.** SQLite SQL and resource attributes must work on API 26.
   `targetSdk`/`compileSdk` are 37, `minSdk` is 26.
4. **Actual listening time only.** Seeking, or a track's metadata duration, is
   not evidence of listening. `ListeningClock`/`ListeningHistory` must measure
   real elapsed playback.
5. **A partial streaming cache is never a completed offline download.** The
   download state machine must distinguish "downloaded" from "cached bytes".
6. **Never clear `~/.nedotify/` or alter the user's library.** (Desktop rule;
   applies to the Android port's equivalent — the user's own media store.)
7. **Player/player state and queue state must stay consistent** between the
   service, the ViewModel and the UI.
8. **No source file may be modified during this audit.** You are a reviewer.
9. **The user currently forbids building APKs.** Use `compileDebugKotlin`,
   `testDebugUnitTest`, `lintDebug`, `compileDebugAndroidTestKotlin` only.
   Never `assemble*`, `bundle*`, `package*`.
10. **`android/verify.ps1`** manages `local.properties` and a temp SDK alias
    and restores the original bytes. Prefer it over hand-rolled Gradle calls.

## 4. Ground rules for every reviewer

- **Read the real files.** Never assume contents. Use `read`, `grep`, `glob`,
  `shell` (PowerShell on Windows).
- **Do not modify any source file.** Scratch files under `%TEMP%` are fine;
  the repo tree is not.
- **Evidence is mandatory.** Every finding needs `path:line` plus a quoted
  snippet or a precise description of the code at those lines.
- **Trace call chains.** A defect inside a callee belongs to the area that owns
  the callee; a defect in how a caller uses it belongs to the caller's area.
  Do not double-report one root cause in two areas — cross-reference it and
  name the owning area.
- **CONFIRMED vs HYPOTHESIS.** A hypothesis must state exactly what evidence
  is missing and what would confirm it.
- **No style nits.** Naming, formatting, comment wording, "this could be
  nicer" — not findings. Do not propose refactoring for aesthetics.
- **No invented findings.** If an area is clean, say it is clean. A short
  report beats a padded one.
- **Platform differences are not defects.** Android and the desktop app
  legitimately differ. Only report a difference when it breaks a **stated
  contract** or the **user-visible behaviour** the contract promises.
- When running PowerShell, set
  `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` first, or Cyrillic
  output is mangled and you may misread the source.
- If you run Gradle, use `android/verify.ps1` (source-only tasks) and report
  the exact task list and exit code you observed. **Never report a test result
  you did not actually observe.**

## 5. The desktop app is an oracle, not the subject

The Windows desktop app (Python, repo root) implements the same product
features. Use it to answer "what is the intended behaviour of this feature?"
and to spot **silent divergence** — e.g. the backup file format, the Spotify /
Yandex API usage, the lyrics cascade order, the smart-playlist rule semantics,
the listening-report definition.

Desktop files most useful as references:
`core/database.py` (schema + history/listening semantics),
`core/api.py` (bridge methods, backup export/import),
`core/settings.py` (defaults),
`services/spotify_service.py`, `services/yandex_service.py`,
`services/youtube_service.py`, `services/soundcloud_service.py`,
`services/lyrics_service.py`, `services/smart_playlists.py`,
`services/listening_comparison.py`, `core/listening.py`.

A desktop-vs-Android difference is a finding only if the Android side
**silently** behaves worse or breaks a promised feature — e.g. a field is
dropped from the backup, an API field is interpreted differently, a rule
evaluates to a different result. If the difference is a deliberate,
documented platform decision, it is not a finding.

## 6. Prior review artifacts — treat as claims, not as truth

`android/review/` contains the results of a previous review round
(2026-10-18) and the fixes that followed:

- `received/REVIEW_A_2026-10-18.txt`, `received/REVIEW_B_2026-10-18.txt` —
  the two prior external review reports (raw).
- `REVIEW_RESOLUTION.md` — the table of "reported item → decision/fix".
- `BUGFIX_2026-10-19.md` — the later fix round.
- `VALIDATION.md`, `TEST_SUMMARY.json`, `FINAL_CHECKS.log` — build/test claims.
- `SOURCE_SHA256.txt` — the SHA256 snapshot of the audited source.

Two ways to use them:
1. **Do not blindly re-report a fixed item.** Check the current source. If the
   fix is genuinely present and holds, say so. If the fix is *incomplete or
   incorrect*, that is a fresh, high-value finding — say explicitly that it
   regresses or is only partially fixed.
2. **The open items in `REVIEW_RESOLUTION.md` §"Оставлено открытым"** are
   declared-unresolved. If you can resolve one with evidence, that is a
   valuable finding. If you find a *new* defect in an area those items touch,
   report it as new.

The claims in `VALIDATION.md` are the previous round's claims. Verify against
the current tree before repeating them.

## 7. Priority scale

- **P0 CRITICAL** — data loss/corruption, serious vulnerability, total failure
  of a core function.
- **P1 HIGH** — reproducible crash, broken important functionality, serious
  race condition, substantial resource leak.
- **P2 MEDIUM** — bug in a specific scenario, noticeable performance problem,
  unstable state handling.
- **P3 LOW** — non-critical defect, small implementation-quality issue, local
  optimisation.
- **ARCH** — architecture improvement *without* a proven defect. Report it in a
  separate section; never mix it into the defect list.

## 8. Required report format

Return your report as Markdown with exactly these sections:

```
## AREA <ID> — <name> — ROLE <A|B>
### 1. Scope reviewed
- Files opened (path: line ranges actually read)
- Callees traced into other areas (list, with area ID if known)

### 2. Findings
For each finding, in exactly this shape:

#### F-<AREA>-<n>  [P0|P1|P2|P3] — <one-line title>
- **File:** `path:line-line` (plus any other file:line)
- **Confirmed:** yes | hypothesis
- **Description:** what is wrong
- **Cause:** root cause, not symptom
- **Trigger conditions:** how it manifests
- **User impact:** what the user experiences
- **Evidence:** quoted code
- **Reproduction / verification:** concrete steps, test, or command
- **Suggested fix:** direction only — do NOT implement
- **Fix side effects:** risks of the fix
- **Discovered by:** A | B

### 3. Architecture observations (only if you have a concrete ARCH point)
### 4. Clean areas
What you checked and found correct (brief).
### 5. Coverage gaps
What you could not verify and why.
```

If an area has no findings, write "No findings." in section 2 and still fill in
sections 1, 4 and 5. Do not invent work. Do not pad the report.

**Your report must be self-contained**: another engineer must be able to fix
the defect from your report without re-reading the whole codebase.
