# RECOMMENDED FIX ORDER

Built **only** from findings this verification confirmed (or confirmed
conditionally). Items whose original rationale was refuted are listed
separately in §4 and must **not** be implemented as written. **No code was
changed by this verification.**

Ordering principle: fix the thing that lets everything else regress first,
then fix the things that destroy user data, then the things that break a
feature, then the surface.

---

## 0. The one decision that changes the plan

The original remediation plan's **wave W1** and its Appendix-A "highest-value
single change" (`R1.1`, the `PendingSelectionGate` intent token) rest on a
Media3 claim that the pinned Media3 1.11.1 bytecode **refutes**:
`MediaController.play()` and `pause()` *do* reach
`MediaSession.Callback.onPlayerCommandRequest`, and they arrive as
`Player.COMMAND_PLAY_PAUSE` — which is exactly the constant the app checks.
See `FALSE_POSITIVES.md` FP-1.

**Consequence.** `R1.1` as written would replace a boolean latch whose
re-arm path *works*, while leaving the real defect — a **silent veto** — in
place. Two of the four defects `R1.1` claims to remove (`P2-12`, `P2-13`) are
real and should still be fixed; the "the play button is dead" claim is not.

**Do not execute R1.1 as written.** Execute **R1.1′** below instead.

---

## 1. W0 — Make the gate real (do this first; it is cheap and it changes the economics of everything after)

| # | Action | Why it is first | Evidence |
|---|---|---|---|
| **1.1** | `git add android/` (the `.gitignore` already excludes exactly the right things) | Every other fix in this list is unreviewable, unbisectable and unrevertable until this is done. It is also the pre-condition for the CI job. | `git ls-files android` → 0; 193 untracked files |
| **1.2** | Regenerate `android/review/SOURCE_SHA256.txt` from a **directory walk**, include `app/build.gradle`, and make `VERIFY.ps1` also fail on any *unlisted* file | The current manifest is an allow-list that certifies a tree that no longer exists (160 match / 27 differ / 0 missing; 8 files unlisted) | REG P2-55, P2-38 |
| **1.3** | Fix `verify.ps1` so it does not abort when its output is captured | The project's only sanctioned entry point executes **zero** Gradle tasks in every CI/agent context. Today it silently "verifies" nothing. | REG P2-72 (executed) |
| **1.4** | Give the **desktop** a non-destructive "dup cleanup": merge duplicates into the survivor instead of `DELETE`ing them; snapshot first (`VACUUM INTO`); make the block atomic; log at WARNING; replace the one-shot boolean with a versioned migration record | Unrecoverable, silent, unattended loss of listening history and playlist membership. It is the only *data-loss* defect in the whole set. | P0-01 (confirmed at runtime) |
| **1.5** | Ship a corrective migration that restores from a backup table where one exists, and state plainly that for users who already ran the destructive migration the history is unrecoverable | The damage is already done for everyone who ran v2.0.0+ (2026-08-13). | P0-01 |
| **1.6** | Fix the desktop's `playlist_tracks` cleanup so it can never remove a **surviving** track's playlist entry | The second statement groups by `LOWER(title), LOWER(artist)` *within a playlist* and keeps `MIN(playlist_tracks.id)`; it can strip a track that survives. | P0-01, arbiter reproduction #2 |

**Acceptance for 1.4–1.6.** A synthetic DB with same-title/same-artist rows
differing by album, source, file_path, case and NULL artist comes out of the
migration with: no distinct recording deleted, every surviving track still
in its playlists, every history row still present, and a log line naming what
was touched.

---

## 2. W1 — The play path (revised from the original W1)

