# Windows audit remediation — tools and packaging

Scope: `tools/`, packaging inputs, and closely related tests. This report was
prepared without launching NeDotify, a built executable, a browser, or a GUI.
Live benchmark and visual captures were intentionally not run.

## Findings

| Audit IDs | Status | Resolution / evidence |
|---|---|---|
| AUD-459–460 | Fixed | Static checkers scan production roots, preserve Python lexical scope, and recognize actual `threading.Lock`/`RLock` constructors. Synthetic coverage is in `tests/test_tool_checkers.py`; CI runs both checkers. |
| AUD-405 | Fixed | Pixel comparison now fails closed when the golden directory contains no PNGs; the CSS declaration guard also rejects an empty declaration baseline. Synthetic tests cover both empty-baseline cases in `tests/test_visual_guard_diff.py` and `tests/test_visual_guard_css_decls.py`. |
| AUD-461 | Deferred | Fresh golden captures require a running app/WebView. The user prohibited app/GUI launch, so no pixel captures were generated. The CSS declaration baseline is static and has been regenerated independently. |
| AUD-462 | Fixed | `verify_frontend_report.py` reconfigures stdout/stderr to UTF-8 with replacement for unencodable characters. |
| AUD-463 | Partially contained | Scroll benchmark returns an explicit error when the selected node is absent or has no overflow, preventing empty-node data from being reported as 60 FPS. It still needs a live UI scenario to prove the default targets overflow. |
| AUD-464 | Fixed in benchmark harness; live measurement unverified | The isolated benchmark child replaces provider-facing `AppApi` methods with deterministic seeded fixtures. Search and feed use the normal bridge event path without provider/network calls. A mocked bridge contract test covers search, feed, and download fixture events; the app-backed measurement was not run under the no-GUI restriction. |
| AUD-465 | Fixed | Aggregation excludes failed repetitions from medians and records total/successful/failed counts plus failures; the command exits nonzero unless every requested repetition succeeds. Covered by `tests/test_bench_tooling.py`. |
| AUD-466 | Fixed in scenario; live measurement unverified | The scenario seeds a silent local WAV, calls the real `get_library`/`play_track` bridge, and requires a recorded `state_changed` event with `playing` before sampling. It errors when playback is not confirmed. No app-backed playback was launched. |
  | AUD-467 | Fixed for static animation declarations | Regenerated `tools/bench/results/animation_declarations.json` from the current UI sources and ran the guard self-check: 411 declarations, 0 changed, 0 removed. The count dropped from 434 after the audit-mandated full-screen canvas blur removal and dead particle-animation removal; blur caps and deduplication also changed the authored declaration set. Pixel and animation runtime captures remain unverified without launching the UI. |
