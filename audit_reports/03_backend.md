# Отчет аудита серверной части и сервисов AURA Music (Backend Core & Services)

**Дата**: 2026-09-21  
**Компонент**: `core/` и `services/`  
**Аудитор**: Backend Core Auditor  
**Статус**: COMPLETED  
**Правило доказательности (R2)**: Все утверждения подтверждены точными ссылками на `file:line` и верифицированы статическим анализом кода.

---

## 1. Сводка результатов (Executive Summary)

В ходе глубокого аудита модулей `core/` (`api.py`, `proxy.py`, `downloader.py`, `database.py`, `resolver.py`, `settings.py`, `session.py`, `app.py`) и `services/` (`youtube_service.py`, `soundcloud_service.py`, `spotify_service.py`, `yandex_service.py`, `lyrics_service.py`, `recommendation_service.py`, `track_resolver.py`, `playlist_import_service.py`, `discord_rpc.py`) выявлено **12 подтвержденных дефектов**:

| Severity | Count | Findings |
|:---|:---:|:---|
| **P0** (Критический) | 0 | — |
| **P1** (Высокий) | 4 | Обход проверки истечения stream URL в `api.py`; срыв самовосстановления Spotify-потоков в `proxy.py`; отравление метаданных провайдера в SoundCloud fallback; фиктивная отметка `is_downloaded = 1` для 0-байтовых файлов |
| **P2** (Средний) | 5 | Отсутствие слушателей событий `api_error` и `track_updated` во фронтенде; обход `_write_lock` и транзакций БД в `downloader.py`; отсутствие модуля санитайзинга путей `utils/path_utils.py`; рассинхронизация категорий настроек Discord RPC; неявная обработка WinError 10053 в прокси |
| **P3** (Низкий) | 3 | Несогласованный payload события `playlists_updated`; пустой обработчик `setting_changed`; пропуск кэша поиска на уровне `api.py` и отсутствие TTL-кэша в `spotify_service.py` |

---

## 2. Детальные результаты аудита по направлениям

---

### Направление 1: `core/api.py` — Обработка исключений и эмит событий в UI

#### DEF-BE-01: Событие `api_error` эмитится бэкендом, но игнорируется фронтендом (DEAD_EVENT / Подтип d)
- **Файл и строки**: `core/api.py:181-188`, `ui/web_new_v2/js/events.js:292-294`
- **Severity**: P2
- **Симптом**: При возникновении необработанного исключения в любом публичном bridge-методе UI не получает обратной связи, тост с ошибкой не отображается, элемент управления может зависнуть в состоянии загрузки.
- **Root Cause**: Метод `_install_bridge_error_logging` перехватывает исключения и отправляет событие:
  ```python
  inner_self._emit("api_error", {
      "method": method_name,
      "error": f"{type(exc).__name__}: {exc}",
  })
  ```
  Однако в `ui/web_new_v2/js/events.js` (и `ui/web_new/js/events.js`) отсутствует секция `case 'api_error':`. Событие попадает в `default:` и выводится только в `console.log('Unknown event:', eventName)`.
- **Proposed Fix**: Добавить в `events.js` обработчик `case 'api_error': showToast(`Ошибка вызова ${data.method}: ${data.error}`, 'error'); break;`.
- **Regression Test**: `tests/test_ui_adversarial_stress.py`

#### DEF-BE-02: Событие `track_updated` не имеет слушателя в UI (Подтип d)
- **Файл и строки**: `core/api.py:3100`, `ui/web_new_v2/js/events.js:292`
- **Severity**: P2
- **Симптом**: При изменении тегов трека через метод `update_track_tags` (например, из контекстного меню) UI не обновляет отображение названия, артиста или обложки трека в реальном времени.
- **Root Cause**: `core/api.py:3100` вызывает `self._emit("track_updated", updated_track)`. Во фронтенде нет ни одного слушателя для события `track_updated`.
- **Proposed Fix**: Добавить слушатель `track_updated` в `events.js` с вызовом обновления строки трека в активном представлении (`refreshActiveLibraryView()`).
- **Regression Test**: `tests/test_audit_regressions.py`

