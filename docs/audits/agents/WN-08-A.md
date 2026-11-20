# WIN Audit — WN-08 Role A (Correctness & Reliability)

## AREA WN-08 — Bridge settings, onboarding, autostart, subscription, storage/quota, equalizer — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `core/api.py` | 1–120 (module constants: `LICENSE_VALIDATION_ENABLED`, `AUTOSTART_RUN_*`), 215–334 (`_as_float`, `_mask_secrets`, `_bridge_write_error`, `_is_empty_secret_write`, `_normalize_cache_quota`), 335–404 (`AppApi.__init__`), 1840–1919 (`get_setting`/`set_setting` context), **2750–3199 (assigned range)**, **4015–4124 (assigned range)**, 4125–4169 (`get_offline_mode`/`set_offline_mode`, callee trace) |
| `core/settings.py` | 1–589 (whole file: `DEFAULT_SETTINGS`, `SettingsManager.get/set/flush/get_category/_load_all`) |
| `core/database.py` | 1060–1139 + 1272–1291 (`add_track` / `mark_track_downloaded` / `get_downloaded_tracks`), 1569–1628 (`get_recommendation_quality`), 1723–1832 (`get_wrapped_stats`), 2010–2129 (`_serialize_setting`, `set_setting(s_batch)`, `get_setting(s_by_category)`, `get_all_settings`), 82 (`TRACK_IDENTITY_SQL`), 274–286 (`history` schema) |
| `core/offline.py` | 1–77 (whole file) |
| `utils/cache_manager.py` | 1–299 (`__init__`, `get_cache_size`, `get_storage_details`, `clear_all`, `_clear_dir`, `purge_stream_cache`) |
| `utils/file_scanner.py` | 100–159 (`_import_file` → `db.add_track(file_path=...)`) |
| `services/artist_identity.py` | 1–63 (whole file) |
| `core/app.py` | 110–111 (`self.cache`, `self.scanner` wiring), grep for `scanner`/`autostart` |
| `installer.iss` | 52–84 (`[Registry]` Run entry) |
| `ui/web_new_v2/js/hotkeys.js` | 1–256 (whole file) |
| `ui/web_new_v2/js/equalizer.js` | 1–351 (whole file) |
| `ui/web_new_v2/js/onboarding.js` | 1–238 (whole file) |
| `ui/web_new_v2/js/settings.js` | 180–359, 700–819, 990–1139 |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (whole file) |
| `ui/web_new_v2/js/main.js` | 380–479, 520–579 |
| `ui/web_new_v2/js/utils.js` | 598–627, 1080–1100 |
| `ui/web_new_v2/js/player.js` | 230–245, 1435–1445, 1520–1528 (grep context) |
| `ui/web_new_v2/js/library.js` | 105–144, 180–209 |
| `ui/web_new_v2/index.html` | 1790–1820 (`select-cache-quota` options) |
| `docs/audits/WIN_AUDIT_CONTEXT.md`, `docs/audits/WIN_AUDIT_AREAS.md` | whole files |
| `tests/test_keybind_contracts.py`, `tests/test_api_f1_audit.py`, `tests/test_api_audit_b.py` | executed (111 passed) |

**Callees traced into other areas** (defect in a callee → owning area; listed for attribution only):

- `core/settings.py` `SettingsManager` → **WN-14** (settings manager & hotkey table)
- `core/database.py` `add_track` / `get_downloaded_tracks` / `get_wrapped_stats` / `get_recommendation_quality` / `_serialize_setting` → **WN-12** (SQLite persistence layer)
- `utils/cache_manager.py` `CacheManager.clear_all` / `purge_stream_cache` / `get_storage_details` → **WN-27** (utility modules)
- `utils/file_scanner.py` `FileScanner._import_file` → **WN-27**
- `services/artist_identity.py` → **WN-18**
- `core/offline.py` → **WN-15**
- `ui/web_new_v2/js/settings.js` (`onStorageInfo`, `saveSetting`), `js/feature-controls.js`, `js/utils.js`, `js/player.js`, `js/equalizer.js`, `js/onboarding.js`, `js/hotkeys.js` → **WN-30 / WN-32 / WN-29 / WN-28**

---

### 2. Findings

#### F-WN-08-1  [P1] — `get_settings()` drops the `network` category, so the persisted offline-mode state never reaches the UI

- **File:** `core/api.py:2922-2938` (list at `:2929`); consumers `ui/web_new_v2/js/feature-controls.js:112,133`, `ui/web_new_v2/js/utils.js:526,608`, `ui/web_new_v2/js/player.js:1440,1524`; defaults `core/settings.py:52-55`
- **Confirmed:** yes
- **Description:** `get_settings()` assembles the whole tree from a hand-written list of category names. That list does not contain `network`, so `network.offline_mode` is never returned to JS. `get_all_settings()` (`:2955`) is the same call. The frontend never calls `get_offline_mode()` (zero hits in `ui/web_new_v2`), it only reads `window.settings.network.offline_mode` — which is therefore `undefined` after every fresh settings load.
- **Cause:** the category list is a duplicated copy of `DEFAULT_SETTINGS`' keys that has drifted (`network` was added to `core/settings.py` but never to the bridge list). `SettingsManager.get_category("network")` still returns `{'offline_mode': True}` — only the bridge drops it.
- **Trigger conditions:** the user enables offline mode, then restarts the app (or the app reloads settings). Any `get_settings()` response replaces `window.settings` wholesale (`js/main.js:415`), so `window.settings.network` disappears again even if `applyOfflineState` had created it.
- **User impact:** the app starts in offline mode but the UI shows online mode: the `offline-mode` CSS class is not applied, the "offline" note stays hidden, `offlineImageUrl()` (`js/utils.js:607-613`) no longer blanks remote image URLs so covers are fetched from the network, the offline local-file URL rewrite is skipped, and `prefetch_track` is fired although the backend refuses network work (`core/api.py:4132-4161` pauses downloads and rewrites the queue to local files only).
- **Evidence:**
  ```python
  # core/api.py:2929
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                'session', 'zapret']
  ```
  ```js
  // ui/web_new_v2/js/feature-controls.js:112
  applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  ```
