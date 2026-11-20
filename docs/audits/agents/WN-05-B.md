## AREA WN-05 — Bridge playback, queue ops, listening telemetry, volume — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` L1–300 (module header, secret masking, `_SECRET_SETTING_KEYS`, `_bridge_write_error`, `_is_empty_secret_write`), L340–519 (`AppApi.__init__`, bridge error wrapper, offline interception), L720–759 (`_deferred_window_op`), L1110–1160 (`_emit`), **L1161–2080 (the audited range, in full)**, L2225–2269, L2750–2979 (the WN-08 settings surface, for the duplication check), L2985/3006/3466/3481/3484 (`_window_op_lock` users).
- `audio/engine.py` L1–508 (whole file), `audio/queue.py` L1–302 (whole file), `core/listening.py` L1–44 (whole file).
- `core/app.py` L280–370, L368–487, L490–569 (`re_resolve_stream_url_async`, `cleanup`).
- `core/database.py` L1–60, L160–239 (thread-local connections), L1550–1629 (`begin_listening_session`, `update_history_duration`), L2030–2109 (`set_setting`/`set_settings_batch`), L2410–2489 (`close`).
- `core/settings.py` L1–589 (whole file), `core/proxy.py` L485–544 (`_authorized`), L1260–1334 (`LocalProxyManager`, `get_proxy_url`, `auth_query`), `core/user_errors.py` L1–24.
- `ui/web_new_v2/js/player.js` L20–69, L520–699, L698–700, L820–899, L920–979, L1200–1239, L1410–1489, L1526–1609, L1625–1724, L1820–1869, L1920–1959, L1970–1999, L2028–2057.
- `ui/web_new_v2/js/events.js` L90–229, L270–464; `ui/web_new_v2/js/queue.js` L1–303 (whole file); `ui/web_new_v2/js/main.js` L20–169; `ui/web_new_v2/js/library.js` L235–284; `ui/web_new_v2/js/search-discovery.js` L20–89; `ui/web_new_v2/js/feature-controls.js` L55–94; `ui/web_new_v2/js/hotkeys.js` (grep only); `ui/web_new_v2/js/lyrics.js` L295–324.
- `tests/conftest.py` L1–176, `tests/test_measured_listening.py` (whole), `tests/test_queue.py` (whole), `tests/test_emit_thread_safety.py` (whole), `tests/test_playback_recovery.py` (whole), `tests/test_keybind_contracts.py` (whole), `tests/test_api_f1_audit.py` L1–120, `tests/test_api_audit_b.py` L1–120.

**Callees traced into other areas (not owned by WN-05)**

- `audio/engine.py` + `audio/queue.py` → **WN-17** (queue invariants, `set_tracks` re-shuffle, `add_tracks` not recording `_original_order`).
- `core/resolver.py` / `core/app.py::re_resolve_stream_url_async` → **WN-15** (the resolution worker thread is spawned untracked; single-flight not audited here).
- `core/proxy.py` → **WN-11** (the loopback bearer token threat model, `?k=` URL shape, `serve_local_file` allow-list).
- `core/database.py` → **WN-12** (`update_history_duration` transaction cost, plaintext `settings` table, per-thread connections).
- `core/settings.py` → **WN-14** (`SettingsManager` write-behind batching, `DEFAULT_SETTINGS`).
- `ui/web_new_v2/js/player.js`, `js/queue.js`, `js/events.js` → **WN-29 / WN-28** (the frontend side of the event contracts).
- `services/yandex_service.py` → **WN-21** (the OAuth client that consumes the token).

---

### 2. Findings

#### F-WN-05-1  [P2] — `play_pause` is a read-only query on the bridge, but three frontend call sites use it as a *toggle command*

- **File:** `core/api.py:1746-1759` (method), plus `ui/web_new_v2/js/player.js:691-692`, `ui/web_new_v2/js/library.js:244-245`, `ui/web_new_v2/js/library.js:274-275`
- **Confirmed:** yes
- **Description:** `AppApi.play_pause()` only reads and returns `self._last_reported_state`; it never changes anything. The frontend, however, calls it as a command: the `navigator.mediaSession` "play"/"pause" action handlers and the library "Play all" / playlist "Play" buttons all fire `api('play_pause')` and **ignore the return value**.
- **Cause:** the bridge method and its callers disagree on the contract (query vs. command). The method's own docstring states it "must not guess" — but nothing on the JS side knows that, so a caller cannot distinguish "I asked for a state" from "I asked for a toggle".
- **Trigger conditions:** (a) the user presses the Play/Pause button in the Windows media overlay / media keys while the app is focused; (b) the user clicks "Play all" in the Library or "Play" on a playlist **while the current track is already in that list** (`isPlayingFromCurrentList` is true → the `play_pause` branch is taken instead of `play_track`).
- **User impact:** the media-overlay Play/Pause button does nothing at all (no pause, no resume, no visible change). The Library "Play all" / playlist "Play" button silently does nothing when the track is already in the list — the classic "the failure mode here is silence".
- **Evidence:**
  ```python
  # core/api.py:1746-1759
  def play_pause(self) -> str:
      """Report the last playback state the frontend observed.
      ... it receives no argument telling it whether the user asked to play or to pause ...
      """
      state = getattr(self, "_last_reported_state", "") or ""
      return state
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:691-692
  navigator.mediaSession.setActionHandler('play', () => api('play_pause'));
  navigator.mediaSession.setActionHandler('pause', () => api('play_pause'));
  // ui/web_new_v2/js/library.js:244-245
  if (isPlayingFromCurrentList && window.pywebview?.api?.play_pause) {
      window.pywebview.api.play_pause();      // return value discarded -> no toggle
  ```
- **Reproduction / verification:** read the two sides. The frontend's own `togglePlayPause()` in `js/player.js:859` is the real implementation and is what the hotkey dispatcher (`js/hotkeys.js:202-203`) and the player-bar buttons use. Nothing routes the mediaSession handlers or the library buttons to it.
- **Suggested fix:** either (a) make the bridge method a real command — `play_pause()` should ask the frontend to toggle and the frontend should own the audio element, e.g. rename the bridge method to `get_playback_state()` and have the JS call `togglePlayPause()` directly; or (b) change the bridge method to accept the intended state (`play_pause('playing'|'paused')`) and let the frontend apply it. Do not leave a name that reads as a verb but behaves as a getter.
- **Fix side effects:** the bridge method is exposed to JS and might be called by third-party plugin code (the plugin folder is never on `sys.path`, but `core/plugins.py` exists) — check before removing it. `tests/test_api_misc.py:38-39` pins `get_setting`, not `play_pause`, so the test surface is small.
- **Discovered by:** B

#### F-WN-05-2  [P2] — A solo `play_track(track)` (no `track_list`) destroys the whole queue

