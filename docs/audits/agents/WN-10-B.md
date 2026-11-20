## AREA WN-10 — Bridge cache cleaning, prefetch, batch downloads, zapret, discord, offline mode, smart playlists — ROLE B

### 1. Scope reviewed

**Primary range (read in full):**

- `core/api.py` L3595–4228 — the whole WN-10 range:
  - `_clean_stream_cache` (3595–3638), `prefetch_track` (3640–3683), `download_all_favorites` (3685–3728),
    `cancel_batch_download` (3730–3738), `get_feed` (3740–3752), `get_home_artists` (3754–3763),
    `get_home_releases` (3765–3780), `get_home_mixes` (3782–3794), `toggle_zapret` (3796–3816),
    `toggle_discord_rpc` (3818–3838), `get_discord_rpc_status` (3840–3844), `get_zapret_status` (3846–3858),
    `check_zapret_update` (3860–3865), `update_zapret` (3867–3874), `get_offline_mode` (4129–4130),
    `set_offline_mode` (4132–4161), `get_offline_library` (4163–4164), `recover_stream` (4166–4174),
    `get_downloads` (4176–4181), `pause_download` (4183–4184), `resume_download` (4186–4187),
    `retry_failed_downloads` (4189–4190), `_smart_playlists` (4192–4194), `get_smart_playlists` (4196–4197),
    `create_smart_playlist` (4199–4202), `update_smart_playlist` (4204–4207), `delete_smart_playlist` (4209–4212),
    `get_smart_playlist_tracks` (4214–4217), `get_search_suggestions` (4219–4221),
    `get_listening_comparison` (4223–4225).
  - Surrounding context needed to judge the range: `core/api.py` L1–350 (SSRF guard, settings masking),
    L350–529 (`_install_bridge_error_logging`, `_offline_bridge_result`, `cleanup`), L1122–1209 (`_emit`,
    `_on_track_changed`), L2294–2361 (`download_track`).

**Callees traced (read):**

- `services/zapret_service.py` (1 475 L) — `sanitize_zapret_args` (203–219), `validate_zapret_binary` (222–262),
  `is_valid_windows_binary` (126–174), `binary_integrity_error` (177–200), `_verify_zip_sha256` (44–51),
  `find_binary` (732–752), `start` (1063–1150), `_launch` (1152–1212), `_launch_elevated` (1264–1334),
  `_extract_zip` (839–866), `download_binaries` (888–913), `update_zapret` (956–1013),
  `check_for_updates`/`get_latest_release_info` (927–954), `stop` (1336–1407), `get_status` (1411–1475).
- `core/services/discord_rpc.py` (183 L) — `start` (51–85), `update_presence` (87–162),
  `clear_presence` (164–172), `stop` (174–183).
- `core/offline.py` (77 L) — `is_offline` (10–14), `available_track` (35–59), `available_tracks` (62–73),
  `offline_library` (76–77).
- `services/smart_playlists.py` (177 L) — `normalize_rule` (20–51), `tracks` (128–177).
- `utils/cache_manager.py` (453 L) — `get_cache_size` (78–93), `purge_stream_cache` (171–271),
  `enforce_cache_limit` (273–287), `download_audio_stream` (289–396).
- `core/downloader.py` (909 L) — `pause_download` (101–113), `resume_download` (115–128),
  `retry_failed_downloads` (130–138), `start_batch` (185–191), `_decrement_batch_total_for_dedup` (193–211),
  `_on_batch_task_done` (213–239), `cancel_batch` (241–285), `queue_download` (356–410), `stop` (884–909).
- `core/download_store.py` (71 L) — `update` (21–30), `rows` (32–56), `recover` (58–64), `preserve_shutdown` (66–71).
- `core/database.py` — `set_cached_file` (2134–2147), `get_cached_stream` (2149–2160),
  `cleanup_expired_cache` (2227–2242), `download_queue_add` (2330–2359),
  `download_queue_set_status` (2361–2370), `get_favorite_tracks` (1224–1227), `mark_track_downloaded` (1278–1282).
- `core/playback_recovery.py` (183 L) — `recover_stream` (95–183), `_callback_result` (40–63).
- `core/proxy.py` — offline gate (814–816), stream-cache write + `set_cached_file` (802–812, 1187–1214),
  `LocalProxyManager.start`/`get_proxy_url`/`auth_query` (1273–1334).
- `core/resolver.py` — `refresh`/`_persist` (232–267); `audio/engine.py` — `resolve_stream_url` (121–151),
  `_notify_track_changed` (78–119).
- `core/app.py` — `__init__` wiring (120–185), `start_zapret_if_enabled` (236–294),
  `re_resolve_stream_url_async` (296–506), `cleanup` (508–586).
- `services/listening_comparison.py` (84 L) — `listening_comparison` (13–84).
- `utils/search_query.py` (101 L) — `suggest_search_queries` (31–101).

**Frontend contract side (read, to verify the bridge contract):**
`ui/web_new_v2/js/downloads-view.js` (193 L), `js/events.js` (L55–304), `js/library.js` (L18–169, L495–554),
`js/feature-controls.js` (L1–105), `js/smart-playlists.js` (185 L), `js/player.js` (L97–164, L450–494),
`js/settings.js` (L1850–2029), `ui/web_new_v2/index.html` (grep for `offline`).

**Tests read:**
`tests/test_offline_mode.py`, `tests/test_offline_proxy.py`, `tests/test_offline_resolve_callbacks.py`,
`tests/test_smart_playlists.py`, `tests/test_download_retry.py`, `tests/test_download_resume.py`,
`tests/test_download_integrity.py`, `tests/test_zapret_binary_integrity.py`, `tests/test_zapret_uac_window.py`,
`tests/test_playback_startup_performance.py`, `tests/conftest.py`, `tests/test_cache_performance.py`
(test names only).

**Runtime verified with the project venv** (`& ".venv_win\Scripts\python.exe"`, hermetic temp DB + redirected `~`;
nothing under `~/.nedotify/` was touched). Scratch scripts live in `%TEMP%\opencode\wn10_*.py`.

---

### 2. Findings

#### F-WN-10-1  [P1] — `_clean_stream_cache` deletes a favourite track's only cached audio copy, bypassing the protection rule the cache manager owns

