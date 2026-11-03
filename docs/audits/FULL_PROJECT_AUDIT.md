# NeDotify (AURA Music) — Windows Desktop — Full Project Multi-Agent Audit

**Subject:** the **Windows desktop product** — `main.py`, `core/`, `services/`, `audio/`, `utils/`, `ui/web_new_v2/`, `tests/`, `tools/`, packaging.
**Out of scope:** `android/` (the native Kotlin/Compose port). It was audited separately in a previous run — see `docs/audits/ANDROID_FULL_PROJECT_AUDIT.md` and `docs/audits/ANDROID_FINDINGS_REGISTER.md` (those files were preserved verbatim when this report replaced `FULL_PROJECT_AUDIT.md`).
**Repo root:** `C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main`
**Date:** 2026-10-20
**Method:** 94 independent reviewer agents — **70 primary** (35 logical areas × 2 independent roles) + **24 integration-scenario** reviewers (12 end-to-end scenarios × 2 roles) — followed by coordinator cross-review, source-level verification of every P0/P1 claim, and an automated test/compile pass.
**Mode:** read-only. **No source file was modified** (`git status --porcelain` shows the same 229 entries as before the audit). The writes are: this report, `docs/audits/REMEDIATION_PLAN.md`, the audit scaffolding (`WIN_AUDIT_CONTEXT.md`, `WIN_AUDIT_AREAS.md`), the reviewer dossiers under `docs/audits/agents/`, and preservation copies of the previous Android audit (`ANDROID_FULL_PROJECT_AUDIT.md`, `ANDROID_REMEDIATION_PLAN.md`) made before this report took over `FULL_PROJECT_AUDIT.md`.

---

## 0. Method

### 0.1 Area decomposition

The codebase was decomposed from its **actual** structure, not from a preset list. 35 areas were identified:

| Group | Areas |
|---|---|
| Bootstrap & lifecycle | WN-01 packaging/bootstrap · WN-02 AppCore wiring · WN-16 tray/assets/errors |
| The bridge (`core/api.py`, 4228 lines, ~200 methods) | WN-03 bridge core/SSRF/emit · WN-04 window mgmt · WN-05 playback/queue/listening · WN-06 search/catalog/library · WN-07 playlists/tags/dupes · WN-08 settings/onboarding/storage · WN-09 lyrics/cover/home/profile · WN-10 cache/prefetch/zapret/offline/smart-playlists |
| Core services | WN-11 loopback proxy · WN-12 SQLite · WN-13 downloader · WN-14 settings manager · WN-15 resolver/recovery · WN-17 engine/queue |
| Providers & features | WN-18 base/resolver/matching · WN-19 YouTube · WN-20 SoundCloud · WN-21 Yandex/VK/Spotify/Last.fm/iTunes · WN-22 lyrics · WN-23 recommendations · WN-24 catalog/artist/import/smart-playlists · WN-25 loudness/fingerprint/watchdog/comparison · WN-26 zapret/Discord · WN-27 utilities |
| Frontend (`ui/web_new_v2/`, 33 JS modules, 26 CSS, 1 HTML) | WN-28 document/bootstrap/event-bus/utils · WN-29 player/equalizer/queue/visualizer · WN-30 settings/hotkeys/style-picker · WN-31 search/home/particles · WN-32 library/downloads/lyrics/profile/onboarding · WN-33 theming & CSS |
| Quality | WN-34 test suite · WN-35 tooling (bench + visual guard) |

### 0.2 The two-reviewer rule

Every area received **two independent reviewers**:

- **Role A — Correctness & Reliability.** Logic errors, state-machine bugs, unhandled exceptions, race conditions, deadlocks, resource leaks, thread-safety violations, async mistakes, null/empty handling, boundary inputs, data loss, crashes, broken recovery.
- **Role B — Architecture, Security & Performance.** Layering and responsibility split, coupling, duplication, algorithmic inefficiency, excess allocation, data leaks, unsafe external-data handling, incorrect API usage, scalability, antipatterns, lifecycle mistakes, broken contracts, testability.

**Independence.** A and B received an identical scope with different specializations. Neither was given the other's brief, output, or conclusions; each was instructed to derive every claim from the source independently and to cite `path:line` plus a quoted snippet. Each wrote its full report to its own file (`docs/audits/agents/<AREA>-<A|B>.md`) and returned only a condensed summary to the coordinator, so no agent could see another's output before finishing.

### 0.3 Coordination, cross-review and verification

1. **Coordinator cross-review** — every agent's finding list was compared against the other role's list for the same area; overlapping findings were merged into one root cause, single-agent findings were marked as needing verification.
2. **Source-level verification by the coordinator** — every P0 and P1 claim was independently re-checked against the source (and, where possible, executed) before being admitted to the confirmed list. Verification commands and their raw output are quoted in §9.4.
3. **Rules for admission to the confirmed list:**
   - the claim must point at real code that still exists at the cited lines;
   - the cited behaviour must follow from that code (not from an assumption about the framework);
   - the "Confirmed / Hypothesis" label must match the evidence available;
   - speculative issues are reported separately in §10 (Coverage gaps) and §11 (Hypotheses), **never** in the defect tables.

### 0.4 What the reviewers were told not to do

No source edits; no dependency changes; no writes to `~/.nedotify/`; no launching the app; no style nitpicking; no "would be nicer" refactors; no invented findings (an area that is clean is reported as clean); no double-reporting a single root cause across areas.

---

## 1. Executive Summary

The NeDotify Windows desktop app is a **substantial, well-organised product with a fragile core**. The architecture is coherent (a pywebview bridge over a loopback proxy, a clean service layer, a vanilla-JS UI with no build step), the security instincts are visible and often correct, and the test suite is unusually large for a project of this size.

But the audit found that the **contract seams between layers are the weak point** — exactly the failure mode the project's own `AGENTS.md` warns about (*"a renamed event, a hotkey id present on one side of the bridge only, an unserialisable `_emit` payload — each disappears without a traceback"*). The most serious findings are not algorithmic; they are **contract divergences between a Python layer and a JavaScript layer, or between two Python layers, that no single-file review can see**.

### Headline findings

**One launch-blocking defect (P0).** `main.py:29` assigns `webview.settings['WEBVIEW2_RUNTIME_PATH']`. In pywebview 5.4 `settings` is an `ImmutableDict` that **raises `KeyError` on any new key** — verified by execution. The assignment is guarded by `os.path.exists(<pinned WebView2 path>)`, so on the very machine the pin was written for (where the pinned runtime *is* installed) the app **crashes at import and never starts**. On machines without the pinned copy the branch is skipped and the app runs — which is why the defect survived. The neighbouring `os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER']` line, which is the half that actually works, is unreachable because the crash happens first.

**One fixed, predictable, wildcard-CORS HTTP port (P1).** `main.py:555` calls `webview.start(http_server=True, private_mode=False)` with no `http_port`. pywebview then pins the server to `DEFAULT_HTTP_PORT = 42001` and serves the UI *and* the `/js_api/<uuid>` bridge endpoint with `Access-Control-Allow-Origin: *` (verified in the installed pywebview source). Any local process can squat the port and prevent the app from starting at all; the fixed port is also per-machine while the single-instance mutex is per-session.

**The tray never starts (P1).** `core/api.py:572` ends `_install_snap_layouts` with an unconditional `return False`. The `self._tray.start()` on line 575 and the window-icon helper on lines 577–597 are therefore **unreachable dead code** — verified by reading the file. `general.minimize_to_tray` defaults to `True`, so the user believes minimise-to-tray works while the ✕ button destroys the window and no tray icon appears.

**The SSRF guard fails open (P1).** `core/api.py:143-158` defaults the verdict to "safe" and, when DNS resolution fails, only downgrades it for four literal prefixes. `main.py`'s process-wide `socket.getaddrinfo` monkey-patch raises `gaierror` when its three DoH endpoints time out — so a DNS outage makes every hostname pass the guard, and the wrong verdict is then cached for 120 seconds. The resolved IP is also never pinned (check-time and fetch-time are two separate resolutions).

**The test suite is red on the current working tree.** `pytest` reports **11 failed, 1491 passed, 1 skipped, 3 xfailed**. All 11 failures share one root cause: `ui/web_new_v2/js/player.js:2244` and `:2358` read `document.documentElement.dataset.progressStyle` without optional chaining, while line 2513 in the same file uses `dataset?.uiStyle`. The Node-based test harness stubs `documentElement` without a `dataset`, so the tests abort with `TypeError: Cannot read properties of undefined`. Three of the affected test files are untracked (`??` in git), so this is a **live, uncommitted regression**.

**The bridge is a god object with three divergent settings APIs.** `core/api.py` exposes **174 public bridge methods** on one 4 228-line class. Two independent settings implementations exist (`get_setting`/`set_setting` at `:1853-1900` and `get_settings`/`save_setting` at `:2922-2962`) with **inverted argument order** and different semantics, plus `core/settings.py::SettingsManager` as a third path. Verified consequences: `set_setting` never triggers `update_autostart`, so the setting says "on" while the Run key is absent; `set_setting('auth','yandex_token',None)` writes to the wrong category and never clears the token.

**A confirmed UI defect from the same class.** `core/settings.py:256-264` stores `shuffle`/`repeat` under the `session` category, so `get_settings()` returns them at `settings.session.shuffle`. But `ui/web_new_v2/js/player.js:1981-1984` reads `settings.shuffle` / `settings.repeat` at the **top level** — always `undefined`. Result: the shuffle button is never highlighted, and the repeat button is **always** highlighted (`undefined !== 'off'` → `true`).

### Severity summary

| Severity | Count | Meaning |
|---|---|---|
| **P0** | **1** | The app does not start on the target machine |
| **P1** | **48** | Broken core functionality, a real vulnerability, or a silent data-integrity failure |
| **P2** | **254** | A defect in a specific scenario, a visible UI error, a measurable performance problem |
| **P3** | **151** | A non-critical defect, a small quality issue, a local optimisation |
| | **454** | **total confirmed findings** |
| **Cross-module** | **15** | Findings no single-area reviewer could see (§6, `X-01`…`X-15`) |
| **Architecture** | **9** | Improvements with no proven defect — reported separately, never mixed into the defect list (§8) |

The counts above are **machine-counted from this document**, not estimates. The full per-finding dossier with `path:line`, the quoted evidence, the cause, the trigger, the user impact, the reproduction and the fix side-effects is in §4 (P0/P1), §5 (P2/P3) and §6 (cross-module); the priority ordering and the dependency graph are in §11.

**ID ranges.** `AUD-001`…`AUD-020` are the primary P0/P1 findings (§4). `AUD-515`…`AUD-522` are the additional P1s raised by the integration reviewers (§4.1). `AUD-101`…`AUD-534` are the P2/P3 findings (§5) — the gap at `AUD-021`…`AUD-100` is deliberate, so the bands can never collide. `X-01`…`X-15` are the cross-module findings (§6).

### The single most valuable conclusion

**Most of the P1/P2 defects are contract divergences, not logic errors.** The codebase's own documentation names this failure mode. The remedy is not a rewrite: it is (a) a single source of truth for the settings tree, the event names, the download-status vocabulary and the proxy-URL shape; (b) one place that validates the shapes at the boundary; and (c) a test layer that exercises the **seams**, not only the units - because the current suite runs 1 495 assertions that mostly pass while the seams are broken in **fifteen** distinct, independently confirmed places (§6).

---

## 2. Architecture Overview

### 2.1 The product

NeDotify (AURA Music) is a Windows desktop music player: a **Python 3.14.7 backend** hosted in a **pywebview 5.4 WebView2 shell**, driving a **vanilla-JS/CSS frontend** with no build step, no bundler and no framework. A **loopback HTTP proxy** (`core/proxy.py`) sits between the WebView and the upstream streaming providers so that provider credentials never reach the browser and expired stream URLs can be self-healed.

```
                    ┌──────────────────────── pywebview / WebView2 ───────────────────────┐
                    │  ui/web_new_v2/index.html  +  33 ES modules  +  26 CSS files        │
                    │  window.pywebview.api.<method>(...)   ◄── JS → Python              │
                    │  window.onPythonEvent(name, payload)  ──►  Python → JS             │
                    └──────────┬──────────────────────────────────────┬──────────────────┘
                               │                                      │
                    ┌──────────▼─────────┐              ┌─────────────▼───────────────┐
                    │  core/api.py       │              │  core/proxy.py              │
                    │  AppApi (~200      │              │  ThreadingHTTPServer        │
                    │  bridge methods)   │              │  127.0.0.1:<port>           │
                    └──────────┬─────────┘              │  auth token + HLS rewrite   │
                               │                        │  + local file serving       │
                    ┌──────────▼─────────┐              └─────────────┬───────────────┘
                    │  core/app.py       │◄── AppCore: owns every subsystem, cleanup()
                    │  AppCore           │
                    └──────────┬─────────┘
       ┌───────────┬───────────┼────────────┬──────────────┬──────────────┐
       ▼           ▼           ▼            ▼              ▼              ▼
  core/        audio/      services/     utils/       core/database   tests/ + tools/
  proxy        engine      7 providers   cache        SQLite (WAL)
  downloader   queue       + features    scanner
  settings                 lyrics/recs
  resolver
```

### 2.2 Module inventory (production source, Windows product only)

| Layer | Files | Lines (physical) | Role |
|---|---|---|---|
| Entry point | `main.py` | 584 | process policy: WebView2 pin, DoH fallback, single-instance mutex, route capture, startup watchdog, session save/cleanup |
| Bridge | `core/api.py` | 4228 | `AppApi` — the entire JS↔Python surface |
| Wiring | `core/app.py` | 586 | `AppCore` — constructs every subsystem, owns `cleanup()` |
| Network | `core/proxy.py` | 1334 | loopback stream proxy, path safety, HLS rewriting, self-healing URLs |
| Persistence | `core/database.py` | 2489 | SQLite schema, migrations, the duplicate-cleanup migration, all persistence |
| Downloads | `core/downloader.py` (+`download_store.py`, `download_transfer.py`) | ~1015 | background queue, worker pool, resume, retry, cancellation |
| Settings | `core/settings.py` | 589 | defaults, DB-backed store, async writer, hotkey table |
| Resolution | `core/resolver.py`, `core/playback_recovery.py`, `core/offline.py` | ~450 | mem→DB→network resolution, single-flight, bounded stream renewal, offline helpers |
| Playback | `audio/engine.py`, `audio/queue.py` | ~950 | queue state, shuffle/repeat, track-change notification |
| Providers | `services/*.py` (26 modules) | ~9 800 | YouTube, SoundCloud, Yandex, VK, Spotify, Last.fm, iTunes + lyrics, recommendations, catalog, artist, playlist-import, smart-playlists, loudness, fingerprint, watchdog, zapret |
| Frontend | `ui/web_new_v2/js/*.js` (33) + `css/**` (26) + `index.html` | ~500 KB JS | player, queue, search, home, library, lyrics, profile, settings, onboarding, theming |
| Utilities | `utils/*.py` (6) | ~1 040 | cache manager, file scanner, search query, stream-URL expiry, tag parser, URL safety |
| Packaging | `setup_pyinstaller.spec`, `installer.iss` | ~200 | PyInstaller bundle + Inno Setup installer |
| Tests | `tests/*.py` (~100 files) | — | pytest suite; `pytest.ini` deselects the `network` marker by default |
| Tooling | `tools/bench/**`, `tools/visual_guard/**` | — | profiling harness, visual-regression harness, lock/shadow-import checkers |

### 2.3 The contracts that matter (and where they break)

This project is held together by five **implicit contracts**. Every one of them is implemented on both sides of a boundary, and each is a place where a divergence is invisible until a user hits it:

| # | Contract | Producer | Consumer | Status |
|---|---|---|---|---|
| C1 | Event names + payload shape | `core/api.py::_emit`, `core/downloader.py` | `ui/web_new_v2/js/events.js` | Mostly aligned (11 names verified identical in the WN-05 band); `download_complete` carries no `file_path` — consumers must not expect one |
| C2 | Settings tree shape | `core/api.py::get_settings` → `{category: {...}}` | `js/settings.js`, `js/player.js`, `js/feature-controls.js` | **BROKEN in at least two places**: the `network` category is missing from the list (`:2929`); `player.js` reads `settings.shuffle`/`.repeat` at the top level instead of `settings.session.*` |
| C3 | Hotkey table | `core/settings.py::DEFAULT_SETTINGS["hotkeys"]` | `ui/web_new_v2/js/hotkeys.js::DEFAULT_KEYBINDS` | **Verified identical** — both tables match, and a single-key write preserves the other ids (`tests/test_keybind_contracts.py` passes) |
| C4 | Proxy URL + auth token shape | `core/proxy.py::local_url` / `get_proxy_url` | `js/player.js::loadAudioSource` | Aligned; **three independent URL builders** exist with different quoting (`api.py:1218`, `api.py:2061-2071`, `engine.py:90-117`) |
| C5 | Download status vocabulary | `core/downloader.py`, `core/database.py::download_queue_set_status` | `js/downloads-view.js` | Aligned in the reviewed band; the *queue* vocabulary is not duplicated in a third place |

### 2.4 The five non-negotiable rules from `AGENTS.md` — audited status

| Rule | Verdict |
|---|---|
| 1. `_emit` never runs on the UI thread | **Holds** in the normal path (the UI-thread detection is by thread *identity*, captured at import). But the UI-thread branch spawns one OS thread per event with **no ordering** (verified: two emits arrived as `[2, 1]`) and its `try/except` does not cover the worker thread. `cleanup()` does not quiesce the path — `evaluate_js` is still called after cleanup (verified). |
| 2. A new shared field joins its class's existing lock | **Largely holds** in `BaseMusicService` and `StreamResolver`. It **does not hold** for `audio/queue.py` (no lock) and is violated by `core/api.py::_window_op_lock`, which is shared by six unrelated concerns including SQLite writes. |
| 3. `~/.nedotify/` is the user's library | **Violated**: `clear_storage("all")` deletes files **outside** `~/.nedotify` (verified against a real DB — a locally imported track's file was deleted and the DB row was left dangling). No UI caller today ⇒ latent P0. |
| 4. WAL is load-bearing | **Holds** — `journal_mode=WAL`, `busy_timeout=30000` and `foreign_keys=ON` all verified effective. |
| 5. The hotkey table is mirrored | **Holds** — verified identical from both sides. |
| 6. There is no SSE/WebSocket channel | **Holds** — the bridge callback is the only Python→JS path. |
| 7. `download_complete` carries `{"track_id"}` and no `file_path` | Holds in the backend; the JS side does not read a `file_path` from it. |
| 8. Filename sanitisation is not enforced | **Violated** — `services/yandex_service.py` still builds `ya_<raw_id>_<ts>.mp3` from an unsanitised id; the lyrics disk-cache key and the download filenames embed raw track metadata. |
| 9. Frozen-vs-source asset lookups need both `sys._MEIPASS` branches | **Violated** — `setup_pyinstaller.spec` does not ship `icon.ico` in `datas`, so the packaged app has no window icon; `zapret`/`bin` are bundled only if they exist relative to the process CWD. |
| 10. The plugin folder is never added to `sys.path` | **Holds**. |
| 11. Python 3.14.7 only | **Holds** — `.venv_win` is 3.14.7; `requirements.txt` states the floor. |

---

## 3. Multi-Agent Coverage

### 3.1 What was covered

**94 independent reviewer tasks** — 35 primary areas × 2 roles + 12 integration scenarios × 2 roles — each reading the real source, tracing call chains into neighbouring layers, and citing path:line plus a quoted snippet for every claim.