- **Reproduction / verification:** AST comparison of the `categories` literal in `core/api.py` against `DEFAULT_SETTINGS` keys → `in DEFAULT but MISSING from api: ['network', 'subscription']`. Harness (real `SettingsManager` + `AppApi`): `get_settings()` returns 18 categories, `'network' in result → False`, while `settings.get_category("network") → {'offline_mode': False}`. Harness script: `%TEMP%\opencode\audit_reports\verify_wn08.py` (block 1).
- **Suggested fix:** derive the list from `core.settings.DEFAULT_SETTINGS` (plus the runtime-only categories `lyrics`/`player` that `save_setting` creates) instead of hardcoding it; keep `subscription` excluded deliberately (or mask it) and add a comment stating why.
- **Fix side effects:** the frontend would then receive `network.offline_mode` on every settings load; `applyOfflineState` must tolerate it (`window.settings.network` already exists then). `subscription.key` must stay out of the tree — add it to `_SECRET_SETTING_KEYS`/masking before adding it to the list.
- **Discovered by:** A

---

#### F-WN-08-2  [P1] — `clear_storage("all")` deletes files outside `~/.nedotify` (the user's own media) and leaves dangling DB rows

- **File:** `core/api.py:3105-3154` (`clear_storage` at `:3105`, `_delete_downloaded_files` at `:3138`); contributing callee `core/database.py:1088-1091,1122-1126` (→ **WN-12**), `utils/file_scanner.py:128-139` (→ **WN-27**); non-negotiable rule #3 in `docs/audits/WIN_AUDIT_CONTEXT.md:80-81`
- **Confirmed:** yes
- **Description:** `_delete_downloaded_files()` deletes every path found in `tracks.file_path` for rows with `is_downloaded = 1`, with **no check that the path lives under `~/.nedotify/downloads`** and **no DB update** afterwards. A locally imported track can end up with `is_downloaded = 1` and a `file_path` pointing at the user's own media folder: `add_track()` (`core/database.py:1122-1126`) matches an existing row by `LOWER(title)=LOWER(?) AND LOWER(artist)=LOWER(?)` and then runs `UPDATE tracks SET file_path = ?, is_downloaded = 1`.
- **Cause:** the destructive decision trusts the `tracks.file_path` column as "a file the app owns", while that column also holds paths to files the user owns (media folder / imported files). The delete step also does not reset `is_downloaded`/`file_path`, so the DB keeps pointing at files that no longer exist.
- **Trigger conditions:** (1) the user has a track in the library from a streaming source (no `file_path`); (2) the user adds their music folder to the library and the scanner imports the same title+artist → the row is re-pointed at the user's file and marked `is_downloaded = 1`; (3) anything calls `clear_storage("all")`.
- **User impact:** the user's own music files are permanently deleted from their media folder (data loss outside `~/.nedotify/`), and the library keeps listing those tracks as downloads with a `file_path` that no longer exists (broken "downloaded" entries, `core/offline.py:35-59` then reports them as unavailable).
- **Evidence:**
  ```python
  # core/api.py:3145-3151
  fp = t.get("file_path")
  if not fp:
      continue
  try:
      if os.path.isfile(fp):
          os.remove(fp)
          removed += 1
  ```
  ```python
  # core/database.py:1122-1126
  if file_path and not row["file_path"]:
      cursor.execute(
          "UPDATE tracks SET file_path = ?, is_downloaded = 1 WHERE id = ?",
          (file_path, t_id),
      )
  ```
- **Reproduction / verification:** end-to-end harness with the real `DatabaseManager` + `AppApi` and a throwaway DB (`%TEMP%\opencode\audit_reports\verify_wn08_clear.py`):
  ```
  1) online row: id=1 is_downloaded=0 file_path=None
  2) after local import: same id=1 is_downloaded=1 file_path='...\MyMusic\Artist - Title.mp3'
  3) file exists before clear_storage('all'): True
  4) clear_storage('all') -> True
  5) file exists AFTER  clear_storage('all'): False
  6) DB rows still say: [(1, 1, '...\MyMusic\Artist - Title.mp3')]
  ```
- **Suggested fix:** restrict deletion to files under the app-owned download root (`os.path.commonpath` against `~/.nedotify/downloads`) and skip everything else; afterwards reset `is_downloaded = 0, file_path = NULL` for the rows whose file was removed (or mark them "missing") in the same transaction.
- **Fix side effects:** real downloads deleted through `core/downloader.py` must keep their `~/.nedotify/downloads` prefix — verify the downloader's target directory before adding the root check, otherwise the "all" path would stop deleting anything. Separately, `add_track` should not set `is_downloaded = 1` for a local media file (**WN-12**).
- **Discovered by:** A

---

#### F-WN-08-3  [P2] — `get_storage_info()` caches for 30 s and is never invalidated by the clear/quota operations

