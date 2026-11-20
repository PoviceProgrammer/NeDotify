## WX-10 — Rapid track switching / concurrent transport commands — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py`: 1–120 (imports/helpers), 330–409 (`AppApi.__init__`, lock setup,
  bridge error logging), 1090–1209 (`_emit`, `_enrich_track_lufs`, `_on_track_changed`),
  1210–1309 (`_on_queue_end`, `_on_audio_error`, `_listening_for_track`),
  1330–1409 (`report_listening_state`, `report_state`, `report_position`),
  1400–1849 (`play_track`, `_resolve_track`, `play_pause`, `next_track`, `prev_track`,
  `get_queue`, `reorder_queue`, `play_next`, `add_to_queue`, `add_tracks_to_queue`,
  `remove_from_queue`, `clear_queue`), 1975–2069 (`toggle_mute`, `toggle_shuffle`,
  `toggle_repeat`, `get_next_track`).
- `core/app.py`: 280–419 and 420–529 (`re_resolve_stream_url_async`, worker thread,
  offline handling, YouTube→SoundCloud fallback chain).
- `core/resolver.py`: 1–271 (whole file — `StreamResolver`, `_Flight`, single-flight,
  `_mem`, `_failed`, `invalidate`, `refresh`).
- `audio/engine.py`: 1–508 (whole file — `AudioEngine.play_track/play_queue/next_track/
  prev_track/_notify_track_changed/resolve_stream_url/_resolve_via_network`).
- `audio/queue.py`: 1–302 (whole file — `PlaybackQueue`, all mutators, shuffle setter).
- `core/proxy.py`: 780–919 and 1000–1228 (`do_GET` `/api/stream` + `?url=` branches,
  DB/disk cache lookup, 403/410 self-heal re-resolution, response streaming/caching).
- `ui/web_new_v2/js/player.js`: 1–300, 300–474, 470–799, 840–959, 1380–1629,
  1620–1899, 2105–2144 (`loadAudioSource`, `setupAudioEvents`, the `timeupdate`/`ended`/
  `error`/`pause`/`playing` handlers, `playTrack`, `togglePlayPause`, `onTrackChanged`,
  `stopPlaybackForQueueEnd`, `updateMediaSession`, prefetch/`checkAutomaticTransition`,
  the local `api()` bridge helper).
- `ui/web_new_v2/js/events.js`: 60–199, 270–429 (`track_changed`, `queue_updated`,
  `queue_ended`, `audio_error`, `error`, `track_updated` dispatch).
- `ui/web_new_v2/js/queue.js`: 1–303 (whole file — queue drawer render, drag & drop
  reorder, remove-from-queue, `queue_updated` handling).
- `ui/web_new_v2/js/library.js`: 230–289 ("play all" / playlist "play" buttons).
- `ui/web_new_v2/js/hotkeys.js`: 195–224 (`play_pause` hotkey → local `togglePlayPause`).
- `ui/web_new_v2/js/home.js`: 760–799 (feed-card play → `play_track(trackObj)` with no list).
- `ui/web_new_v2/js/main.js`: 535–574 (secondary `track_changed` consumer).
- `services/youtube_service.py`: 240–309, 894–973 (`_get_ydl` thread-local instances,
  `get_stream_url` per-URL single-flight via `_pending_streams`).
- `AGENTS.md` (repo root) — single-lock rule, `_emit` thread rule.
- `docs/audits/WIN_AUDIT_CONTEXT.md`, `docs/audits/WIN_AUDIT_AREAS.md` (the brief).
- `tests/conftest.py`, `tests/test_api_audit_b.py` (fixtures + existing coverage, read to
  build the repro harness).

**Callees traced into other areas**

- `core/proxy.py` (WN-11) — proxy is *track-scoped*: the proxy URL carries
  `source`/`source_id`, the on-disk cache name is `{source}_{source_id}`, and the
  self-heal re-resolves the same `(source, source_id)`. **No cross-track bleed found.**
- `services/youtube_service.py` (WN-19) — per-thread yt-dlp instances + per-URL
  single-flight; concurrent resolutions of the same video are coalesced.
- `core/resolver.py` (WN-15) — `StreamResolver.resolve()` single-flight; **not on the
  play path** (see F-WX-10-9).
- `core/app.py` (WN-02) — `re_resolve_stream_url_async` thread fan-out.
- pywebview internals (`.venv_win\Lib\site-packages\webview\util.py:303-309`,
  `platforms\edgechromium.py:110-135`) — **every JS bridge call runs on its own
  Python thread**, and `evaluate_js` is a *blocking* `Control.Invoke` to the UI thread.

