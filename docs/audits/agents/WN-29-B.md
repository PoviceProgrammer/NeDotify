## AREA WN-29 — UI player, equalizer, queue view, visualizer — ROLE B

### 1. Scope reviewed

**Files opened (read in full):**

| Path | Lines read |
|---|---|
| `ui/web_new_v2/js/player.js` | 1–2711 (whole file; the area map says 2489 L — the file is now 2711 L) |
| `ui/web_new_v2/js/queue.js` | 1–303 (whole file) |
| `ui/web_new_v2/js/equalizer.js` | 1–351 (whole file) |
| `ui/web_new_v2/js/visualizer.js` | 1–532 (whole file) |

**Callees traced into other areas (read for cross-checking, not owned here):**

- `core/api.py` — `get_proxy_info` (1398‑1405), `report_position` (1407‑1428), `play_track` (1437‑1606), `_resolve_track` (1608‑1744), `play_pause`/`next_track`/`get_queue`/`reorder_queue`/`remove_from_queue`/`clear_queue` (1746‑1851), `set_volume`/`toggle_mute`/`is_muted`/`toggle_shuffle`/`toggle_repeat` (1956‑2014), `get_next_track` (2016‑2075), `get_equalizer`/`set_equalizer` (3173‑3190), `recover_stream` (4166‑4174), `_on_track_changed` (1195‑1242).
- `core/proxy.py` — `auth_query`/`get_proxy_url` (1300‑1334), `_authorized` (491‑511), `_send_cors_headers` (530‑536), `_is_loopback_origin` (102‑112), `serve_local_file` (538‑597), `_rewrite_hls_playlist` (396‑410).
- `audio/engine.py` — `_notify_track_changed` (78‑119), `next_track` (55‑63).
- `audio/queue.py` — full file (shuffle setter 68‑106, `set_tracks` 119‑132, `next_track` 215‑248, `move_track` 193‑213).
- `core/playback_recovery.py` — `recover_stream` (95‑183).
- `core/settings.py` — `DEFAULT_SETTINGS["audio"]` (71‑79), `["equalizer"]` (238‑241), `["hotkeys"]`.
- `ui/web_new_v2/js/main.js` — bridge gate / `PROXY_PORT`+`PROXY_TOKEN` publication (32‑73), init order (528‑545).
- `ui/web_new_v2/js/events.js` — `dispatchPythonEvent` (50‑69), `track_changed` (97‑101), `position_changed` (110‑127), `queue_updated` (283‑286), `shuffle_changed` (288‑295).
- `ui/web_new_v2/js/utils.js` — `escapeHtml` (17‑25), `getCanvasDpr` (369‑371), `sizeCanvasForDpr` (382‑398), `getCoverUrl` (615‑639), `renderIcons` (943‑958), `updatePlayingTrackInDOM` (676‑686).
- `ui/web_new_v2/js/hotkeys.js` — only the player-facing bindings (178‑209).
- `main.py` — `create_window(url=html_path)` (348‑381), `webview.start(http_server=True, …)` (555).
- pywebview `webview/__init__.py` (188‑198, 326‑341), `webview/window.py` (179‑202), `webview/util.py::is_local_url`, `webview/http.py::start_server`, `webview/platforms/edgechromium.py` (48‑61) — to establish the page origin and the WebView2 settings.
- Tests: `tests/test_playback_latency_ui.py`, `tests/test_player_layout_geometry.py`, `tests/test_player_recovery_transitions.py`, `tests/test_player_resources.py`, `tests/test_visual_effects_lifecycle.py`, `tests/test_equalizer_controls_ui.py`, `tests/test_keybind_contracts.py`.

---

### 2. Findings

#### F-WN-29-1  [P1] — The loopback proxy bearer token is written into live DOM attributes and into the WebView console on every track change

- **File:** `ui/web_new_v2/js/player.js:1731,1760,1797` (+ `ui/web_new_v2/js/queue.js:157`); source of the URL: `ui/web_new_v2/js/utils.js:626-628`; the token is minted per session in `core/proxy.py:1271-1276` and is the only credential the proxy accepts (`core/proxy.py:491-511`). Console leak: `ui/web_new_v2/js/events.js:74` + `core/api.py:1240`.
- **Confirmed:** yes that the token reaches those surfaces. The *exploitability* of the console surface depends on who can read the WebView devtools log — see "Trigger conditions".
- **Description:** The proxy is a bearer-token service: every request must carry `?k=<per-session token>` (`core/proxy.py:503-511`, fail-closed). The frontend builds token-bearing URLs and then puts them straight into DOM attributes of real, attached elements:
  - `player.js` writes the cover URL into `<img id="pb-cover">`, `<img id="pp-cover">`, `<img id="mp-cover">` via `setElSrc()`;
  - `queue.js` writes it into **one `<img src>` per queue row** (up to hundreds).
  Separately, the backend embeds the same token into `track.stream_url` (`core/proxy.py:1313,1331-1332` → `core/api.py:1216-1225,1240`), and `events.js:74` logs the *entire* payload verbatim: `console.log('Python Event:', eventName, data)` — so the full `?k=<token>` URL is written to the WebView2 console on every single track change.
