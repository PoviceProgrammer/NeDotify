## SCENARIO WX-06 — Lyrics cascade (`js/lyrics.js` → `core/api.py::get_lyrics` → `services/lyrics_service.py` → `services/lyrics_lookup.py` → `services/lyrics_cache.py` → UI) — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| Path | Lines read |
|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–200 (whole) |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 (whole) |
| `ui/web_new_v2/js/lyrics.js` | 1–1262 (whole file) |
| `ui/web_new_v2/js/events.js` | 60–199, 330–429 |
| `ui/web_new_v2/js/main.js` | 535–604 |
| `ui/web_new_v2/js/player.js` | 755–799, 1630–1689, grep on `duration`/`normalizeDurationMs` |
| `ui/web_new_v2/js/utils.js` | 943–982, grep on `escapeHtml`/`renderIcons` |
| `ui/web_new_v2/js/feature-controls.js` | grep on `lyric` (no match) |
| `ui/web_new_v2/index.html` | grep on `lyric` (all 32 matches), lines 568–623, 2256–2269 |
| `core/api.py` | 1–60, 340–379, 400–523, 1190–1264, 1437–1506, 3180–3379 |
| `core/app.py` | 505–586 (cleanup), grep on `lyrics` |
| `core/settings.py` | grep on `lyric` |
| `core/offline.py` | 1–77 (whole) |
| `services/lyrics_service.py` | 1–327 (whole) |
| `services/lyrics_lookup.py` | 1–387 (whole) |
| `services/lyrics_cache.py` | 1–109 (whole) |
| `services/base_service.py` | 1–140 |
| `services/music_matching.py` | 1–80 |
| `utils/tag_parser.py` | 100–169 (`extract_embedded_lyrics`) |
| `audio/engine.py` | 70–139, 175–214 |
| `audio/queue.py` | grep on `current_track`/`duration` |
| `main.py` | 505–579 (shutdown path) |
| `docs/PLAYBACK_LYRICS_PERFORMANCE.md` | 1–51 (whole) |
| `tests/test_lyrics_performance.py` | 1–342 (whole) |
| `tests/test_build_and_brand.py` | grep on `lyrics` |
| `.venv_win/Lib/site-packages/webview/util.py` | 234–323 (`js_bridge_call` threading) |
| `.venv_win/Lib/site-packages/webview/platforms/edgechromium.py` | 105–144 (`evaluate_js`) |

**Callees traced into other areas (list)**

- `services/base_service.py` — `BaseMusicService`, `_SharedExecutor`, `normalize_proxy_url` (the contract the lyrics stack does **not** use → F-WX-06-3, ARCH-2/ARCH-4).
- `services/music_matching.py` — `title_metadata`, `similarity`, `artist_matches`, `normalize`, `BASE_FALLBACK_VERSIONS` (query identity; WN-18 owns it).
- `services/artist_identity.py` — `artist_aliases`, `canonical_artist` (key normalisation; WN-18).
- `utils/tag_parser.py::extract_embedded_lyrics` — the fourth lyrics source (WN-27 owns the module).
- `core/offline.py::is_offline` — offline gate (WN-15/WX-09).
- `core/settings.py` — `SettingsManager.get` (in-memory; no DB hit on the bridge thread).
- `audio/engine.py::_notify_track_changed` / `resolve_stream_url` — supplies `track.duration` (WN-17). This is what makes the duration-0 first lookup possible (see F-WX-06-6 note in §3).
- `utils/cache_manager.py` — `get_cache_size`, `clear_all` (WN-27) — does **not** know about `lyrics_cache.db` (F-WX-06-7).
- `main.py` — process exit path (WN-01) → F-WX-06-4.
- `webview.util.js_bridge_call` / `webview.platforms.edgechromium.evaluate_js` — pywebview 5.4 threading/eval semantics (third-party; read for the bridge-thread and XSS analysis).

**Cross-component defects and their owning area**

| Defect | Owning area |
|---|---|
| `AppApi.get_lyrics` cascade counter + `_emit` contract | WN-09 (bridge) — read here only as the cascade's entry point |
| `audio/engine.py` not filling `track.duration` before `track_changed` | WN-17 — surfaced here as a lyrics-side cost (F-WX-06-6 note) |
| `utils/tag_parser.py` mutagen parse | WN-27 |
| `translate_lyrics` chunk truncation → line misalignment | WN-22 owns the truncation; WN-32 owns the index alignment. Reported once here. |
| `CacheManager` not covering `lyrics_cache.db` | WN-27 owns `CacheManager`; the lyrics side owns the file's placement. Reported once here. |

---

### 2. Findings

#### F-WX-06-1  [P1] — Every track change silently discloses title/artist/album/duration to five third-party lyric providers, with no disclosure and no opt-out

