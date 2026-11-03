---
name: nedotify-test
description: Run and write NeDotify regression tests using the Windows project venv. Use to verify backend, bridge, playback, provider, UI or packaging changes, diagnose test failures, or add contract coverage. Explains network opt-in and user-profile isolation.
---

# Testing NeDotify

## Running

`pytest.ini` is the single source of truth (`testpaths = tests`,
`addopts = -m "not network"`). `run_tests.py` just delegates to it.

```powershell
& ".venv_win\Scripts\python.exe" -m pytest                     # full suite, no network
& ".venv_win\Scripts\python.exe" -m pytest tests\test_proxy_security.py -x -q
& ".venv_win\Scripts\python.exe" -m pytest -k "downloader" -q
& ".venv_win\Scripts\python.exe" -m pytest -m network           # opt into real network I/O
& ".venv_win\Scripts\python.exe" run_tests.py                  # same default pytest configuration
```

Tests marked `network` are **deselected by default** and hit live providers
(YouTube, SoundCloud, Spotify, Yandex). Never mark a new test `network` just
to make it pass — mock the provider instead.

Always run through `.venv_win\Scripts\python.exe`, not bare `python`. `.venv\` was
removed on 2026-10-03 and does not exist — `.gitignore` ignores `.venv*/`, so the
wrong name fails silently by looking plausible.

## Conventions

- Suites are **opaque-box**: they assert the interface contracts (proxy headers,
  `download_complete` / `download_failed` payloads, `search_results` shape), not
  internals. Mock all external network calls in unit tests.
- Shared fixtures live in `tests/conftest.py`, `tests/helpers.py`, and
  `tests/jsdom.py`. Collection is isolated by a temporary profile, and
  `redirect_home` is autouse with a fresh per-test profile. Never restore the
  real profile inside a test; pass explicit temporary paths when spawning a
  child process.
- Feature areas map to files:

  | Area | Suites |
  |---|---|
  | API surface | `test_api_search.py`, `test_api_download.py`, `test_api_misc.py`, `test_api_audit_b.py` |
  | Proxy | `test_proxy_harness.py`, `test_proxy_paths.py`, `test_proxy_ranges.py`, `test_proxy_security.py`, `test_proxy_url_validation.py` |
  | Downloader | `test_downloader.py`, `test_downloader_cancel.py` |
  | Resume & offline | `test_download_resume.py`, `test_offline_mode.py`, `test_offline_proxy.py`, `test_offline_resolve_callbacks.py` |
  | Bridge & events | `test_emit_thread_safety.py`, `test_engine_notify.py` |
  | Window & tray | `test_window_visibility.py`, `test_snap_layouts.py`, `test_window_resize_api.py` |
  | Resolver & cache | `test_engine_resolve.py`, `test_resolver_state.py`, `test_resolve_fallback_budget.py`, `test_cache_lru.py`, `test_lazy_service_deadlock.py` |
  | Playback recovery & resources | `test_playback_recovery.py`, `test_player_recovery_transitions.py`, `test_playback_startup_performance.py`, `test_player_resources.py` |
  | Settings & keybinds | `test_settings_manager.py`, `test_settings_flush.py`, `test_keybind_contracts.py` |
  | Frontend | `test_frontend_js.py`, `test_frontend_css_wiring.py`, `test_keybind_contracts.py`, `test_player_layout_geometry.py`, `test_sidebar_rail.py`, `test_visual_guard_css_decls.py`, `test_visual_guard_diff.py` |
  | Database | `test_database.py`, `test_db_integrity.py` |
  | Repo gates | `test_repo_hygiene.py`, `test_build_and_brand.py`, `test_conftest_home_isolation.py` |
  | Features | `test_lyrics_netease.py`, `test_queue.py`, `test_youtube_gating.py` |
  | Lyrics matching & performance | `test_verified_lyrics.py`, `test_lyrics_performance.py`, `test_catalog_lyrics_ui.py` |
  | Providers & matching | `test_provider_loading.py`, `test_provider_performance.py`, `test_track_resolver_matching.py`, `test_catalog_verification.py` |
  | Discovery & recommendations | `test_smart_search_bridge.py`, `test_recommendation_bridge.py`, `test_recommendation_signals.py`, `test_smart_playlists.py`, `test_taste_profile.py` |
  | Listening & profile | `test_measured_listening.py`, `test_listening_comparison.py`, `test_profile_view_ui.py` |
  | UI v2 views | `test_ui_v2_independence.py`, `test_flow_ui.py`, `test_library_view_ui.py`, `test_search_discovery_ui.py`, `test_settings_palette_ui.py` |

- Concurrency and socket-abort behaviour is regression-critical: a change to
  `core/proxy.py`, `core/downloader.py` or `services/base_service.py` needs the
  matching suite run, not just a unit test.
- `test_keybind_contracts.py`, `test_frontend_js.py` and parts of
  `test_build_and_brand.py` shell out to `node --check` and **skip when node is
  absent**. On a runner without node those gates do not run — treat them as
  unverified, not as passing.

## Definition of done

A backend change is not done until the relevant suite passes. If the suite
cannot run (missing dep, environment limit), say so explicitly with the error
rather than reporting success.

Use the suites that cover the changed contracts; this table is a starting point,
not a claim that every test file is listed. Keep regression fixtures for legacy
`AURA Music` autostart values and persisted `aura_*` keys: they verify migration
and compatibility, and must not be renamed as product copy.

Pytest checks do not establish that a real window is visible or that live audio
plays. For a requested UI launch or playback check, also follow
[nedotify-run](../nedotify-run/SKILL.md). Benchmarks and measured performance
claims use [nedotify-perf](../nedotify-perf/SKILL.md).
