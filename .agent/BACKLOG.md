# Continuous Improvement Backlog

| ID | Категория | Приоритет | Файл | Описание | Статус |
|---|---|---|---|---|---|
| BUG-001 | BUG | P1 | `services/playlist_import_service.py` | `_resolve_spotify` подставляет фейковый `Mock Spotify Track` при ошибке импорта вместо генерации исключения | done |
| BUG-002 | BUG | P1 | `core/downloader.py` | `DownloadManager` не поддерживает загрузку треков `source == 'spotify'`, завершаясь с ошибкой `None or file missing` | done |
| DEBT-003 | DEBT | P1 | `core/downloader.py` | `_download_worker` не закрывает соединение SQLite потока (`db.close_thread_connection()`) в блоке `finally` | done |
| BUG-004 | BUG | P2 | `core/downloader.py` | Метод `queue_download` не возвращает boolean статус добавления, из-за чего `api.download_track` возвращает `None` | done |
| SEC-005 | SEC | P1 | `core/proxy.py` | `_is_safe_local_audio` не проверяет путь `downloads_dir`, что может блокировать стриминг скачанных файлов | done |
| DEBT-006 | DEBT | P2 | `.gitignore` | `tests/` и `run_tests.py` добавлены в `.gitignore`, препятствуя контролю версий тестовых наборов | done |
| TEST-007 | TEST | P1 | `tests/test_playlist_imports.py` | Отсутствует формализованный набор юнит-тестов импорта плейлистов (YouTube, SoundCloud, Spotify) | done |
| TEST-008 | TEST | P1 | `tests/test_downloader.py` | Отсутствует модуль тестов для `core/downloader.py` (загрузка Spotify, закрытие SQLite, возврат статуса) | done |
| PERF-009 | PERF | P2 | `core/database.py` | Индексация внешних ключей и частых выборок (`tracks(source, source_id)`, `tracks(is_downloaded)`) | todo |
| SEC-010 | SEC | P2 | `services/playlist_import_service.py` | Валидация redirect chains в `urllib.request.urlopen` для предотвращения SSRF через HTTP 30x редиректы | todo |
| UX-011 | UX | P2 | `ui/web_new_v2/js/artist_profile.js` | Динамическая загрузка данных артиста через backend API вместо статичного словаря `MOCK_ARTISTS` | todo |