- **File:** `core/api.py:3595-3638` (deletion loop `:3616-3636`, root resolution `:3600-3602`); `utils/cache_manager.py:171-271` (protection `:198-232`, DB sync `:252-267`)
- **Confirmed:** yes (reproduced end-to-end)
- **Description:** `AppApi._clean_stream_cache` is a second, private implementation of the stream-cache eviction policy. It deletes every file in `~/.nedotify/streams` that is older than 48 h, and then evicts oldest-first down to 350 MB. It has **no** protection for downloaded or favourite tracks and **no** DB synchronisation. `CacheManager.purge_stream_cache` implements the opposite rule and documents it: *"Strictly preserves files where is_downloaded = 1 OR is_favorite = 1."* The proxy caches a stream as `~/.nedotify/streams/<source>_<source_id>.<ext>` (`core/proxy.py:802-812`, `:1187-1214`), which is exactly the file name `purge_stream_cache` protects for favourites (`utils/cache_manager.py:229`). The bridge's cleaner deletes it.
- **Cause:** two owners of one policy. The bridge reaches into a private attribute of another class (`self._core.cache._streams_dir`) and re-implements the rules instead of delegating.
- **Trigger conditions:** a track is favourited and played once (the proxy caches it), then not played for 48 h — or the streams directory exceeds 350 MB. The prune runs from the prefetch task at most every 600 s (`core/api.py:3665-3671`), i.e. during normal playback.
- **User impact:** the only local copy of the track disappears. `stream_cache.cached_file_path` still points at the deleted file, so `core/offline.py::_local_file` (`os.path.isfile`) rejects it and the track silently drops out of the offline library; the proxy's cache-hit branch (`core/proxy.py:797`) misses and falls through to the network — which in offline mode is a 503. The user's "favourite is available offline" state is destroyed with no confirmation, no log line above `debug`, and no recovery (the file is gone).
- **Evidence:**
  ```python
  # core/api.py:3616-3624 — no protection, no DB sync
  for path, mtime, size in files:
      if (now - mtime) > max_age_sec:
          try:
              os.remove(path)
              total_size -= size
          except Exception:
              kept_files.append((path, mtime, size))
  ```
  ```python
  # utils/cache_manager.py:227-232 — the rule the bridge does not honour
  if norm_fp in protected_paths:      continue
  if any(p_src in base_name for p_src in protected_sources):  continue
  if any(act in base_name for act in active_downloads_copy):  continue
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_repro.py` (run with the project venv). Output:
  ```
  === F1: _clean_stream_cache deletes a FAVOURITE's cached stream ===
    purge_stream_cache(quota=1) -> freed 0 | favourite file still present: True
    api._clean_stream_cache() -> favourite file present: False
    DB cached_file_path still points at the deleted file: True | file on disk: False
  ```
  Steps: temp DB + temp `~`; add a track, set `is_favorite = 1`; write `~/.nedotify/streams/youtube_FAV123.m4a`; `db.cache_stream(...)` + `db.set_cached_file(...)`; set the file mtime to 72 h ago; call `AppApi._clean_stream_cache()`.
- **Suggested fix:** delete `AppApi._clean_stream_cache` and delegate to `CacheManager.purge_stream_cache()`. If a TTL prune is genuinely wanted, add `CacheManager.purge_expired(max_age_hours)` that reuses the existing protection and DB-sync helpers, and have the bridge call that.
- **Fix side effects:** `purge_stream_cache` is quota-driven, not TTL-driven; a TTL policy needs either an mtime filter inside `CacheManager` or a new expiry column. The 350 MB hardcoded ceiling would disappear (see F-WN-10-2), which changes how quickly the disk fills for users who set a 5 GB quota.
- **Discovered by:** B

---

#### F-WN-10-2  [P1] — `_clean_stream_cache` never synchronises the DB, so `stream_cache` accumulates dangling rows that no cleanup ever removes

- **File:** `core/api.py:3616-3636`; `core/database.py:2134-2147` (`set_cached_file` sets `expires_at = NULL`); `core/database.py:2227-2242` (`cleanup_expired_cache` only deletes rows with `expires_at IS NOT NULL` **and** an empty `cached_file_path`)
- **Confirmed:** yes (code + runtime check)
- **Description:** every file the bridge cleaner deletes leaves a permanent row behind in `stream_cache` whose `cached_file_path` points at a file that no longer exists. `CacheManager.purge_stream_cache` performs the matching DB update in one transaction (`utils/cache_manager.py:252-267`); the bridge's cleaner omits it entirely. The scheduled cleanup in `core/app.py:176-185` cannot reclaim the rows either, because `set_cached_file` sets `expires_at = NULL` and `cleanup_expired_cache` skips NULL-expiry rows.
- **Cause:** the same duplicated ownership as F-WN-10-1 — the private cleaner implements the *file* half of the policy and forgets the *state* half.
- **Trigger conditions:** any prune cycle (every ≥ 600 s during playback) with at least one cached stream on disk.
- **User impact:** `stream_cache` grows monotonically over the app's lifetime. `core/offline.py:63-64` loads **every** row with a non-null `cached_file_path` into a Python dict on each `available_tracks()` call — so the offline library, the offline smart-playlist paging and `set_offline_mode` all pay the growing cost. The rows are also stale state: `proxy.py:797` finds a `cached_file_path` that no longer exists and falls through to the network.
- **Evidence:**
  ```python
  # core/database.py:2235-2237
  "DELETE FROM stream_cache WHERE expires_at IS NOT NULL "
  "AND datetime(expires_at) < datetime('now') "
  "AND (cached_file_path IS NULL OR cached_file_path = '')"
  ```
  ```python
  # core/database.py:2141-2145 — every cached file sets expires_at = NULL
  "UPDATE stream_cache SET cached_file_path = ?, expires_at = NULL, cached_at = CURRENT_TIMESTAMP "
  "WHERE source = ? AND source_id = ?",
  ```
- **Reproduction / verification:** in the same script, after the prune, `SELECT cached_file_path FROM stream_cache WHERE source_id='FAV123'` still returns the deleted path, and `db.cleanup_expired_cache()` returns `0` rows deleted. The paired `CacheManager.purge_stream_cache` path clears the column in the same transaction it deletes the file.
- **Suggested fix:** as F-WN-10-1 — one owner. If the bridge keeps a cleaner, it must clear `stream_cache.cached_file_path` (and `tracks.is_cached`) in the same transaction, or hand the deletion to `CacheManager`.
- **Fix side effects:** the DB write per prune adds a transaction; batching the updates in one transaction (as `purge_stream_cache` does) keeps it cheap. Rows that are currently dangling would need a one-off cleanup migration.
- **Discovered by:** B

---

#### F-WN-10-3  [P1] — `update_zapret` installs and elevates a binary with **no integrity verification** for every release except the pinned one

- **File:** `core/api.py:3867-3874` (bridge entry point) → `services/zapret_service.py:956-1013` (`expected_hash` `:976-981`), `services/zapret_service.py:44-51` (`_verify_zip_sha256`), `services/zapret_service.py:839-866` (`_extract_zip`), `services/zapret_service.py:1264-1334` (`_launch_elevated`)
- **Confirmed:** yes (executed)
- **Description:** the pinned SHA-256 exists **only** for the bundled release `v72.13`. For every actual update the URL differs from `ZAPRET_ZIP_URL`, so `expected_hash` becomes `""` and `_verify_zip_sha256(zip_bytes, "")` returns `True` — *"No pinned hash — verification not possible"*. The archive URL itself is taken from the GitHub API (`get_latest_release_info`, `:927-942`), so the trust boundary is "whatever the network returns". The archive is then unpacked into `~/.nedotify/zapret` (`.exe`, `.dll` and `.sys` entries only) and the binary is launched **elevated** (`ShellExecuteW "runas"`, `:1285`).
- **Cause:** the hash pin was written for the *bootstrap* download and was never extended to the update path; the verifier treats "no expected hash" as "verified".
- **Trigger conditions:** the user clicks "Обновить Zapret" (or the background auto-updater fires with `zapret.autoupdate = true`) and upstream has published a release newer than `v72.13`.
- **User impact:** a MITM on the TLS path, a compromised release asset, or a compromised upstream account yields arbitrary `.exe`/`.dll`/`.sys` files written into the user's profile and executed **as Administrator** after the UAC prompt. The user is shown "Zapret успешно обновлен до версии vX" and has no way to tell that the bytes were never checked.
- **Evidence:**
  ```python
  # services/zapret_service.py:976-981
  expected_hash = ZAPRET_ZIP_SHA256 if zip_url == ZAPRET_ZIP_URL else ""
  if not _verify_zip_sha256(zip_bytes, expected_hash):
      ... return False, msg
  ```
  ```python
  # services/zapret_service.py:48-49
  if not expected_sha256:
      return True  # No pinned hash — verification not possible
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_zapret.py`:
  ```
  === 1. _verify_zip_sha256 with an EMPTY expected hash ===
    _verify_zip_sha256(b'anything', '') -> True
    pinned hash exists only for: v72.13
  ```
  The pinned URL is `https://github.com/bol-van/zapret/releases/download/v72.13/zapret-v72.13.zip`; every later tag takes the unverified branch.
