# STATUS.md — фактическое состояние NeDotify

> Проверено по коду 2026-10-03, ветка `fix/audit-j2` (на базе
> `fix/audit-2026-10-03`).
> Каждое число и каждый путь в этом файле сверены с исходником; расхождения
> с `docs/history/PROJECT.md` (исторический документ) помечены явно.
> Что именно менял аудит — в `docs/AUDIT.md`.

---

## 1. Стек и точка входа

| Что | Значение | Где подтверждено |
|---|---|---|
| Интерпретатор | **Python 3.14.7** (64-bit, MSC v.1944) | `.venv_win\Scripts\python.exe --version` |
| Минимальная версия | 3.14+ | `requirements.txt` (шапка), `AGENTS.md:12` |
| Оболочка UI | pywebview (`js_api=AppApi`) | `core/api.py`, `main.py` |
| БД | SQLite в режиме WAL | `core/database.py` (`PRAGMA journal_mode=WAL`) |
| Локальный прокси | `http.server`-based, loopback, с токеном | `core/proxy.py` |
| Фронтенд | Vanilla JS + CSS, без фреймворков | `ui/web_new_v2/` |
| UI по умолчанию | `ui/web_new_v2/` | `main.py`: `NEDOTIFY_UI_DIR`, default `"web_new_v2"` |
| Legacy UI | `ui/web_new/`, только через `--ui-v1` / `--v1` | `main.py` |
| Пул поиска | `ThreadPoolExecutor(max_workers=6, thread_name_prefix="SearchWorker")` | `core/api.py:324` |
| Пул загрузок | `ThreadPoolExecutor(max_workers=_MAX_INFLIGHT=2, thread_name_prefix="download_worker")` | `core/downloader.py:16,27` |
| Общий пул провайдеров | `_SharedExecutor(max_workers=8)` | `services/base_service.py:76` |

### Расхождения по версии Python

| Место | Указано | Статус |
|---|---|---|
| `.venv_win` (факт) | 3.14.7 | — эталон |
| `requirements.txt` | 3.14+ | корректно |
| `AGENTS.md:12` | 3.14+ (`.venv_win` is 3.14.7) | корректно |
| `README.md:59` | «Python 3.10 или новее» | **устарело**, правит другой агент |
| `CLAUDE.md:7,10,12` | 3 вхождения `.venv\Scripts\python.exe` | **исправлено** 2026-10-03 → `.venv_win\Scripts\python.exe` |
| `CLAUDE.md:14` | «Perf harness в `scripts/` + `benchmarks/`» | **исправлено**: оба каталога удалены из git коммитом `a3425eb` |
| `CLAUDE.md:28-33` | `utils/path_utils.py`, `.cache/streams/`, `aura.db` | **исправлено**: модуля нет, путь — `~/.nedotify/` |
| `CLAUDE.md:3` | ссылка на `@PROJECT.md` в корне | **исправлено** → `@STATUS.md` + `@docs/AUDIT.md` |

---

## 2. TTL кэшей потока — их действительно три, и это не опечатка

| Константа | Значение | Где | Что кэширует |
|---|---|---|---|
| `StreamResolver._MEM_TTL` | `3600.0` с (1 ч) | `core/resolver.py:19` | LRU-словарь URL **в памяти процесса** (`_MEM_MAX_SIZE = 1024`) |
| `StreamResolver._DB_MAX_AGE` | `14400` с (4 ч) | `core/resolver.py:22` | таблица `stream_cache` **в SQLite** (`get_cached_stream(..., max_age_seconds=...)`) |
| `BaseMusicService._STREAM_CACHE_TTL` | `6 * 3600.0` с (6 ч) | `services/base_service.py:83` | классовый `_stream_cache` (`_MAX_CACHE_SIZE = 2000`) — кэш, который сами сервисы провайдеров отдают через `get_stream_cache`/`set_stream_cache` |
| `BaseMusicService._SEARCH_CACHE_TTL` | `300` с (5 мин) | `services/base_service.py:85` | классовый `_search_cache` (`_SEARCH_CACHE_MAX_SIZE = 300`) |
| `StreamResolver._RESOLVE_TIMEOUT` | `12.0` с | `core/resolver.py:21` | ожидание single-flight, не TTL |