- **File:** `core/api.py:3030-3103` (cache read `:3036-3039`, write `:3091`), `core/api.py:3105-3136` (`clear_storage`), `core/api.py:4031-4095` (`set_cache_quota`), `core/api.py:4097-4108` (`clear_storage_cache`)
- **Confirmed:** yes
- **Description:** `get_storage_info` memoises its result for `_STORAGE_INFO_TTL = 30.0` seconds. No other method in the codebase clears `self._storage_info_cache` (the whole repository contains exactly two references to that attribute, both inside `get_storage_info`). `clear_storage_cache()`, `clear_storage()` and `set_cache_quota()` therefore leave a stale snapshot behind, and the cache-hit path re-emits the stale payload to the UI.
- **Cause:** the TTL cache was added to avoid re-walking the cache tree on every settings render, but no invalidation hook was added for the mutating operations.
- **Trigger conditions:** open the storage panel (fills the cache) → clear the cache / change the quota → within the next 30 s any `get_storage_info()` call (settings panel open, library import, `library.js:119,191`) returns the pre-clear numbers and re-emits them.
- **User impact:** the storage panel flips back to the old totals right after the user pressed "Очистить кэш" — the clear looks like it did nothing (or like it deleted the wrong thing), and the "Кэш / Защищено" figures contradict the toast.
- **Evidence:**
  ```python
  # core/api.py:3036-3039
  cached = getattr(self, "_storage_info_cache", None)
  if cached and (time.monotonic() - cached[0]) < self._STORAGE_INFO_TTL:
      self._emit("storage_info", cached[1])
      return cached[1]
  ```
  ```python
  # core/api.py:4097-4104  (clear_storage_cache - no invalidation)
  self._core.cache.clear_all()
  details = self._core.cache.get_storage_details()
  self._emit("storage_updated", details)
  ```
  `grep "_storage_info_cache"` over the repository → only `core/api.py:3036` and `core/api.py:3091`.
- **Reproduction / verification:** call `get_storage_info()` (populates the cache) → `clear_storage_cache()` → call `get_storage_info()` again within 30 s → the returned payload still contains the pre-clear `total`/`tracks`/`covers` values and is re-emitted as `storage_info` (`ui/web_new_v2/js/events.js:317-320` → `onStorageInfo`).
- **Suggested fix:** drop `self._storage_info_cache` in `clear_storage`, `clear_storage_cache` and `set_cache_quota` (and after any download/import that changes the library size).
- **Fix side effects:** invalidating on every mutation makes the next `get_storage_info()` walk the tree again — that walk is the reason the TTL exists, so keep the TTL for the read-only path only.
- **Discovered by:** A

---

#### F-WN-08-4  [P2] — `get_storage_info()` and `get_storage_details()` return incompatible shapes that feed the same three UI labels with different meanings

- **File:** `core/api.py:3084-3090` (`get_storage_info` result) vs `core/api.py:4021-4029` (`get_storage_details`); consumer `ui/web_new_v2/js/settings.js:1015-1031` (→ **WN-30**); labels `ui/web_new_v2/index.html:1789-1791`
- **Confirmed:** yes
- **Description:** the storage panel is fed by two bridge methods with different schemas. `get_storage_info()` returns `{total, total_mb, tracks:{count,size}, covers:{count,size}, cache_dir}` where `total` = cache + covers + **downloaded tracks**; `get_storage_details()` returns `{used_bytes, quota_bytes, quota_gb, protected_count}` where `used_bytes` = **cache only**. `onStorageInfo()` branches on `data.used_bytes !== undefined` and writes the same three DOM ids in both branches, so "storage-total", "storage-streams" (label "Кэш:") and "storage-protected" (label "Защищено (Избранное/Загрузки):") mean different things depending on which call answered last.
- **Cause:** two independently designed storage metrics with no shared contract; the UI labels were written for one of them.
- **Trigger conditions:** any interleaving of `get_storage_info()` (`js/settings.js:1085`, `js/library.js:119,191`) and `get_storage_details()` / `clear_storage_cache()` / `set_cache_quota()` (`js/settings.js:232,266`).
- **User impact:** after "Очистить кэш" the panel shows cache-only numbers and `storage-streams` duplicates `storage-total`; a moment later a library action repaints it with download-inclusive numbers and `storage-streams` shows the size of the downloaded music while labelled "Кэш:", and "Защищено" shows a cover count instead of a track count.
- **Evidence:**
  ```python
  # core/api.py:3084-3090
  res = {
      "total": total_mb, "total_mb": total_mb,
      "tracks": {"count": track_count, "size": f"{track_mb} MB"},
      "covers": {"count": covers_count, "size": f"{cover_mb} MB"},
      "cache_dir": base_cache_dir,
  }
  ```
  ```js
  // ui/web_new_v2/js/settings.js:1017-1029
  if (data.used_bytes !== undefined) {
      const usedMb = (data.used_bytes / (1024 * 1024)).toFixed(1);
      setElText('storage-total', `${usedMb} MB`);
      setElText('storage-streams', `${usedMb} MB`);
      setElText('storage-protected', `${data.protected_count || 0} треков`);
  } else {
      setElText('storage-total', `${(data.total || 0).toFixed(1)} MB`);
      if (data.tracks) setElText('storage-streams', `${data.tracks.size || '0 MB'}`);
      if (data.covers) setElText('storage-protected', `${data.covers.count || 0} обложек`);
  }
  ```
