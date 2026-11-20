# NeDotify Android — Full Project Multi-Agent Audit

**Subject:** `android/` — the native Kotlin / Jetpack Compose / Media3 / Room port
**Date:** 2026-10-19
**Repo root:** `C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main`
**Method:** 70 independent reviewer agents (2 per area), cross-review, automated verification
**Source of truth:** the working tree as of this date. `android/` is **untracked in git** — there is no diff to review.

> This file is a work in progress. It is finalised when the "Audit complete" marker appears at the end.

---

## 1. Executive Summary

**Subject:** the `android/` port — a native Kotlin / Jetpack Compose / Media3 /
Room implementation of NeDotify, 75 production Kotlin files plus 42 JVM and 15
instrumentation test files. The Windows Python desktop app was used as the
**parity oracle**, not as the subject.

**Method.** 70 independent reviewer agents over 27 logical areas (AN-01…AN-27)
and 8 end-to-end integration scenarios (XI-01…XI-08) — two reviewers per area
(A = correctness & reliability, B = architecture / security / performance),
cross-reading each other's areas and the desktop oracle, with the report format
fixed in advance (`docs/audits/ANDROID_AUDIT_CONTEXT.md`) and the area map in
`docs/audits/ANDROID_AUDIT_AREAS.md`. Every claim was re-verified against the
source by the synthesiser; library behaviour was established from the **exact
pinned AARs** in the Gradle cache with `javap -c`, not from documentation.

### What was found

| Severity | Count | What it means |
|---|---|---|
| **P0** | 1 | Data loss in shipped desktop code |
| **P1** | 5 | The core play path or the user's data is broken |
| **P2** | 81 | A real defect with a user-visible consequence |
| **P3** | 116 | A defect, a smell, or a missing invariant — condensed into a table |

Plus **6 cross-module findings** (§6) that no single-area reviewer could see,
and **10 architectural improvements** (§8) that would remove whole families of
defects rather than individual instances.

### The six things that matter most

1. **P0-01 — the desktop app destroys user data on upgrade.**
   `core/database.py:313-362` contains a one-shot startup migration that
   deletes tracks and, through the foreign keys, cascades away their
   listening history and playlist entries. Found independently and reproduced.
   It is the only finding that should be fixed before anything else, because
   the desktop users are already running the broken build.

2. **The play path has a one-way latch that swallows the user's Play
   button.** `PendingSelectionGate.playAllowed` is tripped by every player
   command but re-armed only from `MediaSession.Callback.onPlayerCommandRequest`
   — and in Media3 1.11.1 that callback is **never reached** by
   `MediaController.play()`/`pause()` (only `setPlayWhenReady` dispatches
   through it). Once tripped, every subsequent Play is dropped with no error
   and no state change, until the user re-picks a track. Found by the XI-08
   B reviewer over the Media3 bytecode; the same root cause produces P2-11
   (a swallowed Play), P2-12 (a discarded queue selection) and P2-13 (a
   cancelled restore).

3. **The queue snapshot — the app's only durable session state — is written
   into the settings file every five seconds.** The playback position is
   embedded in the *compared* value, so the de-duplication guard can never
   suppress a write: a 3000-track queue costs ~270 KB of JSON churn and
   ~270 KB of whole-file flash writes **per track change**, and ~27 KB/s
   while music plays. The desktop caps the persisted queue at 200 entries and
   writes once, at exit.

4. **The port has never been run.** 59 instrumentation tests, including
   **all 19** Room schema-migration tests — the only guard on the v1→v2→v3
   migration that will run against real user data — were compiled and never
   executed. There is no `connectedDebugAndroidTest` task anywhere, no
   Android CI job, no device, no emulator, and **the whole `android/` tree is
   untracked in git** (`git ls-files android` → 0). The prior review's
   snapshot manifest is stale (27 of 187 files changed), so the audit anchor
   is broken too.

5. **Every serious defect clusters exactly where a device would have caught
   it.** The design is competent: the media-session architecture is idiomatic,
   the offline read path is physically network-free, the download state
   machine is generation-fenced, the backup codec has a real strict-JSON
   grammar, `minSdk 26` is verified against every dependency's AAR metadata.
   What it lacks is *operation*. 35 of the 75 production files (54.6 % of
   LOC) have no JVM test; 5 of the 10 non-negotiable contracts have no
   automated coverage of any kind.

6. **The "Все" search silently drops the user's own library.** The local
   source is not a query — it is a page-at-a-time scan of the whole `tracks`
   table in Kotlin, ordered by a column (`addedAt`) that carries **no index**.
   `EXPLAIN QUERY PLAN` says `SCAN tracks` + `USE TEMP B-TREE FOR ORDER BY`.
   Measured: 1 000 rows → 5.5 ms, 10 000 → 117 ms, 50 000 → **13.9 s**,
   100 000 → **63.5 s**. The aggregate gives that local scan the *same* 6.5 s
   budget as a network provider, so past ≈ 35 000–40 000 tracks it is
   cancelled mid-flight and the local matches are dropped — and because the
   network sources succeeded, the "a source was unreachable" signal never
   fires. The user gets a normal-looking result list that is missing every
   track they already own, with no error. The desktop has a real FTS5 index
   (0.50 ms at 1 000 rows, 10.5 ms at 100 000).

### The structural pattern

Six of the most serious findings are not in a function but in the
*relationships between modules* — and each was found independently by two to
four reviewers, which is the strongest evidence in the report:

- "is my work still current?" is answered **five different ways in five
  layers** (X-01);
- "offline" is defined **nine times by four mechanisms** (X-04);
- the effective source of a queue item is encoded **twice** — in the
  `MediaItem` and in the download table — and the two can disagree (A-4);
- the user's library has **five writers and no delete**, and one of them is
  *playback* (X-05, P2-31);
- the cross-platform format is the desktop's **private SQLite schema with no
  version** (X-06).

### What was actually verified

- Android JVM suite: **236 tests, 0 failures, 0 errors, 1 skipped** — BUILD
  SUCCESSFUL, exit 0.
- Lint: **0 errors, 15 warnings**.
- Desktop pytest: **1459 passed, 1 skipped, 3 xfailed** — exit 0.
- File-level review coverage: **75/75** main Kotlin files mapped, **0**
  unmapped.
- `android/verify.ps1 --rerun-tasks`: **BUILD FAILED** — a real build-tooling
  defect, documented in §9.3.
- `android/review/VERIFY.ps1`: **exit 1** — the prior snapshot does not match
  the tree.
- Media3 1.11.1, WorkManager 2.12.0, material3 1.4.0, Room 2.8.5 and AOSP
  `org.json` were read from the pinned artifacts with `javap -c`; the
  `minSdk` of all 139 cached AARs was extracted and checked.

### The recommendation

**The port should not ship in its current state — and the reason is not the
defect count. It is that there is no gate.** The riskiest surfaces are
covered by tests that have never run, in a tree that is not in version
control, with a build script that silently executes **zero** tasks whenever
its output is captured. Fixing the P1/P2 findings without first standing up
a gate means the next fifty findings arrive the same way.

The cheapest actions in this report are also the most valuable:
`git add android/`, regenerate the review manifest, and make the 59 device
tests actually execute. That is a few hours of work, and it changes the
economics of everything after it.

**No source code was modified during this audit.** The only file touched
outside `docs/audits/` was `android/local.properties`, rewritten and
restored byte-for-byte by `verify.ps1`.

---

## 2. Architecture Overview

### 2.1 What the project is

NeDotify is a music player. This audit's subject is the **Android port** — a native
Kotlin / Jetpack Compose / Media3 / Room application under `android/`. The
repository also contains the older **Windows desktop** app (Python 3.14 +
pywebview + vanilla JS) at the repo root; that app is used here as an **oracle**
for the shared product contracts (library backup, listening semantics, smart
rules, report windows, provider protocols), not as an audit subject.

Stack (from `android/app/build.gradle`):

| Layer | Choice | Version |
|---|---|---|
| Language | Kotlin + Java 17 target | 2.2.10 (AGP 9.1.1, KSP 2.3.12) |
| UI | Jetpack Compose (BOM-driven), Material 3 | BOM 2026.09.00 |
| Audio | Media3 `ExoPlayer` + `MediaSessionService`, HLS + progressive | 1.11.1 |
| Persistence | Room (6 entities, v3), DataStore Preferences | 2.8.5 / 1.2.0 |
| Background | WorkManager (downloads) | 2.12.0 |
| Network | OkHttp (shared client), `org.json` | 4.12.0 / platform |
| Images | Coil 3 (+ OkHttp fetcher) | 3.3.0 |
| Blur | `dev.chrisbanes.haze` | 1.7.3 |
| SDK range | min 26 / target 37 | — |
| Build | Gradle 9.3.1 (wrapper checksum-pinned), `android/verify.ps1` | — |

### 2.2 Module map

```
android/app/src/main/java/ru/nedotify/app/   75 Kotlin files (~7 000 LOC)
├── NeDotifyApp.kt        Application: hand-rolled DI (repository, downloads,
│                         audioCache, ioScope, queue-snapshot channel)
├── MainActivity.kt       Activity: Compose host, SAF pickers, runtime
│                         permissions, OAuth deep-link intake
├── data/  (35 files)     Room entities+DAO+DB, repository, provider clients,
│                         source resolution, stream cache, backup codec,
│                         desktop-import converter, lyrics cascade, discovery,
│                         smart rules, preferences, audio settings
├── player/ (12 files)    PlaybackService (MediaSessionService), DualDeckPlayer
│                         (two-deck crossfade), queue selection, pending-selection
│                         gate, mutation guard, focus state, listening clock/history
├── downloads/ (5 files)  WorkManager worker, download manager, storage, keys,
│                         offline media source
└── ui/  (21 files)       MusicViewModel (the central state machine), Compose
                          screens, design system

Non-Kotlin: AndroidManifest.xml + 4 res/ files.
Tests: 40 JVM files (app/src/test) + 15 instrumentation files (app/src/androidTest).
```

### 2.3 The runtime topology

```
Compose UI  ──StateFlow──▶  MusicViewModel  ──MediaController (IPC)──▶  PlaybackService
    ▲                            │                                            │
    │                            └── Room (library)                            │
    │                            └── DataStore (prefs, queue snapshot)          │
    │                            └── DataStore (provider secrets, Keystore)    │
    │                                                                         │
    └── audio: MediaSession (system UI, Android Auto, headset buttons) ◀────────┘
                                     │
                         ExoPlayer ──▶ ResolvingDataSource ──▶ CacheDataSource
                                                │                   │
                                       repository.resolve()    OkHttpDataSource
                                                │
                              StreamCache → SoundCloud / InnerTube / Yandex CDN
```

**Ownership rules the code follows (and where it breaks):**

* *Player ownership lives in `MediaSessionService`.* Verified to hold — the
  Compose layer only speaks to a `MediaController`; no composable or Activity
  touches `ExoPlayer`. (`PlaybackService.kt`, `MusicViewModel.kt:103-121`)
* *Stream URLs are resolved lazily, per item.* Verified to hold — `mediaItems()`
  builds every `MediaItem` with the app's own `nedotify://track/<id>` scheme;
  no provider URL is fetched for the queue. (`PlaybackService.kt:320-332`)
* *Listening time is measured, not inferred.* `ListeningClock` accumulates only
  while `player.isPlaying`. The **completion** rule diverges from the desktop
  oracle — see P1-01.
* *A partial streaming cache is never a completed download.* The Media3
  `SimpleCache` and the `offline_downloads` table are separate stores. Whether
  the *user-visible* notion of "available offline" is consistent across them is
  a finding (see P2-xx).

### 2.4 Architectural themes (the recurring shapes)

1. **Manual DI via the `Application` object.** `NeDotifyApp` is a service
   locator; `MusicViewModel`, `PlaybackService` and `TrackDownloadWorker` all
   reach it with `(application as NeDotifyApp)`. Consequence: the graph cannot
   be substituted in a JVM test, and the `Application` type is in every
   component's public contract.
2. **Three different "generation" / fencing-token mechanisms** coexist:
   `interactionVersion` in `PlaybackService`, `spotifyGeneration` /
   `yandexGeneration` in `ProviderConnections`, and the `generation` column in
   the `offline_downloads` table. Each solves "don't apply a stale result", but
   they are independent, undocumented and inconsistently applied.
3. **Two concurrency idioms for one intent.** `interactionVersion` (a counter)
   and `guardedPlaybackMutation` (a prepare/validate/apply protocol) express
   the same invariant in two places, plus a third hand-rolled variant inside
   `resolveFuture`. The invariant "a queue prepared for generation N must not
   be applied at generation N+1" is enforced at four sites with three
   different failure semantics.
4. **The desktop proxy capability is missing on Android.** The desktop resolves
   out of band and serves the stream through a loopback HTTP proxy
   (`core/proxy.py`) that injects provider headers, re-resolves an expired URL
   transparently, and rewrites HLS manifests. The Android port resolves
   *inside* the `ResolvingDataSource` with a blocking `runBlocking`, and passes
   only the final URL through — so the header-injection and transparent
   re-resolution capabilities do not exist on Android.
5. **The cross-platform library format is defined twice.** The desktop exports
   nothing; the Android app is a second, hand-written reader of the desktop's
   *private SQLite schema* (`DesktopLibraryImport.kt` / `DesktopLibraryConverter.kt`),
   with 26 hard-coded column names and no version marker on either side.
6. **The design system is a colour scheme, not a token layer.** 184 of the 193
   raw `dp` literals and 10 of the 24 raw `Color(0x…)` literals live outside
   `Design.kt`. The desktop has a real token layer (`ui/web_new_v2/css/tokens.css`,
   180 lines, with a written "declared exactly once" invariant).

### 2.5 The desktop oracle

The desktop app is the reference for the shared product contracts. The
relevant files are `core/database.py` (schema, migrations, FTS5 search table,
history semantics), `core/listening.py` (measured-listening model, the 80 %
completion rule, the 15 s heartbeat clamp), `core/api.py` (the ~200-method
bridge surface, backup export/import), `core/settings.py` (defaults),
`services/smart_playlists.py` (rule grammar), `services/listening_comparison.py`
(report definition), `services/lyrics_lookup.py` / `lyrics_cache.py` /
`lyrics_service.py` (the lyrics cascade), `services/base_service.py` (provider
fan-out + the 300 s search cache), `core/resolver.py` + `core/proxy.py`
(stream resolution), `core/downloader.py` + `core/download_store.py` (download
state machine), `audio/engine.py` + `audio/queue.py` (queue/shuffle/repeat),
and `ui/web_new_v2/` (the UI, its design tokens and its navigation model).

---

## 3. Multi-Agent Coverage

### 3.1 Method and independence

Every one of the **27 primary areas** and **8 integration scenarios** was
assigned to **exactly two** independent reviewers:

* **Role A — Correctness & Reliability**: logical errors, state-management
  errors, unhandled exceptions, race conditions, deadlocks, resource leaks,
  threading errors, async errors, null/empty handling, malformed input, edge
  cases, data loss, crashes, recovery after failure.
* **Role B — Architecture, Security & Performance**: separation of
  responsibilities, coupling, duplication, algorithmic inefficiency, avoidable
  allocation, data leaks, unsafe handling of external data, API misuse,
  scalability, anti-patterns, unstable dependencies, lifecycle errors, contract
  violations, testability and maintainability.

**Independence guarantee.** Each reviewer was a fresh subagent with its own
context, seeded with the same shared brief
(`docs/audits/ANDROID_AUDIT_CONTEXT.md`) and the same area, and given a
*different* specialisation. No reviewer was shown another's output, and no
reviewer was asked to reproduce another's conclusions. Findings were therefore
produced independently and only merged afterwards, in the cross-review step.

Both reviewers were additionally required to: read the real files rather than
assume their contents; trace call chains into other areas and cross-reference
rather than double-report; cite `path:line` plus a quoted snippet for every
finding; separate CONFIRMED findings from HYPOTHESES; avoid style nits; and
modify no repository file.

**Total: 70 independent review tasks** (54 primary + 16 integration).

### 3.2 Area coverage table

| ID | Area | Files reviewed | A | B |
|---|---|---|---|---|
| AN-01 | App shell, Activity, Application, Manifest, res | 4 + 12 traced | ✔ | ✔ |
| AN-02 | ViewModel orchestration & app state machine | 3 (455-LOC VM) | ✔ | ✔ |
| AN-03 | MediaSession service: commands, restore, autoplay, offline | 1 (349 L) + 14 traced | ✔ | ✔ |
| AN-04 | Dual-deck player, crossfade, gain, audio runtime | 4 (313-LOC player) | ✔ | ✔ |
| AN-05 | Queue selection, gate, mutation guard, focus, history | 7 | ✔ | ✔ |
| AN-06 | Room: entities, DAO, DB v3, repository, schemas | 5 + schemas | ✔ | ✔ |
| AN-07 | Backup codec, merge, backup storage | 3 (28 KB codec) | ✔ | ✔ |
| AN-08 | Desktop library import & converter | 2 + 8 traced | ✔ | ✔ |
| AN-09 | Provider connections, PKCE, secure store, provider HTTP | 4 | ✔ | ✔ |
| AN-10 | Catalog providers (Spotify/Yandex) & parsers | 2 | ✔ | ✔ |
| AN-11 | Source resolution, stream cache, signed-URL TTL, deadlines | 6 (245-LOC sources) | ✔ | ✔ |
| AN-12 | Search aggregation & catalog matcher | 2 | ✔ | ✔ |
| AN-13 | Lyrics cascade, lyrics data, lyrics disk cache | 3 (237-LOC cascade) | ✔ | ✔ |
| AN-14 | Discovery, smart rules, listening reports | 4 | ✔ | ✔ |
| AN-15 | Downloads: worker, manager, storage, keys, offline source | 5 | ✔ | ✔ |
| AN-16 | Preferences, profile settings, audio settings store | 4 | ✔ | ✔ |
| AN-17 | UI shell: navigation, design system, home | 3 + 12 traced | ✔ | ✔ |
| AN-18 | UI player screen & mini player | 2 | ✔ | ✔ |
| AN-19 | UI library, browse, catalog browser, downloads, import | 5 | ✔ | ✔ |
| AN-20 | UI search & discovery controls | 2 | ✔ | ✔ |
| AN-21 | UI profile, settings, appearance, audio controls | 4 | ✔ | ✔ |
| AN-22 | UI connections & backup controls | 2 | ✔ | ✔ |
| AN-23 | Build config, dependencies, lint, SDK levels, packaging | 7 build files | ✔ | ✔ |
| AN-24 | Android unit test suite (JVM, 40 files) | 40 | ✔ | ✔ |
| AN-25 | Android instrumentation test suite (15 files) | 15 | ✔ | ✔ |
| AN-26 | Desktop-parity oracle: backup, DB schema, history semantics | 13 Python files | ✔ | ✔ |
| AN-27 | Docs & porting-status consistency; review artifact integrity | 20+ files | ✔ | ✔ |
| XI-01 | MediaSession ↔ ViewModel ↔ Compose state consistency | cross-cutting | ✔ | ✔ |
| XI-02 | Track resolution → playback → error → recovery | cross-cutting | ✔ | ✔ |
| XI-03 | Download lifecycle end-to-end | cross-cutting | ✔ | ✔ |
| XI-04 | Provider auth lifecycle | cross-cutting | ✔ | ✔ |
| XI-05 | Offline mode end-to-end | cross-cutting | ✔ | ✔ |
| XI-06 | App lifecycle & process death | cross-cutting | ✔ | ✔ |
| XI-07 | Backup round-trip & desktop import | cross-cutting | ✔ | ✔ |
| XI-08 | Rapid user interaction & concurrency | cross-cutting | ✔ | ✔ |

### 3.3 File-level coverage accounting (verified mechanically)

| Package | Files | Mapped to an area | Unmapped |
|---|---|---|---|
| `ru/nedotify/app/` (root) | 2 | 2 | 0 |
| `ru/nedotify/app/data/` | 35 | 35 | 0 |
| `ru/nedotify/app/player/` | 12 | 12 | 0 |
| `ru/nedotify/app/downloads/` | 5 | 5 | 0 |
| `ru/nedotify/app/ui/` | 21 | 21 | 0 |
| **Total main Kotlin** | **75** | **75** | **0** |

Non-Kotlin main sources: `AndroidManifest.xml`, `res/drawable/ic_nedotify.xml`,
`res/values/styles.xml`, `res/xml/backup_rules.xml`,
`res/xml/data_extraction_rules.xml` — all covered by AN-01, cross-checked by
AN-23. Test sources: 40 JVM files (AN-24) + 15 instrumentation files (AN-25).
Build files: all covered by AN-23. The Python desktop tree is covered by AN-26
as the parity oracle and by AN-07/09/10/11/13/14/15/17 for the shared
contracts.

**Every source file in the audit subject belongs to at least one area. Zero
files are unaccounted for.**

---

## 4. Critical Findings

### 4.0 Summary

| Severity | Count | Note |
|---|---|---|
| **P0 — CRITICAL** | **1** | A one-shot startup migration in the **desktop** reference app permanently deletes tracks and cascades away their listening history and playlist entries. **Independently reproduced by the coordinator.** |
| **P1 — HIGH** | **5** | Two broken core features, one permanently-wedged state, one shipped feature that cannot work at all, and one search path that silently drops the user's own library. |
| P2 — MEDIUM | 81 | See §5.1 and the full register |
| P3 — LOW | 116 | See §5.2 and the full register |

**No P0 was found in the Android port.** This is a deliberate, evidence-based
conclusion, not an absence of review: every area was covered by two
independent reviewers, and the audit looked specifically for data-loss paths,
injection surfaces, exported components, credential handling and the backup
round-trip. The security posture of the credential store, the SQL layer, the
URL construction and the HTTP transport is sound (see §7.1). The Room
migrations on Android were hand-verified line by line against the exported
schemas and match them exactly.

The one P0 in the project is in the **Windows desktop reference app**, which is
also the app that owns the user's real library at `~/.nedotify/`. It is
reported here because the engagement covers the whole repository.

---

### P0-01 — A one-shot startup migration in the desktop app permanently deletes tracks and cascades away their listening history and playlist entries

* **Component:** Windows desktop reference app (the Android port is **not** affected)
* **File:** `core/database.py:313-362` (trigger `:314-315`; the destructive `DELETE` at `:344-357`; the flag write at `:358-360`)
* **Status:** **CONFIRMED — independently reproduced by the coordinator** against an isolated synthetic "old build" database. The user's `~/.nedotify/` was never opened.
* **Priority:** **P0** — unrecoverable destruction of the user's listening history and playlist membership, executed automatically at startup with no report, no backup and no user consent.

**Description.** On every database open, the app checks for a
`migration_dup_cleanup_done` flag in `settings`. If the flag is absent — which
is true for every library created by a build predating this migration — it
runs a "duplicate cleanup" that ends with:

```sql
DELETE FROM tracks
WHERE id IN (
    SELECT t.id
    FROM tracks t
    WHERE t.id NOT IN (
        SELECT MIN(t2.id) FROM tracks t2
        GROUP BY LOWER(t2.title), LOWER(t2.artist)
    )
)
```

The grouping key is **`(LOWER(title), LOWER(artist))` only**. It ignores
`album`, `source`, `source_id` and `file_path`. Two rows that share a title
and an artist but are *different recordings* — a studio album and a live
album, a local file and a YouTube link of the same song, two different songs
with the same title — are therefore treated as duplicates, and every row
except the **lowest-id** one is deleted.

`PRAGMA foreign_keys=ON` is set on every connection (`core/database.py:119`),
and both referencing tables declare `ON DELETE CASCADE`:

```sql
-- core/database.py:194-195
FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
-- core/database.py:208
FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
```

so each deleted track takes its **history rows** and its **playlist entries**
with it. The audio file stays on disk, unreferenced. `play_count` is lost.
Nothing in the UI reports the deletion, and the migration is wrapped in
`except Exception: logger.debug(...)`, so a failure is silent too.

**Cause.** The de-duplication key was chosen as the *display* identity
(title + artist) rather than the *recording* identity (title + artist + album +
source + source_id + file path). A display-identity key is not a safe key for
a destructive operation.

**Trigger conditions.** Any library created by a build predating the
migration that contains two rows sharing `LOWER(title)`/`LOWER(artist)`. The
migration runs on the UI thread at startup, exactly once, and the flag is
then set forever.

**User impact.** A library row disappears. Every play of it vanishes from the
listening history and from the profile statistics; its playlist entries are
removed; `play_count` is lost; the audio file remains on disk with nothing
pointing at it. It is **not recoverable from the database**, and because the
app's own backup is a *post-hoc* export, a user who has not exported before
upgrading has no copy.

**Evidence — coordinator's own reproduction** (isolated temp DB, the exact
statements from `core/database.py:317-357`, the user's library untouched):

```
BEFORE tracks: [(1,'Yesterday','Help!','local',5),
                 (2,'Yesterday','Live at Rickenbacker','local',9),   <-- different ALBUM
                 (3,'Yesterday','Help!','youtube',2),               <-- different SOURCE
                 (4,'Come Together','Beatles','Abbey Road','youtube',3)]
BEFORE history rows: 4
BEFORE playlist_tracks rows: 4

AFTER  tracks: [(1,'Yesterday','Help!','local',5), (4,'Come Together',Beatles,'Abbey Road','youtube',3)]
AFTER  history rows: 2 (lost: 2)
AFTER  playlist_tracks rows: 2
AFTER  history detail: [(1, 60.0), (4, 60.0)]
```

Track 2 (a **live album** with 9 plays) and track 3 (the **YouTube** copy of
the same song with 2 plays) were both deleted, taking 2 history rows and 2
playlist entries with them. Track 1 — the *same album and title*, the one
copy that happened to have the lowest id — survived. The user's "Yesterday"
entry is now a single row pointing at one arbitrary edition.

**Reproduction / verification.** The script above (`%TEMP%\opencode\dup_migration_repro.py`)
is self-contained and uses a throwaway database. To observe it on a real
profile, copy an old `nedotify_storage.db` to a temp location, open it with
the app's own `core/database.py`, and diff `tracks` / `history` /
`playlist_tracks` before and after.

**Recommended fix.** Scope the grouping to the *recording* identity —
`(LOWER(title), LOWER(artist), album, source, source_id)` — and only collapse
rows that are genuinely the same file (`source_id IS NULL AND file_path IS
NULL`). Better still: **never delete a row that a `history` row references**;
move such rows to a `tracks_duplicate_of` column instead. And take a backup
table (`CREATE TABLE tracks_backup AS SELECT * FROM tracks`) before any
destructive `DELETE`.

**Fix side effects.** A correctly-scoped migration leaves genuine duplicates
visible in the library. That is the correct trade-off — a visible duplicate is
recoverable, a deleted history row is not. Existing installations that have
already run the migration cannot be repaired automatically; the `tracks_backup`
table would need to be created *before* the destructive statement, which
means shipping a corrective migration that restores any `history` rows whose
`track_id` is now missing.

**Cross-reference:** the Android port has **no equivalent defect**. Its Room
migrations (`MIGRATION_1_2`, `MIGRATION_2_3`) were hand-verified against the
exported schemas `android/app/schemas/…/2.json` and `3.json` and match the
column sets, affinities, NOT NULL flags, primary keys and foreign keys
exactly, with no destructive fallback.

---

### P1-01 — The lyrics identity gate rejects any track whose title is "Artist - Song", so lyrics are never found for those tracks

* **Area:** AN-13 (Lyrics) · **Found by:** B · **Independently consistent with:** the desktop oracle's two-layer split (`services/music_matching.py:71-77` + `services/lyrics_service.py:220-224`)
* **File:** `android/app/src/main/java/ru/nedotify/app/data/LyricsCascade.kt:46-54` (title normalisation), `:77-78` (the gate)
* **Status:** CONFIRMED (deterministic string logic; the reviewer executed a line-for-line Python mirror of the Kotlin and observed the rejection)
* **Priority:** **P1** — a core feature is broken for a large, easily-identified class of tracks, and the app fetches the correct candidate and then discards it.

**Description.** `LyricsIdentity.title()` strips a bracketed qualifier and
strips a `" - <version>"` **suffix** only when the suffix matches a version
word (`remix|live|acoustic|instrumental|slowed|sped|nightcore|edit|cover|remaster`).
It never splits an `"Artist - Title"` **prefix**. The normalised base
therefore becomes `"artist song"` while every provider offers `"song"`, the
Levenshtein ratio falls to ~0.64, and the gate rejects **every** candidate from
all four providers.

**Cause.** The Android port merged the desktop's two layers — query cleaning
(`_clean_track_and_artist`) and identity parsing (`title_metadata`) — into one
layer and dropped the artist-prefix rule.

**Trigger conditions.** `track.title` contains `" - "` with a non-version
suffix, and the provider's title is the bare song name. This is the normal
shape of:
* a **YouTube** result, whose title is the raw title row (`data/Sources.kt:157` → `"Artist - Song (Official Video)"`);
* a **SAF-imported file with no ID3 title**, whose title becomes the file name (`data/LibraryRepository.kt:91`, `data/LocalImportTitle.kt:3-6`).

The same codebase already knows this pattern for catalogue matching —
`data/CatalogMatcher.kt:51`: *"YouTube commonly includes the artist in the title"*.

**User impact.** The lyrics tab is permanently empty ("Текст не найден") for a
large share of YouTube-imported and untagged local tracks, even though the
app successfully fetched the correct candidate from LRCLIB / NetEase / QQ and
then threw it away.

