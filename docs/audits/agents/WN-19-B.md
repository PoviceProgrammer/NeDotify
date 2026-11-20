## AREA WN-19 — YouTube provider — ROLE B

### 1. Scope reviewed

**Files opened (read in full or in the cited ranges):**

| File | Lines read | Why |
|---|---|---|
| `services/youtube_service.py` | 1–1190 (whole file, 1037 non-empty lines) | the area under review |
| `services/base_service.py` | 1–329 (whole) | shared cache / executor contract |
| `services/soundcloud_service.py` | 1–1023 | structural comparison (WN-20) |
| `core/settings.py` | 220–499 | `auth.*` schema, `get`/`set`/`flush` |
| `core/api.py` | 225–294, 2900–2979 | `_mask_secrets`, `get_settings`/`get_all_settings` |
| `core/database.py` | 2095–2164 | `get_all_settings` / `get_settings_by_category` |
| `core/app.py` | 296–340, 560–586 | `re_resolve_stream_url_async`, shutdown of the pool |
| `core/proxy.py` | 930–1104 | cookie injection + self-heal, `_get_ydl` call site |
| `core/downloader.py` | 130–209, 460–579, 600–729 | `_call_provider`, `download_context`, retry loop |
| `core/download_transfer.py` | 1–128 | `DownloadContext.ydl_options` |
| `core/resolver.py` | 150–271 | single-flight, `_failed` memo, `invalidate` |
| `core/playback_recovery.py` | (grep) | direct provider calls |
| `audio/engine.py` | 185–229 | 10 s resolution deadline |
| `services/track_resolver.py` | 285–344 | `_search_youtube` |
| `utils/cache_manager.py` | 280–399 | second consumer of `_get_ydl_opts` / `_require_audio_file` |
| `ui/web_new_v2/index.html` | 1728–1757 | cookie settings UI |
| `ui/web_new_v2/js/settings.js` | 375–399, 954–960 | cookie settings UI wiring |
| `.venv_win/.../yt_dlp/YoutubeDL.py` | 735–774, 1040–1069, 4210–4269 | `cookiejar` cached_property, `close()`/`save_cookies()` |
| `.venv_win/.../yt_dlp/cookies.py` | 60–179, 1141–1148, 1320–1369 | `load_cookies`, `_merge_cookie_jars`, `save()` |
| `tests/test_youtube_gating.py`, `tests/test_youtube_related.py`, `tests/test_hls_playback.py`, `tests/test_soundcloud_drm_unavailable.py`, `tests/test_provider_loading.py`, `tests/test_provider_performance.py`, `tests/test_stream_startup_performance.py`, `tests/test_download_integrity.py`, `tests/test_media_guard_f3.py` | full | test coverage assessment |

**Callees traced into other areas (not double-reported here):**

- `core/proxy.py:990-995, 1068-1071` — calls `youtube._get_ydl('high')` from a per-request thread (**WN-11**); the per-request cost is charged there, the thread-local design is charged here (F-WN-19-5).
- `core/download_transfer.py:24-32` — `ydl_options()` clobbers `overwrites` (**WN-13**); the conflicting intent is in WN-19 (F-WN-19-9).
- `core/downloader.py:37, 807` — `_downloaded_file_defect` is the safety net that makes F-WN-19-6 non-fatal (**WN-13**).
- `core/resolver.py:79-99` — `_failed` memo partially compensates for the missing provider-level memo (F-WN-19-10) (**WN-15**).
- `core/api.py:243-253` — `_mask_secrets` decides what reaches JS (**WN-08**).
- `services/soundcloud_service.py:390, 751, 895` — constructs a new `YouTubeService` per fallback (**WN-20**), see ARCH-4.
- `core/settings.py` `auth` schema / `services/base_service.py` cache contract — **WN-14 / WN-18**.

**Out of scope / not opened:** the `android/` subtree.

---

### 2. Findings

#### F-WN-19-1  [P1] — `cookiefile` + `cookiesfrombrowser` on the same `YoutubeDL` makes yt-dlp write the browser's ENTIRE cookie jar (all domains, plaintext) into the user's `cookies.txt`

- **File:** `services/youtube_service.py:350-361` (both options set), `services/youtube_service.py:846-857` (browser sweep), `services/youtube_service.py:1112-1139` (download fallback)
- **Confirmed:** yes (runtime-verified against the installed yt-dlp 2026.08.19 with a faked browser extractor — no real browser was touched)
- **Description:** The provider sets `cookiefile` **and** `cookiesfrombrowser` on the same yt-dlp options dict. yt-dlp merges the two jars into one whose `filename` is the user's cookies file, and `YoutubeDL.close()` — which every `with yt_dlp.YoutubeDL(...)` block triggers — calls `save_cookies()` → `jar.save()`. The result: the merged jar, which contains **every cookie of the chosen browser for every domain** (bank sessions, GitHub, Google account, …), is written back to the user's `cookies.txt` in Netscape plaintext. The provider never asks for this and never warns.
- **Cause:** Two independent credential sources are combined in one `YoutubeDL`, and the code uses the context-manager form, whose `__exit__` persists the jar to `cookiefile`.
- **Trigger conditions:** `auth.cookies_file_path` points at an existing file **and** a gating error occurs (browser-sweep path, `youtube_service.py:844-857`), **or** `auth.browser_cookies` is set **and** the download falls back to `authenticated_opts` (`youtube_service.py:1136`). Both paths are the normal "обход ограничений" flow the settings section exists for.
- **User impact:** The user's exported `cookies.txt` is silently rewritten to contain session cookies for completely unrelated sites in plaintext. If that file lives in OneDrive/Dropbox/a git repo/a backup, that is credential exfiltration of the user's whole browser session. On the next run the app re-reads that file and re-merges it, so the jar keeps growing.
- **Evidence:**
  ```python
  # services/youtube_service.py:352-358  (inside _get_ydl_opts)
  if self.settings:
      cookies_file_path = self.settings.get("auth", "cookies_file_path", "")
      if not anonymous and cookies_file_path and os.path.exists(cookies_file_path):
          opts["cookiefile"] = cookies_file_path          # <-- user's file
      configured_browser = self.settings.get("auth", "browser_cookies", "none")
      if not anonymous and configured_browser and configured_browser != "none":
          opts["cookiesfrombrowser"] = (configured_browser,)   # <-- whole browser
  ```
  ```python
  # services/youtube_service.py:846-857  (sweep; cookiefile is NOT popped)
  cookie_opts = opts.copy()
  cookie_opts["cookiesfrombrowser"] = (b_name,)
  with yt_dlp.YoutubeDL(cookie_opts) as ydl_cookie:
      res = ydl_cookie.extract_info(video_url, download=False)
  ```
  ```python
  # services/youtube_service.py:1130-1139  (download fallback; both present)
  authenticated_opts = ydl_opts.copy()
  if self.settings:
      browser = self.settings.get('auth', 'browser_cookies', 'none')
      cookie_file = self.settings.get('auth', 'cookies_file_path', '')
      if browser and browser != 'none':
          authenticated_opts['cookiesfrombrowser'] = (browser,)
      if cookie_file and os.path.exists(cookie_file):
          authenticated_opts['cookiefile'] = cookie_file
  ...
      with yt_dlp.YoutubeDL(authenticated_opts) as clean_ydl:
          info = clean_ydl.extract_info(url, download=True)
  ```
  yt-dlp side (`yt_dlp/YoutubeDL.py:1054-1064`, `yt_dlp/cookies.py:93-113, 1141-1148, 1333-1352`):
  ```python
  def save_cookies(self):
      if self.params.get('cookiefile') is not None:
          self.cookiejar.save()
  def close(self):
      self.save_cookies()
  ```
  ```python
  def load_cookies(cookie_file, browser_specification, ydl):
      cookie_jars = []
      if browser_specification is not None:
          cookie_jars.append(extract_cookies_from_browser(browser_name, profile, ...))
      if cookie_file is not None:
          jar = YoutubeDLCookieJar(cookie_file); jar.load(); cookie_jars.append(jar)
      return _merge_cookie_jars(cookie_jars)      # one jar, filename = the user's file
  ```
