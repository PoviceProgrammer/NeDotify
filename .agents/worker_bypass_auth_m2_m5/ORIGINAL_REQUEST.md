## 2026-07-13T17:22:07Z

You are the Worker for the AURA Music Auth & Bypass task.
Your task is to implement bypass limits and authentication for Yandex Music, YouTube Music, and SoundCloud in the project.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Please make the following changes:

1. Settings schema (`core/settings.py`):
   - Update `DEFAULT_SETTINGS` dictionary to add the "auth" category:
     ```python
     "auth": {
         "cookies_file_path": "",
         "browser_cookies": "none",
         "yandex_token": "",
     },
     ```

2. Service initialization in Core App (`core/app.py`):
   - Pass the settings instance `self.settings` to all service constructors in `AppCore.__init__`:
     - `YouTubeService(settings=self.settings)`
     - `SoundCloudService(settings=self.settings)`
     - `VKService(settings=self.settings)`
     - `YandexService(settings=self.settings)`
     - `RecommendationService(settings=self.settings)`

3. API Bridge Hooks and routing (`core/api.py`):
   - Bind Yandex auth error callback:
     - In `AppApi.__init__`, bind:
       ```python
       self._core.yandex.on_auth_error = self._on_yandex_auth_error
       ```
     - Add the callback method:
       ```python
       def _on_yandex_auth_error(self, is_error):
           self._emit("yandex_auth_error", is_error)
       ```
   - In `get_settings()`, inject the current yandex auth error state for initial load:
     ```python
     settings_dict["auth"]["yandex_auth_error"] = self._core.yandex.auth_error
     ```
     (Note: Ensure settings_dict["auth"] exists before writing to it, in case cache is empty, though _cache will have it due to DEFAULT_SETTINGS).
   - In `save_setting()`, delegate to `update_setting` to ensure settings are validated, hooks run, and `setting_changed` events are emitted:
     ```python
     def save_setting(self, key, value, category="ui"):
         try:
             return self.update_setting(category, key, value)
         except Exception as e:
             print(f"Error saving setting {key}: {e}")
             return False
     ```
   - In `update_setting()`, add logic to reset active service clients when auth configurations change:
     - If `category == "auth"`:
       - If `key == "yandex_token"`: call `self._core.yandex.reset_client()`
       - If `key in ("cookies_file_path", "browser_cookies")`: call `self._core.youtube.reset_ydl()` and `self._core.soundcloud.reset_ydl()`

4. Yandex Music Service (`services/yandex_service.py`):
   - Modify the constructor `__init__(self, settings=None)`:
     - Store `self.settings = settings`
     - Add `self.on_auth_error = None`
     - Add `self.auth_error = False`
   - In `_get_client()`:
     - Read the `yandex_token` from settings: `token = self.settings.get("auth", "yandex_token", "") if self.settings else ""`
     - If `token` is present:
       - Wrap `Client(token).init()` in `try...except Exception as e`.
       - If it succeeds: log it, set `self.auth_error = False`, call `self.on_auth_error(False)` if bound, and return the client.
       - If it fails: log the error, set `self.auth_error = True`, call `self.on_auth_error(True)` if bound.
     - Else (if `token` is empty): set `self.auth_error = False`, call `self.on_auth_error(False)` if bound.
     - Fallback: Wrap anonymous client initialization `Client().init()` in a try...except block to prevent crashes.
   - Implement `reset_client(self)`:
     - Clear the client (`self._client = None`) and submit `self._get_client` to `self._executor` to run in background.

