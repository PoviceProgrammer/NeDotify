# Project: AURA Music Independent Recommendation Engine

## Architecture Overview
The goal was to replace YTMusic generative recommendation algorithms (`YTMusic.get_watch_playlist`, `get_explore`) in `services/recommendation_service.py` with an independent, hybrid recommendation engine that combines:
1. **User Taste Profile & Last.fm Scrobble Merging**: Extracted from local database history (`core/database.py`) and optional Last.fm scrobble history (if username configured in settings), aggregating listened tracks, artists, play counts, favorite tracks, and time-of-day listening patterns.
2. **Last.fm Open API**: Querying artist similarity (`artist.getSimilar`), artist top tracks (`artist.getTopTracks`), top tags/genres (`artist.getTopTags`), user scrobbles (`user.getRecentTracks`), and overall chart data (`chart.getTopTracks`, `chart.getTopArtists`).
3. **Resilient Track Resolution (TrackSourceProvider)**: SoundCloud primary audio source provider with YouTube fallback. Unresolved tracks drop out silently without breaking feeds. Zero hardcoding of API keys (env/config based with graceful degradation to local DB data when offline).
4. **Contextual Mixes, Smart Feed & Mix Sequencing**: Re-implementing `get_smart_home_feed` and `get_mixes` to generate personalized contextual mixes based on time of day (Morning Vibe, Daytime Energy, Evening Chill, Night Vibe), user genre clusters, new releases, and top charts with custom calculation weights. Applying harmonic transitions and energy curves (build-up -> peak -> wind-down) when sequencing mixes.
5. **Unified UI API Interface**: Ensuring 100% backward compatibility for `ui/web_new/js/main.js` and `core/api.py`. Output objects match standard UI fields: `title`, `artist`, `cover_url`, `source`, `source_id`, `source_url`, `duration`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Exploration & Interface Specs | Analyze `database.py`, `recommendation_service.py`, `main.js` APIs, Last.fm API patterns | None | DONE |
| M2 | User Taste Profile & Last.fm Engine | Build `UserTasteProfile` & `LastFMService` integration & track resolution | M1 | DONE |
| M3 | Smart Feed, Mixes & Sequencing | Refactor `services/recommendation_service.py` (`get_smart_home_feed`, `get_mixes`, energy sequencing, R4 resilience) | M2 | DONE |
| M4 | Verification & Forensic Audit | Write `tests/test_new_recommendations.py`, test `get_mixes`, schema verification, static check zero YTMusic calls, audit | M3 | DONE |

## Code Layout
- `services/recommendation_service.py` — Core recommendation service (refactored)
- `services/lastfm_service.py` — Last.fm API wrapper service (open endpoints + scrobble merging + key rotation + caching)
- `services/taste_profile.py` — User taste profile extractor (local DB + Last.fm scrobbles)
- `services/track_resolver.py` — Resilient TrackSourceProvider (SoundCloud primary -> YouTube fallback -> silent drop)
- `core/database.py` — Local SQLite DB manager (user history & taste data source)
- `core/services/recommendation.py` — High-level recommendation wrapper
- `core/api.py` — PyWebView API interface exposes recommendation endpoints to UI
- `ui/web_new/js/main.js` — Frontend UI consuming home feed and mixes
- `tests/test_new_recommendations.py` — Official automated verification script (created and 100% passing)

## Interface Contracts
### UI Track Schema
Each track item returned in feed/mix lists contains:
```json
{
  "title": "Track Title",
  "artist": "Artist Name",
  "cover_url": "https://... or file://...",
  "source": "soundcloud" | "youtube",
  "source_id": "video_or_track_id",
  "source_url": "https://...",
  "duration": 210
}
```
### Smart Home Feed Structure
```json
{
  "greeting": "Доброе утро" | "Добрый день" | "Добрый вечер" | "Доброй ночи",
  "sections": [ ... ]
}
```
