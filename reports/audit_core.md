# Аудит модуля `core/` (Бизнес-логика, БД, Настройки, Прокси, API)

## Executive Summary
Проведен глубокий статический анализ всех файлов пакета `core/`.
- **Всего находок**: 10
- **Критические (Critical)**: 2
- **Высокие (High)**: 4
- **Средние (Medium)**: 3
- **Низкие (Low)**: 1

---

### [CORE-001] Незакрытый сокет и падение потока в `serve_local_file` при отключении клиента
- **Файл и строка**: `core/proxy.py:L224-L227`
- **Серьёзность**: `critical`
- **Описание проблемы**: В `serve_local_file` для не-Range запросов вызывается `shutil.copyfileobj(f, self.wfile)` без перехвата сокетных исключений (`ConnectionResetError`, `ConnectionAbortedError`, `BrokenPipeError`, `OSError`). Если WebView2 разрывает соединение во время передачи локального файла, выбрасывается необработанный `WinError 10053`, что приводит к аварийному завершению потока сервера без корректного закрытия файловых дескрипторов и ресурсов.
- **Предполагаемое исправление**: Обернуть `shutil.copyfileobj(f, self.wfile)` в `try...except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError): pass`.

---

### [CORE-002] `AttributeError` в `finally` блоке `do_GET` при сбое сетевого подключения прокси
- **Файл и строка**: `core/proxy.py:L587-L589`
- **Серьёзность**: `critical`
- **Описание проблемы**: В `do_GET` в блоке `finally` вызывается `resp.close()`. Если все попытки подключения в цикле `_safe_urlopen` завершились ошибкой (таймаут, DNS сбой), переменная `resp` остается равной `None`. Вызов `None.close()` порождает `AttributeError: 'NoneType' object has no attribute 'close'`, который маскирует первоначальную сетевую ошибку и крашит поток обработчика.
- **Предполагаемое исправление**: 
```python
finally:
    if resp is not None and hasattr(resp, "close"):
        try:
            resp.close()
        except Exception:
            pass
```

---

### [CORE-003] SQL Синтаксическая ошибка в `get_wrapped_stats("all")`
- **Файл и строка**: `core/database.py:L993-L1006`
- **Серьёзность**: `high`
- **Описание проблемы**: При запросе статистики за период `"all"`, `where_clause` равен пустой строке `""`. В запросе `query_top_artists` строка `{where_clause}` подставляется перед `AND t.artist IS NOT NULL...`. В итоге генерируется невалидный SQL:
`FROM history h JOIN tracks t ON h.track_id = t.id AND t.artist IS NOT NULL...` (отсутствует ключевое слово `WHERE`). Запрос падает с `sqlite3.OperationalError: near "AND": syntax error`.
- **Предполагаемое исправление**: Сформировать `where_clause` как `WHERE 1=1` или динамически объединять условия через список `clauses` с `" AND ".join(clauses)`.

---

### [CORE-004] Маппинг `history.id` вместо `track_id` в рекомендательном движке
- **Файл и строка**: `core/services/recommendation.py:L194-L196`
- **Серьёзность**: `high`
- **Описание проблемы**: Функция `build_real_engine` извлекает `history_records = db.get_history(...)` и делает `history = [str(r.get("id", "")) ...]`. Однако `r["id"]` в возвращаемом словаре — это первичный ключ таблицы `history` (`h.id`), а не `track_id`. В результате `RecommendationEngine` проверяет `track["id"] in self.history_set`, сравнивая ID трека с ID записи истории, из-за чего история прослушиваний пользователя полностью игнорируется в алгоритмах рекомендаций и миксов.
- **Предполагаемое исправление**: Заменить `r.get("id", "")` на `r.get("track_id", "")`.

---

