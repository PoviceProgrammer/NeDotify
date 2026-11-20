## AREA WN-09 — Bridge lyrics, cover fetch, home feed, artist profile, waveform — ROLE B

### 1. Scope reviewed

**Primary (read in full):**
- `core/api.py` L3192–3595 — `get_lyrics` (3192–3225), `fetch_missing_covers` (3227–3265), `_resolve_track_metadata` (3267–3281), `_resolve_track_cover` (3283–3284), `get_lyrics_translation` (3286–3291), `get_home_data` (3293–3313), `get_popular_tracks` (3315–3335), `get_authentic_home_feed` (3337–3386), `get_profile_stats` (3388–3397), `select_avatar` (3399–3418), `create_local_playlist` (3420–3434), `open_local_file` (3436–3459), `_store_artist_binding` (3461–3475), `get_artist_profile` (3477–3513), `get_artists_avatars` (3515–3535), `get_recommendations` (3537–3553), `get_track_wave` (3555–3581), `get_waveform` (3583–3593).
- `core/api.py` L1–520 (bridge core for context: `_install_bridge_error_logging` 401–444, `_offline_bridge_result` 461–512, `_is_ssrf_safe_url` 161–196, `_emit` 1122–1159), L1110–1160 (`open_url`, `_emit`), L2365 (second `_is_ssrf_safe_url` use site), L2513–2572 (`get_playlists`, `get_track_info`), L3740–3795 (adjacent feed methods, for the duplication analysis).

**Frontend (read in full):**
- `ui/web_new_v2/js/lyrics.js` (1–1262) — `loadCurrentTrackLyrics` 764–883, `renderLyrics` 894–1027, `parseLrc` 1029–1057, `toggleTranslation` 43–92, mini-widget 1144–1248.
- `ui/web_new_v2/js/home.js` (1–1049) — `applyCoverBackground` 16–25, `loadHome` 110–213, `backfillHomeCovers` 90–108, `renderAuthenticHome` 292–431, `createFeedCard` 709–789, `applyArtistAvatar`/`requestArtistAvatars` 582–637, `renderArtists` 639–687, `renderTopTracks`/`renderTopArtists` 810–888.
- `ui/web_new_v2/js/artist_profile.js` (1–811) — `renderArtistCandidates` 161–177, `fetchArtistAvatarFromApi` 209–252, `ArtistPhotoComponent` 255–366, `ArtistBioComponent` 369–449, `ArtistAlbumsComponent` 451–548, `loadArtistProfile` 716–808.
- `ui/web_new_v2/js/utils.js` — `escapeHtml` 17–25, `safeCssImageUrl` 40–50, `coverImgHtml` 522–530, `offlineImageUrl` 607–613, `getCoverUrl` 615–648, `createTrackElement` 688–890.
- `ui/web_new_v2/js/player.js` 1722–1746, 2241–2319 (`fetchAndRenderWaveform`); `ui/web_new_v2/js/main.js` 110–171 (`startTrackWave`); `ui/web_new_v2/js/profile.js` 100–188 (`loadProfile`); `ui/web_new_v2/js/events.js` 120–389 (event→UI dispatch table); `ui/web_new_v2/js/home-shell.js` 1–70; `ui/web_new_v2/js/search-discovery.js` 50–127; `ui/web_new_v2/index.html` L10 (CSP).

**Callees traced (other areas — defects there are attributed to the owner, not re-reported here):**
- `services/lyrics_service.py` (1–327) — `translate_lyrics` 243–272, `_LyricsSharedExecutor` 31–88, `_lyrics_pool` (6 workers) 87.
- `services/lyrics_lookup.py` (1–387) — `get` 237–387, provider jobs 346–372, `_read`/`_json` 73–84.
- `services/lyrics_cache.py` (1–109) — `LyricsDiskCache` (bounded, TTL, thread-safe per call).
- `services/recommendation_service.py` (1–917) — `get_charts` 568–624, `get_recommendations` 555–566, `get_wave_for_track` 901–914, `_collect_candidates` 366–449, `_async_recommendation` 481–493.
- `services/artist_service.py` (1–388) — `get_avatars` 329–339, `get_profile` 341–388.
- `services/catalog_service.py` (26–160) — `resolve_artist` 103–151, `_cached` 44–70.
- `services/base_service.py` (1–329) — `_SharedExecutor` 65–119, `BaseMusicService._executor` 124 (class-level, 8 workers, shared).
- `services/soundcloud_service.py` — `get_track_metadata` 493–524, `get_waveform_data_sync` 1018–1055, `waveform_url` capture 338 / 996, `_TTLCache` 17–49.
- `services/youtube_service.py` — `get_track_metadata` 862–892, `_get_ydl_opts` 293–314 (`socket_timeout: 8`, `retries: 1`).
- `core/database.py` — `get_tracks_missing_cover` 1626–1655, `backfill_track_metadata` 1665–1693, `get_most_played` 1695–1706, `get_top_artists` 1708–1721, `add_track` 1054+, index set 350–378.
- `core/offline.py` (1–77) — `is_offline` 10–14.

**Tests read:** `tests/test_verified_lyrics.py`, `tests/test_lyrics_performance.py`, `tests/test_lyrics_netease.py`, `tests/test_catalog_lyrics_ui.py`, `tests/test_profile_view_ui.py`, `tests/test_recommendation_ui.py`, `tests/test_recommendation_bridge.py`, `tests/test_offline_mode.py` (L78–110), `tests/test_frontend_js.py` (L300–315).

**Verification runs:** read-only probes in `%TEMP%` (`wn09_probe.py`) exercising `AppApi.get_waveform`, `AppApi._resolve_track_metadata`, `DatabaseManager.get_tracks_missing_cover` against a throwaway SQLite file in `%TEMP%`. Nothing in the repo or in `~/.nedotify/` was modified.

### 2. Findings

#### F-WN-09-1  [P1] — `get_waveform` fetches an arbitrary, provider-supplied URL with no SSRF check, and reads the response back into the WebView