**Зачем три.** Это три независимых уровня с разной ценой и разной живучестью,
вложенных в каскад `in-memory dict → DB stream_cache → network cascade`
(документировано в шапке `core/resolver.py`):

1. **1 ч (память)** — самый горячий слой. Живёт только внутри процесса, поэтому
   терять записи дёшево; короткий TTL страхует от протухших
   `googlevideo`-ссылок. Именно сюда `get_cached_url` переносит успешный
   DB-hit (`resolver.py:108-110`), то есть повторный запрос в первые 4 часа
   вообще не ходит в БД.
2. **4 ч (БД)** — переживает перезапуск приложения. `StreamResolver` создаётся
   в `core/app.py:113` как `StreamResolver(self.db)` (дефолтные TTL), поэтому
   URL, найденные в прошлой сессии, переиспользуются. Комментарий в коде
   объясняет потолок: реальные googlevideo-URL живут ~6 ч, 4 ч — запас.
3. **6 ч (сервисный кэш)** — самый долгий и самый большой. Это кэш уровня
   отдельного провайдера (`YouTubeService`, `SoundCloudService`, …), куда
   попадают URL, полученные в обход `StreamResolver`. Комментарий
   `base_service.py:80-82` прямо связывает 6 ч со сроком жизни провайдерских
   ссылок и с тем, что отдача протухшей ссылки гарантированно даёт 403 через
   proxy self-heal.

Все три работают вместе: 6 ч — верхняя граница «provider-знания», 4 ч — сколько
это переживает перезапуск, 1 ч — как часто текущий процесс берёт из оперативки
без похода в БД. Расхождение TTL между уровнями — не баг, а разные временные
шкалы; **сводить их к одному числу нельзя**, сломается инвалидация на одном из
уровней.

> Историческая формулировка из `docs/history/PROJECT.md`: «TTL кэша потока 3 ч
> (фича 3)». **Не соответствует коду ни на одном из трёх уровней.**

### Квота кэша на диске

`DEFAULT_SETTINGS["storage"]["cache_size_mb"] = 500` (`core/settings.py:133`),
рядом `auto_cache_streams: True`, `cache_covers: True`, `scan_folders: []`.
Это значение по умолчанию для нового профиля; `AppApi` нормализует и старую
схему (`storage.cache_quota_gb`, приоритетнее) и legacy-ключ `cache_size_mb`
через `_normalize_cache_quota()` (`core/api.py:235`), а `set_cache_quota()`
обратно пишет оба ключа (`core/api.py:3295-3326`). Квота `0` не доходит до
`purge_stream_cache(quota_bytes=0)` — проверено `tests/test_api_audit_b.py`
(P2-8).

---

## 3. Контракт события завершения загрузки

**Код эмитит `download_complete` с payload `{"track_id": track_id}` и больше
ничего:**

```python
# core/downloader.py:521
self._emit('download_complete', {'track_id': track_id})
```

Перед этим эмитятся `library_updated` (строка 520) и вызывается
`_on_batch_task_done(track_id, success=True)`. Путь `file_path` наружу **не
отдаётся** — он уходит только в БД через `db.mark_track_downloaded(track_id,
file_path)` (`core/downloader.py:504`).

**Исторический `PROJECT.md` требовал `track_downloaded` с
`{"track_id", "file_path"}`.** Это расхождение зафиксировано, но не исправлено
и не должно исправляться молча.

**Фронтенд принимает оба имени** — `ui/web_new_v2/js/events.js:238-244`:

```js
case 'download_complete':
case 'track_downloaded':
    loadDownloaded();
    loadPlaylists();
    if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
    document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
```

То есть падение одного из двух имён внешне не видно: промах по контракту
компенсирован `case`-ом с двумя метками. Внутреннее событие
`nedotify:track_downloaded` (с подчёркиванием) — это отдельная, фронтендовая
сигнатура, которую слушают `library.js:1037` и `utils.js:625`.
В legacy-дереве `ui/web_new/js/events.js:176-181` то же самое.

