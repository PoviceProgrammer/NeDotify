## AREA WN-34 — Test suite — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `docs/audits/WIN_AUDIT_CONTEXT.md:1-200`, `docs/audits/WIN_AUDIT_AREAS.md:1-70`
- `AGENTS.md` (injected by harness), `.claude/skills/nedotify-test/SKILL.md:1-82`
- `pytest.ini:1-5`, `run_tests.py:1-12`, `requirements-dev.txt:1-3`
- `tests/conftest.py:1-176`
- Full read: `tests/test_emit_thread_safety.py:1-168`, `tests/test_keybind_contracts.py:1-204`,
  `tests/test_queue.py:1-109`, `tests/test_engine_notify.py:1-551`, `tests/test_engine_resolve.py:1-1137`,
  `tests/test_playback_recovery.py:1-119`, `tests/test_player_recovery_transitions.py:1-246`,
  `tests/test_playback_startup_performance.py:1-119`, `tests/test_download_integrity.py:1-147`,
  `tests/test_download_resume.py:1-386`, `tests/test_download_retry.py:1-128`,
  `tests/test_downloader_cancel.py:1-405`, `tests/test_downloader.py:1-95`,
  `tests/test_database.py:1-38`, `tests/test_db_integrity.py:1-327`,
  `tests/test_db_core_fixes_f2.py:1-120`, `tests/test_conftest_home_isolation.py:1-174`,
  `tests/test_android_source_gates.py:1-75`, `tests/test_repo_hygiene.py:1-132`,
  `tests/test_frontend_js.py:1-318`, `tests/test_frontend_css_wiring.py:1-184`,
  `tests/test_visual_guard_css_decls.py:1-570`, `tests/test_visual_guard_diff.py:1-133`,
  `tests/test_proxy_security.py:1-204`, `tests/test_proxy_url_validation.py:1-172`,
  `tests/test_proxy_harness.py:1-215`, `tests/test_proxy_paths.py:140-178`,
  `tests/test_offline_proxy.py:1-27`, `tests/test_resolver_state.py:1-249`,
  `tests/test_resolve_fallback_budget.py:1-98`, `tests/test_lazy_service_deadlock.py:1-102`,
  `tests/test_provider_loading.py:1-209`, `tests/test_provider_performance.py:1-102`,
  `tests/test_itunes_request_queue.py:1-69`, `tests/test_lyrics_performance.py:1-342`,
  `tests/test_cache_performance.py:1-131`, `tests/test_auto_save_favorites.py:1-161`,
  `tests/test_flow_ui.py:1-140`, `tests/test_zapret_binary_integrity.py:40-109`,
  `tests/test_media_guard_f3.py:1-45`, `tests/benchmark_lyrics_cache.py:1-40`
- Callee/product files traced into other areas: `core/api.py:29,1110-1159` (WN-03),
  `core/app.py:44,96-101,190-280,457-484` (WN-02), `core/downloader.py:55-94,375-424,437-484,625-694,789,880-909` (WN-13),
  `core/database.py:151-162` (WN-12), `services/itunes_gateway.py:15-93` (WN-21),
  `services/zapret_service.py:321` (WN-26), `ui/web_new_v2/js/player.js:1734,2241-2244,2358,2474,2513` (WN-29),
  `main.py:97-123` (WN-01).

**Callees traced into other areas**: WN-03 (`core/api.py::_emit`), WN-02 (`core/app.py::_service_lock`,
`_SC_FALLBACK_BUDGET_S`), WN-13 (`core/downloader.py`), WN-12 (`core/database.py`),
WN-21 (`services/itunes_gateway.py`), WN-26 (`services/zapret_service.py`), WN-29 (`js/player.js`),
WN-01 (`main.py` logging bootstrap).

**Tooling used**: pytest 9.1.1 (only plugin installed: `pytest-asyncio`; **no `pytest-timeout`**),
Node v24.19.0 present, git present, PowerShell present, `android/` tree present.

**Temporary probe scripts written to `%TEMP%\opencode` only** (no repo file was modified):
`probe_emit.py`, `probe_pollution.py`, `neuter_emit.py`, `probe_nolock_runner.py`, `probe_dom_stub.py`,
`probe_android_absent.py`, `watch_real_home.py`, `watch_stub.py`, `watch_expanduser.py`,
`classify_tests3.py`, `scan_antipatterns.py`, `coverage_map.py`.

---

### 2. Findings

#### F-WN-34-1  [P1] — The suite is RED on a clean tree: 11 failures, all from one incomplete DOM stub in the Node harness

- **File:** `tests/test_flow_ui.py:49`, `tests/test_player_resources.py:43` (the `HARNESS` consumed by `tests/test_player_recovery_transitions.py:1`), `ui/web_new_v2/js/player.js:2244` and `:2358`
- **Confirmed:** yes
- **Description:** The two Node harnesses build a fake `document` whose `documentElement` has **no `dataset` property**. The product reads `document.documentElement.dataset.progressStyle` (unguarded, no `?.`). Every test that reaches `onTrackChanged` → `fetchAndRenderWaveform` dies with `TypeError: Cannot read properties of undefined (reading 'progressStyle')`. 11 tests fail on every run.
- **Cause:** The test stub drifted from the product. A real browser always exposes `dataset` on `HTMLElement`; the stub does not, so the product line is safe in production but fatal in the harness. Nothing in the suite guards the stub against product changes of this kind.
- **Trigger conditions:** Any run of `pytest` at the repo root. Always.
- **User impact:** `pytest` exits 1. Per `.claude/skills/nedotify-test/SKILL.md` ("A backend change is not done until the relevant suite passes") no change can be signed off; CI would be permanently red, and the 11 tests provide zero signal because they fail before their assertions run.
- **Evidence:**
  - `tests/test_flow_ui.py:49` — `documentElement: {classList, getAttribute: () => null, style: {setProperty() {}}}, body: {classList}},`
  - `tests/test_player_resources.py:43` — `documentElement: {classList, getAttribute() {return null}, style: {setProperty() {}}}, body: {classList}},`
  - `ui/web_new_v2/js/player.js:2244` — `const style = document.documentElement.dataset.progressStyle || 'bars';`
  - `ui/web_new_v2/js/player.js:2513` — `document.documentElement.dataset?.uiStyle === 'macos';`  ← the *same file* uses optional chaining at 2513 but not at 2244/2358, so the two call sites disagree about whether `dataset` may be absent.
  - Real pytest output: `TypeError: Cannot read properties of undefined (reading 'progressStyle') at fetchAndRenderWaveform (evalmachine.<anonymous>:2244:52) at Object.onTrackChanged (evalmachine.<anonymous>:1734:5)`
