# AUDIT_INCONSISTENCIES — internal contradictions of the original audit set

Each row states what the documents claim, where, the classification, and the
most likely cause. Severity here is the severity of the **documentation
defect**, not of the underlying finding.

---

## A. Two conflicting P2 id namespaces inside one document set — the most serious traceability defect

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

## B. Contradictory headline statistics

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

## C. The critical Android finding has no id, and the cross-references to it are broken

| # | Statement | Problem |
|---|---|---|
| C1 | `:51-60` §1 item 2, `:1616-1622` §6 X-01, `:2147-2149` §10.1, `:2268` §11 W1, `:1687-1689` §7, `A-2`, `REMEDIATION_PLAN.md` R1.1 | The finding is referred to as *"the XI-08 B P1"* — an **area-reviewer coordinate**, not a finding id. It is not in §4, not in the register, and has no P1 number. The report simultaneously claims 4 P1s and treats this as a 5th, higher one |
| C2 | `:1616-1617` §6 X-01 — *"its release hook (`MediaSession.Callback.onPlayerCommandRequest` with `COMMAND_PLAY_PAUSE`) is **never reached** by `MediaController.play()`/`pause()` in Media3 1.11.1 — only `setPlayWhenReady` dispatches through that path"* | **Factually wrong** (see `FALSE_POSITIVES.md` FP-1; `javap` on `media3-session-1.11.1.aar`). There is no `COMMAND_SET_PLAY_WHEN_READY` in Media3 1.11.1; `play()`/`pause()` dispatch as `COMMAND_PLAY_PAUSE` |
| C3 | `:1617` §6 X-01 — *"(P1-02 in the register, see §5)"* | **P1-02 is the DataStore-corruption finding**, and §5 contains no P1 at all. The cross-reference resolves to nothing |
| C4 | `:1083` §5.1 P2-11 — *"The second press works (it re-opens the gate via `receivedPlayCommand()`), so the gate is not permanently stuck, but the first press is silently lost"* | **Directly contradicts** §1 item 2 (`:56-58`): *"Once tripped, **every subsequent Play is dropped** … until the user re-picks a track"*. Both statements were shipped; the mechanism, when checked against the bytecode, supports the first and refutes the second |
| C5 | `:781-783` §1 item 4, `:2207` §12 | The report's #1 Android finding (item 2) and the plan's "highest-value single change" (`REMEDIATION_PLAN.md` Appendix A, item 3) rest on the refuted claim in C2 |

---

## D. Counts inside individual findings that do not survive re-measurement

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

## E. Findings that exist only in the remediation plan

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

## F. The "instrumentation compiled but never run" claim — accurate, but counted three ways

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

## G. What the audit *never* claims — verified honest

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

## H. Minor but citable

| # | Where | Problem |
|---|---|---|
| H1 | `:9` §1 — *"This file is a work in progress. It is finalised when the 'Audit complete' marker appears at the end."* vs `:2349` — `<!-- Audit complete -->` | The marker **is** present, so the file is final. No defect, but the two lines read as an unresolved state |
| H2 | `:1764-1767` §7.1 item 2 — the media-header gap is listed under **"Security"** although the report itself calls it *"a **correctness** gap (403 on the first byte) that happens to also be a bot-detection gap"* | Category error: a correctness finding filed as a security finding |
| H3 | `:1877` §7.1 item 7 — the lock-screen title leak is filed under an informal id *(XI-03 B, F-XI03-4)* while every other §7.1 item has a P-id | Inconsistent id scheme inside one list |
| H4 | `:1809-1810` §7.2 — *"`DownloadStorage` first touch (**P3-?** / AN-15 A)"* | A literal `P3-?` placeholder survives in the final document |
| H5 | `:1984-1986` §9 — *"All results below were **observed during this audit**, not read from a prior report."* | True for §9, but §2.3/§2.5 and §5 quote the desktop oracle as "the reference implementation" without a comparable observation statement. Minor asymmetry in the evidence standard between the Android and the desktop halves |
| H6 | `REMEDIATION_PLAN.md:118-123` R1.1 | The remediation plan **restates the refuted Media3 claim verbatim** (*"In Media3 1.11.1 that callback is never invoked for `MediaController.play()`/`pause()`"*) and its acceptance criterion ("the gate must be re-armed from a path the app actually uses") is written against a false premise. Executing the plan as written would produce a fix for a defect that does not exist, while leaving the real one (a silent veto) in place |

---

## I. Additional inconsistencies found by the dedicated document auditor

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
