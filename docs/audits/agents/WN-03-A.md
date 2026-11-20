## AREA WN-03 — Bridge core: init, `_emit`, SSRF guard, error logging, offline interception — ROLE A

### 1. Scope reviewed

- Files opened (path: line ranges actually read)
  - `core/api.py` L1–520 (the area range: module header, constants, `_reset_ssrf_cache`,
    `_ssrf_cache_get`, `_ssrf_cache_put`, `_dns_resolves_to_public_ip`, `_is_ssrf_safe_url`,
    `_extract_first_url`, `_as_float`, `_mask_secrets`, `_bridge_write_error`,
    `_is_empty_secret_write`, `_normalize_cache_quota`, `_missing_local_file_message`,
    `class AppApi.__init__`, `_install_bridge_error_logging`, `cleanup`, `_offline_bridge_result`)
  - `core/api.py` L1109–1160 (`_emit` + `emit_event` + `open_url`) — read because the area
    title names `_emit` as part of WN-03; **the line range in `WIN_AUDIT_AREAS.md` places
    `_emit` inside WN-04 (L514–1160)**. See "Double-reporting note" in §4.
  - `core/api.py` L1860–1945, L2077–2156, L2244–2261, L2355–2404, L2545–2614, L2905–2974,
    L3180–3229, L3293–3317, L3754–3783, L4021–4111, L4166–4228 (call sites of the helpers
    under review; used only as evidence, not as the subject of the finding)
  - `core/offline.py` L1–77 (whole file)
  - `core/user_errors.py` L1–24 (whole file)
  - `core/settings.py` L52–287 (DEFAULT_SETTINGS tree), L351–418 (`get`/`set`), L532–535
    (`get_category`)
  - `core/app.py` L94–213 (`AppCore.__init__` order), L508–567 (`AppCore.cleanup`)
  - `core/proxy.py` L23–24, L368–393 (`SafeRedirectHandler`, `_safe_urlopen`), L421–447,
    L496–535 (proxy token gate), L800–999 (the two `_is_ssrf_safe_url` call sites)
  - `main.py` L145–244 (DoH `socket.getaddrinfo` patch), L300–409 (AppApi creation,
    `on_loaded`), L406–584 (shutdown path)
  - `core/tray.py` L160–194 (`TrayIcon.start/stop`)
  - `core/snap_layouts.py` L330–357 (UI-thread window proc — checked for main-thread emits)
  - `services/lyrics_service.py` L225–284 (network call + `get_lyrics`)
  - `services/playlist_import_service.py` L26–95 (`resolve()` — which URLs are actually fetched)
  - `services/base_service.py` L25–58 (`normalize_proxy_url` — `auth.proxy_url` semantics)
  - `core/database.py` L182, L1470–1482 (`get_album_tracks` return shape)
  - `ui/web_new_v2/js/settings.js` L248–287, L379, L952, L983; `js/events.js` L75–104,
    L325–364; `js/artist_profile.js` L125–174; `js/search.js` L595–654; `js/home.js` L238–386;
    `js/main.js` L124–165; `js/lyrics.js` L58–63 (consumer side of the offline contract)
  - `ui/web_new_v2/index.html` L1795–1814 (the cache-quota `<select>` options)
  - `tests/test_emit_thread_safety.py` (whole file), `tests/test_api_audit_b.py` L253–339,
    L593–606 (the existing coverage of the functions under review)
  - Third-party read-only: `.venv_win/Lib/site-packages/webview/{window.py,util.py,event.py,http.py}`,
    `platforms/edgechromium.py`, `js/api.js` (to verify the pywebview threading/serialisation
    contract the code depends on)
- Callees traced into other areas
  - `core/offline.py` → `is_offline`, `available_track`, `available_tracks` (WN-15)
  - `core/user_errors.py` → `describe_error` (WN-16)
  - `core/settings.py` → `SettingsManager.get/set/get_category` (WN-14)
  - `core/proxy.py` → the two `_is_ssrf_safe_url` call sites and `SafeRedirectHandler` (WN-11)
  - `core/database.py` → `get_album_tracks` (WN-12)
  - `core/tray.py` → `TrayIcon.stop` (WN-16)
  - `core/app.py` → `AppCore.__init__`/`cleanup` (WN-02)
  - `services/lyrics_service.py` → `LyricsService.get_lyrics` network path (WN-22)
  - `services/playlist_import_service.py` → `PlaylistImportService.resolve` (WN-24)
  - `main.py` → DoH resolver patch + startup/shutdown ordering (WN-01)

### 2. Findings

#### F-WN-03-1  [P1] — The SSRF guard fails OPEN when DNS resolution fails, and the wrong verdict is cached as "safe" for 120 s
- **File:** `core/api.py:143-158` (in `_dns_resolves_to_public_ip`), `core/api.py:99-100` (TTL)
- **Confirmed:** yes
- **Description:** `_dns_resolves_to_public_ip` initialises `verdict = True` and only ever
  *downgrades* it inside the `try` block. When `socket.getaddrinfo` raises, the `except
  Exception` branch performs a four-item string-prefix fallback (`169.254.`, `10.`,
  `192.168.`, `127.`) and leaves `verdict = True` for every other host. The "safe" verdict is
  then written into `_ssrf_cache` with a 120 s TTL, so a *transient* resolution failure
  authorises that hostname for the next two minutes.
- **Cause:** the safe default is "public", and the error path is a partial prefix list rather
  than "unknown ⇒ not safe". The cache then amplifies a momentary failure into a 2-minute
  authorisation.
- **Trigger conditions:** the hostname does not resolve at check time. This is a normal
  condition in this app: `main.py:160-225` patches `socket.getaddrinfo` with a DoH fallback
  that raises `socket.gaierror("All DoH endpoints failed for host")` when all three
  endpoints time out (2 s each) — exactly the "blocked DNS" scenario the app ships for.
