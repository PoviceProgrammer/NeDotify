# ROOT CAUSE MAP

How the original findings collapse into a much smaller number of independent
root causes. A finding is **independent** if fixing its root cause does not
fix any other root cause's findings; a finding is **derived** if it is a
symptom of another root cause.

Ids are the canonical ones (see `01_INVENTORY.md`): **REG** = the register's
P2 numbering; **MAIN** = the main report's §5.1-only records.

---

## RC-1 — The Media3 session/player boundary is observed at two different moments

* **Root cause.** `PendingSelectionGate` re-arms at **command-enqueue** time
  (`MediaSession.Callback.onPlayerCommandRequest`, `player/PlaybackService.kt:85-88`)
  and refuses at **command-execution** time
  (`player/DualDeckPlayer.kt:231`). The re-arm is *unconditional* on
  `COMMAND_PLAY_PAUSE`, and Media3 1.11.1 dispatches `play()`/`pause()` as
  exactly `COMMAND_PLAY_PAUSE` — so the two halves actually agree for the
  app's own transport, and the gate is self-healing. The surviving defect is
  that the refusal is **silent** and that the gate is closed by events that
  are not user interactions.
* **Derived findings.** The unnamed "XI-08 B P1" (the report's #1 Android
  headline) — **FALSE POSITIVE in its stated mechanism** (see
  `FALSE_POSITIVES.md` FP-1). REG **P2-11** — survives only as a silent-veto
  defect. REG **P2-12** — survives. REG **P2-13** — survives. Architecture item
  **A-2**. Cross-module **X-01** (its claim that the two protocols "disagree
  exactly in the window that matters" is refuted). Remediation items
  **R1.1** and **A-2**'s premise.
* **Independent?** Yes — but note that RC-1 and RC-2 are coupled through
  `interactionVersion` (see RC-17).

## RC-2 — A destructive `DELETE` where a merge was required (desktop)

* **Root cause.** The "dup cleanup" in `core/database.py:313-362` deletes
  duplicate rows instead of merging them, and the schema's
  `ON DELETE CASCADE` clauses then propagate the deletion into
  `history.track_id` and `playlist_tracks.track_id`. The migration's own two
  explicit `DELETE FROM playlist_tracks` statements remove playlist membership
  *independently* of any track deletion, and can remove the entry of a track
  that survives.
* **Derived findings.** **P0-01** (the mechanism is confirmed; the stated
  *cause* is refuted — see FP-2 — and the causal story for the playlist half
  is refuted — see FP-3). Remediation **R0.1**.
* **Independent?** Yes. Nothing else in the audit set causes data loss.

## RC-3 — The library has five writers, no delete, and playback is one of them

* **Root cause.** `tracks` is written by the MediaStore scan, the SAF import,
  the catalogue import, the **playback preparation** and the backup restore;
  there is no `DELETE FROM tracks` in the DAO and no UI affordance to remove
  a track.
* **Derived findings.** REG **P2-31**. Cross-module **X-05**. Architecture
  **A-9**. **P3-14** (the same file through two import paths produces two
  rows). **P3-63** (the profile screen re-materialises the whole table).
  MAIN-**P2-45** (the unguarded history write is the same "no single writer"
  problem seen from the write side).
* **Independent?** Yes.

## RC-4 — The only durable session state lives in the settings file, and the compared value contains the one field that always changes

* **Root cause.** The queue snapshot is a JSON blob in the *settings*
  DataStore; `checkpointQueue()` embeds `player.currentPosition` in the value
  it compares, so the de-duplication guard can never fire.
* **Derived findings.** REG **P2-01**. Cross-module **X-02**. Architecture
  **A-1**. **P3-34** (the `queue_v1` key / payload `"version":2` mismatch and
  the missing version check on read). **P2-72** and the build-tooling family
  share the "no gate" theme but not the mechanism.
* **Independent?** Yes.

## RC-5 — The download and streaming paths have no shared identity, budget or completeness contract

* **Root cause.** Two `SimpleCache` instances keyed differently, one HTTP
  client with a 30 s *total* call budget shared by metadata and bulk
  transfer, a download path with no completeness check and no size ceiling,
  and a media URL validated only for `https`.
* **Derived findings.** REG **P2-47**, **P2-49**, **P2-50**, **P2-30**,
  **P2-29**, **P2-51**, **P2-52**, **P2-48**. **P1-04** (the same shared
  client). Cross-module **X-03**. **P3-24**, **P3-77**, **P3-23**.
  Architecture **A-8**.
* **Independent?** Partly — **P1-04** is one client-config change that also
  affects the *streaming* path (see `VERIFIED_FINDINGS.md`).

## RC-6 — The lyrics identity gate is stricter than the desktop oracle in four independent dimensions

* **Root cause.** The Android port merged the desktop's two layers (query
  cleaning + identity parsing) into one and dropped the artist-prefix rule,
  implemented the version relation as set *equality* instead of a set
  *relation*, used set *containment* (`containsAll`) where the oracle uses
  intersection, and gave the whole cascade no failure channel and no
  base-recording fallback.
