## AREA WN-35 — Tooling: performance bench & visual guard — ROLE B

### 1. Scope reviewed

**Files opened (path : line ranges actually read)**

- `tools/bench/run_bench.py` : 1–339 (full)
- `tools/bench/scenarios.py` : 1–470 (full)
- `tools/bench/bench_child.py` : 1–437 (full)
- `tools/bench/profile.py` : 1–330 (full)
- `tools/bench/cdp.py` : 1–364 (full)
- `tools/bench/procsampler.py` : 1–194 (full)
- `tools/bench/check_live_providers.py` : 1–149 (full)
- `tools/bench/build_hotspots.py` : 1–30 (header + import block)
- `tools/bench/css_inventory.py` : 1–45 (header)
- `tools/bench/run_pyprof.py` : 1–70 (header + helper map)
- `tools/bench/verify_frontend_report.py` : 1120–1228 (tail: main / run / reporting)
- `tools/bench/pyprof_child.py` : structural grep (all `def`/redirect/`environ`/spawn sites)
- `tools/visual_guard/run_guard.py` : 1–738 (full)
- `tools/visual_guard/capture.py` : 1–140 (full)
- `tools/visual_guard/diff.py` : 1–125 (full)
- `tools/visual_guard/fixtures.py` : 1–339 (full)
- `tools/check_lock_nesting.py` : 1–127 (full)
- `tools/check_shadow_imports.py` : 1–119 (full)
- `.claude/skills/nedotify-perf/SKILL.md` : 1–67 (full)
- `.claude/skills/nedotify-build/SKILL.md` : 1–45 (full)
- `docs/audits/WIN_AUDIT_CONTEXT.md`, `docs/audits/WIN_AUDIT_AREAS.md` : full
- `docs/perf/baseline.md` : 1–146 (full); `docs/perf/prof_frontend.md` : 1–20; `docs/perf/prof_python_startup.md` : 1–25
- `docs/RESOURCE_OPTIMIZATION.md` : 1–60; `docs/PLAYBACK_LYRICS_PERFORMANCE.md` : 1–40
- `.github/workflows/ci.yml` : 1–32 (full); `.github/workflows/android-source.yml` : 1–40; `.gitignore` (full)
- All 20 committed artefacts in `tools/bench/results/*.json` (parsed programmatically), `tools/bench/results/raw/*.json`, `tools/visual_guard/reports/*.json` (parsed)

**Callees traced into other areas** (product defects raised there, not here)

- `core/api.py:2077` `AppApi.search` → provider fan-out (`core/api.py:2100`) — WN-06 / WX-05
- `core/api.py:3315/3740/3765/3782` `get_popular_tracks` / `get_feed` / `get_home_releases` / `get_home_mixes` → `core/services/recommendation.py` — WN-09 / WN-23
- `core/proxy.py:796` `StreamProxyHandler.do_GET` → `app_core.db` / `app_core.cache` / `app_core.engine` — WN-11
- `core/database.py:204` `DatabaseManager.conn` (sqlite3.Connection) — WN-12
- `core/api.py:17/570/579-595` `AppApi._install_snap_layouts` — WN-04 (only cited as evidence for the checker defect)
- `services/lastfm_service.py:23/152/204-208` `API_KEYS` / `_get_session` / `available` — WN-21 / WN-22 (only cited as evidence that the monkey-patch still binds)
- `main.py:549-555` `storage_path` under `expanduser("~")` — WN-01 (cited as evidence that the profile redirect is real)

---

### 2. Findings

