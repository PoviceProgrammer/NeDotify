# CYCLE #1 | 2026-08-19T20:32:00Z

## AGENTS STATUS & FINDINGS
| Agent | Track | Status | Findings Count | Highlights |
|---|---|---|:---:|---|
| T1 | Tests & Coverage | **BROKEN / DEGRADED** | 4 | `core/settings.py:22` c0000005 crash; 22/26 test files untracked in git; 89 passed / 27 failed |
| T2 | Build & Packaging | **BROKEN** | 13 | `.gitignore` ignores spec/icons/tests; 8 missing runtime deps in `requirements.txt`; missing hiddenimports |
| T3 | Discord RPC | **DEGRADED** | 10 | Connect race drops initial presence; missing 15s rate limit; stop playback is no-op stub; tests pass (5/5) |
| T4 | SQLite & Storage | **DEGRADED** (Clean) | 10 | 0 schema corruptions; 96.8% fragmentation in user DB; unindexed FK on history.track_id; FTS5 update churn |
| T5 | API + Bridge + Frontend | **DEGRADED** | 6 | 104 bridge methods (76 active JS, 0 broken contracts); 0 JS syntax errors; SSRF TOCTOU (B-5); CORS * (B-6) |
| T6 | Startup & Process Health | **DEGRADED** | 4 | Elevated `winws.exe` PID discovery fails leaking background orphan; premature autostart in `AppCore.__init__` |

---

## BACKLOG DELTA
- **NEW**: 
  - `core/settings.py:22 + win32_geo_name_access_violation` (CRITICAL)
  - `setup_pyinstaller.spec:23 + pyinstaller_missing_hiddenimports` (CRITICAL)
  - `services/zapret_service.py:162 + elevated_winws_pid_discovery_failure` (CRITICAL)
  - `core/services/discord_rpc.py:83 + initial_track_presence_dropped_on_connect` (MAJOR)
  - `core/services/discord_rpc.py:40 + unthrottled_connection_attempts_no_backoff` (MAJOR)
  - `core/services/discord_rpc.py:69 + missing_15s_rate_limiting` (MAJOR)
  - `core/api.py:836 + stop_playback_does_not_clear_presence` (MAJOR)
  - `ui/web_new/js/player.js:342 + resume_playback_resets_elapsed_time_to_zero` (MAJOR)
  - `core/database.py:24 + user_db_high_fragmentation_96_percent` (MAJOR)
  - `core/database.py:124 + unindexed_history_track_id_foreign_key` (MAJOR)
  - `core/database.py:307 + fts5_trigger_tracks_au_overactive_churn` (MAJOR)
  - `core/database.py:63 + missing_composite_index_tracks_source_source_id` (MAJOR)
  - `core/app.py:130 + zapret_autostart_premature_in_init_regression` (MAJOR)
  - `ui/web_new/js/hotkeys.js:175 + search_hotkey_navigates_to_home` (MAJOR) [S-9]
  - `ui/web_new/js/search.js:207 + multi_provider_search_lack_dedup` (MAJOR) [S-4]
- **FIXED**: None (Baseline observation cycle)
- **STILL (Confirmed Baseline Open Issues)**:
  - `S-STARTUP` (Startup hang regression under active fix on branch fix/startup-hang)
  - `D-1` (tests/ not tracked in git; 22/26 files untracked)
  - `D-3` (Fresh clone unbuildable: .gitignore ignores *.spec, installer.iss, icon.ico)
  - `D-5` (requirements.txt drift: 8 missing runtime dependencies)
  - `B-5` (SSRF TOCTOU & redirect bypass in core/proxy.py:217)
  - `B-6` (Proxy loopback CORS * in core/proxy.py:73)
  - `F-5` (CACHE_VERSION split in index.html:18)
  - `T-NEDOTIFY` (Legacy test suite broken tests)
  - `M-DEAD` (P2P / tray dead code paths)

---

## CRITICAL FINDINGS (Orchestrator Personally Re-Verified)

