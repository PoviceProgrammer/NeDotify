## 2026-08-03T07:16:42Z
You are Worker M2 for the AURA Music recommendation engine project.
Your working directory is: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m2
Project root: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music

Objective:
Implement the core User Taste Profile extractor, Last.fm open API service wrapper (`services/lastfm_service.py`), and track resolution helper (SoundCloud/YouTube resolution).

Instructions:
1. Create `services/lastfm_service.py`:
   - Inherit from `BaseMusicService` (or standard class with caching/session support).
   - Implement queries for:
     - `artist.getSimilar(artist, limit=10)`
     - `artist.getTopTracks(artist, limit=10)`
     - `artist.getTopTags(artist)`
     - `track.getSimilar(artist, track, limit=10)`
     - `chart.getTopTracks(limit=20)`
     - `chart.getTopArtists(limit=20)`
   - Implement API key rotation (keys: `b25b959554ed76058ac220b7b2e0a026`, `2c8038f0d5757d5f0426315220c8f133`, `4cb0edd8ea11e4f641723f031a770edc`).
   - Implement response caching (TTL: 7 days for recommendations, 24 hours for charts) using in-memory or SQLite caching.
   - Ensure graceful error handling & fallbacks if Last.fm fails, returns 429/403, or if offline.

2. Create `UserTasteProfile` class in `services/recommendation_service.py` (or helper module `services/taste_profile.py`):
   - Method `build_from_db(db)`: Query local SQLite `history` and `tracks` tables via `db` connection/manager for top artists, top tracks, recent history, genre distribution, favorite tracks, and time-of-day listening habits.
   - Method `get_seed_artists(limit=5)`: Returns top seed artist names.
   - Method `get_seed_tracks(limit=5)`: Returns top seed track dicts.
   - Method `get_time_of_day_vibe()`: Returns string representation of time slot ('morning', 'afternoon', 'evening', 'night') based on local time and history.

3. Create Track Resolution Helper:
   - Implement track search resolution mapping recommended metadata `(title, artist)` into playable UI track dictionaries:
     1. Search local `tracks` table first for local match.
     2. Query `SoundCloudService` search (`soundcloud_service.py`).
     3. Fallback to `YouTubeService` search (`youtube_service.py`).
     4. Format track dictionary with UI keys: `title`, `artist`, `cover_url`, `source`, `source_id`, `source_url`, `duration`.

4. Run unit tests / verification scripts to verify that `LastFMService`, `UserTasteProfile`, and Track Resolution function cleanly and pass all builds/tests.
5. Write a handoff report in `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m2/handoff.md` with documented build/test results, and send a summary message back to orchestrator.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