- **User impact:** the SSRF control approves a host it could not evaluate. Combined with
  F-WN-03-2 (the resolved IP is never pinned), an attacker-controlled resolver that answers
  "no such host" during the check and `127.0.0.1` during the actual fetch gets the fetch
  through the guard. Reachable sinks: `import_external_playlist` (`core/api.py:2365` →
  yt-dlp fetch), the proxy's resolved-stream fetch (`core/proxy.py:841` and `:954`), and
  `open_url` (`core/api.py:1111`).
- **Evidence:**
  ```python
  143:     verdict = True
  144:     try:
  145:         addr_info = socket.getaddrinfo(hostname, None)
  ...
  152:     except Exception:
  153:         # If DNS resolution fails, fallback string check
  154:         if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("127."):
  155:             verdict = False
  156:
  157:     _ssrf_cache_put(hostname, verdict)
  ```
- **Reproduction / verification:** monkeypatch `socket.getaddrinfo` to raise `gaierror` and
  call the helper (scratch script, `%TEMP%\opencode\audit_reports\_scratch_wn03.py`, section F):
  ```
  unresolvable.example -> True
  10.0.0.5 (literal)   -> False
  172.16.0.5 (literal) -> True          <-- also a miss: "172.16." is not in the prefix list
  evil.example         -> True
  cache after -> {'unresolvable.example': (..., True), '10.0.0.5': (..., False),
                  '172.16.0.5': (..., True), 'evil.example': (..., True)}
  ```
  Note the second defect visible in that output: even the *literal* private address
  `172.16.0.5` is judged "safe" when resolution fails, because the fallback list omits
  `172.16.`/`172.31.`.
- **Suggested fix:** treat an unresolvable host as *not* safe (return False, or a tri-state
  "unknown" that the callers treat as blocked), and never cache a verdict that was produced
  by the exception path. Extend the literal fallback to the full private ranges, or reuse
  `ipaddress.ip_address()` on the hostname instead of a prefix list.
- **Fix side effects:** a transient DNS outage would then block the proxy's stream fetches
  and playlist imports instead of letting them fail later at connect time. That is the
  intended fail-closed behaviour, but it converts a soft failure into a hard 400/403 and may
  need a short "unknown ⇒ retry" path rather than a flat block.
- **Discovered by:** A

#### F-WN-03-2  [P2] — The SSRF check never pins the resolved address: check-time DNS and fetch-time DNS are two independent resolutions (TOCTOU)
- **File:** `core/api.py:145` (resolution), `core/api.py:139-141` (per-hostname memo),
  `core/api.py:193` (return value); consumers `core/proxy.py:841`, `core/proxy.py:954`,
  `core/api.py:2365`
- **Confirmed:** yes
- **Description:** `_dns_resolves_to_public_ip` resolves the hostname, classifies the
  addresses and then **throws the addresses away** — it returns a `bool` and caches a
  `bool`. The subsequent fetch (`urllib.request.urlopen`, yt-dlp, `requests`) performs its
  own `getaddrinfo` and connects to whatever that returns. The address that is actually
  contacted is never the address that was validated.
- **Cause:** the guard is a boolean predicate over a hostname, not a validated address
  handle. The 120 s hostname cache widens the window further.
- **Trigger conditions:** any DNS answer that changes between the check and the fetch
  (classic DNS rebinding), or a resolver that returns several A records where the public
  one is validated and a private one is used for the connection.
- **User impact:** the guard can be fully bypassed by an attacker who controls the DNS for
  the imported link. The concrete fetch sinks live in other areas (WN-11 proxy, WN-24
  playlist import); the *guard* is WN-03's.
- **Evidence:**
  ```python
  145:         addr_info = socket.getaddrinfo(hostname, None)
  146:         for family, socktype, proto, canonname, sockaddr in addr_info:
  147:             ip_str = sockaddr[0]
  ...
  157:     _ssrf_cache_put(hostname, verdict)
  158:     return verdict
  ```
  The address list (`addr_info`) is local to the function and never returned or cached.
- **Reproduction / verification:** static — no address flows out of
  `_dns_resolves_to_public_ip`; grep the module for any use of `sockaddr` beyond the
  classification loop confirms it. A live rebinding test needs a controlled resolver and
  is out of scope for a read-only review.
- **Suggested fix:** return the validated address list, and make the fetch connect to one of
  those addresses (with the original `Host` header / TLS SNI preserved), or re-validate at
  connect time via a custom `socket` factory instead of validating by name.
- **Fix side effects:** pinning the address breaks TLS SNI and virtual-host routing unless
  the `Host` header is preserved, and breaks CDN geo-selection. It also means every fetch
  path (proxy, yt-dlp, `requests`) must opt in — a large change across WN-11/WN-24.
- **Discovered by:** A

#### F-WN-03-3  [P2] — `_emit`'s main-thread branch spawns one OS thread per event, does not preserve order, and lets worker exceptions escape uncaught
- **File:** `core/api.py:1141-1159` (`_emit`), `core/api.py:1122-1139` (payload build)
- **Confirmed:** yes
- **Description:** when `_emit` is called on the main thread it starts a *new* daemon thread
  per event whose target is `self._window.evaluate_js` directly. Two consequences:
  (a) **ordering is not preserved** — two consecutive events race, and the second can be
  delivered first; (b) the `try/except` that guards `evaluate_js` only covers the *inline*
  branch, so an exception raised inside the worker thread is an **unhandled thread
  exception** (it is printed by the default `threading.excepthook`, not by the app logger).
- **Cause:** the branch was written as "get off the UI thread quickly" rather than "hand the
  event to an ordered emitter". A per-event thread has no ordering guarantee and no place
  to put a `try/except` around the worker body.
