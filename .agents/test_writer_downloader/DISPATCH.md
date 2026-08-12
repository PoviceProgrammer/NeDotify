## 2026-08-07T15:28:30Z
You are test_writer_downloader, an E2E Test Writer subagent.

Your Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/test_writer_downloader

Mandatory Input Files (READ THESE FIRST BEFORE WRITING TESTS):
1. ORIGINAL_REQUEST.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. PROJECT.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. TEST_INFRA.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/TEST_INFRA.md

Objective:
Create a comprehensive, opaque-box, requirement-driven E2E test suite file:
`c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/tests/test_downloader_e2e.py`

Scope: Features 6 through 11 (Track Downloader & Cache System)
- Feature 6: Downloader Spotify Fallback (YouTube search fallback mechanism)
- Feature 7: Dedicated Download Directory (.cache/downloads/ file isolation, immune to stream cache eviction)
- Feature 8: Downloader UI Events & Error Handling (track_downloaded and download_failed events)
- Feature 9: Database Downloaded Status Integrity (setting is_downloaded = 1 and file_path, preserving original source provider)
- Feature 10: Windows Path & Filename Sanitization (Cyrillic characters and illegal Windows path characters \ / : * ? " < > |)
- Feature 11: Downloader Queue Status & Error Reporting (updating download_queue status, logging errors, preventing false is_downloaded)

Quantity Thresholds:
- Tier 1 (Feature Coverage): AT LEAST 5 test cases per feature (≥30 tests)
- Tier 2 (Boundary & Corner Cases): AT LEAST 5 test cases per feature (≥30 tests)
- Total in test_downloader_e2e.py: AT LEAST 60 distinct test cases using pytest / unittest.

Test Quality Requirements:
- Opaque-box requirement-driven testing strictly adhering to spec.
- Write executable, valid Python test code using pytest fixtures or unittest.
- Test actual methods/modules in `core/downloader.py`, `utils/cache_manager.py`, `utils/path_utils.py`, `core/database.py`, `core/api.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Completion Criteria:
1. `tests/test_downloader_e2e.py` written with ≥60 tests.
2. Run pytest on `tests/test_downloader_e2e.py` to ensure zero syntax or collection errors.
3. Write `handoff.md` and `progress.md` in your working directory `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/test_writer_downloader/`.
4. Send a message to parent summarizing results.