| # | Action | Defects it removes | Note |
|---|---|---|---|
| **2.1 (R1.1′)** | **Make the gate's refusal observable.** When `canStartPlayback()` is false, send a `SessionError` on the existing `onFocusDenied` channel and/or `invalidateState()`. Do **not** replace the boolean with an intent token yet — the re-arm path works. | the real kernel of REG P2-11 | The original R1.1 premise is refuted; this is the defect that survives. |
| **2.2** | **Stop cancelling the pending queue set on an interruption.** `interruptPending()` should close the gate without cancelling the `onSetMediaItems` future; the service should keep the resolved items and install them paused. | REG P2-12 | Independently confirmed by two verifiers at bytecode level (`Util.transformFutureAsync` / `Util.postOrRunWithCompletion` skip the install runnable for a cancelled future). |
| **2.3** | **Report the abandonment.** `resolveFuture`'s `CancellationException` branch must send a `SessionError` (or set a UI message) instead of swallowing it. | REG P2-12 (the silent half) | The user's selection is currently destroyed with zero feedback. |
| **2.4** | **Separate focus events from user interactions.** `AUDIOFOCUS_LOSS_TRANSIENT` and `pauseForReason` (becoming-noisy, permanent focus loss) must not call `onUserInteraction()`. `PlaybackFocusState.transientLoss()` already models the intent as preserved. | REG P2-13, P3-10 | `interactionVersion` guards the restore, the autoplay append and the offline refresh — the split must keep a per-request version that advances on **real** user actions. |
| **2.5** | **Never hand-build a `MediaItem` for the live queue.** `removeDownload` and `attachLocalFile` build `MediaItem.Builder().setMediaId(id).build()` — no URI, no metadata. Media3 1.11.1's `MediaSession.Callback` has no `onReplaceMediaItems`, and `DefaultMediaSourceFactory.createMediaSource` does `Preconditions.checkNotNull(mediaItem.localConfiguration)` → NPE. | the unnamed P1 in `REMEDIATION_PLAN.md` R1.2 | This finding exists **only** in the plan and in the W1 row of the main report; it has no P-id anywhere. |
| **2.6** | **Give the media path its own HTTP client** (no 30 s *total* call budget), and use it for `DownloadStorage.factory` **and** `PlaybackService`'s `OkHttpDataSource.Factory`. | P1-04 (and the *larger* streaming consequence the audit did not report) | `OkHttpDataSource.open()` uses a blocking `Call.execute()`, so the 30 s budget also bounds the media read. |
| **2.7** | **Re-validate a Yandex credential before deleting it.** On a 401, call `account/status` first; delete only if that also fails. | P1-03 | The current handler fires on any 401 from any Yandex call. |
| **2.8** | **Repair, do not merely detect, a corrupt preferences file.** Pass `ReplaceFileCorruptionHandler { emptyPreferences() }` to both delegates and announce the reset. | P1-02 | The write path re-throws the cached read failure forever (confirmed at bytecode level). |

---

## 3. W2 — Data durability and honesty

| # | Action | Defects it removes |
|---|---|---|
| **3.1** | **Type the queue snapshot** (`data/QueueSnapshotCodec.kt`), separate the queue *identity* from the *position*, and persist the position on a slower cadence. | REG P2-01, X-02, P3-34, A-1 |
| **3.2** | **Bound the backup's heap cost** and convert `OutOfMemoryError` into a `SourceFailure`. | REG P2-16 — **RAISED to P1**: re-measured at **183 MB** of live heap (not "120 MB"), against a typical 128–192 MB per-app limit. A routine "import backup" kills the app. |
| **3.3** | **Split the encoder's and decoder's error prefixes** and decide explicitly whether the 20 000-track cap is a product limit. | REG P2-15 |
| **3.4** | **Make the report's two comparison windows the same length.** | REG P2-43, MAIN-P2-31 |
| **3.5** | **Make the desktop import's losses visible** — per-row tolerance, a column-presence check, a notice line, and a machine-specific library identity. | REG P2-17, P2-18, P2-19, P2-20, P2-21, P2-25, P2-26 |
| **3.6** | **Reconcile the cross-platform identity model** so a cross-device restore does not duplicate local tracks, and add the missing delete path for the library. | REG P2-14, P2-26, P2-31, X-05, A-7, A-9 |

