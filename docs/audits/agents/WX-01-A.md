## AREA WX-01 — Track resolution → proxy → frontend playback — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole file) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole file) |
| `core/api.py` | 370–419 (bridge wiring, error logging), 1180–1299 (`_on_track_changed`, `_on_audio_error`, `get_proxy_info`), 1400–1859 (`play_track`, `_resolve_track`, `play_pause`, queue ops) |
| `core/proxy.py` | 1–300 (constants, SSRF/credential hosts, `_safe_stream_local_path`), 301–600 (byte ranges, `_rewrite_hls_playlist`, `_authorized`/`_authenticate`, `serve_local_file`), 601–900 (`do_HEAD`, `_resolve_stream_local_file`, `do_GET` `/`+`/api/stream`), 901–1334 (`/` branch, upstream fetch, HLS branch, `LocalProxyManager`) |
| `core/resolver.py` | 1–271 (whole file) |
| `core/app.py` | 110–169 (AppCore wiring), 270–488 (`re_resolve_stream_url_async`) |
| `core/playback_recovery.py` | 1–183 (whole file) |
| `core/offline.py` | 1–77 (whole file) |
| `core/database.py` | 1278–1322 (`mark_track_downloaded`, `get_downloaded_tracks`) |
| `core/downloader.py` | 780–859 (download completion + `download_complete` emit) |
| `audio/engine.py` | 1–259 (`play_track`, `play_queue`, `_notify_track_changed`, `resolve_stream_url`, `_resolve_via_network`) |
| `audio/queue.py` | 1–302 (whole file) |
| `services/base_service.py` | 120–239, 320–329 (`_join_request`, `_stream_cache`, `get_stream_url` contract) |
| `services/youtube_service.py` | 890–999 (`get_stream_url`, `_pending_streams` coalescing) |
| `utils/stream_urls.py` | 1–26 (whole file) |
| `ui/web_new_v2/js/player.js` | 1–220 (`normalizeAudioSourceUrl`, `loadAudioSource`, audio elements), 400–599 (`handleStreamError`, `stopFailedPlayback`, stall fallback, audio events), 600–959 (`playTrack`, `togglePlayPause`), 1600–1799 (`onTrackChanged`) |
| `ui/web_new_v2/js/events.js` | 60–199 (`track_changed`, `state_changed`), 230–349 (`download_complete`, `download_failed`), 380–459 (`audio_error`, `track_updated`) |
| `ui/web_new_v2/js/main.js` | 1–718 (`awaitBridge`, `PROXY_PORT`/`PROXY_TOKEN` bootstrap) |
| `ui/web_new_v2/js/search-discovery.js` | 30–69 |
| `ui/web_new_v2/js/feature-controls.js` | 55–94 |
| `ui/web_new_v2/js/library.js` | 540–579 (`loadDownloaded`) |
| `tests/test_playback_latency_ui.py` | 1–151 (pins the frontend proxy-URL construction) |
| `tests/test_proxy_harness.py` | 1–215 (proxy test harness) |

**Callees traced into other areas** (read only as far as needed for the handoff; defects living entirely inside them are *named*, not re-reported):
`core/offline.py` (WN-10), `core/database.py` (WN-12), `core/downloader.py` (WN-13), `audio/engine.py` + `audio/queue.py` (WN-17), `services/base_service.py` (WN-18), `services/youtube_service.py` (WN-19), `services/soundcloud_service.py` (WN-20), `core/resolver.py` (WN-15), `core/playback_recovery.py` (WN-15), `utils/stream_urls.py` (WN-27), `js/player.js` (WN-29), `js/events.js` (WN-28), `js/library.js` (WN-32), `js/search-discovery.js` (WN-31).

---

#### Hop-by-hop trace (actual field/URL shapes)

**Hop 1 — provider → resolver.**
`services/youtube_service.py::get_stream_url` (`:894`) returns a raw upstream CDN URL, e.g.
`https://rr3---sn-4g5ednsn.googlevideo.com/videoplayback?expire=1758…&sig=…` (no proxy, no token).
SoundCloud returns `https://api-v2.sndcdn.com/media/…/stream/hls`. The value is a **plain string**; there is no envelope/struct anywhere in the chain.

**Hop 2 — `AppCore.re_resolve_stream_url_async` (`core/app.py:296`).**
Called from `core/api.py:1604` (queue path) and `core/api.py:1744` (solo path). It calls `service.get_stream_url(url, cb, err_cb)` **directly** — it does **not** go through `StreamResolver.resolve` (see F-WX-01-4). On success it calls `self.resolver.refresh(source, source_id, stream_url)` (`core/app.py:354`), which persists the same raw URL into `stream_cache.stream_url` and the in-memory `_mem`.

**Hop 3 — `core/api.py::play_track` (`:1437`) / `_resolve_track` (`:1608`).**
The resolved URL is stored as `track["file_path"]` (`api.py:1591` queue path, `api.py:1723` solo path). `file_path` therefore holds *either* a remote URL *or* a local file path — the same field, two meanings.

**Hop 4 — `audio/engine.py::_notify_track_changed` (`:78`).**
Builds `track["stream_url"]` = the proxy URL:

* remote (`engine.py:97-99`):
  `http://127.0.0.1:{port}/?url={quote(fp)}&source={src}&source_id={sid}&title={t}&artist={a}&k={token}`
* local file (`engine.py:115-117`):
  `http://127.0.0.1:{port}/api/stream?url={quote(fp)}&track_id={id}&source={src}&source_id={sid}&title={t}&artist={a}&k={token}`

**Hop 5 — `core/api.py::_on_track_changed` (`:1216-1225`)** — the *second, independent* construction, via `LocalProxyManager.get_proxy_url` (`core/proxy.py:1304`):

* `http://127.0.0.1:{port}/?url={urlencode(url)}&source={s}&source_id={sid}&k={token}` (remote)
* `http://127.0.0.1:{port}/api/stream?track_id={id}&source={s}&source_id={sid}&k={token}` (track-id form)

**Hop 6 — `core/proxy.py::StreamProxyHandler.do_GET` (`:694`).**
`KNOWN_PROXY_PATHS = ('/', '/api/cover', '/api/avatar', '/api/stream')` (`:40`).
Auth gate: `_authenticate` → `_authorized` (`:491-511`) reads **`AUTH_PARAM = 'k'`** (`proxy.py:31`), accepts the legacy alias `auth_token`, compares with `hmac.compare_digest`, **fails closed** when the server token is empty.
`/api/stream` with a `url=` param: local-file shortcut at `:742-751` → `_resolve_stream_local_file` (`:684`) → `_safe_stream_local_path` (`:238`); otherwise DB stream cache → on-disk `~/.nedotify/streams` probe → offline 503 → `engine.resolve_stream_url` → SSRF gate `:841` → upstream fetch → upstream `Content-Type` contains `mpegurl` ⇒ `_rewrite_hls_playlist` (`:396`).

**Hop 7 — frontend `js/player.js::loadAudioSource` (`:105`) / `normalizeAudioSourceUrl` (`:97`).**
`track.stream_url` (a proxy URL) is passed straight to `audioEl.src` / `hls.loadSource`.
A *raw local path* is converted by the frontend's own third construction:
`http://127.0.0.1:{PROXY_PORT}/api/stream?url={encodeURIComponent(src)}&k={PROXY_TOKEN}`.

**Token parameter — both ends quoted:**
* producer: `core/proxy.py:31` → `AUTH_PARAM = 'k'`; `core/proxy.py:1300-1302` → `return f'&{AUTH_PARAM}={urllib.parse.quote(self.token)}' if self.token else ''`
* consumer: `core/proxy.py:507` → `supplied = (query_params.get(AUTH_PARAM) or [''])[0]`
* frontend producer: `js/player.js:99` → `` const tokenQuery = window.PROXY_TOKEN ? `&k=${encodeURIComponent(window.PROXY_TOKEN)}` : ''; ``
⇒ **the parameter name matches on all three producers and the single consumer (`k`).** No mismatch found.

---

### 2. Findings

#### F-WX-01-1  [P1] — A failed stream resolution in the solo `play_track` path produces **no** user-visible error
- **File:** `core/api.py:1608-1744` (guard at `:1623-1629`, `:1716-1721`, `:1739-1742`); frontend callers `ui/web_new_v2/js/search-discovery.js:43`, `ui/web_new_v2/js/home.js:784`, `ui/web_new_v2/js/feature-controls.js:69`, `ui/web_new_v2/js/player.js:892/895/898`
- **Confirmed:** yes (executed against the real `AppApi._resolve_track`)
- **Description:** `play_track(track)` **without** a `track_list` goes to the `else` branch (`core/api.py:1606`) → `_resolve_track(track, lambda t: self._core.engine.play_track(t))`. When the provider yields nothing or raises, the error is emitted only when `_is_current()` is true — but `_is_current()` compares the requested track against `engine.queue.current_track`, which in the solo path still holds the **previous** track (the new track is only put into the queue by `play_callback` on *success*). So the guard is false, `_on_audio_error` is never called, and no `audio_error`/`error` event reaches the UI. `play_track` also returns `None` (not `{'success': False}`), so the frontend's `result?.success === false` check does not fire either.
- **Cause:** the staleness guard is expressed as "is this track the queue's current track?", but in the solo path the track is not in the queue yet. The guard is correct for the queue path (`queue.current_track is target_track`) and wrong for the solo path.
- **Trigger conditions:** a track whose stream cannot be resolved (deleted/DRM/private upload, provider outage, yt-dlp failure) clicked from a UI entry point that calls `play_track` without a list — i.e. the "Знакомая музыка" history cards, the home feed cards, the error-overlay "retry" action, and `togglePlayPause` when the `<audio>` element has no `src`.
- **User impact:** the click is **silently ignored** — no sound, no spinner, no toast; the previously playing track keeps playing and the UI still shows it. The user cannot tell whether the app failed or the click was missed.
- **Evidence:**
  ```python
  # core/api.py:1623-1629
  def _is_current():
      cur = self._core.engine.queue.current_track
      if cur is track:
          return True
      if not cur or not source_id:
          return False
      return cur.get("source") == source and cur.get("source_id") == source_id
  ```
  ```python
  # core/api.py:1716-1721 and :1739-1742
  def on_resolved(stream_url, metadata=None):
      if not stream_url:
          logger.warning(f"api.py -> on_resolved FAILED: {source}/{source_id}")
          if _is_current():
              self._on_audio_error(f"Не удалось найти поток для {track.get('title') or source_id}")
          return
  ...
  def on_resolve_error(err):
      logger.warning(f"api.py -> on_resolve error: {err}")
      if _is_current():
          self._on_audio_error(f"Не удалось найти поток для {track.get('title') or source_id}")
  ```
  ```javascript
  // ui/web_new_v2/js/search-discovery.js:43  (solo play_track, result not inspected)
  try { await window.pywebview.api.play_track({...entry.track,id:entry.track.track_id || entry.track.id}); }
  catch { window.dispatchEvent(new CustomEvent('nedotify:toast',{detail:{msg:'Не удалось включить трек. Повторите попытку.',type:'error'}})); }
  ```