- **File:** `ui/web_new_v2/js/lyrics.js:297-299` (auto-trigger), `ui/web_new_v2/js/lyrics.js:854` (bridge call), `services/lyrics_lookup.py:346-349` (fan-out), `services/lyrics_lookup.py:95, 122, 152, 177, 195` (the five outbound queries)
- **Confirmed:** yes
- **Description:** The lyrics cascade is fired **unconditionally on every track change**, whether or not the user ever opens the lyrics panel. The frontend calls `get_lyrics`, and the backend then queries LRCLIB, NetEase, QQ Music, Genius and Megalobiz with the track's **title**, **artist**, **duration** and — for LRCLIB only — the **album**. Nowhere in the UI, in `core/settings.py`, in `js/settings.js`, in `js/feature-controls.js` or in `index.html` is any of these five providers (or the fact that listening history is sent to them at all) mentioned, and there is no setting that disables the lookup. The only lyrics-related setting in the whole product is the `toggle_lyrics` **hotkey** and the per-track `lyrics_offset_*` entries in the `lyrics` settings category.
- **Cause:** The cascade was designed as a transparent background enrichment (see `docs/PLAYBACK_LYRICS_PERFORMANCE.md:19-25`) and the privacy dimension was never modelled: there is no `ProviderRegistry` with a disclosure surface, no `lyrics.enabled` setting, and no per-provider consent state. `services/lyrics_service.py` has no `settings.get('lyrics', ...)` read anywhere.
- **Trigger conditions:** Play any track. Nothing else is required — the panel never has to be opened.
- **User impact:** The user's listening history (title + artist + album + duration of every track played) is continuously disclosed to five unrelated third-party companies with no notice and no way to opt out. On a network whose egress policy blocks those hosts, the app still attempts the requests. It also means the app is not usable as-is in environments where such disclosure is not permitted.
- **Evidence:**
  ```js
  // ui/web_new_v2/js/lyrics.js:296-299
  // Listen to track/position events dispatched by events.js via custom events
  document.addEventListener('nedotify:track_changed', () => {
      loadCurrentTrackLyrics();
  });
  ```
  ```js
  // ui/web_new_v2/js/lyrics.js:854
  p = window.pywebview.api.get_lyrics(track.title, track.artist, durMs, track.file_path, track.album || '', activeLyricsRequestId);
  ```
  ```python
  # services/lyrics_lookup.py:346-349
  jobs = [(self.lrclib, forms[0]), (self.netease, forms[0]), (self.genius, forms[0])]
  jobs += [(self.lrclib, f) for f in forms[1:]]
  jobs += [(self.qqmusic, forms[0]), (self.megalobiz, forms[0])]
  jobs += [(self.netease, f) for f in forms[1:]]
  ```
  ```python
  # services/lyrics_lookup.py:88-93  (album leaves the process)
  params = {'artist_name': people, 'track_name': title}
  if form['duration'] and not form['fallback']:
      params['duration'] = round(form['duration'])
  if form['album']:
      params['album_name'] = form['album']
  ```
  Absence of disclosure/opt-out, verified by grep over the whole UI tree:
  `grep -rn "lrclib|LRCLIB|translate\.googleapis|privacy|конфиденц|приватн" ui/web_new_v2` → **no matches**;
  `grep -rn "lyric" ui/web_new_v2/js/settings*.js` → **no matches**;
  `grep -rn "lyric" ui/web_new_v2/js/feature-controls.js` → **no matches**;
  `grep -rn "lyric" core/settings.py` → only `"toggle_lyrics": "KeyL"` (hotkey).
- **Reproduction / verification:** Open the app, play a track, and watch the outbound traffic (or `~/.nedotify/logs/app.log` at DEBUG). Five hosts are contacted per lookup: `lrclib.net`, `music.163.com`, `c.y.qq.com` / `y.qq.com`, `genius.com`, `www.megalobiz.com` — see `services/lyrics_lookup.py:95, 122, 152, 177, 195`. Search the whole repo for a disclosure of those hosts in user-facing text: `grep -rn "lrclib" --include=*.html --include=*.js ui/` → no matches.
- **Suggested fix:** Add a `lyrics.enabled` setting (default **off**, or at least "on but only when the panel is opened"), read it in `LyricsLookup.get()` before the fan-out (the offline gate at `services/lyrics_lookup.py:74` is the natural place), and add a short disclosure of the provider list in Settings → Lyrics. Alternatively, make the automatic fetch conditional on the lyrics panel having been opened at least once.
- **Fix side effects:** Turning it off by default removes the karaoke lyrics for users who never open Settings — a visible feature regression. A "fetch only when the panel is opened" mode breaks the design intent in `docs/PLAYBACK_LYRICS_PERFORMANCE.md:23` (plain text published immediately, upgraded to karaoke later) because the refinement would then have to wait for the panel. A provider disclosure also has to be translated and placed in a discoverable spot.
- **Discovered by:** B

#### F-WX-06-2  [P2] — The translation path ships the whole song text to Google Translate and occupies a bridge thread for up to 60 s with no deadline and no cancellation

- **File:** `core/api.py:3286-3291`, `services/lyrics_service.py:243-272`, `ui/web_new_v2/js/lyrics.js:57-88`
- **Confirmed:** yes
- **Description:** `AppApi.get_lyrics_translation` calls `LyricsService.translate_lyrics` **synchronously** on the pywebview bridge thread. `translate_lyrics` chunks the lyrics into pieces of ≤1500 characters (max 10) and issues one `GET` per chunk to `https://translate.googleapis.com/translate_a/single?...&q=<chunk>`. The **entire cleaned song text** — not the title, not the artist, the lyrics themselves — is therefore transmitted to Google. Each chunk has its own `HTTP_TIMEOUT = 6.0`, so the worst case is **10 × 6 s = 60 s** of bridge-thread occupancy for a single call.
- **Cause:** The translation path was written as a straight synchronous bridge call with no shared deadline (the lyrics lookup path has `LyricsLookup.BUDGET = 8.0`, the translation path has none) and no use of the shared lyrics thread pool (`services/lyrics_service.py:87`).
- **Trigger conditions:** The user clicks the 🌐 translation button on a song whose lyrics exceed ~15 000 characters, or on a network where `translate.googleapis.com` is slow/unreachable.
- **User impact:** (a) The **complete song text is sent to a fourth-party service** (Google) that the product never mentions, on top of the five lyric providers of F-WX-06-1 — a much larger payload than the metadata those providers receive. (b) The pywebview bridge thread is blocked for up to a minute; pywebview spawns **one thread per API call** (`.venv_win/Lib/site-packages/webview/util.py:308`), so repeated clicks multiply blocked threads. The WebView UI thread is *not* blocked (verified: pywebview 5.4 `js_bridge_call` runs `_call` on a fresh `Thread`), so the window does not freeze — but the promise stays pending for up to a minute and the stale-response guard at `ui/web_new_v2/js/lyrics.js:64` is the only thing keeping an old song's translation off the new song's sheet.
- **Evidence:**
  ```python
  # core/api.py:3286-3291
  def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
      """Get translation for lyrics text."""
      try:
          return self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
      except Exception as e:
          return {"error": str(e)}
  ```
  ```python
  # services/lyrics_service.py:261-269
  out = []
  try:
      for ch in chunks:
          url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(ch)}"
          req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
          with self._open_url(req, timeout=HTTP_TIMEOUT) as resp:
  ```
  ```python
  # services/lyrics_service.py:28
  HTTP_TIMEOUT = 6.0
  ```
  ```js
  // ui/web_new_v2/js/lyrics.js:63
  window.pywebview.api.get_lyrics_translation(cleanText, 'ru').then(res => {
  ```
