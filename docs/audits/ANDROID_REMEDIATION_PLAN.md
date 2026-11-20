# NeDotify — Prioritised Remediation Plan

**Derived from:** `docs/audits/FULL_PROJECT_AUDIT.md` (full report) and
`docs/audits/ANDROID_FINDINGS_REGISTER.md` (the P2 evidence register).
**Date:** 2026-10-19.
**Scope:** 1 P0, 5 P1, 81 P2, 116 P3, 6 cross-module findings, 10
architectural improvements.

**No code was changed during the audit.** This plan is a proposal; executing it
requires explicit permission, and two items (W4.1, W4.2) require a separate
explicit grant because they conflict with the standing "no APK" rule.

---

## 0. How to read this plan

Each item has: **ID** · **priority** · **what** · **why** · **where** ·
**how** (the fix in one paragraph) · **done when** (the acceptance criterion) ·
**blocks** / **blocked by**.

Two rules govern the whole plan:

1. **Do not fix a state-machine defect by patching its symptom.** P2-11,
   P2-12, P2-13 and R1.1 are four presentations of one design error. Fixing
   them separately will re-introduce them.
2. **Re-run the gate after every wave.** The JVM suite (236 tests, green) is
   the only automated signal the port has, and it covers 46 % of the
   production code and none of the device-only surfaces.

**Verification commands** (the sanctioned path, no APK):

```powershell
cd android
& ".\verify.ps1" -Tasks @(':app:testDebugUnitTest','--rerun')
& ".\verify.ps1" -Tasks @(':app:lintDebug')
& ".\verify.ps1" -Tasks @(':app:compileDebugAndroidTestKotlin')
```

> **Tooling trap.** `verify.ps1` sets `$ErrorActionPreference='Stop'` and
> exports `JAVA_TOOL_OPTIONS`, so under Windows PowerShell 5.1 the JVM's
> `Picked up JAVA_TOOL_OPTIONS: …` banner on stderr becomes a terminating
> `NativeCommandError` **whenever the output is captured** (`2>&1`,
> `| Tee-Object`, `*>$null`, any CI harness). The script then exits 1 having
> executed **zero** Gradle tasks. Run it **without** redirecting stderr, or fix
> it first (item R4.3).

---

## W0 — Stop the bleeding (do this first, hours not days)

### R0.1 — The desktop app's destructive startup migration [P0-01] 🔴

* **Where:** `core/database.py:313-362`
* **What:** a one-shot startup migration deletes tracks and, through the
  foreign keys, cascades away their listening history and playlist entries.
* **Why:** users of the shipped desktop build are losing data on upgrade.
  This is the only finding that is not about the Android port, and the only
  one that is actively destroying data in the field.
* **How:** read the migration's intent; make it idempotent and non-
  destructive — deduplicate by *keeping* one row and re-pointing the
  references, or by marking duplicates rather than deleting them. Add a
  regression test that asserts a library's row counts before and after the
  migration are equal.
* **Done when:** the desktop test suite has a case that runs the migration
  against a fixture with duplicate tracks and asserts that no track, history
  row or playlist link disappears.
* **Blocks:** nothing. **Blocked by:** nothing. **Do it today.**

### R0.2 — Put `android/` in version control [P2-42, P2-54]

* **Where:** the repository root; `android/.gitignore` already excludes
  `.gradle/`, `.kotlin/`, `**/build/`, `local.properties`, `*.jks`,
  `*.keystore`, `captures/`.
* **What:** `git ls-files android` returns **0**. 193 untracked files,
  3 289 905 bytes. There is no history, no blame, no bisect, no review trail.
  The Room schema history (`1.json`, `2.json`) — irreproducible by any build
  task, since KSP exports only the *current* schema — exists in exactly one
  place.
* **How:** `git add android/` then commit. Verify with
  `git check-ignore -v android/local.properties` (must show
  `android/.gitignore:4:local.properties`) before committing, so the
  machine-local SDK path is not captured.
* **Done when:** `git ls-files android | Measure-Object` > 0, and
  `git log --oneline -- android` shows the baseline commit.
* **Note:** the first commit is large and will surface the current tree as the
  baseline. Say so in the commit message — "no prior Android history" is
  expected.

### R0.3 — Regenerate the review snapshot and make it verifiable [P2-38, P2-55]

* **Where:** `android/review/SOURCE_SHA256.txt`, `android/review/VERIFY.ps1`
* **What:** the manifest is stale (160 match / 27 differ / 0 missing), 7
  source files are absent from it, `app/build.gradle` is absent (it declares
  `minSdk 26`, `compileSdk/targetSdk 37` and every dependency version), and
  `VERIFY.ps1` iterates manifest lines only — so it can never detect a file
  that is *missing* from the manifest. `app/src/androidTest/.../LocalArtworkTest.kt`
  is in none of the seven manifests.
* **How:** regenerate the manifest from a directory walk, not a hand-kept
  list; include `app/build.gradle`; add a reverse check to `VERIFY.ps1` that
  fails when any file under `app/src` is unlisted. Delete the byte-identical
  `PRE_AUDIT2_*` duplicates (P2-42).
* **Done when:** `cd android\review; & .\VERIFY.ps1` exits 0 **and** fails
  when a file is added to `app/src` without regenerating.
* **Depends on:** R0.2 (a commit id supersedes the manifest as the anchor).

---

## W1 — Unbreak the play path

### R1.1 — Replace the boolean latch with an intent token [P1, XI-08 B] 🔴

* **Where:** `player/PendingSelectionGate.kt:12-30`,
  `player/PlaybackService.kt:85-88`, `player/DualDeckPlayer.kt:230-232`,
  `ui/MusicViewModel.kt:174-179`
* **What:** `playAllowed` is set `true` in exactly two places — `begin()` (a
  new queue set) and `receivedPlayCommand()`. The service re-arms it only
  from `MediaSession.Callback.onPlayerCommandRequest` when
  `playerCommand == COMMAND_PLAY_PAUSE`. **In Media3 1.11.1 that callback is
  never invoked for `MediaController.play()`/`pause()`** — only
  `setPlayWhenReady` dispatches through the queued path. `MusicViewModel.toggle()`
  calls `it.play()`/`it.pause()`. So `receivedPlayCommand()` is unreachable
  from the app's own transport, and once `playAllowed` is `false` the play
  button is dead until the user re-picks a track.
* **Also produces:** P2-11 (the refused Play has no error and no state
  change), P2-12 (the same interruption cancels the in-flight queue set, so
  the tapped track is silently discarded), P2-13 (a transient audio-focus
  loss is reported as a "user interaction" and cancels the startup restore).
