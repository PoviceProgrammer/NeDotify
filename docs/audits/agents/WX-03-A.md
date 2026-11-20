# WX-03-A — Settings round-trip (Windows desktop) — ROLE A (Correctness & Reliability)

## SCENARIO WX-03 — Settings round-trip — ROLE A

Scenario: `core/settings.py::DEFAULT_SETTINGS` ↔ `ui/web_new_v2/js/settings.js` ↔
`core/api.py::get_settings`/`save_setting` ↔ `core/database.py::set_setting` ↔
`ui/web_new_v2/js/hotkeys.js::DEFAULT_KEYBINDS` ↔ `core/settings.py::DEFAULT_SETTINGS["hotkeys"]`.

---

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `core/settings.py` | 1–589 (whole file) |
| `core/api.py` | 232–281, 440–519, 912–941, 1853–1900, 1945–2004, 2775–2914, 2915–3039, 3160–3209, 4040–4119, 4120–4169 |
| `core/database.py` | 2020–2149 (`set_setting`, `set_settings_batch`, `get_setting`, `get_settings_by_category`, `get_all_settings`) |
| `core/app.py` | 100–160, 500–586 (constructor wiring, `cleanup`) |
| `core/session.py` | 1–96 (whole file) |
| `core/offline.py` | 1–77 (whole file) |
| `core/playback_recovery.py` | 113 (offline check) |
| `core/tray.py` | 104 (quit path) |
| `main.py` | 300–379, 400–459, 510–584 (startup, session restore, `on_closed`, watchdog `os._exit` path, shutdown) |
| `ui/web_new_v2/js/settings.js` | 1–130, 126–565, 643–1002, 1033–1153, 1653–1720, 2021–2160, 2494–2560, 2589–2730, 3195–3219 |
| `ui/web_new_v2/js/hotkeys.js` | 1–256 (whole file) |
| `ui/web_new_v2/js/player.js` | 15–20, 170–312, 380–424, 1150–1235, 1420–1464, 1955–2039 |
| `ui/web_new_v2/js/equalizer.js` | 1–283 |
| `ui/web_new_v2/js/feature-controls.js` | 1–135 (whole file) |
| `ui/web_new_v2/js/main.js` | 340–564 |
| `ui/web_new_v2/js/events.js` | 280–350 |
| `ui/web_new_v2/js/library-view.js` | 172–196 |
| `ui/web_new_v2/js/queue.js` | 60–99 |
| `ui/web_new_v2/js/onboarding.js` | 150–229 |
| `ui/web_new_v2/js/visualizer.js` | 60–75, 185–230 |
| `ui/web_new_v2/js/utils.js` | 520–530, 605–615, 1300–1320 |
| `ui/web_new_v2/js/ui-style.js` | 78–100, 146–165 |
| `ui/web_new_v2/index.html` | 1388, 1405, 2245 (control inventory) |
| `tests/test_keybind_contracts.py` | whole file |
| `tests/test_settings_controls_ui.py` | whole file |

**Callees traced into other areas** (not owned by WX-03; named where relevant):
`core/app.py::AppCore.cleanup` (WN-02), `main.py` bootstrap/shutdown (WN-01),
`core/tray.py` (WN-16), `core/session.py` (WN-02), `audio/queue.py` (WN-17),
`core/offline.py` / `core/playback_recovery.py` (WN-15),
`ui/web_new_v2/js/player.js` (WN-29), `ui/web_new_v2/js/settings.js` (WN-30),
`core/database.py` (WN-12).

**Verification harnesses written (scratch, outside the repo)**
- `%TEMP%\opencode\wx03_scan.py` — static enumeration of every `DEFAULT_SETTINGS` key → Python readers/writers and JS writers.
- `%TEMP%\opencode\wx03_verify.py`, `wx03_verify2.py`, `wx03_verify3.py` — executed the **real** `core/settings.py::SettingsManager` against a `FakeDB` that reproduces `core/database.py::_serialize_setting` / `json.loads` exactly.
- `%TEMP%\opencode\wx03_hotkeys.js` — executed the **real** `ui/web_new_v2/js/hotkeys.js` in a Node `vm` with a fake `pywebview` bridge and a fake `localStorage`, driving `initHotkeys()` through 6 scenarios.

No repo file was modified. `~/.nedotify/` was never touched.

---

### 2. Findings

#### F-WX-03-1  [P1] — `AppApi.get_settings()` omits the `network` category, so offline mode is never restored into the frontend

- **File:** `core/api.py:2922-2938` (list at `core/api.py:2929`); `core/settings.py:52-55`; `ui/web_new_v2/js/feature-controls.js:9-24,109-113,133`; `ui/web_new_v2/js/player.js:1440,1524`; `ui/web_new_v2/js/utils.js:526,608`; `core/offline.py:10-14`
- **Confirmed:** yes
- **Description:** `get_settings()` assembles the whole settings tree from a **hard-coded** category list. `network` (and `subscription`) are in `DEFAULT_SETTINGS` but **not** in that list, so the bridge never returns `network.offline_mode`. The frontend reads `window.settings?.network?.offline_mode` in seven places; that value is therefore always `undefined`.
- **Cause:** the category list at `core/api.py:2929` is a duplicated, manually-maintained copy of `DEFAULT_SETTINGS`' key set. It has drifted: `network` and `subscription` are missing, while `appearance`, `system` (and `player`/`lyrics`, which only exist as ad-hoc categories) are listed.
- **Trigger conditions:** any app start while `network.offline_mode` is `True` in the database (i.e. the user enabled offline mode and restarted the app).
- **User impact:** the UI comes up **as if it were online** while the backend is in offline mode:
  - `feature-controls.js:112` → `applyOfflineState({ enabled: window.settings?.network?.offline_mode === true })` → `false` → the `offline-mode` CSS class is not applied and `#offline-mode-note` stays hidden.
  - `feature-controls.js:133` → the `nedotify:settings_applied` listener reads `event.detail?.network?.offline_mode` → `undefined` → `false` again.
  - `player.js:1440` → `if (!window.settings?.network?.offline_mode && ...prefetch_track)` → prefetch **is** issued while offline.
  - `player.js:1524` → the flow/auto-pilot track request is issued while offline.
  - `utils.js:526` / `utils.js:608` → remote cover URLs are still attached and remote images are still fetched, although the backend refuses all network work (`core/api.py:461-512`, `core/offline.py:13`).
  The backend side *is* correct (`core/offline.py` reads the DB value), so the two halves of the app disagree about whether the app is offline.
- **Evidence:**
  ```python
  # core/api.py:2929
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', 'overlay',
                'efficiency', 'optimization', 'hotkeys', 'storage', 'player_appearance',
                'personalization', 'interface', 'ui', 'theme', 'equalizer', 'auth', 'services',
                'session', 'zapret']
  ```
  ```python
  # core/settings.py:52-55
  DEFAULT_SETTINGS = {
      "network": {
          "offline_mode": False,
      },
  ```
  ```javascript
  // ui/web_new_v2/js/feature-controls.js:112
  applyOfflineState({ enabled: window.settings?.network?.offline_mode === true });
  ```
- **Reproduction / verification:** executed `wx03_scan.py` / `wx03_verify.py` against the real `DEFAULT_SETTINGS` and the literal list from `core/api.py:2929`:
  ```
  DEFAULT_SETTINGS categories MISSING from get_settings() list: ['network', 'subscription']
  categories in the list that do not exist in DEFAULT_SETTINGS: ['appearance', 'player', 'lyrics', 'system']
  ```
  `subscription` is documented as intentionally unused (`core/settings.py:265-278`), so `network` is the real defect.
