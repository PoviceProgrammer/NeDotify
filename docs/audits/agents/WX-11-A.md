## WX-11 — Network loss during playback and recovery after connectivity returns — ROLE A

### 1. Scope reviewed

- **Files opened (path: line ranges actually read)**
  - `core/playback_recovery.py:1-183` (whole file — `same_recording`, `_callback_result`, `_invalidate`, `_target`, `recover_stream`)
  - `core/resolver.py:1-271` (whole file — mem/DB cache, single-flight, `_mark_failed`, `_is_failed`, `mark_unavailable`, `clear_unavailable`, `_url_expired`, `resolve`, `refresh`, `invalidate`, `_persist`)
  - `utils/stream_urls.py:1-26` (whole file — `stream_url_expired`)
  - `core/api.py:340-400` (AppApi ctor / the engine error-hook wiring), `core/api.py:1110-1160` (`_emit`), `core/api.py:1180-1400` (`_on_track_changed`, `_on_queue_end`, `_on_audio_error`, `report_state`), `core/api.py:1437-1770` (`play_track`, `_resolve_track`), `core/api.py:4130-4228` (`recover_stream`, offline mode)
  - `core/proxy.py:238-307` (`_safe_stream_local_path`), `core/proxy.py:680-1193` (`do_GET`, the 403/410 self-heal, the upstream retry loop), `core/proxy.py:1290-1334` (`get_proxy_url`)
  - `core/user_errors.py:1-24` (whole file), `core/offline.py:1-77` (whole file), `core/session.py:1-95`
  - `core/database.py:2130-2239` (`get_cached_stream` / `cache_stream` / `invalidate_cached_stream` / `set_cached_file`)
  - `core/app.py:90-209` (service wiring, lazy `soundcloud`/`yandex`), `core/app.py:280-399` (`re_resolve_stream_url_async`)
  - `audio/engine.py:1-508` (whole file — `resolve_stream_url`, `_resolve_via_network`, `_notify_track_changed`)
  - `services/base_service.py:1-329` (shared `_stream_cache`, TTL, `get_from_cache`)
  - `services/youtube_service.py:96-135, 894-953` (cache key, `get_stream_url`), `services/soundcloud_service.py:60-139, 515-894` (`_unavailable_cache`, `_is_unplayable_error`, `_media_url_is_servable`), `services/yandex_service.py:160-239`, `services/vk_service.py:50-98`
  - `ui/web_new_v2/js/player.js:1-180, 380-957, 1625-1908` (`handleStreamError`, `stopFailedPlayback`, `setupAudioEvents`, `playTrack`, `loadAudioSource`, `onTrackChanged`, `onStateChanged`)
  - `ui/web_new_v2/js/events.js:310-449` (`audio_error`, `error`), `ui/web_new_v2/js/main.js:545-624` (`proxy_status` banner)
  - `tests/test_playback_recovery.py`, `tests/test_player_recovery_transitions.py`, `tests/test_player_resources.py`, `tests/test_recommendation_ui.py` (the node harness reused for verification)
- **Callees traced into other areas**
  - WN-11 `core/proxy.py` — upstream fetch, 403 self-heal, 502 on network failure, local-file gate
  - WN-15 `core/resolver.py`, `core/playback_recovery.py`, `utils/stream_urls.py` — the caches and the recovery itself
  - WN-17 `audio/engine.py` — the queue and the resolution cascade
  - WN-12 `core/database.py` — `stream_cache` rows
  - WN-16 `core/user_errors.py` — the error categorisation
  - WN-19/20/21 — YouTube / SoundCloud / Yandex / VK provider caches and negative memos
  - WN-28/29 — the frontend event bus and the player
- **Verification harnesses used (read-only, written under `%TEMP%`)**
  - `C:\Users\Артур\AppData\Local\Temp\opencode\wx11_verify.py` (node harness of the shipped `player.js`)
  - `C:\Users\Артур\AppData\Local\Temp\opencode\wx11_verify2.py` (node harness, part 2)
  - `C:\Users\Артур\AppData\Local\Temp\opencode\wx11_verify_py.py` (in-process Python harness of `recover_stream` / `StreamResolver`)

### 2. Findings

#### F-WX-11-1  [P2] — The resolver's negative cache is dead code: `mark_unavailable()` has no production caller, so an outage records no verdict and every attempt re-runs the whole provider cascade