**Repro harness** (scratch files under `%TEMP%\opencode\audit_repro\`, nothing in the
repo was modified): `wx10_repro.py`, `wx10_repro2.py`, `wx10_repro4.py`,
`wx10_repro5b.py`, `wx10_repro6.py`.

---

### 2. Findings

#### F-WX-10-1  [P1] — Stale resolution wins: `_resolve_track` has no request/generation token, so the *first* resolution to finish plays and the *last* track the user asked for is dropped

- **File:** `core/api.py:1608-1744` (`_resolve_track`), guard at `core/api.py:1734`;
  cross-component with `ui/web_new_v2/js/player.js:1695-1705` (`onTrackChanged` → `play_track(pendingTrack)`)
  and `core/api.py:1746` (`play_pause` sibling) — the request carries **no** correlation id.
- **Confirmed:** yes (executed repro, see below).
- **Description:** `_resolve_track` has no generation counter. It decides whether an
  in-flight resolution is still wanted with two identity checks:
  `_is_current()` (same object, or same `source`+`source_id` as the queue's current
  track) and `queue.current_track is cur_start` (the queue did not change since the
  request started). When **the queue is empty**, `cur_start` is `None` and
  `queue.current_track` is still `None`, so `None is None` is **True** and the stale
  resolution is delivered. Two consequences, both reproduced:
  1. **First-to-resolve wins, not last-requested.** Request A, then request B; A's
     network round trip finishes first → A is played and pushed into the queue, B's
     later resolution is *silently dropped* (no `track_changed`, no error, nothing).
  2. **The requested track is silently lost.** Request A, the user presses next, A's
     resolution lands → `_is_current()` is False and `cur_start` no longer matches →
     the resolution is dropped → the track the user clicked never plays, with no
     feedback at all.
- **Cause:** the guard conflates *"the queue did not change"* with *"the user still
  wants this request"*. With an empty queue `cur_start is None`, so the identity test
  degenerates to `None is None` and always passes. There is no monotonic request
  counter anywhere in `AppApi` (the only counters are `_lyrics_cascade_count` and
  `_search_generation`, both unrelated).
- **Trigger conditions:** any two stream resolutions in flight at the same time with
  an empty or unchanged queue. Reachable from the UI: `search-discovery.js:43`
  (`play_track(track)` with **no** track list), `home.js:784` (same), and the
  player.js resolve path `player.js:1704` (`play_track(pendingTrack)`, no list).
- **User impact:** the user clicks track B, hears track A; or clicks a track and
  nothing happens at all while the old track keeps playing. No error, no toast.
- **Evidence:**

  ```python
  # core/api.py:1714-1737
  cur_start = self._core.engine.queue.current_track          # None when the queue is empty

  def on_resolved(stream_url, metadata=None):
      ...
      if _is_current():
          ...
      elif self._core.engine.queue.current_track is cur_start:   # <-- None is None -> True
          # Selection unchanged since resolution started: safe to deliver
          play_callback(track)
      # else: user moved on - drop stale resolution
  ```

  ```python
  # core/api.py:1623-1629  (the other half of the guard)
  def _is_current():
      cur = self._core.engine.queue.current_track
      if cur is track:
          return True
      if not cur or not source_id:
          return False
      return cur.get("source") == source and cur.get("source_id") == source_id
  ```

  ```js
  // ui/web_new_v2/js/player.js:1695-1705  - the request carries no token
  } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
      isPlaying = false;
      onStateChanged('loading');
      const resolveKey = String(track.source) + '|' + String(track.source_id);
      if (window._pendingResolveKey !== resolveKey) {
          window._pendingResolveKey = resolveKey;
          const pendingTrack = { ...track, file_path: undefined, stream_url: undefined };
          window.pywebview.api.play_track(pendingTrack);      // <-- no generation id
      }
  }
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro.py`
  (stubbed db/settings/proxy + a controllable `re_resolve_stream_url_async`):

  ```
  [older request resolves FIRST] resolve order=[0, 1] -> track_changed=['A'] queue=['A']
  [newer request resolves FIRST] resolve order=[1, 0] -> track_changed=['B'] queue=['B']
  --- state after the race ---
  emitted: [('track_changed', 'A')]
  queue: [('A', 'http://cdn/stream/vA')]
  current: A
  ```
  The last-requested track B never plays when A's resolution lands first; only one
  `track_changed` is ever emitted.
  `%TEMP%\opencode\audit_repro\wx10_repro4.py` case **4c** shows the "silently
  dropped" variant: `-> the SOLO track the user asked for never plays: True`.
- **Suggested fix:** give `AppApi` a monotonic playback-request generation (or a
  per-request token handed to the frontend and echoed back). `_resolve_track` should
  capture the generation at request time and drop the callback unless it is still the
  newest request *for that track*. `None is None` must never be accepted as "the
  selection is unchanged".
- **Fix side effects:** the "solo play" path (`play_track(track)` with no list) must
  still be able to start playback after the queue is empty, so the fix cannot simply
  require a non-empty queue; and the frontend's `window._pendingResolveKey` dedupe
  would have to carry the same token, or a legitimate retry of the same track would
  be suppressed.
- **Discovered by:** A

---

#### F-WX-10-2  [P1] — Concurrent `next_track` calls emit `track_changed` **out of order**: the UI and the `<audio>` element end up on a stale track and one queue entry is skipped

- **File:** `audio/engine.py:55-63` + `audio/engine.py:78-119` (`next_track` /
  `_notify_track_changed`), `core/api.py:1122-1159` (`_emit`),
  `ui/web_new_v2/js/player.js:1625-1709` (`onTrackChanged`),
  `ui/web_new_v2/js/events.js:97-101` (the `track_changed` dispatch).
- **Confirmed:** yes (executed repro).
- **Description:** `_notify_track_changed()` does **not** use the track that
  `queue.next_track()` returned. It re-reads `self.queue.current_track` (the value at
  that instant) and then emits it — after a DB lookup, a Discord-RPC call and a proxy
  URL build, all *outside* the queue lock. pywebview dispatches **every** JS bridge
  call on its own Python thread (`webview/util.py:308`: `thread = Thread(target=_call);
  thread.start()`), so five "next" clicks in two seconds are five concurrent
  `next_track()` calls. `PlaybackQueue.next_track()` itself is atomic (it holds the
  queue RLock), so the *index* is correct — but the *emissions* can be reordered:
  thread 1 reads "B", thread 2 advances to "C" and emits `track_changed(C)` first,
  thread 1 then emits `track_changed(B)`. The frontend applies the last event it
  receives unconditionally (`events.js:97` → `onTrackChanged`), so the UI shows **B**
  and the audio element plays **B**, while the backend queue is at **C**. When B
  ends, `ended` → `next_track()` advances from C to D, so C is never heard.
- **Cause:** the "current track" is sampled under the lock and then emitted later
  without any sequence number, and the emit path (pywebview `Control.Invoke`) gives
  no ordering guarantee between concurrent emitters. There is no version/sequence
  field on the `track_changed` payload and none on the frontend side.
- **Trigger conditions:** two or more transport commands in flight simultaneously —
  exactly the WX-10 scenario ("next" x5 in 2 s, or play/pause + next together).
- **User impact:** the player bar and the audio show a track that is not the queue's
  current one; a queued track is skipped entirely; the "previous" button then jumps
  to the wrong place.
- **Evidence:**

  ```python
  # audio/engine.py:55-63
  def next_track(self):
      track = self.queue.next_track()      # atomic advance
      if track:
          self._notify_track_changed()     # <-- re-reads the current track, not `track`
          return track

  # audio/engine.py:78-80
  def _notify_track_changed(self):
      current = self.queue.current_track   # sampled here ...
      if self._on_track_changed and current:
          track = current.copy()           # ... emitted much later, outside the lock
  ```

  ```python
  # .venv_win/Lib/site-packages/webview/util.py:303-309  (every bridge call = 1 thread)
  func = window._functions.get(func_name) or get_nested_attribute(window._js_api, func_name)
  if func is not None:
      try:
          func_params = param
          thread = Thread(target=_call)
          thread.start()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro2.py`
  case 3 (two threads calling `api.next_track()`, first one's DB lookup slowed):

  ```
  emitted order: [('track_changed', 'T2'), ('track_changed', 'T1')]
  backend queue current_index: 2 current: T2
  last event the UI saw: T1
  ```
  The backend is at T2 while the last event the UI received is T1.
- **Suggested fix:** make the emitted `track_changed` carry a monotonic sequence
  number (or emit the track that was actually advanced to, not a re-read), and have
  the frontend drop events whose sequence is older than the one it already applied.
- **Fix side effects:** the frontend applies `track_changed` in several places
  (`events.js`, `main.js:550`, `queue.js:71`, `lyrics.js`, `utils.js:971`); a
  sequence check must be applied consistently or stale UI parts will persist.
- **Discovered by:** A

---

#### F-WX-10-3  [P1] — `play_pause` is a documented no-op on the backend, but three UI call sites use it as the transport command: the OS media keys and the library "Play all"/"Play" buttons do nothing

- **File:** `core/api.py:1746-1759` (`play_pause`), `ui/web_new_v2/js/player.js:691-692`
  (mediaSession handlers), `ui/web_new_v2/js/library.js:244-245` and
  `ui/web_new_v2/js/library.js:274-275` (library / playlist play buttons).
- **Confirmed:** yes (code trace; the backend method is self-documenting).
- **Description:** `AppApi.play_pause()` only *reports* the last state the frontend
  observed; it deliberately does not touch the `<audio>` element, which lives in the
  WebView. But the frontend wires the OS media-session `play`/`pause` actions and the
  library/playlist "Play all" / "Play" buttons to that bridge method instead of to
  the local `togglePlayPause()` (which the Space hotkey correctly uses,
  `hotkeys.js:202-203`). The bridge call therefore performs **no** transport action at
  all: the audio keeps playing when the user presses the Windows media play/pause
  key, and the library "Play" button appears completely dead when the current track
  already belongs to that list.
- **Cause:** a contract mismatch — the backend API surface advertises a
  `play_pause` transport command, the frontend treats it as one, and the backend
  implements it as a query.
- **Trigger conditions:** pressing the OS media play/pause key (or the overlay
  button), or clicking "Play all"/"Play" in the library or in a playlist while the
  current track is part of that list.
- **User impact:** the media keys and two visible buttons do nothing; the user has to
  use the player bar or the Space hotkey.
- **Evidence:**

  ```python
  # core/api.py:1746-1759
  def play_pause(self) -> str:
      """Report the last playback state the frontend observed.

      The audio element lives in the frontend, so the backend cannot pause or
      resume it - and it must not guess: it receives no argument telling it
      whether the user asked to play or to pause, so any state change here
      would desync the UI. ...
      """
      state = getattr(self, "_last_reported_state", "") or ""
      return state
  ```

  ```js
  // ui/web_new_v2/js/player.js:691-694
  navigator.mediaSession.setActionHandler('play',  () => api('play_pause'));
  navigator.mediaSession.setActionHandler('pause', () => api('play_pause'));
  navigator.mediaSession.setActionHandler('previoustrack', () => api('prev_track'));
  navigator.mediaSession.setActionHandler('nexttrack',     () => api('next_track'));
  ```

  ```js
  // ui/web_new_v2/js/library.js:244-247
  if (isPlayingFromCurrentList && window.pywebview?.api?.play_pause) {
      window.pywebview.api.play_pause();          // no-op: nothing is paused
  } else if (window.pywebview?.api?.play_track) { ... }
  ```
- **Reproduction / verification:** read `core/api.py:1746-1759` (the method returns a
  string and mutates nothing) and the three call sites; the bridge promise resolves
  with the last reported state, which the call sites discard. No transport action is
  possible because the `<audio>` element is not reachable from Python.
- **Suggested fix:** route all three call sites through the local
  `togglePlayPause()` exported by `player.js` (as `hotkeys.js:203` already does), and
  keep `play_pause()` as a pure query — or give the bridge an explicit
  `set_playback_state(state)` command if the backend ever needs to drive playback.
- **Fix side effects:** `library.js` would need to import `togglePlayPause` from
  `player.js` (it already imports `getCurrentTrack` from there), and the
  mediaSession handler must be careful not to fight the `ended` auto-advance.
- **Discovered by:** A

---

#### F-WX-10-4  [P2] — `queue_ended` is not final: an in-flight resolution of the last track restarts playback after the UI was told the queue was exhausted

- **File:** `core/api.py:1716-1737` (`on_resolved`), `core/api.py:1244-1253`
  (`_on_queue_end`), `core/api.py:1761-1765` (`next_track`),
  `ui/web_new_v2/js/events.js:396-403` (`queue_ended` handler),
  `ui/web_new_v2/js/player.js:1829-1853` (`stopPlaybackForQueueEnd`),
  `ui/web_new_v2/js/player.js:1687-1692` (`onTrackChanged` → `playTrack`).
- **Confirmed:** yes (executed repro).
- **Description:** pressing "next" on the last track of the queue makes
  `PlaybackQueue.next_track()` return `None` → `_on_queue_end()` → the `queue_ended`
  event → the frontend releases the audio element and shows "stopped". The current
  track does **not** change, so the resolution that is still in flight for that very
  track still satisfies `_is_current()` → it sets `file_path` and calls
  `_notify_track_changed()` → a second `track_changed` is emitted → the frontend's
  `onTrackChanged` sees `track.stream_url` and `!activeAudio.src` (the element was
  just released) → `playTrack(...)` → **playback restarts on the last track** after
  the app already announced that the queue ended.
- **Cause:** `queue_ended` is a UI-only teardown signal; the backend keeps the current
  track and keeps accepting resolution callbacks for it, and nothing invalidates the
  in-flight request when the queue is declared exhausted.
- **Trigger conditions:** the last track of the queue is still resolving (a very
  common state — the frontend requests the resolution as soon as the track becomes
  current) and the user presses "next" before it lands.
- **User impact:** the player says "stopped"/"queue ended", then a second later the
  last track starts playing on its own. The user's stop is undone; the UI state and
  the audio disagree.
- **Evidence:**

  ```python
  # core/api.py:1716-1737  (the resolution callback does not know about queue_ended)
  def on_resolved(stream_url, metadata=None):
      ...
      if _is_current():                       # the last track is STILL the current one
          cur = self._core.engine.queue.current_track
          cur["file_path"] = stream_url
          ...
          self._core.engine._notify_track_changed()   # -> track_changed -> playback restarts
  ```

  ```js
  // ui/web_new_v2/js/player.js:1687-1692
  } else if (track.stream_url) {
      window._pendingResolveKey = null;
      if (!sameTrack || activeAudio.ended || !activeAudio.src || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
          playTrack(track, track.stream_url);      // activeAudio.src === '' after queue_ended
      }
  }
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro4.py` case 4a:

  ```
  pending: ['v2']
  next_track() at the end -> None
  events: ['track_changed', 'queue_ended']
  after the in-flight resolution lands: [('track_changed','T2'), ('queue_ended',None), ('track_changed','T2')]
  ```
  A `track_changed` is emitted **after** `queue_ended`.
- **Suggested fix:** when the queue is exhausted, invalidate the in-flight
  resolution (same mechanism as F-WX-10-1's generation counter) or mark the track as
  "not to be started"; the frontend should also refuse to auto-start a track whose
  `track_changed` arrives after a `queue_ended` for the same track.
- **Fix side effects:** if the user legitimately wants the last track to finish
  loading, the fix must not suppress the *resolution* — only the automatic restart.
- **Discovered by:** A

---

#### F-WX-10-5  [P2] — `remove_from_queue` is TOCTOU: the "cannot remove the current track" guard is checked outside the lock, so the **currently playing** track can be removed and the current pointer moves silently

- **File:** `core/api.py:1819-1836` (`remove_from_queue`), `audio/queue.py:173-191`
  (`remove_track`), `ui/web_new_v2/js/queue.js:190-220` (the drawer remove button).
- **Confirmed:** yes (executed repro).
- **Description:** `remove_from_queue` reads `queue._current_index` **directly** (an
  unsynchronised read of a field the queue's own RLock is supposed to protect) and
  compares it with the requested index; only afterwards does it call
  `queue.remove_track(index)`, which takes the lock. If a `next_track()` lands in
  that window, the guard passes for an index that has meanwhile become the current
  one. `PlaybackQueue.remove_track` then clamps `_current_index`
  (`self._current_index = min(self._current_index, len(self._tracks) - 1)`), i.e. the
  backend's current track silently becomes a *different* track — and **no
  `track_changed` is emitted**, so the frontend keeps playing the removed track while
  the queue drawer highlights the new one.
- **Cause:** the guard and the mutation are not performed atomically under the queue
  lock; the check reads a private field directly instead of asking the queue.
- **Trigger conditions:** a `remove_from_queue` RPC in flight while a `next_track`
  RPC is processed (both are ordinary bridge calls, each on its own thread).
- **User impact:** the track that is playing disappears from the queue; the player bar
  and the queue drawer disagree about what is playing; "next" now continues from a
  different track.
- **Evidence:**

  ```python
  # core/api.py:1826-1832
  queue = self._core.engine.queue
  if not (0 <= index < len(queue.tracks)):
      return {"success": False, "error": "Неверный индекс очереди"}
  if index == queue._current_index:          # <-- unlocked read of a private field
      return {"success": False, "error": "Cannot remove current track"}
  queue.remove_track(index)                 # <-- the mutation happens later, under the lock
  ```

  ```python
  # audio/queue.py:186-191
  if len(self._tracks) == 0:
      self._current_index = -1
  elif index < self._current_index:
      self._current_index -= 1
  elif index == self._current_index:
      self._current_index = min(self._current_index, len(self._tracks) - 1)   # silently moves
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro6.py`
  (the interleaved `next_track()` is injected between the guard and the removal):

  ```
  remove_from_queue(1) -> {'success': True}
  queue          : ['A', 'C']
  current_index  : 1
  current track  : C
  events emitted : [('queue_updated', None)]
  -> the track the frontend is playing (B) is no longer in the queue: True
  -> no track_changed was emitted, so the UI still shows B: True
  ```
- **Suggested fix:** perform the "is it the current track?" test and the removal in
  one queue-locked operation (e.g. `queue.remove_track(index)` returning a refusal
  code when `index == _current_index`), and emit `track_changed` whenever the current
  pointer moves as a side effect of a removal.
- **Fix side effects:** the frontend also pre-checks `index === currentIndex` with a
  possibly stale snapshot (`queue.js:194`), so the backend must remain authoritative.
- **Discovered by:** A

---

#### F-WX-10-6  [P2] — The `ended` auto-advance is not interlocked with a user-initiated skip: the queue advances twice and one track is skipped

- **File:** `ui/web_new_v2/js/player.js:627-658` (`ended` handler),
  `ui/web_new_v2/js/player.js:934` (`btnNext` click), `ui/web_new_v2/js/player.js:971`
  (player-page next), `core/api.py:1761-1765` (`next_track`).
- **Confirmed:** yes (code trace; the absence of the interlock is a fact, the window
  is the browser event-loop / bridge latency).
- **Description:** when a track ends, the `ended` handler unconditionally issues
  `window.pywebview.api.next_track()` (the only escape is `automaticTransition`, i.e.
  the crossfade path). The "next" buttons issue `api('next_track')` with no
  interlock, no in-flight flag and no "the user already skipped" marker. If the user
  clicks "next" in the same instant the track ends (a very common reflex: the song
  ends, the user hits next), **two** `next_track` RPCs reach the backend and the
  queue advances by two — the track in between is never heard, and the user does not
  understand why.
- **Cause:** the auto-advance and the manual skip are two independent requests with
  no shared token; the frontend has `playbackGeneration`, but it is only consulted
  for the flow-autoplay fallback (`endedGeneration === playbackGeneration`,
  `player.js:654`) and for the recovery path — not to suppress a duplicate advance.
- **Trigger conditions:** a user click on "next" within the window between the
  `ended` event and the backend processing the auto-advance RPC (a few ms).
- **User impact:** a track is skipped; the queue position no longer matches what the
  user did.
- **Evidence:**

  ```js
  // ui/web_new_v2/js/player.js:643-653
  let advanced = false;
  if (window.pywebview?.api?.next_track) {
      try {
          const nextRes = await window.pywebview.api.next_track();   // unconditional
          if (nextRes) advanced = true;
      } catch(e) { console.error('next_track on ended failed:', e); }
  } else { api('next_track'); }

  // ui/web_new_v2/js/player.js:934  - no interlock with the handler above
  if (btnNext) btnNext.addEventListener('click', () => api('next_track'));
  ```
- **Reproduction / verification:** static trace of the two call sites; the backend
  `next_track` (`core/api.py:1761-1765`) has no de-duplication, and
  `PlaybackQueue.next_track` advances unconditionally (`audio/queue.py:244-248`).
  Reproducible by pressing "next" exactly as a track ends.
- **Suggested fix:** latch a "skip in progress" flag (or bump `playbackGeneration`)
  when the user skips manually, and have the `ended` handler skip its own
  `next_track()` when the generation has moved since the track started.
- **Fix side effects:** the `ended` handler also drives the flow-autoplay fallback
  (`player.js:654`), so the suppression must not disable that path when the skip was
  *not* user-initiated.
- **Discovered by:** A

---

#### F-WX-10-7  [P2] — A late solo resolution replaces the whole loaded queue with one track (`engine.play_track` → `set_tracks([track])`)

- **File:** `core/api.py:1631-1637` (`_deliver`/`play_callback`),
  `core/api.py:1734-1736` (`on_resolved` → `play_callback`),
  `audio/engine.py:35-39` (`play_track` → `queue.set_tracks([track], 0)`),
  `ui/web_new_v2/js/search-discovery.js:43` and `ui/web_new_v2/js/home.js:784`
  (`play_track(track)` with **no** track list).
- **Confirmed:** yes (executed repro).
- **Description:** when the frontend asks for a single track without a list
  (`search-discovery.js:43`, `home.js:784`), `play_track` takes the
  `else` branch and calls `_resolve_track(track, lambda t: engine.play_track(t))`.
  If the resolution lands while the queue has not changed since the request, the
  `cur_start` guard passes and `play_callback` runs `engine.play_track(track)` —
  which does `queue.set_tracks([track], start_index=0)`, i.e. it **replaces the entire
  playlist with that one track**. The user's 20-track queue is destroyed; "next"
  then has nowhere to go.
- **Cause:** `AudioEngine.play_track()` is a *queue-replacing* operation, but it is
  used as the "start playing this resolved track" callback of `_resolve_track`,
  where the intent is only "make this track audible".
- **Trigger conditions:** a solo play request (no track list) whose resolution
  completes while the queue is unchanged — e.g. clicking an item in the home
  "discovery" rail while a playlist is loaded.
- **User impact:** the whole queue is silently replaced by one track; the playlist
  is gone from the queue drawer.
- **Evidence:**

  ```python
  # core/api.py:1734-1736
  elif self._core.engine.queue.current_track is cur_start:
      # Selection unchanged since resolution started: safe to deliver
      play_callback(track)
  ```

  ```python
  # audio/engine.py:35-39
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)   # <-- replaces the whole queue
      self._notify_track_changed()
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro4.py` case 4b:

  ```
  queue after the resolution landed: ['SOLO']
  emitted: [('track_changed', 'T0'), ('track_changed', 'SOLO')]
  ```
  A 5-track queue was reduced to `['SOLO']`.
- **Suggested fix:** the callback used by `_resolve_track` should *not* call
  `AudioEngine.play_track` (queue-replacing); it should set the current track's
  `file_path` and notify, the way `on_queue_resolved` already does
  (`core/api.py:1590-1597`).
- **Fix side effects:** the genuine "play this solo track from scratch" case (empty
  queue, no list) still needs to install the track in the queue — so the callback
  must distinguish "the queue was empty" from "the queue has content".
- **Discovered by:** A

---

#### F-WX-10-8  [P3] — `reorder_queue` does not update `PlaybackQueue._original_order`, so a manual drag is silently discarded when shuffle is switched off; the same call also wipes the "previous" history

- **File:** `core/api.py:1782-1785` (`reorder_queue`), `audio/queue.py:193-213`
  (`move_track`), `audio/queue.py:68-106` (the shuffle setter),
  `ui/web_new_v2/js/queue.js:261-293` (the drag & drop handler).
- **Confirmed:** yes (executed repro).
- **Description:** `PlaybackQueue` keeps two orders: `_tracks` (the live order) and
  `_original_order` (the pre-shuffle order). `add_track`, `add_tracks` and
  `remove_track` all maintain `_original_order`; `move_track` does not. So a drag
  performed while shuffle is on is lost as soon as the user switches shuffle off —
  the queue snaps back to the pre-drag order. `move_track` additionally clears
  `_history_stack`, so the "previous track" button can no longer return to the track
  that was playing before the drag.
- **Cause:** `move_track` updates only `_tracks`; the `_original_order` mirror (used
  by the shuffle-off restore path) is left stale. The history reset is intentional in
  `move_track` but is not compensated anywhere.
- **Trigger conditions:** the user drags a queue row while shuffle is enabled, then
  disables shuffle; or drags a row while a track is playing and then presses
  "previous".
- **User impact:** the manual ordering disappears; "previous" jumps to an arbitrary
  earlier track instead of the one that was playing.
- **Evidence:**

  ```python
  # audio/queue.py:193-213
  def move_track(self, old_index: int, new_index: int):
      with self._lock:
          if 0 <= old_index < len(self._tracks) and 0 <= new_index < len(self._tracks):
              if old_index == new_index:
                  return
              self._history_stack.clear()
              track = self._tracks.pop(old_index)
              self._tracks.insert(new_index, track)
              # ... _original_order is never touched
  ```

  ```python
  # audio/queue.py:88-96  (the restore path that reads the stale mirror)
  current_keys = {self._track_key(t) for t in self._tracks}
  restored = [t for t in self._original_order if self._track_key(t) in current_keys]
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_repro\wx10_repro5b.py`
  case 5b:

  ```
  shuffled      : ['A', 'B', 'D', 'C']
  original_order: ['A', 'B', 'C', 'D']
  after reorder : ['B', 'D', 'C', 'A']
  shuffle off   : ['A', 'B', 'C', 'D']  <-- manual reorder lost
  ```
- **Suggested fix:** apply the same move to `_original_order` inside `move_track`
  (mirroring `remove_track`'s key-based maintenance), and decide explicitly whether a
  reorder should clear the back-history.
- **Fix side effects:** `_original_order` is keyed by `_track_key` (source/source_id),
  so duplicates of the same song cannot be distinguished — the mirror update must
  handle duplicate keys or the restore path must become index-based.
- **Discovered by:** A

---

#### F-WX-10-9  [P3] — The resolver's single-flight wait timeout (12 s) is shorter than the engine's own cascade budget (20 s), so a concurrent waiter can 404 while the owner later succeeds

- **File:** `core/resolver.py:22` (`_RESOLVE_TIMEOUT = 12.0`) and
  `core/resolver.py:223-224` (`flight.event.wait(timeout=self._resolve_timeout)`),
  vs `audio/engine.py:278` (`cascade_deadline = time.monotonic() + 20.0`),
  `core/proxy.py:817` / `core/proxy.py:899` / `core/proxy.py:925`
  (`engine.resolve_stream_url(...)` → `resolver.resolve(...)`), `core/proxy.py:1052`
  (`resolve_event.wait(timeout=7)`).
- **Confirmed:** yes (constant mismatch, read from source).
- **Description:** `StreamResolver.resolve()` coalesces concurrent requests for the
  same `(source, source_id)`; the non-owner waits at most `_RESOLVE_TIMEOUT` = 12 s
  and then returns `None` ("no stream") even though the owner is still inside the
  resolution cascade, which `audio/engine.py` budgets at **20 s**. The proxy calls
  `engine.resolve_stream_url()` synchronously on the request thread, so the waiter
  path is the proxy's: the waiter gets `None` → the proxy answers `404 Stream not
  found` → the frontend's `error` handler fires `handleStreamError` → a recovery
  attempt for a track that was about to resolve. (The proxy's own self-heal path has
  the same shape with a 7 s budget at `core/proxy.py:1052`.)
- **Cause:** the wait budget is defined in one module and the cascade budget in
  another, and neither is derived from the other.
- **Trigger conditions:** two concurrent stream requests for the same track where the
  resolution takes between 12 s and 20 s (a slow provider, a bot-challenge
  fallback, a cold network).
- **User impact:** a spurious "cannot play" error and an unnecessary
  renew/recovery cycle for a track that does resolve.
- **Evidence:**

  ```python
  # core/resolver.py:20-22
  _MEM_TTL = 3600.0
  _MEM_MAX_SIZE = 1024
  _RESOLVE_TIMEOUT = 12.0  # max wait for a single-flight resolution
  ```

  ```python
  # core/resolver.py:223-224
  else:
      flight.event.wait(timeout=self._resolve_timeout)
  ```

  ```python
  # audio/engine.py:278
  cascade_deadline = time.monotonic() + 20.0
  ```
- **Reproduction / verification:** compare the two constants; the wait timeout is
  strictly smaller than the maximum lifetime of the flight it is waiting for. A
  deterministic test needs a stubbed cascade that sleeps > 12 s (the network marker
  is deselected by `pytest.ini`, so this must be a stub).
- **Suggested fix:** derive the single-flight wait budget from the cascade budget
  (or make the cascade deadline a parameter of the resolver), so a waiter never
  gives up before the owner can finish.
- **Fix side effects:** a longer wait holds the proxy request thread open longer;
  the proxy's socket timeout must stay above the new budget.
- **Discovered by:** A (owning area for the fix: **WN-15** / `core/resolver.py`)

---

#### F-WX-10-10  [P3] — `get_queue()` reads `queue._current_index` outside the queue lock, so the emitted snapshot can mix an old `tracks[]` with a new `current_index`

- **File:** `core/api.py:1772-1780` (`get_queue`).
- **Confirmed:** hypothesis — the unsynchronised read is a fact, but I could not
  produce an observable inconsistent snapshot (see the note below).
- **Description:** `get_queue()` builds the payload from four independent reads.
  `queue.tracks`, `queue.current_track`, `queue.shuffle` and `queue.repeat` are
  properties that take the queue RLock; `queue._current_index` is a **direct read
  of the private field** with no lock. Between the `tracks` snapshot and the
  `_current_index` read another thread can replace the queue (`set_tracks`), so the
  payload can describe a queue that never existed — e.g. `tracks` from the old list
  with a `current_index` from the new one. The frontend then highlights the wrong
  row (`queue.js:146`, `index === currentIndex`) and its remove-button guard
  (`queue.js:194`) no longer matches the backend's current track, so the user can
  click "remove" on the row the backend considers current and gets the
  "Cannot remove current track" error back.
- **Cause:** one unlocked read among four locked ones in the same snapshot.
- **Trigger conditions:** a queue replacement (`play_queue`/`set_tracks`) concurrent
  with a `get_queue()` call — i.e. any track switch while the drawer is open.
- **User impact:** a transiently wrong "now playing" highlight in the queue drawer
  and a confusing rejection toast.
- **Evidence:**

  ```python
  # core/api.py:1772-1780
  def get_queue(self):
      """Return current queue state."""
      return {
          "tracks": self._core.engine.queue.tracks,          # locked property
          "current_index": self._core.engine.queue._current_index,   # <-- unlocked private read
          "current_track": self._core.engine.queue.current_track,   # locked property
          "shuffle": self._core.engine.queue.shuffle,               # locked property
          "repeat": self._core.engine.queue.repeat,                 # locked property
      }
  ```
- **Reproduction / verification:** **not confirmed.** My harness
  (`%TEMP%\opencode\audit_repro\wx10_repro5b.py` case 5c) looped `set_tracks` of a
  3-track and a 10-track list against a concurrent `get_queue()` reader and produced
  0 snapshots with `current_index >= len(tracks)` — the GIL makes the window between
  the two reads very narrow. Missing evidence: an instrumented run that widens the
  window (e.g. a `time.sleep` injected between the two reads) or a debug build of
  the queue that records the read order. The *code* defect is certain; only its
  observability is unproven.
- **Suggested fix:** expose `current_index` as a locked property on `PlaybackQueue`
  (it already has one at `audio/queue.py:37-40`) and build the whole snapshot under
  a single queue-locked call.
- **Fix side effects:** `get_queue` is called on every queue change and by the
  drawer; adding a queue-locked snapshot method means adding one to
  `PlaybackQueue` (WN-17).
- **Discovered by:** A (owning area for the fix: **WN-05** / `core/api.py`)

---

#### F-WX-10-11  [P3] — `navigator.mediaSession.playbackState` is never set to `"playing"`: the Windows media overlay always reports the app as paused

- **File:** `ui/web_new_v2/js/player.js:681-696` (`updateMediaSession`),
  `ui/web_new_v2/js/player.js:1684-1686` (the only assignment).
- **Confirmed:** yes (single grep over `ui/web_new_v2/**` for `playbackState`
  returns exactly one hit, at line 1685, and it assigns `"paused"`).
- **Description:** `updateMediaSession()` sets the metadata and the action handlers
  but never the playback state. The only `playbackState` assignment in the whole UI
  is `navigator.mediaSession.playbackState = 'paused'` in the initial-load branch.
  The OS media session therefore keeps showing "paused" (and the global media keys
  are disabled by the OS in that state) even while audio is playing.
- **Cause:** the state is never synchronised with `onStateChanged`.
- **Trigger conditions:** always, as soon as a track is playing.
- **User impact:** the Windows media overlay / global media keys show the wrong
  state; combined with F-WX-10-3 the media keys do nothing anyway.
- **Evidence:**

  ```js
  // ui/web_new_v2/js/player.js:681-696
  export function updateMediaSession(track) {
      if ('mediaSession' in navigator) {
          navigator.mediaSession.metadata = new MediaMetadata({...});
          navigator.mediaSession.setActionHandler('play',  () => api('play_pause'));
          ...
      }
  }
  ```

  ```js
  // ui/web_new_v2/js/player.js:1684-1686  - the ONLY playbackState assignment
  if ('mediaSession' in navigator) {
      navigator.mediaSession.playbackState = 'paused';
  }
  ```
- **Reproduction / verification:** `grep -n "playbackState" ui/web_new_v2/**` → one
  hit, `player.js:1685`.
- **Suggested fix:** set `navigator.mediaSession.playbackState` from
  `onStateChanged(state)` (`'playing'` / `'paused'` / `'none'`).
- **Fix side effects:** none; it is a pure UI-state mirror.
- **Discovered by:** A (single-file defect — owning area: **WN-29** / `js/player.js`)

---

### 3. Clean areas

Checked and found correct (brief):

- **Listener lifecycle on the `<audio>` elements — NO accumulation, NO double-advance
  from duplicated listeners.** `setupAudioEvents(audio)` (`player.js:527-672`) is
  called exactly twice, once per element, at module load (`player.js:678-679`).
  There is no per-`play_track` listener registration anywhere; `playTrack()`
  (`player.js:698-...`) never calls `addEventListener`. The `timeupdate`, `ended`,
  `error`, `pause`, `playing`, `seeking`/`seeked`, `loadedmetadata`, `loadstart`,
  `stalled`, `waiting`, `canplay` and `progress` handlers are therefore singletons —
  the hypothesis in the brief ("each play_track adds another listener") does **not**
  hold for this codebase. The dual-element design (`audioA`/`audioB`, `player.js:82-86`)
  is what provides the "old element" isolation, and every handler correctly re-checks
  `audio === activeAudio` before acting.
- **The queue's own lock discipline (inside `PlaybackQueue`).** All mutators
  (`set_tracks`, `add_track`, `add_tracks`, `remove_track`, `move_track`,
  `next_track`, `previous_track`, `jump_to`, `clear`, `toggle_shuffle`,
  `toggle_repeat`, the `shuffle`/`repeat` setters) hold the single `threading.RLock`
  (`audio/queue.py:15`). `current_track`, `current_index`, `tracks`, `count`,
  `shuffle`, `repeat` are all locked properties. The single-lock rule of `AGENTS.md`
  is respected *inside* the class. (`AppApi` bypasses it in `get_queue` and
  `remove_from_queue` — F-WX-10-5 / F-WX-10-10.)
- **`PlaybackQueue.next_track()` / `previous_track()` semantics** — the history stack
  is not polluted when the queue ends (`audio/queue.py:224-229`), `repeat == "one"`
  returns the current track, `repeat == "all"` wraps while keeping the current track
  first, and `previous_track()` pops the history stack under the lock. No
  inconsistency between the current index and the current track inside the class.
- **`move_track`'s index arithmetic** — the `old_index`/`new_index` →
  `_current_index` adjustment (`audio/queue.py:201-213`) was checked for all six
  orderings (before/after/equal × moving-current/not) and is correct.
- **The frontend's *prefetch* path does have proper tokens.** `checkPlaybackLookahead`
  captures `currentQueueVersion` and `playbackGeneration` before `get_next_track()`
  and re-checks both in the `.then()` (`player.js:1432-1436`); the crossfade gate
  re-checks `preparedNext.queueVersion === currentQueueVersion`
  (`player.js:1476-1478`, `player.js:635`). A queue drag invalidates the prefetch
  because `queue_updated` → `incrementQueueVersion()` → `preparedNext = null`
  (`queue.js:62`, `player.js:58-62`). **No stale preloaded track can be adopted.**
- **The gapless/crossfade advance ordering is correct.** `checkAutomaticTransition`
  advances the *backend* first (`player.js:1484`) and the `ended` gapless branch
  (`player.js:635-641`) plays the prepared track that the backend is about to select
  — the backend index and the audio element stay in agreement, and the `ended`
  handler's `automaticTransition` guard prevents a second advance.
- **`playbackGeneration` correctly invalidates the stream-recovery path**
  (`player.js:464-489`): a recovery result that arrives after the user switched
  tracks is discarded (`generation !== playbackGeneration || recoveryRequest !== request`).
- **The proxy is track-scoped — no cross-track bleed.** The proxy URL carries
  `source`/`source_id`/`track_id`; the on-disk cache name is `{source}_{source_id}`
  (`proxy.py:804-805`); the 403/410 self-heal re-resolves the *same*
  `(source, source_id)` (`proxy.py:1027-1051`); the SSRF guard is applied to the
  re-resolved URL (`proxy.py:1054-1056`). Concurrent switches therefore cannot make
  the proxy serve the wrong track.
- **Provider-level concurrency is deliberate.** `YoutubeService._get_ydl()` returns
  a **thread-local** `YoutubeDL` instance (`youtube_service.py:253-275`), and
  `get_stream_url()` coalesces concurrent requests for the same video through
  `_pending_streams` (`youtube_service.py:912-933`). Five concurrent resolutions of
  five different tracks therefore use five independent yt-dlp instances and do not
  corrupt each other.
- **`StreamResolver`'s single-flight bookkeeping is leak-free.** The flight is removed
  from `_inflight` in a `finally` block, guarded by an identity check
  (`resolver.py:218-222`), and `flight.event.set()` follows immediately — a failed or
  cancelled flight never blocks a later resolve of that key. Five concurrent
  resolutions of five *different* tracks produce five independent flights
  (the key is `(source, str(source_id))`, `resolver.py:61-62`), each resolved once.
  The `_failed` verdict map is only written by the explicit `mark_unavailable()`
  (`resolver.py:101-117`), never by a plain failure, so it cannot permanently block a
  track. (The 12 s vs 20 s budget mismatch is F-WX-10-9.)
- **`_emit` never runs on the UI thread** — the `threading.current_thread() is
  _MAIN_THREAD` branch (`core/api.py:1147-1154`) is intact, and pywebview's
  `evaluate_js` is a blocking `Control.Invoke` (`edgechromium.py:126-130`), so the
  emit path never deadlocks the window. (The *ordering* of concurrent emits is a
  separate problem — F-WX-10-2.)
- **The listening telemetry is session-guarded.** `report_position` /
  `report_state` / `report_listening_state` reject a stale `listening_session`
  (`core/api.py:1409-1410`, `1359-1360`, `1338-1339`), so a late `timeupdate` from a
  previous track cannot pollute the new track's listening session.
- **The frontend's `_pendingResolveKey` correctly de-duplicates identical resolve
  requests** (`player.js:1700-1705`) — the same track is not resolved twice while a
  request for it is pending. (It is *not* a cross-request token — F-WX-10-1.)

---

### 4. Coverage gaps

- **No browser runtime.** The WebView2 behaviour (event ordering, `ended`
  delivery, `mediaSession`, `AbortController` behaviour on `src` changes) could not
  be exercised; the frontend findings are derived from the source and from the
  documented pywebview/Chromium semantics. In particular the *exact* width of the
  double-advance window in F-WX-10-6 could not be measured.
- **The 5-clicks-in-2-seconds case was not reproduced against a real provider.** The
  repro harness stubs `re_resolve_stream_url_async` so that the completion order can
  be controlled; with a real provider the 5 cascades interleave with network
  latency, yt-dlp bot-challenge fallbacks and the 20 s cascade deadline, which will
  make the "first-to-resolve wins" behaviour of F-WX-10-1 far more visible (a slow
  track A and a fast track B in the same queue).
- **`core/proxy.py` was read only along the `/api/stream` and `?url=` paths**
  (lines 780-1228). The HLS rewrite path, the Range/`serve_local_file` path and the
  proxy's own cache-eviction logic were not audited for this scenario (they belong
  to WX-01/WX-11).
- **`services/soundcloud_service.py` / `yandex_service.py` / `vk_service.py` were not
  read.** Only `youtube_service.py` was checked for concurrency (thread-local yt-dlp
  + per-URL single-flight). If SoundCloud/Yandex lack an equivalent
  `_pending_streams` coalescing, five rapid switches could trigger five parallel
  cascades per provider — a performance question (Role B) that I could not confirm
  here.
- **The DB-backed stream cache under concurrency** (`core/database.py`
  `cache_stream`/`get_cached_stream`/`set_cached_file`) was not audited for the
  rapid-switch scenario; the proxy writes `set_cached_file` from several request
  threads (`proxy.py:810`, `proxy.py:1207`).
- **`main.py`'s session restore path** (`main.py:324`, `main.py:392` — which calls
  `engine._on_track_changed` directly) intersects with the startup ordering of the
  first `play_track`, but session restore belongs to WX-07/WX-12 and was not
  analysed here.
- **The offline-mode variants** of `play_track` / `_resolve_track`
  (`core/api.py:1439-1448`, `core/app.py:298-304`) were read but not exercised;
  WX-09 owns offline mode.
