# REMEDIATION TRACKER — autonomous multi-agent repair

Working register for the repair of the confirmed defects from
`docs/audits/independent_verification/` (the independent verification is the
authority; the original `FULL_PROJECT_AUDIT.md` / `ANDROID_FINDINGS_REGISTER.md`
are *not*).

**Ground rules (from the task brief)**

* One area = exactly one `FIX → 2 independent reviews → VERIFY & REPAIR` pass.
  Reviews are **not** repeated for the same area.
* Reviewers 2 and 3 are **read-only**. Only agent 1 and agent 4 edit.
* APK/`assemble*`/`bundle*`/`package*` tasks are **forbidden** (`android/AGENTS.md`).
  Allowed: `compileDebugKotlin`, `testDebugUnitTest`, `lintDebug`,
  `compileDebugAndroidTestKotlin`.
* `~/.nedotify/` is the user's library — never opened, never cleared.
* Windows-side changes: synthetic databases only.

**Test entry points**

| What | Command |
|---|---|
| Android JVM unit tests | `powershell -File C:\Temp\nedotify-B3544D227D\run-tests.ps1` |
| Android lint | `powershell -File C:\Temp\nedotify-B3544D227D\run-tests.ps1 -Tasks ':app:lintDebug'` |
| Android compile | `powershell -File C:\Temp\nedotify-B3544D227D\run-tests.ps1 -Tasks ':app:compileDebugKotlin'` |
| Desktop pytest | `& ".venv_win\Scripts\python.exe" -m pytest tests -q` (repo root) |

The Android tree must be built through the ASCII junction
`C:\Temp\nedotify-B3544D227D\project` — the Gradle test worker cannot start
from the Cyrillic repository path (`ClassNotFoundException:
worker.org.gradle.process.internal.worker.GradleWorkerMain`). `run-tests.ps1`
already sets `GRADLE_USER_HOME` to an ASCII path for the same reason.

Baseline before any repair: **236 tests, 0 failures, 0 errors, 1 skipped**.

---

## Area status