* **Derived findings.** **P1-01** (artist prefix). REG **P2-68** (artist
  superset), **P2-71** (base fallback), **P2-66** (failure channel),
  **P2-67** (cache poisoning), **P2-69** + **P2-70** (budgets), MAIN-**P2-29**
  (alias of 69+70), MAIN-**P2-28** / **P3-79** (the oversized primary throws),
  **P3-29** / **P3-78** (provider attribution), **P3-80** (cache version),
  **P3-81** (cache in `cacheDir`).
* **Independent?** Yes, but they share one test surface: the cascade's
  identity policy.

## RC-7 — Provider and transport errors are classified at the edge and thrown away at every layer above

* **Root cause.** `SourceFailure.httpCode` exists and the transport maps
  401/403/429 to distinct messages, but every consumer above collapses them
  into one counter or one `String?`.
* **Derived findings.** REG **P2-62**, **P2-58**, **P2-17** (lyrics
  availability). **P1-03** (the Yandex 401 handler — same shape: a
  classified code drives a destructive action). **P3-04**, **P3-17**,
  **P3-22**, **P3-23**, **P3-11** (message taxonomy), **P3-57** (empty-state
  taxonomy), **P3-74** (backup failure taxonomy).
* **Independent?** Yes.

## RC-8 — Long-running network work is modelled as UI-scoped work

* **Root cause.** `importCatalog()` and the search pipeline are
  `viewModelScope` coroutines that are unbounded, non-resumable, serial and
  (partly) main-thread, and they block the rest of the catalogue while they
  run.
* **Derived findings.** REG **P2-08**, **P2-60**, **P2-61**, **P2-62**,
  **P2-58**, **P2-59**, **P2-74**. MAIN-**P2-40** (the root composable
  subscribes to the progress flow). **P3-26**, **P3-27**, **P3-28**,
  **P3-44**, **P3-54**.
* **Independent?** Yes.

## RC-9 — The cross-platform format is a private, unversioned, hand-duplicated schema with unbounded memory

* **Root cause.** The desktop's private SQLite schema *is* the wire format;
  it is reimplemented by hand in Kotlin with no version marker, no golden
  fixture, no conformance test and no CI; the backup codec that transports it
  is bounded at 16 MB but not in heap.
* **Derived findings.** REG **P2-14**, **P2-15**, **P2-16**, **P2-19**,
  **P2-47**. Cross-module **X-06**. **P3-96**, **P3-97**, **P3-98**,
  **P3-99**, **P3-100**, **P3-101**, **P3-102**. Architecture **A-7**.
  MAIN-**P2-35** (no retention policy on `history`).
* **Independent?** Yes.

## RC-10 — The desktop import treats the desktop's schema as optional input, not as a contract