- **File:** `core/api.py:1605-1606` (the no-list branch), `core/api.py:1734-1737` (the delivery), `audio/engine.py:35-39` (the callee that replaces the queue)
- **Confirmed:** yes
- **Description:** when the frontend calls `play_track(track)` **without** a `track_list`, the bridge routes to `_resolve_track(track, lambda t: self._core.engine.play_track(t))`. `AudioEngine.play_track` calls `queue.set_tracks([track], 0)` — i.e. it replaces the entire queue with that single track. The bridge never merges the new track into the existing queue, and never restores the previous queue.
- **Cause:** the bridge has two incompatible notions of "play this track" — "play this track **as the new queue**" (the no-list form) and "play this track **inside this queue**" (the list form) — and the frontend uses both interchangeably.
- **Trigger conditions:** any of these reach the no-list form: `js/search-discovery.js:43` (clicking a card in "Знакомая музыка"), `js/feature-controls.js:69` (the "retry" action button of the playback-error dialog), `js/player.js:892/895/898` (the `togglePlayPause` fallback when the queue is empty), `js/player.js:1704` (the "stream not resolved yet" re-resolve request).
- **User impact:** the user's queue (up to hundreds of tracks, shuffle/repeat state, the drawer contents) is silently replaced by one track. After that, "Next" has nothing to advance to, the queue drawer shows a single row, and the shuffle/repeat context is gone. The "retry" path in the error dialog is the worst offender: retrying a failed track destroys the playlist the user was listening to.
- **Evidence:**
  ```python
  # core/api.py:1605-1606
  else:
      self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  ```
  ```python
  # audio/engine.py:35-39  (the callee that owns the replacement semantics)
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)
      self._notify_track_changed()
  ```
- **Reproduction / verification:** reproduced with a headless harness (`AppApi` + real `AudioEngine` + real `PlaybackQueue`, `re_resolve_stream_url_async` stubbed):
  ```
  === A) queue play then solo play_track (no track_list) ===
  queue length after queue play: 30
  pending solo resolution armed: True
  queue length after solo resolution: 1
  queue contents: ['solo']
  ```
  (script: `%TEMP%\opencode\wn05_probe3.py`, section A).
- **Suggested fix:** in the no-list branch, do not call `engine.play_track` (replace-the-queue). Either resolve the track and then *append/replace in place* in the existing queue, or make the no-list form explicitly mean "solo, queue is not preserved" and have the frontend stop using it for the retry / discovery paths (pass the current queue instead). The queue's replace-vs-merge semantics belong to the engine (WN-17); the bridge must not silently pick the destructive one.
- **Fix side effects:** preserving the queue changes what "Next" does after a solo play; the frontend's `player.js:876-899` already has a "pass the current queue so the backend keeps the queue" pattern — reusing it removes the ambiguity. The `queue_ended`/`next_track` semantics in `js/player.js:644-657` will need to stay consistent.
- **Discovered by:** B

#### F-WN-05-3  [P2] — No generation counter on the play path: a resolution that lands after the queue ended restarts the last track from 0:00

- **File:** `core/api.py:1583-1604` (`on_queue_resolved` / `on_queue_error`), `core/api.py:1716-1744` (`on_resolved` in `_resolve_track`), `core/api.py:1714` (`cur_start` capture)
- **Confirmed:** yes
- **Description:** the only staleness guard on the play path is an **object-identity** check — `self._core.engine.queue.current_track is target_track` (`core/api.py:1590`, `1601`) and the `cur_start` snapshot in `_resolve_track` (`core/api.py:1714`, `1734`). There is no generation/epoch counter, no cancellation token and no "the user asked for something else since" flag. A resolution that was started while track *A* was current is still delivered when the queue is still showing *A* — including after the queue has already ended.
- **Cause:** "what the user wants to hear" is never modelled as a versioned intent. The identity check answers "is the queue still pointing at the same dict?", not "is this resolution still the one the user is waiting for?".
- **Trigger conditions:** the last track of the queue is an online track whose stream is still being resolved when it ends (slow network, cold cache, provider fallback). The user presses "Next" (or the track ends) → `AudioEngine.next_track()` returns `None` → `_on_queue_end()` → the frontend tears the audio down. A second later the resolution lands and `on_queue_resolved` sees `queue.current_track is target_track` (still true — the queue never advanced) → it sets `file_path` and calls `engine._notify_track_changed()` → a fresh `track_changed` event.
- **User impact:** the player that had just stopped **starts playing the last track again from the beginning** and the UI flips back to "playing" — the queue never really ends. In `js/player.js:1687-1692` the re-emitted track has a `stream_url` and `activeAudio.src` was cleared by `stopPlaybackForQueueEnd()` (`js/player.js:1846-1848`), so the guard `!activeAudio.src` is true and `playTrack(track, track.stream_url)` restarts it.
- **Evidence:**
  ```python
  # core/api.py:1583-1597
  def on_queue_resolved(stream_url, metadata=None):
      if not stream_url:
          ...
      if self._core.engine.queue.current_track is target_track:   # <-- identity, not intent
          target_track["file_path"] = stream_url
          ...
          self._core.engine._notify_track_changed()
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:1687-1692
  } else if (track.stream_url) {
      if (!sameTrack || activeAudio.ended || !activeAudio.src ||
          activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
          playTrack(track, track.stream_url);      // <-- restarts the ended track
      }
  }
  ```
- **Reproduction / verification:** headless harness, one-track queue, resolution delivered after `next_track()` returned `None`:
  ```
  === B) late resolution after the queue ended (real _on_track_changed) ===
  queue current after play: t0
  next_track() -> None
  emitted before late resolution: ['track_changed', 'queue_updated', 'queue_ended']
  emitted after late resolution: ['track_changed', 'queue_updated', 'queue_ended', 'track_changed']
  track_changed count: 0 -> 1 extra track_changed
  current track file_path now: http://cdn.example/stream.mp3
  ```
  (script: `%TEMP%\opencode\wn05_probe3.py`, section B.)
- **Suggested fix:** introduce a monotonic playback generation in `AppApi` (incremented on every `play_track`, `next_track`, `prev_track`, `clear_queue` and on `queue_ended`), stamp the resolution closure with the generation it was started in, and drop the callback if the generation has moved on. The frontend already has exactly this concept (`playbackGeneration` in `js/player.js:23`, `currentQueueVersion` in `js/player.js:22`) — the backend has no counterpart.
- **Fix side effects:** the same generation must be honoured by `core/playback_recovery.py` (WN-15) and by `core/app.py::re_resolve_stream_url_async` (WN-15/WN-02) or legitimate recoveries will be dropped. `tests/test_measured_listening.py:80-87` (`test_re_resolved_same_track_keeps_one_listening_session`) must keep passing — a re-resolution of the *same* track must still be delivered, so the generation must only change on a *user intent* change, not on a re-resolve.
- **Discovered by:** B

#### F-WN-05-4  [P2] — `get_setting`/`set_setting` are a second, divergent settings API: inverted argument order, no autostart registry sync, and a `None` value silently mis-routed into the `zapret` category