- **Reproduction / verification:** in the settings panel press "Очистить кэш" (→ `clear_storage_cache`, `used_bytes` branch) and then trigger a library import (`js/library.js:191` → `get_storage_info`, `else` branch) and watch the three labels change meaning/scale.
- **Suggested fix:** make the bridge return one storage schema (e.g. always `{used_bytes, quota_bytes, quota_gb, protected_count, downloads_bytes, covers_bytes}`) and let the UI compose the panel from it; the bridge side is WN-08, the label semantics are WN-30.
- **Fix side effects:** `js/library.js` and `js/events.js` consume the `storage_info` event; changing the payload requires updating both.
- **Discovered by:** A

---

#### F-WN-08-5  [P2] — `save_setting` writes the setting before the registry update and ignores `update_autostart()`'s failure; the `"autostart"` key matches in *any* category

- **File:** `core/api.py:2940-2953` (trigger `:2947`, call `:2949`), `core/api.py:2839-2890` (`update_autostart`)
- **Confirmed:** yes
- **Description:** `save_setting` writes `category.key = value` into the settings cache first, then calls `update_autostart(bool(value))` and **discards its return value**; the bridge still answers `True`. Two defects in one place: (a) the settings end up claiming autostart is on/off even when the `HKCU\...\Run` write failed; (b) the trigger condition is `key == "autostart"` for *every* category, so `save_setting('autostart', False, 'anything')` removes the Windows Run entry.
- **Cause:** the guard was written as `key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart")` — the first clause already matches every category, making the third redundant, and the registry result is not checked.
- **Trigger conditions:** any caller of `save_setting` with the key `autostart` (there is **no UI caller at the time of the audit** — the only live autostart path is `complete_onboarding`, which does check the result at `core/api.py:2789`), or a registry write that fails (policy restriction, a locked Run key, a missing `HKCU\...\Run` key).
- **User impact:** the settings screen shows autostart as enabled while Windows never starts the app (or the opposite: the app is removed from autostart while the setting says it is on). Silent divergence between the UI state and the registry.
- **Evidence:**
  ```python
  # core/api.py:2946-2953
  self._core.settings.set(category, key, value)
  if key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart"):
      try:
          self.update_autostart(bool(value))
      except Exception as e:
          logger.warning(f"Failed to sync autostart in save_setting: {e}")
  self._emit("setting_changed", {"category": category, "key": key, "value": value})
  return True
  ```
- **Reproduction / verification:** harness (`%TEMP%\opencode\audit_reports\verify_wn08.py`, block 2) with `api.update_autostart` monkeypatched to return `False`:
  ```
  save_setting returned      : True
  update_autostart called    : [True]
  stored general.autostart   : False
  stored app.autostart       : True
  ```
  (the call fires for `category='app'`, and the bridge reports success although the registry was never touched).
- **Suggested fix:** narrow the trigger to `category in ("general", "app") and key == "autostart"` (or the dotted `"general.autostart"` form), check the `update_autostart()` result, and on failure roll the setting back and return `False` so the UI can show an error (as `complete_onboarding` already does).
- **Fix side effects:** `update_autostart()` already writes `general.autostart`/`app.autostart` itself, so `save_setting` must not double-write them before the registry call, or the rollback has to restore both.
- **Discovered by:** A

---

#### F-WN-08-6  [P2] — `set_equalizer` stores unvalidated values, never clears the bands with an empty list, and `get_equalizer` does not return the band mode

- **File:** `core/api.py:3173-3190`; frontend `ui/web_new_v2/js/equalizer.js:192,314-319,331-351` (→ **WN-29**); defaults `core/settings.py:238-241`
- **Confirmed:** yes
- **Description:** (a) `set_equalizer(preamp, bands)` performs no validation at all — the preamp type, the band count and the gain range are stored verbatim; (b) `if bands:` means an **empty** band list never clears the stored bands (the previous values survive, so "reset to flat" via an empty list is impossible and the stored data silently diverges from what the caller asked for); (c) `get_equalizer()` returns only `{preamp, bands}` — the 3/6/10-band **mode** lives in a different key (`equalizer.mode`) written by a *separate* `save_setting` call in the frontend (`js/equalizer.js:345`), so the mode is not part of the equalizer contract and `restoreEq()` (`js/equalizer.js:314-319`) can never restore it from the backend.
- **Cause:** the backend treats the equalizer as two independent free-form settings; the frontend models it as one object `{preamp, bands, mode}` with a fixed 10-band array and 3/6/10 display modes.
- **Trigger conditions:** (a) any caller sending a band list of a length other than 10 or gains outside ±20 dB; (b) `set_equalizer(0, [])`; (c) app start with `localStorage` cleared and `window.settings` not yet populated when `initEqualizer()` runs — the mode then silently falls back to 3 bands although the stored band array holds 10 values.
- **User impact:** the equalizer graph and the persisted data can disagree (a 3-band view showing averaged 10-band values, or a stored band list whose length does not match the graph); a "flat" reset that sends an empty list leaves the old curve audible.
- **Evidence:**
  ```python
  # core/api.py:3180-3190
  def set_equalizer(self, preamp: float = 0, bands: list = None):
      self._core.settings.set("equalizer", "preamp", preamp)
      if bands:
          self._core.settings.set("equalizer", "bands", bands)
      return True
  ```
  ```js
  // ui/web_new_v2/js/equalizer.js:317-318
  eqBands=Array.from({length:10},(_,index)=>gain(data.bands?.[index]));
  if(BAND_CONFIGS[data.mode])currentEqMode=Number(data.mode);
  ```