---

## 4. W3 — Network and provider correctness

| # | Action | Defects it removes |
|---|---|---|
| **4.1** | **Give the streaming cache a stable identity** (a `CacheKeyFactory` keyed on the track id, mirroring `downloadCacheKey`), and honour `ResolvedStream.expiresAt` in the download path. | REG P2-47, P2-49, X-03 |
| **4.2** | **Check the download's completeness before publishing `complete`** — keep the provider's declared total, compare it with the received bytes, and apply a minimum-size floor. | REG P2-50 |
| **4.3** | **One media-URL policy**: https + a per-source host allow-list, re-applied to every redirect hop. | REG P2-52, P3-24, P3-30 |
| **4.4** | **Send the headers the CDNs expect** (a stable UA; a per-source `Referer`), and surface a 401/403 from the media path as a session error. | REG P2-51, P3-22 |
| **4.5** | **Make the resolution cascade fall back** to the other provider under one shared wall-clock budget, with the identity gate applied to the fallback. | REG P2-48 |
| **4.6** | **Keep the provider's error classification** — carry `httpCode` out of the import loop and out of `CatalogMatcher.resolve`. | REG P2-62, P2-58, P2-17 |
| **4.7** | **Give the local search task its own budget**, separate from the 6.5 s network budget, and add an index on `addedAt`. | REG P2-59 |
| **4.8** | **Run the provider bodies on `Dispatchers.IO`** (search and catalogue paths). | REG P2-60, P2-61 |
| **4.9** | **Move the catalogue import into a WorkManager job** with persisted per-item progress, bounded concurrency and a cancel affordance; stop `importing` from silently freezing the whole catalogue. | REG P2-08, P2-74, MAIN-P2-40 |
| **4.10** | **Make the download state machine a type** and give removal its own terminal state and control. | REG P2-29, P2-30, P3-75, A-8 |
| **4.11** | **Fix the lyrics identity layer** — artist-conditioned prefix rule, artist *intersection* instead of superset, the base-recording fallback, and a real failure channel. | P1-01, REG P2-66, P2-67, P2-68, P2-71, P3-78, P3-79 |
| **4.12** | **Derive one global lyrics deadline** and pass it down; run the providers concurrently under it. | REG P2-69, P2-70, MAIN-P2-29 |
| **4.13** | **Pin the JSON semantics** the production code depends on (one `optText` helper, or one parser facade). | REG P2-73, P2-22, MAIN-P2-28 |

---

## 5. W4 — Establish the gate (run in parallel with W1–W3)

| # | Action | Defects it removes |
|---|---|---|
| **5.1** | **Make the 59 device tests actually run** — an opt-in `:app:connectedDebugAndroidTest` step plus an emulator job in CI. **Requires a one-off explicit user grant**, because it needs an APK. | REG P2-53 (raised to **P1**), P3-91 |
| **5.2** | **Commit `android/app/schemas/`** so the Room migration fixtures are versioned; add a check that the current schema has not drifted. | REG P2-54 |
| **5.3** | **Give the orchestration layer a test seam** (a `PlayerGateway`, a `LibraryGateway`, a `DownloadScheduler`; shared `stillCurrent` predicates). | REG P2-75, P3-90, P3-36, A-5 |
| **5.4** | **Make the build hermetic** — a version catalog, dependency locking, `verification-metadata.xml`, and a separate non-blocking "newer version available" task. | plan-only P2-77, P2-78; P3-82, P3-86, plan-only P3-113, P3-114 |
| **5.5** | **Add a `release` build type** with R8, a `proguard-rules.pro`, a `signingConfig` from environment properties and an `applicationIdSuffix` for `debug`. | plan-only P2-76 |
| **5.6** | **Install a Coil `ImageLoader`** with explicit timeouts and a response-size cap. | plan-only P3-112 |
| **5.7** | **Move the SDK out of the system temp dir** and stop relying on the globally shared `local.properties`. | plan-only P2-79 |
| **5.8** | **Migrate the five Compose test files to the v2 API** — but only in the same change that first makes the suite runnable. | REG P2-57, P3-93, P3-94, P3-95 |
| **5.9** | **Regenerate `VALIDATION.md` / `TEST_SUMMARY.json` from the real XML** and fix the 217-vs-236 and 55-vs-59 figures. | P3-83, P3-92, P2-55 |

