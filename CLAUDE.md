Guidelines for this repo live in @AGENTS.md (Python/concurrency, pywebview bridge,
SQLite integrity, testing, packaging rules) and the architecture, feature inventory
and interface contracts in @PROJECT.md. Follow both.

## Quick reference

- Always use the venv interpreter: `& ".venv\Scripts\python.exe"` — bare `python`
  lacks pywebview/yt-dlp. Windows + PowerShell.
- Tests: `& ".venv\Scripts\python.exe" -m pytest` (`pytest.ini` deselects the
  `network` marker by default). See the `aura-test` skill.
- Run the app: `& ".venv\Scripts\python.exe" main.py` — blocking GUI process.
  See the `aura-run` skill.
- Perf harness in `scripts/` + `benchmarks/`: see the `aura-perf` skill.
- Packaging: `build_installer.py` / `setup_pyinstaller.spec`: see `aura-build`.

## Non-obvious constraints

- WebView2 is pinned to `151.0.4129.86` in `main.py`; Evergreen `.93` kills
  bridge injection on this machine, so `window.pywebview.api.*` silently dies.
- Bottle route/no-cache hooks must be installed synchronously in the
  monkeypatched `bottle.run`, before serving starts — a background thread loses
  the race and causes an `/assets/*.png` 404 storm.
- The audio proxy must swallow `WinError 10053`, `BrokenPipeError` and
  `ConnectionResetError` on `wfile.write()` rather than 500.
- Sanitize Cyrillic and illegal Windows characters for every path written to
  `.cache/streams/` or `.cache/downloads/` (`utils/path_utils.py`).
- Do not delete `aura.db` or `.cache/` to get a clean state without asking.