- **Reproduction / verification:** `%TEMP%\opencode\verify_wn19_cookies.py` (hermetic: `extract_cookies_from_browser` faked with one cookie for `.mybank.example`; the cookiefile lives in `%TEMP%`). Output:
  ```
  jar holds: ['SID', 'bank_session']
  --- contents of the user's cookies.txt AFTER close() ---
  # Netscape HTTP Cookie File
  # This file is generated by yt-dlp.  Do not edit.
  .mybank.example  TRUE  /  TRUE  0  bank_session  SUPER-SECRET-BANK-TOKEN
  .youtube.com     TRUE  /  TRUE  0  SID            original-youtube-value
  browser cookie leaked into the cookiefile? True
  unrelated-domain cookie present?         True
  ```
- **Suggested fix:** Never put both sources in one `YoutubeDL`. Either (a) prefer `cookiesfrombrowser` and drop `cookiefile` whenever a browser is configured, or (b) when the browser is configured, copy the extracted jar into a private temp cookie file and point `cookiefile` at that temp file so yt-dlp can never write back to the user's path. Additionally, pass `cookiefile=None` for the sweep/download-fallback instances.
- **Fix side effects:** Option (a) drops the user's exported `cookies.txt` for browsers yt-dlp cannot read (Safari on Windows, Brave/Opera variants). Option (b) adds a temp-file lifecycle and must ensure the temp file is deleted and is not inside `~/.nedotify/`.
- **Discovered by:** B

---

#### F-WN-19-2  [P2] — `nocheckcertificate: True` disables TLS certificate verification for every yt-dlp request, including the media download

- **File:** `services/youtube_service.py:308`
- **Confirmed:** yes
- **Description:** `_get_ydl_opts()` unconditionally sets yt-dlp's `nocheckcertificate`, so the HTTPS connection to `youtube.com` **and** to `*.googlevideo.com` (the actual media bytes) is not authenticated. Any MITM on the path can serve arbitrary content as the "audio stream"; the app caches that URL, plays it and writes it into the user's library.
- **Cause:** A blanket "don't verify TLS" flag was added to work around an environment problem instead of fixing the CA store.
- **Trigger conditions:** Any network path where an attacker can intercept (rogue Wi-Fi, hostile DNS, compromised router, TLS-inspecting middlebox).
- **User impact:** Content substitution — a malicious file is silently accepted as the track, played, and stored as a download. The stream cache then serves it for the session (TTL 6 h, `base_service.py:131`).
- **Evidence:**
  ```python
  # services/youtube_service.py:303-312
  opts = {
      "quiet": True,
      "no_warnings": True,
      "format": format_str or "bestaudio/best",
      "noplaylist": True,
      "nocheckcertificate": True,     # <-- TLS verification off for every request
      "skip_download": True,
      "socket_timeout": 8,
      ...
  ```