- **Reproduction / verification:** scratch probe `wx01_fail.py` (in `%TEMP%\opencode\audit_scratch`) drives the real `AppApi._resolve_track` with a stubbed core:
  ```
  --- SOLO: play_track(track)  (search-discovery.js / home.js / feature-controls.js) ---
     errors emitted to the UI: []
  --- SOLO: provider raises (on_error path) ---
     errors emitted to the UI: []
  --- QUEUE: play_track(track, [track], 0) ---
     errors emitted to the UI: ['Не удалось найти поток для A']
  --- SOLO but the queue already holds the SAME track (frontend onTrackChanged path) ---
     errors emitted to the UI: ['Не удалось найти поток для A']
  ```
  i.e. the *same* failure is reported in the queue path and in the solo path **when the queue already holds the track**, and swallowed in the solo path when it does not.
- **Suggested fix:** give the solo path its own "this request is still the one the user asked for" check (e.g. a monotonically increasing request id on `AppApi`, compared in `on_resolved`/`on_resolve_error`), and/or return `{'success': False, 'error': …}` from the solo branch of `play_track` and have the frontend inspect it.
- **Fix side effects:** a request-id guard changes which of two overlapping resolutions may report; combined with F-WX-01-2 the two must be designed together. Returning a failure dict changes the bridge contract of `play_track` for existing callers that ignore the return value (harmless) and for `feature-controls.js:70` (which would then surface the error — intended).
- **Discovered by:** A

#### F-WX-01-2  [P1] — `_resolve_track` has no request-generation token: the *older* resolution wins the race
- **File:** `core/api.py:1713-1737` (`cur_start` capture at `:1714`, delivery at `:1734-1737`)
- **Confirmed:** yes (executed against the real `AppApi._resolve_track`)
- **Description:** `_resolve_track` captures `cur_start = self._core.engine.queue.current_track` once, at entry. The async callback delivers the track when `self._core.engine.queue.current_track is cur_start`. Two solo `play_track` calls issued back-to-back therefore share the same `cur_start`; the resolution that finishes **first** is delivered (it mutates the queue), and the second one is dropped because the queue no longer holds `cur_start`. There is no per-request token anywhere on the Python side.
- **Cause:** the guard answers "did the user move on?" with a *queue-identity* comparison. In the solo path the queue is not updated until a resolution succeeds, so the queue identity does not change between two clicks and cannot discriminate between them. The frontend's `playbackGeneration` (`js/player.js:23`) does not help: the decision is made in Python and the frontend only learns the outcome through `track_changed`.
- **Trigger conditions:** two clicks in quick succession on entries that use the solo path (`search-discovery.js:43`, `home.js:784`, `feature-controls.js:69`, `player.js:892/895/898`), where the first track's provider cascade is slower than the second's (or vice versa). The provider cascades are asynchronous and of very different durations (YouTube extraction + SoundCloud fallback), so the order is not deterministic.
- **User impact:** the user clicks track **B** and hears track **A**; B's resolution is discarded without any message, and the queue/now-playing shows A. The user must click B again.
- **Evidence:**
  ```python
  # core/api.py:1713-1737
  # Re-resolve stream url asynchronously
  cur_start = self._core.engine.queue.current_track

  def on_resolved(stream_url, metadata=None):
      ...
      if _is_current():
          cur = self._core.engine.queue.current_track
          cur["file_path"] = stream_url
          ...
          self._core.engine._notify_track_changed()
      elif self._core.engine.queue.current_track is cur_start:
          # Selection unchanged since resolution started: safe to deliver
          play_callback(track)
      # else: user moved on - drop stale resolution
  ```
- **Reproduction / verification:** scratch probe `wx01_race2.py` / `wx01_race3.py`:
  ```
  === two solo clicks (A then C), A's resolution finishes first ===
    queue after A resolved : A
    queue after C resolved : A
    => the user clicked C last; the track that ends up playing is 'A'

  SOLO  (A resolves first): ('A', [])
  SOLO  (C resolves first): ('C', [])
  QUEUE (A resolves first): ('C', [])     <- queue path is protected
  QUEUE (C resolves first): ('C', [])
  ```
  The queue path (`play_track(track, track_list, index)`) is safe because `on_queue_resolved` (`core/api.py:1586`) compares `self._core.engine.queue.current_track is target_track` — an identity check against the *newly selected* track, not a snapshot taken before the click.
