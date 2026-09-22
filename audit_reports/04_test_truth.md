# Отчет аудита достоверности тестов (Test Truth Audit)

**Проект**: AURA Music (NeDotify) Linux  
**Дата проведения**: 2026-09-21  
**Каталог аудитора**: `.agents/explorer_test_truth/`  
**Статус**: ЗАВЕРШЕН  

---

## 1. Резюме аудита

Аудит тестовой инфраструктуры (`tests/`, `run_tests.py`, `pytest.ini`) выявил системные проблемы достоверности:
1. **Иллюзия 100% покрытия и ложная победа (False Victory)**:
   В предыдущих циклах разработки (`.agents/auditor/handoff.md:24`) заявлялось: *"Ran 93 tests in 2.926s OK... VERDICT: VICTORY CONFIRMED"*. Однако более 90% методов bridge API (`core/api.py`, 60+ методов из 64) вообще не имеют unit-тестов.
2. **Кейс BUG-030 — классический over-mocking**:
   Баг BUG-030 (скачивание и нормализация треков VK) был помечен как `done` (коммит `58bb252`), но в реальности остался полностью неработоспособен. `yt-dlp` **не поддерживает извлечение аудио из VK** (`VKIE.suitable()` возвращает `False`), однако тест замокал `yt_dlp.YoutubeDL` и подменил `os.path.exists = True`, создав иллюзию работоспособности.
3. **«Grep-as-a-Test» (фиктивные тесты)**:
   Значительная часть регрессионных тестов (`test_audit_regressions.py`, `test_player_tab_m3.py`, `test_fonts_m2.py`) не выполняет код, а с помощью `open()` читает исходные файлы `.py`, `.js`, `.css`, `.html` и проверяет наличие подстрок через `assertIn` или регулярные выражения.
4. **Сломанный дефолтный запуск `run_tests.py`**:
   Запуск `python run_tests.py` в системном окружении падает с ошибкой коллекции (5 ошибок: отсутствие `webview` и `PIL`), так как зависимости установлены только в изолированном `.venv`.
5. **Деструктивные Live-тесты, ломающие рабочее приложение**:
   `test_lifecycle_stress.py`, `test_ui_adversarial_stress.py` и `test_visual_ui.py` запускаются дефолтным pytest-раннером, удаляют системные файлы блокировки в `/tmp/nedotify_instance.lock` и падают с `[Errno 98] Адрес уже используется`, если у пользователя запущено приложение на порту 42001.

---

## 2. Расследование кейса BUG-030

### 2.1. Контекст и предыстория
В `.agent/BACKLOG.md` (коммит `482e05f3`):
> `BUG-030 | BUG | P1 | services/vk_service.py, core/downloader.py | Отсутствие нормализации raw ID треков в download_audio_sync/get_stream_url приводит к ошибкам yt-dlp, утечка .part файлов и отсутствие проверки сервиса vk в downloader | done`

В коммите `58bb252` (`fix(services, core): normalize VKService track IDs, prevent download corruption, and harden VK downloader worker`):
- В `services/vk_service.py:70-78` был добавлен статический метод `_normalize_url(url_or_id)`:
  ```python
  @staticmethod
  def _normalize_url(url_or_id: str) -> str:
      s = str(url_or_id).strip()
      if s.startswith(('http://', 'https://')):
          return s
      if s.startswith('audio') or s.startswith('video'):
          return f"https://vk.com/{s}"
      return f"https://vk.com/audio?id={s}"
  ```
- В `core/downloader.py:184-188` была добавлена ветка:
  ```python
  elif source == 'vk':
      vk_service = getattr(self._core, 'vk', None)
      if not vk_service:
          raise Exception("VK сервис не инициализирован")
      file_path = vk_service.download_audio_sync(source_id, download_dir)
  ```

### 2.2. Как BUG-030 тестировался (Доказательство Over-Mocking)
В `tests/test_services_unit.py:744-758`:
```python
def test_vk_service_normalizes_raw_id_to_url(self):
    fake_info = {"id": "vk_id_100", "ext": "mp3"}
    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, \
         patch("os.path.exists", return_value=True), \
         patch("os.makedirs"):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = fake_info
        mock_ydl.prepare_filename.return_value = "/tmp/vk_test/vk_track.mp3"

        self.vk.download_audio_sync("2000000001_456240001", "/tmp/vk_test")
        mock_ydl.extract_info.assert_called_once_with("https://vk.com/audio?id=2000000001_456240001", download=True)
```
В `tests/test_downloader.py:87-96`:
```python
def test_download_worker_vk_download_support(self):
    item = {"track_id": 505, "source": "vk", "source_id": "https://vk.com/audio123"}
    self.mock_db.conn.cursor.return_value.fetchone.return_value = {"status": "pending"}

    with patch("os.path.exists", return_value=True):
        self.mock_core.vk.download_audio_sync.return_value = "/tmp/fake_vk.mp3"
        self.dm._download_worker(item)

        self.mock_core.vk.download_audio_sync.assert_called_once_with("https://vk.com/audio123", self.dm.download_dir)
```

