## AREA WN-14 — Settings manager & hotkey table — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read | What I looked at |
|---|---|---|
| `core/settings.py` | 1–589 (full) | `get_system_region`, `DEFAULT_SETTINGS` (all 21 categories), `SettingsManager.__init__`, `_load_all`, `_is_known_category`, `get`, `set`, `sync_flush_now`, `flush`, `_write_batch`, `_wake_writer`, `_writer_loop`, `get_category`, `reset_category`, `reset_all`, all 11 typed accessors |
| `ui/web_new_v2/js/hotkeys.js` | 1–256 (full) | `DEFAULT_KEYBINDS`, `parseKeyEventCombo`, `initHotkeys` (defaults → localStorage → legacy migrations → backend apply), the global `keydown` listener (capture branch, input guard, modal guard, F11, media keys, dispatch loop), `executeHotkeysAction` |
| `core/database.py` | 2028–2132 | `_serialize_setting`, `set_setting`, `set_settings_batch`, `get_setting`, `get_settings_by_category`, `get_all_settings` (the settings persistence contract) |
| `core/api.py` | 236–285, 440–514, 1840–1900, 1940–2000, 2915–2975 | `_mask_secrets`/`_bridge_write_error`/`_is_empty_secret_write`, `cleanup`, `get_setting`, `set_setting`, `set_volume`/`get_volume`/`toggle_mute`, `get_settings`, `save_setting`, `get_settings_by_category`, `update_setting` |
| `core/app.py` | 520–586 | `AppCore.cleanup` — the shutdown flush/DB-close order |
| `main.py` | 308–337, 385–444, 495–584 | session restore, `on_loaded` autoplay, `_startup_watchdog` (`sync_flush_now` → `cleanup` → `sync_flush_now` → `os._exit(3)`), the normal exit path |
| `core/session.py` | 1–96 (full) | `save_session` (writes 7 settings + `flush()`), `restore_session`, `should_autoplay` |
| `ui/web_new_v2/js/settings.js` | 1025–1064, 1115–1274 | `saveSetting`, `initKeybinds`, the reset-keybinds button, `formatKeyName`, `renderKeybindsList` |
| `ui/web_new_v2/js/main.js` | 385–444 | the settings bootstrap order (`initHotkeys` after the async `get_settings`) |
| `ui/web_new_v2/js/feature-controls.js` | 1–60 | `applyOfflineState` (the `window.settings.network` shape) |
| `ui/web_new_v2/js/utils.js` | 335–369 | `isFocusInsideModalTrap` (the modal guard used by the hotkey dispatcher) |
| `ui/web_new_v2/js/player.js` | 30–59, 1190–1219 | `scheduleVolumeRpc`/`set_volume`, `adjustVolume` clamping |
| `tests/test_keybind_contracts.py` | 1–204 (full) | the existing mirror pin |
| `tests/test_settings_flush.py` | 1–229 (full) | the existing flush-durability pin |
| `tests/test_settings_manager.py` | 138–196, 428–477 (grep-level) | the alias and accessor expectations |

**Not opened:** the whole `android/` subtree (out of scope).

**Callees traced into other areas**

- `core/database.py` → WN-12 (SQLite persistence layer). The settings rows live in the `settings` table; `_serialize_setting` decides the on-disk format of every value.
- `core/api.py` → WN-08 (bridge settings surface). `get_settings`/`save_setting`/`get_setting`/`set_setting` are the JS bridge; their misuse is attributed to WN-08, not here.
- `core/app.py::cleanup` / `main.py` → WN-02 / WN-01 (lifecycle). I only traced the flush ordering.
- `ui/web_new_v2/js/settings.js` → WN-30 (UI settings). The keybind list UI is shared between WN-14 and WN-30; the findings below are about the capture/apply logic that the brief put in my scope (`js/hotkeys.js`).
- `core/session.py` → WN-02 (session persist/restore).

**Verification tooling used (scratch files only, under `%TEMP%`)**

- `%TEMP%\opencode\wn14_probe.py` … `wn14_probe4.py` — drive `core/settings.py` against fake DBs (empty / partial-write / always-fail / unknown-category) and the real `DatabaseManager._serialize_setting`.
- `%TEMP%\opencode\wn14_hotkeys_harness.js` — Node harness that slices the **verbatim** capture branch and dispatch loop out of `ui/web_new_v2/js/hotkeys.js` at runtime and drives them with synthetic `KeyboardEvent`s.
- `pytest tests/test_keybind_contracts.py -k "not format_key_name"` → **7 passed** (the mirror pin is green today).

---

### 2. Findings

#### F-WN-14-1  [P1] — A hotkey can never be re-bound to a modifier combination: the first modifier keydown cancels the capture