- **Suggested fix:** introduce a monotonic request counter (e.g. `self._play_request_seq` on `AppApi`), stamp it into `_resolve_track`/`play_track`, and deliver/reject on the counter rather than on the queue snapshot; the frontend already has the analogous `playbackGeneration` concept.
- **Fix side effects:** the queue path must keep working when `play_track` is re-entered by the frontend's own "resolve in background" call (`js/player.js:1704`) — that call must not cancel the queue-path request for the same track, or the queue path would stop resolving at all. A per-(track, path) token, or "newest request wins unless it is the same track", is safer than a single global counter.
- **Discovered by:** A

#### F-WX-01-3  [P2] — When the loopback proxy is not running, the **raw signed CDN URL** is handed to the WebView
- **File:** `core/proxy.py:1304-1306` (`get_proxy_url`), `core/api.py:1216-1225` (`_on_track_changed`), `audio/engine.py:88-117`
- **Confirmed:** yes (by reading; the branch is unconditional)
- **Description:** `LocalProxyManager.get_proxy_url` returns the *unproxied* upstream URL when the proxy has no port:
  ```python
  def get_proxy_url(self, source, source_id, original_url=None, track_id=None):
      if not self.port:
          return original_url or ''
  ```
  `AppApi._on_track_changed` then stores that raw URL in `track_copy["stream_url"]` and emits `track_changed` with it. The frontend puts it straight into `<audio>.src` (`js/player.js:142`), so the browser fetches the provider CDN directly.