---

## 6. W5 — The remaining surface

Grouped by theme, all confirmed:

* **Queue / player UI** — REG P2-33, P2-34, P2-35; MAIN-P2-41; P3-46, P3-47, P3-48, P3-49, P3-50, P3-52.
* **Search / library state** — REG P2-31, P2-32, P2-64; P3-14, P3-26, P3-27, P3-28, P3-54, P3-55.
* **Theme / layout / navigation** — MAIN-P2-37, MAIN-P2-39, MAIN-P2-40; P3-37, P3-39, P3-41, P3-42, P3-43, P3-45.
* **Settings / profile** — P3-58, P3-59, P3-60, P3-61, P3-62, P3-63, P3-65.
* **Connections / auth UX** — MAIN-P2-42; P3-66, P3-67, P3-68, P3-69, P3-70.
* **Player / focus / lifecycle** — REG P2-09, P2-10; P3-05..P3-12, P3-103..P3-110.
* **Desktop import / backup** — REG P2-19, P2-22; P3-15, P3-16, P3-71..P3-74, P3-101, P3-102.
* **Discovery / reports** — REG P2-07, P2-44, P2-45; MAIN-P2-34, MAIN-P2-35; P3-32, P3-33.
* **Accessibility** — P3-42, P3-43, P3-69, P3-70.
* **Documentation / process** — REG P2-39, P2-40, P2-41, P2-42; P3-84, P3-85, P3-87, P3-88, P3-89, P3-96..P3-100.

---

## 7. Unconfirmed high-risk hypotheses — **do not implement as written**

These are the original audit's high-risk claims that this verification did
**not** confirm as stated. They are listed so that nobody "fixes" a
non-existent defect, and so that the remaining uncertainty is explicit.

