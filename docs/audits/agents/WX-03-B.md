## SCENARIO WX-03 — Settings round-trip (`core/settings.py` ↔ `js/settings.js` ↔ `AppApi.get_settings`/`save_setting` ↔ `core/database.py::set_setting` ↔ `js/hotkeys.js`) — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `core/settings.py` | 1–589 (whole) |
| `core/api.py` | 225–344, 344–423, 1122–1176, 1840–1919, 2740–3019, 3770–3829, 4130–4169 |
| `core/database.py` | 145–204, 480–639, 2010–2169 |
| `core/app.py` | 540–586 |
| `core/offline.py` | 1–77 (whole) |
| `core/session.py` | 57–63 (grep-confirmed writer) |
| `services/base_service.py` | 22–66 (`normalize_proxy_url`) |
| `services/youtube_service.py` | 835–874 (browser-cookie setting) |
| `services/zapret_service.py` | 690–779, 1100–1159 (`find_binary`, `sanitize_zapret_args`) |
| `ui/web_new_v2/js/settings.js` | 1–70, 68–117, 360–469, 675–734, 900–1139, 1178–1262, 3340–3388 |
| `ui/web_new_v2/js/hotkeys.js` | 1–256 (whole) |
| `ui/web_new_v2/js/main.js` | 385–454 |
| `ui/web_new_v2/js/events.js` | 300–344 |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 |
| `ui/web_new_v2/js/onboarding.js` | 50–99, 168–217 |
| `ui/web_new_v2/js/pages.js` | 125–154 |
| `ui/web_new_v2/js/lyrics.js` | 108–187 |
| `ui/web_new_v2/js/player.js` | 1440, 1524 (grep-confirmed offline guards) |
| `ui/web_new_v2/js/utils.js` | 526, 608 (grep-confirmed offline guards) |
| `ui/web_new_v2/index.html` | 1692, 1718, 1734, 1748, 1755 (auth inputs) |
| `tests/conftest.py` | 1–115 |
| `tests/test_api_f1_audit.py` | 1–380 |

**Callees traced into other areas**

- `core/session.py` (session persistence via `SettingsManager.set`) — WN-02.
- `services/base_service.py::normalize_proxy_url` (proxy credential handling) — WN-18.
- `services/youtube_service.py` (writes `auth.browser_cookies`) — WN-19.
- `services/zapret_service.py::find_binary` / `sanitize_zapret_args` (consumes `zapret.binary_path` / `zapret.custom_args`) — WN-26.
- `core/offline.py::is_offline` (consumes `network.offline_mode`) — WN-15.
- `core/database.py` migrations that write raw rows into the `settings` table — WN-12.
- `ui/web_new_v2/js/player.js`, `js/utils.js`, `js/feature-controls.js` (consume `window.settings.network.offline_mode`) — WN-29 / WN-28 / WN-30.

**Verification harness (read-only; never touched `~/.nedotify/`)**

Four throwaway probes under `%TEMP%\opencode\wx03_probe*.py`, each building a **real** `DatabaseManager` on a temp file + a real `SettingsManager` + a real `AppApi` (`_emit` stubbed). Numbers quoted below are measured, not estimated. The repo suite
`tests/test_keybind_contracts.py tests/test_settings_flush.py tests/test_settings_manager.py tests/test_api_f1_audit.py` → **100 passed**, so nothing below is a known failing test.

---

### 2. Findings

#### F-WX-03-1  [P1] — `network.offline_mode` never round-trips: the persisted offline state is dropped from `get_settings()` and the frontend runs online while the backend runs offline

- **File:** `core/api.py:2922-2938` (the hard-coded category whitelist), `core/settings.py:52-55` (`DEFAULT_SETTINGS["network"]`), `ui/web_new_v2/js/feature-controls.js:112` and `:133`, `ui/web_new_v2/js/player.js:1440`, `ui/web_new_v2/js/utils.js:526`, `:608`
- **Confirmed:** yes
- **Description:** `DEFAULT_SETTINGS` declares a `network` category (`{"offline_mode": False}`), and `AppApi.set_offline_mode` persists `network.offline_mode` into the DB (`core/api.py:4135`). But `AppApi.get_settings()` iterates a *second, hand-maintained* list of 22 category names that does **not** contain `network` (nor `subscription`). The category is therefore never serialised into the blob, so `window.settings.network` is `undefined` in the WebView. The frontend's only restore path is `window.settings?.network?.offline_mode` (`feature-controls.js:112` and the `nedotify:settings_applied` listener at `:133`); the dedicated `AppApi.get_offline_state()` bridge method has **no caller anywhere in `ui/web_new_v2/`**. Consequently `applyOfflineState({enabled: false})` runs at every start: the `offline-mode` CSS class is removed, the offline note stays hidden, and `nedotify:offline_mode_changed` is not dispatched — while `core/offline.py::is_offline(settings)` returns `True` and the backend refuses network resolution.
- **Cause:** two registries describe the same schema — `core/settings.py::DEFAULT_SETTINGS` (20 categories) and the literal list inside `core/api.py::get_settings` (22 names). They disagree: `network` and `subscription` are in the schema but not in the transport list; `appearance`, `player`, `lyrics`, `system` are in the transport list but not in the schema. Nothing checks the two against each other, so the divergence is silent.
- **Trigger conditions:** the user enables offline mode (Settings → storage/network, or the "go online" error action) and then restarts the app. Also true for every fresh start with `network.offline_mode` already `True` in the DB.
- **User impact:** the app is in offline mode in the backend but the UI shows the online state. The frontend keeps issuing work the backend will refuse: `player.js:1440` prefetches a track (`!window.settings?.network?.offline_mode` is true) and `utils.js:526`/`:608` keep emitting/loading remote cover URLs. The `offline-mode` CSS class and the offline notice are missing, so the UI gives no indication that the app is offline. It self-corrects only if the user touches the offline toggle again.
- **Evidence:**
  ```python
  # core/api.py:2922-2938
  def get_settings(self, category: str = None):
      if category:
          return _mask_secrets(category, self._core.settings.get_category(category))
      # SettingsManager exposes get_category() only - there is no get_all(),
      # so the whole tree is assembled category by category.
      categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio',
                    'overlay', 'efficiency', 'optimization', 'hotkeys', 'storage',
                    'player_appearance', 'personalization', 'interface', 'ui', 'theme',
                    'equalizer', 'auth', 'services', 'session', 'zapret']
  ```
  ```javascript
  // ui/web_new_v2/js/feature-controls.js:109-112
  export function initFeatureControls() {
      if (initialized) return;
      initialized = true;
      applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe4.py` (real `AppApi` + real `SettingsManager` over a temp DB):
  ```
  persisted in the DB   : True | row: [('network.offline_mode', 'true', 'network')]
  backend is_offline()  : True
  'network' in get_settings()      : False
  get_settings() categories        : ['app','audio','auth','efficiency','equalizer','general',
                                      'hotkeys','interface','optimization','overlay','personalization',
                                      'player_appearance','services','session','storage','theme','ui','zapret']
  get_settings('network')          : {'offline_mode': True}
  frontend applyOfflineState(enabled): False -> the 'offline-mode' CSS class is NOT applied
  in DEFAULT_SETTINGS but NOT shipped: ['network', 'subscription']
  ```
  Note `get_settings('network')` *does* return it — the bug is only in the no-argument (whole-tree) form the UI actually calls.
