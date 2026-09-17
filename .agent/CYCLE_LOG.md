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