### 1. `core/settings.py:22 + win32_geo_name_access_violation`
- **Mechanism**: Win32 API `GetUserDefaultGeoName(LPWSTR geoName, int cchGeoName)` takes 2 parameters. Code calls `ctypes.windll.kernel32.GetUserDefaultGeoName(16, buf, 10)` passing 3 arguments where integer `16` (0x10) is interpreted as memory pointer. Writing to 0x10 causes a fatal Windows `0xC0000005 Access Violation` crash (unrecoverable SEH crash terminating Python) whenever `core.settings` is imported in test runners.
- **Proposed Fix**: Correct call to `ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 10)`.

### 2. `.gitignore:15,29,63-74 + fresh_clone_unbuildable_untestable` [D-1, D-3]
- **Mechanism**: `.gitignore` explicitly ignores `tests/`, `*.spec`, `installer.iss`, `icon.ico`, `icon.png`, `build_*.py`, and `run_tests.py`. Only 4 out of 26 test files and 0 spec/installer files are tracked in git. A fresh clone is completely unbuildable and untestable.
- **Proposed Fix**: Clean `.gitignore` to un-ignore `tests/`, `*.spec`, `installer.iss`, `icon.ico`, `icon.png`, and build scripts, and track them in version control.

### 3. `requirements.txt:1-13 + runtime_dependency_drift` [D-5]
- **Mechanism**: 8 packages imported and used across runtime services are omitted from `requirements.txt`: `yandex-music`, `ytmusicapi`, `miniaudio`, `numpy`, `watchdog`, `zeroconf`, `ifaddr`, `pythonnet`.
- **Proposed Fix**: Add all 8 missing runtime dependencies with appropriate version constraints to `requirements.txt`.

### 4. `setup_pyinstaller.spec:23-42 + pyinstaller_missing_hiddenimports`
- **Mechanism**: `hiddenimports` in PyInstaller specification omits dynamic packages (`yandex_music`, `ytmusicapi`, `miniaudio`, `numpy`, `pystray`, `PIL`, `pyloudnorm`, `soundfile`). PyInstaller standalone builds fail to resolve these modules at runtime.
- **Proposed Fix**: Populate `hiddenimports` in `setup_pyinstaller.spec` with all dynamic service and audio libraries.

### 5. `core/proxy.py:217 + ssrf_toctou_and_redirect_bypass` [B-5]
- **Mechanism**: `_is_ssrf_safe_url` resolves DNS during validation, but `urllib.request.urlopen` performs a second DNS resolution during connection, creating a DNS rebinding TOCTOU window. Furthermore, `urlopen` automatically follows HTTP 301/302 redirects without re-validating redirect target URLs against the SSRF filter.
- **Proposed Fix**: Implement a custom `HTTPRedirectHandler` that intercepts redirects and validates every destination host, or use socket-level connection verification.

### 6. `services/zapret_service.py:162 + elevated_winws_pid_discovery_failure`
- **Mechanism**: On Windows 11, `wmic` is deprecated/absent, and PowerShell `Get-CimInstance Win32_Process` returns null `CommandLine` when called by Medium Integrity processes for High Integrity (elevated) processes. `_scan_pids_with` returns `[]`, causing `_launch_elevated` to clear `run.pid` and assume failure, leaving elevated `winws.exe` as an untracked background orphan process holding WinDivert drivers.
- **Proposed Fix**: Write PID directly from the elevated launcher process into a handshake file in `%USERPROFILE%\.nedotify\zapret\run.pid`.

---

## NEXT FOCUS & STOP-CONDITION COUNTER
- **Consecutive zero-new-finding cycles**: 0 / 10
- **Next Cycle Focus**: 
  1. Monitor startup hang fix progress on branch `fix/startup-hang`.
  2. Verify test execution after `core/settings.py` Win32 fix is applied.
  3. Validate database VACUUM and indexing recommendations.
  4. Track resolution of Zapret PID discovery and Discord RPC rate-limiting.