* **How:** replace the boolean with an explicit intent token (a one-shot
  object, like `PlaybackPreparation.generation` but owned in one layer) and
  separate the two intents:
  - "the user changed the **queue**" → cancels a pending queue *build*;
  - "the user changed the **playback state**" → cancels a pending *play
    intent*, not the queue build.
  `interruptPending()` must not cancel the `onSetMediaItems` future, and the
  gate must be re-armed from a path the app actually uses.
* **Done when:** a JVM test drives `PendingSelectionGate` through
  begin → interrupt → play and asserts (a) the set future is still
  installable, (b) the play is refused, (c) a subsequent play is accepted;
  and an instrumentation test asserts that a Pause during a queue load leaves
  the new queue installed but paused.
* **Side effects to manage:** keeping the queue build alive across a pause
  means the service may install a queue the user has "paused away from" —
  the pending-set and pending-play cancellations need two tokens, not one.
* **Also:** wire the refusal into the existing feedback channel
  (`session.sendError`, the same path the focus-denial branch uses), so a
  refused play is not silent.

### R1.2 — Never build a queue item by hand in the UI layer [P1, XI-01 A / XI-05 B] 🔴

* **Where:** `ui/MusicViewModel.kt:196-198` (`removeDownload`) and
  `:208-223` (`attachLocalFile`); `player/PlaybackService.kt:325-332`
  (`mediaItem`), `:233-256` (`refreshQueueSources`)
* **What:** both call `player.replaceMediaItem(index, MediaItem.Builder().setMediaId(id).build())`
  — a `MediaItem` with **no URI and no `MediaMetadata`**. `MediaSession.Callback`
  in Media3 1.11.1 has **no** `onReplaceMediaItems` hook, so the item is
  applied to the session's player as-is. `DefaultMediaSourceFactory.createMediaSource`
  then does `Preconditions.checkNotNull(mediaItem.localConfiguration)` → NPE.
  Worse, `attachLocalFile` changes neither the offline flag nor the
  `offline_downloads` table, so the only re-builder of queue items is never
  triggered — the damage is **permanent** for that queue slot.
* **How:** never hand-build a `MediaItem` for the live queue. Express the
  intent as a *state* change (delete the `offline_downloads` row / update
  `tracks.localUri`) and let the service's reconcile observe it, or extend
  `refreshQueueSources` to a targeted, id-scoped refresh that builds the
  replacement with `PlaybackService.mediaItem(track, saved)`.
* **Done when:** a test attaches a local file to a queued track and asserts
  that the queue item still carries a URI and a title, and that the track
  plays from the new file.
* **Related:** R3.4 widens the reconcile's trigger set so this class of
  staleness cannot recur.

### R1.3 — Give the download path its own HTTP deadline [P1-04] 🔴

* **Where:** `data/Sources.kt:22-23` (`MusicNetwork`), `downloads/DownloadStorage.kt:23-29`
* **What:** one `OkHttpClient` with `callTimeout(30, TimeUnit.SECONDS)` serves
  both the interactive API and the bulk byte transfer. OkHttp's `callTimeout`
  bounds the **entire** call including reading the body. A progressive file is
  fetched in one call, so any transfer slower than ~30 s is aborted with
  `InterruptedIOException("timeout")` — which the worker classifies as a
  plain `IOException` and therefore as **retryable**, with the message
  "Соединение прервано. Загрузку можно продолжить" (a wrong diagnosis: the
  network did not break, the client aborted). The retry budget is 4 attempts
  ≈ 120 s of total transfer, so a 100 MB track on a 300 KB/s link can
  **never** complete.
* **How:** give the downloader its own client derived from the shared one with
  the total deadline removed —
  `network.http.newBuilder().callTimeout(0, TimeUnit.MILLISECONDS).build()` —
  keeping `readTimeout` as the stall guard, or move the deadline onto the
  metadata calls that actually need it.
* **Done when:** a JVM test with a `MockWebServer` that trickles a body for
  > 30 s completes the download.
* **Side effect:** without a total deadline a stalled server can hold one of
  the two download slots indefinitely. `readTimeout` bounds idleness but not a
  trickling body — a generous cap (e.g. 10 min) is the compromise.

### R1.4 — Do not destroy a Yandex credential on a single 401 [P1-03] 🔴

* **Where:** `data/ProviderConnections.kt:187-191`
* **What:** a 401 from any Yandex API call clears the stored credential. A
  transient 401 (a race between two concurrent calls, a clock skew, a
  momentary server hiccup) permanently logs the user out, with no recovery
  path and no distinction between "the token is wrong" and "the request was
  rejected once".
* **How:** treat a 401 as "the token is invalid" only after N consecutive
  failures or after a fresh-token exchange also fails; on a single 401, retry
  once and then keep the credential but mark the connection as needing
  re-authentication.
* **Done when:** a test drives one 401 and asserts the credential survives and
  the connection state reads "needs re-auth"; a test drives two consecutive
  401s and asserts the credential is cleared.
* **Related:** R3.3 narrows the provider mutex, which is what made this
  reachable in the first place.

### R1.5 — Repair, do not merely detect, a corrupt preferences file [P1-02] 🔴

* **Where:** `data/Preferences.kt:9-18`
* **What:** the DataStore has no `CorruptionHandler`. A truncated or
  unreadable `nedotify.preferences_pb` makes the app look healthy — it
  starts, it renders, it plays — but **no setting can ever be changed
  again**, because every write fails and the failure is swallowed.
* **How:** supply a `ReplaceFileCorruptionHandler` that resets the preferences
  to defaults, and surface a one-shot message so the user knows their
  appearance/profile settings were reset.
* **Done when:** a test writes garbage into a file-backed preferences store
  and asserts that the next read returns the defaults and the next write
  succeeds.

### R1.6 — Fix the lyrics identity gate [P1-01] 🔴

* **Where:** `data/LyricsCascade.kt:46-78`
* **What:** the gate rejects any candidate whose title is not a close match
  to the expected title, so a track titled `"Artist - Song"` never matches
  anything, and the lyrics tab reports "Текст не найден" for a large class of
  catalogue tracks. The desktop matches on a *set* of title forms.
* **How:** port the desktop's candidate-title set (`services/lyrics_lookup.py`)
  rather than comparing a single normalised string; keep the artist and
  duration gates.
* **Done when:** a JVM test with the `"Artist - Song"` shape finds the
  candidate.
