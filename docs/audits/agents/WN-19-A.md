## AREA WN-19 — YouTube provider — ROLE A

### 1. Scope reviewed

**Primary file (read in full, 1190 physical lines):**
- `services/youtube_service.py` — L1–1190 (module helpers L35–184, `class YouTubeService` L187–1190).
  - `_detect_browser_cookies` L39–57; `_YT_GATED_MSG`/`_YT_GATING_MARKS` L60–72; `_yt_gating_error` L75–79;
    `_YT_VIDEO_ID_RE`/`_YT_HOSTS` L82–83; `_is_allowed_youtube_target` L86–98; `_yt_cache_key` L101–121;
    `_is_storyboards_only` L124–130; `_AUDIO_DOWNLOAD_EXTS`/`_MIN_AUDIO_BYTES` L137–139;
    `_require_audio_file` L142–163; `_has_playable_audio` L167–184.
  - `__init__` L192–225; `reset_ydl` L227–251; `_get_ydl` L253–275; `_prefetch_top_tracks` L277–291;
    `_get_ydl_opts` L293–363; `available` L366–368; `search` L370–513; `search_sync` L515–544;
    `get_related_tracks_sync` L546–641; `get_album_tracks` L643–701; `get_playlist_tracks` L703–770;
    `_extract_info_safe` L772–860; `get_track_metadata` L862–892; `get_stream_url` L894–1070;
    `download_audio_sync` L1072–1176; `download_audio` L1178–1190.

**Callees / neighbours read to verify contracts:**
- `services/base_service.py` L121–329 (`_parse_yt_entry` L278–313, `_join_request` L140–161, stream/search cache L186–276).
- `core/api.py` L61–67 (`PROVIDER_SEARCH_TIMEOUT`, `BRIDGE_SYNC_BUDGET`), L483–512 (offline interception),
  L1195–1264, L2077–2232 (`search`), L2545–2613 (`get_playlist_tracks` / `get_yt_playlist_tracks`),
  L3267–3284 (`_resolve_track_metadata`), L1195–1240.
- `core/resolver.py` L1–271 (single-flight resolver).
- `core/downloader.py` L78, L140–155, L440–659 (`_call_provider`, `_download_spotify_track`, `_fetch_from_provider`).
- `core/download_transfer.py` L16–128 (`DownloadContext.stem` / `ydl_options`).
- `core/app.py` L36–75 (`_SC_FALLBACK_BUDGET_S`), L240–330, L348–506 (resolve cascade), L508–586 (cleanup).
- `core/settings.py` L340–518 (`get`/`set`/`flush` → SQLite `settings` table).
- `core/database.py` L1054–1083 (`add_track` signature).
- `core/proxy.py` L975–1034, L1055–1099 (`youtube._get_ydl('high')` cookie injection), L421–440 (ThreadingHTTPServer).
- `services/track_resolver.py` L248–330 (`_search_youtube`).
- `services/recommendation_service.py` L355–404, L870–909.
- `utils/cache_manager.py` L285–374.
- `audio/engine.py` L80–209.
- `ui/web_new_v2/index.html` L1727–1757 (browser-cookie select), `ui/web_new_v2/js/settings.js` L375–393, L954–960.
- `tests/test_youtube_gating.py` L1–62, `tests/test_youtube_related.py` (grep).
- Installed `yt_dlp` 2026.08.19 (`YoutubeDL.py` L2400–2650, L3130–3157; `extractor/youtube/_video.py` L3762–3811, L4150–4189) and
  `ytmusicapi` 1.12.3 (`YTMusic.get_playlist` / `get_album` signatures).

**Callees traced into other areas (defects there are NOT reported here):**
- `core/proxy.py` — calls `youtube._get_ydl('high')` from its own per-connection thread (cookie-jar lifecycle, WS-11).
- `core/downloader.py` / `core/download_transfer.py` — own the download filename/stem and the resume/overwrite policy (WS-13).
- `core/resolver.py` — owns the DB/mem stream cache and single-flight (WN-15).
- `core/settings.py` — owns plaintext persistence of settings (WN-14).
- `services/track_resolver.py` — owns the `source_url` consumption of provider dicts (WN-18).
- `utils/cache_manager.py` — owns the stream-cache download path (WN-27).

### 2. Findings

#### F-WN-19-1  [P1] — `_is_storyboards_only()` cannot detect a real storyboard-only response; the gating message is dead code in the streaming path
- **File:** `services/youtube_service.py:124-130` (definition), `services/youtube_service.py:1024-1031` (only caller), `tests/test_youtube_gating.py:13-20,32-39` (fixture that encodes the wrong assumption)
- **Confirmed:** yes
- **Description:** The anti-bot / storyboard detector tests for "formats exist but none has a `url`". Real yt-dlp storyboard formats **do** carry a `url`, so the detector returns `False` for a genuine storyboard-only payload. In addition, yt-dlp never returns such an info dict at all: the format selector yields nothing for a storyboard-only (or video-only) format list, so yt-dlp raises `Requested format is not available` *before* `info` exists — the detector is never reached.
- **Cause:** The check was written against an assumed payload shape (`{"format_id": "sb0", "ext": "mhtml"}` with no `url`), not against yt-dlp's actual storyboard format dict.
- **Trigger conditions:** Any YouTube video whose extraction returns only storyboard formats (the classic PO-token / anti-bot gate).
- **User impact:** The user never sees the actionable Russian `_YT_GATED_MSG` ("попробуйте SoundCloud…") from the streaming path; they see the raw yt-dlp English error instead (see F-WN-19-2).
- **Evidence:** `services/youtube_service.py:129-130`
  ```python
  fmts = (info or {}).get("formats") or []
  return bool(fmts) and not any(f.get("url") for f in fmts)
  ```
  Real yt-dlp shape — `yt_dlp/extractor/youtube/_video.py:3787-3794`:
  ```python
  yield {
      'format_id': f'sb{i}',
      'format_note': 'storyboard',
      'ext': 'mhtml',
      'protocol': 'mhtml',
      'acodec': 'none',
      'vcodec': 'none',
      'url': url,          # <-- the storyboard URL IS present
  ```
- **Reproduction / verification:** Ran the real helpers and yt-dlp's own selector against the real storyboard shape:
  ```
  _is_storyboards_only({'id':'v','formats':[{'format_id':'sb0','ext':'mhtml','acodec':'none','vcodec':'none','url':'https://i.ytimg.com/sb/0'}]}) -> False
  ydl.build_format_selector('bestaudio/best')(storyboard_ctx)               -> []
  ydl.build_format_selector('bestaudio/best/ba/b/worst')(storyboard_ctx)     -> []
  ```
  → yt-dlp raises "Requested format is not available"; `_is_storyboards_only` is never called with such a payload.
