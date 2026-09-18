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
| PERF-009 | PERF | P2 | `core/database.py` | Индексация внешних ключей и частых выборок (`tracks(album)`, композитные индексы `fav`, `dl`, `playlist_tracks`, `history`, `download_queue`) | done |
| SEC-010 | SEC | P1 | `services/playlist_import_service.py` | Валидация redirect chains в `urllib.request.urlopen` и доменов Spotify для предотвращения SSRF через HTTP 30x редиректы | done |
| UX-011 | UX | P2 | `ui/web_new_v2/js/artist_profile.js` | Удаление устаревшего словаря `MOCK_ARTISTS` в пользу динамических профилей и чистого фоллбэка | done |
| BUG-012 | BUG | P0 | `core/proxy.py` | Воспроизведение скачанных треков (`is_downloaded=1`, `file_path`) при `source != 'local'` вызывало онлайн-резолв вместо локального файла | done |
| SEC-013 | SEC | P1 | `core/proxy.py` | `_is_safe_local_audio` не проверял расширения аудиофайлов и допускал fallthrough в резолвер при запрете доступа | done |
| BUG-014 | BUG | P1 | `audio/queue.py` | `remove_track` удаляет все дубликаты трека из `_original_order` и рассинхронизирует `_history_stack` | done |
| BUG-015 | BUG | P1 | `audio/queue.py` | `move_track` не обновляет `_original_order` при выключенном shuffle, приводя к сбросу пользовательского порядка | done |
| DEBT-016 | DEBT | P2 | `audio/queue.py` | Отсутствие метода `peek_next`, поддержки отрицательных индексов (-1) и валидации входных типов в `add_track` | done |
| BUG-017 | BUG | P1 | `services/soundcloud_service.py` | `AttributeError` при null-значениях user/media объектов в ответах API SoundCloud (`search`, `get_stream_url`, `get_playlist_tracks`) | done |
| BUG-018 | BUG | P1 | `services/spotify_service.py` | `TypeError` / `AttributeError` при `trackTimeMillis: null` и `artworkUrl100: null` в `_cached_spotify_search` и `get_album_tracks` | done |
| TEST-019 | TEST | P1 | `tests/test_audio_queue.py` | Отсутствует изолированный набор юнит-тестов для `PlaybackQueue` (concurrency, repeat/shuffle, history, edge cases) | done |
| BUG-021 | BUG | P1 | `audio/queue.py` | Рассинхронизация `_history_stack` при `add_track(play_next=True)` и переключении shuffle | done |
| BUG-022 | BUG | P1 | `audio/queue.py` | Залипание первого трека при `repeat=all` + shuffle и невозможность старта очереди при `repeat=one` | done |
| BUG-023 | BUG | P1 | `audio/queue.py` | `update_current` не обновляет `_original_order` в режиме shuffle и неограниченный рост `_history_stack` | done |
| BUG-024 | BUG | P1 | `services/soundcloud_service.py` | Пустые/None аргументы в `get_stream_url` и `get_playlist_tracks` вызывали скрейпинг корня через yt-dlp | done |
| DEBT-025 | DEBT | P1 | `services/spotify_service.py` | Отсутствие управления токенами доступа, интеграции со Spotify Web API и резолва ссылок плейлистов | done |
| BUG-026 | BUG | P1 | `services/youtube_service.py` | Падения (TypeError/ValueError) при пустых/null артистах, некорректной длительности, генераторах entries и отсутствие fast-fail валидации | done |
| BUG-027 | BUG | P1 | `services/vk_service.py` | Отсутствие наследования от BaseMusicService (кэш, пул потоков), инвертированный путь file_path, сбой fallback артиста и отсутствие поддержки в downloader | done |
| BUG-028 | BUG | P1 | `services/yandex_service.py` | TypeError при сравнении bitrate None, сбой join артиста при None, отсутствие извлечения ID из URL в download_audio_sync и неуправляемый ThreadPoolExecutor | done |
| BUG-029 | BUG | P1 | `services/youtube_service.py` | Артист возвращает None при uploader/channel=None в стриме, сбой парсинга duration в search на строках секунд, промах кэша по video_id и утечка .part файлов | done |
| BUG-030 | BUG | P1 | `services/vk_service.py`, `core/downloader.py` | Отсутствие нормализации raw ID треков в download_audio_sync/get_stream_url приводит к ошибкам yt-dlp, утечка .part файлов и отсутствие проверки сервиса vk в downloader | done |
| BUG-031 | BUG | P1 | `services/yandex_service.py` | Неатомарная загрузка повреждает конечный mp3 файл при обрыве сети и парсинг префиксов ya:, yandex:, track: ломает запросы к API | done |
| BUG-032 | BUG | P1 | `utils/cache_manager.py` | Уязвимость path traversal в download_id / кэш-файлах, отсутствие блокировки mutex при конкурентном purge_stream_cache, отсутствие обработки disk full / permission errors и отрицательных квот | done |
| BUG-033 | BUG | P1 | `utils/file_scanner.py` | Необработанные битые симлинки и не-файлы в scan_folder/scan_files, отсутствие нормализации путей (дубликаты в БД) и сбои при поврежденных/отрицательных тегах аудио | done |
| BUG-034 | BUG | P1 | `services/lyrics_service.py` | Отсутствие парсера LRC таймстемпов, сбои на 1-значных минутах [1:23.45], неразобранные теги [offset: +/-ms] и принятие пустых/пробельных текстов песен | done |
| BUG-035 | BUG | P1 | `services/artist_service.py` | Падения при null-значениях артистов / не-словарях в ответах, TypeError при сортировке альбомов с null title, необработанные сетевые таймауты и rate limiting | done |
| BUG-036 | BUG | P1 | `services/lastfm_service.py` | Преждевременный abort при временных таймаутах сети, AttributeError на null-коллекциях, падение при строковых числах и сбой обработки одиночных картинок-словарей | done |
| FEAT-037 | FEAT | P1 | `services/artist_service.py`, `services/musicbrainz_service.py`, `services/spotify_service.py`, `services/lastfm_service.py`, `ui/web_new/js/artist_profile.js`, `ui/web_new_v2/js/artist_profile.js` | Полноценный парсер дискографии и биографии артистов: интеграция со Spotify, Last.fm, MusicBrainz с каскадным фоллбэком, категоризацией релизов (альбомы, синглы, EP, сборники), табами в UI и расширенной двуязычной биографией | done |
| BUG-038 | BUG | P1 | `services/watchdog_service.py` | TypeError: unhashable type: 'dict' в `_sync_folders` и падение `stop()` при отсутствующем watchdog модуле | done |
| BUG-039 | BUG | P1 | `services/audio_fingerprint_service.py` | `delete_duplicate_track` удаляет аудиофайл с диска, если на него всё ещё ссылаются другие треки в библиотеке | todo |
| BUG-040 | BUG | P1 | `audio/engine.py` | Отсутствие обработчика `source == "vk"` в каскаде сетевого резолва `_resolve_via_network` | todo |
| BUG-041 | BUG | P1 | `services/taste_profile.py` | Утечка дескрипторов SQLite соединений при передаче строкового пути к БД в `build_from_db` | todo |
| BUG-042 | BUG | P2 | `utils/tag_parser.py` | Коллизии не-уникальных путей бэкапа в `write_tags`, приводящие к перезаписи и повреждению отката | todo |
| BUG-043 | BUG | P2 | `core/session.py` | `restore_session` не сбрасывает `file_path` и `resolved_at` для онлайн-треков Spotify и Yandex | todo |
| BUG-044 | BUG | P2 | `core/services/discord_rpc.py` | Несинхронизированный метод `stop()` допускает состояние гонки с активными потоками подключения | todo |
| BUG-045 | BUG | P2 | `services/lufs_scanner.py` | Неосвобождаемое соединение SQLite потока сканера и сырые UPDATE без `_write_lock` | todo |

