# Context & Technical Background

## Problem Statement
The current recommendation engine in `services/recommendation_service.py` relies heavily on `ytmusicapi` methods (`YTMusic.get_explore`, `get_watch_playlist`), which are subject to throttling, API changes, cookie issues, and external platform lock-in.

## Objective
Build a self-contained, independent recommendation system that:
1. Derives user taste directly from local SQLite history stored in `core/database.py`.
2. Queries Last.fm open API endpoints (`artist.getSimilar`, `artist.getTopTracks`, `track.getSimilar`, `chart.getTopTracks`) for music discovery and similarity recommendations.
3. Uses `SoundCloudService` and `YouTubeService` exclusively for track search and stream resolution (resolving `title` + `artist` to audio stream / video ID), NEVER for recommendation generation.
4. Generates contextual smart home feeds (Morning Vibe, Daytime Energy, Evening Chill, Night Vibe, Genre Mixes, Top Charts) based on local time and custom calculated taste weights.
5. Keeps full backward compatibility with the frontend (`ui/web_new/js/main.js`), matching existing track JSON objects (`title`, `artist`, `cover_url`, `source`, `source_id`).
6. Is programmatically verified via `tests/test_new_recommendations.py`.

## Subagent Working Directories
- Explorer M1: `.agents/explorer_m1`
- Worker M2: `.agents/worker_m2`
- Worker M3: `.agents/worker_m3`
- Worker M4: `.agents/worker_m4`
- Reviewer M4: `.agents/reviewer_m4`
- Auditor M4: `.agents/auditor_m4`
