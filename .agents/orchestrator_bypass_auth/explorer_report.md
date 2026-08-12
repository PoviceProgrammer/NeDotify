# Explorer Findings & Design Report: Auth & Bypass Integration

This report outlines the structural analysis and proposed modifications to integrate authentication (Yandex Music tokens) and bypass limits (yt-dlp cookies) into the AURA Music application.

---

## 1. Observations

We analyzed the current implementation across various components of the codebase. Below are our observations of specific files and lines:

### A. Settings Management (`core/settings.py`)
- **Default Dictionary Definition**: The `DEFAULT_SETTINGS` dictionary (lines 11–151) defines structured categories of settings (e.g., `"general"`, `"audio"`, `"overlay"`, `"services"`).
- **Persistence Mechanism**: Persistent storage utilizes SQLite via a `DatabaseManager` class (lines 154–160).
- **Keys Read/Write**: The settings manager loads stored values matching `{category}.{key}` or fallback raw `{key}` and falls back to defaults where database values are missing (lines 162–175). It sets values via `self.db.set_setting(f"{category}.{key}", value, category)` (lines 184–190).
- **Missing Elements**: The settings schema does not currently define any fields for storing credentials, tokens, or cookie settings.

### B. Service Instantiation (`core/app.py` & `core/api.py`)
- **Service Wires**: In `core/app.py` (lines 69–75), all service classes are constructed with zero arguments:
  ```python
  self.youtube = YouTubeService()
  self.soundcloud = SoundCloudService()
  self.vk = VKService()
  self.yandex = YandexService()
  self.recommendations = RecommendationService()
  ```
- **Constructor Signature Mismatches**: The backend expects these services to operate independently without accessing application settings, meaning constructors currently accept no arguments.
- **Immediate Application**: `core/api.py` handles setting updates through `update_setting` (lines 440–456). However, there is no immediate re-initialization of service client instances when their settings (like authentication details) are changed on the frontend.

### C. Yandex Music authentication & Error Handling (`services/yandex_service.py`)
- **Client Instantiation**: `YandexService._get_client()` (lines 33–42) initializes an anonymous client:
  ```python
  self._client = Client().init()
  ```
  This mode is subject to a 30-second preview limit on tracks.
- **Token and Signaling**: There is currently no token passed to `Client()` and no IPC signaling to inform the frontend if authentication fails.

### D. YouTube & SoundCloud bypass and Error Interception (`services/youtube_service.py` & `services/soundcloud_service.py`)
- **yt-dlp Options Layout**: Both services compile static `ydl_opts` dicts containing network headers, formats, and timeouts (e.g., `youtube_service.py` lines 64–84, `soundcloud_service.py` lines 36–48). 
- **Missing Cookie Parameters**: Neither service propagates `cookiefile` or `cookiesfrombrowser` properties to yt-dlp options.
- **Unstructured Errors**: Extracting stream URLs (via `extract_info`) wraps general exceptions in an try-except block, yielding raw exceptions (e.g., `youtube_service.py` lines 219–226, `soundcloud_service.py` lines 171–175). Specific `DownloadError` exceptions (like geo-restrictions, age limits, and bot verification) are not parsed to deliver human-readable alerts.

### E. Frontend UI Layout (`ui/web_new/index.html` & `ui/web_new/js/settings.js`)
- **Settings Layout**: The settings page uses a tabbed structure (`settings-nav` and corresponding `settings-panel` elements) to segment settings into Appearance, Audio, Particles, and Storage.
- **Load/Save Operations**: Toggles and text fields trigger `saveSetting(key, value, category)` (which maps to backend `AppApi.save_setting`) and load via `applySettingsFromBackend(settings)`.
- **Frontend Warning Banners**: The UI currently lacks alerts or banner spaces for displaying authentication or configuration warnings. The only alert system is the temporary `showToast(message, type)` notification.

### F. Root File Analysis (`settings_new.html` & `settings_logic.js`)
- **Execution Hook**: In `main.py` (lines 44–59), PyWebView is started with the path pointing directly to `ui/web_new/index.html`:
  ```python
  html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "web_new", "index.html")
  ```
