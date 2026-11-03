# Independent verification — inventory of the ORIGINAL audit findings

Built by the independent verification orchestrator, from:
- `docs/audits/FULL_PROJECT_AUDIT.md` (main report)
- `docs/audits/ANDROID_FINDINGS_REGISTER.md` (declared "authoritative" P2 register)
- `docs/audits/REMEDIATION_PLAN.md`
- `docs/audits/ANDROID_AUDIT_CONTEXT.md`, `docs/audits/ANDROID_AUDIT_AREAS.md`
- `android/PORTING_STATUS.md`, `android/AGENTS.md`

Snapshot anchor: git HEAD `76cab49107b43e8368974d31f9116f5964e821a4` (2026-10-11),
branch `fix/audit-v2`, `android/` **untracked** (0 tracked files), 220 porcelain entries.

---

## 0. THE TWO P2 NUMBERING NAMESPACES (read this first)

The original audit contains **two conflicting P2 ID namespaces inside the same
document set**:

| Namespace | Where | Range | Status |
|---|---|---|---|
| **REG** | `ANDROID_FINDINGS_REGISTER.md` | P2-01 … P2-75 | declared authoritative by `FULL_PROJECT_AUDIT.md:835` |
| **MAIN** | `FULL_PROJECT_AUDIT.md` §5.1 | P2-01 … P2-45 | condensed subset, **different IDs for the same findings** |

They agree on P2-01…P2-21 and diverge from P2-22 onward.

**Canonical rule used by this verification: `REG` is canonical.** A `MAIN` id that
is not present in `REG` is recorded as a separate original record with the
prefix `MAIN-P2-xx`; a `MAIN` id that aliases a `REG` id is recorded as an
*alias*, not as a new finding.

Alias table (MAIN → REG):

| MAIN | REG | MAIN | REG | MAIN | REG |
|---|---|---|---|---|---|
| P2-22 | P2-61 | P2-31 | P2-43 | P2-40 | — (MAIN-only) |
| P2-23 | P2-62 | P2-32 | P2-44 | P2-41 | — (MAIN-only) |
| P2-24 | P2-58 | P2-33 | P2-45 | P2-42 | — (MAIN-only) |
| P2-25 | P2-59 | P2-34 | — (MAIN-only) | P2-43 | — (MAIN-only) |
| P2-26 | P2-60 | P2-35 | — (MAIN-only) | P2-44 | — (MAIN-only) |
| P2-27 | P2-71 | P2-36 | P2-46 | P2-45 | — (MAIN-only) |
| P2-28 | — (MAIN-only) | P2-37 | — (MAIN-only) | P2-29 | P2-69 + P2-70 |
| P2-30 | P2-66 | P2-38 | — (MAIN-only) | | |

Canonical P2 records: **75 (REG) + 13 (MAIN-only) = 88**.

---

## 1. P0 / P1 (main report §4)

| ID | Title | Cited location |
|---|---|---|
| P0-01 | One-shot startup migration in the desktop app deletes tracks and cascades away listening history + playlist entries | `core/database.py:313-362` |
| P1-01 | Lyrics identity gate rejects any track whose title is "Artist - Song" | `android/.../data/LyricsCascade.kt:46-54,77-78` |
| P1-02 | A corrupt preferences file is never repaired — no setting can ever be changed again | `android/.../data/Preferences.kt:9,14`; `AudioSettingsStore.kt:10,18` |
| P1-03 | A single 401 from any Yandex API call permanently destroys the user's Yandex credential | `android/.../data/ProviderConnections.kt:187-191,203` |
| P1-04 | The shared HTTP client's 30 s `callTimeout` aborts every download whose body takes >30 s | `android/.../data/Sources.kt:22-23`; `downloads/DownloadStorage.kt:26-29`; `downloads/TrackDownloadWorker.kt:56,84-89` |

## 1b. Unnumbered / informal critical finding (must not be dropped)

| ID used by the audit | Title | Where named |
|---|---|---|
| **"XI-08 B P1"** | `PendingSelectionGate.playAllowed` is tripped by every player command but re-armed only from `MediaSession.Callback.onPlayerCommandRequest`; in Media3 1.11.1 that callback is never reached by `MediaController.play()`/`pause()`, so once tripped every subsequent Play is dropped with no error and no state change | `FULL_PROJECT_AUDIT.md:51-60`, `:1616-1622`, `:1687-1689`, `:2147-2149`, `:2268`, `:2276-2279`; `A-2`; remediation W1 |
| ARCH-1 | Resolve effective source at open time (architecture recommendation) | §8 A-4 |
| ARCH-3 | Queue snapshot format is unreachable from a JVM test | X-02 |
| F-AN-07-3 | "restoring a backup on a device that already has a same-named playlist creates a second, indistinguishable playlist" | §8 A-7 |
| F-XI03-4 | Download notification leaks the track title on the lock screen | §7.1 item 7 |
| F-XI-05-2 | `refreshQueueSources` trigger set misses `localUri` changes | §8 A-4 |

