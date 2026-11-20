## AREA WX-10 — Rapid track switching / concurrent transport commands → queue + engine + proxy state consistency — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `core/api.py`: 1–100, 330–449, 1090–1269, 1267–1401, 1400–1859, 2010–2079, 3815–3839
- `core/app.py`: 290–409, 409–518 (plus grep over the whole file)
- `core/resolver.py`: 1–271 (whole file)
- `core/proxy.py`: 421–540, 800–844, 960–1109, 1259–1334
- `audio/engine.py`: 1–508 (whole file)
- `audio/queue.py`: 1–302 (whole file)
- `services/base_service.py`: 55–204
- `services/youtube_service.py`: 350–479, 894–993, 1040–1079
- `ui/web_new_v2/js/player.js`: 1–200, 430–759, 759–1088, 1600–1839, 2105–2144
- `ui/web_new_v2/js/events.js`: 40–169, 280–329
- `ui/web_new_v2/js/queue.js`: 55–184, 255–303
- `ui/web_new_v2/js/main.js`: 520–599
- `main.py`: 548–577
- `tests/conftest.py`: 1–176; `tests/test_api_audit_b.py`: 1–120, 295–459; `tests/test_queue.py`: 1–109;
  `tests/test_engine_notify.py`: 1–120; `tests/test_engine_resolve.py` (grep of all test names);
  `tests/test_player_recovery_transitions.py`: 1–246; `tests/test_playback_latency_ui.py` (grep);
  `tests/test_resolver_state.py`: 130–209
- `tools/check_lock_nesting.py`: 1–127 (executed)
- `.venv_win/Lib/site-packages/webview/util.py`: 225–324; `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py`: 105–154
  (the pywebview bridge threading model — read to establish the concurrency contract)

**Callees traced into other areas**

- `core/resolver.py::StreamResolver` (WN-15) — traced; see F-WX-10-4 (not on the playback path)
- `core/app.py::AppCore.re_resolve_stream_url_async` (WN-02) — traced; the actual resolution entry point
- `core/proxy.py` (WN-11) — traced: `engine.resolve_stream_url` is the *only* consumer of `StreamResolver.resolve()`
- `services/base_service.py::_SharedExecutor` / `_cache_lock` (WN-18) — traced; the shared 8-worker provider pool
- `services/youtube_service.py::get_stream_url` (WN-19) — traced; the `_pending_streams` dedupe
- `services/lyrics_*`, `core/listening.py` (WN-04/22) — read only where they share `_window_op_lock` with the transport path
- `core/database.py::get_cached_stream` (WN-12) — read the signature only (WN-12 owns it)

**Concurrency contract established from the framework (not from the repo)**

`webview/util.py:303-312` — every JS→Python call is served on a **fresh thread**:

```python
    func = window._functions.get(func_name) or get_nested_attribute(window._js_api, func_name)
    if func is not None:
        try:
            func_params = param
            thread = Thread(target=_call)
            thread.start()
```

`webview/platforms/edgechromium.py:126` — Python→JS is a `Control.Invoke` marshal onto the UI thread:

```python
            self.webview.Invoke(Func[Object](lambda: self.webview.ExecuteScriptAsync(script).ContinueWith(
```

**Consequence:** `AppApi` methods are *not* serialised by the bridge. Two `play_track` / `next_track` /
`reorder_queue` calls can be inside Python at the same time, in an order the caller did not intend.

---

### 2. Findings

#### F-WX-10-1  [P1] — Transport commands are not serialised: every bridge call gets its own thread and `AppApi` has no playback lock

- **File:** `core/api.py:1437-1606` (`play_track`), `core/api.py:1761-1770` (`next_track`/`prev_track`), `core/api.py:1782-1785` (`reorder_queue`), `core/api.py:1797-1836` (`add_to_queue`/`remove_from_queue`); `core/api.py:353` (the only lock on the class); `audio/queue.py:15`; `audio/engine.py:27-33`
- **Confirmed:** yes
- **Description:** `AppApi` has exactly four locks: `_ssrf_cache_lock` (module-level, `core/api.py:102`), `_window_op_lock` (`core/api.py:353`), `_lyrics_lock` (`:359`), `_search_lock` (`:364`). `_window_op_lock` guards **window geometry** and **listening telemetry** — it is *not* taken around any queue or transport mutation. `AudioEngine` (`audio/engine.py:27-33`) has **no lock at all**; it relies entirely on `PlaybackQueue._lock`. `PlaybackQueue._lock` makes each *individual* queue mutation atomic, but the compound operation *mutate queue → notify → emit* is not. Because pywebview serves each call on a new thread, two transport commands genuinely overlap.
- **Cause:** the transport path was written as if the bridge serialised it. The lock discipline was designed for window ops and was never extended to playback; `PlaybackQueue` protects its data but not the state machine built on top of it.
- **Trigger conditions:** any two transport commands in flight at once — the user clicking "next" twice, a media-key next arriving while a click is resolving, the tray "next" during a track change, `reorder_queue` racing a `next_track`.
- **User impact:** the queue advances more steps than the UI does; the value the bridge returns and the track the event announces can be different tracks (see F-WX-10-2 for the same defect on the resolution path).
- **Evidence:**

  `core/api.py:1761-1770` — no lock at all around the transport command:

  ```python
  def next_track(self):
      """Play next track in queue. Returns the next track or None at queue end."""
      if hasattr(self._core.engine, 'next_track'):
          return self._core.engine.next_track()
      return None

  def prev_track(self):
      """Play previous track in queue."""
      if hasattr(self._core.engine, 'prev_track'):
          self._core.engine.prev_track()
  ```

  `audio/engine.py:55-63` — the queue is read **twice** inside one command, with a window in between:

  ```python
  def next_track(self):
      """Advance the queue and notify the UI. Returns the new track or None at the end."""
      track = self.queue.next_track()      # <- read #1 (advances _current_index)
      if track:
          self._notify_track_changed()      # <- read #2 (re-reads queue.current_track)
          return track
  ```

  `audio/engine.py:78-79` — read #2 is a *separate* lock acquisition on a *different* value:

  ```python
  def _notify_track_changed(self):
      current = self.queue.current_track
  ```

