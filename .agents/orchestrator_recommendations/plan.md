# Master Plan: Independent Recommendation Engine Architecture

## Objective
Build a completely new, independent recommendation architecture for AURA Music that replaces YTMusic algorithms with open APIs (Last.fm, SoundCloud) and local database history stats.

## Strategy & Iteration Design
We will follow the Project Orchestrator pattern. For each milestone:
1. **Explore**: Dispatch `teamwork_preview_explorer` to inspect existing code, schemas, APIs, and specify exact changes needed.
2. **Implement**: Dispatch `teamwork_preview_worker` to write modules, implementations, and unit test suites.
3. **Review**: Dispatch `teamwork_preview_reviewer` to review code quality, backward compatibility, and edge case handling.
4. **Audit**: Dispatch `teamwork_preview_auditor` to conduct forensic integrity verification (ensuring clean implementation, no mock facades or hardcoded cheating).
5. **Gate**: Collect all verdicts. If clean and passing, advance milestone.

## Milestone Breakdown

### Milestone 1: Exploration & Specification (Architecture & Data Contracts)
- Task: Analyze `core/database.py`, `services/recommendation_service.py`, `core/services/recommendation.py`, `core/api.py`, `ui/web_new/js/main.js`, `services/soundcloud_service.py`, `services/youtube_service.py`.
- Deliverable: Comprehensive architectural report detailing data schemas, Last.fm endpoint usage, resolution pipelines, and backward compatibility specs.

### Milestone 2: User Taste Profile & Last.fm Recommendation Client
- Task:
  - Create `services/lastfm_service.py` to handle Last.fm open API queries (`artist.getSimilar`, `artist.getTopTracks`, `track.getSimilar`, `chart.getTopTracks`).
  - Build `UserTasteProfile` extractor in `services/recommendation_service.py` (or helper module) querying `core/database.py` for top artists, top played tracks, listening history by time of day, and genre distribution.
  - Implement search resolution helper using `SoundCloudService` / `YouTubeService` to map recommended metadata (`title`, `artist`) to playable objects (`source_id`, `cover_url`, `source`).
- Deliverable: Functional taste profile builder & Last.fm query & resolution module with passing unit tests.

### Milestone 3: Contextual Mixes & Smart Feed Refactor
- Task:
  - Completely rewrite `get_smart_home_feed` and `get_mixes` in `services/recommendation_service.py`.
  - Remove all calls to `YTMusic.get_watch_playlist` and `YTMusic.get_explore`.
  - Implement contextual mixes: Time-of-day weighting (Morning Vibe, Daytime Energy, Evening Chill, Night Vibe), personalized taste mixes, artist radios, new releases, top charts.
  - Ensure all returned data strictly conforms to UI format expected by `ui/web_new/js/main.js`.
- Deliverable: Updated `services/recommendation_service.py` fully decoupled from YTMusic.

### Milestone 4: Programmatic Verification & Forensic Integrity Audit
- Task:
  - Create `tests/test_new_recommendations.py` to programmatically test `get_smart_home_feed` and `get_mixes` using mock listening history.
  - Assert ZERO calls to YTMusic generative APIs (`get_explore`, `get_watch_playlist`).
  - Verify JSON structure matches UI requirements strictly.
  - Execute full reviewer and forensic auditor integrity checks.
- Deliverable: Passing automated test suite and clean auditor report.
