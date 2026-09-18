# Code Coverage & Module Inventory

## Core Modules
| Модуль | Описание | Существующее покрытие |
|---|---|---|
| `audio/engine.py` | Координатор аудиодвижка, переключение треков, фейды | `test_audit_regressions.py` (resolver race) |
| `audio/queue.py` | Очередь воспроизведения, shuffle, repeat, negative indexing, peek_next, concurrency | `test_audio_queue.py` |
| `core/app.py` | Инициализация и жизненный цикл приложения | Косвенно через тесты UI и API |
| `core/api.py` | pywebview JS bridge, IPC API | `test_audio_proxy.py`, `test_audit_regressions.py` |
| `core/database.py` | SQLite менеджер, транзакции, миграции, композитные индексы | `test_audit_regressions.py` |
| `core/downloader.py` | Фоновый загрузчик и очередь yt-dlp | `test_downloader.py` |
| `core/proxy.py` | HTTP стрим-прокси, Range 206, кэш, офлайн-треки | `test_audio_proxy.py`, `test_audit_regressions.py` |
| `core/settings.py` | Менеджер настроек JSON | `test_fonts_m2.py`, `test_particles_m1.py` |
| `services/youtube_service.py` | YouTube поиск, стриминг и yt-dlp загрузка | `test_services_unit.py`, `test_downloader.py` |
| `services/soundcloud_service.py` | SoundCloud поиск, REST API v2, стриминг, waveform, кеширование | `test_services_unit.py` |
| `services/spotify_service.py` | Spotify метаданные iTunes, альбомы, плейлисты, LRU кеш, парсер каталога | `test_services_unit.py`, `test_playlist_imports.py`, `test_artist_discography.py` |
| `services/musicbrainz_service.py` | MusicBrainz API, токен-бакет рейт-лимитер 1 rps, release-groups, Wikipedia REST био | `test_artist_discography.py` |
| `services/yandex_service.py` | Yandex Music сервис | `test_services_unit.py` |
| `services/vk_service.py` | VK сервис | `test_services_unit.py`, `test_downloader.py` |
| `services/playlist_import_service.py` | Импорт плейлистов YouTube, SC, Spotify, M3U | `test_playlist_imports.py` |
| `services/artist_service.py` | Мульти-провайдерная дискография (Spotify, MusicBrainz, Last.fm, YT), дедупликация, двуязычная био | `test_utils_services.py`, `test_artist_discography.py` |
| `services/lastfm_service.py` | Last.fm рекомендации, getInfo био, getTopAlbums, похожие артисты/треки | `test_utils_services.py`, `test_artist_discography.py` |
| `services/lyrics_service.py` | Тексты песен, парсинг LRC, offset теги, Genius fallback | `test_utils_services.py` |
| `utils/cache_manager.py` | LRU дисковый кэш треков и обложек, защита от traversal | `test_utils_services.py`, `test_audit_regressions.py` |
| `utils/file_scanner.py` | Сканер локальных аудиофайлов, нормализация путей | `test_utils_services.py`, `test_audit_regressions.py` |
| `ui/web_new_v2/` | Интерфейс плеера, шрифты, частицы, настройки, профиль артиста и табы дискографии | `test_visual_ui.py`, `test_particles_m1.py`, `test_fonts_m2.py`, `test_player_tab_m3.py` |
