# Original User Request

## 2026-07-13T20:53:11Z

You are the Project Orchestrator (archetype: teamwork_preview_orchestrator).
Your working directory is: c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\orchestrator_playback_fix
Your mission is to fix the audio playback issues in AURA Music app (R1: Fix VLC Playback Failure, R2: Fix Infinite Skipping Loop) according to the requirements and acceptance criteria in c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\ORIGINAL_REQUEST.md.

Specifically:
- R1: Fix VLC Playback Failure by resolving issues where stream URLs extracted via yt-dlp (YouTube, SoundCloud) and Yandex Music fail to play in VLC (e.g. cookies or headers mismatch). You may implement a lightweight local HTTP proxy in the python backend to stream data to VLC.
- R2: Fix Infinite Skipping Loop in audio/engine.py when VLC enters an Error state. Stop playback and display an error notification instead of infinitely skipping.

Please follow these steps:
1. Create plan.md, progress.md, and context.md in your working directory (c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\orchestrator_playback_fix).
2. Formulate a plan, decompose milestones, and spawn explorer and worker/reviewer subagents to implement and verify the changes.
3. Update progress.md frequently.
4. When all milestones are complete, notify the Sentinel (conv ID: 01bdfdd6-f3b0-48f5-969b-0e92ef87ef92) with a victory claim.
