# WIN Audit — Shared Context Brief (Windows desktop product)

Read this file first. It is the common brief for every reviewer agent in this run.

> **Scope of this run: the WINDOWS DESKTOP product only.**
> Repo root: `C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main`
> The `android/` subtree (Kotlin/Compose/Media3/Room) is **OUT OF SCOPE**. Do not
> open it, do not review it, do not use it as a subject. A *previous* run audited
> Android (`docs/audits/ANDROID_FINDINGS_REGISTER.md`); this run audits the
> Windows desktop app only. You may read `android/AGENTS.md` for nothing — skip it.

## What this project is

NeDotify (AURA Music) — a Windows desktop music player.

- **Backend**: Python 3.14.7 + `pywebview` (embedded WebView2). Entry point `main.py`.
- **Bridge**: `core/api.py::AppApi` is the pywebview `js_api` object. Python → JS is
  `AppApi._emit(name, payload)` → `window.onPythonEvent(name, payload)`.
  JS → Python is `window.pywebview.api.<method>(...)`.
- **Frontend**: Vanilla JS + CSS, no build step, no bundler, no framework.
  The **only** UI is `ui/web_new_v2/`. `ui/MACos_ui/` is a legacy CSS pack.
- **Proxy**: a loopback `http.server` in `core/proxy.py` that injects auth headers
  into cloud stream requests and self-heals expired stream URLs.
- **Storage**: SQLite (WAL) at `~/.nedotify/nedotify_storage.db` (`core/database.py`),
  downloads in `~/.nedotify/downloads/`, stream cache in `~/.nedotify/streams/`,
  logs in `~/.nedotify/logs/app.log`.
- **Providers**: YouTube, SoundCloud, Yandex Music, VK, Spotify, Last.fm, iTunes
  (under `services/`).
- **Audio**: playback is HTML5 `<audio>` in the frontend; the Python side
  (`audio/engine.py`, `audio/queue.py`) owns the queue and resolution.
- **Tests**: pytest suite in `tests/` (~100 files). `pytest.ini` deselects the
  `network` marker by default.

## Repository map (directory → responsibility)

| Path | Responsibility |
|---|---|
| `main.py` | process bootstrap: WebView2 pin, DoH fallback, single-instance mutex, Bottle route capture, startup watchdog, session save/cleanup |
| `core/app.py` | `AppCore` — wires every subsystem together, owns lifecycle (`cleanup`) |
| `core/api.py` | `AppApi` — the whole JS bridge surface (~200 methods) |
| `core/proxy.py` | loopback HTTP stream proxy + self-healing URL re-resolution |
| `core/database.py` | SQLite schema, migrations, all persistence |
| `core/downloader.py` | background download queue, worker pool, resume, retries |
| `core/settings.py` | settings defaults + DB-backed store + hotkey table (mirrors `ui/web_new_v2/js/hotkeys.js`) |
| `core/resolver.py` | stream URL resolution coordinator (mem → DB → network, single-flight) |
| `core/playback_recovery.py` | bounded stream renewal without touching the queue |
| `core/session.py` | session persist/restore |
| `core/listening.py` | per-play listening measurement dataclass |
| `core/tray.py` | pystray system-tray menu |
| `core/snap_layouts.py` | Win11 Snap Layouts for the frameless window (ctypes/Win32) |
| `core/plugins.py` | opt-in user plugin loader |
| `core/offline.py` | offline-mode helpers |
| `core/download_store.py`, `core/download_transfer.py` | download state persistence + cooperative transfer control |
| `core/ui_assets.py` | legacy macOS CSS pack route |
| `core/user_errors.py` | stable user-facing error categories |
| `core/services/discord_rpc.py` | Discord Rich Presence |
| `core/services/recommendation.py` | recommendation scoring core |
| `audio/engine.py`, `audio/queue.py` | playback queue, shuffle/repeat, track resolution callbacks |
| `services/*` | provider clients and feature services (see the area list) |
| `utils/*` | cache manager, file scanner, search query, stream URL helpers, tag parser, URL safety |
| `ui/web_new_v2/index.html` | the single UI document (~209 KB) |
| `ui/web_new_v2/js/*` | 34 ES modules: player, settings, search, home, library, lyrics, profile, events, hotkeys, utils… |
| `ui/web_new_v2/css/*` | themes, tokens, component styles |
| `tools/bench`, `tools/visual_guard` | performance harness and visual regression harness |
| `tests/` | ~100 pytest files |

## Non-negotiable rules of this codebase (from `AGENTS.md` / `CODING_STANDARDS.md`)

These are the *intended* contracts. Violating them is a finding; so is
implementing them in a way that provably does not hold.

1. **`_emit` must never run on the UI thread.** pywebview's WinForms backend
   marshals `evaluate_js` through `Control.Invoke`, so the UI thread waiting on
   itself freezes the whole window. `AppApi._emit` detects this and hands off to
   an `EmitWorker` thread. `tests/test_emit_thread_safety.py` pins it.
2. **A new shared field joins its class's existing lock** rather than opening a
   second one. `BaseMusicService` guards `_search_cache` / `_stream_cache` with the
   class-level `_cache_lock` (an `RLock`); `StreamResolver` guards `_mem` /
   `._inflight` with `self._lock`.
3. **`~/.nedotify/` is the user's library.** Clearing it is not a cleanup step.
4. **WAL is load-bearing** in `core/database.py` (`PRAGMA journal_mode=WAL`).
   The proxy serves reads while the UI writes.