- **Trigger conditions:** any `_emit` executed on the main thread. Note that the comment's
  stated trigger — "the pywebview `loaded` event runs on the UI thread" — is **not true for
  the installed pywebview**: `webview/util.py:230` starts the injection in a fresh
  `Thread`, and `webview/event.py:59` runs the `loaded` handlers in yet another fresh
  thread, so `main.py:on_loaded` (and therefore `_on_track_changed`) does *not* run on the
  UI thread. I found no code path in the app that emits from the main thread
  (`core/snap_layouts.py:335-357`, the only genuine UI-thread callback, does not call into
  the API). The defect is therefore **latent today**, but the branch is the app's only
  defence against the documented deadlock and any future main-thread emit re-opens it.
- **User impact:** if the branch is ever taken, state-carrying events (`queue_updated`,
  `track_changed`, `position_changed`) can be delivered out of order, leaving the UI showing
  an older state than the backend; and every emit after the WebView is gone prints an
  unhandled traceback to stderr instead of a log line.
- **Evidence:**
  ```python
  1147:         if threading.current_thread() is _MAIN_THREAD:
  1148:             threading.Thread(
  1149:                 target=self._window.evaluate_js,
  1150:                 args=(js_code,),
  1151:                 daemon=True,
  1152:                 name="EmitWorker",
  1153:             ).start()
  1154:             return
  1155:
  1156:         try:
  1157:             self._window.evaluate_js(js_code)
  1158:         except Exception as e:
  1159:             logger.error("emit %s failed: %r", event_name, e, exc_info=True)
  ```
- **Reproduction / verification:** scratch script
  `%TEMP%\opencode\audit_reports\_scratch_wn03_b.py` (sections 1 and 2) makes the main
  thread the "UI" thread and uses a window whose first `evaluate_js` sleeps 0.4 s:
  ```
  === 1. ordering hazard: two emits from the main thread ===
    evaluate_js call order: [2, 1] -> events delivered out of order
  === 2. exception in the EmitWorker thread is NOT caught by _emit ===
    unhandled in worker thread: {'exc': 'RuntimeError: webview is gone'}
  ```
- **Suggested fix:** use a single long-lived emit worker with a `queue.Queue` (one thread,
  FIFO order, one place for the `try/except`), and let the main-thread branch only enqueue.
  Update the comment to state the real trigger instead of the `loaded` event.
- **Fix side effects:** a queue introduces back-pressure and an unbounded-growth decision
  (drop-oldest vs. block); a bounded queue that drops events would break the "no lost
  events" expectation, so the queue needs a size cap and an explicit overflow policy. A
  single worker also serialises emits that were previously parallel, which slightly slows
  bursts but restores ordering.
- **Discovered by:** A

#### F-WN-03-4  [P2] — `AppApi.cleanup()` does not quiesce the emit path: events are still delivered to a destroyed window after cleanup
- **File:** `core/api.py:446-459` (`cleanup`), `core/api.py:1122-1125` (`_emit`),
  `main.py:555` / `main.py:575-579` (shutdown order)
- **Confirmed:** yes
- **Description:** `cleanup()` stops the tray and shuts down the two thread-pool
  executors, but it never clears `self._window`, never sets a "closed" flag and never
  stops or joins the per-event emit threads of F-WN-03-3. `_emit` only bails out when
  `self._window` is falsy, and nothing ever sets it to `None`.
- **Cause:** the lifecycle flag that would make the bridge refuse to talk to a dead
  WebView is missing; cleanup only releases *its own* resources.
- **Trigger conditions:** anything that emits between `webview.start()` returning
  (`main.py:555`) and process exit (`main.py:580`) — e.g. an in-flight search result, a
  download progress event, the lyrics cascade thread, or the tail of
  `AppCore.cleanup()`.
- **User impact:** `evaluate_js` is called on a torn-down WebView2 control. pywebview
  catches the error and logs it (`platforms/edgechromium.py:131-133`), but in the
  main-thread branch of `_emit` the exception is not caught at all (F-WN-03-3), so the
  user sees stderr tracebacks during shutdown. No data is corrupted, but the shutdown path
  is noisy and the "closed" state is invisible to the rest of the bridge.
- **Evidence:**
  ```python
  446:     def cleanup(self):
  447:         """O-15: release the shared search executor without blocking app exit."""
  448:         try:
  449:             if getattr(self, "_tray", None):
  450:                 self._tray.stop()
  ...
  453:         try:
  454:             if getattr(self, "_search_executor", None) is not None:
  455:                 self._search_executor.shutdown(wait=False, cancel_futures=True)
  ```
  and in `_emit`:
  ```python
  1124:         if not self._window:
  1125:             return
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03_b.py` section 3:
  ```
  === 3. emit after cleanup(): _window is not cleared, evaluate_js is still called ===
    evaluate_js called after cleanup(): True
  ```
- **Suggested fix:** set a `self._closed` flag (and clear `self._window`) in `cleanup()`,
  and make `_emit` return early when it is set; stop the emit worker at the same time.
- **Fix side effects:** `_emit` becoming a no-op after cleanup also silences the final
  "goodbye" style events some apps emit on close; here nothing depends on that (the only
  post-close emit in the tree is `session_autoplay` at `main.py:397`, which happens before
  cleanup).
- **Discovered by:** A

#### F-WN-03-5  [P2] — The offline interception list omits `get_lyrics`: offline mode still performs outbound lyrics requests
- **File:** `core/api.py:461-512` (`_offline_bridge_result`), `core/api.py:502`
  (`get_lyrics_translation` is intercepted), `core/api.py:3192-3225` (`get_lyrics`),
  `services/lyrics_service.py:236-241` (`urllib.request.urlopen`)
- **Confirmed:** yes
- **Description:** `_offline_bridge_result` blocks 25 network-bound bridge methods in
  offline mode, but not `get_lyrics`. The lyrics service has no offline check of its own
  (`grep -n "offline" services/lyrics_service.py` → no match) and reaches the network via
  `urllib.request.urlopen` (`services/lyrics_service.py:241`). The inconsistency is
  visible inside the same function: `get_lyrics_translation` *is* blocked (L502) while the
  primary lyrics lookup is not.