* **Related:** P2-68 (the gate requires *all* artists, so "Artist feat. Guest"
  loses its lyrics) and P2-71 (no base-recording fallback for remix / slowed /
  sped) are the same family — fix the gate once, with the desktop's rules.

---

## W2 — Make the data durable and honest

### R2.1 — Extract the queue snapshot into a typed codec [P2-01 + A-1] 🔴

* **Where:** `player/PlaybackService.kt:333-342` (write), `:157-172` (read),
  `data/Preferences.kt:38,49`
* **What:** the format is a private string inside a `MediaSessionService`,
  with a `version` field that is written but never read, a storage key
  (`queue_v1`) that disagrees with the payload version (`2`), and a
  de-duplication guard that can never fire because the compared value embeds
  `player.currentPosition`. The whole settings file is rewritten every 5
  seconds while playing and on every seek.
* **How:** create `data/QueueSnapshotCodec.kt` with a `QueueSnapshot` data
  class and `encode`/`decode` (the pattern `data/BackupCodec.kt` already
  demonstrates). Split the payload into a **cheap head** (`index`,
  `position`, `repeat`, `shuffle`, `currentId`) and an **expensive body**
  (the id list + the shuffle order), stored under two different keys, so a
  seek rewrites only the head. Cap the persisted queue the way the desktop
  does (`core/session.py:9,50-55` — 200 entries, index adjusted).
* **Done when:** a JVM round-trip test passes; a test of the form "two
  snapshots with the same queue identity but different positions must not
  produce two writes" passes; the restore rejects an unknown `version`.
* **Also closes:** P3-34 (version never checked), and it makes the restore
  unit-testable for the first time.
* **Side effect:** a crash between the two writes must leave a consistent
  state — the head must be rejected if its `currentId` is not in the id list.

### R2.2 — Bound the backup's heap cost and stop the crash [P2-16]

* **Where:** `data/BackupCodec.kt:116-124`, `:161-165`;
  `data/LibraryBackupStorage.kt:27-42`; `ui/MusicViewModel.kt:263-271`
* **What:** the 16 MB cap bounds the *file*, not the heap. A 16.4 MB document
  that the codec itself accepts needs ~120 MB of live heap and throws
  `OutOfMemoryError` at `-Xmx160m` (measured on the JVM with the project's own
  `org.json:json:20250517`). `OutOfMemoryError` is an `Error` — it escapes
  `catch (_: Exception)` in both the decoder and the ViewModel, and kills the
  process instead of producing the promised message.
* **How:** (a) drop the `ByteArrayOutputStream.toByteArray()` copy; (b) bound
  the *shape* (member/object count) in the strict-JSON pass, not just the byte
  count; (c) catch `OutOfMemoryError` at the task boundary and convert it to
  a `SourceFailure`. The member budget must sit above the real worst case
  (20 000 tracks × 12 members ≈ 240 000).
* **Done when:** importing a max-size backup on a constrained heap produces
  the error message, not a process death.

### R2.3 — Export atomically [AN-07 A]

* **Where:** `data/LibraryBackupStorage.kt:19-24`
* **What:** the export opens the user's chosen document in mode `"wt"`
  (write + **truncate**) and writes straight into it. The destination is
  destroyed *before* a single byte of the new backup exists, and it is left
  half-written if the write fails. The default name is date-based, so the
  same document is overwritten on every export.
* **How:** materialise and verify the payload in a private temp file first,
  then stream it to the SAF document; on failure, delete the partially written
  document (or at minimum tell the user the previous copy at that path was
  lost).
* **Done when:** a failed export leaves the previous good file intact.
* **Related:** P2-15 (the export caps are the *decoder's* caps and the error
  message is the read-side wording) and P3-73 (the decoded backup is
  retained for the whole preview).

### R2.4 — Make the report's comparison windows equal [P2-43]

* **Where:** `data/ListeningReports.kt:86-117`
* **What:** the current period is an **incomplete** calendar period and the
  comparison period is a **complete** one, so the headline percentage is
  biased by up to −14 % at the start of the day — the app tells the user
  their listening dropped when it did not.
* **How:** compare against the previous period truncated to the same elapsed
  offset, or switch both to equal rolling windows as the desktop does
  (`services/listening_comparison.py:23-24`).
* **Done when:** the percentage is identical at 00:00 and at 23:59 for an
  unchanged habit.
* **Also:** P2-44 (artists are grouped case-sensitively, so one artist splits
  into several rows) and P3-97 (the desktop's "year" period has no Android
  counterpart) are the same area.

### R2.5 — Report the desktop import's losses instead of hiding them [P2-18, P2-17, P2-20, P2-21]

* **Where:** `data/DesktopLibraryImport.kt:43-69`,
  `data/DesktopLibraryConverter.kt:20-100`
* **What, as a group:**
  - a missing desktop column is accepted silently — every track imports
    un-favourited, undated, with duration 0, and the notice says nothing
    (P2-18);
  - one unparsable smart playlist aborts the **whole** import (P2-17);
  - two libraries under the same source name collide on their ids (P2-20);
  - a WAL copy taken without a clean close imports a silently incomplete
    library (P2-21).
* **How:** treat the allowlisted column set as a contract (fail loudly, or at
  minimum add an explicit notice line per lost field); make the desktop-rule
  conversion per-row fault-tolerant the way the desktop is; derive the
  imported-library identity from something machine-specific; and warn when
  `PRAGMA journal_mode` is `wal`.
* **Done when:** a fixture missing `is_favorite` produces a notice that says
  so, and a fixture with a `NULL` `rule_json` imports the rest.

---

## W3 — Close the network and provider gaps

### R3.1 — Send the headers the CDN expects [P2-51] 🔴

* **Where:** `player/PlaybackService.kt:55-69`; `data/Sources.kt:47-49`
* **What:** the media/CDN request goes out as `User-Agent: okhttp/4.12.0` with
  no `Referer`. The desktop sends a Chrome UA on every upstream request. A
  403 on the first byte is not a `SourceFailure`, so it is **not** forwarded
  as a session error and collapses into the generic snackbar; the automatic
  recovery then re-resolves the *same* track and re-requests the same URL.
* **How:** put the header policy on the client or the Media3 factory —
  `OkHttpDataSource.Factory(repository.network.http).setUserAgent(...)` plus a
  per-source `Referer`/`Origin` map (Media3 1.11.1 has both
  `setUserAgent` and `setDefaultRequestProperties`).
* **Done when:** a captured request to the CDN carries the expected UA and the
  per-source `Referer`.