- **Reproduction / verification:** `YouTubeService()._get_ydl_opts("bestaudio/best")["nocheckcertificate"] is True` → `True`. Same flag is also set on the download path via the same helper (`youtube_service.py:1087`).
- **Suggested fix:** Remove `nocheckcertificate` and fix the root cause (bundle `certifi`'s CA file with the app, or set `ssl` context for yt-dlp). If a user genuinely needs it, expose it as an explicit, per-user opt-in with a warning, not as a silent default.
- **Fix side effects:** Users behind a TLS-inspecting corporate proxy, or on a machine with an outdated/system-only CA store, will start seeing certificate errors — the flag is presumably there for that case. The fix must therefore include a diagnosable error path, not a hard removal.
- **Discovered by:** B
- **Note:** the same flag is set in `services/soundcloud_service.py:247,277` and `utils/cache_manager.py:352` — those are **WN-20** / **WN-27**, not re-reported here.

---

#### F-WN-19-3  [P2] — The anti-bot browser sweep silently persists `auth.browser_cookies` to the settings DB and can store a value the settings UI cannot represent

- **File:** `services/youtube_service.py:832-859` (write at 852-856); UI contract: `ui/web_new_v2/index.html:1734-1741`, `ui/web_new_v2/js/settings.js:382-393, 954-960`
- **Confirmed:** yes
- **Description:** When an extraction fails with an age/bot error and no browser is configured, the provider sweeps up to seven browsers and — on the first one that answers — writes that browser's name into the persisted settings (`auth.browser_cookies`). The user never opted in, no `setting_changed` event is emitted, and three of the seven candidates (`brave`, `vivaldi`, `yandex`) are **not options** of the settings dropdown. When such a value is stored, `selectBrowserCookies.value = settings.auth.browser_cookies` assigns a value that does not exist in the `<option>` list, so the control renders with no selection and the UI no longer reflects the real state.
- **Cause:** A service-layer fallback writes a user-facing security setting, and the value domain of that setting is wider than the UI's option list.
- **Trigger conditions:** A single gated extraction with `auth.browser_cookies == "none"`. That is the default configuration, so it happens to every affected user.
- **User impact:** (a) The app starts reading the user's browser cookie DB on every extraction and on every proxied stream request without consent; (b) the settings page shows a blank/none selection, so the user cannot see or turn the behaviour off from the UI; (c) the change is invisible until the settings page is reloaded.
- **Evidence:**
  ```python
  # services/youtube_service.py:840-857
  for b_cand in ("firefox", "edge", "chrome", "brave", "opera", "vivaldi", "yandex"):
      if b_cand not in browsers_to_try:
          browsers_to_try.append(b_cand)
  for b_name in browsers_to_try:
      try:
          cookie_opts = opts.copy()
          cookie_opts["cookiesfrombrowser"] = (b_name,)
          with yt_dlp.YoutubeDL(cookie_opts) as ydl_cookie:
              res = ydl_cookie.extract_info(video_url, download=False)
              if res:
                  if self.settings and (configured_browser == "none" or not configured_browser):
                      try:
                          self.settings.set("auth", "browser_cookies", b_name)   # <-- persisted silently
                      except Exception:
                          pass
                  return res
  ```
  UI option list (`ui/web_new_v2/index.html:1735-1740`): `none, chrome, firefox, edge, opera, safari` — `brave`, `vivaldi`, `yandex` are absent.
- **Reproduction / verification:** Set `auth.browser_cookies` to `"none"`, force `_extract_info_safe` to raise `"Sign in to confirm your age"`, run the sweep, then read `settings.get("auth","browser_cookies")` → it is now e.g. `"brave"`; `document.getElementById('select-browser-cookies').value = 'brave'` leaves `selectedIndex === -1`. Also note the dropdown offers `safari`, which yt-dlp cannot read on Windows → the extraction always fails with "Не удалось прочитать куки браузера" (`youtube_service.py:953-956`).
- **Suggested fix:** Do not persist from inside the provider. Return the detected browser to the caller and let the UI ask the user (or emit `setting_changed`). Constrain the sweep to the browsers the UI offers. Drop `safari` from the Windows option list.
- **Fix side effects:** Users who currently benefit from the implicit persistence would have to pick their browser once. The UI must be able to display every value the backend can store.
- **Discovered by:** B

---

#### F-WN-19-4  [P2] — `_get_ydl`'s cache key omits the cookie configuration, so changing `auth.browser_cookies` / `auth.cookies_file_path` never reaches the cached yt-dlp instances (`reset_ydl()` has zero callers)

- **File:** `services/youtube_service.py:253-275` (key at 269), `services/youtube_service.py:293-363` (opts frozen at creation), `services/youtube_service.py:227-251` (`reset_ydl`)
- **Confirmed:** yes
- **Description:** The thread-local instance cache is keyed by `("main"|"fallback", fmt, anonymous)`. The cookie configuration (`cookiefile`, `cookiesfrombrowser`, `proxy`) is read only when the instance is **created** (`_get_ydl_opts` is called at line 273, inside the `if ydl is None` branch). `reset_ydl()` — the only thing that drops those instances — has **no call site anywhere in the repository** (verified by grep over `*.py`).
- **Cause:** The cache key describes the *quality* dimension of the instance but not its *credential/transport* configuration.
- **Trigger conditions:** The user changes the cookies browser or the cookies.txt path in Settings and presses Play in the same session.
- **User impact:** The "Использовать куки браузера" switch appears to do nothing for playback: the streaming path keeps using the instance built before the change, so the gate is still hit. The download path behaves differently (it builds fresh opts at `youtube_service.py:1087`), so the same setting works for downloads and not for playback — the user cannot tell which path is failing.
- **Evidence:**
  ```python
  # services/youtube_service.py:267-275
  with self._ydl_lock:
      anonymous = self._prefer_anonymous
  key = ("fallback" if fallback else "main", fmt, anonymous)   # <-- no cookie/transport fingerprint
  ydl = store.get(key)
  if ydl is None:
      ydl = yt_dlp.YoutubeDL(self._get_ydl_opts(fmt, fallback=fallback))   # opts frozen here
      store[key] = ydl
  return ydl
  ```
  `grep -rn "reset_ydl" --include=*.py` → only the two definitions (`youtube_service.py:227`, `soundcloud_service.py:231`), no callers.
- **Reproduction / verification:** Build a service, call `_get_ydl("high")` once, change `settings` (`browser_cookies` `"none"` → `"chrome"`), call `_get_ydl("high")` again → the same object is returned, still constructed without `cookiesfrombrowser`.
- **Suggested fix:** Include a fingerprint of the credential/transport configuration (browser name + cookiefile path + proxy) in the instance key, or call `reset_ydl()` whenever an `auth.*` setting changes (the `setting_changed` event already exists in `core/api.py:2952`).
- **Fix side effects:** Keying on the fingerprint makes the instance set larger (bounded by the number of distinct configurations) and forces a rebuild — and, per F-WN-19-1, a rebuild re-triggers the cookie merge, so F-WN-19-1 must be fixed first.
- **Discovered by:** B

---

#### F-WN-19-5  [P2] — `_get_ydl` is thread-local and the proxy calls it from a per-request thread, so every proxied stream request re-reads and re-decrypts the user's whole browser cookie database

- **File:** `services/youtube_service.py:253-275` (thread-local instance store), `services/youtube_service.py:356-358` (`cookiesfrombrowser` in the opts); caller: `core/proxy.py:990-995` and `core/proxy.py:1068-1071` (**WN-11**)
- **Confirmed:** yes for the mechanism (verified at runtime); the wall-clock magnitude on a real browser profile is a **hypothesis** (see below)
- **Description:** `core/proxy.py` injects the provider's cookies into each proxied request with
  `cj = getattr(ydl, "_cookiejar", None) or getattr(ydl, "cookiejar", None)`.
  yt-dlp 2026.08.19 has **no `_cookiejar` attribute** (verified: `hasattr(ydl, "_cookiejar") is False`), so the second `getattr` evaluates the `cookiejar` `functools.cached_property`, which calls `load_cookies()` → `extract_cookies_from_browser()` → copies and decrypts the browser's whole cookie SQLite DB. Because `_get_ydl` is `threading.local()` and `core/proxy.py:421` uses `ThreadingHTTPServer` (a new thread per request), every proxied request builds a **new** `YoutubeDL` and therefore performs a **new** full browser-cookie extraction. The cookies are not even needed: the media URLs are signed `googlevideo.com` URLs.
- **Cause:** A per-thread instance store is used to hand out a credential-bearing object to a caller that only needs a read-only cookie snapshot, and the caller is on a per-request thread model.
- **Trigger conditions:** `auth.browser_cookies` is set to anything other than `"none"` **and** the user plays a YouTube track (the HTML5 `<audio>` element issues several Range requests per track).
- **User impact:** Each proxied Range request pays a browser-cookie-DB read + DPAPI decryption before the audio byte is fetched; the proxy request thread is blocked for that whole time. On a profile with hundreds of cookies this is the dominant cost of a stream request.
- **Evidence:** runtime output of `%TEMP%\opencode\verify_wn19.py`:
  ```
  == 3. _get_ydl is thread-local (proxy creates one per request thread) ==
    same object across threads?  False | ids: 2223177067088 2223177553616
    'cookiejar' attribute exists on the instance?  False
  == 4. accessing .cookiejar triggers load_cookies (browser DB read) ==
    load_cookies calls right after construction: 0
    load_cookies calls after the proxy's getattr(...,'cookiejar'): 1 [(None, ('firefox',))]
  ```
  `core/proxy.py:990-995`:
  ```python
  elif source == 'youtube':
      try:
          ydl = self.server.app_core.youtube._get_ydl('high')
          _inject_ydl_cookies(ydl, req)
  ```
  `core/proxy.py:421`: `class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer)`.
- **Reproduction / verification:** Mechanism is proven by the script above (it patches `yt_dlp.cookies.load_cookies` and counts calls). To measure the real cost: run the app with `auth.browser_cookies=chrome`, play a YouTube track and time the proxy requests — the delay appears in `core/proxy.py` between the request arriving and `urllib.request.urlopen`; each request first logs "Extracting cookies from chrome".
- **Suggested fix:** Expose a **cookie-free, shared** yt-dlp instance (or a one-shot cookie snapshot) from the provider for read-only injection, e.g. `YouTubeService.get_cookie_header(host)` that caches the jar once per session instead of per request. At minimum, the proxy should not construct a new provider instance per request.
- **Fix side effects:** A cached jar goes stale relative to the browser's own state; refresh it on the provider's existing `reset_ydl()`/settings-change path.
- **Discovered by:** B
- **Note:** the per-request *call* is WN-11's; the thread-local-with-credentials design that makes it expensive is WN-19's, so it is charged here once.

---

#### F-WN-19-6  [P2] — The provider has no negative memo for permanently unresolvable YouTube targets, so every retry re-runs the full extraction chain (up to 9 yt-dlp extractions + a cookie-DB read each)

- **File:** `services/youtube_service.py:772-860` (the chain), `services/youtube_service.py:894-1070` (`get_stream_url`, no failure memo); contrast `services/soundcloud_service.py:526-539` (`_mark_unavailable` + `_unavailable_cache`)
- **Confirmed:** yes
- **Description:** Nothing in `YouTubeService` records "this target can never be extracted". The failure chain is: anonymous attempt → cookie attempt → fallback format attempt → anonymous retry → **up to 7 browsers** (`youtube_service.py:840`) — each a full yt-dlp extraction, and each of the browser ones a full browser-cookie-DB read. SoundCloud solves exactly this with `_unavailable_cache` + `_mark_unavailable` (`soundcloud_service.py:526-539`, with the rationale spelled out at `soundcloud_service.py:65-83`); YouTube has no equivalent.
- **Cause:** The gating verdict is treated as a transient error and is not memoised at the provider level.
- **Trigger conditions:** Any age/bot/DRM-gated track, re-played, or a proxy 403 → `resolver.invalidate` → `re_resolve_stream_url_async` (`core/app.py:502`) → `youtube.get_stream_url` → the whole chain again.
- **User impact:** Repeated multi-second extractions and repeated browser-cookie DB reads for a track that will never play; the app also hammers YouTube, which is what triggers the rate limiting in the first place (`core/downloader.py:665-676` states this principle for the downloader but the provider does not apply it).
- **Evidence:**
  ```python
  # services/youtube_service.py:844-859 — the sweep, no memo, no early exit
  for b_name in browsers_to_try:
      try:
          logger.info(f"Trying YouTube cookies from browser: {b_name}")
          ...
      except Exception as cookie_err:
          logger.debug(f"Browser cookies extraction from {b_name} failed: {cookie_err}")
  raise e
  ```
  vs. the SoundCloud equivalent:
  ```python
  # services/soundcloud_service.py:526-539
  def _mark_unavailable(self, track_url: str, reason: str) -> None:
      self._unavailable_cache.set(_unavailable_key(track_url), reason)
      with self._cache_lock:
          self._stream_cache.pop(f'soundcloud:{track_url}', None)
  ```
- **Reproduction / verification:** Force `_extract_info_safe` to raise `"Sign in to confirm your age"` and call `get_stream_url` twice for the same id; count the `extract_info` calls — 1 + 7 browser attempts per call, i.e. ~16 extractions for two plays, with no memo in between.
- **Suggested fix:** Add a bounded, TTL'd "known unavailable" memo to `YouTubeService` (same shape as SoundCloud's `_unavailable_cache`), keyed by `_yt_cache_key(target)`, and consult it in `get_stream_url` before scheduling the extraction.
- **Fix side effects:** A track that YouTube later un-gates stays unavailable until the TTL expires; keep the TTL short (SoundCloud uses 1 h) and clear it on `reset_ydl()` / settings change.
- **Discovered by:** B
- **Note:** `core/resolver.py:79-99` (`_failed` memo, **WN-15**) mitigates this for the resolver path only. The proxy self-heal path (`core/app.py:502`) and `audio/engine.py:205` / `core/playback_recovery.py:128,157` call the provider directly and bypass it.