- **Reproduction / verification:**
  ```
  & ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider --tb=no -rs
  → 11 failed, 1491 passed, 1 skipped, 3 xfailed in 82.04s
  ```
  Failing node ids (exact):
  `tests/test_flow_ui.py::test_immediate_flow_coalesces_and_filters_duplicates_in_the_same_response`
  `tests/test_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[track|seed_mutation|queue_event|queue_without_event|flow_toggle]`
  `tests/test_flow_ui.py::test_ended_flow_joins_periodic_fetch_and_advances_after_completion`
  `tests/test_flow_ui.py::test_failed_fetch_or_append_does_not_suppress_the_next_attempt`
  `tests/test_player_recovery_transitions.py::test_crossfade_waits_for_ready_media_then_advances_once_and_releases_outgoing`
  `tests/test_player_recovery_transitions.py::test_gapless_starts_preloaded_audio_before_bridge_and_adopts_fresh_session`
  `tests/test_player_recovery_transitions.py::test_seek_finishes_crossfade_and_cancels_outgoing_audio`
  Node probe (`%TEMP%\opencode\probe_dom_stub.py`): stub **as shipped** → `node rc = 1` (TypeError); stub **+ `dataset: {}`** → `node rc = 0`, `OK style=bars`. Root cause is the stub, not the product.
- **Suggested fix:** Add `dataset: {}` to the `documentElement` stub in `tests/test_flow_ui.py:49` and `tests/test_player_resources.py:43` (and to the other `documentElement` stubs at `tests/test_feature_controls_ui.py:37`, `tests/test_settings_controls_ui.py:21`, `tests/test_settings_palette_ui.py:19`, `tests/test_visual_effects_lifecycle.py:76` for the same reason). Separately, consider `document.documentElement.dataset?.progressStyle` at `player.js:2244/2358` so the product tolerates a stub — but that is a WN-29 change, not a test change.
- **Fix side effects:** Low. Adding `dataset` may surface *new* failures in the 11 tests, because they currently abort before their real assertions — that is the point, but the blast radius should be expected.
- **Discovered by:** A

---

#### F-WN-34-2  [P1] — Contract #1 (`_emit` must never run on the UI thread) is NOT pinned: the whole file passes with the branch deleted

- **File:** `tests/test_emit_thread_safety.py:17,44-69`; production `core/api.py:29` and `core/api.py:1147-1154`
- **Confirmed:** yes
- **Description:** `AGENTS.md` states "Keep that branch — `tests/test_emit_thread_safety.py` pins it". It does not. The test monkeypatches the **test module's** copy of `_MAIN_THREAD`, not `core.api`'s module global, so `core.api._emit` never sees the patched value and always takes the *synchronous* path. The assertions ("did not block", "evaluate_js was scheduled") are both satisfied by that synchronous path.
- **Cause:** `from core.api import AppApi, _MAIN_THREAD` (line 17) binds the *value*; `global _MAIN_THREAD` (line 56) rebinds the *test module's* name. `core/api.py:29` keeps its own `_MAIN_THREAD = threading.main_thread()`, so `threading.current_thread() is _MAIN_THREAD` at `core/api.py:1147` is always False in the test.
- **Trigger conditions:** Any change to `core/api.py:1147-1154` — including deleting the whole UI-thread handoff — is invisible to the suite.
- **User impact:** The exact regression the file was written for (UI-thread deadlock freezing the window, `track_changed` never reaching the frontend) can be reintroduced silently; the green suite would say nothing.
- **Evidence:**
  - `tests/test_emit_thread_safety.py:17` — `from core.api import AppApi, _MAIN_THREAD`
  - `tests/test_emit_thread_safety.py:56-62` — `global _MAIN_THREAD` / `_MAIN_THREAD = threading.current_thread()` … `finally: _MAIN_THREAD = original`
  - `core/api.py:1147` — `if threading.current_thread() is _MAIN_THREAD:`
  - Probe output (`%TEMP%\opencode\probe_emit.py`): inside the test body, `test-module _MAIN_THREAD now = <Thread(FakeUIThread…)>` but `core.api._MAIN_THREAD = <_MainThread(MainThread…)>`, `current thread is api's? = False`.
- **Reproduction / verification:**
  ```
  # neuter_emit.py replaces AppApi._emit with a copy that has the UI-thread branch REMOVED
  $env:PYTHONPATH="<temp>"; & ".venv_win\Scripts\python.exe" -m pytest -p no:cacheprovider -p neuter_emit tests/test_emit_thread_safety.py -v
  → 9 passed in 0.09s
  ```
  All nine tests pass with the contract branch removed.
- **Suggested fix:** Patch `core.api._MAIN_THREAD` (the module attribute), not the imported name — e.g. `monkeypatch.setattr(core.api, "_MAIN_THREAD", threading.current_thread())` — and assert that the emission happened on a *different* thread than the caller (the branch hands off to a `EmitWorker` thread); today no assertion distinguishes the two paths.
- **Fix side effects:** A correct version of the test will actually exercise the handoff; the `evaluate_js` call then becomes asynchronous, so the "worker thread runs inline" test and the "unserializable payload" test may need to wait for the worker.
- **Discovered by:** A

---

#### F-WN-34-3  [P1] — The suite writes into the user's REAL `~/.nedotify/downloads/` (contract #3 violated by the tests themselves)

