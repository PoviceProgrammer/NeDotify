# NeDotify (Windows desktop) — Remediation Plan

**Companion to:** `docs/audits/FULL_PROJECT_AUDIT.md`
**Date:** 2026-10-20
**Scope:** the Windows desktop product only (`main.py`, `core/`, `services/`, `audio/`, `utils/`, `ui/web_new_v2/`, `tests/`, `tools/`). The `android/` port is **out of scope**.
**Status of this document:** a plan only. **No code was changed during the audit.** Nothing in this file has been applied.

---

## 0. How to use this plan

Every task below has a stable ID (`R-###`), a priority, an audit finding it closes, the exact files to touch, the acceptance criterion, and the risks. Tasks are grouped into **waves** that are ordered by dependency, not by severity alone.

**Two rules before you start:**

1. **Do not merge anything until W-0 is complete.** The test suite is currently **red** (11 failures) and the isolation is **opt-in**, so the suite has already written test artefacts into the user's real `~/.nedotify/downloads/`. Until both are fixed, "the tests pass" is not evidence and running the suite causes damage.
2. **Commit the working tree.** `git status` shows **123 untracked / 36 deleted / 70 modified** entries, including **17 production modules** and **53 test files**. The git history does not represent the shipped product; there is no bisect, no rollback and no reviewable diff for roughly a third of the runtime code. This is task `R-000` and it should land first if the team agrees.

**Legend:** `P0` critical · `P1` high · `P2` medium · `P3` low · **AUD-*** = the audit finding ID (`FULL_PROJECT_AUDIT.md` §4/§5) · **ARCH-*** = an architecture improvement (`FULL_PROJECT_AUDIT.md` §8).

---

## W-0 — Unblock the quality gate (do this first, nothing else)

### R-000 · P1 · Commit the working tree
- **Closes:** `FULL_PROJECT_AUDIT.md` §9.5 (123 untracked / 36 deleted / 70 modified).
- **Action:** decide, per file, whether it belongs to the shipped product. Commit the 17 untracked production modules (`core/download_store.py`, `core/download_transfer.py`, `core/listening.py`, `core/offline.py`, `core/playback_recovery.py`, `core/ui_assets.py`, `core/user_errors.py`, `services/artist_identity.py`, `services/catalog_service.py`, `services/itunes_gateway.py`, `services/listening_comparison.py`, `services/lyrics_cache.py`, `services/lyrics_lookup.py`, `services/music_matching.py`, `services/smart_playlists.py`, `utils/search_query.py`, `utils/stream_urls.py`) and the 53 untracked test files. Do **not** commit `android/` in the Windows repo — it has its own audit and its own history.
- **Acceptance:** `git ls-files core services audio utils tests` lists every module that `main.py` imports; `git status --porcelain` shows only intentional changes.
- **Risk:** none — it changes no behaviour.

### R-001 · P1 · Restore the green test suite (one root cause)
- **Closes:** **AUD-015** (P1) — 11 failures, one root cause.
- **Files:** `ui/web_new_v2/js/player.js` (lines 2244 and 2358), the DOM stub in `tests/test_flow_ui.py` and `tests/test_player_resources.py`.
- **Action:** read `document.documentElement.dataset.progressStyle` as `document.documentElement.dataset?.progressStyle` at both sites (line 2513 in the same file already uses `?.`). Then add `dataset: {}` to the Node DOM stub so the harness models the real DOM.
- **Acceptance:** `& ".venv_win\Scripts\python.exe" -m pytest -q -p no:cacheprovider` → **0 failed**; the 1506 tests are collected.
- **Risk:** none. In a browser `dataset` always exists, so this is a robustness fix, not a behaviour change.

### R-002 · P1 · Make the test isolation unconditional
- **Closes:** **AUD-455** (P1) — the suite writes `stub_*.mp3` / `gated_*.mp3` into the user's real `~/.nedotify/downloads/`.
- **Files:** `tests/conftest.py` (the `redirect_home` fixture at ~L170-176 is opt-in and is not requested by the downloader/api/core fixtures), `core/api.py:2700`, `core/downloader.py:789-790`.
- **Action:** make `redirect_home` an **autouse session-scoped** fixture that points `HOME`/`USERPROFILE` at a `tmp_path` **before** any module resolves `~`. Add a guard test that fails if any write escapes the sandbox.
- **Acceptance:** a full pytest run creates **no** file under the real `~/.nedotify/`; the existing `stub_*.mp3` artefacts are removed once.
- **Risk:** a test that *relied* on the real profile would now fail — that is the point, but check `tests/test_auto_save_favorites.py:87-96` first.

