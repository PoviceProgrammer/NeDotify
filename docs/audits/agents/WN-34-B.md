## AREA WN-34 — Test suite — ROLE B

### 1. Scope reviewed

**Mandatory context read**

- `docs/audits/WIN_AUDIT_CONTEXT.md` (1–200)
- `docs/audits/WIN_AUDIT_AREAS.md` (1–70, row WN-34 = `tests/**`)
- `tests/conftest.py` (1–176), `pytest.ini` (1–5), `run_tests.py` (1–12)
- `.claude/skills/nedotify-test/SKILL.md` (1–82)
- `.github/workflows/ci.yml` (1–32), `.github/workflows/android-source.yml` (head)

**Suite reviewed** — `tests/**`: 101 `test_*.py` files + `tests/conftest.py`, `tests/__init__.py`,
`tests/benchmark_lyrics_cache.py`. 1506 collected test items / ~1052 test functions.

**Tooling reviewed** — `tools/check_lock_nesting.py` (1–127), `tools/check_shadow_imports.py` (1–119),
`tools/bench/**` (34 files), `tools/visual_guard/**` (5 files), `requirements-dev.txt`, `.gitignore`,
`setup_pyinstaller.spec`.

**Production tree read for the coverage map** — `main.py`, `core/api.py` (342–392, 2680–2734),
`core/app.py` (91–210), `core/downloader.py` (775–814), `core/tray.py` (1–70),
`core/listening.py`, `core/database.py` (grep), `core/settings.py`, `services/base_service.py` (1–329),
`services/youtube_service.py`, `services/soundcloud_service.py`, `services/spotify_service.py`,
`services/lastfm_service.py`, `services/lyrics_service.py`, `services/lyrics_lookup.py`,
`services/yandex_service.py`, `services/recommendation_service.py`, `services/taste_profile.py`,
`core/services/recommendation.py`, `core/services/discord_rpc.py`, `utils/*`.

**Frontend read** — `ui/web_new_v2/js/**` (35 files, 1 313 027 B; 33 first-party, 907 871 B),
`ui/web_new_v2/js/player.js` (2244, 2358, 2513).

**Callees traced into other areas**

- `core/api.py:542–597` — `_install_snap_layouts()`: `self._tray.start()` at 575 is **unreachable**
  (unconditional `return False` at 572). Already logged as `F-AR-04-1` in
  `docs/audits/FULL_PROJECT_AUDIT.md:64`; **owner is WN-04 / WN-16**, not reported as a new finding here.
  From the WN-34 side the only issue is the *coverage gap* (see §4).
- `core/api.py:446–457` — `AppApi.cleanup()`; owner WN-03/WN-04.
- `core/database.py:1882–1892` — `_cleanup_duplicate_empty_system_playlists()`; owner WN-12.

---

### 1b. Module → test coverage map (measured)

Production modules: **59** in total — **54 real modules** (one of which is `main.py`) plus **5 `__init__.py`** files.
Reachability was measured by the **transitive module-level import closure** of every test file.

| bucket | count | modules |
|---|---|---|
| imported **directly** by ≥1 test | **40** | `core.api`(9 files), `core.app`(6), `core.database`(5), `core.downloader`(4), `core.resolver`(7), `core.settings`(5), `core.proxy`(7), `core.snap_layouts`(2), `core.tray`(2), `core.offline`, `core.playback_recovery`, `core.download_transfer`, `core.ui_assets`, `core.user_errors`, `audio.engine`(7), `audio.queue`(4), `services.base_service`(9), `services.youtube_service`(8), `services.soundcloud_service`(4), `services.taste_profile`(6), `services.track_resolver`(2), `services.recommendation_service`, `services.smart_playlists`, `services.catalog_service`, `services.artist_identity`, `services.itunes_gateway`, `services.listening_comparison`, `services.lufs_scanner`, `services.lyrics_cache`, `services.lyrics_service`(4), `services.music_matching`, `services.spotify_service`, `services.zapret_service`, `utils.cache_manager`(2), `utils.file_scanner`, `utils.search_query`, `utils.stream_urls`, `utils.url_safety` |
| reached **only transitively** (no test imports it) | **11** | `core.download_store`, `core.plugins`, `core.session`, `core.services.discord_rpc`, `services.artist_service`, `services.audio_fingerprint_service`, `services.lastfm_service`, `services.playlist_import_service`, `services.vk_service`, `services.watchdog_service`, `utils.tag_parser` |
| **never loaded** by any test | **8** | `main.py`, `services.yandex_service`, `core.services.recommendation`, `services.lyrics_lookup`*, `core.listening`*, + 3 `__init__.py` — (*) both are imported only through an indirect form (`from core import listening`; `monkeypatch.setattr('services.lyrics_lookup.os.stat', …)`), so in practice the **effective untested set is `main.py`, `services.yandex_service.py`, `core/services/recommendation.py`** |
| *effective* untested (real modules) | **3** | `main.py` · `services.yandex_service.py` · `core/services/recommendation.py` |

**Modules with NO obviously-named test file: 34 of 54** — i.e. a reader cannot answer
"is `core/session.py` tested?" from the file listing. The 20 that *do* have one:
`core/api.py`, `core/app.py`(only via `test_appearance_backgrounds.py` — accidental),
`core/database.py`, `core/downloader.py`, `core/listening.py`, `core/offline.py`,
`core/playback_recovery.py`, `core/proxy.py`, `core/resolver.py`, `core/settings.py`,
`core/snap_layouts.py`, `audio/engine.py`, `audio/queue.py`,
`services/listening_comparison.py`, `services/recommendation_service.py`,
`services/smart_playlists.py`, `services/taste_profile.py`, `services/track_resolver.py`,
`utils/search_query.py`, `utils/url_safety.py`.

### 2. Findings

#### F-WN-34-1  [P1] — `AppCore.__init__` is never executed by any test: the whole wiring is untested

- **File:** `core/app.py:94–185`; `tests/test_lazy_service_deadlock.py:17,23,63`; `tests/test_offline_mode.py:67`; `tests/test_provider_loading.py:114`; `tests/test_db_core_fixes_f2.py:527,536,545,556,581,619`
- **Confirmed:** yes
- **Description:** `AppCore.__init__` is the single place where every subsystem is constructed. **No test ever calls it.** Every test that needs `AppCore` uses `AppCore.__new__(AppCore)` (bypassing `__init__`) or calls unbound methods with a hand-made fake `core`. Consequently the constructor's side effects — `DatabaseManager()` (line 107, real `~/.nedotify/nedotify_storage.db`), `SettingsManager`/`SessionManager`/`CacheManager`/`FileScanner` (108–111), `StreamResolver` (122), `AudioEngine` (125), all six provider clients (129–134), `LocalProxyManager` + `self.proxy.start()` (137–158, opens a loopback socket), `DownloadManager` (139), `PluginManager` + `plugins.load_plugins()` (140, 159), `ZapretService` (141), `PlaylistImportService` (142), `WatchdogService` + `.start()` (143, 163), `LufsScannerService` + `.start()` (144, 170), `AudioFingerprintService` (145), `DiscordRPCService` + `.start()` (146–147), the background `update_ytdlp_safely` thread (150–151), `zapret.auto_update_in_background()` (154–155) and the `_cache_cleanup_loop` thread (176–185) — are **never executed by the suite**.
- **Cause:** `AppCore.__init__` has **no injection seam**: every collaborator is constructed inline with a hard-coded argument (`DatabaseManager()`, `DiscordRPCService(self.settings)`, `LocalProxyManager(self)`), so there is no way to substitute a fake DB, a fake provider, or "no network" without editing production code. The tests therefore fake the *object graph* (`types.SimpleNamespace`) instead of the *wiring*.
- **Trigger conditions:** Any change to `AppCore.__init__` (new subsystem, reordered construction, changed proxy/discord/watchdog wiring) is invisible to the suite. A constructor that raises, hangs on `proxy.start()`, or spawns a thread that keeps the process alive passes 1506 tests.
- **User impact:** The wiring is where cross-subsystem defects live (the `AppCore._service_lock` self-deadlock the tool docstring cites, the `cleanup()` ordering, the proxy/discord/watchdog start order). Those are exactly the defects this audit is looking for, and the suite cannot see them.
- **Evidence:**
  ```python
  # tests/test_lazy_service_deadlock.py:17
  core = AppCore.__new__(AppCore)
  # tests/test_provider_loading.py:114
  core = AppCore.__new__(AppCore)
  # tests/test_db_core_fixes_f2.py:619
  AppCore.cleanup(core)          # unbound call with a fake core
  ```
  ```python
  # core/app.py:94-107,137-147,158
  def __init__(self):
      ...
      self.db = DatabaseManager()
      ...
      self.proxy = LocalProxyManager(self)
      ...
      self.discord_rpc = DiscordRPCService(self.settings)
      self.discord_rpc.start()
      ...
      self.proxy.start()
  ```