---

#### F-WN-19-7  [P3] — `_prefer_anonymous` is one service-wide flag: the first anonymous success silently disables the user's configured browser cookies for every later track

- **File:** `services/youtube_service.py:221` (declaration), `services/youtube_service.py:267-269` (read), `services/youtube_service.py:786-788, 825-827, 1127-1128` (writes), `services/youtube_service.py:350-358` (effect on the opts)
- **Confirmed:** yes
- **Description:** `_prefer_anonymous` is a single boolean on the service. Any successful anonymous extraction sets it to `True`, and `_get_ydl_opts()` then omits `cookiefile`/`cookiesfrombrowser` for **every** subsequent extraction. The user's explicit "use browser cookies" choice is therefore dropped after the first public track, and age/region-restricted tracks start failing again.
- **Cause:** A per-request credential decision is stored as global service state. The state is lock-protected (no data race), but its *scope* is wrong. `reset_ydl()` would clear it, but it has no callers (F-WN-19-4).
- **Trigger conditions:** The user has `auth.browser_cookies` configured and plays any public track first.
- **User impact:** The cookie bypass works for the first gated track and then silently stops working; the user sees "Sign in to confirm your age" again with no indication that the app disabled its own credentials.
- **Evidence:**
  ```python
  # services/youtube_service.py:783-788
  if info and _has_playable_audio(info):
      with self._ydl_lock:
          self._prefer_anonymous = True
      return info
  ```
  ```python
  # services/youtube_service.py:350-358 — reads the global flag
  with self._ydl_lock:
      anonymous = self._prefer_anonymous
  if self.settings:
      cookies_file_path = self.settings.get("auth", "cookies_file_path", "")
      if not anonymous and cookies_file_path and os.path.exists(cookies_file_path):
          opts["cookiefile"] = cookies_file_path
  ```
