## AREA WN-17 — Audio engine & playback queue — ROLE A

### 1. Scope reviewed

**Files opened (full read of the area):**
- `audio/queue.py` — L1–302 (whole file; 267 non-empty lines). All members: `PlaybackQueue.__init__` (L14), `current_track` (L24), `update_current` (L31), `current_index` (L38), `tracks` (L43), `count` (L48), `is_empty` (L53), `_track_key` (L58), `shuffle` getter (L64)/setter (L69), `repeat` getter (L109)/setter (L114), `set_tracks` (L119), `add_track` (L134), `add_tracks` (L159), `remove_track` (L173), `move_track` (L193), `next_track` (L215), `previous_track` (L250), `toggle_shuffle` (L265), `toggle_repeat` (L270), `jump_to` (L280), `clear` (L290), `get_upcoming` (L298).
- `audio/engine.py` — L1–508 (whole file; 440 non-empty lines). All members: `AudioEngine.__init__` (L27), `play_track` (L35), `play_queue` (L41), `add_to_queue` (L49), `add_tracks_to_queue` (L52), `next_track` (L55), `prev_track` (L65), `toggle_shuffle` (L72), `toggle_repeat` (L75), `_notify_track_changed` (L78), `resolve_stream_url` (L121), `_resolve_via_network` (L153).
- `core/api.py` — L1122–1191 (`_emit`), L1195–1290 (`_on_track_changed`, `_on_queue_end`, `_on_audio_error`), L1437–1744 (`play_track`, `_resolve_track`), L1746–1851 (`play_pause`, `next_track`, `prev_track`, `get_queue`, `reorder_queue`, `play_next`, `add_to_queue`, `add_tracks_to_queue`, `remove_from_queue`, `clear_queue`), L2004–2075 (`toggle_shuffle`, `toggle_repeat`, `get_next_track`), L2922–2958 (`get_settings`), L3640–3683 (`prefetch_track`), L4129–4161 (`set_offline_mode`).
- `ui/web_new_v2/js/player.js` — L620–739 (audio `ended`/`error` handlers), L855–1000 (transport + shuffle/repeat buttons), L1415–1484 (prefetch / lookahead), L1625–1700 (`onTrackChanged`), L1829–1853 (`stopPlaybackForQueueEnd`), L1973–2030 (`applySettings`, `updateRepeatIcon`).
- `ui/web_new_v2/js/queue.js` — L1–303 (whole file).
- `ui/web_new_v2/js/events.js` — L92–121 (`track_changed`), L283–311 (`queue_updated`, `shuffle_changed`, `repeat_changed`), L396–403 (`queue_ended`).
- `ui/web_new_v2/js/library-view.js` — L176–187 (library "Перемешать" button).
- `ui/web_new_v2/js/feature-controls.js` — L55–79 (operation-error "retry" → `play_track`).
- `ui/web_new_v2/js/search-discovery.js` — L33–53 (history card click → `play_track`).
- `ui/web_new_v2/js/main.js` — L385–429 (settings bootstrap → `applySettings`).
- `core/resolver.py` — L1–271 (whole file; the cache/single-flight layer `resolve_stream_url` delegates to).
- `core/settings.py` — L235–304 (`session.shuffle` / `session.repeat` defaults).
- `core/session.py` — L1–96 (whole file; persists `shuffle`/`repeat`).
- `main.py` — L300–349 (session restore into the queue), L548–584 (session save).
- `core/app.py` — L280–400 (`re_resolve_stream_url_async`), L126–138 (`engine.app_core`, `engine.proxy` wiring).
- `core/proxy.py` — L421–441 (`ThreadingHTTPServer`), L800–939 (the three call sites of `engine.resolve_stream_url`).
- `.venv_win/Lib/site-packages/webview/util.py` — L290–315 (pywebview js_api dispatch).
- `tests/test_queue.py` — L1–109 (whole file; existing coverage).
- `tests/test_engine_notify.py` — L460–539 (existing coverage of `next_track` / `prev_track` / queue-end).

**Callees traced into other areas (read only to trace, not reviewed):**
- `core/resolver.py` → `StreamResolver.resolve` / `get_cached_url` (WN-15).
- `core/proxy.py` → `StreamProxyHandler.do_GET` (WN-11) — three call sites of `engine.resolve_stream_url`.
- `core/api.py` (WN-05) — the bridge surface for `play_track` / `next_track` / `prev_track` / `toggle_shuffle` / `toggle_repeat` / `reorder_queue` / `remove_from_queue` / `get_queue` / `get_next_track`.
- `ui/web_new_v2/js/player.js`, `js/queue.js`, `js/events.js`, `js/library-view.js`, `js/feature-controls.js`, `js/search-discovery.js`, `js/main.js` (WN-28 / WN-29).
- `core/settings.py` (WN-14) and `core/session.py` (WN-02) — the persisted `shuffle` / `repeat` values.
- `utils/file_scanner.py` (WN-27) — the shape of local track dicts (they always carry a DB `id`).

**Scratch probes** (written to `%TEMP%`, nothing in the repo was modified):
`%TEMP%\opencode\wn17_probe.py`, `wn17_probe2.py`, `wn17_probe3.py`, `wn17_probe4.py` — run with `& ".venv_win\Scripts\python.exe"`.

---

### 2. Findings

