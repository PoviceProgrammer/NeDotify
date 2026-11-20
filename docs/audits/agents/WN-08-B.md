## AREA WN-08 — Bridge settings, onboarding, autostart, subscription, storage/quota, equalizer — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `core/api.py` | 200–339 (helpers: `_as_float`, `_SECRET_SETTING_KEYS`, `_mask_secrets`, `_bridge_write_error`, `_is_empty_secret_write`, `_normalize_cache_quota`), 340–339 continuation, 1122–1166 (`_emit`), 1840–1919 (`get_setting`/`set_setting`), 2740–3209 (**WN-08 range**), 3425–3479 (`open_local_file`, traced), 4015–4119 (**WN-08 range**), 4126–4170 (`get_offline_mode`/`set_offline_mode`, traced) |
| `core/settings.py` | 1–589 (whole file: `DEFAULT_SETTINGS`, `SettingsManager`, `_writer_loop`, `flush`, `sync_flush_now`) |
| `core/database.py` | 82–139 (`TRACK_IDENTITY_SQL`, `name_is_meaningful`), 1075–1184 (`add_track`), 1280–1339 (`get_downloaded_tracks`), 2030–2149 (`set_setting`, `set_settings_batch`, `get_setting`, `get_settings_by_category`, `get_all_settings`), 1723–1797 (`get_wrapped_stats`) |
| `utils/cache_manager.py` | 1–260 (`get_cache_size`, `get_storage_details`, `clear_all`, `_clear_dir`, `purge_stream_cache`) |
| `utils/file_scanner.py` | 1–181 (whole file) |
| `utils/tag_parser.py` | 1–149 (`parse_tags` fallback title/artist derivation) |
| `services/youtube_service.py` | 30–99 (`_detect_browser_cookies`), 350–360, 770–860 (cookie handling) |
| `services/base_service.py` | 20–79 (`normalize_proxy_url`) |
| `core/session.py` | 1–70 (`MAX_PERSISTED_QUEUE`, `save_session`) |
| `core/offline.py` | 10–76 (`is_offline`, `available_track`) |
| `main.py` | 505–549 (watchdog flush ordering) |
| `ui/web_new_v2/js/settings.js` | 200–319 (storage panel), 705–764 (`applySettingsFromBackend`), 1005–1054 (`onStorageInfo`, `saveSetting`), 1060–1139 (`loadSettings`, `initKeybinds`) |
| `ui/web_new_v2/js/hotkeys.js` | 1–160 (`DEFAULT_KEYBINDS`, `initHotkeys`) |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (whole file) |
| `ui/web_new_v2/js/equalizer.js` | grep of 182/201/339/342–345 |
| `ui/web_new_v2/js/utils.js` | 595–634 (`offlineImageUrl`, `getCoverUrl`) |
| `ui/web_new_v2/js/library.js` | 108–147 (import → `get_storage_info`) |
| `ui/web_new_v2/js/main.js` | 390–449 (settings bootstrap) |
| `ui/web_new_v2/js/events.js` | 305–334 (event dispatch) |
| `ui/web_new_v2/index.html` | 1796–1835 (quota/clear-cache controls) |
| `tests/test_settings_manager.py` | 1–538 (whole file) |
| `tests/test_settings_flush.py` | 1–229 (whole file) |
| `tests/test_settings_controls_ui.py` | 1–128 (whole file) |
| `tests/test_equalizer_controls_ui.py` | 1–70 (whole file) |
| `tests/test_keybind_contracts.py` | 1–204 (whole file) |
| `tests/test_onboarding.py` | 1–108 (whole file) |
| `tests/test_api_audit_b.py` | 455–614 (`clear_storage`, `set_cache_quota` pins) |
| `tests/conftest.py` | 1–176 (whole file: `SettingsStub`, `api` fixture) |
| `.venv_win/Lib/site-packages/webview/util.py` | 230–314 (pywebview bridge dispatch) |