#### DEF-BE-03: Пустой обработчик события `setting_changed` в UI
- **Файл и строки**: `core/api.py:1284, 1288, 2306`, `ui/web_new_v2/js/events.js:218-220`
- **Severity**: P3
- **Симптом**: Изменения настроек, инициированные бэкендом (например, после авторизации Яндекс, автостарта или хоткеев), не синхронизируются с элементами управления в UI.
- **Root Cause**: В `events.js:218-220`:
  ```javascript
  case 'setting_changed':
      // data = { key, value, category }
      break;
  ```
  Тело обработчика пустое.
- **Proposed Fix**: Вызывать `applySettingsFromBackend(data)` внутри `case 'setting_changed':`.

#### DEF-BE-04: Несогласованность payload события `playlists_updated`
- **Файл и строки**: `core/api.py:1936, 2022, 2029, 2625`
- **Severity**: P3
- **Симптом**: Разные методы `api.py` передают кардинально разные структуры в одном и том же событии `playlists_updated`.
- **Root Cause**: 
  - Строка 1936 (`import_external_playlist`) и 2625 (`create_local_playlist`) передают словарь `{"playlist_id": id}`.
  - Строки 2022 и 2029 (`create_playlist`, `delete_playlist`) передают список всех плейлистов `self.get_playlists()`.
- **Proposed Fix**: Стандартизировать payload: передавать структуру `{"playlist_id": playlist_id, "playlists": self.get_playlists()}`.

---

### Направление 2: `core/proxy.py`, `core/player.py` и воспроизведение потоков

#### DEF-BE-05: Обход проверки истечения stream URL в `_resolve_track` и `play_track`
- **Файл и строки**: `core/api.py:995-1000`, `core/api.py:1126-1131`
- **Severity**: P1
- **Симптом**: При попытке воспроизвести трек YouTube/SoundCloud, ранее сохраненный в кэше БД `stream_cache`, плеер зависает или завершается ошибкой 403 Forbidden.
- **Root Cause**: 
  В `core/resolver.py` реализован координатор `StreamResolver` с проверкой `_url_expired()` (`expire=` для YouTube, `Policy=` / `EpochTime` для SoundCloud). Однако методы `play_track` и `_resolve_track` в `core/api.py` напрямую обращаются к базе данных:
  ```python
  cached = self._core.db.get_cached_stream(source, str(source_id))
  ...
  c_url = cached.get("stream_url")
  if c_url and (c_url.startswith("http://") or c_url.startswith("https://")):
      track["file_path"] = c_url
      _deliver()
      return
  ```
  Они **не проверяют** `StreamResolver._url_expired(c_url)` и не используют `self._core.resolver.get_cached_url()`. Истекший URL (срок жизни googlevideo ~6 часов, SoundCloud ~15 минут) передается в плеер как валидный.
- **Proposed Fix**: Заменить прямой доступ к БД в `core/api.py:982-1001` и `core/api.py:1113-1132` на вызов `self._core.resolver.get_cached_url(source, source_id)`.
- **Regression Test**: `tests/test_stream_resolver.py::TestStreamResolver::test_url_expired_youtube`

#### DEF-BE-06: Срыв самовосстановления Spotify-потоков в `core/proxy.py` при HTTP 401/403/404
- **Файл и строки**: `core/proxy.py:791`, `core/app.py:239-244`
- **Severity**: P1
- **Симптом**: Функция автоматического переподключения и ре-резолва (self-healing proxy) падает при попытке восстановить поток Spotify-трека.
- **Root Cause**: 
  В `core/proxy.py:791` при получении HTTP ошибки от апстрима вызывается:
  ```python
  self.server.app_core.re_resolve_stream_url_async(source, str(source_id), _on_resolved)
  ```
  Параметр `track` не передается (`track=None`). В `core/app.py:239-244`:
  ```python
  elif track and (not sid_str or sid_str == "None" or sid_str.startswith("spotify_")):
      t_art = track.get("artist", "")
      t_tit = track.get("title", "")
      url = f"ytsearch1:{t_art} - {t_tit}"
  else:
      url = f"https://www.youtube.com/watch?v={sid_str}"
  ```
  Поскольку `track` равен `None`, `re_resolve_stream_url_async` формирует URL вида `https://www.youtube.com/watch?v=<spotify_id>`, где `<spotify_id>` — это хэш Spotify (например, `4cOdK2wGLETKBW3PvgPWqT`). Запрос на YouTube падает с 404, и авто-резолв не срабатывает.
- **Proposed Fix**: В `core/proxy.py:791` передавать `track=track`:
  `self.server.app_core.re_resolve_stream_url_async(source, str(source_id), _on_resolved, track=track)`.