- **Suggested fix:** ship a signed manifest (a pinned public key + per-release SHA-256) and refuse to install an archive whose hash is not in the manifest; treat "no expected hash" as **fail closed** in `_verify_zip_sha256`.
- **Fix side effects:** every new upstream release needs a manifest entry, so the update button stops working for releases the app has not pinned — that is the intended security posture but it is a product decision. A manifest fetched over the same channel is worthless unless it is signed or pinned.
- **Discovered by:** B — *root cause lives in `services/zapret_service.py` (owning area WN-26); the bridge method is the user-facing trigger.*

---

#### F-WN-10-4  [P1] — `ZapretService.find_binary()` returns CWD-relative candidates **without** the validation the user-supplied path gets

- **File:** `services/zapret_service.py:732-752` (candidates `:740-746`), `services/zapret_service.py:222-262` (`validate_zapret_binary`), `services/zapret_service.py:1087-1108` (only a PE-signature check), `services/zapret_service.py:1152-1195` (non-elevated `_launch`, no re-validation); reached from `core/api.py:3796-3816`
- **Confirmed:** yes (executed)
- **Description:** `validate_zapret_binary` (root containment + name allow-list + PE check) is applied **only** to the user-supplied `custom_path`. The built-in candidate list contains `os.path.join(os.getcwd(), "bin", "winws.exe")` and `os.path.join(os.getcwd(), "zapret", "winws.exe")`, and `find_binary` returns the first candidate that merely *exists*. `start()` then validates only the image (`binary_integrity_error` — a PE-signature check), not the location. The **non-elevated** `_launch()` path never re-validates; only `_launch_elevated()` does (`services/zapret_service.py:1270-1273`).
- **Cause:** validation was applied to the untrusted *input* and forgotten on the *default* selection path — the exact inverse of the usual mistake, but with the same outcome: an unvalidated path reaches `subprocess.Popen`.
- **Trigger conditions:** the app is started with a working directory that contains `bin\winws.exe` (a portable install in a shared or downloaded folder, a shortcut with a custom "Start in", a sync folder) and the user enables Zapret.
- **User impact:** arbitrary code execution at the user's own privilege, launched by the app with no prompt and no visible trace. The elevated path refuses such a file, so this is not a privilege escalation — but it is an unvalidated binary-hijack of the one feature that also runs `cmd.exe` with a constructed command line.
- **Evidence:**
  ```python
  # services/zapret_service.py:740-751
  candidates = [
      os.path.join(self.app_dir, "winws.exe"),
      os.path.join(self.app_dir, "zapret.exe"),
      os.path.join(self.app_dir, "bin", "winws.exe"),
      os.path.join(os.getcwd(), "bin", "winws.exe"),          # <-- not validated
      os.path.join(os.getcwd(), "zapret", "winws.exe")        # <-- not validated
  ]
  for c in candidates:
      if os.path.exists(c):
          return c
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_zapret.py`:
  ```
  === 2. find_binary() returns CWD candidates WITHOUT validation ===
    planted: ...\cwd\bin\winws.exe
    find_binary() -> ...\cwd\bin\winws.exe
    is it the planted file: True
    validate_zapret_binary(planted, app_dir, extra_roots=[base_dir]) -> False
  ```
  The planted file is a structurally valid PE, so `binary_integrity_error` also returns `""` and `start()` proceeds to `Popen`.
- **Suggested fix:** run every candidate through `validate_zapret_binary` before returning it, and remove the `os.getcwd()` entries (the repo checkout is already covered by `base_dir`).
- **Fix side effects:** a developer workflow that relies on `cwd\bin\winws.exe` stops working; `base_dir` (`services/zapret_service.py:326`) already resolves to the repo root in a dev checkout, so the CWD candidates are redundant there.
- **Discovered by:** B — *root cause lives in `services/zapret_service.py` (owning area WN-26); `toggle_zapret` in WN-10 is the trigger.*

---

#### F-WN-10-5  [P2] — In the frozen build the only "trusted" extra root for the elevated Zapret launch is the per-run `_MEIPASS` temp directory (user-writable)

- **File:** `services/zapret_service.py:326` (`base_dir = getattr(sys, "_MEIPASS", ...)`), `services/zapret_service.py:1270` (`validate_zapret_binary(exe, self.app_dir, extra_roots=[self.base_dir])`), `services/zapret_service.py:1219-1262` (`ShellExecuteW "runas"`)
- **Confirmed:** yes (executed)
- **Description:** `validate_zapret_binary` accepts a binary that lives under `app_dir` (`~/.nedotify/zapret`) **or** `base_dir`. In a PyInstaller one-file build `base_dir` is `sys._MEIPASS`, a per-launch extraction directory under `%TEMP%` — writable by the user and by any process running as the user. The elevated launch accepts it.
- **Cause:** `extra_roots=[self.base_dir]` was added to support "the application directory (repo checkout in dev, `sys._MEIPASS` in the frozen build)". Those two are not the same trust level: one is an installed directory, the other a temporary extraction folder that changes on every launch.
- **Trigger conditions:** the app is running from a frozen build; any same-user process writes a PE named `winws.exe` into the live `_MEIPASS` folder; the user then enables Zapret.
- **User impact:** local privilege escalation — "write access to the user's temp directory" becomes "run as Administrator" after the UAC prompt (the user still sees the prompt, so the social-engineering burden remains, but the binary is not the one the product intends to run).
- **Evidence:**
  ```python
  # services/zapret_service.py:326
  self.base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  ```
  ```python
  # services/zapret_service.py:1270-1273
  if not validate_zapret_binary(exe, self.app_dir, extra_roots=[self.base_dir]):
      msg = f"Отказано в запуске: {os.path.basename(exe)} не является разрешённым исполняемым файлом Zapret."
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_zapret.py`:
  ```
  === 3. base_dir in a frozen build is a user-writable temp dir ===
    base_dir = ...\wn10_zapret\_MEI12345
    validate_zapret_binary(<_MEIPASS>/winws.exe) -> True
  ```
  (A synthetic `_MEIPASS` was set; no frozen build was executed — see Coverage gaps.)