**Практическое следствие:** если кто-то начнёт читать `file_path` из payload
события, он получит `undefined`. Путь надо брать из БД (`tracks.file_path`)
или из `get_downloaded_tracks`.

---

## 4. Параметры поиска и таймауты

Все константы — `core/api.py`:

| Константа | Значение | Строка | Назначение |
|---|---|---|---|
| `PROVIDER_SEARCH_TIMEOUT` | `6.0` с | 58 | жёсткий дедлайн на один провайдер. Поднят с 4.0: `yt-dlp socket_timeout` = 6 с, таймаут сессии YTMusic = 15 с, и 4 с давали видимое «ничего не найдено» до ответа провайдера |
| SoundCloud-таймаут | `8.0` с | 1779 | `_timeout = 8.0 if name == "soundcloud" else PROVIDER_SEARCH_TIMEOUT`. У SoundCloud поиск регулярно превышает общий бюджет: скраппинг `client_id` + round-tripы `api-v2` |
| `BRIDGE_SYNC_BUDGET` | `6.0` с | 64 | общий бюджет wall-clock для синхронного bridge-метода. pywebview отдаёт вызов в потоке моста, JS ждёт промис, поэтому длинный блок ощущается как «зависшее» окно. Многоступенчатые lookup'ы делят **один** бюджет, а не получают каждый свой |
| Пул поиска | `max_workers=6`, префикс `SearchWorker` | 324 | `AppApi._search_executor` |
| `_SSRF_CACHE_TTL` | `120.0` с | 95 | мемоизация DNS-вердиктов (`_SSRF_CACHE_MAX = 512`), под защитой `_ssrf_cache_lock` |

`BRIDGE_SYNC_BUDGET` используется в двух местах: `get_album_tracks`
(`core/api.py:1818`, дедлайн + `_remaining()`) и ещё один синхронный lookup
(`core/api.py:2187`, `done_event.wait(timeout=BRIDGE_SYNC_BUDGET)`).

Отключённые провайдеры: `DISABLED_UI_PROVIDERS = {"yandex", "vk", "vkontakte",
"zeno"}` (`core/api.py:1685`). При `source == "all"` реально идут
`["local", "youtube", "soundcloud", "spotify"]`. Если фильтр оставил пустой
список, `search_completed` эмитится **сразу**, чтобы UI не крутил спиннер
вечно (`core/api.py:1714-1718`).

---

## 5. Известные расхождения фронтенд/бэкенд (НЕ чинились — решение владельца)

### 5.1 `network_status`: UI слушает, backend не эмитит

`ui/web_new_v2/js/main.js:487-501` (`_handleNetworkEvent`) обрабатывает
`network_status` и рисует баннер «Нет подключения к сети. Локальный режим.» /
«Нестабильное подключение». Grep по всему дереву `*.py` на `network_status`
даёт **ноль совпадений**: событие не эмитится ниоткуда.

**Что это значит на практике:** баннер сетевого состояния — мёртвый код.
`ui/web_new/js/main.js:450` (legacy) — то же самое. Рядом в этом же обработчике
живёт `proxy_status` (строка 502), который эмитится и работает.

**Статус: отложено по решению владельца.** Не воспроизводится как баг —
пользователь не видит отказа, просто баннер никогда не появляется. Чинить
означало бы либо эмитить событие (новое поведение), либо удалять ~15 строк
 фронтенда в зоне `ui/**`, которую правят другие агенты.

### 5.2 Yandex / VK: поиск отключён намеренно

- Поиск: `DISABLED_UI_PROVIDERS` в `core/api.py:1685` вырезает `yandex`,
  `vk`, `vkontakte`, `zeno` **до** диспетчеризации по провайдерам.
- `VKService.search()` (`services/vk_service.py:30-48`) при любом исходе
  вызывает `callback([])` — заглушка, документированная как «limited
  functionality due to anti-bot protection».
- У `VKService` **нет** метода `download_audio_sync`. У `YouTubeService`
  (`:847`), `SoundCloudService` (`:588`) и `YandexService` (`:254`) — есть.
