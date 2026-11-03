# Windows audit remediation — core and data

Scope: desktop database/data lifecycle, resolver and offline state, download
scheduling, cache accounting, local file/tag utilities, and scanner behavior.
Android and application/GUI execution are out of scope. Statuses below were
cross-checked against current source and tests; passing legacy tests alone is not
treated as proof that a finding is fixed.

## Findings

| Audit IDs | Status | Resolution and limits |
|---|---|---|
| AUD-151, AUD-153 | Fixed | Duplicate merge reselects the live survivor after updates; empty-playlist cleanup filters by `is_system`, not a display name. Covered by `tests/test_database.py`. |
| AUD-152, AUD-194, AUD-200 | Fixed | Restore migration selects previously merged rows, snapshots use a stable one-shot filename, and an existing backup is preserved before refresh. The merge now aborts if either the file snapshot fails integrity checks or the internal table snapshot cannot be made. Legacy destructive migrations are reported as unrecoverable. `tests/test_dup_cleanup_migration.py`. |
| AUD-155, AUD-163, AUD-198, AUD-533 | Fixed | Database connections are tracked by owner thread, dead-owner handles are reaped lazily on later DB access, and shutdown closes tracked handles. Close is final/idempotent and uses a bounded passive WAL checkpoint. Bridge worker calls close their thread connection in `finally`. `tests/test_db_core_fixes_f2.py`. |
| AUD-156 | Fixed with bounded recent-window semantics | `get_history` first selects at most 20,000 newest events, then groups them; returned tracks are capped at 200, nonpositive limits return no rows, and ordering breaks timestamp ties by event ID. `play_count` and listened duration in this feed describe the bounded event window. Explicit retention remains opt-in to preserve older user history. `tests/test_database.py`. |
| AUD-157–160 | Fixed | Listening stats aggregate in SQL, playlist search counts are joined, query indexes are installed, and download queue rows reference tracks with cascade cleanup. `tests/test_database.py`, `tests/test_db_integrity.py`, `tests/test_db_core_fixes_f2.py`. |
| AUD-161, AUD-162 | Fixed | Settings round-trip JSON values and null; downloaded-track marking validates identifiers and paths and refuses file paths already owned by another track. `tests/test_database.py`, `tests/test_db_core_fixes_f2.py`. |
| AUD-164–168, AUD-201–202 | Fixed in core paths | Resolver owner/waiter deadlines and in-flight cleanup are bounded; negative availability is honored; offline checks use shared availability logic; recovery records the recovered provider identity; stream refresh updates URL fields without overwriting metadata. `tests/test_engine_resolve.py`, `tests/test_resolver_state.py`, `tests/test_playback_recovery.py`. Bridge-level playback is covered separately in `WINDOWS_INTEGRATION_TESTS.md`. |
| AUD-169–174, AUD-176–177, AUD-207–209 | Fixed in downloader paths | Paused batches finish accounting, transient retries are classified and scheduled outside worker slots, cancellation removes managed partial/orphan files, IDs are validated, transfer completeness is checked, and downloaded media is decoded/validated beyond extension and size. `tests/test_downloader.py`, `tests/test_downloader_cancel.py`, `tests/test_download_resume.py`, `tests/test_download_integrity.py`, `tests/test_download_retry.py`. |
| AUD-175 | Fixed | `cancel_batch` delegates one bulk status transition to the database helper, which cancels pending and downloading rows and clears `resume_on_restart` when that column exists. The compatibility fallback also issues one bulk update. `tests/test_database.py`, `tests/test_downloader_cancel.py`. |
| AUD-305, AUD-357, AUD-362 | Fixed | Quota applies to evictable stream cache; storage reports stream and total cache separately; purge does not wipe streams because protected covers/temp files exceed the quota; favorite protection uses normalized source identity. Lightweight settings test doubles tolerate absent settings. `tests/test_cache_manager.py`, `tests/test_cache_lru.py`, `tests/test_cache_performance.py`, `tests/test_provider_loading.py`. |
| AUD-301–303, AUD-307–308, AUD-359–361 | Fixed in tag utilities | Tag writes use sibling temp files and atomic replace; OGG FLAC pictures decode to bytes; WAV reads/writes preserve frames; lyrics normalize; artist fallback uses the last separator; quality matching is anchored; front cover selection and MIME sniffing are handled; failures are logged. `tests/test_tag_parser_remediation.py`. AAC/WMA round trips were not separately exercised. |
| AUD-304, AUD-309, AUD-364 | Fixed in source; UI not manually exercised | Local tracks with distinct file paths no longer collapse solely because title/artist match. Folder scans stream enumeration, reject concurrent scans, return acceptance status, and use generation-based cancellation with a joined `stop()` hook. The bridge and settings action are wired in current source; automated scanner coverage is in `tests/test_file_scanner.py`. No WebView interaction was performed. |
| AUD-306, AUD-358 | Fixed in source | `utils.url_safety.safe_public_url` is shared by media URL checks, API compatibility wrapper, and proxy; it uses bounded DNS lookup and memoization. Bridge/proxy assertions are in `tests/test_api_audit_b.py` and proxy tests. |
| AUD-524 | Fixed in source; confirmation UI not manually exercised | History clearing requires explicit `confirmed=True`, clears history and listening aggregates plus associated session/recommendation/profile state, and the settings flow asks for confirmation before invoking it. `tests/test_api_audit_b.py`; no WebView dialog was opened. |
| AUD-154 | Integrated by root/frontend | The API projects and paginates rows and optionally reports total/has_more; overview requests eight tracks, and all-tracks navigation offers subsequent pages. Legacy list responses remain supported. `WINDOWS_ROOT.md`, `WINDOWS_FRONTEND.md`. |