- **File:** `core/api.py:1853-1900` (this range) vs `core/api.py:2922-2962` (the WN-08 surface: `get_settings`, `save_setting`, `get_all_settings`, `get_settings_by_category`, `update_setting`)
- **Confirmed:** yes
- **Description:** seven settings methods exist on the same bridge object, split across two areas, with two different write paths and two different read paths that do not agree:
  - **Argument order is inverted.** `set_setting(section, key, value)` vs `save_setting(key, value, category)`. `set_setting('audio', 'volume', 50)` is correct; `save_setting('audio', 'volume', 50)` writes `settings.set(50, 'audio', 'volume')` — category `50`.
  - **No autostart registry sync.** `save_setting` calls `self.update_autostart(bool(value))` for the `autostart` key (`core/api.py:2947-2951`); `set_setting` does **not**. `set_setting('general', 'autostart', True)` therefore writes the *setting* but never the `HKCU\...\Run` value → the app claims autostart is on but never starts at logon (the exact failure the constant `AUTOSTART_RUN_VALUE` exists to prevent).
  - **`None` is mis-routed.** `set_setting` treats `value is None and key is not None` as "dotted-key form" (`core/api.py:1874-1888`), so `set_setting('auth', 'yandex_token', None)` writes `settings.set('zapret', 'auth', 'yandex_token')` — the intended `auth.yandex_token` is *not* cleared, and a junk `zapret.auth` key is created. The user believes they revoked the token; the token stays live.
  - **Bare-key reads are refused.** `get_setting('volume')` returns the default and logs a warning, while `get_settings_by_category('audio')` returns `{'volume': 55}`.
- **Cause:** two hand-written wrappers over the same `core/settings.py` store, added at different times, never reconciled. Neither has a frontend caller today (`get_setting`/`set_setting` are only exercised by `tests/test_api_misc.py:38-39` and `tests/test_api_f1_audit.py:65-112`), so the drift was invisible — but both are **public bridge methods**: any JS in the webview can call them, and they are the path of least resistance for the next contributor.
- **Trigger conditions:** any JS/plugin call to `pywebview.api.set_setting(...)`, or a future frontend change that prefers the `set_setting` name over `save_setting`.
- **User impact:** silent misconfiguration: autostart that does not autostart, a settings key written into the wrong category, and a revoked Yandex token that is still valid. This is exactly the "failure mode here is silence" class the project rules single out.
- **Evidence:**
  ```python
  # core/api.py:1871-1888
  def set_setting(self, section: str, key=None, value=None):
      try:
          if value is None and key is not None:
              full_key = str(section)
              val = key
              if "." in full_key:
                  cat, k = full_key.split(".", 1)
              else:
                  cat, k = "zapret", full_key          # <-- 'auth' lands in 'zapret'
              ...
              self._core.settings.set(cat, k, val)
  ```
  ```python
  # core/api.py:2940-2951  (the other write path)
  def save_setting(self, key: str, value, category: str = "app"):
      ...
      self._core.settings.set(category, key, value)
      if key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart"):
          self.update_autostart(bool(value))          # <-- set_setting has no equivalent
  ```
- **Reproduction / verification:**
  ```
  --- set_setting(section, key, None) with a None value ---
  result: {'success': True}
  settings written: [('zapret', 'audio', 'volume')]
  audio.volume -> MISSING
  zapret.audio -> volume

  --- set_setting does not sync the Windows autostart Run key ---
  update_autostart called via set_setting: []
  update_autostart called via save_setting: [True]
  ```
  (script: `%TEMP%\opencode\wn05_probe.py`.)
- **Suggested fix:** delete `get_setting`/`set_setting` and route everything through `get_settings*`/`save_setting`/`update_setting` (WN-08 owns those), or make them thin aliases with the *same* argument order and the *same* side effects as `save_setting`. At minimum `set_setting` must (a) treat an explicit `value=None` as a real write, not as the dotted form, (b) sync autostart, and (c) never fall back to the `zapret` category.
- **Fix side effects:** `tests/test_api_f1_audit.py:71-112` and `tests/test_api_misc.py:38-39` call `set_setting`/`get_setting`; they would need updating. If a third-party plugin depends on the current `set_setting` signature, keep it as a deprecated alias rather than deleting it outright.
- **Discovered by:** B

#### F-WN-05-5  [P2] — Every queue mutation re-serialises and re-broadcasts the *whole* queue: O(n²) payload

- **File:** `core/api.py:1430-1435` (`_notify_queue_updated`), `core/api.py:1772-1780` (`get_queue`), and every caller: `1528`, `1540`, `1547`, `1567`, `1581`, `1639`, `1785`, `1791`, `1801`, `1813`, `1832`, `1847`
- **Confirmed:** yes
- **Description:** each queue operation mutates the queue and then emits `queue_updated` with a **full snapshot** of every track dict in the queue. `get_queue()` returns `queue.tracks` (a list copy of *all* track dicts, each with ~18 keys) plus `current_track`, `current_index`, `shuffle`, `repeat`. Nothing is diffed, and nothing is truncated. Adding *N* tracks one at a time therefore serialises O(N²) track records.
- **Cause:** the event is modelled as "here is the whole queue" rather than "here is what changed", and the emit happens inside the mutation call rather than being coalesced/debounced.
- **Trigger conditions:** any bulk operation performed as a sequence of single-track calls — the documented fallback in `js/utils.js:1653-1654` and `js/main.js:136-139` (`for (const t of tracks) await api.add_to_queue(t)`), or the `remove_from_queue` fallback loop in `js/queue.js:116-119`. A user with a 2000-track queue pays ~800 KB of JSON per single add.
- **User impact:** the WebView2 bridge thread blocks on `evaluate_js` with a multi-hundred-KB string; the UI stutters and the audio element's event handlers are delayed, which shows up as dropped `timeupdate` ticks and visible lag when the queue drawer is open.
- **Evidence:**
  ```python
  # core/api.py:1430-1435
  def _notify_queue_updated(self):
      """Emit queue_updated so the drawer never goes stale after a queue swap."""
      try:
          self._emit("queue_updated", self.get_queue())
  ```
  ```python
  # core/api.py:1772-1780
  def get_queue(self):
      return {
          "tracks": self._core.engine.queue.tracks,      # full copy of every track dict
          "current_index": self._core.engine.queue._current_index,
          "current_track": self._core.engine.queue.current_track,
          "shuffle": self._core.engine.queue.shuffle,
          "repeat": self._core.engine.queue.repeat,
      }
  ```
- **Reproduction / verification:** headless harness with a 2000-track queue:
  ```
  queue_updated payload for 2000 tracks: 725997 bytes, json+emit took 3.7 ms
  200x add_to_queue: 833 ms total, 152387480 bytes emitted, 200 emits
  => O(n^2): 152387480 bytes for 200 adds, final queue payload 797757 bytes
  ```
  (script: `%TEMP%\opencode\wn05_probe4.py`.)
