# Project: AURA Music Auth & Bypass

## Architecture
- `core/settings.py` defines the default settings schema.
- `core/app.py` initializes services and must pass the settings object to them.
- `services/yandex_service.py`, `services/youtube_service.py`, and `services/soundcloud_service.py` read their respective auth options from settings and handle cookies/tokens.
- Frontend HTML and JS files (`ui/web_new/index.html` and `ui/web_new/js/settings.js`) render the configuration settings, save/load them, and display warnings/notifications to the user.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | Explore & Design | Analysis of settings, UI structure, service initialization. | None | DONE |
| 2 | Backend Settings Schema | Update `core/settings.py` default settings schema, service config pass-through in `core/app.py`. | Milestone 1 | DONE |
| 3 | Frontend UI & JS | Implement "Авторизация и Обход блокировок" settings UI, token/cookie options, warning for `yandex_auth_error`. | Milestone 2 | DONE |
| 4 | Yandex Music Service | Implement yandex_token read, `Client(token).init()` error handling, anonymous fallback, `yandex_auth_error` event. | Milestone 3 | DONE |
| 5 | YouTube & SoundCloud Services | Implement cookies cascade, yt-dlp exception interception, error_callback reporting, and extractor_args. | Milestone 4 | DONE |
| 6 | Verification & Audit | End-to-end verification, test execution, coverage audit, and integrity checks. | Milestone 5 | DONE |

## Interface Contracts
### settings.py ↔ Services
- Settings schema includes:
  - `auth.cookies_file_path`: string
  - `auth.browser_cookies`: string ("none", "chrome", "firefox", "edge", "opera", "safari")
  - `auth.yandex_token`: string
- Services access settings via `self.settings.get("auth", "key", default)` or similar interface.

### Services ↔ Frontend
- Yandex Service notifies frontend of authentication error via event `yandex_auth_error` with payload `true`.
- YouTube and SoundCloud notify frontend of browser cookies read failure via event/callback with a user message.