## Cross-review dispositions for previously unlisted findings

These entries are source-level dispositions, not a blanket closure. The table
distinguishes exercised behavior from findings that still need a focused
regression or a code change.

| Audit ID | Disposition | Source and test evidence / remaining limit |
|---|---|---|
| AUD-127 | Source behavior verified; regression added | Reproduction across queue sizes 1, 199, 200, 201, and 1000 and requested indexes 0, 1, 199, 200, 250, 799, 950, and 999 did not find a dropped current track. `save_session()` advances the retained window to the current index when necessary, adjusts the restored index, caps persisted rows at 200, and preserves position. `tests/test_session_remediation.py` pins all 40 round trips. |
| AUD-128 | Fixed bounded-gap policy; regression added | `ListeningSession.tick()` accepts elapsed gaps through 300 seconds and treats larger gaps as a discontinuity worth zero listening time. This is an intentional anomaly cap: ordinary 15/16/60-second stalls remain measurable while a suspended system or wedged renderer cannot accrue hours. Injected boundary coverage for 15, 16, 60, 300, and 301 seconds is in `tests/test_session_remediation.py`. |
| AUD-146 | Fixed and regression-covered | `report_listening_state()` settles the elapsed interval with `session.tick()` before assigning the incoming playback rate. The transition regression checks 1x to 2x to 0.5x across heartbeats and pause: nine wall-clock seconds accrue ten media seconds. `tests/test_measured_listening.py::test_playback_rate_transition_charges_each_interval_at_its_actual_rate`. |
| AUD-147 | Fixed and regression-covered | `restore_session()` deep-copies `last_queue` before clearing transient remote file paths. The regression verifies both the cached list and its track dictionary retain their original values after restore normalization: `tests/test_session_remediation.py::test_restore_session_clears_legacy_transient_paths_on_copy_only`. |
| AUD-178 | Fixed; behavior regression covered | `_authorized()` UTF-8 encodes supplied and expected tokens before `hmac.compare_digest`. `tests/test_proxy_security.py::test_non_ascii_proxy_token_is_authenticated_without_connection_error` exercises a real authenticated request using a non-ASCII token and an invalid-token request. |
| AUD-179 | Fixed in source; offline gate covered | `do_GET()` checks offline state before resolving missing local paths or opening upstream URLs. `tests/test_offline_proxy.py::test_offline_root_does_not_resolve_missing_local_path` and `test_offline_proxy_refuses_remote_before_dns_or_resolver` cover the no-network contract. |
| AUD-180 | Fixed in source; UNC regression covered | `_resolve_inside_roots()` rejects UNC and non-local `file:` paths before `realpath`; `tests/test_proxy_fixes_f5.py::test_unc_and_file_host_paths_refused_before_fs_access` asserts rejection before filesystem access. |
| AUD-181 | Fixed for local/cached resources; upstream HEAD intentionally not fetched | `do_HEAD()` mirrors local file, DB track path, cached stream, range, and cover/avatar headers. It returns 404 when answering would require fetching an upstream body. `tests/test_proxy_paths.py` covers local HEAD, ranges, auth, and missing paths. |
| AUD-182 | Fixed for supported HTTP(S) HLS resources; malformed non-HTTP URI is fail-closed | `_rewrite_hls_playlist()` routes HTTP(S) URI attributes, nested playlists, and segments through the authenticated proxy. `tests/test_hls_playback.py` covers HLS rewriting and rejects local-file AES key URIs. |
| AUD-183 | Fixed in source; range suite covers byte lengths | `serve_local_file()` opens once, obtains size from that handle with `fstat`, and writes at most the corresponding byte count. `tests/test_proxy_ranges.py` exercises full and partial local responses. Concurrent same-file truncation is not separately simulated. |
| AUD-184 | Fixed in source; overload saturation not measured | Accepted sockets receive a 15-second timeout and the server uses a 24-slot bounded semaphore. `tests/test_proxy_harness.py` checks daemon/thread bookkeeping; no test attempts to saturate all 24 slots. |
| AUD-185 | Fixed through shared transport; connection reuse not benchmarked here | Proxy requests use `utils.url_safety.guarded_open_url`, whose per-thread opener is reused and bypasses environment proxies while pinning validated public addresses. `tests/test_proxy_url_validation.py` and DNS fallback tests cover transport policy; TLS reuse count was not measured. |
| AUD-186 | Fixed in source; lifecycle smoke covered | `process_request()` delegates thread bookkeeping to `ThreadingMixIn` and `process_request_thread()` releases its semaphore in `finally`; it no longer replaces `_threads`. `tests/test_proxy_harness.py` exercises server/thread shutdown helpers. |
| AUD-187 | Fixed by removing proxy-side cache writer | The proxy marks upstream responses non-cacheable and no longer writes 206 bodies into a complete stream-cache file; CacheManager owns file caching. `tests/test_proxy_ranges.py::test_googlevideo_open_ranges_are_bounded_and_never_cached` covers range exclusion. |
| AUD-188 | Fixed; behavior regression covered | Upstream response forwarding uses a fixed allowlist that excludes `Set-Cookie`. `tests/test_proxy_security.py::test_proxy_never_forwards_upstream_set_cookie` serves a mocked upstream response over the real loopback handler and asserts the cookie is absent while audio headers/body remain. |
| AUD-189 | Fixed; behavior regression covered | `_referenced_by_library()` uses the registered `unicode_casefold` SQLite function for stored and requested paths. `tests/test_proxy_security.py::test_proxy_serves_cyrillic_library_path_with_casefold_match` registers a Cyrillic library path in SQLite, requests an alternate-case path through the real proxy, and verifies the media body is served. |
| AUD-190 | Fixed in source; single-range behavior covered | `_parse_byte_range()` accepts one RFC byte range, ignores malformed or multi-range sets, and returns 416 only for valid unsatisfiable ranges. `tests/test_proxy_ranges.py` covers closed/open/suffix, unsatisfiable, malformed, and multi-range cases; a leading plus sign is rejected by digit validation. |
| AUD-191 | Intentional fail-closed deviation; not fixed to audit's skip behavior | `_rewrite_hls_playlist()` raises on any non-HTTP(S) URI attribute, causing the manifest to be rejected rather than skipping that attribute. `tests/test_hls_playback.py::test_hls_rejects_local_file_keys` pins rejection of `file://` AES keys. Keep this security contract unless a safe, explicit policy for unsupported attributes is designed. |
| AUD-192 | Fixed; behavior regression covered | `_host_allows_credentials()` requires HTTPS and provider-owned hostname. `tests/test_proxy_security.py::test_plain_http_yandex_target_never_receives_oauth_credentials` sends a Yandex OAuth setting through a real proxy request to an HTTP Yandex URL and asserts the mocked upstream request has no `Authorization` header. |
| AUD-193 | Fixed in source; auth and CORS paths covered | `do_OPTIONS()` authenticates before returning 204; `end_headers()` adds loopback CORS to error paths when absent. `tests/test_proxy_security.py::test_unauthenticated_options_is_rejected_with_loopback_cors` and `test_proxy_errors_include_loopback_cors_for_visible_status` cover these contracts. |
| AUD-195 | Fixed in source; literal punctuation search covered | `search_tracks()` uses escaped LIKE for punctuation-bearing terms and quotes FTS tokens for ordinary terms; `tests/test_database.py::test_search_tracks_punctuation_uses_literal_like_matching` and `tests/test_db_core_fixes_f2.py` wildcard tests cover literal `%` and `_`. |
| AUD-196 | Fixed; non-duplicate migration failure propagation covered | `tests/test_database_migration_remediation.py::test_non_duplicate_alter_operational_error_propagates` injects a disk-I/O `sqlite3.OperationalError` during a real temporary-DB schema ALTER and verifies initialization propagates it. |
| AUD-197 | Fixed in source; terminal re-arm covered | `download_queue_add()` re-arms failed, cancelled, and paused rows while retaining active/completed rows. `tests/test_db_core_fixes_f2.py::test_terminal_row_is_rearmed` and `test_live_row_is_not_rearmed` cover the upsert contract. |
| AUD-199 | Fixed; legacy settings schema migration covered | `tests/test_database_migration_remediation.py::test_legacy_settings_table_gets_category_without_losing_values` opens a real temporary DB with the old schema and verifies the new `category` column defaults to `general` while preserving the stored setting. |

