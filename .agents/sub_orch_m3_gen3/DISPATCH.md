## 2026-08-07T18:28:42Z

You are the Sub-orchestrator for Milestone 3: Search Optimization & Caching in AURA Music.

Your Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m3_gen3

Mandatory Inputs:
1. Read ORIGINAL_REQUEST.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. Read PROJECT.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. Read Survey Report at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_search/handoff.md

Mission:
Execute Milestone 3 (Search Optimization):
- Feature 12: Restore & Integrate Yandex Music Search: add `"yandex"` to `services` dict in `core/api.py`, remove Yandex filter in `search.js`, add Yandex option and "All Providers" ("Все источники") option in `index.html` dropdown.
- Feature 13: Offload local SQLite DB search (`db.search_tracks`) from main thread to `ThreadPoolExecutor` worker pool in `core/api.py`. Add DB indexes on `tracks(title)` and `tracks(artist)` in `core/database.py`.
- Feature 14: Implement 4.0s hard per-provider execution timeouts in backend search dispatcher; fix `SoundCloudService` DRM error branch to always execute callback/error_callback; emit `search_completed` event.
- Feature 15: Refactor `BaseMusicService._search_cache` to use `threading.Lock()` and an LRU eviction policy with capacity limit (e.g. 300 entries) for thread-safe bounded caching.
- Feature 16: Implement track deduplication in `search.js` / backend based on normalized `artist - title`, merging duplicate tracks from multiple providers and preventing UI result jittering.

Procedure:
1. Initialize your BRIEFING.md, progress.md, plan.md, and SCOPE.md in your working directory.
2. Run iteration loop: Explorer -> Worker (`teamwork_preview_worker`) -> Reviewer (`teamwork_preview_reviewer`) -> Challenger (`teamwork_preview_challenger`) -> Auditor (`teamwork_preview_auditor`).
3. Gate check: Require worker to run tests (`python run_tests.py`). All reviewers must APPROVE, challenger must confirm correctness, auditor must report CLEAN. Binary veto on audit failure.
4. Record verdicts in GATE_STATUS.md. Mark milestone DONE when passed.

Constraints:
- DISPATCH-ONLY. Do NOT modify source code directly.
- Include MANDATORY INTEGRITY WARNING in worker prompt.
- Update progress.md continuously. Send completion handoff message when done.
