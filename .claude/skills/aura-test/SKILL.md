---
name: aura-test
description: Run and write tests for AURA Music. Use before reporting any backend change as done, when a test fails, or when adding coverage for playback, proxy, downloader, search, recommendation or tray features. Explains the network marker, the venv, conftest fixtures and the opaque-box test conventions.
---

# Testing AURA Music

## Running

`pytest.ini` is the single source of truth (`testpaths = tests`,
`addopts = -m "not network"`). `run_tests.py` just delegates to it.

```powershell
& ".venv\Scripts\python.exe" -m pytest                      # full suite, no network
& ".venv\Scripts\python.exe" -m pytest tests\test_search_e2e.py -x -q
& ".venv\Scripts\python.exe" -m pytest -k "downloader" -q
& ".venv\Scripts\python.exe" -m pytest -m network           # opt into real network I/O
```

Tests marked `network` are **deselected by default** and hit live providers
(YouTube, SoundCloud, Spotify, Yandex). Never mark a new test `network` just
to make it pass — mock the provider instead.

Always run through `.venv\Scripts\python.exe`, not bare `python`.

## Conventions

- Suites are **opaque-box and requirement-driven**: they assert the interface
  contracts in `PROJECT.md` (proxy headers, `track_downloaded` /
  `download_failed` payloads, `search_results` shape), not internals.
- Mock all external network calls in unit tests. Shared fixtures live in
  `tests/conftest.py` — check there before building your own temp DB or app
  core.
- Feature areas map to files: `test_playback_e2e.py`, `test_downloader_e2e.py`,
  `test_search_e2e.py`, `test_search_concurrency.py`,
  `test_event_delivery_contract.py`, `test_stream_cache_age.py`, plus
  per-phase and per-audit suites (`test_global_phases_audit.py`,
  `test_audit_verify_scenarios.py`).
- Concurrency and socket-abort behaviour is regression-critical: a change to
  `core/proxy.py`, `core/downloader.py` or `services/base_service.py` needs the
  matching e2e suite run, not just a unit test.

## Definition of done

A backend change is not done until the relevant suite passes. If the suite
cannot run (missing dep, environment limit), say so explicitly with the error
rather than reporting success.