#### F-WN-17-1  [P2] — Turning shuffle off can re-point `current_index` at a *different* queue entry that shares the same `_track_key`
- **File:** `audio/queue.py:57-61`, `audio/queue.py:83-106`
- **Confirmed:** yes
- **Description:** `_track_key` is `(source, str(source_id or id or url or ""))`. Two *different* tracks that have no `source_id`/`id`/`url` collapse onto the same key (e.g. `("local", "")`). The shuffle-off branch then locates the current track **by key, not by identity**, and takes the *first* match. The current track silently becomes a different entry while the audio keeps playing the old one.
- **Cause:** identity was replaced by a value-equality key that is not unique across the queue. The enabling branch pins the current track by *object* (`self._tracks = [current] + remaining`), the disabling branch re-finds it by *key* (`audio/queue.py:97-103`) — the two branches do not agree on how the current track is identified.
- **Trigger conditions:** the queue holds two entries with an identical `_track_key` (same `source` and same `source_id`, or same `source` and neither has `source_id`/`id`/`url`), and the user toggles shuffle off while one of them is current.
- **User impact:** the queue's "current" pointer, the highlighted row in the queue drawer, and the target of the next/previous button all point at the wrong entry. Because `core/api.py` identifies the playing track by object identity (`core/api.py:1586`, `core/api.py:1590`, `core/api.py:1625` — `queue.current_track is target_track`), a stream-resolution callback that captured the old object is then discarded and the user gets *"Не удалось найти поток"* for a track that resolved fine.
- **Evidence:**
  ```python
  # audio/queue.py:57-61
  @staticmethod
  def _track_key(track: dict) -> tuple:
      if not isinstance(track, dict):
          return (None, None)
      return (track.get("source"), str(track.get("source_id") or track.get("id") or track.get("url") or ""))
  ```
  ```python
  # audio/queue.py:97-103  (shuffle-off branch)
  if current_key:
      found_idx = -1
      for idx, t in enumerate(self._tracks):
          if self._track_key(t) == current_key:
              found_idx = idx
              break
      self._current_index = found_idx if found_idx >= 0 else (0 if self._tracks else -1)
  ```
- **Reproduction / verification:** run `%TEMP%\opencode\wn17_probe2.py` (section A / A3):
  ```
  === A. shuffle-off with two DIFFERENT tracks sharing one _track_key ===
  keys: ('local', '') ('local', '') equal: True
  after shuffle ON : tracks = ['Beta', 'Alpha'] current = Beta ci 0
  after shuffle OFF: tracks = ['Alpha', 'Beta'] current = Alpha ci 0
  current is still the playing track (B)? False
  ```
  and with a duplicated YouTube id (same `source_id`, different title):
  ```
  === A3. collision via same source_id but different titles ===
  after ON : current = One (Remastered) ci 0
  after OFF: current = One ci 0 is D2? False
  ```
- **Suggested fix:** identify the current track by **object identity** in the shuffle-off branch (keep the pinned current object and locate *it* in the restored list), and make `_track_key` collision-free — e.g. fall back to `(source, id, title, artist)` before collapsing to `""`.
- **Fix side effects:** the restore logic currently relies on the key to survive a re-created track object (a track re-added from a different list). An identity-based restore must fall back to the key when the object is gone (e.g. after `remove_track` rebuilt the list).
- **Discovered by:** A

#### F-WN-17-2  [P2] — `AudioEngine.next_track()` advances the queue and announces the track in two separate lock acquisitions → a concurrent `next_track` skips a track and announces the same track twice
- **File:** `audio/engine.py:55-63` (also `audio/queue.py:215-248`)
- **Confirmed:** yes (the race window is structural; reproduced with the window widened — see below)
- **Description:** `queue.next_track()` takes the queue lock, advances the index and **releases** the lock. `_notify_track_changed()` then takes the lock again and reads `queue.current_track` — i.e. *whatever is current now*, not the track that was returned. Two overlapping `next_track()` calls therefore (a) advance the queue twice but announce the second track only, and (b) announce the same track twice.
- **Cause:** the "advance" and the "announce" are not one atomic operation, and the announced payload is re-read from shared state instead of being the value returned by the advance.
- **Trigger conditions:** two concurrent `next_track()` bridge calls. pywebview dispatches **every** JS→Python `js_api` call on a brand-new thread (`webview/util.py:308-309`: `thread = Thread(target=_call); thread.start()`), so the bridge is *not* serialised. Two rapid presses of Next, or the `ended` handler (`js/player.js:644-653`) racing a Next click, produce exactly this.
- **User impact:** a track is silently skipped (never played, never announced) or the same track is started twice (the frontend restarts it because `activeAudio.ended` is true — `js/player.js:1690`). This is precisely the WX-10 scenario ("Rapid track switching / concurrent play-pause-next commands → queue + engine + proxy state consistency").
- **Evidence:**
  ```python
  # audio/engine.py:55-63
  def next_track(self):
      """Advance the queue and notify the UI. Returns the new track or None at the end."""
      track = self.queue.next_track()
      if track:
          self._notify_track_changed()
          return track
      if self._on_queue_end:
          self._on_queue_end()
      return None
  ```
  ```python
  # audio/engine.py:78-80  (re-reads the *current* track, not the returned one)
  def _notify_track_changed(self):
      current = self.queue.current_track
      if self._on_track_changed and current:
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe4.py` widens the window between the two statements and shows the failure:
  ```
  announced track ids: [2, 2]
  queue current_index : 2
  -> track id 1 was advanced past but NEVER announced: True
  ```
  `%TEMP%\opencode\wn17_probe3.py` shows that without the artificial delay the three concurrent calls announce `[1, 2, 3]` — i.e. the window is narrow but real.
