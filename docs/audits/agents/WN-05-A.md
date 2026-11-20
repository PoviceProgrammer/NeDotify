## AREA WN-05 — Bridge playback, queue ops, listening telemetry, volume — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py` — L230-409 (helper block + `__init__`), L410-444 (bridge error wrapper), L461-526 (offline interception), L915-954 (`close`), L1120-1164 (`_emit`), **L1161-2080 (the assigned range, in full)**, L2915-3004 (`get_settings` / `save_setting` / `update_setting`, for the duplicate-implementation check).
- `audio/engine.py` — L1-508 (whole file; `play_track`, `play_queue`, `next_track`, `prev_track`, `toggle_shuffle/repeat`, `_notify_track_changed`, `resolve_stream_url`, `_resolve_via_network`).
- `audio/queue.py` — L1-302 (whole file; `PlaybackQueue`: `move_track`, `remove_track`, `add_track(s)`, `next_track`, `previous_track`, `toggle_repeat`, `set_tracks`, `clear`).
- `core/listening.py` — L1-44 (whole file; `ListeningSession.tick/state`).
- `core/settings.py` — L1-589 (whole file; `DEFAULT_SETTINGS`, `SettingsManager.get/set/flush`).
- `core/app.py` — L280-389 and L389-518 (`re_resolve_stream_url_async`, the callback chain), L508-578 (`cleanup` → `flush_listening`).
- `core/database.py` — L1255-1314 (`ensure_track_exists`), L1550-1629 (`add_to_history`, `begin_listening_session`, `update_history_duration`), L1320-1348 (`record_listening_once` deprecation note).
- `main.py` — L400-429, L510-582 (session save on exit, `cleanup()` ordering).
- `ui/web_new_v2/js/events.js` — L60-219, L275-414 (event-name/payload contract for `track_changed`, `state_changed`, `position_changed`, `queue_updated`, `shuffle_changed`, `repeat_changed`, `audio_error`, `error`, `mute_changed`, `queue_ended`, `yandex_device_auth_*`).
- `ui/web_new_v2/js/player.js` — L520-709 (audio event → `report_state` / `report_listening_state` / `report_position` wiring), L845-934, L1650-1769 (`onTrackChanged` → background `play_track`), L1970-2009 (`applySettings`), L2032-2048 (`applyMuteState`), L1172-1220 (volume slider).
- `ui/web_new_v2/js/queue.js` — L80-159 (drawer render + clear), L240-300 (drag → `reorder_queue`).
- `ui/web_new_v2/js/search-discovery.js` — L28-67; `ui/web_new_v2/js/home.js` — L765-794; `ui/web_new_v2/js/settings.js` — L438-487; `ui/web_new_v2/js/hotkeys.js` — L179-221; `ui/web_new_v2/js/utils.js` — L1308-1310, L1346-1360, L1651-1655.
- `tests/conftest.py` — L1-176; `tests/test_api_audit_b.py` — L1-80, L370-489; `tests/test_api_f1_audit.py` — L345-381.

**Callees traced into other areas (defects there are attributed to the owning area, not double-reported here)**

- `audio/engine.py`, `audio/queue.py` → **WN-17**.
- `core/app.py::re_resolve_stream_url_async` → **WN-02** (callback chain, SoundCloud fallback budget).
- `core/resolver.py` — reached only indirectly via `core/app.py`; not opened separately (no WN-05 call site).
- `core/database.py` → **WN-12** (`begin_listening_session`, `update_history_duration`, plaintext settings storage).
- `core/settings.py` → **WN-14**.
- `core/user_errors.py::describe_error` → **WN-16** (only used to shape the `audio_error` payload).
- `ui/web_new_v2/js/player.js`, `js/queue.js`, `js/events.js`, `js/settings.js` → **WN-28 / WN-29 / WN-30**.
- `core/proxy.py` — only the self-heal re-resolve call site (`core/proxy.py:1051`) was noted; it does not go through the WN-05 code under review.

**Reproduction harness** (read-only, outside the repo): `C:\Users\Артур\AppData\Local\Temp\opencode\audit_reports\repro_wn05.py`, `repro_wn05b.py`, `repro_wn05c.py`, run with `& ".venv_win\Scripts\python.exe"`.

---

### 2. Findings

#### F-WN-05-1  [P1] — Stale-resolution race: the FIRST `play_track` to resolve wins, the user's latest click is silently discarded

- **File:** `core/api.py:1714-1737` (`_resolve_track` → `cur_start` / `on_resolved`); `core/api.py:1606` (the solo call site); `audio/engine.py:35-39`
- **Confirmed:** yes
- **Description:** When `play_track` is called **without** a `track_list`, the backend does not touch the queue until the stream has resolved. `_resolve_track` therefore captures `cur_start = self._core.engine.queue.current_track` and, in the async callback, treats "the queue's current track is still the one it was when the request started" as proof that the selection has not changed:
  ```python
  cur_start = self._core.engine.queue.current_track
  ...
  elif self._core.engine.queue.current_track is cur_start:
      # Selection unchanged since resolution started: safe to deliver
      play_callback(track)
  # else: user moved on - drop stale resolution
  ```
  There is **no request token / generation counter**. When the user makes a second `play_track` request while the first is still resolving, the queue has *not* changed yet (the solo path only writes the queue after the resolution succeeds), so the **older** request still satisfies `queue.current_track is cur_start` and calls `play_callback(track)` → `engine.play_track(A)` → `queue.set_tracks([A], 0)`. The **newer** request then resolves, finds that the queue moved on, and drops its result on the floor — with no `audio_error`, no `queue_ended`, and no log line that reaches the user.
