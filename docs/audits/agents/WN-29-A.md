## AREA WN-29 — UI player, equalizer, queue view, visualizer — ROLE A

### 1. Scope reviewed

**Files opened and read in full (physical 1-based lines):**

- `ui/web_new_v2/js/player.js` — 1–2711 (the whole file; the area map's "2489 L" is the
  pre-`Read`-tool count, the file on disk is 2711 physical lines)
- `ui/web_new_v2/js/queue.js` — 1–303
- `ui/web_new_v2/js/equalizer.js` — 1–351
- `ui/web_new_v2/js/visualizer.js` — 1–532

**Callees traced into other areas (read to verify the bridge contract, not reviewed as findings):**

- `core/api.py` — `get_settings` (2922), `set_volume` (1956), `get_volume` (1960),
  `toggle_mute` (1964), `is_muted` (1993), `toggle_shuffle` (2004), `toggle_repeat` (2010),
  `get_next_track` (2016–2075), `get_queue` (1772), `reorder_queue` (1782), `play_next` (1787),
  `add_to_queue` (1797), `add_tracks_to_queue` (1807), `remove_from_queue` (1819),
  `clear_queue` (1838), `play_pause` (1746), `next_track` (1761), `prev_track` (1767),
  `report_state` (1355), `report_position` (1407), `report_listening_state` (1332),
  `play_track` (1437–1759), `_resolve_track` (1608–1759), `recover_stream` (4166),
  `prefetch_track` (3640), `get_flow_tracks` (4110), `get_waveform` (3583),
  `get_equalizer` (3173), `set_equalizer` (3180), `save_setting` (2939),
  `get_playlists` (2513), `add_to_playlist` (2517), `download_track` (2293),
  `minimize_window` (954), `minimize` (949), `close_window` (945), `close` (916),
  `begin_window_drag` (958), `toggle_mini_player` (773), `_enrich_track_lufs` (1161)
- `core/proxy.py` — `AUTH_PARAM` (31), `KNOWN_PROXY_PATHS` (40), `_is_loopback_origin` (102),
  `_safe_stream_local_path` (238–272), `_rewrite_hls_playlist` (396–418),
  `_authorized`/`_authenticate` (491–519), `serve_local_file` (538–590),
  `do_GET` (694–903)
- `core/settings.py` — `DEFAULT_SETTINGS` (dumped via the venv interpreter)
- `audio/engine.py` — 1–508 (`_notify_track_changed` 78–119, `play_track` 35–39,
  `next_track` 55–63)
- `audio/queue.py` — 1–302 (`set_tracks` 119, `remove_track` 173, `move_track` 193,
  `next_track` 215, `toggle_shuffle` 265, `toggle_repeat` 270)
- `ui/web_new_v2/js/events.js` — 90–139, 370–427 (event → player.js wiring)
- `ui/web_new_v2/js/main.js` — 30–55 (proxy info), 172–206 (mini player), 390–429
  (settings application), 515–545 (module init order)
- `ui/web_new_v2/index.html` — 12–19 (script tags), 206/537 (visualizer canvases),
  2300–2304 (queue drawer), 1997 (volume fill)
- `ui/web_new_v2/js/hls.min.js` — bundled HLS.js (384 244 bytes), loaded `<script defer>`

**Not reviewed (out of area / out of scope):** `android/**`; `ui/web_new_v2/js/settings.js`,
`search.js`, `library.js` etc. except the specific call sites quoted above.

---

### 2. Findings

#### F-WN-29-1  [P1] — `applySettings()` reads a flat settings shape the backend never sends: the persisted volume is never restored and the shuffle/repeat buttons show the wrong state on every launch

- **File:** `ui/web_new_v2/js/player.js:1973-1992` (also `ui/web_new_v2/js/main.js:396-418`,
  `ui/web_new_v2/js/onboarding.js:63-67`, `core/api.py:2922` `get_settings`,
  `core/settings.py` `DEFAULT_SETTINGS`)
- **Confirmed:** yes
- **Description:** `applySettings(settings)` reads `settings.volume`, `settings.shuffle` and
  `settings.repeat` as **top-level** keys. The backend's `get_settings()` returns a
  **category-keyed tree** (`{app:{…}, audio:{…}, session:{…}, equalizer:{…}, …}`), so those three
  top-level keys are always `undefined`. Consequences:
  1. `currentVolume` stays at the hard-coded module default `70`. `audio.volume` is written by
     `api('set_volume', …)` on every volume change and persisted in SQLite, but **never read
     back** — the user's volume is silently lost on every restart, and the slider in
     `index.html:1997` is hard-coded `width:70%`.
  2. `settings.repeat !== 'off'` evaluates `undefined !== 'off'` → **true**, so the repeat button
     renders as *active* on startup even when the backend repeat mode is `off`.
  3. `settings.shuffle` is `undefined` → the shuffle button is never shown as active, even when
     shuffle is on.
- **Cause:** the settings DTO shape drifted. `get_settings()` assembles the tree category by
  category; the real locations are `audio.volume`, `session.shuffle`, `session.repeat` (and the
  live shuffle/repeat actually live in the queue, surfaced by `get_queue()`).
- **Trigger conditions:** every application start (`main.js:400` cached settings and
  `main.js:416` fresh settings), and the onboarding path (`onboarding.js:66`, `:185`).
