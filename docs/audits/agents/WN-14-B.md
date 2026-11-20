## AREA WN-14 — Settings manager & hotkey table — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `core/settings.py` | 1–589 (full) |
| `ui/web_new_v2/js/hotkeys.js` | 1–256 (full) |
| `core/api.py` | 230–279, 1850–1929, 2900–2989, 4120–4174 (settings/secret/offline surface) |
| `core/database.py` | 155–229, 2020–2119, 2455–2486 (settings table + connection lifecycle) |
| `core/app.py` | 236–265, 540–584 (offline gate, cleanup order) |
| `core/session.py` | 1–96 (full) |
| `core/offline.py` | 1–77 (full) |
| `core/api.py` (prefetch) | 3640–3669 |
| `ui/web_new_v2/js/settings.js` | 25–54, 372–391, 1020–1089, 1110–1239 |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (full) |
| `ui/web_new_v2/js/player.js` | 255–324 |
| `ui/web_new_v2/js/lyrics.js` | 112–181 |
| `ui/web_new_v2/js/utils.js` | 595–619, 1296–1320 |
| `ui/web_new_v2/js/events.js` | 305–334 |
| `ui/web_new_v2/js/main.js` | 400–439 |
| `tests/test_settings_manager.py` | 1–538 (full) |
| `tests/test_settings_flush.py` | 1–229 (full) |
| `tests/test_keybind_contracts.py` | 1–204 (full) |
| `tests/test_db_core_fixes_f2.py` | grep only (settings-related sections) |
| `services/artist_identity.py` | 1–30 |
| `services/lastfm_service.py` | 99–145 (grep + read of the API-key read) |
| `main.py` | 505–584 (watchdog / shutdown ordering) |
| `docs/audits/WIN_AUDIT_CONTEXT.md`, `docs/audits/WIN_AUDIT_AREAS.md` | full |

**Callees traced into other areas**

- `core/api.py` — WN-08 (settings/onboarding/offline bridge). `AppApi.save_setting`, `AppApi.set_setting`, `AppApi.get_settings`, `AppApi.get_all_settings`, `AppApi.get_settings_by_category`, `AppApi.set_offline_mode`, `AppApi.get_offline_mode`, `AppApi.complete_onboarding`. Called from my area's perspective; defects found *in* api.py are attributed to WN-08 below and flagged explicitly.
- `core/database.py` — WN-12 (`set_setting`, `set_settings_batch`, `get_all_settings`, `conn` lifecycle).
- `ui/web_new_v2/js/settings.js`, `js/player.js`, `js/lyrics.js`, `js/utils.js`, `js/feature-controls.js` — WN-30 / WN-29 / WN-32.
- `core/session.py` — WN-02 (`SessionManager` writes through `SettingsManager`).
- `core/offline.py` — WN-15.

**Commands run**

- `pytest tests/test_keybind_contracts.py tests/test_settings_manager.py tests/test_settings_flush.py -q` → **69 passed** (0.77 s). The hotkey mirror currently has zero drift.
- Two read-only probe scripts under `%TEMP%/opencode/audit_reports/` (`_probe_wn14.py`, `_probe_wn14b.py`) that import `core.settings` with an in-memory DB double. No repo file was modified; `~/.nedotify/` was never touched.

---

### 2. Findings

#### F-WN-14-1  [P1] — `get_settings()` omits the `network` category: the persisted offline mode never reaches the frontend

- **File:** `core/api.py:2929` (the hardcoded category list), `core/settings.py:52-55` (`DEFAULT_SETTINGS["network"]`), `core/offline.py:10-14`, `ui/web_new_v2/js/feature-controls.js:112`, `ui/web_new_v2/js/utils.js:608`, `ui/web_new_v2/js/player.js:1440`, `ui/web_new_v2/js/player.js:1524`
- **Confirmed:** yes
- **Description:** The settings schema lives in two independent lists. `DEFAULT_SETTINGS` (core/settings.py) declares 21 categories including `network`; `AppApi.get_settings()` iterates its own hardcoded list of 22 categories which contains `appearance`, `player`, `lyrics`, `system` (none of which are in `DEFAULT_SETTINGS`) and **omits `network` and `subscription`**. `get_all_settings()` is a direct alias of `get_settings()`. The frontend's only source of `window.settings` is `get_settings()` (`js/main.js:409`, `js/onboarding.js:63`), so `window.settings.network.offline_mode` is `undefined` at every start. `initFeatureControls()` then calls `applyOfflineState({enabled: window.settings?.network?.offline_mode === true})` → `enabled === false`, which *writes* `window.settings.network.offline_mode = false`. The backend's own `is_offline(self.settings)` reads `network.offline_mode` from the manager and is correct — only the frontend mirror is stale. `AppApi.get_offline_mode()` (core/api.py:4129) returns the correct persisted state but **has zero JS callers** (grep over `ui/**` finds only `set_offline_mode`), and `offline_mode_changed` is emitted only from `set_offline_mode` (core/api.py:4160), i.e. only in response to a UI toggle — never at startup.
- **Cause:** Two independent enumerations of the same schema (a Python dict and a JS-side list literal) with no shared source and no test that compares them. `tests/test_keybind_contracts.py` compares only the *hotkey* tables; nothing compares the category lists.
- **Trigger conditions:** The user enables offline mode in the UI (persisted as `network.offline_mode = True`), then restarts the app. Nothing pushes the state back to the frontend.
- **User impact:** Offline mode is half-dead after every restart. The frontend believes it is online: `js/utils.js:608 offlineImageUrl()` returns remote cover URLs (so the WebView keeps hitting the internet for covers in offline mode), `js/utils.js:526` still emits `data-cover-url`, `js/player.js:1440` calls `prefetch_track` — and `AppApi.prefetch_track` (core/api.py:3640-3669) has **no** `is_offline` guard, unlike 30 other call sites — so the resolver attempts network resolution while offline; `js/player.js:1524` fires the "infinite radio" flow request that the backend refuses (core/api.py:2085/2269 guards), producing a visible error instead of the intended silent offline behaviour.
- **Evidence:**
  ```python
  # core/api.py:2929
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                'session', 'zapret']
  ```
  ```python
  # core/settings.py:52-55 — the category that never reaches JS
  "network": {
      "offline_mode": False,
  },
  ```
  ```javascript
  // ui/web_new_v2/js/feature-controls.js:112
  applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  ```
