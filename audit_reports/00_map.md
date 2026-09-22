# AURA Music - Repository Map (Phase 0)

## Активный фронтенд
По умолчанию загружается: `web_new_v2` (в `main.py` параметр `ui_dir_name = os.environ.get("NEDOTIFY_UI_DIR", "web_new_v2")`).
Параллельный фронтенд `web_new` активируется только при наличии флага `--v1`. Аудит проводится по `web_new_v2`, для `web_new` требуются только заметки о соответствии.

## Запуск приложения и тестов
- Запуск приложения: `python main.py`
- Запуск тестов: `pytest tests/` или `python run_tests.py`

## JS -> Python Bridge Methods (вызовы из frontend в core/api.py)
`window.pywebview.api.*`
cleanup, set_window, toggle_mini_player, set_mini_player_position, set_windows, close, shutdown, close_window, minimize, minimize_window, restore, maximize, toggle_fullscreen, open_url, open_external_url, emit_event, maybe_log_history, report_state, get_proxy_info, report_position, play_track, stop_track, play_pause, next_track, prev_track, get_queue, reorder_queue, play_next, add_to_queue, add_tracks_to_queue, remove_from_queue, get_setting, set_setting, yandex_device_auth, set_volume, get_volume, get_audio_devices, set_audio_device, toggle_mute, set_position, toggle_shuffle, toggle_repeat, get_next_track, search, get_album_tracks, get_library, get_favorites, get_downloaded_tracks, download_track, import_external_playlist, export_playlist, create_playlist, delete_playlist, get_playlists, add_to_playlist, get_track_info, get_playlist_tracks, get_yt_playlist_tracks, toggle_favorite, get_favorite_tracks, save_theme, complete_onboarding, update_autostart, validate_subscription_key, get_subscription_info, get_settings, save_setting, get_all_settings, get_settings_by_category, update_setting, get_personalization, save_personalization, get_storage_info, clear_storage, get_wrapped_stats, get_equalizer, set_equalizer, get_lyrics, get_lyrics_translation, get_home_data, get_popular_tracks, get_authentic_home_feed, get_profile_stats, select_avatar, create_local_playlist, open_local_file, get_artist_profile, get_artist_discography, get_artists_avatars, get_recommendations, get_track_wave, get_waveform, prefetch_track, download_all_favorites, cancel_batch_download, get_feed, get_home_artists, get_home_releases, get_home_mixes, toggle_zapret, toggle_discord_rpc, get_discord_rpc_status, get_zapret_status, check_zapret_update, update_zapret, find_duplicate_tracks, delete_duplicate_track, update_track_tags, choose_cover_image, get_storage_details, set_cache_quota, clear_storage_cache, get_flow_tracks.

## Python -> JS Events (эмитятся из бэкенда)
Через `window.onPythonEvent(eventName, data)`:
api_error, artist_profile_error, artist_profile_ready, artists_avatars_ready, artists_ready, audio_devices_changed, audio_error, authentic_home_ready, batch_download_cancelled, batch_download_finished, batch_download_progress, batch_download_started, download_complete, error, favorites_updated, feed_ready, library_updated, lyrics_ready, mini_player_toggled, mixes_ready, playlist_changed, playlists_updated, popular_results, position_changed, proxy_status, queue_updated, releases_ready, repeat_changed, search_completed, search_results, setting_changed, shuffle_changed, state_changed, storage_info, storage_updated, theme_changed, track_changed, track_updated, track_wave_ready, yandex_device_auth_code, yandex_device_auth_result.

## Слушатели на фронтенде (Frontend Event Listeners)
В `ui/web_new_v2/js/events.js` определена глобальная функция `window.onPythonEvent = function(eventName, data)`, которая использует `switch(eventName)` для обработки входящих событий. В других файлах (например, `main.js`) эта функция переопределяется (обертывается), чтобы добавить логику ожидания готовности DOM.

## Структура репозитория
- Фронтенд: `ui/web_new_v2/`
  - `index.html` (основная разметка)
  - `js/`: `artist_profile.js`, `contextmenu.js`, `debug.js`, `efficiency.js`, `equalizer.js`, `events.js`, `home.js`, `hotkeys.js`, `library.js`, `lyrics.js`, `main.js`, `onboarding.js`, `pages.js`, `particles.js`, `player.js`, `queue.js`, `search.js`, `settings.js`, `utils.js`, `visualizer.js`
  - `css/components/`: `base.css`, `player-bar.css`, `lyrics.css`, `home-view.css`, `track-table.css`, etc.
- Бэкенд: `core/` и `services/`
  - `core/api.py`: основной мост `window.pywebview.api` (64+ методов)
  - `core/player.py`, `core/proxy.py`, `core/downloader.py`, `core/database.py`
  - `services/`: `lyrics_service.py`, `youtube_service.py`, `soundcloud_service.py`, `spotify_service.py`, `yandex_service.py`, `recommendation_service.py`, `zapret_service.py`, etc.
- Тесты: `tests/`

## Наводки и критические правила
- `position_changed` и `state_changed` эмитятся backend-ом и могут расходиться с реальным состоянием аудио (и синхронизация lyrics может зависеть от них).
- Учесть, что BUG-030 был помечен done, но остался сломан из-за over-mocking в тестах.
- Формат findings: ID, severity (P0/P1/P2/P3), area, symptom, root cause, evidence (file:line), status (UNVERIFIED / CONFIRMED / REFUTED / FIXED), fix/proposed fix, regression test path.
- Подтипы DEAD_CONTROL:
  - a. нет обработчика (неверный селектор, потерян при ререндере).
  - b. обработчик — заглушка (empty body, log-only, TODO, pass).
  - c. вызывает bridge-метод, которого нет, или у которого неверная сигнатура.
  - d. бэкенд отрабатывает, но результат не доходит до UI (событие не эмитится, неверный payload).
  - e. элемент физически недоступен (перекрыт overlay, pointer-events: none).
  - f. обработчик падает (throws/rejects), и ошибка проглатывается.
  - g. работает только в одном состоянии (например, только пока играет первый трек).

