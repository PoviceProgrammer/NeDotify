# VERIFICATION SUMMARY — how much of the NeDotify / AURA Music audit survives independent verification

**Verifier:** Principal Software Engineer / Independent Software Auditor /
Senior Android Engineer / Security Researcher / QA Architect, with a
multi-agent team (2 independent verifiers per finding class, plus an arbiter
that re-derived every disputed fact from the artefacts).
**Subject:** `docs/audits/FULL_PROJECT_AUDIT.md` +
`docs/audits/ANDROID_FINDINGS_REGISTER.md` + `docs/audits/REMEDIATION_PLAN.md`.
**Mode:** read-only. **No production code was modified.** `~/.nedotify/` was
never opened.

---

## 1. The headline

> The original audit is **substantially right about the defects and
> substantially wrong about three things**: its most prominent Android
> finding, its stated root cause for the only data-loss defect, and its own
> bookkeeping.
>
> Of **234 original records** re-verified, **176 (75.2 %)** stand with their
> original severity, **42 (17.9 %)** need a severity change, **4** are
> **false positives**, **15** are **conditional** (true only under stated
> conditions), **1** is a pure alias, **1** is a pure merged pointer, **11**
> are **architecture recommendations** (explicitly not defects), and **5**
> **cannot be verified** (they need a device, or they arrived in the corpus
> *while this verification was running* and were recorded rather than dropped).
>
> **The single most consequential result:** the audit's #1 Android priority —
> the `PendingSelectionGate` "play button is dead" finding, which justifies
> remediation wave **W1**, architecture item **A-2**, and the plan's
> "highest-value single change" — is **refuted by the bytecode of the pinned
> Media3 1.11.1**. `MediaController.play()` and `pause()` **do** reach
> `MediaSession.Callback.onPlayerCommandRequest`, and they arrive as
> `Player.COMMAND_PLAY_PAUSE` — exactly the constant the app checks. The
> gate is **not** stuck. Only a *silent veto* survives. Three independent
> `javap` passes (arbiter + two verifiers) agree.

## 2. Verdict tally (233 original records)