- **Reproduction / verification:** `Select-String -Path "tests\*.py" -Pattern "AppCore\("` → **0 matches**; every occurrence is `AppCore.__new__(AppCore)` or `AppCore.<method>(core)`.
- **Suggested fix:** Give `AppCore.__init__` an optional dependency-injection mapping (`AppCore(providers=..., db_path=..., net=...)` or a `factories` dict) with production defaults; add one `test_app_core_wiring.py` that constructs a real `AppCore` with fakes and asserts the graph (proxy started, discord not started, watchdog started, cleanup order).
- **Fix side effects:** `AppCore.__init__` becomes a wider API; `main.py` must be updated; a careless default keeps the current side effects (so the default must stay identical).
- **Discovered by:** B

---

#### F-WN-34-2  [P1] — CI runs only the 48 of 101 test files that git tracks; 53 (52 %) are untracked

- **File:** `.github/workflows/ci.yml:14` (`actions/checkout@v3`), `tests/**` (53 untracked `test_*.py`), `ui/web_new_v2/js/**` (12 untracked modules)
- **Confirmed:** yes
- **Description:** The CI job does a plain `actions/checkout@v3` of the pushed branch, then `pytest -m "not network"`. Git tracks only **48** of the **101** `test_*.py` files present in the working tree. The other **53** test files (52 %) exist only on disk and are **never executed by CI**. The same applies to the product: 12 of the 35 `ui/web_new_v2/js/` modules and 16 production modules (`core/download_store.py`, `core/download_transfer.py`, `core/listening.py`, `core/offline.py`, `core/playback_recovery.py`, `core/ui_assets.py`, `core/user_errors.py`, `services/artist_identity.py`, `services/catalog_service.py`, `services/itunes_gateway.py`, `services/listening_comparison.py`, `services/lyrics_cache.py`, `services/lyrics_lookup.py`, `services/music_matching.py`, `services/smart_playlists.py`, `utils/search_query.py`, `utils/stream_urls.py`) are untracked — i.e. the *production code the new tests cover* is itself outside version control.
- **Cause:** The work is done on a long-lived branch (`fix/audit-v2`, HEAD `76cab49`) with a huge uncommitted delta; there is no "all tests are tracked" gate. `tests/test_repo_hygiene.py:96` checks only that `tests/` is *not* gitignored — it never checks that the suite is *committed*.
- **Trigger conditions:** Every CI run on any branch. A regression introduced in an untracked module or untracked test is invisible to the gate.
- **User impact:** The "CI is green" signal covers roughly half of the suite and two thirds of the UI. Most of the regression value the project claims from the suite is not actually gated.
- **Evidence:**
  ```
  $ git ls-files tests | wc -l        -> 50 entries (48 test files + __init__.py + conftest.py)
  $ ls tests/test_*.py | wc -l        -> 101 files
  $ git status --porcelain | wc -l    -> 229   (70 M, 36 D, 123 ??)
  $ git ls-files ui/web_new_v2/js     -> 23 of 35 tracked
  UNTRACKED js: appearance-assets.js downloads-view.js feature-controls.js home-shell.js
                 library-view.js profile-comparison.js profile.js search-discovery.js
                 settings-view.js smart-playlists.js ui-style.js window-resize.js
  ```
- **Reproduction / verification:** `git ls-files tests` vs `Get-ChildItem tests -Filter 'test_*.py'`; `git status --porcelain`.
- **Suggested fix:** Add a repo gate (`test_repo_hygiene.py`) asserting that every `tests/test_*.py` on disk is tracked (`git ls-files --error-unmatch`) and that `git status --porcelain` is empty on `main`; commit or delete the 53 files before merging.
- **Fix side effects:** Large one-time commit; any file that was intentionally scratch would need deleting instead.
- **Discovered by:** B

---

#### F-WN-34-3  [P1] — `tests/test_android_source_gates.py` hard-fails when `android/` is absent; `android/` is untracked, so CI is red

- **File:** `tests/test_android_source_gates.py:12–13, 41–44, 61–67, 72–75`; `.github/workflows/ci.yml:14`; `.github/workflows/android-source.yml` (untracked)
- **Confirmed:** yes
- **Description:** This file belongs to the **Android** product, not the Windows desktop suite, and it is **not** skipped when the Android tree is missing. The module-level guard is `pytestmark = pytest.mark.skipif(not POWERSHELL, ...)` — it skips only when PowerShell is missing. The Android tree is located as `Path(__file__).resolve().parents[1] / "android"` (line 13) and is used unconditionally: the test dot-sources `android/tools/SourceSnapshot.ps1` and `android/tools/SourceTasks.ps1` via PowerShell. `git ls-files android` → **0 files** (the whole Android tree is untracked), so `actions/checkout@v3` in `ci.yml` produces a checkout **without** `android/` → the PowerShell dot-source fails → the assertions fail.
- **Cause:** The Windows suite contains a gate for a sibling product whose inputs are not version-controlled in this repository, and the failure mode is "assert" instead of "skip".
- **Trigger conditions:** Any CI run of the Windows workflow (the workflow does not check out `android/`, and `.github/workflows/android-source.yml` is itself untracked so it does not exist in CI either).
- **User impact:** The Windows CI job fails for a reason unrelated to the Windows product; the 1506-test signal is lost. On the author's machine the file passes, so the breakage is invisible locally.
- **Evidence:**
  ```python
  # tests/test_android_source_gates.py:12-13
  pytestmark = pytest.mark.skipif(not POWERSHELL, reason="PowerShell unavailable")
  ANDROID = Path(__file__).resolve().parents[1] / "android"
  # :41-44
  common = quoted(ANDROID / "tools" / "SourceSnapshot.ps1")
  create = run_script(f"... . {common}; Write-ReviewSnapshot {root}; Test-ReviewSnapshot {root}")
  assert create.returncode == 0, create.stdout + create.stderr
  ```
  Reproduction (same file, copied to a tree with no `android/`):
  ```
  FAILED test_android_source_gates.py::test_snapshot_rejects_membership_and_content_drift[new-New (]
  FAILED test_android_source_gates.py::test_snapshot_rejects_membership_and_content_drift[change-Changed (]
  FAILED test_android_source_gates.py::test_snapshot_rejects_membership_and_content_drift[remove-Removed (]
  FAILED test_android_source_gates.py::test_snapshot_rejects_membership_and_content_drift[unlisted-...]
  FAILED test_android_source_gates.py::test_source_gate_rejects_packaging_device_abbreviations_and_options[...]
  8 failed in 2.41s
  ```
  and `git ls-files android` → `0`.
