---
name: aura-test
description: Run and write tests for AURA Music. Use before reporting any backend change as done, when a test fails, or when adding coverage for playback, proxy, downloader, search, recommendation or tray features. Explains the network marker, the venv, conftest fixtures and the opaque-box test conventions.
---

# Testing AURA Music

## Running

`pytest.ini` is the single source of truth (`testpaths = tests`,
`addopts = -m "not network"`). `run_tests.py` just delegates to it.

```powershell
& ".venv_win\Scripts\python.exe" -m pytest                     # full suite, no network
& ".venv_win\Scripts\python.exe" -m pytest tests\test_proxy_security.py -x -q
& ".venv_win\Scripts\python.exe" -m pytest -k "downloader" -q
& ".venv_win\Scripts\python.exe" -m pytest -m network           # opt into real network I/O
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
- Shared fixtures live in `tests/conftest.py` — check there before building your
  own temp DB or app core. `redirect_home` is **opt-in, not autouse**, so a test
  that touches `~/.nedotify/` must request it explicitly.
- Feature areas map to files:

  | Area | Suites |
  |---|---|
  | API surface | `test_api_search.py`, `test_api_download.py`, `test_api_misc.py`, `test_api_audit_b.py` |
  | Proxy | `test_proxy_harness.py`, `test_proxy_paths.py`, `test_proxy_ranges.py`, `test_proxy_security.py`, `test_proxy_url_validation.py` |
  | Downloader | `test_downloader.py`, `test_downloader_cancel.py` |
  | Bridge & events | `test_emit_thread_safety.py`, `test_engine_notify.py` |
  | Resolver & cache | `test_engine_resolve.py`, `test_resolver_state.py`, `test_resolve_fallback_budget.py`, `test_cache_lru.py`, `test_lazy_service_deadlock.py` |
  | Settings & keybinds | `test_settings_manager.py`, `test_settings_flush.py`, `test_keybind_contracts.py` |
  | Frontend | `test_frontend_js.py`, `test_frontend_css_wiring.py`, `test_keybind_contracts.py`, `test_player_layout_geometry.py`, `test_sidebar_rail.py`, `test_visual_guard_css_decls.py`, `test_visual_guard_diff.py` |
  | Database | `test_database.py`, `test_db_integrity.py` |
  | Repo gates | `test_repo_hygiene.py`, `test_build_and_brand.py`, `test_conftest_home_isolation.py` |
  | Features | `test_lyrics_netease.py`, `test_queue.py`, `test_youtube_gating.py` |

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
