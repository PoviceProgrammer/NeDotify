## SCENARIO WX-11 — Network loss during playback and recovery after connectivity returns — ROLE B

### 1. Scope reviewed

**Files opened (physical line ranges actually read):**

- `core/playback_recovery.py` — 1-183 (whole file)
- `core/resolver.py` — 1-271 (whole file)
- `core/proxy.py` — 1-160, 366-597, 694-983, 983-1262, 1290-1334
- `core/api.py` — 155-234, 372-519, 1112-1141, 1180-1379, 1440-1779, 4130-4228
- `core/app.py` — 280-509 (+ grep for `resolver`/`on_error`)
- `core/database.py` — 2125-2254
- `core/user_errors.py` — 1-24 (whole file)
- `core/offline.py` — 1-77 (whole file)
- `core/settings.py` — grep (`browser_cookies`, `offline_mode`, `auto_cache_streams`)
- `services/base_service.py` — 1-329 (whole file)
- `services/youtube_service.py` — 30-169, 240-399, 760-889, 880-1029, 1029-1190
- `services/soundcloud_service.py` — 14-128, 160-229, 295-364, 500-569, 569-795
- `services/music_matching.py` — 1-95 (whole file)
- `utils/stream_urls.py` — 1-26 (whole file)
- `utils/cache_manager.py` — 286-400
- `ui/web_new_v2/js/player.js` — 100-179, 380-579, 580-699, 698-947
- `ui/web_new_v2/js/main.js` — 560-599
- `main.py` — 90-169
- `.venv_win/Lib/site-packages/webview/util.py` — 290-334 (pywebview JS-API threading)
- `tests/test_playback_recovery.py` — 1-119 (whole file)

**Callees traced into other areas (list):**

- WN-11 `core/proxy.py` → `core/api.py::_is_ssrf_safe_url` (SSRF guard), `core/app.py::re_resolve_stream_url_async` (proxy self-heal), `core/database.py::{get_cached_stream,set_cached_file}`
- WN-15 `core/resolver.py` → `core/database.py::{get_cached_stream,cache_stream,invalidate_cached_stream}`, `utils/stream_urls.py::stream_url_expired`
- WN-15 `core/playback_recovery.py` → `services/base_service.py::BaseMusicService._stream_cache`, `services/music_matching.py::same_recording` helpers, `core/offline.py::is_offline`, `core/proxy.py::get_proxy_url`
- WN-05/WN-29 `core/api.py` → `ui/web_new_v2/js/player.js::handleStreamError` (the only caller of the `recover_stream` bridge method)
- WN-02 `core/app.py::re_resolve_stream_url_async` → `services/youtube_service.py`, `services/soundcloud_service.py`
- WN-19/WN-20 providers → `services/base_service.py::_SharedExecutor` (shared 8-worker pool)
- WN-16 `core/user_errors.py::describe_error` → `core/api.py::_on_audio_error`

---

### 2. Findings

#### F-WX-11-1  [P1] — No circuit breaker, no cross-attempt backoff: every manual Play press during an outage re-runs the whole provider cascade (~15-40 provider HTTP requests per press)

- **File:** `core/app.py:296-506` (+ `core/app.py:44`), `core/playback_recovery.py:95-183`, `ui/web_new_v2/js/player.js:859-903`
- **Confirmed:** yes
- **Description:** Nothing in the failure/recovery path limits how often the providers are contacted. There is no circuit breaker (no "provider unreachable → stop calling for N seconds"), no shared backoff between attempts, and no per-provider rate limiter. The only bound is the *per-attempt* time budget (`playback_recovery`'s 18 s deadline, `app.py`'s 20 s SoundCloud budget) and the *per-track* JS retry counter (2). Both are reset by a manual Play press.
- **Cause:** The retry counter lives in the frontend and is reset on every non-recovery `playTrack` (`player.js:719-722`) and on every manual resume (`player.js:906`). The backend's `re_resolve_stream_url_async` — which is the *other*, unbounded path to the providers — has no state at all: each call spawns a fresh thread (`core/app.py:506`) and runs a fresh cascade.
- **Trigger conditions:** Network is down (or the CDN is unreachable) and the user keeps pressing Play / clicking the track in the library. Every press re-enters `core/app.py::play_track` → `re_resolve_stream_url_async` → `youtube.get_stream_url` (a full yt-dlp extraction) → on failure `_on_err` → the SoundCloud fallback chain over up to 6 query variants, bounded only by `_SC_FALLBACK_BUDGET_S = 20.0`.
- **User impact:** The provider sees a sustained burst from one IP. The app's own codebase names the failure mode it will cause: `_YT_GATED_MSG = "YouTube не отдал аудиоформаты (anti-bot гейт …)"` and `_YT_GATING_MARKS` include `"confirm you're not a bot"` (`services/youtube_service.py:60-79`). The user gets gated/banned and the app cannot play anything.
- **Evidence:**
  ```python
  # core/app.py:379-497  (the fallback chain that runs on EVERY failed resolution)
  def _on_err(err):
      if offline_result(): return
      if source == "youtube" and hasattr(self, "soundcloud") and self.soundcloud:
          ...
          c_queries = []                       # up to 6 variants built from title/artist
          ...
          def try_search_candidates(idx=0, _started=None):
              if _started is None: _started = time.monotonic()
              elapsed = time.monotonic() - _started
              if idx >= len(candidates) or elapsed > _SC_FALLBACK_BUDGET_S:   # 20 s
                  ...
              self.soundcloud.search(sq, max_results=3, callback=on_sc_search_res, ...)
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:905-907  — a manual press wipes the retry counter
  if (activeAudio.paused) {
      currentTrackRetries = 0;
      activeAudio.play().catch(e => console.error("Play error:", e));
  ```