- **File:** `core/api.py:3583-3593`; `services/soundcloud_service.py:1018-1055`; `ui/web_new_v2/js/player.js:2241-2284`, `ui/web_new_v2/js/player.js:1734`; `services/soundcloud_service.py:338`, `services/soundcloud_service.py:996`
- **Confirmed:** yes
- **Description:** `get_waveform` takes the track dict straight from the WebView and hands `track_data["waveform_url"]` to `SoundCloudService.get_waveform_data_sync`, which performs `requests.get(json_url, timeout=10.0)` on that URL with **no scheme/host validation**, then parses the body as JSON and returns the resulting float list to the frontend. The project already owns an SSRF policy for exactly this class of input (`core/api.py:161 _is_ssrf_safe_url`), applied at `core/api.py:1111` (`open_url`), `core/api.py:2365` (playlist import) and to **every** redirect hop in the proxy (`core/proxy.py:379, 841, 954, 1054`) — but this one bridge sink bypasses it entirely. The URL is not user-typed: it is the raw `waveform_url` string from the SoundCloud API response, carried through the track dict → DB → JS current-track object → back into the bridge.
- **Cause:** The bridge treats a provider payload as a trusted URL. The trust boundary of the pywebview bridge is the WebView, and the URL that crosses it is provider-controlled and never re-validated on the Python side. `requests` also follows redirects by default, so even a public host can 302 the app to an internal address.
- **Trigger conditions:** Any SoundCloud track is played (the URL is then in the DB row), or any script in the WebView calls `window.pywebview.api.get_waveform({waveform_url: "<any url>"})`. The fetch happens on every track change while the progress style is `bars`/`wave`.
- **User impact:** The desktop app can be made to issue HTTP GETs to hosts reachable from the user's machine (LAN router, NAS, printer, `169.254.169.254`), and the JSON response body is parsed and returned into the UI (`data.get('samples')` → list of floats → bridge return value). JSON-speaking internal endpoints can be read back. The app runs on the user's home network, which is exactly what the project SSRF guard exists to protect.
- **Evidence:**
  ```python
  # core/api.py:3583-3593
  def get_waveform(self, track_data: dict):
      """Get sound wave peak amplitude points (0.0..1.0) for waveform scrubber."""
      if not track_data or not isinstance(track_data, dict):
          return []
      waveform_url = track_data.get("waveform_url") or ""
      if waveform_url and hasattr(self._core, "soundcloud"):
          try:
              return self._core.soundcloud.get_waveform_data_sync(waveform_url)
  ```
  ```python
  # services/soundcloud_service.py:1027-1035
  cached = self._waveform_cache.get(json_url)
  if cached is not None:
      return cached
  try:
      r = self._session.get(json_url, timeout=10.0)
      if r.status_code == 200:
          data = r.json()
  ```
  ```python
  # services/soundcloud_service.py:996  — the URL's origin, verbatim from the provider
  waveform_url = item.get('waveform_url') or ''
  ```
- **Reproduction / verification:** `%TEMP%/wn09_probe.py` (run with `& ".venv_win\Scripts\python.exe"`) stubs the SoundCloud client and calls the bridge method directly:
  ```
  === F-WN-09-1: get_waveform forwards an arbitrary URL, no SSRF check ===
  returned: [0.1, 0.2]
  url handed to the HTTP client: ['http://192.168.1.1/status.json']
  ```
  The URL reaches the HTTP client unmodified — no scheme check, no host check, no loopback/private-range check.
- **Suggested fix:** Validate the URL inside `get_waveform` with `_is_ssrf_safe_url` (and/or a SoundCloud-CDN host allow-list) before calling the service, and re-validate after redirects (`allow_redirects=False` + manual re-check, as `core/proxy.py` does). Alternatively, resolve the waveform URL server-side from `source`/`source_id` instead of trusting a URL carried through the UI.
- **Fix side effects:** A host allow-list breaks if SoundCloud rotates its CDN (the Android audit recorded exactly this with `soundcloud.cloud`), so the policy needs a maintenance path; a scheme-only check would still leave LAN hosts reachable.
- **Discovered by:** B

#### F-WN-09-2  [P2] — `fetch_missing_covers` runs N sequential provider lookups on one bridge thread and re-scans the same unresolvable rows forever

- **File:** `core/api.py:3227-3284`; `core/database.py:1626-1655`; `services/youtube_service.py:862-892`; `ui/web_new_v2/js/home.js:90-108`
- **Confirmed:** yes for the sequential fan-out and the row starvation; the *existence* of affected rows in any given user's DB is a hypothesis (see Coverage gaps).
- **Description:** Two defects in one method. (a) `fetch_missing_covers` resolves up to `limit` rows **one at a time** in a plain `for` loop on the bridge thread. For `source == 'youtube'` each row is a full `yt_dlp` `extract_info()` (`socket_timeout: 8`, `retries: 1`), so 40 rows can hold the bridge thread for minutes; `library_updated` is emitted only after the whole batch (`core/api.py:3263-3264`), so the grid keeps showing placeholders until the very end. (b) The selection query covers **every** non-local provider (`AND source != 'local'`, `core/database.py:1648`) and orders `id DESC LIMIT 40`, but `_resolve_track_metadata` only knows `soundcloud` and `youtube` (`core/api.py:3269-3273`) and the result is persisted **only when a cover was found** (`core/api.py:3252-3253`). A row from any other provider — or a YouTube row whose video was deleted — is therefore re-selected on every pass, always at the head of the id-descending window, so the backfill can never advance past it and older rows never get artwork.
- **Cause:** The backfill has no notion of "unresolvable": the row set is recomputed from scratch each pass, with no negative-cache/mark-as-tried column and no ordering that skips known-bad rows.
- **Trigger conditions:** A library containing rows with a missing cover or a placeholder `title`/`artist` from a provider other than YouTube/SoundCloud (e.g. `yandex`, `vk`, `spotify` — `core/database.py:1057` defaults `artist` to `'Unknown Artist'` on insert, and `core/api.py:2522` inserts with that default), or any deleted YouTube video.
- **User impact:** Home/library tiles stay empty for exactly the rows that need the backfill, and every 5-minute home reload re-runs up to 40 provider round-trips for nothing. The user sees a permanent placeholder grid with no indication that a background job is running.
- **Evidence:**
  ```python
  # core/api.py:3241-3262
  updated = 0
  for row in rows:
      source = (row.get("source") or "").lower()
      source_id = str(row.get("source_id") or "").strip()
      if not source or not source_id:
          continue
      try:
          extra = self._resolve_track_metadata(source, source_id)
      except Exception:
          ...
      cover = str(extra.get("cover_url") or "")
      if cover:                       # <-- nothing is persisted without a cover
          try:
              self._core.db.backfill_track_metadata(...)
  ```
  ```python
  # core/api.py:3267-3281 — closed set of providers
  if source == "soundcloud":  svc = getattr(self._core, "soundcloud", None)
  elif source == "youtube":   svc = getattr(self._core, "youtube", None)
  getter = getattr(svc, "get_track_metadata", None) if svc else None
  if not callable(getter): return {}
  ```
  ```sql
  -- core/database.py:1643-1651
  WHERE ( (cover_path IS NULL AND (cover_url IS NULL OR cover_url = ''))
       OR title IS NULL OR title IN ('', 'Unknown', 'Unknown Title')
       OR artist IS NULL OR artist IN ('', 'Unknown', 'Unknown Artist') )
    AND source IS NOT NULL AND source != 'local'
    AND source_id IS NOT NULL AND source_id != ''
  ORDER BY id DESC LIMIT ?
  ```
