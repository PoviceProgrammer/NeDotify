## AREA WN-30 — UI settings, hotkeys, style picker, feature controls, window resize — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `ui/web_new_v2/js/settings.js` — 1–3388 (whole file, 4 reads: 1–800, 801–1700, 1701–2450, 2451–3150, 3151–3388)
- `ui/web_new_v2/js/settings-view.js` — 1–123 (whole file)
- `ui/web_new_v2/js/hotkeys.js` — 1–256 (whole file)
- `ui/web_new_v2/js/ui-style.js` — 1–294 (whole file)
- `ui/web_new_v2/js/feature-controls.js` — 1–135 (whole file)
- `ui/web_new_v2/js/window-resize.js` — 1–22 (whole file)
- `ui/web_new_v2/js/appearance-assets.js` — 1–51 (whole file)

**Callees traced into other areas (read for cross-checking, not reviewed):**

- `core/settings.py` — 1–589 (`DEFAULT_SETTINGS`, `SettingsManager.get/set/get_category`)
- `core/api.py` — 200–330 (`_mask_secrets`, `_is_empty_secret_write`, `_normalize_cache_quota`), 975–1054 (`begin_window_resize`), 2680–2709 (`auto_download_favorites_quota_gb`), 2745–2804 (`save_theme`, `complete_onboarding`), 2920–2999 (`get_settings`, `save_setting`, `get_settings_by_category`), 3020–3103 (`get_storage_info`), 4031–4108 (`set_cache_quota`, `clear_storage_cache`), 4125–4174 (`get_offline_mode`, `set_offline_mode`)
- `core/database.py` — 2030–2132 (`_serialize_setting`, `set_setting`, `set_settings_batch`, `get_all_settings`)
- `utils/cache_manager.py` — 30–204 (`cache_dir`/`clear_all`/`purge_stream_cache`)
- `ui/web_new_v2/js/main.js` — 380–579 (boot order: `initHotkeys` → `initSettings` → `initFeatureControls`)
- `ui/web_new_v2/js/events.js` — 1–60, 60–119, 378–402 (`storage_info`, `theme_changed` dispatch)
- `ui/web_new_v2/js/utils.js` — 240–369 (`openModalFocusTrap` / `isFocusInsideModalTrap`), 520–531, 600–619
- `ui/web_new_v2/js/player.js` — 170–259 (`audioSetting`, `applyAudioSettings`), 716–740, 1429, 1524
- `ui/web_new_v2/js/visualizer.js` — 30–119, 198–227
- `ui/web_new_v2/index.html` — 663–1412, 1400–1424, 1748–1839, 1839–1900 (control ids / defaults)
- `ui/web_new_v2/css/themes.css`, `css/components/window-resize.css`, `css/components/feature-tools.css` — theme tokens, resize handles, offline note
- `setup_pyinstaller.spec` — 1–111 (asset bundling)
- `tests/test_keybind_contracts.py` — executed: **9 passed** (`pytest tests/test_keybind_contracts.py -q`)

**Verification tooling used:** an id cross-check script that extracted every `getElementById('…')` from the seven in-scope JS files and diffed it against every `id="…"` in `index.html` (only dynamic ids and dead `select-font-family` differ).

---

### 2. Findings

#### F-WN-30-1  [P2] — The persisted offline-mode state is never restored into the UI at startup
- **File:** `ui/web_new_v2/js/feature-controls.js:112`, `ui/web_new_v2/js/feature-controls.js:133`; `core/api.py:2929`
- **Confirmed:** yes
- **Description:** The frontend reads the offline flag only from `window.settings.network.offline_mode`, but `AppApi.get_settings()` never includes the `network` category, so that value is always `undefined` and both restore paths evaluate to `false`. The bridge method that does expose the state (`get_offline_mode`) is never called from the UI. The result: after a restart with offline mode enabled, the frontend believes it is online.
- **Cause:** `get_settings()` builds its response from a hard-coded category list that omits `network` (`DEFAULT_SETTINGS["network"]["offline_mode"]` exists in `core/settings.py:53-55`). `feature-controls.js` has no `get_offline_mode()` call, and `offline_mode_changed` is only emitted from `set_offline_mode` (a user action), never at startup.
- **Trigger conditions:** The user enables offline mode, then restarts the app.
- **User impact:** The `offline-mode` class and the `#offline-mode-note` banner stay hidden; `window.settings.network.offline_mode` is forced to `false`, so `js/utils.js:526` keeps attaching remote `data-cover-url` attributes (cover fetches go to the network), `js/utils.js:608` `offlineImageUrl()` no longer strips remote image URLs, `js/player.js:1440` keeps prefetching the next track over the network, and `js/player.js:1524` keeps requesting Flow/recommendation tracks — all while the backend enforces offline mode and rejects them.
- **Evidence:**
  ```js
  // feature-controls.js:112
  applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  // feature-controls.js:133
  document.addEventListener('nedotify:settings_applied', event => applyOfflineState({ enabled: event.detail?.network?.offline_mode === true }));
  ```
  ```python
  # core/api.py:2929 — 'network' is NOT in this list
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                'session', 'zapret']
  ```
  ```python
  # core/api.py:4129 — the correct accessor exists but has zero frontend callers
  def get_offline_mode(self):
      return {'enabled': is_offline(self._core.settings)}
  ```