- **Suggested fix:** emit a delta (`{"added": [...], "removed_index": n, "reordered": ...}`) plus a `queue_version` counter, and let the frontend merge it (the frontend already maintains `currentQueue` and `currentQueueVersion` in `js/queue.js:6` / `js/player.js:22`). At minimum, coalesce the emits: a single queued "queue dirty" flag flushed by a single background thread, and cap the payload (e.g. a compact per-track projection like the one `get_next_track` already builds at `core/api.py:2044-2054`).
- **Fix side effects:** the frontend's `js/queue.js:61-69` currently replaces its whole `currentQueue` on every `nedotify:queue_updated`; a delta protocol needs a matching change there (WN-29). `js/player.js:1546-1602` (`flowQueueSnapshot`) compares full queue snapshots and would need to compare versions instead.
- **Discovered by:** B

#### F-WN-05-6  [P2] — `get_queue()` is not an atomic snapshot: four separate lock acquisitions plus one unguarded private read

- **File:** `core/api.py:1772-1780` (the read), `audio/queue.py:23-51` (the properties), `audio/queue.py:193-213` (`move_track`), `audio/queue.py:173-191` (`remove_track`)
- **Confirmed:** yes (the non-atomicity is a fact of the code); the *runtime* torn payload is a hypothesis (see below)
- **Description:** `get_queue()` builds its payload from four independently locked property reads (`tracks`, `current_track`, `shuffle`, `repeat`) plus one **direct read of the private attribute `queue._current_index`** that bypasses `PlaybackQueue._lock` entirely (the class exposes a `current_index` property precisely for that).
- **Cause:** the queue's lock is per-method, and the bridge assembles a compound snapshot outside the queue's abstraction instead of asking the queue for one (`PlaybackQueue.snapshot()`).
- **Trigger conditions:** any queue mutation concurrent with a `get_queue()` — e.g. `remove_from_queue` (which pops a track and adjusts `_current_index` under the lock) racing the `get_queue()` that `_notify_queue_updated` performs, or `move_track` adjusting `_current_index` while the snapshot is being assembled.
- **User impact:** a `queue_updated` payload whose `tracks` list and `current_index` disagree — the drawer highlights the wrong row, and `js/player.js`'s `flowQueueSnapshot` comparison (`js/player.js:1549`, `1559`) sees a false mismatch and aborts a flow autoplay.
- **Evidence:**
  ```python
  # core/api.py:1776  -- private attribute, no lock
  "current_index": self._core.engine.queue._current_index,
  ```
  ```python
  # audio/queue.py:37-45  -- the public, locked accessors that exist
  @property
  def current_index(self) -> int:
      with self._lock:
          return self._current_index
  @property
  def tracks(self) -> list:
      with self._lock:
          return self._tracks.copy()
  ```
- **Reproduction / verification:** the non-atomicity is directly readable. To *observe* a torn payload deterministically one would need to interleave `remove_track` between the `tracks` copy and the `_current_index` read — e.g. by patching `PlaybackQueue.tracks` to sleep — which was not attempted here. Missing evidence: a deterministic interleaving harness; the code path is unambiguous, the timing window is narrow (microseconds).
- **Suggested fix:** add `PlaybackQueue.snapshot()` (WN-17) that returns `{"tracks", "current_index", "current_track", "shuffle", "repeat"}` under a single `self._lock` acquisition, and have `AppApi.get_queue()` call it. Also stop reading `queue._current_index` from outside the class.
- **Fix side effects:** the snapshot copies the track list under the lock, which is the same cost as today; no behavioural change. `tests/test_queue.py` has no concurrency test, so the new method needs one (see §5, A-5).
- **Discovered by:** B

#### F-WN-05-7  [P3] — `report_position` costs one SQLite UPDATE + one full bridge round-trip every 5 s, and the `position_changed` echo is redundant

- **File:** `core/api.py:1407-1428` (`report_position`), `core/api.py:1290-1295` (`_persist_listening`), `core/database.py:1586-1597` (`update_history_duration`), `ui/web_new_v2/js/player.js:611-616` (the caller), `ui/web_new_v2/js/player.js:1925-1932` (`onPositionChanged` early-returns while playing)
- **Confirmed:** yes
- **Description:** the frontend calls `report_position` every 5 s from `timeupdate`. Each call: (1) takes the global `_window_op_lock`; (2) `session.tick()`; (3) `_persist_listening(session)` → **one `UPDATE history` transaction** (the `last_saved` guard only suppresses *identical* measured tuples, and `seconds` changes on every audible tick, so the write always happens); (4) writes the private `engine._last_reported_position`; (5) `_emit("position_changed", …)` → a `json.dumps` + a WebView2 `evaluate_js` IPC.
  Step (5) is pure echo: the position was *just* produced by the WebView, and the only consumer (`onPositionChanged`) returns immediately when the audio is playing (`js/player.js:1930-1932`). The lyric-sync consumer is already fed by the frontend's own local `nedotify:position_changed` dispatch at `js/player.js:609`, which fires at ~4 Hz versus the backend's 0.2 Hz.
- **Cause:** the bridge is used as a position *relay* instead of a position *sink*. The telemetry the backend actually needs (audible seconds) is already delivered by `report_listening_state`.
- **Trigger conditions:** any playback, all the time.
- **User impact:** ~12 extra `history` row updates and ~12 extra WebView2 IPCs per minute of playback (~36 writes per 3-minute track). Individually small, but it is constant background write traffic on the same SQLite file the proxy reads and the downloader writes, and it puts a bridge-thread IPC on the critical path of the position heartbeat.
- **Evidence:**
  ```python
  # core/api.py:1290-1295
  def _persist_listening(self, session):
      measured = (session.seconds, session.completed, session.media_seconds, session.closed)
      if session.history_id is not None and measured != session.last_saved:
          self._core.db.update_history_duration(session.history_id, session.seconds, session.completed,
                                               media_listened=session.media_seconds, session_finished=session.closed)
          session.last_saved = measured
  ```
  ```python
  # core/api.py:1423-1428
  self._emit("position_changed", {
      "pos": pos_sec, "duration": dur_sec, "position_ms": pos_ms, "duration_ms": duration
  })
  ```
- **Reproduction / verification:** headless harness with an audible session, `db.update_history_duration` spied:
  ```
  === C) report_position: DB writes per heartbeat while audible ===
  report_position calls: 10
  history UPDATE transactions: 10
  ```
  (script: `%TEMP%\opencode\wn05_probe3.py`, section C.) The JS side of the redundancy: `js/player.js:1925-1932`.
- **Suggested fix:** (a) drop the `position_changed` emit from `report_position` — or make it opt-in — since the caller already knows the position; (b) throttle the `history` write to a coarser granularity (e.g. every 15–30 s) and let `flush_listening()` (`core/api.py:1297-1302`, already called from `core/app.py:530-531`) write the final value. Keep the in-memory `session.seconds` exact so the measurement stays correct.
- **Fix side effects:** coarser DB writes mean a crash loses up to one interval of measured time; `tests/test_measured_listening.py:27-46` asserts exact `duration_listened` values right after `report_position`, so that test would have to be relaxed to the flush boundary. Do not coarsen `media_seconds`/completion semantics — `test_measured_listening.py:49-62` and `109-118` depend on them.
- **Discovered by:** B

