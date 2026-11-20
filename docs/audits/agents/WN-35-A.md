## AREA WN-35 — Tooling: performance bench & visual guard — ROLE A

### 1. Scope reviewed

**Files opened and read in full (line ranges actually read):**

- `docs/audits/WIN_AUDIT_CONTEXT.md` (1–200), `docs/audits/WIN_AUDIT_AREAS.md` (1–70), `.claude/skills/nedotify-perf/SKILL.md` (1–67)
- `tools/bench/__init__.py` (1), `tools/bench/cdp.py` (1–364), `tools/bench/procsampler.py` (1–194), `tools/bench/thread_lineage.py` (1–89)
- `tools/bench/read_pyprof.py` (1–47), `tools/bench/query_pstats.py` (1–77), `tools/bench/check_pstats_consistency.py` (1–46)
- `tools/bench/import_chains.py` (1–61), `tools/bench/dom_nesting.py` (1–289), `tools/bench/css_inventory.py` (1–476), `tools/bench/js_census.py` (1–417)
- `tools/bench/run_bench.py` (1–339), `tools/bench/scenarios.py` (1–470), `tools/bench/bench_child.py` (1–437)
- `tools/bench/profile.py` (1–330), `tools/bench/run_pyprof.py` (1–684), `tools/bench/pyprof_child.py` (1–702)
- `tools/bench/check_live_providers.py` (1–149), `tools/bench/build_hotspots.py` (1–352), `tools/bench/report_numbers.py` (1–131)
- `tools/bench/sleepscan.py` (1–144), `tools/bench/verify_frontend_report.py` (1–1228)
- `tools/visual_guard/__init__.py` (1), `tools/visual_guard/diff.py` (1–125), `tools/visual_guard/capture.py` (1–140), `tools/visual_guard/fixtures.py` (1–339), `tools/visual_guard/run_guard.py` (1–738)
- `tools/check_lock_nesting.py` (1–127), `tools/check_shadow_imports.py` (1–119)
- Supporting/trace-in reads: `main.py` (1–30, 140–234), `core/api.py` (550–609), `core/app.py` (grep of `_service_lock`, `Lock()`), `core/proxy.py` (grep of `port`/`token`), `services/youtube_service.py` (30–99, grep of `search`/`get_stream_url`/`_detect_browser_cookies`), `core/services/discord_rpc.py` (grep of `Lock`), `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.github/workflows/ci.yml`
- Artefacts/records inspected: `tools/bench/results/*` (all JSON + `profile_appcore_init.pstats`), `tools/visual_guard/reports/guard-20261006-*.json`, `docs/perf/prof_frontend.md`, `docs/perf/prof_python_startup.md`, `docs/perf/baseline.md` (path only)

**Callees traced into other areas (product defects found there are attributed to the owning area, not repeated here):**

- `core/api.py::_install_snap_layouts` — a **false positive** reported by `tools/check_shadow_imports.py` (see F-WN-35-11). The underlying code is *not* broken: `core/api.py:17` has a module-level `import time`, and the flagged `import time` at `core/api.py:581` lives inside the nested `_set_icon()` helper. **No product defect; ownership stays with WN-04 only if it were real.**
- `core/proxy.py::LocalProxyManager.port/.token` — used by `tools/bench/check_live_providers.py`; the attribute names are correct (`core/proxy.py:1268,1271`).
- `services/youtube_service.py::search/get_stream_url`, `services/soundcloud_service.py::search/get_stream_url`, `services/spotify_service.py::search` — the keyword arguments used by `check_live_providers.py` match the real signatures.
- `main.py:260` (`Local\NeDotify_App_Single_Instance_Mutex`) — matches `tools/visual_guard/run_guard.py:64`.

**Repo hygiene:** every tool that writes into the tree was run against a byte-identical backup and the tree was restored afterwards. `git status --porcelain` shows **229 changed entries before and after** this review; `tools/bench/results` hashes are identical to the backup; `tools/visual_guard/reports` was restored to its original two files.

---

### 2. Findings

#### F-WN-35-1  [P1] — The AGENTS.md lock checker never looks at the application code it claims to police