**Evidence.**
```kotlin
// LyricsCascade.kt:46-54
val suffix = base.substringAfterLast(" - ", "")
if (suffix.isNotEmpty() && versionWord.containsMatchIn(suffix)) {
    versions += normalize(suffix).replace("remastered", "remaster")
    base = base.substringBeforeLast(" - ")
} else if (versionWord.containsMatchIn(base)) { ... }
return Title(normalize(base), versions.sorted())
```
```kotlin
// LyricsCascade.kt:77-78
if (wanted.base.isBlank() || wanted.base.length > 512 || offered.base.length > 512 ||
    wanted.version != offered.version || !similar(wanted.base, offered.base)) return null
```
Desktop oracle — `services/lyrics_service.py:220-224`:
```python
if artist:
    art_esc = re.escape(artist)
    track = re.sub(rf'^{art_esc}\s*[\-—–:]\s+', '', track, flags=re.IGNORECASE).strip()
```
and `services/music_matching.py:71-77` splits it a second time in the identity layer.

Mirror output (Android vs desktop, `track.title="Artist - Song (Official Video)"`,
`track.artist="Artist"`, provider offers `"Song"/"Artist"`):
```
android : want.base='artist song'  got.base='song'  dist/size=0.636 -> accept=False
desktop : base_title='song'                              -> accepted
```

**Reproduction / verification.** Add a JVM case to `LyricsCascadeTest`:
`LyricsIdentity.accept(Track("youtube:1","Artist - Song (Official Video)","Artist",durationMs=180_000), "Song", "Artist", 180_000, "[00:01]x", "x")` must currently return `null`; the desktop's `LyricsLookup.accept` returns a hit for the same inputs.

**Recommended fix.** Give the identity layer an explicit *artist-conditioned*
prefix rule: when the segment before the last `" - "` normalises to the track's
artist, drop it from `wanted.base`. Do **not** loosen the similarity threshold
to compensate — that would weaken the false-match protection the gate exists
for.

**Fix side effects.** Dropping the prefix changes `wanted.base` for every title
containing `" - "`, including genuine titles such as "AC/DC - Back in Black"
(the prefix "ac dc" is not the artist, so it must stay) and "Song - Part 2"
(the suffix is not a version word and must stay). The rule must be
artist-conditioned, not unconditional.

---

### P1-02 — A corrupt preferences file is never repaired: the app looks healthy but **no setting can ever be changed again**

* **Area:** AN-16 (Preferences) · **Found by:** B
* **File:** `android/app/src/main/java/ru/nedotify/app/data/Preferences.kt:9`, `:14`; `android/app/src/main/java/ru/nedotify/app/data/AudioSettingsStore.kt:10`, `:18`
* **Status:** CONFIRMED — the library behaviour was established by decompiling the exact shipped AARs (`datastore-core-android-1.2.0`, `datastore-preferences-android-1.2.0`) with `javap`, not from documentation.
* **Priority:** **P1** — the app enters a state where every user action on every setting fails, with a generic message, and the only recovery destroys the user's library.

**Description.** Neither `preferencesDataStore` delegate is given a
`corruptionHandler`. The default is `null`, which `DataStoreFactory.create`
replaces with **`NoOpCorruptionHandler`**, whose `handleCorruption` simply
rethrows the `CorruptionException`.

* On the **read** side the app is safe *by accident*: `CorruptionException extends java.io.IOException`, so `catch { if(it is IOException) emit(emptyPreferences()) else throw it }` converts it into "all defaults".
* On the **write** side nothing recovers: `DataStoreImpl` caches the failure as `State.ReadException` and `handleUpdate` re-enters `readAndInitOrPropagateAndThrowFailure()` → `readDataOrHandleCorruption()` → the handler rethrows again. **Every `store.edit` fails, and the corrupt file is never rewritten.**

**Cause.** The app relies on the read fallback only. A
`ReplaceFileCorruptionHandler { emptyPreferences() }` was never supplied, so
the library's default (rethrow) governs the write path.

**Trigger conditions.** A truncated or unparseable `*.preferences_pb` —
an interrupted write, out-of-space, or a key whose stored proto type no longer
matches the Kotlin key type. Exposure is raised by the fact that the settings
file is rewritten **wholesale every 5 s during playback** (see P2-09) and the
audio file on every audio-setting change.

**User impact.** After corruption the app *looks* healthy (defaults
everywhere: dark theme, no profile edits, no search history) but **no setting
can be changed**: every toggle produces the generic snackbar
"Не удалось выполнить действие" and the value never persists. The state is
permanent until the user clears the app's data — which also destroys their
library. The user is never told their settings were lost or the file damaged.

**Evidence.**
```kotlin
// Preferences.kt:9,14
private val Context.settings by preferencesDataStore("nedotify")
...
private val values=store.data.catch { if(it is IOException) emit(emptyPreferences()) else throw it }
```
```kotlin
// AudioSettingsStore.kt:10,18
private val Context.audioSettingsStore by preferencesDataStore("nedotify_audio")
...
val settings:Flow<AudioSettings> = store.data.catch {if(it is IOException)emit(emptyPreferences()) else throw it}
```
Library bytecode (javap, local Gradle cache): `preferencesDataStore$default` stores
`aconst_null` for the handler; `DataStoreFactory.create(Storage, ReplaceFileCorruptionHandler, …)`
replaces null with `new NoOpCorruptionHandler`; `NoOpCorruptionHandler.handleCorruption`
is `aload_1; athrow`; `CorruptionException extends java.io.IOException`;
`DataStoreImpl$handleUpdate$2$1.invokeSuspend` calls
`readAndInitOrPropagateAndThrowFailure` on the `ReadException` state.

**Reproduction / verification.** Overwrite `files/datastore/nedotify.preferences_pb`
with arbitrary bytes (`adb shell run-as` on a debug build) and start the app:
theme/profile fall back to defaults, then toggle any switch in Settings and
observe the "Не удалось выполнить действие" snackbar and the value not
persisting across a restart.

**Recommended fix.** Pass an explicit `ReplaceFileCorruptionHandler { emptyPreferences() }`
to both delegates, and surface a one-shot "настройки сброшены" notice so a
silent reset is not confused with a fresh install.

**Fix side effects.** The corrupt file is then replaced with an empty one,
permanently discarding its contents — the intended trade-off, but it must be
announced rather than silent.

---

### P1-03 — A single 401 from any Yandex API call permanently destroys the user's Yandex credential, with no recovery path

* **Area:** AN-09 (Provider auth) · **Found by:** A
* **File:** `android/app/src/main/java/ru/nedotify/app/data/ProviderConnections.kt:187-191` (GET) and `:203` (POST)
* **Status:** CONFIRMED
* **Priority:** **P1** — a single transient HTTP response destroys a credential the user can only obtain by hand, and the app provides no way to get it back.

**Description.** Every Yandex catalogue call is authenticated with the user's
long-lived OAuth token. On HTTP **401** the app performs no recovery — it
unconditionally deletes the credential from the secure store and clears the
in-memory token, uid and display name. Yandex has **no refresh flow** in this
app (unlike Spotify, which refreshes first at `:179-186`), so the only
recovery is for the user to re-acquire the token from the Yandex website and
paste it again. The 401 is never re-validated.

**Cause.** The handler conflates "this credential is invalid" with "this request
was not authorized", and treats the former as sufficient justification to
destroy a secret the user must obtain out-of-band.

**Trigger conditions.** Any 401 from `api.music.yandex.net` on a search /
playlists / liked-tracks / tracks-POST call while the Yandex provider is
connected — including a proxy/WAF interstitial, a service hiccup, or a session
revoked elsewhere.

**User impact.** The Yandex connection silently disappears from the settings
screen. The token is gone from the app, so it cannot be retried.

**Evidence.**
```kotlin
// ProviderConnections.kt:187-191
if(error.httpCode==401)withContext(Dispatchers.IO){lock.withLock {
    if(provider=="spotify" && spotifyGeneration==access.generation && token?.access==access.value){store.remove("spotify_token");token=null;spotifyGeneration++}
    if(provider=="yandex" && yandexGeneration==access.generation && yandexToken==access.value){store.remove("yandex_token");store.remove("yandex_user");yandexToken=null;yandexUid="";yandexGeneration++;_status.value=_status.value.copy(yandexName="")}
    publish()
}}
```
Desktop oracle, `services/yandex_service.py:242-243`, keeps the token and only
reports the failure:
```python
'Ошибка авторизации Яндекс Музыки. Добавьте токен в Настройки → Авторизация'
```

**Reproduction / verification.** Drive `ProviderConnections.get("yandex", …)`
against a server that answers 401 once (`MockResponse().setResponseCode(401)`),
then assert the store: `store.values["yandex_token"] == null` and
`status.value.yandexConnected == false`. **This path has no test today** —
`ProviderConnectionsTest.kt` covers the Spotify 401/refresh/disconnect paths
and the Yandex *logout* race, but never a 401 from a Yandex call.

**Recommended fix.** On a Yandex 401, re-validate the credential against
`account/status` (`ProviderConnections.kt:109` already performs exactly this
call) before deciding to delete it; delete only if the re-validation also
fails.

**Fix side effects.** One extra request on the error path, and the
"disconnected" state would lag a 401 by one round-trip, so the status text
must still reflect the failure immediately. The `yandexScope()` rotation
contract must keep rotating whenever the credential really is dropped.

---

### P1-04 - The shared HTTP client's 30-second `callTimeout` aborts every download whose body takes longer than 30 seconds

* **Area:** AN-15 (downloads) · *Found by:* B
* **Files:** `android/app/src/main/java/ru/nedotify/app/data/Sources.kt:22-23`; `android/app/src/main/java/ru/nedotify/app/downloads/DownloadStorage.kt:26-29`; `android/app/src/main/java/ru/nedotify/app/downloads/TrackDownloadWorker.kt:56`, `:84-89`
* **Status:** CONFIRMED - verified against the bytecode of the exact pinned dependency versions in the Gradle cache (`okhttp-4.12.0.jar`, `media3-datasource-okhttp-1.11.1.aar`, `okio-jvm-3.15.0.jar`)
* **Priority:** **P1** - a shipped feature cannot work at all for normal-length tracks.

**Description.** `MusicNetwork` builds **one** `OkHttpClient` and uses it for
both metadata requests *and* the media data source:
```kotlin
class MusicNetwork(val http:OkHttpClient=OkHttpClient.Builder().connectTimeout(12,TimeUnit.SECONDS)
        .readTimeout(20,TimeUnit.SECONDS).callTimeout(30,TimeUnit.SECONDS).build()) {
```
`DownloadStorage.factory(...)` installs exactly that client as the upstream of
the download's `CacheDataSource`. OkHttp's `callTimeout` spans the **whole
call including reading the response body**, so the transfer is aborted 30 s
after the request starts, regardless of how much has been transferred.

**Cause.** one HTTP client with a 30 s *total* call budget is reused for bulk
media transfer. The metadata requests legitimately want a 30 s ceiling; the
byte transfer does not.

**Trigger conditions.** any progressive download whose transfer time exceeds
30 s. At 320 kbps that is ~1.2 MB; at 1 Mbit/s ~3.6 MB; at 2 Mbit/s ~7.5 MB -
i.e. essentially every real track on any mobile connection. HLS is *not*
affected the same way: `HlsDownloader` opens each segment with its own
`DataSpec` -> its own call -> each segment is small, so the per-call deadline
is not reached. **Progressive downloads (all YouTube, and SoundCloud when the
track has a progressive transcoding) are the affected ones.**

**User impact.** the download never completes. The worker classifies the
aborted call as a plain `IOException` (`InterruptedIOException("timeout")`),
treats it as retryable and re-runs it up to 3 more times (~4 x 30 s wasted),
then ends in state `failed` with the text *"Соединение прервано. Загрузку
можно продолжить"* - the user is told to continue, and continuing fails
identically. The offline-download feature, which `android/PORTING_STATUS.md:112`
lists as the shipped offline mechanism, is unusable for normal-length tracks.

**Evidence.**
```kotlin
// data/Sources.kt:22-23 - the shared client
class MusicNetwork(val http:OkHttpClient=OkHttpClient.Builder().connectTimeout(12,TimeUnit.SECONDS)
        .readTimeout(20,TimeUnit.SECONDS).callTimeout(30,TimeUnit.SECONDS).build()) {

// downloads/DownloadStorage.kt:26-29 - that client is the download's upstream
fun factory(id:String,online:Boolean,seen:MutableSet<String>?=null):CacheDataSource.Factory = CacheDataSource.Factory()
    .setCache(cache).setCacheKeyFactory {spec->downloadCacheKey(id,spec.uri.toString()).also {seen?.add(it)}}
    .setUpstreamDataSourceFactory(if(online)OkHttpDataSource.Factory(network.http) else null)

// downloads/TrackDownloadWorker.kt:84-89 - the timeout is treated as retryable
} catch(error:Exception) {
    val status=generateSequence<Throwable>(error){it.cause}.take(12).filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()?.responseCode
    val retry=error is IOException && error !is SourceFailure && downloadCanRetry(runAttemptCount,status)
    dao.downloadState(trackId,generation,if(retry)"queued" else "failed",failureText(error,status))
    if(retry)Result.retry() else Result.failure()
}
```
Bytecode evidence from `okhttp-4.12.0.jar`: `RealCall.execute()` arms the
deadline via `RealCall$timeout$1.enter()` at the start of the call;
`RealCall$timeout$1.timedOut()` calls `RealCall.cancel()`, aborting the
in-flight body read; and `okio.AsyncTimeout.enter()` inserts the timeout into
a global queue with a deadline, so the watchdog stays armed for the whole body
read. `OkHttpDataSource.open` -> `callFactory.newCall(request)` ->
`executeCall(call)` -> `call.execute()`, i.e. the same `Call` stays open while
`CacheDataSource` streams the body into the cache.

**Reproduction / verification.** assert `MusicNetwork().http.callTimeoutMillis == 30_000` and that
`DownloadStorage.factory(id, true)` uses that client. End-to-end: point the
download at a `MockWebServer` that writes a 5 MB body over >30 s and assert the
worker ends in `failed` with an `InterruptedIOException` instead of `complete`.

**Recommended fix.** give the media path its own client. `MusicNetwork` should
expose a second `OkHttpClient` (e.g. `mediaHttp`) built with `callTimeout(0)`
(no total call budget) or a download-sized budget, keeping the 30 s
`callTimeout` for metadata. `DownloadStorage.factory` must use that client.
The same change is required for the streaming path in
`player/PlaybackService.kt:55` - the fix belongs in the shared client, so it
must be applied in one place.

**Fix side effects.** the transfer then has no total-time bound; only the 20 s
per-read `readTimeout` applies, so a half-dead connection is still detected but
a very slow one is not. The retry/backoff policy
(`downloadCanRetry`, `downloads/DownloadKeys.kt:23`) would then need to bound
slow-but-alive transfers instead.

---

### P1-05 — Local library search is a full table scan with no index; past ~35 000 tracks the "Все" search silently drops every local match

* **Area:** AN-12 (search aggregation) · **Found by:** B
* **Files:** `data/LibraryRepository.kt:55-67`; `data/Models.kt:104-105`;
  `data/SearchAggregate.kt:16,22`; `ui/SearchScreen.kt:90-93`;
  `android/app/schemas/ru.nedotify.app.data.LibraryDatabase/3.json:98-113`
* **Status:** CONFIRMED — the query plan, the absence of the index, and the
  timings were all reproduced against the exact exported schema and SQL
* **Description.** The "На устройстве" source is *paging over the whole
  `tracks` table in Kotlin*, not a query. `dao.searchPage(500, offset)`
  selects from **all** rows where `localUri!='' OR id IN (completed
  downloads)`, ordered by `addedAt DESC`, `LIMIT 500 OFFSET n`. The entity
  declares only two indices — `index_tracks_source` and
  `index_tracks_favorite` — so **`ORDER BY addedAt DESC` has no supporting
  index**. `EXPLAIN QUERY PLAN` on the reproduced schema:
  ```
  SCAN tracks
  LIST SUBQUERY 1
  SCAN offline_downloads
  CREATE BLOOM FILTER
  USE TEMP B-TREE FOR ORDER BY
  ```
  Every page re-scans the whole table and re-sorts it. The loop pages until
  100 matches accumulate **or the table is exhausted** — so a query matching
  nothing walks the entire library, and the total work is O(N²/500) row
  visits. The desktop does the opposite: `core/database.py:395` creates a real
  FTS5 index with insert/update/delete triggers, queried with per-word prefix
  matching.
* **Measured** (host SQLite, the exact schema and SQL from the exported JSON):
  | library size | Android paged scan | desktop FTS5 |
  |---|---|---|
  | 1 000 | 5.5 ms / 1 000 rows read | 0.50 ms |
  | 10 000 | 117 ms / 10 000 rows read | 1.16 ms |
  | 50 000 | **13 943 ms** / 50 000 rows read | — |
  | 100 000 | **63 456 ms** / 100 000 rows read | 10.54 ms |
* **Cause.** A hand-rolled scan-and-filter in Kotlin instead of a query; and
  the local source is given **the same 6.5 s budget as a network provider**
  (`SearchAggregate.kt:16,22`), although it is a local operation.
* **Trigger.** A device library of tens of thousands of tracks (reachable
  with lossless/FLAC collections), then any "Все" or "На устройстве" search
  whose result set is smaller than 100 rows. The measured crossover against
  the 6.5 s budget is ≈ 35 000–40 000 tracks.
* **User impact.** The "Все" tab calls
  `aggregateSearch(listOf({search(query,"local")}, {soundCloud…}, {youtube…}))`,
  and the local task is cancelled mid-flight → `TimeoutCancellationException`
  → `Result.failure` → the local tracks are dropped. Because the two network
  sources usually succeed, `tracks` is non-empty, so the `SourceFailure` at
  `SearchAggregate.kt:30` — the one signal that a source was unreachable —
  **never fires**. The user sees a normal-looking result list that is
  missing every track they already own, with no error and no warning. The
  dedicated "На устройстве" chip is worse: it has **no** timeout at all, so a
  non-matching query on a 100 000-track library blocks the search for over a
  minute, holding the ViewModel's `searchJob` in the `busy` state throughout.
* **Evidence.** The paging loop at `data/LibraryRepository.kt:55-67`, the
  query at `data/Models.kt:104-105`, the only two indices in
  `schemas/.../3.json:98-113`, and the desktop's FTS5 DDL + `MATCH` query at
  `core/database.py:395-400,786-808`.
* **Reproduction.** The exact `searchPage` SQL and the exact
  `tracks`/`offline_downloads` DDL were reproduced in host SQLite from the
  exported schema; `EXPLAIN QUERY PLAN` and the paging loop were timed at
  1 000 / 10 000 / 50 000 / 100 000 rows against the desktop's FTS5 path,
  and the crossover was bisected at 30 000 / 40 000 / 45 000 / 50 000 /
  60 000. Scripts kept outside the repo tree.
* **Fix.** Push the filter into SQL and add an index that supports the
  query — or, closer to the oracle, add an FTS table with the desktop's
  triggers and query it with per-word prefix terms. Separately, give the
  local source its **own** budget (it is not a network call) so a slow local
  scan can never be silently discarded.
* **Fix side effects.** An FTS table requires a Room migration (schema v4)
  plus a backfill; `room-runtime:2.8.5` has no `@Fts4` support without the
  `room-fts` artefact, so a hand-written FTS5 table (as the desktop does) or
  a plain indexed `LIKE` query are the realistic options. An indexed
  `LIKE '%q%'` still cannot use an index for a leading wildcard, so it fixes
  the *scan* but not the *per-page* cost. Changing the local budget changes
  when `SearchAggregate.kt:30` raises `SourceFailure`, so `SearchAggregateTest`
  must be re-checked. See also P3-116 (the same `OFFSET` pagination is not
  snapshot-stable: a track added or removed mid-scan is returned twice or
  not at all).
* **Note on the related findings.** P2-59 in the register recorded this same
  defect at P2 priority from a cruder 20 000-row measurement; this is that
  finding, measured properly and **promoted to P1**. P2-80 (SoundCloud's
  first call must scrape a `client_id` inside the same 6.5 s budget, which
  the desktop explicitly budgets 8 s for) and P2-81 (the catalogue matcher
  performs up to 1 000 sequential third-party searches per import, where the
  desktop uses bounded concurrency, a memo cache and a local-first step) are
  the same area.

---

## 5. Other Findings

### 5.0 How this register was built

Each of the 27 areas produced two independent reports. Findings were then
**cross-reviewed**: findings reported by both roles were merged into one entry
credited to both; findings reported by only one role were kept but marked
"single-reviewer"; claims that the other role contradicted were verified
against the source before inclusion.

**Root causes that two or more independent reviewers found separately** were
merged into a single entry — this is the strongest signal in the whole audit.
Six such merged findings are marked **[MERGED ×N]** below:

| Merged finding | Independent discoverers | Areas |
|---|---|---|
| The queue snapshot rewrites the whole settings DataStore every 5 s | 3 | AN-03 B, AN-05 B, AN-16 B |
| `NeDotifyApp.audioCache` blocks the main thread with `runBlocking` | 3 | AN-01 A, AN-01 B, AN-16 B |
| The OAuth redirect / pending login is consumed before the exchange succeeds | 4 | AN-01 A, AN-01 B, AN-09 A, AN-09 B |
| The provider mutex is held across network I/O | 3 | AN-09 A, AN-09 B, AN-10 B |
| The exported `PlaybackService` accepts any Media3-"trusted" controller | 2 | AN-01 B, AN-03 B |
| `startFlow()` silently flips the persisted `autoplay` setting | 2 | AN-02 B, AN-16 B |

### 5.1 P2 - MEDIUM

> **The complete, authoritative P2 register - P2-01 … P2-79, with the full
> evidence format for every entry — is in
> `docs/audits/ANDROID_FINDINGS_REGISTER.md`.** The entries below are the
> same findings; the register carries the two findings that arrived after
> this section was written and expands the compact rows into the full
> description / cause / trigger / impact / evidence / repro / fix /
> side-effects format.

---

#### P2-01 — The playback queue snapshot rewrites the entire settings DataStore every 5 seconds **[MERGED ×3]**

* **Areas:** AN-03 (PlaybackService) · AN-05 (queue) · AN-16 (preferences) · **Found by:** B in all three
* **Files:** `android/app/src/main/java/ru/nedotify/app/player/PlaybackService.kt:183-186`, `:333-342`; `android/app/src/main/java/ru/nedotify/app/data/Preferences.kt:38`, `:49`; `android/app/src/main/java/ru/nedotify/app/NeDotifyApp.kt:24-31`
* **Status:** CONFIRMED (three independent reviewers, plus the DataStore `PreferencesSerializer.writeTo` behaviour read from the shipped 1.2.0 AAR)
* **Description.** The queue checkpoint is stored **in the settings DataStore** under `queue_v1` as a JSON blob. `checkpointQueue()` is called from a 5-second timer while playing **and** on every `EVENT_POSITION_DISCONTINUITY` (i.e. every seek). The snapshot embeds `player.currentPosition`, so the de-duplication guard `if(snapshot!=lastCheckpoint)` can never suppress a write while anything is playing. Each write makes DataStore re-serialise and atomically rewrite the **whole** preferences protobuf.
* **Cause.** Session state (the queue) was placed in the same key/value file as the user's settings, and the checkpoint cadence was chosen to preserve the playback position, which changes on every tick — so the "did anything change?" comparison includes the one field that always changes.
* **Trigger conditions.** Any playback. ~12 writes/min, ~720/hour; plus one full rewrite per seek.
* **User impact.** Sustained write traffic and fsync for the whole listening session, proportional to the queue size: with ~20-character track ids a 200-track queue is a ~5 KB blob and a 1000-track queue ~25 KB → roughly 60 KB/min and **18 MB/hour** of file writes, plus 720 fsyncs/hour. On a device with slow eMMC this competes with the audio-cache writes. Additionally, the JSON is built and string-compared **on the main thread** (the service scope is `Dispatchers.Main.immediate`).
* **Evidence.**
```kotlin
// PlaybackService.kt:333-342
private fun checkpointQueue() {
    val ids=JSONArray((0 until player.mediaItemCount).map {player.getMediaItemAt(it).mediaId})
    val order=player.shuffleOrder
    val shuffled=mutableListOf<Int>();var index=order.firstIndex
    while(index!=C.INDEX_UNSET && shuffled.size<player.mediaItemCount){shuffled+=index;index=order.getNextIndex(index)}
    val snapshot=JSONObject().put("version",2).put("ids",ids).put("index",player.currentMediaItemIndex)
        .put("currentId",player.currentMediaItem?.mediaId).put("position",player.currentPosition)
        .put("repeat",player.repeatMode).put("shuffle",player.shuffleModeEnabled).put("shuffleOrder",JSONArray(shuffled)).toString()
    if(snapshot!=lastCheckpoint){lastCheckpoint=snapshot;app.saveQueue(snapshot)}
}
```
```kotlin
// Preferences.kt:38,49
suspend fun saveQueue(json:String) { store.edit { it[QUEUE]=json } }
private val QUEUE=stringPreferencesKey("queue_v1")
```
```kotlin
// PlaybackService.kt:122-125 — also fires on every seek
override fun onEvents(player:Player,events:Player.Events) {
    if(events.containsAny(...,Player.EVENT_POSITION_DISCONTINUITY))checkpointQueue()
}
```
* **Reproduction / verification.** Play with a 300-track queue and watch the file's mtime: `adb shell run-as ru.nedotify.app ls -l files/datastore/`. It advances every 5 s and its size tracks the queue. Unit-level: build two snapshots 5 s apart with identical ids/index/shuffle and a different `position` — they are unequal, so `saveQueue` is called twice.
* **Recommended fix.** Separate the *queue shape* from the *position*: compare only ids/index/currentId/repeat/shuffle/shuffleOrder for the de-duplication decision, and persist the position on a slower cadence (or on pause/stop/transition). Better: move the snapshot out of the settings file entirely (a dedicated file or a Room table) so the settings file is not rewritten at all.
* **Fix side effects.** A slower position cadence widens the window in which a process kill loses progress on resume; a separate small "position" preference key avoids that. Moving the blob out of DataStore changes `Preferences.queue()` and orphans the `queue_v1` key (old installs silently lose their restored queue once).
* **Note on prior art:** `android/review/REVIEW_RESOLUTION.md:45` claimed this fixed ("history и queue отбрасывают одинаковые снимки"). `ListeningHistory` does discard identical records; the **queue** snapshot never does, because the position is inside the compared value. **Partial fix of a previously-closed item.**

---

#### P2-02 — `NeDotifyApp.audioCache` blocks the main thread with `runBlocking` for up to 1.5 s at every cold start **[MERGED ×3]**

* **Areas:** AN-01 (app shell) · AN-16 (preferences) · **Found by:** A and B in both
* **Files:** `android/app/src/main/java/ru/nedotify/app/NeDotifyApp.kt:20-23`; triggered from `android/app/src/main/java/ru/nedotify/app/player/PlaybackService.kt:53-56`; reached via `android/app/src/main/java/ru/nedotify/app/ui/MusicViewModel.kt:103-106`
* **Status:** CONFIRMED
* **Description.** `audioCache` is a `by lazy` whose initializer performs a **blocking** read of the DataStore on the calling thread:
```kotlin
val audioCache by lazy {
    val megabytes=runBlocking(Dispatchers.IO) {withTimeoutOrNull(1_500) {repository.audioSettings.settings.first().cacheLimitMb}?:256}
    SimpleCache(File(cacheDir,"audio"),LeastRecentlyUsedCacheEvictor(megabytes.toLong()*1024*1024),StandaloneDatabaseProvider(this))
}
```
`runBlocking` parks the **caller**. The only caller is `PlaybackService.onCreate`, which the framework always runs on the **main thread**. Media3 binds with `BIND_AUTO_CREATE`, so the service is created as part of the first Activity launch — before the user has pressed play.
* **Cause.** A lazily-initialised, `runBlocking`-based read of a persistent setting inside a `Service.onCreate` on the main thread, combined with a controller bind that auto-creates the service.
* **Trigger conditions.** Every cold start (and after every process death).
* **User impact.** A visible up-to-1.5 s UI freeze before the first frame is interactive, plus the `SimpleCache` + `StandaloneDatabaseProvider` construction (real disk I/O) on the same thread. On slow storage the first frame can be delayed well past the point where the app feels hung. Below the 5 s ANR budget, so it is jank rather than an ANR — but it lands on every cold start.
* **Reproduction / verification.** `adb shell am start -W -n ru.nedotify.app/.MainActivity` and compare `TotalTime`; or enable `StrictMode` with `detectDiskReads()` on the main thread in a debug build and watch the `NeDotifyApp.audioCache` frame fire.
* **Recommended fix.** Publish the limit asynchronously into a `@Volatile` field with a 256 MB default, and build the `SimpleCache` from that field. `LeastRecentlyUsedCacheEvictor` exposes `setMaxCacheSize`, so the real limit can be applied later without recreating the cache.
* **Fix side effects.** For the first seconds of playback the cache uses the default limit; if the user's limit is *smaller* the cache briefly exceeds it before being trimmed. A second background read is still required to learn the value. Note that re-creating a `SimpleCache` over the same directory while the old one is alive trips Media3's "another SimpleCache instance uses the same directory" lock, so a re-create must release the previous instance first.
* **Note:** this is **not** the previously-rejected B P2-12. That rejection covered the claim that the `SimpleCache` *constructor* scans the cache directory on the main thread; it does not cover the separate `runBlocking` in the same `lazy` initializer, which is still present.

---

#### P2-03 — The OAuth callback and the pending PKCE login are consumed before the token exchange succeeds **[MERGED ×4]**

* **Areas:** AN-01 (app shell) · AN-09 (provider auth) · **Found by:** A and B in both
* **Files:** `android/app/src/main/java/ru/nedotify/app/MainActivity.kt:29-38`; `android/app/src/main/java/ru/nedotify/app/data/ProviderConnections.kt:93-105`
* **Status:** CONFIRMED
* **Description.** Two independent losses stack:
  1. `MainActivity.readOAuth` dispatches the redirect into an in-memory coroutine and then **immediately** clears `intent.data`, so the payload exists nowhere but in a process-bound coroutine:
```kotlin
private fun readOAuth(intent:Intent) {
    val uri=intent.data?:return
    if(uri.scheme=="nedotify" && uri.host=="oauth" && uri.path=="/spotify")model.handleSpotifyRedirect(uri.toString())
    intent.data=null
}
```
  2. `ProviderConnections.handleSpotifyRedirect` **deletes** the single-use `spotify_pending` record (which holds the PKCE verifier) **before** the token exchange:
```kotlin
if(awaiting.clientId!=clientId)throw SourceFailure("Настройки Spotify изменились. Начните вход заново")
store.remove("spotify_pending");pending=null
val body=FormBody.Builder().add("client_id",clientId).add("grant_type","authorization_code")
    .add("code",code).add("redirect_uri",AuthPkce.REDIRECT).add("code_verifier",awaiting.verifier).build()
val received=ProviderToken.response(network.json(Request.Builder().url(endpoints.spotifyToken).post(body).build()),now())
```
  A transient failure at the token endpoint (no connectivity, captive portal, a 5xx — the call timeout is 30 s) therefore destroys **both** the authorization code and the verifier, and there is no retry path.
* **Cause.** Single-use is implemented by *deleting* the pending rather than by *consuming* it, and consumption happens before the one step that can still fail for reasons unrelated to the user's intent. The Activity additionally treats the redirect as fire-and-forget.
* **Trigger conditions.** Any transient failure of `POST https://accounts.spotify.com/api/token`; or a process kill during the exchange window.
* **User impact.** The user completes the Spotify sign-in in the browser, returns to the app, and is told the login failed. The consent grant is thrown away and the whole browser round-trip must be repeated. A process kill in the window loses the login **silently** — no message at all.
* **Reproduction / verification.** Put the device behind a proxy that returns 503 for `accounts.spotify.com/api/token` but 200 for `accounts.spotify.com/authorize`; complete the authorisation; observe the failure and that a second attempt without restarting the login yields «Нет активного входа Spotify».
* **Recommended fix.** Keep the pending record (and the verifier) until the exchange has *succeeded*, or has failed with a definitively non-retryable status (`invalid_grant`/400); a 5xx/timeout should leave the pending intact. On the Activity side, stop nulling `intent.data` unconditionally — or null it only after the ViewModel reports success. Additionally, the `savedInstanceState == null` guard in `onCreate` should be replaced by an explicit "already consumed" marker (the encrypted store already holds the single-use pending, so it can be the source of truth).
* **Fix side effects.** Retaining the pending widens the replay window from "until the exchange starts" to "until the pending's 10-minute expiry"; a per-attempt "exchange already attempted" flag inside the pending record bounds it to one retry. The `state` must remain single-use, and the code is single-use server-side, so a retry is only safe where the request provably never reached Spotify.

---

#### P2-04 — The exported `PlaybackService` accepts any Media3-"trusted" controller, and Media3's trust predicate includes "enabled notification listener" **[MERGED ×2]**