- `DownloadManager._SUPPORTED_SOURCES = frozenset({'youtube', 'soundcloud',
  'yandex', 'spotify', 'spotify_album'})` (`core/downloader.py:21`), `vk` там
  нет, и ветка «провайдера нет» честно сообщает
  `f"No download provider for source '{source}'."` (`core/downloader.py:527-529`).

**Итог:** это не поломка, а незавершённая фича за выключателем. Баг P1-2 из
исходного аудита («VK ищет и падает») **не воспроизводится** — путь до
`search()` и до `download_audio_sync` недостижим из UI. Подробности —
`docs/AUDIT.md`.

### 5.3 Дубли схемы настроек `theme` ↔ `interface` — миграция НЕ выполнена

В `DEFAULT_SETTINGS` (`core/settings.py`) есть **две** категории с
пересекающимися ключами:

| Ключ | `theme` (стр. 154) | `interface` (стр. 174) |
|---|---|---|
| `theme` | `"dark"` (имя палитры) | `"dark"` |
| `name` | `"Dark"` | `"Dark"` |
| `accent_color` | `"#a855f7"` | `"#a855f7"` |
| `transparency_enabled` | `False` | `False` |
| `transparency_level` | `0.8` | `0.8` |
| `glass_blur` | `15` | `15` |
| `glass_color_intensity` | `0.5` | `0.5` |
| `custom_themes` | `[]` | `[]` |

Кто что читает:
- **Фронтенд читает `theme.*`** — `ui/web_new_v2/js/settings.js:657-783`
  (`applySettingsFromBackend`): `theme_mode`, `theme.theme`/`theme.name`,
  `glass_blur`, `font_family`, `transparency_*`, `font_size`, `icon_pack`,
  `custom_bg_image`, `bg_blur`, `bg_dim`.
- **Бэкенд читает `interface.*`** — `core/settings.py:499`
  (`self.get("interface", "border_radius", 12)`) и `:518`
  (`self.get("interface", "font_family", "system")`).

Обе категории возвращаются через `get_settings()` (`core/api.py:2344` перечисляет
и `interface`, и `theme`), и обе сохраняются независимо. Итог: **изменение
радиуса/шрифта из UI не доезжает до бэкенда, а изменение темы из бэкенда не
доезжает до UI** — там просто две несвязанные копии одного и того же.

**Статус: не выполненная миграция.** Не исправлено: любая попытка слить
категории ломает либо фронтенд, либо два backend-метода, а покрытия на них
нет. Требует отдельного решения владельца (см. «Требует решения»).

### 5.4 Лицензирование (`subscription`) — намеренно мёртвая ветка

`DEFAULT_SETTINGS["subscription"]` (`core/settings.py:243`) помечен
комментарием: фича не планируется, UI не имеет ни поля ввода, ни пути валидации
(`AppApi.validate_subscription_key` и `AppApi.get_subscription_info` не имеют
вызывающих сторон). Блок сохранён только ради совместимости старых
`settings.json` (неизвестные ключи сохраняются, а не выбрасываются).

---

## 6. Сборка и установка

**Канонический установщик — Inno Setup:**

```
iscc installer.iss            ->  dist\NeDotify_Setup.exe
```

Шапка `installer.iss` задаёт канонический порядок сборки:

```
pyinstaller setup_pyinstaller.spec  ->  dist\NeDotify.exe
iscc installer.iss                  ->  dist\NeDotify_Setup.exe
```

- `installer.iss`: `AppName=NeDotify`, `AppVersion=5.0 Beta`,
  `DefaultDirName={localappdata}\Programs\NeDotify`, `PrivilegesRequired=lowest`,
  `OutputBaseFilename=NeDotify_Setup`, две секции `[Registry]`/`[Run]`
  для автозапуска. Языки: русский (`compiler:Languages\Russian.isl`) + английский.