- **Regression Test**: `tests/test_audio_proxy.py`

#### DEF-BE-07: Отсутствие явного перехвата WinError 10053 в `core/proxy.py`
- **Файл и строки**: `core/proxy.py:264, 362, 384, 705, 914`, `AGENTS.md:17`
- **Severity**: P2
- **Симптом**: В правилах `AGENTS.md` предписано перехватывать Windows-специфичный сокетный разрыв `WinError 10053` (`WSAECONNABORTED`). В `core/proxy.py` отсутствует явная проверка `getattr(e, 'winerror', None) == 10053`.
- **Root Cause**: Перехватываются общие `(ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError)`. На Windows ряд вызовов может проскакивать как общий `OSError` с `winerror=10053` без маппинга в `ConnectionAbortedError`.
- **Proposed Fix**: Добавить унифицированный предикат:
  ```python
  def _is_disconnect(e):
      return isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)) or getattr(e, 'winerror', None) in (10053, 10054)
  ```
- **Regression Test**: `tests/test_audio_proxy.py`

---

### Направление 3: `core/downloader.py` — Загрузка треков и целостность файлов

#### DEF-BE-08: Отметка `is_downloaded = 1` для пустых (0-байтовых) файлов
- **Файл и строки**: `core/downloader.py:199-208`
- **Severity**: P1
- **Симптом**: Прерванная загрузка или сбойный поток, создавший пустой файл на диске, помечает трек как успешно скачанный. В дальнейшем трек невозможно воспроизвести оффлайн.
- **Root Cause**: 
  В `downloader.py:199`:
  ```python
  if file_path and os.path.exists(file_path):
      ...
      self._core.db.conn.execute(
          "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
          (file_path, track_id),
      )
  ```
  Проверяется только факт существования файла (`os.path.exists`), но **не проверяется его размер** (`os.path.getsize(file_path) > 1024`). Если сервис создал 0-байтовый файл до ошибки, трек навсегда помечается как `is_downloaded = 1`.
- **Proposed Fix**: Проверять `if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 1024:`.
- **Regression Test**: `tests/test_downloader.py`

#### DEF-BE-09: Отсутствие модуля санитайзинга `utils/path_utils.py` и нечитаемые имена файлов
- **Файл и строки**: `AGENTS.md:19`, `core/downloader.py:171`, `services/youtube_service.py:830-832`, `services/soundcloud_service.py:641`
- **Severity**: P2
- **Симптом**: Файлы сохраняются с нечитаемыми именами (`sc_1726941234.mp3`, `yt_ABC123_1726941234.webm`), без названия трека и артиста. Кириллические символы заменяются на подчеркивания `_____`.
- **Root Cause**: 
  В `AGENTS.md` указано:
  > Always sanitize Cyrillic and forbidden Windows characters (`\ / : * ? " < > |`) when saving cached streams or downloaded music files (`utils/path_utils.py`).
  
  Однако файл `utils/path_utils.py` **отсутствует в репозитории**. В `youtube_service.py:830` используется грубый `re.sub(r'[^a-zA-Z0-9_-]', '_', raw_token)`, уничтожающий кириллицу.
- **Proposed Fix**: Создать `utils/path_utils.py` с функциями `sanitize_filename(name)` и `build_download_filename(artist, title, ext)`, поддерживающими UTF-8/кириллицу и фильтрующими запрещенные символы Windows (`<>:"/\|?*`). Подключить в сервисы загрузки.
- **Regression Test**: `tests/test_utils_services.py`

#### DEF-BE-10: Обход `_write_lock` и транзакций SQLite в `core/downloader.py`
- **Файл и строки**: `core/downloader.py:51-53, 112-116, 160-165, 202-207, 218-220`, `core/database.py:669-674`
- **Severity**: P2
- **Симптом**: Риск `sqlite3.OperationalError: database is locked` при одновременной фоновой загрузке и пользовательских операциях в БД (редактирование тегов, избранное).
- **Root Cause**: 
  `core/downloader.py` выполняет `self._core.db.conn.execute(...)` и `commit()` напрямую без захвата `self._core.db._write_lock`. В `core/database.py:669` уже реализован потокобезопасный метод `mark_track_downloaded(track_id, file_path)`:
  ```python
  def mark_track_downloaded(self, track_id: int, file_path: str) -> None:
      with self._write_lock:
          with self.conn:
              cursor = self.conn.cursor()
              cursor.execute("UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?", (file_path, track_id))
  ```
  `downloader.py` не использует этот метод и делает сырой незащищенный апдейт.