* **Side effect:** a blanket `Referer` may leak usage to a third-party host —
  scope it per source, following the desktop's rule that credentials attach
  only to the provider's own hosts.

### R3.2 — One media-URL policy, applied to every redirect hop [P2-52]

* **Where:** `data/Sources.kt:115,176`; contrast `data/YandexDownloadInfo.kt:29-36`
* **What:** SoundCloud's final URL is accepted on the strength of an `https://`
  prefix alone, and YouTube's formats are filtered the same way. The correct
  pattern (`trustedUrl`: host allow-list, port 443, no userinfo, no fragment,
  length cap) exists in the same codebase and is applied to exactly one of
  three providers. The media client keeps OkHttp's default
  `followRedirects=true`, so a 302 moves the player to a host that was never
  validated.
* **How:** one shared media-URL policy (https + a per-source host allow-list),
  applied to the resolved URL *and* re-applied to every redirect hop via an
  interceptor.
* **Done when:** a stub resolver returning `https://127.0.0.1/x` is rejected,
  and a 302 to an internal address is not followed.
* **Side effect:** a strict allow-list breaks when a provider rotates its CDN
  — the desktop hit exactly this with `soundcloud.cloud`. The list needs a
  maintenance path and a documented fallback.

### R3.3 — Narrow the provider mutex [P2-05]

* **Where:** `data/ProviderConnections.kt:21,62-74,135-139`
* **What:** one `Mutex` is held across provider network I/O — including the
  Spotify token refresh. A slow or degraded provider therefore stalls every
  other provider operation for up to the 30 s call timeout, and the Settings
  panel disables **every** control while it is busy.
* **How:** narrow the lock to the credential-state critical sections and move
  the HTTP work outside it, using a separate single-flight `Deferred` keyed by
  generation — the shape `SoundCloudClient` already uses in `data/Sources.kt:58-79`.
* **Done when:** the existing 22 JVM tests in `ProviderConnectionsTest` still
  pass (they pin "one refresh for N concurrent expired requests"), and a new
  test asserts that a hanging token endpoint does not block a Yandex call.
* **Side effect:** the current code is what guarantees the generation fences
  that stop a stale response from repopulating a logged-out account. The
  replacement must be built and tested first.

### R3.4 — Make the offline source-of-truth singular [A-4 + XI-05 B]

* **Where:** `player/PlaybackService.kt:233-256` (the reconcile),
  `:320-332` (`mediaItem`), `downloads/OfflineSources.kt:10-16`
* **What:** the effective source of a queue item is encoded **twice** — in
  the `MediaItem` (URI scheme + an `OfflineAsset` tag) and in the download
  table — and the two can disagree. The reconcile's trigger set covers only
  the completed-download set, so a `localUri` change never re-materialises the
  item. The rewrite is O(N) on the main thread.
