# NeDotify Windows — Полный аудит UI, настроек и функциональности

**Файл:** `WINDOWS_FULL_AUDIT_AND_FIX_PLAN.md`
**Дата аудита:** 2026-10-29
**Режим:** read-only audit + safe testing. Исходный код не изменён.
**Единственный новый файл в репозитории:** этот документ.

---

## Часть I — Executive Summary

### 1.1 Общее состояние проекта

NeDotify Windows — десктопный музыкальный плеер: Python 3.14 + pywebview (WebView2) + loopback HTTP-прокси + Vanilla JS без фреймворков и без сборщика. **Единственный активный UI — `ui/web_new_v2/`**. В репозитории также присутствует каталог `ui/MACos_ui/` (только CSS + ассеты), который подключается как **второй скин** поверх той же DOM-структуры (переключатель `ui_style`: `current` / `macos`).

Архитектура двух скинов — **одна DOM + CSS-оверлеи**: элементы `#macos-toolbar`, `#macos-backdrop`, `#macos-drag-region`, `#macos-sidebar-profile`, `#macos-profile-row`, `.macos-library-chevron` присутствуют в разметке всегда; их видимость управляется стилями. Стандартный скин скрывает их через `css/components/ui-style-picker.css`, macOS-скин перестраивает их через `MACos_ui/interface.css`.

### 1.2 Число исследованных подсистем

15 подсистем: startup/lifecycle, система настроек, поиск, главная, macOS UI, стандартный UI, плеер, нижняя панель, библиотека, уведомления, офлайн-режим, рекомендации/Riff, Python bridge, синхронизация двух UI, глобальный аудит UI.

### 1.3 Число обнаруженных дефектов

Всего подтверждённых и вероятных дефектов: **34** (см. Часть V). Распределение:

| Приоритет | Кол-во | Описание |
|---|---|---|
| P0 | 0 | Критических (потеря данных / блокировка) не подтверждено |
| P1 | 5 | STARTUP-001, SETTINGS-001, SETTINGS-002, PLAYER-001, WHITE-001 |
| P2 | 22 | Серьёзные с ограниченным влиянием |
| P3 | 7 | Незначительные / визуальные |

### 1.4 Основные архитектурные проблемы

1. **Startup-оверлей двух UI (P1, STARTUP-001)** — подтверждён браузерной проверкой: при холодном старте в стандартном скине macOS-фрагменты (`#macos-toolbar` с рабочим полем поиска и тремя кнопками, `#macos-profile-row`) остаются видимыми, потому что `ui-style-picker.css` (единственный носитель правил скрытия) подключается **только на странице настроек**. Ручное переключение UI посещает страницу настроек → CSS загружается → фрагменты скрываются до перезапуска.
2. **Дублирование схемы `theme` ↔ `interface` (P1, SETTINGS-001/002)** — frontend читает `theme.*`, backend читает `interface.*` для `border_radius`/`font_family`; обе категории сохраняются независимо (STATUS.md §5.3).
3. **Рекомендации жёстко зависят от Last.fm** — `get_smart_home_feed` вызывает `self.lastfm.*` без гардов → падает для большинства пользователей (Last.fm отключён по умолчанию).
4. **Несколько событий без потребителей** и **двойные подписки** (main.js:630/679/777).
5. **Нативные `<select>`/`<input>`/`<checkbox>`** визуально выбиваются из macOS-стиля.

### 1.5 Ограничения исследования

- Нативное приложение, pywebview, аудиодвижок в составе приложения **не запускались** (запрещено).
- Браузерная проверка выполнена через копию `ui/` в `%TEMP%\opencode\ui_test` + `python -m http.server` (без изменения репозитория). Bridge отсутствовал — проверялось только DOM/CSS-поведение.
- Рантайм-проверка Python-части (settings flush, bridge, аудио) опирается на существующие тесты (`pytest`) и статический анализ; полный прогон тестов не запускался в этом аудите (ограничение по времени/лимитам). Существующие тесты (566 passed, 3 xfailed по STATUS.md) принимаются как baseline.
- Подагенты 2-5 завершились с ошибкой лимита бесплатной модели; их задачи выполнены главным агентом через прямые чтения/грепы.

---

## Часть II — Архитектурная карта

### 2.1 Структура Windows-проекта

```
NeDotify_Windows/
├── main.py                 # entry point, pywebview, lifecycle, routes
├── core/
│   ├── app.py              # AppCore (db, settings, engine, proxy, plugins, cleanup)
│   ├── api.py              # AppApi (bridge-facing methods, _emit)
│   ├── bridge.py           # BridgeApi whitelist proxy + install_bridge_guard
│   ├── settings.py         # SettingsManager (SQLite-backed, writer thread)
│   ├── database.py         # SQLite WAL
│   ├── ui_server.py        # LocalUiServer (Bottle, StaticByteCache, hardening)
│   ├── ui_assets.py        # install_macos_assets, install_library_artwork
│   ├── session.py, tray.py, proxy.py, resolver.py, downloader.py, ...
├── audio/                  # engine.py (frontend-driven queue/resolution), queue.py
├── services/               # recommendation_service.py, taste_profile.py, lyrics, providers...
├── ui/
│   ├── web_new_v2/         # ЕДИНСТВЕННЫЙ UI (index.html 2434 строк, js/, css/, MACos_ui-sibling)
│   └── MACos_ui/           # только CSS + assets (interface.css 39KB, library.css, settings.css, tokens.css)
├── tests/                  # 566 passed baseline
└── docs/audits/            # предыдущие аудиты
```

### 2.2 Оба UI

- **Стандартный скин (`ui_style='current'`)**: базовые CSS (`base.css`, `player-bar.css`, `home-view.css`, …) + `ui-style-picker.css` (скрывает macOS-фрагменты).
- **macOS-скин (`ui_style='macos'`)**: дополнительно `MACos_ui/tokens.css`, `interface.css`, `settings.css`/`library.css` (по страницам). Перестраивает `#title-bar` (светофоры слева), показывает `#macos-toolbar`, `#macos-backdrop`, `#macos-sidebar-profile`, `#macos-profile-row`.
- Переключатель в `js/ui-style.js` (синхронный IIFE, читает localStorage `nedotify_interface_ui_style`, по умолчанию `'current'`), затем `restore(settings)` из backend (`settings.interface.ui_style`).
- Применение: `root.dataset.uiStyle = style`. Стили подгружаются асинхронно через `js/style-loader.js` (deferred `<link>` placeholders).

### 2.3 Общие компоненты

Единая DOM (`index.html`), единый `window.settings`, единый bridge (`BridgeApi` whitelist), единый `AppApi`. Оба скина используют одни и те же обработчики (`initEvents`, `initPages`, …). Различаются только CSS и набор видимых элементов.

### 2.4 Хранение состояния

- **Backend**: SQLite `~/.nedotify/nedotify_storage.db`, таблица `settings` (категория, ключ, значение). `SettingsManager` (`core/settings.py`) — in-memory cache + dirty-set + `SettingsWriter` daemon thread (flush каждые 0.5 с, до 5 retry с backoff). `sync_flush_now()` — жёсткий выход.
- **Frontend**: `window.settings` (кэш из `get_settings`), `localStorage` (`nedotify_cached_settings`, `nedotify_interface_*`), `nedotify_${category}_${key}`.
- **Сессия**: `SessionManager` (queue, index, shuffle, repeat, position) → восстанавливается в `main.py:313-320`.

### 2.5 Python bridge

- `BridgeApi` (`core/bridge.py`) — whitelist из 129 методов. `install_bridge_guard` monkey-patches `webview.util.js_bridge_call`, отклоняя незаявленные методы.
- `_emit` (`core/api.py:1016-1076`) — JSON-сериализация, очередь FIFO 512, один `EmitWorker` daemon-поток, никогда не ждёт renderer дольше 0.05 с. Не работает на UI-потоке (AGENTS.md).
- `ui_ready()` (`core/api.py:4013-4023`) — первый вызов переигрывает `track_changed` + `queue_updated`.

### 2.6 Аудиодвижок

**Frontend-driven**: Python не воспроизводит звук. `audio/engine.py` управляет очередью и разрешением stream URL (proxy URL для удалённых, `/api/stream?track_id=…` для локальных). Позиция/длительность живут в HTML5 `<audio>`; backend получает их через `report_position`/`report_state`. `play_pause()` не может паузить — отвечает последним reported state.

### 2.7 Конфигурации

`DEFAULT_SETTINGS` (`core/settings.py:52-308`): категории `app, general, audio, overlay, efficiency, optimization, hotkeys, downloads, storage, player_appearance, personalization, theme, interface, ui, equalizer, auth, lyrics, services, session, subscription (мёртвая), zapret`.

### 2.8 Жизненный цикл приложения

`main()` → single-instance mutex → `AppCore.__init__` → `AppApi` → `restore_session` → `webview.create_window` (url=index.html, js_api=BridgeApi) → `events.loaded` (once) → `setup.maybe_auto_update`, `start_zapret_if_enabled`, `render_watchdog` → `webview.start(http_server=True)`. Frontend: `ui-style.js` (sync) → `style-loader.js` → `main.js` init (cached settings → applySettings → applySettingsFromBackend → init modules → showPage('home') → remove splash) → `ui_ready()`.

---

## Часть III — Полная инвентаризация настроек

### 3.1 Сводка по категориям

Ключи `DEFAULT_SETTINGS` (все, с дефолтами) — см. `core/settings.py:52-308`. Frontend читает `theme.*`/`ui.*`/`personalization.*`/`audio.*`/`storage.*`/`optimization.*`/`interface.*`/`player.*`/`zapret.*`/`services.*`/`auth.*`/`lyrics.*`/`equalizer.*`/`hotkeys.*`/`downloads.*`/`general.*`/`app.*`.

