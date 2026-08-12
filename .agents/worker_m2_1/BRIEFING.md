# BRIEFING — 2026-08-07T18:31:25Z

## Mission
Implement Milestone 2: Track Downloading & DB Integrity (Features 6-11) for AURA Music.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m2_1
- Original parent: 5d9a0a8c-dba1-42be-820a-754fc376d579
- Milestone: Milestone 2 — Track Downloading & DB Integrity

## 🔒 Key Constraints
- Minimal change principle.
- No cheating, no hardcoding test outputs or facade implementations.
- Preserve original `source` in SQLite database (`is_downloaded = 1`, `file_path = ?`, do not change `source = 'local'`).
- Do not bypass DRM.
- Ensure downloaded files go to dedicated `downloads_dir` (`.cache/downloads/`), isolated from stream cache eviction.
- Correctly emit `track_downloaded` and `download_failed` UI events.
- Handle Windows path & filename sanitization for Cyrillic (NFC), illegal characters, reserved device names, length limits.

## Current Parent
- Conversation ID: 5d9a0a8c-dba1-42be-820a-754fc376d579
- Updated: 2026-08-07T18:31:25Z

## Task Summary
- **What to build**: Features 6-11 (Spotify fallback download, dedicated download directory, UI events & error feedback, DB downloaded status integrity, Windows path sanitization, queue resilience).
- **Success criteria**: All tests pass (`python run_tests.py` / `pytest tests/test_nedotify.py`), DB integrity intact, download directory isolated, events properly emitted and handled in frontend.
- **Interface contracts**: PROJECT.md and SCOPE.md
- **Code layout**: PROJECT.md § Code Layout

## Change Tracker
- **Files modified**: None yet
- **Build status**: Pending
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pending
- **Lint status**: Pending
- **Tests added/modified**: Pending

## Loaded Skills
- None loaded.

## Key Decisions Made
- [TBD]

## Artifact Index
- `.agents/worker_m2_1/DISPATCH.md` — Dispatch assignment from parent
- `.agents/worker_m2_1/BRIEFING.md` — Agent working memory
- `.agents/worker_m2_1/progress.md` — Heartbeat and progress log
- `.agents/worker_m2_1/handoff.md` — Final handoff report