* **How:** resolve the effective source at **open time** via the
  `ResolvingDataSource` seam the app already has ("is there a completed
  download for this id? → the offline store; else → remote"), and delete the
  `refreshQueueSources` / `planQueueSourceRefresh` machinery.
* **Done when:** attaching a local file to a queued track is reflected on the
  next play of that item, with no queue rewrite.
* **Side effect:** the "resolve before `CacheDataSource` picks its key"
  ordering must be preserved.

### R3.5 — Make the resolution cascade fall back [P2-48]

* **Where:** `data/LibraryRepository.kt:29-42`
* **What:** `resolveRemote` calls exactly one provider and fails if it fails.
  The desktop runs a cascade for the same track (primary → a SoundCloud
  search by title/artist → a YouTube search) and falls back in the other
  direction too. The Android port has the cascade pattern *in the same
  codebase* for lyrics but not for streams. For YouTube this is the dominant
  failure mode: the port uses the `ANDROID_MUSIC` InnerTube client with no
  cookies, and the porting status already records
  "player — LOGIN_REQUIRED. Гарантированное анонимное воспроизведение не
  реализовано."
* **How:** restructure `resolveRemote` into a cascade with a shared
  wall-clock budget, where a provider failure falls through to a
  title/artist search on the other playback provider, reusing
  `CatalogMatcher.match` so the fallback is identity-checked rather than a
  blind first result.
* **Done when:** a track that the desktop plays via the fallback plays on
  Android, and the stored `Track.source`/`sourceId` records which provider
  actually answered.
* **Side effect:** a fallback can substitute a different recording — the
  identity gate and duration tolerance must be applied, and the 15 s
  `sourceDeadline` must be raised or the budget split per stage.

### R3.6 — Give the streaming cache a stable identity [P2-47]

* **Where:** `player/PlaybackService.kt:56`; `data/Sources.kt:117,185`
* **What:** `CacheDataSource.Factory()` is used with **no** `CacheKeyFactory`,
  so Media3's default applies — the key is the **full signed URL**. Every
  provider hands out an expiring URL, so every re-resolution produces a new
  key, the bytes are never read again, and the LRU evicts exactly those
  never-re-read entries first. The advertised "Кэш потоков 64–1024 МБ"
  quota is therefore effectively inert.
* **How:** give the playback `CacheDataSource` a `CacheKeyFactory` derived
  from the **track id**, mirroring what `downloads/DownloadKeys.kt` already
  does for the download store.
* **Done when:** playing a track, letting the URL expire and playing it again
  produces **one** cache entry, not two.
* **Side effect:** the key must keep the quality in scope (a quality change
  must not collide) and the HLS manifest/segment identity must stay
  distinguishable.

### R3.7 — Keep the provider's error classification [P2-62, P2-58, P2-59, P2-60, P2-61]

* **Where:** `ui/MusicViewModel.kt:377-389`; `data/SearchAggregate.kt:28-31`;
  `data/ProviderHttp.kt:51-69`; `data/LibraryRepository.kt:55-67`
* **What, as a group:**
  - the HTTP layer classifies 401/403/429 into distinct Russian messages and
    the catalogue path throws that classification away — a rate-limited
    provider is reported as "the version was not found" (P2-62);
  - a failed provider is invisible in "Все" search unless the *whole* result
    set is empty (P2-58);
  - the local DB scan is given the 6.5 s *network* budget, so a large library
    silently loses the local hits (P2-59);
  - the search pipeline body — a 126 KB JSON parse and a 50 000-node DOM walk
    — runs **on the UI thread** (P2-60);
  - the catalogue path parses multi-hundred-kilobyte Yandex documents on the
    main thread (P2-61).
* **How:** carry the per-provider outcome out of `aggregateSearch` and surface
  a non-blocking notice; give the local task its own budget; move the
  provider bodies and the JSON parses to `Dispatchers.IO`.
* **Done when:** a search with one failing provider shows a notice naming it,
  and a `gfxinfo` trace during a search shows no main-thread JSON parsing.

### R3.8 — The remaining download-lifecycle findings

| ID | Where | What | How |
|---|---|---|---|
| P2-49 | `data/CatalogProviders.kt:111`, `downloads/TrackDownloadWorker.kt:44-47` | A Яндекс download starts on a link the app itself declares valid for 45 s, and `ResolvedStream.expiresAt` is never read in the download path | Honour `expiresAt`; make the Яндекс cache key stable across `ts`/signature renewals the way `downloadCacheKey` does for the other CDNs |
| P2-50 | `downloads/TrackDownloadWorker.kt:74-78` | A truncated body is published as "Скачано" (the expected total from the progress listener is discarded) | Compare the received byte count with the total; reject and delete below a floor — mirroring `core/downloader.py:807-814` |
| P2-30 | `downloads/DownloadStorage.kt:25` | No size ceiling, no free-space probe, `NoOpCacheEvictor`; `ENOSPC` is treated as *retryable* | A per-track ceiling, a `StatFs` probe, a store budget, and a non-retryable storage-full failure |
| P2-29 | `downloads/TrackDownloadWorker.kt:41-42` | Up to 20 foreground notifications for 2 concurrent transfers; the worker enters the foreground *before* taking the permit | Cap WorkManager's concurrency at 2; create the notification channel once |
| P3-75 | `downloads/TrackDownloadWorker.kt:114-119` | A failed *removal* offers a retry that re-downloads the track | A separate terminal state for a failed removal, and a control that re-enqueues the removal worker |
| P2-63 | `ui/LibraryScreen.kt:50,76` | The «Скачанные» tab lists rows that are not downloaded | Filter the list, or rename the tab and derive the count from the rendered set |
| P3-55 | `ui/LibraryScreen.kt:72`, `ui/SettingsScreen.kt:49` | The size summary counts the bytes of *all* rows | Sum the bytes of the same subset used for the count |

### R3.9 — The lyrics feature [P2-66, P2-67, P2-69, P2-70, P2-71, P3-78..P3-81]

The cascade is the right shape (it mirrors the desktop) but has three
structural gaps: no failure channel, no shared deadline, and a per-provider
budget that does not cover a provider's own request count.

* **A failure channel** (P2-66): `LyricsResult` cannot express "the lookup
  failed", so a provider outage is reported as "no lyrics found". The desktop
  has a three-state result and renders three different messages. Introduce a
  sealed result (`Found` / `NotFound` / `Unavailable`).
* **One deadline** (P2-69, P2-70): the ViewModel's 12 s cap is *smaller* than
  the cascade's own worst case (3.5 s + 4 × 2.2 s = 12.3 s), so a late success
  is thrown away. Thread a single global deadline down, as the desktop does.
* **The identity gate** (P2-68, P2-71): relax the artist check to an
  intersection (as the desktop's `artist_matches` does) and port the
  base-recording fallback for `remix` / `slowed` / `sped`.
* **Never cache a worse result** (P2-67): a forced refresh that returns an
  empty result currently overwrites a good 24-hour cache entry with a
  10-minute negative — in memory *and* on disk.
* **Do not poison the disk cache** (P3-78..P3-81): record the provider in
  `source`; clamp instead of throwing in `lyricsResult`; add a schema version
  to the cache key; and move the cache out of `cacheDir`, which Android may
  purge, into `filesDir` (updating the backup-exclusion XML).

### R3.10 — Pin the JSON semantics the production code depends on [P2-73] 🔴

* **Where:** `android/app/build.gradle:57`; `data/Sources.kt:106,233`;
  `data/CatalogProviders.kt:31`; `data/ProviderConnections.kt:114`;
  `data/SourceJson.kt:22`; `data/ProviderHttp.kt:65`
* **What:** the JVM suite parses JSON with the **reference** implementation
  (`org.json:json:20250517`) while production runs on the **Android platform**
  `org.json`. Three measured divergences: `optString` on an explicit null
  (reference `""` / platform `"null"`), `getString` on a non-string (reference
  throws / platform coerces), and duplicate keys (reference throws / platform
  keeps the last value). The production code already compensates for the
  platform in **2 of 55** `optString` call sites — and those two workarounds
  are *dead code on the test classpath*, so the branch is never taken in any
  of the 236 executed tests. The other 53 sites inherit the platform
  behaviour with no compensation and no test.
* **Impact, on the device only:** a SoundCloud track whose `title` is `null`
  is stored with the literal title `null`; a Spotify catalogue item whose
  `name` is `null` is *accepted and imported* with the title `null` (the
  reference implementation rejects it, so the JVM suite would pass); the
  Yandex account name is displayed as `null` instead of falling back to the
  login. A provider response with a duplicated key is rejected on the JVM and
  accepted on the device.
* **How:** make the semantics explicit and pinned. Either (i) add a **JSON
  contract fixture** asserting the *platform* rules the production code
  relies on, and route all 55 `optString` sites through one helper
  (`optText(obj,key)`) that normalises `"null"` → `""` once; or (ii) route
  all production JSON through one internal parser facade (`SourceJson` already
  exists) so there is exactly one `org.json` on the classpath, and move the
  strict-JSON checks (`BackupCodec.requireStrictJson` already does this for
  backups) to the same facade.
* **Done when:** a JVM test asserts the platform contract, and a device run
  confirms the same behaviour.
* **Side effects:** option (i) touches 55 call sites and needs a decision on
  whether `"null"` should become `""` everywhere; option (ii) requires a
  strict-mode JSON dependency, increases the APK size, and must be
  re-audited against the 4 MB / 2 MB body bounds in `Sources.kt:24-46`.

### R3.11 — Stop the catalogue import from freezing the whole catalogue [P2-74]

* **Where:** `ui/MusicViewModel.kt:315-336`, `:369-394`
* **What:** `importCatalog()` holds `importing = true` for the whole run (up
  to 500 items × a 20 s per-item deadline, worst case ~2.8 h). Every other
  catalogue entry point refuses to run while that flag is set — and refuses
  **silently**: search, "Мои плейлисты" and even playing a single track become
  no-ops with no message.
* **How:** keep a dedicated `importing` flag for the import job only and let
  the normal catalogue operations run against a snapshot; or give the import
  its own overall deadline and make the blocked operations surface a message
  instead of returning silently. Both are fixed properly by moving the import
  into a persisted WorkManager job (which also closes P2-08).
* **Done when:** starting an import no longer blocks search or track playback
  in the same screen.
* **Side effect:** a catalogue reload during an import means
  `_catalog.value.tracks` can change under the import — the import already
  captures its own snapshot and a generation, so it must keep using the
  captured list and stay generation-guarded (it is, via `updateCatalog`).

---

### R3.12 — Make the local search a query, and give the search subsystem per-source budgets [P1-05, P2-80, P2-81, P3-115, P3-116] 🔴

* **Where:** `data/LibraryRepository.kt:54-71`; `data/Models.kt:104-105`;
  `data/SearchAggregate.kt:16-32`; `data/CatalogMatcher.kt:66-76`;
  `ui/MusicViewModel.kt:351-355,369-394`
* **What.** The local search is not a query: it pages the whole `tracks`
  table in Kotlin, ordered by `addedAt` — a column with **no index**
  (`EXPLAIN QUERY PLAN`: `SCAN tracks` + `USE TEMP B-TREE FOR ORDER BY`).
  Measured: 1 000 rows → 5.5 ms, 10 000 → 117 ms, 50 000 → **13.9 s**,
  100 000 → **63.5 s**. The aggregate gives that scan the *same* 6.5 s
  budget as a network provider, so past ≈ 35 000–40 000 tracks it is
  cancelled and the local matches are dropped **without any error** (the
  network sources succeeded, so the "a source was unreachable" signal never
  fires). The dedicated "На устройстве" chip has **no** timeout at all and
  blocks the search for over a minute. The desktop has a real FTS5 index
  (10.5 ms at 100 000 rows).
* **Also in this item:** the SoundCloud client-id scrape runs inside the
  same 6.5 s budget (the desktop gives it 8 s for exactly this reason);
  the catalogue matcher performs up to **1 000 sequential** third-party
  searches per 500-track import (the desktop: bounded concurrency 8, a
  300 s memo, a local-first step); `search` has three mutually exclusive
  exit paths with different timeouts so the same query behaves differently
  per chip; and the `OFFSET` pagination is not snapshot-stable, so a track
  added or removed mid-scan is returned twice or not at all.
* **How.**
  1. Push the filter into SQL and add an index that supports the query. For
     a faithful fix, add an FTS table with the desktop's triggers and query
     it with per-word prefix terms — note that `room-runtime:2.8.5` has no
     `@Fts4` support without the `room-fts` artefact, and that an indexed
     `LIKE '%q%'` still cannot use an index for a leading wildcard (it fixes
     the *scan*, not the *per-page* cost). This needs a Room migration
     (schema v4) plus a backfill.
  2. Give the local source **its own** budget — it is not a network call —
     and make the failure mode explicit: "the local scan was too slow" must
     be reportable, not indistinguishable from "no matches".
  3. Replace the single `providerTimeoutMs` with a per-source table
     (`SearchSource(name, timeoutMs, block)`), giving SoundCloud the
     desktop's 8 s for its first (client-id-scraping) call, and make the
     "all" path literally the composition of the same entries the
     single-source paths use. This also gives per-source attribution, which
     fixes the "partial result presented as a complete one" problem
     (P2-58).
  4. Replace the serial catalogue-import loop with a batch resolver: a memo
     keyed by (artist, title), a bounded-concurrency fan-out, a whole-batch
     deadline, and a local-library lookup *before* the network.
* **Done when:** a 100 000-track library answers a non-matching local
  search in well under a second, and the "Все" search either returns the
  local matches or says plainly that it could not.
* **Side effects:** a schema v4 migration and an FTS backfill; changing the
  local budget changes when `SearchAggregate.kt:30` raises `SourceFailure`,
  so `SearchAggregateTest` must be re-checked; a batch deadline means some
  catalogue tracks legitimately resolve to "not found", so the `unavailable`
  counter and the "обработаны первые 500 записей" message must reflect a
  partial batch.

---

## W4 — Establish a gate (do this in parallel with W1–W3)

### R4.1 — Make the 59 device tests actually run [P2-53] 🔴

* **Where:** `android/verify.ps1:5`; no `connectedDebugAndroidTest` anywhere
* **What:** the default task list is source-only. 59 instrumentation tests —
  including **all 19** Room schema-migration tests, the only guard on the
  v1→v2→v3 migration that will run against real user data — have been
  *compiled* and never executed.
* **How:** add a `:app:connectedDebugAndroidTest` invocation behind an
  explicit opt-in switch in `verify.ps1` (keeping the source-only default),
  and add an emulator job to CI.
* **⚠ Requires an explicit user grant:** `connectedDebugAndroidTest` runs
  `assembleDebug` + `assembleDebugAndroidTest`, which the standing "no APK"
  rule forbids. **Do not delete the tests instead.**
* **Done when:** the 59 tests execute and pass on an API-26-or-above AVD, and
  the result appears in the machine-readable summary.
* **Note:** the first run may surface pre-existing failures. Triage them; do
  not suppress them.

### R4.2 — Add an Android CI job

* **Where:** `.github/workflows/ci.yml` (currently the desktop pytest only)
* **What:** the repository's only CI runs `pytest -m "not network"` on
  Windows. There is no Gradle job, no JDK/SDK setup, no Android job, no
  emulator job.
* **How, in dependency order:**
  1. Track `android/` in git (R0.2) — without it a checkout contains no
     Android sources at all.
  2. A **unit-test job** on every PR: `actions/setup-java` (JDK 21),
     `actions/setup-android`, then `android/verify.ps1 -Tasks
     @(':app:testDebugUnitTest', ':app:lintDebug')`. Cheap; it immediately
     makes the 236 JVM regressions gate every change. Note that
     `verify.ps1`'s junction-alias dance is Windows-specific — use
     `windows-latest` or a Linux-safe wrapper.
  3. An **emulator job** for the instrumentation suite
     (`reactivecircus/android-emulator-runner`, `api-level: 26` to cover the
     `minSdk 26` contract).
  4. Check in `app/schemas/` — required by the migration tests and only
     meaningful once `android/` is tracked.
* **Done when:** a PR that breaks a JVM test fails CI.

### R4.3 — Fix `verify.ps1` so it does not silently execute zero tasks [P2-72]

* **Where:** `android/verify.ps1:7,56,63`
* **What:** `$ErrorActionPreference='Stop'` + a script-exported
  `JAVA_TOOL_OPTIONS` means the JVM's stderr banner becomes a terminating
  `NativeCommandError` **whenever the output is captured** — the script exits
  1 having run nothing, and looks like a build failure with no explanation.
  A harness that ignores the exit code would report a green build that
  verified nothing.
* **How:** scope the error preference to the native call
  (`$ErrorActionPreference='Continue'` around line 63, restored in the inner
  `finally`) and/or stop exporting `JAVA_TOOL_OPTIONS` — the script already
  redirects `$env:TEMP`/`$env:TMP` to the ASCII alias, which covers the same
  need.
* **Done when:** `& ".\verify.ps1" -Tasks @(':app:testDebugUnitTest') 2>&1 |
  Tee-Object out.log` runs the tests and the log contains `> Task :app:…`.

### R4.4 — Stop `verify.ps1` from reverting a concurrent `local.properties` [AN-23 A]

* **Where:** `android/verify.ps1:44-46,53,67-68`
* **What:** the script replaces `android/local.properties` with an alias path
  for the whole Gradle run (measured 5 m 8 s) and in `finally` restores the
  bytes captured **before** the run — unconditionally. An Android Studio edit
  made during the run is silently reverted; a file created during the run is
  silently deleted.
* **How:** make the restore conditional — write the snapshot back only if the
  current file still equals exactly the alias bytes the script wrote; in the
  "did not exist before" case, delete only if the content is still the alias.
* **Done when:** editing `local.properties` during a verify run leaves the
  edit in place.

### R4.5 — Add the four missing contract tests [P3-90]

Five of the ten non-negotiable contracts have **zero** automated coverage:

| Contract | Test to add |
|---|---|
| The player is owned by `MediaSessionService`, never by the UI | A source-scanning test: no `ExoPlayer` in `ui/**` |
| Stream URLs are never fetched for the whole queue before playback | A test that asserts `ResolvingDataSource` is the only resolution point and that no `resolve()` call precedes `setMediaItems` |
| Minimum API 26 | Already covered by lint's `NewApi`; make it an explicit assertion in the build |
| A partial streaming cache is never a completed download | A Room download-state test |
| The user's library is never altered | A test that a *play* adds no `tracks` row (currently fails — see R2.6) |

Plus the four proposed in the AN-27 B report: a queue-shape test, a
`ListeningClock` seek case, and two source-scanning contract tests.

### R4.6 — Move the pure parts of the device-only tests into the JVM suite

The instrumentation suite is 59 tests across 15 files with **zero** shared
helpers — roughly 28 duplicated setup sites. Extract the pure parts of the
DAO, codec and rule semantics into the JVM suite (which already runs
`BackupCodecTest`, `BackupMergeTest`, `SmartRulesTest`, `QueueSelectionTest`
and `DesktopLibraryConverterTest` on the JVM), leaving only the genuinely
Android-specific parts on the device.

### R4.7 — Give the orchestration layer a test seam [P2-75] 🔴

* **Where:** `ui/MusicViewModel.kt:29-31`; `player/PlaybackService.kt:31,173`;
  `data/LibraryRepository.kt:15-22`; `downloads/Downloads.kt:18-20`;
  `downloads/TrackDownloadWorker.kt:26`; `player/DualDeckPlayer.kt:28-34`;
  `app/src/test/.../player/PlaybackMutationTest.kt:18-21`
* **What:** 1 219 LOC of orchestration cannot be reached by any of the 236
  executed tests, because they need an `Application`, a concrete
  `LibraryRepository`, a `MediaSessionService`/`ExoPlayer`, a `Room` DAO or
  `WorkManager`. The project extracted `PlaybackPreparation`,
  `guardedPlaybackMutation`, `playbackFailureMessage`, `sourceDeadline`,
  `onlineSource`, `aggregateSearch` and `importLocalBatch` so they *could* be
  tested — but **the extraction stopped at the helper**: the guard tests
  re-implement the service's predicate locally, so a change to the real
  predicate is invisible.
* **Proof:** change `PlaybackService.kt:173` to
  `stillCurrent={restoreVersion==interactionVersion}` (dropping the
  `mediaItemCount==0` clause) and re-run `:app:testDebugUnitTest` — 236/236
  still pass.
* **How:** introduce the missing seams — a `PlayerGateway` interface that
  `PlaybackService` implements and the ViewModel talks to; a `LibraryGateway`
  in front of `LibraryRepository`; a `DownloadScheduler` in front of
  `WorkManager` — and move the `stillCurrent` predicates into named, shared,
  testable functions that both the service and the test call. Extract the
  `PlaybackService` queue-restore and offline-refresh state machines into a
  plain class that owns `interactionVersion` and is unit-testable without
  Media3.
* **Done when:** the queue-restore and offline-refresh races have a JVM test
  that exercises the *service's own* predicate.
* **Side effect:** the `DualDeckPlayer` seam is expensive because Media3's
  `Player` is a wide interface — a narrow `PlaybackState` value object is the
  cheaper route. This is the same change as A-5, seen from the test's side.

### R4.8 — Make the build reproducible and hermetic [P2-76, P2-77, P2-78, P2-79, P3-111, P3-112, P3-113, P3-114]

These eight findings are one theme: **the build is not a fixed artefact of the
source.**

| ID | What | Fix |
|---|---|---|
| P2-79 | The SDK lives in `C:\Temp\nedotify-android\sdk` (3 697 MB, inside the system temp dir); `ANDROID_HOME`/`ANDROID_SDK_ROOT` are unset and `%LOCALAPPDATA%\Android\Sdk` does not exist, so `local.properties` is the *only* channel that says where the SDK is - and it is a globally shared file | Install the SDK under `%LOCALAPPDATA%\Android\Sdk`; keep the junction alias for the *project* path (that part is sound) and pass the SDK through the environment only |
| P2-77 | 30 literal dependency coordinates, no catalog, no lockfile, no `verification-metadata.xml`; and the **gating lint task reaches out to Maven Central on every build**, so "0 errors, 15 warnings" is a function of the calendar, not of the source | `gradle/libs.versions.toml` + `dependencyLocking` + `--write-verification-metadata sha256`; move the "newer version available" checks into a separate, non-blocking task |
| P2-76 | No `buildTypes`, no R8, no `proguard-rules.pro`, no `signingConfig` - `assembleRelease` would produce an **unsigned, unshrunk** APK; `debug` and `release` share the applicationId, so a debug build silently replaces a release one | Add a `release` build type with `isMinifyEnabled`/`isShrinkResources`, a `signingConfig` read from environment properties (never from the repo), `app/proguard-rules.pro`, and an `applicationIdSuffix` for `debug` |
| P2-78 | KSP 2.3.12 is built against Kotlin **2.3.20** while the project compiles with Kotlin **2.2.10**; `room-compiler:2.8.5` separately declares the two-year-old `symbol-processing-api:2.0.10-1.0.24` | Pin KSP to the Kotlin-matching release; keep `room-compiler` on the same API line; record the AGP↔Kotlin↔KSP↔Compose matrix in the catalog |
| P3-113 | Every build prints an SDK-XML-version mismatch; every build ends with "incompatible with Gradle 10"; the configuration cache is off and the measured configuration phase is **11.5 s** | Fix the Gradle-10 deprecations with `--warning-mode all`; enable `org.gradle.caching`; enable the configuration cache **only after** validating it against the full suite (Room + KSP + AGP 9 is exactly where it historically breaks) |
| P3-114 | `kotlin.incremental=false` makes a **one-line** edit cost a measured **33.6 s** full-module recompile | `kotlin.incremental=true` **and** separate the two build roots - the flag alone re-introduces the path-aliasing inconsistency the comment describes |
| P3-112 | No Coil `ImageLoader` is configured, so cover art is fetched by a **second, unconfigured `OkHttpClient`** with stock timeouts and none of the app's caps | Install a `SingletonImageLoader` on a dedicated client with explicit timeouts and a response-size cap |
| P3-111 | `haze` drags the JetBrains Compose coordinates and a newer `kotlin-stdlib`, and pins `minCompileSdk=37` | Keep it; record the constraint in a comment. *If it is ever dropped, it is a **one-function** change* - all 35 `.glass()` call sites route through `Modifier.glass()` at `ui/Design.kt:71` |

**Done when:** two builds of the same commit, on different days, on a clean
checkout, produce the same dependency graph and the same lint result; and the
SDK is found without `local.properties`.

---

## W5 — The remaining surface

### R5.1 — The user-visible P2 findings, grouped by theme

| Theme | IDs | Where |
|---|---|---|
| Search / library state | P2-31 (a search result list is written into the permanent library), P2-32 (a new search wipes the previous results), P2-53, P2-55, P2-64 | `ui/MusicViewModel.kt`, `ui/SearchScreen.kt` |
| Queue / player | P2-33 (index-prefixed `LazyColumn` key), P2-34 (`NowPlaying` carries the whole queue), P2-35 (the queue rows lose artist/cover/duration), P3-46, P3-47, P3-48, P3-49, P3-50, P3-52 | `ui/PlayerScreen.kt`, `ui/MusicViewModel.kt` |
| Theme / layout | P2-36 (7 of ~40 Material roles overridden), P2-37 (per-tab state destroyed on a tab switch), P3-37, P3-39, P3-40, P3-41, P3-42, P3-43, P3-45 | `ui/Design.kt`, `ui/MusicApp.kt` |
| Connections / auth UX | P3-66, P3-67, P3-68, P3-69, P3-70 | `ui/ConnectionsControls.kt` |
| Settings / profile | P2-43, P3-58, P3-59, P3-60, P3-61, P3-62, P3-63, P3-65 | `ui/AudioSettingsControls.kt`, `ui/ProfileScreen.kt` |
| Player / focus / lifecycle | P2-09, P2-10, P2-13, P2-14, P2-15, P2-27, P2-28, P3-05..P3-12, P3-103..P3-108 | `player/**` |
| Desktop import / backup | P2-19, P2-22..P2-26, P3-15, P3-16, P3-71..P3-74, P3-101, P3-102 | `data/DesktopLibrary*.kt`, `data/Backup*.kt` |

### R5.2 — Documentation and process consistency [P2-38..P2-42, P3-83..P3-92]

* **The root `AGENTS.md` (P2-39)** states repo-wide absolutes that are false
  for the Android tree — "The sole UI is `ui/web_new_v2/`", "Interpreter for
  every command: `.venv_win\Scripts\python.exe`" — and never points to
  `android/AGENTS.md`. `STATUS.md` and `README.md` contain **0** matches for
  "android". Add a dispatch header naming the two products.
* **`android/AGENTS.md` (P2-40)** protects `~/.nedotify` — a **host** path
  that cannot exist on the device — and never names the Android library
  (the app's private data, the MediaStore rows the user added, the persisted
  SAF grants). Translate the rule.
* **`REVIEW_A.md` / `REVIEW_B.md` (P2-41)** are the reviewer *briefs*, not
  summaries: the file a reader opens first contains **zero** findings. The
  real reports are in `received/`. Rename to `BRIEF_A.md`/`BRIEF_B.md` and
  add an index.
* **The validation artefacts (P3-83, P3-92)** say 217 JVM tests (the tree has
  **236**), 17 lint warnings (the tree has **15**), 55 instrumentation tests
  (the tree has **59**) and "APK не собирался" on one page and "debug APK,
  instrumentation APK" on another within the same day. Regenerate them from
  the actual XML.
* **The Compose test API (P2-57):** migrate the five files to
  `androidx.compose.ui.test.junit4.v2.*` — **but only in the same change that
  first makes the suite runnable**, because the v2 dispatcher change alters
  execution semantics.

---

## Appendix A — Quick reference: the highest-value single changes

If only three things get done, these are they.

1. **R0.2 + R0.3** — `git add android/` and regenerate the manifest. Hours.
   Makes every later change reviewable, diffable and revertible.
2. **R4.1 + R4.2** — make the 59 device tests run, and add the Android CI
   job. Requires a one-off grant for the APK assembly. Turns a project with
   no signal into a project with a gate.
3. **R1.1** — replace the `PendingSelectionGate` boolean with an intent
   token. One focused change that removes four defects (P1, P2-11, P2-12,
   P2-13) and makes the play path honest.

## Appendix B — What the plan does *not* cover

* **The desktop app's own defects** beyond P0-01 and the parity gaps the
  Android port depends on. The desktop was the oracle, not the subject.
* **Release engineering**: signing, R8/ProGuard, `lintVitalRelease`,
  `bundleRelease`, `zipalign` — no APK or AAB was assembled, so those stages
  were never exercised.
* **Localisation.** The UI is Russian-only; no i18n audit was performed.
* **The P3 register in full** (110 rows). They are real, but each is a
  localised fix; §5.2 of the full report lists them with a one-line fix each.

---

*Audit complete. No code was changed by the audit; the only file touched
outside `docs/audits/` was `android/local.properties`, rewritten and restored
byte-for-byte by `verify.ps1`.*
