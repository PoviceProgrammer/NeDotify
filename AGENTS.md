# NeDotify / AURA Music - Development Guidelines & Rules

> Audited against the code on 2026-10-03. Every claim below was checked against
> a real call site; when a rule could not be verified it was removed rather than
> kept as folklore. See `STATUS.md` for what the code actually does and
> `docs/AUDIT.md` for what the audit changed.

## Project Overview
AURA Music (shipped as **NeDotify**) is a desktop music streaming and downloading
application for Windows.

- **Backend**: Python **3.14+** (`.venv_win` is 3.14.7; this is the minimum),
  SQLite (WAL), a loopback HTTP proxy, `ThreadPoolExecutor`, pywebview JS bridge.
- **Frontend**: HTML5 + Vanilla JS + CSS. The **default** UI is
  `ui/web_new_v2/` (`main.py`: `NEDOTIFY_UI_DIR`, default `"web_new_v2"`).
  `ui/web_new/` is the legacy v1, reachable only via `--ui-v1` / `--v1`.
- **Providers** (`services/`): YouTube, SoundCloud, Spotify (metadata only),
  Yandex Music, VK Music. Yandex and VK search are **disabled on purpose**
  (`core/api.py: DISABLED_UI_PROVIDERS`); see `STATUS.md`.
- **Packaging**: PyInstaller only (`setup_pyinstaller.spec`,
  `build_installer.py`) + Inno Setup (`installer.iss`, `installer_gui.py`,
  `uninstaller_gui.py`). **Nuitka is not used** - there is no Nuitka config,
  no `--onefile` Nuitka build, and no Nuitka dependency anywhere.
- **Testing**: pytest suite in `tests/` (566 tests), `run_tests.py`, `pytest.ini`.
  No Playwright/Selenium: the "E2E" tests are opaque-box Python tests against the
  real `AppApi`/`DownloadManager`/`DatabaseManager` with stub providers.

---

## Coding Rules & Best Practices

### 1. Python Backend & Concurrency
- **Thread Safety**: All shared state must be lock-protected.
  `BaseMusicService._search_cache` / `._stream_cache` use the class-level
  `_cache_lock` (`services/base_service.py`); `StreamResolver._mem` /
  `._inflight` use `self._lock` (`core/resolver.py`). When you add a cache or a
  new field to one of those classes, extend the existing lock, do not invent a
  second one.
- **Windows Socket Handling**: In `core/proxy.py` and the streaming endpoints,
  swallow Windows-specific disconnects (`WinError 10053`/`10054`,
  `BrokenPipeError`, `ConnectionResetError`) around `wfile.write()` instead of
  letting them become 500s.
- **Never `evaluate_js` from the UI thread**: `AppApi._emit` (`core/api.py`)
  already detects `_MAIN_THREAD` and hands the call to an `EmitWorker` thread,
  because pywebview's WinForms backend marshals `evaluate_js` through
  `Control.Invoke` and calling it from the UI thread deadlocks the whole window.
  Keep that branch intact; it is covered by a regression test.
- **Async & Thread Pools**: Long operations stay off the UI thread. Search runs
  on `ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")`
  (`core/api.py`); downloads on `max_workers=_MAX_INFLIGHT` with prefix
  `download_worker` (`core/downloader.py`); shared provider work on
  `BaseMusicService._executor` (8 workers). `BaseMusicService.submit()` is
  shutdown-safe and returns `None` when the pool is gone - keep using it rather
  than touching `ThreadPoolExecutor` directly.
- **Path Sanitization**: there is **no** `utils/path_utils.py` and no generic
  "strip forbidden Windows characters" helper. What actually exists:
  - Cache **file names** are reduced to `[A-Za-z0-9_-]` inline with
    `re.sub(r'[^a-zA-Z0-9_-]', '_', ...)`:
    `services/youtube_service.py` (yt-dlp `outtmpl`),
    `core/api.py` (~lines 1140 and 1277, on-disk stream cache lookup),
    `core/proxy.py` (~line 746, same lookup on the proxy side).
  - Downloaded files are written **as** `yt_<safe_id>_<ts>.<ext>` into
    `~/.nedotify/downloads` (`core/downloader.py`), i.e. sanitized by
    construction, not by a title-based filename.
  - `services/zapret_service.py: sanitize_zapret_args()` sanitizes the *zapret
    command line*, not filenames.
  If you add a human-readable `<artist> - <title>.mp3` name, you must add the
  forbidden-character filtering at the same time.

### 2. Frontend & pywebview Bridge
- **Bridge contract** (verified, no SSE anywhere in this project):
  - Python -> JS: `AppApi._emit(name, payload)` serializes the payload with
    `json.dumps` and calls `window.onPythonEvent(<name>, <payload>)` via
    `window.evaluate_js`. A **non-serializable payload used to be dropped
    silently** - it is now guarded and logged; keep that guard.
  - JS -> Python: `window.pywebview.api.<method>(...)`, i.e. the
    `AppApi` instance passed to `create_window(js_api=...)`. Call it
    defensively (try/catch + fallback UI state).
  - There is **no** `EventSource` / `text/event-stream` endpoint and no
    WebSocket channel. Do not add frontend code that waits for one.
- **Event names**: the backend emits `download_complete`, **not**
  `track_downloaded`, and with payload `{"track_id": ...}` only (no `file_path`).
  `ui/web_new_v2/js/events.js` accepts both spellings - that is why the drift is
  invisible. See `STATUS.md`.
- **Dual HTML5 Audio & Teardown**: in `player.js`, clear `audio.src = ""` and
  drop listeners during crossfade/stop so WebView does not leak sockets.
- **DOM & UI**: keep it Vanilla JS + plain CSS, no heavy UI framework.

### 3. Database Integrity (SQLite)
- **WAL Mode**: `core/database.py` issues `PRAGMA journal_mode=WAL` - do not
  remove it; the proxy serves reads while the UI writes.
- **Integrity**: when marking `is_downloaded = 1` / `file_path`, preserve the
  original `source` provider and the existing metadata columns.
- **Transactions**: parameterized queries and `with conn:` context managers only.

### 4. Testing Protocols
- Run `pytest -q` (or `python run_tests.py`). Baseline before the audit was 96
  tests; the suite is now **566** - a regression is never acceptable.
- Network providers are stubbed (`ServiceStub` / `YouTubeService` stand-ins) or
  `monkeypatch`ed. No test may hit the network.
- **Home isolation is mandatory**: `tests/conftest.py::redirect_home` redirects
  `~` into `tmp_path`. It handles `"~"`, `"~/x"` **and** `"~\\x"` because the
  production code spells the profile as the forward-slash literal
  `"~/.nedotify"`. If you add a code path that touches the profile, add a test
  that goes through that fixture - `tests/test_conftest_home_isolation.py`
  guards the fixture itself.

### 5. Packaging & Resource Paths
- Static assets (icons, HTML, JS) resolve via `sys._MEIPASS` when frozen and
  `os.path.dirname(__file__)` in development - see `main.py`, `core/tray.py`,
  `core/proxy.py`, `installer_gui.py`.
- `installer.iss` + `installer_gui.py` own registry/shortcut/uninstall; keep
  generated artifacts (`*.spec` other than `setup_pyinstaller.spec`, `dist/`,
  `build/`) out of version control per `.gitignore`.