- **Reproduction / verification:** Configure `browser_cookies="chrome"`; resolve one public video anonymously (success) → `svc._prefer_anonymous is True`; the next extraction's opts contain neither `cookiefile` nor `cookiesfrombrowser`.
- **Suggested fix:** Make "anonymous" a per-request decision (e.g. "try anonymous first, then authenticated") rather than a persistent mode, or keep it as a per-track preference keyed by the target.
- **Fix side effects:** A per-request decision means the anonymous probe runs on every track, which doubles the extraction count for authenticated users — the trade-off F-WN-19-6's memo and the stream cache have to absorb.
- **Discovered by:** B

---

#### F-WN-19-8  [P3] — `download_audio_sync` sets `overwrites: True` and then the download context silently sets it back to `False`

- **File:** `services/youtube_service.py:1102-1108` vs `core/download_transfer.py:24-32` (**WN-13**)
- **Confirmed:** yes
- **Description:** The provider sets `'overwrites': True` with an explicit rationale, then unconditionally merges `download_context.ydl_options(output_dir)` over it. That dict contains `'overwrites': False` and `'continuedl': True`, so in the production download path the `overwrites: True` is dead.
- **Cause:** Two layers declare the same yt-dlp key and the merge order silently discards the provider's intent.
- **Trigger conditions:** A normal download (the downloader always builds a `DownloadContext`, `core/downloader.py:730`) where a file with the same outtmpl already exists (the outtmpl is `download_<track>_<digest>_<id>.<ext>`, stable across attempts).
- **User impact:** yt-dlp skips the download ("already downloaded") and the previous artefact — possibly a truncated or stale file — is returned as the result. This is exactly the failure the provider's own comment says it prevents.
- **Evidence:**
  ```python
  # services/youtube_service.py:1102-1108
  # A previous partial download of the same id must not be reused:
  # yt-dlp skips an existing file by default, so a 0-byte or
  # truncated leftover silently became "the download".
  "overwrites": True,
  })
  if download_context:
      ydl_opts.update(download_context.ydl_options(output_dir))   # <-- clobbers it
  ```
  ```python
  # core/download_transfer.py:24-32
  def ydl_options(self, output_dir):
      self.checkpoint()
      return {
          'outtmpl': os.path.join(output_dir, self.stem + '_%(id)s.%(ext)s'),
          'continuedl': True,
          'overwrites': False,        # <-- overwrites the provider's True
          'nopart': False,
          'progress_hooks': [self._ydl_progress],
      }
  ```
- **Reproduction / verification:** Call `download_audio_sync("dQw4w9WgXcQ", out_dir, download_context=ctx)` twice into the same `out_dir` with a fake `YoutubeDL` that records `opts['overwrites']` — the recorded value is `False`, not `True`.
- **Suggested fix:** Resolve the conflict explicitly: either the provider wins for the `overwrites` key, or the context takes the key out of its dict and lets the provider own it. Also make `continuedl` and `overwrites` mutually exclusive by intent (resume a `.part`, but never accept a complete stale file).
- **Fix side effects:** Turning `overwrites` back on for every attempt discards partial downloads and loses the resume capability that `continuedl` provides; the fix should be "resume the `.part`, but re-download a *complete* stale file".
- **Discovered by:** B

---

#### F-WN-19-9  [P3] — `download_audio_sync` returns the downloaded file without the `_require_audio_file` integrity gate on its three primary return paths

- **File:** `services/youtube_service.py:1148-1176` (gate applied only at 1173); helper defined at `services/youtube_service.py:142-163`
- **Confirmed:** yes
- **Description:** The module defines `_require_audio_file` precisely to reject a 0-byte file, a `.part` fragment and a non-media artefact such as `sb0.mhtml`, and its own docstring says that without this check "the track was marked is_downloaded=1 and download_complete fired — the user saw the track in the library with no audio in it". Yet `download_audio_sync` applies it only in the last-resort directory scan; the three earlier returns hand the file back unchecked.
- **Cause:** The gate was added to the fallback path instead of to the function's return contract.
- **Trigger conditions:** yt-dlp leaves a 0-byte/truncated file or a consent-page artefact at the `prepare_filename` path.
- **User impact:** A broken file is reported as a successful download *by this function*. In the current production path the damage is contained because `core/downloader.py:807` applies `_downloaded_file_defect` to the returned path (WN-13) — but the provider's own contract is inconsistent, and any future/other caller of `download_audio_sync` inherits the gap.
- **Evidence:**
  ```python
  # services/youtube_service.py:1151-1174
  # 1. Check prepare_filename
  downloaded_file = ydl.prepare_filename(info)
  if os.path.exists(downloaded_file):
      return downloaded_file                      # <-- no gate

  # 2. Check info ext
  ext = info.get('ext', 'm4a')
  cand = os.path.join(output_dir, f"yt_{clean_id}_{ts}.{ext}")
  if os.path.exists(cand):
      return cand                                 # <-- no gate

  # 3. Check common audio extensions
  for e in (".mp3", ".m4a", ".webm", ".opus", ".aac", ".ogg"):
      cand = os.path.join(output_dir, f"yt_{clean_id}_{ts}{e}")
      if os.path.exists(cand):
          return cand                             # <-- no gate

  # 4. Check directory for file starting with prefix
  for fname in os.listdir(output_dir):
      if fname.startswith(prefix) and not fname.endswith('.part'):
          found = os.path.join(output_dir, fname)
          _require_audio_file(found)              # <-- only here
          return found
  ```