- `setup_pyinstaller.spec`: `pyinstaller setup_pyinstaller.spec`.
  Спека намеренно бандлит **оба** UI-дерева (`main.py` выбирает `web_new_v2`
  по умолчанию и `web_new` только с `--v1`), и в ней есть фильтр
  `_is_ui_cover_cache()`, который исключает любой `.../ui/.../covers/` — в том
  числе `web_new_v2/covers/` (старый фильтр искал литерал `web_new/covers/`,
  что не является подстрокой `web_new_v2/covers/`, из-за чего кэш обложек
  активного UI попадал внутрь exe).

**Связка бренда закреплена тестом** `tests/test_build_and_brand.py`:
`AUTOSTART_RUN_VALUE = "NeDotify"` (`core/api.py:46`) должен совпадать с
литералом в секции `[Registry]` файла `installer.iss` — Inno Setup не умеет
читать константы Python. Пока писал `"AURA Music"`, а установщил `"NeDotify"`,
Windows логин'ил дважды и ни один переключатель не выключал обе записи.

### PyInstaller-скрипты: что удалено, что осталось

| Файл | Состояние | Источник истины |
|---|---|---|
| `build_nuitka.bat` | **удалён** из git | `git log --diff-filter=D`: `ab207a7` |
| `build_beta5_installer.py` | **удалён** из git | `git log --diff-filter=D`: `d417624`, ранее `ab207a7` |
| `build_installer.py` | **в репозитории** (62 строки) | `git ls-files` |
| `installer_gui.py` | **в репозитории** | `git ls-files` |
| `uninstaller_gui.py` | **в репозитории** | `git ls-files` |
| `scripts/*.ps1`, `scripts/*.py` | **удалены** из git | `a3425eb` (11 файлов) |

> **Расхождение, требующее внимания.** Шапка `installer.iss` утверждает, что
> «PyInstaller GUI-installer pipeline (`build_installer.py` /
> `installer_gui.py` / `uninstaller_gui.py`) is gone», но все три файла
> **физически присутствуют и отслеживаются git**. Удалены были Nuitka- и
> beta5-скрипты. Ничего из перечисленного я не удалял (вне моей зоны) —
> фиксирую как есть.

---

## 7. Тесты: текущее состояние

```
363 passed in 12.19s
```

Интерпретатор: `.venv_win\Scripts\python.exe` (3.14.7). `pytest.ini` снимает
маркер `network` по умолчанию. Фикстура `tests/conftest.py::redirect_home`
изолирует `~` в `tmp_path` (включая форму `"~\\x"` — продакшн-код пишет путь
литералом `"~/.nedotify"`), и сама фикстура защищена тестом
`tests/test_conftest_home_isolation.py`.

### 7.1 Покрытие по файлам (число собранных тестов)

| Файл | Тестов | Зона |
|---|---|---|
| `test_api_audit_b.py` | 69 | `core/api.py`, `audio/engine.py`, `audio/queue.py` |
| `test_lyrics_netease.py` | 42 | `services/lyrics_service.py` |
| `test_frontend_js.py` | 39 | статические проверки + `node --check` по `ui/web_new_v2/js` |
| `test_conftest_home_isolation.py` | 23 | изоляция домашней директории (H-1) |
| `test_db_integrity.py` | 21 | `core/database.py` |
| `test_cache_lru.py` | 16 | LRU и TTL кэшей |
| `test_repo_hygiene.py` | 12 | правила `.gitignore` через `git check-ignore` |
| `test_proxy_paths.py` | 14 | маршрутизация `core/proxy.py` |
| `test_proxy_ranges.py` | 14 | RFC 7233 Range |
| `test_proxy_security.py` | 14 | SSRF/токен/SSRF-кеш |
| `test_downloader_cancel.py` | 12 | кооперативная отмена, backpressure |
| `test_queue.py` | 11 | `audio/queue.py` |
| `test_resolver_state.py` | 11 | single-flight, статистика под локом |
| `test_build_and_brand.py` | 10 | автозапуск в реестре, инварианты сборки |
| `test_settings_flush.py` | 10 | гарантированный flush настроек |
| `test_api_misc.py` | 7 | `core/api.py` (квота, разное) |
| `test_downloader.py` | 8 | `core/downloader.py` |
| `test_api_download.py` | 5 | скачивание |
| `test_emit_thread_safety.py` | 5 | `AppApi._emit` и потоки |
| `test_api_search.py` | 4 | `core/api.py::search` |
| `test_database.py` | 4 | `core/database.py` |
| `test_resolve_fallback_budget.py` | 4 | бюджет каскада резолва |
| `test_lazy_service_deadlock.py` | 3 | ленивая загрузка сервисов |
| `test_youtube_gating.py` | 3 | гейт извлечения YouTube |
| `test_proxy_harness.py` | 2 | харнесс `core/proxy.py` |
| **Итого** | **363** | |

