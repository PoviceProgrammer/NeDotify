# Original User Request

## Initial Request — 2026-07-13T20:16:06+03:00

Your task is to implement bypass limits and authentication for Yandex Music, YouTube Music, and SoundCloud in the AURA Music project at `c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music/`.

Follow these requirements exactly:

1. UI and Settings (`ui/web_new/index.html`, `ui/web_new/js/settings.js` and `core/settings.py`):
   - Create an "Авторизация и Обход блокировок" section in the settings UI.
   - Add a fallback for cookies: In addition to a dropdown for `browser_cookies` (options: none, chrome, firefox, edge, opera, safari), add a text input `cookies_file_path` for specifying the direct path to a cookies.txt file (Netscape format) in the settings interface.
   - Add a text input for `yandex_token`.
   - Update the default settings schema (`core/settings.py`) with: `auth.cookies_file_path: ""`, `auth.browser_cookies: "none"`, `auth.yandex_token: ""`.
   - Ensure these settings are saved and loaded correctly in `settings.js`.
   - Display a warning in the UI if `yandex_auth_error` is emitted from the backend.

2. Yandex Music Service (`services/yandex_service.py`):
   - In `_get_client()`, read the `yandex_token` from settings (via `self.settings.get("auth", "yandex_token", "")` - you may need to pass settings or app_core to the service, or access it globally/via db if possible. Note: currently services are initialized in `app.py`. Modify initialization to pass `self.settings` to services if needed).
   - Wrap `Client(token).init()` in a `try...except` block.
   - If the token is invalid or expired, do not crash. Catch the exception, log the error, switch the session to anonymous mode (30-sec limit).
   - Send a status flag (e.g., `yandex_auth_error: true`) to the frontend (e.g. via an event or callback) so the UI can warn the user.

3. YouTube and SoundCloud Services (`services/youtube_service.py`, `services/soundcloud_service.py`):
   - You need access to settings to read cookie configurations. Update constructors to accept `settings` if necessary.
   - Cookie import priority: Implement cascading logic in `ydl_opts`:
     a) If `auth.cookies_file_path` is set and the file exists on disk (use `os.path.exists`), add `'cookiefile': path`.
     b) If path is empty, but `auth.browser_cookies` is set to a specific browser (not "none"), add `'cookiesfrombrowser': (browser, )`.
     c) If both are empty/disabled, run `yt-dlp` without cookies.
   - yt-dlp Error Interception: Wrap parser calls (like `extract_info`) in `try...except yt_dlp.utils.DownloadError`. If `yt-dlp` fails (e.g., due to database locked errors when unable to read browser profile), catch the error and return a clear user notification via `error_callback` (e.g., "Не удалось прочитать куки браузера. Закройте браузер или используйте cookies.txt").
   - Add `extractor_args: {'youtube': ['player_client=android,web']}` to `ydl_opts` for YouTube.

Make sure to view the files first, verify your changes do not break existing logic, and properly inject `settings` into the services in `core/app.py` so they can read the configurations. After completing all files, provide a summary.

## Follow-up — 2026-07-13T20:52:49+03:00

Fix the audio playback issue in the AURA Music app where tracks fail to load in VLC, causing an infinite loop of skipping to the next track.

Working directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music
Integrity mode: development

## Requirements

### R1. Fix VLC Playback Failure
Currently, stream URLs extracted via `yt-dlp` (YouTube, SoundCloud) and Yandex Music fail to play in VLC. This is likely because the stream URLs are bound to specific cookies or headers that VLC is not sending. Implement a robust solution so that these URLs play correctly. If VLC cannot send the required headers/cookies, consider implementing a lightweight local HTTP proxy in the python backend to stream the data to VLC.

### R2. Fix Infinite Skipping Loop
When VLC fails to play a track (enters the Error state), `audio/engine.py` immediately calls `self.next()`. If the next track also fails, it creates an infinite skipping loop. Fix `engine.py` to handle errors gracefully (e.g., stop playback and show an error notification) rather than infinitely skipping.

## Acceptance Criteria

### Manual UI Verification
- [ ] **Playback**: Clicking play on any YouTube, SoundCloud, or Yandex track successfully plays the audio without skipping.
- [ ] **Error Handling**: If a track genuinely cannot be played, the player stops and displays a clear error message in the UI, rather than rapidly skipping through the entire playlist.

## Follow-up — 2026-07-14T08:06:11Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Создание нового ультра-современного фронтенда для десктопного музыкального приложения "Aure Music" на базе React, Vite, Tailwind CSS и Framer Motion, готового к интеграции с FastAPI бекендом и сборке через Tauri.

