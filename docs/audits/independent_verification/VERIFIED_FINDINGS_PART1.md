# VERIFIED FINDINGS — per-finding verification record

Format per finding: **id В· original severity В· revised severity В· Verifier A
result В· Verifier B result В· Arbiter result В· Final verdict В· Confidence В·
Evidence type В· relevant source paths В· execution path В· trigger conditions В·
evidence В· executed reproduction В· actual result В· limitations В· root cause В·
recommended resolution В· potential regressions.**

"Verifier A" = code & runtime verifier. "Verifier B" = adversarial reviewer
(never shown A's output). "Arbiter" = this session, which re-derived every
disputed fact from the artefacts (bytecode / re-execution) rather than
counting agreeing agents.

---

# PART 1 — P0 and P1

---

## P0-01 — The one-shot desktop startup migration deletes tracks and cascades away history and playlist entries

**Original severity:** P0 В· **Revised severity:** **P1** (data loss is real
and irreversible, but the affected population is narrower than claimed and the
stated root cause is wrong)

**Verifier A result:** mechanism **confirmed by runtime reproduction**;
population and recoverability measured; root cause **restated** as "a blind
`DELETE` where a merge was required".

**Verifier B result:** mechanism confirmed; the *identity-key* argument
**refuted**; the *cascade* causal story for playlist loss **refuted**; the
affected population **narrowed** to pre-`b6a6553` libraries.

**Arbiter result:** independently reproduced (two throwaway databases, one of
which extracts the statements verbatim from `core/database.py`); independently
established that `(LOWER(title), LOWER(artist))` **is the app's own track
identity** (`core/database.py:529-544`, introduced in the same commit as the
migration); independently established that the bulk of the playlist loss is
**not** the cascade.

**Final verdict:** **CONFIRMED — RUNTIME** (the data loss), with the cause and
the causal story **corrected** (FP-2, FP-3).

**Confidence:** HIGH В· **Evidence type:** runtime (arbiter + verifier A) +
static + git history

**Relevant source paths:** `core/database.py:313-362` (the block), `:314-315`
(flag check), `:317-326` (statement 1), `:327-343` (statement 2), `:344-357`
(statement 3), `:358-360` (flag write), `:119` (`PRAGMA foreign_keys=ON`),
`:194-195` and `:208` (the two `ON DELETE CASCADE` clauses), `:465`
(`conn.commit()`), `:529-544` (`add_track`'s own de-duplication rule).

**Execution path:** `main.py` в†’ `core/app.py` в†’ `DatabaseManager.__init__` в†’
`_init_database()` в†’ the flag check в†’ the three `DELETE`s в†’ the flag insert в†’
`conn.commit()` at `:465`.

**Trigger conditions (all three required):**
1. the `settings` table has no `migration_dup_cleanup_done` row — i.e. the
   library was written by a build predating commit `b6a6553` (2026-08-12), or
   the flag insert failed;
2. `tracks` contains в‰Ґ 2 rows with equal `LOWER(title)` and equal
   `LOWER(artist)`;
3. the app starts.

A **fresh** library is unaffected (an empty `tracks` makes the `DELETE`s
no-ops) and has the flag burned on first open.

**Evidence — arbiter reproduction #1** (throwaway DB; the statements were
extracted verbatim from `core/database.py`, so the test cannot drift from the
shipped code):

```
BEFORE : tracks=6  history=6  playlist_tracks=12
AFTER  : tracks=2  history=2  playlist_tracks=4
playlist membership LOST: [(1,2),(1,3),(1,5),(1,6),(2,2),(2,3),(2,5),(2,6)]
```

**Evidence — arbiter reproduction #2** (a playlist entry belonging to a track
that **survives**):

```
BEFORE: tracks=[(10,'Song','Artist','x'), (11,'song','artist','y')]
BEFORE: playlist_tracks=[(100,1,11), (101,1,10)]
AFTER : tracks=[(10,'Song','Artist','x')]      <- 10 SURVIVED
AFTER : playlist_tracks=[]                    <- its playlist entry is GONE
>> playlist entry for a SURVIVING track was destroyed: YES
```

**Evidence — verifier A's foreign-key on/off separation** (isolated
statements, own fixture):

```
foreign_keys = 1
  stmt1 (:317) exact-duplicate (playlist_id,track_id) pairs removed : 2
  stmt2 (:327) title+artist dup entries within a playlist removed  : 4
  stmt3 (:344) track rows deleted                                    : 6
  history rows left : 4      ORPHANED playlist_tracks : 0
foreign_keys = 0
  stmt1 : 2   stmt2 : 4   stmt3 : 6
  history rows left : 10     ORPHANED playlist_tracks : 1
```

в‡’ with foreign keys **off** the `playlist_tracks` loss is *identical*: the
**cascade accounts for none of the bulk of the playlist loss**. The history
loss *is* the cascade (10 rows survive with FK off, 4 with FK on).

**Actual result.**

* **Real and irreversible:** a track row, its `history` rows, its playlist
  entries, its `play_count`, its `is_favorite`, its `is_downloaded` /
  `file_path`, its `last_played` and its `metadata_json` are destroyed; the
  audio file stays on disk, referenced by nothing. No backup table, no undo,
  no UI report, and the desktop has **no backup feature at all** (verified:
  zero backup/export methods in `core/api.py`).
* **The surviving track can also lose its playlist entry** — a loss mode the
  original audit did not identify.
