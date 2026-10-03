Guidelines for this repo live in @AGENTS.md (Python/concurrency, pywebview bridge,
SQLite integrity, testing, packaging rules). What the code actually does is in
@STATUS.md; what the 2026-10-03 audit changed is in @docs/AUDIT.md.

## Quick reference

- Always use the venv interpreter: `& ".venv_win\Scripts\python.exe"` — bare
  `python` lacks pywebview/yt-dlp. Windows + PowerShell. `.venv\` and
  `.venv_win_backup\` were removed on 2026-10-03; only `.venv_win\` exists.
- Tests: `& ".venv_win\Scripts\python.exe" -m pytest` (`pytest.ini` deselects the
  `network` marker by default). See the `aura-test` skill.
- Run the app: `& ".venv_win\Scripts\python.exe" main.py` — blocking GUI process.
  See the `aura-run` skill.
- The perf harness that used to live in `scripts/` + `benchmarks/` was removed
  from git (`a3425eb`); neither directory is tracked.
- Packaging: `pyinstaller setup_pyinstaller.spec` then `iscc installer.iss`
  (the canonical installer). See the `aura-build` skill.

## Non-obvious constraints

- WebView2 is pinned to `151.0.4129.86` in `main.py`; Evergreen `.93` kills
  bridge injection on this machine, so `window.pywebview.api.*` silently dies.
- Bottle route/no-cache hooks must be installed synchronously in the
  monkeypatched `bottle.run`, before serving starts — a background thread loses
  the race and causes an `/assets/*.png` 404 storm.
- The audio proxy must swallow `WinError 10053`, `BrokenPipeError` and
  `ConnectionResetError` on `wfile.write()` rather than 500.
- There is **no** `utils/path_utils.py`. Cache *file names* are reduced to
  `[A-Za-z0-9_-]` inline (`re.sub(r'[^a-zA-Z0-9_-]', '_', ...)`) in
  `services/youtube_service.py`, `core/api.py` and `core/proxy.py`; downloads
  are written as `yt_<safe_id>_<ts>.<ext>`. If you add a human-readable
  `<artist> - <title>.mp3`, add forbidden-character filtering with it.
- Do not delete the profile tree `~/.nedotify/` (or the SQLite DB inside it) to
  get a clean state without asking.