- **Unused Files**: The root-level files `settings_new.html` and `settings_logic.js` are not loaded, referenced, or executed by `main.py` or the `ui/web_new` codebase. They are legacy, redundant files.

---

## 2. Logic Chain

1. **Schema Extension**: Since SQLite is the persistent layer, updating the settings default schema is sufficient to automatically enable loading and saving new options. The keys `auth.yandex_token` (string), `auth.cookies_file_path` (string), and `auth.browser_cookies` (boolean) must be defined.
2. **Service Access**: To allow services to read these configurations, the `SettingsManager` instance `self.settings` must be injected into all service constructors in `core/app.py`. To prevent python initialization crashes, all service constructors must be modified to support `settings=None`.
3. **Yandex Music Flow**:
   - The token should be fetched in `_get_client()`. If present, the service should attempt `Client(token).init()`.
   - On exception (invalid token), it must trigger `self.on_auth_error(message)` to notify the backend API, and then fallback to `Client().init()` (anonymous).
   - If validation succeeds, it should trigger `self.on_auth_success()` to clear warnings.
   - When the token changes on the UI, the active client must be set to `None` to force immediate re-authentication.
4. **yt-dlp Bypass Cascade**:
   - yt-dlp options should cascade settings: first check if a `cookies_file_path` is specified and exists (`os.path.exists`), setting `cookiefile`.
   - If not, check if `browser_cookies` is `True`, setting `cookiesfrombrowser` to `('chrome',)` to auto-extract from Chrome.
   - When these settings change, cached `YoutubeDL` instances in the services must be set to `None` to trigger options re-compilation.
5. **yt-dlp Error Interception**:
   - Catching `yt_dlp.utils.DownloadError` during stream url extraction allows parsing error details for patterns like `"Sign in to confirm your age"`, `"confirm you are not a bot"`, or `"geo-restricted"` to emit localized explanations rather than raw stack traces.
6. **UI Presentation**:
   - Add a new tab `auth` labeled "Авторизация и обход" in settings.
   - Embed warning banners inside the Yandex settings section that toggle visibility based on `yandex_auth_error` / `yandex_auth_success` events.
7. **Legacy File Removal**:
   - Root files `settings_new.html` and `settings_logic.js` can be safely ignored (and deleted) because `main.py` explicitly loads the modern UI at `ui/web_new/index.html`.

---

## 3. Caveats

- **Network Limits**: Under CODE_ONLY mode, live network validation of tokens or yt-dlp cookie extraction cannot be tested directly in the workspace. Synthetic mocked unit tests must verify state handling.
- **Browser Cookies Dependency**: Extracting cookies from Chrome requires Chrome to be installed on the user's OS and permission to access Chrome's profile lock file. If Chrome is locked (e.g., currently open), extraction might fail or warn.
- **yandex-music Library**: Real token validation depends on the `yandex_music` library (if `HAS_YANDEX` is true). If the library is missing or cannot be imported in some environments, the code must still fallback safely and not throw import exceptions.

---

## 4. Conclusion & Proposed Changes

The following changes are required to implement the features:

### 1. Update settings schema (`core/settings.py`)
Add the `"auth"` category under the `DEFAULT_SETTINGS` dictionary (around line 134):
```python
    # === АВТОРИЗАЦИЯ И ОБХОД БЛОКИРОВОК ===
    "auth": {
        "yandex_token": "",
        "cookies_file_path": "",
        "browser_cookies": False,
    },
```

### 2. Inject Settings into Service Constructors (`core/app.py`)
Modify service initializations (lines 69–75):
```python
        # Services
        self.youtube = YouTubeService(settings=self.settings)
        self.soundcloud = SoundCloudService(settings=self.settings)
        self.vk = VKService(settings=self.settings)
        self.yandex = YandexService(settings=self.settings)
        self.recommendations = RecommendationService(settings=self.settings)
```