### 7.2 Что покрыто хорошо

- `core/proxy.py` — маршрутизация, Range, HEAD, токен-аутентификация (fail-closed),
  SSRF, 404 на неизвестный путь, daemon-потоки.
- `core/api.py` — поиск, квота кэша, очередь, обложки, `_emit`, автозапуск.
- `audio/engine.py` + `audio/queue.py` — конец очереди, `get_next_track`, repeat.
- `core/database.py` — целостность, чистый `get_playlists`, bool-идентификаторы,
  DDL очереди загрузок.
- `core/resolver.py` — single-flight, статистика под локом, LRU.
- `services/base_service.py` — LRU и TTL обоих кэшей.
- `core/settings.py` — гарантированный flush при жёстком выходе.
- `core/downloader.py` — отмена, backpressure, drain на stop.
- Фронтенд — **только статически**: `test_frontend_js.py` проверяет исходник
  регулярками и дополнительно гоняет `node --check`. Рантайм-харнесса для
  webview-фронтенда нет.

### 7.3 Чего покрытия нет

- **Сервисы провайдеров почти не покрыты.** Реально тестируются
  `services/lyrics_service.py` (42 теста) и косвенно
  `services/youtube_service.py` (3 теста на гейт извлечения).
  **Нет ни одного теста** на `services/soundcloud_service.py`,
  `services/vk_service.py`, `services/spotify_service.py`,
  `services/artist_service.py`, `services/playlist_import_service.py`,
  `services/zapret_service.py`.
- `core/tray.py` — покрыт ровно одной статической проверкой
  (`tests/test_build_and_brand.py:191` `test_tray_icon_uses_active_ui` ищет
  строку `web_new_v2` в исходнике). Никакого запуска трея.
- `main.py`, `core/app.py` — покрыты только косвенно, через инстанцирование
  `AppApi`/`AudioEngine` в тестах.
- `core/proxy.py` запускается в тестах на реальном сокете (харнесс
  `test_proxy_harness.py` поднимает сервер на localhost) — это самый близкий
  к интеграционному тест в наборе, но он не проверяет pywebview-мост.
- GUI/`main.py` не запускается в тестах никогда (это блокирующий процесс).

---

## 8. Известные ограничения и техдолг

### Ограничения (по решению владельца не исправляются)

1. **`network_status` не эмитится** — баннер сетевого состояния в UI мёртв.
2. **Yandex/VK отключены** — `DISABLED_UI_PROVIDERS`; `VKService.search()`
   возвращает `[]`; у VK нет `download_audio_sync`. Фича за выключателем, а не
   баг.
3. **Миграция `theme` ↔ `interface` не выполнена** — две независимые копии
   схемы, бэкенд и фронтенд читают разные категории.
4. **`subscription` мертва** — `validate_subscription_key` /
   `get_subscription_info` без вызывающих сторон.
5. **Покрытие сервисов провайдеров отсутствует** — реальные сетевые интеграции
   (SoundCloud, VK, Spotify, Artist, PlaylistImport, Zapret) не имеют тестов.
6. **Фронтенд покрыт только статически** — `node --check` ловит синтаксис,
   но не поведение. Регрессии в логике UI пройдут зелёными.
