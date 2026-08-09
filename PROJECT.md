# Project: AURA Music

## Architecture
AURA Music is a desktop music application built with Python backend, SQLite database, pywebview UI layer (HTML5 Audio), local HTTP audio proxy, multi-provider search/stream engine (YouTube, SoundCloud, Spotify, Yandex), and track downloader.

### Core Architecture & Boundaries
1. **Audio Playback & Proxy Layer**: `core/proxy.py`, `core/app.py`, `audio/engine.py`, `ui/web_new/js/player.js`
   - Handles local HTTP stream proxying (`http://127.0.0.1:<port>/api/stream`), range requests, socket abort resilience, stream URL expiration/re-resolution, and frontend HTML5 audio crossfade teardown.
2. **Track Downloader & Cache Layer**: `core/downloader.py`, `utils/cache_manager.py`, `core/api.py`, `ui/web_new/js/contextmenu.js`, `ui/web_new/js/events.js`
   - Manages asynchronous background downloading (`ThreadPoolExecutor`), YouTube/SoundCloud/Spotify-fallback downloading, `.cache/downloads/` file isolation, database status update (`is_downloaded = 1`), path sanitization, and UI event notification.
3. **Multi-Provider Search & Caching Layer**: `core/api.py`, `services/*` (`youtube_service.py`, `soundcloud_service.py`, `spotify_service.py`, `yandex_service.py`, `base_service.py`), `core/database.py`, `ui/web_new/js/search.js`, `ui/web_new/index.html`
   - Performs parallel async multi-source search (Spotify, YouTube, SoundCloud, Yandex), thread-safe LRU caching, provider hard timeouts, non-blocking DB search, deduplication, and unified UI rendering.
4. **E2E Testing Track**: `tests/`, `run_tests.py`
   - Requirement-driven opaque-box test suite covering Tiers 1-4.

---

## Feature Inventory
| # | Feature | Description | Source | Assigned Milestone |
|---|---------|-------------|--------|-------------------|
| 1 | Proxy Socket Abort Resilience | Catch `WinError 10053`, `BrokenPipeError`, `ConnectionResetError` during `wfile.write()` without error logging or crash | ORIGINAL_REQUEST §1, Survey | M1 (Playback & Proxy) |
| 2 | Local File Stream Proxying | Allow local downloaded files in proxy (`file_path`) without SSRF 400 rejection | ORIGINAL_REQUEST §1, Survey | M1 (Playback & Proxy) |
| 3 | Stream URL TTL & Auto Re-resolution | Reduce stream cache TTL to 3h; perform fast non-blocking re-resolve on 403/410 | ORIGINAL_REQUEST §1, Survey | M1 (Playback & Proxy) |
| 4 | Range Request & 206 Partial Content | Correct HTTP Range header handling and byte-limit delivery | ORIGINAL_REQUEST §1, Survey | M1 (Playback & Proxy) |
| 5 | Frontend Audio Element Teardown | Clear `oldAudio.src` on pause/fade to prevent background socket leaks in pywebview | ORIGINAL_REQUEST §1, Survey | M1 (Playback & Proxy) |
| 6 | Downloader Spotify Fallback | Implement YouTube fallback search for Spotify track downloads | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 7 | Dedicated Download Directory | Save downloaded tracks to `.cache/downloads/` isolated from stream cache eviction | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 8 | Downloader UI Events & Error Handling | Emit `track_downloaded` and `download_failed` events for UI auto-refresh & toasts | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 9 | Database Downloaded Status Integrity | Set `is_downloaded = 1` and `file_path`, preserving original `source` provider | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 10 | Windows Path & Filename Sanitization | Sanitize Cyrillic characters and illegal Windows path characters (`\ / : * ? " < > \|`) | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 11 | Downloader Queue Status & Error Reporting | Update `download_queue` status, log errors, and prevent false `is_downloaded` flags | ORIGINAL_REQUEST §2, Survey | M2 (Track Downloading) |
| 12 | Restore Yandex Search Provider | Enable Yandex search in `core/api.py`, `search.js`, and `index.html` ("All Providers" option) | ORIGINAL_REQUEST §3, Survey | M3 (Search Optimization) |
| 13 | Non-blocking Asynchronous DB Search | Offload local DB track search off main thread to thread pool | ORIGINAL_REQUEST §3, Survey | M3 (Search Optimization) |
| 14 | Provider Hard Timeouts & Silent Failure Patch | Add 3.5–5s hard timeout per provider; fix SoundCloud DRM callback skip | ORIGINAL_REQUEST §3, Survey | M3 (Search Optimization) |
| 15 | Thread-Safe Bounded Search Cache | Refactor `BaseMusicService._search_cache` with `Lock()` and LRU capacity limit | ORIGINAL_REQUEST §3, Survey | M3 (Search Optimization) |
| 16 | Track Deduplication & UI Result Merging | Merge identical tracks across providers by normalized title/artist; non-blocking UI | ORIGINAL_REQUEST §3, Survey | M3 (Search Optimization) |
| 17 | E2E Testing Suite (Tiers 1-4) | Comprehensive opaque-box test suite for features 1-16 -> publish `TEST_READY.md` | Dual Track Policy | E2E Track |
| 18 | Tier 5 Adversarial Coverage Hardening | White-box code analysis, edge case test generation, and bug fixing | Dual Track Policy | M4 (Final Milestone) |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test suite (Tiers 1-4) covering Features 1-16 -> publish `TEST_READY.md` | none | PLANNED |
| M1 | Playback & Proxy Fixes | Features 1–5: `proxy.py`, `database.py`, `player.js` | none | PLANNED |
| M2 | Track Downloading | Features 6–11: `downloader.py`, `cache_manager.py`, `api.py`, `events.js` | M1 (interface contracts) | PLANNED |
| M3 | Search Optimization | Features 12–16: `api.py`, `services/*`, `search.js`, `index.html` | none | PLANNED |
| M4 | Integration & Hardening | Phase 1: 100% E2E test pass (Tiers 1-4); Phase 2: Tier 5 Adversarial Hardening | E2E, M1, M2, M3 | PLANNED |