- **Reproduction / verification:** `grep -n "network" ui/web_new_v2/js` shows only `feature-controls.js` reading `window.settings.network`; `grep -rn "get_offline_mode" ui/` returns no hits. Set `network.offline_mode = true` in `~/.nedotify/nedotify_storage.db` (`settings` table, key `network.offline_mode`), restart, and observe `document.documentElement.className` has no `offline-mode` and `window.settings.network.offline_mode === false` while `AppApi.get_offline_mode()` returns `{'enabled': True}`.
- **Suggested fix:** In `initFeatureControls()`, call `window.pywebview.api.get_offline_mode()` once and feed the result into `applyOfflineState`; keep the `nedotify:settings_applied` handler but make it treat a missing `network` block as "unknown" rather than "false".
- **Fix side effects:** `applyOfflineState` currently also writes `window.settings.network.offline_mode`; the restore path must set it from the bridge answer or the prefetch/cover guards keep seeing `false`. The `network` category omission in `get_settings()` is owned by WN-08 (bridge settings) — the UI-side fix does not require changing it, but adding `'network'` to the bridge list would be the cheaper global fix.
- **Discovered by:** A

#### F-WN-30-2  [P2] — The "Нормализация громкости (EBU R128)" toggle is persisted but has no effect
- **File:** `ui/web_new_v2/js/settings.js:128`; `ui/web_new_v2/js/player.js:724-730`, `ui/web_new_v2/js/player.js:18`
- **Confirmed:** yes
- **Description:** `settings.js` binds `audio.volume_normalization` to the "Нормализация громкости" switch and persists it, but the player applies ReplayGain/LUFS normalisation unconditionally whenever the track carries LUFS data — the setting is never consulted. The related `audio.target_loudness` default (`-14.0`) is also dead: the player hard-codes `TARGET_LUFS = -14.0`.
- **Cause:** The normalisation branch in `player.js` has no `audioSetting('volume_normalization', …)` guard, and `window.settings.audio.volume_normalization` is read nowhere outside `settings.js` itself (and `onboarding.js`, which only writes it).
- **Trigger conditions:** Any track that exposes `loudness_lufs` / `lufs`.
- **User impact:** The user switches "Нормализация громкости" off and the volume curve does not change — the toggle appears broken. Conversely a user who never touched the toggle still gets +LUFS normalisation applied silently.
- **Evidence:**
  ```js
  // settings.js:128
  setupToggle('toggle-normalization', 'volume_normalization', 'audio');
  ```
  ```js
  // player.js:724-730 — no mention of the setting
  // ReplayGain LUFS volume normalization
  const trackLufs = track.loudness_lufs !== undefined && track.loudness_lufs !== null ? track.loudness_lufs : track.lufs;
  if (trackLufs !== undefined && trackLufs !== null && !isNaN(Number(trackLufs))) {
      currentReplayGain = Math.min(2.0, Math.max(0.1, Math.pow(10, (TARGET_LUFS - Number(trackLufs)) / 20)));
  } else {
      currentReplayGain = 1.0;
  }
  ```
  ```js
  // player.js:18
  const TARGET_LUFS = -14.0;   // ignores settings.audio.target_loudness
  ```
- **Reproduction / verification:** `grep -rn "volume_normalization" ui/web_new_v2/js` → only `settings.js` (write/read-back) and `onboarding.js` (write). `grep -rn "target_loudness" .` → only `core/settings.py:81`. Play a track whose metadata carries `loudness_lufs` and toggle the switch off: `currentReplayGain` remains != 1.0.
- **Suggested fix:** Gate the `currentReplayGain` computation on `audioSetting('volume_normalization', false)` and read the target from `audioSetting('target_loudness', -14)`.
- **Fix side effects:** Turning normalisation off changes the perceived loudness of already-normalised catalogues — a behaviour change users may notice as "the app got quieter". The `target_loudness` wiring must keep the -14.0 default so nothing shifts unless the user edits it.
- **Discovered by:** A

#### F-WN-30-3  [P2] — Hotkey conflict detection is missing: a duplicate binding silently kills one action
- **File:** `ui/web_new_v2/js/hotkeys.js:136-143`; `ui/web_new_v2/js/settings.js:1230-1261`
- **Confirmed:** yes
- **Description:** The recording path writes the new combo straight into `activeKeybinds` with no check against the other nine actions, and the Settings list renders the raw combo with no warning. Because the dispatcher `break`s on the first exact match, the second action bound to the same combo becomes unreachable — silently.
- **Cause:** `parseKeyEventCombo()` produces a string and the recorder performs no lookup of the other entries before assigning.
- **Trigger conditions:** The user binds a combo that is already in use (e.g. rebinds "Нравится трек" to `KeyM`, which is "Вкл / Выкл звук").
- **User impact:** One of the two actions stops responding with no message and no visual indication; the user has to discover which one was shadowed. The duplicate is also written to the backend (`save_setting(id, combo, 'hotkeys')`), so it survives a restart and keeps shadowing the other action.
- **Evidence:**
  ```js
  // hotkeys.js:136-143
  const combo = parseKeyEventCombo(e);
  if (combo && e.code !== 'Escape') {
      activeKeybinds[listeningKeybindId] = combo;
      saveKeybindsToStorage(activeKeybinds);
      if (window.pywebview?.api?.save_setting) {
          window.pywebview.api.save_setting(listeningKeybindId, combo, 'hotkeys');
      }
  }
  ```
  ```js
  // hotkeys.js:186-196 — the first match wins, the second is unreachable
  for (const [actionId, key] of Object.entries(activeKeybinds)) {
      const isMatch = (key === pressedCombo) || (key === 'Space' && (...));
      if (isMatch) { e.preventDefault(); ... executeHotkeysAction(actionId); break; }
  }
  ```
  `grep -rn "conflict\|уже назнач\|занят" ui/web_new_v2/js` → **no matches**.
