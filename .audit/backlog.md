# NeDotify / AURA Music — Audit Backlog

## Deduplication Key Schema
`file:line + symptom` | Severity: `CRITICAL` (app dead/data loss/security), `MAJOR` (feature broken), `MINOR` (code hygiene, docs, drift).

---

## Active Backlog Items

### CRITICAL
- **[C-1]** `services/zapret_service.py:170-178 + wmic_csv_column_mismatch_and_swallowed_value_error` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: WMIC CSV formatting outputs `Node,CommandLine,ProcessId`. Splitting on the first two commas fails when arguments contain commas (`--wf-tcp=80,443`), raising `ValueError` in `int(parts[1])` which is swallowed, breaking elevated PID discovery.
- **[C-2]** `services/zapret_service.py:205, 668-678 + standard_user_cannot_kill_elevated_winws` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: Standard non-elevated process cannot terminate elevated `winws.exe` (`taskkill` returns Access is denied). `stop()` deletes `run.pid`, leaving permanent orphan elevated winws locking WinDivert.
- **[C-3 / SEC-1 / Z-5]** `services/zapret_service.py:597-610 + elevated_powershell_command_injection` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: Unescaped `raw_args` formatted directly into elevated PowerShell `-Command` string via `ShellExecuteW('runas', ...)`. Malicious arguments can execute arbitrary commands as Administrator.
- **[C-4 / P-1]** `services/soundcloud_service.py:17-42 + ttl_cache_ordereddict_multithread_race` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: `_TTLCache` uses unsynchronized `collections.OrderedDict` accessed concurrently across 10 thread pool workers, throwing `RuntimeError: OrderedDict mutated during iteration` and `KeyError`.
- **[C-5 / P-2]** `services/soundcloud_service.py:268-270, 460, 560-561 + unclosed_youtube_service_thread_pool_leak` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: Fallback paths instantiate fresh unmanaged `YouTubeService()` instances with dedicated thread pools and HTTP sessions, causing thread/socket explosion.
- **[C-6 / P-4]** `services/lufs_scanner.py:60, 100-102 + background_thread_sqlite_connection_sharing` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: Background daemon thread directly queries and commits on the shared main-thread SQLite connection without lock or thread isolation.
- **[C-7 / F-2]** `core/api.py:2243 + choose_cover_image_wrong_module_import` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: Executes `import pywebview` and `pywebview.OPEN_DIALOG` instead of `import webview`, causing `ModuleNotFoundError` on cover image selection.
- **[C-8 / F-1]** `ui/web_new/js/onboarding.js:60-68 + onboarding_button_id_mismatch_dead_click` | Severity: `CRITICAL` | Status: `NEW`
  - Mechanism: `onboarding.js` searches for non-existent IDs (`ob-btn-next-1`), leaving the actual `ob-btn-next` and `ob-btn-back` buttons without event listeners.

---