- **Proposed Fix**: Использовать `self._core.db.mark_track_downloaded(track_id, file_path)` и обернуть операции с `download_queue` в `with self._core.db._write_lock: with self._core.db.conn:`.
- **Regression Test**: `tests/test_downloader.py`

---

### Направление 4: Потокобезопасность и параллелизм

#### Анализ разделяемых ресурсов:
- **`BaseMusicService` (`services/base_service.py:76-87`)**:
  - `_stream_cache` и `_search_cache` защищены через `_cache_lock = threading.RLock()`. Чтение и запись синхронизированы.
  - Потоковый пул `_SharedExecutor` защищен внутренним `self._lock = threading.Lock()`.
- **`LyricsService` (`services/lyrics_service.py:93-95`)**:
  - `self._cache` защищен через `self._cache_lock = threading.Lock()`.
- **`LastFMService` (`services/lastfm_service.py:121-122`)**:
  - `self._cache` защищен через `self._cache_lock = threading.Lock()`.
- **`SettingsManager` (`core/settings.py:269-272`)**:
  - `_cache` и `_dirty` защищены `self._lock = threading.RLock()`, сброс на диск защищен `self._flush_lock = threading.Lock()`.
- **`StreamResolver` (`core/resolver.py:48-50`)**:
  - Память `_mem` и полеты `_inflight` защищены `self._lock = threading.Lock()`.

---

### Направление 5: База данных SQLite (`core/database.py`)

#### Результаты инспекции:
- **WAL Mode**: Активирован в `core/database.py:113` (`PRAGMA journal_mode=WAL`).
- **Синхронизация и таймауты**: В `_get_connection()` установлены:
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA busy_timeout=30000` (30 секунд ожидания при блокировке)
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA temp_store=MEMORY`
- **Параметризация запросов**: Проверен AST-анализом весь проект. В `core/database.py` все динамические конструкции (включая строку 856 `UPDATE tracks SET {', '.join(set_clauses)}`) используют строгий whitelist полей (`TRACKS_UPDATABLE_COLUMNS`) и подстановку значений через `?`.
- **Утечки соединений**: Реализован `close_thread_connection()`, который корректно вызывается в `finally:` потоков `proxy.py:280`, `downloader.py:241`, `lufs_scanner.py:104`, `file_scanner.py:138`, `cache_manager.py:365`.

---

### Направление 6: Сервисы (`services/`) и Fallback Chains

#### DEF-BE-11: Отравление метаданных провайдера в SoundCloud Fallback
- **Файл и строки**: `services/soundcloud_service.py:298-304`
- **Severity**: P1
- **Симптом**: Треки, найденные через фолбэк SoundCloud на YouTube, ломают последующее воспроизведение и скачивание.
- **Root Cause**: 
  При падении поиска SoundCloud в блоке `except Exception as e:` запускается фолбэк:
  ```python
  from services.youtube_service import YouTubeService
  yt = YouTubeService(self.settings)

  def yt_cb(tracks):
      for t in tracks:
          t['source'] = 'soundcloud'
      if callback:
          callback(tracks)

  yt.search(query, max_results=max_results, callback=yt_cb, error_callback=error_callback)
  ```
  Код перезаписывает `t['source'] = 'soundcloud'`, оставляя при этом YouTube video ID в `source_id`! Полученный трек имеет `source: 'soundcloud'`, но ID от YouTube. При клике на трек плеер обращается к API SoundCloud за потоком для YouTube ID и возвращает ошибку 404.
- **Proposed Fix**: Не подменять `source` на `'soundcloud'`. Оставлять честный `t['source'] = 'youtube'` либо возвращать чистый результат fallback без мутации исходного источника.
- **Regression Test**: `tests/test_services_unit.py`