- **Suggested fix:** derive the transport list from the schema instead of hard-coding it: iterate `DEFAULT_SETTINGS` (plus an explicit list of the undeclared frontend categories) and build the blob from that, so a new category cannot be forgotten. Separately, either call `get_offline_state()` at startup or add `network` to the blob.
- **Fix side effects:** `subscription` must stay excluded on purpose (it is the licence key; see F-WX-03-3), so the derived list needs an explicit exclusion rather than "everything in `DEFAULT_SETTINGS`". Shipping `network` adds one key to the blob.
- **Discovered by:** B

---

#### F-WX-03-2  [P1] — `auth.proxy_url` carries proxy credentials across the bridge in clear text and is persisted twice into unencrypted `localStorage`

- **File:** `core/api.py:240` (`_SECRET_SETTING_KEYS`), `core/api.py:243-253` (`_mask_secrets`), `core/api.py:2925`, `:2935`, `:2959` (the three read paths), `core/settings.py:246`, `services/base_service.py:25-62`, `ui/web_new_v2/index.html:1755`, `ui/web_new_v2/js/settings.js:962-965`, `:1040`, `ui/web_new_v2/js/main.js:411-414`
- **Confirmed:** yes
- **Description:** the masking policy is a two-entry allow-list — `{"auth": ("yandex_token", "oauth_client_secret")}` — and `auth.proxy_url` is not in it. `normalize_proxy_url` (WN-18) accepts any `http/https/socks*` URL with a hostname **and preserves the userinfo component**, so `http://alice:hunter2@10.0.0.1:8080` is a valid proxy setting. That value is returned verbatim by `get_settings()`, `get_settings(category)` and `get_settings_by_category('auth')`, merged into `window.settings.auth.proxy_url` by `applySettingsFromBackend` (`settings.js:716-719`), written into `localStorage` under **two** keys (`nedotify_cached_settings` at `main.js:414` — the whole blob — and `nedotify_auth_proxy_url` at `settings.js:1040`), and rendered in a `type="text"` input.
- **Cause:** the secret list was written when only two credentials existed; the proxy URL is a third credential but was never classified as one. The read path is the only place masking is applied, so anything the frontend mirrors into `window.settings` / `localStorage` inherits the unmasked value.
- **Trigger conditions:** any user who configures an authenticated proxy. Every app start then writes the credential into the WebView2 profile on disk.
- **User impact:** the proxy password is present in the WebView's JS heap, in two unencrypted `localStorage` entries (readable by any process with access to the WebView2 user-data folder, and by anything that reaches the page), and in clear text on screen. The `yandex_token` in the same panel is properly masked, so the inconsistency is visible to the user.
- **Evidence:**
  ```python
  # core/api.py:239-253
  # Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}

  def _mask_secrets(category: str, data: dict) -> dict:
      secret_keys = _SECRET_SETTING_KEYS.get(category)
      if not secret_keys or not isinstance(data, dict):
          return data
      masked = dict(data)
      for key in secret_keys:
          if key in masked:
              masked[f"has_{key}"] = bool(masked[key])
              masked[key] = ""
      return masked
  ```
  ```html
  <!-- ui/web_new_v2/index.html:1755 -->
  <input type="text" class="settings-input" id="input-proxy-url" aria-label="HTTP/HTTPS прокси" placeholder="http://127.0.0.1:1080">
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe2.py` §F:
  ```
  get_settings('auth') -> {'yandex_token': '', 'has_yandex_token': True, 'oauth_client_secret': '',
                            'proxy_url': 'http://alice:hunter2@10.0.0.1:8080'}
  get_settings()['auth']['proxy_url'] -> http://alice:hunter2@10.0.0.1:8080
  ```
  and `%TEMP%\opencode\wx03_probe.py` §8 (raw `get_category('auth')` → `proxy_url` unmasked).
- **Suggested fix:** add `"proxy_url"` to `_SECRET_SETTING_KEYS` (mask on read, treat a blank write as "keep the stored value"), render the field as `type="password"` with a `has_proxy_url` affordance, and stop mirroring the credential into `localStorage` (skip secret keys in the `saveSetting` mirror).
- **Fix side effects:** the proxy field would appear empty after a restart and the user could no longer read back the URL to edit it; they would have to retype it. `services/*` read the value from `SettingsManager`, not from the bridge, so the backend keeps working unchanged.
- **Discovered by:** B

---

#### F-WX-03-3  [P2] — The bridge has no settings schema: any `(category, key)` pair can be written, and the read side has no category allow-list (the licence key is readable from JS)