- **Suggested fix:** Move the file to the Android tree (or a separate `tests-android/` root excluded from `pytest.ini`'s `testpaths`), and make the `android/`-absent case a `pytest.skip` instead of a failure.
- **Fix side effects:** The Android gate stops running in the Windows job; if it was meant to protect the Windows tree it needs a different, in-tree input.
- **Discovered by:** B

---

#### F-WN-34-4  [P1] — The suite is red on the current tree: 11 failures from one DOM-contract drift

- **File:** `ui/web_new_v2/js/player.js:2244,2358`; `tests/test_flow_ui.py:47–49,67`; `tests/test_player_resources.py` (HARNESS); `tests/test_player_recovery_transitions.py:1,52`
- **Confirmed:** yes
- **Description:** A full run of the suite fails 11 tests: 8 in `tests/test_flow_ui.py` and 3 in `tests/test_player_recovery_transitions.py`. The cause is a **new DOM read in the product** — `document.documentElement.dataset.progressStyle` (added to `player.js` in the uncommitted diff, lines 2244 and 2358) — against a **hand-written fake DOM in the test** whose `documentElement` has no `dataset`:
  ```javascript
  // tests/test_flow_ui.py:49
  documentElement: {classList, getAttribute: () => null, style: {setProperty() {}}}, body: {classList}},
  ```
  `dataset` is `undefined` → `document.documentElement.dataset.progressStyle` throws `TypeError: Cannot read properties of undefined (reading 'progressStyle')`. Note `player.js:2513` uses the optional form `dataset?.uiStyle`, so only the two non-optional reads break.
- **Cause:** There is **no shared DOM stub**. Five test files each embed their own private fake `document` (`test_flow_ui.py`, `test_player_resources.py` → `HARNESS`, `test_visual_effects_lifecycle.py`, `test_recommendation_ui.py` → `run_node`, `test_player_recovery_transitions.py` → imports `HARNESS` from `test_player_resources`). Every new DOM feature the product reads has to be added to N copies, and nothing detects the drift until the suite is run — which is exactly what happened.
- **Trigger conditions:** Any product change that reads a new DOM property. Here: the uncommitted `player.js` change.
- **User impact:** The gate is red, so it carries no signal; a developer cannot tell "my change broke something" from "the harness was already stale". (The product itself is fine — a real browser always has `document.documentElement.dataset`.)
- **Evidence:** observed run:
  ```
  FAILED tests/test_flow_ui.py::test_immediate_flow_coalesces_and_filters_duplicates_in_the_same_response
  FAILED tests/test_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[track]
  ... (8 failures in test_flow_ui.py)
  FAILED tests/test_player_recovery_transitions.py::test_crossfade_waits_for_ready_media_then_advances_once_and_releases_outgoing
  FAILED tests/test_player_recovery_transitions.py::test_gapless_starts_preloaded_audio_before_bridge_and_adopts_fresh_session
  FAILED tests/test_player_recovery_transitions.py::test_seek_finishes_crossfade_and_cancels_outgoing_audio
  ========================= 11 failed, 1491 passed, 1 skipped, 3 xfailed in 62.39s (0:01:02) =========================
  ```
  Error: `TypeError: Cannot read properties of undefined (reading 'progressStyle') at fetchAndRenderWaveform (evalmachine.<anonymous>:2244:52)`.
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_flow_ui.py` → 8 failed in 0.46 s.
- **Suggested fix:** Extract one shared DOM stub into `tests/jsdom.py` (or `conftest.py`) and have all five harnesses import it; add a contract test that asserts the stub exposes every `document.*` member the production JS reads.
- **Fix side effects:** The shared stub must satisfy five different harnesses, some of which need extra behaviour; expect a short consolidation effort.
- **Discovered by:** B

---

#### F-WN-34-5  [P1] — `tools/check_lock_nesting.py` scans only `tools/`, and neither it nor `check_shadow_imports.py` is wired into any gate

- **File:** `tools/check_lock_nesting.py:11`; `tools/check_shadow_imports.py:12–16`; `.github/workflows/ci.yml:28–30`
- **Confirmed:** yes
- **Description:** `check_lock_nesting.py` sets `ROOT = os.path.dirname(os.path.abspath(__file__))` — i.e. **`tools/`** — and walks that directory. It therefore never looks at `core/`, `services/`, `audio/` or `utils/`, i.e. at the code the tool was written for (its own docstring cites three shipped deadlocks in `AppCore._service_lock`, `DiscordRPCService._lock` and a `Lock` around `evaluate_js`). Run as shipped it prints `OK: no nested-lock self-deadlock patterns` and exits 0 — a green gate that checks nothing. `check_shadow_imports.py` does set `ROOT` to the repository root (line 12) but is also wired into **no** workflow, **no** pre-commit hook, and **no** test (the only references in the tree are `tools/bench/results/*.json`, which record the tools' SHA-1 hashes as part of a benchmark snapshot).
- **Cause:** The two scripts were written as ad-hoc developer tools, never promoted to CI, and one of them has the wrong root.
- **Trigger conditions:** Always — the gate simply does not exist.
- **User impact:** A whole class of self-deadlock / `UnboundLocalError` defects that the project has already been bitten by twice (`core/proxy.py:do_GET` per the tool's own docstring) can be reintroduced silently. The tool that exists specifically to prevent this is inert.
- **Evidence:**
  ```python
  # tools/check_lock_nesting.py:11
  ROOT = os.path.dirname(os.path.abspath(__file__))      # == tools/
  # tools/check_shadow_imports.py:12
  ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # == repo root
  ```
  Observed:
  ```
  $ python tools/check_lock_nesting.py
  OK: no nested-lock self-deadlock patterns
  EXIT=0
  $ python tools/check_shadow_imports.py
  SHADOWING function-local imports (UnboundLocalError risk):
    core\api.py: _install_snap_layouts() uses 'time' at line 570 but imports it locally at line 581
  EXIT=1
  ```
  Pointed at the repository root (copy with only `ROOT` changed, in `%TEMP%`):
  ```
  POTENTIAL self-deadlocks (non-reentrant Lock held across a same-lock call):
    core\database.py: DatabaseManager.create_playlist_ex() holds self.conn and calls _cleanup_duplicate_empty_system_playlists()
  ```
  Note both hits are **false positives** of the tools: `core/api.py:581` is `import time` inside the *nested* `_set_icon` function (the tool's `_own_body` helper is defeated by `ast.walk` descending into nested defs), and `self.conn` at `core/database.py:1250` is a **SQLite connection** used as a transaction context manager, not a `threading.Lock`.
- **Reproduction / verification:** `& ".venv_win\Scripts\python.exe" tools/check_lock_nesting.py` (prints OK while scanning `tools/` only); `Select-String -Recurse -Pattern "check_lock_nesting|check_shadow_imports"` finds no `.yml`/`.py` caller.
- **Suggested fix:** Fix `ROOT` in `check_lock_nesting.py` to the repo root; make both tools only report attributes that are *actually* `threading.Lock` instances (check `lock_kinds` for `self.<name>`); add both to `.github/workflows/ci.yml` as a separate step so a false positive blocks the build loudly and gets fixed immediately.
- **Fix side effects:** Until the false positives are fixed, wiring the tools in turns CI red on `core/database.py` and `core/api.py` — that is the correct outcome (they must be fixed), but it must be sequenced.
- **Discovered by:** B

---

#### F-WN-34-6  [P1] — Test isolation is opt-in and is not applied by the `api` / `core_ns` / `downloader` fixtures: a test reads the real `~/.nedotify/downloads`

- **File:** `tests/conftest.py:170–176` (`redirect_home`, opt-in, not `autouse`), `tests/conftest.py:97–129` (`api`, `core_ns`, `downloader` fixtures), `core/api.py:2700`, `core/downloader.py:789–790`, `tests/test_auto_save_favorites.py:87–96`
- **Confirmed:** yes
- **Description:** `redirect_home` is the only sandbox and it is **opt-in**: `tests/conftest.py:170–176` declares it without `autouse=True`, and none of the three shared fixtures (`core_ns`, `api`, `downloader`) requests it. Consequently the production code paths that compute paths from `os.path.expanduser("~")` are reached with the **user's real profile** unless a test remembers to ask for the sandbox. A concrete, live instance:
  ```python
  # core/api.py:2698-2700  (AppApi._auto_save_favorite)
  dl_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "downloads")
  if os.path.isdir(dl_dir):
      for name in os.listdir(dl_dir): ...
  ```
  `tests/test_auto_save_favorites.py::test_streaming_track_is_cached_then_queued` (line 87) calls `_auto_save_favorite` **without** `redirect_home`, so the quota it computes comes from the **real** `~/.nedotify/downloads`.
  The same is true for `core/downloader.py:789` (`download_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'downloads')`), which is the path the downloader writes to.
  The user's real profile **already contains artefacts written by this suite**:
  ```
  C:\Users\<user>\.nedotify\downloads\gated_3.mp3 .. gated_12.mp3   16 B each
  C:\Users\<user>\.nedotify\downloads\stub_1.mp3                  8207 B
  ```
  `stub_1.mp3` is byte-exact the payload of `tests/conftest.py:58–61` (`b"ID3\x00\x01stub-audio" + b"\x00" * 8192` = 8207 B, header `49 44 33 00 01 73 74 75 62 2D 61 75 64 69 6F 00`); the `gated_*.mp3` files are the payload of `tests/test_downloader_cancel.py:45–49`. (The 16-byte `gated_*` files are from a pre-fix revision of that test; `stub_1.mp3` is dated 2026-10-20 22:24.)
- **Cause:** The sandbox is a fixture a developer must remember to request; it is not the default. `AGENTS.md` states "`~/.nedotify/` is the user's library — clearing it is not a cleanup step", but the suite is able to write into it.
- **Trigger conditions:** (a) Any new test that forgets `redirect_home` and reaches `core/downloader.py:789` or `core/api.py:2700`; (b) the test above, on any machine whose real `~/.nedotify/downloads` exceeds the configured quota (default 20 GB) — the test then fails for a reason unrelated to the code.
- **User impact:** The user's music library is polluted with test files, and the test suite's result depends on the user's disk content.
- **Evidence:** decisive reproduction — with `USERPROFILE`/`HOME` redirected to a temp home whose `.nedotify/downloads` contains one file, and `os.path.getsize` shimmed to report 1 TiB for that directory, the un-sandboxed test fails:
  ```
  >       assert res["queued"] is True
  E       assert False is True
  tests\test_auto_save_favorites.py:94: AssertionError
  ```
  i.e. the test read `$HOME/.nedotify/downloads`. Direct listing of the real profile (read-only):
  ```
  downloads\gated_10.mp3  16  2026-10-03 10:48:24
  ... (gated_3..gated_12)
  downloads\stub_1.mp3  8207  2026-10-20 22:24:33
  ```
- **Reproduction / verification:** `Get-ChildItem "$HOME\.nedotify\downloads"`; run the shimmed experiment above; `Select-String -Path "tests\*.py" -Pattern "redirect_home"` → 42 hits in 12 files (one of which is `conftest.py` itself); **none** of the three shared fixtures in `tests/conftest.py:85–129` requests it.
- **Suggested fix:** Make the sandbox the default: an `autouse=True` session fixture in `tests/conftest.py` that redirects `~` to a per-test temp dir (and restores it), so `redirect_home` becomes a no-op compatibility alias. Add a repo gate that fails when any test file writes outside `tmp_path`/the sandbox.
- **Fix side effects:** Tests that deliberately exercise the real path (`test_conftest_home_isolation.py` asserts `REAL_HOME` behaviour) need an explicit opt-out; a session-wide `expanduser` patch changes `os.path.expanduser` for code under test, so the `redirect_home` fixture must be re-expressed on top of it rather than removed.
- **Discovered by:** B

---

#### F-WN-34-7  [P2] — The `network` marker is declared but never used: `-m "not network"` deselects nothing

- **File:** `pytest.ini:3–5`; `.claude/skills/nedotify-test/SKILL.md:21–23`; `run_tests.py:12`
- **Confirmed:** yes
- **Description:** `pytest.ini` declares a `network` marker and deselects it by default:
  ```ini
  [pytest]
  testpaths = tests
  markers =
      network: test performs real network I/O (deselected by default)
  addopts = -m "not network"
  ```
  **No test anywhere uses it.** `Select-String -Path "tests\*.py" -Pattern "mark\.network"` → 0 matches. The documented escape hatch `pytest -m network` therefore selects **zero** tests, and the default `-m "not network"` deselects **zero** tests. The skill file claims "Tests marked `network` are deselected by default and hit live providers (YouTube, SoundCloud, Spotify, Yandex)" — there are none.
- **Cause:** The marker was declared as policy and never applied to the provider tests that would need it (`test_provider_loading.py`, `test_provider_performance.py` reach real provider code paths).
- **Trigger conditions:** Always; the marker is decorative.
- **User impact:** The suite's hermeticity is accidental rather than enforced: the guarantee "no test touches the network" is not backed by a marker, so a future test that does hit the network will not be excluded, and the documented way to run live-provider tests does nothing.
- **Evidence:**
  ```
  $ python -m pytest -m network --collect-only -q
  no tests collected (1506 deselected) in 1.14s
  $ python -m pytest --collect-only -q
  1506 tests collected in 1.65s
  ```
- **Suggested fix:** Either mark the live-provider tests `network` (and make them opt-in), or delete the marker, the `addopts` line and the skill-file paragraph so the policy matches reality.
- **Fix side effects:** Marking tests `network` moves them out of the default run — the default suite gets smaller; if some "network" tests are actually hermetic stubs they should be unmarked.
- **Discovered by:** B

---

#### F-WN-34-8  [P2] — No lint, type-check or coverage gate; `pytest.ini` has no strict mode; no dependency lockfile

- **File:** `.github/workflows/ci.yml:22–30`; `pytest.ini:1–5`; `requirements.txt`; `requirements-dev.txt`
- **Confirmed:** yes
- **Description:** The entire CI job is:
  ```yaml
  - name: Install dependencies
    run: |
      pip install -r requirements.txt
      pip install -r requirements-dev.txt
  - name: Run Python tests
    run: |
      pytest -m "not network"
  ```
  There is **no** linter, **no** type checker, **no** coverage measurement or threshold, and **no** `--strict-markers` / `--strict-config` / `filterwarnings = error` in `pytest.ini`. An unknown marker or a bad `pytest.ini` key is silently accepted. `requirements-dev.txt` contains only `pytest==9.1.1` and `pytest-asyncio==1.4.0` (the latter is used by **no** test — see F-WN-34-13). `requirements.txt` uses open ranges (`pywebview>=5.0.0,<6`, `requests>=2.31.0,<3`, …), and there is **no lockfile** anywhere (`requirements*.lock`, `poetry.lock`, `uv.lock`, `constraints.txt` → none).
- **Cause:** The gate was written once, as "does the suite pass", and never extended; the dependency policy is "caps, not pins".
- **Trigger conditions:** Every CI run.
- **User impact:** Non-reproducible CI (a transitive dependency bump can change the result of the same commit); no static defence against the classes of defect the audit is finding (dead code, shadowed imports, unreachable blocks); coverage is invisible, so nobody can tell which parts of the 206 KB `core/api.py` are exercised.
- **Evidence:**
  ```
  $ Get-ChildItem -Recurse -Include "*.lock","poetry.lock","uv.lock","constraints*.txt"   -> (only .git/cursor/.../build.lock)
  $ Get-Content pytest.ini
  [pytest]
  testpaths = tests
  markers =
      network: test performs real network I/O (deselected by default)
  addopts = -m "not network"
  ```
- **Suggested fix:** Add `ruff check` (and `ruff format --check`) + a type check step to `ci.yml`; add `pytest --strict-markers --strict-config -W error`; add `pytest-cov` with a per-module coverage floor (start at the measured baseline, ratchet up); generate and commit a lockfile (`pip-compile`/`uv lock`).
- **Fix side effects:** Introducing a linter on an existing tree produces a large first-run diff; the type checker will produce noise on the untyped bridge; the coverage floor must be set from a measurement, not guessed.
- **Discovered by:** B

---

#### F-WN-34-9  [P2] — Wall-clock thresholds, a 0.5 s TTL race, and a local-timezone dependency

- **File:** `tests/test_lyrics_performance.py:162,180,324`; `tests/test_emit_thread_safety.py:47–69`; `tests/test_engine_resolve.py:653–657`; `tests/test_settings_flush.py:74–79`; `tests/test_downloader_cancel.py:282–284`; `tests/test_api_search.py:16–20`; `tests/test_offline_mode.py:57–58`; `tests/test_taste_profile.py:104`
- **Confirmed:** yes
- **Description:** The suite contains hard wall-clock assertions and one genuine race:
  - `tests/test_lyrics_performance.py:162` `assert elapsed < .5`, `:180` `assert actual['instrumental'] and elapsed < .5`
  - `tests/test_emit_thread_safety.py:69` `assert holder["elapsed"] < 1.0`
  - `tests/test_engine_resolve.py:657` `assert elapsed < 1.0`
  - `tests/test_settings_flush.py:79` `assert elapsed < 5.0`
  - `tests/test_downloader_cancel.py:284` `assert time.monotonic() - start < 1.0`
  - `tests/test_api_search.py:20` `assert dt < 5.0` (the disabled-provider path must beat the 6.0 s `PROVIDER_SEARCH_TIMEOUT`)
  - `tests/test_lyrics_performance.py:324` `conn.execute('UPDATE lyrics_cache SET expires = ?', (time.time() + .5,))` — a **0.5-second** wall-clock TTL used to force a cache expiry; on a loaded runner the "expired" window can close before the assertion runs.
  - `tests/test_taste_profile.py:104` `(datetime.now() - timedelta(days=90)).isoformat()` — uses **local time** while the sibling line 115 writes `datetime.now(timezone.utc)`, i.e. the same row is written in local time and read in UTC on a machine with a non-UTC timezone.
- **Cause:** Performance is asserted with the wall clock instead of with an injected clock; the cache TTL is expressed in seconds rather than as an injectable clock source.
- **Trigger conditions:** A loaded CI runner, a debug build, a machine with a non-UTC timezone, or a machine whose clock is adjusted.
- **User impact:** Flaky red/green that is indistinguishable from a real regression — the worst failure mode for a gate, because it teaches the team to re-run instead of to fix.
- **Evidence:** quoted assertions above; all thresholds are hard-coded literals, not derived from the production constant they test (e.g. `test_api_search.py:20` hard-codes `5.0` while `core/api.py:61` defines `PROVIDER_SEARCH_TIMEOUT = 6.0`).
- **Reproduction / verification:** `Select-String -Path "tests\*.py" -Pattern "time\.monotonic|perf_counter|elapsed <"` → the list above; `tests/test_taste_profile.py:104` vs `:115` shows the local/UTC mix.
- **Suggested fix:** Inject a clock (monkeypatch `time.monotonic`/`time.time`) in the cache and retry tests; for the latency assertions, either raise the budget to a value derived from the production constant, or move the measurement into `tools/bench/` (which already exists for that purpose) and assert only the *ordering* in pytest.
- **Fix side effects:** Making the clock injectable touches `services/base_service.py` (`time.time()` at 201, 221, 256, 270) and `core/resolver.py`; a shared clock module is a small but real production change.
- **Discovered by:** B

---

#### F-WN-34-10  [P2] — Shared test harnesses live in test modules, not in `conftest.py`: 25 cross-test-module imports

- **File:** `tests/test_recommendation_ui.py:18–23` (`run_node`, `source`), `tests/test_proxy_harness.py`, `tests/test_player_resources.py` (`HARNESS`), `tests/test_provider_loading.py` (`DeferredExecutor`) — imported from 25 sites in 13 other files
- **Confirmed:** yes
- **Description:** The suite's reusable machinery lives in *test modules* that pytest also collects as test files:
  ```
  8 files  import {run_node, source}   from tests.test_recommendation_ui
  4 files  import fixtures              from tests.test_proxy_harness
  3 files  import {DeferredExecutor}    from tests.test_provider_loading
  1 file   import {HARNESS}             from tests.test_player_resources
  1 file   import {recommendations,track,fetch} from tests.test_recommendation_service
  ```
  `tests/test_proxy_harness.py` is simultaneously a fixture provider (`app_core`, `nedotify_home`, `proxy`, `proxy_factory`, `offline_handler`) **and** a collected test file (2 test functions). `tests/test_proxy_fixes_f5.py:8` imports it with `# noqa: F401` purely to get the fixtures.
- **Cause:** `tests/conftest.py` only holds the Python-side fixtures; the JS harness and the proxy harness were never promoted to shared fixtures, so each new consumer imports a sibling test module.
- **Trigger conditions:** Always. Because pytest imports test modules in collection order, the *import* of one test module by another fixes the module's evaluation order — and with it the order in which module-level state (e.g. `BaseMusicService._stream_cache`, the `_ssrf_cache`) is populated.
- **User impact:** Test order is coupled to the import graph rather than to an explicit dependency; a refactor of one "helper" test file silently breaks unrelated suites; a helper file that fails to import breaks every consumer.
- **Evidence:**
  ```
  $ Select-String -Path "tests\*.py" -Pattern "^from tests\.|^import tests\."   -> 25 matches in 13 files
  tests/test_proxy_fixes_f5.py:8:
    from tests.test_proxy_harness import PROXY_TOKEN, nedotify_home, app_core, offline_handler  # noqa: F401
  ```
- **Suggested fix:** Move `run_node`/`source` into `tests/jsdom.py` (or `conftest.py`), the proxy fixtures into `tests/conftest.py`, and `DeferredExecutor` into `tests/helpers.py`; keep the collected test files free of cross-imports.
- **Fix side effects:** Fixture discovery rules change (a fixture defined in a non-`conftest` module is not auto-available), so the import list must be updated in the same change.
- **Discovered by:** B

---

#### F-WN-34-11  [P2] — Process-global caches leak across test files; only 4 files isolate them

- **File:** `services/base_service.py:124–133, 164–171`; `core/api.py:99–102` (`_ssrf_cache`); `tests/test_cache_lru.py:22–34`; `tests/test_api_audit_b.py:63–68`
- **Confirmed:** yes
- **Description:** Several pieces of state are **class-level / module-level globals** that every test in the process shares:
  ```python
  # services/base_service.py:124-133
  class BaseMusicService:
      _executor = _SharedExecutor(max_workers=8)
      _cache_lock = threading.RLock()
      _stream_cache: Dict[str, Any] = {}
      _search_cache: Dict[str, Dict[str, Any]] = {}
  # core/api.py:99-102
  _SSRF_CACHE_TTL = 120.0
  _ssrf_cache: dict = {}
  ```
  Only **four** test files define an `autouse` fixture at all (`test_api_audit_b.py:63`, `test_cache_lru.py:22`, `test_engine_resolve.py:239`, `test_stream_startup_performance.py:18`), and only two of them reset the globals they touch. Other files mutate the shared caches directly without isolation — `tests/test_playback_recovery.py:75` (`BaseMusicService._stream_cache.pop(...)`), `tests/test_soundcloud_drm_unavailable.py:174,176` (`.clear()`), `tests/test_lyrics_performance.py:324` (writes `lyrics_cache` rows). `BaseMusicService._executor` is a single 8-worker pool shared by every provider and every test in the process; it is never shut down by the suite except in three files that call `svc._executor.shutdown(...)`.
- **Cause:** Production state lives on class objects rather than on injected instances, and the suite has no session-level reset fixture.
- **Trigger conditions:** Running the suite in a different order (`pytest -p no:randomly` isn't used, but the import graph already fixes part of the order — see F-WN-34-10), or running a single file after another in the same process.
- **User impact:** Order-dependent results and cross-file pollution; a test can pass in isolation and fail in a full run, or vice versa.
- **Evidence:**
  ```
  $ Select-String -Path "tests\*.py" -Pattern "autouse"
  test_api_audit_b.py:63, test_cache_lru.py:22, test_engine_resolve.py:239, test_stream_startup_performance.py:18
  $ Select-String -Path "tests\*.py" -Pattern "_stream_cache|_search_cache"
  -> 30 hits across 7 files, only test_cache_lru.py isolates them (autouse snapshot/restore)
  ```
- **Suggested fix:** Add a session-scoped autouse fixture in `tests/conftest.py` that snapshots/restores `BaseMusicService._stream_cache`, `_search_cache`, `core.api._ssrf_cache` and the provider caps around every test; shut the shared executor down at session end.
- **Fix side effects:** A per-test snapshot of the caches adds a small cost; the `test_cache_lru.py` fixture becomes redundant (and can be removed).
- **Discovered by:** B

---

#### F-WN-34-12  [P2] — `services/yandex_service.py` and `core/services/recommendation.py` have zero test coverage

- **File:** `services/yandex_service.py` (12 224 B), `core/services/recommendation.py` (8 722 B), `tests/test_engine_resolve.py:148–159, 1053–1063`
- **Confirmed:** yes
- **Description:** Two production modules are never loaded by the suite:
  - **`services/yandex_service.py`** — the only importer is `core/app.py:205` (a lazy import inside the `yandex` property), and `AppCore.__init__` is never executed (F-WN-34-1). The Yandex tests use a local stub instead: `tests/test_engine_resolve.py:148` `class _Yandex:` … `:1053` `def test_yandex_branch_resolves_through_the_yandex_service()`. The real service — including the documented unsanitised filename `ya_<raw_id>_<ts>.mp3` (per `WIN_AUDIT_CONTEXT.md` rule 8) — is never executed.
  - **`core/services/recommendation.py`** — a repository-wide search finds **no Python importer at all**; the only references are in the audit documentation (`docs/audits/WIN_AUDIT_CONTEXT.md:57`, `WIN_AUDIT_AREAS.md:37`). It is orphaned production code with no test and no caller.
- **Cause:** The suite tests *branches* through stubs rather than the provider implementations; dead or rarely-used modules are never imported, so pytest never notices they exist.
- **Trigger conditions:** Always (this is a static gap, not a race).
- **User impact:** 21 KB of unexercised production code. The Yandex filename defect called out in the shared context brief has no regression test; a dead module in `core/services/` is invisible to the whole quality process.
- **Evidence:**
  ```
  $ git grep -n "core/services/recommendation|core.services.recommendation"  (excluding android)
  ./docs/audits/WIN_AUDIT_AREAS.md:37, ./docs/audits/WIN_AUDIT_CONTEXT.md:57   -> docs only, no code
  $ Select-String -Path "core\*.py","services\*.py","tests\*.py" -Pattern "yandex_service"
  app.py:205: from services.yandex_service import YandexService    (lazy, inside the property)
  ```
- **Suggested fix:** Add `tests/test_yandex_service.py` (filename sanitisation, cache TTL, reset_client) and either wire `core/services/recommendation.py` into `core/app.py` or delete it; add a gate that fails when a module under `core/`/`services/` has no importer and no test.
- **Fix side effects:** New tests need the Yandex client faked — `services/yandex_service.py` uses the `yandex-music` package, so a fake client object must be injected or the module must gain a seam (see ARCH-2).
- **Discovered by:** B

---

#### F-WN-34-13  [P3] — A test writes two scratch files into the repository tree

- **File:** `tests/test_keybind_contracts.py:131–134, 148–150`
- **Confirmed:** yes
- **Description:** `_format_key_name()` writes its extracted JS body and its runner **into the `tests/` directory**:
  ```python
  body_path = Path(__file__).with_name("_fmtkey_body.js")
  body_path.write_text(body + "\nmodule.exports = formatKeyName;\n", encoding="utf-8")
  runner = "console.log(JSON.stringify(process.argv.slice(2).map(c => require('./_fmtkey_body.js')(c))));\n"
  path = Path(__file__).with_name("_fmtkey_runner.js")
  path.write_text(runner, encoding="utf-8")
  ```
  They are removed in a `finally` block (`:148–150`), but a killed run, a Ctrl-C, or a second parallel pytest process leaves them in the working tree — and `_fmtkey_runner.js` is *not* covered by `.gitignore`.
- **Cause:** The scratch directory is the repository instead of `tmp_path`.
- **Trigger conditions:** An interrupted run, or two pytest processes running concurrently in the same checkout.
- **User impact:** Stray files in the source tree (`git status` noise); a concurrent run can read another run's half-written body and produce a false failure.
- **Evidence:** `tests/test_keybind_contracts.py:131–134` (quoted above); `.gitignore` has no `*.js` scratch rule.
- **Suggested fix:** Write the two files into `tmp_path` and pass the absolute path to node; `require()` needs an absolute path or a `cwd` of `tmp_path`.
- **Fix side effects:** The runner uses a relative `require('./_fmtkey_body.js')`; switching to `tmp_path` requires adjusting `cwd=` (the call already passes `cwd=str(REPO_ROOT)`).
- **Discovered by:** B

---

#### F-WN-34-14  [P3] — `tests/benchmark_lyrics_cache.py` sits in the test directory but is never collected; `pytest-asyncio` is a dependency with zero users

- **File:** `tests/benchmark_lyrics_cache.py:1–69`; `requirements-dev.txt:2`
- **Confirmed:** yes
- **Description:** `tests/benchmark_lyrics_cache.py` is a standalone benchmark script (`if __name__ == '__main__': main()`), documented as "From the repository root in PowerShell: `& ".venv_win\Scripts\python.exe" tests/benchmark_lyrics_cache.py`". Because its name does not start with `test_`, pytest never collects it — it is neither a test nor a gate. It lives in `tests/`, so it is also inside the directory the suite treats as "the regression suite". `requirements-dev.txt` pins `pytest-asyncio==1.4.0`, but **no test uses asyncio** (`Select-String -Pattern "asyncio|async def test"` → 0 matches), and `pytest.ini` does not configure `asyncio_mode`.
- **Cause:** Two different kinds of artefact (benchmark, dependency) were parked in the test directory / dev requirements without a rule about what belongs there.
- **Trigger conditions:** Always (a latent trap: adding an `async def test_*` would silently not run without `asyncio_mode`).
- **User impact:** Dead dependency in CI (`pip install -r requirements-dev.txt` installs it on every run); a benchmark that produces no recorded artefact and is not gated; the suite's directory mixes tests, harnesses and scripts.
- **Evidence:** `tests/benchmark_lyrics_cache.py:1–5` and `:69–70`; `requirements-dev.txt`; `pytest --collect-only -q` → 1506 collected, `benchmark_lyrics_cache.py` absent.
- **Suggested fix:** Move the benchmark to `tools/bench/` (where the other harnesses live) and delete `pytest-asyncio` from `requirements-dev.txt` until an async test exists; alternatively configure `asyncio_mode = strict` and keep it.
- **Fix side effects:** None functional.
- **Discovered by:** B

---

#### F-WN-34-15  [P3] — `tests/test_frontend_js.py` states that the frontend has no runtime harness; the statement is stale

- **File:** `tests/test_frontend_js.py:1–8`; `tests/test_frontend_js.py:62–78`
- **Confirmed:** yes
- **Description:** The module docstring says:
  > "The Windows frontend is Vanilla-JS ES modules running inside pywebview/WebView2 and has **no runtime test harness** in this repository. Everything below is therefore a *static* assertion on the shipped source text (plus a real `node --check` parse when a Node binary is available). These tests prove the intended wiring is present in the files; they do NOT prove the UI behaves correctly at runtime."
  This is **false**: 20 test files now execute real JS through node (`test_recommendation_ui.py`, `test_player_resources.py`, `test_visual_effects_lifecycle.py`, `test_flow_ui.py`, `test_smart_search_ui.py`, …). The file itself only does `node --check` (a parse) at lines 62–78 — a *syntax* gate, not a behavioural one.
- **Cause:** The docstring was written when the JS suite was purely static and was never updated when the node harnesses were added; nobody re-reads docstrings.
- **Trigger conditions:** Always.
- **User impact:** A reader (or a reviewer) underestimates the real coverage and overestimates the risk; the file's name and docstring also invite a reviewer to treat `node --check` as a behavioural gate. It directly contradicts the measured behavioural/static ratio.
- **Evidence:** quoted docstring; contrast with `tests/test_recommendation_ui.py:18–23` (a real `node --input-type=module` runner with runtime assertions) and the 20-file behavioural set.
- **Suggested fix:** Rewrite the docstring to say "syntax + static wiring checks for these specific modules; the behavioural coverage lives in test_<area>_ui.py / test_player_*.py"; add a pointer to the shared harness.
- **Fix side effects:** None.
- **Discovered by:** B

---

#### F-WN-34-16  [P3] — `AppApi.cleanup()` is never called by the suite; the `api` fixture leaks two thread pools

- **File:** `core/api.py:446–457`; `tests/conftest.py:97–101`
- **Confirmed:** yes
- **Description:** `AppApi.cleanup()` is the only place that shuts down the two executors the constructor creates:
  ```python
  # core/api.py:362-369 (constructor)
  self._search_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")
  self._prefetch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="StreamWarmup")
  # core/api.py:454-457 (cleanup)
  if getattr(self, "_search_executor", None) is not None:
      self._search_executor.shutdown(wait=False, cancel_futures=True)
  ```
  `Select-String -Path "tests\*.py" -Pattern "\.cleanup\("` finds exactly one hit — `tests/test_db_core_fixes_f2.py:619` `AppCore.cleanup(core)` — which is **`AppCore.cleanup`**, not `AppApi.cleanup`. The shared `api` fixture (`tests/conftest.py:97–101`) yields the `AppApi` without ever calling `cleanup()`, and `AppApi` has no `__del__`.
- **Cause:** The fixture was written for the constructor only; the teardown path was never wired.
- **Trigger conditions:** Every test that uses the `api` fixture (9 files) and submits work.
- **User impact:** Worker threads of the 6-worker search pool and the 2-worker prefetch pool stay alive for the whole session (they are non-daemon and joined at interpreter exit); the bridge's own teardown contract — the one that must cancel in-flight work on window close — is never exercised.
- **Evidence:** `Select-String -Path "tests\*.py" -Pattern "\.cleanup\("` → 1 hit, `AppCore.cleanup`; `core/api.py:454–457` shows the only shutdown site.
- **Suggested fix:** Make the `api` fixture teardown call `api.cleanup()`; add a test that asserts `cleanup()` cancels the search/prefetch executors and stops the engine.
- **Fix side effects:** `AppApi.cleanup()` currently touches window state; calling it from a fixture may surface latent errors in the teardown path (which is the point, but it will turn green tests red until fixed).
- **Discovered by:** B

---

### 3. Clean areas

- **`tests/conftest.py:132–167` (`home_expander`)** is a genuinely good piece of engineering: it handles `~`, `~/x`, `~\x` and mixed separators, delegates `~user` to the native implementation, and normalises to `os.sep`. `tests/test_conftest_home_isolation.py` (13 tests) pins every one of those properties, including a traversal case (`"~/.nedotify/../escape"`) and a no-leak assertion. This is the strongest part of the suite.
- **`tests/test_proxy_harness.py`** exercises the proxy over a **real loopback socket** with a real `DatabaseManager` and a recording stub engine; the status line, headers and body are asserted as a browser would see them. That is the right level of abstraction for a stream proxy.
- **`tests/test_emit_thread_safety.py`** pins the `_emit`-must-not-run-on-the-UI-thread contract from `AGENTS.md` with a real thread and a real clock — exactly the contract the shared brief calls out as non-negotiable.
- **`tests/test_keybind_contracts.py`** compares the Python `DEFAULT_SETTINGS["hotkeys"]` against the JS `DEFAULT_KEYBINDS` table (rule 5 of the shared brief) and compiles the real `formatKeyName()` out of `settings.js` to test it; the `git check-ignore` usage in `tests/test_repo_hygiene.py` tests the real rule table (`--no-index -v`) instead of re-implementing the patterns.
- **`pytest.ini` / `run_tests.py`** are correctly factored: `run_tests.py` delegates entirely to pytest so the ini is the single source of truth. `pytest --collect-only` is fast (1.65 s) and the full suite runs in 62 s.
- **`tests/test_build_and_brand.py`** cross-checks the PyInstaller spec, the Inno Setup installer and the autostart registry value name, which is the kind of cross-boundary contract that is usually missed.
- The **bug-bucket test files themselves are good tests** — they are opaque-box, each test's name/docstring says which pre-fix behaviour it pins, and they avoid touching the network and the real profile. The finding is about their *organisation*, not their quality.

---

### 4. Coverage gaps

- **I did not execute the network path.** No test in the repository uses the `network` marker (F-WN-34-7), so there is no live-provider coverage at all; `pytest -m network` collects zero tests. Whether the providers still work against the real services was therefore not verified by this review.
- **I did not run the suite against the real `~/.nedotify/`.** Every execution in this review used a redirected `USERPROFILE`/`HOME` (`%TEMP%\opencode\wn34\fakehome`) precisely to avoid touching the user's library, so the *current* behaviour of the suite against the real profile was not directly observed — the real-profile artefacts reported in F-WN-34-6 were found by read-only listing and byte comparison.
- **`main.py` was not executed by the suite at all** (never imported by any test). The WebView2 pin, the DoH fallback, the single-instance mutex, the Bottle route capture and the startup watchdog — all listed in `WIN_AUDIT_CONTEXT.md` as WN-01's subject — have **zero** test coverage. I did not attempt to launch the app (forbidden by the brief).
- **The `AppCore` wiring is untested** (F-WN-34-1), so the proxy-start, Discord-RPC-start, watchdog-start, zapret-autostart and yt-dlp-update paths are unverified; the product defects there belong to WN-02/WN-26 and should be raised by their owners.
- **`core/api.py:542–597` — the dead tray block** (`return False` at 572 makes `self._tray.start()` at 575 unreachable) has no test. The defect itself is already recorded as `F-AR-04-1` in `docs/audits/FULL_PROJECT_AUDIT.md:64`; the **owner is WN-04 / WN-16**. From the WN-34 side the gap is: `tests/test_snap_layouts.py` covers `core/snap_layouts.py` (the Win32 subclass) but nothing covers the *wiring* that calls it, which is why the dead block survived.
- **`ui/web_new_v2/js/**` — 7 of 33 first-party modules have no test of any kind** (not even a grep): `contextmenu.js` (2 015 B), `debug.js` (1 839 B), `downloads-view.js` (9 063 B), `home-shell.js` (8 122 B), `queue.js` (13 037 B), `settings-view.js` (11 136 B), `window-resize.js` (1 360 B). Exactly **3** more are only grepped / syntax-checked: `boot.js`, `hotkeys.js`, `pages.js`. The remaining **23** are executed at runtime by a node harness (`appearance-assets, artist_profile, efficiency, equalizer, events, feature-controls, home, library, library-view, lyrics, main, onboarding, particles, player, profile, profile-comparison, search, search-discovery, settings, smart-playlists, ui-style, utils, visualizer`).
- **Grep : behavioural ratio for the frontend (measured, method stated).** Classification rule: *behavioural* = the module's source is handed to a node runtime and the assertions are on runtime behaviour; *static* = the module is only read as text (substring/regex) or passed to `node --check` (a parse). By **module**: 23 behavioural / 3 static / 7 untested out of 33 → **70 % behavioural, 9 % static-only, 21 % untested**. By **test file**: of the 31 files that reference a `.js` file, **20 execute JS** (83 test functions) and **11 only grep or syntax-check** (77 test functions) → **≈ 1.1 : 1**. By **test function** inside those two groups: 83 : 77. A stricter reading — counting *every* test function in the JS-facing files, including the ones that only check CSS/HTML — gives 83 : 204 (29 %), which is the lower bound of the range.
- **The `visual_guard` harness is not a gate.** `tools/visual_guard/run_guard.py` (33 KB) and `tools/bench/**` (34 files) are not referenced by any workflow or test; `tests/test_visual_guard_diff.py` / `test_visual_guard_css_decls.py` cover the *report format*, not the capture pipeline. No visual-regression or performance number is enforced anywhere.
- **Coverage is not measured at all** (no `pytest-cov`, no `.coverage`, no threshold), so "coverage" in this report means *module import reachability* and *test-function counts*, not line/branch coverage.
- **`core/listening.py`, `services/lyrics_lookup.py` and `services/yandex_service.py`** are imported by tests only indirectly (via `from core import listening`, a `monkeypatch.setattr('services.lyrics_lookup.os.stat', …)` string target, and a lazy import respectively); their internal behaviour is only lightly exercised.

---

### 5. Architecture improvements (ARCH)

- **ARCH-1 — Give `AppCore` an injection seam; this is the root cause of the weak suite.**
  `AppCore.__init__` (core/app.py:94–185) hard-codes every collaborator, so the suite can only fake the *object graph* and never the *wiring*; that is why `AppCore.__init__` is never executed (F-WN-34-1) and why 21 KB of production code (F-WN-34-12) has no coverage. A `AppCore(providers={...}, db_path=..., network=False, factories={...})` parameter with production defaults would let one real-wiring test exist and would make the whole suite hermetic by construction rather than by remembering a fixture.
- **ARCH-2 — Give the providers an injectable HTTP client.**
  There is no seam anywhere: `services/base_service.py:136` takes no arguments, `services/soundcloud_service.py:155` builds `requests.Session()` in `__init__`, `services/spotify_service.py:18` builds one as a **class attribute at import time**, `services/lastfm_service.py:152` builds a new one per call, and `services/lyrics_service.py:241` calls `urllib.request.urlopen` directly. Every network test must therefore monkeypatch a global, which is why the provider tests are the most fragile part of the suite. One `http_client`/`session_factory` parameter on `BaseMusicService` would remove most of the monkeypatching.
- **ARCH-3 — One shared DOM stub instead of five private copies.**
  `test_flow_ui.py`, `test_player_resources.py`, `test_visual_effects_lifecycle.py`, `test_recommendation_ui.py` and `test_player_recovery_transitions.py` each embed their own fake `document`. A new product DOM read broke all of them at once (F-WN-34-4). A single `tests/jsdom.py` with a contract test ("the stub exposes every `document.*` member the production JS reads") would have turned one product change into one stub update.
- **ARCH-4 — Organise the suite by module, not by audit bucket.**
  6 of 101 files (5.9 %) use triage-bucket names (`test_api_audit_b.py`, `test_api_f1_audit.py`, `test_db_core_fixes_f2.py`, `test_media_guard_f3.py`, `test_service_fixes_f4.py`, `test_proxy_fixes_f5.py`) holding **138 of ~1052 test functions (13.1 %)**; their identifiers (`P0-5`, `H1`, `M3`, `F1`…`F5`) belong to `docs/AUDIT.md` and mean nothing to a reader of the code. **34 of 54 production modules have no obviously-named test file**, so a reader cannot answer "is `core/session.py` tested?" from the file listing. A `tests/test_<module>.py` convention (one file per production module, sub-suites by concern) plus pytest **markers** (`@pytest.mark.slow`, `@pytest.mark.ui`, `@pytest.mark.provider`) would keep the triage information without the opaque file names.
- **ARCH-5 — Make isolation the default, not a fixture you must remember.**
  `redirect_home` should be `autouse=True` (F-WN-34-6), joined by an autouse reset of the process-global caches (F-WN-34-11) and a teardown that calls `api.cleanup()` (F-WN-34-16). "Hermetic by construction" is currently a claim in the `tests/conftest.py` docstring, not an invariant of the suite.
- **ARCH-6 — Promote the existing static tools into CI.**
  `tools/check_lock_nesting.py` and `tools/check_shadow_imports.py` already exist and encode two hard-won lessons from this codebase (F-WN-34-5); one scans the wrong directory, the other has two false-positive classes, and neither runs anywhere. Fixing them and adding them as a CI step (together with a linter, a type check and a coverage floor — F-WN-34-8) converts "we wrote a tool once" into "the defect cannot come back".
- **ARCH-7 — Pin the toolchain.**
  No lockfile exists and `requirements.txt` uses ranges, so the same commit can install different dependencies on CI and on a developer machine (F-WN-34-8). A `pip-compile`/`uv` lockfile committed alongside `requirements.txt` would make the gate reproducible.
- **ARCH-8 — Close the frontend coverage gap at the DOM level.**
  7 of 33 first-party JS modules have no test at all and 3 more have only static coverage; of the 31 test files that touch a `.js` file, 20 execute it and 11 only grep it (83 behavioural vs 77 static test functions, ≈ 1.1 : 1 — the conservative lower bound is 83 : 204, 29 %). The static half asserts on *source text*, so it pins the wiring but not the behaviour: it cannot catch a wrong `await`, a wrong branch, or a DOM contract drift (exactly the class of defect that broke 11 tests — F-WN-34-4). A single browser-level harness (Playwright/Chromium against the shipped `ui/web_new_v2/`) would cover all 33 modules with one fixture and would also give the `visual_guard` harness a real gate.
- **ARCH-9 — Make the gate honest about what it covers.**
  `pytest.ini` should carry `--strict-markers --strict-config` and `filterwarnings = error`; the `network` marker should either be used or deleted (F-WN-34-7); the skill file (`.claude/skills/nedotify-test/SKILL.md`) should list the suites that actually exist and state the node-dependency caveat. Today the documentation describes a suite that does not exist.