- **Reproduction / verification:** `%TEMP%/wn09_probe.py` inserted one `yandex` row and one `youtube` row into a throwaway SQLite DB and called `get_tracks_missing_cover` twice:
  ```
  selected rows: [(2, 'youtube'), (1, 'yandex')]
  _resolve_track_metadata('yandex', ...) -> {}
  second pass selects: [(2, 'youtube'), (1, 'yandex')]
  ```
  The `yandex` row is selected, is unresolvable, and comes back on the next pass. Combined with `ORDER BY id DESC LIMIT 40` it permanently occupies a slot in the window.
- **Suggested fix:** (i) fan the lookups out over a bounded executor with a per-call deadline instead of a serial loop; (ii) make the resolver a provider protocol (`get_track_metadata` on the service that owns the source) so the closed `if/elif` set in the bridge disappears; (iii) persist a negative marker (or advance a cursor) for rows that could not be resolved so the window moves past them.
- **Fix side effects:** Parallel lookups multiply provider load and can trip rate limits — the pool must stay small and the total per-pass budget bounded; a negative marker needs a schema column (or reuse of the existing placeholder fields) and interacts with the `core/database.py` dedup migration.
- **Discovered by:** B

#### F-WN-09-3  [P2] — `get_artists_avatars` is an N+1 over the shared 8-worker provider pool with no cancellation

- **File:** `core/api.py:3515-3535`; `services/artist_service.py:329-339`; `services/catalog_service.py:103-151`; `services/base_service.py:124`
- **Confirmed:** yes
- **Description:** One bridge call resolves up to 30 artist names. `ArtistService.get_avatars` loops over the names **sequentially**, calling `catalog.resolve_artist(name)` for each; a miss is a YT Music artist search (8 s deadline) with an iTunes fallback, a hit is cached 900 s but a miss only 60 s (`services/catalog_service.py:64`). The whole task is submitted to `BaseMusicService.submit` → the **class-level** `_SharedExecutor(max_workers=8)` shared with `RecommendationService` and `CatalogService` (`services/base_service.py:124`). There is no `is_current` handle and no cancellation: the task runs to completion (up to 30 × 8 s ≈ 240 s) even after the user has navigated away from the page that asked for it.
- **Cause:** The batch API has the shape of a single-item API. The bridge passes a list to a service method that treats it as a loop, and the service offers no per-item parallelism or deadline of its own.
- **Trigger conditions:** Opening the home page or the search page with ≥10 distinct artists in the top list/history — `ui/web_new_v2/js/home.js:686` and `:887` both call `requestArtistAvatars(...)`, and `ui/web_new_v2/js/search-discovery.js:65` calls it for every history artist.
- **User impact:** One of the eight shared provider workers is occupied for minutes, and concurrent `get_charts` / `get_releases` / `get_mixes` tasks (`services/recommendation_service.py:624, 674, 689`) queue behind it — the home sections then time out (the 20 s retry button at `ui/web_new_v2/js/home.js:71-74`) even though the providers are healthy.
- **Evidence:**
  ```python
  # services/artist_service.py:329-339
  def get_avatars(self, names, callback=None):
      def task():
          mapping = {}
          for name in list(dict.fromkeys(n.strip() for n in names or [] if isinstance(n, str) and n.strip()))[:30]:
              resolved = self.catalog.resolve_artist(name)
              raw = resolved.get('profile_data') or {}
              mapping[name] = self._best_thumbnail(raw) if resolved.get('status') == 'found' and resolved.get('source') == 'youtube' else ''
          if callback: callback(mapping)
      if self.submit(task) is None and callback: callback({})
  ```
  ```python
  # core/api.py:3530-3531
  svc.get_avatars([n for n in names if isinstance(n, str)][:30], callback=_done)
  ```
  ```python
  # services/base_service.py:124  — one pool for ArtistService + RecommendationService + CatalogService
  _executor = _SharedExecutor(max_workers=8)
  ```
- **Reproduction / verification:** The sequential loop is confirmed by `inspect.getsource(ArtistService.get_avatars)` in `%TEMP%/wn09_probe.py` (output reproduced verbatim in the finding). The shared pool is confirmed by grep: `services/base_service.py:124` is the only class-level executor, and `services/artist_service.py` sets no instance `_executor` (unlike `youtube_service.py:195`, `soundcloud_service.py:132`, `spotify_service.py:100`, `yandex_service.py:30`).
- **Suggested fix:** Resolve the batch in parallel over a dedicated bounded pool (the `catalog_service._catalog_pool` already exists with 4 workers), give the batch an overall deadline, and add an `is_current` predicate so a superseded request stops early.
- **Fix side effects:** Parallel YT Music searches raise the provider's rate-limit exposure; the per-name budget and the pool size must stay small, and negative caching (currently 60 s) becomes more important.
- **Discovered by:** B

#### F-WN-09-4  [P2] — `get_lyrics` spawns an unbounded thread per request and a superseded cascade keeps the shared lyrics pool occupied