- **Cause:** staleness is detected by comparing the queue state before/after, but the solo path leaves the queue unchanged for the whole resolution window, so the queue state cannot distinguish "the user did not change the selection" from "the user changed the selection but the queue has not been updated yet".
- **Trigger conditions:** two **solo** `play_track` calls inside one resolution window. The solo path is live in the shipped UI: `ui/web_new_v2/js/search-discovery.js:43` (`play_track({...entry.track,…})` — the "listened" cards on Home), `ui/web_new_v2/js/home.js:784` (`play_track(trackObj)` when the feed card has no list), `ui/web_new_v2/js/player.js:892/895/898` (resume path when the queue is unknown), `ui/web_new_v2/js/player.js:1704` (background resolution of a stream-less track), `ui/web_new_v2/js/feature-controls.js:69`. A provider that answers A faster than B (very common: different backends / cached vs. uncached) is enough.
- **User impact:** the user clicks track B; **track A starts playing instead** and B is silently ignored. The UI shows A, the queue shows A, and nothing tells the user that B was dropped. This is exactly the "rapid track switching" scenario of WX-10.
- **Evidence:**
  ```python
  # core/api.py:1606  (solo path)
  self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  # core/api.py:1714-1737
  cur_start = self._core.engine.queue.current_track
  def on_resolved(stream_url, metadata=None):
      ...
      if _is_current():
          ...
      elif self._core.engine.queue.current_track is cur_start:
          play_callback(track)
      # else: user moved on - drop stale resolution
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_A_stale_resolution_race_solo` — stub `core.re_resolve_stream_url_async` to capture the callbacks, call `api.play_track(A)` then `api.play_track(B)` (both solo), fire A's callback first and B's second:
  ```
  A) solo race -> queue current source_id = A
     audio_error emitted: []
  ASSERTION FAILED: expected B, got 'A'
  ```
  The list path is *not* affected (`test_B`: `queue current source_id = B`) because `play_track(track, list, idx)` writes the queue synchronously at `core/api.py:1580` before resolving — so the fix must not regress that path.
- **Suggested fix:** add a monotonically increasing request id (e.g. `self._play_request_seq`) incremented in `play_track`; capture it in `_resolve_track` and compare it in `on_resolved` / `on_resolve_error`; deliver only if it is still the newest request. Keep the existing `cur_start`/`_is_current` checks as an additional (not sole) guard.
- **Fix side effects:** the queue-preserving fast path `_deliver()` (`core/api.py:1631-1641`) must be guarded by the same token, otherwise a *stale* fast-path resolution would still overwrite `cur["file_path"]`. The proxy's own self-heal re-resolve (`core/proxy.py:1051`) calls `core/app.py::re_resolve_stream_url_async` directly and does not pass through `_resolve_track`, so it is unaffected.
- **Discovered by:** A

#### F-WN-05-2  [P2] — The solo `play_track` path replaces the whole queue with a single track

- **File:** `core/api.py:1606`; `audio/engine.py:35-39`; `core/api.py:1631-1641` (`_deliver`)
- **Confirmed:** yes
- **Description:** `_resolve_track` only preserves the queue when the resolved track is *already* the current one (`if _is_current() and len(...queue.tracks) > 1: cur["file_path"] = ...`). For any other track the callback is `lambda t: self._core.engine.play_track(t)` → `AudioEngine.play_track` → `self.queue.set_tracks([track], start_index=0)` — which **discards every other queued track**, the shuffle order and the history stack.
- **Cause:** the solo entry point has no notion of "insert into the existing queue"; `play_track` (engine) is the *replace-the-queue* primitive, whereas the solo bridge path needs an *insert/append* semantic.
- **Trigger conditions:** any solo `play_track` for a track that is not already current, while a queue exists — e.g. clicking a "listened" card in the Home feed (`js/search-discovery.js:43`) or a feed card without a list (`js/home.js:784`).
- **User impact:** the user's queue (album / playlist / shuffled list) is silently replaced by one track; "next" then immediately ends the queue, and the queue drawer shows a single row. No error, no toast.
- **Evidence:**
  ```python
  # core/api.py:1606
  self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  # audio/engine.py:35-39
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)
      self._notify_track_changed()
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_A_stale_resolution_race_solo` shows `after A resolved -> queue: [{'id': 1, …'source_id': 'A'}]` — the queue contains exactly the one resolved track. `repro_wn05c.py` prints `queue: [None] current: None` after `add_to_queue(None)` (same "queue is whatever was handed over" behaviour).
- **Suggested fix:** in the solo path, append/insert the resolved track into the existing queue (e.g. `engine.add_to_queue(track, play_next=False)` then `engine.queue.jump_to(...)`) instead of `engine.play_track(track)`; or make the frontend always pass a list.
- **Fix side effects:** the frontend keeps its own `window.currentQueue` copy (`js/queue.js:82`), so after the change the backend queue and the frontend copy would diverge until `loadQueue()` runs — the drawer must be reloaded after the resolve.
- **Discovered by:** A

