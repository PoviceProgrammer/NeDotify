## 2026-08-03T07:24:49Z
<USER_REQUEST>
You are Worker M4 for the AURA Music recommendation engine project.
Your working directory is: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m4
Project root: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music

Objective:
Create the official automated test script `tests/test_new_recommendations.py` and execute the complete test suite to programmatically verify the new recommendation engine.

Instructions:
1. Create `tests/test_new_recommendations.py`:
   - Test `get_smart_home_feed` with mock listening history in local SQLite DB.
   - Test `get_mixes` generation.
   - Test network failure / mock fallbacks for Last.fm and SoundCloud APIs (confirming zero crashes and graceful local DB fallback).
   - Test static AST and mock assertions confirming ZERO calls or imports to `YTMusic.get_explore` or `YTMusic.get_watch_playlist` in `services/recommendation_service.py` and `core/api.py`.
   - Validate JSON output format strictly matches expected UI structure (`greeting`, `sections`, `items` containing mandatory UI track fields `title`, `artist`, `cover_url`, `source`, `source_id`, `source_url`, `duration`, `is_favorite`, `is_downloaded`).

2. Execute full test suite:
   - Run `python pytest.py tests/test_new_recommendations.py` and `python run_tests.py`.
   - Ensure 100% of test cases pass cleanly with exit code 0.

3. Write a comprehensive handoff report to `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m4/handoff.md` detailing all test names, assertions, and test output logs. Send a summary message back to orchestrator.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
</USER_REQUEST>