- **Reproduction / verification:**
  1. Probe (executed): `API_CATS not in DEFAULT_SETTINGS: ['appearance','player','lyrics','system']` / `DEFAULT cats not returned by get_settings: ['network','subscription']`.
  2. Grep `ui/**` for `get_offline_mode` → 0 hits; grep for `get_settings_by_category` → only `js/hotkeys.js:105`.
  3. Manual: set `network.offline_mode = True` in the DB, start the app, evaluate `window.settings.network` in DevTools → `undefined`/`{offline_mode:false}`.
- **Suggested fix:** Make `DEFAULT_SETTINGS` the single source of the category list — add `SettingsManager.get_all()` / `iter_categories()` and have `AppApi.get_settings()` iterate it instead of a hardcoded literal; and/or have the frontend call the existing `get_offline_mode()` at startup and feed it into `applyOfflineState()`.
- **Fix side effects:** `get_settings()` would start returning `subscription` (currently excluded) — that category is documented as unused (core/settings.py:265-271) and its `key` field is a licence key; it must be masked or stay excluded deliberately. Returning `network` also means the offline flag is now in the `nedotify_cached_settings` localStorage blob.
- **Discovered by:** B
- **Owner note:** the literal list lives in `core/api.py` (WN-08); the *root cause* — the schema being declared twice — is WN-14. Not double-reported: WN-08 should not file the same root cause again.

#### F-WN-14-2  [P1] — A failed settings write is never retried automatically: the writer thread does not re-arm after a failure

- **File:** `core/settings.py:508-530` (`_wake_writer` / `_writer_loop`), `core/settings.py:443-483` (`flush`)
- **Confirmed:** yes
- **Description:** The write-behind queue is the `_dirty` set. On a failed batch, `flush()` re-adds the pending keys to `_dirty` and logs an error — but it never re-arms `self._writer_wake`. The writer loop is `wait() → clear() → sleep(0.5) → flush()`; after the flush it loops back to `wait()`, and because the Event was cleared *before* the sleep, the loop blocks until the next `set()` sets it again. So a transient write failure parks the key in `_dirty` indefinitely: nothing retries it. The bridge has already answered `True` to the JavaScript caller (`AppApi.save_setting` returns `True` right after `settings.set()`, which only touches the in-memory cache), so the UI shows success.
- **Cause:** The retry contract documented in `flush()`'s docstring ("Keys whose write fails stay pending so the next flush retries them") is implemented, but the *automatic* flush source (the Event) is only re-armed by `set()`. There is no self-retry.
- **Trigger conditions:** Any transient SQLite failure on the settings batch write — `SQLITE_BUSY` (the DB is shared with the proxy thread and the downloader), a locked file during a backup, a full disk, or the `sqlite3.ProgrammingError` "Cannot operate on a closed database" that is possible if a `set()` lands after `db.close()` (see F-WN-14-8).
- **User impact:** The user's change (volume, quality, a hotkey, a theme) is silently not persisted. The only trace is one line in `~/.nedotify/logs/app.log`. If the app is killed before the next unrelated `set()` (or an explicit flush at exit), the change is lost for good.
- **Evidence:**
  ```python
  # core/settings.py:520-530
  def _writer_loop(self) -> None:
      while True:
          self._writer_wake.wait()
          self._writer_wake.clear()
          time.sleep(self.FLUSH_INTERVAL_SECONDS)
          try:
              self.flush()
          except Exception as e:
              logger.error(f"Settings writer thread error: {e}")
  ```
  ```python
  # core/settings.py:472-483 — the pending keys are restored, the Event is NOT set
  if written < len(payload):
      with self._lock:
          self._dirty.update(pending)
      if error is not None:
          logger.error(f"Settings flush failed, {len(pending)} keys still pending: {error}")
  ```
- **Reproduction / verification:** executed probe `_probe_wn14b.py` (in-memory DB double whose `set_settings_batch` raises "database is locked"):
  ```
  after 1s with a permanently failing DB: attempts=1 rows={} dirty={('audio','volume')}
  after DB recovery + 1s, NO new set(): attempts=1 rows={} dirty={('audio','volume')}   <-- no retry
  after an unrelated set():            attempts=2 rows={'theme.name':'Light','audio.volume':42}
  ```
  The DB was healthy for a full second and the writer made **zero** further attempts; the key was only written because an *unrelated* `set()` re-armed the Event. `tests/test_settings_flush.py:117 test_failed_write_is_retried_and_succeeds` retries through an explicit `sync_flush_now()`, so it never exercises the automatic path.
- **Suggested fix:** Re-arm the wake event when a flush leaves keys pending (e.g. `self._writer_wake.set()` inside the failure branch, or a bounded back-off inside `_writer_loop`), and/or make `flush()` return a status that the writer loop uses to schedule the next attempt.
- **Fix side effects:** A permanently broken DB would then be retried in a hot loop — needs a back-off and a "give up after N attempts / persist to a fallback file" policy, otherwise the log grows without bound.
- **Discovered by:** B

#### F-WN-14-3  [P2] — `SettingsManager.set()`'s dotted-key overload corrupts the store when the value is `None`

- **File:** `core/settings.py:401-418`
- **Confirmed:** yes
- **Description:** `set()` accepts `set("cat", "key", value)` and `set("cat.key", value)`. The dotted branch is guarded by `"." in category and value is None and key is not None`. In the call `set("session.last_track_id", None)` the positional binding is `key=None, value=None`, so the guard is False and the call falls through to the three-argument path: a **new cache category literally named `"session.last_track_id"`** is created and the key `None` is stored in it (`self._cache[category][key] = value` with `key is None`). On the next flush that junk is persisted as the settings row `"session.last_track_id.None"`. The documented dotted form therefore cannot clear a value — and it corrupts the store instead. Second-order damage: once the junk category exists, `_is_known_category("session.last_track_id")` returns True (core/settings.py:344-349), so the dotted `get()` overload stops working for that key and `get("session.last_track_id")` returns `None` even when the real value exists.
- **Cause:** The overload uses `None` as a sentinel for "not supplied", but `None` is also a legitimate value to store. There is no distinct "no value" marker.
- **Trigger conditions:** Any caller that clears a setting through the dotted form, e.g. `settings.set("session.last_track_id", None)`. The store is polluted for the lifetime of the profile (the junk row is never garbage-collected — `_load_all` preserves unknown keys by design, core/settings.py:336-342).
- **User impact:** A cleared setting stays set (the dotted read returns `None`/the old value), and the settings table accumulates malformed rows. No exception is raised, so the failure is silent.
- **Evidence:**
  ```python
  # core/settings.py:408-411
  if "." in category and value is None and key is not None:
      cat, k = category.split(".", 1)
      val = key
      return self.set(cat, k, val)
  # ... else: self._cache[category][key] = value  with category="session.last_track_id", key=None
  ```
