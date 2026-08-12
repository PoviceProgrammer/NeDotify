## 2026-08-07T15:27:50Z

You are the Sub-orchestrator for Milestone 1: Audio Playback & Local HTTP Proxy Fixes in AURA Music.

Your Working Directory:
c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/sub_orch_m1

Mandatory Inputs:
1. Read ORIGINAL_REQUEST.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/ORIGINAL_REQUEST.md
2. Read PROJECT.md at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/PROJECT.md
3. Read Survey Report at:
   c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/explorer_playback/handoff.md

Mission:
Execute Milestone 1 (Playback & Proxy Fixes):
- Feature 1: Suppress and handle socket connection resets (`WinError 10053`, `BrokenPipeError`, `ConnectionResetError`) in `core/proxy.py` (`_proxy_stream`) on `self.wfile.write()` without error logs or crashes.
- Feature 2: Support local file streaming in `core/proxy.py` (`_is_safe_url` / `_find_playable_url`) so downloaded files stream cleanly with HTTP 200/206.
- Feature 3: Reduce YouTube/SoundCloud stream cache TTL to 3h; implement fast non-blocking URL re-resolution on HTTP 403/410 errors.
- Feature 4: Handle HTTP Range requests (`bytes=start-end`) and deliver exact byte ranges with 206 Partial Content.
- Feature 5: Update frontend `ui/web_new/js/player.js` (`cancelActiveFade`, error handlers) to clear `oldAudio.src` (`oldAudio.removeAttribute('src'); oldAudio.load()`) to prevent background socket leaks.

Procedure:
1. Initialize your BRIEFING.md, progress.md, plan.md, and SCOPE.md in your working directory.
2. Run iteration loop: Explorer -> Worker (`teamwork_preview_worker`) -> Reviewer (`teamwork_preview_reviewer`) -> Challenger (`teamwork_preview_challenger`) -> Auditor (`teamwork_preview_auditor`).
3. Gate check: Require worker to run tests (`python run_tests.py`). All reviewers must APPROVE, challenger must confirm correctness, and auditor must report CLEAN. Hard veto on audit failure.
4. Record verdicts in GATE_STATUS.md. Mark milestone DONE when passed.

Constraints:
- DISPATCH-ONLY. Do NOT modify source code directly.
- Include MANDATORY INTEGRITY WARNING in worker prompt.
- Update progress.md continuously. Send completion handoff message when done.