- **User impact:** the volume the user set (e.g. 20 %) is gone after a restart and playback
  starts at 70 %; the repeat button is lit up when repeat is off (and the first click appears to
  do nothing because the backend cycles `off → all` while the button was already lit); the
  shuffle button is never lit even when shuffle is on.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/player.js:1973-1992
  export function applySettings(settings) {
      ...
      if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
      if (ppShuffle) ppShuffle.classList.toggle('active', settings.shuffle);
      if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
      if (ppRepeat) ppRepeat.classList.toggle('active', settings.repeat !== 'off');

      if (settings.volume !== undefined) {
          currentVolume = settings.volume;
      }
      if (volFill) volFill.style.width = `${currentVolume}%`;
      updateVolumeIcon(currentVolume);
  }
  ```
  ```python
  # core/api.py :: get_settings  —  category-keyed tree
  categories = ['app', 'appearance', 'player', 'lyrics', 'system', 'general', 'audio', ...,
                'session', ..., 'equalizer', ...]
  res = {}
  for c in categories:
      cat_data = self._core.settings.get_category(c)
      if cat_data: res[c] = _mask_secrets(c, cat_data)
  return res
  ```
  ```python
  # core/settings.py :: DEFAULT_SETTINGS  (dumped via the venv interpreter)
  "audio":   { ..., "volume": 70, "muted": False }
  "session": { ..., "shuffle": False, "repeat": "off" }
  ```
- **Reproduction / verification:**
  1. Launch the app, drag the bottom-bar volume to ~20 % (this calls
     `api('set_volume', 20)` → `settings.set("audio","volume",20)`).
  2. Quit and relaunch. `applySettings(freshSettings)` runs with the category tree →
     `settings.volume === undefined` → `currentVolume` stays `70` → the slider shows 70 % and
     `playTrack()` (`player.js:782`) sets `newAudio.volume = 0.7`.
  3. Static confirmation: `Select-String` over `ui/web_new_v2/js` shows `currentVolume` is
     assigned in exactly 5 places (`player.js:15`, `1178`, `1188`, `1198`, `1987`) and only
     `1987` reads it from settings — with the wrong key.
- **Suggested fix:** read the nested keys (`settings.audio?.volume`, `settings.session?.shuffle`,
  `settings.session?.repeat`) and clamp the value; better, seed shuffle/repeat from
  `get_queue()` (which carries the live `shuffle`/`repeat` of `audio/queue.py`) instead of the
  persisted `session` snapshot, because `toggle_shuffle`/`toggle_repeat` never write to
  `session.*`.
- **Fix side effects:** none for the volume. For shuffle/repeat, sourcing from `get_queue()`
  introduces an async step at startup — the buttons would be correct only after `get_queue()`
  resolves; keep the current `repeat_changed` / `shuffle_changed` event sync
  (`events.js:288-310`) as the authoritative update.
- **Discovered by:** A

---

#### F-WN-29-2  [P1] — Rapid "next" on an unresolved track makes the frontend call `play_track` without the queue; a late-arriving resolution then replaces the whole queue with one track

- **File:** `ui/web_new_v2/js/player.js:1693-1709` (caller) →
  `core/api.py:1606` + `core/api.py:1631-1637` (callee) → `audio/engine.py:35-39` →
  `audio/queue.py:119-132`
- **Confirmed:** yes (the call chain is fully traced in source; the runtime trigger requires an
  out-of-order async resolution, which is reproducible but timing-dependent)
- **Description:** when a `track_changed` event arrives for a cloud track whose stream is not
  resolved yet (no `stream_url`, no `file_path`), `onTrackChanged` asks the backend to resolve it
  **without passing the queue**:
  ```js
  } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
      // Stream not resolved yet: show loading and request background resolution.
      // Backend keeps the queue intact for the current track.
      ...
      window.pywebview.api.play_track(pendingTrack);
  }
  ```
  On the Python side, `play_track(track)` with no `track_list` takes
  `self._resolve_track(track, lambda t: self._core.engine.play_track(t))`. `_resolve_track`'s
  `_deliver()` then does:
  ```python
  def _deliver():
      if _is_current() and len(self._core.engine.queue.tracks) > 1:
          cur = self._core.engine.queue.current_track
          cur["file_path"] = track.get("file_path")
          self._core.engine._notify_track_changed()
      else:
          play_callback(track)     # -> engine.play_track(t) -> queue.set_tracks([t], 0)
  ```
  `engine.play_track(t)` → `queue.set_tracks([track], start_index=0)` → `self._tracks = [track]`,
  i.e. **the entire user queue is replaced by the single stale track**, and
  `_notify_track_changed()` switches playback back to it.
  The `else` branch is taken exactly when the resolved track is no longer the current queue
  track — i.e. when the user moved on while the resolution was in flight.
- **Cause:** the caller does not pass the queue, so the backend has no way to know that the
  resolved track belongs to a larger queue and falls back to the "solo" delivery path, which
  *is* destructive. The comment "Backend keeps the queue intact for the current track" is true
  only while the track is still current.
- **Trigger conditions:** the user clicks **Next** (or the track auto-advances) while the
  current track is still resolving, and then advances again before the first resolution
  completes. This is exactly the "rapid track switching" scenario. The window is the resolution
  latency (seconds for a cold cloud stream).
- **User impact:** the 20-track queue the user built is destroyed and reduced to one track;
  playback jumps *backwards* to the intermediate track, then to the last one. The user has no
  way to recover the lost queue, and the queue drawer silently shows a single row.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/player.js:1700-1705
  const resolveKey = String(track.source) + '|' + String(track.source_id);
  if (window._pendingResolveKey !== resolveKey) {
      window._pendingResolveKey = resolveKey;
      const pendingTrack = { ...track, file_path: undefined, stream_url: undefined };
      window.pywebview.api.play_track(pendingTrack);      // <-- no queue, no index
  }
  ```
  ```python
  # audio/engine.py:35-39
  def play_track(self, track: dict) -> None:
      if not track:
          return None
      self.queue.set_tracks([track], start_index=0)   # <-- queue replaced by one track
      self._notify_track_changed()
  ```
  ```python
  # audio/queue.py:119-124
  def set_tracks(self, tracks: list, start_index: int = 0):
      with self._lock:
          self._tracks = tracks.copy()
          self._original_order = tracks.copy()
          self._current_index = max(0, min(start_index, len(tracks) - 1)) if tracks else -1
  ```
  Note the contrast with the *correct* call in the same file: `player.js:880`
  `window.pywebview.api.play_track(currentTrack, q, findQueueIndex(q, currentTrack));` — the
  queue-aware form.
- **Reproduction / verification:**
  1. Build a queue of ≥ 5 **cloud** tracks (YouTube/SoundCloud, not cached locally) and start
     playback.
  2. Press **Next** and then press **Next** again within the resolution window (1–5 s) of the
     first new track.
  3. When the first resolution lands, `~/.nedotify/logs/app.log` shows
     `api.py -> play_track called! … has_track_list=False`, followed by the queue collapsing:
     the drawer (`nedotify:queue_updated`) shows 1 row, and the `queue_ended`/`track_changed`
     sequence jumps back to the intermediate track.
  4. Static confirmation: `core/api.py:1631-1637` `else: play_callback(track)` →
     `audio/engine.py:38` `set_tracks([track], 0)`.
