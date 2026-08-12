# Scope: Milestone 3 — Search Optimization & Caching

## Mission
Implement and verify Milestone 3 (Features 12-16) for AURA Music.

## Feature Inventory & Scope
- Feature 12: Restore & Integrate Yandex Music Search
  - Add `"yandex"` to `services` dictionary in `core/api.py`
  - Remove Yandex filter/commented out code in `search.js`
  - Add Yandex option and "All Providers" ("Все источники") option in `index.html` dropdown
- Feature 13: Offload Local DB Search & DB Indexing
  - Offload local SQLite DB search (`db.search_tracks`) from main thread to `ThreadPoolExecutor` worker pool in `core/api.py`
  - Add DB indexes on `tracks(title)` and `tracks(artist)` in `core/database.py`
- Feature 14: Search Execution Timeouts & Error Handling
  - Implement 4.0s hard per-provider execution timeouts in backend search dispatcher
  - Fix `SoundCloudService` DRM error branch to always execute callback/error_callback
  - Emit `search_completed` event when search finishes or times out
- Feature 15: Thread-Safe LRU Search Cache
  - Refactor `BaseMusicService._search_cache` to use `threading.Lock()` and an LRU eviction policy with capacity limit (300 entries) for thread-safe bounded caching
- Feature 16: Track Deduplication & UI Stability
  - Implement track deduplication in `search.js` / backend based on normalized `artist - title`, merging duplicate tracks from multiple providers and preventing UI result jittering

## Status
Status: IN_PROGRESS