- **Cause:** the deny-list was assembled from "home/feed/download" screens and was never
  reconciled with the lyrics cascade, which was added later.
- **Trigger conditions:** offline mode enabled and a track is opened whose lyrics are not
  in the local lyrics cache (`services/lyrics_cache.db`). `get_lyrics` is called from
  `js/lyrics.js` on every track change.
- **User impact:** the app performs third-party HTTP requests while the user has
  explicitly asked for offline mode — the mode's promise is broken and the user's IP leaks
  to the lyrics providers. The lyrics panel then waits for the provider timeouts before
  reporting "unavailable", so the UI feels broken in exactly the mode where it should be
  instant.
- **Evidence:**
  ```python
  502:         if method in ('prefetch_track', 'get_lyrics_translation', 'check_zapret_update', 'update_zapret'):
  503:             return True, None
  ```
  `get_lyrics` appears nowhere in the function (L461-512), and `services/lyrics_service.py:241`
  is `return urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)`.
- **Reproduction / verification:** scratch script `_scratch_wn03_b.py` section 4 with a
  fake core whose `network.offline_mode` is `True`:
  ```
  get_lyrics (not intercepted)  -> (False, None)
  ```
  i.e. the real `get_lyrics` runs and its worker thread performs the network cascade.
- **Suggested fix:** add `get_lyrics` to the offline interception and serve it from the
  local lyrics cache only (the cache lives in `services/lyrics_cache.db`, already wired
  through `LyricsLookup`), returning `status: 'unavailable'` on a cache miss.
- **Fix side effects:** cached lyrics must still be returned in offline mode, otherwise
  offline lyrics regress from "slow" to "missing"; the interception must therefore not
  short-circuit the local cache lookup.
- **Discovered by:** A

#### F-WN-03-6  [P2] — `_normalize_cache_quota` silently reinterprets any bare value above 64 as megabytes: a 100 GB quota becomes 1 GB
- **File:** `core/api.py:236` (`_POSITIONAL_MB_THRESHOLD = 64.0`), `core/api.py:313-316`
  (the heuristic), `core/api.py:294-311` (precedence), `core/api.py:4050-4075`
  (`set_cache_quota`), `ui/web_new_v2/js/settings.js:266` (the only production caller)
- **Confirmed:** yes
- **Description:** a bare number larger than 64 is assumed to be megabytes. The frontend
  calls the method **positionally** (`window.pywebview.api.set_cache_quota(val)`), so the
  ambiguous form is the only form the UI uses — the "explicit gigabyte value wins" rule
  in the docstring can never apply to it. The UI select currently offers 1/2/5/10 GB
  (`index.html:1800-1804`), so the shipped UI is safe, but the conversion factor is 1024
  and there is no ceiling on the value the bridge accepts.
- **Cause:** a unit-inferring heuristic is applied to a channel that carries no unit, and
  the resulting "GB" value is then floored at 1 GB, which hides the mistake instead of
  reporting it.
- **Trigger conditions:** any `set_cache_quota` call whose value exceeds 64 — a future
  "100 ГБ" option, a script, a restored older configuration, or another caller of the
  public bridge method.
- **User impact:** the user asks for 100 GB and silently gets 1 GB; the cache is then
  purged against the wrong quota, deleting far more of the stream cache than intended
  (`core/api.py:4086` → `purge_stream_cache(quota_bytes=quota_val * 1024**3)`).
- **Evidence:**
  ```python
  236: _POSITIONAL_MB_THRESHOLD = 64.0
  ...
  313:     # Heuristic: a bare number > 64 with no explicit unit key is MB, not GB.
  314:     if size_mb is None and val_gb is not None and val_gb > _POSITIONAL_MB_THRESHOLD:
  315:         size_mb = val_gb
  316:         val_gb = None
  ```
  and the floor that hides it:
  ```python
  4072:             if val_gb < 0.5:
  4073:                 val_gb, size_mb = 1.0, 1024.0
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` section B:
  ```
  {'quota_gb': 500}  -> (0.48828125, 500.0)
  {'quota_gb': 100}  -> (0.09765625, 100.0)
  {'quota_gb': 65}   -> (0.0634765625, 65.0)
  {'quota_gb': 64}   -> (64.0, 65536.0)
  ```
  100 GB → 0.098 GB → floored to 1.0 GB by `set_cache_quota`.
- **Suggested fix:** make the unit explicit at the call site (`set_cache_quota(cache_quota_gb=val)` —
  the bridge already accepts the named form, and `js/settings.js:263` already writes
  `cache_quota_gb` with the correct unit), and drop or hard-bound the >64 heuristic. A
  value that is implausible in either unit should be rejected with an error instead of
  reinterpreted.
- **Fix side effects:** older builds (and `storage.cache_size_mb` writers) used the
  positional form with a megabyte value; removing the heuristic without a migration would
  turn a 500 MB legacy write into a 500 GB quota. The alias handling has to be kept for
  the explicit `cache_size_mb=` key, and the migration path reviewed before the heuristic
  is dropped.
- **Discovered by:** A

#### F-WN-03-7  [P3] — `_as_float` accepts NaN/inf, and a NaN quota silently becomes "no limit"
- **File:** `core/api.py:223-230` (`_as_float`), `core/api.py:299-327`
  (`_normalize_cache_quota`), `core/api.py:4062-4075` (`set_cache_quota`)
- **Confirmed:** yes
- **Description:** `_as_float` only rejects `None` and `bool`; `float("nan")` and
  `float("inf")` are returned as-is. In `_normalize_cache_quota` the final clamp
  `max(0.0, val_gb)` turns NaN into `0.0` (Python's `max` keeps the first argument when
  the comparison is false), and `0.0` is the documented encoding of "no limit". The
  negative-value guard in `set_cache_quota` does not catch NaN either (`nan < 0` is false).
