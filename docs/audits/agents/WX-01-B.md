## SCENARIO WX-01 — Track resolution → proxy → frontend playback — ROLE B

> Scope: Windows desktop only. `android/` was not opened.
> Path audited: `AppApi.play_track` (`core/api.py:1437`) → `AppApi._resolve_track` (`core/api.py:1608`)
> → `AppCore.re_resolve_stream_url_async` (`core/app.py:296`) / `StreamResolver.resolve` (`core/resolver.py:165`)
> → `AudioEngine.resolve_stream_url` (`audio/engine.py:121`) → provider services
> → `LocalProxyManager.get_proxy_url` (`core/proxy.py:1304`) → `StreamProxyHandler.do_GET` (`core/proxy.py:694`)
> → `ui/web_new_v2/js/player.js` `loadAudioSource` (`ui/web_new_v2/js/player.js:105`).

---

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

| File | Lines read | Why |
|---|---|---|
| `docs/audits/WIN_AUDIT_CONTEXT.md` | 1–201 | common brief |
| `docs/audits/WIN_AUDIT_AREAS.md` | 1–70 | WX table |
| `core/api.py` | 1–209, 342–421, 1100–1274, 1398–1405, 1437–1745, 2040–2099, 2650–2719 | bridge surface of the play path, SSRF guard, `_emit`, `get_proxy_info` |
| `core/proxy.py` | 1–1334 (whole file) | the proxy: auth, SSRF, caching, HLS rewrite, URL builders |
| `core/resolver.py` | 1–271 (whole file) | mem/DB cache, single-flight, negative cache |
| `core/app.py` | 290–539 | `re_resolve_stream_url_async`, the 5 s auto-cache timer, worker thread |
| `core/playback_recovery.py` | 1–183 (whole file) | the stream-expiry recovery leg of the play path |
| `audio/engine.py` | 1–200 | `_notify_track_changed` (proxy URL builder), `resolve_stream_url` |
| `utils/stream_urls.py` | 1–26 | `stream_url_expired` |
| `utils/url_safety.py` | 1–37 | `is_safe_media_url` |
| `utils/cache_manager.py` | 130–400 | `download_audio_stream`, `purge_stream_cache`, stream-cache naming |
| `ui/web_new_v2/js/player.js` | 1–220, 420–539, 690–869, 1620–1749 | `loadAudioSource`, `playTrack`, `onTrackChanged`, HLS lifecycle |
| `ui/web_new_v2/js/main.js` | 20–99 | `PROXY_PORT` / `PROXY_TOKEN` bootstrap, `window.NeDotify` surface |
| `ui/web_new_v2/js/events.js` | 80–139 | `track_changed` routing |
| `ui/web_new_v2/js/search.js` | 810–856 | playlist play entry point |
| `ui/web_new_v2/js/library.js` | 230–289 | library "play all" entry point |
| `services/youtube_service.py` | 86–125, 894–973 | target allow-list, provider single-flight |
| `services/soundcloud_service.py` | 569–638 | provider single-flight, URL handling |
| `services/yandex_service.py` | 160–269 | provider single-flight (**absent**) |
| `services/base_service.py` | 125–275 (grep) | `_join_request`, `_cache_lock` |
| `core/offline.py` | 1–77 | offline interception on the path |
| `core/settings.py` | grep (`auto_cache_streams`) | default of the auto-cache flag |
| `ui/web_new_v2/index.html` | 1–2314 (grep) | CSP (`script-src 'self'`, `media-src`, `connect-src`) |
| `main.py` | grep (logging setup) | log level = INFO; request-line masking is DEBUG |
| `tests/test_proxy_harness.py`, `tests/test_proxy_security.py`, `tests/test_hls_playback.py`, `tests/test_recommendation_ui.py` | whole files | to avoid re-reporting already-pinned behaviour |

**Callees traced into other areas**

* `services/youtube_service.py` / `services/soundcloud_service.py` / `services/yandex_service.py` — provider
  single-flight and target allow-lists (WN-19/WN-20/WN-21). Only the entry points needed for this scenario.
* `core/database.py` — `get_cached_stream` / `cache_stream` / `set_cached_file` (WN-12). Only the call contract.
* `utils/cache_manager.py` — `download_audio_stream` / `purge_stream_cache` (WN-27).
* `core/settings.py` — `auto_cache_streams` default (WN-14).
* `core/listening.py` — `ListeningSession` (WN-02), touched only to confirm a second `play_track` does not
  create a second listening session.

**Reproduction artefact** (outside the repo, allowed by the ground rules):
`%TEMP%\opencode\audit_reports\_wx01b_probe.py` — a read-only probe that drives the *real* `AppApi`,
`AudioEngine` and `LocalProxyManager` with a stub DB and counts resolution requests, and compares the
proxy-URL shapes. Output is quoted verbatim in the findings.

---

### 2. Contract-point table (how many components must agree for one track to play)