- **File:** `core/api.py:256-269` (`_BRIDGE_READONLY_SETTINGS`, `_bridge_write_error`), `core/api.py:2940-2953` (`save_setting`), `core/api.py:2922-2938` / `:2958-2959` (read paths), `core/settings.py:401-418` (`SettingsManager.set`), `core/database.py:2049-2082` (`set_settings_batch`)
- **Confirmed:** yes
- **Description:** `_BRIDGE_READONLY_SETTINGS` contains exactly one pair (`("general", "plugins_enabled")`). Everything else is accepted: `save_setting("totally_made_up", {...}, "attacker_ns")` writes a row `attacker_ns.totally_made_up` into the `settings` table and returns `True`. `SettingsManager.set` creates the category on the fly (`core/settings.py:414-415`) and `DatabaseManager.set_settings_batch` inserts whatever key it is handed. Symmetrically, `get_settings(category)` and `get_settings_by_category(category)` accept **any** category string — `get_settings_by_category('subscription')` returns `{'key': 'LICENCE-KEY-ABC123', ...}` **unmasked**, because `_SECRET_SETTING_KEYS` has no `subscription` entry. (The whole-tree `get_settings()` happens to omit `subscription` — see F-WX-03-1 — but the single-category form does not.)
- **Cause:** the settings store is an untyped key/value table whose only contract is a Python dict literal (`DEFAULT_SETTINGS`) that the bridge never consults. Secret handling is a per-category allow-list rather than a property of the key.
- **Trigger conditions:** any script running in the WebView (the bridge is fully public: `window.pywebview.api.save_setting(...)`), or a future backend feature that stores a credential outside `auth`.
- **User impact:** (a) the `settings` table is an unbounded, untyped sink — one row per call, no size or key validation; (b) the "secrets never travel to JS" property depends on a hand-maintained two-entry dict, so a secret stored in a new category silently ships to the WebView; (c) the licence key in `subscription` is reachable from JS today via `get_settings_by_category('subscription')`.
- **Evidence:**
  ```python
  # core/api.py:256-269
  # Settings the bridge refuses to write: enabling plugins runs third-party code.
  _BRIDGE_READONLY_SETTINGS = {("general", "plugins_enabled")}

  def _bridge_write_error(category: str, key: str, value):
      """Error message when a bridge write must be refused, else None."""
      if (category, key) in _BRIDGE_READONLY_SETTINGS:
          return f"{category}.{key} cannot be changed from the UI"
      return None
  ```
  ```python
  # core/settings.py:413-417
  with self._lock:
      if category not in self._cache:
          self._cache[category] = {}
      self._cache[category][key] = value
      self._dirty.add((category, key))
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe2.py` §A and §E:
  ```
  save_setting -> True
  rows written: [('attacker_ns.totally_made_up', 'attacker_ns', 415)]
  get_settings_by_category('subscription') -> {'key': 'LICENCE-KEY-ABC123', ...}
  get_settings('subscription')             -> {'key': 'LICENCE-KEY-ABC123', ...}
  ```
- **Suggested fix:** validate `(category, key)` at the bridge boundary against `DEFAULT_SETTINGS` **plus** an explicit allow-list of the undeclared frontend namespaces the UI actually uses (`player.*`, `lyrics.lyrics_offset_*`, `personalization.nickname`, `personalization.pinned_track`, `personalization.avatar_path`, `theme.custom_palette_enabled`, `theme.color_*`, `equalizer.mode`, `storage.cache_quota_gb`, `app.avatar_path`, `app.current_theme`, `general.plugins_enabled` read-only); mark the secret keys as a property of the key, not of the category; and route every read through one masking function.
- **Fix side effects:** building the allow-list is the bulk of the work — a wrong list silently breaks a settings control. `subscription` should stay unreadable from JS, so it must be excluded explicitly rather than by accident.
- **Discovered by:** B

---

#### F-WX-03-4  [P2] — `save_setting` echoes the raw secret value back to JS in the `setting_changed` event, contradicting the module's own "secrets never travel back to JS" contract

- **File:** `core/api.py:239` (the contract comment), `core/api.py:2952` (the emit), `core/api.py:1887` / `:1896` (the same emit in `set_setting`), `ui/web_new_v2/js/events.js:313-315` (the only consumer)
- **Confirmed:** yes
- **Description:** masking is applied **only** on the read path (`_mask_secrets`). The write path emits the unredacted value: `self._emit("setting_changed", {"category": category, "key": key, "value": value})`. Writing `auth.yandex_token` therefore ships the token to the WebView a second time, in a second channel, with no `has_*` flag. The frontend's only handler for the event is `case 'setting_changed': break;` — it does nothing.
- **Cause:** the secret policy lives in the read path only; the event bus was never brought under it.
- **Trigger conditions:** every write of a secret through the bridge. (A backend-side write via `SettingsManager.set` does not emit, so it does not leak this way.)
- **User impact:** the masking guarantee is one bridge method away from being void, and the secret is delivered for a consumer that does not exist. Today the value originated in the same WebView, so this is not a new disclosure to a third party — but it is a redundant copy of a credential sitting in the event bus, and it is the obvious next thing a "settings sync" / "undo" / debug consumer would pick up.
- **Evidence:**
  ```python
  # core/api.py:239 (contract)  vs  core/api.py:2952 (violation)
  # Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
  ...
      self._emit("setting_changed", {"category": category, "key": key, "value": value})
  ```
  ```javascript
  // ui/web_new_v2/js/events.js:313-315
  case 'setting_changed':
      // data = { key, value, category }
      break;
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe2.py` §B:
  ```
  emitted: [('setting_changed', {'category': 'auth', 'key': 'yandex_token', 'value': 'RAW-SECRET-TOKEN'})]
  ```
- **Suggested fix:** redact the value in the emit for secret keys (emit `has_<key>` instead of the value), or drop the emit entirely until something consumes it (see F-WX-03-8).
- **Fix side effects:** any future consumer that relies on the echoed value for non-secret keys is unaffected if only secret keys are redacted.
- **Discovered by:** B

---

#### F-WX-03-5  [P2] — Three divergent parallel bridge write paths: `set_setting` never performs the autostart side effect, and `save_setting` swallows its failure

- **File:** `core/api.py:1871-1900` (`set_setting`), `core/api.py:2940-2953` (`save_setting`), `core/api.py:2961-2962` (`update_setting`), `core/api.py:2839-2890` (`update_autostart`), `core/api.py:2787-2790` (`complete_onboarding`)
- **Confirmed:** yes
- **Description:** three public bridge methods write the same store and have **different** side-effect semantics:
  1. `save_setting(key, value, category)` — calls `update_autostart` when the key is `autostart`, but **ignores its boolean result** and returns `True` ("saved") either way. It also writes the autostart mirror *before* the registry write is confirmed.
  2. `update_setting(category, key, value)` — delegates to `save_setting` (consistent).
  3. `set_setting(section, key, value)` — does **not** call `update_autostart` at all, so it writes `general.autostart = True` while leaving `app.autostart` at its default `False` and never touching the HKCU Run entry.
  `complete_onboarding` is the only caller that checks the result (`core/api.py:2789`).