- **Suggested fix:** make advance+announce atomic — e.g. have `PlaybackQueue.next_track()` return the track *and* have the engine notify from the returned object (not from `queue.current_track`), or hold the queue lock across the advance and the callback.
- **Fix side effects:** holding the queue lock across `_on_track_changed` would run the whole bridge callback (DB lookups, `_emit`) under the queue lock — that would serialise the queue but slow down every other queue operation and risks a deadlock if the callback re-enters the queue (it does: `core/api.py:1633` reads `queue.current_track`, `core/api.py:1586` too). Prefer "notify from the returned object".
- **Discovered by:** A

#### F-WN-17-3  [P2] — `AudioEngine.play_track()` replaces the whole queue with one track, and the solo bridge path never emits `queue_updated`
- **File:** `audio/engine.py:35-39`; `core/api.py:1605-1606` (and the contrast at `core/api.py:1527-1528`, `1539-1540`, `1546-1547`, `1566-1567`, `1580-1581`)
- **Confirmed:** yes
- **Description:** `play_track()` calls `queue.set_tracks([track], 0)` — the queue is **replaced** by a single track. The bridge's solo path (`play_track(track)` with no `track_list`) reaches it and — on the network-resolution branch — never emits `queue_updated`, so the frontend's queue mirror stays stale. The list branch always calls `self._notify_queue_updated()`; the solo branch does not.
- **Cause:** two different code paths for the same queue mutation, only one of which publishes the new queue state. `core/api.py::_resolve_track._deliver()` does emit `queue_updated` (`core/api.py:1638-1641`), but `_deliver()` is only reached on the *fast* paths (usable `file_path`, DB cache hit, streams-dir hit). The async branch calls `play_callback(track)` from `on_resolved` (`core/api.py:1736`) with no `queue_updated`.
- **Trigger conditions:** any `play_track(track)` call without a `track_list` for a track that has to be resolved over the network. Live call sites: `ui/web_new_v2/js/feature-controls.js:69` (the "retry" action of an audio operation error), `ui/web_new_v2/js/search-discovery.js:43` (clicking one track in the "recently listened" discovery cards), `ui/web_new_v2/js/player.js:892` / `895` / `898` (the fallbacks of the "no valid src" branch). `js/player.js:876-877` even documents the hazard: *"Pass the current queue when we have it so the backend keeps the queue (shuffle/repeat/next) instead of resolving solo."*
- **User impact:** the user's entire queue is silently destroyed — Next/Previous stop working, the queue drawer keeps showing the old list, and `window.currentQueue` (written only by `js/queue.js:10 syncQueueToWindow()`, called from the `queue_updated` handler at L65 and `loadQueue()` at L83) stays stale. `js/player.js:878-880` then reads that stale list and pushes it back into the backend on the next play attempt.
- **Evidence:**
  ```python
  # audio/engine.py:35-39
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)
      self._notify_track_changed()
  ```
  ```python
  # core/api.py:1605-1606  (solo branch — no _notify_queue_updated())
  else:
      self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  ```
  vs.
  ```python
  # core/api.py:1527-1528  (list branch — publishes the queue)
  self._core.engine.play_queue(track_list, safe_index)
  self._notify_queue_updated()
  ```
  ```python
  # core/api.py:1736  (async solo resolve — queue replaced, nothing published)
  play_callback(track)
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe3.py`:
  ```
  === engine.play_track() wipes the queue ===
  queue before play_track: 5
  queue after  play_track: 1 [42]
  next_track() -> None
  ```
  and the missing publish is visible by reading `core/api.py:1605-1606` against `core/api.py:1527-1528`.
- **Suggested fix:** either (a) make `AudioEngine.play_track()` *append/replace-preserving* semantics explicit and have `core/api.py` always call `_notify_queue_updated()` after a queue mutation, or (b) give the solo path an explicit "replace queue" API and make the frontend call sites pass the current queue (or add a dedicated `restart_current_track()` that preserves the queue).
- **Fix side effects:** (a) changes the observable meaning of `play_track(track)` for every caller — the queue would no longer be reset, so "play this one song" would keep the old queue around; that must be decided deliberately, not silently. (b) requires touching four frontend call sites (WN-29).
- **Discovered by:** A

