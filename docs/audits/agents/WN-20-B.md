## AREA WN-20 — SoundCloud provider — ROLE B

### 1. Scope reviewed

**Files opened (path: line ranges actually read):**

- `services/soundcloud_service.py` — L1–1055 (whole file; `_TTLCache` L17–49, `_is_drm_transcoding` L88–97, `_is_unplayable_error` L100–103, `_MEDIA_DENIED_STATUSES` L109, `_unavailable_key` L112–123, `SoundCloudService` L126–1055: `__init__` L129–171, `_get_client_id` L173–210, `_api_get` L212–229, `reset_ydl` L231–235, `_get_ydl` L237–264, `_get_ydl_search` L266–289, `search` L295–402, `get_playlist_tracks` L404–491, `get_track_metadata` L493–524, `_mark_unavailable` L526–539, `_media_url_is_servable` L541–567, `get_stream_url` L569–846, `download_audio_sync` L847–958, `get_related_tracks_sync` L960–1016, `get_waveform_data_sync` L1018–1055)
- `services/base_service.py` — L1–329 (the `BaseMusicService` contract this provider extends)
- `core/api.py` — L2080–2379 (search fan-out, provider dispatch, 8 s SoundCloud deadline), L2440–2509 (M3U export), L2540–2619 (`get_playlist_tracks`), L3240–3284 (`_resolve_track_metadata`), L3570–3609 (`get_waveform`), L1608–1757 (`_resolve_track` play path)
- `core/app.py` — L85–129 (service construction/locks), L188–198 (`soundcloud` lazy property), L270–299 (`re_resolve_stream_url_async`), L300–506 (YouTube→SoundCloud fallback cascade), L508–586 (`cleanup` pool shutdown)
- `core/proxy.py` — L40–84 (host allow-lists, `CREDENTIAL_HOSTS`), L900–1119 (stream proxy, SSRF guard, cookie injection, 403 self-heal)
- `core/resolver.py` — L1–271 (`StreamResolver`, `_FAIL_TTL`, `mark_unavailable`, `invalidate`, `refresh`)
- `core/downloader.py` — L500–669 (TrackResolver construction, `_RETRYABLE_MARKS`, `_fetch_from_provider` SoundCloud branch)
- `core/download_transfer.py` — L1–40 (download filename stem)
- `audio/engine.py` — L120–365 (SoundCloud fallback tier of the resolve cascade)
- `services/track_resolver.py` — L230–409 (`_search_soundcloud`, `resolve_track`)
- `services/playlist_import_service.py` — L120–229 (`_resolve_soundcloud`, `_enrich_soundcloud_tracks`)
- `services/recommendation_service.py` — L580–609, L725–754 (resolver use, source filters)
- `services/youtube_service.py` — L1–200, L1100–1190 (`_is_storyboards_only`, `_YT_GATING_MARKS`, `_has_playable_audio`, `_is_allowed_youtube_target`)
- `utils/url_safety.py` — L1–37 (`is_safe_media_url`, the repo's SSRF guard)
- `tests/test_soundcloud_drm_unavailable.py` — L1–355
- `tests/test_provider_loading.py` — L1–209
- `tests/test_provider_performance.py` — L1–102
- `requirements.txt` — L1–25; `setup_pyinstaller.spec` — L1–111
- Installed dependency sources read for ground truth: `yt_dlp` 2026.08.19 `extractor/soundcloud.py` (L85–165, L255–300, L360–395), `extractor/common.py::raise_geo_restricted` / `report_drm`, `yt_dlp/__pyinstaller/hook-yt_dlp.py`

**Callees traced into other areas (defects there are attributed to that area, not re-reported here):**

- `core/resolver.py::StreamResolver` — owns the resolver-level negative memo (`_FAIL_TTL = 120 s`). Its `mark_unavailable()` has **no production caller**; only `tests/test_soundcloud_drm_unavailable.py` calls it. (See ARCH-1.)
- `core/proxy.py` — owns the loopback proxy, the host allow-lists (`SOUNDCLOUD_HOSTS`), the SSRF guard on the fetched URL, and the 403 self-heal loop.
- `core/downloader.py` — owns `_RETRYABLE_MARKS` (decides whether a failed SoundCloud download is retried) and the per-download `TrackResolver` construction.
- `services/youtube_service.py` — owns the YouTube anti-bot/DRM gating (`_YT_GATING_MARKS`, `_is_storyboards_only`).
- `services/playlist_import_service.py` — owns the N+1 per-track metadata enrichment of an imported SoundCloud set.
- `services/recommendation_service.py` — owns the recommendation feed's `source in ('soundcloud','youtube','local')` filter.
- `utils/url_safety.py` — owns `is_safe_media_url`, the repo-wide SSRF guard that this provider does not use.
- `core/api.py` — owns the bridge surface (`search` deadline, `get_playlist_tracks`, `get_waveform`).

---

### 2. Findings

#### F-WN-20-1  [P1] — A CDN refusal arms a 60-minute "unavailable" memo that then suppresses the yt-dlp path *and* the YouTube fallback, so one 403 makes the track unplayable for an hour

- **File:** `services/soundcloud_service.py:526-539` (`_mark_unavailable`), `:585-592` (memo short-circuit), `:693-699` (CDN 403 → memo), `:106-109` (`_MEDIA_DENIED_STATUSES`); caller-side: `core/app.py:322-329`, `audio/engine.py:317`
- **Confirmed:** yes
- **Description:** The "track is gone" memo is armed from a **CDN HTTP status**, not from a track property. `_media_url_is_servable()` treats `401/403/404/410` on the media URL as "this media is not for you" and the caller then calls `_mark_unavailable(track_url, 'CDN refused the media URL')`. The memo is consulted at the *top* of `get_stream_url`, **before** the yt-dlp extraction and **before** the YouTube fallback, so from the second attempt onwards the track cannot be resolved at all — for `_UNAVAILABLE_TTL = 3600` seconds.
- **Cause:** The memo conflates two different verdicts. "The CDN refused *this media URL*" (a per-URL, per-attempt, per-network-condition outcome) is stored under a key that means "*this track* cannot be extracted", and the key is checked at a point in the flow that also gates the *cross-provider* fallback. A CDN 403 is emitted by SoundCloud for rate-limiting, geo-restriction, bot detection and expired signed URLs as well as for DRM/removed content; the code cannot tell them apart.
- **Trigger conditions:** The api-v2 fast path obtains a media URL, the ranged CDN probe returns 403/401/404/410, and the yt-dlp path then returns a preview-only or unplayable URL (so no stream URL is cached). The very next `get_stream_url` for the same track returns the memo's answer with zero provider calls.
- **User impact:** The track is unplayable for up to **60 minutes** even when a different source could have served it. The user is shown `"Трек недоступен: защищён DRM или снят автором"` — a diagnosis that is *wrong* for a CDN refusal and actively misleads ("my track was taken down?!"). The player then gives up on the track (`core/api.py:1716-1721` → `_on_audio_error`).
- **Evidence:**
  ```python
  # services/soundcloud_service.py:106-109
  _MEDIA_DENIED_STATUSES = frozenset({401, 403, 404, 410})

  # services/soundcloud_service.py:693-699
  if self._media_url_is_servable(stream_url):
      self._verified_cache.set(stream_url, True)
  else:
      self._mark_unavailable(track_url, 'CDN refused the media URL')
      stream_url = None

  # services/soundcloud_service.py:585-592  (BEFORE the yt-dlp path at L719 and
  #                                         BEFORE the YouTube fallback at L750)
  unavailable = self._unavailable_cache.get(_unavailable_key(track_url))
  if unavailable and not cached_url:
      self.logger.info(
          f'SoundCloud {track_url} is unavailable ({unavailable}); not re-resolving')
      if error_callback:
          error_callback(_UNAVAILABLE_MSG)
      return
  ```
- **Reproduction / verification:** Offline probe against the real `SoundCloudService` (stubbed `requests.Session`, stubbed yt-dlp, `services.youtube_service.YouTubeService` replaced by a stub whose `search()` fails transiently):
  - attempt 1 → 3 HTTP calls (`/tracks/{id}`, `/media/...`, CDN probe) + 1 YouTube fallback search → error `"Ошибка резервного поиска YouTube: ..."`, memo = `"CDN refused the media URL"`.
  - attempt 2 → **0 HTTP calls, 0 YouTube calls**, error = `"Трек недоступен: защищён DRM или снят автором"`.
  Script: `C:\Users\Артур\AppData\Local\Temp\opencode\sc_probe2.py` (case A). Run: `& ".venv_win\Scripts\python.exe" "$env:TEMP\opencode\sc_probe2.py"`.
- **Suggested fix:** Separate the two verdicts. Keep a per-URL negative verdict (short TTL, e.g. 60–120 s, keyed by the media URL) for "the CDN refused this URL", and reserve the *track-level* memo for verdicts that are genuinely track properties (DRM transcodings, `policy == 'BLOCK'`, "removed by the owner"). Do not let a CDN verdict short-circuit the cross-provider fallback — the YouTube fallback must be attempted before the track is declared unplayable.
- **Fix side effects:** A shorter CDN-verdict TTL re-introduces some probe traffic (one ranged GET per re-resolution). The correct trade is to let the fallback run once per resolution rather than to memo a network outcome for an hour.
- **Discovered by:** B

---

#### F-WN-20-2  [P1] — The failure classifier recognises DRM only: private, deleted and geo-blocked tracks are classified as transient and re-resolved on every single attempt

- **File:** `services/soundcloud_service.py:65-77` (`_UNAVAILABLE_MARKS` + its docstring), `:100-103` (`_is_unplayable_error`), `:644-645` (`policy` handling), `:719-739` (yt-dlp error branch)
- **Confirmed:** yes
- **Description:** `_UNAVAILABLE_MARKS` is `('drm', 'private video', 'video unavailable', 'this video is unavailable', 'has been removed', 'does not exist')`. The docstring above it claims the list covers "DRM/licence-protected uploads … **and for private or deleted tracks**". It does not. `'private video'` and `'video unavailable'` are *YouTube* phrasings; SoundCloud's private/deleted/geo-blocked failures arrive as `HTTP Error 403/404` / `HTTP Error 401` / `raise_geo_restricted`, and the provider never inspects the api-v2 `policy` field except for `'SNIP'`.
- **Cause:** The classification was written against the wrong extractor's error strings, and the fast path only understands one of SoundCloud's three `policy` values.
- **Trigger conditions:** Any non-DRM permanent failure — a private track, a deleted track, a track with api-v2 `policy == 'BLOCK'` (geo-restricted), or an api-v2 `401` (invalid/expired client id for that track).
- **User impact:** The retry storm the module was written to stop still happens, and it is the *expensive* kind: each attempt re-runs `/tracks/{id}` (4 s timeout) + `/media/...` (4 s) + a yt-dlp extraction (`socket_timeout: 10`, `retries: 1`, `extractor_retries: 1`) ≈ up to 18 s of wall-clock per click, with no memo to stop it. The same message also reaches the downloader, where `core/downloader.py::_RETRYABLE_MARKS` contains `'unable to download json metadata'`, so a *deleted* track is retried 3× with 20 s/40 s backoff — the download queue stalls on a track that can never resolve. (The `_RETRYABLE_MARKS` decision belongs to WN-13; the misclassification that feeds it is here.)
- **Evidence:**
  ```python
  # services/soundcloud_service.py:65-77
  #: Extraction failures that no retry can fix. yt-dlp raises these for
  #: DRM/licence-protected uploads (its own "This video is DRM protected",
  #: extractor/soundcloud.py::report_drm), and for private or deleted tracks.
  _UNAVAILABLE_MARKS = (
      'drm',
      'private video',
      'video unavailable',
      'this video is unavailable',
      'has been removed',
      'does not exist',
  )

  # services/soundcloud_service.py:644-645  (only 'SNIP' is understood)
  preview_only = t_data.get('policy') == 'SNIP'
  ```
  Ground truth from the installed extractor (yt-dlp 2026.08.19):
  ```python
  # yt_dlp/extractor/soundcloud.py:375-379
  if not formats:
      if has_drm:
          self.report_drm(track_id)          # "This video is DRM protected"
      if info.get('policy') == 'BLOCK':
          self.raise_geo_restricted(metadata_available=True)
  # yt_dlp/extractor/common.py::raise_geo_restricted
  # msg='This video is not available from your location due to geo restriction'
  ```
- **Reproduction / verification:** Offline classifier probe (`$env:TEMP\opencode\sc_probe5.py`), calling the real `_is_unplayable_error`:
  | realistic yt-dlp message | `_is_unplayable_error` | `core.downloader` treats it as retryable |
  |---|---|---|
  | `This video is DRM protected` | **True** | False |
  | `This video is not available from your location due to geo restriction` | **False** | False |
  | `unable to download JSON metadata: HTTP Error 404: Not Found` | **False** | **True** |
  | `unable to download JSON metadata: HTTP Error 403: Forbidden` | **False** | **True** |
  | `unable to download JSON metadata: HTTP Error 401: Unauthorized` | **False** | **True** |
  | `unable to download webpage: Read timed out` | False | True |
- **Suggested fix:** Derive the verdict from structured signals, not from free-text substrings: the api-v2 `policy` field (`'BLOCK'` → geo-blocked, `'SNIP'` → preview), the HTTP status of the api-v2 track/media calls (401/403/404 → permanent for that track vs 429/5xx → transient), and yt-dlp's `GeoRestrictedError` / `report_drm` exception *types*. Keep the substring list only as a last-resort fallback and correct its contents.
- **Fix side effects:** Treating 401 as permanent would mask a genuinely expired client id. Distinguish "the api-v2 call was rejected because of the client id" (refresh the id and retry) from "the track is not accessible".
- **Discovered by:** B

---

#### F-WN-20-3  [P1] — The positive stream cache is class-level, the negative/verified caches are per-instance, so the "remember the failure" contract is defeated by the app's other `SoundCloudService` instances

- **File:** `services/soundcloud_service.py:141-153` (instance caches), `services/base_service.py:126` (`_stream_cache` is a class attribute)
- **Confirmed:** yes
- **Description:** `BaseMusicService._stream_cache` is a **class** attribute, so every provider instance sees the same positive cache. `_unavailable_cache`, `_verified_cache`, `_related_cache`, `_waveform_cache` and `_track_metadata_cache` are **instance** attributes. The app creates several `SoundCloudService` instances: one long-lived in `core/app.py:193`, one per `TrackResolver` in `services/track_resolver.py:252`, and one per playlist import in `services/playlist_import_service.py:192`.
- **Cause:** The provider's caches were given instance scope while the base class's positive cache has class scope, so a track's "known bad" verdict lives in a shorter-lived object than its "known good" URL. The asymmetry means a new instance sees the cached stream URL but not the verdict that invalidated it.
- **Trigger conditions:** Any resolution that goes through a `TrackResolver` (every Spotify download — `core/downloader.py:516-522` builds a fresh `TrackResolver` per download) or a playlist import.
- **User impact:** The "permanent failure is remembered, the next attempt costs zero provider calls" contract that `tests/test_soundcloud_drm_unavailable.py` documents holds **per instance only**. A track that instance A already declared dead is fully re-resolved by instance B — 3 HTTP calls plus a yt-dlp extraction plus a YouTube fallback search — and instance B re-arms its own memo. The user pays the full cost again for every download that goes through the resolver path.
- **Evidence:**
  ```python
  # services/base_service.py:124-127  (class scope — shared by every instance)
  _executor = _SharedExecutor(max_workers=8)
  _cache_lock = threading.RLock()
  _stream_cache: Dict[str, Any] = {}

  # services/soundcloud_service.py:141-153  (instance scope)
  self._related_cache = _TTLCache(max_entries=100, ttl_seconds=600)
  self._waveform_cache = _TTLCache(max_entries=100, ttl_seconds=600)
  self._track_metadata_cache = _TTLCache(max_entries=200, ttl_seconds=60,
                                        lock=self._cache_lock)
  self._unavailable_cache = _TTLCache(max_entries=200, ttl_seconds=_UNAVAILABLE_TTL)
  self._verified_cache = _TTLCache(max_entries=200, ttl_seconds=_UNAVAILABLE_TTL)
  ```
  ```python
  # services/track_resolver.py:249-255
  if not self.sc_service:
      try:
          from services.soundcloud_service import SoundCloudService
          self.sc_service = SoundCloudService(settings=self.settings)
  ```
- **Reproduction / verification:** Offline probe (`$env:TEMP\opencode\sc_probe2.py` case B, `$env:TEMP\opencode\sc_probe3.py` case G). A second `SoundCloudService` instance, given the same track, re-issued all 3 HTTP calls and re-ran the YouTube fallback search that instance A had been told to forget; `scA._unavailable_cache is not scB._unavailable_cache` → True, while `BaseMusicService.get_from_cache("soundcloud:1")` is visible from both.
- **Suggested fix:** Give the provider one owner. Either (a) make the provider's caches class-level like the base class's, keyed with a `soundcloud:` namespace, or (b) inject the single long-lived instance (`core/app.py:193`) into `TrackResolver` and `PlaylistImportService` instead of letting them build their own, and move the negative verdicts into the class-level cache.
- **Fix side effects:** Class-level caches need the class-level `_cache_lock` for every access (the repo rule: "a new shared field joins its class's existing lock"). `_track_metadata_cache` already does this; the others would have to.
- **Discovered by:** B

---

#### F-WN-20-4  [P2] — Every `SoundCloudService()` instantiation allocates a 10-thread pool, a fresh `requests.Session` and a fresh 5-request client-id scrape, and the extra instances are never shut down

- **File:** `services/soundcloud_service.py:132` (`ThreadPoolExecutor(max_workers=10)`), `:155` (`requests.Session()`), `:158-160` (connection pool), `:169-171` (constructor submits the scrape + `_get_ydl`); instances created at `services/track_resolver.py:252`, `services/playlist_import_service.py:192`; a `TrackResolver` per download at `core/downloader.py:516-522`; shutdown list at `core/app.py:572-586`
- **Confirmed:** yes
- **Description:** Constructing the provider is expensive: it creates a private 10-worker thread pool, a `requests.Session` with a 20-connection pool, and immediately submits two warm-up tasks — `_get_client_id` (a live scrape of `soundcloud.com` plus its JS bundles plus api-v2 validation calls) and `_get_ydl`. The two extra creation sites are per-operation, and `core/app.py`'s cleanup only shuts down `self._soundcloud._executor` — the `TrackResolver`/playlist-import instances are never shut down, so their pools, sessions and sockets live for the whole process lifetime.
- **Cause:** The provider is used as a library object rather than as a singleton, and its per-instance state (client id, caches) was never made shareable — see F-WN-20-3.
- **Trigger conditions:** Every Spotify download that reaches `TrackResolver` (`core/downloader.py:516` builds a new `TrackResolver` **per download task**, and `TrackResolver._search_soundcloud` builds a new `SoundCloudService` when `self.sc_service` is None) and every SoundCloud playlist import.
- **User impact:** Measurable overhead per download: a full client-id scrape (5 HTTP round trips measured) plus a new connection pool and TLS handshakes. Over a batch of N downloads that is N×5 extra requests to `soundcloud.com`/`sndcdn.com`/`api-v2.soundcloud.com` plus N leaked thread pools and sessions — a resource leak and a needless load on SoundCloud's edge, which is also the fastest way to get the app's IP rate-limited (which then triggers F-WN-20-1).
- **Evidence:**
  ```python
  # services/soundcloud_service.py:132, 155, 169-171
  self._executor = ThreadPoolExecutor(max_workers=10)
  ...
  self._session = requests.Session()
  adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
  ...
  self._executor.submit(self._get_client_id)
  if HAS_YTDLP:
      self._executor.submit(self._get_ydl)
  ```
  ```python
  # core/app.py:572-578 — only the AppCore-owned instance is shut down
  for _pool in (
      ...
      getattr(self, "_soundcloud", None) and getattr(self._soundcloud, "_executor", None),
  ```
- **Reproduction / verification:** Offline probe (`$env:TEMP\opencode\sc_probe3.py` cases C/D/E, `$env:TEMP\opencode\sc_probe4.py` cases I/J):
  - cold client-id scrape = **5 HTTP round trips**: `https://soundcloud.com` → 1 JS bundle → 3 api-v2 validation calls (one per candidate id). With 4 bundles × 3 candidates the loop is bounded by the 6 s deadline but the request count is `1 + bundles + candidates` (measured 10 calls for a doubled scrape).
  - a **rejected (403) client id costs 5 round trips** for one logical API call: original request → `soundcloud.com` → 1 JS bundle → validation → retry (`_api_get`).
  - two instances ⇒ two `requests.Session` objects, two thread pools, two independent `_client_id`/`_unavailable_cache`/`_verified_cache` states.
- **Suggested fix:** Inject the single `core/app.py` instance into `TrackResolver` and `PlaylistImportService` (both already accept a service object for the sibling providers), and/or make the provider's warm-up lazy so an unused instance performs no network I/O and holds no thread pool.
- **Fix side effects:** Passing the shared instance into `TrackResolver` makes the download path share the provider's `_unavailable_cache` — which is F-WN-20-3's fix, and makes F-WN-20-1's 60-minute memo bite the download path too. Fix F-WN-20-1 first, or fix both together.
- **Discovered by:** B

---

#### F-WN-20-5  [P2] — The provider fetches payload-derived URLs with no SSRF guard and no host allow-list, unlike every other outbound-media path in the codebase

- **File:** `services/soundcloud_service.py:553-564` (`_media_url_is_servable` → `self._session.get(url, …)`), `:1031-1032` (`get_waveform_data_sync` → `self._session.get(json_url, …)`); guard that is *not* used: `utils/url_safety.py:13-37`; applied elsewhere at `audio/engine.py:176`, `core/downloader.py:639,650`, `core/download_transfer.py:67`, `core/proxy.py:954,1054`
- **Confirmed:** yes (code fact); the practical reachability of an attacker-chosen URL is bounded — see *Trigger conditions*
- **Description:** Two outbound requests in this provider use a URL taken from a remote payload (or, for the waveform, from a bridge argument) and are issued with `requests` defaults: no `is_safe_media_url()` check, no host allow-list, and `allow_redirects` left at its default `True`, so a 302 can move the request to any host.
- **Cause:** The provider was written as a "talk to SoundCloud" client and never adopted the repo's `utils/url_safety.is_safe_media_url` convention that the proxy, the downloader and the audio engine all follow. The proxy *does* guard the URL it fetches (`core/proxy.py:954`), so the proxy is safe; the provider's own two fetches are not.
- **Trigger conditions:**
  - `_media_url_is_servable`: the URL comes from `tc_resp.json().get('url')` — a SoundCloud-controlled CDN URL today. Reachable only if the api-v2 response (or a MITM on the non-verified yt-dlp path, see F-WN-20-7) is manipulated.
  - `get_waveform_data_sync`: the URL is taken **verbatim from the bridge argument** — `core/api.py:3587-3590` does `waveform_url = track_data.get("waveform_url")` → `self._core.soundcloud.get_waveform_data_sync(waveform_url)`, and the WebView supplies it (`ui/web_new_v2/js/player.js:2274`). The value normally originates from SoundCloud's own search payload (`services/soundcloud_service.py:338, 996`), but nothing constrains it to a `sndcdn.com` host, and the `.png` → `.json` rewrite does not change the host.
- **User impact:** An SSRF primitive from the user's own machine/network: the desktop app can be made to issue GETs to internal services or cloud metadata endpoints. The response is only returned when it parses as JSON with a `samples` key, so the primitive is blind rather than readable, but the *request* itself is the harmful part. The `requests` session follows redirects, so a SoundCloud-hosted URL that 302s to an internal address is followed.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:553-564
  probe = self._session.get(
      url,
      timeout=3.0,
      headers={'Range': 'bytes=0-1'},
      stream=True,
  )
  ...
  # services/soundcloud_service.py:1023-1032
  json_url = waveform_url
  if json_url.endswith('.png'):
      json_url = json_url[:-4] + '.json'
  ...
  r = self._session.get(json_url, timeout=10.0)
  ```
  For contrast, the guard the rest of the codebase uses:
  ```python
  # core/downloader.py:650
  if sc_url.startswith('http') and not is_safe_media_url(sc_url):
      raise Exception('Unsafe media URL rejected')
  ```
- **Reproduction / verification:** Read the two call sites above and confirm the absence of `is_safe_media_url` / a host allow-list; compare with `core/downloader.py:639-651`, `audio/engine.py:176`, `core/proxy.py:954`. Static confirmation; the probe harness `tests/test_media_guard_f3.py` covers `utils/url_safety.is_safe_media_url` but there is **no test that any provider-issued URL is passed through it**.
- **Suggested fix:** Run both provider-side fetches through `utils.url_safety.is_safe_media_url()` and additionally constrain the hosts to the SoundCloud CDN set already declared in `core/proxy.py:50` (`soundcloud.com`, `sndcdn.com`, `soundcloud.cloud`, `scdn.co`) — the provider should not need to hard-code a second copy of that list; it should import it.
- **Fix side effects:** A strict host allow-list breaks if SoundCloud moves its CDN to a new domain; the failure mode must be a clean error, not a hang. `is_safe_media_url()` performs a DNS lookup per call, which adds latency to the probe — cache the verdict per host for a few minutes.
- **Discovered by:** B

---

#### F-WN-20-6  [P2] — `get_playlist_tracks` never sends `limit` to the API: the whole set is downloaded and only then truncated, and the cache key embeds the limit

- **File:** `services/soundcloud_service.py:404-452` (REST branch), `:456-481` (yt-dlp fallback branch); caller `core/api.py:2545-2600` (`limit: int = 50`)
- **Confirmed:** yes for the code behaviour (limit is not sent; truncation is post-hoc); the on-wire payload size is a hypothesis (see *Reproduction / verification*)
- **Description:** The api-v2 playlist call is built as `https://api-v2.soundcloud.com/playlists/{id}?client_id={cid}` and the resolve form as `…/resolve?url=…&client_id=…` — **neither carries `limit` or `offset`**. The full `tracks` array is received and parsed, and only then does the loop `break` at `len(tracks) >= limit` (L446-447, L475-476). The result is cached under `f"sc_playlist:{playlist_id}:{limit}"`, so a second call with a different `limit` re-downloads the same set.
- **Cause:** The limit was implemented as a client-side truncation of an already-unbounded response instead of as a request parameter.
- **Trigger conditions:** Opening any SoundCloud playlist/set. SoundCloud sets reach several hundred tracks; each entry carries full metadata plus an artwork URL.
- **User impact:** Bandwidth and memory proportional to the *whole* set are spent to render `limit` (50) rows, and the work is repeated for every distinct `limit` value. The `BRIDGE_SYNC_BUDGET` in `core/api.py:2605` can then expire and the user sees `"Таймаут получения треков плейлиста"` for a large set.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:415-447
  raw = str(playlist_id).strip()
  cid = self._get_client_id()
  if cid:
      try:
          if raw.isdigit():
              url = f"https://api-v2.soundcloud.com/playlists/{raw}?client_id={cid}"
          else:
              url = f"https://api-v2.soundcloud.com/resolve?url={urllib_parse.quote(raw)}&client_id={cid}"
          r = self._api_get(url, timeout=4.0)
          ...
              for item in data.get('tracks') or []:
                  ...
                  if limit and len(tracks) >= limit:
                      break
  ```
- **Reproduction / verification:** Static (the URL contains no `limit`). The server-side payload size could not be measured offline; to confirm, issue one request for a set with >200 tracks against a real client id and compare the response size with `limit=50` added to the query string.
- **Suggested fix:** Add `&limit={limit}` (and `offset` for paging) to the api-v2 playlist/resolve URLs, and page explicitly for sets larger than one page. Cache on the set id, not on `{id}:{limit}`.
- **Fix side effects:** The `resolve` endpoint may not honour `limit`; the playlist endpoint does. Keep the client-side `break` as a belt-and-braces guard and add a paging loop for the remainder.
- **Discovered by:** B

---

#### F-WN-20-7  [P3] — TLS certificate verification is disabled for the provider's yt-dlp extraction and search paths

- **File:** `services/soundcloud_service.py:247` (`_get_ydl`), `:276` (`_get_ydl_search`); the download path is **not** affected (`:874`, `:927`, `:946` build their own opts without the flag)
- **Confirmed:** yes
- **Description:** `'nocheckcertificate': True` is set in both yt-dlp option sets, so every metadata/media-manifest request made by the yt-dlp path is accepted without verifying the server certificate. The `requests`-based api-v2 path is unaffected (`requests` verifies by default).
- **Cause:** Copy-pasted house pattern — the same flag appears in `services/youtube_service.py:308`, `services/vk_service.py:63` and `utils/cache_manager.py:352`, so it was never a SoundCloud-specific decision.
- **Trigger conditions:** Any resolution that falls through to yt-dlp (the DRM/preview-only/geo-blocked fallback path), and any search that falls back to `scsearch{max_results}:{query}`.
- **User impact:** A network-position attacker can rewrite the metadata response and substitute the media URL, so the app plays attacker-chosen audio. The blast radius is limited: the proxy withholds provider cookies when the target host is not one of `SOUNDCLOUD_HOSTS` (`core/proxy.py:50, 91-93, 984-1001`), and the proxy fetches the substituted URL over a **verified** TLS connection, so no user credential is forwarded to the attacker's host. The `requests` fast path and the download path are unaffected.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:243-253
  ydl_opts = {
      'quiet': True,
      'no_warnings': True,
      'format': 'bestaudio[protocol^=http]/bestaudio/best',
      'nocheckcertificate': True,
      'legacy_server_connect': True,
      'socket_timeout': 10,
      ...
  ```
- **Suggested fix:** Drop `nocheckcertificate` from the provider's yt-dlp options and let yt-dlp/curl_cffi verify the certificate (curl_cffi is already a hard dependency and ships the CA bundle — see *Clean areas*). If a specific host genuinely breaks verification, scope the exception to that host instead of disabling it globally.
- **Fix side effects:** On a machine with a broken or missing system CA store, the yt-dlp path starts failing where it previously worked. The `curl_cffi` bundle (`cacert.pem`) mitigates this, but it must actually be used (`yt_dlp/__pyinstaller/hook-yt_dlp.py` already collects it).
- **Discovered by:** B

---

#### F-WN-20-8  [P3] — `_get_ydl()` is thread-local, so the proxy rebuilds a yt-dlp instance and re-parses the user's cookie file on every stream request

- **File:** `services/soundcloud_service.py:137` (`threading.local()`), `:237-264` (`_get_ydl`), `:259-262` (`cookiefile` from `auth.cookies_file_path`); consumers `core/proxy.py:998` and `core/proxy.py:1073`, served by `core/proxy.py:421` (`ThreadingHTTPServer`, one thread per request)
- **Confirmed:** yes
- **Description:** `self._ydl_tls = threading.local()` means every thread that calls `_get_ydl()` gets its **own** `yt_dlp.YoutubeDL` instance. The proxy is a threading HTTP server, so each stream request runs on a fresh thread and therefore builds a fresh yt-dlp instance — which re-reads and re-parses the user's cookie file, opens a new HTTP opener and a new connection pool, and re-does the TLS handshake to SoundCloud.
- **Cause:** A per-thread cache was chosen to avoid sharing a cookie jar across threads, but the consumers are per-request threads, so the "cache" never hits.
- **Trigger conditions:** Every stream request proxied for a SoundCloud track (`core/proxy.py:996-1001` injects the yt-dlp cookie jar into the outgoing request; `core/proxy.py:1072-1075` does the same on the 403 self-heal path).
- **User impact:** Measured ~28–185 ms of pure construction overhead per proxy request *with* a 500-cookie file (vs ~36 ms without), plus a new connection pool and TLS handshake — all on the hot streaming path, and multiplied by the number of Range requests the `<audio>` element issues per track.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:237-263
  def _get_ydl(self):
      store = getattr(self._ydl_tls, "instances", None)
      if store is None:
          store = {}
          self._ydl_tls.instances = store
      if "main" not in store:
          ydl_opts = { ... }
          if self.settings:
              proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', ''))
              if proxy:
                  ydl_opts['proxy'] = proxy
              import os
              cookies_file_path = self.settings.get('auth', 'cookies_file_path', '')
              if cookies_file_path and os.path.exists(cookies_file_path):
                  ydl_opts['cookiefile'] = cookies_file_path
          store["main"] = yt_dlp.YoutubeDL(ydl_opts)
      return store["main"]
  ```
  ```python
  # core/proxy.py:996-1001  (runs on a per-request thread)
  elif source == 'soundcloud':
      try:
          ydl = self.server.app_core.soundcloud._get_ydl()
          _inject_ydl_cookies(ydl, req)
  ```
- **Reproduction / verification:** Constructed 500-cookie Netscape `cookies.txt` and timed `yt_dlp.YoutubeDL(...)`: `construct WITH cookiefile : 185.0 ms / 28.3 ms` vs `construct WITHOUT cookiefile: 35.6 ms`; `cookiejar size: 500` — i.e. the file is parsed at construction time, once per instance, and the proxy creates one instance per request.
- **Suggested fix:** Extract the cookie jar once (at construction, or from a single shared yt-dlp instance) and inject *that* into the outgoing request; the proxy only needs the `Cookie` header, not a whole extractor. If a per-thread extractor is still needed for the extract path, keep it but stop using it as the cookie source in the proxy.
- **Fix side effects:** Sharing one cookie jar across threads requires it to be read-only after construction (yt-dlp's `cookiejar` is not documented as thread-safe for concurrent mutation).
- **Discovered by:** B

---

#### F-WN-20-9  [P3] — `_TTLCache` never proactively purges expired entries, and the positive `_verified_cache` inherits the 1-hour negative TTL

- **File:** `services/soundcloud_service.py:17-49` (`_TTLCache`), `:153` (`_verified_cache` with `ttl_seconds=_UNAVAILABLE_TTL`)
- **Confirmed:** yes
- **Description:** (a) An expired entry is removed only when that exact key is read (`get()` L34-36); an entry whose key is never read again stays in the `OrderedDict` until LRU eviction. (b) `_verified_cache` stores a **positive** verdict ("this media URL is servable") but is given the same 3600 s TTL as the negative `_unavailable_cache` — a value chosen for a negative verdict. (c) The `while len(self._data) > self._max` eviction in `set()` (L44-45) means the cache can hold `max_entries + 1` items between calls, which is harmless.
- **Cause:** The cache has no sweep step, and one TTL constant is reused for two different kinds of verdict.
- **Trigger conditions:** Any provider with a steady stream of distinct keys (search + related tracks + resolutions) over a long session.
- **User impact:** Bounded and therefore not a leak: the caches are capped at 100/100/200/200/200 entries. The cost is a slowly stale memory footprint plus a positive verdict that is trusted for up to an hour — during which a media URL that has started 403-ing (expired signed URL) is still handed out from `_verified_cache` without a re-probe.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:28-45
  def get(self, key):
      with self._lock:
          entry = self._data.get(key)
          if entry is None:
              return None
          timestamp, value = entry
          if time.time() - timestamp > self._ttl:
              self._data.pop(key, None)
              return None
          self._data.move_to_end(key)
          return value
  ...
  # services/soundcloud_service.py:153
  self._verified_cache = _TTLCache(max_entries=200, ttl_seconds=_UNAVAILABLE_TTL)
  ```
- **Suggested fix:** Add a sweep on write (drop expired entries when the cache grows) or give `_TTLCache` an explicit `purge_expired()` called on a timer; use a short TTL (60–120 s) for `_verified_cache` — a positive "servable" verdict ages quickly.
- **Fix side effects:** A shorter `_verified_cache` TTL adds one probe round trip per re-resolution of the same track; that is the price of not handing out a URL that has since started failing.
- **Discovered by:** B

---

#### F-WN-20-10  [P3] — The api-v2 REST fast path has no TLS impersonation and no bot-detection handling, so its failure mode is an expensive yt-dlp fallback rather than an impersonated retry

- **File:** `services/soundcloud_service.py:59-63` (`import requests`), `:155-163` (session + spoofed `User-Agent`), `:357-358` / `:453-454` (the "REST failed → yt-dlp" fallbacks); the impersonation dependency is declared at `requirements.txt:10-14`
- **Confirmed:** yes (code fact: the provider never imports `curl_cffi`; the impersonation is only available inside yt-dlp)
- **Description:** The provider's own REST client is plain `requests` with a **spoofed Chrome `User-Agent` string** but the real (non-impersonated) TLS/JA3 fingerprint. The repository explicitly depends on `curl_cffi` for TLS impersonation — but only for **yt-dlp's** extractor:
  > `requirements.txt:10-14` — *"yt-dlp needs a TLS-impersonating HTTP stack for the SoundCloud extractor. Without it the extractor logs 'attempting impersonation, but no impersonate target is available' and SoundCloud metadata fetches fail. Install is not optional"*
  The primary path (search, playlist, track metadata, transcodings, related tracks, waveform) is exactly the path that has **no** impersonation; the yt-dlp fallback has it.
- **Cause:** The REST fast path was written as a lightweight optimisation over yt-dlp and inherited the UA string without the matching TLS stack.
- **Trigger conditions:** Any edge-level bot detection on `api-v2.soundcloud.com` (a 403/429 on the REST call).
- **User impact:** A blocked REST call costs a 4 s timeout and then falls back to a full yt-dlp extraction (`socket_timeout: 10`, `retries: 1`, `extractor_retries: 1`) — i.e. ~10–15 s instead of ~1 s — and the yt-dlp fallback is *also* the path that carries the YouTube fallback cascade. The client-id scrape (5 round trips, F-WN-20-4) rides on the same non-impersonated stack, so a bot-detection event breaks search *and* resolution at once.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:59-63, 161-163
  import requests
  ...
  self._session.headers.update({
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
  })
  # services/soundcloud_service.py:357-358
  except Exception as api_err:
      self.logger.warning(f"Fast SoundCloud REST API search failed, trying yt-dlp: {api_err}")
  ```
  `grep -r "curl_cffi" services/` → no matches; the only `curl_cffi` reference in the source tree is `requirements.txt:14`.
- **Suggested fix:** Either move the REST fast path onto `curl_cffi.requests` with an `impersonate=` target (the dependency is already mandatory and the API is the same one yt-dlp impersonates for), or make the REST failure fall back to an *impersonated* yt-dlp call first and only then to the cross-provider YouTube cascade.
- **Fix side effects:** `curl_cffi` is a compiled, platform-specific wheel (the requirements comment says `cp310-abi3-win_amd64`); switching the REST client to it makes the provider depend on a native extension at import time, which must be reflected in the PyInstaller spec (the current spec relies on yt-dlp's own hook to pull `curl_cffi` in).
- **Discovered by:** B

---

### 3. Clean areas

- **No credential in the repo.** The SoundCloud API `client_id` is **not** hardcoded: `_get_client_id()` (`services/soundcloud_service.py:173-210`) scrapes it at runtime from `soundcloud.com`'s own JS bundles and validates each candidate against api-v2. No token, key or password is committed. The client id is a public value (SoundCloud ships it to every visitor), so its appearance in `~/.nedotify/logs/app.log` via `requests` exception text is not a secret leak.
- **TLS impersonation *is* available in the packaged build.** `curl_cffi>=0.7.0,<1` is a hard dependency (`requirements.txt:14`) and yt-dlp ships its own PyInstaller hook (`yt_dlp/__pyinstaller/hook-yt_dlp.py`) that adds `curl_cffi` to `hiddenimports` and collects `curl_cffi/cacert.pem` as a data file. PyInstaller auto-discovers that hook, so the packaged `.exe` keeps the impersonating stack. `setup_pyinstaller.spec` does not need to list it. (Verified in the installed venv: `curl_cffi 0.16.3`, `curl_cffi.requests` importable.)
- **The stream URL *is* guarded before the bytes are fetched.** `core/proxy.py:954` applies `_is_ssrf_safe_url(target_url)` to the resolved URL, and `:1054` re-checks the re-resolved URL after the 403 self-heal. The download path applies `is_safe_media_url` (`core/downloader.py:639, 650`) and `core/download_transfer.py:67`. The proxy also withholds provider cookies when the target host is not owned by the provider (`core/proxy.py:50, 91-93, 984-989`), so a substituted host cannot harvest the user's SoundCloud cookies.
- **Filename sanitisation is respected (rule #8).** `download_audio_sync` derives every filename from a timestamp only — `sc_{ts}.mp3` (L871-872), `sc_{ts}.%(ext)s` (L931), `sc_yt_{ts}.%(ext)s` (L911). No raw track id, title or artist reaches a path. The download-context stem is sanitised upstream (`core/download_transfer.py:18-20`: `re.sub(r'[^a-zA-Z0-9_-]', '_', …)`). This is better than the documented `services/yandex_service.py` counter-example.
- **No cookies or tokens are written to disk, and none are logged.** The only credential handling is *reading* the user's own `auth.cookies_file_path` into yt-dlp's `cookiefile` (`services/soundcloud_service.py:259-262`). Nothing is written, and the log lines (`_mark_unavailable` L534, L587-589) contain only the track URL and the failure reason.
- **The search path has no N+1.** Measured: exactly **1** api-v2 request per search (`https://api-v2.soundcloud.com/search/tracks?q=…&client_id=…&limit=20`), no per-track detail call. The result list is parsed in one pass, and each item is additionally stored in `_track_metadata_cache` so the later stream resolution can skip the `/tracks/{id}` call (L640-643).
- **`_TTLCache` is bounded, LRU-evicting and thread-safe.** `max_entries` caps every instance (100/100/200/200/200), eviction is LRU (`popitem(last=False)`), and every mutation happens under a lock. The caches are **instance**-scoped, so they cannot leak across providers (the flip side of that is F-WN-20-3).
- **Single-flight and replay are handled well.** `get_stream_url` uses the base class's `_join_request` (L594-597), so N concurrent play/queue requests cost one extraction, and the `_verified_cache` makes a replayed resolution cost **0** HTTP requests (measured: first resolution 3 calls, replay 0 additional calls). `tests/test_provider_performance.py:62-79` pins the "one task, shared API calls" contract.
- **`_is_drm_transcoding` matches the real extractor rule exactly.** The installed yt-dlp 2026.08.19 uses `protocol.startswith(('ctr-', 'cbc-'))` (`yt_dlp/extractor/soundcloud.py`), identical to `services/soundcloud_service.py:96-97`. The docstring's claim is accurate.
- **The api-v2 payload's `media` is not trusted blindly.** DRM transcodings are skipped (L666-668), `snipped`/`SNIP`/`abr_*` presets are skipped (L671-673), and a preview URL is rejected (L678, L743-744).
- **`requests` verifies TLS by default** in this provider — only the yt-dlp option sets disable it (F-WN-20-7). The `HTTPAdapter` is configured with `max_retries=0` and a 20-connection pool (L158), which is the right call given the 8 s UI search deadline noted at L156-157.
- **The provider's `_join_request`/callback contract is respected.** Callbacks are always invoked (success or error) and the base class's `finish()` swallows listener exceptions with a logged traceback (`services/base_service.py:149-160`).

---

### 4. Coverage gaps

- **No live-network measurement.** Every number in this report was produced with a stubbed `requests.Session` / stubbed yt-dlp, so the *latency* of the api-v2 endpoints and of the SoundCloud CDN could not be measured from this machine. One accidental live request did escape (`https://soundcloud.com`, issued by the constructor's warm-up thread during probe #2) and it returned a real script URL (`https://a-v2.sndcdn.com/assets/55-db72ef36.js`), which confirms the scrape still finds script bundles — but no live stream/playback was exercised.
- **The api-v2 playlist payload size (F-WN-20-6) is a hypothesis.** That the endpoint returns the whole set (rather than a default page) is inferred from the code's own `data.get('tracks')` usage and from the fact that no `limit` is sent; it was not confirmed against a real large set.
- **Whether api-v2 still emits `policy == 'BLOCK'` in 2026 could not be checked against the live API.** The installed yt-dlp extractor still handles it (`extractor/soundcloud.py:378-379`), which is strong but indirect evidence.
- **The proxy's cookie-injection behaviour was read, not exercised.** F-WN-20-8's timing was measured for yt-dlp construction, not for the proxy's end-to-end request cost.
- **`services/soundcloud_service.py` was read in full, but its collaborators were not audited for defects**: `core/proxy.py` (WN-11), `core/resolver.py` (WN-15), `core/downloader.py` (WN-13), `audio/engine.py` (WN-17), `services/youtube_service.py` (WN-19), `services/playlist_import_service.py` (WN-24). Defects found in those files are attributed to them, not reported here.
- **The `android/` subtree was not opened** (out of scope for this run).
- **Only the three named test files were read and run.** `pytest tests/test_soundcloud_drm_unavailable.py tests/test_provider_loading.py tests/test_provider_performance.py -q` → **32 passed**; the findings above are therefore gaps in those tests' coverage, not contradictions of them. The full suite was not executed.
- **The SoundCloud account/credentials model was not exercised** (no logged-in SoundCloud session, no premium/geo-restricted account available), so the behaviour of `policy == 'BLOCK'` and of premium transcodings is inferred from the extractor source rather than observed.

---

### 5. Architecture improvements (ARCH)

No proven defect — improvement proposals only.

- **ARCH-1 — Two negative caches with 30× different TTLs, and the shared one is dead code.** `core/resolver.py::StreamResolver` implements the "known unavailable" verdict with `_FAIL_TTL = 120.0` and a public `mark_unavailable(source, source_id, reason)` API — but **`mark_unavailable` has no production caller** (only `tests/test_soundcloud_drm_unavailable.py` calls it). The provider instead keeps a private `_unavailable_cache` with `_UNAVAILABLE_TTL = 3600`. The effective production behaviour is therefore the provider's 60-minute verdict, while the test suite pins the resolver's 2-minute expiry (`test_a_verdict_expires_so_a_re_enabled_track_is_tried_again` monkeypatches `resolver_module._FAIL_TTL`, not the provider's constant) — the suite gives false assurance that a re-enabled track is retried after 2 minutes. *Proposal:* one owner for the verdict. The provider classifies and reports; `StreamResolver` stores and expires it. The provider's verdict should be fed in through `mark_unavailable`, and the TTL should live in one place.

- **ARCH-2 — No provider-capability model.** "Does this provider support streaming / related tracks / waveforms / artwork backfill / downloads" is expressed as ad-hoc duck typing: `core/api.py:3270-3277` does `getattr(svc, "get_track_metadata", None) if svc else None`; `services/recommendation_service.py:374` does `getattr(self.youtube_service, 'get_related_tracks_sync', None)`; `core/api.py:3588` does `hasattr(self._core, "soundcloud")`. `SoundCloudService` implements `get_track_metadata`, `get_related_tracks_sync` and `get_waveform_data_sync`; `YouTubeService` implements `get_related_tracks_sync` but not the other two. Every new capability adds another `hasattr` probe at the call site. *Proposal:* a declarative `ProviderCapabilities` descriptor (`supports_stream`, `supports_related`, `supports_waveform`, `supports_metadata`, `preview_policy`, `drm_policy`) on `BaseMusicService`, so callers branch on data instead of on attribute existence.

- **ARCH-3 — The DRM / unplayable classification is triplicated with three unrelated string lists.** `services/soundcloud_service.py:70-77` (`_UNAVAILABLE_MARKS`), `services/youtube_service.py:64-72` (`_YT_GATING_MARKS`), `core/downloader.py:612-619` (`_RETRYABLE_MARKS`). Each list encodes the *same* three-way question (permanent vs transient vs gated) against a different extractor's wording, and the lists drift — `services/soundcloud_service.py` says "private or deleted tracks" in prose while the list only matches DRM (F-WN-20-2). *Proposal:* a single `classify_failure(exc_or_status) -> FailureKind` in `services/`, with per-provider signal tables (exception types + HTTP statuses), consumed by both the provider and the downloader.

- **ARCH-4 — The provider reaches into `BaseMusicService`'s class-level caches by hand.** `services/soundcloud_service.py:538-539` does `with self._cache_lock: self._stream_cache.pop(f'soundcloud:{track_url}', None)`; the same file hand-rolls four more key namespaces (`sc_search:`, `sc_playlist:`, `sc_rel:`, `sc_unavailable:`) on top of the base class's `soundcloud:` namespace. `services/youtube_service.py:101-121` writes its own `_yt_cache_key()` for the same reason. The base class exposes no namespaced get/set/invalidate API, so every provider re-implements key hygiene and one provider's bug can evict another's entry. *Proposal:* give `BaseMusicService` a namespaced cache handle (`self.cache("soundcloud").get/set/pop`) so key construction, TTL and eviction live in one place.

- **ARCH-5 — One 1055-line class holds six responsibilities.** `SoundCloudService` is simultaneously a client-id scraper (L173-210), a REST client (L212-229, L295-524, L960-1016), a yt-dlp wrapper (L237-289, L847-958), a DRM classifier (L88-123), a cross-provider fallback orchestrator (L719-835) and a waveform/related-track enricher (L960-1055). The YouTube fallback in particular is re-implemented **four** times with four different query-building strategies: `services/soundcloud_service.py:388-398` (search fallback), `:750-820` (stream fallback), `core/app.py:411-492` (`clean_noise` + candidate list), `audio/engine.py:235-279` (a third `clean_noise` implementation). *Proposal:* split into `SoundCloudClient` (transport), `SoundCloudExtractor` (track → media URL), `SoundCloudFallback` (cross-provider), and hoist the shared "artist - title" query builder and "same recording" matcher (`core/playback_recovery.py::same_recording`, already used at L777-778) into one module.

- **ARCH-6 — The client-id discovery is a hand-rolled duplicate of yt-dlp's own.** `services/soundcloud_service.py:187-202` re-implements `yt_dlp.extractor.soundcloud.SoundcloudIE._update_client_id` (same `soundcloud.com` → `<script src>` → `client_id:"…"` regex), plus a per-candidate validation request yt-dlp does not make — which is why the app's scrape costs 5 round trips where yt-dlp's costs 2-3. It also ignores yt-dlp's on-disk client-id cache (`self.cache.load('soundcloud', 'client_id')`), so the app re-scrapes on every process start where yt-dlp would not. *Proposal:* read the client id from yt-dlp's cache first, and only scrape when it is missing or rejected — one discovery implementation instead of two.

- **ARCH-7 — The provider bypasses the shared executor design.** `BaseMusicService` provides a lazily-created, shutdown-safe `_SharedExecutor` precisely so that "importing a service never spawns threads" (`services/base_service.py:65-118`), but `SoundCloudService.__init__` creates its own `ThreadPoolExecutor(max_workers=10)` (L132) and submits two warm-up tasks to it. Every provider does the same (`services/youtube_service.py:195`), so this is a house pattern rather than a SoundCloud defect — but it is the mechanism behind F-WN-20-4. *Proposal:* providers submit through `BaseMusicService.submit()` and keep only a lazy per-provider extractor, not a private pool.

- **ARCH-8 — Provider-side requests bypass the shared SSRF policy.** `utils/url_safety.is_safe_media_url` is the repo's outbound-media policy, but it is applied by the proxy, the downloader and the audio engine — not by the providers themselves, which are the components that actually *choose* the URLs. *Proposal:* make the guard part of the provider transport (a `safe_get()` on the provider's session) so every provider-issued request is covered by construction, rather than relying on each caller to remember.