- **File:** `core/api.py:3192-3225`; `services/lyrics_lookup.py:346-372`; `services/lyrics_service.py:87`
- **Confirmed:** yes
- **Description:** Every `get_lyrics` call creates a new OS thread (`threading.Thread(target=run, daemon=True, name=f'Lyrics-{cascade_no}').start()`, `core/api.py:3224`) — there is no pool and no bound. The cascade counter makes only the newest request publish (`current()` = `cascade_no == self._lyrics_cascade_count`), but the superseded request's provider work is **not** cancelled: `services/lyrics_lookup.py:346-352` submits up to 11 provider jobs to the shared 6-worker lyrics pool, and they are only cancelled in the owner's `finally` block (`services/lyrics_lookup.py:381-382`) after the owner has waited up to `BUDGET = 8.0` s (`services/lyrics_lookup.py:358`). So each superseded request keeps the 6 pool slots busy for up to 8 s.
- **Cause:** Staleness is expressed as "the newest request wins" instead of "cancel the previous one". The bridge has no cancellation channel into the service, so a dead request's network work is only reaped when its own deadline expires.
- **Trigger conditions:** Fast track skipping, or the duration-refresh path in `ui/web_new_v2/js/lyrics.js:308-310` (`nedotify:position_changed` → `loadCurrentTrackLyrics(durationMs)`), which issues a second request whenever the first was started without a duration.
- **User impact:** Rapid skipping saturates the 6-worker lyrics pool with stale cascades, so the *current* track's lyrics queue behind dead requests and arrive late (the UI shows "Ищем текст..." for seconds); in the worst case the pool is fully occupied by superseded requests. The global "newest wins" rule also means any second lyrics request from anywhere in the app silently discards the first one's result.
- **Evidence:**
  ```python
  # core/api.py:3196-3201, 3224
  with self._lyrics_lock:
      self._lyrics_cascade_count += 1
      cascade_no = self._lyrics_cascade_count
  def current():
      with self._lyrics_lock:
          return cascade_no == self._lyrics_cascade_count
  ...
  threading.Thread(target=run, daemon=True, name=f'Lyrics-{cascade_no}').start()
  ```
  ```python
  # services/lyrics_lookup.py:346-352  (jobs are submitted, not cancellable from outside)
  jobs = [(self.lrclib, forms[0]), (self.netease, forms[0]), (self.genius, forms[0])]
  jobs += [(self.lrclib, f) for f in forms[1:]]
  jobs += [(self.qqmusic, forms[0]), (self.megalobiz, forms[0])]
  jobs += [(self.netease, f) for f in forms[1:]]
  for provider, form in jobs:
      future = self.service.submit(run, provider, form)
  ```
  ```python
  # services/lyrics_service.py:87
  _lyrics_pool = _LyricsSharedExecutor(max_workers=6, thread_name_prefix="LyricsPool")
  ```
- **Reproduction / verification:** Static: the cascade counter is only compared for equality, so an older request can never publish again (`core/api.py:3199-3201`), and no code path cancels the provider futures of a superseded request before the 8 s budget expires (`services/lyrics_lookup.py:358-382`). A runtime repro: call `api.get_lyrics('A','B')` twice in a row within < 1 s with a provider stubbed to sleep 5 s, and observe that the first call's provider job is still running (and holding a pool slot) after the second request was issued.
- **Suggested fix:** Give the bridge a cancellation handle (the service already threads an `is_current` predicate into `LyricsLookup.get`) and have the superseded request cancel its own futures immediately; run the per-request body on a bounded pool instead of a fresh thread.
- **Fix side effects:** Cancelling on supersede must not poison the negative cache — `services/lyrics_lookup.py:354-357` already distinguishes "executor refused" from "not found", and the same distinction is needed for "cancelled".
- **Discovered by:** B

#### F-WN-09-5  [P2] — `get_popular_tracks(region)` silently drops the region; the section is always the global Last.fm chart

- **File:** `core/api.py:3315-3335`; `services/recommendation_service.py:568-624`
- **Confirmed:** yes
- **Description:** `get_popular_tracks` forwards `region` as the first positional argument to `RecommendationService.get_charts(region, callback=...)`. `get_charts` accepts it as `country` and **never reads it** — the body only calls `self.lastfm.chart.getTopTracks(limit=max_results * 2)`, which is the global chart. The parameter is dead. Two secondary defects in the same method: the `fallback = self._core.db.get_history(limit=10)` query is executed on every call even though it is only used on the exception path, and that fallback emits **raw DB history rows**, which have a different shape from the `_format_ui_track` UI rows the normal path emits.
- **Cause:** The bridge presents a parameter that the service contract does not honour, so a caller cannot tell from the API that the region is ignored; there is no region validation *and* no region support.
- **Trigger conditions:** Any call to `get_popular_tracks` — the frontend currently calls it with no argument (`ui/web_new_v2/js/home.js:177`), so the home "Популярное" section is always the same global chart. `tools/bench/bench_child.py:173` calls it with `'US'`.
- **User impact:** The "Популярное" tile never reflects the user's region, and the bridge advertises a filter that cannot be honoured — a caller who passes `'RU'` silently receives the global chart with no indication. The fallback path also renders rows shaped differently from the normal path (no `source_id`/`cover_url` normalisation), which can produce empty tiles in the fallback state.
- **Evidence:**
  ```python
  # core/api.py:3315-3335
  def get_popular_tracks(self, region: str = "US"):
      fallback = self._core.db.get_history(limit=10) or []      # always executed
      try:
          provider = getattr(self._core.recommendations, "get_charts", None)
          if provider:
              provider(region, callback=lambda tracks: self._emit("popular_results", tracks or []))
  ```
  ```python
  # services/recommendation_service.py:568-572
  def get_charts(self, country='US', max_results=20, callback=None, error_callback=None):
      def _task():
          tracks = []
          try:
              chart_raw = self.lastfm.chart.getTopTracks(limit=max_results * 2) if hasattr(self, 'lastfm') and self.lastfm else []
  ```
- **Reproduction / verification:** `%TEMP%/wn09_probe.py` inspects the source of `RecommendationService.get_charts`:
  ```
  'country' referenced in get_charts body: True
      def get_charts(self, country='US', max_results=20, callback=None, error_callback=None):
  ```
  The only occurrence of `country` is the parameter in the signature — it is never read in the body.
- **Suggested fix:** Either implement region support in `get_charts` (Last.fm `chart.getTopTracks` takes a `country`/page argument — the parameter exists upstream) or remove `region` from the bridge signature so the API stops advertising a filter it cannot honour. Validate against a known country-code list if it is kept. Move the `fallback` query inside the `except` branch and normalise the fallback rows through `_format_ui_track`.
- **Fix side effects:** Last.fm's chart endpoint is global-only for anonymous accounts, so "implement it" may not be possible without an API key; in that case removing the parameter is the honest fix. Normalising the fallback rows changes what the fallback event payload contains — `ui/web_new_v2/js/events.js:163-169` accepts both a list and `{tracks: [...]}`.
- **Discovered by:** B