| AUD-468, AUD-492 | Fixed | CDP evaluation reads nested `exceptionDetails`; all WebSocket frame writes share a send lock so ping replies cannot interleave with command frames. Nested-exception behavior has an offline synthetic test. |
| AUD-469 | Fixed | The consistency checker now compares each child edge's charged time with the actual caller's cumulative time, instead of summing callers and comparing against the child total. Synthetic import-time tree linkage is covered by `tests/test_bench_tooling.py`; no stale profile result was regenerated. |
| AUD-470 | Fixed | `psutil` is declared as a development dependency in `requirements-dev.txt`; it is not added to runtime dependencies. |
| AUD-471 | Deferred | Existing benchmark reports and fingerprints remain stale. Regenerating them launches the app or runs live measurements, which were prohibited. |
| AUD-472 | Fixed | Ctrl+C terminates the measured child process, waits briefly, then kills it if needed before scratch-profile cleanup. |
| AUD-473 | Fixed | Visual capture now writes into `current/`, never removes reference goldens, and `--all` captures current output before comparison. A static test protects the destination/deletion contract. |
| AUD-474 | Fixed in benchmark harness; live measurement unverified | Added `play` and `download` scenarios. Playback uses a seeded local WAV and requires the backend playing event; download uses a benchmark-only API stub that writes a WAV under the scratch profile and emits `download_progress`/`download_complete`. Offline mocked tests cover scenario completion contracts. |
| AUD-475 | Fixed | Pixel-diff tolerance is now 0.025% (from 0.1%); synthetic boundary tests cover the new threshold in `tests/test_visual_guard_diff.py`. |
| AUD-476–477 | Fixed | CI runs on Windows with Python 3.14, installs `requirements-lock.txt` with `--require-hashes`, enforces strict pytest markers and excludes network-marked tests, runs static checkers, focused Ruff syntax/error checks, a scoped mypy check, and an incremental service coverage floor. The hash-locked resolver dry-run and the same test/static gates passed locally in an isolated temporary venv. |
| AUD-458 | Fixed | `tools/source_manifest.json` records all 133 desktop test Python files and 36 `ui/web_new_v2/js` modules in this checkout. `tools/check_source_manifest.py` detects omitted or missing files and, under `--require-tracked`, rejects paths absent from `git ls-files`; CI runs that strict mode. Synthetic Git repositories verify tracked, omitted, missing, and untracked cases without staging workspace files. |
| AUD-478–482 | Root/core/frontend owned or coordinated | These cover API/core test contracts, frontend behavior, shared test harnesses, global fixtures, and CI. They were not modified here beyond overlapping root-owned workspace changes. |
| AUD-483 | Fixed / coordinated | Yandex has isolated service tests in `tests/test_yandex_service.py`, and `core/services/recommendation.py` was removed because no production importer exists. The full offline CI suite runs the Yandex contract tests. |
| AUD-484–486 | Fixed | Keybind JS scratch files now live under `tmp_path`; the lyrics microbenchmark moved from `tests/` to `tools/bench/`; unused `pytest-asyncio` was removed; frontend test docstring now distinguishes static checks from other Node harness suites. |
| AUD-487 | Root-owned | API fixture teardown is being handled by the root agent. |
| AUD-488–491 | Fixed / verified | Bench tools import sibling modules through `tools.bench` rather than prepending the bench directory to `sys.path`; event recording is installed after the reloaded document is ready; import-time postorder linkage has a synthetic regression test; `--list` matches all ten argparse choices. |
| AUD-493 | Fixed in capture tooling; capture unverified | Every visual capture writes `machine_manifest.json` with Windows/Python/pywebview/WebView2 versions, CPU architecture, display adapter and driver versions, bundled font SHA-256 hashes, viewport/DPR, theme/screen list, and source fingerprint. No capture was run, so no host manifest was generated here. |
| AUD-494 | Fixed for generated outputs | Benchmark/profile/static-analysis outputs and visual capture/report artifacts now default to `%TEMP%\NeDotify\...`; callers can set `NEDOTIFY_BENCH_OUT`, `NEDOTIFY_VISUAL_GUARD_OUT`, or `--artifacts-dir` to choose another destination. Committed input artifacts and the CSS baseline remain in the repository. |
| AUD-495 | Fixed in packaging | PyInstaller excludes source `assets/backgrounds/photo-*.jpg`/`.jpeg` and `SOURCES.json`, while retaining WebP runtime assets and the JS catalog. The source JPEGs stay in the working tree for persisted-path migration. |
| AUD-496 | False positive against current UI references | Theme preview PNGs and `logo.png` remain live splash/favicon assets; the macOS presentation pack uses `atmosphere-dusk.png` and `library-wave.svg`. The spec keeps those files. |
| AUD-497 | Fixed | `icon.ico` is included in PyInstaller data files. |
| AUD-498 | Fixed with a release-time prerequisite | `tools/packaging/native_dependencies.json` defines optional `zapret/` and `bin/` bundles. Any present directory must contain a valid PE entrypoint, and `NEDOTIFY_RELEASE_BUILD=1` fails unless at least one bundle is present; the spec includes validated directories. No external binaries are checked into this checkout, so a release build intentionally fails until the bundle is supplied. |
| AUD-499 | Signing mechanism implemented; trusted artifact requires external certificate | `sign_release.ps1` validates the user's certificate/private key/EKU, invokes SHA-256 timestamped signing, enables signed Inno uninstallers and verifies signer/trust. See `WINDOWS_SIGNING.md`. No signing certificate/private key is available, so no actual signature is claimed or fabricated. |
| AUD-500 | Fixed | Inno Setup uses `AppMutex=Local\NeDotify_Installer_Guard`; `main.py` creates the same static session-scoped mutex alongside its profile-derived single-instance guard. The app owner confirmed the shared name. Installer and source-contract tests pin the contract. |
| AUD-501–502 | Fixed | `yt-dlp` is capped below 2027; `curl_cffi` is constrained to `>=0.10,<0.17`, matching the `yt-dlp 2026.8.19` metadata exclusions/range; `bottle` is declared directly. `requirements-lock.txt` pins the Windows CPython 3.14 runtime and development resolution with SHA-256 hashes. `pip install --dry-run --ignore-installed --require-hashes -r requirements-lock.txt` resolved successfully. |
| AUD-503 | Fixed in tray import | `core/tray.py` uses `Menu.SEPARATOR` instead of importing unavailable `Separator` from `pystray`; this root-owned change was verified by the parent. |
| AUD-504 | Fixed in spec | The wheel's sibling `curl_cffi.libs/*.dll` files are collected into the matching frozen destination. The frozen app was not launched, so runtime loading still needs the normal release smoke test. |
| AUD-514 | Fixed | Welcome text and installer task descriptions use Russian/English custom messages based on the selected language. |

## Verification

Commands used the repository interpreter. No application or GUI was started.

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_audio_fingerprint_duplicates.py tests/test_bench_tooling.py tests/test_tool_checkers.py tests/test_visual_guard_diff.py tests/test_visual_guard_css_decls.py tests/test_keybind_contracts.py
```

Result: **78 passed**.

After adding the source inventory and fail-closed baseline cases, the isolated
checker/visual-guard batch reported **61 passed**. The broader provider, proxy,
downloader, LUFS, duplicate, checker, and visual-guard regression batch reported
**115 passed**. The local `--require-tracked` command reports the shared
workspace's newly created test/JS files as untracked; they were not staged. The
same rule is covered with synthetic repositories, and CI will evaluate the
manifest after checkout of tracked sources.

The two static checkers also passed:

```powershell
& ".venv_win\Scripts\python.exe" tools/check_shadow_imports.py
& ".venv_win\Scripts\python.exe" tools/check_lock_nesting.py
```

Both static checkers reported `OK`. `tools/bench/run_bench.py --list` lists all
ten supported scenarios. Python compilation passed for the changed benchmark,
visual-guard, packaging-helper, and PyInstaller spec sources. A hash-locked
install completed in a temporary Python 3.14 environment, leaving the app
environment untouched. Ruff's syntax/import-error gate, the scoped mypy check,
and duplicate-service coverage run in CI were also validated there. The static
animation baseline self-check passed with 434 declarations. Live benchmark and
pixel-capture results remain unverified because they require launching the
app/WebView. The unrelated API and playlist failures from an earlier broader
run are recorded in the service remediation report and are outside this
tools/packaging scope.
