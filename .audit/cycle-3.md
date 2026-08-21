# CYCLE #3 — 2026-08-19T21:52:00Z

## SUBAGENTS
| Agent | Status | Findings | CRITICAL | MAJOR | MINOR |
|-------|--------|----------|----------|-------|-------|
| ZAPRET | DEGRADED | 9 | 2 | 4 | 3 |
| DISCORD | DEGRADED | 9 | 0 | 4 | 5 |
| PERFORMANCE | DEGRADED | 19 | 4 | 9 | 6 |
| SECURITY | DEGRADED | 6 | 1 | 4 | 1 |
| DATABASE | OK / STABLE | 14 | 0 | 5 | 9 |
| FRONTEND | DEGRADED | 16 | 2 | 6 | 8 |
| **TOTAL** | **ACTIVE** | **73** | **8 (deduped)** | **28 (deduped)** | **27 (deduped)** |

---

## VERIFIED CRITICAL FINDINGS (orchestrator-checked)

### [C-1] `services/zapret_service.py:170-178` — WMIC CSV Column Parsing Mismatch & ValueError
- **Mechanism**: `wmic process where "name='winws.exe'" get ProcessId,CommandLine /FORMAT:CSV` outputs columns alphabetically as `Node,CommandLine,ProcessId`. `line.split(",", 2)` splits on arguments commas (e.g. `--wf-tcp=80,443`), setting `parts[1]` to `--wf-tcp=80`. `int(parts[1])` raises `ValueError`, which is swallowed in the loop. The PowerShell fallback in `except Exception:` is never reached, causing elevated PID discovery to return empty lists.
- **Impact**: 9/10 (Elevated Zapret process running state cannot be detected, causing duplicate spawns or false "stopped" status).
- **Proposed Fix**: Parse CSV with Python `csv.reader` or split from the right (`line.rsplit(",", 1)`), and ensure unexpected formats bubble up to the PowerShell CIM fallback.

### [C-2] `services/zapret_service.py:205, 668-678` — Standard User Unable to Terminate Elevated `winws.exe` (Orphan Process Leak)
- **Mechanism**: Non-elevated AURA Music executing `taskkill /PID {pid} /F` against high-integrity (elevated) `winws.exe` fails with `ERROR: Access is denied` (exit code 1). `_kill_pid` catches the error, but `stop()` unconditionally calls `_clear_pidfile()`, deleting the PID reference while `winws.exe` remains running in the background indefinitely holding WinDivert locks.
- **Impact**: 9/10 (Orphan elevated processes linger, blocking driver re-initialization and subsequent Zapret startups).
- **Proposed Fix**: If non-elevated `taskkill` fails, prompt/dispatch an elevated taskkill via `ShellExecuteW('runas', 'taskkill.exe', f'/PID {pid} /F', ...)` to cleanly kill the elevated process.

### [C-3] `services/zapret_service.py:597-610` — Command Injection / Privilege Escalation via PowerShell in Elevated Zapret Launcher
- **Mechanism**: In `_launch_elevated(exe, raw_args)`, user-controlled `raw_args` passed from `toggle_zapret(enabled, mode="custom", custom_args=...)` is directly interpolated into a single-quoted string executed via elevated PowerShell `-Command` (`ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", ...)`). An injection payload containing single quotes breaks out of `-ArgumentList` to execute arbitrary commands under Administrator privileges.
- **Impact**: 9/10 (Arbitrary elevation of privilege and command injection).
- **Proposed Fix**: Validate/sanitize `raw_args` against strict allowed characters (`^[a-zA-Z0-9_=\-\s\.,/]+$`), escape single quotes, or pass arguments via a temporary script or environment variable.

### [C-4] `services/soundcloud_service.py:17-42` — Unsynchronized `_TTLCache` Concurrency Race across Worker Threads
- **Mechanism**: `_TTLCache` encapsulates `collections.OrderedDict` without any `threading.Lock`. Class-level caches `_related_cache` and `_waveform_cache` are read, updated (`pop`, `set`), and pruned (`popitem`) simultaneously across 10 worker threads in `self._executor`, causing intermittent `RuntimeError: OrderedDict mutated during iteration` or `KeyError`.
- **Impact**: 9/10 (Random thread worker crashes during concurrent SoundCloud lookups).
- **Proposed Fix**: Add `self._lock = threading.Lock()` to `_TTLCache` and guard all `get()`, `set()`, and `__len__()` methods with `with self._lock:`.