- **File:** `tools/check_lock_nesting.py:11` (and `:99-114`)
- **Confirmed:** yes
- **Description:** `ROOT = os.path.dirname(os.path.abspath(__file__))` resolves to `<repo>/tools`, so `os.walk(ROOT)` only ever visits the harness's own directory (29 tool files). `core/`, `services/`, `audio/`, `utils/` and `main.py` — where all 34 shipped `threading.Lock()` objects live — are **never scanned**. The tool prints "OK: no nested-lock self-deadlock patterns" and exits 0 while the application it was written for is untouched.
- **Cause:** one missing `dirname`. The sibling checker gets it right: `tools/check_shadow_imports.py:12` uses `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (repo root).
- **Trigger conditions:** always — the scan root is wrong, so the result is meaningless for every input.
- **User impact:** the governance tool gives false assurance. Its own docstring says three shipped deadlocks (`AppCore._service_lock`, `DiscordRPCService._lock`, "a Lock used across evaluate_js") "each froze the UI" — none of them can be found by this script. A new non-reentrant `Lock` nesting in shipped code passes silently.
- **Evidence:**
  ```python
  # tools/check_lock_nesting.py:11
  ROOT = os.path.dirname(os.path.abspath(__file__))     # -> <repo>/tools
  ...
  # tools/check_lock_nesting.py:101
  for dirpath, dirnames, filenames in os.walk(ROOT):
  ```
  vs.
  ```python
  # tools/check_shadow_imports.py:12
  ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # -> <repo>
  ```
  Shipped non-reentrant locks that are out of reach of the scanner (all `threading.Lock()`): `core/api.py:102,359,364,2119,2173`, `core/app.py:95`, `core/database.py:157`, `core/downloader.py:61,63,81`, `core/proxy.py:435`, `core/resolver.py:49`, `core/settings.py:307`, `core/tray.py:34`, `services/artist_service.py:47,49`, `services/base_service.py:78`, `services/lastfm_service.py:102,116`, `services/lyrics_service.py:37`, `services/soundcloud_service.py:136,139`, `services/taste_profile.py:27`, `services/track_resolver.py:27,102,103`, `services/watchdog_service.py:31`, `services/yandex_service.py:33`, `services/youtube_service.py:220`, `services/zapret_service.py:317`, `utils/cache_manager.py:33,37`, `utils/file_scanner.py:32`.
- **Reproduction / verification:** A/B on an identical copy of the tool with a synthetic `core/app.py` containing a textbook self-deadlock:
  ```
  === same tool, ROOT patched to the temp repo root ===
  POTENTIAL self-deadlocks (non-reentrant Lock held across a same-lock call):
    core\app.py: Demo.outer() holds self._service_lock and calls inner()
  EXIT= 1
  === same tool UNMODIFIED (ROOT = its own tools/ dir) ===
  OK: no nested-lock self-deadlock patterns
  EXIT=0
  ```
  and the scan scope measured directly:
  ```
  ROOT = C:\...\AURA_Music_main\tools
  py files scanned = 29      (all under tools/ — none under core/, services/, audio/, utils/)
  ```
- **Suggested fix:** change `ROOT` to the repository root (parent of `tools/`) and keep the `SKIP` set; add a unit test that plants a nested-`Lock` fixture under a non-`tools/` directory and asserts the tool flags it.
- **Fix side effects:** the first run over the real tree may report pre-existing findings (e.g. `core/api.py:359/364` `_lyrics_lock` / `_search_lock`, `core/downloader.py:61/63` `_queue_lock` / `_lock`). Those need triage, otherwise the gate stays red.
- **Discovered by:** A

---

#### F-WN-35-2  [P1] — The visual guard's pixel half is vacuous: there are no goldens, and an empty comparison reports PASS

- **File:** `tools/visual_guard/diff.py:93-125` (`compare_sets`), `tools/visual_guard/run_guard.py:44-45` (`GOLDENS`/`CURRENT`), `tools/visual_guard/run_guard.py:691`
- **Confirmed:** yes
- **Description:** `tools/visual_guard/goldens/` exists on disk but is **empty**, and it is **not tracked by git** (`git ls-files tools/visual_guard` lists only the five `.py` files). `compare_sets()` computes `ok = not failures and not missing`; with an empty golden set, `missing` is empty and `failures` is empty, so it returns `ok=True, compared=0`. The guard therefore passes the pixel half without comparing a single pixel, and the goldens can never be reproduced from the repository.
- **Cause:** the golden images were never committed and the "nothing compared" case is not treated as a failure.
- **Trigger conditions:** `run_guard.py --compare` on a fresh checkout (the normal case for a reviewer or CI).
- **User impact:** the "visual regression guard" that the skill and the docs advertise protects nothing. A UI regression in any of the 8 screens × 3 themes × 2 viewports × 2 DPRs is invisible; `run_guard.py` prints `pixels: 0/0 passed, 0 failed, 0 missing`, which reads as a pass.
- **Evidence:**
  ```python
  # tools/visual_guard/diff.py:113-118
  failures = [r for r in results if not r["ok"]]
  return {
      "ok": not failures and not missing,
      ...
      "compared": len(results),
  ```
  ```
  === compare_sets on the shipped tree ===
  GOLDENS = C:\...\tools\visual_guard\goldens exists = True
  {'ok': True, 'compared': 0, 'passed': 0, 'failed': 0, 'missing': [], 'unexpected': []}
  ```
  ```
  === git ls-files tools/visual_guard ===
  tools/visual_guard/__init__.py
  tools/visual_guard/capture.py
  tools/visual_guard/diff.py
  tools/visual_guard/fixtures.py
  tools/visual_guard/run_guard.py
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools\visual_guard\run_guard.py --compare` → real output:
  ```
  [guard] comparing 8 screens x 3 themes x 2 viewports x 2 dpr
  [guard]   pixels: 0/0 passed, 0 failed, 0 missing
  [guard]   css declarations: REGRESSION (2 changed, 302 removed, 89 added)
  ...
  [guard] RESULT: FAIL
  ```
  (exit code 1 — but only because of the CSS half; the pixel half contributed nothing.)
- **Suggested fix:** commit a golden set, or make `compare_sets` return `ok=False` with `reason="no_goldens"` when `compared == 0`; add the golden directory to git.
- **Fix side effects:** goldens are machine-specific (see F-WN-35-15) — committing them turns the guard into a cross-machine false-positive generator unless the capture is made deterministic (fixed font, disabled GPU raster, pinned DPR).
- **Discovered by:** A

---

#### F-WN-35-3  [P1] — The CSS half of the visual guard is permanently red: 293 of 302 "removed" declarations come from a deleted directory

- **File:** `tools/bench/results/animation_declarations.json` (the enforced baseline), `tools/visual_guard/run_guard.py:502-579` (`css_declaration_guard`), `tools/bench/css_inventory.py:423-433`
- **Confirmed:** yes
- **Description:** the committed guard baseline still references the **old** UI directory `ui/web_new/` (`ui/web_new/css/styles.css`, `ui/web_new/index.html`, `ui/web_new/js/*.js`), which no longer exists — the UI was renamed to `ui/web_new_v2/`. `css_declaration_guard()` therefore reports 302 removed declarations, of which **293 are phantom** (the file simply no longer exists) and only **9 are real** removals in the live tree. The 2 genuine regressions (`visual-polish.css` `backdrop-filter: blur(16px) saturate(160%)` → `blur(var(--glass-blur, 16px)) saturate(160%)`) are drowned in the noise, and 89 "added" entries are the whole legacy `ui/MACos_ui/interface.css` pack the baseline never covered.
- **Cause:** the baseline was recorded against the pre-rename tree and was never re-recorded; the guard's keying scheme (content-keyed, no line numbers) survives renames only if the baseline is regenerated.
- **Trigger conditions:** every `run_guard.py --compare` / `--all` run on the current tree.
- **User impact:** the guard cannot be used as a gate — it always fails, for a reason that has nothing to do with the current code. A reviewer who reads the 302-line removal list concludes the UI was gutted; it was not.
- **Evidence:**
  ```
  removed total 302 | OLD ui/web_new/: 293 | ui/web_new_v2/: 9
  real removals in the live tree:
      ui/web_new_v2/css/components/visual-polish.css|-webkit-backdrop-filter = blur(16px) saturate(160%)
      ui/web_new_v2/css/components/visual-polish.css|backdrop-filter = blur(16px) saturate(160%)
      ui/web_new_v2/index.html|backdrop-filter = blur(12px); background: rgba(0,0,0,0.65)
      ui/web_new_v2/js/library.js|transition = none
      ui/web_new_v2/js/library.js|transition = opacity 0.18s
      ui/web_new_v2/js/library.js|transition = opacity 0.22s ease, transform 0.22s ease
      ui/web_new_v2/js/library.js|transition = transform 0.25s ease, opacity 0.25s ease, max-height 0.3s ease
      ui/web_new_v2/js/search.js|animation = fadeIn 0.3s ease
      ui/web_new_v2/js/search.js|transition = transform 0.2s, background 0.2s
  ```
  ```python
  # tools/visual_guard/run_guard.py:546-547
  for k in sorted(base_keys - cur_keys):
      removed.extend(f"{k} = {v}" for v in base_map[k])
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from tools.visual_guard import run_guard as rg; print(rg.css_declaration_guard())"` → `ok=False, removed=302, changed=2, added=89, baseline_keys=99, current_keys=103, intersection_keys=67`; the 293 phantom keys all start with `ui/web_new/`.
- **Suggested fix:** re-record the baseline with `run_guard.py --write-css-baseline` (the sanctioned path — **not** `css_inventory.py`, whose own comment warns that writing the line-numbered inventory to the guard path makes the guard vacuous), and add a "baseline file no longer exists" check that reports a stale baseline as a distinct, actionable error instead of 293 removals.
- **Fix side effects:** re-recording makes the guard agree with the current tree by construction — that is a *deliberate* re-statement of the visual contract, and it must be reviewed, not scripted.
- **Discovered by:** A

---

#### F-WN-35-4  [P1] — `verify_frontend_report.py` crashes on a default Windows console and never prints the failures it exists to report

- **File:** `tools/bench/verify_frontend_report.py:1215-1228` (esp. `:1223`), module docstring `:3` ("Exits non-zero when a structural check fails. **Never raises.**")
- **Confirmed:** yes
- **Description:** the verifier prints `PASSED`, then `REPORTED` notes, then the `FAILED` list. The notes are printed *before* the failures, and `print("  NOTE:", r)` raises `UnicodeEncodeError` when a note contains a character outside the console codepage (this machine: cp1251) — the notes embed CSS/JS source lines containing Cyrillic. The process dies with a traceback and **the `FAILED` section is never printed**; the exit code is 1 for the wrong reason. A caller cannot distinguish "the document is stale (7 structural failures)" from "the verifier crashed".
- **Cause:** `sys.stdout` is never reconfigured, even though the project already knows the pattern — `tools/bench/run_bench.py:32-37` does exactly this ("The app logs Cyrillic; a cp1251 console would raise UnicodeEncodeError and kill the runner mid-report").
- **Trigger conditions:** any Windows console whose active codepage is not UTF-8 (the default for cp1251/cp866 machines) and any note containing non-ASCII — which is the case on the current tree.
- **User impact:** the only verifier that can tell you the recorded frontend report is stale is unusable as-is; the user sees a traceback instead of the list of stale claims.
- **Evidence:**
  ```
  File "...\tools\bench\verify_frontend_report.py", line 1223, in <module>
      print("  NOTE:", r)
  File "...\Lib\encodings\cp1251.py", line 19, in encode
      return codecs.charmap_encode(input,self.errors,encoding_table)[0]
  UnicodeEncodeError: 'charmap' codec can't encode characters in position 323-324: character maps to <undefined>
  ```
  With `PYTHONIOENCODING=utf-8` the same run produces the (hidden) failure list:
  ```
  FAILED 7
  FAIL: all 99 guard keys name a real scanned file under ui/ :: ui/web_new/css/styles.css|--app-bg-opacity; ...
  FAIL: report's '55 call sites' == artefact's 74 :: document says 55, artefact holds 74
  FAIL: report's "2 `document.createElement('img')`" == artefact's 3 :: document says 2, artefact holds 3
  FAIL: report's "2 `new Image()`" == artefact's 3 :: document says 2, artefact holds 3
  FAIL: all 143 hand-listed claim texts exist in the file they are cited in :: ui/web_new_v2/js/particles.js: '1000 / 15' is no longer in the file; ...
  FAIL: class .glass-panel present
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools\bench\verify_frontend_report.py` (no `PYTHONIOENCODING`) → `UnicodeEncodeError`, exit 1, no `FAILED` block. Then `& ".venv_win\Scripts\python.exe" -c "import os;os.environ['PYTHONIOENCODING']='utf-8';exec(open('tools/bench/verify_frontend_report.py',encoding='utf-8').read())"` → `FAILED 7`.
- **Suggested fix:** reconfigure `sys.stdout`/`sys.stderr` to UTF-8 at import (mirror `run_bench.py:32-37`), and print the `FAILED` block *before* the `REPORTED` notes so the failure list survives a crash in the note printer.
- **Fix side effects:** none — the output becomes readable on every codepage.
- **Discovered by:** A

---

#### F-WN-35-5  [P2] — The CDP client never reports a JavaScript exception: `evaluate()` returns `None` and the caller cannot tell

- **File:** `tools/bench/cdp.py:185-195` (`WSClient.evaluate`)
- **Confirmed:** yes
- **Description:** `Runtime.evaluate` returns `{"result": {"result": <RemoteObject>, "exceptionDetails": {...}}}` — `exceptionDetails` is nested **inside** the command result. `evaluate()` looks for it at the wrong level (`res.get("exceptionDetails")`, i.e. at the message root) and therefore never raises `CDPError` for a thrown exception; it returns `res["result"]["result"]["value"]`, which is `None` for an error RemoteObject. A JS exception is indistinguishable from "the expression returned null".
- **Cause:** wrong nesting level in the response path; the *value* path one level deeper is correct, which is why normal calls work.
- **Trigger conditions:** any `ctx.js(...)` / `sess.js(...)` call whose expression throws — including `capture.py`'s `_reset_js()` (the whole reset is wrapped in `try {} catch (e) {}` *and* the outer CDP check is blind), and `wait_for_js` (which then retries until a misleading `TimeoutError`).
- **User impact:** a broken driver script or a renamed DOM id silently produces a screenshot of the *previous* screen state, and a broken bench probe silently reports `null` instead of an error. In the visual guard this is how a wrong golden gets created.
- **Evidence:**
  ```python
  # tools/bench/cdp.py:185-195
  def evaluate(self, expression: str, timeout: float = 15.0,
               await_promise: bool = False):
      res = self.call("Runtime.evaluate", {...})
      details = res.get("exceptionDetails")          # <-- wrong level
      if details:
          raise CDPError(f"JS exception: {json.dumps(details)[:400]}")
      return res.get("result", {}).get("result", {}).get("value")
  ```
- **Reproduction / verification:** driven against a minimal local WebSocket server that answers with a spec-shaped `Runtime.evaluate` error reply:
  ```
  A) JS exception -> evaluate() returned None (no CDPError raised)
  B) normal evaluate -> True
  ```
- **Suggested fix:** read `res.get("result", {}).get("exceptionDetails")` and raise `CDPError` with `exceptionDetails.text` / `exception.description`.
- **Fix side effects:** previously silent probe failures will start raising; bench drivers that relied on `None` will need to tolerate the new exception (they already catch `CDPError` in `wait_for_js`).
- **Discovered by:** A

---

#### F-WN-35-6  [P2] — The `feed` scenario measures the harness's own timeout, not the feed build time

- **File:** `tools/bench/bench_child.py:308` vs `:320-326`; `tools/bench/bench_child.py:106-220` (`measure_feed`); `tools/bench/scenarios.py:467-470`
- **Confirmed:** yes
- **Description:** `install_event_recorder()` (which creates `window.__bench.pythonEvents`) is called **before** the `Page.reload()` that the "time to interactive" block performs. A reload replaces the document, so `window.__bench` is destroyed and the recorder is never re-installed. `measure_feed()` then polls `window.__bench.pythonEvents`, which is always `[]`, so the loop immediately satisfies "the event count stopped growing", waits its fixed `settle_deadline` (3 s) plus `time.sleep(2.0)`, and reports the elapsed time as `wall_ms`.
- **Cause:** ordering bug — the recorder is installed on a document that is about to be thrown away.
- **Trigger conditions:** every `feed` and `combo` run.
- **User impact:** the recorded "home-feed build time" is a **constant ~5 s**, i.e. the harness's timeout, not a measurement. The committed artefacts prove it: `feed.wall_ms = 5020.1 / 5030.0 / 5008.4 ms` across three reps, with `lastfm_requests = 14 / 0 / 0` — the wall time does not move even when the feed issued no requests at all.
- **Evidence:**
  ```python
  # tools/bench/bench_child.py:308
  ctx.sess.install_event_recorder()
  ...
  # tools/bench/bench_child.py:323-326
  ctx.sess.ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": READY_HOOK_JS})
  ctx.sess.ws.call("Page.reload", {"ignoreCache": False})
  ```
  ```python
  # tools/bench/bench_child.py:189-192  (measure_feed)
  got = self.js("(window.__bench && window.__bench.pythonEvents || [])"
                 ".filter(e => %s.indexOf(e.name) >= 0).length" % json.dumps(list(feed_events)))
  ```
  ```
  == combo-2000trk-20261004-095459.json
    run 0 ok=True  feed: {'wall_ms': 5020.1, 'lastfm_requests': 14, ...}
    run 1 ok=True  feed: {'wall_ms': 5030.0, 'lastfm_requests': 0,  ...}
    run 2 ok=True  feed: {'wall_ms': 5008.4, 'lastfm_requests': 0,  ...}
  ```
- **Reproduction / verification:** read `tools/bench/results/combo-2000trk-20261004-095459.json` (the three `wall_ms` values above); the code path is deterministic — `window.__bench` cannot survive a `Page.reload`.
- **Suggested fix:** re-install the recorder after the reload (or inject it with `Page.addScriptToEvaluateOnNewDocument`, as the capture mode already does at `:264-265`), and make `measure_feed` fail loudly when the event list stays empty.
- **Fix side effects:** the reported feed build time will change (it will become a real number); any doc quoting ~5 s must be updated.
- **Discovered by:** A

---

#### F-WN-35-7  [P2] — The import-graph resolver mis-links packages to their own submodules, so `import_chains.py` reports ancestry backwards

- **File:** `tools/bench/run_pyprof.py:135-150` (`_link_parents`), `tools/bench/import_chains.py:26-47`
- **Confirmed:** yes
- **Description:** `_link_parents` reverses the `-X importtime` rows on the assumption that the output is a post-order DFS in which "a parent appears after its children". That is false for a **package**: when Python imports `pkg.mod`, the package `pkg` is imported *while* `pkg.mod` is on the import stack, so `pkg` is printed **before** `pkg.mod` **and with a deeper indent**. The indent-stack algorithm then attaches the package to the submodule's subtree. Result: the tool claims `yt_dlp.extractor` was imported *by* `yt_dlp.extractor.afreecatv`.
- **Cause:** the reversal + "nearest previous node with smaller depth" heuristic cannot represent the package edge, which is parent-after-child in the printed order but parent-*deeper* in the indent.
- **Trigger conditions:** any package with lazily-loaded submodules — exactly the hot case (`yt_dlp.extractor` is ~164 ms of the startup import).
- **User impact:** `import_chains.py` answers the question it exists to answer ("who pulls this module in?") with an inverted chain for exactly the modules it targets (`yt_dlp.extractor`, `yt_dlp.extractor.common`).
- **Evidence:**
  ```
  --- RAW importtime lines mentioning yt_dlp.extractor ---
  'import time:       488 |        488 |                 yt_dlp.extractor'
  'import time:      2134 |       3246 |                 yt_dlp.extractor.common'
  'import time:      1604 |       5337 |               yt_dlp.extractor.afreecatv'
  --- after _link_parents: parent of each yt_dlp.extractor* node ---
    yt_dlp.extractor                         depth=8 parent=yt_dlp.extractor.afreecatv
    yt_dlp.extractor.common                  depth=8 parent=yt_dlp.extractor.afreecatv
    yt_dlp.extractor.afreecatv               depth=7 parent=yt_dlp.downloader.soop
  ```
  and the tool's own output:
  ```
  yt_dlp.extractor:
      yt_dlp.extractor(0.2) <- yt_dlp.extractor.afreecatv(3.7) <- yt_dlp.downloader.soop(3.9) <- ...
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools\bench\import_chains.py` (real output above) and the raw-`importtime` probe quoted here.
- **Suggested fix:** detect the package edge explicitly (a row whose name is a strict prefix of the next row's name and whose *printed order* is before it) and treat it as a parent edge; do not rely on a single reversal of the printed order.
- **Fix side effects:** `_families()` in `run_pyprof.py` depends on `rows[i]["parent"]` to pick the "outermost" nodes of a package family; fixing the edges changes `watched_families[*].cum_ms` in the recorded profile JSON and therefore the numbers quoted in `docs/perf/prof_python_startup.md`.
- **Discovered by:** A

---

#### F-WN-35-8  [P2] — The pstats consistency checker implements the inverse of its own documented rule and reports 22 false "inconsistencies"

- **File:** `tools/bench/check_pstats_consistency.py:1-6` (docstring), `:19-33`
- **Confirmed:** yes
- **Description:** the docstring states the rule as "If a **parent's** `cumtime` is smaller than a **child's**, the linkage is broken". The implementation computes `children_cum = sum(v[3] for v in callers.values())` — `v[3]` is the **caller's** cumulative time, i.e. the *parents'*, not the children's — and then flags rows where that sum exceeds `1.5 ×` the row's own cumtime. That is the *normal* case in cProfile (a parent's inclusive time always dominates its child's), so 22 of 714 rows are reported as "inconsistent" when they are perfectly consistent.
- **Cause:** the metric is mis-named and mis-derived; the comparison is the inverse of the documented one.
- **Trigger conditions:** every run of the checker against the committed `.pstats`.
- **User impact:** the tool that exists to tell the reader "this row must not be used as evidence" instead marks 22 good rows — including `youtube_service.py:209(_get_ydl_opts)` and `services/youtube_service.py:37(_detect_browser_cookies)`, which are exactly the hot spots the report relies on.
- **Evidence:**
  ```python
  # tools/bench/check_pstats_consistency.py:19-29
  for (fn, ln, name), (cc, nc, tt, ct, callers) in st.stats.items():
      rows[f"{Path(fn).name}:{ln}({name})"] = {
          "ncalls": nc, "tottime": tt, "cumtime": ct,
          "children_cum": sum(v[3] for v in callers.values()),   # <- callers' ct == PARENTS' cum
          ...
      if r["children_cum"] > r["cumtime"] * 1.5 + 1e-9 and r["children_cum"] > 1e-4:
          bad.append((key, r))
  ```
  ```
  rows: 714   inconsistent (children_cum >> cumtime): 22
    threading.py:975(start)          ncalls=17 cumtime=  1.165ms children_cum= 95.230ms
    youtube_service.py:114(__init__) ncalls=2  cumtime=  0.196ms children_cum= 54.342ms
    youtube_service.py:209(_get_ydl_opts) ncalls=2 cumtime=14.630ms children_cum=31.695ms   <- false positive
  ```
  Recomputing both metrics independently from the same `.pstats`:
  ```
  total rows 714
  tool-flagged (parents_sum > 1.5*cum): 22
  truly broken (true_children_cum > cum): 284      <- the rule the docstring actually describes
  both: 16
  ```
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools\bench\check_pstats_consistency.py` (output above) plus the independent recomputation of `true_children_cum` by inverting the `callers` map.
- **Suggested fix:** compute the *children's* cumulative time by inverting the `callers` map (for each row, sum `ct` of every row that lists it as a caller) and compare that against the row's own `cumtime`; rename the field to `parents_cum` if the parents' metric is wanted as well.
- **Fix side effects:** the count will change from 22 to 284, and the 284 will be dominated by cProfile's known thread-profiling artefacts (`threading.py` rows), so the check must also exclude rows whose children were profiled on another thread.
- **Discovered by:** A

---

#### F-WN-35-9  [P2] — `psutil` is undeclared, and without it the benchmark silently records *no* CPU/RAM data while still exiting 0

- **File:** `tools/bench/procsampler.py:18-21`, `:136-143`, `:145-149`, `:152-186`; `requirements.txt`, `requirements-dev.txt`
- **Confirmed:** yes
- **Description:** `psutil` is used by `procsampler.py` and by `pyprof_child.py::_cpu_times`/`_os_thread_cpu`, but it appears in **neither** `requirements.txt` **nor** `requirements-dev.txt`. `procsampler.py` documents the omission ("owner-approved as a dev-only tool; it is not added to requirements.txt"), but the dev requirements file does not carry it either. When the import fails, `psutil = None` and `ProcSampler.start()` returns **without starting the sampling thread**; `stop()` returns `[]` and `summary()` returns `{}`.
- **Cause:** an undeclared optional dependency that degrades silently instead of failing.
- **Trigger conditions:** any checkout or CI image that installs only the declared requirements (`ci.yml` does exactly `pip install -r requirements.txt -r requirements-dev.txt`).
- **User impact:** the bench reports "no CPU data" instead of "the sampler is unavailable", and `run_bench.py` still returns exit code 0 (`return 0 if ok_runs else 1` — the child's exit code is 0). Every idle/CPU number in the result JSON is simply absent, and `"summary": {}` is easy to mistake for "no measurable load".
- **Evidence:**
  ```python
  # tools/bench/procsampler.py:18-21
  try:
      import psutil
  except ImportError:  # pragma: no cover
      psutil = None
  ...
  # tools/bench/procsampler.py:136-143
  def start(self) -> "ProcSampler":
      if psutil is None:
          return self          # <- no thread started, no error
  ```
  ```
  === procsampler with psutil MISSING (simulating a fresh checkout) ===
  procsampler.psutil is None
  n_samples = 0
  summary   = {}
  ```
  ```
  # requirements-dev.txt (complete)
  pytest==9.1.1
  pytest-asyncio==1.4.0
  ```
- **Reproduction / verification:** simulate the missing import (as above) and observe `summary() == {}`; `Select-String -Path requirements.txt,requirements-dev.txt -Pattern psutil` → no match.
- **Suggested fix:** add `psutil` to `requirements-dev.txt` (it is dev-only and must not reach `requirements.txt`, per the shipped-app rule), and make `ProcSampler.start()` raise (or record `"psutil_unavailable": true`) instead of returning an empty sampler.
- **Fix side effects:** none for the shipped app; the bench gains a hard dependency on a dev-only wheel.
- **Discovered by:** A

---

#### F-WN-35-10  [P2] — Every recorded perf artefact is stale; the two perf documents no longer describe the tree

- **File:** `docs/perf/prof_frontend.md`, `docs/perf/prof_python_startup.md`, `tools/bench/results/profile_appcore_init.pstats`, `tools/bench/results/animation_declarations_inventory.json`, `tools/bench/results/backdrop_nesting.json`, `tools/bench/results/frontend_hotspots.json`, `tools/bench/results/css_blur_map.json`
- **Confirmed:** yes
- **Description:** re-running the static analysers on the current tree produces different artefacts from the committed ones, and the committed `.pstats` describes code that no longer exists. Quantified below.
- **Cause:** the artefacts are regenerated by hand ("Every artefact here is regenerated by hand", `verify_frontend_report.py:30-32`) and the tree has moved on since 2026-10-03/04.
- **Trigger conditions:** reading either perf document as evidence about the current product.
- **User impact:** any performance conclusion drawn from these documents is about a tree that is 33 JS files and ~500 DOM elements behind. The `nedotify-perf` skill already warns "They are dated observations, not measurements of the current checkout" — the finding is that the artefacts are *far* more stale than "dated": they are wrong, and the verifier that exists to catch that is itself broken (F-WN-35-4).
- **Evidence:**
  ```
  # artefacts regenerated now vs committed
  backdrop_nesting counts  committed: {'dom_nodes': 1435, 'records': 60, ...}
  backdrop_nesting counts  regenerated: {'dom_nodes': 1940, 'records': 56, ...}
  inventory counts committed: {'total_declarations_parsed': 4232, 'guard_declarations': 302}
  inventory counts regenerated: {'total_declarations_parsed': 4384, 'guard_declarations': 315}
  animation_declarations_inventory.json  committed=75ADDA7C9F51  regenerated=FC77F8CD71D4  DIFFERENT
  css_blur_map.json                       committed=5DBC0425B75A  regenerated=6625EDCD9A78  DIFFERENT
  backdrop_nesting.json                   committed=28C634669A6D  regenerated=EF18ECD19658  DIFFERENT
  frontend_hotspots.json                  committed=568F6F924993  regenerated=A63B193D4370  DIFFERENT
  ```
  ```
  # verify_frontend_report.py against docs/perf/prof_frontend.md
  FAILED 7
  FAIL: report's '55 call sites' == artefact's 74 :: document says 55, artefact holds 74
  FAIL: report's "2 `document.createElement('img')`" == artefact's 3
  FAIL: report's "2 `new Image()`" == artefact's 3
  FAIL: all 143 hand-listed claim texts exist in the file they are cited in :: ...
  FAIL: class .glass-panel present
  NOTE: first-party JS files: live=33 recorded=22 [DIFFERS]
  NOTE: first-party JS lines: live=18807 recorded=15413 [DIFFERS]
  NOTE: inventory: 208/302 line anchors have drifted
  NOTE: blur map: 55/81 line anchors have drifted
  NOTE: backdrop_nesting.json: 52/60 records point at a line that no longer holds their declaration
  NOTE: track_row_nodes.json: template_source.lines says '338-368', but createTrackElement is at line 688
  NOTE: report: 17 of 100 file:line citations no longer resolve to a real, non-blank line
  ```
  ```
  # docs/perf/prof_python_startup.md - 21 of 97 file:line citations no longer resolve
  core/app.py:93 is blank | core/database.py:107 is blank | services/youtube_service.py:24 is blank
  utils/_utils.py:4822 (file missing) | utils/_utils.py:1478 (file missing)
  services/lyrics_service.py:336 out of range (327 lines) | ...
  ```
  ```
  # the committed .pstats targets code that has moved
  core/app.py:93(__init__)            -> current core/app.py:94
  core/database.py:79(__init__)       -> current core/database.py:151
  services/youtube_service.py:114(__init__) -> current :192
  services/youtube_service.py:171(_get_ydl)  -> current :253
  api.py:68(_connect)                 -> core/api.py has no _connect at all
  ```
  (`check_pstats_consistency.py:35-37` looks these up with `if key in rows:` — so the stale key is simply skipped and the "specific rows" section silently prints 5 of 6 entries.)
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools\bench\verify_frontend_report.py` (with `PYTHONIOENCODING=utf-8`); the regeneration diff above; the citation scan over `docs/perf/prof_python_startup.md`.
- **Suggested fix:** re-run `run_pyprof.py` / `css_inventory.py` / `dom_nesting.py` / `build_hotspots.py` and re-write both documents, or mark them explicitly as "snapshot of <commit>" with the commit id so a reader can tell how old they are; make `check_pstats_consistency.py`'s hard-coded line targets derive from the tree instead of literals.
- **Fix side effects:** the refreshed numbers will differ from the documents; `docs/perf/baseline.md` cross-references must be updated in the same pass.
- **Discovered by:** A

---

#### F-WN-35-11  [P2] — The shadow-import checker false-positives on nested helpers, so it always fails on a clean tree

- **File:** `tools/check_shadow_imports.py:31-46` (`_own_body`), `:49-80` (`local_imports`, `used_before`), `:83-115`
- **Confirmed:** yes
- **Description:** `_own_body` is documented as "Walk a function's own body, NOT descending into nested defs/lambdas", but it only filters nested definitions that are **direct children of the function body**. When a nested helper sits inside an `if`/`try`/`for`/`with` block, the enclosing block node is yielded and `local_imports()` / `used_before()` then call `ast.walk(node)` on it — which re-descends into the nested helper. The tool therefore reports the helper's local import as if it were the outer function's.
- **Cause:** the "own body" filter is applied to the traversal stack, but the per-node `ast.walk()` re-introduces the whole subtree.
- **Trigger conditions:** any function whose nested helper performs a function-local import — the exact shape of `core/api.py::_install_snap_layouts`.
- **User impact:** the tool's only output on the current tree is **wrong**: it claims `core/api.py::_install_snap_layouts()` "uses 'time' at line 570 but imports it locally at line 581" — but line 581 is inside the nested `_set_icon()` helper, and `core/api.py:17` has a module-level `import time`, so line 570 is perfectly safe. The gate exits 1 on a clean tree, so it will be ignored, and a genuine shadowing bug would be indistinguishable from the noise.
- **Evidence:**
  ```
  SHADOWING function-local imports (UnboundLocalError risk):
    core\api.py: _install_snap_layouts() uses 'time' at line 570 but imports it locally at line 581
  EXIT=1
  ```
  ```python
  # core/api.py:17  ->  import time      (module level)
  # core/api.py:579 ->  def _set_icon():
  # core/api.py:581 ->      import time  (inside the nested helper)
  # core/api.py:570 ->  time.sleep(delay)
  ```
  A/B on a synthetic fixture with the same shape (module-level `import time`, nested helper inside a `try:`):
  ```
  === repo tool over the fixture ===
  SHADOWING function-local imports (UnboundLocalError risk):
    mod\safe_try.py: outer() uses 'time' at line 6 but imports it locally at line 14
  EXIT = 1
  ```
  With the traversal corrected (never descending into a nested `FunctionDef`/`ClassDef`/`Lambda`), the same fixture tree yields **0** findings, while the deliberately unsafe fixture is still caught:
  ```
  CORRECTED tool finds: unsafe.py outer time use@ 5 import@ 6
  ```
  Applying the corrected traversal to the whole shipped tree yields **0 true shadowing findings** — i.e. the repo is clean and the tool's single report is a false positive.
- **Reproduction / verification:** run `tools/check_shadow_imports.py` (exit 1 with the `core/api.py` line above), then re-run with the corrected traversal to get 0 findings.
- **Suggested fix:** replace the `ast.walk(node)` calls in `local_imports`/`used_before` with a traversal that never descends into a nested `FunctionDef`/`AsyncFunctionDef`/`Lambda`/`ClassDef` (e.g. reuse `_own_body`'s generator directly).
- **Fix side effects:** the gate turns green on the current tree; a regression test with the `mod/safe_try.py` and `mod/unsafe.py` fixtures should be added.
- **Discovered by:** A

---

#### F-WN-35-12  [P2] — The pixel-diff budget makes a 1-px layout shift of a small element undetectable, and only failing images surface their bbox

- **File:** `tools/visual_guard/diff.py:21-22`, `:43-70`; `tools/visual_guard/run_guard.py:691-699`
- **Confirmed:** yes
- **Description:** the pass criterion is a **ratio** (`<= 0.1 %` of all pixels). At 1280×800 that budget is 1024 pixels, so a 1-px vertical shift of an element narrower than ~500 px changes fewer pixels than the budget and is reported as **PASS**. The bbox of a *passing* image is computed but never surfaced: `run_guard.py` prints only `pixel["failures"]`.
- **Cause:** a fixed fractional budget applied to images of very different content area, combined with a report that hides sub-threshold signal.
- **Trigger conditions:** any small element moves by 1 CSS px (a button, an icon, a badge) — a very common regression.
- **User impact:** a genuine 1-px layout shift in the player bar or the settings panel passes the guard silently. The tool's own docstring says the task "explicitly requires eyeballing differences, not trusting the number alone", but nothing is produced for a passing image.
- **Evidence:**
  ```
  1px shift of 1000px-wide bar       ok=False  diff_px= 2000  ratio=0.001953  bbox=[100, 300, 1100, 341]
  2px shift of 1000px-wide bar       ok=False  diff_px= 4000  ratio=0.003906  bbox=[100, 300, 1100, 342]
  1px shift of 200px-wide button     ok=True   diff_px=  400  ratio=0.000391  bbox=[100, 300, 300, 341]
  identical                            -> {'ok': True, 'diff_pixels': 0, ...}
  uniform +2/255 shift                 -> {'ok': True, 'diff_pixels': 0, 'max_channel_delta': 2}   (AA tolerance behaves as documented)
  40x40 icon tint +10/255             -> {'ok': False, 'diff_pixels': 1600, 'diff_ratio': 0.001563}
  ```
  ```python
  # tools/visual_guard/diff.py:22
  DIFF_PIXEL_RATIO_LIMIT = 0.001
  ```
- **Reproduction / verification:** the synthetic diff probe above (numpy/PIL, no app required): draw a 1000-px bar, then the same bar shifted down 1 px → 2000 differing pixels (FAIL); draw a 200-px button shifted 1 px → 400 differing pixels, `ok=True` (PASS).
- **Suggested fix:** report the bbox and diff count for *every* compared image (not only failures), and add an absolute per-region criterion (e.g. a changed bounding box wider than N px is a failure regardless of the global ratio).
- **Fix side effects:** a stricter rule will surface pre-existing sub-threshold drift in any future golden set, so the golden set must be re-recorded at the same time.
- **Discovered by:** A

---

#### F-WN-35-13  [P2] — `scenario_idle_states` documents a "visible+playing" state it never measures

- **File:** `tools/bench/scenarios.py:246-294` (esp. the docstring at `:248-251` and the comment at `:278-286`)
- **Confirmed:** yes
- **Description:** the docstring promises three states — "visible+playing, visible+idle, and minimised" — but the implementation samples `visible_idle`, `minimized`, `restored`. The comment "start playback on a real library track so the progress loop is live" is followed by code that only calls `window.pywebview.api.get_library()` and assigns `window.__benchTrack`; **no playback is ever started**.
- **Cause:** the code was never completed; the comment describes the intent, not the behaviour.
- **Trigger conditions:** every `idle_states` run.
- **User impact:** the "visible+playing" idle figure — arguably the most interesting one for a music player — is missing, and the recorded artefact presents three states while measuring two. A reader of `docs/perf/*` cannot tell that the playing state was never taken.
- **Evidence:**
  ```python
  # tools/bench/scenarios.py:248-251
  """Idle CPU/RAM in the three states the task names.

  visible+playing, visible+idle, and minimised. ...
  """
  # tools/bench/scenarios.py:278-286
  # start playback on a real library track so the progress loop is live
  try:
      ctx.js_async("""(async () => {
          const t = await window.pywebview.api.get_library();
          if (t && t.length) { window.__benchTrack = t[0]; }
          return true;
      })()""", timeout=30.0)
  ```
  ```
  # recorded states in tools/bench/results/idle_states-2000trk-20261004-103547.json
  states: ['visible_idle', 'minimized', 'restored']
  ```
- **Reproduction / verification:** read `tools/bench/scenarios.py:246-294` — no `play_track` / `play` bridge call exists in the file at all (`Select-String -Path tools\bench\scenarios.py -Pattern "play"` → only the comment).
- **Suggested fix:** either implement the playing state (call the bridge's play API and wait for `track_changed`) or correct the docstring and the recorded labels.
- **Fix side effects:** starting playback in the bench touches the app's playback path inside the scratch profile — acceptable, but it must not reach the user's real library.
- **Discovered by:** A

---

#### F-WN-35-14  [P2] — The `search` scenario is not hermetic: it fans out to the live providers, contradicting the harness's own contract

- **File:** `tools/bench/scenarios.py:1-10` (module docstring), `:415-464` (`SEARCH_JS`, `scenario_search`)
- **Confirmed:** yes
- **Description:** the module docstring states "Scenarios must be hermetic: no network, no writes outside the scratch profile, no dependence on wall-clock time or random data." `SEARCH_JS` calls `window.pywebview.api.search(query, 'all')` — the **real** bridge search, which fans out to YouTube / SoundCloud / Spotify / VK / Yandex. The recorded medians show the consequence: `847.7 ms`, `8422.8 ms`, `8298.4 ms` across three reps of the same query — a 10× spread driven by the network and by the providers' anti-bot behaviour, not by the app.
- **Cause:** the scenario measures the real user flow (a deliberate choice, per the inline comment) but the hermeticity contract was never enforced or amended.
- **Trigger conditions:** every `search` and `combo` run.
- **User impact:** the recorded "search fan-out" numbers are not reproducible and cannot be compared before/after; they also make live requests to third-party providers on every bench run (rate limiting / ToS exposure), and the bench's "no network" promise in the skill and the docstring is false.
- **Evidence:**
  ```python
  # tools/bench/scenarios.py:415-445 (SEARCH_JS)
  window.pywebview.api.search(query, 'all');
  ...
  # tools/bench/scenarios.py:3-6
  Scenarios must be hermetic: no network, no writes outside the scratch profile, ...
  ```
  ```
  == combo-2000trk-20261004-095459.json
    run 0 search: {'query': 'Daft Punk', 'rounds': 2, 'medianMs': 847.7}
    run 1 search: {'query': 'Daft Punk', 'rounds': 2, 'medianMs': 8422.8}
    run 2 search: {'query': 'Daft Punk', 'rounds': 2, 'medianMs': 8298.4}
  ```
- **Reproduction / verification:** the recorded JSON above; `tools/bench/scenarios.py:438` is the only network-triggering call in the file.
- **Suggested fix:** split the scenario into a hermetic local-search measurement (the seeded FTS5 index, as the visual-guard fixtures already do) and an explicitly-labelled live-provider measurement, and record which one produced each number.
- **Fix side effects:** the "search fan-out" number the audit refers to would no longer be measured end-to-end unless the live variant is kept and clearly labelled.
- **Discovered by:** A

---

#### F-WN-35-15  [P2] — The visual-guard capture has no readiness assertion: a slow machine captures a half-rendered golden

- **File:** `tools/visual_guard/capture.py:49-70` (`_SETTLE_JS`), `:83-121` (`capture_one`); `tools/visual_guard/fixtures.py:169-251` (screen drivers)
- **Confirmed:** yes
- **Description:** each screen driver is a **fixed sleep** (library 1200 ms, search 900 ms, artist 900 ms, settings 900 ms, player 700 ms, lyrics 900 ms) with no assertion that the content it wanted actually appeared. The driver *does* return counts (`{ resultChildren: res.children.length }`, `{ rows: el.children.length }`), but `capture_one` only stores them in `driver_status` — nothing checks them, and `driver_error` is only set when the JS call itself throws. A machine slower than the developer's produces a golden of an empty list. Additionally `_reset_js()` wraps its whole body in a single `try { ... } catch (e) {}`, so if `window.showPage` is missing the reset silently aborts half-way and the "next" capture inherits the previous screen's state.
- **Cause:** time-based instead of state-based synchronisation, and no validation of the returned status.
- **Trigger conditions:** any capture on a machine slower than the reference machine, or after a UI rename that breaks a driver.
- **User impact:** the golden set becomes a snapshot of the machine's speed rather than of the UI. Every later comparison then reports a diff that has nothing to do with a code change (or, worse, blesses a broken screen as the baseline).
- **Evidence:**
  ```python
  # tools/visual_guard/fixtures.py:195-201  (library driver)
  "library": """
    (async () => {
      window.showPage('library');
      await new Promise(r => setTimeout(r, 1200));
      const el = document.getElementById('lib-active-tracks');
      return { view: 'library', rows: el ? el.children.length : -1 };
    })()
  """,
  # tools/visual_guard/capture.py:107-119  (status recorded, never checked)
  rec = {..., "driver_status": status, "driver_error": err, "page_info": info}
  # tools/visual_guard/capture.py:22-46  (_reset_js: one try/catch around everything)
  ```
  ```python
  # tools/visual_guard/capture.py:22-24
  """Return every screen to a known state before the next capture."""
  return """
    (async () => {
      try {
        ...
        window.showPage('home');
  ```
- **Reproduction / verification:** read `tools/visual_guard/fixtures.py:169-251` (all drivers are `setTimeout`-based) and `tools/visual_guard/capture.py:83-121` (no validation of `driver_status`). The `driver_status` values are stored in `tools/visual_guard/reports/guard-*.json` but never asserted anywhere in `run_guard.py`.
- **Suggested fix:** poll for the expected state (e.g. `document.getElementById('lib-active-tracks').children.length > 0`) with a timeout, and make a driver that returns an unexpected count fail the capture instead of writing a golden.
- **Fix side effects:** captures become slower (bounded by the poll timeout) but deterministic.
- **Discovered by:** A

---

#### F-WN-35-16  [P2] — `run_bench.aggregate()` silently discards failed repetitions but reports the total as `n_runs`

- **File:** `tools/bench/run_bench.py:196-209` (`aggregate`), `:293-335` (`main`), `:196-209`
- **Confirmed:** yes
- **Description:** `aggregate()` flattens each run and takes the median over the runs that produced a value; a failed run contributes no leaves and is therefore dropped **silently**, while `agg["n_runs"]` is `len(runs)` — the number of *attempted* reps. The process exit code is `0 if ok_runs else 1`, i.e. **0 when even one rep succeeded**. The skill's own rule ("Report medians and repetition counts from the result JSON; check exit codes and error fields before accepting a sample. **Do not silently discard failed samples**") is violated by the tool that produces the JSON.
- **Cause:** no per-key sample count and no separation of accepted vs rejected runs.
- **Trigger conditions:** any bench run where at least one rep fails (common: "Another instance of NeDotify is already running", see `tools/bench/results/combo-2000trk-20261004-094813.json`, where all 5 runs have `ok=False`).
- **User impact:** a result file can claim `n_runs: 5` while the median is computed from 1 sample, and the runner exits 0. A before/after comparison can therefore be built on a single noisy sample.
- **Evidence:**
  ```python
  # tools/bench/run_bench.py:196-209
  def aggregate(runs: list[dict]) -> dict:
      per_run = []
      for r in runs:
          flat: dict = {}
          _flatten({"cold_start": r.get("cold_start"), "child": r.get("child")}, "", flat)
          per_run.append(flat)
      keys = sorted({k for f in per_run for k in f})
      agg = {}
      for k in keys:
          med = _median([f.get(k) for f in per_run])
          if med is not None:
              agg[k] = med
      return {"n_runs": len(runs), "medians": agg}      # <- n_runs counts FAILED reps too
  # tools/bench/run_bench.py:335
  return 0 if ok_runs else 1
  ```
  ```
  # tools/bench/results/combo-2000trk-20261004-094813.json  (5 reps, all failed)
    run 0 ok= False exit= 0   search: {}   feed: {}
    ... (runs 1..4 identical)
  ```
- **Suggested fix:** record `n_accepted` / `n_failed` next to each median, exclude failed reps from the key set explicitly (and log them), and return a non-zero exit code when any rep fails.
- **Fix side effects:** scripts that consume `aggregate.n_runs` will need to switch to the new counters; the recorded result files use the old shape.
- **Discovered by:** A

---

#### F-WN-35-17  [P2] — Coverage gap: no bench scenario exercises the play path or the download path

- **File:** `tools/bench/scenarios.py:296-470` (all scenarios), `tools/bench/run_bench.py:214-269` (`--scenario` choices)
- **Confirmed:** yes
- **Description:** the harness has `startup`, `idle`, `idle_states`, `cpu_attribution`, `scroll`, `search`, `feed`, `combo`. There is **no** scenario for the **play path** (resolve → proxy → `<audio>` play) and **none** for the **download path** (queue → worker → `download_complete`). `scenario_idle_states` claims a playing state but never starts playback (F-WN-35-13); `check_live_providers.py` probes provider search/resolve outside the bench harness and does not drive the app at all.
- **Cause:** the harness grew around the frontend/startup questions of one pass and was never extended to the other two hot paths.
- **Trigger conditions:** always — the coverage simply is not there.
- **User impact:** the two paths the audit brief names as critical (play and download) have **no** reproducible measurement. Any statement about their cost in `docs/perf/*` rests on the cProfile of `AppCore()` construction only.
- **Evidence:**
  ```
  # tools/bench/run_bench.py:215-217
  ap.add_argument("--scenario", default="startup",
                  choices=["startup", "idle", "idle_states", "cpu_attribution",
                           "scroll", "search", "feed", "combo"])
  ```
  No scenario references `play`, `download`, `resolve`, or the proxy beyond `scenario_backdrop_live`.
- **Suggested fix:** add a `play` scenario (seeded local track → bridge play → assert `track_changed` → measure time-to-first-audio and the proxy's first-byte latency) and a `download` scenario (seeded download → assert `download_complete` → measure queue latency and worker CPU).
- **Fix side effects:** the download scenario needs a writable scratch library and must never touch `~/.nedotify/`; the play scenario needs a real audio file, which the current fixture generator does not produce (only cover PNGs).
- **Discovered by:** A

---

#### F-WN-35-18  [P3] — The capture has no cross-machine determinism: system fonts, no raster control, and uncommitted goldens

- **File:** `tools/visual_guard/fixtures.py:277-294` (`_ls`), `:309-336` (`THEMES`), `:338-339` (`VIEWPORTS`, `DPRS`); `tools/visual_guard/capture.py:49-70`
- **Confirmed:** yes
- **Description:** the dark/light fixtures use `font_family: "system"` and the custom theme uses `Georgia` — both resolved by the OS. `_SETTLE_JS` waits for `document.fonts.ready`, which guarantees the *webfonts* are loaded but says nothing about the system font stack, the Windows font version, ClearType/hinting settings, or the GPU rasteriser. No `--font-render-hinting`, `--disable-gpu` or `--force-device-scale-factor` argument is passed to WebView2. Because no golden is committed (F-WN-35-2), a golden captured on one machine produces 100 % "regressions" on another.
- **Cause:** the capture is deterministic *within* a machine, not across machines, and the baseline is machine-local.
- **Trigger conditions:** sharing the guard output between developers or CI agents.
- **User impact:** every future golden set is a per-machine artefact; the guard cannot be a shared, reviewable contract.
- **Evidence:**
  ```python
  # tools/visual_guard/fixtures.py:277-294
  def _ls(theme: str, glass: bool, blur: int, primary: str, accent: str, font: str) -> dict:
      return {
          ...
          "nedotify_interface_font_family": _json.dumps(font),
      }
  # tools/visual_guard/fixtures.py:311 / :319  -> font "system"
  # tools/visual_guard/fixtures.py:327           -> font "Georgia"
  ```
- **Reproduction / verification:** read `tools/visual_guard/fixtures.py:277-336`; the WebView2 argument list in `tools/bench/profile.py:296` is `--remote-debugging-port=... --disable-background-timer-throttling` only.
- **Suggested fix:** embed a fixed webfont in the fixture, pin the font stack, and add the WebView2 flags that make raster deterministic (`--disable-lcd-text`, `--force-color-profile=srgb`, `--disable-gpu`).
- **Fix side effects:** the shipped UI's "system" font appearance is no longer what the golden shows — the guard would then guard the fixture's font, not the user's font.
- **Discovered by:** A

---

#### F-WN-35-19  [P3] — `import_chains.py` puts `tools/bench` on `sys.path`, shadowing the stdlib `profile` module

- **File:** `tools/bench/import_chains.py:12-13`; contrast `tools/bench/run_pyprof.py:40-50`
- **Confirmed:** yes
- **Description:** `import_chains.py` does `sys.path.insert(0, str(Path(__file__).resolve().parent))` and then `import run_pyprof as R`. That directory contains `profile.py`, which shadows the stdlib `profile` module. `run_pyprof.py` documents the hazard explicitly for its own children ("``tools/bench`` must NOT go on ``sys.path``: ``tools/bench/profile.py`` shadows the stdlib ``profile`` module, which ``cProfile`` needs") and `pyprof_child.py::_bootstrap()` removes the directory for the same reason — but `import_chains.py` re-introduces it in the parent process.
- **Cause:** the invariant is enforced in two places and violated in a third.
- **Trigger conditions:** always, for `import_chains.py`; it becomes a hard failure the moment anything in that process imports `profile` (e.g. `cProfile`, `pstats`, or a future helper).
- **User impact:** latent, not currently triggered — the tool currently runs. It is a trap for the next person who adds a `cProfile` step to this script.
- **Evidence:**
  ```python
  # tools/bench/import_chains.py:12-13
  sys.path.insert(0, str(Path(__file__).resolve().parent))
  import run_pyprof as R  # noqa: E402
  # tools/bench/run_pyprof.py:42-45
  """``tools/bench`` must NOT go on ``sys.path``: ``tools/bench/profile.py``
  shadows the stdlib ``profile`` module, which ``cProfile`` needs."""
  ```
- **Reproduction / verification:** read the two files; `tools/bench/profile.py` exists (`ls tools/bench/profile.py`).
- **Suggested fix:** import `run_pyprof` by path (`importlib.util.spec_from_file_location`, as `run_pyprof._load_sleepscan()` already does) instead of by `sys.path` entry.
- **Fix side effects:** none.
- **Discovered by:** A

---

#### F-WN-35-20  [P3] — `run_bench.py --list` advertises fewer scenarios than the tool accepts

- **File:** `tools/bench/run_bench.py:246-248` vs `:215-217`
- **Confirmed:** yes
- **Description:** `--list` prints `scenarios: startup, idle, scroll, search, feed, combo` — it omits `idle_states` and `cpu_attribution`, both of which are valid `--scenario` choices and both of which the `.claude/skills/nedotify-perf/SKILL.md` lists.
- **Cause:** the `--list` string was not kept in sync with `choices=[...]`.
- **Trigger conditions:** always.
- **User impact:** minor discovery defect — the two scenarios that produced the "idle while minimised" and "where does the idle CPU go" evidence are not advertised.
- **Evidence:**
  ```python
  # tools/bench/run_bench.py:246-248
  if args.list:
      print("scenarios: startup, idle, scroll, search, feed, combo")
      return 0
  # tools/bench/run_bench.py:215-217
  ap.add_argument("--scenario", default="startup",
                  choices=["startup", "idle", "idle_states", "cpu_attribution",
                           "scroll", "search", "feed", "combo"])
  ```
  ```
  === run_bench.py --list ===
  scenarios: startup, idle, scroll, search, feed, combo
  === argparse choices ===
  [--scenario {startup,idle,idle_states,cpu_attribution,scroll,search,feed,combo}]
  ```
- **Suggested fix:** derive the `--list` output from the same `choices` list.
- **Fix side effects:** none.
- **Discovered by:** A

---

#### F-WN-35-21  [P3] — The CDP WebSocket client can interleave frames: pong is written from the receive thread without a write lock

- **File:** `tools/bench/cdp.py:107-115` (`_send_frame`), `:117-151` (`_recv_loop`), `:153-168` (`call`)
- **Confirmed:** hypothesis (code-level defect confirmed; a real interleaving was not observed in this run)
- **Description:** `_send_frame` writes to the socket with no lock. `call()` sends a request from the caller thread; `_recv_loop` may send a **pong** (`opcode 0xA`) from its own thread at the same moment (`cdp.py:134-136`). Two concurrent `sendall` calls on the same socket can interleave their bytes and corrupt a frame.
- **Cause:** the `_lock` protects only the pending-response map, not the socket write path.
- **Trigger conditions:** a CDP server that sends a ping while the client is issuing a command — rare with Chromium's DevTools endpoint, but not impossible.
- **User impact:** a corrupted frame would surface as a `CDPError("connection closed while waiting for ...")` or a hung `call()` — i.e. an unexplained bench failure.
- **Evidence:**
  ```python
  # tools/bench/cdp.py:134-136   (receive thread)
  if opcode == 0x9:
      self._send_frame(data, opcode=0xA)
      continue
  # tools/bench/cdp.py:107-115   (no lock around self._sock.sendall)
  def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
      ...
      self._sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
  ```
- **Reproduction / verification:** not reproduced in this run (no live CDP endpoint was available); the defect is visible in the code — the same `self._lock` that guards `self._pending` is not used for writes.
- **Suggested fix:** guard `_send_frame` with a dedicated write lock.
- **Fix side effects:** none.
- **Discovered by:** A

---

#### F-WN-35-22  [P3] — The static analysers write into the repository, and `run_guard --capture` deletes the goldens directory

- **File:** `tools/bench/css_inventory.py:42,431,462`; `tools/bench/dom_nesting.py:22,230`; `tools/bench/js_census.py:21,396`; `tools/bench/build_hotspots.py:345`; `tools/bench/run_bench.py:41`; `tools/bench/run_pyprof.py:36,614`; `tools/visual_guard/run_guard.py:672-674`; `tools/visual_guard/capture.py:102,138`
- **Confirmed:** yes
- **Description:** six tools write into the repo tree. `css_inventory.py`, `dom_nesting.py`, `js_census.py` and `build_hotspots.py` write into `tools/bench/results/`; `run_pyprof.py` writes `profile_python_startup.json`, `profile_appcore_init.pstats` and `results/raw/*.json`; `run_guard.py` writes `tools/visual_guard/reports/` and `tools/visual_guard/current/`, and on `--capture` it does `shutil.rmtree(GOLDENS)`. Only `run_bench.py` honours `NEDOTIFY_BENCH_OUT`; the static analysers have no output override. `run_guard.py --capture --compare` deletes the goldens and then captures into `current/`, leaving `compare_sets` with an empty golden set — which, per F-WN-35-2, reports `ok=True`.
- **Cause:** no separation between "artefacts" (committed) and "scratch output" (temp); `NEDOTIFY_BENCH_OUT` is applied inconsistently.
- **Trigger conditions:** any run of those tools.
- **User impact:** running the analysers dirties the working tree and can silently overwrite a committed baseline (the `css_inventory.py` docstring already warns about exactly this hazard for `animation_declarations.json`); `--capture --compare` destroys the reference set and then reports success.
- **Evidence:**
  ```python
  # tools/visual_guard/run_guard.py:672-674
  if GOLDENS.exists() and args.capture:
      log(f"rebuilding goldens in {GOLDENS} (old set removed)")
      shutil.rmtree(GOLDENS, ignore_errors=True)
  # tools/visual_guard/run_guard.py:675-677
  capture_summary = capture(CURRENT if args.compare else GOLDENS, ...)
  # tools/bench/css_inventory.py:423-433  (the "do not merge these two files" warning)
  ```
- **Reproduction / verification:** ran `css_inventory.py`, `dom_nesting.py`, `js_census.py` and `run_guard.py --compare` in this session; each changed files under `tools/bench/results/` and `tools/visual_guard/reports/`. The tree was restored byte-for-byte afterwards (hashes verified against a pre-run backup).
- **Suggested fix:** default every analyser's output to a temp directory (or honour `NEDOTIFY_BENCH_OUT` everywhere) and require an explicit `--write` flag to touch a committed artefact; refuse `--capture --compare`.
- **Fix side effects:** the committed artefacts then have to be refreshed deliberately (which is the intent).
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct:

- **`tools/bench/cdp.py` — WebSocket mechanics.** RFC6455 client is correct: client-side masking with a random 4-byte key, the 126/127 extended-length encoding, the `0x80 | opcode` FIN byte, ping→pong, close handling, and a proper HTTP `101` handshake with `Sec-WebSocket-Accept` semantics. The frame builder's nested conditional (`cdp.py:110`) parses as intended.
- **`tools/bench/cdp.py` — "browser not running" behaviour.** `wait_for_page_target` swallows the connection error and retries until the deadline, then raises a `TimeoutError` that carries the attempt count and the last exception (`cdp.py:341-364`) — exactly the "the endpoint is not listening yet" case the docstring describes. No crash, no hang.
- **`tools/bench/cdp.py` — `wait_for_new_document`.** Genuinely fixes the "read the outgoing document" race the docstring warns about, by comparing `performance.timeOrigin` before/after the reload.
- **`tools/bench/procsampler.py` — process attribution.** It samples **only** its own PID and its descendants filtered by `msedgewebview2.exe` (`_tree_pids` → `psutil.Process(root).children(recursive=True)` + `_is_webview2`); it never touches unrelated processes on the machine. The CPU% is derived by differencing `cpu_times()` against the sampler's *own* previous reading, which is self-contained and reproducible (and the docstring explains why `cpu_percent(interval=None)` was rejected).
- **`tools/bench/profile.py` / `pyprof_child._redirect_profile` — profile isolation.** The redirect is real and verified at runtime: `os.path.expanduser("~")` is compared against the target and the run aborts if it does not match (`pyprof_child.py:56-58`); `HOMEDRIVE`/`HOMEPATH` are cleared; `LASTFM_API_KEY`/`LASTFM_USERNAME` are removed from the child environment; the cookie jar override (`auth.cookies_file_path`) is written into the scratch profile. The real `~/.nedotify/` is not touched by any of the harnesses I ran.
- **`tools/check_shadow_imports.py` — scope and detection.** The scan root is the repository root (unlike the lock checker), the `SKIP` set is sensible, and it *does* catch a genuine direct function-local shadowing import — verified with a fixture (`mod/unsafe.py: outer() uses 'time' at line 5 but imports it locally at line 6`). Only the nested-def traversal is wrong (F-WN-35-11).
- **`tools/bench/query_pstats.py` / `read_pyprof.py` — pstats parsing.** The `(cc, ncalls, tottime, cumtime, callers)` tuple order is read correctly, the path relativisation works, and the output is stable and quotable (real run below). `read_pyprof.py` reads the recorded JSON without re-timing anything, as documented.
- **`tools/visual_guard/diff.py` — anti-aliasing tolerance.** A uniform ±2/255 shift produces `diff_pixels = 0` (tolerance works as documented), identical images compare clean, and a 40×40 tint change of +10/255 is detected (1600 px, ratio 0.00156 → FAIL). The threshold semantics are as documented; only the *ratio* budget is too coarse (F-WN-35-12).
- **`tools/visual_guard/run_guard.py::_ensure_single_instance_free`.** Uses exactly the mutex name the app uses (`main.py:260` — `Local\NeDotify_App_Single_Instance_Mutex`), so the guard really does refuse to run beside a live instance instead of silently colliding.
- **`tools/bench/sleepscan.py`.** A clean read-only AST scan with correct `time.sleep` / `<expr>.wait` recognition, keyword-argument handling, and a useful classification. It writes nothing.
- **`tools/bench/thread_lineage.py`.** Patches `threading.Thread.__init__` in the child only, restores it, and never touches `webview.start()`. The `USERPROFILE` redirect is verified the same way `pyprof_child` does it.
- **`tools/bench/check_live_providers.py` — provider API compatibility.** The keyword arguments it uses match the real signatures (`youtube_service.search(query, max_results=…)`, `soundcloud_service.search(query, max_results=…)`, `spotify_service.search(query, limit=…)`), the Spotify branch correctly substitutes the YouTube service for stream resolution, and it uses `proxy.port` / `proxy.token`, which exist (`core/proxy.py:1268,1271`). It runs in a `tempfile.TemporaryDirectory` with `USERPROFILE`/`HOME` redirected before the service imports, and it stops the proxy and shuts down the executors in a `finally`.
- **Safety of the harnesses (general).** `run_bench.py`, `run_pyprof.py` and `run_guard.py` all run the app in a **scratch profile** and never write to `~/.nedotify/`; `run_guard.py` refuses to run while the app is up; `pyprof_child.py` never reaches `webview.start()`. The one script that does hit the network (`check_live_providers.py`) is explicit about it in its docstring, performs read-only provider searches, and does not modify the user's library, downloads or playlists.

---

### 4. Coverage gaps

- **Nothing that starts the app was executed.** Per the brief, I did not run `run_bench.py`, `run_pyprof.py`, `run_guard.py --capture/--all`, `pyprof_child.py`, `thread_lineage.py` or `check_live_providers.py` (they start the real app and/or hit the network). All conclusions about those paths come from reading the code plus the committed result JSON in `tools/bench/results/`.
- **`check_live_providers.py` was not executed**, so its live behaviour (real YouTube/SoundCloud/Spotify traffic, whether the browser-cookie auto-detection actually reads the user's real browser profile under the `USERPROFILE` redirect, and whether the proxy media fetch succeeds) is unverified. The yt-dlp cookie extractor is a plausible privacy concern worth a dedicated review; I could not confirm it without running the script.
- **The visual guard's pixel half could not be exercised end to end** — there is no golden set (F-WN-35-2) and the app cannot be launched here. The diff logic was validated against synthetic images only.
- **`tools/bench/track_row_nodes.js` could not be regenerated** — `node.exe` is not on PATH on this machine, so the `track_row_nodes.json` numbers (and the `createTrackElement` node/listener counts quoted in `docs/perf/prof_frontend.md`) could only be checked for staleness, not reproduced. The verifier already reports the drift: `template_source.lines says '338-368', but createTrackElement is at line 688`.
- **`py-spy` cross-checking was not exercised** — `py-spy.exe` exists in `.venv_win\Scripts`, but capturing it requires a live `idle_hold` child (i.e. running the app), which was out of scope.
- **The CDP fragmentation hypothesis (F-WN-35-21) was not reproduced** — no live DevTools endpoint was available; only the missing write lock is evidenced.
- **`tools/bench/build_hotspots.py` was not executed** (it calls `js_census.main()` in-process and rewrites `frontend_hotspots.json`); its inputs were compared against the committed artefact by hash instead.
- **No cross-machine determinism test for the visual guard was possible** (F-WN-35-18) — a second Windows machine / build was not available.