### MAJOR
- **[SEC-2]** `core/proxy.py:196-214, 315-320 + ssrf_validation_omission_api_stream` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: SSRF validation is bypassed on `/api/stream` endpoint and self-healing stream re-resolution.
- **[SEC-3]** `core/api.py:68-74, core/proxy.py:41-44 + toctou_dns_rebinding_ssrf` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Independent DNS resolution between SSRF pre-check and `urlopen` allows DNS rebinding with 0 TTL domains.
- **[SEC-5]** `services/lastfm_service.py:19-26 + plaintext_api_keys_in_repo` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: 6 shared Last.fm production API keys hardcoded in source array `API_KEYS`.
- **[P-3]** `services/track_resolver.py:94-96, 134-136 + recommendation_n_plus_one_blocking` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Sequential 5-second blocking resolution on track suggestions stalls recommendations for 30–100s.
- **[P-5]** `core/api.py:1186-1200 + uncancelled_search_timer_thread_accumulation` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Search provider timeout timers (12.0s) are not cancelled on success, lingering in memory.
- **[P-6]** `core/api.py:1225-1267, 1417-1442 + sync_wait_on_bridge_thread_freezes_ui` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `get_album_tracks`, `get_playlist_tracks`, and `get_recommendations` call synchronous `Event.wait()` on JS bridge thread.
- **[P-7]** `core/api.py:1589-1620 + sync_storage_os_walk_stalls_bridge` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `get_storage_info()` performs synchronous recursive `os.walk` on large cache directories on UI bridge thread.
- **[P-8]** `services/lyrics_service.py:63-108 + unpooled_thread_pool_and_uncancelable_requests` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: New thread pool created per lyrics lookup with uncancelable `urllib.request` sockets.
- **[P-9]** `services/youtube_service.py:316-317, 335-360 + search_keystroke_prefetch_storm` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Unconditionally triggers full yt-dlp extraction on top 2 results on every search debounce.
- **[P-10]** `services/taste_profile.py:267, 286-300 + taste_profile_unbounded_history_load` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Fetches all historical records and re-queries SQLite catalog without limits or memoization.
- **[P-11]** `services/lastfm_service.py:198-240 + lastfm_inmemory_cache_unbounded_growth` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: In-memory dictionary `self._cache` lacks LRU/TTL eviction.
- **[P-12]** `services/watchdog_service.py:35, 39, 43 + watchdog_nameerror_is_audio_file` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Filesystem events crash on undefined function `is_audio_file`.
- **[P-13]** `ui/web_new/js/home.js:77-105 + home_startup_burst_concurrency` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Simultaneous un-batched bridge calls trigger provider rate limits on home load.
- **[SQL-1]** `core/database.py:69, 189-202 + missing_index_tracks_file_path` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Full Table Scan (`SCAN tracks`) on every track lookup by file path (`get_track_by_path`, watchdog, LUFS scanner).
- **[SQL-2]** `services/lastfm_service.py:163-172 + lastfm_db_delete_journal_sync_full` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `lastfm_cache.db` operates in legacy DELETE journal mode with `synchronous=FULL` and no busy timeout.
- **[SQL-3]** `services/lastfm_service.py:165-171 + lastfm_cache_missing_ttl_purge` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Unbounded disk growth and retention of stale cache rows in `lastfm_cache.db`.
- **[SQL-4]** `core/database.py:365-382 + missing_composite_index_tracks_source_source_id` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Missing composite index and unique constraint on `tracks(source, source_id)` allowing duplicate track rows.
- **[SQL-5]** `services/track_resolver.py:42-60 + track_resolver_lower_full_table_scan` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Full table scan on `WHERE LOWER(title) = LOWER(?) AND LOWER(artist) = LOWER(?)`.
- **[F-3]** `ui/web_new/js/settings.js:1882 vs player.js:1667 + slider_style_event_target_mismatch` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: CustomEvent dispatched on `window` but listened on `document`.
- **[F-4]** `ui/web_new/js/events.js:45 vs lyrics.js:116 + lyrics_sync_seconds_ms_unit_mismatch` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `events.js` dispatches `pos` in seconds while `updateLyricsPosition` expects milliseconds, breaking synced lyrics.
- **[F-5]** `ui/web_new/js/main.js:23-31 + await_bridge_infinite_polling_loop` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `awaitBridge()` polls indefinitely with no timeout/rejection fallback.
- **[F-6]** `ui/web_new/js/queue.js:97 + queue_onerror_infinite_loop_risk` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Queue drawer `<img>` sets fallback src without resetting `this.onerror=null;`.
- **[F-7]** `ui/web_new/js/search.js:500-535 + album_modal_listener_accumulation` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Attaches new click listeners to reused modal DOM node on every open.
- **[B-6 / SEC-4]** `core/proxy.py:73, 94 + proxy_loopback_cors_wildcard` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Stream proxy serves wildcard `Access-Control-Allow-Origin: *` on loopback.
- **[S-4]** `ui/web_new/js/search.js:207 + multi_provider_search_lack_dedup` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Multi-provider search results lack cross-source track deduplication.
- **[S-9 / F-8]** `ui/web_new/js/hotkeys.js:175 + search_hotkey_navigates_to_home` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Global search hotkey triggers home page navigation instead of search view.
- **[RPC-2]** `core/services/discord_rpc.py:40, 57-74 + unthrottled_connection_attempts_no_backoff` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Missing backoff cooldown spawns thread and instance on every playback event when Discord client is inactive.
- **[RPC-3]** `core/services/discord_rpc.py:35, 102-148 + missing_15s_rate_limiting` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: Dead rate-limiting timestamp field with no debouncing or rate-limiting enforcement logic.
- **[RPC-4]** `core/api.py:858 + stop_playback_does_not_clear_presence` | Severity: `MAJOR` | Status: `STILL`
  - Mechanism: `stop_track()` is a no-op backend stub; stopping playback leaves Rich Presence active indefinitely.