- **Cause:** the proxy's auth model is "bearer in the query string", and the frontend treats those URLs as ordinary asset URLs. There is no redaction step anywhere between `get_proxy_url()` and the DOM/console.
- **Trigger conditions:** every track change (console) and every cover render / queue render (DOM attributes). The token is valid for the whole app session.
- **User impact:** anything that can read the DOM or the console (a DOM-serialising diagnostic/crash path, a shared devtools session, an injected script) obtains a bearer that unlocks the user's local library and the provider-authenticated upstream requests the proxy makes on their behalf. The proxy's own docstring states the threat model explicitly: *"readable by any local process or by any web page that guesses the port"*.
- **Evidence:**
  ```js
  // player.js:1731
  setElSrc('pb-cover', coverUrl);
  // utils.js:626-628
  if (window.PROXY_PORT) {
      const tokenQuery = window.PROXY_TOKEN ? `&k=${encodeURIComponent(window.PROXY_TOKEN)}` : '';
      return `http://127.0.0.1:${window.PROXY_PORT}/api/cover?path=${encodeURIComponent(track.cover_path)}${tokenQuery}`;
  }
  // queue.js:157
  ${coverUrl ? `<img class="track-item-cover" src="${escapeHtml(coverUrl)}" alt="" ...>` : ...}
  // events.js:74
  console.log('Python Event:', eventName, data);   // data.stream_url contains "&k=<token>"
  ```
- **Reproduction / verification:**
  1. Launch the app, play any track.
  2. Open the WebView2 devtools (debug build) → Console: `Python Event: track_changed {… stream_url: 'http://127.0.0.1:PORT/api/stream?...&k=<token>' …}`.
  3. `document.getElementById('pb-cover').getAttribute('src')` → contains `&k=<token>`; `document.querySelectorAll('#queue-drawer-content img.track-item-cover')[0].src` → same.
  4. `curl "http://127.0.0.1:<proxyPort>/api/stream?url=…" -H "Cookie: k=<token>"` style replay: the token alone is sufficient for the proxy (see `core/proxy.py:503-511`).
- **Suggested fix:** (a) stop putting the token in URLs the frontend renders — move cover/stream fetches behind a `fetch()` + `URL.createObjectURL` blob, or a `SameSite=Strict` cookie on `127.0.0.1`; (b) drop or redact the `console.log('Python Event:', …)` payload in `events.js` (WN-28 owns that line) — at minimum strip `k=` from any logged URL.
- **Fix side effects:** a cookie-based scheme needs a backend change in `core/proxy.py` (WN-11) because the `<audio>` element cannot attach an `Authorization` header; the blob approach costs an object-URL lifecycle and loses HTTP range streaming for covers only (not for audio).
- **Discovered by:** B

---

#### F-WN-29-2  [P1] — The Web Audio graph is bound to the media elements with no user gesture, and the "context is suspended" recovery is swallowed

- **File:** `ui/web_new_v2/js/player.js:325-384` (`initAudioContext`), `:404-414` (`getAudioFrequencyData`), `:701-703`, `:870`, `:416-418`; callers `ui/web_new_v2/js/equalizer.js:188,206,334` and `ui/web_new_v2/js/visualizer.js:279`.
- **Confirmed:** the code facts are **confirmed** (creation sites, absence of a gesture, swallowed rejections, no `close()`). The end-user consequence ("the app plays silently") is a **hypothesis** — see below.
- **Description:** `initAudioContext()` calls `audioCtx.createMediaElementSource(audioA)` / `(audioB)`. Once an element is bound to a `MediaElementAudioSourceNode` its output is routed **exclusively** through the Web Audio graph; the element's own output is muted. The context is created:
  - from `setEq()` — called by `equalizer.js:188`/`:206` during `initEqualizer()`, which `main.js:543` runs at app start, long before any click;
  - from `getAudioFrequencyData()` — called from the **visualizer's rAF callback** (`visualizer.js:279`), which is not a user gesture either.
  Chromium's autoplay policy starts such a context in `suspended`. The only recovery is `audioCtx.resume()`, and it is invoked from four sites whose promises are **not** handled consistently:
  - `player.js:702` — `audioCtx.resume().catch(() => {})` → the rejection is silently swallowed;
  - `player.js:407` — `audioCtx.resume();` → **unhandled promise rejection**, and it is called on *every* visualizer frame (24 Hz) while suspended;
  - `player.js:418`, `player.js:870` — the returned promise is not awaited.
  There is also no `audioCtx.close()` anywhere in the file (grep: `audioCtx.` appears at 316-430 only) and no `dispose()` for the graph.
- **Cause:** the DSP graph is created as a side effect of *reading* analyser data / restoring settings, instead of at an explicit "the user pressed play" boundary with a documented lifetime.
- **Trigger conditions:** the visualizer or the equalizer being touched before the first user gesture; any environment in which the WebView2 media-autoplay policy blocks `resume()`.
- **User impact:** if the context stays suspended, the two `<audio>` elements are bound to a graph that never processes samples — **the app is silent while the UI reports "playing"**, and the visualizer shows only its synthetic fallback. The four `resume()` call sites make the authors' own uncertainty visible: they clearly hit a suspended context at some point.
- **Evidence:**
  ```js
  // player.js:328, 371-372
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  srcA = audioCtx.createMediaElementSource(audioA);
  srcB = audioCtx.createMediaElementSource(audioB);
  // player.js:404-408  (called from the visualizer rAF loop)
  export function getAudioFrequencyData(dataArray) {
      if (!audioCtx) initAudioContext();
      if (audioCtx && audioCtx.state === 'suspended') {
          audioCtx.resume();          // <-- unhandled rejection, 24x/s
      }
  ```
- **Reproduction / verification:**
  1. Hypothesis check (needs a build where autoplay is gated): launch the app, **do not click anything**, let `initEqualizer()` finish (DevTools → Console: `initAudioContext` ran), then press Play.
  2. Assert `audioCtx.state` — if it stays `suspended`, the element output is muted. In DevTools: `getEventListeners(document)` is not available for the detached `<audio>`; instead observe that `analyserNode.getByteFrequencyData()` returns zeros while the transport UI advances.
  3. Code-level verification (no runtime needed): `grep -n "audioCtx.close\|audioCtx.suspend" ui/web_new_v2/js/player.js` → no matches; `grep -n "resume()" ui/web_new_v2/js/player.js` → 4 sites, only one of which handles the rejection.
- **Suggested fix:** create the graph lazily but **only from a user-gesture handler** (the play button / the first `pointerdown`), gate the visualizer's `getAudioFrequencyData()` on `audioCtx?.state === 'running'`, and always `catch()` the `resume()` promise. Add an explicit `disposeAudioGraph()` next to `destroyVisualizer()`.
- **Fix side effects:** deferring the graph means the analyser is silent until the first click — the orbit-glow bass effect must degrade gracefully (it already has a synthetic path). `createMediaElementSource` can only be called once per element, so the deferral must be idempotent.
- **Discovered by:** B

---

#### F-WN-29-3  [P2] — The frontend keeps its own queue copy that is never refreshed on shuffle; the drawer shows a stale order and a queue-row click rewrites the backend queue from the stale copy

- **File:** `ui/web_new_v2/js/queue.js:6,10,61-69,76-85,181-186`; `core/api.py:2004-2008` (`toggle_shuffle`); `ui/web_new_v2/js/events.js:288-295` (`shuffle_changed` handler); `audio/queue.py:68-106` (shuffle setter), `119-132` (`set_tracks`); `core/api.py:1502-1529` (`play_track` → `engine.play_queue` → `set_tracks`).
- **Confirmed:** yes.
- **Description:** The backend's shuffle **mutates the queue order in place** (`audio/queue.py:76-80`: the current track is pinned at index 0 and the rest are shuffled) and moves `_current_index` to 0. But `AppApi.toggle_shuffle` emits only `shuffle_changed` — **never `queue_updated`**:
  ```python
  # core/api.py:2004-2008
  def toggle_shuffle(self):
      enabled = self._core.engine.toggle_shuffle()
      self._emit("shuffle_changed", {"state": enabled})
      return enabled
  ```
  and the frontend's `shuffle_changed` handler (`events.js:288-295`) only toggles the two button classes. `queue.js` refreshes its copy **only** on `nedotify:queue_updated` (61‑69) or `nedotify:track_changed` (71‑73, and only while the drawer is open). So after a shuffle:
  - `queue.js`'s `currentQueue` / `window.currentQueue` still holds the **pre-shuffle** order and the **pre-shuffle** `current_index`;
  - an open drawer keeps rendering that stale order with the "playing" highlight on the wrong row;
  - clicking a drawer row sends the stale copy back to the backend: `window.pywebview.api.play_track(track, currentQueue, index)` (`queue.js:182`) → `core/api.py:1502-1529` → `engine.play_queue(track_list, safe_index)` → `queue.set_tracks(track_list, …)` → **the backend queue is overwritten by the stale pre-shuffle list and the shuffle is re-randomised** (`audio/queue.py:126-132` re-shuffles because `_shuffle` is still `True`), and `_original_order` is reset to the stale list, so un-shuffling later restores the wrong "original" order.
- **Cause:** the frontend treats the queue as a mirrored copy that it may also *author*, while the backend is the only owner of the shuffle permutation. There is no version/ordering handshake between the two.
- **Trigger conditions:** toggle shuffle (bottom bar or player page), then click a row in the queue drawer without closing/reopening it first. Also: toggle shuffle, then let the queue reach its end and press Play — `player.js:878` re-sends `window.currentQueue` to `play_track`.
- **User impact:** the queue drawer shows the wrong order and the wrong "now playing" row; clicking a row silently rewrites the queue order and re-randomises the shuffle, so the order the user sees is not the order that plays.
- **Evidence:**
  ```js
  // queue.js:61-69  — the only refresh paths
  document.addEventListener('nedotify:queue_updated', (e) => {
      incrementQueueVersion();
      const q = e.detail || {};
      currentQueue = q.tracks || [];
      syncQueueToWindow();
      if (isQueueVisible) renderQueue(q.tracks, q.current_index);
  });
  // queue.js:181-182 — the stale copy is sent back as the authoritative queue
  if (window.pywebview?.api?.play_track) {
      window.pywebview.api.play_track(track, currentQueue, index);
  ```
  ```python
  # audio/queue.py:76-80 — the backend really does permute in place
  remaining = [t for i, t in enumerate(self._tracks) if i != self._current_index]
  random.shuffle(remaining)
  if current:
      self._tracks = [current] + remaining
      self._current_index = 0
  ```
- **Reproduction / verification:**
  1. Build a queue of ≥3 tracks (library → "play all"), let it start.
  2. Open the queue drawer (it loads the current order), close it, press the bottom-bar shuffle button, then re-open the drawer and compare the order with `python -c "…"` reading `core.engine.queue.tracks` — or simply watch the drawer: it shows the same order as before the shuffle.
  3. While the drawer is open, press shuffle in the bottom bar, then click the 2nd row: the row that starts playing is the stale-list row, and the queue order in the drawer resets.
  4. Unit-level: `tests/` has no test that asserts `queue_updated` is emitted after `toggle_shuffle` (grep `toggle_shuffle` in `tests/` → only `audio/queue.py`-level tests).
- **Suggested fix:** emit `queue_updated` from `AppApi.toggle_shuffle` (and from `toggle_repeat` for symmetry), and stop sending the frontend's queue copy back as the authoritative list — send the track id / index and let the backend resolve it inside its own queue.
- **Fix side effects:** the backend-side fix is one line and safe. The frontend-side fix (never sending the list) changes `play_track`'s contract for every caller (library "play all", playlist import, yt_playlist_ready in `events.js:148`), so it is a cross-area change.
- **Discovered by:** B

---

#### F-WN-29-4  [P2] — No playback state machine: `isPlaying` is forced to `false` while the previous track is still audible, and the progress loop is parked

- **File:** `ui/web_new_v2/js/player.js:1695-1705` vs `:744-745`, `:1855-1872`, `:1371-1379`.
- **Confirmed:** yes.
- **Description:** `player.js` holds the playback state in ~20 independent module-level `let`s (`currentTrack`, `isPlaying`, `currentDuration`, `currentPosMs`, `targetPosMs`, `isSeeking`, `isDraggingProgress`, `activeAudio`, `outgoingAudio`, `currentReplayGain`, `currentPlaybackRate`, `playbackGeneration`, `currentQueueVersion`, `automaticTransition`, `preparedNext`, `pendingResume`, `gaplessAdoptionKey`, `recoveryRequest`, `currentTrackRetries`, `lastSeekTime`). There is no state enum. Two concrete divergent writes:
  - **`isPlaying`**: written at `player.js:745` (`playTrack` → `true`), `1681`/`1698`/`1707` (`onTrackChanged` → `false`), `1856` (`onStateChanged` → `state === 'playing'`). In the "stream not resolved yet" branch (`1695-1705`) the frontend sets `isPlaying = false` and `onStateChanged('loading')` **but never pauses `activeAudio`** — the previous track keeps playing audibly while the UI shows a spinner, and `onStateChanged` cancels the rAF progress loop (`1868-1871`), so the progress bar freezes.
  - **`currentDuration`**: written at `586` (`timeupdate`, only when it differs by >2000 ms), `773` (`playTrack`, from track metadata), `1388` (`animateProgress`, from `audio.duration`), `1656`/`1747` (`onTrackChanged`, from metadata), `1943` (`onPositionChanged`, from the backend). The *label* is only written from the metadata value (`1664-1666`, `1754-1756`), while the *bar percentage* is computed from `currentDuration` — which `animateProgress` silently replaces with the element's real duration. The two therefore disagree whenever the backend metadata and the element duration differ.
  - **`targetPosMs`** is written at `555, 814, 1647, 1745, 1950` and **never read anywhere** — dead state that looks like part of a state machine (verified by grep over the whole file).
- **Cause:** state is modelled as independent mutable flags with multiple, uncoordinated writers instead of a single transition function with one owner per field.
- **Trigger conditions:** any track change that needs a network resolution (the common case for YouTube/SoundCloud tracks): the old track keeps playing for the length of the resolution while the UI says "loading" and the progress bar is frozen. The duration/label divergence appears whenever `track.duration` ≠ `audio.duration`.
- **User impact:** the transport UI contradicts the audio; the position readout stops updating; the play/pause button shows a spinner while sound is still coming out of the speakers.
- **Evidence:**
  ```js
  // player.js:1695-1705 — the unresolved branch
  } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
      // Stream not resolved yet: show loading and request background resolution.
      isPlaying = false;                 // <-- diverges from the still-playing element
      onStateChanged('loading');         // <-- cancels the progress rAF (1868-1871)
      ...
      window.pywebview.api.play_track(pendingTrack);
  ```
  ```js
  // player.js:1386-1399 vs 1754-1756 — two writers, two different sources of truth
  currentDuration = Math.round(activeAudio.duration * 1000);   // bar % uses this
  setElText('pb-time-total', formatTime(currentDuration / 1000)); // label uses metadata
  ```
- **Reproduction / verification:**
  1. Play a YouTube track; wait for it to start.
  2. Press Next to a track that is not in the stream cache.
  3. Observe: the spinner replaces the play button, the time readout stops, **but the previous track is still audible** until the resolution lands (typically 0.5–3 s).
  4. Divergence of the duration: play a track whose backend `duration` is rounded differently from the stream's real duration (or set the backend duration to 0 for a local file) and compare the "total" label with the bar's arrival at 100%.
- **Suggested fix:** introduce an explicit transport state (`idle | loading | playing | paused | ended | error`) owned by one transition function, and make `onTrackChanged` pause/release the outgoing element before entering `loading`.
- **Fix side effects:** the crossfade/gapless paths depend on the current "flags" semantics (e.g. `player.js:735-737` reads `automaticTransition` before `playTrack` clears it), so the refactor must preserve the crossfade handoff ordering.
- **Discovered by:** B

---

#### F-WN-29-5  [P2] — The progress rAF loop forces three style recalculations per frame and does three uncached `getElementById` lookups per frame

- **File:** `ui/web_new_v2/js/player.js:1416` (`renderWaveforms(pct / 100)`), `:2296-2303` (`renderWaveforms`), `:2358-2366` (`drawWaveformToCanvas`), `:2207-2210` (`getProgressOpacity`), `:1341-1355` (`_getProgEls` — the *cached* pattern, applied only to the progress elements).
- **Confirmed:** yes.
- **Description:** The progress bar itself is updated well: a `requestAnimationFrame` loop (`animateProgress`, throttled to `progressThrottleMs`, default 33 ms → 30 fps) writes `style.transform` on three elements and only rewrites `textContent`/`aria-valuenow` when the value actually changed (`1399-1413`). The cached-DOM pattern is even documented in the file ("Pre-cache progress DOM elements once (avoids getElementById on every frame)", `1343`). **The waveform path does not follow it**:
  - `renderWaveforms` (`2296-2303`) does `document.getElementById(id)` for all three canvases **on every frame** — no cache, unlike `_getProgEls()`.
  - `drawWaveformToCanvas` computes `const opacity = getProgressOpacity();` at `2360` — i.e. `getComputedStyle(document.documentElement).getPropertyValue('--player-progress-opacity')` — **before** the "nothing changed, skip the redraw" guard at `2365`. `getComputedStyle(...).getPropertyValue()` forces a style recalculation; because `animateProgress` has just written `style.transform`/`textContent` on three elements, the style is dirty, so each call is a real recalc. With three canvases that is **three forced style recalculations per animation frame (≈90/s)** over a ~209 KB document.
  - The colour lookup (`getWaveColor`, `2195-2205`) *is* properly cached — the opacity read was simply missed.
- **Cause:** a value that only changes on theme/settings changes is read per-canvas-per-frame, and the "skip the work" guard is placed *after* the expensive computation instead of before it.
- **Trigger conditions:** any playback with the waveform scrubber visible (the default `data-progress-style` is `bars`).
- **User impact:** avoidable main-thread work on every frame of every track; on a low-power laptop this shows up as a lower effective frame rate and higher CPU during playback.
- **Evidence:**
  ```js
  // player.js:2296-2303 — uncached lookups in the hot path
  export function renderWaveforms(progressPct = 0) {
      if (!isWaveformScrubberActive || !currentWaveformData) return;
      ['pb-waveform-canvas', 'pp-waveform-canvas', 'mp-waveform-canvas'].forEach(id => {
          const canvas = document.getElementById(id);
          if (canvas && !canvas.classList.contains('hidden')) drawWaveformToCanvas(canvas, currentWaveformData, progressPct);
      });
  }
  // player.js:2358-2366 — expensive read BEFORE the cheap guard
  const opacity = getProgressOpacity();
  ...
  if (canvas._wfProgressPixel === progressPixel && canvas._wfHoverPixel === hoverPixel && canvas._wfPeaks === peaks
      && canvas._wfStyle === style && canvas._wfColor === color && canvas._wfOpacity === opacity) return;
  // player.js:2207-2210
  function getProgressOpacity() {
      const opacity = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--player-progress-opacity'));
  ```
- **Reproduction / verification:**
  1. DevTools → Performance → record 5 s of playback; look for `getComputedStyle` / `updateLayoutTree` / `Recalculate Style` frames under the player's rAF callback.
  2. Cheap static proof: `grep -n "getComputedStyle" ui/web_new_v2/js/player.js` → `2208` is the only one, and it sits inside the per-canvas loop.
  3. Instrument: add `console.count(getProgressOpacity)` — it will print ≈90/s at the default 30 fps with the waveform visible.
- **Suggested fix:** hoist the opacity read out of the per-canvas loop and cache it in the same invalidation bucket as `waveColorCache` (invalidate on `data-theme`/`style` mutations of `<html>` and on `nedotify:progress_appearance_changed`); cache the three canvas elements like `_getProgEls()` does.
- **Fix side effects:** the opacity must be re-read when `--player-progress-opacity` changes; the existing `MutationObserver` on `<html>`'s `style` attribute (`player.js:2213-2216`) already covers theme/accent changes, so it can be reused.
- **Discovered by:** B

---

#### F-WN-29-6  [P2] — The queue drawer rebuilds every row (O(n) innerHTML + 2n lucide SVG creations) on every `queue_updated` event

- **File:** `ui/web_new_v2/js/queue.js:128-300` (per-row `innerHTML` at `153-166`, `renderIcons()` at `299`); `ui/web_new_v2/js/utils.js:943-958` (`renderIcons` → `lucide.createIcons({root: document.body})`).
- **Confirmed:** yes.
- **Description:** `renderQueue` clears the container and rebuilds every row from scratch, parsing one `innerHTML` template per row (which contains two `<i data-lucide>` placeholders) and then calling `renderIcons()` with **no argument** — so `root` is `document.body` and lucide replaces *every* remaining `[data-lucide]` element in the whole document. The code even documents that it avoided N `appendChild` layout invalidations (the `DocumentFragment`, `141`), but the per-row `innerHTML` parse and the whole-body lucide pass remain O(n).
  `queue_updated` is emitted on **every** queue mutation: `add_to_queue`, `play_next`, `add_tracks_to_queue`, `remove_from_queue`, `clear_queue`, `reorder_queue` (`core/api.py:1787-1851`), and `_notify_queue_updated` from `play_track` (`api.py:1430-1435`, called from the fast paths at `1528/1540/1547/1567/1581`).
  The Flow autopilot can grow the queue by up to 6 tracks per batch, up to 200 per session (`player.js:1552`, `1592`), and "play all" from the library adds whole albums — so queues of several hundred rows are reachable. A drag-and-drop reorder of one row costs a full rebuild of the list.
- **Cause:** the view has no diffing/recycling; every state change is a full re-render, and icon rendering is global rather than scoped to the rebuilt subtree.
- **Trigger conditions:** opening/refreshing the drawer with a long queue, or any queue mutation while the queue is long.
- **User impact:** visibly laggy queue interactions (drag-and-drop, remove, clear) and a main-thread stall proportional to the queue length; the drawer is rebuilt even when the change is a single row's removal.
- **Evidence:**
  ```js
  // queue.js:153-166 — one innerHTML parse per row, two lucide placeholders each
  item.innerHTML = `
      <div ... class="drag-handle" ...><i data-lucide="grip-vertical" ...></i></div>
      ${coverUrl ? `<img class="track-item-cover" src="${escapeHtml(coverUrl)}" ...>` : ...}
      ...
      <button class="icon-btn queue-remove-btn" ...><i data-lucide="x" ...></i></button>`;
  // queue.js:299 — global icon pass
  renderIcons();
  // utils.js:945 — root defaults to document.body
  const root = (targetEl && targetEl.nodeType) ? targetEl : document.body;
  ```
- **Reproduction / verification:**
  1. Fill the queue with 200+ tracks (Flow autopilot, or a library "play all").
  2. Open the drawer and time it; then drag one row and time the reorder.
  3. Instrument: `console.count(document.querySelectorAll('[data-lucide]').length)` before/after `renderQueue`; DevTools → Performance shows `lucide.createIcons` dominating the frame.
  4. Static proof that the event is hot: `grep -n "_emit(\"queue_updated\"\|queue_updated" core/api.py` → 7 emit sites.
- **Suggested fix:** scope the icon pass to the rebuilt subtree (`renderIcons(content)`), reuse row elements (keyed recycling) instead of rebuilding, and only re-render the rows that actually changed.
- **Fix side effects:** row recycling must preserve the `item._trackData` binding and the per-row listeners; a scoped `renderIcons(content)` changes `renderIcons`' contract (WN-28 owns the helper).
- **Discovered by:** B

---

#### F-WN-29-7  [P3] — No teardown path for the Web Audio graph or the `AudioContext`

- **File:** `ui/web_new_v2/js/player.js:316-430` (`audioCtx`, `eqNodes`, `analyserNode`, `compressorNode`, `srcA`, `srcB`); `ui/web_new_v2/js/visualizer.js:500-519` (`destroyVisualizer`).
- **Confirmed:** yes.
- **Description:** `destroyVisualizer()` releases the rAF loop, the resize listener, the DPR listener and the `IntersectionObserver`, but it does not touch the `AudioContext`, the EQ filter chain, the compressor or the two `MediaElementAudioSourceNode`s — all of which live in `player.js` and are never released. There is no `audioCtx.close()`, no `disconnect()` of the filter chain, and no `pagehide`/`beforeunload` teardown for the graph (the only `pagehide` handler, `player.js:1502-1504`, reports the listening state).
- **Cause:** the DSP graph was bolted onto the player module instead of being encapsulated in an object with a lifecycle.
- **Trigger conditions:** app shutdown / re-init.
- **User impact:** minor in a single-window desktop app (the process exit reclaims the audio device), but the audio output device can stay pinned to a `setSinkId` selection, and a future "restart the player" path would leak a context and a second set of source nodes per restart.
- **Evidence:**
  ```js
  // player.js:1502-1504 — the only page-lifecycle hook, and it does not release the graph
  window.addEventListener('pagehide', () => {
      api('report_listening_state', currentTrack?.listening_session, false);
  });
  // visualizer.js:500-519 — destroyVisualizer releases visuals only
  ```
- **Reproduction / verification:** `grep -n "audioCtx.close\|close()\|disconnect()" ui/web_new_v2/js/player.js` → no `AudioContext.close()` anywhere; `grep -n "destroyVisualizer" ui/web_new_v2/js/*.py ui/web_new_v2/js/*.js` → the function is exported but never called by the app.
- **Suggested fix:** give the graph an owner object with `dispose()`; call it from `pagehide` and from `destroyVisualizer`.
- **Fix side effects:** `createMediaElementSource` is irreversible per element, so after a `close()` the elements must be replaced (or the graph re-created), which interacts with the crossfade element pair.
- **Discovered by:** B

---

#### F-WN-29-8  [P3] — `report_position` makes a full JS→Python→JS round trip every 5 s with no consumer on the Python side

- **File:** `ui/web_new_v2/js/player.js:613-616`; `core/api.py:1407-1428`.
- **Confirmed:** yes.
- **Description:** the frontend's `timeupdate` handler calls `api('report_position', currentPosMs, currentDuration, 0, session)` at most every 5 s. On the Python side `report_position` updates the listening session and then **emits the position straight back to the frontend**:
  ```python
  # core/api.py:1423-1428
  self._emit("position_changed", {
      "pos": pos_sec, "duration": dur_sec,
      "position_ms": pos_ms, "duration_ms": duration,
  })
  ```
  which lands in `events.js:110-127` → `player.js:1925-1971` (`onPositionChanged`), where it immediately returns because the element is playing (`1930-1932`). The net effect is one extra UI-thread round trip (through `_emit`'s `EmitWorker`) every 5 s for a value the frontend already owns.
- **Cause:** the frontend is used as the transport's position reporter *and* as the position consumer of the same event; the backend has no need to echo.
- **Trigger conditions:** every 5 s of playback (and on every seek, `player.js:850`).
- **User impact:** small but constant avoidable IPC; it also re-enters `onPositionChanged`, which is a second, differently-scaled writer of `currentDuration` (see F-WN-29-4).
- **Evidence:** quoted above; `player.js:615` `api('report_position', currentPosMs, currentDuration, 0, currentTrack?.listening_session);`
- **Reproduction / verification:** DevTools → Network/console: count `position_changed` events — one every ~5 s while the `position_changed` DOM event never changes anything (the handler returns at `1930`). `grep -n "position_changed" ui/web_new_v2/js/lyrics.js` shows lyrics uses its own local timer instead.
- **Suggested fix:** do not emit `position_changed` from `report_position`; let the backend consume the number (it already does, for `session.tick()` and `_last_reported_position`).
- **Fix side effects:** any other consumer of the `position_changed` bridge event would stop receiving it — check `ui/web_new_v2/js/lyrics.js` and WN-32 before changing.
- **Discovered by:** B

---

#### F-WN-29-9  [P3] — `audioCtx.resume()` is called 24×/s from the visualizer with an unhandled promise rejection

- **File:** `ui/web_new_v2/js/player.js:404-414`; caller `ui/web_new_v2/js/visualizer.js:279`.
- **Confirmed:** yes.
- **Description:** `getAudioFrequencyData()` is invoked once per visualizer frame (24 fps default) and contains
  ```js
  if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
  }
  ```
  The returned promise is neither awaited nor `catch`-ed. If the context stays suspended (see F-WN-29-2), this produces **24 unhandled promise rejections per second** for the whole session, which WebView2 surfaces as console errors.
- **Cause:** a per-frame retry of an async operation whose failure mode is ignored.
- **Trigger conditions:** the visualizer enabled and the AudioContext suspended.
- **User impact:** console noise; in Chromium an unhandled rejection per frame is also measurable overhead.
- **Evidence:** quoted above.
- **Reproduction / verification:** DevTools → Console: filter for "Uncaught (in promise) NotAllowedError: The AudioContext was not allowed to start" — it repeats ~24×/s while the visualizer is on screen.
- **Suggested fix:** attempt `resume()` once per state transition (remember the in-flight promise) and `catch()` it.
- **Fix side effects:** none.
- **Discovered by:** B

---

#### F-WN-29-10  [P3] — The visualizer keeps a 24 fps rAF + canvas work alive while nothing is playing

- **File:** `ui/web_new_v2/js/visualizer.js:330-402` (esp. `348-360`), `235-249`.
- **Confirmed:** yes.
- **Description:** `draw()` re-schedules itself unconditionally while the visualizer is enabled, the document is visible and at least one canvas is on screen — including the *paused* case:
  ```js
  if (!playing) {
      // Ambient idle loop: keep animating gently on pause instead of
      // freezing after a single near-invisible frame.
      animFrameId = requestAnimationFrame(draw);
  }
  ```
  so a paused app keeps a 24 fps loop that runs 48 bars of physics (`updateSimulation`, `262-328`) and repaints up to two canvases every frame. The loop *is* correctly cancelled when the document/window is hidden (`242-249`, `documentVisible`) and when no canvas is visible (`348-351`) — that part is clean.
- **Cause:** an always-on decorative loop with no idle budget.
- **Trigger conditions:** the visualizer visible and playback paused (or stopped).
- **User impact:** constant CPU/GPU wakeups on a paused app; on a laptop on battery this is measurable even though nothing is playing.
- **Evidence:** quoted above; the FPS cap is `targetFps = 24` (`visualizer.js:26`), so it is not a 60 fps problem.
- **Reproduction / verification:** pause playback, DevTools → Performance → record 10 s: a steady 24 fps rAF with 48-bar physics and canvas paints; `window.__vc = 0` instrumentation or the Chromium "Frames" track shows the same rate while paused.
- **Suggested fix:** drop to a low idle cadence (e.g. 6 fps) or a single static frame when `playing === false`, and reuse the existing `efficiency_state` / battery-saver plumbing.
- **Fix side effects:** the ambient idle animation is a deliberate visual choice (the code comments say so); reducing its cadence changes the look on pause.
- **Discovered by:** B

---

#### F-WN-29-11  [P3] — `queue.js` mutates its local queue copy *before* the backend reorder succeeds, so a failed reorder leaves the view and the backend disagreeing

- **File:** `ui/web_new_v2/js/queue.js:279-292`.
- **Confirmed:** yes.
- **Description:**
  ```js
  if (draggedItemIndex !== insertIndex) {
      const movedItem = currentQueue.splice(draggedItemIndex, 1)[0];
      currentQueue.splice(insertIndex, 0, movedItem);      // local copy already mutated
      if (window.pywebview?.api?.reorder_queue) {
          try {
              await window.pywebview.api.reorder_queue(draggedItemIndex, insertIndex);
          } catch(err) {
              console.error('reorder_queue failed:', err);   // <-- local copy NOT rolled back
          } finally {
              await loadQueue();                              // re-syncs on both paths
          }
      }
  }
  ```
  The local array is spliced first and the backend call is awaited afterwards; a rejected `reorder_queue` leaves `currentQueue` (and `window.currentQueue`) in the new order until the `finally` block's `loadQueue()` repairs it. `loadQueue()` does have a generation guard (`76-85`), so the repair is normally reliable — but the window between the failure and the repair is a window in which `window.currentQueue` is wrong, and `player.js:878` reads exactly that global.
- **Cause:** optimistic local mutation before the authoritative call, with the rollback delegated to a later refresh.
- **Trigger conditions:** `reorder_queue` fails (bridge error, backend exception) — the failure is logged and swallowed, so the user sees the row snap back without any message.
- **User impact:** brief UI/backend divergence and a silent failure (no toast), unlike the remove button which does show an error (`queue.js:204-207`).
- **Evidence:** quoted above.
- **Reproduction / verification:** DevTools → stub `window.pywebview.api.reorder_queue = () => Promise.reject(new Error('x'))`, drag a row in the drawer, and watch `window.currentQueue` change while the backend order does not; the row jumps back when `loadQueue()` resolves.
- **Suggested fix:** mutate the local copy only after the bridge call resolves, and surface a toast on failure like the remove path does.
- **Fix side effects:** the drag would feel one round trip slower; alternatively keep the optimistic update but roll it back explicitly on error.
- **Discovered by:** B

---

### 3. Clean areas

Checked and found correct (no finding raised):

- **Rapid-track-switching race — the JS generation token works.** `playbackGeneration` is incremented in `playTrack` (`player.js:708`), `onTrackChanged` (`1635`), `togglePlayPause` (`861`, `910`), `stopFailedPlayback` (`497`) and `stopPlaybackForQueueEnd` (`1830`); the `play()` promise's `then`/`catch` compare the captured generation (`789`, `801`) and the recovery path compares it too (`469`, `474`, `485`). The prefetch callback is guarded by `capturedQueueVer === currentQueueVersion && capturedGeneration === playbackGeneration` (`1436`), and the recovery result is guarded by `recoveryRequest !== request` (`474`, `485`). The late-arriving resolution therefore **cannot** overwrite a newer one. This is pinned by `tests/test_player_recovery_transitions.py::test_skip_discards_a_recovery_result_and_queue_end_releases_both_elements` and `::test_prefetch_callback_after_skip_cannot_load_stale_audio`.
- **The backend also drops stale resolutions.** `core/api.py:1623-1629` (`_is_current`) and `1734-1737` ("user moved on — drop stale resolution") — a resolution that finishes after the user skipped is discarded server-side. (The Python half is WN-05's; the JS half is clean.)
- **The proxy token is never persisted.** It lives only in `window.PROXY_TOKEN` (`main.js:38`, `:54`) — not in `localStorage`, not in the settings DB — and is minted per session (`core/proxy.py:1271-1276`). It does not appear in the address bar (the app is a frameless WebView2 window served from `http://127.0.0.1:<pywebview port>/`, so there is no address bar) and it is not in the `Referer` of the proxy request (the referrer is the page URL). The proxy redacts it in its own log (`core/proxy.py:489`).
- **`crossOrigin` is set correctly and early.** `player.js:83` and `:85` set `crossOrigin = "anonymous"` on both elements at construction, before any `src` is assigned — so the WebAudio `createMediaElementSource` node is not tainted. The proxy does emit the CORS headers the browser needs for a `crossOrigin` media element: `_send_cors_headers` (`core/proxy.py:530-536`) echoes the `Origin` when it is loopback, and the page origin *is* loopback (pywebview serves `index.html` from its own `http://127.0.0.1:<port>` server — `webview/window.py:196-202` sets `real_url` from `server.address`). `Access-Control-Allow-Headers: Range` is present (`proxy.py:619`, `1169`), so range requests survive.
- **HLS / `MediaSource` lifecycle is sound.** `destroyHls()` (`player.js:89-95`) is called from `loadAudioSource` before every new source, from `releaseAudio` (`159`), from the old-element teardown in `playTrack` (`755`) and from `stopPlaybackForQueueEnd` (`1845`). `hls.destroy()` is wrapped in try/catch and `_hls` is nulled, so no per-track `Hls` instance leaks. Pinned by `tests/test_playback_latency_ui.py::test_audio_prefetch_reuses_buffer_and_error_or_teardown_reloads`.
- **The `<audio>` event listeners are attached exactly once.** `setupAudioEvents(audioA)` / `(audioB)` (`player.js:678-679`) plus the `ratechange` loop (`673-677`) run at module evaluation; the elements live for the app's lifetime, so there is no listener accumulation.
- **The rAF loops are properly parked when the app is hidden.** `syncPlayerVisibility` (`player.js:1489-1500`) cancels the progress loop on `visibilitychange` **and** on the bridge's `nedotify:window_visibility_changed` (native minimise), and `animateProgress` refuses to re-create the loop when hidden (`1376-1379`). The orbit-glow loop stops on the same events (`2510-2542`, `2594-2612`). Pinned by `tests/test_player_resources.py::test_hidden_player_parks_frames_resumes_once_and_still_prefetches` and `::test_native_minimize_parks_player_when_webview_visibility_stays_visible`.
- **The progress bar itself is a good rAF implementation.** `animateProgress` throttles to `progressThrottleMs` (default 33 ms), writes `transform` (composited, no layout), and skips `textContent`/`aria-valuenow` writes when the value is unchanged (`1407-1413`). Pinned by `tests/test_player_resources.py::test_progress_updates_only_changed_text_and_accessibility_values_at_full_fps`.
- **The waveform canvas DPR handling does not thrash the backing store.** `sizeCanvasForDpr` (`utils.js:382-398`) only assigns `canvas.width/height` when they actually change, so the context is not reset every frame.
- **The equalizer's async restore is properly revision-guarded.** `equalizer.js:198-211` captures `editRevision` before `get_equalizer()` and discards the response if the user edited meanwhile; `applyEq()` (`331-351`) debounces the backend write by 200 ms and shows a toast on rejection. Pinned by `tests/test_equalizer_controls_ui.py::test_late_equalizer_restore_cannot_overwrite_user_input_and_mode_is_saved`.
- **No XSS in the queue renderer.** `queue.js:159-160` escapes the title and artist, `157` escapes the cover URL, `162` formats a number; `escapeHtml` (`utils.js:17-25`) escapes `& < > " '`. The player's own DOM writes use `textContent` (`player.js:1716`, `1758-1759`) or static SVG.
- **The `api()` wrapper never lets a bridge failure become an unhandled rejection** (`player.js:2113-2125`): every call is `Promise.resolve(...).catch(...)`.
- **The volume RPC is properly throttled** (100 ms, last value wins, flushed on release — `player.js:38-44`, `1186-1193`), so dragging the slider does not flood the bridge.
- **The queue drawer's `loadQueue()` has a request-generation guard** (`queue.js:77`, `81`) so a slow `get_queue` cannot overwrite a newer one.
- **The tests in scope are real behavioural tests, not static greps.** `test_playback_latency_ui.py`, `test_player_recovery_transitions.py`, `test_player_resources.py`, `test_visual_effects_lifecycle.py` and `test_equalizer_controls_ui.py` execute the shipped JS in Node's `vm` against a stub DOM/bridge and assert on observable behaviour (frame counts, DOM writes, ordering, bridge calls). `test_player_layout_geometry.py` is explicitly a CSS-arithmetic guard (it says so in its own docstring) and `test_keybind_contracts.py` is a table-equality guard between `hotkeys.js` and `core/settings.py` — both are legitimate, but they are static by design.

---

### 4. Coverage gaps

- **The "silent app" consequence of F-WN-29-2 could not be confirmed on this machine.** It depends on the WebView2 media-autoplay policy of the shipped runtime. `webview/platforms/edgechromium.py:48-61` sets no autoplay-related flag, so the effective policy is the WebView2 default; I could not determine it from the installed SDK/runtime without launching the app (forbidden by the brief: *"Never run the real app"*). **Missing evidence:** the value of `CoreWebView2Settings.AreMediaAutoplayAllowed` in the target WebView2 runtime, or a DevTools readout of `AudioContext.state` right after `initEqualizer()` completes. **Would confirm:** the finding if the state is `suspended`; would downgrade it to P3 if it is `running`.
- **`initEqualizer()` runs before the first user gesture, but I could not measure whether a gesture has already happened at that point in a real session** (the WebView2 page is created and the bridge is injected asynchronously; `main.js:353-354` starts `init()` after `awaitBridge()`). The code path itself is confirmed; only the runtime ordering of "first click" vs "init" is unverified.
- **The 2711-line `player.js` was read in full but its ~19 responsibilities were not each traced to a test.** I read the in-scope test files; I did not audit the whole `tests/` tree for coverage of e.g. the Flow autopilot (`requestFlowAutoplay`), the mini-player drag path, the marquee `ResizeObserver`, or the magnetic-waveform hover path — those live in other areas' test files (WN-28/WN-34) and are outside this review's file list.
- **`tools/bench` and `tools/visual_guard` were not executed.** The perf findings (F-WN-29-5, F-WN-29-6, F-WN-29-10) are derived from code inspection and from the existing behavioural tests' assertions about frame/write counts; I did not produce a CPU profile of the running app.
- **The exact token-rotation/expiry semantics of the proxy were not audited** — `core/proxy.py` is WN-11's area. I only checked that the token is per-session, is required, and is redacted in the proxy's own request log.
- **I did not verify the `queue_updated`/`track_changed` event *ordering* guarantee** between the `EmitWorker` thread and the WebView2 `evaluate_js` marshalling. The JS-side reasoning in F-WN-29-3 assumes events arrive in emission order; if the backend can reorder them, additional divergence modes exist (that is WN-03's `_emit` contract to own).

---

### 5. Architecture improvements (ARCH)

1. **Split `player.js` (2711 lines, ~19 responsibilities) into modules.** The file currently owns: source loading/normalisation (`97-145`), the dual-element crossfade transport (`82-95`, `155-169`, `698-808`), the Web Audio graph (`316-430`), output-device selection (`183-261`), transport controls (`810-920`, `1035-1219`), position reporting + the render loop (`580-618`, `1341-1422`), stream-error recovery (`432-525`), automatic transition / gapless (`635-641`, `1475-1487`), next-track prefetch (`1424-1466`), the Flow autopilot (`263-312`, `1506-1621`), the waveform engine (`2187-2484`), the orbit glow (`2489-2612`), mini-player wiring (`1035-1117`), the track-options menu (`1221-1303`), MediaSession (`681-696`), the queue-version counter (`54-62`) and the bridge wrapper (`2113-2125`). Suggested seams: `player/transport.js` (state machine), `player/source.js` (proxy URL + HLS), `player/dsp.js` (Web Audio graph), `player/waveform.js` (canvas), `player/flow.js` (autopilot).
2. **Replace the ~20 independent playback flags with one explicit state object + one transition function.** The variables that hold playback state and where they are written: `currentTrack` (744, 1644), `isPlaying` (745, 1681, 1698, 1707, 1856), `currentDuration` (586, 773, 1388, 1656, 1747, 1943), `currentPosMs` (554, 592, 813, 1391, 1646, 1744), `targetPosMs` (555, 814, 1647, 1745, 1950 — **never read**), `isSeeking` (564, 570, 661, 816, 821, 846), `activeAudio` (86, 743), `outgoingAudio` (30, 750, 166), `playbackGeneration` (497, 708, 861, 910, 1635, 1830), `currentQueueVersion` (59, 1570), `preparedNext` (60, 738, 1445), `automaticTransition` (27, 737, 1483), `pendingResume` (436, 774, 1637), `gaplessAdoptionKey` (28, 718, 1633), `recoveryRequest` (24, 471, 498, 709, 1636, 1831), `currentTrackRetries` (433, 459, 456, 593, 721, 906, 1638). A single `PlaybackState {phase, track, positionMs, durationMs, generation}` with one `transition(next)` removes the divergent-write class of bug entirely (F-WN-29-4).
3. **Make the backend the sole owner of the queue and shuffle; the frontend should hold a read-only view model.** Today the frontend keeps `currentQueue`/`window.currentQueue` and sends it back as the authoritative list (`queue.js:182`, `player.js:878`), which is what lets a shuffle toggle desynchronise and then overwrite the backend order (F-WN-29-3). The bridge should accept a track identity, not a queue snapshot.
4. **Move the proxy bearer out of URLs.** `?k=<token>` in query strings is what forces the token into DOM attributes, console logs and the media element's `src`. A `SameSite=Strict` cookie scoped to `127.0.0.1` (or a `fetch()` + `URL.createObjectURL` media pipeline) would remove the token from every renderable surface. This needs a coordinated change in `core/proxy.py` (WN-11) and `core/api.py` (WN-03/WN-05).
5. **Encapsulate the Web Audio graph behind an object with `init(userGesture)` / `dispose()`.** `initAudioContext()` today has four callers, three of which can fire without a gesture, no `close()` path, and a partially-constructed graph would leave the media elements permanently muted (F-WN-29-2, F-WN-29-7).
6. **Cache the CSS-derived values used by the canvas renderer.** `waveColorCache` already exists as the right pattern; `--player-progress-opacity` should join it, and the three waveform canvases should be cached like `_getProgEls()` (F-WN-29-5).
7. **Replace the ad-hoc globals with a typed event bus.** `window.currentQueue`, `window._pendingResolveKey`, `window._lastReportTime`, `window.getIsPlaying`, `window.NeDotify.*` are cross-module back-channels that no module owns; the codebase already has the right primitive (`addPythonEventHandler` in `events.js:37-44`).
8. **Drop the frontend→backend→frontend `position_changed` echo** (F-WN-29-8) and make `report_position` a one-way telemetry call.
9. **Give the queue view a diffing renderer** instead of a full rebuild, and scope `renderIcons` to the rebuilt subtree (F-WN-29-6).
10. **Split `player.js` responsibilities from `visualizer.js`/`equalizer.js` at the DSP boundary.** `visualizer.js` imports `getAudioFrequencyData` from `player.js`, which means the *visual* module is what pulls the *audio* module into the Web Audio graph — the coupling that makes the gesture problem possible (F-WN-29-2). A `dsp.js` module owning the graph would invert the dependency correctly.