#### F-WN-17-4  [P2] — The frontend renders the shuffle/repeat buttons from `settings.shuffle` / `settings.repeat`, which do not exist at the top level of the settings tree
- **File:** `ui/web_new_v2/js/player.js:1973-1984` (owner: **WN-29** — reported here because it is the shuffle/repeat contract of `PlaybackQueue`); data source `core/api.py:2922-2938`, `core/settings.py:256-264`; trigger `ui/web_new_v2/js/library-view.js:180-184`
- **Confirmed:** yes
- **Description:** `AppApi.get_settings()` returns a dict **keyed by category** (`res[c] = ...`). The shuffle/repeat values live under `session.shuffle` / `session.repeat`, so `settings.shuffle` and `settings.repeat` are `undefined` at the top level. `applySettings()` therefore always clears the shuffle button's `active` class and always *sets* the repeat button's `active` class (`undefined !== 'off'` is `true`).
- **Cause:** a shape mismatch between the settings payload (nested per category) and the flat `settings.shuffle` / `settings.repeat` access. The authoritative values are already exposed by the queue — `AppApi.get_queue()` returns `shuffle` and `repeat` at the top level (`core/api.py:1778-1779`) — but the frontend never reads them.
- **Trigger conditions:** every `applySettings()` call — `js/main.js:400` (cached settings at startup) and `js/main.js:416` (fresh settings). At startup this runs *after* the backend restored `session.shuffle` into the queue (`main.py:320-321`), so the button state and the queue state disagree from the first frame.
- **User impact:** (1) the repeat button is rendered as **active** although repeat is `off`; the shuffle button is rendered as **inactive** although shuffle is on. (2) The library "Перемешать" button decides whether to toggle by inspecting that same class (`js/library-view.js:182`: `if(!document.getElementById('pb-btn-shuffle').classList.contains('active')){...toggle_shuffle()...}`), so with shuffle already on in the queue the button **turns shuffle OFF** and the list is then played in the original order — the user asked to shuffle and got the original order.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:1981-1984
  if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
  if (ppShuffle) ppShuffle.classList.toggle('active', settings.shuffle);
  if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
  if (ppRepeat) ppRepeat.classList.toggle('active', settings.repeat !== 'off');
  ```
  ```python
  # core/api.py:2929-2936  (settings are nested per category)
  categories = ['app', 'appearance', ..., 'session', 'zapret']
  res = {}
  for c in categories:
      cat_data = self._core.settings.get_category(c)
      if cat_data:
          res[c] = _mask_secrets(c, cat_data)
  ```
  ```python
  # core/settings.py:256-264  (the real home of the values)
  "session": {
      ...
      "shuffle": False,
      "repeat": "off",
  },
  ```
- **Reproduction / verification:** read `core/api.py:2922-2938` (the payload shape) against `ui/web_new_v2/js/player.js:1981-1984` (the access). At runtime: start the app with `session.shuffle = true` in the DB, watch the shuffle button come up un-highlighted, then press the library "Перемешать" button — `toggle_shuffle()` fires and the backend flips the queue's shuffle to `False`.
- **Suggested fix:** read `settings.session.shuffle` / `settings.session.repeat`, or better, initialise the buttons from `AppApi.get_queue()` (`core/api.py:1778-1779`), which is the live source of truth.
- **Fix side effects:** the buttons would then reflect the *live* queue rather than the persisted session value; the two can differ if the queue was changed after startup (the `shuffle_changed` / `repeat_changed` events already keep the buttons in sync, so reading the queue at boot is safe).
- **Discovered by:** A

#### F-WN-17-5  [P3] — `PlaybackQueue.remove_track()` of the current entry silently re-points `current_index` at the next entry, and the displaced track is never played
- **File:** `audio/queue.py:186-191`; guard lives in the caller `core/api.py:1829-1830`
- **Confirmed:** yes
- **Description:** removing the entry at `current_index` leaves `current_index` unchanged, so it now designates the *following* track. The track that was removed is not queued anywhere, and `next_track()` then skips its successor entirely.
- **Cause:** the removal branch clamps the index but never transfers "currentness"; `PlaybackQueue` has no notion of a protected current entry — the protection lives only in the bridge.
- **Trigger conditions:** `queue.remove_track(queue.current_index)`. Today the only caller (`AppApi.remove_from_queue`) blocks it, so this is defence-in-depth for any future/internal caller (e.g. `set_offline_mode`'s `queue.set_tracks(...)` path, or a new bridge method).
- **User impact:** the queue silently changes the playing track and one track is dropped from the rotation.
- **Evidence:**
  ```python
  # audio/queue.py:186-191
  if len(self._tracks) == 0:
      self._current_index = -1
  elif index < self._current_index:
      self._current_index -= 1
  elif index == self._current_index:
      self._current_index = min(self._current_index, len(self._tracks) - 1)
  ```
  ```python
  # core/api.py:1829-1830  (the only guard, in the caller)
  if index == queue._current_index:
      return {"success": False, "error": "Cannot remove current track"}
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe2.py` (section E):
  ```
  === E. remove_track of the current track ===
  ci 1 current id 2 (was id 1)
  next -> 3   <- id 2 is skipped entirely
  ```
- **Suggested fix:** either refuse to remove the current entry inside `PlaybackQueue` (return a bool / raise) and let the caller map that to its error message, or make the removal explicit about the successor (advance to the next track *and* leave the removed one in place as "already played").
- **Fix side effects:** `PlaybackQueue.remove_track` currently returns `None`; changing it to return a status means updating `AppApi.remove_from_queue` (WN-05).
- **Discovered by:** A

#### F-WN-17-6  [P3] — `move_track()` / `remove_track()` / `jump_to()` raise `TypeError` on a non-integer index, and `AppApi.reorder_queue` has no `try/except`
- **File:** `audio/queue.py:196` (`move_track`), `audio/queue.py:176` (`remove_track`), `audio/queue.py:283` (`jump_to`); `core/api.py:1782-1785`
- **Confirmed:** yes
- **Description:** the bounds checks are `0 <= index < len(self._tracks)`, which raises `TypeError` for a `str`, `None` or `float` index instead of being rejected. `AppApi.remove_from_queue` coerces with `int(index)` (`core/api.py:1822-1825`), but `AppApi.reorder_queue` passes the raw bridge argument straight through, so the exception escapes the bridge method.
- **Cause:** no type validation on the public index parameters of `PlaybackQueue`; the coercion exists only in one of the two bridge methods.
- **Trigger conditions:** a non-integer `old_index`/`new_index` reaching `reorder_queue`. The current frontend (`js/queue.js:285`) always passes integers, so this is not reachable today — but the bridge is a public surface and pywebview forwards whatever JSON the page sends.
- **User impact:** the bridge call rejects with an exception instead of the `{"success": false, "error": ...}` shape the other queue methods return; `js/queue.js:286-288` catches it and only logs to the console, so the drag-and-drop silently does nothing.
- **Evidence:**
  ```python
  # audio/queue.py:196
  if 0 <= old_index < len(self._tracks) and 0 <= new_index < len(self._tracks):
  ```
  ```python
  # core/api.py:1782-1785  (no coercion, no try/except)
  def reorder_queue(self, old_index: int, new_index: int):
      """Move track from old_index to new_index in queue."""
      self._core.engine.queue.move_track(old_index, new_index)
      self._emit("queue_updated", self.get_queue())
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe2.py` (section F):
  ```
  move_track('0', 1) raised TypeError: '<=' not supported between instances of 'int' and 'str'
  move_track(None, 1) raised TypeError: '<=' not supported between instances of 'int' and 'NoneType'
  move_track(1.5, 1) raised TypeError: 'float' object cannot be interpreted as an integer
  remove_track('0') raised TypeError: '<=' not supported between instances of 'int' and 'str'
  jump_to(None) raised TypeError: '<=' not supported between instances of 'int' and 'NoneType'
  ```
- **Suggested fix:** coerce/validate the index in `PlaybackQueue` itself (`int(index)` in a `try`, or an `isinstance(index, int)` guard) so the contract is enforced at the owner of the data, and add the same `try/except` + error-dict shape to `reorder_queue` that `remove_from_queue` already has.
- **Fix side effects:** `bool` is a subclass of `int` — `move_track(True, 1)` currently "works" as index 1; an `isinstance` check would accept it too unless explicitly excluded.
- **Discovered by:** A

#### F-WN-17-7  [P3] — `move_track()` does not update `_original_order`, so a manual reorder is silently discarded when shuffle is turned off
- **File:** `audio/queue.py:193-213` (vs. `audio/queue.py:74` and `audio/queue.py:90-96`)
- **Confirmed:** yes
- **Description:** the shuffle-off branch rebuilds the queue from `_original_order` filtered by the current keys. `move_track` mutates only `_tracks`, never `_original_order`, so a drag-and-drop reorder performed while shuffle is on is reverted the moment the user turns shuffle off.
- **Cause:** `_original_order` is maintained by `add_track` (`audio/queue.py:149-155`) and `remove_track` (`audio/queue.py:178-180`) but not by `move_track` — the three mutators do not agree on who owns that list.
- **Trigger conditions:** shuffle on → the user drags a row in the queue drawer (`js/queue.js:261-293` → `AppApi.reorder_queue`) → the user turns shuffle off.
- **User impact:** the user's manual ordering is lost without any notice; the queue snaps back to the pre-shuffle order.
- **Evidence:**
  ```python
  # audio/queue.py:202-213  (move_track — _original_order is not touched)
  track = self._tracks.pop(old_index)
  self._tracks.insert(new_index, track)
  ...
  ```
  ```python
  # audio/queue.py:90-96  (shuffle-off rebuilds from _original_order)
  restored = [t for t in self._original_order if self._track_key(t) in current_keys]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe.py` (section 12):
  ```
  === 12. move_track while shuffle on, then shuffle off ===
  shuffled: [0, 2, 1, 4, 3]
  after move: [2, 1, 4, 0, 3] ci 3
  after shuffle off: [0, 1, 2, 3, 4]      <-- the move is gone
  ```
- **Suggested fix:** apply the same move to `_original_order` inside `move_track` (mirroring the key-based insert/remove that `add_track`/`remove_track` already do), or record an explicit "manual order" flag that the shuffle-off branch honours.
- **Fix side effects:** `_original_order` is a *pre-shuffle* order; rewriting it for a move performed in the *shuffled* list is only meaningful if the move is mapped back through the key. A key-based mapping has the same collision problem as F-WN-17-1.
- **Discovered by:** A

#### F-WN-17-8  [P3] — `remove_track()` deletes *every* `_original_order` entry with the same key, relocating the surviving duplicate to the end of the queue
- **File:** `audio/queue.py:178-180` (vs. `audio/queue.py:89-96`)
- **Confirmed:** yes
- **Description:** removal from `_original_order` is done by key, not by position, so all copies of the removed track are dropped from the original order. When shuffle is later turned off, the remaining copy is not found in `_original_order` and is appended at the end of the restored list instead of keeping its place.
- **Cause:** `_track_key` is used as an identity for list surgery, but it is not unique (see F-WN-17-1); removing by key removes all occurrences, and the restore then re-appends the leftover.
- **Trigger conditions:** the same track appears more than once in the queue (a duplicate playlist entry, or the same song added twice) and the user removes one copy and later toggles shuffle off.
- **User impact:** the surviving copy jumps to the end of the queue — the running order changes for no visible reason.
- **Evidence:**
  ```python
  # audio/queue.py:178-180
  if self._original_order:
      target_key = self._track_key(track)
      self._original_order = [t for t in self._original_order if self._track_key(t) != target_key]
  ```
  ```python
  # audio/queue.py:89-96  (restore appends anything not found in _original_order)
  current_keys = {self._track_key(t) for t in self._tracks}
  restored = [t for t in self._original_order if self._track_key(t) in current_keys]
  restored_keys = {self._track_key(t) for t in restored}
  for t in self._tracks:
      if self._track_key(t) not in restored_keys:
          restored.append(t)
          restored_keys.add(self._track_key(t))
  ```
- **Reproduction / verification:** `%TEMP%\opencode\wn17_probe.py` (section 10):
  ```
  === 10. duplicate track + remove + shuffle off ===
  shuffled: ['dup', 'other', 'dup']
  after remove: ['other', 'dup'] orig_order len 1
  after shuffle off: ['other', 'dup'] ci 0
  ```
  (the surviving `dup` was originally first, and ends up last after the shuffle-off restore.)
- **Suggested fix:** remove exactly one occurrence from `_original_order` (match by identity first, then by key as a fallback) instead of filtering all key-equal entries.
- **Fix side effects:** with duplicate tracks, "which occurrence" is ambiguous; matching by object identity resolves it because `add_track`/`set_tracks` keep the caller's dict objects.
- **Discovered by:** A

#### F-WN-17-9  [P3] — `AppApi.get_queue()` reads `queue._current_index` without the lock while `queue.tracks` is a locked copy → the published snapshot can be internally inconsistent
- **File:** `core/api.py:1772-1780` (owner: **WN-05** — the caller bypasses the queue's public accessor); `audio/queue.py:37-45`
- **Confirmed:** yes (code-level)
- **Description:** `get_queue()` builds the payload from `queue.tracks` (a locked copy) and `queue._current_index` (the **private** field, read with no lock at all). Between the two reads another thread can replace the queue, so the emitted `queue_updated` payload can carry a `current_index` that is outside the range of the `tracks` it ships with.
- **Cause:** a private field is read directly instead of the public `current_index` property (`audio/queue.py:37-40`), which does take the lock. The snapshot is also not taken under a single lock acquisition.
- **Trigger conditions:** a queue mutation concurrent with a `get_queue()` call. pywebview runs every bridge call on its own thread (`webview/util.py:308-309`), so `set_offline_mode` (`core/api.py:4151`) or a `play_track` can run while another thread calls `get_queue()`.
- **User impact:** `js/queue.js:146` highlights the row with `index === currentIndex`; with an out-of-range index no row is highlighted. Low impact, but the payload is the contract other components consume.
- **Evidence:**
  ```python
  # core/api.py:1772-1780
  def get_queue(self):
      """Return current queue state."""
      return {
          "tracks": self._core.engine.queue.tracks,
          "current_index": self._core.engine.queue._current_index,
          ...
      }
  ```
  ```python
  # audio/queue.py:37-45  (the public accessor that DOES lock)
  @property
  def current_index(self) -> int:
      with self._lock:
          return self._current_index
  ```
- **Reproduction / verification:** the inconsistency is a TOCTOU between two unsynchronised reads; it is reproducible by calling `queue.tracks` and `queue._current_index` from one thread while another thread calls `queue.set_tracks(...)`. Not observed in the 4000-iteration fuzz of `%TEMP%\opencode\wn17_probe2.py` (section B), which only exercised the queue's own invariants.
- **Suggested fix:** use `queue.current_index` (the locking property) in `get_queue()`, and — better — add a `PlaybackQueue.snapshot()` that returns `tracks` + `current_index` + `current_track` under one lock acquisition.
- **Fix side effects:** none; the public property returns the same value.
- **Discovered by:** A

#### F-WN-17-10  [P3] — `resolve_stream_url()` can block its caller for up to ~33 s; there is no overall timeout on the resolution cascade
- **File:** `audio/engine.py:121-151`, `audio/engine.py:153-508` (in particular L208, L223, L278, L305, L322, L349, L367)
- **Confirmed:** yes
- **Description:** `resolve_stream_url()` is fully synchronous. For `source == "youtube"` the worst case is: 10 s waiting for the direct `get_stream_url` (`audio/engine.py:208`), up to 3 s for the oembed lookup (`audio/engine.py:223`, outside the cascade budget), then the SoundCloud fallback loop bounded by `cascade_deadline = time.monotonic() + 20.0` (`audio/engine.py:278`) which also covers the Tier-2 YouTube search (6 s + 8 s waits). Total ≈ 33 s for one call. The `resolver.resolve()` wrapper adds a 12 s single-flight wait for non-owners (`core/resolver.py:224`).
- **Cause:** the cascade budget (`cascade_deadline`) starts only *after* the direct attempt, so the 10 s direct wait and the 3 s oembed wait are not counted against it; and there is no deadline on the whole call.
- **Trigger conditions:** an unresolvable or slow track. The call sites are `core/proxy.py:817`, `core/proxy.py:899`, `core/proxy.py:925` (proxy request threads) and `core/api.py:3661` (`prefetch_track`, on the prefetch executor) — **never on the bridge/UI thread**, so the UI is not frozen. The proxy is a `ThreadingHTTPServer` with `daemon_threads = True` (`core/proxy.py:421-430`), so other requests are not blocked.
- **User impact:** the audio request for an unresolvable track hangs for up to ~33 s before the proxy answers 404/400; the frontend shows a spinner for that whole time and then an error. Under repeated retries this can stack up proxy threads.
- **Evidence:**
  ```python
  # audio/engine.py:278
  cascade_deadline = time.monotonic() + 20.0
  ```
  ```python
  # audio/engine.py:208
  event.wait(timeout=10)
  ```
  ```python
  # audio/engine.py:121-151 (resolve_stream_url — synchronous, no timeout of its own)
  def resolve_stream_url(self, track: dict) -> Optional[str]:
  ```
- **Reproduction / verification:** read the waits at `audio/engine.py:208`, `223`, `305`, `322`, `349`, `367` and add them up; `core/proxy.py:817/899/925` show the callers are the request threads. `tests/test_engine_resolve.py` exercises the cascade with fakes but does not assert an upper bound on the total wait.
- **Suggested fix:** start the deadline at the top of `_resolve_via_network` (so the direct attempt and the oembed lookup are inside the same budget) and give `resolve_stream_url()` an overall deadline.
- **Fix side effects:** a shorter budget reduces the chance that a slow-but-successful provider gets a chance; the budget must stay comfortably above a healthy `get_stream_url` round trip (the current direct wait is 10 s).
- **Discovered by:** A

---

### 3. Clean areas

Checked and found **correct** (no finding):

1. **`current_index` is always a valid index or `-1`, and `current_track` always agrees with it.** Verified by exhaustive enumeration (`move_track` over all `(n, current, old, new)` combinations for `n` = 2..6: 0 mismatches) and by a 4000-iteration randomised fuzz over `next/prev/jump/remove/move/add/clear/shuffle/repeat/set_tracks` (0 invalid indices, 0 disagreements between `current_track` and `tracks[current_index]`). `current_track` (`audio/queue.py:23-29`), `current_index` (`audio/queue.py:37-40`), `remove_track` (`audio/queue.py:186-191`), `move_track` (`audio/queue.py:206-213`), `clear` (`audio/queue.py:290-296`), `set_tracks` (`audio/queue.py:124`) all maintain it.
2. **`set_tracks` clamps `start_index`** — `max(0, min(start_index, len(tracks) - 1)) if tracks else -1` (`audio/queue.py:124`): 99 → 2 (last), -5 → 0, empty list → -1. ✓
3. **`move_track`'s index arithmetic is correct.** All three branches (`old == current`, `old < current and new >= current`, `old > current and new <= current`) were verified by exhaustive enumeration — the currently playing track is never displaced by a reorder.
4. **The shuffle ORDER is preserved, not lost, and the current track keeps playing.** Enabling shuffle pins the current track at index 0 and shuffles only the remainder (`audio/queue.py:75-82`); the order is stored in `_original_order` and restored verbatim when shuffle is switched off (`audio/queue.py:89-96`, verified: `[0..5]` → shuffled → `[0..5]`). Setting `shuffle = True` twice is idempotent (the `enabled and not self._shuffle` guard at `audio/queue.py:72`); `shuffle = False` twice is idempotent too.
5. **`get_upcoming()` DOES account for shuffle** — it slices the live `_tracks` list, so it returns the real upcoming order (`audio/queue.py:298-302`; verified: upcoming `[3,0,1]` == the real next three of the shuffled order).
6. **The repeat mode strings match on all three sides — no divergence.** Backend: `self._repeat: str = "off"  # off, one, all` (`audio/queue.py:20`), the setter accepts exactly `("off", "one", "all")` (`audio/queue.py:116`), the toggle cycles `modes = ["off", "all", "one"]` (`audio/queue.py:272`) → observed cycle `off → all → one → off`. Bridge: `"""Cycle repeat mode (off -> all -> one -> off)."""` (`core/api.py:2011`) and `self._emit("repeat_changed", {"state": mode})` (`core/api.py:2013`). Frontend: `const mode = await api('toggle_repeat'); … mode !== 'off'` (`js/player.js:945-950`, `981-985`), `if (mode === 'one') {…'repeat-1'…} else {…'repeat'…}` (`js/player.js:2022-2030`), and `const repeatMode = data?.state ?? 'off'; const repeatOn = repeatMode !== 'off';` (`js/events.js:298-299`). All three use `off` / `all` / `one`. ✓ An invalid mode is rejected by the setter and leaves the previous mode untouched (verified: `q.repeat = "bogus"` → still `"all"`).
7. **End-of-queue behaviour is correct and matches the documented modes.** repeat `off` → `next_track()` returns `None` and stays put (`audio/queue.py:227-229`, verified: current index unchanged); repeat `all` → wraps to index 0 (`audio/queue.py:241-242`, verified); repeat `one` → returns the *same* track with the index unchanged (`audio/queue.py:221-222`, verified) and does **not** pollute the history stack.
8. **`previous_track()` at index 0 is well-defined and intentional** — with an empty history it stays at index 0 and returns the current track (`audio/queue.py:261-263`), which the frontend turns into a restart of the current track; pinned by `tests/test_engine_notify.py:503-510`. The history stack is walked first and out-of-range entries are discarded, not followed (`audio/queue.py:256-260`). `prev_track` deliberately does **not** emit `queue_ended` (pinned by `tests/test_engine_notify.py:477-486`).
9. **`_notify_track_changed()` is called exactly once per engine operation** — `play_track` (1), `play_queue` (1), `next_track` (1, only when a track was returned), `prev_track` (1). The bridge's play path notifies twice on purpose (loading state, then the resolved URL), and the frontend tolerates that: `js/player.js:1687-1692` only restarts when the source URL actually changed.
10. **The "empty queue" case is handled.** `play_track(None)` / `play_queue([])` return early without notifying (`audio/engine.py:36-37`, `audio/engine.py:45-46`); the queue cannot become empty while a track is playing, because `AppApi.clear_queue` re-seeds it with the current track (`core/api.py:1842-1846`) and `AppApi.remove_from_queue` refuses to remove the current entry (`core/api.py:1829-1830`). The end-of-playback state is signalled by the dedicated `queue_ended` event (`core/api.py:1244-1253`), handled by the frontend at `js/events.js:396-403` → `stopPlaybackForQueueEnd()` (`js/player.js:1829-1853`).
11. **`PlaybackQueue` is properly locked and follows the AGENTS.md lock rule.** `self._lock = threading.RLock()` (`audio/queue.py:15`) and **every** public accessor/mutator takes it (`current_track`, `current_index`, `tracks`, `count`, `is_empty`, `shuffle` getter/setter, `repeat` getter/setter, `set_tracks`, `add_track`, `add_tracks`, `remove_track`, `move_track`, `next_track`, `previous_track`, `toggle_shuffle`, `toggle_repeat`, `jump_to`, `clear`, `get_upcoming`). The `RLock` is required because the setters re-enter the properties (`audio/queue.py:75`, `85`, `127`). No second lock was opened for any new field. ✓ (The single exception is the caller-side direct read of `_current_index` in `core/api.py:1776` — reported as F-WN-17-9.)
12. **`AudioEngine`'s own shared fields are write-once at startup and therefore race-free in practice**: `engine.proxy = self.proxy` and `engine.app_core = self` are set in `AppCore.__init__` (`core/app.py:126`, `core/app.py:138`), and `engine._on_track_changed` / `engine._on_queue_end` are wired once in `AppApi.__init__` (`core/api.py:374`, `core/api.py:380`) before any worker thread exists. `_notify_track_changed` reads `self.proxy` without a lock, but the reference never changes after startup.
13. **`resolve_stream_url()` is never called on the bridge/UI thread.** Call sites: `core/proxy.py:817`, `core/proxy.py:899`, `core/proxy.py:925` (proxy request threads) and `core/api.py:3661` (`prefetch_track`, submitted to `self._prefetch_executor` at `core/api.py:3678`). ✓ (Its blocking cost is still a defect — F-WN-17-10.)
14. **`resolve_stream_url()` delegates to the shared resolver and does not keep a private cache.** It uses `self.app_core.resolver.get_cached_url(...)` and `resolver.resolve(source, source_id, _network)` (`audio/engine.py:137-149`), i.e. the mem → DB → network, single-flight coordinator of `core/resolver.py`. ✓ It also guards against the `source_id` being a row id (`audio/engine.py:175`: `direct_id = source_id if isinstance(source_id, str) else ""`).
15. **Exceptions in the resolution cascade are contained.** `_network()` converts any exception into `(None, error)` (`audio/engine.py:143-147`), `StreamResolver.resolve` catches anything raised by `resolver_fn` (`core/resolver.py:216-217`), and every provider call in `_resolve_via_network` is wrapped in `try/except` with `event.set()` so no `wait()` can hang forever (`audio/engine.py:206-207`, `300-302`, `318-319`, `344-346`, `404-405`, `445-446`, `504-505`). A failed resolution surfaces as `None` → the proxy answers 404/400 (`core/proxy.py:820-825`, `927-929`) and the bridge reports *"Не удалось найти поток для …"* (`core/api.py:1585-1587`, `core/api.py:1717-1721`) — the UI does get an error, not a silent hang.
16. **`_emit` is never called on the UI thread by this area.** `_notify_track_changed` → `AppApi._on_track_changed` → `_emit` (`core/api.py:1240`), and `_emit` hands off to an `EmitWorker` thread when it is on the main thread (`core/api.py:1147-1154`). The queue's own callbacks run on whichever thread called the bridge method (a pywebview worker thread), so the `_emit` fast path is safe.
17. **`_notify_track_changed` always produces a proxy URL for a playable track.** A `http(s)` `file_path` and an existing local file both become `http://127.0.0.1:<port>/…` URLs (`audio/engine.py:88-117`); an unresolved track keeps `stream_url` empty on purpose so the frontend shows the loading state (`audio/engine.py:118`). The payload is a **copy** of the queue's dict (`audio/engine.py:81`), so the live queue entry is never mutated by the notification.
18. **`PlaybackQueue.update_current()` and `prev_track = previous_track`** (`audio/queue.py:276-278`) are harmless aliases/utility methods with no caller in the app.
19. **Session restore/save keeps the queue's shuffle/repeat consistent.** `main.py:319-321` restores the queue first and then applies `queue.shuffle` / `queue.repeat`; the shuffle setter pins the restored current track at index 0 (`audio/queue.py:75-82`), so the persisted `queue_index` is honoured through the track, not the index. `main.py:561-569` saves `queue.shuffle` / `queue.repeat` — the same `"off"/"all"/"one"` vocabulary used everywhere else. ✓