- **Reproduction / verification:** Run `download_audio_sync` against a fake `YoutubeDL` that writes a 0-byte file at `prepare_filename(info)` and returns `{'ext':'m4a'}` — the function returns that path instead of raising "Файл повреждён".
- **Suggested fix:** Run every candidate path through `_require_audio_file` before returning it; the helper already exists in this module.
- **Fix side effects:** A legitimate very short clip (< 4 KiB) would be rejected; the floor is already documented as a floor (`tests/test_download_integrity.py:11-13`).
- **Discovered by:** B

---

#### F-WN-19-10  [P3] — The `quality` parameter is a no-op: all four quality levels resolve to the same format string

- **File:** `services/youtube_service.py:260-266`; setting: `core/settings.py:75` (`"audio": {"quality": "high"}`)
- **Confirmed:** yes
- **Description:** `low`, `medium`, `high` and `lossless` all map to `"bestaudio/best"`. The provider therefore always takes the highest-bitrate audio available, and because `fmt` is part of the instance key (`youtube_service.py:269`), the "low" request hits the same cache entry as the "high" one.
- **Cause:** The mapping table was collapsed to one value; the parameter survives in the signature but not in the behaviour.
- **Trigger conditions:** Any call with `quality="low"` (`core/app.py:502` passes a `quality` argument through).
- **User impact:** A user on a metered or slow link cannot reduce the audio bitrate; the stream cache and the downloaded file always carry the highest bitrate. (`audio.quality` has no UI control either — no `*.js` file reads it — so today the setting is simply dead.)
- **Evidence:**
  ```python
  # services/youtube_service.py:260-266
  quality_map = {
      "low": "bestaudio/best",
      "medium": "bestaudio/best",
      "high": "bestaudio/best",
      "lossless": "bestaudio/best",
  }
  fmt = quality_map.get(quality, "bestaudio/best")
  ```
  `grep -rn "['\"]quality['\"]" --include=*.py` → only `core/settings.py:75` and its tests; no production code reads `audio.quality`.
- **Reproduction / verification:** `YouTubeService()._get_ydl_opts("bestaudio/best")` vs `_get_ydl_opts` with `quality="low"` → identical `fmt`.
- **Suggested fix:** Either implement the ladder (`bestaudio[abr<=96]/bestaudio[abr<=192]/bestaudio`) or delete the parameter and the dead setting so the contract is honest.
- **Fix side effects:** A real ladder changes the stream URLs and therefore invalidates the existing stream cache (a one-off re-resolution cost) and changes the downloaded file sizes.
- **Discovered by:** B

---

#### F-WN-19-11  [P3] — `_detect_browser_cookies()` is dead code that would enumerate the user's entire cookie jar for five browsers

- **File:** `services/youtube_service.py:35-57`
- **Confirmed:** yes — zero call sites (repo-wide grep over `*.py` excluding `android/` and `.venv_win/` returns only the definition at line 39 and a stale comment in `tools/bench/profile.py:242`)
- **Description:** The function opens up to five installed browsers' cookie stores, materialises the **whole** jar (every domain, not just YouTube's) and only uses `len(list(cj))` to decide whether to continue. It is never called, so it has no runtime effect today — but it is the function the benchmark comment still refers to as the thing that "scrapes the real installed browser", which means the next person to wire it up will re-introduce an automatic, unconsented full-jar read.
- **Cause:** Dead code kept next to live code with a misleading name, plus a stale comment in the tooling that treats it as active.
- **Trigger conditions:** None today.
- **User impact:** None today. The risk is maintenance: the function is a loaded gun.
- **Evidence:**
  ```python
  # services/youtube_service.py:39-57
  def _detect_browser_cookies():
      global _detected_working_browser, _browser_detection_tried
      if _browser_detection_tried:
          return _detected_working_browser
      _browser_detection_tried = True
      for b in ("firefox", "chrome", "edge", "brave", "opera"):
          try:
              import yt_dlp.cookies
              cj = yt_dlp.cookies.extract_cookies_from_browser(b)
              if cj is not None:
                  cookie_count = len(list(cj))     # <-- counts EVERY cookie of EVERY domain
                  if cookie_count > 0:
                      logger.info(f"Auto-detected working browser cookies from '{b}' ({cookie_count} cookies)")
  ```
  `tools/bench/profile.py:242`: `# YouTubeService._detect_browser_cookies() scrapes the *real* installed` — the bench still believes the function runs.
- **Reproduction / verification:** `grep -rn "_detect_browser_cookies" --include=*.py` (excluding `android/` and `.venv_win/`) → 2 hits, both non-call sites.
- **Suggested fix:** Delete the function and the stale bench comment, or replace it with a YouTube-scoped check (`get_cookies_for_url("https://www.youtube.com")`) that never enumerates unrelated domains.
- **Fix side effects:** None.
- **Discovered by:** B

---

### 3. Clean areas

- **Target allowlist (`_is_allowed_youtube_target`, `youtube_service.py:86-98`) — CLEAN.** It is a genuine allowlist, not a blocklist. Runtime matrix:
  ```
  'dQw4w9WgXcQ'                                             -> True
  'https://www.youtube.com/watch?v=dQw4w9WgXcQ'             -> True
  'https://youtu.be/dQw4w9WgXcQ?t=12'                       -> True
  'https://music.youtube.com/watch?v=dQw4w9WgXcQ'           -> True
  'file:///etc/passwd'                                      -> False
  'http://127.0.0.1:8080/'                                  -> False
  'https://evil.example/watch?v=dQw4w9WgXcQ'                -> False
  'https://youtube.com.evil.example/watch?v=x'              -> False
  'https://www.youtube.com@evil.example/watch?v=x'          -> False
  'ytsearch1: Artist - Title'                               -> True
  'ytsearch1:'                                              -> False
  'ytsearch10:x'                                            -> False
  'ytsearch:'                                               -> False
  'HTTPS://WWW.YOUTUBE.COM/watch?v=dQw4w9WgXcQ'             -> True
  'https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ'        -> True
  ```
  `file://` and every non-http(s) scheme are rejected; the userinfo trick (`youtube.com@evil.example`) and the suffix trick (`youtube.com.evil.example`) are both rejected because the check uses `parsed.hostname` and an exact-match set; the scheme/host are case-normalised by `urlparse`. The `ytsearch1:` escape hatch is bounded (non-empty payload, exact prefix) and yt-dlp resolves it against YouTube's own search endpoint — no SSRF. Pinned by `tests/test_media_guard_f3.py:99-124` and `tests/test_provider_loading.py:44-46`.
