# Windows: источники, Last.fm и удаление старого подключения — 2026-11-09

Область: только `NeDotify_Windows`, Python/Vanilla JS. Android и Linux не изменялись. Это проверка текущего исходного кода; она не подтверждает работу ранее собранного установщика. Существовавшие изменения рабочей копии сохранены.

## Исправленные проблемы

### Выбор неправильной локальной записи

`TrackResolver.resolve_track(title, artist, expected_duration)` передавал ожидаемую длину удалённым провайдерам и включал её в ключ memo, но вызывал `_search_local` без длины. Поэтому локальная запись с теми же исполнителем/названием, но 300 сек вместо 180 сек, выигрывала раньше проверки удалённых кандидатов. Это затрагивало подбор для метаданных каталога и скачивания.

Изменение `services/track_resolver.py`: передавать `expected_duration` через локальный поиск в уже существующий `_is_plausible_match`. Его допуск `max(4 сек, 2,5%)` сохранён, новый алгоритм не вводился.

Два сценария добавлены в `tests/test_track_resolver_matching.py`, каждый для DatabaseManager, raw SQLite tuple и raw SQLite Row: отклонение неверной локальной длины с переходом к провайдеру и выбор правильной локальной записи среди одноимённых. До исправления все 6 падали; после — проходят.

### Название Spotify обещало другой сервис

`services/spotify_service.py` — совместимый исторический класс/ключ источника, который получает поиск, альбомы и треки из `itunes.apple.com` через `ITunesGateway`. Spotify Web API, OAuth пользователя Spotify и защищённого аудиопотока Spotify в этом пути нет. `source_id` трека — выражение `ytsearch1: Artist - Title`, а `audio/engine.py::_resolve_via_network`, ветка `source == 'spotify'`, ищет подходящую запись YouTube через `search_verified`/`same_recording`, получает поток и сохраняет выбранный video ID в настройках категории `resolution`.

В текущем UI источник ошибочно назывался Spotify. Исправлены подпись/aria/иконка селектора в `ui/web_new_v2/index.html`, README и текущая UI-документация. Смежные правки агента альбомов: placeholder и иконка в `search.js`; основной агент обновляет tooltip `utils.js`. Ключ `spotify` и сохранённые ID оставлены для совместимости библиотеки.

`PlaylistImportService.resolve` поддерживает YouTube, SoundCloud, Deezer и M3U/M3U8/JSON/текстовые списки. Импорт Spotify URL не реализован; README теперь прямо сообщает об этом. Существующий `SpotifyService.get_playlist_tracks` является lookup iTunes, а не доступом к плейлистам Spotify. Новую интеграцию Spotify в рамках исправлений не добавляли.

### Старый скрытый раздел авторизации

Раздел подключения Яндекс Музыки был лишь скрыт CSS: его DOM, инструкции токена, device-code обработчики, события и уведомления оставались в поставляемом UI. Удалены сам раздел и обработчики в `index.html`, `settings-panel.js`, `settings.js`, `events.js`; упоминания в README и `UI_UX_CURRENT_STATE.md`. Основной агент удаляет `yandex_device_auth` из `AppApi`/`BridgeApi`, а также из агрегированного поиска; явный поиск остаётся отклонённым существующей политикой отключённых провайдеров.

**Осознанно сохранены**: `services/yandex_service.py`, backend ленивого сервиса и пути воспроизведения/скачивания старых записей, OAuth/DPAPI-фильтры секретов, CDN allowlists и scoped Zapret hosts, секретные ключи старых настроек, пакет `yandex-music` в requirements/lock и hidden import PyInstaller. Это ещё используемый backend совместимости, а не неиспользуемая интеграция. Его удаление сломало бы сохранённые ранее треки и существующую сборку; удаление маскирования секретов или сетевых ограничений ослабило бы защиту. Исторические аудиты/миграции/регрессионные фикстуры и инструкции разработчика с фактическими ссылками на этот backend не переписывались. Нового пользовательского пути подключения/обнаружения этого сервиса больше нет. Наличие служебных идентификаторов и исторических упоминаний не скрывается.

## Last.fm: восемь ответов по реализации