- **Reproduction / verification:** harness (`%TEMP%\opencode\audit_reports\verify_wn08.py`, block 4):
  ```
  after set  : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
  after []   : [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]     # empty list did not clear
  get_equalizer -> {'preamp': 0.0, 'bands': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
  ```
  The band count itself is consistent (backend default `[0]*10`, frontend `length:10`, `BAND_CONFIGS` 3/6/10 are groupings of the same 10 values) — the defect is the missing validation and the split mode contract.
- **Suggested fix:** validate in `set_equalizer` (preamp finite and within ±20 dB, `bands` a list of exactly 10 finite numbers within ±20 dB, reject otherwise), use `if bands is not None:` so an empty list is an explicit "clear", and return the mode from `get_equalizer()` (`settings.get("equalizer","mode")`) so the frontend can restore the whole equalizer object from one call.
- **Fix side effects:** the frontend currently sends `mode` through a separate `save_setting`; if `get_equalizer` starts returning `mode`, `js/equalizer.js:314-319` will pick it up automatically — that is the intended behaviour, but it changes which mode the panel opens in for existing users.
- **Discovered by:** A

---

#### F-WN-08-7  [P3] — `set_cache_quota`'s positional MB heuristic silently clamps a >64 GB request to the 1 GB minimum

- **File:** `core/api.py:236` (`_POSITIONAL_MB_THRESHOLD`), `core/api.py:272-327` (`_normalize_cache_quota`, heuristic at `:314`), `core/api.py:4031-4095` (`set_cache_quota`, clamp at `:4069-4075`); caller `ui/web_new_v2/js/settings.js:264-266`
- **Confirmed:** yes
- **Description:** a bare positional number above 64 is reinterpreted as **megabytes** (`quota_gb=500` → 500 MB → 0.49 GB → the "minimum" rule raises it to 1 GB). A caller asking for 100 GB gets 1 GB stored, with no error and no warning. The frontend currently only offers 1/2/5/10/0 GB (`ui/web_new_v2/index.html:1800-1804`), so the misfire is latent — but the toast reports the *requested* value (`js/settings.js:268`: "Лимит кэша установлен на ${val} ГБ"), so the UI would claim a quota the backend never applied.
- **Cause:** the unit heuristic is applied to a parameter whose unit is not carried by the caller, and the "0 < x < 0.5 GB" rule then promotes the misinterpreted value to the 1 GB floor instead of rejecting it.
- **Trigger conditions:** any `set_cache_quota(<n>)` call with `n > 64` (e.g. a future "128 GB" option, or a caller that passes MB positionally).
- **User impact:** the user believes a large quota is in force while the app enforces 1 GB; the cache is purged far more aggressively than requested (`set_cache_quota` calls `purge_stream_cache(quota_bytes=1 GB)`).
- **Evidence:**
  ```python
  # core/api.py:313-316
  if size_mb is None and val_gb is not None and val_gb > _POSITIONAL_MB_THRESHOLD:
      size_mb = val_gb
      val_gb = None
  ```
  ```python
  # core/api.py:4072-4074
  if val_gb < 0.5:
      val_gb, size_mb = 1.0, 1024.0
  quota_val = max(1, int(round(val_gb)))
  ```
- **Reproduction / verification:** harness (`%TEMP%\opencode\audit_reports\verify_wn08.py`, blocks 5 and 6):
  ```
  set_cache_quota(100) -> cache_quota_gb: 1   cache_size_mb: 1024   (asked for 100 GB)
  set_cache_quota(5)   -> cache_quota_gb: 5   cache_size_mb: 5120   (the value the UI sends)
  ```
- **Suggested fix:** make the unit explicit at the bridge boundary (accept `cache_quota_gb` only, or require a `unit` argument), and treat the "interpreted as MB" case as an error rather than silently re-interpreting it; reject a bare positional value above a sane GB ceiling instead of promoting it to the floor.
- **Fix side effects:** `js/settings.js:266` currently calls `set_cache_quota(val)` positionally — it must be changed to `set_cache_quota({cache_quota_gb: val})` or `set_cache_quota(val, cache_quota_gb=val)` when the signature is tightened.
- **Discovered by:** A

---

#### F-WN-08-8  [P3] — `complete_onboarding` stores `None` for `accent_color` / `audio_device` when the payload carries an explicit null

- **File:** `core/api.py:2756-2837` (validation `:2767-2781`, mapping `:2791-2799`, write loop `:2818-2820`); caller `ui/web_new_v2/js/onboarding.js:167-176`
- **Confirmed:** yes
- **Description:** the validator treats `None` as "not provided" for `theme`, `theme_mode` and `performance_preset` (the corresponding blocks are skipped), but the mapping loop writes **any key that is present**, including a `None` value. `accent_color: null` and `audio_device: null` therefore overwrite the stored values with `None`. `None` is then serialised as `""` by `core/database.py:2032-2033`, so after a restart the value comes back as an empty string rather than the schema default.
- **Cause:** the "is the key present" test (`if key in settings_data`) is not paired with a "is the value usable" test for the two non-boolean mapped keys.
- **Trigger conditions:** a caller that sends an explicit null for `accent_color` or `audio_device`. The current onboarding payload (`js/onboarding.js:167-172`) never does, so the impact is latent.
- **User impact:** today the two consumers fall back to a default (`js/player.js:243` `String(settings.output_device || 'default')`, `js/feature-controls.js:43` `|| 'default'`), so nothing visibly breaks — but the persisted settings now hold a null/empty value where a colour and a device were configured, and any new consumer of `theme.accent_color` inherits `None`.
- **Evidence:**
  ```python
  # core/api.py:2779-2781
  accent = settings_data.get("accent_color")
  if accent is not None and (not isinstance(accent, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent)):
      return {"success": False, "error": "Некорректное цвет оформления"}
  ```
  ```python
  # core/api.py:2818-2820
  for key, target in mapping.items():
      if key in settings_data:
          settings.set(target[0], target[1], settings_data[key])
  ```
