# Windows audit remediation — services

Scope: the Windows desktop service layer in `services/`, `core/services/` where
it implements a service, and directly related service tests. Android and GUI
runtime behavior were not exercised. This records source state and isolated
test evidence; it is not a claim that every item in the full audit is closed.

## Service findings

| Audit IDs | Status | Resolution / evidence |
|---|---|---|
| AUD-211–215 | Fixed | Track matching now compares normalized artist credits and title versions, rejects empty titles, enforces one cancellable resolution deadline, and serializes lazy provider construction. `tests/test_track_resolver_matching.py`, `tests/test_media_guard_f3.py`, and `tests/test_lazy_service_deadlock.py`. |
| AUD-216–220 | Fixed | Providers use the shared proxy-aware transport, expired single-flight requests can be retried, search caches are separated from recommendation caches, and rejected proxy values are redacted in logs. `tests/test_service_fixes_f4.py`, `tests/test_provider_loading.py`. |
| AUD-221–226 | Fixed | YouTube storyboard and gate errors are normalized on search/stream paths; cookie fallback is bounded and does not merge browser cookies into the saved cookie file; cookie configuration participates in extractor reuse; playable audio formats are selected. `tests/test_youtube_gating.py`, `tests/test_youtube_related.py`, `tests/test_provider_loading.py`. |
| AUD-227–234 | Fixed | SoundCloud keeps later playable transcodings, scopes temporary CDN failures to SoundCloud and re-probes them, handles null metadata, guards payload URLs, shares bounded verification state, and passes playlist limits. `tests/test_soundcloud_drm_unavailable.py`, `tests/test_service_fixes_f4.py`. |
| AUD-235–237, AUD-239–242 | Fixed | Catalog artist-credit matching is symmetric; playlist imports validate each item, cap and time-bound work, validate redirect destinations, and accept supported remote playlist files; artist profile work observes a deadline/cancellation token and uses a bounded profile cache. `tests/test_catalog_verification.py`, `tests/test_catalog_lyrics_ui.py`, `tests/test_onboarding_ui.py`. |
| AUD-238 | Integrated | API imports use `DatabaseManager.import_playlist_atomic`; new/existing playlists, rows and membership roll back together, verified using a mid-batch SQLite trigger failure. `tests/test_playlist_import_atomic.py`. |
| AUD-243 | Fixed | Offline smart-playlist filtering materializes the stream-cache identities once per page instead of rescanning the cache for each batch. `tests/test_smart_playlists.py`. |
| AUD-244–246 | Fixed | Spotify/iTunes joined requests are generation-scoped; the iTunes request queue shares a bounded budget and preserves retry-after; Yandex auth failures are surfaced instead of silently becoming anonymous access. `tests/test_itunes_request_queue.py`, `tests/test_provider_loading.py`. |
| AUD-247 | Root-owned | OAuth callback/bridge routing is outside the service-layer change. |
| AUD-248–250 | Fixed | Yandex expiry recognizes timestamps encoded in the path, Last.fm reads live credentials, and it reuses the base service cache lock. `tests/test_stream_startup_performance.py`, `tests/test_service_fixes_f4.py`. |
| AUD-251–255 | Fixed | LUFS analysis streams decoded audio in native channel count, records failed/missing measurements as status rather than fabricated values, rejects non-finite results, includes downloaded files, and keys measurements by path/mtime. `tests/test_lufs_resources.py`. |
| AUD-256 | Integrated in source | Watchdog waits for stable size/mtime and handles an unstarted observer. Folder-import completion registers the scanned folder in the DB, starts/synchronizes the watcher and emits progress/completion. Provider/scanner/UI contract suites cover the components; the native picker was not opened. |
| AUD-257–258 | Fixed with narrowed promise | Duplicate candidates include downloaded rows. The implementation is explicitly byte-for-byte SHA-256 identity, not an acoustic fingerprint or “90% similarity” detector; deletion requires an exact full-content match to a verified keeper and merges the DB identity. The legacy one-ID bridge call resolves only an exact-hash keeper; absent a match it refuses deletion. Shared file paths are preserved. It intentionally does not claim to detect re-encodes. `tests/test_audio_fingerprint_duplicates.py`, `tests/test_service_fixes_f4.py`. |
| AUD-259 | Fixed | Listening comparison materializes the pre-window artist set once; optional IANA timezone input computes each local day using that date's DST offset. `tests/test_listening_comparison.py`. |
| AUD-260 | Integrated | Lyrics fan-out honors `lyrics.enabled`; settings now includes the actual toggle and an external-metadata disclosure, with HTML placement and callback tests. `tests/test_settings_controls_ui.py`. |
| AUD-261–266 | Fixed | Lyrics lookup bounds provider fan-out and starts its deadline after admission; translation returns an explicit failure, chunks by encoded-byte budget without silent truncation, and refuses offline requests. `tests/test_lyrics_performance.py`, `tests/test_verified_lyrics.py`, `tests/test_lyrics_netease.py`. |
| AUD-267 | Root-owned | `LyricsService.shutdown_executor()` exists; `AppCore` must call it in the ordered shutdown path. |
| AUD-268 | Fixed | Lyrics HTTP calls use the app's proxy-aware service transport. `tests/test_lyrics_netease.py`, `tests/test_lyrics_performance.py`. |
| AUD-269–272 | Fixed | Recommendation inputs preserve measured listening fields; taste-profile memoization uses stable data/settings revisions without a connection object; artist aliases are revision-cached; the unused second scorer was removed. `tests/test_recommendation_service.py`, `tests/test_taste_profile.py`, `tests/test_measured_listening.py`. |
| AUD-273–277 | Root-owned | These findings are in the bridge/API (`core/api.py`): asynchronous recommendations, bounded avatars/waveforms, regional charts, cover retry state, and translation response envelope. |
| AUD-310–318 | Fixed / coordinated | Zapret update locks, binary validation, size limits, fail-closed digest handling, bounded process operations and atomic replacement are hardened; Discord stop/connect generation handling is fixed. Disabling Discord through the API must call `stop()` (root-owned). `tests/test_zapret_binary_integrity.py`, `tests/test_zapret_uac_window.py`. |
| AUD-319–322 | Fixed | VK TLS verification is enabled and its service is explicitly unavailable for search; Apple/iTunes transport re-reads current proxy settings; Yandex client is rebuilt when its token changes. `tests/test_provider_loading.py`, `tests/test_itunes_request_queue.py`. |
| AUD-323–338 | Fixed | Zapret PE architecture and argument options are validated, Windows quoting is parsed safely, provider construction/client-ID work is shared, YouTube cookie/gating/format/playlist edge cases are covered, and SoundCloud handles preview URLs, retry-after, and missing client IDs. `tests/test_zapret_binary_integrity.py`, `tests/test_soundcloud_drm_unavailable.py`, `tests/test_youtube_related.py`, `tests/test_youtube_gating.py`. |
| AUD-339–341 | Fixed | Music credit parsing handles “featuring” before “feat”, similarity is symmetric, and artist aliases are cached by settings revision. `tests/test_track_resolver_matching.py`, `tests/test_taste_profile.py`. |
| AUD-342, AUD-347 | Fixed | Playlist import provider dispatch checks parsed hosts and its supported-provider error includes SoundCloud. `tests/test_onboarding_ui.py`, `tests/test_provider_loading.py`. |
| AUD-343–346 | Fixed | Smart-playlist filters handle invalid persisted rules; catalog single-flight cleanup runs on copy failure; obsolete avatar cache declarations were removed; short artist names can produce near candidates. `tests/test_smart_playlists.py`, `tests/test_catalog_verification.py`. |
| AUD-348 | Fixed | Yandex accepts numeric IDs and supported `music.yandex.ru` / `.com` track URLs through one parser; download no longer turns a URL into the ID `https`. `tests/test_yandex_service.py`. |
| AUD-349–350 | Fixed | LRC headers are case-insensitive; embedded lyrics are identity-checked before winning the provider cascade. `tests/test_verified_lyrics.py`, `tests/test_lyrics_performance.py`. |
| AUD-351–353 | Fixed | LUFS memo rows include file mtime, writes use the DB write lock/transaction, and stop waits for in-flight analysis before returning. `tests/test_lufs_resources.py`. |
| AUD-354–355 | Fixed | Folder watcher waits for a stable file signature and only joins an observer that was started. `tests/test_provider_loading.py`. |
| AUD-356 | Fixed | Listening comparison accepts a timezone name and groups each UTC timestamp in that zone, including DST changes. `tests/test_listening_comparison.py`. |
| AUD-357–358 | Root-owned | Cache ownership and shared URL-safety implementation are tracked with `utils/cache_manager.py`, `utils/url_safety.py`, and the bridge/proxy remediation. |
| AUD-523 | Fixed | Recommendation provider outages now reach the async error callback and are briefly negative-cached, avoiding a full provider fan-out on each home reload. Regression test also verifies retry after the short cache expires. `tests/test_recommendation_service.py`. |
| AUD-527 | Integrated | Settings includes an explicit consent switch, username, masked API key replacement and data disclosure. Backend defaults consent to false independently of saved/environment credentials; LastFMService enforces consent/offline state before HTTP and recommendations enforce consent before seed lookups. Canonical service keys retain a masked legacy-auth fallback. `tests/test_lastfm_consent.py` plus settings/recommendation suites. |
| AUD-528–530, AUD-532 | Fixed | Settings are passed into custom-artist/smart-feed profiles; feed keys use bounded digests rather than large raw signatures; profile state is copied once; aliases are cached by settings revision. `tests/test_recommendation_service.py`, `tests/test_taste_profile.py`. |
| AUD-531 | Coordinated with core/data | Taste memo keys no longer include the connection object. Stable cross-thread hits depend on `DatabaseManager.data_revision` and `SettingsManager.revision`, owned by core/data remediation. `tests/test_taste_profile.py`. |
| AUD-533–534 | Root-owned / removed | AUD-533 is the bridge connection lifecycle. The unimported duplicate scorer for AUD-534 was removed with AUD-272. |
| AUD-520 | Fixed in source; incorrect-match regression covered | `LyricsLookup.accept()` compares positive expected duration before synced/unsynced output selection and requires a non-placeholder artist plus duration when artist metadata is unavailable. `tests/test_verified_lyrics.py` covers duration compatibility and provider artist filtering. |
| AUD-521 | Fixed with bounded writer retries and durable bridge acknowledgement | Failed or short writes restore all pending keys. The background writer retries up to five times with bounded backoff; a synchronous flush reports failure without claiming persistence. Bridge saves wait for that result and roll back the cached value on failure. `tests/test_settings_flush.py`, `tests/test_api_misc.py`. |
| AUD-203 | Fixed | `utils.stream_urls.stream_url_expired()` accepts both epoch expiry values and HTTP-date `Expires` values. `tests/test_stream_startup_performance.py::test_expires_accepts_http_date_form`. |
| AUD-204 | Fixed | `core.playback_recovery._callback_result()` invokes providers on a daemon worker and bounds the caller's wait; late callbacks are ignored after timeout. `tests/test_playback_recovery.py::test_callback_result_timeout_does_not_wait_for_blocking_provider`. |
| AUD-205 | Fixed | `_invalidate()` snapshots the shared provider cache once while holding `_cache_lock`, then checks entries outside the full-scan critical section and conditionally removes exact entries. `tests/test_playback_recovery.py::test_invalidate_snapshots_shared_provider_cache_once`. |
| AUD-206 | Fixed | When the wanted track has a positive duration, a candidate with missing/non-positive duration is rejected before it can be selected and cached as a fallback. `tests/test_playback_recovery.py::test_same_recording_requires_offered_duration_when_expected`. |
| AUD-210 | Fixed | `DownloadStore.rows()` performs the pure SELECT without acquiring `DatabaseManager._write_lock`; writes remain serialized through that lock. `tests/test_download_resume.py::test_download_store_rows_does_not_take_database_write_lock`. |
| X-11 | Fixed | LUFS analysis and duplicate discovery select tracks with a real `file_path`, including downloaded provider tracks; they no longer rely on `source='local'`. `tests/test_lufs_resources.py`, `tests/test_audio_fingerprint_duplicates.py`. |
| X-12 | Fixed | Proxy 403/410 self-heal invalidates the provider's own cached stream URL before resolver/DB invalidation and re-resolution. YouTube invalidation also removes the cached resolved video ID behind a Spotify search-expression key; SoundCloud removes its supported provider key forms. `tests/test_proxy_provider_cache.py`. |
| X-14 | Fixed at the provider boundary | YouTube and SoundCloud stream extraction now use dedicated two-worker playback executors; search and other provider work retain their existing executors. `AppCore`'s existing executor shutdown discovery includes `_playback_executor`. `tests/test_provider_playback_lane.py`. The mocked routing regression is verified; live provider saturation was not exercised. |