## Verification

Commands use the repository interpreter and disable pytest's cache plugin:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_file_scanner.py tests/test_playlist_import_atomic.py tests/test_database.py tests/test_db_integrity.py tests/test_dup_cleanup_migration.py tests/test_db_core_fixes_f2.py
```

Result from the most recent focused database/download run: **55 passed**.
Settings flush warnings at teardown are expected from tests that deliberately
close or invalidate their database writer.

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_downloader.py tests/test_downloader_cancel.py tests/test_download_resume.py tests/test_download_integrity.py tests/test_download_retry.py tests/test_engine_resolve.py tests/test_playback_recovery.py tests/test_resolver_state.py tests/test_cache_lru.py tests/test_tag_parser_remediation.py
```

Earlier isolated run: **188 passed, 2 xfailed**.

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_proxy_harness.py tests/test_proxy_paths.py tests/test_proxy_ranges.py tests/test_proxy_security.py tests/test_offline_proxy.py tests/test_proxy_fixes_f5.py
```

Earlier isolated run: **55 passed**. No application window was opened and no
GUI was controlled.

A broader adjacent run including `tests/test_api_f1_audit.py` completed with
**100 passed, 5 failed**. The failures are API behaviors outside these changes:
two `plugins_enabled` bridge writes, deleting a duplicate whose file is gone,
and two external-playlist rollback expectations. They are reported to the
integrating agent rather than counted as regressions from the history,
snapshot, or cancellation changes.

`DatabaseManager.import_playlist_atomic` was source-reviewed: input validation
happens before writes, playlist and track/membership changes share the write
lock and SQLite transaction. `tests/test_playlist_import_atomic.py` injects a
mid-batch trigger failure and verifies rollback for both new and existing
playlists, plus idempotent repeat imports and invalid-input rejection.