- **Reproduction / verification:** executed probe `_probe_wn14.py`:
  ```
  [junk] _cache keys: [..., 'session.last_track_id']
  [junk] session.last_track_id value: None
  [junk] persisted rows: ['session.last_track_id.None']
  ```
  The repository already documents this as a live bug: `tests/test_settings_manager.py:299-320` — *"Pinned BUG core/settings.py:374 … the dotted form degenerated into a category named 'session.last_track_id'"* — the test pins the defect instead of fixing it, so it stays.
- **Suggested fix:** Use an explicit sentinel (`_UNSET`) for the overload instead of `None`, and reject/ignore a `None` key in the three-argument path; alternatively normalise the dotted form before the branch is taken.
- **Fix side effects:** `set("cat.key", None)` currently stores `None`; after the fix it must actually clear the value. Any caller relying on the current (broken) behaviour would change — none exists today.
- **Discovered by:** B

#### F-WN-14-4  [P2] — `AppApi.set_setting(category, key, None)` writes the value under the WRONG category (`zapret.<category>` = the key name) — **owner: WN-08**

- **File:** `core/api.py:1871-1900`; root-overload in `core/settings.py:401-418`
- **Confirmed:** yes
- **Description:** `AppApi.set_setting` uses the same `value is None and key is not None` sentinel trick as `SettingsManager.set`, so a legitimate three-argument call with a `None` value is misread as the two-argument form: `set_setting("audio", "volume", None)` takes the `value is None and key is not None` branch, treats `"audio"` as a bare key, and — because it contains no `"."` — falls back to `cat="zapret", k="audio"`, `val="volume"`. The settings table then receives the row `zapret.audio = "volume"` (a string, in the wrong category) and `audio.volume` is left untouched. `False`/`0`/`""` values work correctly, so the defect is invisible except for `None`.
- **Cause:** `None` doubles as "argument absent" and "clear this value" across the bridge boundary.
- **Trigger conditions:** Any three-argument `set_setting` call with a `None` value from JavaScript. `AppApi.set_setting` has no JS caller today (grep over `ui/**` finds only `save_setting`), so the practical exposure is via future/other bridge callers and via Python code that calls `AppApi.set_setting` directly (e.g. `tests/test_api_f1_audit.py:88` calls `api.set_setting("auth", "yandex_token", "fresh-token")`).
- **User impact:** Clearing a setting through the bridge silently writes garbage into an unrelated category instead, and the intended key keeps its old value.
- **Evidence:**
  ```python
  # core/api.py:1874-1888
  if value is None and key is not None:
      full_key = str(section)
      val = key
      if "." in full_key:
          cat, k = full_key.split(".", 1)
      else:
          cat, k = "zapret", full_key      # <-- bare key lands in the zapret category
      ...
      self._core.settings.set(cat, k, val)
  ```
- **Reproduction / verification:** executed probe `_probe_wn14.py` replays the exact branch:
  ```
  emulate set_setting('audio','volume',None)  -> ('zapret', 'audio', 'volume')
  emulate set_setting('audio','volume',False) -> ('audio', 'volume', False)
  emulate set_setting('zapret.auto_start',True) -> ('zapret', 'auto_start', True)
  ```
  A live reproduction: `api.set_setting("audio", "volume", None)` → `db` row `zapret.audio == "volume"`.
- **Suggested fix:** Distinguish "argument absent" from "value is None" — e.g. use `*args`/`**kwargs` or a dedicated sentinel, and reject `None` for the three-argument form with an explicit error instead of silently reinterpreting it.
- **Fix side effects:** `set_setting("zapret.auto_start", True)` (the two-argument form) must keep working; the `zapret` fallback for bare keys is deliberate and must be preserved or replaced by an explicit error.
- **Discovered by:** B
- **Owner note:** the defective code is in `core/api.py` → **WN-08**. Listed here because the root cause is the shared `None`-as-sentinel overload documented in F-WN-14-3; the fix should be made once, in the shared overload.

#### F-WN-14-5  [P2] — The settings store keeps secrets as ordinary rows and the masking contract is one-sided; the frontend mirrors every value into plaintext localStorage

- **File:** `core/settings.py:242-250` (the `auth` category), `core/api.py:239-269` (`_SECRET_SETTING_KEYS`, `_mask_secrets`, `_is_empty_secret_write`), `ui/web_new_v2/js/settings.js:1033-1053` (the localStorage mirror), `ui/web_new_v2/js/settings.js:379` (the token input), `services/lastfm_service.py:143`
- **Confirmed:** yes
- **Description:** `DEFAULT_SETTINGS["auth"]` declares `yandex_token`, `oauth_client_id`, `oauth_client_secret`, `proxy_url`, `cookies_file_path` as ordinary settings keys in the same plaintext SQLite table as everything else — there is no secret/non-secret separation in the store and no encryption. The *bridge* does make an effort: `_mask_secrets()` blanks `yandex_token` and `oauth_client_secret` on read and adds `has_*` flags, and `_is_empty_secret_write()` prevents a masked read echoed back from wiping the stored token. Two consequences:
  1. **The masking is one-sided.** `auth.proxy_url` is *not* in `_SECRET_SETTING_KEYS`, so a proxy URL of the form `http://user:password@host:port` is returned verbatim to the WebView by `get_settings()` / `get_settings_by_category('auth')` and is written into the input field at `js/settings.js:963-964`. `auth.lastfm_api_key` — a third API credential read by `services/lastfm_service.py:143` — is not even declared in `DEFAULT_SETTINGS`, so it is an undeclared, unmasked credential in the same table.
  2. **The frontend mirror defeats the masking.** `js/settings.js:1040` writes *every* setting value to localStorage unconditionally: `localStorage.setItem('nedotify_${category}_${key}', JSON.stringify(value))`. When the user types a Yandex token (`js/settings.js:379` → `saveSetting('yandex_token', …, 'auth')`), the secret is written in plaintext into the WebView2 profile at `~/.nedotify/webview2_data` — the exact place the backend's masking was meant to keep it out of.