- **File:** `core/resolver.py:20-28`, `core/resolver.py:79-84`, `core/resolver.py:86-95`, `core/resolver.py:101-117`, `core/resolver.py:165-230`; `core/playback_recovery.py:85`
- **Confirmed:** yes (runtime-verified)
- **Description:** The scenario's key question — "does a transient network outage permanently blacklist the track (and the provider)?" — has two halves. (a) *Permanent blacklisting*: **no.** The verdict TTL is `_FAIL_TTL = 120.0` s (`core/resolver.py:27`) and it expires on its own (`_is_failed` pops the entry past the TTL, `core/resolver.py:92-94`). (b) *Retry damping*: **also no — and this is the defect.** `StreamResolver.resolve()` never records a failure verdict: on a failed cascade it only logs and returns `None` (`core/resolver.py:226-230`); `_mark_failed()` is reachable **only** through `mark_unavailable()` (`core/resolver.py:113-114`), and `mark_unavailable()` has **no production caller anywhere in the repo** (only `tests/test_soundcloud_drm_unavailable.py` calls it). The provider-level negative memos are safe by construction: `SoundCloudService._unavailable_cache` (TTL 3600 s) is written only from DRM / 401-403-404-410 verdicts, and `_media_url_is_servable()` returns `True` on any transport error (`services/soundcloud_service.py:541-567`), `_is_unplayable_error()` matches only the fixed mark list (`services/soundcloud_service.py:100-103`).
- **Cause:** The memo was designed as an explicit provider verdict ("Pass the provider's own verdict through `mark_unavailable`" — `core/resolver.py:104-110`), but no provider ever passes one. The result is a cache whose protection never engages.
- **Trigger conditions:** Any network outage, or any track the resolution cascade cannot resolve.
- **User impact / blast radius:** **No permanent blacklist of the track or the provider — that part is safe.** The blast radius is the opposite of what the memo was written for: because `_failed` stays empty, `resolve()` re-runs the *entire* cascade (up to three provider searches plus two stream extractions, `audio/engine.py:143-151` → `_resolve_via_network`, 20 s budget at `audio/engine.py:278`) on **every** attempt. During one outage the user pays: 1 proxy request (4 upstream attempts × 12 s + backoff ≈ 56 s of proxy thread, `core/proxy.py:1009-1120`), 2 player recovery attempts × 3 provider calls (measured below), the proxy's own 403 self-heal cascade, plus one full cascade per manual re-press. The `skip resolution … already known unavailable` fast path (`core/resolver.py:181-185`) never fires.
- **Evidence:**
  ```python
  # core/resolver.py:209-230
  if owner:
      try:
          url, error = resolver_fn()
          flight.url = url
          flight.error = error
          if url:
              self._persist(source, source_id, url)
      except Exception as e:
          flight.error = str(e)
      finally:
          ...
  if flight.url:
      return flight.url
  if flight.error:
      logger.warning(f"Stream resolution failed for {source}:{source_id}: {flight.error}")
  return None
  ```
  ```python
  # core/resolver.py:27
  _FAIL_TTL = 120.0
  ```
  ```python
  # core/playback_recovery.py:83-85  (clears a memo that is never populated)
  if resolver:
      resolver.invalidate(source, identifier)
      resolver.clear_unavailable(source, identifier)
  ```
- **Reproduction / verification:**
  ```
  $ .venv_win\Scripts\python.exe -c "from core.resolver import StreamResolver; ..."
  resolve -> None
  cascade calls: 1
  _failed map: {}            # <-- a failed cascade records NO verdict
  is_unavailable: False
  ```
  and, through the recovery:
  ```
  resolver negative-cache entries after a failed recovery: {}
  ```
  A repo-wide scan for `mark_unavailable` returns only `core/resolver.py` (the definition), `services/soundcloud_service.py:526` (a *different*, private `_mark_unavailable`), `core/playback_recovery.py:85` (`clear_unavailable`) and tests — no production caller of `StreamResolver.mark_unavailable`.
- **Suggested fix:** Decide the policy explicitly: either call `resolver.mark_unavailable(source, source_id, reason)` from the provider paths that already hold a "this track is gone" verdict (SoundCloud DRM / 401-403-404-410), or make `resolve()` record a *network-classified* failure on its own. Keep the classification split so a transport error never becomes a permanent verdict.
- **Fix side effects:** Populating the memo re-enables `resolve()`'s skip path; a mis-classified network error would then block a track for 120 s. The TTL must stay short and the provider verdict path must be the only writer of the permanent class.
- **Discovered by:** A
- **Owning area:** WN-15 (`core/resolver.py`) — single-file defect, not double-reported here.

#### F-WX-11-2  [P2] — A failed recovery throws the playback position away: the manual retry after the network returns restarts the track at 0:00