| Verdict | Count | Share | Which |
|---|---:|---:|---|
| **CONFIRMED — STATIC** | 177 | 75.6 % | the bulk of the P2/P3 register |
| **CONFIRMED — RUNTIME** | 20 | 8.5 % | P0-01, P1-01…P1-04, P2-16, P2-17, P2-20, P2-21, P2-22, P2-26, P2-36, P2-38, P2-42, P2-43, P2-44, P2-55, P2-68, P2-71, P2-72, P3-04 |
| **CONDITIONAL** | 15 | 6.4 % | P1-01, P2-05, P2-09, P2-11, P2-13, P2-25, P2-46, P2-49, P2-59, P2-65 + X-01, X-02, X-04 + P3-11, P3-84, P3-107, P3-110 |
| **FALSE POSITIVE** | 4 | 1.7 % | the unnamed "XI-08 B P1", REG P2-10, P3-87, P3-99 |
| **ALIAS / MERGED** | 2 | 0.9 % | MAIN-P2-29 (alias of P2-69+P2-70), P3-64 (pointer to P3-35) |
| **RECOMMENDATION** | 11 | 4.7 % | A-1…A-10 (by the report's own words) + MAIN-P2-39 |
| **CANNOT VERIFY** | 5 | 2.1 % | the API-26 read-only-WAL consequence, REG P1-05, and three records that need a device |
| **NOT REPRODUCED / FIXED-OBSOLETE** | 0 | 0 % | — |
| **Total** | **233** | | |

Per-finding rows: `VERIFICATION_MATRIX.csv` (233 rows × 7 columns, no duplicate
ids). Narrative: `VERIFIED_FINDINGS_PART1.md` (P0/P1 + the gate),
`VERIFIED_FINDINGS_PART2.md` (REG P2-17…P2-75 + P3-01…P3-55),
`VERIFIED_FINDINGS_PART3.md` (P3-56…P3-110). The X-01…X-06 and A-1…A-10
verdicts are in the matrix and summarised in `ROOT_CAUSE_MAP.md`.

## 3. Severity changes (40 of 233)

| Change | Count | Findings |
|---|---:|---|
| **P0 → P1** | 1 | P0-01 — the data loss is real and irreversible, but the stated cause is refuted and the affected population is narrower than claimed |
| **P1 → P2** | 4 | P1-01 (lyrics prefix), P1-03 (Yandex 401), P1-04 (30 s callTimeout), and the unnamed **R1.2 P1** (the URI-less `MediaItem`) |
| **P1 → P3** | 1 | the unnamed "XI-08 B P1" (the gate) — **FALSE POSITIVE** as stated; P2-11 likewise → P3 |
| **P2 → P1** | 2 | REG P2-53 (the 59 device tests have never run and they are the only guard on the Room v1→v2→v3 migration) and REG P2-16 (a routine "import backup" needs **183 MB** of heap — re-measured, against a typical 128–192 MB per-app limit — and the OOM kills the process) |
| **P2 → P3** | 21 | REG P2-10 (false positive), P2-13, P2-27, P2-32, P2-33, P2-35, P2-41, P2-46, P2-47, P2-49, P2-51, P2-52, P2-57, P2-59, P2-60, P2-61, P2-62, P2-63, P2-64, P2-67, P2-75, P2-78 + MAIN-P2-39, MAIN-P2-40, MAIN-P2-41 |
| **P3 → P2** | 13 | P3-66, P3-67, P3-68, P3-75, P3-76, P3-78, P3-79, P3-85, P3-103, P3-104, P3-105, P3-108 + MAIN-P2-42 |
| **unchanged** | 177 | |

**One severity call is left open and is recorded as a dispute, not a
majority vote:** **P1-02** (the corrupt preferences file). One verifier argues
**P2** because the fix is a one-line `ReplaceFileCorruptionHandler` per
delegate; the arbiter keeps **P1** because the impact is total and
irreversible — every setting, the **saved queue** and `libraryId()` (so backup
export/import break too) are lost, the 5 s checkpoint fails *silently*, and
the state survives restarts. Both sides agree the mechanism is confirmed at
runtime.

**P1-04 was raised back to P1** by the arbiter after the runtime evidence
arrived: the 30 s `callTimeout` abort is confirmed at runtime (30 016 ms →
`InterruptedIOException`), and the **streaming** path — which the audit did
not examine — uses the same client with one open call per progressive media
item. It is flagged as a **P0 candidate** pending an on-device playback test.

## 4. The four false positives

| # | Finding | Why it is false |
|---|---|---|
| **FP-1** | the unnamed **"XI-08 B P1"** — *"the `onPlayerCommandRequest` callback is never reached by `MediaController.play()`/`pause()` … once tripped, every subsequent Play is dropped … until the user re-picks a track"* | `javap` on `media3-session-1.11.1.aar`: `MediaSessionStub.setPlayWhenReady` / `playForControllerInfo` / `pauseForControllerInfo` all push `iconst_1` = `Player.COMMAND_PLAY_PAUSE` into `queueSessionTaskWithPlayerCommand`, which calls `MediaSessionImpl.onPlayerCommandRequestOnHandler` → the app's callback → `selectionGate.receivedPlayCommand()`. The gate is re-armed at **enqueue** time, before the check at **execution** time. The gate is not stuck. The audit's own P2-11 body says the opposite of its headline — both were shipped. |
| **FP-18** | **REG P2-10** — *"an in-place `MediaItem` replacement splits one listen into two sessions and marks the first completed"* | `ExoPlayerImpl.evaluateMediaItemTransitionReason` (bytecode + upstream source) has **no play-state term**; `replaceMediaItems` reports `DISCONTINUITY_REASON_REMOVE`, so an in-place replacement yields `MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED` → `forceNewSession=false`, `completedPrevious=false` → **one** session, not completed, elapsed time preserved. The branch the audit called unreachable is the *only* branch reached. The app's own `ListeningHistoryTest` pins it. |
| **FP-15** | **P3-87** — *"`REVIEW_RESOLUTION.md` has already rotted: a row's factual premise is false"* | The document is **self-consistent**: `:14-16` states the app *has* a `POST_NOTIFICATIONS` request; `:66` is a different claim (media-session exemption). The premise is a misreading. |
| **FP-16** | **P3-99** — *"the Android's library search covers only device files and completed downloads"* | The paged scan pages the **whole `tracks` table**; a track that was played or added to a playlist is a row in `tracks` and **is** matched. The claimed trigger does not hold. |

Plus **12 OVERSTATED** findings whose mechanism is right but whose impact,
count or causal story is wrong — see `FALSE_POSITIVES.md` FP-2 … FP-14 and
FP-19 … FP-23. The most important of these:

* **FP-2 / FP-3 (P0-01).** The audit says the migration's *wrong identity
  key* is the cause and that the FK cascade takes the playlist entries.
  Both are wrong: `(LOWER(title), LOWER(artist))` **is the desktop's own
  track identity** (`core/database.py:529-544`, introduced in the *same
  commit* as the migration), and with foreign keys **disabled** the
  `playlist_tracks` loss is *identical* — the cascade accounts for none of
  the bulk of it. The audit also **missed a worse loss mode**: the second
  `DELETE FROM playlist_tracks` can remove the playlist entry of a track
  that **survives** the migration (reproduced).

## 5. What the verification *added* that the audit did not report

1. **The 30 s `callTimeout` also bounds the media *stream*, not only the
   download.** `OkHttpDataSource.open()` uses a blocking
   `Call.execute()` (`javap` on `media3-datasource-okhttp-1.11.1.aar`), so
   the shared client's total-call budget governs the progressive media read
   as well. This is a **larger** consequence than the one the audit filed.
2. **The catalogue import *disables* the UI rather than silently ignoring
   it** — `ui/CatalogBrowser.kt:29` sets `working = busy || importing` and
   disables the query field, the buttons and the rows, while showing a
   progress bar and a live counter. REG P2-74's "silent no-ops" is wrong.
3. **A cold `DataStore.first()` is not a file read.** `DataStoreImpl` keeps
   an in-memory `StateFlow` cache; the 10 `appearance.first()` sites are 10
   *collections* of a shared hot flow, not 10 disk reads. REG P2-46's cost
   model is wrong even though its structure is right.
4. **The report's own "35 files / 3 977 LOC / 54.6 %" coverage figure is
   not reproducible** under any rule (strict: 38 files / 4 618 LOC / 63.4 %;
   loose: 26 / 2 984 / 41.0 %) — the true gap is **larger** than reported.
5. **"all 19 Room schema-migration tests" is a 6× overstatement** — 19
   Room-touching tests exist; **3** actually exercise a schema migration.
6. **The "HLS VOD verifier" device test does not exist.** A grep of
   `android/app/src/androidTest` for `Hls|VOD` returns **0**; the 2 Media3
   tests are decoder-handover tests. The report asserts coverage of a test
   surface that was never written.
7. **The desktop's `add_track` de-duplicates by `(LOWER(title),
   LOWER(artist))`** — the migration's grouping key is the app's own
   identity rule, not a foreign "display identity".
8. **P1-01 is narrower than the audit claims.** A live probe of LRCLIB's
   `/api/get` shows the provider **echoes** the prefixed title
   (`trackName='Rick Astley  Never Gonna Give You Up'`), so the candidate is
   *accepted* and the lyrics are found. The defect is confirmed only for
   **non-Latin scripts** and for the **sentinel-artist SAF import**; the
   audit's YouTube trigger is refuted (music.youtube.com returns bare
   titles).
9. **The lint gate is provably not a function of the source.** Three lint runs
   over the **same unchanged source** produced **15**, **13** and **4**
   warnings, and even different "latest version" numbers (Gradle 9.8.1 vs
   9.8.2; core-ktx 1.19.1 vs 1.18.0) — the 4-warning run was made with
   the network black-holed and the lint cache deleted. The audit's own
   "15 warnings" is therefore one of three possible answers, and the
   `NewerVersionAvailable` detector's own text admits it "connects to the
   library every time". The plan's mechanism ("on every build") is wrong —
   the reads are cache-backed — but the **conclusion** is now proven
   experimentally rather than asserted.
10. **P2-16 is worse than the audit claims.** Re-measured independently:
   the live heap at the end of `BackupCodec.decode` is **183 MB**, not
   "120 MB", and the OOM at `-Xmx160m` reproduces. Against a typical
   128–192 MB per-app heap this is a crash on a routine action, not an
   edge case. **Raised to P1.**
11. **The plan's "one-function change" for `haze` is false** — dropping it
   touches **two files at eight sites**, not one function.
12. **The plan's "11.5 s configuration phase" is a cold-daemon artefact** —
   measured 10.657 s cold versus **0.32–0.61 s warm**. The steady-state
   cost of the missing configuration cache is far smaller than the plan
   implies.

## 6. The original report's internal reliability

`AUDIT_INCONSISTENCIES.md` documents **56** distinct inconsistencies. The
most serious:

| # | Inconsistency | Severity |
|---|---|---|
| 1 | **Two conflicting P2 id namespaces inside one document set.** §5.1 numbers P2-01…P2-45; the register numbers P2-01…P2-79/P2-81. They agree only to ≈P2-21. **8+ cross-references in §6/§7/§8/§10/§11 and in the remediation plan resolve to the wrong finding** — e.g. §6 X-03's "(P2-30)" points at the lyrics-taxonomy finding, §7.2's performance table points at five wrong rows, §11 W2's "(P2-43)" points at the album-search finding. | **CRITICAL** |
| 2 | **The #1 Android finding is refuted** (FP-1), and it is the stated justification for wave W1, item A-2 and the plan's "highest-value single change". | **CRITICAL** |
| 3 | **The corpus is unversioned and was mutated *during* this verification**: `git ls-files docs/audits` → **0**; the register grew 473 → 637 lines and the main report 2 349 → 2 451 lines *while it was being audited*, adding P1-05, P2-76…P2-81 and P3-111…P3-116. | **HIGH** |
| 4 | **Lint warnings: 15 vs 17.** §9.1's "LINT_ISSUES=17" is a transcription of `TEST_SUMMARY.json`, not of the XML it cites. The arbiter measured **15** (x6/x5/x2/x1/x1) from the repo's own report file and from a fresh `:app:lintDebug` in an ASCII-path copy. §9.1 is labelled *"observed"* — it is a false claim of observation. | **HIGH** |
| 5 | **Instrumentation count: 59 vs 55.** Measured: **59** `@Test` methods in 15 files. §9.4 (the *not-verified* table) and P3-91 carry the stale 55. | MEDIUM |
| 6 | **"Six subagents ran out of context"** names **7** reviewer slots, and **`XI-09` does not exist in the Android area map** — it is an id from the *older, desktop* audit's area file (`_AUDIT_AREAS.md:61`), which is still in the same directory with no deprecation marker. | HIGH |
| 7 | **The critical finding has no id.** It is called *"the XI-08 B P1"* at 5 sites; §4 defines 4 P1s; the register has **no** P-ids at all. The plan's R1.2 adds a *second* unnamed P1 (the URI-less `MediaItem`). So the set really contains **6** P1-level items, not 4. | CRITICAL |
| 8 | **§4.0's summary table** says "P2 ~35 / P3 ~30" while §1 says 75/110 and the plan says 79/114. | HIGH |
| 9 | **X-01's headline contradicts its own table** ("three mechanisms" vs the table's "five layers"), and the executive summary sides with the table. | MEDIUM |
| 10 | **X-04 says the offline flag is read in "nine places"; its companion P2-46 says "twelve"; P2-46's own body says 14.** The true figure is 13 independent subscriptions / 19 read points. | MEDIUM |
| 11 | **"21 marked [MERGED]"** in the P3 consolidation note — only **2** rows carry the marker. The note was written against an earlier draft (110 rows) and never updated after §5.2 grew to 114. | HIGH |
| 12 | **The earlier desktop audit was silently dropped.** `docs/audits/_FINDINGS_SO_FAR.md` is a *completed* desktop audit (1 P0, 10 P1s, ~35 P2s) — including *"the proxy serves the wrong track's audio"*, *"the OAuth token is stored in plaintext"*, *"the system tray never starts"* and a **second P0-class migration defect 50 lines below** the one reported — and the new report never mentions it, supersedes it, or cites it. | **HIGH** |
| 13 | **The 70 reviewer reports are not in the repository**, so §3.1's independence guarantee, §5.0's `[MERGED ×N]` table and the `F-AN-07-3` / `F-XI-05-2` / `F-XI03-4` ids cannot be checked by anyone. | HIGH |

**Positive result.** The report's epistemic hygiene is genuinely good. It
states plainly that the port has never been run, that no APK was built, that
the instrumentation suite was compiled and never executed, that every
recomposition figure is *derived from source cadences* rather than measured,
and that the backup-OOM figure is a **JVM** measurement whose device
equivalent was not measured. The failures are in **bookkeeping and in one
bytecode claim** — not in fabricated observation.

## 7. The original audit's true reliability score

| Dimension | Score | Comment |
|---|---|---|
| Did it find real defects? | **High** | ~150 confirmed findings, including the only data-loss defect in the project and the only "no gate" diagnosis. |
| Were the mechanisms right? | **Mostly** | 4 outright false positives + 12 materially overstated. The false positives are concentrated in the **Media3 layer** — exactly the layer the report claimed to have read from bytecode. |
| Were the priorities right? | **Partly** | 4 of 5 P1s were over-prioritised; 13 P3s were under-prioritised; the P0 was over-prioritised as to population and under-prioritised as to cause. |
| Were the counts right? | **No** | 15/17 lint, 55/59 instrumentation, 40/42 test files, 35/39 uncovered files, 26/29 columns, 110/114 P3 rows, 35/79 P2, "six"/7 exhausted slots, "1 219"/1 438 LOC, 1 100→"three mechanisms". |
| Was it self-consistent? | **No** | two id namespaces, 56 documented inconsistencies, an unnamed critical finding, a `P3-?` placeholder in a shipped table. |
| Is its remediation plan actionable as written? | **Partly** | W0 and W4 are excellent and unchanged. **W1 and R1.1 must not be executed as written** — they fix a defect that does not exist while leaving the real one (a silent veto) in place. |

## 8. What this verification could not do

* **No device, no emulator, no APK.** The project forbids APK builds
  (`android/AGENTS.md`); `connectedDebugAndroidTest` was not run. Every
  finding that depends on on-device behaviour — MediaSession lifecycle,
  foreground service, Keystore, Room migrations on a device, audio focus in
  practice, the `dataSync` quota, the API-26 read-only-WAL case — is
  **CANNOT VERIFY**, not "confirmed".
* **The platform `org.json` was not executed** (the SDK ships stubs only),
  so P2-73's platform half is derived from the AOSP source.
* **The Gradle test worker cannot start from the non-ASCII repository
  path**; the JVM suite was run from an ASCII-path copy of `android/` with
  the same cache. The result is identical (236 / 0 / 0 / 1) to the XML
  already in `android/app/build/`.
* **The user's real library was never touched.** The P0-01 reproduction used
  two throwaway SQLite databases, one of which extracts the three `DELETE`
  statements **verbatim from `core/database.py`** so the test cannot drift
  from the shipped code.
* **27 records arrived in the corpus during the verification** (register
  Addendum 2 and 3: P1-05, P2-76…P2-81, P3-111…P3-116) and are recorded
  as `CANNOT VERIFY` rather than silently dropped. One of them — **P1-05** —
  *promotes* the audit's own REG P2-59 to P1 after a better measurement, and
  this verification's **independent** measurement agrees with the promotion.

## 9. Bottom line

**The audit earns its place.** It found the project's only data-loss defect,
the only "there is no gate" diagnosis, and roughly 150 real defects. Its
*method* — two independent reviewers per area, bytecode rather than
documentation, explicit "not verified" tables — is the right method and is
the reason the report is mostly right.

But it is **not** the document its own Executive Summary claims to be. Three
corrections must be made before anything is acted on:

1. **Retract the `PendingSelectionGate` headline and rewrite R1.1** to fix
   the *silent veto* (make the refusal observable) and to stop the transient
   focus loss from cancelling the user's pending selection. Do **not** build
   an intent token to fix a stuck gate that is not stuck.
2. **Retract P2-10** and fix the desktop migration's *operation* (merge, do
   not delete; make it atomic; back it up; fix the second `playlist_tracks`
   statement) rather than its *key* — which is already the app's own
   identity rule.
3. **Publish one id namespace** and regenerate every cross-reference; and
   **put `docs/audits/` under version control**, because the corpus was
   mutated while it was being audited and 27 findings are already
   untraceable for exactly that reason.

The fix order that follows is in `RECOMMENDED_FIX_ORDER.md`; the findings
collapse into **17 root causes** (`ROOT_CAUSE_MAP.md`), of which **"there is
no gate"** is the one that explains why the other sixteen survived.