- **Reproduction / verification:** Call the bridge directly with a 20 000-character string and time it against a blackholed `translate.googleapis.com`: the call returns after ~60 s (10 chunks × 6 s timeout). The 60 s figure is derived from the code (`services/lyrics_service.py:248-260` caps at 10 chunks, line 266 uses `HTTP_TIMEOUT`); it was **not** measured against the live endpoint (see §4).
- **Suggested fix:** Move the translation onto the shared lyrics pool with an explicit deadline (reuse `LyricsLookup.BUDGET` semantics), cap the payload, and disclose Google Translate as a lyrics processor in the same place the other providers are disclosed (F-WX-06-1).
- **Fix side effects:** Moving it off the bridge thread changes the bridge method's contract (it currently returns the translated text synchronously); the frontend already handles a promise, so the JS side needs no change, but the bridge method must keep returning the string. A payload cap means very long songs get a partial translation (see F-WX-06-5 for the alignment hazard that creates).
- **Discovered by:** B

#### F-WX-06-3  [P2] — The lyrics provider stack bypasses the app's proxy setting (a second, parallel provider contract)

- **File:** `services/lyrics_service.py:236-241`, `services/lyrics_lookup.py:73-84`; contrast `services/youtube_service.py:210, 236, 359`, `services/soundcloud_service.py:165, 256, 285`, `services/spotify_service.py:107`
- **Confirmed:** yes
- **Description:** `LyricsService` does **not** derive from `BaseMusicService`. Its HTTP path is `urllib.request.urlopen(req, timeout=..., context=ssl_ctx)` with no proxy handling at all, so the `auth.proxy_url` setting is never consulted. Every other network provider in the product normalises that setting through `services/base_service.py::normalize_proxy_url` and passes it to `requests`. The five lyrics providers therefore bypass the user's configured egress route.
- **Cause:** The lyrics stack was built as a self-contained service with its own executor, its own cache and its own HTTP helper, instead of reusing `BaseMusicService` (`services/lyrics_service.py:31-88` is a near-copy of `services/base_service.py:65-118`). The app-level proxy policy is implemented in `BaseMusicService`/`normalize_proxy_url` and has no other entry point.
- **Trigger conditions:** The user sets `auth.proxy_url` (the field the Settings UI exposes) and plays a track. Search and streaming go through the proxy; lyrics do not.
- **User impact:** On a network that only permits egress through the configured proxy, lyrics never load while everything else works. The failure is reported as *"Не удалось загрузить текст: источники временно недоступны"* (`ui/web_new_v2/js/lyrics.js:931`, `status === 'unavailable'`), which points the user at the lyric providers rather than at their own proxy setting. In the opposite direction, the user's proxy is bypassed for five hosts, which can break a "all traffic through the corporate proxy" policy.
- **Evidence:**
  ```python
  # services/lyrics_service.py:236-241
  def _open_url(self, req_or_url, headers=None, timeout=3.5):
      if isinstance(req_or_url, str):
          req = urllib.request.Request(req_or_url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
      else:
          req = req_or_url
      return urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
  ```
  ```python
  # services/youtube_service.py:210 (the contract the lyrics stack does not follow)
  proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", "")) if self.settings else ""
  ```
  ```
  $ grep -rn "proxy_url|proxies=|normalize_proxy_url" services/*.py
  services/base_service.py:25   services/spotify_service.py:12,107   services/soundcloud_service.py:12,165,256,285
  services/youtube_service.py:15,210,236,359
  # -> no occurrence in lyrics_service.py / lyrics_lookup.py
  ```
- **Reproduction / verification:** Set `auth.proxy_url` to a local port that only accepts CONNECT for the provider hosts (or block the provider hosts directly and route everything else through the proxy), then play a track: `get_lyrics` returns `status='unavailable'` while `AppApi.search` still succeeds. Alternatively, instrument `services/lyrics_service.py::_open_url` and assert that no `ProxyHandler`/`proxies=` is ever installed.
- **Suggested fix:** Route the lyrics HTTP calls through the same proxy policy — either make `LyricsService` a `BaseMusicService` subclass, or inject the normalised proxy into `LyricsService._open_url` via an `urllib.request.ProxyHandler` built from `settings.get('auth','proxy_url','')`.
- **Fix side effects:** `urllib`'s `ProxyHandler` is process-global if installed with `urllib.request.install_opener`; a per-call opener must be used instead, or the global default would also change the behaviour of unrelated `urllib` users (the proxy self-heal in `core/proxy.py` uses its own stack). A proxy that cannot reach the lyric hosts would then make lyrics fail where they previously succeeded by accident — that is the correct behaviour but it is a visible change.
- **Discovered by:** B

#### F-WX-06-4  [P2] — `AppCore.cleanup()` never releases the lyrics thread pool, so an in-flight lyrics read delays the app's exit by up to the socket timeout