#### F-WN-05-8  [P3] — `_enrich_track_lufs` performs 1–2 uncached SQLite lookups on every call, up to three times per track change

- **File:** `core/api.py:1161-1193` (the lookup), `core/api.py:1208` (`_on_track_changed`), `core/api.py:1457` and `1505` (`play_track`)
- **Confirmed:** yes
- **Description:** the LUFS enrichment is not memoised. Each call that finds no `loudness_lufs`/`lufs` on the dict tries `get_track(id)`, then `get_track_by_path(file_path)`, then `get_track_by_source_id(source, source_id)` — up to three separate SQLite SELECTs, in that order, with no cache and no index hint. The same track is enriched up to three times per play: once for the `track` argument (`core/api.py:1457`), once for the resolved `target_track` (`core/api.py:1505`) and once more in `_on_track_changed` (`core/api.py:1208`) — plus once more on the re-notify after the stream resolves (`core/api.py:1597` → `_on_track_changed`).
- **Cause:** the lookup is a per-call DB probe rather than a memoised attribute of the track. Note the code already carries a comment about exactly this cost (`core/api.py:1463-1465`: "Querying every entry here made one click perform thousands of unrelated SQLite lookups") — the per-track case was thinned but the per-play repetition was left in.
- **Trigger conditions:** every track change. Tracks whose LUFS is already on the dict (the common case once a track has been enriched) cost nothing; the repeated cost hits tracks whose LUFS is unknown, i.e. the first play of every track.
- **User impact:** 2–3 extra SQLite round-trips per track change on the bridge thread. Small in absolute terms (sub-millisecond each on WAL), but it is on the path between the click and the first frame of the player, and it multiplies with F-WN-05-5's payload work.
- **Evidence:**
  ```python
  # core/api.py:1172-1183
  try:
      db_track = None
      t_id = track_dict.get("id") or track_dict.get("track_id")
      if t_id:
          try:
              db_track = self._core.db.get_track(int(t_id))
          except (ValueError, TypeError):
              pass
      if not db_track and track_dict.get("file_path"):
          db_track = self._core.db.get_track_by_path(track_dict["file_path"])
      if not db_track and track_dict.get("source") and track_dict.get("source_id"):
          db_track = self._core.db.get_track_by_source_id(track_dict["source"], str(track_dict["source_id"]))
  ```
- **Reproduction / verification:** instrumented `db.get_track` / `db.get_track_by_path` / `db.get_track_by_source_id`:
  ```
  DB reads for one _enrich_track_lufs (miss): ['get_track', 'get_track_by_source_id']
  DB reads for one _enrich_track_lufs (hit by id): ['get_track']
  ```
  (script: `%TEMP%\opencode\wn05_probe4.py`.)
- **Suggested fix:** enrich once and reuse — e.g. compute the enriched dict in `play_track` and hand it to the engine so `_on_track_changed` does not re-probe, and/or add a small LRU keyed by `(source, source_id)` for the LUFS value. The `loudness_lufs` column is already indexed by track id, so the `get_track` path is cheap; the `get_track_by_path`/`get_track_by_source_id` fallbacks are the ones to avoid.
- **Fix side effects:** a stale LUFS value would be served if the scanner updates the row after the cache is filled; the LUFS scanner (`services/lufs_scanner.py`, WN-25) writes asynchronously, so a short TTL is needed. `tests/test_lufs_resources.py` (WN-34) may assert current behaviour.
- **Discovered by:** B

#### F-WN-05-9  [P2] — The Yandex OAuth token is stored in plaintext in SQLite, and the loopback proxy's bearer token is handed to the webview

- **File:** `core/api.py:1902-1954` (`yandex_device_auth`), `core/api.py:1930-1932` (the token write), `core/api.py:1398-1405` (`get_proxy_info`), `core/settings.py:413-418` (`set`), `core/database.py:2049-2082` (`set_settings_batch`), `core/proxy.py:1300-1302` (`auth_query`)
- **Confirmed:** yes
- **Description:**
  - **At rest:** the device-auth token is written with `self._core.settings.set("auth", "yandex_token", token.access_token)` → `SettingsManager.set` → `db.set_settings_batch` → `INSERT OR REPLACE INTO settings (key, value, …)`. The value is a plain JSON string; there is no DPAPI/`CryptProtectData`/keyring anywhere in the repository (grep for `CryptProtectData|win32crypt|dpapi|keyring` → no matches). The token sits in cleartext in `~/.nedotify/nedotify_storage.db`.
  - **In flight to the webview:** `get_proxy_info()` returns `{"port": …, "token": …}` — the per-session bearer for the loopback proxy, which is the component that forwards the user's Yandex OAuth token upstream (`core/proxy.py:1004-1006`: `req.add_header('Authorization', f'OAuth {token}')`) and the provider cookies.
  - **Not leaked by this method:** the token is *not* returned to the frontend — `yandex_device_auth` answers `{"success": True, "message": …}`, the `yandex_device_auth_code` event carries only the device code and the verification URL, and the bridge masks the secret on read (`core/api.py:1860-1861`, `core/api.py:240`). The token is also never logged (the exception logger at `core/api.py:1944` prints only the exception).
- **Cause:** the app treats the local SQLite file as a trusted secret store. It is not: it is a plain file in the user's profile, readable by every process running as that user, and routinely captured by profile-sync/backup tooling.
- **Trigger conditions:** the user completes the Yandex device authorization. From then on the bearer sits in cleartext until the user revokes it.
- **User impact:** any process running as the user (or a stolen/backup copy of the profile) can read a token that grants full read/write access to the user's Yandex Music account. The `k=` proxy bearer is also visible to any script that can run in the webview, but that one is *structurally* required (the frontend builds `<audio>` URLs itself) and is only exploitable together with a webview XSS.
- **Evidence:**
  ```python
  # core/api.py:1929-1932
  token = client.device_auth(on_code=_on_code, timeout=300)
  if token and getattr(token, "access_token", ""):
      self._core.settings.set("auth", "yandex_token", token.access_token)   # cleartext at rest
      self._core.settings.set("auth", "yandex_token_valid", True)
  ```
  ```python
  # core/api.py:1398-1405
  def get_proxy_info(self):
      """Return proxy port and auth token for local asset requests."""
      if hasattr(self._core, 'proxy') and self._core.proxy:
          return {"port": getattr(self._core.proxy, "port", 0),
                  "token": getattr(self._core.proxy, "token", "")}
  ```
  ```python
  # core/database.py:2074-2078  -- plain value column
  conn.executemany(
      "INSERT OR REPLACE INTO settings (key, value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
      rows,
  )
  ```