1. **Назначение.** Код реализует дополнительный источник метаданных для discovery: похожие треки/исполнители, топы исполнителя, жанровые теги, мировые и региональные чарты, топ артистов указанного пользователя. Это подтверждают `LastFMService` и вызовы в `RecommendationService`. Исходный замысел автора вне кода и документации не устанавливался; не следует приписывать ему обязательный scrobbling.
2. **Используется сейчас?** Да, условно. Нужны явное `services.lastfm_enabled == True` и действующий ключ из `LASTFM_API_KEY`, `services.lastfm_api_key` либо fallback `auth.lastfm_api_key`. По умолчанию выключено. Ключ сам по себе согласия не даёт. При отказе/отключении `_api_request` возвращает `None`, включая cached responses.
3. **Зависящие функции.** `RecommendationService._discover_candidates` использует `track.getsimilar` и `artist.gettoptracks`; `_get_merged_seed_artists` асинхронно запрашивает `user.gettopartists`; чарты пополняются Last.fm при разрешении. Есть namespace wrappers, `artist_get_top_tags` и чтение recent tracks, но наличие метода не доказывает активного вызова. Artist biography fallback имел вызовы отсутствующих `has_credentials()` и `_get()`, поэтому подавлял AttributeError; это передано агенту альбомов для отдельной проверки/исправления.
4. **Какие данные передаются?** HTTPS GET к `ws.audioscrobbler.com/2.0/`: API-ключ, имя API-метода, формат, limit; в зависимости от метода — имя исполнителя, название трека, country или указанное пользователем имя аккаунта. Через рекомендации названия/исполнители выбранных локальных сигналов тем самым раскрываются Last.fm. Аудиофайлы, полный дамп библиотеки, локальные отметки «любимое» и альбомы текущие вызовы не отправляют. API-ключ обязательно передаётся самому Last.fm — прежняя надпись «ключи API не передаются» была неверной и исправлена в disclosure UI.
5. **Рекомендации?** Да, как необязательный дополнительный кандидатный источник. Основная локальная персонализация/YouTube/SoundCloud/Deezer продолжают работать без него.
6. **История/scrobbling?** Записи `track.scrobble`, `track.updateNowPlaying`, подписания `api_sig` и Last.fm session key в этой интеграции нет. `user.getrecenttracks` — только чтение внешней истории; текущий merge семян реально использует top artists, не загружает историю в локальную БД и не отправляет локальные прослушивания на сервер. Локальная история/аналитика работают через SQLite. Поэтому диалог «Топ треков (Local Last.fm)» переименован в «Топ треков» (`home-shell.js`), чтобы не связывать локальный топ с внешним сервисом.
7. **Последствия удаления.** Пропадут перечисленные дополнительные кандидаты/чарты и внешние user top artists; после восстановления artist bio fallback пропадёт и этот резервный источник. Локальное воспроизведение, очередь, история, лайки и базовые рекомендации принципиально не требуют Last.fm. Прямое удаление файла без правок импортов сломает создание `RecommendationService`.
8. **Рекомендация.** Оставить как необязательный источник; сохранить opt-in и работающие без него рекомендации. Уточнение privacy disclosure уже выполнено. Ключ/secret/UI API не удалялись. Реальный API Last.fm с пользовательским ключом не вызывался, реальные данные пользователя не отправлялись.

Параметр `services.lastfm_api_secret` хранится/маскируется, но не участвует в найденных исходящих запросах: наличие поля не означает, что scrobbling реализован. SQLite `cache/lastfm_cache.db`, memory cache, TTL, key rotation и rate limiter относятся к чтению метаданных.

## Автоматические проверки

Команды выполнялись через `.venv_win\Scripts\python.exe`; tests/conftest изолирует профиль. Внешний транспорт unit/regression suites замокан. Никакие реальные системные службы не устанавливались и Zapret не запускался.

- Начальный новый reproducer: `-m pytest tests/test_windows_provider_cleanup.py tests/test_track_resolver_matching.py -k 'retired or readme or requested_duration' -q`: **8 failed**, доказано наличие скрытых UI/неверного README и неверного duration matching.
- Новые проверки названия каталога и disclosure: **2 failed, 2 passed** до исправления текстов.
- Ранний targeted run matching/provider loading/Last.fm consent/SoundCloud DRM+manifest/resolver/recovery/budget: **105 passed**.
- Широкий run `tests/test_windows_provider_cleanup.py tests/test_track_resolver_matching.py tests/test_provider_loading.py tests/test_provider_performance.py tests/test_lastfm_consent.py tests/test_recording_selection.py tests/test_engine_resolve.py tests/test_soundcloud_drm_unavailable.py tests/test_soundcloud_manifest_reuse.py tests/test_soundcloud_short_playlists.py tests/test_youtube_gating.py tests/test_youtube_related.py tests/test_playback_recovery.py tests/test_resolver_state.py tests/test_resolve_fallback_budget.py tests/test_frontend_js.py tests/test_build_and_brand.py`: **353 passed, 1 skipped**. Skip: `tests/test_build_and_brand.py:212`, `CLAUDE.md not present`; это отсутствие документа, не подтверждение gate.
- Дополнительный run `tests/test_windows_provider_cleanup.py tests/test_track_resolver_matching.py tests/test_lastfm_consent.py tests/test_provider_playback_lane.py tests/test_player_resources.py tests/test_player_recovery_transitions.py tests/test_queue.py tests/test_playlist_import_formats.py tests/test_playlist_import_atomic.py`: **100 passed**. Проверены очередь, освобождение Audio, переходы recovery, резерв playback lane и импорт поддержанных форматов.
- Один запуск с ошибочным именем `tests/test_playlist_import_service.py` не собрал тестов; исправленный запуск реальных файлов — предыдущие 100 passed. Он не считается успешной проверкой.