* **The affected population is narrower than "every existing user".** Tags:
  `v1.0.0`, `v1.5.0`, `v1.5.1` (2026-08-09) contain neither the migration
  nor the de-duplication rule; `v2.0.0` (2026-08-13) and `cycle-2`
  (2026-08-19) contain both. Users who have already run v2.0.0+ have already
  been hit, irreversibly; the remaining at-risk population is users whose
  library predates 2026-08-12 and who have not launched since.
* **Silent:** `logger.debug` is below the production root level (INFO), so
  nothing is emitted in a normal run (verifier A executed both levels and
  captured the output).
* **Failure is not atomic:** the three `DELETE`s are inside
  `try/except Exception: logger.debug(...)`, and the transaction is committed
  by the unconditional `conn.commit()` at `:465` — so a mid-block failure
  leaves a **half-migrated** database and the flag unset, i.e. the block
  re-runs on every subsequent start.

**Limitations.** The user's real `~/.nedotify/` was never opened, so the
number of affected rows in the real library is unmeasured. Whether a
pre-2026-08-12 database's `history` table carried the `ON DELETE CASCADE`
clause (the clause and the migration landed in the same commit) could not be
determined — with FK off, history rows are **orphaned** rather than deleted
(verifier A demonstrated that shape). The normal path is healthy
(`PRAGMA integrity_check=ok`, FTS `integrity-check=ok`) and the migration is
idempotent on already-cleaned data.

**Root cause (corrected).** Not a wrong identity key — `(title, artist)` *is*
the app's own identity — but a **destructive** operation where a **merge**
was required: the duplicate rows are `DELETE`d instead of being folded into
the survivor, `ON DELETE CASCADE` then propagates the deletion into the
user's history and playlist membership, and the cleanup's own second
statement strips playlist entries by a *playlist-local* `MIN(id)` rule that
can hit a surviving track. The `settings` flag makes it one-shot and
permanent; the sub-INFO logging makes it invisible; the missing transaction
boundary makes a failure permanent-but-partial.

**Recommended resolution (description only — not implemented).**
1. Never delete a row a `history` row references: **merge** the duplicate
   into the survivor (carry over `play_count`, `last_played`, `is_favorite`,
   `file_path`, `cover_url`, `source_id`, `duration`) or mark it
   (`is_duplicate_of`) rather than deleting it.
2. Snapshot before the destructive statement (`CREATE TABLE tracks_backup AS
   SELECT * FROM tracks`) and keep it.
3. Make the block atomic; write the flag only after a successful commit.
4. Fix or drop statement 2 — it can remove a **surviving** track's playlist
   entry and is not needed for track de-duplication.
5. Log at `warning`/`error` and surface the result in the UI.
6. Ship a corrective migration that restores from a backup table where one
   exists; for users who already ran the destructive migration there is no
   backup, so state that plainly and offer a library re-scan.

**Potential regressions of a fix.** Genuine duplicates stay visible in the
library and in playlists (a visible duplicate is recoverable; a deleted
history row is not). `add_track` (`core/database.py:529-544`) still
de-duplicates on `(LOWER(title), LOWER(artist))` alone — fixing only the
migration leaves the door open for the same near-duplicates to reappear, so
the two must move together. A per-run backup table grows the DB without
bound and needs a one-shot guard. Dropping statement 2 leaves pre-existing
duplicate `(playlist_id, track_id)` rows in playlists. A consent prompt
changes the startup path between `main.py:306` and `main.py:348` and must not
deadlock with the single-instance guard at `main.py:260`. A corrective
migration that resurrects rows must be idempotent and must not resurrect
tracks the user deleted *after* the migration. Stopping the deletion changes
`get_most_played` / `get_wrapped_stats` / `get_top_artists` (all `JOIN
tracks`), so the profile numbers will differ from what today's users see.

---

## P1-01 — The lyrics identity gate rejects any track whose title is "Artist - Song"

**Original severity:** P1 В· **Revised severity:** **P2**

**Verifier A result:** mechanism confirmed; the *stated* rejection path
("the Levenshtein ratio falls to ~0.64") is **not** the one that fires.

**Verifier B result:** the finding survives, but the *reachability* argument
is weaker than stated: providers frequently echo the **full** "Artist - Song"
title, in which case the gate **accepts** the candidate.

**Arbiter result:** the `similar()` pre-check fires **before** the edit
distance is computed, so the audit's "dist/size=0.636" figure is not the
operative mechanism.

**Final verdict:** **CONFIRMED — RUNTIME** (the rule is absent), severity
revised down.

**Confidence:** HIGH (rule) / MEDIUM (frequency) В· **Evidence type:** static +
executed mirror

**Relevant source paths:** `data/LyricsCascade.kt:36-55` (`title()`),
`:60-71` (`similar()`), `:73-89` (`accept()`), `:46` (`substringAfterLast`),
`:77-78` (the gate).

**Execution path:** `LyricsCascade.lrclib/netease/qq/genius` в†’
`LyricsIdentity.accept(track, offeredTitle, вЂ¦)` в†’ `title(track.title)` в†’
`title(offeredTitle)` в†’ `wanted.version != offered.version || !similar(...)`
в†’ `return null`.

**Trigger conditions:** `track.title` contains `" - "` with a **non-version**
suffix, **and** the provider's title is the bare song name.

**Evidence — the actual rejection mechanism** (`data/LyricsCascade.kt:60-71`):

```kotlin
private fun similar(left: String, right: String): Boolean {
    if (left == right) return true
    val size = max(left.length, right.length)
    if (size == 0 || left.isBlank() || right.isBlank() || size > 512 ||
        abs(left.length - right.length) > size / 10) return false      // <-- fires here
    вЂ¦ levenshtein вЂ¦
    return previous.last().toDouble() / size <= .10
}
```

