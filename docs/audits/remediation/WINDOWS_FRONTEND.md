# Windows frontend remediation

Scope: desktop UI in `ui/web_new_v2/` only. The application and GUI were not
started for this pass. No Android files were changed by this frontend work.

## Findings verified in the current UI

| Audit ID | Status | Frontend change / evidence |
|---|---|---|
| AUD-009 | Fixed in current source | `events.js` installs the bridge dispatcher before `initEvents()` and queues early events until `flushPythonEvents()`. Existing frontend event tests cover early queueing and delivery. |
| AUD-260, AUD-527 | Integrated | Actual settings controls disclose lyrics metadata requests and Last.fm data use. Last.fm requires explicit consent, disabled by default, enforced by the backend independently of credentials. Password fields never restore plaintext keys or mirror them into localStorage. HTML placement, callbacks and backend consent are tested. |
| AUD-381 | Fixed in current source | Search `playlists` filter only renders actual `type === 'playlist'` provider results; track rows are not converted to fabricated playlist cards. |
| AUD-391 | Fixed | Settings secrets are excluded from localStorage mirrors; legacy cached auth/Last.fm fields are removed and sanitized. `tests/test_settings_controls_ui.py` verifies secret settings still go through the backend without appearing in localStorage. |
| AUD-400 | Fixed | Bundled Noto Sans Cyrillic fallback is declared with Cyrillic unicode ranges; font assets and OFL license are present. CSS wiring tests verify the local assets. |
| AUD-401 | Fixed | The duplicate dark palette override was removed from `home-refresh.css`; `themes.css` owns the dark palette. |
| AUD-402 | Fixed | The 761–900px player breakpoint overrides now live after the later component base rule and are exercised by CSS wiring checks. |
| AUD-411 | Fixed | `parseKeyEventCombo()` ignores modifier-only keydowns, leaving the chord recorder active until a second key is pressed. |
| AUD-416 | Fixed | Home feed calls carry generation-scoped request IDs; stale event payloads are ignored. Current responses unwrap `tracks`/`artists`. |
| AUD-432 | Fixed | Settings exposes a re-entry button for the onboarding wizard. |
| AUD-433 | Fixed in current source | Backend completion is authoritative; legacy local completion markers are migrated only after a successful backend write and are removed after canonical completion. |
| AUD-523 | Frontend portion fixed | Provider error payloads for popular, recommendations, artists, releases, and mixes now show a retry control instead of rendering an outage as an empty result. Backend error propagation/cache behavior remains part of the service/API workstream. |

## Cross-layer UI integrations added

- Settings > Storage now has a dedicated folder import control with scan progress
  and completion feedback. It calls `import_music_folder()` and handles
  `scan_progress {current,total}` and `scan_complete {count}` events. The
  existing single-file import control remains separate.
- Settings > Storage has a separate, explicitly confirmed measured listening
  history action. It calls `clear_listening_history(confirmed=False)` and
  repeats with `confirmed=True` only if the API requests confirmation. The
  success event rotates `currentTrack.listening_session` in place so continued
  playback is counted in the fresh session without restarting audio.
- Mini-player transitions pass a request ID, wait for a matching
  `mini_player_toggled` completion when the API returns pending, ignore stale
  completions, and roll back the CSS state on failure or timeout.
- `events.js` forwards scan and history events to UI custom events and delegates
  mini-player state changes to the request-correlated handler.

These integrations are wired to the API contracts below. They were checked with
isolated frontend harnesses; a native picker and native window transition still
require a later GUI run, which was explicitly out of scope for this pass.

| Method / event | Expected payload |
|---|---|
| `import_music_folder()` | `{success, pending, path}` or `{success, count}`; cancellation may return `{cancelled: true}` |
| `scan_progress` | `{current, total}` |
| `scan_complete` | `{count}` |
| `clear_listening_history(confirmed=False/True)` | `{success, confirmation_required?}` |
| `listening_history_cleared` | Event after successful clear |
| `toggle_mini_player(target, request_id)` | Immediate `{success, pending: true, is_mini, request_id}` followed by `mini_player_toggled {request_id, success, is_mini}` |

## Verification

Command run from the repository root, using the required Windows interpreter:

```powershell
& ".venv_win\Scripts\python.exe" -m pytest tests/test_storage_actions_ui.py tests/test_mini_player_toggle_ui.py tests/test_recommendation_ui.py tests/test_frontend_css_wiring.py tests/test_onboarding_ui.py tests/test_settings_controls_ui.py tests/test_frontend_js.py tests/test_feature_controls_ui.py tests/test_visual_effects_lifecycle.py tests/test_sidebar_rail.py tests/test_player_layout_geometry.py tests/test_player_recovery_transitions.py tests/test_player_resources.py tests/test_queue.py tests/test_search_discovery_ui.py tests/test_search_query_suggestions.py tests/test_library_view_ui.py tests/test_keybind_contracts.py tests/test_flow_ui.py tests/test_equalizer_controls_ui.py tests/test_profile_view_ui.py tests/test_catalog_lyrics_ui.py tests/test_smart_search_ui.py tests/test_recommendation_bridge.py tests/test_macos_ui.py tests/test_playback_latency_ui.py -q
```

Result: **218 passed**. Tests are isolated Node/pytest checks; no app or GUI was launched.
The native picker and native mini-window behavior remain unverified without GUI.

## Full frontend finding disposition (AUD-365–453)

Status is scoped to the Windows web UI. “Cross-layer” means the UI handling is
updated, while the parent remediation owns the Python contract. Deferred items
are intentionally visible so this report does not imply the entire audit is
closed.