### 3. Handle Setting Updates and IPC Bridge (`core/api.py`)
Modify `__init__` to register Yandex error/success callbacks (around lines 25–30):
```python
        # Bind Yandex auth status callbacks
        self._core.yandex.on_auth_error = self._on_yandex_auth_error
        self._core.yandex.on_auth_success = self._on_yandex_auth_success
```
Implement the callback handlers:
```python
    def _on_yandex_auth_error(self, message):
        self._emit("yandex_auth_error", message)

    def _on_yandex_auth_success(self):
        self._emit("yandex_auth_success")
```
Modify `update_setting` to reset active services when auth parameters change (around lines 440–456):
```python
        elif category == "auth":
            if key == "yandex_token":
                self._core.yandex.reset_client()
            elif key in ("cookies_file_path", "browser_cookies"):
                self._core.youtube.reset_ydl()
                self._core.soundcloud.reset_ydl()
```

### 4. Upgrade Yandex Client Initialization & Fallback (`services/yandex_service.py`)
Modify constructor and client initialization:
```python
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self.on_auth_error = None
        self.on_auth_success = None
        self._executor = ThreadPoolExecutor(max_workers=3)
        self.logger = logging.getLogger(__name__)
        self._client = None
        
        if HAS_YANDEX:
            self._executor.submit(self._get_client)

    def _get_client(self):
        if not self._client and HAS_YANDEX:
            token = ""
            if self.settings:
                token = self.settings.get("auth", "yandex_token", "")
            
            if token:
                try:
                    self._client = Client(token).init()
                    self.logger.info("Yandex Music client initialized with token.")
                    if self.on_auth_success:
                        self.on_auth_success()
                    return self._client
                except Exception as e:
                    self.logger.error(f"Failed to initialize Yandex Music client with token: {e}")
                    if self.on_auth_error:
                        self.on_auth_error(str(e))
            
            # Fallback
            try:
                self._client = Client().init()
                self.logger.info("Yandex Music client initialized (anonymous fallback).")
            except Exception as e:
                self.logger.error(f"Failed to initialize anonymous fallback: {e}")
        return self._client

    def reset_client(self):
        self._client = None
        if HAS_YANDEX:
            self._executor.submit(self._get_client)
```

### 5. Modify YouTube Extractor and Cookies Options (`services/youtube_service.py`)
Modify constructor:
```python
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=5)
        self._ytmusic = None
        if HAS_YTMUSIC:
            self._ytmusic = YTMusic()
        self._ydl = None
        self._ydl_fallback = None
        if HAS_YTDLP:
            self._executor.submit(self._get_ydl, "high")

    def reset_ydl(self):
        self._ydl = None
        self._ydl_fallback = None
```
Modify `_get_ydl_opts` to support cookie cascading:
```python
    def _get_ydl_opts(self, format_str, fallback=False):
        opts = {
            'quiet': True,
            'no_warnings': True,
            'format': format_str,
            'noplaylist': True,
            'nocheckcertificate': True,
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'socket_timeout': 10,
            'retries': 1,
            'extractor_retries': 1,
            'source_address': '0.0.0.0',
            'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
        }
        if fallback:
            opts['extractor_args'] = {'youtube': {'player_client': ['web', 'tv']}}
            opts['format'] = 'best'
            
        # Apply cookies
        if self.settings:
            import os
            cookies_file = self.settings.get("auth", "cookies_file_path", "")
            if cookies_file and os.path.exists(cookies_file):
                opts['cookiefile'] = cookies_file
            elif self.settings.get("auth", "browser_cookies", False):
                opts['cookiesfrombrowser'] = ('chrome',)
                
        return opts
```
Modify `get_stream_url` to catch `DownloadError` and emit clean warnings:
```python
        from yt_dlp.utils import DownloadError

        # inside _extract():
        # replace attempt exception handler:
                except DownloadError as de:
                    err_msg = str(de).replace('\x1b', '').replace('[0;31m', '').replace('[0m', '')
                    if "Sign in to confirm your age" in err_msg:
                        user_msg = "Требуется авторизация (подтверждение возраста). Укажите Cookies в настройках."
                    elif "confirm you are not a bot" in err_msg:
                        user_msg = "YouTube заблокировал запрос. Настройте Cookies или воспользуйтесь VPN."
                    elif "Video unavailable" in err_msg:
                        user_msg = "Видео недоступно (возможно, заблокировано или удалено)."
                    else:
                        user_msg = f"Ошибка YouTube: {err_msg}"
                        
                    if attempt < max_attempts - 1:
                        time.sleep(1)
                        continue
                    if error_callback:
                        error_callback(user_msg)
                    return
```