- **Cause:** no finiteness check on the parsed float.
- **Trigger conditions:** a non-finite value reaches `_as_float` — reachable through the
  bridge with a *string* argument (`set_cache_quota("nan")`), because pywebview
  serialises the arguments with `JSON.stringify` (`webview/js/api.js:243`), where a JS
  *number* `NaN`/`Infinity` becomes `null` but a JS *string* `"nan"` survives.
- **User impact:** the stream cache quota is switched to "no limit" (nothing is ever
  purged) while the call reports `{"success": true}`; the user believes a limit is in
  force. `inf` is handled better but produces an ugly error
  (`"cannot convert float infinity to integer"` from `int(round(inf))` at L4074).
- **Evidence:**
  ```python
  223: def _as_float(value):
  224:     """Best-effort float conversion; None when the value is not numeric."""
  225:     if value is None or isinstance(value, bool):
  226:         return None
  227:     try:
  228:         return float(value)
  ```
  ```python
  327:     return max(0.0, val_gb), max(0.0, size_mb)
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` sections A and B:
  ```
  _as_float('nan') = nan
  {'quota_gb': nan}       -> (0.0, 0.0)
  {'quota_gb': 'nan'}     -> (0.0, 0.0)
  {'quota_gb': inf}       -> (inf, inf)
  max(0.0, float('nan')) = 0.0
  ```
- **Suggested fix:** reject non-finite values in `_as_float` (`math.isfinite`) so the
  caller reports "quota not specified" instead of silently switching the quota off.
- **Fix side effects:** none for legitimate values; `_as_float` is also used for the
  negative-quota scan, where rejecting NaN/inf turns a silent pass into a clean rejection.
- **Discovered by:** A

#### F-WN-03-8  [P3] — `_extract_first_url` truncates URLs whose path ends in `)` and mangles text that merely starts with `http://`
- **File:** `core/api.py:198-220`, consumer `core/api.py:2364-2367`
- **Confirmed:** yes
- **Description:** two independent defects.
  (a) The regex `[^\s<>"']+` stops at an apostrophe, and the trailing-punctuation
  `rstrip('.,;:!?)]}"\'')` removes a closing parenthesis even when that parenthesis belongs
  to the URL (a Wikipedia-style path). The result is a truncated URL.
  (b) The "already looks like a URL" shortcut returns the whole trimmed text, so a paste
  that *starts* with `http://` but contains a second URL is returned as one string; the
  SSRF guard then validates only the first host, and the importer receives a URL with a
  space in it.
- **Cause:** the extractor treats "starts with http" as "is exactly one URL", and the
  punctuation strip is context-free.
- **Trigger conditions:** pasting a markdown link with parentheses in the path, a URL with
  a quoted query parameter, or a share blob that begins with a URL and continues with
  another one.
- **User impact:** `import_external_playlist` rejects the link with the generic
  "Некорректная или небезопасная ссылка" although the link was valid, and in case (b) the
  guard validates a different host than the one that will be requested.
- **Evidence:**
  ```python
  198: _URL_IN_TEXT_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
  ...
  212:     if text.lower().startswith(("http://", "https://")):
  213:         # Still strip trailing sentence punctuation: a link copied out of a
  214:         # sentence keeps it ("...list=PL123.").
  215:         return text.rstrip('.,;:!?)]}"\'')
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` section C:
  ```
  'see [link](https://en.wikipedia.org/wiki/Foo_(bar)) for details' -> 'https://en.wikipedia.org/wiki/Foo_(bar'
  "https://example.com/q?x='y'"                                     -> "https://example.com/q?x='y"
  'http://a.test/x https://b.test/y'                                -> 'http://a.test/x https://b.test/y'
  ```
- **Suggested fix:** balance parentheses when stripping trailing punctuation (only strip a
  `)` that has no matching `(` inside the URL), and cut the "starts with http" shortcut at
  the first whitespace so only the first URL is considered.
- **Fix side effects:** stopping at the first whitespace would change the behaviour for
  legitimately space-containing URLs (rare, and they must be percent-encoded anyway); the
  parenthesis balance must not strip the `)` of `.../Foo_(bar)` — the test corpus in
  `tests/` has no such case, so a new regression test is needed.
- **Discovered by:** A

#### F-WN-03-9  [P3] — `_is_empty_secret_write` swallows every falsy write to a secret key and reports success: a stored credential can never be cleared
- **File:** `core/api.py:267-269`, callers `core/api.py:1884-1885`, `core/api.py:1893-1894`,
  `core/api.py:2944-2945`; UI `ui/web_new_v2/js/settings.js:952`
- **Confirmed:** yes
- **Description:** the predicate is `key in _SECRET_SETTING_KEYS.get(category, ()) and not
  value`. `not value` is true for `""`, `0`, `False` **and** `None`, so *any* falsy write to
  `auth.yandex_token` or `auth.oauth_client_secret` is dropped — and the caller answers
  `{"success": True}` (L1885/L1894) or `True` (L2945), so the frontend is told the write
  happened.
- **Cause:** the helper conflates "the masked echo-back of the current value" (an empty
  string) with "the user cleared the field", and there is no separate way to express
  "remove this credential".
- **Trigger conditions:** the user empties the Yandex-token or OAuth-secret field and
  saves. The UI placeholder even states the design: "Токен сохранён (введите новый, чтобы
  заменить)" (`js/settings.js:952`).
- **User impact:** a credential the user meant to revoke stays active and keeps being used
  for API calls, while the UI reports success and shows the "saved" placeholder again.
  There is no bridge path that can clear `auth.yandex_token` at all.
