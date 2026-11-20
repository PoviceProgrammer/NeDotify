## AREA WN-17 — Audio engine & playback queue — ROLE B

### 1. Scope reviewed

- `audio/engine.py` — lines 1–508 (read in full)
- `audio/queue.py` — lines 1–302 (read in full)
- Note: the area map (`docs/audits/WIN_AUDIT_AREAS.md:31`) quotes `audio/engine.py` as 440 L and `audio/queue.py` as 267 L. The current files are **508 L** and **302 L**. All line numbers below are physical 1-based lines of the files as they exist now.

Callees traced into other areas (read only far enough to establish the contract; the defect, if any, is attributed to the owning area):

- `core/api.py` — L1407–1428 (`report_position`), L1437–1606 (`play_track`), L1608–1744 (`_resolve_track`), L1761–1851 (queue bridge surface), L2016–2075 (`get_next_track`), L3640–3683 (`prefetch_track`), L4143–4158 (offline-mode queue rewrite)
- `core/app.py` — L125–138 (engine wiring), L296–506 (`re_resolve_stream_url_async` + its own fallback cascade), L361–374 (`threading.Timer` reading `engine.queue.current_track`)
- `main.py` — L313–330 (session restore), L391–398 (autoplay), L557–569 (session save)
- `core/proxy.py` — L684–692 (`_resolve_stream_local_file` → `_safe_stream_local_path`), L733–960 (`/api/stream` and `/` handlers, `parse_qs` parameter reads, SSRF guard), L421–430 (`ThreadingHTTPServer`)
- `core/playback_recovery.py` — L1–183 (a third, independent resolution cascade)
- `core/resolver.py` — used through `engine.resolve_stream_url` (cache + single-flight)
- `core/session.py` — L39–89 (queue persistence, `_slim_track`)
- `utils/url_safety.py` — L1–37 (`is_safe_media_url`)
- `.venv_win/Lib/site-packages/webview/util.py` — L234–315 (**every JS→Python bridge call runs on its own `Thread`**, L308-309) — the fact that makes the bridge surface genuinely concurrent
- `ui/web_new_v2/js/queue.js` (L60–130), `ui/web_new_v2/js/player.js` (L630–700, L865–914, L1425–1520, L1625+), `ui/web_new_v2/js/events.js` (L95–105), `ui/web_new_v2/js/search-discovery.js` (L43), `ui/web_new_v2/js/feature-controls.js` (L69), `ui/web_new_v2/js/home.js` (L784), `ui/web_new_v2/js/hotkeys.js` (L179–209) — read only to establish what the backend contract actually drives
- Tests read: `tests/test_queue.py` (109 L, 11 tests), `tests/test_engine_notify.py` (551 L, 33 tests), `tests/test_engine_resolve.py` (~1140 L, 67 tests), `tests/test_player_recovery_transitions.py` (246 L — **pure JS/frontend, touches no Python queue code**), `tests/test_media_guard_f3.py` (L215–291), `tests/test_api_audit_b.py` (L100–150, L614–712)

Verification harness (scratch, outside the repo): `C:\Users\Артур\AppData\Local\Temp\opencode\wn17_verify.py` and `...\wn17_verify2.py`. Both import the real `audio.queue` / `audio.engine` / `core.api` and interleave threads deterministically. No repo file was modified.

---

### 2. Findings

#### F-WN-17-1  [P1] — `get_queue()` emits a non-atomic snapshot: the track list and `current_index` are read at different instants

- **File:** `core/api.py:1772-1780`, `audio/queue.py:42-45`, `audio/queue.py:37-40`
- **Confirmed:** yes
- **Description:** `get_queue()` builds the payload the frontend uses as the single source of truth for the queue drawer from two independent reads. `queue.tracks` copies the list **under the lock**; `queue._current_index` is read **outside the lock** and through the *private* attribute, bypassing the `current_index` property that does take the lock. Nothing ties the two together, so the emitted dict can pair an old track list with a new index and a new current track.
- **Cause:** `PlaybackQueue` exposes no single atomic "give me the whole state" operation. `core/api.py` therefore has to compose the snapshot itself out of one locked accessor and one unlocked private attribute, and the composition is not atomic.
- **Trigger conditions:** any bridge call that mutates the queue concurrently with `get_queue()`. pywebview runs **every** JS→Python call on its own thread (`.venv_win/Lib/site-packages/webview/util.py:308-309`: `thread = Thread(target=_call); thread.start()`), so `get_queue()` (called on every `queue_updated` emit) can genuinely overlap `play_track`, `next_track`, `remove_from_queue` or `clear_queue` from another bridge thread. Reproduced deterministically below.
- **User impact:** the frontend receives `tracks` = the old list but `current_index` / `current_track` = the new state. `ui/web_new_v2/js/queue.js:67` calls `renderQueue(q.tracks, q.current_index)` → the highlighted "now playing" row points at an index that does not exist in the list it was given (or at the wrong track). `ui/web_new_v2/js/player.js:1515-1521` (`flowQueueSnapshot`) compares `current_index` **and** `tracks` together to decide whether the queue changed; a mixed snapshot makes the flow-autoplay guard believe the queue changed when it did not (or vice versa).
- **Evidence:**
  ```python
  # core/api.py:1772-1780
  def get_queue(self):
      """Return current queue state."""
      return {
          "tracks": self._core.engine.queue.tracks,          # locked copy (list only)
          "current_index": self._core.engine.queue._current_index,   # UNLOCKED, private
          "current_track": self._core.engine.queue.current_track,   # separate locked read
          "shuffle": self._core.engine.queue.shuffle,
          "repeat": self._core.engine.queue.repeat,
      }
  ```
  ```python
  # audio/queue.py:42-45
  @property
  def tracks(self) -> list:
      with self._lock:
          return self._tracks.copy()
  ```
- **Reproduction / verification:** deterministic interleaving harness (`wn17_verify2.py`, section B2): the `tracks` property is wrapped so that a second thread replaces the queue with a 9-track list *between* the copy and the index read. Result:
  ```
  snapshot tracks len : 3 (the OLD 3-track queue)
  snapshot current_idx: 4 (read AFTER the replacement)
  snapshot cur track  : 4
  real queue now      : 9 tracks, current_index 4
  ```
  i.e. the emitted snapshot contains a `current_index` of 4 and a `current_track` whose id is not present in the emitted 3-track `tracks` list.
- **Suggested fix:** add a single `PlaybackQueue.snapshot()` that returns `(tracks, current_index, current_track, shuffle, repeat)` under one lock acquisition, and make `get_queue()` use it. The same helper then serves `get_next_track` (F-7).
- **Fix side effects:** `get_queue()`'s payload shape is consumed by `js/queue.js`, `js/player.js` (`flowQueueSnapshot`), `js/utils.js` and `core/api.py::_notify_queue_updated`; the keys must stay identical. A snapshot method also means the queue copies the track list once per call instead of once per field — no behavioural change, but `main.py:565` (`queue=engine.queue.tracks`) should be switched to the same helper for consistency.
- **Discovered by:** B