- **Suggested fix:** Detect the gate by inspecting the *format ids* (`format_id` starting with `sb`) and/or the absence of any format with `acodec != 'none'`, not by the presence of a `url`; and move the mapping to the exception path so it fires on the `DownloadError` that yt-dlp actually raises.
- **Fix side effects:** `tests/test_youtube_gating.py` pins the current (wrong) fixture — the test must be updated together with the fix.
- **Discovered by:** A

#### F-WN-19-2  [P1] — The streaming path never maps yt-dlp errors to user-facing text; "video unavailable / private / geo-blocked" is indistinguishable from a network error
- **File:** `services/youtube_service.py:958-982` (`get_stream_url` error branch), `services/youtube_service.py:64-72` (`_YT_GATING_MARKS`), `services/youtube_service.py:1130-1139` (the only `_yt_gating_error` call sites — download path only)
- **Confirmed:** yes
- **Description:** `_yt_gating_error()` is applied **only** in `download_audio_sync`. The stream-resolution path passes the raw yt-dlp exception text straight to `error_callback`. In addition `_YT_GATING_MARKS` contains no marker for removed / private / members-only / geo-blocked videos, so those are not distinguished from a timeout or DNS failure.
- **Cause:** The error-mapping helper was wired into the download path only; the streaming path was left with `str(exc)`.
- **Trigger conditions:** Any yt-dlp failure during `get_stream_url` — a gated video, a removed video, a private video, a region lock, or a plain network timeout.
- **User impact:** The UI shows an English yt-dlp string such as `ERROR: [youtube] dQw4w9WgXcQ: Video unavailable` or `ERROR: [youtube] xyz: Requested format is not available` in an otherwise Russian interface, and the user is not told that the track is permanently unavailable vs. temporarily unreachable. `core/app.py:379-497` then treats it as a generic failure and burns the 20 s SoundCloud fallback budget on a track that will never resolve.
- **Evidence:** `services/youtube_service.py:962-966`
  ```python
  except Exception as exc_fb:
      logger.warning(f"YouTube bot challenge fallback failed: {exc_fb}")
      if error_callback:
          error_callback(str(exc_fb))        # raw yt-dlp text, not _yt_gating_error(exc_fb)
  ```
  and `services/youtube_service.py:64-72` — the mark list has no "video unavailable" / "private" / "removed by the uploader" / "not available in your country" / "members-only" entry.
- **Reproduction / verification:** Static: `_yt_gating_error` appears only at `youtube_service.py:1134` and `:1139` (both inside `download_audio_sync`). Dynamic: with a stubbed `yt_dlp` whose `extract_info` raises `Exception("Requested format is not available")`, `get_stream_url` delivers the raw string to `error_callback` while `download_audio_sync` (same input) delivers `_YT_GATED_MSG` — the asymmetry is directly observable.
- **Suggested fix:** Route every yt-dlp exception in `get_stream_url` through `_yt_gating_error()` and extend `_YT_GATING_MARKS` with the "video unavailable / private / removed / geo-blocked" family mapped to a dedicated, actionable message.
- **Fix side effects:** `_YT_GATING_MARKS` is a substring list; broadening it risks swallowing genuine network errors — keep the "video unavailable" family in a separate list from the anti-bot family.
- **Discovered by:** A

#### F-WN-19-3  [P1] — Browser cookie stores are harvested automatically on every bot-gate error, overriding the user's explicit "None" setting and persisting the discovered browser to SQLite
- **File:** `services/youtube_service.py:832-859` (the sweep), `services/youtube_service.py:353-358` (`_get_ydl_opts` cookie wiring), `core/settings.py:401-418` + `core/settings.py:443-506` (plaintext persistence), `ui/web_new_v2/index.html:1734-1741` (the UI select)
- **Confirmed:** yes (code path and persistence); the *frequency* of the trigger is a hypothesis
- **Description:** When an extraction fails with an auth/bot-shaped error, the service walks a hard-coded list of seven browsers (`firefox, edge, chrome, brave, opera, vivaldi, yandex`), and for each one asks yt-dlp to open **that browser's entire cookie store** (`cookiesfrombrowser`) — i.e. it reads and decrypts the user's whole cookie jar (every domain, not just YouTube) into the app process. It then **persists the first browser that answered** into the app settings as `auth.browser_cookies`, even when the user explicitly selected "Не использовать (None)" (the default). No cookie *material* is written to disk — only the browser name — but the opt-out is silently reversed and the app keeps using that browser's cookies on every subsequent request.
- **Cause:** The sweep is a recovery mechanism that was never gated behind the user's `auth.browser_cookies` choice; the persistence condition `configured_browser == "none"` treats "none" as "not configured yet" rather than "explicitly disabled".
- **Trigger conditions:** Any extraction whose error text contains one of `("confirm your age", "sign in", "inappropriate", "bot", "confirm you")` — i.e. the common YouTube anti-bot state.
- **User impact:** (a) The user's browser cookies are read and decrypted without an opt-in, and the whole jar (all domains) is materialised in the app process; (b) the settings screen flips itself from "None" to e.g. "Google Chrome"; (c) if the swept browser is `brave`/`vivaldi`/`yandex` — none of which exist in the `<select>` — the persisted value has no matching option, so `ui/web_new_v2/js/settings.js:956` (`selectBrowserCookies.value = settings.auth.browser_cookies`) leaves the control blank and the next user interaction overwrites it with a different value.
- **Evidence:** `services/youtube_service.py:837-857`
  ```python
  browsers_to_try = []
  if configured_browser and configured_browser != "none":
      browsers_to_try.append(configured_browser)
  for b_cand in ("firefox", "edge", "chrome", "brave", "opera", "vivaldi", "yandex"):
      if b_cand not in browsers_to_try:
          browsers_to_try.append(b_cand)
  ...
              if self.settings and (configured_browser == "none" or not configured_browser):
                  try:
                      self.settings.set("auth", "browser_cookies", b_name)   # persists to SQLite
  ```
  `core/settings.py:413-418` → `self._dirty.add((category, key))` → `flush()` → `db.set_settings_batch([("auth.browser_cookies", "chrome", "auth")])` — a plaintext row in `~/.nedotify/nedotify_storage.db`.