- **File:** `ui/web_new_v2/js/hotkeys.js:133-147` (capture branch), `ui/web_new_v2/js/hotkeys.js:35-53` (`parseKeyEventCombo`), `ui/web_new_v2/js/hotkeys.js:47-49` (modifier-only ignore list), `ui/web_new_v2/js/settings.js:1251-1258` (the button that arms the capture)
- **Confirmed:** yes
- **Description:** While the user is recording a binding, a single `keydown` ends the recording — *whether or not a combo was captured*. `parseKeyEventCombo` returns `null` for a standalone modifier, and the branch then unconditionally executes `listeningKeybindId = null`. Since the browser delivers the modifier's `keydown` **before** the non-modifier key of the chord, the recording is already over by the time the user presses `Ctrl+K`. The binding is never written, nothing is reported to the user, and the Settings row silently keeps its old value.
- **Cause:** the capture branch treats "no combo parsed" and "combo captured" identically — one `keydown` = one attempt — instead of waiting for a non-modifier key. The modifier-only early return in `parseKeyEventCombo` is correct on its own; the caller discards the "still waiting" state.
- **Trigger conditions:** the user clicks the "record" button on any hotkey row and presses **any** chord containing Ctrl / Alt / Shift / Win. Every default in the table except `play_pause`, `toggle_mute`, `toggle_lyrics`, `toggle_mini`, `like` is a Ctrl-modified combo, so the most natural thing a user tries (re-bind "next track" to something else) fails.
- **User impact:** the Settings → Hotkeys screen silently refuses to record any modifier combo. The user sees the button flip back to the previous binding with no error, so the app looks broken; the backend is never told, so `hotkeys.<id>` in the DB is unchanged and the old binding keeps working.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/hotkeys.js:133-147
  if (listeningKeybindId) {
      e.preventDefault();
      e.stopPropagation();
      const combo = parseKeyEventCombo(e);
      if (combo && e.code !== 'Escape') {
          activeKeybinds[listeningKeybindId] = combo;
          saveKeybindsToStorage(activeKeybinds);
          if (window.pywebview?.api?.save_setting) {
              window.pywebview.api.save_setting(listeningKeybindId, combo, 'hotkeys');
          }
      }
      listeningKeybindId = null;   // <-- unconditional: a lone Ctrl keydown ends the recording
      if (window.renderKeybindsList) window.renderKeybindsList();
      return;
  }
  ```
  ```js
  // ui/web_new_v2/js/hotkeys.js:47-49
  if (['ControlLeft', 'ControlRight', 'AltLeft', 'AltRight', 'ShiftLeft', 'ShiftRight',
       'MetaLeft', 'MetaRight', 'Control', 'Alt', 'Shift', 'Meta'].includes(keyName)) {
      return null;
  }
  ```
- **Reproduction / verification:** run the Node harness `%TEMP%\opencode\wn14_hotkeys_harness.js` (it extracts the capture branch verbatim from the repo file). Output:
  ```
  == TEST 1: rebinding to a MODIFIER combo (Ctrl+Shift+K) ==
  after Ctrl keydown : listeningKeybindId = null
  after KeyK keydown : activeKeybinds.like = "KeyK"
  expected (if capture worked)          = "Ctrl+Shift+KeyK"
  RESULT: *** BUG: combo NOT recorded ***
  == TEST 1b: control - rebinding to a PLAIN key (Z) ==
  activeKeybinds.like = "KeyZ"
  ```
  Manual repro: Settings → Hotkeys → click the "record" button on "Нравится трек" → press `Ctrl+K` → the button shows the old binding, nothing is saved.
- **Suggested fix:** keep the recording armed while `parseKeyEventCombo` returns `null` for a modifier-only press (only clear `listeningKeybindId` on `Escape`, on a successful capture, or on the outside-pointerdown cancel); alternatively accumulate the pressed modifiers and build the combo from them when the non-modifier key arrives.
- **Fix side effects:** the recording state must then also be cancelled explicitly on `Escape` and on window blur, otherwise a cancelled modifier press leaves the UI in "Нажмите клавишу..." forever. `keydown` auto-repeat of the modifier must also be ignored.
- **Discovered by:** A

#### F-WN-14-2  [P2] — Duplicate hotkey bindings are silently accepted; the second action to claim a key becomes dead

- **File:** `ui/web_new_v2/js/hotkeys.js:186-196` (dispatch loop), `ui/web_new_v2/js/hotkeys.js:200-256` (`executeHotkeysAction`), `ui/web_new_v2/js/hotkeys.js:138-142` (rebind write), `ui/web_new_v2/js/settings.js:1136-1139` (reset writes all 10 defaults), `core/settings.py:401-418` (`set` — no uniqueness check), `core/api.py:2940-2953` (`save_setting` — no uniqueness check)
- **Confirmed:** yes
- **Description:** Nothing anywhere detects that two actions are bound to the same key. The dispatcher iterates `activeKeybinds` in insertion order and `break`s on the **first** match, so the action that comes later in `DEFAULT_KEYBINDS` order silently never fires. The backend happily stores both rows (`hotkeys.toggle_mute` and `hotkeys.like` can both be `KeyM`), so the collision survives a restart and is re-applied from the DB on every launch.
- **Cause:** the table is keyed by *action*, with no inverse index (key → action) and no conflict check at capture time or at persistence time. `break` on first match makes the collision deterministic but silent.
- **Trigger conditions:** the user binds an action to a key that another action already owns (e.g. "Нравится трек" → `M`, which is `toggle_mute`'s default), or the reset button is used after a legacy migration produced a duplicate (see F-WN-14-3).
- **User impact:** one hotkey stops working entirely and nothing tells the user which one or why. The Settings list shows both rows with the same key, so the UI looks self-consistent while one action is unreachable.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/hotkeys.js:186-196
  for (const [actionId, key] of Object.entries(activeKeybinds)) {
      const isMatch = (key === pressedCombo) ||
                      (key === 'Space' && (pressedCombo === 'Space' || e.code === 'Space' || e.key === ' '));
      if (isMatch) {
          e.preventDefault();
          if (e.repeat && !REPEATABLE_ACTIONS.has(actionId)) break;
          executeHotkeysAction(actionId);
          break;            // <-- first match wins, the other action is dead
      }
  }
  ```
  ```js
  // ui/web_new_v2/js/settings.js:1136-1139  (reset writes every default with no conflict check)
  DEFAULT_KEYBINDS.forEach(kb => {
      activeKeybinds[kb.id] = kb.defaultKey;
      saveSetting(kb.id, kb.defaultKey, 'hotkeys');
  });
  ```
- **Reproduction / verification:** Node harness `%TEMP%\opencode\wn14_hotkeys_harness.js`:
  ```
  == TEST 2: duplicate binding - "like" rebound to the mute key ==
  action fired for KeyM: [ 'toggle_mute' ] (only the FIRST match in iteration order runs)
  iteration order: play_pause, next_track, prev_track, volume_up, volume_down,
                   toggle_mute, toggle_lyrics, toggle_mini, search, like
  ```
  Manual repro: Settings → Hotkeys → record "Нравится трек" as `M` → press `M` → the mute button is clicked, the track is never liked. Restart the app: the collision is still there (the backend stores both).
- **Suggested fix:** build a key → action index when the binding set is assembled and refuse/deduplicate at capture time (and when applying the backend table): either reject the new binding with a visible message, or move the action to the end of the iteration order and report the reassignment.
- **Fix side effects:** a key-index changes the dispatch semantics for the pre-existing `Space` special case (`key === 'Space' && …`), which must keep matching `e.code === 'Space'`; the "hold to repeat" rule (`REPEATABLE_ACTIONS`) also depends on the per-action iteration.
- **Discovered by:** A

#### F-WN-14-3  [P2] — The legacy migration maps `Ctrl+L` → `KeyK`, manufacturing a duplicate `KeyK` binding that kills the `like` hotkey for upgrading users