#### F-WN-17-2  [P1] — The "cannot remove the current track" invariant lives in the caller and is a TOCTOU: the current track can be removed anyway

- **File:** `core/api.py:1819-1836`, `audio/queue.py:173-191`
- **Confirmed:** yes
- **Description:** `remove_from_queue` performs a three-step read-modify-write against the queue with no shared lock: (a) bounds-check, (b) compare the index against the **private** `_current_index`, (c) call `queue.remove_track(index)`. Step (c) does not re-validate (b). `PlaybackQueue.remove_track` has no "not the current track" rule of its own — the invariant exists only in `core/api.py`. If the queue advances between (b) and (c), the track that is current at the moment of removal is removed, and `remove_track` silently re-points `_current_index` at a *different* track.
- **Cause:** the invariant is enforced outside the class that owns the state, using an unlocked private attribute, instead of inside an atomic queue operation.
- **Trigger conditions:** a `remove_from_queue` bridge call overlapping any other bridge call that moves the cursor (`next_track`, `prev_track`, `play_track`, `reorder_queue`, or `play_queue` with a new list). All of these are separate pywebview threads.
- **User impact:** the track the UI is playing disappears from the queue, the backend's current index now points at a different track, and **no `track_changed` event is emitted** — the frontend keeps playing audio for a track the backend no longer considers current. `core/api.py` then answers `{"success": True}` for a removal that broke the queue's own invariant.
- **Evidence:**
  ```python
  # core/api.py:1826-1831
  queue = self._core.engine.queue
  if not (0 <= index < len(queue.tracks)):
      return {"success": False, "error": "Неверный индекс очереди"}
  if index == queue._current_index:
      return {"success": False, "error": "Cannot remove current track"}
  queue.remove_track(index)
  ```
  ```python
  # audio/queue.py:186-191  (inside remove_track, under the lock)
  if len(self._tracks) == 0:
      self._current_index = -1
  elif index < self._current_index:
      self._current_index -= 1
  elif index == self._current_index:
      self._current_index = min(self._current_index, len(self._tracks) - 1)
  ```
  The last line is the smoking gun: the queue *does* handle "the removed track was the current one" — by pointing the cursor at the next track, silently, with no notification.
- **Reproduction / verification:** deterministic interleaving harness (`wn17_verify2.py`, section D2): `PlaybackQueue.remove_track` is wrapped so that another thread advances the queue by two positions immediately before the removal executes (i.e. exactly between the guard read and the write):
  ```
  guard passed, remove_track(2) executed -> {'success': True}
  queue count now : 3
  current_index   : 2 -> current track id: 3
  ```
  The track that was current (id 2) is gone from the queue even though the guard had already approved the removal.
- **Suggested fix:** move the invariant into `PlaybackQueue` — e.g. `remove_track` refuses to remove the current track (or `remove(index)` returns a status) — and expose one atomic operation to the bridge. The bridge should not need to know the queue's internals to keep it consistent.
- **Fix side effects:** `ui/web_new_v2/js/utils.js:1346-1358` and `js/queue.js:201-203` call `remove_from_queue` and surface `{"success": false, "error": ...}` as a toast; a refusal now surfacing from the queue layer needs the same user-facing message. The existing "Cannot remove current track" message should stay.
- **Discovered by:** B

#### F-WN-17-3  [P1] — `AudioEngine.next_track()` announces "whatever is current now", not "the track it just moved to": a concurrent advance silently skips a track

- **File:** `audio/engine.py:55-63`, `audio/engine.py:65-70`, `audio/engine.py:78-79`
- **Confirmed:** yes
- **Description:** `engine.next_track()` performs two steps: `queue.next_track()` (atomic) and then `_notify_track_changed()`, which **re-reads** `self.queue.current_track` (line 79) instead of announcing the track the queue just selected. The "advance + announce" transition is split across two objects that share no lock, so it cannot be made atomic. The same shape applies to `prev_track()` (lines 65-70).
- **Cause:** the queue owns the cursor but cannot announce; the engine announces but does not own the cursor. Neither side can make the pair atomic without a shared lock or a callback fired from inside the queue's lock.
- **Trigger conditions:** two overlapping `next_track` bridge calls. There are three independent JS callers that can fire simultaneously: the `<audio>` `ended` handler (`ui/web_new_v2/js/player.js:646`), the crossfade auto-transition (`ui/web_new_v2/js/player.js:1484`), and the media-session / hotkey handlers (`ui/web_new_v2/js/hotkeys.js:179`, `:206`). Each is a separate pywebview thread.
- **User impact:** the backend consumes two queue positions but the frontend is told about only one of the new tracks — **a track is skipped** and the UI's queue position drifts from the backend's. `js/events.js:97-100` dispatches `nedotify:track_changed` → `player.js:1625 onTrackChanged()`, which is what actually loads the audio element, so the skipped track is never played and never announced.
- **Evidence:**
  ```python
  # audio/engine.py:55-63
  def next_track(self):
      """Advance the queue and notify the UI. Returns the new track or None at the end."""
      track = self.queue.next_track()
      if track:
          self._notify_track_changed()      # <- re-reads queue.current_track
          return track
      if self._on_queue_end:
          self._on_queue_end()
      return None
  ```
  ```python
  # audio/engine.py:78-79
  def _notify_track_changed(self):
      current = self.queue.current_track   # <- second, unsynchronised read
  ```
- **Reproduction / verification:** deterministic interleaving harness (`wn17_verify2.py`, section E2) — `PlaybackQueue.next_track` is wrapped so the second thread runs to completion while the first is between `next_track()` and `_notify_track_changed()`:
  ```
  next_track() returned : [1, 2]
  track_changed emitted : [2, 3]
  final current_index   : 3
  ```
  The queue advanced to ids 1 and 2, but the frontend was told about ids 2 and 3 — id 1 was consumed and never announced. The same harness reproduces the `prev_track` variant (section E3): returned `[3, 4]`, emitted `[3, 2]`.
- **Suggested fix:** make the queue own the transition and hand the selected track back as the *only* source of truth — e.g. `queue.next_track()` returns the track it moved to and the engine announces **that** track instead of re-reading; better still, the queue fires a `current_changed(track)` callback from inside its own lock so "advance + announce" is one atomic step. The engine's `_notify_track_changed` would then take the track as a parameter.
- **Fix side effects:** `_notify_track_changed()` currently derives the proxy URL from the queue's current track and is also called with no argument from `core/api.py:1597`, `:1635`, `:1733` and `main.py` — changing its signature means updating those call sites. `tests/test_engine_notify.py` asserts the emitted payload for many of them; they would need to keep the same shape.
- **Discovered by:** B