- **Suggested fix:** in a frozen build use the *installed* directory (`os.path.dirname(sys.executable)`) as the trusted root and never `_MEIPASS`; keep `bin/winws.exe` next to the installed exe and reference it from there.
- **Fix side effects:** `setup_pyinstaller.spec` / `installer.iss` must place the binaries in the installed folder, and the dev fallback (`base_dir` = repo root) must be kept for source runs.
- **Discovered by:** B — *root cause lives in `services/zapret_service.py` (owning area WN-26).*

---

#### F-WN-10-6  [P2] — `download_all_favorites` performs one blocking UI-thread round-trip per queued track

- **File:** `core/api.py:3685-3728` (loop `:3717-3718`), `core/api.py:2294-2361` (`download_track`), `core/downloader.py:356-410` (`queue_download` → `_emit('download_queue_updated', …)` `:409`), `core/api.py:1122-1159` (`_emit` → `window.evaluate_js`)
- **Confirmed:** yes (measured event count; the pywebview mechanism was read in the installed venv)
- **Description:** the batch is queued **synchronously on the bridge thread**, and every queued track emits its own `download_queue_updated` event. On the EdgeChromium/WinForms backend `evaluate_js` is `self.webview.Invoke(...)` followed by `semaphore.acquire()` — a *synchronous* marshal to the WinForms UI thread that the caller waits on (`webview/platforms/edgechromium.py:126-130`). So one queued track = one blocking UI-thread script execution.
- **Cause:** the batch enqueue and the per-item progress notification were designed as two independent concerns; nothing aggregates the notifications for a bulk operation.
- **Trigger conditions:** "Скачать всё избранное" with a few hundred favourites. Measured: 400 favourites → exactly 400 `download_queue_updated` emissions + 1 `batch_download_started`.
- **User impact:** the UI thread is asked to run N scripts back to back and the JS promise for the batch resolves only after the last one. 2 000 favourites ⇒ 2 000 UI-thread script executions; the window's responsiveness degrades in proportion to the library size. The DB cost itself is negligible (0.08 ms/track measured) — the cost is entirely in the UI marshalling.
- **Evidence:**
  ```python
  # core/api.py:3717-3718
  for track in to_download:
      self.download_track(track)
  ```
  ```python
  # core/downloader.py:409
  self._emit('download_queue_updated', {'track_id': track_id, 'status': 'pending'})
  ```
  ```python
  # webview/platforms/edgechromium.py:126-130 (installed venv)
  self.webview.Invoke(Func[Object](lambda: self.webview.ExecuteScriptAsync(script)...))
  semaphore.acquire()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_repro2.py` (real `DownloadManager`, processor halted):
  ```
  queued 400 favourite tracks in 33 ms (0.08 ms/track)
  bridge events emitted: 401 | download_queue_updated: 400 | batch_download_started: 1
  sample payload: [{'track_id': 1, 'status': 'pending'}, {'track_id': 2, 'status': 'pending'}]
  ```
- **Suggested fix:** emit one aggregate event for the batch (or suppress the per-track `download_queue_updated` while a batch is active) and hand the enqueue loop to a worker thread that reports a single summary; `js/downloads-view.js` already re-reads `get_downloads()` on any event, so a summary event is sufficient.
- **Fix side effects:** a consumer that relies on the per-track event to advance a row would stop advancing until the summary arrives; the downloads view polls, so this is contained, but any other consumer must be checked.
- **Discovered by:** B

---

#### F-WN-10-7  [P1] — `get_listening_comparison` can block the bridge thread for ~24 s (measured) on a normal-sized history

- **File:** `core/api.py:4223-4225` → `services/listening_comparison.py:56-81` (`new_artists` `:56-66`, `returning_artists` `:67-81`)
- **Confirmed:** yes (measured, per-query timings)
- **Description:** the "new artists" and "returning artists" queries correlate on `LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist))` — an expression on **both** sides, so no index can serve it. Each outer row of the window re-scans the candidate `history` rows and re-joins `tracks`. With 4 000 tracks and 20 000 history rows the two queries alone take 23.7 s.
- **Cause:** a normalised, indexable artist key was never materialised; the artist identity is recomputed as a string expression per comparison.
- **Trigger conditions:** the user opens the profile's comparison panel with period = "month" (or "week") on a library with a year of listening history. Measured: `week` 2.77 s, `month` 34.0 s, `year` 0.62 s (the year case is fast only because the "previous" window is empty, so the correlated `EXISTS` short-circuits).
- **User impact:** the comparison panel hangs for tens of seconds with the refresh button disabled and no progress indication. Every additional click spawns another multi-second query on its own bridge thread (`webview/util.py:308-309` starts a thread per call) → CPU saturation of the machine. The project's own rule states that "a long block is felt as a frozen UI" (`core/api.py:63-67`).
- **Evidence:**
  ```python
  # services/listening_comparison.py:61-64
  AND NOT EXISTS (
      SELECT 1 FROM history old JOIN tracks older ON older.id = old.track_id
      WHERE old.played_at < ? AND old.duration_listened > 0
        AND LOWER(TRIM(older.artist)) = LOWER(TRIM(t.artist)))
  ```
  Per-query timings (4000 tracks / 20 000 history rows):
  ```
  totals(current)      ->       0.8 ms
  artists(current)     ->       1.9 ms
  daily(current)       ->       0.9 ms
  totals(previous)     ->       0.7 ms
  new_artists          ->    4926.2 ms
  returning_artists    ->   18787.8 ms
  ```
  Query plan (the correlated subqueries use `idx_history_played_at` only to find candidate rows; the join predicate is still an expression):
  ```
  SEARCH old USING INDEX idx_history_played_at (played_at<?)
  SEARCH older USING INTEGER PRIMARY KEY (rowid=?)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_perf.py` and `%TEMP%\opencode\wn10_perf2.py` (hermetic temp DB, 4 000 tracks / 20 000 history rows):
  ```
  === get_listening_comparison -> listening_comparison(db, 'year') ===
    period=week  ->   2773.8 ms
    period=month ->  34007.3 ms
    period=year  ->    620.5 ms
  ```
- **Suggested fix:** materialise a normalised artist key (`tracks.artist_key`) and an index on it, and/or maintain a per-(day, artist) roll-up table updated on write. A short-term bound (a statement timeout or a LIMIT on the correlated scans) would at least stop the 34-second stall.
- **Fix side effects:** a schema migration plus a backfill of `artist_key` for existing tracks; `history` is never pruned (already reported in WN-12), so a roll-up has to be maintained incrementally on insert.
- **Discovered by:** B — *the SQL lives in `services/listening_comparison.py` (owning area WN-25); the bridge method is the entry point and carries no bound.*

---

#### F-WN-10-8  [P2] — `update_zapret` silently keeps the old executable: the "update" replaces the version marker, not the binary