| Audit ID(s) | Disposition | Current evidence / remaining owner |
|---|---|---|
| AUD-365 | Fixed | Removed the duplicate `track_downloaded` library refresh; debounced `library_updated` is the collection refresh path. |
| AUD-366 | Fixed | `main.js` merges into `window.NeDotify`, retaining utility exports and guards. |
| AUD-367, AUD-369 | Fixed UI | `utils.js` clears only rows matching database/provider identifiers; backend now needs to supply both identities on completion. |
| AUD-368 | Fixed UI | Fire-and-forget calls on the audited main path are awaited or caught; player recovery now reports rejected `play_track`. |
| AUD-370–373 | Cross-layer | Playback uses backend resolution and request generations; queue-row selection uses `entry_id` + `queue_revision` (`play_queue_track`) or `play_track(track)` without a queue snapshot. New collection starts still submit their fresh collection list. Backend queue/resolver behavior is owned by core. |
| AUD-374 | Fixed UI | Track, status, duration, position and animation timestamp now live in `player.js`'s `playbackState`; state transitions update that object, and the unread `targetPosMs` mirror was removed. Existing playback generation, queue version, recovery and resume guards remain in place. |
| AUD-375–379 | Fixed | Progress element lookups are cached behind frame guards; queue icon work is scoped; HLS detection inspects MIME/URL; `awaitBridge()` shares one bounded waiter; blur observer scans `#main-content`. |
| AUD-380 | Cross-layer | UI cancels the prior search on input and ignores stale results. Provider-task cancellation and worker-pool behavior remain in core/services. |
| AUD-381–387 | Fixed | Playlist filtering accepts actual playlist objects; artist cards populate and dispatch the search input; result covers use the shared lazy image helper; IDs are normalized for favorites; playlist mutations check boolean/error results; library teardown runs on empty results; failed lyric translation shows an error. |
| AUD-388 | Fixed | Added `get_canonical_artist_names` to the explicit bridge allowlist. It uses `services.artist_identity` and configured settings aliases; artist profile matching sends a batch of split display credits and compares returned canonical keys instead of reimplementing normalization in JavaScript. |
| AUD-389 | Fixed | Artist popular tracks sort by available play/view counts and render count badges only when counts exist. |
| AUD-390 | Fixed | Smart-playlist editing shows “Текущие правила”; selecting a preset after edits asks before replacing them. Verified by `tests/test_smart_search_ui.py`. |
| AUD-391–394 | Fixed | Secret settings are never mirrored into localStorage; save failures roll back; hotkey writes surface errors and reject duplicate bindings; color pickers preview on input and persist on change. |
| AUD-395 | Fixed | Removed the inert region selector from settings. |
| AUD-396 | Fixed | ReplayGain is guarded by the persisted `audio.volume_normalization` value. |
| AUD-397–402 | Fixed | Cache clearing requires confirmation; offline state and settings restore from the category tree; proxy credentials use a password field; Cyrillic fonts are bundled; palette and breakpoint cascade ownership were corrected. |
| AUD-403–404 | Fixed in the audited base/refresh boundary | See `WINDOWS_CSS.md`: duplicate unconditional owners were removed; 218 conditional and two state overrides are explicitly inventoried and guarded against drift. Semantic/blur/performance tokens have one owner. Other style/theme overrides remain intentional layers. |
| AUD-405 | Tooling scope | Visual-guard empty-baseline behavior belongs to `tools/visual_guard`; this UI report does not claim pixel-baseline coverage. |
| AUD-406 | Fixed in source | Thirteen shared sheets remain eager; twelve view/macOS packs use a tested loader that preserves authored cascade slots and waits before showing the destination view. See `WINDOWS_CSS.md`. |
| AUD-407 | Fixed for audited large surfaces | Shared/lyrics/macOS blur caps at 16px; slider and persisted-value normalization match the cap. See `WINDOWS_CSS.md`. No native rendering was inspected. |
| AUD-408 | Fixed | Removed the full-viewport `blur(8px)` filter from the particle canvas container. |
| AUD-409, AUD-440 | Fixed | Theme cards use the 17 purpose-built `assets/theme-previews/*.png` files; the local background catalog now uses WebP for full-size theme backgrounds. |
| AUD-410–416 | Fixed | Hotkey conflicts and modifier capture are handled; key migration and `/` use physical `code`; album year is escaped; provider chunks append in batches; home feeds are generation/request-ID scoped. |
| AUD-417 | Fixed UI | `home.js` now shares `createFeedTile` for common feed-card structure and `createFeedCard` for track playback across history, popular/recommendation feeds, authentic tracks and top tracks. Playlist and artist tiles use the shared shell, and artist names resolve through the same click handler. Custom playlist artwork retains its specialized cover treatment. |
| AUD-418–430 | Fixed | Image error handling is delegated; session storage is guarded; settings view transitions, context-menu cleanup, debug serialization, AudioContext recovery/resume, seeking, playback errors, EQ mode, stable queue identifiers, queue errors and teardown have explicit handling. |
| AUD-431 | Fixed UI | UNC paths are rejected by the player URL normalizer; local paths still route through the authenticated loopback stream bridge. |
| AUD-432–433 | Fixed | Onboarding can be re-entered; the backend is authoritative and legacy completion markers are migrated/removed. |
| AUD-434–436 | Fixed UI | Profile comparison awaits `awaitBridge()` and validates the API result. Settings search debounces input and builds a cached index of panel, section and row text once; keystrokes filter that index and update only the settings root. Child-list changes invalidate the index. |
| AUD-437–439 | Fixed | Focus color is consumed by focus rings; unused performance CSS variables were removed; font families are self-hosted. |
| AUD-441 | Fixed | `css/styles.css` and the `index.html` stylesheet comment now describe the actual loader relationship and current view/macOS layers. |
| AUD-442–444 | Fixed | macOS library artwork resolves inside its pack; duplicate theme data was removed; the orphan `.particle` selector was removed. |
| AUD-445–446 | Cross-layer fixed | UI reports media-session playback state; unused position/settings echoes were removed by core while position persistence stays one-way. |
| AUD-447–449 | Fixed | Paused visualizer draws one idle frame then parks; particle canvas is `aria-hidden`; particle count scales with viewport area and DPR. |
| AUD-450 | Cross-layer fixed | Removed the no-op UI handler; core removed the unused `setting_changed` emission. |
| AUD-451–453 | Cross-layer fixed | Orbit glow stops in mini mode; mini-player CSS waits for matching native completion; queue end stops audio and invalidates pending playback work. |

## P1 and cross-module cross-check