- **Cause:** the autostart side effect is attached to one write method instead of to the setting itself, so the other write paths silently skip it — and the one path that does call it discards the failure.
- **Trigger conditions:** (a) `save_setting('autostart', true, 'general')` while the registry write fails (HKCU locked, policy restriction) → the setting is stored as ON and the UI shows "Автозапуск включён" but Windows never starts the app. (b) any call to `window.pywebview.api.set_setting('general','autostart',true)` → the setting flips to ON with no Run entry and `app.autostart` stays OFF.
- **User impact:** the UI and Windows disagree about autostart, and the app silently fails to start at logon. The second variant also desynchronises the two mirrors (`general.autostart` vs `app.autostart`), which the onboarding path keeps in sync.
- **Evidence:**
  ```python
  # core/api.py:2946-2953 (save_setting)
      self._core.settings.set(category, key, value)
      if key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart"):
          try:
              self.update_autostart(bool(value))
          except Exception as e:
              logger.warning(f"Failed to sync autostart in save_setting: {e}")
      self._emit("setting_changed", {"category": category, "key": key, "value": value})
      return True
  ```
  ```python
  # core/api.py:1895-1897 (set_setting) - no autostart side effect at all
                  self._core.settings.set(section, key, value)
                  self._emit("setting_changed", {"category": section, "key": key, "value": value})
                  return {"success": True}
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe2.py` §C and §D:
  ```
  save_setting('autostart') -> update_autostart called with: [True]
  set_setting('general','autostart') -> update_autostart called with: []  result: {'success': True}
  settings general.autostart = True | app.autostart = False
  ---
  save_setting returned: True  (True = 'saved') while the registry write FAILED
  stored general.autostart = True -> UI shows ON, OS has no Run entry
  ```
- **Suggested fix:** make `set_setting` delegate to `save_setting`; check the `update_autostart` result and either roll the setting back or report the failure; keep the side effect in the api layer (not in `SettingsManager`, which must not import `winreg`).
- **Fix side effects:** returning `False`/an error from `save_setting` when the registry write fails changes the UI contract for the autostart toggle — the settings panel will have to distinguish "setting saved" from "autostart registered".
- **Discovered by:** B

---

#### F-WX-03-6  [P2] — Onboarding is two transactions, not one, and the failed-first-flush branch returns without rolling the in-memory state back → a half-configured app

- **File:** `core/api.py:2756-2837` (`complete_onboarding`)
- **Confirmed:** yes
- **Description:** the happy path uses **two** DB transactions: 23 preference keys, then the 2 completion flags (`general.first_launch_done`, `personalization.onboarding_completed`). The failure branch at `:2826-2827` returns `{"success": False}` **without undoing** the 23 in-memory changes: they stay in `SettingsManager._dirty` and the writer thread persists them a moment later, while the completion flags are never set. The `except` handler at `:2833-2836` restores only the two flags, not the other 21 keys.
- **Cause:** the completion flags are deliberately written in a second transaction *after* the preferences, and the rollback is asymmetric — it covers the flags but not the preferences. The registry side effect (`update_autostart`, `:2789`) is applied **before** any DB commit, so it is not rolled back either.
- **Trigger conditions:** the first `sync_flush_now()` fails (DB locked, disk full, write error). Probe: `set_settings_batch` returning 0.
- **User impact:** the app comes up with the new theme / particles / performance preset applied but with `first_launch_done = False`, so the onboarding wizard runs again on the next start — with the user's previous choices already in effect and the draft state (`nedotify_onboarding_draft`) out of step. The user sees an error toast with no indication of what was saved. If autostart was requested, Windows also starts the app at logon while the stored setting says "off".
- **Evidence:**
  ```python
  # core/api.py:2825-2837
  flush = getattr(settings, "sync_flush_now", None)
  if callable(flush) and not flush():
      return {"success": False, "error": "Не удалось сохранить настройки. Повторите попытку."}
  settings.set("general", "first_launch_done", True)
  settings.set("personalization", "onboarding_completed", True)
  if callable(flush) and not flush():
      raise RuntimeError("Onboarding completion was not persisted")
  return {"success": True, "settings": self.get_settings()}
  except Exception:
      logger.exception("Failed to complete onboarding")
      settings.set("general", "first_launch_done", previous_flags[0])
      settings.set("personalization", "onboarding_completed", previous_flags[1])
      return {"success": False, "error": "Не удалось сохранить настройки. Повторите попытку."}
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe3.py`:
  ```
  === 1. HAPPY PATH ===
  DB transactions used for the whole onboarding: 2
  keys per transaction: [23, 2]
  === 2. DB WRITE FAILS ON THE FIRST FLUSH ===
  result: {'success': False, ...}
  theme in the IN-MEMORY cache now: midnight (was dark )
  first_launch_done (cache): False
  pending dirty keys still queued for the writer thread: 23
  DB rows actually written: 2
  === 3. ORDER ===
    1. update_autostart(registry) = True
    2. settings.set(theme.theme) = midnight
    ... the registry write happens FIRST; the DB commit happens LAST.
  ```
- **Suggested fix:** write the preferences **and** the completion flags in a single `sync_flush_now()` (one transaction), and roll the in-memory cache back to the pre-onboarding snapshot when the write fails. Apply the registry side effect *after* the successful commit, or record it for rollback.
- **Fix side effects:** with one transaction, `first_launch_done` becomes true only together with the preferences — if the commit fails the wizard reappears, which is the intended behaviour. Rolling back the in-memory cache must not undo unrelated concurrent writes.
- **Discovered by:** B

---

#### F-WX-03-7  [P2] — The settings blob grows without bound (one row per track for lyrics offsets) and the whole blob is re-serialised, compared and mirrored into `localStorage` at every start