- **[Z-3]** `services/zapret_service.py:134-160 + stale_pid_reuse_terminates_unrelated_apps` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `_pid_alive` and `_kill_pid` do not check executable name, killing unrelated processes on PID collision.
- **[Z-4]** `services/zapret_service.py:182-195 + cim_commandline_access_restriction_elevation` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: `Win32_Process.CommandLine` is empty across integrity boundaries for standard users.
- **[Z-6]** `main.py:186-211 + stale_lock_pid_reuse_prevents_startup` | Severity: `MAJOR` | Status: `NEW`
  - Mechanism: Stale `nedotify_instance.lock` causes instant process exit without verifying image name.

---

### MINOR
- **[P-14]** `services/base_service.py:37-42 + premature_cache_eviction_on_update` | Severity: `MINOR` | Status: `NEW`
- **[P-15]** `services/yandex_service.py:89-94 + unsynchronized_cache_clear` | Severity: `MINOR` | Status: `NEW`
- **[P-16]** `services/youtube_service.py:661 + nameerror_re_not_defined_download` | Severity: `MINOR` | Status: `NEW`
- **[P-17]** `services/audio_fingerprint_service.py:68-85 + sync_file_read_in_duplicate_scan` | Severity: `MINOR` | Status: `NEW`
- **[P-18]** `ui/web_new/js/player.js:1440-1449 + player_slider_permanent_listener_leak` | Severity: `MINOR` | Status: `NEW`
- **[P-19]** `ui/web_new/js/main.js:422-428 + unbounded_closure_nesting_onpythonevent` | Severity: `MINOR` | Status: `NEW`
- **[SEC-6]** `ui/web_new/js/settings.js:2479-2492 + unescaped_workshop_template_interpolation` | Severity: `MINOR` | Status: `NEW`
- **[SQL-6]** `core/database.py:468 + missing_index_tracks_added_at` | Severity: `MINOR` | Status: `NEW`
- **[SQL-7]** `core/database.py:503 + missing_index_tracks_play_count_last_played` | Severity: `MINOR` | Status: `NEW`
- **[SQL-8]** `core/database.py:1008 + missing_index_playlist_tracks_position` | Severity: `MINOR` | Status: `NEW`
- **[SQL-9]** `core/database.py:134, 192 + duplicate_history_played_at_index` | Severity: `MINOR` | Status: `STILL`
- **[SQL-10]** `core/database.py:163, 193 + redundant_stream_cache_index` | Severity: `MINOR` | Status: `STILL`
- **[SQL-11]** `services/taste_profile.py:267 + taste_profile_memory_spike_history_fetch` | Severity: `MINOR` | Status: `NEW`
- **[SQL-12]** `core/database.py:949 + delete_in_get_playlists_write_lock` | Severity: `MINOR` | Status: `NEW`
- **[SQL-13]** `core/database.py:721 + duplicate_fts5_manual_edit_execution` | Severity: `MINOR` | Status: `NEW`
- **[SQL-14]** `core/database.py:646 + arbitrary_album_cover_in_search_albums` | Severity: `MINOR` | Status: `NEW`
- **[RPC-5]** `core/app.py:338 + missing_discord_rpc_stop_on_shutdown` | Severity: `MINOR` | Status: `STILL`
- **[RPC-6]** `core/api.py:2074 + toggle_discord_rpc_false_does_not_close_socket` | Severity: `MINOR` | Status: `STILL`
- **[RPC-7]** `core/services/discord_rpc.py:103 + discord_ipc_string_length_underflow` | Severity: `MINOR` | Status: `STILL`
- **[RPC-8]** `core/services/discord_rpc.py:27 + thread_safety_partial_lock` | Severity: `MINOR` | Status: `STILL`
- **[RPC-9]** `core/services/discord_rpc.py:108 + stale_progress_timestamps_on_replay` | Severity: `MINOR` | Status: `STILL`
- **[Z-7]** `services/zapret_service.py:649 + false_uac_declined_error_message` | Severity: `MINOR` | Status: `NEW`
- **[Z-8]** `services/zapret_service.py:432 + concurrent_update_and_start_race` | Severity: `MINOR` | Status: `NEW`
- **[Z-9]** `services/zapret_service.py:58 + dns_blocking_in_check_internet` | Severity: `MINOR` | Status: `NEW`
- **[F-9]** `ui/web_new/js/particles.js:129 + particles_toggle_listener_leak` | Severity: `MINOR` | Status: `NEW`
- **[F-10]** `ui/web_new/js/pages.js:88 + title_bar_logo_erased_on_nav` | Severity: `MINOR` | Status: `NEW`
- **[F-11]** `ui/web_new/js/events.js:238 + duplicate_unreachable_switch_cases` | Severity: `MINOR` | Status: `NEW`
- **[F-12]** `ui/web_new/js/home.js:435 + dead_event_listener_artists_ready` | Severity: `MINOR` | Status: `NEW`
- **[F-13]** `ui/web_new/js/debug.js:29 + unbounded_debug_console_dom_accumulation` | Severity: `MINOR` | Status: `NEW`
- **[F-14]** `ui/web_new/js/search.js:578 + unchecked_bridge_method_call` | Severity: `MINOR` | Status: `NEW`
- **[F-15]** `core/api.py:451 + stdout_pollution_print_in_maximize` | Severity: `MINOR` | Status: `NEW`
- **[F-16]** `ui/web_new/js/utils.js:126 + youtube_fallback_ignored_missing_data_cover_url` | Severity: `MINOR` | Status: `NEW`
- **[BUILD-1]** `build_nuitka.bat:34 + non_existent_icon_path` | Severity: `MINOR` | Status: `STILL`

