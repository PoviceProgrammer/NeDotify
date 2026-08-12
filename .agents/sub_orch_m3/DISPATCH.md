## 2026-08-07T15:27:50Z
Execute Milestone 3 (Search Optimization & Caching):
- Feature 12: Restore & Integrate Yandex Music Search: add `"yandex"` to `services` dict in `core/api.py`, remove Yandex filter in `search.js`, add Yandex option and "All Providers" ("Все источники") option in `index.html` dropdown.
- Feature 13: Offload local SQLite DB search (`db.search_tracks`) from main thread to `ThreadPoolExecutor` worker pool in `core/api.py`. Add DB indexes on `tracks(title)` and `tracks(artist)` in `core/database.py`.
- Feature 14: Implement 4.0s hard per-provider execution timeouts in backend search dispatcher; fix `SoundCloudService` DRM error branch to always execute callback/error_callback; emit `search_completed` event.
- Feature 15: Refactor `BaseMusicService._search_cache` to use `threading.Lock()` and an LRU eviction policy with capacity limit (e.g. 300 entries) for thread-safe bounded caching.
- Feature 16: Implement track deduplication in `search.js` / backend based on normalized `artist - title`, merging duplicate tracks from multiple providers and preventing UI result jittering.