#### F-WN-05-3  [P2] — `reorder_queue` validates nothing: out-of-range indices are a silent no-op, non-int indices raise `TypeError` out of the bridge

- **File:** `core/api.py:1782-1785`; `audio/queue.py:193-213`; `ui/web_new_v2/js/queue.js:261-293`
- **Confirmed:** yes
- **Description:** `reorder_queue` forwards its two arguments straight to `PlaybackQueue.move_track`, which does `if 0 <= old_index < len(self._tracks) and 0 <= new_index < len(self._tracks)`. A `new_index == len(tracks)` (the canonical "drag to the end" slot) is **rejected silently** — the queue does not move, no error is produced, and `reorder_queue` still emits `queue_updated` as if something had happened. A non-integer index (`"0"`, `1.0`) raises `TypeError` inside `move_track`; the bridge wrapper (`core/api.py:427-441`) logs it, emits `api_error` and **re-raises**, so the JS promise rejects and the reorder is lost.
- **Cause:** the bridge method performs no argument normalisation and no bounds check of its own, and it does not report the outcome of the move.
- **Trigger conditions:** the "drag to the very end" position (the frontend currently compensates with `if (draggedItemIndex < insertIndex) insertIndex--`, so this is *latent* for the shipped UI but reachable from any other caller), or a float/string index.
- **User impact:** the reorder silently does nothing (the UI shows the unchanged order) or raises in JS; the user gets no explanation.
- **Evidence:**
  ```python
  # core/api.py:1782-1785
  def reorder_queue(self, old_index: int, new_index: int):
      """Move track from old_index to new_index in queue."""
      self._core.engine.queue.move_track(old_index, new_index)
      self._emit("queue_updated", self.get_queue())
  # audio/queue.py:196
  if 0 <= old_index < len(self._tracks) and 0 <= new_index < len(self._tracks):
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_C_reorder_out_of_range`:
  ```
  C) reorder_queue(0, 3): before=[0, 1, 2] after=[0, 1, 2]  (no error, no change)
     reorder_queue('0', 1) raised TypeError: '<=' not supported between instances of 'int' and 'str'
     reorder_queue(0, 1.0) raised TypeError: 'float' object cannot be interpreted as an integer
  ```
  (both TypeErrors were additionally logged by the bridge wrapper as `bridge call reorder_queue() failed`).
- **Suggested fix:** normalise in `reorder_queue` — `int(old_index)`, `int(new_index)`, reject negatives, and treat `new_index == len(tracks)` as "append to the end"; return a result dict (`{"success": bool}`) so the caller can tell whether the move happened.
- **Fix side effects:** clamping `new_index` to `len-1` would change the "move to end" semantics; the frontend's own arithmetic must be reconciled with the backend's convention or the last-slot drag will keep misbehaving.
- **Discovered by:** A

#### F-WN-05-4  [P2] — `set_volume` persists any value verbatim (no clamp, no type check) and `get_volume` hands it back unchanged

- **File:** `core/api.py:1956-1962`; `core/settings.py:71-85` (`audio.volume` default 70); `ui/web_new_v2/js/player.js:1973-1992` (`applySettings`)
- **Confirmed:** yes
- **Description:**
  ```python
  def set_volume(self, volume: int):
      """Set playback volume (0-100)."""
      self._core.settings.set("audio", "volume", volume)

  def get_volume(self):
      """Return current volume level."""
      return self._core.settings.get("audio", "volume", 70)
  ```
  The docstring promises 0-100 but nothing enforces it. `500`, `-20` and even the string `'abc'` are written to the settings table and read back unchanged.
- **Cause:** the bridge trusts the caller; `SettingsManager.set` stores whatever it is given.
- **Trigger conditions:** any caller that passes an unclamped value. The shipped slider clamps (`js/player.js:1178` `Math.round(pct*100)`, `js/player.js:1198` `Math.max(0, Math.min(100, …))`), so the defect is currently *latent* — but the value is persisted in SQLite and survives restarts, and `applySettings` (`js/player.js:1986-1991`) assigns it to `currentVolume` **without clamping**, then renders `volFill.style.width = '${currentVolume}%'` and picks the volume icon from an out-of-range number.
- **User impact:** a single out-of-range write permanently poisons the persisted volume: the slider shows an impossible fill, the icon is wrong, and the app never self-heals the stored value. A negative value is also read back by `main.py:560` into the saved session.
- **Evidence:** see the snippet above; `core/settings.py:83` shows `"volume": 70` as the only bound.
- **Reproduction / verification:** `repro_wn05b.py::test_D_volume_no_clamp`:
  ```
  D) set_volume(500) -> get_volume() = 500
  D) set_volume(-20) -> get_volume() = -20
  D) set_volume('abc') -> get_volume() = 'abc'
  D) set_volume(150) -> get_volume() = 150
  ```