### 6. Modify SoundCloud Extractor and Cookies Options (`services/soundcloud_service.py`)
Modify constructor:
```python
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=3)
        self.logger = logging.getLogger(__name__)
        self._ydl = None
        self._ydl_search = None
        if HAS_YTDLP:
            self._executor.submit(self._get_ydl)
            self._executor.submit(self._get_ydl_search)

    def reset_ydl(self):
        self._ydl = None
        self._ydl_search = None

    def _apply_cookies(self, opts):
        if not self.settings:
            return
        import os
        cookies_file = self.settings.get("auth", "cookies_file_path", "")
        if cookies_file and os.path.exists(cookies_file):
            opts['cookiefile'] = cookies_file
        elif self.settings.get("auth", "browser_cookies", False):
            opts['cookiesfrombrowser'] = ('chrome',)
```
Call `self._apply_cookies(ydl_opts)` in `_get_ydl` and `_get_ydl_search` before starting `YoutubeDL`.
Update `get_stream_url` to catch `DownloadError`:
```python
            except yt_dlp.utils.DownloadError as de:
                err_msg = str(de).replace('\x1b', '').replace('[0;31m', '').replace('[0m', '')
                if "geo-restricted" in err_msg or "country" in err_msg:
                    user_msg = "Трек SoundCloud недоступен в вашей стране. Рекомендуется использовать VPN."
                else:
                    user_msg = f"Ошибка SoundCloud: {err_msg}"
                if error_callback:
                    error_callback(user_msg)
```

### 7. Prevent Signature Crashes in Other Services
Modify constructors in `services/vk_service.py` and `services/recommendation_service.py` to accept `settings=None` as well:
```python
# In vk_service.py
    def __init__(self, settings=None):
        self.settings = settings

# In recommendation_service.py
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        ...
```

### 8. Add Settings Controls in HTML (`ui/web_new/index.html`)
Add tab item under `settings-nav`:
```html
                    <button class="settings-nav-btn" data-panel="auth">
                        <i data-lucide="shield" style="width:16px;height:16px"></i>
                        Авторизация
                    </button>
```
Add settings panel under `settings-panels`:
```html
                    <!-- Auth & Bypass -->
                    <div id="settings-auth" class="settings-panel">
                        <div class="settings-section">
                            <div class="settings-section-title">Яндекс Музыка</div>
                            <div class="setting-row">
                                <div style="flex: 1; margin-right: 16px;">
                                    <div class="setting-label">Токен Yandex Music</div>
                                    <div class="setting-sublabel">Необходим для полноценного прослушивания (без ограничения в 30 секунд).</div>
                                    <div id="yandex-auth-warning" class="warning-box" style="display: none; margin-top: 8px; color: var(--error); font-size: 12px; align-items: center; gap: 6px;">
                                        <i data-lucide="alert-triangle" style="width:14px;height:14px"></i>
                                        <span>Токен недействителен. Используется демо-режим (30 сек).</span>
                                    </div>
                                </div>
                                <input type="password" class="text-input" id="input-yandex-token" placeholder="Введите Yandex токен" style="width: 250px; padding: 8px 12px; border-radius: 8px; background: var(--bg-sec); border: 1px solid var(--border); color: var(--text);">
                            </div>
                        </div>
                        <div class="settings-section">
                            <div class="settings-section-title">YouTube и SoundCloud (Обход блокировок)</div>
                            <div class="setting-row">
                                <div>
                                    <div class="setting-label">Использовать cookies браузера</div>
                                    <div class="setting-sublabel">Автоматически извлекать cookies из Chrome для обхода блокировок.</div>
                                </div>
                                <button class="toggle-switch" id="toggle-browser-cookies"><div class="toggle-dot"></div></button>
                            </div>
                            <div class="setting-row">
                                <div style="flex: 1; margin-right: 16px;">
                                    <div class="setting-label">Путь к файлу cookies.txt</div>
                                    <div class="setting-sublabel">Укажите путь к файлу Netscape cookies.txt для обхода ограничений.</div>
                                </div>
                                <input type="text" class="text-input" id="input-cookies-path" placeholder="C:\path\to\cookies.txt" style="width: 250px; padding: 8px 12px; border-radius: 8px; background: var(--bg-sec); border: 1px solid var(--border); color: var(--text);">
                            </div>
                        </div>
                    </div>
```