### 2.3. Реальность (Почему код сломан в рантайме)
1. **yt-dlp не имеет экстрактора для VK Audio**:
   Проверка реального класса `yt_dlp.extractor.vk.VKIE`:
   ```python
   from yt_dlp.extractor.vk import VKIE
   VKIE.suitable('https://vk.com/audio123_456')    # -> False
   VKIE.suitable('https://vk.com/audio?id=123_456') # -> False
   ```
   В библиотеке `yt-dlp` существуют экстракторы только для `vk` (видео и клипы), `VKPlay`, `vk:uservideos` (видео-плейлисты) и `vk:wallpost` (посты с видео). Экстрактора для аудиозаписей ВКонтакте в yt-dlp **нет вообще**.
2. **Аудио VK требует закрытой авторизации и токенов**:
   Любая попытка yt-dlp обработать URL вида `https://vk.com/audio?id=...` попадает в `GenericIE`, получает страницу логина VK или 302 Redirect и падает с ошибкой `Unsupported URL` или `No audio stream found`.
3. **Механизм самообмана**:
   Тест замокал весь класс `yt_dlp.YoutubeDL`, перехватил метод `extract_info`, заставил его вернуть словарь `fake_info`, а также пропатчил `os.path.exists(return_value=True)`. Тест лишь подтвердил, что строка передается в мок.
4. **Результат для пользователя**:
   В приложении при попытке скачать любой трек VK загрузчик `core/downloader.py:188` вызывает реальный `download_audio_sync`, который падает с необработанным исключением в yt-dlp, статус в `download_queue` переходит в `failed`, файл на диск не сохраняется. При попытке воспроизвести VK трек через `services/vk_service.py:79` (`get_stream_url`) вызов yt-dlp также падает, вызывая `error_callback`.
5. **Вывод**:
   BUG-030 был помечен как «done» исключительно на основании самозаверяющего теста, подменяющего всю исполняемую логику моками.

---

## 3. Анализ Over-Mocking в кодовой базе

### 3.1. Подмена тестируемой логики моками (Self-Fulfilling Mocks)

| Файл и строки | Что тестируется | Характер мока | Почему тест недостоверен |
|---|---|---|---|
| `tests/test_audio_proxy.py:126-134` | `StreamProxyHandler._handle_stream` | `StreamProxyHandler.__new__(StreamProxyHandler)` без `__init__`, `handler.serve_local_file = MagicMock()` | Тест не отправляет HTTP-запрос, не создает сокет, не парсит заголовки. Он просто проверяет, вызвался ли мок `serve_local_file`. |
| `tests/test_audio_proxy.py:147-155` | Проверка 403 Forbidden | `handler.send_error = MagicMock()` | Не проверяется реальный HTTP статус-код в сетевом потоке; перехватывается только аргумент Python-метода. |
| `tests/test_downloader.py:54-66` | Fallback Spotify -> YouTube | `mock_core.youtube.download_audio_sync.return_value = "/tmp/fake_spotify.mp3"`, `patch("os.path.exists", return_value=True)` | Реальный резолв через YouTube search и скачивание не выполняются; фиктивный путь считается существующим благодаря `patch`. |
| `tests/test_audit_cycle7.py:68-83` | `AudioEngine._resolve_via_network` для VK | `mock_vk.get_stream_url.side_effect = fake_get_stream` | Подменяет всю сетевую логику VK; подтверждает лишь ветвление `if source == 'vk'`. |

### 3.2. Несоответствие моков реальным ответам провайдеров

#### 1. Spotify Scraper (`services/playlist_import_service.py:358-375`)
- **Как тестируется** (`tests/test_playlist_imports.py:224-245`):
  Тест скармливает сервису синтетический HTML:
  ```html
  <meta property="og:title" content="Awesome Spotify Mix">
  <meta name="description" content="Song A · Artist 1, Song B · Artist 2">
  ```
- **Реальность**:
  Spotify Web Player в мета-теге `description` не отдает список треков в формате `Song · Artist, Song · Artist` для реальных плейлистов (там обычно содержится `Listen on Spotify: Playlist · N songs` или рекламное описание). Когда регулярное выражение не находит ` · `, сервис пытается вызвать `yt-dlp` (`services/playlist_import_service.py:385`), который не поддерживает импорт плейлистов Spotify без плагинов.