* **Root cause.** The importer selects only the columns that happen to exist
  and reads them with defaulting accessors; one unusable rule row aborts the
  whole import; the imported-library identity is a free-text label; the WAL
  sidecar is never read.
* **Derived findings.** REG **P2-17**, **P2-18**, **P2-19**, **P2-20**,
  **P2-21**, **P2-25**, **P2-26**. **P3-15**, **P3-16**, **P3-71**.
* **Independent?** Shares the "no versioned contract" theme with RC-9 but is
  a different mechanism (tolerance vs. duplication).

## RC-11 — The settings file is a whole-file blob rewritten on a fast cadence, and its failure mode is a silent no-op

* **Root cause.** The `preferencesDataStore` delegates have no
  `ReplaceFileCorruptionHandler`, so the library's default
  `NoOpCorruptionHandler` governs; the read path survives only by accident
  (`CorruptionException extends IOException`), and the write path re-throws
  the cached read failure forever. The same file also carries the queue
  snapshot and the user's profile.
* **Derived findings.** **P1-02** (the write path is permanently wedged).
  REG **P2-46** (the `offline` flag is a theme field read cold from this
  file). **P3-03** (the message channel conflates), **P3-60** (a failed write
  leaves an optimistic value on screen), **P3-68** (a failed save discards
  the typed value), **P3-34**, **P3-36**.
* **Independent?** Yes.

## RC-12 — There is no gate

* **Root cause.** The device suite has never run, the tree is untracked, the
  review manifest is stale and one-directional, the build script executes zero
  tasks when its output is captured, and the build is not hermetic.
* **Derived findings.** REG **P2-53**, **P2-54**, **P2-55**, **P2-56**,
  **P2-57**, **P2-72**, **P2-38**, **P2-39**, **P2-40**, **P2-41**,
  **P2-42**. **P3-82**, **P3-83**, **P3-84**, **P3-85**, **P3-86**,
  **P3-87**, **P3-88**, **P3-89**, **P3-90**, **P3-91**, **P3-92**,
  **P3-93**, **P3-94**, **P3-95**. **P2-76**, **P2-77**, **P2-78**,
  **P2-79**, **P3-111**, **P3-112**, **P3-113**, **P3-114** (plan-only).
  Cross-module **X-02** (partly). Architecture **A-5**, **A-10**.
* **Independent?** Yes — and it is the highest-leverage root cause in the
  whole set, because it is what let every other defect survive.

## RC-13 — High-frequency and whole-collection state is read at the top of the composition

* **Root cause.** Values that change at 2 Hz (position) or that are
  collections (the queue, the library) are read at the root of a composable
  and therefore invalidate the whole subtree.
* **Derived findings.** MAIN-**P2-41**. REG **P2-34**, **P2-35**.
  **P3-46**, **P3-47**, **P3-48**, **P3-49**, **P3-50**, **P3-62**,
  **P3-37**, **P3-39**.
* **Independent?** Yes.

## RC-14 — "Now playing" and playback errors have no single source of truth

