# FALSE POSITIVES and MATERIALLY OVERSTATED CLAIMS

Every entry below was tested by two independent verifiers plus the arbiter.
Where the original claim was *directionally* right but the stated mechanism or
consequence was wrong, the entry is classified as **OVERSTATED** and the
surviving kernel is stated explicitly. A claim is only called
**FALSE POSITIVE** when there is concrete evidence that the assertion as
written is wrong.

---

## FP-1 — The audit's #1 Android headline: "the `onPlayerCommandRequest` callback is never reached by `MediaController.play()`/`pause()`" and "every subsequent Play is dropped … until the user re-picks a track"

**Original claim** (`FULL_PROJECT_AUDIT.md:51-60`, `:1616-1622`, `:2147-2149`,
`:2268`, `:2276-2279`; `A-2`; remediation wave **W1**; the unnamed finding
*"XI-08 B P1"*):

> `PendingSelectionGate.playAllowed` is tripped by every player command but
> re-armed only from `MediaSession.Callback.onPlayerCommandRequest` — and in
> Media3 1.11.1 that callback is **never reached** by
> `MediaController.play()`/`pause()` (only `setPlayWhenReady` dispatches
> through it). Once tripped, every subsequent Play is dropped with no error
> and no state change, until the user re-picks a track.

**Verdict: FALSE POSITIVE** (the central mechanism) — **OVERSTATED**
(the residual behaviour). Confidence: **HIGH**. Evidence type: **bytecode**
(independent `javap` by the arbiter and by two separate verifiers).

**Evidence — Media3 1.11.1, `media3-session-1.11.1.aar` + `media3-common-1.11.1.aar`
from the local Gradle cache:**

```
androidx.media3.common.Player
  public static final int COMMAND_PLAY_PAUSE = 1;      <-- there is NO COMMAND_SET_PLAY_WHEN_READY in 1.11.1

androidx.media3.session.MediaSessionStub
  public void setPlayWhenReady(IMediaController, int, boolean);
      7:  iload_2          // session id
      8:  iconst_1        // <-- player command = 1 = COMMAND_PLAY_PAUSE
      9:  iload_3
      10: invokedynamic  // Consumer
      15: invokestatic  sendSessionResultSuccess
      18: invokespecial  dispatchAndQueueSessionTaskWithPlayerCommand:(IMediaController;II;SessionTask)V

androidx.media3.session.MediaSessionStub
  private void queueSessionTaskWithPlayerCommand(ControllerInfo, int, int, SessionTask);
      42: connectedControllersManager.isPlayerCommandAvailable(controllerInfo, playerCommand)
      75: MediaSessionImpl.onPlayerCommandRequestOnHandler(controllerInfo, playerCommand)   <-- the app callback IS consulted
      84: if (result != 0) { sendSessionResult(...); return; }                              <-- RESULT_SUCCESS continues
     134: connectedControllersManager.addToCommandQueue(controllerInfo, playerCommand, asyncCommand)

androidx.media3.session.MediaSessionImpl
  public int onPlayerCommandRequestOnHandler(ControllerInfo, int);
      14: invokeinterface MediaSession$Callback.onPlayerCommandRequest:(MediaSession;ControllerInfo;I)I

androidx.media3.session.MediaControllerImplBase
  public void setPlayWhenReady(boolean);
      1: iconst_1; 2: invokespecial isPlayerCommandAvailable:(I)Z
     30: invokespecial dispatchRemoteSessionTaskWithPlayerCommand:(...)V      <-- the remote task carries COMMAND_PLAY_PAUSE
```

`MediaController.play()` is `final` and delegates to
`MediaControllerImplBase.setPlayWhenReady(true)`. The app calls
`controller.play()` / `controller.pause()` (`ui/MusicViewModel.kt:175-178`,
`:185`) and never calls `setPlayWhenReady` or `togglePlayPause` directly.

**Consequence.** The app's own callback
(`player/PlaybackService.kt:85-88`)

```kotlin
override fun onPlayerCommandRequest(mediaSession, controller, playerCommand):Int {
    if(playerCommand==Player.COMMAND_PLAY_PAUSE) selectionGate.receivedPlayCommand()
    return SessionResult.RESULT_SUCCESS
}
```

**does fire on every play/pause press**, and `receivedPlayCommand()` sets
`playAllowed = true`. Because the callback runs at *command-enqueue* time and
the gate is consulted at *command-execution* time
(`player/DualDeckPlayer.kt:231`), the re-arm always precedes the check.

Therefore:

* the gate is **not** stuck;
* the **first** press after a trip is **not** swallowed;
* the phrase *"every subsequent Play is dropped … until the user re-picks a
  track"* is false;
* the phrase *"only `setPlayWhenReady` dispatches through it"* is false —
  `play`, `pause`, `prepare`, `stop`, every seek, repeat/shuffle, volume and
  every media-items mutation route through
  `queueSessionTaskWithPlayerCommand` and therefore through
  `onPlayerCommandRequest`.