- **Reproduction / verification:** read the code path end-to-end (`core/api.py:1931` → `core/settings.py:417` → `core/settings.py:456-459` → `core/database.py:2074`); the value is stored verbatim. To confirm at rest, inspect `SELECT value FROM settings WHERE key='auth.yandex_token'` in a throwaway DB — **not** performed on the real `~/.nedotify` (the ground rules forbid touching it).
- **Suggested fix:** protect the secret at rest with DPAPI (`CryptProtectData`, i.e. `win32crypt`) behind a small `core/secret_store.py` helper, keeping the plaintext value only in memory; fall back to plaintext only if DPAPI is unavailable, and log that fact. The `has_yandex_token` flag the bridge already returns is the right shape for the UI and does not need to change.
- **Fix side effects:** the token must be decrypted on every use — `services/yandex_service.py:41` and `core/proxy.py:1004` read it per request/初始化, so a per-call DPAPI decrypt adds latency and can fail after a machine/Credential-Manager reset (the user would have to re-authorize). `core/proxy.py` (WN-11) and `services/yandex_service.py` (WN-21) must both be changed, so this is a cross-area change, not a WN-05-local one.
- **Discovered by:** B

#### F-WN-05-10  [P2] — `remove_from_queue` performs a check-then-act on the queue's current index outside the queue's lock

- **File:** `core/api.py:1819-1836` (`remove_from_queue`), `audio/queue.py:173-191` (`remove_track`)
- **Confirmed:** hypothesis (the code shape is confirmed; the interleaving was not reproduced)
- **Description:** `remove_from_queue` reads `queue._current_index` (an unguarded private read) and `len(queue.tracks)`, decides "this is the current track, refuse", and only then calls `queue.remove_track(index)` — which re-acquires the queue lock and adjusts `_current_index` itself. The two steps are not atomic with respect to the queue.
- **Cause:** the guard lives in the bridge instead of inside `PlaybackQueue.remove_track`, so the invariant "the current track is never removed" is enforced in two places, one of which is not under the lock.
- **Trigger conditions:** a `next_track` (from the `ended` handler, `js/player.js:644-647`) advancing `_current_index` between the bridge's check and the queue's removal.
- **User impact:** the track the user is currently hearing can be removed from the queue; `PlaybackQueue.remove_track` then re-points `_current_index` at a neighbour, so the player keeps playing a track that is no longer in the queue and "Next" skips one.
- **Evidence:**
  ```python
  # core/api.py:1826-1831
  queue = self._core.engine.queue
  if not (0 <= index < len(queue.tracks)):
      return {"success": False, "error": "Неверный индекс очереди"}
  if index == queue._current_index:                       # <-- read outside the queue's lock
      return {"success": False, "error": "Cannot remove current track"}
  queue.remove_track(index)                              # <-- separate lock acquisition
  ```
  ```python
  # audio/queue.py:186-191
  if len(self._tracks) == 0:
      self._current_index = -1
  elif index < self._current_index:
      self._current_index -= 1
  elif index == self._current_index:
      self._current_index = min(self._current_index, len(self._tracks) - 1)
  ```
- **Reproduction / verification:** **not reproduced.** The window is microseconds wide and the bridge and the 'ended' handler are separate pywebview bridge threads, so the interleaving is possible but rare. Missing evidence: a deterministic test that interleaves `engine.next_track()` between the check and the removal (e.g. by patching `PlaybackQueue.tracks` to block). The static shape — a private read outside the lock, followed by a separately-locked mutation — is unambiguous.
- **Suggested fix:** move the invariant into `PlaybackQueue.remove_track` (WN-17): have it refuse to remove the current track, or accept an explicit `allow_current=False` and return a status the bridge maps to its error message. Then the bridge makes one call and the invariant lives in one place.
- **Fix side effects:** `PlaybackQueue.remove_track` currently returns `None`; changing it to return a status is an API change for WN-17. `js/queue.js:194-196` already guards the current track client-side, so the visible behaviour does not change.
- **Discovered by:** B

#### F-WN-05-11  [P3] — The listening telemetry borrows the global `_window_op_lock` and performs SQLite writes while holding it

- **File:** `core/api.py:353` (the lock's creation), `core/api.py:1211-1212`, `1269-1288`, `1297-1302`, `1310-1330`, `1334-1353`, `1364-1372`, `1411-1417` (the telemetry users), `core/api.py:731` (a window operation under the same lock), `core/api.py:2236`, `2253`, `2256`, `2985`, `3006`, `3466`, `3481`, `3484` (four other areas' users)
- **Confirmed:** yes
- **Description:** `_window_op_lock` is a single `RLock` used as the mutex for **six unrelated concerns**: native window operations, the listening-session state, the lyrics/album request id, the storage/quota scan, the artist-profile request id and the catalog-service construction. The playback telemetry — `report_position` (every 5 s), `report_state`, `report_listening_state`, `maybe_log_history`, `flush_listening`, `_on_track_changed` — is layered on top of it. Worse, `_persist_listening` runs a SQLite `UPDATE` **inside** the lock (`core/api.py:1281`, `1302`, `1352`, `1370`, `1417`), and `maybe_log_history` runs an `INSERT` + `UPDATE` inside it (`core/api.py:1310-1327`, called from `report_listening_state` at `core/api.py:1341` — i.e. while the lock is already held).
- **Cause:** the listening telemetry was given no lock of its own, so it joined the class's existing lock (the AGENTS.md rule) — but the existing lock belongs to a *different* concern. The rule "a new shared field joins its class's existing lock" is being satisfied at the cost of a global critical section.
- **Trigger conditions:** always. The window operations are the concerning holder: `_deferred_window_op` (`core/api.py:721-735`) takes the lock and then performs a native `window.resize()`/`move()` — a Win32 round-trip to the UI thread — while holding it.
- **User impact:** the position heartbeat, the state report and the "start of a play" history write all queue behind a native window operation or a storage scan. A slow UI thread therefore delays `report_position`/`report_state`, which delays the `state_changed` emit and the history write. The measurement itself is protected (the 15 s delta cap in `core/listening.py:27` prevents over-counting), so the user-visible effect is delayed telemetry rather than wrong telemetry.
- **Evidence:**
  ```python
  # core/api.py:721-735
  def _deferred_window_op(self, delay: float, fn):
      def _run():
          time.sleep(delay)
          try:
              with self._window_op_lock:      # <-- global lock held across a native call
                  fn()
  ```
  ```python
  # core/api.py:1334-1352
  with self._window_op_lock:
      session = self._listening_sessions.get(listening_session)
      ...
      if audible and session.history_id is None:
          self.maybe_log_history()          # <-- INSERT + UPDATE inside the lock
      ...
      self._persist_listening(session)      # <-- UPDATE inside the lock
  ```
- **Reproduction / verification:** the lock's user set is enumerable from the source: `grep -n "_window_op_lock" core/api.py` → 23 hits across 6 concerns (lines 731, 1211, 1269, 1298, 1310, 1334, 1364, 1411, 1452, 2236, 2253, 2256, 2985, 3006, 3466, 3481, 3484). The DB-inside-the-lock part was confirmed by the spy in F-WN-05-7 (10 `report_position` calls → 10 `UPDATE history` transactions, each taken while the lock was held).
- **Suggested fix:** give the listening telemetry its own lock (`self._listening_lock`), and move the SQLite writes out of the critical section (compute the value under the lock, write outside it). Independently, `_window_op_lock` should be split per concern (window ops / request-id guards) — that part belongs to WN-04 and WN-09.
- **Fix side effects:** the `_listening_sessions` dict, `_active_listening_token` and `_history_logged_key` are the only state guarded by it; moving them to a dedicated lock is a contained change, but `maybe_log_history`'s check-then-write sequence must stay atomic (`tests/test_api_f1_audit.py:327-338` asserts 8 concurrent `maybe_log_history` calls produce exactly one history row).
- **Discovered by:** B