- **File:** `core/app.py:562-586` (the pool shutdown list), `services/lyrics_service.py:87-88, 192-195`, `main.py:573-579`
- **Confirmed:** yes
- **Description:** `AppCore.cleanup()` shuts down the `base_service`, downloader, cache, youtube, soundcloud, yandex, spotify and recommendation pools under the explicit comment *"shutdown(wait=False) all thread pools so app exit never blocks"*. The **lyrics pool is missing from that list**. `LyricsService.shutdown_executor()` exists (`services/lyrics_service.py:192-195`) but is **never called from anywhere** in the product (only `BaseMusicService.shutdown_executor` is called, from `core/app.py:565`). The lyrics pool is stopped solely by an `atexit` hook (`services/lyrics_service.py:88`), and `concurrent.futures.ThreadPoolExecutor` worker threads are joined by `threading._register_atexit(_python_exit)` — **before** `atexit` callbacks run. So a lyrics HTTP read that is in flight at exit is joined with no timeout and the process waits for it.
- **Cause:** The lyrics pool was introduced as a module-level singleton (`services/lyrics_service.py:87`) that `AppCore.cleanup()` does not know about, and the "never blocks" contract of `cleanup()` was not extended to it.
- **Trigger conditions:** The user closes the app (or the startup watchdog restarts it) while a lyrics lookup is in flight — i.e. within ~8 s of a track change, which is the normal case because the cascade fires on every track change (F-WX-06-1).
- **User impact:** The app's process lingers after the window is gone (up to the 6 s `HTTP_TIMEOUT`, and unbounded with a slow-drip host — see F-WX-06-5). `main.py:574` releases the single-instance mutex *before* `app_core.cleanup()`, so a relaunch can overlap the dying process. The user sees the app "not closing" for several seconds.
- **Evidence:**
  ```python
  # core/app.py:562-580
  # O-15: shutdown(wait=False) all thread pools so app exit never blocks
  def _shutdown_shared_pool():
      from services.base_service import BaseMusicService
      shutdown = getattr(BaseMusicService, "shutdown_executor", None)
      ...
  _step("base_service pool", _shutdown_shared_pool)
  for _pool in (
      getattr(self, "downloader", None) and getattr(self.downloader, "_pool", None),
      getattr(self, "cache", None) and getattr(self.cache, "_executor", None),
      getattr(self, "youtube", None) and getattr(self.youtube, "_executor", None),
      getattr(self, "_soundcloud", None) and getattr(self._soundcloud, "_executor", None),
      getattr(self, "_yandex", None) and getattr(self._yandex, "_executor", None),
      getattr(self, "spotify", None) and getattr(self.spotify, "_executor", None),
      getattr(getattr(self, '_recommendations', None), '_candidate_executor', None),
  ):
  ```
  → no `self.lyrics` / lyrics pool.
  ```python
  # services/lyrics_service.py:87-88
  _lyrics_pool = _LyricsSharedExecutor(max_workers=6, thread_name_prefix="LyricsPool")
  atexit.register(_lyrics_pool.shutdown, wait=False, cancel_futures=True)
  ```
  ```
  $ grep -rn "shutdown_executor" --include=*.py .
  core/app.py:565      -> BaseMusicService.shutdown_executor   (the only live call)
  services/lyrics_service.py:193 -> LyricsService.shutdown_executor  (never called)
  ```
  Interpreter-exit join behaviour, measured:
  ```
  $ & ".venv_win\Scripts\python.exe" -c "import concurrent.futures, time; p=concurrent.futures.ThreadPoolExecutor(max_workers=2); p.submit(time.sleep,5); time.sleep(0.2)"
  elapsed_s=5.14
  ```
- **Reproduction / verification:** Start a lyrics lookup (play a track with no cached lyrics), then close the app within the 8 s budget window and measure the time between "window gone" and "process gone" — expect up to ~6 s. To make it deterministic, point `HTTP_TIMEOUT` at a blackholed host, or hold a provider connection open.
- **Suggested fix:** Add `LyricsService.shutdown_executor()` to the `_step(...)` list in `AppCore.cleanup()` (and/or give `LyricsService` an instance-level `stop()`), so `shutdown(wait=False, cancel_futures=True)` runs before the interpreter joins the workers. Cancelling a *running* future is not possible with `ThreadPoolExecutor`, so this bounds the damage only for queued work; closing the socket would need a per-request timeout that is actually enforced (F-WX-06-5).
- **Fix side effects:** Shutting the pool down early makes any lyrics request that is still queued return `unavailable` instead of a result — acceptable during shutdown. Because `shutdown_executor` sets `_shutdown = True` permanently on the module-level singleton, a restart inside the same process (the watchdog path calls `cleanup()` then spawns a child process, so this is not hit today) would break lyrics for the remainder of the process lifetime.
- **Discovered by:** B

#### F-WX-06-5  [P3] — No wall-clock cap on provider response bodies: a slow-drip host can pin the shared six-worker lyrics pool