| Finding | Frontend disposition | Remaining boundary |
|---|---|---|
| AUD-006 | Fixed | Volume, shuffle and repeat read category-scoped backend settings. |
| AUD-009 / X-07 | Fixed | Bridge events queue before UI initialization and flush when the dispatcher is ready. |
| AUD-010 | Cross-layer fixed | Managed cover/avatar `<img>` URLs now use same-origin read-only `/api/cover` and `/api/avatar` routes without proxy bearer tokens, including before proxy startup. WebView bridge-event diagnostics log only method and structured code; core/proxy owns path containment and route-origin checks. |
| AUD-015 | Covered in frontend tests | Player/flow regression checks are isolated; test-suite quality and CI scope remain in the shared test/CI remediation. |
| AUD-019 | Frontend duplicate refresh fixed | Database pagination/projection remains core/database ownership. |
| AUD-133 | Cross-layer fixed | The `api_error` event logs only method/code; the rejected bridge Promise and its caller own user-facing feedback, avoiding a second toast/panel for the same failure. Core owns the sanitized `_error_payload` boundary. |
| AUD-154 | Cross-layer fixed | The library overview requests 8 recent rows with an authoritative total; “Вся музыка” requests 200-row pages and exposes further pages through a generation-checked, deduplicating “Показать ещё” control. Legacy array responses still work. Core/database own the bounded query and total count. `tests/test_smart_search_ui.py` covers 450 rows, exact total, deduplication, and legacy page arrays. |
| X-01 | Frontend duplicate-resolution trigger removed | Resolver single-flight and negative-cache behavior is core/services ownership. |
| X-02 | Frontend fixed | Queue snapshots are no longer passed when selecting existing queue rows; core owns the canonical queue. |
| X-03 | UI settings accessors fixed | Backend settings shape/default contract remains core settings/API ownership. |
| X-04 | UI matching fixed | Atomic download row creation and event identities remain API/downloader ownership. |
| X-05 | No UI policy | One cache quota/cleanup owner remains core/cache ownership. |
| X-06 | UI state restore fixed | Offline enforcement at network choke points remains core/proxy/services ownership. |
| X-07 | Fixed | See AUD-009. |
| X-08 | No UI surface | Loopback server origin/port authentication is core/app ownership. |
| X-09 | Frontend retries/errors are surfaced | Canonical lyric identity/cache and provider fan-out remain services ownership. |
| X-10 | UI accepts backend track identities | Canonical provider identity and matching remain services ownership. |
| X-11 | Setting gate fixed in UI | LUFS scanning/downloaded-file semantics remain services/database ownership. |
| X-12 | No UI cache owner | Stream cache invalidation remains resolver/service ownership. |
| X-13 | UI displays API results | Listening-time definition and aggregation remain database/service ownership. |
| X-14 | No UI pool policy | Reserved playback capacity remains provider-service ownership. |
| X-15 | No caller found | Path containment and transaction semantics remain core API/database ownership. |

## Additional integrations and appearance assets

- Settings now exposes folder import with progress/completion, confirmed
  listening-history clearing, native mini-player completion handling, and a
  request-correlated Zapret update check. Zapret check feedback is dispatched
  from `zapret_update_checked`; the existing Update button remains separate.
- The saved session restore path honors `track_changed.autoplay` on every
  notification. Restore position is read from `restore_position_sec` in
  seconds and applied when media metadata is ready; explicit play uses
  `autoplay: true`. The legacy `session_autoplay` event no longer uses fixed
  timers.
- Full-size theme backgrounds resolve to the 27 `photo-*.webp` derivatives.
  Existing persisted catalog `.jpg`/`.jpeg` paths migrate in memory to their
  matching WebP. The installer spec excludes original wallpaper JPEGs; it
  retains the WebPs, logo, preview PNGs and macOS assets. `SOURCES.json` is a
  source-tree provenance manifest and is not needed by runtime code.
- The user's requested sidebar/player-bar transparency and waveform-progress
  rendering remain in the existing UI CSS/player canvas code; this pass made
  no GUI changes to their appearance and, per instruction, did not launch the
  app for visual inspection.

## Current verification status

Latest targeted run after the AUD-374/388/417/434–436 changes: **86 passed**.
It covers artist identity bridge and UI matching, indexed settings search,
player recovery/state, HLS partial harnesses, catalogue UI, frontend wiring,
macOS, recommendations and playback latency. The prior broader isolated run
recorded **222 passed** before this final scoped refactor. No app or GUI was
started; the full suite is queued with the parent agent.