### R-003 · P1 · Fix the two governance checkers and wire them into CI
- **Closes:** **AUD-459**, **AUD-460** (P1).
- **Files:** `tools/check_lock_nesting.py` (L11 — `ROOT` points at `tools/`), `tools/check_shadow_imports.py` (L49-56 — `ast.walk` re-descends into nested bodies), `.github/workflows/ci.yml`.
- **Action:** set `ROOT` to the repository root; require a real `threading.Lock`/`RLock` (so `self.conn`, a SQLite connection used as a transaction CM, is not flagged); make the shadow-import walk scope-aware; add both to CI.
- **Acceptance:** `python tools/check_lock_nesting.py` scans `core/`, `services/`, `audio/`, `utils/`, `main.py`; `python tools/check_shadow_imports.py` exits 0 on the current tree (both current hits are false positives); CI runs both.
- **Risk:** low — the checkers currently find only false positives.

### R-004 · P1 · Move the Android gate out of the Windows suite
- **Closes:** **AUD-457** (P1) — `tests/test_android_source_gates.py` hard-fails (8 failures in 2.41 s) when `android/` is absent.
- **Files:** `tests/test_android_source_gates.py`.
- **Action:** move it into the `android/` tree, or skip it when the directory is absent (`pytest.mark.skipif(not (ROOT/"android").exists())`).
- **Acceptance:** the Windows suite is green with `android/` absent.
- **Risk:** none.

---

## W-1 — The five P1s a user can hit in one session

### R-010 · P0 · Delete the invalid `webview.settings` assignment
- **Closes:** **AUD-001** (P0).
- **Files:** `main.py:24-30`.
- **Action:** delete line 29 (`webview.settings['WEBVIEW2_RUNTIME_PATH'] = _PINNED_WEBVIEW2`). Keep line 30 (`os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER']`), which is the mechanism pywebview actually honours. If the runtime path is genuinely required, set the environment variable **before** importing pywebview and assert the key exists before assigning it.
- **Acceptance:** `python -c "import webview; webview.settings['WEBVIEW2_RUNTIME_PATH']='X'"` is no longer reachable from the app's import path; the app starts on a machine where the pinned WebView2 is installed.
- **Risk:** none — the line currently always raises on the affected path.
- **Note:** `webview.settings` is an `ImmutableDict`; its six valid keys are `ALLOW_DOWNLOADS`, `ALLOW_FILE_URLS`, `IGNORE_SSL_ERRORS`, `OPEN_DEVTOOLS_IN_DEBUG`, `OPEN_EXTERNAL_LINKS_IN_BROWSER`, `REMOTE_DEBUGGING_PORT`.

### R-011 · P1 · Start the tray — and make it stoppable
- **Closes:** **AUD-003** (P1) + **AUD-129/130** (P2).
- **Files:** `core/api.py:538-597` (the `return False` at 572 makes 574-597 dead), `core/tray.py:13-19` (`from pystray import … Separator` fails on 0.19.5), `requirements.txt:18`.
- **Action:**
  1. Move `self._tray.start()` and the `_set_icon` block **above** the Snap Layouts block (they are independent of the window handle) or into their own method called from `set_window()`.
  2. Raise the `pystray` floor to a version that exports `Separator` (`pystray.Menu.SEPARATOR` exists in 0.19.x — or use that constant instead of the import).
  3. Make `TrayIcon.stop()` work before pystray marks the icon ready (track readiness, not `_is_running`).
  4. Confine the native `HMENU` rebuild to the tray thread (queue the hand-off) — `core/tray.py:158-161`.
- **Acceptance:** a tray icon appears; `tray.icon` is not `None`; ✕ hides to the tray instead of quitting; no icon remains after exit; the `minimize_to_tray` setting now matches the behaviour.
- **Risk:** **medium** — landing this exposes the stop-path bug and the 1 Hz-throttle state bug. Land R-011 and R-012 together.