#### F-WN-09-6  [P2] — `get_waveform` is a synchronous, uncancellable 10 s HTTP request on every track change, and it ignores offline mode

- **File:** `core/api.py:3583-3593`; `services/soundcloud_service.py:1018-1055`; `ui/web_new_v2/js/player.js:1734`, `ui/web_new_v2/js/player.js:2241-2284`; `core/api.py:461-512`
- **Confirmed:** yes
- **Description:** The peak analysis itself is fine — SoundCloud ships pre-computed peaks, so there is **no** FFT/decode in Python, and the normalised result is cached (`_TTLCache(max_entries=100, ttl_seconds=600)`, thread-safe, `services/soundcloud_service.py:141-142`, `:1027-1050`). The defect is the transport: `get_waveform` is a synchronous bridge method that performs the HTTP GET inline with `timeout=10.0`, and `fetchAndRenderWaveform(track)` is invoked from the track-change handler (`ui/web_new_v2/js/player.js:1734`), so every new SoundCloud track issues a fresh request. The frontend discards a stale answer with `if (requestId !== waveformRequestId) return;` (`ui/web_new_v2/js/player.js:2276`) — but the HTTP request has already been made and is not cancelled. Separately, `get_waveform` is **not** in the bridge's offline interception table (`core/api.py:461-512` lists `get_feed`, `get_popular_tracks`, `get_authentic_home_feed`, `get_home_releases`, `get_home_mixes`, `get_artist_profile`, `get_artists_avatars`, `fetch_missing_covers`, `get_album_tracks`, `get_album_details`, `get_flow_tracks`, `get_recommendations`, `get_yt_playlist_tracks`, `get_track_wave`, `get_playlist_tracks`, `prefetch_track`, `get_lyrics_translation`, …), and `services/soundcloud_service.py` contains no `is_offline` check of its own.
- **Cause:** A remote-fetching method was added to the bridge as a plain synchronous call, bypassing the offline-interception convention that every other network-touching bridge method follows; and the cache key is the URL, so a cache miss on a new track always costs a full round trip.
- **Trigger conditions:** Progress style `bars`/`wave` (the default, `ui/web_new_v2/js/player.js:2244-2245`) and any track change to a SoundCloud track not already in the 10-minute/100-entry cache. With `network.offline_mode = true`, the outbound request still happens.
- **User impact:** The waveform scrubber renders nothing (the player falls back to a pseudo-waveform) for up to 10 s on a slow or blocked network; in offline mode the app still makes an outbound HTTPS request, contradicting the offline contract that the rest of the bridge honours, and the request adds up to 10 s of latency to every track change.
- **Evidence:**
  ```python
  # services/soundcloud_service.py:1031-1033
  try:
      r = self._session.get(json_url, timeout=10.0)
  ```
  ```python
  # core/api.py:502 — the offline table covers its neighbours but not get_waveform
  if method in ('prefetch_track', 'get_lyrics_translation', 'check_zapret_update', 'update_zapret'):
      return True, None
  ```
  ```javascript
  // ui/web_new_v2/js/player.js:1734 — every track change
  fetchAndRenderWaveform(track);
  ```
- **Reproduction / verification:** Grep `core/api.py` for `get_waveform` → the only hits are the method definition (3583) and its body (3590); the interception table (`core/api.py:461-512`) contains no `get_waveform` entry. Grep `services/soundcloud_service.py` for `is_offline` → no matches. `tests/test_offline_mode.py:99-110` covers `get_album_tracks`, `get_album_details` and `get_track_wave` under offline mode but not `get_waveform`.
- **Suggested fix:** Move the fetch off the bridge thread (submit to an executor and publish the result through an event, like the other waveform-like surfaces) or add `get_waveform` to the offline interception table and return `[]`; keep the existing TTL cache.
- **Fix side effects:** An event-based waveform needs a correlation id in the frontend (the existing `waveformRequestId` already provides one), and the pseudo-waveform fallback in `ui/web_new_v2/js/player.js:2281` must remain the default until the real peaks arrive.
- **Discovered by:** B

#### F-WN-09-7  [P3] — `get_lyrics_translation` returns three different shapes and silently returns untranslated text

- **File:** `core/api.py:3286-3291`; `services/lyrics_service.py:243-272`; `ui/web_new_v2/js/lyrics.js:63-84`
- **Confirmed:** yes
- **Description:** The bridge method returns `str` on success, `{"error": str(e)}` on exception, and `None` under offline mode (`core/api.py:502`) — three shapes for one method. The frontend branches on `typeof res === 'string'` and otherwise assigns the value straight into the translation map (`currentTranslationMap = res || {}`), so the error dict becomes a map with one bogus key and no line ever matches: the translation pane stays empty and **no error is shown to the user**. Worse, the callee swallows its own failures and returns the **original** text (`services/lyrics_service.py:269` `return "\n".join(out) if out else lyrics` and `:272` `return lyrics`), so a provider outage makes the app render the untranslated original in the translation slot (the map then pairs each line with itself) while the user believes it is translated.
- **Cause:** The bridge does not normalise the callee's return type, and the callee uses "return the input unchanged" as its error fallback — a value that is indistinguishable from a successful translation in the payload.
- **Trigger conditions:** Any translation toggle while the Google endpoint is unreachable/rate-limited (the code comments themselves note the endpoint is rate-limited), or any exception in `translate_lyrics`.
- **User impact:** Silent, misleading UI: the translation row appears to be populated but shows the source text, or shows nothing with no error message.
- **Evidence:**
  ```python
  # core/api.py:3286-3291
  def get_lyrics_translation(self, lyrics_text: str, target_lang: str = "ru"):
      try:
          return self._core.lyrics.translate_lyrics(lyrics_text, target_lang=target_lang)
      except Exception as e:
          return {"error": str(e)}
  ```
  ```python
  # services/lyrics_service.py:269-272
          return "\n".join(out) if out else lyrics
      except Exception as e:
          logger.debug(f"Translation error: {e}")
          return lyrics
  ```
  ```javascript
  // ui/web_new_v2/js/lyrics.js:81-83
  } else {
      currentTranslationMap = res || {};
  }
  ```