| Original claim | Status | What to do |
|---|---|---|
| "The `PendingSelectionGate` play button is dead until the user re-picks a track" (the report's #1 Android finding; `R1.1`; `A-2`) | **REFUTED** at the bytecode level | Do **not** build the intent-token replacement on this premise. Build **2.1** (the observable refusal) instead. |
| REG P2-10 — "an in-place `MediaItem` replacement splits one listen into two sessions" | **REFUTED** at the bytecode level | No product change is required. Keep only the small `explicitQueueBoundary` hygiene item (P3-05). |
| "A 403 on the first byte" for the media request (REG P2-51) | **NOT REPRODUCED** — the repo's own probe shows the SoundCloud CDN serving 200/206 to the same header-less client | Treat as a risk, not a defect. Fix the headers anyway (4.4) — it is cheap. |
| "The local search exceeds the 6.5 s budget" (REG P2-59) | **NOT REPRODUCED at the scale quoted** — re-measured worst case 0.89 s for 20 000 rows; the corpus's own later Addendum-3 measurement puts the crossover at 35 000–40 000 tracks and **promotes the same defect to P1** (REG P1-05) | Fix the budget coupling and add the `addedAt`/FTS index (4.7) — the corpus's P1 promotion is justified and this verification's independent measurement agrees. |
| "the lyrics are **never** found for 'Artist - Song' tracks" (P1-01) | **OVERSTATED** — a live LRCLIB probe shows `/api/get` **echoes** the prefixed title, so the candidate is accepted and the lyrics *are* found. The defect is confirmed only for **non-Latin scripts** and for the **sentinel-artist SAF import**; the audit's YouTube trigger is refuted (music.youtube.com returns bare titles) | Fix the artist-conditioned prefix rule (4.11) — it is still a real parity gap, but measure the population before sizing the work. |
| "The catalogue browser silently ignores every input during an import" (REG P2-74) | **OVERSTATED** — the UI *disables* the query field, the buttons and the rows and shows a progress bar with a live counter; the ViewModel guards are belt-and-braces behind it | The defect that survives is that the catalogue is **unusable for up to ~2 h 47 m** with only a progress line and no cancel. Fix it (4.9); do not describe it as a silent no-op. |
| "The streaming cache's bytes are never read again" (REG P2-47) | **OVERSTATED** — within a signed URL's lifetime (~14 min for SoundCloud/YouTube) the cache *is* re-read; what is true is that every re-resolution orphans the previous spans | Fix the identity (4.1); do not describe the cache as entirely inert. |
| "The user can never download a normal-sized Яндекс track" (REG P2-49) | **NOT ESTABLISHED** — every retry re-resolves and obtains a *fresh* signed link; the CDN's real TTL was never probed | The defect that survives is that the download cache key is unstable across resolutions, so a retry restarts from zero. Fix the key (4.1); do not claim the track is undownloadable. |
| "Every transport/queue command cancels the pending preparation" (REG P2-65) | **OVERSTATED** — `shuffle()` and `repeat()` do **not** cancel, so two of the six transport buttons already behave correctly | Fix it (4.9/§6); note that the two commands that already behave correctly are the reference for the fix. |
| "The `queue_v1` / `"version":2` mismatch" | **CONFIRMED** but P3 | Fold into 3.1. |
| P2-46's "12 cold DataStore reads" | the real numbers are **10 cold + 3 + 1 = 14**, and a cold `.first()` is a *collection of a shared hot flow*, not a disk read | Use the real numbers in any ticket; the structural fix (3.1/§6) is still right. |
| P2-73's "53 of 55 call sites" | the real number is **67**, of which **65** are uncompensated | The exposure is *larger*; fix it (4.13). |
| P2-75's "1 219 LOC" | the real figure is **1 438** (the register's own per-class numbers) / **1 469** measured | The gap is larger; fix it (5.3). |
| P3-90's "35 files / 3 977 LOC / 54.6 %" | not reproducible: **38 / 4 618 / 63.4 %** (strict) | The gap is larger; fix it (5.3). |
| P0-01's "the cause is a display-identity key" | **REFUTED** — `(title, artist)` is the app's own identity | Do not "fix" the key; fix the *operation* (1.4). |
| P0-01's "the playlist entries are lost by the cascade" | **REFUTED** — the explicit statements do the bulk of it, and they can also strip a **surviving** track's entry | Fix statement 2 (1.6). |
| P2-14's "the track cannot be removed" / P2-31's "the library grows" | confirmed, but the fix is a *product* decision (add a delete path) | Schedule it (3.6); do not treat it as a one-line fix. |
| P2-25 (read-only WAL on API 26) | **CANNOT VERIFY** without an API-26 emulator | Keep as a hypothesis. |
| All instrumentation-dependent behaviour (MediaSession lifecycle, foreground service, Keystore, audio, Room migrations on device) | **NOT VERIFIED AT RUNTIME** — no device, no APK (forbidden) | Do not claim these are fixed. 5.1 is the only way to know. |

---

## 8. Two constraints that shape the whole plan

1. **The project forbids APK builds** (`android/AGENTS.md`). Items **5.1** and
   anything that needs `assembleDebug` require a **separate, explicit user
   grant**. This verification did not request or use one, and did not run
   any `assemble*` / `bundle*` / `package*` task.
2. **`~/.nedotify/` is the user's library.** Item **1.4** and every fix in the
   backup/desktop area must be exercised against **synthetic** databases
   only, exactly as this verification did.