## 2. P2 — canonical REG list (75) with MAIN-only additions (13)

Canonical REG ids and titles are read directly from
`docs/audits/ANDROID_FINDINGS_REGISTER.md` (part 1 headings P2-01…P2-16 and
P2-73…P2-75; part 2 table P2-17…P2-72).

MAIN-only records (title from `FULL_PROJECT_AUDIT.md` §5.1):

| Canonical id | Title | Cited location |
|---|---|---|
| MAIN-P2-28 | An oversized primary LRCLIB response aborts the whole lookup; the four-provider cascade is never consulted | `data/Sources.kt:224-230`; `data/LyricsData.kt:10,21,31` |
| MAIN-P2-34 | The smart-playlist view re-runs a full-library aggregation and a full in-memory sort every 5 s while music plays | `data/DiscoveryController.kt:62-67,96-98`; `data/DiscoveryEngine.kt:13-19`; `data/SmartRules.kt:93-113` |
| MAIN-P2-35 | The `history` table has no retention policy; past 100 000 rows the JSON backup can no longer be exported | `data/BackupCodec.kt:30,34,168-171`; `data/Models.kt:37-39,78` |
| MAIN-P2-37 | Navigation is a single `String` with no back stack: Back from Settings/Profile always lands on Home | `ui/MusicApp.kt:48,55,83-89` |
| MAIN-P2-38 | The `nedotify://oauth/spotify` deep link cannot navigate | `MainActivity.kt:29-34,38`; `AndroidManifest.xml:22-27` |
| MAIN-P2-39 | `Design.kt` is not a token layer: 184 of 193 raw `dp` literals live outside it | `ui/Design.kt:38-50` + all `ui/*.kt` |
| MAIN-P2-40 | The root composable subscribes to the catalogue progress flow: a 500-track import produces 500 full-tree recompositions | `ui/MusicApp.kt:45,107`; `ui/MusicViewModel.kt:369-393,395-397` |
| MAIN-P2-41 | `positionMs` is read at the top of `PlayerScreen`, invalidating the whole player subtree every 500 ms | `ui/PlayerScreen.kt:33,39,49-93`; `ui/MiniPlayer.kt:20` |
| MAIN-P2-42 | A second PKCE start silently invalidates the pending login | `ui/ConnectionsControls.kt:28,34`; `data/ProviderConnections.kt:84-92`; `data/AuthPkce.kt:87` |
| MAIN-P2-43 | Local library search never matches the album column | `data/LibraryRepository.kt:61`; `data/Models.kt:104` |
| MAIN-P2-44 | `searchPage(limit, offset)` has no total order, so the paged local scan can duplicate and skip tracks | `data/Models.kt:104-105`; `data/LibraryRepository.kt:57-66` |
| MAIN-P2-45 | An unhandled failure in the listening-history write can kill the process | `player/PlaybackService.kt:38`; `NeDotifyApp.kt:17`; `data/Models.kt:138-145` |
| MAIN-P2-29 (alias of REG P2-69+P2-70) | The lyrics cascade is strictly serial and its intrinsic worst case (12.3 s) exceeds the 12 s UI deadline | `data/LyricsCascade.kt:95,103-109`; `ui/MusicViewModel.kt:442` |

## 2b. Findings added by the audit corpus WHILE this verification was running

> **The audited corpus is a moving target.** The register grew from
> 473 → 637 lines and the main report from 2 349 → 2 451 lines *during* this
> verification (register mtime 19:52 → **20:31**, main report → **20:32**,
> `REMEDIATION_PLAN.md` → **20:33**). `git ls-files docs/audits` → **0**, so
> nothing versions this. The inventory below is pinned to the corpus state
> of **2026-10-19 20:33** and records what arrived after the earlier
> snapshot.

**CORRECTION to an earlier draft of this file.** P2-76…P2-79 and
P3-111…P3-114 were first believed to exist *only* in `REMEDIATION_PLAN.md`.
They are in fact in the register's **"Addendum 2"**
(`ANDROID_FINDINGS_REGISTER.md:477-551`), and the main report's §5.2 grew
from 110 to **114** P3 rows. The "8 findings documented only in the plan"
claim is **withdrawn**.