5. YouTube Service (`services/youtube_service.py`):
   - Update constructor `__init__(self, settings=None)` to store `self.settings = settings`. Add `reset_ydl()` to clear cached ydl instances.
   - Update `_get_ydl_opts(self, format_str, fallback=False)` to set:
     - `'extractor_args': {'youtube': ['player_client=android,web']}` (or `['player_client=web,tv']` for fallback).
     - Add cascading cookie import priority logic:
       - If `auth.cookies_file_path` is set and the file exists on disk (use `os.path.exists`), add `'cookiefile': path`.
       - Else if `auth.browser_cookies` is set to a specific browser (not "none"), add `'cookiesfrombrowser': (browser, )`.
       - Else, do not add cookie parameters.
   - Wrap `extract_info` call in `try...except yt_dlp.utils.DownloadError` (or general Exception checks for DownloadError type). If a `DownloadError` is caught:
     - If the error details contain database/profile locked/sqlite indicators, pass a user-friendly error message via `error_callback`: `"Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt"`.
     - Otherwise, forward the error message to the `error_callback`.

6. SoundCloud Service (`services/soundcloud_service.py`):
   - Update constructor `__init__(self, settings=None)` to store `self.settings = settings` and add `reset_ydl()`.
   - Update `_get_ydl` and `_get_ydl_search` to apply the same cascading cookie import priority logic to `ydl_opts` before constructing the `YoutubeDL` instances.
   - Wrap `extract_info` calls in `try...except yt_dlp.utils.DownloadError`. If a cookie/database-locked error occurs, notify the user via `error_callback` with `"Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt"`.

7. Prevent TypeError in other services:
   - Modify the constructors of `VKService` (`services/vk_service.py`) and `RecommendationService` (`services/recommendation_service.py`) to accept `settings=None` and store it.

8. Frontend UI and Settings page (`ui/web_new/index.html`):
   - Add a tab button in `.settings-nav` for "auth" labeled "Авторизация и Обход блокировок" (using lucide icon `shield` or `key`).
   - Add the corresponding `.settings-panel` under `#view-settings` with id `settings-auth`:
     - Under "Яндекс Музыка": text input (password type) `input-yandex-token` and the `#yandex-auth-warning` box (hidden by default) with an alert-triangle icon.
     - Under "YouTube и SoundCloud (Обход ограничений)": a `<select>` dropdown `select-browser-cookies` with options: none, chrome, firefox, edge, opera, safari, and a text input `input-cookies-path` for the direct cookies path.

9. Settings logic (`ui/web_new/js/settings.js`):
   - Add bindings in `initSettings()` to save the settings on input change / select change:
     - `#input-yandex-token` -> save key `yandex_token` in category `auth`.
     - `#select-browser-cookies` -> save key `browser_cookies` in category `auth`.
     - `#input-cookies-path` -> save key `cookies_file_path` in category `auth`.
   - In `applySettingsFromBackend(settings)`: load and set the values of `#input-yandex-token`, `#select-browser-cookies`, `#input-cookies-path` if they exist in `settings.auth`. Also show/hide `#yandex-auth-warning` based on the value of `settings.auth.yandex_auth_error`.
   - Implement `export function setYandexWarning(visible)` to toggle `#yandex-auth-warning` display and call `renderIcons()`.

10. Event Routing (`ui/web_new/js/events.js`):
    - Add case `yandex_auth_error`:
      - If data is true: show `#yandex-auth-warning`, show toast message `Ошибка авторизации Яндекс Музыка. Ограничение 30 сек.`, status `error`.
      - If data is false: hide `#yandex-auth-warning`.

11. Verification and Unit Tests:
    - Add unit tests to `tests/test_nedotify.py` covering:
      - Default schema auth settings values.
      - Settings injection in service constructors.
      - Cascade cookies priority options in `youtube_service.py` / `soundcloud_service.py` (mocked `self.settings` and verifying the resulting `ydl_opts`).
      - Yandex service token auth success/fail mock checks.
    - Run the entire test suite using the virtual environment python interpreter:
      `.venv\Scripts\python.exe -m unittest tests/test_nedotify.py`
    - Document your execution command, output, and layout compliance, and write a handoff report to `c:\Users\valee\OneDrive\Desktop\ждж\дз\AURA Music\.agents\worker_bypass_auth_m2_m5\handoff.md`.
    - Finally, send a message back to parent conversation ID: 0e1a4293-5e84-4175-8d0b-524348f18492.