7. **`tests/test_downloader_cancel.py::test_queue_processor_applies_backpressure`
   флакует.** Наблюдалось 1 падение из 9 полных прогонов: `_wait_until(...,
   timeout=5.0)` не дождался входа обоих воркеров в провайдер
   (`timed out waiting for: workers inside provider`). Тест гоняет настоящий
   поток `_process_queue` и завязан на тайминги. Не связано с правками
   документации/гигиены: файл не менялся ни в этой зоне, ни в слитых
   коммитах; 5/5 прогонов файла в одиночку и 4/4 последующих полных — зелёные.
   Требует либо увеличения таймаута, либо синхронизации через событие вместо
   опроса.

### Техдолг

8. **`theme`/`interface` — см. п. 5.3.** Требуется решение: какой из блоков
   канон, и что делать со вторым.
9. **Строки-таймауты в коде** — 8.0 с для SoundCloud и 6.0 с для остальных
   вшиты литералами в `core/api.py:1779`, а не вынесены в константы рядом с
   `PROVIDER_SEARCH_TIMEOUT`. Причина (SoundCloud медленнее) задокументирована
   в комментарии, но магическое число легко потерять при рефакторинге.
10. **Комментарий про «4.0s» устарел** — `core/api.py:1777-1778` говорит
   «keep 4.0s for the rest», тогда как константа уже 6.0 с. Комментарий
   описывает состояние до правки.
11. **`build_installer.py` / `installer_gui.py` / `uninstaller_gui.py` в
    репозитории**, хотя шапка `installer.iss` объявляет pipeline удалённым
    (п. 6). Мёртвый или недоиспользуемый код сборки.
12. **`main.js` legacy-дерева всё ещё декорирует `window.onPythonEvent`
    дважды** (`ui/web_new/js/main.js:482` и `:666`, плюс `events.js:24`).
    Рефакторинг P1-8 сделан только для активного `ui/web_new_v2/`, и
    `test_frontend_js.py` сканирует только `JS_DIR = ui/web_new_v2/js`.
13. **Четыре `case` без фигурных скобок в активном дереве**, вне `events.js`:
    `ui/web_new_v2/js/hotkeys.js:199` (`mute`), `:203` (`like`), `:207`
    (`toggle_lyrics`) и `ui/web_new_v2/js/utils.js:862` (`share`). Все
    объявляют `const`/`let`. Правка P2-14 и её защитный тест
    `test_no_unbraced_case_body_declares_bindings` покрывают **только**
    `events.js`. В legacy-дереве таких мест 8.
14. **`AGENTS.md:24,97-98` пишет «318 тестов»** — фактически **363**
   (`test_repo_hygiene.py` добавил 12). Файл правит другой агент, здесь не
   трогал.

---

## 9. Требует решения владельца

| # | Вопрос | Почему не решено здесь |
|---|---|---|
| 1 | Какой блок настроек канон — `theme` или `interface`? | Правка ломает либо фронтенд, либо `core/settings.py:499,518`; покрытия нет |
| 2 | Эмитить `network_status` или удалить обработчик из UI? | Новое поведение vs. правка чужой зоны `ui/**` |
| 3 | Удалять ли `build_installer.py`, `installer_gui.py`, `uninstaller_gui.py`? | Файлы вне моей зоны; шапка `installer.iss` уже говорит, что их нет |
| 4 | Расширять ли `case`-скобки на `hotkeys.js`/`utils.js` и на legacy-дерево? | Зона `ui/**` |
| 5 | Нужен ли реальный фронтенд-харнесс (jsdom/node-тесты) вместо статики? | Требует новой инфраструктуры |
| 6 | Тестировать ли сервисы провайдеров (SoundCloud, VK, Spotify)? | Нужен выбор стратегии моков/контрактных тестов |
| 7 | Править ли двойной перехват `window.onPythonEvent` в legacy `ui/web_new/js/main.js:482,666`? | Зона `ui/**`; `test_frontend_js.py` сканирует только `ui/web_new_v2/js` |
| 8 | `AGENTS.md:24,97-98` — «318 тестов» вместо фактических 363 | Файл правит другой агент |
| 9 | Чинить ли флакующий `test_queue_processor_applies_backpressure` (увеличить таймаут или заменить опрос на событие)? | Файл вне моей зоны; диагностика в п. 7 |