Working directory: `aure-music-v2` (в корневой папке текущего проекта)
Integrity mode: development

## Requirements

### R1. Инициализация и архитектура проекта
Инициализировать проект React + Vite. Настроить Tailwind CSS и Framer Motion. Использовать Zustand для управления стейтом (настройки тем, состояние плеера, режим прозрачности). Подготовить структуру для Tauri: отключить выделение текста (`user-select: none`), стилизовать кастомные скроллбары, добавить отступы в стиле macOS/Windows.

### R2. Дизайн и "Glassmorphism"
Создать стейт `isTransparencyEnabled` в Zustand.
- При `true`: использовать глубокий Glassmorphism (например, `bg-black/40 backdrop-blur-2xl border-white/10`) с эффектом свечения от текущей обложки трека на заднем фоне.
- При `false`: использовать плоские цвета (solid colors) без эффектов размытия для оптимизации производительности.

### R3. Система тем (Theme Engine)
Реализуйте переключатель для 17 цветовых тем. Темы должны менять фон приложения и акцентные цвета (accent colors) для кнопок Play, ползунков громкости и прогресс-бара.
Список тем: Dark, AMOLED, Midnight, Aqua, Emerald, Sunset, Ocean, Lavender, Rose, Amber, Slate, Light, Sky, Mint, Violet, Blossom, Sand.
(Конфиг тем должен быть легко расширяемым через CSS переменные или Tailwind плагин).

### R4. Главный интерфейс (`AurePlayer`) и анимации
Реализовать главный компонент `AurePlayer`, включающий:
- Сайдбар с навигацией и кнопками переключения прозрачности и тем.
- Главную область отображения с крупной красивой обложкой текущего трека.
- Нижнюю панель управления (Controls bar).
Добавить Framer Motion анимации: плавная смена обложки альбома (`AnimatePresence` или `layoutId`), анимация кнопок (`whileHover={{ scale: 1.05 }}`, `whileTap={{ scale: 0.95 }}`), плавное заполнение прогресс-бара трека.

### R5. Интеграся заглушек (Mock Data)
Спроектировать слои доступа к данным (API calls) с использованием заглушек (Mock Data), эмулирующих ответы от FastAPI (JSON с метаданными треков, URL на аудио и обложки). Структура должна быть готова к быстрой замене на реальные `fetch` запросы.

### R6. Инфраструктура качества кода
Настроить ESLint/Prettier, а также Vitest + React Testing Library. Написать базовые тесты для рендера компонента `AurePlayer` и переключения `isTransparencyEnabled` в Zustand.

## Acceptance Criteria

### Инициализация и Архитектура
- [ ] Проект успешно собирается командой `npm run build`.
- [ ] Стили предотвращают случайное выделение текста пользователем, скроллбар стилизован под нативный.

### Дизайн и Темы
- [ ] Zustand хранит значение `isTransparencyEnabled` и текущую тему.
- [ ] Интерфейс корректно переключается между режимом Glassmorphism (с `backdrop-blur`) и режимом Solid (без блюра).
- [ ] Доступно переключение между всеми 17 указанными темами, что меняет акцентные цвета кнопок и ползунков.

### Интерфейс и Анимации
- [ ] Отрисован `AurePlayer` (Сайдбар, Главная область, Controls bar).
- [ ] Кнопки управления плеером (Play/Pause, Next) имеют анимации `whileHover` и `whileTap`.
- [ ] Смена трека анимирует смену обложки (Framer Motion).

### Данные и Тесты
- [ ] В коде присутствует изолированный слой API с mock-данными (как минимум 2-3 трека для демонстрации смены обложек).
- [ ] Настроены `npm run lint` и `npm test`.
- [ ] Базовые тесты для UI и Zustand проходят успешно (`npm test` без ошибок).

## Follow-up — 2026-07-14T12:59:32Z

Please ensure that running `python main.py` in the root directory immediately opens the new `aure-music-v2` React UI instead of the old vanilla JS UI. Update `main.py` (which uses `pywebview`) so that it points to the new Vite project's index.html or dev server, and integrate it smoothly into the existing Python backend structure.

## Follow-up — 2026-07-17T11:39:26Z

# Teamwork Project Prompt — Draft

> Status: Ready for launch — awaiting user approval.
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Complete redesign of the "AURA Music" frontend UI to an ultra-premium, multi-theme architecture (Dotify style), along with bug fixes for transparency and playlists, and adding audio visualizers/equalizers.