### Addendum 2 (register `:475-551`) — now inside the register

| Id | Title |
|---|---|
| **P2-76** | No `buildTypes`, no R8, no `proguard-rules.pro`, no `signingConfig`; `assembleRelease` would produce an unsigned, unshrunk APK; `debug` and `release` share the `applicationId` |
| **P2-77** | 30 literal dependency coordinates, no catalog, no lockfile, no `verification-metadata.xml`; the gating lint task reaches out to Maven Central on every build, so "0 errors, 15 warnings" is a function of the calendar |
| **P2-78** | The KSP plugin is a Kotlin minor version ahead of the compiler it plugs into, and the Room compiler declares a two-year-old KSP API |
| **P2-79** | The whole toolchain lives in `C:\Temp`, and `local.properties` is the only channel that says where |
| **P3-111** | `haze` drags the JetBrains Compose Multiplatform coordinates and a newer `kotlin-stdlib`, and pins `minCompileSdk=37` |
| **P3-112** | Coil is declared with a network fetcher but no `ImageLoader` is configured, so cover art is fetched by a second, unconfigured `OkHttpClient` |
| **P3-113** | The build is not hermetic: an SDK metadata version mismatch is already reported, the build is Gradle-10-incompatible, and the configuration cache is off |
| **P3-114** | `kotlin.incremental=false` costs a measured 33.6 s full-module recompile for a one-line edit |

### Addendum 3 (register `:562-636`) — arrived after this verification's main pass

| Id | Title | Status in the register |
|---|---|---|
| **P1-05** | Local library search is a full table scan with no index and no FTS; it silently exceeds the aggregate's 6.5 s per-source budget and drops local results from the "Все" search | "CONFIRMED (the query plan, the absence of the index, and the timings were all reproduced against the exact exported schema and SQL)" |
| **P2-80** | The "Все" fan-out gives every provider the same 6.5 s budget, but SoundCloud's first call must scrape a `client_id` — the desktop budgets 8 s for exactly this reason | CONFIRMED for the provider set and the timeout values; the "first search loses SoundCloud" outcome is a **hypothesis** |
| **P2-81** | The catalogue matcher performs up to 1 000 sequential third-party searches per import; the desktop does it with bounded concurrency, a memo cache and a local-first step | CONFIRMED |
| **P3-115** | `LibraryRepository.search` has three mutually exclusive exit paths with different providers, different timeouts and different result shapes; the "all" path is not a superset of the per-source paths | — |
| **P3-116** | The local scan's `OFFSET` pagination is not snapshot-stable: a track added or removed during the scan is returned twice or not at all | CONFIRMED (reproduced against the exact schema and SQL) |

**Note on P1-05 vs REG P2-59.** The register itself says P1-05 is *"the same
root cause, now measured properly and **promoted to P1**"* — i.e. the corpus
acknowledges that its own P2-59 was the same defect under-measured. This
verification reached the **same conclusion independently** (REG P2-59 →
CONDITIONAL, P2 → P3, because the 20 000-row timings quoted in P2-59 were not
reproducible: re-measured 0.89 s worst case) — and the register's
Addendum-3 measurement (13.9 s at 50 000 rows, 63.5 s at 100 000) is
**consistent** with this verification's numbers at 20 000 rows and with the
conclusion that the crossover sits at ≈ 35 000–40 000 tracks. **The
promotion to P1 is therefore justified by the later, better measurement, and
the two documents agree on the mechanism.**

### Other unnamed findings carried by the remediation plan

| Plan id | Description | Referenced as |
|---|---|---|
| **R1.2** | `ui/MusicViewModel.kt` hand-builds a `MediaItem` with **no URI and no metadata** (`MediaItem.Builder().setMediaId(id).build()`) in `removeDownload` and `attachLocalFile`; Media3 1.11.1's `MediaSession.Callback` has no `onReplaceMediaItems`, so the item reaches the player as-is and `DefaultMediaSourceFactory.createMediaSource` hits `Preconditions.checkNotNull(mediaItem.localConfiguration)` → NPE; and `attachLocalFile` changes neither the offline flag nor the `offline_downloads` table, so the queue item is never rebuilt — the damage is permanent for that slot | `REMEDIATION_PLAN.md:148-170`; `FULL_PROJECT_AUDIT.md:2268`; marked 🔴 P1 in the plan but **absent from the P0/P1 register** |
| **R2.3** | "Export atomically" | `REMEDIATION_PLAN.md:291`; cited as "AN-07 A" (an area, not a finding id) |
| **R4.4** | `verify.ps1` reverts a concurrently modified `android/local.properties` | `REMEDIATION_PLAN.md:638`; cited as "AN-23 A" |
| **R1.1** | Restates the (refuted) `PendingSelectionGate` Media3 claim; its "done when" acceptance criterion is built on it | `REMEDIATION_PLAN.md:110-146` |