### R-012 · P1 · One authoritative shutdown path
- **Closes:** **AUD-011** (P1), AUD-123, AUD-163, AUD-502, AUD-512, and the resource-leak family.
- **Files:** `main.py:406-408`, `:506-539`, `:557-580`; `core/app.py:508-586`; `core/api.py:446-459`.
- **Action:**
  1. Introduce `AppCore.shutdown(reason)` running a **declared, ordered** teardown list: proxy → downloader → settings writer → watchdog → LUFS pool → tray → Discord → zapret → bridge executors → thread pools → **DB last**.
  2. Call it from `on_closed`, from the watchdog branch (`main.py:506-539`, which currently skips `AppApi.cleanup()` entirely) and from a `try/finally` around `webview.start()`.
  3. Release the **instance mutex last**, not in `on_closed` (pywebview fires `closed` before `webview.start()` returns).
  4. Save the session before the teardown, and also on minimise.
  5. Give `SettingsManager` a `close()` that stops the writer thread and joins it (it is currently never stopped).
  6. Add a `SettingsManager.close()` call to the teardown list so a post-close write cannot hit a closed DB.
- **Acceptance:** a single exit path; no resource survives it; `close()` → no tray icon, no bound proxy port, no writer thread; a relaunch during teardown does not start a second instance.
- **Risk:** **medium** — touches every exit path. Test the normal close, the watchdog restart, and a forced exception in `webview.start()`.

### R-013 · P1 · Fix the SSRF guard
- **Closes:** **AUD-004** (P1), **AUD-005** (P1), **AUD-352** (P3).
- **Files:** `core/api.py:133-195`; `utils/url_safety.py:13-37`; `core/proxy.py:23-24`.
- **Action:**
  1. **Fail closed** on a resolution failure (`verdict = False`), and **never cache** the exception-path verdict.
  2. Replace the four-prefix string fallback with a full `ipaddress` check.
  3. Resolve and **validate the address**, then connect to it (preserving the `Host` header and TLS SNI so CDNs still work) — or re-validate the peer address after connect.
  4. Collapse the two guards into one implementation in `utils/url_safety.py` and have `core/api.py` and `core/proxy.py` both import it (this also removes the `core.proxy → core.api → webview` layering inversion).
  5. Reduce the DNS memo TTL and add a **negative** TTL so a transient outage does not blackhole a host for two minutes.
- **Acceptance:** a DNS failure makes `_is_ssrf_safe_url` return `False`; the cache never stores "safe" from the exception path; `169.254.169.254` is refused with a pinned resolver; one SSRF implementation exists.
- **Risk:** **medium** — IP pinning can break SNI/virtual-host routing for CDN-backed providers. Roll out per provider (YouTube/SoundCloud first) and keep the hostname path as a fallback behind a flag.

### R-014 · P1 · Fix the download identity
- **Closes:** **AUD-282** (P2), **X-04** (P1).
- **Files:** `core/api.py:2294-2360`; `core/database.py:1278-1282`; `core/downloader.py:819`; `js/utils.js:977-1017`.
- **Action:**
  1. Distinguish the provider id from the database row id in `download_track`; **always** create the row (or resolve an existing one) before enqueueing.
  2. Make `mark_track_downloaded` a single write, retried, with the error contained (do not repeat the identical failing UPDATE).
  3. Emit `download_complete` with both the row id and the provider `source_id`, and make the frontend matcher accept either.
  4. Emit a `download_failed` event when the queue refuses the request (today it returns `False` silently → the spinner never clears) — **AUD-283**.
- **Acceptance:** downloading a track from Search creates exactly one `tracks` row, marks it `is_downloaded = 1`, clears the spinner and appears in the Library; the file is not an orphan.
- **Risk:** low, but it changes a bridge payload — bump the frontend matcher accordingly and keep the old field for compatibility.

