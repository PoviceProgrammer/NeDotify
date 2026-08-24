# Полный консолидированный отчёт об аудите проекта NeDotify (AURA Music)

## Общая статистика аудита
- **Проверено модулей**: 5 зон (`core/`, `ui/`, `services/`, `audio/`, `utils/`)
- **Всего уникальных проблем**: 29
  - 🔴 **Критические (Critical)**: 5
  - 🟠 **Высокие (High)**: 12
  - 🟡 **Средние (Medium)**: 8
  - 🟢 **Низкие (Low)**: 4

---

## 1. 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ (CRITICAL)

### [BUG-CRIT-01] Удаление новых треков из очереди при выключении режима Shuffle
- **Файл и строка**: [audio/queue.py:L63-L86](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/audio/queue.py#L63-L86), [L113-L120](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/audio/queue.py#L113-L120)
- **Зона**: `audio/`
- **Описание проблемы**: При включении перемешивания (`shuffle = True`) сохраняется снимок порядка `self._original_order = self._tracks.copy()`. Если после этого пользователь добавляет новые треки через интерфейс (`add_track` / `play_next`), они добавляются только в перемешанный список `self._tracks`, а `self._original_order` остается без изменений. При отключении `shuffle = False` список `self._tracks` перезаписывается устаревшей копией `self._original_order.copy()`, из-за чего все треки, добавленные во время перемешивания, навсегда удаляются из очереди.
- **Предполагаемое исправление**: В методах `add_track`, `remove_track`, `move_track` обновлять оба списка (`self._tracks` и `self._original_order`), сохраняя консистентность.

---

### [BUG-CRIT-02] Незакрытый сокет и падение потока в `serve_local_file` при `WinError 10053`
- **Файл и строка**: [core/proxy.py:L224-L227](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/proxy.py#L224-L227)
- **Зона**: `core/`
- **Описание проблемы**: В `serve_local_file` для не-Range запросов вызывается `shutil.copyfileobj(f, self.wfile)` без перехвата сокетных исключений Windows. При закрытии или перемотке трека в WebView2 соединение с сокетом обрывается, и `shutil.copyfileobj` выбрасывает необработанный `ConnectionAbortedError: [WinError 10053]`, аварийно обрывая поток сервера и оставляя файловые дескрипторы незакрытыми.
- **Предполагаемое исправление**: Обернуть `shutil.copyfileobj(f, self.wfile)` в `try...except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError): pass`.

---

### [BUG-CRIT-03] `AttributeError` в `finally` блоке `do_GET` при сбое сетевого подключения прокси
- **Файл и строка**: [core/proxy.py:L587-L589](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/proxy.py#L587-L589)
- **Зона**: `core/`
- **Описание проблемы**: В методе `do_GET` в блоке `finally` вызывается `resp.close()`. Если все попытки подключения к целевому стриму завершились неудачей (таймаут, сбой DNS), переменная `resp` остается равной `None`. Вызов `None.close()` порождает исключение `AttributeError: 'NoneType' object has no attribute 'close'`, маскирующее первопричину сетевой ошибки и вызывающее падение потока.
- **Предполагаемое исправление**: Заменить на `if resp is not None and hasattr(resp, 'close'): resp.close()`.

---

### [BUG-CRIT-04] Опасность Fork-бомбы `ProcessPoolExecutor` на Windows при запуске exe
- **Файл и строка**: [services/lufs_scanner.py:L11](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/lufs_scanner.py#L11), [L42](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/lufs_scanner.py#L42)
- **Зона**: `services/`
- **Описание проблемы**: `LufsScannerService` инициализирует `ProcessPoolExecutor`. В операционной системе Windows дочерние процессы создаются через спавн (`multiprocessing.spawn`). Если приложение скомпилировано через PyInstaller/Nuitka без обязательного `multiprocessing.freeze_support()` в точке входа `main.py`, каждый воркер перезапускает главный процесс приложения, порождая лавинообразное клонирование окон и процессов (Fork Bomb), что полностью подвешивает Windows.
- **Предполагаемое исправление**: Заменить `ProcessPoolExecutor` на `ThreadPoolExecutor` (библиотека `miniaudio`/`numpy` отпускает GIL во время декодирования) или гарантировать вызов `multiprocessing.freeze_support()` в первой строке `main.py`.

---

### [BUG-CRIT-05] Блокировка загрузки локальных обложек `file:///` в WebView2
- **Файл и строка**: [ui/web_new/js/utils.js:L144](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/utils.js#L144)
- **Зона**: `ui/`
- **Описание проблемы**: Функция `getCoverUrl(track)` для локальных файлов возвращает URL вида `file:///C:/Users/...`. В Chromium / WebView2, когда фронтенд работает по схеме `http://127.0.0.1:...`, браузерный движок блокирует загрузку любых `file:///` ресурсов политикой безопасности (`Not allowed to load local resource`). В итоге ни одна обложка локального трека не может быть отображена.
- **Предполагаемое исправление**: Отдавать локальные обложки через встроенный HTTP сервер (`/api/stream` или `/__aura_cover?path=...`), формируя безопасный `http://127.0.0.1:{port}/...` URL.

---

## 2. 🟠 ВЫСОКИЕ ПРОБЛЕМЫ (HIGH)

### [BUG-HIGH-01] SQL синтаксическая ошибка в `get_wrapped_stats("all")`
- **Файл и строка**: [core/database.py:L993-L1006](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/database.py#L993-L1006)
- **Зона**: `core/`
- **Описание проблемы**: При запросе итоговой статистики за все время (`period = "all"`) переменная `where_clause` пуста (`""`). В запросе `query_top_artists` она интерполируется перед `AND t.artist IS NOT NULL...`. В результате генерируется SQL: `FROM history h JOIN tracks t ON h.track_id = t.id AND t.artist IS NOT NULL...` (без ключевого слова `WHERE`), что вызывает немедленное падение с `sqlite3.OperationalError: near "AND": syntax error`.
- **Предполагаемое исправление**: Формировать `where_clause = "WHERE 1=1"` или использовать динамическую сборку условий через список с `' AND '.join(clauses)`.

---

### [BUG-HIGH-02] Маппинг `history.id` вместо `track_id` в рекомендательном движке
- **Файл и строка**: [core/services/recommendation.py:L194-L196](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/services/recommendation.py#L194-L196)
- **Зона**: `core/`
- **Описание проблемы**: В `build_real_engine` список прослушиваний формируется как `history = [str(r.get("id", "")) for r in history_records]`. В словаре `db.get_history()` ключ `r["id"]` — это ID записи в таблице `history`, а не `track_id`. Алгоритм рекомендаций затем проверяет `track["id"] in self.history_set`, сравнивая ID треков каталога с ID истории прослушиваний. В итоге история прослушиваний пользователя полностью игнорируется в рекомендациях.
- **Предполагаемое исправление**: Использовать `r.get("track_id", "")`.

---

### [BUG-HIGH-03] Потеря путей локальных треков при сохранении/восстановлении сессии
- **Файл и строка**: [core/session.py:L10-L34](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/session.py#L10-L34)
- **Зона**: `core/`
- **Описание проблемы**: В `PERSISTED_TRACK_FIELDS` отсутствует `file_path`. При закрытии приложения метод `_slim_track` отсекает пути локальных файлов. После перезапуска в очереди треков `file_path` равен `None`, из-за чего локальные файлы из восстановленной очереди не могут быть воспроизведены без повторного поиска.
- **Предполагаемое исправление**: Сохранять `file_path` для треков с `source == 'local'`.

---

### [BUG-HIGH-04] Тройная рассинхронизация категорий настроек темы (`theme` vs `ui` vs `interface`)
- **Файл и строка**: [core/settings.py:L144-L170](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/settings.py#L144-L170), [core/settings.py:L427-L437](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/settings.py#L427-L437), [ui/web_new/js/settings.js:L613-L620](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/settings.js#L613-L620)
- **Зона**: `core/` + `ui/`
- **Описание проблемы**: `DEFAULT_SETTINGS` определяет тему в `interface.theme` и `interface.accent_color`. Python-геттеры запрашивают `theme.name` и `theme.accent_color`. А JS-код во фронтенде ищет `settings.ui.theme`. Из-за фрагментации категорий дефолтные значения не применяются, а при сбросе настроек интерфейс получает неверную цветовую схему.
- **Предполагаемое исправление**: Унифицировать категорию `theme` во всех модулях.

---

### [BUG-HIGH-05] Остановка цикла анимации визуализатора при переключении страниц
- **Файл и строка**: [ui/web_new/js/visualizer.js:L230-L233](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/visualizer.js#L230-L233), [ui/web_new/js/pages.js:L75-L100](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/pages.js#L75-L100)
- **Зона**: `ui/`
- **Описание проблемы**: При уходе со страницы с канвасом цикл `draw()` в `visualizer.js` останавливается (`animFrameId = null`). Однако функция навигации `showPage()` при возврате на Главную или Плеер не перезапускает цикл отрисовки. Если трек уже играет, визуализатор навсегда замирает в статичном положении.
- **Предполагаемое исправление**: В `showPage()` вызывать `notifyPlaybackState(getIsPlaying())`.

---

### [BUG-HIGH-06] Накопление аудио-узлов и утечка памяти в WebAudio API
- **Файл и строка**: [ui/web_new/js/player.js:L134-L190](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/player.js#L134-L190)
- **Зона**: `ui/`
- **Описание проблемы**: При изменениях параметров эквалайзера и нормализации звука создаются новые связи и фильтры в AudioContext без отсоединения старых графов, что приводит к утечкам памяти в WebView2 и искажениям звука при длительной работе.
- **Предполагаемое исправление**: Защитить цепочку узлов паттерном Singleton и переиспользовать уже подключенные ноды.

---

### [BUG-HIGH-07] Состояние гонки и непотокобезопасность `YoutubeDL` в `youtube_service.py` и `soundcloud_service.py`
- **Файл и строка**: [services/youtube_service.py:L119-L156](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/youtube_service.py#L119-L156), [services/soundcloud_service.py:L142-L155](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/soundcloud_service.py#L142-L155)
- **Зона**: `services/`
- **Описание проблемы**: Единственный экземпляр `YoutubeDL` создается без локов и разделяется между десятком рабочих потоков пула. Внутреннее состояние `yt_dlp` не рассчитано на одновременный вызов `extract_info()` из разных потоков, что приводит к сбоям парсинга куки и таймаутам.
- **Предполагаемое исправление**: Синхронизировать вызовы экстракции через `threading.Lock` или использовать thread-local экземпляры.

---

### [BUG-HIGH-08] Отсутствие `source_id` при импорте URL-треков из плейлистов
- **Файл и строка**: [services/playlist_import_service.py:L246-L254](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/playlist_import_service.py#L246-L254)
- **Зона**: `services/`
- **Описание проблемы**: При импорте M3U файлов с URL треков поле `source_id` не заполняется. Движок воспроизведения не может определить ID трека для кэширования и резолвинга, что делает трек невоспроизводимым.
- **Предполагаемое исправление**: Извлекать ID из URL с помощью регулярных выражений при парсинге.

---

### [BUG-HIGH-09] Длительная блокировка потока при синхронном ожидании каскада сетевых резолверов
- **Файл и строка**: [audio/engine.py:L174-L350](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/audio/engine.py#L174-L350)
- **Зона**: `audio/`
- **Описание проблемы**: Цепочка последовательных сетевых резолверов выполняется с несколькими таймаутами по 3–10 секунд. В случае недоступности сети суммарная задержка составляет до 30.5 секунд, подвешивая поток и вызывая лаги в интерфейсе.
- **Предполагаемое исправление**: Ограничить суммарный дедлайн каскада до 8 секунд.

---

### [BUG-HIGH-10] Некорректный подсчет размера кэша в `CacheManager.get_cache_size`
- **Файл и строка**: [utils/cache_manager.py:L65-L76](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/utils/cache_manager.py#L65-L76)
- **Зона**: `utils/`
- **Описание проблемы**: `get_cache_size()` сканирует всю директорию `~/.nedotify`, включая скачанные постоянные треки `downloads/` и файлы базы данных SQLite. В результате постоянная музыка считается частью кэша и провоцирует постоянную очистку временных стримов.
- **Предполагаемое исправление**: Сканировать только `streams/`, `covers/` и `temp/`.

---

### [BUG-HIGH-11] Поломка извлечения обложек из M4A/AAC файлов
- **Файл и строка**: [utils/tag_parser.py:L171-L177](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/utils/tag_parser.py#L171-L177)
- **Зона**: `utils/`
- **Описание проблемы**: В `_extract_cover` проверяется несуществующий приватный атрибут `_DictProxy__dict`. Из-за этого встроенные обложки для всех файлов `.m4a` и `.aac` никогда не извлекаются.
- **Предполагаемое исправление**: Убрать проверку и использовать `if 'covr' in audio.tags`.

---

### [BUG-HIGH-12] Двойное обновление FTS5 индекса в `update_track_metadata`
- **Файл и строка**: [core/database.py:L870-L883](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/database.py#L870-L883)
- **Зона**: `core/`
- **Описание проблемы**: В SQLite определен триггер `tracks_au`, который автоматически обновляет `tracks_fts`. Метод `update_track_metadata` повторно вызывает ручные SQL-запросы на вставку и удаление из `tracks_fts`, создавая риск дубликатов в полнотекстовом поиске.
- **Предполагаемое исправление**: Убрать ручные вызовы `tracks_fts` из `update_track_metadata`.

---

## 3. 🟡 СРЕДНИЕ ПРОБЛЕМЫ (MEDIUM)

### [BUG-MED-01] Потоковая небезопасность счетчиков батча в `core/downloader.py`
- **Файл и строка**: [core/downloader.py:L36-L55](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/downloader.py#L36-L55), [L170-L186](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/downloader.py#L170-L186)
- **Зона**: `core/`
- **Описание**: `DownloadManager` использует два разных лока (`_queue_lock` и `_lock`) для одних и тех же счетчиков батча, создавая состояние гонки при отмене скачивания.

### [BUG-MED-02] Мутация `sys.modules` в `get_real_thread_class`
- **Файл и строка**: [core/proxy.py:L593-L605](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/proxy.py#L593-L605)
- **Зона**: `core/`
- **Описание**: Функция `get_real_thread_class` временно удаляет `'threading'` из `sys.modules`, что может вызвать `KeyError` в других потоках при импортах.

### [BUG-MED-03] Потенциальный XSS при рендеринге пользовательских плейлистов через `innerHTML`
- **Файл и строка**: [ui/web_new/js/queue.js:L93-L103](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/queue.js#L93-L103)
- **Зона**: `ui/`
- **Описание**: В некоторых элементах очереди и библиотеки атрибуты `title="${track.title}"` не экранируют кавычки, допуская инъекцию при вредоносных тегах в названии файла.

### [BUG-MED-04] Layout Thrashing в анимациях частиц и размытия
- **Файл и строка**: [ui/web_new/js/particles.js:L60-L90](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/particles.js#L60-L90)
- **Зона**: `ui/`
- **Описание**: Считывание `offsetWidth` внутри циклов анимации перед записью стилей вызывает принудительный пересчет геометрии DOM на каждом кадре.

### [BUG-MED-05] Состояние гонки при авто-повторе и быстрой смене треков в `handleStreamError`
- **Файл и строка**: [ui/web_new/js/player.js:L243-L270](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/player.js#L243-L270)
- **Зона**: `ui/`
- **Описание**: Отложенный повтор при ошибке воспроизведения может сработать уже после того, как пользователь включил другой трек, перебив новое воспроизведение.

### [BUG-MED-06] Игнорирование настроек прокси в `spotify_service.py` и `soundcloud_service.py`
- **Файл и строка**: [services/spotify_service.py:L18-L25](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/spotify_service.py#L18-L25)
- **Зона**: `services/`
- **Описание**: Сессии `requests` не считывают параметр `auth.proxy_url`, из-за чего поиск не работает через настроенный пользователем прокси.

### [BUG-MED-07] Игнорирование параметра `file_path` в `lyrics_service.py`
- **Файл и строка**: [services/lyrics_service.py:L122](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/lyrics_service.py#L122)
- **Зона**: `services/`
- **Описание**: Параметр `file_path` принимается, но не проверяется на наличие встроенных тегов `USLT`/`SYLT`, делая лишние сетевые запросы для локальных треков.

### [BUG-MED-08] Рассинхронизация `_current_index` при удалении трека из очереди
- **Файл и строка**: [audio/queue.py:L121-L130](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/audio/queue.py#L121-L130)
- **Зона**: `audio/`
- **Описание**: Удаление последнего играющего трека из очереди оставляет `_current_index = 0` при пустом списке треков.

---

## 4. 🟢 НИЗКИЕ ПРОБЛЕМЫ (LOW)

### [BUG-LOW-01] Искусственная задержка `time.sleep(1)` в цикле скачивания очереди
- **Файл и строка**: [core/downloader.py:L117](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/core/downloader.py#L117)
- **Зона**: `core/`
- **Описание**: Задержка в 1 секунду на каждый трек замедляет наполнение пула потоков при батчевом скачивании.

### [BUG-LOW-02] Отсутствие виртуализации списков для больших библиотек (>1000 треков)
- **Файл и строка**: [ui/web_new/js/library.js:L210-L280](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/ui/web_new/js/library.js#L210-L280)
- **Зона**: `ui/`
- **Описание**: Создание тысяч DOM-узлов без виртуализации нагружает память браузера при открытии больших локальных коллекций.

### [BUG-LOW-03] Зависание сетевых запросов при сбоях DNS в `check_internet`
- **Файл и строка**: [services/zapret_service.py:L122-L139](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/services/zapret_service.py#L122-L139)
- **Зона**: `services/`
- **Описание**: DNS-резолвинг доменных имен в `check_internet` может блокировать поток на время системного таймаута DNS.

### [BUG-LOW-04] Дублирование логики маппинга прокси-URL в `_notify_track_changed`
- **Файл и строка**: [audio/engine.py:L96-L124](file:///C:/Users/valee/OneDrive/Desktop/%D0%B6%D0%B4%D0%B6/%D0%B4%D0%B7/AURA%20Music/audio/engine.py#L96-L124)
- **Зона**: `audio/`
- **Описание**: Ручная конкатенация параметров прокси вместо использования метода `get_proxy_url()`.

---

## 5. 🎯 ПРИОРИТИЗИРОВАННЫЙ ПЛАН ИСПРАВЛЕНИЙ (Что чинить первым)

1. **Фаза 1: Предотвращение крашей и зависаний процесса (Критические)**
   - `BUG-CRIT-01`: Починить логику очереди при отключении Shuffle в `audio/queue.py`.
   - `BUG-CRIT-02` и `BUG-CRIT-03`: Закрыть сокетные исключения и `NoneType.close()` в `core/proxy.py`.
   - `BUG-CRIT-04`: Обеспечить `freeze_support` или перевести `lufs_scanner.py` на `ThreadPoolExecutor`.
   - `BUG-CRIT-05`: Реализовать HTTP-проксирование локальных обложек для WebView2 в `ui/web_new/js/utils.js`.

2. **Фаза 2: Целостность данных и устранение SQL/Logic багов (Высокие)**
   - `BUG-HIGH-01`: Исправить синтаксис SQL в `core/database.py:get_wrapped_stats`.
   - `BUG-HIGH-02`: Исправить маппинг `track_id` в `core/services/recommendation.py`.
   - `BUG-HIGH-03`: Добавить сохранение `file_path` локальных треков в `core/session.py`.
   - `BUG-HIGH-04`: Синхронизировать категорию `theme` между `core/settings.py` и `ui/web_new/js/settings.js`.
   - `BUG-HIGH-08`: Извлекать `source_id` при импорте внешних плейлистов в `playlist_import_service.py`.
   - `BUG-HIGH-10`: Ограничить подсчет размера кэша в `utils/cache_manager.py` только папками кэша.
   - `BUG-HIGH-11`: Исправить извлечение обложек M4A в `utils/tag_parser.py`.

3. **Фаза 3: Стабильность интерфейса и многопоточности (Высокие & Средние)**
   - `BUG-HIGH-05`: Возобновлять отрисовку визуализатора при переходе на страницу в `pages.js`.
   - `BUG-HIGH-06`: Очистить утечки WebAudio API в `player.js`.
   - `BUG-HIGH-07`: Добавить потокобезопасность `YoutubeDL` в сервисах.
   - `BUG-HIGH-09`: Ограничить максимальный таймаут каскадного резолвинга в `audio/engine.py`.
   - `BUG-MED-01` – `BUG-MED-08`: Исправить гонки батч-скачивания, XSS-экранирование и прокси-сессии.

4. **Фаза 4: Оптимизация производительности (Низкие)**
   - Убрать `sleep(1)` в очереди скачивания, оптимизировать `check_internet` и убрать дублирование URL-маппинга.