- **Evidence:**
  ```python
  267: def _is_empty_secret_write(category: str, key: str, value) -> bool:
  268:     """A blank secret from the UI (masked read echoed back) must not wipe the stored one."""
  269:     return key in _SECRET_SETTING_KEYS.get(category, ()) and not value
  ```
  ```python
  2944:         if _is_empty_secret_write(category, key, value):
  2945:             return True
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` section G:
  ```
  empty secret write ('', auth, yandex_token): True
  empty secret write (0, auth, yandex_token): True
  empty secret write (False): True
  empty secret write (None): True
  ```
- **Suggested fix:** treat only the empty string as "unchanged", add an explicit
  "clear" affordance (a dedicated bridge method or a sentinel value) for revocation, and
  answer `{"success": False, "error": ...}` instead of a bare success when a value is
  dropped.
- **Fix side effects:** the current UI relies on the "empty ⇒ keep" rule to avoid wiping a
  token when the settings form round-trips the masked value. Distinguishing the two cases
  must not break that round-trip, which is why the sentinel has to be explicit rather than
  "any falsy value".
- **Discovered by:** A

#### F-WN-03-10  [P3] — The bridge error wrapper erases the introspected signature of every wrapped method
- **File:** `core/api.py:401-444` (`_install_bridge_error_logging`), `core/api.py:420-442`
  (`_make`/`_wrapped`), consumer `.venv_win/Lib/site-packages/webview/util.py:170-191`
  (`get_args` → `inspect.getfullargspec(func).args`)
- **Confirmed:** yes
- **Description:** pywebview publishes the JS-side API from the *introspected* signature of
  each exposed callable. `functools.wraps` copies `__wrapped__`, but
  `inspect.getfullargspec` does not follow wrapper chains
  (`follow_wrapper_chains=False`), so the wrapper's own signature `(*args, **kwargs)` is
  what gets reported: every wrapped method is published to JavaScript as a **zero-argument**
  function, while the five methods in `_UNWRAPPED` keep their real signature.
- **Cause:** the wrapper replaces the callable with a generic `*args/**kwargs` shim and
  relies on `functools.wraps` for metadata, but the one piece of metadata pywebview reads
  (`getfullargspec`) is exactly the piece `functools.wraps` does not restore.
- **Trigger conditions:** always — the wrapper is installed on every public method in
  `AppApi.__init__` (L392).
- **User impact:** none today — pywebview's JS shim forwards
  `Array.prototype.slice.call(arguments)` (`webview/js/api.js:62-78`), so the arguments
  survive regardless of the declared arity, and the existing tests pass. It is a latent
  trap: any future pywebview version that trusts the published parameter list, or any
  frontend code that reads `api.method.length`, would break, and the API surface is now
  inconsistent between wrapped and unwrapped methods.
- **Evidence:**
  ```python
  420:             def _make(func, method_name):
  421:                 @functools.wraps(func)
  422:                 def _wrapped(inner_self, *args, **kwargs):
  ```
  vs. `webview/util.py:170-172`:
  ```python
  def get_args(func: object):
      params = list(inspect.getfullargspec(func).args)
      return params
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` section H wraps a
  2-arg and a 1-arg method exactly like `_install_bridge_error_logging` does:
  ```
  alpha  getfullargspec(bound).args = ['inner_self']   -> published params []
  beta   getfullargspec(bound).args = ['inner_self']   -> published params []
  ```
  (before wrapping, `alpha` reports `['self', 'a', 'b']`).
- **Suggested fix:** set `_wrapped.__signature__ = inspect.signature(func)` (bound to the
  instance) after `functools.wraps`, or wrap at class level with a descriptor that keeps
  `__get__` semantics, so introspection continues to report the real parameters.
- **Fix side effects:** changing the published signature changes what pywebview generates
  in `webview/js/api.js`; the arity of the generated JS functions would change, so the
  frontend should be re-checked for any reliance on `Function.length`.
- **Discovered by:** A

#### F-WN-03-11  [P3] — The bridge error log and the `api_error` toast record the raw exception text, which can contain the secret that failed
- **File:** `core/api.py:428-441` (the `except` block of `_wrapped`)
- **Confirmed:** hypothesis (the code path is confirmed; that a *current* bridge method
  embeds a credential in its exception message is not confirmed)
- **Description:** the wrapper logs `str(exc)` verbatim and puts the same text into the
  `api_error` payload that the frontend renders as a toast
  (`ui/web_new_v2/js/events.js:335-341`).
- **Cause:** the exception text is not redacted before it is written to
  `~/.nedotify/logs/app.log` or displayed on screen.
- **Trigger conditions:** a bridge method raises an exception whose message contains a
  credential — e.g. a provider client that echoes the request (token in the URL/header)
  inside a `ValueError`/`RuntimeError`.
- **User impact:** a credential can be written verbatim into the log file that users attach
  to bug reports, and flashed on screen in a toast. Low, because the log is local.
- **Evidence:**
  ```python
  429:                         logger.error(
  430:                             "bridge call %s() failed: %s: %s",
  431:                             method_name, type(exc).__name__, exc, exc_info=True,
  432:                         )
  ...
  436:                             "error": f"{type(exc).__name__}: {exc}",
  ```
- **Reproduction / verification:** static — the unredacted `str(exc)` reaches both sinks.
  What is missing for a full confirmation: an audit of the provider clients for exception
  messages that embed tokens (WN-18..WN-22 territory); the settings secrets are the most
  likely carriers (`auth.yandex_token`, `auth.oauth_client_secret`).
- **Suggested fix:** log the exception *type* plus a truncated message at WARNING level
  and keep the full text at DEBUG, and redact the known secret values before putting the
  message into the `api_error` payload.
- **Fix side effects:** truncating the message reduces the diagnostic value of the toast
  and of the log; the full traceback is still available via `exc_info=True` at DEBUG level.
- **Discovered by:** A