- **File:** `ui/web_new_v2/js/hotkeys.js:72-78` (`LEGACY_DEFAULT_MIGRATION`), `ui/web_new_v2/js/hotkeys.js:86-98` (the migration loop), `ui/web_new_v2/js/hotkeys.js:186-196` (first match wins)
- **Confirmed:** yes
- **Description:** The legacy-format migration table sends `Ctrl+L` to **`KeyK`** — the `like` action's default — while `Ctrl+KeyK` (the legacy `like` default) also maps to `KeyK`. Every other entry in the table maps a legacy `<Ctrl>+<letter>` to the same letter for the *same* action (`Ctrl+M`→`KeyM`, `Ctrl+F`→`Slash`), so `Ctrl+L`→`KeyL` is the only consistent reading; `Ctrl+L`→`KeyK` moves the **lyrics** action onto the **like** action's key. A user upgrading from a build whose backend default was `Ctrl+L` ends up with `toggle_lyrics = KeyK` and `like = KeyK` — a duplicate, and because `toggle_lyrics` comes earlier in the iteration order, `like` is the action that dies.
- **Cause:** a typo in the migration table (`KeyK` instead of `KeyL`) that the migration table's own convention makes unambiguous.
- **Trigger conditions:** the user has a `nedotify_keybinds` entry (localStorage) holding the legacy backend default `Ctrl+L` for `toggle_lyrics` — exactly the "old backend-default formats that used to leak into storage" the comment above the table describes.
- **User impact:** after the upgrade, the "Нравится трек" hotkey stops working (the key now toggles lyrics), and the migration is written straight back to localStorage, so the state is sticky.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/hotkeys.js:72-78
  const LEGACY_DEFAULT_MIGRATION = {
      'Ctrl+Right': 'Ctrl+ArrowRight', 'Ctrl+Left': 'Ctrl+ArrowLeft',
      'Ctrl+Up': 'Ctrl+ArrowUp', 'Ctrl+Down': 'Ctrl+ArrowDown',
      'Ctrl+KeyM': 'KeyM', 'Ctrl+KeyK': 'KeyK',
      'Ctrl+M': 'KeyM', 'Ctrl+L': 'KeyK', 'Ctrl+F': 'Slash',
      'Ctrl+KeyO': null, 'Ctrl+O': null
  };
  ```
- **Reproduction / verification:** Node harness `%TEMP%\opencode\wn14_hotkeys_harness.js`:
  ```
  legacy 'Ctrl+L'   migrates to: "KeyK"
  legacy 'Ctrl+KeyK' migrates to: "KeyK"
  ```
  Manual repro: put `{"toggle_lyrics":"Ctrl+L","like":"Ctrl+KeyK"}` into `localStorage['nedotify_keybinds']`, reload → both actions are `KeyK` → pressing `K` toggles lyrics and the like action never fires.
- **Suggested fix:** map `'Ctrl+L'` to `'KeyL'` (the lyrics action's own default), consistent with `Ctrl+M`→`KeyM`.
- **Fix side effects:** a user who already ran the broken migration has `toggle_lyrics = KeyK` stored in localStorage; the fix does not repair that, so a one-off normalisation (e.g. treat a stored `toggle_lyrics === 'KeyK'` as the legacy artifact) may be needed — but that would collide with a deliberate user choice, so it must be distinguished from the broken migration.
- **Discovered by:** A

#### F-WN-14-4  [P2] — The `/` key is matched by `e.key`, so the combo for `/` is layout-dependent and the default `search` binding (`Slash`) cannot fire on layouts where `/` needs Shift

- **File:** `ui/web_new_v2/js/hotkeys.js:42-44`, `ui/web_new_v2/js/hotkeys.js:35-53`, `ui/web_new_v2/js/hotkeys.js:13` (`search` default `'Slash'`), `core/settings.py:143` (`"search": "Slash"`)
- **Confirmed:** yes (code-level); the per-layout impact is a hypothesis (see below)
- **Description:** Every other key is identified by `e.code`, which is layout-independent. `/` is special-cased: the `e.key === '/'` test **overwrites** `e.code`, so the character `/` always becomes the token `Slash` regardless of which physical key produced it. On a layout where `/` is only reachable as Shift + another key, the parsed combo becomes `Shift+Slash`, which does not equal the default `Slash` — so the `search` hotkey is dead and the user cannot record a working replacement (F-WN-14-1 blocks modifier combos anyway).
- **Cause:** the special case mixes two different key-identification schemes (`e.code` for everything else, `e.key` for `/` and Space) in one function.
- **Trigger conditions:** a keyboard layout where the `/` character is not the unshifted output of the physical `Slash` key — e.g. German QWERTZ (`/` is Shift+7, the physical Slash key gives `-`/`_`) or any layout where `/` lives on another key. Russian ЙЦУКЕН (the app's default language is `ru`) keeps `/` on the physical Slash key, so it is **not** affected.
- **User impact:** on the affected layouts the "Фокус на поиск" hotkey never fires, and the Settings row shows a binding the user cannot reproduce. The user must use the mouse.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/hotkeys.js:42-44
  if (keyName === ' ' || e.key === ' ') keyName = 'Space';
  if (keyName === '/' || e.key === '/') keyName = 'Slash';   // <-- e.code is discarded here
  ```
- **Reproduction / verification:** Node harness `%TEMP%\opencode\wn14_hotkeys_harness.js`, TEST 4:
  ```
  code="Slash"  key="/"      shift=false -> combo = "Slash"
  code="Digit7" key="/"      shift=true  -> combo = "Shift+Slash"
  ```
  Confirms the asymmetry: the *same character* `/` yields two different combo strings depending on which physical key produced it, and only the first one matches the default. To confirm the German-layout case on a real machine: switch the Windows input to German (QWERTZ), press the `/` key (Shift+7) and read `e.code`/`e.key` in the WebView2 devtools — `e.key === '/'`, `e.code === 'Digit7'`, so the combo is `Shift+Slash` ≠ `Slash`.
- **Suggested fix:** identify the `/` key by `e.code` only (`Slash`), and — if the `/` character must stay reachable — add it as an *alias* (`e.key === '/'` accepted in the matcher) rather than rewriting the combo token.
- **Fix side effects:** users who already recorded a `Shift+Slash` binding (or a `Slash` binding on an affected layout) would need their stored combo migrated; changing the token format invalidates stored hotkey rows in the DB (`hotkeys.search`), which the frontend applies verbatim.
- **Discovered by:** A

#### F-WN-14-5  [P2] — A failed flush is not retried on the writer's own schedule: the pending keys sit in `_dirty` until the next `set()` or process exit