- **Suggested fix:** pass the queue and the index, exactly like `player.js:880` does:
  `api('play_track', pendingTrack, window.currentQueue, findQueueIndex(window.currentQueue, currentTrack))`;
  and/or make the backend's `_deliver()` non-destructive when the track belongs to a queue that
  is still alive (that callee defect belongs to **WN-05** — `core/api.py::_resolve_track._deliver`
  — and is reported there; this finding is only the caller's misuse).
- **Fix side effects:** passing the queue means the backend's `play_track` fast path
  (`core/api.py:1473-1580`) may resolve the *whole* list rather than one track — that path
  already exists and is used by the queue drawer, so behaviour should be equivalent. Guard
  against re-entering `onTrackChanged` for a track that is no longer current.
- **Discovered by:** A

---

#### F-WN-29-3  [P2] — HLS detection only inspects the `url` query parameter, so a proxied HLS playlist handed over in the `/api/stream?track_id=…` form is fed to `<audio src>` (WebView2 has no native HLS support)

- **File:** `ui/web_new_v2/js/player.js:119-145`; URL forms produced by
  `audio/engine.py:88-105` and `core/api.py:2061-2071`
- **Confirmed:** the detection logic — **yes**; the runtime impact — **hypothesis** (no provider
  currently returns an `.m3u8`; see coverage gaps)
- **Description:** `loadAudioSource` decides "this is HLS" by unwrapping the proxy URL:
  ```js
  let mediaUrl = src;
  try { mediaUrl = new URL(src, window.location.href).searchParams.get('url') || src; } catch (e) {}
  const isHls = typeof mediaUrl === 'string' && (mediaUrl.includes('.m3u8') ||
               mediaUrl.includes('/playlist') || mediaUrl.includes('format=m3u8'));
  ```
  The backend emits **two** proxy URL shapes:
  * `http://127.0.0.1:<port>/?url=<encoded upstream>&source=…&k=…` — the upstream URL *is*
    exposed, so the detection works;
  * `http://127.0.0.1:<port>/api/stream?track_id=…&source=…&source_id=…&title=…&artist=…&k=…`
    — the upstream URL is **not** exposed, so `searchParams.get('url')` is `null`, `mediaUrl`
    falls back to the proxy URL, `isHls` is `false`, and the playlist is assigned to
    `audioEl.src`.
  The `/api/stream` form is used by `audio/engine.py:95` for any upstream whose host contains
  `youtube.com`, `youtu.be`, `soundcloud.com` or `music.yandex.ru` — exactly the providers that
  are allowed to be HLS. Chromium/WebView2 has **no native HLS support**, so `<audio src="…m3u8">`
  fails: the `error` event fires → `handleStreamError` → 2 retries → `stopFailedPlayback` and a
  toast ("Не удалось восстановить «…»"), i.e. the track is unplayable.
- **Cause:** the HLS decision is made on the *frontend-visible* URL instead of on a
  server-side signal (the proxy already knows the upstream `Content-Type` — `core/proxy.py`
  has `_rewrite_hls_playlist()` and `_ext_for_response()`).
- **Trigger conditions:** a provider resolves to an `.m3u8` (or a URL containing `/playlist`)
  on a `youtube.com` / `youtu.be` / `soundcloud.com` / `music.yandex.ru` host.
- **User impact:** the track never plays; the user sees a recovery-failure toast after ~4.5 s
  instead of the track starting. Because the bundled `hls.min.js` (384 KB) *is* loaded and the
  HLS branch *is* implemented, the failure looks like a provider outage rather than a routing
  bug.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/player.js:119-123
  let mediaUrl = src;
  try { mediaUrl = new URL(src, window.location.href).searchParams.get('url') || src; } catch (e) {}
  const isHls = typeof mediaUrl === 'string' && (mediaUrl.includes('.m3u8') ||
               mediaUrl.includes('/playlist') || mediaUrl.includes('format=m3u8'));
  if (isHls && window.Hls && window.Hls.isSupported()) {
  ```
  ```python
  # audio/engine.py:95-104
  if not any(d in fp for d in ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru")):
      quoted_url = urllib_parse.quote(fp)
      proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}" ...)
  else:
      proxy_url = (f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}" ...)
  ```
- **Reproduction / verification:**
  1. Confirm the two URL shapes: `core/api.py:2069` builds
     `/api/stream?track_id=…` (no `url` param) and `audio/engine.py:97` builds
     `/?url=…` (with `url` param).
  2. Feed `loadAudioSource` either shape with an upstream that ends in `.m3u8`:
     `new URL('http://127.0.0.1:1/api/stream?track_id=5&source=soundcloud&k=t').searchParams.get('url')`
     → `null` → `isHls === false` → `audioEl.src = <playlist URL>` → Chromium fires `error`
     (MEDIA_ERR_SRC_NOT_SUPPORTED).
  3. To confirm the live impact, point a provider at an `.m3u8` upstream on a
     `soundcloud.com` host and observe that `audioEl._hls` stays `null` in the WebView console.
- **Suggested fix:** don't infer HLS from the URL shape. Either (a) always route through the
  proxy's generic endpoint `/?url=…` so the upstream URL is visible, or (b) have the backend
  tell the frontend the media kind (e.g. add `"is_hls": True` to the `track_changed` payload /
  `get_next_track()` result) and branch on that.
- **Fix side effects:** (a) changes the proxy URL shape for the YouTube/SoundCloud/Yandex path
  and would move the provider-credential logic in `core/proxy.py` (`_host_allows_credentials`)
  onto the `?url=` branch — that is WN-11's area and needs its own review. (b) requires a
  payload change in WN-05/WX-01.
- **Discovered by:** A

---

#### F-WN-29-4  [P3] — `seekTo()` does not clamp the target to `[0, duration]` before assigning `currentTime` and before reporting the position

- **File:** `ui/web_new_v2/js/player.js:810-851` (assignment at 841-847, RPC at 850);
  caller `ui/web_new_v2/js/lyrics.js:966`
- **Confirmed:** yes
- **Description:** `seekTo(posMs)` clamps the *UI* percentage
  (`Math.max(0, Math.min(100, (posMs / currentDuration) * 100))`, line 826) but then assigns the
  raw value:
  ```js
  if (activeAudio) {
      try {
          activeAudio.currentTime = posMs / 1000;
      } catch (e) {
          console.error("Error seeking audio:", e);
          isSeeking = false;
      }
  }
  api('report_position', posMs, currentDuration);
  ```
  `posMs` is not clamped to `[0, currentDuration]`. `lyrics.js:966` calls
  `seekTo(line.timeMs)` with a lyric timestamp that can exceed the real track duration (stale
  lyrics, a different/longer track, or an LRC from another provider).
- **Cause:** the clamp was applied to the visual representation only, not to the value that is
  written into the media element and reported to the backend.
- **Trigger conditions:** clicking a lyric line whose timestamp is past the end of the loaded
  media; a stale `session_autoplay` position (`events.js:425`).
- **User impact:** Chromium clamps the actual seek to the seekable range, so playback does not
  break — but the backend is told a position past the end of the track
  (`api('report_position', posMs, currentDuration)`), which pollutes the listening session
  (`core/listening.py`) and the "listening comparison" statistics. If the media is not seekable
  yet (`readyState < 1`), the assignment throws `InvalidStateError`, which is caught and logged
  as `console.error("Error seeking audio: …")` — a console error, not a user-visible message.
- **Evidence:** see the quote above; `player.js:826` shows the clamp exists only for the UI.
- **Reproduction / verification:** play a 60 s track, then open lyrics and click a line stamped
  at 3:10; in the WebView console observe `report_position` carrying `pos = 190000` while
  `duration = 60000`.
- **Suggested fix:** clamp once at the top of `seekTo`:
  `const target = Math.max(0, Math.min(currentDuration || Infinity, posMs));` and use `target`
  for both the assignment and the RPC.
- **Fix side effects:** none; the clamp only affects out-of-range targets, which are already
  clamped by the UA.
- **Discovered by:** A

---

#### F-WN-29-5  [P3] — A track that cannot be played at all (local source, missing file, no stream) fails silently

- **File:** `ui/web_new_v2/js/player.js:1693-1709`
- **Confirmed:** yes
- **Description:** the final `else` of `onTrackChanged`:
  ```js
  } else {
      isPlaying = false;
      onStateChanged('paused');
  }
  ```
  No toast, no `nedotify:operation_error` event, no diagnostic. The track title updates to the
  new track, the play button flips to "paused", and nothing tells the user why. This is exactly
  the "the failure mode here is silence" case from `AGENTS.md`.
- **Cause:** the error-reporting path exists for stream errors (`handleStreamError` →
  `stopFailedPlayback` → toast, `player.js:496-508`) but is not reachable for a track that never
  gets a source at all.
- **Trigger conditions:** a `local` track whose file was moved/deleted, an imported track with
  no `source_id`, or a track whose `source` is empty.
- **User impact:** the user clicks a library item and *nothing* happens except the title
  changing — indistinguishable from a UI freeze. (The backend does emit `audio_error` for the
  `source == "local"` case at `core/api.py:1574-1576`, but only when `play_track` was called
  with a `track_list`; the `onTrackChanged` path reaches the silent `else` first.)
- **Evidence:** the quoted `else` branch; compare `stopFailedPlayback` (`player.js:496-508`)
  which does dispatch a toast.
- **Reproduction / verification:** import a local file, delete it from disk, then click it in
  the library → the title changes, the player stays paused, no toast is shown.
- **Suggested fix:** raise the same user-visible error the rest of the player uses (e.g. call
  `stopFailedPlayback('Файл трека не найден')` or dispatch `nedotify:operation_error`).
- **Fix side effects:** none; it only adds a message.
- **Discovered by:** A

---

#### F-WN-29-6  [P3] — The equalizer band-count mode (3/6/10) is never restored from the backend: `get_equalizer()` does not return a `mode` key

- **File:** `ui/web_new_v2/js/equalizer.js:192-195` and `:314-319`;
  `core/api.py:3173-3178`
- **Confirmed:** yes
- **Description:** `restoreEq` expects `data.mode`:
  ```js
  function restoreEq(data) {
      const gain = value => Math.max(-20,Math.min(20,Number(value)||0));
      eqPreamp=gain(data.preamp);
      eqBands=Array.from({length:10},(_,index)=>gain(data.bands?.[index]));
      if(BAND_CONFIGS[data.mode])currentEqMode=Number(data.mode);
  }
  ```
  but the bridge method only returns preamp and bands:
  ```python
  def get_equalizer(self):
      return {
          "preamp": self._core.settings.get("equalizer", "preamp", 0),
          "bands": self._core.settings.get("equalizer", "bands", [0] * 10)
      }
  ```
  The mode is persisted separately under `equalizer.mode` via
  `api.save_setting('mode', currentEqMode, 'equalizer')` (`equalizer.js:345`) and is read back
  only from `window.settings?.equalizer?.mode` (`equalizer.js:192`). `window.settings` is the
  category tree from `get_settings()`, and `DEFAULT_SETTINGS["equalizer"]` contains only
  `preamp` and `bands` — `mode` exists only after the user has changed it at least once.
  `main.js` **never awaits `window.nedotifySettingsReady`** before `initEqualizer()`
  (`main.js:409` creates the promise; `main.js:543` runs `initEqualizer()`), so on a cold start
  with no `nedotify_cached_settings` in localStorage, `window.settings` is still `undefined`
  when `initEqualizer()` runs → the mode silently falls back to 3.
- **Cause:** the mode was written through a different channel (`save_setting`) than the one it
  is read from (`get_equalizer`), and neither the bridge payload nor `DEFAULT_SETTINGS`
  declares it.
- **Trigger conditions:** cold start with an empty localStorage cache, or a user who selected
  6/10 bands on a previous run.
- **User impact:** the equalizer reopens with 3 bands instead of the chosen 6/10, and the
  per-band sliders show the 3-band grouping — the saved curve is still applied to the audio
  graph (all 10 bands are restored) but the UI misrepresents it, and moving a slider in 3-band
  mode overwrites several of the 10 stored gains at once.
- **Evidence:** quoted above; plus `core/settings.py` `DEFAULT_SETTINGS` dump:
  `"equalizer": {"preamp": 0.0, "bands": [0]*10}` — no `mode`.
- **Reproduction / verification:** select the 10-band mode, quit, clear
  `localStorage['nedotify_cached_settings']` (or start with a fresh profile), relaunch and
  open the equalizer → 3 bands are shown.
- **Suggested fix:** return the mode from the bridge (`get_equalizer()` →
  `{"preamp":…, "bands":…, "mode": settings.get("equalizer","mode",3)}`) and/or add
  `"mode": 3` to `DEFAULT_SETTINGS["equalizer"]`; and make `initEqualizer()` await
  `window.nedotifySettingsReady` (or re-read `window.settings` when it resolves).
- **Fix side effects:** adding `mode` to `get_equalizer()` changes the bridge payload — WN-08
  owns that method and should be aligned; the JS side already tolerates a missing `mode`.
- **Discovered by:** A

---

#### F-WN-29-7  [P3] — `queue.js` removes a row by an index captured at render time; a stale index removes the wrong track

- **File:** `ui/web_new_v2/js/queue.js:189-222` (index captured at 144/148, used at 203)
- **Confirmed:** yes (code path); the runtime window is narrow
- **Description:** the remove handler closes over the row's render-time index and sends it
  straight to the backend:
  ```js
  item.addEventListener('click', async (e) => {
      e.stopPropagation();
      ...
      if (index === currentIndex) { showToast('Нельзя удалить текущий трек', 'warning'); return; }
      ...
      const res = await window.pywebview.api.remove_from_queue(index);
  ```
  `core/api.py::remove_from_queue` validates only the range and the "not the current track"
  condition, then removes whatever sits at that index:
  ```python
  if not (0 <= index < len(queue.tracks)):
      return {"success": False, "error": "Неверный индекс очереди"}
  if index == queue._current_index:
      return {"success": False, "error": "Cannot remove current track"}
  queue.remove_track(index)
  ```
  So a stale index removes a **different** track and reports success.
- **Cause:** index-based addressing with no re-validation against the track identity the row
  was rendered for (the row keeps `item._trackData = track` at `queue.js:146` but never uses it
  for the removal).
- **Trigger conditions:** the backend queue changes between the last render and the click —
  e.g. the Flow/autoplay feature appends tracks (`add_tracks_to_queue`), a download completes,
  or the user removes a row in another view — while the `queue_updated` event is still in
  flight to the WebView.
- **User impact:** the wrong track disappears from the queue with no confirmation; the user's
  intended track stays. The queue drawer is the only place where a destructive action has no
  confirmation dialog.
- **Evidence:** quoted above; `core/api.py:1819-1833` for the backend contract.
- **Reproduction / verification:** open the queue drawer, then trigger a queue mutation from
  another surface (e.g. enable Flow/autoplay so `add_tracks_to_queue` appends rows) and click
  the × on a row before the `queue_updated` event is rendered — the row above/below is removed.
  Static check: `item._trackData` is assigned at `queue.js:146` and never read.
- **Suggested fix:** re-read the queue and resolve the target by identity
  (`item._trackData.source_id` / `id` / title+artist) instead of by index before calling
  `remove_from_queue`, or have the backend accept a track key.
- **Fix side effects:** an extra `get_queue()` round-trip per removal, or a new bridge method
  (WN-05/WN-07).
- **Discovered by:** A

---

#### F-WN-29-8  [P3] — A failed queue reorder is swallowed: the rows snap back with no message

- **File:** `ui/web_new_v2/js/queue.js:283-291`
- **Confirmed:** yes
- **Description:**
  ```js
  if (window.pywebview?.api?.reorder_queue) {
      try {
          await window.pywebview.api.reorder_queue(draggedItemIndex, insertIndex);
      } catch(err) {
          console.error('reorder_queue failed:', err);
      } finally {
          await loadQueue();
      }
  }
  ```
  `core/api.py::reorder_queue` returns `None` and never raises; `audio/queue.py::move_track`
  silently ignores an out-of-range index (`if 0 <= old_index < len(...) and 0 <= new_index < len(...)`),
  so a rejected reorder is indistinguishable from a successful one at the bridge level. The
  catch only fires on a transport failure.
- **Cause:** the bridge method has no success/failure result, so the caller cannot tell.
- **Trigger conditions:** the queue changed between the render and the drop (same race as
  F-WN-29-7), or the bridge call fails.
- **User impact:** the dragged row jumps back to its old position and the user gets no
  explanation — the app looks broken rather than the operation having been refused.
- **Evidence:** quoted above; `core/api.py:1782-1785`:
  ```python
  def reorder_queue(self, old_index: int, new_index: int):
      self._core.engine.queue.move_track(old_index, new_index)
      self._emit("queue_updated", self.get_queue())
  ```
- **Reproduction / verification:** drag a row in the queue drawer while the queue is being
  mutated elsewhere; observe `console.error('reorder_queue failed:', …)` or a silent snap-back
  with no toast.
- **Suggested fix:** have `reorder_queue` return `{"success": bool, "error": str}` (WN-05 owns
  the method) and surface the failure with `showToast`, consistent with
  `remove_from_queue` (`queue.js:204-207`), which already does this.
- **Fix side effects:** a bridge payload change in WN-05.
- **Discovered by:** A

---

#### F-WN-29-9  [P3] — If `initAudioContext()` fails half-way, the media element is routed into an unconnected AudioContext → total silence

- **File:** `ui/web_new_v2/js/player.js:325-384` (specifically 370-381)
- **Confirmed:** yes (the code path); the trigger is an unlikely API failure
- **Description:** the graph is built before the media elements are attached, but the
  `connect()` calls come **after** both `createMediaElementSource()` calls:
  ```js
  if (!mediaSourcesCreated) {
      srcA = audioCtx.createMediaElementSource(audioA);
      srcB = audioCtx.createMediaElementSource(audioB);   // <-- if this throws...
      mediaSourcesCreated = true;
  }
  if (srcA) srcA.connect(preampNode);                    // <-- ...this never runs
  if (srcB) srcB.connect(preampNode);
  ...
  } catch(e) {
      console.error("AudioContext initialization failed:", e);
  }
  ```
  Once `createMediaElementSource(el)` succeeds, the element's output is diverted into the
  `AudioContext`; if the context is never connected to `audioCtx.destination`, the element
  produces **no audible output at all**. The `catch` swallows the error into a `console.error`
  and leaves the app in that state.
- **Cause:** the graph is assembled in an order where a mid-way throw leaves the media element
  captured but disconnected, and the failure is not surfaced or rolled back.
- **Trigger conditions:** `createMediaElementSource` throwing (an element already bound to a
  different `AudioContext`, or a WebView2 quirk). The context is created lazily by the
  visualizer (`getAudioFrequencyData`) or the equalizer (`setEq`), so the failure can happen at
  an arbitrary point in the session, including while a track is playing.
- **User impact:** complete silence with no user-visible error — the strongest possible
  manifestation of the "failure mode is silence" rule.
- **Evidence:** quoted above; `player.js:404-414` (`getAudioFrequencyData`) and
  `player.js:416-430` (`setEq`) are the two lazy entry points that can trigger the creation.
- **Reproduction / verification:** instrument `AudioContext.prototype.createMediaElementSource`
  to throw on the second call in the WebView console, then trigger the visualizer
  (`getAudioFrequencyData`) → the console shows
  `AudioContext initialization failed: …` and audio is inaudible while the UI still shows
  "playing".
- **Suggested fix:** wrap each `createMediaElementSource` in its own try/catch and connect
  whatever succeeded; on total failure, close the context and fall back to direct element
  output (do not leave the element captured), and surface the failure to the user.
- **Fix side effects:** an element that has already been captured by an `AudioContext` cannot
  be "un-captured" — recovery requires recreating the `Audio` element, so the fallback must
  rebuild the element or accept the silence.
- **Discovered by:** A

---

#### F-WN-29-10  [P3] — `normalizeAudioSourceUrl` does not recognise UNC paths, so a local track on a network share is loaded as a bogus relative URL

- **File:** `ui/web_new_v2/js/player.js:97-103`; `core/proxy.py:253-255`
- **Confirmed:** yes
- **Description:**
  ```js
  function normalizeAudioSourceUrl(src) {
      if (typeof src === 'string' && (src.match(/^[a-zA-Z]:[\\/]/) || src.startsWith('file://')) && window.PROXY_PORT) {
          const tokenQuery = window.PROXY_TOKEN ? `&k=${encodeURIComponent(window.PROXY_TOKEN)}` : '';
          return `http://127.0.0.1:${window.PROXY_PORT}/api/stream?url=${encodeURIComponent(src)}${tokenQuery}`;
      }
      return src;
  }
  ```
  A UNC path (`\\server\share\track.mp3`) matches neither `^[a-zA-Z]:[\\/]` nor `file://`, so it
  is returned unchanged and assigned to `audioEl.src`. The browser then resolves it as a
  *relative* URL against the app origin, producing a 404 from the pywebview HTTP server. The
  proxy would have refused it anyway (`core/proxy.py:253`: "Refused /api/stream read of
  UNC/file-URL path"), so the correct behaviour is an explicit error, not a bogus URL.
- **Cause:** the path classifier covers drive-letter paths and `file://` URLs but not UNC.
- **Trigger conditions:** an imported local track located on a `\\host\share\…` path.
- **User impact:** a confusing 404 → `handleStreamError` → 2 retries → a recovery-failure toast
  naming the track, rather than "network path not supported".
- **Evidence:** quoted above + `core/proxy.py:252-255`.
- **Reproduction / verification:** import a file from `\\NAS\music\x.mp3` and play it; in the
  WebView network panel the request goes to the *app* origin with an encoded backslash path,
  not to `127.0.0.1:<proxy port>`.
- **Suggested fix:** classify `\\` and `//` prefixes explicitly and route them to a
  user-visible "unsupported network path" error rather than to `audioEl.src`.
- **Fix side effects:** none; UNC playback is refused by the proxy either way.
- **Discovered by:** A

---

### 3. Clean areas

* **Bridge-method cross-check — every method called from these four files exists in
  `core/api.py`.** No call to a non-existent method (no silent `TypeError` at runtime). The
  full list, with the Python definition site:

  | JS call site(s) | Python definition | Result |
  |---|---|---|
  | `player.js:42` `set_volume` | `core/api.py:1956` | OK |
  | `player.js:235`, `equalizer.js:345`, `visualizer.js:71-72` `save_setting` | `core/api.py:2939` | OK |
  | `player.js:473` `recover_stream` | `core/api.py:4166` | OK |
  | `player.js:532/537/544/565/572/623/633/660/675/1003/1503/1672` `report_listening_state` | `core/api.py:1332` | OK |
  | `player.js:543/623/1671` `report_state` | `core/api.py:1355` | OK |
  | `player.js:615/850` `report_position` | `core/api.py:1407` | OK |
  | `player.js:646/652/694/934/971/1017/1048/1584/1602` `next_track` | `core/api.py:1761` | OK |
  | `player.js:691-694` `play_pause` | `core/api.py:1746` | OK |
  | `player.js:693/935/972/1052` `prev_track` | `core/api.py:1767` | OK |
  | `player.js:698/880/890/892/895/898/1704` `play_track` | `core/api.py:1437` | OK |
  | `player.js:882/1583/1599/1600` `get_queue` | `core/api.py:1772` | OK |
  | `player.js:938/975` `toggle_shuffle` | `core/api.py:2004` | OK |
  | `player.js:945/981` `toggle_repeat` | `core/api.py:2010` | OK |
  | `player.js:955/990/1024` `toggle_favorite` | `core/api.py:2614` | OK |
  | `player.js:1212` `toggle_mute` | `core/api.py:1964` | OK |
  | `player.js:1218` `is_muted` | `core/api.py:1993` | OK |
  | `player.js:1248` `get_playlists` | `core/api.py:2513` | OK |
  | `player.js:1257` `add_to_playlist` | `core/api.py:2517` | OK |
  | `player.js:1073/1075` `minimize_window`/`minimize` | `core/api.py:954` / `949` | OK |
  | `player.js:1091/1093` `close_window`/`close` | `core/api.py:945` / `916` | OK |
  | `player.js:1105` `begin_window_drag` | `core/api.py:958` | OK |
  | `player.js:1435` `get_next_track` | `core/api.py:2016` | OK |
  | `player.js:1441` `prefetch_track` | `core/api.py:3640` | OK |
  | `player.js:1553` `get_flow_tracks` | `core/api.py:4110` | OK |
  | `player.js:1573` `add_tracks_to_queue` | `core/api.py:1807` | OK |
  | `player.js:1582` `add_to_queue` | `core/api.py:1797` | OK |
  | `player.js:2274` `get_waveform` | `core/api.py:3583` | OK |
  | `player.js:2018` `download_track` | `core/api.py:2293` | OK |
  | `queue.js:107` `clear_queue` | `core/api.py:1838` | OK |
  | `queue.js:118/203` `remove_from_queue` | `core/api.py:1819` | OK |
  | `queue.js:285` `reorder_queue` | `core/api.py:1782` | OK |
  | `equalizer.js:201` `get_equalizer` | `core/api.py:3173` | OK (missing `mode` key — F-WN-29-6) |
  | `equalizer.js:345` `set_equalizer` | `core/api.py:3180` | OK |

  Argument arity/meaning also matches on every call: `report_position(pos_ms, dur_ms,
  duration_ms, listening_session)`, `report_listening_state(session, audible, ended,
  duration_sec, playback_rate)`, `report_state(state, elapsed_ms, listening_session)`,
  `recover_stream(track, position_ms)`, `set_equalizer(preamp, bands)`, `get_flow_tracks(seed,
  limit, exclude_ids)`, `prefetch_track(track_data)`, `add_to_playlist(playlist_id,
  track_data)`, `save_setting(key, value, category)`.

* **Fields read by the JS that Python does send:** `get_queue()` → `tracks`, `current_index`,
  `current_track`, `shuffle`, `repeat` (all present); `track_changed` → `stream_url`,
  `listening_session`, `loudness_lufs`/`lufs`, `duration`, `file_path`, `source`, `source_id`,
  `id` (all present — `listening_session` is stamped at `core/api.py:1287`,
  `loudness_lufs` by `_enrich_track_lufs`). The **only** missing field found is
  `equalizer.mode` (F-WN-29-6).

* **Shuffle / repeat mode strings match exactly** across the three layers:
  * `audio/queue.py:272` — `modes = ["off", "all", "one"]`
  * `core/api.py:2010-2014` — `def toggle_repeat(self): mode = self._core.engine.toggle_repeat(); … return mode`
  * `ui/web_new_v2/js/player.js:2022-2030` — `if (mode === 'one') … else …`, and
    `player.js:946/982` — `mode !== 'off'`.
  `core/api.py:2013` also emits `repeat_changed {"state": mode}` and
  `core/api.py:2007` emits `shuffle_changed {"state": enabled}`; `events.js:288-310` maps them
  onto the same button classes and the same `repeat-1`/`repeat` icon, so the icon convention is
  consistent across the bridge and the UI. `updateRepeatIcon` (`player.js:2022`) and
  `events.js:453` (`syncRepeatIcon`) are duplicated implementations that agree.

* **The `<audio>` event surface is complete and correctly guarded.** Every event that
  `setupAudioEvents` (`player.js:527-672`) registers is handled:
  `loadstart`, `stalled`, `waiting`, `playing`, `canplay`, `loadedmetadata`, `progress`,
  `seeking`, `seeked`, `timeupdate`, `pause`, `ended`, `error`, plus `ratechange`
  (`player.js:673-677`). All of them except `error`/`timeupdate` are guarded by
  `audio === activeAudio`, so the inactive crossfade element cannot corrupt the active
  track's state.

* **`ended` cannot double-advance the queue.** The handler bails on
  `if (automaticTransition) return;` (crossfade already advanced) and, decisively, on
  `if (audio === activeAudio)`. During a crossfade the outgoing element is swapped out
  (`activeAudio` becomes the new element) and `releaseAudio()` → `audio.pause()` prevents the
  outgoing element from ever reaching `ended`. The `ended` handler therefore runs at most
  once per track.

* **`timeupdate` is throttled correctly.** `timeupdate` fires ≈4×/s but the bridge RPC is
  throttled to **one `report_position` per 5 s** (`player.js:612-616`,
  `now - (window._lastReportTime || 0) > 5000`) — not a bridge round-trip per tick. The
  smooth UI is driven by the separate rAF loop `animateProgress` (`player.js:1371-1422`) with
  an explicit FPS throttle (`progressThrottleMs`, `player.js:1357`, `setUiFps`) and cached DOM
  nodes (`_getProgEls`, `player.js:1345`), so the per-tick DOM cost is negligible.

* **The proxy token is handled correctly.** `normalizeAudioSourceUrl` appends
  `&k=<token>` (`player.js:99`) using the same `AUTH_PARAM = 'k'` the proxy verifies
  (`core/proxy.py:31`, `_authorized` at 491-511) and `window.PROXY_TOKEN` is populated from
  `get_proxy_info()` (`main.js:34-38`, `main.js:50-54`). The proxy **fails closed** when the
  token is unset (`core/proxy.py:503-506`) and **redacts** it in its own logs
  (`core/proxy.py:489`). The token does appear in the `audio.src` attribute and in the WebView
  DevTools network panel, which is inherent to the query-parameter design used for covers and
  avatars as well (`utils.js:626-628`) — noted, not reported as a defect.

* **HLS lifecycle is correct where it is reached.** `destroyHls()` (`player.js:89-95`) calls
  `hls.destroy()` (which detaches the `MediaSource`) and is called on every source change
  (`player.js:115`), on release (`player.js:159`), on track switch (`player.js:755`), on
  prefetch failure (`player.js:1451`) and on queue end (`player.js:1845`). `hls.min.js` is
  bundled (`ui/web_new_v2/js/hls.min.js`, 384 KB) and loaded before the modules
  (`index.html:19`, `defer`; the module entry point is at `index.html:2308`). The
  MediaSource is not left attached. (The *detection* gap is F-WN-29-3.)

* **The crossfade setting is implemented, not dead.** `audio.crossfade_enabled` /
  `audio.crossfade_duration_sec` exist in `core/settings.py::DEFAULT_SETTINGS` (both present,
  default `false` / `3`) and are read through `audioSetting()` (`player.js:175-181`, which reads
  `window.settings.audio.<key>` — the correct nested path, unlike F-WN-29-1).
  `checkAutomaticTransition` (`player.js:1475-1487`) fires `next_track()` exactly `duration`
  seconds before the end; `playTrack` (`player.js:732-799`) then keeps the outgoing element
  alive as `outgoingAudio`, ramps it down with `Math.cos(fraction*π/2)` while ramping the new
  one up with `Math.sin(fraction*π/2)`, and `finishFade()` releases the old element. The
  crossfade also needs `preparedNext` (the prefetch), which requires `get_next_track()` to
  return a `stream_url` — it does (`core/api.py:2061-2071` builds a proxy URL even for an
  unresolved cloud track). A/B-tested path confirmed by the code, not by running the app.

* **Volume / mute handling is sound apart from F-WN-29-1.** The volume is clamped to
  `[0, 100]` in `adjustVolume` (`player.js:1198`) and to `[0, 1]` at the element level
  (`player.js:172`, `782`, `1181`, `1189`, `1201`, `2036`). Muting does **not** destroy the
  previous volume: `applyMuteState` (`player.js:2032-2040`) keeps `currentVolume` intact and
  only sets the element's `muted` property and `volume` to 0, so unmuting restores the
  previous level. The persisted mute flag is owned by the backend (`audio.muted`) and is read
  on start (`player.js:1216-1219` → `is_muted()`), and `mute_changed` keeps the UI in sync
  (`events.js:392-394`). The volume RPC is throttled to 100 ms with an immediate flush on
  release (`player.js:38-44`, `scheduleVolumeRpc`).

* **`queue.js` drag-and-drop index arithmetic is correct.** The computed `insertIndex` is
  expressed in post-removal coordinates and matches `audio/queue.py::move_track`
  (pop-then-insert, `queue.py:202-203`) exactly; the local `currentQueue.splice` mirrors it
  (`queue.js:280-281`). `move_track` also adjusts `_current_index` correctly
  (`queue.py:206-213`), and `reorder_queue` re-emits `queue_updated`
  (`core/api.py:1785`), so the drawer re-renders with the correct highlighted row.

* **`queue.js` empty state and live update are correct.** `renderQueue` renders
  `<div class="empty-state">Очередь пуста</div>` for an empty list (`queue.js:130-133`), and
  the `nedotify:queue_updated` listener (`queue.js:61-69`) updates `currentQueue` /
  `window.currentQueue` on **every** event (not only when the drawer is open) and re-renders
  only when visible — the right split. `loadQueue` has a generation guard
  (`queueLoadGen`, `queue.js:76-85`) so a slow response cannot overwrite a newer one.
  `incrementQueueVersion()` correctly invalidates the prefetch on any queue change
  (`player.js:58-62`).

* **`equalizer.js` is crash-safe.** `restoreEq` (`equalizer.js:314-319`) clamps every gain to
  `[-20, 20]`, always rebuilds a 10-element array
  (`Array.from({length:10},(_,i)=>gain(data.bands?.[i]))`), so a short, missing or
  non-numeric `bands` array from Python cannot crash the graph, and a missing `mode` is simply
  ignored. `setEq` (`player.js:416-430`) guards every node write with
  `if (eqNodes[i] && audioCtx)` and `bands.forEach` is always called with an array. The WebAudio
  graph itself is correct: `preamp → 10 biquads (lowshelf / peaking×8 / highshelf at
  31/62/125/250/500/1k/2k/4k/8k/16k Hz) → DynamicsCompressor → AnalyserNode → destination`,
  with `createMediaElementSource(audioA)` and `createMediaElementSource(audioB)` both connected
  to the preamp (`player.js:365-377`) — i.e. the EQ actually affects the audible output.

* **`visualizer.js` handles the rAF lifecycle correctly.** The loop is cancelled when the
  visualizer is disabled (`setVisualizerEnabled`, `visualizer.js:44-52`), when the window is
  hidden (`documentVisible` via `visibilitychange` and `nedotify:window_visibility_changed`,
  `visualizer.js:98-108` → `syncVisualizerAnimation`, `242-249`), and when the efficiency
  preset disables visualisations (`nedotify:efficiency_state`, `visualizer.js:526-532`).
  `draw()` schedules the next frame **only after** the "is a canvas visible" check
  (`visualizer.js:338-360`), so there is no orphan rAF chain, and `destroyVisualizer`
  (`visualizer.js:500-519`) removes the resize listener, the DPR listener and the
  `IntersectionObserver`. Drawing is additionally throttled to `frameInterval`
  (default 24 fps, `visualizer.js:26-33`), so this is not a 60 fps CPU burn.
  `getAudioFrequencyData` (`player.js:404-414`) returns `false` when there is no audio
  context, and the visualizer falls back to the synthetic simulation
  (`visualizer.js:286-311`) — a null `AudioContext` is handled, not crashed on. The
  `AnalyserNode` is configured with `fftSize = 256` / `smoothingTimeConstant = 0.8`
  (`player.js:330-332`); `getByteFrequencyData` is called with a 64-element array
  (`visualizer.js:13`), which the UA fills with the first 64 of the 128 bins (no exception) —
  the visualiser therefore covers 0–~11.8 kHz and never the top octave. That is a range
  choice, not a defect, but it is worth knowing when comparing the spectrum with the EQ's
  16 kHz band.

* **The mini-player / fullscreen toggles go through the bridge correctly.** The mini-player
  expand button calls `window.toggleMiniPlayerMode(false)` (`player.js:1079-1086`), which
  `main.js:175-206` forwards to `window.pywebview.api.toggle_mini_player(targetState)`
  (`core/api.py:773`). Minimise / close use `minimize_window` / `close_window` with fallbacks
  (`player.js:1070-1095`), and the mini-player drag uses `api('begin_window_drag')`
  (`player.js:1105`).

---

### 4. Coverage gaps

* **No runtime verification.** The audit rules forbid running the real app (it would touch the
  user's `~/.nedotify/` profile). Every finding above is derived from source; F-WN-29-1,
  F-WN-29-2, F-WN-29-4, F-WN-29-6, F-WN-29-7 and F-WN-29-10 have a concrete static
  reproduction path, but the *observed* user-visible symptom was not reproduced on screen.
  What would confirm them: a scripted session that (a) sets the volume, restarts and reads
  `player.js` state, (b) issues two `next_track()` calls 1 s apart on an unresolved cloud queue
  and then reads `get_queue()`, (c) calls `seekTo()` with an out-of-range value and inspects
  `report_position`, (d) reads `get_equalizer()` over the bridge, (e) mutates the queue while
  the drawer is open and clicks ×, (f) imports a UNC path.
* **No provider currently returns an HLS playlist**, so F-WN-29-3 could not be reproduced
  end-to-end: `Select-String -Pattern "m3u8"` over `services/*.py`, `core/*.py` and `utils/*.py`
  finds only *playlist import/export* formats, never a stream URL. The Yandex provider uses
  `direct_link` from `yandex-music` (`services/yandex_service.py:212`), which is normally a
  direct `.mp3`. What would confirm the finding: a provider (or a `yandex-music` version) that
  returns an `.m3u8` on a `youtube.com` / `soundcloud.com` / `music.yandex.ru` host — then
  `audioEl._hls` stays `null` and `<audio src>` receives the playlist.
* **The pywebview bridge dispatch order was not inspected.** Whether five rapid
  `api('next_track')` calls are serialised by pywebview (which would make F-WN-29-2's trigger
  window narrower) depends on the installed `pywebview` version's `ApiBridge` implementation,
  which lives outside the repo. The F-WN-29-2 trigger does not depend on the *ordering* of the
  `next_track` calls, only on the *ordering of the two background stream resolutions*, which is
  plainly non-deterministic (network I/O).
* **`lyrics.js:966` was not reviewed** (WN-32's area); it is cited only as the caller that
  can produce an out-of-range `seekTo()` argument.
* **`core/api.py::_resolve_track._deliver` (the destructive callee behind F-WN-29-2) is
  formally WN-05's area**; it was read to prove the call chain but is not duplicated as a
  WN-29 finding. Likewise `core/proxy.py` (WN-11) owns the proxy URL shapes referenced in
  F-WN-29-3 and F-WN-29-10, and `core/settings.py` (WN-14) owns `DEFAULT_SETTINGS` referenced
  in F-WN-29-1 and F-WN-29-6.
* **The `crossfade` / `gapless` paths were verified by code reading only** — no A/B playback
  test was run, so the claim "the crossfade actually works" is a code-level conclusion
  (graph and index arithmetic checked), not an observed one.