#### F-WN-35-1  [P1] — `check_lock_nesting.py` scans only `tools/`, so the AGENTS.md lock rule is checked against the wrong tree and its "OK" is meaningless
- **File:** `tools/check_lock_nesting.py:11`, `tools/check_lock_nesting.py:99-114`
- **Confirmed:** yes
- **Description:** `ROOT = os.path.dirname(os.path.abspath(__file__))` resolves to `<repo>/tools`, not the repository root. `main()` then walks `ROOT` and reports on every `.py` it finds there. The application tree (`main.py`, `core/`, `services/`, `audio/`, `utils/` — 61 files) is never parsed. The script therefore prints "OK: no nested-lock self-deadlock patterns" about the *benchmark harness*, not about the code the rule protects.
- **Cause:** the root was computed with one `dirname` instead of two. The sibling script `check_shadow_imports.py:12` gets it right: `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`.
- **Trigger conditions:** always. The script cannot report anything about `core/`, `services/` or `audio/` regardless of the tree state.
- **User impact:** the AGENTS.md contract *"A new shared field joins its class's existing lock rather than opening a second one"* has a checker that never looks at the code. The three real self-deadlocks the docstring cites (`AppCore._service_lock`, `DiscordRPCService._lock`, the lock across `evaluate_js`) are, by construction, invisible to it — a regression of that class would ship silently.
- **Evidence:**
  ```python
  # tools/check_lock_nesting.py:11
  ROOT = os.path.dirname(os.path.abspath(__file__))
  ```
  ```
  check_lock_nesting.ROOT = C:\...\AURA_Music_main\tools
  files scanned by the checker: 29
      bench\__init__.py, bench\bench_child.py, ... (tools/ only)
  does it scan core/ ? False
  does it scan main.py ? False
  ```
  `& ".venv_win\Scripts\python.exe" tools/check_lock_nesting.py` → `OK: no nested-lock self-deadlock patterns` (exit 0).
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" -c "import os,tools.check_lock_nesting as m;print(m.ROOT);print([p for p in os.listdir(m.ROOT)])"
  ```
  and the 29-vs-61 file count above (app tree re-walked with the same `SKIP` set).
- **Suggested fix:** one extra `dirname` on `ROOT`; add the `tools/` subtree to `SKIP` explicitly; make the script fail (non-zero) when the number of scanned files drops below a floor, so a wrong root cannot masquerade as a clean bill of health.
- **Fix side effects:** once the root is correct the checker will start reporting on the app tree — see F-WN-35-2 for the false positives that will immediately surface; fix the detector before switching the root on.
- **Discovered by:** B

#### F-WN-35-2  [P1] — `locks_taken()` treats every `with self.X:` as a mutex, so the checker reports sqlite transactions as lock nesting
- **File:** `tools/check_lock_nesting.py:18-31`, `tools/check_lock_nesting.py:34-54`
- **Confirmed:** yes
- **Description:** `locks_taken()` returns every `with self.<attr>:` as "a lock taken". `lock_kinds()` builds a map of *actual* `Lock`/`RLock` attributes, but it is used only to *skip* `RLock` — it is never used to *require* that the attribute really is a lock. `with self.conn:` is a `sqlite3.Connection` transaction context manager (commit/rollback), not a mutex.
- **Cause:** the two helpers were written independently and never cross-checked; the "is this a lock?" knowledge lives in `lock_kinds()` and is not consulted by `locks_taken()`.
- **Trigger conditions:** any `with self.<non-lock>:` that encloses a call to a sibling method which also uses the same `with` block.
- **User impact:** if F-WN-35-1 is fixed naively, the checker immediately fires on `core/database.py` — and a real deadlock signal would be lost in the noise. The tool as it stands cannot be trusted either way.
- **Evidence:**
  ```python
  # tools/check_lock_nesting.py:24-30
  if (isinstance(ctx, ast.Attribute) and isinstance(ctx.value, ast.Name)
          and ctx.value.id == "self"):
      out.append((ctx.attr, sub.lineno, sub.end_lineno))
  ```
  ```
  lock_kinds(core/database.py): {'_write_lock': 'RLock', '_conns_lock': 'Lock'}
  detector findings over the app tree: 1
      ('core\\database.py', 'DatabaseManager', 'create_playlist_ex',
       '_cleanup_duplicate_empty_system_playlists', 'conn')
  ```
  The "lock" is `conn`, and `core/database.py:204` is `def conn(self) -> sqlite3.Connection:` — a connection, not a lock. The call at `core/database.py:1882` is `self._cleanup_duplicate_empty_system_playlists(cursor)` — it passes a *cursor* and never re-enters the connection context.
- **Reproduction / verification:** run the detector's `ClassScan` over `core/database.py` with the app-tree walk shown in F-WN-35-1; the single hit above is the output.
- **Suggested fix:** in `locks_taken()`, require `ctx.attr in self.kinds` (i.e. only attributes that `lock_kinds()` proved are `Lock`/`RLock`), and treat everything else as an ordinary context manager.
- **Fix side effects:** narrowing the set will reduce recall; the detector is AST-only and will still miss locks acquired through a local alias or a helper (`with self._lock_for(x):`). Acceptable — a checker that cries wolf is worse than one that is conservative.
- **Discovered by:** B

#### F-WN-35-3  [P1] — The visual guard has zero golden baselines; the pixel half passes vacuously and the guard currently guards nothing
- **File:** `tools/visual_guard/run_guard.py:44`, `tools/visual_guard/diff.py:98-115`
- **Confirmed:** yes
- **Description:** `GOLDENS = GUARD_DIR / "goldens"`. That directory exists on disk but contains **0 PNG files**, and nothing under it is tracked by git. `compare_sets()` builds `goldens` from `golden_dir.glob("*.png")`; an empty (or missing) directory yields an empty set, `results` is empty, `failures` is empty and `missing` is empty — so it returns `ok=True`. A visual guard with no baselines compares nothing and reports success.
- **Cause:** the baselines were never committed (the directory is empty because git does not track empty directories), and nothing in the tooling or CI regenerates or verifies them.
- **Trigger conditions:** every run of `run_guard.py --compare` on a clean clone.
- **User impact:** the "visual regression guard" contributes zero guarantee. A regression that changes the rendered UI by any amount passes. `docs/perf/prof_frontend.md` and `docs/UI_V2_REFINEMENT.md` both point at the guard as the mechanism that protects the design system; it does not.
- **Evidence:**
  ```
  goldens dir exists: True   png count: 0
  current dir exists: False
  PIXEL GUARD ok = True  compared: 0  passed: 0  failed: 0  missing: 0
  ```
  ```python
  # tools/visual_guard/diff.py:113-115
  failures = [r for r in results if not r["ok"]]
  return {
      "ok": not failures and not missing,
  ```
  `git ls-files tools` contains no `goldens/` entry; `git status --porcelain --untracked-files=all tools` shows only `?? tools/bench/check_live_providers.py` and `?? tools/bench/results/optimization-before-20261015-154303.json`.
  **Correction to the audit brief:** the PNGs under `docs/` are *not* the guard's baselines. `docs/screenshots/` holds 170 PNGs — manual documentation shots dated 2026-10-14/15 in per-screen subfolders (`macos-ui`, `ui-v2-search-20261014`, …) — and the whole `docs/screenshots/` tree is **untracked** (`?? docs/screenshots/`). Only 19 PNGs are tracked in the entire repository.
- **Reproduction / verification:**
  ```powershell
  (Get-ChildItem -Recurse -File tools\visual_guard\goldens).Count   # -> 0
  git ls-files tools | Select-String goldens                          # -> no match
  ```
  plus the `compare_sets` semantics probe (empty golden dir + missing current dir → `{'ok': True, 'compared': 0}`).
- **Suggested fix:** commit a golden set generated on a declared reference machine (see ARCH item 4), and make `compare_sets()` treat "no goldens" as a hard error (`ok=False`, `reason="no_baseline"`) instead of success.
- **Fix side effects:** committing ~96 PNGs adds binary weight to the repo and requires a documented re-capture procedure; a hard error will make the guard fail loudly until the baselines exist — which is the point, but it will break any ad-hoc `--compare` invocation in the meantime.
- **Discovered by:** B

#### F-WN-35-4  [P1] — The `scroll` scenario scrolls an empty element, and its number is published as the scroll-FPS headline
- **File:** `tools/bench/scenarios.py:390-411`, `tools/bench/scenarios.py:409`, `tools/bench/run_bench.py:45-49`, `tools/bench/run_bench.py:265`
- **Confirmed:** yes
- **Description:** `scenario_scroll()` never navigates to the library or search page and never populates it. It queries the selector, and the injected JS scrolls `el.scrollTop` — but `el.scrollHeight` is 0 because the container has no rows. The frame timings therefore measure a browser sitting at the 60 Hz vsync interval, not a 2000-row list being scrolled. The result is published anyway.
- **Cause:** the scenario has no fixture step (no `showPage('library')`, no wait for the row render) — the *visual guard* has exactly such a driver (`tools/visual_guard/fixtures.py:195-201`, `"library"` waits 1200 ms and reports `res.children.length`), but the bench scenario does not reuse it.
- **Trigger conditions:** every `scroll` and `combo` run.
- **User impact:** `docs/perf/baseline.md:22` publishes *"Scroll FPS, 2000-track library | 16.7 ms/frame (~60 FPS) | 3 | `combo-*.json`"* as a headline performance figure. It is the measurement of an empty box. The real cost of the 76 000-node library list (which `prof_frontend.md` §4 derives statically) has never been measured by this harness, so the number gives false assurance that the library list scrolls smoothly.
- **Evidence:**
  ```
  scroll: library_2000     selector: #lib-active-tracks  rows_rendered(scrollHeight): 0  medianFrameMs: 16.7
  scroll: search_results   selector: #search-results    rows_rendered(scrollHeight): 0  medianFrameMs: 16.7
  ```
  (identical in all 3 reps of the committed `tools/bench/results/combo-2000trk-20261004-095459.json`).
  The field is also mislabelled: `scenarios.py:409` stores `runs[0].get("scrollHeight")` under the name `rows_rendered`, so a reader of the JSON cannot tell that the list was empty.
- **Reproduction / verification:** parse the committed artefact:
  ```powershell
  & ".venv_win\Scripts\python.exe" -c "import json;d=json.load(open('tools/bench/results/combo-2000trk-20261004-095459.json'));print([(s['label'],s['rows_rendered'],s['medianFrameMs']) for r in d['runs'] for s in (r['child']['data'].get('scroll') or [])])"
  ```
- **Suggested fix:** drive the page before scrolling (reuse `tools/visual_guard/fixtures.py` drivers), assert `scrollHeight > clientHeight` before measuring, and fail the scenario when the list is empty; rename `rows_rendered` to `scroll_height_px` and add a real `row_count`.
- **Fix side effects:** a populated 2000-row list will make the scenario materially slower and may expose a real frame-time regression that the current (empty) measurement hides — the published 16.7 ms will change, and `docs/perf/baseline.md` must be corrected.
- **Discovered by:** B

#### F-WN-35-5  [P2] — The CSS half of the visual guard is permanently red: the baseline was recorded against the deleted legacy `ui/web_new/` tree
- **File:** `tools/visual_guard/run_guard.py:49`, `tools/visual_guard/run_guard.py:502-579`
- **Confirmed:** yes
- **Description:** `ANIM_DECLS` points at the committed baseline `tools/bench/results/animation_declarations.json`. That baseline was recorded when the repo still had the legacy `ui/web_new/` tree; that tree has since been deleted (git status shows `D ui/web_new/css/styles.css` etc.). `css_declaration_guard()` therefore reports every declaration of the deleted file as *removed* — 302 of them — plus 2 substitutions in the surviving `visual-polish.css`.
- **Cause:** the baseline is a hand-maintained artefact stored next to the other bench outputs, with no stamp of the tree it was taken from and no invalidation on a large tree change.
- **Trigger conditions:** any `run_guard.py --compare` / `--all` run on the current tree.
- **User impact:** `run_guard.py` exits 1 for a reason unrelated to the tree under review, so the guard is permanently red and therefore permanently ignored. The two genuine `changed` entries (`ui/web_new_v2/css/components/visual-polish.css|backdrop-filter` and `|-webkit-backdrop-filter`) are buried inside 302 false removals and will never be read.
- **Evidence:**
  ```
  CSS GUARD ok = False
    baseline_declarations: 651   current_declarations: 438
    baseline_keys: 99  current_keys: 103  intersection_keys: 67  vacuous: False
    changed: 2   removed: 302   added: 89
    sample removed: 'ui/web_new/css/styles.css|--app-bg-opacity = 1',
                    'ui/web_new/css/styles.css|--blur-lg = 0px', ...
    sample changed keys: ['ui/web_new_v2/css/components/visual-polish.css|-webkit-backdrop-filter',
                           'ui/web_new_v2/css/components/visual-polish.css|backdrop-filter']
  ```
  The independent verifier in the repo agrees — `tools/bench/verify_frontend_report.py` reports:
  `NOTE: guard baseline keys still present in the tree: live='64/99' recorded='99/99' [DIFFERS]`.
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" -c "import sys;sys.path.insert(0,'.');from tools.visual_guard import run_guard as g;c=g.css_declaration_guard();print(c['ok'],len(c['removed']),len(c['changed']))"
  ```
- **Suggested fix:** regenerate the baseline with `--write-css-baseline` against the current tree, and store the tree fingerprint in the baseline file so a stale baseline is detected as stale rather than reported as 302 removals.
- **Fix side effects:** regenerating will bake the *current* `visual-polish.css` backdrop-filter values into the baseline, i.e. the two real `changed` entries would be accepted silently. Review them before regenerating.
- **Discovered by:** B

#### F-WN-35-6  [P2] — `check_shadow_imports.py` produces a false positive on nested functions and currently fails on `core/api.py`
- **File:** `tools/check_shadow_imports.py:49-56`, `tools/check_shadow_imports.py:31-36`, `core/api.py:17`, `core/api.py:570`, `core/api.py:579-595`
- **Confirmed:** yes
- **Description:** `_own_body()` exists specifically to walk "a function's own body, NOT descending into nested defs/lambdas" — but `local_imports()` then re-walks each yielded statement with `ast.walk(node)`, which descends into everything the statement contains. When a nested `def` sits inside a compound statement (`try`/`if`/`with`), the nested def's local imports are attributed to the enclosing function.
- **Cause:** `local_imports()` bypasses the scoped walk that `_own_body()` provides.
- **Trigger conditions:** any function that defines a nested function inside a `try`/`if`/`with` block and imports a module-level name inside it.
- **User impact:** the checker reports a non-existent `UnboundLocalError` risk on `core/api.py` right now, so the tool that exists to catch the "silence" failure mode of this codebase produces a false alarm on the current code — a strong reason nobody wires it into CI.
- **Evidence:**
  ```
  $ & ".venv_win\Scripts\python.exe" tools/check_shadow_imports.py
  SHADOWING function-local imports (UnboundLocalError risk):
    core\api.py: _install_snap_layouts() uses 'time' at line 570 but imports it locally at line 581
  exit=1
  ```
  In `core/api.py` the `import time` at line 581 is inside the nested `def _set_icon():` (lines 579–595); line 570 (`time.sleep(delay)`) is in `_install_snap_layouts`'s own scope, where `time` is the module-level import at `core/api.py:17`. Python semantics: a nested function's local import does not shadow anything in the enclosing scope.
  Minimal reproduction of the mechanism (probe run):
  ```
  module_level_imports: {'time'}
  local_imports(f): {'time', 'threading'}
  used_before(f,'time'): (4, 8)
  exec OK -> no UnboundLocalError at runtime
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" tools/check_shadow_imports.py            # exit 1, false positive
  ```
  and the synthetic probe shown above (a `try:` block containing a nested `def` that does `import time`).
- **Suggested fix:** make `local_imports()` use the same scoped traversal — walk the function body with a visitor that does not descend into nested `FunctionDef`/`AsyncFunctionDef`/`Lambda`/`ClassDef` — instead of `ast.walk()` over whole statements.
- **Fix side effects:** the checker will then find *fewer* candidates; the genuine shadowing bug that the docstring cites (`core/proxy.py:do_GET`, "killed every proxied stream request") must still be caught — verify with that historical case before shipping the narrower rule.
- **Discovered by:** B

#### F-WN-35-7  [P2] — Neither governance script is wired into any gate; the lock rule in AGENTS.md is prose-only
- **File:** `.github/workflows/ci.yml:28-30`, `tools/check_lock_nesting.py:99-123`, `tools/check_shadow_imports.py:83-115`
- **Confirmed:** yes
- **Description:** The only CI job for the desktop product is `pytest -m "not network"`. There is no `.pre-commit-config.yaml`, no `.husky/`, no `Makefile`, `tox.ini`, `noxfile.py` or `justfile` in the repository. `check_lock_nesting.py` and `check_shadow_imports.py` are referenced **only** from `docs/audits/WIN_AUDIT_AREAS.md` (this audit) — not from `AGENTS.md`, not from `CODING_STANDARDS.md`, not from any skill, not from CI.
- **Cause:** the scripts were written as ad-hoc one-off diagnostics during earlier audit passes and were never promoted to gates.
- **Trigger conditions:** always.
- **User impact:** the two AGENTS.md governance rules that are *mechanically checkable* ("a new shared field joins its class's existing lock", and the function-local-import shadowing hazard) are enforced by nothing. Both scripts are currently broken (F-WN-35-1, F-WN-35-6), so wiring them in as-is would break the build on false positives — which is presumably why they were never wired in.
- **Evidence:**
  ```
  $ Get-ChildItem -Force -File . | Where-Object { $_.Name -match "pre-commit|husky|Makefile|tox|noxfile" }
  (no output)
  ```
  Reference search over `docs/`, `.claude/`, `.github/`, `AGENTS.md`, `CODING_STANDARDS.md`, `STATUS.md`, `README.md`:
  ```
  check_lock_nesting     refs=1  in: WIN_AUDIT_AREAS.md
  check_shadow_imports   refs=1  in: WIN_AUDIT_AREAS.md
  ```
  The Android side of the repo *does* have a real gate (`.github/workflows/android-source.yml`, "Verify the source snapshot" — a hash-pinned manifest that fails on any change until regenerated). The Windows side has no equivalent.
- **Reproduction / verification:** the reference search above plus the absence of any pre-commit/CI configuration.
- **Suggested fix:** move both checkers to `tools/gates/`, add a `tools/gates/run_all.py`, fix the two defects, and add a second job to `.github/workflows/ci.yml` that runs the gates on `windows-latest` with the project interpreter.
- **Fix side effects:** a new CI job adds ~20 s per push and will surface the pre-existing false positives (F-WN-35-2, F-WN-35-6) that must be fixed first.
- **Discovered by:** B

#### F-WN-35-8  [P2] — `aggregate()` silently drops failed repetitions and does not record how many samples each median is over
- **File:** `tools/bench/run_bench.py:196-209`, `tools/bench/run_bench.py:160-170`, `tools/bench/run_bench.py:330-335`
- **Confirmed:** yes
- **Description:** `aggregate()` flattens every run and takes the median of the numeric leaves. `_median()` filters out the `None` produced by a missing key, so a run that produced no data contributes nothing and is dropped without trace. The returned envelope records only `n_runs` (the *total* number of repetitions attempted), never how many repetitions actually contributed to a given key. A median over 1 surviving sample is indistinguishable from a median over 5.
- **Cause:** the aggregator has no per-key sample counter and no separation between "attempted" and "valid" repetitions.
- **Trigger conditions:** any repetition whose scenario failed (CDP attach failure, harness exception, child crash).
- **User impact:** a results file can present a confident-looking median and `n_runs: 5` while the underlying scenario produced **no data at all**. This is exactly what the committed `combo-2000trk-20261004-094813.json` does: all five reps failed with a harness traceback, yet the file publishes six medians including `cold_start.to_window_loaded_ms = 2172.0`. `docs/perf/baseline.md` cites `combo-*.json` as the source of two headline numbers. The `.claude/skills/nedotify-perf/SKILL.md:50-52` explicitly requires *"check exit codes and error fields before accepting a sample"* and *"Do not silently discard failed samples"* — the tool does the opposite.
- **Evidence:**
  ```
  ===== combo-2000trk-20261004-094813.json  n_runs: 5
    ok flags: [False, False, False, False, False]
    aggregate medians: cold_start.interpreter_and_import_ms = 633.8
                       cold_start.to_window_loaded_ms      = 2172.0   (and 4 more)
    child error: AttributeError: 'CDPSession' object has no attribute 'wait_event'
                 at tools/bench/bench_child.py:139
  ```
  `startup-2000trk-20261003-214120.json` has the same shape (`n_runs: 3`, `ok: [False,False,False]`, medians still published).
- **Reproduction / verification:** parse the committed file and compare `aggregate.n_runs` with `[r["ok"] for r in runs]` — they disagree in the two files named above.
- **Suggested fix:** emit `{"n_attempted": N, "n_valid": M, "per_key_samples": {k: m}}`; mark a run invalid when `ok` is false; and refuse to write an aggregate at all when `n_valid == 0`.
- **Fix side effects:** existing result files become non-conforming and the tooling that reads them (`report_numbers.py`, `read_pyprof.py`, `build_hotspots.py`) would need updating; the committed evidence would have to be re-labelled or re-run.
- **Discovered by:** B

#### F-WN-35-9  [P2] — The `search`, `feed` and `combo` scenarios hit live providers, contradicting the harness's own hermeticity contract
- **File:** `tools/bench/scenarios.py:3-6`, `tools/bench/scenarios.py:438`, `tools/bench/bench_child.py:166-178`, `core/api.py:2100`
- **Confirmed:** yes
- **Description:** `scenarios.py` opens with "Scenarios must be hermetic: no network, no writes outside the scratch profile, no dependence on wall-clock time or random data." But `scenario_search()` calls `window.pywebview.api.search(query, 'all')`, and `AppApi.search` with `source='all'` fans out to `["local", "youtube", "soundcloud", "spotify"]` — three live provider APIs. `measure_feed()` similarly drives `get_popular_tracks` / `get_feed` / `get_home_releases` / `get_home_mixes`, which call `self._core.recommendations.*` → live provider HTTP. Only Last.fm is stubbed (with a dummy key and a fake `requests.Session`).
- **Cause:** the hermeticity promise was written for the fixture and never extended to the provider layer; `profile.child_env()` only strips the Last.fm credentials (`profile.py:298-300`).
- **Trigger conditions:** every `search`, `feed` and `combo` run.
- **User impact:** (a) the published search number is a *network* measurement, not an application measurement, and is not reproducible — the committed artefact shows the same query taking **119 ms** in one round and **8813 ms** in another; (b) a bench run consumes the operator's provider quota and can trip rate limits / trigger provider anti-automation on the user's IP; (c) the measurement varies by tens of times between reps, so it cannot serve as a before/after baseline, which is the harness's stated purpose.
- **Evidence:**
  ```
  search medianMs: 847.7   runs: [1576.4, 119]
  search medianMs: 8422.8  runs: [8813.5, 8032.2]
  search medianMs: 8298.4  runs: [8577.2, 8019.6]
  feed wall_ms: 5020.1 / 5030.0 / 5008.4   lastfm_requests: 14 / 0 / 0
  ```
  ```python
  # tools/bench/scenarios.py:3-6
  Each scenario receives a :class:`BenchContext` and returns a JSON-serialisable
  dict. Scenarios must be hermetic: no network, no writes outside the scratch
  profile, no dependence on wall-clock time or random data.
  ```
  ```python
  # core/api.py:2100
  requested_providers = ["local", "youtube", "soundcloud", "spotify"]
  ```
  The 5.0 s `feed wall_ms` in all three reps is the harness's own settle budget, not a measurement — see `bench_child.py:182-203` (a 25 s deadline plus a hard `time.sleep(2.0)`).
- **Reproduction / verification:** the committed `combo-*.json` above; to confirm the live dependency, run a `search` scenario with the network blocked and observe the `search_completed` timeout path (`scenarios.py:440` returns `-1` after 20 s).
- **Suggested fix:** add a provider kill-switch to `child_env()` (an env var the provider services honour) or monkey-patch the provider `search`/`get_stream_url` methods in the bench child the way Last.fm is patched; then split the metric into "local FTS5 fan-out" and "provider fan-out (network, reported separately)".
- **Fix side effects:** the published search figure will change completely (it will become the local-only cost); the provider fan-out cost would then need a separate, explicitly network-labelled measurement.
- **Discovered by:** B

#### F-WN-35-10  [P2] — The visual-guard CLI's three documented modes are mutually inconsistent: `--all` can never pass, `--compare` never refreshes `CURRENT`, `--capture` destroys the reference
- **File:** `tools/visual_guard/run_guard.py:3-6`, `tools/visual_guard/run_guard.py:666-677`, `tools/visual_guard/run_guard.py:688-699`
- **Confirmed:** yes
- **Description:** The module docstring advertises three entry points. In the implementation:
  - `--all` sets `do_capture = True` and captures into `CURRENT if args.compare else GOLDENS` → with `--all` alone `args.compare` is False, so the capture writes into **GOLDENS**, and the subsequent `compare_sets(GOLDENS, CURRENT)` compares against a `CURRENT` that was never produced → every golden is reported as `missing` → `ok=False` → exit 1. `--all` can never succeed.
  - `--compare` alone leaves `do_capture = False`, so `CURRENT` is **never** regenerated; the guard compares the goldens against whatever stale (or empty) `CURRENT` happens to be on disk.
  - `--capture` **overwrites the goldens** with the current tree (`shutil.rmtree(GOLDENS)` then re-capture). There is no protection, no separate "rebuild" verb, and no requirement that a human approve the new baseline.
  The only invocation that actually works is `--capture --compare`, which the docstring does not mention.
- **Cause:** the three flags were designed independently and the capture target was never derived from the intent; the capture/compare coupling is implicit in the argument combination rather than explicit in the CLI.
- **Trigger conditions:** any use of the documented commands.
- **User impact:** the guard's documented usage is wrong in all three modes. Anyone who runs the documented `--all` gets a hard failure and will conclude the UI is broken. Anyone who runs `--capture` to "check the UI" has silently replaced the reference set, after which the guard is green by construction — the classic way a visual guard is neutralised.
- **Evidence:**
  ```python
  # tools/visual_guard/run_guard.py:666-677
  do_capture = args.capture or (args.all and not GOLDENS.exists())
  if args.all:
      do_capture = True
  ...
  capture_summary = capture(CURRENT if args.compare else GOLDENS, themes,
                            screens, args.tracks, args.port,
                            vg_fixtures.VIEWPORTS, vg_fixtures.DPRS)
  ```
  ```python
  # tools/visual_guard/run_guard.py:688-691
  if args.compare or args.all:
      log(f"comparing {len(screens)} screens x {len(themes)} themes ...")
      pixel = vg_diff.compare_sets(GOLDENS, CURRENT, out_dir=CURRENT / "_diff")
  ```
  `compare_sets` semantics (probe):
  ```
  A) golden present, current EMPTY   -> {'ok': False, 'compared': 0, 'missing': ['a__x.png']}
  B) golden present, current identical -> {'ok': True, 'compared': 1, 'passed': 1}
  C) NO goldens at all, no current   -> {'ok': True, 'compared': 0, 'missing': []}
  ```
  Case A is exactly the `--all` outcome; case C is exactly the `--compare`-without-baselines outcome.
- **Reproduction / verification:** read `run_guard.py:666-699` together with the probe above; the two paths are short and deterministic.
- **Suggested fix:** separate the verbs — `--capture-goldens` (writes `GOLDENS`, requires `--i-accept-a-new-baseline`), `--compare` (captures into `CURRENT` then compares), `--all` (both, in that order) — and derive the capture target from the verb, not from the presence of `--compare`.
- **Fix side effects:** the flag names change, so `docs/perf/prof_frontend.md` and `.claude/skills/` references to `run_guard.py --capture/--compare/--all` must be updated.
- **Discovered by:** B

#### F-WN-35-11  [P2] — `verify_frontend_report.py` crashes with `UnicodeEncodeError` while printing its own findings, so it cannot be used as a gate
- **File:** `tools/bench/verify_frontend_report.py:1215-1228`, `tools/bench/run_bench.py:33-37`
- **Confirmed:** yes
- **Description:** The verifier prints its report with bare `print()`. On a console whose code page is cp1251 (the default on the audited machine) the Cyrillic text in the drift notes cannot be encoded and the script dies with `UnicodeEncodeError`, exit code 1, *after* it has already decided the outcome. `run_bench.py` solves exactly this at `run_bench.py:33-37` (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")` with the comment *"The app logs Cyrillic; a cp1251 console would raise UnicodeEncodeError and kill the runner mid-report"*), but the verifier does not.
- **Cause:** the stdout reconfiguration was added to one runner and never propagated to the other 15 scripts in the same directory.
- **Trigger conditions:** any run on a machine whose stdout encoding is not UTF-8.
- **User impact:** the tool that exists to prove `docs/perf/prof_frontend.md` still matches the code dies before it can print the 35 drift notes it found — 34 of them are never shown, and the exit code (1) is indistinguishable from a genuine verification failure. As a gate it is unusable as written.
- **Evidence:**
  ```
  PASSED 171

  REPORTED 35 (snapshots / drift - not failures)
    NOTE: guard baseline keys still present in the tree: live='64/99' recorded='99/99' [DIFFERS]
  UnicodeEncodeError: 'charmap' codec can't encode characters in position 323-324: character maps to <undefined>
    File "...\tools\bench\verify_frontend_report.py", line 1223, in <module>
      print("  NOTE:", r)
  EXIT=1
  ```
- **Reproduction / verification:**
  ```powershell
  & ".venv_win\Scripts\python.exe" tools/bench/verify_frontend_report.py
  ```
- **Suggested fix:** add the same `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` preamble (ideally in a shared `tools/_console.py` imported by every entry point), and wrap the reporting loop so a single un-encodable note cannot abort the report.
- **Fix side effects:** none beyond output encoding; the exit code will then reflect the real verdict (`fails`), which is currently masked.
- **Discovered by:** B

#### F-WN-35-12  [P2] — An interrupted bench leaves the app running with a CDP port open, the single-instance mutex held, and deletes the scratch profile from under the running app
- **File:** `tools/bench/run_bench.py:128-141`, `tools/bench/run_bench.py:171-173`, `tools/bench/bench_child.py:424-425`
- **Confirmed:** yes (code path); process-orphan outcome is a hypothesis (see below)
- **Description:** `run_once()` starts the real application as a child process and waits with `proc.communicate(timeout=timeout)`. There is no `except KeyboardInterrupt`, no `finally` that terminates the child, and no process-group creation (`start_new_session`/`CREATE_NEW_PROCESS_GROUP`) — a repository-wide grep for `KeyboardInterrupt|taskkill|killpg|CREATE_NEW_PROCESS_GROUP|start_new_session` across `tools/**` returns **zero hits**. On Ctrl-C the `KeyboardInterrupt` propagates, the `finally` block deletes the scratch profile (`shutil.rmtree(profile_root)`) **while the child is still running and using it**, and the orphaned NeDotify window stays on screen.
- **Cause:** the child is treated as a fire-and-forget resource; only the timeout path (`proc.kill()`) is handled.
- **Trigger conditions:** the operator presses Ctrl-C during a bench run (very likely — a 5-rep idle run takes minutes), or the parent console is closed.
- **User impact:** (a) an orphaned NeDotify keeps the CDP debugging port open on `127.0.0.1:9222` for as long as it lives — any local process can drive the app's renderer and therefore the whole Python bridge; (b) the orphan holds `Local\NeDotify_App_Single_Instance_Mutex`, so the user's own NeDotify will refuse to start ("a second launch exits silently", `docs/perf/baseline.md:145-146`) until the orphan is killed by hand; (c) the orphan is writing into a directory that the parent just deleted.
- **Evidence:**
  ```python
  # tools/bench/run_bench.py:134-140
  try:
      out, _ = proc.communicate(timeout=timeout)
  except subprocess.TimeoutExpired:
      proc.kill()
      out, _ = proc.communicate()
      out += "\n[bench] TIMEOUT - killed"
  ```
  ```python
  # tools/bench/run_bench.py:171-173
  finally:
      if owns_profile and not spec.get("keep_profile"):
          shutil.rmtree(profile_root, ignore_errors=True)
  ```
  The child opens the debug port unconditionally: `tools/bench/bench_child.py:424-425` → `webview.settings["REMOTE_DEBUGGING_PORT"] = DEBUG_PORT`.
- **Reproduction / verification:** start `run_bench.py --scenario idle --reps 5 --seconds 60` and press Ctrl-C; then `Get-Process msedgewebview2,python -ErrorAction SilentlyContinue` and check whether the app window is still present.
- **Suggested fix:** create the child in its own process group, and in a `finally` terminate the *tree* (`taskkill /T /F /PID` on Windows, `os.killpg` elsewhere) before deleting the scratch profile; also install a `KeyboardInterrupt` handler that reports the abort.
- **Fix side effects:** `taskkill /T /F` on the child will also kill the WebView2 helper processes, which is the intent; the exit code of the run should then distinguish "aborted" from "failed".
- **Discovered by:** B

#### F-WN-35-13  [P2] — `check_live_providers.py` (untracked) cannot work as written and hits live providers with the operator's credentials
- **File:** `tools/bench/check_live_providers.py:43`, `tools/bench/check_live_providers.py:84-130`, `core/proxy.py:796`, `core/proxy.py:802`
- **Confirmed:** yes
- **Description:** The script builds a fake app core — `LocalProxyManager(SimpleNamespace(**services, settings=None))` — and then asks the proxy for the first audio bytes. `StreamProxyHandler.do_GET` dereferences `self.server.app_core.db.get_cached_stream(...)` **unconditionally** (line 796) and `self.server.app_core.cache._streams_dir` (line 802). `SimpleNamespace` has neither `.db` nor `.cache`, so the handler raises `AttributeError` inside the `ThreadingHTTPServer` request thread. The client sees a dropped connection, the script swallows it into `report["media_error"] = type(exc).__name__` (line 130), and the headline capability of the tool — first audio bytes / one-second ffmpeg decode — never produces a result. Nothing in the repo references the file, and it is not tracked by git.
- **Cause:** the tool was written against a proxy handler that it does not satisfy; the fake app core implements the *service* attributes (`youtube`, `soundcloud`, `spotify`) that the handler uses for yt-dlp, but not the `db`/`cache` attributes it uses first.
- **Trigger conditions:** any run of `check_live_providers.py` that reaches the media fetch.
- **User impact:** the only harness in the repo that could measure the play/resolve path (the `WX-01` hot path) is non-functional, undocumented and untracked. Running it as-is performs real YouTube / SoundCloud / Spotify searches and stream resolutions — consuming provider quota, hitting provider rate limits and anti-automation on the user's IP — and, with `--decode`, spawning `ffmpeg` against a signed CDN URL. The failure is reported as a bare exception type, so an operator would reasonably conclude "the provider is broken" rather than "my fake app core is".
- **Evidence:**
  ```python
  # tools/bench/check_live_providers.py:43
  proxy = LocalProxyManager(SimpleNamespace(**services, settings=None))
  ```
  ```python
  # core/proxy.py:796 (unconditional, not guarded by `url_param`)
  cached_stream = self.server.app_core.db.get_cached_stream(source, source_id)
  ```
  ```python
  # tools/bench/check_live_providers.py:128-130
  except Exception as exc:
      # Signed CDN URLs contain tokens; do not print exceptions' URLs.
      report["media_error"] = type(exc).__name__
  ```
  `git status --porcelain --untracked-files=all tools` → `?? tools/bench/check_live_providers.py`; a reference search over `docs/`, `.claude/`, `.github/`, `AGENTS.md` gives `check_live_providers refs=0`.
  **Credit where due:** the script does correctly redirect `USERPROFILE` and `HOME` to a scratch directory *before* importing the services (lines 29-36), so it does not read the real `~/.nedotify` and does not pick up the user's browser cookies.
- **Reproduction / verification:** `git status` shows the file is untracked; `Select-String -Path core/proxy.py -Pattern "app_core.db"` shows the unconditional dereference; a reference search over all docs/skills/CI returns zero hits.
- **Suggested fix:** either give the fake app core the `db`/`cache` attributes the handler needs (or add a `?url=`-only fast path to the proxy), or drop the proxy round-trip and fetch the resolved CDN URL directly; commit the tool and document it in `nedotify-perf/SKILL.md` with an explicit "this consumes provider quota" warning and a `--offline` default.
- **Fix side effects:** fixing it will make a live-network measurement available that the project currently does not have; that measurement will be network-bound and rate-limit-prone, so it must be labelled separately from the hermetic metrics.
- **Discovered by:** B

#### F-WN-35-14  [P2] — `idle_states` never measures a playing state, a failed minimise is silent, and an empty sample window is recorded as a successful run
- **File:** `tools/bench/scenarios.py:246-251`, `tools/bench/scenarios.py:256-294`, `tools/bench/scenarios.py:55-61`
- **Confirmed:** yes
- **Description:** Three separate defects in one scenario.
  1. The docstring promises "visible+playing, visible+idle, and minimised". The code samples `visible_idle`, `minimized`, `restored`. The comment at line 278 says "start playback on a real library track so the progress loop is live", but the following code only calls `window.pywebview.api.get_library()` and stores the result in `window.__benchTrack` — **nothing is ever played**. There is no playing-state measurement anywhere in the harness.
  2. `set_window_minimized(hwnd, ...)` returns `False` when `hwnd` is `None` (i.e. when `find_main_window()` failed to locate the window by title), and the caller ignores the return value. The "minimized" state can therefore be a fully visible window.
  3. The sample summary is emitted even when `rows` is empty (`_summarise([])` → `{}`), and the run is still marked `ok`.
- **Cause:** the scenario was written against an earlier version and the states were renamed without updating the docstring or the driver; the empty-sample case is not validated.
- **Trigger conditions:** every `idle_states` run.
- **User impact:** the "idle CPU while playing" question — arguably the most important CPU question for a music player, and the one `WX-12` (minimise / foreground) turns on — is not measured, and the report presents three differently-named states as if they were the three the docstring names. `docs/perf/baseline.md:83` concludes *"document.hidden does become true on minimise … So 'pause on minimise' is already implemented and is not an opportunity"* on the strength of a state that the scenario only labels.
- **Evidence:**
  ```
  ===== idle_states-2000trk-20261004-103547.json  (ok: True for all 3 reps)
    state=visible_idle   n=27 hidden=False vis=visible   tree_cpu_mean=117.75
    state=minimized      n=28 hidden=True  vis=hidden    tree_cpu_mean=14.63
    state=restored       n=27 hidden=False vis=visible   tree_cpu_mean=140.84
  ===== idle_states-2000trk-20261004-102742.json  (ok: True for all 3 reps)
    state=visible_idle   n=26
    state=minimized      n=0      <-- empty, run still reported ok
    state=restored       n=0      <-- empty
  ```
  The three sampled states are exactly `visible_idle` / `minimized` / `restored` — there is no `visible_playing`.
- **Reproduction / verification:** the two committed `idle_states-*.json` files, parsed above; the comment/code mismatch is at `scenarios.py:278-286`.
- **Suggested fix:** rename the states to what they are, actually start playback before the playing sample (or drop the claim), assert `hwnd is not None` and fail loudly if the minimise failed, and treat `n_samples == 0` as a scenario failure.
- **Fix side effects:** a real playing state requires the fixture to resolve a stream, which the hermetic fixture cannot do (see coverage gaps) — the honest outcome is to drop the "playing" claim from the docstring and measure it separately, e.g. via `check_live_providers.py` once fixed.
- **Discovered by:** B

#### F-WN-35-15  [P3] — Every committed bench result is stale relative to the current tree, and no artefact carries a commit stamp
- **File:** `tools/bench/profile.py:307-330`, `tools/bench/run_bench.py:316-327`
- **Confirmed:** yes
- **Description:** `run_bench.py` records a content fingerprint of the source tree (`code_fingerprint`) with each result, which is a good idea. But the fingerprint is a hash of file *contents*, not a git identity: it cannot be mapped back to a commit, and nothing in the result envelope records the branch, the commit SHA, or the dirty/clean state of the worktree. The repository has 60+ modified and 40+ untracked files, and **all 20 committed result files with a fingerprint are stale** against the current tree.
- **Cause:** the fingerprint was designed to detect drift but not to identify the code; no re-baselining step was performed after the large `ui/web_new/` → `ui/web_new_v2/` consolidation and the current uncommitted work.
- **Trigger conditions:** always, for any committed result file.
- **User impact:** `docs/perf/prof_frontend.md`, `docs/perf/prof_python_startup.md` and `docs/RESOURCE_OPTIMIZATION.md` are cited by the project as the performance evidence, but no number in them can be tied to the code that is shipping. `docs/perf/baseline.md:3` is the only document with a stamp — and it names a different branch and commit from the current HEAD (`fix/audit-2026-10-03` @ `62eff6c` vs. HEAD `76cab49` on `fix/audit-v2`).
- **Evidence:**
  ```
  CURRENT tree fingerprint: 4892a0899fafa383
  animation_declarations.json                             (no code_fingerprint)
  backdrop_live-20261004-105616.json      fp=0f0aa1095434f422  STALE
  combo-2000trk-20261004-094813.json       fp=517480d9f5e26c04  STALE
  cpu_attribution-2000trk-20261004-104016.json fp=2d6bfd83bdd89b0c STALE
  startup-2000trk-20261003-224243.json     fp=c5d6836ca815aa41  STALE
  optimization-before-20261015-154303.json fp=83c2bd7f55e53683  STALE
  ...  (all 20 STALE)
  ```
  ```
  docs/perf/baseline.md:3
  Date: 2026-10-04 · Branch: `fix/audit-2026-10-03` · HEAD at capture: `62eff6c`
  ```
  (`git cat-file -t 62eff6c` → `commit`; it exists but is not the current branch tip.)
- **Reproduction / verification:** recompute the fingerprint and diff it against each result file (probe shown above); `git rev-parse --abbrev-ref HEAD` → `fix/audit-v2`, `git log --oneline -1` → `76cab49`.
- **Suggested fix:** add `git_commit`, `git_branch` and `git_dirty` to the result envelope (queryable with `git rev-parse`), and re-run + re-publish the three perf documents against the current tree, or mark them explicitly as historical with their commit pinned.
- **Fix side effects:** requires a full re-measurement cycle; the numbers will move and the published docs must be updated in the same change.
- **Discovered by:** B

#### F-WN-35-16  [P3] — Bench and guard artefacts land untracked in the repository tree, and the committed evidence set mixes verified and crashed runs
- **File:** `tools/bench/run_bench.py:41`, `tools/visual_guard/run_guard.py:45-46`, `.gitignore:44-48`
- **Confirmed:** yes
- **Description:** Every bench run writes a JSON result into `tools/bench/results/`, and every guard compare writes PNGs into `tools/visual_guard/current/` and a report into `tools/visual_guard/reports/`. Only `tools/bench/results/_warm_profile/` and `*.pstats` are ignored; `reports/` is ignored by a generic rule. The result JSONs, the goldens and the `current/` PNGs are **not** ignored, so they show up as untracked files and are easy to commit by accident. At the same time, 47 result files (2.3 MB) *are* committed, including files whose runs crashed (F-WN-35-8).
- **Cause:** the results directory serves two incompatible purposes — "versioned evidence" and "scratch output" — with a single ignore policy that fits neither.
- **Trigger conditions:** every bench run and every guard compare.
- **User impact:** the repository accumulates untracked megabytes of run output; `git status` noise; a contributor can `git add .` and commit a 2000-track idle run plus screenshots. The already-committed set contains at least two files that record a harness crash, which is misleading as "evidence".
- **Evidence:**
  ```
  git check-ignore -v tools/bench/results/newrun.json         -> (no match)
  git check-ignore -v tools/visual_guard/current              -> (no match)
  git check-ignore -v tools/visual_guard/goldens/x.png        -> (no match)
  git check-ignore -v tools/visual_guard/reports/g.json        -> .gitignore:57:reports/
  git status --porcelain --untracked-files=all tools
      ?? tools/bench/check_live_providers.py
      ?? tools/bench/results/optimization-before-20261015-154303.json
  ```
  `tools/bench/results/` currently holds 44 files / 2.3 MB, of which 47 are tracked in git.
  **Correction to the audit brief:** the `.pstats` artefact is **not** committed — `.gitignore:48` has `*.pstats` and `git ls-files tools` lists no `.pstats` entry. The file exists on disk (`tools/bench/results/profile_appcore_init.pstats`, 106 861 bytes) but is correctly ignored. The one generated binary-ish artefact that *is* committed is `tools/bench/results/pyspy_idle.svg` (308 bytes).
- **Reproduction / verification:** the `check-ignore` probes above plus `git ls-files tools | Select-String pstats` (no match).
- **Suggested fix:** split the outputs — `tools/bench/results/` stays versioned and read-only (a fixture, with a `README` stating that new runs go elsewhere), new runs go to a gitignored `tools/bench/_runs/` or to `%TEMP%` (the `NEDOTIFY_BENCH_OUT` mechanism already exists for this), and `tools/visual_guard/current/` + `goldens/` get an explicit ignore rule for `current/` while `goldens/` becomes versioned.
- **Fix side effects:** the committed evidence set must be curated (drop or annotate the crashed files); anyone relying on `NEDOTIFY_BENCH_OUT` defaults sees a changed output location.
- **Discovered by:** B

#### F-WN-35-17  [P3] — `build_hotspots.py` puts `tools/bench` on `sys.path`, which shadows the stdlib `profile` module
- **File:** `tools/bench/build_hotspots.py:27-30`, `tools/bench/run_pyprof.py:40-47`
- **Confirmed:** yes
- **Description:** `build_hotspots.py` does `sys.path.insert(0, str(REPO / "tools" / "bench"))` to import the sibling `js_census`. `tools/bench/` contains `profile.py`, so from that point on `import profile` resolves to the benchmark's profile module instead of the stdlib one. `run_pyprof.py:40-47` explicitly documents the opposite rule — *"tools/bench must NOT go on sys.path: tools/bench/profile.py shadows the stdlib profile module, which cProfile needs"* — and loads its sibling `sleepscan.py` by file path instead.
- **Cause:** two conventions inside one package; the sibling-import technique was applied to one script and not the other.
- **Trigger conditions:** running `build_hotspots.py` (or anything that imports it) in a process that later imports `profile`.
- **User impact:** a latent, hard-to-diagnose failure mode (stdlib `profile` is used by `cProfile`/`pstats` tooling and by some test helpers) in a repository where the failure mode of this exact class is a silent wrong result.
- **Evidence:**
  ```python
  # tools/bench/build_hotspots.py:29-30
  sys.path.insert(0, str(REPO / "tools" / "bench"))
  import js_census  # noqa: E402
  ```
  ```python
  # tools/bench/run_pyprof.py:40-47
  def _load_sleepscan():
      """Import the sibling scanner by path.
      ``tools/bench`` must NOT go on ``sys.path``: ``tools/bench/profile.py``
      shadows the stdlib ``profile`` module, which ``cProfile`` needs.
      """
  ```
  Probe:
  ```
  $ python -c "import sys;sys.path.insert(0,'tools/bench');import profile;print(profile.__file__)"
  ...\tools/bench/profile.py
  is stdlib profile? False
  ```
- **Reproduction / verification:** the probe above.
- **Suggested fix:** load `js_census` the way `run_pyprof.py` loads `sleepscan` (importlib by file path), or rename `tools/bench/profile.py` to something non-shadowing (`profile_fixtures.py`) and update the two importers (`run_bench.py:39`, `run_guard.py:39`).
- **Fix side effects:** renaming touches the two entry points and `bench_child.py`; the importlib approach touches only `build_hotspots.py` and is the lower-risk option.
- **Discovered by:** B

#### F-WN-35-18  [P3] — `psutil` is an undeclared dependency whose absence silently turns every CPU figure into 0.00 %
- **File:** `tools/bench/procsampler.py:7-21`, `tools/bench/procsampler.py:83-84`, `requirements.txt`, `requirements-dev.txt`
- **Confirmed:** yes
- **Description:** `psutil` is imported with `try: import psutil / except ImportError: psutil = None` and is deliberately **not** declared in `requirements.txt` ("nothing in the shipped app imports it") nor in `requirements-dev.txt` (which contains only `pytest` and `pytest-asyncio`). When it is missing, `_take()` returns an all-zero `Sample` and the sampler keeps running, so the published CPU/RAM figures are `0.00 %` and `0.0 MB` with no error and no note in the output. The CI job installs only `requirements.txt` + `requirements-dev.txt`.
- **Cause:** an undeclared dev dependency with a fail-open degradation path.
- **Trigger conditions:** any bench run on a machine whose venv lacks `psutil` — i.e. every fresh clone and every CI runner.
- **User impact:** a CPU measurement of "0.00 %" is indistinguishable from a genuinely idle process. The harness that exists to detect *exactly* the "renderer burns a core while idle" class of regression (see `docs/perf/baseline.md` §3, where the headline finding is a 102 % renderer CPU) would report zero and be believed.
- **Evidence:**
  ```python
  # tools/bench/procsampler.py:18-21
  try:
      import psutil
  except ImportError:  # pragma: no cover
      psutil = None
  ```
  ```python
  # tools/bench/procsampler.py:83-84
  if psutil is None:
      return s          # all-zero Sample
  ```
  ```
  $ python -c "import importlib.util as u; print('psutil', bool(u.find_spec('psutil')))"
  psutil True                       # present in this .venv_win
  $ Get-Content requirements-dev.txt
  pytest==9.1.1
  pytest-asyncio==1.4.0             # no psutil
  ```
  Probe with `psutil` forced to `None`:
  ```
  sample WITHOUT psutil: Sample(python_cpu_pct=0.0, webview_cpu_pct=0.0, tree_cpu_pct=0.0,
                                 python_rss_mb=0.0, webview_rss_mb=0.0, tree_rss_mb=0.0,
                                 python_threads=0, n_children=0)
  ```
- **Reproduction / verification:** the probe above (`procsampler.psutil = None` then `_take()`).
- **Suggested fix:** declare `psutil` in `requirements-dev.txt` (or a `requirements-bench.txt`), and make the sampler raise / record `"psutil_missing": true` instead of emitting zeros, so the aggregate can refuse to publish a CPU number.
- **Fix side effects:** one more dev dependency to install; the CI job would need it if the bench is ever run there.
- **Discovered by:** B

#### F-WN-35-19  [P3] — `run_bench.py --list` prints a stale scenario list
- **File:** `tools/bench/run_bench.py:246-248`, `tools/bench/run_bench.py:215-217`
- **Confirmed:** yes
- **Description:** `--list` prints `"scenarios: startup, idle, scroll, search, feed, combo"` while the argument parser accepts eight (`startup`, `idle`, `idle_states`, `cpu_attribution`, `scroll`, `search`, `feed`, `combo`). Two of the available scenarios — `idle_states` and `cpu_attribution`, the two that produce the `docs/perf/baseline.md` §3 findings — are not listed.
- **Cause:** the `--list` string was written before the two scenarios were added and never derived from the parser.
- **Trigger conditions:** every `--list` invocation.
- **User impact:** the discovery command under-reports the harness's capabilities; combined with the fact that the scenario list is duplicated in three places (`argparse choices`, the `--list` string and `.claude/skills/nedotify-perf/SKILL.md:20-21`) — the skill is currently correct, the `--list` output is not — this is a symptom of the missing scenario registry (ARCH item 5).
- **Evidence:**
  ```
  $ & ".venv_win\Scripts\python.exe" tools/bench/run_bench.py --list
  scenarios: startup, idle, scroll, search, feed, combo
  $ & ".venv_win\Scripts\python.exe" tools/bench/run_bench.py --help
  usage: run_bench.py [-h] [--scenario {startup,idle,idle_states,cpu_attribution,
                                     scroll,search,feed,combo}] ...
  ```
- **Reproduction / verification:** the two commands above.
- **Suggested fix:** derive the `--list` output from the scenario registry (single source of truth) rather than a hard-coded string.
- **Fix side effects:** none.
- **Discovered by:** B

---

### 3. Clean areas

- **Every tool module compiles.** `& ".venv_win\Scripts\python.exe" -m py_compile` over all 29 files under `tools/bench/*.py`, `tools/visual_guard/*.py`, `tools/*.py` → **exit 0, no output**. No dead-by-syntax tools.
- **All project imports used by the tools resolve against the current tree.** Verified by executing them: `tools.bench.profile` → `core.database.DatabaseManager` ✔; `tools.bench.bench_child` → `services.lastfm_service.LastFMService` with `API_KEYS` (`:23`), `_get_session` (`:152`) and the `available` **property** (`:204-208`) all present, so the Last.fm monkey-patch still binds ✔; `tools.visual_guard.run_guard` → `tools.bench.profile`, `tools.visual_guard.diff`, `tools.visual_guard.fixtures` ✔; `tools.bench.verify_frontend_report` → `tools.bench.css_inventory` ✔. `numpy` and `Pillow` (needed by `diff.py`, `profile.py`) are declared in `requirements.txt` ✔.
- **The profile isolation is real and verified.** Every app write path goes through `os.path.expanduser("~")` (17 call sites enumerated across `main.py`, `core/`, `services/`, `utils/`), and `profile.child_env()` (`tools/bench/profile.py:287-304`) redirects `USERPROFILE` and clears `HOMEDRIVE`/`HOMEPATH`, which is exactly what `ntpath.expanduser` consults. `main.py:549` puts the WebView2 user-data folder under the same redirected home (`storage_path=~/.nedotify/webview2_data`), so the WebView2 profile is captured too. The real `~/.nedotify/` is never touched by a bench or guard run.
- **The sampler does not touch unrelated processes.** `procsampler.ProcSampler.pid` defaults to `os.getpid()` (`procsampler.py:44`) — it samples *its own* process tree and only counts children whose image name is `msedgewebview2.exe` (`_is_webview2`, `:189-194`). It reads `cpu_times()`/`memory_info()`/`num_threads()` only. No attach, no ptrace, no scanning of other processes.
- **`py-spy` usage is safe and degrades gracefully.** `run_pyprof.py:413-470` attaches to a PID it spawned itself, and returns `{"available": False, ...}` when `py-spy.exe` is absent (it is absent in this venv — verified: `find_spec('py_spy') → False`).
- **`check_live_providers.py` does not read the user's real profile.** It sets `USERPROFILE` and `HOME` to the scratch directory *before* importing the provider services (`:29-36`), so it does not pick up the real browser cookie jar or the real `~/.nedotify`. (Its functional defect is F-WN-35-13; its isolation is correct.)
- **The pixel-diff thresholds are sensibly chosen and are applied symmetrically.** `diff.py:21-22` uses a 0.1 % differing-pixel ratio with a ±2/255 per-channel tolerance; the tolerance is applied identically to the golden and the current image, so it cannot mask a real regression in one direction. (The guard has no goldens to compare — F-WN-35-3 — so the threshold is currently untested in practice.)
- **`check_lock_nesting.py` is conservative about reentrancy.** It correctly skips `RLock` attributes (`tools/check_lock_nesting.py:88-89`) and `core/database.py:156` uses `threading.RLock()` for the write lock, so the *real* write path is safe. (The defects are the wrong root and the over-broad `with self.X:` matching — F-WN-35-1, F-WN-35-2.)
- **The `docs/perf/baseline.md` headline numbers are traceable to a committed artefact.** "Cold start → window loaded 2035 ms", "interpreter + module imports 446 ms", "FCP 136 ms", "interactive 523 ms" match `tools/bench/results/startup-2000trk-20261003-224243.json` exactly (`cold_start.to_window_loaded_ms = 2035.4`, `interpreter_and_import_ms = 446.4`, `child.data.fcp_since_nav_ms = 136.0`, `child.data.app_ready_since_reload_ms = 523.2`). The baseline is not fabricated.
- **The `cpu_attribution` scenario is methodologically the best part of the harness**: it has a control condition, it runs the condition list in both orders to cancel positional drift (`scenarios.py:204-210`), it injects CSS at runtime without touching any file, and it correlates the CPU number with CDP `Performance.getMetrics` deltas (`_perf_delta`, `:136-154`) so a reader can tell script work from raster work. This is the pattern the rest of the harness should follow.
- **The bench's cookie handling is explicit and defaults to hermetic.** `profile.seed_db` writes an empty Netscape jar and pins `auth.cookies_file_path` / `auth.browser_cookies=none` for `cookie_mode="pinned"`, and `--cookie-mode real` is an explicit opt-in that is documented in the CLI help (`run_bench.py:229-233`) and in the skill. The default never scrapes the user's real browser.

---

### 4. Coverage gaps

- **The bench and the visual guard were not executed end to end.** The ground rules forbid running the real app ("Never run the real app (it would disturb the user's profile)"), and both harnesses launch the full NeDotify window with a CDP debugging port. Every bench/guard finding above is therefore derived from (a) reading the code, (b) the committed result JSONs, and (c) calling the *pure* functions directly (`css_declaration_guard()`, `compare_sets()`, `aggregate()`, `ClassScan`, `local_imports`) — never the app.
- **F-WN-35-12's process-orphan outcome is a hypothesis.** The code fact (no `KeyboardInterrupt` handling, no process-group creation, profile deleted in `finally` while the child is alive) is confirmed by reading; whether orphaned `msedgewebview2.exe` processes survive the parent kill was not observed, because that requires an interrupted real run.
- **F-WN-35-13 was not executed**, because doing so performs live YouTube / SoundCloud / Spotify traffic. The proxy-handler dereference that breaks it is confirmed by reading `core/proxy.py:796/802` against the `SimpleNamespace` construction.
- **Cross-machine stability of the visual guard is untested** — with no goldens committed there is nothing to compare twice. Whether the capture is byte-stable across two Windows builds / font sets / GPU drivers (the claim at `tools/visual_guard/cdp.py:233-236` — *"two captures 0.7 s apart were byte-identical"*) was not re-verified, and that claim only covers same-machine, same-session captures.
- **The `prof_frontend.md` drift list is only partially surfaced.** The verifier printed 1 of its 35 drift notes before crashing (F-WN-35-11), so the remaining 34 — including the file:line citation drift that the report itself calls out as "line drift; the claim text is still checked by the content anchors" — were not read. The 171 passing checks are trustworthy; the drift inventory is not.
- **The two governance checkers were not run over the full application tree by their own entry point** (they cannot be — F-WN-35-1). I re-ran the *same* detector logic over the 61 application `.py` files manually to obtain the `core/database.py` finding; a complete lock-nesting audit of the app is therefore **not** covered by this area and would need a corrected checker.
- **`docs/RESOURCE_OPTIMIZATION.md` and `docs/PLAYBACK_LYRICS_PERFORMANCE.md` were read but not audited.** Their own numbers come from ad-hoc micro-benchmarks that are not in `tools/` and are not reproducible from the repository. They are referenced by the skill as the "current feature notes" but no tool produced them.
- **The `android/` tree was not opened**, per the audit scope.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — One dispatcher instead of three orchestrators and thirteen loose scripts.**
`tools/` holds 29 Python modules across ~7 000 lines. There are three "run" entry points (`tools/bench/run_bench.py` for app scenarios, `tools/bench/run_pyprof.py` for the Python profile, `tools/visual_guard/run_guard.py` for the visual guard) and thirteen scripts that are reachable only by filename: `build_hotspots.py`, `css_inventory.py`, `dom_nesting.py`, `import_chains.py`, `js_census.py`, `query_pstats.py`, `read_pyprof.py`, `report_numbers.py`, `sleepscan.py`, `thread_lineage.py`, `verify_frontend_report.py`, `check_pstats_consistency.py`, `check_live_providers.py`. A reference search over `docs/`, `.claude/`, `.github/`, `AGENTS.md`, `CODING_STANDARDS.md`, `STATUS.md`, `README.md` shows that ten of them are cited **only** from a Russian-language perf report — nobody discovers them from the CLI. Proposed: a `tools/cli.py` with sub-commands (`bench`, `profile`, `guard`, `gates`, `report`) and a `tools/README.md` index mapping each script to *what it measures* and *which document cites it*.
*Note:* the sharing that *does* exist is good — `cdp.py` is shared by the bench and the guard, `profile.py` is shared by `run_bench.py` and `run_guard.py`. The problem is the tail of one-off scripts, not the head.

**ARCH-2 — A single result envelope.**
`run_bench.py`, `run_pyprof.py` and `run_guard.py` each invent their own JSON shape (`aggregate`+`runs` / `profile_python_startup.json` / `pixels`+`css`+`capture`). A shared envelope — schema version, `git_commit`, `git_branch`, `git_dirty`, `code_fingerprint`, `n_attempted`, `n_valid`, per-key sample counts, machine/OS/WebView2/Python versions, and a uniform `error` field — would make the three tools composable and would fix F-WN-35-8 and F-WN-35-15 in one step.

**ARCH-3 — A scenario registry.**
Scenario knowledge is duplicated in three places: the `if/elif` chain in `bench_child.py:355-388`, the `argparse choices` list in `run_bench.py:216`, and the prose list in `.claude/skills/nedotify-perf/SKILL.md:20-21`. It has already drifted (F-WN-35-19). A `SCENARIOS = {"startup": scenario_startup, ...}` registry in `scenarios.py`, consumed by argparse, by the `--list` output and by the skill's generation step, removes the class of defect entirely.

**ARCH-4 — The visual guard needs a machine manifest before it can have goldens.**
Even once baselines exist, a pixel guard is only meaningful if the reference environment is declared: WebView2 build (`docs/perf/baseline.md:4` already pins 154.0.4258.53), Windows build, installed font set (the `custom` theme renders in Georgia — `fixtures.py:327` — so the font set is part of the contract), GPU/driver, and the DPR matrix. `capture.py:52` waits for `document.fonts.ready`, which guarantees *loaded* fonts, not *identical* fonts. Proposed: a `tools/visual_guard/manifest.json` written next to the goldens, a guard check that refuses to compare when the current manifest differs, and a documented `--rebaseline` procedure. Without this, a guard that runs only on one machine gives a guarantee that is weaker than it appears (F-WN-35-3).

**ARCH-5 — Promote the two static checkers into a `tools/gates/` package with a CI job.**
Both checkers exist, both are referenced by nothing, and both are broken in ways that would surface immediately once they were run over the right tree (F-WN-35-1, F-WN-35-2, F-WN-35-6). The Android side of the same repository already demonstrates the pattern that works — a hash-pinned source manifest that fails on any change until regenerated (`.github/workflows/android-source.yml`). The Windows side should get the equivalent: a `tools/gates/run_all.py` invoked as a second job in `.github/workflows/ci.yml`.

**ARCH-6 — Declare the dev-only dependencies.**
`psutil` (silently zero, F-WN-35-18) and `py-spy` (gracefully absent) are used by the harness but declared nowhere. A `requirements-bench.txt` with an explicit "dev-only, not shipped" marker would make both their presence and their absence loud.

**ARCH-7 — Separate "versioned evidence" from "scratch output".**
`tools/bench/results/` currently holds 47 committed files *and* receives every new run's output. Splitting it into a read-only, curated evidence directory (with a manifest and a per-file validity flag) and a gitignored run directory — the `NEDOTIFY_BENCH_OUT` mechanism already provides the second half — would remove the accidental-commit hazard (F-WN-35-16) and let the crashed runs be excluded from the evidence set (F-WN-35-8).

**ARCH-8 — Measure the hot paths the audit identified, or say so explicitly.**
The harness covers startup, idle CPU, renderer-CPU attribution, search (network-bound) and feed (network-bound). It does not cover play/resolve, download, library scan, settings load, LUFS decode, taste-profile rebuild, smart-playlist SQL or the proxy stream path. Some of those are now covered by pytest perf tests (`tests/test_playback_startup_performance.py`, `tests/test_stream_startup_performance.py`, `tests/test_lyrics_performance.py`, `tests/test_provider_performance.py`, `tests/test_cache_performance.py`), but the split between "pytest perf test" and "tools/bench scenario" is undocumented, so nobody can answer "is X measured?" without reading the whole repo. A one-page coverage matrix in `tools/README.md` — hot path → measuring tool → last measurement date → validity — would make the answerable question answerable.