- **File:** `services/lyrics_lookup.py:73-84`, `services/lyrics_service.py:236-241`, `services/lyrics_service.py:87`
- **Confirmed:** the missing wall-clock cap is **confirmed**; the exploitability is a **hypothesis**
- **Description:** `LyricsLookup._read` opens the response with `timeout=min(6.0, remaining)` and then calls `response.read(2 * 1024 * 1024)`. In CPython, `urlopen(timeout=…)` sets the **socket** timeout, and `HTTPResponse.read(n)` applies it per `recv()` — not to the total read. A host that emits one byte every 5 s keeps the read alive indefinitely. The 8 s `LyricsLookup.BUDGET` bounds only the *caller's* wait (`concurrent.futures.wait(..., timeout=...)` in the `while` loop at `services/lyrics_lookup.py:358-359`); the worker thread stays blocked inside the read.
- **Cause:** There is no total-transfer deadline — the code has a per-socket timeout and a global lookup budget, but nothing that caps the wall clock of one HTTP body.
- **Trigger conditions:** One of the five provider hosts (or a TLS-terminating middlebox) trickles the response instead of sending it. The lyrics pool has `max_workers=6`; the cascade submits up to 9 jobs per lookup.
- **User impact:** Six stuck workers starve the pool: a later lookup's jobs never start, `submit` returns futures that never run, and the lookup ends at the 8 s budget with `status='unavailable'` — lyrics break for the rest of the session even though the network is fine. The stuck workers also delay the app's exit (F-WX-06-4).
- **Evidence:**
  ```python
  # services/lyrics_lookup.py:73-84
  def _read(self, url, deadline, headers=None):
      if is_offline(self.service.settings):
          raise ConnectionError('Включён офлайн-режим')
      remaining = deadline - time.monotonic()
      if remaining <= 0:
          raise TimeoutError('Lyrics deadline exceeded')
      req = urllib.request.Request(url, headers=headers or {'User-Agent': 'NeDotify/1.0'})
      with self.service._open_url(req, timeout=min(6.0, remaining)) as response:
          return response.read(2 * 1024 * 1024).decode('utf-8', errors='replace')
  ```
  ```python
  # services/lyrics_service.py:87
  _lyrics_pool = _LyricsSharedExecutor(max_workers=6, thread_name_prefix="LyricsPool")
  ```
- **Reproduction / verification:** **Missing evidence:** I could not exercise this against the live providers (no live traffic was generated in this audit — see §4). What *is* confirmed by reading the code is that no total-read deadline exists. To confirm the impact, serve a response that sends 1 byte every 5 s from a local HTTP server, point `services.lyrics_lookup.LyricsLookup._read` at it, and observe that `response.read()` does not return after 6 s (the socket timeout only fires when no byte arrives within the window). Then submit six such lookups and confirm the seventh never reaches a provider.
- **Suggested fix:** Enforce a wall-clock cap on the body read — read in bounded chunks against `time.monotonic()` and abort when the deadline passes, and/or cap the number of bytes actually consumed (2 MiB is already the cap, but a slow trickle still holds the worker). A per-host total deadline (not just a socket timeout) is the robust fix.
- **Fix side effects:** Chunked reads with a wall-clock check add a per-chunk `time.monotonic()` call (negligible) and change the failure mode from "hang" to "TimeoutError" — the latter already maps to `unavailable` via the `except Exception: failed = True` path at `services/lyrics_lookup.py:362-364`, so the user-visible behaviour is an existing, handled state. A tighter cap could truncate a legitimately large Genius/Megalobiz HTML page (currently up to 2 MiB) and turn a hit into a miss.
- **Discovered by:** B

#### F-WX-06-6  [P3] — `translate_lyrics` silently truncates at ten chunks; the frontend aligns by index, so every line after the cut is mistranslated

- **File:** `services/lyrics_service.py:248-260`, `ui/web_new_v2/js/lyrics.js:65-80`
- **Confirmed:** yes
- **Description:** `translate_lyrics` breaks out of the chunk loop with `if len(chunks) >= 10: break`, dropping the remainder of the text without any signal to the caller. The frontend then aligns the returned translation to the original **by index**: `keys.forEach((k, i) => { if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i]; ... })`. A truncated translation therefore shifts every subsequent line onto the previous line's translation.
- **Cause:** The chunk cap is a guard against the URL length limit, but the truncation is not propagated (`translate_lyrics` returns a plain string, and the "partial" case is indistinguishable from a complete translation). The frontend's alignment is positional, not content-anchored.
- **Trigger conditions:** Lyrics longer than ~15 000 characters (the cap is 10 chunks × 1500 chars). Rare for a normal song, reachable for a long narrative/medley lyric sheet.
- **User impact:** From the truncation point onward, every line shows the **previous** line's translation — plausible-looking but wrong text, with no error shown.
- **Evidence:**
  ```python
  # services/lyrics_service.py:248-260
  chunks = []
  text = str(lyrics)
  while text:
      if len(text) <= 1500:
          chunks.append(text)
          break
      cut = text.rfind("\n", 0, 1500)
      if cut <= 0:
          cut = 1500
      chunks.append(text[:cut])
      text = text[cut:].lstrip("\n")
      if len(chunks) >= 10:
          break
  ```
  ```js
  // ui/web_new_v2/js/lyrics.js:71-75
  const keys = parsedLyrics.length > 0 ? parsedLyrics.map(l => l.text) : origLines;
  keys.forEach((k, i) => {
      if (k && transLines[i] && transLines[i] !== k) map[k] = transLines[i];
      else if (k && origLines[i] && transLines[i]) map[origLines[i]] = transLines[i];
  });
  ```
- **Reproduction / verification:** Feed `translate_lyrics` a 20 000-character lyric sheet (10 chunks of 1500 + a remainder) with the network stubbed; the returned string is ~15 000 characters and ends mid-line. Feed that string to the frontend's alignment loop and observe that `map[origLines[i]] === transLines[i-1]` for every line after the cut.
- **Suggested fix:** Have `translate_lyrics` report truncation (return a `{text, truncated}` object or raise/flag), and have the frontend stop aligning past the truncation point (or align by content rather than index). A safer alternative is to translate line-by-line in batches so a dropped tail cannot shift the rest.
- **Fix side effects:** Changing the return type of `translate_lyrics` breaks `AppApi.get_lyrics_translation`'s current "returns a plain string" contract, which the frontend branches on (`typeof res === 'string'` at `ui/web_new_v2/js/lyrics.js:65`) — both sides have to change together. Line-by-line translation multiplies the number of HTTP requests (a 60-line song → 60 requests) unless batched, which trades this P3 for the latency problem of F-WX-06-2.
- **Discovered by:** B

#### F-WX-06-7  [P3] — The lyrics disk cache (up to 96 MiB) is invisible to the storage/quota UI and is never reclaimed by the cache cleaner