- **Reproduction / verification:** Block egress (or point the proxy at a blackhole) and press Play repeatedly. Instrument `services/soundcloud_service.py::search` and `services/youtube_service.py::get_stream_url` and count calls per press — observed path: 1 yt-dlp extraction (3-10 HTTP requests to `youtube.com`/`youtubei.googleapis.com`) + up to 6 × (`api-v2.soundcloud.com/search/tracks` + `api-v2.soundcloud.com/tracks/<id>` + transcoding + CDN probe) = **~15-40 provider HTTP requests per press**. At 1 press / 3 s over 600 s that is **3 000-8 000 provider HTTP requests from one IP**, plus **~800 upstream CDN connection attempts** (4 per proxy GET: `core/proxy.py:1009 max_retries = 3`, `1012 for attempt in range(max_retries + 1)`).
- **Suggested fix:** Introduce one owner for "the provider is unreachable" — e.g. a per-(provider, host) circuit breaker in `core/resolver.py` (or a new `core/network_policy.py`) that opens after N consecutive transport failures and short-circuits resolution for a cooldown, plus a per-provider minimum interval between cascades. `re_resolve_stream_url_async` and `playback_recovery` should both consult it.
- **Fix side effects:** A breaker that opens too eagerly must not strand a user who reconnects; it needs a half-open probe and a "user pressed play" override, otherwise recovery after connectivity returns (the second half of this scenario) would be blocked by the breaker the outage opened.
- **Discovered by:** B

#### F-WX-11-2  [P1] — The recovery budget bounds latency, not work: `_callback_result` abandons the provider task instead of cancelling it, so orphaned extractions pile up in the shared 8-worker pool and all fire at the provider when connectivity returns

- **File:** `core/playback_recovery.py:40-63`, `core/playback_recovery.py:121-165`, `services/base_service.py:124`, `services/youtube_service.py:1069`, `services/soundcloud_service.py:594-599`
- **Confirmed:** yes
- **Description:** `recover_stream` has an 18 s deadline and splits it into per-call waits (8 s primary, 3 s per fallback search, 4 s per fallback extraction). When a wait expires, `_callback_result` sets the completion event and returns `(None, {})` — but the provider task it started is **still running** and is never cancelled. The submitted work (a yt-dlp extraction, a SoundCloud API search) continues to completion, and if it *succeeds* after the timeout its URL is silently discarded (`completed.is_set()` → the callback returns immediately).
- **Cause:** The provider APIs are callback-based and offer no cancellation handle. The recovery treats "wait timeout" as "task finished", so the 18 s budget constrains only what the user waits for, not how much provider work is in flight.
- **Trigger conditions:** Any outage, or simply a slow provider (a yt-dlp extraction with `socket_timeout: 8, retries: 1, extractor_retries: 1` can occupy a pool worker for 15-30 s).
- **User impact:** (a) A recovery can report failure and show the error toast while a *successful* extraction lands 1 s later and is thrown away — the user retries for nothing. (b) The shared provider pool is starved and its queue grows without bound (see below). (c) After connectivity returns, a backlog of stale extractions fires at the provider at once — precisely the "recovery after connectivity returns" moment.
- **Evidence:**
  ```python
  # core/playback_recovery.py:40-63
  def _callback_result(invoke, timeout):
      completed = threading.Event()
      result = {}
      def success(value, metadata=None):
          if completed.is_set(): return          # <-- the late success is DROPPED
          result.update(value=value, metadata=metadata or {})
          completed.set()
      ...
      try:
          invoke(success, failure)
      except Exception as error:
          failure(error)
      if not completed.wait(max(0, timeout)):
          completed.set()                          # <-- task is abandoned, NOT cancelled
          return None, {}
      return result.get("value"), result.get("metadata", {})
  ```
  ```python
  # services/base_service.py:124  — one pool for EVERY provider, unbounded queue
  _executor = _SharedExecutor(max_workers=8)
  ```
  ```python
  # services/youtube_service.py:1069 — the work that outlives the budget
  self._executor.submit(_extract)
  ```
- **Reproduction / verification:** Instrument `services/base_service.py::_SharedExecutor.submit` and count `pool._work_queue.qsize()` while the network is blackholed and the user presses Play. Arrival rate ≈ 1-7 provider tasks per press (≈ 2.3 tasks/s at 1 press / 3 s); service rate ≈ 8 workers / ~10 s per task ≈ 0.5-1 task/s ⇒ the `ThreadPoolExecutor` backlog grows linearly and is in the several-hundred range after 10 minutes. It then drains against the provider the moment the network returns. *Measured queue depth is an estimate from the code's timeouts, not an instrumented run.*
- **Suggested fix:** Make the provider layer cancellable (a per-request `threading.Event` that the extraction checks between phases) and have `_callback_result` signal it on timeout; and/or give the recovery its own bounded executor separate from the shared 8-worker pool so a recovery storm cannot starve search/normal playback.
- **Fix side effects:** Cancelling mid-extraction risks leaving yt-dlp's `_pending_streams` entry dangling (`services/youtube_service.py:919-921` pops it in `finish()`), so the cancel path must still call `finish()` to release the listeners.
- **Discovered by:** B

#### F-WX-11-3  [P2] — The resolver's negative cache is dead code: `mark_unavailable` is never called, so the documented "skip the cascade for a known-dead track" never happens and `mark_unavailable` itself does no failure classification