### R-015 · P1 · Bound the fixed webview port
- **Closes:** **AUD-002** (P1), **X-08** (P1), AUD-100 (the mutex squat).
- **Files:** `main.py:14`, `:555`; `main.py:260` (the mutex is `Local\`-scoped while the port is per-machine — AUD-502).
- **Action:** pass an explicit random `http_port` and **assert the bind succeeded** (pywebview sets `server.running = True` without checking). Narrow `Access-Control-Allow-Origin` from `*` to the app's own origin. Use a per-user mutex namespace.
- **Acceptance:** two instances cannot collide on a port; a squatter cannot brick the app; the UI's origin is the only allowed CORS origin.
- **Risk:** low — the frontend addresses the proxy port (already dynamic), not the webview port.

---

## W-2 — Contract seams (each task removes a family of defects)

### R-020 · P1 · One settings schema
- **Closes:** **X-03** (P1), AUD-366, AUD-371, AUD-391, AUD-398, AUD-101, AUD-114.
- **Files:** `core/settings.py:52-287`; `core/api.py:239-269`, `:2922-2938`, `:2940-2953`; `ui/web_new_v2/js/player.js:1973-1992`; `js/utils.js:526-530`, `:608`; `js/feature-controls.js:112`; `js/settings.js:1039-1041`.
- **Action:**
  1. Derive the bridge transport from `DEFAULT_SETTINGS` — stop hard-coding the category list at `core/api.py:2929` (it omits `network` and `subscription` and lists four categories that do not exist).
  2. Fix the access depth in `js/player.js`: `settings.session.shuffle` / `settings.session.repeat` / `settings.audio.volume`.
  3. Never mirror a secret into `localStorage` — add a `secret` marker to the schema and skip the mirror for it.
  4. Mask `auth.proxy_url` and `auth.lastfm_api_key` in the schema, not in a two-entry tuple.
  5. Delete the second `get_setting`/`set_setting` pair (`core/api.py:1853-1900`) and route every caller through `save_setting` — **AUD-017** (P1).
  6. Add a contract test that asserts every JS settings accessor resolves to a real key.
- **Acceptance:** the volume survives a restart; the repeat button reflects the real state; the offline toggle reflects the real state; no secret appears in `localStorage`; `set_setting` no longer exists on the bridge.
- **Risk:** medium — the hotkey mirror (contract #5) must keep passing (`tests/test_keybind_contracts.py`).

### R-021 · P1 · One resolution front door + a playback epoch
- **Closes:** **X-01** (P1), AUD-125, AUD-164, AUD-165, AUD-166, AUD-167, AUD-167, **AUD-165**.
- **Files:** `core/resolver.py:165-230`; `core/api.py:1608-1744`; `core/app.py:296-506`; `audio/engine.py:121-151`; `core/playback_recovery.py`.
- **Action:**
  1. Route the user-facing play path through `StreamResolver.resolve()` instead of calling the provider directly.
  2. Add a monotonic `playback_epoch` captured with the request; a resolution callback may only update the current entry, never re-select.
  3. Make the single-flight waiter budget **≥** the owner's cascade budget (12 s vs ~30 s today) and add an owner watchdog so a hung provider cannot pin `_inflight` forever.
  4. Wire `mark_unavailable` with a PERMANENT/TRANSIENT verdict so a dead track is not re-resolved through the whole cascade on every click.
  5. Cancel superseded resolutions instead of abandoning them.
- **Acceptance:** rapid clicks play the **last** requested track; a dead track is not re-resolved; the proxy's 403/410 self-heal still works.
- **Risk:** medium — `resolver.resolve` has a 12 s timeout and a callback shape; adapt carefully.

### R-022 · P1 · One cache owner
- **Closes:** **X-05** (P1), AUD-292, AUD-293, AUD-357.
- **Files:** `core/api.py:3595-3638` (`_clean_stream_cache`); `utils/cache_manager.py:171-271` (`purge_stream_cache`); `core/database.py:2134-2242`.
- **Action:** delete `_clean_stream_cache` and let `CacheManager` own the policy (the user's quota, the favourite/downloaded protection, the DB sync). Make the quota accounting consistent (it currently counts covers+temp+streams but purges only `streams/` — **AUD-305**). Add an index on `stream_cache.cached_file_path`.
- **Acceptance:** a favourite's cached audio survives a purge; the user's quota is honoured; no `stream_cache` row points at a missing file.
- **Risk:** low.

### R-023 · P1 · One network/offline policy
- **Closes:** **X-06** (P1), AUD-020, AUD-179, AUD-232, AUD-262, AUD-266.
- **Files:** `core/offline.py`; `core/api.py:461-512`; `core/proxy.py:814-1016`; `core/resolver.py`; `services/lyrics_service.py:243-272`; `services/soundcloud_service.py:1023-1032`.
- **Action:**
  1. Introduce a `NetworkPolicy` consulted at the two real choke points — the proxy's request builder and `StreamResolver.resolve`.
  2. Hoist the proxy's offline guard so the `/?url=` branch (the production CDN path) is covered, not only `/api/stream`.
  3. Invert the bridge interception list to a per-method capability attribute with **default DENY**.
  4. Add `get_lyrics` and `get_waveform` to the policy; add an offline check to `translate_lyrics`.
- **Acceptance:** with offline ON, **no** outbound request is made from any path (enumerate them and assert); offline mode is visible in the UI.
- **Risk:** medium — inverting the list will block methods that are currently implicitly allowed; audit each.

### R-024 · P1 · A frontend readiness handshake
- **Closes:** **X-07** (P1), **AUD-009** (P1), AUD-369.
- **Files:** `main.py:389-402`; `js/events.js:46-73`; `js/main.js:352-372`, `:516-528`.
- **Action:** the frontend signals readiness (`ui_ready()`); the backend emits `track_changed` / `session_autoplay` **after** that signal (or the frontend pulls `get_state()` on boot). Buffer the events that arrive early.
- **Acceptance:** on a cold start with a saved session, the restored track and its position appear in the player without a reload.
- **Risk:** low.

### R-025 · P1 · One window-state owner and one coordinate space
- **Closes:** **AUD-012** (P1), AUD-101-106, AUD-451, AUD-452.
- **Files:** `core/api.py:538-1160`; `core/snap_layouts.py`; `js/main.js:175-205`.
- **Action:** read `native.scale_factor` (not the non-existent `native._scale`); define **one** coordinate space (physical Win32 pixels) and convert exactly once at pywebview's `move()` boundary; introduce a `WindowState` enum owning `_is_mini_active` / `_is_maximized` / `_last_geometry` / `_saved_mini_pos` and both CSS classes; replace the thread-per-deferred-op with one serialised worker with a generation counter; make the deferred ops report completion so the frontend's rollback branch is reachable.
- **Acceptance:** on a 125 % / 150 % display the mini player stays on screen and the main window returns to its exact previous position; a fast mini toggle cannot invert.
- **Risk:** medium — the geometry is stored in the old space; migrate or discard the saved preference.

---

## W-3 — Correctness of the write paths (data integrity)

### R-030 · P1 · Atomic tag writing
- **Closes:** **AUD-301** (P1), AUD-302, AUD-303.
- **Files:** `utils/tag_parser.py:249-302`, `:372-397`.
- **Action:** write to a temp file in the **same directory** and `os.replace` it into place; keep a restorable backup next to the file until the write succeeds; handle `.wav`/`.aac`/`.wma` (mutagen's `easy=True` only normalises MP3/MP4/TrueAudio).
- **Acceptance:** killing the process mid-write leaves the original file intact and byte-identical.
- **Risk:** **high** — this is the user's only copy of their music. Test on FLAC, MP3, OGG, MP4 and WAV.

### R-031 · P1 · Root-confine the destructive storage operations
- **Closes:** **AUD-018** (P1), **X-15** (P2), AUD-293, AUD-132.
- **Files:** `core/api.py:3105-3154`; `core/database.py:1122-1127`.
- **Action:** restrict `_delete_downloaded_files` to paths that canonicalise **inside** `~/.nedotify/downloads` (reuse the `is_relative_to` + `realpath` pattern from `core/proxy.py`); delete the DB rows for the files that were actually removed in the same transaction; require an explicit confirmation for the `"all"` variant; show what will be deleted before doing it.
- **Acceptance:** a locally imported track outside `~/.nedotify` is never deleted; after a clear, no row points at a missing file; the auto-download path can re-fetch a cleared track.
- **Risk:** **high** — the blast radius of a mistake is the user's music.

### R-032 · P1 · Fix the zapret update path
- **Closes:** **AUD-016** (P1), AUD-310, AUD-311, AUD-314, AUD-315, AUD-316.
- **Files:** `services/zapret_service.py:44-51`, `:317`, `:740-751`, `:833-837`, `:861-862`, `:960`, `:1262-1290`; `core/api.py:3860-3874`.
- **Action:** refuse to install without a trusted digest (pin the URL **and** the hash, or publish a signed manifest); never treat an empty expected hash as "verified"; fix the `_update_lock` self-deadlock (`RLock` or restructure); always replace the binary (the extraction guard currently skips any valid existing file); validate the candidate path at the **use** site, not only at the user-input site; install to a protected location rather than `~/.nedotify/zapret`; cap the download size; use `cmd.exe` with `/d` and an absolute path.
- **Acceptance:** an unpinned release cannot be installed; the update actually replaces `winws.exe`; the update thread always returns; the elevated binary does not live in a user-writable directory.
- **Risk:** **high** — an elevated, network-supplied binary.

### R-033 · P1 · Stop yt-dlp writing the browser cookie jar
- **Closes:** **AUD-224** (P1), AUD-225 (P2).
- **Files:** `services/youtube_service.py:352-358`, `:846-857`, `:308`; `services/soundcloud_service.py:247`, `:276`; `services/vk_service.py:63`; `utils/cache_manager.py:352`.
- **Action:** pop `cookiefile` from the options before `close()` (or never set both `cookiefile` and `cookiesfrombrowser`); remove `nocheckcertificate: True` from every provider so TLS verification covers the **media bytes**.
- **Acceptance:** after a gated extraction, `cookies.txt` contains only the cookies it was given; TLS verification is on for the media path.
- **Risk:** medium — removing `nocheckcertificate` may break users behind TLS-intercepting middleboxes; provide an explicit opt-in instead.

### R-034 · P2 · Repair the duplicate-merge and the playlist-origin flag
- **Closes:** AUD-151, AUD-152, AUD-153, AUD-194.
- **Files:** `core/database.py:863-869`, `:905-913`, `:961-965`, `:1001-1005`, `:1908-1924`.
- **Action:** merge into a **live** row (not a plan-time snapshot) so `play_count` / `is_favorite` / `last_played` accumulate across a 3+ member partition; fix the restore predicate; add an `is_system` column (with a migration) instead of matching playlists by name.
- **Acceptance:** a 3-row duplicate partition merges to the correct totals; the restore path can actually undo a merge; a user playlist named "Локальные" is never deleted.
- **Risk:** medium — the migration runs on the user's live database. Take a snapshot first (the code already has `VACUUM INTO`).

### R-035 · P2 · Database indexes, projections and connection hygiene
- **Closes:** AUD-154…AUD-200 (the DB group).
- **Files:** `core/database.py:1184-1209`, `:1465`, `:1599-1624`, `:1723-1834`, `:179-201`, `:2028-2134`, `:2440-2489`; `core/api.py:2267-2271`, `:2727-2731`.
- **Action:** add the missing indexes (`LOWER(artist)`, `LOWER(album)`, missing-cover, `stream_cache.cached_file_path`); project only the columns the UI reads instead of `SELECT *`; add `limit`/`offset` to the bridge listing methods; evict dead-thread connections from `_all_conns`; make `close()` idempotent and bound the WAL checkpoint; store typed settings values and distinguish NULL from `""`.
- **Acceptance:** `get_library` is paged; `get_wrapped_stats` is one aggregate; a burst of bridge calls does not grow the connection registry; the shutdown does not block for 30 s.
- **Risk:** low.

### R-036 · P2 · Downloader correctness
- **Closes:** AUD-162, AUD-169…AUD-177, AUD-207, AUD-208, AUD-209.
- **Files:** `core/downloader.py:37-52`, `:108-112`, `:272-284`, `:356-410`, `:587-608`, `:612-627`, `:798-800`, `:884-909`; `core/download_transfer.py:100-119`.
- **Action:** always account for a paused batch item (`_on_batch_task_done`); invert the retryable classification (404 is not retryable, 500 is); classify the transient error **before** the provider masks it; remove the orphan file on abort; require a `Content-Length` or verify the stream; strengthen the integrity gate beyond "extension + 4 KiB"; validate the `track_id` type; make the cancel/worker write a single compare-and-set transition.
- **Acceptance:** a batch always terminates; a 404 fails fast; a truncated body is rejected; a cancelled download leaves nothing on disk.
- **Risk:** medium.

---

## W-4 — Performance

| ID | Pri | Action | Closes |
|---|---|---|---|
| R-040 | P2 | `services/listening_comparison.py`: materialise the pre-window artist set once (CTE) instead of a correlated `NOT EXISTS` per row | AUD-259 (467 s → ~1 s at 120 k rows) |
| R-041 | P2 | `services/lufs_scanner.py`: stream the decode in chunks; honour the real channel count; reject non-finite LUFS; select on "has a local file", not `source='local'` | AUD-251…AUD-257, X-11 |
| R-042 | P1 | Paginate `get_library` / `get_all_tracks`; project the needed columns; coalesce the download-driven refresh into one | AUD-019, AUD-154, AUD-365 |
| R-043 | P2 | `core/proxy.py`: a pooled opener, a socket timeout, a request-thread semaphore; refuse UNC paths before the filesystem call | AUD-180, AUD-184, AUD-185, AUD-186 |
| R-044 | P2 | Write-behind accumulation for the listening telemetry (the `core/settings.py` pattern); make `report_position` one-way | AUD-441, X-13 (−3 MB WAL/h, −720 UI-thread hops/h) |
| R-045 | P2 | `services/taste_profile.py`: drop the connection from the revision key; cache the alias table per settings revision | AUD-270, AUD-271 |
| R-046 | P2 | The CSS: collapse 25 blocking sheets to 4; migrate the 69 conflicting selectors; drop the canvas blur; ship a Cyrillic font subset | AUD-400…AUD-409 |
| R-047 | P3 | `core/api.py`: `_emit` becomes one long-lived worker with a bounded FIFO queue; `queue_updated` ships a versioned delta | AUD-110, AUD-375, X-02 |

---

## W-5 — Structural work

| ID | Pri | Action | Closes |
|---|---|---|---|
| R-050 | P2 | Split `AppApi` into per-capability façades; publish only the façade's public methods; give the bridge an allow-list | AUD-107, AUD-138, §8.2 |
| R-051 | P2 | Add an injection seam to `AppCore` and an injectable HTTP client to `BaseMusicService`; write one real-wiring test | AUD-454, AUD-456, §8.3 |
| R-052 | P2 | One shared DOM stub (`tests/jsdom.py`) for every JS test; add the missing frontend tests | AUD-479, AUD-015 |
| R-053 | P2 | A provider interface + registry; one cache-key namespace per provider; one failure classifier; rename the "Spotify" provider (it is iTunes) or implement the real API | AUD-211…AUD-249, AUD-290, X-10 |
| R-054 | P2 | A retention + erasure policy for the listening history; a `clear_history` bridge method | X-13, §7.1 privacy |
| R-055 | P2 | Tooling: visual-guard baselines + a machine manifest; bench scenarios for the play and download paths; a result envelope with a tree fingerprint; regenerate the stale artefacts | AUD-461…AUD-475, §8.7 |
| R-056 | P2 | CI: ruff + a type check + a coverage floor + a lockfile + `--strict-markers`; mark or delete the unused `network` marker | AUD-476, AUD-477, AUD-501, AUD-502 |
| R-057 | P2 | Packaging: ship `icon.ico`, the `curl_cffi` DLL and the `plugins` folder; a frozen-aware plugin path; prune 634 KB of dead imagery; convert the wallpapers to WebP; sign the installer | AUD-013, AUD-134, AUD-493…AUD-504 |
| R-058 | P3 | Frontend structure: split `player.js` (2 711 lines) and `settings.js` (3 388 lines); replace the `window.NeDotify` global with ES imports; one `createTrackElement`; a `js/bridge.js` façade | AUD-366, AUD-412, AUD-417, §8.4 |
| R-059 | P3 | Privacy: an opt-in for the automatic lyrics lookup; disclose the providers; a `settings.lyrics.enabled` switch | AUD-260, AUD-266 |
| R-060 | P3 | Correct the stale documentation: `css/styles.css` (the CSS architecture record), `AGENTS.md` contract #8 (the Yandex filename example), `pytest.ini` (the unused marker), `nedotify-test/SKILL.md` (the live-provider fiction) | AUD-440, AUD-441, AUD-476 |

---


---

## W-1b — The P1s raised by the integration reviewers

These eight (AUD-515…AUD-522 in FULL_PROJECT_AUDIT.md §4.1) were surfaced after the area reviews and cross-confirmed. They slot into the waves above.

| ID | Pri | Action | Closes | Wave |
|---|---|---|---|---|
| R-070 | P1 | Add a monotonic **playback epoch** to the resolution path: a resolution callback may only update the current entry, never re-select. Make the frontend start **one** chain per click (an explicit status: resolving\|ready\|failed instead of inferring "not started" from the absence of stream_url). | **AUD-515**, AUD-372, X-01 | W-2 |
| R-071 | P1 | Introduce a **playback command lock** around mutate → notify → emit in udio/engine.py, and an atomic PlaybackQueue.snapshot() so the index and the current track are read together. Stop reading queue._current_index from outside the class. | **AUD-516**, AUD-152, AUD-208 | W-2 |
| R-072 | P1 | Report a failed resolution on the **solo** play path (raise into the bridge's error envelope); today the click is silently ignored. | **AUD-517** | W-2 |
| R-073 | P1 | Give the stream cache **one** owner: the proxy's inline cache and cache.download_audio_stream currently write the same file concurrently, so every play downloads twice. | **AUD-518**, AUD-302, AUD-303 | W-2 |
| R-074 | P1 | Make cleanup() able to release the process: cooperative cancellation + a bounded join, a hard exit after the final flush, and add the **lyrics** pool to the teardown list (its shutdown_executor has no caller at all). | **AUD-519**, AUD-267, AUD-172 | W-1 |
| R-075 | P1 | Apply the duration tolerance to **plain** (unsynced) lyric hits, not only to synced ones — today a track with no artist is matched to a different song of a different length. | **AUD-520** | W-3 |
| R-076 | P1 | Re-arm the settings writer after a failed write (with an attempt budget and a back-off) and surface a failed flush to the bridge — today the bridge says "saved" and the value is lost. | **AUD-521** | W-2 |
| R-077 | P1 | Project the 
etwork category in get_settings() (derive the list from DEFAULT_SETTINGS), add a UI toggle and a boot-time get_offline_mode() call — today offline mode is invisible to the UI **and** the frontend keeps loading remote covers while offline. | **AUD-522**, AUD-020, AUD-398 | W-2 |

**Plus 15 promotions** (audited at P2, promoted to P1 after cross-review): AUD-169, AUD-170, AUD-172, AUD-224, AUD-228, AUD-232, AUD-235, AUD-259, AUD-286, AUD-290, AUD-301, AUD-302, AUD-303, AUD-381, AUD-411 — see FULL_PROJECT_AUDIT.md §4.2 for the reason and the §5 dossier for each.

**Final counts:** 1 × P0, 48 × P1, 254 × P2, 151 × P3 = **454 confirmed findings**, plus 15 cross-module and 9 architecture items.

## Appendix A — the findings index

The full finding list with `path:line`, evidence, cause, trigger, impact, reproduction and fix side-effects is in **`docs/audits/FULL_PROJECT_AUDIT.md`** §4 (P0/P1) and §5 (P2/P3). IDs are stable: `AUD-001`…`AUD-514`, plus `X-01`…`X-15` for the cross-module findings and `ARCH-1`…`ARCH-9` for the architecture improvements.

## Appendix B — where the evidence lives

Each reviewer's full report is **preserved in the repository** at `docs/audits/agents/<AREA>-<A|B>.md` (94 files, ~4.5 MB) with the complete 12-field dossier for every finding, next to 57 reviewer scratch repro scripts (`*.py`) that produced the measurements quoted throughout the report.

The coordinator's own verification commands and their raw output are in `FULL_PROJECT_AUDIT.md` §9.4 — in particular the executed proof of **AUD-001** (the `ImmutableDict` `KeyError`), **AUD-002** (the 42001 pin and the wildcard CORS), **AUD-003** (the unreachable tray start), **AUD-004** (the fail-open SSRF verdict) and **AUD-006** (the settings tree depth).

## Appendix C — the ten changes with the best return

If only ten things get done, do these:

1. `R-010` — delete `main.py:29` (**one line**, the P0).
2. `R-001` — make the suite green (**one line + a stub**, unblocks everything).
3. `R-002` — make the isolation unconditional (stops the suite damaging the user's library).
4. `R-011` — start the tray (the user-visible P1 everyone notices).
5. `R-012` — one shutdown path (closes the whole leak family).
6. `R-013` — fail the SSRF guard closed (the one real vulnerability class).
7. `R-014` — fix the download identity (stops the orphan-file dead end).
8. `R-020` — one settings schema (closes three separate "nothing happens" bugs at once).
9. `R-030` + `R-031` — atomic tag writes and root-confined deletes (the two paths that can touch the user's music).
10. `R-000` — commit the tree (so all of the above is reviewable and revertible).
