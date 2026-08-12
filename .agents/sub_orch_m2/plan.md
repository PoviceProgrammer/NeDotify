# Execution Plan: Milestone 2 (Track Downloading & DB Integrity)

## Phase 1: Exploration
- Dispatch 3 Explorers in parallel (`teamwork_preview_explorer`) to investigate:
  - `core/downloader.py`, `utils/cache_manager.py`, `core/api.py`, `ui/web_new/js/events.js`, `utils/path_utils.py` (if present or needs creation)
  - Detailed implementation design for Features 6-11
  - Test coverage requirements in `tests/test_nedotify.py` / `run_tests.py`

## Phase 2: Implementation (Worker)
- Dispatch 1 Worker (`teamwork_preview_worker`) armed with Explorer findings and MANDATORY INTEGRITY WARNING to:
  1. Create/Implement `utils/path_utils.py` for Cyrillic and Windows illegal path sanitization.
  2. Update `core/downloader.py` for Spotify YouTube fallback search.
  3. Update `utils/cache_manager.py` & `core/downloader.py` to route downloads to `.cache/downloads/` and ensure `enforce_cache_limit` only purges `streams_dir`.
  4. Preserve original `source` provider in SQLite DB updates (`is_downloaded = 1`, `file_path = ...`, keep `source` intact).
  5. Fix event emitting: backend emits `track_downloaded` and `download_failed`; frontend `events.js` handles both events.
  6. Resilient error handling in queue status (`'failed'`), preventing false `is_downloaded` flags.
  7. Run test suite `python run_tests.py` and report detailed results.

## Phase 3: Review (2 Reviewers)
- Dispatch 2 Reviewers independently to verify code quality, correctness, and adherence to requirements.

## Phase 4: Stress Verification (2 Challengers)
- Dispatch 2 Challengers independently to empirically stress test downloading, Spotify fallback, path sanitization, cache separation, and error events.

## Phase 5: Forensic Audit (1 Auditor)
- Dispatch 1 Forensic Auditor (`teamwork_preview_auditor`) to verify zero cheating/hardcoding/facades.

## Phase 6: Gate Decision & Handoff
- Evaluate gate results in `GATE_STATUS.md`. If passed, report completion to parent.