#### F-WN-03-12  [P3] — `_mask_secrets` masks 2 of the credential-bearing `auth` settings; `auth.proxy_url` (which may embed `user:password@host`) is returned to JS verbatim
- **File:** `core/api.py:239-253` (`_SECRET_SETTING_KEYS`, `_mask_secrets`),
  `core/settings.py:242-250` (the `auth` defaults),
  `services/base_service.py:25-58` (`normalize_proxy_url`)
- **Confirmed:** yes
- **Description:** the mask table contains only `("yandex_token", "oauth_client_secret")`.
  The `auth` category also holds `proxy_url`, a free-text proxy URL that
  `normalize_proxy_url` passes to `requests`/yt-dlp and that may carry
  `http://user:password@host:port` credentials. It is returned unmasked by
  `get_settings()` (L2935), `get_settings(category)` (L2925) and
  `get_settings_by_category()` (L2959).
- **Cause:** the mask table was written for the two values that the UI must be able to
  show as "set / not set" and was never extended to the other credential-shaped field.
- **Trigger conditions:** the user stores a proxy URL with embedded credentials and opens
  the settings screen.
- **User impact:** the credential travels to the WebView and sits in the frontend's
  settings object (and in any frontend logging). The consumer is the app's own local
  WebView, so the exposure is local rather than remote — low severity.
- **Evidence:**
  ```python
  239: # Secrets never travel back to JS: the bridge answers with "" and a has_* flag.
  240: _SECRET_SETTING_KEYS = {"auth": ("yandex_token", "oauth_client_secret")}
  ```
  ```python
  246:         "proxy_url": "",
  ```
- **Reproduction / verification:** scratch script `_scratch_wn03.py` section G:
  ```
  mask auth: {'yandex_token': '', 'oauth_client_secret': '', 'other': 'x',
              'has_yandex_token': True, 'has_oauth_client_secret': True}
  ```
  (only the two listed keys are touched; `proxy_url` is untouched).
- **Suggested fix:** mask `auth.proxy_url` as well, or mask only the userinfo component of
  the URL and keep the host/port visible so the field stays usable.
- **Fix side effects:** masking the whole value would leave the user unable to see which
  proxy is configured (the `has_*` flag covers that); masking only the userinfo needs a
  small URL-aware helper.
- **Discovered by:** A

### 3. Clean areas

- **`_emit` payload serialisation** (`core/api.py:1131-1139`): `json.dumps` is inside the
  guard, so a non-serialisable or self-referential payload is logged and dropped instead
  of raising out of `_emit` — exactly the failure mode the contract calls out. Verified by
  `tests/test_emit_thread_safety.py:103-116` and by the fact that `json.dumps` is
  default-`check_circular`. Falsy payloads (`[]`, `0`, `False`, `""`) are preserved
  (`data if data is not None else {}`), pinned by
  `tests/test_emit_thread_safety.py:119-130`. The generated JS is safe: both the event
  name and the payload go through `json.dumps`, so no injection into the `evaluate_js`
  string is possible.
- **UI-thread detection by thread identity** (`core/api.py:29`, `core/api.py:1147`):
  `_MAIN_THREAD = threading.main_thread()` is captured at import time and compared with
  `is`, i.e. by object identity, not by thread name — so a worker thread that happens to be
  named "MainThread" cannot fool it, and the identity cannot change during the process
  lifetime. The `loaded`-event justification in the comment is inaccurate for the
  installed pywebview (see F-WN-03-3), but the guard itself is correct and is the right
  shape: the branch is taken *only* for the main thread, and the main thread is the thread
  that runs the WinForms message loop in pywebview's edgechromium backend
  (`platforms/edgechromium.py:126` — `self.webview.Invoke(...)` followed by
  `semaphore.acquire()`, which is exactly the self-deadlock the branch avoids).
- **SSRF cache hygiene** (`core/api.py:99-130`): the cache is bounded at
  `_SSRF_CACHE_MAX = 512`, every mutation happens under `_ssrf_cache_lock`
  (a `threading.Lock`), the eviction picks the entry closest to expiry, and the lock is
  never held across the DNS call (`_dns_resolves_to_public_ip` does get → resolve → put),
  so there is no lock-ordering or deadlock risk. The key is the *hostname*, so two
  different hosts can never share a verdict (pinned by
  `tests/test_api_audit_b.py:259-268`). The cache stores a per-host verdict, not a
  per-URL one, so port/scheme differences cannot cross-contaminate it.
- **IP literal classification** (`core/api.py:176-190`): the decimal-integer form
  (`2130706433` → 127.0.0.1) is handled explicitly and fails closed on overflow
  (`except Exception: return False`). IPv6 literals are handled correctly by
  `ipaddress` — `::1` and the IPv4-mapped `::ffff:127.0.0.1` are both classified as
  loopback/private (verified: `IPv6Address('::ffff:127.0.0.1').is_loopback is True`),
  and `parsed.hostname` strips the brackets so `[::1]` is caught.
  `127.1` is caught too, via the `hostname.startswith("127.")` fallback.
- **`_bridge_write_error` / `_BRIDGE_READONLY_SETTINGS`** (`core/api.py:256-264`): a
  single, explicit deny-list for the one setting that must not be writable from the UI
  (`general.plugins_enabled` — enabling plugins runs third-party code). It refuses
  *before* the write in all three call sites (L1881, L1890, L2942), and the refusal is
  reported as an error, not as a success. No legitimate write is swallowed.
- **`_mask_secrets` does not corrupt the live settings cache** (`core/api.py:243-253` +
  `core/settings.py:532-535`): `get_category()` returns a copy and `_mask_secrets` copies
  again before mutating, so the stored secret is never blanked by a read. The
  `has_<key>` flags are computed from the pre-mask value, so "is a token set?" survives the
  round trip.
- **`_missing_local_file_message`** (`core/api.py:330-339`): total function — a non-dict
  track, a track without a title, a missing `file_path` and a Cyrillic label are all
  handled; verified for `None`, `{"title": ""}` and a full dict.