- **Reproduction / verification:** harness (`%TEMP%\opencode\audit_reports\verify_wn08.py`, block 3):
  ```
  complete_onboarding({"accent_color": None, "audio_device": None})
  theme.accent_color    : None
  audio.output_device   : None
  ```
- **Suggested fix:** skip `None` values in the mapping loop (`if settings_data.get(key) is not None:`), mirroring the `theme`/`preset` handling.
- **Fix side effects:** none — the current frontend never sends null for these keys, and "skip null" is the semantics the docstring already implies for the other keys.
- **Discovered by:** A

---

#### F-WN-08-9  [P3] — `save_setting` accepts an unknown category and creates an orphan settings category that `get_settings()` never returns

- **File:** `core/api.py:2940-2953`, `core/settings.py:401-418` (`SettingsManager.set`), `core/settings.py:532-535` (`get_category`)
- **Confirmed:** yes
- **Description:** neither `save_setting` nor `update_setting` validates the category. `SettingsManager.set()` creates the category on the fly (`if category not in self._cache: self._cache[category] = {}`) and the value is flushed to the DB as `"<category>.<key>"`. A category that is not in the bridge's hardcoded list (`core/api.py:2929`) is then invisible in `get_settings()`, `get_all_settings()` and `get_settings_by_category()` (the latter returns `{}` for an unknown category because `get_category` falls back to `DEFAULT_SETTINGS.get(category, {})`), while the row is still persisted.
- **Cause:** the category list exists in three places (bridge list, `DEFAULT_SETTINGS`, and the runtime categories created by `save_setting`) with no single source of truth and no validation at the write boundary.
- **Trigger conditions:** a typo in a frontend `saveSetting(key, value, category)` call, or a category that the frontend invents.
- **User impact:** the setting is silently lost from the user's point of view (the control snaps back to its old value on the next render) while a permanent row sits in the settings table; `get_all_settings()` is loaded at startup, so the orphan also grows the startup read.
- **Evidence:**
  ```python
  # core/settings.py:413-418
  with self._lock:
      if category not in self._cache:
          self._cache[category] = {}
      self._cache[category][key] = value
      self._dirty.add((category, key))
  ```
  ```python
  # core/settings.py:532-535
  def get_category(self, category: str) -> Dict[str, Any]:
      with self._lock:
          return self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()
  ```
- **Reproduction / verification:** `api.save_setting("x", 1, "typo_category")` → `api.get_settings()` has no `typo_category` key, `api.get_settings_by_category("typo_category") == {}`, while `settings.get_category("typo_category") == {"x": 1}`.
- **Suggested fix:** validate the category in `save_setting` against the known set (schema categories + the runtime ones) and reject/log unknown ones, the same way `_bridge_write_error` already refuses `general.plugins_enabled`.
- **Fix side effects:** a hard rejection would break any frontend call that currently relies on writing to a category the bridge does not know (e.g. `lyrics`, `player` — those must be added to the accepted set first).
- **Discovered by:** A

---

#### F-WN-08-10  [P3] — `save_theme` writes the dead key `theme.current_theme`; the live theme key is `theme.theme`

- **File:** `core/api.py:2750-2754`; live key `core/settings.py:177-196`; consumer `ui/web_new_v2/js/settings.js:724-746` (→ **WN-30**)
- **Confirmed:** yes
- **Description:** `save_theme(theme)` stores the value under `theme.current_theme`, a key that exists in no schema. The key the application actually reads is `theme.theme` (palette name) / `theme.theme_mode` / `theme.mode`. The method also emits `theme_changed` with the raw theme string, which no JS listener consumes.
- **Cause:** the method was written against an older settings layout and never updated; it has **no caller** anywhere in the repository (grep for `save_theme` → only `core/api.py:2750`).
- **Trigger conditions:** any future caller that wires the UI to `save_theme` — the theme would appear to save (the bridge answers `True`) but the palette would not change, because the app reads `theme.theme`.
- **User impact:** none today (dead method); a latent trap for the next caller.
- **Evidence:**
  ```python
  # core/api.py:2750-2754
  def save_theme(self, theme: str):
      """Save theme setting."""
      self._core.settings.set("theme", "current_theme", theme)
      self._emit("theme_changed", theme)
      return True
  ```
- **Reproduction / verification:** `api.save_theme("mint")` → `settings.get("theme","current_theme") == "mint"`, `settings.get("theme","theme")` unchanged (`"dark"`); `grep -r "save_theme"` over the repo → 1 hit (the definition).
- **Suggested fix:** either delete the method or make it write `theme.theme` (and `theme.theme_mode`) with the same validation the onboarding applies (`core/api.py:2770-2775`).
- **Fix side effects:** none — the method is currently unreachable.
- **Discovered by:** A

---

#### F-WN-08-11  [P3] — `save_personalization` performs no validation and the artist-alias map has no size cap