## 3. P3 — 114 rows, exactly P3-01 … P3-116 (see §2b for the numbering note)

`FULL_PROJECT_AUDIT.md:1473-1584`. 110 table rows, no duplicate ids, no gaps.
21 rows are marked `[MERGED]` with a pointer to a P2 row.

## 4. Cross-module findings (§6) — 6

| ID | Title |
|---|---|
| X-01 | Two playback states, three "is this still current?" mechanisms, four "generation" counters |
| X-02 | The queue snapshot is the app's only durable session state, and it is written into the settings file |
| X-03 | The offline download store and the streaming store are two mechanisms for the same concept |
| X-04 | The app has no single definition of "offline" |
| X-05 | The user's library has no single writer, and three of its writers can silently change its meaning |
| X-06 | The desktop's storage schema is the de-facto wire format, and it has no version |

## 5. Architecture improvements (§8) — 10 (recommendations, not defects)

A-1 … A-10 (queue-snapshot codec · intent token · now-playing source of truth ·
resolve-at-open-time · substitutable dependency graph · offline/preferences
authority · one identity policy · typed download state machine · "no silent
state loss" invariant · retire the SHA-manifest mechanism).

## 6. Original counts vs. re-counted counts

**CORPUS ANCHOR: 2026-10-19 20:33** (register 637 lines, main report 2 451
lines, plan 52 793 bytes). The corpus's own §1 table at that anchor reads
**P0 1 / P1 5 / P2 81 / P3 116**.

| Claim | Original claim | Re-count at the 20:33 anchor |
|---|---|---|
| P0 | 1 | 1 |
| P1 | 4 (main report §1 §4) → **5** (main report §1 at 20:32) → the plan still says 4 | **6 P1-level items**: P1-01…P1-05 plus the unnamed *"XI-08 B P1"* (which the main report's §1 at 20:32 evidently counted as the 5th) — **plus** the plan's R1.2 (the URI-less `MediaItem`), also marked 🔴 P1 and present in no register. **The set contains 6–7 P1-level items depending on how the unnamed one is counted** |
| P2 | 75 (register part 1) → **79** (plan scope line) → **81** (main report §1 at 20:32) | **91 distinct P2-level records**: 79 in the register + 12 that exist only in the main report's §5.1 (P2-28, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44, 45) + MAIN-P2-29 (a lossy alias of REG P2-69+P2-70). Minus 2 P2↔P3 duplicate pairs (MAIN-P2-42≡P3-66, MAIN-P2-28≡P3-79) ⇒ **89 distinct P2-level defects** |
| P3 | 110 (early draft) → **114** (register Addendum 2) → **116** (main report §1 at 20:32) | **116** rows, P3-01…P3-116, no gaps, no duplicate ids. Minus 2 rows that are pure merged pointers (P3-25→MAIN-P2-43, P3-64→P3-35) ⇒ **114 distinct P3-level defects** |
| Cross-module | 6 | 6 (X-01…X-06) |
| Architecture | 10 | 10 (A-1…A-10) — explicitly *not* defects |
| Instrumentation tests | "59" (§1, §10.1) vs "55+ (§9.4) vs "55" (P3-91, P2-55) | **59 `@Test` methods in 15 files** (arbiter re-counted per file) |
| Lint warnings | "15" (§1, §10.2) vs "17" (§9.1) | **15**, breakdown x6/x5/x2/x1/x1 (arbiter re-measured) |
| JVM test files | "42" (§1, §9.1) vs "40" (§2.2, §3.2) | **42** |
| Reviewers | "70 independent review tasks (54 primary + 16 integration)" (§3.1) vs "Six subagents ran out of context" (§10.4) | 70 planned; the six named entries cover **7** reviewer slots; **0** of the 70 reviewer reports are retained in the repository |
| **Total original records** | 1 + 4 + 75 + 110 + 6 + 10 = **206** (early reading) | **229** at the 20:33 anchor (1 + 5 + 91 + 116 + 6 + 10), of which **89 + 114 = 203 are distinct defects** and 10 are architecture recommendations |
