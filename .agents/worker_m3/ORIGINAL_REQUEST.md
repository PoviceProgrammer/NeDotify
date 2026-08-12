## 2026-08-03T07:18:43Z
You are Worker M3 for the AURA Music recommendation engine project.
Your working directory is: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m3
Project root: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music

Objective:
Refactor `services/recommendation_service.py` to completely decouple recommendation generation from YTMusic (`get_watch_playlist`, `get_explore`), and re-implement `get_smart_home_feed` and `get_mixes` using `UserTasteProfile`, `LastFMService`, and `TrackResolver`.

Instructions:
1. Refactor `services/recommendation_service.py`:
   - Replace all `YTMusic.get_watch_playlist` and `YTMusic.get_explore` calls with `LastFMService` queries (`artist.getSimilar`, `artist.getTopTracks`, `track.getSimilar`, `chart.getTopTracks`, `chart.getTopArtists`) and `UserTasteProfile` data.
   - Update `_fetch_recommendations`, `get_feed`, `get_custom_artists`, `get_releases`, `get_charts`, `get_authentic_home`, `get_mixes`, and `get_smart_home_feed`.

2. Re-implement `get_smart_home_feed` and `get_mixes`:
   - Account for time of day:
     - 05:00 - 11:59: Morning Vibe ("Утренний вайб")
     - 12:00 - 17:59: Daytime Focus ("Дневной фокус")
     - 18:00 - 22:59: Evening Chill ("Вечерний релакс")
     - 23:00 - 04:59: Late Night Vibe ("Ночной вайб")
   - Calculate user taste weights (blend play count 0.4, recency 0.3, time of day match 0.2, favorite boost 0.1).
   - Generate 4 personalized home feed sections:
     1. Time-of-Day Contextual Section (e.g. "Утренний вайб")
     2. Custom Mixes / Personal Flow (e.g. "Микс: [Top Artist]", "Мой поток", "Любимый жанр: [Genre]")
     3. New Releases ("Новые релизы" via Last.fm top tracks / artist releases resolved via SoundCloud/YouTube)
     4. Top Charts ("Топ-чарты" via Last.fm `chart.getTopTracks` resolved via SoundCloud/YouTube)
   - Ensure `get_mixes` generates curated mixes for target artists, moods, and genres.

3. Backward Compatibility & UI Contracts:
   - Ensure `get_smart_home_feed` emits `smart_home_ready` and `authentic_home_ready` callback payloads with structure:
     `{ "greeting": "...", "sections": [ { "title": "...", "items": [ { "type": "track"|"custom_playlist", "title": "...", "artist": "...", "cover_url": "...", "source": "soundcloud"|"youtube", "source_id": "...", "source_url": "...", "duration": ... } ] } ] }`
   - Ensure every returned track dictionary includes mandatory UI fields: `title`, `artist`, `cover_url`, `source`, `source_id`, `source_url`, `duration`, `is_favorite`, `is_downloaded`.

4. Update `core/services/recommendation.py` and `core/api.py` if any references to YTMusic generative recommendations remain.

5. Test & Verify:
   - Run `pytest` and verify that all unit tests pass cleanly.
   - Verify zero calls to `YTMusic.get_explore` or `YTMusic.get_watch_playlist`.

6. Write handoff report in `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/.agents/worker_m3/handoff.md` with build/test results, and send a summary message back to orchestrator.

## 2026-08-03T07:19:11Z
**Context**: Updated User Requirements (R1 expansion, R4 resilience, R5 mix sequencing, expanded criteria)
**Content**: 
The user has updated the requirements for the recommendation architecture:
1. **R1 Expansion (Last.fm Scrobble Merging)**: Merge user taste profile with Last.fm user scrobbles (using `LastFMService.user.getRecentTracks` / `user.getTopArtists` or pylast if lastfm username is set in settings/config).
2. **R4 (Resilience & Extensibility)**:
   - Unified `TrackSourceProvider` / `TrackResolver`: SoundCloud as primary source, YouTube as fallback. Unresolved tracks drop out silently without breaking the feed.
   - Env/config key reading (with environment variables `LASTFM_API_KEY`, `SOUNDCLOUD_CLIENT_ID`, etc., or settings config) with zero hardcoding. If keys are missing or external APIs fail, degrade gracefully to local DB data so demo works out of the box.
   - SQLite response caching for Last.fm responses + rate limit backoff.
3. **R5 (Mix Sequencing)**:
   - Order tracks in mixes by genre/mood coherence. If BPM/key/energy metadata exists, apply harmonic transitions and an energy curve (build-up -> peak -> wind-down).
4. **Expanded Acceptance Criteria**:
   - Tests for `get_mixes`, JSON schema validation, failure mocks for Last.fm/SoundCloud, and static check asserting zero calls/imports to `YTMusic.get_watch_playlist` or `YTMusic.get_explore`.