---

## Historical Fixed Baseline
- **[CRIT-1]** `core/settings.py:22` — Win32 GeoName crash (FIXED in `05cfd9e`)
- **[B-5]** `core/proxy.py:217` — SSRF TOCTOU and redirect bypass (FIXED in `05cfd9e`)
- **[Z-1 (legacy)]** `services/zapret_service.py:162` — Win11 elevated PID discovery (FIXED in `b4f02bc`)
- **[Z-2 (legacy)]** `core/app.py:130` — Zapret premature autostart in `__init__` (FIXED in `0ac7974`)
- **[S-STARTUP]** `main.py` / `ui/web_new/` — Startup hang & single instance (FIXED in `0ac7974` / `7bf8872`)
- **[D-1 / D-3]** `.gitignore` — Asset and test tracking (FIXED in `a2b0257`)
- **[D-5]** `requirements.txt` — Dependency drift (FIXED in `2a1961c`)
- **[SPEC-1]** `setup_pyinstaller.spec` — Missing hiddenimports (FIXED in `a2b0257`)
- **[SQL-1 (legacy)]** `nedotify_storage.db` — Database fragmentation 96.8% (FIXED via VACUUM)
- **[SQL-2 (legacy)]** `core/database.py:124` — `idx_history_track_id` missing (FIXED in `c900749`)
- **[RPC-1 (legacy)]** `core/services/discord_rpc.py:83` — Connect drop race (FIXED in `c900749`)
