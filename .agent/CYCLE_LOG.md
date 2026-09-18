# Continuous Improvement Cycle Log

## Cycle 1
- **Started**: 2026-09-17 21:18
- **Initial Baseline**: 63 tests passing (pytest), Node.js verification suites passing.
- **Goals**:
  1. Исправить подстановку мок-трека в `services/playlist_import_service.py` и добавить юнит-тесты импорта плейлистов.
  2. Добавить поддержку загрузки треков Spotify через YouTube в `core/downloader.py`.
  3. Устранить утечку SQLite соединений в потоках `core/downloader.py` (`close_thread_connection()`).
  4. Обеспечить явный возврат булевого статуса в `queue_download()`.
  5. Расширить `_is_safe_local_audio` в `core/proxy.py` проверкой каталога загрузок `downloads_dir`.
  6. Убрать `tests/` и `run_tests.py` из `.gitignore` для сохранения тестов в системе контроля версий.
- **Commits**:
  - `4de0d60`: fix(ui): harmonize font system, particles rendering, and responsive player layout
  - `e16fa92`: fix(core): strengthen process lifecycle, db connection tracking, and audio device monitor
  - `8cb714a`: chore(build): remove tests/ and run_tests.py from .gitignore to track test suites
  - `7bad24f`: fix(importer): remove mock fallback for empty Spotify playlists and add import tests
  - `07e9b5c`: fix(downloader): add Spotify download resolution, cleanup thread db connections, and return bool
  - `fccff13`: fix(proxy): allow downloads_dir in safe local audio check
- **Final Result**:
  - Tests: 63 -> 79 passed (+16 new tests, 0 regressions).
  - All Node.js tests passing.
  - Backlog items BUG-001, BUG-002, DEBT-003, BUG-004, SEC-005, DEBT-006, TEST-007, TEST-008 resolved and verified.

## Cycle 2
- **Started**: 2026-09-17 21:22
- **Initial Baseline**: 79 tests passing (pytest).
- **Goals**:
  1. Исправить критический баг офлайн-воспроизведения скачанных треков (source != 'local') в `core/proxy.py` и защитить локальные файлы от несанкционированного доступа (403 + проверка расширений).
  2. Устранить SSRF уязвимость в `services/playlist_import_service.py` через SafeRedirectHandler (валидация HTTP 30x цепочек) и валидацию доменов Spotify.
  3. Оптимизировать запросы и сортировку в `core/database.py` и `core/downloader.py` композитными индексами (PERF-009).
  4. Устранить технический долг в `artist_profile.js`: удаление устаревшего словаря `MOCK_ARTISTS` в пользу чистого динамического профиля.
- **Commits**:
  - `94c28f4`: fix(proxy): serve downloaded tracks directly and restrict local file access
  - `18c5781`: sec(importer): block SSRF via HTTP redirect chains and enforce Spotify domain validation
  - `a3f9546`: perf(database): add composite indexes for favorites, downloads, playlists, and history
  - `1e52aaf`: refactor(ui): remove static mock artists dictionary in favor of dynamic fallback
- **Final Result**:
  - Tests: 79 -> 85 passed (+6 new tests, 0 regressions).
  - All Node.js tests passing.
  - Backlog items PERF-009, SEC-010, UX-011, BUG-012, SEC-013 resolved and verified.

## Cycle 3
- **Started**: 2026-09-17 21:36
- **Initial Baseline**: 85 tests passing (pytest).
- **Goals**:
  1. Глубокий аудит и юнит-тестирование `audio/queue.py`: поддержка отрицательных индексов, метод `peek_next()`, исправление удаления дубликатов в `_original_order`, сдвиг `_history_stack`, сохранение пользовательского порядка при `move_track()`.
  2. Глубокий аудит и юнит-тестирование `services/soundcloud_service.py`: отказоустойчивость к null-значениям user/media/transcodings/samples, кэширование TTL.
  3. Глубокий аудит и юнит-тестирование `services/spotify_service.py`: устранение `TypeError`/`AttributeError` при null `trackTimeMillis` и `artworkUrl100`, реализация свойства `available` и метода `get_stream_url()`.
  4. Создание изолированных наборов тестов `tests/test_audio_queue.py` (17 тестов) и `tests/test_services_unit.py` (14 тестов).