- **Suggested fix:** derive the list from `DEFAULT_SETTINGS` (plus the ad-hoc categories the UI writes) instead of hard-coding it, or at minimum insert `'network'`. A unit test that asserts `set(AppApi.get_settings()) ⊇ set(DEFAULT_SETTINGS)` would pin it.
- **Fix side effects:** adding `network` means the frontend will start in offline mode and will stop prefetching/remote-covering — correct, but it changes visible behaviour on an offline start, so the offline banner/note paths must work.
- **Discovered by:** A

---

#### F-WX-03-2  [P2] — `applySettings()` reads `shuffle` / `repeat` / `volume` at the top level; the schema nests them under `session` / `audio`

- **File:** `ui/web_new_v2/js/player.js:1973-1992` (reads at 1981-1988); `core/settings.py:83` (`audio.volume`), `core/settings.py:256-264` (`session.shuffle`, `session.repeat`); `ui/web_new_v2/js/main.js:400,416`; `ui/web_new_v2/js/queue.js:61-69`
- **Confirmed:** yes
- **Description:** `get_settings()` returns a **category map** (`{audio: {...}, session: {...}, …}`). `applySettings(settings)` is handed that whole map and reads `settings.shuffle`, `settings.repeat` and `settings.volume` — keys that exist only at the top level of an *old flat* schema. In the current schema `shuffle`/`repeat` live under `session` and `volume` under `audio`, so all three reads are `undefined`.
- **Cause:** the settings schema was nested but this consumer was not updated; there is no second consumer that restores them.
- **Trigger conditions:** every app start. `settings.shuffle === undefined` → `classList.toggle('active', undefined)` → the button is always drawn inactive. `settings.volume === undefined` → the `if (settings.volume !== undefined)` guard at `player.js:1986` is skipped → `currentVolume` keeps the module default `70` (`player.js:15`).
- **User impact:**
  1. **Shuffle/repeat state is lost on restart.** The *engine* is correctly restored (`main.py:320-321`: `app_core.engine.queue.shuffle = session_data.get("shuffle", False)` / `.repeat = …`), but the UI shows both buttons inactive. `shuffle_changed` / `repeat_changed` are only emitted on a user toggle (`core/api.py:2004-2013`), and `queue_updated` → `queue.js:61-69` does not touch those buttons — so `applySettings` is the *only* restore path and it is broken.
  2. **"Перемешать" (Shuffle all) in the library toggles the engine the wrong way.** `library-view.js:182`:
     ```javascript
     if(!document.getElementById('pb-btn-shuffle').classList.contains('active')){
       const active=await window.pywebview.api.toggle_shuffle();
       document.querySelectorAll('#pb-btn-shuffle,#pp-btn-shuffle').forEach(button=>button.classList.toggle('active',Boolean(active)));
     }
     ```
     With shuffle already ON in the restored engine but the button drawn inactive, this calls `toggle_shuffle()` → the engine turns shuffle **OFF** → the "shuffle all" action silently does nothing.
  3. **The saved volume is never restored.** `audio.volume` is written by the bridge (`core/api.py:1956-1958 set_volume`) and read back by `main.py:560`, but the player starts at **70 %** on every launch. `AppApi.get_volume()` (`core/api.py:1960-1962`) exists and has **zero** JS callers.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:1981-1988
  if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
  if (ppShuffle) ppShuffle.classList.toggle('active', settings.shuffle);
  if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
  if (ppRepeat) ppRepeat.classList.toggle('active', settings.repeat !== 'off');

  if (settings.volume !== undefined) {
      currentVolume = settings.volume;
  }
  ```
  ```python
  # core/settings.py:256-264
  "session": {
      "last_track_id": None, "last_position": 0, "last_volume": 70,
      "last_queue": [], "last_queue_index": 0,
      "shuffle": False,
      "repeat": "off",
  },
  ```
- **Reproduction / verification:** read `main.js:400` (`applySettings(cachedSettings)`) and `main.js:416` (`applySettings(freshSettings)`) — both pass the category map produced by `AppApi.get_settings()`. Grep for `settings.shuffle` / `settings.repeat` / `settings.volume` in `ui/web_new_v2/js/**` returns **only** `player.js:1981-1988`. Grep for `get_volume` in `ui/web_new_v2/**` returns **no** hits.
- **Suggested fix:** read `settings.session?.shuffle` / `settings.session?.repeat` / `settings.audio?.volume` (or have the backend emit a flat `player_state` object). The engine's live state is already available via `AppApi.get_queue()` (`core/api.py:1772-1780` returns `shuffle` and `repeat`) — using it avoids the schema-depth problem entirely.
- **Fix side effects:** restoring the volume means the audible volume on start equals the stored one — that is the intent, but users who were surprised by the previous always-70 % behaviour will notice the change. Restoring the shuffle button state also means the library "Перемешать" button must no longer toggle the engine when it is already active.
- **Discovered by:** A

---

#### F-WX-03-3  [P2] — The legacy hotkey migration table rewrites a *legitimate* user binding on every start

- **File:** `ui/web_new_v2/js/hotkeys.js:66-98` (table at 72-78, application at 86-98, persistence at 98); `ui/web_new_v2/js/hotkeys.js:186-196` (dispatcher); `ui/web_new_v2/js/hotkeys.js:140-142` (the write path)
- **Confirmed:** yes (executed)
- **Description:** `LEGACY_DEFAULT_MIGRATION` maps old *default* strings to new ones and is applied **unconditionally to every action id** whose current binding happens to equal one of the legacy strings. It cannot distinguish "a legacy default that leaked into storage" from "a binding the user deliberately chose". When it fires, the rewritten value is written back to `localStorage` (`hotkeys.js:98`), i.e. the damage is persisted.
- **Cause:** the migration is keyed on the *binding value* alone, with no record of which bindings were shipped defaults and no per-action provenance.
- **Trigger conditions:** the user's binding for an action equals one of `'Ctrl+M'`, `'Ctrl+L'`, `'Ctrl+F'`, `'Ctrl+KeyM'`, `'Ctrl+KeyK'`, `'Ctrl+O'`, `'Ctrl+KeyO'` **and** the backend does not hold that binding for that action (e.g. the `save_setting` bridge call failed, or the DB write was lost). The backend normally masks the damage (it wins at `hotkeys.js:104-115`), but the localStorage copy has already been rewritten by then.
- **User impact (all reproduced):**
  - `Ctrl+L` → rewritten to **`KeyK`**. `KeyK` is the *default* binding of the `like` action, so the user now has two actions on `KeyK`. The dispatcher (`hotkeys.js:186-196`) iterates `activeKeybinds` in insertion order and `break`s on the first match; `toggle_lyrics` is inserted before `like`, so **the `like` hotkey becomes permanently dead** and `Ctrl+L`/lyrics stops working too.
  - `Ctrl+O` → the migration value is `null`, so the action id is **deleted** from `activeKeybinds` (`hotkeys.js:89`). The action then has **no binding at all** — not even the default `KeyM` — and the deletion is persisted to `localStorage`.
  - `Ctrl+F` → rewritten to `Slash` (the `search` default) — the user's own choice is destroyed and `search` now has a duplicate.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/hotkeys.js:72-78
  const LEGACY_DEFAULT_MIGRATION = {
      'Ctrl+Right': 'Ctrl+ArrowRight', 'Ctrl+Left': 'Ctrl+ArrowLeft',
      'Ctrl+Up': 'Ctrl+ArrowUp', 'Ctrl+Down': 'Ctrl+ArrowDown',
      'Ctrl+KeyM': 'KeyM', 'Ctrl+KeyK': 'KeyK',
      'Ctrl+M': 'KeyM', 'Ctrl+L': 'KeyK', 'Ctrl+F': 'Slash',
      'Ctrl+KeyO': null, 'Ctrl+O': null
  };
  ```
  ```javascript
  // ui/web_new_v2/js/hotkeys.js:86-98
  for (const [actionId, key] of Object.entries(activeKeybinds)) {
      if (Object.prototype.hasOwnProperty.call(LEGACY_DEFAULT_MIGRATION, key)) {
          const newK = LEGACY_DEFAULT_MIGRATION[key];
          if (newK === null) { delete activeKeybinds[actionId]; }
          else { activeKeybinds[actionId] = newK; }
          migrated = true;
      } else if (!KNOWN_ACTIONS.has(actionId)) { … }
  }
  if (migrated) saveKeybindsToStorage(activeKeybinds);
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wx03_hotkeys.js` loads the real `hotkeys.js` in a Node `vm` with a fake bridge and `localStorage`. Output:
  ```
  ### 3. same, but the BACKEND is unreachable (bridge rejects)
     active = {… "toggle_lyrics":"KeyK" … "like":"KeyK"}
     localStorage nedotify_keybinds = {… "toggle_lyrics":"KeyK" … "like":"KeyK"}

  ### 4b. user binds toggle_mute to Ctrl+O, backend unreachable
     toggle_mute present? false
     localStorage nedotify_keybinds = {… }        <- toggle_mute deleted
  ```
  With a healthy backend that already holds the user's value the migration is masked (scenario 2 returned `toggle_lyrics: 'Ctrl+L'` intact) — so the defect needs the backend copy to be missing/stale.
- **Suggested fix:** run the migration only against values that are *known legacy defaults* (i.e. only when the value equals the shipped default of that build), or gate it behind an explicit "migrated-from-version-X" marker written once. Never delete an action id whose current binding came from the user. Also migrate **before** merging `localStorage`, or record which ids the backend supplied.
- **Fix side effects:** existing installs that still carry a genuine legacy default in `localStorage` need the migration to keep running — so the fix must be one-shot/version-gated, not a removal.
- **Discovered by:** A

---

#### F-WX-03-4  [P2] — Two settings controls with no effect: "Volume normalization (EBU R128)" and the "Region" selector

- **File:** `ui/web_new_v2/js/settings.js:128` (`setupToggle('toggle-normalization','volume_normalization','audio')`), `ui/web_new_v2/js/player.js:386-402` (`applyVolumeNormalization`), `ui/web_new_v2/js/player.js:391`; `core/settings.py:80-81`; `ui/web_new_v2/js/settings.js:402-407` (region select), `core/api.py:3315` (`get_popular_tracks(region="US")`)
- **Confirmed:** yes
- **Description:**
  - `audio.volume_normalization` is written by the settings toggle (`settings.js:128`) and by the onboarding wizard (`onboarding.js:170`), and read back only to repaint the toggle (`settings.js:877-880`). The only code that could apply it — `player.js::applyVolumeNormalization` — **has zero callers** (grep over `ui/web_new_v2/js/**` returns only its own definition). The `DynamicsCompressor` node is therefore never reconfigured. `audio.target_loudness` (`-14.0`) is likewise never read; `player.js:391` hard-codes `-14.0`.
  - `general.region` is written by the Region dropdown (`settings.js:405`) and restored into the dropdown (`settings.js:884-887`), but **no backend code reads it**: the only region consumer, `AppApi.get_popular_tracks(self, region: str = "US")` (`core/api.py:3315`), takes a hard-coded `"US"` default and the frontend never passes the setting.
- **Cause:** two UI controls were wired to settings keys that no consumer ever acts on; the schema entries look live but are inert.
- **Trigger conditions:** any time the user toggles "Volume normalization" or changes the Region dropdown.
- **User impact:** the toggles/selects persist and re-render correctly (so the app *looks* like it works) but nothing changes: the compressor threshold stays at the default `-3.0` ratio `2`, and popular-track feeds are still fetched for `US` regardless of the selected region.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:386-402 — no caller anywhere
  export function applyVolumeNormalization(enabled) {
      if (!audioCtx) initAudioContext();
      if (!compressorNode) return;
      try {
          if (enabled) { compressorNode.threshold.value = -14.0; … }
  ```
  ```python
  # core/api.py:3315 — the only region consumer, hard-coded default
  def get_popular_tracks(self, region: str = "US"):
  ```
  ```javascript
  // ui/web_new_v2/js/settings.js:402-407
  const selectRegion = document.getElementById('select-region');
  if (selectRegion) {
      selectRegion.addEventListener('change', (e) => {
          saveSetting('region', e.target.value, 'general');
      });
  }
  ```
- **Reproduction / verification:** `Select-String` over `ui/web_new_v2/js/*.js` for `applyVolumeNormalization` → only `player.js:386` (the definition). `Select-String` over `core/**/*.py`, `main.py` for `volume_normalization|target_loudness|region` → only the settings schema, `api.py:2795` (onboarding mapping) and `api.py:3315` (hard-coded `"US"`). No JS caller passes a region to `get_popular_tracks`.
- **Suggested fix:** either wire the two controls to real consumers (call `applyVolumeNormalization` from the audio graph setup and pass `settings.general.region` into `get_popular_tracks`), or remove the controls and the schema entries so the UI stops advertising a no-op.
- **Fix side effects:** wiring the normalizer changes the audio character of every track; wiring the region changes which popular feed is fetched. Both are behaviour changes that need product sign-off.
- **Discovered by:** A

---

#### F-WX-03-5  [P3] — `AppApi` has two settings write paths with different semantics; only one is live, and it swallows the autostart failure

- **File:** `core/api.py:2940-2953` (`save_setting`) vs `core/api.py:1871-1900` (`set_setting`); `core/api.py:2958-2962` (`get_settings_by_category`, `update_setting`); `core/api.py:2839-2890` (`update_autostart`)
- **Confirmed:** yes
- **Description:** the bridge exposes **two** write implementations over the same store. `core/settings.py::SettingsManager` is the single source of truth, but the *bridge* has two wrappers with different contracts:

  | | `save_setting(key, value, category="app")` | `set_setting(section, key=None, value=None)` |
  |---|---|---|
  | return value | `True` / `False` (bool) | `{"success": True}` / `{"success": False, …}` (dict) |
  | dotted key | **not** supported — `save_setting("zapret.auto_start", True)` writes category `app`, key `"zapret.auto_start"` | supported: `set_setting("zapret.auto_start", True)` → `zapret.auto_start` |
  | bare key | category defaults to `app` | category defaults to `zapret` (`core/api.py:1880`) |
  | autostart side effect | **yes** (`core/api.py:2947-2951`) | **no** |
  | secret masking | yes (`_is_empty_secret_write`) | yes |
  | read-only guard | yes (`_bridge_write_error`) | yes |
  | JS callers | all of them | **none** |

- **Cause:** `set_setting`/`get_setting` are the older pair; they survive only for the unit tests (`tests/test_api_f1_audit.py`, `tests/test_api_misc.py`) and are not called from any `.js` file.
- **Trigger conditions:** any current or future caller that uses the "wrong" one; and, today, `save_setting`'s autostart branch.
- **User impact:** two concrete consequences today:
  1. **`save_setting` reports success when the Windows autostart registration failed.** `update_autostart` returns `False` on a registry error (`core/api.py:2888-2890`) but `save_setting` ignores the return value and only catches an exception — which `update_autostart` never raises. Meanwhile `save_setting` has *already* done `self._core.settings.set(category, key, value)` at `core/api.py:2946`. So `app.autostart` / `general.autostart` are persisted as **ON** while the `HKCU\…\Run` entry was never written — the stored setting and the OS state disagree, and the bridge says "success".
  2. **The two paths disagree on the autostart contract**, so `set_setting("general","autostart",True)` (used by tests and any future caller) silently writes the setting **without** touching the registry.
- **Evidence:**
  ```python
  # core/api.py:2940-2953
  def save_setting(self, key: str, value, category: str = "app"):
      """Save a setting value."""
      if _bridge_write_error(category, key, value):
          return False
      if _is_empty_secret_write(category, key, value):
          return True
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
  # core/api.py:1871-1900
  def set_setting(self, section: str, key=None, value=None):
      """Persist a setting value. Supports set_setting('zapret.auto_start', True) and set_setting('zapret', 'auto_start', True)."""
      …
          if "." in full_key:
              cat, k = full_key.split(".", 1)
          else:
              cat, k = "zapret", full_key
  ```
  ```python
  # core/api.py:2888-2890
      except (OSError, Exception) as e:
          logger.error(f"Failed to update autostart: {e}")
          return False
  ```
- **Reproduction / verification:** `Select-String` over `ui/web_new_v2/js/*.js` + `index.html` for `set_setting` / `update_setting` → **no** hits; `save_setting` → many. `Select-String` over `tests/*.py` → `set_setting`/`get_setting` used in `tests/test_api_f1_audit.py:73-74,88,100-103` and `tests/test_api_misc.py:36-39`.
- **Suggested fix:** delete `set_setting`/`get_setting` (and `update_setting`) and make `save_setting`/`get_settings` the single bridge contract; propagate `update_autostart`'s `False` return so a failed registry write is reported (and the stored setting is rolled back or flagged).
- **Fix side effects:** the tests that call `set_setting`/`get_setting` must be migrated; some external tooling may rely on `get_setting`'s dotted-key form.
- **Discovered by:** A

---

#### F-WX-03-6  [P3] — The same logical setting is written under two different categories (`player.queue_autopilot` vs `audio.queue_autopilot`); the ad-hoc categories/keys are outside the schema

- **File:** `ui/web_new_v2/js/player.js:283-301` (`save_setting('queue_autopilot', …, 'player')`), `ui/web_new_v2/js/settings.js:2663`; `core/settings.py:71-74` (`audio.queue_autopilot`, `audio.flow_enabled`); `core/settings.py:401-418` (`SettingsManager.set` creates unknown categories); `core/settings.py:537-544` (`reset_category` only resets schema keys)
- **Confirmed:** yes
- **Description:** the schema declares `audio.queue_autopilot` and `audio.flow_enabled` and even adds a cross-fallback in `SettingsManager.get` (`core/settings.py:373-382`) — but the frontend writes the value into a **non-existent** `player` category (`player.queue_autopilot`). `SettingsManager.set` happily creates the phantom category, and `_load_all` restores it from the DB (`core/settings.py:336-342`), so the value does round-trip on the frontend side — but **nothing on the backend ever reads `audio.queue_autopilot`**, so the schema entry and its fallback logic are dead code, and the two spellings are a trap for the next reader.
  The same applies to several other keys the UI writes that are **not** in `DEFAULT_SETTINGS`:
  `player.*` (12 keys: `show_queue`, `compact_queue_btn`, `next_track_preview`, `player_prefetch`, `queue_autopilot`, `aura_orbs_enabled`, `progress_color`, `progress_transparency`, `mp_pos`, `title_align`, `player_style`, `slider_type`, `queue_pos`, `queue_view`, `mp_progress`, `mp_cover_shape`, `mp_shape`),
  `storage.cache_quota_gb` (written by `settings.js:263` **and** `core/api.py:4077`),
  `theme.color_<prop>` / `theme.custom_palette_enabled`,
  `equalizer.mode` (written by `js/equalizer.js:345`),
  `personalization.nickname` / `personalization.pinned_track`,
  `audio.visualizer_style` (written by `js/visualizer.js:195`),
  `lyrics.lyrics_offset_<trackKey>`.
- **Cause:** the schema in `core/settings.py` is not the single source of truth — the UI invents keys at the call site and `SettingsManager.set` accepts anything.
- **Trigger conditions:** any of those controls.
- **User impact:**
  - `reset_category("storage")` (and `reset_all()`) **does not** reset `storage.cache_quota_gb` — the "reset" silently leaves the user's cache quota in place, while `cache_size_mb` goes back to 500.
  - The schema's `audio.queue_autopilot` / `audio.flow_enabled` entries and their fallback branch can never fire, so a future reader who "fixes" the frontend to write `audio.queue_autopilot` would silently change behaviour.
  - `core/database.py::get_settings_by_category` (see F-WX-03-7) returns the *stored* rows only, so for these ad-hoc categories it returns a very different set from `AppApi.get_settings_by_category`.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:287-293
  if (window.pywebview?.api?.save_setting) {
      try {
          Promise.resolve(window.pywebview.api.save_setting('queue_autopilot', isFlowEnabled, 'player')).then(result => {
  ```
  ```python
  # core/settings.py:413-417 — an unknown category is silently created
  with self._lock:
      if category not in self._cache:
          self._cache[category] = {}
      self._cache[category][key] = value
      self._dirty.add((category, key))
  ```
  ```python
  # core/settings.py:537-544 — reset only touches schema keys
  def reset_category(self, category: str) -> None:
      if category in DEFAULT_SETTINGS:
          for key, value in DEFAULT_SETTINGS[category].items():
              self.set(category, key, copy.deepcopy(value))
  ```
- **Reproduction / verification:** executed `wx03_verify.py` against the real `SettingsManager`:
  ```
  'cache_quota_gb' in DEFAULT_SETTINGS['storage']: False
  after reset_category('storage'), cache_quota_gb = 7   cache_size_mb = 500
  categories in cache: ['app','audio','auth','efficiency','equalizer','general','hotkeys',
   'interface','network','optimization','overlay','personalization','player',
   'player_appearance','services','session','storage','subscription','theme','ui','zapret']
  'player' in DEFAULT_SETTINGS: False
  ```
- **Suggested fix:** promote the ad-hoc keys into `DEFAULT_SETTINGS` (so they are reset, typed and visible) and make `SettingsManager.set` reject or log unknown `(category, key)` pairs instead of silently creating them.
- **Fix side effects:** adding the keys to the schema changes `get_settings()` payloads slightly and makes `reset_category` actually reset them — the latter is the intended behaviour but is a user-visible change.
- **Discovered by:** A

---

#### F-WX-03-7  [P3] — `core/database.py::get_settings_by_category` is a second, divergent implementation of the same name (dead code)

- **File:** `core/database.py:2100-2115` vs `core/api.py:2958-2959`
- **Confirmed:** yes
- **Description:** two methods with the same name and different contracts:
  - `AppApi.get_settings_by_category(category)` → `SettingsManager.get_category(category)` → **bare** keys, **merged with the schema defaults** (all 10 hotkey ids are always present).
  - `core/database.py::get_settings_by_category(category)` → **full** keys (`"hotkeys.toggle_mute"`) and **only the rows physically stored in SQLite** (the 8 untouched defaults are absent).
- **Cause:** the DB-level helper predates the `SettingsManager` cache and was never removed when the manager took over.
- **Trigger conditions:** the DB-level method has **zero callers** in `core/`, `services/`, `audio/`, `utils/`, `main.py` and `tests/` — so it is dead code that a future caller will happily use and get a different answer from.
- **User impact:** none today; a latent trap. A caller that used the DB method for the hotkeys would see 2 rows instead of 10 and would conclude that the other 8 bindings were lost.
- **Evidence:**
  ```python
  # core/database.py:2100-2115
  def get_settings_by_category(self, category: str) -> Dict[str, Any]:
      cursor = self.conn.cursor()
      cursor.execute("SELECT key, value FROM settings WHERE category = ?", (category,))
      result = {}
      for row in cursor.fetchall():
          k, raw_v = row[0], row[1]
  ```
  ```python
  # core/api.py:2958-2959
  def get_settings_by_category(self, category: str):
      return _mask_secrets(category, self._core.settings.get_category(category))
  ```
- **Reproduction / verification:** `Select-String` over all `*.py` for `get_settings_by_category` → only the two definitions. Executed `wx03_verify2.py`:
  ```
  get_category('hotkeys') -> {10 ids, bare keys}
  db.get_settings_by_category('hotkeys') -> {'hotkeys.toggle_mute': 'KeyQ'}
  ```
- **Suggested fix:** delete `core/database.py::get_settings_by_category` (or rename it to `get_stored_settings_by_category` and document the key-shape difference).
- **Fix side effects:** none — no callers.
- **Discovered by:** A

---

#### F-WX-03-8  [P3] — A failed settings write is re-queued but never retried by the writer thread

- **File:** `core/settings.py:443-483` (`flush`), `core/settings.py:508-530` (`_wake_writer` / `_writer_loop`)
- **Confirmed:** yes
- **Description:** `flush()` correctly re-queues a failed batch (`core/settings.py:472-474`), but the writer thread does **not** re-arm its wake event after a failure: `_writer_loop` does `wait() → clear() → sleep(0.5) → flush()` and nothing sets `_writer_wake` again after a failed flush. The pending keys are therefore retried only when (a) the next `set()` happens, (b) `atexit` fires, or (c) `AppCore.cleanup()` runs.
- **Cause:** the retry signal is the same one-shot event that triggered the flush; a failed flush consumes it.
- **Trigger conditions:** any transient DB failure (SQLITE_BUSY, a locked file, a disk error) while the writer thread is the only writer.
- **User impact:** a single transient failure can leave a setting unwritten for the rest of the session; if the app is then killed (not closed), the setting is lost. On a clean exit the `atexit`/`AppCore.cleanup()` flushes cover it, so this is not a loss on a normal quit.
- **Evidence:**
  ```python
  # core/settings.py:472-483
  if written < len(payload):
      with self._lock:
          self._dirty.update(pending)
      if error is not None:
          logger.error(f"Settings flush failed, {len(pending)} keys still pending: {error}")
  ```
  ```python
  # core/settings.py:520-530
  def _writer_loop(self) -> None:
      while True:
          self._writer_wake.wait()
          self._writer_wake.clear()
          time.sleep(self.FLUSH_INTERVAL_SECONDS)
          try:
              self.flush()
  ```
- **Reproduction / verification:** `wx03_verify3.py` forced `set_settings_batch` to return 0:
  ```
  Settings flush wrote 0 of 1 keys; 1 keys still pending
  after failed flush, _dirty = {('audio', 'volume')}
  db rows = {}
  _writer_wake.is_set() = False
  ```
  (and the key only reached the DB after a subsequent `set()`).
- **Suggested fix:** re-arm the wake event after a failed flush (or use a bounded retry loop inside the writer) so the pending set is retried on the next interval.
- **Fix side effects:** a permanently failing DB would spin the writer at 2 Hz instead of once — cap the retries or add back-off.
- **Discovered by:** A

---

#### F-WX-03-9  [P3] — Text settings change type across the persistence round trip; one write path sends strings where another sends numbers

- **File:** `core/database.py:2028-2034` (`_serialize_setting`), `core/database.py:2084-2098` (`get_setting`), `core/database.py:2117-2132` (`get_all_settings`); `ui/web_new_v2/js/settings.js:3204-3208` (workshop write), `ui/web_new_v2/js/settings.js:2118,2131` (slider write); `core/settings.py:394-399` (`get()` string coercion)
- **Confirmed:** yes
- **Description:** `_serialize_setting` JSON-encodes `dict/list/bool/int/float` but writes a **plain string** as-is (`str(value)`), while every reader does `json.loads(raw_v)` first. A string whose content happens to be valid JSON therefore comes back with a **different type**: `"true"` → `True` (bool), `"12"` → `12` (int), `"null"` → `None`. `SettingsManager.get` adds a second coercion layer (`"true"`/`"false"` → bool, `core/settings.py:394-399`).
  This is not theoretical: the **workshop "apply wallpaper" button writes `bg_blur`/`bg_dim` as strings** (`document.getElementById('slider-bg-blur').value` is always a string), while the background sliders write the same two keys as **numbers** (`setupSlider` → `Number(e.target.value)`, `settings.js:704`).
- **Cause:** an asymmetric serializer (raw string) paired with a JSON-parsing reader, plus a write path that skips the `Number()` normalisation the slider helper performs.
- **Trigger conditions:** applying a wallpaper from the workshop panel (`settings.js:3198-3217`).
- **User impact:** no user-visible break **today** — all current consumers coerce with `Number()`/`parseInt()` (`ui-style.js:162-163`, `main.js:320-321`, `settings.js:2119,2132`) and the DB read-back re-types the value to a number anyway. The defect is the latent type flip: a future consumer that does `settings.theme.bg_blur === 12` or `typeof v === 'string'` would silently misbehave, and a text setting whose value is `"true"` would arrive as a boolean.
- **Evidence:**
  ```python
  # core/database.py:2028-2034
  @staticmethod
  def _serialize_setting(value: Any) -> str:
      if isinstance(value, (dict, list, bool, int, float)):
          return json.dumps(value)
      if value is None:
          return ""
      return str(value)
  ```
  ```python
  # core/database.py:2090-2098 (get_setting) / 2123-2131 (get_all_settings)
  try:
      return json.loads(raw_v)
  except (json.JSONDecodeError, TypeError):
      if raw_v in ("True", "true"): return True
      elif raw_v in ("False", "false"): return False
      return raw_v
  ```
  ```javascript
  // ui/web_new_v2/js/settings.js:3204-3208 — strings, not numbers
  const blurVal = document.getElementById('slider-bg-blur')?.value || 0;
  const dimVal = document.getElementById('slider-bg-dim')?.value || 20;
  …
  saveSetting('bg_blur', blurVal, 'theme');
  saveSetting('bg_dim', dimVal, 'theme');
  ```
- **Reproduction / verification:** `wx03_verify.py`:
  ```
  string 'true' -> True bool
  string '12'   -> 12 int
  SettingsManager.get('theme','font_family') -> True
  ```
  (the last line shows the value coming back as a Python `bool`, not the `str` that was written).
- **Suggested fix:** make `_serialize_setting` JSON-encode strings too (`json.dumps(str)`), or make the reader not `json.loads` a column that is known to be a string. Independently, wrap the workshop write in `Number(...)` like `setupSlider` does.
- **Fix side effects:** changing the serializer changes the stored representation of every existing string setting; the reader must stay tolerant of the old raw form (it already is, via the `except` branch), so the migration is safe but should be checked against pre-existing rows.
- **Discovered by:** A

---

#### F-WX-03-10  [P3] — Dead schema: 47 of the 160 `DEFAULT_SETTINGS` keys have neither a UI control nor any reader

- **File:** `core/settings.py:52-287` (the schema); `core/settings.py:551-589` (the ten accessor properties)
- **Confirmed:** yes
- **Description:** a systematic sweep of all 20 categories / 160 keys against (a) every `saveSetting`/`save_setting`/`setupToggle`/`setupSlider` call site in `ui/web_new_v2/js/**` and (b) every `settings.get(...)`/`settings.set(...)` call site in `core/`, `audio/`, `services/`, `utils/`, `main.py` shows a large block of schema entries that are neither written nor read:
  - `player_appearance.*` — all 8 keys (`show_spectrum`, `spectrum_style`, `show_progress_bar`, `show_time`, `cover_animation`, `adaptive_accent`, `cover_blur_bg`, `cover_size`): no control, no reader.
  - `services.*` — all 3 (`youtube_enabled`, `soundcloud_enabled`, `vk_enabled`): no control, no reader (the providers are always enabled).
  - `overlay.*` — 9 of 10 (`position`, `opacity`, `scale`, `width`, `height`, `offset_x`, `offset_y`, `show_cover`, `show_controls`); only `mode` has a reader, and that reader is the dead property `SettingsManager.overlay_mode` (`core/settings.py:583-585`), which nothing calls.
  - `general.*` — `language`, `start_minimized`, `check_updates`, `show_notifications`, `gpu_acceleration`: no control, no reader. `app.autostart` is written by `update_autostart` but read by nobody (`general.autostart` is the one that is read, at `core/api.py:2789`).
  - `audio.*` — `quality`, `target_loudness`: no reader; `crossfade_duration` / `crossfade_enabled` / `gapless_playback` are read **only** by the dead properties `crossfade_enabled`, `crossfade_duration`, `gapless` (`core/settings.py:569-581`), which nothing calls — the live consumers are the frontend's `audioSetting()` (`player.js:175-181`), which reads `window.settings.audio.*` directly.
  - `storage.*` — `cache_covers`, `scan_folders`: no control, no reader.
  - `personalization.*` — `explicit_artists`, `preferred_moods`: no control, no reader.
  - `interface.*` — `font_name`, `fullscreen_scale`, `window_scale`, `border_radius`, `font_family` (read only by the dead `SettingsManager.font_family` property), `tabs`, `background`, and the 8 duplicated `theme`/`name`/`accent_color`/`transparency_*`/`glass_*`/`custom_themes` mirrors of the `theme` category: no reader.
  - `theme.*` — `name`, `mode`, `accent_color`, `glass_color_intensity`: read only by dead properties (`theme_name`, `theme_mode`, `accent_color`).
  - `subscription.*` — all 5, **documented** as intentionally unused (`core/settings.py:265-278`).
- **Cause:** the schema accreted entries over time and was never reconciled with the consumers; the accessor properties (`theme_name`, `theme_mode`, `accent_color`, `border_radius`, `crossfade_enabled`, `crossfade_duration`, `gapless`, `overlay_mode`, `font_family`, `volume`) have no callers at all, so they give the *appearance* of a live schema.
- **Trigger conditions:** n/a (structural).
- **User impact:** none directly, but the schema is the contract that `AppApi.get_settings()` mirrors into the frontend, so it inflates the payload and misleads every future reader about what the app actually honours. The dead properties are the most dangerous part: `settings.gapless` / `settings.crossfade_enabled` *look* like the feature switch but are not what the player reads.
- **Evidence:**
  ```python
  # core/settings.py:569-585 — every one of these properties is unused
  @property
  def crossfade_enabled(self) -> bool:
      return self.get("audio", "crossfade_enabled", False)
  @property
  def crossfade_duration(self) -> int:
      return self.get("audio", "crossfade_duration", 3)
  @property
  def gapless(self) -> bool:
      return self.get("audio", "gapless_playback", False)
  @property
  def overlay_mode(self) -> str:
      return self.get("overlay", "mode", "disabled")
  ```
  The live frontend reader is:
  ```javascript
  // ui/web_new_v2/js/player.js:175-181
  function audioSetting(key, fallback) {
      if (window.settings?.audio?.[key] !== undefined) return window.settings.audio[key];
      …
  }
  ```
- **Reproduction / verification:** `wx03_scan.py` enumerated every key against the Python call sites (`get(<cat>, <key>)` / `set(<cat>, <key>, …)` / `get_category(<cat>)`) and the JS call sites (`saveSetting`, `save_setting`, `setupToggle`, `setupSlider`). Result: 47 keys with neither a writer nor a reader, plus the ten properties with zero callers (grep for `\.gapless\b`, `\.crossfade_enabled\b`, `\.overlay_mode\b`, `\.theme_name\b`, `\.accent_color\b`, `\.border_radius\b` across `core/`, `audio/`, `services/`, `utils/`, `main.py` returns only the definitions in `core/settings.py`).
- **Suggested fix:** delete the dead schema entries and the dead accessor properties (or add the missing consumers), and add a test that fails when a `DEFAULT_SETTINGS` key has neither a reader nor a writer — the same idea as `tests/test_keybind_contracts.py`, generalised.
- **Fix side effects:** removing keys from `DEFAULT_SETTINGS` makes `reset_category` stop resetting them and stops them appearing in `get_settings()`; `core/settings.py:265-278` notes that unknown stored keys are preserved on load, so old rows survive — but the `subscription` block must stay for exactly that reason.
- **Discovered by:** A

---

### 3. Clean areas

- **The hotkey mirror (contract #5) holds exactly.** `DEFAULT_SETTINGS["hotkeys"]` (`core/settings.py:134-143`) and `DEFAULT_KEYBINDS` (`ui/web_new_v2/js/hotkeys.js:4-15`) contain the **same 10 ids** with the **same 10 default bindings**. Verified by diffing the parsed tables:
  ```
  only in frontend: []
  only in backend : []
  binding mismatch: {}
  ```
  `tests/test_keybind_contracts.py` pins ids, default values, the absence of the legacy `mute` id, the single dispatcher and the per-action dispatcher branch. **No finding here** — the mirror contract is satisfied.
- **A single-hotkey write does NOT drop the other ids.** `AppApi.save_setting` → `SettingsManager.set` is a **per-key** update (`core/settings.py:413-417`) and the DB write is `INSERT OR REPLACE` on the full key (`core/database.py:2042-2045`, `2074-2078`). Executed against the real `SettingsManager`:
  ```
  set("hotkeys","toggle_mute","KeyQ") → get_category('hotkeys') =
    {play_pause: Space, next_track: Ctrl+ArrowRight, prev_track: Ctrl+ArrowLeft,
     volume_up: Ctrl+ArrowUp, volume_down: Ctrl+ArrowDown, toggle_mute: KeyQ,
     toggle_lyrics: KeyL, toggle_mini: KeyP, like: KeyK, search: Slash}   (10/10)
  ```
  There is **no** partial-write data loss on the hotkey table. (Only the *defaults* are absent from SQLite — they live in the in-memory schema and are merged back on read; the DB-level `get_settings_by_category` therefore shows fewer rows, see F-WX-03-7.)
- **The flush round-trip on the exit paths is sound.** Normal close: `main.py:561 app_core.session.save_session(...)` → `core/session.py:66-68 settings.flush()` → `main.py:575 app_core.cleanup()` → `core/app.py:557-558 _step("settings.flush", self.settings.flush)` **before** `core/app.py:559 db.close()`. Watchdog restart: `main.py:526` and `main.py:536` both call `settings.sync_flush_now()` around `cleanup()` before `os._exit(3)` (`main.py:539`). Tray Quit goes through `window.destroy()` (`core/tray.py:104`) → the normal path. `atexit.register(self.flush)` (`core/settings.py:313`) is the last backstop. **No setting written from the bridge is lost on a clean exit.**
- **`SettingsManager.get()`'s alias handling works.** `queue_autopilot` ↔ `flow_enabled` and `crossfade_duration` ↔ `crossfade_duration_sec` fall back correctly (`core/settings.py:373-392`), and `get("zapret.mode")` dotted form resolves (`core/settings.py:360-365`). `core/settings.py::get` also normalises the legacy string booleans (`core/settings.py:394-399`).
- **`_load_all` deep-copies mutable defaults** (`core/settings.py:334`), so `scan_folders`, `last_queue` and the equalizer `bands` list cannot be mutated in place by a consumer — the "reset all resets nothing" bug is genuinely fixed.
- **The value types on the hotkey and equalizer paths are correct end to end.** `setupToggle` sends a real boolean (`settings.js:652`), `setupSlider` sends a real number (`settings.js:704`), `set_equalizer` sends a real list of numbers (`core/api.py:3180-3190`), and `restoreEq` reads them back with `Number()` (`equalizer.js:314-319`). No `"true"`/`"70"`-as-string mismatch exists on these paths (the general serializer asymmetry is F-WX-03-9).
- **Secrets are masked on both read paths and are not wiped by a masked echo.** `_mask_secrets` (`core/api.py:243-253`) blanks `auth.yandex_token` / `auth.oauth_client_secret` and adds `has_*` flags; `_is_empty_secret_write` (`core/api.py:267-269`) refuses to store a blank secret. Pinned by `tests/test_api_f1_audit.py:36-103`.
- **The write-behind batcher is transactional and count-checked.** `set_settings_batch` writes all rows in one transaction and returns the count (`core/database.py:2049-2082`); `flush` treats a short batch as a failure and re-queues the keys as a group (`core/settings.py:461-483`). The only gap is the missing retry signal (F-WX-03-8).
- **The frontend has a working localStorage fallback layer.** `savedSetting()` (`settings.js:29-33`) prefers the backend and falls back to `nedotify_<cat>_<key>`, which is written on every `saveSetting` (`settings.js:1040`). This is why most UI panels still restore correctly even though the backend schema is incomplete.

---

### 4. Coverage gaps

- **The running app was never launched** (forbidden by the brief) and `~/.nedotify/` was never read, so all findings are derived from source + executable harnesses against the real `core/settings.py` and the real `ui/web_new_v2/js/hotkeys.js`. The F-WX-03-1/2/3 user-visible claims are derived from the code paths, not from an observed session.
- **The `ui/web_new_v2/index.html` control inventory was sampled** (only the ids that appear in `settings.js`/`hotkeys.js`/`feature-controls.js` were checked: `toggle-normalization`, `select-region`, `toggle-crossfade`, `toggle-gapless`, `toggle-particles`, `slider-crossfade-sec`, `select-cache-quota`, `select-auto-download-quota`, `toggle-discord-rpc`, `toggle-queue-autopilot`, `btn-reset-keybinds`). A full sweep of all 2314 index.html lines against all 160 schema keys was not performed, so the "no control" column of the appendix may under-report controls bound directly in `index.html` inline handlers (the project has no inline handlers — all are in `js/**` — but this was not exhaustively proven).
- **`core/tray.py` was read only at line 104**; the full tray menu (which may contain a settings-related action) was not reviewed.
- **`core/database.py` was read only for the settings surface** (`set_setting`, `set_settings_batch`, `get_setting`, `get_settings_by_category`, `get_all_settings`, 2028-2149). The schema/migration code that creates the `settings` table was not reviewed, so a pre-existing row with an unusual encoding (e.g. a hand-edited value) could behave differently from the harnesses' synthetic DB.
- **`services/*` providers were not reviewed** for settings reads beyond the grep sweep; a provider reading `settings.get(...)` through a differently-shaped helper would not have been detected by the `get(<cat>, <key>)` regex.
- **The `equalizer` band-count (`3`/`6`/`10`) restore is racy** (`equalizer.js:192` reads `window.settings.equalizer.mode`, which is only present if the `get_settings()` promise resolved before `initEqualizer()` ran; `main.js:409` vs `main.js:543`). I did not raise this as a finding because I could not demonstrate a deterministic failure — it is a hypothesis only, listed here as a gap.
- **The `session.last_queue` payload** (up to 200 track dicts, `core/session.py:9-37`) is returned to the frontend by `get_settings()` and written into `localStorage['nedotify_cached_settings']` (`main.js:414`) and into one localStorage key per setting (`onboarding.js:188`). I did not measure the resulting localStorage footprint; that is a payload/quota question for Role B.

---

## Appendix A — settings-key coverage table

`Ctl` = a UI control writes it · `R` = read by any code · `W` = written by any code.
"read by any code" includes the frontend (`window.settings.<cat>.<key>`) and the backend.

| Category | Key | Ctl | R | W | Notes |
|---|---|:--:|:--:|:--:|---|
| network | offline_mode | ✗ | ✓ | ✓ | **not returned by `get_settings()` → F-1** |
| app | discord_rpc_enabled | ✓ | ✓ | ✓ | |
| app | autostart | ✗ | ✗ | ✓ | dead duplicate of `general.autostart` |
| general | language | ✗ | ✗ | ✗ | dead |
| general | region | ✓ | ✗ | ✓ | **no consumer → F-4** |
| general | minimize_to_tray | ✓ (onboarding) | ✓ | ✓ | |
| general | start_minimized | ✗ | ✗ | ✗ | dead |
| general | check_updates | ✗ | ✗ | ✗ | dead |
| general | show_notifications | ✗ | ✗ | ✗ | dead |
| general | autostart | ✓ (onboarding) | ✓ | ✓ | |
| general | first_launch_done | ✓ (backend) | ✓ | ✓ | |
| general | gpu_acceleration | ✗ | ✗ | ✗ | dead |
| audio | autoplay | ✓ | ✓ | ✓ | |
| audio | queue_autopilot | ✗ | ✗ | ✗ | **frontend writes `player.queue_autopilot` → F-6** |
| audio | flow_enabled | ✗ | ✗ | ✗ | same |
| audio | quality | ✗ | ✗ | ✗ | dead |
| audio | gapless_playback | ✓ | ✓ (js) | ✓ | backend property `gapless` is dead |
| audio | crossfade_enabled | ✓ | ✓ (js) | ✓ | backend property dead |
| audio | crossfade_duration | ✗ | ✓ (js) | ✗ | alias of `crossfade_duration_sec` |
| audio | crossfade_duration_sec | ✓ | ✓ | ✓ | |
| audio | volume_normalization | ✓ | ✓ (toggle only) | ✓ | **no effect → F-4** |
| audio | target_loudness | ✗ | ✗ | ✗ | hard-coded `-14.0` in `player.js:391` |
| audio | output_device | ✓ | ✓ | ✓ | |
| audio | volume | ✓ | ✓ | ✓ | **never restored into the player → F-2** |
| audio | muted | ✓ | ✓ | ✓ | restored via `is_muted()` |
| overlay | mode | ✗ | ✗ | ✗ | only the dead `overlay_mode` property reads it |
| overlay | position / opacity / scale / width / height / offset_x / offset_y / show_cover / show_controls | ✗ | ✗ | ✗ | dead (9 keys) |
| efficiency | unfocus_enabled / unfocus_fps_limit / unfocus_blur_reduction / unfocus_disable_visualizations / unfocus_disable_animations | ✓ | ✓ | ✓ | |
| optimization | performance_preset / blur_quality / glow_quality / fps_particles / fps_visualizer / fps_ui / resource_bg / resource_particles / resource_visualizers / resource_blur | ✓ | ✓ | ✓ | |
| optimization | limit_state | ✗ | ✗ | ✗ | dead |
| optimization | resource_covers | ✓ (`resource_${res}`) | ✗ | ✓ | no consumer |
| hotkeys | play_pause … search (10 ids) | ✓ | ✓ | ✓ | mirror exact; **F-3** is about the migration, not the mirror |
| storage | cache_size_mb | ✗ | ✗ | ✓ | written by `set_cache_quota` only |
| storage | auto_cache_streams | ✗ | ✓ | ✗ | backend-only, no UI |
| storage | cache_covers | ✗ | ✗ | ✗ | dead |
| storage | scan_folders | ✗ | ✗ | ✗ | dead |
| storage | auto_download_favorites | ✓ | ✓ | ✓ | |
| storage | auto_download_favorites_quota_gb | ✓ | ✓ | ✓ | |
| player_appearance | show_spectrum, spectrum_style, show_progress_bar, show_time, cover_animation, adaptive_accent, cover_blur_bg, cover_size | ✗ | ✗ | ✗ | dead (8 keys) |
| personalization | favorite_genres / artist_aliases / artist_bindings / blocked_artists / disliked_tracks / discovery_ratio / onboarding_completed | ✓/backend | ✓ | ✓ | |
| personalization | explicit_artists, preferred_moods | ✗ | ✗ | ✗ | dead |
| theme | theme / theme_mode / transparency_enabled / transparency_level / glass_blur / custom_themes / custom_bg_image / bg_blur / bg_dim / font_size / font_family / icon_pack / custom_primary / custom_accent | ✓ | ✓ | ✓ | |
| theme | name, mode, accent_color, glass_color_intensity | ✗ | ✗ (dead properties) | ✗ | dead (4 keys) |
| interface | ui_style / macos_mode / macos_glass / macos_blur / macos_font_family / macos_font_size | ✓ | ✓ | ✓ | |
| interface | font_family, font_name, border_radius, fullscreen_scale, window_scale, tabs, background, theme, name, transparency_enabled, transparency_level, glass_blur, glass_color_intensity, accent_color, custom_themes | ✗ | ✗ | ✗ | dead (15 keys; `font_family`/`border_radius` only via dead properties) |
| ui | particles_enabled / particles_count / particles_speed / particles_size / particles_shape / cover_visualizer | ✓ | ✓ | ✓ | |
| equalizer | preamp / bands | ✓ (via `set_equalizer`) | ✓ | ✓ | types correct |
| auth | cookies_file_path / browser_cookies / yandex_token / proxy_url | ✓ | ✓ | ✓ | secrets masked |
| auth | oauth_client_id / oauth_client_secret / oauth_completed | ✗ (inputs disabled) | ✓ | ✗ | `oauth_completed` read by the UI badge |
| services | youtube_enabled, soundcloud_enabled, vk_enabled | ✗ | ✗ | ✗ | dead (3 keys) |
| session | last_track_id / last_position / last_volume / last_queue / last_queue_index / shuffle / repeat | ✗ (backend) | ✓ (backend) | ✓ (backend) | **the frontend reads `shuffle`/`repeat` at the wrong depth → F-2** |
| subscription | key / valid_until / last_validated / is_valid / signature | ✗ | ✗ | ✗ | documented as intentionally unused (`core/settings.py:265-278`) |
| zapret | enabled / auto_start / mode / autoupdate | ✓ | ✓ | ✓ | |
| zapret | custom_args, binary_path | ✓ | ✓ | ✓ | written via `toggle_zapret`, not `save_setting` |

**Summary:** 160 schema keys · 20 categories · **47 keys with neither a control nor a reader** · **0 keys read but never written** except `general.autostart` (written, read) and `app.autostart` (written, never read) · **18 ad-hoc keys written by the UI that are not in the schema** (`player.*`, `storage.cache_quota_gb`, `theme.color_*`, `theme.custom_palette_enabled`, `equalizer.mode`, `personalization.nickname`, `personalization.pinned_track`, `audio.visualizer_style`, `lyrics.lyrics_offset_*`).

---

## Appendix B — hotkey id / binding diff

| id | `DEFAULT_KEYBINDS` (hotkeys.js) | `DEFAULT_SETTINGS["hotkeys"]` (settings.py) | diff |
|---|---|---|---|
| play_pause | `Space` | `Space` | — |
| next_track | `Ctrl+ArrowRight` | `Ctrl+ArrowRight` | — |
| prev_track | `Ctrl+ArrowLeft` | `Ctrl+ArrowLeft` | — |
| volume_up | `Ctrl+ArrowUp` | `Ctrl+ArrowUp` | — |
| volume_down | `Ctrl+ArrowDown` | `Ctrl+ArrowDown` | — |
| toggle_mute | `KeyM` | `KeyM` | — |
| toggle_lyrics | `KeyL` | `KeyL` | — |
| toggle_mini | `KeyP` | `KeyP` | — |
| search | `Slash` | `Slash` | — |
| like | `KeyK` | `KeyK` | — |

**ids only on one side: none. Differing defaults: none.** Contract #5 (the mirror) is **satisfied**.
The defects around the hotkey table are (a) the unconditional `LEGACY_DEFAULT_MIGRATION` rewrite (F-3) and (b) the DB-level `get_settings_by_category` showing only the stored rows (F-7).

`LEGACY_DEFAULT_MIGRATION` (hotkeys.js:72-78) — the entries that can hit a **user-chosen** binding:

| legacy value | rewritten to | risk |
|---|---|---|
| `Ctrl+M` | `KeyM` | collides with the `toggle_mute` default |
| `Ctrl+L` | `KeyK` | **collides with the `like` default → `like` becomes dead** |
| `Ctrl+F` | `Slash` | collides with the `search` default |
| `Ctrl+KeyM` | `KeyM` | collides with the `toggle_mute` default |
| `Ctrl+KeyK` | `KeyK` | collides with the `like` default |
| `Ctrl+O`, `Ctrl+KeyO` | `null` | **the action id is deleted → no binding at all** |

---

## Appendix C — value-type round-trip list

| key / path | UI sends | stored as | read back as | verdict |
|---|---|---|---|---|
| `audio.crossfade_enabled` (toggle) | `boolean` | `true`/`false` (JSON) | `bool` | ✓ |
| `audio.crossfade_duration_sec` (slider) | `number` | `3` (JSON) | `int` | ✓ |
| `ui.particles_count` / `speed` / `size` (sliders) | `number` | JSON number | `int`/`float` | ✓ |
| `theme.font_family` (select) | `string` | raw text | `str` | ✓ |
| `hotkeys.*` (combo) | `string` | raw text | `str` | ✓ |
| `storage.auto_download_favorites_quota_gb` | `number` (`parseInt`) | JSON number | `int` | ✓ |
| `storage.cache_quota_gb` | `number` (`parseInt`) | JSON number | `int` | ✓ (key not in schema → F-6) |
| `equalizer.bands` | `array<number>` | JSON array | `list[float]` | ✓ |
| `equalizer.preamp` | `number` | JSON number | `float`/`int` | ✓ |
| `personalization.pinned_track` | `object` | JSON object | `dict` | ✓ |
| `theme.bg_blur` / `theme.bg_dim` — **workshop path** | **`string`** (`input.value`) | raw text (`"12"`) | `int` (`json.loads("12")`) | ✗ **type changes across the round trip → F-9** |
| `theme.bg_blur` / `theme.bg_dim` — slider path | `number` | JSON number | `int` | ✓ |
| any text setting whose content is `"true"` / `"false"` / `"12"` / `"null"` | `string` | raw text | **`bool` / `int` / `None`** | ✗ **type changes → F-9** |
| `network.offline_mode` | `boolean` (bridge) | `true` (JSON) | `bool` | ✓ in the DB — but the category is **not returned** → F-1 |
| `audio.volume` | `number` (`set_volume`) | JSON number | `int` | ✓ in the DB — but the frontend reads `settings.volume` (top level) → **F-2** |
| `session.shuffle` / `session.repeat` | backend-written | JSON | `bool` / `str` | ✓ in the DB — but the frontend reads `settings.shuffle` (top level) → **F-2** |