- **Reproduction / verification:** Set `auth.browser_cookies = "none"`, force an extraction that raises `Exception("Sign in to confirm you're not a bot")`, and observe the sweep list being walked and `settings.get("auth","browser_cookies")` flipping from `"none"` to a browser name after the call. `services/youtube_service.py:39-57` (`_detect_browser_cookies`) is a *dead* second copy of this idea — see F-WN-19-12.
- **Suggested fix:** Only sweep browsers the user explicitly allowed; never persist a browser name that was not in the allowed set; if auto-probing is wanted at all, make it an explicit opt-in setting and record consent.
- **Fix side effects:** Restricting the sweep removes the current automatic escape hatch for gated videos — the user-facing "use cookies" hint must be shown instead (see F-WN-19-2).
- **Discovered by:** A

#### F-WN-19-4  [P1] — The 7-browser sweep runs inside the shared 10-worker pool and is unbounded → provider-wide starvation
- **File:** `services/youtube_service.py:840-859` (sweep), `services/youtube_service.py:195` (`self._executor = ThreadPoolExecutor(max_workers=10)`), `services/youtube_service.py:1069` (`self._executor.submit(_extract)`), `services/youtube_service.py:512` (`search`), `services/youtube_service.py:700/769` (album/playlist fetch)
- **Confirmed:** yes (code path); the wall-clock magnitude is a hypothesis
- **Description:** The browser sweep is executed **synchronously inside `_extract`**, i.e. on a worker of the same 10-thread pool that also serves `search()`, `get_stream_url()`, `get_album_tracks()`, `get_playlist_tracks()` and `_prefetch_top_tracks()`. Each sweep step constructs a *new* `YoutubeDL` (a fresh cookie-jar read + decrypt) and performs a full extraction with `socket_timeout: 8`, `retries: 1`, `extractor_retries: 1`. Seven of them in series can occupy a worker for a minute or more. yt-dlp runs **in-process** (no subprocess isolation), so the whole extraction cost is charged to that pool thread.
- **Cause:** The fallback chain is written as a sequential loop inside the single extraction task instead of being bounded (count and total deadline) or moved off the shared pool.
- **Trigger conditions:** Several concurrent plays/prefetches hitting the same anti-bot gate at the same time.
- **User impact:** The YouTube provider goes effectively silent: `search_sync` (`youtube_service.py:541`, 6 s wait) and `audio/engine.py:208` (`event.wait(timeout=10)`) both give up long before a sweep finishes, so the UI reports "nothing found"/times out and the SoundCloud fallback is entered for tracks that would have resolved.
- **Evidence:** `services/youtube_service.py:844-859`
  ```python
  for b_name in browsers_to_try:
      try:
          cookie_opts = opts.copy()
          cookie_opts["cookiesfrombrowser"] = (b_name,)
          with yt_dlp.YoutubeDL(cookie_opts) as ydl_cookie:     # new jar per browser
              res = ydl_cookie.extract_info(video_url, download=False)
  ```
  with `services/youtube_service.py:310-314` (`socket_timeout: 8`, `retries: 1`, `extractor_retries: 1`).
- **Reproduction / verification:** Stub `yt_dlp.YoutubeDL.extract_info` to raise `Exception("Sign in to confirm you're not a bot")` and sleep 8 s per call; submit 10 `get_stream_url()` calls and measure that the pool is blocked for the whole sweep chain, while a concurrent `search()` submitted afterwards does not start until a worker frees.
- **Suggested fix:** Cap the sweep (max 2–3 browsers) and give it an explicit deadline; run it on a separate, small executor so it cannot starve search/streaming.
- **Fix side effects:** A tighter sweep reduces the chance of finding a working browser; the cap must be paired with the actionable error message from F-WN-19-2.
- **Discovered by:** A

#### F-WN-19-5  [P2] — The sweep accepts the first browser that returns *any* info dict, even a non-playable one, and then stops
- **File:** `services/youtube_service.py:846-857`
- **Confirmed:** yes
- **Description:** Inside the sweep the result is accepted with a bare `if res:` — no `_has_playable_audio(res)` check, unlike the two anonymous fast paths at `youtube_service.py:785` and `:824`. The loop `return res` on the first non-empty dict, so a browser that answers with a *gated* payload (formats present, nothing playable) terminates the sweep and the remaining browsers are never tried.
- **Cause:** The playability guard was applied to the anonymous paths but omitted from the sweep path.
- **Trigger conditions:** The first browser in the list returns a non-empty but unplayable info dict (the exact shape the anti-bot gate produces).
- **User impact:** The user is told the track cannot be extracted even though a later browser in the list would have worked; the sweep's whole cost is paid for nothing.
- **Evidence:** `services/youtube_service.py:850-857`
  ```python
  res = ydl_cookie.extract_info(video_url, download=False)
  if res:                                   # <-- no _has_playable_audio(res)
      if self.settings and (configured_browser == "none" or not configured_browser):
          ...
      return res                            # <-- ends the sweep
  ```
  Compare `services/youtube_service.py:785`: `if info and _has_playable_audio(info):`.
- **Reproduction / verification:** Stub `extract_info` to return `{'id':'v','formats':[{'format_id':'sb0','url':'https://x','acodec':'none'}]}` for the first browser and a playable dict for the second; assert the function returns the first (unplayable) result and never touches the second browser.
- **Suggested fix:** Apply `_has_playable_audio(res)` in the sweep and only `return` on a playable result; keep iterating otherwise.
- **Fix side effects:** The sweep then runs all seven browsers in the worst case — combine with the deadline from F-WN-19-4.
- **Discovered by:** A

#### F-WN-19-6  [P2] — `_prefer_anonymous` is a one-way latch that disables cookies for the rest of the session (and for the proxy's cookie injection)
- **File:** `services/youtube_service.py:221` (init), `services/youtube_service.py:786-788`, `:825-827`, `:1127-1128` (set sites), `services/youtube_service.py:350-358` (consumer), `services/youtube_service.py:227-251` (`reset_ydl`), `core/proxy.py:990-995` (proxy consumer)
- **Confirmed:** yes
- **Description:** After a **single** successful anonymous extraction the flag `self._prefer_anonymous = True` is set and never cleared, because `reset_ydl()` — the only place that clears it — is never called anywhere in the repository. From then on `_get_ydl_opts()` stops emitting `cookiefile`/`cookiesfrombrowser`, so every later extraction for the whole process runs anonymously.
- **Cause:** A per-attempt optimisation ("public tracks need no profile") was implemented as a global, irreversible mode switch.
- **Trigger conditions:** The first successful anonymous extraction — i.e. essentially always, because the anonymous fast path is tried first whenever cookies are configured (`youtube_service.py:775-788`).
- **User impact:** (a) Age-restricted / private / members-only tracks can no longer be resolved through the normal path — they only survive via the F-WN-19-3 sweep; (b) `core/proxy.py:992` calls `youtube._get_ydl('high')` from the proxy's own per-connection thread; with the latch set, that instance has **no** cookie jar, so `_inject_ydl_cookies` injects nothing and the proxy cannot supply the cookies a restricted `googlevideo.com` URL needs.
- **Evidence:** `services/youtube_service.py:785-788`
  ```python
  if info and _has_playable_audio(info):
      with self._ydl_lock:
          self._prefer_anonymous = True
      return info
  ```
  `services/youtube_service.py:353-358`
  ```python
  if not anonymous and cookies_file_path and os.path.exists(cookies_file_path):
      opts["cookiefile"] = cookies_file_path
  configured_browser = self.settings.get("auth", "browser_cookies", "none")
  if not anonymous and configured_browser and configured_browser != "none":
      opts["cookiesfrombrowser"] = (configured_browser,)
  ```
  `grep -r "reset_ydl" --include=*.py` → only the definition at `youtube_service.py:227` (and the unrelated `soundcloud_service.py:231`).
