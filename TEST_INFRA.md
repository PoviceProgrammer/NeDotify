# E2E Test Infra: AURA Music

## Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests are designed strictly from `ORIGINAL_REQUEST.md` and feature requirements. No dependency on implementation internals.
- **Progressive Testability**: Lower tiers test features in isolation without depending on unbuilt higher-level features.
- **Methodology**: 4-tier systematic approach (Category-Partition, Boundary Value Analysis, Pairwise Combinatorial Testing, Real-World Workloads).

---

## Feature Inventory
| # | Feature | Source (Requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|---------------------|:------:|:------:|:------:|:------:|
| 1 | Proxy Socket Abort Resilience | ORIGINAL_REQUEST §1 | 5 | 5 | ✓ | ✓ |
| 2 | Local File Stream Proxying | ORIGINAL_REQUEST §1 | 5 | 5 | ✓ | ✓ |
| 3 | Stream URL TTL & Auto Re-resolution | ORIGINAL_REQUEST §1 | 5 | 5 | ✓ | ✓ |
| 4 | Range Request & 206 Partial Content | ORIGINAL_REQUEST §1 | 5 | 5 | ✓ | ✓ |
| 5 | Frontend Audio Element Teardown | ORIGINAL_REQUEST §1 | 5 | 5 | ✓ | ✓ |
| 6 | Downloader Spotify Fallback | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 7 | Dedicated Download Directory | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 8 | Downloader UI Events & Error Handling | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 9 | Database Downloaded Status Integrity | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 10 | Windows Path & Filename Sanitization | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 11 | Downloader Queue Status & Error Reporting | ORIGINAL_REQUEST §2 | 5 | 5 | ✓ | ✓ |
| 12 | Restore Yandex Search Provider | ORIGINAL_REQUEST §3 | 5 | 5 | ✓ | ✓ |
| 13 | Non-blocking Asynchronous DB Search | ORIGINAL_REQUEST §3 | 5 | 5 | ✓ | ✓ |
| 14 | Provider Hard Timeouts & Silent Failure Patch | ORIGINAL_REQUEST §3 | 5 | 5 | ✓ | ✓ |
| 15 | Thread-Safe Bounded Search Cache | ORIGINAL_REQUEST §3 | 5 | 5 | ✓ | ✓ |
| 16 | Track Deduplication & UI Result Merging | ORIGINAL_REQUEST §3 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture
- **Runner**: `python -m pytest tests/` or `python run_tests.py`
- **Output Format**: standard pytest assertion results
- **Pass Criterion**: 100% pass rate (exit code 0) across all test cases

---

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Rapid Track Switch & Seek Stream Resilience | F1, F3, F4, F5 | High |
| 2 | Spotify Track Download & Offline Local Playback | F2, F6, F7, F8, F9, F10 | High |
| 3 | Concurrent Multi-Provider Search with Failed Provider | F12, F13, F14, F15, F16 | High |
| 4 | High Volume Cache Eviction Isolation | F7, F9, F10, F11 | High |
| 5 | Full User Session E2E Workflow (Search -> Stream -> Download -> Offline Play) | F1 to F16 | High |

---

## Coverage Thresholds
Given 16 identified features:
- **Tier 1 (Feature Coverage)**: ≥5 test cases per feature (16 × 5 = 80 test cases)
- **Tier 2 (Boundary & Edge Cases)**: ≥5 test cases per feature (16 × 5 = 80 test cases)
- **Tier 3 (Cross-Feature Combinations)**: ≥16 pairwise integration test cases
- **Tier 4 (Real-World Application Scenarios)**: ≥8 real-world end-to-end scenarios
- **Total Suite Minimum**: ≥184 test cases