- **File:** `core/app.py:132-133`, `services/lyrics_cache.py:20-22`, `utils/cache_manager.py:42-57, 78-95, 152-157`
- **Confirmed:** yes
- **Description:** The lyrics cache lives in `~/.nedotify/lyrics_cache.db`, next to the library database. `CacheManager` — the component that computes "storage used" and that the Settings → Storage screen and the cache-cleaner button drive — only knows the `covers`, `streams` and `temp` directories. `lyrics_cache.db` is in neither the size scan nor `clear_all()`. Its own limits (`MAX_ENTRIES = 20_000`, `MAX_PAYLOAD_BYTES = 96 MiB`, `MAX_FILE_BYTES = 128 MiB`) bound it, but nothing in the product reports or reclaims it.
- **Cause:** The cache was added next to the DB rather than inside `CacheManager`'s directory model; `CacheManager` has no notion of "cache files" outside its three directories.
- **Trigger conditions:** Any user who plays enough distinct tracks for the cache to grow (a few thousand songs is enough to reach tens of MiB).
- **User impact:** The storage/quota figure shown to the user under-reports the real footprint by up to ~96 MiB + the WAL file, and the "clear cache" button does not reclaim it — the user has no in-product way to remove it (contract #3: `~/.nedotify/` is the user's library and must not be cleared implicitly).
- **Evidence:**
  ```python
  # core/app.py:132-133
  self.lyrics = LyricsService(self.settings, cache_path=os.path.join(
      os.path.dirname(os.path.abspath(self.db.db_path)), 'lyrics_cache.db'))
  ```
  ```python
  # services/lyrics_cache.py:20-22
  MAX_ENTRIES = 20_000
  MAX_PAYLOAD_BYTES = 96 * 1024 * 1024
  MAX_FILE_BYTES = 128 * 1024 * 1024
  ```
  ```python
  # utils/cache_manager.py:86-87
  cache_dirs = [self._covers_dir, self._streams_dir, self._temp_dir]
  ```
  ```
  $ grep -n "lyrics" utils/cache_manager.py   ->  no matches
  ```
- **Reproduction / verification:** Play several hundred tracks with distinct lyrics, then compare `CacheManager.get_cache_size_mb()` (Settings → Storage) with the on-disk size of `~/.nedotify/lyrics_cache.db*`. The latter is excluded from the former. `tests/test_lyrics_performance.py:262-281` pins the cache's own bounds but not its visibility.
- **Suggested fix:** Either extend `CacheManager` with a "cache files" concept that includes `lyrics_cache.db` (size + a purge entry point), or move the lyrics cache under one of the managed cache directories so the existing accounting and cleanup pick it up.
- **Fix side effects:** Moving the file changes the cache's location, so an existing cache would be orphaned (a one-off re-download of the lyrics, not a data loss — the cache is expendable by design, `services/lyrics_cache.py:3-4`). Adding it to `clear_all()` would make the cache-cleaner button delete 96 MiB of lyrics data that the user did not ask about — it should be a separate, labelled entry.
- **Discovered by:** B

---

### 3. Clean areas

**XSS / injection — the lyrics body is never HTML-parsed. This is the single most important clean result of the cascade.**

The provider-controlled text reaches the DOM only through `textContent`:

- `ui/web_new_v2/js/lyrics.js:953` — `origSpan.textContent = line.text;` (synced line)
- `ui/web_new_v2/js/lyrics.js:959` — `subEl.textContent = currentTranslationMap[line.text];` (synced translation)
- `ui/web_new_v2/js/lyrics.js:1009` — `el.textContent = line;` (plain line)
- `ui/web_new_v2/js/lyrics.js:1013` — `subEl.textContent = currentTranslationMap[line];` (plain translation)
- `ui/web_new_v2/js/lyrics.js:1236-1241` — the floating karaoke widget uses `textContent` for `currentLine`, `nextLine` and `translation`.

Every `innerHTML` assignment in `lyrics.js` (lines 781, 813, 907, 933, 946, 996, 1002) writes a **compile-time constant** or a message drawn from a closed set of three literals (`ui/web_new_v2/js/lyrics.js:931`, `:1001`); `normalizedData.match_type` is constrained to `'exact' | 'base'` by the producer (`services/lyrics_lookup.py:70`) and re-validated on the disk-cache read path (`services/lyrics_cache.py:42`, `:53-56`), so it cannot carry an injected value into `warnEl.innerHTML` at line 1002.

**Python → JS event channel is injection-safe.** `AppApi._emit` (`core/api.py:1131-1136`) embeds the payload with `json.dumps(...)` (default `ensure_ascii=True`), which produces a valid, fully-escaped JavaScript string literal — including `\u2028`/`\u2029` and `\u0000` (the `track_key` in the payload contains a NUL). The script is executed with `ExecuteScriptAsync` (`.venv_win/Lib/site-packages/webview/platforms/edgechromium.py:126`), which evaluates JavaScript and never parses HTML. No `</script>`-style breakout is possible on this path.

**SSRF is guarded.** All provider URLs are hard-coded hosts (`services/lyrics_lookup.py:95, 122, 152, 177, 195`). The one URL taken from a provider response — the Genius page — is hostname-allowlisted before the fetch (`services/lyrics_lookup.py:185-186`: `if urllib.parse.urlparse(url).hostname not in ('genius.com', 'www.genius.com'): continue`). The Megalobiz link is constrained by a regex to a `/lrc/maker/…` relative path (`services/lyrics_lookup.py:196`).

**Query construction is escaped.** Every provider parameter goes through `urllib.parse.urlencode` / `urllib.parse.quote` (`services/lyrics_lookup.py:88-95, 120, 150, 176, 194`) — no raw string interpolation of the title/artist into a URL. The local file path is **never** sent to a provider: `file_path` is used only for the cache key and the embedded-tag lookup (`services/lyrics_lookup.py:241-253, 320-326`).

**Request coalescing exists and works.** `LyricsLookup.get()` implements a proper single-flight: the first caller becomes the *owner* of a flight, later callers for the same identity join it as listeners and wait on `flight['event']` (`services/lyrics_lookup.py:259-283`). Verified empirically — two concurrent identical lookups produced **1** provider invocation and both callers got `status='found'` (probe §1). The frontend has a matching guard (`ui/web_new_v2/js/lyrics.js:791-793`, 15 s window) so reopening the lyrics panel mid-search does not restart the work.

**Latency is bounded by a single global deadline, not by N × timeout.** `LyricsLookup.BUDGET = 8.0` is a wall-clock deadline passed into every provider (`services/lyrics_lookup.py:284, 305, 343-345`), and each provider's reads are clamped by `min(6.0, remaining)` (`services/lyrics_lookup.py:80`). The five providers run concurrently on the shared 6-worker pool. So the worst case for the cascade is ~8 s, not 5 × 6 s. A verified exact plain hit short-circuits the remaining providers (`services/lyrics_lookup.py:366-369`; pinned by `tests/test_lyrics_performance.py:148-162`).

**The bridge call never blocks the UI.** `AppApi.get_lyrics` starts a dedicated `Lyrics-N` thread and returns `{'status': 'loading', ...}` immediately (`core/api.py:3208-3225`); pywebview itself runs every JS→Python API call on its own thread (`.venv_win/Lib/site-packages/webview/util.py:305-309`). The disk-cache read happens on the `Lyrics-N` thread, **not** on the bridge thread (`core/api.py:3224` → `services/lyrics_lookup.py:309`). Switching tracks therefore does not stall the UI.

**Disk cache design is sound.** The key is `sha256(json([SCHEMA_VERSION, key]))` → a 64-hex digest, so the identity is filesystem-safe and the local file path never lands on disk in clear text (contract #8); verified: `identity is hex-sha256: True`. TTL is 30 days for verified synced/instrumental results and 1 day for plain ones (`services/lyrics_lookup.py:219-223`). **Negative results are never persisted** — `_remember` writes to disk only for `status == 'found'` (`services/lyrics_lookup.py:234-235`); verified: a `not_found` lookup left the disk row count unchanged (probe §3). An `unavailable` result is not cached at all (`services/lyrics_lookup.py:226-227`). Writes go through a single SQLite transaction in WAL mode → atomic; four threads writing the same key concurrently produced **one** valid row and no exception (probe §5). A corrupt cache file is treated as a miss, not a failure (`services/lyrics_cache.py:72-74`); verified: the lookup returned `not_found` with no exception (probe §4). The memory cache is LRU-bounded at 2048 entries and the frontend cache at 40 (`services/lyrics_lookup.py:26, 232-233`; `ui/web_new_v2/js/lyrics.js:22-23`).

**The "no lyrics" vs "provider failure" distinction is modelled.** The backend distinguishes `found` / `not_found` / `unavailable` (`services/lyrics_lookup.py:374`), and the frontend renders three different messages (`ui/web_new_v2/js/lyrics.js:931`: *"Текст песни не найден"* vs *"Не удалось загрузить текст: источники временно недоступны"* vs *"Инструментальная версия — без текста"*). An outage is therefore **not** reported as "this song has no lyrics" — the exact defect the Android port was found to have (`docs/audits/ANDROID_FINDINGS_REGISTER.md`, P2-66). Cancelled lookups are also excluded from the negative cache (`services/lyrics_lookup.py:226-227`; `tests/test_lyrics_performance.py:284-289`).

**No listener/timer leak per track change.** `initLyrics()` is called exactly once (`ui/web_new_v2/js/main.js:542`), so the `nedotify:track_changed` / `nedotify:position_changed` / `nedotify:lyrics_ready` document listeners are bound once. The kinetic sheet state is cached on the DOM node (`ui/web_new_v2/js/lyrics.js:399-424`), so the wheel/pointer listeners are bound once per sheet, not per track. The per-line click handlers are attached to nodes that `renderLyrics` replaces wholesale (`ui/web_new_v2/js/lyrics.js:946, 979`), so they die with the old nodes. `followResumeTimer` and `kineticResizeObserver` are single module-level singletons, guarded and reused (`ui/web_new_v2/js/lyrics.js:358-360, 674-678, 696-698`). The position hot path is deliberately allocation-free: a binary search plus zero layout work when the line index has not changed (`ui/web_new_v2/js/lyrics.js:1068-1129`).

**The lyrics cache is separate from the user's library** (contract #3): it is its own `lyrics_cache.db` next to the storage DB, and a cache failure is always a miss, never a playback failure (`services/lyrics_cache.py:1-4`).

---

### 4. Coverage gaps

- **No live provider traffic.** I did not contact LRCLIB, NetEase, QQ Music, Genius, Megalobiz or Google Translate. The real-world latency, the providers' current behaviour and the actual bytes they receive were not observed. The 8 s budget, the 60 s translation worst case and the 2 MiB body cap are derived from the code.
- **F-WX-06-5 (slow-drip) is not confirmed end-to-end.** The missing wall-clock cap on `response.read()` is confirmed by reading `services/lyrics_lookup.py:73-84` and by CPython's socket-timeout semantics, but I did not run a trickling HTTP server against the real code path, and I did not measure the pool starvation.
- **The frontend was analysed statically.** There is no headless harness in this environment for `ui/web_new_v2/js/lyrics.js`, so the JS half of the duration-refinement behaviour was reasoned from the source, not executed. The backend half (duration 0 vs 120000 ms producing two separate flights and two provider invocations) **was** executed (probe §2).
- **`services/lyrics_service.py`'s `_fetch_*` family (`_fetch_lrclib`, `_fetch_netease`, `_fetch_qqmusic`, `_fetch_genius`, `_fetch_megalobiz`, `_fetch_duckduckgo`, lines 300-327) is a parallel provider surface** that the production path never calls (only `tests/test_lyrics_netease.py` uses it). I did not audit those six methods' behaviour beyond noting that they are dead in production — see ARCH-1.
- **`utils/tag_parser.py` was only read at the `extract_embedded_lyrics` boundary** (lines 121-142). The mutagen parse cost on the lookup thread was not measured; WN-27 owns that module.
- **The `discord_rpc` / tray / session side effects of a lyrics lookup** were not traced; they are outside this cascade.
- **The Android subtree was excluded** by instruction, so the desktop cascade was not compared with the Android port's cascade, even though `docs/audits/ANDROID_FINDINGS_REGISTER.md` discusses the same five providers.
- **`core/api.py`'s `_offline_bridge_result` interception was checked** (line 502: `get_lyrics_translation` returns `None` in offline mode; `get_lyrics` is not intercepted and is gated inside `LyricsLookup`), but the interaction of the offline mode with the disk cache (cached lyrics still resolve offline) was not exercised.

---

### 5. Architecture improvements (ARCH)

**ARCH-1 — The provider list is a hard-coded literal in the lookup, and a second provider surface exists in the service.**
`services/lyrics_lookup.py:346-349` builds the fan-out from four inline list expressions inside `get()`, and `services/lyrics_service.py:300-327` carries a *parallel* family of `_fetch_<provider>` wrappers over `_compat_lookup` that the production path never calls (only `tests/test_lyrics_netease.py` does). There is no registry, no shared `Provider` protocol and no single place where a provider is declared. Consequence: adding a provider means editing the literal, writing a method with the `(form, deadline, offer)` signature, and — if the new provider needs a "candidate" pass — mirroring `accept()` semantics; the duplicate `_fetch_*` family makes it easy to change one surface and not the other. A `LyricsProvider` protocol plus a `PROVIDERS` tuple (`(name, callable, priority)`) that both the fan-out and any future disclosure/telemetry iterate over would remove the duplication and give F-WX-06-1 a natural place to hang a per-provider consent flag.

**ARCH-2 — `LyricsService` is a fork of `BaseMusicService` rather than a user of it.**
`services/lyrics_service.py:31-88` is a near-verbatim copy of `services/base_service.py:65-118` (`_LyricsSharedExecutor` vs `_SharedExecutor`), and `LyricsService.submit` (`:187-190`) mirrors `BaseMusicService.submit`. The consequence is visible in F-WX-06-3 (the proxy policy lives only in `BaseMusicService`) and in F-WX-06-4 (the pool lives only in `lyrics_service`, so `cleanup()` misses it). The lyrics memory cache also becomes a second, independent LRU that the product's other cache accounting cannot see or purge.

**ARCH-3 — `LyricsLookup` reaches into `LyricsService`'s private state instead of receiving a store.**
`services/lyrics_lookup.py:31-32`: `self.service._cache = collections.OrderedDict()` and `self.service._inflight = {}`. The lookup module therefore *replaces* the cache that `LyricsService.__init__` just created (`services/lyrics_service.py:182`) and owns its lifetime, while the lock that guards both lives on the service (`_cache_lock`). The locking itself is correct — `_inflight` joins the existing `_cache_lock` exactly as the repo's "a new shared field joins its class's existing lock" rule requires — but the *ownership* is inverted. A `LyricsStore` object (memory LRU + disk cache + inflight registry) constructed by `LyricsService` and passed into `LyricsLookup` would make the data flow explicit and would let the cache be sized/purged from one place.

**ARCH-4 — The lyrics stack has its own HTTP layer with no shared policy.**
`LyricsService._open_url` (`services/lyrics_service.py:236-241`) is a thin `urllib` wrapper with a hard-coded User-Agent per call site (`{'User-Agent': 'Mozilla/5.0'}` for translation, `{'User-Agent': 'NeDotify/1.0'}` for the providers), no proxy policy, no per-host rate limit, and no retry/backoff. The rest of the product uses `requests` through `BaseMusicService`. A shared HTTP policy object (proxy + UA + per-host throttle + total-read deadline) would fix F-WX-06-3 and F-WX-06-5 together and would give the five lyric hosts one place to be rate-limited — today a user who skips through 50 tracks in 5 minutes can emit 50 × 5 provider requests with no throttle anywhere in the stack.

**ARCH-5 — Three overlapping caches with three different identities.**
The frontend keeps `lyricsMemoryCache` keyed by `lyricsTrackKey` = `JSON.stringify([source, source_id, title, artist, album, local path])` (`ui/web_new_v2/js/lyrics.js:26-32`); the backend memory cache and the disk cache are keyed by `lyrics_lookup.py:257-258` = `(normalised title, canonical artists, version, normalised album, duration, file path, mtime)`. The two identities disagree on **duration** and **version**. The consequence is visible in the cascade: the frontend's key is stable across a duration refinement (so the frontend believes it has the lyrics) while the backend's key changes (so it re-queries), and the frontend's cache can hold a plain-text result under a key that the backend would consider a different song. A single identity — ideally the backend's, returned with the payload and used as the frontend cache key — would remove the mismatch.

**ARCH-6 — The provider fan-out is not observable.**
Nothing records which provider answered, how long the cascade took, or how many provider jobs were launched; the only trace is `logger.debug('Lyrics source %s unavailable: %s', ...)` in the unused `_compat_lookup` (`services/lyrics_service.py:307`). The result carries a `source` field (`services/lyrics_lookup.py:70`), but there is no aggregate timing. With an automatic, every-track lookup (F-WX-06-1), the absence of any measurement of "how many third-party requests does this session make" is what makes the privacy and rate-limit exposure invisible to the maintainers.