- **Reproduction / verification:** deterministic repro (`%TEMP%\opencode\audit_reports\wx10_repro.py`, R1). A subclass of `AudioEngine` blocks inside `_notify_track_changed`; a second thread calls `queue.next_track()` in that window:

  ```
  queue.current_track after both calls : T2
  next_track() RETURNED                : T1
  track_changed EMITTED                : ['T2']
  >>> divergence: YES
  ```

  The command returned `T1` while the event announced `T2` — the return value and the emitted event describe two different tracks.
- **Suggested fix:** introduce one playback command lock (`self._playback_lock = threading.RLock()`) in `AppApi` and hold it across *mutate → notify → emit* for every transport command; or better, move the whole transport state machine into one owner (see ARCH-1).
- **Fix side effects:** a lock held across `_emit` must not be held across `evaluate_js` on the UI thread (the AGENTS.md `_emit` rule); `AppApi._emit` already hands UI-thread emits to a worker thread, so the lock must be released before `_emit` or `_emit` must be made non-blocking.
- **Discovered by:** B

---

#### F-WX-10-2  [P1] — A stale resolution callback replaces the whole queue and the user's newer selection

- **File:** `core/api.py:1714` (`cur_start`), `core/api.py:1727-1737` (`on_resolved`), `core/api.py:1606` (`play_callback`), `audio/engine.py:35-39` (`play_track`), `audio/queue.py:119-132` (`set_tracks`); trigger source `ui/web_new_v2/js/player.js:1695-1705`
- **Confirmed:** yes (deterministic repro, see below)
- **Description:** `AppApi._resolve_track` decides whether a finished resolution is still wanted by comparing **the queue's current track object** captured at request time:

  ```python
  cur_start = self._core.engine.queue.current_track          # core/api.py:1714
  ...
  def on_resolved(stream_url, metadata=None):
      ...
      if _is_current():
          cur = self._core.engine.queue.current_track
          cur["file_path"] = stream_url
          ...
          self._core.engine._notify_track_changed()
      elif self._core.engine.queue.current_track is cur_start:
          # Selection unchanged since resolution started: safe to deliver
          play_callback(track)                                  # core/api.py:1736
  ```

  `play_callback` is `lambda t: self._core.engine.play_track(t)` (`core/api.py:1606`), and `AudioEngine.play_track` does:

  ```python
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)            # audio/engine.py:38
      self._notify_track_changed()
  ```

  `set_tracks` **replaces the entire queue with a single track**. So when the "selection unchanged" test is satisfied by a track that is *not* the one the user wants any more, the late callback destroys the queue and re-announces the stale track.
- **Cause:** there is **no playback generation / epoch counter on the backend**. Staleness is inferred from *object identity* of the queue's current track, which is not the same thing as "is this still what the user selected". The frontend has exactly such a counter (`ui/web_new_v2/js/player.js:23` `let playbackGeneration = 0;`) — the backend has none. The comment "Selection unchanged since resolution started" describes the intent, but the code tests "the queue's current track object is unchanged", which is true in exactly the wrong situation.
- **Trigger conditions:** the user clicks track A, then clicks track B **before** the frontend's automatic re-request for A (`player.js:1704`) is processed by the backend. `play_track(B, …)` sets the queue's current to B; the frontend's `play_track(pendingA)` (no queue) then enters `_resolve_track` with `cur_start == B`; when A's resolution lands, `_is_current()` is false (A ≠ B) but `queue.current_track is cur_start` is true → `play_callback(A)` → the queue collapses to `[A]`.
- **User impact:** the user clicks B and hears A. The queue drawer is wiped from N tracks to 1. `track_changed(A)` is emitted, so the UI flips back to A.
- **Evidence:** the guard chain, quoted above; `player.js:1695-1705` is the source of the second (queue-less) resolution:

  ```javascript
  } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
      // Stream not resolved yet: show loading and request background resolution.
      isPlaying = false;
      onStateChanged('loading');
      const resolveKey = String(track.source) + '|' + String(track.source_id);
      if (window._pendingResolveKey !== resolveKey) {
          window._pendingResolveKey = resolveKey;
          const pendingTrack = { ...track, file_path: undefined, stream_url: undefined };
          window.pywebview.api.play_track(pendingTrack);
      }
  }
  ```
- **Reproduction / verification:** deterministic repro (`%TEMP%\opencode\audit_reports\wx10_repro4.py`) — real `AppApi` + real `AudioEngine` + real `PlaybackQueue`, with `re_resolve_stream_url_async` stubbed so the resolution can be released at a chosen moment:

  ```
  after click A  -> queue: ['T0','T1','T2'] current: T0
  after click B  -> queue: ['T0','T1','T2'] current: T1
  -- firing A's stale resolution --
  FINAL queue       : ['T0']
  FINAL current     : T0
  track_changed log : ['T0', 'T1', 'T0']
  >>> the user's selection B was replaced by the stale A: YES
  >>> the whole queue was collapsed to a single track: YES
  ```
- **Suggested fix:** add a monotonic `playback_epoch` to the backend, incremented on every `play_track`/`next_track`/`prev_track`; capture it with the resolution request and drop any callback whose epoch no longer matches. Never call `play_callback` from a resolution callback — the callback may only *update* the already-current entry.
- **Fix side effects:** the epoch must be bumped on the same thread that mutates the queue, otherwise it inherits F-WX-10-1. Epoch-based dropping also means a resolution that lands for a track the user re-selected later is discarded and must be re-requested (one extra round trip, acceptable).
- **Discovered by:** B

---

#### F-WX-10-3  [P2] — `play_track` re-initialises the queue: it re-shuffles it, wipes the back-history, and discards backend-side queue edits

