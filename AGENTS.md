# NeDotify — agent rules

Windows desktop music app: Python 3.14 + pywebview (embedded WebView) + a loopback
HTTP proxy + Vanilla JS. No build step, no bundler, no framework. The sole UI
is `ui/web_new_v2/`. Legacy version flags and UI directory overrides are retired.

## Scope: this file is about the DESKTOP product only

The repository holds **two products**:

| Product | Where | Rules |
|---|---|---|
| Windows desktop player (Python + pywebview) | `main.py`, `core/`, `services/`, `audio/`, `ui/web_new_v2/` | **this file** |
| Native Android app (Kotlin + Compose + Media3 + Room) | `android/` | [`android/AGENTS.md`](android/AGENTS.md) |

Everything below — the interpreter, the bridge, `~/.nedotify/`, the keybind
tables — describes the **desktop** product. It does **not** apply to the code
under `android/`: that tree is Kotlin, it has no `~/.nedotify/` (its library
lives on the device), it has no pywebview bridge and no hotkeys, and it is
built by Gradle, not by PyInstaller. Read `android/AGENTS.md` before editing
anything under `android/`. The state of that port is in
`android/PORTING_STATUS.md`.

**Interpreter for every command:** `& ".venv_win\Scripts\python.exe"`. Bare
`python` lacks pywebview/yt-dlp.

## The failure mode here is silence

A renamed event, a hotkey id present on one side of the bridge only, an
unserialisable `_emit` payload — each disappears without a traceback. When a
change crosses one of those boundaries, run the named test. Do not read the diff
and conclude.

- `CODING_STANDARDS.md` — read **before** editing the pywebview bridge, the
  proxy's socket handling, a download filename, or either keybind table.
- `.claude/skills/nedotify-test` — running the suite, the `network` marker, what counts
  as done.
- `.claude/skills/nedotify-run` — launching the app, the WebView2 pin, logs, shutdown.
- `.claude/skills/nedotify-build` — installer, `sys._MEIPASS`, `datas`, hidden imports.
- `.claude/skills/nedotify-perf` — isolated benchmarks in `tools/bench/`.
- `STATUS.md` — what the code actually does. `docs/AUDIT.md` — what the
  2026-10-03 audit changed.

## Three rules that outlive the details

- **`_emit` never runs on the UI thread.** pywebview's WinForms backend marshals
  `evaluate_js` through `Control.Invoke`, so the UI thread waits on itself and the
  whole window freezes. `AppApi._emit` detects this and hands off to an
  `EmitWorker` thread. Keep that branch — `tests/test_emit_thread_safety.py`
  pins it.
- **A new shared field joins its class's existing lock** rather than opening a
  second one. `BaseMusicService` guards `_search_cache` / `_stream_cache` with the
  class-level `_cache_lock`; `StreamResolver` guards `_mem` / `._inflight` with
  `self._lock`. The rule is not statically checkable — it is a statement of
  intent, so it stays in prose.
- **`~/.nedotify/` is the user's library** — downloads, the SQLite database, the
  logs. Clearing it is not a cleanup step. Ask first.

When a doc and the code disagree, the code wins. If a rule cannot be verified at
a call site, delete it rather than passing it on.
