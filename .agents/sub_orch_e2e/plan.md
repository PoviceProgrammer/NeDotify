# E2E Testing Track Decomposition & Implementation Plan

## Overview
Target: Implement a 100% requirement-driven, opaque-box E2E test suite for AURA Music covering 16 features across 4 tiers as defined in `TEST_INFRA.md`.

Total Test Requirement Minimum:
- Tier 1: 16 features × 5 tests = 80 test cases
- Tier 2: 16 features × 5 tests = 80 test cases
- Tier 3: 16 pairwise integration tests
- Tier 4: 8 real-world application workflow scenarios
- Total: ≥184 test cases

---

## Sub-Milestone Breakdown

### Sub-Milestone 1: Playback & Proxy Test Suite (`tests/test_playback_e2e.py`)
- Target Features:
  - F1: Proxy Socket Abort Resilience (WinError 10053, BrokenPipeError, ConnectionResetError suppression)
  - F2: Local File Stream Proxying (`file_path` streaming without 400 rejection)
  - F3: Stream URL TTL & Auto Re-resolution (3h TTL, fast re-resolve on 403/410)
  - F4: Range Request & 206 Partial Content (Range header, byte boundaries)
  - F5: Frontend Audio Element Teardown (socket leak prevention)
- Target Quantities:
  - Tier 1: ≥25 tests (5 per feature)
  - Tier 2: ≥25 tests (5 per feature)
  - Subtotal: ≥50 tests

### Sub-Milestone 2: Downloader & Cache Test Suite (`tests/test_downloader_e2e.py`)
- Target Features:
  - F6: Downloader Spotify Fallback (YouTube search fallback)
  - F7: Dedicated Download Directory (`.cache/downloads/` isolation)
  - F8: Downloader UI Events & Error Handling (`track_downloaded`, `download_failed`)
  - F9: Database Downloaded Status Integrity (`is_downloaded = 1`, `file_path`)
  - F10: Windows Path & Filename Sanitization (Cyrillic, illegal Windows chars `\ / : * ? " < > |`)
  - F11: Downloader Queue Status & Error Reporting (`download_queue` updates, error logging)
- Target Quantities:
  - Tier 1: ≥30 tests (5 per feature)
  - Tier 2: ≥30 tests (5 per feature)
  - Subtotal: ≥60 tests

### Sub-Milestone 3: Search & Caching Test Suite (`tests/test_search_e2e.py`)
- Target Features:
  - F12: Restore Yandex Search Provider (all providers option)
  - F13: Non-blocking Asynchronous DB Search (thread pool offloading)
  - F14: Provider Hard Timeouts & Silent Failure Patch (4.0s timeout per provider, SoundCloud DRM fix)
  - F15: Thread-Safe Bounded Search Cache (Lock, LRU capacity limit)
  - F16: Track Deduplication & UI Result Merging (normalized title/artist matching)
- Target Quantities:
  - Tier 1: ≥25 tests (5 per feature)
  - Tier 2: ≥25 tests (5 per feature)
  - Subtotal: ≥50 tests

### Sub-Milestone 4: Integration & Real-World Application Scenarios (`tests/test_integration_e2e.py`)
- Target Scenarios & Combinations:
  - Tier 3: Pairwise interactions across Playback, Downloader, and Search (≥16 tests)
  - Tier 4: Real-world workflow E2E scenarios (≥8 scenarios):
    1. Rapid Track Switch & Seek Stream Resilience (F1, F3, F4, F5)
    2. Spotify Track Download & Offline Local Playback (F2, F6, F7, F8, F9, F10)
    3. Concurrent Multi-Provider Search with Failed Provider (F12, F13, F14, F15, F16)
    4. High Volume Cache Eviction Isolation (F7, F9, F10, F11)
    5. Full User Session E2E Workflow (Search -> Stream -> Download -> Offline Play) (F1 to F16)
    6. Cyrillic & Special Character Track Search, Download & Playback Lifecycle
    7. Expiry & Re-resolution during Continuous Stream Loop
    8. Multi-Provider Downloader Error Recovery & Queue Integrity Workflow
  - Subtotal: ≥24 tests

### Sub-Milestone 5: Verification & TEST_READY Publication
- Dispatch `teamwork_preview_reviewer` to review opaque-box test quality, coverage counts, pytest execution.
- Create `TEST_READY.md` at project root with test command and tier coverage breakdown.