Сценарии recording selection проверяют отказ от live/remix/другого исполнителя/неверной длительности, повторное использование video ID. Recovery проверяет инвалидацию обоих stream caches, сохранение позиции и отказ от истёкшего URL. Engine проверяет переходы провайдеров, ошибки и общие бюджеты. Это автоматические проверки контрактов, не наблюдение реального проигрывания в WebView.

## Реальные сетевые проверки

Добавлен воспроизводимый `tools/bench/check_windows_sources_20261109.py`: до импорта сервисов HOME/USERPROFILE/APPDATA/LOCALAPPDATA перенаправляются во временный профиль; settings в памяти, без пользовательских cookies/ключей. Скрипт не запускает AppCore, UI, драйверы, Zapret и не меняет библиотеку. Вывод сохраняет только публичные метаданные, HTTP status, Content-Type, byte count; signed stream URL остаются в памяти.

Результаты:

| Сценарий | Фактически наблюдали |
|---|---|
| iTunes «Rick Astley Never Gonna Give You Up» | 3 результата; 213 сек; реальная ветка engine `source=spotify` подобрала проверенный YouTube поток; HTTP **206**, **4096 байт** |
| YouTube тот же запрос | Найден Rick Astley, 214 сек; поток **audio/webm**, HTTP **206**, **4096 байт** |
| SoundCloud тот же запрос | 30-секундное preview; сервис отказал в полном потоке, callback завершился; защищённый звук не извлекался |
| iTunes «HOME Resonance», первый прогон | Метаданные 212 сек; verified mapping отказал, когда приемлемой записи не было среди кандидатов. Не подменил её первым YouTube результатом на 3690 сек |
| Повтор HOME | Каталог 212 сек → подходящий YouTube 213 сек, **audio/webm**, HTTP **206**, **4096 байт** |
| SoundCloud HOME | Реальный найденный трек «Resonance - Home Bladerunner ( Bladerunner 2049 )», Haunuva, 261 сек; HLS manifest HTTP **200**; первый media segment **audio/mp4**, HTTP **206**, **4096 байт**. Это запись самого SoundCloud, не доказательство соответствия оригиналу HOME |

JSON доказательства: `tools/bench/results/windows-sources-live-20261109.json`, `windows-sources-live-mapping-20261109.json`, `windows-sources-live-home-20261109.json`, `windows-sources-live-home-segment-20261109.json`.

Сетевые результаты относятся к моменту проверки и доступности этих конкретных публичных записей. Поиск нестабилен по ранжированию; правило verified mapping позволяет отказать при отсутствии соответствия. Скрипт проверяет доступность первых bytes/segment, **не** полный файл, слышимое аудио, WebView decoder и не весь диапазон перемотки. В Last.fm сеть не обращались.

## Ограничения и оставшиеся задачи

- Нативные пауза/продолжение/seek/прогресс/смена источников/повтор в видимом окне, полный download/decode, сборка и запуск готового EXE не проверялись этой подзадачей. Автотесты не заменяют эти сценарии.
- Нет настоящего Spotify аудио и Spotify playlist URL import. Метаданные Apple и законно доступная подобранная запись YouTube обозначены явно. Для неподходящих/недоступных кандидатов остаётся отказ вместо случайной записи.
- Проверка фактического истечения подписанного удалённого URL выполнялась регрессионными фикстурами, без многочасового ожидания реального TTL.
- Совместимый Яндекс backend/зависимость/исторические упоминания сохранены по причинам выше; полный запрет любых байтов слова в репозитории не заявляется.
- Анализ Last.fm обнаружил сломанный artist bio fallback; результаты его исправления/тестов относятся к отчёту агента альбомов и итоговой интеграции.