5. **The hotkey table is mirrored**: `DEFAULT_KEYBINDS` in
   `ui/web_new_v2/js/hotkeys.js` must equal `DEFAULT_SETTINGS["hotkeys"]` in
   `core/settings.py`. An id present on one side only is silently discarded.
6. **There is no EventSource / SSE / WebSocket channel.** The bridge callback is
   the only Python → JS channel. Frontend code that waits for a server push
   waits forever.
7. **Event names**: the backend emits `download_complete` (`{"track_id": ...}`)
   and `download_failed`. `download_complete` carries **no** `file_path`.
8. **Filename sanitisation**: no generic helper exists. Stream-cache names are
   reduced to `[A-Za-z0-9_-]`. Windows rejects `< > : " / \ | ? *` in filenames.
   `services/yandex_service.py` still builds `ya_<raw_id>_<ts>.mp3` from an
   unsanitised id — documented, not enforced.
9. **Frozen vs source assets**: any asset lookup needs both
   `getattr(sys, "_MEIPASS", ...)` branches or it breaks in the packaged exe.
10. **The plugin folder is never added to `sys.path`.**
11. **Python 3.14.7** is the only supported interpreter; the venv is
    `.venv_win\Scripts\python.exe`.

## Ground rules for every reviewer

- **Read the real files.** Do not assume contents. Use `read`, `grep`, `glob`,
  `shell` (PowerShell on Windows).
- **Do not modify any source file.** You are a reviewer. Writing scratch files
  under `%TEMP%` is allowed; touching the repo tree is not — with ONE exception:
  your own report file (see "Where to put your report").
- **Evidence is mandatory.** Every finding needs `path:line` references and a
  quoted snippet (or a precise description of the code at those lines).
- **Trace call chains.** A defect in a callee is a finding for the area that owns
  the callee; a defect in how a caller uses it is a finding for the caller's area.
  Do not double-report the same root cause in two areas — say so in the report
  and name the owning area.
- **Separate CONFIRMED from HYPOTHESIS.** A hypothesis must say exactly what
  evidence is missing and what would confirm it.
- **No style nits.** Naming, formatting, comment style, "this could be nicer" —
  not findings. Do not propose refactoring for aesthetics.
- **No invented findings.** If an area is clean, say it is clean. A short report
  is a better outcome than a padded one.
- **The interpreter for any command is `& ".venv_win\Scripts\python.exe"`.
  Never bare `python`. Never install or change dependencies. Never touch
  `~/.nedotify/`. Never run the real app (it would disturb the user's profile).
  Read-only commands and `pytest` are fine.
- When you run commands in PowerShell, set
  `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` first, otherwise
  Cyrillic text is mangled in the output and you may misread source files.

## Priority scale

- **P0 CRITICAL** — data loss/corruption, serious vulnerability, total failure of a
  core function.
- **P1 HIGH** — reproducible crash, broken important functionality, serious race
  condition, substantial resource leak.
- **P2 MEDIUM** — bug in a specific scenario, noticeable performance problem,
  unstable state handling.
- **P3 LOW** — non-critical defect, small implementation-quality issue, local
  optimisation.
- **ARCH** — architecture improvement *without* a proven defect. Report separately
  from defects; do not mix it into the defect list.

## Role A — Correctness & Reliability

Find everything that can break under real use: logic errors, wrong conditions,
state-machine bugs, unhandled exceptions, race conditions, deadlocks, resource
leaks, thread-safety violations, async mistakes, null/empty handling, bad
boundary inputs, data loss, crashes, broken recovery after failure.

## Role B — Architecture, Security & Performance

Judge the engineering: layering and responsibility split, coupling, duplication,
algorithmic inefficiency, excess allocation, data leaks and vulnerabilities,
unsafe handling of external data, incorrect API usage, scalability, antipatterns,
unstable dependencies, lifecycle mistakes, broken contracts between components,
testability and maintainability. **Do not report pure style opinions** — only
architecture/security/performance issues that have a concrete consequence.

## Where to put your report

1. Write your **full** Markdown report to:
   `C:\Users\Артур\AppData\Local\Temp\opencode\audit_reports\<AREA-ID>-<A|B>.md`
   (create the directory if needed). Use the `write` tool.
2. Return in your final message a **condensed version**: the scope you read, the
   full list of findings in the required shape but with short evidence quotes,
   clean areas, and coverage gaps. Keep it under roughly 120 lines.

## Required report format

Your Markdown report must contain exactly these sections:

```
## AREA <ID> — <name> — ROLE <A|B>
### 1. Scope reviewed
- Files opened (path: line ranges actually read)
- Callees traced into other areas (list)

### 2. Findings
For each finding, in this exact shape:

#### F-<AREA>-<n>  [P0|P1|P2|P3] — <one-line title>
- **File:** `path:line-line` (plus any other file:line)
- **Confirmed:** yes | hypothesis
- **Description:** what is wrong
- **Cause:** why it is wrong (root cause, not symptom)
- **Trigger conditions:** how it manifests
- **User impact:** what the user experiences
- **Evidence:** quoted code
- **Reproduction / verification:** concrete steps, test, or command
- **Suggested fix:** direction only (do not implement)
- **Fix side effects:** risks of the fix
- **Discovered by:** A | B

### 3. Clean areas
What you checked and found correct (brief).

### 4. Coverage gaps
What you could not verify and why.
```

If there are no findings in an area, say so explicitly in section 2
("No findings.") and still fill in sections 1, 3 and 4. Do not invent work.