- **File:** `tests/conftest.py:115-129` (the `downloader` fixture), `tests/conftest.py:52-61` (`ServiceStub.download_audio_sync`), `core/downloader.py:789`
- **Confirmed:** yes
- **Description:** `redirect_home` is opt-in and is **not** applied by the `downloader` / `api` / `core_ns` fixtures. `core/downloader.py:789` computes the target directory at call time from the *current* `os.path.expanduser('~')`. Any test that lets a download worker run without `redirect_home` therefore writes into the user's real library. This has already happened — twice, in two different runs.
- **Cause:** The isolation mechanism is a per-test opt-in fixture rather than an autouse one, so the default is "writes to the real profile" and only the tests that remembered `redirect_home` are safe.
- **Trigger conditions:** A download worker reaching line 789 while no `redirect_home` monkeypatch is installed — which happens when a test queues a download without `redirect_home` (`tests/test_downloader.py:10,16,28,37`; `tests/test_api_download.py:26,33,41,51`), or when a worker thread is still alive after the `redirect_home` fixture is torn down (fixture teardown order is reverse of setup: `redirect_home` is undone **before** `downloader.stop()` runs).
- **User impact:** Test junk in the user's music library (`stub_1.mp3`, `gated_*.mp3`). A `stub_1.mp3` / `gated_N.mp3` file in `~/.nedotify/downloads` is a bogus "downloaded track" that the app will show in the library.
- **Evidence:** physical artefacts in the real profile, with the exact payloads the test stubs write:
  ```
  C:\Users\Артур\.nedotify\downloads\stub_1.mp3     8207 bytes  20.10.2026 22:24:33
  C:\Users\Артур\.nedotify\downloads\gated_3..7.mp3   16 bytes    03.10.2026 10:47:36
  C:\Users\Артур\.nedotify\downloads\gated_8..12.mp3  16 bytes    03.10.2026 10:48:24
  ```
  `tests/conftest.py:58-60` — `fp = os.path.join(download_dir, "stub_%d.mp3" % self.n)` / `f.write(b"ID3\x00\x01stub-audio" + b"\x00" * 8192)` → exactly 8207 bytes.
  `tests/test_downloader_cancel.py:45` — `fp = os.path.join(download_dir, "gated_%d.mp3" % n)` → exactly the `gated_*` names.
  `core/downloader.py:789` — `download_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'downloads')`
- **Reproduction / verification:**
  1. Run the suite once (any `pytest` invocation) and watch `C:\Users\<user>\.nedotify\downloads` — a `stub_1.mp3` with mtime = run time appears (reproduced at 22:24:33 during this review; the run is racy, so it does not reproduce on every run).
  2. Instrumented probe `%TEMP%\opencode\watch_expanduser.py` shows `expanduser('~')` resolving to the **real** home (`C:\Users\Артур`) with no `redirect_home` active in `tests/test_auto_save_favorites.py::test_streaming_track_is_cached_then_queued` and in eight `tests/test_zapret_binary_integrity.py` tests (`ZapretService.__init__` sets `self.logs_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "logs")`, `services/zapret_service.py:321`; the fixture at `tests/test_zapret_binary_integrity.py:48-54` patches `app_dir` but **not** `logs_dir`).
  3. `tests/test_conftest_home_isolation.py` — the file that is supposed to prove isolation — only exercises the fixture's own `expanduser` patch; it never asserts that a test's file writes stay out of the real profile.
- **Suggested fix:** Make `redirect_home` **autouse** in `tests/conftest.py` (or at minimum make the `downloader` fixture depend on it), and add a session-scoped guard that fails the run if any file is created under the real `~/.nedotify` — the same shape as `tests/test_conftest_home_isolation.py` but for the *dangerous* case. Also patch `logs_dir` in the zapret fixture.
- **Fix side effects:** Tests that deliberately assert on the real home (e.g. `tests/test_auto_save_favorites.py:99` uses `monkeypatch.setenv("USERPROFILE", …)`, which is unaffected by `expanduser` patching on Windows only because `ntpath.expanduser` prefers `USERPROFILE`) may need adjusting.
- **Discovered by:** A

---

#### F-WN-34-4  [P2] — Cross-test `sys.modules` pollution: a stub module stays installed for the rest of the session

- **File:** `tests/test_lazy_service_deadlock.py:83`
- **Confirmed:** yes
- **Description:** `test_concurrent_lazy_access_all_succeed` installs a stub `services.soundcloud_service` with a **plain assignment** into `sys.modules`, so it is never restored. Every later test in the same pytest process that imports `services.soundcloud_service` gets the stub instead of the real module. The suite already knows about this and works around it.
- **Cause:** `monkeypatch.setitem(sys.modules, …)` is used correctly two lines earlier (line 51/52 in the other test) but not here.
- **Trigger conditions:** Any pytest run that includes this file — i.e. always. The stub is installed *before* `tests/test_proxy_url_validation.py` runs (alphabetically `l` < `p`).
- **User impact:** Order-dependent test behaviour: a later test can silently exercise a fake provider instead of the real one. The workaround already in the tree is a maintenance trap.
- **Evidence:**
  - `tests/test_lazy_service_deadlock.py:83` — `sys.modules["services.soundcloud_service"] = sc_mod`
  - `tests/test_proxy_url_validation.py:76-84` — *"`tests/test_lazy_service_deadlock.py` replaces sys.modules entries with stand-in modules **and one of them assigns into sys.modules WITHOUT restoring it** … Importing normally can therefore hand back a stub whose class has no `_session`."*
- **Reproduction / verification:**
  ```
  # %TEMP%\opencode\probe_pollution.py
  pytest.main(["-q","-p","no:cacheprovider","tests/test_lazy_service_deadlock.py"])
  → 3 passed
  sys.modules['services.soundcloud_service'] = <module 'services.soundcloud_service'>
    is stub (no _session attr on class)? True
    module file = None
  later import got: <class 'tests.test_lazy_service_deadlock.…SoundCloudService'> from None
  later import has _session attr: False
  ```
- **Suggested fix:** Use `monkeypatch.setitem(sys.modules, "services.soundcloud_service", sc_mod)` (as the sibling test already does) so the entry is removed on teardown; then `tests/test_proxy_url_validation.py::_real_module` can be simplified back to a normal import.
- **Fix side effects:** Low. Removing the workaround in `test_proxy_url_validation.py` may expose latent assumptions in that file.
- **Discovered by:** A

---

#### F-WN-34-5  [P2] — `test_service_lock_is_reentrant` is vacuous: the reentrant-lock contract is not pinned