- **File:** `core/resolver.py:24-28`, `core/resolver.py:97-122`, `core/resolver.py:178-185`, `core/playback_recovery.py:85`
- **Confirmed:** yes (verified by exhaustive grep of the non-test tree)
- **Description:** `StreamResolver` implements a negative cache (`self._failed`, `_FAIL_TTL = 120.0`, `_FAIL_MAX_SIZE = 512`) with `mark_unavailable()`, `is_unavailable()` and `clear_unavailable()`. Nothing in production code ever calls `mark_unavailable` — only `tests/test_soundcloud_drm_unavailable.py` does. Consequences: (a) `resolve()`'s "skip a known-dead track" branch (`core/resolver.py:181-185`) is unreachable, so a genuinely dead track re-runs the *entire* cascade on every request; (b) `playback_recovery.py:85`'s `resolver.clear_unavailable(...)` is a no-op; (c) `mark_unavailable` performs **no classification of the failure** — it stores whatever `reason` string the caller passes, so the "a transient network error must not be cached as unavailable" invariant is currently upheld only by the *absence* of any caller, not by a rule.
- **Cause:** The negative cache was designed for a caller that reports a provider's own "this track is gone" verdict; that caller was never written (or was removed), leaving an orphaned policy.
- **Trigger conditions:** Always. Any request for a track the provider cannot deliver re-runs the full cascade (up to 3 provider searches + 2 stream extractions per `core/resolver.py:178-180`'s own comment).
- **User impact:** The negative-cache blast radius of a 30 s outage is **0 tracks, for 0 seconds** — nothing is wrongly blacklisted. But the *positive* consequence of the same dead code is the retry-storm amplifier of F-WX-11-1: a track that is permanently gone is re-resolved on every single click instead of being skipped.
- **Evidence:**
  ```python
  # core/resolver.py:24-28
  #: A key whose cascade just produced nothing is skipped for this long. Short on
  #: purpose: a DRM-protected or deleted track keeps the same answer for good,
  #: while a network blip is retried two minutes later instead of forever.
  _FAIL_TTL = 120.0
  _FAIL_MAX_SIZE = 512
  ```
  ```python
  # core/resolver.py:178-185  — unreachable in production
  # A track a provider already declared unplayable costs nothing to skip.
  # Without this the whole cascade (up to three provider searches plus two
  # stream extractions) reruns on every request for the same dead track.
  if self._is_failed(key):
      logger.info(f"Skipping resolution of {source}:{source_id}: already known unavailable")
      return None
  ```
  Grep over `core/`, `services/`, `ui/`, `audio/`, `utils/` (excluding `tests/` and `android/`) returns **only** the definition site; the only live negative cache in the tree is `services/soundcloud_service.py::_unavailable_cache` (a different class).
- **Reproduction / verification:** `Get-ChildItem -Recurse -Include *.py,*.js,*.html | Select-String 'mark_unavailable|is_unavailable'` outside `tests/` → only `core/resolver.py:97,98,101,108` and `services/soundcloud_service.py`'s own `_mark_unavailable`. Run `pytest tests/test_soundcloud_drm_unavailable.py` → it passes because it calls `mark_unavailable` directly, which is why the dead code survived.
- **Suggested fix:** Either wire `mark_unavailable` to the providers' own "track is gone" verdicts (SoundCloud already computes one — `_is_unplayable_error`), or delete the `_failed`/`_FAIL_TTL`/`mark_unavailable`/`is_unavailable`/`clear_unavailable` machinery. If it is kept, add the classification *inside* `mark_unavailable` (accept an explicit `permanent: bool` or a typed failure kind) so a transport error can never be recorded as "unavailable".
- **Fix side effects:** Wiring it in changes resolution latency for dead tracks (better) but introduces a new class of bug if a *transient* failure is classified as permanent — the 120 s TTL bounds the damage to 512 tracks × 2 minutes, but the track would be unplayable for 2 minutes after a single blip.
- **Discovered by:** B

#### F-WX-11-4  [P2] — The recovery persists a provider-supplied URL into the resolver memory and the DB after only a scheme+hostname check; the SSRF guard is applied only later, at the proxy

- **File:** `core/playback_recovery.py:168-181`, `core/resolver.py:232-236`, `core/resolver.py:256-267`, `core/database.py:2162-2197`
- **Confirmed:** yes
- **Description:** After a successful re-resolution, `recover_stream` validates the URL only as "scheme is http/https and a hostname exists", then writes it into the shared caches (`resolver.refresh` → `_persist` → resolver memory + `db.cache_stream`). `_is_ssrf_safe_url` (`core/api.py:161-195`) is *not* consulted. The same is true of `core/app.py::_on_resolved` (line 354) and of the proxy's own self-heal, which *does* check (`core/proxy.py:1054-1056`) but only after `resolver.invalidate` already ran.
- **Cause:** The SSRF guard lives in the egress component (the proxy) and is treated as sufficient; the persistence component has no view of it. The guard is applied at *fetch* time, not at *trust* time.
- **Trigger conditions:** A provider (or a compromised/misconfigured one) returns a URL pointing at a loopback/private/decimal-IP host — e.g. `http://127.0.0.1:8080/x`, `http://2130706433/x`, `http://169.254.169.254/latest/meta-data/`. The URL is then stored in the DB `stream_cache` row (4 h read cutoff) and in the resolver memory (1 h).
- **User impact:** No direct egress today — the proxy re-checks every fetched URL (`core/proxy.py:841` for `/api/stream`, `954` for `/`, and `SafeRedirectHandler.redirect_request` on every redirect), so the request is answered 400 and nothing is fetched. The residual risk is a poisoned shared cache that any future consumer of `resolver.get_cached_url()` / `db.get_cached_stream()` would trust.
- **Evidence:**
  ```python
  # core/playback_recovery.py:168-181
  if not stream or stream_url_expired(stream):
      return {"ok": False, "code": "source_unavailable", ...}
  parsed = urlparse(str(stream))
  if parsed.scheme not in ("http", "https") or not parsed.hostname:
      return {"ok": False, "code": "invalid_stream", "error": "Источник вернул некорректный адрес"}
  ...
  resolver = getattr(core, "resolver", None)
  if resolver:
      resolver.refresh(source, identifier, stream)      # <-- persisted with NO SSRF check
  ```
  Compare with the proxy, which does check:
  ```python
  # core/proxy.py:1054-1056
  if new_url and not _is_ssrf_safe_url(new_url):
      logger.warning('SSRF guard blocked re-resolved URL for %s:%s', source, source_id)
      new_url = None
  ```
- **Reproduction / verification:** Unit-level: build a fake provider whose `get_stream_url` returns `http://127.0.0.1:9/x`, call `core.playback_recovery.recover_stream(core, track)` with a `StreamResolver` backed by a temp DB, then assert `resolver.get_cached_url('youtube', id)` returns the loopback URL and the `stream_cache` row contains it — while `core.api._is_ssrf_safe_url(url)` returns `False`. (The proxy would still block it at fetch time.)
- **Suggested fix:** Apply `_is_ssrf_safe_url` (imported from `core.api`, the same way `core/proxy.py:23` already does) at the point where a provider-supplied URL is written into the resolver memory / DB, so an unsafe URL is never trusted or persisted.
- **Fix side effects:** `_is_ssrf_safe_url` performs a DNS resolution (memoized per host in `core/api.py:157`); adding it to the resolution hot path adds a lookup for CDN hosts whose DNS can change. It must stay behind the existing `_dns_resolves_to_public_ip` memo.
- **Discovered by:** B

#### F-WX-11-5  [P2] — The recovery path is completely unlogged, and the `<audio>` error never reaches the backend at all: `core/playback_recovery.py` has no logger and `AudioEngine` has no `on_error`

- **File:** `core/playback_recovery.py` (whole file), `core/api.py:381-382`, `core/api.py:1255-1260`, `core/proxy.py:1235-1241`, `ui/web_new_v2/js/player.js:659-671`
- **Confirmed:** yes
- **Description:** Three gaps stack up, so a network failure during playback is invisible in `~/.nedotify/logs/app.log`:
  1. `core/playback_recovery.py` does not import `logging` and has no `logger` — not one line is written for "recovery started", "provider returned nothing", "fallback used", "recovery succeeded". Verified at runtime: `hasattr(core.playback_recovery, 'logger') == False`.
  2. The mid-stream break in the proxy is logged at **DEBUG**: `logger.debug(f'Stream client disconnected: {ce}')` — and `main.py:104-117` sets the file handler level to `INFO`, so it never reaches `app.log`.
  3. The `<audio>` error is handled entirely in the frontend (`player.js:659-671` → `handleStreamError` → `console.warn` at line 460). The backend's `_on_audio_error` → `describe_error` → `audio_error` event path exists, but it is wired to `self._core.engine.on_error`, and **`AudioEngine` has no `on_error` attribute**, so `core/api.py:381`'s `hasattr` guard is always False and the callback is never installed.
- **Cause:** The recovery policy was extracted into its own module but the logging that used to live in `core/api.py` was not moved with it; and the frontend handles the media error without reporting it to the backend.
- **Trigger conditions:** Every network failure during playback, and every failed recovery attempt.
- **User impact:** The user sees a toast and a "reconnecting" banner, but a support engineer reading `app.log` sees only the proxy's three `Network error …, retrying in …` lines (one per proxy GET) with no indication that a recovery was attempted, which provider was used, or why it failed. The two layers each log their own text, and neither says "recovery".
- **Evidence:**
  ```python
  # core/api.py:381-382 — dead: AudioEngine has no on_error
  if hasattr(self._core.engine, "on_error"):
      self._core.engine.on_error(self._on_audio_error)
  ```
  Runtime check: `AudioEngine()` → `hasattr(e, 'on_error') == False`, `dir(e)` contains no attribute matching `err`.
  ```python
  # core/proxy.py:1235-1241 — the actual mid-playback break, below the file log level
  except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as ce:
      logger.debug(f'Stream client disconnected: {ce}')
  ```
- **Reproduction / verification:** Run the app with the log level at INFO (`main.py:104`), block egress, start playback, and read `~/.nedotify/logs/app.log`: there is no line naming `playback_recovery`, no "recovery" line, and no line describing the `<audio>` error. (`grep -i "recover\|recovery\|playback_recovery" ~/.nedotify/logs/app.log` → no hits from the recovery module.)
- **Suggested fix:** Give `core/playback_recovery.py` a module logger and emit at INFO one line per attempt (source, provider used, outcome, elapsed) plus one WARNING when a provider task is abandoned at the deadline; raise the proxy's "client disconnected" line to WARNING when the upstream broke (not when the browser hung up); and have the frontend report the `<audio>` error to the backend (`api('report_playback_error', code, url)`) so `_on_audio_error`/`describe_error` can classify it.
- **Fix side effects:** Logging from the recovery path adds ~1 line per failure — acceptable, but during a storm it can produce hundreds of lines in a 2 MB rotating file (`main.py:113 maxBytes=2_000_000`), which may evict the very lines an engineer needs. The recovery log lines should be rate-limited per track.
- **Discovered by:** B

#### F-WX-11-6  [P2] — Two disjoint error vocabularies: the recovery's ad-hoc codes are never mapped through `describe_error`, so the UI cannot distinguish "network down" from "track gone"

- **File:** `core/user_errors.py:6-24`, `core/playback_recovery.py:98,114,116,118,132,169,172,176`, `core/proxy.py:1108-1118`, `ui/web_new_v2/js/main.js:572-586`
- **Confirmed:** yes
- **Description:** The codebase has a stable user-facing error taxonomy in `core/user_errors.py::describe_error` (`disk_full`, `file_missing`, `offline`, `permission`, `network`, `unavailable`, `invalid_input`, `unexpected`) and it is used by `_on_audio_error` and by the bridge error wrapper. The recovery path invents a *second*, disjoint vocabulary (`invalid_track`, `offline`, `file_missing`, `source_unavailable`, `invalid_stream`, `version_mismatch`) that is never passed through `describe_error`, and the proxy invents a third (`proxy_status: reconnecting | connected | failed`). The two share only `offline` and `file_missing`.
- **Cause:** The recovery module was extracted with its own return contract and no mapping layer; `describe_error` is a free function over a message string, not an enum that both sides share.
- **Trigger conditions:** Every failed recovery.
- **User impact:** The toast shown to the user is generic ("Не удалось восстановить «трек». Проверьте подключение и повторите" for a throw-away case, `result.error` otherwise) and the network banner is driven by the proxy's `proxy_status`, which is emitted on *transport* failures only. A track that was deleted by its owner produces the same "check your connection" advice as a dead router, so the user retries forever instead of skipping the track.
- **Evidence:**
  ```python
  # core/playback_recovery.py:168-169 — a permanent condition reported as a generic one
  if not stream or stream_url_expired(stream):
      return {"ok": False, "code": "source_unavailable",
              "error": "Не удалось восстановить эту запись. Повторите позже или выберите скачанный трек"}
  ```
  ```python
  # core/user_errors.py:17-20 — the taxonomy that already exists and is not used here
  if any(word in message for word in ('timeout', 'timed out', 'connection', 'network', 'ssl', 'dns', 'сеть', 'соединени')):
      return {'code': 'network', 'title': 'Не удалось подключиться к источнику', ...}
  if any(word in message for word in ('403', '404', 'unavailable', 'private video', 'not available', ...)):
      return {'code': 'unavailable', 'title': 'Трек недоступен у источника', ...}
  ```
- **Reproduction / verification:** Compare the `code` values returned by `core/playback_recovery.recover_stream` (`invalid_track|offline|file_missing|source_unavailable|invalid_stream|version_mismatch`) with `core/user_errors.describe_error`'s codes; they are not the same set and no mapping function exists (`grep -n "describe_error" core/playback_recovery.py` → no hits).
- **Suggested fix:** Make `core/user_errors.py` the single owner of the error taxonomy (an enum of codes + a `describe_code(code)`), have `playback_recovery` return those codes (`network` vs `unavailable` vs `offline` …), and let the proxy's `proxy_status` remain a *transport* signal rather than a user-facing error.
- **Fix side effects:** The frontend's toast strings live in `ui/web_new_v2/js/player.js:504-507` and `core/api.py`'s `describe_error` payload; unifying the codes means touching both sides and re-checking the offline bridge interception in `core/api.py:461-512`.
- **Discovered by:** B

#### F-WX-11-7  [P2] — The proxy's 403/410 self-heal invalidates only the resolver's caches, not the provider's 6-hour `BaseMusicService._stream_cache` — the cache `get_stream_url` actually reads — so the self-heal re-fetches the same dead URL

- **File:** `core/proxy.py:1022-1090`, `services/base_service.py:131`, `services/base_service.py:186-221`, `services/youtube_service.py:906-910`, `core/playback_recovery.py:77-92`
- **Confirmed:** yes
- **Description:** On an upstream 403/410 the proxy invalidates the resolver (memory + DB row) and then calls `re_resolve_stream_url_async`. That path ends in `provider.get_stream_url(url, ...)`, and the provider's *first* action is `self.get_from_cache(_yt_cache_key(video_url))` — the shared `BaseMusicService._stream_cache`, TTL **6 hours**. The proxy's self-heal never touches that cache, so the re-resolution returns the very same dead URL that just 403'd, and the proxy writes it back into the resolver (`core/app.py:354 resolver.refresh(...)`). The only thing that clears the provider cache is `core/playback_recovery.py:87-92` — i.e. the *frontend* recovery path. If the frontend recovery does not run, the self-heal is a no-op with respect to the URL that is actually served.
- **Cause:** Two caches hold the same artifact with two owners and two invalidation rules. `core/playback_recovery._invalidate` knows about both; `core/proxy.do_GET` knows about only one.
- **Trigger conditions:** A CDN token that 403s without carrying a parsable `expire`/`Expires` parameter (so `utils/stream_urls.py::stream_url_expired` does not catch it), plus a JS recovery that does not run (retry counter exhausted, or the user navigated away).
- **User impact:** The track stays unplayable for up to 6 hours (`_STREAM_CACHE_TTL = 6 * 3600.0`) even though the user has the network back; every play press re-runs the 403 → self-heal → same-dead-URL cycle (2 upstream attempts per press) and produces the same failure.
- **Evidence:**
  ```python
  # core/proxy.py:1024-1030 — only the resolver is invalidated
  if e.code in (403, 410) and source and source_id and attempt == 0:
      logger.info(f'Received HTTP {e.code} for {source}:{source_id}. Invalidating cache and self-healing re-resolution...')
      try:
          resolver = getattr(self.server.app_core, 'resolver', None)
          if resolver is not None:
              resolver.invalidate(source, source_id)
  ```
  ```python
  # services/youtube_service.py:906-910 — the cache the self-heal actually reads
  info = self.get_from_cache(_yt_cache_key(video_url))
  if info:
      if callback:
          callback(info.get("stream_url"), info)
      return None
  ```
  ```python
  # core/playback_recovery.py:87-92 — the ONLY place that clears the provider cache
  with BaseMusicService._cache_lock:
      for key, entry in list(BaseMusicService._stream_cache.items()):
          data = entry.get("data", entry) if isinstance(entry, dict) else {}
          url = data.get("stream_url") if isinstance(data, dict) else None
          if key in (f"{source}:{identifier}", f"{source}:{target}") or (url and url in dead_urls):
              BaseMusicService._stream_cache.pop(key, None)
  ```
- **Reproduction / verification:** Seed `BaseMusicService._stream_cache["youtube:<vid>"] = {"data": {"stream_url": "<dead-url>"}, "ts": time.time()}` and `resolver` memory/DB with the same URL; then drive the proxy's `/api/stream` path with a provider that returns the same cached URL. The self-heal completes and the same dead URL is served again. (The unit-level equivalent is `tests/test_playback_recovery.py::test_renewal_invalidates_both_stream_caches_and_preserves_position`, which proves the *recovery* path clears both — the proxy path has no equivalent test.)
- **Suggested fix:** Move the "drop every cached copy of this track's stream URL" operation into one shared helper (e.g. `core/resolver.py::invalidate_stream(source, source_id, url)`) that clears the resolver memory, the DB row and the provider cache entry, and call it from *both* `core/playback_recovery._invalidate` and `core/proxy.do_GET`'s 403/410 branch.
- **Fix side effects:** Clearing the provider cache from the proxy thread touches a class-level dict shared by every service; it must be done under `BaseMusicService._cache_lock` (already the rule) and it will force a fresh extraction for any other concurrent consumer of the same key.
- **Discovered by:** B

#### F-WX-11-8  [P3] — The proxy's HTTPError path never closes the upstream response, and the recovery's provider-facing calls each create an untracked thread

- **File:** `core/proxy.py:1022-1101`, `core/app.py:506`, `core/proxy.py:438-446`
- **Confirmed:** yes (the socket is released by CPython refcounting, so this is a robustness issue, not an observed leak)
- **Description:** (a) In `do_GET`, the `except urllib.error.HTTPError as e:` branch answers the client and returns without calling `e.close()`; `HTTPError` is itself a response object holding the open socket. The `finally` block at `core/proxy.py:1249-1254` only closes `resp`, and `resp` is `None` on this path. (b) `core/app.py:506` spawns a `threading.Thread` per re-resolution and `core/proxy.py:438-446` a thread per HTTP request; neither is bounded by a semaphore, and the proxy's per-request thread can live ~55 s during an outage (4 × 12 s upstream timeout + ~7.1 s of backoff).
- **Cause:** Explicit resource discipline was applied to the *success* path (`resp.close()` in the `finally`) but not to the error path; and the thread-per-call model has no concurrency cap.
- **Trigger conditions:** 4xx/5xx answers from the CDN during an outage; many concurrent proxy requests.
- **User impact:** Low. The socket is released promptly by CPython's refcounting when the exception object goes out of scope at the end of the `except` block, so no unbounded descriptor leak was observed. The thread growth is bounded by the browser's own request concurrency and by the daemon-thread policy at `core/proxy.py:430`.
- **Evidence:**
  ```python
  # core/proxy.py:1087-1090 — no e.close()
  else:
      self.send_response(e.code)
      self._send_cors_headers()
      self.end_headers()
      return None
  ```
  ```python
  # core/proxy.py:1249-1254 — the finally only sees `resp` (None on the error path)
  finally:
      if resp is not None and hasattr(resp, "close"):
          try: resp.close()
          except Exception: pass
  ```
  ```python
  # core/app.py:506 — one untracked thread per re-resolution
  threading.Thread(target=worker, daemon=True).start()
  ```
- **Reproduction / verification:** Run the proxy handler with a stubbed `_safe_urlopen` that raises `urllib.error.HTTPError`, and count open sockets via `psutil`/`netstat` before and after; under CPython the count returns to baseline. Under a different GC (or with the exception stored) it would not.
- **Suggested fix:** Close the `HTTPError` explicitly (`try: e.close() except Exception: pass`) in the 4xx/5xx branches, and bound the proxy's concurrent request threads with a semaphore.
- **Fix side effects:** Closing the `HTTPError` before `send_response` is safe (the body is not forwarded), but the `except urllib.error.HTTPError` branch that re-uses `e` after the close must be reviewed.
- **Discovered by:** B

#### F-WX-11-9  [P3] — `same_recording` fails open when a duration or a title is missing, and the version detector does not know "Remastered"/"Radio Edit"/"Extended"

- **File:** `core/playback_recovery.py:14-37`, `core/playback_recovery.py:133`, `core/playback_recovery.py:151`, `core/playback_recovery.py:160`, `services/music_matching.py:8-16`
- **Confirmed:** yes
- **Description:** The guard that decides whether a re-resolved track is "the same recording" has three fail-open edges: (a) the duration check is skipped entirely when either side's duration is 0/unknown (`if expected and actual and abs(...) > ...`); (b) the artist check is skipped when the *wanted* track has no artist; (c) the post-resolution verification at line 160 is applied only `if stream and metadata and metadata.get("title")` — a provider that returns metadata without a title is accepted unchecked. The version detector (`VERSION_PATTERNS`) knows instrumental/cover/live/acoustic/sped/slowed/remix but not *remastered*, *radio edit*, *extended*, *reprise*, *demo*, *mono*.
- **Cause:** Each check is written as "reject if we can prove a mismatch" rather than "accept only if we can prove a match", which is the safe polarity for a substitution guard.
- **Trigger conditions:** A fallback provider returns a candidate whose metadata lacks a duration (or the wanted track has duration 0 — e.g. a track imported from a playlist without duration), and a different recording with the same title and artist exists.
- **User impact:** The user is told "track recovered" and hears a different version of the recording (e.g. a 9-minute extended mix instead of the 3-minute edit) with no indication. The title-similarity gate (0.88) does catch most version changes *when the version is in the title*, so the practical exposure is limited to identically-titled, differently-lengthed releases.
- **Evidence:**
  ```python
  # core/playback_recovery.py:30-36 — the duration gate is skipped when a duration is unknown
  try:
      expected = float(wanted.get("duration") or 0)
      actual = float(offered.get("duration") or 0)
  except (ValueError, TypeError):
      return False
  if expected and actual and abs(expected - actual) > max(4.0, expected * 0.025):
      return False
  ```
  ```python
  # core/playback_recovery.py:160 — verification only runs when a title is present
  if stream and metadata and metadata.get("title") and not same_recording(track, metadata):
      stream = None
  ```
  ```python
  # services/music_matching.py:8-16 — no 'remastered' / 'radio edit' / 'extended'
  VERSION_PATTERNS = {
      'instrumental': ..., 'cover': ..., 'live': ..., 'acoustic': ...,
      'sped': ..., 'slowed': ..., 'remix': ...,
  }
  ```
- **Reproduction / verification:** `same_recording({"title": "Song", "artist": "Artist", "duration": 0}, {"title": "Song", "artist": "Artist", "duration": 540})` → `True` (duration gate skipped because `expected == 0`). The existing test `tests/test_playback_recovery.py:11-19` only covers the case where *both* durations are present.
- **Suggested fix:** Invert the polarity — require a positive match (title similarity **and** a duration check when either side is known **and** an artist check) — and treat an unknown duration on the *offered* side as "unverified" rather than "verified".
- **Fix side effects:** Strict matching will reject legitimate recoveries (a remaster whose duration differs by 1-2 s, a track whose provider duration is rounded) and turn them into `source_unavailable`; the 2.5 % duration tolerance already covers rounding.
- **Discovered by:** B

#### F-WX-11-10  [P3] — A fallback-provider URL is persisted under the *original* provider key, so the DB and the resolver claim a YouTube track's stream is a SoundCloud URL

- **File:** `core/playback_recovery.py:135-165`, `core/playback_recovery.py:177-183`
- **Confirmed:** yes
- **Description:** When the recovery falls back to another provider, the result correctly reports `source`/`source_id` of the fallback (`selected_source`, `selected_id`, lines 163-164), but the persisted cache entry is written under the *original* pair: `resolver.refresh(source, identifier, stream)` (line 179) with `source`/`identifier` still the original ones, while `stream` is the fallback provider's URL. The proxy URL is likewise built with the original pair (`proxy.get_proxy_url(source, identifier, stream, ...)`).
- **Cause:** The function tracks two identities (the requested track and the provider that answered) but persists only one of them.
- **Trigger conditions:** A recovery that succeeds via the SoundCloud (or YouTube) fallback while the original source was the other one.
- **User impact:** The `stream_cache` row for `('youtube', <id>)` now holds a SoundCloud CDN URL. Later reads (`core/api.py:1543`, `core/api.py:1685`) hand it to the proxy with `source='youtube'`, so `_host_allows_credentials` (`core/proxy.py:91-99`) withholds the SoundCloud credentials and logs a warning — the URL still works because the client_id is embedded, but a credentialed SoundCloud URL would not. The fallback provider's own `(source, source_id)` pair is *never* refreshed, so it is re-resolved from scratch next time.
- **Evidence:**
  ```python
  # core/playback_recovery.py:162-165 — the fallback identity is recorded ...
  if stream:
      selected_source = fallback
      selected_id = str(candidate.get("source_id") or "")
      break
  ...
  # core/playback_recovery.py:177-181 — ... but the ORIGINAL identity is persisted
  resolver = getattr(core, "resolver", None)
  if resolver:
      resolver.refresh(source, identifier, stream)
  proxy = getattr(core, "proxy", None)
  playback_url = proxy.get_proxy_url(source, identifier, stream, track_id=track.get("id")) if proxy else stream
  ```
- **Reproduction / verification:** Drive `recover_stream` with a YouTube source whose provider fails and a SoundCloud provider that succeeds (the shape of `tests/test_playback_recovery.py::test_fallback_skips_incorrect_top_result_and_does_not_rewrite_track`), then assert `resolver.get_cached_url('youtube', 'original')` is the SoundCloud URL and `resolver.get_cached_url('soundcloud', 'right')` is `None`.
- **Suggested fix:** Persist under `selected_source`/`selected_id` (the pair that actually owns the URL) and keep the original pair as an alias, or store the provider identity alongside the URL in `stream_cache`.
- **Fix side effects:** Changing the cache key changes what `core/api.py`'s DB fast path and `core/offline.py::available_track` find for the original track; the alias has to be added or the original track will lose its cached file association.
- **Discovered by:** B

---

### 3. Clean areas

- **Negative cache classification (the brief's core question) — CLEAN.** The only *live* negative cache in the tree is `services/soundcloud_service.py::_unavailable_cache` (TTL 3600 s, 200 entries, `_UNAVAILABLE_TTL` at line 83). It is populated from exactly two places and both are correctly classified:
  - `_is_unplayable_error(exc)` (`services/soundcloud_service.py:100-103`) matches only DRM/private/removed markers, and it **guards** the `_mark_unavailable` call at line 738 (`if not _is_unplayable_error(exc): raise`). A transport error is re-raised, not memoised.
  - `_media_url_is_servable()` (`services/soundcloud_service.py:541-567`) treats only `{401, 403, 404, 410}` as a denial; a 5xx or a transport error returns `True` ("retryable") by design.
  → **Blast radius of a 30-second outage: 0 tracks blacklisted, for 0 seconds.** If the resolver's `_failed` map *were* populated (it is not — F-WX-11-3), the exposure would be `_FAIL_MAX_SIZE = 512` tracks × `_FAIL_TTL = 120.0` s. YouTube has no negative cache at all.
- **Stale-URL invalidation — CLEAN and effective.** The chain works end to end and I verified every hop:
  `core/playback_recovery.py:120` → `_invalidate()` (lines 77-92) → `core/resolver.py:238-254 invalidate()` → pops `_mem` **and** `core/database.py:2213-2225 invalidate_cached_stream()` → `UPDATE stream_cache SET stream_url = NULL WHERE source = ? AND source_id = ?`. The same call also evicts the provider's 6 h cache entry (`core/playback_recovery.py:87-92`). The proxy's 403/410 branch does the resolver half (`core/proxy.py:1027-1030`). Every reader of the row checks `stream_url` for truthiness before using it (`core/api.py:1543`, `core/api.py:1685`, `core/resolver.py:153`, `core/proxy.py:797`), so a NULL `stream_url` is never served. **The "failure becomes permanent for 4 hours" scenario described in the brief does not occur on the recovery path.**
- **DB TTL semantics — mostly CLEAN.** `core/database.py:2149 get_cached_stream()` filters on `cached_at` with `max_age_seconds=14400` (4 h) — matching the brief's "4 hours by default" — and the resolver passes the same value explicitly (`core/resolver.py:23 _DB_MAX_AGE = 14400`). The row's own `expires_at` is `+24 hours` (`core/database.py:2183`) and is used only by `cleanup_expired_cache`, so the *effective* TTL is the 4 h read cutoff, as intended. The 24 h row lifetime is a deliberate "keep downloaded-file rows" behaviour, not a stale-URL bug.
- **Proxy retry/backoff — reasonable.** `core/proxy.py:1092-1096` and `1104-1115` use exponential backoff `1.5 ** attempt + random.uniform(0.1, 0.5)` (1.5 s / 2.25 s / 3.375 s) with jitter, `max_retries = 3`, a 12 s socket timeout, and a 7 s bounded self-heal wait (`core/proxy.py:1052`). The `proxy_status` event (`core/proxy.py:1108-1113`) carries attempt/max_attempts/next_retry_in_ms, and the UI renders it (`ui/web_new_v2/js/main.js:577-579`). The *proxy's own* retry loop does not leak a thread per attempt (it is a `for` loop inside one request thread) and `resp.close()` runs in the `finally` on the success path (`core/proxy.py:1249-1254`).
- **Proxy credential scoping — CLEAN.** `_host_allows_credentials()` (`core/proxy.py:91-99`) gates YouTube/SoundCloud/Yandex credentials on the target host, `core/proxy.py:984-1006` withholds them otherwise (with a warning), and `SafeRedirectHandler.redirect_request` (`core/proxy.py:375-387`) strips `Authorization`/`Cookie` on a cross-host redirect and SSRF-checks every redirect destination.
- **SSRF guard at egress — CLEAN.** `_is_ssrf_safe_url` is applied to the `?url=` target (`core/proxy.py:954`), to the resolved target (`core/proxy.py:841`), to every redirect (`core/proxy.py:379`) and to the proxy's own re-resolved URL (`core/proxy.py:1054`). DNS verdicts are memoised per host (`core/api.py:157`).
- **Offline mode is honoured on every recovery entry point.** `core/playback_recovery.py:113`, `131`, `137`, `149`, `166` all re-check `is_offline(settings)` between provider calls, and `core/api.py:4168` checks it before delegating. `tests/test_playback_recovery.py:36-46` pins that the fallback is not started after the mode flips mid-attempt.
- **Frontend retry guard against ping-pong — CLEAN.** `player.js:451` (`if (streamRetryTimer || recoveryRequest) return;`) and `player.js:469/474/485` (generation + `recoveryRequest` identity checks) prevent a second recovery from overlapping the first and prevent a stale recovery from applying to a new track.
- **`same_recording` rejects the common substitution cases — CLEAN.** Wrong artist, Live/Instrumental/Cover versions and a materially different duration are all rejected (`tests/test_playback_recovery.py:11-26`); a provider that returns metadata for a *different* track causes the recovery to return `source_unavailable` rather than play it (`tests/test_playback_recovery.py:107-113`).
- **Per-request DB connection release — CLEAN.** `core/proxy.py:469-486 finish()` closes the thread's SQLite connection before the thread dies.

### 4. Coverage gaps

- **No live network measurements.** I did not run the app or block egress (forbidden by the brief). The retry-storm rates, the pool backlog size and the "≈2.5 minutes to the error toast" figure are **derived from the code's timeouts and budgets**, not measured. Confirming them needs a controlled run with the egress blackholed and counters on `BaseMusicService._SharedExecutor.submit`, `soundcloud_service.search` and `youtube_service.get_stream_url`.
- **Provider rate-limit thresholds are unknown.** Whether 3 000-8 000 requests / 600 s from one IP actually gets the user banned is a property of YouTube/SoundCloud, not of this repo. The *absence of any limit in the app* is confirmed; the *ban* is a hypothesis (the codebase itself acknowledges the "confirm you're not a bot" gate in `services/youtube_service.py:60-79`).
- **The exact number of HTTP requests inside one yt-dlp extraction** (I estimated 3-10) depends on which YouTube clients yt-dlp 2026.x negotiates and on whether a PO token is present; I did not instrument it. The 6-18 figure for a SoundCloud `get_stream_url` counts the api-v2 track call + the transcoding call + the CDN probe, but `_get_client_id`'s scrape can add up to ~6 more requests (rate-limited to once per 10 s by `_client_id_retry_at`).
- **Browser-side behaviour not observed.** I did not verify how many parallel HTTP requests Chromium issues against the proxy for one `<audio>` element during an outage (the 1 MiB googlevideo range binding at `core/proxy.py:74-89` implies several range requests per track). The "4 upstream attempts per press" figure counts proxy GETs, not browser range requests.
- **The `yandex` and `spotify` recovery branches were not exercised.** `core/playback_recovery.py:117` allows `yandex`/`spotify`, but `service = getattr(core, source, None) if source != "spotify" else None` (line 125) means Spotify never takes the primary branch and Yandex has no `get_stream_url` path in this module — both fall straight into the YouTube/SoundCloud fallback. I did not trace `services/yandex_service.py` in depth (out of this scenario's focus).
- **Windows-specific socket behaviour under a blackhole** (SYN timeouts vs. immediate `WSAECONNREFUSED`/`WSAETIMEDOUT`) was not measured, so the "12 s timeout per attempt" worst case is an upper bound; on a router that refuses fast, the proxy request finishes in ~8 s instead of ~55 s.
- **`core/api.py`'s `describe_error` payload for the recovery codes was not checked against the frontend's toast handling** (`ui/web_new_v2/js/events.js:432`), because the recovery path does not use `describe_error` at all (F-WX-11-6) — so there is nothing to check.
- I did not review `tools/bench/**` or `tools/visual_guard/**` (WN-35) and did not open the `android/` subtree (out of scope).

---

### 5. Architecture improvements (ARCH)

These are engineering improvements **without a proven defect**; they are not part of the defect list above.

1. **One owner for "the network is unavailable".** Today the outage is detected independently by the proxy (`core/proxy.py:1102`), by `core/app.py::_on_err`, by `core/playback_recovery.py` and by `utils/stream_urls.py` — four places, four vocabularies, four budgets. A single `core/network_policy.py` exposing "is the provider reachable / is the circuit open / how long must we wait before trying again" would give F-WX-11-1 a single fix point and would let the UI show one coherent "offline" state.

2. **One recovery policy module, one budget, one caller.** `core/playback_recovery.py` is a good idea (a bounded, queue-preserving renewal) but it is only used by the frontend's `<audio>` error path. The *other* renewal path — `core/app.py::re_resolve_stream_url_async` → `core/api.py::play_track` / `_resolve_track` — is an unbounded, differently-bounded copy of the same policy with its own 20 s SoundCloud budget and its own 6-query fallback ladder. Folding both under `core/playback_recovery.py` (with an explicit "mode": `player_recovery` vs `resolve`) would remove the duplication and make the retry storm countable in one place.

3. **A single stream-URL artifact instead of four.** The same URL lives in: the resolver's memory (1 h), the DB `stream_cache` row (4 h read cutoff / 24 h row TTL), `BaseMusicService._stream_cache` (6 h) and the provider's own search cache (5 min). The TTLs are not derived from each other and two of the four owners do not know the other three exist (F-WX-11-7). One artifact type — e.g. `StreamHandle(url, provider, expires_at, source, source_id)` with a single `invalidate()` that clears every copy — would remove a whole class of "the failure became permanent" bugs.

4. **Make the resolver's negative cache a typed, provider-issued verdict.** `mark_unavailable(source, source_id, reason: str)` stores a free-text reason and cannot distinguish "the network is down" from "the track is gone". A typed verdict (`UnavailableKind.PERMISSIVE | TRANSIENT`) checked *inside* `mark_unavailable` would make the brief's invariant ("a transient network error must not be cached as unavailable") enforceable rather than incidental, and would give the `_failed` map a real owner.

5. **Make the failure classification single-sourced.** `core/user_errors.py::describe_error` is already the right shape (stable codes + a user message + an action); it should be the only producer of user-facing error codes, with `playback_recovery` and the proxy mapping into it instead of inventing their own (F-WX-11-6).

6. **Report playback failures to the backend.** The frontend owns the `<audio>` element and therefore owns the error, but it never tells the backend (`core/api.py:381` waits for an `on_error` hook that `AudioEngine` does not have). A `report_playback_error(code, url, position_ms)` bridge call would let the backend own the classification, the log and the user-facing message, and would give the recovery a single authoritative entry point.

7. **Bound the proxy's request concurrency.** `core/proxy.py:438-446` is thread-per-request with no cap, and during an outage each request thread lives up to ~55 s. A semaphore (or a small fixed worker pool) would bound the thread count under a storm.

8. **Give the provider layer a cancellation handle.** Every provider API is callback-based with no way to abandon a request (F-WX-11-2). A `CancellationToken` threaded through `get_stream_url`/`search` would let a bounded recovery actually stop the work it started, and would let the shared 8-worker pool's queue stay shallow.