* **Root cause.** Three copies of the playback state (Media3's `playerInfo`,
  the ViewModel's `NowPlaying`, `AudioRuntime.status`), the error dimension
  missing from the mirror, the listener attached too late, and no
  `onDisconnected` handling.
* **Derived findings.** **P3-103**, **P3-104**, **P3-105**, **P3-106**,
  **P3-107**, **P3-108**, **P3-109**, **P3-110**. Architecture **A-3**.
  Cross-module **X-01** (partly). REG **P2-10** (the listening-session
  boundary is re-derived from Media3's coarse transition-reason enum).
* **Independent?** Yes.

## RC-15 — The app is a manual service locator, so the orchestration layer is untestable

* **Root cause.** `NeDotifyApp` is a service locator reached by a cast; the
  helpers were extracted but the *composition* of those helpers never was.
* **Derived findings.** REG **P2-75**. **P3-36**, **P3-90**, **P3-91**,
  **P3-95**, **P3-98**. Architecture **A-5**. Cross-module **X-05** (partly).
* **Independent?** Yes.

## RC-16 — System/focus events and user interactions are conflated

* **Root cause.** `onUserInteraction` is called for `AUDIOFOCUS_LOSS_TRANSIENT`
  and for `pauseForReason` (becoming-noisy, permanent focus loss) even though
  `PlaybackFocusState` models a transient loss as "intent preserved".
* **Derived findings.** REG **P2-13**. **P3-10** (over-stated, see FP-4).
  REG **P2-12** (the same interruption cancels the pending queue set).
  **P3-12** (the desktop caps a listening tick at 15 s; Android does not).
* **Independent?** Shares the `onUserInteraction` surface with RC-1, but the
  two root causes are separable: RC-1 is *when* the gate is consulted, RC-16
  is *who* is allowed to close it.

## RC-17 — The desktop's library identity and the Android's identity model are two different systems

* **Root cause.** The desktop's `tracks.id` is an `INTEGER PRIMARY KEY
  AUTOINCREMENT` that restarts at 1 on every machine, while the Android's
  identity is a salted SHA-256 of the *device* library id; the bridge uses the
  free-text origin label to bridge them.
* **Derived findings.** REG **P2-14**, **P2-20**, **P2-26**. **P3-101**.
  Architecture **A-7**.
* **Independent?** Part of RC-9/RC-10 in practice; recorded separately
  because it is the one place where a *third* identity rule (the desktop's
  autoincrement id) leaks into the Android.

---

## Independent vs. derived — summary

| Root cause | Independent defects it owns | Findings that are symptoms of another root cause |
|---|---|---|
| RC-1 gate | 1 (the silent veto) | the report's headline "P1" (FP-1), X-01's disagreement claim, A-2, R1.1 |
| RC-2 desktop migration | 1 (P0-01) | FP-2 (wrong cause), FP-3 (wrong causal story) |
| RC-3 library writers | 1 | X-05, A-9, P3-14, P3-63, MAIN-P2-45 |
| RC-4 queue snapshot | 1 | X-02, A-1, P3-34 |
| RC-5 download/stream | 6 | X-03, A-8, P3-24, P3-77, P3-23, P1-04 |
| RC-6 lyrics identity | 4 | REG P2-66/67/69/70, MAIN-P2-28/29, P3-29/78/79/80/81 |
| RC-7 error taxonomy | 3 | P1-03, P3-04/17/22/23/57/74 |
| RC-8 UI-scoped network work | 2 | REG P2-60/61/62/58/59/74, MAIN-P2-40, P3-26/27/28/44/54 |
| RC-9 cross-platform format | 3 | X-06, A-7, P3-96…P3-102, MAIN-P2-35 |
| RC-10 desktop import tolerance | 1 | P3-15/16/71 |
| RC-11 settings durability | 2 | REG P2-46, P3-03/34/36/60/68 |
| RC-12 no gate | 1 | everything in the P3-82…P3-95 range, P2-38…P2-42, P2-53…P2-57, P2-72, the plan-only P2-76…79 / P3-111…114, A-5, A-10 |
| RC-13 composition granularity | 1 | MAIN-P2-41, REG P2-34/35, P3-37/39/46…50/62 |
| RC-14 now-playing truth | 1 | A-3, X-01, REG P2-10, P3-103…P3-110 |
| RC-15 untestable composition | 1 | REG P2-75, P3-36/90/91/95/98, A-5 |
| RC-16 focus vs interaction | 1 | REG P2-12/13, P3-10/12 |
| RC-17 identity model | 1 | REG P2-14/20/26, P3-101, A-7 |

**Net effect.** The original report presents 1 + 4 + 75(+13) + 110(+4) = 207
records. After collapsing symptoms into their causes, they reduce to roughly
**25 independent defects** across 17 root causes — of which **RC-12 ("there
is no gate")** is the one that explains why the other 24 survived.