---

### 4. Coverage gaps

- **The live app was not run** (per the ground rules). All behavioural claims were verified by reading the code and by executing the real `audio/queue.py` / `audio/engine.py` classes in isolation with synthetic tracks and fake providers; the WebView2 UI was never exercised.
- **Provider behaviour was not exercised.** `_resolve_via_network` was read but not executed against the real YouTube / SoundCloud / Yandex / Spotify services: the timing figures in F-WN-17-10 are derived from the source, not measured end-to-end. `tests/test_engine_resolve.py` (1134+ lines) was skimmed for coverage only, not re-run per provider.
- **`core/proxy.py` was read only at the call sites of `engine.resolve_stream_url` (L800-939) plus the server class (L421-441).** The proxy's own SSRF guard, its URL self-healing and its cache handling are WN-11's area and were not audited here.
- **Concurrency findings are structural.** F-WN-17-2 was reproduced by deliberately widening the race window; the *natural* hit rate under real user input was not measured, and the exact interleaving that triggers it in the app is a hypothesis. F-WN-17-9 is a code-level TOCTOU that I did not manage to trigger in the fuzz run.
- **The `shuffle` / `repeat` frontend desync (F-WN-17-4) was not observed in a running UI.** The mismatch between `get_settings()`'s shape and `applySettings()`'s access is confirmed by reading both sides; the visible consequence (repeat button lit, library "Перемешать" turning shuffle off) follows from `js/library-view.js:182` but was not clicked through.
- **The `AudioEngine.play_track()` queue-wipe (F-WN-17-3)** was confirmed at the engine level and by code reading of the bridge; the four frontend call sites were identified by grep but not exercised in a browser.
- **Third-party/legacy callers of `audio/queue.py` were not searched exhaustively.** `PlaybackQueue.prev_track = previous_track` (`audio/queue.py:278`) is documented as an alias for external callers; no in-repo caller was found besides `audio/engine.py`.
- **`utils/file_scanner.py` was only read at L118-147** to confirm that locally scanned tracks always carry a DB `id` (which is what keeps `_track_key` unique for local tracks in practice). A full scan of every producer of queue entries (services, playlists, flow/autoplay) was out of scope.