#### F-WN-05-12  [P3] — `yandex_device_auth` spawns an untracked, uncancellable 5-minute worker with no re-entrancy guard

- **File:** `core/api.py:1902-1954`, in particular `core/api.py:1929` (`device_auth(..., timeout=300)`) and `core/api.py:1950` (`threading.Thread(target=_worker, daemon=True).start()`)
- **Confirmed:** yes
- **Description:** the bridge method returns immediately and runs the device-code flow on a fresh daemon thread that is never registered, never joined and never cancelled. There is no "an authorization is already in flight" flag, so two clicks start two concurrent device-auth flows and the user sees two user codes. The worker can also outlive the app's shutdown: `core/app.py:508-560` (`cleanup`) stops the proxy, the downloader and closes the database, but nothing stops this worker, so it can still `self._core.settings.set("auth", "yandex_token", …)` (→ a write on a closed database, `core/api.py:1931`) and `self._emit("yandex_device_auth_result", …)` (→ an event to a window that is being torn down) after cleanup has run.
- **Cause:** the bridge has no lifecycle handle for long-running background work it starts itself.
- **Trigger conditions:** the user clicks "Authorize" (twice, or once and then closes the app during the 5-minute device-code window).
- **User impact:** a second, confusing authorization prompt; a possible lost token if the app is closed between the device approval and the write (the token is written after the 5-minute `device_auth` call returns, and `SettingsManager`'s write-behind flushes 0.5 s later — if the process exits in that window the token is gone even though the user approved it).
- **Evidence:**
  ```python
  # core/api.py:1929-1950
  token = client.device_auth(on_code=_on_code, timeout=300)
  if token and getattr(token, "access_token", ""):
      self._core.settings.set("auth", "yandex_token", token.access_token)
      ...
  threading.Thread(target=_worker, daemon=True).start()
  ```
  ```python
  # core/app.py:530-531 -- cleanup flushes listening but knows nothing about this worker
  if getattr(self, 'api', None) and hasattr(self.api, 'flush_listening'):
      _step('listening history', self.api.flush_listening)
  ```
- **Reproduction / verification:** the absence of a handle and of a guard is directly readable. Not reproduced at runtime: driving `yandex_music.Client.device_auth` needs the real library and a network round-trip to Yandex (out of bounds for this run). Missing evidence: a stub-level test showing two concurrent calls produce two `yandex_device_auth_code` events.
- **Suggested fix:** keep the worker handle on `AppApi` (e.g. `self._auth_thread`), refuse a second call while one is alive, and join/cancel it in `AppApi.cleanup()` (`core/api.py:446-459`) — and flush the settings synchronously (`SettingsManager.sync_flush_now`, `core/settings.py:420-441`) right after writing the token so an approved token is never lost.
- **Fix side effects:** refusing a second call changes the UI contract — `js/settings.js:443-444` fires `yandex_device_auth()` and awaits `{success, message}`; it would need to show "authorization already in progress". `core/app.py::cleanup` (WN-02) must call the new hook.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct in this range:

- **`_emit` never runs on the UI thread** (`core/api.py:1122-1159`): the main-thread branch hands off to an `EmitWorker` thread; every WN-05 method emits from a bridge/worker thread. `tests/test_emit_thread_safety.py` pins this, including the falsy-payload and unserialisable-payload cases.
- **Event names and payload shapes match the frontend** — verified name-by-name against `ui/web_new_v2/js/events.js`: `track_changed` (L97), `state_changed` (L103, the `{state, elapsed_ms}` dict is correctly normalised to a string), `position_changed` (L110, `position_ms`/`duration_ms` are read), `queue_updated` (L283), `queue_ended` (L396), `shuffle_changed` (L288, `{"state": bool}`), `repeat_changed` (L297, `{"state": mode}`), `mute_changed` (L392, `{"muted": bool}`), `audio_error` (L378, `title`/`message`), `yandex_device_auth_code` / `yandex_device_auth_result` (L370/L374). No renamed or missing event in this range.
- **Repeat-mode strings are identical on both sides**: `audio/queue.py:272` cycles `["off", "all", "one"]`; `js/events.js:298-303` and `js/player.js:946` compare against `'off'` and `'one'`. `api.toggle_repeat`'s docstring ("off → all → one → off") matches the implementation.
- **The queue-end contract is wired correctly**: `PlaybackQueue.next_track()` returns `None` at the end (`audio/queue.py:227-229`), `AudioEngine.next_track()` calls the `_on_queue_end` hook (`audio/engine.py:61-62`), and `AppApi.__init__` assigns it (`core/api.py:380`) — the hook that used to be dead code is now live and emits `queue_ended` exactly once per exhaustion.
- **`get_next_track` does not wrap the queue**: it returns `None` at the end unless `repeat == "all"` (`core/api.py:2035-2037`), matching `PlaybackQueue.next_track()`; `tests/test_api_audit_b.py:102-120` pins it. This is the fix for the "preloader cached the first track on the last track" bug and it is correct.
- **The listening-session identity guard is sound**: `_listening_identity` (`core/api.py:1262-1265`) plus the token check in `report_state`/`report_position`/`report_listening_state` prevent a stale session from writing history. `tests/test_measured_listening.py:65-78` (`test_track_switch_stale_state_and_close_do_not_mix_history`) and `80-87` (re-resolve keeps one session) pin exactly this — the telemetry side of the play path is well covered.
- **Secret masking on the read path works**: `get_setting` (`core/api.py:1860-1861`), `get_settings` (`core/api.py:2925`, `2935`) and `get_settings_by_category` (`core/api.py:2959`) all mask `auth.yandex_token` / `auth.oauth_client_secret` and expose a `has_*` flag instead; a blank secret write does not wipe the stored value (`core/api.py:1884-1885`, `1893-1894`). `tests/test_api_f1_audit.py:36-84` pins this. The token is **not** returned to the frontend by any method in this range.
- **`toggle_mute` / `is_muted` are coherent**: the persisted `audio.muted` flag is the single source of truth, the new state is returned *and* emitted as `mute_changed`, and the frontend applies it via `applyMuteState` (`js/player.js:1209-1215`, `2032-2040`). `tests/test_api_audit_b.py:75-97` pins it.
- **`PlaybackQueue` is properly locked**: every mutator (`set_tracks`, `add_track`, `add_tracks`, `remove_track`, `move_track`, `next_track`, `previous_track`, `toggle_shuffle`, `toggle_repeat`, `jump_to`, `clear`) takes `self._lock` (`audio/queue.py:15`), and the properties lock their reads. The bridge's problems (F-6, F-10) are about *composing* multiple locked reads, not about the queue's own locking.
- **`_on_audio_error` payload contract is consistent** with `core/user_errors.py::describe_error` and with `js/events.js:378-386` (`title` / `message` / `user_message` / `code` / `action`).

---

### 4. Coverage gaps

- **No live app run.** Per the ground rules the real app was never launched, so the *WebView2 IPC* cost of a 726 KB `queue_updated` payload (F-WN-05-5) is extrapolated from a local `json.dumps` measurement (3.7 ms) plus the known per-call overhead; the end-to-end stall was not observed in the UI.
- **F-WN-05-10 (remove_from_queue TOCTOU) was not reproduced** — a deterministic interleaving harness (patching `PlaybackQueue.tracks` to block between the check and the removal) was not written. The code shape is confirmed; the runtime manifestation remains a hypothesis.
- **`core/resolver.py` single-flight and `core/playback_recovery.py` were not audited** (WN-15). I confirmed only that `core/app.py:296-506` spawns an untracked daemon thread per resolution and that it is not cancelled on shutdown; whether the resolver's own single-flight collapses two concurrent resolutions into one callback (which would change the F-WN-05-3 analysis) was not verified.
- **The proxy's threat model was not audited** (WN-11). I verified that the `k=` bearer appears in `stream_url` payloads and is returned by `get_proxy_info`, but not whether the proxy's `/api/stream` handler can be abused once the token is known.
- **Gapless / crossfade interleaving** (frontend `playTrack` vs. backend `next_track`) straddles WN-29 and WX-10; I established the mechanics (F-2, F-3) but did not model the full transition matrix.
- **`services/yandex_service.py` and `core/proxy.py` consumers of the OAuth token** were read only far enough to establish that the token is used as a bearer (`core/proxy.py:1004-1006`); the full credential-handling audit belongs to WN-21/WN-11.
- **Cross-area note, not claimed as a WN-05 finding:** `js/player.js:1973-1992` (`applySettings`) reads `settings.shuffle` / `settings.repeat` at the *top level* of the settings tree, but `AppApi.get_settings()` returns a *category* tree (`core/api.py:2929-2938`) whose shuffle/repeat live under `session.shuffle` / `session.repeat` (`core/settings.py:256-263`). `settings.repeat` is therefore `undefined`, and `undefined !== 'off'` evaluates to `true`, so the repeat button is painted as active on every `applySettings` call. That is a WN-29 frontend bug, not a WN-05 one, and is reported here only so the WN-29 reviewer can find it.

---

### 5. Architecture improvements (ARCH)

**A-1 — There is no authoritative "what should be playing" state machine.**
The play path is a chain of side effects spread over three layers: `AppApi.play_track` → `AudioEngine.play_queue` → `PlaybackQueue.set_tracks` → `AudioEngine._notify_track_changed` → `AppApi._on_track_changed` → `_emit("track_changed")`, plus a background resolution thread whose callback mutates the *same* dicts that live inside the queue (`core/api.py:1591`, `1634`, `1723`). There is no object that owns "the user's playback intent"; the intent is re-derived at every layer by identity comparison (`is target_track`, `is cur_start`) and by re-reading `queue.current_track`. A single `PlaybackIntent`/`PlaybackController` object — owning the current track, a monotonic generation, the pending resolution and the queue — would make F-WN-05-2, F-WN-05-3 and F-WN-05-10 structurally impossible rather than guarded ad hoc. The frontend already has this model (`playbackGeneration`, `currentQueueVersion` in `js/player.js:22-23`); the backend has no counterpart.

**A-2 — `audio/queue.py` and `audio/engine.py` expose no mutation API, so the bridge reaches into their privates.**
`AppApi` writes `engine._last_reported_position` (`core/api.py:1422`), calls `engine._notify_track_changed()` (`core/api.py:1597`, `1635`, `1733`), reads `queue._current_index` (`core/api.py:1776`, `1829`) and calls `queue.set_tracks`/`queue.clear`/`queue.remove_track`/`queue.move_track` directly (`core/api.py:1784`, `1831`, `1843`, `1846`). The queue's invariant ("the current track is never removed", "the index always points at a live row") is therefore enforced in the bridge as well as in the queue — the duplication that produced F-WN-05-6 and F-WN-05-10. Giving `AudioEngine` a complete mutation surface (`remove`, `reorder`, `clear`, `snapshot`, `set_position`) and hiding `PlaybackQueue` behind it would make the bridge a caller, not a co-owner. (Owning area: WN-17; WN-05 is the caller that suffers from it.)

**A-3 — Three independent proxy-URL builders, with different quoting rules.**
`core/api.py:1218-1223` (`proxy.get_proxy_url`), `core/api.py:2061-2071` (`get_next_track`, which builds the URL by hand) and `audio/engine.py:90-117` (`_notify_track_changed`, which builds it by hand) each construct a `http://127.0.0.1:<port>/api/stream?…&k=<token>` URL. The engine quotes `source` with `safe=""` and `track_id`; `get_next_track` quotes neither `source` nor `track_id`. They also disagree on which parameters are included. A single `ProxyURLBuilder` in `core/proxy.py` (WN-11) that all three call would remove the drift risk — today a `source` value containing a space or a non-ASCII character produces a malformed URL in one path and a correct one in another.

**A-4 — `_window_op_lock` should be split per concern.**
One `RLock` currently serialises native window operations, the listening telemetry, the lyrics/album request id, the storage scan, the artist-profile request id and the catalog-service construction (23 call sites, 6 concerns). Splitting it into `_window_lock`, `_listening_lock`, `_request_id_lock` and `_storage_lock` would remove the false coupling described in F-WN-05-11 and make each subsystem independently testable. (Cross-area: WN-04 owns the window lock.)

**A-5 — The queue and the telemetry have no concurrency tests.**
`tests/test_queue.py` is a pure single-threaded unit test of `PlaybackQueue`; `tests/test_measured_listening.py` exercises the telemetry single-threaded with a fake clock. Nothing in the suite runs two bridge calls concurrently, so the torn-snapshot and check-then-act shapes (F-WN-05-6, F-WN-05-10) are invisible to CI, and the `tests/test_api_f1_audit.py:327-338` concurrent-`maybe_log_history` test is the only concurrency test in the area. A small harness that drives `play_track` / `next_track` / `remove_from_queue` / `reorder_queue` from several threads against one `AppApi` would pin the queue invariants the bridge currently enforces by hand.

**A-6 — `queue_updated` should be a versioned delta, not a full snapshot.**
See F-WN-05-5. The frontend already maintains `currentQueue` and `currentQueueVersion`; a delta protocol (`{version, added[], removed_index, moved{from,to}}`) would turn the O(n²) broadcast into O(Δ) and would also fix the torn-snapshot problem (F-WN-05-6), because a versioned delta is necessarily consistent with the mutation that produced it. This needs a matching change in `js/queue.js` (WN-29).