**The audit contradicted itself.** Its own P2-11 body
(`FULL_PROJECT_AUDIT.md:1083`) says the opposite of its headline:

> "The second press works (it re-opens the gate via `receivedPlayCommand()`),
> so the gate is not permanently stuck, but the first press is silently lost."

Both statements were shipped. The parenthetical is the correct one.

**What survives.** A narrow, real and differently-scoped defect:

1. The refusal is **silent**. `player/DualDeckPlayer.kt:231`
   `if(playWhenReady && !canStartPlayback()) return Futures.immediateVoidFuture()`
   returns a *successful* future; no `SessionError` is sent, `invalidateState()`
   is not called, and `PlaybackService.kt:87` returns `RESULT_SUCCESS`
   unconditionally, so the controller cannot distinguish "refused" from
   "succeeded". **This is the kernel of P2-11.**
2. A *first* press can still be dropped in one narrow interleaving: a
   `setMediaItems` is pending, an interruption (transient focus loss,
   becoming-noisy, another controller's command) trips the gate **after** the
   play was enqueued, and the queued play then executes against a closed gate.
   In that window the queue was cancelled anyway, so nothing is audible; the
   next press works.

**Revised severity:** the *"XI-08 B P1"* finding — **P1 → P3** (silent veto
only). **P2-11 — P2 → P3.** The rest of the W1 wave's premise is void.

**Second-order consequence for the audit itself.** The claim is the stated
justification for remediation wave W1 and for architecture item A-2, and it is
one of the audit's "five things that matter most". It also propagates into
X-01, which asserts that the two fencing protocols "disagree exactly in the
window that matters". They do not: `playAllowed` is re-armed by the same
command that the check consults.

---

## FP-2 — P0-01's stated **cause**: "the de-duplication key was chosen as the *display* identity (title + artist) rather than the *recording* identity (title + artist + album + source + source_id + file path). A display-identity key is not a safe key for a destructive operation."

**Verdict: FALSE POSITIVE** (as a root-cause statement). Confidence: **HIGH**.
Evidence type: **source + git history**.

**Evidence.** `(title, artist)` **is** the desktop application's own track
identity, applied by its single track-creation path:

```python
# core/database.py:529-544  (DatabaseManager.add_track)
if name_is_meaningful:
    cursor.execute(
        "SELECT id, cover_url, file_path FROM tracks WHERE LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)",
        (title, artist),
    )
    row = cursor.fetchone()
    if row:
        t_id = row["id"]
        ...
        return t_id          # <-- the existing row is REUSED, not duplicated
```

`git log -S "LOWER(title) = LOWER(?)" -- core/database.py` shows that this
de-duplication rule and the destructive migration were introduced in the **same
commit**, `b6a6553` (2026-08-12, *"Update codebase to current version: restore
core modules, fix proxy/caches, …"*). Tags confirm the split: `v1.0.0`,
`v1.5.0`, `v1.5.1` (all 2026-08-09) contain **neither**; `v2.0.0`
(2026-08-13) and `cycle-2` (2026-08-19) contain **both**.

So the migration is not applying a foreign "display identity" to a data model
that uses a finer "recording identity". It is applying **the app's own
identity rule** — to libraries produced by a build that did not yet have that
rule. A row deleted by the migration is, by the application's own definition,
*the same track* as the surviving row.

**The real defect is different and narrower:** the cleanup is a **blind
`DELETE` instead of a merge**, and `ON DELETE CASCADE` then propagates that
deletion into the user's listening history and playlist membership. The
recommended fix in the original audit ("scope the grouping to the recording
identity") would, on this evidence, introduce a *new* inconsistency with
`add_track`, and the original audit's own note — *"never delete a row that a
`history` row references"* — is the correct kernel.

**Consequence for severity.** The affected population is not "every existing
user"; it is "users whose library was written by a build predating
`b6a6553`" — i.e. v1.x users upgrading to v2.0.0, or anyone whose library sat
unopened across 2026-08-12. Users who have already run v2.0.0+ have already
been hit, irreversibly, and the remaining at-risk population is shrinking with
every launch.

---

## FP-3 — P0-01's stated **causal story** for the playlist-membership loss: "each deleted track takes its **history rows** and its **playlist entries** with it" (i.e. by the foreign-key cascade).

**Verdict: OVERSTATED / MECHANISM WRONG.** Confidence: **HIGH**. Evidence
type: **runtime reproduction** (arbiter + verifier A, independently).

**Evidence — arbiter reproduction** (throwaway SQLite DB; the three `DELETE`
statements were extracted *verbatim from `core/database.py`* so the test cannot
drift from the shipped code —
`C:\Users\<user>\AppData\Local\Temp\opencode\arbiter_dup_repro2.py`):

```
extracted 3 DELETE statements from core/database.py

BEFORE: tracks=[(10, 'Song', 'Artist', 'x'), (11, 'song', 'artist', 'y')]
BEFORE: playlist_tracks=[(100, 1, 11), (101, 1, 10)]
BEFORE: history=[(1, 10), (2, 11)]

AFTER : tracks=[(10, 'Song', 'Artist', 'x')]        <- track 10 SURVIVED
AFTER : playlist_tracks=[]                          <- its playlist entry is GONE
AFTER : history=[(1, 10)]

>> track 10 SURVIVED the migration but its playlist entry count is now 0
>> => playlist entry for a SURVIVING track was destroyed: YES
```

And with a full fixture (arbiter reproduction 1, 6 tracks / 2 playlists /
6 history rows):

```
BEFORE : tracks=6  history=6  playlist_tracks=12
AFTER  : tracks=2  history=2  playlist_tracks=4
playlist membership LOST: [(1,2),(1,3),(1,5),(1,6),(2,2),(2,3),(2,5),(2,6)]
```

Verifier A's independent run separates the two mechanisms with foreign keys
**on** and **off**:

```
foreign_keys = 1
  stmt1 (:317) exact-duplicate (playlist_id,track_id) pairs removed : 2  -> pt=8
  stmt2 (:327) title+artist dup entries within a playlist removed  : 4  -> pt=4
  stmt3 (:344) track rows deleted                                    : 6  -> pt=3
  history rows left : 4     ORPHANED playlist_tracks : 0

foreign_keys = 0
  stmt1 : 2  -> pt=8
  stmt2 : 4  -> pt=4
  stmt3 : 6  -> pt=4
  history rows left : 10    ORPHANED playlist_tracks : 1
```

i.e. with foreign keys **disabled** the `playlist_tracks` loss is *identical* —
**the cascade accounts for none of the bulk of the playlist loss**. The
playlist rows are removed by the migration's own two explicit
`DELETE FROM playlist_tracks` statements, which run *before* the track
deletion and are keyed on `LOWER(title), LOWER(artist)` **within a playlist**.
The history loss, by contrast, *is* the cascade (10 rows survive with
`foreign_keys=0`, 4 with it on).

**Consequences.**

* The audit's mechanism sentence for the playlist half is wrong; the
  *magnitude* claim (playlist entries are lost) is right.
* The audit **missed a strictly worse loss mode**: because statement 2 keeps
  `MIN(playlist_tracks.id)` per `(playlist, LOWER(title), LOWER(artist))` group,
  it can delete the playlist entry of a track that **survives** the migration
  (demonstrated above). The playlist then contains **no entry at all** for that
  song, even though the track is still in the library and still playable. The
  audit described only the cascade path.
* `play_count` **is** lost (it is a column of the deleted row, and nothing
  recomputes it) — that part of the audit is right.

---

## FP-4 — P3-10: "`configure()` fires the user-interaction side effects on every audio-settings change while the queue is ended" — *"Changing any audio setting can cancel an in-flight queue selection"*.

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`player/DualDeckPlayer.kt:118-123` — `configure()` does **not** call
`command()` and does **not** call `onUserInteraction()`:

```kotlin
fun configure(value:AudioSettings) {
    val normalized=value.normalized()
    if(normalized.crossfadeSeconds!=settings.crossfadeSeconds)cancelTransition()
    settings=normalized;effects.configure(normalized);applyVolumes()
    if(!normalized.autoplay)finishIfEnded()          // <-- the only route to onUserInteraction
}
```

The only path to `onUserInteraction()` is `finishIfEnded()` →
`pauseForReason()` (`DualDeckPlayer.kt:139-142`, `:256-258`), which requires
**autoplay to be off** (the default) **and** the active deck to be in
`Player.STATE_ENDED`. An arbitrary audio-settings change while a queue is
merely *selected* does not reach the gate. The defect exists in a much
narrower form than the row states.

---

## FP-5 — P3-42: "Three directional icons are the non-auto-mirrored variants" (with the fix "use `Icons.AutoMirrored.*`").

**Verdict: OVERSTATED — the count is 2, not 3.** Confidence: **HIGH**.
Evidence type: **jar inspection** (verifier A listed the auto-mirrored icon
classes in `material-icons-core-release-api.jar` / `-extended-…` for
BOM 2026.09.00).

The auto-mirrored set is exactly
`{ArrowBack, ArrowForward, ExitToApp, KeyboardArrowLeft, KeyboardArrowRight, List, Send}`.
`Sort` has **no** auto-mirrored variant and is not directional, so the
recommended fix cannot be applied to it. The row's own parenthetical — that
`SkipPrevious`/`SkipNext` have no auto-mirrored variant — is correct.

Real defect: **2** icons (`Icons.Outlined.ArrowForward`,
`Icons.Outlined.ArrowBack`) in an app that declares `supportsRtl="true"`.

---

## FP-6 — P3-39: "The Profile screen can hold **18** simultaneous glass surfaces".

**Verdict: OVERSTATED / not derivable.** Confidence: **MEDIUM**. Evidence
type: **static**.

Static `.glass(` call sites on the Profile path = **7** (5 in
`ui/ProfileScreen.kt`, 2 in `ui/ProfileComponents.kt`). The runtime instance
count depends on the number of history rows rendered and can reach roughly 23.
The figure "18" cannot be reproduced from the source. The *substantive* claims
in the row — an animated indicator inside a `.glass()` surface, one independent
`hazeEffect` node per `.glass()` call with `blurRadius = 22.dp`, and a nested
`glass(12.dp)` inside `glass(14.dp)` in `ui/LibraryScreen.kt:163-164` — are
all confirmed.

---

## FP-7 — P3-37: "The track-row pattern is implemented twice and the 'glass list row' four times".

**Verdict: OVERSTATED on the second count; the row is a refactor request, not
a defect.** Confidence: **MEDIUM**. Evidence type: **static**.

The track-row duplication (2 implementations) and the observable drift (the
Profile "Топ треков" row has no overflow menu, no favourite toggle and no
now-playing highlight) are confirmed. There are **10** glass-bearing
row/tile components in `ui/`, so "four times" understates the duplication
while presenting itself as an exact count. The row is a code-organisation
request; the *observable* part is the drift.

---

## FP-8 — P3-50: "Switching to the lyrics tab discards the already-loaded lyrics and re-shows the spinner".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/PlayerScreen.kt:41` → `model.loadLyrics()` → `loadLyricsInternal(false)`
republishes `LyricsState(id, loading = true)`, which **is** the defect
claimed. But the lyrics are **not** re-downloaded: the in-memory LRU
(`data/Sources.kt:211`) or the disk cache (`data/LyricsDiskCache.kt`) restores
them within a frame or two. The observable artefact is a **spinner flash** on
every visit to the tab, not a refetch and not a loss of the text.

---

## FP-9 — P3-02: "`READ_MEDIA_AUDIO` is requested with no rationale, and after a permanent denial there is no route to Settings" — impact "*the button silently does nothing*".

**Verdict: PARTLY OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/MainActivity.kt:112-114, 124-126`: there is no rationale, no
"already asked" flag (the notification path has one at `:115`) and no
"open app settings" action — that part is right. But a message **is** shown
("Доступ к музыке не разрешён. Можно выбрать отдельные файлы"), so "the
button silently does nothing" is wrong; what is missing is the rationale, the
flag and the route to settings.

---

## FP-10 — P3-07: "Three always-on timers keep ~6 120 main-thread wake-ups per hour alive for the whole life of the service … The process can never go fully idle."

**Verdict: PARTLY OVERSTATED — the number is right.** Confidence: **HIGH**.
Evidence type: **static + arithmetic**.

720/h (5 s checkpoint) + 1 800/h (2 s autoplay) + 3 600/h (1 s deck tick) =
**6 120/h**, confirmed, and it is a *floor* (the deck tick is 200 ms during a
crossfade and 40 ms during a fade). All three loops run on
`Dispatchers.Main.immediate`. But they live in the `MediaSessionService` and
die with it (`player/PlaybackService.kt:344` `onTaskRemoved` → `stopSelf`), so
"the process can never go fully idle" is wrong.

---

## FP-11 — P3-03: "The one-shot UI message channel is a `StateFlow`, so a repeated identical message is conflated away and **never** shown".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/MusicViewModel.kt:79` is a `MutableStateFlow<String?>` and
`MutableStateFlow` conflates equal values — the mechanism is right. But
`ui/MusicApp.kt:54` resets the message to `null` only *after* `showSnackbar`
returns, so the conflation window is bounded by the snackbar's display time. A
second identical failure inside that window emits nothing; one outside it does.
"Never shown" is wrong.

---

## FP-12 — P3-16: "the desktop import writes its rows one at a time, with no batching … on the order of 420 000 individual SQLite statements".

**Verdict: OVERSTATED in the wrong direction (the true figure is larger).**
Confidence: **HIGH**. Evidence type: **arithmetic recomputation**.

At the documented caps: 20 000 tracks (one `putAll`), 2 000 playlists,
100 000 links, 100 000 history rows × **3** statements each (`putSession` =
SELECT + INSERT + UPDATE, `data/Models.kt:138-145`) and 100 smart playlists
= **≈ 422 100** statements inside one transaction. The order of magnitude is
right; the "no batching" framing understates the history path, which is
batched for tracks but not for sessions.

---

## FP-13 — P3-01: "Persistable URI grants are never released … At the platform cap `takePersistableUriPermission` throws and the user can no longer import or re-link any file — with no in-app recovery".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

The mechanism is confirmed: 3 `takePersistableUriPermission` call sites and
**0** `releasePersistableUriPermission` call sites in the whole tree. But the
platform cap is 128 grants per app, and the resulting `SecurityException` is
**caught** and reported ("Часть файлов нельзя сохранить…",
`ui/MainActivity.kt:55, 80, 97`) — it is not a crash, and MediaStore scans
take no grants at all.

---

## FP-14 — P3-15: "Column names taken from the untrusted desktop file are interpolated into SQL unquoted" — the bound as stated.

**Verdict: CORRECT with a clarification.** Confidence: **HIGH**. Evidence
type: **static**.

The *table* names are hard-coded literals (`data/DesktopLibraryImport.kt:65-69`);
only the *column* names come from the untrusted copy's own `PRAGMA table_info`
(`:46`) and are interpolated unquoted (`:50`). The stated bound — read-only
copy, `rawQuery` compiles only the first statement, outcome is the
"Не удалось прочитать БД…" message — is accurate.

---

## FP-15 — P3-87: "`REVIEW_RESOLUTION.md` has already rotted: a row's factual premise is false in the current code" — *"The row states that the app does **not** request `POST_NOTIFICATIONS`; the current tree **does** declare the permission and requests it at runtime. The same document says so 50 lines earlier."*

**Verdict: FALSE POSITIVE** (the alleged contradiction does not exist).
Confidence: **HIGH**. Evidence type: **source + document**.

The document is **self-consistent**:

* `android/review/REVIEW_RESOLUTION.md:14-16` states that stage 0.2.0
  **added** a `POST_NOTIFICATIONS` request, for the download/data-sync
  notifications.
* `:66` is a **different** claim: media-session notifications are exempt
  from the runtime prompt, and no *extra* prompt was added for the single
  media notification.

The row reads one line as a contradiction of another. It is not. The
underlying observation — that the resolution table has no "verified on
snapshot `<sha>` / <date>" column, so a row's premise can rot without the
table showing it — is a valid **maintenance recommendation** and is
retained, but the claim that a specific row is *already* factually false is
wrong.

---

## FP-16 — P3-99: "The Android's library search covers only device files and completed downloads; the desktop's FTS search covers the whole library" — *"A track played from an online search and added to a playlist is invisible in the Android's device/library search."*

**Verdict: FALSE POSITIVE** (the claimed trigger does not hold).
Confidence: **HIGH**. Evidence type: **static**.

The local search is **not** restricted to device files and completed
downloads. `data/Models.kt:104-105` is:

```sql
SELECT id,title,artist FROM tracks
WHERE localUri!='' OR id IN (SELECT trackId FROM offline_downloads WHERE state='complete')
ORDER BY addedAt DESC LIMIT :limit OFFSET :offset
```

— but the *paged scan* (`data/LibraryRepository.kt:55-67`) pages
`dao.searchPage(500, offset)` over the **whole `tracks` table**, and the
Kotlin filter (`data/LibraryRepository.kt:61`) then tests only the text.
Every track that was ever played (`preparePlayback` → `dao.ensureTracks` +
`dao.remember`, `ui/MusicViewModel.kt:161`) or added to a playlist
(`addToPlaylist` calls `remember(track)` first) **is** a row in `tracks` and
therefore **is** matched.

The real local-search defect is the **missing `album` dimension**
(MAIN-P2-43 / P3-25) — a different finding. The desktop's FTS search is
broader than the Android's `LIKE` scan, but not along the axis the row
claims.

---

## FP-17 — P3-90's counts: "35 of the 75 production files (3 977 LOC, 54.6 %) have **no** JVM test"

**Verdict: OVERSTATED / not reproducible.** Confidence: **HIGH**. Evidence
type: **measured**.

The *contract* half of the row — "5 of the 10 non-negotiable contracts have
zero automated coverage of any kind" — is **reproduced**. The *coverage
metric* half is not:

| Measure | Audit | Measured (strict rule: a `<Name>Test.kt` exists) | Measured (loose rule: any test references the class) |
|---|---|---|---|
| uncovered production files | 35 of 75 | **38 of 75** | 26 of 75 |
| uncovered LOC | 3 977 | **4 618** | 2 984 |
| share of production code | 54.6 % | **63.4 %** | 41.0 % |
| files the 236 tests cover | 40 | 37 | 49 |

The total (75 files, **7 282 LOC** / 6 970 non-blank) and the test count
(236) are correct; the **subset** is not reproducible under either rule, and
the report's "40 files" is simply `75 − 35` rather than a measured set.

The direction of the error matters: under the strict rule the *true* gap is
**larger** than reported (63.4 % vs 54.6 %).

---

## FP-18 — REG P2-10: "Replacing the current `MediaItem` in place is reported by Media3 as a media-item *transition*, splitting one listen into two sessions and marking the first 'completed'"

**Verdict: FALSE POSITIVE** (as to the claimed impact). Confidence: **HIGH**.
Evidence type: **bytecode** (Media3 1.11.1 `media3-exoplayer-1.11.1.aar`) +
the upstream source + the project's own `ListeningHistoryTest`.

**The claim.** `refreshQueueSources` swaps the current queue entry for the same
track with a different `MediaItem` (a different URI: `nedotify://track/<id>` →
`nedotify-offline://track/<id>`, plus an `OfflineAsset` tag) via
`player.replaceMediaItem(index, item)`. The audit asserted:

> "A different URI means a different `MediaSource`, hence a different window
> uid, hence Media3 reports it through `onMediaItemTransition` — which the
> service interprets as 'the user moved to another track'.
> `MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED` is the **only** reason for
> which `forceNewSession` can be false, and in Media3 1.11.1 that reason is
> emitted **only when the player was not playing**. So while playing, a source
> replacement always yields `AUTO`/`SEEK` → `forceNewSession = true` **and**
> `completedPrevious = true`. … the branch that implements that contract is
> unreachable for an in-place replacement."

**The refutation — `ExoPlayerImpl` bytecode (Media3 1.11.1).**

```
ExoPlayerImpl.replaceMediaItems(int,int,List):
 46: canUpdateMediaSourcesWithMediaItems:(IILjava/util/List;)Z
 50: ifeq 64                       -> false (the LocalConfiguration uid differs)
104: addMediaSourcesInternal(...)  -> 117: removeMediaItemsInternal(...)
127: newPlaybackInfo.periodId.periodUid  vs  playbackInfo.periodId.periodUid -> equals? -> positionDiscontinuity
161: iconst_0    // timelineChangeReason = TIMELINE_CHANGE_REASON_PLAYLIST_CHANGED
162: iload 7     // positionDiscontinuity
164: iconst_4    // positionDiscontinuityReason = DISCONTINUITY_REASON_REMOVE (4)
173: invokespecial updatePlaybackInfo:(PlaybackInfo;IZIJIZ)V

ExoPlayerImpl.evaluateMediaItemTransitionReason(…):
157: iload_3 (positionDiscontinuity) ; ifeq 172
161: iload_4 (reason) ; ifne 172
166: reason = 1   // AUTO          (positionDiscontinuity && reason == DISCONTINUITY_REASON_AUTO_TRANSITION)
172: iload_3 ; ifeq 188
176: iload_4 ; iconst_1 ; if_icmpne 188
182: reason = 2   // SEEK          (positionDiscontinuity && reason == DISCONTINUITY_REASON_SEEK)
188: iload_5 (timelineChanged) ; ifeq 199
193: reason = 3   // PLAYLIST_CHANGED
199: throw new IllegalStateException()
```

The upstream `main`-branch source matches this bytecode **exactly**:

```java
if (positionDiscontinuity && positionDiscontinuityReason == DISCONTINUITY_REASON_AUTO_TRANSITION) {
  transitionReason = MEDIA_ITEM_TRANSITION_REASON_AUTO;
} else if (positionDiscontinuity && positionDiscontinuityReason == DISCONTINUITY_REASON_SEEK) {
  transitionReason = MEDIA_ITEM_TRANSITION_REASON_SEEK;
} else if (timelineChanged) {
  transitionReason = MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED;
} else { throw new IllegalStateException(); }
```

**Consequences.**

* The predicate contains **no play-state term at all**. The audit's
  "emitted only when the player was **not** playing" is not a property of
  Media3 1.11.1.
* `replaceMediaItems` reports `DISCONTINUITY_REASON_REMOVE (4)`, which is
  neither AUTO_TRANSITION nor SEEK — so the **`timelineChanged`** branch is
  taken and the reason is **`PLAYLIST_CHANGED`**, whether the player is
  playing or paused.
* Therefore, in the app's listener
  (`player/PlaybackService.kt:110-117`):
  `completedPrevious = (reason==AUTO || reason==REPEAT)` = **false**, and
  `forceNewSession = newQueue || reason != PLAYLIST_CHANGED` = **false** →
  `history.transition(mediaId, false, false)` → `player/ListeningHistory.kt:17`
  `if(!forceNewSession && id==trackId){checkpoint(false); return}` — i.e.
  **the same session continues, is not marked completed, and the elapsed
  time is preserved.**
* The app's own unit test pins exactly this contract:
  `ListeningHistoryTest."same recording source replacement keeps one measured
  session but explicit replay starts another"`.

**So the branch the audit called "unreachable" is the *only* branch an
in-place replacement reaches, and the reported symptom (two sessions, the
first `completed = 1`) does not occur.**

**A SECOND, INDEPENDENT BYTECODE PASS REACHED THE SAME CONCLUSION, AND
FOUND THE REGISTER'S POLARITY BACKWARDS.** The full predicate is

```
if (positionDiscontinuity && reason == 0) -> MEDIA_ITEM_TRANSITION_REASON_AUTO
else if (positionDiscontinuity && reason == 1) -> MEDIA_ITEM_TRANSITION_REASON_SEEK
else if (timelineChanged) -> MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED
```

and the replace path calls `updatePlaybackInfo(…, TIMELINE_CHANGE_REASON_PLAYLIST_CHANGED,
positionDiscontinuity = (periodUid changed), positionDiscontinuityReason = 4 = DISCONTINUITY_REASON_REMOVE, …)`.
Reason 4 matches neither AUTO nor SEEK, so the `timelineChanged` branch is
taken ⇒ **PLAYLIST_CHANGED**. The audit's *"in Media3 1.11.1 it is emitted
only when the player was **not** playing"* is the **exact inverse** of the
truth: PLAYLIST_CHANGED is what a **playing** playlist edit produces, because
the discontinuity reason for a playlist edit is REMOVE(4), not AUTO_TRANSITION(0)
or SEEK(1). A further check: the post-replace `player.seekTo(index, position)`
adds **no** second transition, because `BasePlayer.seekTo` passes
`isRepeatingCurrentItem = false` and the SEEK branch requires it to be true.
The repository's own green `ListeningHistoryTest` and the main report's own
P3-05 agree with the refutation.

**What survives.** An in-place replacement *does* emit
`onMediaItemTransition` (reason PLAYLIST_CHANGED), so the service's
transition listener runs on every source refresh; and `explicitQueueBoundary`
is a one-shot flag consumed only by a transition, so a queue set that
produces no transition could let a later refresh be mis-attributed as an
explicit boundary. That is a *different* and much smaller risk (it is the
kernel of P3-05).

**Revised severity:** P2 → **P3** (the residual flag-handling risk only).

---

## FP-19 — REG P2-09: "`Loader.cancelLoading()` … does **not** interrupt the executor thread"

**Verdict: FALSE POSITIVE** (this sub-claim). Confidence: **HIGH**. Evidence
type: **bytecode** (Media3 1.11.1 `media3-exoplayer`).

**The claim.** *"Media3's `Loader.cancelLoading()` only calls
`LoadTask.cancel(false)` → `onLoadCanceled()` and does **not** interrupt the
executor thread (verified in the 1.11.1 bytecode)."*

**The refutation.**

```
androidx.media3.exoplayer.upstream.Loader
  public void cancelLoading();
    10: iconst_0
    11: invokevirtual Loader$LoadTask.cancel:(Z)V

androidx.media3.exoplayer.upstream.Loader$LoadTask.cancel(boolean):
   6: hasMessages(1) ; ifeq 41
  15: canceled = true ; removeMessages(1)
  26: iload_1 (interrupt) ; ifne 84
  29: sendEmptyMessage(2)                  // MSG_CANCEL, no interrupt
  41: synchronized(this) {
  46:     canceled = true
  50:     loadable.cancelLoad()
  59:     executorThread = this.executorThread
  64:     if (executorThread != null) 68: executorThread.interrupt()   <-- it DOES interrupt
```

When a load is already running (`hasMessages(MSG_LOAD) == false`),
`cancel(false)` **does** call `executorThread.interrupt()`. The
`onLoadCanceled()` naming belongs to the older `androidx.media3.datasource.Loader`
API; in 1.11.1 the class is `androidx.media3.exoplayer.upstream.Loader` and
there is no such callback on this path.

**What survives.** The `runBlocking` coroutine is **not** a child of the
loader's job, so the *network resolution itself* keeps running to completion
in the background and the `StreamCache` single-flight slot stays occupied
until it does. The **loader thread**, however, is released by the interrupt
rather than pinned for the full 15 s — the audit's "the loader thread stays
parked" is over-stated.

**Revised severity:** P2 → **P3** (the orphaned resolution coroutine and the
occupied single-flight slot are real; the pinned loader thread is not).

---

## FP-20 — REG P2-11's Media3 rationale: "`SessionResult.RESULT_SUCCESS` … Media3 answers the controller at *enqueue* time"

**Verdict: FALSE POSITIVE** (the rationale; the app-side observation
survives). Confidence: **HIGH**. Evidence type: **bytecode**.

**The claim.** *"The play is refused at the player level but reported as
accepted at the session level"* — because *"`onPlayerCommandRequest` returns
`SessionResult.RESULT_SUCCESS` unconditionally and Media3 answers the
controller at *enqueue* time (`MediaSessionStub.queueSessionTaskWithPlayerCommand`
→ `onPlayerCommandRequestOnHandler` → `addToCommandQueue`)"*.

**The refutation.**

```
androidx.media3.session.SessionResult (1.11.1)
  public static final int RESULT_SUCCESS = 0;
  public static final int RESULT_INFO_SKIPPED = 1;
  public static final int RESULT_ERROR_UNKNOWN = -1;
  public static final int RESULT_ERROR_INVALID_STATE = -2;

androidx.media3.session.MediaSessionStub.queueSessionTaskWithPlayerCommand:
  75: aload 5 (sessionImpl) ; 77: aload_1 (controller) ; 78: iload_3 (playerCommand)
  79: invokevirtual MediaSessionImpl.onPlayerCommandRequestOnHandler:(ControllerInfo;I)I
  82: istore 6 (result)
  84: iload 6
  86: ifeq 106        // result == 0  -> QUEUE the command for the player
  89: sendSessionResult(sessionImpl, controller, seq, new SessionResult(result)) ; return
 106: …
 151: connectedControllersManager.addToCommandQueue(controller, playerCommand, asyncCommand)
```

`RESULT_SUCCESS` is **0**, and a 0 return means *"not handled by the session
— queue the command for the player"*, which is the **opposite** of the
audit's reading. The app's unconditional `RESULT_SUCCESS` is the **normal
Media3 idiom** and is exactly why the app's play/pause works at all. The
controller is **not** answered at enqueue time: the enqueue path returns 0
precisely so that the command is queued, and the controller receives the
result of the **queued command after the player executes it**.

The correct chain is
`queueSessionTaskWithPlayerCommand` → `onPlayerCommandRequestOnHandler` →
`addToCommandQueue` → *the player executes* →
`DualDeckPlayer.handleSetPlayWhenReady` → `Futures.immediateVoidFuture()` →
the controller is told "success". The audit's chain notation also has the
two steps in the wrong order relative to the branch structure.

**What survives.** The app-side observation is unchanged: a closed gate
swallows the Play with **no error, no state change**, and the controller is
told "success" — because the refusal is a *successful* future from
`DualDeckPlayer` and the session layer never learns about it. Only the
rationale is wrong. See FP-1 for the separate, larger refutation of the
"the gate is stuck" headline.

---

## FP-21 — REG P2-07's fix-side-effect citation: "`ListeningReportsDaoTest.checkpointsAndTrackMetadataUpdateAnAlreadyCollectedReport` … explicitly asserts that a `putSession` immediately updates an already-collected report — that test would need relaxing".

**Verdict: FALSE POSITIVE** (the cited test does not exist). Confidence:
**HIGH**. Evidence type: **static** (repository-wide search of the test tree).

The file is `android/app/src/test/java/ru/nedotify/app/data/ListeningReportsTest.kt`
(10 pure-calendar/aggregate tests, **no** Room DAO). A search of the whole
test tree for `checkpointsAndTrackMetadata`, `AlreadyCollectedReport` and
`ListeningReportsDao` returns **nothing**.

The finding itself (the report is recomputed every 5 s while playing) is
**confirmed** — the numbers were independently recomputed: 365 `CASE` arms,
**731** bound arguments, a 10 001-character SQL, and the `@RawQuery`
invalidation on `ListeningSession` (the `history` table). But the
"a test would need relaxing" argument rests on a test that is not there, so
**there is currently no test pinning immediate freshness** — the throttle
can be introduced without breaking a test, and a reviewer should add one for
the intended contract.

**Also corrected:** with `ReportPeriod.ALL` the snapshot runs **five**
queries, not six (`reportSnapshot` skips the previous-window `reportTotals`
when `previousStartInclusive == null`, `data/Models.kt:171-172`); six is the
WEEK/MONTH count. And "13.3 M integer comparisons" is *per query pass* —
with four full-scan passes it is ~53 M per refresh, so the register's figure
understates by 4× if read as "per refresh".

---

## FP-22 — REG P2-14's citation: "the destination-side hashing (`data/LibraryRepository.kt:72-74`)".

**Verdict: WRONG CITATION** (the finding is confirmed). Confidence: **HIGH**.
Evidence type: **static**.

`data/LibraryRepository.kt:72-74` is `LibraryRepository.resolve`, not the
restore path. The restore-side hashing is `data/BackupMerge.kt:7-13`
(`localIds` grouped by `BackupCodec.portableTrackId(it, libraryId)` — the
**destination** library id), together with `data/Models.kt:93-101` and
`data/LibraryBackupStorage.kt:44-50`.

The finding's substance is confirmed: the two hashes can never match across
devices, the incoming row is inserted as a new `portable-local:<hash>` track
with an empty `localUri`, `putAll(plan.tracks)` adds it while the
destination's own `local:<mediaStoreId>` row is untouched (it is not in
`plan.tracks`), and the DAO exposes **no** `DELETE FROM tracks` and the UI
exposes no track-deletion affordance.

Two further precision points the register omits: the duplication is an
emergent property of `putAll(plan.tracks)`, not of an explicit "insert
duplicate" step; and `portableTrackId` lowercases the library id
(`libraryId.lowercase(Locale.ROOT)`) before hashing.

---

## FP-23 — REG P2-12's proposed fix contradicts the repository's own contract test.

**Verdict: the finding is CONFIRMED; the proposed fix is a behaviour change
that the repo's pinned test currently forbids.** Confidence: **HIGH**.
Evidence type: **static + the executed unit suite**.

`android/app/src/test/java/ru/nedotify/app/player/PendingSelectionGateTest.kt:28-29`
(executed, green):

```kotlin
assertTrue(reason, gate.interruptPending())
assertTrue(future.isCancelled)
```

and the class's own KDoc (`player/PendingSelectionGate.kt:6-8`):

> "Media3 1.11.1 queues commands per controller and calls
> `onPlayerCommandRequest` at enqueue time. **Cancelling a set future
> releases that controller's already queued prepare/play.** Such an older
> play must not undo another controller's pause/noisy."

The register's fix — *"`interruptPending()` should close the gate without
cancelling the set future"* — therefore changes a **deliberate, pinned**
behaviour rather than preserving an invariant. The finding's *diagnosis* is
right; its *remedy* must be re-specified around that contract (e.g. a
separate "play abort" token decoupled from the "set" future), and the test
must be updated deliberately in the same change.

---