Working directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music
Integrity mode: development

## Requirements

### R1. CSS Architecture & Multi-Theme Support
- Update `ui/web_new/css/styles.css` to use a narrow icon-only sidebar and a large main content container with heavy rounded corners (`border-radius: 24px+`).
- Implement the 10-theme architecture in CSS based on `data-theme` attributes (AMOLED, Dark, Midnight, Emerald, Sunset, Ocean, Lavender, Rose, Amber, Slate). The base background should be dark, with the accent color changing. (Note: `themes.css` has already been updated with variables, ensure `styles.css` uses them correctly).
- Update `settings.js` to render a grid of theme selection cards and handle `document.documentElement.setAttribute('data-theme', theme)`.

### R2. UI Component Upgrades
- Replace native range sliders (volume, progress) with custom-styled CSS sliders using the active theme's accent color.
- Convert standard checkboxes in the settings to modern switch toggles.
- Apply glassmorphism (`backdrop-filter: blur`) to floating panels, settings, and the bottom player bar.
- Add hover animations to track and playlist covers (scale up + overlay play button).

### R3. Visualizer, Equalizer & Lyrics
- Implement an Audio Visualizer on the main page (`home-visualizer-canvas`) that reacts to audio playback.
- Implement a functional Audio Equalizer (UI + Backend libvlc connection) to adjust Low, Mid, and High bands.
- Add a lyrics view (бегущий текст песни) with smooth scrolling animations.

### R4. Bug Fixes
- Fix the PyWebView native transparency issue (`transparent=True` is set, but the UI background blocks the desktop).
- Fix the library playlists bug where clicking a playlist does not open its track list.

## Acceptance Criteria

### Manual UI Verification
- [ ] Theme Switching: Clicking different themes in settings instantly changes the app's accent colors without reloading.
- [ ] Layout: The main content looks like a "window within a window" separate from the sidebar.
- [ ] Controls: Volume and progress bars are custom-styled and change color with the theme.
- [ ] Transparency: When "Native Transparency" is toggled on, the desktop wallpaper is visible behind the app.
- [ ] Playlists: Clicking a playlist in the Library successfully navigates to its contents.
- [ ] Visualizer & EQ: The home page visualizer animates during playback, and the EQ sliders successfully alter the audio output.
- [ ] Lyrics: Lyrics are displayed and can be smoothly scrolled.

## Follow-up — 2026-08-03T07:14:43Z

Создать полностью новую, независимую архитектуру рекомендаций для AURA Music, которая отказывается от алгоритмов YTMusic. Новое решение должно агрегировать «Топ исполнителей», «Популярные треки», «Новые релизы» и «Миксы», комбинируя локальную статистику прослушиваний (`core/database.py`) с открытыми API (Last.fm, SoundCloud).

Working directory: c:/Users/valee/OneDrive/Desktop/ждж/дз/AURA Music
Integrity mode: demo

## Requirements

### R1. Независимый рекомендательный движок (Last.fm + SoundCloud)
Полностью отвязать `services/recommendation_service.py` от `YTMusic.get_watch_playlist` и `get_explore`. Создать систему, которая:
1. Строит "User Taste Profile" на основе локальной базы (`core/database.py`).
2. Запрашивает похожих артистов и топ-треки через Last.fm API.
3. Разрешает метаданные треков (аудио-источники) через `SoundCloudService` или `YouTubeService` (только как поисковик, а не как генератор рекомендаций).

### R2. Контекстные миксы и смарт-лента (Home Feed)
Переписать `get_smart_home_feed` и `get_mixes`. Алгоритм должен учитывать время суток, кластеризовать жанры из профиля пользователя и формировать персонализированную ленту (Утренний вайб, Новые релизы, Топ-чарты) полностью на базе собственных расчетных весов.

### R3. Единый API интерфейс (Обратная совместимость)
Фронтенд (`ui/web_new/js/main.js`) не должен сломаться. Новый движок должен возвращать данные в том же унифицированном формате (списки словарей с полями `title`, `artist`, `cover_url`, `source`, `source_id`), что и старый.

## Acceptance Criteria

### [Programmatic Verification]
- [ ] Должен быть написан тестовый скрипт (например, `tests/test_new_recommendations.py`), который вызывает `get_smart_home_feed` с фиктивной историей (mock history).
- [ ] Скрипт должен проверять, что в результатах нет вызовов к генеративным функциям YTMusic (можно использовать mock/patch для проверки, что `YTMusic.get_explore` не вызывается).
- [ ] Возвращаемый JSON-объект фида должен строго соответствовать ожидаемому формату UI.