- **Итог**: Тест написан под конкретное регулярное выражение и проходит только на искусственной строке.

#### 2. SoundCloud API V2 (`tests/test_playlist_imports.py:73-136`)
- Тест вручную мокает ответы сессии `mock_sc._session.get` с заготовленными словарями (`artwork_url`, `permalink_url`). Реальное поведение SoundCloud (ротация `client_id`, 401/403 ошибки, разбивка длинных плейлистов на страницы по 50 элементов) тестами не покрыто.

#### 3. Yandex Music Client (`tests/test_services_unit.py:838-874`)
- Все вызовы Yandex Music (`client.tracks()`, `track.get_download_info()`) полностью замоканы через `MagicMock`. Работа с реальной сессией `yandex_music.Client`, обработка сетевых обрывов при стриминге и истечение срока жизни ссылок на CDN (`storage.mds.yandex.net`) не проверяются.

---

## 4. Отсутствие интеграции с реальной SQLite схемой

В проекте файл `core/database.py` насчитывает **1566 строк кода** и содержит критическую бизнес-логику: таблицы `tracks`, `playlists`, `playlist_tracks`, `history`, `settings`, `stream_cache`, индексы, триггеры и FTS5.

### Наблюдения аудита:
1. **Только 2 теста из 238** создают экземпляр `DatabaseManager`:
   - `tests/test_audit_regressions.py:244` (`test_database_composite_indexes_exist`) — проверяет только имена индексов в таблице `sqlite_master`.
   - `tests/test_utils_services.py:22` (`TestCacheManagerUnit`) — передает БД в `CacheManager`.
2. **Все остальные тесты мокают базу данных**:
   В `test_downloader.py`, `test_playlist_imports.py`, `test_recommendation_services.py` база подменяется на `MagicMock()`:
   ```python
   self.mock_db = MagicMock()
   self.mock_core.db = self.mock_db
   ```
3. **Архитектурная аномалия `download_queue`**:
   Таблица `download_queue` **отсутствует** в схеме `core/database.py`! Она создается динамически в методе `_init_db_table()` в `core/downloader.py:62-72`.
   Из-за того, что в `tests/test_downloader.py:13` `self.mock_db` — это `MagicMock`, тесты ни разу не проверяли реальное создание этой таблицы и валидность SQL-запросов (`UPDATE download_queue SET status = 'completed' WHERE track_id = ?`).

---

## 5. Вакуум покрытия WebView и Bridge API

В `audit_reports/00_map.md` зафиксировано более **64 публичных методов** `window.pywebview.api.*` в `core/api.py` (размер файла — 3192 строки).

### Результаты анализа вызовов:
- Из 64 методов в unit-тестах вызываются ровно **4 метода**:
  1. `download_track` (`tests/test_downloader.py:41`)
  2. `import_external_playlist` (`tests/test_playlist_imports.py:270`)
  3. `get_artist_discography` (`tests/test_artist_discography.py:683`)
  4. `_migrate_streams_to_sink` (`tests/test_audio_proxy.py:89`)
- **60 методов ядра (93.7%) имеют 0% unit-тестов**, включая:
  `play_track`, `stop_track`, `play_pause`, `next_track`, `prev_track`, `get_queue`, `reorder_queue`, `search`, `get_lyrics`, `get_lyrics_translation`, `get_home_data`, `get_library`, `get_favorites`, `toggle_favorite`, `create_playlist`, `delete_playlist`, `get_settings`, `save_setting`, `set_volume`, `toggle_mute`, `set_position`, `toggle_shuffle`, `toggle_repeat`, `toggle_zapret`, `toggle_discord_rpc`, `find_duplicate_tracks`.
- **Подавление событий в тестах**:
  В `core/api.py:701-718` метод `_emit` проверяет:
  ```python
  if not self._window:
      return
  ```
  В unit-тестах окно `_window` всегда `None` или `MagicMock()`. Соответственно, `_emit` молча выходит, и ни один тест не проверяет, сериализуются ли payload в валидный JSON и соответствуют ли они ожиданиям обработчиков в `ui/web_new_v2/js/events.js`.

---

## 6. Хрупкие и фейковые тесты («Grep-as-a-Test»)

В кодовой базе обнаружена категория тестов, которые не являются функциональными тестами, а лишь открывают файлы проекта через `open()` и ищут в них строки текста.

### Примеры «Grep-as-a-Test»:

1. **`tests/test_audit_regressions.py:193-222`**:
   ```python
   def test_db_connection_cleanup_in_file_scanner(self):
       file_scanner_path = os.path.join(self.project_root, "utils", "file_scanner.py")
       with open(file_scanner_path, "r", encoding="utf-8") as f:
           content = f.read()
       self.assertIn("self.db.close_thread_connection()", content)
       self.assertTrue(re.search(r"finally:.*self\.db\.close_thread_connection\(\)", content, re.DOTALL))
   ```
   *Суть*: Тест не проверяет закрытие соединений в рантайме. Если строка будет написана внутри недостижимого блока `if False:`, тест пройдет.
2. **`tests/test_audit_regressions.py:226-240`**:
   ```python
   self.assertIn("track = track.copy()", engine_code)
   self.assertIn('self.queue.current_track.get("id") == track.get("id")', engine_code)
   ```
   *Суть*: Проверка предотвращения гонки резолвера сведена к текстовому поиску строчек в `audio/engine.py`.
3. **`tests/test_audit_regressions.py:31-66`**:
   Проверяет текст `ui/web_new/js/player.js` и `ui/web_new_v2/js/player.js`:
   `self.assertIn("masterGainNode.gain.value = 0", sync_vol_body)`.
4. **`tests/test_player_tab_m3.py:32-100` и `tests/test_player_tab_m3_node.js`**:
   Дублируют друг друга и проверяют текстовые селекторы в `index.html`, `player-view.css` и `player.js` (`self.assertIn("justify-content: space-between;", block)`).

### Риски:
- Любой безопасный рефакторинг (переименование переменной, изменение CSS-форматирования) ломает тест.
- Нерабочий код с синтаксической ошибкой или упавшим скриптом JS проходит этот тест без замечаний.

---

## 7. Текущий статус запуска тестов

### 7.1. Запуск через системный Python (`python run_tests.py` / `pytest tests/`)
- **Статус**: **СБОЙ (Exit Code 2)**
- **Причина**: В системном Python 3.14 не установлены пакеты `pywebview` и `Pillow` (они есть только в `.venv`).
- **Стек ошибок коллекции (5 ошибок)**:
  1. `tests/test_audio_proxy.py` -> `core/api.py:21: import webview -> ModuleNotFoundError: No module named 'webview'`
  2. `tests/test_audit_regressions.py` -> `core/api.py:21: import webview -> ModuleNotFoundError: No module named 'webview'`
  3. `tests/test_downloader.py` -> `core/api.py:21: import webview -> ModuleNotFoundError: No module named 'webview'`
  4. `tests/test_playlist_imports.py` -> `core/api.py:21: import webview -> ModuleNotFoundError: No module named 'webview'`
  5. `tests/test_visual_ui.py` -> `from PIL import Image -> ModuleNotFoundError: No module named 'PIL'`
- **Дефект `run_tests.py`**:
  В строке 12 `sys.exit(pytest.main([]))` аргументы командной строки `sys.argv[1:]` не передаются в `pytest.main()`, из-за чего флаги фильтрации (`-k`, `-m`) через `run_tests.py` игнорируются.

### 7.2. Запуск через изолированное окружение (`.venv/bin/python run_tests.py`)
- **Статус**: **НЕСТАБИЛЕН / ПАДАЕТ ПРИ ЗАПУЩЕННОМ ПРИЛОЖЕНИИ**
- **Причина**:
  `pytest.ini` содержит только `addopts = -m "not network"`. Live-тесты (`test_lifecycle_stress.py`, `test_ui_adversarial_stress.py`, `test_visual_ui.py` — всего 27 тестов) не имеют маркера `network` и запускаются по умолчанию.
  В этих тестах (`test_lifecycle_stress.py:57-58`):
  - Вызывается `clean_locks_and_ports()`, удаляющая `/tmp/nedotify_instance.lock` и `/tmp/nedotify_http_port`.
  - Запускается дочерний процесс `main.py`, который пытается занять порт 42001.
  - Если приложение уже запущено пользователем (PID 2699710, слушающий 127.0.0.1:42001), сервер Bottle падает с:
    `OSError: [Errno 98] Адрес уже используется`
  - Тесты зависают по таймауту (15–20 секунд на тест) и падают с ошибками `FAILED`.
  - Удаление lock-файлов повреждает состояние запущенного процесса пользователя.

### 7.3. Запуск изолированного подмножества Unit-тестов
Команда:
```bash
.venv/bin/python -m pytest -v -k "not (lifecycle or stress or visual)" tests/
```
- **Результат**: **211 passed, 27 deselected in 3.00s**.
- **Интерпретация**:
  Все 211 чистых unit-тестов отрабатывают за 3 секунды, но их успешное прохождение обманчиво из-за описанных выше проблем с over-mocking и string-matching.