## Verification

Commands run with the repository interpreter, using pytest's isolated profile:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_yandex_service.py tests/test_recommendation_service.py
```

Result: **25 passed**.

The cross-module proxy/cache and playback-lane regressions were verified with:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_provider_playback_lane.py tests/test_proxy_provider_cache.py tests/test_service_fixes_f4.py tests/test_youtube_gating.py tests/test_soundcloud_drm_unavailable.py tests/test_provider_loading.py
```

Result: **37 passed**. No application window or GUI was opened.

A wider service regression batch was also run:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests/test_service_fixes_f4.py tests/test_track_resolver_matching.py tests/test_youtube_gating.py tests/test_soundcloud_drm_unavailable.py tests/test_youtube_related.py tests/test_lyrics_netease.py tests/test_verified_lyrics.py tests/test_recommendation_service.py tests/test_taste_profile.py tests/test_listening_comparison.py tests/test_smart_playlists.py tests/test_catalog_verification.py tests/test_lufs_resources.py tests/test_provider_loading.py
```

The initial wider batch reported **253 passed, 2 failed, 1 teardown error**.
The recommendation assertion encoded the old empty-success contract; it now
checks the intended provider error and short negative-cache expiry. On rerun,
**263 passed, 1 failed, 1 teardown error**: the remaining service-adjacent
assertion expected `.m4a` while its mocked response declares `audio/wav`; the
isolated run exposed that stale expectation. The root agent is fixing the
bridge-executor teardown fixture, and the core agent is updating the audio-cache
fixture. Rerun the wider batch after those shared test fixes land. No
application window was opened and no GUI/manual provider traffic was used.