- **File:** `core/api.py:3867-3874` → `services/zapret_service.py:839-866` (`_extract_zip`, guard `:861-862`), `services/zapret_service.py:997` (`_write_version_info(latest_tag)`)
- **Confirmed:** yes (executed)
- **Description:** the extraction guard is `if is_valid_windows_binary(target_path): continue` — it skips **any** existing valid image, not only a broken one. So a new release's `winws.exe` never replaces the installed one, while `version.json` is rewritten to the new tag.
- **Cause:** the guard was written to prevent "replacing a working binary with an empty one", but it was expressed as "is the target already valid?" instead of "is the target already *this* version?".
- **Trigger conditions:** any update to a release newer than the one on disk.
- **User impact:** the UI reports "Zapret успешно обновлен до версии v72.14" (and `get_zapret_status` shows the new `version`) while v72.13 keeps running. The user believes they have the current DPI-bypass fix and does not.
- **Evidence:**
  ```python
  # services/zapret_service.py:857-866
  target_path = os.path.join(self.app_dir, filename)
  if is_valid_windows_binary(target_path):
      continue
  tmp_path = target_path + ".part"
  with open(tmp_path, "wb") as f:
      f.write(z.read(name))
  os.replace(tmp_path, target_path)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_zapret.py` (a zip containing `zapret-x86_64/winws.exe` is extracted over an existing valid `winws.exe`):
  ```
  === 5. _extract_zip never replaces a VALID existing binary ===
    winws.exe replaced by the update: False
  ```
- **Suggested fix:** compare the existing file's hash (or the archive member's hash) against the new one and overwrite when they differ, keeping the "never replace a working binary with an empty/corrupt one" guarantee by validating the *new* content before `os.replace`.
- **Fix side effects:** `tests/test_zapret_binary_integrity.py:294` (`test_extract_never_replaces_a_working_binary_with_an_empty_one`) pins the current guard. The test asserts "not empty", the code implements "not different" — the test needs to be tightened, not the guard dropped.
- **Discovered by:** B — *root cause lives in `services/zapret_service.py` (owning area WN-26).*

---

#### F-WN-10-9  [P2] — Offline mode cannot be enabled from the shipped UI: `set_offline_mode(True)` has no caller

- **File:** `core/api.py:4129-4130` (`get_offline_mode`), `core/api.py:4132-4161` (`set_offline_mode`), `core/api.py:4163-4164` (`get_offline_library`); `ui/web_new_v2/js/feature-controls.js:54` (the only caller); `ui/web_new_v2/index.html:461` (the note element)
- **Confirmed:** yes (exhaustive grep of `ui/web_new_v2`)
- **Description:** the only call to `set_offline_mode` anywhere in the UI is `set_offline_mode(false)` — the "Разрешить сеть" recovery action of the operation-error panel. `get_offline_mode` and `get_offline_library` have **no** UI caller at all, and `js/settings.js` never touches the `network` category (`grep 'network\.' js/settings.js` → no match). The offline-mode note in `index.html:461` ("Загрузки остаются на паузе") can therefore never be shown.
- **Cause:** the feature was implemented bottom-up (a settings key, a policy check in eight modules, bridge methods, a UI note) without ever wiring the switch. The only way to enable it is a raw bridge call such as `save_setting('offline_mode', true, 'network')` (`core/api.py:2940-2953` writes any category/key).
- **Trigger conditions:** always — the surface is unreachable.
- **User impact:** the whole offline-mode feature — 20+ `is_offline()` checks across `core/api.py`, `core/app.py`, `core/proxy.py`, `core/downloader.py`, `core/playback_recovery.py`, `services/lyrics_lookup.py`, the offline interception table (`core/api.py:461-512`), the queue pruning in `set_offline_mode` — is invisible to the user. A user who asks for an offline mode gets nothing; a user who *is* offline (no network) is not helped by any of the local-only fallbacks, because the mode was never switched on.
- **Evidence:**
  ```python
  # ui/web_new_v2/js/feature-controls.js:52-56
  async function runErrorAction(detail) {
      if (detail.action === 'online') {
          const result = await window.pywebview.api.set_offline_mode(false);
  ```
  `grep -rn "set_offline_mode" ui/web_new_v2` → 1 hit, argument `false`. `grep -rn "get_offline_mode\|get_offline_library" ui/web_new_v2` → 0 hits.
- **Suggested fix:** either add the switch to the settings panel (a `network.offline_mode` toggle bound to `save_setting`/`set_offline_mode`) and to the persisted settings schema, or delete the unreachable surface (`get_offline_mode`, `get_offline_library`) and the policy checks it drives.
- **Fix side effects:** exposing the switch makes the offline interception table live, which will surface every gap in it (WN-03 reported `get_waveform` as missing from the list) — that is the point, but it turns a dormant feature into a tested one.
- **Discovered by:** B

---

#### F-WN-10-10  [P2] — Enabling offline mode pauses every download without emitting a batch terminator, and switching back online never resumes them

- **File:** `core/api.py:4132-4161` (pause at `:4139-4142`), `core/downloader.py:101-113` (`pause_download` emits only `download_queue_updated`), `core/downloader.py:115-128` (`resume_download` refuses while offline), `ui/web_new_v2/js/library.js:78-105` (the batch widget)
- **Confirmed:** yes (code path)
- **Description:** `set_offline_mode(True)` calls `downloader.pause_download()`, which sets every `pending`/`downloading` row to `paused` and emits only `download_queue_updated`. It does **not** emit `batch_download_finished` or `batch_download_cancelled`, and it does not record that *it* was the one that paused them. `set_offline_mode(False)` does not resume anything.
- **Cause:** offline mode and the user-facing "pause" control share one state (`paused`) with no owner recorded, and no batch-level lifecycle event.
- **Trigger conditions:** switching offline mode on while a batch is running.
- **User impact:** (a) the batch progress widget in the library stays frozen at e.g. "12 / 100" forever — there is no terminator and no explanation; (b) when the user switches back online, the downloads stay `paused` and the batch denominator still reflects the pre-pause count, so the user must press "Продолжить все" manually and the progress numbers no longer add up.
- **Evidence:**
  ```python
  # core/api.py:4139-4142
  if enabled:
      downloader = getattr(self._core, 'downloader', None)
      if downloader and hasattr(downloader, 'pause_download'):
          downloader.pause_download()
  ```
  ```python
  # core/downloader.py:111-113 — no batch terminator
  self._store.update(target, status='paused', resume_on_restart=0)
  self._emit('download_queue_updated', {'status': 'paused'})
  return {'success': True, 'count': len(targets)}
  ```
- **Suggested fix:** emit a batch terminator from `pause_download`, and track which rows the offline mode paused (a dedicated flag on the queue row or an in-memory set) so `set_offline_mode(False)` can resume exactly those.
- **Fix side effects:** distinguishing "paused by offline mode" from "paused by the user" needs a new column on `download_queue` (a migration) or an in-memory set that is lost across a restart — the DB flag is the correct one.
- **Discovered by:** B — *the missing event and the pause/resume ownership live in `core/downloader.py` (owning area WN-13); the caller-side gap is WN-10.*

---

#### F-WN-10-11  [P2] — The batch-download progress contract is unstable: `total` shrinks between `batch_download_started` and `batch_download_progress`/`finished`