- **File:** `ui/web_new_v2/js/lyrics.js:124-126` and `:176-178` (the writers), `core/settings.py:336-342` (`_load_all` copies every dotted row into the cache), `core/api.py:2929-2938` (the whole tree is shipped), `ui/web_new_v2/js/main.js:409-418` (stringify + compare + store)
- **Confirmed:** yes
- **Description:** `js/lyrics.js` stores the per-track lyrics offset in the shared settings table under `lyrics.lyrics_offset_<trackKey>` — one row per track the user ever nudged. `SettingsManager._load_all` copies **every** dotted row of the table into the in-memory cache, and `AppApi.get_settings()` ships the whole `lyrics` category to the WebView. At start the blob is `JSON.stringify`-ed, compared against the cached copy and written to `localStorage`.
- **Cause:** per-entity state was put into a global key/value store instead of a per-track table, and the whole tree is transported although the UI only needs a handful of categories.
- **Trigger conditions:** normal use — every lyrics-offset nudge adds a row that is never removed.
- **User impact:** the settings blob and the `settings` table grow linearly with the number of tracks touched; the startup cost (parse + merge into `window.settings` + `localStorage` write) grows with them. Measured: 2000 offsets → 2007 rows and a **69 KB** blob; adding a realistic 500-track queue and 1000 disliked tracks → a **254 KB** blob.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/lyrics.js:176-178
  if (window.pywebview?.api?.save_setting) {
      window.pywebview.api.save_setting(`lyrics_offset_${trackKey}`, currentOffsetMs, 'lyrics');
  }
  ```
  ```python
  # core/settings.py:336-342
  for full_key, value in stored_all.items():
      if not '.' in full_key:
          continue
      cat, k = full_key.split('.', 1)
      if cat not in self._cache:
          self._cache[cat] = {}
      self._cache[cat][k] = value
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe.py` §2 and `%TEMP%\opencode\wx03_probe2.py` §G/§H:
  ```
  lyrics keys: 500   blob json bytes: 19904   DB rows in settings table: 502
  lyrics entries in blob: 2000   blob bytes: 70997  blob KB: 69.3   DB settings rows: 2007
  blob bytes with a 500-track queue + 1000 disliked tracks: 259883 KB: 253.8
  ```
- **Suggested fix:** move the per-track lyrics offsets out of the `settings` table (a dedicated `lyrics_offsets` table keyed by track), or at minimum stop shipping the `lyrics` category in the blob and fetch it on demand.
- **Fix side effects:** the offsets must survive a restart — a migration for the existing rows is needed. Removing the category from the blob also removes the `lyrics` entries from `window.settings`, which nothing else reads.
- **Discovered by:** B

---

#### F-WX-03-8  [P2] — Every settings save emits a `setting_changed` event that has exactly one consumer, and it does nothing

- **File:** `core/api.py:2952` (emit), `core/api.py:1887`, `:1896`, `core/api.py:1122-1159` (`_emit` → `evaluate_js` through the UI thread), `ui/web_new_v2/js/events.js:313-315`
- **Confirmed:** yes
- **Description:** `save_setting` emits `setting_changed` on every write. The only handler in the whole UI is `case 'setting_changed': break;` — it discards the payload. The emit path marshals `evaluate_js` through the WebView2 UI thread (`Control.Invoke` on the WinForms backend), so every settings change costs a synchronous UI-thread round-trip for an event nobody reads. The "reset hotkeys" button fires 10 of them in a row (`js/settings.js:1136-1139`).
- **Cause:** the event was introduced as a notification channel but was never wired to a consumer; the JS-side `window.settings` cache and the Python-side `SettingsManager._cache` therefore never converge.
- **Trigger conditions:** every settings write from the UI.
- **User impact:** needless UI-thread marshalling per settings change, and two settings caches that can drift: a backend-side change (equalizer, offline mode, zapret, avatar) is never reflected in `window.settings`, because the one event that could have done it is dropped.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/events.js:313-315
  case 'setting_changed':
      // data = { key, value, category }
      break;
  ```
- **Reproduction / verification:** grep over `ui/web_new_v2/**` for `setting_changed` returns exactly two hits — the emit side and this no-op handler. `%TEMP%\opencode\wx03_probe2.py` §B shows the event is emitted with the payload.
- **Suggested fix:** either consume the event — merge `{category, key, value}` into `window.settings` so the JS cache follows the backend — or stop emitting it. Consuming it also closes the gap with F-WX-03-4 (the value would have to be redacted for secrets).
- **Fix side effects:** if the event is consumed, the merge must not clobber a value the user is currently editing in an input.
- **Discovered by:** B

---

#### F-WX-03-9  [P3] — `SettingsManager.get_category()` returns a shallow copy: a caller can mutate the settings cache through it, and the mutation is never persisted

- **File:** `core/settings.py:532-535`
- **Confirmed:** yes
- **Description:** `get_category` returns `self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()` — a **shallow** copy. Nested dicts and lists (`personalization.artist_aliases`, `personalization.artist_bindings`, `equalizer.bands`, `theme.custom_themes`, `session.last_queue`) are the *same objects* the cache holds.
- **Cause:** `.copy()` on a dict of values is not a deep copy; the callers that mutate nested values (`api.py:2988-2999`, `:3007-3018`, `:3475`) each re-copy by hand, which is exactly the smell that indicates the contract is not documented.
- **Trigger conditions:** any in-process caller that mutates a nested value in place instead of copying it first.
- **User impact:** the cache is changed without the key being marked dirty → the change is never written to the DB, and the *next* flush overwrites the DB value with the mutated cache value, so a legitimate direct DB write can be silently reverted. The bridge serialises the result, so today the exposure is limited to Python callers.
- **Evidence:**
  ```python
  # core/settings.py:532-535
  def get_category(self, category: str) -> Dict[str, Any]:
      """Get all settings in a category."""
      with self._lock:
          return self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe.py` §4:
  ```
  cache after mutating the returned dict: {'a': 'MUTATED'}
  ```
  (the returned `artist_aliases` was mutated and the cache followed).
- **Suggested fix:** return a deep copy, or document the mapping as read-only and make the mutating callers copy explicitly (several already do — audit them).
- **Fix side effects:** a `deepcopy` of `session.last_queue` on every `get_settings()` call costs real time on a long queue; the copy could be made per category and cached, or `session` could be excluded from the blob (see F-WX-03-7).
- **Discovered by:** B

---

#### F-WX-03-10  [P3] — A stored hotkey is interpolated into `innerHTML` without escaping (stored-XSS sink fed by an unvalidated backend value)

