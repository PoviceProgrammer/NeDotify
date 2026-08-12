# Master Implementation & Verification Plan: AURA Music

## Overview
AURA Music requires critical fixes and performance optimizations across three core areas:
1. Audio Playback & Local HTTP Proxy (WinError 10053, pywebview stream handling, URL expiration/re-resolution, range requests).
2. Track Downloading (`core/downloader.py`, YouTube/SoundCloud/Spotify fallback, `.cache/downloads/`, DB update `is_downloaded = 1`, error resilience).
3. Search Optimization (parallel multi-provider async search, provider timeouts, caching, deduplication, non-blocking UI).

In addition, per Project Pattern guidelines, we establish a Dual-Track approach:
- **E2E Testing Track**: Build opaque-box test suite covering Tiers 1-4 (Feature, Edge, Pairwise, Real-world).
- **Implementation Track**: Execute Milestones M1, M2, M3, and M4 (Final integration + Tier 5 Adversarial Hardening).

## Work Decomposition Plan

### Step 0: Survey & Codebase Exploration (Parallel)
- **Explorer 1 (Playback/Proxy)**: Investigate audio streaming, proxy server implementation, stream handling, pywebview connection errors (WinError 10053), range requests, URL expiration/re-resolve mechanisms.
- **Explorer 2 (Track Downloading)**: Investigate `core/downloader.py`, downloader pipeline, Spotify fallback mechanisms, path handling (Windows/Cyrillic), DB schema and `is_downloaded` status update logic.
- **Explorer 3 (Search Optimization)**: Investigate search providers (Spotify, YouTube, SoundCloud, Yandex), current concurrency/blocking model, caching strategy, deduplication, UI integration.

### Step 1: Synthesis & Decomposition Document (`PROJECT.md` & `TEST_INFRA.md`)
- Aggregate Explorer reports.
- Compile global `Feature Inventory` in `PROJECT.md`.
- Establish module boundaries and interface contracts.
- Define test suite methodology and thresholds in `TEST_INFRA.md`.

### Step 2: Milestone Execution (Dual Track)
- **E2E Testing Orchestrator**: Create and publish complete E2E test harness & suite -> `TEST_READY.md`.
- **M1 Sub-orchestrator**: Audio Playback & Proxy Fixes (Explorer -> Worker -> Reviewer -> Gate loop).
- **M2 Sub-orchestrator**: Track Downloading & DB Sync (Explorer -> Worker -> Reviewer -> Gate loop).
- **M3 Sub-orchestrator**: Parallel Async Search & Caching (Explorer -> Worker -> Reviewer -> Gate loop).
- **M4 Sub-orchestrator**: Integration & Hardening (Phase 1: Pass 100% E2E tests; Phase 2: Tier 5 Adversarial Coverage Hardening).

### Step 3: Forensic Audit & Sentinel Reporting
- Run `teamwork_preview_auditor` for full forensic integrity verification across all modified modules.
- Present final verified report to Sentinel / Parent agent.