For `"artist song"` (11) vs `"song"` (4): `|11-4| = 7 > 11/10 = 1.1` в‡’ the
**length-ratio pre-check** rejects; the edit distance is never computed. The
audit's quoted `dist/size=0.636` is a different (correct-arithmetic,
wrong-mechanism) figure.

**Evidence — the title rule** (`data/LyricsCascade.kt:46-54`): the
`" - "` **suffix** is stripped only when it matches a version word; there is
**no** artist-conditioned prefix rule anywhere in the file.

**Actual result.**
* The rule is genuinely absent, and the desktop oracle
  (`services/lyrics_service.py:220-224`) really does strip the artist
  prefix — a genuine parity gap.
* The **frequency** is lower than the audit implies: a provider that echoes
  the full "Artist - Song" title is **accepted** by the gate, because
  `wanted.base == offered.base`. The defect only bites when the provider
  returns the bare song name.
* The finding therefore is **not** "lyrics are never found for those tracks"
  but "lyrics are missed for those tracks **when the provider normalises the
  title**".

**Limitations.** The provider fixtures in the repo do not settle what the
live providers return for a YouTube-derived title, so the frequency is
estimated, not measured. No device run.

**Root cause.** The Android port merged the desktop's two layers — query
cleaning (`_clean_track_and_artist`) and identity parsing (`title_metadata`)
— into one and dropped the artist-conditioned prefix rule.

**Recommended resolution (description only).** Add an **artist-conditioned**
prefix rule to the identity layer: when the segment before the last `" - "`
normalises to the track's artist, drop it from `wanted.base`. Do **not**
loosen the similarity threshold — that would weaken the false-match
protection the gate exists for.

**Potential regressions of a fix.** Dropping the prefix changes `wanted.base`
for every title containing `" - "`, including genuine titles such as
"AC/DC - Back in Black" (the prefix "ac dc" is not the artist, so it must
stay) and "Song - Part 2" (the suffix is not a version word and must stay).
The rule must be artist-conditioned, not unconditional. The desktop's
matching layer must be ported together with the identity layer, or the two
will disagree in the other direction.

---

## P1-02 — A corrupt preferences file is never repaired; no setting can ever be changed again

**Original severity:** P1 В· **Revised severity:** **P1** (unchanged) — the
write path is permanently wedged, confirmed at bytecode level.