- **File:** `core/api.py:3024-3028` (`save_personalization`), `core/api.py:3002-3019` (`set_artist_alias`), `core/api.py:2979-3000` (`set_recommendation_feedback`); defence in the callee `services/artist_identity.py:13-32` (→ **WN-18**); defaults `core/settings.py:166-176`
- **Confirmed:** yes
- **Description:** `save_personalization(data)` writes **any** key with **any** value into the `personalization` category: no key whitelist, no type check, no length cap. It is the only writer of `artist_aliases`, `artist_bindings`, `blocked_artists` and `disliked_tracks`, the structures the recommendation core reads. `set_artist_alias` (the dedicated, validating writer) caps the canonical name at 200 chars and detects alias cycles, but the alias **map** itself grows without limit, unlike the feedback lists which are capped at 1000 (`core/api.py:2999`).
- **Cause:** the bulk setter is a raw pass-through to `SettingsManager.set()`; the domain-specific writers next to it are not used for the structures they own.
- **Trigger conditions:** a caller of `save_personalization` with a wrong type — e.g. `{"blocked_artists": "artist"}` (a string instead of a list) — or a caller that adds aliases one by one.
- **User impact:** a non-list `blocked_artists` is silently ignored by `get_recommendation_feedback` (`core/api.py:2976-2977`, `isinstance(blocked, list)` guard) and is then **discarded** by the next `set_recommendation_feedback` call (`core/api.py:2989-2990` resets a non-list to `[]`), so the user's blocked-artist list is lost without any error. The alias map has no ceiling, so a long-lived profile grows the settings row unboundedly.
- **Evidence:**
  ```python
  # core/api.py:3024-3028
  def save_personalization(self, data: dict):
      if isinstance(data, dict):
          for k, v in data.items():
              self._core.settings.set("personalization", k, v)
      return True
  ```
  ```python
  # core/api.py:2989-2990
  values = self._core.settings.get('personalization', key, [])
  values = list(values) if isinstance(values, list) else []
  ```
- **Reproduction / verification:** `api.save_personalization({"blocked_artists": "X"})` → `settings.get("personalization","blocked_artists") == "X"`; `api.get_recommendation_feedback({"artist":"X","title":"T"})["artist"] is False`; a subsequent `api.set_recommendation_feedback({"artist":"Y","title":"T"}, "artist", True)` replaces the value with `["Y"]` — the previous content is gone. Neither `save_personalization` nor `set_artist_alias` has a UI caller at the time of the audit (grep over `ui/web_new_v2` → 0 hits), so the impact is latent.
- **Suggested fix:** whitelist the keys `save_personalization` may write, validate the type of each (list/dict) and cap the sizes, or route the structures through `set_artist_alias` / `set_recommendation_feedback` exclusively.
- **Fix side effects:** `js/profile.js:161` writes `personalization.nickname` through `save_setting` (not through `save_personalization`), so a whitelist must include `nickname`.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct (brief):