- **File:** `core/api.py:3715` (`batch_download_started`, `total = len(to_download)`), `core/downloader.py:193-211` (`_decrement_batch_total_for_dedup` shrinks `_batch_total`), `core/downloader.py:213-239` (`_on_batch_task_done`: `finished = completed >= total`), `ui/web_new_v2/js/library.js:78-101`
- **Confirmed:** yes (code)
- **Description:** when a queued item turns out to be a duplicate (or fails to persist), `_decrement_batch_total_for_dedup` **decrements `_batch_total`** but never decrements `_batch_completed`. The denominator the UI was given at `batch_download_started` therefore no longer matches the one carried by `batch_download_progress`, and `completed >= total` becomes true **early** — `batch_download_finished` fires while downloads are still in flight.
- **Cause:** the batch counter conflates "work items" with "items still to do"; a dedup is modelled as a change of scope rather than as a separate outcome.
- **Trigger conditions:** a favourite that is already in the download queue (or one whose DB row cannot be written) while "Скачать всё избранное" runs.
- **User impact:** the progress widget shows "12 / 98" after "0 / 100"; the bar jumps to 100 % and the toast "✅ Загрузка завершена (N треков)" appears while downloads are still running, and `_batch_active` is then cleared so the remaining tasks emit no further progress at all. The user is told a batch finished that has not.
- **Evidence:**
  ```python
  # core/downloader.py:196-206
  if self._batch_total > 0:
      self._batch_total = max(0, self._batch_total - 1)
  if self._batch_total == 0 or self._batch_completed >= self._batch_total:
      self._batch_active = False
      finished_payload = {'total': self._batch_total, 'completed': self._batch_completed, 'failed': self._batch_failed}
  ```
  ```python
  # core/downloader.py:221-225
  percent = round((self._batch_completed / max(1, self._batch_total)) * 100)
  ...
  finished = completed >= total
  ```
- **Suggested fix:** keep `total` immutable for the lifetime of a batch and report dedups in a separate `skipped` counter; `finished` should be `completed + skipped >= total`.
- **Fix side effects:** the final toast count would include skipped tracks unless the UI switches to `completed - skipped`; `js/library.js:94-98` reads `data.completed` directly.
- **Discovered by:** B — *the counter lives in `core/downloader.py` (owning area WN-13); the `batch_download_started` payload is WN-10's half of the contract.*

---

#### F-WN-10-12  [P2] — `toggle_discord_rpc(False)` never disconnects: the status bridge keeps reporting `connected: True`

- **File:** `core/api.py:3818-3838` (`:3834` → `clear_presence()`), `core/api.py:3840-3844` (`get_discord_rpc_status`), `core/services/discord_rpc.py:164-172` (`clear_presence` does not close the socket), `core/services/discord_rpc.py:174-183` (`stop()` does)
- **Confirmed:** yes (code)
- **Description:** disabling Discord RPC calls `clear_presence()`, which sends a "clear" payload but leaves the IPC socket open, leaves `self.rpc` set and leaves `self.connected = True`. The service's `stop()` — the only method that closes the connection and resets the flags — is never called from the bridge.
- **Cause:** the bridge treats "off" as "stop publishing" rather than "disconnect", so the service ends up with two independent notions of the same state (the settings flag and the live connection).
- **Trigger conditions:** the user turns Discord RPC off in the settings (the toggle writes `app.discord_rpc_enabled = false` and calls `clear_presence()`).
- **User impact:** `get_discord_rpc_status()` answers `{'enabled': False, 'connected': True}` — the UI shows a live connection for a feature the user just switched off; the Discord client keeps the application registered for the whole session; the IPC socket stays open. (The presence itself is not re-published, because `update_presence` checks `is_enabled()` first — so this is a state-reporting and resource-hygiene defect, not a privacy leak.)
- **Evidence:**
  ```python
  # core/api.py:3833-3834
  else:
      self._core.discord_rpc.clear_presence()
  ```
  ```python
  # core/services/discord_rpc.py:164-172
  def clear_presence(self):
      with self._lock:
          if not self.connected or not self.rpc: return
          try: self.rpc.clear()
          except Exception: pass
  ```
  vs `stop()` (`:174-183`) which does `self.rpc.close()` / `self.rpc = None` / `self.connected = False`.
- **Suggested fix:** call `discord_rpc.stop()` when disabling (and keep `clear_presence()` for the "pause the presence" case); `start()` already honours `is_enabled()`, so a later `update_presence` will not reconnect.
- **Fix side effects:** `stop()` sets `self.rpc = None`; `update_presence` then re-enters the `if not self.connected` branch and calls `start()`, which returns immediately because `is_enabled()` is false — so no reconnect loop. Confirm this with a test that toggles off → on → off.
- **Discovered by:** B

---

#### F-WN-10-13  [P3] — `get_smart_playlist_tracks` re-scans the whole `stream_cache` table once per 500-track batch in offline mode

- **File:** `core/api.py:4214-4217`, `services/smart_playlists.py:156-174`, `core/offline.py:62-73`
- **Confirmed:** yes (code)
- **Description:** the offline paging path calls `available_tracks(self.db, batch)` once per 500-row batch, and `available_tracks` rebuilds `{source: source_id → cached_file_path}` from a **full** `SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL` on every call.
- **Cause:** the availability map is computed inside the per-batch helper instead of once per request.
- **Trigger conditions:** opening a smart playlist in offline mode over a library larger than 500 matching tracks.
- **User impact:** `ceil(N/500)` full scans of `stream_cache` per request — and per F-WN-10-2 that table also holds every dangling row the bridge cleaner left behind, so the scan grows with app age.
- **Evidence:**
  ```python
  # core/offline.py:62-64
  def available_tracks(db, tracks):
      cached = {(row['source'], str(row['source_id'])): row['cached_file_path']
                for row in db.conn.execute('SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL')}
  ```
  ```python
  # services/smart_playlists.py:165-166
  while batch := cursor.fetchmany(self.MAX_TRACKS):
      for track in available_tracks(self.db, [dict(row) for row in batch]):
  ```
- **Suggested fix:** build the availability map once per request and pass it into the batch helper (or add an `available_map` parameter to `available_tracks`).
- **Fix side effects:** none — the map is read-only inside one request; the map must still be invalidated between requests (it is rebuilt per call today).
- **Discovered by:** B — *the helper lives in `core/offline.py` (owning area WN-15) and the paging loop in `services/smart_playlists.py` (WN-24); the bridge method is the entry point.*

---

#### F-WN-10-14  [P3] — `get_offline_library` materialises the entire library and stats every file, and has no caller

- **File:** `core/api.py:4163-4164`, `core/offline.py:76-77`, `core/offline.py:62-73`, `core/database.py:1184` (`get_all_tracks`, no default limit)
- **Confirmed:** yes (measured; no UI caller found)
- **Description:** `get_offline_library` → `offline_library(db)` → `available_tracks(db, db.get_all_tracks())`: the whole `tracks` table is materialised, then one `os.path.isfile` per row plus a full `stream_cache` scan. It is the most expensive read in the offline surface and **no UI code calls it** (`grep -rn "get_offline_library" ui/web_new_v2` → 0 hits); the library's "Офлайн треки" card uses `get_downloaded_tracks` instead (`js/library.js:503`).
- **Cause:** the method was written before the UI settled on `get_downloaded_tracks` and was never removed.
- **Trigger conditions:** only if something calls it.
- **User impact:** none today (dead surface); if it is wired up as-is it ships the whole library to the WebView and blocks the bridge thread — `get_all_tracks()` measured 201.8 ms for 4 000 rows here, and the prior run measured 223.5 ms for 20 000 tracks and 4 843 KiB of JSON for 5 000 rows (≈19 MiB extrapolated at 20 000) — see WN-12.
- **Evidence:**
  ```python
  # core/api.py:4163-4164
  def get_offline_library(self):
      return offline_library(self._core.db)
  ```
  ```python
  # core/offline.py:76-77
  def offline_library(db):
      return available_tracks(db, db.get_all_tracks())
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn10_perf.py`: `get_all_tracks()` → 201.8 ms for 4 000 rows; `available_tracks()` → 9.6 ms. `grep -rn "get_offline_library" ui/web_new_v2` → no match.
- **Suggested fix:** remove the method, or give it a LIMIT/paging and reuse the `get_downloaded_tracks` shape that the UI already consumes.
- **Fix side effects:** none — no consumer.
- **Discovered by:** B