- **File:** `ui/web_new_v2/js/settings.js:1238-1248` (`renderKeybindsList`), `ui/web_new_v2/js/settings.js:1212-1222` (`formatKeyName`), `ui/web_new_v2/js/settings.js:1185-1189` (`formatBaseKeyName`), `ui/web_new_v2/js/hotkeys.js:104-115` (the DB value enters `activeKeybinds`)
- **Confirmed:** yes for the sink; the trigger currently requires a hand-edited DB row or a direct bridge write — the WebView loads **no** remote content (`ui/web_new_v2/index.html` contains no `<iframe>` and no remote `<script>`), so there is no remote source feeding this sink today
- **Description:** `renderKeybindsList` builds each row with `row.innerHTML = ...${currentKeyDisplay}...` — **unescaped** — while the label right next to it is passed through `escapeHtml(kb.label)`. `currentKeyDisplay` comes from `formatKeyName(activeKeybinds[kb.id])`, and `formatBaseKeyName` returns an unknown code **verbatim** (`return code;`). `activeKeybinds[kb.id]` is populated from the backend (`get_settings_by_category('hotkeys')`), and the backend does not validate the stored combo (see F-WX-03-3).
- **Cause:** the stored key string is treated as trusted because the UI believes only `parseKeyEventCombo` can produce it — an assumption the generic settings bridge breaks.
- **Trigger conditions:** a `hotkeys.play_pause` row in the DB containing markup (hand-edited DB, or `window.pywebview.api.save_setting('play_pause', '<img src=x onerror=…>', 'hotkeys')`).
- **User impact:** markup in a stored hotkey executes in the app's own WebView. It is not a privilege escalation today (the writer already has script access), but it is a stored-XSS sink whose value the backend does not validate, one step away from a remote value.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/settings.js:1238-1248
  const rawKey = activeKeybinds[kb.id] || kb.defaultKey;
  const currentKeyDisplay = formatKeyName(rawKey);
  row.innerHTML = `
      <div>
          <div class="setting-label">${escapeHtml(kb.label)}</div>
      </div>
      <button class="filter-btn keybind-record-btn ${isListening ? 'active' : ''}" style="min-width: 140px; font-size: 13px;">
          ${isListening ? 'Нажмите клавишу...' : currentKeyDisplay}
      </button>
  `;
  ```
- **Reproduction / verification:** store `hotkeys.play_pause = "<img src=x onerror=alert(1)>"` in the settings table, restart, open Settings → the raw markup is written into `row.innerHTML` (the label next to it is escaped, which is the tell).
- **Suggested fix:** `escapeHtml(currentKeyDisplay)` — and, independently, validate the combo on the backend (accept only `Modifier+KeyCode` shapes) so an invalid combo is rejected at the write boundary.
- **Fix side effects:** none for the escaping fix.
- **Discovered by:** B

---

#### F-WX-03-11  [P3] — The `settings` table mixes three key shapes and the loader resolves bare keys into the first category that declares a matching name

- **File:** `core/database.py:502-504` (bare key `portable_library_id`), `core/database.py:621-624` (bare key `migration_dup_cleanup_done`), `core/settings.py:320-334` (the `elif key in stored_all` fallback), `core/settings.py:336-342` (the dotted-key adoption)
- **Confirmed:** yes (mechanism measured; no production collision today)
- **Description:** the `settings` table holds three different key shapes: dotted (`audio.volume`), bare (`portable_library_id`, `migration_dup_cleanup_done` — both written by raw SQL in `DatabaseManager.__init__`), and category-prefixed (`auth.yandex_token`). `SettingsManager._load_all` handles them asymmetrically: the second loop skips every key without a dot, but the **first** loop has `elif key in stored_all: self._cache[category][key] = stored_all[key]` — a bare key is adopted into **every** category that declares a key of that name, in `DEFAULT_SETTINGS` iteration order (first match wins).
- **Cause:** the table is a shared namespace with no key grammar, and the loader tries to be lenient about legacy shapes.
- **Trigger conditions:** a bare key whose name collides with a default key name in some category (e.g. `language`, `volume`, `name`, `mode`). The two bare keys that exist today (`portable_library_id`, `migration_dup_cleanup_done`) do not collide, so nothing breaks yet.
- **User impact:** a future bare key can silently override the default of an unrelated category, and the value it lands in depends on dict iteration order — a value that changes when `DEFAULT_SETTINGS` is reordered.
- **Evidence:**
  ```python
  # core/settings.py:320-334
  for category, defaults in DEFAULT_SETTINGS.items():
      self._cache[category] = {}
      for key, default_value in defaults.items():
          full_key = f"{category}.{key}"
          if full_key in stored_all:
              self._cache[category][key] = stored_all[full_key]
          elif key in stored_all:                       # <-- bare key, ambiguous
              self._cache[category][key] = stored_all[key]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe.py` §5 — after `db.set_setting("language", "XX-BARE-KEY", "general")`:
  ```
  general.language = XX-BARE-KEY
  theme.language  = None
  ```
- **Suggested fix:** give the table a key grammar (`<category>.<key>` only) and move the two migration flags out of the `settings` table (they are migration metadata, not settings) or namespace them (`system.migration_dup_cleanup_done`). Drop the `elif key in stored_all` fallback once the migration keys are namespaced.
- **Fix side effects:** the migration flags are read by `tests/test_dup_cleanup_migration.py` and by `_run_dup_cleanup_migration` (`core/database.py:574-579`) — relocating them needs a migration and a test update.
- **Discovered by:** B

---

#### F-WX-03-12  [P3] — HYPOTHESIS: the async writer can overwrite a newer direct DB write (a lost update); the mechanism is confirmed but has no production trigger today

- **File:** `core/settings.py:443-483` (`flush`), `core/settings.py:485-506` (`_write_batch`), `core/settings.py:520-530` (`_writer_loop`), `core/database.py:2036-2047` (`set_setting`), `core/settings.py:317` (`_load_all` → `get_all_settings`)
- **Confirmed:** mechanism **yes**; production reachability **no** (see below)
- **Description:** the brief's central question. Answer: **there is exactly one production write path** — `AppApi.save_setting`/`set_setting` → `SettingsManager.set` → `_writer_loop` → `flush` → `_write_batch` → `DatabaseManager.set_settings_batch` → SQLite. `DatabaseManager.set_setting` (the *direct* write) has **no production caller** except `SettingsManager._write_batch`'s fallback branch (`core/settings.py:502`), which only runs against a DB object that lacks `set_settings_batch`. The only other raw writes into the `settings` table are the two migration inserts (`core/database.py:502`, `:621`), which run inside `DatabaseManager.__init__` — **before** `SettingsManager` is constructed (`core/app.py:107-108`), so they cannot race the writer. `SettingsManager`'s own concurrency is sound: the payload is captured from the cache under the same `_lock` that `set()` takes, so a concurrent `set()` either lands in the payload or re-dirties the key and is written by the next flush. **However**, the write path is not *closed*: `DatabaseManager.set_setting` is public, and when it is used the two sides diverge in both directions.
- **Cause:** `DatabaseManager.set_setting` bypasses the cache; the cache is never invalidated by a DB write, so a DB-side change is invisible to `SettingsManager` until restart.
- **Trigger conditions (measured, but not reachable from the current production code):** (a) *stale read* — `db.set_setting("audio.volume", 99)` then `sm.get("audio","volume")` still returns the old cached `11`; (b) *lost update* — `sm.set("audio","volume",22)` (pending) → `db.set_setting("audio.volume",99)` (direct, newer) → `sm.flush()` → the DB holds **22**: the newer direct write is overwritten by the older pending one.
- **User impact:** none today (no production caller). The risk is that the next feature that writes a setting directly (a migration, a repair tool, an import path) will silently lose data or read a stale value, and the failure is invisible because the cache and the table disagree.
- **Evidence:**
  ```python
  # core/settings.py:450-459 (flush) - payload snapshot + dirty clear, then the write
  with self._flush_lock:
      with self._lock:
          if not self._dirty:
              return
          pending = list(self._dirty)
          self._dirty.clear()
          payload = [
              (f"{cat}.{k}", self._cache.get(cat, {}).get(k), cat)
              for cat, k in pending
          ]
      written = 0
      ...
  ```
  ```python
  # core/database.py:2036-2047 - the public bypass, no cache invalidation
  def set_setting(self, key: str, value: Any, category: str = "general") -> None:
      with self._write_lock:
          conn = self.conn
          try:
              with conn:
                  cursor = conn.cursor()
                  cursor.execute(
                      "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                      (key, self._serialize_setting(value), category),
                  )
          except Exception as e:
              logger.error(f"set_setting failed for {key}: {e}")
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_probe.py` §3 and §3b:
  ```
  === 3. LOST UPDATE: writer thread vs direct db.set_setting ===
  db value after DIRECT db.set_setting: 99
  SettingsManager cache still says: 11  <-- stale read?
  db value after a subsequent sm flush: 99
  === 3b. REVERSE ORDER: writer pending, then direct write, then writer flushes ===
  db value after writer flush: 22 (99 would mean the direct write survived)
  cache says: 22
  ```
  Evidence that no production caller exists: `rg "set_setting\(" ` over the repo (excluding `tests/`) matches only `core/settings.py:502`, `core/database.py:2036` (the definition) and `core/api.py:1871` (a different, bridge-level method).
- **Suggested fix:** close the write path — make the direct DB write private (`_set_setting_direct`) or make `SettingsManager` the only public writer, and add a regression test that asserts no module outside `core/settings.py` writes to the `settings` table.
- **Fix side effects:** `tools/bench/profile.py:227-270` and several tests call `db.set_setting` directly; the bench harness would need the private name or a sanctioned helper.
- **Discovered by:** B

---

### 3. Clean areas

- **The write-behind batching itself is correct.** `SettingsManager.flush` (`core/settings.py:443-483`) captures the payload from the cache **under the same `_lock` that `set()` takes**, so a concurrent `set()` either lands in the batch or re-dirties the key for the next flush — no lost update inside `SettingsManager`. `_flush_lock` serialises two flushes, `set_settings_batch` is all-or-nothing inside one transaction, and a short write re-queues the whole batch rather than dropping keys (`core/settings.py:472-483`). Verified by the existing suite: `tests/test_settings_flush.py`, `tests/test_settings_manager.py` → 100 passed with `tests/test_keybind_contracts.py` and `tests/test_api_f1_audit.py`.
- **The hotkey mirror (contract #5) holds today.** `DEFAULT_SETTINGS["hotkeys"]` (`core/settings.py:134-143`) and `DEFAULT_KEYBINDS` (`js/hotkeys.js:4-15`) contain the same 10 action ids with the same combos, and `tests/test_keybind_contracts.py` pins it (passing). The frontend also refuses ghost ids on read (`hotkeys.js:109`) and migrates legacy formats (`hotkeys.js:66-98`).
- **The masked-secret read contract works for the two keys it covers.** `yandex_token` and `oauth_client_secret` are replaced by `""` plus `has_*` flags on every read path (`core/api.py:243-253`, `:1853-1869`), and a blank write of a masked secret does **not** destroy the stored one (`_is_empty_secret_write`, `core/api.py:267-269`) — so the mask **does** survive the round-trip for those two keys. `tests/test_api_f1_audit.py:71-93` pins it.
- **The settings panel does not re-fetch the blob.** Opening the settings view is pure DOM work (`js/settings.js:68-100`); `loadSettings()` (`js/settings.js:1083-1089`) only calls `get_storage_info()`, and `js/pages.js:138` calls it once per settings-page open. The whole settings blob is fetched **once** per app start (`js/main.js:409`) plus one duplicate `get_settings_by_category('hotkeys')` (`js/hotkeys.js:105`). There is **no per-keystroke write amplification**: sliders persist on `change` and only preview on `input` (`js/settings.js:692-710`).
- **`get_all_settings` does not re-read the DB per call.** `DatabaseManager.get_all_settings` (`core/database.py:2117-2132`) is a full table scan, but it is called from exactly one place — `SettingsManager._load_all` at construction (`core/settings.py:317`). Afterwards every read is served from the in-memory cache (`core/api.py:2955-2956` → `get_settings()` → `get_category()`).
- **Shutdown ordering is right.** `core/app.py:557-560` flushes the settings **before** closing the database, and `atexit.register(self.flush)` (`core/settings.py:313`) plus `sync_flush_now()` (`core/settings.py:420-441`) cover the other exit paths.
- **The read-only bridge protection works.** `general.plugins_enabled` is refused by every write path (`core/api.py:256-264`), and the zapret service independently validates `zapret.binary_path` (`services/zapret_service.py:732-738`) and `zapret.custom_args` (`:1110-1130`) at use time — so the unvalidated generic write path cannot be used to launch an arbitrary binary.
- **`auth.browser_cookies` stores a browser *name*, not cookie material** (`services/youtube_service.py:835-856`), so the YouTube session cookies never enter the settings table. `auth.cookies_file_path` is a path, not a secret.
- **`complete_onboarding` validates its input.** Booleans, the theme/mode/preset enums, the audio-device length and the accent colour are all checked before anything is written (`core/api.py:2763-2781`).

### 4. Coverage gaps

- **I did not run the app.** Every measurement comes from a real `DatabaseManager`/`SettingsManager`/`AppApi` on a throwaway SQLite file in `%TEMP%`; the WebView-side behaviour (the `offline-mode` CSS class, the `innerHTML` sink, the `localStorage` mirror) is derived from code reading plus the measured blob contents, not observed in a running window.
- **`ui/web_new_v2/js/settings.js` is 3111 lines and I read the settings-relevant parts, not every line.** The panels I did not trace end-to-end are the appearance/workshop/zapret/efficiency panels; I verified the *write* side of their `saveSetting` calls but not each control's input validation.
- **I did not audit the `android/` subtree** (out of scope by instruction).
- **The XSS reachability of F-WX-03-10 is not fully closed.** I confirmed the WebView loads no remote content (no `<iframe>`, no remote `<script>` in `index.html`) and that no remote-controlled value reaches the hotkey store, but I did not audit every writer of the `settings` table for a path from a provider response to a settings value.
- **The concurrency claims about the writer thread are reasoned from the lock structure and reproduced with a synchronous `flush()`**, not with a stress test running the real `SettingsWriter` thread against a competing writer. A dedicated stress test would be needed to rule out a narrow interleaving.
- **`_emit`'s UI-thread marshalling cost was not measured** — no profiling was done on the WebView2 side; F-WX-03-8's cost claim is derived from the code path (`Control.Invoke` per emit), not from a trace.
- I did not evaluate whether `get_settings()`'s omission of `subscription` is still the intended policy — the code says it is (`core/settings.py:265-271`), but the licence feature has no callers, so the policy is untested in practice.

---

### 5. Architecture improvements (ARCH)

These are **not** defects — they are the structural changes that would remove the defects above.

- **ARCH-1 — One schema, one owner, one transport.** The settings namespace is currently described three times: `core/settings.py::DEFAULT_SETTINGS` (the schema), the category list inside `core/api.py::get_settings` (the transport), and the category strings hard-coded in the JS (`js/settings.js`, `js/player.js`, `js/lyrics.js`, `js/utils.js`). A fourth, informal registry is the set of undeclared categories the frontend invents (`player`, `lyrics`, plus ~12 individual keys). Make `DEFAULT_SETTINGS` the single source, derive the transport list from it (plus one explicit "frontend-only" allow-list and one explicit "never send to JS" exclusion list), and validate `(category, key)` at the bridge boundary. *This single change removes F-WX-03-1, F-WX-03-3 and most of F-WX-03-10.*
- **ARCH-2 — One write path, one entry point.** There are three public bridge write methods (`save_setting`, `update_setting`, `set_setting`) and a public `DatabaseManager.set_setting` bypass, with three different return contracts (`True` / `{"success": True}` / `None`) and two different side-effect behaviours. Collapse them onto one `set_setting(category, key, value)` that validates, applies side effects, checks their result and returns one shape; make the DB-level write private to `SettingsManager`. *Removes F-WX-03-5 and closes the F-WX-03-12 hazard.*
- **ARCH-3 — Classify secrets as a property of the key, not of the category.** `_SECRET_SETTING_KEYS` is a per-category two-entry tuple that must be updated every time a credential is added — which is why `proxy_url` and the licence key slipped through. Model it as `SECRET_SETTINGS: set[tuple[str, str]]` (or a `Secret` wrapper type), apply it in **one** place used by every read *and* the event emit, and make the frontend's "has_* / blank means keep" protocol the only way a secret is ever represented in JS. *Removes F-WX-03-2 and F-WX-03-4.*
- **ARCH-4 — Transport a projection, not the whole tree.** `get_settings()` ships every category, including unbounded per-track state (`lyrics.lyrics_offset_*`), the playback queue and 1000-entry feedback lists — 4 KB in the default case but 254 KB in a realistic one, re-stringified and re-stored in `localStorage` at every start. Give the UI an explicit projection (`get_settings(category)` for the panel that is open, `get_ui_settings()` for the boot sequence) and move per-entity state (lyrics offsets) into its own table. *Removes F-WX-03-7.*
- **ARCH-5 — One cache, or an explicit invalidation contract.** `window.settings` (JS), `localStorage` and `SettingsManager._cache` (Python) are three caches of the same data with no reconciliation. The `setting_changed` event exists for exactly this and is dropped on the floor. Either make the event the reconciliation mechanism (with secrets redacted) or delete the event and accept the drift explicitly; today the app has the cost of the mechanism and none of the benefit.
- **ARCH-6 — Give the settings table a key grammar.** Three key shapes (dotted / bare / category-prefixed) share one namespace, and the loader resolves bare keys by first-match across `DEFAULT_SETTINGS`. Namespace the migration flags, drop the `elif key in stored_all` fallback, and give the table a NOT NULL category with a check that the key starts with `category + "."`.
- **ARCH-7 — Move the per-track and per-session bulk out of the settings store.** `session.last_queue`, `personalization.disliked_tracks` (up to 1000) and the lyrics offsets are entity state stored in a global key/value table; they belong in their own tables with their own queries. This also lets `get_settings()` stay small enough to fetch per panel.
- **ARCH-8 — Return deep copies (or a read-only view) from `SettingsManager.get_category`.** A `.copy()` that leaves nested dicts shared is an implicit mutable-shared-state contract that every caller has to re-derive. Either deep-copy once per category (cached) or expose an immutable mapping and make the mutating callers copy explicitly.
- **ARCH-9 — Make the bridge surface for settings explicit and small.** `get_setting`, `get_settings`, `get_all_settings`, `get_settings_by_category`, `get_personalization`, `save_setting`, `update_setting`, `set_setting` — eight methods for one store, with different masking, validation and return contracts. One `get` and one `set` (plus a category-scoped variant) would make the contract reviewable in one place.