---

## Interface Contracts

### 1. Audio Proxy ↔ Frontend Player (`core/proxy.py` ↔ `ui/web_new/js/player.js`)
- URL Format: `http://127.0.0.1:<port>/api/stream?url=<encoded_stream_or_path>&source=<source>&source_id=<id>`
- Response Headers: `Content-Type`, `Accept-Ranges: bytes`, `Content-Range: bytes <start>-<end>/<total>`, `Content-Length: <chunk_len>`
- Disconnect Handling: Proxy suppresses socket errors (`ConnectionResetError`, `BrokenPipeError`, `WinError 10053`) on aborted connections and stops streaming cleanly without HTTP 500 logs.
- Local File Handling: Proxy accepts local disk paths (`file_path`) and streams directly via `200 OK` or `206 Partial Content`.

### 2. Downloader ↔ API Bridge ↔ UI (`core/downloader.py` ↔ `core/api.py` ↔ `ui/web_new/js/events.js`)
- Python Event Emitted on Completion: `track_downloaded` with payload `{"track_id": track_id, "file_path": file_path}`
- Python Event Emitted on Failure: `download_failed` with payload `{"track_id": track_id, "error": error_msg}`
- Database Update: `tracks` table updated with `is_downloaded = 1`, `file_path = <saved_path>`, leaving `source` provider intact.

### 3. Multi-Provider Search ↔ API ↔ UI (`core/api.py` ↔ `services/*` ↔ `ui/web_new/js/search.js`)
- API Signature: `search(query: str, source: str = "all", result_type: str = None)`
- Search Providers Dict: `{"youtube": ..., "soundcloud": ..., "spotify": ..., "yandex": ..., "local": ...}`
- Execution: Providers run concurrently in `ThreadPoolExecutor(max_workers=5)` with hard timeout of 4.0s per provider.
- UI Format: Emits `search_results` with `{"source": provider_name, "tracks": [...], "is_final": boolean}`.

---

## Code Layout
```
AURA Music/
├── audio/
│   ├── engine.py           # Audio Engine Coordinator
│   └── queue.py            # Playback Queue
├── core/
│   ├── app.py              # Main Application Core
│   ├── api.py              # pywebview API Bridge
│   ├── database.py         # SQLite Database Manager
│   ├── downloader.py       # Download Manager & Queue
│   └── proxy.py            # Local HTTP Stream Proxy Manager
├── services/
│   ├── base_service.py     # Base Music Service & Thread-Safe Search Cache
│   ├── youtube_service.py  # YouTube Service
│   ├── soundcloud_service.py # SoundCloud Service
│   ├── spotify_service.py # Spotify Service (iTunes metadata search)
│   ├── yandex_service.py  # Yandex Music Service
│   └── vk_service.py      # VK Service
├── utils/
│   ├── cache_manager.py    # Stream Cache & Downloads Directory Manager
│   └── path_utils.py       # Path & Filename Sanitization Utilities
├── ui/
│   └── web_new/
│       ├── index.html      # UI Layout & Platform Dropdown
│       └── js/
│           ├── player.js   # Dual HTML5 Audio Player
│           ├── search.js   # Search Handler & Result Deduplication
│           ├── events.js   # Python-to-JS SSE/Event Listener
│           └── contextmenu.js # Download Action Triggers
└── tests/                  # E2E & Unit Test Harness
```