- **Reproduction / verification:** Open Settings → «Управление с клавиатуры», click the record button of "Нравится трек" and press `M`. The list now shows `M` for both "Нравится трек" and "Вкл / Выкл звук"; pressing `M` only toggles the mute (whichever entry comes first in `Object.entries` order) and the like-button never fires.
- **Suggested fix:** Before assigning, scan `activeKeybinds` for another action id with the same combo; either refuse the binding, swap it, or mark the row as conflicting in the rendered list.
- **Fix side effects:** Rejecting a duplicate changes existing muscle memory for users who already created one — offering a "swap" instead of a hard refusal is safer. Any conflict marker must survive the `renderKeybindsList()` rebuild after a backend load.
- **Discovered by:** A

#### F-WN-30-4  [P3] — The "Регион поиска" select is a no-op: `general.region` has no consumer anywhere
- **File:** `ui/web_new_v2/js/settings.js:402-407`, `ui/web_new_v2/js/settings.js:883-888`
- **Confirmed:** yes
- **Description:** The select is labelled "Регион поиска / Страна для трендов и чартов" and its value is saved to `general.region` and read back into the select, but nothing else consumes it — not the backend, not the frontend.
- **Cause:** The setting was declared in `DEFAULT_SETTINGS["general"]["region"]` (`core/settings.py:62`, defaulting to `get_system_region()`) but no provider or chart code reads `settings.get("general", "region")`.
- **Trigger conditions:** Any change of the region dropdown.
- **User impact:** The user believes the search/trend region changed; nothing does. The value is stored but inert.
- **Evidence:**
  ```js
  // settings.js:402-407
  const selectRegion = document.getElementById('select-region');
  if (selectRegion) {
      selectRegion.addEventListener('change', (e) => {
          saveSetting('region', e.target.value, 'general');
      });
  }
  ```
  ```html
  <!-- index.html:1402-1404 -->
  <div class="setting-label">Регион поиска</div>
  <div class="setting-sublabel">Страна для трендов и чартов</div>
  ```
- **Reproduction / verification:** `grep -rn "region" --include=*.py .` → only `core/settings.py:62` (the default) and `core/settings.py:24-49` (`get_system_region()`), i.e. zero readers. `grep -rn "region" ui/web_new_v2/js` → only `settings.js` (write + read-back into the select).
- **Suggested fix:** Either wire the value into the provider calls that actually need a market, or hide/disable the control until a consumer exists.
- **Fix side effects:** Wiring a region into provider requests changes search/chart results for existing users who already picked a region — behaviour change, not just a UI change.
- **Discovered by:** A

#### F-WN-30-5  [P3] — "Очистить кэш" (clear cache) runs destructively with no confirmation
- **File:** `ui/web_new_v2/js/settings.js:226-243`
- **Confirmed:** yes
- **Description:** The button calls `clear_storage_cache()` on a single click with no confirmation step, while the codebase already has a confirmation modal for the other destructive action in the same panel family (`showDeleteDuplicateModal`, `settings.js:3260-3292`).
- **Cause:** The handler was written without a confirm step; `AppApi.clear_storage_cache` → `CacheManager.clear_all()` unconditionally removes the covers, streams and temp directories under `~/.nedotify`.
- **Trigger conditions:** One click on `#btn-clear-storage`.
- **User impact:** Several GB of cached audio and the whole cover cache are deleted immediately, with no way to undo. (The user's downloads in `~/.nedotify/downloads` are *not* touched — the streams/covers/temp dirs are separate — so this is recoverable, but it is still a silent bulk delete under the user's home directory, which `AGENTS.md` explicitly asks to confirm first.)
- **Evidence:**
  ```js
  // settings.js:226-243
  const clearStorageBtn = document.getElementById('btn-clear-storage');
  if (clearStorageBtn) {
      clearStorageBtn.addEventListener('click', async () => {
          clearStorageBtn.disabled = true;
          try {
              if (!window.pywebview?.api?.clear_storage_cache) throw new Error('Bridge unavailable');
              const res = await window.pywebview.api.clear_storage_cache();
              ...
  ```
  ```python
  # utils/cache_manager.py:152-156
  def clear_all(self):
      """Clear all caches safely."""
      self.clear_covers_cache()
      self.clear_streams_cache()
      self.clear_temp()
  ```
- **Reproduction / verification:** `grep -n "confirm" ui/web_new_v2/js/settings.js` → the only `confirm` is the `window.confirm` fallback inside `showDeleteDuplicateModal` (line 3265); `btn-clear-storage` has none. Click the button and observe the immediate `Кэш успешно очищен!` toast.
- **Suggested fix:** Reuse `openModalFocusTrap`/`closeModalFocusTrap` (the pattern already used by `showDeleteDuplicateModal`) for a confirm step naming the amount that will be freed.
- **Fix side effects:** An extra click on a rarely used action; the button's disabled-while-busy handling must survive the modal.
- **Discovered by:** A