### [CORE-005] Потеря путей локальных треков при сохранении/восстановлении сессии
- **Файл и строка**: `core/session.py:L10-L34`
- **Серьёзность**: `high`
- **Описание проблемы**: В `PERSISTED_TRACK_FIELDS` отсутствует поле `file_path`. Метод `_slim_track` отсекает все поля, кроме белого списка. Для локальных треков (`source == 'local'`) после перезапуска приложения в очереди восстанавливается объект без `file_path`, что делает невозможным воспроизведение локального файла из восстановленной очереди, если его нет в кэше.
- **Предполагаемое исправление**: Добавить сохранение `file_path` для треков с `source == 'local'` в `_slim_track` и `PERSISTED_TRACK_FIELDS`.

---

### [CORE-006] Рассинхронизация категорий настроек `theme` vs `interface` в `DEFAULT_SETTINGS`
- **Файл и строка**: `core/settings.py:L144-L170`, `L427-L437`
- **Серьёзность**: `high`
- **Описание проблемы**: В `DEFAULT_SETTINGS` параметры `theme`, `name`, `accent_color` лежат внутри категории `"interface"`. Однако геттеры-свойства (`theme_name`, `theme_mode`, `accent_color`) и код в `ui/web_new/js/settings.js` запрашивают их из категории `"theme"`. При чистой базе `settings.get("theme", "accent_color")` возвращает дефолт свойства (`#6366f1`), в то время как в `DEFAULT_SETTINGS["interface"]["accent_color"]` задан `#a855f7`.
- **Предполагаемое исправление**: Унифицировать категорию `theme` в `DEFAULT_SETTINGS` и геттерах.

---

### [CORE-007] Двойное обновление FTS5 индекса в `update_track_metadata`
- **Файл и строка**: `core/database.py:L870-L883`
- **Серьёзность**: `medium`
- **Описание проблемы**: В базе данных определен триггер `tracks_au AFTER UPDATE ON tracks`, который автоматически выполняет `'delete'` и `insert` в виртуальную таблицу `tracks_fts`. Метод `update_track_metadata` после `UPDATE tracks` вручную повторно выполняет ручной `'delete'` и `insert` в `tracks_fts`. Это приводит к избыточной нагрузке и риску нарушения целостности FTS индекса.
- **Предполагаемое исправление**: Убрать ручной вызов перестроения `tracks_fts` из `update_track_metadata`, полагаясь на триггер базы данных (или проверять наличие триггера).

---

### [CORE-008] Потоковая небезопасность счетчиков батча в `core/downloader.py`
- **Файл и строка**: `core/downloader.py:L36-L55`, `L170-L186`
- **Серьёзность**: `medium`
- **Описание проблемы**: В `DownloadManager` используются два разных лока: `_queue_lock` и `_lock`. В `start_batch` и `cancel_batch` переменные `_batch_active`, `_batch_total`, `_batch_completed` изменяются под `_queue_lock`, а в `_download_worker` (блок `finally`) они инкрементируются под `_lock`. Это создает состояние гонки при одновременной отмене и завершении скачивания.
- **Предполагаемое исправление**: Использовать единый лок (`self._lock`) для защиты всех полей состояния батча.

---

### [CORE-009] Мутация `sys.modules` в `get_real_thread_class`
- **Файл и строка**: `core/proxy.py:L593-L605`
- **Серьёзность**: `medium`
- **Описание проблемы**: Функция `get_real_thread_class()` выполняет `sys.modules.pop('threading', None)`. Если в этот момент другой поток выполняет `import threading` или использует функции модуля, это приведет к `KeyError` или `ImportError`.
- **Предполагаемое исправление**: Получать реальный класс через `threading.Thread` без модификации словаря `sys.modules`.

---

### [CORE-010] Искусственная задержка `time.sleep(1)` в цикле скачивания очереди
- **Файл и строка**: `core/downloader.py:L117`
- **Серьёзность**: `low`
- **Описание проблемы**: В методе `_process_queue` стоит безусловный `time.sleep(1)` на каждую итерацию. При постановке 50 треков на скачивание отправка задач в `ThreadPoolExecutor` занимает 50 секунд, даже если воркеры свободны.
- **Предполагаемое исправление**: Использовать `queue.Queue` с методом `.get(timeout=1)` вместо списка с ручным `sleep(1)`.
