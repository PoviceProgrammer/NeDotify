# BRIEFING — 2026-07-13T17:19:26Z

## Mission
Explore the AURA Music codebase to analyze settings handling, service initialization, Yandex/YouTube/SoundCloud authentication, error handling, settings UI, and identify legacy root files.

## 🔒 My Identity
- Archetype: Explorer
- Roles: Read-only investigator
- Working directory: c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\explorer_bypass_auth
- Original parent: 0e1a4293-5e84-4175-8d0b-524348f18492
- Milestone: explorer_bypass_auth

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- CODE_ONLY network mode: no external requests, no curl/wget/etc.

## Current Parent
- Conversation ID: 0e1a4293-5e84-4175-8d0b-524348f18492
- Updated: 2026-07-13T17:19:26Z

## Investigation State
- **Explored paths**:
  - `core/settings.py` (Settings categories & database read/write)
  - `core/app.py` (Application core initialization and service wireframes)
  - `core/api.py` (IPC bridge between JS and Python core)
  - `services/yandex_service.py` (Yandex API client and stream resolution)
  - `services/youtube_service.py` (YouTube extractor with yt-dlp & ytmusicapi)
  - `services/soundcloud_service.py` (SoundCloud extractor with yt-dlp)
  - `services/vk_service.py` (VK extractor stub/link resolver)
  - `services/recommendation_service.py` (Recommendation extractor & algorithm)
  - `ui/web_new/index.html` (Main HTML structure of the app UI)
  - `ui/web_new/js/settings.js` (UI controls handling settings load/save)
  - `ui/web_new/js/events.js` (Event router for IPC messages)
  - `ui/web_new/js/main.js` (App start entry point loading pages & settings)
  - `main.py` (Application entrypoint calling pywebview with index.html)
- **Key findings**:
  - Stored settings are persisted via `DatabaseManager` using categories. Adding the `"auth"` category (`yandex_token`, `cookies_file_path`, `browser_cookies`) fits this model directly.
  - Services are constructed in `AppCore` without arguments. To prevent `TypeError`, all service class constructors (`YouTubeService`, `SoundCloudService`, `VKService`, `YandexService`, `RecommendationService`) must be modified to accept a `settings=None` parameter.
  - `YandexService` anonymous access results in 30-sec limit. Token authorization can fail, necessitating a fallback to anonymous and event callbacks (via `AppApi._emit`) to warn/inform the frontend.
  - `YouTubeService` and `SoundCloudService` both need cookie cascading (`cookiefile` path existence check vs `cookiesfrombrowser` browser option) and `yt-dlp` instance resets when setting changes.
  - Proper yt-dlp `DownloadError` interception is missing. Wrapping extractors and catching `DownloadError` will allow generating user-friendly errors for geo-restriction, age verification, and bot detection.
  - Root `settings_new.html` and `settings_logic.js` are not imported or referenced anywhere in the app and are legacy.
- **Unexplored areas**: None.

## Key Decisions Made
- Confirmed file modification points for the Auth & Bypass features.
- Designed an event-driven feedback flow for Yandex Auth status.
- Designed cookie-cascading logic for yt-dlp integration.

## Artifact Index
- c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\explorer_bypass_auth\ORIGINAL_REQUEST.md — Original request document.
- c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\explorer_bypass_auth\BRIEFING.md — My current working memory.
- c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\orchestrator_bypass_auth\explorer_report.md — The target analysis report.