- **File:** `core/settings.py:443-483` (`flush`), `core/settings.py:520-530` (`_writer_loop`), `core/settings.py:508-518` (`_wake_writer`)
- **Confirmed:** yes
- **Description:** When a batch write fails, `flush()` puts the keys back into `_dirty` (correct) but does **not** re-arm the writer's wake event. The writer loop is `wait() → clear() → sleep(0.5) → flush()`; after its own flush fails it loops back to `wait()`, which blocks until the *next* `set()` call. So a transient write failure is retried exactly once by the writer (its own next tick, only if the failure happened on a main-thread flush) and then never again until some other setting changes.
- **Cause:** the retry signal is the same `Event` that `set()` uses to wake the writer; the failure path restores the pending set without setting it.
- **Trigger conditions:** any transient DB write error — the SQLite file is locked, the disk is full, the DB connection was closed by a concurrent `db.close()`, a batch contains one value that `json.dumps` cannot serialise (which makes the whole batch fail, see `core/database.py:2060-2067`).
- **User impact:** the setting is silently not persisted (only a line in `~/.nedotify/logs/app.log`); if the user closes the app in a way that skips the atexit flush, or the app is killed, the change is lost with no visible error.
- **Evidence:**
  ```python
  # core/settings.py:472-483
  if written < len(payload):
      with self._lock:
          self._dirty.update(pending)      # keys restored ...
      if error is not None:
          logger.error(f"Settings flush failed, {len(pending)} keys still pending: {error}")
  ```
  ```python
  # core/settings.py:520-530  (no re-arm after a failure)
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
- **Reproduction / verification:** probe `%TEMP%\opencode\wn14_probe4.py` (DB whose `set_settings_batch` always raises), one `set()`, 3 s of observation:
  ```
  A) one set(), DB always failing -> batch attempts in 3s: 1
     dirty: {('general', 'language')}
     => writer retries on its own tick: False
  B) main-thread flush failed; batch attempts after 2.5 more s: 1
     => the writer retried without a new set(): True
  ```
  i.e. the writer only retried because a *main-thread* flush had failed and left the writer's own tick as the next attempt. In case A the writer gave up after one attempt.
- **Suggested fix:** re-arm the wake event when `flush()` restores pending keys (`self._writer_wake.set()`), with a bounded back-off so a permanently failing DB does not spin.
- **Fix side effects:** an always-failing DB would then retry on a timer — it needs a back-off/attempt cap, otherwise the log fills with one error line per interval.
- **Discovered by:** A

#### F-WN-14-6  [P3] — `get_category()` returns a shallow copy: mutating a nested dict/list edits the live cache without marking it dirty, so the change is never persisted

- **File:** `core/settings.py:532-535` (`get_category`), `core/settings.py:367-372` (`get` returns the live object), `core/api.py:2922-2938` / `core/api.py:2958-2959` (the callers)
- **Confirmed:** yes
- **Description:** `get_category` copies only the top level (`dict.copy()`), so nested containers are shared with the live cache: `interface.tabs` (a dict), `interface.background` (a dict), `equalizer.bands` (a list), `storage.scan_folders` (a list), `session.last_queue` (a list), `personalization.artist_aliases`/`artist_bindings` (dicts). A caller that edits one of them in place changes the in-memory value without ever calling `set()`, so the key is not in `_dirty`, is not written, and the cache silently diverges from the DB (until the next restart).
- **Cause:** the copy is one level deep, while `_load_all` deliberately `deepcopy`s the defaults into the cache — the two halves of the class disagree about ownership of nested state.
- **Trigger conditions:** any Python consumer that mutates a nested value obtained from `get_category()` / `get()`. No such consumer exists in the current tree (the bridge only serialises the result to JSON), so this is a latent trap rather than an active bug.
- **User impact:** none today; the moment a Python consumer edits a nested setting in place, the user's change is accepted by the UI and then silently reverted on restart.
- **Evidence:**
  ```python
  # core/settings.py:532-535
  def get_category(self, category: str) -> Dict[str, Any]:
      """Get all settings in a category."""
      with self._lock:
          return self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()
  ```
  Probe output:
  ```
  cache interface.tabs after mutating returned dict: {'show_home': False, 'show_library': True, ...}
  cache interface.background.color: #000000
  dirty? set()
  db interface.tabs written? None
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe.py`, section 7 — mutate `sm.get_category("interface")["tabs"]["show_home"]` and observe that `sm._cache["interface"]["tabs"]` changed while `sm._dirty` stayed empty and nothing was written to the DB.
- **Suggested fix:** return a deep copy from `get_category` (and/or make the cache the only owner and hand out copies of nested values from `get`).
- **Fix side effects:** a deep copy on every `get_category` call costs a little on large categories (`session.last_queue` can hold 200 tracks, `personalization.disliked_tracks` up to 1000 entries) — `get_category` is called on every `get_settings()` bridge call.
- **Discovered by:** A

#### F-WN-14-7  [P3] — `get()` hands out the live mutable object stored in the cache

- **File:** `core/settings.py:367-372`, `core/settings.py:334` (the `deepcopy` of the defaults)
- **Confirmed:** yes
- **Description:** `get()` returns `self._cache[category][key]` directly, so for a list/dict setting the caller receives the very object the cache owns. In-place mutation changes the cache without dirtying it — the same class of defect as F-WN-14-6, one call level down.
- **Cause:** no ownership rule for the values read back out of the cache; the `deepcopy` protection applied to `DEFAULT_SETTINGS` was not applied to the read path.
- **Trigger conditions:** a caller doing `settings.get("equalizer", "bands").append(x)` or `settings.get("storage", "scan_folders").append(p)`. No such caller exists in the current tree (`core/api.py:3189` writes the whole list back through `set()`).
- **User impact:** none today — latent.
- **Evidence:**
  ```python
  # core/settings.py:368-370
  with self._lock:
      if category in self._cache and key in self._cache[category]:
          val = self._cache[category][key]     # <- the live object
  ```
  Probe output:
  ```
  same object as cache? True
  cache equalizer.bands now: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 99]
  DEFAULT_SETTINGS equalizer.bands (must be untouched): [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
  ```
  (Note the positive part: `DEFAULT_SETTINGS` itself is *not* corrupted — the `deepcopy` at `core/settings.py:334` works.)
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe.py`, section 8.
- **Suggested fix:** copy list/dict values on the way out of `get()` (or document the cache as the sole owner and require `set()` for every mutation).
- **Fix side effects:** a copy per `get()` on hot paths (the equalizer bands are read per audio frame on the JS side, but on the Python side `get()` is not on a hot path).
- **Discovered by:** A

#### F-WN-14-8  [P3] — The `set()` overloads are ambiguous and can create phantom settings rows (bridge-reachable)

- **File:** `core/settings.py:401-418` (`set`), `core/settings.py:344-349` (`_is_known_category`), `core/api.py:1871-1897` (`set_setting`)
- **Confirmed:** yes
- **Description:** `set(category, key=None, value=None)` has two mutually incompatible interpretations and no guard:
  - `set("audio.volume", None)` — a dotted key with a `None` value — fails the dotted test (`key is not None` is false), falls through, and creates a **phantom cache category** literally named `"audio.volume"` with a key `None`, then writes a DB row `audio.volume.None`.
  - `set("hotkeys", "Space")` — a two-argument call on a non-dotted category — writes `hotkeys.Space = None` instead of failing.
  `_is_known_category` is only used to disambiguate the *dotted read* path (`core/settings.py:360`); it never rejects a write, so any category name — including a typo — is accepted and persisted.
- **Cause:** the overload is detected by inspecting the argument *types* (`value is None and key is not None`) rather than by an explicit form, and the write path has no category validation.
- **Trigger conditions:** `window.pywebview.api.set_setting("audio.volume", null)` reaches `AppApi.set_setting` with `key=None, value=None` → the `else` branch → `settings.set("audio.volume", None, None)` → the phantom row. Any 2-argument Python `set(category, value)` call does the same.
- **User impact:** phantom rows accumulate in the `settings` table and the phantom category makes `_is_known_category("audio.volume")` return `True`, which in turn **disables the dotted-read path** for that key (`get("audio.volume")` returns `None` instead of the volume). No crash; the damage is silent DB pollution.
- **Evidence:**
  ```python
  # core/settings.py:408-416
  if "." in category and value is None and key is not None:
      cat, k = category.split(".", 1)
      val = key
      return self.set(cat, k, val)

  with self._lock:
      if category not in self._cache:
          self._cache[category] = {}
      self._cache[category][key] = value
  ```
  Probe output:
  ```
  phantom cache categories: ['audio.volume']
  db rows: [('audio.volume.None', None, 'audio.volume')]
  get('audio','volume') still: 70
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe3.py` — `sm.set("audio.volume", None); sm.flush()` produces the row above. From the app: `await pywebview.api.set_setting("audio.volume", null)`.
- **Suggested fix:** make the dotted form explicit (`set(category, key, value)` only, with a separate `set_dotted`), reject a `None` key, and validate the category against `DEFAULT_SETTINGS` before accepting a write.
- **Fix side effects:** rejecting unknown categories would break the current "unknown keys are preserved, not dropped" contract that `core/settings.py:265-271` relies on for old `settings.json` files; the check should therefore be on the *category*, not on the key.
- **Discovered by:** A

#### F-WN-14-9  [P3] — A `None` value is stored as NULL and never round-trips: it comes back as an empty string

- **File:** `core/settings.py:401-418` (`set`), `core/database.py:2028-2034` (`_serialize_setting`), `core/database.py:2084-2098` / `core/database.py:2117-2132` (`get_setting` / `get_all_settings`), `core/session.py:57` (`last_track_id`), `core/session.py:92-96` (`should_autoplay`)
- **Confirmed:** yes
- **Description:** `set(category, key, None)` stores `None` in the cache (it is neither "delete" nor "store null" — it is simply stored). The DB serialiser maps `None` to the empty string `""`, and the reader then returns the raw string `""` (because `json.loads("")` raises). So the value changes type across a restart: `None` → `""`.
- **Cause:** `_serialize_setting` has no representation for NULL (the column is `TEXT NOT NULL`-ish in practice) and the reader's fallback returns the empty string verbatim.
- **Trigger conditions:** any setting written with `None` — `session.last_track_id` is written as `None` whenever the app closes with no track (`core/session.py:57`).
- **User impact:** after a restart `session.last_track_id` is `""` instead of `None`. The one consumer, `SessionManager.should_autoplay` (`core/session.py:95`), tests `last_track_id is not None`, which is **True** for `""` — so `should_autoplay` can report True for "no track". The user-visible effect is currently masked by the extra `and app_core.engine.queue.current_track` guard in `main.py:396`, but the predicate itself is wrong.
- **Evidence:**
  ```python
  # core/database.py:2028-2034
  @staticmethod
  def _serialize_setting(value: Any) -> str:
      if isinstance(value, (dict, list, bool, int, float)):
          return json.dumps(value)
      if value is None:
          return ""            # <- None becomes ""
      return str(value)
  ```
  ```python
  # core/session.py:92-96
  @property
  def should_autoplay(self) -> bool:
      """Check if autoplay is enabled and there's a track to resume."""
      autoplay = self.settings.get("audio", "autoplay", False)
      last_track_id = self.settings.get("session", "last_track_id")
      return autoplay and last_track_id is not None      # "" is not None -> True
  ```
  Probe output:
  ```
  value=None  -> stored=''  -> reloaded=('RAW-STRING', '')
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe3.py` — `DatabaseManager._serialize_setting(None)` → `''`; `json.loads('')` raises → the DB reader returns `''`. Write `session.last_track_id = None`, restart, read `settings.get("session","last_track_id")` → `''`.
- **Suggested fix:** serialise `None` as the JSON literal `null` (`json.dumps(None)`), so it round-trips as `None`; or treat a `None` write as a delete of the row and make `should_autoplay` test for a non-empty id.
- **Fix side effects:** existing rows already stored as `""` would keep loading as `""`; `json.dumps(None)` changes the on-disk representation, so the reader must accept both.
- **Discovered by:** A

#### F-WN-14-10  [P3] — The typed accessors do not validate: `volume` is not clamped, `border_radius` raises `ValueError`, and `crossfade_duration` reads a key the UI never writes

- **File:** `core/settings.py:551-589` (the accessors), `core/settings.py:62` (`region`), `core/api.py:1956-1962` (`set_volume`/`get_volume`), `ui/web_new_v2/js/player.js:1479` and `ui/web_new_v2/js/settings.js:135` (the frontend writes `crossfade_duration_sec`)
- **Confirmed:** yes
- **Description:** Three separate issues in the accessor block:
  1. `volume` returns the stored value verbatim — 150 or −20 are returned as-is; `AppApi.set_volume` (`core/api.py:1956-1958`) documents "Set playback volume (0-100)" but performs no clamping, so an out-of-range value is persisted and handed back by `get_volume()`.
  2. `border_radius` does `int(self.get(...))`, which raises `ValueError` on a non-numeric stored value instead of falling back to the default.
  3. `crossfade_duration` reads `audio.crossfade_duration`, but the UI slider writes and the player reads `audio.crossfade_duration_sec` (`ui/web_new_v2/js/settings.js:135`, `ui/web_new_v2/js/player.js:1479`). The two keys are independent, so the Python property keeps reporting the default `3` forever.
- **Cause:** the accessors are thin `get()` wrappers with no coercion or range check; `crossfade_duration` and `crossfade_duration_sec` are two independent schema keys rather than one key with an alias (the alias branches in `get()` at `core/settings.py:383-392` are unreachable for the `audio` category, because `_load_all` always puts **both** keys into the cache — the alias only fires for categories outside `DEFAULT_SETTINGS`, which is what `tests/test_settings_manager.py:138-160` pins).
- **Trigger conditions:** an out-of-range or non-numeric value in the `settings` table (hand-edited DB, a future writer that forgets to clamp, an older build that stored a string).
- **User impact:** today only latent — the frontend clamps the volume itself (`ui/web_new_v2/js/player.js:1198`, `Math.max(0, Math.min(100, …))`), so the out-of-range value only reaches the DB, and `border_radius` / `crossfade_duration` have no Python consumer. But `int(...)` raising inside a property is a crash-shaped failure waiting for a caller.
- **Evidence:**
  ```python
  # core/settings.py:562-575
  @property
  def volume(self) -> int:
      return self.get("audio", "volume", 70)          # no clamp
  ...
  @property
  def border_radius(self) -> int:
      return int(self.get("interface", "border_radius", 12))   # raises on "abc"
  ...
  @property
  def crossfade_duration(self) -> int:
      return self.get("audio", "crossfade_duration", 3)  # the UI writes crossfade_duration_sec
  ```
  Probe output:
  ```
  volume: 150
  crossfade_enabled: False
  crossfade_duration: 9
  border_radius raised: ValueError invalid literal for int() with base 10: 'abc'
  ```
  and, after `set("audio","crossfade_duration_sec", 7)`:
  ```
  cache crossfade_duration: 9        cache crossfade_duration_sec: 7
  get crossfade_duration -> 9        (alias branch not taken: key present in cache)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe.py` section 12/13 and `%TEMP%\opencode\wn14_probe4.py` section E (`volume property after set 500: 500`, `after set -20: -20`).
- **Suggested fix:** clamp `volume` to 0–100 (in the accessor *and* in `AppApi.set_volume`), make `border_radius` fall back to the default on a bad value, and either drop `crossfade_duration` in favour of `crossfade_duration_sec` or make the two one key with an explicit alias.
- **Fix side effects:** clamping in the accessor changes the value the frontend receives from `get_volume()`; a stored 150 would silently become 100 on the next write.
- **Discovered by:** A

#### F-WN-14-11  [P3] — `AppApi.get_settings()` never returns the `network` category, so the frontend never receives `network.offline_mode`

- **File:** `core/api.py:2922-2938` (the hard-coded category list), `core/settings.py:53-55` (the `network` category in the schema), `ui/web_new_v2/js/player.js:1440` / `ui/web_new_v2/js/player.js:1524` / `ui/web_new_v2/js/utils.js:526` / `ui/web_new_v2/js/utils.js:608` (the consumers), `ui/web_new_v2/js/main.js:409-418` (where `window.settings` is filled)
- **Confirmed:** yes
- **Description:** `AppApi.get_settings()` enumerates a **hard-coded** list of 22 category names. That list does not contain `network` (which exists in `DEFAULT_SETTINGS` and holds `offline_mode`), and it contains four names that do not exist in the schema at all (`appearance`, `lyrics`, `player`, `system` — these return `{}` and are skipped). The frontend's `window.settings` is populated from this payload (`ui/web_new_v2/js/main.js:409-418`), so `window.settings.network` is `undefined` at startup and every `window.settings?.network?.offline_mode` check in the UI evaluates to *false* — i.e. the UI believes it is online.
- **Cause:** the bridge duplicates the schema's category list instead of deriving it from it, so the two lists drift silently.
- **Trigger conditions:** the app starts with offline mode enabled in the DB (or the user toggles it in another window/instance). The state is only corrected once `applyOfflineState()` runs (an explicit offline-mode event), which happens on the toggle, not on startup.
- **User impact:** while offline mode is on, the UI still tries to prefetch the next track and still builds remote cover URLs. The backend intercepts the bridge calls (`core/api.py:461-512`), so playback itself is unaffected — the cost is wasted requests and a UI that does not reflect the mode until the user toggles it.
- **Evidence:**
  ```python
  # core/api.py:2929
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio',
                'overlay', 'efficiency', 'optimization', 'hotkeys', 'storage',
                'player_appearance', 'personalization', 'interface', 'ui', 'theme',
                'equalizer', 'auth', 'services', 'session', 'zapret']
  ```
  Schema diff (probe `%TEMP%\opencode\wn14_probe3.py`):
  ```
  in DEFAULT_SETTINGS but NOT returned by AppApi.get_settings(): ['network', 'subscription']
  returned by get_settings() but NOT a DEFAULT_SETTINGS category: ['appearance', 'lyrics', 'player', 'system']
  ```
  (`subscription` is deliberately excluded — see the comment at `core/settings.py:265-271`.)
- **Reproduction / verification:** start the app with `network.offline_mode = True` in the DB, then evaluate `window.settings?.network?.offline_mode` in the WebView2 devtools → `undefined` (falsy), while `pywebview.api.get_settings_by_category('network')` returns `{'offline_mode': True}`.
- **Suggested fix:** derive the list from `DEFAULT_SETTINGS` (the schema owner is `core/settings.py`) instead of duplicating it in the bridge, or add `network` to the list.
- **Fix side effects:** `get_settings()` would grow by one category; the frontend's localStorage cache (`nedotify_cached_settings`) would change shape, and `applySettingsFromBackend` would need to tolerate the new key.
- **Discovered by:** A — **root cause is in `core/api.py` (WN-08)**; the schema that is being mis-enumerated lives in `core/settings.py` (WN-14). Not double-reported: WN-08 owns the bridge list.

#### F-WN-14-12  [P3] — `get()` coerces only the strings `"true"`/`"false"`; a stored `"0"` stays a truthy string in memory but reloads as the falsy integer `0`

- **File:** `core/settings.py:394-399` (the coercion), `core/settings.py:367-372` (the cache read), `core/database.py:2028-2034` / `core/database.py:2117-2132` (the serialiser and the reader)
- **Confirmed:** yes
- **Description:** `get()` maps the *strings* `"true"`/`"false"` to booleans and leaves every other value alone. A boolean setting that arrives as the string `"0"` is returned as the string `"0"` — truthy in Python. The DB, however, serialises `"0"` via `str(value)` to `"0"`, which `json.loads` turns into the integer `0` — falsy. The truthiness of the same setting therefore flips across a restart.
- **Cause:** the coercion is a string whitelist, while the persistence layer is JSON-based; the two disagree on the representation of a non-boolean truthy/falsy value.
- **Trigger conditions:** a setting written with the string `"0"` / `"1"` / `"off"` / `"yes"`. The frontend's `saveSetting` passes the JS value straight through (`ui/web_new_v2/js/settings.js:1045`), so a `"0"` string from a text input (e.g. a numeric field) reaches the backend as a string.
- **User impact:** a setting reads as "on" in the running app and as "off" after a restart — e.g. `audio.muted` written as the string `"0"` would keep the app muted for the whole session and then un-mute itself on the next launch.
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
  Probe output:
  ```
  get('audio','muted') with stored str 'false' -> False
  get('audio','muted') with stored str '0'     -> '0'     # truthy in Python
  ```
  and the DB round trip:
  ```
  value='0' -> stored='0' -> reloaded=0
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn14_probe.py` section 3.
- **Suggested fix:** normalise on write (store booleans as booleans) and widen the read coercion to `"0"`/`"1"`/`"off"`/`"on"`, or make `get()` return the typed value the schema declares.
- **Fix side effects:** a value that is *legitimately* the string `"0"` (e.g. a numeric text field such as `crossfade_duration_sec`) would become the integer `0` — the coercion must not be applied to string-typed schema entries.
- **Discovered by:** A

#### F-WN-14-13  [P3] — A DB error while loading the settings aborts the whole `SettingsManager` construction (and with it app startup)

- **File:** `core/settings.py:315-317` (`_load_all`), `core/settings.py:298-313` (`__init__`), `core/database.py:2117-2132` (`get_all_settings`)
- **Confirmed:** yes (the missing guard); the corrupt-DB trigger itself belongs to WN-12
- **Description:** `_load_all` calls `self.db.get_all_settings()` with no `try/except`. Any exception raised by the DB layer (a locked file, a corrupt page, a closed connection) propagates out of `SettingsManager.__init__` and aborts the construction of `AppCore` — the app then fails to start, and the user is left with no window at all rather than with default settings.
- **Cause:** the defensive `getattr(self.db, 'get_all_settings', lambda: {})()` guards against a *missing* method but not against a *failing* one.
- **Trigger conditions:** the SQLite file is corrupt or unreadable (WN-12 owns whether the DB layer detects and repairs that).
- **User impact:** the app does not start. With a guard, the app would start with default settings and the user's data would be recoverable.
- **Evidence:**
  ```python
  # core/settings.py:315-317
  def _load_all(self):
      """Load settings from database, populating missing values from default schema."""
      stored_all = getattr(self.db, 'get_all_settings', lambda: {})()
  ```
- **Reproduction / verification:** point `SettingsManager` at a DB stub whose `get_all_settings` raises → the constructor raises. Whether `core/database.py` survives a corrupt file is WN-12's question; this finding is only about the missing guard in the settings manager.
- **Suggested fix:** wrap the read in `try/except Exception` and fall back to `{}` (defaults) with an error log.
- **Fix side effects:** a settings read failure would silently reset the user's settings to the defaults in the UI for that session (the DB rows are not touched) — the log line is the only trace.
- **Discovered by:** A

---

### 3. Clean areas

**THE MIRROR CONTRACT (#5) IS INTACT — verified id-by-id and value-by-value.**

`core/settings.py` `DEFAULT_SETTINGS["hotkeys"]` (L119-144), quoted verbatim:

```python
    "hotkeys": {
        # MUST mirror DEFAULT_KEYBINDS in ui/web_new_v2/js/hotkeys.js exactly:
        ...
        "play_pause": "Space",
        "next_track": "Ctrl+ArrowRight",
        "prev_track": "Ctrl+ArrowLeft",
        "volume_up": "Ctrl+ArrowUp",
        "volume_down": "Ctrl+ArrowDown",
        "toggle_mute": "KeyM",
        "toggle_lyrics": "KeyL",
        "toggle_mini": "KeyP",
        "like": "KeyK",
        "search": "Slash",
    },
```

`ui/web_new_v2/js/hotkeys.js` `DEFAULT_KEYBINDS` (L4-15), quoted verbatim:

```js
export const DEFAULT_KEYBINDS = [
    { id: 'play_pause', label: 'Воспроизведение / Пауза', defaultKey: 'Space' },
    { id: 'next_track', label: 'Следующий трек', defaultKey: 'Ctrl+ArrowRight' },
    { id: 'prev_track', label: 'Предыдущий трек', defaultKey: 'Ctrl+ArrowLeft' },
    { id: 'volume_up', label: 'Увеличить громкость (+5%)', defaultKey: 'Ctrl+ArrowUp' },
    { id: 'volume_down', label: 'Уменьшить громкость (-5%)', defaultKey: 'Ctrl+ArrowDown' },
    { id: 'toggle_mute', label: 'Вкл / Выкл звук', defaultKey: 'KeyM' },
    { id: 'toggle_lyrics', label: 'Открыть / закрыть текст', defaultKey: 'KeyL' },
    { id: 'toggle_mini', label: 'Компактный мини-плеер', defaultKey: 'KeyP' },
    { id: 'search', label: 'Фокус на поиск', defaultKey: 'Slash' },
    { id: 'like', label: 'Нравится трек', defaultKey: 'KeyK' }
];
```

| id | Python `DEFAULT_SETTINGS["hotkeys"]` | JS `DEFAULT_KEYBINDS` | in both? | same binding? |
|---|---|---|---|---|
| `play_pause` | `Space` | `Space` | yes | yes |
| `next_track` | `Ctrl+ArrowRight` | `Ctrl+ArrowRight` | yes | yes |
| `prev_track` | `Ctrl+ArrowLeft` | `Ctrl+ArrowLeft` | yes | yes |
| `volume_up` | `Ctrl+ArrowUp` | `Ctrl+ArrowUp` | yes | yes |
| `volume_down` | `Ctrl+ArrowDown` | `Ctrl+ArrowDown` | yes | yes |
| `toggle_mute` | `KeyM` | `KeyM` | yes | yes |
| `toggle_lyrics` | `KeyL` | `KeyL` | yes | yes |
| `toggle_mini` | `KeyP` | `KeyP` | yes | yes |
| `like` | `KeyK` | `KeyK` | yes | yes |
| `search` | `Slash` | `Slash` | yes | yes |

**Only-in-Python: none. Only-in-JS: none. Binding mismatches: none.** The only difference is the *order* of the last two entries (`like` before `search` in Python, `search` before `like` in JS) — irrelevant for a key→value mapping, but it does decide which action wins a duplicate (see F-WN-14-2/F-WN-14-3). The mirror is additionally pinned by `tests/test_keybind_contracts.py` (`test_backend_ids_are_exactly_the_frontend_ids`, `test_backend_values_match_frontend_defaults`), which I ran: **7 passed**.

**`get_system_region()` (L24-49)** — correct and fail-safe:
- Primary: `kernel32.GetUserDefaultGeoName` via `ctypes`, with `restype`/`argtypes` set explicitly, a 10-char buffer and a `len(region) == 2` sanity check (rejects the 3-digit UN M.49 codes such as `419`).
- Fallback: `locale.getdefaultlocale()[0]`, split on `_`, again length-checked.
- Final fallback: `"US"`. Every step is wrapped in `try/except Exception: pass`, so a non-Windows host (no `ctypes.windll`) or a missing locale degrades to `"US"` instead of raising.
- It is invoked exactly once, at **module import** (L62: `"region": get_system_region()`), so the value is effectively a per-process constant — there is no per-call overhead and no re-detection on a locale change.
- Verified on this machine: returns `RU`; `locale.getdefaultlocale()` returns `('ru_RU','cp1251')` **without a DeprecationWarning** on the pinned interpreter (Python 3.14.7) — so the fallback path is not a warning-noise source here.
- **Caveat (not a finding):** `general.region` has **no consumer anywhere in the Windows tree** — the only occurrence of the key is the default itself. `get_system_region()` is therefore dead weight on the desktop product today. (Reported as a coverage note, not a defect: the schema may be forward-looking.)

**`_load_all` (L315-342)** — behaves correctly for the cases that matter:
- Empty DB → every category/key is filled from the defaults (`copy.deepcopy`, so `DEFAULT_SETTINGS` is never handed out by reference — verified: mutating `settings.get("equalizer","bands")` did **not** corrupt `DEFAULT_SETTINGS`).
- A missing category → filled from the defaults.
- A category missing from the DB but present in the schema → fine.
- **Unknown DB categories are PRESERVED, not dropped**: the second loop (L336-342) copies every dotted DB key into the cache, including categories that are not in `DEFAULT_SETTINGS` (verified: a `legacycat.foo` row stayed in the cache and in the DB across a flush + write cycle). Since `flush()` only writes *dirty* keys and never deletes rows, unknown rows are not lost on the next write.
- The legacy flat-key fallback (L326-327: `elif key in stored_all`) is a deliberate old-schema migration path.

**The async writer (`flush`/`_write_batch`/`_writer_loop`/`_wake_writer`/`sync_flush_now`) — the durability path is sound:**
- **The queue is bounded** — there is no queue at all: `_dirty` is a `set` of `(category, key)` pairs, so the memory footprint is bounded by the number of distinct settings, not by the number of writes. A volume slider drag collapses into one row.
- **No write is lost between `flush()` and `set()`**: `flush()` snapshots and clears `_dirty` under `_lock` and takes the payload from the cache in the same critical section; a `set()` that arrives during the DB write re-adds the key to `_dirty` and re-arms the wake event, so it is written by the next tick. Verified with a deliberately slow DB: both the concurrent `set()` and the flushed value landed (`{'general.language': 'fr', 'general.region': 'RU'}`, `_dirty` empty afterwards).
- **The writer thread cannot die silently**: `_writer_loop` wraps `flush()` in `try/except` and logs; `wait()`/`sleep()` cannot raise; and `_wake_writer` **restarts** a dead writer (`if self._writer_thread is None or not self._writer_thread.is_alive()`), so a dead thread can never leave the app writing into a dead queue.
- The thread is a **daemon** (`daemon=True`) and is **not joined** on exit — correct, because a non-daemon thread would block the interpreter's atexit join (the same trap the proxy explicitly documents at `core/proxy.py:428`).
- **The final flush on app close is guaranteed** on every exit path I could find:
  - normal close: `main.py:575` → `AppCore.cleanup` → `core/app.py:557-558` `settings.flush()` **before** `core/app.py:559-560` `db.close()` → then `main.py:577` `api.cleanup()` → `main.py:580` `sys.exit(0)` → `atexit` (`core/settings.py:313`) flushes again (a no-op).
  - the startup-watchdog hard exit: `main.py:526` `sync_flush_now()` → `main.py:530` `cleanup()` → `main.py:536` `sync_flush_now()` → `main.py:539` `os._exit(3)` (which skips atexit) — the explicit `sync_flush_now()` calls cover exactly that gap, and `sync_flush_now()` never raises (`core/settings.py:433-441`).
  - the session is written through the same manager and flushed explicitly (`core/session.py:57-68`).
  - Only a hard kill (Task Manager / power loss) loses up to `FLUSH_INTERVAL_SECONDS` (0.5 s) of changes — by design.
- **A failed write is surfaced**: `flush()` compares the written count against the batch size, restores the pending keys and logs an error; `sync_flush_now()` returns `False` for a partial or failed write instead of claiming success. `core/database.py:2049-2082` returns the number of rows written and `0` on any failure (including serialisation, which it catches inside the batch), and `SettingsManager._write_batch` (L485-506) keeps that count. The only gap is the *retry cadence* — F-WN-14-5.

**`reset_category` / `reset_all` (L537-549)** — correct:
- Every default key of the category is re-written through `set()` with a `deepcopy`, so the reset value is exactly the schema default and the module-global defaults are never mutated (the comment at L541-543 explains why).
- Custom user values for standard keys are removed (they are overwritten with the default and the row is rewritten).
- The reset touches **both** the in-memory cache and the DB (the cache is updated synchronously by `set()`, the DB by the following flush).
- Extra, non-schema keys inside a category are **not** removed (e.g. a `hotkeys.custom_extra` row survives `reset_category("hotkeys")` — verified). That matches the "unknown keys are preserved, not dropped" contract.
- Unknown DB categories are left alone by `reset_all()` (verified: a `legacycat.foo` row survived) — correct, since there is no default for them.
- `reset_category` on a category that is not in `DEFAULT_SETTINGS` is a silent no-op.

**The typed accessors (`theme_name` … `font_family`, L551-589)** — the defaults agree with the schema:
`theme_name`→`theme.name`="Dark", `theme_mode`→`theme.mode`="dark", `accent_color`→`theme.accent_color`="#a855f7", `gapless`→`audio.gapless_playback`=**False** (the literal was deliberately corrected — see the comment at L578-580), `overlay_mode`→`overlay.mode`="disabled", `font_family`→`interface.font_family`="system", `volume`→70, `crossfade_enabled`→False, `crossfade_duration`→3. `crossfade_duration` is in **seconds** (the frontend clamps it to 0–12 s at `ui/web_new_v2/js/player.js:1479`). The defects around these accessors are in F-WN-14-10.

**The hotkey key-capture / dispatch logic (`js/hotkeys.js`) — the parts that are right:**
- The **input-field guard exists and is correct** (L149-155): `document.activeElement` is checked for `input`/`textarea`/`isContentEditable`, and the event target is matched against `input, textarea, select, [contenteditable="true"]`. A plain-letter binding therefore does **not** swallow typing in the search box or any text field.
- The **modal guard** (`isFocusInsideModalTrap`, L166) is narrow and correct — it only fires for a modal that is armed, visible and contains the focus, so no binding changes behaviour outside an open dialog. `utils.js:342-349` implements it as a `modalTraps` containment check.
- **Modifier-only presses are correctly detected**: `parseKeyEventCombo` returns `null` for `ControlLeft/Right`, `AltLeft/Right`, `ShiftLeft/Right`, `MetaLeft/Right` (and the bare `Control`/`Alt`/`Shift`/`Meta` keys) — the function is right; its *caller* is wrong (F-WN-14-1).
- **Non-Latin layouts are handled correctly for everything except `/`**: the binding is built from `e.code`, which is the physical key and therefore layout-independent, and the defaults are `e.code` names too (`KeyM`, `KeyL`, `KeyP`, `KeyK`, `Space`, `Slash`, `ArrowRight`…). Verified: `code="KeyM" key="ь"` → `"KeyM"` (the Russian layout's "ь" key still produces the physical `KeyM`). Only `/` breaks the rule (F-WN-14-4).
- **The backend application is filtered correctly** (L104-120): only ids in `KNOWN_ACTIONS` are taken from the backend, non-string/empty values are ignored, and the localStorage fallback is applied *before* the backend so the backend wins — this is exactly the drift protection the mirror contract needs.
- **Ghost entries are cleaned up** (L92-96): an id that is not a known action is deleted from `activeKeybinds`, so an old backend default such as `toggle_overlay` cannot linger.
- **`Escape` cancels a recording** (L137: `if (combo && e.code !== 'Escape')`), and clicking outside the record button cancels it too (the `pointerdown` capture listener at L123-128, which correctly exempts `.keybind-record-btn`).
- **Auto-repeat is guarded**: `if (e.repeat && !REPEATABLE_ACTIONS.has(actionId)) break;` — only `volume_up`/`volume_down` repeat.
- **F11 and the native media keys** are handled before the binding table and are unaffected by it.
- The **single dispatcher** rule holds: `executeHotkeysAction` is the only action switch, it has a branch for every one of the 10 ids, and `tests/test_keybind_contracts.py` pins both facts (`test_no_duplicate_hotkey_dispatcher`, `test_every_default_keybind_has_a_dispatcher_branch`).

---

### 4. Coverage gaps

- **I did not run the app.** The key-capture findings are reproduced against the *verbatim* source of `js/hotkeys.js` extracted at runtime (Node harness), not through a real WebView2 key event. The end-to-end confirmation would be: open Settings → Hotkeys, click "record", press `Ctrl+K`. The harness covers the same code path with the same inputs, but the browser's real key-delivery order for chords was not observed live.
- **Per-layout verification of the `/` finding (F-WN-14-4) needs a machine with the layout in question.** I proved the code-level asymmetry (the `e.key === '/'` override) and named German QWERTZ as the affected case from the layout's character map; I did not observe `e.code`/`e.key` on a German keyboard. Russian ЙЦУКЕН (the app's default language) is *not* affected — `/` is the unshifted output of the physical `Slash` key there.
- **The IME case was not exercised.** `parseKeyEventCombo` uses `e.code`, so a key pressed while an IME is composing still records the physical key; `e.isComposing` is never consulted. I could not determine whether that is a defect without a live IME session, so I did not report it.
- **I did not run the whole test suite.** I ran `tests/test_keybind_contracts.py` (7 passed) and read `tests/test_settings_flush.py` and `tests/test_settings_manager.py`; the rest of `tests/` was not executed, so I cannot claim the existing suite is green.
- **I did not verify `core/database.py`'s behaviour on a corrupt DB file** (WN-12's area). My F-WN-14-13 only states that `core/settings.py` has no guard around `get_all_settings()`; whether the app can even reach that state is WN-12's call.
- **The `set()` call sites in `core/api.py` (WN-08) were traced but not audited.** `AppApi.set_setting` (L1871-1897) has its own dotted/2-arg ambiguity (a bare key is silently routed to the `zapret` category at L1880) — that is WN-08's finding, not mine.
- **`js/settings.js` and `js/main.js` are large (3111 L) and shared with WN-30**; I read only the hotkey-related and settings-bootstrap parts.
- **`core/settings.py` was read in full**, so no part of the settings manager is unexamined; the parts I could not exercise at runtime are the ones that need the real SQLite file (which I was told not to touch).