## Follow-up — 2026-08-03T07:19:01Z

Внимание! Пользователь обновил требования к задаче (R1, добавил R4 и R5) и предоставил пример кода.

1. R1: Добавить слияние taste-профиля со скробблами пользователя с Last.fm (pylast), если указан username — иначе профиль беднее, чем мог бы быть (локальная история + Last.fm).
2. Добавлен R4 (Отказоустойчивость и расширяемость):
- Единый интерфейс TrackSourceProvider для аудио-источников: SoundCloud приоритетный, YouTube — fallback; неразрешённый трек молча выпадает, не ломая фид.
- Ключи Last.fm/SoundCloud через env/config, без хардкода; нет ключей или API упал → движок деградирует до локальных данных (демо работает out of the box).
- Кэш ответов Last.fm в локальной БД + backoff на rate limits.
3. Добавлен R5 (stretch) — Секвенсинг миксов:
- Порядок треков по связности: жанр/mood, при наличии BPM/key в метаданных — гармонические переходы и кривая энергии (разгон → пик → спад).
4. Расширены Acceptance Criteria (тесты на get_mixes, схемная проверка, failure-тесты моков Last.fm/SoundCloud, статическая проверка отсутствия импортов YTMusic.get_watch_playlist).

Пример локальной правки для Last.fm fallback:
```python
        # --- Strategy 1.8: Last.fm API Similar Artist/Track Bridge Fallback ---
        if artist and artist != 'Unknown Artist':
            try:
                lastfm = LastFMService(self.settings)
                sim_artists = lastfm.artist.getSimilar(artist, limit=6)
                if sim_artists:
                    ytmusic = self._get_ytmusic()
                    for sa in sim_artists[:4]:
...
```

## Follow-up — 2026-08-03T08:00:35Z

Teamwork Fix Prompt — Контракт событий Home-фида и отказоустойчивость

Контекст (диагноз, не пересобирать движок — чинится слой доставки):
Бэкенд данные считает, но UI частично мёртв. Логи консоли:
- "Python Event: artists_ready (15)" → "Unknown event: artists_ready" — фронтенд не имеет хэндлера, секция «Топ исполнители» пустая.
- "feed_ready (10)" — событие распознано, но лента НЕ отрисовалась.
- "popular_results (20)" — работает, «Популярные треки» отрисовались.
- «Новые релизы» и «Миксы» висят на «Загрузка...» вечно — их события НЕ приехали вообще (пайплайн висит или не эмитит).

F1. Контракт событий (фронтенд — источник истины)
- Прочитать ui/web_new/js/events.js и main.js и выписать, КАК каждая секция дома получает данные: событие (имя + форма payload) ИЛИ RPC (pywebview.api.*).
- Привести бэкенд в точное соответствие:
  * artists_ready: эмитить событие, которое фронт реально слушает для топ исполнителей (либо добавить хэндлер в events.js — только если RPC-канала там отродясь не было);
  * feed_ready: найти рассинхрон хэндлера и payload (имена полей, id контейнера) — событие принимается, но рендера нет;
  * Новые релизы и Миксы: обеспечить доставку по тому каналу, который использует фронт, с хэндлером/ответом.
- Формат элементов не менять: title, artist, cover_url, source, source_id.

F2. Отказоустойчивость: событие обязано приехать всегда
- timeout=5s на КАЖДЫЙ исходящий HTTP-запрос (Last.fm, SoundCloud, YouTube).
- Бюджет ≤10s на сборку каждой секции; превысил или любое исключение → эмитим событие с локальными данными из SQLite (история прослушиваний).
- Эмит события — в finally топ-левел try/except каждой секции. Вечной «Загрузки...» не должно существовать ни при каком сценарии.
- Лог на каждую стадию (старт/успех/ошибка) в терминал бэкенда.

F3. Acceptance Criteria
- Контрактный тест: спарсить имена событий, на которые подписан фронтенд (events.js/main.js), и assert, что сборка home-фида эмитит каждое из них (и что у каждого эмитируемого бэкендом события есть хэндлер).
- Failure-тест: сеть отключена → все секции эмитят события ≤12s, UI рендерит локальные данные.
- E2E-смок: запуск py main.py → «Популярные треки», «Топ исполнители», «Новые релизы», «Миксы» и лента отрисованы ≤15s; в консоли НЕТ строк "Unknown event:".