- **File:** `tests/test_lazy_service_deadlock.py:15-19`; production `core/app.py:96-101`
- **Confirmed:** yes
- **Description:** The test asserts on objects it constructs itself, never on `AppCore`'s actual lock. `assert isinstance(AppCore.__init__.__doc__ or "", (str, type(None)))` is true for every possible docstring; `core._service_lock = threading.RLock()` then asserts `isinstance(core._service_lock, type(threading.RLock()))` — a tautology. If production swapped `threading.RLock()` for `threading.Lock()` (the exact self-deadlock the file is about), the test still passes.
- **Cause:** The test builds a stand-in for the production object instead of inspecting it.
- **Trigger conditions:** Any regression of `core/app.py:101`.
- **User impact:** The documented deadlock (`recommendations` → `soundcloud` under a non-reentrant lock) can return unnoticed; `AGENTS.md` calls this out as one of the three rules that outlive the details.
- **Evidence:**
  - `tests/test_lazy_service_deadlock.py:15-19` — `assert isinstance(AppCore.__init__.__doc__ or "", (str, type(None)))` / `core._service_lock = threading.RLock()` / `assert isinstance(core._service_lock, type(threading.RLock()))`
  - `core/app.py:101` — `self._service_lock = threading.RLock()`
- **Reproduction / verification:** probe `%TEMP%\opencode\probe_nolock_runner.py` forces production to install a **non-reentrant** `threading.Lock`:
  ```
  [probe] core/app.py will now install a NON-reentrant Lock
  tests\test_lazy_service_deadlock.py ...  [100%]
  3 passed in 0.03s
  ```
- **Suggested fix:** Assert on the real thing — e.g. `AppCore.__new__(AppCore)` with the production `__init__` run, or at minimum `assert isinstance(type(AppCore.__init__).__call__, object)` and a direct check that a nested acquisition of the *production* lock succeeds. The docstring assertion should be deleted (it asserts nothing).
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-6  [P2] — `test_resolve_fallback_budget.py` re-implements the cascade inside the test and asserts on its own fake