- **Reproduction / verification:** Call `get_stream_url` once for a public video (anonymous path succeeds → latch set), then assert `svc._prefer_anonymous is True` and that `svc._get_ydl_opts('bestaudio/best')` no longer contains `cookiesfrombrowser`/`cookiefile` even though `auth.browser_cookies` is set to a real browser.
- **Suggested fix:** Make "anonymous" a per-attempt flag rather than a service-level mode, or reset the latch when an extraction actually fails with an auth-shaped error.
- **Fix side effects:** Dropping the latch restores the cookie-jar read cost on every extraction (the reason the flag exists) — a per-attempt "try anonymous first, then authenticated" order preserves the speed-up.
- **Discovered by:** A

#### F-WN-19-7  [P2] — `download_audio_sync` returns the downloaded file without the audio validation `_require_audio_file` exists to enforce; `overwrites=True` is silently reverted
- **File:** `services/youtube_service.py:1151-1176` (the four return paths), `services/youtube_service.py:142-163` (`_require_audio_file`), `services/youtube_service.py:1102-1108` (`overwrites` vs. `download_context`), `core/download_transfer.py:24-32` (`ydl_options`)
- **Confirmed:** yes
- **Description:** Only step 4 of the four "file found" paths calls `_require_audio_file`. Steps 1–3 return the file unchecked. In the **normal** download flow (`core/downloader.py:730` always installs a `DownloadContext`, and `core/download_transfer.py:27` overrides `outtmpl` to `download_<track>_<digest>_<id>.<ext>`) step 1 — `ydl.prepare_filename(info)` — is the path that matches, so the validation is effectively bypassed. In addition, `ydl_opts["overwrites"] = True` (with the explicit comment "A previous partial download of the same id must not be reused") is overwritten back to `False` by `download_context.ydl_options()`, so that intent does not hold either.
- **Cause:** `_require_audio_file` was added to the *scan* branch only, and the option merge order (`ydl_opts.update(download_context.ydl_options(...))` after the `overwrites` assignment) silently undoes an earlier decision.
- **Trigger conditions:** A leftover file with the exact target name that is empty, truncated, or not audio (the scenario `_require_audio_file`'s own docstring describes: "a 0-byte file when the write is cut short, or `sb0.mhtml` when it hits a consent/gate page").
- **User impact:** The track is marked `is_downloaded=1` and `download_complete` fires for a file with no audio in it — the exact failure the helper was written to prevent. The user sees the track in the library and it never plays.
- **Evidence:** `services/youtube_service.py:1151-1174`
  ```python
  downloaded_file = ydl.prepare_filename(info)
  if os.path.exists(downloaded_file):
      return downloaded_file            # <-- no _require_audio_file
  ...
  for fname in os.listdir(output_dir):
      if fname.startswith(prefix) and not fname.endswith('.part'):
          found = os.path.join(output_dir, fname)
          _require_audio_file(found)    # <-- the only validated path
          return found
  ```
  `services/youtube_service.py:1102-1108`
  ```python
  "overwrites": True,
  })
  if download_context:
      ydl_opts.update(download_context.ydl_options(output_dir))   # sets 'overwrites': False again
  ```
  `core/download_transfer.py:26-32` — `'overwrites': False, 'continuedl': True`.
- **Reproduction / verification:** Drive `download_audio_sync` with a stubbed `yt_dlp.YoutubeDL` whose `extract_info` returns an info dict and whose `prepare_filename` points at a 0-byte file; assert the function returns that path instead of raising "Файл повреждён (0 байт…)".
- **Suggested fix:** Apply `_require_audio_file` to every return path (or once, at the single place the file is returned), and decide the `overwrites`/`continuedl` policy in one place instead of letting `download_context` override it.
- **Fix side effects:** Validating the "already downloaded" path means a re-download of a previously truncated file will now fail loudly instead of silently succeeding — the caller (`core/downloader.py`) must then re-queue, which it already does for provider failures.
- **Discovered by:** A

#### F-WN-19-8  [P2] — The resolver's last-resort branch can return a video-only (silent) stream URL
- **File:** `services/youtube_service.py:1016-1022`
- **Confirmed:** code path confirmed; reachability is a hypothesis
- **Description:** When the selected format carries no `url` and no `requested_formats` exist, the resolver falls back to `info["formats"][-1].get("url")` **without filtering on `acodec`**. yt-dlp sorts `formats` best→worst, so `[-1]` is the *worst* format, which for YouTube is typically a video-only mp4 (e.g. `160`, 144p, `acodec='none'`). The returned URL would be served to the HTML5 `<audio>` element, which plays nothing.
- **Cause:** The fallback prefers "any URL" over "an audio URL"; the `acodec` filter that the branch above it uses (`services/youtube_service.py:1017`) is missing.
- **Trigger conditions:** A successful extraction whose selected format has no `url` (e.g. a format dict with `url: None`), while `info["formats"]` is non-empty.
- **User impact:** The player shows the track as playing with no sound and no error; the app's own `_has_playable_audio` guard would have caught this payload, but it is not applied on the main (non-anonymous) extraction path — see F-WN-19-1's cause.
- **Evidence:** `services/youtube_service.py:1016-1022`
  ```python
  if not stream_url and info.get("formats"):
      audio_fmts = [f for f in info["formats"] if f.get("acodec") != "none" and f.get("url")]
      if audio_fmts:
          audio_fmts.sort(key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True)
          stream_url = audio_fmts[0].get("url")
      elif len(info["formats"]) > 0:
          stream_url = info["formats"][-1].get("url")     # <-- no acodec filter
  ```
- **Reproduction / verification:** Feed `get_stream_url` a stubbed extraction returning `{'id':'v','url':None,'formats':[{'format_id':'251','acodec':'opus','url':'https://x/251'},{'format_id':'160','acodec':'none','vcodec':'h264','url':'https://x/160.mp4'}]}` and observe `stream_url == 'https://x/160.mp4'` (video-only) rather than the opus stream. Note `_has_playable_audio` correctly returns `False` for a video-only payload — the guard exists but is not consulted here.
- **Suggested fix:** Reject the branch when no format with `acodec != 'none'` exists; surface the gating/unsupported error instead of a silent video URL.
- **Fix side effects:** Videos that genuinely have no audio-only stream would now error instead of playing a muxed stream — an acceptable trade-off, but the message must say so.
- **Discovered by:** A

#### F-WN-19-9  [P2] — `m.youtube.com` links are rejected as an invalid YouTube target and get a different stream-cache key
- **File:** `services/youtube_service.py:83` (`_YT_HOSTS`), `services/youtube_service.py:86-98` (`_is_allowed_youtube_target`), `services/youtube_service.py:107-121` (`_yt_cache_key`)
- **Confirmed:** yes
- **Description:** `_YT_HOSTS` contains only `youtube.com`, `www.youtube.com`, `music.youtube.com`, `youtu.be`. The mobile host `m.youtube.com` (and `www.youtube-nocookie.com`) is absent, so a mobile share link is rejected outright by `get_stream_url` with "Недопустимый адрес YouTube" before yt-dlp is ever contacted. The same omission in `_yt_cache_key` means the same video addressed through `m.youtube.com` gets a *different* cache key from `www.youtube.com`.
- **Cause:** The allow-list was written without the mobile/embed hosts.
- **Trigger conditions:** The user pastes a `m.youtube.com` link (very common for links shared from the mobile app) into any YouTube flow — search result, playlist import, or a URL typed into the resolver.
- **User impact:** "Недопустимый адрес YouTube" for a perfectly valid YouTube link; and if the host is later added to the allow-list without adding it to the cache-key normalisation, the same track would be extracted twice and cached under two keys.
- **Evidence:** `services/youtube_service.py:83`
  ```python
  _YT_HOSTS = ("youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be")
  ```
  `services/youtube_service.py:98`
  ```python
  return parsed.scheme in ("http", "https") and (parsed.hostname or "") in _YT_HOSTS
  ```
- **Reproduction / verification:**
  ```
  _is_allowed_youtube_target('https://m.youtube.com/watch?v=dQw4w9WgXcQ') -> False
  _yt_cache_key('https://m.youtube.com/watch?v=dQw4w9WgXcQ')  -> 'youtube:https://m.youtube.com/watch?v=dQw4w9WgXcQ'
  _yt_cache_key('https://www.youtube.com/watch?v=dQw4w9WgXcQ') -> 'youtube:dQw4w9WgXcQ'
  ```
  (all other hosts in the list normalise to the bare 11-char id, so the cache key itself is otherwise stable and consistent — see §3.)
- **Suggested fix:** Add `m.youtube.com` / `music.youtube.com` mobile variants to `_YT_HOSTS` **and** to the `_yt_cache_key` normalisation, so the allow-list and the key stay in sync.
- **Fix side effects:** Widening the host allow-list is an SSRF-surface change — the list must stay restricted to YouTube-owned hosts (it is currently a strict equality check, which is correct).
- **Discovered by:** A

#### F-WN-19-10  [P2] — YouTube playlist/album listing has no pagination; `get_yt_playlist_tracks` can only ever return the first page
- **File:** `services/youtube_service.py:703-770` (`get_playlist_tracks`), `services/youtube_service.py:643-701` (`get_album_tracks`), `core/api.py:2545-2613` (`get_playlist_tracks` / `get_yt_playlist_tracks`)
- **Confirmed:** yes
- **Description:** `get_playlist_tracks` calls `self._ytmusic.get_playlist(playlist_id)` with ytmusicapi's default `limit=100` and **ignores the `continuation` token** the API returns for longer playlists. There is no offset/continuation parameter anywhere in the chain, so the bridge can only ever return the first `limit` (default 50) tracks. `get_album_tracks` is likewise a single `get_album(browse_id)` call.
- **Cause:** The `limit` argument was treated as a pagination mechanism, but it is only a truncation of a single page.
- **Trigger conditions:** Any YouTube playlist longer than `limit` tracks (the default path used by `ui/web_new_v2/js/home.js:386` passes `50`).
- **User impact:** The user imports/plays a 500-track YouTube playlist and silently gets 50 tracks with no indication that the rest exist — and there is no way to reach them from the UI. The bridge additionally caps the wait at `BRIDGE_SYNC_BUDGET = 6.0` (`core/api.py:67`), so a slow page yields "Таймаут получения треков плейлиста".
- **Evidence:** `services/youtube_service.py:711-713`
  ```python
  data = self._ytmusic.get_playlist(playlist_id)
  entries = data.get("tracks", []) if isinstance(data, dict) else []
  ```
  (`ytmusicapi` 1.12.3 `get_playlist(playlistId, limit=100, ...)` builds a `request_func_continuations` internally and returns a `continuation` key for longer playlists — the service discards it.)
  `core/api.py:2600` — `srv.get_playlist_tracks(playlist_id, limit=limit, callback=_on_success, error_callback=_on_error)`; there is no continuation parameter in the bridge signature `get_playlist_tracks(self, playlist_id, source="local", limit=50)`.
- **Reproduction / verification:** `inspect.getsource(YTMusic.get_playlist)` shows the internal continuation machinery and the `limit=100` default; the service passes neither `limit` nor the continuation. Assert `YouTubeService.get_playlist_tracks` returns ≤ `limit` entries for a playlist whose `trackCount` is larger, with no flag in the payload.
- **Suggested fix:** Either plumb a `continuation`/offset through `get_playlist_tracks` → `core/api.py` → the UI, or return an explicit `has_more`/`continuation` flag so the UI can say "showing 50 of 500".
- **Fix side effects:** Pagination inside the 6 s bridge budget needs its own timeout strategy (fetch continuation pages outside the synchronous bridge call).
- **Discovered by:** A

#### F-WN-19-11  [P3] — YouTube result dicts omit `source_url`, breaking the provider dict contract that `TrackResolver` consumes
- **File:** `services/youtube_service.py:490-498` (search), `:417-426`, `:442-454`, `:623-634`, `:681-689`, `:749-757` (other producers); `services/base_service.py:305-313`; `services/track_resolver.py:318-326`
- **Confirmed:** yes
- **Description:** Every other provider (and the base class's own `_parse_yt_entry`) emits a `source_url` field; the YouTube service emits `source`, `source_id`, `title`, `artist`, `duration`, `cover_url`, `album` only. `TrackResolver._search_youtube` copies `top.get('source_url', '')` → always `''` for YouTube hits.
- **Cause:** The YouTube service builds its result dicts by hand instead of reusing `BaseMusicService._parse_yt_entry` (which is dead code for this provider).
- **Trigger conditions:** Every YouTube search / related / album / playlist result.
- **User impact:** Currently contained — `audio/engine.py:204` and `core/app.py:320` rebuild the watch URL from `source_id`, `services/soundcloud_service.py:807` falls back to `source_id`, and `core/api.py` never passes `source_url=` to `db.add_track` for any provider — so the DB column is empty regardless. It is a latent contract break: any future code that trusts `source_url` for a YouTube row gets an empty string.
- **Evidence:** `services/youtube_service.py:490-498`
  ```python
  tracks.append({
      "source": "youtube",
      "source_id": source_id,
      "title": title,
      "artist": artist,
      "duration": duration,
      "cover_url": cover_url,
      "album": item.get("album", {}).get("name", "") if isinstance(item.get("album"), dict) else "",
  })                                       # <-- no "source_url"
  ```
  `services/base_service.py:305-313` — the base contract does include `'source_url': entry.get('url') or f'https://www.youtube.com/watch?v={source_id}'`.
- **Reproduction / verification:** `YouTubeService.search` result dicts contain no `source_url` key; `TrackResolver._search_youtube` therefore yields `'source_url': ''` for every YouTube resolution.
- **Suggested fix:** Add `"source_url": f"https://www.youtube.com/watch?v={source_id}"` to the YouTube producers (or route them through `_parse_yt_entry`).
- **Fix side effects:** None — it is additive, and `cover_url` (not `thumbnail`) is the field the UI actually reads (`ui/web_new_v2/js/search.js:419`), so the field naming itself is already correct for this app.
- **Discovered by:** A

#### F-WN-19-12  [P3] — `_detect_browser_cookies()` is dead code
- **File:** `services/youtube_service.py:35-57`
- **Confirmed:** yes
- **Description:** The module-level detector (probing firefox/chrome/edge/brave/opera and caching the winner in `_detected_working_browser`) is never called from anywhere in the repository. Only the *other*, live mechanism (the sweep in `_extract_info_safe`) actually reads browser cookies.
- **Cause:** It was superseded by the inline sweep but left in place; `tools/bench/profile.py:242` still refers to it in a comment ("`YouTubeService._detect_browser_cookies()` scrapes the *real* installed …"), which misleads anyone reading the bench harness.
- **Trigger conditions:** n/a (never invoked).
- **User impact:** None directly — but it makes the codebase look as if browser probing is a single, auditable, opt-in helper, whereas the live behaviour is the automatic sweep of F-WN-19-3.
- **Evidence:** `grep -r "_detect_browser_cookies\|_detected_working_browser\|_browser_detection_tried" --include=*.py` → only the definition block at `services/youtube_service.py:35-57`; `tools/bench/profile.py:242` mentions it in a comment only.
- **Suggested fix:** Delete the dead helper and its module globals, and correct the `tools/bench/profile.py` comment; keep the cookie-jar handling in one visible place.
- **Fix side effects:** None — nothing imports it.
- **Discovered by:** A

#### F-WN-19-13  [P3] — After the cookie-lock retry, the error text used for the gating decisions is stale
- **File:** `services/youtube_service.py:796-860`
- **Confirmed:** yes
- **Description:** `_extract_info_safe` computes `err_lower` from the *first* exception. When the cookie-lock branch (`youtube_service.py:800-810`) re-extracts without cookies and that retry fails, only `err_msg` is updated (`err_msg = str(e_clean)`) — `err_lower` keeps the original text. Every later decision that keys off `err_lower` (the anonymous-retry condition at `:811-813`, the browser-sweep trigger at `:832`) therefore tests the *first* error, and the function finally re-raises the **original** exception `raise e` (`:860`) instead of the more informative retry error.
- **Cause:** `err_lower` is not recomputed after the retry; the original exception is re-raised instead of the latest one.
- **Trigger conditions:** The browser cookie DB is locked (Firefox/Chrome running) **and** the cookie-free retry also fails — e.g. with a bot gate.
- **User impact:** The user is shown "Unable to open cookie database" instead of the actionable anti-bot message, and the anonymous/browser fallback that would have recovered is skipped.
- **Evidence:** `services/youtube_service.py:806-812, 860`
  ```python
  try:
      with yt_dlp.YoutubeDL(clean_opts) as ydl_clean:
          return ydl_clean.extract_info(video_url, download=False)
  except Exception as e_clean:
      err_msg = str(e_clean)          # err_lower NOT recomputed
  if (not anonymous_attempted
          and ('cookiesfrombrowser' in opts or 'cookiefile' in opts)
          and any(k in err_lower for k in _YT_GATING_MARKS)):   # stale err_lower
  ...
  raise e                              # original exception, not e_clean
  ```
- **Reproduction / verification:** Stub `extract_info` to raise `Exception("Unable to open cookie database")` on the cookie-bearing instance and `Exception("Sign in to confirm you're not a bot")` on the cookie-free one; assert the function raises the *database* message and that the anonymous-retry branch is skipped.
- **Suggested fix:** Recompute `err_lower` after the retry and raise the most recent exception.
- **Fix side effects:** The surfaced error becomes the retry's, which may be less familiar to the user — map it through `_yt_gating_error` (F-WN-19-2).
- **Discovered by:** A

#### F-WN-19-14  [P3] — Executor-submit failure leaks the pending-stream / pending-request bookkeeping
- **File:** `services/youtube_service.py:912-917` + `:1069` (pending streams), `services/youtube_service.py:388` + `:512` (pending searches)
- **Confirmed:** yes
- **Description:** `get_stream_url` registers the callback pair in `self._pending_streams[cache_key]` **before** `self._executor.submit(_extract)`, and `search()` registers in `self._pending_requests[cache_key]` (via `_join_request`) before `self._executor.submit(_search)`. If the submit raises (the pool is shut down by `core/app.py:575` during `cleanup()`), the entry is never popped: `finish()` is the only remover, and `finish()` only runs from inside the submitted task.
- **Cause:** The pending maps are updated before the hand-off, with no rollback on a failed hand-off.
- **Trigger conditions:** App shutdown while a YouTube search or stream resolution is in flight.
- **User impact:** After such a failure every subsequent request for the same cache key appends to a listener list that nobody will ever call — the caller's callback is silently never invoked. The bridge's 6 s timer eventually fires, so the UI degrades to "no results" instead of hanging.
- **Evidence:** `services/youtube_service.py:912-917` and `:1069`
  ```python
  with self._ydl_lock:
      if cache_key in self._pending_streams:
          self._pending_streams[cache_key].append((callback, error_callback))
          return None
      self._pending_streams[cache_key] = [(callback, error_callback)]
  ...
  self._executor.submit(_extract)      # <-- RuntimeError here leaves the entry behind
  ```
- **Reproduction / verification:** `svc._executor.shutdown()` then call `svc.get_stream_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ')`; assert `RuntimeError` propagates and `svc._pending_streams` still contains the key.
- **Suggested fix:** Wrap the submit in try/except and pop the pending entry (invoking `error_callback`) on failure; the same for `_join_request` in `search()`.
- **Fix side effects:** None — it only affects the shutdown path.
- **Discovered by:** A

#### F-WN-19-15  [P3] — The `quality` argument is a no-op: all four levels select the same format
- **File:** `services/youtube_service.py:260-266` (`quality_map`), `services/youtube_service.py:293-306` (`_get_ydl_opts`), `services/youtube_service.py:894` (`get_stream_url(..., quality="high")`), `core/app.py:296` + `:502` (`quality` plumbed from the caller)
- **Confirmed:** yes
- **Description:** `quality_map` maps `low`, `medium`, `high` and `lossless` all to `"bestaudio/best"`. The `quality` value therefore has no effect on the selected format, on the returned metadata, or on the cache key.
- **Cause:** The quality ladder was collapsed to a single selector.
- **Trigger conditions:** Any call with `quality="lossless"` (or `low`).
- **User impact:** None today — `audio.quality` is not exposed in the UI (only `optimization.blur_quality` / `glow_quality` exist in `ui/web_new_v2/js/settings.js`), so no user-visible promise is broken. It becomes a defect the moment a quality control is added, and the "lossless" name would be a lie.
- **Evidence:** `services/youtube_service.py:260-266`
  ```python
  quality_map = {
      "low": "bestaudio/best",
      "medium": "bestaudio/best",
      "high": "bestaudio/best",
      "lossless": "bestaudio/best",
  }
  fmt = quality_map.get(quality, "bestaudio/best")
  ```
- **Reproduction / verification:** `_get_ydl_opts` is called with `format_str` from `quality_map`; all four keys produce the identical selector string.
- **Suggested fix:** Either implement the ladder (e.g. `bestaudio[abr<=128]` … `bestaudio`) or remove the parameter so the API does not advertise a quality it does not honour.
- **Fix side effects:** Implementing a real ladder changes the cached stream URLs and could regress extraction on the videos that currently only resolve via the `best` fallback.
- **Discovered by:** A

#### F-WN-19-16  [P3] — `_YT_GATING_MARKS` matches bare substrings ("bot", "drm") and can mis-classify unrelated errors
- **File:** `services/youtube_service.py:64-72`, `services/youtube_service.py:75-79`
- **Confirmed:** yes (code); a concrete false positive in the wild is a hypothesis
- **Description:** The gate detector is a plain substring test over the whole exception text, and the list contains the bare tokens `"bot"` and `"drm"`. Any error whose text happens to contain those three letters is reported to the user as an anti-bot gate.
- **Cause:** Over-broad markers combined with substring matching instead of phrase matching.
- **Trigger conditions:** An unrelated yt-dlp error whose text contains "bot" (a title, a URL, a "robot"-style message) or "drm".
- **User impact:** A network or extractor error is presented as "YouTube не отдал аудиоформаты (anti-bot гейт…)" and the user is sent to SoundCloud for a track that was never gated.
- **Evidence:** `services/youtube_service.py:64-79`
  ```python
  _YT_GATING_MARKS = (
      "requested format is not available",
      "needs to be reloaded",
      "sign in to confirm",
      "confirm you're not a bot",
      "confirm you are not a bot",
      "bot",
      "drm",
  )

  def _yt_gating_error(exc):
      if any(m in str(exc).lower() for m in _YT_GATING_MARKS):
          return Exception(_YT_GATED_MSG)
      return exc
  ```
- **Reproduction / verification:** `_yt_gating_error(Exception("ERROR: unable to download robot video page"))` → returns `_YT_GATED_MSG` although the failure is a network error.
- **Suggested fix:** Drop the bare `"bot"`/`"drm"` entries (the two explicit "confirm you're not a bot" phrases already cover the anti-bot case) and match on phrases.
- **Fix side effects:** The real anti-bot message "Sign in to confirm you're not a bot" is still matched by `"sign in to confirm"` / `"confirm you're not a bot"`, so the gate detection survives the narrowing.
- **Discovered by:** A

### 3. Clean areas

- **Filename sanitisation (contract #8) — CLEAN for YouTube.** `download_audio_sync` derives the file name from the *source id*, not from user metadata: `clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))` (`services/youtube_service.py:1079-1081`), and the downloader path overrides `outtmpl` with `DownloadContext.stem = f'download_{safe_track_id}_{digest}'` (`core/download_transfer.py:18-20`, `core/download_transfer.py:27`) where `safe_track_id` is likewise `re.sub(r'[^a-zA-Z0-9_-]', '_', …)`. A title like `AC/DC` or `Foo: Bar` never reaches the filesystem, and no `< > : " / \ | ? *` can appear in a YouTube download file name. **Title-based collisions are also impossible**: the name is keyed on the video id / track id + sha256 digest, not on the title.
- **`_yt_cache_key` normalisation — CLEAN apart from F-WN-19-9.** Verified empirically: `https://www.youtube.com/watch?v=ID`, the bare `ID`, `https://youtu.be/ID`, `https://music.youtube.com/watch?v=ID` and `https://www.youtube.com/shorts/ID` all normalise to the single key `youtube:<11-char id>`; a `&list=` suffix is dropped. The `youtube:` prefix correctly namespaces the shared `BaseMusicService._stream_cache` (which is class-level and shared with every other provider). The key is deterministic and stable. The only thing that affects the result — the format selector — is constant, so omitting `quality` from the key is consistent with F-WN-19-15.
- **Format selection is audio-first.** `bestaudio/best` resolves to `bestaudio` first (yt-dlp filters `vcodec == 'none' and acodec != 'none'`, so a music video's *video* track is never chosen), and only falls back to a muxed format. Verified against the installed yt-dlp 2026.08.19 selector implementation (`YoutubeDL.py:2591-2641`). The storyboard formats (`sb0..sb3`) are excluded by yt-dlp's own `acodec != 'none'` clause, so a storyboard URL can never be selected.
- **`_has_playable_audio` — CLEAN.** It correctly rejects a storyboard-only payload and a video-only payload (both verified: `False`), and it is applied on both anonymous fast paths (`youtube_service.py:785`, `:824`).
- **`_require_audio_file` — CLEAN as an implementation.** It rejects a missing file, a `.part` leftover, a non-audio extension and a file below 4 KiB; the extension allow-list covers the audio containers yt-dlp can produce. The defect is in *where* it is called (F-WN-19-7), not in what it does.
- **Search result normalisation — CLEAN for this app.** The dicts carry `title`, `artist`, `duration`, `source`, `source_id`, `cover_url`, `album`. The UI reads exactly `t.cover_url`, `t.source_id`, `t.duration` (`ui/web_new_v2/js/search.js:419-421, 322, 326`) — so `cover_url` (not `thumbnail`) is the right key here, and `base_service._parse_yt_entry`'s shape is not the contract the frontend expects. The only real gap is the missing `source_url` (F-WN-19-11).
- **Search query handling — CLEAN.** The query is handed to `self._ytmusic.search(query, …)` as a JSON POST body (`ytmusicapi`), never to a shell; the `ytsearch1:` form is consumed in-process by yt-dlp's own search extractor, not by a subprocess. No injection surface. The result limit is `max_results` (default 20, `core/api.py` never raises it; `search_sync` uses 1–8), and the 5-minute/size-capped search cache is shared correctly.
- **Playlist/album fetching — CLEAN apart from the pagination gap (F-WN-19-10).** Deduplication by `videoId` is applied, `duration_seconds` parsing handles the int and the `mm:ss`/`hh:mm:ss` string forms, and the `limit` break is honoured. The cover selection in `get_playlist_tracks` picks the largest thumbnail by area rather than blindly taking the last one.
- **`get_related_tracks_sync` — CLEAN.** Bounded (`min(int(limit), 50)`, rejects a non-11-char seed), validates the `limit` argument against `TypeError/ValueError/OverflowError`, skips unavailable/unplayable entries, caps the returned list at `count`, caches under a distinct `yt_related:` key in the shared 5-minute search cache, and returns `[]` on any exception (`youtube_service.py:639-641`). Its caller runs it on a bounded worker pool with an 8 s deadline (`services/recommendation_service.py:388-399`).
- **Thread-local `YoutubeDL` instances — CLEAN.** One instance per thread (`youtube_service.py:219`, `:253-275`) avoids yt-dlp's documented non-thread-safe shared state, and the `threading.Lock` around `_prefer_anonymous` is never held across another acquisition of the same non-reentrant lock (no deadlock).
- **`download_audio_sync` error mapping — CLEAN.** This path *does* route through `_yt_gating_error` (`youtube_service.py:1134`, `:1139`) and raises the actionable `_YT_GATED_MSG` for a storyboard-only payload (`:1148-1149`); the "no file after download" case raises a clear message. `overwrites: True` and the `ext`-based fallbacks are sensible for the no-context path.
- **`_is_allowed_youtube_target` — CLEAN as an allow-list.** It uses an exact hostname equality check against a fixed YouTube host set (no substring/suffix matching), so `youtube.com.evil.com` is rejected; `ytsearch1:` is accepted only with a non-empty query; the 11-char id form is accepted. The only gap is the missing mobile host (F-WN-19-9).
- **Bridge integration `get_yt_playlist_tracks` — CLEAN as a wrapper.** `core/api.py:2611-2613` delegates to `get_playlist_tracks(source="youtube")`, which formats the tracks (`cover`/`cover_url` both set), bounds the wait at `BRIDGE_SYNC_BUDGET = 6.0`, and returns `{"success": bool, "tracks": [...]}` / `{"success": False, "error": …}`. In offline mode the call is intercepted (`core/api.py:492`, `:498-501`). The only defect is the missing pagination (F-WN-19-10); note that the identically-named `RecommendationService.get_yt_playlist_tracks` (`services/recommendation_service.py:878`) is a *different* method (Last.fm chart) and is not on this path.
- **yt-dlp is invoked in-process (not a subprocess)** — noted for the record: `yt_dlp.YoutubeDL(...).extract_info(...)` runs inside the service's worker threads. This is the correct choice for cookie reuse and is not by itself a defect, but it is why F-WN-19-4 (an unbounded in-thread sweep) starves the pool.

### 4. Coverage gaps

- **No live network verification.** The environment has no YouTube access from the audit session, so every "gated video" / "removed video" behaviour is derived from the installed yt-dlp 2026.08.19 source (`YoutubeDL.py` format selector, `extractor/youtube/_video.py` storyboard builder) and from exercising the pure helper functions and the format selector directly. The *frequency* with which the real service hits the anti-bot gate in this user's environment was not measured.
- **The browser cookie jars were not inspected.** I did not open or decrypt any real browser profile. The claim in F-WN-19-3 that the app materialises the *entire* cookie jar (all domains) rests on yt-dlp's `cookiesfrombrowser` semantics (it loads the whole profile jar and only filters by domain when sending), not on an observation of this app's runtime.
- **`ytmusicapi` network behaviour** (whether `get_playlist` actually returns a `continuation` token for the playlists in question, and how long a `get_playlist` call takes) was verified from the installed 1.12.3 source only, not against the live API. The 6 s bridge budget pressure in F-WN-19-10 is therefore a code-level observation, not a measured latency.
- **`core/proxy.py` is out of this area.** I traced `youtube._get_ydl('high')` into `core/proxy.py:990-995` / `:1068-1071` to establish the impact of F-WN-19-6, but the proxy's own per-connection `YoutubeDL`/cookie-jar lifecycle and its ThreadingHTTPServer thread model belong to WN-11 — not reported here.
- **The downloader's filename/stem policy** (`core/download_transfer.py`, `core/downloader.py`) was read only far enough to establish that the YouTube provider does not itself build a title-derived file name; the resume/overwrite policy conflict flagged in F-WN-19-7 is reported against `services/youtube_service.py:1102-1108` because the *ordering* of the option merge lives there.
- **The audio engine's 10 s wait and the `core/app.py` SoundCloud fallback cascade** were read to quantify user impact, not audited.
- **Cross-check note for Role B (not double-reported here):** `_get_ydl_opts` sets `nocheckcertificate: True` (`services/youtube_service.py:308`), which disables TLS certificate verification for every YouTube request and download. That is primarily a security property and is left to the Role B review of this area.
