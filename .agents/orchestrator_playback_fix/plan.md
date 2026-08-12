# Plan for Fixing Audio Playback Issues

## Objectives
1. **R1: Fix VLC Playback Failure**: Resolve playback failure of streams from YouTube, SoundCloud, and Yandex Music in VLC by routing through a lightweight local HTTP proxy that passes the correct headers/cookies.
2. **R2: Fix Infinite Skipping Loop**: Prevent infinite skipping in `audio/engine.py` when VLC enters an Error state. Stop playback and trigger an error notification to the UI.

## Milestones and Decompositions
1. **Milestone 1: Exploration and Codebase Analysis**
   - Goal: Explore `audio/engine.py`, services (`youtube_service.py`, `soundcloud_service.py`, `yandex_service.py`), and backend api/app files to map out stream fetching, VLC initialization, error handling, and proxy placement.
   - Subagent: `teamwork_preview_explorer` (Explorer 1)

2. **Milestone 2: Implementation**
   - Goal: Implement the local HTTP proxy, rewrite stream URL resolution to point to the local proxy when necessary (or proxy all media streams), and modify VLC playback error handling in `audio/engine.py` to stop and notify instead of skipping infinitely.
   - Subagent: `teamwork_preview_worker` (Worker 1)

3. **Milestone 3: Verification & Validation**
   - Goal: Validate fixes against existing test suite (`tests/test_nedotify.py`), implement new tests if necessary, check using Reviewer, Challenger, and Forensic Auditor subagents.
   - Subagents: `teamwork_preview_reviewer` (Reviewer 1), `teamwork_preview_challenger` (Challenger 1), `teamwork_preview_auditor` (Auditor 1)

## Architecture Details
- **Local HTTP Proxy**: A lightweight server (e.g. running on a dynamic or static localhost port) that intercepts media requests, retrieves the actual media stream using the correct cookies/headers, and streams the chunked response to VLC.
- **Error State Handling**: Identify VLC player error events in `audio/engine.py`. When an error is encountered, abort the auto-skipping loop, stop the player, and push a UI notification.