- **Commits**:
  - `4ae8a5f`: fix(audio): strengthen queue with negative indexing, peek_next, duplicate preservation, and history tracking
  - `6d6d1ce`: fix(services): harden SoundCloud and Spotify parsing against null attributes and missing payloads
  - `e279b9a`: fix(audio, services): resolve history stack desync, repeat-all shuffle lock, and Spotify token/Web API integration
- **Final Result**:
  - Tests: 85 -> 127 passed (+42 new tests, 0 regressions).
  - Backlog items BUG-014, BUG-015, DEBT-016, BUG-017, BUG-018, TEST-019, TEST-020, BUG-021, BUG-022, BUG-023, BUG-024, DEBT-025 resolved and verified.

## Cycle 4
- **Started**: 2026-09-17 22:02
- **Initial Baseline**: 127 tests passing (pytest).
- **Goals**:
  1. Глубокий аудит и юнит-тестирование `services/youtube_service.py`: отказоустойчивость к null-значениям артистов/альбомов, генераторам entries, невалидным строкам длительности и thumbnails, fast-fail на пустых query/URL.
  2. Глубокий аудит и интеграция `services/vk_service.py`: стандартизация на BaseMusicService (кэширование, thread pool), исправление инвертированного пути `file_path`, исправление fallback артиста при `artist: None`, добавление `download_audio_sync` и поддержка в `core/downloader.py` и `core/app.py`.
  3. Глубокий аудит и юнит-тестирование `services/yandex_service.py`: исправление `TypeError` при сравнении `bitrate_in_kbps: None`, join артистов при null, извлечение ID трека из URL в `download_audio_sync`, автосоздание каталогов загрузки, устранение неуправляемого ThreadPoolExecutor.
- **Commits**:
  - `579aea3`: fix(services): harden YouTubeService against malformed metadata, generator entries, and empty queries
  - `982fd4a`: fix(services, core): standardize VKService on BaseMusicService, fix direct URL paths, and add VK download support
  - `7f23095`: fix(services): resolve YandexService None bitrate comparison, null artist crash, and download URL extraction
  - `9c64762`: fix(services): harden YouTubeService artist fallback, duration parsing, dual caching, and download cleanup
  - `58bb252`: fix(services, core): normalize VKService track IDs, prevent download corruption, and harden VK downloader worker
  - `f868dc0`: fix(services): implement atomic downloads and prefix normalization for YandexService
- **Final Result**:
  - Tests: 127 -> 156 passed (+29 new unit tests, 0 regressions).
  - Backlog items BUG-026, BUG-027, BUG-028, BUG-029, BUG-030, BUG-031 resolved and verified.

## Cycle 5
- **Started**: 2026-09-18 07:01
- **Initial Baseline**: 156 tests passing (pytest).
- **Goals**:
  1. Глубокий аудит и защита `utils/cache_manager.py`: предотвращение path traversal в download_id/ключах, мьютекс потокобезопасности при конкурентном `purge_stream_cache`, обработка сбоев диска/прав доступа и отрицательных квот.
  2. Глубокий аудит `utils/file_scanner.py`: обработка битых симлинков и спец-файлов, кроссплатформенная нормализация путей для исключения дубликатов в БД, валидация поврежденных/отрицательных метаданных ID3/Vorbis.
  3. Глубокий аудит `services/lyrics_service.py`: парсер LRC таймстемпов, поддержка 1-значных минут `[1:23.45]`, обработка тегов сдвига `[offset: +/-ms]` и отсечение пустых/пробельных текстов песен.
  4. Глубокий аудит `services/artist_service.py`: устойчивость к null-артистам и не-словарям в ответах, безопасная сортировка альбомов с отсутствующим названием, ретраи при таймаутах сети.
  5. Глубокий аудит `services/lastfm_service.py`: безопасное преобразование чисел (int/float), обработка коллекций с `None` вместо словарей, поддержка картинок-словарей, fast-fail при пустых аргументах.
  6. Добавление тестового набора `tests/test_utils_services.py` (19 юнит-тестов).