#### F-WN-30-6  [P3] — `begin_window_resize`'s failure result is discarded, so a refused resize is silent
- **File:** `ui/web_new_v2/js/window-resize.js:16`; `core/api.py:997-1002`
- **Confirmed:** yes
- **Description:** The bridge returns a `{'success': False, 'error': …}` object for a refused resize (window maximised, mini-player active, invalid direction); the frontend only catches thrown exceptions, so the failure is dropped without any message.
- **Cause:** `await resize(direction)` resolves with the result object; the result is never inspected.
- **Trigger conditions:** The user drags a resize handle while the window is maximised, or while the mini player is active.
- **User impact:** The window simply does not resize and nothing explains why; the `showToast('Не удалось изменить размер окна','error')` branch is effectively unreachable.
- **Evidence:**
  ```js
  // window-resize.js:16
  try {await resize(direction);}catch {showToast('Не удалось изменить размер окна','error');}
  ```
  ```python
  # core/api.py:997-1002
  if not isinstance(direction, str) or direction not in edges:
      return {'success': False, 'error': 'Invalid resize direction'}
  if sys.platform != 'win32' or not self._window:
      return {'success': False, 'error': 'Native resizing is only available on Windows'}
  if getattr(self, '_is_maximized', False) or self._is_mini_active:
      return {'success': False, 'error': 'Restore the main window before resizing'}
  ```
- **Reproduction / verification:** Maximise the window, then drag the bottom-right resize handle: `AppApi.begin_window_resize` returns `{'success': False, 'error': 'Window is maximized'}` and no toast is shown.
- **Suggested fix:** Check `res?.success === false` and surface `res.error`.
- **Fix side effects:** The toast fires in situations where the user cannot act on the message (maximised window) — the message text should be actionable.
- **Discovered by:** A

#### F-WN-30-7  [P3] — F11 and the media keys are suppressed while a modal is open, contradicting the code comment
- **File:** `ui/web_new_v2/js/hotkeys.js:157-180`
- **Confirmed:** yes
- **Description:** The comment states that "F11, the media keys and the rebinding mode above are all before this point and are untouched", but the modal-trap guard `if (isFocusInsideModalTrap(e.target)) return;` sits **above** the F11 and media-key branches, so both are suppressed while any trapped, visible modal is open.
- **Cause:** The early `return` was placed before the F11 / `MediaPlayPause` / `MediaTrackNext` / `MediaTrackPrevious` handling, contrary to the documented intent.
- **Trigger conditions:** Any modal opened through `openModalFocusTrap` (duplicate delete, track edit, …) is on screen and the user presses F11 or a media key.
- **User impact:** The window cannot be maximised with F11 and the hardware media keys stop controlling playback while a dialog is open — exactly the case where the user is most likely to reach for the media key.
- **Evidence:**
  ```js
  // hotkeys.js:157-180
  // ... F11, the media keys and the rebinding mode above are all before this point and are
  // untouched.
  if (isFocusInsideModalTrap(e.target)) return;

  // F11: Frameless Window Maximize (keeps taskbar visible)
  if (e.key === 'F11' || e.code === 'F11') { ... }
  ...
  if (e.key === 'MediaPlayPause') { e.preventDefault(); togglePlayPause(); return; }
  ```
- **Reproduction / verification:** Open the "Удалить дубликат" modal (`#modal-delete-duplicate`) and press F11 — no maximise; press the play/pause media key — playback does not toggle. Move the `isFocusInsideModalTrap` guard below the F11/media-key block and both work again.
- **Suggested fix:** Move the modal-trap guard to just before the combo dispatch (the part that actually calls `preventDefault()` on Space/Enter), leaving F11 and the media keys above it as the comment describes.
- **Fix side effects:** F11 would then work while a modal is open, which some may find surprising, but the comment already documents that as the intended behaviour.
- **Discovered by:** A

#### F-WN-30-8  [P3] — Several Settings toggles default to the HTML class, which disagrees with `DEFAULT_SETTINGS`
- **File:** `ui/web_new_v2/js/settings.js:643-675` (`setupToggle`), `ui/web_new_v2/js/settings.js:1276-1301`; `ui/web_new_v2/index.html:1381,1388,1422,1555,1571`
- **Confirmed:** yes
- **Description:** `setupToggle()` falls back to the DOM class of the button when neither the backend nor localStorage has a value: `savedSetting(category, key, toggle.classList.contains('on'))`. For five controls the HTML default contradicts `core/settings.py::DEFAULT_SETTINGS`, so the switch shows the opposite of the effective value until the bridge answers (or forever, if `get_settings()` fails).
- **Cause:** The fallback is taken from the markup instead of from the settings schema, and the markup was authored independently of `DEFAULT_SETTINGS`.
- **Trigger conditions:** Cold start before the bridge answers, or any run where `get_settings()` fails.
- **User impact:** "Gapless playback", "Нормализация громкости", "Режим энергосбережения"-adjacent switches, "Отключать размытие стекла", "Останавливать частицы и визуал" and "Показывать визуализатор" briefly display a state the backend does not hold. Toggling one of them then flips the value relative to what the user sees.
- **Evidence:**
  ```js
  // settings.js:646
  toggle.classList.toggle('on', !!savedSetting(category, key, toggle.classList.contains('on')));
  ```
  | control (index.html) | HTML class | `DEFAULT_SETTINGS` |
  |---|---|---|
  | `toggle-gapless` (1381) | `on` | `audio.gapless_playback = False` |
  | `toggle-normalization` (1388) | `on` | `audio.volume_normalization = False` |
  | `toggle-visualizer` (1422) | `on` | `ui.cover_visualizer = False` |
  | `toggle-unfocus-blur` (1555) | off | `efficiency.unfocus_blur_reduction = True` |
  | `toggle-unfocus-visualizations` (1571) | off | `efficiency.unfocus_disable_visualizations = True` |
  ```python
  # core/settings.py:76,80,102,103,236
  "gapless_playback": False,  "volume_normalization": False,
  "unfocus_blur_reduction": True, "unfocus_disable_visualizations": True, "cover_visualizer": False,
  ```
  The `syncSwitch()` helper in the same file disagrees with itself: `syncSwitch('toggle-unfocus-blur','unfocus_blur_reduction', true)` (line 1277) defaults to **true** while `setupToggle('toggle-unfocus-blur', …)` (line 1299) defaults to the DOM class **false**.