### [C-5] `services/soundcloud_service.py:268-270, 460, 560-561` — Unbounded `YouTubeService` Instantiation Storm & Socket Leaks
- **Mechanism**: On search or stream resolution fallback, `SoundCloudService` calls `YouTubeService(self.settings)` directly. Every new `YouTubeService` instance allocates a new `ThreadPoolExecutor(max_workers=10)` and `requests.Session()` which are never shut down or garbage collected promptly.
- **Impact**: 9/10 (Thread exhaustion, memory leak, WinError 10055 socket exhaustion under high search volume).
- **Proposed Fix**: Pass the shared singleton `YouTubeService` from `AppCore` or lazily instantiate and reuse a single instance.

### [C-6] `services/lufs_scanner.py:60, 100-102` — Background Daemon Thread Shared SQLite Connection Concurrency
- **Mechanism**: `LufsScannerService._scan_loop` runs on a background daemon thread and directly calls `self._core.db.conn.cursor()`, `execute()`, and `commit()` on the main-thread SQLite connection object without mutex synchronization or thread-local connections.
- **Impact**: 8/10 (`sqlite3.ProgrammingError` or database locked errors under concurrent library scanning and UI playback).
- **Proposed Fix**: Use connection-per-thread or access database via `DatabaseManager` thread-safe methods (`with self._core.db.lock:` or dedicated worker connection).

### [C-7] `core/api.py:2243` — `choose_cover_image()` Crashes on Missing `pywebview` Module Name
- **Mechanism**: Line 2243 executes `import pywebview` and `pywebview.OPEN_DIALOG`. The installed Python package is `webview` (imported as `import webview`). This raises `ModuleNotFoundError: No module named 'pywebview'` and always returns `{"success": False, "error": "No module named 'pywebview'"}`.
- **Impact**: 8/10 (Cover art picker dialog is completely broken).
- **Proposed Fix**: Change `import pywebview` to `import webview` and use `webview.OPEN_DIALOG`.

### [C-8] `ui/web_new/js/onboarding.js:60-68` vs `ui/web_new/index.html:2220-2222` — Dead Onboarding Navigation Buttons
- **Mechanism**: `onboarding.js` attempts to bind click events to `ob-btn-next-1`, `ob-btn-next-2`, `ob-btn-prev-2`, `ob-btn-prev-3`. `index.html` defines the modal footer buttons as `ob-btn-next` and `ob-btn-back`. The lookup returns `null`, leaving the buttons with zero event listeners.
- **Impact**: 9/10 (First-launch onboarding wizard navigation is completely unresponsive).
- **Proposed Fix**: Bind event listeners to `ob-btn-next` and `ob-btn-back` to advance/revert `currentStep` dynamically.

---

## TOP-10 FIXES BY IMPACT/COST

1. **[C-7] Fix `choose_cover_image` import** (`core/api.py`) — Cost: *1 min* | Impact: 8/10
   - Change `import pywebview` to `import webview; webview.OPEN_DIALOG`.
2. **[C-8] Fix onboarding navigation button bindings** (`ui/web_new/js/onboarding.js`) — Cost: *5 mins* | Impact: 9/10
   - Update button selectors to `ob-btn-next` and `ob-btn-back` and manage step transitions.
3. **[P-12] Fix `is_audio_file` NameError in watchdog** (`services/watchdog_service.py`) — Cost: *3 mins* | Impact: 8/10
   - Import `from utils.path_utils import is_audio_file` (or define audio extensions tuple helper).
4. **[P-16] Fix missing `import re` in YouTube service** (`services/youtube_service.py`) — Cost: *1 min* | Impact: 6/10
   - Add `import re` at the top of `services/youtube_service.py`.
5. **[C-4] Thread-safe `_TTLCache` in SoundCloud service** (`services/soundcloud_service.py`) — Cost: *5 mins* | Impact: 9/10
   - Add `threading.Lock()` inside `_TTLCache`.
6. **[C-3] Sanitize / escape arguments in elevated Zapret launcher** (`services/zapret_service.py`) — Cost: *10 mins* | Impact: 9/10
   - Sanitize `raw_args` and escape single quotes before passing to PowerShell command string.
7. **[C-1] Fix WMIC PID CSV parsing** (`services/zapret_service.py`) — Cost: *10 mins* | Impact: 9/10
   - Use `csv.reader` or `line.rsplit(",", 1)` to correctly extract `ProcessId` regardless of argument commas.
8. **[F-4] Fix lyrics sync milliseconds/seconds unit mismatch** (`ui/web_new/js/lyrics.js`, `events.js`) — Cost: *5 mins* | Impact: 8/10
   - Pass `posMs` (milliseconds) instead of `pos` (seconds) into `updateLyricsPosition(posMs)`.