| # | Contract point | Single owner? | Defined at | Consumed at |
|---|---|---|---|---|
| 1 | Loopback base URL `http://127.0.0.1:<port>` | yes (proxy) | `core/proxy.py:1276` | `audio/engine.py:97,102,115`; `core/api.py:2069`; `js/player.js:100`; `js/utils.js:628`; `js/profile.js:127` |
| 2 | Token parameter name `k` (legacy alias `auth_token`) | yes (proxy) | `core/proxy.py:31` (`AUTH_PARAM`), `:507-511` | `core/proxy.py:1300-1302`; `js/player.js:99`; `js/utils.js:627`; `js/profile.js:126` |
| 3 | Token minting + entropy + hand-off to the WebView | yes (proxy → bridge → JS global) | `core/proxy.py:1275`; `core/api.py:1398-1405` | `js/main.js:34-57` → `window.PROXY_TOKEN` |
| 4 | Endpoint set `/`, `/api/cover`, `/api/avatar`, `/api/stream` | yes (proxy) | `core/proxy.py:40` (`KNOWN_PROXY_PATHS`) | all 5 JS/Python URL builders |
| 5 | Query vocabulary `url`, `source`, `source_id`, `track_id`, `title`, `artist` | proxy parses (`core/proxy.py:734-739, 864-868`), **5 producers** | — | see #6 |
| 6 | **Which URL shape** (`/?url=<upstream>` vs `/api/stream?track_id=`) | **NO — 5 divergent producers** | `core/proxy.py:1307`; `audio/engine.py:95`; `core/api.py:1218`; `core/api.py:2061`; `core/playback_recovery.py:181` | `js/player.js:119-122` (HLS detection reads `?url=`) |
| 7 | Track-payload field names (`stream_url`, `file_path`, `source`, `source_id`, `duration`, `listening_session`, `loudness_lufs`) | split across engine + api | `audio/engine.py:78-119`; `core/api.py:1195-1240` | `js/player.js:1625-1709`; `js/events.js:97-100` |
| 8 | Event name `track_changed` | yes (api) | `core/api.py:1240` | `js/events.js:97` |
| 9 | "stream not resolved yet" signal = *absence* of `stream_url` **and** `file_path` | implicit, nowhere documented | — | `js/player.js:1695-1705` |
| 10 | Expiry semantics of a stream URL | yes | `utils/stream_urls.py:7-26` | `core/resolver.py:127`; `core/api.py:1521,1644`; `core/playback_recovery.py:168` |
| 11 | Credential scoping (which provider's cookies may go to which host) | yes (proxy) | `core/proxy.py:60-99` | `core/proxy.py:984-1006, 1063-1078` |
| 12 | "the upstream URL is never exposed to the frontend" | **NO — comment only** | `audio/engine.py:89` (comment) | violated by `audio/engine.py:97` and `core/proxy.py:1316` |

**Components that must agree for one track to play:** `core/api.py` (bridge + payload shape) →
`core/app.py` (resolution orchestration) → `core/resolver.py` (cache) → provider service (URL) →
`audio/engine.py` (proxy URL) **or** `core/proxy.py::get_proxy_url` (proxy URL — a *second* builder) →
`core/proxy.py` (auth + fetch + cache) → `js/player.js` (source assignment + HLS detection) →
`js/events.js` (event routing). **Eight modules, twelve contract points, no single owner for #6, #7 and #12.**

---

### 3. Findings

#### F-WX-01-1  [P1] — Every played track is downloaded twice: the proxy's inline stream cache and `cache.download_audio_stream` write the same file concurrently

- **File:** `core/proxy.py:1174-1222` (proxy inline cache), `core/app.py:361-374` (5 s timer), `utils/cache_manager.py:289-394` (yt-dlp download), `core/settings.py:147` (flag default)
- **Confirmed:** yes
- **Description:** On every successful resolution the backend schedules a *second*, independent download of the
  same track, five seconds later, into the same directory, under (almost) the same file name — while the proxy
  is already downloading the very same bytes into that file.
- **Cause:** Two independent cache-fill mechanisms exist for the same artefact.
  The proxy streams the upstream body to the browser **and** to a temp file, then atomically publishes it:
  `core/proxy.py:1187-1208`
  ```python
  final_path = os.path.join(
      streams_dir,
      f"{cache_name}{_ext_for_response(resp)}",
  )
  ...
  os.replace(temp_path, final_path)
  self.server.app_core.db.set_cached_file(source, source_id, final_path)
  ```
  Independently, `core/app.py:361-374` fires 5 s after the resolution:
  ```python
  if self.settings and self.settings.get("storage", "auto_cache_streams", False):
      def delayed_download():
          ...
          self.cache.download_audio_stream(source, source_id, stream_url)
      _t = threading.Timer(5.0, delayed_download)
  ```
  `auto_cache_streams` defaults to **True** (`core/settings.py:147`), and `download_audio_stream` starts with
  `self.purge_stream_cache()` then a full yt-dlp download to the *same* target name
  (`utils/cache_manager.py:293-294`, `:315-317`):
  ```python
  safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(source_id))
  download_id = f"{source}_{safe_id}"
  ...
  out_template = os.path.join(self._streams_dir, f"{download_id}.%(ext)s")
  ```
  The downloader's own "already cached?" guard (`utils/cache_manager.py:306-313`) only sees
  `stream_cache.cached_file_path`, which the proxy sets **after** the whole body has been received — i.e.
  typically *after* the 5-second timer has already fired. So the guard does not fire and the download runs.
- **Trigger conditions:** any cold play of an online track (the 5 s timer only fires while the track is still
  `engine.queue.current_track`, `core/app.py:366-369`). A 3-minute track takes far longer than 5 s to stream,
  so the two downloads overlap.
- **User impact:** 2× the network traffic and 2× the CPU for every track played (matters on metered/slow
  links); the two writers race on the same path — the proxy's `os.replace` can hit a Windows sharing violation
  (the file is open by yt-dlp), which the code already anticipates at `core/proxy.py:1209-1222`
  (`Could not replace stream file %s (locked)`) and then the cache entry is silently lost, so the *next* play
  downloads everything again. If the two writers pick different container extensions (the proxy derives it from
  the upstream `Content-Type`, `core/proxy.py:303-313`; yt-dlp from the extracted format) the track ends up as
  **two** files in `~/.nedotify/streams/`, one of them orphaned but still counted against the cache quota.
- **Evidence:** quoted above. Probe output confirming the shared base name:
  `proxy.py=/?url= ... ` (see F-WX-01-5) and `download_id = f"{source}_{safe_id}"` vs the proxy's
  `cache_name = f"{safe_source}_{safe_source_id}"` (`core/proxy.py:803-805`).
- **Reproduction / verification:** play any YouTube/SoundCloud track that is not yet in `~/.nedotify/streams/`
  and watch `~/.nedotify/streams/` during the first 30 s: a `{source}_{id}.*` file appears from the proxy and a
  yt-dlp process starts on the same base name 5 s later. `~/.nedotify/logs/app.log` shows
  `Stream cached successfully to ...` (proxy) *and* `Successfully cached {source}/{source_id} to ...`
  (cache manager) for the same track. Alternatively, patch `core/app.py:369` to log and count calls.
- **Suggested fix:** pick one owner for the stream cache. Either drop the proxy's inline cache write and let
  `download_audio_stream` do it, or make `download_audio_stream` a no-op when the proxy has already published
  the file (the proxy already knows the path). At minimum, make `download_audio_stream` wait for / observe the
  proxy's in-flight publication instead of starting a second download 5 s later.
- **Fix side effects:** removing the inline proxy cache means a partially-played track is not cached (the
  current behaviour caches partial bodies only when `Content-Length` matches). Removing the timer means the
  cache is only filled by full plays.
- **Discovered by:** B

---

#### F-WX-01-2  [P2] — The primary play path never goes through `StreamResolver`: its single-flight and its negative cache are dead on the play path

- **File:** `core/app.py:296-506` (`re_resolve_stream_url_async`), `core/resolver.py:165-230` (`resolve`), `core/resolver.py:79-99` (`_failed` / `is_unavailable`), `audio/engine.py:136-151`
- **Confirmed:** yes
- **Description:** `StreamResolver` is the project's designated cache + single-flight layer, but the code path
  that actually resolves a track for playback calls the provider service directly and only *writes* to the
  resolver afterwards.
- **Cause:** `AppApi.play_track` / `_resolve_track` call `self._core.re_resolve_stream_url_async(...)`
  (`core/api.py:1604`, `:1744`). That method's worker goes straight to the provider:
  `core/app.py:499-502`
  ```python
  service.get_stream_url(url, callback=_on_resolved, error_callback=_on_err, quality=quality)
  ```
  and touches the resolver only *after* the network call, to publish the result:
  `core/app.py:352-354`
  ```python
  # Refresh resolver caches so subsequent requests reuse the fresh URL
  self.resolver.refresh(source, source_id, stream_url)
  ```
  The only caller of `StreamResolver.resolve()` — the method that owns the single-flight, the in-memory TTL
  cache and the `_failed` negative cache — is the **proxy** path:
  `audio/engine.py:136-149`
  ```python
  resolver = getattr(self.app_core, "resolver", None) if self.app_core else None
  if resolver is not None:
      cached = resolver.get_cached_url(source, source_id)
      ...
      return resolver.resolve(source, source_id, _network)
  ```
  Consequently `StreamResolver._failed` / `is_unavailable` (`core/resolver.py:79-99`) protect only requests that
  arrive through the proxy, never a user-initiated play.
- **Trigger conditions:** every click on an online track whose URL is not yet in the DB cache; and every
  re-click on a track the provider has already declared unplayable (DRM, deleted, private).
- **User impact:** a dead track is re-extracted through the full provider cascade on every single attempt —
  the `_FAIL_TTL = 120` negative cache and its comment ("a DRM-protected or deleted track keeps the same
  answer for good") never apply to the path the user actually drives. The single-flight that
  `core/resolver.py:8` advertises ("concurrent requests for the same (source, source_id) share one background
  resolution") does not apply either — see F-WX-01-3.
- **Evidence:** quoted above. Note also that `re_resolve_stream_url_async` never consults
  `resolver.get_cached_url()` before hitting the network, so the resolver's 1-hour in-memory TTL
  (`_MEM_TTL = 3600.0`, `core/resolver.py:20`) short-circuits nothing on the play path.
- **Reproduction / verification:** play a DRM-protected SoundCloud track, let it fail, then click it again
  within 120 s: the provider is asked again (visible in `~/.nedotify/logs/app.log` as a second extraction),
  and `StreamResolver.is_unavailable(source, source_id)` still returns `False` because `mark_unavailable`
  was never called on this path. Instrument `core/app.py:502` with a counter.
- **Suggested fix:** route `re_resolve_stream_url_async` through `StreamResolver.resolve()` (or make it call
  `resolver.resolve` when a provider cascade is needed) so the play path inherits the single-flight, the TTL
  cache and the negative cache; keep `resolver.refresh()` for the "we already have a URL" case.
- **Fix side effects:** `resolve()` blocks up to `_RESOLVE_TIMEOUT = 12.0` s and returns `None` on timeout;
  the current code has no such bound on the play path, so a behaviour change on timeout handling is possible.
  `resolver.resolve()` also persists to the DB, which `re_resolve_stream_url_async` already does via `refresh`.
- **Discovered by:** B

---

#### F-WX-01-3  [P2] — The frontend re-enters `play_track` while the backend is already resolving the same track, producing a second concurrent resolution request

- **File:** `ui/web_new_v2/js/player.js:1687-1709`, `core/api.py:1606`, `core/api.py:1583-1604`
- **Confirmed:** yes (the double request is confirmed; the *network* duplication is provider-dependent)
- **Description:** One user click produces **two** resolution requests for the same `(source, source_id)`.
- **Cause:** the backend's "queue" branch of `play_track` starts the resolution and *simultaneously* publishes
  a `track_changed` event whose payload has **no** `stream_url` (the engine could not build one, because the
  track has no `file_path` yet — `audio/engine.py:84-118`). The frontend treats "no `stream_url` and no
  `file_path`" as "the backend has not resolved this yet, ask it to":
  `ui/web_new_v2/js/player.js:1695-1705`
  ```js
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
  That `play_track` call has **no** `track_list`, so it takes the other branch —
  `core/api.py:1606` `self._resolve_track(track, ...)` — which runs the *whole* cache ladder again and then
  issues a **second** `re_resolve_stream_url_async` for the same track
  (`core/api.py:1744`). The backend has no de-duplication at this level (F-WX-01-2), and the frontend's
  `_pendingResolveKey` guard only suppresses the *third* and later calls.
- **Trigger conditions:** every cold play of an online track (i.e. whenever the DB stream cache has no fresh
  URL for it). Warm plays are unaffected, because `play_track` then finds the cached URL and publishes it in
  the first `track_changed`.
- **User impact:** one extra bridge round trip, one extra resolver worker, one extra DB write
  (`resolver.refresh`) and one extra `track_changed` event per click. For YouTube and SoundCloud the
  *network* cost is absorbed by the provider-level single-flight
  (`services/youtube_service.py:912-917`, `services/base_service.py:140-151`), but
  **`services/yandex_service.py:160-253` has no single-flight**: it checks the cache and then unconditionally
  `self._executor.submit(_extract)` (`:252`), so a Yandex track performs **two** full
  `client.tracks([id])` + `get_download_info()` extractions per click, doubling the API quota consumption.
- **Evidence:** quoted above. Probe output (real `AppApi` + real `AudioEngine`, stub DB):
  ```
  after api.play_track(track, [track], 0) -> [('youtube', 'dQw4w9WgXcQ')]
  track_changed payload: stream_url=None file_path=None source='youtube' source_id='dQw4w9WgXcQ'
  player.js fallback branch (play_track again) fires? True
  total provider resolutions for ONE click -> 2 [('youtube','dQw4w9WgXcQ'), ('youtube','dQw4w9WgXcQ')]
  ```
- **Reproduction / verification:** run the probe (`%TEMP%\opencode\audit_reports\_wx01b_probe.py`), or set a
  breakpoint on `core/app.py:502` and click one cold Yandex track: `get_stream_url` is entered twice with the
  same `raw_id`.
- **Suggested fix:** either (a) publish a distinct "resolving" signal from the backend (e.g. `stream_url:
  null` **plus** `resolving: true`) so the frontend does not have to infer it from the absence of two fields, or
  (b) make the backend de-duplicate: `_resolve_track` should consult the in-flight resolution started by the
  queue branch instead of starting its own. Contract point #9 in the table above needs an explicit owner.
- **Fix side effects:** changing the `track_changed` payload shape touches `js/player.js:1690` (the
  `_loadedSourceUrl` comparison) and `js/lyrics.js:27` (which already special-cases "stream URLs can arrive
  after `track_changed`").
- **Discovered by:** B

---

#### F-WX-01-4  [P2] — `playback_recovery` stamps the *original* source/source_id onto the resolver cache and the proxy URL, even when the recovered stream belongs to a different provider

- **File:** `core/playback_recovery.py:163-165`, `:177-181`; `core/proxy.py:1304-1316`, `:91-99`, `:983-1006`, `:1024-1052`
- **Confirmed:** yes
- **Description:** When the recovery falls back to a *different* provider, the function still records the
  recovered URL under the original track's key and builds the proxy URL with the original provider's
  identity.
- **Cause:** `recover_stream` distinguishes the two, but then throws the distinction away:
  `core/playback_recovery.py:163-165`
  ```python
  selected_source = fallback
  selected_id = str(candidate.get("source_id") or "")
  ```
  `core/playback_recovery.py:177-181`
  ```python
  resolver = getattr(core, "resolver", None)
  if resolver:
      resolver.refresh(source, identifier, stream)          # <- ORIGINAL key, FALLBACK stream
  proxy = getattr(core, "proxy", None)
  playback_url = proxy.get_proxy_url(source, identifier, stream, track_id=track.get("id")) if proxy else stream
  ```
  `get_proxy_url` therefore stamps `source=<original>` and `source_id=<original>` onto a URL whose `url=`
  parameter carries the *fallback* provider's CDN URL.
- **Trigger conditions:** the recovery's SoundCloud→YouTube fallback (`core/playback_recovery.py:135-165`)
  actually succeeding.
- **User impact:** three concrete consequences, all on the play path:
  1. **Wrong credentials.** The proxy decides which cookies to attach from the `source` parameter
     (`core/proxy.py:983-1006`). With `source=soundcloud` and a `*.googlevideo.com` target,
     `_host_allows_credentials` is `False`, so the proxy logs *"Withholding soundcloud credentials: target host
     'rr3---sn-….googlevideo.com' is not owned by that provider"* and fetches the recovered YouTube stream
     **unauthenticated**.
  2. **Wrong self-heal.** If that fetch 403s, the proxy re-resolves `source`/`source_id`
     (`core/proxy.py:1024-1052`) — i.e. the **original SoundCloud track**, not the YouTube fallback that was
     actually playing. The user gets a different song.
  3. **Poisoned resolver cache.** `resolver.refresh(source, identifier, stream)` writes the *YouTube* URL
     under the *(soundcloud, original id)* key, so the next `resolve_stream_url('soundcloud', id)` returns a
     YouTube CDN URL (`core/resolver.py:232-236`, `audio/engine.py:139`).
- **Evidence:** probe output:
  ```
  built: http://127.0.0.1:5555/?url=https%3A%2F%2Frr3---sn-x.googlevideo.com%2Fvideoplayback%3Fexpire%3D1%26sig%3DSECRET&source=soundcloud&source_id=sc-777&k=TOKEN123
  url carries upstream host  : rr3---sn-x.googlevideo.com
  url declares source        : soundcloud
  actual resolved source     : youtube / yt-999
  credentials for that host  : False (withheld -> the recovery stream is fetched unauthenticated)
  ```
- **Reproduction / verification:** force a stream error on a SoundCloud track (`js/player.js:462-490` calls
  `api.recover_stream`), let the fallback match a YouTube recording, and read
  `~/.nedotify/logs/app.log`: the proxy logs "Withholding soundcloud credentials: target host
  '*.googlevideo.com' is not owned by that provider".
- **Suggested fix:** use `selected_source` / `selected_id` for `resolver.refresh()` and for the proxy URL's
  `source`/`source_id`; keep the original identity only in a separate field if it is needed for reporting.
- **Fix side effects:** the proxy's self-heal then re-resolves the *fallback* track, which is correct, but the
  resolver cache key changes from the original identity to the fallback identity — the original track's cached
  URL is then no longer refreshed.
- **Discovered by:** B

---

#### F-WX-01-5  [P3] — Five independent builders produce the "stream URL", with divergent host lists → the same track gets two different proxy URLs

- **File:** `core/proxy.py:1304-1334`, `audio/engine.py:78-117`, `core/api.py:1216-1225`, `core/api.py:2061-2071`, `core/playback_recovery.py:181`
- **Confirmed:** yes
- **Description:** There is no single owner of the stream-URL contract. Five places assemble it, and the two
  that decide *the shape* use different host lists.
- **Cause:** `core/proxy.py:1304-1334` (`LocalProxyManager.get_proxy_url`) decides between the two shapes with
  ```python
  if original_url and not _host_matches(_host_of(original_url), ('youtube.com', 'youtu.be', 'soundcloud.com')):
      ...  return f'http://127.0.0.1:{self.port}/?{query}'          # shape A: ?url=<upstream>
  ...
  return f'http://127.0.0.1:{self.port}/api/stream?{query}'          # shape B: ?track_id=..
  ```
  while `audio/engine.py:95` decides with a **different** list:
  ```python
  if not any(d in fp for d in ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru")):
      proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}" ...)
  else:
      proxy_url = (f"http://127.0.0.1:{self.proxy.port}/api/stream?track_id={t_id}&source={src}" ...)
  ```
  `music.yandex.ru` is in the engine's list and absent from the proxy's — and the engine's test is a
  *substring* test on the whole URL while the proxy's is a *host-suffix* test.
- **Trigger conditions:** any track whose resolved URL is on `music.yandex.ru`, and any divergence introduced
  by editing one of the five builders.
- **User impact:** the frontend's HLS detection can only see the upstream URL in **shape A**
  (`js/player.js:119-122`):
  ```js
  try { mediaUrl = new URL(src, window.location.href).searchParams.get('url') || src; } catch (e) {}
  const isHls = typeof mediaUrl === 'string' && (mediaUrl.includes('.m3u8') || mediaUrl.includes('/playlist') || mediaUrl.includes('format=m3u8'));
  ```
  In shape B there is no `url=` parameter, so `mediaUrl` falls back to the proxy URL, `isHls` is `false`, and
  an HLS manifest is handed to a native `<audio>` element, which Chromium/WebView2 cannot decode — a silent
  playback failure with no error message (the shipped test
  `tests/test_hls_playback.py:101-124` only exercises shape A). The two shapes also produce different
  credential behaviour and different self-heal behaviour inside the proxy.
- **Evidence:** probe output:
  ```
  yandex     https://music.yandex.ru/track/123  proxy.py=/?url=  engine.py=/api/stream  creds_injected=True
      !! DIVERGENT SHAPES for the same track
  ```
  (all other probed hosts agree, so the divergence is currently limited to `music.yandex.ru`).
- **Reproduction / verification:** run the probe; or call
  `LocalProxyManager.get_proxy_url('yandex','y1','https://music.yandex.ru/track/123', track_id=7)` and compare
  with the URL that `audio/engine.py::_notify_track_changed` builds for the same `file_path`.
- **Suggested fix:** make `LocalProxyManager.get_proxy_url()` the only builder and have `audio/engine.py`,
  `core/api.py` and `core/playback_recovery.py` call it. Keep the host decision in one list
  (`core/proxy.py` already has `CREDENTIAL_HOSTS`; reuse it).
- **Fix side effects:** `get_proxy_url` currently drops the `title`/`artist` parameters that
  `audio/engine.py:97-99` adds; those are used by the proxy as the `source_id` fallback
  (`core/proxy.py:771`), so the single builder must preserve them.
- **Discovered by:** B

---

#### F-WX-01-6  [P3] — The signed upstream CDN URL is handed to the WebView, contradicting the code's own "never expose raw URL" invariant

- **File:** `audio/engine.py:88-99`, `core/proxy.py:1307-1316`
- **Confirmed:** yes
- **Description:** `audio/engine.py:89` states the invariant *"Remote stream URL: serve through proxy
  (SSRF-guarded), never expose raw URL"*, but shape A embeds the raw upstream URL — including its signed
  query — into the URL the browser fetches.
- **Cause:** `audio/engine.py:95-99`
  ```python
  quoted_url = urllib_parse.quote(fp)
  proxy_url = (f"http://127.0.0.1:{self.proxy.port}/?url={quoted_url}&source={src}"
               f"&source_id={src_id}&title={title}&artist={artist}"
               f"{self.proxy.auth_query()}")
  ```
  The same happens in `core/proxy.py:1316`.
- **Trigger conditions:** every play of an online track (shape A is the common case).
- **User impact:** the signed CDN URL (`expire`, `sig`, `key`, `ip`, `pot`) becomes visible in JS state, in
  `audioEl.src`, in the DOM attribute and in the WebView2 network log / DevTools. It is not a leak *upstream*
  (verified clean, see §4) and it is per-session, but it is a bearer-equivalent CDN token that the code
  explicitly says should not leave the backend, and the `/?url=` shape makes it trivially copyable from the
  page.
- **Evidence:** quoted above; the probe prints
  `...?url=https%3A%2F%2Frr3---sn-x.googlevideo.com%2Fvideoplayback%3Fexpire%3D1%26sig%3DSECRET&...`.
- **Reproduction / verification:** in DevTools, inspect `document.querySelector('audio')?.src` (or the
  `window.NeDotify` track payload) and observe the percent-decoded upstream URL.
- **Suggested fix:** prefer shape B (`/api/stream?track_id=…`) for the normal path so the upstream URL stays
  inside the proxy — but that requires fixing the HLS detection coupling of F-WX-01-5 first (the frontend
  needs a way to learn that a stream is HLS without seeing the upstream URL, e.g. a `type=hls` parameter).
- **Fix side effects:** the frontend would lose the ability to sniff `.m3u8` from the URL; HLS detection must
  move to an explicit parameter.
- **Discovered by:** B

---

#### F-WX-01-7  [P3] — The SSRF check and the fetch resolve the hostname twice → DNS-rebinding TOCTOU

- **File:** `core/api.py:99` (`_SSRF_CACHE_TTL = 120.0`), `core/api.py:133-158` (`_dns_resolves_to_public_ip`), `core/api.py:161-196` (`_is_ssrf_safe_url`), `core/proxy.py:390-393` (`_safe_urlopen`)
- **Confirmed:** yes (as a design weakness; exploitability is gated by the proxy token)
- **Description:** The safety verdict is computed from one DNS resolution, but the actual connection is made
  from a second, independent resolution.
- **Cause:** `_is_ssrf_safe_url` resolves the host itself and memoises the verdict for 120 s:
  ```python
  addr_info = socket.getaddrinfo(hostname, None)
  ...
  _ssrf_cache_put(hostname, verdict)
  ```
  The fetch then goes through `urllib.request`, which resolves the hostname **again** when it opens the socket
  (`core/proxy.py:390-393` → `urllib.request.build_opener(...).open(req, timeout=timeout)`).
- **Trigger conditions:** an attacker-controlled hostname whose DNS answer changes between the check and the
  connection (classic rebinding), or simply a hostname that resolves to a private address only on the second
  lookup.
- **User impact:** a successful rebind makes the proxy fetch an internal address from the user's machine. The
  blast radius is limited because (a) the request must carry the per-session token, and (b) the local-file
  gate still refuses to serve internal files as audio — the reachable targets are internal HTTP services.
- **Evidence:** quoted above; the two resolutions are in different modules and cannot share a socket address.
- **Reproduction / verification:** point a test hostname at 127.0.0.1 with a 0-second TTL and request
  `/?url=http://<host>/x&k=<token>`; the verdict and the connection use different `getaddrinfo` answers.
  (Not executed — it needs a controllable DNS server and a live proxy.)
- **Suggested fix:** resolve once and pin the address: resolve the host in the proxy, validate **all**
  returned addresses, and connect to the validated IP with the correct `Host` header (or use a transport that
  supports a pinned address).
- **Fix side effects:** TLS certificate validation and `Host`/`SNI` handling must be preserved when pinning;
  redirects would need re-resolution (the redirect handler already re-validates, so it must also re-pin).
- **Discovered by:** B

---

#### F-WX-01-8  [P3] — The proxy writes to SQLite on every cached range request and mixes two copy-loop granularities

- **File:** `core/proxy.py:807-812`, `core/proxy.py:554-567`, `core/proxy.py:569-588`
- **Confirmed:** yes
- **Description:** Every proxy request that finds the track on disk performs a DB **write**, and the two
  response paths use different chunk sizes on an unbuffered `wfile`.
- **Cause:** `core/proxy.py:807-812`
  ```python
  for ext in ("m4a", "webm", "mp3", "ogg"):
      candidate_path = os.path.join(streams_dir, f"{cache_name}.{ext}")
      if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1024:
          self.server.app_core.db.set_cached_file(source, source_id, candidate_path)
          self.serve_local_file(candidate_path)
  ```
  `set_cached_file` is a write although the value is already in the DB. A `<audio>` element issues a new
  `Range` request for every seek, so a user scrubbing a track produces a write per seek. Separately, the
  "full" path uses `shutil.copyfileobj` (64 KiB blocks, `core/proxy.py:562-564`) while the "range" path
  hand-rolls an 8 KiB loop (`core/proxy.py:578-588`); `BaseHTTPRequestHandler.wfile` is unbuffered
  (`wbufsize = 0`), so every chunk is a separate `sendall`.
- **Trigger conditions:** any play of a track that is already cached on disk, plus every seek.
- **User impact:** WAL writes and fsync pressure during seeking, and 8× more syscalls per byte on the range
  path than on the full path.
- **Evidence:** quoted above.
- **Reproduction / verification:** open a cached track, seek 20 times, and count the `stream_cache` writes
  (WAL growth in `~/.nedotify/nedotify_storage.db-wal`).
- **Suggested fix:** only call `set_cached_file` when the stored path differs from `candidate_path`; use one
  copy loop (or `shutil.copyfileobj` with an explicit 64 KiB buffer) for both paths.
- **Fix side effects:** none material; the DB write is idempotent, so skipping it is safe.
- **Discovered by:** B

---

### 4. Clean areas

* **The proxy token is handled correctly.** 192 bits of entropy
  (`secrets.token_urlsafe(24)`, `core/proxy.py:1275`), minted before the port is announced and regenerated on
  every `start()`; held in memory only (`core/proxy.py:1271`) and **never written to the DB** — the DB stores
  upstream URLs and local paths, never the token. Compared with `hmac.compare_digest`
  (`core/proxy.py:511`); **fails closed** when unset (`core/proxy.py:503-506`); masked in the request log
  (`core/proxy.py:489`, and the log level is INFO so it is not even written); handed to the frontend only
  through the bridge (`core/api.py:1398-1405` → `js/main.js:34-57`).
* **The SSRF gate really is applied to the upstream on every leg of the play path**: `/` branch
  (`core/proxy.py:954`), `/api/stream` branch (`:841`), the URL re-resolved after a 403 (`:1054`), and every
  redirect hop (`SafeRedirectHandler.redirect_request`, `:379-380`). Verified by probe:
  `_is_ssrf_safe_url('http://127.0.0.1:1/x') = False`.
* **A client-supplied `url`/`source_id` cannot make the proxy fetch an internal host**, and the provider
  entry points are separately allow-listed: `services/youtube_service.py:86-98`
  (`_is_allowed_youtube_target` — `_YT_HOSTS` only) and `services/soundcloud_service.py:634-636` (an
  arbitrary URL is handed to the SoundCloud *resolve API*, not fetched by the backend).
* **The loopback token never reaches the upstream provider.** The proxy builds a fresh
  `urllib.request.Request(target_url)` (`core/proxy.py:859`, `:965`) and copies only `Range` and `User-Agent`;
  the browser's `Cookie`, `Authorization` and `Referer` are not forwarded. Python 3.14.7's
  `urllib.request.HTTPRedirectHandler.redirect_request` adds **no** `Referer` header (verified against the
  installed stdlib), so the signed CDN URL is never leaked in a `Referer` to the provider. The HLS rewrite
  keeps the token on `127.0.0.1` only (`core/proxy.py:402-408`), and `tests/test_hls_playback.py:59`
  asserts `proxy.token not in req.full_url`.
* **Credential scoping is sound.** `_host_allows_credentials` (`core/proxy.py:91-99`) anchors the suffix
  with a dot, so `evil.youtube.com.attacker.net` does **not** match `youtube.com`; and
  `SafeRedirectHandler.redirect_request` (`:382-386`) strips `authorization`/`cookie` when a redirect
  crosses to a host the provider does not own. The `Authorization` header is added with `add_header` (so it
  *is* copied on redirect) and is therefore correctly stripped.
* **Query/path encoding is correct everywhere on this path.** `get_proxy_url` uses
  `urllib.parse.urlencode` (`core/proxy.py:1315`, `:1333`); the HLS `local_url()` helper uses `urlencode`
  (`:406-408`); `audio/engine.py` uses `urllib.parse.quote` (`:91-96`, `:114`). A path containing a space,
  `#`, `%`, `&` or `?` cannot break the query string — every one of them is percent-encoded. (The single
  exception is `core/api.py:2064`, where `source` is interpolated unquoted; `source` is application-controlled,
  not client-controlled.)
* **The local-file gate is applied on every branch** (`core/proxy.py:238-272`, `:684-692`) and refuses
  arbitrary disk reads; `tests/test_proxy_security.py` pins it.
* **The resolution never blocks the bridge thread or the UI thread.** `re_resolve_stream_url_async` runs its
  worker on a dedicated daemon thread (`core/app.py:506`), and `_emit` keeps its `EmitWorker` branch
  (`core/api.py:1147-1154`). The synchronous part of `play_track` is a handful of SQLite reads and
  `os.path.exists` calls.
* **The HLS instance lifecycle is correct.** `destroyHls` is called on every track change
  (`js/player.js:115`, `:755`) and on release (`:155-161`); the instance is stored on the element that owns
  it so the crossfade prefetch does not tear down the stream that is still playing (`:87-95`); the
  `loadAudioSource` early-return (`:109-114`) keeps the prefetched work.
* **The proxy's request threads are daemons and release their per-thread SQLite connection**
  (`core/proxy.py:425-430`, `:469-486`).
* **Provider-level single-flight exists** for YouTube (`services/youtube_service.py:912-917`) and
  SoundCloud (`services/base_service.py:140-151`), which is what keeps F-WX-01-3 from becoming a double
  network fetch on those two providers.

---

### 5. Architecture improvements (ARCH)

These are improvements **without** a proven defect; they are reported separately from §3.

**ARCH-1 — Introduce a single `StreamUrlContract` module that owns the stream URL.**
Right now the URL is assembled in `core/proxy.py::get_proxy_url`, `audio/engine.py::_notify_track_changed`,
`core/api.py::_on_track_changed`, `core/api.py::get_next_track` and `core/playback_recovery.py::recover_stream`,
and *parsed* in `core/proxy.py::do_GET`. Every field name (`url`, `source`, `source_id`, `track_id`, `title`,
`artist`, `k`) is a string literal repeated in eight places across Python and JS. The project has a named
failure mode for exactly this ("a renamed event … disappears without a traceback", `AGENTS.md`). A single
module that owns (a) the endpoint set, (b) the parameter vocabulary, (c) the shape decision, (d) the token
parameter, and (e) the encoding, plus a machine-readable manifest the JS side reads, would have caught
F-WX-01-4 and F-WX-01-5 mechanically.

**ARCH-2 — Replace the "absence of `stream_url` means unresolved" signal with an explicit one.**
`js/player.js:1695` infers the backend's state from the absence of two fields. That inference is what makes
the frontend re-enter `play_track` (F-WX-01-3). A `status: 'resolving' | 'ready' | 'failed'` field on the
`track_changed` payload would make the handoff explicit and remove the need for the frontend to guess.

**ARCH-3 — Let `StreamResolver` be the only front door for stream resolution.**
Today there are two resolution front doors (`core/app.py::re_resolve_stream_url_async` for the play path and
`audio/engine.py::resolve_stream_url` → `StreamResolver.resolve` for the proxy path) with different caching,
different single-flight and different negative-cache semantics (F-WX-01-2). `StreamResolver` already models
the right thing (mem → DB → network, single-flight, negative cache); it should be the only entry point, with
`re_resolve_stream_url_async` reduced to "call the resolver, then publish".

**ARCH-4 — One owner for the stream cache.**
The stream cache is written by the proxy (`core/proxy.py:1187-1208`) *and* by the cache manager
  (`utils/cache_manager.py:289-394`) *and* purged by `purge_stream_cache` (`:171-271`) which also mutates
  `tracks.file_path`. Three modules own one directory. A `StreamCache` service with `publish(path)` /
  `lookup(key)` / `purge()` would remove the double download (F-WX-01-1) and the write race.

**ARCH-5 — Let the backend tell the frontend what kind of stream it is.**
The frontend sniffs HLS out of the URL (`js/player.js:119-122`), which is why the URL has to leak the
upstream URL (F-WX-01-6). Adding an explicit `stream_type` field to the track payload (or a `type=hls`
parameter on the proxy URL) decouples "how the bytes are served" from "what the URL looks like", and would
let the upstream URL stay in the backend.

**ARCH-6 — Make the proxy's per-request work explicit and measurable.**
Every proxy request repeats `db.get_track` + `db.get_cached_stream` + up to 4 `stat()` calls + a resolver
lookup + an SSRF verdict (DNS, memoised 120 s). With a "request budget" comment or a small per-request
context object, the duplicated lookups would be visible; today they are spread over ~40 lines of `do_GET`
with two independent ladders (`core/proxy.py:795-812` and `:863-968`).

**ARCH-7 — The `play_track` / `_resolve_track` cache ladder is copy-pasted.**
`core/api.py:1510-1568` and `core/api.py:1613-1704` are two near-verbatim copies of the same
"usable file → DB stream cache → on-disk streams dir → give up" ladder (~55 lines each), differing only in
what they do at the end. The two copies already differ in one respect: `_resolve_track` pops `stream_url`
as well as `file_path` when the URL is expired (`core/api.py:1644-1647`), `play_track` does not
(`:1521-1524`). One shared helper (`_resolve_local_or_cached(track)`) would remove the divergence class
entirely.

---

### 6. Coverage gaps

* **No live measurement.** The rules forbid running the real app and the `network` marker is deselected, so
  every latency statement in this report is *structural* (number of sequential network stages), not measured.
  `tools/bench` was not executed.
* **F-WX-01-1's extension-mismatch variant** (proxy writes `.webm`, yt-dlp writes `.m4a`, leaving two files
  for one track) is a **hypothesis**: it depends on which format each side picks for a given track. The
  *double download itself* is confirmed from the code. Evidence that would settle it: play a YouTube track
  whose upstream `Content-Type` is `audio/webm` and list `~/.nedotify/streams/`.
* **F-WX-01-5's user-visible half** (a shape-B URL serving an HLS manifest silently fails in Chromium) was
  traced statically and cross-checked against the shipped test
  `tests/test_hls_playback.py:101-124`, which only exercises shape A. I could not determine from the code
  alone how often shape B is produced for an HLS-capable provider in a real session; the answer needs a
  live session with DevTools open.
* **F-WX-01-7 was not exploited** (it needs a controllable DNS server and a running proxy). The two-resolution
  TOCTOU is confirmed by reading; the practical exploitability is unverified.
* **The provider internals were only read at the entry points** needed for this scenario
  (`get_stream_url`, the single-flight, the target allow-list). The YouTube/SoundCloud/Yandex extraction
  pipelines themselves are WN-19/WN-20/WN-21 and were not audited.
* **`core/database.py` was read only through its call contract** (`get_cached_stream`, `cache_stream`,
  `set_cached_file`, `invalidate_cached_stream`); the schema and WAL behaviour are WN-12.
* **`android/` was not opened** (out of scope for this run).