- **Reproduction / verification:** Launch with the bridge unavailable (or block `get_settings`) and open Settings → Аудио: "Gapless playback" is ON while `core/settings.py` says `gapless_playback: False`. With the bridge up, the state self-corrects at `settings.js:870` (`settings.audio.gapless_playback !== false`).
- **Suggested fix:** Make the fallback the schema default (a single table shared with the backend), not the markup class; or drop the `class="on"` markers from the markup so the markup carries no default.
- **Fix side effects:** Changing the markup defaults changes the first-paint state for users who never touched these settings — matching `DEFAULT_SETTINGS` is the intended behaviour, but it is a visible change for existing installs whose DB already holds a value (no effect there — the backend value wins).
- **Discovered by:** A

#### F-WN-30-9  [P3] — The Storage panel's three readouts change meaning depending on which bridge method answered last
- **File:** `ui/web_new_v2/js/settings.js:1015-1031`; `core/api.py:3084-3090`, `core/api.py:4101-4104`
- **Confirmed:** yes
- **Description:** `onStorageInfo()` branches on the payload shape. `get_storage_info()` returns `{total, tracks:{count,size}, covers:{count,size}}` → the "Всего / Кэш / Защищено" rows show total MB, downloaded size and cover count. `clear_storage_cache()` / `set_cache_quota()` return `cache.get_storage_details()` → `{used_bytes, quota_bytes, quota_gb, protected_count}` → the same three rows now show the cache size twice and a protected-track count. The labels in `index.html` no longer match the numbers.
- **Cause:** One renderer is fed two incompatible payload shapes from two different bridge methods.
- **Trigger conditions:** Clicking "Очистить кэш" or changing the cache quota in the Storage panel.
- **User impact:** The "Всего" and "Кэш" rows suddenly show the same value, "Защищено" switches unit from "обложек" to "треков", and the panel reverts to the other meaning the next time `get_storage_info()` answers (e.g. the `storage_info` event). The numbers are also stale for up to 30 s because `AppApi.get_storage_info` caches for `_STORAGE_INFO_TTL = 30.0` and `clear_storage_cache()` does not invalidate that cache.
- **Evidence:**
  ```js
  // settings.js:1015-1031
  export function onStorageInfo(data) {
      if (!data) return;
      if (data.used_bytes !== undefined) {
          const usedMb = (data.used_bytes / (1024 * 1024)).toFixed(1);
          setElText('storage-total', `${usedMb} MB`);
          setElText('storage-streams', `${usedMb} MB`);
          setElText('storage-protected', `${data.protected_count || 0} треков`);
          ...
      } else {
          setElText('storage-total', `${(data.total || 0).toFixed(1)} MB`);
          if (data.tracks) setElText('storage-streams', `${data.tracks.size || '0 MB'}`);
          if (data.covers) setElText('storage-protected', `${data.covers.count || 0} обложек`);
      }
  }
  ```
  ```html
  <!-- index.html:1789-1791 -->
  <div>Всего: <span id="storage-total" ...>0 MB</span></div>
  <div>Кэш: <span id="storage-streams" ...>0 MB</span></div>
  <div>Защищено (Избранное/Загрузки): <span id="storage-protected" ...>0</span></div>
  ```
- **Reproduction / verification:** Open Settings → Хранилище, note "Всего/Кэш/Защищено", then press "Очистить кэш": `onStorageInfo(res.details)` runs with the `used_bytes` shape and the three rows change meaning. `grep -n "storage_info\|storage_updated" ui/web_new_v2/js/events.js` → the backend's `storage_updated` event name is not handled, so only the explicit call updates the panel.
- **Suggested fix:** Give `onStorageInfo` two explicit entry points (one per payload shape) or normalise both shapes to one internal model before rendering.
- **Fix side effects:** None user-visible beyond the panel; the 30 s `get_storage_info` cache invalidation lives in `core/api.py` (WN-08) and is a separate, optional fix.
- **Discovered by:** A

#### F-WN-30-10  [P3] — `AppApi.save_theme()` and the `nedotify:theme_changed` listener are dead code
- **File:** `ui/web_new_v2/js/settings.js:60-62`; `core/api.py:2750-2754`
- **Confirmed:** yes
- **Description:** The frontend persists the theme with `save_setting('theme', <id>, 'theme')` and never calls the dedicated `save_theme()` bridge method. `save_theme()` is therefore the only producer of the `theme_changed` event, so the event never fires and the `nedotify:theme_changed` listener in `settings.js` never runs.
- **Cause:** Two parallel paths for the same concept; the frontend settled on the generic settings write.
- **Trigger conditions:** Always (the path is unreachable).
- **User impact:** No direct breakage — the theme is applied to the DOM (`data-theme`) and persisted correctly. The latent risk is that the two paths disagree: `save_theme()` writes `theme.current_theme` (a key that is not in `DEFAULT_SETTINGS["theme"]` and is read by nobody) whereas the frontend writes `theme.theme`.
- **Evidence:**
  ```js
  // settings.js:60-62 — never fires
  window.addEventListener('nedotify:theme_changed', (e) => {
      applyThemeMode?.(String(e.detail ?? getLocalSetting('theme_mode', 'system')));
  });
  ```
  ```python
  # core/api.py:2750-2754
  def save_theme(self, theme: str):
      """Save theme setting."""
      self._core.settings.set("theme", "current_theme", theme)
      self._emit("theme_changed", theme)
      return True
  ```
  `grep -rn "save_theme" ui/` → no hits.