**Callees traced into other areas** (defect in the callee belongs to the callee's area):

- `core/settings.py` → WN-14 (SettingsManager). Traced: `DEFAULT_SETTINGS`, `set/get`, `flush`, `sync_flush_now`, `_writer_loop`.
- `core/database.py` → WN-12. Traced: `add_track` (incl. the title/artist dedupe that sets `is_downloaded=1`), `get_downloaded_tracks`, `set_settings_batch`, `get_settings_by_category`, `get_wrapped_stats`.
- `utils/cache_manager.py` → WN-27. Traced: `get_cache_size`, `get_storage_details`, `clear_all`, `purge_stream_cache`.
- `utils/file_scanner.py` → WN-27. Traced: `scan_single_file` → `add_track`.
- `services/youtube_service.py` → WN-19. Traced: `_detect_browser_cookies` (does **not** copy cookies into settings).
- `core/offline.py` → WN-15. Traced: `is_offline`.
- `core/session.py` → WN-02. Traced: `save_session` (queue persisted into the `session` settings category).
- `core/proxy.py` / `services/base_service.py` → WN-11 / WN-18 (proxy URL normalisation, credential-bearing URL shape).
- JS side → WN-28/30/32 (`js/settings.js`, `js/feature-controls.js`, `js/hotkeys.js`, `js/equalizer.js`, `js/utils.js`, `js/library.js`, `js/main.js`, `js/events.js`).

---

### 2. Findings

#### F-WN-08-1  [P0] — `clear_storage("all")` deletes files anywhere on disk: `_delete_downloaded_files` has no path containment

- **File:** `core/api.py:3138-3154` (the deleter), `core/api.py:3105-3136` (the caller), `core/api.py:3436-3456` (`open_local_file`), `utils/file_scanner.py:128-139` (`add_track` with a local `file_path`), `core/database.py:1122-1127` (the row that gets `is_downloaded = 1`).
- **Confirmed:** yes — reproduced end-to-end with the real `DatabaseManager`, `FileScanner` and `AppApi` (script below), deleting a file that lives **outside** `~/.nedotify/`.
- **Description:** `clear_storage("all")` deletes every path found in `tracks.file_path` for rows with `is_downloaded = 1`, with **no check that the path is inside the app-owned download directory** (`~/.nedotify/downloads`). The set of rows it iterates is not limited to real downloads: `core/database.py:1122-1127` re-points an *existing provider row* at a user's local file and sets `is_downloaded = 1` when a local import matches an existing track by `LOWER(title)=LOWER(?) AND LOWER(artist)=LOWER(?)`. So a file the user owns in an arbitrary folder (`D:\Music\...`) becomes a deletion target.
- **Cause:** the destructive operation derives its targets from a DB column that is not a trusted, app-owned namespace, and no containment check (`os.path.realpath` + `os.path.commonpath` against `~/.nedotify/downloads`) is applied before `os.remove()`.
- **Trigger conditions:** (1) the app has a track row for title/artist X (any provider, e.g. played but not downloaded, `file_path` NULL); (2) the user opens their own local file `X - Y.<ext>` via Library → "Import" (`open_local_file` → `FileScanner.scan_single_file` → `add_track`); (3) anything later calls `clear_storage("all")` — currently only reachable from JS in the WebView (`window.pywebview.api.clear_storage('all')`); the shipped UI has **no** caller for `clear_storage` (only `clear_storage_cache`), so today's trigger is a script in the WebView or a future UI button.
- **User impact:** permanent, unannounced loss of the user's own music files (their only copy) — the worst outcome the `~/.nedotify/` contract ("clearing it is not a cleanup step. Ask first.") is meant to prevent. No confirmation dialog exists on any path.
- **Evidence:**
  ```python
  # core/api.py:3138
  def _delete_downloaded_files(self) -> int:
      """Delete every downloaded track file from disk. Returns files removed."""
      removed = 0
      tracks = self._core.db.get_downloaded_tracks() or []
      for t in tracks:
          ...
          fp = t.get("file_path")
          if not fp:
              continue
          try:
              if os.path.isfile(fp):
                  os.remove(fp)          # <-- no containment check
                  removed += 1
  ```
  ```python
  # core/database.py:1122
  if file_path and not row["file_path"]:
      cursor.execute(
          "UPDATE tracks SET file_path = ?, is_downloaded = 1 WHERE id = ?",
          (file_path, t_id),
      )
  ```
- **Reproduction / verification:** `C:\Users\Артур\AppData\Local\Temp\opencode\wn08_repro.py` (temp dir only, `os.path.expanduser` redirected, real `~/.nedotify` untouched). Output:
  ```
  1) youtube row: file_path=None is_downloaded=0
  2a) parse_tags -> {'title': 'Song', 'artist': 'Artist'}
  2) scanner imported: True title/artist from file: Song / Artist
  3) youtube row after local import: file_path='...\MyMusic\Artist - Song.wav' is_downloaded=1
  4) get_downloaded_tracks -> [(1, '...\MyMusic\Artist - Song.wav')]
  5) clear_storage('all') -> True
  6) local file still exists? False
  7) file is inside ~/.nedotify? False
  ```
  (step 2a: `parse_tags` derives title/artist from the *filename* when mutagen cannot read the file, so a file named `Artist - Song.wav` yields exactly `Song`/`Artist`.)
- **Suggested fix:** in `_delete_downloaded_files`, resolve each path (`os.path.realpath`) and keep only those under `os.path.realpath(~/.nedotify/downloads)`; log and skip everything else. Independently, stop `add_track` from setting `is_downloaded = 1` for `source == "local"` rows (that is WN-12's row, but it is what widens the blast radius).
- **Fix side effects:** a legitimate download that was moved by the user out of `~/.nedotify/downloads` would stop being deletable — acceptable, and it should be surfaced as "not under the app's download folder" rather than silently ignored. The DB-row mis-marking fix in WN-12 will make some rows that used to be "downloaded" become plain local rows; the library view must still show them.
- **Discovered by:** B

---

#### F-WN-08-2  [P2] — `clear_storage("all")` deletes the files but leaves the DB rows: the library keeps advertising tracks that no longer exist

- **File:** `core/api.py:3138-3154`; related `core/database.py:1284-1287` (`get_downloaded_tracks`), `utils/cache_manager.py:198-215` (the purge's protected-path set).
- **Confirmed:** yes (code read + the F-WN-08-1 run: after `clear_storage("all")` the row still had `is_downloaded = 1` and a `file_path` pointing at a deleted file).
- **Description:** `_delete_downloaded_files` only unlinks files. The `tracks` rows keep `is_downloaded = 1` and the stale `file_path`, so the Library/Downloads view keeps listing the tracks as downloaded, playback fails with "audio file not found", and `get_storage_info` still counts them (`track_count = len(downloaded_tracks)`) while `track_bytes` skips the missing file — i.e. "N tracks, 0 MB".
- **Cause:** the deletion path has no counterpart that updates the database, unlike `CacheManager.purge_stream_cache`, which explicitly reconciles `stream_cache.cached_file_path` in the same transaction (`utils/cache_manager.py:252-260`).
- **Trigger conditions:** any successful `clear_storage("all")`.
- **User impact:** the app reports state that is not true; the user sees a "downloaded" library whose files are gone and cannot tell which entries are broken. The stale `file_path` also keeps the path in `purge_stream_cache`'s protected set, so a re-download to the same path is permanently shielded from LRU eviction.
- **Evidence:**
  ```python
  # core/api.py:3148
  try:
      if os.path.isfile(fp):
          os.remove(fp)
          removed += 1
  except OSError as e:
      logger.warning("clear_storage: could not remove %s: %s", fp, e)
  # no UPDATE tracks SET is_downloaded = 0 / file_path = NULL
  ```
- **Reproduction / verification:** same script as F-WN-08-1; after step 5, `db.get_downloaded_tracks()` still returns the row and `os.path.exists(fp)` is `False`. `tests/test_api_audit_b.py:479-488` only asserts the file is gone — it does not assert the row is cleared, so the gap is untested.
- **Suggested fix:** in the same loop (or in one transaction after it), set `is_downloaded = 0` and `file_path = NULL` for rows whose file was removed; report the count of demoted rows in the method's return value.
- **Fix side effects:** the library loses the "downloaded" badge for those rows — that is the intent; anything that relied on `is_downloaded` as a proxy for "the user asked for this file" (e.g. `purge_stream_cache` protection) changes behaviour, which is the correct direction.
- **Discovered by:** B

---

#### F-WN-08-3  [P2] — Two incompatible definitions of "storage total" feed the same UI number, and it jumps after every cache clear

- **File:** `core/api.py:3034-3103` (`get_storage_info`), `core/api.py:4021-4029` (`get_storage_details`), `utils/cache_manager.py:104-135` (`get_storage_details`), `ui/web_new_v2/js/settings.js:235` and `:269` (`onStorageInfo(res.details)`), `ui/web_new_v2/js/settings.js:1015-1031` (`onStorageInfo`).
- **Confirmed:** yes (code read; the two shapes are visibly different and both feed the same `storage-total` label).
- **Description:** `get_storage_info()` returns `total = cache(streams+temp) + covers + downloaded-track bytes`, while `get_storage_details()` returns `used_bytes = cache(covers+streams+temp)` with **no** downloads. `clear_storage_cache()` and `set_cache_quota()` return the *second* shape in `details`, and the UI writes both into the same `#storage-total` element. So the label means "cache only" right after a clear and "cache + your music" the moment `get_storage_info()` runs again (e.g. after any local import — `js/library.js:119-121`).
- **Cause:** two independent implementations of the same metric, exposed as two different bridge payloads with no shared contract; the UI branches on `data.used_bytes !== undefined` instead of the backend naming one shape.
- **Trigger conditions:** open Settings → Storage; clear the cache; import a local file.
- **User impact:** the "Total" figure changes meaning and value between two refreshes of the same panel, so the user cannot tell whether the clear worked or how much of the number is their own music.
- **Evidence:**
  ```python
  # core/api.py:3079
  total_bytes = cache_bytes + covers_bytes + track_bytes     # includes downloads
  ...
  # utils/cache_manager.py:117 (reached via core/api.py:4025)
  used_bytes = self.get_cache_size()                          # covers+streams+temp only
  ```
  ```js
  // ui/web_new_v2/js/settings.js:235
  if (res.details) onStorageInfo(res.details);   // cache-only shape
  // ui/web_new_v2/js/settings.js:1085
  Promise.resolve(window.pywebview.api.get_storage_info()).then(onStorageInfo);  // cache+downloads shape
  ```
- **Reproduction / verification:** static trace of the two payload builders; the `_STORAGE_INFO_TTL` cache in `get_storage_info` also keeps the *old* numbers for up to 30 s after a clear, because `clear_storage_cache` never invalidates `self._storage_info_cache`.
- **Suggested fix:** make `get_storage_info` the single source (it already reports tracks/covers separately) and have `clear_storage_cache`/`set_cache_quota` return that same shape, or make `get_storage_info` delegate to `CacheManager.get_cache_size()` and add an explicit `downloads_bytes` field. Invalidate `_storage_info_cache` after any clear.
- **Fix side effects:** the "Total" number will start including (or explicitly exclude) downloads — whichever way is chosen, the UI label text must change with it, otherwise the number becomes "wrong" rather than "ambiguous".
- **Discovered by:** B

---

#### F-WN-08-4  [P2] — `get_settings()` omits the `network` category, so the persisted offline-mode flag never reaches the UI

- **File:** `core/api.py:2922-2938` (the hard-coded category list), `core/settings.py:52-56` (`"network": {"offline_mode": False}` is in the schema), `ui/web_new_v2/js/feature-controls.js:112`, `ui/web_new_v2/js/utils.js:526` and `:608`, `ui/web_new_v2/js/player.js:1440` and `:1524`.
- **Confirmed:** yes — verified by running the real `SettingsManager` + `AppApi` over a temp DB (script below).
- **Description:** `get_settings()` iterates a hand-written list of 22 category names. `network` is not among them, so the `offline_mode` flag the backend persists (`core/api.py:4135`) is never handed to the WebView. The frontend restores its state from `get_settings()` at startup (`ui/web_new_v2/js/main.js:409-419`) and from the localStorage cache that is written from the very same payload, so `window.settings.network` is `undefined` after every restart. `initFeatureControls()` then evaluates `window.settings?.network?.offline_mode === true` → `false`.
- **Cause:** the list of categories in `get_settings()` is a manual copy of `DEFAULT_SETTINGS`' key set that has already drifted (see the same script: `MISSING from get_settings(): ['network', 'subscription']`), plus four names that are *not* in the schema at all (`appearance`, `player`, `lyrics`, `system`) and only appear in the response after the user has changed something in them (`save_setting('queue_autopilot', …, 'player')`, `save_setting('lyrics_offset_…', …, 'lyrics')`) — i.e. the response shape is data-dependent.
- **Trigger conditions:** the user enables offline mode, then restarts the app.
- **User impact:** the UI shows offline mode OFF while the backend is still offline (the backend's own `is_offline()` is correct, so the behaviour diverges from the display); `offlineImageUrl()` stops blanking remote cover URLs, so the UI keeps trying to fetch covers over the network in offline mode; the flow-track path no longer bails out of the flow in offline mode. `get_offline_mode()` exists on the bridge but has **no** JS caller.
- **Evidence:**
  ```python
  # core/api.py:2929
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                'session', 'zapret']
  # 'network' is missing; 'subscription' is missing
  ```
  ```js
  // ui/web_new_v2/js/feature-controls.js:112
  applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  ```
- **Reproduction / verification:** `C:\Users\Артур\AppData\Local\Temp\opencode\wn08_settings.py` (temp DB, real `SettingsManager` + `AppApi`):
  ```
  categories returned by get_settings(): ['app', 'audio', 'auth', 'efficiency', 'equalizer', 'general',
    'hotkeys', 'interface', 'optimization', 'overlay', 'personalization', 'player_appearance',
    'services', 'session', 'storage', 'theme', 'ui', 'zapret']
  schema categories in DEFAULT_SETTINGS: [... 'network', ... 'subscription', ...]
  MISSING from get_settings(): ['network', 'subscription']
  network block present? False
  ```
- **Suggested fix:** derive the list from `DEFAULT_SETTINGS` (plus any runtime-created categories) instead of hard-coding it, or add `network` explicitly and have the frontend call `get_offline_mode()` at boot. The consumer side (`feature-controls.js`, `utils.js`) belongs to WN-30/WN-27.
- **Fix side effects:** `get_settings()` will start returning a `network` block, which changes the `freshStr !== cachedStr` comparison in `main.js:413` (one extra cache write on the first run after the change) and adds `offline_mode` to the localStorage cache — which is exactly what the frontend needs to restore the state.
- **Discovered by:** B

---

#### F-WN-08-5  [P2] — Credentials are handed to the WebView and stored in clear text: `auth.proxy_url`, `auth.cookies_file_path` and `subscription.key` are not masked

- **File:** `core/api.py:240-269` (`_SECRET_SETTING_KEYS`, `_mask_secrets`, `_is_empty_secret_write` — the helper itself sits in WN-03's range), consumed by `core/api.py:2925`, `:2935`, `:2959` (`get_settings` / `get_settings_by_category`) and `core/api.py:1860-1862` (`get_setting`); written by `core/api.py:2940-2953` (`save_setting`) and `core/settings.py:401-418` → `core/database.py:2049-2082` (`set_settings_batch`); leaked further by `ui/web_new_v2/js/settings.js:397` and `:1040` (`localStorage.setItem('nedotify_auth_proxy_url', …)`) and `ui/web_new_v2/js/main.js:414` (the whole settings blob → `nedotify_cached_settings`).
- **Confirmed:** yes — verified against the real `SettingsManager` + `AppApi` and by reading the raw SQLite rows.
- **Description:** the secret allow-list covers exactly two keys — `auth.yandex_token` and `auth.oauth_client_secret`. Everything else in the `auth` category travels to the frontend verbatim:
  - `auth.proxy_url` — a free-text field whose documented form is a full URL; `normalize_proxy_url` (`services/base_service.py:44-56`) explicitly accepts `http://user:password@host:port`, so the proxy password is shipped to the WebView and mirrored into `localStorage`;
  - `auth.cookies_file_path` — the user's local path (and Windows account name);
  - `subscription.key` — the licence key, readable in clear text through `get_settings_by_category('subscription')` and `get_setting('subscription.key')` (only `get_settings()` happens to omit the category).
  On disk, **all** secrets — the Yandex OAuth token, the OAuth client secret, the licence key and the proxy URL — sit as plain JSON strings in the `settings` table of `~/.nedotify/nedotify_storage.db`, readable by any process running as the user.
- **Cause:** the masking policy is expressed as a per-category key tuple in one module-level constant, with no notion of "this field may carry credentials", and there is no at-rest protection (no DPAPI / Windows Credential Manager) for the values that are written.
- **Trigger conditions:** the user configures a proxy with credentials, a Yandex token, or a licence key; then any `get_settings()` call (once per startup) hands them to the page and, for the proxy URL, into `localStorage`.
- **User impact:** a credential that the UI is explicitly told not to show (`yandex_token` is masked and shown as "saved") is exposed for the neighbouring fields; the proxy password and the licence key end up in the WebView's `localStorage`, which is also written to disk unencrypted, and in the SQLite file in clear text. Any script that ends up running in the WebView (or any local process) can read all of them.
- **Evidence:**
  ```python
  # core/api.py:240
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  ```
  Verification output (temp DB, real code):
  ```
  auth block -> {'cookies_file_path': 'C:\\Users\\Somebody\\cookies.txt', 'browser_cookies': 'none',
                 'yandex_token': '', 'proxy_url': 'http://myuser:myPassword@10.0.0.9:8080',
                 'oauth_client_secret': '', ..., 'has_yandex_token': True, ...}
  get_settings_by_category('subscription') -> {'key': 'LIC-KEY-12345', ...}
  get_setting('subscription.key') -> 'LIC-KEY-12345'
  get_setting('auth.proxy_url') -> 'http://myuser:myPassword@10.0.0.9:8080'

  raw rows in the SQLite settings table:
      auth.proxy_url = http://myuser:myPassword@10.0.0.9:8080
      subscription.key = LIC-KEY-12345
      auth.cookies_file_path = C:\Users\Somebody\cookies.txt
      auth.yandex_token = SUPER-SECRET-YANDEX-TOKEN
      auth.oauth_client_secret = SUPER-SECRET-OAUTH
  ```
- **Reproduction / verification:** `C:\Users\Артур\AppData\Local\Temp\opencode\wn08_settings.py`.
- **Suggested fix:** (a) treat `auth.proxy_url` as a secret (return it masked, with a `has_proxy_url` flag, exactly like the token) or strip its user-info component before returning it; (b) add `subscription.key` to the masked set and stop exposing it through `get_settings_by_category`/`get_setting`; (c) move the at-rest values to DPAPI (`CryptProtectData`) or the Windows Credential Manager and keep only a reference in `settings`. The `_SECRET_SETTING_KEYS` helper is WN-03's file range, but every consumer listed above is WN-08's.
- **Fix side effects:** the settings UI currently *pre-fills* the proxy field from `settings.auth.proxy_url` (`ui/web_new_v2/js/settings.js:963-964`); masking it means the field must show a placeholder instead, and the user must retype the URL to change it.
- **Discovered by:** B

---

#### F-WN-08-6  [P3] — `get_storage_info` re-implements the cache-size scan (5× slower than the manager's) and has no in-flight guard

- **File:** `core/api.py:3034-3103` (the walk), `utils/cache_manager.py:78-93` (`get_cache_size`, cached 60 s), `.venv_win/Lib/site-packages/webview/util.py:303-312` (a new thread per bridge call).
- **Confirmed:** yes — both the duplication and the timing were measured.
- **Description:** the API walks `streams/`, `temp/` and `covers/` with `os.walk` + `os.path.getsize` on every cache miss, while `CacheManager.get_cache_size()` already does the same measurement with `os.scandir` (one stat per entry, no double path building) and caches it for 60 s. The API-level result is additionally cached for only 30 s and the cache is not an in-flight guard: two concurrent calls both miss and both walk. pywebview dispatches **every** bridge call on a freshly spawned thread (`webview/util.py:308`), so N concurrent `get_storage_info()` calls mean N concurrent full directory walks, and the UI triggers one after every local import (`ui/web_new_v2/js/library.js:119-121`).
- **Cause:** the storage panel needs a different breakdown (cache / covers / downloads) and the author re-walked the tree instead of composing `CacheManager.get_cache_size()` with a covers-only measurement.
- **Trigger conditions:** a large cover cache (one `cover_<track_id>` file per track) plus repeated or concurrent `get_storage_info()` calls.
- **User impact:** each call occupies a thread for the duration of the walk; the numbers arrive late and the CPU/disk cost is duplicated. The UI thread is not blocked (pywebview runs the call on its own thread), so this is a background cost, not a freeze.
- **Evidence:** measurement over a synthetic tree with 4 000 covers + 1 500 stream files (temp dir, real profile untouched), `C:\Users\Артур\AppData\Local\Temp\opencode\wn08_perf.py`:
  ```
  AppApi.get_storage_info walk: 46.9 ms per call  (4000 covers + 1500 streams)
  CacheManager.get_cache_size:  9.2 ms per call  (4000 covers + 1500 streams)
  ```
  (≈5× slower; the gap grows linearly with the library size.)
- **Reproduction / verification:** the script above; `api.get_storage_info` body copied verbatim from `core/api.py:3047-3077`.
- **Suggested fix:** build `get_storage_info` on `CacheManager.get_cache_size()` plus a covers-only measurement, and guard the whole method with a lock so concurrent calls share one walk.
- **Fix side effects:** `get_cache_size()` has its own 60 s TTL, so the panel's numbers would lag up to 60 s instead of 30 s unless `mark_cache_dirty()` is called after a clear.
- **Discovered by:** B

---

#### F-WN-08-7  [P3] — The equalizer round-trip is unvalidated and the EQ state lives in three stores

- **File:** `core/api.py:3173-3190` (`get_equalizer` / `set_equalizer`), `core/settings.py:238-241` (the schema), `ui/web_new_v2/js/equalizer.js:182`, `:201`, `:339`, `:342-345`.
- **Confirmed:** yes (code read).
- **Description:** `set_equalizer(preamp, bands)` accepts any value: `bands` is not length-checked, not type-checked and not range-checked, and `if bands:` means an **empty** list is silently ignored while the old bands stay. `get_equalizer()` returns the default `[0]*10` when nothing was ever configured, so "not configured" and "10 flat bands" are indistinguishable — the frontend has to keep its own state to tell them apart. In fact the EQ is stored three times: `localStorage['nedotify_equalizer']` (frontend), the backend `equalizer` category (`preamp`+`bands` via `set_equalizer`, `mode` via `save_setting`), and `window.settings.equalizer` (in-memory). The backend is the only durable one, but the frontend restores from `localStorage` first and from the backend second, which is the race `tests/test_equalizer_controls_ui.py:40-54` has to paper over.
- **Cause:** the bridge exposes the DSP state as free-form Python objects with no schema, while the UI treats it as a typed record (`{preamp, bands[10], mode}`).
- **Trigger conditions:** any caller that sends a malformed band array, or the "reset" path that sends an empty array.
- **User impact:** a malformed write is persisted and then re-serialised on every `get_settings()` call; the three stores can disagree, and the frontend's late-restore race is a permanent part of the design.
- **Evidence:**
  ```python
  # core/api.py:3180
  def set_equalizer(self, preamp: float = 0, bands: list = None):
      self._core.settings.set("equalizer", "preamp", preamp)
      if bands:                                   # empty list -> silently dropped
          self._core.settings.set("equalizer", "bands", bands)
      return True
  ```
  ```js
  // ui/web_new_v2/js/equalizer.js:339
  localStorage.setItem('nedotify_equalizer', JSON.stringify({ preamp: eqPreamp, bands: eqBands, mode: currentEqMode }));
  ```
- **Reproduction / verification:** `AppApi(core).set_equalizer(0, [])` leaves the previous bands in `settings`; `set_equalizer(0, list(range(50)))` persists 50 bands, which `get_settings()` then serialises on every call.
- **Suggested fix:** validate the payload in `set_equalizer` (fixed band count / numeric range), store the band count in the schema, and have the frontend treat the backend as the single source of truth (drop the `localStorage` copy or make it a write-through cache with a version stamp).
- **Fix side effects:** a strict band count will reject the 3/6/10-band layouts the UI supports unless the count is part of the record (`mode`) — the payload shape has to change together with the frontend.
- **Discovered by:** B

---

#### F-WN-08-8  [P3] — The bridge writes settings keys that the schema does not declare

- **File:** `core/api.py:2803-2804` (`theme.custom_palette_enabled`), `core/api.py:4076-4078` (`storage.cache_quota_gb`), `core/settings.py:145-155` (`DEFAULT_SETTINGS["storage"]`), `core/settings.py:177-195` (`DEFAULT_SETTINGS["theme"]`).
- **Confirmed:** yes (code read; `custom_palette_enabled` and `cache_quota_gb` are absent from `DEFAULT_SETTINGS`).
- **Description:** `complete_onboarding` writes `theme.custom_palette_enabled`, and `set_cache_quota` writes `storage.cache_quota_gb` — neither key is declared in `DEFAULT_SETTINGS`. Undeclared keys are still persisted and returned (`_load_all` preserves them, `get_category` returns them), but they are missing from the schema-driven defaults, are not covered by `reset_category()`, and are invisible to any schema-based consumer. `storage.cache_quota_gb` is the key the quota UI reads (`ui/web_new_v2/js/settings.js:258`) *and* the key `CacheManager.get_storage_details()` reads (`utils/cache_manager.py:112`) — yet it is not in the schema, so on a fresh install `get_settings()['storage']` has no `cache_quota_gb` until the user touches the dropdown.
- **Cause:** the schema (`DEFAULT_SETTINGS`) and the bridge's writers are maintained independently; there is no "declared key" check on write.
- **Trigger conditions:** onboarding completion, changing the cache quota, or a settings reset.
- **User impact:** schema-driven features (reset-to-default, validation, documentation) silently skip these keys; a future "reset storage settings" would not restore the quota to its default.
- **Evidence:**
  ```python
  # core/api.py:2803
  for key, value in {"theme": selected, "theme_mode": selected_mode, "mode": selected_mode,
                     "custom_palette_enabled": False, "custom_primary": "", "custom_accent": ""}.items():
  # core/api.py:4077
  self._core.settings.set("storage", "cache_quota_gb", quota_val)
  ```
  `DEFAULT_SETTINGS["storage"]` = `['auto_cache_streams', 'auto_download_favorites', 'auto_download_favorites_quota_gb', 'cache_covers', 'cache_size_mb', 'scan_folders']` — no `cache_quota_gb`; `DEFAULT_SETTINGS["theme"]` has no `custom_palette_enabled`.
- **Reproduction / verification:** `python -c "from core.settings import DEFAULT_SETTINGS as D; print(sorted(D['storage'])); print(sorted(D['theme']))"`.
- **Suggested fix:** declare both keys in `DEFAULT_SETTINGS` (with their real defaults) and reject or normalise undeclared `(category, key)` pairs at the bridge boundary.
- **Fix side effects:** adding `cache_quota_gb` to the schema changes the default from "absent" to an explicit value; the frontend already defaults to 5 GB, so align the schema default with that.
- **Discovered by:** B

---

### 3. Clean areas

- **Subscription / licensing is genuinely inert, and honestly documented.** `validate_subscription_key` and `get_subscription_info` (`core/api.py:2892-2920`) are disabled behind `LICENSE_VALIDATION_ENABLED = False` and **have no JS caller** (verified across the whole `ui/` tree). The docstring states the reason ("no caller exists (the UI never asks)"), the flag is honoured rather than hard-coded, and the schema block is explicitly marked "UNUSED - do not wire anything up" (`core/settings.py:265-278`). The *only* residual issue is the clear-text exposure of `subscription.key` (F-WN-08-5), not the validation logic itself. The validation is **not** client-side-only bypassable in a meaningful sense: there is no server, no key check and no gated feature — an empty key unlocks nothing because nothing is gated.
- **YouTube browser cookies are NOT copied into settings.** `services/youtube_service.py:39-57` (`_detect_browser_cookies`) only probes the browsers with `yt_dlp.cookies.extract_cookies_from_browser(b)` and remembers the **browser name**; the only thing it persists is `self.settings.set("auth", "browser_cookies", b_name)` (`youtube_service.py:854`). No cookie value ever enters the `settings` table. (`auth.cookies_file_path` is a *path* the user types, not a cookie jar.)
- **No SQL injection in the Wrapped stats.** `get_wrapped_stats(period)` (`core/database.py:1723-1790`) uses the parameter only in `if period == "week"`-style comparisons; the interpolated `where_clause` is one of three constant strings. No user input reaches the SQL text.
- **Write amplification is not a problem.** `save_setting` → `SettingsManager.set()` only marks the key dirty; the writer thread coalesces a burst into one `set_settings_batch` transaction (`core/settings.py:443-506`, `core/database.py:2049-2082` → one `executemany` inside one transaction). A volume-slider drag costs one COMMIT, not ten. `set_settings_batch` is all-or-nothing and returns the written count, and `flush()` re-queues a short batch instead of dropping it.
- **The settings writer thread's lifecycle is handled on every exit path that can be handled.** `atexit.register(self.flush)` (`core/settings.py:313`), `core/app.py:558` (`settings.flush` in `cleanup()`), and `main.py:525-538` (watchdog: `sync_flush_now()` → `cleanup()` → `sync_flush_now()` → `os._exit(3)`) cover normal exit, orderly shutdown and the hard-exit watchdog. The only loss window is an ungraceful kill (Task Manager / power loss) of up to `FLUSH_INTERVAL_SECONDS = 0.5 s` of settings. Lock ordering is consistent (`_flush_lock` → `_lock`); `flush()` releases `_lock` before the DB write, so a slow write never blocks `get()`/`set()`.
- **The hotkey mirror is defined in exactly two places and is pinned.** `core/settings.py:119-144` (`DEFAULT_SETTINGS["hotkeys"]`) and `ui/web_new_v2/js/hotkeys.js:4-15` (`DEFAULT_KEYBINDS`) hold the same 10 ids with the same values; `js/settings.js:5` *imports* `DEFAULT_KEYBINDS` rather than redefining it, and `core/api.py` contains no hotkey defaults, so there is no third table. `tests/test_keybind_contracts.py` pins id-set equality, value equality, the absence of the legacy `mute` id, the absence of a second dispatcher, and that every id has a branch in `executeHotkeysAction`.
- **`complete_onboarding` validates its input strictly and refuses to acknowledge completion before the data is on disk.** Booleans are type-checked, the theme/mode/preset are allow-listed, the accent colour is regex-checked, the device string is length-checked, and `sync_flush_now()` gates the `first_launch_done` / `onboarding_completed` flags (`core/api.py:2761-2837`). `tests/test_onboarding.py` pins all of it, including the on-disk round trip through a real `SettingsManager`.
- **`update_autostart` is careful about the registry.** It writes exactly the `HKCU\...\Run` value name the installer uses, removes the legacy names on both the enable and the disable path, and anchors the non-frozen command line to `main.py`'s absolute path instead of the CWD (`core/api.py:2839-2890`).
- **The quota normalisation is a pure, well-tested function.** `_normalize_cache_quota` (`core/api.py:272-327`) has an explicit precedence table, rejects negatives, and 0 is consistently "no limit" and never reaches `purge_stream_cache(quota_bytes=0)`. `tests/test_api_audit_b.py:532-610` pins the whole table.

---

### 4. Coverage gaps

- **I did not execute the pywebview runtime.** The bridge dispatch model was read from the installed `webview/util.py` (a new thread per call) rather than observed; the "N concurrent `get_storage_info()` calls = N concurrent walks" claim is therefore a code-level inference, not a measurement. The per-call walk cost *was* measured (F-WN-08-6).
- **The WebView XSS surface was not audited.** The severity of the WebView-side credential exposure (F-WN-08-5) depends on whether remote metadata (track titles, artist names, playlist names) can be injected into the DOM unescaped. I sampled the UI and found `escapeHtml` used consistently in the `innerHTML` call sites I checked (`js/library-view.js`, `js/home.js`, `js/profile.js`, `js/smart-playlists.js`, `js/search-discovery.js`), but `js/home-shell.js:30` and `js/search-discovery.js:38` build markup through `coverImgHtml({… alt: track.title …})`, whose escaping I did not verify. That is WN-28/WN-29's area; it is the missing evidence that would turn F-WN-08-5 from "credentials reach the page" into "credentials are exfiltratable".
- **The `is_downloaded = 1` mis-marking (F-WN-08-1) is rooted in `core/database.py::add_track`, which is WN-12's area.** I proved the effect and the mechanism, but did not audit the whole `add_track`/`update_track` surface for other ways a row can acquire a foreign `file_path`.
- **I did not run the pytest suite** (read-only review; the repo's own tests are the authority on the parts I quote). The `clear_storage` / `set_cache_quota` pins quoted from `tests/test_api_audit_b.py` were read, not re-executed.
- **The `~/.nedotify` tree of the real user was never read or written.** All verification ran against temp directories with `os.path.expanduser` redirected, exactly as `tests/conftest.py::redirect_home` does.
- **`core/offline.py` was read only for `is_offline`**; the offline-library behaviour itself is WN-15's.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — One authoritative settings store, one authoritative category list.**
`core/settings.py::SettingsManager` is the authoritative store (in-memory cache + write-behind flusher) and every bridge read/write goes through it — that part is sound. But the *shape* of the tree is defined twice: `DEFAULT_SETTINGS` (the schema) and the hand-written list in `AppApi.get_settings` (`core/api.py:2929`). They have already drifted (`network` and `subscription` missing; `appearance`/`player`/`lyrics`/`system` not in the schema), which is the direct cause of F-WN-08-4. Deriving the list from `DEFAULT_SETTINGS` (plus runtime-created categories) removes the second source of truth.

**ARCH-2 — The theme/interface duplication in the schema is a latent trap.**
Nine keys are declared in **both** `DEFAULT_SETTINGS["theme"]` and `DEFAULT_SETTINGS["interface"]`: `accent_color`, `custom_themes`, `font_family`, `glass_blur`, `glass_color_intensity`, `name`, `theme`, `transparency_enabled`, `transparency_level`. The frontend writes `theme.font_family` while `SettingsManager.font_family` reads `interface.font_family` — a divergence already pinned as a bug by `tests/test_settings_manager.py:509-537` ("the property never sees it"). The schema owner is WN-14; the bridge surface that exposes both copies side by side is WN-08's `get_settings`.

**ARCH-3 — A dead second category reader with an incompatible shape.**
`core/database.py:2100-2115` (`get_settings_by_category`) selects `WHERE category = ?` and returns the **full** key (`"audio.volume"`) as the dict key, because the batch writer stores the key as `f"{cat}.{k}"` (`core/settings.py:457`). `AppApi.get_settings_by_category` returns the **bare** key. The DB-level method has no production caller, so it is a trap for the next person who wires it up. Either delete it or make it return bare keys.

**ARCH-4 — Eleven of the ~22 WN-08 bridge methods are unreachable from the UI.**
Verified by scanning every `.js`/`.html` under `ui/`: `get_all_settings`, `save_theme`, `update_setting`, `get_personalization`, `save_personalization`, `get_recommendation_quality`, `get_storage_details`, `validate_subscription_key`, `get_subscription_info`, `set_artist_alias` and — most importantly — `clear_storage` (the destructive one). `get_all_settings` is a pure alias of `get_settings` and its name is wrong (it does not return all settings). A bridge surface of ~200 methods, of which the destructive one is exposed but unused, widens the attack surface for no benefit. Note the asymmetry: `get_storage_details` (the quota-metrics reader) is dead while `get_storage_info` (the live one) uses a *different* metric definition (F-WN-08-3).

**ARCH-5 — The equalizer and the hotkeys each have three stores.**
Equalizer: `localStorage['nedotify_equalizer']`, the backend `equalizer` category, and `window.settings.equalizer` (F-WN-08-7). Hotkeys: `localStorage['nedotify_keybinds']`, the backend `hotkeys` category, and `window.settings.hotkeys` — with the *additional* twist that the backend table is the mirror of the frontend table and the frontend overwrites its own defaults from the backend at startup. Both cases are "two durable copies of a preference with no reconciliation rule". The hotkey case is at least pinned by a contract test; the equalizer case is not.

**ARCH-6 — Storage metrics should live in one place.**
`CacheManager.get_cache_size()` (cached, `os.scandir`) and `AppApi.get_storage_info()` (uncached, `os.walk`) measure the same tree, and `CacheManager.get_storage_details()` adds a third projection with a different meaning of "used" (F-WN-08-3, F-WN-08-6). The cache manager is the natural owner; the bridge should project its numbers, not re-derive them.

**ARCH-7 — Secret handling needs a policy, not a two-entry list.**
`_SECRET_SETTING_KEYS` (`core/api.py:240`) is a hand-maintained tuple of two keys, and it is the *only* thing standing between the OAuth token and the WebView. The same list has to be extended every time a credential-bearing field is added, and it says nothing about at-rest storage. A declarative "secret field" marker on the schema (plus DPAPI / Credential Manager at rest) would make the policy default-deny instead of default-allow (F-WN-08-5).

**ARCH-8 — Destructive operations need a declared blast radius and a confirmation.**
`clear_storage("all")` is the only bridge method that unlinks user files. It has no confirmation, no dry-run, no path containment, and no undo, and it is reachable from the WebView. A declared contract — "this operation only ever touches paths under `~/.nedotify/downloads`, it is confirmed by the user, and it reports what it removed" — would have caught F-WN-08-1 and F-WN-08-2 by construction.