- **File:** `core/api.py:1527, 1539, 1546, 1566, 1580` → `audio/engine.py:41-47` → `audio/queue.py:119-132`; `audio/queue.py:245, 256-263` (history)
- **Confirmed:** yes
- **Description:** every manual selection routes through `AudioEngine.play_queue(track_list, safe_index)` → `PlaybackQueue.set_tracks`, and `set_tracks` (a) replaces `_tracks` wholesale, (b) **clears the back-history**, and (c) **re-shuffles** the whole list when shuffle is on:

  ```python
  def set_tracks(self, tracks: list, start_index: int = 0):
      """Set the queue with a list of tracks."""
      with self._lock:
          self._tracks = tracks.copy()
          self._original_order = tracks.copy()
          self._current_index = max(0, min(start_index, len(tracks) - 1)) if tracks else -1
          self._history_stack.clear()
          if self._shuffle:
              current = self.current_track
              remaining = [t for i, t in enumerate(self._tracks) if i != self._current_index]
              random.shuffle(remaining)
              if current:
                  self._tracks = [current] + remaining
                  self._current_index = 0
  ```
- **Cause:** `play_track` was modelled as "replace the queue" instead of "select an entry in the queue". The queue is therefore a derived copy of whatever snapshot the frontend happened to send, and every queue invariant that `set_tracks` resets is reset on every click.
- **Trigger conditions:** any click on a track while shuffle is on, or after `add_to_queue`/`play_next`/`reorder_queue` whose `queue_updated` event has not yet been processed by the page.
- **User impact:** (a) with shuffle on, the queue order visibly changes on *every* track click — shuffle randomises repeatedly instead of once; (b) the "previous track" button stops working across a manual selection, because `_history_stack` was cleared and `previous_track()` falls back to `max(0, current_index - 1)`; (c) a track added with `add_to_queue`/`play_next` is silently dropped by the next `play_track`, because the backend replaces its queue with the frontend's (possibly stale) snapshot.
- **Evidence:** the code above; plus the fact that the frontend's snapshot is the *source* of the replacement — `ui/web_new_v2/js/queue.js:182`:

  ```javascript
  window.pywebview.api.play_track(track, currentQueue, index);
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\wx10_repro.py`, R2 and R3:

  ```
  queue BEFORE play_queue (with shuffle on): ['T0','T1','T4','T2','T3','EXTRA']
  queue AFTER  play_queue(list, 2)          : ['T2','T4','T3','T1','T0']     <- re-shuffled, EXTRA dropped
  after add_to_queue          : ['T0','T1','T2','ADDED']
  after reorder_queue(0,2)    : ['T1','T2','T0','ADDED']
  after play_queue(snapshot)  : ['T0','T1','T2']                              <- ADDED silently lost
  ```
- **Suggested fix:** split the concepts — a `select(index)` operation that only moves the cursor (and appends the history), and a `replace_queue(tracks)` used only when the queue genuinely changes. Shuffle must be applied once, when the queue is built, not on every selection.
- **Fix side effects:** the frontend's `window.currentQueue` is currently the de-facto queue; making the backend authoritative means the frontend must accept `queue_updated` as the source of truth and stop sending its own snapshot (or the backend must reconcile the snapshot against the live queue).
- **Discovered by:** B

---

#### F-WX-10-4  [P2] — The playback path bypasses `StreamResolver` entirely: no single-flight, no in-memory cache, no "known unavailable" memo

- **File:** `core/api.py:1604` and `core/api.py:1744` → `core/app.py:296-506`; `core/resolver.py:40-230`; `audio/engine.py:121-151`; `core/proxy.py:817, 899, 925`
- **Confirmed:** yes
- **Description:** `StreamResolver` is documented as the coordinator:

  ```python
  """Stream URL Resolution Coordinator (C-3)
  Cache layer in front of the network resolution cascade:
      in-memory dict -> DB stream_cache -> network cascade (single-flight).
  Single-flight: concurrent requests for the same (source, source_id) share one
  background resolution instead of each triggering the full network cascade.
  """
  ```

  But the user-facing playback path never calls it. `AppApi.play_track` and `AppApi._resolve_track` both call `AppCore.re_resolve_stream_url_async`, which goes straight to the provider:

  ```python
  # core/api.py:1604
  self._core.re_resolve_stream_url_async(source, source_id, callback=on_queue_resolved, on_error=on_queue_error, track=target_track)
  ```
  ```python
  # core/app.py:502 (inside the worker thread)
  service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
  ```

  `StreamResolver.resolve()` is reached only from `AudioEngine.resolve_stream_url` (`audio/engine.py:149`), whose only callers are the **proxy** (`core/proxy.py:817, 899, 925`). So the single-flight map, the in-memory TTL cache and the `_failed` ("known unavailable") memo are all dead weight for the path the user actually drives; the resolver is only *written* on the playback path (`core/app.py:354` `self.resolver.refresh(...)`) and *read* by the proxy.
- **Cause:** the resolver was introduced as a cache layer in front of the cascade, but the cascade entry point was left as the older `re_resolve_stream_url_async`. The two paths were never unified.
- **Trigger conditions:** every user-initiated play of a cloud track.
- **User impact:** (a) five rapid clicks = five independent cascades; (b) the `_failed` memo (`core/resolver.py:79-95`, 120 s) never suppresses a repeat cascade for a DRM/dead track on the playback path, so every click on an unplayable track re-runs the full cascade (3 provider searches + 2 stream extractions); (c) `tests/test_resolver_state.py:152 test_single_flight_shares_one_cascade` passes and gives false confidence — it exercises a code path the user never takes.
- **Evidence:** `core/resolver.py:165-230` (`resolve`) vs. `core/api.py:1604`/`1744`; `core/app.py:296-506`; the only callers of `engine.resolve_stream_url` are `core/proxy.py:817/899/925` (grep over the whole repo confirms no other caller).
- **Reproduction / verification:** `grep -rn "resolve_stream_url\|\.resolve(source" --include=*.py` over the repo: the only non-test, non-proxy callers of the resolver are `audio/engine.py:149`. Stub `core.resolver.resolve` and observe it is never invoked by `AppApi.play_track`.
- **Suggested fix:** route `AppApi.play_track` / `_resolve_track` through `StreamResolver.resolve(source, source_id, resolver_fn)` so the single-flight, the mem cache and the "unavailable" memo apply to the user path; keep `re_resolve_stream_url_async` only as the *provider callback* wrapper.
- **Fix side effects:** `StreamResolver.resolve` waits at most `_RESOLVE_TIMEOUT = 12.0` s (`core/resolver.py:22`) and returns `None` on timeout, whereas the current path has no such bound on the callback side — the UI's "loading" state would get a hard deadline (an improvement, but it changes the failure timing). The resolver's `resolver_fn` signature is `(url, error)` and the current callbacks expect `(url, metadata)`, so the metadata plumbing must be adapted.
- **Discovered by:** B