- **Reproduction / verification:** `grep -rn "save_theme" ui/web_new_v2` returns nothing; `grep -rn "theme_changed" core/` returns only `core/api.py:2753`.
- **Suggested fix:** Delete `save_theme()` and the dead listener, or route the frontend through it and make both write `theme.theme`.
- **Fix side effects:** If `save_theme()` were made authoritative it would need to stop writing the orphan `theme.current_theme` key, otherwise a second, divergent copy of the theme name would accumulate in the settings table.
- **Discovered by:** A

#### F-WN-30-11  [P3] — `body.window-resizing` is removed before the native drag loop actually starts
- **File:** `ui/web_new_v2/js/window-resize.js:15-17`; `core/api.py:1018-1027`
- **Confirmed:** yes
- **Description:** The CSS rule `body.window-resizing { user-select: none; }` exists to suppress text selection while the window is being resized, but the class is added and removed around the *bridge round trip*, not around the actual drag. `begin_window_resize` queues `SendMessageW(WM_NCLBUTTONDOWN)` on the UI thread and returns `{'success': True}` immediately, so the `await` resolves long before the user finishes dragging.
- **Cause:** The class lifetime is bound to the RPC latency instead of to the resize loop.
- **Trigger conditions:** Every resize drag.
- **User impact:** Cosmetic only — during a resize drag over selectable text the user can still select text, and the cursor styling briefly flickers.
- **Evidence:**
  ```js
  // window-resize.js:15-17
  document.body.classList.add('window-resizing');
  try {await resize(direction);}catch {showToast('Не удалось изменить размер окна','error');}
  finally {document.body.classList.remove('window-resizing');}
  ```
  ```python
  # core/api.py:1018-1027 — the sizing loop is queued asynchronously
  def start_sizing():
      try:
          user32.ReleaseCapture()
          user32.SendMessageW(hwnd, 0x00A1, edges[direction], ...)
      except Exception: ...
  self._on_window_ui_thread(self._window, start_sizing)
  return {'success': True}
  ```
- **Reproduction / verification:** Drag the `se` handle over a text block and try to select it — selection still happens even though `body.window-resizing` was set at pointer-down.
- **Suggested fix:** Keep the class until the native loop ends (a `pointerup` listener), or drive the suppression from CSS `:active` on the handle instead.
- **Fix side effects:** Holding the class until `pointerup` requires the pointerup to be received by the page; during a native sizing loop the pointer capture is released to Windows, so a `pointerup` may never arrive and the class could stick — a CSS-only solution is safer.
- **Discovered by:** A

---

### 3. Clean areas

**Settings load/save flow.** `savedSetting()` (`settings.js:29-33`) correctly prefers the backend (`window.settings`) over localStorage, and `saveSetting()` (`settings.js:1033-1053`) writes to `window.settings`, mirrors to localStorage, refreshes the appearance module for the `interface`/`optimization`/`theme` categories, calls `window.pywebview.api.save_setting(key, value, category)`, and surfaces a toast on a `false`/rejected result. There is **no dirty state and none is needed**: every control writes through immediately; the only deferred writes are the `change` (blur) events on the text inputs (`input-yandex-token`, `input-cookies-path`, `input-proxy-url`) and the sliders (which persist on `change`, i.e. on release, while `input` only updates `window.settings` for live preview). The backend batches the DB write (`SettingsManager.FLUSH_INTERVAL_SECONDS = 0.5`), so the "debounce" lives on the Python side where it belongs. No change is lost when a panel is closed, because there is nothing buffered.

**Settings-key ↔ Python-key cross-check.** Every key the frontend writes exists in `core/settings.py::DEFAULT_SETTINGS` (or is a documented extension key) and every one of them has a reader:

| category | keys written by WN-30 files | in `DEFAULT_SETTINGS`? | reader |
|---|---|---|---|
| `theme` | `theme, theme_mode, font_family, glass_blur, transparency_enabled, transparency_level, custom_bg_image, bg_blur, bg_dim, icon_pack, custom_themes, custom_primary, custom_accent` | yes | `settings.js` / `ui-style.js` |
| `theme` (ext) | `color_primary…color_focus`, `custom_palette_enabled` | no — persisted anyway via `SettingsManager._load_all`'s dotted-key branch | `settings.js::restoreCustomPalette` |
| `interface` | `ui_style, macos_mode, macos_glass, macos_blur, macos_font_family, macos_font_size` | yes | `ui-style.js` |
| `optimization` | `performance_preset, limit_state, blur_quality, glow_quality, fps_particles, fps_visualizer, fps_ui, resource_bg, resource_particles, resource_covers, resource_visualizers, resource_blur` | yes | `settings.js`, `ui-style.js` |
| `audio` | `crossfade_enabled, crossfade_duration_sec, gapless_playback, volume_normalization, autoplay` | yes | `settings.js` / `player.js` (except `volume_normalization` — see F-WN-30-2) |
| `ui` | `particles_enabled, particles_count, particles_size, particles_speed, particles_shape, cover_visualizer` | yes | `settings.js` / `visualizer.js` |
| `efficiency` | `unfocus_enabled, unfocus_blur_reduction, unfocus_disable_animations, unfocus_disable_visualizations, unfocus_fps_limit` | yes | `js/efficiency.js` |
| `storage` | `auto_download_favorites, auto_download_favorites_quota_gb, cache_quota_gb` | first two yes; `cache_quota_gb` is an extension key | `core/api.py:2691`, `utils/cache_manager.py:112,183` |
| `general` | `region` | yes | **nobody** (F-WN-30-4) |
| `auth` | `yandex_token, browser_cookies, cookies_file_path, proxy_url` | yes | `services/youtube_service.py`, `services/soundcloud_service.py`, `services/spotify_service.py` |
| `app` | `discord_rpc_enabled` | yes | `core/api.py:3821,3842`, `core/services/discord_rpc.py:44` |
| `zapret` | `auto_start, mode, autoupdate` | yes | `core/api.py::toggle_zapret` / `get_zapret_status` |
| `player` | `title_align, player_style, slider_type, queue_pos, queue_view, mp_progress, mp_cover_shape, mp_shape, mp_pos, show_queue, compact_queue_btn, next_track_preview, queue_autopilot, player_prefetch, aura_orbs_enabled, progress_color, progress_transparency` | `player` is not a `DEFAULT_SETTINGS` category, but `SettingsManager` creates and persists it (`_load_all` dotted-key branch) and `AppApi.get_settings()` includes `'player'` | `settings.js` only (all `player.*` keys are UI-only by design) |
| `hotkeys` | the 10 action ids | yes | `js/hotkeys.js` |

**Value coercion.** Checkboxes → booleans; sliders → `Number(e.target.value)`; text inputs → strings; colour pickers → validated `^#[\da-f]{6}$` before `saveSetting` (`settings-view.js:81` rejects invalid hex with `aria-invalid`); selects → `parseInt` with a `Number.isNaN` guard (`settings.js:249-250`). The Python side round-trips types correctly: `core/database.py::_serialize_setting` JSON-encodes `dict/list/bool/int/float` and `get_all_settings` `json.loads` them back, so a bool stays a bool and an int stays an int. The one deliberate mismatch is `theme.transparency_level`, whose Python default is the ratio `0.8` while the UI slider is a percentage (`min=10 max=100`) — `transparencyPercent()` (`settings.js:1091-1094`) explicitly normalises both, so this is handled.

**Hotkey table mirror (the WN-14 primary check, JS side).** `DEFAULT_KEYBINDS` (`js/hotkeys.js:4-15`) and `DEFAULT_SETTINGS["hotkeys"]` (`core/settings.py:134-143`) contain **exactly the same 10 ids with the same default combos** — `play_pause=Space, next_track=Ctrl+ArrowRight, prev_track=Ctrl+ArrowLeft, volume_up=Ctrl+ArrowUp, volume_down=Ctrl+ArrowDown, toggle_mute=KeyM, toggle_lyrics=KeyL, toggle_mini=KeyP, search=Slash, like=KeyK`. **No id exists on one side only; no default differs.** `tests/test_keybind_contracts.py` passes (9 passed), and it asserts exactly this. The JS side also defends itself: the backend loader only accepts ids in `KNOWN_ACTIONS` (`hotkeys.js:79,109`), the legacy-default migration drops obsolete formats and ghost actions (`hotkeys.js:72-97`), and the "reset to defaults" button rewrites all ten ids in memory *and* in the backend (`settings.js:1135-1144`).

**Hotkey capture logic.** Modifier-only presses return `null` (`parseKeyEventCombo`, `hotkeys.js:47-49`); the combo format is `Ctrl+Alt+Shift+Meta+<e.code>` with `Space`/`Slash` normalised (`hotkeys.js:42-44`), which matches the backend table's format; `ESC` cancels the recording without changing the binding (`hotkeys.js:137`, `e.code !== 'Escape'` guard); the recording state is cancelled by a pointerdown outside a `.keybind-record-btn` (`hotkeys.js:123-128`); and the input-field guard (`hotkeys.js:149-155`) correctly suppresses every binding while an `input`/`textarea`/`select`/`contenteditable` has focus. The only gap in this area is the missing conflict detection (F-WN-30-3).

**Theme picker (`ui-style.js`, `settings.js`).** The theme is applied to the DOM as `data-theme` on `<html>` (`settings.js:590`, `settings.js:726`) and persisted via `save_setting('theme', id, 'theme')`; the CSS defines every one of the 22 `PRESET_THEMES` ids plus `light` (`css/themes.css:56-390`), so an unknown theme can only occur if a value is written outside the preset list, in which case the token fallback applies. All 22 preset ids resolve to an existing local preview through `window.NeDotifyAssets.themePreviewPath` (`appearance-assets.js:48`), and every one of the 27 photo ids in the `photos` set has a matching `ui/web_new_v2/assets/backgrounds/photo-*.jpg` file (verified by listing the directory).

**`appearance-assets.js` / packaged exe.** The background URLs are relative (`assets/backgrounds/<id>.jpg`), the UI is loaded from a local file path (`main.py:333-339` → `sys._MEIPASS/ui/web_new_v2/index.html`), so relative asset URLs resolve inside the bundle, and `setup_pyinstaller.spec:27` bundles the whole `ui/web_new_v2` tree (`assets/backgrounds/*.jpg` and `assets/theme-previews/*.png` included). `sys._MEIPASS` is handled correctly. The legacy `assets/theme-previews/*.png` map in `settings-view.js` is unreachable at runtime because `window.NeDotifyAssets` is loaded first (`index.html:12`, a classic script, before the deferred module at `index.html:2308`) — the fallback is harmless dead code.

