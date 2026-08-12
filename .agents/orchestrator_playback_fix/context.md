# Project Context: AURA Music Playback Fix

## Overview
AURA Music is a desktop music application (Python backend, HTML/JS/CSS frontend in `ui/web_new/` or `ui/web/`). It uses VLC via a Python wrapper (`audio/engine.py`) to play streams from:
- YouTube (via `services/youtube_service.py` using `yt-dlp`)
- SoundCloud (via `services/soundcloud_service.py` using `yt-dlp`)
- Yandex Music (via `services/yandex_service.py`)

## Key Files
- `audio/engine.py`: Controls VLC audio engine, player status loop, track transition logic, and skipping.
- `services/youtube_service.py` / `services/soundcloud_service.py` / `services/yandex_service.py`: Extract stream URLs.
- `core/app.py`: Backend application lifecycle, routes/events, service initialization.
- `tests/test_nedotify.py`: Unit and E2E test suite.

## The Problems
1. **R1: VLC Playback Failure**:
   - Stream URLs retrieved from YouTube, SoundCloud, or Yandex Music often have session-specific signatures, cookies, or headers (e.g. `User-Agent`, `Referer`, `Cookie`).
   - VLC does not natively send these when requesting the stream URL, resulting in HTTP 403 Forbidden or other errors.
   - Solution: Run a small local HTTP server (proxy) in the Python backend. Stream URLs will be rewritten to local URLs (e.g., `http://localhost:<port>/stream?url=<encoded_url>&headers=<encoded_headers>`). The proxy will perform the HTTP request with the necessary headers/cookies and forward the bytes to VLC.
2. **R2: Infinite Skipping Loop**:
   - When VLC fails to play a track (enters `vlc.State.Error` or raises an error), the engine catches this and automatically calls `self.next()`.
   - If the next track also fails, the cycle repeats, causing the player to skip through the entire queue rapidly.
   - Solution: Detect error state, stop playback, emit an error event to the frontend UI, and do NOT skip to the next track automatically.