- **`_install_bridge_error_logging` does not swallow errors** (`core/api.py:401-444`): the
  wrapper logs, emits `api_error` and **re-raises**, so pywebview still turns the call into
  a rejected promise (`webview/util.py:244-248`) and the JS `.catch()` still fires. The
  `api_error` payload shape (`method`, `error`, plus `code`/`title`/`message`/`action` from
  `describe_error`) matches the consumer in `ui/web_new_v2/js/events.js:335-341`. The
  `_UNWRAPPED` set correctly excludes `cleanup`, `shutdown`, `set_window`, `set_windows`
  and `emit_event`, so teardown and the emit primitives cannot recurse into the wrapper.
- **`_offline_bridge_result` event names and argument indices** (`core/api.py:461-512`):
  every event it emits exists in the frontend dispatcher
  (`ui/web_new_v2/js/events.js`: `feed_ready`, `popular_results`, `authentic_home_ready`,
  `releases_ready`, `mixes_ready`, `artist_profile_error`, `album_details_ready`,
  `track_wave_ready`, `yandex_device_auth_result`, `operation_error`), and the
  `request_id` it forwards is read from the right positional slot for each method
  (`get_artist_profile` → `args[2]`, `get_album_details` → `args[1]`,
  `get_track_wave` → `args[3]`), matching the JS request/response correlation in
  `js/artist_profile.js:136-154` and `js/search.js:599-618`. The `kwargs` fallbacks are
  dead for real bridge calls (pywebview always passes positionally,
  `webview/util.py:307`) but are correct for internal Python calls such as
  `get_yt_playlist_tracks` → `self.get_playlist_tracks(..., source="youtube")`.
- **Offline interception of the methods that must keep working**: `search` (L2085),
  `recover_stream` (L4168) and `get_playlist_tracks(source='local')` each check
  `is_offline` themselves and are therefore *not* double-handled; `get_home_data`,
  `get_home_artists` and `get_search_suggestions` are purely local and are correctly left
  alone. `set_offline_mode` is not intercepted, so the user can always turn the mode off
  again.
- **`AppApi.__init__` ordering** (`core/api.py:345-392`): the engine callbacks, the tray
  and the error-logging wrapper are all installed before the object is published to the
  core (`self._core.api = self` at L347 happens first, but the core's own background
  threads do not call into the API during that window); the `TrayIcon` import is guarded
  (L384-390) so a missing `pystray` degrades to `self._tray = None` instead of leaving a
  half-built object; `self._core.tray` is always assigned, so the core never sees a
  missing attribute. `cleanup()` is idempotent and exception-safe (L446-459) and both
  executor shutdowns are `wait=False`, so it cannot block app exit.
- **`describe_error` mapping** (`core/user_errors.py:6-24`): stable categories, a 240-char
  cap on the invalid-input message, and a sensible fallback — used correctly by
  `_offline_bridge_result` (`describe_error('offline', method)` returns the offline
  category because the literal string `'offline'` is matched at L13).

### 4. Coverage gaps

- **`_emit` is outside the line range of this area.** `WIN_AUDIT_AREAS.md` assigns
  `core/api.py` L514–1160 to **WN-04** (window management), and `_emit` lives at
  L1122–1159. The WN-03 area *title* names `_emit`, and the task brief asked for it, so I
  reviewed it; F-WN-03-3 and F-WN-03-4 therefore overlap with whatever WN-04's reviewer
  produces for the same lines. **Do not double-count** — the root causes are the missing
  ordered emit worker (F-3) and the missing closed-flag (F-4), both of which live in the
  `_emit`/`cleanup` code that WN-04 will also read.
- **No live app run.** Per the ground rules I did not start the app, so the *reachability*
  of `_emit`'s main-thread branch is inferred from the pywebview source
  (`webview/util.py:230`, `webview/event.py:55-60`) and from the absence of any
  main-thread caller in this repo — not observed at runtime. The same applies to the
  "no emit after cleanup" claim: the code path is confirmed by the scratch script, the
  runtime manifestation (pywebview's `EvaluateScriptAsync` on a disposed control) is not.
- **No network access.** The DNS-rebinding scenario in F-WN-03-1/2 was verified by
  monkeypatching `socket.getaddrinfo`, not against a live rebinding resolver; the
  `getaddrinfo` behaviour of this machine was sampled for `0x7f000001`, `0177.0.0.1`,
  `127.1` and `2130706433` (all four raise `gaierror` on this Windows host, so the guard's
  `except` path — and hence the fail-open — is the one that is taken for them).
- **The fetch sinks of the SSRF guard were not audited**: `core/proxy.py` (WN-11) beyond
  the two `_is_ssrf_safe_url` call sites and the token gate, `services/playlist_import_service.py`
  (WN-24) beyond `resolve()`, and the provider clients that produce the URLs the proxy
  fetches. Whether those sinks re-resolve DNS (they do, via `urllib`/`requests`/yt-dlp)
  and whether they are reachable with an attacker-controlled URL is WN-11/WN-24's question.
- **`core/api.py` L1–520 was the assigned range**; the helper call sites outside it
  (L1860–1945, L2077–2156, L2355–2404, L2905–2974, L4021–4111, L4166–4228) were read
  only as evidence for the helpers, and their own defects (e.g. the `get_album_details`
  request-id bookkeeping) were not reviewed.
- **`core/settings.py` was read only where the helpers touch it** (defaults tree,
  `get`/`set`/`get_category`). The write-behind batching, the hotkey mirror and the
  settings flush/atexit behaviour belong to WN-14 and were not evaluated.
- **The `has_*` masking contract was not checked against the frontend's round-trip** for
  the `auth` category beyond `js/settings.js:952`/`:983`; WN-08 owns the settings
  round-trip as a whole.
- **The `android/` subtree was not opened**, per the brief.
