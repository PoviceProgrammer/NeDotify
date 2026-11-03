# Windows audit remediation — test quality and API contracts

Scope: desktop test fixtures and regression tests. No application or GUI was
launched. Production API changes in this worktree were made by the integrating
agent; this report records the tests that now pin their behavior.

## Audit findings

| Audit ID | Status | Evidence |
|---|---|---|
| AUD-454 | Fixed | `tests/test_emit_thread_safety.py` patches `core.api._MAIN_THREAD` and waits on an event from the fake evaluator. The UI-thread branch would fail if removed. |
| AUD-456 | Fixed | `tests/test_lazy_service_deadlock.py` constructs `AppCore` through its real initializer with stubbed components, exercising the production reentrant lock and lazy service properties under nested and concurrent access. |
| AUD-457 | Fixed | `tests/test_android_source_gates.py` skips if PowerShell or the Android product tree is absent. |
| AUD-478 | Fixed | `tests/test_resolve_fallback_budget.py` invokes `AppCore.re_resolve_stream_url_async`; an injected monotonic clock and fake timer make the late-callback expiry deterministic. |
| AUD-480 | Fixed | Lyrics timing assertions use synchronization events, search no longer enforces a machine-specific latency threshold, and taste-profile fixtures use timezone-aware UTC timestamps. |
| AUD-481 | Fixed | Shared Node, proxy, player, recommendation, and provider helpers live in `tests/jsdom.py` and `tests/helpers.py`; no test imports another `test_*.py` module. |
| AUD-482 | Fixed | The autouse fixture snapshots and restores shared service caches, SoundCloud verdict caches, taste-profile cache, and URL DNS cache. Base service caches and its shared executor are isolated per test. |
| AUD-487 | Fixed | The `api` fixture yields the `AppApi` and calls `cleanup()` during teardown. Cleanup tests replace both shared executor hooks so they cannot shut down a global pool used later. |

## API contract regressions

- Cover tests use valid Pillow images, call `choose_cover_image()` through a
  mocked native file dialog, and then verify the selected file is stored as
  `cover_{track_id}.{ext}` with its matching MIME type. Unapproved arbitrary
  paths are not used as test inputs.
- Playlist import rollback tests install a SQLite trigger that aborts midway
  through the actual atomic import transaction. They verify both preexisting
  playlist membership and newly created playlists/tracks survive or roll back
  as a unit.
- Offline-mode tests verify that enabling offline playback preserves the
  current queue while filtering the library to locally available tracks. Tests
  invoking `AppCore.__new__` initialize the production service-lock and
  resolver lifecycle fields.
- Recommendation tests verify the immediate pending response, the asynchronous
  `recommendations_ready` event, request IDs, result limits, and sanitized error
  payloads.
- Resize bridge tests require the Snap subclass to be installed and the native
  window to have `WS_THICKFRAME`; the missing-ready and missing-style paths are
  checked as rejections.
- Empty search verifies the `search_completed` event with the normalized empty
  query, so the caller receives completion instead of waiting indefinitely.
- Avatar bridge verification calls `get_artists_avatars` and asserts the
  provider completion event; it does not depend on a particular source quote.

## Verification

Focused quality, API, proxy, scanner, and adjacent regression run:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q tests/test_api_audit_b.py tests/test_api_f1_audit.py tests/test_api_search.py tests/test_conftest_home_isolation.py tests/test_db_core_fixes_f2.py tests/test_emit_thread_safety.py tests/test_lazy_service_deadlock.py tests/test_android_source_gates.py tests/test_resolve_fallback_budget.py tests/test_lyrics_performance.py tests/test_taste_profile.py tests/test_recommendation_bridge.py tests/test_window_resize_api.py tests/test_provider_loading.py tests/test_stream_startup_performance.py tests/test_hls_playback.py tests/test_player_resources.py tests/test_frontend_js.py tests/test_proxy_harness.py tests/test_proxy_security.py tests/test_proxy_paths.py tests/test_proxy_ranges.py tests/test_proxy_fixes_f5.py tests/test_offline_proxy.py tests/test_player_recovery_transitions.py tests/test_provider_performance.py tests/test_cache_performance.py tests/test_recommendation_service.py tests/test_recommendation_signals.py tests/test_catalog_lyrics_ui.py tests/test_measured_listening.py tests/test_file_scanner.py
```

Result: **479 passed**. The related API-contract set also completed with
**133 passed**:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q tests/test_offline_mode.py tests/test_offline_resolve_callbacks.py tests/test_api_audit_b.py tests/test_api_f1_audit.py tests/test_playlist_import_atomic.py tests/test_recommendation_bridge.py
```

Pytest printed settings-flush warnings from tests that intentionally close or
invalidate their database writers. No live provider was used for the listed
contract tests, and the application window was not opened.
