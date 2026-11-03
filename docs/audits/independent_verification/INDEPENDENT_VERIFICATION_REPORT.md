# NeDotify / AURA Music — Independent Multi-Agent Audit Verification

**Full consolidated report.** Every document produced by the independent
verification of `docs/audits/FULL_PROJECT_AUDIT.md` and
`docs/audits/ANDROID_FINDINGS_REGISTER.md` is reproduced here in one file.

| | |
|---|---|
| **Subject** | the prior audit of the `android/` Kotlin port (and the Windows desktop app it used as a parity oracle) |
| **Verifier** | Principal Software Engineer / Independent Software Auditor / Senior Android Engineer / Security Researcher / QA Architect, with a multi-agent team |
| **Method** | 2 independent verifiers per finding class (code-and-runtime + adversarial), plus an arbiter that re-derived every disputed fact from the artefacts |
| **Mode** | read-only — **no production code was modified**, no APK built, no device used, `~/.nedotify/` never opened |
| **Corpus anchor** | 2026-10-19 20:33 (`docs/audits/` is untracked in git and was **being edited during the verification**) |
| **Records adjudicated** | **233** |
| **Contents** | 9 source documents + the full 233-row verification matrix |

---

## Table of contents

1. [Verification summary](#1-verification-summary) — headline result, verdict tally, severity changes, what was added, document reliability, what could not be verified
2. [Detailed findings — P0, P1 and the pending-selection gate](#2-detailed-findings--p0-p1-and-the-pending-selection-gate) — full per-finding record
3. [Detailed findings — register P2-17…P2-45, P2-46…P2-75, P3-01…P3-55](#3-detailed-findings--register-p2-17p2-45-p2-46p2-75-p301p355)
4. [Detailed findings — P3-56…P3-110](#4-detailed-findings--p356p3110)
5. [False positives and overstated claims](#5-false-positives-and-overstated-claims) — 23 entries with the code that refutes them
6. [Audit inconsistencies](#6-audit-inconsistencies) — 56 internal contradictions in the original report set
7. [Root cause map](#7-root-cause-map) — 17 root causes behind the 207 original records
8. [Recommended fix order](#8-recommended-fix-order) — built only from confirmed findings, plus the hypotheses **not** to implement
9. [Inventory of the original findings](#9-inventory-of-the-original-findings) — re-count, the two conflicting P2 namespaces, the 12 findings that arrived mid-verification
10. [Method and limitations](#10-method-and-limitations) — what was verified first-hand, what was not possible
11. [Verification matrix](#11-verification-matrix) — all 233 records

---



---

# 1. Verification summary

**Verifier:** Principal Software Engineer / Independent Software Auditor /
Senior Android Engineer / Security Researcher / QA Architect, with a
multi-agent team (2 independent verifiers per finding class, plus an arbiter
that re-derived every disputed fact from the artefacts).
**Subject:** `docs/audits/FULL_PROJECT_AUDIT.md` +
`docs/audits/ANDROID_FINDINGS_REGISTER.md` + `docs/audits/REMEDIATION_PLAN.md`.
**Mode:** read-only. **No production code was modified.** `~/.nedotify/` was
never opened.

---

### 1. The headline

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

### 2. Verdict tally (233 original records)

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

### 3. Severity changes (40 of 233)

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

### 4. The four false positives

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

### 5. What the verification *added* that the audit did not report

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

### 6. The original report's internal reliability

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

### 7. The original audit's true reliability score

| Dimension | Score | Comment |
|---|---|---|
| Did it find real defects? | **High** | ~150 confirmed findings, including the only data-loss defect in the project and the only "no gate" diagnosis. |
| Were the mechanisms right? | **Mostly** | 4 outright false positives + 12 materially overstated. The false positives are concentrated in the **Media3 layer** — exactly the layer the report claimed to have read from bytecode. |
| Were the priorities right? | **Partly** | 4 of 5 P1s were over-prioritised; 13 P3s were under-prioritised; the P0 was over-prioritised as to population and under-prioritised as to cause. |
| Were the counts right? | **No** | 15/17 lint, 55/59 instrumentation, 40/42 test files, 35/39 uncovered files, 26/29 columns, 110/114 P3 rows, 35/79 P2, "six"/7 exhausted slots, "1 219"/1 438 LOC, 1 100→"three mechanisms". |
| Was it self-consistent? | **No** | two id namespaces, 56 documented inconsistencies, an unnamed critical finding, a `P3-?` placeholder in a shipped table. |
| Is its remediation plan actionable as written? | **Partly** | W0 and W4 are excellent and unchanged. **W1 and R1.1 must not be executed as written** — they fix a defect that does not exist while leaving the real one (a silent veto) in place. |

### 8. What this verification could not do

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

### 9. Bottom line

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

---

# 2. Detailed findings — P0, P1 and the pending-selection gate

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

## PART 1 — P0 and P1

---

### P0-01 — The one-shot desktop startup migration deletes tracks and cascades away history and playlist entries

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

### P1-01 — The lyrics identity gate rejects any track whose title is "Artist - Song"

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

### P1-02 — A corrupt preferences file is never repaired; no setting can ever be changed again

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

### P1-03 — A single 401 from any Yandex API call destroys the user's Yandex credential

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

### P1-04 — The shared 30-second `callTimeout` aborts every download whose body takes longer than 30 s

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

## PART 2 — The pending-selection gate (the audit's #1 Android finding)

---

### "XI-08 B P1" / REG P2-11 — the closed gate, the swallowed Play

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

### REG P2-12 — the same interruption cancels the in-flight queue set

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

### REG P2-13 — a transient audio-focus loss is reported as a "user interaction"

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

## ADDENDUM — runtime confirmation of P1-01 … P1-04

A second, independent verifier executed the P1 set against the **real**
repository classes (a Gradle unit test injected by an init script, so no repo
file was touched) and against the **shipped** dependency artefacts. That
evidence is recorded here; the matrix carries the updated verdicts.

### P1-01 — CONFIRMED — RUNTIME

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

### P1-02 — CONFIRMED — RUNTIME (severity dispute recorded)

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

### P1-03 — CONFIRMED — RUNTIME

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

### P1-04 — CONFIRMED — RUNTIME (severity held at P1)

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

---

# 3. Detailed findings — register P2-17…P2-45, P2-46…P2-75, P3-01…P3-55

Compact per-finding record. Columns: **verdict · confidence · evidence type ·
original severity → revised severity · confirmed location · note (with every
count correction and every deviation)**.

Full narrative format for P0/P1 and for the gate is in
`VERIFIED_FINDINGS_PART1.md`.

---

### Register P2-17 … P2-45 (arbiter-verified; full evidence format in
`ANDROID_FINDINGS_REGISTER.md` §"P2 register (part 2 of 2)")

| ID | Verdict | Conf. | Sev | Confirmed location | Note |
|---|---|---|---|---|---|
| **P2-17** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryConverter.kt:63-67,80-83`; desktop `services/smart_playlists.py:83-86` | A NULL/empty `rule_json` fails `requireStrictJson` and aborts the whole import; the desktop skips that playlist per-row. |
| **P2-18** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryImport.kt:46-49`; `data/DesktopLibraryConverter.kt:35,37,102,118,134` | Only the columns that exist are selected and the converter defaults them; `is_favorite` / `added_at` / `duration` / `source` are silently lost and the notice says nothing. |
| **P2-19** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryConverter.kt:18,70`; `data/BackupCodec.kt:30,112` | The import round-trips through `BackupCodec.encode`, so `MAX_BYTES = 16 MB` governs it; the error text names a JSON "copy" for a `.db` file, during *preview*. |
| **P2-20** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryConverter.kt:19,44,61,66` | **Verified in source**: `DesktopLibraryConverter.kt:19` `UUID.nameUUIDFromBytes(("nedotify-desktop-v1\u0000"+cleanOrigin.lowercase(Locale.ROOT)).toByteArray(Charsets.UTF_8))` namespaces the playlist / session / smart-playlist ids as `desktop:$libraryId:$id`. Two PCs with the same label collide. |
| **P2-21** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryImport.kt:16-25,41`; desktop `core/database.py:112-113,1857-1874` | The importer copies one stream; the `-wal` sidecar is never read, so a copy taken without a clean close is a *valid but stale* database. |
| **P2-22** | CONFIRMED — STATIC | High | P2 | `data/CatalogProviders.kt:31,35,48,50,53,58,60` | AOSP `optString` on an explicit null returns `"null"`; the reference implementation returns `""`. **65 of the 67 `optString` sites are uncompensated** (the audit said "53 of 55"). |
| **P2-23** | CONFIRMED — STATIC | High | P2 | `data/CatalogProviders.kt:141-150` | `likedTracks()` issues exactly one unpaginated `GET` and never checks completeness, while the sibling playlist path does. |
| **P2-24** | CONFIRMED — STATIC | High | P2 | `ui/MusicViewModel.kt:376-389`; `data/CatalogProviders.kt:100-103` | `playable()` is a pure metadata conversion; account entitlement is discovered only at play time, so the import reports *"недоступно: 0"*. |
| **P2-25** | **CANNOT VERIFY** | Low | P2 | `data/DesktopLibraryImport.kt:40` | Read-only WAL needs SQLite 3.22.0; API 26/27 ship older SQLite. The audit itself labels this a **HYPOTHESIS**; it needs an API-26 emulator. |
| **P2-26** | CONFIRMED — STATIC | High | P2 | `data/DesktopLibraryConverter.kt:19,33`; `data/BackupMerge.kt:17-21` | Local tracks from two libraries under one origin share `source="local"` / `sourceId=""`, so the conflict check never fires and the first row's metadata **and** `localUri` win. |
| **P2-27** | CONFIRMED — STATIC | High | **P3** | `player/DualDeckPlayer.kt:171-181` | The standby copies the whole media-item list and rebuilds a full shuffle order although it plays one item. |
| **P2-28** | CONFIRMED — STATIC | High | P2 | `player/DualDeckPlayer.kt:218-222`; `player/AudioRuntime.kt:25-29,46,50` | `applyVolumes()` reads the **published UI snapshot** `AudioRuntime.status.value.eqSupported` to decide the EQ headroom, while `AudioEffectsController` already knows the truth. |
| **P2-29** | CONFIRMED — STATIC | High | P2 | `downloads/TrackDownloadWorker.kt:41-42,63-65` | The worker enters the foreground **before** taking the `Semaphore(2)` permit; WorkManager's default `maxSchedulerLimit` is 20. |
| **P2-30** | CONFIRMED — STATIC | High | P2 | `downloads/DownloadStorage.kt:25`; `downloads/Downloads.kt:40`; `downloads/TrackDownloadWorker.kt:75-78` | No per-download byte ceiling, no `Content-Length` check, no `StatFs` probe, `NoOpCacheEvictor`; `ENOSPC` is an `IOException` and therefore *retryable*. |
| **P2-31** | CONFIRMED — STATIC | High | P2 | `ui/MusicViewModel.kt:158-163`; `ui/SearchScreen.kt:98` | **Verified in source**: `SearchScreen.kt:98` calls `model.play(track, result.tracks)` — the **whole** result list is the queue — and `MusicViewModel.kt:161` `repository.dao.ensureTracks(items)` writes every one of them into the permanent library. |
| **P2-32** | CONFIRMED — STATIC | High | P2 | `ui/MusicViewModel.kt:143-153`; `ui/SearchScreen.kt:84-99` | `SearchState(busy=true)` carries an **empty** track list, so the list collapses on every keystroke. |
| **P2-33** | CONFIRMED — STATIC | High | **P3** | `ui/PlayerScreen.kt:75` | `itemsIndexed(now.queue, key={index,item->"$index:${item.first}"})` — the index prefix makes the key unstable under reordering. |
| **P2-34** | CONFIRMED — STATIC | High | **P3** | `ui/MusicViewModel.kt:20-22,108,129-142` | `NowPlaying` carries the whole queue; `update()` rebuilds it and `MutableStateFlow` compares it on every event. |
| **P2-35** | CONFIRMED — STATIC | High | P2 | `ui/PlayerScreen.kt:78-81`; `ui/MusicViewModel.kt:20-22,140` | The queue is `List<Pair<String,String>>` (id → title), so a row can render no artist, no cover and no duration. |
| **P2-36** | CONFIRMED — STATIC | High | P2 | `ui/Design.kt:41-44` | Only 7 of ~40 Material colour roles are overridden; the rest keep the M3 baseline (selected chip, dialog surfaces, sliders). |
| **P2-37** | CONFIRMED — STATIC | High | P2 | `ui/MusicApp.kt:83-89`; `ui/LibraryScreen.kt:38-45,140-143` | The `when(route)` branch **replaces** the screen, so `rememberSaveable` state (sort order, open dialogs, typed name, scroll) is dropped on every tab switch. |
| **P2-38** | CONFIRMED — RUNTIME | High | P2 | `android/review/VERIFY.ps1:3-9`; `SOURCE_SHA256.txt` | **160 match / 27 differ / 0 missing**; 7 source files + `app/build.gradle` unlisted; the manifest is an allow-list. **Duplicate of REG P2-55.** |
| **P2-39** | CONFIRMED — STATIC | High | P2 | `AGENTS.md:3-5,7-8,24-25` | The root `AGENTS.md` says *"the sole UI is `ui/web_new_v2/`"* and never points at `android/AGENTS.md`; `STATUS.md` and `README.md` contain **0** matches for "android". |
| **P2-40** | CONFIRMED — STATIC | High | P2 | `android/AGENTS.md:9-10` | It protects `~/.nedotify` — a **host** path that cannot exist on the device — and never names the device library. |
| **P2-41** | CONFIRMED — STATIC | High | P2 | `android/review/REVIEW_A.md:1-34`; `REVIEW_B.md:1-31` | The two files a reader opens first are the reviewer **briefs** (0 findings); the reports are in `received/` one directory down. |
| **P2-42** | CONFIRMED — STATIC | High | P2 | `android/review/*_SOURCE_SHA256.txt` (7 files) | `PRE_AUDIT2_SOURCE_SHA256.txt` is **byte-identical** to `SOURCE_SHA256.txt` (`b1a9c20e…`); 3 of the 39 baseline entries no longer exist; `git ls-files android` → 0. |
| **P2-43** | CONFIRMED — STATIC | High | P2 | `data/ListeningReports.kt:86-113,115-117` | The current window is `[midnight, now]` (incomplete) and the previous is a **full** N-day period; `changePercent` therefore biases by up to −14 %. |
| **P2-44** | CONFIRMED — STATIC | High | P2 | `data/Models.kt:160-165` | **Verified in source**: `GROUP BY name` uses SQLite's default **BINARY** collation and `COLLATE NOCASE` appears only in the `ORDER BY`; the unknown-artist bucket is admitted through the `CASE` expression. |
| **P2-45** | CONFIRMED — STATIC | High | P2 | `data/SmartRules.kt:93-113`; desktop `services/smart_playlists.py:143-151` | **Verified in source**: the desktop uses `t.last_played` and `COALESCE(t.play_count, 0)` and sorts by `t.play_count`; the Android rules use *measured listening time*. `SmartRules.kt:55` (`originalKeys = keys - setOf("downloaded","unplayed","notPlayedDays")`) confirms three desktop rules are not portable. |

---

### Register P2-46 … P2-75

| ID | Verdict | Conf. | Evidence | Sev | Confirmed location | Note |
|---|---|---|---|---|---|---|
| **P2-46** | CONDITIONAL | High | static (grep) | P2 → **P3** | `data/Preferences.kt:10-11,15-17,39`; 10 cold `appearance.first()` sites | Body confirmed; the **title's "12" is wrong** — there are **10** cold `appearance` reads + 3 `audioSettings` + 1 `values` = **14**; `player/PlaybackService.kt:238` is a *hot* collection, not a cold read. The wrong "12" is reproduced in `FULL_PROJECT_AUDIT.md` §5.1 P2-36 and in A-6. |
| **P2-47** | CONFIRMED — STATIC | High | static + bytecode | P2 | `player/PlaybackService.kt:55-57`; `downloads/DownloadKeys.kt:8-21` | No `setCacheKeyFactory` on the streaming path (the only one in the tree is the *download* path). `javap` on media3-datasource 1.11.1: `CacheKeyFactory.DEFAULT` = `key ?: uri.toString()`. Desktop keys by track identity (`core/proxy.py:777-780`). *Deviation:* within the TTL window the same URL **is** re-read, so "the bytes are never read again" is true only across re-resolution/restart. |
| **P2-48** | CONFIRMED — STATIC | High | static | P2 | `data/LibraryRepository.kt:29-42`; `android/PORTING_STATUS.md:105-108` | `resolveRemote` calls exactly one provider, with no catch and no fallback. The desktop cascade (3 SoundCloud query variants + a YouTube tier, and the reverse direction) confirmed. The `LOGIN_REQUIRED` quote confirmed verbatim. |
| **P2-49** | CONDITIONAL | High | static + executed probe | P2 | `data/CatalogProviders.kt:111`; `downloads/DownloadKeys.kt:13-14` | The 45 s TTL and the never-read `expiresAt` are confirmed. **The stated cause is wrong:** the allow-list decides which *query parameters* are stripped, but the Yandex signature and `ts` live in the **path**, which is never normalised for any host. Executed probe: the Yandex key changes on every re-resolve; the SoundCloud key does not. |
| **P2-50** | CONFIRMED — STATIC | High | static + bytecode | P2 | `downloads/TrackDownloadWorker.kt:69-78` | The expected `total` is received and discarded; the row is written `(size,size,100f)`. `javap` on media3-datasource 1.11.1: `CacheWriter` reads to EOF when the length is unknown and `Cache.commitFile` commits whatever was written. The desktop's three checks confirmed. *Deviation:* a `Content-Length`-declared truncation fails loudly (OkHttp raises `ProtocolException`), so only a **chunked/short** or a **wrong-object** body is silent. |
| **P2-51** | CONFIRMED — STATIC | High | static + bytecode | P2 (impact MEDIUM) | `player/PlaybackService.kt:55-69`; `data/Sources.kt:48,51` | Grep: `setUserAgent` 0 hits, `setDefaultRequestProperties` 0 hits, `Origin` 0 hits; `User-Agent` only on the two metadata helpers; `Referer` only in the lyrics cascade. OkHttp 4.12.0's default UA is `okhttp/4.12.0` (confirmed by `javap` on `BridgeInterceptor`). **Deviation:** the repo's own `android/review/PROVIDER_PROBE.json` records the SoundCloud CDN serving the manifest (200) and a media segment (206) to the *same header-less client* — the "403 on the first byte" is a **risk, not an observed defect**. |
| **P2-52** | CONFIRMED — STATIC | High | static | P2 → **P3** (defence-in-depth) | `data/Sources.kt:115,176`; `data/YandexDownloadInfo.kt:29-36`; `data/ProviderHttp.kt:30` | Both prefix-only checks confirmed; the Yandex `trustedUrl` allow-list confirmed and applied to exactly one of three providers; `followRedirects(false)` exists only on the *provider-API* client; `usesCleartextTraffic="false"` confirmed. The desktop closes all four holes (host list, private-IP rejection, DNS resolution, per-redirect check). |
| **P2-53** | CONFIRMED — STATIC | High | static (counted) | P2 → **P1** | `android/verify.ps1:5`; `.github/workflows/ci.yml` | Counted **15 files / 59 `@Test` methods / 0 executed**; the per-area split (Room 19, Compose 27, SAF 7, Keystore 4, Media3 2) is exact. `connectedDebugAndroidTest` appears only inside a received *review report*, in no script. The repo's single CI workflow has no Android job. **Raised to P1**: this is the only guard on the Room v1→v2→v3 migration, and its failure mode is silent library corruption on upgrade. |
| **P2-54** | CONFIRMED — STATIC | High | static | P2 | `android/app/build.gradle:25,27`; `android/app/schemas/…/{1,2,3}.json` | Both build-script lines confirmed; 3 schema files present (`1.json` 8 404 B, `2.json` 10 927 B, `3.json` 11 950 B); `git ls-files android` → 0; `git status --porcelain -uall -- android` → 193 untracked files. *Refinement:* `3.json` **is** reproducible by every KSP run; only `1.json`/`2.json` are not. `android/.gitignore` does **not** exclude the schemas. |
| **P2-55** | CONFIRMED — RUNTIME | High | executed re-hash | P2 | `android/review/VERIFY.ps1:3-9`; `android/review/SOURCE_SHA256.txt` | Independently re-hashed all 187 entries: **match=160, differ=27, missing=0** — exact. The 27 mtimes span 09:38:36–09:46:48, after the manifest's 07:41:31. Seven `app/src` files are absent from the manifest plus `app/build.gradle`. `LocalArtworkTest.kt` sha256 `dec61cf3…` is in **none** of the seven manifests. *Alias:* the same defect is registered **twice inside the register** — as P2-38 and P2-55. |
| **P2-56** | CONFIRMED — STATIC | High | static | P2 | `android/run-emulator.ps1:2-3,18-20,44-47`; `android/README.md:8-11`; `android/review/DEVICE_ACCEPTANCE.md:3` | Every element confirmed: the hard-coded `C:/Temp/nedotify-android/sdk`, the pre-built-APK precondition, `adb install -r` + `am start`, no `am instrument`, no Gradle invocation, a 4-key `EMULATOR_SETUP.json`, «Статус: **не выполнена**», and **0** `*.apk` under `android/`. *Addition:* `run-emulator.ps1:19` tells the user to "Build the APK with verify.ps1 first", but `verify.ps1`'s default task list **cannot** produce an APK — the script's own remediation instruction is wrong. |
| **P2-57** | CONFIRMED — STATIC | High | static + AAR | P2 → **P3** | the five `ui/*Test.kt` androidTest files | Exactly 5 files, v1 API, no v2 import anywhere; one deprecation warning per file in `BUGFIX_CHECKS.log:57-61`; the v2 package **is** present in `ui-test-junit4-android:1.12.1`. *Caveat:* only `v2.createAndroidComposeRule` was found in the cached android artifacts — `v2.createComposeRule` was not; the migration plan must re-check the API surface. These are deprecation warnings, not lint errors; the build is unaffected. |
| **P2-58** | CONFIRMED — STATIC | High | static | P2 | `data/SearchAggregate.kt:30`; `data/LibraryRepository.kt:69` | The guard is exactly `tracks.isEmpty() && outcomes.any { it.isFailure }`. `SearchAggregateTest.kt` pins only the empty-local variant. The SoundCloud scrape is 2 910 777 B (exact, from `PROVIDER_PROBE.json`) and sits inside the **6.5 s** outer budget while its own timeout is 12 s — so the outer fires first. *Deviation:* the scrape cost is paid only on the **first** SoundCloud search per process (the client id is memoised). |
| **P2-59** | CONDITIONAL | High (mech.) / Med (timings) | static + executed re-measurement | P2 → **P3** | `data/LibraryRepository.kt:55-67`; `data/Models.kt:104-105` | Mechanism confirmed (`providerTimeoutMs = 6_500` applies to the local task; no `addedAt` index; `USE TEMP B-TREE FOR ORDER BY` on every page). **The quoted timings are NOT reproducible.** Re-measured: one page 2 000/10 000/20 000 → 0.0020/0.0086/0.0164 s; full loop worst case → **0.0135/0.3020/0.8908 s** (audit claimed 0.007/0.132/0.537 s). Every configuration finishes far inside 6.5 s, so the outcome is **not reachable** at realistic library sizes. |
| **P2-60** | CONFIRMED — STATIC | High | static + bytecode | P2 → **P3** | `data/Sources.kt:47-49,96,143,146-168`; `ui/MusicViewModel.kt:143-153` | `viewModelScope` = `Dispatchers.Main.immediate` confirmed by `javap` on lifecycle-viewmodel 2.10.0; `async` inherits the caller; the `JSONTokener` parse and the 50 000-node `visit` walk are on the main thread. Response sizes 125 981 B / 571 732 B are exact. *Deviation:* the 571 732 B YouTube response is a POST whose JSON is **also** parsed on the main thread before the walk — the impact slightly understates the cost. |
| **P2-61** | CONFIRMED — STATIC | High | static + bytecode | P2 → **P3** | `data/ProviderHttp.kt:29-31,36-50,51-69` | The 2 MiB cap is confirmed; the body is read on the OkHttp thread but the continuation resumes into the caller's Main.immediate context, so the parse and the depth pre-scan run on the main thread. All three catalogue entry points are `viewModelScope` launches. *Note:* the register's own side-effect text is right — the per-item **mapping** is the larger half of the cost. |
| **P2-62** | CONFIRMED — STATIC | High | static | P2 → **P3** | `ui/MusicViewModel.kt:382`; `data/CatalogMatcher.kt:71-75`; `data/ProviderHttp.kt:38` | The 401/403/429 message mapping is confirmed; `httpCode` has **0** reads in the whole `ui/` tree. *Deviation:* the **message** does survive in paths that rethrow (`ui/MusicViewModel.kt:348` shows "Срок входа истёк…"), so the loss is confined to the per-item import loop and to `CatalogMatcher.resolve` — the title's "before it reaches the user" over-generalises. |
| **P2-63** | CONFIRMED — STATIC | High | static | P2 → **P3** | `ui/LibraryScreen.kt:50,56,64,72,76` | The counter and the tile use `state=="complete"`; the list renders **every** download row. *Addition:* the header's byte total on the same line also mixes in-flight bytes — the inconsistency is in two places, not one. |
| **P2-64** | CONFIRMED — STATIC | High | static | P2 → **P3** | `ui/MusicViewModel.kt:280,450-453` | `require(name.isNotBlank())` → `IllegalArgumentException("Failed requirement.")` → `error.message` straight into the snackbar. **Latency confirmed:** both call sites disable the button while the name is blank (`ui/LibraryScreen.kt:142`, `ui/MusicApp.kt:104`). *Addition:* `data/LibraryRepository.kt:126` is a **second, independent** `require` (create, not rename), equally latent. |
| **P2-65** | CONFIRMED — STATIC | High | static | P2 | `ui/MusicViewModel.kt:154-188,356-368`; `ui/PlaybackPreparation.kt:14-17,22-24` | All **eight** transport/queue commands call `cancelPendingPlayback()` first. The 20 s window is confirmed (`ui/MusicViewModel.kt:363`). `PlaybackPreparation.cancel()` bumps the generation so `onReady` is skipped for the cancelled one. *No over-statement* — but the register omits that `startFlow`, `playCatalogTrack` and `offline()` also cancel, which is exactly the split the fix recommends. |
| **P2-66** | CONFIRMED — STATIC | High | static | P2 | `data/LyricsCascade.kt:104-109`; `data/Sources.kt:228,236`; `ui/PlayerScreen.kt:166-169` | The swallowing `catch (_: Exception)` and the **deliberate** 404-is-not-an-error rule are confirmed: a 404 primary + a failed cascade produces **no exception at all** ⇒ "Текст не найден". The desktop's three states confirmed (`services/lyrics_lookup.py:373`). |
| **P2-67** | CONFIRMED — STATIC | High | static | P2 → **P3** | `data/Sources.kt:217-218,237-243` | `forceRefresh` bypasses both caches; the write-back is unconditional and an empty result is written with the **10-minute** negative TTL, replacing a **24-hour** entry — in memory *and* on disk. *Deviation:* the desktop contrast is **over-stated** — `services/lyrics_lookup.py:377-378` remembers an `unavailable` result unless the app is offline; it is not "never remembered". The Android defect stands on its own. |
| **P2-68** | CONFIRMED — RUNTIME | High | executed (verbatim `LyricsIdentity` compiled) | P2 | `data/LyricsCascade.kt:57-58,79-82` | The gate is `containsAll` (superset); the desktop is `artist_matches` = **intersection** (`services/music_matching.py:48-52`). Executed: `track.artist='Artist feat. Guest'` vs `provider.artist='Artist'` → **rejected** on Android, **accepted** on the desktop. |
| **P2-69** | CONFIRMED — STATIC | High | static | P2 | `data/LyricsCascade.kt:96,103-109` | `providerTimeoutMs = 2_200`; strictly serial. Per-provider request counts verified: LRCLIB **1**, NetEase **1+4=5**, QQ **5**, Genius **1+4=5** — exactly as claimed. At 400–800 ms RTT, 5 sequential requests need 2.0–4.0 s > 2.2 s. The desktop runs the providers **in parallel** under one 8 s budget. *Deviation:* the register's "the desktop's `HTTP_TIMEOUT` = 6 s" was not found; the verified constant is `BUDGET = 8.0`. |
| **P2-70** | CONFIRMED — STATIC | High | static (arithmetic) | P2 | `ui/MusicViewModel.kt:442`; `data/Sources.kt:225`; `data/LyricsCascade.kt:96,105` | 3 500 + 4 × 2 200 = **12 300 ms > 12 000 ms** by 300 ms, confirmed from the three constants. *Deviation:* 12.3 s is the worst case of the **whole lookup** (primary + cascade); the cascade alone is 8.8 s — the title's "the cascade's own worst case" is loose. |
| **P2-71** | CONFIRMED — RUNTIME | High | executed (verbatim `LyricsIdentity` compiled) | P2 | `data/LyricsCascade.kt:25,36-55,76-78` | Strict version-set equality confirmed; no base-fallback branch exists. Executed: all ten version markers (Remix/Slowed/Sped Up/Live/Remastered/Edit/Nightcore/Acoustic/Instrumental/dash form) are **rejected** against the plain title. The desktop accepts remix/slowed/sped (`BASE_FALLBACK_VERSIONS`) — **not** live/remaster/edit, so the divergence is narrower than the register's probe list implies. The `LyricsCascadeTest.kt:38` assertion (two different remixes do not match) still holds. |
| **P2-72** | CONFIRMED — RUNTIME | High | executed | P2 | `android/verify.ps1:7,56,63,74` | The script exits 1 with **no Gradle output** when the output is captured; it works uncaptured (`BUILD SUCCESSFUL`, exit 0). The minimal reproducer terminates with `System.Management.Automation.RemoteException` (inner `NativeCommandError`), **not** "NativeException" as claimed. *Mechanism refinement:* `verify.ps1:63` calls `gradlew.bat` with **no** redirection and does **not** terminate on its own — the termination is produced by the **caller's** `2>&1` merge. `android/local.properties` sha256 was identical before and after every run. |
| **P2-73** | CONFIRMED — STATIC | High (reference) / Med (platform) | static + executed reference probe | P2 | `android/app/build.gradle:57`; `data/Sources.kt:106,113,184,233` | The reference behaviour was **executed**: `optString(NULL)` → `""`; `getString` on a null/number → `JSONException`; duplicate key → `JSONException`. The AOSP side was read from the **AOSP source** (the local SDK has stubs only) and matches. **Two corrections:** (a) the two production shims are **not** "dead code on the JVM classpath" — they also fire for the JSON *string* `"null"`, which the reference also returns; (b) the "53 of 55 call sites" figure is stale — there are **67** `optString` call sites today and **65** are uncompensated, so the exposure is *larger* than stated. |
| **P2-74** | CONFIRMED — STATIC | High | static | P2 | `ui/MusicViewModel.kt:325,343,357,373,376,379,392` | All three guards quoted and confirmed **silent** (no `error` write, no `message` write). The cap is `take(500)` and the per-item timeout `withTimeout(20_000)`; the worst case is **2 h 46 min 40 s** — the audit's "~2.8 h" is right. *Addition:* `playCatalogTrack` also sets `importing=true` (`:360`) for a single-track preparation, so the same freeze occurs during a normal play action. |
| **P2-75** | CONFIRMED — STATIC | High | static + executed test run | P2 → **P3** (a coverage gap, not a defect) | `player/PlaybackService.kt:173`; `app/src/test/.../PlaybackMutationTest.kt:18-21` | Grep of the whole JVM test tree: `MusicViewModel` **0**, `PlaybackService` **0**, `LibraryRepository` **0**, `DualDeckPlayer` **0**, `TrackDownloadWorker` **0**. The test supplies its own predicate. `:app:testDebugUnitTest` executed: **42 XML files, 236 tests, 0 failures, 0 errors, 1 skipped** — the audit's number is exact. **The "1 219 LOC" figure is wrong**: the measured total is **1 469** lines (and the register's own per-class numbers already sum to 1 438), so the gap is *larger*, not smaller. |

---

### P3-01 … P3-55 (verifier A, full pass)

| ID | Verdict | Conf. | Sev | Confirmed location | Note |
|---|---|---|---|---|---|
| P3-01 | CONFIRMED — STATIC | High | P3 | `ui/MainActivity.kt:54,78,95` | 3 `takePersistableUriPermission` sites, **0** `releasePersistableUriPermission`. *Impact correction:* the platform cap is 128 grants and the `SecurityException` is **caught and reported** ("Часть файлов нельзя сохранить…"), not a crash; MediaStore scans take no grants. |
| P3-02 | CONFIRMED — STATIC | High | P3 | `ui/MainActivity.kt:112-114,124-126` | No rationale, no "already asked" flag, no route to app settings (the notification path has all three). *Impact correction:* a message **is** shown; "the button silently does nothing" is wrong. |
| P3-03 | CONFIRMED — STATIC | High | P3 | `ui/MusicViewModel.kt:79`; `ui/MusicApp.kt:54` | The channel is a conflating `MutableStateFlow<String?>`. *Impact correction:* the conflation window is the snackbar's display time (the message is reset to `null` only after `showSnackbar` returns), so "never shown" is overstated. |
| P3-04 | CONFIRMED — RUNTIME | High | P3 | `data/Sources.kt:28`; `ui/MusicViewModel.kt:151` | The raw `IOException` message reaches the UI. *Scope correction:* the *provider* transport already curates (`data/ProviderHttp.kt:35`); the leak is `MusicNetwork` only. |
| P3-05 | CONFIRMED — STATIC | High | P3 | `player/PlaybackService.kt:76,113` | The flag is set on every `handleSetMediaItems` and cleared only in `onMediaItemTransition`. *Impact correction:* a set that produces no transition leaves the flag set, so the **next** unrelated transition gets `forceNewSession=true`. |
| P3-06 | CONFIRMED — STATIC | High | P3/trivial | `player/PlaybackService.kt:81-82` vs `downloads/TrackDownloadWorker.kt:96` | Identical `PendingIntent` (request code 0, same intent, `FLAG_UPDATE_CURRENT`). Harmless today, as the row says. |
| P3-07 | CONFIRMED — STATIC | High | P3 | `player/PlaybackService.kt:183-186,191-232`; `player/DualDeckPlayer.kt:110-115` | 720/h + 1 800/h + 3 600/h = **6 120/h** confirmed (and a *floor* — the deck tick is 200 ms/40 ms during a fade). *Impact correction:* the loops die with the service, so "the process can never go fully idle" is wrong. |
| P3-08 | CONFIRMED — STATIC | High | P3 | `player/PlaybackService.kt:235,258-293`; `player/QueueSelection.kt:26-30` | `dao.downloads()` emits on every state change → `refreshQueueSources` → a full data-class deep compare per queue item, on the main thread. |
| P3-09 | CONFIRMED — STATIC | High | P3 | `player/DualDeckPlayer.kt:156-159,196-216` | The gain step exists **only** on the `STATE_ENDED` branch (progress < 1): `handover()` resets the gains *before* the slot swap. On the normal `progress>=1` path there is no step. |
| P3-10 | CONFIRMED — STATIC (conditional) | High | P3 | `player/DualDeckPlayer.kt:118-123,139-142,256-258` | **OVERSTATED** — see `FALSE_POSITIVES.md` FP-4: `configure()` does not call `onUserInteraction()`; it reaches it only via `finishIfEnded()` → `pauseForReason()`, which needs autoplay **off** and `STATE_ENDED`. |
| P3-11 | CONDITIONAL | Medium | P3/informational | `player/QueueSelection.kt:38` | The code fact holds (`?:retained.first()` wraps to the head). But no contract documents "the next" for the all-tail-missing case and the desktop has no equivalent path — the row's own fix offers "amend the contract". Half a contract decision, not a defect. |
| P3-12 | CONFIRMED — STATIC | High | P3 | `player/ListeningClock.kt:9` vs `core/listening.py:27` | The desktop caps a tick at 15 s (`delta = max(0.0, min(15.0, now - last_tick))`); the Android has no upper bound. |
| P3-13 | CONFIRMED — STATIC | High | P3 (dup of MAIN-P2-44) | `data/Models.kt:59,106,177,179` | Count = **4** confirmed; the siblings at `:76,:77,:78,:81` and `DiscoveryEngine.kt:19` do carry tiebreakers. *Duplicate:* MAIN-P2-44's "Note" already lists these four. |
| P3-14 | CONFIRMED — STATIC | High | P3 | `data/LibraryRepository.kt:87-91,103-106` | MediaStore scan → `local:<mediaId>`; SAF import → `document:<uuid>` → two rows with independent favourite/download/history state. |
| P3-15 | CONFIRMED — STATIC | High | P3 | `data/DesktopLibraryImport.kt:46,50` | The **column** names come from the untrusted copy and are interpolated unquoted; the **table** names are hard-coded literals (`:65-69`). The bound (read-only copy, first statement only) is correct. |
| P3-16 | CONFIRMED — STATIC | High | P3 | `data/Models.kt:93-101,138-145` | Recomputed: **≈422 100** statements at the documented caps (history costs 3 each, not 1) in one transaction, no cancel path. The order of magnitude is right. |
| P3-17 | CONFIRMED — STATIC | High | P3 | `data/ProviderConnections.kt:107-110` → `data/ProviderHttp.kt:38` | A wrong token → 401 → "Срок входа истёк. Подключите сервис заново", passed through verbatim. |
| P3-18 | CONFIRMED — STATIC | High | P3 | `data/SecureProviderStore.kt:64` (vs `:54`) | `cipher.init(ENCRYPT_MODE, key(true))` is **outside** the try; the read path's `key(false)` is inside. *Addition:* the raw `javax.crypto` exception escapes `write`, so an English message reaches the UI. |
| P3-19 | CONFIRMED — STATIC | High | P3 / **decision to record** | `data/ProviderHttp.kt:29-30` | No `CertificatePinner` anywhere; three origins carry tokens. This is a **hardening recommendation**, not a contract violation — the row says so itself. |
| P3-20 | CONFIRMED — STATIC | High | P3 | `ui/MusicViewModel.kt:351-355`; `data/CatalogMatcher.kt:66-76` | The Spotify path stores the *candidate*'s metadata; the parsed catalogue metadata is used only to find it. The Yandex path keeps it, so the divergence is Spotify-specific. |
| P3-21 | CONFIRMED — STATIC | High | P3 | `data/ProviderHttp.kt:31,51` | No `maxBytes` seam; count = **2** account-size-growing endpoints (both Yandex); Spotify's are paged at 50. |
| P3-22 | CONFIRMED — STATIC | High | P3 | `player/PlaybackService.kt:127-138` vs `downloads/TrackDownloadWorker.kt:124-129` | A 401/403 is an `InvalidResponseCodeException`, not a `SourceFailure` → the generic "…или выберите другой источник". The download path *does* distinguish it. |
| P3-23 | CONFIRMED — STATIC | High | P3 | `data/Sources.kt:121-134` vs `services/soundcloud_service.py:83-85,143-146` | The message is false for DRM; the desktop has a distinct verdict and a 1-hour negative cache; the Android has none. |
| P3-24 | CONFIRMED — STATIC | High | P3 / **recommendation** | `data/Sources.kt:115,176` | https-only, no host allow-list, no redirect-destination check. Bounded by `usesCleartextTraffic="false"` and by the absence of credentials on the media request — defence in depth. |
| P3-25 | CONFIRMED — STATIC | High | merged → MAIN-P2-43 | `data/LibraryRepository.kt:61`; `data/Models.kt:47,104` | The projection has no `album`; the filter tests title/artist only. |
| P3-26 | CONFIRMED — STATIC | High | P3 | `data/LibraryRepository.kt:54-71` | `source` is not validated (anything else falls through to SoundCloud); the query is unbounded at the data layer. Not reachable from the current UI. |
| P3-27 | CONFIRMED — STATIC | High | P3 | `data/Sources.kt:140-170`; `data/CatalogMatcher.kt:66-76` | No playability pre-flight; the matcher commits to the first candidate and never retries the other provider. |
| P3-28 | CONFIRMED — STATIC | High | P3/informational | `ui/SearchScreen.kt:96` | The UI prints the *returned* count. Caps: local 100, SoundCloud 25, YouTube 30; desktop 50 — parity is roughly right. |
| P3-29 | CONFIRMED — STATIC | High | P3 (dup → P3-78) | `data/Sources.kt:234-235` | Only the LRCLIB branch sets `source="LRCLIB"`; the cascade hits carry `source=""`, and the empty value is persisted into the disk cache. |
| P3-30 | CONFIRMED — STATIC | High | P3 / hardening | `data/LyricsCascade.kt:189-196` vs `data/Sources.kt:22-23` | `safeGeniusPage` validates the initial URL; the fetch uses the shared client, which keeps `followRedirects=true`. |
| P3-31 | CONFIRMED — STATIC | High | P3 | `data/LyricsDiskCache.kt:37,46-48` | The sweep only matches `[0-9a-f]{64}\.json`; the `.tmp` file is never reclaimed if the process dies between the write and the move. The 1.2 MB orphan cap is confirmed. |
| P3-32 | CONFIRMED — STATIC | High | P3 | `data/DiscoveryEngine.kt:28,37,46-49` vs `services/artist_identity.py:9-10` | The Android key is `trim().lowercase()` with no Ё→Е; the desktop's `name_key` does the fold. *Note:* `CatalogMatcher.kt:19` and `LyricsCascade.kt:33` **do** normalise — the gap is specific to the discovery path. |
| P3-33 | CONFIRMED — STATIC | High | P3 | `data/SmartRules.kt:22-37`; `data/DiscoveryController.kt:74-78` | An all-neutral rule set is accepted and the dialog's defaults are exactly that; there is **no** count cap on `createSmart`. The desktop refuses both (`services/smart_playlists.py:48-49, 96-98`). |
| P3-34 | CONFIRMED — STATIC | High | P3 | `player/PlaybackService.kt:338`; `data/Preferences.kt:49` | The key says `queue_v1`, the payload says `"version":2`, and the read path never looks at `version` — it accepts any shape and a malformed one is swallowed at `:181`. |
| P3-35 | CONFIRMED — STATIC | High | P3 (dup → P3-64) | `data/Preferences.kt:30`; `ui/ProfileScreen.kt:47,49` | The store accepts an empty URI but the only caller rejects a non-`content://` URI, so the remove branch is unreachable; `AsyncImage` has no error painter. |
| P3-36 | CONFIRMED — STATIC | High | P3 (dup → P3-95) | `data/Preferences.kt:12-13` vs `data/AudioSettingsStore.kt` | No injection seam; key count = **12** confirmed; no test file references `Preferences`. |
| P3-37 | CONFIRMED — STATIC (as duplication) | Medium | **recommendation** | `ui/MusicApp.kt:115-147` vs `ui/ProfileScreen.kt:97-105` | See `FALSE_POSITIVES.md` FP-7: the track-row duplication (2) and the observable drift are confirmed; there are **10** glass-bearing row/tile components, not 4; this is a refactor request, not a defect. |
| P3-38 | CONFIRMED — STATIC | High | P3 | `ui/MusicViewModel.kt:53` | `listened` is declared and never read anywhere in `ui/`; with `WhileSubscribed` and no subscriber the query never even starts. |
| P3-39 | CONFIRMED — STATIC | Medium | P3 | `ui/ProfileScreen.kt:63-65`; `ui/Design.kt:71-79`; `ui/LibraryScreen.kt:163-164` | See `FALSE_POSITIVES.md` FP-6: the "18 surfaces" figure is not reproducible (7 static `.glass(` sites, ~23 runtime instances); the nested `glass(12.dp)` inside `glass(14.dp)` and `blurRadius=22.dp` per node **are** confirmed. |
| P3-40 | CONFIRMED — STATIC | High | P3 | `ui/Design.kt:116-121` | No scheme check on the artwork URL; the desktop import copies `cover_url` verbatim (up to 8 192 chars) with no scheme check. |
| P3-41 | CONFIRMED — STATIC | High | P3 | `ui/HomeScreen.kt:29` | `LocalTime.now().hour` is evaluated during composition and nothing re-triggers it. |
| P3-42 | CONFIRMED — STATIC (2 of 3) | High | P3 | `ui/BrowseComponents.kt:10,43`; `ui/SearchScreen.kt:13,116` | See `FALSE_POSITIVES.md` FP-5: only **2** icons are fixable (`Sort` has no auto-mirrored variant and is not directional). |
| P3-43 | CONFIRMED — STATIC | High | P3 | `ui/MusicApp.kt:75` | The icon's `contentDescription` is the tab label, and the adjacent `Text(label)` repeats it. |
| P3-44 | CONFIRMED — STATIC | High | P3 | `ui/HomeScreen.kt:22`; `data/DiscoveryController.kt:19-37,69` | `RecommendationLoader.request()` is not idempotent; the engine performs up to **2** SoundCloud searches of **12 s** each when the local candidates are < 12. |
| P3-45 | CONFIRMED — STATIC | High | P3 | `android/app/src/main/res/values/styles.xml:4` | `android:windowBackground` = `#0A0E17` with no `values-night/` override. *Impact correction:* `enableEdgeToEdge()` (`ui/MainActivity.kt:37`) makes the system bars transparent, so the visible artefact is limited to the window background before the first frame. |
| P3-46 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:34,39` | The O(N) `firstOrNull` runs at 2 Hz; the mini player's copy was already hoisted to a map (`ui/MusicApp.kt:37`). |
| P3-47 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:145`; `data/LyricsData.kt:21` | `indexOfLast` per tick over up to **20 000** lines; the list is sorted, so a binary search is available. |
| P3-48 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:37-38` | `tab`/`follow` use `rememberSaveable`; `scrub` uses `remember`. |
| P3-49 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:62-63,67` | The scrub is cleared in the same frame as the async seek, so the thumb falls back to the pre-seek value until the 500 ms poll catches up. |
| P3-50 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:41`; `ui/MusicViewModel.kt:431-435` | See `FALSE_POSITIVES.md` FP-8: the core claim (unconditional `loading=true`) is confirmed; the lyrics are **restored from cache** within a frame or two, so the artefact is a spinner flash, not a refetch. |
| P3-51 | CONFIRMED — STATIC | High | P3 | `ui/MusicViewModel.kt:184` vs `core/api.py:2010-2012` | Android `(repeatMode+1)%3` → OFF→ONE→ALL; the desktop is OFF→ALL→ONE. The icon/stateDescription mapping is correct. |
| P3-52 | CONFIRMED — STATIC | High | P3 | `ui/PlayerScreen.kt:73-92`; `ui/MusicViewModel.kt:188` | No clear action; `clearQueue()` exists but has **no caller**, and `clearMediaItems()` stops playback whereas the desktop keeps the current track. |
| P3-53 | CONFIRMED — STATIC | High | P3 | `ui/LibraryScreen.kt:36,46-48,105-106`; `data/DiscoveryController.kt:62-67,71` | The header switches **synchronously** while `smartTracks` keeps the previous playlist's rows until the new inner Room flow emits. *Impact correction:* the window is one Room emission (tens of ms), not indefinite. |
| P3-54 | CONFIRMED — STATIC | High | P3 | `ui/CatalogBrowser.kt:52` vs `ui/MusicViewModel.kt:376,385` | The button prints the raw count; the import takes 500 and then de-duplicates, so at most **500 distinct** tracks are imported. |
| P3-55 | CONFIRMED — STATIC | High | P3 | `ui/LibraryScreen.kt:72`; `ui/SettingsScreen.kt:49` | The byte sum covers **all** rows next to a count of the **complete** ones — both sites. |

---

# 4. Detailed findings — P3-56…P3-110

Compact per-finding record (verifier A's full pass over the current tree).
Columns: **verdict · confidence · evidence type · original → revised severity ·
confirmed location · duplicate-of · note**.

---

| ID | Verdict | Conf. | Evidence | Sev | Confirmed location | Dup | Note |
|---|---|---|---|---|---|---|---|
| P3-56 | CONFIRMED — STATIC | High | source | P3 (latent) | `data/LibraryRepository.kt:126`; `ui/MusicViewModel.kt:450-452` | — | `require(name.isNotBlank())` → `IllegalArgumentException("Failed requirement.")` → the snackbar. Latent (the button is disabled while blank). |
| P3-57 | CONFIRMED — STATIC | High | source | P3 | `ui/CatalogBrowser.kt:22-24,62-64` | — | `CatalogBrowserState` has no `hasSearched` flag; the same hint renders for "not searched" and "searched, empty". |
| P3-58 | CONFIRMED — STATIC | High | source | P3 | `ui/AudioSettingsControls.kt:53` vs `player/AudioRuntime.kt:83` | — | The label prints the draft gain; the hardware applies `equalizerGainAt(...).coerceIn(minDb,maxDb)`. `AudioSettings.normalized()` clamps to ±12 only, never to the device range. |
| P3-59 | CONFIRMED — STATIC | High | source | P3 | `NeDotifyApp.kt:20-23` | — | A first DataStore emission slower than 1.5 s silently falls back to 256 MB; `runBlocking` blocks the caller (the main thread) for up to 1.5 s. |
| P3-60 | CONFIRMED — STATIC | High | source | P3 | `ui/AudioSettingsControls.kt:22,55-58,100,107`; `ui/MusicViewModel.kt:284` | — | The draft is keyed on the *persisted* value, so a failed write leaves the optimistic value on screen; the write result is not observable. |
| P3-61 | CONFIRMED — STATIC | High | source | P3 | `ui/ProfileScreen.kt:152`; `data/ProfileSettings.kt:13-14` | — | The dialog closes synchronously before the suspend write. The model's message is accurate but the UI never filters ISO control characters, which the model rejects. |
| P3-62 | CONFIRMED — STATIC | High | source | P3 | `ui/SettingsScreen.kt:27,49`; cadence `downloads/TrackDownloadWorker.kt:71` | — | The 750 ms progress write → 1.33 Hz → the whole `SettingsScreen` scope restarts, including the 8 sliders. *Impact correction:* "~30 composables" is an estimate; no recomposition count was ever measured. |
| P3-63 | CONFIRMED — STATIC | High | source | P3 | `ui/ProfileScreen.kt:32,39` | — | The whole `tracks` table flows into the composition to compute one integer; no aggregate query exists. |
| P3-64 | **(merged)** | — | — | — | — | **P3-35** | A pure `[MERGED]` pointer with no independent content. P3-35 itself is confirmed. |
| P3-65 | CONFIRMED — STATIC | High | source + doc | P3 (doc) | `android/PORTING_STATUS.md` vs `core/settings.py:80,146` | — | `volume_normalization`, `gapless_playback` and `personalization.pinned_track` exist desktop-side and none appears in the porting status. A documentation gap. |
| P3-66 | CONFIRMED — STATIC | High | source | **P2** | `data/ProviderConnections.kt:84-92`; `data/AuthPkce.kt:87` | **MAIN-P2-42** (identical title) | A second PKCE start overwrites `pending` with a new `state`; the first tab carries the old one → "Проверка безопасности входа не пройдена". The UI even offers "Начать заново" while pending. |
| P3-67 | CONFIRMED — STATIC | High | source | **P2** | `data/ProviderConnections.kt:96-98,106`; `ui/ConnectionsControls.kt:28` | — | The pending is cleared **only** for the exact message "Вход Spotify отменён"; a state mismatch or an expired pending leaves `spotifyPending=true`. `cancelSpotifyLogin()` has **no caller anywhere**. |
| P3-68 | CONFIRMED — STATIC | High | source | **P2** | `ui/ConnectionsControls.kt:60` | — | The confirm button clears the field **before** the save completes; the failure is only reported in `status.error`. The typed value is lost. |
| P3-69 | CONFIRMED — STATIC | High | source | P3 | `ui/ConnectionsControls.kt:28,44-45` vs `ui/BackupControls.kt:39,43,64,67` | — | No `liveRegion` in `ConnectionsControls`; `BackupControls` in the same screen uses it on both the status and the error line. `liveRegion` appears in exactly 4 places, all in `BackupControls.kt`. |
| P3-70 | CONFIRMED — STATIC (partial) | Medium | source | P3 (a11y) | `ui/ConnectionsControls.kt:57-58` | — | `Modifier.semantics { password() }` is used **nowhere** in the app. *Impact correction:* the sub-claim that the raw token stays in the semantics tree as `EditableText` is unverified and likely false for current Compose — "a screen reader reads the token aloud" is **overstated**; the field is simply not *marked* as a password. |
| P3-71 | CONFIRMED — STATIC | High | source | P3 | `data/DesktopLibraryConverter.kt:17-18`; `data/DesktopLibraryImport.kt:35` | — | The `origin` trigger is unreachable from the UI (the control caps at 80 chars and blocks blanks), but the **other** `require` on the same lines ("В копии слишком много записей") **is** reachable and is also swallowed by the catch-all. |
| P3-72 | CONFIRMED — STATIC | High | source | P3 (cosmetic) | `MainActivity.kt:135` | — | `text/plain` + `application/octet-stream` are in the MIME array. *Correction:* the "`OpenDocument` sets the type to `*/*`" sub-claim is **false for the backup picker** — the default intent type is narrowed by `EXTRA_MIME_TYPES`; the literal `*/*` array at `:141` is the *desktop-DB* picker. No security impact. |
| P3-73 | CONFIRMED — STATIC | High | source | P3 | `ui/MusicViewModel.kt:92,234,240`; `ui/BackupControls.kt:48-58` | — | `pendingBackup` holds a materialised `LibraryBackup` (up to 20 000 tracks / 100 000 sessions) for the whole preview, while the panel renders 6 integers. |
| P3-74 | CONFIRMED — STATIC | High | source | P3 | `data/BackupCodec.kt:366,125,127,164` | — | All three user-relevant categories funnel through one `invalid(reason)`; the test asserts the exception **type**, not the message. |
| P3-75 | CONFIRMED — STATIC | High | source | **P2** | `downloads/TrackDownloadWorker.kt:116`; `downloads/Downloads.kt:62`; `ui/DownloadsScreen.kt:39` | — | A failed removal writes the generic `"failed"` state, and the UI's retry for `"failed"` calls `resumeDownload` → `enqueue(track)` = a **re-download**. The orphaned files are never reclaimed. |
| P3-76 | CONFIRMED — STATIC | High | source | **P2** | `downloads/TrackDownloadWorker.kt:41,100,124-130` | — | An API-34+ foreground-start restriction is not an `IOException` and not a `SourceFailure` → the generic "Не удалось скачать трек. Повторите попытку". No branch recognises the quota. |
| P3-77 | CONFIRMED — STATIC | High | source | P2 | `NeDotifyApp.kt:22` vs `downloads/DownloadStorage.kt:23,25` | — | Two independent `StandaloneDatabaseProvider` instances → two connections to one `exoplayer_internal.db`. The `SQLITE_BUSY` **outcome** remains a hypothesis; the key namespaces are disjoint. |
| P3-78 | CONFIRMED — STATIC | High | source | **P2** | `data/LyricsCascade.kt:88,100-102` vs `data/Sources.kt:234` | **P3-29** | The cascade never sets `LyricsResult.source`; only the primary LRCLIB path sets `"LRCLIB"`. |
| P3-79 | CONFIRMED — STATIC | High | source | **P2** | `data/Sources.kt:230`; `data/LyricsData.kt:10,21,31` | overlaps **MAIN-P2-28** | `lyricsResult(result)` sits **outside** the try/catch; an oversized payload throws `IllegalArgumentException` before `fallback.invoke(...)` — the cascade is never consulted and a valid plain text is lost. |
| P3-80 | CONFIRMED — STATIC | High | source | P3 | `data/Sources.kt:208`; `data/LyricsDiskCache.kt:14-15,39` | — | The key carries no schema version and the record carries no version field, so old rules keep serving for up to 24 h. |
| P3-81 | CONFIRMED — STATIC | High | source | P3 | `data/LibraryRepository.kt:22` | — | The cache lives in `cacheDir`, which Android may purge, while the UI promises offline availability "из ограниченного кэша" without qualifying durability. |
| P3-82 | CONFIRMED — STATIC | High | config | P3 | `android/app/build.gradle` | — | Exactly **3** space-assignment Groovy usages, as claimed. |
| P3-83 | CONFIRMED — STATIC | High | config + artefacts | P3 | `android/review/VALIDATION.md:5,8,9`; `TEST_SUMMARY.json:5,289,299` | — | All three numbers are **correct**: the artefacts are stale (217 / 17 / 55) vs the real **236 / 15 / 59**. The arbiter re-measured the 15-warning breakdown and it is byte-identical to §10.2. |
| P3-84 | CONDITIONAL | Medium | config | P3 → **recommendation** | `android/app/build.gradle` (`unitTests.returnDefaultValues = true`) | — | The flag is on and `SDK_INT=0` is a *consequence* of it, not a separate stub; **0** unit tests import `android.*`, so it masks nothing today. "Five API-gated branches" is a projection about *future* tests. |
| P3-85 | CONFIRMED — STATIC | High | source | **P2 (doc)** | `android/run-emulator.ps1:18-19` | — | The APK path does not exist (`app/build/outputs` contains only `logs`), and `verify.ps1`'s default tasks produce no APK. The instruction is unfollowable. |
| P3-86 | CONFIRMED — STATIC | High | config | P3 (accepted cost) | `android/gradle.properties:4-6` | — | The flag and the stated reason are exactly as claimed. *Note:* same root cause as plan-only P3-114, with a **different measurement**. |
| P3-87 | **FALSE POSITIVE** | High | source + doc | — (close) | `android/review/REVIEW_RESOLUTION.md:14-16` vs `:66` | — | See `FALSE_POSITIVES.md` FP-15: the document is **self-consistent**; the row's premise is a misreading. The underlying "no verified-on-snapshot column" observation survives as a maintenance recommendation. |
| P3-88 | CONFIRMED — STATIC | High | artefacts | P3 (hygiene) | `android/review/FINAL_CHECKS.json` (2026-10-18 22:41) vs `TEST_SUMMARY.json` / `VALIDATION.md` (2026-10-19 07:41) | — | Verified to the minute. `FINAL_CHECKS.json` has no unit-test count. The APK ban is recorded inconsistently **inside one day**: `SOURCE_CHECKS.json` records an `apk_sha256` and `apk_previous_write_utc: 2026-10-18T11:49:00Z` (an APK *was* built that morning) while the same day's `FINAL_CHECKS.json` records `"apk_packaging_executed": false`. |
| P3-89 | CONFIRMED — STATIC | High | source | P3 (doc) | `android/verify.ps1:1-6`; `android/run-emulator.ps1:19` | — | `verify.ps1` has **no** header block: the `local.properties` rewrite, the junction creation, the env overrides and the unconditional restore are all undocumented. |
| P3-90 | CONFIRMED — STATIC (counts wrong) | High | measured | P3 | see note | — | **The contract claim is accurate; the counts are not.** Measured: 75 main files, **7 282 LOC** (6 970 non-blank); uncovered = **38 files / 4 618 LOC / 63.4 %** under the strict rule (a `<Name>Test.kt` exists) or **26 files / 2 984 LOC / 41.0 %** under a loose rule — the audit's `35 / 3 977 / 54.6 %` is **not reproducible** under either rule. The "5 of the 10 non-negotiable contracts have zero coverage" claim **is** reproduced. |
| P3-91 | CONFIRMED — STATIC | High | config + measured | P3 | `android/app/build.gradle`; repo-wide grep | **REG P2-53** | 15 files / **59** `@Test` methods (arbiter re-counted: 59), no `connectedDebugAndroidTest` in any task list, no Android CI job. The "55" is wrong. |
| P3-92 | CONFIRMED — STATIC | High | measured | P3 | `android/app/build/test-results/testDebugUnitTest/*.xml` (42 files) | — | Reproduced exactly: **236 tests, 0 failures, 0 errors, 1 skipped**. The newest XML (2026-10-19 19:05) is newer than the newest main source (09:46), so it matches the current tree. `VALIDATION.md` says 217 → understates by 19. |
| P3-93 | CONFIRMED — STATIC | High | source | P3 | `src/test/.../data/LiveProviderProbeTest.kt:16-17` | — | `assumeTrue(env=="1")` is the **only** guard; no `@Ignore`, no Gradle property. Provider failures are caught into the JSON, so the test passes even when every provider fails. |
| P3-94 | CONFIRMED — STATIC | High | source + test | P3 (flakiness) | `src/test/.../data/LyricsCascadeTest.kt:94` | — | An exact HTTP-request count is asserted under a real 2 200 ms provider budget — flaky on a loaded machine, and a provider-skipping regression produces a different count, so the test cannot distinguish the two. |
| P3-95 | CONFIRMED — STATIC | High | source + test | P3 | `src/test/.../data/ProfileSettingsTest.kt:7-13`; `data/Preferences.kt` | — | The test asserts the **contents of a constant**, not the acceptance rule. `Preferences` (the DataStore-backed class) has **no** test file; only the pure `PreferenceValues` helper is tested. |
| P3-96 | CONFIRMED — STATIC | High | source | P3 (declared) | `data/Models.kt:7-22`; `data/DesktopLibraryImport.kt:65-69`; desktop `core/database.py:37-42,158-163` | — | The Android `Track` entity has none of the 5 desktop columns and the desktop sorts by them. A **capability gap**, declared in `PORTING_STATUS.md` — not a contract violation. |
| P3-97 | CONFIRMED — STATIC | High | source | P3 (declared) | `data/ListeningReports.kt:15,86-110`; desktop `services/listening_comparison.py:6,22-24` | — | Android has `WEEK, MONTH, ALL` — **no `YEAR`**; the desktop has `week/month/year`. Android uses calendar days, the desktop rolling windows. |
| P3-98 | CONFIRMED — STATIC | High | source + test | P3 (declared) | `player/PlaybackService.kt:114-116`; `player/ListeningHistory.kt:14-20` | — | A REPEAT gives `forceNewSession = true` → a new `sessionId`; the test name confirms it ("repeat creates a new session"). The desktop's "one accumulating row" half was not independently re-measured in this pass. |
| P3-99 | **FALSE POSITIVE** | High | source | — (close) | `data/LibraryRepository.kt:55-67`; `data/Models.kt:105,115-117` | — | See `FALSE_POSITIVES.md` FP-16: the local search pages the **entire `tracks` table**, so an online track that was played or added to a playlist **is** in the library and **is** matched. The claimed trigger does not hold. |
| P3-100 | CONFIRMED — STATIC | High | source | P3 (declared) | `data/AudioSettings.kt:16,24,40` vs `core/settings.py:80-81,146`; `core/api.py:3595` | — | Android default 256 MB vs desktop 500 MB; LRU only, no age step (the desktop has `_clean_stream_cache(max_size_mb=350, max_age_hours=48)`); no loudness normalisation on Android (the EQ helper explicitly disclaims it). |
| P3-101 | CONFIRMED — STATIC | High | source | P3 (architecture) | `data/DesktopLibraryImport.kt:64-69`; `data/Models.kt:7-22` | — | **The audit's counts are exactly right**: 5 tables and 11+5+3+6+4 = **29 column names**, hand-reimplemented with no shared spec or fixture. Mostly a recommendation; the contract issue is "reads an undocumented private schema". |
| P3-102 | CONFIRMED — STATIC | High | source | P3 (architecture) | `ui/MusicViewModel.kt:82-92`; `MainActivity.kt:60` | — | 7 state holders across 3 layers confirmed (5 flows + 1 plain field + 1 Compose state). A **design opinion**, not a contract violation. |
| P3-103 | CONFIRMED — STATIC | High | source | **P2** | `ui/MusicViewModel.kt:20-22,129-142` | — | `NowPlaying` has no error dimension and `update()` never reads `player.playerError`. *Impact correction:* the error **does** reach the user as a snackbar (`Player.Listener.onPlayerError`); it just never becomes player-screen state. "never reaches the user" would be wrong. |
| P3-104 | CONFIRMED — STATIC | High | source | **P2** | `ui/MusicViewModel.kt:117-121,129-142` | — | The listener is attached and the mirror is seeded, but `update()` copies no error dimension — an error that happened before the listener existed is never surfaced. |
| P3-105 | CONFIRMED — STATIC | High | source | **P2** | `ui/MusicViewModel.kt:105` | — | `message.value = error.message` assigns a **nullable** into a `MutableStateFlow<String?>` — a `null` clears any pending message and the error is dropped. Exactly as described. |
| P3-106 | CONFIRMED — STATIC | High | source | P3 | `player/AudioRuntime.kt:51-52` | — | `close()` never resets `fading`, so `crossfadeActive` keeps its last value and the Settings screen keeps claiming a crossfade is running. |
| P3-107 | CONDITIONAL | Low-Med | source | P3 (design) | `ui/MusicViewModel.kt:174-179` | — | `toggle()` reads the **live** controller, not the mirror. A one-interval lag is possible but is Media3-internal, and the mirror does not even carry `playbackState`, so the row's proposed fix is not currently possible. A **design/robustness recommendation**. |
| P3-108 | CONFIRMED — STATIC | High | source | **P2** | `ui/MusicViewModel.kt:104-106` | — | The `MediaController.Listener` overrides **only** `onError`; `onDisconnected` is overridden nowhere in `src/**` (repo-wide grep: 0 hits). |
| P3-109 | CONFIRMED — STATIC | High | source | P3 | `player/PlaybackService.kt:127-149` | — | `session.sendError` at `:138` fires **before** the automatic recovery at `:140-149`, so the user sees a failure for a track that then plays. |
| P3-110 | CONDITIONAL | Low-Med | source | P3 (mechanism mis-described) | `player/PlaybackService.kt:60-69`; `data/LibraryRepository.kt:78`; `data/Models.kt:199-209` | — | The *disk* cache key is the resolved URL, so "the key omits the format" is not literally true. The real mechanism: the **in-memory resolution** key is `"id|quality|scope"` — quality but **no format** — and it is not invalidated when the track row's `mimeType` changes, so a re-search leaves the cached resolution on the old format until the process restarts. The *impact* is right, the attribution is wrong. |

---

# 5. False positives and overstated claims

Every entry below was tested by two independent verifiers plus the arbiter.
Where the original claim was *directionally* right but the stated mechanism or
consequence was wrong, the entry is classified as **OVERSTATED** and the
surviving kernel is stated explicitly. A claim is only called
**FALSE POSITIVE** when there is concrete evidence that the assertion as
written is wrong.

---

### FP-1 — The audit's #1 Android headline: "the `onPlayerCommandRequest` callback is never reached by `MediaController.play()`/`pause()`" and "every subsequent Play is dropped … until the user re-picks a track"

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

### FP-2 — P0-01's stated **cause**: "the de-duplication key was chosen as the *display* identity (title + artist) rather than the *recording* identity (title + artist + album + source + source_id + file path). A display-identity key is not a safe key for a destructive operation."

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

### FP-3 — P0-01's stated **causal story** for the playlist-membership loss: "each deleted track takes its **history rows** and its **playlist entries** with it" (i.e. by the foreign-key cascade).

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

### FP-4 — P3-10: "`configure()` fires the user-interaction side effects on every audio-settings change while the queue is ended" — *"Changing any audio setting can cancel an in-flight queue selection"*.

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

### FP-5 — P3-42: "Three directional icons are the non-auto-mirrored variants" (with the fix "use `Icons.AutoMirrored.*`").

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

### FP-6 — P3-39: "The Profile screen can hold **18** simultaneous glass surfaces".

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

### FP-7 — P3-37: "The track-row pattern is implemented twice and the 'glass list row' four times".

**Verdict: OVERSTATED on the second count; the row is a refactor request, not
a defect.** Confidence: **MEDIUM**. Evidence type: **static**.

The track-row duplication (2 implementations) and the observable drift (the
Profile "Топ треков" row has no overflow menu, no favourite toggle and no
now-playing highlight) are confirmed. There are **10** glass-bearing
row/tile components in `ui/`, so "four times" understates the duplication
while presenting itself as an exact count. The row is a code-organisation
request; the *observable* part is the drift.

---

### FP-8 — P3-50: "Switching to the lyrics tab discards the already-loaded lyrics and re-shows the spinner".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/PlayerScreen.kt:41` → `model.loadLyrics()` → `loadLyricsInternal(false)`
republishes `LyricsState(id, loading = true)`, which **is** the defect
claimed. But the lyrics are **not** re-downloaded: the in-memory LRU
(`data/Sources.kt:211`) or the disk cache (`data/LyricsDiskCache.kt`) restores
them within a frame or two. The observable artefact is a **spinner flash** on
every visit to the tab, not a refetch and not a loss of the text.

---

### FP-9 — P3-02: "`READ_MEDIA_AUDIO` is requested with no rationale, and after a permanent denial there is no route to Settings" — impact "*the button silently does nothing*".

**Verdict: PARTLY OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/MainActivity.kt:112-114, 124-126`: there is no rationale, no
"already asked" flag (the notification path has one at `:115`) and no
"open app settings" action — that part is right. But a message **is** shown
("Доступ к музыке не разрешён. Можно выбрать отдельные файлы"), so "the
button silently does nothing" is wrong; what is missing is the rationale, the
flag and the route to settings.

---

### FP-10 — P3-07: "Three always-on timers keep ~6 120 main-thread wake-ups per hour alive for the whole life of the service … The process can never go fully idle."

**Verdict: PARTLY OVERSTATED — the number is right.** Confidence: **HIGH**.
Evidence type: **static + arithmetic**.

720/h (5 s checkpoint) + 1 800/h (2 s autoplay) + 3 600/h (1 s deck tick) =
**6 120/h**, confirmed, and it is a *floor* (the deck tick is 200 ms during a
crossfade and 40 ms during a fade). All three loops run on
`Dispatchers.Main.immediate`. But they live in the `MediaSessionService` and
die with it (`player/PlaybackService.kt:344` `onTaskRemoved` → `stopSelf`), so
"the process can never go fully idle" is wrong.

---

### FP-11 — P3-03: "The one-shot UI message channel is a `StateFlow`, so a repeated identical message is conflated away and **never** shown".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

`ui/MusicViewModel.kt:79` is a `MutableStateFlow<String?>` and
`MutableStateFlow` conflates equal values — the mechanism is right. But
`ui/MusicApp.kt:54` resets the message to `null` only *after* `showSnackbar`
returns, so the conflation window is bounded by the snackbar's display time. A
second identical failure inside that window emits nothing; one outside it does.
"Never shown" is wrong.

---

### FP-12 — P3-16: "the desktop import writes its rows one at a time, with no batching … on the order of 420 000 individual SQLite statements".

**Verdict: OVERSTATED in the wrong direction (the true figure is larger).**
Confidence: **HIGH**. Evidence type: **arithmetic recomputation**.

At the documented caps: 20 000 tracks (one `putAll`), 2 000 playlists,
100 000 links, 100 000 history rows × **3** statements each (`putSession` =
SELECT + INSERT + UPDATE, `data/Models.kt:138-145`) and 100 smart playlists
= **≈ 422 100** statements inside one transaction. The order of magnitude is
right; the "no batching" framing understates the history path, which is
batched for tracks but not for sessions.

---

### FP-13 — P3-01: "Persistable URI grants are never released … At the platform cap `takePersistableUriPermission` throws and the user can no longer import or re-link any file — with no in-app recovery".

**Verdict: OVERSTATED.** Confidence: **HIGH**. Evidence type: **static**.

The mechanism is confirmed: 3 `takePersistableUriPermission` call sites and
**0** `releasePersistableUriPermission` call sites in the whole tree. But the
platform cap is 128 grants per app, and the resulting `SecurityException` is
**caught** and reported ("Часть файлов нельзя сохранить…",
`ui/MainActivity.kt:55, 80, 97`) — it is not a crash, and MediaStore scans
take no grants at all.

---

### FP-14 — P3-15: "Column names taken from the untrusted desktop file are interpolated into SQL unquoted" — the bound as stated.

**Verdict: CORRECT with a clarification.** Confidence: **HIGH**. Evidence
type: **static**.

The *table* names are hard-coded literals (`data/DesktopLibraryImport.kt:65-69`);
only the *column* names come from the untrusted copy's own `PRAGMA table_info`
(`:46`) and are interpolated unquoted (`:50`). The stated bound — read-only
copy, `rawQuery` compiles only the first statement, outcome is the
"Не удалось прочитать БД…" message — is accurate.

---

### FP-15 — P3-87: "`REVIEW_RESOLUTION.md` has already rotted: a row's factual premise is false in the current code" — *"The row states that the app does **not** request `POST_NOTIFICATIONS`; the current tree **does** declare the permission and requests it at runtime. The same document says so 50 lines earlier."*

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

### FP-16 — P3-99: "The Android's library search covers only device files and completed downloads; the desktop's FTS search covers the whole library" — *"A track played from an online search and added to a playlist is invisible in the Android's device/library search."*

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

### FP-17 — P3-90's counts: "35 of the 75 production files (3 977 LOC, 54.6 %) have **no** JVM test"

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

### FP-18 — REG P2-10: "Replacing the current `MediaItem` in place is reported by Media3 as a media-item *transition*, splitting one listen into two sessions and marking the first 'completed'"

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

### FP-19 — REG P2-09: "`Loader.cancelLoading()` … does **not** interrupt the executor thread"

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

### FP-20 — REG P2-11's Media3 rationale: "`SessionResult.RESULT_SUCCESS` … Media3 answers the controller at *enqueue* time"

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

### FP-21 — REG P2-07's fix-side-effect citation: "`ListeningReportsDaoTest.checkpointsAndTrackMetadataUpdateAnAlreadyCollectedReport` … explicitly asserts that a `putSession` immediately updates an already-collected report — that test would need relaxing".

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

### FP-22 — REG P2-14's citation: "the destination-side hashing (`data/LibraryRepository.kt:72-74`)".

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

### FP-23 — REG P2-12's proposed fix contradicts the repository's own contract test.

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

---

# 6. Audit inconsistencies

Each row states what the documents claim, where, the classification, and the
most likely cause. Severity here is the severity of the **documentation
defect**, not of the underlying finding.

---

### A. Two conflicting P2 id namespaces inside one document set — the most serious traceability defect

| # | Claim A | Claim B | Type | Cause |
|---|---|---|---|---|
| A1 | `FULL_PROJECT_AUDIT.md:835` — *"The complete, authoritative P2 register — P2-01 … P2-75 … is in `docs/audits/ANDROID_FINDINGS_REGISTER.md`"* | `FULL_PROJECT_AUDIT.md:833-1459` §5.1 numbers the same findings **P2-01…P2-45** with **different ids** from P2-22 onward | Duplicate id space | Incomplete merge: §5.1 was written first, the register later, and the register's renumbering was never propagated back |
| A2 | `FULL_PROJECT_AUDIT.md:172` — *"the playback position is embedded in the compared value"* (§1 item 3) | `FULL_PROJECT_AUDIT.md:1800-1811` §7.2 cites `(P2-34)` for the *NowPlaying* rebuild and `(P2-33)` for the queue key — but §5.1's P2-33/P2-34 are the **smart-rules** and **smart-playlist** findings | Cross-reference points to the wrong finding | Namespace mix: §5.1 uses the MAIN ids, §6/§7/§11 use the REG ids, in the same document |
| A3 | `FULL_PROJECT_AUDIT.md:1663-1671` §6 X-03 — *"the download path has no completeness check (P2-50) and no size ceiling (P2-30)"* | Under the MAIN namespace, §5.1 P2-30 is *"The lyrics failure taxonomy is collapsed"* | Same id, two different findings, one document | Namespace mix |
| A4 | `FULL_PROJECT_AUDIT.md:1696` §6 X-04 — *"bytes keep flowing in that window (P2-73)"* | **P2-73 does not exist in the MAIN namespace** (which ends at P2-45). Under the REG namespace P2-73 is *"The JVM suite parses JSON with a different implementation"*. Either way the reference is wrong | Dangling / wrong reference | Namespace mix |
| A5 | `FULL_PROJECT_AUDIT.md:2153` §10.1 — *"read-only WAL on API 26 (P2-25) remains a hypothesis"* | Under the MAIN namespace, §5.1 P2-25 is *"The local DB scan is given the 6.5 s network-provider budget"* | Wrong finding | Namespace mix |
| A6 | `FULL_PROJECT_AUDIT.md:2152` §10.1 — *"the 20-notification storm (P2-29)"* | Under the MAIN namespace, §5.1 P2-29 is *"The lyrics cascade is strictly serial"* | Wrong finding | Namespace mix |
| A7 | `FULL_PROJECT_AUDIT.md:1810` §7.2 — *"Standby deck rebuild (P2-27)"* | Under the MAIN namespace, §5.1 P2-27 is *"The lyrics identity gate has no base-recording fallback"* | Wrong finding | Namespace mix |
| A8 | `FULL_PROJECT_AUDIT.md:2269` §11 W2 — *"the report window bias (P2-43)"* | Under the MAIN namespace, §5.1 P2-43 is *"Local library search never matches the album column"* | Wrong finding | Namespace mix |
| A9 | `FULL_PROJECT_AUDIT.md:2154` §10.1 — *"the 59 instrumentation tests … (P2-53)"* | Under the MAIN namespace there is no P2-53 at all | Namespace mix | The MAIN namespace has 45 entries; the REG namespace has 75 |
| A10 | `FULL_PROJECT_AUDIT.md:1074-1083` §5.1 P2-11/P2-12/P2-13 | `ANDROID_FINDINGS_REGISTER.md` P2-11/P2-12/P2-13 | Duplicate entries under the same id, with (for the gate) **different conclusions** | Two documents written in parallel, never reconciled |

**Consequence for a reader.** Any "(P2-nn)" citation in §6, §7, §8, §10 or
§11 of the main report resolves to a *different* finding in §5.1 of the same
report for 8 of the 10 cross-references above. This is a **readability and
traceability failure**, and it is the mechanism by which the plan's scope line
came to say "79 P2, 114 P3" (see §E).

**Severity: HIGH.**

---

### B. Contradictory headline statistics

**ARBITER GROUND TRUTH** (measured directly by the arbiter from the build
artefacts, not from the audit documents):

| Quantity | Arbiter's measured value | Where it came from |
|---|---|---|
| Lint issues | **15** (0 errors) | `android/app/build/reports/lint-results-debug.xml` |
| Lint breakdown | `NewerVersionAvailable x6, GradleDependency x5, UseKtx x2, AndroidGradlePluginVersion x1, ExportedService x1` | same file |
| Instrumentation files | **15** | `android/app/src/androidTest` |
| Instrumentation `@Test` methods | **59** | same, counted per file |
| JVM test files | **42** | `android/app/src/test` |
| JVM tests | **236** (0 failures, 0 errors, 1 skipped) | `android/app/build/test-results/testDebugUnitTest/*.xml` (42 XML files) |
| Main Kotlin files | **75** | `android/app/src/main` |
| Production files with no JVM test | **not re-measured by the arbiter** — see P3-90 in the P3 pass | — |

| # | Claim A | Claim B | True value | Type |
|---|---|---|---|---|
| B1 | `FULL_PROJECT_AUDIT.md:108` §1 — *"Lint: **0 errors, 15 warnings**"*; `:2168` §10.2 — *"0 errors, 15 warnings"* with the breakdown `NewerVersionAvailable x6, GradleDependency x5, UseKtx x2, AndroidGradlePluginVersion x1, ExportedService x1` | `:2015-2018` §9.1 — *"LINT_ISSUES=17  Warning=17  Error=0"* with the breakdown `NewerVersionAvailable **x8**, GradleDependency x5, UseKtx x2, AndroidGradlePluginVersion x1, ExportedService x1` | **15**, with the §1/§10.2 breakdown — i.e. **§9.1 is the stale one** | Stale statistics — two runs, one narrative |
| B2 | `:2130-2133` §10.1 — *"The **59** instrumentation tests"*; `:2039` §9.1 — *"**15** instrumentation files"*; P2-53 — *"59 `@Test` methods, 0 executed"* | `:2104` §9.4 — *"The **55+** instrumentation tests"*; P3-91 — *"The **55** instrumentation tests"*; P2-55 — *"`TEST_SUMMARY.json` says **55** but the tree holds **59**"* | **59 `@Test` methods in 15 files** — the arbiter counted them per file and got exactly the audit's per-area split (Room 19, Compose 27, SAF 7, Keystore 4, Media3 2) | Stale numbers in §9.4, P3-91 and the validation artefacts |
| B3 | `:17` §1 and `:2005` §9.1 — *"**42** JVM" test files* | `:187` §2.2 and `:334` §3.2 — *"**40** JVM files (app/src/test)"* | **42** | Stale count in the architecture/coverage sections |
| B4 | `:36` §1 — *"P2 **75**"*; `:35` §1 — *"P3 **110**"* | `:379-380` §4.0 — *"P2 — MEDIUM \| **~35**"* and *"P3 — LOW \| **~30**"* | 79 / 114 **documented** | §4.0 was never updated after §5.1 was expanded |
| B5 | `:35-36` §1 | `REMEDIATION_PLAN.md:6-7` — *"Scope: 1 P0, 4 P1, **79 P2, 114 P3**, 6 cross-module findings, 10 architectural improvements"* | The plan's number is the *documented* one; the report's is the *register* one | Un-reconciled merge |
| B6 | `:2211-2220` §10.4 — *"**Six** subagents ran out of context … (AN-24 B, XI-01 B, XI-04 B, XI-06 A, **XI-09 A/B**, AN-20 B)"* | `:313-345` §3.2 lists **XI-01 … XI-08** only; there is no Android area **XI-09** | The list names **7 reviewer slots** in **6 area-pair entries** | **Two errors in one sentence**: (a) the count says six, the list covers seven slots; (b) `XI-09` does not exist in the Android area map — it exists only in the *older, desktop* `_AUDIT_AREAS.md` (`:61`, which also has XI-10). `AN-09` (Android area 09, provider auth) is the intended reference — and if it is, then **both** reviewers of AN-09 are incomplete, which would leave P1-03 ("Found by: A" in AN-09) without its stated independent reviewer |
| B7 | `:305` §3.1 — *"**Total: 70** independent review tasks (54 primary + 16 integration)"*; `:20-22` §1 — *"70 independent reviewer agents"* | `:2217-2220` §10.4 — six+ reviewers did not deliver | At most **63** completed review tasks | Incomplete delivery, not reconciled with the headline |
| B8 | `:2181-2184` §10.3 — *"the `minSdk` of all **139** cached AARs was extracted"* | `:117` §1 — same 139 | not re-measured by the arbiter | Unverified |
| B9 | `:110-111` §1 — *"File-level review coverage: **75/75** main Kotlin files mapped"* | the tree has **75** main Kotlin files | **75** ✓ | — |
| B10 | `REMEDIATION_PLAN.md:28` — the JVM suite *"covers **46 %** of the production code"* | `FULL_PROJECT_AUDIT.md:2175-2177` §10.2 — *"**54.6 %** of the production code has **no** JVM test"* (⇒ 45.4 % covered) | 45.4 % | Rounding / different denominators |
| B11 | `:2135` §10.1 — *"all **19** Room DAO and schema-migration tests"*; `:2140` — *"The **Compose UI** assertions (27 tests)"* | the arbiter's own per-file count reproduces 19 / 27 exactly | ✓ | — |

---

### C. The critical Android finding has no id, and the cross-references to it are broken

| # | Statement | Problem |
|---|---|---|
| C1 | `:51-60` §1 item 2, `:1616-1622` §6 X-01, `:2147-2149` §10.1, `:2268` §11 W1, `:1687-1689` §7, `A-2`, `REMEDIATION_PLAN.md` R1.1 | The finding is referred to as *"the XI-08 B P1"* — an **area-reviewer coordinate**, not a finding id. It is not in §4, not in the register, and has no P1 number. The report simultaneously claims 4 P1s and treats this as a 5th, higher one |
| C2 | `:1616-1617` §6 X-01 — *"its release hook (`MediaSession.Callback.onPlayerCommandRequest` with `COMMAND_PLAY_PAUSE`) is **never reached** by `MediaController.play()`/`pause()` in Media3 1.11.1 — only `setPlayWhenReady` dispatches through that path"* | **Factually wrong** (see `FALSE_POSITIVES.md` FP-1; `javap` on `media3-session-1.11.1.aar`). There is no `COMMAND_SET_PLAY_WHEN_READY` in Media3 1.11.1; `play()`/`pause()` dispatch as `COMMAND_PLAY_PAUSE` |
| C3 | `:1617` §6 X-01 — *"(P1-02 in the register, see §5)"* | **P1-02 is the DataStore-corruption finding**, and §5 contains no P1 at all. The cross-reference resolves to nothing |
| C4 | `:1083` §5.1 P2-11 — *"The second press works (it re-opens the gate via `receivedPlayCommand()`), so the gate is not permanently stuck, but the first press is silently lost"* | **Directly contradicts** §1 item 2 (`:56-58`): *"Once tripped, **every subsequent Play is dropped** … until the user re-picks a track"*. Both statements were shipped; the mechanism, when checked against the bytecode, supports the first and refutes the second |
| C5 | `:781-783` §1 item 4, `:2207` §12 | The report's #1 Android finding (item 2) and the plan's "highest-value single change" (`REMEDIATION_PLAN.md` Appendix A, item 3) rest on the refuted claim in C2 |

---

### D. Counts inside individual findings that do not survive re-measurement

| # | Row | Stated | Verified | Type |
|---|---|---|---|---|
| D1 | §2.4 theme 5 (`:252`) — *"with **26** hard-coded column names"* | 26 | 29 (per X-06 `:1724` and P3-101) | Numeric contradiction inside the report |
| D2 | §5.1 MAIN-P2-39 — *"**184 of the 193** raw `dp` literals"* vs *"(9 in `Design.kt`, **184** in the 17 screen/component files)"* | 193 total, 184 outside | 9 + 184 = 193 ✓ internally consistent, but the same row's "Repro" says `-> 193 hits, 9 in Design.kt` — the count of *screen files* (17) is not re-derivable from the report | Unverified |
| D3 | §7.1 item 10 (`:1788`) — *"The backup's 16 MB cap does not bound the heap (**P2-16, P2-30**)"* | P2-30 is the size-ceiling finding under REG, the lyrics-taxonomy finding under MAIN | Namespace mix (see A) |
| D4 | §5.1 MAIN-P2-39 — *"`Design.kt` is not a token layer: it defines no spacing scale, and **184 of the 193** raw `dp` literals live outside it"* | — | **Design-recommendation, not a contract violation** — the report itself says "the desktop has a real token layer" but never states a contract the Android side breaks | Category error (a design preference filed as a defect) |
| D5 | §7.2 (`:1801`) — *"`NowPlaying` rebuild (**P2-34**): 3 000 `Pair` allocations … **3 000 `Pair.equals`**"* | — | 3 000 allocations of 2-element `Pair`s = 6 000 `String.equals`; the "3 000 `Pair.equals`" is the data-class comparison, so both numbers are used for different things in the same sentence | Imprecision |
| D6 | §5.1 MAIN-P2-11 — *"three timers"* vs P3-07 *"720/h + 1800/h + 3600/h"* | 6 120/h | ✓ reproducible; but §5.1 MAIN-P2-11/P2-34 and the REG ids collide | See A |
| D7 | P3-86 vs plan-only P3-114 | P3-86: *"`kotlin.incremental=false` forces a full recompile … measured `:app:compileDebugKotlin :app:lintDebug` = **5 m 8 s**; a forced main-source recompile = **58 s**"* | P3-114: *"`kotlin.incremental=false` makes a **one-line** edit cost a measured **33.6 s** full-module recompile"* | Same phenomenon, two ids, two different numbers, neither reconcilable from the documents | Duplicate + numeric conflict |

---

### E. Findings that exist only in the remediation plan

`REMEDIATION_PLAN.md:6-7` states a scope of *"79 P2, 114 P3"*. The main report
and the register contain **75 P2** and **110 P3**. The difference is eight
findings that are documented **only** in the plan's R4.8 table
(`:709-727`) and that are referenced by no audit document:

* **P2-76** (no `buildTypes` / R8 / signing config; debug and release share
  the `applicationId`)
* **P2-77** (30 literal dependency coordinates, no catalog, no lockfile, no
  verification metadata; the gating lint task reaches out to Maven Central on
  every build, so *"0 errors, 15 warnings"* is *"a function of the calendar,
  not of the source"*)
* **P2-78** (KSP 2.3.12 built against Kotlin 2.3.20 while the project
  compiles with Kotlin 2.2.10; `room-compiler:2.8.5` on a two-year-old
  `symbol-processing-api`)
* **P2-79** (the SDK lives inside the system temp dir; `local.properties` is
  the only channel that says where it is, and it is globally shared)
* **P3-111** (`haze` drags Compose coordinates and pins `minCompileSdk=37`)
* **P3-112** (no Coil `ImageLoader` configured → a second, unconfigured
  `OkHttpClient` for cover art)
* **P3-113** (SDK-XML-version mismatch on every build, "incompatible with
  Gradle 10" on every build, configuration cache off, 11.5 s configuration
  phase)
* **P3-114** (`kotlin.incremental=false` → 33.6 s one-line recompile)

**Severity: HIGH** — eight findings with no source, no evidence and no
severity justification exist only as ids in a fix plan. P2-77 in particular
undermines the audit's own headline lint statistics.

Two further plan items are findings with no id at all:

* **R1.2** — the *URI-less `MediaItem`* defect, marked 🔴 **P1** in the plan
  (`:148-170`) and referenced from the main report's W1 row
  (`:2268`, *"the URI-less `MediaItem` (XI-01 A / XI-05 B)"*) but **absent from
  §4 and from the register**.
* **R2.3** (*"Export atomically"*) and **R4.4** (*"`verify.ps1` reverting a
  concurrent `local.properties`"*) are cited by **area** (`AN-07 A`,
  `AN-23 A`) rather than by finding id.

---

### F. The "instrumentation compiled but never run" claim — accurate, but counted three ways

`:2036-2042` §9.1, `:2104` §9.4, `:2130-2134` §10.1, P3-91, P2-53 and
P2-55 all assert the same core fact, which **checks out**: `verify.ps1` runs
`:app:compileDebugAndroidTestKotlin`, there is no `connectedDebugAndroidTest`
task, no Android CI job, and no device. The *counts* attached to it differ
(55 / 55+ / 59 / "15 files"), and §10.1's breakdown *"Room DAO + schema
migrations 19, Compose UI 27, SAF/files/downloads 7, Android Keystore 4,
Media3 handover 2"* sums to **59**, while §9.1's *"the **Keystore**
implementation … has 4 device tests"*, *"the **HLS VOD verifier** and the
**Media3 crossfade handover** — 2 device tests"* and *"the **Compose UI**
assertions (27 tests)"* are consistent with the same split. So the
**method** is sound and the **55** figure is the only stale number.

**Severity: MEDIUM** (stale numbers, not a wrong conclusion).

---

### G. What the audit *never* claims — verified honest

These were checked specifically, because the report's §9.4/§10.1 is its
strongest section:

* The report states plainly that **no APK was built** and that the
  instrumentation suite was **compiled, never executed** (`:2036-2047`).
* Every "measured" figure is attributed to a JVM/SQLite measurement, not to a
  device: the backup heap profile (*"measured on the JVM with the project's own
  `org.json:json:20250517`; the device heap limit was **not** measured"*,
  `:1145`), the report-window percentages (*"Transliterated into a scratch
  JDK-21 `jshell` script"*, `:1351`), the local-search timings (*"Measured on
  desktop SQLite with the same SQL"*, `:1268`).
* The recomposition figures are explicitly derived from source cadences, not
  measured (`:2155-2158`).
* The Media3 semantics are stated as bytecode-derived from the *exact pinned*
  AARs (`:2178-2192`).
* `verify.ps1`'s `--rerun-tasks` failure is reported as a **real** finding
  (`:2065-2094`) rather than hidden.

**Verdict: the report's epistemic hygiene is good.** Its defects are in
*counting*, *id space* and *one Media3 claim* — not in pretending to have
observed things it did not observe.

**Severity: — (no finding; a positive verification result).**

---

### H. Minor but citable

| # | Where | Problem |
|---|---|---|
| H1 | `:9` §1 — *"This file is a work in progress. It is finalised when the 'Audit complete' marker appears at the end."* vs `:2349` — `<!-- Audit complete -->` | The marker **is** present, so the file is final. No defect, but the two lines read as an unresolved state |
| H2 | `:1764-1767` §7.1 item 2 — the media-header gap is listed under **"Security"** although the report itself calls it *"a **correctness** gap (403 on the first byte) that happens to also be a bot-detection gap"* | Category error: a correctness finding filed as a security finding |
| H3 | `:1877` §7.1 item 7 — the lock-screen title leak is filed under an informal id *(XI-03 B, F-XI03-4)* while every other §7.1 item has a P-id | Inconsistent id scheme inside one list |
| H4 | `:1809-1810` §7.2 — *"`DownloadStorage` first touch (**P3-?** / AN-15 A)"* | A literal `P3-?` placeholder survives in the final document |
| H5 | `:1984-1986` §9 — *"All results below were **observed during this audit**, not read from a prior report."* | True for §9, but §2.3/§2.5 and §5 quote the desktop oracle as "the reference implementation" without a comparable observation statement. Minor asymmetry in the evidence standard between the Android and the desktop halves |
| H6 | `REMEDIATION_PLAN.md:118-123` R1.1 | The remediation plan **restates the refuted Media3 claim verbatim** (*"In Media3 1.11.1 that callback is never invoked for `MediaController.play()`/`pause()`"*) and its acceptance criterion ("the gate must be re-armed from a path the app actually uses") is written against a false premise. Executing the plan as written would produce a fix for a defect that does not exist, while leaving the real one (a silent veto) in place |

---

### I. Additional inconsistencies found by the dedicated document auditor

*(Independent pass over the same five documents; reproduced here because each
item is checkable and not already covered above.)*

| # | Claim A | Claim B | Type | Cause |
|---|---|---|---|---|
| I1 | `:838-841` §5.1 — *"the register carries **the two findings** that arrived after this section was written"* | the register now carries **seven** post-§5.1 findings (P2-73…P2-79) plus four P3 rows (P3-111…P3-114) and, in Addendum 3, five more (P1-05, P2-80, P2-81, P3-115, P3-116) | Stale statistic | The note was written when there were two |
| I2 | `:1590-1591` §5.2 — *"**110 P3 rows** were raised; the **21** marked **[MERGED]**"* | the §5.2 table has **114** rows (P3-01…P3-116 across three addenda) and **only 2** rows carry a `[MERGED]` marker | Stale statistics + counting error | The consolidation note was written against a previous draft and never updated |
| I3 | `:822-831` §5.0 — *"**Six** such merged findings are marked **[MERGED ×N]**"* + a 6-row table | §5.1 marks **ten** findings `[MERGED]` (P2-01…P2-06, P2-07, P2-08, P2-41, P2-43); §10.4 repeats the stale "Six" | Counting error | The §5.0 table enumerates only P2-01…P2-06 |
| I4 | `:2135-2139` §10.1 and `:70-72` §1 — *"all **19** Room DAO and schema-migration tests — the only guard on the v1→v2→v3 migration"* | 19 Room-touching tests exist; only **3** call `MigrationTestHelper.runMigrationsAndValidate` (DownloadMigrationTest 1 + SmartPlaylistMigrationTest 2) | Counting error — a 6× overstatement of the migration guard | "Room DAO **and** schema-migration" was read as "19 schema-migration tests" |
| I5 | `:2142-2143` §10.1 — *"The **HLS VOD verifier** and the Media3 crossfade handover — 2 device tests"* | a grep of `android/app/src/androidTest` for `Hls\|HOD\|Vod\|VOD` returns **0**; the 2 tests are decoder-handover tests | Unsupported claim — a test surface that does not exist | The report asserts coverage of a test that was never written. P2-53's own breakdown correctly lists only "Media3 handover 2" |
| I6 | `:253-256` §2.4 theme 5 — *"with **26** hard-coded column names"* | `:1728` §6 X-06 and `:1575` P3-101 both say **29**; measured 11+5+3+6+4 = **29** occurrences / 23 distinct | Numeric contradiction inside one document | §2.4 was written before the column set was finalised |
| I7 | `:1418` §5.1 P2-39 — *"**193** raw `dp` literals"* / *"**24** raw `Color(0x…)` literals"* | 193 is the number of **lines** containing a `dp` literal; the occurrence count is **285** (10 in `Design.kt`, 275 outside). 24 is likewise lines; the occurrence count is **43** (29 + 14). The "17 screen/component files" is **21** | Methodological mislabel — a line count presented as a literal count | `Select-String` counts matching *lines*; the row's own repro command cannot produce the number it quotes. The *conclusion* is **understated**, not overstated |
| I8 | `:264` §2.5 — *"the ~200-method bridge surface, **backup export/import**"* (`core/api.py`) | `core/api.py` has 232 `def`s and **zero** occurrences of "backup"; the whole desktop tree has no backup export/import | False statement inside the oracle description | Contradicts X-06, which the same report gets right |
| I9 | `:1754` §7.1 — *"lint's `NewApi` detector (severity error) reported **0 errors**"* | P3-84 — the `unitTests.returnDefaultValues = true` flag *"silently masks five API-gated production branches"* | Unreconciled | The two can both be true (the flag affects unit tests, not lint's `NewApi`), but §7.1's "genuinely safe" claim is made without noting P3-84 |
| I10 | `:2237-2242` §10.4 and `:2299-2300` §12 — *"The audit verified **15** of the prior round's 'Исправлено' claims … all 15 hold"* | `android/review/REVIEW_RESOLUTION.md:26-55` has **28** rows, every one marked fixed | Unverifiable statistic | A subset was checked and reported as the whole |
| I11 | `:1605-1637` §6 X-01 and `:2272` §11 W1 — the gate latch is *"the **XI-08 B P1**"* | `REMEDIATION_PLAN.md:148` R1.2 is marked 🔴 **P1** (*"Never build a queue item by hand in the UI layer"*) and is referenced from `:2272` as *"the URI-less `MediaItem` (XI-01 A / XI-05 B)"* — in **neither** §4 nor the register | Plan items with no id in any register | The plan's own scope line says "4 P1" |
| I12 | `:2114` §9.4 — *"Nothing in this report claims a test, build or measurement that was not observed."* | §9.1's lint result (17) is not in the cited file; §1/§10.1's "19 schema-migration tests"; §10.1's "HLS VOD verifier" | The report's own honesty guarantee is false in three specific places | The guarantee is honoured everywhere else — there is no fabricated device screenshot, `gfxinfo`, APK run or live-provider result |
| I13 | `:2114` §9.4 / `:2249-2251` §10.5 — the desktop was "the oracle, not the subject — with one exception: P0-01"; the Windows proxy was out of scope | `_FINDINGS_SO_FAR.md` is a **completed** desktop audit (1 P0, 10 P1s, ~35 P2s) holding *"two distinct ids that sanitise identically make the proxy serve **the wrong track's audio**"*, *"the provider OAuth token is stored in **plaintext**"*, *"the system tray never starts"*, *"two divergent SSRF policies … one **fails open**"*, and a **second P0-class migration defect** at `core/database.py:364-379` — 50 lines below the one reported | **Lost findings** — an entire earlier audit silently dropped | The desktop was treated as a pure oracle, so an earlier desktop audit's results were never carried forward; the three underscore files carry **no deprecation marker** and reuse the same `XI-nn` labels for completely different scenarios |
| I14 | `:305` §3.1 — *"**Total: 70** independent review tasks"*; `:20-22` §1 — *"70 independent reviewer agents"* | `:2221-2224` §10.4 — 7 slots did not deliver; **0** of the 70 reviewer reports are retained in the repository | Unreconciled headline + traceability break | §3.1's independence guarantee and §5.0's `[MERGED ×N]` table cannot be checked by anyone |
| I15 | `:110.5` §10.5 — *"The desktop app's own correctness"* was out of scope | `_AUDIT_CONTEXT.md:191` — *"The **entire frontend** … **No `innerHTML` sink was audited** — this is the highest-value remaining check, because a provider-supplied string reaching `innerHTML` is a stored-XSS-to-full-bridge path"* | Lost finding (the highest-value remaining check) | The new report claims to have read the JS UI "in full" for the compared areas and never mentions the unaudited `innerHTML` surface |
| I16 | `:2069-2098` §9.3 — the `--rerun-tasks` failure is *"a real finding rather than a tooling curiosity"* | the same failure class did **not** reproduce: a clean `:app:lintDebug` in an ASCII-path copy succeeded (5 m 26 s) because the KSP outputs were regenerated first | Over-claim | The failure is a task-ordering artefact, not a defect in the project |
| I17 | `:2114` §9.4 lists the desktop→Android import and the Room migration as "NOT verified" | §4 P0-01 ran a **Python reproduction against `core/database.py`'s migration** — the one thing §10.5 says was out of scope | Undeclared scope expansion | The report ran a desktop runtime reproduction without declaring it in the "NOT verified" list |
| I18 | `:1549` P3-75 / `:1540` P3-79 and §5.1 P2-42 / P2-28 | P3-66 ≡ MAIN-P2-42 (identical title *and* area) and P3-79 ≡ MAIN-P2-28 (same symptom, same fix location) | Duplicate entries counted at two severities | Only P3-25/P3-64 use the `[MERGED]` mechanism; these two pairs do not. Both the P2 and the P3 counts are inflated |
| I19 | `android/review/VALIDATION.md:5,8,9` / `TEST_SUMMARY.json` / `SNAPSHOT.json` — *"217 JVM passed"*, *"17 warnings … NewerVersionAvailable: 8"*, *"55 instrumentation tests"* | the tree: **236** JVM tests, **15** lint warnings (x6), **59** instrumentation tests | Stale artefacts (correctly reported as P3-83/P3-92) | §9.1 imports the stale numbers instead of the measured ones |
| I20 | `android/review/SOURCE_SHA256.txt` mtime 2026-10-19 **07:41:31** | `android/review/PRE_AUDIT2_SOURCE_SHA256.txt` (and its three twins) mtime **09:29:04**, byte-identical content | Naming inversion | The file named **PRE_**audit2 is **newer** than the file it duplicates — the "pre-audit" label is backwards. P2-42 notes the byte-identity but not the inversion |
| I21 | `docs/audits/independent_verification/01_INVENTORY.md` (this verification's own first draft) — *"P2-76…P2-79 and P3-111…P3-114 are documented ONLY in the remediation plan"* | they are in the register's **Addendum 2** (`ANDROID_FINDINGS_REGISTER.md:477-551`) | **Self-correction** | The inventory was written before the corpus was extended; the claim was **withdrawn** in §2b of the same file. This is a third-generation instance of the same disease — and it is the reason the corpus is now under version control in this verification's own output directory |
| I22b | The lint gate's result is treated as a property of the source | three lint runs over the **same unchanged source** gave **15** warnings (the stored report), **13** (network on) and **4** (network black-holed + the lint cache deleted) — with different "latest version" numbers in each | The gate is **not hermetic**; "15 warnings" is one of three possible answers | The `NewerVersionAvailable`/`GradleDependency` detectors query live repository metadata. The plan's mechanism ("on **every** build") is wrong — the reads are cache-backed (7-day TTL) — but the *conclusion* is now **experimentally proven** rather than asserted |
| I23 | `REMEDIATION_PLAN.md:717` — *"if it is ever dropped, it is a **one-function** change"* (P3-111) | dropping `haze` touches **two files at eight sites** (`Design.kt:28,:36,:75-77`; `MusicApp.kt:28,:52,:58,:60`) | Over-stated remediation cost | The plan's own reasoning is right (`Modifier.blur` is not a backdrop blur) but the cost is a CompositionLocal + a `HazeState` provider, not a function |
| I24 | `REMEDIATION_PLAN.md:720` — *"the measured configuration phase is **11.5 s**"* (P3-113) | measured **10.657 s cold daemon** versus **0.321–0.612 s warm** | A cold-daemon figure presented as a steady-state cost | The SDK parse and the class loading are cached in the Gradle daemon |
| I25 | `REMEDIATION_PLAN.md:714` — *"The SDK lives in `C:\Temp\nedotify-android\sdk` … `local.properties` is the only channel"* (P2-79) | the alias is **per-checkout-path** (`SHA-256(projectPath)[0..9]` = `B3544D227D`), **stable across runs**, and `verify.ps1` also exports `ANDROID_HOME`/`ANDROID_SDK_ROOT` for its own run | Imprecise | The *path* is right and the *size* (3 696.8 MiB) is exact; the "per-run alias" and "only channel" characterisations are not |
| I26 | `REMEDIATION_PLAN.md:723` — *"all 35 `.glass()` call sites route through `Modifier.glass()`"* (P3-111) | 35 is the **textual** match count; 1 is the definition and 1 is an unrelated `MusicViewModel.glass(Boolean)` ⇒ **33** real call sites | Count off by 2 | The two non-callsite matches share the name |
| I27 | `REMEDIATION_PLAN.md:717` — *"30 literal dependency coordinates"* (P2-77) | **34** (+1 `platform(...)`) | Count off by 4–5 | Hand count |
| I28 | The plan claims the R4.8 findings exist "only in the remediation plan" | eight of the nine are in the register's **Addendum 2** (`ANDROID_FINDINGS_REGISTER.md:475-558`) and are summarised in the main report (`:1687-1690`); only the **R1.2 P1** is genuinely new | The premise was false | The plan re-plans already-registered findings |
| I29 | `REMEDIATION_PLAN.md:148-170` (R1.2) — *"the damage is **permanent** for that queue slot"* | permanent **for that queue slot**, but **not** across a service restart (the restore path rebuilds the queue from the saved ids); and for `removeDownload` the reconcile *does* fire when the removed download was `complete` | Over-stated permanence | The "permanent" property holds only for `attachLocalFile`, which writes only `tracks.localUri` and triggers neither the `offline_downloads` nor the `offline`-preference reconcile |
| I22 | The audited corpus **changed while it was being audited** | `ANDROID_FINDINGS_REGISTER.md` 473 → **637** lines; `FULL_PROJECT_AUDIT.md` 2 349 → **2 451**; `REMEDIATION_PLAN.md` → **52 793** bytes, all between 19:52 and 20:33 on 2026-10-19, with `git ls-files docs/audits` → **0** | **The audited subject is a moving target** | New ids (P1-05, P2-76…P2-81, P3-111…P3-116) appeared mid-verification. This verification pins its snapshot at **2026-10-19 20:33** and records the 21 late arrivals as `CANNOT VERIFY` rather than dropping them. **Fix: put `docs/audits/` under version control.** |

---

---

# 7. Root cause map

How the original findings collapse into a much smaller number of independent
root causes. A finding is **independent** if fixing its root cause does not
fix any other root cause's findings; a finding is **derived** if it is a
symptom of another root cause.

Ids are the canonical ones (see `01_INVENTORY.md`): **REG** = the register's
P2 numbering; **MAIN** = the main report's §5.1-only records.

---

### RC-1 — The Media3 session/player boundary is observed at two different moments

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

### RC-2 — A destructive `DELETE` where a merge was required (desktop)

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

### RC-3 — The library has five writers, no delete, and playback is one of them

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

### RC-4 — The only durable session state lives in the settings file, and the compared value contains the one field that always changes

* **Root cause.** The queue snapshot is a JSON blob in the *settings*
  DataStore; `checkpointQueue()` embeds `player.currentPosition` in the value
  it compares, so the de-duplication guard can never fire.
* **Derived findings.** REG **P2-01**. Cross-module **X-02**. Architecture
  **A-1**. **P3-34** (the `queue_v1` key / payload `"version":2` mismatch and
  the missing version check on read). **P2-72** and the build-tooling family
  share the "no gate" theme but not the mechanism.
* **Independent?** Yes.

### RC-5 — The download and streaming paths have no shared identity, budget or completeness contract

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

### RC-6 — The lyrics identity gate is stricter than the desktop oracle in four independent dimensions

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

### RC-7 — Provider and transport errors are classified at the edge and thrown away at every layer above

* **Root cause.** `SourceFailure.httpCode` exists and the transport maps
  401/403/429 to distinct messages, but every consumer above collapses them
  into one counter or one `String?`.
* **Derived findings.** REG **P2-62**, **P2-58**, **P2-17** (lyrics
  availability). **P1-03** (the Yandex 401 handler — same shape: a
  classified code drives a destructive action). **P3-04**, **P3-17**,
  **P3-22**, **P3-23**, **P3-11** (message taxonomy), **P3-57** (empty-state
  taxonomy), **P3-74** (backup failure taxonomy).
* **Independent?** Yes.

### RC-8 — Long-running network work is modelled as UI-scoped work

* **Root cause.** `importCatalog()` and the search pipeline are
  `viewModelScope` coroutines that are unbounded, non-resumable, serial and
  (partly) main-thread, and they block the rest of the catalogue while they
  run.
* **Derived findings.** REG **P2-08**, **P2-60**, **P2-61**, **P2-62**,
  **P2-58**, **P2-59**, **P2-74**. MAIN-**P2-40** (the root composable
  subscribes to the progress flow). **P3-26**, **P3-27**, **P3-28**,
  **P3-44**, **P3-54**.
* **Independent?** Yes.

### RC-9 — The cross-platform format is a private, unversioned, hand-duplicated schema with unbounded memory

* **Root cause.** The desktop's private SQLite schema *is* the wire format;
  it is reimplemented by hand in Kotlin with no version marker, no golden
  fixture, no conformance test and no CI; the backup codec that transports it
  is bounded at 16 MB but not in heap.
* **Derived findings.** REG **P2-14**, **P2-15**, **P2-16**, **P2-19**,
  **P2-47**. Cross-module **X-06**. **P3-96**, **P3-97**, **P3-98**,
  **P3-99**, **P3-100**, **P3-101**, **P3-102**. Architecture **A-7**.
  MAIN-**P2-35** (no retention policy on `history`).
* **Independent?** Yes.

### RC-10 — The desktop import treats the desktop's schema as optional input, not as a contract

* **Root cause.** The importer selects only the columns that happen to exist
  and reads them with defaulting accessors; one unusable rule row aborts the
  whole import; the imported-library identity is a free-text label; the WAL
  sidecar is never read.
* **Derived findings.** REG **P2-17**, **P2-18**, **P2-19**, **P2-20**,
  **P2-21**, **P2-25**, **P2-26**. **P3-15**, **P3-16**, **P3-71**.
* **Independent?** Shares the "no versioned contract" theme with RC-9 but is
  a different mechanism (tolerance vs. duplication).

### RC-11 — The settings file is a whole-file blob rewritten on a fast cadence, and its failure mode is a silent no-op

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

### RC-12 — There is no gate

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

### RC-13 — High-frequency and whole-collection state is read at the top of the composition

* **Root cause.** Values that change at 2 Hz (position) or that are
  collections (the queue, the library) are read at the root of a composable
  and therefore invalidate the whole subtree.
* **Derived findings.** MAIN-**P2-41**. REG **P2-34**, **P2-35**.
  **P3-46**, **P3-47**, **P3-48**, **P3-49**, **P3-50**, **P3-62**,
  **P3-37**, **P3-39**.
* **Independent?** Yes.

### RC-14 — "Now playing" and playback errors have no single source of truth

* **Root cause.** Three copies of the playback state (Media3's `playerInfo`,
  the ViewModel's `NowPlaying`, `AudioRuntime.status`), the error dimension
  missing from the mirror, the listener attached too late, and no
  `onDisconnected` handling.
* **Derived findings.** **P3-103**, **P3-104**, **P3-105**, **P3-106**,
  **P3-107**, **P3-108**, **P3-109**, **P3-110**. Architecture **A-3**.
  Cross-module **X-01** (partly). REG **P2-10** (the listening-session
  boundary is re-derived from Media3's coarse transition-reason enum).
* **Independent?** Yes.

### RC-15 — The app is a manual service locator, so the orchestration layer is untestable

* **Root cause.** `NeDotifyApp` is a service locator reached by a cast; the
  helpers were extracted but the *composition* of those helpers never was.
* **Derived findings.** REG **P2-75**. **P3-36**, **P3-90**, **P3-91**,
  **P3-95**, **P3-98**. Architecture **A-5**. Cross-module **X-05** (partly).
* **Independent?** Yes.

### RC-16 — System/focus events and user interactions are conflated

* **Root cause.** `onUserInteraction` is called for `AUDIOFOCUS_LOSS_TRANSIENT`
  and for `pauseForReason` (becoming-noisy, permanent focus loss) even though
  `PlaybackFocusState` models a transient loss as "intent preserved".
* **Derived findings.** REG **P2-13**. **P3-10** (over-stated, see FP-4).
  REG **P2-12** (the same interruption cancels the pending queue set).
  **P3-12** (the desktop caps a listening tick at 15 s; Android does not).
* **Independent?** Shares the `onUserInteraction` surface with RC-1, but the
  two root causes are separable: RC-1 is *when* the gate is consulted, RC-16
  is *who* is allowed to close it.

### RC-17 — The desktop's library identity and the Android's identity model are two different systems

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

### Independent vs. derived — summary

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

---

# 8. Recommended fix order

Built **only** from findings this verification confirmed (or confirmed
conditionally). Items whose original rationale was refuted are listed
separately in §4 and must **not** be implemented as written. **No code was
changed by this verification.**

Ordering principle: fix the thing that lets everything else regress first,
then fix the things that destroy user data, then the things that break a
feature, then the surface.

---

### 0. The one decision that changes the plan

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

### 1. W0 — Make the gate real (do this first; it is cheap and it changes the economics of everything after)

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

### 2. W1 — The play path (revised from the original W1)

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

### 3. W2 — Data durability and honesty

| # | Action | Defects it removes |
|---|---|---|
| **3.1** | **Type the queue snapshot** (`data/QueueSnapshotCodec.kt`), separate the queue *identity* from the *position*, and persist the position on a slower cadence. | REG P2-01, X-02, P3-34, A-1 |
| **3.2** | **Bound the backup's heap cost** and convert `OutOfMemoryError` into a `SourceFailure`. | REG P2-16 — **RAISED to P1**: re-measured at **183 MB** of live heap (not "120 MB"), against a typical 128–192 MB per-app limit. A routine "import backup" kills the app. |
| **3.3** | **Split the encoder's and decoder's error prefixes** and decide explicitly whether the 20 000-track cap is a product limit. | REG P2-15 |
| **3.4** | **Make the report's two comparison windows the same length.** | REG P2-43, MAIN-P2-31 |
| **3.5** | **Make the desktop import's losses visible** — per-row tolerance, a column-presence check, a notice line, and a machine-specific library identity. | REG P2-17, P2-18, P2-19, P2-20, P2-21, P2-25, P2-26 |
| **3.6** | **Reconcile the cross-platform identity model** so a cross-device restore does not duplicate local tracks, and add the missing delete path for the library. | REG P2-14, P2-26, P2-31, X-05, A-7, A-9 |

---

### 4. W3 — Network and provider correctness

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

### 5. W4 — Establish the gate (run in parallel with W1–W3)

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

### 6. W5 — The remaining surface

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

### 7. Unconfirmed high-risk hypotheses — **do not implement as written**

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

### 8. Two constraints that shape the whole plan

1. **The project forbids APK builds** (`android/AGENTS.md`). Items **5.1** and
   anything that needs `assembleDebug` require a **separate, explicit user
   grant**. This verification did not request or use one, and did not run
   any `assemble*` / `bundle*` / `package*` task.
2. **`~/.nedotify/` is the user's library.** Item **1.4** and every fix in the
   backup/desktop area must be exercised against **synthetic** databases
   only, exactly as this verification did.

---

# 9. Inventory of the original findings

Built by the independent verification orchestrator, from:
- `docs/audits/FULL_PROJECT_AUDIT.md` (main report)
- `docs/audits/ANDROID_FINDINGS_REGISTER.md` (declared "authoritative" P2 register)
- `docs/audits/REMEDIATION_PLAN.md`
- `docs/audits/ANDROID_AUDIT_CONTEXT.md`, `docs/audits/ANDROID_AUDIT_AREAS.md`
- `android/PORTING_STATUS.md`, `android/AGENTS.md`

Snapshot anchor: git HEAD `76cab49107b43e8368974d31f9116f5964e821a4` (2026-10-11),
branch `fix/audit-v2`, `android/` **untracked** (0 tracked files), 220 porcelain entries.

---

### 0. THE TWO P2 NUMBERING NAMESPACES (read this first)

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

### 1. P0 / P1 (main report §4)

| ID | Title | Cited location |
|---|---|---|
| P0-01 | One-shot startup migration in the desktop app deletes tracks and cascades away listening history + playlist entries | `core/database.py:313-362` |
| P1-01 | Lyrics identity gate rejects any track whose title is "Artist - Song" | `android/.../data/LyricsCascade.kt:46-54,77-78` |
| P1-02 | A corrupt preferences file is never repaired — no setting can ever be changed again | `android/.../data/Preferences.kt:9,14`; `AudioSettingsStore.kt:10,18` |
| P1-03 | A single 401 from any Yandex API call permanently destroys the user's Yandex credential | `android/.../data/ProviderConnections.kt:187-191,203` |
| P1-04 | The shared HTTP client's 30 s `callTimeout` aborts every download whose body takes >30 s | `android/.../data/Sources.kt:22-23`; `downloads/DownloadStorage.kt:26-29`; `downloads/TrackDownloadWorker.kt:56,84-89` |

### 1b. Unnumbered / informal critical finding (must not be dropped)

| ID used by the audit | Title | Where named |
|---|---|---|
| **"XI-08 B P1"** | `PendingSelectionGate.playAllowed` is tripped by every player command but re-armed only from `MediaSession.Callback.onPlayerCommandRequest`; in Media3 1.11.1 that callback is never reached by `MediaController.play()`/`pause()`, so once tripped every subsequent Play is dropped with no error and no state change | `FULL_PROJECT_AUDIT.md:51-60`, `:1616-1622`, `:1687-1689`, `:2147-2149`, `:2268`, `:2276-2279`; `A-2`; remediation W1 |
| ARCH-1 | Resolve effective source at open time (architecture recommendation) | §8 A-4 |
| ARCH-3 | Queue snapshot format is unreachable from a JVM test | X-02 |
| F-AN-07-3 | "restoring a backup on a device that already has a same-named playlist creates a second, indistinguishable playlist" | §8 A-7 |
| F-XI03-4 | Download notification leaks the track title on the lock screen | §7.1 item 7 |
| F-XI-05-2 | `refreshQueueSources` trigger set misses `localUri` changes | §8 A-4 |

### 2. P2 — canonical REG list (75) with MAIN-only additions (13)

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

### 2b. Findings added by the audit corpus WHILE this verification was running

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

#### Addendum 2 (register `:475-551`) — now inside the register

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

#### Addendum 3 (register `:562-636`) — arrived after this verification's main pass

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

#### Other unnamed findings carried by the remediation plan

| Plan id | Description | Referenced as |
|---|---|---|
| **R1.2** | `ui/MusicViewModel.kt` hand-builds a `MediaItem` with **no URI and no metadata** (`MediaItem.Builder().setMediaId(id).build()`) in `removeDownload` and `attachLocalFile`; Media3 1.11.1's `MediaSession.Callback` has no `onReplaceMediaItems`, so the item reaches the player as-is and `DefaultMediaSourceFactory.createMediaSource` hits `Preconditions.checkNotNull(mediaItem.localConfiguration)` → NPE; and `attachLocalFile` changes neither the offline flag nor the `offline_downloads` table, so the queue item is never rebuilt — the damage is permanent for that slot | `REMEDIATION_PLAN.md:148-170`; `FULL_PROJECT_AUDIT.md:2268`; marked 🔴 P1 in the plan but **absent from the P0/P1 register** |
| **R2.3** | "Export atomically" | `REMEDIATION_PLAN.md:291`; cited as "AN-07 A" (an area, not a finding id) |
| **R4.4** | `verify.ps1` reverts a concurrently modified `android/local.properties` | `REMEDIATION_PLAN.md:638`; cited as "AN-23 A" |
| **R1.1** | Restates the (refuted) `PendingSelectionGate` Media3 claim; its "done when" acceptance criterion is built on it | `REMEDIATION_PLAN.md:110-146` |

### 3. P3 — 114 rows, exactly P3-01 … P3-116 (see §2b for the numbering note)

`FULL_PROJECT_AUDIT.md:1473-1584`. 110 table rows, no duplicate ids, no gaps.
21 rows are marked `[MERGED]` with a pointer to a P2 row.

### 4. Cross-module findings (§6) — 6

| ID | Title |
|---|---|
| X-01 | Two playback states, three "is this still current?" mechanisms, four "generation" counters |
| X-02 | The queue snapshot is the app's only durable session state, and it is written into the settings file |
| X-03 | The offline download store and the streaming store are two mechanisms for the same concept |
| X-04 | The app has no single definition of "offline" |
| X-05 | The user's library has no single writer, and three of its writers can silently change its meaning |
| X-06 | The desktop's storage schema is the de-facto wire format, and it has no version |

### 5. Architecture improvements (§8) — 10 (recommendations, not defects)

A-1 … A-10 (queue-snapshot codec · intent token · now-playing source of truth ·
resolve-at-open-time · substitutable dependency graph · offline/preferences
authority · one identity policy · typed download state machine · "no silent
state loss" invariant · retire the SHA-manifest mechanism).

### 6. Original counts vs. re-counted counts

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

---

# 10. Method and limitations

**Verifier role:** Principal Software Engineer / Independent Software Auditor /
Senior Android Engineer / Security Researcher / QA Architect.
**Subject:** the original audit set in `docs/audits/` — principally
`FULL_PROJECT_AUDIT.md` and `ANDROID_FINDINGS_REGISTER.md`, which audit the
`android/` Kotlin port and use the Windows Python desktop app as a parity
oracle.
**Mode:** read-only verification + documentation. **No production code was
modified.**

---

### 0. Snapshot anchor

| Item | Value |
|---|---|
| Git HEAD | `76cab49107b43e8368974d31f9116f5964e821a4` (2026-10-11 19:42:58 +0300) |
| Branch | `fix/audit-v2` |
| `git ls-files android` | **0** — the audited tree is untracked in git |
| `git status --porcelain` | 220 entries (M / D / ??) |
| Main Kotlin files | 75 (`android/app/src/main/java/ru/nedotify/app`) |
| JVM test files | 42 (`app/src/test`) |
| Instrumentation test files | 15 (`app/src/androidTest`) |
| Newest source mtime | 2026-10-19 09:46 (the 27 files the original audit already flagged as post-manifest) |

The original audit is dated 2026-10-19 and already describes the 09:38–09:46
mtimes, so **the current tree is the tree the audit examined**. Findings are
therefore reproducible against the current code; nothing is "fixed later".

**Guardrails honoured:** the Android project forbids APK builds
(`android/AGENTS.md`) — no `assemble*` / `bundle*` / `package*` task was run and
no `connectedDebugAndroidTest` (no device). `~/.nedotify/` was never opened,
read, copied or mutated. All database work used throwaway files under
`C:\Users\<user>\AppData\Local\Temp\opencode\`.

### 1. Method

0. **Pin the corpus first — and keep watching it.** `git ls-files docs/audits`
   is **0**: the audited documents are not version-controlled, and they
   **changed while this verification was running** (register 473 → 637 lines,
   main report 2 349 → 2 451 lines, plan → 52 793 bytes, all between 19:52
   and 20:33 on 2026-10-19). New findings (P1-05, P2-76…P2-81,
   P3-111…P3-116) arrived mid-flight. This verification therefore records
   its anchor explicitly (**2026-10-19 20:33**), lists the late arrivals
   separately in `01_INVENTORY.md` §2b, and marks them `CANNOT VERIFY` rather
   than silently dropping them or pretending to have checked them.
1. **Inventory before verification.** Every original claim was extracted with
   its id, title, priority, cited location, claimed mechanism, claimed
   evidence and inter-finding links, into `01_INVENTORY.md`. The inventory
   established that the audit contains **two conflicting P2 id namespaces**
   (register vs. main-report) and that several findings carry informal ids
   (`XI-08 B P1`, `F-AN-07-3`, `F-XI03-4`, `F-XI-05-2`, `ARCH-1`, `ARCH-3`).
   No id was discarded.
2. **Two independent verifiers per finding.**
   * **Verifier A (code & runtime)** — locates the cited code, traces the real
     call chain, checks reachability, and executes a reproduction where it is
     safely possible (JVM scratch programs, synthetic SQLite databases,
     `javap` on the *exact pinned* AARs in the Gradle cache).
   * **Verifier B (adversarial)** — is given the same claim as a hypothesis and
     is explicitly instructed to **refute** it: to look for defensive code in
     another module, alternative branches, deliberate product decisions, and
     to attack the audit's stated *causal story* as well as its mechanism.
     Verifier B never sees Verifier A's output.
3. **Arbiter (this session).** Where A and B disagree, the arbiter re-derives
   the disputed fact from the artefacts — in this case overwhelmingly by
   `javap` on the pinned Media3 / DataStore / OkHttp artifacts in the local
   Gradle cache, and by executing independent reproductions. The arbiter does
   not resolve disputes by counting agreeing agents.
4. **Verdict taxonomy** (exactly one per id): `CONFIRMED — RUNTIME`,
   `CONFIRMED — STATIC`, `CONDITIONAL`, `NOT REPRODUCED`, `FALSE POSITIVE`,
   `FIXED / OBSOLETE`, `CANNOT VERIFY`. `NOT REPRODUCED` is never used as a
   synonym for `FALSE POSITIVE`.
5. **Evidence discipline.** Every verdict names its evidence type
   (runtime / test / static / bytecode / documentation). Claims that could not
   be executed (no device, no APK) are marked as such and are never presented
   as observed behaviour.

### 2. What the arbiter verified first-hand (not delegated)

* **Media3 1.11.1 command dispatch** (`javap` on
  `media3-session-1.11.1.aar` + `media3-common-1.11.1.aar`):
  `Player.COMMAND_PLAY_PAUSE = 1`; `MediaSessionStub.setPlayWhenReady` pushes
  `iconst_1`; `MediaControllerImplBase.setPlayWhenReady` dispatches a remote
  task with `COMMAND_PLAY_PAUSE`; `queueSessionTaskWithPlayerCommand` calls
  `MediaSessionImpl.onPlayerCommandRequestOnHandler(controllerInfo, 1)` which
  invokes `MediaSession.Callback.onPlayerCommandRequest`. This is the pivot
  of the audit's headline claim and is settled by bytecode.
* **DataStore 1.2.0 corruption handling** (`javap` on
  `datastore-core-android-1.2.0.aar`): `DataStoreFactory.create` substitutes
  `NoOpCorruptionHandler` for a null handler; `handleCorruption` rethrows;
  `CorruptionException extends java.io.IOException`;
  `DataStoreImpl$handleUpdate$2$1` re-throws the cached `ReadException` on the
  write path.
* **OkHttpDataSource 1.11.1** (`javap` on `media3-datasource-okhttp-1.11.1.aar`):
  `open()` → `callFactory.newCall(request)` → `executeCall(call)` — a blocking
  `Call.execute()`, so the shared client's `callTimeout` also bounds the
  *streaming* body read, not only the download.
* **The desktop `dup cleanup` migration** (`core/database.py:313-362`),
  reproduced twice in throwaway databases, including a test in which the
  statements are extracted *verbatim from the source file* so the reproduction
  cannot drift from the shipped code.
* **The desktop's own track identity rule** (`core/database.py:530-544`) and
  the git history that ties it to the migration (both introduced in commit
  `b6a6553`, 2026-08-12).

### 3. Artifacts produced

| File | Content |
|---|---|
| `01_INVENTORY.md` | the complete re-count of the original findings, the two-id-namespace map, and the informal ids |
| `VERIFICATION_SUMMARY.md` | aggregate reliability of the original audit |
| `VERIFIED_FINDINGS.md` | per-finding verification record |
| `FALSE_POSITIVES.md` | every refuted claim, with the code that refutes it |
| `ROOT_CAUSE_MAP.md` | findings grouped by shared root cause |
| `AUDIT_INCONSISTENCIES.md` | internal contradictions of the original report set |
| `VERIFICATION_MATRIX.csv` | machine-readable register of every original id |
| `RECOMMENDED_FIX_ORDER.md` | fix order built only from confirmed/conditional findings |

---

# 11. Verification matrix

All 233 original records with the verdict reached by the independent verification. The same data is available machine-readable in `VERIFICATION_MATRIX.csv`.

| original_id | orig | final verdict | revised | conf | evidence | note |
|---|---|---|---|---|---|---|
| `P0-01` | P0 | **CONFIRMED-RUNTIME** | P1 | HIGH | runtime+static+git | Desktop dup-cleanup migration destroys tracks+history+playlist rows; CONFIRMED, but the stated cause (wrong identity key) and the playlist causal story (FK cascade) are REFUTED; a SURVIVING track can also lose its playlist entry. FP-2, FP-3 |
| `P1-01` | P1 | **CONDITIONAL** | P2 | HIGH | runtime(live providers)+static | ARBITER VERDICT AFTER BOTH VERIFIERS. Verifier A (runtime, real LyricsIdentity) and Verifier B (live LRCLIB/NetEase/QQ/Genius + InnerTube probes) agree the rule is absent but the trigger is far narrower than claimed. LIVE PROOF that the app USUALLY FINDS the lyrics: LRCLIB /api/get?track_name='Rick Astley - Never Gonna Give You Up' -> HTTP 200 trackName='Rick Astley  Never Gonna Give You Up' -- the provider ECHOES the prefixed form, so similar() returns true at left==right and the candidate is ACCEPTED. The primary path is /api/get (data/Sources.kt:219), NOT the cascade's /api/search. The defect is confirmed only for (a) non-Latin scripts ('Земфира - Искала' -> Android finds nothing, the desktop's real services/lyrics_service.py finds it) and (b) the sentinel-artist SAF import (artist='Неизвестный исполнитель' -> the query 404s / returns 0 items, so the root cause is the sentinel in the query, not the gate). The audit's YouTube trigger is REFUTED by a live InnerTube probe: music.youtube.com returns a BARE title ('Never Gonna Give You Up'), not 'Artist - Song (Official Video)'. The desktop citation services/lyrics_service.py:220-224 is DEAD CODE. NEW FINDING from verifier B: the Android gate is stricter than the desktop in BOTH directions -- it also rejects a provider's full 'Artist - Song' offer when the wanted title is bare. 'Every candidate from all four providers is rejected' is contradicted for 3 of 6 tested shapes |
| `P1-02` | P1 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime+bytecode+static | ARBITER ARBITRATION OF A THREE-WAY SEVERITY DISPUTE (A said P2, B said P3, the arbiter's first pass said P1). SETTLED AT P2. Reasoning: the size of the fix is a PRIORITY input, not a severity input; the impact is 'the user's settings revert to defaults and every write fails permanently, with no in-app recovery', which is squarely 'a real defect with a user-visible consequence' (P2), and the trigger is EXTERNAL -- DataStore writes are atomic (android.util.AtomicFile on Android, okio atomicMove on the JVM), so the app CANNOT produce the corruption itself; the audit's 'interrupted write' trigger is not producible. MECHANISM CORRECTED by verifier B: the write path is a RE-READ + RE-THROW (DataStoreImpl.readAndInit is a RunOnce that re-runs doRun() after a failure), not a 'cached read failure' replay -- the outcome is identical (every edit fails forever, the corrupt file is never rewritten) but the audit's description of DataStore's internals was wrong. VERIFIER A's EXECUTED probe against the shipped 1.2.0 artefacts confirms: read swallowed, 3/3 edits throw CorruptionException, the file is byte-identical afterwards, and a FRESH store over the same file fails to read AND to write. Additional permanent losses: the saved queue (Preferences.queue() -> '') and libraryId() (throws -> backup export/import break); the 5s checkpoint fails silently (NeDotifyApp.kt:27 catches IOException with a Log.e only). Contrast: the secure store DOES have a recovery path (ProviderConnections.load().recover() removes the key and tells the user to reconnect); the DataStore path has none. The user sees the settings REVERT, which is not 'looks healthy' |
| `P1-03` | P1 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime+static | ARBITER VERDICT AFTER BOTH VERIFIERS. The DEFECT survives; the audit's two absolute assertions do not. Verifier A executed it: one Yandex 401 on GET or POST removes yandex_token and yandex_user from the secure store and disconnects the UI, in ONE request, with NO retry and NO refresh. Verifier B's three refutations are upheld: (1) the delete is GUARDED by yandexGeneration==access.generation && yandexToken==access.value, so a STALE 401 arriving after the user re-pasted a token cannot destroy the newer credential -- so 'unconditionally' is FALSE; (2) a recovery path DOES exist -- ConnectionsControls.kt:42 renders a 'Подключить' button whenever !status.yandexConnected, and the editor calls saveYandexToken (ProviderConnections.kt:107-118) which validates against account/status -- so 'no recovery path' is FALSE (the token VALUE is unrecoverable, the ACCOUNT is re-connectable in one dialog); (3) the audit's 'clears the token and retries once' is the SPOTIFY branch (:179-186) -- Yandex never retries, so Yandex behaves WORSE than described, but the description was of the wrong provider. Desktop contrast refined: the desktop keeps a dead token and keeps failing the same call, so the difference is 'proactively discards' vs 'keeps failing'. The remaining defect: the app wipes a user-supplied credential without asking, and with no re-auth prompt at the point of failure. One verifier judged the WORDED claim a false positive; the arbiter records that judgement and does not adopt it, because the destructive behaviour is real and was reproduced at runtime |
| `P1-04` | P1 | **CONFIRMED-RUNTIME** | P1 | HIGH | runtime+bytecode+static | ARBITER VERDICT AFTER BOTH VERIFIERS. Severity HELD AT P1 (verifier A said P1, verifier B said P2). Runtime-proven by both: a body still progressing at the deadline is aborted with InterruptedIOException('timeout') in BOTH the sync and the async path, and the control (callTimeout=0) completes. The retry classification and the final text are exactly as claimed (4 attempts, 'Соединение прервано. Загрузку можно продолжить'). SCOPE UPGRADE (both verifiers): the 30s cap also governs STREAMING PLAYBACK -- player/PlaybackService.kt:55 uses the same client and Media3's OkHttpDataSource.executeCall uses call.enqueue + the same call's body read, so the first play of a track whose audio is not fully received within 30s fails mid-playback. The affected provider set is LARGER than the audit says: Yandex is progressive too (CatalogProviders.kt:111, audio/mpeg) and was omitted. TWO CORRECTIONS that soften the DOWNLOAD half: each attempt gets a fresh 30s window and RESUMES from the committed cache span, so the effective budget is ~4 x 30s, not 30s total, and the practical threshold is size/120s rather than size/30s. The streaming half is NOT softened by the resume budget. Practical impact: a 3-minute 320kbps track is 7.2MB and needs only ~1.1Mbit/s average to fit in one window, so 'every real track' is not supported. Flagged as a P0 CANDIDATE pending an on-device playback check |
| `XI-08B-P1` | P1 | **FALSE-POSITIVE** | P3 | HIGH | bytecode | The audit's central Media3 claim is refuted: MediaController.play()/pause() DO reach onPlayerCommandRequest, as COMMAND_PLAY_PAUSE. The gate is not stuck. Only a silent veto survives. FP-1 |
| `REG-P2-01` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+executed | CONFIRMED. Bytecode on the pinned datastore-preferences-core-android-1.2.0: PreferencesSerializer.writeTo builds a FRESH PreferenceMap and writes the ENTIRE protobuf - a whole-file rewrite, not a partial update. CORRECTIONS: (a) the WRITE is NOT on the main thread - the queueWrites consumer runs on ioScope (NeDotifyApp.kt:24-31); only the JSON build + string compare are on the main thread, and the main report's perf table ('the rewrite is on the main thread') is FALSE; (b) the CONFLATED channel (mentioned nowhere in the register) collapses bursts of seeks but does not change the ~12 writes/min steady state; (c) the register's own numbers are internally inconsistent - 60 KB/min x 60 = 3.5 MB/hour, not 18. Executed recomputation: n=200 -> 4 766 B/snapshot = 3.27 MB/hour; n=1000 -> 23 766 B = 16.32 MB/hour; n=3000 -> 73 266 B = 50.31 MB/hour - so the register UNDERSTATES the 3000-track worst case by ~2.8x, and the main report's own perf table gives a THIRD number (~135 KB, ~27 KB/s, ~100 MB/hour) for the same finding |
| `REG-P2-02` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+source | CONFIRMED in full. Bytecode settles a DOCUMENT CONFLICT in the register's favour: androidx.media3.datasource.cache.SimpleCache's constructor starts an init thread and calls ConditionVariable.block() - it DOES block the caller for the whole cache-index initialisation, so the main report's P2-02 note (which implies it does not) is WRONG. The service is really created at cold start: MediaControllerImplBase.requestConnectToService() calls Context.bindService with flags 4097 (BIND_AUTO_CREATE\|BIND_IMPORTANT) on API>=29, and MusicViewModel.init builds the controller at Activity creation, so the by lazy initializer runs inside Service.onCreate on the main thread |
| `REG-P2-03` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+existing-test | CONFIRMED. Both losses verified: readOAuth nulls intent.data unconditionally (the local uri is captured first, so only the re-deliverable copy is destroyed), and store.remove('spotify_pending') precedes the token POST; the 10-minute expiry is real (ProviderConnections.kt:49) and a retry is impossible (the verifier is gone). NEW FINDING not in the register: the exchange runs in viewModelScope (MusicViewModel.kt:299), so ordinary Activity teardown cancels it and the login is lost SILENTLY - ProviderConnectionsTest.kt:162-172 already pins that path. The register lists only process kill |
| `REG-P2-04` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode | CONFIRMED, with the exact trust predicate derived from MediaSessionManager$MediaSessionManagerImpl.isTrustedForMediaControl: TRUE iff uid==1000 (system) or uid==Process.myUid() or the package holds STATUS_BAR_SERVICE or MEDIA_CONTENT_CONTROL or the package appears in Settings.Secure.enabled_notification_listeners. The uid substitution below API 28 applies to the uid comparison only. DEFAULT_PLAYER_COMMANDS = addAllCommands() = read+write, including COMMAND_SET_MEDIA_ITEM (31) and COMMAND_CHANGE_MEDIA_ITEMS (20). TERMINOLOGY FIX: Media3 1.11.1 has NO COMMAND_ADD_MEDIA_ITEMS constant. controller.packageName is not spoofable (SessionUtil.checkPackageValidity against PackageManager.getPackagesForUid). ADDITION: MediaSession.Callback in 1.11.1 has NO onReplaceMediaItems, so a replace goes through remove+add and is ALSO rebuilt from the DB - no URI-injection path there either |
| `REG-P2-05` | P2 | **CONDITIONAL** | P2 | HIGH | source+bytecode | REFINED: the lock IS held across HTTP in two places - action{} (ProviderConnections.kt:62-74, wrapping handleSpotifyRedirect and saveYandexToken) and spotifyAccess() (:126-140, across the refresh POST). BUT the CATALOGUE PATH DOES NOT HOLD IT ACROSS ITS HTTP: get() takes the lock only to read the credential (:170-173) and issues the request OUTSIDE it (:177). So a slow SPOTIFY REFRESH stalls everything (up to the 30s callTimeout), while a slow YANDEX catalogue read does NOT stall Spotify. The register's 'the same mutex is required by get(), postYandex(), spotifyAccess() and yandexScope() for every catalogue read' is literally true (they acquire it) but implies they hold it across I/O, which they do not. The Settings panel is enabled=!status.busy, and busy is set only inside action{} - so a background token refresh does NOT disable the panel while the mutex is held |
| `REG-P2-06` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | CONFIRMED. Exactly one non-switch writer of autoplay (MusicViewModel.kt:292); the switch is the only writer of false; the key is the global booleanPreferencesKey('autoplay') in the nedotify_audio DataStore, and PlaybackService.kt:191-195 gates the global 2s autoplay loop on it. TRIGGER CORRECTION: the write at :292 comes AFTER the empty-queue guard (:291) and BEFORE playSelected (:293) - so the flag is NOT flipped when the candidate set is empty, and IS flipped when the queue is non-empty but the subsequent playback fails. The register's 'it persists even when the Flow fails to start' is true for a PLAYBACK failure, false for an empty candidate set |
| `REG-P2-07` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+executed | CONFIRMED. The 60s clock IS inside an inner flatMapLatest (MusicViewModel.kt:68-74), re-subscribing the Room query every tick; observeReportChanges is @RawQuery(observedEntities=[ListeningSession,Track]) and the history table IS ListeningSession (Models.kt:37-39); the flow is stateIn(WhileSubscribed(5000)) and ProfileScreen collects it, so it is active exactly while the Profile tab is composed. 365 CASE arms and 731 bound arguments CONFIRMED. COUNTING CORRECTION: in ALL mode exactly FIVE queries execute (the previous-window totals query is skipped because previousStartInclusive==null); four of those five scan the whole history table (reportDays is bounded to 365 days). The ~13.3M comparison figure is per query pass, so four full-scan passes is ~53M per refresh. CORRECTION to an earlier note in this register: ListeningReportsDaoTest DOES exist - in androidTest/, not test/ - so it is device-only and was never executed, but it is not a dangling citation |
| `REG-P2-08` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+bytecode | CONFIRMED. THE CAP IS 500 ITEMS, NOT 1000: MusicViewModel.kt:376 take(500), and the user-facing message at :389 says 'Обработаны первые 500 записей'. 1000 is the worst-case number of PROVIDER SEARCHES (500 items x 2 searchers), not items - the register's TITLE is wrong, its body right. Worst case 500 x 20s = 10 000 s = 2 h 46 min 40 s. The SoundCloud parse IS on the main thread (MusicNetwork.get resumes the coroutine in the caller's Main.immediate context and the JSONObject parse + collection walk happen there) while the YouTube path uses withContext(IO) - the asymmetry is real. REFINEMENT: a cancel path DOES exist (dismissing the catalogue calls dismissCatalog -> catalogImportJob.cancel, and offline(true) also cancels) - what is missing is an explicit 'Отмена' control and any indication that closing aborts, so 'no cancel affordance' is too absolute. No provider-response cache (the desktop has 300s / 300 entries) |
| `REG-P2-09` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode | CONFIRMED with a class-path correction: in Media3 1.11.1 the class is androidx.media3.exoplayer.upstream.Loader - androidx.media3.datasource.Loader no longer exists in the AAR, so the register's citation is stale. ResolvingDataSource.open() really calls the resolver INLINE (no hand-off). The 15s sourceDeadline is real (LibraryRepository.kt:76, SourceDeadline.kt:9-11). The StreamCache single-flight slot does stay occupied: StreamCache.get registers inflight[id] and removes it only in the task's finally, and the task lives on the app-owned resolverScope, so a caller-side cancellation does not release it. ADDITION: Media3's Loader uses a SINGLE-THREADED executor, so the parked thread blocks that period's whole loader queue, not just one call. REFINEMENT: the resolution is not unabandonable - repository.invalidate(id)/streams.cancelAll() cancel the StreamCache task and the runBlocking resumes with a CancellationException; what Media3's cancelLoading() cannot do is abandon it |
| `REG-P2-10` | P2 | **FALSE-POSITIVE** | P3 | HIGH | bytecode | REFUTED, and the register has the POLARITY BACKWARDS. The full evaluateMediaItemTransitionReason predicate is: if (positionDiscontinuity && reason==0) -> AUTO; else if (positionDiscontinuity && reason==1) -> SEEK; else if (timelineChanged) -> PLAYLIST_CHANGED. The replace path calls updatePlaybackInfo(..., TIMELINE_CHANGE_REASON_PLAYLIST_CHANGED, Y=periodUid changed, reason=4=DISCONTINUITY_REASON_REMOVE, ...) - reason 4 matches neither AUTO nor SEEK, so the branch taken is PLAYLIST_CHANGED. The register's 'it is emitted only when the player was NOT playing' is the exact inverse of the truth. Consequently the app computes completedPrevious=false and forceNewSession=false, the ListeningHistory contract branch IS reached, and the session is KEPT and NOT marked completed. The repo's own green ListeningHistoryTest ('same recording source replacement keeps one measured session but explicit replay starts another') pins this, and the main report's own P3-05 agrees with it. The post-replace player.seekTo adds no second transition (BasePlayer.seekTo passes isRepeatingCurrentItem=false, and the SEEK branch requires it true). ONLY the stale explicitQueueBoundary flag survives - already filed separately as P3-05 |
| `REG-P2-11` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+existing-test | CONFIRMED: the refusal is silent - handleSetPlayWhenReady returns Futures.immediateVoidFuture() BEFORE invalidateState() and with no session.sendError, and onPlayerCommandRequest returns RESULT_SUCCESS unconditionally, so the controller is told 'success' and the UI shows no change. PRECISE TRIGGER (refined): the first press is lost IFF the interruption lands between (i) Media3 calling onPlayerCommandRequest(COMMAND_PLAY_PAUSE) - at which point receivedPlayCommand() sets playAllowed=true - and (ii) the controller's command queue being flushed, which happens only when the in-flight onSetMediaItems request set completes. That window is the WHOLE QUEUE-RESOLUTION WINDOW (a Room read of the selected ids: a few ms for a small queue, tens of ms for a 3000-item one), NOT a sub-millisecond race. The decisive fact is that the command is QUEUED, not executed inline (ConnectedControllersManager.addToCommandQueue always does Deque.add). The second press recovers. The repo's own green PendingSelectionGateTest pins the interleaving |
| `REG-P2-12` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode | CONFIRMED in full: Util.transformFutureAsync's lambda cancels the output on a CancellationException, and Util.postOrRunWithCompletion's lambda returns early when the future isCancelled - so the skipped runnable is MediaSessionStub.lambda$handleMediaItemsWithStartPositionWhenReady$7, the ONLY caller of MediaItemsWithStartPositionPlayerTask.run -> player.setMediaItems is never called. No SessionError is sent, because resolveFuture catches CancellationException BEFORE the generic catch(error:Exception) that carries the sendError. The window is one Room round-trip per 900 ids. The desktop differs in KIND, not bug-for-bug: its queue lives in audio/queue.py behind a threading.RLock and playback is a direct in-process call, so there is no session-callback future to cancel |
| `REG-P2-13` | P2 | **CONDITIONAL** | P3 | HIGH | static | REFINED, severity lowered to P3. The callback wiring is confirmed (DualDeckPlayer.kt:250 AUDIOFOCUS_LOSS_TRANSIENT -> onUserInteraction; PlaybackFocusState.kt:15 transientLoss keeps requested=true). BUT THE STATED STARTUP IMPACT IS UNREACHABLE: at app start the app holds NO AUDIO FOCUS - focus is requested only inside handleSetPlayWhenReady - so no AUDIOFOCUS_LOSS_TRANSIENT callback can arrive while the restore job is running. The path to 'the app opens with an empty queue' is a USER PRESS inside the restore window, not a focus loss. The transient focus loss is one of several interchangeable triggers and the only one that can arrive WHILE ALREADY PLAYING - where it then cancels the pending SET (P2-12), not the restore |
| `REG-P2-14` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | CONFIRMED. Two REFINEMENTS: (a) the placeholder is not forever unplayable - the track menu offers 'Указать файл' (selectLocalFile -> attachLocal), so the user can attach the file to the placeholder and make the restored playlists playable; what remains unrecoverable is the DUPLICATE ROW itself, not the playback. The register's 'the only recovery is clearing app data' is too strong. (b) THE DEFECT IS NOT ANDROID-SPECIFIC: the desktop import has the same problem, because DesktopLibraryConverter:33 turns a desktop local row into local:desktop:<nativeId>, which BackupCodec.encode salts with the desktop's label-derived libraryId, so the Android destination cannot match it against its own local:<mediaStoreId> rows either. This is a cross-platform identity-model defect |
| `REG-P2-15` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+existing-test | CONFIRMED; the caps and the line citation are exact. Two NUANCES: the pinning test asserts the REJECTION, not the WORDING - no test constrains the read-side prefix, so the wording defect is unconstrained. And the cap that will bite FIRST is MAX_SESSIONS=100 000 (one row per listening session at ~3 min each is ~7 months of continuous listening) - which is the same root cause as the main report's own 'no retention policy' finding (MAIN-P2-35) |
| `REG-P2-16` | P2 | **CONFIRMED-RUNTIME** | P1 | HIGH | runtime+bytecode | RE-MEASURED BY A SECOND INDEPENDENT VERIFIER: the real requirement is HIGHER than the register states. Measured with the project's own org.json:json:20250517 jar, JDK 21, a document inside the codec's own caps (20 000 tracks + 2 000 playlists + 80 000 links + 67 000 sessions = 16 651 260 B): heap after BAOS 33.1 MB -> after toByteArray() 49.1 -> after CharsetDecoder.decode 81.1 -> after toString() 97.1 -> after the JSONObject DOM 183.3 MB, with the DOM ALONE at 86.2 MB. -Xmx160m OOMs inside org.json.JSONObject.<init>; -Xmx256m survives at 183.4 MB. The register's '120 MB live' counts the DOM plus one String only - the real live set is 183 MB, so it UNDERSTATES by ~35%. OutOfMemoryError is an Error, not an Exception, so it escapes every catch(Exception) and kills the process. Against a typical 128-192 MB per-app heap this means a routine 'import backup' KILLS the app - the arbiter RAISES this to P1. Also: the AOSP org.json uses LinkedHashMap/ArrayList while the measured reference uses HashMap/ArrayList (per-entry 40 B vs 32 B), so the AOSP DOM would be ~5 MB LARGER - the measurement is if anything optimistic for Android |
| `REG-P2-46` | P2 | **CONDITIONAL** | P3 | HIGH | static | Body confirmed; the title's '12' is wrong - 10 cold appearance reads + 3 audioSettings + 1 values = 14; PlaybackService:238 is a hot collection |
| `REG-P2-47` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+static | No setCacheKeyFactory on the streaming path; Media3 DEFAULT key = full signed URL; every re-resolution orphans the bytes. Within the TTL window the bytes ARE re-read |
| `REG-P2-48` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | resolveRemote calls exactly one provider; the desktop runs a cascade in both directions; PORTING_STATUS records LOGIN_REQUIRED |
| `REG-P2-49` | P2 | **CONDITIONAL** | P2 | HIGH | static+executed | 45s TTL and the never-read expiresAt confirmed; the stated CAUSE is wrong - the Yandex signature/ts live in the PATH, which is never normalised |
| `REG-P2-50` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+static | The expected total is received and discarded; Media3 commits whatever was written. Correction: a Content-Length-declared truncation fails loudly |
| `REG-P2-51` | P2 | **CONDITIONAL** | P2 | HIGH | bytecode+static | No headers on the media path (0 setUserAgent/setDefaultRequestProperties hits); UA is okhttp/4.12.0. The '403 on the first byte' is NOT reproduced - the repo probe shows SoundCloud serving 200/206 to the same client |
| `REG-P2-52` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | Prefix-only https checks for 2 of 3 providers; the correct allow-list exists in the same codebase for Yandex; followRedirects=false only on the provider-API client; the desktop closes all four holes |
| `REG-P2-53` | P2 | **CONFIRMED-STATIC** | P1 | HIGH | static+measured | 15 files / 59 @Test methods / 0 executed; no connectedDebugAndroidTest anywhere; no Android CI job. RAISED to P1 - the only guard on the Room v1-v2-v3 migration has never run |
| `REG-P2-54` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | Schemas 1/2/3 present, wired correctly; the whole android/ tree is untracked (git ls-files -> 0); 1.json/2.json are not reconstructible by any build task |
| `REG-P2-55` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | Re-hashed all 187 entries: match=160 differ=27 missing=0 - exact; 8 files unlisted; LocalArtworkTest in none of the 7 manifests. DUPLICATE of REG P2-38 |
| `REG-P2-56` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | run-emulator.ps1 requires a pre-built APK, never invokes instrumentation, points at a stale SDK path; no APK exists under android/; the documented on-ramp is an outright dead end |
| `REG-P2-57` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static+AAR | 5 files on the deprecated v1 Compose test API; the v2 package is present. Deprecation warnings, not lint errors - no build impact. Caveat: only v2.createAndroidComposeRule was found in the cached artifacts |
| `REG-P2-58` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | Guard is exactly tracks.isEmpty() && outcomes.any{failure}; the first SoundCloud search pays a 2.9 MB scrape inside the 6.5s budget |
| `REG-P2-59` | P2 | **CONDITIONAL** | P3 | HIGH | static+runtime | Mechanism confirmed; the quoted timings are NOT reproducible - re-measured worst case 0.89s for 20k rows, well inside the 6.5s budget |
| `REG-P2-60` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | bytecode+static | viewModelScope = Main.immediate (bytecode-confirmed); the JSONTokener parse and the 50k-node DOM walk run on the UI thread |
| `REG-P2-61` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | bytecode+static | The continuation resumes into the caller's Main.immediate context, so the parse and depth pre-scan run on the main thread; the 2 MiB cap bounds the cost |
| `REG-P2-62` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | httpCode is never read in ui/; the import loop collapses every failure into one counter. Correction: the message DOES survive on paths that rethrow |
| `REG-P2-63` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | The header/tile count complete downloads; the list renders every row. The byte sum on the same line also mixes in-flight bytes |
| `REG-P2-64` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | require(name.isNotBlank()) -> 'Failed requirement.' into the snackbar. Latent - both call sites disable the button while blank |
| `REG-P2-65` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | All 8 transport/queue commands cancel the pending preparation; the 20s window is confirmed; the old track resumes |
| `REG-P2-66` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | Provider failures are swallowed; a 404 primary + a failed cascade produces NO exception at all, so an outage is reported as 'no lyrics' |
| `REG-P2-67` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | forceRefresh bypasses both caches but the write-back is unconditional; an empty result with a 10-minute TTL replaces a 24-hour entry. Correction: the desktop's cited guard does NOT say 'never remembered' |
| `REG-P2-68` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | Gate is containsAll (superset); the desktop is intersection. Executed against the verbatim LyricsIdentity: 'Artist feat. Guest' vs 'Artist' -> rejected on Android, accepted on the desktop |
| `REG-P2-69` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | 2.2s per provider, strictly serial; per-provider request counts verified (1 / 1+4 / 5 / 1+4); the desktop runs them in parallel under one 8s budget |
| `REG-P2-70` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | 3500 + 4x2200 = 12300 > 12000 - exact. Correction: 12.3s is the whole lookup, not the cascade alone (8.8s) |
| `REG-P2-71` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | Strict version-set equality, no base fallback. Executed: all 10 version markers rejected against the plain title; the desktop accepts only remix/slowed/sped |
| `REG-P2-72` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | Captured output -> exit 1, zero Gradle tasks, no log file; uncaptured -> BUILD SUCCESSFUL. The exception type is RemoteException, not 'NativeException'; the termination is produced by the CALLER's 2>&1 merge, not by the script |
| `REG-P2-73` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+runtime | Reference behaviour executed and confirmed; the AOSP side read from source. TWO corrections: the shims are not 'dead code on the JVM classpath'; the count is 67 optString sites, 65 uncompensated (not '53 of 55') |
| `REG-P2-74` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | All three guards confirmed and silent; cap take(500), timeout 20s, worst case 2h46m40s |
| `REG-P2-75` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static+runtime | 0 hits for all 5 composition-root types in the test tree; 236/0/0/1 confirmed. It is a COVERAGE GAP, not a product defect. The '1 219 LOC' figure is wrong - 1 469 measured |
| `MAIN-P2-28` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | An oversized primary LRCLIB payload throws outside the provider-failure boundary, so the cascade is never consulted. Same symptom as P3-79 |
| `MAIN-P2-29` | P2 | **ALIAS** | P2 | HIGH | static | Alias of REG P2-69 + P2-70 (12.3s vs 12s) |
| `MAIN-P2-34` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | Smart-playlist view re-runs a full-library aggregation and sort every 5s while playing |
| `MAIN-P2-35` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | history has no retention policy; past 100k rows the backup export fails outright |
| `MAIN-P2-37` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | Navigation is one String with no back stack; Back from Settings/Profile always lands on Home |
| `MAIN-P2-38` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The nedotify://oauth/spotify deep link performs the exchange and leaves the user where they were |
| `MAIN-P2-39` | P2 | **RECOMMENDATION** | P3 | MEDIUM | static | Design.kt is not a token layer. This is a DESIGN RECOMMENDATION, not a contract violation - the report files it as a defect |
| `MAIN-P2-40` | P2 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The root composable subscribes to the catalogue progress flow; N imports = N full-tree recompositions |
| `MAIN-P2-41` | P2 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | positionMs is read at the top of PlayerScreen, invalidating the whole subtree at 2 Hz |
| `MAIN-P2-42` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | A second PKCE start invalidates the pending login. DUPLICATE of P3-66 |
| `MAIN-P2-43` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The local search projection has no album column. DUPLICATE of P3-25 |
| `MAIN-P2-44` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | searchPage ORDER BY addedAt DESC has no tiebreaker. DUPLICATE of P3-13 |
| `MAIN-P2-45` | P2 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The history write is the only unguarded Room write; an escaping exception terminates the process |
| `X-01` | X | **CONDITIONAL** | X | HIGH | bytecode+static | Structure confirmed: 3 playback-state holders, 5 layers of currency tokens, 4 identifiers literally named *Generation, 2 pending one-shot mechanisms, 3 stillCurrent predicates in PlaybackService. BUT the headline ('three mechanisms') contradicts its own table ('five layers') and the executive summary sides with the table. The rationale paragraph rests on the REFUTED Media3 claim (FP-1). The '270 KB per next()' figure is the all-UUID worst case; a typical 3000-track queue serialises to ~85 KB, and there is ONE serialisation and ONE file rewrite per checkpoint, not two |
| `X-02` | X | **CONDITIONAL** | X | HIGH | static | Format/version/testability half CONFIRMED: queue_v1 vs payload version 2, no version check on read, unreachable from a JVM test (no Robolectric), the desktop caps at 200 and writes once at exit (core/session.py:9,50-55,57-63). BUT the opening claim 'the only thing that survives process death' is FALSE - the Room DB, two DataStore files, the download store and the library id all survive. The correct statement is 'the only durable state of the playback session' |
| `X-03` | X | **CONFIRMED-STATIC** | X | HIGH | static | All three disagreements CONFIRMED: both are SimpleCache; identity differs (download = SHA-256 + normalised URL, streaming = Media3's default full signed URL); integrity differs (no completeness check, NoOpCacheEvictor vs a real signed-URL TTL). The shared-SQLite-index item is a HYPOTHESIS in the source row and is restated here as fact - flagged. The (P2-30) citation is broken under the MAIN namespace |
| `X-04` | X | **CONDITIONAL** | X | HIGH | static | Structure confirmed (many read sites, several mechanisms, two independent subscriptions, one shared key) but the counts are wrong: 13 independent subscriptions to the DataStore flow (10 cold + 3 hot) and 19 distinct read points - not 'nine' (X-04) and not 'twelve' (P2-46, whose own body says 14). At least six distinct access mechanisms are in use, not four. The (P2-73) citation resolves to nothing in either namespace |
| `X-05` | X | **CONFIRMED-STATIC** | X | HIGH | static | Substance CONFIRMED: 9 write call sites / 8 write paths (the row lists 5 and omits the autoplay append, download enqueue, favourite and add-to-playlist); NO DELETE FROM tracks anywhere in the DAO; no UI track-removal affordance; playback writes the entire search result list. The headline's 'three of its writers' contradicts its own five-item list, and the implied rule does not hold |
| `X-06` | X | **CONFIRMED-STATIC** | X | HIGH | static | CONFIRMED: the desktop has zero backup machinery in the whole tree (232 defs in core/api.py, 0 'backup' hits), so it can neither produce nor consume the nedotify-library JSON; 5 tables and 29 column-name occurrences (23 distinct) are hand-reimplemented; 7 smart-rule keys and 5 sort values confirmed; no version marker, no golden fixture, no conformance test, no CI job. The section-2.4 figure of '26' is the erroneous one. The quoted desktop comment is about WAL checkpointing, not about format versioning |
| `A-1` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. The 'Today' description is ACCURATE: a private string produced and consumed inside a MediaSessionService, a version written but never read, a key that disagrees with the payload, no test (needs a MediaSessionService; no Robolectric in the build) |
| `A-2` | A | **RECOMMENDATION** | A | HIGH | bytecode | Architecture recommendation, not a defect. Its PREMISE IS REFUTED: the 'Today' text repeats the claim that the app's own command path never triggers the release wire - it does (FP-1). The recommendation itself (a typed intent token) remains sound; the stated current state must be corrected |
| `A-3` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. The 'Today' description is ACCURATE: three copies of the playback state, the error dimension missing from the ViewModel's copy, the listener attached at connect but the seeding read copying no error |
| `A-4` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. The 'Today' description is ACCURATE: the source is encoded in the MediaItem, changing it requires an O(N) main-thread queue rewrite, the trigger set covers only the completed-download table and misses localUri changes, and the ResolvingDataSource seam already exists |
| `A-5` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. The 'Today' description is ACCURATE: (application as NeDotifyApp) in exactly four places, no MusicViewModelTest/PlaybackServiceTest/NeDotifyAppTest, no android:process in the manifest. The three named test files are exemplary, not the full list of extracted-and-tested units |
| `A-6` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. Its 'Today' description is INACCURATE in one number: '12 independent cold DataStore reads' is wrong (10 cold + 3 + 1 = 14, of which 10 read .offline), and (P2-46) does not resolve under the MAIN namespace - the same finding is MAIN P2-36. The 'one preferences authority' half is well founded: two independent DataStore files and only AudioSettingsStore has an injection seam |
| `A-7` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. The 'Today' description is ACCURATE with one terminology imprecision: 'content-addressed remote ids' is the wrong label - the remote ids are provider-scoped natural keys and the content-addressed SHA-256 ids are the LOCAL ones (and are also the device-scoped ones), so the two attributes are swapped. The 'same-named playlist' defect is real but has no P-row of its own |
| `A-8` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. Accurate in substance; 'bare literals in four files' under-counts - the seven states appear in TEN main-source files (four writers plus six UI readers); 'four' is right only for the writers. The overloaded 'failed' state is CONFIRMED: a failed REMOVAL offers a retry that RE-DOWNLOADS the track (P3-75) |
| `A-9` | A | **RECOMMENDATION** | A | HIGH | static | Architecture recommendation, not a defect. Inaccurate in one number: 'five different paths' under-counts - there are 8 write paths / 9 call sites. 'Has no delete affordance' and 'is polluted by playback' are ACCURATE; the (P2-31) reference does not resolve under the MAIN namespace |
| `A-10` | A | **RECOMMENDATION** | A | HIGH | static+hash | Architecture recommendation, not a defect. The 'Today' description is ACCURATE: 7 manifests; 'two names for one artefact' under-states it - FOUR file pairs share byte-identical twins; 3 of the 39 baseline entries no longer exist; git ls-files android -> 0; the Android .gitignore already excludes exactly the right things |
| `REG-P2-76` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | AGP model inspection | CONFIRMED via an AGP model dump (init script, real project copy, NO APK built). CORRECTION to the framing: AGP DOES synthesise a 'release' build type even though the file declares no buildTypes block - the EFFECTIVE state is what matters: release.minifyEnabled=false, release.shrinkResources=false, release.signingConfig=null (=> assembleRelease produces an UNSIGNED apk), release.applicationIdSuffix=null and debug.applicationIdSuffix=null (=> both are 'ru.nedotify.app', so a debug build SILENTLY REPLACES a release build), and proguardFiles=[] with no proguard-rules.pro anywhere. debug already has AGP's auto-generated ~/.android/debug.keystore, so only release is unsigned. The right phrasing is 'no buildTypes CUSTOMISATION' |
| `REG-P2-77` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | runtime (network blackout experiment) | CONFIRMED FOR THE CONCLUSION, FALSE FOR THE STATED MECHANISM. The mechanism 'reaches out to Maven Central on EVERY build' is FALSE: the detector's reads are CACHE-BACKED (TTL in hours, default 7 days; cache in app/build/intermediates/lint-cache/.../maven-versions/), so the reach-out happens on a cold/expired/cleaned cache. The detector DOES read the network (Lint.readUrlData with a maven-metadata.xml bootstrap) - the on-disk proof is the lint cache the detector itself wrote. BUT THE CONCLUSION IS EMPIRICALLY PROVEN: three lint runs on the SAME UNCHANGED SOURCE gave 15 warnings (the stored report, 18:41), 13 (network on, 20:47 and 21:04) and 4 (network blocked via a black-hole proxy + the lint cache deleted, 21:31) - and even different 'latest version' numbers (Gradle 9.8.1 vs 9.8.2; core-ktx 1.19.1 vs 1.18.0). The gate's result is NOT a function of the source. Also: 34 literal dependency coordinates (+1 platform(...)), not 30; no libs.versions.toml; no dependencyLocking; no verification-metadata.xml. CORRECTION: the lint{} block sets NEITHER checkDependencies NOR checkReleaseBuilds - AGP 9.1.1 defaults both to TRUE, so a fix must not rely on those flags |
| `REG-P2-78` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | resolved-artifact metadata | CONFIRMED from the cached .pom/.module files: symbol-processing-api-2.3.12 declares kotlin-stdlib 2.3.20 (KSP 2.3.12 is built against Kotlin 2.3.20) while the project compiles with Kotlin 2.2.10; and room-compiler:2.8.5 declares symbol-processing-api 2.0.10-1.0.24 (a ~2.6-year-old line). SEVERITY LOWERED TO P3: the register itself records 'Impact: None observed today' and :app:kspDebugKotlin ran clean in every build (2.2-4.8s, no mismatch warning) - this is a dormant upgrade-time hazard, not a present defect. Nuance the plan omits: Gradle resolves to the HIGHEST of the two KSP API coordinates (2.3.12), so only one ends up on the classpath - 2.0.10-1.0.24 is a DECLARED dependency, not the resolved one |
| `REG-P2-79` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | filesystem+environment inspection | CONFIRMED with corrections. The SDK really is inside the system temp dir: C:\Temp\nedotify-android\sdk = 34 671 files, 3 876 413 431 B = 3 696.8 MiB (the plan's '3 697 MB' is exact), and ANDROID_HOME/ANDROID_SDK_ROOT are empty and %LOCALAPPDATA%\Android\Sdk does not exist. TWO CORRECTIONS: (a) the alias is PER-CHECKOUT-PATH, not per-run - the identity is SHA-256(projectPath)[0..9] = B3544D227D, so C:\Temp\nedotify-B3544D227D\sdk is a stable junction to the shared SDK, and only the SDK it points to is in a shared location; (b) local.properties is per-checkout and gitignored, not 'globally shared' - it IS shared by every process using that checkout, and verify.ps1 rewrites it in place, so two concurrent runs race (which is what the plan's R4.4 covers). Also, local.properties is not literally the ONLY channel: verify.ps1 exports ANDROID_HOME/ANDROID_SDK_ROOT for the duration of its own run - it is the only channel for a DIRECT gradlew invocation, and AGP prefers the file over the env var when both are set |
| `REG-P3-111` | P3 | **CONFIRMED-STATIC** | P3 | HIGH | resolved-artifact metadata + source | Dependency facts CONFIRMED: haze-android 1.7.3 pulls org.jetbrains.compose.ui/foundation 1.12.0, kotlin-stdlib 2.3.20 (newer than the project's 2.2.10), and its AAR metadata declares minCompileSdk=37 - which the project's compileSdk 37 exactly meets, so the constraint is currently SATISFIED and lowering compileSdk would break the build. TWO CORRECTIONS: (a) 'all 35 .glass() call sites' is 35 TEXTUAL matches of which 1 is the definition (Design.kt:71) and 1 is an unrelated MusicViewModel.glass(Boolean) - so 33 real Modifier.glass() call sites; (b) THE 'one-function change' IS FALSE - dropping haze touches TWO files at EIGHT sites (Design.kt:28 import, :36 LocalBackdrop typed HazeState, :75-77 the hazeEffect inside Modifier.glass; MusicApp.kt:28 import, :52 HazeState(), :58 LocalBackdrop provides, :60 .hazeSource(haze)). That is the plan's most misleading sentence. Mitigation the plan omits: the org.jetbrains.compose.* artefacts are genuine EMPTY SHIMS (ui.aar = 6 026 B, foundation.aar = 6 118 B), so there is no duplicate-class risk |
| `REG-P3-112` | P3 | **CONFIRMED-STATIC** | P3 | HIGH | source+bytecode | CONFIRMED: zero ImageLoader/SingletonImageLoader/ImageLoaderFactory anywhere in android/; coil-network-okhttp's service loader returns OkHttpNetworkFetcher.factory() whose default is a STOCK new OkHttpClient() (bytecode: invokespecial OkHttpClient.<init>:()V - no builder at all), so the cover-art path has connect/read/write 10 000 ms and callTimeout=0, i.e. NONE of the app's 12/20/30s bounds and none of its 2-4 MB maxBytes cap. The app's MusicNetwork client is never seen by Coil. Two Coil request sites: cover art (Design.kt:119, reached from 10 Cover() call sites) and the profile avatar (ProfileScreen.kt:47) - both third-party provider URLs. The plan's characterisation matches the bytecode |
| `REG-P3-113` | P3 | **CONFIRMED-STATIC** | P3 | HIGH | real build + profile | CONFIRMED with two precision corrections. Real --warning-mode all output: exactly THREE deprecation sites, all the Groovy space-assignment form, at app/build.gradle:7, :17 and :24; and the emitted line is verbatim 'Deprecated Gradle features were used in this build, making it incompatible with Gradle 10.' The configuration cache is OFF (no org.gradle.configuration-cache in gradle.properties; every build prints 'Consider enabling configuration cache'). CORRECTION 1: the SDK-XML-version-mismatch warning is printed on COLD-DAEMON builds only - the SDK parse is cached in the daemon, so a warm build is silent; 'every build prints' is an overstatement. CORRECTION 2: the '11.5 s configuration phase' is a COLD-DAEMON figure - measured 10.657 s cold (23.117 s total) versus 0.321-0.612 s WARM, i.e. two orders of magnitude lower in the steady-state dev loop. The plan also omits that the wrapper distribution IS pinned with a SHA-256 (distributionSha256Sum=b266d5ff..., validateDistributionUrl=true) - the one genuinely hermetic part of the build |
| `REG-P3-114` | P3 | **CONFIRMED-STATIC** | P3 | HIGH | own measurement | CONFIRMED and independently MEASURED in an isolated copy: a one-line edit to a leaf main source gives :app:compileDebugKotlin 34.749 s and 38.774 s total - the plan's 33.6 s REPRODUCES (+3.5%). The main report's P3-86 numbers ALSO reproduce: 5 m 33 s for compileDebugKotlin+lintDebug (its '5 m 8 s', +8%) and 57.513 s for the forced main-source recompile (its '58 s', -0.8%). THE TWO NUMBERS ARE THE SAME WORK MEASURED IN TWO CONTEXTS: 34.7 s is a DEDICATED rebuild on an idle machine (only kspDebugKotlin 2.2 s + compileDebugKotlin 34.7 s re-run); 57.5 s is the same recompile inside a combined compile+lint invocation where three lint analysis workers (4m18s + 1m46s + 1m23s) run concurrently and compete for the same 12 CPUs and 3 GB heap. The difference is CONTENTION, not a different algorithm. Nuance: the gradle.properties comment's premise is stale - verify.ps1 ALWAYS builds through the alias, so the path IS stable for every verify.ps1 run; the instability only arises when someone builds directly at the Cyrillic path |
| `REG-P1-05` | P1 | **CANNOT-VERIFY** | P1 | LOW | static | Arrived in the register's Addendum 3 DURING this verification and was not independently verified here. Recorded for completeness: the register's own claim is that P1-05 is REG P2-59 'measured properly and PROMOTED to P1' - a 50 000-row local scan takes 13.9 s and a 100 000-row scan 63.5 s against the aggregate's 6.5 s per-source budget, and the desktop uses an FTS5 index. This verification's INDEPENDENT measurement of REG P2-59 (worst case 0.89 s at 20 000 rows) is consistent with that crossover and supports the promotion |
| `REG-P2-80` | P2 | **CANNOT-VERIFY** | P2 | LOW | static | Addendum 3 (register :597). The SoundCloud 8s-vs-6.5s timeout asymmetry |
| `REG-P2-81` | P2 | **CANNOT-VERIFY** | P2 | LOW | static | Addendum 3 (register :610). The 500x2 sequential-search cost; overlaps REG P2-08 |
| `REG-P3-115` | P3 | **CANNOT-VERIFY** | P3 | LOW | static | Addendum 3 (register :619) |
| `REG-P3-116` | P3 | **CANNOT-VERIFY** | P3 | LOW | static | Addendum 3 (register :626). The OFFSET pagination instability; overlaps MAIN-P2-44 |
| `P3-01` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | MediaStore/SAF grants: 3 take, 0 release. The 128-grant cap IS caught and reported, not a crash |
| `P3-02` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No rationale, no already-asked flag, no route to app settings. A message IS shown, so 'silently does nothing' is wrong |
| `P3-03` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Conflating MutableStateFlow<String?>. The window is the snackbar display time - 'never shown' is overstated |
| `P3-04` | P3 | **CONFIRMED-RUNTIME** | P3 | MEDIUM | static | Raw IOException text reaches the UI. Scope: MusicNetwork only, the provider transport already curates |
| `P3-05` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | explicitQueueBoundary cleared only on a transition; a set with no transition leaves it set. THIS IS THE RESIDUAL OF THE REFUTED P2-10 |
| `P3-06` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Identical PendingIntent (request code 0). Harmless today |
| `P3-07` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 6120/h confirmed (a floor). 'The process can never go fully idle' is wrong - the loops die with the service |
| `P3-08` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Every download-state change re-materialises and deep-diffs the whole queue on the main thread |
| `P3-09` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The gain step exists only on the STATE_ENDED branch; the normal progress>=1 path has no step |
| `P3-10` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | OVERSTATED - configure() does not call onUserInteraction; it reaches it only via finishIfEnded() with autoplay off. FP-4 |
| `P3-11` | P3 | **CONDITIONAL** | P3 | MEDIUM | static | Code fact holds but no contract documents 'the next'; the desktop has no equivalent path. Half a contract decision |
| `P3-12` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The desktop caps a listening tick at 15s; Android has no upper bound |
| `P3-13` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 4 non-tiebroken ORDER BY queries confirmed. DUPLICATE of MAIN-P2-44 |
| `P3-14` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | MediaStore scan and SAF import produce two rows with independent state |
| `P3-15` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Column names from the untrusted file are interpolated unquoted; TABLE names are hard-coded literals |
| `P3-16` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | ~422100 statements at the caps (history costs 3 each) in one transaction, no cancel |
| `P3-17` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | A wrong token yields 'РЎСЂРѕРє РІС…РѕРґР° РёСЃС‚С‘Рє' - the input is not named |
| `P3-18` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | cipher.init(key(true)) is outside the try; a broken alias is never replaced. The raw crypto exception also reaches the UI |
| `P3-19` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No CertificatePinner. A HARDENING DECISION TO RECORD, not a contract violation |
| `P3-20` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The Spotify import stores the candidate's metadata; the parsed catalogue metadata is discarded. Yandex keeps it |
| `P3-21` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No maxBytes seam; 2 account-size-growing endpoints affected |
| `P3-22` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | A 401/403 is an InvalidResponseCodeException, not a SourceFailure - the download path does distinguish it |
| `P3-23` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The DRM message is false; the desktop distinguishes the verdict and has a 1h negative cache |
| `P3-24` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | https-only, no host allow-list, no redirect check. DEFENCE IN DEPTH |
| `P3-25` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The projection has no album. DUPLICATE of MAIN-P2-43 |
| `P3-26` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | source is not validated; the query is unbounded at the data layer. Not reachable from the current UI |
| `P3-27` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No playability pre-flight; the matcher commits to the first candidate and never retries the other provider |
| `P3-28` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The UI prints the returned count. Parity with the desktop's 50 |
| `P3-29` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Only the LRCLIB branch sets source. DUPLICATE of P3-78 |
| `P3-30` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | safeGeniusPage validates the initial URL only; the fetch follows redirects |
| `P3-31` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The .tmp orphan is never reclaimed |
| `P3-32` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The discovery path does not fold РЃ->Р• (CatalogMatcher and LyricsCascade do) |
| `P3-33` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | An all-neutral rule set is accepted; no count cap on createSmart. The desktop refuses both |
| `P3-34` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | queue_v1 vs payload version 2, never validated on read |
| `P3-35` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The avatar remove branch is unreachable; AsyncImage has no error painter. DUPLICATE of P3-64 |
| `P3-36` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No injection seam; 12 keys; no test references Preferences. DUPLICATE of P3-95 |
| `P3-37` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | RECOMMENDATION. The row duplicates the track-row pattern (2) but there are 10 glass-bearing row components, not 4. FP-7 |
| `P3-38` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | listened is declared and never read |
| `P3-39` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The '18 surfaces' figure is not reproducible (7 static sites). Nested glass and blurRadius=22dp ARE confirmed. FP-6 |
| `P3-40` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No scheme check on the artwork URL; the desktop import copies cover_url verbatim |
| `P3-41` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | LocalTime.now().hour is sampled during composition |
| `P3-42` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Only 2 icons are fixable - Sort has no auto-mirrored variant. FP-5 |
| `P3-43` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The icon contentDescription repeats the tab label |
| `P3-44` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | RecommendationLoader.request() is not idempotent; up to 2 x 12s SoundCloud searches |
| `P3-45` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No values-night override; a dark window background in the light theme |
| `P3-46` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The O(N) firstOrNull runs at 2 Hz; the mini player's copy was already hoisted |
| `P3-47` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | indexOfLast per tick over up to 20000 lines; the list is sorted |
| `P3-48` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | scrub uses remember, the neighbours use rememberSaveable |
| `P3-49` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The scrub is cleared in the same frame as the async seek |
| `P3-50` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The core claim holds; the lyrics are restored from cache, so the artefact is a spinner FLASH. FP-8 |
| `P3-51` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Android OFF->ONE->ALL; the desktop OFF->ALL->ONE |
| `P3-52` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No clear action; clearQueue() has no caller and clearMediaItems stops playback |
| `P3-53` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The header switches synchronously while the rows lag. The window is one Room emission |
| `P3-54` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The button prints the raw count; the import caps at 500 distinct |
| `P3-55` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The byte sum covers all rows next to a count of the complete ones |
| `P3-56` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | require(name.isNotBlank()) -> 'Failed requirement.' Latent. DUPLICATE of REG P2-64 |
| `P3-57` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No hasSearched flag; the same hint renders for both empty states |
| `P3-58` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The label prints the draft; the hardware applies the device-clamped value |
| `P3-59` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | A slow first emission silently falls back to 256 MB; runBlocking blocks the main thread |
| `P3-60` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | A failed write leaves the optimistic draft on screen |
| `P3-61` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The dialog closes before the write; the UI never filters the control characters the model rejects |
| `P3-62` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The 750 ms progress write re-runs the whole settings scope. '~30 composables' is an estimate |
| `P3-63` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The whole tracks table flows into the composition for one integer |
| `P3-64` | P3 | **MERGED** | P3 | MEDIUM | static | A pure [MERGED] pointer to P3-35 with no independent content |
| `P3-65` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Three desktop features absent from the porting status. A DOCUMENTATION GAP |
| `P3-66` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | A second PKCE start invalidates the pending login. DUPLICATE of MAIN-P2-42 |
| `P3-67` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The pending is cleared only for one exact message; cancelSpotifyLogin() has no caller |
| `P3-68` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The confirm button clears the field before the save completes |
| `P3-69` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No liveRegion in ConnectionsControls; BackupControls in the same screen has one |
| `P3-70` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | password() semantics are used nowhere. The 'reads the token aloud' impact is OVERSTATED |
| `P3-71` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The origin trigger is unreachable, but the other require on the same lines IS reachable and is swallowed |
| `P3-72` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The MIME array is too wide. The '*/*' sub-claim is false for the backup picker |
| `P3-73` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | pendingBackup holds a materialised LibraryBackup for the whole preview |
| `P3-74` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Three failure categories funnel through one invalid(); the test asserts the type, not the message |
| `P3-75` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | A failed removal uses the generic failed state; the retry RE-DOWNLOADS the track and never reclaims the files |
| `P3-76` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | An API-34+ foreground-start restriction is not recognised; the message is generic |
| `P3-77` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | Two StandaloneDatabaseProvider instances over one SQLite file. The SQLITE_BUSY outcome remains a hypothesis |
| `P3-78` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The cascade never sets LyricsResult.source. DUPLICATE of P3-29 |
| `P3-79` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | lyricsResult() sits outside the try/catch; an oversized payload aborts the whole lookup. Overlaps MAIN-P2-28 |
| `P3-80` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No schema version in the lyrics cache key or record |
| `P3-81` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The lyrics cache lives in the purgeable cacheDir |
| `P3-82` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | Exactly 3 space-assignment Groovy usages |
| `P3-83` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The artefacts are stale (217/17/55) vs the real 236/15/59. All three numbers in the row are correct |
| `P3-84` | P3 | **CONDITIONAL** | P3 | MEDIUM | static | returnDefaultValues is on but 0 unit tests import android.*, so it masks nothing today. A RECOMMENDATION |
| `P3-85` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The APK path does not exist and verify.ps1 cannot produce one. The instruction is unfollowable |
| `P3-86` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | kotlin.incremental=false with the stated reason. DUPLICATE of PLAN-P3-114 with a different measurement |
| `P3-87` | P3 | **FALSE-POSITIVE** | P3 | MEDIUM | static | The alleged contradiction does not exist - REVIEW_RESOLUTION.md is self-consistent. FP-15 |
| `P3-88` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | FINAL_CHECKS.json (2026-10-18 22:41) vs the 07:41 pair; the APK ban is recorded inconsistently inside one day |
| `P3-89` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | verify.ps1 has no header block; the documented on-ramp dead-ends |
| `P3-90` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The 5-contracts claim is reproduced; the 35 files / 3977 LOC / 54.6% is NOT reproducible (38/4618/63.4% strict). FP-17 |
| `P3-91` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 15 files / 59 @Test methods, no connectedDebugAndroidTest, no Android CI. The '55' is wrong. DUPLICATE of REG P2-53 |
| `P3-92` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 236 / 0 / 0 / 1 reproduced exactly; VALIDATION.md says 217. DUPLICATE of P3-83 |
| `P3-93` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | assumeTrue(env) is the only guard; provider failures are caught so the test passes anyway |
| `P3-94` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | An exact request count is asserted under a real 2200ms budget - flaky, and it cannot distinguish a provider-skipping regression |
| `P3-95` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | The test asserts the contents of a constant; Preferences itself has no test. DUPLICATE of P3-36 |
| `P3-96` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 5 desktop columns have no Android counterpart. A DECLARED capability gap |
| `P3-97` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | No ReportPeriod.YEAR; calendar vs rolling windows. A DECLARED difference |
| `P3-98` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | A REPEAT starts a new session id - confirmed by the test name. A DECLARED difference |
| `P3-99` | P3 | **FALSE-POSITIVE** | P3 | MEDIUM | static | The local search pages the WHOLE tracks table, so the claimed trigger does not hold. FP-16 |
| `P3-100` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 256 MB vs 500 MB; LRU only, no age step; no loudness normalisation. A DECLARED difference |
| `P3-101` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 5 tables and 29 column names hand-duplicated with no spec or fixture. Counts confirmed exactly |
| `P3-102` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | 7 state holders across 3 layers confirmed. A DESIGN OPINION |
| `P3-103` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | NowPlaying has no error dimension. The error DOES reach the user as a snackbar, so 'never reaches the user' would be wrong |
| `P3-104` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | The listener is attached and the mirror seeded, but update() copies no error dimension |
| `P3-105` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | A null message clears the channel and the error is dropped |
| `P3-106` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | close() never resets fading, so the crossfade hint persists |
| `P3-107` | P3 | **CONDITIONAL** | P3 | MEDIUM | static | A stale controller snapshot is possible but Media3-internal; the mirror does not carry playbackState so the proposed fix is impossible today. A DESIGN RECOMMENDATION |
| `P3-108` | P3 | **CONFIRMED-STATIC** | P2 | MEDIUM | static | onDisconnected is overridden nowhere in src/** |
| `P3-109` | P3 | **CONFIRMED-STATIC** | P3 | MEDIUM | static | sendError fires before the automatic recovery, so a self-healing error is still shown |
| `P3-110` | P3 | **CONDITIONAL** | P3 | MEDIUM | static | The impact is right, the attribution is wrong - it is the in-memory resolution key that omits the format, not the disk cache key |
| `REG-P2-17` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime+static | CONFIRMED: the desktop skips the row (services/smart_playlists.py:87-88 `except (TypeError, ValueError): continue`, executed: 1 of 3 rows returned, no error) while the Android bridge aborts the whole import on `BackupCodec.requireStrictJson("")` -> 'ожидается объект JSON'. Correction: the desktop's skip is at :87-88, not :83-86 |
| `REG-P2-18` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | The reader selects only the columns that exist and the converter defaults them; is_favorite/added_at/duration/source are silently lost and the notice says nothing |
| `REG-P2-19` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static+executed | CONFIRMED, but the register's OWN REPRO IS WRONG: '10k tracks + 40k history rows' = 11.03 MB, UNDER the 16 MB cap - it does not trip. The trip needs the codec's own caps (20k tracks + 100k sessions + 100k links) or ~14k tracks with full-length ids/titles. Measured marginal costs: track 298 B, session 211 B (the register said 170-200 - slightly low), link 82 B; the register's 11.7 MB scenario recomputes to 12.13 MB |
| `REG-P2-20` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | CONFIRMED by an executed transliteration: two PCs with the same label produce the SAME libraryId, the SAME portableTrackId and the SAME playlist/session/smart ids. Both claimed outcomes reproduce: (a) the second import MERGES SILENTLY into the first PC's playlists - PC1's playlist NAME and identity survive and PC2's links are appended; (b) if the two PCs recorded the session at different instants, the second import fails outright with 'Конфликт сессии прослушивания в резервной копии'. The desktop's tracks.id is INTEGER PRIMARY KEY AUTOINCREMENT and restarts at 1 per machine, so the collision is guaranteed, not unlikely |
| `REG-P2-21` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | CONFIRMED by an executed WAL reproduction: a copy of the main .db alone passes PRAGMA quick_check(1)='ok' and still reports journal_mode=wal, yet the newest track AND the entire history are missing. The desktop's own docstring (core/database.py:1858-1866) states the hazard verbatim: 'the recent writes are lost without a word' |
| `REG-P2-22` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime+bytecode+primary-source | CONFIRMED with three independent evidence sources: the AOSP libcore source fetched live (JSONObject.optString -> JSON.toString(opt(name)) -> String.valueOf(JSONObject.NULL) = 'null'), the org.json jar's bytecode (optString returns the FALLBACK for JSON null), and an executed probe. Consequences re-derived: a null Spotify name -> a track titled 'null'; a null Yandex owner.uid -> uid='null' -> fails the [0-9]{1,24} regex -> the WHOLE PLAYLIST is dropped silently, while the JVM dep would have used the default uid and kept it - the suite really does mask it. TWO SITES THE REGISTER OMITTED: CatalogProviders.kt:29 and :45 (optString('type',...)) are also affected. Fix caveat: isNull(key) is also true for a MISSING key, so the per-field defaults must be kept |
| `REG-P2-23` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | likedTracks() issues exactly one unpaginated GET and never checks completeness, while the sibling playlist path does |
| `REG-P2-24` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | playable() is a pure metadata conversion; account entitlement is discovered only at play time, so the import reports 'nedostupno: 0' |
| `REG-P2-25` | P2 | **CONDITIONAL** | P2 | HIGH | primary-source | PREMISE NOW PRIMARY-SOURCE PROVEN: the Android platform SQLite versions were fetched from the AOSP tags - API 26 = 3.18.2, API 27 = 3.19.4, API 28 = 3.22.0 - and the SQLite 3.22.0 changelog confirms read-only WAL support landed there. So both API 26 and 27 predate it. The CONSEQUENCE still needs an API-26 device. NEW MITIGATING DETAIL the register omits: because the importer copies ONLY the .db (no -shm, no -wal), even a 3.22.0+ reader has no shared-memory file and treats the copy as a plain empty WAL - so the read-only aspect may not be the operative failure at all; that IS the P2-21 hazard |
| `REG-P2-26` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | CONFIRMED by an executed transliteration of BackupMerge.plan: the second import reports success, the OLD row's title/artist/album/duration AND its localUri survive, and the new track never appears. The conflict check (BackupMerge.kt:17-18) compares source/sourceId, which are constant ('local'/'') for local tracks, so it can never fire. Note the existing test BackupMergeTest.sameLibraryRestorePreservesLocalGrantsMetadataAndAddedAt pins the SAME 'old row wins' policy for a legitimate re-import - so this is a deliberate policy that the same-origin collision silently triggers. Fix caveat: extending the conflict check naively would make a legitimate re-import fail, so it must compare metadata, not just source |
| `REG-P2-27` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+static | CONFIRMED and the Media3 constraint is byte-verified: ExoPlayerImpl.setShuffleOrder asserts shuffleOrder.getLength()==mediaSourceHolderSnapshots.size(), so the full-length order is mandatory. CORRECTION: the register's 'although the standby only ever plays one item' is FALSE - the standby becomes the ACTIVE deck at handover (activeSlot swap + handoverTo(incoming)), so it takes over the whole queue; the full playlist is NECESSARY, not redundant. The real defect is the DUPLICATION and the per-boundary rebuild, and the register's own fix (a one-item standby playlist) would VIOLATE the Media3 assertion |
| `REG-P2-28` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | applyVolumes() reads AudioRuntime.status.value.eqSupported - a published UI snapshot - to decide the EQ headroom |
| `REG-P2-29` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | The worker enters the foreground before taking the Semaphore(2) permit; WorkManager's default maxSchedulerLimit is 20 |
| `REG-P2-30` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | No per-download byte ceiling, no Content-Length check, no StatFs probe, NoOpCacheEvictor; ENOSPC is an IOException and therefore retryable |
| `REG-P2-31` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | CONFIRMED: SearchScreen.kt:98 passes the whole result list as the queue; MusicViewModel.kt:161 ensureTracks(items) writes every one into the permanent library; no DELETE FROM tracks anywhere; the queue is <=155 (100 local + 25 SoundCloud + 30 YouTube) - the register's '~155' is exact. CORRECTION: 'the desktop writes to tracks only on download and add-to-playlist, never on play' is FALSE - core/api.py:1319 (maybe_log_history -> ensure_track_exists ON PLAY), :2652 (toggle_favorite) and :2420/:3481 also write. The desktop's add_track is an upsert keyed on source/source_id/file_path/title+artist, so a repeat play does not duplicate - the contrast is 'the desktop creates ONE row per played track and de-duplicates by identity', not 'the desktop never writes on play' |
| `REG-P2-32` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | CONFIRMED; severity lowered to P3 - cosmetic and self-correcting within ~350 ms plus network time; no data loss. Correction: the list is not EMPTIED but REPLACED by a progress row (SearchScreen.kt:84-89); the 'Ничего не найдено' branch is correctly gated on the new query having completed |
| `REG-P2-33` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | CONFIRMED; severity lowered to P3 - per-item UI state loss plus flicker on reorder, no data loss. The index prefix changes for the moved item AND every item after it, so the per-row DropdownMenu state (remember { mutableStateOf(false) }) is discarded. Fix caveat confirmed: Compose throws on duplicate keys, so the key must be the media id plus an occurrence counter, or the queue must be deduplicated |
| `REG-P2-34` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | CONFIRMED; the O(n) shape and the 3 000 Pair allocations are right, but '6000 String.equals' is an OVER-STATEMENT: String.toString() returns the same instance, so String.equals short-circuits on identity - the real cost is 3 000 Pair allocations plus 3 000 identity comparisons |
| `REG-P2-35` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | CONFIRMED; severity lowered to P3 - a UI fidelity gap, and the data is already in the same layer (ui/MusicApp.kt:37 builds trackIndex: Map<String,Track>). The desktop renders a 42x42 cover, title, artist, duration and a remove button (queue.js:157-165); the Android row renders the index, the title and an overflow menu only. The register's fix caveat is right: widening NowPlaying.queue widens the per-emission equality comparison (P2-34), so the two fixes must land together |
| `REG-P2-36` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | bytecode | CONFIRMED against the exact pinned material3-android-1.4.0.aar: secondaryContainer light #E8DEF8 / dark #4A4458, tertiary light #7D5260 / dark #EFB8C8, surfaceContainerHigh light #ECE6F0 / dark #2B2930 - all four hex values exact, and the token bindings (FilterChipTokens.FlatSelectedContainerColor -> SecondaryContainer; DialogTokens.ContainerColor -> SurfaceContainerHigh) are confirmed. The '7 of ~40' count is right (ColorScheme exposes 48 roles). ONE CORRECTION: the SLIDER and PROGRESS sub-claim is NOT affected - in M3 1.4.0 both use colorScheme.primary, which IS overridden. The chip, the dialog and the mini-player favourite heart (tertiary) ARE affected, and the Library tile's heart is a hard-coded #B52366 - two different favourite colours in one app |
| `REG-P2-37` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | The when(route) branch REPLACES the screen, so rememberSaveable state (sort, dialogs, typed name, scroll) is dropped on every tab switch |
| `REG-P2-38` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | 160 match / 27 differ / 0 missing reproduced EXACTLY by an independent re-hash; VERIFY.ps1 exits 1 with 'Source changed: app/src/androidTest/.../BackupTransactionTest.kt'. 7 source files + app/build.gradle are unlisted; app/build.gradle WAS in STAGE4_SOURCE_SHA256.txt, so it was dropped. ALIAS (important): register P2-38 == the MAIN audit's PROSE/TABLE P2-38 (:2175, :2236, :2338); the MAIN audit's SECTION 5.1 HEADING P2-38 is a DIFFERENT defect (the oauth deep link). DUPLICATE of register P2-55 |
| `REG-P2-39` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | CONFIRMED: AGENTS.md/STATUS.md/README.md contain 0 matches for 'android'. The root file gives no way to know a second product exists, so desktop contracts get applied to Kotlin code. ONE CORRECTION: the register's 'no EventSource/WebSocket channel anywhere in ui/** is false by glob' is an OVER-STATEMENT - the Android ui package also has none, so the sentence is factually true today; the real problem is the AMBIGUOUS SCOPE MARKER (ui/** now matches two directories), not a false statement |
| `REG-P2-40` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | android/AGENTS.md protects ~/.nedotify - a host path that cannot exist on the device - and never names the device library |
| `REG-P2-41` | P2 | **CONFIRMED-STATIC** | P3 | HIGH | static | CONFIRMED; severity lowered to P3 - documentation navigability only, no behavioural impact. 0 findings in both briefs; the real reports are in received/ at 20 202 and 60 167 bytes (the register's '20 KB/60 KB' matches to the byte). Rename to BRIEF_A.md/BRIEF_B.md + add a review/README.md index |
| `REG-P2-42` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime+hash | EVERY figure reproduced exactly: the 39->76->89->113->167->187->187 manifest sequence; PRE_AUDIT2_SOURCE_SHA256.txt byte-identical to SOURCE_SHA256.txt (sha256 b1a9c20e...) and so are its TEST_SUMMARY/VALIDATION/SNAPSHOT twins - FOUR duplicated pairs, not two; 3 of the 39 baseline entries no longer exist; git ls-files android -> 0; 193 untracked files, 3 289 905 bytes. ALIAS (important): register P2-42 == the MAIN audit's PROSE P2-42 (A-10, :1980/:2082, :2338); the MAIN audit's SECTION 5.1 HEADING P2-42 is a DIFFERENT defect (second PKCE start) |
| `REG-P2-43` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | CONFIRMED: the audit's three figures reproduce EXACTLY (0.857 / 0.929 / 0.967) in an independent scratch JDK-21 program, with the raw window lengths 144.0 h and 168.0 h. With an unchanged habit the app reports -14.3% at 00:00, drifting to 0% by 23:59. One correction: the prose says the previous period starts at 'today-2N days'; the code uses firstDate.minusDays(dayCount) = today-(2N-1) (for WEEK: today-13, not today-14) - the figures are unaffected because the previous window is N days long either way |
| `REG-P2-44` | P2 | **CONFIRMED-RUNTIME** | P2 | HIGH | runtime | CONFIRMED by EXECUTING the actual DAO query against a throwaway SQLite DB: the Android query returns 3 rows (the weeknd / Unknown Artist / The Weeknd) where the desktop's GROUP BY LOWER(t.artist) returns 1 row. The desktop groups case-insensitively in BOTH report implementations and excludes the pseudo-artist; the app is internally inconsistent (DiscoveryEngine.kt:28 lowercases the artist). GROUP BY name uses SQLite's default BINARY collation; COLLATE NOCASE appears only in the ORDER BY |
| `REG-P2-45` | P2 | **CONFIRMED-STATIC** | P2 | HIGH | static | FOUR divergences confirmed (not three): not_played_days, unplayed, most_played/least_played, and downloaded - the last is the worst because the importer never selects is_downloaded, so an imported 'downloaded: true' playlist is PERMANENTLY EMPTY. The desktop's begin_listening_session (core/database.py:975-984) writes a zero-duration row with listening_measured=1 and bumps play_count/last_played - and that row is then ERASED on import at DesktopLibraryConverter.kt:60, so the desktop's evidence of 'played' is lost too: the divergence is not reinterpreted but erased |
| `UNNUMBERED-R1-2-P1` | P1 | **CONFIRMED-STATIC** | P2 | HIGH | bytecode+static | THE UNNAMED P1 CARRIED ONLY BY REMEDIATION_PLAN R1.2 ('Never build a queue item by hand in the UI layer'). CONFIRMED by bytecode: ui/MusicViewModel.kt:197 (removeDownload) and :215 (attachLocalFile) both call player.replaceMediaItem(index, MediaItem.Builder().setMediaId(id).build()) - no URI, no MediaMetadata. MediaSession.Callback in 1.11.1 has NO onReplaceMediaItems, so MediaSessionStub.replaceMediaItem goes straight to PlayerWrapper.replaceMediaItem and the hand-built item is applied to the session's player AS-IS. MediaItem.Builder.build() leaves localConfiguration null without a URI, and DefaultMediaSourceFactory.createMediaSource does Preconditions.checkNotNull(mediaItem.localConfiguration) -> NPE; the app's own OfflineSources.createMediaSource takes the elvis branch (localConfiguration?.tag as? OfflineAsset ?: return online.createMediaSource(item)) so it does not intercept it. SEVERITY P1 -> P2: the NPE is caught by ExoPlayer and surfaces as a generic PlaybackException snackbar ('Не удалось воспроизвести трек...'), it is recoverable by re-queuing or by a service restart, and the library/DB state stays correct. TWO CORRECTIONS to the plan: (a) 'permanent for that queue slot' is right for attachLocalFile (it writes only tracks.localUri, so neither the offline_downloads nor the offline-preference trigger fires and refreshQueueSources never runs) but NOT across a service restart (the restore path rebuilds the queue); for removeDownload the reconcile DOES fire if the removed download was in the 'complete' state, and only when an in-progress download was cancelled does the item persist. (b) The plan omits that the replace hits EVERY queue slot with that mediaId, and that the user first sees a FALSE SUCCESS snackbar ('Аудиофайл связан с треком') and only then the generic failure |