- **Reproduction / verification:** Call `api.get_lyrics_translation("hello", "ru")` with `self._core.lyrics.translate_lyrics` raising → the return value is `{'error': '...'}`; feed that into `currentTranslationMap` in `ui/web_new_v2/js/lyrics.js` → `currentTranslationMap[line.text]` is `undefined` for every real line, so `subEl` is never appended.
- **Suggested fix:** Make the bridge method always return a dict with an explicit status (`{"ok": bool, "text": str, "error": str|None}`) and have the callee distinguish "translation failed" from "input unchanged" (e.g. return `None` on failure instead of the original text). Note: the "return the original" fallback itself is a callee defect owned by WN-22 (`services/lyrics_service.py`) — only the bridge's type divergence and the frontend's silent branch are this area's.
- **Fix side effects:** Changing the return type touches `ui/web_new_v2/js/lyrics.js:63-84` and the offline branch at `core/api.py:502`; the offline path currently returns `None` and the frontend already treats that as "no translation".
- **Discovered by:** B

#### F-WN-09-8  [P3] — `get_authentic_home_feed` is unreachable bridge surface with a per-item DB lookup

- **File:** `core/api.py:3337-3386`; `ui/web_new_v2/js/events.js:139-143`
- **Confirmed:** yes
- **Description:** No frontend code calls `get_authentic_home_feed`. `ui/web_new_v2/js/home.js:176-193` requests `get_popular_tracks`, `get_feed`, `get_home_releases` and `get_home_mixes` instead, and `tests/test_recommendation_ui.py:54,71` explicitly asserts that `get_authentic_home_feed` is *not* called. The method is nevertheless live surface: it is in the offline interception table (`core/api.py:465`), it has a dedicated event handler (`ui/web_new_v2/js/events.js:139-143` and `ui/web_new_v2/js/main.js:679`), and it is maintained. It also performs one DB lookup **per feed item** via `self._enrich_track_lufs(item_copy)` (`core/api.py:3352` → `core/api.py:1172-1191` → `db.get_track` / `get_track_by_path` / `get_track_by_source_id`).
- **Cause:** The home-feed redesign replaced the "authentic feed" with the four staggered sections but the old bridge method was never removed; the god-object surface (`AppApi` has 174 methods, 136 public) makes it cheap to leave dead methods behind.
- **Trigger conditions:** None from the shipped UI — the method is only reachable by a script in the WebView or by a future caller.
- **User impact:** None directly today; the cost is maintenance and risk: a 50-line bridge method with its own formatting/enrichment logic that duplicates `get_feed`'s responsibilities, plus an N+1 that would fire if it were ever wired up.
- **Evidence:**
  ```python
  # core/api.py:3345-3354
  def _format_section_items(items):
      formatted = []
      for it in (items or []):
          if isinstance(it, dict):
              item_copy = dict(it)
              if "type" not in item_copy:
                  item_copy["type"] = "track"
              self._enrich_track_lufs(item_copy)      # one DB lookup per item
              formatted.append(item_copy)
      return formatted
  ```
  ```javascript
  // ui/web_new_v2/js/home.js:176-193 — the four sections that replaced it
  requestHomeSection('home-popular', 'get_popular_tracks');
  await delay(75); requestHomeSection('home-recommended', 'get_feed', [10]);
  await delay(75); requestHomeSection('home-releases', 'get_home_releases', [10]);
  await delay(75); requestHomeSection('home-mixes', 'get_home_mixes', [10]);
  ```
- **Reproduction / verification:** Grep the whole repo for `get_authentic_home_feed` → only `core/api.py:465/3337/3370/3373/3375/3382/3384/3385` and `tests/test_recommendation_ui.py:54`; no `ui/web_new_v2/**` call site.
- **Suggested fix:** Delete `get_authentic_home_feed` together with the `authentic_home_ready` event plumbing, or wire it and remove the four-section path — but not both. If it stays, drop the per-item `_enrich_track_lufs` in favour of one bulk query.
- **Fix side effects:** Removing the method also removes the offline-interception entry (`core/api.py:465`) and the `authentic_home_ready` case in `ui/web_new_v2/js/events.js:139`; `tests/test_frontend_js.py:233` references the event name list and would need updating.
- **Discovered by:** B

#### F-WN-09-9  [P3] — `get_recommendations` is unreachable bridge surface and discards a late provider result

- **File:** `core/api.py:3537-3553`; `services/recommendation_service.py:555-566`
- **Confirmed:** yes
- **Description:** No frontend code calls `get_recommendations` — the flow feature uses `get_flow_tracks` (`ui/web_new_v2/js/player.js:1526, 1553`). The method blocks the bridge thread for up to 3 s (`evt.wait(timeout=3.0)`) and, because the result list is filled by a worker callback, any answer that arrives **after** the 3 s deadline is written into `res` *after* the bridge has already returned `res[:max_results]` — the recommendation is silently lost.
- **Cause:** A synchronous bridge method wrapping an asynchronous provider, with the timeout implemented as "give up waiting" rather than "cancel the provider".
- **Trigger conditions:** Only a direct caller (the flow feature uses a different method); the provider answering later than 3 s.
- **User impact:** None from the shipped UI (dead method); the pattern is a trap for the next caller, and it is the only place in this area where a bridge method waits on an event without a correlation id.
- **Evidence:**
  ```python
  # core/api.py:3537-3553
  def get_recommendations(self, track_data: dict, max_results: int = 10):
      res = []
      evt = threading.Event()
      def callback(tracks):
          if tracks: res.extend(tracks)
          evt.set()
      try:
          self._core.recommendations.get_recommendations(
              track_data, max_results=max_results, callback=callback,
              error_callback=lambda _error: evt.set(),
          )
          evt.wait(timeout=3.0)
      except Exception as e:
          logger.error(f"Error in get_recommendations: {e}")
      return res[:max_results]
  ```
- **Reproduction / verification:** Grep `ui/web_new_v2/**` for `get_recommendations` → no hits (only `get_flow_tracks` in `ui/web_new_v2/js/player.js:1526`). `tests/test_recommendation_bridge.py:8-18` exercises the method with a provider that calls back synchronously, so the late-answer path is untested.
- **Suggested fix:** Delete the method (the flow path uses `get_flow_tracks`), or convert it to the event contract used by `get_track_wave` (`request_id` + `track_wave_ready`-style event) so a late answer is not lost.
- **Fix side effects:** `tests/test_recommendation_bridge.py:8-18` pins the current synchronous behaviour and would have to be rewritten or removed.
- **Discovered by:** B

### 3. Clean areas