---

## 8. Матрица доказательств (R2 Evidence Table)

| ID | Область | Файл и строки (Evidence) | Симптом / Исходная причина | Статус достоверности |
|---|---|---|---|---|
| **E-01** | VK Downloader | `services/vk_service.py:70-78`, `tests/test_services_unit.py:744-758` | BUG-030 помечен как done, но yt-dlp не имеет VK audio экстрактора (`VKIE.suitable() == False`). Тест замокал `YoutubeDL` и `os.path.exists`. | **CONFIRMED BROKEN** (Ложный тест) |
| **E-02** | Test Runner | `run_tests.py:10-13`, `core/api.py:21` | `python run_tests.py` падает с 5 ошибками `ModuleNotFoundError: No module named 'webview'` в системном окружении. | **CONFIRMED BROKEN** |
| **E-03** | Test Runner CLI | `run_tests.py:12` | `pytest.main([])` вызывается с пустым списком, аргументы `sys.argv[1:]` не пробрасываются в pytest. | **CONFIRMED DEFECT** |
| **E-04** | Live Tests | `tests/test_lifecycle_stress.py:57-58`, `tests/test_visual_ui.py:41-44` | Live GUI тесты не изолированы маркером, удаляют lock-файлы живого приложения в `/tmp` и падают с `[Errno 98] Адрес уже используется`. | **CONFIRMED UNSTABLE** |
| **E-05** | Proxy Tests | `tests/test_audio_proxy.py:126-134` | `StreamProxyHandler.__new__` обходит `__init__`, мокает `serve_local_file`. Реальный HTTP-поток не тестируется. | **CONFIRMED OVER-MOCK** |
| **E-06** | Spotify Import | `services/playlist_import_service.py:358-375`, `tests/test_playlist_imports.py:224-245` | Тест использует искусственный HTML, не соответствующий реальному Spotify. В продакшене парсинг падает на yt-dlp fallback. | **CONFIRMED BRITTLE** |
| **E-07** | Database Schema | `core/database.py:140-270`, `core/downloader.py:62-72` | 99% unit-тестов используют `self.mock_db = MagicMock()`. Таблица `download_queue` отсутствует в `core/database.py`. | **CONFIRMED GAP** |
| **E-08** | Bridge API | `core/api.py:148-192`, `audit_reports/00_map.md:13` | Из 64+ методов `AppApi` unit-тестами затронуты только 4 метода (>93% не покрыто). `_emit` молча выходит при `_window is None`. | **CONFIRMED GAP** |
| **E-09** | Fake Tests | `tests/test_audit_regressions.py:193-240`, `tests/test_player_tab_m3.py:32-100` | Тесты считывают код `.py`/`.js`/`.css` как строки через `open()` и проверяют наличие подстрок (`assertIn`), не выполняя логику. | **CONFIRMED FAKE / FRAGILE** |

---

## 9. Рекомендации по исправлению тестовой инфраструктуры

1. **Изоляция Live-тестов в `pytest.ini`**:
   Добавить маркер `live` для `test_lifecycle_stress.py`, `test_ui_adversarial_stress.py`, `test_visual_ui.py` и исключить их по умолчанию (`addopts = -m "not network and not live"`). Запускать их только при явном указании флага интеграционного тестирования.
2. **Исправление `run_tests.py`**:
   - Передавать `sys.argv[1:]` в `pytest.main(sys.argv[1:])`.
   - Добавить автоопределение виртуального окружения `.venv` (если запускается системным `python`, автоматически перезапускать через `.venv/bin/python`).
3. **Честный статус для VK (BUG-030)**:
   - Признать, что загрузка аудио по raw ID через yt-dlp не поддерживается без приватного VK API / токенов.
   - В `services/vk_service.py` и `core/downloader.py` явно возвращать понятную ошибку пользователю («VK Music требует авторизации через аккаунт») вместо падения в yt-dlp.
   - Убрать ложный тест с `patch("os.path.exists", return_value=True)` или заменить его на тест обработки ошибки неподдерживаемого URL.
4. **Внедрение тестов на реальной SQLite БД (`:memory:`)**:
   Заменить фиктивные `MagicMock()` в `test_downloader.py` и сервисах на реальный экземпляр `DatabaseManager(":memory:")`, чтобы гарантировать валидность схемы и SQL-запросов.
5. **Замена «Grep-as-a-Test» на функциональные проверки**:
   Удалить текстовые проверки исходников в `test_audit_regressions.py` и заменить их на вызовы функций с проверкой выходных состояний.