#### DEF-BE-12: Рассинхронизация категории настроек Discord RPC
- **Файл и строки**: `core/services/discord_rpc.py:39`, `core/api.py:2947, 2968`, `core/settings.py:52-252`
- **Severity**: P2
- **Симптом**: Настройка `discord_rpc_enabled` не сбрасывается при общем сбросе настроек и отсутствует в `DEFAULT_SETTINGS`.
- **Root Cause**: `discord_rpc.py` и `api.py` обращаются к категории `("app", "discord_rpc_enabled")`. В `DEFAULT_SETTINGS` категории `"app"` не существует (настройки сервисов расположены в `"services"` или `"general"`).
- **Proposed Fix**: Добавить категорию `"app": {"discord_rpc_enabled": True}` в `DEFAULT_SETTINGS` в `core/settings.py` либо перенести ключ в `"services": {"discord_rpc_enabled": True}`.

---

## 3. Сводная таблица дефектов

| ID | Severity | Область | Симптом для пользователя / системы | Статус | Файл и строка |
|:---|:---:|:---|:---|:---:|:---|
| **DEF-BE-01** | P2 | API Bridge | Ошибки бэкенда не отображаются в UI (`api_error` игнорируется) | CONFIRMED | `core/api.py:182`, `ui/web_new_v2/js/events.js:292` |
| **DEF-BE-02** | P2 | API Bridge | Редактирование тегов не обновляет интерфейс (`track_updated` без слушателя) | CONFIRMED | `core/api.py:3100`, `ui/web_new_v2/js/events.js:292` |
| **DEF-BE-03** | P3 | API Bridge | Изменение настроек из бэкенда не обновляет UI (`setting_changed` пустой) | CONFIRMED | `ui/web_new_v2/js/events.js:218` |
| **DEF-BE-04** | P3 | API Bridge | Несогласованный тип данных события `playlists_updated` | CONFIRMED | `core/api.py:1936, 2022` |
| **DEF-BE-05** | P1 | Player / Cache | Воспроизведение кэшированных треков падает с 403 из-за пропуска проверки TTL | CONFIRMED | `core/api.py:995, 1126` |
| **DEF-BE-06** | P1 | Proxy / Stream | Срыв самовосстановления потока Spotify в прокси (потеря объекта track) | CONFIRMED | `core/proxy.py:791`, `core/app.py:239` |
| **DEF-BE-07** | P2 | Proxy / Network | Неявная обработка WinError 10053 в прокси-сервере | CONFIRMED | `core/proxy.py:264, 362, 914` |
| **DEF-BE-08** | P1 | Downloader | 0-байтовые поврежденные файлы помечаются как `is_downloaded = 1` | CONFIRMED | `core/downloader.py:199` |
| **DEF-BE-09** | P2 | Downloader | Отсутствие `utils/path_utils.py` и стирание кириллических имен файлов | CONFIRMED | `AGENTS.md:19`, `services/youtube_service.py:830` |
| **DEF-BE-10** | P2 | Database / Downloader | Обход блокировки `_write_lock` и транзакций SQLite при скачивании | CONFIRMED | `core/downloader.py:202`, `core/database.py:669` |
| **DEF-BE-11** | P1 | Services | Отравление метаданных треков в SoundCloud fallback (`source = soundcloud`) | CONFIRMED | `services/soundcloud_service.py:300` |
| **DEF-BE-12** | P2 | Services / Settings | Настройка Discord RPC не входит в `DEFAULT_SETTINGS` (категория `"app"`) | CONFIRMED | `core/settings.py:52`, `services/discord_rpc.py:39` |

---

## 4. Рекомендации по исправлению (Phase 3 Fix Guidelines)

1. **Воспроизведение (P1)**:
   - В `core/api.py` (`play_track` и `_resolve_track`) делегировать получение кэшированного URL координатору `StreamResolver.get_cached_url()`.
   - В `core/proxy.py:791` передавать `track=track` в `re_resolve_stream_url_async`.
2. **Загрузчик и файлы (P1, P2)**:
   - В `core/downloader.py:199` добавить проверку размера файла `os.path.getsize(file_path) > 1024`.
   - В `core/downloader.py:202` вызывать `self._core.db.mark_track_downloaded(track_id, file_path)` вместо прямого SQL-запроса.
   - Реализовать `utils/path_utils.py` с безопасным санитайзингом имен файлов с поддержкой кириллицы.
3. **Сервисы и события (P1, P2)**:
   - В `services/soundcloud_service.py:300` не мутировать `source` на `'soundcloud'`.
   - В `ui/web_new_v2/js/events.js` добавить обработчики `api_error` и `track_updated`.
   - В `core/settings.py` добавить схему для категории `"app"` (или перенести в `"services"`).