- **Hotkey mirror contract (rule #5).** `DEFAULT_SETTINGS["hotkeys"]` (`core/settings.py:119-144`) and `DEFAULT_KEYBINDS` (`ui/web_new_v2/js/hotkeys.js:4-15`) contain the same 10 ids with the same combos and the same order-independent mapping (`play_pause=Space`, `next_track=Ctrl+ArrowRight`, `prev_track=Ctrl+ArrowLeft`, `volume_up=Ctrl+ArrowUp`, `volume_down=Ctrl+ArrowDown`, `toggle_mute=KeyM`, `toggle_lyrics=KeyL`, `toggle_mini=KeyP`, `like=KeyK`, `search=Slash`). `tests/test_keybind_contracts.py` parses both files and fails on drift — it passes. **Saving a hotkey preserves the ids that are not in the payload**: the frontend writes one key at a time (`js/hotkeys.js:140-142` → `save_setting(id, combo, 'hotkeys')`) and there is no bulk hotkey setter anywhere in `core/api.py`, so `SettingsManager.set()` only adds/overwrites that one id. The "reset keybinds" button in `js/settings.js:1136-1139` also writes id by id.
- **Unknown category / unknown key on read.** `get_settings("nope")` and `get_settings_by_category("nope")` return `{}` without raising (`core/settings.py:535` falls back to `DEFAULT_SETTINGS.get(category, {})`); `get_settings()` catches per-category exceptions (`core/api.py:2931-2937`).
- **Value typing round-trip.** dict/list/bool/int/float survive the DB round-trip: `_serialize_setting` (`core/database.py:2028-2034`) JSON-encodes them and `get_all_settings` (`core/database.py:2117-2129`) JSON-decodes them. `SettingsManager.get` additionally coerces the legacy `"true"/"false"` strings (`core/settings.py:394-399`). Only `None` degrades to `""` (a known, benign loss — see F-WN-08-8).
- **Secret masking.** `auth.yandex_token` / `auth.oauth_client_secret` are masked in `get_settings` (both the single-category and the whole-tree form) and a blank write from the UI is ignored instead of wiping the stored secret (`core/api.py:243-269`). Pinned by `tests/test_api_f1_audit.py` (passes).
- **Subscription / licensing.** `validate_subscription_key` (`:2892-2907`) and `get_subscription_info` (`:2909-2920`) are documented stubs guarded by `LICENSE_VALIDATION_ENABLED = False` (`:38`). The `key` argument is **never stored, never logged and never sent anywhere** — there is no network call in either method, the "valid" verdict is a hardcoded constant, and the returned `key` is the literal `"OPEN-SOURCE"`. The `subscription` category is not part of the bridge's settings tree, so the (unused) `subscription.key` column is not exposed by `get_settings()`/`get_all_settings()`. No caller exists in the UI.
- **Autostart registry mechanics.** `update_autostart` writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — per-user, no elevation required — with the value name `NeDotify`, which matches `installer.iss:59` exactly (hive, subkey and value name), so enabling autostart leaves exactly one Run entry. The legacy `"AURA Music"` value is deleted on **both** the enable and the disable path (`:2871-2879`), and the disable path also removes the current value, so the toggle can always be turned off. The non-frozen path anchors the command to `main.py` next to the module, not to the CWD (`:2860-2866`).
- **Destructive-path hardening that is present.** `clear_storage` validates `storage_type` strictly against `("cache","all")` and returns `False` for anything else (`core/api.py:3121-3124`) — no path is ever built from that string, so there is no traversal surface. The `"cache"` path only touches `~/.nedotify/{covers,streams,temp}` (`utils/cache_manager.py:152-156`) and never `~/.nedotify/downloads`. `purge_stream_cache` keeps `is_downloaded`/`is_favorite` tracks and synchronises `stream_cache.cached_file_path` / `tracks.is_cached` in the same transaction (`utils/cache_manager.py:198-267`), so the *cache* path does not leave dangling rows. `_delete_downloaded_files` uses `os.remove` on the path itself, so a symlink is unlinked, not followed to its target.
- **`set_cache_quota` input handling.** Negative quotas are rejected from the raw arguments (`core/api.py:4062-4065`), `0` is documented and stored as "no limit" and is deliberately **not** handed to `purge_stream_cache` (which would read it as "delete everything", `core/api.py:4066-4084`), and a 0 < x < 0.5 GB value is promoted to the 1 GB minimum instead of silently becoming "no limit" (`:4072-4073`).
- **`complete_onboarding` correctness.** Unknown keys are **not** stored (only the seven mapped keys are written, `:2791-2799`, `:2818-2820`); the five boolean keys are type-checked (`:2763-2766`); `theme`/`theme_mode`/`performance_preset`/`audio_device`/`accent_color` are validated against fixed allow-lists; the autostart failure is surfaced as an error instead of being swallowed (`:2789-2790`); the whole write is committed with `sync_flush_now()` (`:2825-2831`) so the success answer is only sent after the settings reached the DB; the failure path restores `first_launch_done`/`onboarding_completed` (`:2835-2836`); and the method is idempotent for the same payload (the autostart branch is skipped when the value is unchanged).
- **`set_artist_alias` / `set_recommendation_feedback`.** Both validate their inputs (non-empty artist/title, `name_key` non-empty), the alias cycle is detected correctly (a A→B→A chain returns "Циклическая связь имён"), the canonical name is capped at 200 chars, the feedback lists are capped at 1000 entries, duplicates are removed before the append, and the read-modify-write runs under `self._window_op_lock` (an `RLock`, `core/api.py:353`).
- **`get_wrapped_stats`.** The bridge wraps the call and returns a well-formed empty payload on failure (`core/api.py:3156-3171`). The date range uses SQLite `datetime('now','-7 days')` while `history.played_at` defaults to `CURRENT_TIMESTAMP` — both UTC, so there is no timezone/DST skew; the day-of-week mapping (`%w` → 0=Sunday) is reordered Mon-Sun correctly (`core/database.py:1791-1823`). An empty history yields zeros, not an exception.

---

### 4. Coverage gaps

- **The app was not run** (forbidden by the brief). All UI-level consequences above are derived from the code paths, not observed on screen. The destructive-path defect (F-WN-08-2) and the settings defects (F-WN-08-1, -3, -5, -7, -8) were verified with harnesses that drive the real `AppApi` / `SettingsManager` / `DatabaseManager` classes, but not through the WebView.
- **`update_autostart` was not executed against the real registry** — the machine's `HKCU` was not modified. The key path, hive and value name were verified by reading `core/api.py:2839-2890` and `installer.iss:52-84`; the "registry write fails" branch of F-WN-08-5 was simulated by stubbing `update_autostart`.
- **The storage-panel collision (F-WN-08-4)** was derived from the two payload shapes and `onStorageInfo`; I did not click through the panel in the running UI, and I did not enumerate every other consumer of the `storage_info` / `storage_updated` events outside `ui/web_new_v2/js/{settings,events,library}.js`.
- **`utils/cache_manager.py`, `utils/file_scanner.py`, `services/artist_identity.py` and `core/offline.py` were read only along the lines needed to trace the callee behaviour** — their own defects (e.g. `clear_covers_cache()` leaving `tracks.cover_path` dangling after deleting the cover files, WN-27; the `add_track` `is_downloaded = 1` collision, WN-12) are attributed to those areas and were not audited in full.
- **The equalizer DSP path** (`js/player.js::setEq`, the WebAudio graph) is WN-29 and was not reviewed; only the bridge↔frontend data contract was checked.
- **The hotkey *behaviour*** (which actions the frontend actually implements, `js/hotkeys.js:200-256`) was not audited — WN-30.
- **`get_recommendation_quality`** (`core/api.py:3021-3022`) delegates to `core/database.py:1569-1584`, which clamps `days` to `[1,365]` and parameterises the SQL; a non-numeric `days` raises inside the callee and is turned into a bridge error by `_install_bridge_error_logging`. It has no UI caller, so it was not pursued further.
- **Tests:** only the four targeted files were executed (`tests/test_keybind_contracts.py`, `tests/test_api_f1_audit.py`, `tests/test_api_audit_b.py` → 111 passed). The full suite was not run; a regression introduced by the findings above would not necessarily be caught by the existing suite (no test asserts the `get_settings` category list, the storage payload shape, or the `save_setting` autostart failure path).