- **XSS — lyrics and translations.** Every untrusted string in the lyrics chain is written with `textContent`, never `innerHTML`: `ui/web_new_v2/js/lyrics.js:953` (`origSpan.textContent = line.text`), `:959` and `:1013` (`subEl.textContent = currentTranslationMap[line.text]`), `:1009` (`el.textContent = line`), `:1236-1241` (mini-widget lines). The only `innerHTML` uses in the lyrics renderer interpolate fixed strings (`:781`, `:813`, `:907`, `:933`, `:1002` — `message` is a literal). Third-party LRC/HTML text is stripped server-side (`services/lyrics_lookup.py:189, 202` `html.unescape(re.sub(r'<[^>]+>', '', ...))`) before it reaches the UI. **No injection path found** from lyrics or translated lyrics to script execution.
- **XSS — cover art and artist images.** The image sink is centralised and safe: `ui/web_new_v2/js/utils.js:522-530` `coverImgHtml` escapes `src` with `escapeHtml` (`utils.js:17-25`, which escapes `& < > " '`), and the CSS sink is `utils.js:40-50` `safeCssImageUrl`, which enforces an `https:`/`data:` scheme allow-list *and* strips `'"()\;` — the characters `escapeHtml` cannot neutralise inside a CSS `url()` token. `ui/web_new_v2/js/utils.js:615-648` `getCoverUrl` prefixes non-URL values with `https://`, so a `javascript:` payload cannot survive as a scheme. `ui/web_new_v2/js/artist_profile.js:170, 480` escape the URL into the `src` attribute; `ui/web_new_v2/js/home.js:582-598` and `artist_profile.js:279` assign to `img.src` (a URL in an `<img>` never executes script). `ui/web_new_v2/index.html:10` adds `script-src 'self'` (no `unsafe-inline`), `object-src 'none'`, `base-uri 'none'` — inline handlers injected through an attribute break-out would not run even if one existed. **No injection path found.**
- **`ui/web_new_v2/js/home.js:16-25` `applyCoverBackground`** (CSS `url()` injection) is safe despite not reusing `safeCssImageUrl`: it parses with `new URL()` (which percent-encodes `"` and newlines, and normalises `\`), allow-lists `https:`/`data:`, and interpolates into a double-quoted CSS string where `)` and `;` are inert. It is nonetheless a duplicated policy — see ARCH-5.
- **Lyrics identity verification and caching** (`services/lyrics_lookup.py:40-71` `accept`, `:225-235` `_remember`, `services/lyrics_cache.py:39-57` `valid`) is well built: the disk cache rejects malformed/unverified payloads, is byte- and entry-bounded, and `tests/test_lyrics_performance.py` pins the identity/timing rules. The in-memory cache and the in-flight map share the service's single `_cache_lock` (`services/lyrics_service.py:183`, `services/lyrics_lookup.py:260, 290, 383`) — it does not open a second lock, satisfying the repo rule.
- **Offline interception is applied to most of this area.** `core/api.py:461-512` short-circuits `get_feed`, `get_popular_tracks`, `get_authentic_home_feed`, `get_home_releases`, `get_home_mixes`, `get_artist_profile`, `get_artists_avatars`, `fetch_missing_covers`, `get_album_tracks`, `get_album_details`, `get_flow_tracks`, `get_recommendations`, `get_yt_playlist_tracks`, `get_track_wave`, `get_playlist_tracks`, `prefetch_track`, `get_lyrics_translation` and the download entry points — no provider is contacted in offline mode. (`get_waveform` is the one gap — F-WN-09-6.)
- **`get_home_data` (`core/api.py:3293-3313`) is cheap and correctly shaped.** Seven indexed local queries (`core/database.py:367` `idx_tracks_play_count`, `:351-352` `idx_tracks_favorite/artist`); no network. The payload keys match the frontend exactly: `history` (with the `track_id → id` alias the consumers expect), `favorites_count`, `total_listening_ms`, `total_tracks`, `playlists`, `analytics.{total_time_seconds,top_tracks,top_artists}` — consumed at `ui/web_new_v2/js/home.js:118-134`, `ui/web_new_v2/js/home-shell.js:12`. `get_profile_stats` (`core/api.py:3388-3397`) matches `ui/web_new_v2/js/profile.js:138-144` (`total_tracks`, `favorite_count`, `playlist_count`, `total_listening_time_ms`, `recently_played`). The only divergence is cosmetic: `get_profile_stats` also returns `most_played`, which no frontend code reads.
- **`get_lyrics` result freshness is coherent.** `revision` + `phase` (`partial` → `final`) are threaded through the service (`services/lyrics_lookup.py:296-297`) and the frontend enforces monotonic revisions (`ui/web_new_v2/js/lyrics.js:896-897`); `tests/test_verified_lyrics.py:132-144` and `tests/test_catalog_lyrics_ui.py:5-41` pin both ends of that contract. The `request_id` round-trip (`core/api.py:3206`, `ui/web_new_v2/js/lyrics.js:314`) matches.
- **`get_artist_profile` correlation works.** `core/api.py:3477-3513` echoes `request_id` and drops superseded results via `current()`; the frontend matches on `request_id` (`ui/web_new_v2/js/artist_profile.js:146`) and `tests/test_catalog_lyrics_ui.py:65-83` pins it.
- **`get_track_wave` request-id contract works.** `core/api.py:3555-3581` always publishes a `track_wave_ready` event (including for invalid input and for provider errors), so the frontend's 25 s deadline is never the only way out; `tests/test_recommendation_bridge.py:68-99` pins the out-of-order and legacy-payload cases.
- **`_emit` is not on the UI thread** (`core/api.py:1147-1154`) and serialises the payload inside the guard (`core/api.py:1131-1139`) — the repo's non-negotiable rules are honoured by every method in this area.

### 4. Coverage gaps

- **Live provider behaviour was not exercised.** The `network` marker is deselected by default and I did not run the app (it would disturb the user's profile). The measured cost of `fetch_missing_covers` (40 × yt-dlp `extract_info`) and of `get_artists_avatars` (30 × YT Music search) is therefore an upper bound derived from the code and the configured timeouts (`services/youtube_service.py:310-313` `socket_timeout: 8`, `retries: 1`; `services/catalog_service.py:104` 8 s deadline), not a measurement. Confirming would need a stubbed provider that sleeps a realistic amount.
- **The existence of "unresolvable" rows** (F-WN-09-2) depends on the user's database. I proved that *if* such a row exists it is re-selected forever and starves the window; I did not inspect any real `~/.nedotify/nedotify_storage.db` (forbidden). A read-only query on a user DB — `SELECT source, COUNT(*) FROM tracks WHERE source NOT IN ('local','youtube','soundcloud') AND (cover_url IS NULL OR artist IN ('','Unknown','Unknown Artist')) GROUP BY source` — would confirm the population.
- **`get_waveform` SSRF impact (F-WN-09-1) was not exercised against a real host.** I verified that the URL is forwarded unmodified to the HTTP client with a stub; the actual reachability of LAN/metadata endpoints from the user's machine, and whether a specific provider could be made to return an internal URL, is untested.
- **Browser-level XSS was not executed.** The analysis is a static read of the DOM sinks; no WebView2 run was performed. `tools/visual_guard/` was not used.
- **`select_avatar` (`core/api.py:3399-3418`), `create_local_playlist` (3420–3434), `open_local_file` (3436–3459) and `_store_artist_binding` (3461–3475)** fall inside the reviewed line range but outside the named method list, so they were only read in passing. `select_avatar` copies the user-chosen file into the avatars cache dir and stores the path for the proxy's `/api/avatar` route to serve — the path-validation contract lives in `core/proxy.py` (WN-11) and was not audited here.
- **No test exists for `fetch_missing_covers`, `get_artists_avatars`, `get_waveform`, `get_home_data`, `get_popular_tracks`, `get_profile_stats` or `get_lyrics_translation`** at the bridge level. `tests/test_frontend_js.py:304-312` only asserts that the names exist in the source; `tests/test_recommendation_ui.py:47-77` stubs `fetch_missing_covers` with a never-resolving promise, so the backend behaviour is entirely unpinned.

### 5. Architecture improvements (ARCH)

- **ARCH-1 — `AppApi` is a god object (174 methods, 136 public, 4228 lines) and this area is a symptom.** Thirteen bridge methods live in a 400-line window, each re-implementing the same "call a service → publish an event → fall back" template. Five of them are near-identical: `get_popular_tracks` (`core/api.py:3315`), `get_authentic_home_feed` (`:3337`), `get_feed` (`:3740`), `get_home_releases` (`:3765`), `get_home_mixes` (`:3782`) — same try/except, same `callback=`/`error_callback=` plumbing, same "emit an empty list on failure". The last three are owned by WN-10; the duplication spans both areas and should be fixed once. *Direction:* one helper (e.g. `AppApi._publish_feed(method, event, *args, **kwargs)`) or, better, a service-level API that already owns the callback convention (`services/base_service.py:140-161` `_join_request`).
- **ARCH-2 — there is no cross-cutting request-correlation contract; each async method invents its own.** `get_lyrics` uses a dedicated counter + `_lyrics_lock` (`core/api.py:3196-3201`); `get_artist_profile` stores its id in `self._artist_request_id` **guarded by `_window_op_lock`** — a window-operation lock (`core/api.py:353`, used for minimise/restore/maximise), so a request-id field is coupled to window state; `get_track_wave` treats `request_id` as correlation-only with no Python-side staleness check; `get_artists_avatars` and `get_home_data` have no correlation at all. *Direction:* a single `RequestGate` (per-key latest-id + `is_current()` predicate) used by every async bridge method, replacing `_lyrics_cascade_count`, `_artist_request_id` and the ad-hoc `request_id` echoes.
- **ARCH-3 — the bridge re-implements provider dispatch instead of using a provider protocol.** `_resolve_track_metadata` (`core/api.py:3267-3281`) is a closed `if/elif` over provider names inside the bridge, even though `services/youtube_service.py:862` and `services/soundcloud_service.py:493` already expose a uniform `get_track_metadata(source_id)` method. Any provider that does not implement it (yandex, vk, spotify) is silently unreachable from the backfill — the root cause of F-WN-09-2(b). *Direction:* a `get_track_metadata` protocol on the provider services, with the bridge asking `self._core.service_for_source(source)`.
- **ARCH-4 — the bridge re-implements the service callback/executor conventions.** `core/api.py` opens its own threads (`core/api.py:3224`), its own `threading.Event` waits (`core/api.py:3550`), and its own executors (`_search_executor`, `_prefetch_executor`, `core/api.py:363-370`) while `services/base_service.py` and `services/lyrics_service.py` already provide `submit()` / `_join_request()` / bounded pools. *Direction:* one lifecycle-managed worker facility owned by `AppCore`; bridge methods should describe *what* they want, not how it is scheduled.
- **ARCH-5 — duplicated client-side policies.** `ui/web_new_v2/js/home.js:16-25` `applyCoverBackground` re-implements the `safeCssImageUrl` policy that already exists in `ui/web_new_v2/js/utils.js:40-50`, with a weaker character-stripping rule. Two divergent copies of a security decision is how the weaker one becomes the default. *Direction:* import `safeCssImageUrl` from `utils.js` (the two are equivalent today, so the change is behaviour-preserving).
- **ARCH-6 — leaky DTOs at the bridge boundary.** `get_home_data` returns raw DB history rows and patches `h["id"] = h["track_id"]` (`core/api.py:3296-3298`); the consumers then re-patch the same thing (`ui/web_new_v2/js/home-shell.js:33` and `:56` both do `id: track.track_id || track.id`). `get_popular_tracks`'s fallback path emits a *different* row shape from its normal path (F-WN-09-5). *Direction:* one normalisation function per feed, applied to every path, so the frontend stops needing to know which backend branch produced the payload.
- **ARCH-7 — dead bridge surface is still maintained and intercepted.** `get_authentic_home_feed` (F-WN-09-8), `get_recommendations` (F-WN-09-9), plus `RecommendationService.get_authentic_home` / `get_smart_home_feed` (`services/recommendation_service.py:719, 868`) have no UI caller, yet each has an event handler, an offline-interception entry and (for the recommendation service) a test. *Direction:* delete the unreachable surface, or make it reachable — the current state is the worst of both.
- **ARCH-8 — the lyrics of whatever the user is playing are sent to a third party on demand.** `get_lyrics_translation` (`core/api.py:3286-3291`) posts the full lyric text to `translate.googleapis.com` (`services/lyrics_service.py:264`) in up to 10 chunks. The text itself is public song lyrics, but the *request* reveals what is currently playing, and the endpoint is unauthenticated and rate-limited. *Direction:* if the translation feature stays, make the endpoint (and the privacy implication) explicit in the settings UI; a local translation model would remove the dependency.