- **File:** `tests/test_resolve_fallback_budget.py:41-67` and `:77-98`
- **Confirmed:** yes
- **Description:** Two of the four tests never call production code. `test_silent_provider_does_not_recurse_forever` defines `FakeApp._on_err_impl` **inside the test** and then asserts `calls >= 0` (always true) — the production `_on_err_impl` in `core/app.py` is never invoked. `test_cascade_reports_error_to_ui` re-implements the "budget check first, then advance" loop as inline Python and asserts `errors == ["exhausted"]` — a property of the test's own loop.
- **Cause:** The budget cascade in `core/app.py:457-484` was mirrored rather than driven.
- **Trigger conditions:** Always. These two tests cannot fail for any production change.
- **User impact:** The "SoundCloud unreachable → permanent loading spinner" regression (the file's stated purpose) has **no effective coverage**; the two remaining tests only assert that `_SC_FALLBACK_BUDGET_S` is a float in a range.
- **Evidence:**
  - `tests/test_resolve_fallback_budget.py:49-60` — `def _on_err_impl(self, candidates, on_error, source_id):` defined *inside* `FakeApp` in the test
  - `tests/test_resolve_fallback_budget.py:66` — `assert calls >= 0`
  - `tests/test_resolve_fallback_budget.py:90-96` — `# Mirror the shipped guard structure: budget check first, then advance.` / `while not finished:` … `errors.append("exhausted")`
  - `tests/test_resolve_fallback_budget.py:97` — `assert errors == ["exhausted"]`
  - production: `core/app.py:457` `if idx >= len(candidates) or elapsed > _SC_FALLBACK_BUDGET_S:` — never called by the file.
- **Reproduction / verification:** Static reading is sufficient; `grep -n "_on_err_impl" tests/test_resolve_fallback_budget.py` shows the only definition is the test-local `FakeApp` one. The production symbol `AppCore._on_err_impl` is never referenced.
- **Suggested fix:** Drive `AppCore._on_err_impl` (or whichever real method owns the cascade) with a silent provider stub and assert the number of provider attempts is bounded by the budget and that `on_error` fires exactly once. Then delete the two in-test re-implementations.
- **Fix side effects:** Medium — the real method may need its own dependency seams, which is a WN-02 change.
- **Discovered by:** A

---

#### F-WN-34-7  [P2] — `tests/test_android_source_gates.py` gates the ANDROID tree inside the Windows suite and hard-fails when `android/` is absent

- **File:** `tests/test_android_source_gates.py:11-12,36-44,70-75`
- **Confirmed:** yes
- **Description:** The Windows pytest suite (`pytest.ini: testpaths = tests`) contains a file whose only purpose is to exercise the **Android** PowerShell snapshot tooling (`android/tools/SourceSnapshot.ps1`, `android/tools/SourceTasks.ps1`). It is misplaced: the Android port has its own tree and its own gates, and this run's brief explicitly excludes `android/`. Worse, the skip condition only covers a missing PowerShell — **not** a missing `android/` tree — so on a Windows-only checkout (release branch, source-only export, CI image without the Android subtree) the four `test_snapshot_rejects_membership_and_content_drift` cases fail instead of skipping.
- **Cause:** `pytestmark = pytest.mark.skipif(not POWERSHELL, …)` guards the interpreter but not the subject under test.
- **Trigger conditions:** Any checkout of the Windows product without the `android/` subtree.
- **User impact:** The Windows suite goes red for a reason that has nothing to do with the Windows product; the gate is silently absent in the environment where it is needed.
- **Evidence:**
  - `tests/test_android_source_gates.py:12` — `pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")`
  - `tests/test_android_source_gates.py:13` — `ANDROID = Path(__file__).resolve().parents[1] / "android"`
  - `tests/test_android_source_gates.py:44` — `assert create.returncode == 0, create.stdout + create.stderr`
- **Reproduction / verification:** probe `%TEMP%\opencode\probe_android_absent.py` runs the exact PowerShell command against a non-existent tree:
  ```
  returncode: 1
  stderr: . : The term '…\no_such_android_tree\tools\SourceSnapshot.ps1' is not recognized as the name of a cmdlet …
  ```
  → `assert create.returncode == 0` fails. (The `SourceTasks` variant asserts `returncode != 0`, so it would pass — for the wrong reason.)
- **Suggested fix:** Either move this file into the Android tree's own test setup, or add `pytest.mark.skipif(not (ANDROID / "tools" / "SourceSnapshot.ps1").exists(), reason="android tree absent")` so the Windows suite degrades gracefully.
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-8  [P2] — The `network` marker is declared and deselected but never used; the documented opt-in mechanism is dead

- **File:** `pytest.ini:3-5`; `.claude/skills/nedotify-test/SKILL.md:21-23`
- **Confirmed:** yes
- **Description:** `pytest.ini` declares a `network` marker and deselects it by default, and the skill file documents "Tests marked `network` are **deselected by default** and hit live providers (YouTube, SoundCloud, Spotify, Yandex)". **No test in the suite carries the marker** (grep for `pytest.mark.network` → 0 matches). The whole opt-in mechanism is therefore non-functional: `-m network` selects nothing, and `addopts = -m "not network"` excludes nothing.
- **Cause:** The marker was declared but never applied.
- **Trigger conditions:** Always.
- **User impact:** The documented escape hatch ("run the live providers") does not exist, and a future test that *does* perform live I/O and forgets the marker will silently run in the default suite. (Today the suite happens to be hermetic — every `requests.get` / `urlopen` / `requests.Session.get` in `tests/**` is monkeypatched — but that is by convention, not enforced by the marker.)
- **Evidence:**
  - `pytest.ini:3-5` — `markers =` / `network: test performs real network I/O (deselected by default)` / `addopts = -m "not network"`
  - `.claude/skills/nedotify-test/SKILL.md:21-23` — "Tests marked `network` are **deselected by default** … Never mark a new test `network` just to make it pass — mock the provider instead."
  - Grep over `tests/**` for `pytest.mark.network` → **0 matches** (the only `pytest.mark.*` usages are `parametrize`, `skipif`, `xfail`).
- **Reproduction / verification:**
  ```
  & ".venv_win\Scripts\python.exe" -m pytest -m network -q -p no:cacheprovider --collect-only
  → (collects nothing)
  ```
- **Suggested fix:** Either drop the marker and the `addopts` line and correct the skill file, or add a session-scoped autouse guard that fails any test that opens a real socket (the suite already has the building blocks: `tests/test_engine_resolve.py:239-249` monkeypatches `urllib.request.urlopen`).
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-9  [P2] — `test_conftest_home_isolation.py` proves the FIXTURE works, not that the dangerous cases are covered

- **File:** `tests/test_conftest_home_isolation.py:27-134`
- **Confirmed:** yes
- **Description:** The file's docstring claims it is the "Proof that `redirect_home` actually isolates the user profile (H-1)". All twelve tests exercise `home_expander()` in isolation or check `.gitignore`. None asserts that a *test that downloads / writes* stays out of the real profile, and none asserts that the `downloader`/`api`/`core_ns` fixtures are redirected. The dangerous case — the one that actually leaks — is uncovered (see F-WN-34-3).
- **Cause:** The test targets the mechanism, not the observable property.
- **Trigger conditions:** Always.
- **User impact:** A green `test_conftest_home_isolation.py` is currently a false assurance: the suite still writes into the user's library.
- **Evidence:**
  - `tests/test_conftest_home_isolation.py:1-14` — "Proof that ``redirect_home`` actually isolates the user profile (H-1)."
  - `tests/test_conftest_home_isolation.py:110-118` — `test_sandbox_dir_is_actually_usable` writes `probe.bin` **inside the sandbox** and asserts it is not in the real profile; there is no counterpart that exercises a product code path (e.g. `DownloadManager._download_worker`) and checks the real profile afterwards.
- **Reproduction / verification:** Read the file end to end; the only filesystem assertion about the real profile is `assert not os.path.exists(os.path.join(REAL_HOME, ".nedotify", "downloads", "probe.bin"))` (line 118) — about the sandbox's own probe file.
- **Suggested fix:** Add a test that runs a real download through the `downloader` fixture and asserts that no file appeared under `os.path.expanduser("~")/.nedotify/downloads`, plus an autouse session guard that fails the run if anything is created under the real `~/.nedotify`.
- **Fix side effects:** The new test would fail today (that is the point) until F-WN-34-3 is fixed.
- **Discovered by:** A

---

#### F-WN-34-10  [P2] — Contract #7 (`download_complete` carries `{"track_id": …}` and NO `file_path`) is not pinned

- **File:** `tests/test_downloader.py:60`, `tests/test_downloader_cancel.py:220`; production `core/downloader.py` (emit site)
- **Confirmed:** yes
- **Description:** Every assertion on `download_complete` checks only that the event *name* fired. No test inspects the payload. The `download_failed` payload, by contrast, is asserted key-by-key in `tests/test_download_resume.py:191-204` — the asymmetry shows the gap is an oversight, not a policy.
- **Cause:** The event was added before the payload was specified in a test.
- **Trigger conditions:** A change that adds `file_path` to `download_complete` (a real historical failure mode — a large absolute path crossing the bridge) is invisible to the suite.
- **User impact:** The frontend would receive a payload shape it does not expect; per `AGENTS.md` "The failure mode here is silence", that means a silently broken download-to-library flow.
- **Evidence:**
  - `tests/test_downloader.py:59-60` — `kinds = [e for e, _ in emitted]` / `assert "download_complete" in kinds`
  - `tests/test_downloader_cancel.py:220` — `assert "download_complete" in [e for e, _ in emitted]`
  - Contrast `tests/test_download_resume.py:195-204` — `assert payload['track_id'] == 27` / `assert payload['method'] == 'download_track'` / `assert payload['code'] == code` …
- **Reproduction / verification:** Grep `tests/**` for `download_complete` → 5 hits, none of which reads a payload key.
- **Suggested fix:** Assert the payload of `download_complete` explicitly (`track_id` present, `file_path` absent), mirroring `test_download_resume.py:191-204`.
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-11  [P2] — The frontend "wiring" suites are source-text greps: 30 of 31 test functions assert that a string is present in a file

- **File:** `tests/test_frontend_js.py:1-318`, `tests/test_frontend_css_wiring.py:1-184`
- **Confirmed:** yes
- **Description:** `test_frontend_js.py` has 24 test functions; 23 of them read a `.js`/`.py` file as text and assert that a literal string is (or is not) present. Only `test_js_files_parse_as_es_modules` executes anything (it runs `node --check` on a copy). `test_frontend_css_wiring.py` has 7 test functions and **zero** behavioural ones: they all regex the `<link>` tags out of `index.html` and compare them with the `.css` files on disk. A file can be renamed, the assertion renamed with it, or the whole function deleted, and the suite stays green.
- **Cause:** The repo has no webview test harness, and the files were written as source-text checks; the file docstring is honest about it (`test_frontend_js.py:1-8`: "They do NOT prove the UI behaves correctly at runtime").
- **Trigger conditions:** Always.
- **User impact:** The frontend contracts these files claim to protect (event registry, `api_error` handling, stylesheet wiring) are unpinned in the behavioural sense; a rename that keeps the string count equal passes. Note the contrast: `tests/test_visual_guard_css_decls.py` (33 behavioural tests against a synthetic tree) and `tests/test_visual_guard_diff.py` (8 behavioural) show the repo *can* write behavioural frontend-adjacent tests.
- **Evidence:**
  - `tests/test_frontend_js.py:88-90` — `assert '_emit("api_error"' in src` / `assert '"method": method_name' in src` / `assert '"error": f"{type(exc).__name__}: {exc}"' in src`
  - `tests/test_frontend_js.py:102-108` — `match = re.search(r"case 'api_error':\s*\{(.*?)\n\s*\}", events_src, re.S)` … `assert "showToast(" in body`
  - `tests/test_frontend_css_wiring.py:89-107` — `orphans = sorted(p for p in on_disk if p not in linked_css …)` — a set diff over text.
  - `tests/test_frontend_js.py:66` — `pytest.skip("node is not installed; syntax check skipped")` (the only execution-based test skips without node).
- **Reproduction / verification:** Manual classification of every `def test_` in the two files: 23 grep + 1 behavioural in `test_frontend_js.py`; 7 grep + 0 behavioural in `test_frontend_css_wiring.py`. AST cross-check (`%TEMP%\opencode\classify_tests3.py`): suite-wide 658 behavioural / 107 grep / 328 other of 1093 test functions (grep share 9.8%); focus files 42 behavioural / 24 grep / 9 other.
- **Suggested fix:** Replace the string-presence assertions with the pattern the repo already uses elsewhere — a Node `vm` harness that loads the real module and asserts behaviour (as in `tests/test_flow_ui.py`, `tests/test_player_resources.py`, `tests/test_visual_effects_lifecycle.py`). At minimum, keep the greps as *wiring smoke checks* but stop counting them as contract coverage.
- **Fix side effects:** Medium — writing Node harnesses for the 34 ES modules is real work.
- **Discovered by:** A

---

#### F-WN-34-12  [P3] — Two wall-clock thresholds in `test_lyrics_performance.py` will flake on a loaded machine

- **File:** `tests/test_lyrics_performance.py:162`, `:180`
- **Confirmed:** yes
- **Description:** `assert elapsed < .5` (500 ms) on a path that should be a dict lookup. The slow provider it races against is `release.wait(2)`, so the correct path has 4× headroom over the failure threshold — but the *success* threshold is an absolute 500 ms wall-clock bound on a shared CI box.
- **Cause:** Absolute wall-clock budget instead of a deterministic fake clock. The repo already has the right pattern (`tests/test_engine_resolve.py:188-220` `_Clock` / `_FakeTimeModule`).
- **Trigger conditions:** A busy CI runner, an antivirus scan, or a laptop under load.
- **User impact:** Intermittent red builds that mask real regressions.
- **Evidence:**
  - `tests/test_lyrics_performance.py:154-162` — `monkeypatch.setattr(service._lookup, 'netease', lambda *args: release.wait(2) and None)` … `assert elapsed < .5, f'Exact plain text waited on a source that cannot validate timing: {elapsed:.3f}s'`
  - `tests/test_lyrics_performance.py:173-180` — `assert actual['instrumental'] and elapsed < .5`
- **Reproduction / verification:** Read the two tests; the threshold is a literal `.5`. Not observed to flake locally (the whole suite ran in 65–82 s across four runs, all green on this point).
- **Suggested fix:** Use a fake clock (the `_Clock` pattern from `tests/test_engine_resolve.py`) or drive the ordering with an `Event` and assert the *ordering* (the exact result is returned before the slow provider is released) instead of a duration.
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-13  [P3] — `test_backoff_grows` asserts on the test's own arithmetic, not on the product's backoff

- **File:** `tests/test_download_retry.py:81-88`
- **Confirmed:** yes
- **Description:** The test reads `downloader._RETRY_BASE_DELAY` (the only production value it touches) and then computes the doubling itself: `delay *= 2; seen.append(delay)` → `assert seen == [20.0, 40.0, 80.0]`. If the production backoff stopped doubling, this test would still pass.
- **Cause:** The behaviour is re-implemented instead of observed.
- **Trigger conditions:** Always.
- **User impact:** The "the delay backs off and can be cancelled during the wait" contract (the file's own docstring, line 10) is unpinned; only the *base* value 20.0 is pinned.
- **Evidence:** `tests/test_download_retry.py:81-88` — `delay = downloader._RETRY_BASE_DELAY` / `for _ in range(2): delay *= 2; seen.append(delay)` / `assert seen == [20.0, 40.0, 80.0]`
- **Reproduction / verification:** By inspection; no production call is made in the test body.
- **Suggested fix:** Record the sleep durations the product actually requests (monkeypatch `time.sleep`, as `tests/test_download_retry.py:42` already does elsewhere) and assert the recorded sequence is `[20, 40]`.
- **Fix side effects:** Low.
- **Discovered by:** A

---

#### F-WN-34-14  [P3] — No `pytest-timeout`: one hanging test blocks the whole suite indefinitely

- **File:** `requirements-dev.txt:1-3`, `pytest.ini:1-5`
- **Confirmed:** yes
- **Description:** The dev requirements pin only `pytest` and `pytest-asyncio`. The installed plugin list is `plugins: asyncio-1.4.0` only. There is no per-test timeout, so any test that blocks (the suite has many real threads, real sockets and `Event.wait()` calls) hangs the run forever instead of failing.
- **Cause:** Timeout guard never added.
- **Trigger conditions:** Any deadlock regression in a threaded test.
- **User impact:** CI can hang instead of reporting a failure; the reviewer/agent cannot tell a hang from a slow run.
- **Evidence:** `requirements-dev.txt:1-3` — `pytest==9.1.1` / `pytest-asyncio==1.4.0`; pytest banner — `plugins: asyncio-1.4.0`.
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -m pytest --version` → `pytest-9.1.1, pluggy-1.6.0` with `plugins: asyncio-1.4.0` only.
- **Suggested fix:** Add `pytest-timeout` and `addopts = --timeout=120` (or a per-file marker for the socket tests).
- **Fix side effects:** Low, but the timeout must be generous enough for `tests/test_provider_performance.py` / `tests/test_downloader_cancel.py` (which use 20 s waits).
- **Discovered by:** A

---

#### F-WN-34-15  [P3] — Twelve product modules have no test file at all, including two that carry documented contracts

- **File:** `services/yandex_service.py`, `core/plugins.py`, `core/session.py`, `core/services/discord_rpc.py`, `core/services/recommendation.py`, `core/download_store.py`, `services/artist_service.py`, `services/audio_fingerprint_service.py`, `services/lastfm_service.py`, `services/playlist_import_service.py`, `services/vk_service.py`, `services/watchdog_service.py`
- **Confirmed:** yes
- **Description:** No test file imports these modules. Two of them carry contracts from the brief:
  - **Contract #8** — "`services/yandex_service.py` still builds `ya_<raw_id>_<ts>.mp3` from an unsanitised id — documented, not enforced." There is no test file for `services/yandex_service.py` at all, so the Windows-illegal-character failure mode is unpinned on the product side.
  - **Contract #10** — "The plugin folder is never added to `sys.path`." `core/plugins.py` has no test; the opt-in plugin loader (WN-02) is completely uncovered.
  Also uncovered: `core/session.py` (session persist/restore — WN-02 / WX-07), `core/services/discord_rpc.py` (WN-26), `core/download_store.py` (covered only indirectly through `core/downloader.py`).
- **Cause:** Test coverage was built around the features that had regressions, not around the module inventory.
- **Trigger conditions:** Always.
- **User impact:** The areas listed in §4 have no regression net.
- **Evidence:** automated import map (`%TEMP%\opencode\coverage_map.py`) — 38 of 81 product modules have no direct test import; 12 of those are product (non-`tools/`) modules.
- **Suggested fix:** Add at least a smoke/contract test per uncovered module, starting with `core/plugins.py` (contract #10: assert the plugin folder is not on `sys.path` after a plugin load) and `core/session.py` (save → restart → restore round trip).
- **Fix side effects:** Low.
- **Discovered by:** A

---

### 3. Clean areas

- **`tests/test_keybind_contracts.py` — contract #5 is genuinely pinned.** It parses the **frontend** table with a regex over `hotkeys.js` and the **backend** table with a real `ast` walk of `core/settings.py`, then asserts the id sets are equal (`test_backend_ids_are_exactly_the_frontend_ids`), the values are equal (`test_backend_values_match_frontend_defaults`), the legacy `mute` id is absent, there is exactly one dispatcher (`test_no_duplicate_hotkey_dispatcher`) and every default id has a `case` branch (`test_every_default_keybind_has_a_dispatcher_branch`). It also compiles the real `formatKeyName` out of `settings.js` with Node (`_format_key_name`). This is the model the other "wiring" tests should follow.
- **`tests/test_engine_notify.py` (42 tests) and `tests/test_engine_resolve.py` (71 tests)** are exemplary behavioural suites: in-process stubs, synchronous callbacks, exact URL string comparison, a fake monotonic clock for the cascade budget, and an autouse `urlopen` blocker. `test_engine_resolve.py` even pins known product bugs as **strict** `xfail`s (`tests/test_engine_resolve.py:528-544`, `:1083-1097`), which is the right way to keep a bug from being forgotten.
- **`tests/test_queue.py`, `tests/test_playback_recovery.py`, `tests/test_resolver_state.py`, `tests/test_db_integrity.py`, `tests/test_proxy_security.py`, `tests/test_proxy_url_validation.py`, `tests/test_media_guard_f3.py`, `tests/test_download_integrity.py`, `tests/test_download_resume.py`, `tests/test_downloader_cancel.py`, `tests/test_itunes_request_queue.py`** all exercise production code paths and assert on values, not on source text. `tests/test_resolver_state.py:72-119` is a particularly good pattern (it replaces the lock with a depth-counting wrapper and the stats dict with a write-recording subclass, proving the invariant directly).
- **Vacuity anti-patterns are essentially absent.** AST scan of all 1093 test functions: **0** `assert True`, **0** `except: pass` / `except Exception: pass` inside a test body. 72 test functions contain no Python `assert`, but 60 of those are the Node-harness suites whose assertions live inside the JS payload (`assert.equal(...)` in the `node --input-type=module` script), and the remaining ~12 are legitimate "must not raise" smoke tests (`test_emit_without_window_is_noop`, `test_close_on_memory_db_is_harmless`, `test_close_thread_connection_handles_absent_slot`, `test_no_callback_configured_is_a_noop`, `test_uninstall_without_install_is_safe`).
- **The suite is hermetic with respect to the network.** Every `requests.get` / `requests.Session.get` / `urllib.request.urlopen` in `tests/**` is monkeypatched (`tests/test_download_resume.py:238,257,273,290,309`; `tests/test_engine_resolve.py:248`; `tests/test_hls_playback.py:62`; `tests/test_proxy_ranges.py:42`; `tests/test_offline_resolve_callbacks.py:50`; `tests/test_media_guard_f3.py:176`). No test opens a real outbound connection.
- **The database is always hermetic.** Every `DatabaseManager` in `tests/**` is constructed with an explicit path (`tmp_path`, or `":memory:"`) — `tests/conftest.py:66`, `tests/test_db_integrity.py:313`, `tests/test_db_core_fixes_f2.py:112,129,143,161`, `tests/test_dup_cleanup_migration.py:54,87`, `tests/test_portable_library_identity.py:10,21,29-30`, `tests/test_macos_ui.py:97`. `core/database.py:160-162` (the `~/.nedotify` default) is never reached.
- **`tests/test_repo_hygiene.py` and `tests/test_conftest_home_isolation.py:132-174`** use `git check-ignore --no-index -v` rather than re-implementing the ignore rules, and `test_repo_hygiene.py:49-69` correctly handles the `!` negation case (`setup_pyinstaller.spec`). These are good tests.
- **`tests/test_visual_guard_css_decls.py` (36) and `tests/test_visual_guard_diff.py` (8) are genuinely behavioural** — they build synthetic trees in `tmp_path` and drive the real `tools/visual_guard` code, including a non-vacuity assertion (`test_baseline_comparison_is_not_vacuous`, `tests/test_visual_guard_css_decls.py:151-158`). They are the counter-example to F-WN-34-11.
- **No ordering dependencies found in the DB/filesystem fixtures.** `tmp_db` is function-scoped with a throwaway SQLite file; `redirect_home` is `monkeypatch`-based and auto-undone; `test_conftest_home_isolation.py:90-98` even asserts that restoration is automatic.
- **`pytest.ini` / `run_tests.py` are consistent** — `run_tests.py:1-12` delegates entirely to pytest, so there is one source of truth.

---

### 4. Coverage gaps

**Contract → test coverage table**

| # | Contract (brief §"Non-negotiable rules") | Test file | What it actually asserts | Verdict |
|---|---|---|---|---|
| 1 | `_emit` must never run on the UI thread | `tests/test_emit_thread_safety.py` | Patches the **test module's** `_MAIN_THREAD`; `core.api`'s global is untouched, so the branch is never taken. Asserts only "did not block" + "evaluate_js was scheduled" — both true on the synchronous path. | **MISSING** — proven: 9/9 pass with the branch deleted (F-WN-34-2) |
| 2 | A new shared field joins its class's existing lock | `tests/test_resolver_state.py:72-119` (StreamResolver); `tests/test_lazy_service_deadlock.py:15-19` (AppCore) | Resolver half: real — depth-counting lock + write-recording dict prove `_stats` is only mutated under the lock. AppCore half: **vacuous** — the test constructs its own RLock and asserts on a docstring. `BaseMusicService._cache_lock` discipline: **no test at all**. | **PARTIAL** — StreamResolver REAL; AppCore MISSING; BaseMusicService MISSING (F-WN-34-5) |
| 3 | `~/.nedotify/` is the user's library | `tests/test_conftest_home_isolation.py` | Tests the `expanduser` patch in isolation; never asserts that a test's own writes stay out of the real profile — and the suite **does** write into it. | **WEAK + actively violated** (F-WN-34-3, F-WN-34-9) |
| 4 | WAL is load-bearing in `core/database.py` | `tests/test_db_core_fixes_f2.py:109-160`, `tests/test_db_integrity.py:309-327` | Real: closes a DB with a foreign connection and asserts the `-wal` file exists (checkpoint ran) and that a `:memory:` DB closes without error. | **REAL** |
| 5 | The hotkey table is mirrored (`hotkeys.js` ≡ `core/settings.py`) | `tests/test_keybind_contracts.py` | Real: regex over the JS table + `ast` walk of the Python table, id-set equality, value equality, single dispatcher, per-action dispatch branch, real `formatKeyName` executed under Node. | **REAL (strongest contract in the suite)** |
| 6 | There is no EventSource / SSE / WebSocket channel | — | No test mentions `EventSource`/`WebSocket`. The product currently complies (`grep` over `ui/web_new_v2/**/*.js` → 0 hits), but nothing pins it. | **MISSING** |
| 7 | `download_complete` carries `{"track_id": …}` and **no** `file_path` | `tests/test_downloader.py:60`, `tests/test_downloader_cancel.py:220` | Only asserts the event *name* fired. The payload is never inspected. (`download_failed` **is** asserted key-by-key in `tests/test_download_resume.py:191-204`.) | **WEAK** (F-WN-34-10) |
| 8 | Filename sanitisation (no generic helper; `yandex_service` builds `ya_<raw_id>_<ts>.mp3` from an unsanitised id) | — | No test file for `services/yandex_service.py`; the Windows-illegal-character path is unpinned. | **MISSING** (F-WN-34-15) |
| 9 | Frozen vs source assets (`getattr(sys, "_MEIPASS", …)` on both branches) | `tests/test_proxy_paths.py:148-171`, `tests/test_ui_v2_independence.py:69` | Real: sets and then deletes `sys._MEIPASS` and asserts the cover-root set changes accordingly. | **REAL** (proxy cover roots) |
| 10 | The plugin folder is never added to `sys.path` | — | No test imports `core/plugins.py`. | **MISSING** (F-WN-34-15) |

**Uncovered product modules (no test file imports them)** — `core/session.py`, `core/plugins.py`, `core/download_store.py` (indirect only), `core/services/discord_rpc.py`, `core/services/recommendation.py`, `services/yandex_service.py`, `services/vk_service.py`, `services/lastfm_service.py`, `services/artist_service.py`, `services/playlist_import_service.py`, `services/audio_fingerprint_service.py`, `services/watchdog_service.py`. (`services/lyrics_lookup.py` is exercised only through `services/lyrics_service.py`.)

**Uncovered tooling (area WN-35, noted for the other reviewer)** — none of `tools/bench/**` (21 modules) has a test; `tools/check_lock_nesting.py` and `tools/check_shadow_imports.py` have no test; only `tools/visual_guard/run_guard.py` and `tools/visual_guard/diff.py` are covered.

**Areas with no test at all**: WN-16 `core/tray.py` is imported by two tests but only for a symbol-existence check; `core/snap_layouts.py` is covered by `tests/test_snap_layouts.py` (25 behavioural tests).

**What could not be verified**
- The exact interleaving that produced the real-home write (F-WN-34-3) is racy and did not reproduce on 3 of 4 suite runs; the *artefacts* and the mechanism (`redirect_home` is opt-in, `core/downloader.py:789` resolves `~` at call time) are both confirmed directly.
- I did not run the suite with the `network` marker (there is nothing to select) and did not run any test against a live provider.
- I did not execute the `android/` PowerShell gates against a real Android build; the "absent tree" behaviour was verified by running the same PowerShell command against a non-existent path.
- `pytest-timeout` is not installed, so no run was protected against a hang; all observed runs completed in 65–82 s.
- I did not read every line of every test file (~1093 functions); the detailed read covered the files listed in §1, and the remaining files were covered by AST analysis (vacuity scan, grep/behaviour classification, module→test import map) plus targeted reads.