- **Cause:** The threat model is implemented in the *bridge read path* instead of in the *store*, and the frontend keeps its own untyped mirror of every setting with no secret awareness.
- **Trigger conditions:** Any user who enters a Yandex token, an OAuth client secret, or a credential-bearing proxy URL in the Settings UI.
- **User impact:** Long-lived OAuth/API credentials sit in plaintext in two places (the SQLite table and the WebView2 localStorage) and are readable by anything with access to the user profile. The proxy password additionally crosses the bridge unmasked, unlike the neighbouring tokens — an inconsistent policy that a reviewer cannot reason about.
- **Evidence:**
  ```python
  # core/api.py:239-241 — only two of the five auth secrets are treated as secrets
  _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  ```
  ```javascript
  // ui/web_new_v2/js/settings.js:1039-1041 — every value, secrets included, hits localStorage
  try {
      localStorage.setItem(`nedotify_${category}_${key}`, JSON.stringify(value));
  } catch (e) {}
  ```
- **Reproduction / verification:** 1. Type a token in the Settings UI → `DevTools → Application → Local Storage → nedotify_auth_yandex_token` contains the cleartext token. 2. `AppApi.get_settings_by_category('auth')` returns `proxy_url` unchanged. 3. Grep `services/` for `settings.get('auth'` → `lastfm_service.py:143` reads `auth.lastfm_api_key`, a key absent from `DEFAULT_SETTINGS["auth"]`.
- **Suggested fix:** Move credentials out of the generic settings table into a dedicated secret store (Windows Credential Manager / DPAPI) with its own accessor; extend `_SECRET_SETTING_KEYS` to cover `proxy_url` and `lastfm_api_key`; and make the frontend's localStorage mirror skip secret keys (it needs a flag to know which are secret — the backend's `has_*` flags are the natural carrier).
- **Fix side effects:** `core/proxy.py:1004` reads `settings.get('auth','yandex_token','')` at request time — a secret store must stay readable from the proxy thread; the localStorage change breaks the "offline first paint" fallback for the masked keys (the UI already handles this via the `has_*` placeholders).
- **Discovered by:** B
- **Owner note:** the localStorage mirror is `ui/web_new_v2/js/settings.js` (WN-30) and the masking helpers are `core/api.py` (WN-08). The *store-level* absence of secret separation is WN-14's.

#### F-WN-14-6  [P2] — `get()` and `get_category()` hand out live mutable objects from the cache

- **File:** `core/settings.py:367-372` (`get`), `core/settings.py:532-535` (`get_category`), `core/api.py:2964-2965` (`get_personalization`)
- **Confirmed:** yes
- **Description:** `get()` returns the cache object itself, not a copy: `val = self._cache[category][key]`. For every list/dict-valued setting (`personalization.blocked_artists`, `personalization.artist_aliases`, `personalization.artist_bindings`, `equalizer.bands`, `interface.tabs`, `interface.background`, `storage.scan_folders`, `session.last_queue`) the caller receives a live reference into the manager's state. Mutating it in place changes the cache **without** marking the key dirty, so the change is never written to SQLite and silently disappears on restart. `get_category()` returns `self._cache.get(category, …).copy()` — a **shallow** copy, so the nested containers inside it are still the live cache objects.
- **Cause:** The cache is exposed directly; the copy at the category level is one level too shallow, and `get()` copies nothing.
- **Trigger conditions:** Any Python consumer that mutates a value it obtained from `settings.get(...)` or `settings.get_category(...)`. `services/artist_identity.py:13-18` currently copies defensively (`aliases = dict(DEFAULT_ALIASES)` + `aliases.update(...)`), so no live corruption exists today — but the contract is not documented and not enforced.
- **User impact:** Silent loss of a settings change (the value is live in memory and visible in the UI, but the DB row is never updated). A future caller that appends to `settings.get('personalization','blocked_artists')` — the exact pattern used by `services/recommendation_service.py:152-153` — would corrupt the store without a trace.
- **Evidence:**
  ```python
  # core/settings.py:368-372
  with self._lock:
      if category in self._cache and key in self._cache[category]:
          val = self._cache[category][key]      # <-- the live object
  ...
  # core/settings.py:534-535
  with self._lock:
      return self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()   # shallow
  ```
- **Reproduction / verification:** executed probe `_probe_wn14.py`:
  ```
  [shallow] cache mutated via get_category copy: {'x': {'a': 1}}
  [shallow] get('personalization','artist_aliases') is the cache object: True
  [mutable] cache now: ['injected']
  [mutable] dirty (mutation not tracked): set()
  ```
  i.e. `sm.get("personalization","blocked_artists").append("injected")` changed the cache while `_dirty` stayed empty.
- **Suggested fix:** Return `copy.deepcopy` from `get()` for mutable values (or freeze them), and make `get_category()` deep-copy as well; alternatively expose an explicit `update(key, mutator)` API that marks the key dirty.
- **Fix side effects:** Deep-copying on every `get()` adds allocation on the hot read path (`is_offline()`, `settings.get("audio","volume")` are called per frame / per request in places). A copy-on-write or "only copy mutable types" compromise avoids most of that.
- **Discovered by:** B

#### F-WN-14-7  [P3] — The hotkey table has three encodings and two persistence stores; only a text-scanning test keeps the two tables in sync