---

#### F-WX-10-5  [P2] — One user click starts two independent resolution chains for the same track

- **File:** `ui/web_new_v2/js/player.js:1695-1705` → `core/api.py:1606` → `core/api.py:1744` → `core/app.py:305-506`
- **Confirmed:** yes
- **Description:** `AppApi.play_track(track, track_list, index)` starts a background resolution and *also* publishes the track to the UI with an **empty `stream_url`** (`audio/engine.py:118` — "stream not resolved yet - leave stream_url empty; frontend shows loading state"). The frontend sees no `stream_url` and calls back into the backend **without the queue**, which starts a *second* resolution for the same `(source, source_id)`:

  ```python
  # core/api.py:1605-1606  (the no-track_list branch)
  else:
      self._resolve_track(track, lambda t: self._core.engine.play_track(t))
  ```
  ```python
  # core/api.py:1744
  self._core.re_resolve_stream_url_async(source, source_id, callback=on_resolved, on_error=on_resolve_error, track=track)
  ```
- **Cause:** the "still resolving" state is expressed by the *absence* of a field, and the frontend interprets absence as "the backend has not started, start it". The backend has no way to say "I already have a resolution in flight for this key".
- **Trigger conditions:** every play of a cloud track that needs a network resolution — i.e. the normal case.
- **User impact:** double the provider work per click (partly absorbed by `youtube_service`'s `_pending_streams` dedupe, `services/youtube_service.py:912-917`), two independent callback chains, two `track_changed` emissions, and — critically — the *second* chain is the one that can trigger F-WX-10-2.
- **Evidence:** the frontend branch quoted in F-WX-10-2; `core/api.py:1604` and `core/api.py:1744` both calling `re_resolve_stream_url_async` for the same key.
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\wx10_repro2.py`, R6:

  ```
  after ONE play_track(track, list):          resolution chains = 1 [('youtube','v1')]
  after the frontend's automatic re-request:  chains = 2 [('youtube','v1'), ('youtube','v1')]
  >>> duplicate resolution for one click: YES
  ```
- **Suggested fix:** publish the in-flight state explicitly (e.g. `track_changed` carries `resolving: true` / a `resolution_id`), or — cheaper and consistent with F-WX-10-4 — let `StreamResolver`'s single-flight absorb the duplicate: the second call joins the first flight instead of starting a new cascade.
- **Fix side effects:** the frontend's `window._pendingResolveKey` guard (`player.js:1701`) currently *suppresses* the re-request for the same key; if the backend stops emitting an empty-`stream_url` track, that guard becomes dead code and must be removed together with the change.
- **Discovered by:** B

---

#### F-WX-10-6  [P2] — Superseded resolutions are never cancelled; each abandoned cascade keeps a thread and a provider worker busy

- **File:** `core/app.py:305-506` (`threading.Thread(target=worker, daemon=True).start()` at `:506`), `core/api.py:1583-1604`, `core/api.py:1716-1744`; pool size `services/base_service.py:124`
- **Confirmed:** yes
- **Description:** `AppCore.re_resolve_stream_url_async` spawns **one unbounded OS thread per request** and never cancels it:

  ```python
          threading.Thread(target=worker, daemon=True).start()
  ```

  The worker calls the provider; the provider calls back whenever it finishes. There is no cancellation token, no epoch check before the expensive work, and no "the user moved on" signal. The `callback` closure in `core/api.py:1583-1604` only *checks* whether the result is still wanted **after** the whole cascade has already been paid for.
- **Cause:** the resolution pipeline has no lifecycle; a resolution is a fire-and-forget promise with no handle to cancel.
- **Trigger conditions:** any rapid switching. Each abandoned resolution keeps its `worker` thread alive plus a slot in the shared provider pool until the provider answers or its own timeout expires.
- **User impact / cost quantification:** measured with the real `AppApi` (`%TEMP%\opencode\audit_reports\wx10_repro2.py`, R7):

  ```
  resolutions started: 5 ['v0','v1','v2','v3','v4']
  resolutions cancelled: 0
  track_changed events: 7
  queue_updated events: 5
  total bridge events for 5 clicks: 12
  ```

  Five clicks → **five** provider cascades, **zero** cancelled, and **twelve** bridge events. The actual extraction runs on `BaseMusicService._executor = _SharedExecutor(max_workers=8)` (`services/base_service.py:124`) — the **same 8-worker pool the search box uses**. Five abandoned yt-dlp extractions therefore occupy 5/8 of the provider pool while the user is still typing in the search field; yt-dlp extraction is the expensive stage (network + CPU), not a cheap lookup.
- **Evidence:** `core/app.py:506`; `services/base_service.py:124`; the measured numbers above.
- **Reproduction / verification:** run `%TEMP%\opencode\audit_reports\wx10_repro2.py` (R7) and `%TEMP%\opencode\audit_reports\wx10_repro.py` (R4); both show 5 started / 0 cancelled for 5 clicks.
- **Suggested fix:** (a) give the resolution a handle (`threading.Event` cancellation token + a backend epoch) and let the worker abort *before* the provider call if the epoch moved; (b) cap the number of in-flight resolutions for the playback path with a small dedicated pool instead of one thread per request; (c) with F-WX-10-4 applied, the resolver's single-flight collapses the duplicates and the epoch check discards the rest.
- **Fix side effects:** cancelling a resolution that the proxy would have benefited from (the proxy's self-heal path, `core/proxy.py:1051`, uses the same entry point) must not break the 403/410 self-heal; the cancellation token has to be scoped to the *playback* path, not to `re_resolve_stream_url_async` in general.
- **Discovered by:** B

---

#### F-WX-10-7  [P2] — `_emit` is thread-per-event with no queue and no ordering guarantee

- **File:** `core/api.py:1122-1159` (the UI-thread branch at `:1147-1154`)
- **Confirmed:** the thread-per-event behaviour is **confirmed**; the out-of-order delivery is a **hypothesis** (see "Reproduction / verification").
- **Description:** the "EmitWorker" in the brief is a *thread name*, not a worker with a queue. On the UI thread `_emit` spawns a **new OS thread per event**:

  ```python
          if threading.current_thread() is _MAIN_THREAD:
              threading.Thread(
                  target=self._window.evaluate_js,
                  args=(js_code,),
                  daemon=True,
                  name="EmitWorker",
              ).start()
              return
  ```

  There is no queue, no single writer and therefore **no ordering guarantee** for events emitted from different threads. Off the UI thread `_emit` calls `evaluate_js` directly, and `evaluate_js` marshals onto the UI thread via `Control.Invoke` (`webview/platforms/edgechromium.py:126`) — two concurrent callers are serviced in an order the OS picks, not the order in which the state changed.
- **Cause:** `_emit` was written to satisfy one rule ("never run `evaluate_js` on the UI thread") and inherited a fire-and-forget shape that has no back-pressure and no ordering.
- **Trigger conditions:** any burst that emits from more than one thread — exactly the rapid-switch case: the transport command thread and the resolution thread both emit.
- **User impact:** the frontend receives the 12 events of a 5-click burst in an arbitrary order. `onTrackChanged` assigns `currentTrack = track` unconditionally (`ui/web_new_v2/js/player.js:1644`), so whichever `track_changed` arrives last wins, regardless of which is actually current. The UI can display track 3 while the backend queue is on track 5.
- **Evidence:** the quoted branch; `ui/web_new_v2/js/player.js:1625-1644`:

  ```javascript
  export function onTrackChanged(track) {
      if (!track) return;
      const sameTrack = trackPlaybackKey(currentTrack) === trackPlaybackKey(track);
      ...
      currentTrack = track;
  ```
- **Reproduction / verification:** the thread-per-event part is confirmed by `%TEMP%\opencode\audit_reports\wx10_repro3.py`: 50 `_emit` calls from the main thread with a stubbed `evaluate_js` produced a **peak of 44 concurrent OS threads**. The *ordering* claim needs a live WebView2 to confirm: two `_emit` calls from two threads, each `evaluate_js` blocking until the UI thread runs it, and the order in which the page's `window.onPythonEvent` fires recorded in the page. **Missing evidence:** the live WebView2 ordering; the mechanism (`Control.Invoke` from N threads) is confirmed by reading `webview/platforms/edgechromium.py:126`.
- **Suggested fix:** replace the thread-per-event with a **single writer thread + a bounded `queue.Queue`**; the UI-thread branch then only enqueues. Ordering becomes FIFO and the thread count is constant. Coalesce `queue_updated` events (they are idempotent snapshots) so a burst does not enqueue 5 full-queue payloads.
- **Fix side effects:** a bounded queue must define an overflow policy (drop the oldest `queue_updated`, never drop `track_changed`); a single writer thread must not become a new bottleneck for `position_changed`, which fires every 5 s from the frontend (`player.js:613`) — that event should probably be dropped-if-busy rather than queued.
- **Discovered by:** B

---

#### F-WX-10-8  [P2] — `get_queue()` builds an inconsistent snapshot and reads a private field without the queue's lock

- **File:** `core/api.py:1772-1780`, `core/api.py:1819-1836`, `core/api.py:2016-2075`; `audio/queue.py:37-40`
- **Confirmed:** yes (the code); the exact interleaving is a hypothesis.
- **Description:** `AppApi.get_queue()` — the payload behind every `queue_updated` event — is assembled from **three independent lock acquisitions** on `PlaybackQueue`, one of which bypasses the lock entirely:

  ```python
  def get_queue(self):
      """Return current queue state."""
      return {
          "tracks": self._core.engine.queue.tracks,            # lock #1 (copy under the lock)
          "current_index": self._core.engine.queue._current_index,   # NO LOCK - private field
          "current_track": self._core.engine.queue.current_track,   # lock #2
          "shuffle": self._core.engine.queue.shuffle,          # lock #3
          "repeat": self._core.engine.queue.repeat,            # lock #4
      }
  ```

  `PlaybackQueue` exposes a properly locked `current_index` property (`audio/queue.py:37-40`) — the API deliberately bypasses it. `remove_from_queue` does the same (`core/api.py:1829` `if index == queue._current_index:`), and `main.py:566` reads `engine.queue._current_index` directly as well.
- **Cause:** the queue's invariants (tracks ↔ current_index ↔ current_track) are only consistent inside one critical section, but the consumer stitches them together from four separate ones. This is the AGENTS.md rule ("a new shared field joins its class's existing lock") inverted: an *existing* shared field is read *without* its class's lock.
- **Trigger conditions:** a `queue_updated` payload built while another thread is inside `queue.next_track()` / `queue.move_track()`.
- **User impact:** a `queue_updated` event can carry a `current_index` that points at a different track than `current_track`; the frontend's queue drawer then highlights the wrong row (`ui/web_new_v2/js/queue.js:67` `renderQueue(q.tracks, q.current_index)`). `remove_from_queue` can compare the index against a stale `_current_index` and refuse (or remove) the wrong entry.
- **Evidence:** the quoted `get_queue`; `audio/queue.py:37-40`:

  ```python
      @property
      def current_index(self) -> int:
          with self._lock:
              return self._current_index
  ```
- **Reproduction / verification:** the inconsistency is directly observable by interleaving `queue.next_track()` between the `tracks` read and the `_current_index` read — e.g. by calling `AppApi.get_queue()` from two threads while a third calls `engine.next_track()`. **Missing evidence:** a deterministic, non-timing-dependent test that pins the *wrong index* value; the code path is unambiguous, the interleaving is probabilistic.
- **Suggested fix:** add `PlaybackQueue.snapshot()` that returns `{tracks, current_index, current_track, shuffle, repeat}` built under **one** acquisition of `_lock`, and make `AppApi.get_queue()` use it. Delete the direct `_current_index` reads (also in `main.py:566` and `core/api.py:1829`).
- **Fix side effects:** `snapshot()` copies the whole track list under the lock, so a long queue blocks the lock slightly longer than the current per-field reads; that is strictly better than the current inconsistency and the copy already happens today (`queue.tracks` copies the list).
- **Discovered by:** B

---

#### F-WX-10-9  [P3] — Shared "current track" and "last position" fields live outside their class's lock

- **File:** `core/api.py:1227` (write, no lock), `core/api.py:1307` (read, under lock), `core/api.py:1378` (read, no lock), `core/api.py:3825` (read, no lock); `core/api.py:1422` (`engine._last_reported_position` write), `main.py:563` (read), `audio/engine.py:27-33` (`AudioEngine.__init__` declares no such field)
- **Confirmed:** yes
- **Description:** two fields are shared mutable state with no consistent lock discipline:
  - `AppApi._current_track` is written at `core/api.py:1227` **outside** any lock (the `with self._window_op_lock:` block at `:1211-1212` covers only `_history_logged_key`), and read both under the lock (`:1307`) and outside it (`:1378`, `:3825`).
  - `AudioEngine._last_reported_position` is not declared in `AudioEngine.__init__` at all (`audio/engine.py:27-33`); it is created from the outside by `core/api.py:1422` (`self._core.engine._last_reported_position = pos_sec`) and read by `main.py:563` at shutdown.
- **Cause:** the AGENTS.md rule ("a new shared field joins its class's existing lock") is honoured for `BaseMusicService` and `StreamResolver` but not for `AppApi` / `AudioEngine`, which have no playback lock at all (see F-WX-10-1). The `_last_reported_position` field is an attribute grafted onto another class from a third one.
- **Trigger conditions:** a `report_position` racing a `track_changed` (both run on bridge threads).
- **User impact:** low on its own — the values are single attribute assignments and therefore atomic under the GIL — but it means the Discord presence (`core/api.py:1378`) and the session save (`main.py:563`) can read a track/position that belongs to a different track than the one being played. `_last_reported_position` is not reset when the track changes, so the saved session can resume the *previous* track at the *new* track's position.
- **Evidence:** `core/api.py:1422` and `main.py:561-566`:

  ```python
              app_core.session.save_session(
                  track_id=engine.queue.current_track.get("id") if engine.queue.current_track else None,
                  position=getattr(engine, '_last_reported_position', 0),
                  volume=app_volume,
                  queue=engine.queue.tracks,
                  queue_index=engine.queue._current_index,
  ```
- **Reproduction / verification:** `grep -rn "_last_reported_position" --include=*.py` → exactly two hits: the write (`core/api.py:1422`) and the read (`main.py:563`). `_last_reported_position` is never reset on track change (grep for assignments: one), so after switching tracks the saved position belongs to the previous track.
- **Suggested fix:** declare both fields in their owning class, reset `_last_reported_position` in `AudioEngine._notify_track_changed`, and guard them with the playback lock introduced for F-WX-10-1 (or move the position into the `PlaybackQueue`/`AudioEngine` state that already exists).
- **Fix side effects:** resetting the position on track change changes the saved-session behaviour (correctly — the session should not resume a track at another track's offset); it may break a test that asserts the old behaviour (none found).
- **Discovered by:** B

---

#### F-WX-10-10  [P3] — `queue_updated` ships the entire queue on every event; a 5-click burst marshals 0.35–2.4 MB of JSON to the WebView

- **File:** `core/api.py:1430-1435` (`_notify_queue_updated`), `core/api.py:1528, 1540, 1547, 1567, 1581` (one call per `play_track` fast path), `core/api.py:1785` (`reorder_queue`), `core/api.py:1791, 1801, 1813, 1832` (queue ops)
- **Confirmed:** yes (measured)
- **Description:** every queue mutation emits the full queue. `get_queue()` returns the whole track list, `_emit` serialises it with `json.dumps` (`core/api.py:1132`) and injects it as **JavaScript source** into the page (`core/api.py:1133-1136`).
- **Cause:** the queue is broadcast as a full snapshot because there is no delta/dirty-tracking and no version negotiation with the frontend (the frontend *does* have `currentQueueVersion`, `ui/web_new_v2/js/player.js:22`, but the backend never sends one).
- **Trigger conditions:** any burst of queue mutations.
- **User impact:** measured payload sizes (`%TEMP%\opencode\audit_reports\wx10_repro5.py`):

  ```
  queue of    50 tracks: snapshot  0.00 ms | json.dumps  0.11 ms |    17.5 KiB
     -> a 5-click burst emits 5-7 queue_updated events:  88-123 KiB of JSON
  queue of   200 tracks: snapshot  0.01 ms | json.dumps  0.27 ms |    69.3 KiB
     -> a 5-click burst emits 5-7 queue_updated events: 347-485 KiB of JSON
  queue of  1000 tracks: snapshot  0.01 ms | json.dumps  1.26 ms |   346.7 KiB
     -> a 5-click burst emits 5-7 queue_updated events: 1733-2427 KiB of JSON
  ```

  The `json.dumps` cost itself is negligible (0.11–1.26 ms); the cost lands in the WebView, which must parse 0.35–2.4 MB of injected JS source per burst, and in the `Control.Invoke` marshalling of that string. The frontend then re-renders the whole drawer for each event (`ui/web_new_v2/js/queue.js:67`).
- **Evidence:** the measured table above; `core/api.py:1430-1435`:

  ```python
      def _notify_queue_updated(self):
          """Emit queue_updated so the drawer never goes stale after a queue swap."""
          try:
              self._emit("queue_updated", self.get_queue())
  ```
- **Reproduction / verification:** `%TEMP%\opencode\audit_reports\wx10_repro5.py` (uses the real `PlaybackQueue` and `json.dumps`).
- **Suggested fix:** send a queue **version** plus a delta (or at minimum coalesce the 5–7 `queue_updated` events of a burst into one, which the single-writer emit queue of F-WX-10-7 makes trivial).
- **Fix side effects:** the frontend's drawer logic (`queue.js:61-73`) currently assumes a full snapshot; a delta protocol requires a matching frontend change, which is outside the Windows-only defect scope of this area.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct:

- **`PlaybackQueue` is internally consistent.** `audio/queue.py:15` declares one `threading.RLock` and *every* mutator and reader takes it (`set_tracks:121`, `add_track:136`, `add_tracks:163`, `remove_track:175`, `move_track:195`, `next_track:217`, `previous_track:252`, `toggle_shuffle:266`, `toggle_repeat:271`, `jump_to:282`, `clear:292`, `get_upcoming:300`, and all properties). The RLock is re-entrant, which is what makes `set_tracks`' internal `self.current_track` call legal.
- **No lock-order inversion between `core/api.py` and `core/resolver.py`.** `StreamResolver` holds a plain `threading.Lock` (`core/resolver.py:49`) and never calls out while holding it: the DB calls in `get_cached_url` (`:152`) and `_persist` (`:265`) are made **outside** the critical section. Nothing in the resolver path acquires the queue lock or `_window_op_lock`. `tools/check_lock_nesting.py` reports `OK: no nested-lock self-deadlock patterns` across the repo.
- **`BaseMusicService` honours the AGENTS.md lock rule.** `services/base_service.py:125` `_cache_lock = threading.RLock()` (class level) guards `_search_cache`, `_stream_cache` **and** `_pending_requests` (`:142, 150, 194, 219, 251, 268, 275`).
- **Provider-level dedupe exists.** `services/youtube_service.py:912-917` keeps a `_pending_streams` map under `_ydl_lock`, so N concurrent requests for the *same* YouTube URL collapse into **one** yt-dlp extraction with N callbacks fanned out (`finish`, `:919-930`). Five rapid clicks on the *same* track therefore cost one extraction, not five.
- **`StreamResolver._inflight` does not leak.** The flight is removed in a `finally` (`core/resolver.py:218-222`) and `flight.event.set()` always runs, so a failed cascade cannot strand a waiter. `_mem` is LRU-capped at 1024 (`:21, 75-77`) and `_failed` at 512 (`:28, 82-83`).
- **The proxy's self-heal path is bounded and safe.** `core/proxy.py:1023-1052` invalidates the resolver cache on 403/410, re-resolves once through the same entry point with a hard `resolve_event.wait(timeout=7)`, re-checks the SSRF guard on the new URL (`:1054-1056`) and does **not** leak credentials to a foreign host (`:1063-1079`).
- **The proxy's auth is fail-closed and constant-time.** `core/proxy.py:491-511` refuses every request when the token is unset and compares with `hmac.compare_digest`; the CORS header is only echoed for a loopback `Origin` (`:530-536`).
- **No `<audio>` listener leak in the frontend.** `setupAudioEvents` is installed exactly once per element at module load (`ui/web_new_v2/js/player.js:678-679`) on the two module-level singletons `audioA`/`audioB` (`:82-86`); there is no per-track `addEventListener`. The `ratechange` listener is likewise installed once per element (`:673-677`).
- **`MediaSource`/HLS instances are destroyed on every abandon path.** `destroyHls` (`ui/web_new_v2/js/player.js:89-95`) is called from `loadAudioSource` (`:115`), `releaseAudio` (`:159`) and the `playTrack` teardown (`:755`); `releaseAudio` is reached from `finishFade` (`:166`), `handleStreamError` (`:452`), `stopFailedPlayback` (`:501-502`) and `stopPlaybackForQueueEnd` (`:1837-1838`). `loadAudioSource` correctly keeps a preloaded HLS instance alive when the URL is unchanged (`:109-114`).
- **The frontend already has the right primitive — it just is not mirrored on the backend.** `playbackGeneration` (`ui/web_new_v2/js/player.js:23`) correctly discards stale recovery/prefetch results, and `tests/test_player_recovery_transitions.py` pins that behaviour (`test_skip_discards_a_recovery_result_…`, `test_prefetch_callback_after_skip_cannot_load_stale_audio`).
- **`_emit` correctly avoids the UI-thread deadlock.** `core/api.py:1147-1154` detects the main thread and hands the `evaluate_js` to a worker; `tests/test_emit_thread_safety.py` pins it. The defect in F-WX-10-7 is the *shape* of that mechanism, not the rule itself.
- **The proxy's thread bookkeeping is sound.** `core/proxy.py:421-446` uses `ThreadingMixIn` with `daemon_threads = True` and prunes dead threads under `_threads_lock`; the per-request SQLite connection is released in `finish()` (`:469-486`).

---

### 4. Coverage gaps

- **No test drives two concurrent transport commands.** The only thread-based tests in the suite are `tests/test_api_audit_b.py:296` (SSRF cache) and `tests/test_resolver_state.py:152` (the resolver's single-flight) — neither touches `AppApi.play_track`/`next_track`/`reorder_queue`. `tests/test_queue.py`, `tests/test_engine_notify.py`, `tests/test_engine_resolve.py`, `tests/test_player_recovery_transitions.py` and `tests/test_playback_latency_ui.py` are entirely single-threaded and call every callback synchronously.
- **The stale-resolution branch is untested.** Every `_resolve_track` test uses a **local** track, i.e. the synchronous fast path (`tests/test_api_audit_b.py:412-459`): `test_resolve_track_local_missing_file_reports_error`, `test_resolve_track_local_recovered_from_streams_dir`, `test_resolve_track_local_existing_file_is_delivered`. The async path's `elif queue.current_track is cur_start: play_callback(track)` branch (`core/api.py:1734-1736`) is never executed by the suite — which is exactly why the F-WX-10-2 defect survives.
- **The single-flight test gives false confidence.** `tests/test_resolver_state.py:152 test_single_flight_shares_one_cascade` proves `StreamResolver.resolve` is single-flight, but the playback path never calls it (F-WX-10-4). A green suite therefore says nothing about the user's actual burst behaviour.
- **`tests/test_engine_notify.py` asserts the proxy-URL *shape* only.** It is a good contract test, but every callback fires synchronously in-process, so it cannot see the ordering between "queue advanced" and "event emitted".
- **Not verified (needs a live WebView2 / real providers):** the *ordering* of `track_changed` events delivered to the page when several bridge threads emit concurrently (F-WX-10-7's hypothesis). Everything else in this report was reproduced headlessly against the real `AppApi`/`AudioEngine`/`PlaybackQueue`.
- **Not measured on real hardware:** the wall-clock cost of an abandoned yt-dlp extraction and the actual starvation of the 8-worker provider pool under a 5-click burst; the numbers in F-WX-10-6 are structural (5 chains started, 0 cancelled) rather than timing measurements.
- **Out of scope but noted:** `ui/web_new_v2/js/queue.js:280-281` mutates the frontend's `currentQueue` *before* awaiting `reorder_queue`, so the frontend's optimistic reorder and the backend's `move_track` can disagree; that is a WN-29/WN-19-adjacent frontend concern and was not audited here.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — One owner for "what is playing", one command lock, one epoch.**
Today "what is playing" is held in five places that can disagree:

| Holder | Field | Written by | Lock |
|---|---|---|---|
| `core/api.py` | `self._current_track` (`:1227`) | `_on_track_changed` | none (read under `_window_op_lock` in one place, outside it in two) |
| `audio/queue.py` | `_current_index` + `_tracks` (`:16-18`) | every queue op | `PlaybackQueue._lock` (RLock) |
| `audio/engine.py` | *no field* — delegates to `queue` | — | none (`AudioEngine` has no lock at all) |
| `core/resolver.py` | `_inflight` (`:51`) | `resolve` | `self._lock` (plain Lock) |
| `ui/web_new_v2/js/player.js` | `currentTrack` (`:3`), `activeAudio` (`:86`) | `onTrackChanged` / `playTrack` | JS single-threaded, but **asynchronous w.r.t. the bridge** |
| `ui/web_new_v2/js/queue.js` | `currentQueue` (`:6`) | `queue_updated` / optimistic edits | none |

`AudioEngine` owns the queue but the *state machine* is split across three layers with no single authority: `AppApi.play_track` (bridge method) → `AudioEngine.play_queue` (queue mutator) → `PlaybackQueue.set_tracks` (data). The transport command path has no state machine at all: there is no "idle → resolving → playing → paused" model, only a set of side effects. That is why staleness cannot be detected: there is no epoch, only object identity.

*Proposed seam (not implemented):* a single `PlaybackController` (new module, e.g. `audio/controller.py`) that owns
1. the queue (moving `PlaybackQueue` behind it),
2. the current-track state (one field, replacing `AppApi._current_track`),
3. a `playback_epoch` counter,
4. one `command_lock` (RLock) around *every* state transition,
5. a single `on_state_changed(state)` callback that is the **only** publisher of `track_changed` / `queue_updated`.

`AppApi.play_track/next_track/prev_track/reorder_queue` become thin adapters: validate input → `controller.command(...)` → return. `AudioEngine` shrinks to a resolution helper. The frontend keeps its own `playbackGeneration` but the backend's epoch is echoed in `track_changed`, so the page can drop results that are already stale instead of guessing.

**ARCH-2 — A single-writer event bus with ordering and back-pressure.**
`_emit` is a fire-and-forget thread spawner (F-WX-10-7). One writer thread + a bounded queue gives FIFO ordering, a constant thread count and a place to coalesce idempotent snapshots (`queue_updated`, `position_changed`). It also removes the "is this the UI thread?" branch as a correctness concern rather than a performance one.

**ARCH-3 — Make `StreamResolver` the only resolution entry point.**
Today there are three ways to resolve a stream: `AppCore.re_resolve_stream_url_async` (playback), `StreamResolver.resolve` (proxy), and `AudioEngine._resolve_via_network` (a second, duplicated cascade implementation at `audio/engine.py:153-508` that the resolver calls). Three implementations of the same cascade, with different caches and different budgets, is the root cause of F-WX-10-4/5/6. One entry point — with the single-flight, the mem cache, the "unavailable" memo and a cancellation token — would make the burst cheap by construction instead of by tuning.

**ARCH-4 — Make the backend authoritative for the queue; stop round-tripping the whole list.**
`AppApi.play_track` replaces the backend queue with whatever list the page sends (F-WX-10-3), and `queue_updated` ships the whole list back (F-WX-10-10). The backend should own the queue; the page should send *intent* ("play index 7", "move 3→5", "append these") and receive a versioned delta. The frontend already has `currentQueueVersion` (`player.js:22`) and `incrementQueueVersion()` (`player.js:58`) — the backend never sends a version, so the two sides cannot detect that one of them is stale.

**ARCH-5 — One `PlaybackQueue.snapshot()` and no private-field access.**
`PlaybackQueue` exposes locked properties, but three call sites read `_current_index` directly (`core/api.py:1776`, `core/api.py:1829`, `main.py:566`). A single `snapshot()` under one lock acquisition removes the inconsistent-snapshot class of bugs (F-WX-10-8) and makes the queue's invariants enforceable in one place.

---
