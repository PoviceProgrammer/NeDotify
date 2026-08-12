# Scope: Milestone 3 — Search Optimization & Caching

## Features
| # | Feature | Scope Description | Source Files |
|---|---------|-------------------|--------------|
| 12 | Restore & Integrate Yandex Music Search | Add `"yandex"` to `services` dict in `core/api.py`, remove Yandex filter in `search.js`, add Yandex option and "All Providers" ("Все источники") option in `index.html` dropdown. | `core/api.py`, `ui/web_new/js/search.js`, `ui/web_new/index.html` |
| 13 | Asynchronous Non-blocking DB Search & DB Indexing | Offload local SQLite DB search (`db.search_tracks`) from main thread to `ThreadPoolExecutor` worker pool in `core/api.py`. Add DB indexes on `tracks(title)` and `tracks(artist)` in `core/database.py`. | `core/api.py`, `core/database.py` |
| 14 | Provider Hard Timeouts & Silent Failure Patch | Add 4.0s hard per-provider execution timeouts in backend search dispatcher; fix `SoundCloudService` DRM error branch to always execute callback/error_callback; emit `search_completed` event. | `core/api.py`, `services/soundcloud_service.py`, `ui/web_new/js/search.js` |
| 15 | Thread-Safe Bounded Search Cache | Refactor `BaseMusicService._search_cache` to use `threading.Lock()` and an LRU eviction policy with capacity limit (e.g. 300 entries) for thread-safe bounded caching. | `services/base_service.py` |
| 16 | Track Deduplication & UI Result Merging | Implement track deduplication in `search.js` / backend based on normalized `artist - title`, merging duplicate tracks from multiple providers and preventing UI result jittering. | `ui/web_new/js/search.js` |

## Milestones Status
| # | Name | Scope | Status |
|---|------|-------|--------|
| M3 | Search Optimization & Caching | Features 12-16 | IN_PROGRESS |
