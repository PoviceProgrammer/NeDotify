## AREA WN-30 — UI settings, hotkeys, style picker, feature controls, window resize — ROLE B

### 1. Scope reviewed

**Files opened (full read):**

- `ui/web_new_v2/js/settings.js` — lines 1–3388 (the whole file; note the area map says "3111 L", the file is now **3388 physical lines** — the map is stale)
- `ui/web_new_v2/js/settings-view.js` — lines 1–123 (whole file)
- `ui/web_new_v2/js/hotkeys.js` — lines 1–256 (whole file)
- `ui/web_new_v2/js/ui-style.js` — lines 1–294 (whole file)
- `ui/web_new_v2/js/feature-controls.js` — lines 1–135 (whole file)
- `ui/web_new_v2/js/window-resize.js` — lines 1–22 (whole file)
- `ui/web_new_v2/js/appearance-assets.js` — lines 1–51 (whole file)

**Callees traced into other areas (read to attribute defects, not to re-review):**

- `core/api.py` — WN-08 (settings bridge): `get_settings` 2922–2938, `get_all_settings` 2955–2956, `get_settings_by_category` 2958–2959, `save_setting` 2940–2953, `set_setting` 1871–1900, `get_setting` 1853–1869, `_mask_secrets` / `_SECRET_SETTING_KEYS` / `_is_empty_secret_write` / `_bridge_write_error` 239–269, `_emit` 1122–1159, `set_cache_quota` 4031–4078, `_normalize_cache_quota` 272–330, `begin_window_resize` 995–1030 (WN-04)
- `core/settings.py` — WN-14: `DEFAULT_SETTINGS` 52–287, `SettingsManager._load_all` 315–342, `get` 351–399, `set` 401–418, `flush` 443+
- `services/base_service.py` — WN-18: `normalize_proxy_url` 25–62 (accepts `user:pass@host` userinfo)
- `ui/web_new_v2/js/events.js` — WN-28: `dispatchPythonEvent` 50–65, `console.log('Python Event:', …)` 74, `case 'setting_changed'` 313–315
- `ui/web_new_v2/js/main.js` — WN-28: settings fetch/caching 390–423, `initSettings()` 536, `initWindowResize()` 445, debug.js loader 437–442
- `ui/web_new_v2/js/utils.js` — WN-28: `renderIcons` 943–958, `compressBackgroundImage` 912–941
- `ui/web_new_v2/js/pages.js` — WN-28: `loadSettings()` on panel open, line 138
- `ui/web_new_v2/index.html` — WN-28: settings markup 661–760 (secret inputs 1692/1712/1718/1734/1748/1755), colour pickers 791–821, workshop search 1216, `#operation-error` 661
- `ui/web_new_v2/css/themes.css` — WN-33: `[data-theme=…]` token blocks (theme mechanism)
- `ui/web_new_v2/css/components/window-resize.css` — WN-33: handle geometry + `body.window-resizing`
- `ui/web_new_v2/css/components/base.css` — WN-33: `#custom-bg-layer` 430, `#custom-bg-dim-layer` 443

**Tests read (coverage assessment only):** `tests/test_settings_controls_ui.py`, `tests/test_settings_palette_ui.py`, `tests/test_equalizer_controls_ui.py`, `tests/test_feature_controls_ui.py`, `tests/test_keybind_contracts.py`, `tests/test_window_resize_api.py`, `tests/test_appearance_backgrounds.py`. All 42 tests in that set pass (`.venv_win\Scripts\python.exe -m pytest <those files> -q` → `42 passed in 3.81s`).