- **Suggested fix:** clamp and coerce inside `set_volume` (`try: v = int(volume) except: v = 70`, then `max(0, min(100, v))`), and clamp again on read in `get_volume` so a poisoned legacy row is healed on the next start.
- **Fix side effects:** a value of `'abc'` would become 70 rather than raising — the frontend never sends one, so this only changes failure behaviour.
- **Discovered by:** A

#### F-WN-05-5  [P2] — `get_setting`/`set_setting` are a second, divergent settings API: a bare key is written to the **`zapret`** category and autostart is never synced

- **File:** `core/api.py:1853-1900` (WN-05 copies) vs `core/api.py:2922-2962` (`get_settings` / `save_setting` / `update_setting`, WN-08 copies)
- **Confirmed:** yes
- **Description:** the area contains two implementations of the same operation with different semantics:
  | | WN-05 `set_setting` (L1871) | WN-08 `save_setting` / `update_setting` (L2940 / L2961) |
  |---|---|---|
  | return value | `{"success": bool, "error": str}` | `bool` |
  | bare key | **accepted**, routed to the `zapret` category | impossible (category is explicit) |
  | autostart side-effect | **none** | calls `update_autostart()` |
  | secret masking on read | `get_setting` returns `""` | `get_settings` returns `""` **plus `has_<key>` flags** |
  The bare-key rule is also *asymmetric inside the same area*: `get_setting` explicitly refuses bare keys ("Bare keys are ambiguous (they used to silently hit the 'zapret' category); refuse them instead of returning a surprise value", L1863-1866), while `set_setting` performs exactly the write that comment warns about.
- **Cause:** the two methods were written independently and never reconciled; the `zapret` default in `set_setting` (`cat, k = "zapret", full_key`, L1880) is a leftover.
- **Trigger conditions:** any caller of `set_setting` with a key that has no dot — e.g. `set_setting('autostart', True)` silently creates `zapret.autostart`.
- **User impact:** a setting written through `set_setting` lands in the wrong category (the value is then invisible to the real reader) and, for `general.autostart`, the Windows autostart entry is never registered even though the setting says it is on — the app claims to start with Windows but does not.
- **Evidence:**
  ```python
  # core/api.py:1877-1888
  if "." in full_key:
      cat, k = full_key.split(".", 1)
  else:
      cat, k = "zapret", full_key
  err = _bridge_write_error(cat, k, val)
  ...
  self._core.settings.set(cat, k, val)
  ```
  vs `core/api.py:2947-2951`:
  ```python
  if key == "autostart" or key == "general.autostart" or (category == "general" and key == "autostart"):
      try:
          self.update_autostart(bool(value))
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_E_set_setting_bare_key_goes_to_zapret`:
  ```
  E) set_setting('autostart', True) -> {'success': True}
     core.settings.get('zapret','autostart') = True
     core.settings.get('general','autostart') = None
     get_setting('autostart') -> 'MISSING'
     set_setting('general.autostart', True) -> {'success': True}
     core.settings.get('general','autostart') = True
     save_setting('autostart', True, 'general') -> True
  ```
- **Suggested fix:** delete the duplicates and route `get_setting`/`set_setting` to `get_settings`/`save_setting` (or make `set_setting` a thin wrapper with the same return shape and the same autostart side effect); refuse bare keys in `set_setting` exactly as `get_setting` does.
- **Fix side effects:** the return shape of `set_setting` is part of its public bridge contract; changing `{"success": …}` to `bool` would break any external caller. Today the shipped frontend calls **`save_setting` exclusively** (`js/settings.js:1045`, `js/hotkeys.js:141`, `js/player.js:235/289`, `js/profile.js:161`, `js/visualizer.js:71/72/195`, `js/equalizer.js:345`, `js/utils.js:1309`, `js/lyrics.js:125/177`) — `set_setting`/`get_setting` have **zero** frontend callers, so the divergence is latent today. Cross-reference: the settings surface itself belongs to **WN-08 / WN-14**.
- **Discovered by:** A

#### F-WN-05-6  [P3] — `yandex_device_auth`: parallel device flows on repeated calls, plaintext token storage, and an offline payload that the frontend cannot render

- **File:** `core/api.py:1902-1954`; `core/api.py:504-506` (the offline interception of the same method); `ui/web_new_v2/js/settings.js:443-486`
- **Confirmed:** yes (concurrency + payload); the plaintext-storage part is confirmed by reading `core/database.py` (no encryption path exists)
- **Description:** three separate problems in one method:
  1. **No re-entrancy guard.** Every call spawns another `threading.Thread(target=_worker)` that runs its own `client.device_auth(on_code=_on_code, timeout=300)`. Two calls ⇒ two live OAuth device flows, two `yandex_device_auth_code` events (the second overwrites the first code shown to the user) and two `yandex_device_auth_result` events.
  2. **The token is persisted in clear text.** `self._core.settings.set("auth", "yandex_token", token.access_token)` → `core/settings.py` → `core/database.py::set_setting` → plain row in `~/.nedotify/nedotify_storage.db`. The bridge read paths mask it (`_SECRET_SETTING_KEYS`, `core/api.py:240`), but the value at rest is not protected.
  3. **The offline path uses a different payload key.** `core/api.py:505` emits `yandex_device_auth_result` as `{"success": False, "error": "Включён офлайн-режим"}`, while every other path emits `{"success": …, "message": …}`. The frontend renders `data.message || ''` (`js/settings.js:482`) → the status line is displayed **empty** in offline mode.