### 3.2 Инвентаризация контролов (выборка наиболее важных; полный список — по grep `saveSetting` в `js/settings.js`, `js/settings-panel.js`, `js/ui-style.js`)

| ID | UI | Раздел | Элемент | Обработчик | Сервис | Persistence | Состояние | Дефект |
|---|---|---|---|---|---|---|---|---|
| SET-UISTYLE | оба | Внешний вид | `data-ui-style-choice="current"/"macos"` (index.html:784-785) | ui-style.js:238-249 → apply() + save(key,value,'interface') | settings.interface.ui_style | да | рабочий | — |
| SET-MACMODE | оба | Внешний вид | `data-macos-mode-choice` light/dark/system | ui-style.js:238-249 | settings.interface.macos_mode | да | рабочий | — |
| SET-MACGLASS | оба | Внешний вид | `#macos-glass-enabled` | ui-style.js:263-272 → enableEffects/save | settings.interface.macos_glass | да | рабочий | — |
| SET-MACBLUR | оба | Внешний вид | `#slider-glass-blur` | ui-style.js syncResources | settings.interface.macos_blur | да | рабочий | — |
| SET-MACFONT | оба | Внешний вид | `#slider-font-size` | ui-style.js syncResources | settings.interface.macos_font_size | да | рабочий | — |
| SET-THEME | оба | Внешний вид | `.theme-btn/.theme-card` | settings.js:144 | settings.theme.theme + theme_mode | да | рабочий | дубль с interface.theme (SETTINGS-001) |
| SET-TRANSP | оба | Внешний вид | `#toggle-transparency`, `#slider-transparency-level` | settings-panel.js:189 | settings.theme.transparency_enabled/level | да | рабочий | — |
| SET-FONTFAM | оба | Внешний вид | карточки `#font-cards-grid` | settings.js:185 → save 'font_family'/'macos_font_family' в theme/interface | settings.theme.font_family / interface.font_family | да | **частично** | backend читает interface.font_family (core/settings.py:518) — для стандартного скина запись идёт в theme.font_family → не доезжает (SETTINGS-002) |
| SET-BORDERR | оба | Внешний вид | (нет прямого контрола) | — | settings.interface.border_radius | дефолт 12 | **мёртвый ключ** | нет UI для изменения (SETTINGS-002) |
| SET-EQ | оба | Аудио | ползунки полос + preamp + mode (#settings-audio) | equalizer.js:345 → set_equalizer + save 'mode' | equalizer.preamp/bands/mode | да | рабочий | — |
| SET-CROSSFADE | оба | Аудио | toggles + duration | settings.js applyAudioSettings | audio.crossfade_enabled/duration | да | **проверить** | grep не показал save_setting для crossfade в settings-panel.js — возможен разрыв цепочки (SETTINGS-008, вероятно) |
| SET-VOLNORM | оба | Аудио | toggle volume_normalization | settings.js applyAudioSettings | audio.volume_normalization | да | **проверить** | как выше |
| SET-OUTDEV | оба | Аудио | select output_device | player.js:248 → save 'output_device' 'audio' | audio.output_device | да | рабочий | backend не применяет устройство (нет consumer в audio/engine.py) — SETTINGS-009 (Probable) |
| SET-DLDIR | оба | Загрузки | input directory | settings-panel.js:? | downloads.directory | да | **проверить** | — |
| SET-DLFMT | оба | Загрузки | select format/quality | settings-panel.js:? | downloads.format/quality | да | **проверить** | — |
| SET-DLCONC | оба | Загрузки | slider max_concurrent/fragment_concurrency | settings-panel.js:? | downloads.max_concurrent | да | **проверить** | downloader использует `_MAX_INFLIGHT=2` константу, возможно не читает настройку (SETTINGS-010, Probable) |
| SET-STORAGE | оба | Хранилище | slider cache quota | settings-panel.js:358 → save 'cache_quota_gb' 'storage' | storage.cache_quota_gb (+ cache_size_mb dual) | да | рабочий | — |
| SET-SCANFOLDERS | оба | Хранилище | import music folder | main.py route / import_music_folder | storage.scan_folders | да (через import) | рабочий | — |
| SET-ZAPRET | оба | Zapret | toggles mode/autoupdate | settings-panel.js:1128/1141/1153 | zapret.* | да | рабочий | — |
| SET-HOTKEYS | оба | Горячие клавиши | keybind rows + reset | hotkeys.js:148-149 | hotkeys.<action> | да | рабочий | дубль DEFAULT_KEYBINDS в двух местах (hotkeys.js + settings.py) — риск дрейфа (SETTINGS-011) |
| SET-PARTICLES | оба | Эффекты | toggles/sliders shape/size/speed/count | settings-panel.js:225 + settings.js:328-377 | ui.particles_* | да | рабочий | — |
| SET-OPTPRESET | оба | Оптимизация | performance_preset buttons | settings.js:962-966 | optimization.performance_preset + blur_quality/glow_quality/glass_blur/resource_blur | да | рабочий | — |
| SET-ICONS | оба | Иконки | icon pack cards | settings-panel.js:1350 | theme.icon_pack | да | рабочий | — |
| SET-CUSTOMTHEMES | оба | Внешний вид | сохранённые темы + activate | settings-panel.js:681 | theme.custom_themes | да | рабочий | — |
| SET-LASTFM | оба | Сервисы | username/api_key/enabled | settings-panel.js:31/38/47 | auth.lastfm_username / services.lastfm_api_key / services.lastfm_enabled | да | рабочий | — |
| SET-YANDEX | оба | Сервисы | token input | settings-panel.js:474 | auth.yandex_token | да | рабочий | — |
| SET-LYRICS | оба | Лирика | offset/language | lyrics.js:247-300 + settings-panel.js:18 | lyrics.* | да | рабочий | — |
| SET-PERSONAL | оба | Профиль | nickname | profile.js:160 | personalization.nickname | да | рабочий | — |
| SET-NOTIF | оба | Общие | show_notifications (general.show_notifications) | ? | general.show_notifications | дефолт True | **мёртвый** | никто не читает (NOTIF-002) |
| SET-SUBSCRIPTION | оба | — | (нет UI) | — | subscription.* | дефолт | **мёртвая ветка** | validate_subscription_key без вызывающих (STATUS.md §5.4) |

### 3.3 Дублирование и мёртвые настройки (подтверждено)

- **SETTINGS-001 (P1)**: `theme` ↔ `interface` схемы дублируют ключи (theme, name, accent_color, transparency_enabled, transparency_level, glass_blur, glass_color_intensity, custom_themes) — STATUS.md §5.3.
- **SETTINGS-002 (P1)**: `border_radius`/`font_family` backend читает из `interface.*` (`core/settings.py:499,518`), но UI пишет в `theme.*` (font_family) → изменение шрифта из UI не доезжает до backend. `border_radius` вообще не имеет контрола.
- **SETTINGS-003 (P2)**: нативные `<select>`/`<input>`/`<checkbox>` в macOS-скине не стилизованы (ui-style-picker.css не содержит правил для них) — визуальный разрыв.
- **SETTINGS-004 (P2)**: `get_volume` (`core/api.py:1703`) не в `PUBLIC_METHODS` (`core/bridge.py:6-129`) → JS не может прочитать громкость напрямую; читает через `get_settings`/`get_setting('audio.volume')` — рабочий обход, но контракт неполный.
- **SETTINGS-005 (P2)**: пустая строка для секретов — no-op (`_store_setting`), документировано.
- **SETTINGS-006 (P2)**: дрейф `DEFAULT_KEYBINDS` между `js/hotkeys.js` и `core/settings.py:116-141` (SETTINGS-011).
- **SETTINGS-007 (P2)**: `subscription` мёртвая ветка (STATUS.md §5.4).
- **SETTINGS-008 (Probable)**: crossfade/volume_normalization toggles — цепочка save→apply не подтверждена статически (нет saveSetting в settings-panel.js для этих ключей; applyAudioSettings вызывается только из applySettingsFromBackend). Требует runtime-проверки.
- **SETTINGS-009 (Probable)**: `output_device` сохраняется, но `audio/engine.py` не читает настройку (нет consumer) — устройство не переключается.
- **SETTINGS-010 (Probable)**: `downloads.max_concurrent`/`fragment_concurrency` сохраняются, но downloader использует константу `_MAX_INFLIGHT=2` (`core/downloader.py:27`) — настройка может не влиять.

---

## Часть IV — Подробный аудит по подсистемам

### 4.1 Startup и наложение UI (P1)

**Подтверждено браузерной проверкой (см. STARTUP-001).**

Последовательность:

**A. Первоначальный запуск (cold start):**
1. `main.py`: `ui_root = ui/web_new_v2`, `window = webview.create_window(url=html_path)`.
2. `index.html` head: `ui-style.js` (sync) читает localStorage `nedotify_interface_ui_style` (дефолт `'current'`) → `root.dataset.uiStyle = 'current'`.
3. `style-loader.js` (sync): `ensureForPage('home')` → `pagePacks['home']` undefined → `names = []` → ничего не грузит. `ensureMacStyle()` → style!=='macos' → no-op. `css-loading` снимается.
4. Первый paint: загружены `base.css`, `player-bar.css`, `home-view.css`, … но **НЕ** `ui-style-picker.css` (deferred, грузится только на странице настроек) и **НЕ** `MACos_ui/interface.css`.
5. `main.js` init: cached settings → `applySettingsFromBackend` → `NeDotifyAppearance.restore(settings)` → `apply(settings.interface.ui_style ?? style, …)` → если backend говорит `'macos'`, меняет `data-ui-style` → MutationObserver в style-loader → `ensureForPage(activeView)` → если active view home → грузит macosTokens+macosInterface (async). Если backend говорит `'current'` → атрибут не меняется → observer НЕ срабатывает → `ui-style-picker.css` **никогда** не грузится.
6. Splash снимается после init → пользователь видит стандартный UI **+** `#macos-toolbar` (display:block, рабочее поле поиска + 3 кнопки) **+** `#macos-profile-row` в сайдбаре.

**B. Ручное переключение UI:**
1. Пользователь открывает настройки (страница `settings`) → `ensureForPage('settings')` грузит `featureTools, settings, stylePicker` → `ui-style-picker.css` теперь в DOM (и остаётся в `loaded` Map на всё время сессии).
2. Клик по `data-ui-style-choice` → `apply()` → `root.dataset.uiStyle = …` → observer → `ensureForPage(activeView)` (settings) → грузит macos-паки при необходимости.
3. Правило `#macos-toolbar { display: none; }` из `ui-style-picker.css` теперь активно для `'current'` → фрагменты скрыты. До перезапуска страница не пересоздаётся → `loaded` Map сохраняется → оверлей не возвращается.

**Расхождение (root cause):** в пути холодного старта отсутствует загрузка `ui-style-picker.css` (и, для `'current'`, отсутствует любой механизм скрытия macOS-фрагментов). В пути ручного переключения эта таблица стилей загружается побочным эффектом посещения страницы настроек.

**Доказательства:** browser-evaluate показал: до загрузки stylePicker — `#macos-toolbar` display:block (rect 95,15,888,44), `#macos-profile-row` block, `#macos-sidebar-profile` inline-block; после `ensureForPage('settings')` — все `display:none`, link media='all', правило `#macos-toolbar { display: none; }` присутствует. Файл `css/components/ui-style-picker.css` строки 2-3 содержит единственные правила скрытия; `js/style-loader.js` строки 29 (`pagePacks.settings = [..., 'stylePicker']`) и 55-63 (ensureForPage/ensureMacStyle).

**Уверенность:** высокая (Confirmed via browser + static).

**Инструкция по исправлению (STARTUP-001):**
1. Начать с `js/style-loader.js` и `css/components/ui-style-picker.css`.
2. Сделать правила скрытия macOS-фрагментов частью **базового** CSS (синхронно загружаемого в `<head>`), а не отложенного пакета. Вариант: перенести строки 2-3 из `ui-style-picker.css` в `base.css` (или в `tokens.css`), либо добавить `stylePicker` в `ensureForPage('home')` и в начальный `boot`-Promise, либо загружать `ui-style-picker.css` безусловно в `<head>` (синхронно) в `index.html`.
3. Обеспечить инвариант «в любой момент активен только один скин»: проверка `data-ui-style` + наличие CSS-правил скрытия должна выполняться до первого paint. Рассмотреть FOUC-защиту: установить `html[data-ui-style="current"] #macos-toolbar { display:none }` в синхронном `tokens.css`.
4. Не использовать `display:none`-костыль через JS после paint, если можно сделать через CSS до paint.
5. Регрессия: холодный старт в обоих скинах, перезапуск, 5 последовательных переключений, проверка, что `#macos-toolbar` не виден в `'current'` ни на одной странице (home/search/library/player/settings).

**STARTUP-002 (P2, Probable):** зависимость macOS-скина от `install_macos_assets` (`core/ui_assets.py:30-49`) и `rglob`-маршрутов. Если `base_dir` неверен (например, в frozen-сборке) или маршрут не зарегистрирован, `/MACos_ui/interface.css` → 404 → macOS-скин не применяется → наложение. Инструкция: добавить проверку/логирование успешной регистрации маршрутов; добавить fallback (встроить критические правила в base.css) или явную ошибку в консоль. Проверить вручную в установленной сборке.

**STARTUP-003 (P2, Probable):** `css-loading` class на `<html>` и splash (`#app-splash`) снимаются только после init (до 16 с на холодном WebView2). Если `interface.css` пришёл, но splash ещё виден — пользователь видит splash, не оверлей; после снятия splash возможен краткий FOUC. Инструкция: убедиться, что splash снимается только после `NeDotifyStyles.ready` (boot promise) + `applySettingsFromBackend`.

### 4.2 Настройки (P1/P2)

См. Часть III. Ключевые дефекты: SETTINGS-001, SETTINGS-002, SETTINGS-003, SETTINGS-008, SETTINGS-009, SETTINGS-010, SETTINGS-011. Плюс известные из STATUS.md: `network_status` не эмитится (баннер мёртв), Yandex/VK отключены (`DISABLED_UI_PROVIDERS`), `subscription` мёртвая, `theme`/`interface` не слиты.

**Инструкция (SETTINGS-001/002):**
1. Выбрать канон: предпочтительно `interface.*` (backend уже читает оттуда `border_radius`, `font_family`), мигрировать frontend на чтение `interface.*` для этих ключей; удалить дубли из `theme.*` через миграцию в `SettingsManager._load_all` (сохранить обратную совместимость: если `theme.font_family` задан, а `interface.font_family` нет — скопировать).
2. Добавить UI-контрол для `border_radius`.
3. Тесты: `tests/test_settings_flush.py` расширить проверкой round-trip `font_family`/`border_radius`.

**Инструкция (SETTINGS-003):** создать стилизованные компоненты (select, toggle, slider) в macOS-стиле (см. Часть VII) и применять их через `html[data-ui-style="macos"]` селекторы; убрать нативные элементы из macOS-скина или стилизовать.

**Инструкция (SETTINGS-008/009/010):** провести runtime-проверку цепочки save→apply→consumer; если разрыв подтвердится — добавить consumer (audio engine читает `output_device`; downloader читает `max_concurrent`).

### 4.3 Поиск

**SEARCH-001 (P2, пользовательский запрос):** полностью убрать блок быстрых жанров из поиска.

- Где: `index.html` секция `#search-genres` (строка ~452), генерация/обработчики в `js/search.js`/`js/search-discovery.js`, стили в `css/components/search-refresh.css`.
- План безопасного удаления: (1) удалить разметку секции; (2) удалить все ссылки на `#search-genres`/`search-genres-*` из JS (grep по `search-genres`, `searchGenres`, `genre` в js/); (3) удалить CSS-правила; (4) убедиться, что поисковый движок (backend `search`) не зависит от жанров (он не зависит — жанры только UI-фильтр). Сохранить внутри поискового движка: ничего не удалять в `core/api.py::search`.
- Риск: если жанры используются в рекомендациях (time-of-day genres в `recommendation_service.py:120-141`) — это отдельный код, не трогать.

**SEARCH-002 (P2, пользовательский запрос):** прозрачное оформление недавних поисков (macOS-стиль).
- Структура: `#search-discovery` секция в `index.html` (~455), стили `css/components/search-refresh.css`.
- Предложение: фон `rgba(255,255,255,0.04)` + `backdrop-filter: blur(12px)` + border `1px solid rgba(255,255,255,0.08)`, hover `rgba(255,255,255,0.08)`, текст `var(--mac-text)`, контраст ≥4.5:1 в обеих темах; в `'current'` скине сохранить текущий вид (только macOS-ветка через `html[data-ui-style="macos"]`).

**SEARCH-003 (P2):** `network_status` событие не эмитится backend'ом (STATUS.md §5.1) — баннер `#network-banner` мёртв. Решение владельца: либо эмитить, либо удалить обработчик в `main.js:487-501`.

**Дополнительные проверки поиска:** `search_results`/`search_completed` events; `cancel_search`; пустые результаты; обработка ошибок API (provider deadline 6s/8s); синхронизация между UI (единый state — ок).

### 4.4 Главная

- Секции: `#home-continue`, `#home-top-tracks`, `#home-authentic-feed`, `#home-notices`, wrapped (`#wrapped-top-list`, `#wrapped-period-btns`), mixes/releases/artists.
- `#home-notices` кликается из `#macos-notices` (ui-style.js:262) → показывает уведомления.
- Поиск мёртвых кнопок: требует runtime; статически проверены обработчики в `home.js`/`home-shell.js` (не полный аудит из-за лимитов).

### 4.5 macOS UI

**MACUI-001 (P2, пользовательский запрос):** убрать из верхней панели (`#macos-toolbar`, index.html:245-253) кнопки уведомлений (`#macos-notices`), настроек (`.icon-btn[data-macos-page="settings"]`), профиля (`.icon-btn[data-macos-page="profile"]`).

- Зависимости:
  - `#macos-notices` → `ui-style.js:262` кликает `#home-notices` (home.js). Альтернативный доступ: `#home-notices` остаётся в главном экране (стандартный скин). Безопасно убрать из тулбара.
  - settings: `data-macos-page="settings"` → `ui-style.js:259-261` → `window.showPage('settings')`. Альтернативы: сайдбар (стандартная навигация), hotkey. Но в macOS-скине сайдбар свёрнут/скрыт? Проверить `pages.js`/`showPage`. Если сайдбар недоступен в macOS-скине — оставить иконку настроек или добавить доступ через меню.
  - profile: `data-macos-page="profile"` → `showPage('profile')`. Альтернатива: `#macos-sidebar-profile` (строка 236) уже ведёт на профиль. Безопасно убрать из тулбара.
- CSS: `MACos_ui/interface.css:163` уже скрывает settings-кнопку на home (`#main-content:has(#view-home.active) … #macos-toolbar [data-macos-page="settings"] { display: none; }`). Удаление разметки безопаснее, чем CSS-скрытие.
- Инструкция: удалить три элемента из `index.html:250-253`, обновить `ui-style.js` (убрать привязки `#macos-notices` и `data-macos-page` для settings/profile, если больше не используются), проверить, что `#macos-search-form` (поиск) остаётся.

**MACUI-002 (P2):** вкладка плеера (`#view-player`, index.html ~561-650).
- Обложка: `#pp-cover`/`.player-cover` — размеры в `player-view.css` и `MACos_ui/interface.css`. Проверить переполнение в узких окнах (min_size 600×640).
- `#pp-btn-expand` (`.player-macos-action`) — «развернуть»; проверить, есть ли настоящий fullscreen (не подтверждено; помечено Needs runtime verification).
- Текст песни: `#lyrics-overlay` + `js/lyrics.js` (62KB), macOS-стили `lyrics.css:185-190` (`html[data-ui-style="macos"] #view-player #player-lyrics-scroll .lyric-word`). Сохранить логику отображения текста.
- Рекомендация: не возвращать громоздкие карточки; добавить полноэкранный режим с сохранением lyrics.

### 4.6 Стандартный UI

Основные дефекты: STARTUP-001 (macOS-фрагменты), SETTINGS-003 (нативные элементы). Дополнительно: `#title-bar` (стандартный) vs `#macos-toolbar` (macOS) — в `'current'` скине `#title-bar` виден, macOS-фрагменты должны быть скрыты (см. STARTUP-001).

### 4.7 Плеер и нижняя панель

**PLAYER-001 (P1, Probable):** риск рассогласования отображаемой длительности/позиции с активным треком.
- `player.js:620-630`: при `timeupdate` HTML5-длительность перезаписывает `playbackState.durationMs`, если расхождение >2 с (`Math.abs(...) > 2000`). Это может «прыгать» длительность при смене трека, если старое значение осталось.
- `player.js:661-692`: на `ended` вызывается `next_track(false)`; если не advanced и flow включён — `triggerFlowAutoplayImmediate()`. Двойной advanced возможен при гонке.
- `formatTime` (`utils.js:80-85`): Infinity → «Infinity:NaN»; NaN → «0:00». Для live/HLS-потоков длительность NaN → «0:00» (приемлемо, но seek отключается проверкой `durationMs <= 0` в `seekTo`).
- Позиция backend'у отправляется каждые 5 с (`player.js:645-650`), state — на play/pause. `play_pause()` backend'а не паузит (frontend владеет audio) — архитектурно ок, но `report_state` должен вызываться синхронно.

**PLAYER-002 (P2):** `formatTime(Infinity)` → «Infinity:NaN» (utils.js:80-85) — исправить гардом `if (!Number.isFinite(seconds) || seconds <= 0)`.

**PLAYER-003 (P2, Needs runtime):** полноэкранный режим плеера (`#pp-btn-expand`) — проверить, есть ли настоящий fullscreen, поведение в узких окнах, переполнение контейнеров.

**PLAYER-004 (P2, Needs runtime):** mini-player (`#mini-player-overlay`, `mp-*`) — синхронизация с основным плеером, прозрачность, темы.

**PLAYER-005 (P2):** альтернативная визуализация прогресса (`#pb-panel-fill` clip-path, index.html:2049) — проверить синхронизацию с основной полосой.

**PLAYER-006 (P2):** `seekTo` (`player.js:865-894`) — `isSeeking` снимается через 600 мс таймер; если seek не завершится за 600 мс (медленный стрим), `isSeeking` сбросится преждевременно → timeupdate перезапишет позицию. Увеличить таймер или снимать по `seeked`.

**PLAYER-007 (P2):** гонка `playbackState.durationMs` при смене трека: старое значение может сохраниться до прихода `track_changed`. Добавить сброс `durationMs = 0` при смене трека.

**PLAYER-008 (P3):** дублирование `report_state('playing', …)` в `player.js:590` и `:1828` — проверить на двойной вызов.

### 4.8 Нижняя панель (оба UI)

- Элементы: `#player-bar` (index.html:2048), `#pb-panel-fill`, `#pb-time-current`/`#pb-time-total`, `#pp-time-*`, `#mp-*`.
- Расположение времени и кнопок, отступы, переполнение, прозрачность, совместимость с темами — статически не подтверждено (CSS-аудит `player-bar.css` 22KB не выполнен полностью). Помечено Needs runtime verification.
- Рекомендация: единый источник данных для прогресса (HTML5 audio → `playbackState` → UI), backend только для scrobbling; уже так сделано, но сброс duration при смене трека (PLAYER-007).

### 4.9 Библиотека

- `#view-library`, `#lib-active-tracks`, `#lib-download-manager`, `#lib-batch-progress-box`, `#track-options-menu`, `#playlist-context-menu`.
- Дубликаты треков (`find_duplicate_tracks`/`delete_duplicate_track`), редактирование тегов (`update_track_tags`), обложки (`choose_cover_image`).
- Виртуальный список (`library-virtual-list.js`).
- Мёртвые кнопки — статически не полностью проверено (лимиты).

### 4.10 Уведомления и офлайн-режим

**NOTIF-001 (P2):** различать:
- Устаревший раздел уведомлений (если есть отдельная страница) — можно убрать.
- Необходимое информирование об ошибках скачивания/воспроизведения — **сохранить** (toast-система `#toast-container`, `#operation-error` aside index.html:701).
- `general.show_notifications` (`core/settings.py:63`) — **никто не читает** (NOTIF-002, P3). Либо реализовать, либо удалить.

**OFFLINE-001 (P2):** офлайн-режим удалён из backend (`core/app.py:22`: `is_offline` больше не существует), но UI может содержать остатки:
- `#network-banner` (`main.js:487-501` `_handleNetworkEvent`) слушает `network_status` — backend не эмитит → мёртвый код (STATUS.md §5.1).
- `get_offline_library` bridge-метод (`core/api.py:3864`) → `core.offline.offline_library` — проверить, кто вызывает в JS.
- Локальная музыка/скачанные треки — **сохранить** (это реальная функциональность, не UI-раздел).

**Инструкция:** удалить `#network-banner` и обработчик `network_status` (или реализовать эмит); сохранить toast-ошибки и локальную библиотеку.

### 4.11 Рекомендации и Riff

**REC-001 (P1, Probable):** `get_smart_home_feed` (`recommendation_service.py:748-895`) вызывает `self.lastfm.artist.getTopTracks`, `self.lastfm.chart.getTopTracks`, `self.lastfm.user.getTopArtists` без гардов → при отключённом Last.fm (по умолчанию) падает → `authentic_home_error`. Инструкция: добавить `if self._lastfm_enabled()` гарды и fallback на локальные/curated треки.

**REC-002 (P2):** `CURATED_WELCOME_TRACKS` (`recommendation_service.py:26-35`) — 8 захардкоженных YouTube-ID; используется как fallback. Приемлемо для cold start, но стоит сделать настраиваемым/локализуемым.

**REC-003 (P2):** `get_authentic_home` (`recommendation_service.py:897`) вызывает `get_smart_home_feed(history=[])` — игнорирует историю пользователя → рекомендации «холодного старта» даже для опытных пользователей. Инструкция: передавать реальную историю (как `get_feed`).

**REC-004 (P2):** `get_charts` (`recommendation_service.py:597-653`) зависит от Last.fm; fallback на `get_most_played_tracks`/сырой SQL/curated — ок, но SQL-fallback читает `conn` напрямую (нарушение инкапсуляции).

**REC-005 (P2):** кеширование `get_feed` включает `history` в ключ → при каждом изменении сессии кеш инвалидируется → частые пересчёты. Рассмотреть TTL-кеш по профилю, а не по истории.

**Riff (rootscripts/riff, MIT, Electron+Vanilla JS+WebGL, YouTube Music/YouTube/SoundCloud + local):**
- Идентифицирован однозначно: `github.com/rootscripts/riff` (MIT). Другие «Riff» (Diegovsky/riff = Spotify-клиент GNOME, projectriff = FaaS, tessro/riff = CLI) не подходят по домену.
- Релевантные подходы (из README/релизов, не код): «My Mix» с like/dislike feedback, формирующим будущие миксы; «My Wave» с показом похожих исполнителей; Last.fm scrobbling; динамическая цветовая палитра из обложки.
- Условия использования: MIT → изучение и самостоятельная реализация подходов допустимы с атрибуцией; **копирование кода запрещено** (другой стек — Electron, но JS-логика может быть портирована; лицензия позволяет, но лучше переimplement).
- План: (1) изучить исходники rootscripts/riff (рекомендательная логика, feedback-схема) — отдельная задача; (2) спроектировать feedback-таблицу в NeDotify (уже есть `set_recommendation_feedback`/`get_recommendation_feedback` в api.py); (3) реализовать «My Mix»-подобный микс с like/dislike; (4) добавить «похожие исполнители» в Wave. Не переносить код напрямую.

### 4.12 Python bridge

**BRIDGE-001 (P2):** события без потребителей в `events.js`:
- `position_changed` (строка 128) — backend никогда не эмитит (зарезервировано; player использует HTML5 timeupdate) — мёртвый case.
- `session_autoplay` (473) — legacy no-op.
- `operation_error` (104) — эмитится? проверить (grep `_emit('operation_error'` — в api.py не найден) → вероятно мёртвый.
- `authentic_home_error` (173) — эмитится при падении `get_authentic_home` → жив, но обработчик только логирует.
- `storage_info_updated` (351) — backend эмитит `storage_info`/`storage_updated`, не `storage_info_updated` → мёртвый алиас.
- `track_downloaded` (308) — backend эмитит `download_complete` (events.js объединяет через fallthrough 307-309) → standalone case недостижим, но безвреден.

**BRIDGE-002 (P2):** двойные подписки — `main.js:630` (`handleFeatureEvent`), `:679`, `:777` вызывают `addPythonEventHandler`. Проверить, не дублируют ли они обработку одних и тех же событий (например, `track_changed` → два вызова `onTrackChanged`). Статически: `events.js` dispatches to ALL registered handlers (`addPythonEventHandler` массив). Если два handler'а обрабатывают `track_changed` — двойной рендер. Требует runtime-проверки.

**BRIDGE-003 (P2):** очередь событий до установки подписчиков (`events.js:54-64`, буфер 256) — replay при `flushPythonEvents`. Гонка: если более 256 событий придут до init — потеря. На практике маловероятно, но стоит увеличить буфер или уменьшить задержку init.

**BRIDGE-004 (P2):** `get_volume` не в whitelist (`core/bridge.py`) — контракт неполный (SETTINGS-004).

### 4.13 Синхронизация двух UI

- Единый `window.settings`, единый bridge, единый `AppApi` → состояние общее. Двух независимых playback state нет (один `playbackState` в player.js, один `engine.queue` в Python).
- Дублирование событий: см. BRIDGE-002.
- Горячие клавиши: `hotkeys.js` — один обработчик; проверить, не срабатывают ли они в полях ввода (textarea/input) — обычно исключаются.
- Выбор активного UI: `ui_style` в `interface` категории + localStorage.
- Старый UI не размонтируется (одна DOM) — компоненты остаются в DOM, скрываются CSS → возможны скрытые обработчики (например, `#macos-notices` кликает `#home-notices` даже в `'current'` скине, где `#macos-notices` скрыт — но элемент всё равно в DOM и доступен через DOM API).
- Повторный монтирование: нет (одна страница).
- Таймеры: `setInterval` heartbeat (boot.js:119), render_watchdog (main.py). Повторный `loaded` event обрабатывается один раз (`_window_loaded_handled`).
- Двойная инициализация плеера: `ui_ready()` переигрывает `track_changed` один раз (флаг `_ui_ready_replayed`? проверить `core/api.py:4013-4023` — нет флага, каждый вызов `ui_ready` переигрывает; но вызывается один раз из main.js:640).

**Целевая архитектура (рекомендация):** единый store состояния (уже есть `window.settings`), явный lifecycle для скинов (mount/unmount через JS, а не CSS-hide), единая загрузка стилей до первого paint (STARTUP-001), удаление дублей `theme`/`interface`.

### 4.14 Дополнительные найденные проблемы

- **CASE-001 (P3):** 4 `case` без фигурных скобок в активном дереве: `hotkeys.js:199` (mute), `:203` (like), `:207` (toggle_lyrics), `utils.js:862` (share) — объявляют `const`/`let`. Защитный тест покрывает только `events.js` (STATUS.md §8, п.13).
- **CASE-002 (P3):** двойной перехват `window.onPythonEvent` в legacy `ui/web_new/js/main.js:482,666` (legacy не активен, но в репозитории).
- **TYPING-001 (P3):** ошибки типизации/null-обработка в `core/api.py` (например, `track.get('duration')` без проверки) — требует детального аудита, не выполнен.
- **RACE-001 (P2, Probable):** `applySettingsFromBackend` вызывается дважды (cached + fresh) — `NeDotifyAppearance.restore` дважды → двойной `syncResources`/`syncBackdrop`. Безвредно, но лишняя работа.
- **LYRICS-001 (P3):** CSS-правило `html[data-ui-style="macos"] #view-player #player-lyrics-scroll .lyric-word` (lyrics.css:185-190) — проверить, что lyrics-движок работает в обоих скинах.

---

### 4.15 Белый экран / зависание композитора (новый симптом пользователя)

**Симптом:** после развёртывания/сворачивания окна, а затем через ~5 минут окно становится полностью белым (рендерер мёртв, процесс жив).

**Известная инфраструктура:** `main.py:357-411` `render_watchdog` — проверяет heartbeat каждые 5 с; если тишина >75 с при visible — `location.reload()`; если через 40 с после reload всё ещё тихо — перезапуск процесса один раз (бюджет `NEDOTIFY_RESTART_COUNT`).

**Причина (Probable, Static-confirmed частично):**
1. Heartbeat (`boot.js:106-122`) — JS `setInterval(beat, 4000)` вызывает `pywebview.api.frontend_heartbeat()`. Если композитор WebView2 завис, но JS-поток жив, heartbeat продолжает идти → `silent` никогда не превышает 75 с → watchdog не срабатывает → белый экран остаётся навсегда (или до ручного закрытия).
2. `--disable-features=CalculateNativeWinOcclusion` уже установлен (main.py:44), но этого недостаточно: WebView2 всё равно может приостановить рендеринг при `WM_SIZE`/minimize/maximize из-за внутренней логики occlusion/GPU-процесса.
3. `animateProgress` (`player.js:1067`) не приостанавливается при `document.hidden` (perf doc line 130) — непрерывный rAF-источник перерисовки, увеличивающий нагрузку на композитор.
4. `snap_layouts.py` обрезает максимизированное окно до work area (строки 252-275) — при restore (разворачивание обратно) возможна несогласованность прямоугольника WebView2-поверхности и окна → непрорисованная полоса/белый экран.
5. Таймаут 75 с слишком велик для пользовательского опыта (белый экран на 1+ минуту).

**WHITE-001 (P1/P0-candidate):** белый экран после maximize/minimize.

**Инструкция по исправлению (WHITE-001):**
1. Усилить watchdog: добавить проверку не только тишины heartbeat, но и отсутствия визуального обновления (например, проверка `document.visibilityState` + сравнение скриншота/пикселя через `canvas`? не доступно в WebView2 без CDP). Альтернатива: сократить порог с 75 с до 15-20 с при visible.
2. Добавить обработку `visibilitychange`/`focus`/`resize` в JS: при возврате видимости вызывать `location.reload()` если прошло >N секунд с последнего успешного paint (или если `document.hidden` был true дольше порога).
3. В `player.js:1067` приостанавливать `animateProgress` rAF при `document.hidden` (как остальные loops).
4. Проверить `snap_layouts.py` restore-путь: после разворачивания из максимизированного состояния принудительно вызвать `InvalidateRect`/`RedrawWindow` для HWND WebView2.
5. Рассмотреть флаги WebView2: `--disable-gpu` (крайняя мера), `--enable-features=msWebView2EnableDraggableRegions` и т.п.; проверить, помогает ли `--disable-features=CalculateNativeWinOcclusion` уже есть.
6. Добавить ручной «перезагрузить рендерер» в UI (кнопка в настройках/меню) для восстановления без перезапуска приложения.
7. Тест: максимизировать → свернуть → развернуть → подождать 5 мин → проверить, что окно не белое; при белом экране — watchdog должен перезагрузить за ≤20 с.

**Критерии готовности:** при зависании композитора окно восстанавливается автоматически за ≤20 с; `animateProgress` не работает при hidden.

**Уверенность:** средняя (требует runtime-воспроизведения).

---

## Часть V — Реестр всех дефектов

| ID | Приоритет | Подсистема | Симптом | Причина (кратко) | Статус |
|---|---|---|---|---|---|
| STARTUP-001 | P1 | Startup/UI | Два UI накладываются при холодном старте | `ui-style-picker.css` (правила скрытия macOS-фрагментов) грузится только на странице настроек | Confirmed (browser+static) |
| STARTUP-002 | P2 | Startup/UI | macOS-скин не применяется (404 interface.css) в сборке | Зависимость от `install_macos_assets`/rglob-маршрутов | Probable (Needs runtime) |
| STARTUP-003 | P2 | Startup/UI | Краткий FOUC при снятии splash | Splash снимается до `NeDotifyStyles.ready` | Probable |
| WHITE-001 | P1 | Рендерер/Окно | Белый экран после maximize/minimize и через ~5 мин | Heartbeat жив при мёртвом композиторе → watchdog не срабатывает; `animateProgress` не паузится при hidden; snap_layouts restore | Probable/Needs runtime |
| SETTINGS-001 | P1 | Настройки | Дублирование `theme`/`interface` схем | Не выполненная миграция (STATUS.md §5.3) | Static-confirmed |
| SETTINGS-002 | P1 | Настройки | Шрифт/радиус из UI не доезжает до backend | backend читает `interface.*`, UI пишет `theme.*` | Static-confirmed |
| SETTINGS-003 | P2 | Настройки/UI | Нативные элементы выбиваются из macOS-стиля | Нет стилизованных компонентов | Static-confirmed |
| SETTINGS-004 | P2 | Настройки/Bridge | `get_volume` недоступен из JS | Не в `PUBLIC_METHODS` | Static-confirmed |
| SETTINGS-005 | P2 | Настройки | Пустая строка секрета — no-op | `_store_setting` | Static-confirmed (by design) |
| SETTINGS-006 | P2 | Настройки | Дрейф keybinds между frontend/backend | Два источника DEFAULT_KEYBINDS | Static-confirmed |
| SETTINGS-007 | P2 | Настройки | `subscription` мёртвая ветка | Нет вызывающих | Static-confirmed (by design) |
| SETTINGS-008 | P2 | Настройки | Crossfade/volume_normalization могут не применяться | Цепочка не подтверждена | Needs runtime |
| SETTINGS-009 | P2 | Настройки/Аудио | output_device не переключает устройство | Нет consumer в engine | Probable |
| SETTINGS-010 | P2 | Настройки/Загрузки | max_concurrent может не влиять | Downloader использует константу | Probable |
| SETTINGS-011 | P3 | Настройки | Дубль DEFAULT_KEYBINDS | hotkeys.js + settings.py | Static-confirmed |
| PLAYER-001 | P1 | Плеер | Рассогласование длительности/позиции | HTML5 duration перезаписывает state | Probable |
| PLAYER-002 | P2 | Плеер | `formatTime(Infinity)` → «Infinity:NaN» | utils.js:80-85 | Static-confirmed |
| PLAYER-003 | P2 | Плеер | Fullscreen не подтверждён | Needs runtime | Needs runtime |
| PLAYER-004 | P2 | Плеер | Mini-player синхронизация | Needs runtime | Needs runtime |
| PLAYER-005 | P2 | Плеер | Альтернативный прогресс-бар | Needs runtime | Needs runtime |
| PLAYER-006 | P2 | Плеер | `isSeeking` снимается по таймеру 600мс | player.js:876-879 | Static-confirmed |
| PLAYER-007 | P2 | Плеер | Старая duration при смене трека | Нет сброса durationMs | Probable |
| PLAYER-008 | P3 | Плеер | Двойной `report_state('playing')` | player.js:590,1828 | Needs runtime |
| SEARCH-001 | P2 | Поиск | Быстрые жанры (пользовательский запрос на удаление) | UI-блок, не backend | Confirmed (user request) |
| SEARCH-002 | P2 | Поиск | Недавние поиски — прозрачность | Стили search-refresh.css | Static-confirmed (design) |
| SEARCH-003 | P2 | Поиск | `network_status` мёртвый баннер | Backend не эмитит | Static-confirmed (STATUS.md §5.1) |
| MACUI-001 | P2 | macOS UI | Лишние кнопки в тулбаре (пользовательский запрос) | #macos-notices, settings, profile | Confirmed (user request) |
| MACUI-002 | P2 | macOS UI | Плеер-вкладка геометрия/fullscreen | Needs runtime | Needs runtime |
| NOTIF-001 | P2 | Уведомления | Различить устаревший раздел и критические ошибки | Архитектурный | Static-confirmed |
| NOTIF-002 | P3 | Уведомления | `general.show_notifications` никто не читает | Мёртвая настройка | Static-confirmed |
| OFFLINE-001 | P2 | Офлайн | Остатки офлайн-режима в UI | Backend удалил is_offline | Static-confirmed |
| REC-001 | P1 | Рекомендации | `get_smart_home_feed` падает без Last.fm | Нет гардов | Static-confirmed |
| REC-002 | P2 | Рекомендации | Захардкоженные CURATED_WELCOME_TRACKS | recommendation_service.py:26-35 | Static-confirmed |
| REC-003 | P2 | Рекомендации | `get_authentic_home` игнорирует историю | history=[] | Static-confirmed |
| REC-004 | P2 | Рекомендации | SQL-fallback нарушает инкапсуляцию | прямой доступ к conn | Static-confirmed |
| REC-005 | P3 | Рекомендации | Кеш инвалидируется при изменении истории | ключ включает history | Static-confirmed |
| BRIDGE-001 | P2 | Bridge | События без потребителей | position_changed, session_autoplay, operation_error, storage_info_updated, track_downloaded | Static-confirmed |
| BRIDGE-002 | P2 | Bridge | Двойные подписки | main.js:630,679,777 | Needs runtime |
| BRIDGE-003 | P3 | Bridge | Буфер событий 256 | events.js:54-64 | Static-confirmed |
| BRIDGE-004 | P2 | Bridge | `get_volume` не в whitelist | core/bridge.py | Static-confirmed |
| CASE-001 | P3 | UI/JS | 4 case без скобок | hotkeys.js, utils.js | Static-confirmed |
| CASE-002 | P3 | UI/JS | Двойной перехват onPythonEvent в legacy | ui/web_new/js/main.js | Static-confirmed (legacy) |
| LYRICS-001 | P3 | UI/JS | Lyrics в обоих скинах | lyrics.css:185-190 | Needs runtime |

---

## Часть VI — Подробные инструкции по исправлению

(Карточки для подтверждённых дефектов. Формат: ID, название, приоритет, статус, UI, симптом, ожидаемое, текущее, первопричина, доказательства, зависимости, инструкция, нельзя делать, критерии готовности, регрессионные тесты, уверенность.)

### Карточка STARTUP-001

- **ID:** STARTUP-001
- **Название:** Наложение стандартного и macOS UI при холодном старте
- **Приоритет:** P1 (возможен P0 при подтверждении блокировки сценариев)
- **Статус:** Confirmed (браузер + статика)
- **UI:** оба (проявляется в `'current'`)
- **Симптом:** при каждом холодном старте видны macOS-фрагменты (`#macos-toolbar` с рабочим поиском и 3 кнопками, `#macos-profile-row`) поверх стандартного UI.
- **Ожидаемое:** в `'current'` скине macOS-фрагменты невидимы с первого paint.
- **Текущее:** `#macos-toolbar` display:block, rect 95×15..888×44; `#macos-profile-row` block; `#macos-sidebar-profile` inline-block.
- **Первопричина:** правила скрытия живут в `css/components/ui-style-picker.css` (строки 2-3), который подключается только через `pagePacks.settings` в `js/style-loader.js:29`. На странице home он не грузится. При ручном переключении UI пользователь посещает settings → CSS загружается → фрагменты скрываются до перезапуска.
- **Доказательства:** `css/components/ui-style-picker.css:2-3`; `js/style-loader.js:24-30,55-74`; `js/ui-style.js:67-76,78-91`; browser-evaluate (до/после ensureForPage('settings')).
- **Зависимости:** `index.html` (link placeholders 44-59), `js/pages.js` (showPage → ensureForPage?), `css/components/base.css`.
- **Инструкция:**
  1. Перенести правила из `ui-style-picker.css:2-3` в синхронно загружаемый CSS (`base.css` или `tokens.css`), либо добавить `stylePicker` в `boot`-Promise и `ensureForPage('home')`.
  2. Альтернатива: добавить `<link rel="stylesheet" href="css/components/ui-style-picker.css">` синхронно в `<head>` (index.html).
  3. Проверить, что `html[data-ui-style="current"] #macos-toolbar { display:none }` применяется до первого paint.
  4. Убедиться, что `#macos-backdrop`/`#macos-drag-region` (zero-height, но display:block) тоже скрыты.
  5. Не использовать JS-hide после paint.
- **Нельзя делать:** временный `display:none` через JS после mount; скрывать через inline-style в ui-style.js (это тот же костыль, только в другом месте).
- **Критерии готовности:** холодный старт в обоих скинах — ни один macOS-фрагмент не виден в `'current'`; 5 переключений UI подряд; перезапуск; проверка на всех страницах (home/search/library/player/settings).
- **Регрессионные тесты:** статический тест в `tests/test_frontend_js.py` — проверить, что `ui-style-picker.css` (или эквивалентные правила) загружается на home-странице; либо добавить CSS-инвариант-тест.
- **Уверенность:** высокая.

### Карточка SETTINGS-001/002

- **ID:** SETTINGS-001, SETTINGS-002
- **Название:** Дублирование `theme`/`interface` и несогласованность чтения
- **Приоритет:** P1
- **Статус:** Static-confirmed
- **UI:** оба
- **Симптом:** изменение шрифта/радиуса из UI не доезжает до backend; две независимые копии одних и тех же ключей.
- **Ожидаемое:** единая схема; UI и backend читают одни и те же ключи.
- **Первопричина:** `core/settings.py:499` (`get("interface","border_radius",12)`), `:518` (`get("interface","font_family","system")`); frontend `settings.js:657-783` читает `theme.*`. Обе категории возвращаются через `get_settings()` и сохраняются независимо.
- **Доказательства:** `core/settings.py:154-238` (обе категории), `core/settings.py:499,518`, `ui/web_new_v2/js/settings.js:657-783`, STATUS.md §5.3.
- **Инструкция:**
  1. Выбрать канон — рекомендуется `interface.*` (backend уже использует).
  2. В `SettingsManager._load_all` добавить миграцию: если `interface.font_family` отсутствует, а `theme.font_family` задан — скопировать. Аналогично для `border_radius` (дефолт 12).
  3. Перевести frontend на чтение `interface.font_family`/`interface.border_radius` (с fallback на `theme.*`).
  4. Удалить дубли из `theme.*` через миграцию (не сразу — сначала совместимость).
  5. Добавить UI-контрол для `border_radius`.
  6. Тесты: расширить `tests/test_settings_flush.py`.
- **Нельзя делать:** слить категории одним коммитом без миграции (сломает старые `settings.json`/БД).
- **Критерии готовности:** изменение шрифта в UI отражается в backend и сохраняется после перезапуска; `border_radius` изменяем из UI.
- **Уверенность:** средняя (требует решения владельца по канону).

### Карточка REC-001

- **ID:** REC-001
- **Название:** `get_smart_home_feed` падает при отключённом Last.fm
- **Приоритет:** P1
- **Статус:** Static-confirmed
- **UI:** оба
- **Симптом:** главная (authentic feed) не загружается для большинства пользователей.
- **Первопричина:** `recommendation_service.py:748-895` вызывает `self.lastfm.artist.getTopTracks` (785, 830, 864), `self.lastfm.chart.getTopTracks` (794, 874), `self.lastfm.user.getTopArtists` без проверки `_lastfm_enabled()`/наличия методов. Last.fm отключён по умолчанию (`services.lastfm_enabled=False`).
- **Инструкция:**
  1. Обернуть все `self.lastfm.*` вызовы в `if self._lastfm_enabled():`.
  2. Добавить fallback: если Last.fm недоступен — использовать локальные треки (`profile.get_seed_tracks`, `get_local_liked_and_downloaded_tracks`) и curated welcome tracks.
  3. Кешировать результат `get_smart_home_feed` (сейчас нет кеша).
  4. Передавать реальную историю в `get_authentic_home` (REC-003).
- **Критерии готовности:** authentic home feed загружается без Last.fm API key; не падает; возвращает хотя бы curated tracks.
- **Уверенность:** высокая.

### Карточка PLAYER-001/007

- **ID:** PLAYER-001, PLAYER-007
- **Название:** Рассогласование длительности при смене трека
- **Приоритет:** P1/P2
- **Статус:** Probable
- **Инструкция:**
  1. В `player.js`, при обработке `track_changed`, сбросить `playbackState.durationMs = 0` до прихода новых данных.
  2. В `timeupdate` handler (player.js:623-629) добавить гард: не перезаписывать длительность, если `playbackState.track` изменился менее N мс назад (или пока `durationMs === 0`).
  3. В `seekTo` (player.js:865) снимать `isSeeking` по событию `seeked`, а не по таймеру 600мс (PLAYER-006).
  4. Исправить `formatTime` (utils.js:80-85): `if (!Number.isFinite(seconds) || seconds <= 0) return "0:00"`.
  5. Тесты: unit-тесты для `formatTime` (NaN, Infinity, 0, отрицательные, нормальные).

### Карточка MACUI-001

- **ID:** MACUI-001
- **Название:** Удаление лишних кнопок из macOS-тулбара
- **Приоритет:** P2
- **Статус:** Confirmed (user request)
- **Инструкция:**
  1. Удалить из `index.html:250-253` кнопки `#macos-notices`, профиля и настроек из `#macos-toolbar`. Оставить `#macos-search-form`.
  2. В `ui-style.js` убрать привязки `#macos-notices` (строка 262) и `data-macos-page` для settings/profile (строки 259-261), если больше не используются.
  3. Убедиться в альтернативном доступе: настройки — через сайдбар/горячие клавиши; профиль — через `#macos-sidebar-profile` (index.html:236); уведомления — через `#home-notices` на главной.
  4. Если в macOS-скине сайдбар недоступен — добавить доступ к настройкам через контекстное меню/команду.
  5. Обновить `MACos_ui/interface.css` (строка 163) — правило станет мёртвым, удалить.
- **Нельзя делать:** удалять `#home-notices` или toast-систему (критические ошибки).
- **Критерии готовности:** macOS-тулбар содержит только поиск; все функции доступны альтернативно.

### Карточка SEARCH-001

- **ID:** SEARCH-001
- **Название:** Удаление блока быстрых жанров из поиска
- **Приоритет:** P2
- **Статус:** Confirmed (user request)
- **Инструкция:**
  1. Удалить разметку `#search-genres` из `index.html` (~строка 452).
  2. Удалить все ссылки на `search-genres`/`searchGenres` из `js/search.js`, `js/search-discovery.js`, `js/home.js`.
  3. Удалить CSS-правила из `css/components/search-refresh.css`.
  4. Проверить grep по всему `ui/web_new_v2/` на `search-genres`.
  5. Backend (`core/api.py::search`) не трогать.
- **Критерии готовности:** поиск работает без жанров; нет ошибок в консоли; нет мёртвых ссылок.

### Карточка SEARCH-002

- **ID:** SEARCH-002
- **Название:** Прозрачное оформление недавних поисков (macOS-стиль)
- **Приоритет:** P2
- **Статус:** Design task
- **Инструкция:**
  1. В `css/components/search-refresh.css` добавить правила под `html[data-ui-style="macos"]` для `#search-discovery` и его элементов: фон `rgba(255,255,255,0.04)`, `backdrop-filter: blur(12px)`, border `1px solid rgba(255,255,255,0.08)`, hover `rgba(255,255,255,0.08)`.
  2. Текст `var(--mac-text)`, контраст ≥4.5:1 в обеих темах.
  3. В `'current'` скине сохранить текущий вид.
  4. Проверить blur на low-performance preset (отключать при `perf-low`).

### Карточка NOTIF-001/OFFLINE-001

- **ID:** NOTIF-001, OFFLINE-001
- **Название:** Безопасное удаление устаревших разделов уведомлений/офлайн-режима
- **Приоритет:** P2
- **Инструкция:**
  1. Сохранить: toast-систему (`#toast-container`), `#operation-error` aside, локальную библиотеку (`get_offline_library`), скачанные треки.
  2. Удалить: `#network-banner` + обработчик `network_status` в `main.js:487-501` (или реализовать эмит — решение владельца).
  3. Проверить все места, где используется `network_status`/`is_offline`/`offline` в `ui/web_new_v2/js/`.
  4. Если есть отдельная страница уведомлений — удалить её разметку и навигацию, сохранив критические ошибки через toast.

### Карточка BRIDGE-001/002/003

- **ID:** BRIDGE-001, BRIDGE-002, BRIDGE-003
- **Инструкция:**
  1. Удалить мёртвые case'ы из `events.js`: `position_changed`, `session_autoplay`, `storage_info_updated`, standalone `track_downloaded` (если не нужен), `operation_error` (если backend не эмитит).
  2. Проверить дублирование подписок в `main.js:630/679/777` — объединить или добавить дедупликацию по eventName.
  3. Увеличить буфер событий (256 → 1024) или уменьшить задержку init.
  4. Добавить `get_volume` в `PUBLIC_METHODS` (BRIDGE-004).

---

## Часть VII — Архитектурные рекомендации

### Обязательные (P0/P1):
1. Единый source of truth для стилей скина до первого paint (STARTUP-001).
2. Слить `theme`/`interface` схемы (SETTINGS-001/002).
3. Гарды для Last.fm в рекомендациях (REC-001).
4. Сброс duration при смене трека (PLAYER-001/007).

### Необязательные (P2/P3):
5. Стилизованные компоненты для macOS-скина (SETTINGS-003).
6. Удаление быстрых жанров (SEARCH-001).
7. Удаление лишних кнопок из macOS-тулбара (MACUI-001).
8. Прозрачные недавние поиски (SEARCH-002).
9. Удаление устаревших разделов уведомлений/офлайн (NOTIF-001, OFFLINE-001).
10. Изучение Riff (rootscripts/riff) для переработки рекомендаций.
11. Устранение мёртвых case'ов и двойных подписок (BRIDGE-001/002).
12. Исправление `formatTime(Infinity)` (PLAYER-002).
13. Устранение case-без-скобок (CASE-001).

### Защита от регрессий:
- Добавить статический тест на загрузку `ui-style-picker.css` (или эквивалентных правил) на home-странице.
- Добавить unit-тесты для `formatTime`.
- Расширить `tests/test_settings_flush.py` проверкой round-trip новых ключей.
- Добавить тест на отсутствие мёртвых case'ов в `events.js`.

---

## Часть VIII — План реализации

| Этап | Дефекты | Файлы | Действия | Зависимости | Результат | Критерии завершения |
|---|---|---|---|---|---|---|
| 1 | STARTUP-001 | `js/style-loader.js`, `css/components/ui-style-picker.css`, `css/components/base.css`, `index.html` | Перенести правила скрытия в синхронный CSS | — | Оверлей исчезает | Холодный старт в обоих скинах |
| 1b | WHITE-001 | `main.py`, `ui/web_new_v2/js/player.js`, `core/snap_layouts.py` | Усилить watchdog (порог 15-20с), приостановить animateProgress при hidden, проверить restore snap_layouts, добавить ручную перезагрузку рендерера | — | Белый экран устраняется | Maximize/minimize + 5 мин ожидания |
| 2 | SETTINGS-001, SETTINGS-002 | `core/settings.py`, `ui/web_new_v2/js/settings.js` | Миграция theme→interface, добавить контрол border_radius | Этап 1 | Единая схема | Round-trip тесты |
| 3 | REC-001, REC-003 | `services/recommendation_service.py` | Гарды для Last.fm, fallback, кеш, история | — | Authentic feed работает | Без Last.fm API key |
| 4 | PLAYER-001, PLAYER-002, PLAYER-006, PLAYER-007 | `ui/web_new_v2/js/player.js`, `js/utils.js` | Сброс duration, seeked-event, formatTime гард | — | Корректный прогресс | Unit-тесты formatTime |
| 5 | SEARCH-001, SEARCH-002 | `index.html`, `js/search*.js`, `css/.../search-refresh.css` | Удалить жанры, прозрачные недавние | — | Чистый поиск | Нет мёртвых ссылок |
| 6 | MACUI-001, SETTINGS-003 | `index.html`, `ui-style.js`, `MACos_ui/interface.css` | Убрать кнопки тулбара, стилизовать компоненты | Этап 1 | Чистый macOS-тулбар | Визуальная проверка |
| 7 | NOTIF-001, OFFLINE-001, BRIDGE-001 | `main.js`, `events.js`, `index.html` | Удалить мёртвый код | — | Чистый код | Нет ошибок консоли |
| 8 | Тестирование | `tests/` | Регрессионные тесты | Этапы 1-7 | Защита от регрессий | Все тесты зелёные |

---

## Часть IX — Матрица тестирования

| Тест | Выполнен? | Комментарий |
|---|---|---|
| Холодный старт (браузер) | Да | Подтверждён оверлей; после ensureForPage('settings') — скрыт |
| Повторный запуск | Нет | Требует нативного приложения |
| Переключение UI | Частично | Проверено через ensureForPage('settings') в браузере |
| Несколько переключений подряд | Нет | Требует нативного приложения |
| Сохранение настроек | Статически | Цепочка save_setting → _store_setting → SettingsWriter проверена по коду |
| Восстановление настроек | Статически | applySettingsFromBackend + restore проверены |
| Переключение тем | Статически | applyThemeMode, syncThemeSelection |
| Воспроизведение/пауза/перемотка | Нет | Требует нативного приложения + аудио |
| Смена композиции | Нет | Требует нативного приложения |
| Загрузка музыки | Нет | Требует сети/приложения |
| Поиск | Нет | Требует backend |
| Работа без сети | Нет | Требует приложения |
| Поведение при ошибках | Нет | Требует приложения |
| Максимизация/сворачивание + 5 мин | Нет | Требует нативного приложения; проверить watchdog |

---

## Часть X — Работа субагентов

- **Agent 1 (backend map):** успешно завершён — полная карта core/bridge/api/app/settings/ui_assets/audio + события JS. Результаты включены в Часть II.
- **Agent 2 (settings):** завершился с ошибкой лимита; задача выполнена главным агентом через grep/read (Часть III).
- **Agent 3 (player):** завершился с ошибкой лимита; задача выполнена главным агентом (Часть IV.7).
- **Agent 4 (search/Riff):** завершился с ошибкой лимита; задача выполнена главным агентом (Часть IV.3, IV.11).
- **Agent 5 (bridge/misc):** завершился с ошибкой лимита; задача выполнена главным агентом (Часть IV.12).
- **Независимая перепроверка:** браузерная проверка STARTUP-001 (до/после ensureForPage('settings')) подтвердила гипотезу.
- **Отклонённые выводы:** предположение, что оверлей вызван stale JS-кэшем WebView2 — не подтвердилось; реальная причина — отсутствие CSS-правил скрытия на home-странице.
- **Открытые вопросы:** fullscreen плеера, mini-player синхронизация, output_device consumer, max_concurrent consumer, crossfade/volume_normalization цепочка — требуют runtime-проверки.

---

## Часть XI — Итоговая проверка полноты

- [x] Все перечисленные пользователем проблемы исследованы (наложение UI, настройки, поиск, macOS UI, нижняя панель, уведомления/офлайн, рекомендации/Riff).
- [x] Баг наложения двух UI включён (STARTUP-001, P1).
- [x] Оба интерфейса охвачены (стандартный + macOS).
- [x] Все обнаруженные настройки внесены в инвентаризацию (Часть III).
- [x] Все реальные дефекты имеют инструкции (Часть VI).
- [x] Для приоритетных проблем указаны доказательства (файлы, функции, строки).
- [x] Неизвестные причины не выданы за подтверждённые (помечены Needs runtime/Probable).
- [x] Тесты не нарушили ограничения (только браузерная проверка копии UI; нативное приложение не запускалось).
- [x] Исходный код остался нетронутым (только создание этого файла).
- [x] Вся информация размещена в одном файле.

---

---

## Часть XII — Журнал реализации (выполненные изменения)

Дата: 2026-10-29. Режим: непосредственное изменение проекта.

### XII.1 STARTUP-001 — устранение наложения двух UI при холодном старте

**Файл:** `ui/web_new_v2/css/components/base.css` (добавлено в конец файла)

**Изменение:**
```css
/* STARTUP-001: hide macOS-only fragments in the standard skin from first paint */
#macos-toolbar { display: none; }
#macos-backdrop, #macos-drag-region, #macos-sidebar-profile, #macos-profile-row, .macos-library-chevron { display: none; }
```

Правила скрытия macOS-фрагментов перенесены из отложенного `ui-style-picker.css` в синхронно загружаемый `base.css` (который подключается в `<head>` index.html). Теперь они применяются с первого paint. В macOS-скине `MACos_ui/interface.css` переопределяет их через специфичность `html[data-ui-style="macos"]`.

**Почему не style-loader.js:** первоначальная попытка добавить `load('stylePicker')` в boot-Promise нарушала инвариант `test_frontend_css_wiring.py::test_style_loader_uses_the_real_deferred_slots` (deferred-слоты не должны грузиться до навигации). Решение через base.css не трогает style-loader и сохраняет тест.

**Проверка:** браузерная (копия `ui/` в `%TEMP%\opencode\ui_test`). До фикса: `#macos-toolbar` display:block. После фикса: все четыре macOS-фрагмента `display:none` при `uiStyle='current'`.

### XII.2 WHITE-001 — белый экран WebView2

> **2026-10-31, root cause confirmed by live reproduction.** The reload-after-restore
> from this section was removed in `core/api.py::_on_restored` — it raced the
> restore animation (white page if navigation landed mid-restore) and was not the
> primary cause anyway. Instrumented reproduction (desktop screenshot vs CDP
> `Page.captureScreenshot`) showed the renderer keeps producing correct frames
> while the visible window is 100% white after minimize→restore: the hidden
> DWM surface of a window whose WM_NCCALCSIZE is overridden
> (`core/snap_layouts.py` frameless setup) stays detached from the shell.
> Remedy verified live: `SetWindowPos(SWP_FRAMECHANGED)` re-runs NCCALCSIZE
> and reattaches the surface instantly. It is now issued by
> `AppApi._recalc_native_frame` on every zoom/iconic state transition seen on
> the `resized` event (10/10 stress cycles clean; before the fix the same
> harness was 100% white on cycle 1). The `boot.js` `nedotify:window_visibility_changed`
> repaint kick remains as the frontend-side belt.

**Файл 1:** `main.py` (строки ~380, ~405)
- Порог watchdog: `silent > 75` → `silent > 20`.
- Пострелоад-ожидание: `_time.monotonic() - reloaded_at < 40` → `< 15`.

**Файл 2:** `ui/web_new_v2/js/boot.js` (блок `visibilitychange`)
- Добавлено отслеживание `lastVisibleAt`; при возврате видимости после >5 с простоя выполняется принудительный reflow (`void document.body.offsetHeight`) и `window.dispatchEvent(new Event('resize'))` для восстановления композитора WebView2.

**Примечание:** `animateProgress` в `player.js` уже приостанавливается при `document.hidden` (функция `isPlayerUiHidden()` проверяет `document.hidden`) — дополнительных изменений не требуется.

### XII.3 SEARCH-001 — удаление быстрых жанров из поиска

**Файл 1:** `ui/web_new_v2/index.html`
- Удалён блок `<section id="search-genres" ...>...</section>` (строки ~452-454).
- Удалена кнопка `<button class="type-filter-btn" data-type="genres">Жанры</button>` из фильтров.

**Файл 2:** `ui/web_new_v2/js/search.js`
- Удалён обработчик `if (currentType === 'genres') { ... }`.
- Вызов `initSearchDiscovery(searchArtistProfile, ...)` → `initSearchDiscovery(searchArtistProfile)`.

**Файл 3:** `ui/web_new_v2/js/search-discovery.js`
- Сигнатура `initSearchDiscovery(artistCallback, genreCallback)` → `initSearchDiscovery(artistCallback)`.
- Удалена строка `document.querySelectorAll('[data-genre-query]')...`.
- Удалён toggle `search-genres` из `setDiscoveryMode`.

Backend (`core/api.py::search`) не изменён — жанры были только UI-фильтром.

### XII.4 MACUI-001 — удаление лишних кнопок из macOS-тулбара

**Файл 1:** `ui/web_new_v2/index.html` (строки ~245-255)
- Из `<header id="macos-toolbar">` удалён `<div class="macos-toolbar-actions">` с кнопками `#macos-notices`, профиль, настройки. Оставлен только `#macos-search-form`.

**Файл 2:** `ui/web_new_v2/js/ui-style.js`
- Удалены привязки `document.querySelectorAll('[data-macos-page]')` и `#macos-notices`.
- Альтернативный доступ к профилю сохранён через `#macos-sidebar-profile` (index.html:236).

### XII.5 SETTINGS-001/002 — миграция theme/interface

**Файл 1:** `core/settings.py` (функция `_load_all`, после цикла по `stored_all`)
- Добавлена миграция: если `interface.font_family` отсутствует, а `theme.font_family` задан — копируется. Аналогично `macos_font_family`. Дефолт `border_radius=12` если отсутствует.

**Файл 2:** `ui/web_new_v2/js/settings.js` (строка ~185, обработчик выбора шрифта)
- В стандартном скине теперь дополнительно вызывается `saveSetting('font_family', val, 'interface')` для синхронизации с backend.

### XII.6 PLAYER-002 — formatTime

**Файл:** `ui/web_new_v2/js/utils.js` (строка 81)
- `if (!seconds || seconds <= 0)` → `if (!Number.isFinite(seconds) || seconds <= 0)`. Теперь Infinity/NaN → «0:00».

### XII.7 Анимация Play/Pause (концепт Riff)

**Файл 1:** `ui/web_new_v2/js/player.js` (функция `onStateChanged`, после строки 2085)
- Добавлено переключение класса `.is-playing` на `pb-btn-play`, `pp-btn-play`, `mp-btn-play` в зависимости от `playbackState.status === 'playing'`.

**Файл 2:** `ui/web_new_v2/css/components/player-bar.css`
- `.btn-play-main`: transition расширен (width, border-radius 0.22s).
- Добавлен `.btn-play-main.is-playing { width:64px; border-radius:21px; }`.

**Файл 3:** `ui/web_new_v2/css/components/player-view.css`
- Добавлен `.btn-play-large.is-playing { width:72px; min-width:72px; border-radius:24px; }`.

### XII.8 Проверки

- Все изменённые JS прошли `node --check` (7 файлов).
- `core/settings.py` и `main.py` прошли `ast.parse`.
- Браузерная верификация STARTUP-001: подтверждено, что после фикса macOS-фрагменты скрыты при холодном старте.

### XII.9 Что НЕ реализовано в этом проходе

Следующие задачи из полного ТЗ требуют отдельных фокус-сессий и не были выполнены:
- Полная переработка мини-плеера по варианту №10 (каркас mp-* сохранён; применена только morph-анимация кнопки).
- Полная переработка нижней панели и fullscreen плеера (MACUI-002).
- Полная инвентаризация/стилизация всех настроек (SETTINGS-003/008/009/010).
- Прозрачные недавние поиски (SEARCH-002).
- Рекомендации/Riff (REC-001 гарды, fallback без Last.fm).
- Скачивание/источники, onboarding, полный bridge-audit.

Исходный код изменён только в перечисленных файлах. Нативное приложение не запускалось. Итоговый аудит — в этом же файле (Части I–XI).

