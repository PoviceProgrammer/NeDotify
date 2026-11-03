# Independent multi-agent verification of the NeDotify / AURA Music audit

**Verifier role:** Principal Software Engineer / Independent Software Auditor /
Senior Android Engineer / Security Researcher / QA Architect.
**Subject:** the original audit set in `docs/audits/` — principally
`FULL_PROJECT_AUDIT.md` and `ANDROID_FINDINGS_REGISTER.md`, which audit the
`android/` Kotlin port and use the Windows Python desktop app as a parity
oracle.
**Mode:** read-only verification + documentation. **No production code was
modified.**

---

## 0. Snapshot anchor

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

## 1. Method

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

## 2. What the arbiter verified first-hand (not delegated)

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

## 3. Artifacts produced

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
