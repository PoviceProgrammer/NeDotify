## 2026-08-07T15:27:50Z
<USER_REQUEST>
You are the Sub-orchestrator for Milestone 2: Track Downloading & DB Integrity in AURA Music.

Your Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m2

Mandatory Inputs:
1. Read ORIGINAL_REQUEST.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. Read PROJECT.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. Read Survey Report at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_downloader/handoff.md

Mission:
Execute Milestone 2 (Track Downloading):
- Feature 6: Implement YouTube fallback search in `core/downloader.py` for Spotify track downloads (`source == "spotify"`).
- Feature 7: Isolate downloaded tracks to dedicated directory `.cache/downloads/` and ensure `CacheManager.enforce_cache_limit` only cleans `streams_dir`.
- Feature 8: Fix UI events & error feedback: backend emits `track_downloaded` and `download_failed`; frontend `events.js` handles both events and updates offline track list & error toasts.
- Feature 9: Database update integrity: set `is_downloaded = 1` and `file_path = ...`, but preserve original `source` provider (`youtube`/`soundcloud`/`spotify`) without changing to `'local'`.
- Feature 10: Implement Windows path & filename sanitization utility (`path_utils.py`) handling Cyrillic Unicode characters and illegal Windows characters (`\ / : * ? " < > |`).
- Feature 11: Queue status tracking & error logging resilience: update `download_queue` status to `'failed'`, log errors, prevent false `is_downloaded` flags.

Procedure:
1. Initialize your BRIEFING.md, progress.md, plan.md, and SCOPE.md in your working directory.
2. Run iteration loop: Explorer -> Worker (`teamwork_preview_worker`) -> Reviewer (`teamwork_preview_reviewer`) -> Challenger (`teamwork_preview_challenger`) -> Auditor (`teamwork_preview_auditor`).
3. Gate check: Require worker to run tests (`python run_tests.py`). All reviewers must APPROVE, challenger must confirm correctness, auditor must report CLEAN. Binary veto on audit failure.
4. Record verdicts in GATE_STATUS.md. Mark milestone DONE when passed.

Constraints:
- DISPATCH-ONLY. Do NOT modify source code directly.
- Include MANDATORY INTEGRITY WARNING in worker prompt.
- Update progress.md continuously. Send completion handoff message when done.
</USER_REQUEST>