- **No `--exec` / post-processor injection.** The provider never passes `exec_before_download`, `exec_after_download`, `postprocessors` or any `outtmpl` field derived from remote metadata. `outtmpl` is built from a locally sanitised id (`re.sub(r'[^a-zA-Z0-9_-]', '_', …)`, `youtube_service.py:1079`) or from `DownloadContext.stem` (also sanitised, `core/download_transfer.py:19-20`). No path traversal from user-controlled metadata into the output directory.
- **Stream-cache key (`_yt_cache_key`, `youtube_service.py:101-121`) — CLEAN and correct.** It normalises every spelling of the same video to one key, so the shared `BaseMusicService._stream_cache` cannot collide with another provider:
  ```
  'dQw4w9WgXcQ'                                   -> 'youtube:dQw4w9WgXcQ'
  'https://www.youtube.com/watch?v=dQw4w9WgXcQ'   -> 'youtube:dQw4w9WgXcQ'
  'https://youtu.be/dQw4w9WgXcQ?t=12'             -> 'youtube:dQw4w9WgXcQ'
  'https://music.youtube.com/watch?v=…&list=x'    -> 'youtube:dQw4w9WgXcQ'
  'https://www.youtube.com/shorts/dQw4w9WgXcQ'    -> 'youtube:dQw4w9WgXcQ'
  'ytsearch1: Artist - Title'                     -> 'youtube:ytsearch1: Artist - Title'
  ```
  The resolved video id is additionally cached under its own key (`youtube_service.py:1047-1049`), which is what makes the Spotify `ytsearch1:` → id handoff hit the cache. The search cache is namespaced (`yt_search:`, `yt_related:`) and shared TTL/LRU bookkeeping is inherited from `BaseMusicService`.