- **Cause:** the method was written as a fire-and-forget worker with no state, and the offline interception (a different area's code path) was written against a different payload shape.
- **Trigger conditions:** (1) the user double-clicks "Authorise Yandex Music" or the button is re-enabled while the first flow is still running (the button is only re-enabled when a result arrives, so this needs two quick clicks or a retry); (2) any successful authorisation; (3) offline mode + the Yandex auth button.
- **User impact:** (1) the user is shown a stale/overwritten device code and the flow they did not start can win; (2) a long-lived OAuth token sits unencrypted in the user's profile; (3) in offline mode the auth status area shows a blank red line instead of an explanation.
- **Evidence:**
  ```python
  # core/api.py:1929-1937
  token = client.device_auth(on_code=_on_code, timeout=300)
  if token and getattr(token, "access_token", ""):
      self._core.settings.set("auth", "yandex_token", token.access_token)
  # core/api.py:504-506 (offline interception of the SAME method)
  if method == 'yandex_device_auth':
      self._emit('yandex_device_auth_result', {'success': False, 'error': 'Включён офлайн-режим'})
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_N_yandex_device_auth_double_start`:
  ```
  N) yandex_device_auth x2 -> {'success': True, …} {'success': True, …}  device_auth calls: 2
     events: ['yandex_device_auth_result', 'yandex_device_auth_result']
  ```
  The offline payload shape is visible in the code above and in `js/settings.js:482`.
- **Suggested fix:** keep a `self._yandex_auth_inflight` flag and return early (or the in-flight result) when a flow is already running; emit the offline result with the `message` key so the frontend renders it; at-rest protection for the token belongs to WN-12/WN-14 (DPAPI / OS keyring) — the write site here should at least stop writing the token to an unprotected plain column.
- **Fix side effects:** the in-flight guard must be reset in a `finally:` block, otherwise a crashed flow would block all future authorisations.
- **Discovered by:** A

#### F-WN-05-7  [P3] — `next_track()` on an **empty** queue publishes a false `queue_ended` (and tears down the player)

- **File:** `core/api.py:1761-1765`; `core/api.py:1244-1253` (`_on_queue_end`); `audio/engine.py:55-63`; `audio/queue.py:215-219`; `ui/web_new_v2/js/events.js:396-403`
- **Confirmed:** yes
- **Description:** `PlaybackQueue.next_track()` returns `None` both for *"the queue is exhausted"* and for *"the queue is empty"* (`if self.is_empty: return None`, `audio/queue.py:218-219`). `AudioEngine.next_track` cannot tell them apart and calls `self._on_queue_end()` for both, so `AppApi._on_queue_end` publishes `queue_ended` even though nothing was ever playing. The frontend handler then calls `stopPlaybackForQueueEnd()` and `onStateChanged('stopped')`.
- **Cause:** the "empty" and "exhausted" states are conflated one level below the bridge. The root cause sits in `audio/queue.py` (**WN-17**); the false event is published by WN-05's `_on_queue_end`.
- **Trigger conditions:** pressing "next" (button, hotkey `Ctrl+ArrowRight`, or the OS media key `MediaTrackNext`) while the queue is empty — e.g. right after startup, or after `clear_queue()` on an empty queue.
- **User impact:** the player UI is torn down (`stopPlaybackForQueueEnd`, `js/player.js:1850` region) and `events.js:383`-style resets (the frontend clears `window._pendingResolveKey` on `audio_error`, and `stopPlaybackForQueueEnd` clears the pending-resolve state) can abandon an in-flight background resolution that was about to succeed.
- **Evidence:**
  ```python
  # audio/engine.py:55-63
  def next_track(self):
      track = self.queue.next_track()
      if track:
          self._notify_track_changed()
          return track
      if self._on_queue_end:
          self._on_queue_end()
      return None
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_K_next_track_empty_queue`:
  ```
  K) next_track() on empty queue -> events: ['queue_ended']
  ```
  (With `repeat='one'` the same call correctly produces **no** `queue_ended` — `test_L` — so the exhausted path itself is correct.)
- **Suggested fix:** in `AppApi.next_track`, check `self._core.engine.queue.count == 0` first and return without notifying; or make `PlaybackQueue.next_track` distinguish "empty" from "exhausted" (WN-17) and have the engine only fire `_on_queue_end` for the latter.
- **Fix side effects:** the autoplay/flow logic in `js/player.js:644-656` relies on `next_track()` returning a falsy value to mean "nothing advanced" — returning `None` early keeps that contract.
- **Discovered by:** A

#### F-WN-05-8  [P3] — `add_to_queue` accepts a non-dict and `add_tracks_to_queue` reports a `count` it did not add

- **File:** `core/api.py:1797-1817`; `audio/queue.py:134-171`
- **Confirmed:** yes
- **Description:** neither method validates its payload. `add_to_queue(None)` returns `{"success": True}` and appends `None` to the queue; `queue.add_track` then sets `_current_index = 0` because the queue has exactly one element, so `queue.current_track` becomes `None` and `get_queue()` publishes `"current_track": null`. `add_tracks_to_queue([1, 2, 'x'])` returns `{"success": True, "count": 3}` although `PlaybackQueue.add_tracks` skips every non-dict (`if not isinstance(track, dict): continue`) and the queue is left unchanged — the count is a lie.
- **Cause:** the bridge forwards the raw JS value without a type check; `count` is computed from the input length rather than from the number of items actually enqueued.
- **Trigger conditions:** a malformed caller (a plugin, a future UI path, or a corrupted JS payload). The shipped frontend always sends dicts.
- **User impact:** a `None` entry in the queue is published to the queue drawer (`js/queue.js:143-159` calls `getCoverUrl(track._trackData)` on every row) → a rendering error in the drawer; and the reported `count` misleads the caller.
- **Evidence:**
  ```python
  # core/api.py:1797-1805
  def add_to_queue(self, track: dict):
      try:
          self._core.engine.add_to_queue(track, play_next=False)
          self._emit("queue_updated", self.get_queue())
          return {"success": True}
  # core/api.py:1812-1814
  self._core.engine.add_tracks_to_queue(tracks)
  self._emit("queue_updated", self.get_queue())
  return {"success": True, "count": len(tracks)}
  ```
- **Reproduction / verification:** `repro_wn05b.py::test_J_add_to_queue_non_dict_and_count`:
  ```
  J) add_to_queue(None) -> {'success': True}
     queue: [None] current: None
     add_tracks_to_queue([1,2,'x']) -> {'success': True, 'count': 3}
     queue: [None]
  ```
- **Suggested fix:** reject non-dict entries with `{"success": False, "error": …}`; return the number of items actually enqueued.
- **Fix side effects:** none for the current frontend, which always sends dicts.
- **Discovered by:** A

#### F-WN-05-9  [P3] — The listening-telemetry path holds the app-wide `_window_op_lock` across SQLite writes

- **File:** `core/api.py:1334-1353` (`report_listening_state` → `maybe_log_history` → `db.begin_listening_session`), `core/api.py:1411-1417` (`report_position` → `_persist_listening` → `db.update_history_duration`), `core/api.py:1310-1328` (`maybe_log_history`); the same lock is also taken by the window-management, search and lyrics code paths at `core/api.py:731`, `2236`, `3466`
- **Confirmed:** the lock-across-a-DB-write is **confirmed** by reading; the *stall* consequence is a **hypothesis**
- **Description:** `_window_op_lock` is the app's single shared lock — it is the lock used by the window/mini-player operations and is reused by the search and lyrics paths; the listening sessions reuse it too. The telemetry path takes it and then performs a **blocking SQLite write** inside the critical section: `report_position` runs `db.update_history_duration` every time the frontend's 5-second heartbeat arrives, and `maybe_log_history` runs `db.begin_listening_session` (an INSERT plus a `play_count` UPDATE). `core/api.py:1211` (`_on_track_changed`) needs the same lock, so the track-change notification waits behind the telemetry write.
- **Cause:** an I/O-bound operation was placed inside a lock that also guards unrelated UI state, instead of a dedicated listening lock (as `core/listening.py:1` itself states: *"the caller owns the API's existing lock"*).
- **Trigger conditions:** every playback session (a write every 5 s) plus any SQLite contention — WAL checkpointing while the loopback proxy is serving reads (`core/proxy.py`) is the realistic source of a slow write.
- **User impact:** a delayed `track_changed` (the UI keeps showing the old track) — magnitude unverified.
- **Evidence:**
  ```python
  # core/api.py:1411-1417
  with self._window_op_lock:
      session = self._listening_sessions.get(self._active_listening_token)
      if session:
          session.tick()
          ...
          self._persist_listening(session)   # -> db.update_history_duration(...) : a SQLite write
  ```
- **Reproduction / verification:** the code path is directly visible; to *prove* the stall one would need to inject a slow `db.update_history_duration` (e.g. a SQLite lock held by another connection) and observe `_on_track_changed` blocking — I did not attempt this, so the stall magnitude remains unverified. What is verified: the write happens under the shared lock (see the snippet) and `_on_track_changed` at `core/api.py:1211` acquires the same lock.
- **Suggested fix:** use a dedicated `threading.Lock` for the listening-session map and perform the DB writes outside the window lock (or in a writer thread), so the telemetry path cannot stall window/track-change operations.
- **Fix side effects:** the session map is currently mutated under `_window_op_lock` in six places (L1211, 1269, 1298, 1310, 1334, 1364, 1411); all of them must move to the new lock together, otherwise the map loses its protection.
- **Discovered by:** A

#### F-WN-05-10  [P3] — `report_position` accepts negative / absurd positions and writes them into `engine._last_reported_position`, which is persisted into the session

- **File:** `core/api.py:1407-1428`; `main.py:558-569`
- **Confirmed:** yes
- **Description:** `report_position` forwards `pos_ms` unchecked:
  ```python
  pos_sec = pos_ms / 1000.0 if pos_ms else 0.0
  ...
  self._core.engine._last_reported_position = pos_sec
  self._emit("position_changed", {"pos": pos_sec, ..., "position_ms": pos_ms, ...})
  ```
  A negative `pos_ms` is published to the UI as a negative `position_ms` (`js/events.js:112` prefers `data.position_ms`), and `engine._last_reported_position` is what `main.py:563` saves as `session.last_position` on exit — so a bogus value is written to the session file and used to resume playback on the next start.
- **Cause:** no validation of the reported position; the position is trusted to be a real media position.
- **Trigger conditions:** a malformed/hostile bridge call, or a future frontend change. The shipped frontend computes `Math.round(audio.currentTime * 1000)` and never sends a negative value, so the defect is **latent** today.
- **User impact:** a negative progress bar / negative lyric offset, and a corrupted resume position (`position=1e9` ms) that survives restarts.
- **Evidence:** see the snippet above; `main.py:562-563`:
  ```python
  position=getattr(engine, '_last_reported_position', 0),
  ```
- **Reproduction / verification:** `repro_wn05c.py::test_Z_report_position_negative_and_jumps`:
  ```
  Z) seconds after negative/huge positions: 9.14999982342124e-05
     engine._last_reported_position: 1000000000.0
  ```
  (The listening seconds stayed correct — `ListeningSession.tick` uses wall-clock deltas, not the reported position, so the telemetry itself is not poisoned; only the emitted payload and the session resume position are.)
- **Suggested fix:** clamp `pos_ms` to `>= 0` and to the reported duration before emitting and before storing it on the engine.
- **Fix side effects:** none for the current frontend.
- **Discovered by:** A

---

### 3. Clean areas

Checked and found correct — no finding raised:

- **Repeat-mode string contract is consistent end-to-end.** `audio/queue.py:20` (`_repeat: str = "off"`, comment `# off, one, all`), `audio/queue.py:116` (`if mode in ("off", "one", "all")`), `audio/queue.py:270-274` (`toggle_repeat` cycles `["off", "all", "one"]`), `core/api.py:2010-2014` (emits `repeat_changed` with `{"state": mode}`) and the frontend `ui/web_new_v2/js/events.js:297-311` (`repeatMode = data?.state ?? 'off'`, `repeatOn = repeatMode !== 'off'`, `syncRepeatIcon` renders `repeat-1` for `'one'`). Verified empirically: `toggle_repeat -> off all one`. **No Python/JS string mismatch.**
- **Shuffle contract.** `core/api.py:2004-2008` emits `shuffle_changed` with `{"state": bool}`; `js/events.js:288-294` reads `data?.state` as a boolean. Consistent.
- **Queue event name and payload contract (#7).** `_notify_queue_updated` / `reorder_queue` / `play_next` / `add_to_queue` / `add_tracks_to_queue` / `remove_from_queue` / `clear_queue` all emit **`queue_updated`** with the payload of `get_queue()` = `{tracks, current_index, current_track, shuffle, repeat}`; `js/events.js:283-286` dispatches it as `nedotify:queue_updated` and `js/queue.js:61/80-84` reads `q.tracks` and `q.current_index`. Verified payload keys: `['current_index', 'current_track', 'repeat', 'shuffle', 'tracks']`.
- **`track_changed` / `state_changed` / `position_changed` / `mute_changed` / `audio_error` / `error` / `queue_ended` / `yandex_device_auth_code` / `yandex_device_auth_result`** event names all exist in `js/events.js` with matching payload keys (`state`, `elapsed_ms`; `pos`/`duration`/`position_ms`/`duration_ms`; `muted`; `message`/`user_message`/`title`/`code`; `reason`; `user_code`/`verification_url`; `success`/`message`).
- **`_emit` is never called on the UI thread from this area.** All WN-05 emissions go through `AppApi._emit` (`core/api.py:1122-1159`), which hands off to an `EmitWorker` thread when called from the main thread. No direct `evaluate_js` call exists in the reviewed range. (The `_emit` implementation itself is WN-03's contract.)
- **Listening telemetry does not double-count.** One `history` row and one `play_count` increment per actual playback start: 5 × `report_state('playing')` for the same session ⇒ 1 row / `play_count == 1` (repro `test_X`); a full play-through (`report_state` + `report_listening_state` + 5 × `report_position`) ⇒ exactly 1 row (repro `test_G`). The dedup lives in `session.history_id`, and `_history_logged_key` (set at L1212/L1328/L1372) is vestigial — written but never read; the *behaviour* it is supposed to provide is provided correctly.
- **No time is counted while paused.** `ListeningSession.tick` only accumulates when `self.audible` is true and the session is open (`core/listening.py:22-30`); after `report_state('paused')` the seconds stayed at ~0 over repeated `report_position` calls (repro `test_paused_counts_time`).
- **Negative / non-monotonic deltas are handled.** `delta = max(0.0, min(15.0, now - self.last_tick))` (`core/listening.py:27`) clamps negative deltas to 0 and caps a suspended machine at 15 s per heartbeat, so a sleeping laptop cannot inflate the listening time.
- **Stale listening tokens are rejected.** `report_state`, `report_position` and `report_listening_state` all compare `listening_session` against `self._active_listening_token` and return `False` for a foreign token; the session's seconds do not move (repro `test_I`).
- **`_listening_identity` keys by source + source_id**, so the same title/artist from two providers is two different sessions, and it falls back to the DB row id only when `source_id` is empty. The session map is also capped at 32 entries (`core/api.py:1284-1285`); the eviction is benign because each session is already closed and persisted when the next track starts (verified: 40 sessions → 32 kept, all 40 history rows end with `session_finished=1`).
- **`flush_listening` is not lost on exit.** It is called by `AppCore.cleanup()` (`core/app.py:530-531`) *before* `db.close()` (L559) and by `AppApi.close()` (`core/api.py:934`).
- **Queue index bookkeeping is correct.** `reorder_queue(1, 0)` with the current track at index 1 moves it and updates `_current_index` to 0; `remove_from_queue(0)` with the current track at index 2 decrements the index to 1 and keeps the current track; removing the current track is refused; `clear_queue` keeps the current track (4 → 1 track, index 0, same current track); `play_next` on an empty queue inserts and sets index 0.
- **`get_next_track` preview logic is correct**: `None` at the end of the queue with repeat off, wraps to track 0 with repeat `all`, returns the current track with repeat `one`, `None` for an empty queue.
- **A missing local file fails loudly and does not corrupt the queue**: `play_track` on a local track whose file is gone emits `audio_error` + `error` and leaves the queue untouched (count 0) — the old "play against a missing path" behaviour is gone.
- **An audio error does not destroy the queue**: the failing track stays in the queue and `queue_updated` was already published; the frontend receives `audio_error` (toast + `state → stopped`). The `error` event that `_on_audio_error` also emits is de-duplicated by the frontend's 300 ms `lastAudioErrorAt` guard, so the user sees one toast, not two.
- **`play_pause` is honest.** It does not pretend to pause an element it cannot control; it returns the last state the renderer reported (`""` before anything was reported) — the docstring matches the code.
- **`toggle_mute` / `is_muted` persist and report the real state**, and the frontend keeps `currentVolume` untouched while muted (`js/player.js:2032-2039`), so unmuting restores the previous level.
- **`_enrich_track_lufs` is defensive**: non-dict input is returned unchanged, `int(t_id)` conversion failures are swallowed, and the whole lookup is wrapped in `try/except`.

---

### 4. Coverage gaps

- **The provider callback contract was not exercised against real providers.** `core/app.py::re_resolve_stream_url_async` can call `callback` from the SoundCloud fallback chain *after* the provider's `error_callback` has already fired. If a provider ever invokes **both** its success and its error callback for one request, `AppApi._resolve_track`'s `on_resolved` would run twice (a second `_notify_track_changed()` → a duplicate `track_changed` event) and `play_callback` could be invoked twice. I could not confirm this against `services/youtube_service.py` / `services/soundcloud_service.py` (WN-19 / WN-20) within this area's budget — flagged as a **hypothesis** for those areas, not reported as a defect here.
- **`core/resolver.py` (WN-15) was not opened.** The reviewed code reaches it only indirectly through `core/app.py::re_resolve_stream_url_async`; its single-flight behaviour is therefore assumed, not verified.
- **The real pywebview / WebView2 marshalling was not exercised.** All reproductions ran headless with `_emit` monkey-patched, so the "the worker thread blocks in `evaluate_js` until the UI thread drains the message queue" behaviour of `core/api.py:1156-1157` could not be observed. F-WN-05-1/2 are pure Python state-machine defects and were reproduced without the UI, but their *visual* consequences were inferred from the frontend source, not observed.
- **The offline-mode branches of `play_track` / `_on_track_changed` were only read, not executed** (they need `core/offline.py` + a populated downloads table). The code path was verified by inspection: `play_track` returns `{"success": False, "code": "offline", …}` in that branch while the normal path returns `None` — an inconsistent return shape that no shipped caller depends on (the frontend only awaits the promise and reacts to the `audio_error` event), so it was **not** raised as a finding.
- **The `core/proxy.py` self-heal re-resolve** (`core/proxy.py:1051`) calls `re_resolve_stream_url_async` directly, bypassing `_resolve_track`, so it is outside the F-WN-05-1 race; the interaction between the proxy's re-resolve and `AppApi`'s pending resolution was not traced (WX-01 / WN-11).
- **`yandex_music.device_auth` was stubbed**, not run against the real library: the 300 s polling timeout, the exact token object shape (`token.access_token`) and the library's "does the installed version support `device_auth`" branch were verified only against the code path and a fake client.
- **Thread-safety of `_listening_sessions` under real concurrency was not stress-tested.** The map is guarded by `_window_op_lock` everywhere it is touched (L1269, L1298, L1310, L1334, L1364, L1411) — but `self._active_listening_token` is read **outside** the lock at `core/api.py:1338`, `1359` and `1409`. That is a benign-looking race (a stale read only causes a report to be dropped), but it was not reproduced under load and is therefore **not** raised as a finding.
- **`tests/` were not modified or extended.** The existing suite (`tests/test_api_audit_b.py`, `tests/test_measured_listening.py`, `tests/test_engine_notify.py`, `tests/test_api_f1_audit.py`) was read to avoid re-reporting already-pinned behaviour; all reproductions were run from a scratch script outside the repo.