- **File:** `ui/web_new_v2/js/player.js:496-508` (`stopFailedPlayback`), `ui/web_new_v2/js/player.js:774` (`pendingResume`), `ui/web_new_v2/js/player.js:872-902` (`togglePlayPause` → `api.play_track`), `core/api.py:1437-1604` (`play_track` takes no position argument)
- **Confirmed:** yes (runtime-verified in the node harness)
- **Description:** The position **is** preserved across a *successful* recovery (`resumeMs` → `pendingResume` → applied in `loadedmetadata`, `ui/web_new_v2/js/player.js:549-558`; verified: `position after a successful recovery: 61.25 s`). It is **lost** on the failure path: `stopFailedPlayback` sets `pendingResume = null` and discards the captured `resumeMs`, and the user's next action goes through the backend (`api.play_track(currentTrack, queue, idx)`), which has no notion of a playback position at all (`core/api.py:1437`). The reloaded stream therefore starts at 0:00.
- **Cause:** The position is carried only in the frontend's `recovery` option (`{resumeMs, recovery: true}`, `ui/web_new_v2/js/player.js:483`); the manual retry path is a different code path with no position plumbing.
- **Trigger conditions:** The network is down long enough for both recovery attempts to fail (the recovery budget is 2 attempts at +1.5 s and +3 s, `ui/web_new_v2/js/player.js:462,490`), and the user then presses play again once the network is back. This is the *common* case: the whole recovery budget is consumed within ~10 s of the failure, while a Wi-Fi/Ethernet reconnect typically takes 5-30 s.
- **User impact:** The user is sent back to the beginning of the track they were 2 minutes into, every time a brief outage breaks the first recovery window.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:496-508
  function stopFailedPlayback(message) {
      playbackGeneration++;
      recoveryRequest = null;
      pendingResume = null;
      finishFade();
      releaseAudio(audioA);
      releaseAudio(audioB);
      onStateChanged('paused');
      window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {
          msg: message || `Не удалось восстановить «${currentTrack?.title || 'трек'}». Проверьте подключение и повторите`,
          type: 'error',
      }}));
  }
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:774 — the position only exists on the recovery path
  pendingResume = options.recovery ? {key: trackIdKey, ms: options.resumeMs || 0} : null;
  ```
- **Reproduction / verification:** node harness on the shipped `player.js` (`wx11_verify2.py`, V5/V6): play a track, set `currentTime = 61.25`, fire the media `error`, let both recovery attempts fail, then `togglePlayPause()` and answer with the backend's `track_changed`:
  ```
  === V5: a failed recovery loses the playback position on the manual retry ===
  position after the manual retry: 0  pendingResume=null
  === V6: the same, but the backend re-emits a FRESH stream_url ===
  position after the manual retry with a fresh URL: 0
  ```
  For contrast, the successful-recovery case keeps the position (`wx11_verify.py`, V1): `player.pending.ms === 61250` → `player.active.currentTime === 61.25`.
- **Suggested fix:** Keep the captured `resumeMs` (and the `currentTrack` key) when the recovery fails, and replay it when the same track is reloaded — either by passing it through `play_track` (the bridge already has `report_position`) or by keeping `pendingResume` armed for the manual retry instead of clearing it in `stopFailedPlayback`.
- **Fix side effects:** Resuming at a non-zero offset on a *different* recording (the recovery may have swapped provider) can start mid-word; the existing `same_recording` check and the `min(seconds, duration - 0.05)` clamp in `loadedmetadata` already bound that.
- **Discovered by:** A

#### F-WX-11-3  [P2] — After a successful recovery the backend's queue entry keeps the dead upstream URL; the next backend-driven play of that track replays the dead URL and restarts from 0:00

- **File:** `core/playback_recovery.py:177-183` (`resolver.refresh` but no queue update), `core/api.py:1583-1597` and `core/api.py:1716-1733` (the queue entry's `file_path` is the **raw upstream URL**), `audio/engine.py:78-119` (`_notify_track_changed` builds the proxy URL from that `file_path`), `ui/web_new_v2/js/player.js:1687-1692` (`onTrackChanged` restarts playback when the stream URL differs)
- **Confirmed:** yes (runtime-verified)
- **Description:** The recovery resolves a fresh URL and pushes it into the resolver/DB caches (`resolver.refresh(source, identifier, stream)`, `core/playback_recovery.py:179`) and returns the proxy URL to the frontend — but the **backend's queue entry for that track still holds the dead raw upstream URL** in `file_path`. The frontend's recovery is a purely local action: the backend is never told which URL is now playing. The next time the backend re-emits `track_changed` for that track (next/prev cycle, "play" from the library, `api.play_track` → `engine.play_queue` → `_notify_track_changed`), the frontend receives a proxy URL for the **dead** upstream URL. `onTrackChanged` compares it with the currently loaded source and, because they differ, calls `playTrack(track, track.stream_url)` → the stream restarts at 0:00 **and** the dead URL is fetched again (the proxy must burn a 403 plus a full re-resolution cascade before the track plays).
- **Cause:** `recover_stream()` refreshes the *cache* but not the *queue*; the queue's `file_path` is the only place the backend keeps "which URL is this track currently playing".
- **Trigger conditions:** A successful recovery followed by any backend-driven re-emit of the same track (prev/next, library play, session restore of the queue entry).
- **User impact:** The user hears the track again from the beginning after a visible stall of several seconds (403 → invalidate → full provider cascade), even though the recovery had already produced a working URL.
- **Evidence:**
  ```python
  # core/playback_recovery.py:177-183
  resolver = getattr(core, "resolver", None)
  if resolver:
      resolver.refresh(source, identifier, stream)
  proxy = getattr(core, "proxy", None)
  playback_url = proxy.get_proxy_url(source, identifier, stream, track_id=track.get("id")) if proxy else stream
  return {"ok": True, "stream_url": playback_url, "position_ms": position, ...}
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:1687-1692
  } else if (track.stream_url) {
      window._pendingResolveKey = null;
      // Avoid restarting playback when backend re-emits the same stream (e.g. double resolution notify)
      if (!sameTrack || activeAudio.ended || !activeAudio.src || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
          playTrack(track, track.stream_url);
      }
  ```
- **Reproduction / verification:** `wx11_verify_py.py` P5 — the queue dict handed to the recovery is not modified while the resolver does get the fresh URL:
  ```
  === P5: the queue track dict is NOT updated by the recovery ===
    queue file_path after recovery: https://cdn.example/dead.mp3
    resolver cached url after recovery: https://cdn.example/fresh.mp3
  ```
  and `wx11_verify2.py` V5 — after the manual retry the frontend is put back on the **dead** URL:
  ```
  active src: http://127.0.0.1:9/api/stream?source=youtube&source_id=first
  ```
- **Suggested fix:** In `core/playback_recovery.recover_stream()`, after a successful resolution, write the fresh URL back to the queue's current track (`core.engine.queue.current_track["file_path"] = stream`) and re-emit `track_changed` (or at least keep the queue entry consistent), so the backend and the frontend agree on the live URL.
- **Fix side effects:** Mutating the queue from the recovery path races with `next_track`/`prev_track`; the update must be guarded by the same track identity check the frontend uses (`source` + `source_id`).
- **Discovered by:** A

#### F-WX-11-4  [P2] — The `<audio>` error never reaches `core/api.py::_on_audio_error`: the engine has no error hook, so the backend never learns that the stream died and the queue keeps pointing at the dead track

- **File:** `ui/web_new_v2/js/player.js:659-671` (the media `error` handler), `core/api.py:381-382` (the wiring), `audio/engine.py:27-33` (no `on_error` attribute), `core/api.py:1255-1260` (`_on_audio_error`)
- **Confirmed:** yes
- **Description:** The scenario premise ("the `<audio>` element fires `error` → `core/api.py::_on_audio_error`") does not hold. The frontend's media `error` handler only reports *listening* state; it never tells the backend that the stream failed. The backend hook that is supposed to do this is dead code: `AppApi.__init__` guards it with `hasattr(self._core.engine, "on_error")` and `AudioEngine` defines no `on_error` attribute (`audio/engine.py:27-33` sets only `proxy`, `_on_track_changed`, `_on_queue_end`), so the assignment at `core/api.py:381-382` never executes. `_on_audio_error` is therefore reachable **only** from the backend's own resolution failures (`core/api.py:1204, 1442, 1575, 1587, 1602, 1710, 1720, 1742`).
- **Cause:** The engine never grew the `on_error` hook the bridge expects; the media element's failure is handled exclusively in the frontend.
- **Trigger conditions:** Any media failure (network loss, decode error, 502 from the proxy).
- **User impact:** The backend's state stays "this track is playing": the queue's `current_track` still points at the dead track, `AppApi._current_track` still holds it, and the categorised `audio_error` event (with its `code`/`action`) is never emitted for a media failure. The user *is* told — but only by the frontend toast from `stopFailedPlayback` (`ui/web_new_v2/js/player.js:504-507`), which bypasses `core/user_errors.py` entirely and therefore loses the categorisation.
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:659-671
  audio.addEventListener('error', (e) => {
      if (audio === activeAudio) api('report_listening_state', currentTrack?.listening_session, false);
      isSeeking = false;
      if (seekTimeoutId) { clearTimeout(seekTimeoutId); seekTimeoutId = null; }
      // Ignore synthetic or background cleanup errors
      if (audio !== activeAudio || !audio.src || audio.src === '' || audio.src === 'about:blank' || audio.src === window.location.href) {
          return;
      }
      handleStreamError(audio, 'error_event');
  });
  ```
  ```python
  # core/api.py:381-382 — dead: AudioEngine has no `on_error`
  if hasattr(self._core.engine, "on_error"):
      self._core.engine.on_error(self._on_audio_error)
  ```
  ```python
  # audio/engine.py:27-33
  def __init__(self):
      self.queue = PlaybackQueue()
      self.proxy = None
      self._on_track_changed = None
      self._on_queue_end = None
      self.app_core = None
  ```
- **Reproduction / verification:** Repo-wide scan of `player.js` for `api('…')` calls: the `error` handler is the only failure path and it calls only `report_listening_state`; there is no `report_error`/`audio_error` bridge method. `grep -n "on_error" audio/engine.py` → no match.
- **Suggested fix:** Either give `AudioEngine` an `on_error` hook and have the frontend report the media failure (`api('report_playback_error', code, message)`) so `_on_audio_error` can categorise it, or delete the dead wiring at `core/api.py:381-382` and document that media failures are a frontend-only concern.
- **Fix side effects:** Routing media failures through `_on_audio_error` would emit `audio_error` → `events.js:384` calls `onStateChanged('stopped')`, which would fight the frontend's own recovery state machine (`onStateChanged('loading')` during the recovery). The two paths must be reconciled.
- **Discovered by:** A
- **Owning area:** WN-05 (`core/api.py:381-382`) + WN-17 (`audio/engine.py`).

#### F-WX-11-5  [P3] — The media error code is ignored, so a non-recoverable decode / "source not supported" error burns two full provider cascades and delays the failure message

- **File:** `ui/web_new_v2/js/player.js:659-671` (the `error` handler ignores its `e` argument and `audio.error.code`)
- **Confirmed:** yes
- **Description:** `HTMLMediaElement.error.code` distinguishes `MEDIA_ERR_NETWORK` (2) — where a re-resolve can genuinely help — from `MEDIA_ERR_DECODE` (3) and `MEDIA_ERR_SRC_NOT_SUPPORTED` (4), where re-resolving the *same bytes* cannot help. The handler passes the reason string `'error_event'` for all of them, so a decode failure triggers the same two full recovery cascades (each up to ~14 s of provider work, `core/playback_recovery.py:121`) before the user is told.
- **Cause:** The error code is never read; `handleStreamError` has a single code path.
- **Trigger conditions:** The proxy serves a body the element cannot decode (e.g. the known AR-11 finding F-AR-11-2: a `200 OK` HTML error page cached and later served as `audio/mp4`), or a corrupt stream.
- **User impact:** ~30 s of apparent "retrying" and a second provider cascade for an error that no re-resolution can fix; the toast then shows the generic "Не удалось восстановить «track»" rather than "the stream is corrupt".
- **Evidence:**
  ```javascript
  // ui/web_new_v2/js/player.js:659-671 — `e` is declared and never used
  audio.addEventListener('error', (e) => {
      ...
      handleStreamError(audio, 'error_event');
  });
  ```
- **Reproduction / verification:** Static: `grep -n "error.code\|MEDIA_ERR" ui/web_new_v2/js/player.js` → no match. Dynamic: the harness's `AudioStub` has no `error` object, so a decode error and a network error are indistinguishable to the current code by construction.
- **Suggested fix:** Read `audio.error?.code` and skip (or shorten) the recovery cascade for codes 3 and 4, reporting "the stream could not be decoded" instead.
- **Fix side effects:** A track that first fails with a network error and then with a decode error would lose its recovery budget; the two-step error (network → decode) must still be allowed one re-resolve.
- **Discovered by:** A
- **Owning area:** WN-29 (`ui/web_new_v2/js/player.js`).

#### F-WX-11-6  [P3] — The provider's real error is discarded before categorisation, so an outage is reported as "Не удалось выполнить действие" instead of naming the network

- **File:** `core/api.py:1583-1602` (`on_queue_error(err)` / `on_queue_resolved`), `core/api.py:1716-1742` (`on_resolve_error(err)` / `on_resolved`), `core/user_errors.py:6-24` (`describe_error`), `ui/web_new_v2/js/events.js:378-386` (the `audio_error` handler shows only `data.title`)
- **Confirmed:** yes (runtime-verified)
- **Description:** `_on_audio_error` does classify the message, but the message it is given is a fixed generic string — the provider's actual error (`err`) is only logged and then dropped:
  ```python
  def on_queue_error(err):
      logger.warning(f"api.py -> queue resolve error: {err}")
      if self._core.engine.queue.current_track is target_track:
          self._on_audio_error(f"Не удалось найти поток для {target_track.get('title') or source_id}")
  ```
  `describe_error()` therefore sees "Не удалось найти поток для …", which matches none of its categories and falls through to the generic branch. The categorised `user_message` that `describe_error` *does* produce is computed but never displayed — the frontend shows `data.title` only.
- **Cause:** The error text is replaced by a generic string one level above the classifier, and the classifier's actionable `message` field is dropped by the UI.
- **Trigger conditions:** Any backend-side resolution failure — in particular the outage case (the provider reports "connection failed"/"timed out", which `describe_error` *would* have classified as `code: 'network'`).
- **User impact:** During an outage the user is told "Не удалось выполнить действие" — a message that names neither the network nor the track — instead of "Не удалось подключиться к источнику / Проверьте интернет". The actionable half of the error system is computed and thrown away.
- **Evidence:**
  ```
  $ .venv_win\Scripts\python.exe -c "from core.user_errors import describe_error; ..."
  'Не удалось найти поток для Song' -> {'code': 'unexpected', 'title': 'Не удалось выполнить действие', ...}
  'connection failed'                 -> {'code': 'network', 'title': 'Не удалось подключиться к источнику',
                                          'message': 'Проверьте интернет или повторите попытку позже.', ...}
  ```
  ```javascript
  // ui/web_new_v2/js/events.js:378-386
  case 'audio_error': {
      lastAudioErrorAt = Date.now();
      const cleanAudioErr = (data?.message || '').toString().replace(/\x1b\[[0-9;]*m/g, '');
      showToast(data?.title || 'Не удалось воспроизвести трек', 'error');
      ...
  ```
- **Reproduction / verification:** The two `describe_error` calls above (runtime output). The `on_queue_error`/`on_resolve_error` bodies are quoted from `core/api.py:1599-1602` and `core/api.py:1739-1742`.
- **Suggested fix:** Pass the provider's error text through to `describe_error` (or send both: the raw error for the log, the classified one for the user) and show `data.user_message`/`data.message` in the toast, not only `data.title`.
- **Fix side effects:** Provider error strings are unfiltered and can contain URLs/tokens; they must stay out of the user-visible toast (they are already stripped of ANSI escapes only).
- **Discovered by:** A
- **Owning area:** WN-05 (`core/api.py`) for dropping `err`; WN-16 (`core/user_errors.py`) / WN-28 (`events.js`) for the title-only toast.

#### F-WX-11-7  [P3] — The recovery refuses `vk` before it invalidates the failed URL, so the same dead URL is served again on the next attempt

- **File:** `core/playback_recovery.py:115-120` (the source allow-list and the position of `_invalidate`), `core/app.py:330-336` (`re_resolve_stream_url_async` has no `vk` branch), `core/api.py:1216` (`_on_track_changed` proxies `vk`)
- **Confirmed:** yes
- **Description:** The recovery's source allow-list is `("youtube", "soundcloud", "spotify", "yandex")` — `vk` is missing — and the rejection happens **before** `_invalidate()` is called, so for a `vk` track the dead URL stays in the resolver cache and in the DB `stream_cache` row. The next play attempt therefore hands out the same dead URL again (an infinite failure loop for that track), instead of re-resolving. The async re-resolver has the same gap: `core/app.py:330-336` answers `on_error(f"Unsupported source: {source}")` for `vk`, so even the proxy's 403 self-heal cannot renew a `vk` URL.
- **Cause:** Two independent source lists (`playback_recovery`, `app.re_resolve_stream_url_async`) that do not cover the sources the rest of the app proxies (`core/api.py:1216` proxies `youtube`, `soundcloud`, `yandex`, `vk`).
- **Trigger conditions:** A `vk` track whose stream fails.
- **User impact:** Today the impact is masked: `vk` is missing from the resolution cascade as well (`audio/engine.py:168-508` has no `vk` branch), so a `vk` track never resolves in the first place — the deeper `vk` gap belongs to WX-01 / WN-21 and is **not** reported here. What is reported here is the cross-component inconsistency: a source the app proxies is not renewable, and its failed URL is not invalidated.
- **Evidence:**
  ```python
  # core/playback_recovery.py:115-120
  if source == "local":
      return {"ok": False, "code": "file_missing", "error": "Файл перемещён или удалён. Выберите его заново"}
  if source not in ("youtube", "soundcloud", "spotify", "yandex"):
      return {"ok": False, "code": "source_unavailable", "error": "Источник не поддерживает восстановление"}
  target = _target(source, track)
  _invalidate(core, source, track, target)
  ```
  ```python
  # core/app.py:330-336
  elif source == "yandex":
      url = f"https://music.yandex.ru/track/{source_id}"
      service = self.yandex
  else:
      if on_error:
          on_error(f"Unsupported source: {source}")
      return
  ```
- **Reproduction / verification:** Static trace of `core/playback_recovery.py:115-120` (the early return precedes `_invalidate`) and `core/app.py:330-336` (no `vk` branch). `services/vk_service.py:50-88` shows `VKService.get_stream_url` exists and is a real implementation, so the provider is not the limitation.
- **Suggested fix:** Move `_invalidate()` above the source check (an unsupported source must still drop its dead URL), and either add a `vk` branch to the recovery + `re_resolve_stream_url_async` or stop proxying `vk` tracks until the cascade supports them.
- **Fix side effects:** Invalidating for an unsupported source is safe (the URL is dead either way); adding `vk` to the recovery widens the provider surface that the recovery can hit during an outage.
- **Discovered by:** A
- **Owning area:** WN-15 (`core/playback_recovery.py`) for the ordering; the `vk` resolution gap is owned by WX-01 / WN-21 and is **not** claimed here.

### 3. Clean areas

- **The `<audio>` error path is not silent and it is bounded.** `handleStreamError` (`ui/web_new_v2/js/player.js:448-494`) retries at most twice (delays 1.5 s and 3 s), then `stopFailedPlayback` (`:496-508`) releases both elements, sets the UI to *paused* and raises a toast carrying the backend's error text. Verified in the node harness: exactly 2 `recover_stream` calls, no third attempt, one toast, `audio.src === ''` on both elements. **The user is always told.**
- **The recovery is bounded in wall-clock time and the callback wait is bounded.** `core/playback_recovery.py:121` sets an 18 s deadline; `_callback_result` (`core/playback_recovery.py:40-63`) applies `completed.wait(max(0, timeout))` with per-stage budgets of 8 s / 3 s / 4 s. Measured with a provider that never answers: **14.0 s** elapsed, 3 provider calls, result `{'ok': False, 'code': 'source_unavailable', …}`. No unbounded wait, no retry storm inside one recovery.
- **The playback position is preserved across a *successful* recovery, end to end.** `resumeMs = Math.round((audio.currentTime||0)*1000)` is captured at the moment of the error (`ui/web_new_v2/js/player.js:463`), carried through `api.recover_stream(track, resumeMs)`, echoed by the backend as `position_ms` (`core/playback_recovery.py:182`), and re-applied on `loadedmetadata` (`ui/web_new_v2/js/player.js:549-558`) with a `duration - 0.05` clamp. Verified: `pending.ms === 61250` → `active.currentTime === 61.25` after the recovery. (The *failed* path loses it — F-WX-11-2.)
- **A stale result is discarded when the user moves on.** The generation guard (`ui/web_new_v2/js/player.js:464, 469, 474`) plus `playbackGeneration++` in `playTrack` drops a recovery that lands after a skip. Verified (V4): the stale URL is never loaded.
- **The failed URL IS invalidated from every cache — there is no "same dead URL forever" loop for the supported sources.** `core/playback_recovery.py:77-92` calls `resolver.invalidate()` (mem + DB `stream_url = NULL`, `core/database.py:2213-2225`), `resolver.clear_unavailable()`, and purges the provider's `_stream_cache` entry both by key (`youtube:<id>`, matching `services/youtube_service.py:101-121`) and by URL. Verified: after a failed recovery the resolver cache and the provider cache both return `None` for the dead URL, and the fresh URL is in place. The "infinite failure loop" hypothesis is **not** confirmed for youtube / soundcloud / yandex.
- **Expiry detection is sound and the margin is adequate.** `utils/stream_urls.py:7-26` parses only the explicit `expire` / `Expires` tokens (epoch seconds, ≥ 6 digits) and applies a **60 s** margin, so a URL that dies 30 s from now is already treated as expired (verified). It correctly leaves token-less URLs alone (they fall back to the provider TTL + the proxy's 403 self-heal) rather than mis-reading an arbitrary numeric parameter.
- **The proxy answers an upstream network failure with a real HTTP error, so the media element sees a media error, not a decode failure.** `core/proxy.py:1102-1120` retries the upstream (4 attempts, 12 s timeout each, exponential backoff) and then `send_error(502, 'Bad Gateway / Upstream connection failed')` — a valid 5xx with an HTML error body, which the `<audio>` element reports as a network error and routes into `handleStreamError`. The 403/410 path (`core/proxy.py:1022-1090`) returns the upstream status with no body — likewise a media error.
- **The proxy's 403/410 self-heal invalidates the cache before re-resolving** (`core/proxy.py:1027-1029` → `resolver.invalidate`), and the re-resolved URL is SSRF-checked before use (`core/proxy.py:1054-1056`). The recovery path additionally purges the provider cache, which the proxy path does not.
- **A downloaded / local track plays with no network and without touching the resolver.** Traced `core/api.py:1437-1548`: for a track whose `file_path` is an existing local file, `_fp_usable()` is true and the function returns via `engine.play_queue()` — the DB `stream_cache` lookup, `re_resolve_stream_url_async` and the whole resolution cascade are skipped. `audio/engine.py:106-117` then builds a `/api/stream?url=<path>` proxy URL, and `core/proxy.py:742-751` serves the file straight from disk (`_safe_stream_local_path`, `core/proxy.py:238-272`) with **no** upstream request and no resolver involvement. `core/playback_recovery.py:108-111` likewise answers a track with an existing local file from disk and never contacts a provider (`tests/test_playback_recovery.py:92-104` pins this).
- **The offline mode is re-checked at every step of the recovery** (`core/playback_recovery.py:112-114, 131-132, 137-138, 149-150, 166-167` and `core/api.py:4168-4173`), so toggling offline mode mid-recovery aborts it cleanly with `code: 'offline'`.
- **The recovery's fallback does not silently swap in a different recording.** `same_recording` (`core/playback_recovery.py:14-37`) rejects a different artist, version or duration, and a mismatching provider result is discarded (`core/playback_recovery.py:133-134, 160-161`) rather than played (`tests/test_playback_recovery.py:78-89, 107-113`).
- **The recovery result is bound to the track it was requested for** — `selected_source`/`selected_id` are returned separately (`core/playback_recovery.py:182-183`) and the requested track dict is never mutated (`tests/test_playback_recovery.py:88-89`).
- **`_emit` is not called from the UI thread on the recovery path** — `recover_stream` runs on the bridge thread and `_emit` keeps its `EmitWorker` hand-off (`core/api.py:1122-1155`).

### 4. Coverage gaps

- **The proxy's per-request time budget during an outage was not measured end to end.** From the code, one media request can hold a proxy thread for ≈ 4 × 12 s + backoff ≈ 56 s (`core/proxy.py:1009-1120`) plus a synchronous `engine.resolve_stream_url` cascade (up to 20 s, `core/proxy.py:817`, `audio/engine.py:278`). The previous audit already recorded the missing total deadline (`docs/audits/_FINDINGS_SO_FAR.md:90`, "No total deadline on a proxy request: ~55–62 s of thread occupancy for one media request", owned by AR-11 / WN-11), so it is **not** re-reported here; I did not reproduce it against a live socket.
- **No live network was used.** Every provider was stubbed; the real Chromium behaviour on a mid-stream socket drop (whether `audio.currentTime` survives the `error` event, and whether `MEDIA_ERR_NETWORK` is raised before or after `stalled`) could not be observed here. The position claim in section 3 rests on the harness, which sets `currentTime` explicitly.
- **`vk` playback could not be exercised end to end** — `vk` is missing from the resolution cascade (`audio/engine.py:168-508`) and from `re_resolve_stream_url_async` (`core/app.py:330-336`), so no `vk` track reaches the player. The deeper gap belongs to WX-01 / WN-21; only the recovery ordering is claimed in F-WX-11-7.
- **The `_invalidate` identifier mismatch was not exercised.** `core/playback_recovery.py:80` uses `track.get("source_id")`, while `audio/engine.py:125` falls back to the DB row `id` when `source_id` is missing. A track resolved under the row id would be invalidated under the wrong key (`core/resolver.py:247-254`) — a hypothesis only; it needs a track whose `source_id` is empty but whose row id was used as the cache key, which the UI does not normally produce.
- **`core/proxy.py`'s HLS branch** (`core/proxy.py:1128-1152`) was read but not exercised; the WX-11 recovery path assumes a progressive stream.
- **The `describe_error`/`events.js` mismatch (F-WX-11-6) was verified on the mapping and on the toast field, not on a live toast render** (no DOM run of `events.js`).
- **`services/soundcloud_service.py`'s `_unavailable_cache` TTL (3600 s) was read, not timed.** Its writers are all "this track is gone" verdicts, so a network outage cannot populate it — but the yt-dlp error strings that feed `_is_unplayable_error` were not sampled against a real outage.