---

#### F-WN-10-15  [P3] — The batch-download event payloads are not a stable contract (`batch_download_cancelled` carries a bare boolean)

- **File:** `core/downloader.py:283` (`self._emit('batch_download_cancelled', True)`), `core/downloader.py:211` and `:235-239` (object payloads), `core/api.py:3715` (object payload), `ui/web_new_v2/js/events.js:242-256`
- **Confirmed:** yes
- **Description:** four sibling events, three object payloads and one bare boolean. `batch_download_started` = `{total, current}`, `batch_download_progress` = `{current, total, percent, track_id}`, `batch_download_finished` = `{total, completed, failed}`, `batch_download_cancelled` = `True`.
- **Cause:** each event was added when its consumer needed it; there is no shared envelope.
- **Trigger conditions:** cancelling a batch.
- **User impact:** a consumer that reads `detail.total` from the cancelled event gets `undefined`; `js/events.js` forwards all four verbatim to `document.dispatchEvent`, so the inconsistency is one refactor away from a crash. Today `js/library.js:103` ignores the detail, so nothing breaks.
- **Evidence:**
  ```python
  # core/downloader.py:283-284
  self._emit('batch_download_cancelled', True)
  self._emit('download_queue_updated', {'status': 'cancelled'})
  ```
- **Suggested fix:** give `batch_download_cancelled` the same shape as `batch_download_finished` (`{total, completed, failed}`), and document the four payloads in one place.
- **Fix side effects:** none — the current consumer ignores the payload.
- **Discovered by:** B

---

#### F-WN-10-16  [P3] — `check_zapret_update` has no caller and performs an unbounded network round-trip on the bridge thread

- **File:** `core/api.py:3860-3865` → `services/zapret_service.py:927-954` (`urlopen(timeout=6.0)`)
- **Confirmed:** yes (grep)
- **Description:** no code in `ui/web_new_v2` calls `window.pywebview.api.check_zapret_update`; the settings panel only calls `update_zapret`. The method performs a synchronous GitHub API call (up to 6 s) plus, indirectly, the same call again inside `update_zapret`.
- **Cause:** dead bridge surface.
- **Trigger conditions:** only if something calls it.
- **User impact:** none today; if wired up it adds a 6 s bridge call with no loading state, and the offline interception table (`core/api.py:502`) already blocks it, so the "no update available" state would be indistinguishable from "offline".
- **Evidence:** `grep -rn "check_zapret_update" ui/web_new_v2` → no match; `core/api.py:502` lists it in the offline interception set.
- **Suggested fix:** remove the bridge method, or wire it to the settings panel with an explicit loading state and reuse the result inside `update_zapret` so the GitHub call is made once.
- **Fix side effects:** none.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