- **Single-flight for stream extraction — CLEAN.** `get_stream_url` registers the target in `_pending_streams` under `_ydl_lock` before scheduling, and every waiter is notified on both success and failure (`youtube_service.py:912-933`). The re-check inside the worker (`youtube_service.py:939-942`) closes the prefetch/Play race. Pinned by `tests/test_provider_loading.py:49-67` and `tests/test_stream_startup_performance.py:127-141`.
- **Anti-bot gating IS detected and surfaced, not presented as a generic failure — CLEAN.** `_yt_gating_error` (`youtube_service.py:75-79`) maps the yt-dlp gating markers to an actionable message, `_is_storyboards_only` (`youtube_service.py:124-130`) recognises a formats-but-no-playable-URL response, and both the download path (`youtube_service.py:1148-1149`) and the stream path (`youtube_service.py:1027-1030`) surface `_YT_GATED_MSG`. The download path deliberately does **not** set `ignoreerrors`, so the error propagates and the mapping stays reachable (documented at `youtube_service.py:336-347`). Pinned by `tests/test_youtube_gating.py`.
- **Retry policy of the provider — CLEAN.** `max_attempts = 1` (`youtube_service.py:943`) and the `for attempt in range(max_attempts)` loop with a `time.sleep(1)` retry branch (`youtube_service.py:1059-1063`) is dead code — the provider never retries on its own. The bounded, backing-off retry lives in `core/downloader.py:664-711` (3 attempts, 20 s/40 s), which is the right place for it. The provider therefore does not hammer YouTube by itself (the amplification comes from F-WN-19-6's missing memo, not from an internal retry loop).
- **The `with yt_dlp.YoutubeDL(...)` blocks that are *known* safe do not write cookies back.** `clean_opts` (`youtube_service.py:779-781`), the locked-cookie retry (`youtube_service.py:802-804`) and `anon_opts` (`youtube_service.py:819-821`) all pop both `cookiefile` and `cookiesfrombrowser`, so `save_cookies()` is a no-op there. Only the two paths in F-WN-19-1 leak.
- **yt-dlp is not run with any command-execution option** — no `exec_before_download` / `exec_after_download` / `postprocessors` / `exec` anywhere in the file, so a malicious title cannot become a shell command.
- **`_get_ydl_opts` never pins `player_client`** (`youtube_service.py:296-302`, `336-347`) — the documented PO-token pitfall is avoided, and the comment explains why.
- **Filename sanitisation (contract #8) holds on the provider's own paths.** `clean_id` is reduced to `[A-Za-z0-9_-]` before it reaches `outtmpl`, and `DownloadContext.stem` is sanitised the same way; no remote title or artist reaches the filename.

---

### 4. Coverage gaps

- **Magnitude of F-WN-19-5 is unmeasured.** The mechanism (a browser-cookie load per proxied request) is confirmed, but I did not measure the wall-clock cost of a real Chrome/Edge cookie extraction: doing so requires reading the user's actual browser profile, which the ground rules forbid (`Never touch ~/.nedotify/`; and reading the real browser DB is the very thing this finding is about). *Missing evidence:* a timing run on a machine with a populated browser profile, e.g. `time yt_dlp.cookies.extract_cookies_from_browser("chrome")`.
- **No live YouTube traffic was exercised.** The whole audit is static + hermetic; yt-dlp 2026.08.19 / ytmusicapi behaviour against the real service (rate limiting, PO-token gating, the exact error strings) was not reproduced. The gating strings in `_YT_GATING_MARKS` are taken from the code's own comments and the installed yt-dlp source, not from a captured failure.
- **`core/proxy.py` was read only in the ranges that touch this provider** (cookie injection 930–1104). The proxy's SSRF guard, the range-request logic and the retry ladder were not audited (WN-11's job); I only verified that the provider hands the proxy an object whose `cookiejar` access triggers a browser-cookie load.
- **`services/track_resolver.py` was traced only to its `_search_youtube` call site** (285–344); the memoisation and matching rules belong to WN-18.
- **`audio/engine.py` was read only around the resolution deadline** (185–229). The 10 s wait at `audio/engine.py:208` bounds the *user-visible* stall, but I did not verify every caller of `youtube.get_stream_url` (`audio/engine.py:363, 393, 469`; `core/playback_recovery.py:128, 157`; `core/app.py:502`) for the same bound — those are WN-05/WN-15/WX-01.
- **`utils/cache_manager.py:329-368` builds a second, divergent yt-dlp option set** (its own fallback dict with `nocheckcertificate`, `socket_timeout: 30`, `retries: 10`) instead of reusing `_get_ydl_opts`. That divergence is WN-27's to fix, but it means the "one place that defines yt-dlp options" idea is already broken; I did not enumerate every divergent option.
- **The `tests/` files listed in the task were read, but the suite was not executed.** `pytest` was not run, so "the tests pass" is not asserted anywhere in this report; all findings are derived from reading the code and from the two hermetic scripts under `%TEMP%\opencode\`.
- **The `android/` subtree was not opened**, per the scope of this run.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — There is no provider interface; every provider is a bespoke class with its own caching, proxy, retry and gating logic.**
`BaseMusicService` (`services/base_service.py:121-329`) offers only `_join_request`, the shared TTL/LRU caches and `submit`. Everything else is per-provider: YouTube builds its own `_TTLCache`-free world on the shared caches plus a private `_pending_streams` single-flight, while SoundCloud writes its **own** `_TTLCache` class (`soundcloud_service.py:17-49`) with its own lock, its own `_unavailable_cache`, `_verified_cache`, `_related_cache`, `_waveform_cache` and `_track_metadata_cache`. Two cache implementations and two single-flight implementations coexist in the same subsystem, and the two providers' yt-dlp option dicts have already drifted (`youtube_service.py:303-324` vs `soundcloud_service.py:243-254`: `socket_timeout` 8 vs 10, `concurrent_fragment_downloads`/`http_chunk_size` only on the YouTube side). *Direction:* a `ProviderAdapter` protocol (search / stream / download / related / metadata + declared capabilities) plus one shared `YtdlOptions` builder and one shared `ProviderCache` policy, so that a fix (e.g. `nocheckcertificate`, the `overwrites` conflict, the cookie rules) lands once instead of in three files.

**ARCH-2 — The credential policy is spread over four places and none of them agrees.**
`auth.cookies_file_path` and `auth.browser_cookies` are read in `_get_ydl_opts` (`youtube_service.py:352-358`), again in `download_audio_sync` (`youtube_service.py:1113-1119`), again in the sweep (`youtube_service.py:833-835`) and again in `soundcloud_service.py:260-262`; the "prefer anonymous" decision lives in a mutable flag on the YouTube service (`youtube_service.py:221`); the "which browsers may be used" list lives in the sweep (`youtube_service.py:840`) while the "which browsers may be selected" list lives in the HTML (`index.html:1735-1740`). Nothing validates the combination and nothing states the invariant "never combine `cookiefile` with `cookiesfrombrowser`". *Direction:* one `CredentialPolicy` object owned by the app that resolves to an explicit, validated yt-dlp option set (and refuses the invalid combination), plus a single source of truth for the browser list shared by the sweep and the UI.

**ARCH-3 — The provider owns state that belongs to the app.**
`YouTubeService` writes `auth.browser_cookies` into the settings DB (`youtube_service.py:854`) and mutates its own `_prefer_anonymous` mode; `core/proxy.py` reaches into `ydl._cookiejar` / `ydl.cookiejar` — a private yt-dlp attribute that does not even exist in the installed version, which is why the proxy silently falls into the expensive `cookiejar` path (F-WN-19-5). *Direction:* the provider should expose intent-level methods (`get_cookie_header(host)`, `invalidate(target)`, `refresh_credentials()`), and the proxy should never touch yt-dlp internals.

**ARCH-4 — `YouTubeService` is a heavyweight object that callers instantiate ad hoc.**
Its constructor creates a `ThreadPoolExecutor(max_workers=10)` and a `requests.Session` with a 30-connection pool for YTMusic (`youtube_service.py:195-213`), and it has no `close()`. `services/soundcloud_service.py:390, 751, 895` constructs a **new** `YouTubeService(self.settings)` on every SoundCloud fallback — one per failed search, per failed stream and per download — each with its own pool and session, none of them shut down. `core/app.py:575` shuts down only the singleton's pool. *Direction:* one app-owned provider registry with a lazily created, closable instance per provider; callers borrow it instead of constructing it.

**ARCH-5 — yt-dlp runs in-process, so a provider stall is a worker stall.**
Every extraction occupies one of the provider's 10 threads for the whole network round trip (`socket_timeout: 8`, `retries: 1`, plus, on the gated path, up to 9 chained extractions each preceded by a browser-cookie DB read). The pool is separate from `BaseMusicService._executor` (8 workers), so the *shared* pool is not starved, but the YouTube pool can be: 10 concurrent gated tracks occupy all 10 workers and every later `get_stream_url` queues behind them with no timeout of its own. The visible stall is bounded only by the callers (`audio/engine.py:208` waits 10 s). *Direction:* bound the provider's concurrency explicitly (a semaphore + a per-target deadline), and consider running yt-dlp as a subprocess so a hung extraction can be killed — which would also make the "no `--exec`" guarantee structural rather than incidental.

**ARCH-6 — The test suite pins the behaviour of the *happy path* but not the credential or filename contract.**
What is pinned: the gating message mapping and the storyboard detection (`tests/test_youtube_gating.py`), the allowlist (`tests/test_media_guard_f3.py:99-137`), the single-flight and cache reuse (`tests/test_provider_loading.py`, `tests/test_stream_startup_performance.py`), the related-tracks contract (`tests/test_youtube_related.py`), the DRM memo for SoundCloud (`tests/test_soundcloud_drm_unavailable.py`) and the file-integrity helpers (`tests/test_download_integrity.py`). What is **not** pinned anywhere:
  - that `cookiefile` and `cookiesfrombrowser` are never combined, nor that no cookie is written back to the user's file (F-WN-19-1) — the whole credential-write path is untested;
  - that `nocheckcertificate` is off (F-WN-19-2);
  - that the provider never persists `auth.browser_cookies` on its own, nor that the UI can represent every stored value (F-WN-19-3);
  - that changing `auth.browser_cookies` takes effect (F-WN-19-4) — `tests/test_provider_loading.py:90-109` even asserts the *current* behaviour (that the anonymous instance is reused) and therefore locks the bug in;
  - that `download_audio_sync` applies the integrity gate to every returned path (F-WN-19-9) — `tests/test_download_integrity.py` only tests the helper in isolation, never through `download_audio_sync`;
  - that `overwrites` survives the `download_context` merge (F-WN-19-8);
  - format selection (`quality_map`) — no test asserts which format string a given quality yields.
  *Direction:* add a hermetic test module that asserts the yt-dlp option set for each credential configuration (no both-sources, no `nocheckcertificate`, correct `overwrites`), and a test that runs `download_audio_sync` against a fake `YoutubeDL` that produces a 0-byte file.