### 9. Connect Controls in JS Settings & Events (`ui/web_new/js/settings.js` & `events.js`)
In `ui/web_new/js/settings.js`, add binding and load/apply:
```javascript
    // Inside initSettings():
    setupToggle('toggle-browser-cookies', 'browser_cookies', 'auth');

    const inputYandexToken = document.getElementById('input-yandex-token');
    if (inputYandexToken) {
        inputYandexToken.addEventListener('change', (e) => {
            saveSetting('yandex_token', e.target.value, 'auth');
        });
    }

    const inputCookiesPath = document.getElementById('input-cookies-path');
    if (inputCookiesPath) {
        inputCookiesPath.addEventListener('change', (e) => {
            saveSetting('cookies_file_path', e.target.value, 'auth');
        });
    }

    // Inside applySettingsFromBackend():
    if (settings.auth) {
        const toggleBC = document.getElementById('toggle-browser-cookies');
        if (toggleBC) toggleBC.classList.toggle('on', !!settings.auth.browser_cookies);

        const inputYT = document.getElementById('input-yandex-token');
        if (inputYT) inputYT.value = settings.auth.yandex_token || '';

        const inputCP = document.getElementById('input-cookies-path');
        if (inputCP) inputCP.value = settings.auth.cookies_file_path || '';
    }

    // Add helper function:
    export function setYandexWarning(visible) {
        const box = document.getElementById('yandex-auth-warning');
        if (box) {
            box.style.display = visible ? 'flex' : 'none';
            renderIcons();
        }
    }
```
In `ui/web_new/js/events.js`, register the IPC event routing:
```javascript
            case 'yandex_auth_error':
                console.warn('Yandex auth failed:', data);
                import('./settings.js').then(m => m.setYandexWarning(true));
                showToast('Ошибка авторизации Яндекс Музыки. Используется демо-режим.', 'error');
                break;

            case 'yandex_auth_success':
                import('./settings.js').then(m => m.setYandexWarning(false));
                showToast('Успешно авторизовано в Яндекс Музыке!', 'success');
                break;
```

---

## 5. Verification Method

Once implemented, the changes should be verified through the following steps:

1. **Service Instantiation and Compile Check**:
   Run tests (e.g., `pytest` if a testing framework is present) to confirm that the changes to the app core initialization and service constructors do not result in a Python initialization error or signature `TypeError` on startup.
2. **Settings Persistence Check**:
   Launch the app, select the "Авторизация" settings tab. Enter values for the Yandex Music token, toggle the browser cookies switch, and enter a cookie path. Restart the application and verify that the entered values are preserved (confirming database persistence).
3. **Yandex Fallback simulation**:
   - Provide an invalid string as the Yandex token. Confirm that the application does not crash, logs the error, falls back to anonymous mode, triggers the warning banner (`#yandex-auth-warning`), and renders a toast warning.
   - Enter a valid Yandex token (if testing online). Verify that `yandex_auth_success` triggers, clearing the warning banner and showing a success toast.
4. **Cookie Option Cascading verification**:
   - Input a valid path to a dummy `cookies.txt` file. Place a breakpoint in `YouTubeService._get_ydl_opts()` and verify that the option `cookiefile` resolves to the input path.
   - Toggle browser cookies on, clear the cookies file path. Verify that the option `cookiesfrombrowser` resolves to `('chrome',)` in the compiled yt-dlp options.
5. **yt-dlp Error Interception verification**:
   Simulate a `DownloadError` (e.g., by attempting to play a video that requires age verification or is geo-restricted). Confirm that the intercepted error yields the corresponding clean user-facing warning rather than a generic stack trace.