1. **`custom_args` cannot inject arguments.** `sanitize_zapret_args` (`services/zapret_service.py:203-219`) tokenises with `shlex.split(..., posix=False)` on Windows and then matches every token against `_ALLOWED_ARG_RE` (`:90`), which allows only `--name` / `--name=value` with a restricted value charset. Executed against 9 hostile inputs: `&`, `|`, `;`, `$( )`, `"` and `%` are all **rejected**; only `--x=..\..\evil` survives (harmless — the value reaches `Popen` as an argv element and `subprocess.list2cmdline` quotes it). The elevated path builds its command with `subprocess.list2cmdline(tokens)` (`:1281`) — argv, never a shell string built from raw user input. `%` being excluded also means no environment expansion.
2. **The user-supplied `binary_path` is validated at the *use* site, not the write site.** `find_binary(custom_path)` → `validate_zapret_binary` enforces: a drive letter (no UNC, no relative path), containment in `~/.nedotify/zapret` or `base_dir`, a basename in `{winws.exe, zapret.exe, winws}`, and a structurally valid PE. A value written through `save_setting` (which accepts any category/key) is therefore re-validated on every launch. The rejection is surfaced to the user (`services/zapret_service.py:1072-1077`) instead of being silently dropped. *(The gap is on the default-candidate path — see F-WN-10-4.)*
3. **The proxy bearer token never reaches the database.** `cache_stream` stores the raw provider URL (`core/database.py:2162-2194`); the per-session token (`secrets.token_urlsafe(24)`, regenerated on every proxy start — `core/proxy.py:1271-1276`) appears only in the URL handed to the WebView (`proxy.get_proxy_url`, `:1304-1334`) and is masked in the logs (`:489`). `prefetch_track` therefore does **not** write an authenticated URL into `stream_cache`.
4. **The download-status string set is exactly consistent** between producer and consumer: `pending | downloading | paused | completed | failed | cancelled` — written by `core/downloader.py` (`queue_download` → `pending`, `download_queue_set_downloading` → `downloading`, `pause_download` → `paused`, `mark_track_downloaded` → `completed`, the failure paths → `failed`, `_mark_queue_cancelled`/`cancel_batch` → `cancelled`) and by `core/download_store.py` (`rows()` ordering: downloading, pending, paused, failed, rest), and consumed by `ui/web_new_v2/js/downloads-view.js:9-12` (`statusLabels`) with no divergence. `get_downloads` (`core/api.py:4176-4181`) adds `user_error` only for `failed`, exactly where the UI reads it (`downloads-view.js:40`).
5. **`download_complete` honours the project contract** — `{'track_id': …}` only, no `file_path` (`core/downloader.py:839`), matching `WIN_AUDIT_CONTEXT.md` rule #7. `download_failed` carries the error plus a serialisable `describe_error` payload (`core/downloader.py:174-175`).
6. **`prefetch_track` respects the shared-lock rule and is exception-safe.** It guards `_prefetch_pending` with the existing `self._search_lock` (no second lock — `core/api.py:3650`, `:3666`, `:3675`), caps outstanding warmups at 2, releases the slot in a `finally`, survives an executor shutdown (`RuntimeError` → the slot is released and `False` returned, `:3679-3682`), never mutates the caller's dict (`candidate = dict(track_data)`, `:3658`), and is blocked in offline mode by the interception table (`core/api.py:502`). Pinned by `tests/test_playback_startup_performance.py:62-99`.
7. **`_clean_stream_cache` cannot escape its root.** The root is a fixed `~/.nedotify/streams` (taken from `CacheManager._streams_dir` or the literal fallback); `os.scandir` yields only direct children and `entry.is_file()` never produces a path outside it; `os.remove()` on a symlink removes the link, not the target. There is no path traversal and no way to delete the user's downloads (`~/.nedotify/downloads` is a different directory and is never scanned).
8. **`recover_stream` is bounded.** `core/playback_recovery.py` has an 18 s overall deadline with per-stage sub-budgets (8 s / 3 s / 4 s) and re-checks the offline flag between stages (`:131`, `:137`, `:149`, `:166`). The bridge's offline branch (`core/api.py:4168-4173`) does no network I/O at all.
9. **Smart-playlist rules cannot inject SQL.** `normalize_rule` (`services/smart_playlists.py:20-51`) rejects unknown keys, non-int day counts, non-bool flags, an over-long artist and an unknown sort; the artist value is bound as a parameter with `%`/`_`/`\` escaped (`services/smart_playlists.py:153-155`); `tracks()` validates `limit` (1..500), `offset` (0..100000) and a positive integer id. Pinned by `tests/test_smart_playlists.py:57-89`.
10. **The offline branch of `recover_stream` returning a raw filesystem path is fine** — the frontend converts a `C:\...` path into an authenticated proxy URL before assigning it to `<audio>.src` (`ui/web_new_v2/js/player.js:97-103`).
11. **`get_search_suggestions` is cheap enough to call after a failed search.** Measured on 4 000 tracks: 23.9–28.2 ms per call (`utils/search_query.py:62-101` reads 600 rows and applies an early-exit edit distance).

---

### 4. Coverage gaps

- **No frozen build and no real elevated launch.** F-WN-10-3 (integrity), F-WN-10-4 (CWD candidate) and F-WN-10-5 (`_MEIPASS` root) were verified by calling the service's own validators with synthetic inputs and by reading the PyInstaller/runtime path assumptions. The *consequences* (a real MITM, a real UAC prompt, a real privilege escalation) were not executed.
- **No UI observation.** The magnitude of the F-WN-10-6 UI-thread cost is inferred from the installed pywebview implementation (`webview/platforms/edgechromium.py:126-130`) plus the measured event count (400 events for 400 favourites); the on-screen effect was not observed.
- **F-WN-10-7 timings are synthetic.** 4 000 tracks / 20 000 history rows is a plausible but not a measured user profile; the `history` growth rate depends on real usage. The *shape* of the cost (correlated subqueries on an un-indexable expression) is a code fact, not a measurement.
- **`services/zapret_service.py` is 1 475 lines and owned by WN-26.** I read the launch, validation, extraction, update and status paths; I did **not** audit the PID-scan/`taskkill` machinery (`:557-728`), the status cache/refresh thread (`:1411-1475`) or the auto-update scheduler (`:1015-1059`) in depth.
- **No test in `tests/` exercises `AppApi._clean_stream_cache` for real** — the only reference is a monkeypatch (`tests/test_playback_startup_performance.py:57`); and **no test exercises `download_all_favorites`, `toggle_zapret`, `update_zapret`, `toggle_discord_rpc`, `get_listening_comparison`, `get_offline_library` or `set_offline_mode(True)` end-to-end**. `tests/test_offline_mode.py:33-49` covers `set_offline_mode(True/False)` only in the happy path (it stubs the downloader with `SimpleNamespace(pause_download=…)`, so the real pause/resume interplay of F-WN-10-10 is not exercised).
- **The full pytest suite was not run**; only the WN-10-adjacent test files were read.
- **`core/proxy.py` was traced only** for the stream-cache write path, the offline gate and the token handling; the proxy's own defects belong to WN-11 and were not reviewed.
- **`core/database.py`** was read only for the specific methods listed above; the schema/migration questions belong to WN-12.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — The stream-cache eviction policy has two owners.** `AppApi._clean_stream_cache` (`core/api.py:3595`) and `CacheManager.purge_stream_cache` (`utils/cache_manager.py:171`) both delete files from `~/.nedotify/streams`, with different rules, different ceilings (a hardcoded 350 MB vs the settings-driven quota), different protection rules and different DB-sync behaviour — and the bridge reaches into the manager's *private* `_streams_dir` attribute to find the root. The bridge should not own a filesystem policy: `CacheManager` should expose `purge_expired(max_age_hours)` next to `purge_stream_cache(quota_bytes)`, and the bridge should call one of them. This closes F-WN-10-1, F-WN-10-2 and the hidden 350 MB ceiling in one move.

**ARCH-2 — Offline mode is a scattered boolean, not a policy layer.** `is_offline(settings)` is consulted in eight modules (`core/api.py` ×10, `core/app.py` ×8, `core/proxy.py` ×3, `core/playback_recovery.py` ×4, `core/downloader.py`, `services/lyrics_lookup.py` ×4) and, in the bridge, as a **hand-maintained list of method names** (`AppApi._offline_bridge_result`, `core/api.py:461-512`). A newly added network-touching bridge method is *online by default* until somebody remembers to add its name — the prior run already found one omission (`get_waveform`). An `OfflinePolicy` object with `allows(method_name)` / `requires_network()` derived from a declared per-method capability would make the rule explicit, testable and impossible to forget.

**ARCH-3 — `AppApi` is a god object, and this area is the proof.** 30+ of the methods reviewed here are one-line adapters over a service. `get_smart_playlists`, `create_smart_playlist`, `update_smart_playlist`, `delete_smart_playlist` and `get_smart_playlist_tracks` each construct **a brand-new `SmartPlaylistService`** through `_smart_playlists()` (`core/api.py:4192-4194`) — five short-lived objects per UI action, each re-deriving the same constants. The services should be long-lived collaborators of `AppCore`, and the bridge should hold a reference.

**ARCH-4 — The bridge mixes three response conventions.** `get_feed` / `get_home_releases` / `get_home_mixes` return `[]` and communicate only through an event; `get_home_artists` returns the data **and** emits `artists_ready`; `get_smart_playlist_tracks` returns `{success, tracks}`; `download_all_favorites` returns `{success, count, total, message}`. "Did I read the return value or listen for the event?" is decided differently in every block of the file, and the codebase has already got this wrong elsewhere (`js/events.js:258` handles both `download_complete` and `track_downloaded`). One convention — or one envelope — would remove the ambiguity.

**ARCH-5 — The privileged Zapret launch is reachable from a bridge method that takes three free-form strings.** `toggle_zapret(enabled, mode, custom_args, binary_path)` forwards raw strings into a path that ends in `ShellExecuteW("runas")`. The validation is *correct*, but it lives in the callee, five frames below the trust boundary, and it is applied to only one of the three inputs (F-WN-10-4). A `ZapretLaunchRequest` value object — mode enum, validated args tuple, validated executable path — constructible only through the validator, would make the privileged launch structurally safe rather than conventionally safe.

**ARCH-6 — The Discord RPC "off" state is split between a settings flag and a live socket.** `toggle_discord_rpc` writes the setting and calls `clear_presence()`; the service keeps the connection open and `connected == True` (F-WN-10-12). `DiscordRPCService.set_enabled(bool)` owning both the flag and the socket would remove the split-brain state that `get_discord_rpc_status` currently reports.

**ARCH-7 — The bridge's batch-download contract has no single owner.** The `total` that `batch_download_started` announces (`core/api.py:3715`), the counters in `core/downloader.py` and the renderer in `js/library.js:78-101` are three independent interpretations of "how much is left". A single `BatchProgress` value object (announced total, completed, skipped, failed, phase) emitted by the downloader and rendered by the UI would remove the shrink/early-finish class of bugs in F-WN-10-11 and the payload-shape drift in F-WN-10-15.