9. **[F-8 / S-9] Fix search hotkey navigation** (`ui/web_new/js/hotkeys.js`) — Cost: *2 mins* | Impact: 7/10
   - Change `window.NeDotify.showPage('home')` to `window.NeDotify.showPage('search')`.
10. **[SEC-2] Add SSRF check to `/api/stream`** (`core/proxy.py`) — Cost: *5 mins* | Impact: 8/10
    - Insert `if not self._is_ssrf_safe_url(target_url): self.send_error(403, 'Forbidden destination'); return None` before fetching stream.

---

## SCORE TABLE

| Category | Weight | Score | Evidence IDs |
|----------|--------|-------|--------------|
| Functionality | 20 | 8 | [C-7], [C-8], [P-12], [F-4], [F-8 / S-9], [RPC-4] |
| Performance | 20 | 4 | [C-4], [C-5], [P-3], [P-6], [SQL-1], [SQL-2], [P-9] |
| Security | 15 | 3 | [C-3 / SEC-1], [SEC-2], [SEC-4 / B-6], [SEC-5] |
| Reliability | 15 | 3 | [C-1], [C-2], [C-6], [RPC-2], [F-5] |
| Code quality | 15 | 8 | [P-16], [SQL-4], [SQL-9], [SQL-10], [F-11], [F-12], [RPC-3] |
| UX/visual | 10 | 4 | [F-3], [F-10], [Z-7], [SQL-14] |
| Build/maintainability | 5 | 4 | [BUILD-1] |

**TOTAL: 34/100**

---

## BACKLOG DELTA (vs Cycle #2)

- **NEW CRITICAL (8 items)**:
  - `[C-1]` `services/zapret_service.py:170-178` (WMIC CSV comma splitting bug)
  - `[C-2]` `services/zapret_service.py:205, 668-678` (Elevated winws termination Access Denied orphan leak)
  - `[C-3]` `services/zapret_service.py:597-610` (Elevated PowerShell command injection in Zapret launcher)
  - `[C-4]` `services/soundcloud_service.py:17-42` (Unsynchronized `_TTLCache` concurrency race)
  - `[C-5]` `services/soundcloud_service.py:268, 460` (Unbounded `YouTubeService()` instantiation storm)
  - `[C-6]` `services/lufs_scanner.py:60, 100-102` (Background LUFS daemon thread shared SQLite connection)
  - `[C-7]` `core/api.py:2243` (`choose_cover_image` `import pywebview` ModuleNotFoundError)
  - `[C-8]` `ui/web_new/js/onboarding.js:60-68` (Onboarding button ID mismatch dead click bug)

- **NEW MAJOR & MINOR HIGHLIGHTS**:
  - `[P-12]` `services/watchdog_service.py:35` (`is_audio_file` NameError)
  - `[P-16]` `services/youtube_service.py:661` (`re` NameError in `download_audio_sync`)
  - `[SEC-2]` `core/proxy.py:196-214` (SSRF check missing on `/api/stream`)
  - `[F-4]` `ui/web_new/js/lyrics.js:116` (Lyrics sync seconds/ms unit mismatch)
  - `[SQL-1]` `core/database.py:69` (Missing index `idx_tracks_file_path` causing full table scans)

- **STILL (Carried from Cycle #2)**:
  - `[B-6 / SEC-4]` Loopback proxy wildcard CORS
  - `[S-9 / F-8]` Global search hotkey navigating to home
  - `[RPC-2..4]` Discord RPC unthrottled reconnects, missing 15s throttle, stop playback stub
  - `[SQL-3..4]` `lastfm_cache.db` unbounded growth, `tracks` composite `(source, source_id)` index

- **FIXED in Baseline**:
  - `CRIT-1` (Win32 GeoName crash)
  - `B-5` (SSRF redirect chain validation)
  - `SQL-1` (DB fragmentation VACUUM)
  - `SQL-2` (Index `idx_history_track_id`)
  - `RPC-1` (Connect race `_pending_update` buffer)
  - `Z-2` (Zapret premature autostart in init)
  - `S-STARTUP` (Startup hang & single instance guard)

---

## REQUIRES MANUAL TEST
1. Windows 11 (24H2) UAC prompt elevation behavior for `winws.exe` with PowerShell ExecutionPolicy set to Restricted.
2. Web Audio API `AudioContext` suspension and auto-resume behavior when audio output device switches to Bluetooth headphones.
3. System tray context menu events triggering `nedotify:tray_action` across Windows minimized vs hidden tray states.
4. Discord Rich Presence asset verification under Application Client ID `1329524021200158781`.
