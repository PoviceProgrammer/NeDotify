## 2026-08-07T15:28:07Z

You are test_writer_integration, an E2E Test Writer subagent.

Your Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/test_writer_integration

Mandatory Input Files (READ THESE FIRST BEFORE WRITING TESTS):
1. ORIGINAL_REQUEST.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. PROJECT.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. TEST_INFRA.md: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/TEST_INFRA.md

Objective:
Create a comprehensive, opaque-box, requirement-driven E2E test suite file:
`c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/tests/test_integration_e2e.py`

Scope: Tiers 3 & 4 (Cross-Feature Combinations & Real-World Application Scenarios)
- Tier 3: Pairwise interactions across Playback, Downloader, and Search (AT LEAST 16 distinct tests)
- Tier 4: Real-world workflow E2E scenarios (AT LEAST 8 distinct scenarios):
  1. Rapid Track Switch & Seek Stream Resilience (F1, F3, F4, F5)
  2. Spotify Track Download & Offline Local Playback (F2, F6, F7, F8, F9, F10)
  3. Concurrent Multi-Provider Search with Failed Provider (F12, F13, F14, F15, F16)
  4. High Volume Cache Eviction Isolation (F7, F9, F10, F11)
  5. Full User Session E2E Workflow (Search -> Stream -> Download -> Offline Play) (F1 to F16)
  6. Cyrillic & Special Character Track Search, Download & Playback Lifecycle
  7. Expiry & Re-resolution during Continuous Stream Loop
  8. Multi-Provider Downloader Error Recovery & Queue Integrity Workflow

Quantity Thresholds:
- Tier 3 (Pairwise Interactions): AT LEAST 16 tests
- Tier 4 (Real-World Scenarios): AT LEAST 8 scenarios
- Total in test_integration_e2e.py: AT LEAST 24 distinct test cases using pytest / unittest.

Test Quality Requirements:
- Opaque-box requirement-driven testing strictly adhering to spec.
- Write executable, valid Python test code using pytest fixtures or unittest.
- Test cross-module integration across `core/proxy.py`, `core/downloader.py`, `core/api.py`, `services/*`, `utils/*`, `core/database.py`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Completion Criteria:
1. `tests/test_integration_e2e.py` written with ≥24 tests.
2. Run pytest on `tests/test_integration_e2e.py` to ensure zero syntax or collection errors.
3. Write `handoff.md` and `progress.md` in your working directory `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/test_writer_integration/`.
4. Send a message to parent summarizing results.