**Scratch harnesses used (outside the repo, under `%TEMP%\opencode\`):** `wn30_probe.js`, `wn30_probe2.js`, `wn30_probe3.js` — they execute the *real* `settings.js` source in a Node `vm` with a stub DOM. No repo file was modified.

---

### 2. Findings

#### F-WN-30-1  [P1] — The Yandex Music OAuth token is persisted to WebView2 localStorage in cleartext by the generic settings writer

- **File:** `ui/web_new_v2/js/settings.js:1033-1053` (writer), `ui/web_new_v2/js/settings.js:375-381` (the only secret producer in the UI), `core/api.py:239-253` (the invariant this breaks)
- **Confirmed:** yes (executed the real `saveSetting()` in a Node `vm` — see Reproduction)
- **Description:** `saveSetting(key, value, category)` mirrors **every** value into `localStorage` under `nedotify_<category>_<key>` before it calls the bridge. There is no secret allow-list. The Yandex Music token is written through that same generic path, so it lands in the WebView2 profile on disk as plain text, even though the backend deliberately keeps it out of every read (`_mask_secrets` returns `""` + `has_yandex_token`).
- **Cause:** the "secret" policy lives only on the *read* side (`core/api.py::_SECRET_SETTING_KEYS`). The frontend's own persistence mirror has no notion of a secret and re-materialises the value the backend just refused to hand back.
- **Trigger conditions:** the user types a Yandex Music token into Settings → «Подключение музыкальных сервионов» and the field loses focus (the `change` handler fires). The localStorage entry is then never removed — not on logout, not on token replacement, not on app close.
- **User impact:** a token that grants full read access to the user's Yandex Music account sits in cleartext in the WebView2 user-data folder on disk, readable by any process running as the same user. It also survives an app restart independently of the database. This directly defeats the documented contract at `core/api.py:239` ("Secrets never travel back to JS").
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings.js:375-381
  const inputYandexToken = document.getElementById('input-yandex-token');
  if (inputYandexToken) {
      inputYandexToken.addEventListener('change', (e) => {
          if (!e.target.value) return;
          saveSetting('yandex_token', e.target.value, 'auth');   // <-- secret
      });
  }
  // ui/web_new_v2/js/settings.js:1039-1041 (inside saveSetting)
  try {
      localStorage.setItem(`nedotify_${category}_${key}`, JSON.stringify(value));
  } catch (e) {}
  ```
  vs. the backend's intent:
  ```python
  # core/api.py:239-253
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  def _mask_secrets(category, data):
      masked = dict(data)
      for key in secret_keys:
          masked[f"has_{key}"] = bool(masked[key]); masked[key] = ""
      return masked
  ```
- **Reproduction / verification:** run the real `settings.js` in a Node `vm` with a stub `localStorage` and a stub bridge, then call the exported `saveSetting`:
  ```
  PROBE1 localStorage["nedotify_auth_yandex_token"] = "\"y0uthe-secret-oauth-token\""
  PROBE1 contains plaintext secret = true
  PROBE2 localStorage["nedotify_auth_proxy_url"]   = "\"http://user:hunter2@proxy.local:8080\""
  ```
  In the app: open DevTools → Application → Local Storage → `nedotify_auth_yandex_token`.
- **Suggested fix:** mirror the backend's secret policy in the frontend mirror — do not write secret keys to `localStorage` at all (store a `has_<key>` marker instead), exactly as `_mask_secrets` does for the read path. The list should live in one shared place so the two sides cannot drift again.
- **Fix side effects:** `savedSetting()` falls back to the localStorage copy when the backend has not answered yet. Dropping the token from localStorage only affects that pre-bridge window, in which the token is not needed (the backend holds it).
- **Discovered by:** B

---

#### F-WN-30-2  [P2] — Proxy credentials and the cookies-file path reach the frontend in cleartext and are written into a visible `type="text"` input

- **File:** `ui/web_new_v2/js/settings.js:962-965`, `ui/web_new_v2/index.html:1755`, `ui/web_new_v2/js/main.js:411-414`; masking gap rooted in `core/api.py:240` (owner: **WN-08**)
- **Confirmed:** yes (code path + the backend list read directly)
- **Description:** `auth.proxy_url` is a free-text field that legitimately carries credentials (`http://user:pass@host:port` — `services/base_service.py:44-56` accepts userinfo). It is **not** in `_SECRET_SETTING_KEYS`, so `get_settings()` returns it verbatim; `applySettingsFromBackend()` writes it into a plain-text input; and `main.js` caches the whole payload — including `auth.proxy_url` and `auth.cookies_file_path` — into `localStorage['nedotify_cached_settings']`.
- **Cause:** the secret classification is a hand-maintained two-entry tuple in `core/api.py`; `proxy_url` was never added to it, so the entire pipeline (DB → bridge → DOM → localStorage cache) treats it as ordinary configuration.
- **Trigger conditions:** the user configures an authenticated proxy in Settings → «Подключение музыкальных сервионов», or points `cookies_file_path` at a real `cookies.txt`.
- **User impact:** the proxy password is stored in cleartext in the SQLite settings table, is returned to JS, is **displayed on screen** in an unmasked text box, and is duplicated into the WebView2 localStorage cache. `cookies_file_path` additionally discloses the user's home-directory layout. Contrast with `yandex_token` / `oauth_client_secret`, which *are* masked — the inconsistency is the bug.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings.js:962-965
  const inputProxyUrl = document.getElementById('input-proxy-url');
  if (inputProxyUrl && settings.auth.proxy_url !== undefined) {
      inputProxyUrl.value = settings.auth.proxy_url;      // <-- cleartext secret into the DOM
  }
  ```
  ```html
  <!-- ui/web_new_v2/index.html:1755 -->
  <input type="text" class="settings-input" id="input-proxy-url" aria-label="HTTP/HTTPS прокси" placeholder="http://127.0.0.1:1080">
  ```
  ```python
  # core/api.py:240  — proxy_url is absent
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  ```
  ```js
  // ui/web_new_v2/js/main.js:411-414 — whole payload (incl. auth.proxy_url) cached on disk
  const freshStr = JSON.stringify(freshSettings);
  if (freshStr !== cachedStr) { localStorage.setItem('nedotify_cached_settings', freshStr); … }
  ```
- **Reproduction / verification:** set `auth.proxy_url = "http://user:hunter2@proxy.local:8080"` in the settings DB, restart, open Settings → «Подключение музыкальных сервионов» → the field shows the URL with the password in clear text; `localStorage['nedotify_cached_settings']` contains the same string.
- **Suggested fix:** (a) backend — mask `auth.proxy_url` (return a redacted URL + `has_proxy_credentials`) — this is a WN-08 change; (b) frontend — use `type="password"` for the field and follow the token pattern already implemented at `settings.js:948-953` (clear the field, show a "saved" placeholder). Also stop caching `auth.*` in `nedotify_cached_settings`, or cache a redacted copy.
- **Fix side effects:** redacting the proxy URL means the user must re-enter it to edit it; the "saved" placeholder flow (already used for the token) handles that.
- **Discovered by:** B

---

#### F-WN-30-3  [P2] — A secret written from the settings UI is echoed straight back into the WebView and printed to the console

- **File:** `ui/web_new_v2/js/settings.js:375-381` (producer, WN-30), `core/api.py:2946-2952` (the echo — owner **WN-08**), `ui/web_new_v2/js/events.js:74` (the console sink — owner **WN-28**), `ui/web_new_v2/js/debug.js:22-39` (on-screen sink in `?debug=1` mode)
- **Confirmed:** yes (the whole path is static code; `save_setting` is the only bridge method that writes `auth.yandex_token`)
- **Description:** the frontend masks secrets on the **read** path, but the **write** path unmasked-echoes the value straight back into the JS context:
  `saveSetting('yandex_token', token, 'auth')` → `AppApi.save_setting` stores it and then calls `self._emit("setting_changed", {"category": …, "key": …, "value": value})` with the **raw** value → `_emit` builds `window.onPythonEvent("setting_changed", {…})` → `events.js:74` executes `console.log('Python Event:', eventName, data)` for **every** event → the raw token is printed in full.
- **Cause:** `_mask_secrets` is applied only in `get_settings` / `get_settings_by_category` / `get_setting`; the `_emit` in `save_setting` bypasses it, and the event bus logs every payload unconditionally.
- **Trigger conditions:** any save of `auth.yandex_token` — i.e. the user connecting their Yandex Music account.
- **User impact:** the secret is present in the JS heap, in the console log, and — when the app is launched with `?debug=1` — `debug.js` re-renders the same `console.log` payload into the **on-screen** floating debug console. The "secrets never travel back to JS" invariant stated at `core/api.py:239` is false for the write path.
- **Evidence:**
  ```python
  # core/api.py:2946-2952
  self._core.settings.set(category, key, value)
  …
  self._emit("setting_changed", {"category": category, "key": key, "value": value})  # raw secret
  ```
  ```js
  // ui/web_new_v2/js/events.js:72-74
  coreEventHandler = function(eventName, data) {
      console.log('Python Event:', eventName, data);      // <-- every payload, verbatim
  ```
  ```js
  // ui/web_new_v2/js/debug.js:23,37
  const msg = Array.from(args).map(arg => typeof arg === 'object' ? JSON.stringify(arg) : arg).join(' ');
  console.log = function() { _log.apply(console, arguments); log('log', arguments); };  // on-screen
  ```
- **Reproduction / verification:** open DevTools → Console, connect a Yandex token in Settings, then read the `Python Event: setting_changed {category:'auth', key:'yandex_token', value:'<raw token>'}` line. With `?debug=1` the same string appears in the green floating debug box.
- **Suggested fix:** WN-08 — mask the emitted value for keys in `_SECRET_SETTING_KEYS` (emit `has_<key>` instead of `value`). WN-28 — stop logging raw event payloads (log the event name and the key set, not the values).
- **Fix side effects:** other consumers of `setting_changed` would lose the value; `events.js:313` currently ignores the payload entirely, so there is no in-tree consumer that needs a secret value.
- **Discovered by:** B

---

#### F-WN-30-4  [P2] — No rollback when the bridge write fails: the UI, the in-memory mirror and localStorage keep the new value while the backend kept the old one

- **File:** `ui/web_new_v2/js/settings.js:1033-1053` (writer), `ui/web_new_v2/js/settings.js:650-652` (the toggle handler), `ui/web_new_v2/js/settings.js:29-33` (`savedSetting` prefers the in-memory mirror); contrast the pattern that *does* roll back: `ui/web_new_v2/js/settings.js:1887` and `:1902` (zapret)
- **Confirmed:** yes (executed the real code in a Node `vm`)
- **Description:** `saveSetting()` mutates `window.settings[category][key]` and writes `localStorage` **before** it calls the bridge. On rejection it only shows a toast and resolves `false`. The callers (`setupToggle`, `setupCardGroup`, the slider commit handler) neither `await` the promise nor restore the visual state. The result is a three-way divergence: the toggle renders ON, `window.settings` says ON, localStorage says ON — and the database says OFF.
- **Cause:** the write is optimistic and there is no compensating action on the failure path. The toast tells the user "Не удалось сохранить настройку", but the control keeps the new state, so the UI claims a configuration the backend does not have.
- **Trigger conditions:** the bridge rejects (pywebview not yet ready → `throw new Error('Bridge unavailable')`; `save_setting` returns `False` because of `_bridge_write_error`; a Python-side exception). Also any transient bridge disconnect.
- **User impact:** the effective configuration silently differs from the displayed one for the rest of the session. `savedSetting()` prefers `window.settings` over the backend, so the divergence survives every later read; the value reverts on the next start, and the user is never told why. Resource toggles that read `window.settings` (particles, visualizer) keep running in the rejected state.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings.js:1033-1052
  function saveSetting(key, value, category) {
      if (!window.settings) window.settings = {};
      if (category) { … window.settings[category][key] = value; }     // mutated first
      try { localStorage.setItem(`nedotify_${category}_${key}`, JSON.stringify(value)); } catch (e) {}
      …
      return Promise.resolve(window.pywebview.api.save_setting(key, value, category)).then(result => {
          if (result === false || result?.success === false) throw new Error('Setting rejected');
          return true;
      }).catch(() => { showToast('Не удалось сохранить настройку. Повторите изменение.', 'error'); return false; });
  }
  // ui/web_new_v2/js/settings.js:650-652 — no await, no revert
  const clickHandler = () => {
      const isOn = toggle.classList.toggle('on');
      saveSetting(key, isOn, category);
  ```
  ```js
  // ui/web_new_v2/js/settings.js:1887 — the rollback that exists elsewhere
  if (!res.success) { if (toggleZapret) toggleZapret.classList.toggle('on', !enable); … }
  ```
- **Reproduction / verification:** Node `vm` probe with a bridge whose `save_setting` returns `false`:
  ```
  P5 after click (bridge REJECTED):
     toggle visual state "on"      = true   <-- UI shows ENABLED
     window.settings.audio.autoplay= true   <-- in-memory mirror says ENABLED
     localStorage nedotify_audio_autoplay = true  <-- persisted locally
     backend value (authoritative)        = false  <-- backend still says DISABLED
     toast after rejected save: [["Не удалось сохранить настройку. Повторите изменение.","error"]]
  ```
- **Suggested fix:** make `saveSetting()` return a boolean the callers can act on and revert the control's visual state on `false` (the zapret panel already shows the pattern); or apply the value to the DOM only after the bridge confirms.
- **Fix side effects:** reverting on failure removes optimistic UI; the existing toast already tells the user, so the interaction stays honest.
- **Discovered by:** B

---

#### F-WN-30-5  [P2] — A keybind saved through `hotkeys.js` has no error handling at all: the binding looks saved, the backend never received it, and the user gets no feedback

- **File:** `ui/web_new_v2/js/hotkeys.js:136-143`
- **Confirmed:** yes
- **Description:** the rebind path calls the bridge directly instead of going through `settings.js`'s `saveSetting()` helper, and does so with no `await`, no `.catch()` and no toast:
  ```js
  if (window.pywebview?.api?.save_setting) {
      window.pywebview.api.save_setting(listeningKeybindId, combo, 'hotkeys');
  }
  ```
  Before that call, `activeKeybinds[listeningKeybindId] = combo` (`:138`) and `saveKeybindsToStorage(activeKeybinds)` (`:139`) have already updated the UI and the localStorage mirror. `saveSetting()` in `settings.js` handles all three failure modes (reject, `false` result, throw) and reports them; this path handles none.
- **Cause:** `hotkeys.js` cannot import `settings.js` (`settings.js` imports `hotkeys.js` — a circular ESM import), so it re-implemented the persistence call instead of sharing a helper.
- **Trigger conditions:** any failed bridge write during a rebind (pywebview not ready, a bridge exception, a `_bridge_write_error` rejection).
- **User impact:** the Settings list shows the new binding, the key appears to work in the current session (the local `activeKeybinds` map drives the dispatcher), and the backend still holds the old binding — so after a restart the user's rebind has silently disappeared, with no message at any point. A rejected promise here is also an unhandled rejection in the WebView console.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/hotkeys.js:136-143
  const combo = parseKeyEventCombo(e);
  if (combo && e.code !== 'Escape') {
      activeKeybinds[listeningKeybindId] = combo;      // UI updated first
      saveKeybindsToStorage(activeKeybinds);            // localStorage updated
      if (window.pywebview?.api?.save_setting) {
          window.pywebview.api.save_setting(listeningKeybindId, combo, 'hotkeys');  // no .catch, no toast
      }
  }
  ```
  Compare `ui/web_new_v2/js/settings.js:1043-1052`, which does `.catch(() => showToast(…))`.
- **Reproduction / verification:** break the bridge (or make `save_setting` return `False`) and rebind a key in Settings → «Управление с клавиатуры»: the row shows the new combo, no toast appears, and after a restart the old combo is back.
- **Suggested fix:** extract the persistence primitive into a small shared module (e.g. `js/settings-store.js`) that both `settings.js` and `hotkeys.js` use, so the failure handling and the toast are identical. Minimum viable fix: add `.catch()` + a toast + revert `activeKeybinds` on failure.
- **Fix side effects:** none; the shared module must not import `hotkeys.js` or `settings.js` to avoid the cycle.
- **Discovered by:** B

---

#### F-WN-30-6  [P2] — The colour picker persists on every `input` event: dragging one colour fires two bridge round-trips and two synchronous localStorage writes per frame

- **File:** `ui/web_new_v2/js/settings.js:1736-1755` (the `input` listener), `ui/web_new_v2/js/settings.js:1675-1681` (`activateCustomPalette`), `ui/web_new_v2/js/settings.js:1039-1052` (`saveSetting`), `ui/web_new_v2/index.html:791-821` (eight `<input type="color">`)
- **Confirmed:** yes (measured with the real source in a Node `vm`)
- **Description:** `<input type="color">` fires `input` continuously while the user drags the swatch in Chromium. The handler persists on **every** one of those events:
  ```js
  el.addEventListener('input', (e) => {
      activateCustomPalette();
      …
      saveSetting(item.id.replace('picker-color-', 'color_'), val, 'theme');
      if (item.id === 'picker-color-primary') saveSetting('custom_primary', val, 'theme');
      if (item.id === 'picker-color-accent')  saveSetting('custom_accent',  val, 'theme');
  });
  ```
  Each `saveSetting` performs a **synchronous** `localStorage.setItem` and a `window.pywebview.api.save_setting(...)` bridge call. The backend then emits `setting_changed` for every one of those writes (`core/api.py:2952`), which is an `evaluate_js` hop onto the WebView2 UI thread.
- **Cause:** the colour picker does not separate *preview* (`input`) from *commit* (`change`), unlike every other continuous control in the same file — `setupSlider` commits on `change` (`settings.js:701-705`) and the player progress colour does the same (`settings.js:2669-2673`).
- **Trigger conditions:** dragging any of the eight custom-colour pickers in Settings → «Внешний вид».
- **User impact:** roughly 120 bridge round-trips and 120 synchronous localStorage (LevelDB) writes per second of dragging, each of them waking the WebView UI thread through the `_emit` path. Synchronous localStorage writes on the main thread are the classic source of visible stutter during a drag.
- **Evidence:**
  ```
  P7 bridge save_setting calls caused by ONE colour-picker input event = 4
  P7 localStorage.setItem calls caused by ONE colour-picker input event = 4
  P7 bridge save_setting calls caused by the SECOND input event      = 2
  P7 keys written: nedotify_theme_color_primary, nedotify_theme_custom_palette_enabled, nedotify_theme_custom_primary
  ```
  (The probe stub had one picker; with all eight present the *first* event writes ~11 keys, every later event of the same drag writes 2.)
- **Reproduction / verification:** open DevTools → Network/Console, drag the primary-colour swatch for two seconds and count `save_setting` bridge calls; or set a breakpoint on `localStorage.setItem`.
- **Suggested fix:** keep the live CSS-variable preview on `input` and persist on `change` (commit), mirroring `setupSlider` and `player-progress-color`.
- **Fix side effects:** the palette would only be persisted when the user releases the swatch; the visible preview is unaffected.
- **Discovered by:** B

---

#### F-WN-30-7  [P2] — The settings schema is duplicated and hand-written; the frontend already writes keys the backend schema does not declare

- **File:** `ui/web_new_v2/js/settings.js` (whole file, 3388 lines), `core/settings.py:52-287` (`DEFAULT_SETTINGS`), `core/api.py:2940-2953` (`save_setting` — no key validation), `core/api.py:272-330` + `4031-4078` (the normalisation shim that papers over the drift)
- **Confirmed:** yes for the drift instances listed below; the "class of bug" argument is an ARCH item (see §5)
- **Description:** the settings are not a table. They are ~94 independent, hand-written imperative call sites (`saveSetting(...)`, `setupToggle(...)`, `setupSlider(...)`, `setupCardGroup(...)`), each re-implementing the load → preview → persist → restore cycle. The backend keeps a *second* copy of the schema in `DEFAULT_SETTINGS`, and the two copies have already drifted: the frontend writes **`player.mp_pos`**, **`storage.cache_quota_gb`** and **`theme.custom_palette_enabled`**, none of which exist in `DEFAULT_SETTINGS`; `audio.queue_autopilot` / `audio.flow_enabled` are declared but never written by the UI (the UI writes `player.queue_autopilot`). The backend compensates with an alias layer (`core/settings.py:373-392`) and a three-spelling quota normaliser (`core/api.py:272-330`) — both are visible symptoms of the drift.
- **Cause:** there is no shared schema and no validation on the write path — `AppApi.save_setting` accepts any `(category, key, value)` and stores it verbatim.
- **Trigger conditions:** any typo in a category/key pair, any new control added without updating `DEFAULT_SETTINGS`, any rename on one side only.
- **User impact:** a control can exist, write a key nobody reads back, and nothing notices. The frontend already compensates with fallback chains such as `savedSetting('player','queue_autopilot', savedSetting('player','flow_enabled', true))` (`settings.js:909`, `:2622-2623`, `:2720-2721`) and `savedSetting('audio','crossfade_duration_sec', …)` (`settings.js:859`). Each of those is a latent "the setting did not save" bug waiting to happen, and no test in the repo can catch one.
- **Evidence:**
  ```
  frontend-saved (category,key) pairs found: 39 (of ~94 call sites)
  NOT declared in DEFAULT_SETTINGS: 3
      player.mp_pos
      storage.cache_quota_gb
      theme.custom_palette_enabled
  ```
  ```python
  # core/settings.py:119-144 — the schema the frontend is supposed to match
  "hotkeys": { "play_pause": "Space", … },
  "storage": { "cache_size_mb": 500, … },     # but the UI writes storage.cache_quota_gb
  "theme":   { "theme": "dark", … },          # but the UI writes theme.custom_palette_enabled
  ```
  ```python
  # core/api.py:4031-4078 — the shim that exists because the two copies disagree
  def set_cache_quota(self, quota_gb=None, cache_size_mb=None, cache_quota_gb=None, **kwargs) -> dict:
  ```
- **Reproduction / verification:** `python -c` diff of the frontend `saveSetting(...)`/`setupToggle(...)`/`setupSlider(...)` call sites against `ast`-parsed `DEFAULT_SETTINGS` (the AST check is in the Reproduction of the harness note above); the three keys above are the current divergence. Alternatively: `grep -c "saveSetting(" ui/web_new_v2/js/settings.js` → 94 call sites, vs. one `DEFAULT_SETTINGS` dict.
- **Suggested fix:** see §5 (ARCH-1): a single declarative settings table, generated into both the JS and the Python schema, plus a validation step in `save_setting` that rejects unknown `(category, key)` pairs.
- **Fix side effects:** validation would reject the three undeclared keys until they are added to the schema; a generator needs a build step, and this project has none by design — the table would have to be plain JSON/JS that both sides parse.
- **Discovered by:** B

---

#### F-WN-30-8  [P3] — The workshop search rebuilds the whole card grid and re-renders every Lucide icon in the document on every keystroke

- **File:** `ui/web_new_v2/js/settings.js:3234-3239` (input handler), `ui/web_new_v2/js/settings.js:3153-3196` (`render()`), `ui/web_new_v2/js/utils.js:943-958` (`renderIcons`)
- **Confirmed:** yes for the rebuild; **hypothesis** for the visible-jank magnitude (the app must not be launched to measure it)
- **Description:** every keystroke in `#workshop-search-input` calls `render()`, which replaces the grid's `innerHTML` with ~48 KB of freshly built markup for **all** filtered items and then calls `renderIcons()` with no target element — `renderIcons` therefore calls `window.lucide.createIcons({root: document.body})`, i.e. a body-wide scan plus the construction of ~75 inline SVGs for the new cards. The same rebuild also happens on every "like" click (`settings.js:3226`). There is no debounce.
- **Cause:** the filter is implemented as "re-render the list from scratch" rather than "toggle `hidden` on the cards that already exist", and the icon re-render is not scoped to the grid.
- **Trigger conditions:** typing in the Settings → «Мастерская» search box; clicking the heart on any workshop card.
- **User impact:** per keystroke the panel recreates 25 cards and ~75 SVG icons and re-scans the whole document for `[data-lucide]`. Whether this is visibly janky was **not** measured — that would require running the app, which the ground rules forbid.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings.js:3234-3239
  if (searchInput) {
      searchInput.addEventListener('input', (e) => {
          searchQuery = e.target.value;
          render();                       // full innerHTML rebuild + global icon re-render
      });
  }
  // ui/web_new_v2/js/settings.js:3153 / 3196
  grid.innerHTML = items.map(it => { … }).join('');
  renderIcons();                        // -> window.lucide.createIcons({root: document.body})
  ```
  Probe output: `P6 grid markup length after first render = 48027`, `P6 renderIcons() … calls = 4 for 3 keystrokes + 1 initial`.
- **Reproduction / verification:** open Settings → «Мастерская», type in the search field with DevTools open and record `Performance`; the grid's `innerHTML` setter is called once per character.
- **Suggested fix:** build the 25 cards once and toggle `hidden` on filter/sort changes; scope the icon render to the grid (`renderIcons(grid)`); debounce the input handler by ~120 ms.
- **Fix side effects:** sorting requires reordering the DOM (a `DocumentFragment` reorder is cheap); the icon scope change requires the cards to be built before the icons are created.
- **Discovered by:** B

---

#### F-WN-30-9  [P3] — The settings live-search re-scans the whole settings DOM on every keystroke, with no index and no debounce

- **File:** `ui/web_new_v2/js/settings.js:3352-3388`
- **Confirmed:** yes (code read + DOM census of `index.html`)
- **Description:** every character typed into `#settings-search` re-queries all 14 `.settings-panel`s, all 60 `.settings-section`s and every row matching the selector list (59 `.setting-row` + 9 `.setting-card-group` + 6 singletons ≈ 74 elements), reading `row.textContent` plus the `placeholder` / `aria-label` / `title` of every `input, select, button` inside the row, and then writes `hidden` on ~74 rows + 60 sections + 14 panels. There is no precomputed haystack and no debounce.
- **Cause:** the filter is a full re-evaluation of the DOM on every `input` event rather than an indexed lookup.
- **Trigger conditions:** typing in the Settings search box.
- **User impact:** bounded — the settings markup is static, so this is a small constant per keystroke, and it is listed because the same text is re-extracted and re-lowercased for every character instead of once.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/settings.js:3367-3371
  rows.forEach(row=>{
      const labels=Array.from(row.querySelectorAll('input,select,button')).map(el=>`${el.placeholder||''} ${el.getAttribute('aria-label')||''} ${el.title||''}`).join(' ');
      const match=!query || headingMatch || `${row.textContent} ${labels}`.toLocaleLowerCase('ru').includes(query);
      row.hidden=!match; if(match) sectionMatch=true;
  });
  ```
  DOM census of `ui/web_new_v2/index.html`: 14 `settings-panel`, 60 `settings-section`, 59 `setting-row`, 9 `setting-card-group`.
- **Reproduction / verification:** `Select-String`/regex census of `index.html` for the row selector classes; the per-keystroke scan is visible in the DevTools Performance profile as a burst on each keypress.
- **Suggested fix:** compute a lowercase haystack per row once (lazily, on first search) and debounce the handler by ~120 ms.
- **Fix side effects:** the haystack must be invalidated when a control's label changes (rare, static markup).
- **Discovered by:** B

---

#### F-WN-30-10  [P3] — The resize contract between `window-resize.js` and `begin_window_resize` is broken: the frontend's "resizing" state ends before the drag does, and its error path is unreachable

- **File:** `ui/web_new_v2/js/window-resize.js:9-18`; `core/api.py:995-1030` (owner: **WN-04**); `ui/web_new_v2/css/components/window-resize.css:14`
- **Confirmed:** yes
- **Description:** `begin_window_resize` returns `{'success': True}` **immediately** and queues the native sizing loop asynchronously (`self._on_window_ui_thread(self._window, start_sizing)`); the `SendMessageW(WM_NCLBUTTONDOWN)` inside `start_sizing()` blocks the UI thread until the drag ends, but the bridge call has already returned by then. Consequently `await resize(direction)` in the frontend resolves at once and the `finally` removes `body.window-resizing` — the `user-select: none` guard that is supposed to span the drag — long before the drag ends. In the other direction, the backend swallows a native failure inside `start_sizing()` (`logger.warning('Native sizing loop failed')`) while the bridge has already answered success, so the frontend's `catch { showToast('Не удалось изменить размер окна','error') }` can never fire for a native failure.
- **Cause:** the frontend assumes the bridge promise spans the native sizing loop; the backend answers before the loop starts.
- **Trigger conditions:** any window resize; the error path additionally requires the native `SendMessageW` to fail.
- **User impact:** the `user-select: none` guard during the drag is ineffective (cosmetic), and a failed native resize is silent — the user drags an edge and nothing happens with no message.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/window-resize.js:15-17
  document.body.classList.add('window-resizing');
  try { await resize(direction); } catch { showToast('Не удалось изменить размер окна','error'); }
  finally { document.body.classList.remove('window-resizing'); }
  ```
  ```python
  # core/api.py:1018-1027
  def start_sizing():
      try:
          user32.ReleaseCapture()
          user32.SendMessageW(hwnd, 0x00A1, edges[direction], …)   # blocks until the drag ends
      except Exception:
          logger.warning('Native sizing loop failed', exc_info=True)  # swallowed, success already returned
  self._on_window_ui_thread(self._window, start_sizing)
  return {'success': True}
  ```
- **Reproduction / verification:** drag a window edge and watch `document.body.className` in DevTools — `window-resizing` disappears immediately on `pointerdown`, not when the drag ends. A native failure is only visible in `~/.nedotify/logs/app.log`.
- **Suggested fix:** WN-04 — report the outcome of the native loop back to the frontend (a promise that resolves after `start_sizing()` returns, or an emitted event); WN-30 — keep `window-resizing` until that signal arrives.
- **Fix side effects:** the bridge call would then be held open for the duration of the drag (the JS thread is not blocked, but the bridge slot is occupied).
- **Discovered by:** B

---

#### F-WN-30-11  [P3] — `ui-style.js` writes into the settings DOM on every invocation, waking the settings-view `MutationObserver` and forcing a full settings-subtree rescan

- **File:** `ui/web_new_v2/js/ui-style.js:113-125` (unconditional `textContent` writes), `ui/web_new_v2/js/ui-style.js:271-283` (the observers), `ui/web_new_v2/js/ui-style.js:92-142` (`syncResources`), `ui/web_new_v2/js/settings-view.js:37-53` (`syncControls`)
- **Confirmed:** yes as a coupling; the cost is small and was not measured at runtime
- **Description:** `syncResources()` unconditionally assigns `status.textContent` and `bgStatus.textContent`. Assigning `textContent` replaces the text node, which is a `childList` mutation. Both targets (`#macos-effects-status`, `#macos-background-status`, `index.html:754-755`) live **inside** `#view-settings` (`index.html:663`), whose `MutationObserver` is registered with `{subtree:true, childList:true, attributes:true, attributeFilter:['class']}` (`settings-view.js:52`). Every such write therefore wakes `syncControls()`, which re-queries the whole settings subtree and re-writes `role` / `tabIndex` / `aria-pressed` / `aria-checked` on every card and toggle. `syncResources()` is itself re-entered on every `style` / `class` / `data-theme` mutation on `<html>` (`ui-style.js:276-282`).
- **Cause:** the appearance layer writes into the settings layer's DOM without checking whether the text actually changed, even though the same function already guards its other writes (`ui-style.js:133`, `:140` compare before assigning).
- **Trigger conditions:** any CSS-variable write on `<html>` — e.g. dragging the «Размытие (Blur)» slider (`applyGlassBlur`, `settings.js:1403-1415`, writes five variables and a label per `input` event) — or any theme / optimization / interface setting save (`saveSetting` → `NeDotifyAppearance.refresh()` → `syncResources()`, `settings.js:1042`).
- **User impact:** each root-element style mutation cascades into a rescan of the entire settings subtree (~74 rows, ~50 cards). Bounded, but it is an unnecessary coupling between two modules that are otherwise independent, and it is on the hot path of a slider drag.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/ui-style.js:115-125 — unconditional text writes
  const status = document.getElementById('macos-effects-status');
  if (status) status.textContent = !supported ? '…' : … ;
  …
  const bgStatus = document.getElementById('macos-background-status');
  if (bgStatus) bgStatus.textContent = !bg ? '…' : … ;
  ```
  ```js
  // ui/web_new_v2/js/settings-view.js:52 — the observer that is woken
  new MutationObserver(syncControls).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
  ```
  ```js
  // ui/web_new_v2/js/ui-style.js:133 — the guarded pattern used elsewhere in the same function
  if (label && label.textContent !== `${fontSize}px`) label.textContent = `${fontSize}px`;
  ```
- **Reproduction / verification:** in DevTools, watch the `#view-settings` subtree with a `MutationObserver` while dragging the glass-blur slider; `childList` records appear for the status paragraphs on every `input` event.
- **Suggested fix:** compare before assigning (the pattern already used two lines above), or move the status text out of `#view-settings` / stop observing `childList` in `settings-view.js` (the observer only needs `attributes:['class']` for its purpose).
- **Fix side effects:** none; the text content is identical.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (no finding raised):

- **Secret masking on the read path.** `core/api.py::_mask_secrets` correctly returns `""` + `has_<key>` for `auth.yandex_token` and `auth.oauth_client_secret`; `get_settings`, `get_settings_by_category` and `get_setting` all route through it. `get_all_settings()` (WN-08) is a thin alias of `get_settings()` and inherits the masking. The `subscription` category is deliberately excluded from the category list in `get_settings()`, so the (unused) licence key never reaches the frontend. `settings.js:948-984` correctly clears the token and secret inputs and shows a "saved" placeholder instead — **the masking IS preserved when the value is written back** for these two fields.
- **`window-resize.js` pointer capture.** The handler never takes DOM pointer capture (`setPointerCapture` is not called anywhere in the file); the native Windows sizing loop owns the drag. The defensive `if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId)` at `:14` therefore has nothing to release, and there is **no pointer-capture leak**. `event.preventDefault()`/`stopPropagation()` are called synchronously before the first `await`, so the default drag is suppressed correctly.
- **Theme switching mechanism.** Themes are **not** applied by rewriting a `<style>` element. `document.documentElement.setAttribute('data-theme', id)` swaps an attribute and `css/themes.css` supplies 22 `:root[data-theme="…"]` token blocks (plus a `[data-theme="light"]` block). No `adoptedStyleSheets`, no `<style>` element is created or rewritten anywhere in the UI JS (verified by grep). The per-theme restyle is a normal CSS custom-property re-resolution, not a full stylesheet reparse.
- **No listener leak per settings visit.** Every re-bindable setup function guards its listeners: `setupToggle` removes the previous `_boundClick` (`settings.js:648`), `setupSlider` removes `_boundInput`/`_boundChange` (`:689-690`), `setupOptimizationPanel`'s `setupCardGroup` removes `_boundClick` (`:1499`), `setupIconsPanel` uses `grid.dataset.bound` (`:2416`), `setupZapretPanel` uses `_zapretListenersAttached` (`:1909`), `setupWorkshopPanel` uses the `refreshWorkshop` closure (`:3117`). `initSettings()` runs once (guarded by `window._nedotifyInitialized` in `main.js:391`). No duplicate-listener growth was found.
- **The settings payload is NOT refetched on every panel open.** `pages.js:138` calls `loadSettings()`, which issues only `get_storage_info()` (`settings.js:1083-1089`). The full settings payload is fetched exactly once, at startup (`main.js:408-423`), and is then cached in `localStorage['nedotify_cached_settings']` so the next cold start paints from cache.
- **The settings panel is not rebuilt wholesale on every change.** The panel DOM lives in `index.html`; the JS only performs targeted rebuilds (`renderThemePresets`, `renderFontCards`, `renderKeybindsList`, `renderSavedCustomThemes`, workshop `render()`).
- **The settings live-search does not hide or lose settings.** The `Escape` handler resets the query and restores the previously active panel (`settings.js:3381-3384`); the "nothing found" state is a separate `#settings-search-empty` element.
- **Background image size is bounded.** `compressBackgroundImage` (`utils.js:912-941`) downscales the uploaded wallpaper to a 256 px JPEG at q0.8 before it is persisted, so the base64 blob stored in the settings table and in `localStorage` stays in the tens of kilobytes — the settings store is not being used as an image store.
- **The `appearance-assets.js` resolver is safe.** `resolveBackground` only rewrites `images.unsplash.com` URLs that are in the 27-photo allow-list (plus the `wsrv.nl` unwrap and one documented 404 fix-up) and returns every other value unchanged; `data:` URLs, arbitrary hosts and relative paths pass through untouched (`appearance-assets.js:30-45`).
- **The hotkey mirror contract is pinned.** `tests/test_keybind_contracts.py` parses both `DEFAULT_KEYBINDS` (`hotkeys.js`) and `DEFAULT_SETTINGS["hotkeys"]` (`core/settings.py`) and fails on any id or value drift; it also checks that `executeHotkeysAction` has a branch for every action id and that no second dispatcher exists in `settings.js`. The two tables currently match exactly (10 ids, no value drift).
- **The `hotkeys.js` legacy-migration logic is careful.** It drops ghost action ids, migrates the old `Ctrl+KeyK` format, and refuses to let the backend shadow defaults for actions it does not know (`hotkeys.js:100-120`).
- **The `feature-controls.js` audio-output refresh is race-safe.** The `outputGeneration` counter discards stale results (`feature-controls.js:30-35`), and the device list is only re-fetched when the Audio tab is opened or a `devicechange` fires.
- **No secret is ever written to the console by the settings code itself.** A grep of `ui/web_new_v2/js` for `console.*(token|secret|password|proxy|cookie|key)` finds no hits in the WN-30 files. (The console exposure of the echoed secret comes from `events.js:74`, attributed in F-WN-30-3.)

---

### 4. Coverage gaps

- **The application was never launched** (forbidden by the ground rules). Every runtime claim below is therefore derived from code reading or from executing the real source in a Node `vm`, not from observing the app. In particular I could not measure: the visible magnitude of the workshop-search rebuild (F-WN-30-8), the settings-search keystroke cost (F-WN-30-9), the `syncResources` → `syncControls` cascade cost (F-WN-30-11), or the colour-picker drag stutter (F-WN-30-6). The *rebuild/write counts* are confirmed; only the perceptual consequences are hypotheses.
- **The DOM stubs in the Node probes are minimal.** `document.querySelectorAll` returns `[]` and `getElementById` returns a small element map, so the probes prove *what the code writes and calls*, not the behaviour of the real layout, the real Lucide icon set or the real CSS. Any finding that depends on real layout (e.g. the exact paint cost of a 48 KB `innerHTML` replacement) is marked as a hypothesis.
- **I did not execute the WebView2 process itself**, so the claim that `window.pywebview.api.save_setting` really is invoked once per colour-picker `input` event is derived from the code path (`settings.js:1750` → `saveSetting` → `window.pywebview.api.save_setting`) plus the measured number of `saveSetting` invocations; the bridge hop itself was not observed.
- **The `_emit` → `evaluate_js` hop count for F-WN-30-6** was not measured; the number of bridge round-trips is confirmed, the number of UI-thread hops is inferred from `core/api.py:1122-1159`.
- **The console exposure in F-WN-30-3** was not observed in a live session; it is derived from `events.js:74` (an unconditional `console.log` of every event payload) plus `core/api.py:2952` (the echo) plus `debug.js:37` (the on-screen mirror). The `?debug=1` path is opt-in (`main.js:437-442`).
- **I did not audit `ui/web_new_v2/index.html`'s settings markup as an area in itself** (WN-28/WN-33 ownership), only the specific attributes that WN-30's code depends on (input types, element ids, data attributes).
- **The equalizer UI tests (`tests/test_equalizer_controls_ui.py`) belong to WN-29**; I read them only to judge whether the WN-30 test suite is behavioural or textual, and did not review `js/equalizer.js`.
- **Not verified: whether the SQLite settings table is itself encrypted.** `core/database.py` was not opened for this area; if the DB is plaintext (it appears to be, per the storage description in the brief), then F-WN-30-1's localStorage copy is the *second* plaintext copy of the token, not the only one. This does not change the finding, but it changes the fix priority: the backend should treat the token as sensitive-at-rest too.
- **`js/appearance-assets.js` preloading was checked but not benchmarked.** `backgroundPaths` is exported and never used by any caller (verified by grep) — so there is no explicit preload of the 27 background JPEGs; they are fetched on demand. `ui-style.js:175-189` *does* preload the macOS backdrop through `new Image()` before swapping it in, which is the correct pattern.

---

### 5. Architecture improvements (ARCH)

No proven defect — these are engineering improvements for the coordinator to schedule.

**ARCH-1 — Turn the settings into a declarative table (the single highest-value change in this area).**
`js/settings.js` is 3388 physical lines (the area map's "3111 L" is already stale) and contains ~94 hand-written imperative call sites, each re-implementing load → preview → persist → restore. `core/settings.py::DEFAULT_SETTINGS` is a second, independent copy of the same schema, and the two have already drifted (`player.mp_pos`, `storage.cache_quota_gb`, `theme.custom_palette_enabled` are written by the UI but not declared; `audio.queue_autopilot`/`flow_enabled` are declared but never written). A data-driven schema — one table of `{category, key, type, default, control, secret?}` that both the JS and Python read — would eliminate the entire "control exists but nothing saves it" class, kill the fallback chains (`savedSetting('player','queue_autopilot', savedSetting('player','flow_enabled', true))`), and let `save_setting` reject unknown keys instead of storing them forever. Because the project has no build step, the table should be plain JSON/JS that both sides parse, not generated code.

**ARCH-2 — One persistence primitive for the whole frontend.**
`settings.js::saveSetting` (toast + failure signal), `hotkeys.js`'s bare `window.pywebview.api.save_setting(...)` (no handling — F-WN-30-5) and `feature-controls.js`'s direct `window.pywebview.api.*` calls are three different persistence styles. Extract `js/settings-store.js` with `persist(category, key, value)` that owns the localStorage mirror, the secret policy and the failure reporting; both `settings.js` and `hotkeys.js` can import it without the `settings.js ↔ hotkeys.js` cycle.

**ARCH-3 — One secret policy, owned by the backend, consumed by the frontend.**
`_SECRET_SETTING_KEYS` (`core/api.py:240`) is currently a two-entry tuple that has already missed `proxy_url` (F-WN-30-2) and does not cover the *write* echo (F-WN-30-3) or the frontend's localStorage mirror (F-WN-30-1). Publish the list once — e.g. as part of the settings schema — and have the backend mask reads, mask emits, and expose a `secret` flag the frontend uses to decide whether to mirror into localStorage and whether to mask the input.

**ARCH-4 — Split `js/settings.js` by panel.**
The file mixes the settings schema, DOM construction, event wiring, persistence, validation, the workshop gallery, the duplicate-scanner UI, the import/export UI, the icon-pack catalogue and the keybind renderer. A per-panel split (`js/panels/appearance.js`, `…/player.js`, `…/optimization.js`, `…/zapret.js`, `…/keybinds.js`, `…/workshop.js`) would let each panel own its own setup/teardown and make the "one file, one init" coupling explicit. `js/settings-view.js` and `js/ui-style.js` already show the shape the codebase is moving toward (presentation vs. state), and the remaining 3388 lines are the part that has not been split yet.

**ARCH-5 — Adopt the "preview on `input`, commit on `change`" rule everywhere.**
`setupSlider` and `player-progress-color` already follow it; the custom-colour pickers (F-WN-30-6), the workshop search (F-WN-30-8) and the settings search (F-WN-30-9) do not. Stating the rule in `CODING_STANDARDS.md` and applying it uniformly would remove the write storms without per-site fixes.

**ARCH-6 — Give the appearance layer its own DOM instead of writing into the settings panel.**
`ui-style.js` writes status text into `#view-settings` (`ui-style.js:115-125`), which wakes `settings-view.js`'s subtree observer (F-WN-30-11). Moving the macOS effect status into a container the appearance layer owns (or exposing a small `renderStatus()` callback) would remove the cross-module coupling and the rescan.

**ARCH-7 — Reconsider the `setting_changed` event.**
It is emitted on every single settings write (`core/api.py:2952`) — i.e. once per bridge call — and the only consumer is an empty `case` (`events.js:313`). Either give it a real consumer (so multi-window / tray state stays in sync) or drop it; as it stands every palette drag produces a UI-thread `evaluate_js` hop that nobody reads.

**ARCH-8 — Trim the dead schema.**
`core/settings.py::DEFAULT_SETTINGS` declares ~40 keys the UI never writes (`overlay.*`, `player_appearance.*`, `personalization.*` except onboarding, `session.*` except the ones `core/session.py` owns, `subscription.*`, `services.*`, `general.*` beyond `region`). Conversely the UI writes three keys the schema does not know. A one-off reconciliation would make the schema a truthful description of the app instead of an archaeological record.