#### F-WN-17-4  [P2] — `AudioEngine.play_track()` conflates "play this track" with "replace the whole queue with this track"

- **File:** `audio/engine.py:35-39`, `core/api.py:1605-1606`, `ui/web_new_v2/js/search-discovery.js:43`, `ui/web_new_v2/js/feature-controls.js:69`, `ui/web_new_v2/js/player.js:892`, `ui/web_new_v2/js/player.js:895`, `ui/web_new_v2/js/player.js:898`, `ui/web_new_v2/js/player.js:1704`, `ui/web_new_v2/js/home.js:784`
- **Confirmed:** yes
- **Description:** `play_track` is implemented as `self.queue.set_tracks([track], start_index=0)`. `set_tracks` *replaces* the queue. The engine offers no "play this one track without touching the queue" operation, so every caller that means "play this track" also means "discard the queue". The frontend calls `play_track(track)` **without** a track list in at least six places, and `core/api.py:1605-1606` routes that case straight into `engine.play_track`.
- **Cause:** the engine's API has only "replace the queue" and "append to the queue"; the "play a single track in the context of the existing queue" operation has no name, so it defaults to the destructive one.
- **Trigger conditions:** any of the six JS call sites above (search-discovery result, feature-controls "play current", player.js's fallback paths, home.js). `core/api.py:1605-1606`:
  ```python
  else:
      self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  ```
- **User impact:** a 20-track queue becomes a 1-track queue. The UI's queue drawer keeps rendering the old list, because the no-track_list branch of `play_track` **never emits `queue_updated`** (`core/api.py:1605-1606` has no `_notify_queue_updated()` call, unlike the `track_list` branch at L1528/1540/1547/1567/1581). Pressing "next" then ends the queue after one track, while the drawer still shows the old list.
- **Evidence:**
  ```python
  # audio/engine.py:35-39
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)   # set_tracks REPLACES the queue
      self._notify_track_changed()
  ```
  ```python
  # audio/queue.py:119-124
  def set_tracks(self, tracks: list, start_index: int = 0):
      with self._lock:
          self._tracks = tracks.copy()          # <- the old queue is dropped
          self._original_order = tracks.copy()
          self._current_index = max(0, min(start_index, len(tracks) - 1)) if tracks else -1
  ```
- **Reproduction / verification:** harness (`wn17_verify.py`, sections A / F2):
  ```
  queue before: 20 current_index 3
  queue after engine.play_track(): 1 current_index: 0
  ```
  The behaviour is also pinned (deliberately) by `tests/test_engine_notify.py:327-335` (`test_play_track_replaces_the_queue_and_notifies`).
- **Suggested fix:** give the engine an explicit, non-destructive "play this track" operation (e.g. `play_single(track)` that inserts/replaces only the *current* slot) and keep `set_tracks` for the genuine "replace the queue" case. The queue needs a way to hold a current track that is not simply "index N of the list" (see F-5).
- **Fix side effects:** `tests/test_engine_notify.py:327-335` pins the destructive behaviour and will have to change together with the fix. The *missing* `queue_updated` emit in the no-track_list branch is a **WN-05** (`core/api.py`) defect, not WN-17's — this report only names the engine-side contract.
- **Discovered by:** B

#### F-WN-17-5  [P2] — `PlaybackQueue` cannot represent "the queue is empty but a track is still playing"

- **File:** `audio/queue.py:119-132`, `audio/queue.py:23-29`, `core/api.py:1838-1851`
- **Confirmed:** yes
- **Description:** `set_tracks` clamps `_current_index` into `[0, len-1]` whenever the list is non-empty, so **a non-empty queue always has a current track**; the "no current track" state (`-1`) is reachable only when the queue is empty. There is no separate "playing" flag and no separate current-track slot. The engine likewise has no playback state at all: "what is playing" is *always* inferred from `current_index` + `current_track`.
- **Cause:** the queue conflates "the ordered list of upcoming tracks" with "the track that is playing". The two are different things: a queue can be empty while something is still audible, and a track can be playing that is not (yet) in the list.
- **Trigger conditions:** any operation that should stop playback but keep the queue, or empty the queue without stopping playback. The bridge's own "clear the queue" method works around it:
  ```python
  # core/api.py:1838-1846
  queue = self._core.engine.queue
  current = queue.current_track
  queue.clear()
  # Keep the current track so playback state stays valid.
  if current:
      queue.set_tracks([current], 0)
  ```
  The comment is the admission: the queue cannot express "empty but still playing", so the current track has to be smuggled back in as a one-element queue.
- **User impact:** "clear the queue" cannot mean "stop playing and empty the list"; the backend has to misrepresent the queue contents. More broadly, because there is no explicit state, every "is something playing?" question in the system is answered by re-reading an index — which is precisely what makes F-3 (announce the wrong track) and F-7 (stale index) possible. A player that cannot represent "idle / resolving / playing / failed" also cannot express "the stream resolution failed but the queue is unchanged".
- **Evidence:**
  ```python
  # audio/queue.py:124
  self._current_index = max(0, min(start_index, len(tracks) - 1)) if tracks else -1
  ```
  ```python
  # audio/queue.py:26-29
  with self._lock:
      if 0 <= self._current_index < len(self._tracks):
          return self._tracks[self._current_index]
      return None
  ```
  There is no other field describing the current track; `PlaybackQueue.__init__` (`audio/queue.py:14-21`) holds `_tracks`, `_original_order`, `_current_index`, `_shuffle`, `_repeat`, `_history_stack` and nothing else.
- **Reproduction / verification:** `PlaybackQueue.set_tracks([t], 0)` then `q.clear()` → `q.current_track is None` and `q.count == 0`: the only way to have no current track is to have no queue. The `core/api.py:1843-1846` workaround above is the observable proof that the state is not representable.
- **Suggested fix:** separate the "current/playing track" from the ordered list — either the queue holds an explicit `_current` reference plus an index, or (cleaner) the engine owns the current track and the queue owns only ordering. Then "empty the queue, keep playing" becomes expressible, and the announce step can be made atomic (F-3).
- **Fix side effects:** `current_index` is part of the bridge payload (`core/api.py:1776`) and is consumed by `js/queue.js:67`, `js/player.js:1517`, `js/utils.js:115`, `core/api.py:2023-2039` and `main.py:566` — an explicit current-track slot must still be expressible as an index for the frontend. `main.py:319` (session restore) also depends on `set_tracks(tracks, index)` placing the current track.
- **Discovered by:** B

#### F-WN-17-6  [P2] — The queue's lock protects the list but not the track dicts: `tracks` is a shallow copy and `current_track` returns the live dict

- **File:** `audio/queue.py:42-45`, `audio/queue.py:23-29`, `core/api.py:1633-1634`, `core/api.py:1728-1729`, `main.py:565`
- **Confirmed:** yes
- **Description:** `PlaybackQueue.tracks` copies the **list** (`self._tracks.copy()`) but the **track dicts inside are the queue's own objects**. `PlaybackQueue.current_track` returns the internal dict itself, with no copy at all. So a caller that mutates a track dict obtained from either accessor mutates the queue's live state — bypassing the lock, bypassing every queue method, and leaving no trace in `_history_stack` / `_original_order`. The queue's `_lock` therefore protects the *container*, not the *state it contains*.
- **Cause:** the accessors were written as "give me the data" rather than "give me a snapshot of the data"; the lock is only as strong as the objects it guards, and the guarded objects escape it.
- **Trigger conditions:** any caller that mutates a dict obtained from `queue.tracks` or `queue.current_track`. Two production call sites already do exactly that:
  ```python
  # core/api.py:1633-1634
  cur = self._core.engine.queue.current_track
  cur["file_path"] = track.get("file_path")
  ```
  ```python
  # core/api.py:1728-1729
  cur = self._core.engine.queue.current_track
  cur["file_path"] = stream_url
  ```
  These are *relying* on the aliasing — the frontend is never told the resolved URL if the accessors start copying.
- **User impact:** (a) queue invariants can change without any queue API call — e.g. the `file_path` of the current track is rewritten from outside; (b) a reader that holds a track dict can observe it being rewritten under it (the write is not covered by the queue's lock); (c) "copying" the queue does not copy it: `main.py:565` hands the live dicts to the session layer (which happens to re-project them via `core/session.py:33-37`, so no leak today — but the contract is accidental).
- **Evidence:**
  ```python
  # audio/queue.py:42-45
  @property
  def tracks(self) -> list:
      with self._lock:
          return self._tracks.copy()          # list copied, dicts shared
  ```
  ```python
  # audio/queue.py:26-29
  with self._lock:
      if 0 <= self._current_index < len(self._tracks):
          return self._tracks[self._current_index]   # the LIVE dict, not a copy
  ```
- **Reproduction / verification:** harness (`wn17_verify.py`, section F):
  ```
  list identity differs  : True
  queue's own dict changed: MUTATED BY CALLER
  ```
  i.e. `snapshot = q.tracks; snapshot[0]["title"] = "MUTATED BY CALLER"` changes `q.current_track["title"]`.
- **Suggested fix:** either make the queue the only writer of its track dicts (add explicit mutators such as `set_current_stream(path)` and have `core/api.py` call them), or have the public accessors return copies of the dicts. The queue must own its invariants; the bridge should not be able to mutate queue state by writing into a dict it was handed.
- **Fix side effects:** **high** — `core/api.py:1634` and `core/api.py:1729` depend on the aliasing to inject the resolved URL into the queue's track. If the accessors start copying, those two lines silently stop working and the frontend never receives a resolved stream (a total playback regression). Both call sites must move to an explicit queue mutator in the same change.
- **Discovered by:** B

#### F-WN-17-7  [P2] — `get_next_track()` can raise `IndexError` on a stale snapshot; the error is swallowed and next-track preloading silently stops

- **File:** `core/api.py:2016-2075` (specifically L2020, L2023, L2024-2025, L2073-2074)
- **Confirmed:** yes
- **Description:** `get_next_track()` takes two independent reads: `tracks = queue.tracks` (a snapshot of the list) and `current_idx = queue.current_index` (a later read of the index). If the queue is replaced with a **longer** list between the two, `current_idx` can exceed `len(tracks)`, and the `repeat == "one"` branch indexes the stale snapshot without a bounds check: `dict(tracks[current_idx])`. The resulting `IndexError` is swallowed by the blanket `except Exception` at L2073 and the method returns `None`.
- **Cause:** the same non-atomic snapshot problem as F-1, but here the consequence is an exception rather than a wrong index, and there is no bounds check on the one index that is used without one.
- **Trigger conditions:** a `play_track` / `play_queue` with a bigger list (the frontend's "play all" on an album/playlist) overlapping the frontend's next-track lookahead (`ui/web_new_v2/js/player.js:1435` `window.pywebview.api.get_next_track()`), which runs on its own bridge thread.
- **User impact:** the frontend's next-track preload silently stops working (`get_next_track()` → `None`), so the gapless / crossfade transition to the next track degrades — with no error in the UI, only a `get_next_track error` line in the log.
- **Evidence:**
  ```python
  # core/api.py:2019-2025
  queue = self._core.engine.queue
  tracks = queue.tracks                  # snapshot (len N)
  if not tracks:
      return None
  current_idx = queue.current_index      # separate, later read
  if queue.repeat == 'one' and current_idx >= 0:
      return dict(tracks[current_idx])   # <- no bounds check against len(tracks)
  ```
  ```python
  # core/api.py:2073-2075
  except Exception as e:
      logger.error(f"get_next_track error: {e}")
  return None
  ```
- **Reproduction / verification:** harness (`wn17_verify2.py`, section G2): snapshot taken with 2 tracks, then the queue replaced by a 9-track list with `current_index = 6`:
  ```
  api.py:2020 snapshot len: 2 | api.py:2023 current_index: 6
  IndexError: list index out of range -> api.py:2073 swallows it, get_next_track() returns None
  ```
- **Suggested fix:** take the list and the index in one atomic `queue.snapshot()` (F-1) and bounds-check `current_idx` against `len(tracks)` before indexing.
- **Fix side effects:** the `repeat == "one"` branch is the only consumer that indexes the snapshot without a bounds check; the fix is local, but it should be verified against `tests/test_api_audit_b.py:102-150` (`get_next_track` suite) and `tests/test_player_recovery_transitions.py:179-190` (the frontend preload test).
- **Discovered by:** B

#### F-WN-17-8  [P2] — `AudioEngine` has no lock at all, and its one dynamically-added shared field (`_last_reported_position`) is not even declared in the class

- **File:** `audio/engine.py:27-33`, `core/api.py:1421-1422`, `main.py:563`
- **Confirmed:** yes
- **Description:** `PlaybackQueue` has `self._lock = threading.RLock()` (`audio/queue.py:15`) and honours the AGENTS.md rule. `AudioEngine` has **no lock**, and the shared field `_last_reported_position` is not declared in `AudioEngine.__init__` — it is created on the fly by a different module:
  ```python
  # core/api.py:1421-1422
  if hasattr(self._core, "engine") and self._core.engine:
      self._core.engine._last_reported_position = pos_sec
  ```
  and read from the main thread at shutdown:
  ```python
  # main.py:563
  position=getattr(engine, '_last_reported_position', 0),
  ```
  `getattr(..., 0)` with a default is only needed because the attribute may not exist — i.e. the engine's contract is split across two modules and neither the reader nor the writer can see the declaration.
- **Cause:** AGENTS.md states "A new shared field joins its class's existing lock rather than opening a second one". `AudioEngine` has no lock to join, so the rule could not be honoured; the field was then added without giving the class a lock at all.
- **Trigger conditions:** `report_position` is called from a bridge thread (every position tick, `core/api.py:1407`); `main.py:563` reads it from the main thread during shutdown.
- **User impact:** today the race is benign (a float store is atomic under the GIL) — the impact is structural: the engine's shared state is invisible to anyone reading the class, `main.py` has to guess a default, and the next shared field added to `AudioEngine` will follow the same pattern. `AudioEngine` also holds `self.proxy`, `self.app_core`, `self._on_track_changed` and `self._on_queue_end`, all of which are written from one thread and read from others (`core/app.py:138` writes `engine.proxy` at startup while a proxy request thread may already be inside `engine.resolve_stream_url`).
- **Evidence:**
  ```python
  # audio/engine.py:27-33
  def __init__(self):
      self.queue = PlaybackQueue()
      self.proxy = None
      self._on_track_changed = None
      self._on_queue_end = None

      self.app_core = None
  ```
  No `_last_reported_position`, no lock. `inspect.getsource(AudioEngine)` contains no `_last_reported_position` (verified).
- **Reproduction / verification:** `AudioEngine().__dict__` has no `_last_reported_position` key; the attribute only appears after `AppApi.report_position` runs (`core/api.py:1422`). `inspect.getsource(AudioEngine.__init__)` shows no lock.
- **Suggested fix:** give `AudioEngine` its own `threading.RLock()` and declare `_last_reported_position` in `__init__` under it; keep the "one lock per class" rule rather than opening a second one. Use the same lock for the "advance + announce" transition (F-3).
- **Fix side effects:** `main.py:563`'s `getattr(engine, '_last_reported_position', 0)` fallback becomes redundant but should stay harmless. No behavioural change expected.
- **Discovered by:** B

#### F-WN-17-9  [P2] — `_notify_track_changed()` performs a blocking filesystem stat on the caller's thread (the bridge thread)

- **File:** `audio/engine.py:106`, `audio/engine.py:78-119`
- **Confirmed:** yes (the blocking call and its call site); the wall-clock stall is filesystem-dependent
- **Description:** for every local track the engine calls `os.path.exists(fp)` **synchronously, on the thread that asked for playback** — in the common case the pywebview bridge thread:
  ```python
  # audio/engine.py:106
  elif fp and os.path.exists(fp):
  ```
  `fp` comes from the track's `file_path`, i.e. a path in the user's music library, which may live on a disconnected USB drive, an unmapped drive letter or a network share. On Windows a stat against an unreachable network path blocks until the SMB/redirector timeout expires — seconds to tens of seconds — with no timeout and no way to cancel.
- **Cause:** a network-capable filesystem operation is performed inline in the notification path instead of being bounded or moved to a worker.
- **Trigger conditions:** the library folder is on a network share or a removable drive that is currently unavailable. `os.path.exists` is then called on every track change for every local track.
- **User impact:** the `play_track` bridge call never returns → the frontend's `await window.pywebview.api.play_track(...)` hangs → the play button appears to do nothing and the UI feels frozen for the duration of the filesystem timeout. `core/api.py:1516` (`os.path.exists(fp) and os.path.getsize(fp) > 1024`) has the same shape but is WN-05's code.
- **Evidence:** see the snippet above; `audio/engine.py` contains exactly one filesystem call (`os.path.exists`, L106) and it sits inside the synchronous notification path.
- **Reproduction / verification:** map a drive letter to a host that is not reachable (`net use Z: \\unreachable\host`), then call `engine.play_track({"id": 1, "source": "local", "file_path": "Z:\\song.mp3", ...})` and time it — the call blocks until the redirector gives up instead of returning immediately. (Verified statically: the call is on the caller's thread with no timeout; the wall-clock duration was not measured on this machine because that would require creating a broken network mapping.)
- **Suggested fix:** bound the existence check (run it on a short-lived worker with a timeout, or cache the last known good state), and/or resolve the path to a proxy URL without stat-ing it (the proxy already validates the path through `_safe_stream_local_path`, `core/proxy.py:684-692`).
- **Fix side effects:** the `os.path.exists` check is what keeps a *missing* file from being turned into a proxy URL — `tests/test_engine_notify.py:182-193` (`test_missing_file_leaves_stream_url_unset`) pins that. Removing the stat without replacing it would regress that behaviour.
- **Discovered by:** B

#### F-WN-17-10  [P3] — `len(queue.tracks)` copies the entire queue just to read its length, at three call sites

- **File:** `core/api.py:1827`, `core/api.py:1632`, `audio/engine.py:45`
- **Confirmed:** yes
- **Description:** `PlaybackQueue` exposes `count` (O(1), `audio/queue.py:47-50`) and `is_empty` (O(1), L52-55), but three call sites use the O(n) copying `tracks` property instead:
  ```python
  # core/api.py:1827
  if not (0 <= index < len(queue.tracks)):
  # core/api.py:1632
  if _is_current() and len(self._core.engine.queue.tracks) > 1:
  # audio/engine.py:45
  if not self.queue.tracks:
  ```
- **Cause:** `count`/`is_empty` exist but the discipline was never applied to the call sites; `tracks` reads like a cheap accessor.
- **Trigger conditions:** every `remove_from_queue` and every `_deliver()` (resolution-delivery path).
- **User impact:** measured at **10.3 µs per `len(queue.tracks)` vs 0.1 µs per `queue.count`** on a 5000-track queue (100×), each call allocating a 5000-element list. In absolute terms this is sub-millisecond for a realistic queue, so it is not user-visible on its own — it is a symptom of the missing `count` discipline and of F-1 (the payload is assembled field by field instead of from one snapshot).
- **Evidence:** measurement harness (`wn17_verify.py`, section G):
  ```
  len(queue.tracks) x2000: 0.021s  (10.3 us/call, copies 5000 refs)
  queue.count      x2000: 0.000s  (0.1 us/call)
  ```
- **Suggested fix:** use `queue.count` / `queue.is_empty` at the three call sites.
- **Fix side effects:** none.
- **Discovered by:** B

#### F-WN-17-11  [P3] — Dead public API on the queue: `get_upcoming`, `jump_to`, `update_current` and the `prev_track` alias have no production caller

- **File:** `audio/queue.py:31-35`, `audio/queue.py:280-288`, `audio/queue.py:298-302`, `audio/queue.py:276-278`
- **Confirmed:** yes
- **Description:** a repo-wide grep for `get_upcoming`, `jump_to`, `update_current` finds **only their definitions** — no production caller and no test. The `prev_track = previous_track` alias (`audio/queue.py:278`) is called only from `tests/test_api_audit_b.py:701`. The project already applied a dead-code policy to this exact class:
  ```python
  # tests/test_api_audit_b.py:692-695
  assert not hasattr(PlaybackQueue, "to_serializable")
  assert not hasattr(PlaybackQueue, "get_queue_track_ids")
  ```
  These four members escape that policy.
- **Cause:** the class accumulated API surface without a contract; `get_upcoming` in particular returns the queue's **live** track dicts (a slice, so the list is new but the dicts are shared) — a future caller would inherit the aliasing defect of F-6.
- **Trigger conditions:** n/a (dead code).
- **User impact:** none today; the risk is a future caller binding to an API that has never been exercised, and `get_upcoming`'s aliasing semantics being wrong on first use.
- **Evidence:**
  ```python
  # audio/queue.py:298-302
  def get_upcoming(self, count: int = 10) -> list:
      """Get the next N upcoming tracks."""
      with self._lock:
          start = self._current_index + 1
          return self._tracks[start:start + count]
  ```
  ```python
  # audio/queue.py:276-278
  # Alias kept for external/3rd-party callers: the app itself only uses
  # previous_track() (audio/engine.py:prev_track).
  prev_track = previous_track
  ```
- **Suggested fix:** delete `get_upcoming`, `jump_to`, `update_current` and the `prev_track` alias (or give `get_upcoming` a caller and copy the dicts it returns). Note that `get_upcoming` itself is *not* a performance problem — it slices, so it is O(count), not O(n).
- **Fix side effects:** `tests/test_api_audit_b.py:701` calls `q.prev_track()` and would need updating.
- **Discovered by:** B

#### F-WN-17-12  [P3] — `engine.play_queue([])` destroys the queue while reporting "nothing happened"

- **File:** `audio/engine.py:41-47`
- **Confirmed:** yes
- **Description:** `play_queue` calls `queue.set_tracks([])` (which empties the queue and sets `_current_index = -1`) and then, because the queue is now empty, returns `None` **without notifying**:
  ```python
  # audio/engine.py:41-47
  def play_queue(self, track_list: Optional[list] = None, index: int = 0) -> None:
      if track_list is not None:
          safe_index = max(0, min(index, len(track_list) - 1)) if track_list else 0
          self.queue.set_tracks(track_list, start_index=safe_index)
      if not self.queue.tracks:
          return None
      self._notify_track_changed()
  ```
- **Cause:** the "empty list" case is funnelled through the same `set_tracks` call as a real playlist, and the "nothing to announce" early return is applied *after* the destructive mutation.
- **Trigger conditions:** any caller passing an empty list. The bridge currently only calls `play_queue` with a non-empty list (`core/api.py:1580` is inside `if track_list:`), so this is not reachable from the UI today — which is why the impact is latent.
- **User impact:** if it ever were reached, the backend queue would be empty while the frontend still shows the old list, and "next" would end the queue immediately.
- **Evidence:** harness (`wn17_verify.py`, section J):
  ```
  return: None queue count: 0 events: 0
  ```
  The behaviour is already documented in the suite as a known bug — `tests/test_engine_notify.py:350-362` carries a `strict=True` xfail: *"BUG audio/engine.py:40 - play_queue([]) destroys the playback queue while reporting 'nothing happened' (no _on_track_changed), leaving the frontend and the backend out of sync"*.
- **Suggested fix:** make `play_queue([])` a no-op (return before `set_tracks`), which is exactly what the existing xfail asserts.
- **Fix side effects:** the xfail is `strict=True`, so once the behaviour is fixed the test **fails** as XPASS — the test must be un-xfailed in the same change.
- **Discovered by:** B

#### F-WN-17-13  [P3] — The engine builds the proxy URL with two unencoded query parameters (`source`, `track_id`) while the others are encoded

- **File:** `audio/engine.py:109-117` (compare with `audio/engine.py:91-99`)
- **Confirmed:** yes (the encoding inconsistency); the escalation to an arbitrary fetch is **not** proven
- **Description:** in the local-file branch of `_notify_track_changed`, `source_id`, `title` and `artist` are percent-encoded but `track_id` and `source` are interpolated raw:
  ```python
  # audio/engine.py:109-117
  t_id = track.get("id") or 0                       # NOT encoded
  src = track.get("source") or "local"             # NOT encoded
  src_id = urllib_parse.quote(str(track.get("source_id") or ""))
  title = urllib_parse.quote(str(track.get("title") or ""))
  artist = urllib_parse.quote(str(track.get("artist") or ""))
  quoted_fp = urllib_parse.quote(str(fp))
  track["stream_url"] = (f"http://127.0.0.1:{self.proxy.port}/api/stream?url={quoted_fp}"
                         f"&track_id={t_id}&source={src}&source_id={src_id}"
                         f"&title={title}&artist={artist}{self.proxy.auth_query()}")
  ```
  The remote-URL branch (`audio/engine.py:91-99`) encodes *everything*, including `source`. So the two branches of the same function disagree about the contract.
- **Cause:** the URL is assembled by hand instead of through `urllib.parse.urlencode`, so each parameter's encoding is a manual decision that was made inconsistently.
- **Trigger conditions:** a track whose `source` or `id` contains `&`, `=` or `#`. `source`/`id` come from the frontend payload (`core/api.py::play_track` → `track_list` → `engine.play_queue`) or from provider metadata.
- **User impact:** the proxy receives duplicate query parameters. `core/proxy.py:734` reads `query_params.get('url', [None])[0]` — `parse_qs` keeps **all** values and the code takes the **first**, so the `url=` parameter is load-bearing **by position**: it must remain the first parameter in the URL, or the proxy will act on a different value. The same "first value wins" rule applies to `source` (`core/proxy.py:736`) and `source_id` (L737).
- **Evidence:** the two snippets above; the proxy side reads the first value only (`core/proxy.py:734-739`).
- **Suggested fix:** build the query with `urllib.parse.urlencode({...})` so every parameter is encoded uniformly and the ordering is explicit.
- **Fix side effects:** the exact URL string is asserted string-by-string in `tests/test_engine_notify.py:50-176` (e.g. `test_existing_local_file_is_served_through_the_stream_route` expects `"?url=" + q(fp) + "&track_id=3&source=local&..."`). `urlencode` produces the same order but encodes spaces as `+` instead of `%20` — those assertions would have to be updated, and the frontend/proxy must both accept the new encoding.
- **Discovered by:** B

#### F-WN-17-14  [P3] — The engine's SSRF guard is applied on the direct URL paths but not on the search-fallback path

- **File:** `audio/engine.py:176`, `audio/engine.py:307-319`, `audio/engine.py:440-447`
- **Confirmed:** yes (the inconsistency); the downstream impact is **bounded** by guards in other areas
- **Description:** the engine imports `is_safe_media_url` and applies it on the two paths where a URL is taken from the track dict:
  ```python
  # audio/engine.py:176 (YouTube direct id)
  if direct_id.startswith("http") and not is_safe_media_url(direct_id):
      direct_id = ""
  # audio/engine.py:440 (SoundCloud direct target)
  if sc_target.startswith("http") and not is_safe_media_url(sc_target):
      logger.warning("Rejected unsafe SoundCloud URL in resolve")
      event.set()
  ```
  But the **SoundCloud search fallback** — where the URL comes from *external API data* rather than from the track dict — passes the value straight to the provider with no guard at all:
  ```python
  # audio/engine.py:307-317
  if sc_results:
      target_sc = sc_results[0].get("source_url") or sc_results[0].get("source_id")
      ...
      self.app_core.soundcloud.get_stream_url(target_sc, _sc_done, lambda e: sc_stream_event.set())
  ```
- **Cause:** the guard was added where the input was user-supplied, and not extended to the branch where the input is provider-supplied — the riskier one.
- **Trigger conditions:** a SoundCloud API response whose `source_url` is an internal/loopback URL (compromised or spoofed provider response, or a hijacked API response). The same applies to the Tier-2 YouTube `source_id` (L351), though that one is an id, not a URL.
- **User impact:** **bounded today.** `services/soundcloud_service.py:634-636` does not fetch the supplied URL itself — it forwards it to `https://api-v2.soundcloud.com/resolve?url=<quoted>`, and the URL that comes back is re-validated by the proxy's SSRF guard (`core/proxy.py:841`, `:954`) before the proxy fetches it. So no arbitrary internal fetch was demonstrated. The finding is the missing defence-in-depth at the layer that decides to hand an external URL to a provider.
- **Evidence:** the three snippets above; `utils/url_safety.py:13-37` shows the guard fails closed (DNS failure → `False`).
- **Suggested fix:** apply `is_safe_media_url` to `target_sc` (and to the Tier-2 id when it looks like a URL) exactly as the direct branches do, so the guard is uniform across the cascade.
- **Fix side effects:** the guard does a DNS lookup per call; on a slow or blocked resolver it fails closed and would reject legitimate SoundCloud permalinks. `tests/test_engine_resolve.py:566-600` (`test_soundcloud_fallback_uses_the_first_search_hit`) and `:712-724` would need the guard's DNS behaviour accommodated (they stub the provider, so they may fail closed unless the test injects a resolver).
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

- **`PlaybackQueue` really does have a lock and really does hold it for the whole of every mutating operation** — `audio/queue.py:15` (`self._lock = threading.RLock()`); `set_tracks`, `add_track`, `add_tracks`, `remove_track`, `move_track`, `next_track`, `previous_track`, `jump_to`, `clear`, `get_upcoming`, `toggle_shuffle`, `toggle_repeat` and *both* property setters (`shuffle`, `repeat`) take `self._lock` for the entire body. The queue's own state transitions are atomic. The problems in this report are all in the **composition** of queue operations by callers, not inside the queue's own methods.
- **`get_upcoming` does NOT copy the whole list** — `audio/queue.py:302` is a slice (`self._tracks[start:start+count]`), so it is O(count), not O(n). (It is nevertheless dead code — F-11.)
- **Shuffle preserves the current track in both directions** — the enable branch pins the current track at index 0 (`audio/queue.py:78-80`), the disable branch locates it by `_track_key` and restores its index (`audio/queue.py:97-105`). Measured over a 5000-track on/off round trip: the current track (id 2500) was preserved. Disabling shuffle also restores the original order while keeping tracks added during shuffle (`audio/queue.py:83-105`).
- **`next_track()` at the end of the queue returns `None` without advancing and without pushing a stale index onto the history stack** (`audio/queue.py:224-229`); `remove_track` re-maps the history indices (`audio/queue.py:181-185`); `move_track` and a shuffle toggle clear it (`audio/queue.py:199`, `:71`). `tests/test_media_guard_f3.py:220-284` pins all of this.
- **The `repeat` setter rejects unknown modes** (`audio/queue.py:116-117`), so `toggle_repeat`'s `modes.index(self._repeat)` (`audio/queue.py:273`) cannot raise `ValueError` — pinned by `tests/test_engine_notify.py:290-297`.
- **`_notify_track_changed` does not mutate the queue's track dict** — it copies first (`audio/engine.py:81`), so the proxy URL lands on the emitted copy only; pinned by `tests/test_engine_notify.py:237-248`.
- **The engine's proxy-URL construction percent-encodes the metadata and appends the proxy auth token**, and the raw CDN URL is never exposed to the frontend (`audio/engine.py:89-105`). The local-file route always goes through the proxy — a raw `fs` path is never handed to the browser (`audio/engine.py:107`).
- **Resolution goes through the resolver's cache + single-flight** (`audio/engine.py:136-149`), so two concurrent resolutions of the same track collapse into one network round trip; pinned by `tests/test_engine_resolve.py:370-401`.
- **The fallback cascade has a wall-clock budget** shared by all of its stages (`audio/engine.py:278`), and the budget covers the stream-extraction step too (`audio/engine.py:348-349`, `:366-367`); pinned by `tests/test_engine_resolve.py:795-845`.
- **Every provider wait in the engine is bounded** — `event.wait(timeout=10)` (`:208`), `timeout=15` (`:447`), `timeout=10` (`:482`), `timeout=10` (`:506`), `timeout=3.0` (`:223`). There is no unbounded wait anywhere in `audio/engine.py`.
- **The engine's `source_id` derivation is defensive** — `direct_id = source_id if isinstance(source_id, str) else ""` (`audio/engine.py:175`) prevents the row-id/int case from reaching `len()`/`in`; pinned by `tests/test_engine_resolve.py:1092-1123`.
- **`is_safe_media_url` fails closed** on DNS failure and on an unparsable host (`utils/url_safety.py:13-37`), and it is applied on the engine's two direct-URL paths.
- **The proxy is the right place to gate local files, and it does gate them** — `core/proxy.py:684-692` resolves any local path through `_safe_stream_local_path` (managed app root **or** a referenced tracks row), so the engine's unvalidated `file_path` is not an arbitrary-file-read today.
- **`core/session.py` re-projects the queue before persisting it** (`_slim_track`, `core/session.py:26-37`), so `main.py:565` handing over the queue's live dicts does not leak them into the settings store.

---

### 4. Coverage gaps

- I did **not** run the real app (forbidden by the ground rules), so the two-bridge-calls-at-once scenarios (F-1, F-2, F-3, F-7) are demonstrated with a deterministic in-process harness that interleaves the real `PlaybackQueue` / `AudioEngine` / `AppApi` code, not observed live in the WebView. The harness lives in `%TEMP%` and imports the real modules; the interleaving points are the exact ones the production code exposes.
- The wall-clock duration of the F-9 stall was **not measured** on this machine: that needs a mapped-but-unreachable network path, which I did not create. The blocking call, its thread and its call site are confirmed statically.
- I could **not** prove an escalation from F-13 (unencoded `source` / `track_id`) to an arbitrary fetch. The proxy reads the **first** value of each duplicated parameter (`core/proxy.py:734-739`), the engine puts `url=` first, and the proxy's SSRF guard plus `_safe_stream_local_path` block the obvious paths. Finding the missing evidence would require showing that a crafted `source`/`id` makes `parse_qs` hand the proxy a *different* first value — I did not find such a path.
- I did **not** prove a live SSRF in F-14. `services/soundcloud_service.py:634-636` forwards the value to SoundCloud's own resolve API rather than fetching it, and the proxy re-validates the final URL. What I confirmed is the *inconsistency* of the guard inside the engine.
- The UI was read only far enough to establish the consequences of the backend contracts (`js/queue.js`, `js/player.js`, `js/events.js`, `js/hotkeys.js`, `js/search-discovery.js`, `js/feature-controls.js`, `js/home.js`). The UI player/queue view itself is **WN-29** and was not reviewed.
- `core/api.py` and `main.py` were reviewed only at the call sites listed in §1; the rest of the bridge is **WN-03…WN-10**.
- The `_track_key` collision behaviour of the shuffle-disable branch (two distinct tracks sharing `(source, source_id)`) was analysed but **not** reproduced as a user-visible defect; it is left to Role A rather than reported here.
- `tests/test_player_recovery_transitions.py` was read in full and is **entirely JavaScript** (it drives `js/player.js` in a Node VM harness). It pins nothing about `audio/queue.py` or `audio/engine.py` — it is a WN-29 test, not a WN-17 one.

---

### 5. Architecture improvements (ARCH)

These are improvement proposals **without** a proven defect; they are reported separately from the findings above.

**ARCH-1 — Give the queue one atomic snapshot and let the engine own the "advance + announce" transition.**
`PlaybackQueue` currently exposes state as a set of independent accessors (`tracks`, `current_index`, `current_track`, `shuffle`, `repeat`), so every consumer has to compose the state itself and gets a non-atomic result (F-1, F-7). One `snapshot()` returning the whole state under a single lock acquisition fixes three findings at once. Symmetrically, the "advance the cursor + announce the new track" pair should be one atomic step performed under one lock — either the queue fires a `current_changed(track)` callback from inside its lock, or the engine performs the advance and the announcement under `AudioEngine`'s own lock (which F-8 says it does not have). This also removes the need for `core/api.py` and `main.py` to reach into `queue._current_index` at all.

**ARCH-2 — There are three independent resolution cascades; they have already diverged.**
`audio/engine.py::_resolve_via_network` (L153–508, 355 lines), `core/app.py::re_resolve_stream_url_async` (L296–506, 210 lines) and `core/playback_recovery.py::recover_stream` (L95–183, 89 lines) all implement "ask the provider → fall back to a SoundCloud search → fall back to a YouTube search", each with its own time budget (20 s / 20 s / 18 s) and its own copy of the `clean_noise` query-cleaning regex (`audio/engine.py:237`, `core/app.py:411`). They already differ in an important way: `core/playback_recovery.py:14-37` (`same_recording`) validates that a fallback hit is the *same recording* (title, artist, version, duration), while the engine's cascade accepts the **first** SoundCloud search hit with no match check (`audio/engine.py:307-330`). Because `core/proxy.py:817` resolves through `engine.resolve_stream_url`, the proxy path can serve a different recording than the one the frontend resolved. Extracting one cascade with an optional "must match the request" flag would remove the divergence and shrink ~600 lines.

**ARCH-3 — Introduce an explicit playback state machine instead of inferring "what is playing" from an index.**
`AudioEngine` has no state at all: no idle / resolving / playing / paused / failed. Everything is derived from `queue.current_index` + `queue.current_track`, which is why the engine cannot tell "the queue moved" from "the queue is being replaced", cannot express "resolution failed, the queue is unchanged" (F-12), and cannot represent "the queue is empty but something is playing" (F-5). A small enum on the engine, updated on every transition, would make the failure paths (a `None` from `resolve_stream_url`, a failed `remove_track` of the current track) observable instead of implicit, and would give the bridge one authoritative object to report instead of a bag of indices.

**ARCH-4 — Make the queue the only owner of its track dicts.**
Today the queue's `_lock` protects the list but not the dicts inside it (F-6), and `core/api.py` mutates queue state by writing into a dict it was handed (`core/api.py:1634`, `:1729`). Either the accessors return copies (and those two call sites move to explicit queue mutators) or the queue exposes mutators such as `set_current_stream(path)`. Either way the invariant "only the queue mutates queue state" becomes enforceable.

**ARCH-5 — Publish one queue API on `AudioEngine` and stop letting the bridge touch the queue's internals.**
`core/api.py` reaches into `queue._current_index` (L1776, L1829) and `main.py` does the same (`main.py:566`); `main.py` also calls the engine's private hook `engine._on_track_changed(...)` directly (L325, L392), bypassing `engine._notify_track_changed()` and therefore the engine's proxy-URL construction; `core/api.py` calls `engine._notify_track_changed()` (a private method) from four places (L1597, L1635, L1733). A small façade on `AudioEngine` — `queue_snapshot()`, `play_single(track)`, `advance()`, `set_shuffle(bool)`, `set_repeat(mode)` — would remove all of it and make the queue's public surface (`get_upcoming`, `jump_to`, `update_current`) unnecessary, since the façade is the only intended entry point.

**ARCH-6 — Delete the dead queue API.**
`get_upcoming`, `jump_to`, `update_current` and the `prev_track` alias have no production caller (F-11). The project already applied this policy to `PlaybackQueue` (`tests/test_api_audit_b.py:692-695`), so these four are the remaining exceptions.

**ARCH-7 — Give the resolution cascade one wall-clock budget across all branches, and a much shorter one for prefetch.**
The engine's budget (`audio/engine.py:278`, 20 s) covers only the SoundCloud/YouTube fallback stages of the YouTube branch — the direct extraction above it can still block for 10 s (`audio/engine.py:208`), so the YouTube branch can take ~30 s in total, and the SoundCloud branch up to 25 s (15 s + 10 s). `core/api.py:3640-3683` runs that cascade on a **2-worker** prefetch executor (`core/api.py:369`), and the frontend calls `prefetch_track` on every track change (`ui/web_new_v2/js/player.js:1440-1441`); two slow resolutions therefore stall the whole prefetch pipeline for up to ~30 s. A separate, short budget for the prefetch path (and one budget that covers *all* branches of the cascade) would keep the "instant next track" feature responsive.