* **Areas:** AN-01 (app shell) · AN-03 (playback service) · **Found by:** B in both
* **Files:** `android/app/src/main/AndroidManifest.xml:29-32`; `android/app/src/main/java/ru/nedotify/app/player/PlaybackService.kt:85-105`
* **Status:** CONFIRMED — Media3's trust semantics were established by `javap` decompilation of the exact AAR this project pins (`media3-session:1.11.1`)
* **Description.** The service is exported with a `MediaSessionService` intent filter, so any app on the device can bind. `onConnect` is the only gate:
```kotlin
override fun onConnect(mediaSession:MediaSession,controller:MediaSession.ControllerInfo):MediaSession.ConnectionResult {
    return if(controller.packageName==packageName || controller.isTrusted)
        MediaSession.ConnectionResult.accept(MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS,MediaSession.ConnectionResult.DEFAULT_PLAYER_COMMANDS)
        else MediaSession.ConnectionResult.reject()
}
```
`controller.isTrusted` is **not** a signature check. In Media3 1.11.1 it is true when the connecting UID is 1000 (system), the app's own UID, **or** the connecting package holds `STATUS_BAR_SERVICE`, **or** `MEDIA_CONTENT_CONTROL`, **or** is an *enabled notification-listener service*. `DEFAULT_PLAYER_COMMANDS` is `Player.Commands.Builder.addAllCommands()` — the complete set, including `COMMAND_SET_MEDIA_ITEM` and `COMMAND_ADD_MEDIA_ITEMS` — and `onPlayerCommandRequest` returns `RESULT_SUCCESS` unconditionally.
* **Precise residual risk.** A trusted third party **can**: read the Now-Playing metadata and the entire queue (media ids + titles — the user's listening history and library contents); drive transport; and replace, reorder, remove or clear the queue with any subset of tracks already in the Room library. It **cannot** inject a URI or an arbitrary media item — `onSetMediaItems`/`onAddMediaItems` discard the controller's `MediaItem`s except for `mediaId` and rebuild every item from the database row (`readQueue` → `selectQueue` → `dao.tracks(ids)` → `mediaItems(...)`); an id absent from the library is dropped, and an all-unknown list yields «В очереди нет доступных треков». It **cannot** reach the OAuth tokens, and it **cannot** spoof its package name (Media3 validates the package against the calling UID via `SessionUtil.checkPackageValidity` before `onConnect`).
* **Trigger conditions.** The user installs an app and grants it notification-listener access (or the app holds `MEDIA_CONTENT_CONTROL`). That app binds and is accepted. No interaction inside NeDotify is required.
* **User impact.** Silent disclosure of what the user is listening to and of their library contents, and an external app taking over playback and the queue. There is no indication inside NeDotify that a third-party controller is connected.
* **Reproduction / verification.** On an API 33+ device, install a minimal app that requests `NotificationListenerService` access, binds to `ru.nedotify.app/.player.PlaybackService` with a `MediaController`, and observe that the connection is **accepted**. Then call `setMediaItems` with an attacker URI and observe that the played URI is `nedotify://track/<id>`.
* **Recommended fix.** Split the acceptance by controller identity: accept the full command set only when `controller.packageName == packageName`; for every other controller accept `DEFAULT_UNTRUSTED_SESSION_COMMANDS` / `DEFAULT_UNTRUSTED_PLAYER_COMMANDS` (read-only + transport), or reject outright.
* **Fix side effects.** System controllers (Android Auto, Assistant, Wear, Bluetooth) would lose `COMMAND_SET_MEDIA_ITEM` and the ability to replace the queue. This app exposes no `MediaBrowser`/library service, so the loss is confined to queue replacement by external controllers — but it must be re-verified on a device with Android Auto and with a headset.

---

#### P2-05 — A single provider mutex is held across provider network I/O, so one slow provider stalls every other provider operation **[MERGED ×3]**

* **Areas:** AN-09 (provider auth) · AN-10 (catalog providers) · **Found by:** A and B in both
* **Files:** `android/app/src/main/java/ru/nedotify/app/data/ProviderConnections.kt:21` (the mutex), `:62-74` (`action`), `:103`, `:109-110`, `:135-139` (the network calls inside it)
* **Status:** CONFIRMED
* **Description.** `ProviderConnections` serialises *all* provider state transitions through one `Mutex`, and `action` holds it across the body of the block — including the HTTP calls made by `handleSpotifyRedirect` and `saveYandexToken`. The Spotify **token refresh** is likewise performed inside the lock. The same mutex is required by `get()`, `postYandex()`, `spotifyAccess()` and `yandexScope()` for every catalogue read and every Yandex stream resolution.
* **Cause.** The mutex is used simultaneously as the credential-state mutex, the single-flight refresh gate and the busy-flag gate, so it must be held across I/O that could be done outside it. The generation/`checkAccess` machinery at `:156-159` and `:183-191` already provides the consistency guarantee a network call outside the lock would need.
* **Trigger conditions.** An expired Spotify token (roughly hourly) combined with a degraded or slow network; or any provider action while a login/logout is in flight. The OkHttp call timeout is 30 s.
* **User impact.** The catalogue dialog shows an indefinite spinner (up to 30 s) and the **unrelated Yandex** collection is blocked by a Spotify problem. A Yandex track transition and the download worker both block on the same lock, so they hit the 15 s `sourceDeadline` in `LibraryRepository.resolve` and fail with «Источник не ответил вовременить». The Settings panel disables **every** control (`enabled=!status.busy`).
* **Evidence.**
```kotlin
// ProviderConnections.kt:62-74
private suspend fun <T> action(block:suspend ()->T):T=withContext(Dispatchers.IO) {
    lock.withLock {
        _status.value=_status.value.copy(busy=true,error=null)
        try {load();block()}
        ...
        finally {publish();_status.value=_status.value.copy(busy=false)}
    }
}
// ProviderConnections.kt:135-139 — the refresh POST runs inside the lock
val response=try {network.json(Request.Builder().url(endpoints.spotifyToken).post(body).build())}
```
* **Reproduction / verification.** `MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE)` on the token endpoint, then start a second provider call (`session.spotify.search(...)`) and observe that it does not reach the server until the first call times out.
* **Recommended fix.** Narrow the lock to the credential-state critical sections (read/compare/increment the generation) and move the HTTP work outside it, using a separate single-flight `Deferred` keyed by generation for the refresh — the same shape `SoundCloudClient` already uses in `data/Sources.kt:58-79`.
* **Fix side effects.** The current code is what guarantees "one refresh for N concurrent expired requests" (pinned by `ProviderConnectionsTest.kt:57-68`) and the generation fences that stop a stale response from repopulating a logged-out account (`:192-232`). Splitting the lock without an explicit single-flight primitive would reintroduce both, so the replacement must be built and tested first. The `busy` flag must move out of the lock so it reflects the actual in-flight work.

---

---

#### P2-06 — `startFlow()` permanently flips the user-visible "Продолжать музыку" setting to ON and never restores it **[MERGED ×2]**

*Area:* AN-02 (ViewModel) · AN-16 (preferences) · *Found by:* B in both · *Files:* `ui/MusicViewModel.kt:285-295`; `ui/AudioSettingsControls.kt:78-82`; `player/PlaybackService.kt:191-195`
*Status:* CONFIRMED
**Description.** `startFlow()` — a one-shot action on the Home screen — persists `AudioSettings.autoplay = true` into the `nedotify_audio` DataStore. `autoplay` is the *global* user preference "Продолжать музыку — Добавлять похожие треки, когда очередь заканчивается", and it drives the service's autoplay loop for **every** queue, not just the Flow queue. A repo-wide grep shows exactly one writer of `autoplay=true` and no writer of `autoplay=false` other than the Settings switch. The write happens *before* `playSelected`, so it persists even when the Flow fails to start.
**Cause.** One persisted field serves two unrelated concepts — a transient action ("start a Flow now") and a persistent preference.
**Trigger:** any tap on the Flow card. **Impact:** from then on every queue auto-appends recommendations when it ends, across restarts, with no snackbar and no indication that a setting changed.
**Evidence.** `MusicViewModel.kt:292` `repository.audioSettings.update {it.copy(autoplay=true)}`; `AudioSettingsControls.kt:82` is the user-facing switch; `PlaybackService.kt:193` is the global loop it enables. The desktop keeps them apart — its Flow is a separate persisted flag `player.queue_autopilot` (`ui/web_new_v2/js/player.js:260-307`) while `audio.autoplay` is a session-restore flag (`core/session.py:92-96`).
**Repro:** Settings → Плеер → "Продолжать музыку" = OFF → Home → tap the Flow card → reopen Settings → the switch is ON and stays ON after a restart.
**Fix:** do not use a global preference as a transport for a session intent — either a per-queue "radio mode" owned by the service, or a distinct `flow_enabled` key mirroring the desktop.
**Side effects:** a per-queue flag means the Flow queue no longer survives a service restart; a separate key needs a default/migration decision.

---

#### P2-07 — The listening report is recomputed from SQL every 5–60 seconds while the profile screen is open, even when nothing changed **[MERGED ×2]**

*Area:* AN-02 (ViewModel) · AN-14 (discovery/reports) · *Found by:* B in both · *Files:* `ui/MusicViewModel.kt:61-75`; `data/ListeningReports.kt:143-148`, `:66-82`; `data/Models.kt:146-176`
*Status:* CONFIRMED
**Description.** Two independent refresh triggers fire the same six-statement aggregate:
1. `reportClock` is a cold flow emitting every 60 s. It is combined with `reportRetry` and fed into an **inner** `flatMapLatest`, so every tick **cancels the current Room subscription and starts a new one**, which immediately re-runs `dao.reportSnapshot(window)` — six aggregate statements, three of which are full scans/joins over the whole `history` table. The tick was meant to roll the local-day boundary; it re-subscribes every minute instead of only when the calendar day changes.
2. `dao.observeReportChanges(SimpleSQLiteQuery("SELECT 1"))` is declared `@RawQuery(observedEntities = [ListeningSession::class, Track::class])`. The `history` table **is** `ListeningSession`, and the service writes it every 5 s while playing — so the whole snapshot is rebuilt every 5 s, not every 60 s. The 60 s clock is only the *idle* trigger.
With `ReportPeriod.ALL` (`startInclusive = Long.MIN_VALUE`) four of the six queries scan the entire `history` table, and `dailyQuery()` evaluates a **365-branch `CASE`** per row (731 bound arguments — under SQLite's 999 limit, so it is valid but expensive).
**Cause.** The invalidation signal is bound to the raw tables rather than to "the report window changed" or "the aggregate changed"; nothing throttles recomputation, and the `ALL` window removes the natural time bound.
**Trigger:** the Profile screen is open. **Impact:** constant needless SQLite load and battery drain while the user only *looks* at statistics. With a year of history (~36 500 sessions) the `ALL` period costs ~13.3 M integer comparisons plus a temp B-tree `GROUP BY` over a computed expression, **four times over, every 5 seconds**. The numbers do not change between ticks — the work is pure waste.
**Evidence.** `Models.kt:147-148` `@RawQuery(observedEntities = [ListeningSession::class, Track::class])`; `Models.kt:170-176` `reportSnapshot` runs all six queries in one transaction per emission; `ListeningReports.kt:66-82` the 365-branch `CASE`; `MusicViewModel.kt:62-66` the 60 s clock. Index coverage is partial: `index_history_startedAt` and `index_history_trackId` exist, but there is **no** composite index supporting `GROUP BY trackId` + `ORDER BY SUM(listenedMs)`, and none supporting the `CASE` grouping; `reportTopArtists` groups on `TRIM(t.artist)`, a non-indexed expression.
**Repro:** open Profile, select "Всё время", start playback, and watch the Room query log — the six queries re-execute every ~5 s with no user action.
**Fix:** decouple the refresh from the raw invalidation — observe a throttled "report epoch" for the expensive `ALL` queries, keep `reportRetry` as the explicit user trigger, and make the clock emit only on a day rollover. For `ALL`, pre-aggregate per day instead of a 365-branch `CASE`.
**Side effects:** a debounce means the headline total can lag by the debounce interval. `ListeningReportsDaoTest.checkpointsAndTrackMetadataUpdateAnAlreadyCollectedReport` (`androidTest/…`) explicitly asserts that a `putSession` **immediately** updates an already-collected report — that test would need relaxing, or the fix must keep session-level freshness while throttling the `ALL`-period queries.

---

#### P2-08 — `importCatalog()` is an unbounded (worst case ≈2 h 45 m), non-resumable, main-dispatcher batch of up to 1 000 sequential network round-trips **[MERGED ×2]**

*Area:* AN-02 (ViewModel) · AN-10 (catalog) · *Found by:* B in both · *Files:* `ui/MusicViewModel.kt:369-394`; `data/CatalogMatcher.kt:66-76`; `data/Sources.kt:91-100`; `ui/CatalogBrowser.kt:52`
*Status:* CONFIRMED
**Description.** The import takes up to 500 catalogue entries and resolves each **sequentially**; each resolution runs up to **two** provider searches serially under a 20 s `withTimeout` per item. Worst case `500 × 20 s ≈ 2 h 46 m`; typical 8–25 minutes of sustained HTTPS traffic. The job runs in `viewModelScope` (`Dispatchers.Main.immediate`), so the SoundCloud JSON parse (`sourceObject(network.get(...))` — `MusicNetwork.get` returns a `String` and does **not** switch dispatcher) executes on the **main thread** once per item; the response is 126 KB (`android/review/PROVIDER_PROBE.json:22-27`). The only way to stop it is to dismiss the catalogue dialog; the import button is disabled while working and there is no cancel affordance.
**Cause.** An unbounded-duration batch is modelled as a UI-scoped coroutine instead of a persisted, resumable job — even though the codebase already has WorkManager for downloads.
**Trigger:** opening a Spotify/Yandex playlist with 200–1000 tracks and tapping "Импортировать список". **Impact:** the radio and CPU stay busy for tens of minutes; if the process is killed at item 400/500 **all** progress is lost with no partial import, no resume and no record of what failed; each parse is a main-thread stall.
**Evidence.** `MusicViewModel.kt:377-383` the serial loop; `CatalogMatcher.kt:69` the serial two-provider loop; `Sources.kt:47-49` `MusicNetwork.get` returns a `String` with no dispatcher switch; `CatalogBrowser.kt:52` the only control, disabled while working.
**Repro:** connect a Spotify account, open a ≥200-track playlist, tap import, then `adb shell am force-stop ru.nedotify.app` mid-way: no playlist is created and no error is shown on the next launch.
**Fix:** move the batch into a WorkManager job with a persisted per-item progress table; bound the per-item timeout for the batch path (20 s is sized for a single user-initiated play); run the resolution on an IO dispatcher with bounded concurrency (2–4) instead of serially; add an explicit cancel control.
**Side effects:** a WorkManager job needs foreground-service notification handling for long jobs and must re-initialise the provider connection across process restarts (`ProviderConnections` re-reads from the Keystore on `initialize()`). Bounded concurrency raises the request rate and may trip provider rate limits.

---

#### P2-09 — `runBlocking` inside the `ResolvingDataSource` pins a Media3 loader thread and makes the network resolution non-cancellable

*Area:* AN-03 (PlaybackService) · *Found by:* B · *Files:* `player/PlaybackService.kt:60-69`; `data/LibraryRepository.kt:76`
*Status:* CONFIRMED (code path and Media3 1.11.1 cancellation semantics verified from the shipped AAR)
**Description.** The stream URL is resolved inside the `ResolvingDataSource` resolver, which Media3 invokes from `DataSource.open()` — a **synchronous** contract. The resolver bridges the suspend `repository.resolve(track)` with `runBlocking`:
```kotlin
val source=ResolvingDataSource.Factory(cached) {spec->
    if(spec.uri.scheme!="nedotify")spec else runBlocking {
        val track=repository.dao.track(spec.uri.lastPathSegment.orEmpty())?:throw SourceFailure("Трек отсутствует в библиотеке")
        val resolved=repository.resolve(track)
        ...
    }
}
```
Two consequences: (a) the call occupies a dedicated Media3 loader thread for the whole resolution, bounded by the 15 s `sourceDeadline`; (b) **`runBlocking` creates a coroutine that is not a child of the loader's job**, and Media3's `Loader.cancelLoading()` only calls `LoadTask.cancel(false)` → `onLoadCanceled()` and does **not** interrupt the executor thread (verified in the 1.11.1 bytecode). When the user seeks away, removes the item, or the player is released, the in-flight resolution keeps running to completion, the `StreamCache` single-flight slot stays occupied, and the loader thread stays parked.
**Cause.** A suspend-based resolution placed behind a synchronous framework callback with a blocking bridge.
**Trigger:** any remote track; worst case a slow provider, or a seek/queue change during resolution. **Impact:** a visible stall of up to 15 s at the start of a track whose provider is slow, plus an unabandonable network request; repeated seeks park several loader threads.
**Repro:** instrument the resolver with a log before/after `runBlocking` and observe the gap; start a track on a slow provider, seek away within a second, and confirm the first resolution still runs to completion.
**Fix:** move resolution out of the synchronous `open()` contract — resolve the next item's URL in a service coroutine and substitute the resolved URI into the `MediaItem` before the player prepares it, or serve the stream through an out-of-band local proxy (the desktop oracle's design, `core/proxy.py`). At minimum, bridge the coroutine to the loader thread through a `Future`/`ListenableFuture` the loader's cancellation can cancel, instead of `runBlocking`.
**Side effects:** resolving ahead of the item means the URL can expire between resolution and playback, and the resolved URL would be visible in the `MediaItem` handed to external controllers unless the URI is kept internal. A cancellable bridge adds a failure mode (cancellation must surface as a playback error, not a hang).
**Note:** `android/review/REVIEW_RESOLUTION.md:40` already declared the blocking part open; the report sharpens it — the wait is also **not cancellable**, which the resolution text did not state.

---

#### P2-10 — Replacing the current `MediaItem` in place is reported by Media3 as a media-item *transition*, splitting one listen into two sessions and marking the first "completed"

*Area:* AN-03 (PlaybackService) · *Found by:* B · *Files:* `player/PlaybackService.kt:110-117`, `:274-285`; `player/ListeningHistory.kt:14-20`
*Status:** CONFIRMED (the Media3 reason mapping verified from the 1.11.1 bytecode)
**Description.** `refreshQueueSources` swaps the current queue entry for the same track with a different `MediaItem` (a different URI: `nedotify://track/<id>` → `nedotify-offline://track/<id>`, plus an `OfflineAsset` tag) via `player.replaceMediaItem(index, item)`. A different URI means a different `MediaSource`, hence a different window uid, hence Media3 reports it through `onMediaItemTransition` — which the service interprets as "the user moved to another track". `MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED` is the **only** reason for which `forceNewSession` can be false, and in Media3 1.11.1 that reason is emitted only when the player was **not** playing. So while playing, a source replacement always yields `AUTO`/`SEEK` → `forceNewSession = true` **and** `completedPrevious = true`. That contradicts the contract written in `ListeningHistory` itself: *"Switching the same recording from a signed URL to a local/offline URI is a source refresh, not another listen."* — the branch that implements that contract is unreachable for an in-place replacement.
**Cause.** The service re-derives the listening-session boundary from Media3's coarse 4-value transition-reason enum, although the service is the component that performed the replacement and already knows the item was replaced in place rather than advanced to.
**Trigger:** the current item is replaced while playing — i.e. offline mode is toggled on while a downloaded track plays, or the current downloaded track is re-downloaded (its generation changes). **Impact:** the report shows **two** sessions for one listen, and the first is flagged `completed = true` although the user never finished the track; `completedSessions` and `sessions` are inflated. The total listened ms is preserved (the rows are summed), so no time is fabricated — but the session/completion semantics are wrong, and they diverge from the desktop oracle where one listen is one record.
**Repro:** download a track, start playing it, toggle offline mode on. Inspect `history`: two rows for the same `trackId`, the earlier with `completed = 1`.
**Fix:** have the service tell `ListeningHistory` explicitly when a replacement is a source refresh (e.g. `history.transition(id, completedPrevious = false, forceNewSession = false)`), instead of inferring it from the transition reason.
**Side effects:** the transition listener would then have to suppress the subsequent automatic `onMediaItemTransition` for the same media id (a one-shot suppression flag). `forceNewSession=false` also means the clock is not reset, so the elapsed time continues accumulating across the source change — the intended behaviour.

---

#### P2-11 — A closed pending-selection gate swallows the user's Play command with no error and no state change

*Area:* AN-05 (queue) · *Found by:* A · *Files:* `player/DualDeckPlayer.kt:230-231`; `player/PlaybackService.kt:85-88`; `player/PendingSelectionGate.kt:21-30`
*Status:* CONFIRMED
**Description.** `PendingSelectionGate` has three states: idle-open, pending-open, and **closed** (`interruptPending()` cancelled the pending future, `pending == null`, `playAllowed == false`). While closed, `handleSetPlayWhenReady(true)` returns `Futures.immediateVoidFuture()` — no player action, **no `SessionError`**, and the controller is meanwhile told "success", because `onPlayerCommandRequest` returns `SessionResult.RESULT_SUCCESS` unconditionally and Media3 answers the controller at *enqueue* time (`MediaSessionStub.queueSessionTaskWithPlayerCommand` → `onPlayerCommandRequestOnHandler` → `addToCommandQueue`) — i.e. **before** the gate is ever consulted. The play is refused at the player level but reported as accepted at the session level.
**Cause.** the gate expresses a refusal only as a boolean consulted deep inside `DualDeckPlayer`; there is no path from that refusal back to the session/controller/UI. `PlaybackService` has exactly one feedback channel for player-level problems (`onFocusDenied` → `session.sendError(...)`) and the gate is not wired into it.
**Trigger:** a player command (notification pause, `ACTION_AUDIO_BECOMING_NOISY`, an audio-focus loss, or a seek/shuffle/repeat from another controller) lands while a queue set is still in flight. **Impact:** the user presses Play and **nothing happens** — no sound, no state change, no snackbar, no log entry. The player stays paused. The second press works (it re-opens the gate via `receivedPlayCommand()`), so the gate is not permanently stuck, but the first press is silently lost.
**Repro:** issue a pause/noisy while a queue set is being resolved (`readQueue` → `queueTracks` on `Dispatchers.IO`), then press Play. The first Play is dropped without any message. Unit-level: closed gate + `handleSetPlayWhenReady(true)` → no player call, no error emitted — no test asserts any user-visible signal for this path.
**Fix:** give the refusal a user-visible signal — expose a "play refused" reason on the gate and raise the same `SessionError` the focus-denial path raises.
**Side effects:** an error on every refused play can become noisy; the message must not blame the user and must not be shown when a newer play command is already queued.

---

#### P2-12 — The same interruption cancels the in-flight queue set, silently discarding the user's track selection

*Area:* AN-05 (queue) · *Found by:* A · *Files:* `player/PendingSelectionGate.kt:21-30`; `player/PlaybackService.kt:75`, `:297-319`
*Status:* CONFIRMED (Media3 half verified from the 1.11.1 bytecode)
**Description.** `interruptPending()` does not only close the gate — it calls `future.cancel(false)` on the `onSetMediaItems` future. In Media3 1.11.1 the session installs the resolved items only when that future completes successfully (`MediaSessionStub.handleMediaItemsWithStartPositionWhenReady` → `Util.postOrRunWithCompletion`, whose runnable is skipped for a cancelled future). A cancelled set therefore means **the resolved queue is never installed**: the previous playlist stays and the user's new selection is thrown away. The app reports nothing — `resolveFuture` only reports *exceptions*; a cancellation takes the `catch(cancelled:CancellationException)` branch and sends no `SessionError`. `MusicViewModel.startPrepared` does not observe the `setMediaItems` future at all, so the failure is invisible on the UI as well.
**Cause.** the gate conflates two different intents. Its documented purpose is to stop *an older queued play* from undoing another controller's pause/noisy; cancelling the *set* future additionally destroys the queue the user just asked for — a side effect the gate does not need, since the `playAllowed == false` check in `handleSetPlayWhenReady` already covers the play.
**Trigger:** a pause, becoming-noisy, a focus loss, or any command from another controller landing in the window between `onSetMediaItems` and the completion of the queue read (a few ms for a small queue, tens of ms for a 3000-item queue). **Impact:** the user taps a track; the old queue keeps playing; the new selection never appears; no error, no message. "Tapping a track does nothing."
**Repro:** make the queue read slow (a 2000+ track library), tap a track, and hit Pause on the notification within the resolution window. Deterministic unit variant: `PendingSelectionGate.begin(future)` → `interruptPending()` and assert the *set* future is still installable while the *play* is refused.
**Fix:** separate "abort the play" from "abort the queue" — `interruptPending()` should close the gate without cancelling the set future (or the service should keep the resolved items and install them paused).
**Side effects:** if the set future is not cancelled, Media3 installs the queue and then runs the controller's queued `prepare`/`play`; the play must still be refused by the gate, which the current `playAllowed` check does — so the "pause must not be undone" invariant is preserved. A user-initiated pause arriving mid-set then leaves the *new* queue installed but paused, which is the intended behaviour.

---

#### P2-13 — A transient audio-focus loss is reported as a "user interaction", cancelling the pending queue selection and the startup queue restore

*Area:* AN-04 (dual-deck player) · *Found by:* A · *Files:* `player/DualDeckPlayer.kt:248-251`; `player/PlaybackService.kt:75`; `player/PendingSelectionGate.kt:21-30`
*Status:** CONFIRMED
**Description.** `DualDeckPlayer` invokes `onUserInteraction` for `AUDIOFOCUS_LOSS_TRANSIENT` — a *recoverable* event by definition. The service implements `onUserInteraction` as "the user changed the playback intent" and it (a) bumps `interactionVersion`, (b) cancels the queue-restore job, (c) cancels the pending `setMediaItems` future and sets `playAllowed=false`, (d) cancels the error-recovery job.
**Cause.** the callback conflates "the user's intent changed" with "the system took the audio focus away". `PlaybackFocusState` already models the difference (`transientLoss()` keeps `requested=true`; `stop()` clears it), but the callback invocation does not follow it.
**Trigger:** the user taps a track while a `setMediaItems` is in flight (resolved asynchronously on `Dispatchers.IO`) at the same moment another app takes transient focus (a navigation prompt, a voice assistant). The same happens at app start while the saved queue is being restored. **Impact:** the tap silently does nothing — no queue, no playback, no error — and the user must tap again. At startup the saved queue is dropped and the app opens with an empty queue.
**Repro:** instrument `onUserInteraction`, or set a breakpoint on `PendingSelectionGate.interruptPending`; drive `DualDeckPlayer.audioFocusChanged(AUDIOFOCUS_LOSS_TRANSIENT)` while `PendingSelectionGate.pending` is non-null. No such test exists today.
**Fix:** split the callback into "user intent changed" and "playback was interrupted by the system". The transient branch should not invoke the user-interaction callback — the play intent is already preserved in `focusState`, and `cancelTransition()` + `active.pause()` cover the player side. Give the service a separate, non-destructive callback if it needs to invalidate the autoplay/recovery candidates.
**Side effects:** the gate exists precisely to drop a stale "prepare/play" queued before a competing pause/noisy, so the fix must keep the "stale play must not undo another controller's pause/noisy" invariant while allowing the *set* itself to survive.

---

#### P2-14 — A cross-device restore permanently duplicates local tracks and points playlists at the unplayable copy

*Area:* AN-07 (backup) · *Found by:* B · *Files:* `data/BackupMerge.kt:6-22`; `data/BackupCodec.kt:44-58`; `data/LibraryRepository.kt:72-74`
*Status:** CONFIRMED
**Description.** An incoming local track is matched to an existing library row **only** by the portable id, which is salted with the *source* device's library id (`portableTrackId(track, libraryId)` = SHA-256 of `libraryId + '\0' + track.id`). On restore, existing rows are hashed with the *destination* device's library id, so a backup produced by another device can never match. The local track is inserted as a new `portable-local:<hash>` row with an empty `localUri`, while the destination's own copy (`local:<mediaStoreId>`) stays. The song appears twice and the restored playlist links point at the placeholder — which is unplayable until the user re-attaches a file. The app has **no** track-deletion affordance anywhere (`dao` exposes only `deletePlaylist`, `deleteSmartPlaylist`, `deleteDownload`, `removeFromPlaylist`), so the duplicate cannot be removed.
**Cause.** the identity model conflates "same physical file" with "same library + same native id", and the library id is by design never replaced by an import.
**Trigger:** device B already has file F in MediaStore; the user restores a JSON backup exported from device A that contains F. **Impact:** the library permanently gains a duplicate, unplayable entry; every restored playlist contains the dead copy. The only recovery is clearing app data.
**Repro:** pure-JVM on the existing `BackupMerge` seam: `plan(BackupSnapshot(tracks=[Track("local:123", …, source="local")]), backup(tracks=[Track(portableIdFromOtherLibrary, …, source="local")]), libraryId)` → the plan contains **two** tracks for the same file, and `plan.links` reference the portable id. `BackupMergeTest` has no case for a cross-device local import; the closest test (`anotherDevicesMediaStoreIdCannotOverwriteThisDevicesFile`) asserts only that the native id is *not* overwritten — never that the file is not *duplicated*.
**Fix:** when an incoming local track has no portable-id match, try to reconcile it with an existing local row by content (title+artist+duration) and reuse that row's id, or at minimum surface the collision in the import notice and provide a way to drop the placeholder.
**Side effects:** content matching can merge two genuinely different files with identical tags — warning + allowing removal is safer than auto-merging. A track-deletion affordance is a wider product change.

---

#### P2-15 — Exporting a library with more than 20 000 tracks fails outright, and the error uses the read-side wording

*Area:* AN-07 (backup) · *Found by:* B · *Files:* `data/BackupCodec.kt:60-61`, `:168-171`, `:366`; `ui/MusicViewModel.kt:258-273`
*Status:* CONFIRMED
**Description.** `encode` starts with `checkCounts`, which rejects more than 20 000 tracks (and >2 000 playlists, >100 000 links, >100 000 sessions) with `invalid("слишком много записей")`. `invalid` hard-codes the prefix `"Не удалось прочитать копию: "` for **both** directions, so pressing "Сохранить копию" on a large library shows *"Не удалось прочитать копию: слишком много записей"* — a read error on a write path. The same applies to the 16 MB byte budget.
**Cause.** a single `invalid()` helper with a read-only message prefix is shared by the encoder and the decoder; the collection caps were sized for the decoder's untrusted-input budget and applied to the encoder without a separate policy.
**Trigger:** a library of 20 001+ tracks. **Impact:** the feature stops working for large libraries, and the message points at the wrong cause (the user never chose a file to read). The behaviour is already pinned by a passing test — `BackupCodecTest.kt:170`.
**Repro:** `BackupCodec.encode(LibraryBackup(…, tracks = List(20_001) { … }, …))` → `SourceFailure("Не удалось прочитать копию: слишком много записей")`.
**Fix:** split the error prefix by direction (encode → "Не удалось сохранить копию"), state the actual limit, and decide explicitly whether the export caps are a product limit (then say so in the UI) or should scale with the library.
**Side effects:** raising the caps increases the encode memory peak (P2-16) and the import attack surface; the **decoder** caps are the security-relevant ones and should stay independent of the export caps.

---

#### P2-16 — Decoding a backup the codec itself accepts needs ~120–150 MB of heap; the OOM escapes every `catch (Exception)` and kills the process

*Area:* AN-07 (backup) · *Found by:* B · *Files:* `data/BackupCodec.kt:116-124`; `data/LibraryBackupStorage.kt:27-42`; `ui/MusicViewModel.kt:266`
*Status:** CONFIRMED (heap profile measured on the JVM with the project's own `org.json:json:20250517`; the device heap limit was **not** measured)
**Description.** The format is bounded at 16 MB, but the *decoded* representation is not. The import path holds (a) the raw file bytes, (b) a **second** full copy from `ByteArrayOutputStream.toByteArray()`, (c) the decoded UTF-16 `String`, (d) the `JsonShape` grammar pass's transient `StringBuilder`s, and (e) a full `org.json` DOM. Measured with the same org.json version the project uses: a **16.4 MB** document (20 000 tracks + 70 000 sessions + 80 000 links — all inside the codec's own `MAX_TRACKS`/`MAX_SESSIONS`/`MAX_LINKS`) costs **87 MB** for the DOM alone, **120 MB** live after the DOM + `toString()` + `toByteArray()`, and the JVM **threw `OutOfMemoryError` at `-Xmx160m`** (survived at 256 MB). The Android platform `org.json` is a different implementation with the same `LinkedHashMap`/`ArrayList` DOM shape, so the order of magnitude carries over. `OutOfMemoryError` is an `Error`: `BackupCodec.decode` (`catch (_: Exception)`) and `MusicViewModel.backupTask` (`catch(error:Exception)`) do not catch it, so the process dies.
**Cause.** the codec materialises the whole document three to four times over instead of streaming, and the read path duplicates the input array before parsing.
**Trigger:** a large backup near the 16 MB cap on a device with a ~128–192 MB app heap limit. **Impact:** the app crashes while importing/exporting a large backup instead of reporting an error; the library is not damaged (the Room transaction rolls back) but the user sees the app die.
**Evidence.** `LibraryBackupStorage.kt:29-41` (BAOS buffer + `toByteArray()` + decode); `BackupCodec.kt:119-124` (String + strict-JSON pass + full DOM); `MusicViewModel.kt:266` `catch(error:Exception)`. Measured: `json utf8 bytes = 16 405 803` (cap 16 777 216) → `heap after DOM = 87 MB`, `after String = 104 MB`, `after bytes = 120 MB`; `OutOfMemoryError` at `-Xmx160m`; re-parse took 619 ms at `-Xmx256m`.
**Repro:** run the scratch measurement with the project's org.json jar at `-Xmx160m` and a 16 MB document, or import a max-size backup on a low-RAM device and watch for an OOM kill.
**Fix:** drop the `toByteArray()` copy (read into a right-sized array), parse incrementally, or lower `MAX_BYTES` to what the device can hold — and convert `OutOfMemoryError` into a `SourceFailure` so the user gets a message instead of a crash.
**Side effects:** lowering `MAX_BYTES` makes large libraries un-backupable (interacts with P2-15); a streaming parser is a large rewrite of `BackupCodec`.

---

#### P2-17 — A single unparsable smart playlist in a desktop library aborts the whole import, with a message that points at the wrong thing

*Area:* AN-08 (desktop import) · *Found by:* B · *Files:* `data/DesktopLibraryConverter.kt:63-67`, `:80-83`; desktop `services/smart_playlists.py:83-86`
*Status:* CONFIRMED
**Description.** The desktop's `smart_playlists.rule_json` column is nullable, and legacy `playlists.smart_rules_json` is likewise nullable. The converter takes the rule text and passes it straight into `desktopRules(json)`, whose first action is `BackupCodec.requireStrictJson(json)`. An empty string fails the strict grammar, so the whole import dies. The desktop app, given the very same row, **silently skips** that playlist (`except (TypeError, ValueError): continue`) and keeps working.
**Cause.** the converter treats "this one row is unusable" as a fatal condition, while the oracle treats it as a per-row skip. There is no per-row error collection, so the first bad smart playlist aborts 10 000 tracks of otherwise valid data.
**Trigger:** the user's desktop DB contains a smart playlist with a NULL/empty `rule_json` (created outside `SmartPlaylistService.create`, a partially migrated legacy DB, or an older desktop version). **Impact:** the import fails with "Не удалось прочитать копию: ожидается объект JSON" — wording that talks about a JSON *copy*, so the user has no way to know one smart playlist is the culprit.
**Repro:** insert `INSERT INTO smart_playlists(name, rule_json) VALUES ('X', NULL)` into a desktop-shaped DB and feed it to `DesktopLibraryImport.readSnapshot(file, "PC")` → `SourceFailure("Не удалось прочитать копию: ожидается объект JSON")`. A JVM unit test over `DesktopLibraryConverter.convert(..., smartRows = listOf(mapOf("id" to 1L, "name" to "X", "rule_json" to "", …)))` reproduces it without a device.
**Fix:** make the desktop-rule conversion per-row fault-tolerant: skip (and count) an unparsable rule set the way the desktop does, and report the count in the existing `notice` string; keep the whole-import abort for structurally broken input.
**Side effects:** a skipped smart playlist must be visible; bound the tolerance (only skip rule-parse failures, keep failing on other errors).

---

#### P2-18 — A missing desktop column is accepted silently: the import "succeeds" with dropped fields and no warning

*Area:* AN-08 (desktop import) · *Found by:* B · *Files:* `data/DesktopLibraryImport.kt:48`; `data/DesktopLibraryConverter.kt:22-37`, `:101-116`, `:134`
*Status:** CONFIRMED
**Description.** The reader selects only the columns that exist in the imported file (`columns.filter { it in available }`) and the converter then reads them with defaulting accessors. There is no "expected column missing" check, so a schema difference between the desktop build and the reader is indistinguishable from "the data is empty". The import reports success, the preview shows plausible counts, and the notice says nothing about the dropped field.
**Cause.** the reader treats the desktop's column set as optional input rather than as a contract it validates.
**Trigger:** the desktop renames a column, or the user copies a DB from an older build. Concretely reachable today: `history.listening_measured` is added by an `ALTER TABLE` in `core/database.py:216-224`, so any desktop DB created before that ALTER has no such column. **Impact:** silent data loss — `is_favorite` missing → every track imports as non-favourite; `added_at` missing → `timestamp(null)` → 0 → all imported tracks sort last and every `added_within_days` smart rule excludes them; `duration` missing → 0; `source` missing → `""` → the track is demoted to a local stub **and** is not counted in `unresolved` because `""` is in `setOf("local","","file")`, so the notice under-reports the damage. The `history` case is worst: the entire listening history is dropped and the notice phrases it as "Старая история без отметки измеренного времени не перенесена: N записей" — blaming old data, not a missing column.
**Repro:** build a desktop-shaped DB without `is_favorite` and `added_at` and run `DesktopLibraryImport(context).readSnapshot(file, "PC")` — the import succeeds, all tracks are `favorite=false, addedAt=0`, and the notice contains no hint that the columns were missing.
**Fix:** treat the allowlisted column set as a contract: fail with a precise message naming the column and the table, or import the row and add an explicit notice line ("В таблице tracks нет столбца is_favorite — избранное не перенесено"). Keep the tolerant path only for genuinely optional columns (`cover_url`, `source_url`).
**Side effects:** strictness can break the import for a merely older DB; the notice-based route keeps the import working while making the loss visible.

---

#### P2-19 — The desktop import inherits the backup codec's 16 MB ceiling, far below its own documented row caps, and reports it with a backup-format message

*Area:* AN-08 (desktop import) · *Found by:* B · *Files:* `data/DesktopLibraryConverter.kt:18`, `:70`; `data/BackupCodec.kt:30`, `:112`, `:174-252`
*Status:** CONFIRMED
**Description.** `DesktopLibraryConverter.convert` advertises caps of 20 000 tracks / 2 000 playlists / 100 000 links / 100 000 history rows, and `DesktopLibraryImport` enforces the same numbers — but the last step of the conversion round-trips the whole library through the JSON backup codec (`BackupCodec.decode(BackupCodec.encode(draft))`). `BackupCodec.encode` refuses anything above `MAX_BYTES = 16 MB`. **The effective ceiling is therefore ~16 MB of JSON, not the row caps.**
**Cause.** the desktop DB is transported through the *backup* format, so the backup format's byte budget silently governs the desktop import, and the two limit sets are not reconciled.
**Trigger:** a realistic heavy library. Per-row JSON cost from the codec's own writer: a track ≈ 250–300 B, a listening session ≈ 170–200 B, a playlist link ≈ 80 B. 10 000 tracks + 30 000 sessions + 40 000 links ≈ 11.7 MB (just under); add 10 000 sessions and the import crosses 16 MB. The desktop's own cap of 100 000 history rows is unreachable — 100 000 sessions alone are ≈ 18 MB. **Impact:** the import fails with "Не удалось прочитать копию: размер копии превышает 16 МБ" — a message about a JSON *copy*, for a file the user picked as a `.db` — during *preview*, so the user cannot even see the counts.
**Repro:** build a desktop-shaped DB with 10 000 tracks + 40 000 history rows and run `DesktopLibraryImport.readSnapshot(file, "PC")`; the estimator in `BackupCodec.checkEncodedSize` exceeds `MAX_BYTES`.
**Fix:** reconcile the two limit sets — give the desktop import its own budget and an error message naming the table that is too large, or document/enforce a single shared limit the desktop import can actually reach.
**Side effects:** raising the budget raises the peak memory of the JSON round trip (P2-16) and enlarges the `LibraryBackup` held between preview and restore.

---

#### P2-20 — The imported-library identity is the free-text source name, so two computers with the same name collide

*Area:* AN-08 (desktop import) · *Found by:* B · *Files:* `data/DesktopLibraryConverter.kt:19`, `:44`, `:61`, `:66`; `data/BackupMerge.kt:42-49`; `ui/DesktopImportControls.kt:19-20`
*Status:** CONFIRMED
**Description.** The desktop library identity is derived from the free-text origin the user types: `UUID.nameUUIDFromBytes(("nedotify-desktop-v1\u0000"+cleanOrigin.lowercase()).toByteArray())`. That single value namespaces the imported playlist ids, the listening-session ids and the smart-playlist ids. Two different PCs given the same name therefore produce *identical* ids — and the desktop's `tracks.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so track ids restart at 1 on every machine: the collision is **guaranteed**, not unlikely.
**Cause.** identity is derived from a human-entered label with no machine identifier, and there is no record of which PCs have already been imported.
**Trigger:** the user imports from "Домашний ПК", then imports from a second machine reusing the same label. The UI only *advises* a different name; nothing enforces or records it. **Impact:** two distinct outcomes, both bad — (a) if a session id maps to a different track id, `BackupMerge.plan` throws «Конфликт сессии прослушивания в резервной копии» and the **entire** second import fails with a message about a "backup copy"; the user cannot import from the second PC at all until they invent a new label, with no explanation. (b) If the session ids happen to line up, the second PC's playlists are merged *into* the first PC's playlists, and the user ends up with one playlist named after PC-A containing both PCs' tracks.
**Repro:** convert two different fixtures with the same `origin` but different track ids, merge the second into a library that already holds the first → `SourceFailure("Конфликт сессии прослушивания в резервной копии")`.
**Fix:** make the imported-library identity independent of the label — derive it from something machine-specific (a fingerprint of the desktop DB the user can see and confirm) or record the imported libraries and detect "same label, different library", reporting it in the notice rather than failing with a backup-format message.
**Side effects:** a machine-derived identity makes re-importing the *same* PC depend on that fingerprint staying stable (a desktop reinstall changes it) — the current label scheme is stable across reinstalls, which is why it was chosen, and the "same PC → same ids" property must be preserved because it is what makes re-import idempotent.

---

#### P2-21 — The desktop WAL sidecar is not copied, so a desktop DB that was not closed cleanly imports with silently missing recent changes

*Area:* AN-08 (desktop import) · *Found by:* B · *Files:* `data/DesktopLibraryImport.kt:16-25`; desktop `core/database.py:113`, `:1872`; `ui/DesktopImportControls.kt:21`
*Status:** CONFIRMED (the mechanism and the missing sidecar); the size of the loss window is bounded by SQLite's auto-checkpoint, so it is a recency window rather than total loss
**Description.** The desktop runs SQLite in WAL mode (`PRAGMA journal_mode=WAL`) and truncates the WAL only on a clean `close()` (`PRAGMA wal_checkpoint(TRUNCATE)`). The importer copies **only the selected stream of the main `.db` file** into the cache and opens that copy read-only; the `-wal`/`-shm` sidecars are never requested, so any transactions still living in the WAL are absent from the copy. The "close the desktop player first" control is a self-asserted switch, not something the app can verify.
**Cause.** the import treats "a `.db` file" as a complete snapshot; for a WAL-mode database it is not.
**Trigger:** the desktop was killed (task manager, crash, power loss) or simply closed without the checkpoint running, and the user copies the `.db` file. The copy then contains the state as of the last auto-checkpoint (default `wal_autocheckpoint` = 1000 pages), so the most recent tracks, favourites, playlist edits and history rows are missing. **Impact:** the import succeeds, the preview shows a plausible but smaller library, and the user believes their library moved. Nothing indicates the source was stale.
**Repro:** with the desktop's own `core/database.py`, create a DB, insert a track, kill the process without `close()` (so the WAL keeps the row), copy only `nedotify_storage.db`, and run `DesktopLibraryImport.readSnapshot(copy, "PC")` — the track is absent while the copy passes `PRAGMA quick_check`.
**Fix:** either document the requirement in the app's own copy instructions ("скопируйте .db вместе с -wal, или закройте плеер и дождитесь завершения") and accept the `-wal` file as a second document, or make the desktop produce a consistent snapshot file (`VACUUM INTO` / a backup export) — which is the same change the architecture section argues for.
**Side effects:** asking for two files doubles the picker complexity; relying on a desktop-side export makes the feature depend on a desktop release.

---

#### P2-22 — Provider JSON responses are parsed on the Android main thread in every catalogue path

*Area:* AN-10 (catalog providers) · *Found by:* B · *Files:* `data/ProviderHttp.kt:51-69`; `ui/MusicViewModel.kt:327`, `:345`, `:374`
*Status:** CONFIRMED
**Description.** `ProviderHttp.json` reads the body (the byte copy happens on the OkHttp callback thread) but then performs the JSON parse **in the caller's coroutine context**. Every catalogue entry point is launched from `viewModelScope` (`Dispatchers.Main.immediate`), and `ProviderConnections.get`/`postYandex` never switch the dispatcher for the request/parse path — the `withContext(Dispatchers.IO)` blocks there wrap only the *token read*, and `withContext` returns to the outer context afterwards. The continuation of `suspendCancellableCoroutine` is resumed from the OkHttp thread, so `Dispatchers.Main.immediate` re-dispatches it to the main looper; the `JSONTokener` parse and the whole `CatalogParsers` mapping therefore run on the main thread.
**Cause.** the parse is not moved off the caller thread. The auth path (`ProviderConnections.action`) *does* use `withContext(Dispatchers.IO)`, which is why the inconsistency was not visible from the login flow.
**Trigger:** opening a Yandex playlist or "Избранное", or any Spotify collection. The largest payloads are exactly the collection endpoints: a Yandex playlist (up to 1000 embedded track objects) and `users/{uid}/likes/tracks` (the whole liked library in one document), plus 20 sequential Spotify `me/tracks` pages. **Impact:** dropped frames / jank in the catalogue dialog while it is open; a multi-hundred-kilobyte Yandex document costs a visible main-thread stall (the body cap allows 2 MiB).
**Repro:** `viewModelScope` = `Dispatchers.Main.immediate`; `ProviderHttp.text` resumes the continuation from `onResponse` (OkHttp dispatcher thread) → the coroutine body (and thus `JSONTokener`) is dispatched to the main looper. A device profile (`gfxinfo`) while opening a large Yandex playlist would confirm the main-thread time.
**Fix:** parse on `Dispatchers.IO` inside `ProviderHttp.json` (or wrap the provider call sites in `withContext(Dispatchers.IO)`), keeping the `SourceFailure` contract intact.
**Side effects:** the parsed `JSONObject` is then handed to the caller on the main thread — the per-item mapping would still be on the main thread unless it is moved too, and moving the mapping is the larger part of the cost for 1000-item collections.

---

#### P2-23 — Provider errors are classified at the HTTP layer but the classification is discarded before it reaches the user

*Area:* AN-10 (catalog providers) · *Found by:* B · *Files:* `ui/MusicViewModel.kt:377-389`; `data/CatalogMatcher.kt:71-75`; `data/ProviderHttp.kt:38`
*Status:** CONFIRMED
**Description.** The transport layer *does* classify: `SourceFailure` carries `httpCode` and `ProviderHttp.text` maps 401/403/429 to distinct Russian messages; `ProviderConnections.get` even reacts to a 401 by clearing the token and retrying once. The catalogue path throws that classification away: (1) `importCatalog` catches every per-track exception with `catch(_:Exception) {unavailable++}`, so an expired token, a 429 rate limit, an offline transition and a genuine "no match" all become one indistinguishable counter, and the final message is "Импортировано N треков; недоступно: M"; (2) `CatalogMatcher.resolve` swallows the searcher's exception and then reports "Не найдено достаточно точное совпадение" — a provider that is rate-limiting is presented to the user as "the version was not found"; (3) `CatalogBrowserState.error` is a single `String?`, so even where the message survives the UI cannot react differently.
**Cause.** the catalogue state models errors as a single string, and the import loop treats every failure as "unavailable".
**Trigger:** any provider 401/403/429 during a catalogue browse or import; the most likely trigger is a rate limit during a 500-track import. **Impact:** the user is told "N tracks unavailable" or "no exact match found" when the real cause is a temporary rate limit or an expired login, and is not offered the right action (wait / reconnect).
**Repro:** the `httpCode` is not read anywhere in `ui/MusicViewModel.kt` (it appears only in `data/Sources.kt` and `data/ProviderHttp.kt`/`ProviderConnections.kt`). A MockWebServer returning 429 during `importCatalog` shows the "unavailable" counter with no reason.
**Fix:** keep the first classified failure (message + `httpCode`) per import and surface it alongside the counter; carry a typed error into `CatalogBrowserState` so the UI can offer "reconnect" vs. "retry later".
**Side effects:** the catalogue UI state gains a discriminated error type; the import result text becomes more complex.

---

#### P2-24 — A failed provider is invisible in "Все" search mode unless the whole result set is empty

*Area:* AN-12 (search) · *Found by:* A · *Files:* `data/SearchAggregate.kt:28-31`; `data/LibraryRepository.kt:69`
*Status:** CONFIRMED
**Description.** `aggregateSearch` converts every provider exception into `Result.failure` and only raises it to the user when **nothing at all** was found — the guard is `tracks.isEmpty() && outcomes.any {it.isFailure}`. As soon as one task produced ≥1 track, every other task's failure (HTTP 401, DNS error, timeout, provider outage) is discarded silently. The prior round's fix ("В «Все» пустая локальная библиотека скрывала сбой обоих сетевых источников как «Ничего не найдено»") is present and correct **for the empty-local case only**; the symmetric case (local contributes one hit, both remotes down) is still silent, and the one-remote-down case is silent even when the other remote returned zero hits.
**Cause.** the failure information is discarded at the point of aggregation; no per-provider outcome is carried out to the UI.
**Trigger:** (a) local-only success — correct; (b) one remote failing — the other remote's results are shown, the failure is invisible; (c) all remotes failing with a non-empty local library → the user gets a short local list and **no error**, believing the search was complete; (d) single-source mode — the failure propagates unchanged, correct. A highly likely trigger for (b)/(c): the **first** SoundCloud search after process start must scrape the client id (`soundcloud.com` plus a 2.9 MB JS bundle — `android/review/PROVIDER_PROBE.json` shows `length: 2910777`), and that whole sequence is inside the 6.5 s provider budget, so on a mobile link the SoundCloud task times out on the first search of a session and its results are dropped without a word.
**Impact:** the user searches for a song they do not own, gets a couple of unrelated local hits, and concludes "that is all there is". There is no way to tell an incomplete search from a complete one.
**Repro:** `aggregateSearch(listOf({listOf(track("local-1"))},{throw SourceFailure("blocked SC")},{throw SourceFailure("blocked YT")}))` returns `listOf(track("local-1"))` with no exception and no indication of the two failures. `SearchAggregateTest.kt:31-34` pins only the *empty-local* variant.
**Fix:** carry the per-provider outcome out of `aggregateSearch` (e.g. `AggregateResult(tracks, failedProviders)`) and surface a non-blocking notice naming the failed source.
**Side effects:** the UI must distinguish "empty result set" from "incomplete result set"; a notice on every flaky provider would train users to ignore it.

---

#### P2-25 — The local DB scan is given the 6.5 s *network-provider* budget; when it expires its results are dropped with no error

*Area:* AN-12 (search) · *Found by:* A · *Files:* `data/LibraryRepository.kt:55-67`; `data/SearchAggregate.kt:16`, `:22`
*Status:** CONFIRMED (code path); the millisecond magnitude is a hypothesis (needs a device)
**Description.** the local task is an ordinary entry in the provider list, so `withTimeout(providerTimeoutMs = 6_500)` applies to it. The local task is a **full scan** of the candidate rows done in 500-row pages, each page re-running the whole predicate and re-sorting by `addedAt` because there is no index on `addedAt`. If the scan does not finish in 6.5 s it becomes `Result.failure(TimeoutCancellationException)` and the local hits vanish from the aggregate — and because the remote tasks succeeded, `tracks` is non-empty, so P2-24's guard does not fire. The user gets remote results with no local results and no explanation.
**Cause.** a local, CPU/IO-bound full-table scan is scheduled as if it were a network provider with the same deadline, and its failure is treated as a provider failure.
**Trigger:** a large library on a slow device, or a narrow query — the loop `while(matches.size<100)` keeps paging until it finds 100 matches or reaches the end of the table, so a *narrow* query forces a complete scan. **Impact:** "Все" search silently loses the local hits — the ones the user already owns, which are the most relevant.
**Evidence.** `LibraryRepository.kt:58-64` the paging loop; `Models.kt:104` the query (no `addedAt` index). Measured on desktop SQLite with the same SQL: 2 000 rows → 0.007 s; 10 000 → 0.132 s; 20 000 → **0.537 s**; a phone is several times slower and must also run the Kotlin `contains` filter over every row.
**Repro:** the scratch script reproduces the timing; on-device confirmation needs a ~20 k library plus a query matching almost nothing.
**Fix:** give the local task its own (larger or unbounded) budget distinct from the network budget, and treat a local-task timeout as a distinct, reportable condition.
**Side effects:** an unbounded local task would let a pathological query block the "Все" search indefinitely; a separate budget plus a reported "local search did not finish" state keeps the user informed.

---

#### P2-26 — The whole search pipeline body runs on the main thread, including a 126 KB JSON parse and a 50 000-node DOM walk

*Area:* AN-12 (search) · *Found by:* A · *Files:* `data/Sources.kt:47-49`, `:96`, `:143`, `:146-168`; `ui/MusicViewModel.kt:146-149`; `data/SourceJson.kt:8-27`
*Status:** CONFIRMED (the threading is provable from the code; the millisecond cost needs a device)
**Description.** `MusicViewModel.search` runs in `viewModelScope` (`Dispatchers.Main.immediate`) and calls `repository.search` **without** changing dispatcher. `aggregateSearch` uses `supervisorScope { tasks.map { async { … } } }`, and `async` inherits the caller's dispatcher, so each provider task body continues on the main thread after its network suspension point: **SoundCloud** — `MusicNetwork.get` returns a `String` and does *not* switch dispatcher, so the caller parses it: `sourceObject(network.get(...))` → `sourceJson` runs a full depth pre-scan **and** a `JSONTokener` DOM parse on the UI thread; **YouTube** — `network.post` does parse on IO, but the result is then walked as a DOM **on the UI thread**: `visit(data)` traverses the whole parsed tree with a budget of `depth>40 || visited++>50_000`.
**Cause.** the provider clients return a parsed/raw payload and let the caller's dispatcher do the parsing/traversal, and the caller never moves the work off `Dispatchers.Main`.
**Trigger:** every search. The cost scales with the provider response size — 126 KB for SoundCloud and 572 KB / up to 50 000 visited nodes for YouTube (`android/review/PROVIDER_PROBE.json:22-27,78-83`). Every other network path in this codebase is explicit about the dispatcher (`Sources.kt:50`, `ProviderConnections.kt:62`, `LibraryRepository.kt:85,95,116`, `LibraryBackupStorage.kt:13,27,44`) — **the search path is the outlier.**
**Impact:** a visible freeze of the search screen (the spinner stops animating) at the moment results arrive; on a low-end device this can approach the ANR threshold.
**Repro:** enable StrictMode or attach a systrace during a search and look for the main thread inside `org.json.JSONTokener.nextValue` / `JSONObject.keys`.
**Fix:** run the provider bodies on `Dispatchers.IO` (e.g. `withContext(Dispatchers.IO)` inside `aggregateSearch`'s `async`, or inside `MusicNetwork.get` / `SoundCloudClient.api` / `InnerTubeClient.search`).
**Side effects:** none functionally — the results are plain data classes and `withContext` keeps the caller's job as the parent, preserving cancellation.

---

#### P2-27 — The lyrics identity gate has no "base recording" fallback, so slowed / remix / sped tracks can never show lyrics

*Area:* AN-13 (lyrics) · *Found by:* B · *Files:* `data/LyricsCascade.kt:76-78`; desktop `services/music_matching.py:17`, `services/lyrics_lookup.py:50-53`
*Status:** CONFIRMED (verified by an executed mirror of the Kotlin)
**Description.** the desktop explicitly allows a *variant* track (sped/slowed/remix) to match the **plain** lyrics of the base recording, while never letting a base recording supply karaoke timing (`match_type='base'` ⇒ `syncedLyrics=None`). The Android instead requires `wanted.version == offered.version` exactly, so a "Song (Slowed)" track only matches a release that is itself tagged "Slowed" — which almost never exists in a lyrics index. The Android *detects* the variant (its `versionWord` list contains `slowed`, `sped`, `remix`) and then refuses every candidate.
**Cause.** the base-fallback rule of the desktop oracle was not ported; the version gate is implemented as equality instead of a set relation.
**Trigger:** `track.title` contains a version qualifier in the Android's list — `(Slowed)`, `(Sped Up)`, `(Remix)`, `(Nightcore)` — and the index holds only the base recording. **Impact:** "Текст не найден" for a whole class of very common tracks, where the desktop shows the base lyrics.
**Evidence.** `LyricsCascade.kt:77-78` `wanted.version != offered.version || !similar(...)` → `return null`; desktop `music_matching.py:17` `BASE_FALLBACK_VERSIONS = {'sped', 'slowed', 'remix'}` and `lyrics_lookup.py:50-53` `base = bool(version and not offered_version and version in BASE_FALLBACK_VERSIONS)`.
**Repro:** `LyricsIdentity.accept(Track("x","Song (Slowed)","Artist",durationMs=180_000), "Song", "Artist", 180_000, "", "Текст")` currently returns `null`; the desktop returns `{'status':'found','plainLyrics':'Текст','syncedLyrics':None,'match_type':'base'}`.
**Fix:** model the version relation as a set relation (equal / base-fallback) instead of string equality, and make the base-fallback path yield plain text only.
**Side effects:** a base-fallback match is, by definition, a *different* recording's words; the desktop mitigates this by refusing synced timing for base matches, and the Android must do the same, otherwise a "Slowed" track would be given the base recording's timestamps and the karaoke cursor would drift.

---

#### P2-28 — An oversized primary LRCLIB response aborts the whole lookup; the four-provider cascade is never consulted

*Area:* AN-13 (lyrics) · *Found by:* B · *Files:* `data/Sources.kt:224-230`; `data/LyricsData.kt:10`, `:21`, `:31`
*Status:** CONFIRMED
**Description.** the primary `/api/get` response is parsed by `lyricsResult()` **outside** the try/catch that converts provider failures into an empty result. `lyricsResult()` uses `require(...)`, which throws `IllegalArgumentException` when the payload exceeds 256 000 characters or 20 000 LRC lines. The transport permits up to 2 MB, so a 2 MB response with a 1 MB `plainLyrics` aborts `lyrics()` with an uncaught exception. The cascade is skipped entirely, and the ViewModel shows the generic "Не удалось получить текст. Повторите попытку". The cascade path itself is safe — `LyricsIdentity.accept` bounds the lengths and returns `null` instead of throwing.
**Cause.** `require` (an assertion-style precondition) is used to validate untrusted third-party data, and the validation sits outside the provider-failure boundary of the caller.
**Trigger:** LRCLIB (or a MitM/compromised host) returns a `/api/get` body whose `plainLyrics`/`syncedLyrics` exceeds 256 000 characters, or whose `syncedLyrics` contains more than 20 000 timestamped lines. **Impact:** the whole lyrics feature fails for that track with an opaque message, and the NetEase/QQ/Genius fallback — which would have produced a hit — is never tried.
**Repro:** a MockWebServer case for `LyricsClient` that enqueues `{"plainLyrics":"<300 000 chars>"}` and asserts the client still returns the cascade's result (or a well-typed error) instead of throwing `IllegalArgumentException`. No such test exists today.
**Fix:** make the size/line limits a *typed* provider failure (or a truncated result) rather than a thrown `IllegalArgumentException`, and move the `lyricsResult()` call inside the existing failure boundary so an oversized primary degrades to "primary failed, run the cascade".
**Side effects:** silently truncating lyrics would hide a provider's misbehaviour; the failure should stay visible in the taxonomy (P2-30) rather than become a silent "text not found".

---

#### P2-29 — The lyrics cascade is strictly serial and its intrinsic worst case (12.3 s) exceeds the 12 s UI deadline

*Area:* AN-13 (lyrics) · *Found by:* B · *Files:* `data/LyricsCascade.kt:95`, `:103-109`; `data/Sources.kt:225`; `ui/MusicViewModel.kt:442`; desktop `services/lyrics_lookup.py:25`, `:284`, `:346-357`
*Status:** CONFIRMED (the arithmetic follows directly from the source constants)
**Description.** the cascade runs its four providers **one after another**, each under its own `withTimeoutOrNull(2_200)`. The primary LRCLIB `/api/get` has its own 3 500 ms budget. Worst case = 3 500 + 4 × 2 200 = **12 300 ms**, while the ViewModel wraps the whole call in `withTimeout(12_000)`. The sum of the inner budgets is 300 ms larger than the outer one, so in the worst case the fourth provider (Genius) is always cancelled before it can answer, and the user sees "Источник текста не ответил. Повторите попытку" instead of the Genius hit. The cascade has **no overall deadline of its own** — it is bounded only by its caller, and the desktop's equivalent has an intrinsic one (`BUDGET = 8.0`).
**Cause.** the per-provider timeout was made the only budget; the desktop instead ran every provider concurrently under one shared deadline, so its wall-clock was `max(provider)` ≈ 1–2 s rather than the sum.
**Trigger:** every provider is slow. **Impact:** the lyrics tab spins for up to 12 s on a slow network, and the last provider's work is thrown away; on a good connection a track whose lyrics are only on QQ Music or Genius waits for LRCLIB *and* NetEase to fail first.
**Repro:** instrument `LyricsCascade` with a MockWebServer that delays every response by 2 100 ms; the lookup then takes ≈ 12.3 s and the ViewModel's 12 000 ms wrapper aborts it. A deterministic variant: assert `providerTimeoutMs * providers.size + 3_500 <= 12_000`.
**Fix:** give the cascade its own total deadline (the desktop's 8 s shape) strictly smaller than the caller's, and run the providers concurrently so the wall-clock is the maximum, not the sum, of the provider latencies.
**Side effects:** concurrent providers multiply the number of simultaneous third-party requests per track (the desktop caps this with a 6-thread pool); an Android version must keep the total request count bounded and must not open four sockets per track on a metered connection.

---

#### P2-30 — The lyrics failure taxonomy is collapsed: "provider unreachable" is reported to the user as "no lyrics exist"

*Area:* AN-13 (lyrics) · *Found by:* B · *Files:* `data/LyricsCascade.kt:104-109`; `data/Sources.kt:236`; `ui/PlayerScreen.kt:166-169`
*Status:** CONFIRMED
**Description.** every provider exception is swallowed (`catch (_: Exception)`) and the cascade returns a `LyricsResult` with an empty `plain`/`lines`. `LyricsClient.lyrics` then returns that empty result as a normal answer, and the UI renders "Текст не найден / Для этого трека пока нет текста" — **identical** to the message shown when the index genuinely has no entry. The desktop keeps the two apart (`status='unavailable'` vs `status='not_found'`) and the desktop UI prints two different sentences.
**Cause.** the cascade's result type (`LyricsResult`) has no failure channel, so a transport/schema failure is indistinguishable from an empty index.
**Trigger:** any provider being unreachable, blocked, returning a changed schema, or a 5xx — i.e. every network or provider-side failure, not only "no lyrics". **Impact:** the user is told the song has no lyrics when the real cause is a network problem, and is invited to press "Повторить поиск" — which cannot help.
**Evidence.** `LyricsCascade.kt:104-109` the swallowing catch; `PlayerScreen.kt:166-169` the empty state; desktop `lyrics_lookup.py:374` `result = flight['best'] or {'status': 'unavailable' if failed else 'not_found', …}` and `ui/web_new_v2/js/lyrics.js:931` two different messages.
**Repro:** point `LyricsEndpoints` at a MockWebServer answering every path with HTTP 503; the cascade returns an empty `LyricsResult` and the UI cannot distinguish it from a legitimate miss.
**Fix:** give the cascade result a failure channel (e.g. a `LyricsResult.status` or a separate outcome type carrying `not_found` vs `unavailable`) and let the ViewModel map it to two messages, mirroring the desktop.
**Side effects:** `LyricsResult` is stored in the disk cache and in the memory cache, so adding a field changes the cache record format and the `read` validation; the negative-cache TTL logic must keep the two apart so a transient outage is not cached for 10 minutes as "not found".

---

*(pending)*

---

#### P2-31 - The report's "change vs previous period" compares a partial current window against a full previous window, biasing the headline percentage by up to -14 %

*Area:* AN-14 (A) · *Files:* `data/ListeningReports.kt:86-113` (window), `:115-117` (percentage) · *Status:* CONFIRMED (verified numerically)
The current period is `[local midnight of today-(N-1) days, now]` - an **incomplete** calendar period. The comparison period is `[midnight of today-2N days, current start - 1 ms]` - a **complete** N-day period. `changePercent` divides one by the other, so the shorter the current day, the more negative the reported change. **Cause:** the window builder derives the previous period as whole calendar days but the current as "calendar days so far today". **Trigger:** any user reading the "X % к прошлему периоду" line. **Impact:** with an unchanged habit the app reports a fall of ~14 % (week) / ~3 % (month) at the start of the day, drifting back to 0 % as the day progresses - the user is told their listening dropped when it did not. This is a headline statistic on the Profile screen.
**Evidence.** `ListeningReports.kt:105-112` `previousStartInclusive = midnight(firstDate.minusDays(dayCount))`, `previousEndInclusive = start - 1`, `endInclusive = now`; `:115-117` `((currentMs - previousMs) / previousMs) * 100.0`. Transliterated into a scratch JDK-21 `jshell` script: `WEEK at midnight: current=144.0 h previous=168.0 h ratio=0.857`; `WEEK at noon: 156.0 h, ratio=0.929`; `MONTH at midnight: 696.0 h vs 720.0 h, ratio=0.967`. With 60 min/day, `percentage` returns -14.3 % at 00:00. The desktop uses two **equal** rolling windows (`services/listening_comparison.py:23-24` `current_start = moment - timedelta(days=days); previous_start = current_start - timedelta(days=days)`). The project's own test pins the asymmetry but only the boundaries (`ListeningReportsTest.kt:23-32`).
**Repro.** transliterate `ReportCalendar.window` and print the two window lengths at 00:00 and 12:00.
**Fix.** make the two windows the same length - either compare against the previous period truncated to the same elapsed offset, or switch both to equal rolling windows as the desktop does.
**Side effects.** the "было N" text (`ui/ProfileComponents.kt:68`) also becomes partial; the daily chart is unaffected; `ListeningReportsTest` must be updated.

---

#### P2-32 - "Топ исполнителей" groups artists case-sensitively, so one artist is split across several rows and the unknown-artist bucket is admitted

*Area:* AN-14 (A) · *Files:* `data/Models.kt:160-165` · *Status:* CONFIRMED
`GROUP BY name` uses SQLite's default BINARY collation; `COLLATE NOCASE` is applied only in the `ORDER BY`, which affects tie-breaking, not grouping. "The Weeknd", "the weeknd" and "THE WEEBND" become three groups with three separate totals. The desktop groups case-insensitively in **both** report implementations (`core/database.py:1201` `GROUP BY LOWER(t.artist)`; `services/listening_comparison.py:38-39` `GROUP BY LOWER(TRIM(t.artist))`) and excludes the unknown-artist bucket. The app is also internally inconsistent: the discovery ranking merges case variants (`data/DiscoveryEngine.kt:28`), so one artist is one entity in the Flow but several in the report. **Trigger:** a library whose artist strings differ in case - very common after a desktop->phone import (`DesktopLibraryConverter` copies `artist` verbatim). **Impact:** the panel shows the same artist twice with split times; a listener of one artist sees a fragmented list. **Repro:** insert history rows for `"The Weeknd"` and `"the weeknd"` - `reportTopArtists` returns two rows; the equivalent desktop query returns one. **Fix:** group by a case-folded key with a deterministically chosen display name, and decide explicitly whether the unknown-artist bucket belongs in the top list. **Side effects:** case-insensitive grouping merges artists the user may consider distinct; the display name must be chosen deterministically or the list shows an arbitrary variant.

---

#### P2-33 - Three smart rules shared with the desktop evaluate to different results on Android

*Area:* AN-14 (A) · *Files:* `data/SmartRules.kt:93-113`; bridge `data/DesktopLibraryConverter.kt:80-100` · *Status:* CONFIRMED
Field-by-field comparison against `services/smart_playlists.py:24`, `:140-155`:

| rule | desktop | Android | divergence |
|---|---|---|---|
| `not_played_days` | `t.last_played IS NULL OR t.last_played < datetime('now',-N days)`; `last_played` bumped by **every** logged play (`core/database.py:731-733`) | `row.lastPlayed == 0L \|\| row.lastPlayed <= cutoff`, where `lastPlayed = MAX(h.startedAt)` over rows with `listenedMs > 0` | a track played but with no measurable listening counts as **never played** on Android, **played** on the desktop |
| `unplayed` | `COALESCE(t.play_count,0) = 0`; `play_count` incremented for every history row | `row.playCount == 0`, counting only rows with `listenedMs > 0` | a skipped track is "already played" on the desktop, "not yet played" on Android |
| `most_played` / `least_played` | `t.play_count DESC/ASC` (a **play count**) | `row.listenedMs DESC/ASC` (a **summed listening time**) | same sort name, different order |

The `most_played` divergence is directly reachable through the import bridge: `DesktopLibraryConverter.desktopRules` maps the desktop's `"most_played"` straight onto `SmartOrder.MOST_PLAYED` (`DesktopLibraryConverter.kt:93-99`), so a playlist carried over from the PC keeps its name but changes its meaning. **Cause:** the Android port re-derives "played" from *measured listening time* (a deliberate, contract-compliant improvement) but never reconciled it with the desktop rule names, and the import bridge maps the names without translation. **Trigger:** importing a desktop library with smart playlists; any library with skipped tracks. **Impact:** a smart playlist that was correct on the PC shows a different set and a different order on the phone; "Ещё не слушал" contains tracks the user already played through on the PC. **Repro:** create a track that was started and skipped within a second (0 measured ms) - it is present in `history` with `listenedMs = 0`; the Android `unplayed=true` rule matches it, the desktop's `play_count > 0` rule does not. **Fix:** pick one definition of "played" and apply it consistently - either translate the desktop rules on import and document the difference, or reintroduce a separate play counter so `unplayed`/`not_played_days` mean "played at least once" while `listenedMs` keeps its measured meaning; the `most_played` import mapping must be renamed or re-defined. **Side effects:** the second option adds a column and a Room migration (the DB is at v3) and changes the meaning of the existing `unplayed` rule for existing users.

---

#### P2-34 - The smart-playlist view re-runs a full-library aggregation and a full in-memory sort every 5 seconds while music plays

*Area:* AN-14 (B) · *Files:* `data/DiscoveryController.kt:62-67`, `:96-98`; `data/DiscoveryEngine.kt:13-19`; `data/SmartRules.kt:93-113`; `player/PlaybackService.kt:183-186` · *Status:* CONFIRMED
`observeDiscoveryCandidates(now)` is a Room `Flow` over a query with **no LIMIT** that aggregates the whole `history` table. Room re-runs a `@Query` flow whenever any table it reads is written - and `history` is written every 5 s during playback. So while a smart playlist is open and music plays, the app re-executes the aggregation, re-materialises **every** `Track` in the library as a `DiscoveryCandidate`, and re-runs `SmartPlaylistEngine.select` (filter, then `sortedWith` over the entire list) **12 times per minute**. The 60 s `clock()` tick adds a further full re-execution even when nothing changed. **Cause:** the candidate query has no bound and no incremental cache; the pipeline couples "library changed" and "history changed" to "recompute the whole ranking over the whole library". **Trigger:** the Library screen open with the "Умные" filter, a smart playlist selected, and audio playing. **Impact:** with ~20 000 tracks and ~50 000 history rows each re-run visits ~70 000 rows, allocates ~20 000 objects (~4-5 MB) and sorts 20 000 elements, 12x/min; the device runs hot, the battery drains and the Library screen stutters. **Evidence.** `DiscoveryEngine.kt:13-19` the unbounded SQL; `Models.kt:89` uses it verbatim for the Flow while `:90` appends `LIMIT 5000` for the suspend variant, so the two paths use **different candidate universes**; `SmartRules.kt:113` `rows.sortedWith(comparator).take(filter.limit)` - the sort is over the whole list and `take` is applied after it. **Repro:** instrument the DAO flow, open a smart playlist, start playback, and count re-executions of `DISCOVERY_CANDIDATES_SQL` per minute. **Fix:** bound the candidate query (push the predicates into SQL, or aggregate per track in a materialised summary table updated on session write) and drop the redundant 60 s re-subscription. **Side effects:** pushing filters into SQL changes `SmartPlaylistEngine.select`'s signature and the JVM unit tests that build candidates by hand; a summary table adds a write on the hot session path and needs a Room migration.

---

#### P2-35 - The `history` table has no retention policy; once it passes 100 000 rows the JSON backup can no longer be exported at all

*Area:* AN-14 (B) · *Files:* `data/BackupCodec.kt:30`, `:34`, `:168-171`; `data/Models.kt:37-39`, `:78`; `data/LibraryBackupStorage.kt:13-25` · *Status:* CONFIRMED
`history` has no pruning anywhere - a repo-wide grep for `DELETE FROM history` / `prune` / `retention` over `android/app/src/main` returns nothing. One row is created per *track playback session* and then updated in place, so rows ~ the number of track transitions; even a one-second skip creates a row. Meanwhile the JSON backup has a hard session cap and a hard byte cap, and `checkCounts` rejects the export outright with `invalid("слишком много записей")`. `LibraryBackupStorage.export` calls `BackupCodec.encode` **before** opening the destination, so the failure is clean - but the user simply cannot produce a backup any more. The 16 MB cap is reached first: at ~140 bytes per session the history alone is ~14 MB at 100 000 rows. **Trigger:** ~100 tracks/day -> 36 500 sessions/year; ~300 tracks/day (a user who skips through queues) -> ~110 000 sessions/year, i.e. the export starts failing after roughly one year. **Impact:** "Резервная копия библиотеки" silently stops working for long-term users; they discover it only when they try to back up or move to a new phone, with no warning and no in-app way to trim the history. **Note:** the desktop has no backup feature and also does not prune, so this is an Android-only collision between an unbounded table and a bounded export format. **Repro:** insert 100 001 `ListeningSession` rows (the DAO accepts them; only the *backup* caps), then call `BackupCodec.encode(...)`. **Fix:** either add a retention policy (keep the newest N sessions plus per-day aggregates for older ones, mirroring what the report already computes) and surface it in the UI, or make the export tolerate a large history. **Side effects:** pruning deletes user data - the project rule is "never alter the user's library", so any policy must be explicit, opt-out-able and announced.

---

#### P2-36 - The offline network-mode flag is modelled inside the *theme* data class and read through 12 independent cold DataStore reads

*Area:* AN-16 (B) · *Files:* `data/Preferences.kt:10-11`, `:15-17`; readers at `data/LibraryRepository.kt:32,45,68,75`, `data/DiscoveryEngine.kt:58,65`, `downloads/Downloads.kt:45`, `downloads/TrackDownloadWorker.kt:38`, `ui/MusicViewModel.kt:297,441`, `player/PlaybackService.kt:238` · *Status:* CONFIRMED
`offline` is a network-mode flag stored inside `Appearance`, which is otherwise purely cosmetic. Ten call sites read it as `repository.preferences.appearance.first().offline`; each starts a **new** collection of the cold `store.data` flow, even though the ViewModel already holds a hot `StateFlow` copy of the very same value (`ui/MusicViewModel.kt:54`, `SharingStarted.Eagerly`). The complete list of `.first()` reads on a preferences flow: `preferences.appearance.first()` (10 sites), `audioSettings.settings.first()` (3 sites: `NeDotifyApp.kt:21`, `LibraryRepository.kt:46,78`), `values.first()` (the `queue()` accessor, `Preferences.kt:39`). **Cause:** the settings model has no separate "network mode" concept and the repository/download/discovery layers have no shared cached view of the flag. **Trigger:** every track resolution, search, download enqueue, lyrics load and provider catalogue action. **Impact:** the first read after a cold start is a real file read on the DataStore's IO scope, so the calling coroutine suspends on the user-action path; it does not block the main thread, but it is an unnecessary cold read per action - and the DataStore actor is also the target of the 5 s queue write (P2-01), so a read can queue behind a write. **Repro:** `grep -rn "\.first()" android/app/src/main` lists the 14 sites; instrument `Preferences.appearance` with an `onStart` counter and observe one collection per call site per action. **Fix:** promote `offline` to its own typed group and expose a single cached `StateFlow` from the repository so consumers read `.value` instead of re-collecting; inject the cached flag into the repository/download layers. **Side effects:** the repository currently has no lifecycle of its own, so it needs an owning scope for the cached `StateFlow`; moving `offline` out of `Appearance` changes the `Appearance` shape used by `ui/MusicApp.kt:58` and `ui/SettingsScreen.kt:47`.

---

#### P2-37 - Navigation is a single `String` with no back stack: Back from Settings/Profile always lands on Home

*Area:* AN-17 (B) · *Files:* `ui/MusicApp.kt:48`, `:55`, `:83-89` · *Status:* CONFIRMED
The entire navigation model is one `rememberSaveable` string. There is no `NavHost`, no `NavController`, no back stack and no sealed route type. `BackHandler` is registered only when `route != "home" && !fullPlayer`, and its action is unconditionally `route = "home"`. Because Settings and Profile are *replacements* for the current route rather than pushes, the tab the user was on is destroyed: a user in the **Library** who taps the gear icon and presses Back lands on **Home**, losing their place and scroll position. The desktop keeps the base page (`ui/web_new_v2/js/pages.js:13` `let currentBasePage = 'home'`; `:178-189` `closeSettings()` restores `currentBasePage` and re-activates the matching nav item). **Cause:** a single-slot route variable models "which screen is visible", not "a stack of screens"; there is nowhere to store the previous route, so the only possible back target is a hard-coded constant. **Trigger:** open Settings or Profile from any tab other than Home, then press Back. **Impact:** the user is silently teleported to Home. **Repro:** open Library, tap the gear, press Back -> Home, not Library. **Fix:** replace the `String` route with a `NavHost`/`NavController` graph, or at minimum a sealed `Route` type plus an explicit back stack. **Side effects:** a `NavController` changes how `fullPlayer` (a `ModalBottomSheet`, not a route) is modelled; a `rememberSaveable` back stack needs a custom `Saver` to survive process death.

---

#### P2-38 - The `nedotify://oauth/spotify` deep link cannot navigate: it performs the token exchange and leaves the user on whatever screen they were on

*Area:* AN-17 (B) · *Files:* `MainActivity.kt:29-34`, `:38`; `AndroidManifest.xml:22-27`; `ui/MusicApp.kt:48` · *Status:* CONFIRMED
The manifest declares a `VIEW`/`BROWSABLE` filter for `nedotify://oauth/spotify`. `MainActivity.readOAuth` validates scheme/host/path and calls `model.handleSpotifyRedirect(...)` - and that is all. It cannot change the route: the route lives in `MusicApp`'s composition (`ui/MusicApp.kt:48`), and the Activity has no channel to it. After a browser round trip the app shows a transient snackbar ("Spotify подключён") and the user is left on Home, with no route to **Settings -> Подключения** (where the connection state lives) and no route to the Spotify catalogue (`openCatalog("spotify")` is only reachable from the Settings screen). On a cold start the app comes up on Home and the deep link produces no visible screen change at all. **Cause:** navigation state is owned by a composable, not by a `NavController`/`ViewModel`; an Activity-level intent therefore has no way to express "navigate to X". The deep link is modelled as a *side effect on the ViewModel*, not as a *destination*. **Trigger:** completing the Spotify PKCE login, or sending the app any `nedotify://oauth/spotify` intent from outside. **Impact:** the user cannot tell that the connection succeeded (a snackbar that may be missed) and cannot reach the new connection without manually hunting for Settings. **Repro:** `adb shell am start -a android.intent.action.VIEW -d "nedotify://oauth/spotify" ru.nedotify.app` -> the app comes to the foreground on the current route; no navigation occurs. **Fix:** hoist the route into the ViewModel (or a `NavController` owned by the Activity) and let `MainActivity` post the deep link as a one-shot event the navigation layer consumes - the pattern already used for `openExternalUrl`. **Side effects:** moving the route out of the composition changes how it is saved across process death (it would need `SavedStateHandle`, which the ViewModel already has).

---

#### P2-39 - `Design.kt` is not a token layer: it defines no spacing scale, and 184 of the 193 raw `dp` literals live outside it

*Area:* AN-17 (B) · *Files:* `ui/Design.kt:38-50` (the whole theme) plus every file under `ui/` · *Status:* CONFIRMED
The design system provides exactly three things: a Material 3 `ColorScheme` (`Design.kt:41-44`), three overridden typography slots (`:46-48`) and one shape literal (`RoundedCornerShape(12.dp)` in `Cover`, `:117`). There is **no** spacing scale, no radius scale, no shape scale and no `CompositionLocal` carrying them. Counted over `ui/*.kt`: **193** raw `dp` literals (9 in `Design.kt`, **184** in the 17 screen/component files); **24** raw `Color(0x…)` literals (14 in `Design.kt`, **10** outside); 8 raw `fontSize=`. Corner radii are ad hoc: `12.dp` (`Design.kt:117`), `16.dp` (`MiniPlayer.kt:29`), `20.dp` (`BrowseComponents.kt:72`), `14.dp` (`BrowseComponents.kt:61`), `24.dp` (`BrowseComponents.kt:32`), `12.dp` (`SearchScreen.kt:57`) - six different radii for the same conceptual "card" role. The desktop oracle has an explicit token layer with a documented single-declaration rule: `ui/web_new_v2/css/tokens.css:65-82` defines `--radius-xs…--radius-full` (5) and `--space-xs…--space-2xl` (6); `:32-63` a 9-name semantic colour layer; `:98-111` the type scale; `:10-23` states the invariant explicitly: *"every name below is declared EXACTLY ONCE in the whole stylesheet set"*. **Cause:** the Compose port was written screen-by-screen with literal values; `Design.kt` was only ever used for the colour scheme, `glass()`, `Cover` and `EmptyState`. **Impact:** dark-mode and accent changes only reach the parts of the UI that read `MaterialTheme`; the decorative and hard-coded surfaces (hero scenery, avatar gradient, favourites pink, the MiniPlayer's blue gradient and border) do not follow the theme - `LibraryScreen.kt:152-154` hard-codes the favourites pink with a manual luminance check, and `MiniPlayer.kt:28-29` hard-codes a blue gradient and border on top of `glass()`, overriding `glass()`'s own themed border. **Repro:** `Select-String -Path 'ui/*.kt' -Pattern '\d+(\.\d+)?\.dp'` -> 193 hits, 9 in `Design.kt`; `-Pattern 'Color\(0x'` -> 24 hits, 10 outside. **Fix:** introduce a token layer in `Design.kt` (a `Spacing` object with a 6-step scale, a `Radii` object, an extended `Typography`) and migrate the 184 `dp` literals and the 10 stray colours to it; the three existing `CompositionalLocal`s (`LocalGlass`, `LocalPowerSave`, `LocalOffline`) establish the pattern. **Side effects:** a large mechanical diff across 17 files; migrate one screen at a time and compare against the current build. The decorative gradients in `BrowseComponents.kt` are arguably out of scope and can stay literal.

---

#### P2-40 - The root composable subscribes to the catalogue progress flow: a 500-track import produces 500 full-tree recompositions

*Area:* AN-17 (B) · *Files:* `ui/MusicApp.kt:45`, `:107`; `ui/MusicViewModel.kt:369-393`, `:395-397`; `ui/CatalogBrowser.kt:53-64` · *Status:* CONFIRMED
`MusicApp.kt:45` collects `model.catalog` at the **root** of the composition. `MusicViewModel.importCatalog` writes that flow once per imported track to render a progress counter (`:378`), and `updateCatalog` unconditionally assigns `_catalog.value` (`:396`). `state.tracks.take(500)` bounds the loop at 500. `CatalogBrowserState` holds `List<CatalogTrack>`/`List<CatalogPlaylist>`, so the type is not Compose-stable and `CatalogBrowser` is never skipped - it re-runs `state.tracks.distinctBy { it.key }` and `state.playlists.distinctBy { it.key }` (two fresh list allocations over up to 500 elements) on every one of those emissions. **Cause:** a progress counter is modelled as ordinary state on the same object that carries the catalogue contents, and the shell subscribes to the whole object. **Trigger:** importing a Spotify/Yandex playlist of N tracks (N <= 500). **Impact:** the root recomposes N times, each time re-executing the active screen's body and re-diffing the catalogue `LazyColumn`; the import visibly stutters and the screen behind the dialog re-lays-out on every tick. The cost is O(N^2) in the number of catalogue items because of the two `distinctBy` allocations per tick. **Repro:** open the Spotify catalogue, select a ~200-track playlist, tap "Импортировать список", and watch `adb shell dumpsys gfxinfo ru.nedotify.app`. **Fix:** split the catalogue state into a stable content part and a separate progress part, and hoist the progress into the dialog's own scope; alternatively throttle the progress emission (at most every 100 ms) and memoise the `distinctBy` results with `remember(state.tracks)`. **Side effects:** splitting `CatalogBrowserState` changes its shape; it is consumed by `CatalogBrowser.kt` and `MusicViewModel` only, so the blast radius is small.

---

#### P2-41 - `positionMs` is read at the top of `PlayerScreen`, so the whole player subtree is invalidated every 500 ms while a track plays **[MERGED x2]**

*Area:* AN-17 (B) + AN-18 (A, B) · *Files:* `ui/PlayerScreen.kt:33`, `:39`, `:49-93`; `ui/MiniPlayer.kt:20` · *Status:* CONFIRMED
`PlayerScreen.kt:33` reads `model.positionMs` in the screen's own restart scope, invalidating `PlayerScreen` and everything below it every 500 ms for as long as playback runs. The subtree contains the queue `LazyColumn` (up to N items), the lyrics `LazyColumn` (up to hundreds of lines) and the transport row. Only three leaves need the position: the scrub slider, the elapsed-time label and the lyrics auto-scroll. The screen body additionally re-runs `tracks.firstOrNull { it.id == now.id }` - a linear scan over the whole library - on every tick (`PlayerScreen.kt:39`), even though `ui/MusicApp.kt:37` already builds `trackIndex = tracks.associateBy { it.id }` and uses it for the identical lookup in the mini player. **Cause:** a high-frequency value is read at the top of a large composable instead of at the leaves that consume it. **Trigger:** any playback with the full-player sheet open; the mini player's own `positionMs` collection keeps the 2 Hz poll running even when the sheet is closed. **Impact:** every 500 ms the queue list and the lyrics list are recomposed and re-laid-out while the user is trying to scroll them - the classic "lyrics/queue list fights the user's scroll" symptom. With a 3 000-track library the scan adds ~6 000 `String.equals` per second on the main thread, purely to find one already-known track. **Evidence.** `PlayerScreen.kt:33` `val position by model.positionMs.collectAsStateWithLifecycle()`; `:39` `val current=tracks.firstOrNull {it.id==now.id}`; `ui/MusicApp.kt:37` the map that already exists one level up. The prior round fixed the *identical* `firstOrNull` in the mini player (`ui/MusicApp.kt:71-72` uses `trackIndex`) and left the `PlayerScreen` copy in place. **Repro:** put a 3 000-track library in place, open the full player, and record a main-thread trace - `firstOrNull` over `List<Track>` appears once per 500 ms. **Fix:** remove the read from `PlayerScreen` and re-read `positionMs` inside a small wrapper composable for the slider/elapsed label and inside the lyrics list, so the invalidation is confined to those leaves; hoist the same `remember(tracks){tracks.associateBy{it.id}}` map so the current track is a map lookup. **Side effects:** the slider and the elapsed label must stay in sync - a shared leaf composable that reads `positionMs` once and passes it down keeps them consistent.

---

#### P2-42 - A second PKCE start silently invalidates the pending login, and the already-open browser session then fails with a security error

*Area:* AN-22 (A) · *Files:* `ui/ConnectionsControls.kt:28`, `:34`; `data/ProviderConnections.kt:84-92`; `data/AuthPkce.kt:87`; `ui/MusicViewModel.kt:298` · *Status:* CONFIRMED (the double-tap *timing* amplifier is a hypothesis)
The single Spotify login button stays **enabled** whenever `status.spotifyConfigured && !status.busy`; the presence of a pending login only changes its *label* to «Начать заново» - it does not disable it, and pressing it calls the same `onBeginSpotify`. `ProviderConnections.beginSpotifyLogin()` unconditionally builds a **new** `PendingSpotify` and overwrites the stored `spotify_pending` (new `state` + new `code_verifier`). The browser tab opened by the first press still carries the **old** `state`, so completing the authorisation there is rejected with «Проверка безопасности входа не пройдена. Начните вход заново» - the user did everything correctly and the login still fails, with no hint that a second tab is the cause. **Cause:** the UI's only guard against a second PKCE start is `status.busy`, a *network/action* flag set inside `action{}` - i.e. only after two suspensions - so nothing keys the button off `status.spotifyPending`. **Trigger:** (a) deterministic - press «Войти», then «Начать заново» while the first tab is open, then authorise in the old tab; (b) amplifier - two taps inside the window before `status.busy=true`, which contains a DataStore file read plus an IO dispatch. **Impact:** the Spotify connection appears broken to a user who followed the flow exactly; recovery costs another browser authorisation. **Repro:** configure a Client ID, press «Войти», press «Начать заново», then authorise in the **first** tab -> the snackbar shows «Проверка безопасности входа не пройдена» and the panel still reads «Spotify · ожидает входа». **Fix:** disable the login button while `status.spotifyPending` is true, or require an explicit confirmation before starting a second PKCE flow, and make the start single-flight (return the existing authorize URL instead of regenerating `state`/`verifier`). **Side effects:** disabling the button removes the only way to recover from a lost browser tab, so a cancel affordance is needed in the same change; a single-flight start requires the data layer to expose the pending authorize URL.

---

#### P2-43 - Local library search never matches the album column, unlike the desktop oracle and unlike the app's own smart-playlist search **[MERGED x2]**

*Area:* AN-06 (A) + AN-12 (A) · *Files:* `data/LibraryRepository.kt:61`; `data/Models.kt:104` · *Status:* CONFIRMED
The "local" search path matches only `title` and `artist`, and the `SearchTrack` projection does not even fetch `album`, so the album can never match. The desktop matches `title OR artist OR album` (`core/database.py:810-820`), and this app's **own** smart-playlist engine matches all three (`data/SmartRules.kt:98`). **Cause:** the projection was reduced to `id,title,artist` for performance (a deliberate prior change) and the album dimension was dropped with it. **Trigger:** any local search whose text appears only in the album field ("Greatest Hits", "Live at Wembley", "Deluxe Edition"). **Impact:** a track the user demonstrably owns is reported as absent; the user may re-import the file, creating the duplicate rows of the next finding. **Repro:** put a track with `album="Live at Wembley"` in the library and search "Wembley" -> 0 results on Android, 1 row on the desktop. **Fix:** extend the projection and the filter to include `album` (e.g. `SearchTrack(id,title,artist,album)` and `it.album.contains(query,true)`), keeping the projection narrow. **Side effects:** slightly larger rows/pages; the paging scan already reads the full local set, so the cost is one extra TEXT column.

---

#### P2-44 - `searchPage(limit, offset)` has no total order, so the paged local scan can duplicate and skip tracks

*Area:* AN-06 (A) · *Files:* `data/Models.kt:104-105`; `data/LibraryRepository.kt:57-66`; `data/Models.kt:20` · *Status:* CONFIRMED for the non-total order; the duplicate/skip outcome is a hypothesis (needs a device)
`ORDER BY addedAt DESC` orders by a column that is not unique, while `LIMIT/OFFSET` paging requires a total order. `addedAt` is *routinely* tied: `Track.addedAt` defaults to `System.currentTimeMillis()` and `scanLocal()` constructs up to 250 tracks in one tight loop, so a whole MediaStore batch normally shares one millisecond. The paged consumer also never de-duplicates the ids it accumulates. **Cause:** the paging key was chosen as a timestamp without a unique tiebreaker, and the page consumer treats the page sequence as a stable ordering. **Trigger:** any write to `tracks` between two page queries of the same search (favouriting, `remember()` from playback, a `refresh()` from a re-scan, a catalogue import). **Impact:** a track can be returned on two pages or fall between the page boundary; because `matches` is not de-duplicated, `matches.take(100)` can also yield fewer than 100 distinct results even when more exist. **Repro:** seed >1 000 local tracks with an identical `addedAt` (exactly what `scanLocal()` produces), then run a local search while a concurrent `dao.remember()` touches `tracks` between the page queries; compare the concatenated pages against `SELECT id FROM tracks … ORDER BY addedAt DESC, id`. **Fix:** add the primary key as the tiebreaker (`ORDER BY addedAt DESC, id`) and de-duplicate `matches` (a `LinkedHashSet`) before `take(100)`. **Side effects:** none functionally; the extra `id` column is already in the primary-key index. **Note:** four other DAO queries have the same non-tiebroken ordering (`Models.kt:59`, `:106`, `:177`, `:179`), while their siblings in the same file *do* carry tiebreakers (`:76`, `:77`, `:78`, `DiscoveryEngine.kt:19`) - which makes the four exceptions look like oversights.

---

#### P2-45 - An unhandled failure in the listening-history write can kill the process

*Area:* AN-06 (A) · *Files:* `player/PlaybackService.kt:38`; `NeDotifyApp.kt:17`; DAO contract `data/Models.kt:138-145` · *Status:* CONFIRMED for the code path; the trigger (an SQLite-level failure - disk full, I/O error) is a hypothesis
The history writer is the only Room write in the app that is not wrapped in an error handler. `putSession` is a suspend DAO function that may throw (`SourceFailure` for a malformed record, or any Room/SQLite exception). It is launched on `app.ioScope`, a plain `SupervisorJob()+Dispatchers.IO` scope with **no** `CoroutineExceptionHandler`. An exception escaping a `launch` on such a scope is delivered to the thread's default uncaught-exception handler, which on Android terminates the process. **Cause:** the caller neither catches nor supplies a handler; the DAO contract permits throwing. **Trigger:** a transient or fatal storage error while the history checkpoint fires (the service checkpoints every ~5 s while playing, and on every track transition). **Impact:** playback stops and the app dies instead of degrading - the user's queue, position and the session are lost. **Evidence.** `PlaybackService.kt:38` `app.ioScope.launch {repository.dao.putSession(record)}`; `NeDotifyApp.kt:17` `CoroutineScope(SupervisorJob()+Dispatchers.IO)`; `Models.kt:138-145` the throwing DAO. Contrast `ui/MusicViewModel.kt:450-453`, where every other DAO write is guarded. **Repro:** fill the device volume so SQLite writes fail, then play a track; the history checkpoint throws and the process dies. **Fix:** catch and log inside the history publisher, or give `ioScope` a `CoroutineExceptionHandler` that logs instead of crashing. **Side effects:** a silently dropped history row on a storage error - the next checkpoint re-sends the same session id with a larger `listenedMs`, and `advanceSession` is monotonic, so no time is lost as long as the process survives. **Ownership:** the defect is in how the *caller* uses the DAO, so the player area owns the fix; the DAO-side contract is not itself wrong.

---

### 5.2 P3 — LOW (condensed register)

Every P3 row below was raised independently by at least one reviewer and
verified against the source. They are grouped by theme; the full evidence for
each lives in the corresponding subagent report and, for the rows marked
**[MERGED]**, in more than one.

**A. State that is lost, never written, or written in the wrong place**

| ID | Area | Title | Impact | Fix |
|---|---|---|---|---|
| P3-01 | AN-01 A | Persistable URI grants are never released; the grant set grows monotonically for the life of the install | At the platform cap `takePersistableUriPermission` throws and the user can no longer import or re-link any file — with no in-app recovery, and clearing app data would destroy the library. | Keep a registry of granted URIs (Room `Track.localUri` + the avatar) and release superseded ones before taking a new one. Sx: releasing a grant whose URI is still referenced silently breaks playback. |
| P3-02 | AN-01 A | `READ_MEDIA_AUDIO` is requested with no rationale, and after a permanent denial there is no route to Settings | After two denials the button silently does nothing and the message does not point at the app-settings page (unlike the notification path, which does). | Show a rationale first and offer a "open app settings" action on permanent denial, driven by the app's own "already asked" flag. |
| P3-03 | AN-02 B | The one-shot UI message channel is a `StateFlow`, so a repeated identical message is conflated away and never shown | The second of two identical failures produces no emission, so the `LaunchedEffect(message)` key never changes and the user sees the error only once. | Model the message as an event (a `Channel`/`SharedFlow`, or a state carrying a monotonic token). |
| P3-04 | AN-02 B | Raw OkHttp exception text (possibly a provider URL and the user's query) is surfaced verbatim in the search error UI | An English internal hostname appears in a Russian UI. | Wrap raw `IOException`s into a curated `SourceFailure` in `MusicNetwork.request` and sanitise at the ViewModel boundary. |
| P3-05 | AN-03 B | `explicitQueueBoundary` is set on every session-driven queue set but cleared only inside `onMediaItemTransition` | A stale flag forces `forceNewSession = true` for a transition that should keep the session, amplifying P2-10. | Clear the flag when the set operation completes, not only on a transition. |
| P3-06 | AN-03 B | The session-activity and download-notification `PendingIntent`s are the same object (request code 0, identical intent) | Harmless today, but `FLAG_UPDATE_CURRENT` means they share one extras bundle. | Give each a distinct request code or a distinguishing intent action. |
| P3-07 | AN-03 B | Three always-on timers keep ~6 120 main-thread wake-ups per hour alive for the whole life of the service | 720/h (5 s checkpoint) + 1 800/h (2 s autoplay) + 3 600/h (1 s deck tick). The process can never go fully idle. | Gate each loop on the state it actually needs and/or drive it from player events. |
| P3-08 | AN-03 B | Every completed-download change re-materialises and deep-diffs the whole queue on the main thread | A burst of main-thread work proportional to the queue size each time a download completes — audible as a stutter while music plays. | Compare the *offline asset identity* (trackId + generation + uri) instead of the whole `MediaItem`. |
| P3-09 | AN-04 A | A boundary handover cuts the equal-power fade with an abrupt gain step on both decks | A click at the track boundary whenever the real stream is shorter than the reported duration. | Carry the curve values across the slot flip and ramp the outgoing deck down over a short tail. |
| P3-10 | AN-04 A | `configure()` fires the user-interaction side effects on every audio-settings change while the queue is ended | Changing any audio setting can cancel an in-flight queue selection — the same destructive side effect as a transient focus loss (P2-13). | Make the autoplay-off re-assertion a local state operation that does not invoke the user-interaction callback. |
| P3-11 | AN-05 A | `selectQueue` falls back to the *first* available track, not "the next" one, when the selected track and everything after it are gone | The user asked for track N and hears track 0. Three of the four sub-claims of the contract hold exactly. | Keep the last retained item before the requested index, or amend the contract to state the wrap-to-first fallback — and add a test either way. |
| P3-12 | AN-05 A/B | `ListeningClock` has no per-tick upper bound, so a starved heartbeat inflates the measured listening time | The desktop caps a tick at 15 s explicitly; the Android has no cap, so a main-thread stall is booked as listening time. | Cap the per-tick delta as the oracle does. Sx: a genuinely long session with a starved heartbeat loses the excess — the same trade-off the desktop accepts. |
| P3-13 | AN-06 A | Four DAO list queries order by a non-unique column with no tiebreaker | Equally-keyed rows may reshuffle between emissions; their siblings in the same file *do* carry tiebreakers, which makes the four exceptions look like oversights. | Append the primary key to the four `ORDER BY` clauses. |
| P3-14 | AN-06 A | The same audio file imported through two different paths (MediaStore scan vs. SAF import) produces two library rows | The song appears twice, with independent favourite flags, download state and history rows, so listening time is split across duplicates. | Key SAF imports by the underlying MediaStore id where one exists, or add an explicit duplicate check. |
| P3-15 | AN-08 B | Column names taken from the untrusted desktop file are interpolated into SQL unquoted | Bounded — the statement runs against the untrusted copy, opened read-only, and `rawQuery` compiles only the first statement. The realistic outcome is a malformed statement reported as "Не удалось прочитать БД…", sending the user to the wrong remedy. | Quote the identifiers, or restrict the selection to the known allow-list (which also fixes P2-18). |
| P3-16 | AN-08 B | The desktop import writes its rows one at a time, with no batching | Restoring a library near the documented caps issues on the order of 420 000 individual SQLite statements inside one transaction, with only an indeterminate spinner and no cancel. | Chunk the statements inside the transaction, stream the read side, and expose a percentage. |
| P3-17 | AN-09 A | A wrong pasted Yandex token is reported as an expired session, not as an invalid token | The user is told "Срок входа истёк" for a value they just typed, blaming the service for the user's input. | Validate the hand-entered token in the caller with messages that name the input. |
| P3-18 | AN-09 A | A Keystore key that `cipher.init` refuses makes credential storage permanently unusable | The read path recovers; the write path calls `key(true)` **outside** the try block, so a broken key entry is never replaced and every future save fails. **HYPOTHESIS** (no device). | Guard the key lookup; on a key failure delete the alias and regenerate (the ciphertext is unreadable anyway). |
| P3-19 | AN-09 B | No certificate pinning for the three origins that carry provider bearer tokens | Bounded: the origins are hard-coded, redirects are not followed, the Spotify client is a public PKCE client with no secret, so a leaked access token grants only the three read scopes that were requested. | If pinning is wanted, pin the intermediate anchors for the three provider hosts only, with a backup pin and an expiry — and record the decision either way, since it is currently implicit. |
| P3-20 | AN-10 B | The Spotify import stores the *playback candidate's* metadata, not the catalogue metadata | The library shows the raw provider title and the uploader's name as the artist, with an empty album — while the carefully parsed catalogue metadata is used only to *find* the candidate and then discarded. | Merge the catalogue metadata into the resolved track while keeping the candidate's source/sourceId for playback. |
| P3-21 | AN-10 B | `ProviderHttp.json` has no `maxBytes` seam, so the 2 MiB cap applies to the endpoints that grow with the account size | A Yandex account with a very large liked list fails wholesale instead of being paged. | Expose `maxBytes` on `ProviderHttp.json` and raise the budget for the two collection endpoints. |
| P3-22 | AN-11 B | An expired signed URL (HTTP 401/403) is reported as a generic playback failure, although the download path already distinguishes it | The user is told "выберите другой источник" for a transient, self-healing condition. | Add the status branch the download worker already has. |
| P3-23 | AN-11 B | A DRM/protected SoundCloud track is reported as "SoundCloud изменил формат записи", and there is no negative cache | The message is false (the format did not change; the track is DRM-protected) and every play attempt re-runs the full resolution. The desktop distinguishes the verdict and memoises it for an hour. | Distinguish the verdict and add a short-TTL negative tier. Sx: memoise only the provider-confirmed dead-track verdict. |
| P3-24 | AN-11 B | The resolved media URL is checked for `https` only; no host allow-list, no redirect-destination check | A hostile or compromised provider response can point the app at an internal/loopback address. Bounded by `usesCleartextTraffic="false"` and by the absence of any credential on the media request. | One shared media-URL policy (https + per-source host allow-list), re-applied to every redirect hop. Sx: a strict allow-list breaks when a provider rotates its CDN. |
| P3-25 | AN-12 A | The local search ignores the `album` column | **[MERGED]** — same root cause as P2-43, reported there. | — |
| P3-26 | AN-12 A | `search(query, source)` is not validated against an allow-list and the query length is not bounded at the data layer | Every source value other than "all"/"local"/"youtube" falls through to SoundCloud, so a typo silently searches the wrong provider. Not reachable from the current UI, but the contract depends on the UI. | `require(source in setOf(...))` plus `query.trim().take(200)` at the repository entry. |
| P3-27 | AN-12 A | The catalogue matcher validates identity but never playability | YouTube keeps every `musicResponsiveListItemRenderer` it finds, including videos whose player answer is not `OK`; the matcher commits to the first candidate and never retries the other provider, so the user gets a raw player error instead of "Аудио для этой записи не найдено". | Pre-flight the selected candidate's playability, or fall back to the other provider on a resolution failure. |
| P3-28 | AN-12 A | The result caps truncate silently; there is no "show more" affordance | The UI prints the *returned* count, so a truncated search looks complete. (The desktop caps at 50 too, so this is parity.) | Report the true number of matches and offer "показать ещё". |
| P3-29 | AN-13 B | Fallback hits lose their provider attribution | Only the primary LRCLIB path sets a source, so the "Текст: <source>" header appears for LRCLIB hits and disappears for every other provider. | Let the provider supply its own label and keep it in the cached record. |
| P3-30 | AN-13 B | The Genius host allow-list is bypassable by an HTTP redirect | `safeGeniusPage` validates the *initial* URL, but the fetch goes through `MusicNetwork`, whose client keeps OkHttp's default `followRedirects=true`. | Disable redirects for the lyrics transport, or re-validate the final response URL. |
| P3-31 | AN-13 B | Orphaned `.tmp` files in the lyrics cache directory are never reclaimed | A process kill between the temp write and the rename leaves an orphan of up to 1.2 MB that the eviction sweep never deletes — unbounded growth outside the documented 100-entry bound. | Include the temp pattern in the sweep, or use a single temp name per directory. |
| P3-32 | AN-14 B | Artist identity is not normalised, so "Ёлка"/"Елка" split one artist in two | The taste map is keyed by the raw lowercase name, so the minutes of both spellings are not summed and the diversity penalty is keyed by the same string — the same artist can be picked two or three times in one mix. | One `artistKey()` helper mirroring the desktop's `name_key`. Sx: the display name must be chosen deterministically. |
| P3-33 | AN-14 B | A smart playlist can be saved with no conditions at all, and the count is uncapped on creation | An all-neutral rule set matches the whole library and degenerates into "the 100 newest tracks", while the row is labelled "Обновляется по правилам". The desktop refuses to create it. | Require at least one condition; apply the same 100-playlist cap to `createSmart`. Sx: existing all-default playlists would start showing a "damaged rules" error. |
| P3-34 | AN-16 B | The queue snapshot is returned as raw JSON and its format version is written but never checked | The key is named `queue_v1` while the payload says `"version":2`; the version marker lives in the wrong place and is never validated, so a format change silently degrades restores instead of failing loudly. | Model the snapshot as a typed record with its own codec, and validate the version on read. |
| P3-35 | AN-16 A/B | The profile avatar can never be cleared, and a dead `content://` grant fails silently | The store supports an empty URI, but the only caller can pass a non-empty one, so the "remove" branch is unreachable; and the `AsyncImage` has no error state, so a revoked grant is indistinguishable from "no photo". | Add a remove action and an error painter. |
| P3-36 | AN-16 B | `Preferences` has no injection seam, so the whole 12-key settings model is untested | `AudioSettingsStore` deliberately exposes an `internal constructor(DataStore)` and is tested; `Preferences` hard-wires `context.settings`, so the read mapping, the default fallbacks, the enum validation, the search-history round trip and the "libraryId is created once" guarantee are all unverified. | Give it the same `internal constructor(DataStore)` seam and cover the mapping. |
| P3-37 | AN-17 B | The track-row pattern is implemented twice and the "glass list row" four times; the duplicates have already drifted | The Profile "Топ треков" row has no overflow menu, no favourite toggle and no now-playing highlight, so the same track looks different in two screens. | Move `TrackRow` and a shared `GlassRow`/`SectionHeader` into a `ui/Components.kt`. |
| P3-38 | AN-17 B | `model.listened` is a public state holder that nothing collects | A `WhileSubscribed` Room query over the `history` table that no consumer ever subscribes to. | Delete the property, or wire it in. |
| P3-39 | AN-17 B | An indeterminate progress spinner sits *inside* a `.glass()` surface, forcing a full backdrop re-blur on every animation frame | Each `.glass()` call is an independent `hazeEffect` node with `blurRadius=22.dp`; the Profile screen can hold 18 simultaneous glass surfaces and the Library nests a `glass(12.dp)` inside a `glass(14.dp)`. | Keep the animated indicator outside the glass surface, cap the number of blurred surfaces, remove the nested `glass()`. |
| P3-40 | AN-17 B | Cover-art URLs are handed to Coil without a scheme check | The stream URL is https-validated, but the *artwork* URL is not: a remote `http://` artwork URL — or one carried in an imported backup — is fetched in cleartext on API 26-27. | Validate the scheme at ingestion and in `Cover()`. |
| P3-41 | AN-17 A/B | The home greeting is sampled with `LocalTime.now()` during composition | The app can greet the user with "Доброе утро!" in the evening until some unrelated state change occurs. | Derive the greeting from a state refreshed on a timer. |
| P3-42 | AN-17 A | Three directional icons are the non-auto-mirrored variants, so they point the wrong way in RTL | The manifest declares `supportsRtl="true"`, but `ArrowForward`, `ArrowBack` and `Sort` are taken from the non-mirrored packages. | Use `Icons.AutoMirrored.*`; `SkipPrevious`/`SkipNext` have no auto-mirrored variant and must be mirrored manually. |
| P3-43 | AN-17 A | The bottom navigation passes the tab label as the icon's content description, so TalkBack announces every tab name twice | "Главная, Главная" for each of the three destinations. | `icon={Icon(icon,null)}` — the adjacent `Text(label)` already provides the accessible name. |
| P3-44 | AN-17 A | Every entry into the Home tab restarts the recommendation load, including a fresh network search | `RecommendationLoader.request()` is not idempotent and the engine performs up to two 12-second SoundCloud searches whenever the local candidate list is short. | Make the loader idempotent within a freshness window; keep the manual "Обновить" button bypassing it. |
| P3-45 | AN-17 A | The light theme starts on a hard-coded dark window | There is no `res/values-night/` and the window background is the dark colour, so a cold start in the light theme shows a dark frame. (Still-unfixed prior-review item A P3-6.) | Add `res/values-night/styles.xml`. |
| P3-46 | AN-18 B | The player screen re-scans the whole library for the current track on every 2 Hz recomposition | O(N) string comparisons twice per second on the main thread. The identical lookup in the mini player was fixed in the previous round; the copy in `PlayerScreen` was not. | Pass the existing `remember(tracks){tracks.associateBy{it.id}}` map down. |
| P3-47 | AN-18 B | The lyrics' active line is found with a linear scan on every position tick | The parser allows up to 20 000 lines, so a pathological LRC payload costs 20 000 comparisons per tick. The list is already sorted, so a binary search is available. | Binary search over the time-sorted list. |
| P3-48 | AN-18 A | The seek slider's drag state is not saved across configuration changes | `scrub` uses `remember` while the neighbouring `tab` and `follow` use `rememberSaveable`, so a rotation mid-drag throws the drag away. | `rememberSaveable { mutableStateOf<Float?>(null) }`. |
| P3-49 | AN-18 A | The seek thumb snaps back to the pre-seek position on release | The scrub value is discarded in the same frame as the seek, and the seek is asynchronous, so the thumb and the elapsed label are drawn at the old position. | Keep the committed value until the reported position converges with it. |
| P3-50 | AN-18 A | Switching to the lyrics tab discards the already-loaded lyrics and re-shows the spinner | `loadLyricsInternal` unconditionally republishes `loading = true` before re-reading the cache, so every visit to the tab blanks the text. | Skip the reload when the state already holds a result for the same track; `retryLyrics()` must still bypass it. |
| P3-51 | AN-18 A / AN-26 A / XI-08 A | The repeat button cycles OFF → ONE → ALL; the desktop product cycles OFF → ALL → ONE | The first press gives "loop this one track" instead of "repeat the whole queue" — the mode most users want takes two taps. The icon and `stateDescription` mapping are correct; only the order differs. | Step through an explicit ordered list rather than incrementing the Media3 constant. |
| P3-52 | AN-18 A | The queue tab has no "clear queue" action, and the existing `clearQueue()` would stop playback instead of keeping the current track | A feature the desktop ships is silently absent. | Add a header action and make the helper keep the current item, matching the oracle. |
| P3-53 | AN-19 A | The "Умные" filter can list the previously opened smart playlist's tracks under the newly selected playlist's name | The header switches instantly to the new selection while the list still carries the previous one, so the counter and the highlighted rows are wrong — and a fast tap plays a track from a different smart playlist than the one named on screen. | Carry the selection together with its content and a loading flag; suppress the "Нет подходящих треков" empty state while loading. |
| P3-54 | AN-19 A | The catalogue import button counts raw entries, not the 500 that will actually be imported | The button promises "Импортировать список · 1000" while at most 500 distinct tracks are imported. | Render the count from the same capped/de-duplicated list the import uses. |
| P3-55 | AN-19 A | "Скачанная музыка" reports the byte size of *all* download rows next to the count of *completed* ones | A failed or paused download's partial bytes are added to the total, so the stated size exceeds the real one. (Same computation at `ui/SettingsScreen.kt:49`.) | Sum the bytes of the same subset used for the count. |
| P3-56 | AN-19 A | A blank playlist name would be reported to the user as Kotlin's raw "Failed requirement." | Latent (both call sites disable their button while the name is blank), but any future caller passing a blank name shows an English developer string in a snackbar. | Use `SourceFailure("Введите название плейлиста")`, the established pattern. |
| P3-57 | AN-19 A | A completed catalogue search that returns nothing is rendered with the same hint as the initial, not-yet-searched state | The user is told to go and look in playlists instead of being told the search found nothing. | Distinguish the two empty cases (e.g. a `hasSearched` flag). |
| P3-58 | AN-21 A | The equalizer band label can show a gain that is not the gain the hardware applies | The label prints the unclamped draft while the hardware applies the device-clamped value, so a stored +9 dB can be shown on a device whose range is ±6 dB. | Derive the displayed value from the same clamped value that is persisted. |
| P3-59 | AN-21 A | The stream-cache limit control can be silently discarded at start-up, and its read blocks the main thread for up to 1.5 s | If the DataStore's first emission takes >1.5 s the cache is created with the 256 MB default and the user's chosen limit is discarded with no message. | Read the limit off the main thread and surface a failure. |
| P3-60 | AN-21 B | A failed audio-settings write leaves the optimistic slider value on screen | The control shows a configuration that is not in effect; the discrepancy only surfaces when the user leaves and re-enters the screen, and the draft then snaps back. | Make the write result observable and reset the draft from the persisted value on failure. |
| P3-61 | AN-21 B | The profile editor is dismissed before the write is confirmed | A rejected name/bio (the model rejects control characters the UI does not filter) closes the dialog and discards the user's text; the snackbar message does not name the real cause. | Keep the dialog open until the write succeeds and align the UI filter with the model's `require`. |
| P3-62 | AN-21 B | The whole settings screen is re-composed ~1.33 times per second while any download progresses | The download list is collected at screen level but used for one summary line, so every 750 ms progress write re-runs ~30 composables including 8 sliders. | Move the summary into a small composable that collects only the aggregate it needs. |
| P3-63 | AN-21 B | The profile screen loads the entire `tracks` table to compute one number | A missing aggregate query means every track-table change re-reads and re-scans N rows in the composition scope. | Add a favourite-count query. |
| P3-64 | AN-21 B | A chosen avatar can never be removed | **[MERGED]** — same root cause as P3-35. | — |
| P3-65 | AN-21 B | Three desktop features have no Android counterpart and are not listed as platform differences | `gapless_playback`, `volume_normalization` and the `personalization.pinned_track` section are absent on Android and **undocumented** in the porting status, so every review pass re-reports them. | Add the three omissions to the platform-difference list. |
| P3-66 | AN-22 A | A second PKCE start silently invalidates the pending login, and the already-open browser session then fails with a security error | The browser tab opened by the first press carries the old `state`, so completing it yields «Проверка безопасности входа не пройдена» — a message that reads as a tampered callback. | Keep a per-attempt marker so a superseded callback is reported as "этот вход заменён более новым". Sx: a foreign `state` must still never overwrite credentials. |
| P3-67 | AN-22 A | A failed or expired Spotify callback leaves the panel claiming «ожидает входа», and there is no way to abandon a pending login | The pending is dropped only for the exact message «Вход Spotify отменён»; a state mismatch or an expired pending leaves the badge claiming a login that can never succeed. `cancelSpotifyLogin()` has **no caller anywhere in the app**. | Clear the pending on every terminal outcome and expose a cancel action. |
| P3-68 | AN-22 A | A failed Client ID / Yandex token save discards the value the user typed | The confirm button clears the field and closes the dialog **before** the result is known, so a rejected Client ID or a mistyped token costs the user a re-type. | Keep the editor open and the value until the operation succeeds. |
| P3-69 | AN-22 A/B | The connections panel announces neither its busy state nor its error to screen readers | The status line and the error line have no live region, while the sibling backup panel in the same screen does. | Add `Modifier.semantics { liveRegion = LiveRegionMode.Polite }` as `BackupControls` does. |
| P3-70 | AN-22 A | The Yandex OAuth token is masked on screen but is not marked as a password for accessibility services, so a screen reader reads the raw token aloud | `PasswordVisualTransformation` is a *visual* filter only; the raw value stays in the semantics tree as `EditableText`, and `SemanticsProperties.Password` is used nowhere in the app. | Add `Modifier.semantics { password() }`, keeping the visual transformation. |
| P3-71 | AN-22 B | An invalid "source name" in the desktop-import path is reported as a database read failure | The `origin` validation uses `require(...)`, which the catch-all rewrites as «Не удалось прочитать БД…» — a remedy unrelated to the actual cause. | Throw `SourceFailure` for the `origin` validation. |
| P3-72 | AN-22 B | The backup file picker does not effectively restrict the file type | `application/octet-stream` and `text/plain` are in the allow-list and `OpenDocument` sets the type to `*/*`. No security impact — the decoder is strict. | Narrow the MIME array to `application/json`. Sx: some providers store a `.json` as `application/octet-stream`. |
| P3-73 | AN-22 B | The fully decoded backup is retained in the ViewModel for the whole preview, although the panel renders only six integers | `pendingBackup` holds a materialised `LibraryBackup` — up to 20 000 tracks and 100 000 history sessions — on top of the decode peak of P2-16. | Retain the source (URI/bytes) plus the summary and re-validate at merge time. |
| P3-74 | AN-22 B | The failure taxonomy the backup panel shows is a string literal that no test pins | Three user-relevant outcomes (wrong format / unsupported version / corrupt content) reach the user through one `invalid()` funnel, and the test asserts only the exception *type* — so the three categories can collapse into one generic sentence while the whole suite stays green. | Assert the message (or add a stable error code) for at least the three categories. |
| P3-75 | AN-15 A / XI-03 A | A failed or interrupted *removal* is reported as a failed *download*; the only offered retry re-downloads the track and the removed files are never reclaimed | The user pressed "delete" to free space; the app says "repeat the deletion", the button next to it re-**downloads** the track, and the space is still not freed. | Give removal its own terminal state (e.g. `"remove_failed"`) and a dedicated control that re-enqueues `RemoveDownloadWorker`. |
| P3-76 | AN-15 A / XI-03 A | The API 34+ `dataSync` foreground-service quota is not handled; the download dies with an unrelated message | Every subsequent download fails with «Не удалось скачать трек», and retrying does not help until the quota window resets. | Recognise the foreground-start restriction explicitly and surface it. |
| P3-77 | AN-15 A / XI-03 A | The download cache and the streaming cache open the same Media3 SQLite database through two independent helpers | Two independent SQLite connections to one file can raise `SQLITE_BUSY` under concurrent writes. The media is **not** at risk — the key namespaces are disjoint. **HYPOTHESIS.** | Create one `StandaloneDatabaseProvider` per process and pass it to both `SimpleCache` instances, or give the download cache its own database name. |
| P3-78 | AN-13 A | The provider that actually supplied the lyrics is never recorded, so the source label is empty for every fallback | The user cannot tell which service supplied the text, and cannot judge its trustworthiness. | Pass a provider name into the cascade's `offer`/`accept` and set `result.source`. |
| P3-79 | AN-13 A | `lyricsResult` can throw and abort the whole lookup, losing an otherwise valid plain text | The lyrics tab shows "Не удалось получить текст" for a track whose plain lyrics were available and would have rendered. | Clamp instead of throwing at the call site, or wrap the call in `runCatching`. |
| P3-80 | AN-13 A | The lyrics disk cache key and record carry no format/provider version | Lyrics that the new build would refuse to accept are still served from the cache for up to 24 h — the old rules keep applying to already-cached tracks. | Add a `SCHEMA_VERSION` to the hashed key and a version field to the record. |
| P3-81 | AN-13 A | The lyrics disk cache lives in `cacheDir`, which Android may purge, so the offline promise is not durable | The cached lyrics silently disappear and the user is back to "нужно подключение к сети" in offline mode. | Move the lyrics cache to `filesDir` (or `noBackupFilesDir`) and update the backup-exclusion XML. |
| P3-82 | AN-23 A | The project's own Groovy DSL uses the space-assignment syntax that Gradle removes in Gradle 10 | The build fails to configure on the next Gradle major, at a moment when the developer is trying to move the SDK/dependency pins forward, and with no CI to catch it. | Change the three assignments to `namespace = …`, `compose = true`, `abortOnError = true`. |
| P3-83 | AN-23 A / AN-27 A | `VALIDATION.md` / `TEST_SUMMARY.json` report stale test and lint numbers | The observed figures are 236 JVM tests (not 217) and 15 lint warnings (not 17); the instrumentation count is 59 (not 55). A reader concludes that 18 unit tests are missing. | Regenerate the validation artefacts from the actual XML results. |
| P3-84 | AN-23 A | `unitTests.returnDefaultValues = true` plus the `SDK_INT=0` stub silently masks five API-gated production branches | A future test asserting "the app requests POST_NOTIFICATIONS" or "the FGS declares a dataSync type" would pass vacuously. The flag hides nothing *today* (0 unit tests reference an `android.*` type). | Remove the flag and supply real JVM implementations; the project already did this once for `AudioSettingsStore`. |
| P3-85 | AN-23 A | `run-emulator.ps1` tells the user to build an APK with a script that never builds APKs, and points at a path that does not exist | The documented "run the app" path fails immediately with an instruction that cannot be followed. | Make the message name the actual constraint and derive the SDK path from the same source as `verify.ps1`. |
| P3-86 | AN-23 A | `kotlin.incremental=false` forces a full recompile of every source set on every build | Measured `:app:compileDebugKotlin :app:lintDebug` = 5 m 8 s; a forced main-source recompile = 58 s. | Consider scoping the workaround to the junction-only path, or accept the cost as a defensible choice. |
| P3-87 | AN-27 A/B | `REVIEW_RESOLUTION.md` has already rotted: a row's factual premise is false in the current code | The row states that the app does **not** request `POST_NOTIFICATIONS`; the current tree **does** declare the permission and requests it at runtime. The same document says so 50 lines earlier. | Add a "проверено на снимке `<sha>` / <дата>" column and re-verify each row. |
| P3-88 | AN-27 A/B | The machine-readable results disagree about which run is final, contradict each other on the APK ban, and are not derivable from any artefact in the folder | `FINAL_CHECKS.json` is dated 2026-10-18 22:41 and contains no unit-test count; the actual final run is the 2026-10-19 07:41 pair. And the APK ban is recorded inconsistently within one day. | One machine-generated result file per run named `<stage>_<date>.json`; record the ban's effective date. |
| P3-89 | AN-27 A/B | `verify.ps1` has no header documentation, and the documented on-ramp dead-ends on a build the user forbids | Nothing says that it rewrites `local.properties`, that it creates ASCII junctions, or that it restores the original bytes. `run-emulator.ps1:19` points at "Build the APK with verify.ps1 first" — a command that by default cannot produce an APK. | Add a header comment block; change `run-emulator.ps1` to name the actual constraint. |
| P3-90 | AN-24 A/B | 35 of the 75 production files (3 977 LOC, 54.6 %) have **no** JVM test, and 5 of the 10 non-negotiable contracts have **zero** automated coverage of any kind | Contracts with no coverage at all: (1) player ownership in `MediaSessionService`; (2) no whole-queue URL prefetch; (3) minimum API 26; (5) partial cache ≠ completed download (the worker half); (6) never alter the user's library. | Add the four contract tests proposed in the AN-27 B report (source-scanning contracts, a queue-shape test, a `ListeningClock` seek case, a Room download-state test). |
| P3-91 | AN-24 A | The 55 instrumentation tests contribute nothing to the green gate — there is no `connectedDebugAndroidTest` in any task list | The Room migrations, the DAO batch inserts, the Keystore store, the Compose UI and the HLS downloader are covered only by tests that were **compiled and never run**. | Add a device-backed CI job, or mark the four resolution rows explicitly as "compiled only — no regression gate". |
| P3-92 | AN-24 A | `VALIDATION.md`'s "217 JVM passed" is not reproducible: the observed number is **236** | The validation record understates the suite by 19 tests. | Regenerate `VALIDATION.md` from the actual XML results. |
| P3-93 | AN-24 A | `LiveProviderProbeTest`'s opt-in is an environment variable only, with no build-level guard | If `NEDOTIFY_LIVE_PROBES=1` leaks into an environment the default task list performs real provider requests, writes a report, and **still passes** — every provider failure is caught into the JSON. | Add `@Ignore` as a second layer, and make the probe *fail* rather than swallow when it is enabled. |
| P3-94 | AN-24 A | `LyricsCascadeTest` asserts exact HTTP request counts under a real 2 200 ms provider deadline | On a loaded agent the count is 4 and the test fails even though the code is correct — while a *real* regression that skips a provider would be indistinguishable. | Assert the set of providers consulted via a recording fake, or raise the fixture's budget. |
| P3-95 | AN-24 A | `ProfileSettingsTest` asserts the *contents of a constant* instead of the acceptance rule | The test breaks if the palette is legitimately changed and passes unchanged if the *rule* it advertises is broken — and that rule lives in `Preferences`, which has no test at all. | Replace the constant assertions with a behavioural test over a JVM DataStore. |
| P3-96 | AN-26 A | The desktop's `play_count`/`last_played` have no Android counterpart; `genre`, `year`, `track_number` and the technical fields are dropped by the import | The Android re-derives play counts from `history`, and the metadata the desktop *searches and sorts by* is unrecoverable from the Android copy. Documented in `PORTING_STATUS.md`, so it is a declared difference — but the *capability* it removes is not called out. | Add the columns if they are wanted, or name the lost capability in the notice. |
| P3-97 | AN-26 A | The report window arithmetic differs (rolling 24 h × N vs N calendar days) and the desktop's "year" period has no Android counterpart | The same history yields slightly different totals at the window edges. | Add `ReportPeriod.YEAR` and either mirror the rolling definition or document the calendar-day choice. |
| P3-98 | AN-26 A | Repeat-one produces one accumulating history row on the desktop but a new session per repeat on Android | The measured *time* is the same, but the *session count* differs, and therefore the profile's "N прослушиваний" and the number of exported history rows differ for identical listening activity. | Decide which model is canonical and make the other platform match. |
| P3-99 | AN-26 A | The Android's library search covers only device files and completed downloads; the desktop's FTS search covers the whole library | A track played from an online search and added to a playlist is invisible in the Android's device/library search. | Widen the query to all library rows, or state the device-only scope in the UI. |
| P3-100 | AN-26 A | Settings defaults diverge behaviourally in the streaming-cache quota and in loudness normalisation | The Android evicts the streaming cache at 256 MB instead of 500 MB and never evicts by age, so the same usage produces a different disk footprint and more re-resolving. | Align the default quota or justify the smaller mobile default; add an age-based eviction step. |
| P3-101 | AN-26 B | The cross-platform format is defined twice by hand and the Android reads the desktop's *private* schema | 29 column names, 5 table names, 7 smart-rule keys, 5 sort values and the whole "completed listen" predicate are reimplemented by hand, with no spec, no golden fixture, no conformance test and no CI job. | Publish a versioned field/table inventory both trees cite, and add a shared fixture that the desktop test asserts and the Android test imports. |
| P3-102 | AN-19 B / AN-22 B | The backup import/export state machine is spread over seven state holders in three layers | One operation lives in five `StateFlow`s plus a plain `pendingBackup` field plus a Compose-state `backupPickerOpen`, so a mismatch cannot be detected by any test. | One sealed operation state (`Idle / Inspecting / Preview / Merging / Failed`) exposed as a single `StateFlow`. |
| P3-103 | XI-01 A | `NowPlaying` carries no error state: the mirror never reads `player.playerError` | A failed track is rendered as a normal paused "now playing" — the actionable message never reaches the player screen. | Add an error dimension to the mirrored state and surface it next to the transport. |
| P3-104 | XI-01 A | The `Player.Listener` is attached only after the controller connects, and nothing re-reads the error afterwards | A failure that happens before the listener exists is never surfaced: no snackbar, no error state. | Treat the connect step as "attach + seed": after `addListener`, read the controller's current state including `playerError`. |
| P3-105 | XI-01 A | `MediaController.Listener.onError` assigns a nullable message into the message channel | A `SessionError` without a message clears pending messages and the error is dropped. | `message.value = error.message ?: "Ошибка воспроизведения"`. |
| P3-106 | XI-01 A | `AudioRuntime.status.crossfadeActive` is never reset when the player is released | The Settings screen keeps claiming "Сейчас звучит переход между треками" although nothing is playing. | Reset `fading=false` in `close()`, and/or derive the hint from the mirrored playback state. |
| P3-107 | XI-08 B | `toggle()` branches on a *stale* controller snapshot | The `STATE_ENDED`/`STATE_IDLE` branches are decided from a snapshot that can be one push-interval behind, so the first press at the end of a track does nothing. | Read the transport state from the ViewModel's own mirror, or make the ENDED branch tolerant. |
| P3-108 | XI-08 B | No `MediaController.Listener.onDisconnected` handling | After a session death the UI keeps a stale "now playing" and the transport buttons silently do nothing. | Override `onDisconnected` and clear/flag the playback state. Sx: it also fires during a transient rebind. |
| P3-109 | XI-02 A | The failure is announced to the user *before* the automatic recovery runs | A self-healing error still shows a failure message (twice) — and then the track plays. | Announce the failure only after the retry budget is exhausted. |
| P3-110 | XI-02 A | The stream-cache key omits the stream format | A format change between two searches becomes a hard "format changed" refusal that re-searching cannot fix. | Include the expected format in the cache key, or invalidate on mismatch. |
| P3-111 | AN-23 B | `haze` drags the JetBrains Compose Multiplatform coordinates and a `kotlin-stdlib` newer than the project's compiler, and pins `minCompileSdk=37` | An upgrade of Haze or of Kotlin can pull a new Compose coordinate family or a newer stdlib into the classpath. The JetBrains artifacts are empty shims, so there is no duplicate-class risk. | Keep Haze; record the constraint in a comment. *If it is ever dropped it is a **one-function** change* - all 35 `.glass()` call sites route through `Modifier.glass()` at `ui/Design.kt:71`. |
| P3-112 | AN-23 B | No Coil `ImageLoader` is configured, so cover art is fetched by a second, unconfigured `OkHttpClient` | A slow or oversized cover response can hold a request far longer than the app's own policy allows, and nothing bounds the bytes or the decoded bitmap. | Install a `SingletonImageLoader` on a dedicated client with explicit timeouts and a response-size cap. |
| P3-113 | AN-23 B | The build is not hermetic: an SDK-metadata version mismatch is already reported, the build is Gradle-10-incompatible, and the configuration cache is off | ~11.5 s of configuration on every invocation; a build that will break on Gradle 10 with no advance notice; a lint gate whose result depends on Maven Central's state rather than on the source. | Fix the Gradle-10 deprecations with `--warning-mode all`; enable `org.gradle.caching`; enable the configuration cache only after validating it against the full suite. |
| P3-114 | AN-23 B | `kotlin.incremental=false` costs a measured 33.6 s full-module recompile for a one-line edit | The inner dev loop is ~34 s of pure recompile per edit instead of seconds; with 10-20 edits per session that is 6-12 minutes of pure waiting. | `kotlin.incremental=true` **and** separate the two build roots - the flag alone re-introduces the path-aliasing inconsistency the comment describes. |

**Consolidation note.** 110 P3 rows were raised; the 21 marked **[MERGED]** above
were each reported by two or more agents under different ids and appear once.
The P3 register is a *table* because the evidence for each row is the source
line cited in the subagent report; only the P2 and P1 rows were expanded to the
full evidence format.

---

## 6. Cross-Module Findings

Some of the most consequential defects do not belong to a single area — they
appear only when two modules are read together. Six of them are recorded here
rather than in §4/§5, because a reviewer who read only one side of the pair
would not have found them.

### X-01 — The app has **two** playback states, **three** "is this still current?" mechanisms and **four** "generation" counters [MERGED ×4]

**Areas:** AN-02, AN-03, AN-05, XI-01, XI-02, XI-08 (A and B, six agents).

| Concept | Implementations | Owner |
|---|---|---|
| "what is playing" | `MediaControllerImplBase.playerInfo` (Media3) · `MusicViewModel.playback: NowPlaying` · `AudioRuntime.status` | three layers, two of them in this codebase |
| "is my async work still current?" | `PlaybackService.interactionVersion` · `PlaybackPreparation.generation` · `MusicViewModel.catalogGeneration` · `ProviderConnections.spotifyGeneration`/`yandexGeneration`/`catalogScope` · `offline_downloads.generation` (a UUID — a *different* concept with the same name) | five layers |
| "a pending one-shot operation" | `PlaybackPreparation` (ViewModel) · `PendingSelectionGate` (service) | two layers, unconnected |
| "is the request still current?" predicate | three in `PlaybackService` alone (`:173`, `:209-211`, `:266-267`), two of which repeat the literal `(0 until player.mediaItemCount).map{…}==ids` — an O(N) allocation evaluated inside a 50 ms retry loop | one layer, three copies |

**Why this is a finding and not a style note.** The two protocols that protect
the same state — `interactionVersion` (service) and `PendingSelectionGate.playAllowed`
(service) — are tripped by the *same* event (`onUserInteraction`) but have
*different* release conditions. `interactionVersion` is released by any new
interaction; `playAllowed` only by a new queue set, and (P1-02 in the register,
see §5) its release hook (`MediaSession.Callback.onPlayerCommandRequest` with
`COMMAND_PLAY_PAUSE`) is **never reached** by `MediaController.play()`/`pause()`
in Media3 1.11.1 — only `setPlayWhenReady` dispatches through that path. The
two protocols therefore disagree exactly in the window that matters, and the
consequences are P2-11 (a swallowed Play), P2-12 (a discarded queue selection)
and P2-13 (a cancelled restore).

**The concrete cost, measured.** One `next()` on a 3000-track queue costs:
two full-queue JSON serialisations (~270 KB of string churn), two whole-DataStore-file
rewrites (~270 KB of flash writes), one full-queue rebuild in the ViewModel
(9 000 allocations), one Room write, one ExoPlayer source switch, and one
full-screen Compose recomposition — all on the main thread except the writes.
A burst of 10 presses multiplies every line by 10.

**Fix direction.** One intent token, owned in one layer, replacing the boolean
latch and the two per-layer generations; one "now playing" source of truth; and
the queue list removed from the per-event snapshot (P2-34).

### X-02 — The queue snapshot is the app's only durable session state, and it is written into the settings file

**Areas:** AN-03, AN-05, AN-16, XI-06, XI-08 (A and B).

The queue + position is the only thing that survives process death. It is
written as a JSON blob into the *settings* DataStore, every 5 seconds, with
the playback position embedded in the compared value — so the de-duplication
guard can never suppress a write (P2-01), and a whole settings file is
rewritten for it. The desktop caps the persisted queue at 200 entries and
writes **once, at exit** (`core/session.py:9,50-55`).

Meanwhile the *format* has no version check on read, the storage key
(`queue_v1`) disagrees with the payload version (`2`), and the format lives as
a private string inside a `MediaSessionService` — unreachable from a JVM test
(XI-06 B, ARCH-3).

**Fix direction.** A typed `QueueSnapshotCodec` (the pattern
`data/BackupCodec.kt` already demonstrates), the identity of the queue
separated from the volatile position, two storage slots so a seek does not
rewrite the id list, and a persisted-queue cap as the oracle has.

### X-03 — The offline download store and the streaming store are two mechanisms for the same concept

**Areas:** AN-15, AN-11, XI-03, XI-05 (A and B).

Both are Media3 `SimpleCache` instances. Both are supposed to hold "bytes the
app already fetched". But they disagree on *identity*: the download store keys
by a per-track SHA-256 prefix plus a normalised URL, while the streaming store
uses Media3's default key — the **full signed URL**. The consequence (P2-47)
is that the streaming cache's advertised 64 MB–1 GB quota is essentially
inert: every re-resolution produces a new key, the bytes are never read
again, and the LRU evicts exactly those never-re-read entries first.

They also disagree on *integrity*: the download path has no completeness check
(P2-50) and no size ceiling (P2-30), while the streaming path has a signed-URL
TTL. And they share one SQLite index file through two independent helpers
(P3-77).

**Fix direction.** One cache-identity helper used by both paths, keyed by media
identity rather than by URL; one shared `DatabaseProvider`; and the download
store given a real budget.

### X-04 — The app has no single definition of "offline"

**Areas:** AN-11, AN-12, AN-14, AN-15, AN-16, XI-05 (A and B, six agents).

The same boolean is read in **nine** places by four different mechanisms:
`ViewModel.requireOnline()` (a cold `first()` on a preferences flow), the
`LibraryRepository.resolve()` gate (the authoritative one), the
`OnlineSource` re-check, the Compose `LocalOffline` composition local (which
only *hides* remote artwork), the `DiscoveryEngine` ranking change, the
`Downloads`/`TrackDownloadWorker` pause, and the service's collector.

The *value* is consistent — all read the same DataStore key — so there is no
stale-value divergence. What there is instead is **no single place that defines
what offline means**: the semantics are re-derived at each site, and the sites
disagree in kind. One is a control-plane guard (block user-initiated provider
actions); one is a data-plane guard (block remote resolution); one is a
presentation rule (hide remote images). The service reacts through a
*different subscription* than the UI, so the UI's `pause()` and the service's
`player.stop()` are separated by an unbounded-by-construction DataStore round
trip — and bytes keep flowing in that window (P2-73).

**Fix direction.** One `StateFlow<Boolean>` exposed by the repository, one
service command that both stops the loader and starts the reconcile, and the
artwork rule scoped to "is this item locally backed?" rather than "are we
offline?".

### X-05 — The user's library has no single writer, and three of its writers can silently change its meaning

**Areas:** AN-02, AN-05, AN-06, AN-07, AN-20, XI-07 (A and B).

- The library (`tracks`) is written by the MediaStore scan, the SAF import, the
  catalogue import, the **playback preparation**, and the backup restore.
- There is **no** `DELETE FROM tracks` anywhere in the DAO and no UI action to
  remove a track — so every one of those writes is permanent.
- The playback preparation writes the **entire** search result list into the
  library (P2-31), which floods «Для тебя» with tracks the user never chose.

**Fix direction.** Separate the *queue* store from the *library* store, and add
the missing delete path.

### X-06 — The desktop's storage schema is the de-facto wire format, and it has no version

**Areas:** AN-08, AN-26, XI-07 (A and B).

The "cross-platform library format" is not the `nedotify-library` JSON — the
desktop cannot produce or consume it (zero backup methods in `core/api.py`).
The actual channel is the desktop's **private SQLite schema**, reimplemented in
Kotlin: 5 table names, 29 column names and ~12 semantic rules, with no
version marker, no golden fixture, no conformance test and no CI job
(P3-101). The desktop's own comment at `core/database.py:1858-1866` describes
exactly the failure mode — "the recent writes are lost without a word".

**Fix direction.** A versioned contract both trees cite, plus a generated
fixture the desktop test asserts and the Android test imports.

---

## 7. Security & Performance

### 7.1 Security

**What is genuinely good.** These are not filler; they were checked and hold.

| Control | Evidence |
|---|---|
| The app never modifies a file the user picked | `DesktopLibraryImport.kt` copies the source into `cacheDir` and opens the copy; `DesktopLibraryImportTest.kt:24-26` hashes the source before and after. |
| The desktop import has no SQL-injection surface | Table names are literals; column names come from a hard-coded list filtered against `PRAGMA table_info`; `rows()` requires `sqlite_master.type == "table"`, which blocks the "view with injected SQL" trick. |
| The backup format has no path traversal | `localUri` is blanked on encode and any backup that still contains one is **rejected**; the desktop import never selects `file_path` or `cover_path`; the temp file name is a generated UUID. |
| The backup decoder is strict | `requireStrictJson` rejects duplicate keys (including a `\uXXXX`-escaped duplicate), trailing data, a non-object root, nesting deeper than 32, unterminated strings, raw control characters, invalid escapes, invalid JSON numbers, comments, single quotes and unpaired surrogates; invalid UTF-8 is rejected *before* the parser runs; unknown fields are rejected rather than silently dropped. |
| Provider secrets never leave the device | AES-GCM in the Android Keystore with the key name bound as AAD; excluded from the library backup (the format carries only tracks/playlists/history/smart-playlists). |
| The system backup excludes everything | `data_extraction_rules.xml` and `backup_rules.xml` exclude `root`, `file`, `database`, `sharedpref`, `external` and all `device_*` domains for both `cloud-backup` and `device-transfer`. |
| The offline read path is physically network-free | `OfflineSources` builds the source with `setUpstreamDataSourceFactory(null)` — a cache miss fails locally instead of silently re-fetching. |
| No cleartext traffic | `usesCleartextTraffic="false"`; the only `http://` occurrences are XML feature URIs. |
| `minSdk 26` is genuinely safe | The **highest** dependency minSdk across all 139 AARs in the Gradle cache is 24; lint's `NewApi` detector (severity *error*) reported 0 errors. |

**Gaps, in order of severity.**

1. **The exported media session is open to any Media3-"trusted" controller
   (P2-04).** `isTrusted` is true for the system UID, the app's own UID, a
   holder of `STATUS_BAR_SERVICE` or `MEDIA_CONTENT_CONTROL`, **or an enabled
   notification-listener service**. A third party can therefore read the
   Now-Playing metadata and the whole queue (the user's listening history and
   library contents), drive transport, and replace or clear the queue. It
   **cannot** inject a URI — `onSetMediaItems`/`onAddMediaItems` rebuild every
   item from the database row — and it cannot reach the OAuth tokens. The fix
   is a one-line split: full commands for the same package, read-only for
   everyone else.
2. **The media/CDN request carries no headers (P2-51).** `User-Agent:
   okhttp/4.12.0`, no `Referer`. The desktop sends a Chrome UA on every
   upstream request. This is a *correctness* gap (403 on the first byte) that
   happens to also be a bot-detection gap.
3. **The media URL is not host-allow-listed and redirects are followed
   unvalidated (P2-52).** The pattern already exists in the same codebase
   (`YandexDownloadInfo.trustedUrl`) and is applied to exactly one of three
   providers.
4. **The Genius lyrics host allow-list is bypassable by a redirect (P3-30).**
5. **No certificate pinning for the three token-bearing origins (P3-19).**
   Bounded — a public PKCE client with no secret, so a leaked access token
   grants only the three read scopes that were requested. The absence is
   confirmed; whether to pin should be a recorded decision either way.
6. **The Yandex OAuth token is read aloud by screen readers (P3-70).**
   `PasswordVisualTransformation` is a *visual* filter only; the raw value
   stays in the semantics tree, and `SemanticsProperties.Password` is used
   nowhere in the app.
7. **The download notification leaks the track title on the lock screen**
   (XI-03 B, F-XI03-4): the channel keeps the platform default
   `VISIBILITY_PRIVATE` and the text is the unredacted title.
8. **Cover-art URLs are fetched without a scheme check (P3-40)** — an `http://`
   artwork URL in an imported backup is fetched in cleartext on API 26-27.
9. **Persisted URI grants are never released (P3-01)**, and a revoked grant
   fails silently (P3-35).
10. **The backup's 16 MB cap does not bound the heap (P2-16, P2-30).** A
    16.4 MB document that the codec itself accepts needs ~120 MB of live heap
   and throws `OutOfMemoryError` at `-Xmx160m` — and `OutOfMemoryError` is an
    `Error`, so it escapes every `catch (Exception)` and kills the process
   instead of producing the promised message.

### 7.2 Performance

**Measured / derived costs, worst realistic case.**

| Site | Cost | Trigger |
|---|---|---|
| `checkpointQueue()` (P2-01) | ~135 KB JSON + a ~135 KB whole-file DataStore rewrite, on the **main thread**; ≈270 KB of flash writes per track change; ≈27 KB/s while playing (≈100 MB/hour) | every seek, every track change, every 5 s |
| `NowPlaying` rebuild (P2-34) | 3 000 `Pair` allocations + 3 000 `Pair.equals` on the main thread, inside `Player.Listener.onEvents` | every track change, every metadata event |
| Standby deck rebuild (P2-27) | 3 000-element list copy + a 3 000-window `Timeline` + a 3 000-element shuffle traversal, **while the outgoing track is audible** | every track boundary with crossfade on |
| `refreshQueueSources` (XI-05 B) | O(N) `MediaItem` construction + O(N) deep `MediaItem.equals` (≈40 field comparisons per item) on the service's main scope | every completed/failed download, every offline toggle |
| Listening report (P2-07) | 6 SQL statements per snapshot, re-run **every 5 s** while the Profile tab is open; with `ReportPeriod.ALL` four of them scan the whole `history` table with a **365-branch `CASE`** per row | Profile tab open + playing |
| Search pipeline (P2-60, P2-61) | a 126 KB JSON parse and a 50 000-node DOM walk **on the UI thread**; the catalogue path parses multi-hundred-kilobyte Yandex documents on the main thread | every search / catalogue open |
| Local DB search (P2-59) | 20 000 rows -> 0.537 s of SQL on desktop, several times that on a phone, plus a Kotlin filter over every row | every "Все" search |
| Profile screen (P2-07, P3-63) | the entire `tracks` table re-materialised to count favourites; the report re-drawn ~12×/min | Profile tab open |
| Settings screen (P3-62) | ~30 composables including 8 sliders re-composed ~1.33×/s | any download in progress |
| `audioCache` construction (P2-02) | up to 1.5 s of `runBlocking` on the **main thread** at every cold start | every cold start |
| `DownloadStorage` first touch (P3-? / AN-15 A) | a directory listing + a SQLite read on the caller's thread | first offline track of a session |
| The queue `LazyColumn` key (P2-33) | the visible part of the list destroyed and re-created on every reorder | every reorder/remove |

**The structural observation.** Almost none of these is a "slow algorithm" in
the usual sense. They are **whole-collection rebuilds triggered by a
single-item change**, and they all happen on the main thread. The three
highest-value fixes are therefore structural rather than micro-optimisations:

1. **Do not carry a collection inside a per-event snapshot.** Split the queue
   list out of `NowPlaying` and rebuild it only on `EVENT_TIMELINE_CHANGED`
   (P2-34, P3-107, XI-08 B).
2. **Do not compare a value that always changes to decide whether to write.**
   Split the queue *identity* from the playback *position* (P2-01, X-02).
3. **Do not re-materialise the whole queue to change one item's source.**
   Resolve the effective source at open time — the `ResolvingDataSource` seam
   already exists and is already lazy, per-item and correct (XI-05 B, ARCH-1);
   the `refreshQueueSources` machinery is a **second, parallel** source-of-truth
   mechanism that can disagree with the first one, and it does (P2-49/P2-50 in
   the register, XI-05 B).

**The `setMediaItems` outlier.** The client builds N `MediaItem`s, Media3
converts every one into a `Bundle`, ships them through the binder, the service
unparcels them — and then **throws all of them away**: `onSetMediaItems` uses
only `items.map { it.mediaId }`, re-reads the tracks from Room, and constructs
N *fresh* `MediaItem`s. For a 3000-track queue that is 3 000 `Bundle`
allocations + 3 000 parcel writes + 3 000 parcel reads + 6 000 `MediaItem`
constructions — the dominant cost of the entire "tap a track" path, and entirely
avoidable. Note that the desktop's proxy does the same job far more cheaply:
it resolves out-of-band and hands Media3 a stable local URL.

**The toolchain cost.** `kotlin.incremental=false` is a deliberate trade-off
(the junction alias breaks incremental metadata), and it is paid on every
iteration: `:app:compileDebugKotlin :app:lintDebug` measured **5 m 8 s**; a
forced main-source recompile **58 s**.

---

## 8. Architecture Improvements

These are not defects. They are places where the *shape* of the code makes a
class of defect possible, and where a change would remove a whole family of
bugs rather than one instance. Ordered by leverage.

### A-1 — Extract the queue snapshot into a typed codec

**Today:** the format is a private string produced and consumed inside
`MediaSessionService` (`PlaybackService.checkpointQueue()` and the `prepare`
block), with a `version` field that is written but never read, a storage key
that disagrees with it, and no test — the format is unreachable from a JVM
test because it needs a `MediaSessionService`.

**The target:** `data/QueueSnapshotCodec.kt` with a `QueueSnapshot` data class
and `encode`/`decode`, exactly as `data/BackupCodec.kt` already demonstrates
for the library backup.

**What it removes:** the whole class of "the compared value and the persisted
value are the same string, so the de-duplication guard can never fire" (P2-01);
the version-marker inconsistency (P3-34); the un-restorable-after-a-crash
format; and the inability to unit-test the restore at all. A round-trip test
plus a test of the form "two snapshots with the same queue identity but
different positions must not produce two writes" pins the defect in a type
instead of in a string comparison buried in a service method.

### A-2 — Replace the boolean latch with an explicit intent token

**Today:** `PendingSelectionGate.playAllowed` is a boolean whose trip wires
are every player command and whose release wire is a Media3 callback the
app's own command path never triggers (P2-11, and the XI-08 B P1).

**The target:** a one-shot token, like `PlaybackPreparation.generation` but
owned in one layer, with the two intents separated: "the user changed the
*queue*" (cancels a pending queue build) versus "the user changed the
*playback state*" (cancels a pending play intent, not the queue). The
`PendingSelectionGate` and `PlaybackPreparation` mechanisms are the same
pattern in two layers with different semantics and no shared vocabulary;
merging them removes X-01.

### A-3 — One "now playing" source of truth

**Today:** three copies — Media3's `playerInfo`, the ViewModel's `NowPlaying`,
and `AudioRuntime.status` (for the crossfade flag). The ViewModel's copy omits
the error dimension (P3-103) and the listener is attached too late to catch a
pre-existing error (P3-104).

**The target:** one mirrored state that includes the error, seeded on connect,
and one owner for the crossfade flag.

### A-4 — Resolve the effective source at open time, not by rewriting the queue

**Today:** the source is encoded *in* the `MediaItem` (URI scheme + an
`OfflineAsset` tag), so changing it requires rebuilding the queue — the O(N)
main-thread `refreshQueueSources` machinery, with a trigger set that covers
only the completed-download table and therefore misses `localUri` changes
entirely (XI-05 B, F-XI-05-2).

**The target:** the `ResolvingDataSource` seam the app already has, asking
"is there a completed download for this id? -> use the offline store; else ->
remote". The `refreshQueueSources` machinery then disappears, along with the
trigger-coverage gap, the O(N) rebuild and the URI-less-item class of bug
(XI-05 B, ARCH-1).

### A-5 — Make the dependency graph substitutable

**Today:** a manual service locator whose contract is a cast —
`(application as NeDotifyApp)` in four places. The visible cost is that the
`player/` unit tests cover only the pure functions that were *deliberately
extracted out of* the service (`QueueSelectionTest`, `PlaybackMutationTest`,
`PendingSelectionGateTest`); there is no `MusicViewModelTest`, no
`PlaybackServiceTest`, no `NeDotifyAppTest`. The parts that were extracted are
exactly the parts that are tested.

**The target:** a `ServiceLocator`/`AppGraph` created in `NeDotifyApp.onCreate`;
components receive the *interfaces* they need; the ViewModel gets them through
a `ViewModelProvider.Factory`.

**The second reason:** the manifest declares no `android:process`, so the cast
is safe *today*. The moment a second process is introduced — a WorkManager
`:remote` process, a dedicated downloads process — `applicationContext as NeDotifyApp`
dies with a `ClassCastException` at the first `app.downloads` access, with no
compile-time or test-time signal.

**The teardown half is *not* worth porting.** The desktop's `AppCore.cleanup()`
exists because the desktop owns threads, a local HTTP proxy and a child process;
Android owns none of those. Only the substitutability half is worth it, and the
single highest-value change is to let `MusicViewModel` take its dependencies as
constructor parameters with a `Factory` — that alone would make the largest
orchestration class in the app testable on the JVM.

### A-6 — One "offline" authority, one "preferences" authority

**Today:** the offline flag is a network-mode flag stored inside the *theme*
data class and read through 12 independent cold DataStore reads (P2-46);
"offline" is defined nine times by four mechanisms (X-04).

**The target:** a typed preferences group per concern, exposed as cached
`StateFlow`s from a repository that owns a scope.

### A-7 — One identity policy for the library

**Today:** the backup format and the merge policy are split across two files
with the identity rules implicit in both — content-addressed remote ids,
device-scoped local ids, a random per-device `UUID` for playlists, and
`desktop:<libraryId>:<id>` for imported ones. A single explicit identity table
would have made the "restoring a backup on a device that already has a
same-named playlist creates a second, indistinguishable playlist" defect
(AN-07 A, F-AN-07-3) a design decision rather than a bug.

### A-8 — Make the download state machine a type

**Today:** `"queued" | "preparing" | "downloading" | "complete" | "paused" |
"removing" | "failed"` are bare literals in four files, and the single
`"failed"` state is overloaded for two different terminal conditions — which
is exactly why a failed *removal* offers a retry that re-downloads the track
(P3-75). A sealed/enum state plus a separate operation kind makes that
structurally impossible.

### A-9 — A "no silent state loss" invariant for the user's library

**Today:** the library is written by five different paths, has no delete
affordance, and is polluted by playback (P2-31). **Target:** an explicit
`inLibrary` flag honoured by every library query, a delete path, and an
assertion in the test suite that a play never adds a library row.

### A-10 — Retiring the SHA-manifest mechanism in favour of git

The manifest chain is seven overlapping files with two names for one artefact
and an unverifiable baseline (P2-42). Tracking `android/` in git makes every
one of those problems disappear, and it is a prerequisite for A-5 (a commit id
is the audit anchor) and for the CI job that would actually gate the port.

---

---

## 9. Test Results

All results below were **observed during this audit**, not read from a prior
report. Commands and their exact exit codes are given.

### 9.1 Android — build, unit tests, lint

Build harness: `android/verify.ps1` (the project's sanctioned entry point; it
uses ASCII junction aliases so the Windows path does not break the Android
SDK, temporarily rewrites `local.properties`, and restores the original bytes
in a `finally`).

| Command | Result | Exit code |
|---|---|---|
| `verify.ps1 -Tasks @(':app:testDebugUnitTest',':app:lintDebug',':app:compileDebugAndroidTestKotlin')` | BUILD SUCCESSFUL | **0** |
| `verify.ps1 -Tasks @(':app:testDebugUnitTest','--rerun')` | BUILD SUCCESSFUL, tests **actually re-executed** | **0** |
| `verify.ps1 -Tasks @(':app:testDebugUnitTest',':app:lintDebug',':app:compileDebugAndroidTestKotlin','--rerun-tasks')` | **BUILD FAILED** — see 9.3 | **1** |

**Unit tests (observed, from `app/build/test-results/testDebugUnitTest/*.xml`):**

```
FILES=42   TESTS=236   FAILURES=0   ERRORS=0   SKIPPED=1
skipped: ru.nedotify.app.data.LiveProviderProbeTest :: liveSourceReadiness
```

The single skip is the opt-in live provider probe — it is gated behind
`NEDOTIFY_LIVE_PROBES=1`, so the default run is hermetic.

**Lint (observed, from `app/build/reports/lint-results-debug.xml`):**

```
LINT_ISSUES=17   Warning=17   Error=0
NewerVersionAvailable x8   GradleDependency x5   UseKtx x2
AndroidGradlePluginVersion x1   ExportedService x1
```

`lint { abortOnError true }` fails the build on *errors* only; the 17 warnings
are informational (dependency-age and one exported-service advisory).

**Compilation (observed):** `:app:compileDebugKotlin` and
`:app:compileDebugAndroidTestKotlin` both succeed. The Kotlin compiler emits
4 warnings in the main source set and 5 in the instrumentation source set:

* main: `AudioRuntime.kt:6` `Virtualizer` is deprecated; `BrowseComponents.kt:43`,
  `LibraryScreen.kt:110`, `SearchScreen.kt:116` use non-auto-mirrored icons
  (`ArrowForward`, `Sort`, `ArrowBack`) — the latter three are RTL correctness
  issues on a `supportsRtl="true"` app.
* androidTest: all five Compose test files use the **v1** `createComposeRule` /
  `createAndroidComposeRule`; the v2 API is recommended because it uses
  `StandardTestDispatcher` instead of `UnconfinedTestDispatcher`. This is a
  scheduled breaking change for tests that rely on immediate execution.

**Instrumentation tests: NOT EXECUTED.** `verify.ps1` runs
`:app:compileDebugAndroidTestKotlin` — which only *compiles* them. There is no
`connectedDebugAndroidTest` task, no emulator orchestration and no Android CI
job. **15 instrumentation files therefore have never been run by any automated
task in this project.** The Room migrations, the Keystore credential store,
the SAF download storage, the Compose UI and the dual-deck handover — the five
highest-risk areas of the port — are covered *only* by tests that never run.

**APK builds were not attempted**, per `android/AGENTS.md`
("The user currently forbids building APKs"). No `assemble*`, `bundle*` or
`package*` task was run. Consequently **no artefact was produced and no
on-device behaviour was observed** by this audit.

### 9.2 Desktop reference app — pytest

The Windows desktop app is the parity oracle; its suite was run to confirm the
reference implementation is itself green.

```
$ .venv_win\Scripts\python.exe -m pytest tests -q
1459 passed, 1 skipped, 3 xfailed in 116.21s
PYTEST_EXITCODE=0
```

(The suite writes some deliberate failure-path diagnostics to stderr; the
first run appeared to exit 1 because PowerShell merged stderr into the success
stream. Re-running with stderr separated confirms pytest's own exit code is
**0**.)

### 9.3 Automated checks that FAILED, and why it matters

`verify.ps1 -Tasks @(':app:testDebugUnitTest',':app:lintDebug',':app:compileDebugAndroidTestKotlin','--rerun-tasks')`
→ **BUILD FAILED**, exit code 1, with four failures:

```
> Task :app:lintAnalyzeDebug FAILED
> Task :app:lintAnalyzeDebugUnitTest FAILED
> Task :app:lintAnalyzeDebugAndroidTest FAILED
java.io.FileNotFoundException:
  app/build/generated/ksp/debug/kotlin/ru/nedotify/app/data/LibraryDao_Impl.kt
  (Системе не удается найти указанный путь)
> Task failed: Failed to stop service 'LintClassLoaderBuildService_...'
```

**Cause:** `--rerun-tasks` forces *every* task to re-run, including the
Room/KSP code-generation tasks. The lint analysis tasks then start before (or
instead of) the regenerated KSP sources being available to them, and fail with
`FileNotFoundException` on the generated `LibraryDao_Impl.kt` /
`LibraryDatabase_Impl.kt`. A fourth failure is the lint classloader service
failing to stop.

**Consequence, and why it is a real finding rather than a tooling curiosity:**
the project's only sanctioned build script cannot be used to force a clean
rebuild. `--rerun-tasks` — the standard way to defeat a stale build cache — is
broken. The workaround used for this audit was to run the test task alone with
`--rerun`, which works (236 tests re-executed, 0 failures). The second-order
effect is that **a developer cannot reliably reproduce a from-scratch build
through the sanctioned script**, which weakens the "the build is green" signal
the project relies on.

### 9.4 What was NOT verified (explicitly)

| Not verified | Why |
|---|---|
| On-device audio playback, decoding, seeking, audio focus, becoming-noisy | No Android device or emulator available in this environment; APK builds forbidden |
| Foreground-service behaviour on real API levels | no device |
| Room migration behaviour on a device (migrations are compiled, not run) | no device |
| Keystore hardware backing and key-invalidation behaviour | no device (`SecureProviderStoreTest` is instrumentation-only) |
| The 55+ instrumentation tests | no device; no `connectedDebugAndroidTest` task exists |
| Live Spotify / Yandex / SoundCloud / YouTube traffic | the live probe is opt-in and was skipped; no credentials available |
| The desktop→Android library import against a real desktop DB | the desktop app must not be run against the user's real profile |
| Compose compiler stability report | not generated (would require adding a compiler flag) |
| Real frame-time / jank / battery measurements | no device |

Nothing in this report claims a test, build or measurement that was not
observed.

---

## 10. Coverage Gaps

This section is the honest boundary of the audit. Everything above it is
either source-verified, bytecode-verified, executed, or measured; everything
below it is *not*.

### 10.1 No device, no emulator, no APK

**No Android device or emulator was available to any reviewer.** This is the
single largest limitation of the audit, and it is a *stated* constraint of the
brief (no APK builds) compounded by the absence of an AVD:
`android/review/EMULATOR_SETUP.json` records a host-feature change with
`"RestartNeeded": true` and no confirmed boot.

Consequences — every one of these is unverified at runtime:

- **The 59 instrumentation tests have never been executed.** They were
  *compiled* (`:app:compileDebugAndroidTestKotlin`, BUILD SUCCESSFUL). Not one
  has run. That covers **all 19 Room DAO and schema-migration tests** — the
  only guard on the v1→v2→v3 migration that runs against real user data
  (P2-53).
- The **Keystore** implementation (AES-GCM, AAD binding, the `AtomicFile`
  write/recovery path) has 4 device tests, none of which have run.
- The **HLS VOD verifier** and the **Media3 crossfade handover** — 2 device
  tests, none run.
- The **Compose UI** assertions (27 tests) — none run.
- No `connectedDebugAndroidTest` task exists anywhere in the repository, and
  no CI workflow covers Android at all.
- No audio was ever played: crossfade equal-power gain, the EQ headroom, the
  BassBoost/Virtualiser chains, the output-gain clipping path and the
  boundary handover gain step (P3-09) are code-verified only.
- No audio focus, noisy-becoming, headset-unplug, or notification interaction
  was exercised — the entire `PendingSelectionGate` / `interactionVersion`
  protocol (P2-11, P2-12, P2-13, and the XI-08 B P1) is **static analysis over
  Media3 1.11.1 bytecode**, not observed behaviour.
- No SAF grant was taken or revoked; no URI-grant exhaustion was observed.
- The `dataSync` foreground-service quota (P3-76) and the 20-notification
  storm (P2-29) were not observed.
- `read-only WAL` on API 26 (P2-25) remains a **hypothesis** that needs an
  API-26 emulator.
- No Compose recomposition counts, no `gfxinfo` frame stats, no
  `StrictMode` trace, no allocation profile. Every recomposition figure in
  this report is **derived from source cadences** (750 ms progress write, 5 s
  history checkpoint, 60 s report clock, 500 ms position poll), not measured.
- No memory profile on an Android runtime: the backup OOM (P2-16) was
  measured on the JVM with the project's own `org.json:json:20250517`, and the
  AOSP `org.json` has the same eager-DOM shape but was not measured.

### 10.2 What *was* executed, and what it does and does not prove

| Command | Result | What it proves |
|---|---|---|
| `android/verify.ps1 -Tasks @(':app:testDebugUnitTest','--rerun')` | **BUILD SUCCESSFUL**, exit 0 | The JVM suite is green on the current tree. 236 tests, 0 failures, 0 errors, 1 skipped. |
| Lint (`:app:lintDebug` → `lint-results-debug.xml`) | 0 errors, 15 warnings | `lint { abortOnError true }` is satisfied. The warning mix is `NewerVersionAvailable` x6, `GradleDependency` x5, `UseKtx` x2, `AndroidGradlePluginVersion` x1, `ExportedService` x1. |
| `verify.ps1 ... '--rerun-tasks'` | **BUILD FAILED** | A real build-tooling defect (lint's `FileNotFoundException` on a KSP-generated `LibraryDao_Impl.kt`) — see §9.3. |
| `pytest -m "not network"` (desktop) | 1459 passed, 1 skipped, 3 xfailed, exit 0 | The desktop reference app is green. |
| `android/review/VERIFY.ps1` | **exit 1** | The prior round's review snapshot does not match the tree (27 of 187 files changed; 7 source files absent from the manifest) — P2-38. |
| `:app:compileDebugAndroidTestKotlin` | BUILD SUCCESSFUL | The instrumentation sources **compile**. Nothing more. |

**The suite proves less than its size suggests.** 236 JVM tests cover
**40 files**; the 35 uncovered production files hold 3 977 LOC — **54.6 % of
the production code has no JVM test at all**, and 5 of the 10 non-negotiable
contracts (the ones the project states it will not break) have **zero**
automated coverage of any kind (P3-90).

### 10.3 Coverage that was verified mechanically

- **File-level coverage:** 75/75 main Kotlin files are mapped to a review
  area, 0 unmapped (data 35, player 12, ui 21, downloads 5, root 2), plus the
  manifest and 4 res files. The accounting is in §3.3.
- **Library semantics:** Media3 1.11.1, WorkManager 2.12.0, material3 1.4.0,
  Room 2.8.5 and AOSP `org.json` were read from the *exact* pinned artifacts
  in the Gradle cache with `javap -c`, not from documentation or memory. Every
  Media3 claim in this report (the `isTrusted` predicate, the
  `CacheKeyFactory.DEFAULT` key, `onPlayerCommandRequest`'s single call site,
  `SimpleCache`'s blocking constructor, `Cache.commitFile` semantics,
  `MediaItem.localConfiguration` being null without a URI, the
  `playerInfo` field-read semantics) is bytecode-derived.
- **Runtime classpath:** `:app:dependencies --configuration debugRuntimeClasspath`
  was parsed, and the `minSdk` of all 139 cached AARs was extracted from their
  manifests. The `minSdk 26` claim is therefore *verified*, not asserted.
- **The desktop oracle** was read in full for every compared area:
  `core/database.py`, `core/api.py`, `core/proxy.py`, `core/resolver.py`,
  `core/session.py`, `core/listening.py`, `core/settings.py`,
  `core/downloader.py`, `core/download_transfer.py`,
  `services/soundcloud_service.py`, `services/lyrics_lookup.py`,
  `services/lyrics_service.py`, `services/lyrics_cache.py`,
  `services/music_matching.py`, `services/smart_playlists.py`,
  `services/artist_identity.py`, `services/listening_comparison.py`, and the
  JS UI (`player.js`, `queue.js`, `lyrics.js`, `settings.js`, `profile.js`,
  `hotkeys.js`).

### 10.4 Known limitations of the method

1. **The two reviewers per area were briefed, not blind.** They shared the
   same contract document and the same area map, so a *misreading of the
   contract* is not independent. Independence is in the reading and the
   conclusion, not in the frame.
2. **Area boundaries are porous.** Several defects are genuinely
   cross-module (§6) and were necessarily re-reported by more than one
   reviewer. Six findings were found by 2–4 independent agents and merged
   (§5.1); the merge count is recorded on each.
3. **Six subagents ran out of context** before their full reports arrived
   (AN-24 B, XI-01 B, XI-04 B, XI-06 A, XI-09 A/B, AN-20 B). Their areas are
   covered by the other role in each pair in every case, and each was
   cross-checked by the synthesiser against the source.
4. **No live provider probe was re-run.** `android/review/PROVIDER_PROBE.json`
   is the previous round's artefact (2026-10-18). The InnerTube
   `LOGIN_REQUIRED` result it records was **not** re-verified — and the
   porting status already documents it as a known platform limitation
   (`PORTING_STATUS.md:105-108`), so it is reported as a documented gap
   (P2-48) rather than as a new defect.
5. **Encoding mojibake in the console is a PowerShell artifact, not a file
   defect.** Every file under `android/` decodes as valid UTF-8 with no
   double-encoded sequences (byte-level check over 47 candidates).
6. **The `android/` tree is untracked in git**, so there is no diff, no
   history and no bisect to review — the audit is a *snapshot* review, and
   the snapshot anchor is broken (P2-38, P2-42).
7. **The prior-round artifacts are themselves partly stale** — `VALIDATION.md`
   says 217 tests (the tree has 236), 17 lint warnings (the tree has 15), 55
   instrumentation tests (the tree has 59), and one of its four "still open"
   items is mis-described in `PORTING_STATUS.md`. The audit verified 15 of
   the prior round's "Исправлено" claims against the current source; all 15
   hold, and one is a **partial** fix (the queue snapshot — P2-01).

### 10.5 What this audit did not look at

- The **desktop app's own correctness** beyond the areas the Android port
  depends on. The desktop was the *oracle*, not the subject — with one
  exception: P0-01, a destructive migration found in the desktop and
  independently reproduced.
- The **Windows proxy's** implementation beyond the behaviours the port
  compares against (SSRF checks, credential scoping, redirect handling).
- **Release engineering**: signing, R8/ProGuard rules, the `lintVitalRelease`
  task, `bundleRelease`, `zipalign` — no APK or AAB was assembled, so the
  dexing and shrinking stages were never exercised.
- **Accessibility on a real device.** The static analysis says the accent
  chips publish a selection state and the chart publishes a description, but
  the *number of focusable nodes* per row (e.g. whether the inner
  `Switch(checked, onCheckedChange = null)` is separately focusable alongside
  the row's `toggleable`) needs a device and a screen reader.
- **Localisation.** The UI is Russian-only; no i18n audit was performed.

---

## 11. Prioritized Remediation Plan

The full, dependency-ordered plan with acceptance criteria is in
**`docs/audits/REMEDIATION_PLAN.md`**. The summary:

| Wave | Goal | Contents | Gate |
|---|---|---|---|
| **W0** | Stop the bleeding | P0-01 (desktop destructive migration); put `android/` in git; regenerate the review manifest | The desktop library survives an upgrade |
| **W1** | Unbreak the play path | The `PendingSelectionGate` latch (P1, XI-08 B); the swallowed Play (P2-11); the discarded queue selection (P2-12); the transient-focus cancel (P2-13); the URI-less `MediaItem` (XI-01 A / XI-05 B); the download `callTimeout` (P1-04); the Yandex 401 credential loss (P1-03) | A track plays, and it keeps playing |
| **W2** | Make the data durable and honest | The DataStore corruption handler (P1-02); the queue snapshot codec (P2-01 + A-1); the backup OOM (P2-16); the export truncation (AN-07 A); the lyrics identity gate (P1-01); the report window bias (P2-43) | Nothing the user owns can be lost or silently mis-stated |
| **W3** | Close the network and provider gaps | The media headers (P2-51); the URL allow-list (P2-52); the resolution cascade (P2-48); the provider error classification (P2-62); the offline source-of-truth (A-4); the Yandex download TTL (P2-49) | Every provider path has a fallback and a truthful error |
| **W4** | Establish a gate | The 59 device tests actually run; the Android CI job; the four contract tests; the `verify.ps1` capture bug (P2-72); the local-properties race (AN-23 A) | A regression cannot reach the user |
| **W5** | Clean the surface | The remaining P2 UX/consistency findings; the P3 register; the documentation consistency (P2-38..P2-42) | — |

**Two rules for whoever executes this plan.**

1. **Do not fix the symptoms of a state-machine defect by patching the
   symptom.** P2-11, P2-12, P2-13 and the XI-08 B P1 are four presentations of
   one design error (a boolean latch where an intent token belongs). Fixing
   them separately will re-introduce them.
2. **Re-run the gate after every wave.** The JVM suite is green today
   (236 tests); that is the only automated signal the port has, and it does
   not cover 54.6 % of the production code or any of the device-only surfaces.

---

## 12. Final Assessment

**What the port is.** A competent, carefully-built Android port. The media3
architecture is idiomatic (a `MediaSessionService` owns the player, the UI
speaks only through a `MediaController`, streams are resolved lazily per item,
the offline read path is physically network-free, the download state machine
is generation-fenced against a durable store, the backup codec has a real
strict-JSON grammar, the Keystore store is properly abstracted, the system
backup excludes everything, and `minSdk 26` is verified against every
dependency). The prior round's 15 "Исправлено" claims all hold against the
current source. This is not a codebase in trouble.

**What is wrong with it.** The port has been *audited* rather than
*operated*. It has never been run on a device, it has never been run in CI,
it is not in version control, and its only automated signal — 236 JVM tests —
covers less than half the production code and none of the risky surfaces
(Room migrations, Keystore, SAF, HLS, Media3 handover). Every finding in this
report is a consequence of that: the defects cluster exactly where a device
would have caught them.

**The shape of the risk.** Six of the most serious findings are not in a
single function but in the *relationships between modules*: the queue
snapshot is the only durable session state and it is written into the
settings file every five seconds (X-02); "is my work still current?" is
answered five different ways in five layers (X-01); "offline" is defined nine
times (X-04); the effective source of a queue item is encoded twice, in the
`MediaItem` and in the download table, and the two can disagree (A-4); the
user's library has five writers and no delete (X-05); the cross-platform
format is a private schema with no version (X-06). Each of those has been
found independently by two to four reviewers, which is the strongest evidence
in this report: they are not artefacts of one reviewer's reading.

**The desktop P0 is the exception.** P0-01 is a one-shot startup migration in
the desktop app that deletes tracks and cascades away their listening history
and playlist entries. It is not a porting defect; it is a data-loss defect in
shipped code, it was found independently and reproduced, and it is the one
finding in this report that should be fixed *before* anything else — because
the users of the desktop app are the ones already running the broken build.

**The honest bottom line.** The Android port should not be shipped to users
in its current state, and the reason is not the defect count — it is that
**there is no gate**. The port's riskiest surfaces (a library migration, a
keystore, a file-picker contract, an HLS downloader, a media-session
lifecycle) are covered by tests that have never been run, in a tree that is not
in version control, with a build script that silently executes zero tasks
whenever its output is captured. Fixing the P1/P2 findings without first
standing up a gate means the next 50 findings arrive the same way. Fixing the
gate first means the rest becomes ordinary work.

**One recommendation, stated plainly.** W0 and W4 in the plan above —
`git add android/`, regenerate the review manifest, and make the 59 device
tests actually execute — are a few hours of work and they change the
economics of everything else. They are the cheapest actions in this report
and the most valuable.

---

---

<!-- Audit complete -->