| # | Area | Primary files | Findings in scope | Status |
|---|---|---|---|---|
| A1 | Playback core (MediaSession / ExoPlayer / gate / focus / queue) | `android/app/src/main/java/ru/nedotify/app/player/**`, `ui/MusicViewModel.kt`, `ui/PlaybackPreparation.kt`, `ui/PlaybackErrors.kt` | REG P2-11, REG P2-12, REG P2-13, REG P2-65, REG P2-27, REG P2-28, REG P2-34, REG P2-35, UNNUMBERED-R1-2-P1, P3-05, P3-09, P3-10, P3-12, P3-103…P3-110 | **closed — verified & repaired** (arbiter pass 2026-10-20; see the A1 log at the end of this file) |
| A2 | Network client, media-URL policy, streaming & downloads | `data/Sources.kt`, `data/ProviderHttp.kt`, `data/SourceDeadline.kt`, `data/StreamCache.kt`, `data/OnlineSource.kt`, `data/SignedUrlExpiry.kt`, `downloads/**` | P1-04, REG P2-47:P2-52, REG P2-29, REG P2-30, REG P2-09, P3-22, P3-23, P3-24, P3-77, P3-112 | **closed with residuals** (arbiter & repair pass 2026-10-20; see the A2 log at the end of this file) |
| A3 | DataStore / preferences / settings durability | `data/Preferences.kt`, `data/AudioSettingsStore.kt`, `data/ProfileSettings.kt`, `data/SmartRules.kt` | P1-02, REG P2-01, REG P2-46, P3-03, P3-34, P3-59, P3-60, P3-61, P3-62, P3-67, P3-68, P3-84 | **fixed — pending the two independent reviews** (fix engineer pass 2026-10-20; see the A3 log at the end of this file) |
| A4 | Library, Room, backup codec, desktop import/export | `data/Models.kt`, `data/LibraryRepository.kt`, `data/BackupCodec.kt`, `data/BackupMerge.kt`, `data/DesktopLibraryImport.kt`, `data/DesktopLibraryConverter.kt`, `data/LibraryBackupStorage.kt`, `data/LocalImportBatch.kt` | REG P2-14…P2-19, REG P2-21…P2-26, REG P2-31, REG P2-44, REG P2-45, REG P2-53, REG P2-54, P3-15, P3-16, P3-71…P3-74, P3-96…P3-102 | **partial — interrupted** (the fix engineer was cut off mid-edit; see "Area A4 — interrupted pass" below) |
| A5 | Providers, OAuth / auth, secure credential store | `data/ProviderConnections.kt`, `data/SecureProviderStore.kt`, `data/AuthPkce.kt`, `ui/ConnectionsControls.kt` | P1-03, REG P2-03…P2-06, P3-17…P3-21, P3-66…P3-70 | **fixed — pending the two independent reviews** (fix engineer pass 2026-10-20; see the A5 log at the end of this file) |
| A6 | Lyrics, search, discovery, catalogue import | `data/LyricsCascade.kt`, `data/LyricsData.kt`, `data/LyricsDiskCache.kt`, `data/DiscoveryEngine.kt`, `data/DiscoveryController.kt`, `data/CatalogMatcher.kt`, `data/SearchAggregate.kt`, `ui/CatalogBrowser.kt`, `ui/DiscoveryControls.kt` | P1-01, REG P2-08, REG P2-22, REG P2-23, REG P2-24, REG P2-27, REG P2-28, REG P2-58…P2-63, REG P2-66…P2-71, REG P2-73, REG P2-74, MAIN-P2-28, P3-26…P3-33, P3-44, P3-79, P3-80, P3-81 | pending |
| A7 | Compose UI, navigation, theming, accessibility, library UI | `ui/**` not owned above, `MainActivity.kt`, `NeDotifyApp.kt` | MAIN-P2-34, MAIN-P2-36…MAIN-P2-45, REG P2-32, P2-33, P2-36, P2-37, P2-40…P2-42, P3-01, P3-02, P3-07, P3-08, P3-11, P3-13, P3-14, P3-19, P3-20, P3-25, P3-37…P3-55, P3-57, P3-58, P3-63, P3-70, P3-75, P3-76 | pending |
| A8 | Build system, test infrastructure, review manifests, docs | ndroid/build.gradle, ndroid/settings.gradle, ndroid/gradle.properties, ndroid/gradle/**, ndroid/verify.ps1, ndroid/tools/**, ndroid/review/**, ndroid/README.md, ndroid/PORTING_STATUS.md, ndroid/AGENTS.md, ndroid/lint.xml, .github/workflows/android-source.yml, docs/REMEDIATION_TRACKER.md, 	ests/test_android_source_gates.py | REG P2-38, REG P2-39, REG P2-40, REG P2-41, REG P2-42, REG P2-54, REG P2-55, REG P2-72, REG P2-76, REG P2-77, REG P2-79, P3-83, P3-85, P3-88, P3-89, P3-92 | **closed with residuals** (arbiter & repair pass 2026-10-20; see the A8 log at the end of this file) |
| A9 | Windows desktop destructive dup-cleanup migration (data safety) | `core/database.py`, `tests/**` | P0-01 | **fixed — pending the two independent reviews** (fix engineer pass 2026-10-20; see the A9 log at the end of this file) |

---

## Registry of confirmed defects (deduplicated by root cause)

Root causes come from `docs/audits/independent_verification/ROOT_CAUSE_MAP.md`.
Each entry is worked exactly once, in the area named in the “Area” column.

| Key | Root cause | Area | Representative ids |
|---|---|---|---|
| RC-1 | Gate refusal is silent; gate closed by non-user events | A1 | REG P2-11 |
| RC-16 | System/focus events reported as user interaction | A1 | REG P2-13, REG P2-12, P3-10 |
| RC-14 | “Now playing” and playback errors have no single source of truth | A1 | P3-103…P3-110, REG P2-10 (residual only) |
| — | Hand-built `MediaItem` without a URI | A1 | UNNUMBERED-R1-2-P1 |
| — | Transport commands cancel the pending preparation | A1 | REG P2-65 |
| RC-5 | No shared identity / budget / completeness contract for stream+download | A2 | P1-04, REG P2-47…P2-52, P2-29, P2-30, P3-24, P3-77 |
| RC-7 | Provider error classification thrown away | A2/A5/A6 | P1-03, REG P2-62, P2-58, P2-17 |
| RC-11 | Settings file is a whole-file blob with a silent no-op failure | A3 | P1-02, REG P2-01, REG P2-46, P3-03, P3-60 |
| RC-4 | Durable session state lives in the settings file; compared value always changes | A3/A1 | REG P2-01, P3-34, X-02 |
| RC-3 | Library has five writers, no delete | A4 | REG P2-31, X-05, P3-14, P3-63 |
| RC-9 | Cross-platform format is a private, unversioned schema with unbounded memory | A4 | REG P2-14…P2-16, P2-19, P3-96…P3-102 |
| RC-10 | Desktop import treats the desktop schema as optional input | A4 | REG P2-17…P2-21, P2-25, P2-26, P3-15, P3-16 |
| RC-6 | Lyrics identity gate stricter than the desktop oracle | A6 | P1-01, REG P2-66…P2-71, MAIN-P2-28, P3-79 |
| RC-8 | Long-running network work modelled as UI-scoped work | A6 | REG P2-08, P2-60, P2-61, P2-74, MAIN-P2-40 |
| RC-13 | High-frequency state read at the top of the composition | A7 | MAIN-P2-41, REG P2-34, P2-35, P3-46…P3-50 |
| RC-12 | There is no gate (tests never run, tree untracked, manifest stale) | A8 | REG P2-53…P2-57, P2-72, P3-82…P3-95 |
| RC-2 | Destructive `DELETE` where a merge was required (desktop) | A9 | P0-01 |

## Refuted — must NOT be "fixed"

* The `PendingSelectionGate` “play button is dead” headline (FP-1). The gate is
  **not** stuck; `MediaController.play()/pause()` reach
  `onPlayerCommandRequest` as `COMMAND_PLAY_PAUSE`. Only the **silent veto**
  survives → A1/R2.1′.
* REG P2-10 (in-place `MediaItem` replacement splitting a listen) — FP-18.
  Only the stale `explicitQueueBoundary` flag survives → A1/P3-05.
* P3-87 (REVIEW_RESOLUTION.md contradiction) — FP-15.
* P3-99 (local search covers only device files) — FP-16.
* P0-01's *stated cause* (wrong identity key) and the FK-cascade story — FP-2,
  FP-3. Fix the **operation**, not the key.
* “A 403 on the first byte” (REG P2-51) — not reproduced; fix headers anyway.
* “Lyrics are never found for ‘Artist - Song’ tracks” — overstated; the rule
  is absent but the trigger is narrow (non-Latin scripts, sentinel artist).
* “The catalogue browser silently ignores every input during an import” —
  overstated; the UI disables the controls.
* “The streaming cache's bytes are never read again” — overstated; the key is
  unstable, not the cache inert.
* “The user can never download a normal-sized Яндекс track” — not established.
* “Every transport/queue command cancels the pending preparation” — overstated;
  `shuffle()`/`repeat()` already behave correctly (reference for the fix).
* P3-87/P3-99/P2-10 above; REG P2-46's “12 cold reads” (real: 10 cold + 3 + 1).

## Conditionals — fix only if the condition is reachable and the fix is sound

REG P2-05 (mutex held across HTTP only in two places), REG P2-09 (orphaned
resolution coroutine), REG P2-11 (narrow interleaving), REG P2-13 (P3),
REG P2-25 (read-only WAL on API 26 — no device), REG P2-46 (P3), REG P2-49,
REG P2-51, REG P2-59 (P3, crossover at 35–40 k rows), REG P2-59/P1-05
(independent measurement agrees with the P1 promotion — fix the budget
coupling and add the `addedAt` index), P3-11, P3-84, P3-107, P3-110, P3-50.

---

## Area A1 — Playback core (fix engineer log, 2026-10-19)

Status: **fixed — pending the two independent reviews.** Baseline
236 tests / 0 failures / 0 errors / 1 skipped → now **263 / 0 / 0 / 1**;
`:app:lintDebug` is green. No device/emulator was available: everything that
needs a real decoder, an audio session or a Media3 controller is *not* runtime
verified (the list is in the fix report).

### The one design change that carries items 1, 2, 3 and 5

The old player had a single `onUserInteraction` callback that meant three
different things (a user action, a system interruption, and "cancel the queue
the user just asked for"). It is now split into three, and the *gate* no longer
owns the selection:

| Callback / field | Meaning | Effect |
|---|---|---|
| `DualDeckPlayer.onUserInteraction` | a real user action | advances `interactionVersion` (the restore / autoplay / offline-refresh guard) |
| `DualDeckPlayer.onPlaybackInterrupted` | the environment changed, or another controller paused | closes the gate's **play latch** only; the pending selection survives |
| `DualDeckPlayer.onPlaybackRefused` | the gate refused a play | the service sends a `SessionError`, the controller's `onError` shows the reason |
| `PlaybackService.selectionVersion` | a **new** queue selection | the only thing that supersedes a pending selection |

* `PendingSelectionGate` now has `interruptPlay()` (closes the latch, keeps the
  set future) instead of `interruptPending()` (cancelled the set future).
  The class KDoc and `PendingSelectionGateTest` were rewritten in the same
  change — the pinned "an older play must not undo another controller's
  pause/noisy" invariant is kept, but it no longer costs the queue.
* The latch is closed only while a selection is unresolved: without one there
  is no play queued behind it, so an ordinary pause-and-play still works.

### Per finding

| Id | Outcome | Where |
|---|---|---|
| REG P2-11 (silent veto) | fixed | `player/PlaybackRefusal.kt`, `player/DualDeckPlayer.kt:287`, `player/PlaybackService.kt:81` |
| REG P2-12 (an interruption destroys the queue) | fixed | `player/PendingSelectionGate.kt`, `player/DualDeckPlayer.kt:298`, `player/PlaybackService.kt:317` |
| REG P2-13 (focus loss reported as a user action) | fixed | `player/DualDeckPlayer.kt:318`, `:325` |
| REG P2-65 (transport commands cancel the preparation) | fixed | `player/PlaybackService.kt:46`, `:103`, `:311` |
| UNNUMBERED-R1-2-P1 (hand-built `MediaItem`) | fixed | `player/TrackMediaItems.kt`, `ui/MusicViewModel.kt:235`, `:258` |
| REG P2-01 / P3-34 (untyped queue snapshot) | fixed | `data/QueueSnapshotCodec.kt`, `data/Preferences.kt`, `player/PlaybackService.kt:351` |
| P3-05 (stale `explicitQueueBoundary`) | fixed | `player/DualDeckPlayer.kt:348`, `player/PlaybackService.kt:124` |
| P3-09 (the gain step on the `STATE_ENDED` branch) | fixed | `player/CrossfadePolicy.kt`, `player/DualDeckPlayer.kt:169`, `:257` |
| P3-10 (`configure()` fires the user-interaction side effects) | fixed as a side effect of the split | `player/DualDeckPlayer.kt:325` (`pauseForReason` no longer calls `onUserInteraction`) |
| P3-12 (no cap on the listening tick) | fixed | `player/ListeningClock.kt` |
| P3-103/104 (no error dimension in `NowPlaying`) | fixed | `ui/MusicViewModel.kt:30`, `:160` |
| P3-105 (a null message clears the channel) | fixed | `ui/PlaybackErrors.kt`, `ui/MusicViewModel.kt:118` |
| P3-106 (`close()` keeps the crossfade hint) | fixed | `player/AudioRuntime.kt:52` |
| P3-107 (a stale controller snapshot) | **no change needed** — Media3-internal; the proposed fix needs `playbackState` in the mirror, which the mirror does not carry | `ui/MusicViewModel.kt:30` |
| P3-108 (`onDisconnected` nowhere) | fixed | `ui/MusicViewModel.kt:120` |
| P3-109 (a self-healing error is shown) | fixed | `player/PlaybackService.kt:149` |
| P3-110 (the in-memory resolution key omits the format) | fixed | `data/LibraryRepository.kt:80` (the disk key was never the problem) |
| REG P2-27 (the standby rebuilds the whole queue per boundary) | fixed | `player/DualDeckPlayer.kt:186`, `:219`, `:235`, `:268` |
| REG P2-28 (the EQ headroom reads a UI snapshot) | fixed | `player/AudioRuntime.kt:57` (`eqControlled`), `player/DualDeckPlayer.kt:275` |
| REG P2-34 (the per-emission `Pair` allocations) | fixed | `ui/MusicViewModel.kt:25`, `:166`, `ui/NowPlayingQueue.kt` |
| REG P2-35 (the queue row shows index/title/overflow) | **data side fixed**, the rendering side is in `ui/PlayerScreen.kt` (area A7) — the row now carries artist and artwork | `ui/MusicViewModel.kt:25` |
| P3-46 (an O(N) `firstOrNull` at 2 Hz) | **out of area** — `ui/PlayerScreen.kt:39` (A7): hoist `tracks` into a map exactly as `ui/MusicApp.kt:37` already does | — |

### Not verified here

No device, no emulator and no APK build (forbidden). The Media3 controller
round trip, the audio focus callbacks, the crossfade handover and the Media3
command queue are therefore reasoned about from the pinned 1.11.1 bytecode
(`javap` on the local Gradle cache) and covered by JVM unit tests only for the
pure decision logic.

---

## Area A1 — Playback core (arbiter & repair log, 2026-10-20)

Status: **closed.** The two independent reviews (reviewer 2: adversarial,
reviewer 3: independent verification) were adjudicated remark by remark
against the pinned Media3 1.11.1 bytecode; every remark that survived was
repaired, and every decision that now carries the area is a **pure function
with a test that fails when the production code is reverted**.

Baseline before this pass: **263 / 0 / 0 / 1** → now **298 / 0 / 0 / 1**;
`:app:lintDebug` green; `:app:compileDebugAndroidTestKotlin` green.

### The gate redesign (B1 + B2 + R1 — one root cause)

**The defect.** The play latch was tied to the lifetime of the *pending set
future*, not to the *queued play*. Two consequences, both confirmed against the
pinned bytecode:

* `MediaSessionImpl.handleMediaControllerPlayRequestInternal` (offsets 103-110)
  calls `Util.handlePlayButtonAction(playerWrapper)` **directly** →
  `Player.play()` → `PlayerWrapper.setPlayWhenReady(true)` →
  `DualDeckPlayer.handleSetPlayWhenReady(true)`. The media button and the
  notification's play button therefore **never** reach
  `MediaSession.Callback.onPlayerCommandRequest`
  (`MediaSessionImpl$MediaPlayPauseKeyHandler.lambda$setPendingPlayPauseTask$0`
  → `access$1000` → the same method; the notification reaches it through
  `MediaSessionService.onStartCommand` → `MediaSessionImpl.onMediaButtonEvent`).
  The old latch was re-armed in exactly one place — `onPlayerCommandRequest` —
  so the notification's play button was **permanently** dead after one
  interruption, and the refusal was invisible (the notification has no
  controller).
* `ConnectedControllersManager.addToCommandQueue` **defers** the command: the
  play is executed by `flushCommandQueue` only after the set task's future
  completed. `PendingSelectionGate.complete(future)` nulls the pending future
  in that very moment, so an interruption in the window between "the set
  resolved" and "the queued play runs" was swallowed (`pending == null`) and
  the stale play resumed the playback the environment had stopped.

**The new contract** (`player/PendingSelectionGate.kt`):

| State | Meaning |
|---|---|
| `pending` | the queue selection that is being resolved. An interruption **never** cancels it (REG P2-12); only a newer selection supersedes it. |
| `epoch` | the interruption counter. Every interruption advances it. |
| `commands` | one entry per **enqueued** play/pause command, holding the epoch of the moment it was enqueued. A command whose epoch is older than `epoch` is **stale**. |
| `freshPlays` | plays that arrived through the media button / the notification (`MediaSession.Callback.onMediaButtonEvent`). They never went through the enqueue callback, so they are never stale. |

* `expectQueuedPlay()` — from `onPlayerCommandRequest(COMMAND_PLAY_PAUSE)`:
  the command is remembered with the current epoch.
* `expectFreshPlay()` — from `onMediaButtonEvent` with a play/pause key code
  (`player/MediaButtonPlay.kt`): a fresh request.
* `interruptPlay()` — advances `epoch`. Every command enqueued before it
  becomes stale. The pending selection is untouched.
* `evaluatePlay(playWhenReady)` — called once per **executed** play. A fresh
  play is always allowed. Otherwise the oldest command is consumed: it is
  refused iff it is stale **and** it is a play. A pause is never refused.
* `canStartPlayback` — false while a stale command is outstanding: the queue is
  then installed **paused** (`installPaused()`).

**Why both invariants hold.**

* *A stale play must not resume playback.* The command is enqueued at
  `onPlayerCommandRequest` (T0) and executed later (T2). An interruption
  between T0 and T2 advances `epoch`, so the command's epoch is older than the
  current one and the play is refused — **independently of the pending set
  future**, which is what closed the B2 window. The refusal is observable:
  `invalidateState()` + a failed future + `onPlaybackRefused` → a `SessionError`
  addressed to the offending controller (REG P2-11).
* *A fresh play must not be refused.* A play that never went through the
  enqueue callback is counted in `freshPlays` and is allowed; it does **not**
  consume the queued command, so the stale queued play is still refused when it
  runs. A play that was enqueued *after* the interruption carries the current
  epoch and is allowed. And the refusal is **not sticky**: the gate refuses
  only what it can prove is stale, so the very next play is judged on its own
  merits — the notification's play button is never permanently dead.
* *The queue the user selected survives* — the interruption only advances the
  epoch; the pending set future is never cancelled, and the resolved items are
  installed paused.

**Why FP-1 stays refuted.** FP-1 refuted the *audit's* claim that the app's own
`MediaController.play()`/`pause()` never reach `onPlayerCommandRequest`. That
is still true (`MediaControllerImplBase.play()` →
`dispatchRemoteSessionTaskWithPlayerCommand` → `MediaSessionStub.sendPlayerCommandRequest`
→ `MediaSessionImpl.onPlayerCommandRequestOnHandler`), and the repair keeps it
true: the app's own transport still re-arms through the enqueue callback, and
the second press after an interruption always works. What the reviewers have
now established is a **different, newly discovered fact** — the
media-button/notification path genuinely bypasses `onPlayerCommandRequest` in
1.11.1. Correcting the latch for *that* path is a different fix from the
refuted intent-token project: `RECOMMENDED_FIX_ORDER` §2.1's "do not replace
the boolean with an intent token yet" was conditioned on "the re-arm path
works", and it does **not** work on that path. The replacement is therefore
**not** an intent token but a per-command ledger whose entries carry the
interruption epoch, plus an explicit fresh-play marker taken from
`onMediaButtonEvent` — the one hook Media3 offers for the media-button path.

### Remark-by-remark adjudication

| Remark | Verdict | Notes |
|---|---|---|
| B1 (the latch is never re-armed on the media-button path) | **confirmed & fixed** | the gate now has a *fresh play* marker fed by `onMediaButtonEvent`; see above |
| B2 (`interruptPlay()`'s `pending == null` early-out) | **confirmed & fixed** | the latch no longer depends on the pending future at all |
| B3 (`onDisconnected` leaves the app unable to play) | **confirmed & fixed** | `ui/MediaControllerConnector.kt`: a disconnect builds a **new** controller (the future is one-shot) |
| B4 (the recovery job has no exception guard) | **confirmed & fixed** | `catch (CancellationException) { throw } catch (Exception) { reportPlaybackError(...) }`, plus a `destroyed` guard before the player is touched |
| N1 (`NowPlaying.error` is written, never read) | **confirmed & fixed (partly), rest → A7** | the error now also reaches the message channel (`playerErrorMessage`); the *player screen* must render `now.error` — that is `ui/PlayerScreen.kt` (A7) |
| N2 (the snackbar host only exists when the full player is closed) | **confirmed → A7** | `ui/MusicApp.kt:61` — out of area, reported to the coordinator |
| N3 (the EQ headroom does a binder IPC per crossfade tick) | **confirmed & fixed** | `player/AudioRuntime.kt`: `CachedControlState` caches `hasControl()`; the cache is refreshed by the control-status listener |
| N4 (P3-05 is narrowed, not closed) | **confirmed & fixed** | see D1 |
| N5 (the legacy `queue_v1` key is never cleared) | **confirmed & fixed** | `data/Preferences.kt`: the first write under `queue_v2` removes `queue_v1`; the legacy key is still **read** (`savedQueue()`) |
| N6 (a raw `error.message` is forwarded to the controller) | **confirmed & fixed** | `player/PlaybackRefusal.kt` `failureText()`: only the app's own `SourceFailure` text is forwarded |
| N7 (`PlaybackRefusedException` is public) | **confirmed & fixed** | it is `internal` now |
| N8 (a second URI-less `MediaItem.Builder()` in the view model) | **confirmed & fixed** | `ui/MusicViewModel.startPrepared` uses the shared factory `trackMediaItem()` |
| N9 (REG P2-35 is data-side only) | **confirmed → A7** | the data side carries artist + artwork; `ui/PlayerScreen.kt:79-83` still renders index + title (A7) |
| N10 (P3-46 is not fixed) | **confirmed → A7** | `ui/PlayerScreen.kt:39` — an O(N) `firstOrNull` at 2 Hz (A7) |
| R1 (the latch is weaker than before) | **confirmed & fixed** | the latch is tied to the queued play, not to the set future |
| R2 (a second URI-less builder) | **confirmed & fixed** | same as N8 |
| R3 (`NowPlaying.error` never read) | **confirmed** | same as N1 |
| R4 (the write rate is still ~12/min) | **confirmed & fixed** | `player/QueueCheckpoint.kt`: the position is written on a 30 s cadence (2/min), the queue identity at once |
| R5 (the factory checks the URI, not the download state) | **confirmed & fixed** | `player/TrackMediaItems.kt`: only a `complete` download becomes the offline item |
| R6 (the refusal is broadcast to every controller) | **confirmed & fixed** | the refusal is addressed to the controller that asked for the play; the broadcast is the fallback |
| R7 (`configure()` can close the latch) | **confirmed & fixed** | `finishIfEnded()` no longer counts as an interruption: the queue ending is not an environment interruption |
| D1 (P3-05: the boundary survives a set that produces no transition) | **confirmed & fixed** | `player/QueueBoundary.kt`: only a `PLAYLIST_CHANGED` transition can be the explicit boundary |
| test-quality criticism | **confirmed & fixed** | the decisions were extracted into pure functions (`playbackRefusal`, `installPaused`, `failureText`, `isExplicitQueueBoundary`, `QueueCheckpoint`, `CachedControlState`, `ControllerConnector`, `playerErrorMessage`, `savedQueue`) and each is pinned by a test that fails on a revert. The tautologies (a string constant, a literal) and the order-dependent `AudioRuntimeTest` were removed. |

### Per finding (after this pass)

| Id | Outcome | Where |
|---|---|---|
| REG P2-11 (silent veto) | fixed — observable, addressed to the offending controller | `player/PlaybackRefusal.kt`, `player/DualDeckPlayer.kt:295`, `player/PlaybackService.kt:85` |
| REG P2-12 (an interruption destroys the queue) | fixed — the queue survives, installed paused | `player/PendingSelectionGate.kt`, `player/DualDeckPlayer.kt:360` |
| REG P2-13 (focus loss reported as a user action) | fixed | `player/DualDeckPlayer.kt:327`, `:333` |
| REG P2-65 (transport commands cancel the preparation) | fixed | `player/PlaybackService.kt:134`, `:343` |
| UNNUMBERED-R1-2-P1 (hand-built `MediaItem`) | fixed | `player/TrackMediaItems.kt`, `ui/MusicViewModel.kt:225`, `:277` |
| REG P2-01 / P3-34 (untyped queue snapshot) | fixed — plus the write rate (R4) and the legacy key (N5) | `data/QueueSnapshotCodec.kt`, `data/Preferences.kt`, `player/QueueCheckpoint.kt` |
| P3-05 (stale `explicitQueueBoundary`) | fixed | `player/QueueBoundary.kt`, `player/PlaybackService.kt:151` |
| P3-09 (the gain step on the `STATE_ENDED` branch) | fixed | `player/CrossfadePolicy.kt`, `player/DualDeckPlayer.kt:169`, `:257` |
| P3-10 (`configure()` fires the user-interaction side effects) | fixed | `player/DualDeckPlayer.kt:333` |
| P3-12 (no cap on the listening tick) | fixed | `player/ListeningClock.kt` |
| P3-103/104 (no error dimension in `NowPlaying`) | fixed (the rendering is A7) | `ui/MusicViewModel.kt:30`, `:177` |
| P3-105 (a null message clears the channel) | fixed | `ui/PlaybackErrors.kt`, `ui/MusicViewModel.kt:121` |
| P3-106 (`close()` keeps the crossfade hint) | fixed | `player/AudioRuntime.kt:84` |
| P3-107 (a stale controller snapshot) | no change needed — Media3-internal | — |
| P3-108 (`onDisconnected` nowhere) | fixed — the controller is rebuilt | `ui/MediaControllerConnector.kt`, `ui/MusicViewModel.kt:128` |
| P3-109 (a self-healing error is shown) | fixed | `player/PlaybackService.kt:173` |
| P3-110 (the in-memory resolution key omits the format) | fixed | `data/LibraryRepository.kt:80` (untouched in this pass) |
| REG P2-27 (the standby rebuilds the whole queue per boundary) | fixed | `player/DualDeckPlayer.kt:186`, `:219`, `:235`, `:268` |
| REG P2-28 (the EQ headroom reads a UI snapshot) | fixed — and no per-tick binder IPC | `player/AudioRuntime.kt:40`, `:80` |
| REG P2-34 (the per-emission `Pair` allocations) | fixed | `ui/MusicViewModel.kt:25`, `:191`, `ui/NowPlayingQueue.kt` |
| REG P2-35 (the queue row shows index/title/overflow) | data side fixed; the rendering is A7 | `ui/MusicViewModel.kt:25` |
| P3-46 (an O(N) `firstOrNull` at 2 Hz) | out of area — A7 | `ui/PlayerScreen.kt:39` |

### Not verified here (blockers)

* No device, no emulator, no APK build (forbidden by `android/AGENTS.md`).
  The Media3 controller round trip, the audio-focus callbacks, the crossfade
  handover and the media-button/notification path are therefore reasoned about
  from the pinned 1.11.1 bytecode and covered by **instrumented** tests that
  could not be executed here:
  `androidTest/.../player/PlaybackGateWiringTest.kt` (the refusal round trip,
  the install-paused wiring, the MediaItem factory) and
  `androidTest/.../data/PreferencesQueueTest.kt` (the queue keys).
  They compile (`compileDebugAndroidTestKotlin` is green) but **have not been
  run**.
* `android/app/src/main/AndroidManifest.xml` declares no
  `androidx.media3.session.MediaButtonReceiver`: on API 26-30 the *headset*
  media buttons may therefore never reach the session (the notification's
  buttons do). The manifest is not in A1's ownership — reported to the
  coordinator.

---

## Area A2 — Network client, media-URL policy, streaming & downloads (arbiter & repair log, 2026-10-20)

Status: **closed with residuals** (final pass: arbiter + repair engineer, after
the two independent reviews). The suite of the whole app: 298 tests before the
area's first pass, 352 before this pass, **427** now / 0 failures / 0 errors /
1 skipped; `:app:lintDebug` is green and `:app:compileDebugAndroidTestKotlin`
compiles. No device, no emulator, no
APK: everything that needs a real decoder, a CDN or a Media3 loader is
*reasoned about* from the pinned Media3 1.11.1 / OkHttp 4.12.0 bytecode and
covered by JVM unit tests for the decisions only.

### The five blocking remarks of the adversarial review

| # | Remark | Verdict | What changed |
|---|---|---|---|
| B1 | REG P2-48 is reported *fixed*, but the fallback can never be reached | **confirmed** | the cascade now **finds** the fallback the way the desktop finds it (`core/playback_recovery.py`): the other providers are searched and the app's own matcher (`CatalogMatcher` → `ResolutionIdentity.admitted`) decides whether a candidate is the same recording. `data/ResolutionIdentity.kt` (`findFallback`, `fallbackSources`), `data/LibraryRepository.kt` (`fallbackCandidate`, `resolutionAttempts`). The relation is **session scoped** — nothing is written to the library and the Room schema is unchanged. The registry entry REG P2-48 is **re-opened and re-closed** below. |
| B2 | A truncated HLS package is published as `complete` | **confirmed and worse than described** | the completeness of an HLS package is now judged **by its manifest**: `verifyVod` returns the segments the manifest names, the prune keeps them, and `hlsCompletion` refuses a package that does not hold every one of them. The *mechanism* the review did not see: `SegmentDownloader` **skips** a segment it finds already complete, so the segment was never opened, so the key factory never saw it, so the **prune deleted the bytes of the segments the previous attempt had already downloaded** — a resumed HLS download ended with only the segments of the last attempt. `data/DownloadStorage.kt` (`verifyVod`, `HlsPackage`, `segmentUrls`, `prune`), `downloads/DownloadPolicy.kt` (`hlsCompletion`), `downloads/TrackDownloadWorker.kt` (the keep list, the verdict). |
| B3 | A full disk is retried and the user is told the wrong thing | **confirmed** | the app's own verdict is now a **type**: `DiskFullException`. `isDiskFull` recognises it (a text that merely contains the words of the message is not a verdict), `diskFullFailure()` returns it, `failureText` prints `DISK_FULL_MESSAGE` and `downloadRetry` never retries it. `downloads/DownloadPolicy.kt`, `downloads/TrackDownloadWorker.kt`. |
| B4 + N7 | The policy is enforced against the **union** of the allow-lists, on the media path and on every redirect hop | **confirmed** | the chain now stays inside **one** source. The source travels with the request as an OkHttp **tag** (never on the wire), the first URL decides it, and every hop must be allowed **for that source**. The `Referer` of the hop is the `Referer` of the origin. The cross-provider fallback is reconciled: the fallback is resolved with **its own** source (`resolveWith(fallback, fallback.source, …)`), and the resolution boundary already checks the URL against the source that produced it. `data/MediaHttp.kt` (`MediaSourceTag`, `MediaRedirectInterceptor`, `MediaPolicyInterceptor`), `data/MediaUrlPolicy.kt` (`MediaHostPolicy.accepts`, `onRefusedHost`). |
| B5 | The allow-list has never been checked against a real SoundCloud HLS URL | **confirmed as a hypothesis, refuted as a defect** | see "the observed hosts" below. The list was **widened** to the desktop's oracle (`core/proxy.py`: `scdn.co`, the bare `soundcloud.cloud`) and the observed hosts were pinned as fixtures. |

### The corrected status of REG P2-48

REG P2-48 is **re-opened** and closed as **fixed — the fallback is reachable**:

* before this pass the `fallbackCandidates` parameter of `resolveRemote` was
  dead: the two call sites passed an empty list, so `ResolutionCascade.resolve`
  always got a one-element list and the identity gate was never asked;
* the gate itself was **not** the defect (`ResolutionCascadeTest` proved that
  it admits a cross-provider candidate) — the *relation* was never fed;
* the relation is now produced on demand: the second attempt searches the
  other providers (never the own source of the track) and the app's own
  matcher decides. The search is bounded (`FALLBACK_SEARCH_BUDGET_MS`, 6 s)
  and a search that fails is not an error of the resolution;
* the relation is **session scoped** by necessity: carrying it durably needs a
  column of `Track`, and `data/Models.kt` (the Room schema) belongs to A4.
  Nothing is written to the library;
* the fallback is resolved with **its own** source, so its URL lives on its
  provider's hosts and the media-URL policy is checked against that source.

Pinned by `data/ResolutionCascadeTest.kt` (`the fallback is found by searching
the other provider`, `the own source of a track is never searched again`, `a
search that fails does not break the resolution`, `a supplied candidate is
admitted without a search`).

### The observed hosts of the allow-list

The app's own live probe (`android/review/PROVIDER_PROBE.json`) and a **live
capture of 2026-10-20** (the flow of `data/LiveProviderProbeTest.kt`, run
outside Gradle) agree:

| What | Host | Allowed |
|---|---|---|
| the SoundCloud HLS manifest | `playback.media-streaming.soundcloud.cloud` | yes |
| the SoundCloud HLS segments | `playback.media-streaming.soundcloud.cloud` | yes |
| the client-id asset | `a-v2.sndcdn.com` | yes |
| the metadata path | `api-v2.soundcloud.com` | **no** — it is not a media path |

The live capture also confirmed that the manifest URL carries the CloudFront
authentication parameters (`expires`, `Policy`, `Signature`, `Key-Pair-Id`) —
they are in `authQueryKeys`, so the cache identity of a manifest and of its
segments is stable across resolutions.

The list was **widened** (never narrowed) to the desktop's own oracle
(`core/proxy.py`: `soundcloud.com`, `sndcdn.com`, `soundcloud.cloud`,
`scdn.co`): `scdn.co`, `*.scdn.co`, `soundcloud.cloud` and
`*.soundcloud.cloud` were added for SoundCloud, and the same hosts were added
to `MediaIdentity.signedQueryHosts` so that the cache identity of a segment on
them stays stable. The YouTube and Yandex lists were **not** widened: the
media host of the InnerTube path is `googlevideo.com` (the only host the
player call ever hands out) and the media host of the Yandex path is
`storage.mds.yandex.net` — the other hosts of the desktop's lists are its
*credential* hosts, not its media hosts.

The observed hosts and the desktop's hosts are pinned as fixtures in
`data/MediaUrlPolicyTest.kt` (`the hosts the app has observed are allowed for
their own source`, `the list is at least the list of the desktop`, `a host
belongs to exactly one source`).

### The non-blocking remarks

| # | Remark | Verdict | What changed |
|---|---|---|---|
| N1 / R2 | the documented model of `declared` is the inverse of Media3's | **confirmed** (bytecode) | `CacheWriter.getLength()` is `endPosition - dataSpec.position` and `ProgressiveDownloader` builds its request with the position 0, so `total` is the **total** content length; the `committedBefore + declared` branch was dead. `expectedTotal(declared)` now says so, and the test pins the new model. `downloads/DownloadPolicy.kt`, `downloads/DownloadPolicyTest.kt`. |
| N2 | `lastProgress` is read from another thread | **confirmed** | `AtomicLong` (`downloads/TrackDownloadWorker.kt`). |
| N3 / D7 | the watchdog's claim is not true | **confirmed** | the watchdog bounds a transfer that **stops**; a connection that keeps trickling bytes is bounded by neither the read timeout nor the watchdog, and the stream path is unbounded. The claim is now stated exactly (`TrackDownloadWorker.STALL_TIMEOUT_MS`, `data/MediaHttp.kt`). |
| N4 / D4 | the free-space probe fails open and is not size-aware | **confirmed** | the probe returns `null` when the volume cannot be read and **fails closed**; a size-aware check compares the free space with the bytes that are still missing while the package is written. `downloads/DownloadStorage.kt` (`freeBytes`), `downloads/DownloadPolicy.kt` (`freeSpaceSufficient`), `downloads/TrackDownloadWorker.kt`. |
| N5 / R7 | `observedKeys()` is a process-global set | **false positive** | `ConcurrentHashMap.newKeySet()` returns a **new** set per call, so the keep list was already per attempt; the confusion was in the name. The record is now a named type (`ObservedKeys`) with an explicit "a new record for every call" contract, and the keep list of the attempt is the *observed* keys plus the keys the manifest names. |
| N6 | two blocking cache reads per key computation; a dead legacy fallback | **confirmed** | the key factory is **pure** now, and the legacy fallback is gone: the old key contains the signature of a signed path, the signature changes with every resolution, so the old package cannot be found by a new resolution any more. The fallback was dead code that cost a disk read for every HLS segment. `downloads/DownloadStorage.kt`, `downloads/DownloadKeys.kt`. |
| N8 | OkHttp drops `Authorization` on a cross-host redirect; the hand-made hop did not | **confirmed** (bytecode) | the hop now drops the header when the connection cannot be reused (host, port or scheme) — the same rule as `RetryAndFollowUpInterceptor`. `data/MediaHttp.kt`. |
| N9 / R3 | the media UA differs from the provider UA and from the desktop's YouTube UA | **confirmed** | one agent for the whole provider session: the metadata call, the InnerTube call and the media call all send the Chrome UA of the desktop (`services/youtube_service.py`, `services/soundcloud_service.py`). `data/MediaUrlPolicy.kt` (`USER_AGENT`), `data/Sources.kt`. |
| N10 | the budget is measured with a wall clock | **confirmed** | `ResolutionCascade` measures with `System.nanoTime()`; an NTP step can no longer end the cascade silently. `data/ResolutionCascade.kt`. |
| N11 | two files named `MediaStatus.kt` | **confirmed** | `downloads/MediaStatus.kt` → `downloads/MediaResponseStatus.kt` (the function `mediaResponseStatus` keeps its name). |
| N12 | `onCreate` forces the Media3 database, the Room database and the reconcile | **confirmed** | the recovery now runs on the IO scope; the first frame does not wait for it. `NeDotifyApp.kt`. |
| R4 | the cancellation cleanup of `StreamCache` can be cancelled by its own cancellation | **confirmed** | the cleanup runs in `withContext(NonCancellable)`, the idiom the class already used in its `finally`. `data/StreamCache.kt`. |
| R5 | a refused host is invisible | **confirmed** | the refused **host** (never the URL — a signed URL carries a signature) is logged. `data/MediaUrlPolicy.kt` (`onRefusedHost`), `data/MediaHttp.kt`. |
| R6 | two construction sites could create two Media3 database providers | **confirmed** | the `DatabaseProvider` is a **required** parameter of `Downloads` and `DownloadStorage`. `downloads/Downloads.kt`, `downloads/DownloadStorage.kt`. |
| D6 | the progress reported to the DAO is the newly cached bytes | **confirmed** (bytecode) | Media3 counts the bytes of the resource it writes: a progressive download counts the bytes that are already in the cache, an HLS download counts only the new ones. The worker reports the **committed total** in both cases and computes the percentage itself. `downloads/TrackDownloadWorker.kt`. |

### The per-finding table (corrected)

| Id | Outcome | Where |
|---|---|---|
| P1-04 (the 30 s total budget cuts every transfer) | fixed | `data/MediaHttp.kt` (`callTimeout(0)`), `data/Sources.kt` (`mediaHttp`), `player/PlaybackService.kt`, `downloads/DownloadStorage.kt` |
| REG P2-52 / P3-24 (no media-URL policy) | fixed — **per source, on every hop** | `data/MediaUrlPolicy.kt`, `data/MediaHttp.kt`, `data/LibraryRepository.kt` (the resolution boundary), `downloads/TrackDownloadWorker.kt` |
| REG P2-51 / P3-22 (no headers, no session error on 401/403) | fixed | `data/MediaHttp.kt`, `data/MediaStatus.kt` (`mediaSessionError`) |
| REG P2-47 (the streaming cache has no stable identity) | fixed | `data/MediaIdentity.kt`, `player/PlaybackService.kt` |
| REG P2-49 (the Yandex signature lives in the path) | fixed | `data/MediaIdentity.kt`, `downloads/DownloadKeys.kt` |
| REG P2-50 (the completeness is never checked) | fixed | `downloads/DownloadPolicy.kt` (`downloadCompletion`, `hlsCompletion`), `downloads/TrackDownloadWorker.kt` |
| REG P2-30 (no ceiling, no length check, no space probe, ENOSPC retried) | fixed | `downloads/DownloadPolicy.kt` (the ceiling, the floor, the probe, the disk-full **type**), `downloads/TrackDownloadWorker.kt` |
| REG P2-29 (the worker enters the foreground before the permit) | fixed | `downloads/DownloadGate.kt`, `downloads/TrackDownloadWorker.kt` |
| **REG P2-48 (the cascade never falls back)** | **re-opened and fixed — the fallback is reachable; the relation is session scoped** | `data/ResolutionCascade.kt`, `data/ResolutionIdentity.kt`, `data/LibraryRepository.kt` |
| REG P2-09 (a cancelled resolution keeps the slot) | fixed | `data/StreamCache.kt` |
| P3-77 (two database providers over one file) | fixed (one provider, required parameter) | `NeDotifyApp.kt`, `downloads/Downloads.kt`, `downloads/DownloadStorage.kt` |
| P3-112 (Coil has no image loader) | fixed | `data/ImageHttp.kt`, `NeDotifyApp.kt` |
| P3-23 (the DRM message is false) | fixed | `downloads/DownloadPolicy.kt`, `data/Sources.kt` |
| P2-53 (the download must publish `complete` only when the bytes are complete) | fixed — an HLS package is judged by its manifest | `downloads/TrackDownloadWorker.kt` |

### The tests

Every new test fails when its production code is reverted.

| File | Contract it pins |
|---|---|
| `data/MediaUrlPolicyTest.kt` | the per-source allow-list, the **observed** hosts, the desktop's hosts, the "looks like" hosts, the port/credential/fragment rules, the Yandex list against `YandexDownloadInfo.trustedUrl`, one owner per host |
| `data/MediaHttpTest.kt` | the headers, the redirect to a foreign host, the redirect **to another source** (refused), the redirect inside the source (followed, with the referer of the origin), the `Authorization` header dropped on a hop that cannot reuse the connection, the redirect loop, the 401/403 classification, the absent total budget, one agent per session |
| `data/MediaWiringTest.kt` | the **download** path, the **player** path and the **manifest** read use `network.mediaHttp` and not the metadata client — the one test that fails if the media client is put back |
| `data/MediaStatusTest.kt` | the text of a media failure survives the wrapping of the loader and reaches the user |
| `data/ResolutionCascadeTest.kt` | the shared budget, the second attempt, the first error, the identity gate, the **reachable** fallback, the monotonic clock |
| `data/StreamCacheTest.kt` | the flight is released and its job cancelled when the last waiter leaves; a flight with a waiter survives |
| `downloads/DownloadPolicyTest.kt` | the completeness verdict, the **HLS** completeness verdict, the declared total of Media3, the disk-full **type**, the retry decision, the free-space probe (fails closed), the ceiling, the stream verdicts |
| `downloads/DownloadWorkerContractTest.kt` | the order of the worker's statements: the verdict before the publication, the free-space probe before the transfer, the ceiling cancels the downloader, the retry decision is one function |
| `downloads/DownloadGateTest.kt` | the foreground is not entered while the worker waits for its slot |
| `downloads/MediaResponseStatusTest.kt` | the status survives the wrapping of the loader, the texts of 401/403 |

### Not verified here (blockers)

* **No device, no emulator, no APK** (forbidden by `android/AGENTS.md`).
  The end-to-end behaviour of the media path is therefore reasoned about from
  the pinned Media3 1.11.1 and OkHttp 4.12.0 bytecode and covered by JVM unit
  tests for the decisions only. In particular **not** observed:
  * the **progressive stream** on a slow link (P1-04);
  * the **HLS download** end to end: the segment URLs of the verdict are
    resolved with `UriUtil.resolveToUri`, which needs `android.net.Uri` and
    therefore **cannot be exercised in a JVM test**. The resolution is the
    same call Media3 makes, and a mismatch would fail the verdict *loudly*
    (the download would be refused) instead of publishing a truncated package;
  * the **resumed HLS download** (the defect of B2) — the mechanism was read
    out of the `SegmentDownloader` bytecode, not observed;
  * the **cache identity** in the player and the read itself.
* **The YouTube media path is unobservable right now.** A live InnerTube call
  with the client's own `ANDROID_MUSIC` context answers `LOGIN_REQUIRED`
  ("Требуется вход") for every video — the same verdict the repository's own
  probe recorded (`android/review/PROVIDER_PROBE.json`). The media host of
  the YouTube path therefore could not be confirmed live; the allow-list of
  the path (`googlevideo.com`, `*.googlevideo.com`) is the only host the
  player call hands out, and the agent of the path is the desktop's.
* The **cover-art** path (P3-112) is a Coil loader with an OkHttp client; the
  client is unit tested, the loader is not (it needs an Android runtime).
* `android/PORTING_STATUS.md` (owned by A8) still describes the old
  streaming behaviour — **not** changed here.
---

## Area A9 - Windows desktop destructive dup-cleanup migration, data safety (fix engineer log, 2026-10-20)

Status: **fixed - pending the two independent reviews.** Baseline
**1459 tests / 0 failures / 0 errors / 1 skipped**  now **1485 / 0 / 0 / 1**
(26 new tests in `tests/test_dup_cleanup_migration.py`; the three `xfail`s
and the skip were already there). Every test builds its own throwaway SQLite
file; the real `~/.nedotify/` library was never opened.

### The defect (P0-01)

`core/database.py` used to run, once per library, three `DELETE` statements
guarded by the `settings` row `migration_dup_cleanup_done`:

1. remove exact-duplicate `(playlist_id, track_id)` rows from `playlist_tracks`;
2. remove `playlist_tracks` rows whose track groups by `LOWER(title),
   LOWER(artist)` **within a playlist**, keeping `MIN(pt2.id)` — this one could
   strip the playlist entry of a track that **survived** the migration;
3. delete every `tracks` row that is not the `MIN(id)` of its
   `LOWER(title), LOWER(artist)` group.

Statement 3 destroyed the track row and, through `ON DELETE CASCADE`, its
`history` rows, its playlist entries, its `play_count`, its `is_favorite`, its
`file_path` / `is_downloaded`, its `last_played` and its `metadata_json`. The
audio file stayed on disk, referenced by nothing. The whole block sat in
`try/except Exception: logger.debug(...)` — below the production log level —
and the transaction was committed by the unconditional `conn.commit()`, so a
mid-block failure left a **half-migrated** library with the flag unset.

Two refutations were honoured and are **not** “fixed”:

* the identity key is not the cause — `(LOWER(title), LOWER(artist))` **is**
  the desktop's own track identity (`add_track`), introduced in the same
  commit `b6a6553` as the migration. The key was **not** changed.
* the FK cascade is not the cause of the playlist loss — statements 1 and 2
  removed the playlist entries themselves. The cascade was **not** disabled.

### The new algorithm (in order)

`_run_dup_cleanup_migration()` runs from `_init_database()`:

1. **Versioned one-shot guard.** A new table `schema_migrations(version,
   applied_at, details)` records the migration (`dup_cleanup_v2`). If the
   record exists, nothing runs. The legacy boolean `migration_dup_cleanup_done`
   is *read* (it says the old destructive cleanup already ran) and — when the
   library never ran it — written with the new value `'2'` **inside the
   transaction**, i.e. only after a successful commit.
2. **A library that already ran the old cleanup is left exactly as it is** —
   no plan, no merge, not even the redundant playlist entries. Its damage is
   done and cannot be undone.
3. **The plan is computed read-only** (`_plan_track_merges`): the rows are
   grouped by the application's own identity (`TRACK_IDENTITY_SQL` — the same
   expression `add_track` uses) and each group is partitioned by the
   *recording* fields (`title, artist, album, source, source_id, file_path`).
   Only the rows of one partition — the same recording — may be collapsed.
   Rows that merely share a title/artist (different album, different provider
   id, different file, different spelling, unknown artist) are **different
   recordings** and are left untouched.
4. **Snapshot, before anything is written** (`_snapshot_before_dup_cleanup`):
   * a dated byte-level copy of the whole database next to it —
     `<db>.dup-cleanup-<timestamp>.db`, produced by `VACUUM INTO` (it cannot
+     run inside a transaction, so the open transaction is committed first);
+   * a one-shot `tracks_backup` table (`CREATE TABLE IF NOT EXISTS tracks_backup
+     AS SELECT * FROM tracks`) — the source the corrective migration restores
+     from. The one-shot guard is the table itself, so it cannot grow without
+     bound. The snapshot is taken **only when there is something to merge**:
+     an empty library has nothing to lose.
+5. **The merge** (`_apply_track_merges` → `_merge_track_row_into`), inside one
+   transaction:
+   * the duplicate's payload moves into the survivor: `play_count` is summed,
+     `is_favorite` is OR-ed, `last_played` is the later of the two, and every
+     other non-empty column (`file_path`, `cover_url`, `source_id`, `duration`,
+     `metadata_json`, …) is carried over where the survivor has none. The
+     columns are taken from `PRAGMA table_info(tracks)`, so an old library
+     that does not have every column yet is still migrated;
+   * the duplicate's `history` rows, `playlist_tracks` rows and
+     `download_queue` rows are **re-pointed at the survivor** (the old ids are
+     recorded in `history_track_remap` / `playlist_tracks_track_remap`);
+   * only then is the (now empty) duplicate row deleted, and the merge is
+     recorded in `track_merges(duplicate_id, survivor_id, merged_by,
+     merged_at)`.
+   * **No history row ever loses its track**: it is re-pointed, never deleted.
+6. **The playlist cleanup** now only removes a redundant *second* entry for
+   the **same** `(playlist_id, track_id)` pair. The old statement 2 — the one
+   that could remove the playlist entry of a **surviving** track — is gone.
+7. **The versioned record and the flag are written inside the transaction.**
+   A failure rolls the whole block back: the library is untouched and the
+   migration runs again on the next start.
+8. **The log.** A `WARNING` names what was touched: the number of merged
+   rows, the survivors, the re-pointed history rows and playlist entries, the
+   removed redundant entries, the same-title rows left in place, and the
+   snapshot path. A library with nothing to merge gets an `INFO` line with the
+   same counters. The old `logger.debug` is gone; a failure is an `ERROR`
+   with the traceback.
+
+### The corrective migration
+
+`_run_dup_cleanup_restore()` runs right after the merge and is versioned
+(`dup_cleanup_restore_v1`):
+
+* it restores the rows a **previous** merge version retired, from
+  `tracks_backup`, and moves their history and playlist entries back with
+  them (`track_merges` is the candidate list, so a track the user deleted
+  afterwards is never resurrected — the backup table is *not* used as the
+  candidate list);
+* if the legacy destructive cleanup already ran on the library, it says so
+  plainly at `ERROR`: the deleted tracks, listening history and playlist
+  entries were **not** backed up and are **not recoverable**; the audio files
+  are still on disk — re-scan the music folders to bring the missing tracks
+  back, the listening history and the playlist entries cannot be restored.
+
+### The identity decision (and why the two paths move together)
+
+**The app keeps ONE track identity: `(LOWER(title), LOWER(artist))`.** It is
+defined once, in `core/database.py`, as `TRACK_IDENTITY_SQL`, and both paths
+use that very expression — `add_track` (the creation path) and
+`_plan_track_merges` (the migration). The placeholder-name guard
+(`name_is_meaningful`) is likewise one definition used by both.
+
+The migration adds **one strictly stronger condition before it removes a row**:
+the two rows must also agree on the recording fields
+(`album, source, source_id, file_path`). The identity alone is too coarse —
+the same title with a different album, a different provider id or a different
+file is a *different recording*, and the migration must not destroy it. So the
+migration can never collapse two rows the app's own identity keeps apart, and
+it can never collapse a pair the app's identity calls the same song but the
+recording fields call different.
+
+Widening `add_track` to the recording identity was **rejected**, deliberately:
+
+* it would make the creation path *create* near-duplicate rows (the same song
+  from two providers, or the same song in two albums) instead of reusing one
+  row — the exact behaviour change the audit's “potential regressions” note
+  warns about, and a change the app's existing contract
+  (`tests/test_database.py::test_add_track_dedups_by_source`, which pins that
+  two rows with the same title/artist but different `source_id` are one track)
+  would have to be weakened;
+* it is not needed for safety: the danger was never the key, it was the
+  `DELETE`. The operation is now a merge, and the merge only touches rows it
+  can prove are the same recording.
+
+### Per finding
+
+| Requirement (R1.1 §1.4–1.6) | Outcome | Where |
+|---|---|---|
+| 1.4 merge instead of `DELETE`; never delete a row a `history` row references | fixed — the payload is folded into the survivor, the history rows are re-pointed, only the emptied row goes | `core/database.py::_merge_track_row_into` |
+| snapshot before anything destructive, one-shot | fixed — `VACUUM INTO` copy + one-shot `tracks_backup` table, taken only when there is something to merge | `core/database.py::_snapshot_before_dup_cleanup` |
+| atomic block; the flag only after a successful commit | fixed — one transaction, the versioned record and the flag are written inside it | `core/database.py::_run_dup_cleanup_migration` |
+| 1.6 fix or drop statement 2 (it could strip a *surviving* track's playlist entry) | fixed — statement 2 is gone; only a redundant second entry for the same `(playlist, track)` pair is removed | `core/database.py::_remove_exact_duplicate_playlist_entries` |
+| log at `warning`/`error`, naming what was touched | fixed — a `WARNING` with the counters and the snapshot path; a failure is an `ERROR` with the traceback | `core/database.py::_run_dup_cleanup_migration` |
+| 1.5 corrective migration that restores from the backup table where one exists | fixed — `dup_cleanup_restore_v1` restores a retired row from `tracks_backup` and moves its history/playlist entries back; for the users the old cleanup already hit there is **no** backup, and that is said plainly | `core/database.py::_run_dup_cleanup_restore` |
+| idempotent; must not resurrect tracks the user deleted afterwards | fixed — the versioned records make it one-shot, and the restore's candidate list is `track_merges`, not the backup table | `core/database.py::_restore_merged_tracks` |
+| the creation path and the migration must use the same key | fixed — `TRACK_IDENTITY_SQL` + `name_is_meaningful`, one definition, both paths | `core/database.py` (module level) and `add_track` |
+
+### Tests
+
+`tests/test_dup_cleanup_migration.py` — 26 tests, all of them failing against
+the old block (checked by re-running the file against the pre-fix migration:
+**22 of 25 failed**, the three that passed are the structural ones). The
+acceptance criteria of `RECOMMENDED_FIX_ORDER.md` §1, item by item:
+
+| Criterion | Test |
+|---|---|
+| same title/artist, different **album** → not deleted | `test_same_title_artist_different_album_survives` |
+| same title/artist, different **source** → not deleted | `test_same_title_artist_different_source_survives` |
+| same title/artist, different **source_id** → not deleted | `test_same_title_artist_different_source_id_survives` |
+| same title/artist, different **file_path** → not deleted | `test_same_title_artist_different_file_path_survives` |
+| same title/artist, different **case** → not deleted | `test_same_title_artist_different_case_survives` |
+| **NULL artist** → not deleted | `test_null_artist_rows_survives` |
+| placeholder names → not collapsed (the creation path's own guard) | `test_placeholder_names_are_never_collapsed` |
+| a true duplicate is **merged**, the payload folded into the survivor | `test_true_duplicate_is_merged_not_dropped` |
+| a duplicate's **history row** is still present | `test_history_row_of_a_duplicate_is_still_present` |
+| a duplicate stays in its **playlist** | `test_duplicate_stays_in_its_playlist` |
+| a **surviving** track keeps its playlist entry (arbiter reproduction #2) | `test_surviving_track_keeps_its_playlist_entry` |
+| **no distinct recording deleted** (the whole synthetic library) | `test_no_distinct_recording_is_deleted` |
+| a **log line naming what was touched** | `test_log_names_what_was_touched` |
+| the **snapshot** exists before the merge | `test_snapshot_is_taken_before_the_merge` |
+| the block is **atomic** (a failure leaves the library untouched) | `test_the_migration_is_atomic` |
+| the **flag is written only after a successful commit** | `test_the_flag_is_written_only_after_a_successful_commit` |
+| a **fresh** database is a no-op | `test_fresh_database_is_a_noop` |
+| a database that **already has the flag** is left alone | `test_database_with_the_legacy_flag_is_left_alone` |
+| the migration is **idempotent** | `test_the_migration_is_idempotent` |
+| the **upgrade path**: a pre-`b6a6553` library (no flag, no versioned record) is migrated | every test above runs on such a library; `test_an_old_schema_without_the_newer_columns_is_migrated` additionally uses a pre-`lufs` schema |
+| the **corrective** migration restores a retired row | `test_corrective_migration_restores_a_retired_row` |
+| it does **not** resurrect a track the user deleted | `test_corrective_migration_does_not_resurrect_a_deleted_track` |
+| the legacy damage is reported **plainly** | `test_legacy_damage_is_reported_plainly` |
+| the creation path and the migration **share the key** | `test_creation_path_and_migration_share_the_identity_key`, `test_the_creation_path_agrees_with_the_merged_survivor`, `test_name_guard_is_shared` |
+
+### What is NOT recoverable
+
+**The users who already ran the destructive migration (v2.0.0 and later, and
+`cycle-2`) have already lost data, and this change cannot give it back.** The
+old block took no snapshot, so the deleted `tracks` rows, their `history`
+rows, their playlist entries, their `play_count`, their `is_favorite` and
+their `file_path` are gone. The audio files are still on disk — a library
+re-scan brings the missing tracks back — but **the listening history and the
+playlist membership cannot be restored**. The corrective migration says
+exactly that in the log (`ERROR`) instead of pretending otherwise.
+
+The remaining at-risk population (a library written before 2026-08-12 that
+has not been opened since) is protected by the new merge.
+
+### Not verified here (blockers)
+
+* The real `~/.nedotify/` library was never opened, read or copied, so the
+  number of affected rows in a real library is unmeasured. Everything is
+  proven on synthetic throwaway databases.
+* The desktop application was not started (the brief forbids it), so the
+  startup path was exercised through `DatabaseManager` only.
+* The **file** snapshot (`VACUUM INTO`) costs a second copy of the database on
+  disk, once, and only for a library that actually has duplicates to merge.
+  A library with a very large `history` table pays that once.
+* The merge changes the library's *statistics* for the affected rows: the
+  play counts of the collapsed duplicates are now carried by the survivor, so
+  `get_most_played` / `get_wrapped_stats` / `get_top_artists` rank the
+  survivor higher. The totals are unchanged.
+* A library that already ran the old cleanup is left untouched, so the
+  *remaining* near-duplicates in it (if the old block created any) stay. That
+  is the deliberate “left alone” behaviour, not an oversight.
+
+
---

## Area A5 - Providers, OAuth / auth, secure credential store (fix engineer log, 2026-10-20)

> **Second pass — the final arbitration of A5.** The two independent reviews
> (`android/review/ARBITRATION_A3_A4_A5.md` → "## A5") were adjudicated remark by
> remark against the code, the confirmed defects were repaired, and the missing
> regression tests were added. The area report is
> `android/review/REMEDIATION_A5_FIX.md`.

Status: **fixed — arbitrated and repaired.** The area's own tests:
**88 / 0 / 0 / 0** (`ProviderConnectionsTest` 46, `ProviderAuthTest` 10,
`SecureProviderStoreTest` 14, `AuthPkceTest` 14, `ConnectionsControlsTest` 4).
The whole tree: **602 tests / 0 failures / 0 errors / 0 skipped**
(`TEST_SUMMARY files=82 tests=602 failures=0 errors=0 skipped=0`).
`:app:lintDebug` is green: **0 errors, 17 warnings, 0 hints** — none of them in
a file of this area. No device, no emulator and
no APK (forbidden by `android/AGENTS.md`): the Android Keystore, the
notification-listener trust predicate and the real OAuth round trip are **not**
runtime verified.

### The one model that carries the area

The area had one dominant root cause (**RC-7**: “a classified code drives a
destructive action”, plus the auth-lifecycle half of it: *the pending login, the
credential rotation and the single-flight refresh*). It is now **one** model
with three rules, in `data/ProviderConnections.kt`:

| Rule | What it replaces |
|---|---|
| **The state is guarded, the network is not.** The mutex protects the in-memory credentials and is *never* held across an HTTP call. | `action{}` and `spotifyAccess()` held the lock across the token POST, the account call and the refresh (REG P2-05). |
| **One flight at a time.** A refresh token is spent by exactly one request; the waiters share its result. The re-validation of a credential after a 401 is done once for all the requests that failed together. | Two concurrent refreshes could spend the same refresh token; a 401 storm could trigger a re-validation per request. |
| **A credential is only destroyed on proof.** A 401 from one endpoint is re-validated against `account/status` before the credential is dropped; a pending login is only consumed after its token has been stored; and a stored record is removed **only** when it is provably damaged — a keystore that cannot be reached leaves it alone. | One 401 from any Yandex call destroyed the user's credential (P1-03); the pending login was destroyed *before* the token POST (REG P2-03); an unreachable Keystore deleted the record (the second pass). |

The pending login is now a **list** (`PendingLogins`), not a single record: a
second PKCE start adds its own login instead of overwriting the first one, and
the callback is matched against the login whose `state` it carries (P3-66). The
exchange runs in an **application-scoped** coroutine (`ProviderConnections.scope`),
so an Activity that goes away in the middle of it does not lose the login
(REG P2-03).

### Per finding

| Id | Outcome | Where |
|---|---|---|
| P1-03 (a 401 destroys the Yandex credential) | fixed — **re-validate → then remove**; the re-validation is the same `account/status` call the login makes | `data/ProviderConnections.kt:438` (`handleYandexUnauthorized`), `data/ProviderAuth.kt` (`yandexCredentialAction`) |
| REG P2-03 (the OAuth flow loses the login) | fixed — the pending login survives a failed exchange, the exchange runs in the application scope, and the callback is re-deliverable | `data/ProviderConnections.kt:234` (`handleSpotifyRedirect`), `:278` (`exchangeToken`), `MainActivity.kt:52-66` |
| REG P2-05 (the mutex is held across HTTP) | fixed — the lock is never held across a request; a single-flight guard replaces it | `data/ProviderConnections.kt` (all `lock.withLock` blocks), `data/ProviderAuth.kt` (`SingleFlight`) |
| REG P2-04 (the MediaSession trust predicate) | **no change needed** — `controller.packageName==packageName \|\| controller.isTrusted` is already the predicate of Media3 1.11.1 | `player/PlaybackService.kt:158-162` (A2's file, not touched) |
| P3-17 (the error does not name the credential) | fixed — the message names the service, and tells a dead credential from a refused request | `data/ProviderAuth.kt` (`providerAuthMessage`) |
| P3-18 (`cipher.init` outside the try, a broken alias is never replaced) | fixed — the whole cipher is guarded, a broken alias is deleted and re-created, a raw crypto exception never leaves the class | `data/SecureProviderStore.kt` (`ProviderSecretCipher`, `providerKeyAction`) |
| P3-19 (no `CertificatePinner`) | **decision recorded, not implemented** — pinning would break the app when a CDN rotates its chain; the three token-bearing origins are `api.spotify.com`, `accounts.spotify.com` and `api.music.yandex.net` | recorded here and in the fix report |
| P3-20 (the Spotify import stores the candidate's metadata) | **out of area** — the divergence is in `data/CatalogMatcher.kt:66-76` (A6) and `ui/MusicViewModel.kt` (A7); the Yandex path (`data/CatalogProviders.kt:102`) is the reference | reported to the coordinator |
| P3-21 (no `maxBytes` seam on the account-growing endpoints) | fixed — the provider path reads the body with an explicit limit; the Yandex `users/…` endpoints (the whole library, one playlist) get 8 MB, everything else stays at 2 MB | `data/ProviderPayload.kt`, `data/ProviderAuth.kt` (`providerPayloadLimit`) |
| P3-66 / MAIN-P2-42 (a second PKCE start invalidates the first) | fixed — every start adds its own pending login, the callback is matched by `state` | `data/AuthPkce.kt` (`PendingLogins`), `data/ProviderConnections.kt:213` |
| P3-67 (the pending is cleared for one exact message; `cancelSpotifyLogin()` has no caller) | fixed — the denial is a typed outcome (`AuthPkce.Outcome.Denied`), and the user can cancel the login from the panel | `data/AuthPkce.kt` (`decide`), `data/ProviderConnections.kt:311` (`logout("spotify-login")`), `ui/ConnectionsControls.kt` (“Отменить вход”) |
| P3-68 (the confirm button clears the field before the save completes) | fixed — the value is dropped only when the service has accepted it; a failed save keeps it and shows the error inside the dialog | `ui/ConnectionsControls.kt` (`credentialSaveSettled`) |
| P3-69 (no `liveRegion` in `ConnectionsControls`) | fixed — the status lines and both error lines are a live region | `ui/ConnectionsControls.kt` |
| P3-70 (the `password()` semantics are unused) | fixed — the token field is marked as a password and has a visibility toggle. The audit's “reads the token aloud” is **overstated** and was not adopted as stated | `ui/ConnectionsControls.kt` |
| P3-71 (a `require` whose trigger can never fire; the reachable one is swallowed) | fixed **in the part that is A5's**: the reachable `require` in `apiUrl` now produces "Недопустимый запрос к сервису" instead of the raw "Failed requirement.". The other half of the finding is in A4's files and is reported | `data/ProviderConnections.kt:389` (`apiUrl`) |

### The second pass: the arbitration of A5

Every remark of the two independent reviews (`android/review/ARBITRATION_A3_A4_A5.md`
→ "## A5") was verified against the code before it was acted on. The full
adjudication (with the evidence and the file:line of every remark) is in
`android/review/REMEDIATION_A5_FIX.md`; the table below is the summary.

| remark | verdict | what changed |
|---|---|---|
| B1 (High) — an unreachable Keystore **destroys** the stored credential | confirmed & fixed | two typed failures (`ProviderCredentialUnavailableException` / `ProviderCredentialCorruptException`); the recovery removes a record **only** when it is provably damaged. `data/SecureProviderStore.kt:27-38`, `data/ProviderConnections.kt:94-160` |
| B2 (Medium) — a 403 from the re-validation is treated as a dead credential | confirmed & fixed | `DEAD` = **401 only**; a 403 is `RESTRICTED` and maps to `KEEP`. `data/ProviderAuth.kt:66-84`, `data/ProviderConnections.kt:458` |
| B3 (Medium) — `exchangeSpotifyRedirect()` can never find the pending login | confirmed & fixed | the durable entry point calls `load()` before it matches the callback. `data/ProviderConnections.kt:256` |
| B4 (Medium) — a failed durable exchange is silent | confirmed & fixed | the failure is published into `_status.error`. `data/ProviderConnections.kt:241` |
| B5 (Medium) — the same client id in another case destroys the token | confirmed & fixed | the id is canonicalised once. `data/AuthPkce.kt:121` |
| N1 — no coverage for the inconclusive re-validation | confirmed & fixed | a 500 from `account/status` keeps the credential (test added) |
| N2 — the bound of the pending list is not pinned | confirmed & fixed | the bound of 4 is pinned by a test |
| N3 — the flight key holds the refresh token without redaction | confirmed & fixed | `SecretKeyRef`, a redacted carrier. `data/ProviderAuth.kt:15-21` |
| N4 — the redirect scheme is claimable by another app | confirmed & **recorded, not fixed** | a design limitation (PKCE bounds the damage); it needs a domain the project does not own |
| N5 — `URLDecoder` for a URI query | confirmed & fixed | the area's own percent-decoder; a `+` is a literal plus. `data/AuthPkce.kt:188-208` |
| N6 — the wrong speaker for a user-pasted token | confirmed & fixed | `AuthPkce.userSecret()`. `data/AuthPkce.kt:133` |
| N7 / D4 — `busy` is a boolean read-modify-written outside the lock | confirmed & fixed | a counter under the mutex. `data/ProviderConnections.kt:173-179` |
| N8 — an expired pending login is not removed when the callback is refused by age | confirmed & fixed | the refusal by age removes the pending login |
| N9 — the editor state is lost on a configuration change | confirmed & fixed | `rememberSaveable` (the token itself stays in memory only). `ui/ConnectionsControls.kt:43-53` |
| N10 — a stale line citation | confirmed & fixed | `player/PlaybackService.kt:158-162` |
| N11 — no `REMEDIATION_A5_FIX.md` | confirmed & fixed | the report is created |
| D1 (Medium) — the OAuth callback is not re-deliverable | confirmed & fixed | the callback is read on **every** creation and marked in a ViewModel (a rotation does not deliver it twice, a process death does). `MainActivity.kt:35-66` |
| D2 — a Spotify refresh that answers 400 keeps the generic message | confirmed & fixed | `invalid_grant` (400) names the credential that was lost. `data/ProviderAuth.kt:108-119` |
| D3 — the second JSON reader and the dead `ProviderHttp.json` | confirmed & fixed | one reader (`data/ProviderPayload.kt`); the copy is deleted |
| D6 (info) — the file layer has no JVM test | confirmed & fixed | a `File`-based record layer (the `.bak` recovery, the size caps) with tests over real files. `data/SecureProviderStore.kt:169-201` |
| D7 (info) — the expired-pending filter is pinned only on the start path | confirmed & fixed | the filter also runs on the `load()` path (test added) |
| D8 (info) - a pending login of a different Spotify application is now silently dropped at load | confirmed & **recorded, deliberately kept** - such a login cannot be finished (the client id is bound to the application that started it), the record is rewritten without it, and the panel shows the real state. data/ProviderConnections.kt:127-135 |
| R6 (info) — `get(provider, …)` treats everything but "spotify" as Yandex | confirmed & fixed | an unknown provider is refused and no request is sent. `data/ProviderConnections.kt:395` |
| A6 §10 — the AOSP-only `optString` defects in A5's files | confirmed & fixed | the app-wide reader `optText` is used: a JSON null is not a value. `data/AuthPkce.kt`, `data/ProviderConnections.kt:458` |
| the stale test **name** "cancelled token exchange releases mutex busy flag…" | confirmed & fixed | renamed; the assertions are unchanged |

### The three corrections of the corpus that were honoured

* The Yandex delete was **never** unconditional (it is guarded by the
  generation and the token value) — the *behaviour* was fixed, not the wording.
* A recovery path **did** exist (`ui/ConnectionsControls.kt`: “Подключить”); the
  finding that there is none was not adopted.
* The “clears the token and retries once” describes the **Spotify** branch. No
  retry was added to Yandex: Yandex got a **re-validation**.

### Tests

The area's own tests: **88 / 0 / 0 / 0** (27 before the first pass → 57
after it → **88** after the arbitration pass).
Every new test fails when its production code is reverted.

| File | Contract it pins |
|---|---|
| `data/ProviderConnectionsTest.kt` | a Yandex 401 whose re-validation **succeeds** keeps the credential and the scope; a Yandex 401 whose re-validation **fails** drops it and rotates the scope; **an inconclusive re-validation (500) keeps it**; **a 403 from the re-validation keeps it**; **an unreachable keystore never removes the record**; **a damaged record is removed**; the same client id in another case keeps the token and the started login; the durable entry point finds the pending login of a fresh instance; a failed durable exchange is published to the user; the busy flag survives overlapping actions; the expired pending login is dropped on the `load()` path; the old single-object pending format still finishes a login; an unknown provider is refused; a second login start keeps the first one; a failed exchange keeps the pending login; the exchange survives the caller that started it; the user can cancel a started login; the failure names the service; a slow Spotify refresh does not block a Yandex read; the account-growing endpoint accepts a document the tight limit rejects; an expired login is dropped |
| `data/ProviderAuthTest.kt` | the credential decision table (drop only on a rejected re-validation, never on a stale one, never on a restricted one); the two service-named messages; **the message of a credential that was lost (a Spotify 400)**; the payload limit per endpoint; the bounds of the provider JSON reader; one flight at a time; a cancelled waiter does not cancel the flight; **the key of a flight never carries the secret into a diagnostic string** |
| `data/SecureProviderStoreTest.kt` | the key policy (reuse / create / re-create / refuse); a secret survives a round trip and is bound to its own name; a broken alias is replaced; a missing alias is created without a delete; an unreachable keystore is never touched; a raw crypto exception never reaches the caller; **an unavailable key and a damaged record are told apart**; **the file layer**: the round trip, the `.bak` recovery, the size caps, the removal without a remnant, a failed write keeps the previous record |
| `data/AuthPkceTest.kt` | the callback is matched against the login whose state it carries; a refusal is a typed outcome, not a message; every started login is kept until it is finished or expires; **the list of pending logins is bounded**; **a `+` in the query is a literal plus**; **the client id has one spelling**; **a token the user typed in is the user's mistake**; **a JSON null is not a value**; only the registered redirect is a callback |
| `ui/ConnectionsControlsTest.kt` | the value is only dropped when the service accepted it (Yandex by its revision, Spotify by the stored client id); **the OAuth callback is delivered on every creation and only once per process** (a source-level guard — an Activity lifecycle is not observable from a JVM test) |

### Changes to the existing tests (and why)

* `ProviderConnectionsTest.cancelled token exchange releases mutex busy flag and
  preserves previous account` asserted `spotifyPending == false` after a
  cancelled exchange. That assertion pinned the defect of REG P2-03 (the pending
  state was destroyed before the token POST); it is now `assertTrue` — the
  pending login must survive so the user can retry.
* `ProviderConnectionsTest.encoded traversal and backslash authority cannot
  receive provider authorization` expected an `IllegalArgumentException`; it now
  expects a `SourceFailure` with a message the user can read. The assertion that
  matters — *the path is never sent* — is unchanged.
* The three `PendingSpotify.stored(store["spotify_pending"])` call sites read
  the new list format (`PendingLogins.stored(...).items.single()`). The old
  single-object format is still **read** (`PendingLogins.stored` accepts it).
* **The arbitration pass:** the test **name** `cancelled token exchange releases
  mutex busy flag and preserves previous account` was stale (the model has no
  mutex around the exchange any more) and is now `a cancelled token exchange
  releases the busy flag and preserves the previous account`; the **assertions**
  are unchanged. The two call sites of the deleted second JSON reader
  (`ProviderHttp.json`) now use the one reader of the area, and the JSON reader
  test keeps the same documents and the same assertions. **No test was weakened
  or deleted.**

### Not verified here (blockers)

* **No device, no emulator, no APK** (forbidden by `android/AGENTS.md`). The
  Android Keystore (a broken alias, the key rotation), the real OAuth round
  trip and the `MediaSession` trust predicate need a device. The Keystore is
  covered by a **seam** (`ProviderKeyStore`) that is unit tested with a fake;
  the device behaviour of the real Keystore is not. The **file layer** of the
  secure store is exercised on the host JVM with real files; the
  `noBackupFilesDir` filesystem of a device is not.
* The **real** Yandex `account/status` response and the real Spotify token
  endpoint are not exercised — the tests use `okhttp3.mockwebserver`.
* Whether a Yandex 401 is transient in practice is still unmeasured; the
  re-validation makes that question harmless, but it does not answer it.
* The **delivery** of the OAuth callback is pinned on the source of the Activity
  (an Activity lifecycle cannot be observed from a JVM test); the model side of
  the same contract is pinned behaviourally.
* The OAuth redirect scheme `nedotify://oauth/spotify` is **claimable by any
  other app** on the device (`AndroidManifest.xml:22-27`, no `autoVerify`).
  PKCE bounds the damage — the code cannot be exchanged without the verifier —
  but the login can be **denied**. A dedicated HTTPS App Link would need a
  domain the project does not own. **Recorded, not fixed** (a design note).

### Out of area (reported to the coordinator)

* `data/CatalogMatcher.kt:66-76` (A6) + `ui/MusicViewModel.kt` (A7) — **P3-20**:
  the Spotify catalogue import stores the *candidate's* metadata and discards
  the parsed catalogue metadata; the Yandex path keeps it
  (`data/CatalogProviders.kt:102`). The fix belongs in `CatalogMatcher.resolve`:
  the returned track must carry the catalogue's title/artist/album/cover and the
  candidate's source id.
* `data/DesktopLibraryConverter.kt:17-18` and `data/DesktopLibraryImport.kt:35`
  (A4) — the other half of **P3-71**: the `origin` trigger is unreachable from
  the UI and the reachable `require` (“В копии слишком много записей”) is
  swallowed by the catch-all.
* `data/MediaHttp.kt:154` (A2) — **the one failing test in the tree**:
  `MediaRedirectInterceptor.redirectRequest` compares only the **host**, so a
  hop to another **port** of the same host keeps the `Authorization` header
  (OkHttp's own rule is the whole origin: scheme + host + port,
  `HttpUrl.canReuseConnectionFor`). `MediaHttpTest.a hop to another host drops
  the authorization header` fails on it.
* `android/app/src/test/java/ru/nedotify/app/data/MediaWiringTest.kt:50` and
  `android/app/src/test/java/ru/nedotify/app/downloads/DownloadWorkerContractTest.kt:48`
  — **the whole build was blocked** by `File(root,File("src/main/java",path))`
  (a `File` where a `String` is required). The one-line repair
  (`File(root,"src/main/java/$path")`) was applied so that every area could run
  its tests; it changes no assertion.
* `ui/MusicViewModel.kt:372` (A7) — **not needed**: the durable exchange is
  reached through the existing `repository.providers.handleSpotifyRedirect(uri)`,
  because the exchange itself now runs in the application scope. A7 *may* switch
  to `repository.providers.exchangeSpotifyRedirect(uri)` (fire and forget) if it
  prefers not to await the exchange.
* `data/ProviderHttp.kt:57` (A2) — `ProviderHttp.json` has **no size seam**, so
  the provider path reads the body through `ProviderHttp.text(request,maxBytes)`
  and parses it in `data/ProviderPayload.kt` (A5) with the same bounds. If A2
  adds a `maxBytes` parameter to `ProviderHttp.json`, the mirror parser in
  `ProviderPayload` can go away and the two readers cannot diverge.
* **The arbitration pass** resolved that remark the other way round: the second
  reader is **gone**. `data/ProviderHttp.kt` is the transport only (`text`), and
  `data/ProviderPayload.kt` is the one reader of the area. A2 may use
  `ProviderPayload.json(network,request,maxBytes)` instead of adding a seam to
  a reader that does not exist any more.
* `ui/MusicViewModel.kt:469,471-474` (A7) — `handleSpotifyRedirect` refuses the
  callback in the offline mode (`requireOnline()`), so a login that arrives
  while the app is offline is spent without a word. The model keeps the pending
  login, so the user can start over, but the **browser tab** is lost.
* `android/PORTING_STATUS.md:89` (A8) — the text still says "AtomicFile в
  noBackupFilesDir"; the secure provider store now writes its records with its
  own `File`-based layer (`data/SecureProviderStore.kt:169-201`), because
  `android.util.AtomicFile` cannot be exercised by a JVM test. The names on the
  disk (`.bin`, `.bin.bak`) are unchanged. The other `AtomicFile` use
  (`data/LocalAudioMetadata.kt:36-37`) is untouched.
* `data/Sources.kt:21` (A2) — `SourceFailure` is the base of the two typed
  failures of the area (`ProviderCredentialUnavailableException`,
  `ProviderCredentialCorruptException`); the file was not changed.



## Area A3 - Settings, preferences and profile state (fix engineer log, 2026-10-20)

Status: **closed with residuals** (final pass: arbiter + repair engineer, after
the two independent reviews; the report of the pass is
`android/review/REMEDIATION_A3_FIX.md`). The suite of the whole app:
**602 tests / 1 failure / 0 errors / 0 skipped** — the one failure is
`SecureProviderStoreTest.an unavailable key and a damaged record are told
apart`, a test of **area A5** whose production code does not have the failure
type the test asks for yet; **every test of A3 is green**. (The area log of
the first pass quoted `files=67 tests=427 … skipped=1` — that figure was
stale, it was the state of the tree at that moment and the rest of the
difference comes from the parallel areas.) `:app:lintDebug` is green:
**0 errors, 17 warnings, 1 hint** — the same as the baseline, and none of the
warnings comes from a file of this area. No device, no emulator, no APK:
the repair of a corrupt file, the migration of the queue and the reset notice
are covered by JVM unit tests over **real files** (the JVM Okio backend of
DataStore), but the on-device behaviour of the notice is **not** verified.

### The one design change that carries items 1, 2 and 12

The settings were two independent DataStore files, read from thirteen places,
with a read-side fallback and no guarantee that a write ever reached the disk.
They are now **one preferences layer** (`data/PreferencesLayer.kt`) with one
creation path, one corruption policy and one reset signal.

| Piece | File | What it owns |
|---|---|---|
| the layer | `data/PreferencesLayer.kt` | one store per file per process (keyed by the **path**), the path of an existing install, the background read of the file, the **durable record of the pending resets** |
| the corruption policy | `data/PreferencesLayer.kt` | `ReplaceFileCorruptionHandler { emptyPreferences() }` for **every** file, plus the announcement of the reset |
| the reset signal | `data/PreferencesLayer.kt` | `PreferenceResets.pending` — the head of the queue, `PreferenceResets.pendingAll` — every pending notice, with `acknowledge()`; the notice carries an `id`, so two notices of the same file are two values |
| the record of the resets | `data/PreferencesLayer.kt` | `datastore/nedotify_resets` — the notice is written there **before** the repair is handed back, so it outlives the process |
| the settings | `data/Preferences.kt` | the settings file, **the queue file**, **the identity file**, the injection seam, the one shared snapshot, the one-time migration of the queue |
| the audio settings | `data/AudioSettingsStore.kt` | the audio file, the seam, the shared snapshot, the observable write failure, the cache limit |
| the profile draft | `data/ProfileSettings.kt` | the filter of the fields and the model's own message |

**The queue has its own file.** The verification required that the queue
snapshot must survive a corruption of the settings file, so the queue lives in
`nedotify_queue.preferences_pb`. The settings file keeps
`nedotify.preferences_pb` and the audio file keeps `nedotify_audio.preferences_pb`
— the paths an existing install already has, so the upgrade loses nothing. A
one-time migration copies the queue of an older install out of the settings
file and removes the old keys: the legacy `queue_v1` is still **read**, and it
is still removed by the first write, exactly as A1 left it. The migration is
**idempotent**: a process that dies between its two writes leaves the old
keys behind, and the next run removes them.

**The identity of the library has its own file.** The settings file is
replaced when it is damaged, and a new identity would turn the device's own
backup into another device's copy (`data/BackupMerge.kt` recomputes the
portable ids of the local rows with the local library id). The identity
therefore lives in `filesDir/nedotify_library_id`; the key of an older
install (`library_id_v1`) is read once and adopted into that file. The file is
read first and written only when it holds nothing: a read must not depend on
a successful write.

**The reset is announced, not silent — and the announcement is durable.** The
corruption handler publishes a `PreferenceReset` into the layer's signal and
writes it to the durable record **before** it hands the replacement back: a
process that dies in between must not lose the notice together with the
evidence. The channel is a **queue**: two damaged files are two losses, and
the second one must not replace the first. The settings screen shows every
pending notice (`ui/SettingsScreen.kt`); the snackbar of the reset **is**
wired (`ui/MusicViewModel.kt:175` + `:324-326`, `ui/MusicApp.kt:181-184`).

**The shared snapshot.** Each class is the only writer of its file, and the
writes of a class are serialised by **one mutex**, so the result of a write
is published in the order the file was changed and the snapshot cannot go
backwards. Every reader follows the same snapshot: a read that follows a
write never sees the value from before it, and the thirteen cold reads no
longer open a subscription of their own. The file is read once, in the
background, by the layer.

### Per finding

| Id | Outcome | Where |
|---|---|---|
| P1-02 (a corrupt file is never repaired; every write fails forever) | **fixed** — the handler replaces the file, the write path recovers, the reset is announced, and the queue is in its own file | `data/PreferencesLayer.kt:138` + `:163`, `data/Preferences.kt:55`, `data/AudioSettingsStore.kt:52` |
| REG P2-46 / A-6 (no single preferences authority, no injection seam) | **fixed** — both classes take a `DataStore` and share one snapshot | `data/Preferences.kt:55`, `data/AudioSettingsStore.kt:52`, `data/Preferences.kt:264` |
| P3-60 (a failed write leaves the optimistic draft on screen) | **fixed** — the failure is observable and the drafts roll back | `data/AudioSettingsStore.kt:70` + `:99`, `ui/AudioSettingsControls.kt:40` + `:42` |
| P3-61 (the dialog closes before the write; the control characters) | **data side fixed, widget out of area** — the model filters the fields and carries its own message; `ui/ProfileScreen.kt:144-153` (A7) must use `ProfileDraft` and keep the dialog open | `data/ProfileSettings.kt:33`, `:43`, `:72` |
| P3-68 (the confirm button clears the field before the save) | **blocked — out of area** (`ui/ConnectionsControls.kt:60`, A5) | — |
| P3-62 (the 750 ms progress write re-runs the whole settings scope) | **fixed** — the download list is read in a leaf composable | `ui/SettingsScreen.kt:63` + `:105` |
| P3-59 (a slow first emission falls back to 256 MB; `runBlocking` on the main thread) | **fixed** — the `runBlocking` is gone (`NeDotifyApp.kt` reads the settings in a coroutine); the limit of the file is applied by the streaming cache **only when the file has confirmed it**, so the default of 256 MB never passes for the choice of the user | `data/AudioSettingsStore.kt` (`cacheLimit`), `NeDotifyApp.kt` (the cache quota collector) |
| P3-03 (the one-shot message channel conflates) | **no change needed** — the verification itself records the impact as overstated; the channel is A1's | — |
| P3-100 (256 MB vs 500 MB; LRU only; no loudness normalisation) | **recorded, not changed** — a declared difference from the desktop; the product's limits are not changed unilaterally | `data/AudioSettings.kt:24` |
| P3-97 / P3-102 (no `ReportPeriod.YEAR`; calendar vs rolling; 7 state holders) | **recorded only** — a design opinion | `data/ProfileComponents.kt:25` |
| P3-35 / P3-64 (the avatar remove branch; no `AsyncImage` error painter) | **data side fixed** — `removeAvatar()` makes the branch reachable; the widget (`ui/ProfileScreen.kt:47`) and the painter (`ui/Design.kt:119`) are A7's | `data/Preferences.kt:136` |
| P2-46's companion (X-04: the `offline` flag is a theme field) | **kept as is** — the flag stays in the appearance block; the 13 reads are now cheap | `data/Preferences.kt:109` |
| REG P2-01 / P3-34 (the queue snapshot) | A1's; the contract of A1 (`savedQueue`, `queue_v2`, the legacy `queue_v1` read, `queueValues()`) is preserved and now lives in its own file | `data/Preferences.kt:33`, `data/Preferences.kt:160` + `:178` |
| P3-67 (the pending Spotify login) | **out of area** (`data/ProviderConnections.kt`, A5) | — |
| P3-84 (`returnDefaultValues`) | **out of area** (the build config, A8) | — |

### The second pass (arbiter + repair engineer, after the two reviews)

| Id | Outcome | Where |
|---|---|---|
| the announced reset is not durable (B1, R3) | **fixed** — the notice is written to `datastore/nedotify_resets` before the repair is handed back; the next launch shows it again | `data/PreferencesLayer.kt` (`ResetLedger`, `PreferenceResets.announceNow`) |
| the reset channel has one slot; `MutableStateFlow` conflates (B2, R4) | **fixed** — the channel is a queue and every notice carries an `id` | `data/PreferencesLayer.kt` (`PreferenceResets`, `PreferenceReset.id`), `ui/SettingsScreen.kt` (every pending notice is listed) |
| the library identity is destroyed by a settings corruption (B3) | **fixed** — the identity lives in a file of its own; the key of an older install is adopted into it | `data/Preferences.kt` (`libraryId`, `ensureIdentity`), `data/PreferencesLayer.kt` (`identityFile`) |
| `libraryId()` rewrites the file on every call (N1, R8) | **fixed** — the file is read first and written only when it holds nothing | `data/Preferences.kt` (`libraryId`) |
| the shared snapshot can regress (N2, R7) | **fixed** — one write path under one mutex in both classes | `data/Preferences.kt`, `data/AudioSettingsStore.kt` |
| an interrupted migration leaves a stale key forever (N3, R5) | **fixed** — the cleanup of the old keys happens in every case | `data/Preferences.kt` (`migrateQueue`) |
| the `confirmed` cache-limit flag has no production consumer (N5, R9) | **fixed** — the flag is honest and the streaming cache applies a limit only when it is confirmed | `data/AudioSettingsStore.kt`, `NeDotifyApp.kt` |
| a raw system exception message reaches the user (N6) | **fixed** — the notice carries the app's own message, the detail goes to the log | `data/AudioSettingsStore.kt` (`AUDIO_WRITE_FAILED_MESSAGE`) |
| the area log is inaccurate in four places (N7, R10) | **fixed** — this log was rewritten | this section |
| the on-disk name of the queue file is not pinned (N8) | **fixed** — the exact name of all three files is pinned | `data/PreferencesResetTest.kt` (`theQueueFileHasItsOwnNameOnDisk`) |
| the store cache is keyed by the file *name* only (N11) | **fixed** — the stores are keyed by the path of the file | `data/PreferencesLayer.kt` (`stores[file.absolutePath]`) |
| a valid file with a value of another type kills the read (R2) | **fixed** — the key is treated as absent, the file is announced and the offending key is removed | `data/PreferencesLayer.kt` (`Preferences.valueOrNull`), `data/Preferences.kt` (`announceMismatches`) |
| the queue of an older install is destroyed when the settings file is corrupt at the upgrade (R1) | **partly confirmed — the data loss is inherent, the notice is fixed** — a file that cannot be parsed cannot yield the queue; the notice of a damaged settings file now says that a queue that was still kept in it is lost with it | `data/PreferencesLayer.kt` (`PreferenceReset.detail()`) |
| a transient read error is sticky (R6) | **partly fixed** — the fallback is reported and the cache limit it produces is **not** marked as confirmed | `data/Preferences.kt` (`reportDiagnostic`), `data/AudioSettingsStore.kt` (`readFailed`) |
| the migration's `catch { Log.e(...) }` cannot be exercised in a JVM test (harness) | **fixed** — the diagnostic goes through an injectable sink, the pattern A2 used for the media policy | `data/PreferencesLayer.kt` (`PreferenceDiagnostics`, `PreferenceLog`, `reportDiagnostic`) |
| the warm-up read of the layer is discarded (N9) | **refuted** — the warm-up read warms the DataStore, whose flow is hot and shared: the first consumer's `first()` is a collection of that flow, not a second read of the disk | `data/PreferencesLayer.kt` (`of`) |
| an announced QUEUE reset contradicts the migration (N4) | **recorded, not fixed** — the message states the fact (the file was damaged and replaced); whether the queue was restored from the settings file afterwards depends on the order of two independent reads | `data/PreferencesLayer.kt` (`detail`) |
| the profile name bound is enforced by silent truncation (N10) | **recorded, not fixed** — the truncation is the model's own documented bound; the hint that would tell the user belongs to `ui/ProfileScreen.kt` (A7) | `data/ProfileSettings.kt` (`profileField`) |

### Tests

| File | Contract it pins | Fails on a revert |
|---|---|---|
| `data/PreferencesStoreTest.kt` | a corrupt file is a `CorruptionException` **and** the write is wedged (the premise); with the policy the read is repaired, the write works again and the reset is announced; the repair survives a restart; the queue survives a corrupt settings file; the queue of an older install is migrated out of the settings file and the old key is removed; **an interrupted migration leaves no stale key behind**; **a failed migration is reported and the queue is kept**; every setting is persisted and read back; the library identity is created once, **is not stored in the settings file and is not rewritten**, and **survives a corrupt settings file**; **a value of another type is treated as absent and announced**; **a failed write leaves the value alone**; **the shared snapshot does not regress under a concurrent write**; **the settings file has one write path** | yes — the store is built by the production `createStore` and the class under test is the production `Preferences`; **six mutations of the production code were run against the suite and each of them was caught** (the list is in `android/review/REMEDIATION_A3_FIX.md`) |
| `data/PreferencesResetTest.kt` | **the exact on-disk name of the queue file** (and of the two other files); **the notice survives a restart** and the acknowledgement clears the record; **two damaged files carry two notices**; **a second corruption of the same file is a new notice** (not conflated); one notice per file is enough | yes |
| `data/AudioSettingsStoreTest.kt` | a failed write is observable, the persisted value is untouched, a later success clears the notice, and **the message of the system is not shown**; the cache limit is not confirmed before the file answers and is unconfirmed while the file has not answered; a corrupt audio file is repaired and announced; **a value of another type in the audio file is treated as absent and announced** | yes |
| `data/ProfileSettingsTest.kt` | the draft filters the control characters the model refuses; the draft carries the model's own message; the message of `profileError` is the message of the model; the field filter keeps the bounds | yes |
| `data/SavedQueueTest.kt` (A1's, unchanged) | the current key wins, the legacy key is the fallback | — |

### Not verified here (blockers)

* **The tree did not compile when this pass started.** Area A4's pass was
  **interrupted** and left three compile errors in its own files; area A5
  left three in its test files. Six **compile-only** lines were repaired so
  that the suite could be run and the lint measured
  (`data/DesktopRows.kt`, `data/LibraryBackupStorage.kt`,
  `data/LibraryRepository.kt`, `data/BackupMergeTest.kt`,
  `data/ProviderConnectionsTest.kt`, `data/SecureProviderStoreTest.kt`).
  Those files belong to A4 and A5 and are **not** part of this area; the
  repairs are listed in `android/review/REMEDIATION_A3_FIX.md` and have to be
  reviewed by those areas (the signature of the fence of A4 in particular).
* **No device, no emulator, no APK** (forbidden by `android/AGENTS.md`).
  The repair was exercised on the JVM backend of DataStore over real files,
  which is the same `DataStoreImpl` and the same `ReplaceFileCorruptionHandler`
  as the platform backend, but the **atomic replace of the platform
  `FileStorage`** (API 26) and the on-device notice are **CANNOT VERIFY**.
* The **profile dialog** (P3-61) and the **avatar remove button** (P3-35) live
  in `ui/ProfileScreen.kt` (A7) and were not edited by this area. Both **are**
  wired (`ui/ProfileScreen.kt:52` and `:55`); the widget itself is A7's.
* The **snackbar of the reset** is wired (`ui/MusicViewModel.kt:175` + `:324-326`,
  `ui/MusicApp.kt:181-184`); it was not wired when the first pass of this area
  was written, and the log of that pass was wrong about it.
* A **read failure of the audio file** (an `IOException` that is not a missing
  file) cannot be produced on the JVM: the Okio backend answers a missing or
  unreadable path with the default. The path that keeps the limit unconfirmed
  is therefore not exercised by a test; it is exercised by the source.
* The **queue of an install whose settings file was already damaged before
  the first launch of this version** cannot be recovered: the bytes are gone.
  The notice says so.

### Notes for the next areas

* The preferences layer is the only place that creates a DataStore for the
  app. A new settings file belongs there, with its own `PreferenceFile` and
  its own entry in `PreferenceResets`.
* A file that is written by a class **must** publish the result of its write
  (`publish`) under the **one** mutex of the class: the shared snapshot is
  exact only because the class is the only writer of its file **and** its
  writes are serialised.
* A diagnostic of the layer goes through `PreferenceLog.diagnostics`, never
  through `android.util.Log` directly: the log is not implemented in a JVM
  unit test, and a sink that fails must never be a failure of the repair.
* A file that a corruption handler can replace must not hold the identity of
  the device: the identity lives in `filesDir/nedotify_library_id`.





## Area A4 — interrupted pass (2026-10-20)

The A4 fix engineer was cut off by an infrastructure restart while it was rewriting the backup
codec. The partial work was reconciled by hand so the tree compiles and the suite is green again:

* data/BackupCodec.kt — the org.json DOM was replaced by a **streaming** reader/writer
  (JsonReader, JsonWriter, JsonSize), so the peak heap of an import is the document plus the
  model instead of a DOM (REG P2-16). Two defects in the partial state were repaired:
  a **trailing-data check** was missing from decodeDocument (a document with bytes after the root
  object was accepted — BackupCodecTest caught it), and BackupFormatException could not extend
  the **final** SourceFailure.
* data/Sources.kt — SourceFailure is now open, so the codec can carry its own bare reason.
* data/DesktopLibraryImport.kt — the outer use { input -> … } was never closed, which made the
  rest of the class body a lambda body (every later member was reported as a local function);
  copyDocument is now a suspend fun so its ensureActive() has a coroutine context.

**What is still open in A4:** the identity/merge work (REG P2-20, P2-26, P2-14), the WAL sidecar
read (REG P2-21), the import tolerance and notice (REG P2-17, P2-18), the batched import
(P3-16), the quoted identifiers (P3-15), the library delete path (REG P2-31), the report window
and the history retention (REG P2-43, MAIN-P2-35), and the JVM-level guard for the Room
migrations (REG P2-53). **A4 must be re-run from the fix-engineer stage.**

---

## Area A8 - Build system, test infrastructure, review manifests and documentation (arbiter & repair pass, 2026-10-20)

Status: **closed with residuals.** The gate is green: `:app:testDebugUnitTest`
**604 tests / 0 failures / 0 errors / 0 skipped**, `:app:lintDebug` **0 errors,
2 warnings, 0 hints**, `:app:compileDebugAndroidTestKotlin` compiles. No APK, no
`assemble*`, no `bundle*`, no `package*` task was run; no device and no emulator
were used. The full log is
[android/review/REMEDIATION_A8_FIX.md](../android/review/REMEDIATION_A8_FIX.md).

### The findings, against the matrix

The ids below are the ones of `docs/audits/independent_verification/VERIFICATION_MATRIX.csv`.
The previous revision of this row named ids that mean something else (P3-85 is
"the APK path does not exist", P3-88 is "the APK ban is recorded
inconsistently", P3-89 is "verify.ps1 has no header block"; the stale-numbers
ids are P3-83/P3-92, not P3-83/P3-92 under other names; REG P2-53 is the
device suite that has never run, which belongs to A4).

| Id | Outcome | Where |
|---|---|---|
| REG P2-38 / REG P2-55 (the review manifest must be regenerated from a directory walk, must include `app/build.gradle`, must fail on any *unlisted* file, must not embed a machine-local path) | **fixed** - the manifest is written from a directory walk, holds relative paths with forward slashes, and `Read-ReviewManifest` *rejects* a machine-local path; the check reports four lists (new, changed, removed, unlisted) and fails while any of them is non-empty | `android/tools/SourceSnapshot.ps1`, `android/review/VERIFY.ps1` |
| REG P2-39 (the root documentation does not mention the Android product) | **fixed** - one paragraph in the root `README.md`, a scope marker in the root `AGENTS.md`, a scope marker in `STATUS.md` | `README.md`, `AGENTS.md`, `STATUS.md` |
| REG P2-40 (`android/AGENTS.md` protects `~/.nedotify`, a path that cannot exist on a device, and never names the device library) | **fixed** - the rule now names the device library (the Room database, the four DataStore files, the library identity, the offline packages, the Keystore store) and says that `~/.nedotify/` is the *desktop* profile | `android/AGENTS.md` |
| REG P2-41 (the review briefs are not renamed; there is no `review/README.md`) | **fixed** - `REVIEW_A.md`/`REVIEW_B.md` are now `BRIEF_A.md`/`BRIEF_B.md` (they are briefs, not reports) and `review/README.md` indexes the directory | `android/review/BRIEF_A.md`, `android/review/BRIEF_B.md`, `android/review/README.md` |
| REG P2-42 / REG P2-54 (the whole `android/` tree is untracked: `git ls-files android` -> 0) | **fixed** - `git add android/ .github/workflows/android-source.yml`; the tree is **staged**, not committed - the commit is the owner's decision | the git index |
| REG P2-72 (`verify.ps1` executed zero Gradle tasks when its output was captured) | **fixed** - the Gradle output goes to a unique log file, the script reads the log and returns Gradle's exit code; a captured run executes the tasks | `android/verify.ps1` |
| REG P2-76 (the release build type was a silent release) | **fixed and verified without an APK** - R8, the resource shrinker, the ProGuard files, the environment-driven signing config and the `.debug` suffix; read out of the effective AGP model and `:app:signingReport` | `android/app/build.gradle`, `android/tools/dump-variant-model.gradle` |
| REG P2-77 (the lint gate was a function of the network: 15, 13 and 4 warnings for the same source) | **fixed** - `lint { checkDependencies = false }` **plus** the three network-dependent detectors switched off by name in `android/lint.xml`, **plus** the separate non-blocking task `:reportNewerVersions`. Measured on AGP 9.1.1: `checkDependencies = false` alone does **not** remove them - the lint model is regenerated and the three detectors still fire | `android/build.gradle`, `android/lint.xml` |
| REG P2-79 (the SDK is inside the system temp dir; `local.properties` is the only channel) | **fixed** - the SDK lives in `%LOCALAPPDATA%\Android\Sdk` (outside the temp dir), the environment (`ANDROID_HOME`/`ANDROID_SDK_ROOT`) is the primary channel and `local.properties` the fallback; the ASCII junction is only a path alias | `android/tools/run-unit-tests.ps1`, `android/verify.ps1` |
| P3-83 / P3-92 (the artefacts quoted 217/17/55) | **fixed** - `TEST_SUMMARY.json`, `VALIDATION.md` and `SNAPSHOT.json` are generated by **one parse of one run**, so they cannot disagree; the generator refuses to publish a lint report that predates the sources | `android/tools/update-review.ps1` |
| P3-85 (the APK path does not exist and `verify.ps1` cannot produce one) | **fixed as a contradiction, not by building an APK** - `verify.ps1` is a source-only gate, the APK ban lives in `android/AGENTS.md`, and the allow-list rejects every packaging and device task by name before Gradle starts | `android/verify.ps1`, `android/tools/SourceTasks.ps1` |
| P3-88 (the APK ban is recorded inconsistently) | **fixed** - the ban is stated in one place (`android/AGENTS.md`) and enforced by the allow-list; the 2026-10-19 artefacts are marked as history in `android/review/README.md` | `android/AGENTS.md`, `android/review/README.md` |
| P3-89 (`verify.ps1` has no header block; the documented on-ramp dead-ends) | **fixed** - `verify.ps1` has a header that says what it does and does not do, and the README names both entry points | `android/verify.ps1`, `android/README.md` |
| REG P2-57 (five instrumented test files use the deprecated Compose test API) | **recorded, not changed** - a deprecation warning with no build impact (`compileDebugAndroidTestKotlin` is green, lint says nothing); the files are under `app/src/androidTest/**`, which is outside the file list of this pass | `app/src/androidTest/**/AppearanceControlsTest.kt`, `BackupControlsTest.kt`, `BrowseControlsTest.kt`, `NavigationTest.kt`, `ProfilePlayerComponentsTest.kt` |

### The second pass (arbiter + repair engineer, after the two reviews)

| Remark | Outcome | Where |
|---|---|---|
| B4 - the rewrite of `SourceSnapshot.ps1` broke the repository's own regression test (`tests/test_android_source_gates.py`: 3 failed, 4 passed) | **fixed** - the three expected messages now match the four drift kinds the script reports, the fourth case (`unlisted`) was added, and the test asserts that the report names the file that drifted. The detection still fails the gate in every case | `tests/test_android_source_gates.py` |
| B1/D1 - the CI job cannot run: neither `android/` nor the workflow file is in version control | **fixed** - both are staged; `git ls-files --cached android` returns the tree. Not committed: that is the owner's decision | the git index |
| B2/D3 - REG P2-77 is not fixed | **fixed** - see the table above. The stable gate is **0 errors, 2 warnings** (`ExportedService`, `UseKtx`), 0 hints; the 15 network-dependent warnings are out of the gate and are reported by `:reportNewerVersions` | `android/build.gradle`, `android/lint.xml` |
| B3 - the published lint figures come from a run that predates the last source change, and the generator cannot see it | **fixed** - the generator compares the lint report *and* the JUnit XML with the newest source file of the tree and refuses to publish when either is older | `android/tools/update-review.ps1` |
| B5/D4 - REG P2-39 is not fixed: the root documentation does not mention the Android product | **fixed** - see the table above | `README.md`, `AGENTS.md`, `STATUS.md` |
| D2 - the dependency-verification metadata is incomplete: a cold Gradle cache fails at configuration time | **fixed** - the metadata was re-recorded by Gradle itself on an **empty** `GRADLE_USER_HOME` with `--refresh-dependencies --write-verification-metadata sha256`; `guava-parent-33.3.1-jre.pom`, `junit-bom-5.10.2.module` and `junit-bom-5.11.0-M2.module` are now in it. The CI job gained a step that resolves the build with an **empty** Gradle home, because the verification runs at *download* time and a warm cache hides an incomplete file | `android/gradle/verification-metadata.xml`, `.github/workflows/android-source.yml` |
| N1 - REG P2-79 is not fixed: the SDK is still in the temp dir, `local.properties` is still the primary channel | **fixed** - see the table above | `android/tools/run-unit-tests.ps1`, `android/verify.ps1` |
| N2 - REG P2-40 is not fixed: `android/AGENTS.md` protects a host path and never names the device library | **fixed** - see the table above | `android/AGENTS.md` |
| N3/D5 - the summary generator produces an empty lint breakdown on Windows | **fixed** - the finding line is matched with a GREEDY path (the old pattern could not cross the `:` of the drive letter), and the generator now *refuses* to publish an empty breakdown next to a non-empty finding list | `android/tools/update-review.ps1` |
| N4 - the snapshot cannot see 11 files whose type is not in the source rules | **fixed** - the rule set now covers `.md .json .png .yml .yaml .txt .lockfile` and `.gitignore`, so `AGENTS.md`, `README.md`, `PORTING_STATUS.md`, `design/reference.png` and `settings-gradle.lockfile` are pinned | `android/tools/SourceSnapshot.ps1` |
| N5 - `:resolveLinuxAapt2` is allow-listed but does not exist | **fixed** - the task is removed from the allow-list; a task that does not exist must not be offered as a recovery command | `android/tools/SourceTasks.ps1` |
| N6 - REG P2-41 is not fixed | **fixed** - see the table above | `android/review/` |
| N7/D6 - `review/SNAPSHOT.json` still publishes 217/55/187 | **fixed** - the file is generated by the same run as the other two artefacts and carries the current facts | `android/tools/update-review.ps1` |
| N8 - the `PropertyEscape` suppression is global while the docs claim it is file-scoped | **fixed** - the suppression is now `<ignore path="local.properties"/>`, i.e. by file NAME (the report names the ASCII junction, a CI runner names its checkout), and `android/gradle.properties` is checked as usual | `android/lint.xml` |
| N10 - the tracker misattributes finding ids | **fixed** - this section was rewritten against the matrix | this section |
| N11 - the README overstates the lock state | **fixed** - `settings-gradle.lockfile` holds one line, and the README says so; the plugin classpath is pinned by the verification metadata, not by a lock entry | `android/README.md` |
| N12 - `check-catalog-lock.ps1` compares presence, not resolution; skips the BOM entries; is not part of `verify.ps1` | **fixed** - the check compares the version of every library with its lock entry, checks the six BOM-managed libraries by name, reports a module that is locked at several versions, prints the real counts, and now runs inside `verify.ps1` | `android/tools/check-catalog-lock.ps1`, `android/verify.ps1` |
| N13 - the CI's snapshot step is a trip-wire and is not documented | **fixed** - the workflow says so in a comment, and `android/README.md` explains the rule | `.github/workflows/android-source.yml`, `android/README.md` |
| N14 - every Gradle log opens with a rendered "NativeCommandError" | **fixed** - `JAVA_TOOL_OPTIONS` is no longer used; the ASCII temporary directory reaches the JVM through `TEMP`/`TMP` (on Windows the JVM takes `java.io.tmpdir` from them), so the JVM prints nothing to stderr | `android/tools/run-unit-tests.ps1`, `android/verify.ps1` |
| D7 - `verify.ps1` refuses to run after the SDK moves, while `run-unit-tests.ps1` re-points the alias | **fixed** - both scripts re-point the alias instead of throwing | `android/verify.ps1` |
| D8 - the root-level plugin classpath is not locked | **fixed** - the plugins are applied in the **root project**, so their classpath is locked there: uildscript { configurations.classpath { resolutionStrategy.activateDependencyLocking() } }, and the state is written to uildscript-gradle.lockfile (123 lines, including the plugin markers such as com.android.application:com.android.application.gradle.plugin:9.1.1). The catalog check now cross-checks the three plugin aliases against that file. Measured on the way: the settings script has **no** dependencyLocking() method in Gradle 9.3.1 ("Could not find method dependencyLocking() ... on settings"), and a uildscript {} block must precede the plugins {} block | ndroid/build.gradle, ndroid/buildscript-gradle.lockfile, ndroid/tools/check-catalog-lock.ps1 |

### The snapshot and the catalog

* `android/tools/SourceSnapshot.ps1` **reports** the drift - new, changed,
  removed and unlisted files - instead of stopping at the first difference, and
  `Read-ReviewManifest` rejects a machine-local path, so the manifest is
  portable by construction. `android/review/VERIFY.ps1` fails while the manifest
  is stale.
* `android/tools/check-catalog-lock.ps1` compares the version catalog with the
  lock state and fails when they disagree. It found exactly one disagreement:
  the catalog declared `androidx.core:core-ktx:1.17.0` while the lock state
  builds `1.18.0`. The catalog now says `1.18.0` - the version that is
  actually built - and the resolved graph is unchanged.
* The manifest is regenerated **last**, after every area has finished
  (`tools/update-review.ps1 -RefreshSnapshot`).

### The one code fix outside the area

`downloads/Downloads.kt` wrote the track row with `dao.remember(track)`, outside
the library write fence, so a deleted row could come back. The library area
added the fenced path in the same pass (`data/LibraryWrites.kt`,
`data/LibraryRepository.kt:201`) and the download path now uses it
(`downloads/Downloads.kt:53`). `data/**` was not touched here.

### Not verified here (blockers)

* No device, no emulator, no APK. The instrumented tests are **compiled**,
  never executed: 66 `@Test` methods in 17 files under `app/src/androidTest`.
* **The CI job has never run.** It cannot have: until this pass neither
  `android/` nor the workflow file was in version control. The job is now
  staged; its first real run is still ahead.
* The release variant was checked by its **effective AGP model**, not by a
  build: that R8 really runs, that the shrinker helps, that the ProGuard rules
  keep the reflective classes and that the signed APK installs are **not**
  verified.
* The live providers were not contacted (the network probe is opt-in); the
  MockWebServer tests do not prove that Spotify, Yandex or YouTube are reachable.
* The review artefacts of 2026-10-19 describe a tree of 187 files and are kept
  as history, not as evidence of the current tree (`android/review/README.md`
  says which file is which).

### Out of area (reported to the coordinator)

* `app/src/main/AndroidManifest.xml:29` (A1/A7) - the exported `PlaybackService`
  without a permission (lint `ExportedService`). It is a warning, not an error:
  the lint gate stays green with it.
* REG P2-57 - the deprecated Compose test API in five instrumented test files
  (see the table above).

Two findings of the first pass were repaired by their owners in the same pass:

* `ui/MusicViewModel.kt:254` (A7) wrote the track row with
  `repository.dao.remember(track)`, outside the fence; it now uses the fenced
  `repository.remember(track)`.
* `app/src/test/java/ru/nedotify/app/data/LibraryWriteFenceTest.kt` and
  `LibraryWritesTest.kt` (A4) construct `LibraryWrites`, which gained the
  fourth `keep` lambda; both test files pass it now.