- **Cause:** the engine's own builder (`audio/engine.py:90`) guards on `self.proxy.port` and correctly leaves `stream_url` empty, but `AppApi._on_track_changed` has no such guard and treats `get_proxy_url`'s "raw URL" fallback as a valid proxy URL. The two builders disagree on the same field.
- **Trigger conditions:** the proxy failed to bind (`LocalProxyManager.start` swallows the exception, `core/proxy.py:1281-1282`) or was stopped. Then every cloud track plays *unproxied*.
- **User impact:** (a) the proxy is exactly what injects the provider credentials (`_inject_ydl_cookies`, `core/proxy.py:990-1006`); without it a YouTube/SoundCloud stream usually answers 403, so the user hears nothing and the player ends in the generic "Не удалось восстановить «трек»" toast after two retries; (b) the signed, time-limited CDN URL (which is a bearer credential in its own right) is exposed to the WebView DOM/logs. For a **local** track the same outage degrades differently — the engine leaves `stream_url` empty and the frontend builds a bogus `C:\…` `src` — so the two sources fail in two different ways.
- **Evidence:**
  ```python
  # core/proxy.py:1304-1306
  def get_proxy_url(self, source, source_id, original_url=None, track_id=None):
      if not self.port:
          return original_url or ''
  ```
  ```python
  # core/api.py:1216-1225
  if track_copy.get("source") in ("youtube", "soundcloud", "yandex", "vk"):
      if not track_copy.get("stream_url") and track_copy.get("file_path"):
          proxy_url = self._core.proxy.get_proxy_url(
              track_copy.get("source"),
              track_copy.get("source_id"),
              track_copy.get("file_path") or track_copy.get("source_url"),
              track_id=track_copy.get("id")
              )
          if proxy_url:
              track_copy["stream_url"] = proxy_url
  ```
  vs. the engine's guarded builder:
  ```python
  # audio/engine.py:88-92
  if fp and (fp.startswith("http://") or fp.startswith("https://")):
      # Remote stream URL: serve through proxy (SSRF-guarded), never expose raw URL
      if self.proxy and getattr(self.proxy, "port", None):
  ```
  (the comment states the intended contract — "never expose raw URL" — which `get_proxy_url`'s fallback breaks.)
- **Reproduction / verification:** static — `get_proxy_url` returns `original_url` verbatim whenever `self.port == 0`; `AppCore.__init__` calls `self.proxy.start()` (`core/app.py:158`) whose failure path only logs (`core/proxy.py:1281-1282`), leaving `port == 0` for the whole session. To observe: make the port bind fail (e.g. a sandbox that forbids `bind`) and inspect the `track_changed` payload.
- **Suggested fix:** make `get_proxy_url` return `''` (not the raw URL) when the proxy is down, and have `_on_track_changed` leave `stream_url` empty so the frontend shows its "loading / proxy unavailable" state instead of leaking the CDN URL.
- **Fix side effects:** the recovery path `core/playback_recovery.py:181` also uses `get_proxy_url`; returning `''` there would make `recover_stream` return an empty `stream_url`, which the frontend treats as a failed recovery (`js/player.js:476-481`) — acceptable, but the error text should say "proxy unavailable" rather than "track unavailable".
- **Discovered by:** A

#### F-WX-01-4  [P2] — The play path never goes through `StreamResolver.resolve`: the scenario's single-flight / "known unavailable" layer is bypassed
- **File:** `core/api.py:1604` and `core/api.py:1744` → `core/app.py:296-…` `re_resolve_stream_url_async`; `core/resolver.py:165` `StreamResolver.resolve` is reached only from `audio/engine.py:139-149` (`resolve_stream_url`), which is called **by the proxy** (`core/proxy.py:817/899/925`)
- **Confirmed:** yes
- **Description:** The scenario premise is `play_track → _resolve_track → StreamResolver.resolve → providers`. In the code, `_resolve_track`/`play_track` call `AppCore.re_resolve_stream_url_async`, which calls `service.get_stream_url(...)` **directly**. `StreamResolver.resolve` (the single-flight + mem/DB cache + the `_failed` "known unavailable" memo) is only on the *proxy* side of the handoff.
- **Cause:** two resolution front-ends exist. `re_resolve_stream_url_async` was written as a background-resolution helper and never routed through the resolver.
- **Trigger conditions:** every play of a cloud track.
- **User impact:** (a) the resolver's negative memo (`mark_unavailable` / `is_unavailable`, `core/resolver.py:97-122`) is never consulted by the play path, so a track that is known to be unplayable re-runs the whole cascade (three provider searches + two stream extractions) on every click — the exact cost the memo was written to avoid; (b) the frontend's own "resolve in background" call (`js/player.js:1704`) starts a **second** `re_resolve_stream_url_async` for the same track while the backend already has one in flight. The duplicate is only absorbed at the provider level (`YouTubeService._pending_streams`, `services/youtube_service.py:912-917`), so a provider without that coalescing would extract twice. Because the two requests resolve independently, they can complete in either order — which is what makes F-WX-01-2 reachable.
- **Evidence:**
  ```python
  # core/api.py:1744 (solo path) and :1604 (queue path)
  self._core.re_resolve_stream_url_async(source, source_id, callback=on_resolved, on_error=on_resolve_error, track=track)
  ```
  ```python
  # core/app.py:305-…, the worker calls the provider directly
  def worker():
      ...
      self.app_core.youtube.get_stream_url(video_url, cb, err_cb)
  ```
  ```python
  # core/resolver.py:165 — never called from the play path
  def resolve(self, source, source_id, resolver_fn: Callable[[], Tuple[Optional[str], Optional[str]]]) -> Optional[str]:
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:1695-1705 — the frontend re-requests a resolution
  } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
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
- **Reproduction / verification:** `grep -n "re_resolve_stream_url_async\|resolver\.resolve" core/ services/ audio/` → `resolver.resolve` appears only in `audio/engine.py:149`; `resolver.refresh` (the write side) is called from `core/app.py:354`, so the cache is *populated* by the play path but never *read* by it — `_resolve_track` reads `db.get_cached_stream(...)` directly (`core/api.py:1676`), bypassing the resolver's single-flight and its negative memo.
- **Suggested fix:** route `re_resolve_stream_url_async` through `StreamResolver.resolve` (or make `_resolve_track` use `resolver.get_cached_url`/`resolver.resolve`), and give the `track_changed` payload a "resolving" marker so the frontend does not re-issue a resolution the backend already has in flight.
- **Fix side effects:** the resolver's `_RESOLVE_TIMEOUT = 12.0` (`core/resolver.py:22`) is shorter than some provider cascades (YouTube 10 s + SoundCloud fallback budget), so a single-flight wait can time out and return `None` where the current direct call would eventually succeed. `core/app.py:446-465` already caps the SoundCloud fallback with `_SC_FALLBACK_BUDGET_S`; the two budgets must be reconciled before switching.
- **Discovered by:** A

#### F-WX-01-5  [P3] — A downloaded track re-streams from the network unless the UI happened to carry `file_path`
- **File:** `core/downloader.py:819` (`mark_track_downloaded`), `core/database.py:2134` (`set_cached_file` — never called by the downloader), `core/api.py:1648-1667` (the DB `file_path` lookup runs only for `source == "local"`), `core/offline.py:44-52` (offline mode *does* look the file up by row id)
- **Confirmed:** yes for the code paths; the user-visible consequence is conditional (see "Trigger conditions")
- **Description:** On download completion the backend writes the file into `~/.nedotify/downloads/` and updates `tracks.file_path` (`UPDATE tracks SET is_downloaded = 1, file_path = ?`), but never populates `stream_cache.cached_file_path` for `(source, source_id)`. The play path therefore finds the local file only if the *track dict handed to `play_track`* already carries `file_path` (`core/api.py:1520`/`1643`). The DB lookup by row id that would find it exists only in the `source == "local"` branch (`core/api.py:1648-1667`) and in `core/offline.py::available_track`.
- **Cause:** the "where is this track's local file?" question is answered in three different places with three different rules: `tracks.file_path` by row id (offline), `stream_cache.cached_file_path` by `(source, source_id)` (play path), and the track dict's own `file_path` (the only one the play path actually uses for non-local sources).
- **Trigger conditions:** the user downloads a YouTube/SoundCloud track and then plays it from a surface whose track dict has no `file_path` (home feed, search results, "Знакомая музыка") rather than from the Downloads list (whose dicts come from `get_downloaded_tracks()` = `SELECT * FROM tracks`, so they do carry it).
- **User impact:** the track plays from the network again — data is consumed, the download appears pointless, and the user gets no hint that a local copy exists. In offline mode the same track *is* found locally (`core/offline.py`), so the behaviour differs between the two modes for the same track.
- **Evidence:**
  ```python
  # core/downloader.py:818-819
  try:
      self._core.db.mark_track_downloaded(track_id, file_path)
  ```
  ```python
  # core/api.py:1648-1667 — the DB lookup is gated on source == "local"
  if source == "local" and not fp:
      t_id = track.get("id")
      if t_id:
          try:
              db_t = self._core.db.get_track(int(t_id))
              if db_t and db_t.get("file_path"):
                  fp = db_t["file_path"]
                  track["file_path"] = fp
  ```
  versus
  ```python
  # core/offline.py:44-52 — offline mode finds it for ANY source
  identifier = track.get('track_id') or track.get('id')
  if identifier is not None:
      try:
          stored = db.get_track(int(identifier))
      except (TypeError, ValueError):
          pass
  if stored:
      path = _local_file(stored.get('file_path'))
      if path:
          return _with_file(dict(stored, **track), path)
  ```
- **Reproduction / verification:** `grep -n "set_cached_file" -r core services audio` → only `core/database.py:2134` (definition) and `core/proxy.py:810/1207/1214` (the proxy's own cache writes). The downloader never calls it.
- **Suggested fix:** have the download completion also call `db.set_cached_file(source, source_id, file_path)`, and/or extend the `_resolve_track` DB lookup to non-local sources (same rule as `core/offline.py::available_track`).
- **Fix side effects:** `set_cached_file` would make `stream_cache` point at the download; `core/proxy.py:797` then serves the *download* for `/api/stream` requests — which is the desired behaviour but changes cache-file lifetime semantics (the download is no longer disposable cache). It also affects `core/offline.py::available_tracks` (which already reads `cached_file_path`).
- **Discovered by:** A

#### F-WX-01-6  [P3] — The rewritten HLS playlist drops `source_id`, so an expired segment cannot self-heal inside the proxy
- **File:** `core/proxy.py:396-418` (`_rewrite_hls_playlist` / inner `local_url`), `core/proxy.py:1024` (self-heal branch)
- **Confirmed:** yes
- **Description:** `_rewrite_hls_playlist` re-points every nested playlist, key URI and segment at the proxy as `/?url=<absolute>&source=<source>&k=<token>`. The token **is** carried (verified below), but `source_id` is not. The proxy's 403/410 self-healing branch requires `source and source_id`:
  ```python
  if e.code in (403, 410) and source and source_id and attempt == 0:
  ```
  so a segment request that comes back 403 (expired CDN token — the normal failure mode for a long HLS session) is returned to hls.js as-is instead of being re-resolved.
- **Cause:** the rewritten URL carries the minimum needed to *fetch* the resource, but not the identity needed to *renew* it.
- **Trigger conditions:** an HLS session whose segment URLs expire mid-playback (SoundCloud/YouTube HLS streams), or a provider that rotates its segment host.
- **User impact:** the stream breaks and the frontend falls back to its own recovery (`handleStreamError` → `recover_stream`, `js/player.js:462-483`), which re-resolves the whole track and restarts playback from the current position. The user hears a short gap and a resume blip instead of a seamless segment renewal.
- **Evidence:**
  ```python
  # core/proxy.py:402-408
  def local_url(value):
      absolute = urllib.parse.urljoin(upstream_url, value)
      if urllib.parse.urlsplit(absolute).scheme not in ('http', 'https'):
          raise ValueError('Unsupported HLS resource scheme')
      return '/?' + urllib.parse.urlencode({
          'url': absolute, 'source': source or '', 'k': token,
      })
  ```
  ```python
  # core/proxy.py:1024
  if e.code in (403, 410) and source and source_id and attempt == 0:
  ```
  Actual rewritten output (probe `wx01_probe.py`):
  ```
  #EXTM3U
  #EXT-X-KEY:METHOD=AES-128,URI="/?url=https%3A%2F%2Fcdn.example%2Fhls%2Fkey.bin&source=youtube&k=TOKEN"
  /?url=https%3A%2F%2Fcdn.example%2Fhls%2Fseg1.ts&source=youtube&k=TOKEN
  ```
  The `k=` token is present in every rewritten URL and the URLs are root-relative, so hls.js resolves them against the manifest's own origin (the proxy) — the token survives the resolution.
- **Reproduction / verification:** call `_rewrite_hls_playlist(text, upstream_url, 'youtube', 'TOKEN')` and inspect the output (as above); then check `query_params.get('source_id')` for a rewritten segment → `None` → the `and source_id` clause of `core/proxy.py:1024` is False.
- **Suggested fix:** include `source_id` in the rewritten query (it is already known by the caller in both the `/` and `/api/stream` branches).
- **Fix side effects:** the segment URL grows; the proxy's `do_GET` `/` branch would then also carry `source_id`, which it uses to build `track_info` for re-resolution — that is the intent, but it also means a stale `source_id` could re-resolve the wrong track if the URL was copied.
- **Discovered by:** A

#### F-WX-01-7  [P3] — A local file the proxy refuses is reported as `400 "Resolved stream URL blocked by SSRF validation"`, not as "file not found"
- **File:** `core/proxy.py:733-751` (`/api/stream` local shortcut), `core/proxy.py:841-847` (SSRF 400), `core/proxy.py:238-272` (`_safe_stream_local_path`)
- **Confirmed:** yes (code path); the *reachability* of the "path spelling mismatch" sub-case is a hypothesis
- **Description:** In the `/api/stream` branch, a `url=` parameter that is a local path is only served when `_safe_stream_local_path` accepts it (inside `~/.nedotify`, or referenced by a `tracks.file_path` row). When it is refused, the code does **not** answer 404; it falls through to the resolution branch, sets `target_url = url_param` (the Windows path itself) and answers **400 "Resolved stream URL blocked by SSRF validation"**.
- **Cause:** the "not servable" case and the "not a URL" case share one variable. The local-file gate returns `''`, and `''` is indistinguishable from "no local file here", so the path is reused as a remote URL.
- **Trigger conditions:** a local file that is neither under `~/.nedotify` nor listed in `tracks.file_path` — e.g. a library file whose stored path uses forward slashes (`C:/Music/x.mp3`) while the request path is normalised to backslashes (`os.path.normpath`), which makes `_referenced_by_library`'s `LOWER(file_path) = LOWER(?)` comparison fail; or a file deleted after the track dict was built.
- **User impact:** the user gets a generic "stream failed" toast after the retry loop ("Не удалось восстановить «трек»") instead of "the file is missing", and the log shows an SSRF warning for a path that was never an SSRF attempt — misleading for support and for the security log.
- **Evidence:**
  ```python
  # core/proxy.py:742-751
  if url_param:
      local_path = url_param.strip()
      if local_path.startswith('file:///'):
          local_path = urllib.request.url2pathname(local_path[7:])
      elif local_path.startswith('file://'):
          local_path = urllib.request.url2pathname(local_path[6:])
      allowed_local = self._resolve_stream_local_file(local_path)
      if allowed_local:
          self.serve_local_file(allowed_local)
          return None
  ```
  ```python
  # core/proxy.py:817-847
  target_url = url_param or self.server.app_core.engine.resolve_stream_url(track)
  ...
  if not _is_ssrf_safe_url(target_url):
      logger.warning('SSRF guard blocked resolved stream URL for %s:%s', source, source_id)
      try:
          self.send_error(400, 'Resolved stream URL blocked by SSRF validation')
  ```
  ```python
  # core/proxy.py:266-268
  if _referenced_by_library((candidate, resolved), db):
      return resolved
  logger.warning('Refused /api/stream read of unlisted local file: %s', candidate)
  return ''
  ```
- **Reproduction / verification:** scratch probe `wx01_probe.py`: for a local path the gate returns `''`; following the code, `target_url` becomes the path and `_is_ssrf_safe_url(<windows path>)` is False → the 400 branch is taken. To observe the concrete 400 end-to-end, request `/api/stream?url=<a path outside ~/.nedotify that is not in `tracks`>&k=<token>` against the harness in `tests/test_proxy_harness.py` and assert the status is 400 (today) / 404 (expected).
- **Suggested fix:** distinguish "a local path was supplied but is not servable" from "no local path supplied" and answer 404 with a distinct message before the resolution branch.
- **Fix side effects:** the current fall-through is what lets the proxy re-resolve a track whose local file vanished (`core/proxy.py:891-899` does the same for the `/` branch). A blanket 404 would remove that fallback, so the check must be limited to the case where a local-looking path was supplied and refused.
- **Discovered by:** A

---

### 3. Clean areas

* **Proxy auth token contract.** `AUTH_PARAM = 'k'` (`core/proxy.py:31`) is used identically by all three producers (`core/proxy.py:1302` `auth_query`, `core/proxy.py:1314`/`1332` `get_proxy_url`, `ui/web_new_v2/js/player.js:99` `normalizeAudioSourceUrl`) and by the single consumer (`core/proxy.py:507`). `_authorized` fails closed on an unset token and compares with `hmac.compare_digest`; `_authenticate` is the shared gate for GET and HEAD (`core/proxy.py:633`, `:698`). The token is redacted from the proxy log (`core/proxy.py:489`). **No mismatch found.**
* **Local-file round-trip through the proxy.** Verified for a path containing spaces, Cyrillic, `#`, `%` and parentheses: `urllib.parse.quote` (engine) and `encodeURIComponent` (frontend) both survive `parse_qs` unchanged, and `_safe_stream_local_path` receives the identical string from both sides (probe `wx01_probe.py`). The backend `?url=` form and the frontend `?url=` form decode to the same path, so the two independent constructions agree on the value (they differ only in the extra `track_id`/`source`/`source_id`/`title`/`artist` parameters the backend adds, which the proxy treats as optional).
* **The frontend receives a proxy URL, not a `file://` URL.** For a local file the backend publishes `http://127.0.0.1:<port>/api/stream?url=<path>&…&k=<token>` (`audio/engine.py:115-117`); the frontend's own `normalizeAudioSourceUrl` (`js/player.js:97-103`) produces the same shape for the raw-path case. `tests/test_playback_latency_ui.py:144-150` pins this. `file://` inputs are handled correctly by the proxy (`core/proxy.py:744-747`, `url2pathname`).
* **HLS rewrite keeps the token and resolves against the proxy origin.** `_rewrite_hls_playlist` emits root-relative `/?url=…&source=…&k=<token>` URLs; hls.js resolves them against the manifest's own origin (the proxy), and the token is embedded in every rewritten URL, so segment/key requests authenticate. The `Content-Type` check (`core/proxy.py:1128`) and the `application/vnd.apple.mpegurl` response are correct, and the CORS headers are sent for the manifest (`core/proxy.py:1143`).
* **Offline mode.** `play_track` intercepts offline before any resolution (`core/api.py:1439-1448`), reports `{'success': False, 'code': 'offline'}` and emits `audio_error`, and the frontend renders it (`js/events.js:378-385`, which also clears `_pendingResolveKey`). The proxy answers `503 Offline mode` for uncached tracks (`core/proxy.py:814-816`).
* **Stream expiry.** `stream_url_expired` (`utils/stream_urls.py:7`) is applied consistently at `core/api.py:1521`, `:1644`, `core/resolver.py:127/154` and `core/proxy.py` (via the 403/410 self-heal branch and `BaseMusicService.get_from_cache`), and the expired URL is dropped rather than replayed.
* **`download_complete` contract.** The backend emits exactly `{'track_id': track_id}` (`core/downloader.py:839`) — no `file_path` — and `js/events.js:258-264` does not try to read one; it re-reads the library instead. The play path then finds the file: the Downloads list is built from `get_downloaded_tracks()` = `SELECT * FROM tracks` (`core/database.py:1284-1287`), so those track dicts carry `file_path`, and `play_track` uses it (`core/api.py:1520-1529`). **Contract #7 is honoured.**
* **Queue-path race protection.** The `track_list` path guards the delivery with `self._core.engine.queue.current_track is target_track` (`core/api.py:1586`, `:1601`) — an identity check against the newly selected track, verified to be order-independent (probe `wx01_race3.py`: `QUEUE (A resolves first): ('C', [])`).
* **Duplicate provider extractions are absorbed.** The frontend's second `play_track` (`js/player.js:1704`) does start a second `re_resolve_stream_url_async`, but `YouTubeService.get_stream_url` coalesces it through `_pending_streams` (`services/youtube_service.py:912-917`) and `BaseMusicService._join_request` (`services/base_service.py:140-161`) does the same for the other providers.
* **Proxy path allow-list.** `KNOWN_PROXY_PATHS` (`core/proxy.py:40`) covers every path the three URL builders emit (`/`, `/api/stream`); an unknown path is refused with 404 instead of falling into the resolution branch.

---

### 4. Coverage gaps

* **`services/soundcloud_service.py`, `services/track_resolver.py`** were **not** read line-by-line; the SoundCloud hop was traced through `BaseMusicService.get_stream_url`/`_join_request` and the proxy's credential injection (`core/proxy.py:996-1000`) only. The SoundCloud HLS URL shape (and therefore the exact `source` value in the rewritten playlist) is therefore taken from the call site, not from the provider.
* **`services/yandex_service.py` / `vk_service.py`**: the `music.yandex.ru` divergence between the engine's host list (`audio/engine.py:95`) and `get_proxy_url`'s (`core/proxy.py:1307`) was analysed statically but not exercised; I could not confirm whether a Yandex direct-media URL ever reaches `get_proxy_url` in practice (the engine normally fills `stream_url` first, making the api-level builder a fallback only).
* **The live HTTP round-trip through the proxy was not executed** (no app was started, per the ground rules). The proxy behaviours above were verified by reading `core/proxy.py` plus the existing harness in `tests/test_proxy_harness.py`; only the URL/path algebra was executed (scratch probes under `%TEMP%\opencode\audit_scratch`, nothing in the repo was modified).
* **`main.py` / the WebView origin** was not traced in full: the CORS conclusion (`_send_cors_headers` echoing a loopback `Origin`) assumes the UI is served over `http://127.0.0.1:<port>` by pywebview's Bottle server, which I did not confirm by running the app.
* **The `recover_stream` path (`core/playback_recovery.py`) was read but not executed**; in particular the `same_recording` gate (`core/playback_recovery.py:14-37`) and its interaction with the HLS/YouTube fallback were not exercised.
* **`core/database.py::get_cached_stream` (`:2149`) was read only at its signature** (default `max_age_seconds=14400`); the play path calls it *without* a `max_age` (`core/api.py:1533`, `:1676`), so it uses that default — consistent with `StreamResolver._DB_MAX_AGE` — but the row-level expiry check inside the DB was not read.
* **The "second `play_track` from `js/player.js:1704` duplicates the backend resolution" claim was not measured** (no network); it is derived from the call graph and from the provider-level coalescing in `services/youtube_service.py:912-917`.