**Verifier A result:** confirmed.
**Verifier B result:** confirmed; the trigger is rarer than the audit implies
(DataStore's write is atomic), and the recovery cost is understated.

**Arbiter result:** **independently established the write path at bytecode
level** — `DataStoreImpl$handleUpdate$2$1` contains
`instanceof androidx/datastore/core/ReadException`, a call to
`access$readAndInitOrPropagateAndThrowFailure`, and
`checkcast ReadException в†’ getReadException() в†’ athrow`.

**Final verdict:** **CONFIRMED — RUNTIME** (bytecode **and** an executed corruption scenario).

**Confidence:** HIGH В· **Evidence type:** bytecode + static

**Relevant source paths:** `data/Preferences.kt:9` (the delegate), `:14` (the
read fallback), `:38` (`saveQueue`), `:39` (`queue()`);
`data/AudioSettingsStore.kt:10`, `:18`.

**Evidence — arbiter `javap` on `datastore-core-android-1.2.0.aar`:**

```
androidx.datastore.core.handlers.NoOpCorruptionHandler
  public java.lang.Object handleCorruption(CorruptionException, Continuation);
       0: aload_1
       1: athrow                       <-- rethrows

androidx.datastore.core.CorruptionException
  public final class CorruptionException extends java.io.IOException

androidx.datastore.core.DataStoreFactory
  create(... ReplaceFileCorruptionHandler<T> ...):
      31: new  androidx/datastore/core/handlers/NoOpCorruptionHandler
      35: invokespecial <init>          <-- null handler substituted

androidx.datastore.core.DataStoreImpl$handleUpdate$2$1
     113: instanceof  androidx/datastore/core/ReadException
     150: invokestatic DataStoreImpl.access$readAndInitOrPropagateAndThrowFailure
     217: checkcast   androidx/datastore/core/ReadException
     220: invokevirtual ReadException.getReadException:()Ljava/lang/Throwable;
     223: athrow                        <-- the WRITE path re-throws
```

**Execution path:** `store.edit { вЂ¦ }` в†’ `DataStoreImpl.updateData` в†’ the
write actor в†’ `handleUpdate` в†’ the state is `State.ReadException` в†’
`readAndInitOrPropagateAndThrowFailure` в†’ `readDataOrHandleCorruption` в†’
`NoOpCorruptionHandler.handleCorruption` rethrows в†’ the exception is cached
as `ReadException` and re-thrown on every subsequent `edit`.

**Trigger conditions:** a `*.preferences_pb` that `OkioStorage`/`PreferencesSerializer`
cannot parse — a truncated file, a key whose stored proto type no longer
matches the Kotlin key type, or a byte-level corruption.

**Actual result.**
* **Read side:** survives *by accident* — `CorruptionException extends
  java.io.IOException`, so `catch { if(it is IOException) emit(emptyPreferences()) else throw it }`
  turns it into "all defaults". The app therefore *looks* healthy.
* **Write side:** every `store.edit` fails forever, and the corrupt file is
  never rewritten. The user sees the generic snackbar
  *"РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹РїРѕР»РЅРёС‚СЊ РґРµР№СЃС‚РІРёРµ"* for every setting, and the value never
  persists.
* **Recovery:** the app offers none; the only escape is clearing app data,
  which destroys the library.
* **Trigger realism:** DataStore's write is atomic (temp file + rename), so
  an interrupted write is unlikely — the realistic triggers are a
  type/schema mismatch across an app upgrade and external corruption. The
  audit's "exposure is raised by the 5 s whole-file rewrite" is a
  **throughput/energy** argument, not a corruption-probability argument, and
  should be stated as such.

**Limitations.** No device; the corruption was not injected and observed at
runtime. The DataStore write path was read from bytecode, not executed.

**Root cause.** The app relies on the read fallback only; a
`ReplaceFileCorruptionHandler { emptyPreferences() }` was never supplied, so
the library's default (rethrow) governs the write path.

**Recommended resolution (description only).** Pass an explicit
`ReplaceFileCorruptionHandler { emptyPreferences() }` to both delegates, and
surface a one-shot *"РЅР°СЃС‚СЂРѕР№РєРё СЃР±СЂРѕС€РµРЅС‹"* notice so a silent reset is not
mistaken for a fresh install.

**Potential regressions of a fix.** The corrupt file is then replaced with an
empty one, permanently discarding its contents — the intended trade-off, but
it must be announced rather than silent, and it must not be applied to the
*queue* key without a separate decision, because the queue snapshot is the
app's only durable session state.

---

## P1-03 — A single 401 from any Yandex API call destroys the user's Yandex credential

**Original severity:** P1 В· **Revised severity:** **P2**

**Verifier A result:** confirmed; the delete is *guarded* (generation + token
equality), not unconditional, but the guard holds in practice.
**Verifier B result:** the "no recovery path" claim is **overstated** — the
user can re-paste a token; the 401 is **not** fatal to the request itself
(the request throws, it is not retried for Yandex).

**Arbiter result:** read the whole `data/ProviderConnections.kt` and
confirmed the exact shape of the handler, including the fact that the
Spotify branch has a refresh-and-retry path and the Yandex branch does not.

**Final verdict:** **CONFIRMED — RUNTIME** with the mechanism refined.

**Confidence:** HIGH (mechanism) / MEDIUM (impact) В· **Evidence type:** static

**Relevant source paths:** `data/ProviderConnections.kt:166-194` (`get`),
`:187-191` (the 401 handler), `:195-204` (`postYandex`), `:203` (the POST 401
handler), `:179-186` (the Spotify refresh-and-retry path).

**Evidence:**

```kotlin
// ProviderConnections.kt:187-191
if(error.httpCode==401)withContext(Dispatchers.IO){lock.withLock {
    if(provider=="spotify" && spotifyGeneration==access.generation && token?.access==access.value){вЂ¦}
    if(provider=="yandex" && yandexGeneration==access.generation && yandexToken==access.value){
        store.remove("yandex_token"); store.remove("yandex_user")
        yandexToken=null; yandexUid=""; yandexGeneration++
        _status.value=_status.value.copy(yandexName="")
    }
    publish()
}}
```

**Actual result.**
* The delete **is** conditional (generation + token equality), but the
  condition is satisfied on the normal path — the 401 came *from* the
  request that used that token, and no concurrent refresh changed the
  generation. The audit's word "unconditionally" is imprecise; the outcome it
  describes is correct.
* Spotify has a **refresh-and-retry** path (`:179-186`) and only deletes the
  token if the *retry* also 401s. Yandex has **neither** a refresh nor a
  re-validation, so a single 401 destroys the credential.
* Recovery: the user must paste a new token; there is no automatic path.
  The desktop keeps the token and only reports the failure
  (`services/yandex_service.py:242-243`).
* The audit's own note that "this path has no test today" is correct.

**Limitations.** No device; the 401 was not driven against a mock server by
the arbiter (verifier A's mock-based check is the executed evidence).
Whether Yandex returns transient 401s in practice is unmeasured.

**Root cause.** The handler conflates "this credential is invalid" with "this
request was not authorized", and treats the former as sufficient
justification to destroy a secret the user must obtain out of band.

**Recommended resolution (description only).** On a Yandex 401, re-validate
the credential against `account/status` (`ProviderConnections.kt:109` already
performs exactly this call) before deciding to delete it; delete only if the
re-validation also fails. The `yandexScope()` rotation contract must keep
rotating whenever the credential really is dropped.

**Potential regressions of a fix.** One extra request on the error path; the
"disconnected" state would lag a 401 by one round-trip, so the status text
must still reflect the failure immediately. A re-validation that itself
requires the credential cannot run after the credential is removed — the
order of operations must be re-validate в†’ then remove.

---

## P1-04 — The shared 30-second `callTimeout` aborts every download whose body takes longer than 30 s

**Original severity:** P1 · **Revised severity:** **P1 (unchanged)** — with a materially **larger** blast radius than the audit describes, and flagged as a **P0 candidate** pending an on-device playback check.

**Verifier A result:** confirmed for the **download** path; the audit
under-reports the blast radius.
**Verifier B result:** the *download* claim is right; the framing "a shipped
feature cannot work at all" is too strong for a modern connection.
**Arbiter result:** confirmed with an additional, larger consequence — the
**streaming** path uses the same client and the same `Call.execute()`.

**Final verdict:** **CONFIRMED — RUNTIME** for the download path; the scope is
corrected and the severity is **held at P1** (see the addendum below).

**Confidence:** HIGH В· **Evidence type:** bytecode + static

**Relevant source paths:** `data/Sources.kt:22-23` (the client),
`NeDotifyApp.kt:32-36` (one `MusicNetwork` instance for the whole app),
`downloads/DownloadStorage.kt:26-29` (the download upstream),
`downloads/TrackDownloadWorker.kt:56`, `:84-89` (the retry classification),
`downloads/DownloadKeys.kt` (`downloadCanRetry`), `player/PlaybackService.kt:55`
(the **streaming** upstream).

**Evidence — arbiter `javap` on `media3-datasource-okhttp-1.11.1.aar`:**

```
androidx.media3.datasource.okhttp.OkHttpDataSource
  open(DataSpec):
      31: invokeinterface okhttp3/Call$Factory.newCall:(Lokhttp3/Request;)Lokhttp3/Call;
      42: invokespecial  executeCall:(Lokhttp3/Call;)Lokhttp3/Response;
```

в‡’ the media body is read through a **blocking `Call.execute()`**, so OkHttp's
`callTimeout` — which spans the whole call including the body read — bounds
**the streaming read as well as the download**.

**Actual result.**
* One `OkHttpClient` with `connectTimeout(12s) / readTimeout(20s) /
  callTimeout(30s)` serves metadata, the provider API, the **media stream**
  and the **download**. `MusicNetwork` is instantiated exactly once
  (`NeDotifyApp.kt:35`), so the claim of a shared client holds.
* The download path is genuinely broken for transfers slower than the budget:
  at 320 kbps в‰€ 1.2 MB, at 1 Mbit/s в‰€ 3.6 MB, at 2 Mbit/s в‰€ 7.5 MB. A
  normal 4 MB track fails on any link below ~1.1 Mbit/s.
* The worker classifies the abort as retryable and re-runs it, then ends in
  `failed` with *"РЎРѕРµРґРёРЅРµРЅРёРµ РїСЂРµСЂРІР°РЅРѕ. Р—Р°РіСЂСѓР·РєСѓ РјРѕР¶РЅРѕ РїСЂРѕРґРѕР»Р¶РёС‚СЊ"* — a
  message that invites a retry which fails identically.
* **The audit under-reports this**: because `OkHttpDataSource` uses
  `Call.execute()`, a *streaming* read is subject to the same 30 s total
  budget. A track whose transfer takes more than 30 s is cut off mid-playback
  unless the bytes were already in the cache. This is a **larger** consequence
  than the one reported, and it was not raised at all.
* HLS is genuinely less affected (each segment is its own call), but a
  progressive stream is not.

**Limitations.** No device; the 30 s abort was not observed at runtime. The
exact byte threshold at which a given link fails depends on the real
throughput.

**Root cause.** One HTTP client with a 30 s *total* call budget is reused for
bulk media transfer, and the timeout was sized for metadata.

**Recommended resolution (description only).** Give the media path its own
client: `MusicNetwork` should expose a second `OkHttpClient` (e.g. `mediaHttp`)
built with `callTimeout(0)` (no total call budget) or a download-sized
budget, keeping the 30 s `callTimeout` for metadata. `DownloadStorage.factory`
**and** `PlaybackService`'s `OkHttpDataSource.Factory` must both use it.

**Potential regressions of a fix.** The transfer then has no total-time
bound; only the 20 s per-read `readTimeout` applies, so a half-dead
connection is still detected but a very slow one is not. The
retry/backoff policy (`downloadCanRetry`) would then need to bound
slow-but-alive transfers instead. Removing the total budget from the
**streaming** path also removes the accidental protection against a stalled
CDN connection holding a loader thread.

---

# PART 2 — The pending-selection gate (the audit's #1 Android finding)

---

## "XI-08 B P1" / REG P2-11 — the closed gate, the swallowed Play

**Original severity:** P1 (unnamed finding; the report's #1 Android
priority) В· **Revised severity:** **P3** for the gate itself, **P2** for
REG P2-12

**Verifier A result:** **the central Media3 claim is refuted** by bytecode.
**Verifier B result:** **the central Media3 claim is refuted** by bytecode
(the two verifiers reached the same conclusion independently, from the same
AAR, and the arbiter re-derived it a third time).
**Arbiter result:** confirmed the refutation independently (В§ FP-1).

**Final verdict:** **FALSE POSITIVE** as stated (the mechanism) —
**OVERSTATED** for the residual behaviour. See `FALSE_POSITIVES.md` FP-1.

**Confidence:** HIGH В· **Evidence type:** bytecode

**Verdict detail per sub-claim:**

| Sub-claim | Verdict |
|---|---|
| "`onPlayerCommandRequest` is never reached by `MediaController.play()`/`pause()`" | **FALSE** — both reach it as `COMMAND_PLAY_PAUSE` (= 1) |
| "only `setPlayWhenReady` dispatches through it" | **FALSE** — `play`, `pause`, `prepare`, `stop`, seeks, repeat/shuffle, volume and every media-items mutation all route through `queueSessionTaskWithPlayerCommand` |
| "every subsequent Play is dropped вЂ¦ until the user re-picks a track" | **FALSE** — the next press re-arms the gate at enqueue time |
| "the first press is silently lost" (P2-11's own body) | **NARROWLY TRUE** — only in the interleaving "a set is pending AND an interruption trips the gate after the play was enqueued" |
| "the refusal produces no error and no state change" | **TRUE** — `Futures.immediateVoidFuture()`, no `SessionError`, no `invalidateState()`, and `onPlayerCommandRequest` returns `RESULT_SUCCESS` unconditionally |
| "the gate is tripped by every player command" | **PARTLY** — the gate is closed only by `interruptPending()`, which fires only when a set is *pending* |

**Root cause (corrected).** The gate's two halves are consulted at two
different moments — the re-arm at **enqueue** time
(`player/PlaybackService.kt:85-88`) and the refusal at **execution** time
(`player/DualDeckPlayer.kt:231`). Because the re-arm is unconditional on
`COMMAND_PLAY_PAUSE` and Media3 dispatches the app's own play/pause as
exactly that command, the two halves actually agree for the app's own
transport. The surviving defects are (a) the refusal is **silent**, and
(b) the gate is closed by events that are not user interactions.

**Recommended resolution (description only).** Make the refusal observable
(`session.sendError` on the `onFocusDenied` channel, and/or
`invalidateState()`); split the `DualDeckPlayer` callback into "the user
changed the playback state" and "the playback environment changed"; and, if
the design is changed at all, replace the boolean with a per-command token so
that a *stale* released play is rejected while a *fresh* press is accepted —
without relying on the enqueue-time callback.

**Potential regressions of a fix.** A `SessionError` on every refused play
reaches every controller (Android Auto, Wear, a browser client) and would be
shown by the app's own `MediaController.Listener.onError`; the message must
not blame the user. Splitting the callback stops `interactionVersion++` on
focus loss, and `interactionVersion` guards the startup restore, the autoplay
append and the offline source refresh — relaxing it could let a stale
restore overwrite a queue the user changed. Per-command tokens need cleanup
on controller disconnect (not overridden today) and on session release.

---

## REG P2-12 — the same interruption cancels the in-flight queue set

**Original severity:** P2 В· **Revised severity:** **P2** (unchanged)

**Verifier A result:** **CONFIRMED — STATIC**, with bytecode.
**Verifier B result:** **CONFIRMED — STATIC**.
**Arbiter result:** corroborated from the same bytecode chain.

**Final verdict:** **CONFIRMED — STATIC**

**Confidence:** HIGH В· **Evidence type:** bytecode + static

**Relevant source paths:** `player/PendingSelectionGate.kt:21-30`
(`interruptPending`), `player/PlaybackService.kt:75` (the single call site),
`:297-319` (`resolveFuture`).

**Evidence — the cancellation chain (Media3 1.11.1):**

```
Util.transformFutureAsync$2 (media3-common):
   0: aload_0
   1: invokestatic com/google/common/util/concurrent/Futures.getDone:(...)Ljava/lang/Object;
   вЂ¦
  12: invokevirtual SettableFuture.cancel:(Z)Z
  16: return          <-- a cancelled input means the AsyncFunction is NEVER applied

Util.postOrRunWithCompletion$0 (media3-common):
   0: aload_0
   1: invokevirtual SettableFuture.isCancelled:()Z
   4: ifeq 8
   7: return          <-- cancelled: the install Runnable is SKIPPED
```

в‡’ `MediaSessionStub.handleMediaItemsWithStartPositionWhenReady` в†’ the
install runnable (`PlayerWrapper.setMediaItemsWithStartIndexAndPosition`) is
**never run**; `DualDeckPlayer.handleSetMediaItems` is never invoked and the
queue is never installed.

**Evidence — no error is reported:**
`player/PlaybackService.kt:305` is `catch(cancelled:CancellationException){future.cancel(false);throw cancelled}` —
the `session.sendError` at `:307` is only in the generic `Exception` branch.
And `ui/MusicViewModel.kt:164-168` (`startPrepared`) calls
`player.setMediaItems(items, index, 0)`, whose `Player`-level signature
returns **void** — there is no future at that level to observe.

**Actual result.** A pause, becoming-noisy, a focus loss or another
controller's command landing in the window between `onSetMediaItems` and the
completion of the queue read destroys the user's selection with **no** error,
**no** message and **no** state change. The window is short for a small
queue and longer for a large one.

**Root cause.** The gate conflates two intents: "abort the play" and "abort
the queue". The `playAllowed` check already covers the play; cancelling the
set future additionally destroys the queue the user just asked for.

**Recommended resolution (description only).** Separate the two intents —
`interruptPending()` should close the gate **without** cancelling the set
future (or the service should keep the resolved items and install them
paused) — and report the abandonment (`resolveFuture`'s cancellation branch
should send a `SessionError`).

**Potential regressions of a fix.** If the set future is not cancelled, Media3
installs the queue and then runs the controller's queued `prepare`/`play`;
the play must still be refused by the gate, which the current `playAllowed`
check does — so the "a pause must not be undone" invariant is preserved. A
user-initiated pause arriving mid-set then leaves the *new* queue installed
but paused, which is the intended behaviour. Reporting the abandonment adds
an error message on a path the user did not cause, so the wording matters.

---

## REG P2-13 — a transient audio-focus loss is reported as a "user interaction"

**Original severity:** P2 В· **Revised severity:** **P2** (unchanged)

**Verifier A result:** **CONFIRMED — STATIC**.
**Verifier B result:** confirmed, with the note that
`AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK` does **not** fire the callback — only
the hard transient loss does.
**Arbiter result:** confirmed by reading `player/DualDeckPlayer.kt:245-254`.

**Final verdict:** **CONFIRMED — STATIC**

**Confidence:** HIGH В· **Evidence type:** static

**Relevant source paths:** `player/DualDeckPlayer.kt:250`,
`player/PlaybackFocusState.kt:15` (`transientLoss()`),
`player/PlaybackService.kt:75`.

**Evidence:**

```kotlin
// DualDeckPlayer.kt:250
AudioManager.AUDIOFOCUS_LOSS_TRANSIENT->{focusState.transientLoss();onUserInteraction();cancelTransition();active.pause()}
```
```kotlin
// PlaybackFocusState.kt:15
fun transientLoss() {hasFocus=false;suspended=requested}      // requested stays TRUE
```

**Actual result.** The focus model treats a transient loss as *"intent
preserved"* (`canPlay` is false only while `suspended`; `gain()` restores
`hasFocus=requested`), while the interaction model treats the very same event
as *"the user intervened"* and therefore (a) bumps `interactionVersion`,
(b) cancels the startup queue restore, (c) cancels the pending
`onSetMediaItems` future and sets `playAllowed=false`, and (d) cancels the
error-recovery job. The two models contradict each other, and the destructive
one wins. The same `onUserInteraction()` is fired by `pauseForReason`
(`:257`) — becoming-noisy and permanent focus loss.

**Limitations.** No device; the interleaving was not observed.

**Root cause.** One callback conflates "the user's intent changed" with "the
system took the audio focus away".

**Recommended resolution (description only).** Split the callback into "user
intent changed" and "playback was interrupted by the system". The transient
branch should not invoke the user-interaction callback — the play intent is
already preserved in `focusState`, and `cancelTransition()` + `active.pause()`
cover the player side. Give the service a separate, non-destructive callback
if it needs to invalidate the autoplay/recovery candidates.

**Potential regressions of a fix.** The gate exists precisely to drop a stale
"prepare/play" queued before a competing pause/noisy, so the fix must keep
the "a stale play must not undo another controller's pause/noisy" invariant
while allowing the *set* itself to survive.


---

# ADDENDUM — runtime confirmation of P1-01 … P1-04

A second, independent verifier executed the P1 set against the **real**
repository classes (a Gradle unit test injected by an init script, so no repo
file was touched) and against the **shipped** dependency artefacts. That
evidence is recorded here; the matrix carries the updated verdicts.

## P1-01 — CONFIRMED — RUNTIME

```
PROBE wanted='Artist - Song (Official Video)' -> base='artist song' version=[]
PROBE offered='Song'                            -> base='song' version=[]
PROBE similar(): size=11 lenDiff=7 size/10=1 lengthPrecheckRejects=true
PROBE hypothetical editDistance=7 ratio=0.6363636363636364
PROBE accept(offered='Song')                   -> null
PROBE accept(offered='Song') for title='Song (Official Video)' -> LyricsResult(plain=la la la, …)
PROBE accept(offered='Artist - Song (Official Video)')          -> LyricsResult(plain=la la la, …)
PROBE cascade query = 'Artist Artist - Song (Official Video)'
```
Desktop oracle, executed against the repo's own `services/music_matching.py`:
```
DESKTOP wanted='Artist - Song (Official Video)' artist='Artist' -> base_title='Song' artists=['Artist']
DESKTOP similarity(base,base)=1.0000  accept(score>=0.85)=True  artist_matches=True
```

**Two corrections to the audit.**
1. **The mechanism.** The audit says "the Levenshtein ratio falls to ~0.64".
   The Kotlin never computes the edit distance for this pair — the **length
   pre-check** at `data/LyricsCascade.kt:63` fires first
   (`abs(11-4)=7 > 11/10=1`). The audit's "line-for-line Python mirror …
   dist/size=0.636" evidence does not describe the code path that actually
   rejects.
2. **The desktop citation.** `services/lyrics_service.py:220-224`
   (`_clean_track_and_artist`) is **dead code** — a repo-wide grep finds only
   its definition and two assertions in `tests/test_lyrics_netease.py:212,218`;
   it is never called by the live lookup. The live oracle is
   `services/lyrics_lookup.py:243` → `services/music_matching.py:71-77`, which
   was executed and returns `base_title='Song'`, similarity 1.0.

**Two conditions the audit omitted.** (a) The SAF case (no ID3 artist) is
rejected by a **different** branch — `expectedArtists.isEmpty()` at `:83` — not
by `similar()`. (b) The **LRCLIB primary** provider (`data/Sources.kt:231-233`)
is gated by the same `accept`, so the failure is not confined to the fallback
cascade.

**Severity P2.** The desktop accepts the same track; the exposure is limited
to tracks whose title literally embeds `"Artist - "`, and the prevalence was
not measured.

## P1-02 — CONFIRMED — RUNTIME (severity dispute recorded)

```
PROBE step1 write ok, fileSize=18
PROBE step2 corrupted file, bytes=8 -6a 1 7f 0 -1 2a
PROBE step3 guarded read -> ok=true value=true
PROBE step4 edit#1 -> CorruptionException: Unable to parse preferences proto. (isIOException=true)
PROBE step5 edit#2 -> CorruptionException: ... (isIOException=true)
PROBE step6 edit#3 -> CorruptionException: ... (isIOException=true)
PROBE step7 fileSizeAfterEdits=7 bytesAfterEdits=8 -6a 1 7f 0 -1 2a
PROBE step8 raw read after edits -> SUCCESS
PROBE step9  fresh store read -> CorruptionException: ... (isIOException=true)
PROBE step10 fresh store edit -> CorruptionException: ... (isIOException=true)
PROBE step11 fileSizeAfterFreshEdits=7 bytes=8 -6a 1 7f 0 -1 2a
```

The read side is swallowed; **every** write re-throws the cached
`CorruptionException`; the corrupt file is **byte-identical** afterwards; and
a **fresh** store over the same file (the app-restart equivalent) fails to
read *and* to write. **The state is permanent.**

**Two permanent losses the audit did not list:** the **saved queue**
(`Preferences.queue()` → `""` → the restored queue is silently dropped on
restart) and `Preferences.libraryId()` (throws → backup export/import break).
And `NeDotifyApp.kt:27` swallows the `IOException` from `saveQueue` with only
a `Log.e`, so the 5 s checkpoint fails **silently**.

**Severity dispute (recorded, not majority-resolved).** One verifier argues
**P2** because the fix is a one-line `ReplaceFileCorruptionHandler` per
delegate. The arbiter keeps **P1** because the impact is total and
irreversible — every setting, the saved queue and the library id are lost,
the checkpoint fails silently, and the state survives restarts. Both sides
agree the **mechanism** is confirmed at runtime.

**Limitation.** The probe used `OkioStorage` (pure JVM) rather than the
Android `FileStorage`; the corruption detection and the `State.ReadException`
caching live in `DataStoreImpl`, which is storage-agnostic and identical in
both cases.

## P1-03 — CONFIRMED — RUNTIME

```
PROBE before: connected=true name=Слушатель
PROBE get() threw: SourceFailure: … httpCode=401
PROBE after: store['yandex_token']=null store['yandex_user']=null
PROBE after: connected=false name=''
PROBE server requestCount=1
PROBE postYandex threw: SourceFailure: … httpCode=401
PROBE after: store['yandex_token']=null connected=false
PROBE server requestCount=1
PROBE spotify 401: spotify_token={…} yandex_token={…}      <- a Spotify 401 does NOT touch the Yandex credential
PROBE spotify 401: requestCount=2
```

A Yandex 401 on **GET or POST** removes the credential from the secure store
and disconnects the UI, in **one** request, with **no retry** and **no
refresh**.

**Two corrections.**
1. The audit's "retry once on 401" is true only of the **Spotify** branch
   (`data/ProviderConnections.kt:179-186`); the Yandex path has none.
2. **"No recovery path" is overstated** — `ui/ConnectionsControls.kt:42,56-61`
   offers a "Подключить" flow that accepts a pasted OAuth token and calls
   `saveYandexToken`. The *token value* is unrecoverable; the *account* is
   re-connectable by hand.
3. The delete is **guarded** (`yandexGeneration == access.generation &&
   yandexToken == access.value`), so a *concurrent* re-login/logout makes it
   a no-op — the audit's "unconditionally" is too strong, though the practical
   outcome is the same.

**Severity P2** — a spurious Yandex 401 is unlikely and the recovery path
exists, though it is manual.

## P1-04 — CONFIRMED — RUNTIME (severity held at P1)

```
[client] callTimeoutMillis=30000 readTimeoutMillis=20000 connectTimeoutMillis=12000
[client] response code=200 contentLength=400
[client] read 250 bytes at 26961ms
[client] EXCEPTION after 30016ms: java.io.InterruptedIOException: timeout
```
control (`callTimeout` disabled, identical server):
```
[client] read 400 bytes at 43644ms
[client] COMPLETED total=400 in 43644ms
```
and the **async/enqueue** style Media3 uses:
```
[client] headers received at 59ms, failure=null
[client] read 250 bytes at 26844ms
[client] EXCEPTION after 30028ms: java.io.InterruptedIOException: timeout
```
Retry classification, against the **real** repo functions:
```
PROBE extracted http status from a timeout cause chain = null
PROBE timeout -> retryable=true text='Соединение прервано. Загрузку можно продолжить'
PROBE downloadCanRetry(attempt=0..2, status=null) = true
PROBE downloadCanRetry(attempt=3..4, status=null) = false
```
⇒ 4 attempts total; the final state is `"failed"` with the claimed text.
320 kbps → 30 s → **1 200 000 B = 1.2 MB** — the audit's arithmetic is right.

**Three corrections.**
1. **The audit missed the streaming path.** `player/PlaybackService.kt:55` uses
   the **same client** for the media stream, and Media3 keeps one call open
   for a whole progressive media item — so the 30 s budget spans the whole
   track. This is a **larger** consequence than the one reported, and it is
   consistent with `PORTING_STATUS.md:7-10` never having verified sound on a
   device. **The arbiter holds P1-04 at P1 and flags it as a P0 candidate
   pending an on-device playback check.**
2. **"~4 × 30 s wasted" is not accurate** — Media3's `CacheWriter` consults
   `Cache.getCachedBytes(...)` and keeps the committed partial span, so a
   retry *resumes* with a Range request. The real cost is
   `ceil(track_seconds / 30)` retry cycles with 30/60/120 s exponential
   backoff, each surfacing a failure to the user.
3. **The exception type is imprecise** — the worker sees
   `HttpDataSource.HttpDataSourceException` (extends `DataSourceException
   extends IOException`), not a bare `InterruptedIOException`. The
   *classification* is unchanged.

Also: **`PORTING_STATUS.md:112` is a mis-citation** — it is a *limitations*
entry ("a private offline package, not an exported MP3"), not the "shipped"
declaration, which lives at `:24` and `:68-71`.

**Limitation.** No device test, so the Media3/ExoPlayer-level end-to-end
behaviour is **not** observed. A faithful JVM Media3 test is impractical:
`android.net.Uri` is a stub in the unit-test `android.jar`, so `DataSpec`
cannot be constructed without a real Android runtime — hence the probe was
done at the OkHttp layer, mirroring `OkHttpDataSource.executeCall` exactly.
