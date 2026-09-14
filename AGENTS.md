# AURA Music - Development Guidelines & Rules

## Project Overview
AURA Music is a desktop music streaming and downloading application.
- **Backend**: Python 3.14, SQLite, HTTP Proxy server, ThreadPoolExecutor, pywebview API Bridge.
- **Frontend**: HTML5, Vanilla JavaScript, CSS (inside `ui/web_new/`), communicating with Python via pywebview JS bridge.
- **Search & Streaming Providers**: YouTube, SoundCloud, Spotify (metadata), Yandex Music.
- **Packaging**: PyInstaller, Inno Setup (`installer.iss`), Nuitka.
- **Testing**: Pytest, opaque-box E2E test suites in `tests/`, `run_tests.py`.

---

## Coding Rules & Best Practices

### 1. Python Backend & Concurrency
- **Thread Safety**: All shared resources (such as `BaseMusicService._search_cache`) must be protected by threading `Lock()`.
- **Windows Socket Handling**: In `core/proxy.py` and network streaming endpoints, catch Windows-specific socket disconnects (`WinError 10053`, `BrokenPipeError`, `ConnectionResetError`) gracefully during `wfile.write()` without raising 500 errors or crashing.
- **Async & Thread Pools**: Keep long-running operations (database searches, audio downloads, provider scraping) off the main UI thread using `ThreadPoolExecutor`.
- **Path Sanitization**: Always sanitize Cyrillic and forbidden Windows characters (`\ / : * ? " < > |`) when saving cached streams or downloaded music files (`utils/path_utils.py`).

### 2. Frontend & pywebview Bridge
- **Dual HTML5 Audio & Teardown**: In `player.js`, clear `audio.src = ""` and remove event listeners during crossfade/stop to prevent lingering background audio connections or socket leaks in WebView.
- **Bridge Calls**: Call `window.pywebview.api.*` defensively with proper error handling and fallback UI states (loaders, toasts).
- **DOM & UI**: Keep frontend pure Vanilla JavaScript and clean CSS without heavy third-party UI dependencies.

### 3. Database Integrity (SQLite)
- **WAL Mode**: Use Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for concurrent reading and writing.
- **Integrity**: When updating `tracks` table with `is_downloaded = 1` and `file_path`, preserve original `source` provider and metadata.
- **Transactions**: Always use parameterized queries and safe context managers (`with conn:`) to prevent database lockups.

### 4. Testing Protocols
- Run tests via `pytest` or `python run_tests.py`.
- Mock external network calls (YouTube, SoundCloud, Spotify, Yandex) in unit tests to ensure fast and reliable execution.
- Maintain test coverage for Tiers 1–4 across Playback, Downloader, and Search modules.

### 5. Packaging & Resource Paths
- When loading static assets (icons, HTML, JS, templates), resolve paths dynamically using `sys._MEIPASS` when frozen (PyInstaller) and `os.path.dirname(__file__)` during development.