| Group | Areas | Primary files | Task count |
|---|---|---|---|
| Bootstrap & lifecycle | WN-01, WN-02, WN-16 | main.py, core/app.py, core/session.py, core/listening.py, core/plugins.py, core/tray.py, core/ui_assets.py, core/user_errors.py, setup_pyinstaller.spec, installer.iss | 6 |
| The bridge (core/api.py, 4 228 lines, 174 public methods) | WN-03 … WN-10 | core/api.py in eight contiguous ranges | 16 |
| Core services | WN-11 … WN-15, WN-17 | core/proxy.py, core/database.py, core/downloader.py + download_store.py + download_transfer.py, core/settings.py, core/resolver.py + core/playback_recovery.py + core/offline.py, udio/engine.py + udio/queue.py | 12 |
| Providers & features | WN-18 … WN-27 | 26 modules under services/, utils/, core/services/ | 20 |
| Frontend | WN-28 … WN-33 | ui/web_new_v2/index.html (2 314 lines), 33 ES modules, 25 CSS files, ui/MACos_ui/** | 12 |
| Quality | WN-34, WN-35 | 	ests/** (~100 files), 	ools/bench/**, 	ools/visual_guard/**, 	ools/check_*.py, .github/workflows/ | 4 |
| Integration scenarios | WX-01 … WX-12 | the 12 end-to-end flows listed in §0 | 24 |
| **Total** | **35 areas + 12 scenarios** | | **94** |

### 3.2 File coverage

| Surface | Covered | Note |
|---|---|---|
| main.py | 584 / 584 lines | read in full by WN-01 A/B, WX-07 A/B |
| core/api.py | 4 228 / 4 228 lines | split across WN-03…WN-10, each range read twice |
| core/*.py (12 modules) | all | WN-02, WN-04, WN-11, WN-12, WN-13, WN-14, WN-15, WN-16, WN-17 |
| services/*.py (26 modules) | all | WN-18 … WN-27, plus cross-references from WN-06/09/10 |
| udio/*.py | all | WN-17 |
| utils/*.py (6 modules) | all | WN-27 |
| ui/web_new_v2/js/*.js (33 modules) | all | WN-28 … WN-32, plus WX-01 … WX-12 call-site traces |
| ui/web_new_v2/css/** (25 files) | all | WN-33 (machine sweep + targeted reads) |
| ui/web_new_v2/index.html | 2 314 / 2 314 lines | WN-28 (script/link inventory, duplicate-id census) |
| ui/MACos_ui/** | all | WN-16 (routing), WN-33 (styling) |
| 	ests/** (~100 files) | all | WN-34 (AST classification of 1 093 test functions) |
| 	ools/** | all | WN-35 |
| setup_pyinstaller.spec, installer.iss, equirements*.txt, pytest.ini, un_tests.py | all | WN-01 |
| core/services/, udio/, utils/, plugins/, docs/ (authoritative docs) | read where they bear on a finding | WN-01…WN-35 |
| ndroid/** | **0 lines** | out of scope by instruction — never opened |
| Generated / vendored (hls.min.js, lucide.min.js, yt_dlp, pywebview, pystray, mutagen) | read where they define a contract | cited as the contract source |

### 3.3 Coverage caveats

- The **reviewers' line counts for the frontend were stale** in the area map: player.js is 2 711 lines (map said 2 489), settings.js 3 388 (map said 3 111), library.js 967 (854), lyrics.js 1 262 (1 144), rtist_profile.js 811 (743), utils.js 1 690 (1 533), search.js 1 250 (1 122), home.js 1 049 (955). Every reviewer read the **actual** file, so the coverage is complete; the area map was corrected in the report's §2.2.
- The **area map's core/api.py line ranges were also stale** (the file is 4 228 lines, not 3 795). The eight ranges were re-derived from the live file before dispatch, so every line is covered.
- 	ools/bench/** was **not executed** (it launches the real app and opens a CDP port). The tooling findings come from the code, the committed JSON artefacts, and direct calls of pure functions — and are labelled as such.
- The **app was never launched** and ~/.nedotify/ was never written to by the audit.

---

## 4. Critical Findings (P0 and P1)

Every finding below was **independently re-verified by the coordinator against the source** (and, where the claim was mechanical, re-executed) before being admitted. Findings reported by both reviewers of an area were merged into a single root cause; the "Discovered by" field lists every agent that found it.

---

### AUD-001 · P0 · CONFIRMED · Startup / packaging · main.py:24-30

**The app crashes at import with `KeyError` on the machine the WebView2 pin targets.**

- **Description.** main.py:29 assigns a **new** key to webview.settings. In pywebview 5.4 settings is an ImmutableDict that raises KeyError on any key it does not already contain.
- **Cause.** The guard if os.path.exists(<pinned WebView2 path>) makes the assignment conditional — so the crash occurs **exactly when the pin is in effect**, i.e. on the machine the code was written for. The neighbouring os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] line, which is the half that actually works, is never reached.
- **Trigger conditions.** The pinned runtime 151.0.4129.86\msedgewebview2.exe is present at `%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application\`.
- **User impact.** The process raises during module import — **before** the window, the DB, the proxy or the tray are created. The app never starts and shows no error; ~/.nedotify/logs/app.log is never even created. There is no recovery path short of the watchdog, which respawns and dies identically.
- **Evidence.**
  `python
  # main.py:24-30
  _PINNED_WEBVIEW2 = os.path.join(
      os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
      'Microsoft', 'EdgeWebView', 'Application', '151.0.4129.86',
  )
  if os.path.exists(os.path.join(_PINNED_WEBVIEW2, 'msedgewebview2.exe')):
      webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2   # <-- KeyError
      os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = _PINNED_WEBVIEW2
  `
- **Reproduction / verification** (executed by the coordinator):
  `
  settings type: <class 'webview.util.ImmutableDict'>
  RESULT: assignment RAISED KeyError "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."
  valid keys: ['ALLOW_DOWNLOADS','ALLOW_FILE_URLS','IGNORE_SSL_ERRORS',
               'OPEN_DEVTOOLS_IN_DEBUG','OPEN_EXTERNAL_LINKS_IN_BROWSER','REMOTE_DEBUGGING_PORT']
  WEBVIEW2_RUNTIME_PATH valid? False
  pinned path exists on this host: False   (installed: 155.0.4283.60 / .62)
  `
  ⇒ **latent on this host, fatal on the target host.** The defect is invisible here *because the pin is not present here*. WN-01-A additionally reproduced the full import failure with a faked ProgramFiles(x86) and a redirected HOME: import main → KeyError, rc=1, no log file created.
- **Recommended fix.** Delete line 29. The WEBVIEW2_BROWSER_EXECUTABLE_FOLDER environment variable on line 30 is the mechanism pywebview actually honours (edgechromium.py:98-107 passes no rowserExecutableFolder), so line 30 alone achieves the stated intent. If a runtime path is genuinely required, set the environment variable **before** importing pywebview and assert the key exists before assigning it.
- **Fix side effects.** None. Removing a line that always raises on the affected path cannot regress the working path. A defensive if 'WEBVIEW2_RUNTIME_PATH' in webview.settings: guard is acceptable but leaves the inert assignment in place.
- **Discovered by:** WN-01-A, WN-01-B, WX-07-A; independently verified and promoted to P0 by the coordinator.

---

### AUD-002 · P1 · CONFIRMED · Startup / webview server · main.py:555

**The UI and the bridge are served on a fixed, predictable port with wildcard CORS.**

- **Description.** webview.start(http_server=True, private_mode=False) is called with no http_port. pywebview therefore pins the server to DEFAULT_HTTP_PORT = 42001 and sets Access-Control-Allow-Origin: * on every response, including the POST /js_api/<uuid> bridge endpoint.
- **Cause.** The port is a module-level constant in pywebview, and the private_mode=False branch is the default for a non-ile:// UI.
- **Trigger conditions.** Always, on every start.
- **User impact.** (a) **Port squatting:** if any local process already holds 42001, the bind does not fail loudly — pywebview sets server.running = True without checking — the bridge is dead, and the user stares at a blank window while the watchdog respawns and fails the same way. (b) The port is **per-machine** while the single-instance mutex is **per-session** (Local\), so two Windows sessions on one machine collide. (c) A fixed, guessable port with Access-Control-Allow-Origin: * widens the surface for any web page the user has open.
- **Evidence.**
  `python
  # main.py:555
  webview.start(http_server=True, debug=_devtools, private_mode=False, storage_path=_storage_dir)
  `
  `python
  # .venv_win/Lib/site-packages/webview/__init__.py:70,192-193
  DEFAULT_HTTP_PORT = 42001
  if not _state['private_mode'] and not http_port:
      http_port = DEFAULT_HTTP_PORT
  # .venv_win/Lib/site-packages/webview/http.py:108
  bottle.response.headers['Access-Control-Allow-Origin'] = '*'
  `
- **Reproduction / verification.** Quoted pywebview source (above). WX-07-B additionally demonstrated the squatter case: the attacker binds first, GET /index.html returns the attacker's page, and pywebview loads it **inside the app's privileged WebView** — giving the attacker's script the whole AppApi surface. The double-bind was also reproduced independently by WN-01-A (SECOND BIND ON THE SAME PORT SUCCEEDED), because main.py:14 sets socketserver.TCPServer.allow_reuse_address = True and Windows SO_REUSEADDR permits it.
- **Recommended fix.** Pass an explicit random http_port (note: http_port=0 does **not** work — 
ot 0 is True in pywebview's check) and **assert the bind succeeded**. Narrow Access-Control-Allow-Origin from * to the app's own origin. Use a per-user mutex namespace.
- **Fix side effects.** The frontend addresses the **proxy** port (already dynamic), not the webview port, so no frontend change is needed.
- **Discovered by:** WN-01-B, WX-07-A, WX-07-B; verified by the coordinator.

---

### AUD-003 · P1 · CONFIRMED · Bridge / system tray · core/api.py:572-597

**The tray never starts — "minimize to tray" silently closes the app instead.**

- **Description.** _install_snap_layouts ends with an unconditional eturn False on line 572. The code that follows it — self._tray.start() (575) and the native window-icon setter (577-597) — is **unreachable dead code**. self._tray.start() at line 575 is the **only** call to _tray.start() in the entire repository.
- **Cause.** A eturn was inserted into the middle of the function when the Snap Layouts retry loop was added; the tray start was left below it. A **second, independent** blocker exists: core/tray.py:16 does rom pystray import … Separator, and the installed pystray 0.19.5 exports no Separator → ImportError → HAS_PYSTRAY = False (verified by executing the import).
- **Trigger conditions.** Always.
- **User impact.** No tray icon is ever created. core/api.py:924 therefore sees 	ray.icon is None and takes the "no tray" branch — so pressing ✕ **destroys the window** even though general.minimize_to_tray defaults to True. The user is told (in the settings) that minimising to the tray is enabled; it is not. The window also never gets its native icon.ico, so the packaged app shows a default icon.
- **Evidence.**
  `python
  # core/api.py:570-577
              time.sleep(delay)
          logger.warning("Snap Layouts skipped: no window handle after %.1fs", attempts * delay)
          return False                                   # <-- unconditional

          if getattr(self, "_tray", None):               # <-- unreachable
              self._tray.start()                         # <-- the ONLY call in the repo
  `
- **Reproduction / verification** (executed by the coordinator): the source above was read directly. WN-16-B and WX-12-A independently ran an AST scan reporting the statements after the eturn (:574, :577) and confirmed the single call site; WX-07-A additionally confirmed the pystray ImportError by executing the import.
- **Recommended fix.** Move the tray start and the icon setter **above** the Snap Layouts block (they are independent of the window handle) or into their own method called from set_window(). Raise the pystray floor to a version that exports Separator (or use pystray.Menu.SEPARATOR). Add a test that asserts the tray is started — 	ests/test_window_visibility.py:100 currently fakes 	ray.icon = object(), which is why the defect survived.
- **Fix side effects.** Starting the tray brings back a native resource that must then be released — see AUD-011 (AppApi.cleanup() is skipped on the watchdog restart path) and AUD-130 (TrayIcon.stop() cannot stop an icon pystray has not yet marked ready). Fix those **in the same change** or the app will start leaving a tray icon behind at exit.
- **Discovered by:** WN-04-A, WN-04-B, WN-16-A, WN-16-B, WX-07-A, WX-12-A, WX-12-B (cross-confirmed by seven agents); verified by the coordinator.

---

### AUD-004 · P1 · CONFIRMED · Security / SSRF · core/api.py:133-158

**The SSRF guard fails open when DNS resolution fails, and caches the wrong verdict for 120 seconds.**

- **Description.** _dns_resolves_to_public_ip initialises erdict = True (i.e. "safe"). Only inside the 	ry is it downgraded when a resolved address is loopback/private/link-local/reserved/multicast/unspecified. If socket.getaddrinfo raises, the except branch downgrades the verdict **only** for four literal hostname prefixes.
- **Cause.** The default was chosen as "safe" and the failure path was treated as "probably an internal host, check the string" — but the string check is both incomplete and unreachable in the common case.
- **Trigger conditions.** Any DNS failure. This is not hypothetical: main.py:160-230 replaces socket.getaddrinfo **process-wide** with a DoH resolver that raises gaierror after three 2-second endpoint timeouts. **A DNS outage therefore makes every hostname pass the guard** — and _ssrf_cache_put then stores "safe" for _SSRF_CACHE_TTL = 120 seconds, so the exposure persists for two minutes after the network recovers.
- **User impact.** The loopback proxy can be induced to fetch http://169.254.169.254/ (cloud instance metadata), http://127.0.0.1:<port>/ or any LAN host, using the app as a confused deputy. The 120-second cache makes the exposure window long and the recovery silent.
- **Evidence.**
  `python
  # core/api.py:143-158
  verdict = True
  try:
      addr_info = socket.getaddrinfo(hostname, None)
      for family, socktype, proto, canonname, sockaddr in addr_info:
          ip = ipaddress.ip_address(sockaddr[0])
          if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved \
             or ip.is_multicast or ip.is_unspecified:
              verdict = False
              break
  except Exception:
      # If DNS resolution fails, fallback string check
      if hostname.startswith("169.254.") or hostname.startswith("10.") \
         or hostname.startswith("192.168.") or hostname.startswith("127."):
          verdict = False
  _ssrf_cache_put(hostname, verdict)
  `
  Note also that 172.16.0.0/12 is missing from the fallback list, and ::ffff:127.0.0.1 is not handled there.
- **Reproduction / verification.** WN-03-A reproduced it by monkey-patching getaddrinfo: unresolvable.example -> True, and the cache entry ('unresolvable.example', (…, True)); the second call made **zero** DNS lookups (the poisoned cache). WN-03-B and WN-11-B independently confirmed the same mechanism and the "hex/octal IPv4 forms come back safe" variant. The coordinator re-read the source and confirmed the control flow above.
- **Recommended fix.** Fail **closed** on resolution failure (erdict = False), never cache the exception-path verdict, and replace the 4-prefix string fallback with a full ipaddress check over a best-effort parse. Consider a short, separate negative-cache TTL so a transient outage does not permanently block a host. Collapse this guard with utils/url_safety.is_safe_media_url into one implementation.
- **Fix side effects.** A DNS outage will block fetches instead of allowing them. That is the correct security posture, but it needs a user-visible "network unavailable" path rather than a silent failure, and the DoH fallback in main.py should get a shorter per-endpoint timeout so the total failure is fast.
- **Discovered by:** WN-03-A, WN-03-B, WN-11-B, WN-27-B; verified by the coordinator.

---

### AUD-005 · P1 · CONFIRMED · Security / SSRF · core/api.py:143-193

**The validated IP address is discarded — the address actually connected to is never the one that was checked (TOCTOU / DNS rebinding).**

- **Description.** _dns_resolves_to_public_ip resolves the hostname, inspects the addresses, and returns a ool. The resolved addresses are thrown away. The subsequent fetch performs its own resolution.
- **Cause.** The guard answers "is this hostname safe?" rather than "connect to this specific, validated address".
- **Trigger conditions.** A hostname whose DNS answer changes between the check and the fetch (a 0-second-TTL rebinding record), or any multi-A-record host whose answers differ per query.
- **User impact.** The SSRF protection can be bypassed entirely by an attacker-controlled DNS server: the first answer is a public IP (passes the check), the second is 127.0.0.1 or 169.254.169.254 (the fetch lands there).
- **Evidence.** core/api.py:145 resolves; :157 discards the addresses and stores only a bool; :193 returns the bool. The fetch sinks are core/api.py:2365 (playlist import), core/proxy.py:841 and core/proxy.py:954 (the proxy's upstream fetches), plus every redirect hop at core/proxy.py:379.
- **Reproduction / verification.** Confirmed by reading the code path; WX-01-B proved the double resolution with an alternating resolver (the guard returned True on its single resolution, the request then resolved to 127.0.0.1). A live rebinding attack was not performed — it would require a controlled DNS server and network egress.
- **Recommended fix.** Return the validated addresses and connect to one of them (preserving the Host header and TLS SNI so CDNs and virtual hosts still work), or re-validate the peer address after connect and abort on mismatch.
- **Fix side effects.** Pinning the address breaks SNI/virtual-host routing for CDN-backed providers unless the SNI and Host are preserved exactly; it must be rolled out per provider (YouTube/SoundCloud CDN hosts are the sensitive ones). This is a deliberate trade of CDN resilience for SSRF safety.
- **Discovered by:** WN-03-A, WN-03-B, WX-01-B.

---

### AUD-006 · P1 · CONFIRMED · Frontend / settings contract · core/settings.py:256-264 + ui/web_new_v2/js/player.js:1981-1984

**The persisted volume is never restored, the repeat button is permanently lit, and the shuffle button is never lit.**

- **Description.** core/settings.py:256-264 stores shuffle and epeat under the **session** category, and udio.volume under udio. AppApi.get_settings() (core/api.py:2922-2938) returns a **category-keyed** tree. But js/player.js:1973-1992 reads them at the **top level**: settings.volume, settings.shuffle, settings.repeat — all undefined.
- **Cause.** The settings tree's shape is declared in four places (DEFAULT_SETTINGS, the hard-coded category list in get_settings(), the JS accessors, and the localStorage mirror) and nothing verifies that they agree.
- **Trigger conditions.** Always.
- **User impact.**
  - udio.volume is write-only: the user's volume is **lost on every restart** (it returns to the hard-coded 70 — js/player.js:15, index.html:1997). AppApi.get_volume() has **zero** JS callers.
  - undefined !== 'off' is 	rue ⇒ **the repeat button is lit on startup even though repeat is off**.
  - undefined is falsy ⇒ the shuffle button is never lit — and js/library-view.js:182 then sees the inactive button and calls 	oggle_shuffle(), turning shuffle **off**, so "Перемешать" silently does nothing.
- **Evidence.**
  `python
  # core/settings.py:256-264
      "session": {
          "last_track_id": None,
          "last_position": 0,
          "last_volume": 70,
          "last_queue": [],
          "last_queue_index": 0,
          "shuffle": False,
          "repeat": "off",
      },
  `
  `javascript
  // ui/web_new_v2/js/player.js:1981-1984
  if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
  if (ppShuffle) ppShuffle.classList.toggle('active', settings.shuffle);
  if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
  if (ppRepeat) ppRepeat.classList.toggle('active', settings.repeat !== 'off');
  `
  `javascript
  // ui/web_new_v2/js/main.js:409  — the object IS the category-keyed tree
  window.nedotifySettingsReady = window.pywebview.api.get_settings().then((freshSettings) => {
  `
- **Reproduction / verification** (executed by the coordinator): the four source sites were read directly and the data flow traced (get_settings() → main.js:409 → pplySettings(freshSettings) → player.js:1973). WN-29-A, WN-29-B, WN-30-A, WN-17-A, WX-03-A and WX-12-A independently reached the same conclusion and quantified the volume loss.
- **Recommended fix.** Read settings.audio.volume, settings.session.shuffle and settings.session.repeat. More importantly, derive the transport from DEFAULT_SETTINGS so this class of defect cannot recur (§8.1, A-1).
- **Fix side effects.** None — the values are already in the tree; only the access path was wrong.
- **Discovered by:** WN-29-A, WN-29-B, WN-30-A, WN-17-A, WX-03-A, WX-12-A; verified by the coordinator.

---

### AUD-007 · P1 · CONFIRMED · Bridge / offline · core/api.py:461-512 + services/lyrics_service.py:241 + core/proxy.py:863-968

**Offline mode does not block all outbound traffic: lyrics, translation, waveform and the proxy's CDN path still leave the machine.**

- **Description.** AppApi._offline_bridge_result maintains a hand-written **method-name list** whose **default is ALLOW** (eturn False, None at :512). get_lyrics_translation **is** blocked; get_lyrics and get_waveform are **not** — and both perform outbound HTTP. Separately, the proxy's '/' branch (the production path for every CDN stream, built at udio/engine.py:97 and core/proxy.py:1316) has **no** offline gate: the guard at core/proxy.py:814 exists only in the /api/stream branch.
- **Cause.** The offline policy is a scattered boolean (41 checks in 6 Python files) rather than one boundary; the method list is a name allow-list rather than a capability attribute.
- **Trigger conditions.** The user enables offline mode and plays a cloud track.
- **User impact.** The user has explicitly asked the app not to use the network; their IP and their listening (title, artist, album, duration) still reach the lyrics providers and the waveform CDN, and the proxy fetches the CDN stream **with the provider credentials attached** (core/proxy.py:990-1006). The app contradicts itself in the same request: /api/stream correctly returns 503 while /?url= performs the fetch.
- **Evidence.** core/api.py:461-512 (the list, default ALLOW); core/api.py:3192-3225 → services/lyrics_service.py:241 (urllib.request.urlopen, no offline check); core/api.py:3583-3593 → services/soundcloud_service.py:1032; core/proxy.py:814-816 (the guard, in the /api/stream branch only) vs :863-1016 (the '/' branch).
- **Reproduction / verification.** WX-09-A and WX-09-B **executed** it with a hermetic harness: with offline ON, /api/stream → 503 with **zero** outbound attempts, while /?url=https://cdn.example/stream.mp3 → **1 recorded upstream fetch**. WN-03-A confirmed get_lyrics is absent from the interception list (_offline_bridge_result("get_lyrics", …) -> (False, None)); WN-09-B independently confirmed get_waveform is absent.
- **Recommended fix.** Enforce offline at the HTTP boundary (one guard inside the shared HTTP helper every provider uses) rather than at the bridge-method list; hoist the proxy's guard above the branch; serve lyrics from the local disk cache and the waveform from the cached peaks when offline.
- **Fix side effects.** Offline lyrics become cache-only — tracks never looked up before will show no lyrics while offline, which is the honest behaviour. The bridge-level list can then be reduced to a small set of genuinely local methods.
- **Discovered by:** WN-03-A, WN-09-A, WN-09-B, WX-09-A, WX-09-B.

---

### AUD-008 · P1 · CONFIRMED · Data integrity / destructive operations · core/api.py:3105-3154

**clear_storage("all") deletes the user's media files outside ~/.nedotify and leaves dangling database rows.**

- **Description.** _delete_downloaded_files unlinks 	rack['file_path'] for every track with is_downloaded, **with no root check**. A locally imported track (a title+artist collision sets is_downloaded = 1 and stores its real path in core/database.py:1122-1127) therefore has its file deleted — even though the file lives in the user's own music folder, not in the app's library. The DB rows are never updated.
- **Cause.** The "delete the downloads" step assumes every ile_path points inside ~/.nedotify/downloads. Nothing enforces that assumption.
- **Trigger conditions.** clear_storage("all") is called. **No UI caller exists today** ⇒ the defect is latent, which is why it is P1 and not P0.
- **User impact (verified against a real DB by WN-08-A).** After importing a local file, clear_storage('all') deleted …\MyMusic\Artist - Title.mp3 and returned True; the DB row still had is_downloaded = 1 pointing at the missing file. **The user's own music, outside the app's library, was destroyed** — with no root check, no confirmation and no record. The dangling row then blocks the auto-download path ("все любимые треки уже скачаны") and the library keeps listing a track whose file no longer exists.
- **Evidence.** core/api.py:3138-3154 (if os.path.isfile(fp): os.remove(fp) — no root check); core/database.py:1122-1127 (a local file gets is_downloaded = 1 and a real path); core/api.py:2671-2677 / core/api.py:3692 (the auto-download path trusts the flag).
- **Reproduction / verification.** WN-08-A executed it against a real SQLite DB with an AppApi instance: ile exists AFTER: False, DB row still is_downloaded=1. WX-02-B independently confirmed the dangling-row consequence (get_downloaded_tracks() -> [2] at the DB level while the API returned []).
- **Recommended fix.** Restrict the deletion to paths that canonicalise inside ~/.nedotify/downloads (use the same is_relative_to + ealpath pattern core/proxy.py already applies), delete the DB rows for the files that were actually removed **in the same transaction**, and require an explicit confirmation for the "all" variant.
- **Fix side effects.** Imported local media will stop being removable by "clear storage" — which is correct (it is not the app's cache), but the UI must reflect that.
- **Discovered by:** WN-08-A, WN-05-B, WX-02-B.

---

### AUD-009 · P1 · CONFIRMED · Frontend bootstrap / event bus · js/events.js:46-73 + js/main.js:352-372, 516-528 + main.py:391-400

**Bridge events that arrive before initEvents() installs the handler are silently dropped — the restored session track and session autoplay never reach the UI on every start.**

- **Description.** events.js holds let coreEventHandler = null; and guards every dispatch with if (coreEventHandler) {...}. The **only** assignment is inside initEvents(), which main.js:528 calls **after** wait safeInit('Icons') — a equestIdleCallback with a 50-300 ms delay, itself gated on the bridge becoming ready. Meanwhile main.py:391-400 emits 	rack_changed and session_autoplay from on_loaded(), and pywebview 5.4 fires loaded on a **separate thread** (webview/event.py:55-60) immediately after injecting the bridge (webview/util.py:210-225).
- **Cause.** A race between the Python side emitting during page load and the JS side installing its handler. There is no compensating pull path.
- **Trigger conditions.** Every start with a saved session.
- **User impact.** The user relaunches the app, the previous track and position were saved, and the player shows **"Не играет"** and does not resume. Session autoplay never starts. There is no error, no log line, and the events are gone — the exact "failure mode is silence" the project documents.
- **Evidence.** js/events.js:46 (let coreEventHandler = null), js/events.js:46-73 (the guard), js/main.js:516-528 (wait safeInit('Icons') then initEvents()), main.py:389-402 (on_loaded emits 	rack_changed + session_autoplay).
- **Reproduction / verification.** The assignment sites were enumerated by WN-28-A: coreEventHandler is assigned **only** inside initEvents(). WX-12-A independently confirmed the ordering from the pywebview source (util.py:218-222: inish.js dispatches pywebviewready, then loaded is set). The timing was **not** observed live because launching the app is out of bounds for this audit.
- **Recommended fix.** A readiness handshake: the frontend calls ui_ready() and the backend emits the restore events **after** it (or the frontend pulls get_state() on boot). Buffering the early events in JS is the weaker alternative.
- **Fix side effects.** Buffering needs a bounded queue so an uninstalled handler cannot grow it without limit. A readiness handshake adds one round-trip to startup; it must not delay first paint.
- **Discovered by:** WN-28-A, WX-12-A, WX-12-B.

---

### AUD-010 · P1 · CONFIRMED · Frontend security · js/player.js:1731, 1760, 1797 + js/queue.js:157 + js/events.js:74

**The loopback proxy's bearer token leaks into live DOM attributes and into the WebView console.**

- **Description.** The proxy auth token travels in the k= query parameter of the proxy URL. That URL is written into src attributes of live <img> elements (one per queue row and per player cover), and the full 	rack_changed payload — which contains stream_url including &k=<token> — is printed to the WebView console by the event logger.
- **Cause.** The token is carried in a URL because the <audio>/<img> elements cannot set headers; the console log is an unconditional debug statement.
- **Trigger conditions.** Every track change.
- **User impact.** The token alone unlocks the entire proxy (core/proxy.py:503-511), which serves local library files and forwards upstream requests. Any script that runs in the WebView — including content injected through a third-party cover URL, a lyrics body or an artist biography — can read the token from the DOM and then read or write through the proxy. The console log additionally persists the token into the DevTools buffer and into any bug report that includes a console capture.
- **Evidence.** js/player.js:1731,1760,1797 (setElSrc('pb-cover', coverUrl) where coverUrl carries &k=<token>), js/queue.js:157 (the same for a queue row), js/events.js:74 (console.log('Python Event:', eventName, data)), core/api.py:1240 → core/proxy.py:1313/1331 (the payload carries the URL).
- **Reproduction / verification.** The presence of the token in the DOM and in the console was confirmed by WN-29-B; the token's authority is confirmed by reading core/proxy.py:503-511 (constant-time compare, fail-closed).
- **Recommended fix.** Move the token out of the query string: issue it as a SameSite=Strict cookie scoped to the loopback origin, or serve the media through a lob: URL built from a one-shot fetch. At minimum, gate console.log behind the NEDOTIFY_DEVTOOLS flag and stop putting the token in img src attributes (fetch the cover bytes and use a blob URL).
- **Fix side effects.** Cookie-based auth requires the proxy to parse cookies and to relax the CORS rules for credentialed requests — a coordinated change across core/proxy.py and the frontend. The blob approach costs one extra round-trip per cover and per stream, and breaks the <audio> element's range requests without an explicit etch + blob pipeline.
- **Discovered by:** WN-29-B.

---

### AUD-011 · P1 · CONFIRMED · Startup / shutdown · main.py:506-539 + core/api.py:446-459 + core/app.py:508-586

**Three divergent shutdown paths; the only place that stops the tray is skipped on the watchdog restart path and on every exception path.**

- **Description.** The app has three exits: (a) normal on_closed → pi.cleanup() → AppCore.cleanup(); (b) the watchdog branch → pp_core.cleanup() → os._exit(3) — **without** pi.cleanup(); (c) an exception anywhere in main() — which skips every cleanup step. AppApi.cleanup() (:446-459) is the only owner of the tray stop and the bridge executors.
- **Cause.** The shutdown contract is implicit and split across three owners, with no single idempotent owner. The teardown order is also **not** the reverse of the construction order (db.close precedes the pool shutdowns; pi.cleanup() runs after db.close()).
- **Trigger conditions.** A crash during startup (e.g. webview.start() raising when the .NET runtime is missing — pywebview does import clr at winforms.py:13), or the watchdog restart path.
- **User impact.** The tray icon is left behind (once AUD-003 is fixed, so this becomes live), the proxy server socket and the port stay bound, the settings writer thread and the shared executors stay alive, and the instance mutex is released **before** the teardown — so a restart can race the old process on the DB and the proxy port.
- **Evidence.** main.py:506-539 (the watchdog branch: Popen → flush → pp_core.cleanup() → flush → os._exit(3) — no pi.cleanup()); core/api.py:446-459 (AppApi.cleanup, the only tray stop); core/app.py:508-586 (AppCore.cleanup, per-step isolation, idempotent).
- **Reproduction / verification.** Read directly from the three files; WN-01-B, WN-02-B, WX-07-A and WX-07-B independently reached the same conclusion and built the exit-path matrix.
- **Recommended fix.** Introduce one authoritative, idempotent shutdown() that runs a fixed, ordered teardown list (proxy → downloader → settings writer → watchdog → tray → Discord → zapret → executors → **DB last**) and call it from **all** exits, including the watchdog branch and a 	ry/finally around webview.start(). Release the instance mutex **last**. Stop and join the settings writer thread (core/settings.py:520-530 has no stop flag).
- **Fix side effects.** Ordering matters: the DB must close **after** the downloader drains and the settings writer flushes. core/app.py:559-560 currently closes the DB **before** the pools — that ordering must be inverted in the same change, or in-flight writes will hit a closed connection.
- **Discovered by:** WN-01-B, WN-02-A, WN-02-B, WX-07-A, WX-07-B, WX-12-A, WX-12-B.

---

### AUD-012 · P1 · CONFIRMED · Window management / DPI · core/api.py:629-648, 749-771, 826-859

**_get_scale_factor() always returns 1.0, and physical pixel coordinates are fed into pywebview's logical-pixel move() — the mini player lands off-screen on any scaled display.**

- **Description.** Two compounding defects:
  1. _get_scale_factor reads getattr(native, "_scale", None). pywebview's WinForms form exposes scale_factor (public) — **no _scale exists anywhere in the package**. The function therefore always returns 1.0 and the entire "logical pixel" layer is dead code.
  2. _native_window_geometry reads GetWindowRect (physical pixels) and passes them to pywebview's move(), which **multiplies by the scale factor** (winforms.py:512-538), while esize() does **not** scale (winforms.py:500-510). The position is scaled and the size is not.
- **Cause.** A private-attribute name was assumed for the DPI scale, and two different coordinate spaces are mixed at the move() boundary.
- **Trigger conditions.** Any display that is not at 100 % scaling (125 %, 150 %, 175 %) — i.e. most laptops.
- **User impact.** The mini player is positioned at 1.5× its intended offset and can land **outside the visible screen** — the button becomes unreachable. Toggling mini on/off restores the main window at 1.5× its previous offset. The _saved_pos_coords "logical workarea" logic is inert, so the window can also be restored off-screen.
- **Evidence.** core/api.py:629-648 (getattr(native, "_scale", None)), core/api.py:749-771 (GetWindowRect → physical), core/api.py:848 (	arget_win.move(int(gx), int(gy))).
- **Reproduction / verification.** WN-04-B executed the scale probe: 
ative.scale_factor = 1.5 → _get_scale_factor() == 1.0. The move-scales / esize-does-not asymmetry was read from the installed pywebview source. The DPI behaviour itself was not exercised on this host (96 DPI / 100 %).
- **Recommended fix.** Read 
ative.scale_factor (the public attribute) and define **one** coordinate space: compute everything in physical Win32 pixels and convert exactly once at the move() boundary (or pass a logical value to move() and a physical one to esize(), consistently). Add a scale_factor parameter to the geometry helpers so they are testable without a GUI.
- **Fix side effects.** Changing the coordinate space moves every window position the app has ever computed; the saved mini-position preference (_saved_mini_pos) is stored in the old space and must be migrated or discarded.
- **Discovered by:** WN-04-A, WN-04-B, WX-12-A (cross-confirmed).

---

### AUD-013 · P1 · CONFIRMED · Packaging / plugins · core/plugins.py:26-29 + setup_pyinstaller.spec:27-30, 90-111

**The plugin folder resolves inside the PyInstaller onefile temp directory, so user plugins are never loaded in the shipped app.**

- **Description.** PluginManager computes plugins_dir as the plugins folder next to core/plugins.py. A PyInstaller **onefile** build extracts the bundle into %TEMP%\_MEIxxxxxx, so the resolved path is <temp>\plugins — not the install directory. There is no plugins entry in the spec's datas and no sys._MEIPASS branch.
- **Cause.** The path is derived from __file__ without the frozen-source branch that contract #9 requires of every other asset lookup (core/tray.py:38, core/proxy.py:158 and services/zapret_service.py:326 all do it correctly).
- **Trigger conditions.** The packaged application (the source tree works, which is why tests never caught it).
- **User impact.** The documented plugin capability does not exist in the product the user installs. The plugin feature is advertised in the UI and simply never fires.
- **Evidence.** core/plugins.py:26-29; setup_pyinstaller.spec:27-30 (extra_datas = [('ui/web_new_v2',…), ('ui/MACos_ui',…)] + the CWD-relative zapret/in entries — no plugins); the spec builds a onefile EXE (setup_pyinstaller.spec:90-111).
- **Reproduction / verification.** Derived from the spec plus _MEIPASS semantics (a onefile bundle extracts to a temp dir). A frozen build was not produced — iscc is not installed on this host and building would write into the repo.
- **Recommended fix.** Resolve the plugin directory from a frozen-aware location: sys.executable's directory in a frozen build, the repo root otherwise; and add the plugins folder to datas (or ship an empty folder). Add a build test that asserts the resolved path exists next to the exe.
- **Fix side effects.** None. This restores documented behaviour; it also means plugins become loadable in the shipped app, so the loader's isolation (contract #10) must be re-verified before shipping.
- **Discovered by:** WN-02-A, WN-02-B.

---

### AUD-014 · P1 · CONFIRMED · Security / SSRF · core/api.py:3583-3593 + services/soundcloud_service.py:1027-1035

**get_waveform fetches an arbitrary provider-supplied URL with no SSRF check.**

- **Description.** The waveform URL comes verbatim from the SoundCloud API → the track dict → the DB → JS → the bridge → equests.get(url, timeout=10.0), and the JSON response is returned to the UI. The project's own _is_ssrf_safe_url guards open_url, the playlist importer and every proxy redirect hop — but not this sink. equests follows redirects by default, so a public host can 302 to a LAN or metadata address.
- **Cause.** The waveform feature was added without reusing the project's existing SSRF gate.
- **Trigger conditions.** Any track whose waveform URL is fetched (SoundCloud tracks; the frontend calls it on every track change).
- **User impact.** The app performs an arbitrary outbound GET on behalf of data a third party controls, from the user's machine and IP, with no allow-list — and returns the body to the UI. Combined with AUD-004 (the guard fails open) and AUD-005 (no IP pinning), the SSRF surface is materially larger than the rest of the app's design assumes.
- **Evidence.** core/api.py:3583-3593 (equests.get(url, timeout=10.0)); services/soundcloud_service.py:1023-1035 (the URL source); js/player.js:2271-2274 (the call site).
- **Reproduction / verification.** WN-09-B probed it: the URL handed to the HTTP client was http://192.168.1.1/status.json with no scheme/host/loopback check. WN-09-A independently confirmed http://127.0.0.1:9/x.json was fetched.
- **Recommended fix.** Apply _is_ssrf_safe_url to the waveform URL before the fetch, and restrict the fetch to the known SoundCloud CDN host set. Better: resolve the waveform through the same proxy path as the audio stream, so the token, the CORS rules and the SSRF gate all apply.
- **Fix side effects.** If SoundCloud serves waveforms from a rotating CDN set, a host allow-list needs to be maintained and will need updating when the CDN changes.
- **Discovered by:** WN-09-A, WN-09-B, WN-20-B.

---

### AUD-015 · P1 · CONFIRMED · Quality gate · ui/web_new_v2/js/player.js:2244, 2358 + 	ests/test_flow_ui.py, 	ests/test_player_recovery_transitions.py

**The project's own test suite is red on the current working tree: 11 failures, one root cause.**

- **Description.** player.js:2244 and player.js:2358 read document.documentElement.dataset.progressStyle **without** optional chaining, while player.js:2513 in the same file uses dataset?.uiStyle. The Node-based test harness stubs documentElement without a dataset, so the unguarded dereference aborts the module evaluation and every assertion after it never runs.
- **Cause.** Inconsistent defensive style within one file, on a DOM access the harness does not model. Five private hand-written fake DOMs exist instead of one shared stub.
- **Trigger conditions.** The current working tree (three of the affected test files are untracked — ?? in git — and player.js carries +1 276 lines of uncommitted change).
- **User impact.** The project's quality gate is red. The three failing files cover the Flow autoplay coalescing, the crossfade/gapless transitions and the queue-end advance — i.e. **exactly the areas the audit found to be contract-fragile** — so the regressions they were written to catch are currently unguarded.
- **Evidence.** player.js:2244 / :2358 (unguarded) vs :2513 (guarded); the harness stub documentElement: { classList, getAttribute: () => null, style: { setProperty() {} } } (no dataset).
- **Reproduction / verification** (executed by the coordinator):
  `
  11 failed, 1491 passed, 1 skipped, 3 xfailed in 106.53s (0:01:46)
  TypeError: Cannot read properties of undefined (reading 'progressStyle')
      at fetchAndRenderWaveform (evalmachine.<anonymous>:2244:52)
      at Object.onTrackChanged (evalmachine.<anonymous>:1734:5)
  `
  WN-34-A reproduced it on 4 separate runs and proved the mechanism with a Node probe: the stub as shipped → c=1; the stub plus dataset:{} → c=0. The full failure list and per-test causes are in §9.2.
- **Recommended fix.** Use document.documentElement.dataset?.progressStyle at both sites, and add dataset: {} to the Node DOM stub so the harness models the real DOM. Restore the suite to green **before** any other change lands.
- **Fix side effects.** None functionally. It is a two-character-class change in two places.
- **Discovered by:** coordinator (Stage 6 automated verification), cross-referenced with WN-28-A, WN-29-A, WN-32-A, WN-34-A, WN-34-B.

---

### AUD-016 · P1 · CONFIRMED · Security / update path · services/zapret_service.py:44-51, 977, 997-1010

**The "update Zapret" path installs an elevated binary without ever verifying its SHA-256.**

- **Description.** _verify_zip_sha256(zip_bytes, expected_hash) returns True when expected_hash is empty. The caller computes expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else "" — but get_latest_release_info() returns the GitHub API's rowser_download_url, so for **every release newer than the pinned v72.13** the expected hash is empty and the verification is a no-op. The extracted binary is then executed with ShellExecuteW(..., "runas") — i.e. **elevated**.
- **Cause.** The hash constant is only valid for the pinned URL; the update path uses a URL that is not pinned.
- **Trigger conditions.** The user clicks "Update Zapret" and a newer release exists.
- **User impact.** A network MITM (or a compromised release asset) can deliver an arbitrary executable that the app then runs **as administrator**. The binary is stored under ~/.nedotify/zapret, a user-writable directory, so it is also replaceable between the check and the execution (a local privilege-escalation path).
- **Evidence.** services/zapret_service.py:44-51 (_verify_zip_sha256 returns True for an empty expectation), :977 (the expected_hash selection), :997-1010 (extract → verify → start), _launch_elevated → ShellExecuteW "runas".
- **Reproduction / verification.** WN-26-A reproduced: _verify_zip_sha256(b"garbage", "") → True. WN-26-B independently confirmed that the pinned hash **is** genuine and **is** checked on the pinned path — the defect is precisely that every *other* path skips it. WN-10-A and WN-10-B confirmed the reachability from the bridge (core/api.py:3867-3874).
- **Recommended fix.** Either pin the update URL to the hashed artifact, or fetch and pin the expected hash from a signed/verified channel (a signed release manifest), and refuse to install when no trusted digest is available. The PE check (is_valid_windows_binary) is necessary but not sufficient — a valid PE can still be malicious. Also move the binary out of the user-writable directory.
- **Fix side effects.** The updater can no longer install an unsigned new release; it will need a signed manifest, which means the release process must publish one.
- **Discovered by:** WN-26-A, WN-26-B, WN-10-A, WN-10-B.

---

### AUD-017 · P1 · CONFIRMED · Data integrity / settings · core/api.py:1853-1900 vs core/api.py:2922-2962

**Two settings APIs with inverted argument order coexist; the wrong one silently corrupts state.**

- **Description.** AppApi exposes both get_setting/set_setting (:1853-1900) and get_settings/save_setting (:2922-2962), plus a third path via core/settings.py::SettingsManager. set_setting(section, key, value) and save_setting(key, value, category="app") have **inverted argument order**.
- **Cause.** The playback-range settings accessors predate the settings-range ones; both are public bridge methods, so pywebview exposes both to the WebView.
- **Trigger conditions.** Any caller of set_setting — the frontend today calls save_setting, so this is currently latent, but the method is public and reachable.
- **User impact (verified by probe).**
  - set_setting('auth','yandex_token',None) writes to the category **zapret**, key yandex_token — the token is not cleared and a bogus setting is created.
  - set_setting **never calls update_autostart()**, so setting autostart through it stores "on" while the Windows Run key is never written — the setting lies to the user.
  - The autostart trigger in save_setting matches key == "autostart" in **any** category.
- **Evidence.** core/api.py:1853-1900 and core/api.py:2940-2953 (the two implementations, side by side).
- **Reproduction / verification.** WN-05-B probed it: settings written: [('zapret','audio','volume')], update_autostart called via set_setting: []. WN-05-A, WN-08-A, WN-14-A and WX-03-A independently confirmed the divergent semantics; WX-03-A also confirmed set_setting/get_setting have **no JS callers** today.
- **Recommended fix.** Delete the get_setting/set_setting pair from the playback range and route every caller through save_setting/get_settings. Add a bridge-surface test that asserts the published js_api method set contains exactly one settings entry point.
- **Fix side effects.** Any frontend code still calling set_setting will break loudly (the method disappears) rather than silently — which is the point. A bridge-surface snapshot test prevents a re-introduction.
- **Discovered by:** WN-05-A, WN-05-B, WN-08-A, WN-08-B, WN-14-A, WN-14-B, WX-03-A (cross-confirmed).

---

### AUD-018 · P1 · CONFIRMED · Persistence / data loss · core/database.py:863-869, 905-913

**The duplicate-merge loses play_count, the favourite flag and last_played when a partition has three or more rows.**

- **Description.** _merge_track_row_into computes params.append((survivor.get("play_count") or 0) + (duplicate.get("play_count") or 0)) — but survivor is a **plan-time** dict captured before the merge, so the second duplicate overwrites the first merge with absolute values.
- **Cause.** The merge accumulates into a snapshot instead of into a live row.
- **Trigger conditions.** A partition of three or more rows with the same recording identity — the two-row case (which the existing test covers) is correct.
- **User impact (reproduced by WN-12-A against a legacy-schema DB).** Three rows with play_count 3 / 5 / 7 and a favourite on the middle row merged to play_count = 10 (not 15), is_favorite = 0 (**the favourite flag was cleared**) and last_played **regressed** to the oldest stamp. The user silently loses plays and their favourite.
- **Evidence.** core/database.py:863-869, :905-913; the two-row test passes because the bug only manifests at three or more.
- **Reproduction / verification.** WN-12-A: 3 identical rows → [(1, 10, 0, '2026-03-03 12:00:00')], expected play_count=15, is_favorite=1.
- **Recommended fix.** Merge into a live row (read the survivor's current values inside the transaction) rather than into the plan snapshot, and add a 3-row regression test.
- **Fix side effects.** None — the merge runs inside one transaction with a snapshot, so a failure is recoverable.
- **Discovered by:** WN-12-A.

---

### AUD-019 · P1 · CONFIRMED · Performance / library · js/events.js:258-263 + js/library.js:379-391, 501-520, 548-550 + core/api.py:2271

**Every completed download rebuilds the entire library three times, each rebuild re-fetching the whole 	racks table with no LIMIT.**

- **Description.** On download_complete the frontend calls loadDownloaded() (an alias of efreshActiveLibraryView()), then efreshActiveLibraryView() directly, then dispatches 
edotify:track_downloaded, whose handler calls loadDownloaded() again — three full rebuilds. AppApi.get_library calls get_all_tracks() with **no LIMIT** and SELECT * (including metadata_json).
- **Cause.** Three independent refresh paths over the same state, and an unbounded collection on the bridge.
- **Trigger conditions.** Every download.
- **User impact (measured).** At 2 000 tracks the get_all_tracks bridge call is hit **30 times** (not 0) for 10 downloads — each one a full-table read and a multi-megabyte JSON serialisation across the WebView bridge, on the bridge thread. The library view visibly stalls and the app burns CPU during a batch download. A 200-track batch was measured at ≈35 s of CPU and 1.2 GB of JSON.
- **Evidence.** js/events.js:258-263 (the three calls), js/library.js:548-550 / :379-391 / :962-964 / :501-520, core/api.py:2271 (get_all_tracks(), limit=None).
- **Reproduction / verification.** WN-32-B measured it: with 2 000 tracks, 10 downloads ⇒ 30 hits on core/api.py:2271. WX-02-B independently measured the per-call cost (1.21 MB per call) and the count.
- **Recommended fix.** Collapse the three paths into one, gate it on the library view being visible (isPageVisible('library') — the pattern already exists at events.js:223), and add server-side pagination to get_library/get_all_tracks so the bridge never ships the whole table.
- **Fix side effects.** Pagination changes the bridge contract; the frontend's infinite-scroll loader (library.js:394-454) already expects batched delivery, so the change is compatible. get_library is also used by core/offline.py:77 and core/api.py:3423 — both must move to the paged form.
- **Discovered by:** WN-32-B, WX-02-B.

---

### AUD-020 · P1 · CONFIRMED · Test suite / isolation · 	ests/conftest.py:115-129, 170-176

**The test suite writes into the user's real ~/.nedotify/downloads/.**

- **Description.** The edirect_home fixture is **opt-in** and is not requested by the downloader/api/core fixtures; core/downloader.py:789 and core/api.py:2700 resolve ~ at call time. The suite therefore creates files in the user's actual library.
- **Cause.** Isolation is a fixture a test must remember to request, rather than a session-wide sandbox.
- **Trigger conditions.** Any test that exercises the downloader or the auto-save-favourite path.
- **User impact.** Test artefacts accumulate in the user's music library. WN-34-A confirmed the physical evidence on disk: C:\Users\<user>\.nedotify\downloads\stub_1.mp3 (8 207 bytes, byte-exact against 	ests/conftest.py:58-61) and gated_3..12.mp3 (16 bytes, from 	ests/test_downloader_cancel.py:45-49). The behaviour is race-dependent, so it does not reproduce on every run.
- **Evidence.** 	ests/conftest.py:170-176 (not autouse; no shared fixture requests it); core/api.py:2700; core/downloader.py:789-790; 	ests/test_auto_save_favorites.py:87-96 (reads the real downloads directory).
- **Reproduction / verification.** WN-34-A listed the user's real ~/.nedotify/downloads/ (read-only) and matched the byte content against the fixture payload; it also re-runs the suite with USERPROFILE redirected and an os.path.getsize shim and observes the test still reach the real path. WN-34-B reached the same conclusion via the core/api.py:2700 path.
- **Recommended fix.** Make the sandbox an **autouse session fixture** that redirects HOME/USERPROFILE before any module resolves ~, and add a guard that fails the run if any write escapes the sandbox. Remove the existing artefacts once.
- **Fix side effects.** A test that relied on the real profile would now fail — that is the intent, but check 	ests/test_auto_save_favorites.py:87-96 first.
- **Discovered by:** WN-34-A, WN-34-B.

---


### 4.1 Additional P1 findings raised by the integration reviewers

These were surfaced by the cross-module (WX-01…WX-12) reviewers after the area reviews, and were cross-confirmed against the source by the coordinator. Full dossiers live in the reviewer reports; the evidence and the fix are given here.

#### AUD-515 · P1 · CONFIRMED · Playback concurrency · core/api.py:1714-1737

**A stale resolution wins: the first track to resolve is played, not the last one requested.**

- **Description.** _resolve_track infers staleness from the **identity** of the queue's current track: elif self._core.engine.queue.current_track is cur_start: play_callback(track). There is no request token or generation counter. Two rapid play_track calls share one snapshot; whichever resolution completes first is delivered and the other is silently discarded. With an empty queue cur_start is None, so None is None is True and the guard always passes.
- **Trigger conditions.** The user clicks play on two tracks in quick succession (or the frontend re-enters play_track — which it does whenever it sees no stream_url, so **one click starts two resolution chains**).
- **User impact.** The wrong track plays. In the queue path the frontend's playbackGeneration guard discards the stale *stream*, but the **decision is made in Python**, so the guard cannot help. Reproduced: click A, then C, with A resolving first ⇒ **A plays** although C was the last request; only one 	rack_changed event is ever emitted, so the UI shows A and the user believes C is playing.
- **Evidence.** core/api.py:1714 (the cur_start snapshot), :1734-1737 (the identity guard); core/api.py:1606 (the solo path, which never puts the new track in the queue); js/player.js:1695-1705 (the frontend's re-entry).
- **Fix:** a monotonic playback epoch captured with the request; a resolution callback may only update the current entry, never re-select. Pair with the "one resolution chain per click" fix in the frontend.
- **Fix side effects:** the epoch must not break the proxy's 403/410 self-heal, which resolves through a different path and must still be able to replace a dead URL.
- **Discovered by:** WX-01-A, WX-01-B, WX-10-A, WX-10-B, WN-05-A, WN-05-B.

#### AUD-516 · P1 · CONFIRMED · Playback concurrency · core/api.py:1437-1606, 1761-1770 + udio/engine.py:27-63

**Transport commands are not serialised — there is no playback lock.**

- **Description.** pywebview runs **every** JS→Python call on its own thread (webview/util.py:308). _window_op_lock guards the window geometry and the listening telemetry, **not** the queue. AudioEngine has no lock at all. engine.py:55-63 reads the queue **twice** — 	rack = self.queue.next_track() then _notify_track_changed() re-reads queue.current_track — so a second thread can advance the queue between the two reads.
- **Trigger conditions.** The user presses Next while the auto-advance from ended fires, or clicks Next twice within a frame.
- **User impact (reproduced).** The queue advances **two** steps while only one is announced: the bridge's return value and the emitted 	rack_changed name **different tracks**, and one track is skipped silently. The frontend applies the last event unconditionally (js/player.js:1625), so the UI and the backend can disagree about what is playing.
- **Evidence.** udio/engine.py:55-63 + :78-80 (the two reads); core/api.py:353 (_window_op_lock covers window ops + telemetry, never the queue); webview/util.py:308 (one thread per bridge call); core/api.py:1122-1159 (_emit → evaluate_js, no cross-thread ordering).
- **Fix:** one playback command lock around mutate → notify → emit, plus a single atomic queue.snapshot() so the index and the track are read together. The lock must **not** be held across a UI-thread evaluate_js.
- **Fix side effects:** the lock must not deadlock against StreamResolver's lock; the resolver never calls out while holding its own, so the order resolver → playback is safe.
- **Discovered by:** WX-10-A, WX-10-B, WN-17-A, WN-17-B.

#### AUD-517 · P1 · CONFIRMED · Playback / error visibility · core/api.py:1608-1744

**A failed resolution in the solo play path produces no user-visible error at all.**

- **Description.** _is_current() compares against engine.queue.current_track, which in the solo path still holds the **previous** track (the new one enters the queue only on success) ⇒ _on_audio_error never fires. play_track also returns None, so the frontend's esult?.success === false check never triggers.
- **Trigger conditions.** The user clicks a track that cannot be resolved (DRM, geo-blocked, removed).
- **User impact (reproduced).** The click is ignored — no sound, no spinner, no toast, and the previous track keeps playing. The user has no way to tell that anything happened.
- **Evidence.** core/api.py:1608-1744 (the guards at :1623-1629, :1716-1721, :1739-1742), core/api.py:381-382 (_on_audio_error), js/search-discovery.js:43, js/home.js:784, js/feature-controls.js:69 (the solo call sites).
- **Fix:** report the failure on the solo path too — the resolution should raise into the bridge's error envelope, and the frontend should surface it.
- **Fix side effects:** none; the queue path already reports correctly.
- **Discovered by:** WX-01-A, WX-10-A.

#### AUD-518 · P1 · CONFIRMED · Download / performance · core/proxy.py:1174-1222 + core/app.py:361-374 + utils/cache_manager.py:293-317

**Every played track is downloaded twice — the proxy's inline cache and the auto-cache write the same file concurrently.**

- **Description.** The proxy streams the body to the browser **and** to a temp file, then os.replaces it into ~/.nedotify/streams/ and writes a DB row. Independently, core/app.py:361-374 schedules cache.download_audio_stream five seconds later with uto_cache_streams: True (on by default), which performs its **own** yt-dlp download to the **same** base name {source}_{safe_id}. The downloader's "already cached?" guard reads cached_file_path, which the proxy sets only **after** the whole body arrives — so at t+5 s the guard misses.
- **Trigger conditions.** Every cloud track played.
- **User impact.** 2× the bandwidth and CPU per play; a Windows file-lock race makes os.replace fail ("Could not replace stream file … locked"), so the cache is silently lost and the next play re-downloads; an extension mismatch can leave two files per track, one of them orphaned but still charged against the quota.
- **Evidence.** core/proxy.py:1174-1222 (stream + write + replace + set_cached_file); core/app.py:361-374 (the 	hreading.Timer auto-cache); core/settings.py:147 (uto_cache_streams: True); utils/cache_manager.py:293-317, :379 (the same base name, its own download).
- **Fix:** one owner for the stream cache (§8.1, A-3) — the proxy should either cache or stream, not both, and the auto-cache should consult the proxy's record before downloading.
- **Fix side effects:** disabling the auto-cache removes the "download for offline" convenience; the proxy's cache already covers most of it.
- **Discovered by:** WX-01-B.

#### AUD-519 · P1 · CONFIRMED · Shutdown · core/app.py:562-586 + core/downloader.py:893-907

**cleanup() cannot release the process: shutdown(wait=False) does not stop the interpreter joining the pool workers.**

- **Description.** The teardown uses ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True), which cancels *queued* work but does not stop a **running** one. CPython's concurrent.futures.thread._python_exit (registered via 	hreading._register_atexit) joins the worker threads **before** the texit callbacks run, so the process waits for them regardless.
- **Trigger conditions.** An in-flight yt-dlp cache download (uto_cache_streams is on by default), a download, or a prefetch.
- **User impact (measured).** A 4-second worker delayed the process exit by **4.29 s**; a 5-second task delayed it by 5.14 s; the LUFS decode measured 4.62 s for a 15-minute file. The user sees the app "hang" on exit for seconds to minutes, and the window disappears before the process is gone.
- **Evidence.** core/app.py:562-586 (the shutdown(wait=False) calls); core/downloader.py:893-907 (the same pattern); services/lyrics_service.py:192-195 (shutdown_executor has **no caller** at all — the lyrics pool is never stopped).
- **Fix:** cooperative cancellation plus a bounded join, and a hard exit after the final flush; add the lyrics pool to the teardown list.
- **Fix side effects:** a task that cannot be cancelled still blocks; the bound must be generous enough not to truncate a real download.
- **Discovered by:** WX-07-A, WX-07-B, WN-02-B, WN-22-B.

#### AUD-520 · P1 · CONFIRMED · Lyrics correctness · services/lyrics_lookup.py:44-49, 61-62

**With no artist metadata, the duration is never used to reject a match — the lyrics of a different song are shown as the current track's.**

- **Description.** When expected['artists'] is empty (an empty **or** a placeholder artist — services/music_matching.py:38-46 strips "unknown artist"), the artist check is skipped entirely, and the duration check exists **only inside** synced_ok. A plain (unsynced) hit from a different artist and a different length is therefore accepted.
- **Trigger conditions.** A track whose artist is missing or unparseable — common for local files and for provider rows with a bare title.
- **User impact (reproduced).** A track titled "Yesterday" with no artist and a duration of 265 s was matched to "Yesterday" by **Gotye** at 190 s. The wrong words are displayed as the current song's, unmarked and uncorrected.
- **Evidence.** services/lyrics_lookup.py:44-49 (the artist check is skipped), :61-62 (the duration check exists only in synced_ok).
- **Fix:** apply the duration tolerance to plain hits as well, and reject a candidate whose duration differs by more than a tolerance (when the expected duration is known).
- **Fix side effects:** a track whose provider duration is wrong would be rejected rather than mismatched — prefer a miss over a wrong lyric.
- **Discovered by:** WX-06-A, WX-06-B.

#### AUD-521 · P1 · CONFIRMED · Settings durability · core/settings.py:443-483, 520-530

**A failed settings write is never retried — the writer thread does not re-arm after a failure.**

- **Description.** lush() restores the failed keys into _dirty but never re-arms _writer_wake; _writer_loop blocks in wait() afterwards. The retry happens only on the next set(), on texit, or during cleanup().
- **Trigger conditions.** A transient write failure (the DB is locked, the disk is momentarily busy).
- **User impact (reproduced).** The bridge already answered True — the user is told the setting was saved — and the value is **not** on disk. Measured: a failing DB produced **1** attempt in 3 s; the DB recovered for a full second and the attempt count stayed at **1**.
- **Evidence.** core/settings.py:472-483 (the re-queue), :520-530 (_writer_loop = wait → clear → sleep → flush).
- **Fix:** re-arm the wake event in the failure branch, with a bounded attempt budget and a back-off; surface a failed flush to the bridge.
- **Fix side effects:** a permanently failing DB would retry forever — hence the attempt budget.
- **Discovered by:** WN-14-A, WN-14-B, WX-03-A.

#### AUD-522 · P1 · CONFIRMED · Settings projection · core/api.py:2929

**The 
etwork category is never returned — offline mode is invisible to the UI after a restart, and the frontend keeps making network requests it believes are offline.**

- **Description.** get_settings() hard-codes a 22-name category list that omits 
etwork (and subscription) and includes four names that are not in DEFAULT_SETTINGS at all — the list has already drifted. js/feature-controls.js:112 evaluates window.settings?.network?.offline_mode === true → always alse → pplyOfflineState({enabled:false}). get_offline_mode() exists but has **zero** UI callers.
- **Trigger conditions.** Every restart with offline mode persisted ON.
- **User impact.** (a) The UI shows no offline state — no class, no note (index.html:461). (b) js/utils.js:607-613 returns remote cover URLs unchanged, so the WebView loads artwork from YouTube/Yandex/SoundCloud CDNs — a **frontend-side leak** that bypasses every Python gate. (c) js/player.js:1440/1524 (prefetch, Flow) proceed as if online.
- **Evidence.** core/api.py:2929 (the list); core/settings.py:52-55 (
etwork.offline_mode is in the schema); js/feature-controls.js:112, js/utils.js:526, :608, js/player.js:1440, :1524.
- **Reproduction / verification.** Verified: MISSING from get_settings(): ['network', 'subscription']; the frontend reads undefined.
- **Fix:** derive the category list from DEFAULT_SETTINGS (§8.1, A-1) and add a UI toggle plus a boot-time get_offline_mode() call.
- **Fix side effects:** none; the category is already in the schema.
- **Discovered by:** WN-08-A, WN-08-B, WN-14-A, WN-14-B, WX-03-A, WX-09-A, WX-09-B.

### 4.2 Findings promoted to P1 after cross-review

Fifteen findings were rated P2 by their area reviewer and were promoted after the integration reviewers independently rated them P1 (or after the coordinator's verification confirmed a user-visible blocker). They keep their full dossier in §5:

| ID | §5 area | Why promoted |
|---|---|---|
| AUD-169 | §5.2 | A paused batch never terminates ⇒ the progress bar hangs forever (WN-10-A, WN-13-A, WX-02-A) |
| AUD-170 | §5.2 | The retry fix never fires for the canonical transient error ⇒ the track fails forever (WN-13-A) |
| AUD-172 | §5.2 | stop() returns while a worker runs and the DB closes under it ⇒ the process cannot exit (WN-13-A, WN-13-B) |
| AUD-224 | §5.3 | yt-dlp writes the user's **entire browser cookie jar** to disk (WN-19-A, WN-19-B) |
| AUD-228 | §5.3 | One CDN refusal removes the track for an hour with a wrong message (WN-20-A, WN-20-B) |
| AUD-232 | §5.3 | One bad duration silently replaces an entire imported playlist (WN-24-A) |
| AUD-235 | §5.3 | "Earth, Wind & Fire" can never open their own albums; another artist's album is accepted instead (WN-24-A) |
| AUD-259 | §5.3 | The period-comparison query takes **467 s** at 120 k rows (WN-25-A, WN-25-B, WX-04-B) |
| AUD-286 | §5.3 | A provider-sourced track never enters the library; the file is an orphan (WX-02-A) — the same root cause as X-04 |
| AUD-290 | §5.3 | The "Spotify" provider is the iTunes API, mislabelled end to end (WX-05-A, WX-05-B) |
| AUD-301 | §5.3 | write_tags rewrites the user's only copy of a file in place (WN-27-A, WN-27-B, WN-07-B) |
| AUD-302 | §5.3 | Every OGG cover is broken (the FLAC picture block is returned instead of the image) (WN-27-A) |
| AUD-303 | §5.3 | write_tags fails on .wav/.aac/.wma, which the open dialog offers (WN-27-A) |
| AUD-381 | §5.4 | The "Плейлисты" filter fabricates playlist cards with a hard-coded "10 треков" (WX-05-A) |
| AUD-411 | §5.4 | A hotkey can never be re-bound to a modifier combination (WN-14-A) |`r`n| AUD-272 | §5.3 | The orphaned second scoring engine is a **different model** with hard-coded fake artists - a reader who trusts the file name is misled about what the app actually scores (WN-23-B) |

### P1 summary

The 20 P1s below are the primary ones (their full dossiers are in the block above). The **8 further P1s** raised by the integration reviewers are in §4.1 (`AUD-515`…`AUD-522`), and **16 further P1s** promoted after cross-review are listed in §4.2 — **47 P1s in total**.

| ID | Area | One-line |
|---|---|---|
| AUD-002 | Startup | The UI + bridge are served on a fixed port 42001 with wildcard CORS |
| AUD-003 | Tray | The tray never starts (two independent blockers) — ✕ quits the app |
| AUD-004 | SSRF | The guard fails open on DNS failure and caches "safe" for 120 s |
| AUD-005 | SSRF | The validated IP is discarded — DNS rebinding defeats the guard |
| AUD-006 | Settings | The volume is never restored; the repeat button is always lit |
| AUD-007 | Offline | Lyrics, translation, waveform and the CDN path still reach the network |
| AUD-008 | Data | clear_storage("all") deletes media outside ~/.nedotify |
| AUD-009 | Frontend | The session-restore events are dropped on every cold start |
| AUD-010 | Security | The proxy bearer token leaks into the DOM and the console |
| AUD-011 | Shutdown | Three exit paths; the tray stop is skipped on two of them |
| AUD-012 | DPI | The mini player lands off-screen on any scaled display |
| AUD-013 | Packaging | User plugins never load in the packaged app |
| AUD-014 | SSRF | get_waveform fetches an arbitrary provider URL with no guard |
| AUD-015 | Quality | The test suite is red — 11 failures, one root cause |
| AUD-016 | Security | The elevated updater installs an unverified binary |
| AUD-017 | Settings | Two settings APIs with inverted argument order |
| AUD-018 | Persistence | The duplicate-merge loses plays and the favourite flag |
| AUD-019 | Performance | Every download rebuilds the whole library three times |
| AUD-020 | Tests | The suite writes into the user's real ~/.nedotify/downloads/ |

---

## 5. Other Findings (P2 and P3)

These are real, confirmed defects with a user-visible or measurable consequence, but they do not break a core function outright. Each entry gives the location, the defect and the remediation direction; the full 12-field dossier for every finding lives in the corresponding reviewer report under `docs/audits/agents/<ID>-<A|B>.md` (94 files, ~4.5 MB, preserved in the repository alongside 57 reviewer scratch repro scripts).

Format: **ID** · *priority* · path:line — defect — **fix**.

### 5.1 Bridge, window management and lifecycle (WN-01, WN-02, WN-03, WN-04, WN-16)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-101 | P2 | core/api.py:617-627 | Every WM_SIZE spawns a Python thread and posts an unbounded UI-thread queue — the resize path is unthrottled. | Use the size pywebview already passes; debounce the layout. |
| AUD-102 | P2 | core/api.py:749-771 | GetWindowRect (physical) is fed into pywebview's logical move(); the position is scaled twice. | Convert once, at the move() boundary. |
| AUD-103 | P2 | core/api.py:749-771, core/api.py:1053-1095 | _change_maximized_state restores a stale _last_geometry; a native maximise (Win+Up) is never recorded. | Refresh the geometry on every resize. |
| AUD-104 | P2 | core/api.py:773-790, :805-816 | Mini-player enter/exit ops are unordered — a fast toggle can invert; native exceptions are swallowed, so the frontend rollback is dead code. | Completion events for deferred ops. |
| AUD-105 | P2 | core/api.py:992-1030 | egin_window_resize reports success without checking that the WS_THICKFRAME subclass is installed — the resize silently no-ops. | Verify the style bit first. |
| AUD-106 | P2 | core/api.py:542-572, js/main.js:455-492 | The Snap Layouts install poll gives up after 5 s and the maximise-button rect is never replayed — no Win11 flyout. | Replay the rect when the handle appears. |
| AUD-107 | P2 | core/api.py:1118-1120 | emit_event is a public, unvalidated bridge method — any script in the WebView can spoof download_complete/	rack_changed. | Curate the published bridge surface. |
| AUD-108 | P2 | core/api.py:1032-1051 | The HWND is resolved by window caption (FindWindowW(None,"NeDotify")) and never validated — a foreign window can be subclassed. | Resolve and cache the real HWND. |
| AUD-109 | P2 | core/api.py:446-459, core/api.py:1147-1159 | cleanup() does not quiesce the emit path: evaluate_js is still called on a destroyed WebView2 after cleanup (verified). | Set a closed flag and clear the window reference. |
| AUD-110 | P2 | core/api.py:1147-1154 | The UI-thread _emit branch spawns **one OS thread per event** — 200 emits produced 200 threads, with no ordering guarantee (two emits arrived as [2, 1]). | One long-lived worker + a bounded FIFO queue. |
| AUD-111 | P2 | core/api.py:940-944 | AppApi.shutdown() has no caller — the Snap subclass is never uninstalled and deferred ops can outlive the window. | Call it from cleanup(). |
| AUD-112 | P2 | core/api.py:272-330, core/api.py:4031-4078 | _normalize_cache_quota reinterprets any bare value > 64 as MB, so a 100 GB request becomes 1 GB; **kwargs swallows typos silently. | Send cache_quota_gb= explicitly; drop the heuristic. |
| AUD-113 | P2 | core/api.py:3036-3039, core/api.py:3091 | The 30 s _storage_info_cache is never invalidated by clear_storage_cache/set_cache_quota. | Invalidate on every mutation. |
| AUD-114 | P2 | core/api.py:3084-3090 vs core/api.py:4021-4029 | Two different "storage total" definitions feed the same three UI labels; the meaning changes after every clear. | One owner for storage metrics. |
| AUD-115 | P2 | core/api.py:2947-2951 | save_setting writes the setting *before* the registry update and ignores update_autostart()'s result. | Check the side effect and report failure. |
| AUD-116 | P2 | core/api.py:3180-3190 | set_equalizer validates nothing; if bands: means an empty list never clears the stored bands, and get_equalizer cannot distinguish "unset" from "flat". | Validate length/type/range; support an explicit clear. |
| AUD-117 | P2 | core/api.py:401-422 | The error wrapper erases every method's introspected signature (published to JS as zero-arg); the 5 unwrapped methods keep theirs. | Set __signature__. |
| AUD-118 | P2 | core/api.py:428-441 | Raw str(exc) reaches both the on-screen toast and ~/.nedotify/logs/app.log — the log users attach to bug reports. | Redact before logging and emitting. |
| AUD-119 | P2 | core/api.py:239-253 | _mask_secrets masks 2 of the credential-bearing uth settings; uth.proxy_url (may embed user:pass@) is returned verbatim. | Move masking into the schema. |
| AUD-120 | P2 | core/api.py:267-269 | _is_empty_secret_write swallows **every** falsy write to a secret key — a credential can never be cleared. | Only "" means "unchanged"; add an explicit clear. |
| AUD-121 | P2 | core/api.py:198-220 | _extract_first_url truncates URLs ending in ) and mangles text starting with http://. | Use a smarter URL extractor. |
| AUD-122 | P2 | core/api.py:223-230, :327 | _as_float accepts NaN/inf — a NaN quota becomes "no limit"; inf raises OverflowError inside int(round(...)). | math.isfinite check. |
| AUD-123 | P2 | core/app.py:555-586 | cleanup() closes the DB **before** stopping the pools; a late write hits a closed connection. | Invert the order. |
| AUD-124 | P2 | core/app.py:47-88, :150-151 | The yt-dlp updater thread is untracked and never joined; it can run pip install -U yt-dlp for 120 s, outliving the app. | Own the subprocess; cancel on exit. |
| AUD-125 | P2 | core/app.py:296-506 | The primary resolution path has **no completion deadline** — a provider that never calls back leaves the UI waiting forever. | A watchdog on the callback pair. |
| AUD-126 | P2 | core/app.py:379-497 | hasattr(self, "soundcloud") sits **outside** the 	ry: in _on_err — a raising lazy property escapes and on_error is never called. | Move the check inside the guard. |
| AUD-127 | P2 | core/session.py:50-55 | save_session clamps the shifted index with max(0, queue_index - dropped), so a current track inside the dropped head resumes the **wrong** track. | Carry the track id, not just an index. |
| AUD-128 | P2 | core/listening.py:22-30 | 	ick() clamps **every** interval to 15 s, so any heartbeat gap > 15 s is discarded — listening time is under-reported. | Use a larger, anomaly-based clamp. |
| AUD-129 | P2 | core/tray.py:158-161 | The native menu is rebuilt from a foreign thread while pystray owns the Win32 HMENU (use-after-destroy). | Queue the hand-off to the tray thread. |
| AUD-130 | P2 | core/tray.py:187-194 | TrayIcon.stop() cannot stop an icon that is not yet "ready" in pystray — a leftover icon at exit. | Track readiness. |
| AUD-131 | P2 | core/tray.py:147-156 | The 1 Hz throttle **drops** the play/pause state instead of deferring it — the tray label stays stale. | Defer, don't drop. |
| AUD-132 | P2 | core/user_errors.py:21-22 | describe_error echoes the raw exception text for ValueError/TypeError — an absolute path can reach the UI. | Sanitise the message branch. |
| AUD-133 | P2 | core/user_errors.py + ~30 bridge sites | The error mapping is advisory, not a boundary: raw str(e) still crosses into the WebView and the same failure is shown two ways. | One _error_payload boundary. |
| AUD-134 | P2 | core/plugins.py:26-29 | plugins_dir resolves inside the PyInstaller onefile temp dir ⇒ user plugins never load in the shipped app. | A frozen-aware path + ship the folder. |
| AUD-135 | P2 | core/plugins.py:99-107 | A plugin whose setup() raises stays in sys.modules and never gets 	eardown(). | Pop it on failure. |
| AUD-136 | P3 | core/api.py:572-597 | The unreachable eturn False also disables the native window-icon setter — the packaged app shows a default icon. | (Fixed with AUD-003.) |
| AUD-137 | P3 | core/api.py:983-986 | ctypes.windll.user32.SendMessageW's signature is mutated process-globally — the exact hazard the snap-layouts module documents. | Use ctypes.WINFUNCTYPE prototypes. |
| AUD-138 | P3 | core/api.py:346, main.py:348 | The bridge has no capability model; all 174 public methods are reachable from the WebView, and the CSP is the only barrier. | A curated façade. |
| AUD-139 | P3 | core/api.py:1853-1900 | The second get_setting/set_setting pair returns a dict (vs bool), routes bare keys to zapret, and never syncs autostart. | (Removed by AUD-017.) |
| AUD-140 | P3 | core/api.py:2779-2820 | complete_onboarding stores None for ccent_color/udio_device when the payload has an explicit null. | Normalise nulls. |
| AUD-141 | P3 | core/api.py:3024-3028 | save_personalization has no key/type/size validation; the alias map has no cap. | Validate and cap. |
| AUD-142 | P3 | core/api.py:2750-2754 | save_theme writes the dead key 	heme.current_theme (the live key is 	heme.theme); no caller. | Delete it. |
| AUD-143 | P3 | core/app.py:376-377 | The consumer callback is invoked with no exception guard — an exception kills the thread and the UI is never told. | Wrap the callback. |
| AUD-144 | P3 | core/app.py:159 | Plugins are loaded before AppApi exists, so core.api is undefined during setup(). | Load plugins after the bridge. |
| AUD-145 | P3 | core/app.py:372-374 | The auto-cache 	hreading.Timer is untracked, uncancelled and ungated by _shutting_down. | Own the timer. |
| AUD-146 | P3 | core/listening.py:28-29 | playback_rate is applied one interval late. | Apply it before the state update. |
| AUD-147 | P3 | core/session.py:82-87 | estore_session() mutates the live SettingsManager cache (a CDN URL ends up in the settings cache). | Copy before mutating. |
| AUD-148 | P3 | core/user_errors.py:9-22 | No sqlite3.Error/KeyError branch; keyword checks run before type checks ("Invalid connection id" is classified as 
etwork). | Reorder and extend. |
| AUD-149 | P3 | core/tray.py:119-120 | The tray favourite entry never reflects reality (is_favorite is absent from the queue's track dicts). | Read it from the DB. |
| AUD-150 | P3 | core/api.py:2803, core/api.py:4077 | The bridge writes schema-undeclared keys (	heme.custom_palette_enabled, storage.cache_quota_gb). | Declare them. |

---
### 5.2 Persistence, resolution, downloads and the proxy (WN-11, WN-12, WN-13, WN-15)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-151 | P2 | core/database.py:863-869, :905-913 | The duplicate-merge loses play_count/is_favorite/last_played when a partition has 3+ rows (the survivor's plan-time values overwrite the accumulated ones). | Merge into a live row, not a plan snapshot. |
| AUD-152 | P2 | core/database.py:1001-1005 | The corrective restore migration can never undo a merge — the query excludes exactly the rows the merge writes. | Fix the version predicate. |
| AUD-153 | P2 | core/database.py:1908-1924 | _cleanup_duplicate_empty_system_playlists silently deletes a **user** playlist named "Локальные" (no is_system column; matched by name). | Add an origin flag. |
| AUD-154 | P2 | core/database.py:1184-1209 + core/api.py:2267-2271 | get_library() ships the whole 	racks table (no LIMIT, SELECT * incl. metadata_json) on every render — 3 MB at 4 000 tracks. | Paginate and project. |
| AUD-155 | P2 | core/database.py:179-201 | _all_conns is a strong-reference registry — connections of dead threads are never evicted (one leaked handle per DB-touching thread). | Evict on thread exit. |
| AUD-156 | P2 | core/database.py:1599-1624 | get_history(50) full-scans 	racks **and** history; history grows unbounded with no pruning. | Index + retention. |
| AUD-157 | P2 | core/database.py:1723-1834 | get_wrapped_stats() = 4 independent full scans of history; profile.js calls it with 'all' on every profile render. | One aggregate query. |
| AUD-158 | P2 | core/database.py:1465 | search_playlists() is N+1 — one COUNT(*) per playlist (51 queries/search). | Join + group. |
| AUD-159 | P2 | core/database.py:1465-1482, :1626-1655 | No index for LOWER(album)/LOWER(artist)/missing-cover ⇒ full scans for album views and the cover backfill. | Add the indexes. |
| AUD-160 | P2 | core/database.py:2293-2302 | download_queue has no FK to 	racks; delete_track leaves a dangling queue row ⇒ an orphan file is written and mark_track_downloaded updates 0 rows. | Add the FK + cascade. |
| AUD-161 | P2 | core/database.py:2028-2034, :2084-2098 | The settings round trip changes the type of string values ("123"→123, "true"→True); None is stored as "" and reloads as "", permanently overriding the default. | Store typed values; distinguish NULL from "". |
| AUD-162 | P2 | core/database.py:219, :1278-1282 | 	racks.file_path UNIQUE ⇒ mark_track_downloaded raises IntegrityError; the downloader's fallback repeats it ⇒ the queue row sticks in downloading forever. | One write, retried, contained. |
| AUD-163 | P2 | core/database.py:2440-2489 | close() can block 30 s on the WAL TRUNCATE checkpoint (measured 32.3 s) ⇒ a frozen shutdown. | Bounded checkpoint. |
| AUD-164 | P2 | core/resolver.py:224 | The single-flight waiter is bounded at 12 s while the owner's cascade runs ~30 s ⇒ a concurrent caller gets None for a track that does resolve. | Waiter budget ≥ owner budget. |
| AUD-165 | P2 | core/resolver.py:209-222 | The owner has no watchdog: a hanging esolver_fn keeps _inflight[key] forever ⇒ every later resolve for that key waits 12 s and returns None. | Owner deadline + flight eviction. |
| AUD-166 | P2 | core/resolver.py:79-122 | The negative cache is **dead code** — mark_unavailable has no production caller, so a known-dead track is re-resolved through the full cascade every time. | Wire it, with a PERMANENT/TRANSIENT verdict. |
| AUD-167 | P2 | core/offline.py:62-73 vs :35-59 | vailable_tracks never consults the DB row while vailable_track does ⇒ the same track is "available" to one and "missing" to the other. | One helper. |
| AUD-168 | P2 | core/playback_recovery.py:177-183 | A cross-provider recovery is cached under the **original** (source, source_id) — the row labelled youtube holds a SoundCloud URL, and the proxy withholds the credentials it needs. | Cache under the recovered provider's key. |
| AUD-169 | P1 | core/downloader.py:108-112, :587-599 | Pausing a batch drops its task without accounting ⇒ atch_download_finished never fires and the progress bar hangs forever. | Always call _on_batch_task_done. |
| AUD-170 | P1 | core/downloader.py:612-627 + services/youtube_service.py:1129-1139 | The retry fix never fires for the canonical transient error — the provider masks the message before the classifier sees it. | Classify before masking. |
| AUD-171 | P2 | core/downloader.py:612-619 | The retryable classification is inverted: a 404 **is** retried (3×, 60 s) while a 500 is not. | Invert the table. |
| AUD-172 | P1 | core/downloader.py:893-907 | stop() returns while a worker still runs; the DB is closed under it; the process cannot exit (measured 4.29 s for a 4 s worker). | Join the worker before closing the DB. |
| AUD-173 | P2 | core/downloader.py:798-800 + core/api.py:3138-3154 | A cancelled download leaves a **complete orphan file** that is invisible to the library, never cleaned and never re-armed. | Remove the orphan on abort. |
| AUD-174 | P2 | core/downloader.py:356-410 | A non-integer 	rack_id is stored as TEXT; mark_track_downloaded then matches 0 rows and the queue row can never be re-queued. | Validate the id type. |
| AUD-175 | P2 | core/downloader.py:272-284 | cancel_batch() runs a bulk UPDATE **and then** one write transaction per row (201 statements for 200 rows), each taking the global write lock. | One transaction. |
| AUD-176 | P2 | core/download_transfer.py:100, :117-119 | download_http skips its completeness check when the server omits Content-Length ⇒ a truncated body is renamed onto the final .mp3 and reported as success. | Require a length or verify the stream. |
| AUD-177 | P2 | core/downloader.py:37-52 | _downloaded_file_defect only checks the extension and a 4 KiB floor ⇒ a truncated large file is marked complete. | Verify the container/duration. |
| AUD-178 | P2 | core/proxy.py:511 | hmac.compare_digest raises TypeError on a non-ASCII token ⇒ an unauthenticated request kills the connection with a traceback instead of a 403. | Compare bytes. |
| AUD-179 | P2 | core/proxy.py:863-968 | The '/' endpoint has no offline gate — the upstream is still fetched and the body truncated (verified: 1 upstream fetch, 0 bytes delivered). | Hoist the guard. |
| AUD-180 | P2 | core/proxy.py:201 | _resolve_inside_roots does not refuse UNC paths before the filesystem call ⇒ a ~21 s SMB block per request. | Share the existing guard. |
| AUD-181 | P2 | core/proxy.py:649-651 | do_HEAD answers 404 for resources GET serves (a ile:// URL, a DB-cached stream). | Unify the resolution ladder. |
| AUD-182 | P2 | core/proxy.py:406-408, :904 | Rewritten HLS segment URLs hit the is_webpage check and get *resolved* instead of fetched. | Distinguish the manifest from its segments. |
| AUD-183 | P2 | core/proxy.py:540-590 | serve_local_file announces a Content-Length from a different stat() than the bytes written ⇒ a truncated 200. | One stat, or a chunked response. |
| AUD-184 | P2 | core/proxy.py:421-446 | No socket timeout and no thread cap: an idle client pins a request thread forever (50 silent sockets → 50 threads). | Handler timeout + a semaphore. |
| AUD-185 | P2 | core/proxy.py:390-393 | A new urllib opener per request ⇒ ~4.8 ms SSL-context rebuild and no connection reuse (60–120 handshakes per HLS track). | A pooled opener. |
| AUD-186 | P2 | core/proxy.py:438-446, :1291-1294 | process_request replaces socketserver's _threads with a plain list ⇒ server_close() raises AttributeError on every shutdown. | Use the superclass bookkeeping. |
| AUD-187 | P2 | core/proxy.py:1174, :1204-1215 | A 206 upstream response is cached verbatim as a complete stream file (a 100-byte file of a 5 000-byte resource). | Check Content-Range. |
| AUD-188 | P2 | core/proxy.py:1162-1165 | Upstream headers are forwarded verbatim — Set-Cookie is planted on the app's own loopback origin. | Allow-list the forwarded headers. |
| AUD-189 | P3 | core/proxy.py:221-222 | _referenced_by_library's "case-insensitive" comparison is ASCII-only ⇒ an existing Cyrillic library track is refused with a 404. | Compare with casefold(). |
| AUD-190 | P3 | core/proxy.py:345-365 | _parse_byte_range answers 416 for an RFC-invalid range-set and accepts a +-signed position. | Follow RFC 7233 §2.1/§4. |
| AUD-191 | P3 | core/proxy.py:402-408 | One non-http(s) URI attribute aborts the whole HLS manifest with a 502. | Skip the attribute, keep the manifest. |
| AUD-192 | P3 | core/proxy.py:1002-1006 | The Yandex OAuth token is attached to plain-HTTP hosts (the host allow-list has no scheme check). | Require https. |
| AUD-193 | P3 | core/proxy.py:615-620 | do_OPTIONS is unauthenticated and the error paths omit the CORS headers ⇒ a cross-origin etch() sees opaque failures instead of status codes. | Gate OPTIONS; centralise the response emission. |
| AUD-194 | P3 | core/database.py:781-784 | 	racks_backup is a one-shot table that is never refreshed — bumping DUP_CLEANUP_VERSION would restore from a stale snapshot. | Refresh the snapshot per run. |
| AUD-195 | P3 | core/database.py:1392-1404 | The LIKE fallback uses a leading % (unindexable), and the FTS5 path bypasses _like_pattern's escaping entirely ('AC_DC' matches 'AC/DC'). | FTS-only with escaped terms, or an index. |
| AUD-196 | P3 | core/database.py:370-378, :477-495 | A bare except sqlite3.OperationalError: pass around ALTER TABLE swallows non-"duplicate column" errors ⇒ the column is never added. | Check the message. |
| AUD-197 | P3 | core/database.py:2347-2352 | download_queue_add cannot re-arm a paused row. | Extend the ON CONFLICT predicate. |
| AUD-198 | P3 | core/database.py:2474-2482 | close() cannot close other threads' connections, drops the handles anyway, and is not final — the next conn opens a new connection. | Track a closed flag. |
| AUD-199 | P3 | core/database.py:298-307 | A settings table without a category column makes DatabaseManager.__init__ raise ⇒ the app cannot boot (not reachable via this repo's history — a defensive gap). | Add the ALTER. |
| AUD-200 | P3 | core/database.py:595, :781-784 | A repeatedly failing migration leaves one full DB copy per start (VACUUM INTO with a dated name, no cleanup). | Guard the snapshot. |
| AUD-201 | P3 | core/resolver.py:152-160 | A DB hit is re-stamped with 
ow, so a URL lives up to 5 h (4 h read + 1 h memory). | Re-stamp only on a real refresh. |
| AUD-202 | P3 | core/resolver.py:263-267 | efresh() upserts the whole row via cache_stream, wiping title/artist/cover/duration. | Update only the URL columns. |
| AUD-203 | P3 | utils/stream_urls.py:18-23 | Expires is only accepted as a numeric epoch, so the HTTP-date form its own docstring names is ignored. | Parse both forms. |
| AUD-204 | P3 | core/playback_recovery.py:56-63 | _callback_result calls invoke() inline, so the timeout bounds only the wait *after* the call — a blocking provider defeats the whole 18 s budget. | Invoke on a worker. |
| AUD-205 | P3 | core/playback_recovery.py:87-92 | _invalidate holds the process-wide provider cache lock while copying the whole 2 000-entry cache, twice per recovery. | Copy under the lock, or version the cache. |
| AUD-206 | P3 | core/playback_recovery.py:30-36 | same_recording skips the duration guard when either side lacks one ⇒ a different take can be substituted and then cached under the original key. | Require a duration when one is expected. |
| AUD-207 | P3 | core/downloader.py:281-282 vs :818-838 | Cancel and the worker write the same queue row with no compare-and-set ⇒ is_downloaded=1 with status cancelled. | A single state-transition owner. |
| AUD-208 | P3 | core/downloader.py:171-183 | The downloader's _emit swallows every bridge failure at debug level — a dropped download_complete leaves the UI stale with nothing in the log. | Log at warning. |
| AUD-209 | P3 | core/downloader.py:700-709 | The retry backoff sleeps **inside** one of only two worker slots. | Sleep outside the slot. |
| AUD-210 | P3 | core/download_store.py:39-46 | ows() is a pure SELECT but runs inside the global write lock ⇒ the UI's download panel serialises behind every progress write. | Use a read connection. |

---
### 5.3 Providers, services and features (WN-18 – WN-27)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-211 | P2 | services/track_resolver.py:239-246 | The artist is compared as one raw string while provider artist fields are comma-joined ⇒ 'Adele' vs 'Adele, Someone' scores 0.5556 and is rejected, even though music_matching.artist_matches handles it correctly and is unused. | Use rtist_matches. |
| AUD-212 | P2 | services/music_matching.py:88-92 + 	rack_resolver.py:242 | Version markers are stripped from **both** sides ⇒ "Song (Live)" matches "Song (Remix)" at similarity 1.0, and the wrong file is resolved and downloaded. | Match on (base_title, version). |
| AUD-213 | P2 | services/track_resolver.py:241-246 | if title and … skips the title check entirely when the requested title is empty ⇒ any track by that artist matches. | Require a title. |
| AUD-214 | P2 | services/track_resolver.py:269-270, :311-312 | No budget on the local→SC→YT chain; the 10 s batch timeout hides the overrun and never cancels the futures ⇒ orphaned tasks occupy the pool. | One deadline, cancellable futures. |
| AUD-215 | P2 | services/track_resolver.py:249-252 | Lazy provider construction has no lock ⇒ 6 concurrent calls build **6** SoundCloudService instances (each with a 10-thread pool and a client-id scrape). | Double-checked locking. |
| AUD-216 | P2 | services/base_service.py:25-62 | The proxy is installed on 3 of 7 providers — not on iTunes, Last.fm, VK or Yandex, although the UI promises bypass for "YouTube and third-party services". | A transport layer in the base class. |
| AUD-217 | P2 | services/base_service.py:22, :55-56 | 
ormalize_proxy_url accepts socks5:// but PySocks is undeclared ⇒ equests raises InvalidSchema. | Declare the dependency or reject the scheme. |
| AUD-218 | P2 | services/base_service.py:140-161 | An abandoned provider flight keeps its single-flight key occupied forever ⇒ the query can never succeed again for the session. | A cancel handle + a TTL. |
| AUD-219 | P2 | services/base_service.py:125-134 | The 300-slot search cache is class-level and shared with the recommendation service ⇒ the home feed evicts the user's search results. | Per-subsystem caches. |
| AUD-220 | P2 | services/base_service.py:57-61 | A rejected uth.proxy_url is logged **with its credentials** (lice:hunter2@10.0.0.9:1080) into ~/.nedotify/logs/app.log. | Redact before logging. |
| AUD-221 | P2 | services/youtube_service.py:124-130 | _is_storyboards_only() cannot detect a real storyboard payload (the formats carry a url) — the gate message is dead in the streaming path. | Use yt-dlp's own rule. |
| AUD-222 | P2 | services/youtube_service.py:958-982 | The streaming path returns raw yt-dlp text; _yt_gating_error is applied only in the download path. | Map the error in both paths. |
| AUD-223 | P2 | services/youtube_service.py:832-859 | An automatic 7-browser cookie sweep runs on every bot-gate error, inside the shared 10-worker pool, unbounded. | One browser, one attempt, bounded. |
| AUD-224 | P1 | services/youtube_service.py:352-358, :846-857 | cookiefile + cookiesfrombrowser on one YoutubeDL ⇒ yt-dlp writes the browser's **entire cookie jar** (all domains, plaintext) into the user's cookies.txt (reproduced: a bank-session cookie appeared). | Pop the cookiefile before close(). |
| AUD-225 | P2 | services/youtube_service.py:308 | 
ocheckcertificate: True disables TLS verification for every yt-dlp request, including the media bytes (same flag in SoundCloud, VK and cache_manager). | Remove it. |
| AUD-226 | P2 | services/youtube_service.py:267-275 | The _get_ydl cache key omits the cookie configuration and eset_ydl() has no caller ⇒ changing rowser_cookies never takes effect for playback. | Include the config in the key. |
| AUD-227 | P2 | services/soundcloud_service.py:662-690 | A DRM transcoding discards a playable URL found in a *later* non-DRM transcoding (diverges from yt-dlp). | Keep scanning the list. |
| AUD-228 | P1 | services/soundcloud_service.py:109, :541-567 | One CDN probe answering 401/403/404/410 removes the track for a full hour with a wrong "DRM or removed" message. | Re-probe before memoising. |
| AUD-229 | P2 | services/soundcloud_service.py:607-617 | The SoundCloud probe can invalidate a *YouTube fallback* URL and then blame DRM — cross-provider contamination of the shared stream cache. | Scope the memo to the provider. |
| AUD-230 | P2 | services/soundcloud_service.py:96, :663 | A transcoding with "format": null raises AttributeError and abandons the whole api-v2 fast path. | or {}. |
| AUD-231 | P2 | services/soundcloud_service.py:337 | One track with "duration": null aborts the entire api-v2 search page (19 usable hits lost). | Coerce defensively. |
| AUD-232 | P1 | services/soundcloud_service.py:553-564, :1023-1032 | The provider fetches payload-derived URLs with no SSRF guard and no host allow-list (the waveform URL reaches the bridge verbatim). | Route through the guarded opener. |
| AUD-233 | P2 | services/soundcloud_service.py:141-153 | The positive stream cache is class-level while the negative/verified caches are per-instance ⇒ a second instance re-issues every call the first was told to forget. | Make all three class-level. |
| AUD-234 | P2 | services/soundcloud_service.py:415-447 | get_playlist_tracks never sends limit to the API — the whole set is downloaded to render 50 rows. | Send the limit. |
| AUD-235 | P1 | services/catalog_service.py:18-23, :230-237 | credited_to/rtist_matches split asymmetry: "Earth, Wind & Fire" is never credited to itself (their albums are permanently unopenable), while a *different* artist's album is accepted. | Fix the split on both sides. |
| AUD-236 | P2 | services/playlist_import_service.py:233-254 | One bad duration in a JSON playlist silently replaces the whole playlist with one garbage entry (the raw JSON as the title). | Validate per item. |
| AUD-237 | P2 | services/playlist_import_service.py:46 | A remote .m3u8/.json/.txt playlist URL is never fetched — the extension branch routes to the local-file resolver, so the app cannot import its own exported .m3u8. | Fetch it (guarded). |
| AUD-238 | P2 | services/playlist_import_service.py:79-124 | The imported track list is uncapped and each track is its own DB transaction inside one bridge call. | A cap + one batch transaction. |
| AUD-239 | P2 | services/playlist_import_service.py:60-71, :126-136 | The import's SSRF guard validates the typed URL only — yt-dlp follows 30x to any host (the proxy re-validates every hop; the importer does not). | Re-validate each hop. |
| AUD-240 | P2 | services/playlist_import_service.py:61-66 | No socket timeout and no entry cap on the import — a hung import parks a bridge thread forever. | socket_timeout + a playlist end. |
| AUD-241 | P2 | services/artist_service.py:133-169, :221-317 | The discography collection has no deadline and ignores is_current() ⇒ up to 9 sequential calls per superseded profile, holding one of the 8 shared workers. | A deadline + cancellation. |
| AUD-242 | P2 | services/artist_service.py:35, :48-49 | The avatar cache is dead — the documented "cached for a week" is false; the real TTL is 900 s. | Wire the cache or fix the doc. |
| AUD-243 | P2 | services/smart_playlists.py:165-171 → core/offline.py:63-64 | The offline smart-playlist page re-scans the whole stream_cache per 500-row batch (measured 50 000 row reads per page). | Index + one materialised set. |
| AUD-244 | P2 | services/spotify_service.py:110-119 | A superseded search generation's cancellation error is delivered to the **current** generation through the shared _join_request listener list ⇒ the live search silently loses all Spotify results. | Include the generation in the join key. |
| AUD-245 | P2 | services/itunes_gateway.py:21-22, :51-64 | The global 3.5 s single-slot throttle plus the 8 s gateway deadline exceed the bridge's 6 s provider timeout ⇒ the Spotify tab returns zero results while the request later succeeds (measured: 5 concurrent calls → 2 raised CatalogueUnavailable). | Align the budgets. |
| AUD-246 | P2 | services/yandex_service.py:38-67 | A rejected/expired token falls through to an anonymous client; on_auth_error/on_subscription_status are never assigned and the UI listens for an event the backend never emits. | Surface the auth failure. |
| AUD-247 | P2 | core/api.py:1930-1932 | The OAuth efresh_token/expires_in are discarded and no refresh path exists ⇒ expiry needs a manual re-auth. | Persist and use the refresh token. |
| AUD-248 | P2 | services/yandex_service.py:180-184, core/proxy.py:1024-1051 | Yandex direct links are cached 6 h but stream_url_expired only parses query params (Yandex embeds the ts in the path) ⇒ a dead link is re-served. | Parse the Yandex form. |
| AUD-249 | P2 | services/lastfm_service.py:23, :105-113 | API_KEYS is a module global filled only at construction ⇒ a key added after startup is ignored although the recommender reports "enabled". | Read the live setting. |
| AUD-250 | P2 | services/lastfm_service.py:116 | self._cache_lock = threading.Lock() shadows the base RLock ⇒ two same-named locks in one hierarchy (a breach of AGENTS.md rule 2). | Use the inherited lock. |
| AUD-251 | P2 | services/lufs_scanner.py:16-35, :80 | The whole file is decoded into RAM: +424 MB for a 5-minute file, +4.7 GiB for an hour (measured 32 B/frame). | Stream the decode in chunks. |
| AUD-252 | P2 | services/lufs_scanner.py:78-95 | Fabricated loudness is written as if measured: a missing file stores lufs=0.0 (the track then plays 14 dB too quiet) and a failed analysis stores -14.0. | Store a status, not a number. |
| AUD-253 | P2 | services/lufs_scanner.py:31-33 | -inf LUFS is persisted and shipped (json.dumps then emits invalid JSON); the player clamps the gain to +6 dB. | Reject non-finite values. |
| AUD-254 | P2 | services/lufs_scanner.py:63-69 | The LUFS query filters source='local' but mark_track_downloaded never changes source ⇒ **no downloaded track is ever analysed**. | Include downloaded rows. |
| AUD-255 | P2 | services/lufs_scanner.py:23 | miniaudio's default stereo output inflates every mono track by exactly +3.01 dB (measured) ⇒ mono tracks play 3 dB too quiet. | Read the real channel count. |
| AUD-256 | P2 | services/watchdog_service.py:104-116 | The watchdog watches **nothing** — scan_folders is never populated, so the whole "watch folder" feature is inert while costing a 1 Hz poll thread. | Wire the folder list or drop the subsystem. |
| AUD-257 | P2 | services/audio_fingerprint_service.py:71 | The duplicate scanner has the same blind spot — only source='local' rows, so the commonest duplicate case is invisible. | Same fix as AUD-254. |
| AUD-258 | P2 | services/audio_fingerprint_service.py:1-4, :26-61 | The "acoustic fingerprint" is a byte hash over 192 KiB — the same song in MP3 and FLAC is never detected, and "90 %" is a hard-coded constant behind a destructive delete. | A real fingerprint, or reword the promise. |
| AUD-259 | P1 | services/listening_comparison.py:56-66 | The correlated NOT EXISTS subquery re-scans the whole history per outer row ⇒ "365 days" takes **467 s** at 120 k rows (measured) and **83 s** at 50 k. | Materialise the pre-window artist set. |
| AUD-260 | P2 | services/lyrics_lookup.py:95, :122, :152, :177, :195 | The listening history is broadcast to 5 third-party lyric providers on **every** track change, with no disclosure and no opt-out. | A lyrics.enabled setting + disclosure. |
| AUD-261 | P2 | services/lyrics_lookup.py:346-357 | One lookup = 16–27 outbound HTTPS requests to 5 hosts; nothing bounds the count. | Cap the fan-out; add a regression test. |
| AUD-262 | P2 | services/lyrics_lookup.py:284 | The 8 s budget starts before the job owns a pool slot ⇒ a lookup can expire with **zero** providers contacted. | Start the deadline on admission. |
| AUD-263 | P2 | services/lyrics_service.py:269-272 | A failed translation returns the **input unchanged** ⇒ the UI index-aligns it into an identity map and renders every line twice. | Return a typed failure. |
| AUD-264 | P2 | services/lyrics_service.py:259-260 | The translation silently truncates at 10 chunks (48 % lost in the probe) and can split a line mid-way, shifting the alignment. | Report truncation. |
| AUD-265 | P2 | services/lyrics_service.py:246-247, :264 | The translation chunk bound is in characters, not encoded bytes — a 1500-char Cyrillic chunk produces a 9 kB URL. | Bound the encoded size. |
| AUD-266 | P2 | services/lyrics_service.py:243-272 | The translation path has **no offline gate** (unlike the provider path) and sends the whole lyric text to Google. | Reuse is_offline(). |
| AUD-267 | P2 | services/lyrics_service.py:87-88, :192-195 | The lyrics thread pool is never shut down by AppCore.cleanup() ⇒ the app's exit waits for an in-flight read (measured 5.14 s). | Add it to the _step(...) list. |
| AUD-268 | P2 | services/lyrics_service.py:236-241 | The lyrics stack bypasses the app's proxy setting (raw urlopen) ⇒ behind a required proxy, lyrics never work but the error says "sources unavailable". | Use the same proxy handler. |
| AUD-269 | P2 | services/recommendation_service.py:173-185 | The API-supplied history rows lack the measurement columns, so the measured-skip demotion never fires for the 30 newest tracks ⇒ skipped tracks come back. | Merge the measured fields onto the caller's row. |
| AUD-270 | P2 | services/taste_profile.py:357-371 | The 60 s profile memo embeds the thread's connection object in the revision key ⇒ it can never hit across threads (measured 0 vs 7 SELECTs). | Drop conn from the revision. |
| AUD-271 | P2 | services/recommendation_service.py:158 + services/artist_identity.py:13-32 | The alias table is rebuilt per candidate (6 180 rebuilds per ranking; 840 ms with 50 bindings). | Cache it per settings revision. |
| AUD-272 | P1 | core/services/recommendation.py:1-240 | The "scoring core" module is **dead code** — nothing imports it; fixes applied there are inert. | Delete it or make it the single scorer. |
| AUD-273 | P2 | core/api.py:3537-3553 | get_recommendations waits 3 s for a job that needs 8–12 s ⇒ it always returns [] and the late result is discarded. | Make it event-based. |
| AUD-274 | P2 | core/api.py:3515-3535, :3583-3593 | get_artists_avatars is N+1 over the shared pool with no cancellation; get_waveform is a synchronous, uncancellable 10 s HTTP request per track change. | Bound and cancel. |
| AUD-275 | P2 | core/api.py:3315-3335 | get_popular_tracks(region) drops the region — get_charts never reads country. | Pass the region through. |
| AUD-276 | P2 | core/api.py:3227-3284 | The cover backfill is permanently monopolised by unresolvable rows (no attempt tracking) ⇒ the oldest rows are never attempted. | Mark failures. |
| AUD-277 | P2 | core/api.py:3286-3291 | get_lyrics_translation returns three different shapes (str / {"error"} / None). | One envelope. |
| AUD-278 | P2 | core/api.py:2382-2396 | Re-importing a playlist of an existing name silently duplicates every track (4 membership rows for 2 tracks). | Deduplicate on insert. |
| AUD-279 | P2 | core/api.py:2517-2530 | dd_to_playlist never de-duplicates (no UNIQUE(playlist_id, track_id)). | Add the constraint. |
| AUD-280 | P2 | core/api.py:3918-3929 | update_track_tags cannot clear album/genre/year — the old value is substituted. | Allow an explicit clear. |
| AUD-281 | P2 | core/api.py:2474 | The m3u8 export is not escaped — a newline in a title splits #EXTINF and the remainder becomes a bogus path entry. | Escape. |
| AUD-282 | P2 | core/api.py:3936-3957 | update_track_tags embeds an arbitrary client-supplied file as the cover, with no size/type/root check (a .pdf was copied byte-for-byte to covers/1.jpg). | Only accept covers written by choose_cover_image. |
| AUD-283 | P2 | core/api.py:3887-3889 | delete_duplicate_track is a hard delete — history, playlist memberships and the favourite flag all CASCADE away (verified 1→0, 2→0). | Merge, don't delete. |
| AUD-284 | P2 | core/api.py:3436-3459 vs js/library.js:114-126 | open_local_file returns a bool where the UI expects an object ⇒ success is reported as failure and cancel is indistinguishable from an error. | One envelope. |
| AUD-285 | P2 | core/api.py:2405-2414 | A failed import into a pre-existing playlist leaves the partially added tracks behind. | Roll back the rows too. |
| AUD-286 | P1 | core/api.py:2294-2360 | download_track overloads id: a provider's synthetic string id skips the row creation ⇒ the file is an orphan and "download complete" fires for a track that is not in the library. | Distinguish the provider id from the row id. |
| AUD-287 | P2 | core/api.py:2356-2359 | download_track returns False with **no event** on a queue rejection/duplicate ⇒ the UI spinner never clears. | Emit a failure event. |
| AUD-288 | P2 | core/api.py:2217-2225 + services/spotify_service.py:124-147 | Spotify ignores esult_type='playlists' and returns tracks, which the UI renders as playlist cards with a fabricated "10 треков". | Implement the filter or hide it. |
| AUD-289 | P2 | core/api.py:2084-2088 | search emits no search_completed for an empty/whitespace query (the bridge contract at :2078-2081 is broken). | Always emit the sentinel. |
| AUD-290 | P1 | core/api.py:2100 + services/spotify_service.py:31, :50 | The "Spotify" provider is an **Apple/iTunes** gateway mislabelled end to end (the UI shows the Spotify logo, the placeholder says "Поиск в Spotify…", the album grid says "iTunes"), with a YouTube-shaped source_id. | Rename it, or implement the real API. |
| AUD-291 | P2 | core/api.py:2083 | The raw search query is written verbatim to the on-disk log at INFO and travels in two third-party URLs. | Redact. |
| AUD-292 | P2 | core/api.py:3595-3638 | _clean_stream_cache deletes the cached audio of **favourite** and **downloaded** tracks and of in-flight downloads, ignoring the protection CacheManager owns, and leaves dangling DB rows. | One cache owner. |
| AUD-293 | P2 | core/api.py:3595 vs core/api.py:4085 | The cleaner enforces a private 350 MB / 48 h policy and ignores the user's storage.cache_quota_gb (including 0 = "no limit"). | One policy. |
| AUD-294 | P2 | core/api.py:3717-3718 | download_all_favorites includes local favourites ⇒ each emits download_failed {"error": "missing source_id"} raw. | Filter to downloadable sources. |
| AUD-295 | P2 | core/api.py:3818-3838 | Disabling Discord calls clear_presence() but never stop() ⇒ the IPC socket stays open and the status reads {"enabled": false, "connected": true}. | One set_enabled(). |
| AUD-296 | P2 | core/api.py:4132-4161 | set_offline_mode(True) rewrites the queue to offline-playable tracks and clears it if none is playable; switching back never restores it. | Keep a restorable snapshot. |
| AUD-297 | P2 | core/api.py:4223-4225 | get_listening_comparison lets ValueError/TypeError escape and rejects real UTC+13/+14 offsets. | Validate and widen. |
| AUD-298 | P2 | core/api.py:3867-3874 → services/zapret_service.py:740-751 | ind_binary() returns a CWD-relative in\winws.exe **unvalidated**, and _launch() does not re-validate. | Validate at the use site. |
| AUD-299 | P2 | core/api.py:3860-3865 | check_zapret_update has no UI caller; if wired it costs a 6 s GitHub round-trip on the bridge thread. | Make it asynchronous. |
| AUD-300 | P2 | core/api.py:3717-3718 | download_all_favorites emits one download_queue_updated per track — 400 events for 400 favourites, each a blocking UI-thread round trip. | Coalesce. |
| AUD-301 | P1 | utils/tag_parser.py:249, :264-267, :302 | write_tags rewrites the user's audio file **in place** — the docstring's "atomic" claim is false; a crash mid-write corrupts the only copy (the %TEMP% backup is never restored). | Temp file + os.replace. |
| AUD-302 | P1 | utils/tag_parser.py:180-189 | OGG cover extraction returns the **FLAC picture block** instead of image bytes ⇒ every OGG cover is broken. | Decode the picture block. |
| AUD-303 | P1 | utils/tag_parser.py:23, :372-386 | write_tags fails on .wav/.aac/.wma although all are in SUPPORTED_FORMATS and .wav is offered in the open dialog. | Handle the format families separately. |
| AUD-304 | P2 | utils/file_scanner.py:128, :142-151 | _import_file overwrites an existing track's cover and silently drops the new file (the DB identity is title+artist). | A stronger identity key. |
| AUD-305 | P2 | utils/cache_manager.py:85-89, :192-196 | The quota counts covers+temp+streams but only streams/ is purged ⇒ the target can never be met and every purge wipes the whole stream cache. | One accounting + one purge. |
| AUD-306 | P2 | utils/url_safety.py:24-33 | is_safe_media_url does an **uncached, untimed** getaddrinfo and fails closed — on the playback and download hot paths a DNS hiccup drops a valid direct URL. | Share the memoised, bounded resolver. |
| AUD-307 | P2 | utils/tag_parser.py:131-140 | Embedded lyrics are returned as Python reprs ("['line one', 'line two']", "b'la la la'"). | Normalise the shape. |
| AUD-308 | P2 | utils/tag_parser.py:111-116 | The artist fallback splits the stem on the **first** " - " ⇒ "03 - Never Gonna Give You Up.mp3" yields artist "03". | Split on the last separator. |
| AUD-309 | P2 | utils/file_scanner.py:58-109 | The folder-scan half of FileScanner is unreachable — no bridge method, no JS call. | Wire it or delete it. |
| AUD-310 | P2 | services/zapret_service.py:317, :960, :1008 | The non-reentrant _update_lock is held across start() → download_binaries() → with self._update_lock: ⇒ a self-deadlock (the update thread never returns). | Use an RLock or restructure. |
| AUD-311 | P2 | services/zapret_service.py:320, :1270 | The elevated EXE (and its WinDivert.dll) runs from a **user-writable** directory ⇒ local privilege escalation. | Install to a protected location. |
| AUD-312 | P2 | services/zapret_service.py:700-711 | Stopping raises an unsolicited UAC prompt at shutdown; declining leaves the elevated bypass running. | Kill by the tracked PID without elevation. |
| AUD-313 | P2 | services/zapret_service.py:557-663 | Process discovery shells out to tasklist + (dead) wmic + PowerShell on **every** call (measured 912 ms) ⇒ the toggle blocks the bridge for seconds. | Use the tracked PID / a job object. |
| AUD-314 | P2 | services/zapret_service.py:833-837 | The update download is unbounded and fully buffered ⇒ a hostile endpoint can OOM the bridge thread. | Cap the size and stream it. |
| AUD-315 | P2 | services/zapret_service.py:861-862, :997 | The extraction guard skips any valid existing binary ⇒ "Update Zapret" never replaces winws.exe yet still reports success and bumps the version file. | Always replace. |
| AUD-316 | P2 | services/zapret_service.py:1282-1285 | The elevated launch uses cmd.exe without /d and takes COMSPEC from the environment. | Hard-code the absolute path and /d. |
| AUD-317 | P2 | services/zapret_service.py:734-752 | A rejected user inary_path is silently ignored — ind_binary falls through to the default candidate. | Report the rejection. |
| AUD-318 | P2 | core/services/discord_rpc.py:68-85 | The Discord presence can outlive stop() (the connect thread assigns after stop() nulled the client) and the connect handshake has no timeout. | A stop flag + join. |
| AUD-319 | P2 | services/vk_service.py:63 | The VK extractor disables TLS certificate verification. | Remove it. |
| AUD-320 | P2 | services/vk_service.py (whole) | There is **no VK API**: search() always returns [], play_direct_url has no caller, the service is never used, and it duplicates the provider plumbing instead of extending BaseMusicService. | Delete it or implement it. |
| AUD-321 | P2 | services/spotify_service.py:18, :107-108 | The Spotify/iTunes provider snapshots uth.proxy_url at construction into a module-global session ⇒ a runtime proxy change never reaches it. | Re-read the proxy per request. |
| AUD-322 | P2 | services/yandex_service.py:38-59 | Editing uth.yandex_token by hand never reaches the live client (the token is read only at client creation) — the UI offers exactly that edit. | Invalidate the client on a settings write. |
| AUD-323 | P3 | services/zapret_service.py:171-174 | The PE machine-type gate is a tautology (machine in (0, 0x8664) or machine > 0 is always true) — its docstring claims otherwise. | Implement the real check. |
| AUD-324 | P3 | services/zapret_service.py:90, :203-219 | The argument grammar is a shape check, not an option allow-list — --hostlist=C:\Windows\win.ini is accepted. | Allow-list the options. |
| AUD-325 | P3 | services/zapret_service.py:90, :213 | shlex.split(posix=False) keeps the quotes, so a quoted argument is rejected and a comma-list is split. | Use a Windows-aware splitter. |
| AUD-326 | P3 | services/zapret_service.py:140-150 | A rejected client id costs 5 round trips for one logical call; each instantiation creates a new pool + session + client-id scrape (the downloader builds one per download). | Share one instance. |
| AUD-327 | P3 | services/soundcloud_service.py:17-49 | _TTLCache never purges expired entries proactively and the *positive* verified cache inherits the negative 1 h TTL. | Separate the TTLs. |
| AUD-328 | P3 | services/youtube_service.py:221, :786-788 | _prefer_anonymous is a one-way latch — one anonymous success disables the user's configured browser cookies for the rest of the session. | Make it per-request. |
| AUD-329 | P3 | services/youtube_service.py:35-57 | _detect_browser_cookies() is dead code. | Delete it. |
| AUD-330 | P3 | services/youtube_service.py:64-79 | The gating marks contain bare "bot"/"drm" substrings ⇒ unrelated errors are reported as an anti-bot gate. | Use precise patterns. |
| AUD-331 | P3 | services/youtube_service.py:1016-1022 | info["formats"][-1] (often a video-only mp4) is returned without an codec filter ⇒ a URL that plays nothing. | Filter by codec. |
| AUD-332 | P3 | services/youtube_service.py:83, :98 | m.youtube.com is not in _YT_HOSTS ⇒ a legitimate URL is rejected. | Add it. |
| AUD-333 | P3 | services/youtube_service.py:711-713 | get_playlist ignores ytmusicapi's continuation ⇒ a 500-track playlist is silently capped at 50. | Follow the continuation. |
| AUD-334 | P3 | services/youtube_service.py:260-266 | quality_map maps all four levels to estaudio/best ⇒ the argument is a no-op. | Map them properly. |
| AUD-335 | P3 | services/youtube_service.py:490-498 | The YouTube dicts omit source_url, which every other provider includes. | Add it. |
| AUD-336 | P3 | services/soundcloud_service.py:887-893 | The download path cannot recognise SoundCloud's 30-second preview URL ⇒ a preview can be registered as the downloaded track. | Reuse the streaming detector. |
| AUD-337 | P3 | services/soundcloud_service.py:158, :212-229 | api-v2 429 is neither retried nor surfaced; Retry-After is ignored. | Honour the header. |
| AUD-338 | P3 | services/soundcloud_service.py:173-210 | "No client id" is never surfaced — the fast path is skipped silently. | Report it. |
| AUD-339 | P3 | services/music_matching.py:44-45 | credits() splits "featuring" on "feat" ⇒ the credit becomes "uring Other", which keys the lyrics cache. | Order the alternations. |
| AUD-340 | P3 | services/music_matching.py:33-35 | similarity() is order-dependent (difflib ratio is not symmetric). | Sort the arguments. |
| AUD-341 | P3 | services/artist_identity.py:13-32 | rtist_aliases() is rebuilt on every comparison (2 SHA-256 per binding). | Cache per revision. |
| AUD-342 | P3 | services/playlist_import_service.py:50, :54 | The provider dispatch is a substring test ⇒ https://attacker.example/youtube.com is treated as YouTube. | Match the host. |
| AUD-343 | P3 | services/smart_playlists.py:71-76, core/api.py:4214 | A corrupt ule_json makes the collection vanish from the list **and** raise out of the bridge. | Validate on read. |
| AUD-344 | P3 | services/catalog_service.py:49-70 | _cached can leave a key permanently in-flight if the result is not deep-copyable. | 	ry/finally. |
| AUD-345 | P3 | services/artist_service.py:33-49 | AVATAR_TTL, _avatars and _avatars_lock are dead, and _avatars_lock is a forbidden second lock. | Delete them. |
| AUD-346 | P3 | services/catalog_service.py:144 | Artist names ≤ 4 chars never yield near-candidates (similarity('ABBA','ABBA Band') == 0.0). | Lower the guard. |
| AUD-347 | P3 | services/playlist_import_service.py:58 | The "unsupported service" message omits SoundCloud, which is supported. | Fix the message. |
| AUD-348 | P3 | services/yandex_service.py:263-287 | The ya_<raw_id>_<ts>.mp3 filename branch is now unreachable — contract #8's Yandex example is stale. | Update the contract. |
| AUD-349 | P3 | services/lyrics_lookup.py:203-210 | The megalobiz provider reads LRC header names case-sensitively ([TI:] is missed). | Lower-case the keys. |
| AUD-350 | P3 | services/lyrics_lookup.py:320-327 | Embedded lyrics preempt the whole cascade and are never identity-checked. | Verify the match. |
| AUD-351 | P3 | services/lufs_scanner.py:63-69 | The LUFS cache has no mtime ⇒ a replaced file keeps the old measurement and can never be re-measured. | Key on path+mtime. |
| AUD-352 | P3 | services/lufs_scanner.py:100-107 | The LUFS writer bypasses db._write_lock and the transaction context. | Use the lock. |
| AUD-353 | P3 | services/lufs_scanner.py:53-56 | stop() does not wait for the in-flight analysis ⇒ the result is written to a closed DB and lost. | Join. |
| AUD-354 | P3 | services/watchdog_service.py:59-66 | The Windows lock probe never fires (share-deny-none) ⇒ a partially written file is imported. | Size/mtime stability check. |
| AUD-355 | P3 | services/watchdog_service.py:97-102 | observer.join() on a never-started observer raises RuntimeError (swallowed). | Guard it. |
| AUD-356 | P3 | services/listening_comparison.py:23-25, :42-45 | One fixed UTC offset for the whole window ⇒ the DST transition day is mis-bucketed by one hour. | Per-day offsets. |
| AUD-357 | P3 | utils/cache_manager.py:171-271 vs core/api.py:3595-3638 | The stream cache has **three owners** with different ceilings, protections and DB sync. | One owner. |
| AUD-358 | P3 | utils/url_safety.py:13-37 vs core/api.py:133-195 | Two divergent SSRF guards — one fail-closed (engine/downloader), one fail-open (bridge and proxy). | One implementation. |
| AUD-359 | P3 | utils/tag_parser.py:100, :103-106 | The unanchored (?i)HD/(?i)HQ mangle real names ("Ashdown" → "Asown"). | Anchor the patterns. |
| AUD-360 | P3 | utils/tag_parser.py:161-167 | The first APIC frame wins regardless of its type (a back cover can be used) and the declared MIME is trusted, never the bytes. | Pick the front cover; sniff the bytes. |
| AUD-361 | P3 | utils/tag_parser.py:87-89 | Failures are reported with print(), which is a no-op in the console=False build ⇒ they never reach the log. | Use the logger. |
| AUD-362 | P3 | utils/cache_manager.py:213, :225-229 | The favourite-protection key uses the raw source_id while the file name uses the sanitised id ⇒ the protection silently fails. | Use one key form. |
| AUD-363 | P3 | utils/tag_parser.py:226, utils/cache_manager.py:430, core/api.py:3954 | Three cover-naming conventions in one directory ⇒ duplicate and stale artwork. | One convention. |
| AUD-364 | P3 | utils/file_scanner.py:85-87 | _scanning is a boolean, not a generation ⇒ a cancel + a new scan lets the old thread's inally abort the new scan. | Use a generation counter. |

---
### 5.4 Frontend (WN-28 – WN-33)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-365 | P2 | js/events.js:258-263, js/library.js:962-964 | Every completed download refreshes the library **twice** (and the library_updated path adds two more). | One coalescing refresh. |
| AUD-366 | P2 | js/main.js:82 | main.js **replaces** window.NeDotify, destroying utils.js's module-scope floating-menu guard (the fix for a stranded menu). | Merge, never replace. |
| AUD-367 | P2 | js/events.js:266-281 | download_failed clears the spinner of **every** downloading row, not just the failed one — and removes the re-click guard. | Target one row. |
| AUD-368 | P2 | js/main.js:104-109 | Fire-and-forget bridge calls ⇒ unhandled promise rejections and a stuck UI (the error branch is dead code). | wait + .catch. |
| AUD-369 | P2 | js/utils.js:694, :977-1017 | download_complete carries only the numeric DB row id while provider rows are keyed by source_id ⇒ the download spinner never clears after a successful download. | Carry both ids, or match on source_id. |
| AUD-370 | P2 | js/player.js:1695-1705 | Rapid "next" on an unresolved track calls play_track without the queue; a late resolution replaces the whole queue with one track. | Pass the queue / a generation token. |
| AUD-371 | P2 | js/player.js:1973-1992 | (AUD-006 — settings.shuffle/.repeat read at the wrong depth; the volume is never restored and the repeat button is always lit.) | Read settings.session.*. |
| AUD-372 | P2 | js/player.js:1695-1705, core/api.py:1606 | One click starts **two** resolution chains (the page reads the absence of stream_url as "not started"). | An explicit status field. |
| AUD-373 | P2 | js/queue.js:6, :61-69 | The frontend's queue copy is never refreshed on shuffle; a stale copy is sent back to the backend and overwrites the queue. | The backend owns the queue. |
| AUD-374 | P2 | js/player.js:1695-1705 | No playback state machine — isPlaying=false while the previous track is still audible; currentDuration has 6 writers and 	argetPosMs is written 5× and never read. | One state object. |
| AUD-375 | P2 | js/player.js:1416, :2296-2303 | The progress rAF forces 3 style recalculations and 3 uncached getElementById per frame (≈90 forced recalcs/s). | Cache the elements; move the read behind the guard. |
| AUD-376 | P2 | js/queue.js:128-300 | The queue drawer rebuilds every row and runs a global lucide pass on every queue_updated. | Scope the icon pass. |
| AUD-377 | P2 | js/player.js:119-123 | HLS detection only inspects the url query param ⇒ a proxied HLS playlist in the /api/stream?track_id= form is fed to <audio src> (WebView2 has no native HLS). | Detect by type, not by URL shape. |
| AUD-378 | P2 | js/main.js:44-73 | waitBridge() spawns one unbounded 100 ms poll per call site (16 of them) and none stops if the bridge never initialises. | One shared waiter. |
| AUD-379 | P2 | js/efficiency.js:48-51 | initBlurObserver observes all of document.body — the #views-container it scopes to does not exist in index.html. | Use the real container. |
| AUD-380 | P2 | js/search.js:109-113 + core/api.py:2090-2096 | The 200 ms debounce guards only the network call; each keystroke still starts a full 4-provider fan-out and the results are delayed until the earliest stale request times out (6–8 s). | Cancel the previous request. |
| AUD-381 | P1 | js/search.js:406-434 | The "Плейлисты" filter fabricates playlist tiles from plain track results with a hard-coded "10 треков"; ▶ on them is a dead end. | Fix the provider filter. |
| AUD-382 | P2 | js/home.js:869-881 | The "Топ исполнителей" tiles navigate to Search but never search (they write a field nobody reads). | Set the search input. |
| AUD-383 | P2 | js/search.js:546, :682, :769, :879 | The album/playlist grids bypass coverImgHtml ⇒ covers load eagerly (no loading="lazy"), and the inline onerror is dead under the CSP. | Use the shared helper. |
| AUD-384 | P2 | js/library.js:350-352, :513-515 | The favourites counter double-counts tracks liked from search (the localStorage key and the DB id are different namespaces). | One id namespace. |
| AUD-385 | P2 | js/library.js:867-872, :937 | "Add to playlist" failures are reported as success (the backend returns a bool; the check tests .success). | Check the boolean. |
| AUD-386 | P2 | js/library.js:447-454, :519 | The library scroll loader is not detached on the empty-collection path ⇒ stale rows are appended into the empty collection. | Always tear down. |
| AUD-387 | P2 | js/lyrics.js:65-83 | A failed translation renders the original text as the "translation" (every line duplicated). | Show the error. |
| AUD-388 | P2 | js/artist_profile.js:51-58 | The artist key is re-implemented in the UI and diverges from services/artist_identity.py (different folding, a hard-coded alias, no multi-artist split). | Reuse one implementation. |
| AUD-389 | P2 | js/artist_profile.js:553, :618-628 | "Популярные треки" is never sorted by popularity and its badges are dead (the payload carries no count). | Sort or rename. |
| AUD-390 | P2 | js/smart-playlists.js:90-108 | The preset dropdown is not synced with the loaded rule; switching it silently discards the user's edits. | Bind the dropdown to the rule. |
| AUD-391 | P2 | js/settings.js:1039-1041 | Every setting — including the Yandex OAuth token — is mirrored into WebView2 localStorage **in cleartext**. | Never mirror a secret. |
| AUD-392 | P2 | js/settings.js:1033-1053 | No rollback on a bridge failure: the UI shows the new value while the backend kept the old one (it silently reverts on restart). | Roll back on failure. |
| AUD-393 | P2 | js/hotkeys.js:136-143 | The keybind save has zero error handling — the binding looks saved, the backend never got it. | Await + report. |
| AUD-394 | P2 | js/settings.js:1736-1755 | The colour picker persists on every input event: 2 bridge calls + 2 synchronous localStorage writes per frame. | Preview on input, commit on change. |
| AUD-395 | P2 | js/settings.js:402-407 | The "Регион поиска" select is a no-op — general.region has **zero** readers. | Wire it or remove it. |
| AUD-396 | P2 | js/settings.js:128, js/player.js:724-730 | The "Нормализация громкости (EBU R128)" toggle does nothing — the gain is applied whenever the track has LUFS, with no guard. | Honour the flag. |
| AUD-397 | P2 | js/settings.js:226-243 | "Очистить кэш" has no confirmation although it wipes ~/.nedotify/{covers,streams,temp} in one click. | Add a confirmation. |
| AUD-398 | P2 | js/feature-controls.js:112, js/player.js:1440 | The offline state is never restored at startup (the 
etwork category is missing from get_settings()). | Project the category. |
| AUD-399 | P2 | js/settings.js:962-965, index.html:1755 | The proxy URL (which may embed user:pass@) is shown in an unmasked 	ype="text" input. | Mask it. |
| AUD-400 | P2 | css/fonts.css:48-99, index.html:2 (lang="ru") | The bundled fonts cover **latin only** — no unicode-range for U+0400-04FF ⇒ every Russian string falls back to Segoe UI and the Sora display face never paints a heading. | Ship a Cyrillic subset. |
| AUD-401 | P2 | css/components/home-refresh.css:12-24 | A **component** file re-declares the global :root[data-theme="dark"] palette with the same specificity but is linked later ⇒ the shipped Dark preset is green, not the purple 	hemes.css defines (verified: --primary = 24,214,162 instead of 168,85,247). | One owner per token. |
| AUD-402 | P2 | css/components/home-refresh.css:9-10 vs player-bar.css:34-35 | A plain later :root outranks an earlier @media-wrapped :root ⇒ both of the player-bar's breakpoint overrides are dead. | One declaration site. |
| AUD-403 | P2 | css/components/base.css vs the 12 *-refresh.css | **200 conflicting (selector, property) pairs on 69 selectors**; 442 !important; #player-bar declares ackdrop-filter 3× with 3 different values. | Migrate to one base. |
| AUD-404 | P2 | css/tokens.css:8-31 vs ase.css:113-125 | "Declared exactly once" is false: 10 properties are in both and **9 disagree**; the token values are dead. | One owner per token. |
| AUD-405 | P2 | 	ools/visual_guard/goldens/ (0 files) + diff.py:113-124 | The pixel half of the visual guard compares against an **empty** baseline and returns ok=true, compared=0 — a vacuous pass. | Commit goldens; fail on an empty set. |
| AUD-406 | P2 | index.html:17-50 | 25 render-blocking stylesheets (427 KB) with Cache-Control: no-cache ⇒ re-fetched on every cold start; ~162 KB is per-view and deferrable. | Split blocking vs per-view. |
| AUD-407 | P2 | css/components/base.css:589+isual-polish.css:77+lyrics.css:245+player-bar.css:50 | 76 ackdrop-filter declarations (48 active), 27 shared selectors always on; #lyrics-overlay is a full-screen lur(40px). | Cap the blur surfaces. |
| AUD-408 | P2 | css/components/base.css:1729 + js/particles.js:301-317 | ilter: blur(8px) on the container of a full-viewport canvas repainted at 24–30 fps ⇒ 8.3 Mpx of Gaussian blur per frame. | Drop the blur. |
| AUD-409 | P2 | js/appearance-assets.js:48, js/settings-view.js:13 | The theme previews resolve to 1600-px wallpapers (5 MB) drawn in 186×58 boxes; the 17 purpose-built PNGs are unreachable. | Use the PNGs. |
| AUD-410 | P2 | js/settings.js:1230-1261, js/hotkeys.js:186-196 | Duplicate hotkey bindings are silently accepted; the first match wins and the shadowed action is unreachable — and the duplicate is persisted. | Detect conflicts. |
| AUD-411 | P1 | js/hotkeys.js:133-147 | A hotkey can never be re-bound to a modifier combination — a lone Ctrl keydown ends the recording before the chord's second key arrives. | Ignore modifier-only keydowns. |
| AUD-412 | P2 | js/hotkeys.js:72-78 | The legacy migration maps Ctrl+L → KeyK (should be KeyL), manufacturing a duplicate that kills like. | Fix the table. |
| AUD-413 | P2 | js/hotkeys.js:42-44 | / is matched by e.key, so the combo is layout-dependent and search=Slash cannot fire where / needs Shift. | Use e.code. |
| AUD-414 | P2 | js/search.js:686 | lbum.year is interpolated unescaped into innerHTML — the only unescaped field in that template. | Escape it. |
| AUD-415 | P2 | js/search.js:378, :399 | The search result list is fully rebuilt on every provider chunk (≈200 element builds for 80 rows). | Append the delta. |
| AUD-416 | P2 | js/home.js:63-213, js/events.js:163-205 | The home feed is filled by unversioned events ⇒ a late answer from an older loadHome() can win. | Carry a generation. |
| AUD-417 | P2 | js/home.js:709 + 7 copies | Seven copies of the .feed-card tile; the artist is a live link in one and dead text in three. | One component. |
| AUD-418 | P3 | js/utils.js:694 / js/search.js:546 etc. | 7 inline onerror= handlers are permanently dead under the app's own CSP (script-src 'self'). | Use the delegated handler. |
| AUD-419 | P3 | js/main.js:374-388 | sessionStorage is used unguarded at module top level ⇒ a throw aborts the module body and the 45 s bridge-error overlay is never scheduled. | Guard it. |
| AUD-420 | P3 | js/pages.js:114-141, js/events.js:16-19 | showPage('settings') returns before deactivating the base view ⇒ two views are .active and the hidden page still re-renders. | One owner for the active view. |
| AUD-421 | P3 | js/utils.js:1111-1114, :1372-1397 | showTrackContextMenu leaks a document click+keydown listener pair when a second menu replaces an open one. | Tear down on replace. |
| AUD-422 | P3 | js/debug.js:22-39 | JSON.stringify(arg) on a cyclic object throws **inside** the overridden console.error, masking the error the tool exists to show. | Guard the stringify. |
| AUD-423 | P3 | js/player.js:316-430, isualizer.js:500-519 | There is no teardown for the AudioContext / DSP graph; destroyVisualizer() is never called by the app. | Close the context. |
| AUD-424 | P3 | js/player.js:406-408 | udioCtx.resume() is unhandled 24×/s while suspended. | Catch it. |
| AUD-425 | P3 | js/player.js:810-851 | seekTo() clamps only the UI percentage, not currentTime nor the reported position ⇒ the backend records a position past the end. | Clamp both. |
| AUD-426 | P3 | js/player.js:1706-1709 | A track that can never play fails silently — no toast, no error event. | Raise the error path. |
| AUD-427 | P3 | js/equalizer.js:192-195, core/api.py:3173-3178 | The equalizer band-count mode is never restored from the backend ⇒ the EQ reopens with 3 bands while a 10-band curve is applied. | Persist the mode. |
| AUD-428 | P3 | js/queue.js:189-222 | queue.js removes a row by a render-time index; a stale index removes the wrong track and the backend reports success. | Identify by a stable key. |
| AUD-429 | P3 | js/queue.js:283-291 | A failed queue reorder is swallowed; the rows snap back with no message. | Report it. |
| AUD-430 | P3 | js/player.js:325-384 | If initAudioContext() fails half-way, the media element is captured by an unconnected AudioContext ⇒ total silence. | Connect atomically. |
| AUD-431 | P3 | js/player.js:97-103 | UNC local paths bypass 
ormalizeAudioSourceUrl and are loaded as bogus relative URLs. | Reject UNC explicitly. |
| AUD-432 | P3 | js/onboarding.js:234-235 | "Настроить позже" (skip) permanently completes the onboarding — the label promises "later", the state means "never". | Keep a re-entry point. |
| AUD-433 | P3 | js/onboarding.js:20-34, :56-59 | The onboarding "done" flag is stored in 3 localStorage keys **and** the DB; localStorage wins and the DB clause is dead. | One store. |
| AUD-434 | P3 | js/profile-comparison.js:31-38 | The bridge is called without waitBridge()/guards ⇒ a permanent "Не удалось сравнить периоды" when the bridge is not ready. | Await the bridge. |
| AUD-435 | P3 | js/settings.js:3234-3239 | The settings search rebuilds the entire grid and runs a body-wide lucide re-render per keystroke. | Debounce + scope. |
| AUD-436 | P3 | js/settings.js:3352-3388 | The settings live-search re-scans the whole settings DOM per keystroke (14 panels / 60 sections / ~74 rows). | Build an index. |
| AUD-437 | P3 | js/settings.js:1653, :1733 | --focus has **zero** CSS consumers — the "focus colour" picker is a silent no-op. | Implement it or drop it. |
| AUD-438 | P3 | css/components/base.css:120-122, :34 | --enable-transitions/--enable-animations/--enable-shadows/--bg-opacity are declared but read by neither CSS nor JS ⇒ inert perf switches. | Wire or delete. |
| AUD-439 | P3 | css/tokens.css:100 | --font-display names a **remote** font (Plus Jakarta Sans) ⇒ the heading typeface depends on the network. | Bundle it. |
| AUD-440 | P3 | js/settings-view.js:4-14 | The 17 theme-preview PNGs (313 KB) are never requested — the dead map points 5 themes at another theme's PNG. | Fix the map. |
| AUD-441 | P3 | css/styles.css:17-45 | The CSS architecture record is wrong in 5 load-bearing places (size, load order, "visual-polish.css is dead"). | Update the doc. |
| AUD-442 | P3 | ui/MACos_ui/library.css:60 | A url("../assets/…") escapes the pack root and only resolves by accident of the HTTP mount. | Fix the path. |
| AUD-443 | P3 | js/settings.js:35-46 | A second, divergent 10-theme THEMES array is never read and disagrees with PRESET_THEMES on the colour-slot order. | Delete it. |
| AUD-444 | P3 | css/components/base.css:1742 | .particle is styled but the class no longer exists (particles are canvas). | Delete it. |
| AUD-445 | P3 | js/player.js:681-696 | 
avigator.mediaSession.playbackState is never set to "playing". | Set it. |
| AUD-446 | P3 | js/player.js:613-616, core/api.py:1407-1428 | eport_position round-trips JS→Python→JS every 5 s; the echo is consumed by nothing (the handler early-returns while playing). | Make it one-way. |
| AUD-447 | P3 | js/visualizer.js:348-360 | The visualizer keeps a 24 fps loop alive while paused, with no idle budget. | Park it. |
| AUD-448 | P3 | js/particles.js:301-305 | The particle canvas is not ria-hidden (its siblings are). | Add it. |
| AUD-449 | P3 | js/particles.js:385 | The particle count is not scaled to the canvas area or the DPR. | Scale it. |
| AUD-450 | P3 | js/settings.js:1033-1053 | setting_changed is emitted per write but consumed by an empty case — a wasted UI-thread marshal per save. | Delete the emit. |
| AUD-451 | P3 | js/player.js:2546-2592 | The orbit glow runs at 30 Hz in mini mode, writing CSS variables into display:none elements. | Add a mini-mode condition. |
| AUD-452 | P3 | js/main.js:180 vs core/api.py:820 | The CSS class is swapped 250 ms before the native resize ⇒ a stretched mini card with a full-window backdrop-filter for a quarter second. | Synchronise the transition. |
| AUD-453 | P3 | js/player.js:1687-1692, core/api.py:1716-1737 | queue_ended is not final — an in-flight resolution of the last track restarts playback. | Mark the queue as closed. |

### 5.5 Test suite and tooling (WN-34, WN-35)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-454 | P1 | 	ests/test_emit_thread_safety.py | The contract #1 test patches the **test module's** _MAIN_THREAD, not core.api's — **proven: the suite still passes 9/9 with the branch deleted**. | Patch the production symbol. |
| AUD-455 | P1 | 	ests/conftest.py:115-129, :170-176 | edirect_home is opt-in and is **not** applied by the downloader/api/core fixtures ⇒ the suite writes stub_*.mp3 / gated_*.mp3 into the user's **real** ~/.nedotify/downloads/ (artefacts confirmed on disk, byte-exact against the fixture). | Make isolation an autouse session sandbox. |
| AUD-456 | P1 | 	ests/test_lazy_service_deadlock.py:15-19 | The re-entrant-lock test assigns its own RLock and cannot fail — **proven: production forced to a plain Lock still passes**. | Test the real lock. |
| AUD-457 | P1 | 	ests/test_android_source_gates.py:12-13 | The Android source gate hard-fails when the ndroid/ tree is absent (8 failures in 2.41 s) — it does not belong in the Windows suite. | Gate it on the tree's presence. |
| AUD-458 | P1 | .github/workflows/ci.yml:14 | CI runs only the **48 of 101** tracked test files; 53 test files (52 %) and 12 of the 35 JS modules are untracked ⇒ "CI green" covers about half the suite. | Gate that every 	ests/test_*.py is tracked. |
| AUD-459 | P2 | 	ools/check_lock_nesting.py:11 | The lock checker scans **only 	ools/** — never core/, services/, udio/, utils/ or main.py — and prints "OK" regardless; neither it nor check_shadow_imports.py is wired into any workflow or hook. | Point ROOT at the repo root and wire both into CI. |
| AUD-460 | P2 | 	ools/check_shadow_imports.py:49-56 | st.walk re-descends into nested bodies ⇒ a **false positive** on core/api.py (the import is inside a nested function) and another on self.conn (a SQLite connection used as a transaction CM). The gate is permanently red for the wrong reason. | Use a scope-aware walk and require a real 	hreading.Lock. |
| AUD-461 | P2 | 	ools/visual_guard/goldens/ | The visual guard has **zero** golden baselines (the folder exists but is empty and untracked) ⇒ the pixel half passes vacuously. | Commit the baselines. |
| AUD-462 | P2 | 	ools/bench/verify_frontend_report.py:1223 | The verifier crashes with UnicodeEncodeError while printing the notes ⇒ the **FAILED list is never printed** and it exits 1 for the wrong reason. | Reconfigure stdout. |
| AUD-463 | P2 | 	ools/bench/scenarios.py:390-411 | The scroll scenario scrolls an **empty** element; its recorded ows_rendered: 0 is the published "16.7 ms/frame (~60 FPS)" headline. | Populate before scrolling. |
| AUD-464 | P2 | 	ools/bench/scenarios.py:4 vs :438 | The search/eed/combo scenarios hit **live providers**, contradicting the harness's own hermeticity contract (recorded 74× spread). | Stub the providers. |
| AUD-465 | P2 | 	ools/bench/run_bench.py:196-209 | ggregate() silently drops failed reps but still reports 
_runs = total and exits 0 if any rep succeeded. | Report the failures. |
| AUD-466 | P2 | 	ools/bench/scenarios.py:249 | idle_states documents a "visible+playing" state it never measures; the minimise result is not checked. | Play something. |
| AUD-467 | P2 | 	ools/bench/results/animation_declarations.json | The CSS guard's baseline points at the **deleted** ui/web_new/ tree ⇒ 293 of the 302 "removed" declarations are phantom; 2 real regressions are buried under 89 "added". | Re-baseline. |
| AUD-468 | P2 | 	ools/bench/cdp.py:192 | evaluate() never detects JS exceptions — exceptionDetails is read at the wrong nesting level ⇒ it returns None silently. | Fix the parsing. |
| AUD-469 | P2 | 	ools/bench/check_pstats_consistency.py:19-29 | The checker implements the **inverse** of its documented rule ⇒ 22 false "inconsistencies" of 714 rows, including the hot rows the report cites. | Invert the predicate. |
| AUD-470 | P2 | 	ools/bench/procsampler.py:18-21 | psutil is in neither requirements file ⇒ without it the sampler is a no-op and the bench records **no** CPU/RAM while still exiting 0. | Declare the dependency. |
| AUD-471 | P2 | docs/prof_*.md + all 	ools/bench/results/* | Every recorded artefact is **stale** (the tree fingerprint differs; prof_frontend.md fails 7 of its own verifier checks; 21 of 97 citations in prof_python_startup.md have drifted). | Re-generate and stamp. |
| AUD-472 | P2 | 	ools/bench/run_bench.py:128-173 | Ctrl-C leaves the app running (the CDP port open, the mutex held) and then deletes the scratch profile under it. | Handle KeyboardInterrupt. |
| AUD-473 | P2 | 	ools/visual_guard/run_guard.py:666-691 | The CLI modes are mutually inconsistent — --all can never pass and --capture destroys the reference set. | One documented workflow. |
| AUD-474 | P2 | 	ools/bench/scenarios.py | No scenario exists for the **play path** or the **download path** — the two most important flows are unmeasured. | Add them. |
| AUD-475 | P2 | 	ools/visual_guard/diff.py:22 | A 0.1 % ratio budget lets a 1-px shift of a ≤500 px element pass. | Tighten the threshold. |
| AUD-476 | P2 | pytest.ini:3-5 | The 
etwork marker is declared but **never used** (0 matches) — pytest -m network collects nothing, so the "network tests are deselected" guarantee is inert. | Mark the real network tests or delete the marker. |
| AUD-477 | P2 | .github/workflows/ci.yml:22-30, pytest.ini, equirements.txt | No lint / type / coverage gate, no --strict-markers, no lockfile ⇒ CI is neither reproducible nor strict. | ruff + type check + a coverage floor + a lockfile. |
| AUD-478 | P2 | 	ests/test_resolve_fallback_budget.py | The test asserts against its **own re-implementation** of the guard, never the shipped code. | Import the real function. |
| AUD-479 | P2 | 	ests/test_frontend_js.py, 	ests/test_frontend_css_wiring.py | The two "frontend wiring" suites are **greps over the source text** — they cannot catch a behavioural frontend regression. | Add a DOM harness. |
| AUD-480 | P2 | 	ests/test_lyrics_performance.py:162, :180 | Absolute wall-clock thresholds (ssert elapsed < .5) fail on a slow machine; 	est_api_search.py:20 hard-codes 5.0 s against a production 6.0 s budget; 	est_taste_profile.py:104 mixes local and UTC datetime.now(). | Inject the clock; move latency budgets to 	ools/bench/. |
| AUD-481 | P2 | 	ests/test_recommendation_ui.py:18-23, 	est_proxy_harness.py, 	est_player_resources.py, 	est_provider_loading.py | Shared harnesses live in **test modules**, not conftest.py — 25 cross-test-module imports fix pytest's evaluation order. | Move them to 	ests/jsdom.py + 	ests/helpers.py. |
| AUD-482 | P2 | services/base_service.py:124-133, core/api.py:99-102 | Process-global caches (_stream_cache, _search_cache, _executor, _ssrf_cache) leak across test files; only 4 files isolate them. | An autouse snapshot/restore fixture. |
| AUD-483 | P2 | services/yandex_service.py, core/services/recommendation.py | Zero coverage: Yandex is only ever a stub; core/services/recommendation.py has **no Python importer anywhere**. | Add a test; wire or delete the orphan. |
| AUD-484 | P3 | 	ests/test_keybind_contracts.py:131-134 | A test writes two scratch files into the repo tree (	ests/) — removed in inally but not gitignored. | Write into 	mp_path. |
| AUD-485 | P3 | 	ests/benchmark_lyrics_cache.py, equirements-dev.txt:2 | The benchmark file is never collected; pytest-asyncio has zero users and no syncio_mode, so an added sync def test_* would silently not run. | Move it to 	ools/bench/; drop the dep. |
| AUD-486 | P3 | 	ests/test_frontend_js.py:1-8 | The file claims the frontend has no runtime harness (false — 20 files execute JS); it only does 
ode --check. | Correct the docstring. |
| AUD-487 | P3 | 	ests/conftest.py:97-101 | AppApi.cleanup() is never called ⇒ the pi fixture leaks two thread pools per test. | Call cleanup() in the teardown. |
| AUD-488 | P3 | 	ools/bench/import_chains.py:29, uild_hotspots.py:29-30 | 	ools/bench is put on sys.path ⇒ it shadows the stdlib profile module — the exact hazard un_pyprof.py documents. | Fix the path. |
| AUD-489 | P3 | 	ools/bench/bench_child.py:308 vs :323-326 | The event recorder is installed **before** Page.reload() ⇒ window.__bench is destroyed and the eed scenario's wall_ms is a harness timeout constant, not a measurement. | Install after the reload. |
| AUD-490 | P3 | 	ools/bench/run_pyprof.py:135-150 | The import-graph resolver mis-links packages to their own submodules (the ancestry is printed backwards). | Fix the resolver. |
| AUD-491 | P3 | 	ools/bench/run_bench.py:246-248 | --list omits idle_states and cpu_attribution (argparse accepts 8). | Sync the list. |
| AUD-492 | P3 | 	ools/bench/cdp.py:107-136 | The pong is written from the receive thread with no write lock ⇒ possible frame interleaving. | Lock the writes. |
| AUD-493 | P3 | 	ools/visual_guard/fixtures.py:277-336 | No cross-machine determinism (system fonts, no hinting/GPU flags) plus uncommitted goldens. | A machine manifest. |
| AUD-494 | P3 | 	ools/bench/{css_inventory,dom_nesting,js_census}.py, un_guard.py | 6 tools write into the repo tree; un_guard --capture mtrees the goldens. | Write outside the repo. |
| AUD-495 | P3 | setup_pyinstaller.spec:27 + ssets/backgrounds/*.jpg | 8.85 MB of 1600-px wallpapers + a 1.42 MB PNG backdrop ship in the installer (10.64 MB of imagery); 15.4 MB of decoded bitmap per portrait. | WebP derivatives + thumbnails. |
| AUD-496 | P3 | setup_pyinstaller.spec:27 + ssets/theme-previews/*.png + ssets/logo.png | 634 KB of dead imagery ships (the PNGs are unreachable, the logo unreferenced). | Prune. |
| AUD-497 | P3 | setup_pyinstaller.spec:27 | icon.ico is not in datas ⇒ the runtime .ico lookups fail in the frozen exe (no window icon). | Ship it. |
| AUD-498 | P3 | setup_pyinstaller.spec:27-30 | zapret/in are bundled only if they exist relative to the process CWD ⇒ the build is CWD-dependent and neither is shipped. | A manifest with existence assertions. |
| AUD-499 | P3 | setup_pyinstaller.spec:100-101, installer.iss | Nothing is code-signed, and the upx mitigation for AV heuristics was "do not compress" rather than "sign" — for a binary that handles OAuth tokens and launches an elevated process. | Sign the installer. |
| AUD-500 | P3 | installer.iss:6-28, :61-65 | No AppId, no AppMutex, and a blanket [UninstallDelete] filesandordirs over {app}. | Add the identity; narrow the delete. |
| AUD-501 | P3 | equirements.txt:5-9, :14 | yt-dlp[default] is uncapped despite the header's policy, and curl_cffi permits versions yt-dlp's own extra excludes; there is no lockfile or hash ⇒ the installed set is not the tested set. | Lock + hash. |
| AUD-502 | P3 | equirements.txt | ottle is imported directly but undeclared (it arrives transitively via pywebview). | Declare it. |
| AUD-503 | P3 | equirements.txt:18, core/tray.py:16 | pystray>=0.19.5 admits 0.19.5, which has **no** Separator ⇒ the tray import fails and HAS_PYSTRAY is False forever. | Raise the floor. |
| AUD-504 | P3 | equirements.txt:10-14 + setup_pyinstaller.spec:27 | curl_cffi's native DLL is never collected by the spec ⇒ the packaged SoundCloud/impersonation path cannot load it — exactly the failure the requirements comment says must not happen. | Add the DLL to datas/inaries. |
| AUD-505 | P3 | main.py:199-223 | The DoH fallback is inert whenever a proxy is configured (urlopen uses the proxy, whose hostname lookup re-enters the patched resolver). | Resolve the proxy host directly. |
| AUD-506 | P3 | main.py:180-223 | A failed DNS lookup blocks the calling thread ~6 s (3 × 2 s) inside a 6 s bridge budget. | Cache the negative result. |
| AUD-507 | P3 | main.py:167, :195-198 | The DoH re-entrancy guard is a 	hreading.local ⇒ N concurrent failures make 3N parallel DoH requests (measured 13.7 s per failed resolution). | A process-wide lock / per-host in-flight map. |
| AUD-508 | P3 | main.py:212-217 | The DoH cache evicts by insertion position, so a refreshed entry is evicted first. | Move it to the end on refresh. |
| AUD-509 | P3 | main.py:454-464 | The 404 safety net returns the PNG **with** a 404 status ⇒ the browser still treats the image as broken. | Return 200. |
| AUD-510 | P3 | main.py:330, :571 | Bootstrap/shutdown failures are reported with print(), a no-op in the console=False build ⇒ they never reach the log. | Use the logger. |
| AUD-511 | P3 | main.py:74-75, :85-86, :475-476 | Three bottle-layer failures are logged at logging.debug while the root logger is at INFO ⇒ invisible. | Log at warning. |
| AUD-512 | P3 | main.py:557-580 | The session is persisted only on the window-close path — no signal/atexit handler — so a kill loses the queue and position. | Also save on minimise. |
| AUD-513 | P3 | main.py:260 | The instance mutex is Local\-scoped (per session, not per user) ⇒ two sessions of one user run two instances. | Use a per-user namespace. |
| AUD-514 | P3 | installer.iss:48, :68-75 | The installer forces Russian text on every language, including the English one it declares. | Localise. |

---


### 5.6 Recommendations and the taste profile (WN-23, WX-08)

| ID | Pri | Location | Defect | Fix |
|---|---|---|---|---|
| AUD-523 | P2 | services/recommendation_service.py:354-355, :398-400, :477-478; core/api.py:3747 | A provider outage is indistinguishable from "the user has no taste": the error string is discarded, the section is hidden, and an **empty** candidate set is never negatively cached — so every home load re-runs the full fan-out. Measured: 3 home loads ⇒ 3 provider calls each. | Cache the empty result briefly; surface the provider error. |
| AUD-524 | P2 | core/api.py:3138-3154, utils/cache_manager.py:22-29 | There is **no way to erase the taste signal**: clear_storage("all") deletes the audio but leaves the profile, the stale is_downloaded/ile_path, and ~/.nedotify/cache/lastfm_cache.db; there is no DELETE FROM history anywhere in the desktop tree except the track-delete CASCADE. | A separately-confirmed "clear my listening history" that removes history, play_count/last_played, listening_stats and session.last_queue. |
| AUD-525 | P2 | core/api.py:4119 → services/recommendation_service.py:914 | get_flow_tracks runs the **whole** candidate collection inline on the js_api thread (≤12 s), unlike every other recommendation entry point which uses the async path. | Route it through the same async helper. |
| AUD-526 | P2 | services/taste_profile.py:269-273 vs core/database.py:1708, 1695, 1784, 1616, 1241; core/api.py:3761, 3770, 3742, 3784 | **Four** definitions of "top artist" and **three** of "recently played" feed the same home page — and the shapes disagree, which strips completed / listening_measured / media_listened / session_finished from the 50 newest rows (the root cause behind AUD-269). | One aggregation, one row shape, consumed by every consumer. |
| AUD-527 | P3 | services/recommendation_service.py:498-499, :514-517, :385-387 | Last.fm receives the user's **username** plus their recent artist/title pairs, with no disclosure in the UI (the no-key path short-circuits, so it only happens when a key is configured). | Disclose the provider in the settings. |
| AUD-528 | P3 | services/recommendation_service.py:651, :723 vs :174 | get_custom_artists and get_smart_home_feed build the profile **without settings**, so the user's alias table is dropped and the track key no longer matches (('moekt','t') vs ('моект','t')). | Pass the settings through. |
| AUD-529 | P3 | services/recommendation_service.py:454-466 | The feed cache key is a **400 KiB epr()** of the track signature plus a SHA-256, rebuilt on every call (measured 5.04 ms for 4 570 tracks). | Hash the signature incrementally; cache it per revision. |
| AUD-530 | P3 | services/taste_profile.py:387, :390 | The profile memo deep-copies the profile **twice** under one process-global lock (measured 6.81 ms per copy at 6 000 rows) ⇒ ~14 ms serialised per build. | Copy once, or hand out a read-only view. |
| AUD-531 | P2 | services/taste_profile.py:368 + core/database.py:155 | The 60 s profile memo embeds the caller's own Connection in the revision key, and the connections are thread-local — so the memo **never hits across threads**. Measured: same thread 0 SELECTs, a fresh thread 7 SELECTs; one home load = **3 builds, 3 misses, 21 SELECTs**. | Drop the connection from the revision; key on settings.revision + db.data_revision. |
| AUD-532 | P2 | services/recommendation_service.py:148, :159, :211-217 | The alias table is rebuilt **per candidate and per favourite** — O(candidates × favourites) × O(bindings). Measured: 274 rebuilds for 50 candidates; **53 274 rebuilds and 203 ms** with 1 000 favourites; 88 ms with 200 bindings. | Cache the alias table per settings revision. |
| AUD-533 | P2 | core/database.py:158, :199-200 + webview/util.py:308 | The recommendation path opens a SQLite connection **per throwaway bridge thread** and never closes it (pywebview runs one thread per js_api call). Measured: 50 bridge calls ⇒ 51 live connections, surviving gc.collect(). | A connection pool, or close-on-return for the bridge. |
| AUD-534 | P3 | core/services/recommendation.py:35-45, :160-176 | The orphaned second scoring engine uses a **different model** (pm/energy/mood/coustics/ass) and hard-coded fake artists — so a reader who trusts the file name is misled about what the app actually scores. | Delete it (AUD-272). |

---
## 6. Cross-Module Findings

These defects span two or more components and could not be found by reviewing any single file. Each was surfaced by the scenario reviewers (WX-01…WX-12) and cross-confirmed where possible by the area reviewers.

### X-01 · P1 · CONFIRMED — The play path bypasses the resolver, so its guarantees do not apply
**Components:** core/api.py::_resolve_track → core/app.py::re_resolve_stream_url_async → provider → core/resolver.py::resolve → core/proxy.py.
StreamResolver advertises a single-flight and a negative cache ("skip known-dead track"), and core/resolver.py:7-8 claims it for all callers. But esolver.resolve() is reached **only** from udio/engine.py:149 (the proxy path). The path the user drives — core/api.py:1604/1744 → core/app.py:296-506 — calls the provider **directly** and only writes back through esolver.refresh() afterwards. Consequences: a dead/DRM track re-runs the whole cascade on every click; the negative memo never applies to playback; and the frontend, seeing the absence of stream_url, fires a **second** resolution chain (one click ⇒ two cascades). 	ests/test_resolver_state.py:152 therefore gives false confidence — it pins a path the user never takes.
**Consequence:** the resolver's central promise is enforced nowhere the user can reach.
**Fix:** make StreamResolver.resolve() the only resolution front door, with the callback shape the bridge already expects.

### X-02 · P1 · CONFIRMED — The queue is copied between the frontend and the backend and the copy wins
**Components:** js/queue.js ↔ core/api.py::play_track ↔ udio/queue.py.
js/queue.js keeps its own window.currentQueue. 	oggle_shuffle emits only shuffle_changed, never queue_updated, although the backend permutes _tracks in place. The drawer therefore shows the pre-shuffle order, and any subsequent play_track(track, currentQueue, index) sends the **stale copy** back, overwriting the backend queue (udio/engine.py:41-47 → queue.set_tracks) and re-randomising the shuffle. The same pattern loses dd_to_queue / eorder_queue edits whenever a play_track lands in between.
**Consequence:** the frontend can silently overwrite backend queue state; the two copies cannot be reconciled.
**Fix:** the backend owns the queue; the frontend holds a read-only view model and never sends a queue snapshot back.

### X-03 · P1 · CONFIRMED — A "settings" round trip exists for three different shapes of the same tree
**Components:** core/settings.py::DEFAULT_SETTINGS → core/api.py::get_settings → js/main.js::applySettings → js/player.js, js/utils.js, js/feature-controls.js.
get_settings() returns a **category-keyed** tree, but three consumers read the **top level**: js/player.js:1981-1984 reads settings.shuffle / settings.repeat (which live under session), js/player.js:1987 reads settings.volume (which lives under udio), and js/feature-controls.js:112 reads window.settings?.network?.offline_mode (the 
etwork category is missing from the hard-coded list at core/api.py:2929). The result: the volume is never restored (it always returns to the hard-coded 70), the repeat button is **permanently lit**, the shuffle button is never lit, and offline mode is invisible to the UI after a restart.
**Consequence:** the same class of defect — "the control exists but nothing happens" — is present in three places, from one root cause: the settings tree's shape is declared in four places (DEFAULT_SETTINGS, the get_settings() list, the JS accessors, the localStorage mirror) and nothing validates that they agree.
**Fix:** derive the transport from DEFAULT_SETTINGS; add a contract test that every UI accessor resolves.

### X-04 · P1 · CONFIRMED — "Download complete" is announced with an id the frontend cannot match
**Components:** core/downloader.py → core/api.py::download_track → js/events.js → js/utils.js.
download_complete carries {'track_id': <int>} — the **database row id**. But a row produced by a provider has no database row: core/api.py:2319 skips dd_track when the payload carries a synthetic provider id ("yt_abc123", "spotify_123"). The frontend matches the event against dataset.trackSourceId / _trackData.id — a **provider** id. The match fails, the download spinner never clears, and the file lands in ~/.nedotify/downloads/ as an orphan that no library row points at. mark_track_downloaded then executes UPDATE tracks … WHERE id='spotify_123' against an INTEGER PRIMARY KEY — **0 rows updated, silently**.
**Consequence:** downloading any track found in Search or in an album modal costs the user's bandwidth and produces a file the app cannot find, while the UI reports success.
**Fix:** distinguish the provider id from the row id; always create the row before enqueueing; make the event carry both ids.

### X-05 · P1 · CONFIRMED — Two implementations of the stream cache with different rules, one of which deletes the user's favourites
**Components:** utils/cache_manager.py::purge_stream_cache ↔ core/api.py::_clean_stream_cache ↔ core/database.py::cached_streams.
purge_stream_cache honours the user's storage.cache_quota_gb, protects is_downloaded = 1 OR is_favorite = 1, and syncs the DB (UPDATE stream_cache SET cached_file_path = NULL). _clean_stream_cache (invoked automatically from prefetch_track every ≥10 min) uses a hard-coded 350 MB / 48 h policy, protects **nothing**, and does **not** sync the DB. Verified: a favourite's cached file is deleted by _clean_stream_cache while purge_stream_cache correctly refuses to touch it; the DB row then points at a file that no longer exists, and because set_cached_file sets expires_at = NULL, the row never expires.
**Consequence:** the user's cache quota is not honoured, favourite downloads are silently re-downloaded, and the DB accumulates permanent dangling paths that core/offline.py re-scans on every listing.
**Fix:** one owner (CacheManager) for the cache policy; delete _clean_stream_cache.

### X-06 · P1 · CONFIRMED — The offline promise is enforced at 41 call sites instead of at the boundary
**Components:** core/settings.py → core/offline.py::is_offline → 41 checks in 6 Python files + 4 JS gates + a method-name allow-list in the bridge.
The flag is read correctly (
etwork.offline_mode — writer and reader agree), but the policy is a **scattered boolean**. The bridge interception list (core/api.py:461-512) is a name allow-list whose **default is ALLOW** (eturn False, None at :512), so a new network-touching method is online by default. Two omissions were found: get_lyrics and get_waveform still make outbound requests while offline, and the proxy's /?url= branch (the production path for every CDN stream) has **no** offline gate — verified: with offline ON, /api/stream correctly returned 503 with zero outbound attempts while /?url= performed the upstream fetch.
**Consequence:** the one mode where the user explicitly asked for no network still uses it, and the app contradicts itself in the same request.
**Fix:** one NetworkPolicy consulted at the two real choke points (the proxy's request builder and StreamResolver.resolve); invert the bridge list to default-DENY.

### X-07 · P1 · CONFIRMED — The restart handshake is fire-and-forget, and the first events are the ones lost
**Components:** main.py::on_loaded → core/api.py::_emit → js/events.js → js/main.js::initEvents.
main.py:389-402 emits 	rack_changed and session_autoplay from the loaded event. js/events.js:50-56 **drops** every event while coreEventHandler is null, and the handler is installed only inside initEvents() (js/main.js:528) — which runs **after** an awaited equestIdleCallback(..., {timeout: 300}) for the Icons module. pywebview fires loaded right after inish.js dispatches pywebviewready — the very event that starts init(). There is no compensating pull path.
**Consequence:** on every cold start with a saved session, the queue is restored but **the player is empty and the saved position is lost** — with no error and no log line.
**Fix:** a readiness handshake (ui_ready()) or a pull-based get_state().

### X-08 · P1 · CONFIRMED — A hardcoded HTTP port plus wildcard CORS is the whole bridge's authentication model
**Components:** main.py:555 → pywebview/http.py → core/api.py::_emit.
webview.start(http_server=True, private_mode=False) with no http_port pins pywebview's server to DEFAULT_HTTP_PORT = 42001 and sets Access-Control-Allow-Origin: * on every response, including the /js_api/<uuid> bridge endpoint. Windows SO_REUSEADDR lets a second process bind the same port, and server.running = True is set **without checking the bind**. A process that binds 42001 first serves its own page into the app's privileged pywebview WebView.
**Consequence:** the bridge's whole 174-method surface is reachable by anything that can reach the port, and the app can be bricked by a local port squatter.
**Fix:** an app-chosen random port (assert the bind), and an origin-pinned CORS policy.

### X-09 · P1 · CONFIRMED — Three lyric caches with three identities, so the frontend believes it has lyrics the backend will re-fetch
**Components:** js/lyrics.js (frontend key) ↔ services/lyrics_lookup.py:257 (backend key) ↔ services/lyrics_cache.py (SHA-256 key).
The frontend keys on title/artist/album/path; the backend adds duration, version and mtime; the disk cache hashes the backend key. The frontend therefore reports "we have the lyrics" for a track the backend will look up again. Separately, the duration-refinement path issues a **second, uncached** cascade (duration is part of the identity) — measured 2 bridge calls and 2 provider invocations per track.
**Consequence:** up to 27 third-party requests per track, and a UI that shows stale lyrics.
**Fix:** one identity, shared by the frontend and the backend.

### X-10 · P1 · CONFIRMED — The "same song" identity is defined four times, and one definition is a YouTube search string
**Components:** js/search.js:320 ↔ js/library.js:511 ↔ services/track_resolver.py _memo_key ↔ services/catalog_service.py similarity ↔ services/spotify_service.py:50.
The "spotify" provider's source_id is "ytsearch1: {artist} - {title}" — a YouTube *search expression*, not an id. Two different Apple releases of the same artist/title therefore share one id, and the frontend's dedup key (source::source_id) makes one row silently disappear; isSameTrack then matches the wrong "now playing" row.
**Consequence:** tracks vanish from search results, and the wrong track can be shown as playing.
**Fix:** one canonical identity helper in services/music_matching.py.

### X-11 · P2 · CONFIRMED — The loudness pipeline measures nothing the user owns
**Components:** services/lufs_scanner.py → core/database.py::tracks.loudness_lufs → js/player.js:725-729 → the ReplayGain gain.
The scanner selects WHERE source='local', but core/database.py::mark_track_downloaded **never changes source** — a downloaded track keeps its provider source and is never analysed. So the ReplayGain feature never applies to the user's actual library. The same blind spot hides the duplicate finder (services/audio_fingerprint_service.py:71), and a fabricated measurement (a missing file ⇒ lufs = 0.0 ⇒ the track plays 14 dB too quiet) is written as if measured.
**Consequence:** a user-facing feature is inert on exactly the files it was built for.
**Fix:** select on "has a local file", not on source.

### X-12 · P2 · CONFIRMED — The proxy's own self-heal invalidates one cache and not the one it reads
**Components:** core/proxy.py:1022-1090 → core/resolver.py::invalidate ↔ services/base_service.py::_stream_cache.
On an upstream 403/410 the proxy re-resolves and writes the new URL into the resolver's memory and DB caches, but the provider's own 6-hour _stream_cache — which is the cache get_stream_url actually reads — still holds the dead URL. The next attempt therefore re-fetches the same dead URL, and only the frontend's recovery path clears it.
**Consequence:** the self-heal does not self-heal; the user must press play again.
**Fix:** one stream-URL artifact with one owner.

### X-13 · P2 · CONFIRMED — The listening history has two incompatible definitions and one of them is fabricated
**Components:** core/database.py::get_wrapped_stats ↔ services/listening_comparison.py → js/profile.js ↔ js/home.js.
get_wrapped_stats credits a zero-duration history row with the **full track length** (or a fabricated 180 s); listening_comparison excludes those rows entirely. Measured on two rows: Wrapped = 2 plays / 410 s, Comparison = 1 play / 200 s. The Home badge shows the inflated number; the comparison panel shows the honest one. A third inconsistency: completed is decided on accumulated *media* seconds, so a 40-second intro looped on a 180-second track counts as a complete play and is weighted as one in the taste profile.
**Consequence:** two screens on the same page disagree about the same week.
**Fix:** one definition in the data layer, consumed by every consumer.

### X-14 · P2 · CONFIRMED — The provider pool that serves search also serves playback, so a search burst stalls the Play button
**Components:** services/youtube_service.py:195 (search + extract) ↔ services/soundcloud_service.py:132 ↔ core/api.py::search.
The provider pools are shared between the search fan-out and the stream extraction. The bridge's deadline stops the **UI** waiting but never cancels the provider task, so the worker stays busy for the provider's own timeout (up to ~30 s for SoundCloud's yt-dlp). Measured: with 10 stuck searches on a 10-worker pool, the extraction task started at **+11.8 s**.
**Consequence:** pressing Play during a search burst hangs for tens of seconds with no error.
**Fix:** separate pools, or a reserved lane for playback.

### X-15 · P2 · CONFIRMED — "Clear storage" has two meanings and the destructive one has no path containment
**Components:** core/api.py::clear_storage → core/api.py::_delete_downloaded_files → core/database.py::tracks.file_path → utils/file_scanner.py::_import_file.
clear_storage("all") unlinks every 	racks.file_path with is_downloaded = 1 and **no root check**. A locally imported track (a title+artist collision sets is_downloaded = 1 and stores the real path) therefore has a file in the user's own music folder deleted. Verified against a real DB: the file was gone and the row still said is_downloaded = 1. The DB rows are never updated, so the library keeps listing tracks whose files no longer exist, and the auto-download path then refuses to re-fetch them ("все любимые треки уже скачаны").
**Consequence:** the user's own media, outside the app's library, is destroyed with no confirmation and no record. No UI caller exists today, which is the only reason this is not P0.
**Fix:** restrict deletion to ~/.nedotify/downloads, update the rows in the same transaction, and require an explicit confirmation.

---

## 7. Security & Performance

### 7.1 Security

The codebase has real security instincts and several of them hold. The audit's security findings are concentrated in **five** places.

#### What is done right (verified)

| Control | Where | Verdict |
|---|---|---|
| Loopback proxy auth token | core/proxy.py:1275, :491-511 | 192-bit secrets.token_urlsafe, per-start regeneration, memory-only (never in the DB), hmac.compare_digest, **fail-closed**, redacted in the access log. |
| Local-file disclosure | core/proxy.py:238-272, :183-206 | Traversal, double-decoding (%252e%252e%252f), absolute-outside, drive-relative, \\?\, UNC, ile://, trailing dot/space, NTFS ADS, reserved names (NUL.mp3, COM1.mp3) and 8.3 aliases are **all** refused. Containment on ealpath of **both** sides. |
| SSRF literals | core/api.py:175-191 | 127.0.0.1, 169.254.169.254, [::1], localhost,  .0.0.0, decimal 2130706433, [::ffff:127.0.0.1] and RFC1918 are blocked. |
| Redirect chain | core/proxy.py:379-387 | Every hop is re-validated and credentials are stripped on a cross-host change. |
| Credential scoping | core/proxy.py:60-99 | A dot-anchored suffix test; provider cookies are withheld for foreign hosts. |
| Provider credential containment | core/proxy.py:859, :965 | The loopback token and the browser's Cookie/Authorization/Referer are never forwarded upstream. |
| SQL injection | core/database.py:55-70, :1349-1404 | ORDER BY and update columns are allow-listed; LIKE escaping is correct (%, _, \ + ESCAPE '\'). The **smart-playlist** rule builder was probed with {"artist":"Robert'); DROP TABLE tracks;--"} and correctly bound. |
| XSS in the shared helpers | ui/web_new_v2/js/utils.js:17-25, :40-50 | escapeHtml is applied at every HTML sink in the reviewed modules; safeCssImageUrl restricts to https:/data: and strips '"();\ — a CSS-url() breakout, which HTML escaping does not prevent. |
| XSS in lyrics / artist bio | js/lyrics.js:953-1013, js/artist_profile.js:405 | Third-party text is written with 	extContent only; every innerHTML in those modules carries a literal. |
| CSP | index.html:10 | script-src 'self', object-src 'none' — and it actually **blocks** the 7 inline onerror handlers (which is why AUD-418 exists). |
| Proxy body handling | core/proxy.py:562-588 | Bodies are streamed (32 KB upstream, copyfileobj/8 KB local); the HLS manifest is capped at 2 MiB. |
| WebView2 origin | js/player.js:83-85 | crossOrigin="anonymous" is set before any src; the proxy sends loopback CORS and Range headers. |
| Lyrics cache key | services/lyrics_cache.py:31-36 | A SHA-256 hex in a SQLite TEXT PRIMARY KEY — no raw title ever reaches a filename (contract #8 is satisfied there, unlike Yandex's legacy branch). |

#### Security defects

**S-1 · The SSRF guard fails open (AUD-004, P1).** core/api.py:143-158 defaults the verdict to *safe* and only downgrades it for four literal prefixes when DNS fails. main.py's process-wide getaddrinfo patch raises gaierror after three 2-second timeouts, so **a DNS outage makes every hostname pass the guard** — and the wrong verdict is cached for 120 seconds. Combined with **S-2** (the resolved IP is never pinned), a DNS-rebinding server defeats the guard entirely.

**S-2 · No IP pinning (AUD-005, P1).** The check resolves and discards the addresses; the fetch resolves again. The connection therefore never reaches a validated address.

**S-3 · Two divergent SSRF policies (AUD-352, P3 / X-06).** utils/url_safety.is_safe_media_url fails **closed** and is used by the engine and the downloader. core/api.py::_is_ssrf_safe_url fails **open** and is used by the bridge and the proxy — and core/proxy.py:23 imports the whole 4 228-line bridge module for one boolean, inverting the layering.

**S-4 · The proxy's local-file resolver does not refuse UNC paths (AUD-180, P2).** core/proxy.py:201 calls os.path.realpath() on a UNC path before the guard at :253-255 runs ⇒ a **~21 s** SMB block per request, during which the user's NTLM challenge is offered to the remote host. The other resolver refuses in 0.00 s.

**S-5 · TLS verification is disabled on the provider media path (AUD-225, AUD-319, P2).** 
ocheckcertificate: True is set in services/youtube_service.py:308, services/soundcloud_service.py:247,276, services/vk_service.py:63 and utils/cache_manager.py:352 — it applies to the **media bytes**, not just the page. A MITM can substitute the audio, which is then cached for 6 hours and written into the user's library.

**S-6 · yt-dlp writes the user's entire browser cookie jar to disk (AUD-224, P1).** services/youtube_service.py:352-358 sets both cookiefile and cookiesfrombrowser on the same YoutubeDL. yt-dlp merges the two jars and close() → save_cookies() writes **every** cookie to the user's file. Reproduced: a ank_session cookie for an unrelated domain appeared in cookies.txt.

**S-7 · The proxy bearer token is exposed in the DOM and in the console (AUD-010, P1).** The token travels in the k= query parameter, which is written into live <img src> attributes (one per queue row) and printed by js/events.js:74 on every event. The token alone unlocks the whole proxy.

**S-8 · Secrets are stored and mirrored in cleartext (AUD-391, AUD-119, P2).** The Yandex OAuth token is written to the SQLite settings table in plaintext, returned to the WebView, and mirrored into WebView2 localStorage by js/settings.js:1040. uth.proxy_url (which may embed user:pass@) is returned verbatim, shown in an unmasked input, and cached in localStorage; uth.lastfm_api_key is not masked at all. core/database.py has **no encryption layer whatsoever**.

**S-9 · Secrets reach the log (AUD-220, AUD-118, P2).** services/base_service.py:57-61 logs a rejected proxy URL **with its credentials**; core/api.py:428-441 writes raw str(exc) to ~/.nedotify/logs/app.log — the file users attach to bug reports; services/lastfm_service.py:214 logs a key prefix.

**S-10 · The proxy's Set-Cookie is planted on the app's own origin (AUD-188, P2).** Upstream headers are forwarded verbatim, so a malicious upstream can set a host-only cookie for 127.0.0.1 — which is **not** port-scoped, so it is also sent to the app's own Bottle origin.

**S-11 · The elevated updater executes an unverified binary from a user-writable directory (AUD-016, AUD-311, P1).** _verify_zip_sha256(b"", "") returns True; the expected hash exists only for the pinned release, so every newer release is installed unverified and launched with ShellExecuteW("runas") from ~/.nedotify/zapret (user-writable, holding winws.exe, WinDivert.dll and a kernel driver).

**S-12 · The bridge has no capability model (AUD-107, AUD-138, P3).** pywebview publishes all 174 public methods, including clear_storage, delete_playlist, open_external_url and emit_event — and emit_event lets any script in the WebView spoof download_complete/	rack_changed. The CSP is the only barrier.

**S-13 · Untrusted input reaches the filesystem and the DB (AUD-282, P3).** update_track_tags copies an arbitrary client-supplied path into ~/.nedotify/covers/<id>.jpg (a .pdf was copied byte-for-byte) with no root, extension or size check.

**S-14 · write_tags corrupts the user's only copy of a file on a crash (AUD-301, P1).** mutagen rewrites in place (insert_bytes + .write); the docstring's "atomic" claim is false and the %TEMP% backup is never restored.

#### Privacy

| Store | Contents | Erasable? |
|---|---|---|
| history (plaintext SQLite) | one row per play: track_id, timestamp, duration, completion, recommendation context | **No** — no clear_history bridge method; clear_storage touches no table |
| 	racks.is_favorite / play_count / last_played | a listening fingerprint | Only by deleting the track (CASCADE) |
| settings.session.last_queue | up to 200 tracks with title/artist | Only via a settings reset |
| listening_stats | duration_ms — the table exists and is **never written** | n/a |
| ~/.nedotify/logs/app.log | every played **title**, plus credentials (S-9) | By log rotation only |
| Third-party egress | up to 5 lyric providers on **every** track change (AUD-260); the user's title/artist/album/duration; the whole lyric text sent to Google on every translation (AUD-266); the search query sent to Apple and SoundCloud | No opt-out exists |

**Net assessment.** The *architecture* of the security model is sound (capability-scoped proxy, fail-closed token, real path containment, parameter-bound SQL, 	extContent discipline in the lyrics and artist modules). The *failures* are concentrated in three habits: (a) the SSRF guard fails open, (b) secrets are handled as ordinary settings, and (c) "verify before you trust" is applied to the proxy's file paths but not to the providers' URLs, the update path, or the tag writer.

### 7.2 Performance

#### Measured hot spots

| Hot path | Measurement | Where |
|---|---|---|
| The profile "compare periods" query | **467 s** at 120 k history rows; 83 s at 50 k; 34 s at 30 k | services/listening_comparison.py:56-66 — a correlated NOT EXISTS subquery per outer row |
| The LUFS decode | +424 MB RSS for a 5-minute file; **+4.7 GiB** for an hour (32 B/frame) | services/lufs_scanner.py:16-35 |
| The library listing | the whole 	racks table, SELECT *, no LIMIT — 3 MB at 4 000 tracks, re-read **5–8 times per completed download** | core/api.py:2267-2271, js/events.js:258-263 |
| The queue_updated payload | 17.5 KiB @ 50 tracks → **347 KiB @ 1 000**, injected as JS source | core/api.py:1430-1435 |
| A search fan-out | 4 providers, **parallel** (measured max, not sum), but **no total budget** — search_completed waits for the slowest (6–8 s) and the timed-out provider's work is not cancelled | core/api.py:2119-2208 |
| A provider burst | 10 stuck searches on a 10-worker pool ⇒ the playback extraction starts at **+11.8 s** | services/youtube_service.py:195 |
| The proxy | ~4.8 ms of SSL-context rebuild **per request** (a new uild_opener() each time), no connection reuse ⇒ 60–120 handshakes per HLS track | core/proxy.py:390-393 |
| The proxy's thread model | one thread per connection, **no socket timeout** ⇒ 50 silent sockets pinned 50 threads forever | core/proxy.py:421-446 |
| The listening telemetry | 720 durable SQLite commits + 720 blocking UI-thread round trips per hour of playback (~3 MB WAL/hour) | core/api.py:1407-1428 |
| The taste profile | the 60 s memo **never hits** across threads (the revision embeds a thread-local connection); 6 180 alias-table rebuilds per ranking | services/taste_profile.py:357-371 |
| The iTunes gateway | a global 3.5 s single-slot throttle, shared with the album catalogue ⇒ 3.5 s of the 6 s provider budget can be consumed by an unrelated call | services/itunes_gateway.py:21-64 |
| The frontend progress loop | 3 forced style recalcs + 3 uncached getElementById **per frame** (≈90 forced recalcs/s) | js/player.js:1416, :2296-2303 |
| The particle canvas | a full-viewport ilter: blur(8px) on a container repainted at 24–30 fps ⇒ 8.3 Mpx of Gaussian blur per frame | css/components/base.css:1729 |
| The CSS payload | 25 render-blocking stylesheets, 427 KB, 
o-cache; ~162 KB is per-view and deferrable | index.html:17-50 |
| The shipped imagery | 10.64 MB in the installer (8.85 MB of 1600-px wallpapers + a 1.42 MB PNG backdrop); 634 KB of it is unreachable | setup_pyinstaller.spec:27 |

#### The systemic cause

**Almost every performance defect is a missing bound rather than a slow algorithm.** The recurring patterns are:

1. **Unbounded collections** — the whole 	racks table, the whole history table, the whole stream_cache table, an unbounded settings blob, an unbounded rtist_aliases map, an unbounded history table.
2. **Unbounded work per event** — every download re-reads the library 5–8 times; every track change fans out to 5 lyric providers; every keystroke starts a 4-provider fan-out.
3. **Unbounded concurrency** — one thread per proxy connection, one thread per bridge call, one thread per download, one provider pool shared by search and playback.
4. **Missing projections** — SELECT * (including metadata_json and absolute file paths) shipped to the WebView for a UI that reads ~8 of the 28 columns.

The database is the sharpest example: core/database.py has correct WAL, usy_timeout, oreign_keys and an RLock, but almost every list query is a full scan, and get_wrapped_stats alone is 4 independent full scans of history, called with 'all' on every profile render.

#### What is fast enough

- **Byte-compilation**: all 194 Python files compile cleanly under Python 3.14.7.
- **The proxy's local-file serving**: MP3 seeking over a cached stream works (a second Range: bytes=1000- yields 206 bytes 1000-4999/5000 with zero upstream requests).
- **The resolver's memory cache**: bounded at 1 024 entries, a true LRU, the TTL is not extended by a hit.
- **The search fan-out**: genuinely parallel, with per-provider isolation — a raising provider does not abort the others.
- **The single-flight** in ase_service._join_request: correct, and it does hold the cache lock across a network call (verified 0.000 s acquisition during an in-flight request).
- **The SQL parameterisation** throughout core/database.py and services/smart_playlists.py.

---

## 8. Architecture Improvements

These are **not** defects — each is a change with no proven defect behind it. They are listed because each one would remove a whole *family* of the defects above, and several are prerequisites for the P0/P1 fixes in §11.

### 8.1 The five seams that matter most

**A-1 · One settings schema, one owner, one transport.** Today the settings tree is declared in four places — core/settings.py::DEFAULT_SETTINGS, the hard-coded category list at core/api.py:2929, the JS accessors in settings.js/player.js/eature-controls.js, and the localStorage mirror — and nothing checks that they agree. The result is already visible in three places (AUD-371, AUD-398, X-03). *Fix:* derive the transport from DEFAULT_SETTINGS; ship it as plain JSON so both sides read the same file; add a contract test that every UI accessor resolves to a real key. *Payoff:* removes the entire "the control exists but nothing happens" class and makes the hotkey mirror structural rather than a convention.

**A-2 · One resolution front door.** StreamResolver exists and is documented as the single-flight authority, but the user-facing path bypasses it (X-01), and three separate cascade implementations exist (udio/engine.py::_resolve_via_network ≈ 355 lines, core/app.py::re_resolve_stream_url_async ≈ 210, core/playback_recovery.py::recover_stream ≈ 89) with three different budgets. *Fix:* one esolve() owning the single-flight, the negative cache, the TTL and the persistence, with a callback shape the bridge already expects. *Payoff:* removes the stale-resolution race, the duplicate cascade, the "dead track re-resolved every click" behaviour and the three-budget inconsistency in one change.

**A-3 · One cache owner per cache.** The stream cache has three owners (AUD-292/293, X-05); the settings store has three writers (AUD-017); the lyrics cache has three identities (X-09); the download status vocabulary appears in four places with 62 string literals (X-02's contract table). *Fix:* a CacheManager that owns the stream cache; a SettingsFacade that owns the settings table; a DownloadContract module (status enum, event schemas, extension set, integrity gate) imported by every layer. *Payoff:* the "two implementations that disagree" family — which produced the favourites-deletion bug, the quota bug and the dangling-row bug — becomes structurally impossible.

**A-4 · One policy layer for offline and for the network.** 41 scattered if offline: checks in 6 Python files, 4 JS gates, and a bridge interception list whose default is ALLOW. Two omissions were found in the first pass (X-06). *Fix:* a NetworkPolicy with llow_remote(host, purpose), consulted at the two real choke points (the proxy's request builder and StreamResolver.resolve); invert the bridge list to a per-method capability attribute with default DENY. *Payoff:* "a new subsystem forgot to check offline" becomes impossible.

**A-5 · One shutdown owner.** The shutdown contract is split across main.py::on_closed, main.py::_startup_watchdog and core/app.py::AppCore.cleanup, with core/api.py::AppApi.cleanup skipped on the watchdog path and on every exception path (AUD-011). The teardown order is not the reverse of the construction order, and the DB is closed before the pools. *Fix:* one AppCore.shutdown(reason) running a declared, ordered teardown list (proxy → downloader → settings writer → watchdog → tray → Discord → zapret → executors → DB), called from every exit path, with the instance mutex released last. *Payoff:* the resource-leak family and the double-instance race both disappear.

### 8.2 The AppApi god object

core/api.py is 4 228 lines with **174 public methods**, all published to the WebView by pywebview. It owns: the bridge surface, the SSRF guard, the settings schema projection, the secret-masking policy, the offline interception table, the window-management state machine, the queue façade, the listening telemetry, the search coordinator, the lyrics orchestration and the storage accounting. No test ever constructs it (core/api.py:413-444 wraps every method in a per-instance closure, so monkeypatch.setattr(AppApi, ...) does not even affect a live instance).

*Fix:* split by capability — PlaybackBridge, LibraryBridge, SearchBridge, SettingsBridge, WindowBridge — behind one façade, and publish only the façade's public methods to the WebView. *Payoff:* the "which of the three settings methods is authoritative" question disappears, and the bridge surface becomes auditable.

### 8.3 Testability as an architectural property

The suite's weakness is not effort — it is that the architecture offers no seams:

- AppCore.__init__ hard-codes every collaborator (DatabaseManager(), LocalProxyManager(self), DiscordRPCService(...).start(), WatchdogService.start(), LufsScannerService.start(), a yt-dlp thread, a zapret updater). **No test ever calls it** — every test uses AppCore.__new__(AppCore) and hand-assigns attributes. The entire wiring is therefore untested, which is exactly where the cross-subsystem defects live.
- BaseMusicService has **no HTTP session at all**; every provider builds its own, so no test can inject a fake transport.
- The frontend has **five private hand-written fake DOMs** instead of one shared stub, so a DOM-contract change breaks three unrelated suites at once (the cause of the current 11 failures).

*Fix:* optional dependency injection on AppCore (a services dict with defaults), an injectable HTTP client on BaseMusicService, and one 	ests/jsdom.py shared by every JS test. *Payoff:* the seam tests that would have caught AUD-009, AUD-003 and AUD-011 become writable.

### 8.4 Frontend structure

- js/player.js (2 711 lines, ~19 responsibilities) and js/settings.js (3 388 lines) should be split. js/utils.js (1 690 lines, imported by 24 of 31 modules) mixes DOM builders, formatters, a modal focus trap, canvas/DPR, storage, multi-select, context menus and bridge wrappers.
- window.NeDotify is an **unowned global** that three modules merge into and main.js replaces — which is precisely why the floating-menu guard was silently destroyed (AUD-366). Replace it with ES imports.
- Seven copies of the .feed-card tile and seven render paths for a track row exist; a fix applied in one place silently misses the others (a concrete example: artist-profile rows are neither focusable nor Enter-activatable while library rows are, because the keydown handler lives in the two decorators rather than in the shared row builder).
- The frontend needs **one bridge façade** (js/bridge.js) plus an event-name constant table testable against core/api.py — the same idea as A-1, for events.
- js/efficiency.js needs a "view owns its animations" contract so the particles canvas, the visualizer and the orbit glow park when a view is not visible (the orbit glow currently runs at 30 Hz in mini mode, writing CSS variables into display:none elements — AUD-451).

### 8.5 Data layer

- core/database.py is a 2 489-line god class with a public conn; five modules bypass it and write outside the lock (core/downloader.py:276+, utils/cache_manager.py:255, utils/file_scanner.py:148, services/lufs_scanner.py:62+, services/smart_playlists.py:94+, services/taste_profile.py:526). A repository/DAO seam would make the write discipline structural.
- The schema **cannot express the domain**: no playlist-origin flag (so "Локальные" is deleted by name — AUD-153), no download-state machine (so the cancel/worker race has no owner — AUD-207), no relation between 	racks and stream_cache (so a deleted track leaves a dangling cache row — AUD-160).
- sqlite3.connect(":memory:") is a trap here — the connections are thread-local, so each thread gets its own empty database (verified).
- The migrations are hard-coded 	ry/except ALTER TABLE blocks with no ordered list and no user_version; a schema_migrations table exists but carries only two constants.
- The listening history needs a **retention and erasure policy** — it is the most personal data the app holds and there is currently no way to delete it (AUD-258, X-13).

### 8.6 Providers

- There is **no provider interface**. The provider set is hard-coded in six places; the bridge dispatches with getattr(self._core, source) and probes the call protocol at runtime with except TypeError (a TypeError raised *inside* a provider causes a second, unintended request — AUD-089/WX-05).
- Every provider hand-rolls its own cache key namespace, its own executor, its own retry policy and its own failure classification — and the classification lists have already drifted (_UNAVAILABLE_MARKS, _YT_GATED_MARKS, _RETRYABLE_MARKS).
- The "Spotify" provider is an iTunes wrapper with a Spotify label (AUD-290) — a **presentation** decision that leaked into the **identity** layer (source_id is a YouTube search string, X-10). Split transport from presentation.
- The provider pools should be sized and scoped by purpose (search vs extraction vs artwork), not shared (X-14).

### 8.7 Tooling

- 	ools/check_lock_nesting.py scans 	ools/ instead of the app and prints "OK" regardless (AUD-459); 	ools/check_shadow_imports.py has the right root but two false positives that keep the gate permanently red (AUD-460). Both are governance tools for rules the project states in AGENTS.md; fixing them and wiring them into CI turns prose into a gate.
- The visual guard needs real baselines (AUD-461) and a machine manifest, and the bench harness needs the play and download scenarios (AUD-474) — the two most important flows are unmeasured.
- The recorded performance artefacts are stale (AUD-471); a tree fingerprint in the result envelope would make staleness detectable.

---

## 9. Test Results and Automated Verification

All checks were run against the working tree as of 2026-10-20 using the project's own interpreter, `& ".venv_win\Scripts\python.exe"` (Python 3.14.7, 64-bit). Nothing was installed, no dependency was changed, no lockfile was touched, and `~/.nedotify/` was never opened.

### 9.1 Byte-compilation (static syntax gate)

`
PS> \="1"
PS> foreach (\ in <194 .py files, excluding venv/build/dist/.git/__pycache__/android/backups>) {
      & ".venv_win\Scripts\python.exe" -m py_compile \.FullName }
PY_COMPILE_RESULT: ALL_OK (194 files)
`

**Result: PASS.** All 194 production and test Python files compile cleanly under Python 3.14.7. No syntax errors, no invalid literals.

### 9.2 Test suite

`
PS> & ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider --no-header
...
11 failed, 1491 passed, 1 skipped, 3 xfailed in 106.53s (0:01:46)
`

**Result: FAIL — 11 failures. The suite is red on the current working tree.**

Collection: **1506 tests collected** in 2.55 s.

#### The 11 failures

| # | Test | Cause |
|---|---|---|
| 1 | 	est_flow_ui.py::test_immediate_flow_coalesces_and_filters_duplicates_in_the_same_response | shared root cause (below) |
| 2 | 	est_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[track] | shared root cause |
| 3 | 	est_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[seed_mutation] | shared root cause |
| 4 | 	est_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[queue_event] | shared root cause |
| 5 | 	est_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[queue_without_event] | shared root cause |
| 6 | 	est_flow_ui.py::test_flow_drops_response_after_listening_intent_changes[flow_toggle] | shared root cause |
| 7 | 	est_flow_ui.py::test_ended_flow_joins_periodic_fetch_and_advances_after_completion | shared root cause |
| 8 | 	est_flow_ui.py::test_failed_fetch_or_append_does_not_suppress_the_next_attempt | shared root cause |
| 9 | 	est_player_recovery_transitions.py::test_crossfade_waits_for_ready_media_then_advances_once_and_releases_outgoing | shared root cause |
| 10 | 	est_player_recovery_transitions.py::test_gapless_starts_preloaded_audio_before_bridge_and_adopts_fresh_session | shared root cause |
| 11 | 	est_player_recovery_transitions.py::test_seek_finishes_crossfade_and_cancels_outgoing_audio | shared root cause |

#### Single root cause — verified by the coordinator

`
TypeError: Cannot read properties of undefined (reading 'progressStyle')
    at fetchAndRenderWaveform (evalmachine.<anonymous>:2244:52)
    at Object.onTrackChanged (evalmachine.<anonymous>:1734:5)
`

The production code:

` ui/web_new_v2/js/player.js:2244 `
`js
const style = document.documentElement.dataset.progressStyle || 'bars';
`
` ui/web_new_v2/js/player.js:2358 `
`js
const style = document.documentElement.dataset.progressStyle || 'bars';
`
` ui/web_new_v2/js/player.js:2513 ` — the same file, **defensive**:
`js
document.documentElement.dataset?.uiStyle === 'macos';
`

The Node-based test harness stubs document with
documentElement: { classList, getAttribute: () => null, style: { setProperty() {} } } — **no dataset**. Lines 2244 and 2358 dereference it unguarded; line 2513 uses optional chaining. The unguarded dereference aborts the whole module evaluation, so every assertion after it never runs.

**Assessment.** In a browser document.documentElement.dataset always exists, so this is *not* a production crash — it is a **robustness/consistency defect** (the file is internally inconsistent about the same access) that happens to be the single cause of the entire red suite. It is also a **live, uncommitted regression**: git status shows 	ests/test_flow_ui.py, 	ests/test_player_recovery_transitions.py and 	ests/test_recommendation_ui.py as **untracked** (??), while ui/web_new_v2/js/player.js carries **+1276/−? lines** of uncommitted change.

**Severity:** P1 (the project's own quality gate is red; the "failure mode is silence" this project cares about is exactly what a red suite is for). **Fix:** use document.documentElement.dataset?.progressStyle at both sites (one character class of change) — or add dataset: {} to the harness stub. Either way the suite must return to green before any other change lands.

### 9.3 Linting and type checking

`
PS> & ".venv_win\Scripts\python.exe" -m pip list | Select-String "ruff|mypy|flake8|pylint|coverage|bandit|black|isort"
`

**Result: no linting, type-checking, coverage or security-scanning tool is installed, and none is configured.** pytest.ini contains only 	estpaths and the 
etwork marker; there is no [mypy]/[tool.ruff] section, no .coveragerc, and no coverage gate. The repository has **no static-analysis gate at all** — which is why an unreachable eturn False (core/api.py:572), an inverted argument order (set_setting) and a KeyError-on-import (main.py:29) all survived.

### 9.4 Coordinator verification of the P0/P1 claims

Each of the following was reproduced by the coordinator against the real source and the installed pywebview package. Raw output is quoted.

**V1 — webview.settings is an ImmutableDict that rejects new keys (P0):**
`
settings type: <class 'webview.util.ImmutableDict'>
RESULT: assignment RAISED KeyError "Cannot add new key 'WEBVIEW2_RUNTIME_PATH'. Only existing keys can be modified."
valid keys: ['ALLOW_DOWNLOADS', 'ALLOW_FILE_URLS', 'IGNORE_SSL_ERRORS',
             'OPEN_DEVTOOLS_IN_DEBUG', 'OPEN_EXTERNAL_LINKS_IN_BROWSER', 'REMOTE_DEBUGGING_PORT']
WEBVIEW2_RUNTIME_PATH valid? False
`
**V2 — the pinned path is absent on this machine, so the branch is skipped here:**
`
pinned path: C:\Program Files (x86)\Microsoft\EdgeWebView\Application\151.0.4129.86\msedgewebview2.exe
exists: False
installed EdgeWebView versions: 155.0.4283.60  155.0.4283.62  SetupMetrics
`
⇒ the defect is **latent on this machine and fatal on the machine the pin targets**.

**V3 — pywebview pins the HTTP port to 42001 and serves CORS * (P1):**
`
webview/__init__.py:70:  DEFAULT_HTTP_PORT = 42001
webview/__init__.py:192: if not _state['private_mode'] and not http_port:
webview/__init__.py:193:     http_port = DEFAULT_HTTP_PORT
webview/http.py:108:  bottle.response.headers['Access-Control-Allow-Origin'] = '*'
`
**V4 — core/api.py:572 makes the tray start unreachable (P1):**
`
572 :         return False
573 :
574 :         if getattr(self, "_tray", None):
575 :             self._tray.start()
576 :
577 :         try:
578 :             import threading
579 :             def _set_icon():
...
595 :             threading.Thread(target=_set_icon, daemon=True).start()
`
eturn False at 572 is unconditional and ends the function; lines 574–597 are **dead code**. self._tray.start() at :575 is the **only** _tray.start() call in the whole tree.

**V5 — the SSRF guard fails open on DNS failure (P1):**
`python
143 :     verdict = True
144 :     try:
145 :         addr_info = socket.getaddrinfo(hostname, None)
...
152 :     except Exception:
153 :         # If DNS resolution fails, fallback string check
154 :         if hostname.startswith("169.254.") or hostname.startswith("10.") \
                 or hostname.startswith("192.168.") or hostname.startswith("127."):
155 :             verdict = False
156 :
157 :     _ssrf_cache_put(hostname, verdict)
`
The default verdict is *safe*; the fallback covers only four literal prefixes; and the result is cached for _SSRF_CACHE_TTL = 120 seconds. main.py:160-225 patches socket.getaddrinfo with a DoH fallback that raises gaierror after three 2-second timeouts — so a DNS outage makes **every** hostname pass the guard, and the wrong verdict is cached.

**V6 — shuffle/epeat are read at the wrong depth in the settings tree (P2):**
`
core/settings.py:256:    "session": {
core/settings.py:262:        "shuffle": False,
core/settings.py:263:        "repeat": "off",
core/api.py:2929:  categories = ['app', 'appearance', 'player', ..., 'session', 'zapret']
js/player.js:1981: if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
js/player.js:1983: if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
js/main.js:409:    window.nedotifySettingsReady = window.pywebview.api.get_settings().then((freshSettings) => {
`
get_settings() returns {category: {...}}; shuffle/epeat live under session; player.js reads them at the top level ⇒ always undefined ⇒ the shuffle button is never highlighted and undefined !== 'off' makes **the repeat button permanently highlighted**.

**V7 — play_pause is a query, but three JS sites use it as a toggle (P2):**
`
core/api.py:1746:    def play_pause(self) -> str:
core/api.py:1758:        state = getattr(self, "_last_reported_state", "") or ""
js/player.js:691: navigator.mediaSession.setActionHandler('play', () => api('play_pause'));
js/player.js:692: navigator.mediaSession.setActionHandler('pause', () => api('play_pause'));
js/library.js:245:  window.pywebview.api.play_pause();
js/library.js:275:  window.pywebview.api.play_pause();
js/player.js:859: export function togglePlayPause() {
`
The backend docstring is explicit that it cannot toggle (the <audio> element lives in the frontend) — so the defect is on the **call sites**: the Windows media-key Play/Pause handlers and the library "Play all" / playlist "Play" buttons do nothing.

### 9.5 Version-control safety net — **absent**

`
PS> git status --porcelain
untracked entries : 123
deleted  entries : 36
modified entries : 70
`

**17 production Python modules are untracked**, including core/offline.py, core/playback_recovery.py, core/listening.py, core/download_store.py, core/download_transfer.py, core/ui_assets.py, core/user_errors.py, services/artist_identity.py, services/catalog_service.py, services/itunes_gateway.py, services/listening_comparison.py, services/lyrics_cache.py, services/lyrics_lookup.py, services/music_matching.py, services/smart_playlists.py, utils/search_query.py, utils/stream_urls.py. ndroid/ is entirely untracked (0 of its files are tracked). The old ui/web_new/ tree is tracked-but-deleted; the live ui/web_new_v2/ is tracked (47 files).

**Consequence:** the git history does **not** represent the shipped product. There is no bisect, no rollback and no reviewable diff for roughly a third of the runtime code — including every module that WN-03/09/10/12/15/24 touched. This is the single largest *process* risk in the repository, and it is the reason defects of the "unreachable eturn" class can survive for months.

### 9.6 Coverage gaps in the automated checks

| Check | Status |
|---|---|
| Byte-compile (194 files) | **PASS** |
| Unit/integration pytest suite | **FAIL** — 11 failures, one root cause (§9.2) |
| Lint (ruff/flake8/pylint) | **Not installed, not configured** |
| Type check (mypy) | **Not installed, not configured** |
| Coverage measurement | **Not configured** — no --cov, no .coveragerc |
| Security scan (bandit/semgrep) | **Not installed, not configured** |
| Dependency audit (pip-audit) | **Not installed**; equirements.txt has **no lockfile and no hashes** ⇒ the installed dependency set is not the tested one |
| PyInstaller build | **Not performed** — no iscc on this machine, and building would write into the repo. Packaging findings are derived from the spec/installer source plus verified runtime consumers (the icon path, the sys._MEIPASS branches, the CWD-relative datas). |
| Live application run | **Not performed** — deliberately avoided: it would disturb the user's real ~/.nedotify/ profile, open real network sessions and drive real provider accounts. All native-Win32 and WebView2 claims are derived from the pywebview 5.4 source in .venv_win plus Win32 documentation, and are labelled *hypothesis* where they could not be executed. |
| Network-dependent tests | Deselected by pytest.ini (ddopts = -m "not network"). The default run therefore **silently skips** the network-marked tests; the suite's green/red signal does not cover them. |

---

## 10. Coverage Gaps

What this audit did **not** verify, and why. Nothing below is a defect; it is the boundary of the evidence.

### 10.1 Not executed (and why)

| Not run | Reason | Consequence |
|---|---|---|
| The packaged application | Launching it would disturb the user's real ~/.nedotify/ profile, open live network sessions and drive real provider accounts | Every WebView2 and native-Win32 claim is derived from the **installed** pywebview 5.4 / pystray / bottle sources plus Win32 documentation, and is labelled *hypothesis* where it could not be executed |
| A frozen PyInstaller build | iscc is not installed on this host, and building writes into the repo | The packaging findings rest on the spec/installer source plus the installed wheel layouts (curl_cffi.libs, yt_dlp's hooks) |
| Live provider traffic | The 
etwork marker is deselected by default and the app must not be run | All provider latencies, rate-limit behaviours and payload shapes are read from the source or from a stub |
| The bench harness / visual guard | un_bench.py, un_guard.py --capture, pyprof_child.py and 	hread_lineage.py all start the real app and open a CDP port | The tooling findings rest on the code, the committed JSON artefacts and direct calls of pure functions |
| A DNS-rebinding attack | Needs a controllable DNS server | The TOCTOU (AUD-005) is proven from the code; the exploit is not demonstrated |
| An SMB/NTLM exchange | No SMB server was stood up | The 21 s UNC stall (AUD-180) is measured; the NTLM offer is inferred from the OS behaviour |
| A real crash during write_tags | A crash injection would need a controlled fault | The non-atomicity (AUD-301) is derived from mutagen's own source and a probe showing no temp-file/rename |
| pip-audit / andit / uff / mypy | Not installed, and the audit must not install anything | The dependency and static-analysis verdicts are code-based, not tool-based |

### 10.2 Known-unknowns left open

- The **frequency** of the 3+ row duplicate-merge partition (AUD-151) depends on a pre-UNIQUE(file_path) database — not present in this repo's history.
- The **live frequency** of the transient CDN 403 that memoises a SoundCloud track for an hour (AUD-228) — the memo's TTL is 1 h, so the blast radius depends on the provider's behaviour.
- The **real impact** of the browser's 	imeupdate throttling on a hidden WebView2 page (the telemetry measured from the renderer's heartbeat) — a WebView2 runtime property, not observable without running the app.
- The **on-screen** manifestation of the DPI displacement (AUD-012), the CSS-class/native-resize divergence and the mini-player transition cost — the host is at 96 DPI / 100 %.
- Whether the settings table without a category column (AUD-199) can occur in a real installation.
- Whether the **_host_allows_credentials** host allow-list ever needs to include a host that the music.yandex.ru divergence (the engine uses a substring test, the proxy a suffix test) would send credentials to.
- The **exact** number of users affected by the "Spotify is iTunes" mislabel — it depends entirely on the installed build.

### 10.3 Premises that were checked and **refuted**

Recording these matters: they are the places where a plausible-sounding hypothesis turned out to be wrong, and a future reviewer should not re-open them without new evidence.

| Hypothesis | Verdict | Evidence |
|---|---|---|
| The provider cache lock is held across a network call | **REFUTED** | The lock is open for 0.000 s during a 3.5 s HTTP call; worst acquisition delay 0.2 ms over 1 591 468 probes |
| The search fan-out is serial | **REFUTED** | 3 providers each sleeping 1 s all started at t=0.001 and search_completed fired at 1.021 s = *max*, not sum |
| A transient network outage blackholes the provider | **REFUTED** | The resolver's negative memo is never populated in production; the SoundCloud memo only records DRM/401-403-404-410 verdicts, and transport errors are explicitly retryable |
| A crafted track title can traverse out of the downloads directory | **REFUTED** | The download filename is download_{sanitised_track_id}_{sha256[:16]} — the title never reaches a filename. Contract #8's Yandex example is **stale** (the id is now sanitised) |
| The bridge's search result shape is missing a esults key | **CONFIRMED as a latent inconsistency** — the return value is always {"query":…, "tracks": []} and the results exist only as event chunks; all three JS callers ignore the value, so there is no symptom today | core/api.py:2088, :2135, :2232 |
| ui/MACos_ui/** is dead legacy CSS | **REFUTED** | It is linked unconditionally at index.html:47-50, routed by core/ui_assets.py, toggled by js/ui-style.js and documented in docs/UI_MACOS.md — it is a **user-selectable interface style**, not dead code. The "legacy pack" label in the audit brief was wrong |
| The proxy's local-file gate can be bypassed | **REFUTED** | Traversal, double-decode, absolute-outside, drive-relative, \\?\, UNC, ile://, trailing dot/space, NTFS ADS, reserved device names and 8.3 aliases were each probed and refused |
| The SQL-injection risk in smart playlists | **REFUTED** | The rule keys are allow-listed, the values are parameter-bound, rtist is LIKE-escaped, the ORDER BY comes from a fixed dict — an injection payload was bound as a literal and the tables survived |
| The _emit UI-thread branch is live | **PARTLY REFUTED** | pywebview 5.4 runs loaded handlers in a fresh thread, so no main-thread emitter exists today; the branch is latent — but it is still one thread per event with no ordering (two emits were observed as [2, 1]) |
| The pystray import works | **REFUTED** | The installed 0.19.5 exports no Separator, so core/tray.py:16 raises ImportError and HAS_PYSTRAY is permanently False — a second, independent reason the tray never starts |

---

## 11. Prioritized Remediation Plan

The full, agent-ready task list is in **docs/audits/REMEDIATION_PLAN.md**. This section is the ordered rationale: what to do first, what depends on what, and what can be done in parallel.

### Wave 0 — Unblock the quality gate (do this before anything else)

| # | Action | Fixes | Why first |
|---|---|---|---|
| 0.1 | Guard the documentElement.dataset access at js/player.js:2244 and :2358 (use ?.), and add dataset: {} to the Node DOM stub | **AUD-015** (P1) | The suite is **red**. While it is red, no other change is protected, and "the tests pass" is not evidence for anything. |
| 0.2 | Delete main.py:29 (webview.settings['WEBVIEW2_RUNTIME_PATH']) | **AUD-001** (P0) | One line; the app currently cannot start on the machine the pin targets. |
| 0.3 | Make the test isolation unconditional: an autouse 	mp_path-backed HOME for the whole session | **AUD-455** (P1) | The suite is currently writing into the user's real ~/.nedotify/downloads/. Until this is fixed, running the tests does damage. |
| 0.4 | Fix 	ools/check_lock_nesting.py's ROOT, fix check_shadow_imports.py's scope walk, and wire both into CI | **AUD-459/460** (P1) | These are the two governance gates the project's own AGENTS.md relies on. They currently pass vacuously and fail falsely. |
| 0.5 | Move 	ests/test_android_source_gates.py out of the Windows suite (or skip it when ndroid/ is absent) | **AUD-457** (P1) | CI is red without it. |

> **Do not merge anything else until 0.1–0.3 are done.** Every subsequent change should land on a green suite and with the user's profile protected.

### Wave 1 — The five P1s that a user can hit in one session

| # | Action | Fixes | Notes |
|---|---|---|---|
| 1.1 | Move the tray start and the window-icon setter **above** the eturn False in _install_snap_layouts (or into set_window()), and raise the pystray floor to a version that exports Separator | **AUD-003** (P1) | Two independent blockers. **Pair with 1.2** — starting the tray exposes the stop bug. |
| 1.2 | Give the tray a lifecycle owner: TrayIcon.stop() must work before pystray marks the icon ready; confine native menu operations to the tray thread | **AUD-129/130** (P2) | Prerequisite for 1.1. |
| 1.3 | One authoritative shutdown path: AppCore.shutdown(reason) with a declared teardown order, called from on_closed, the watchdog branch and an exception handler; release the instance mutex **last**; close the DB **after** the pools | **AUD-011** (P1), AUD-123, AUD-163, AUD-502, AUD-512 | The single highest-leverage fix: it closes the resource-leak family, the double-instance race and the 30 s shutdown stall at once. |
| 1.4 | Fix the SSRF guard: fail closed on resolution failure, never cache the exception-path verdict, and resolve the *address* rather than the hostname | **AUD-004/005** (P1) | Also collapse utils/url_safety.is_safe_media_url and core/api.py::_is_ssrf_safe_url into one implementation (**AUD-352**) so there is a single policy. |
| 1.5 | Fix the "download complete" identity: always create the DB row before enqueueing, distinguish the provider id from the row id, and carry both in the event | **AUD-282** (P2), **X-04** (P1) | Without this, every track downloaded from Search is an orphan file the app cannot find. |
| 1.6 | Move the bridge's tray start, the settings projection and the offline gate behind a single owner | — | See §8; do it while 1.1/1.3 are open. |

### Wave 2 — The contract seams (each removes a family)

| # | Action | Fixes | Depends on |
|---|---|---|---|
| 2.1 | One settings schema: derive the transport from DEFAULT_SETTINGS; project the 
etwork category; fix the settings.session.* access depth in js/player.js; stop mirroring secrets into localStorage | **X-03** (P1), AUD-366, AUD-371, AUD-391, AUD-398 | Wave 0 |
| 2.2 | One resolution front door: route playback through StreamResolver.resolve(); add a monotonic playback epoch so a stale resolution cannot win; cancel superseded resolutions | **X-01** (P1), AUD-125, AUD-164, AUD-165, AUD-164 | 1.3 |
| 2.3 | One cache owner: delete core/api.py::_clean_stream_cache and let CacheManager own the policy; sync the DB rows | **X-05** (P1), AUD-292/293 | 2.1 |
| 2.4 | One offline/network policy at the choke points; invert the bridge interception list to default-DENY; add get_lyrics and get_waveform to it | **X-06** (P1), AUD-020, AUD-179 | 2.1 |
| 2.5 | A readiness handshake (ui_ready()) between the backend and the frontend, replacing the fire-and-forget on_loaded emits | **X-07** (P1), **AUD-009** (P1) | 1.3 |
| 2.6 | One window-state owner and one coordinate space (physical Win32 pixels, converted once at move()); read 
ative.scale_factor, not 
ative._scale | **AUD-012** (P1), AUD-102 | 1.3 |

### Wave 3 — Correctness of the write paths (data integrity)

| # | Action | Fixes |
|---|---|---|
| 3.1 | write_tags → temp file + os.replace; keep a restorable backup next to the file | **AUD-301** (P1), AUD-302, AUD-303 |
| 3.2 | clear_storage("all") → root-confine the deletion to ~/.nedotify/downloads, update the rows in the same transaction, and require an explicit confirmation | **AUD-018** (P1), **X-15** (P2) |
| 3.3 | The zapret update path → refuse to install without a trusted digest; move the binary out of a user-writable directory; fix the _update_lock self-deadlock | **AUD-016** (P1), AUD-310, AUD-311, AUD-314 |
| 3.4 | yt-dlp → pop the cookiefile before close() so the browser jar is never written to disk; remove 
ocheckcertificate from every provider | **AUD-224/225** (P1/P2) |
| 3.5 | The duplicate-merge → merge into a live row; fix the restore predicate; add the is_system playlist flag | AUD-151, AUD-152, AUD-153 |
| 3.6 | The DB → the missing indexes, the get_all_tracks projection + pagination, a bounded connection registry, the close() idempotency and the bounded WAL checkpoint | AUD-154…AUD-200 |
| 3.7 | The downloader → the batch accounting, the retry classification, the orphan removal, the integrity gate, the Content-Length check, the atomic mark_track_downloaded | AUD-162, AUD-169…AUD-177, AUD-207 |

### Wave 4 — Performance

| # | Action | Fixes | Impact |
|---|---|---|---|
| 4.1 | services/listening_comparison.py → materialise the pre-window artist set once (a CTE) instead of a correlated subquery per row | **AUD-259** (P2) | 467 s → ~1 s at 120 k rows |
| 4.2 | services/lufs_scanner.py → stream the decode in chunks and honour the real channel count | AUD-251, AUD-255 | −4.7 GiB peak on a 1-hour file |
| 4.3 | The library bridge → paginate get_library/get_all_tracks, project only the columns the UI reads, and coalesce the download-driven refresh | **AUD-019** (P1), AUD-154, AUD-365 | 5–8 full-table reads per download → 1 delta |
| 4.4 | core/proxy.py → a pooled opener, a socket timeout and a request-thread semaphore; refuse UNC paths before the filesystem call | AUD-180, AUD-184, AUD-185 | removes the 21 s SMB stall and the thread exhaustion |
| 4.5 | The telemetry → write-behind accumulation (the pattern core/settings.py already uses) instead of 720 durable commits/hour; make eport_position one-way | AUD-441, X-13 | −3 MB WAL/hour, −720 UI-thread round trips/hour |
| 4.6 | The taste profile → drop the connection from the revision key; cache the alias table per settings revision | AUD-270, AUD-271 | the 60 s memo actually hits |
| 4.7 | The CSS → collapse 25 blocking sheets to 4, migrate the 69 conflicting selectors, drop the canvas blur, ship a Cyrillic font subset | AUD-400…AUD-409 | −162 KB blocking, no 8.3 Mpx/frame blur, correct Russian typography |

### Wave 5 — Structural work that removes whole classes

| # | Action | Fixes |
|---|---|---|
| 5.1 | Split AppApi into per-capability façades; publish only the façade's public methods | AUD-107, AUD-138, §8.2 |
| 5.2 | Add an injection seam to AppCore and an injectable HTTP client to BaseMusicService; write one real-wiring test | AUD-454, AUD-456, §8.3 |
| 5.3 | One shared DOM stub for the JS tests; add the missing frontend tests | AUD-479, AUD-015 |
| 5.4 | A provider interface + registry; one cache-key namespace per provider; one failure classifier | AUD-211…AUD-249, §8.6 |
| 5.5 | A retention and erasure policy for the listening history; a clear_history bridge method | X-13, §7.1 (privacy) |
| 5.6 | Fix the tooling: the lock checker, the shadow-import checker, the visual-guard baselines, the bench scenarios for the play and download paths, a lockfile, ruff + a type check + a coverage floor | AUD-459…AUD-475, §8.7 |
| 5.7 | **Commit the working tree.** 123 untracked entries, 36 deleted and 70 modified files — including 17 production modules and 53 test files — mean the git history does not represent the shipped product. There is no bisect, no rollback and no reviewable diff for roughly a third of the runtime code. | §9.5 |

### 5.8 Ordering constraints (explicit)

1. **0.1 → 0.3 before everything.** A red suite and a suite that writes to the user's profile make every other measurement meaningless.
2. **0.2 is independent** and can land at any time.
3. **1.3 before 1.1, 2.2, 2.5, 2.6.** The shutdown owner must exist before the tray, the resolver and the window state are touched.
4. **1.1 + 1.2 together.** Starting the tray without fixing its stop path turns a dead feature into a resource leak.
5. **2.1 before 2.3 and 2.4.** Both depend on a correct settings projection.
6. **3.1 before 3.2.** A file writer that corrupts on crash must not be combined with a deleter that has no root check.
7. **3.3 and 3.4 are independent of everything else** and can run in parallel.
8. **5.7 (commit the tree) is independent of all of the above** and should happen first in wall-clock terms if the team agrees to it — it changes the risk profile of every other step.

### 5.9 Estimated effort and risk

| Wave | Items | Size | Risk if done wrong |
|---|---|---|---|
| 0 | 5 | S | Very low — one line, one guard, one fixture, two tool fixes |
| 1 | 6 | M–L | Medium — 1.3 (shutdown) touches every exit path; 1.5 changes a bridge contract |
| 2 | 6 | L | Medium — 2.1 changes a bridge contract; 2.2 changes the resolution path |
| 3 | 7 | M–L | **High** — 3.1/3.2 touch the user's files; 3.3 touches an elevated binary |
| 4 | 7 | M | Low — mostly query and CSS work; measurable by the existing (stale) bench |
| 5 | 7 | XL | Low per item, but 5.1/5.2 are large and touch everything — do them last |

---

## 12. Final Assessment

### 12.1 What this codebase is

NeDotify's Windows desktop app is **not a hobby project**. It has a real architecture: a clean separation between a Python backend, a bridge, a loopback proxy with a capability-scoped token, a provider layer with a shared base class, a SQLite store with WAL and per-thread connections, and a dependency-free vanilla-JS frontend with a design-token system and 17 themes. The engineering vocabulary is mature (AGENTS.md, CODING_STANDARDS.md, per-area skills under .claude/skills/), the security instincts are visible and often correct, and the test suite — 1 506 tests across ~100 files — is far larger than the project's size would predict.

It is also **not finished**. The working tree is mid-migration (ui/web_new/ deleted, ui/web_new_v2/ in place; +7 276 / −25 623 lines across 106 files), with 123 untracked entries including 17 production modules and 53 test files. There is no lint gate, no type gate, no coverage measurement and no lockfile.

### 12.2 The honest verdict

**The architecture is sound; the seams are not policed.** Almost every P0/P1 in this report is a *contract divergence*, not an algorithmic failure:

- A Python layer and a JavaScript layer disagree about the shape of the settings tree (three separate places).
- The backend announces a download with an id the frontend cannot match (and the database row was never created).
- Two cache implementations with different rules, one of which deletes the user's favourites.
- An offline mode implemented as 41 scattered checks instead of one policy, with two omissions found on the first pass.
- A bridge surface of 174 methods published wholesale, with the queue, the current track and the playback epoch owned in five different places.
- A SSRF guard that fails open exactly when the network is unhealthy.

**What is genuinely strong** and should not be disturbed: the proxy's token design and path containment; the SQL parameterisation; the 	extContent discipline in the lyrics and artist modules; the provider-failure isolation; the resolver's memory cache; the fact that a broken provider does not break the search.

**What is genuinely weak**: the boundary between the layers. The project's own documentation names this — *"a renamed event, a hotkey id present on one side of the bridge only, an unserialisable _emit payload — each disappears without a traceback"* - and this audit found **fifteen** independent instances of exactly that failure mode (`X-01`…`X-15` in §6).

### 12.3 Readiness for real use

| Scenario | Verdict | Notes |
|---|---|---|
| **Launching the app** | **FAILS on the target machine** | **P0**: main.py:29 raises KeyError at import wherever the pinned WebView2 is installed. On a machine without it, the app starts — which is why this survived. |
| **Installing and using it** | **Works, with sharp edges** | The tray never appears (P1) despite the setting being on by default; the volume does not survive a restart (P2); the repeat button is always lit (P2); offline mode is invisible (P2) and leaky (P1). |
| **Searching** | **Works** | The fan-out is parallel and isolated. Two providers are mislabelled or mis-typed (the "Spotify" tab is iTunes; the "Плейлисты" filter fabricates tiles), and the "Spotify" rows can collide on a non-id. |
| **Playing a track** | **Works, with races** | The stale-resolution race is real (P1): rapid clicks can play the wrong track, and a late resolution can replace the user's whole queue with one track. |
| **Downloading** | **Broken for provider-sourced tracks** | Files land on disk as orphans the app cannot find (P1). Pause leaks the batch counter (P2). |
| **Lyrics** | **Works** | Wrong-track lyrics are possible when the artist is unknown (P1); a failed translation duplicates every line (P2); the history is broadcast to 5 providers with no opt-out (P2). |
| **Offline** | **Leaks** | The /?url= proxy path still fetches upstream (P1); lyrics and waveform still fetch (P2); the UI does not show the state (P2). |
| **The library** | **Works** | The favourite counter double-counts (P2); the whole table is re-read 5–8 times per download (P1 perf); the loudness feature never analyses a downloaded track (P2). |
| **Shutdown** | **Leaks** | Three divergent exit paths (P1); the DB closes before the pools; the session is lost on the watchdog path and on a kill. |
| **The quality gate** | **Red** | 11 failures from one DOM-contract drift; the isolation is opt-in and the suite has already written into the user's real library. |
| **The governance** | **Absent** | No lint, no type check, no coverage, no lockfile; the two lock/shadow checkers pass vacuously or fail falsely; the visual guard compares against an empty baseline; every recorded performance number is stale. |

### 12.4 The single most important sentence in this report

> The project does not have a **correctness** problem in the sense of "the algorithms are wrong". It has a **contract** problem in the sense of "nothing verifies that the layers still agree with each other" — and the existing quality gate cannot detect it, because the gate is red, the gate is opt-in-isolated, the gate is greps rather than behaviour, and a third of the tree is not even committed.

### 12.5 What would change the verdict

A competent, focused effort would change this from "risky" to "solid":

1. Make the suite green and the isolation unconditional (**Wave 0**, days).
2. Fix the P0 and the five session-reachable P1s (**Wave 1**, ~2 weeks).
3. Establish one owner per contract — settings, resolution, cache, offline, shutdown (**Wave 2**, ~3 weeks).
4. Fix the write paths that can touch the user's files (**Wave 3**, ~2 weeks).
5. Bring the two dominant query costs down and give the frontend a real DOM harness (**Waves 4–5**, ~3 weeks).

That is roughly **8–10 weeks of one engineer's work**, and it converts a product with an excellent architecture and an unreliable perimeter into one that can be shipped. The alternative — continuing to add features on the current footing — will keep producing the same class of defect, because nothing in the current pipeline is capable of seeing it.

### 12.6 A note on what was *not* changed

No source file was modified during this audit. The only writes are this report, docs/audits/REMEDIATION_PLAN.md, the audit scaffolding (WIN_AUDIT_CONTEXT.md, WIN_AUDIT_AREAS.md) and the preservation copies of the previous Android audit (ANDROID_FULL_PROJECT_AUDIT.md, ANDROID_REMEDIATION_PLAN.md) made before this report took over FULL_PROJECT_AUDIT.md. The user's ~/.nedotify/ profile was never opened for writing; the test suite's own writes into it are recorded as **AUD-455** and are a finding, not a side effect of this audit.

---

*End of report.*

---