- **Commits**:
  - `2d68192`: fix(utils): harden CacheManager against path traversal, concurrency races, and disk errors
  - `a2e9433`: fix(utils): normalize scanner file paths, handle broken symlinks, and sanitize audio metadata
  - `3abdb9b`: fix(services): implement robust LRC parser with offset tag support and validate empty lyrics
  - `a20448d`: fix(services): handle null artist payloads, safe album title sorting, and network timeout retries
  - `809ed41`: fix(services): handle malformed numbers, null collections, and empty arguments in LastFMService
  - `5849284`: test(utils, services): add unit tests for cache, scanner, lyrics, and services
- **Final Result**:
  - Tests: 156 -> 175 passed (+19 new unit tests, 0 regressions).
  - Backlog items BUG-032, BUG-033, BUG-034, BUG-035, BUG-036 resolved and verified.

## Cycle 6
- **Started**: 2026-09-18 07:10
- **Initial Baseline**: 175 tests passing (pytest).
- **Goals**:
  1. Реализация Feature Request #1: "Полноценный парсер дискографии и биографии артистов" с интеграцией Spotify API (с fallback на iTunes Search API), MusicBrainz API (release-groups, Wikipedia REST summaries) и Last.fm API.
  2. Разработка `services/musicbrainz_service.py` с токен-бакет рейт-лимитером (1 rps, threading.Condition), SQLite кэшированием ответов, категоризацией release-groups (albums, singles, eps, compilations) и обложками Cover Art Archive.
  3. Интеграция извлечения двуязычной биографии артиста (RU / EN) через Wikipedia REST API summary по связям MusicBrainz (wikidata / wikipedia URL-relations).
  4. Расширение `services/lastfm_service.py` методами `artist_get_info` (очистка HTML, теги, playcount, listeners, bio) и `artist_get_top_albums`.
  5. Расширение `services/spotify_service.py` методом `get_artist_catalog` с поддержкой Spotify Web API и iTunes API fallback с классификацией по типам релизов (albums, singles, eps, compilations) и извлечением 600x600 artwork.
  6. Рефакторинг `services/artist_service.py` в каскадный сервис с дедупликацией релизов, привязкой `yt_source_id` для воспроизведения, каскадом аватаров и приоритетом двуязычной биографии.
  7. Обновление UI (`ui/web_new/js/artist_profile.js`, `ui/web_new_v2/js/artist_profile.js` и CSS): переключаемые табы дискографии (Все, Альбомы, Синглы, EP, Сборники), отображение года и типа релиза, нормализация названий.
  8. Создание полного набора модульных тестов `tests/test_artist_discography.py` (16 тестов).
- **Commits**:
  - feat(services): add MusicBrainzService with rate limiting and Wikipedia bio integration
  - feat(services): add artist_get_info and artist_get_top_albums to LastFMService
  - feat(services): add get_artist_catalog with Web API and iTunes fallback to SpotifyService
  - feat(services, core): implement multi-source discography and bio cascade in ArtistService
  - feat(ui): render categorized discography tabs and bilingual bio in artist_profile.js
  - test(services): add comprehensive unit test suite for artist discography cascade
  - docs(agent): update FEATURE_REQUESTS, BACKLOG, CYCLE_LOG, STATE, and COVERAGE for Cycle 6
- **Final Result**:
  - Tests: 175 -> 191 passed (+16 new unit tests, 0 regressions).
  - Backlog item FEAT-037 / Feature Request #1 resolved and verified.
