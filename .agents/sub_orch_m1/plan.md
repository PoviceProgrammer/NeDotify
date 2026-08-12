# Implementation Plan — Milestone 1: Audio Playback & Local HTTP Proxy Fixes

## Phase 1: Exploration & Fix Strategy Design
Dispatch 3 Explorer agents (`teamwork_preview_explorer`) in parallel to analyze target codebase files and prepare detailed implementation blueprints:
- **Explorer 1**: `core/proxy.py` socket error suppression (`ConnectionResetError`, `WinError 10053`), local file streaming in `_is_safe_url` / `_find_playable_url`, and Range request 206 Partial Content byte math.
- **Explorer 2**: Stream cache TTL reduction to 3 hours (`10800`s) in `database.py`/`proxy.py` and non-blocking re-resolution on 403/410 upstream errors.
- **Explorer 3**: Frontend socket teardown in `ui/web_new/js/player.js` (`cancelActiveFade`, error handlers) and test harness validation (`run_tests.py`).

## Phase 2: Implementation
Dispatch 1 Worker agent (`teamwork_preview_worker`) with:
- Consolidated Explorer recommendations.
- Scope document (`SCOPE.md`) and project instructions.
- Mandatory Integrity Warning.
- Target files: `core/proxy.py`, `core/database.py`, `core/app.py`, `ui/web_new/js/player.js`, `tests/test_proxy.py`.
- Execution of `python run_tests.py`.

## Phase 3: Verification & Auditing
Dispatch verification team in parallel:
- 2 Reviewers (`teamwork_preview_reviewer`) to audit code quality, regression safety, and interface compliance.
- 1 Challenger (`teamwork_preview_challenger`) to stress-test proxy socket disconnects, range requests, and TTL re-resolving.
- 1 Auditor (`teamwork_preview_auditor`) for forensic integrity auditing.

## Phase 4: Gate Verification
Evaluate verdicts in `GATE_STATUS.md`.
- All tests pass.
- All Reviewers APPROVE.
- Challenger confirms correctness.
- Forensic Auditor reports CLEAN (Hard Veto).
Mark milestone DONE upon gate pass.