**Window resize direction strings.** `js/window-resize.js:7` iterates `['n','s','w','e','nw','ne','sw','se']`; `core/api.py:995-996` accepts exactly `{'n','s','w','e','nw','ne','sw','se'}`. **The two sets are identical.** The CSS provides `pointer-events: none` on the overlay layer and `pointer-events: auto` on the handles (`css/components/window-resize.css:1-2`), so the overlay does not swallow app clicks, and `body.mini-player-active #window-resize-handles { display: none; }` matches the JS guard.

**Bridge-method cross-check.** Every bridge method called from the seven in-scope files exists in `core/api.py`: `save_setting` (2940), `get_settings` (2922), `get_settings_by_category` (2958), `get_storage_info` (3034), `set_cache_quota` (4031), `clear_storage_cache` (4097), `find_duplicate_tracks` (3876), `delete_duplicate_track` (3884), `import_external_playlist` (2362), `yandex_device_auth` (1902), `toggle_discord_rpc` (3818), `toggle_zapret` (3796), `get_zapret_status` (3846), `update_zapret` (3867), `set_mini_player_position` (879), `set_offline_mode` (4132), `retry_failed_downloads` (4189), `play_track` (1437), `begin_window_resize` (992), `maximize` (1101), `next_track` (1761), `prev_track` (1767). **No call to a non-existent method was found.** The one bridge method that is *never* called from the frontend is `save_theme` (F-WN-30-10).

**Id cross-check.** An automated diff of every `getElementById('…')` in the seven in-scope files against `index.html` found no missing element that is dereferenced without a guard: `btn-reset-custom-theme`, `custom-palette-enabled`, `macos-palette-note` and `next-track-preview-badge` are created at runtime; `btn-like`/`global-search-input` are optional fallbacks in `hotkeys.js`; `select-font-family` does not exist in the markup at all but every use of it is guarded by `if (selectFont)` (`settings.js:176`, `settings.js:815`), so the dead reference is harmless.

**Duplicate listener hygiene.** `setupToggle`, `setupSlider`, `setupOptimizationPanel`'s card/toggle groups, `setupIconsPanel` and `setupWorkshopPanel` all remove their previous listener before re-binding (`_boundClick` / `_boundInput` / `_boundChange` / `dataset.bound` / `refreshWorkshop`), so the repeated `setupEfficiencyPanel()` / `setupOptimizationPanel()` calls made by `applySettingsFromBackend` and by the panel navigation do not multiply handlers. `setupZapretPanel` is guarded by `_zapretListenersAttached`. The one group without a guard, `setupPlayerSettingsPanel`'s `setupCardGroup` (`settings.js:2638-2649`), is only ever called once.

**Validation.** The colour hex field rejects anything that is not `^#[\da-f]{6}$` before it reaches the backend (`settings-view.js:81`), and the backend independently validates `accent_color` in `complete_onboarding` (`core/api.py:2779-2781`). The playlist-URL input is trimmed and rejected when empty (`settings.js:340-345`) before `import_external_playlist` is called. `set_cache_quota` is called with a value from a `<select>` whose options are 0/1/2/5/10 GB, all below the 64-unit heuristic threshold in `_normalize_cache_quota`, so the GB interpretation holds.

---

### 4. Coverage gaps

- **No runtime verification.** Per the ground rules the real app was not launched, so every "reproduction" above is derived from reading the code and the DOM/DB state, not from an observed session. The F-WN-30-1 reproduction in particular assumes `network.offline_mode = true` is present in the `settings` table.
- **I did not review the backend implementation** of the bridge methods I cross-checked (`core/api.py` beyond the quoted ranges, `utils/cache_manager.py`, `core/database.py`); those belong to WN-08/WN-10/WN-12. Where a finding's root cause is on the Python side (the `network` category missing from `get_settings()`, the 30 s `get_storage_info` cache, `save_theme`'s orphan key) it is named explicitly and not double-reported.
- **`ui/web_new_v2/index.html` was sampled, not read in full.** I read the settings-relevant ranges (663–1412, 1400–1424, 1748–1900) and machine-diffed all ids; the toggle `class="on"` defaults outside those ranges were not audited.
- **CSS was not audited.** `css/themes.css` and `css/components/window-resize.css` were only checked for the presence of the `data-theme` ids and the resize-handle rules; the visual result of the palette/mode interaction (WN-33) was not assessed.
- **Font picker:** `select-font-family` does not exist in the markup, so the `<select>` branch of the font handling is unreachable. Whether the font-card path is fully correct (remote font loading in `boot.js`) was not audited — that is WN-28/WN-33 territory.
- **The `player` settings category has no `DEFAULT_SETTINGS` entry.** I verified that `SettingsManager` creates, persists and reloads it (`core/settings.py:336-342`) and that `AppApi.get_settings()` includes `'player'`, but I did not audit the `player.*` readers in `settings.js` against `player.js` beyond confirming that every `player.*` key written by WN-30 is read back by WN-30 itself.
- **Zapret panel:** the panel's `toggle_zapret` / `get_zapret_status` / `update_zapret` calls are correct and the bridge methods exist, but the zapret service itself (WN-26) was not reviewed.