- **File:** `core/settings.py:119-144` (`DEFAULT_SETTINGS["hotkeys"]`), `ui/web_new_v2/js/hotkeys.js:4-15` (`DEFAULT_KEYBINDS`), `ui/web_new_v2/js/hotkeys.js:29-33` + `61-65` (the localStorage mirror), `ui/web_new_v2/js/hotkeys.js:72-78` (`LEGACY_DEFAULT_MIGRATION`), `tests/test_keybind_contracts.py:36-102`
- **Confirmed:** yes
- **Description:** The hotkey contract named in `WIN_AUDIT_CONTEXT.md` #5 is real but is implemented as duplicated literals: **10 action ids** are written out three times — twice as the default table (Python `DEFAULT_SETTINGS["hotkeys"]`, JS `DEFAULT_KEYBINDS`) and once more inside `LEGACY_DEFAULT_MIGRATION`, which hard-codes *older* default spellings (`'Ctrl+KeyK': 'KeyK'`, `'Ctrl+M': 'KeyM'`, …) that the frontend rewrites on every start. On top of that there are **two persistence stores** for the same logical setting: the `hotkeys` category in SQLite and the `nedotify_keybinds` localStorage blob. The load order is localStorage first, then the backend overwrites it (hotkeys.js:104-120) with no reconciliation and no version stamp, so the two stores can disagree and the DB always wins on the next start. The only synchronisation mechanism is `tests/test_keybind_contracts.py`, which parses both files with a regex and an AST walk; it pins the id sets and the default values, but it does **not** cover `LEGACY_DEFAULT_MIGRATION`, does not cover the localStorage mirror, and cannot cover a *runtime* drift (a stored value in a user's DB that no longer matches any frontend default).
- **Cause:** The frontend needs the defaults before the bridge answers (it renders the keybind list immediately) and the backend needs them for the settings API, so both sides declare them; nothing generates one from the other.
- **Trigger conditions:** Any change to the default table — adding a hotkey, changing `Space` to `Ctrl+Space`, renaming an action id.
- **User impact:** Drift is silent by construction (the frontend filters unknown ids at `hotkeys.js:109` and drops the ones it does not recognise). The user sees a hotkey that does nothing, or a Settings list showing a raw `KeyboardEvent.code`. The `LEGACY_DEFAULT_MIGRATION` map is the sharpest edge: it rewrites a user's *legitimate* binding if it happens to equal a legacy default (e.g. a user who deliberately bound `Ctrl+M` gets it silently reassigned to `KeyM` on every start).
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/hotkeys.js:72-78 — a third, ungoverned encoding of the defaults
  const LEGACY_DEFAULT_MIGRATION = {
      'Ctrl+Right': 'Ctrl+ArrowRight', 'Ctrl+Left': 'Ctrl+ArrowLeft',
      'Ctrl+Up': 'Ctrl+ArrowUp', 'Ctrl+Down': 'Ctrl+ArrowDown',
      'Ctrl+KeyM': 'KeyM', 'Ctrl+KeyK': 'KeyK',
      'Ctrl+M': 'KeyM', 'Ctrl+L': 'KeyK', 'Ctrl+F': 'Slash',
      'Ctrl+KeyO': null, 'Ctrl+O': null
  };
  ```
  ```python
  # core/settings.py:119-144 — the same 10 ids, declared again
  "hotkeys": { "play_pause": "Space", "next_track": "Ctrl+ArrowRight", ... "like": "KeyK", "search": "Slash" },
  ```
- **Reproduction / verification:** `pytest tests/test_keybind_contracts.py -q` → passes; the two tables currently have **0 drift** (same 10 ids, same 10 values). The duplication cost is therefore latent, not active: 10 ids × 3 encodings + 2 stores, guarded by one regex/AST test that covers only 2 of the 3 encodings. To see the failure mode, change `DEFAULT_KEYBINDS[0].defaultKey` to `'Ctrl+Space'` → `test_backend_values_match_frontend_defaults` fails (caught); change only `LEGACY_DEFAULT_MIGRATION` → no test fails (not caught).
- **Suggested fix:** Declare the table once (e.g. a JSON file that both sides load, or a Python-side table that is generated into a JS module at build time) and make the legacy-migration map a *versioned* list keyed by the schema version it upgrades from. Drop the localStorage mirror or version it alongside the table.
- **Fix side effects:** The frontend loads before the bridge answers, so the defaults must be available synchronously — a JSON/ESM import satisfies that, a bridge round-trip does not.
- **Discovered by:** B

#### F-WN-14-8  [P3] — `set()` accepts any category and any key: the settings table is used as a general-purpose key/value store with unbounded row growth

- **File:** `core/settings.py:413-417` (`set`), `core/settings.py:315-342` (`_load_all` preserves unknown keys), `ui/web_new_v2/js/lyrics.js:125` and `:177`, `ui/web_new_v2/js/utils.js:1309`, `ui/web_new_v2/js/player.js:289`, `core/api.py:2964-2965`
- **Confirmed:** yes
- **Description:** `set()` performs no category or key validation: an unknown category is created on the fly and any key name is accepted. The frontend uses this as a generic store, which produces schema-less rows that accumulate in the same table as the schema:
  - `js/lyrics.js:125/177` → `save_setting('lyrics_offset_' + (source_id || id || title), ms, 'lyrics')` → **one settings row and one `_cache` entry per track** whose lyrics offset the user ever touched. `trackKey` falls back to `track.title`, so the row key is arbitrary user text.
  - `js/utils.js:1309` → `save_setting('pinned_track', track, 'personalization')` → the whole track dict is stored as a settings row and is shipped back to the frontend on every `get_settings()` call (the `personalization` category is in the api list).
  - `js/player.js:289` → `save_setting('queue_autopilot', isFlowEnabled, 'player')` → the `player` category is **not** in `DEFAULT_SETTINGS`; it exists only because the frontend created it. The schema declares `audio.queue_autopilot` and `audio.flow_enabled` (core/settings.py:73-74) — two parallel keys for one setting, and the alias machinery in `get()` (core/settings.py:373-382) that was supposed to bridge them is **dead code** for the `audio` category, because `DEFAULT_SETTINGS["audio"]` declares both halves of each alias pair, so the cache branch always answers first. `tests/test_settings_manager.py:186-196` documents this ("the alias does not fire when the key exists in the defaults").
  - `_load_all` (core/settings.py:336-342) deliberately preserves unknown dotted keys, so nothing ever garbage-collects these rows.
- **Cause:** There is no distinction in the store between "a schema key" and "a user-scoped scratch value"; the frontend uses the settings table as a general KV store because nothing else was offered.
- **Trigger conditions:** Ordinary use — every lyrics-offset adjustment on a new track adds a row; the pinned track adds another.
- **User impact:** The `settings` table and the in-memory `_cache` grow monotonically with per-track rows (one per adjusted track; thousands over a long-running profile), each one also re-read on every startup by `_load_all`'s `SELECT key, value FROM settings`. The `player` category split means the queue-autopilot toggle is persisted under a key the Python side never reads (the feature is frontend-only today, but the duplicated key is a trap for the next reader).
- **Evidence:**
  ```python
  # core/settings.py:413-417
  with self._lock:
      if category not in self._cache:
          self._cache[category] = {}
      self._cache[category][key] = value
      self._dirty.add((category, key))
  ```
  ```javascript
  // ui/web_new_v2/js/lyrics.js:177
  window.pywebview.api.save_setting(`lyrics_offset_${trackKey}`, currentOffsetMs, 'lyrics');
  ```
- **Reproduction / verification:** 1. Adjust the lyrics offset on 5 different tracks → `SELECT key FROM settings WHERE key LIKE 'lyrics.lyrics_offset_%'` returns 5 rows and `_cache['lyrics']` grows with them. 2. Grep `core/` for `queue_autopilot` → only `core/settings.py`; no Python consumer exists, confirming the `player` split is dead weight.
- **Suggested fix:** Introduce an explicit namespace for user-scoped values (e.g. `user.lyrics_offset.<trackKey>`) with a documented retention/eviction policy, or give the frontend a purpose-built store. Validate category and key against the schema in `set()` and reject unknown ones unless they are in an allowed namespace.
- **Fix side effects:** Rejecting unknown keys would break the "settings.json written by a newer build stays readable by an older one" property that `_load_all` explicitly preserves (core/settings.py:336-342, `tests/test_settings_manager.py:104-111`). The namespace must therefore allow unknown *keys* while still constraining *categories*.
- **Discovered by:** B

#### F-WN-14-9  [P3] — `get_system_region()` runs at import time and freezes a process-lifetime value into `DEFAULT_SETTINGS`

- **File:** `core/settings.py:24-49`, `core/settings.py:62`
- **Confirmed:** yes
- **Description:** `DEFAULT_SETTINGS["general"]["region"]` is initialised by calling `get_system_region()` at **module import time**. The function calls the Win32 API `GetUserDefaultGeoName` through `ctypes` and falls back to `locale.getdefaultlocale()` and finally to the hardcoded `"US"`. Because the call happens at import, (a) importing `core.settings` — which `core/app.py`, `core/api.py`, `core/session.py` and every service module do — performs a Win32 syscall and, on failure, a deprecated locale call; (b) the detected region is frozen for the lifetime of the process and is never re-detected, so `reset_category("general")` restores the *import-time* region rather than the currently detected one; (c) the fallback chain silently produces `"US"` for a non-US user if the geo call fails, and `locale.getdefaultlocale()` is deprecated since Python 3.11 and slated for removal — when it goes, the fallback degrades to `"US"` for everyone.
- **Cause:** A process-locale probe is evaluated eagerly inside a module-level literal instead of lazily at the point of use.
- **Trigger conditions:** Always at import. The `"US"` fallback triggers when `GetUserDefaultGeoName` fails (e.g. a restricted/locale-less profile) or once `locale.getdefaultlocale()` is removed.
- **User impact:** The Settings region dropdown (`js/settings.js:885-886` reads `settings.general.region`) is pre-filled with a value that may be wrong, and "reset to defaults" restores a stale region. No provider currently consumes `general.region` (grep over `services/` and `core/` finds only `core/settings.py:62` and the JS dropdown), so the practical damage today is limited to the dropdown.
- **Evidence:**
  ```python
  # core/settings.py:62 — evaluated at import
  "region": get_system_region(),
  ```
  ```python
  # core/settings.py:39-49
  try:
      import locale
      loc = locale.getdefaultlocale()[0]
      ...
  except Exception:
      pass
  return "US"
  ```
- **Reproduction / verification:** executed probe `_probe_wn14.py` on this machine (Python 3.14.7): `locale.getdefaultlocale exists: True`, `locale.getdefaultlocale(): ('ru_RU','cp1251')`, `get_system_region() -> RU`, `DEFAULT general.region -> RU`. The failure branch is reachable by calling `get_system_region()` on a non-Windows host (`ctypes.windll` raises `AttributeError`, swallowed) — the function is therefore safe but silently wrong-by-default.
- **Suggested fix:** Make the region a lazily computed default (`get()` falls back to `get_system_region()` when the key is unset) and re-detect it on `reset_category("general")`; replace `locale.getdefaultlocale()` with `locale.getlocale()` / `GetUserGeoID` / the `LANG`/`LC_ALL` environment variables.
- **Fix side effects:** `DEFAULT_SETTINGS` becomes non-deterministic at read time, which the existing tests (`tests/test_settings_manager.py:73-77` compares the whole default tree) rely on being stable — the lazy version must keep returning a deterministic value within a process.
- **Discovered by:** B

#### F-WN-14-10  [P3] — The store carries no type information, so `get()` coerces `"true"`/`"false"` type-blindly and corrupts string settings

- **File:** `core/settings.py:394-399` (the coercion), `core/settings.py:52-287` (`DEFAULT_SETTINGS` — values only, no types), `tests/test_settings_manager.py:261-276` (the pinned footgun)
- **Confirmed:** yes
- **Description:** `DEFAULT_SETTINGS` holds default *values* but no declared *types*, so `get()` cannot know whether a key is a boolean or a string. It therefore applies a blanket coercion: any string value equal to `"true"`/`"false"` (case-insensitive) is returned as a bool. This is correct for `audio.autoplay` and wrong for every string field — `auth.proxy_url == "false"` comes back as the boolean `False`, `auth.cookies_file_path == "true"` comes back as `True`. The same missing-type gap means `set()` accepts any type for any key: `set("auth","proxy_url", 123)` stores an int, and `set("audio","autoplay","yes")` stores a truthy string that `get()` returns as the string `"yes"` (the coercion only handles `"true"`/`"false"`).
- **Cause:** The schema is value-only. The coercion is a heuristic standing in for a type system.
- **Trigger conditions:** A user types the literal word "true" or "false" into a free-text settings field (proxy URL, cookie path, file name), or a bridge caller passes a non-string to a string key.
- **User impact:** A string setting silently changes type in the consumer: `services/spotify_service.py:107` does `normalize_proxy_url(self.settings.get("auth","proxy_url",""))` → a `False` instead of `""` reaches the normaliser. Type confusion in a value store is a class of bug that no test in the suite can currently catch, because there is no type to assert against.
- **Evidence:**
  ```python
  # core/settings.py:394-399
  if isinstance(val, str):
      if val.lower() == "true":
          return True
      elif val.lower() == "false":
          return False
  return val
  ```
  ```python
  # tests/test_settings_manager.py:261-276 — the repo already pins this as a footgun
  """Pinned footgun: the coercion is type-blind … Fixing it means knowing the
  declared type of the key, which DEFAULT_SETTINGS does not carry."""
  ```
- **Reproduction / verification:** executed probe `_probe_wn14.py` / `tests/test_settings_manager.py::test_a_literal_true_string_in_the_auth_category_comes_back_as_a_bool` → `sm.get("auth","yandex_token") is True` for the stored string `"true"`.
- **Suggested fix:** Give the schema types (`"autoplay": bool`, `"proxy_url": str`, …) and coerce/validate per key in `get()`/`set()` instead of applying a global heuristic.
- **Fix side effects:** A typed schema would have to classify every existing key, including the ~30 keys the frontend writes that are not in `DEFAULT_SETTINGS` (`lyrics_offset_*`, `pinned_track`, `player.queue_autopilot`, `visualizer_style`, `mode` in the `equalizer` category, `queue_autopilot`). A "free-form" escape hatch is needed for those, or the schema must be extended to cover them.
- **Discovered by:** B

#### F-WN-14-11  [P3] — The writer thread has no lifecycle: no stop, no join, no `SettingsManager.close()`; the DB is closed while the daemon writer is still alive

- **File:** `core/settings.py:298-313` (`__init__`, `atexit.register`), `core/settings.py:508-530` (`_wake_writer` / `_writer_loop`), `core/app.py:557-560` (cleanup order), `core/database.py:179-205` (lazy per-thread connection)
- **Confirmed:** yes (mechanism); the "a `set()` lands after `db.close()`" trigger is a hypothesis (see below)
- **Description:** The writer thread is created as `daemon=True` and is never stopped or joined. `SettingsManager` exposes no `close()`, `stop()` or `shutdown()` (verified by `hasattr` probe). `core/app.py:557-560` flushes the settings and then closes the database:
  ```python
  if getattr(self, "settings", None) and hasattr(self.settings, "flush"):
      _step("settings.flush", self.settings.flush)
  if getattr(self, "db", None) and hasattr(self.db, "close"):
      _step("db.close", self.db.close)
  ```
  `core/database.py` connections are lazy and per-thread (`_get_connection()` creates a new `sqlite3.connect` when the thread has none), and `db.close()` only closes the connections it knows about. A `set()` that lands after `db.close()` therefore makes the writer thread **open a brand-new connection to the still-open database file** and write to it, behind the app's back, with a connection that is never closed and whose WAL is never checkpointed (the checkpoint already ran inside `close()`).
- **Cause:** The manager owns a background thread but exposes no shutdown contract, so the owner's (`AppCore`) teardown order cannot include it.
- **Trigger conditions:** A service thread that writes a setting during teardown, in the window between `settings.flush()` and process exit. **Hypothesis:** I did not find a confirmed `set()` call in that window — `main.py:561 app_core.session.save_session()` runs *before* `app_core.cleanup()` (main.py:575), so the known session write is safe. The missing evidence is a service thread that calls `settings.set()` during `cleanup()`; `core/app.py:339-364` (cache cleanup) only *reads* settings.
- **User impact:** A zombie write to a database the app already closed; the row lands but the connection leaks and the WAL is left un-checkpointed until the next start. In the worst case the write raises `sqlite3.ProgrammingError` inside `set_settings_batch`, which is swallowed and turned into "wrote 0 of N keys" — the setting is lost (and, per F-WN-14-2, never retried).
- **Evidence:**
  ```python
  # core/settings.py:508-518
  def _wake_writer(self) -> None:
      """Start the single daemon writer thread if needed, then wake it."""
      with self._lock:
          if self._writer_thread is None or not self._writer_thread.is_alive():
              self._writer_thread = threading.Thread(target=self._writer_loop, name="SettingsWriter", daemon=True)
              self._writer_thread.start()
      self._writer_wake.set()
  ```
  Probe output: `writer thread alive: True daemon: True name: SettingsWriter` / `SettingsManager has close()/stop(): False False False`.
- **Reproduction / verification:** Probe (executed) confirms the absence of a lifecycle API. To reproduce the zombie write: call `sm.set("audio","volume",1)` from a thread *after* `db.close()` and observe a new `sqlite3.Connection` in `db._all_conns` plus the row in the DB file.
- **Suggested fix:** Give `SettingsManager` a `close()`/`stop()` that (a) stops accepting writes, (b) wakes the writer, (c) joins it with a timeout, and (d) performs a final flush; call it from `AppCore.cleanup()` *before* `db.close()`.
- **Fix side effects:** `atexit.register(self.flush)` (core/settings.py:313) currently guarantees a last flush; a `close()` must keep that guarantee for the paths that do not run `AppCore.cleanup()` (e.g. the `os._exit(3)` watchdog path in `main.py:539`, which calls `sync_flush_now()` twice and then `os._exit`).
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

- **Single write path.** `AppApi.save_setting` (core/api.py:2946) and `AppApi.set_setting` (core/api.py:1886/1895) both go through `SettingsManager.set` → `db.set_settings_batch`. A grep over the whole tree for `set_setting(` / `set_settings_batch(` finds **no** writer outside `core/settings.py:493-506` (only `core/database.py`'s own definitions and tests). The "two write paths to the same store" defect class does **not** exist here: the bridge does not bypass the manager.
- **Single read path with an in-memory cache.** `get_category()` reads `self._cache`, not SQLite; the DB is queried exactly once, in `_load_all()` at construction. `get_all_settings()`/`get_settings()` therefore do **not** re-read the settings table per access, and there is no cross-path cache-invalidation problem because no other path writes the table.
- **No lost update between `set()` and `flush()`.** A `set()` that lands while a flush is in flight re-dirties the key and the newer value wins. Verified by probe: `final persisted volume: 20`, `final cache volume: 20` (the slow-DB race probe).
- **No lost wakeup in the writer loop.** `flush()` runs *after* the sleep, so every `set()` that happened before the flush is captured; the Event is re-armed by every `set()`. The one theoretical gap (a `set()` between `wait()` and `clear()`) costs at most one extra interval, never a lost write.
- **No lock-ordering deadlock.** The only nesting is `flush()` → `_flush_lock` → `_lock`; `set()` takes `_lock` alone and calls `_wake_writer()` *outside* the lock. `tests/test_settings_flush.py::test_concurrent_setters_and_sync_flush` exercises 3 setters + 1 flusher for 0.3 s and asserts no hang.
- **Defaults are never aliased into the cache.** `_load_all` (core/settings.py:334) and `reset_category` (core/settings.py:544) both `copy.deepcopy` the default, so the module-level `DEFAULT_SETTINGS` cannot be mutated through the manager. (`get_category`'s `.copy()` fallback to `DEFAULT_SETTINGS` is unreachable for known categories, because `_load_all` always populates them.)
- **Secret masking on the read path.** `_mask_secrets()` (core/api.py:243-253) blanks `yandex_token` / `oauth_client_secret` and adds `has_*` flags; `_is_empty_secret_write()` (core/api.py:267-269) stops a masked read echoed back from wiping the stored token; `AppApi.get_setting` (core/api.py:1860-1861) masks too.
- **Values are never logged.** The failure paths log key names, counts and exception text (`core/settings.py:476-483`, `core/settings.py:505`, `core/database.py:2047/2066/2081`) — never a setting value.
- **`get_system_region()` fails safely.** Every branch is wrapped in `try/except`; the worst case is the hardcoded `"US"`, never an exception at import.
- **The hotkey mirror currently has zero drift** — 10 ids, identical values on both sides; `pytest tests/test_keybind_contracts.py tests/test_settings_manager.py tests/test_settings_flush.py -q` → **69 passed**.
- **Shutdown ordering is right.** `main.py:561 save_session()` (which writes 7 session settings and flushes synchronously) runs *before* `main.py:575 app_core.cleanup()`, and `cleanup()` flushes the settings *before* `db.close()` (core/app.py:557-560). The `os._exit(3)` watchdog path flushes explicitly twice because `os._exit` skips `atexit` (main.py:526/536) — a correct use of `sync_flush_now()`.

---

### 4. Coverage gaps

- **The app was never run** (forbidden by the ground rules, and it would disturb the user's profile). All runtime claims are derived from the code paths and from in-memory DB doubles, not from an observed session. In particular, the offline-mode impact (F-WN-14-1) is a code-path derivation: I proved the *state never reaches the frontend*, but I did not observe the user's visible symptoms.
- **F-WN-14-2** was reproduced with a fake DB that raises; I did not induce a real `SQLITE_BUSY` against `core/database.py` (that would mean writing to `~/.nedotify/`, which is forbidden).
- **F-WN-14-11's trigger** is a hypothesis: I confirmed the mechanism (lazy per-thread connection, no lifecycle API) but did not find a confirmed `set()` call in the post-`db.close()` window. The missing evidence is a service thread writing a setting during `AppCore.cleanup()`.
- **`ui/web_new_v2/js/settings.js` (3111 lines)** was read only in the regions relevant to the settings/hotkeys surface (lines 25-54, 372-391, 1020-1089, 1110-1239). The rest of that file — theming, storage panels, the equalizer UI — belongs to WN-30 and was not audited.
- **`js/hotkeys.js` was read in full but the *consumers* of the dispatched actions** (`js/player.js` `togglePlayPause`, `window.NeDotify.adjustVolume`, the DOM ids `pp-btn-like`, `pp-btn-lyrics`) were not traced; those belong to WN-29/WN-30. A hotkey that dispatches correctly but whose target element no longer exists would be a WN-30 finding.
- **`tools/bench/profile.py:131`** already notes that `SettingsManager` only coerces `'true'`/`'false'`; I did not run the bench harness (WN-35).
- **`core/database.py`'s settings table** (schema, migrations, WAL interactions) is WN-12's; I read only the write/read helpers and the connection lifecycle needed for my findings.
- The `android/` subtree was **not opened** (out of scope for this run).
- I did not audit `core/session.py`'s or `core/offline.py`'s own logic beyond the call sites listed in §1.

---

### 5. Architecture improvements (ARCH)

*(No proven defect — proposals for the engineering of the settings subsystem. Separate from the defect list above.)*

- **ARCH-1 — One schema, one owner.** The settings schema is currently declared twice (`core/settings.py` `DEFAULT_SETTINGS` and the literal category list in `core/api.py:2929`) and the hotkey table three times (F-WN-14-1, F-WN-14-7). Introduce a single machine-readable schema (a JSON/py file listing `category → key → type → default`) that the Python side loads at import and that generates the JS-side defaults module, and make `SettingsManager` expose `categories()` / `get_all()` so the bridge cannot re-declare the list. A single test then compares *the schema against itself*, which is the only comparison that cannot drift.

- **ARCH-2 — A real type system for the store.** `DEFAULT_SETTINGS` carries values but no types, which forces the type-blind `"true"/"false"` heuristic in `get()` and makes `set()` accept any type for any key (F-WN-14-10). With declared types the manager can validate on write, coerce on read, and reject a `None` that should be a "clear" (F-WN-14-3) instead of guessing from `None`.

- **ARCH-3 — Separate the secret store from the settings store.** The bridge implements "secrets do not travel to JS" in the *read path* of a generic key/value table, which any new consumer can bypass — and the frontend's own localStorage mirror already does (F-WN-14-5). A dedicated `SecretStore` (Windows Credential Manager / DPAPI) with an explicit `get_secret`/`set_secret` API, referenced by name from the settings schema, makes the boundary structural instead of a convention.

- **ARCH-4 — Give `SettingsManager` a lifecycle.** It owns a thread but exposes no `close()`/`stop()`, so `AppCore.cleanup()` cannot order the teardown correctly and a zombie write to a closed DB is possible (F-WN-14-11). A `close()` that stops accepting writes, wakes the writer, joins it with a timeout and performs the final flush belongs on the same interface as the constructor.

- **ARCH-5 — Make the writer's failure policy explicit.** The write-behind queue currently has "retry on the next unrelated write" as an implicit policy and no re-arm (F-WN-14-2). A policy object — attempt budget, back-off, and a "give up and tell the caller" signal — plus a `flush()` return value the caller can act on (the bridge currently always answers `True`) would make the durability contract explicit instead of emergent.

- **ARCH-6 — Namespaces for user-scoped values.** The settings table currently doubles as a scratch store (`lyrics_offset_<track>`, `pinned_track`, `player.queue_autopilot`) with no retention policy (F-WN-14-8). A reserved namespace with a documented eviction rule keeps the schema table clean and makes the "unknown keys are preserved" compatibility rule enforceable.

- **ARCH-7 — One persistence store per logical setting.** The hotkeys live in both SQLite and `nedotify_keybinds` localStorage with no reconciliation and no version stamp, so the two can disagree and the last-writer (the backend) always wins (F-WN-14-7). Either the localStorage mirror becomes a *cache with a version* or it goes away and the frontend renders from the bridge answer with a synchronously-available default table.

- **ARCH-8 — Deterministic import.** `DEFAULT_SETTINGS` is non-deterministic at import because of `get_system_region()` (F-WN-14-9). Computing it lazily at the point of use, and caching it for the process, makes the schema a pure value — which also makes the whole-tree comparisons in `tests/test_settings_manager.py` meaningful.
