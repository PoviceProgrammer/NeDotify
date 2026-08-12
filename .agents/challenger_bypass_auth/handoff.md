# Challenger Handoff Report — AURA Music Auth & Bypass Verification

## 1. Observation
### Unit Tests
Running the command `.venv\Scripts\python.exe -m unittest tests/test_nedotify.py` in the workspace directory produced the following output:
```
Ran 99 tests in 5.934s

OK
```
This confirms that all 99 unit tests (including the new `TestBypassAndAuth` test cases) pass successfully.

### Yandex Service Fallback & Event Dispatching
In `services/yandex_service.py`:
- Line 38: Retrieves the `yandex_token` setting.
- Lines 40-56: If a token exists, attempts token client initialization: `self._client = Client(token).init()`. If initialization fails (due to invalid token), exceptions are caught, `self.auth_error = True` is set, and `self.on_auth_error(True)` is invoked.
- Lines 57-62: Regardless of token auth failure, fallback anonymous client initialization is performed via `self._client = Client().init()`.
In `core/api.py`:
- Line 31-32: Binds `self._core.yandex.on_auth_error` callback to `self._on_yandex_auth_error`.
- Lines 148-149: The handler invokes `self._emit("yandex_auth_error", is_error)`.
In `ui/web_new/js/events.js`:
- Lines 80-85: Handles the `"yandex_auth_error"` event by calling `setYandexWarning(!!data)` and showing a Cyrillic error toast: `"Ошибка авторизации Яндекс Музыка. Ограничение 30 сек."`.
In `ui/web_new/js/settings.js`:
- Lines 218-223: Defines `setYandexWarning(visible)` which toggles `display` style for the `#yandex-auth-warning` HTML element in the settings authorization pane.

### YouTube and SoundCloud Cookie Cascading
In `services/youtube_service.py` (lines 91-100) and `services/soundcloud_service.py` (lines 55-64, 82-91):
The options dictionary for `YoutubeDL` is populated as follows:
```python
if cookies_file_path and os.path.exists(cookies_file_path):
    opts['cookiefile'] = cookies_file_path
elif browser_cookies and browser_cookies != "none":
    opts['cookiesfrombrowser'] = (browser_cookies, )
```
This prioritizes the custom cookies file if it exists, otherwise falls back to extracting cookies from the selected browser (if not "none").

### yt-dlp Exception and Lock Error Handling
In `services/youtube_service.py` (lines 205-227) and `services/soundcloud_service.py` (lines 143-152, 203-225):
Exceptions from yt-dlp execution are caught and checked:
- If a `DownloadError` contains substrings `"database"`, `"locked"`, `"sqlite"`, or `"profile"`, it invokes `error_callback("Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt")`.
- Other download errors are returned as user-friendly strings.

---

## 2. Logic Chain
1. **Unit Tests Conformance**: The project's unit tests execution results (Observation 1) show `99 tests` run with `OK`, validating that new settings classes, service constructors, cascading rules, and mocks are fully functional and do not break the existing test suites.
2. **Yandex Auth Error Fallback**: If an invalid token is provided, `YandexService` triggers the `on_auth_error(True)` callback and recovers using anonymous Client initialization (Observation 2). The core API routes this event to the frontend (Observation 2), where it is intercepted by the JavaScript controller to show the warning and toast notifications.
3. **Cookie Cascade Hierarchy**: Checking the `settings.get("auth", "cookies_file_path")` existence via `os.path.exists` before check of `"browser_cookies"` (Observation 3) enforces the priority: path-based cookies file -> browser cookies -> no cookies.
4. **yt-dlp Lock Handlers**: Inspecting the exception traps in both YouTube and SoundCloud service modules (Observation 4) confirms that browser lock and SQLite profile lock conditions map to a clear user action message instead of a raw traceback.

---

## 3. Caveats
- **Browser Lock Triggers**: The warning about browser database locks is triggered based on text-matching substrings (`"database"`, `"locked"`, `"sqlite"`, `"profile"`). If an unexpected exception pattern appears that does not match these words (e.g., OS-specific permission denied errors), it might escape the mapping and fall back to displaying the raw error message.
- **Yandex Track Limits**: The fallback anonymous client is fully functional but subject to Yandex Music's stream limits of 30 seconds for non-paying/anonymous clients. This limit is correctly documented and notified to the user.

---

## 4. Conclusion
The implementation of Settings, Bypass, and Auth mechanisms across Yandex Music, YouTube, and SoundCloud is fully correct, handles fallbacks robustly, manages cookie extraction cascading with the correct priority sequence, captures locked profile exceptions gracefully, and is backed by a passing suite of 99 unit tests.

---

## 5. Verification Method
- **Test execution**: Run `.venv\Scripts\python.exe -m unittest tests/test_nedotify.py`. Ensure that it prints `OK`.
- **Code Inspection**: Review the logic inside `services/youtube_service.py` (line 91), `services/soundcloud_service.py` (line 55, 82), `services/yandex_service.py` (line 36), and `core/api.py` (line 31, 461) to confirm configuration synchronization.

---

## 6. Challenge Report (Adversarial Review)

### Overall risk assessment: LOW

### Challenges

#### [Low] Challenge 1: Unpredictable SQLite lock error text on non-English locales
- **Assumption challenged**: Assumed yt-dlp or SQLite lock error messages will always contain "database", "locked", "sqlite", or "profile" in their lowercased representation.
- **Attack scenario**: If a Windows system runs on a locale that formats system error messages in another language, and yt-dlp does not override the locale, the lock exception string might not contain the English keywords.
- **Blast radius**: The raw OS error string is shown to the user instead of the user-friendly notification. The app continues functioning but does not show the specific "Close browser" suggestion.
- **Mitigation**: Standard yt-dlp library exceptions usually normalize lock warnings, but monitoring user reports for localized OS messages is recommended.
